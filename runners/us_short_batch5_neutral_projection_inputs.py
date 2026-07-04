from __future__ import annotations

import argparse
import json
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
from engine.us_short_seam_momentum import DISPOSITION_ABSENT  # noqa: E402
from engine.us_short_seam_theme import DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402


SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_neutral_projection_inputs_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_neutral_projection_inputs_summary_20260704.json"
SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_neutral_projection_inputs_20260704")
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260706.json"
DEFAULT_MOMENTUM_PROJECTION_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_neutral_projection_inputs_20260704_momentum.json"
)
DEFAULT_THEME_PROJECTION_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_neutral_projection_inputs_20260704_theme.json"
)
MAX_SYMBOLS = 3


class NeutralProjectionInputsError(ValueError):
    """Local neutral momentum/theme projection inputs cannot be generated safely."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(path)


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
        raise NeutralProjectionInputsError(f"{field} must stay under the repository root") from exc
    return resolved


def _existing_file(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    if not resolved.exists() or not resolved.is_file():
        raise NeutralProjectionInputsError(f"{field} must be an existing file: {_display_path(resolved)}")
    return resolved


def _git_ignored(path: Path) -> bool:
    rel = _repo_rel(path)
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", rel],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _validate_state_json_path(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise NeutralProjectionInputsError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise NeutralProjectionInputsError(f"{field} must be a .json path")
    if not _git_ignored(resolved):
        raise NeutralProjectionInputsError(f"{field} must be gitignored")
    return resolved


def _validate_summary_path(path: Path | str) -> Path:
    resolved = _resolve_repo_path(path, field="summary_path")
    if resolved.suffix != ".json":
        raise NeutralProjectionInputsError("summary_path must be a .json path")
    if resolved == SUMMARY_PATH.resolve():
        return resolved
    try:
        resolved.relative_to((ROOT / SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise NeutralProjectionInputsError(
            "summary_path must be the canonical tracked summary or under this runner's provider_samples folder"
        ) from exc
    if not _git_ignored(resolved):
        raise NeutralProjectionInputsError("non-canonical summary_path must be gitignored")
    return resolved


def _valid_observed_at(value: str) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _date8_to_ymd(value: str) -> str:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise NeutralProjectionInputsError("expected_decision_date must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise NeutralProjectionInputsError("expected_decision_date must be a real calendar date") from exc


def _selected_symbols(symbols: list[str] | tuple[str, ...]) -> list[str]:
    if type(symbols) not in (list, tuple) or not symbols:
        raise NeutralProjectionInputsError("selected_symbols must be a non-empty list/tuple")
    if len(symbols) > MAX_SYMBOLS:
        raise NeutralProjectionInputsError(f"selected_symbols may contain at most {MAX_SYMBOLS} tickers")
    out: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        if type(raw) is not str:
            raise NeutralProjectionInputsError("selected_symbols must contain exact strings")
        ticker = canonical_us_ticker(raw)
        if ticker is None:
            raise NeutralProjectionInputsError("selected_symbols must be canonicalizable US tickers")
        if ticker in seen:
            raise NeutralProjectionInputsError(f"duplicate selected symbol: {ticker}")
        seen.add(ticker)
        out.append(ticker)
    return out


def _validated_candidate_context(
    *,
    candidate_artifact_path: Path,
    expected_decision_date: str,
    selected_symbols: list[str],
) -> dict[str, Any]:
    artifact = _read_json(candidate_artifact_path)
    eligibility_governance = load_eligibility_governance(ELIGIBILITY_GOVERNANCE_PATH)
    try:
        universe_fetch.validate_candidate_artifact(
            artifact,
            expected_decision_date=expected_decision_date,
            governance=eligibility_governance,
        )
    except Exception as exc:
        raise NeutralProjectionInputsError(f"candidate artifact failed validation: {exc}") from exc

    rows_by_ticker = {row["ticker"]: row for row in artifact["rows"]}
    eligible = set(artifact["eligible_tickers"])
    missing = [ticker for ticker in selected_symbols if ticker not in rows_by_ticker]
    not_eligible = [ticker for ticker in selected_symbols if ticker not in eligible]
    if missing or not_eligible:
        raise NeutralProjectionInputsError(
            f"selected_symbols must exist and be Pass1-eligible (missing {missing}, not_eligible {not_eligible})"
        )
    return {
        "decision_date": artifact["decision_date"],
        "price_basis_date": artifact["price_basis_date"],
        "eligible_count": len(artifact["eligible_tickers"]),
        "row_count": len(artifact["rows"]),
    }


def _neutral_momentum_projection(symbols: list[str]) -> dict[str, Any]:
    return {
        "momentum_by_ticker": {},
        "neutral_fill_tickers": list(symbols),
        "coverage": {ticker: DISPOSITION_ABSENT for ticker in symbols},
        "target_count": len(symbols),
        "scored_count": 0,
    }


def _neutral_theme_projection(symbols: list[str]) -> dict[str, Any]:
    return {
        "theme_block_by_ticker": {},
        "neutral_fill_tickers": list(symbols),
        "coverage": {
            ticker: DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE
            for ticker in symbols
        },
        "target_count": len(symbols),
        "scored_count": 0,
    }


def _prepare_context(
    *,
    candidate_artifact_path: Path,
    expected_decision_date: str,
    selected_symbols: list[str],
    momentum_projection_path: Path,
    theme_projection_path: Path,
    summary_path: Path,
    generated_at: str | None,
) -> dict[str, Any]:
    generated_at = generated_at or iso_now()
    if not _valid_observed_at(generated_at):
        raise NeutralProjectionInputsError("generated_at must be a timezone-aware RFC3339 instant")
    _date8_to_ymd(expected_decision_date)
    symbols = _selected_symbols(selected_symbols)
    candidate_path = _existing_file(candidate_artifact_path, field="candidate_artifact_path")
    momentum_path = _validate_state_json_path(momentum_projection_path, field="momentum_projection_path")
    theme_path = _validate_state_json_path(theme_projection_path, field="theme_projection_path")
    summary_resolved = _validate_summary_path(summary_path)
    if momentum_path == theme_path:
        raise NeutralProjectionInputsError("momentum_projection_path and theme_projection_path must be distinct")
    if candidate_path in {momentum_path, theme_path}:
        raise NeutralProjectionInputsError("projection outputs must not overwrite candidate_artifact_path")
    candidate_context = _validated_candidate_context(
        candidate_artifact_path=candidate_path,
        expected_decision_date=expected_decision_date,
        selected_symbols=symbols,
    )
    return {
        "generated_at": generated_at,
        "expected_decision_date": expected_decision_date,
        "source_as_of": _date8_to_ymd(expected_decision_date),
        "symbols": symbols,
        "candidate_path": candidate_path,
        "momentum_path": momentum_path,
        "theme_path": theme_path,
        "summary_path": summary_resolved,
        "candidate_context": candidate_context,
    }


def _build_summary(*, context: dict[str, Any]) -> dict[str, Any]:
    summary_path = context["summary_path"]
    momentum_path = context["momentum_path"]
    theme_path = context["theme_path"]
    symbols = context["symbols"]
    return {
        "schema_name": "us_short_batch5_neutral_projection_inputs_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_neutral_projection_inputs_summary.schema.json",
        "generated_at": context["generated_at"],
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "neutral_missing_source_projection_inputs",
            "status": "neutral_projection_inputs_written",
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
            "expected_decision_date": context["expected_decision_date"],
            "source_as_of": context["source_as_of"],
        },
        "sample_universe": {
            "symbol_source": "caller_selected_from_validated_candidate_artifact",
            "symbols": symbols,
            "max_symbols": MAX_SYMBOLS,
            "full_market_sample": False,
            "candidate_artifact_row_count": context["candidate_context"]["row_count"],
            "candidate_artifact_eligible_count": context["candidate_context"]["eligible_count"],
        },
        "paths": {
            "candidate_artifact_path": _repo_rel(context["candidate_path"]),
            "momentum_projection_path": _repo_rel(momentum_path),
            "theme_projection_path": _repo_rel(theme_path),
            "summary_path": _repo_rel(summary_path),
        },
        "storage": {
            "projection_paths_gitignored": _git_ignored(momentum_path) and _git_ignored(theme_path),
            "summary_path_gitignored": _git_ignored(summary_path),
            "summary_contains_raw_rows": False,
            "summary_contains_raw_payload": False,
            "summary_contains_request_urls": False,
            "summary_contains_secrets": False,
        },
        "projection_contract": {
            "momentum_disposition": DISPOSITION_ABSENT,
            "theme_disposition": DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE,
            "target_count": len(symbols),
            "momentum_scored_count": 0,
            "theme_scored_count": 0,
            "neutral_fill_only": True,
            "real_momentum_source_consumed": False,
            "real_theme_or_gics_source_consumed": False,
        },
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "paid_access_used": False,
            "live_momentum_source_evidence": False,
            "live_theme_source_evidence": False,
            "datahub_consumed": False,
            "production_readiness_claimed": False,
            "ship_gate_evidence_claimed": False,
            "live_normalized_evidence_claimed": False,
            "broker_or_order_execution_performed": False,
            "a_share_crossing_performed": False,
        },
        "limitations": [
            "This runner creates explicit neutral-fill projection inputs for missing momentum/theme sources.",
            "It does not fetch price history, GICS, theme membership, provider data, or full-market evidence.",
            "The generated projections are acceptable local inputs for the existing score composer, but they do not close live momentum/theme source artifacts.",
            "No provider selection, DataHub, production storage, broker/order execution, live-normalized, or ship-gate evidence is claimed.",
        ],
    }


def _preflight_result(*, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_name": "us_short_batch5_neutral_projection_inputs_preflight_result",
        "schema_version": "1.0.0",
        "generated_at": context["generated_at"],
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "preflight_status": "offline_preflight_passed",
            "network_access_required": False,
            "provider_calls_performed": False,
            "raw_payloads_read": False,
            "projection_files_written": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "preflight_checks": {
            "candidate_artifact_validated": True,
            "selected_symbols_pass1_eligible": True,
            "projection_outputs_gitignored": True,
            "summary_path_allowed": True,
            "no_provider_fetch": True,
            "no_datahub_or_production": True,
        },
        "paths": {
            "candidate_artifact_path": _repo_rel(context["candidate_path"]),
            "momentum_projection_path": _repo_rel(context["momentum_path"]),
            "theme_projection_path": _repo_rel(context["theme_path"]),
            "summary_path": _repo_rel(context["summary_path"]),
        },
        "projection_contract": {
            "symbols": context["symbols"],
            "target_count": len(context["symbols"]),
            "neutral_fill_only": True,
        },
    }


def _assert_text_safe(text: str) -> None:
    lower = text.lower()
    forbidden = (
        "apikey=",
        "financialmodelingprep.com",
        "api.massive.com",
        "data.sec.gov",
        "www.sec.gov",
        "\"payload\"",
        "\"request_url\"",
        "\"raw_payload\"",
    )
    for fragment in forbidden:
        if fragment in lower:
            raise NeutralProjectionInputsError(f"summary contains forbidden fragment: {fragment}")


def _validate_summary_against_schema(summary: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise NeutralProjectionInputsError("jsonschema is required for summary validation") from exc
    schema = _read_json(SUMMARY_SCHEMA_PATH)
    errors = sorted(Draft7Validator(schema).iter_errors(summary), key=lambda error: list(error.path))
    if errors:
        raise NeutralProjectionInputsError(
            "neutral projection-input summary failed schema validation: "
            + "; ".join(error.message for error in errors[:5])
        )


def _write_summary_validated(summary: dict[str, Any], summary_path: Path) -> None:
    _validate_summary_against_schema(summary)
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text)
    _write_json_atomic(summary, summary_path)


def run_preflight(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    expected_decision_date: str,
    selected_symbols: list[str],
    momentum_projection_path: Path = DEFAULT_MOMENTUM_PROJECTION_PATH,
    theme_projection_path: Path = DEFAULT_THEME_PROJECTION_PATH,
    summary_path: Path = SUMMARY_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    context = _prepare_context(
        candidate_artifact_path=candidate_artifact_path,
        expected_decision_date=expected_decision_date,
        selected_symbols=selected_symbols,
        momentum_projection_path=momentum_projection_path,
        theme_projection_path=theme_projection_path,
        summary_path=summary_path,
        generated_at=generated_at,
    )
    return _preflight_result(context=context)


def run_packet(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    expected_decision_date: str,
    selected_symbols: list[str],
    momentum_projection_path: Path = DEFAULT_MOMENTUM_PROJECTION_PATH,
    theme_projection_path: Path = DEFAULT_THEME_PROJECTION_PATH,
    summary_path: Path = SUMMARY_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    context = _prepare_context(
        candidate_artifact_path=candidate_artifact_path,
        expected_decision_date=expected_decision_date,
        selected_symbols=selected_symbols,
        momentum_projection_path=momentum_projection_path,
        theme_projection_path=theme_projection_path,
        summary_path=summary_path,
        generated_at=generated_at,
    )
    summary = _build_summary(context=context)
    _validate_summary_against_schema(summary)
    _assert_text_safe(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    _write_json_atomic(_neutral_momentum_projection(context["symbols"]), context["momentum_path"])
    _write_json_atomic(_neutral_theme_projection(context["symbols"]), context["theme_path"])
    _write_summary_validated(summary, context["summary_path"])
    return summary


def _parse_symbols(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate local neutral-fill US-short Batch5 momentum/theme projection inputs from an existing "
            "validated candidate artifact. This runner never fetches providers or claims live evidence."
        )
    )
    parser.add_argument("--candidate-artifact-path", type=Path, default=DEFAULT_CANDIDATE_ARTIFACT_PATH)
    parser.add_argument("--decision-date", required=True, help="Expected decision date as YYYYMMDD.")
    parser.add_argument("--symbols", default="AAPL,MSFT,JPM", help="Comma-separated <=3 Pass1-eligible tickers.")
    parser.add_argument("--momentum-projection-path", type=Path, default=DEFAULT_MOMENTUM_PROJECTION_PATH)
    parser.add_argument("--theme-projection-path", type=Path, default=DEFAULT_THEME_PROJECTION_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--generated-at")
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    kwargs = {
        "candidate_artifact_path": args.candidate_artifact_path,
        "expected_decision_date": args.decision_date,
        "selected_symbols": _parse_symbols(args.symbols),
        "momentum_projection_path": args.momentum_projection_path,
        "theme_projection_path": args.theme_projection_path,
        "summary_path": args.summary_path,
        "generated_at": args.generated_at,
    }
    result = run_preflight(**kwargs) if args.preflight_only else run_packet(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
