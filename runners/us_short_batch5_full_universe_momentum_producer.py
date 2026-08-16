# -*- coding: utf-8 -*-
"""US-short full-universe momentum PRODUCER (offline half — piece 2 of the full-universe momentum build).

Design authority: docs/system_risk_register.md::R-USSHORT-BATCH5-FULL-UNIVERSE-MOMENTUM-PRODUCTION-MISSING
(+ docs/us_short_system_design.md §2/§4.0/§4.2). This runner scores REAL momentum for ALL ~2404 Pass1-eligible
candidates (the input the now-wired top-K funnel needs), unlike the deliberately curated <=3-symbol
runners/us_short_batch5_momentum_price_source.py (untouched).

WHAT THIS IS: consume a reconstructed per-ticker-series packet (written by the GATED grouped-window fetch via
engine/us_short_momentum_grouped_reconstruct.py) plus the validated candidate artifact, then reuse the PROVEN
engine flow VERBATIM over ALL eligible — compute_momentum_features -> momentum_block -> project_momentum_block
(engine/us_short_momentum.py + engine/us_short_seam_momentum.py) — and emit the same funnel-consumable momentum
projection shape (momentum_by_ticker / neutral_fill_tickers / coverage / target_count / scored_count) plus a
counts-only no-secret tracked summary. The projection feeds runners/us_short_batch5_full_candidate_projection_inputs.py.

GRACEFUL DISPOSITION (the key difference from the curated <=3 producer): a thin / bad / absent ticker is NEVER a
hard raise. The engine is the single PIT/clean authority: compute_momentum_features returns EMPTY features for a
malformed / look-ahead / non-positive-close / too-short series (it never raises), momentum_block routes it to
insufficient_history / insufficient_coverage, and an eligible ticker with NO series in the packet is projected to
`absent_from_pool` by project_momentum_block. So every eligible ticker gets an HONEST disposition and the run
always completes. This runner therefore does NOT re-validate per-ticker close/volume values (the engine owns that);
it validates only the ENVELOPE (clock coherence + benchmarks present-and-parseable + no stray/forged ticker + no
per-ticker look-ahead as_of), which are corrupt-packet signals that must fail closed.

WHAT THIS IS NOT: not a fetch (the live grouped-window fetch is SR-PROVIDER-001 gated, separate piece 3), not a
re-implementation of feature/percentile/PIT math, not theme/catalyst, not Pass2/selection/top-K. Pure/offline; no
provider/live/network/DataHub/production/ship-gate/broker path; no A-share crossing.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
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
from engine.us_short_projection_binding import build_projection_binding  # noqa: E402
from engine.us_short_momentum import compute_momentum_features, momentum_block  # noqa: E402
from engine.us_short_seam_momentum import (  # noqa: E402
    DISPOSITION_ABSENT,
    DISPOSITION_INSUFFICIENT_COVERAGE,
    DISPOSITION_INSUFFICIENT_HISTORY,
    DISPOSITION_SCORED,
    project_momentum_block,
)
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402


PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_momentum_series_packet.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_momentum_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_full_universe_momentum_summary_20260707.json"
SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_full_universe_momentum")
LEGACY_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_full_universe_momentum_20260707")
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260707.json"
DEFAULT_SERIES_PACKET_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_full_universe_momentum_series_20260707_packet.json"
)
DEFAULT_OUTPUT_PROJECTION_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_full_universe_momentum_20260707_momentum.json"
)
BENCHMARK_SYMBOLS = ("SPY", "QQQ")
SAFE_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class FullUniverseMomentumProducerError(ValueError):
    """A full-universe momentum series packet cannot be consumed into a projection safely."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _prepare_json_target(path: Path, *, field: str) -> None:
    if path.parent.exists() and not path.parent.is_dir():
        raise FullUniverseMomentumProducerError(f"{field} parent must be a directory: {_display_path(path.parent)}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FullUniverseMomentumProducerError(
            f"{field} parent could not be created: {_display_path(path.parent)}"
        ) from exc
    if path.exists() and path.is_dir():
        raise FullUniverseMomentumProducerError(f"{field} must be a file path, not a directory: {_display_path(path)}")


def _write_json_atomic(payload: Any, path: Path, *, field: str) -> None:
    _prepare_json_target(path, field=field)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise FullUniverseMomentumProducerError(f"{field} could not be written atomically: {_display_path(path)}") from exc


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
        raise FullUniverseMomentumProducerError(f"{field} must stay under the repository root") from exc
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


def _validate_state_json_file(path: Path | str, *, field: str, must_exist: bool) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise FullUniverseMomentumProducerError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise FullUniverseMomentumProducerError(f"{field} must be a .json path")
    if must_exist and (not resolved.exists() or not resolved.is_file()):
        raise FullUniverseMomentumProducerError(f"{field} must be an existing file: {_display_path(resolved)}")
    if not _git_ignored(resolved):
        raise FullUniverseMomentumProducerError(f"{field} must be gitignored")
    return resolved


def _validate_summary_path(path: Path | str, *, expected_decision_date: str | None = None) -> Path:
    resolved = _resolve_repo_path(path, field="summary_path")
    if resolved.suffix != ".json":
        raise FullUniverseMomentumProducerError("summary_path must be a .json path")
    if resolved == SUMMARY_PATH.resolve():
        return resolved
    try:
        relative = resolved.relative_to((ROOT / SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise FullUniverseMomentumProducerError(
            "summary_path must be the canonical tracked summary or under this runner's provider_samples folder"
        ) from exc
    if len(relative.parts) < 2:
        raise FullUniverseMomentumProducerError(
            "summary_path must include a decision-date directory under the momentum provider_samples root"
        )
    _compact_to_ymd(relative.parts[0], field="summary_path decision-date directory")
    if expected_decision_date is not None and relative.parts[0] != expected_decision_date:
        raise FullUniverseMomentumProducerError("summary_path decision-date directory must match expected_decision_date")
    if not _git_ignored(resolved):
        raise FullUniverseMomentumProducerError("non-canonical summary_path must be gitignored")
    return resolved


def _valid_observed_at(value: str) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _compact_to_ymd(value: Any, *, field: str) -> str:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise FullUniverseMomentumProducerError(f"{field} must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise FullUniverseMomentumProducerError(f"{field} must be a real calendar date") from exc


def _safe_provider_id(value: Any) -> str:
    if type(value) is not str or SAFE_PROVIDER_ID_RE.fullmatch(value) is None:
        raise FullUniverseMomentumProducerError("provenance.provider_id must be a lowercase provider slug")
    return value


def _canonical_ticker(raw: Any, *, field: str) -> str:
    if type(raw) is not str:
        raise FullUniverseMomentumProducerError(f"{field} must be an exact ticker string")
    ticker = canonical_us_ticker(raw)
    if ticker is None:
        raise FullUniverseMomentumProducerError(f"{field} must be a canonicalizable US ticker")
    return ticker


def _validate_schema(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise FullUniverseMomentumProducerError("jsonschema is required for full-universe momentum validation") from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise FullUniverseMomentumProducerError(f"{label} schema rejected {len(errors)} field(s): {joined}") from errors[0]


def _load_candidate_artifact(*, candidate_artifact_path: Path, expected_decision_date: str) -> dict[str, Any]:
    artifact = _read_json(candidate_artifact_path)
    governance = load_eligibility_governance(ELIGIBILITY_GOVERNANCE_PATH)
    try:
        validated = universe_fetch.validate_candidate_artifact(
            artifact,
            expected_decision_date=expected_decision_date,
            governance=governance,
        )
    except Exception as exc:
        raise FullUniverseMomentumProducerError(f"candidate artifact failed validation: {exc}") from exc
    return validated


def _canonical_series_by_ticker(
    *,
    series_by_ticker: dict[str, Any],
    allowed: set[str],
    price_basis_date: str,
    session: str,
    adjustment_mode: str,
) -> dict[str, dict[str, Any]]:
    """Canonicalize the packet's series keys and enforce ENVELOPE coherence (fail-closed on corrupt-packet
    signals): a non-canonical / duplicate / stray (not eligible-or-benchmark) ticker, or a per-ticker
    look-ahead / mismatched clock (as_of != price_basis_date, or session / adjustment_mode != the contract),
    is a corrupt/forged packet and raises. Per-ticker DATA quality (thin / bad closes) is NOT judged here —
    the engine dispositions it gracefully downstream."""
    canonical: dict[str, dict[str, Any]] = {}
    for raw_key, series in series_by_ticker.items():
        ticker = _canonical_ticker(raw_key, field="series_by_ticker key")
        if ticker in canonical:
            raise FullUniverseMomentumProducerError(f"series_by_ticker contains duplicate canonical ticker: {ticker}")
        if ticker not in allowed:
            raise FullUniverseMomentumProducerError(
                f"series_by_ticker contains a ticker outside the eligible+benchmark set: {ticker}"
            )
        if series["as_of"] != price_basis_date:
            raise FullUniverseMomentumProducerError(f"{ticker} series.as_of must equal the price_basis_date")
        if series["session"] != session:
            raise FullUniverseMomentumProducerError(f"{ticker} series.session must match the series_contract")
        if series["adjustment_mode"] != adjustment_mode:
            raise FullUniverseMomentumProducerError(f"{ticker} series.adjustment_mode must match the series_contract")
        canonical[ticker] = series
    return canonical


def _load_context(
    *,
    candidate_artifact_path: Path,
    series_packet_path: Path,
    output_projection_path: Path,
    summary_path: Path,
    generated_at: str | None,
) -> dict[str, Any]:
    generated_at = generated_at or iso_now()
    if not _valid_observed_at(generated_at):
        raise FullUniverseMomentumProducerError("generated_at must be a timezone-aware RFC3339 instant")

    packet = _read_json(series_packet_path)
    _validate_schema(packet, PACKET_SCHEMA_PATH, label="full-universe momentum series packet")

    clock = packet["decision_clock"]
    contract = packet["series_contract"]
    provenance = packet["provenance"]
    price_basis_date = clock["price_basis_date"]
    if clock["source_as_of"] != price_basis_date:
        raise FullUniverseMomentumProducerError("decision_clock.price_basis_date and source_as_of must match")
    if contract["as_of"] != price_basis_date:
        raise FullUniverseMomentumProducerError("series_contract.as_of must equal the price_basis_date")
    if provenance["source_as_of"] != price_basis_date:
        raise FullUniverseMomentumProducerError("provenance.source_as_of must equal the price_basis_date")
    provider_id = _safe_provider_id(provenance["provider_id"])

    artifact = _load_candidate_artifact(
        candidate_artifact_path=candidate_artifact_path,
        expected_decision_date=clock["expected_decision_date"],
    )
    _validate_summary_path(summary_path, expected_decision_date=clock["expected_decision_date"])
    if clock["candidate_price_basis_date"] != artifact["price_basis_date"]:
        raise FullUniverseMomentumProducerError("candidate_price_basis_date must match the candidate artifact")
    if artifact["used_date"] != price_basis_date:
        raise FullUniverseMomentumProducerError("candidate used_date must match the packet price_basis_date")
    eligible = [_canonical_ticker(ticker, field="candidate.eligible_tickers") for ticker in artifact["eligible_tickers"]]

    session = contract["session"]
    adjustment_mode = contract["adjustment_mode"]
    benchmarks = tuple(_canonical_ticker(sym, field="benchmark") for sym in BENCHMARK_SYMBOLS)
    allowed = set(eligible) | set(benchmarks)
    canonical_series = _canonical_series_by_ticker(
        series_by_ticker=packet["series_by_ticker"],
        allowed=allowed,
        price_basis_date=price_basis_date,
        session=session,
        adjustment_mode=adjustment_mode,
    )
    for bench in benchmarks:
        if bench not in canonical_series:
            raise FullUniverseMomentumProducerError(f"required benchmark series missing from packet: {bench}")

    if output_projection_path in {candidate_artifact_path, series_packet_path}:
        raise FullUniverseMomentumProducerError("output_projection_path must not overwrite input files")

    return {
        "generated_at": generated_at,
        "packet": packet,
        "provider_id": provider_id,
        "price_basis_date": price_basis_date,
        "session": session,
        "adjustment_mode": adjustment_mode,
        "artifact": artifact,
        "eligible": eligible,
        "benchmarks": benchmarks,
        "canonical_series": canonical_series,
        "candidate_artifact_path": candidate_artifact_path,
        "series_packet_path": series_packet_path,
        "output_projection_path": output_projection_path,
        "summary_path": summary_path,
    }


def _build_projection(context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    canonical_series = context["canonical_series"]
    eligible = context["eligible"]
    spy_ticker, qqq_ticker = context["benchmarks"]
    spy_series = canonical_series[spy_ticker]
    qqq_series = canonical_series[qqq_ticker]

    # Benchmarks gate the whole pool's relative-strength features, so a malformed benchmark is a fetch bug that
    # must fail closed (not silently drop rel_spy/rel_qqq for EVERY ticker). compute_momentum_features(...).pit
    # is None iff the series failed to parse (the public fail-closed signal).
    for bench_ticker, bench_series in ((spy_ticker, spy_series), (qqq_ticker, qqq_series)):
        if compute_momentum_features(bench_series)["pit"] is None:
            raise FullUniverseMomentumProducerError(f"benchmark series {bench_ticker} is not a parseable PIT series")

    features_by_ticker: dict[str, dict[str, float]] = {}
    for ticker in eligible:
        series = canonical_series.get(ticker)
        if series is None:
            continue  # eligible but no series in packet -> project_momentum_block marks it absent_from_pool
        computed = compute_momentum_features(series, spy_series=spy_series, qqq_series=qqq_series)
        features_by_ticker[ticker] = computed["features"]

    producer_result = momentum_block(features_by_ticker)
    projection = project_momentum_block(producer_result, eligible)
    projection["source_binding"] = build_projection_binding(
        component="momentum",
        producer_id="us_short_batch5_full_universe_momentum_producer",
        generated_at=context["generated_at"],
        expected_decision_date=context["packet"]["decision_clock"]["expected_decision_date"],
        candidate_price_basis_date=context["artifact"]["price_basis_date"],
        source_as_of=context["artifact"]["used_date"],
        target_tickers=eligible,
        projection=projection,
        session=context["session"],
        adjustment_mode=context["adjustment_mode"],
        source_artifact_paths={
            "candidate_artifact": context["candidate_artifact_path"],
            "momentum_series_packet": context["series_packet_path"],
        },
    )
    details = {
        "eligible_with_series_count": len(features_by_ticker),
        "disposition_counts": _disposition_counts(projection["coverage"]),
    }
    return projection, details


def _disposition_counts(coverage: dict[str, str]) -> dict[str, int]:
    counts = Counter(coverage.values())
    return {
        "scored": counts.get(DISPOSITION_SCORED, 0),
        "insufficient_history": counts.get(DISPOSITION_INSUFFICIENT_HISTORY, 0),
        "insufficient_coverage": counts.get(DISPOSITION_INSUFFICIENT_COVERAGE, 0),
        "absent_from_pool": counts.get(DISPOSITION_ABSENT, 0),
    }


def _build_summary(*, context: dict[str, Any], projection: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    packet = context["packet"]
    artifact = context["artifact"]
    eligible = context["eligible"]
    return {
        "schema_name": "us_short_batch5_full_universe_momentum_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_full_universe_momentum_summary.schema.json",
        "generated_at": context["generated_at"],
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "full_universe_momentum_series_packet_to_projection",
            "status": "full_universe_momentum_projection_written",
            "network_access_performed_by_runner": False,
            "provider_calls_performed_by_runner": False,
            "raw_payload_storage_performed_by_runner": False,
            "series_packet_consumed": True,
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
        "candidate_universe": {
            "row_count": len(artifact["rows"]),
            "eligible_count": len(eligible),
            "symbol_scope": "full_pass1_eligible_candidate_set",
            "full_market_sample": False,
        },
        "series_source": {
            "series_count": len(context["canonical_series"]),
            "eligible_with_series_count": details["eligible_with_series_count"],
            "benchmark_symbols": list(BENCHMARK_SYMBOLS),
            "provider_ids": [context["provider_id"]],
            "session": context["session"],
            "adjustment_mode": context["adjustment_mode"],
            "grouped_session_count": packet["series_contract"]["grouped_session_count"],
        },
        "projection_contract": {
            "target_count": projection["target_count"],
            "momentum_scored_count": projection["scored_count"],
            "neutral_fill_count": len(projection["neutral_fill_tickers"]),
            "disposition_counts": details["disposition_counts"],
            "coverage_exactly_matches_full_candidate_set": True,
            "real_momentum_price_source_consumed": projection["scored_count"] > 0,
        },
        "paths": {
            "candidate_artifact_path": _repo_rel(context["candidate_artifact_path"]),
            "series_packet_path": _repo_rel(context["series_packet_path"]),
            "output_projection_path": _repo_rel(context["output_projection_path"]),
            "summary_path": _repo_rel(context["summary_path"]),
        },
        "storage": {
            "series_packet_path_gitignored": _git_ignored(context["series_packet_path"]),
            "output_projection_path_gitignored": _git_ignored(context["output_projection_path"]),
            "summary_path_gitignored": _git_ignored(context["summary_path"]),
            "summary_contains_ticker_lists": False,
            "summary_contains_price_rows": False,
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
            "This runner consumes an already-built local full-universe per-ticker series packet; it performs no provider fetch.",
            "The tracked summary is counts-only: no ticker lists, price rows, raw payloads, request URLs, or secrets.",
            "Neutral-filled / absent candidates have honest dispositions but no live momentum evidence from this runner.",
            "The live grouped-window fetch that builds the series packet, DataHub, production storage, broker/order execution, live-normalized and ship-gate evidence remain out of scope (SR-PROVIDER-001).",
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
        "\"results\"",
    )
    for fragment in forbidden:
        if fragment in lower:
            raise FullUniverseMomentumProducerError(f"summary contains forbidden fragment: {fragment}")


def _write_summary_validated(summary: dict[str, Any], summary_path: Path) -> None:
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="full-universe momentum summary")
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text)
    _write_json_atomic(summary, summary_path, field="summary_path")


def _resolve_paths(
    *,
    candidate_artifact_path: Path,
    series_packet_path: Path,
    output_projection_path: Path,
    summary_path: Path,
) -> dict[str, Path]:
    candidate_path = _validate_state_json_file(candidate_artifact_path, field="candidate_artifact_path", must_exist=True)
    series_path = _validate_state_json_file(series_packet_path, field="series_packet_path", must_exist=True)
    output_path = _validate_state_json_file(output_projection_path, field="output_projection_path", must_exist=False)
    summary_resolved = _validate_summary_path(summary_path)
    if len({candidate_path, series_path, output_path}) != 3:
        raise FullUniverseMomentumProducerError("candidate / series / output projection paths must be distinct")
    return {
        "candidate": candidate_path,
        "series": series_path,
        "output": output_path,
        "summary": summary_resolved,
    }


def run_preflight(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    series_packet_path: Path = DEFAULT_SERIES_PACKET_PATH,
    output_projection_path: Path = DEFAULT_OUTPUT_PROJECTION_PATH,
    summary_path: Path = SUMMARY_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    paths = _resolve_paths(
        candidate_artifact_path=candidate_artifact_path,
        series_packet_path=series_packet_path,
        output_projection_path=output_projection_path,
        summary_path=summary_path,
    )
    context = _load_context(
        candidate_artifact_path=paths["candidate"],
        series_packet_path=paths["series"],
        output_projection_path=paths["output"],
        summary_path=paths["summary"],
        generated_at=generated_at,
    )
    projection, details = _build_projection(context)
    return {
        "schema_name": "us_short_batch5_full_universe_momentum_preflight_result",
        "schema_version": "1.0.0",
        "generated_at": context["generated_at"],
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "preflight_status": "offline_preflight_passed",
            "network_access_required": False,
            "provider_calls_performed_by_runner": False,
            "projection_file_written": False,
            "summary_file_written": False,
        },
        "projection_preview": {
            "target_count": projection["target_count"],
            "momentum_scored_count": projection["scored_count"],
            "eligible_with_series_count": details["eligible_with_series_count"],
            "disposition_counts": details["disposition_counts"],
        },
        "paths": {
            "candidate_artifact_path": _repo_rel(paths["candidate"]),
            "series_packet_path": _repo_rel(paths["series"]),
            "output_projection_path": _repo_rel(paths["output"]),
            "summary_path": _repo_rel(paths["summary"]),
        },
    }


def run_packet(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    series_packet_path: Path = DEFAULT_SERIES_PACKET_PATH,
    output_projection_path: Path = DEFAULT_OUTPUT_PROJECTION_PATH,
    summary_path: Path = SUMMARY_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    paths = _resolve_paths(
        candidate_artifact_path=candidate_artifact_path,
        series_packet_path=series_packet_path,
        output_projection_path=output_projection_path,
        summary_path=summary_path,
    )
    context = _load_context(
        candidate_artifact_path=paths["candidate"],
        series_packet_path=paths["series"],
        output_projection_path=paths["output"],
        summary_path=paths["summary"],
        generated_at=generated_at,
    )
    projection, details = _build_projection(context)
    summary = _build_summary(context=context, projection=projection, details=details)
    # Validate + hygiene-scan BEFORE any write so a bad summary never lands a partial projection artifact.
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="full-universe momentum summary")
    _assert_text_safe(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    _prepare_json_target(paths["output"], field="output_projection_path")
    _prepare_json_target(paths["summary"], field="summary_path")
    _write_json_atomic(projection, paths["output"], field="output_projection_path")
    try:
        _write_summary_validated(summary, paths["summary"])
    except BaseException:
        # All-or-nothing: a summary-write failure must not leave an orphan projection with no summary
        # (§8 no partial state after failure); the projection is only meaningful alongside its summary.
        paths["output"].unlink(missing_ok=True)
        raise
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Score real momentum for ALL Pass1-eligible candidates from an already-built local full-universe "
            "per-ticker series packet, emitting the funnel-consumable momentum projection with honest per-ticker "
            "dispositions. This runner never fetches providers, stores raw payloads, uses DataHub, or claims "
            "production / ship-gate evidence."
        )
    )
    parser.add_argument("--candidate-artifact-path", type=Path, default=DEFAULT_CANDIDATE_ARTIFACT_PATH)
    parser.add_argument("--series-packet-path", type=Path, default=DEFAULT_SERIES_PACKET_PATH)
    parser.add_argument("--output-projection-path", type=Path, default=DEFAULT_OUTPUT_PROJECTION_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--generated-at")
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    kwargs = {
        "candidate_artifact_path": args.candidate_artifact_path,
        "series_packet_path": args.series_packet_path,
        "output_projection_path": args.output_projection_path,
        "summary_path": args.summary_path,
        "generated_at": args.generated_at,
    }
    result = run_preflight(**kwargs) if args.preflight_only else run_packet(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
