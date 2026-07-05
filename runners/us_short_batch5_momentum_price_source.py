from __future__ import annotations

import argparse
import json
import math
import re
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
from engine.us_short_momentum import compute_momentum_features, momentum_block  # noqa: E402
from engine.us_short_seam_momentum import project_momentum_block  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402


PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_momentum_price_source_packet.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_momentum_price_source_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_momentum_price_source_summary_20260705.json"
SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_momentum_price_source_20260705")
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260706.json"
DEFAULT_SOURCE_PACKET_PATH = STATE_US_SHORT_DIR / "us_short_batch5_momentum_price_source_20260705_packet.json"
DEFAULT_OUTPUT_PROJECTION_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_momentum_price_source_20260705_momentum.json"
)
BENCHMARK_SYMBOLS = ("SPY", "QQQ")
MAX_SYMBOLS = 3
SAFE_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class MomentumPriceSourceError(ValueError):
    """Local momentum price-history source packet cannot be consumed safely."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _prepare_json_target(path: Path, *, field: str) -> None:
    if path.parent.exists() and not path.parent.is_dir():
        raise MomentumPriceSourceError(f"{field} parent must be a directory: {_display_path(path.parent)}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MomentumPriceSourceError(f"{field} parent could not be created: {_display_path(path.parent)}") from exc
    if path.exists() and path.is_dir():
        raise MomentumPriceSourceError(f"{field} must be a file path, not a directory: {_display_path(path)}")


def _write_json_atomic(payload: Any, path: Path, *, field: str = "json output") -> None:
    _prepare_json_target(path, field=field)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise MomentumPriceSourceError(f"{field} could not be written atomically: {_display_path(path)}") from exc


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
        raise MomentumPriceSourceError(f"{field} must stay under the repository root") from exc
    return resolved


def _existing_file(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    if not resolved.exists() or not resolved.is_file():
        raise MomentumPriceSourceError(f"{field} must be an existing file: {_display_path(resolved)}")
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


def _validate_state_json_file(path: Path | str, *, field: str, must_exist: bool) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise MomentumPriceSourceError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise MomentumPriceSourceError(f"{field} must be a .json path")
    if must_exist and (not resolved.exists() or not resolved.is_file()):
        raise MomentumPriceSourceError(f"{field} must be an existing file: {_display_path(resolved)}")
    if not _git_ignored(resolved):
        raise MomentumPriceSourceError(f"{field} must be gitignored")
    return resolved


def _validate_summary_path(path: Path | str) -> Path:
    resolved = _resolve_repo_path(path, field="summary_path")
    if resolved.suffix != ".json":
        raise MomentumPriceSourceError("summary_path must be a .json path")
    if resolved == SUMMARY_PATH.resolve():
        return resolved
    try:
        resolved.relative_to((ROOT / SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise MomentumPriceSourceError(
            "summary_path must be the canonical tracked summary or under this runner's provider_samples folder"
        ) from exc
    if not _git_ignored(resolved):
        raise MomentumPriceSourceError("non-canonical summary_path must be gitignored")
    return resolved


def _valid_observed_at(value: str) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _valid_ymd(value: Any):
    if not (type(value) is str and len(value) == 10):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _compact_to_ymd(value: str, *, field: str) -> str:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise MomentumPriceSourceError(f"{field} must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise MomentumPriceSourceError(f"{field} must be a real calendar date") from exc


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        x = float(value)
    except (OverflowError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _safe_provider_id(value: Any, *, ticker: str) -> str:
    if type(value) is not str or SAFE_PROVIDER_ID_RE.fullmatch(value) is None:
        raise MomentumPriceSourceError(
            f"{ticker} provenance.provider_id must be a lowercase provider slug"
        )
    return value


def _validate_schema(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise MomentumPriceSourceError("jsonschema is required for momentum price-source validation") from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise MomentumPriceSourceError(f"{label} schema rejected {len(errors)} field(s): {joined}") from errors[0]


def _selected_symbols(value: list[str]) -> list[str]:
    if type(value) is not list or not value or len(value) > MAX_SYMBOLS:
        raise MomentumPriceSourceError("series_contract.selected_symbols must be a 1-3 item list")
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if type(raw) is not str:
            raise MomentumPriceSourceError("series_contract.selected_symbols must contain exact strings")
        ticker = canonical_us_ticker(raw)
        if ticker is None:
            raise MomentumPriceSourceError("selected_symbols must be canonicalizable US tickers")
        if ticker in seen:
            raise MomentumPriceSourceError(f"duplicate selected symbol: {ticker}")
        seen.add(ticker)
        out.append(ticker)
    return out


def _validated_candidate_context(
    *,
    candidate_artifact_path: Path,
    expected_decision_date: str,
    candidate_price_basis_date: str,
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
        raise MomentumPriceSourceError(f"candidate artifact failed validation: {exc}") from exc
    if artifact["price_basis_date"] != candidate_price_basis_date:
        raise MomentumPriceSourceError(
            "source packet candidate_price_basis_date must match the candidate artifact price_basis_date"
        )
    rows_by_ticker = {row["ticker"]: row for row in artifact["rows"]}
    eligible = set(artifact["eligible_tickers"])
    missing = [ticker for ticker in selected_symbols if ticker not in rows_by_ticker]
    not_eligible = [ticker for ticker in selected_symbols if ticker not in eligible]
    if missing or not_eligible:
        raise MomentumPriceSourceError(
            f"selected_symbols must exist and be Pass1-eligible (missing {missing}, not_eligible {not_eligible})"
        )
    return {
        "decision_date": artifact["decision_date"],
        "candidate_price_basis_date": artifact["price_basis_date"],
        "price_basis_date": _compact_to_ymd(artifact["price_basis_date"], field="candidate.price_basis_date"),
        "eligible_count": len(artifact["eligible_tickers"]),
        "row_count": len(artifact["rows"]),
    }


def _validate_series_values(
    *,
    ticker: str,
    series: dict[str, Any],
    expected_as_of: str,
    session: str,
    adjustment_mode: str,
    min_points: int,
) -> None:
    if series["as_of"] != expected_as_of:
        raise MomentumPriceSourceError(f"{ticker} series.as_of must equal the price_basis_date")
    if series["session"] != session:
        raise MomentumPriceSourceError(f"{ticker} series.session mismatch")
    if series["adjustment_mode"] != adjustment_mode:
        raise MomentumPriceSourceError(f"{ticker} series.adjustment_mode mismatch")
    as_of_date = _valid_ymd(expected_as_of)
    if as_of_date is None:
        raise MomentumPriceSourceError("price_basis_date must be YYYY-MM-DD")
    points = series["points"]
    if len(points) < min_points:
        raise MomentumPriceSourceError(f"{ticker} price series has fewer than {min_points} points")
    previous = None
    for point in points:
        date_value = _valid_ymd(point["date"])
        if date_value is None:
            raise MomentumPriceSourceError(f"{ticker} point.date must be YYYY-MM-DD")
        if previous is not None and date_value <= previous:
            raise MomentumPriceSourceError(f"{ticker} point dates must be strictly ascending")
        previous = date_value
        if date_value > as_of_date:
            raise MomentumPriceSourceError(f"{ticker} source packet contains a future price point")
        close = _finite_number(point["close"])
        if close is None or close <= 0.0:
            raise MomentumPriceSourceError(f"{ticker} point.close must be finite and positive")
        if "volume" in point and point["volume"] is not None:
            volume = _finite_number(point["volume"])
            if volume is None or volume < 0.0:
                raise MomentumPriceSourceError(f"{ticker} point.volume must be finite and non-negative")


def _validate_provenance(
    *,
    ticker: str,
    provenance: dict[str, Any],
    expected_as_of: str,
) -> None:
    _safe_provider_id(provenance["provider_id"], ticker=ticker)
    if provenance["source_as_of"] != expected_as_of:
        raise MomentumPriceSourceError(f"{ticker} provenance.source_as_of must equal price_basis_date")
    if not _valid_observed_at(provenance["observed_at"]):
        raise MomentumPriceSourceError(f"{ticker} provenance.observed_at must be timezone-aware")
    if provenance["coverage_status"] != "full" or provenance["parser_status"] != "ok":
        raise MomentumPriceSourceError(f"{ticker} price source provenance must be full/ok before scoring")


def _load_context(
    *,
    candidate_artifact_path: Path,
    source_packet_path: Path,
    output_projection_path: Path,
    summary_path: Path,
    generated_at: str | None,
) -> dict[str, Any]:
    generated_at = generated_at or iso_now()
    if not _valid_observed_at(generated_at):
        raise MomentumPriceSourceError("generated_at must be a timezone-aware RFC3339 instant")
    packet = _read_json(source_packet_path)
    _validate_schema(packet, PACKET_SCHEMA_PATH, label="momentum price source packet")
    selected = _selected_symbols(packet["series_contract"]["selected_symbols"])
    if tuple(packet["series_contract"]["benchmark_symbols"]) != BENCHMARK_SYMBOLS:
        raise MomentumPriceSourceError("benchmark_symbols must be exactly SPY/QQQ")

    expected_decision_date = packet["decision_clock"]["expected_decision_date"]
    candidate_price_basis_date = packet["decision_clock"]["candidate_price_basis_date"]
    price_basis_date = packet["decision_clock"]["price_basis_date"]
    source_as_of = packet["decision_clock"]["source_as_of"]
    if price_basis_date != source_as_of:
        raise MomentumPriceSourceError("decision_clock.price_basis_date and source_as_of must match")
    if _compact_to_ymd(candidate_price_basis_date, field="decision_clock.candidate_price_basis_date") != price_basis_date:
        raise MomentumPriceSourceError("candidate_price_basis_date must normalize to price_basis_date")
    candidate_context = _validated_candidate_context(
        candidate_artifact_path=candidate_artifact_path,
        expected_decision_date=expected_decision_date,
        candidate_price_basis_date=candidate_price_basis_date,
        selected_symbols=selected,
    )

    required_symbols = set(selected) | set(BENCHMARK_SYMBOLS)
    series_by_ticker = packet["series_by_ticker"]
    provenance_by_ticker = packet["provenance_by_ticker"]
    if set(series_by_ticker) != required_symbols:
        raise MomentumPriceSourceError("series_by_ticker must contain exactly selected_symbols plus SPY/QQQ")
    if set(provenance_by_ticker) != required_symbols:
        raise MomentumPriceSourceError("provenance_by_ticker must contain exactly selected_symbols plus SPY/QQQ")
    session = packet["series_contract"]["session"]
    adjustment_mode = packet["series_contract"]["adjustment_mode"]
    min_points = packet["series_contract"]["min_points_per_series"]
    for ticker in sorted(required_symbols):
        _validate_series_values(
            ticker=ticker,
            series=series_by_ticker[ticker],
            expected_as_of=price_basis_date,
            session=session,
            adjustment_mode=adjustment_mode,
            min_points=min_points,
        )
        _validate_provenance(
            ticker=ticker,
            provenance=provenance_by_ticker[ticker],
            expected_as_of=price_basis_date,
        )

    if output_projection_path in {candidate_artifact_path, source_packet_path}:
        raise MomentumPriceSourceError("output_projection_path must not overwrite input files")
    return {
        "generated_at": generated_at,
        "packet": packet,
        "selected_symbols": selected,
        "required_symbols": sorted(required_symbols),
        "candidate_context": candidate_context,
        "candidate_artifact_path": candidate_artifact_path,
        "source_packet_path": source_packet_path,
        "output_projection_path": output_projection_path,
        "summary_path": summary_path,
    }


def _build_projection(context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    packet = context["packet"]
    series_by_ticker = packet["series_by_ticker"]
    selected = context["selected_symbols"]
    spy_series = series_by_ticker["SPY"]
    qqq_series = series_by_ticker["QQQ"]
    features_by_ticker: dict[str, dict[str, float]] = {}
    details: dict[str, Any] = {}
    for ticker in selected:
        computed = compute_momentum_features(
            series_by_ticker[ticker],
            spy_series=spy_series,
            qqq_series=qqq_series,
        )
        features_by_ticker[ticker] = computed["features"]
        details[ticker] = {
            "n_features": computed["n_features"],
            "alignment": computed["alignment"],
            "pit": computed["pit"],
        }
    producer_result = momentum_block(features_by_ticker)
    projection = project_momentum_block(producer_result, selected)
    return projection, details


def _build_summary(
    *,
    context: dict[str, Any],
    projection: dict[str, Any],
    details: dict[str, Any],
) -> dict[str, Any]:
    packet = context["packet"]
    selected = context["selected_symbols"]
    provenance = packet["provenance_by_ticker"]
    provider_ids = sorted(
        {
            _safe_provider_id(provenance[ticker]["provider_id"], ticker=ticker)
            for ticker in context["required_symbols"]
        }
    )
    return {
        "schema_name": "us_short_batch5_momentum_price_source_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_momentum_price_source_summary.schema.json",
        "generated_at": context["generated_at"],
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "local_momentum_price_history_source_to_projection",
            "status": "momentum_projection_written",
            "network_access_performed_by_runner": False,
            "provider_calls_performed_by_runner": False,
            "raw_payload_storage_performed_by_runner": False,
            "source_packet_consumed": True,
            "momentum_projection_written": True,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "full_market_call_performed": False,
            "yfinance_consumption_performed": False,
            "broker_or_order_execution_performed": False,
            "ship_gate_or_live_normalized_evidence_claimed": False,
            "a_share_crossing_performed": False,
        },
        "decision_clock": dict(packet["decision_clock"]),
        "sample_universe": {
            "symbol_source": "caller_selected_from_validated_candidate_artifact",
            "symbols": selected,
            "max_symbols": MAX_SYMBOLS,
            "full_market_sample": False,
            "candidate_artifact_row_count": context["candidate_context"]["row_count"],
            "candidate_artifact_eligible_count": context["candidate_context"]["eligible_count"],
        },
        "paths": {
            "candidate_artifact_path": _repo_rel(context["candidate_artifact_path"]),
            "source_packet_path": _repo_rel(context["source_packet_path"]),
            "output_projection_path": _repo_rel(context["output_projection_path"]),
            "summary_path": _repo_rel(context["summary_path"]),
        },
        "storage": {
            "source_packet_path_gitignored": _git_ignored(context["source_packet_path"]),
            "output_projection_path_gitignored": _git_ignored(context["output_projection_path"]),
            "summary_path_gitignored": _git_ignored(context["summary_path"]),
            "summary_contains_price_rows": False,
            "summary_contains_raw_payload": False,
            "summary_contains_request_urls": False,
            "summary_contains_secrets": False,
        },
        "price_source": {
            "series_count": len(context["required_symbols"]),
            "selected_series_count": len(selected),
            "benchmark_symbols": list(BENCHMARK_SYMBOLS),
            "provider_ids": provider_ids,
            "session": packet["series_contract"]["session"],
            "adjustment_mode": packet["series_contract"]["adjustment_mode"],
            "min_points_per_series": packet["series_contract"]["min_points_per_series"],
            "feature_counts_by_ticker": {
                ticker: details[ticker]["n_features"]
                for ticker in selected
            },
            "alignment_notes_by_ticker": {
                ticker: details[ticker]["alignment"]
                for ticker in selected
            },
        },
        "projection_contract": {
            "target_count": projection["target_count"],
            "momentum_scored_count": projection["scored_count"],
            "neutral_fill_count": len(projection["neutral_fill_tickers"]),
            "real_momentum_price_source_consumed": True,
            "real_theme_or_gics_source_consumed": False,
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
            "This runner consumes an already-built local price-history source packet; it does not fetch provider endpoints.",
            "The tracked summary excludes price rows, raw payloads, request URLs, and secrets.",
            "This narrows the momentum price-history source wiring only; theme/GICS, provider health, DataHub, production, and ship-gate evidence remain out of scope.",
        ],
    }


def _assert_text_safe(text: str) -> None:
    lower = text.lower()
    forbidden = (
        "apikey=",
        "financialmodelingprep.com",
        "api.massive.com",
        "data.sec.gov",
        "www.sec.gov",
        "bearer ",
        "token=",
        "key=",
        "http://",
        "https://",
        "akia",
        "@",
        "\"payload\"",
        "\"raw_payload\"",
        "\"request_url\"",
        "\"points\"",
    )
    for fragment in forbidden:
        if fragment in lower:
            raise MomentumPriceSourceError(f"summary contains forbidden fragment: {fragment}")


def _write_summary_validated(summary: dict[str, Any], summary_path: Path) -> None:
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="momentum price source summary")
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text)
    _write_json_atomic(summary, summary_path, field="summary_path")


def run_preflight(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    source_packet_path: Path = DEFAULT_SOURCE_PACKET_PATH,
    output_projection_path: Path = DEFAULT_OUTPUT_PROJECTION_PATH,
    summary_path: Path = SUMMARY_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    candidate_path = _existing_file(candidate_artifact_path, field="candidate_artifact_path")
    source_path = _validate_state_json_file(source_packet_path, field="source_packet_path", must_exist=True)
    output_path = _validate_state_json_file(output_projection_path, field="output_projection_path", must_exist=False)
    summary_resolved = _validate_summary_path(summary_path)
    context = _load_context(
        candidate_artifact_path=candidate_path,
        source_packet_path=source_path,
        output_projection_path=output_path,
        summary_path=summary_resolved,
        generated_at=generated_at,
    )
    projection, details = _build_projection(context)
    return {
        "schema_name": "us_short_batch5_momentum_price_source_preflight_result",
        "schema_version": "1.0.0",
        "generated_at": context["generated_at"],
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "preflight_status": "offline_preflight_passed",
            "network_access_required": False,
            "provider_calls_performed_by_runner": False,
            "raw_payloads_read": False,
            "projection_file_written": False,
            "summary_file_written": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "preflight_checks": {
            "candidate_artifact_validated": True,
            "source_packet_schema_validated": True,
            "selected_symbols_pass1_eligible": True,
            "benchmarks_present": True,
            "projection_output_gitignored": True,
            "summary_path_allowed": True,
            "no_provider_fetch_by_runner": True,
            "no_datahub_or_production": True,
        },
        "projection_preview": {
            "target_count": projection["target_count"],
            "momentum_scored_count": projection["scored_count"],
            "feature_counts_by_ticker": {
                ticker: details[ticker]["n_features"]
                for ticker in context["selected_symbols"]
            },
        },
        "paths": {
            "candidate_artifact_path": _repo_rel(candidate_path),
            "source_packet_path": _repo_rel(source_path),
            "output_projection_path": _repo_rel(output_path),
            "summary_path": _repo_rel(summary_resolved),
        },
    }


def run_packet(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    source_packet_path: Path = DEFAULT_SOURCE_PACKET_PATH,
    output_projection_path: Path = DEFAULT_OUTPUT_PROJECTION_PATH,
    summary_path: Path = SUMMARY_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    candidate_path = _existing_file(candidate_artifact_path, field="candidate_artifact_path")
    source_path = _validate_state_json_file(source_packet_path, field="source_packet_path", must_exist=True)
    output_path = _validate_state_json_file(output_projection_path, field="output_projection_path", must_exist=False)
    summary_resolved = _validate_summary_path(summary_path)
    context = _load_context(
        candidate_artifact_path=candidate_path,
        source_packet_path=source_path,
        output_projection_path=output_path,
        summary_path=summary_resolved,
        generated_at=generated_at,
    )
    projection, details = _build_projection(context)
    summary = _build_summary(context=context, projection=projection, details=details)
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="momentum price source summary")
    _assert_text_safe(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    _prepare_json_target(output_path, field="output_projection_path")
    _prepare_json_target(summary_resolved, field="summary_path")
    _write_json_atomic(projection, output_path, field="output_projection_path")
    _write_summary_validated(summary, summary_resolved)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a US-short Batch5 momentum projection from an already-authorized local price-history "
            "source packet. This runner never fetches providers, stores raw payloads, uses DataHub, or "
            "claims production/ship-gate evidence."
        )
    )
    parser.add_argument("--candidate-artifact-path", type=Path, default=DEFAULT_CANDIDATE_ARTIFACT_PATH)
    parser.add_argument("--source-packet-path", type=Path, default=DEFAULT_SOURCE_PACKET_PATH)
    parser.add_argument("--output-projection-path", type=Path, default=DEFAULT_OUTPUT_PROJECTION_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--generated-at")
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    kwargs = {
        "candidate_artifact_path": args.candidate_artifact_path,
        "source_packet_path": args.source_packet_path,
        "output_projection_path": args.output_projection_path,
        "summary_path": args.summary_path,
        "generated_at": args.generated_at,
    }
    result = run_preflight(**kwargs) if args.preflight_only else run_packet(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
