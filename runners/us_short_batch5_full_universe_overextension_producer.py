# -*- coding: utf-8 -*-
"""US-short full-universe OVEREXTENSION producer (offline half — cut 2b-ii-B of the §4.3 overextension wiring).

Design authority: docs/system_risk_register.md::R-USSHORT-BATCH5-OVEREXTENSION-WIRING-INCOMPLETE (cut 2b-ii-B)
(+ docs/us_short_system_design.md §4.3 过热分档). This runner produces the §4.3 overextension tier for ALL
Pass1-eligible candidates (the pool-level input the SELECTION-layer theme-strip [Slice B] + the execution-side
warning lever [cut 2c] consume), computed at the SCORING stage (before ranking).

WHAT THIS IS: consume a full-universe per-ticker OHLCV series packet (written by the GATED grouped-window fetch,
cut 2b-iii, which retains high/low — ATR needs them) plus the validated candidate artifact, then call the PROVEN
pure pool producer engine/us_short_overextension_producer.py::build_overextension_projection VERBATIM over ALL
eligible, and emit a source-bound projection envelope (decision/price clock + source contract + candidate-universe
digest + {overextension_by_ticker: {ticker: tier}, disposition_counts, scored_count, target_count}) plus a
counts-only no-secret tracked summary (disposition tally + the honest §4.3 state tally
none / warning / chasing_extreme). No benchmarks are involved — overextension is a per-ticker ABSOLUTE signal
(not relative strength), unlike the momentum producer's SPY/QQQ-gated features.

ENVELOPE authority is the ENGINE, not this runner (single-source): build_overextension_projection fails closed on
a corrupt/forged packet (stray / duplicate / clock-mismatched series = look-ahead), while a thin / absent / bad
per-ticker series dispositions gracefully to insufficient_data via compute_overextension_features (the single
PIT/clean authority, which never raises on per-ticker data). This runner therefore does NOT re-implement the
envelope; it validates the packet SHAPE (schema) + the clock coherence + the candidate identity, then delegates.

WHAT THIS IS NOT: not a fetch (the live grouped-window OHLCV fetch is SR-PROVIDER-001 gated, separate cut 2b-iii),
not a re-implementation of ATR / pattern / tier math, not the selection theme-strip (Slice B, in the score seam),
not the execution warning lever (cut 2c). Pure/offline; no provider/live/network/DataHub/production/ship-gate/
broker path; no A-share crossing.
"""
from __future__ import annotations

import argparse
import json
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
from engine.us_short_overextension import OVEREXTENSION_STATES  # noqa: E402
from engine.us_short_overextension_producer import (  # noqa: E402
    OverextensionProducerError,
    build_overextension_projection,
    eligible_tickers_sha256,
)
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402


PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_ohlcv_series_packet.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_overextension_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_full_universe_overextension_summary_20260709.json"
SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_full_universe_overextension")
LEGACY_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_full_universe_overextension_20260709")
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260709.json"
DEFAULT_SERIES_PACKET_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_full_universe_ohlcv_series_20260709_packet.json"
)
DEFAULT_OUTPUT_PROJECTION_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_full_universe_overextension_20260709_overextension.json"
)
SAFE_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class FullUniverseOverextensionProducerError(ValueError):
    """A full-universe OHLCV series packet cannot be consumed into an overextension projection safely."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _prepare_json_target(path: Path, *, field: str) -> None:
    if path.parent.exists() and not path.parent.is_dir():
        raise FullUniverseOverextensionProducerError(f"{field} parent must be a directory: {_display_path(path.parent)}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FullUniverseOverextensionProducerError(
            f"{field} parent could not be created: {_display_path(path.parent)}"
        ) from exc
    if path.exists() and path.is_dir():
        raise FullUniverseOverextensionProducerError(f"{field} must be a file path, not a directory: {_display_path(path)}")


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
        raise FullUniverseOverextensionProducerError(
            f"{field} could not be written atomically: {_display_path(path)}"
        ) from exc


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
        raise FullUniverseOverextensionProducerError(f"{field} must stay under the repository root") from exc
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
        raise FullUniverseOverextensionProducerError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise FullUniverseOverextensionProducerError(f"{field} must be a .json path")
    if must_exist and (not resolved.exists() or not resolved.is_file()):
        raise FullUniverseOverextensionProducerError(f"{field} must be an existing file: {_display_path(resolved)}")
    if not _git_ignored(resolved):
        raise FullUniverseOverextensionProducerError(f"{field} must be gitignored")
    return resolved


def _validate_summary_path(path: Path | str, *, expected_decision_date: str | None = None) -> Path:
    resolved = _resolve_repo_path(path, field="summary_path")
    if resolved.suffix != ".json":
        raise FullUniverseOverextensionProducerError("summary_path must be a .json path")
    if resolved == SUMMARY_PATH.resolve():
        return resolved
    try:
        relative = resolved.relative_to((ROOT / SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise FullUniverseOverextensionProducerError(
            "summary_path must be the canonical tracked summary or under this runner's provider_samples folder"
        ) from exc
    if len(relative.parts) < 2:
        raise FullUniverseOverextensionProducerError(
            "summary_path must include a decision-date directory under the overextension provider_samples root"
        )
    _compact_to_ymd(relative.parts[0], field="summary_path decision-date directory")
    if expected_decision_date is not None and relative.parts[0] != expected_decision_date:
        raise FullUniverseOverextensionProducerError("summary_path decision-date directory must match expected_decision_date")
    if not _git_ignored(resolved):
        raise FullUniverseOverextensionProducerError("non-canonical summary_path must be gitignored")
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
        raise FullUniverseOverextensionProducerError(f"{field} must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise FullUniverseOverextensionProducerError(f"{field} must be a real calendar date") from exc


def _safe_provider_id(value: Any) -> str:
    if type(value) is not str or SAFE_PROVIDER_ID_RE.fullmatch(value) is None:
        raise FullUniverseOverextensionProducerError("provenance.provider_id must be a lowercase provider slug")
    return value


def _canonical_ticker(raw: Any, *, field: str) -> str:
    if type(raw) is not str:
        raise FullUniverseOverextensionProducerError(f"{field} must be an exact ticker string")
    ticker = canonical_us_ticker(raw)
    if ticker is None:
        raise FullUniverseOverextensionProducerError(f"{field} must be a canonicalizable US ticker")
    return ticker


def _validate_schema(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise FullUniverseOverextensionProducerError(
            "jsonschema is required for full-universe overextension validation"
        ) from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise FullUniverseOverextensionProducerError(
            f"{label} schema rejected {len(errors)} field(s): {joined}"
        ) from errors[0]


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
        raise FullUniverseOverextensionProducerError(f"candidate artifact failed validation: {exc}") from exc
    return validated


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
        raise FullUniverseOverextensionProducerError("generated_at must be a timezone-aware RFC3339 instant")

    packet = _read_json(series_packet_path)
    _validate_schema(packet, PACKET_SCHEMA_PATH, label="full-universe OHLCV series packet")

    clock = packet["decision_clock"]
    contract = packet["series_contract"]
    provenance = packet["provenance"]
    price_basis_date = clock["price_basis_date"]
    if clock["source_as_of"] != price_basis_date:
        raise FullUniverseOverextensionProducerError("decision_clock.price_basis_date and source_as_of must match")
    if contract["as_of"] != price_basis_date:
        raise FullUniverseOverextensionProducerError("series_contract.as_of must equal the price_basis_date")
    if provenance["source_as_of"] != price_basis_date:
        raise FullUniverseOverextensionProducerError("provenance.source_as_of must equal the price_basis_date")
    if _compact_to_ymd(clock["candidate_price_basis_date"], field="decision_clock.candidate_price_basis_date") != price_basis_date:
        raise FullUniverseOverextensionProducerError("candidate_price_basis_date must normalize to price_basis_date")
    provider_id = _safe_provider_id(provenance["provider_id"])

    artifact = _load_candidate_artifact(
        candidate_artifact_path=candidate_artifact_path,
        expected_decision_date=clock["expected_decision_date"],
    )
    _validate_summary_path(summary_path, expected_decision_date=clock["expected_decision_date"])
    if _compact_to_ymd(artifact["price_basis_date"], field="candidate.price_basis_date") != price_basis_date:
        raise FullUniverseOverextensionProducerError(
            "candidate artifact price_basis_date must match the packet price_basis_date"
        )
    eligible = [_canonical_ticker(ticker, field="candidate.eligible_tickers") for ticker in artifact["eligible_tickers"]]

    if output_projection_path in {candidate_artifact_path, series_packet_path}:
        raise FullUniverseOverextensionProducerError("output_projection_path must not overwrite input files")

    return {
        "generated_at": generated_at,
        "packet": packet,
        "provider_id": provider_id,
        "price_basis_date": price_basis_date,
        "session": contract["session"],
        "adjustment_mode": contract["adjustment_mode"],
        "artifact": artifact,
        "eligible": eligible,
        "candidate_artifact_path": candidate_artifact_path,
        "series_packet_path": series_packet_path,
        "output_projection_path": output_projection_path,
        "summary_path": summary_path,
    }


def _build_projection(context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Delegate the ENVELOPE + per-ticker tier to the pure pool producer (single PIT/envelope authority). A
    corrupt/forged packet (stray / duplicate / clock-mismatched series) raises OverextensionProducerError, wrapped
    here as the runner error; a thin / absent per-ticker series dispositions to insufficient_data honestly."""
    packet = context["packet"]
    try:
        result = build_overextension_projection(
            packet["series_by_ticker"],
            context["eligible"],
            price_basis_date=context["price_basis_date"],
            session=context["session"],
            adjustment_mode=context["adjustment_mode"],
        )
    except OverextensionProducerError as exc:
        raise FullUniverseOverextensionProducerError(f"overextension projection failed closed: {exc}") from exc

    projection = {
        "schema_name": "us_short_full_universe_overextension_projection",
        "schema_version": "1.0.0",
        "generated_at": context["generated_at"],
        "decision_clock": dict(packet["decision_clock"]),
        "source_contract": {
            "session": context["session"],
            "adjustment_mode": context["adjustment_mode"],
        },
        "candidate_binding": {
            "eligible_count": len(context["eligible"]),
            "eligible_tickers_sha256": eligible_tickers_sha256(context["eligible"]),
        },
        "overextension_by_ticker": result["overextension_by_ticker"],
        "disposition_counts": result["disposition_counts"],
        "scored_count": result["scored_count"],
        "target_count": result["target_count"],
    }
    # Every packet series is for an eligible ticker (the engine fails closed on any stray/duplicate key), and there
    # are NO benchmarks, so series_count == eligible_with_series_count == the packet series count.
    details = {
        "series_count": len(packet["series_by_ticker"]),
        "eligible_with_series_count": len(packet["series_by_ticker"]),
        "state_counts": _state_counts(result["overextension_by_ticker"]),
    }
    return projection, details


def _state_counts(overextension_by_ticker: dict[str, Any]) -> dict[str, int]:
    counts = {state: 0 for state in OVEREXTENSION_STATES}
    for tier in overextension_by_ticker.values():
        state = tier["overextension_state"]
        counts[state] = counts.get(state, 0) + 1
    return {state: counts[state] for state in OVEREXTENSION_STATES}


def _build_summary(*, context: dict[str, Any], projection: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    packet = context["packet"]
    artifact = context["artifact"]
    eligible = context["eligible"]
    return {
        "schema_name": "us_short_batch5_full_universe_overextension_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_full_universe_overextension_summary.schema.json",
        "generated_at": context["generated_at"],
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "full_universe_ohlcv_series_packet_to_overextension_projection",
            "status": "full_universe_overextension_projection_written",
            "network_access_performed_by_runner": False,
            "provider_calls_performed_by_runner": False,
            "raw_payload_storage_performed_by_runner": False,
            "series_packet_consumed": True,
            "overextension_projection_written": True,
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
            "series_count": details["series_count"],
            "eligible_with_series_count": details["eligible_with_series_count"],
            "provider_ids": [context["provider_id"]],
            "session": context["session"],
            "adjustment_mode": context["adjustment_mode"],
            "grouped_session_count": packet["series_contract"]["grouped_session_count"],
        },
        "projection_contract": {
            "target_count": projection["target_count"],
            "overextension_scored_count": projection["scored_count"],
            "disposition_counts": dict(projection["disposition_counts"]),
            "state_counts": details["state_counts"],
            "coverage_exactly_matches_full_candidate_set": True,
            "real_ohlcv_source_consumed": projection["scored_count"] > 0,
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
            "This runner consumes an already-built local full-universe per-ticker OHLCV series packet; it performs no provider fetch.",
            "The tracked summary is counts-only: no ticker lists, price rows, raw payloads, request URLs, or secrets.",
            "insufficient_data / absent candidates carry honest dispositions but no live overextension evidence from this runner.",
            "The gated grouped-window OHLCV fetch that builds the series packet (retaining high/low), DataHub, production storage, broker/order execution, live-normalized and ship-gate evidence remain out of scope (SR-PROVIDER-001).",
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
            raise FullUniverseOverextensionProducerError(f"summary contains forbidden fragment: {fragment}")


def _write_summary_validated(summary: dict[str, Any], summary_path: Path) -> None:
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="full-universe overextension summary")
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
        raise FullUniverseOverextensionProducerError("candidate / series / output projection paths must be distinct")
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
        "schema_name": "us_short_batch5_full_universe_overextension_preflight_result",
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
            "overextension_scored_count": projection["scored_count"],
            "eligible_with_series_count": details["eligible_with_series_count"],
            "disposition_counts": dict(projection["disposition_counts"]),
            "state_counts": details["state_counts"],
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
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="full-universe overextension summary")
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
            "Produce the §4.3 overextension tier for ALL Pass1-eligible candidates from an already-built local "
            "full-universe per-ticker OHLCV series packet, emitting the projection + a counts-only no-secret tracked "
            "summary (disposition + none/warning/chasing_extreme tally). This runner never fetches providers, stores "
            "raw payloads, uses DataHub, or claims production / ship-gate evidence."
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
