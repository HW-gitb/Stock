from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_eligibility_gate import canonical_us_ticker, load_eligibility_governance  # noqa: E402
from engine.us_short_projection_binding import (  # noqa: E402
    build_projection_binding,
    validate_projection_binding,
)
from engine.us_short_seam_momentum import (  # noqa: E402
    COVERAGE_DISPOSITIONS as MOMENTUM_COVERAGE_DISPOSITIONS,
    DISPOSITION_ABSENT,
)
from engine.us_short_seam_theme import (  # noqa: E402
    COVERAGE_DISPOSITIONS as THEME_COVERAGE_DISPOSITIONS,
    DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE,
)
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402


SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_candidate_projection_inputs_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_full_candidate_projection_inputs_summary_20260706.json"
SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_full_candidate_projection_inputs_20260706")
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260706.json"
DEFAULT_SOURCE_MOMENTUM_PROJECTION_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_momentum_price_source_20260705_momentum.json"
)
DEFAULT_SOURCE_THEME_PROJECTION_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_theme_source_20260705_theme.json"
)
DEFAULT_OUTPUT_MOMENTUM_PROJECTION_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_full_candidate_projection_inputs_20260706_momentum.json"
)
DEFAULT_OUTPUT_THEME_PROJECTION_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_full_candidate_projection_inputs_20260706_theme.json"
)


class FullCandidateProjectionInputsError(ValueError):
    """Full-candidate local score projection inputs cannot be assembled safely."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json_atomic(payload: Any, path: Path, *, field: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_dir():
        raise FullCandidateProjectionInputsError(f"{field} must be a file path")
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise FullCandidateProjectionInputsError(f"{field} could not be written atomically") from exc


def _repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _display_path(path: Path) -> str:
    try:
        return _repo_rel(path)
    except ValueError:
        return str(path)


def _resolve_repo_path(path: Path | str, *, field: str) -> Path:
    raw = Path(path)
    resolved = raw.resolve() if raw.is_absolute() else (ROOT / raw).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise FullCandidateProjectionInputsError(f"{field} must stay under the repository root") from exc
    return resolved


def _git_ignored(path: Path) -> bool:
    rel = _repo_rel(path)
    result = subprocess.run(
        ["git", "-c", "core.excludesFile=", "check-ignore", "-q", "--", rel],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _existing_state_json(path: Path | str, *, field: str) -> Path:
    resolved = _state_json_path(path, field=field)
    if not resolved.exists() or not resolved.is_file():
        raise FullCandidateProjectionInputsError(f"{field} must be an existing file: {_display_path(resolved)}")
    return resolved


def _state_json_path(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise FullCandidateProjectionInputsError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise FullCandidateProjectionInputsError(f"{field} must be a .json file")
    if not _git_ignored(resolved):
        raise FullCandidateProjectionInputsError(f"{field} must be gitignored")
    return resolved


def _validate_summary_path(path: Path | str) -> Path:
    resolved = _resolve_repo_path(path, field="summary_path")
    if resolved.suffix != ".json":
        raise FullCandidateProjectionInputsError("summary_path must be a .json file")
    if resolved == SUMMARY_PATH.resolve():
        return resolved
    try:
        resolved.relative_to((ROOT / SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise FullCandidateProjectionInputsError(
            "summary_path must be the canonical tracked summary or under this runner's provider_samples folder"
        ) from exc
    if not _git_ignored(resolved):
        raise FullCandidateProjectionInputsError("non-canonical summary_path must be gitignored")
    return resolved


def _valid_observed_at(value: str) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _date8_to_ymd(value: Any, *, field: str) -> str:
    if not (type(value) is str and len(value) == 8 and value.isascii() and value.isdigit()):
        raise FullCandidateProjectionInputsError(f"{field} must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise FullCandidateProjectionInputsError(f"{field} must be a real calendar date") from exc


def _finite_score(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FullCandidateProjectionInputsError(f"{field} must be a finite numeric score")
    try:
        out = float(value)
    except (OverflowError, ValueError) as exc:
        raise FullCandidateProjectionInputsError(f"{field} must be a finite numeric score") from exc
    if not math.isfinite(out) or out < 0.0 or out > 100.0:
        raise FullCandidateProjectionInputsError(f"{field} must be in [0, 100]")
    return out


def _canonical_ticker(raw: Any, *, field: str) -> str:
    if type(raw) is not str:
        raise FullCandidateProjectionInputsError(f"{field} must contain exact ticker strings")
    ticker = canonical_us_ticker(raw)
    if ticker is None:
        raise FullCandidateProjectionInputsError(f"{field} must contain canonicalizable US tickers")
    return ticker


def _canonical_score_map(raw: Any, *, field: str) -> dict[str, float]:
    if type(raw) is not dict:
        raise FullCandidateProjectionInputsError(f"{field} must be an exact dict")
    out: dict[str, float] = {}
    for raw_ticker, raw_score in raw.items():
        ticker = _canonical_ticker(raw_ticker, field=field)
        if ticker in out:
            raise FullCandidateProjectionInputsError(f"{field} contains duplicate canonical ticker: {ticker}")
        out[ticker] = _finite_score(raw_score, field=f"{field}[{ticker}]")
    return out


def _canonical_ticker_list(raw: Any, *, field: str) -> list[str]:
    if type(raw) is not list:
        raise FullCandidateProjectionInputsError(f"{field} must be an exact list")
    out: list[str] = []
    seen: set[str] = set()
    for raw_ticker in raw:
        ticker = _canonical_ticker(raw_ticker, field=field)
        if ticker in seen:
            raise FullCandidateProjectionInputsError(f"{field} contains duplicate canonical ticker: {ticker}")
        seen.add(ticker)
        out.append(ticker)
    return out


def _canonical_coverage(raw: Any, *, field: str, allowed_dispositions: set[str] | frozenset[str] | tuple[str, ...]) -> dict[str, str]:
    if type(raw) is not dict:
        raise FullCandidateProjectionInputsError(f"{field} must be an exact dict")
    allowed = set(allowed_dispositions)
    out: dict[str, str] = {}
    for raw_ticker, raw_disposition in raw.items():
        ticker = _canonical_ticker(raw_ticker, field=field)
        if ticker in out:
            raise FullCandidateProjectionInputsError(f"{field} contains duplicate canonical ticker: {ticker}")
        if type(raw_disposition) is not str:
            raise FullCandidateProjectionInputsError(f"{field}[{ticker}] disposition must be an exact string")
        if raw_disposition not in allowed:
            raise FullCandidateProjectionInputsError(f"{field}[{ticker}] disposition drifted from component contract")
        out[ticker] = raw_disposition
    return out


def _exact_int(value: Any, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise FullCandidateProjectionInputsError(f"{field} must be a non-negative exact int")
    return value


def _load_candidate_artifact(
    *,
    candidate_artifact_path: Path,
    expected_decision_date: str,
) -> dict[str, Any]:
    artifact = _read_json(candidate_artifact_path)
    governance = load_eligibility_governance(ELIGIBILITY_GOVERNANCE_PATH)
    try:
        validated = universe_fetch.validate_candidate_artifact(
            artifact,
            expected_decision_date=expected_decision_date,
            governance=governance,
        )
    except Exception as exc:
        raise FullCandidateProjectionInputsError(f"candidate artifact failed validation: {exc}") from exc
    _date8_to_ymd(validated["price_basis_date"], field="candidate.price_basis_date")
    return validated


def _source_projection_partition(
    projection: Any,
    *,
    component: str,
    value_key: str,
    allowed_dispositions: set[str] | frozenset[str] | tuple[str, ...],
) -> dict[str, Any]:
    if type(projection) is not dict:
        raise FullCandidateProjectionInputsError(f"{component}_projection must be an exact dict")
    expected_keys = {
        value_key, "neutral_fill_tickers", "coverage", "target_count", "scored_count", "source_binding"
    }
    if set(projection) != expected_keys:
        raise FullCandidateProjectionInputsError(f"{component}_projection keys drifted from composer contract")
    values = _canonical_score_map(projection[value_key], field=f"{component}.{value_key}")
    neutral = _canonical_ticker_list(projection["neutral_fill_tickers"], field=f"{component}.neutral_fill_tickers")
    coverage = _canonical_coverage(
        projection["coverage"],
        field=f"{component}.coverage",
        allowed_dispositions=allowed_dispositions,
    )
    value_set = set(values)
    neutral_set = set(neutral)
    if value_set & neutral_set:
        raise FullCandidateProjectionInputsError(f"{component} source projection has scored/neutral overlap")
    partition = value_set | neutral_set
    if set(coverage) != partition:
        raise FullCandidateProjectionInputsError(f"{component} source coverage must match scored+neutral partition")
    if _exact_int(projection["target_count"], field=f"{component}.target_count") != len(partition):
        raise FullCandidateProjectionInputsError(f"{component}.target_count must equal source partition count")
    if _exact_int(projection["scored_count"], field=f"{component}.scored_count") != len(values):
        raise FullCandidateProjectionInputsError(f"{component}.scored_count must equal scored value count")
    return {"values": values, "neutral": neutral, "coverage": coverage, "partition": partition}


def _merge_projection(
    *,
    expected_tickers: list[str],
    source_projection: Any,
    component: str,
    value_key: str,
    allowed_dispositions: set[str] | frozenset[str] | tuple[str, ...],
    missing_disposition: str,
    expected_decision_date: str,
    candidate_price_basis_date: str,
    source_as_of: str,
) -> tuple[dict[str, Any], dict[str, int]]:
    parsed = _source_projection_partition(
        source_projection,
        component=component,
        value_key=value_key,
        allowed_dispositions=allowed_dispositions,
    )
    try:
        validate_projection_binding(
            source_projection,
            component=component,
            expected_decision_date=expected_decision_date,
            candidate_price_basis_date=candidate_price_basis_date,
            source_as_of=source_as_of,
            target_tickers=parsed["partition"],
        )
    except ValueError as exc:
        raise FullCandidateProjectionInputsError(f"{component} projection source binding rejected: {exc}") from exc
    expected_set = set(expected_tickers)
    stale = sorted(parsed["partition"] - expected_set)
    if stale:
        raise FullCandidateProjectionInputsError(f"{component} source projection contains stale tickers: {stale[:10]}")
    missing = [ticker for ticker in expected_tickers if ticker not in parsed["partition"]]
    values = {ticker: parsed["values"][ticker] for ticker in expected_tickers if ticker in parsed["values"]}
    neutral = [
        ticker
        for ticker in expected_tickers
        if ticker in set(parsed["neutral"]) or ticker in missing
    ]
    coverage = {}
    for ticker in expected_tickers:
        if ticker in parsed["coverage"]:
            coverage[ticker] = parsed["coverage"][ticker]
        else:
            coverage[ticker] = missing_disposition
    return (
        {
            value_key: values,
            "neutral_fill_tickers": neutral,
            "coverage": coverage,
            "target_count": len(expected_tickers),
            "scored_count": len(values),
        },
        {
            "source_scored_count": len(parsed["values"]),
            "source_neutral_fill_count": len(parsed["neutral"]),
        },
    )


def _validate_summary_against_schema(summary: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise FullCandidateProjectionInputsError("jsonschema is required for summary validation") from exc
    schema = _read_json(SUMMARY_SCHEMA_PATH)
    errors = sorted(Draft7Validator(schema).iter_errors(summary), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise FullCandidateProjectionInputsError(
            f"full-candidate projection-input summary failed schema validation: {joined}"
        ) from errors[0]


def _assert_text_safe(text: str) -> None:
    lower = text.lower()
    forbidden = (
        "apikey=",
        "financialmodelingprep.com",
        "api.massive.com",
        "data.sec.gov",
        "www.sec.gov",
        "http://",
        "https://",
        "\"payload\"",
        "\"raw_payload\"",
        "\"request_url\"",
        "\"points\"",
        "\"results\"",
        "bearer ",
        "token=",
    )
    for fragment in forbidden:
        if fragment in lower:
            raise FullCandidateProjectionInputsError(f"tracked summary contains forbidden fragment: {fragment}")


def _build_summary(
    *,
    generated_at: str,
    expected_decision_date: str,
    candidate_path: Path,
    source_momentum_path: Path,
    source_theme_path: Path,
    output_momentum_path: Path,
    output_theme_path: Path,
    summary_path: Path,
    artifact: dict[str, Any],
    momentum_projection: dict[str, Any],
    theme_projection: dict[str, Any],
    momentum_source_stats: dict[str, int],
    theme_source_stats: dict[str, int],
) -> dict[str, Any]:
    eligible = list(artifact["eligible_tickers"])
    return {
        "schema_name": "us_short_batch5_full_candidate_projection_inputs_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_full_candidate_projection_inputs_summary.schema.json",
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "full_candidate_local_score_projection_inputs",
            "status": "full_candidate_projection_inputs_written",
            "network_access_performed": False,
            "provider_calls_performed": False,
            "raw_payload_storage_performed": False,
            "momentum_projection_written": True,
            "theme_projection_written": True,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "full_market_call_performed": False,
            "yfinance_consumption_performed": False,
            "broker_or_order_execution_performed": False,
            "ship_gate_or_live_normalized_evidence_claimed": False,
            "a_share_crossing_performed": False,
        },
        "decision_clock": {
            "expected_decision_date": expected_decision_date,
            "candidate_price_basis_date": artifact["price_basis_date"],
            "price_basis_date": _date8_to_ymd(artifact["price_basis_date"], field="candidate.price_basis_date"),
            "used_date": artifact["used_date"],
        },
        "candidate_universe": {
            "candidate_artifact_path": _repo_rel(candidate_path),
            "candidate_artifact_path_gitignored": _git_ignored(candidate_path),
            "row_count": len(artifact["rows"]),
            "eligible_count": len(eligible),
            "symbol_scope": "full_pass1_eligible_candidate_set",
            "full_market_sample": False,
        },
        "source_inputs": {
            "source_momentum_projection_path": _repo_rel(source_momentum_path),
            "source_theme_projection_path": _repo_rel(source_theme_path),
            "source_momentum_scored_count": momentum_source_stats["source_scored_count"],
            "source_theme_scored_count": theme_source_stats["source_scored_count"],
            "source_momentum_neutral_fill_count": momentum_source_stats["source_neutral_fill_count"],
            "source_theme_neutral_fill_count": theme_source_stats["source_neutral_fill_count"],
            "real_momentum_source_consumed": momentum_source_stats["source_scored_count"] > 0,
            "real_theme_or_gics_source_consumed": theme_source_stats["source_scored_count"] > 0,
        },
        "output_projection_contract": {
            "target_count": len(eligible),
            "momentum_scored_count": momentum_projection["scored_count"],
            "theme_scored_count": theme_projection["scored_count"],
            "momentum_neutral_fill_count": len(momentum_projection["neutral_fill_tickers"]),
            "theme_neutral_fill_count": len(theme_projection["neutral_fill_tickers"]),
            "coverage_exactly_matches_full_candidate_set": True,
            "neutral_fill_only_for_missing_source_inputs": True,
            "full_candidate_local_inputs_ready": True,
            "live_momentum_source_evidence_for_all_candidates": momentum_projection["scored_count"] == len(eligible),
            "live_theme_source_evidence_for_all_candidates": theme_projection["scored_count"] == len(eligible),
        },
        "paths": {
            "output_momentum_projection_path": _repo_rel(output_momentum_path),
            "output_theme_projection_path": _repo_rel(output_theme_path),
            "summary_path": _repo_rel(summary_path),
        },
        "storage": {
            "projection_paths_gitignored": _git_ignored(output_momentum_path) and _git_ignored(output_theme_path),
            "summary_contains_raw_rows": False,
            "summary_contains_raw_payload": False,
            "summary_contains_request_urls": False,
            "summary_contains_secrets": False,
        },
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "paid_access_used": False,
            "datahub_consumed": False,
            "production_readiness_claimed": False,
            "ship_gate_evidence_claimed": False,
            "live_normalized_evidence_claimed": False,
            "broker_or_order_execution_performed": False,
            "a_share_crossing_performed": False,
        },
        "limitations": [
            "This runner only merges existing local projections with explicit neutral-fill entries for missing candidates.",
            "Neutral-filled candidates have local score inputs but no live momentum/theme source evidence from this runner.",
            "The output is a local prerequisite for the reviewed full-candidate Pass2 preflight; it does not execute provider calls or write a source packet.",
            "Provider selection, DataHub, production storage, broker/order execution, live-normalized, and ship-gate evidence remain out of scope.",
        ],
    }


def _write_summary_validated(summary: dict[str, Any], summary_path: Path) -> None:
    _validate_summary_against_schema(summary)
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text)
    _write_json_atomic(summary, summary_path, field="summary_path")


def run_packet(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    expected_decision_date: str,
    source_momentum_projection_path: Path = DEFAULT_SOURCE_MOMENTUM_PROJECTION_PATH,
    source_theme_projection_path: Path = DEFAULT_SOURCE_THEME_PROJECTION_PATH,
    output_momentum_projection_path: Path = DEFAULT_OUTPUT_MOMENTUM_PROJECTION_PATH,
    output_theme_projection_path: Path = DEFAULT_OUTPUT_THEME_PROJECTION_PATH,
    summary_path: Path = SUMMARY_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or iso_now()
    if not _valid_observed_at(generated_at):
        raise FullCandidateProjectionInputsError("generated_at must be a timezone-aware RFC3339 instant")
    _date8_to_ymd(expected_decision_date, field="expected_decision_date")
    candidate_path = _existing_state_json(candidate_artifact_path, field="candidate_artifact_path")
    source_momentum_path = _existing_state_json(
        source_momentum_projection_path,
        field="source_momentum_projection_path",
    )
    source_theme_path = _existing_state_json(source_theme_projection_path, field="source_theme_projection_path")
    output_momentum_path = _state_json_path(output_momentum_projection_path, field="output_momentum_projection_path")
    output_theme_path = _state_json_path(output_theme_projection_path, field="output_theme_projection_path")
    summary_resolved = _validate_summary_path(summary_path)
    if len({candidate_path, source_momentum_path, source_theme_path, output_momentum_path, output_theme_path}) != 5:
        raise FullCandidateProjectionInputsError("input and output projection paths must be distinct")

    artifact = _load_candidate_artifact(
        candidate_artifact_path=candidate_path,
        expected_decision_date=expected_decision_date,
    )
    eligible = list(artifact["eligible_tickers"])
    momentum_projection, momentum_source_stats = _merge_projection(
        expected_tickers=eligible,
        source_projection=_read_json(source_momentum_path),
        component="momentum",
        value_key="momentum_by_ticker",
        allowed_dispositions=MOMENTUM_COVERAGE_DISPOSITIONS,
        missing_disposition=DISPOSITION_ABSENT,
        expected_decision_date=expected_decision_date,
        candidate_price_basis_date=artifact["price_basis_date"],
        source_as_of=artifact["used_date"],
    )
    theme_projection, theme_source_stats = _merge_projection(
        expected_tickers=eligible,
        source_projection=_read_json(source_theme_path),
        component="theme",
        value_key="theme_block_by_ticker",
        allowed_dispositions=THEME_COVERAGE_DISPOSITIONS,
        missing_disposition=DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE,
        expected_decision_date=expected_decision_date,
        candidate_price_basis_date=artifact["price_basis_date"],
        source_as_of=artifact["used_date"],
    )
    momentum_projection["source_binding"] = build_projection_binding(
        component="momentum",
        generated_at=generated_at,
        expected_decision_date=expected_decision_date,
        candidate_price_basis_date=artifact["price_basis_date"],
        source_as_of=artifact["used_date"],
        target_tickers=eligible,
        source_artifact_paths={
            "candidate_artifact": candidate_path,
            "source_momentum_projection": source_momentum_path,
        },
    )
    theme_projection["source_binding"] = build_projection_binding(
        component="theme",
        generated_at=generated_at,
        expected_decision_date=expected_decision_date,
        candidate_price_basis_date=artifact["price_basis_date"],
        source_as_of=artifact["used_date"],
        target_tickers=eligible,
        source_artifact_paths={
            "candidate_artifact": candidate_path,
            "source_theme_projection": source_theme_path,
        },
    )
    summary = _build_summary(
        generated_at=generated_at,
        expected_decision_date=expected_decision_date,
        candidate_path=candidate_path,
        source_momentum_path=source_momentum_path,
        source_theme_path=source_theme_path,
        output_momentum_path=output_momentum_path,
        output_theme_path=output_theme_path,
        summary_path=summary_resolved,
        artifact=artifact,
        momentum_projection=momentum_projection,
        theme_projection=theme_projection,
        momentum_source_stats=momentum_source_stats,
        theme_source_stats=theme_source_stats,
    )
    _validate_summary_against_schema(summary)
    _assert_text_safe(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    _write_json_atomic(momentum_projection, output_momentum_path, field="output_momentum_projection_path")
    _write_json_atomic(theme_projection, output_theme_path, field="output_theme_projection_path")
    _write_summary_validated(summary, summary_resolved)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge existing local US-short Batch5 momentum/theme projections with explicit neutral-fill rows "
            "so the current full Pass1-eligible candidate set has honest local score projection inputs. "
            "This runner performs no provider calls and claims no live source evidence for neutral-filled rows."
        )
    )
    parser.add_argument("--candidate-artifact-path", type=Path, default=DEFAULT_CANDIDATE_ARTIFACT_PATH)
    parser.add_argument("--decision-date", required=True, help="Expected decision date as YYYYMMDD.")
    parser.add_argument("--source-momentum-projection-path", type=Path, default=DEFAULT_SOURCE_MOMENTUM_PROJECTION_PATH)
    parser.add_argument("--source-theme-projection-path", type=Path, default=DEFAULT_SOURCE_THEME_PROJECTION_PATH)
    parser.add_argument("--output-momentum-projection-path", type=Path, default=DEFAULT_OUTPUT_MOMENTUM_PROJECTION_PATH)
    parser.add_argument("--output-theme-projection-path", type=Path, default=DEFAULT_OUTPUT_THEME_PROJECTION_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--generated-at")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_packet(
        candidate_artifact_path=args.candidate_artifact_path,
        expected_decision_date=args.decision_date,
        source_momentum_projection_path=args.source_momentum_projection_path,
        source_theme_projection_path=args.source_theme_projection_path,
        output_momentum_projection_path=args.output_momentum_projection_path,
        output_theme_projection_path=args.output_theme_projection_path,
        summary_path=args.summary_path,
        generated_at=args.generated_at,
    )
    print(
        json.dumps(
            {
                "status": summary["scope"]["status"],
                "target_count": summary["output_projection_contract"]["target_count"],
                "momentum_scored_count": summary["output_projection_contract"]["momentum_scored_count"],
                "theme_scored_count": summary["output_projection_contract"]["theme_scored_count"],
                "summary_path": summary["paths"]["summary_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
