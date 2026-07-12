# -*- coding: utf-8 -*-
"""US-short full-universe momentum GATED grouped-window fetch (piece 3, SR-PROVIDER-001).

Design authority: docs/system_risk_register.md::R-USSHORT-BATCH5-FULL-UNIVERSE-MOMENTUM-PRODUCTION-MISSING.
This is the LIVE half that feeds the offline full-universe momentum producer (piece 2,
runners/us_short_batch5_full_universe_momentum_producer.py). It reuses the PROVEN cheap grouped-daily path
(runners/us_short_universe_fetch.py::_massive_grouped_for_date — ONE Massive call per trading day returns
`{T,c,v}` for the WHOLE US market) over ~64-90 sessions ending at the candidate's price_basis_date, keeps ONLY
the eligible+benchmark rows (memory-bounded), and calls the pure reconstruction
(engine/us_short_momentum_grouped_reconstruct.py::reconstruct_series_from_grouped) to write a per-ticker-series
packet (~10MB, eligible+SPY/QQQ only — NOT the ~100MB raw whole-market grouped window, which is never persisted).

WHY IT IS SAFE / GATED: it is SR-PROVIDER-001 gated (a real Massive network fetch is a user-authorized
per-execution action). Fail-closed: no `confirm_user_authorization` -> refuse; no `MASSIVE_API_KEY` -> refuse;
packet path not gitignored -> refuse; benchmarks not covered by the fetched window -> refuse (no packet written).
The grouped URL embeds the apiKey, so the key/URL is NEVER printed, logged, or written — the tracked summary is
counts/shape-only and is secret-scanned (key + provider-domain deny-list) BEFORE any write. Raw whole-market
grouped payloads are NOT persisted; only the bounded reconstructed packet (gitignored state/us_short) is kept.

WHAT THIS IS NOT: not scoring (piece 2 does that), not PIT/clean math (the engine owns it), not corporate-action
reconciliation (the closes are the Massive grouped-daily default adjustment; split/dividend reconciliation is a
separate SR-PROVIDER-001 track), not DataHub/production/ship-gate, not broker/order, no A-share crossing.

Offline-testable: the whole-market grouped call is an injectable `grouped_fetch(date_iso)->rows` seam (default
binds to the real gated Massive call using the env key); tests pass a fake seam + zero pacing so no network/key
is touched. Pure otherwise.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_eligibility_gate import canonical_us_ticker, load_eligibility_governance  # noqa: E402
from engine.us_short_momentum_grouped_reconstruct import (  # noqa: E402
    reconstruct_ohlcv_series_from_grouped,
    reconstruct_series_from_grouped,
)
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402


PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_momentum_series_packet.schema.json"
OHLCV_PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_ohlcv_series_packet.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_momentum_fetch_summary.schema.json"
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
CALENDAR_PRESET = universe_fetch.CALENDAR_PRESET
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260706.json"
SUMMARY_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_full_universe_momentum_fetch")
_CANONICAL_SUMMARY_RE = re.compile(r"^us_short_batch5_full_universe_momentum_fetch_summary_[0-9]{8}\.json$")

BENCHMARK_SYMBOLS = ("SPY", "QQQ")
# Massive grouped daily `adjusted=true` confirms split adjustment. Dividend/ex-date reconciliation remains a
# separate SR-PROVIDER-001 track, so the source contract must not overclaim `split_div_adjusted`.
SESSION_LABEL = "RTH"
ADJUSTMENT_MODE = "split_adjusted"
# momentum ret_3m / vol_surge need ~64 sessions; collect up to WINDOW with data, over WINDOW+BUFFER candidates.
SESSION_WINDOW_TARGET = 70
SESSION_MIN_REQUIRED = 64
SESSION_FETCH_BUFFER = 25
REQUEST_INTERVAL_SECONDS = universe_fetch.MASSIVE_GROUPED_REQUEST_INTERVAL_SECONDS
RATE_LIMIT_RETRY_SECONDS = universe_fetch.MASSIVE_RATE_LIMIT_RETRY_SECONDS
RATE_LIMIT_MAX_RETRIES = universe_fetch.MASSIVE_RATE_LIMIT_MAX_RETRIES


class FullUniverseMomentumFetchError(RuntimeError):
    """The gated full-universe momentum grouped-window fetch cannot proceed / complete safely (fail-closed)."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _resolve_repo_path(path: Path | str, *, field: str) -> Path:
    raw = Path(path)
    resolved = raw.resolve() if raw.is_absolute() else (ROOT / raw).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise FullUniverseMomentumFetchError(f"{field} must stay under the repository root") from exc
    return resolved


def _validate_packet_path(path: Path | str) -> Path:
    resolved = _resolve_repo_path(path, field="series_packet_path")
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise FullUniverseMomentumFetchError("series_packet_path must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise FullUniverseMomentumFetchError("series_packet_path must be a .json path")
    if not universe_fetch._git_check_ignored(resolved):
        raise FullUniverseMomentumFetchError("series_packet_path must be gitignored (real market data stays private)")
    return resolved


def _validate_summary_path(path: Path | str) -> Path:
    resolved = _resolve_repo_path(path, field="summary_path")
    if resolved.suffix != ".json":
        raise FullUniverseMomentumFetchError("summary_path must be a .json path")
    if resolved.parent == (ROOT / "docs").resolve() and _CANONICAL_SUMMARY_RE.match(resolved.name):
        return resolved  # canonical tracked summary
    try:
        resolved.relative_to((ROOT / SUMMARY_SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise FullUniverseMomentumFetchError(
            "summary_path must be the canonical docs summary or under provider_samples/us_short_batch5_full_universe_momentum_fetch/"
        ) from exc
    if not universe_fetch._git_check_ignored(resolved):
        raise FullUniverseMomentumFetchError("non-canonical summary_path must be gitignored")
    return resolved


def _compact_to_ymd(value: Any, *, field: str) -> str:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise FullUniverseMomentumFetchError(f"{field} must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise FullUniverseMomentumFetchError(f"{field} must be a real calendar date") from exc


def _validate_schema(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise FullUniverseMomentumFetchError("jsonschema is required for full-universe momentum fetch") from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise FullUniverseMomentumFetchError(f"{label} schema rejected {len(errors)} field(s): {joined}") from errors[0]


def _load_candidate(*, candidate_artifact_path: Path) -> dict[str, Any]:
    artifact = _read_json(candidate_artifact_path)
    governance = load_eligibility_governance(ELIGIBILITY_GOVERNANCE_PATH)
    try:
        validated = universe_fetch.validate_candidate_artifact(
            artifact,
            expected_decision_date=artifact.get("decision_date"),
            governance=governance,
        )
    except Exception as exc:
        raise FullUniverseMomentumFetchError(f"candidate artifact failed validation: {exc}") from exc
    return validated


def _vol_dedup_key(volume: Any) -> float:
    """Sort key for choosing among duplicate rows: the finite volume, or -inf if it has none (so a row WITH
    volume always beats one without)."""
    if not isinstance(volume, (int, float)) or isinstance(volume, bool):
        return float("-inf")
    try:
        converted = float(volume)
    except (OverflowError, TypeError, ValueError):
        return float("-inf")
    return converted if math.isfinite(converted) else float("-inf")


def _real_grouped_fetch(key: str) -> Callable[[str], list[dict[str, Any]]]:
    if not key:
        raise FullUniverseMomentumFetchError("MASSIVE_API_KEY not set (a live grouped fetch requires it)")

    def _fetch(date_iso: str) -> list[dict[str, Any]]:
        # Reuse the proven, secret-careful grouped call (URL embeds apiKey -> never surfaced here).
        return universe_fetch._massive_grouped_for_date(date_iso, key)

    return _fetch


def _fetch_grouped_series_window(
    grouped_fetch: Callable[[str], list[dict[str, Any]]],
    session_dates_desc: list[str],
    wanted: set[str],
    *,
    window: int,
    min_sessions: int,
    interval_seconds: float,
    required_latest_date: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Step newest-first through candidate sessions, fetch the whole-market grouped daily for each, KEEP ONLY the
    wanted (eligible+benchmark) rows, and collect up to `window` sessions that returned market data. Mirrors the
    proven universe-fetch pacing/retry: pace between requests, retry HTTP 429, then FAIL CLOSED on EVERY HTTP error
    (auth/quota/5xx/other after retries) — never mask a transport/server failure as a missing day. Also requires the
    latest collected session to equal the candidate used_date. Returns (grouped_sessions ASCENDING, stats)."""
    import urllib.error

    collected: list[tuple[str, list[dict[str, Any]]]] = []
    request_count = 0
    retry_total = 0
    collapsed_total = 0
    for date_iso in session_dates_desc:
        if len(collected) >= window:
            break
        retry_count = 0
        try:
            while True:
                if request_count > 0 and retry_count == 0 and interval_seconds > 0:
                    time.sleep(interval_seconds)
                request_count += 1
                try:
                    results = grouped_fetch(date_iso)
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code == 429 and retry_count < RATE_LIMIT_MAX_RETRIES:
                        retry_count += 1
                        retry_total += 1
                        time.sleep(RATE_LIMIT_RETRY_SECONDS)
                        continue
                    raise
        except urllib.error.HTTPError as exc:
            code = exc.code  # never chain the HTTPError because its URL can embed the API key
            raise FullUniverseMomentumFetchError(
                f"Massive grouped daily HTTP {code} after {retry_count} retry attempt(s); fail-closed rather than "
                "emit a silently-truncated momentum window"
            ) from None
        if not isinstance(results, list) or not results:
            continue  # market not published for this day (delayed-data lag) -> skip, do not count
        # Dedup per session by canonical ticker: the whole-market grouped feed can carry >1 row for one symbol
        # (multi-venue / corrected prints), which reconstruct correctly rejects as a corrupt packet — so resolve
        # it HERE at the messy-feed boundary, keeping the max-volume (primary/consolidated) print. This mirrors the
        # universe fetch tolerating duplicates for ADV, but deterministically (max-volume, not feed order).
        by_ticker: dict[str, dict[str, Any]] = {}
        for row in results:
            if not isinstance(row, dict):
                continue
            ct = canonical_us_ticker(row.get("T"))
            if ct is None or ct not in wanted:
                continue
            # Retain high/low (cut 2b-iii): the momentum reconstruct reads only close/volume (so the momentum
            # `{date,close,volume}` packet is byte-identical), while the §4.3 overextension OHLCV reconstruct needs
            # h/l for ATR. The max-volume dedup below still picks the primary print (now carrying its own h/l).
            cand = {"ticker": ct, "close": row.get("c"), "high": row.get("h"), "low": row.get("l"), "volume": row.get("v")}
            prev = by_ticker.get(ct)
            if prev is None:
                by_ticker[ct] = cand
            else:
                collapsed_total += 1
                if _vol_dedup_key(cand["volume"]) > _vol_dedup_key(prev["volume"]):
                    by_ticker[ct] = cand
        collected.append((date_iso, list(by_ticker.values())))
    if len(collected) < min_sessions:
        raise FullUniverseMomentumFetchError(
            f"Massive returned only {len(collected)} sessions with data (< min {min_sessions} for momentum ret_3m); "
            "fail-closed rather than write a too-short window"
        )
    latest_collected_date = max(date_iso for date_iso, _ in collected)
    if latest_collected_date != required_latest_date:
        raise FullUniverseMomentumFetchError(
            f"latest grouped session {latest_collected_date} does not equal candidate used_date "
            f"{required_latest_date}; fail-closed rather than backfill a stale window"
        )
    collected_ascending = sorted(collected, key=lambda item: item[0])
    grouped_sessions = [{"date": date_iso, "rows": rows} for date_iso, rows in collected_ascending]
    stats = {
        "sessions_requested": len(session_dates_desc),
        "sessions_with_data": len(collected),
        "grouped_calls_made": request_count,
        "rate_limit_retries": retry_total,
        "duplicate_ticker_rows_collapsed": collapsed_total,
    }
    return grouped_sessions, stats


def _points_stats(series_by_ticker: dict[str, dict[str, Any]]) -> dict[str, int]:
    counts = sorted(len(series["points"]) for series in series_by_ticker.values())
    if not counts:
        return {"series_ticker_count": 0, "min_points": 0, "median_points": 0, "max_points": 0}
    median = counts[len(counts) // 2]
    return {
        "series_ticker_count": len(counts),
        "min_points": counts[0],
        "median_points": median,
        "max_points": counts[-1],
    }


def _build_packet(
    *,
    generated_at: str,
    artifact: dict[str, Any],
    price_basis_ymd: str,
    grouped_session_count: int,
    series_by_ticker: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_name": "us_short_batch5_full_universe_momentum_series_packet",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "packet_status": "full_universe_per_ticker_series_ready_for_local_momentum_projection",
            "full_market_reconstruction": True,
            "network_access_performed_by_packet_producer": True,
            "provider_calls_performed_by_packet_producer": True,
            "raw_payload_refs_gitignored": True,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {
            "expected_decision_date": artifact["decision_date"],
            "candidate_price_basis_date": artifact["price_basis_date"],
            "price_basis_date": price_basis_ymd,
            "source_as_of": price_basis_ymd,
        },
        "series_contract": {
            "benchmark_symbols": list(BENCHMARK_SYMBOLS),
            "session": SESSION_LABEL,
            "adjustment_mode": ADJUSTMENT_MODE,
            "as_of": price_basis_ymd,
            "grouped_session_count": grouped_session_count,
        },
        "provenance": {
            "provider_id": "massive",
            "endpoint_or_family": "grouped_daily",
            "source_as_of": price_basis_ymd,
            "observed_at": generated_at,
            "coverage_status": "full",
            "parser_status": "ok",
        },
        "series_by_ticker": series_by_ticker,
    }


def _build_ohlcv_packet(
    *,
    generated_at: str,
    artifact: dict[str, Any],
    price_basis_ymd: str,
    grouped_session_count: int,
    ohlcv_series_by_ticker: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """The §4.3 overextension OHLCV packet (cut 2b-iii) — mirrors the momentum packet's clock/provenance but each
    point carries high/low (ATR) and there are NO benchmarks (overextension is a per-ticker ABSOLUTE signal, so
    series_by_ticker is ELIGIBLE-ONLY — the 2b-ii-B producer's envelope requires packet keys ⊆ eligible)."""
    return {
        "schema_name": "us_short_batch5_full_universe_ohlcv_series_packet",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "packet_status": "full_universe_per_ticker_ohlcv_series_ready_for_local_overextension_projection",
            "full_market_reconstruction": True,
            "network_access_performed_by_packet_producer": True,
            "provider_calls_performed_by_packet_producer": True,
            "raw_payload_refs_gitignored": True,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {
            "expected_decision_date": artifact["decision_date"],
            "candidate_price_basis_date": artifact["price_basis_date"],
            "price_basis_date": price_basis_ymd,
            "source_as_of": price_basis_ymd,
        },
        "series_contract": {
            "session": SESSION_LABEL,
            "adjustment_mode": ADJUSTMENT_MODE,
            "as_of": price_basis_ymd,
            "grouped_session_count": grouped_session_count,
        },
        "provenance": {
            "provider_id": "massive",
            "endpoint_or_family": "grouped_daily",
            "source_as_of": price_basis_ymd,
            "observed_at": generated_at,
            "coverage_status": "full",
            "parser_status": "ok",
        },
        "series_by_ticker": ohlcv_series_by_ticker,
    }


def _build_summary(
    *,
    generated_at: str,
    artifact: dict[str, Any],
    price_basis_ymd: str,
    eligible_count: int,
    benchmarks_present: bool,
    stats: dict[str, int],
    points_stats: dict[str, int],
    grouped_session_count: int,
    candidate_path: Path,
    packet_path: Path,
    summary_path: Path,
    ohlcv_packet_path: Path | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "schema_name": "us_short_batch5_full_universe_momentum_fetch_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_full_universe_momentum_fetch_summary.schema.json",
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "full_universe_momentum_grouped_window_fetch",
            "status": "series_packet_written",
            "network_access_performed": True,
            "provider_calls_performed": True,
            "grouped_whole_market_calls_performed": True,
            "raw_grouped_window_persisted": False,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "yfinance_consumption_performed": False,
            "paid_access_performed": False,
            "broker_or_order_execution_performed": False,
            "ship_gate_or_live_normalized_evidence_claimed": False,
            "a_share_crossing_performed": False,
        },
        "decision_clock": {
            "expected_decision_date": artifact["decision_date"],
            "candidate_price_basis_date": artifact["price_basis_date"],
            "price_basis_date": price_basis_ymd,
            "source_as_of": price_basis_ymd,
        },
        "fetch_stats": {
            "sessions_requested": stats["sessions_requested"],
            "sessions_with_data": stats["sessions_with_data"],
            "grouped_calls_made": stats["grouped_calls_made"],
            "rate_limit_retries": stats["rate_limit_retries"],
            "duplicate_ticker_rows_collapsed": stats["duplicate_ticker_rows_collapsed"],
            "session_window_target": SESSION_WINDOW_TARGET,
            "min_sessions_required": SESSION_MIN_REQUIRED,
        },
        "coverage": {
            "eligible_count": eligible_count,
            "benchmark_symbols": list(BENCHMARK_SYMBOLS),
            "benchmarks_present": benchmarks_present,
            "series_ticker_count": points_stats["series_ticker_count"],
            "grouped_session_count": grouped_session_count,
            "points_per_series_min": points_stats["min_points"],
            "points_per_series_median": points_stats["median_points"],
            "points_per_series_max": points_stats["max_points"],
        },
        "paths": {
            "candidate_artifact_path": _repo_rel(candidate_path),
            "series_packet_path": _repo_rel(packet_path),
            "summary_path": _repo_rel(summary_path),
        },
        "storage": {
            "series_packet_path_gitignored": universe_fetch._git_check_ignored(packet_path),
            "raw_grouped_window_persisted": False,
            "summary_contains_ticker_lists": False,
            "summary_contains_price_rows": False,
            "summary_contains_request_urls": False,
            "summary_contains_secrets": False,
        },
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_raw_download_persisted": False,
            "yfinance_used": False,
            "paid_access_used": False,
            "datahub_consumed": False,
            "production_readiness_claimed": False,
            "ship_gate_evidence_claimed": False,
            "live_normalized_evidence_claimed": False,
            "corporate_action_reconciliation_performed": False,
            "broker_or_order_execution_performed": False,
            "a_share_crossing_performed": False,
        },
        "limitations": [
            "Closes are the Massive grouped-daily default adjustment; split/dividend reconciliation is a separate SR-PROVIDER-001 track.",
            "Only the reconstructed eligible+benchmark per-ticker series (gitignored) is persisted; the raw whole-market grouped window is not.",
            "The tracked summary is counts/shape-only: no ticker lists, price rows, request URLs, or secrets.",
            "This is a bounded gated fetch; it selects no provider, and claims no DataHub / production / ship-gate / live-normalized evidence.",
        ],
    }
    if ohlcv_packet_path is not None:  # cut 2b-iii: the SAME fetch also wrote a §4.3 overextension OHLCV packet
        summary["paths"]["ohlcv_series_packet_path"] = _repo_rel(ohlcv_packet_path)
        summary["storage"]["ohlcv_series_packet_path_gitignored"] = universe_fetch._git_check_ignored(ohlcv_packet_path)
    return summary


def run_fetch(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    series_packet_path: Path | None = None,
    summary_path: Path | None = None,
    calendar_path: Path = CALENDAR_PRESET,
    generated_at: str | None = None,
    confirm_user_authorization: bool = False,
    session_window: int = SESSION_WINDOW_TARGET,
    min_sessions: int = SESSION_MIN_REQUIRED,
    grouped_fetch: Callable[[str], list[dict[str, Any]]] | None = None,
    interval_seconds: float = REQUEST_INTERVAL_SECONDS,
    ohlcv_series_packet_path: Path | None = None,
) -> dict[str, Any]:
    if not confirm_user_authorization:
        raise FullUniverseMomentumFetchError(
            "live grouped-window fetch requires explicit user authorization (confirm_user_authorization=True)"
        )
    if not universe_fetch._check_gitignore():
        raise FullUniverseMomentumFetchError("provider_samples/ not confirmed in .gitignore")
    if not (isinstance(session_window, int) and not isinstance(session_window, bool) and session_window >= min_sessions):
        raise FullUniverseMomentumFetchError("session_window must be an int >= min_sessions")

    generated_at = generated_at or iso_now()
    candidate_path = _resolve_repo_path(candidate_artifact_path, field="candidate_artifact_path")
    if not candidate_path.exists() or not candidate_path.is_file():
        raise FullUniverseMomentumFetchError(f"candidate_artifact_path must be an existing file: {_repo_rel(candidate_path)}")
    artifact = _load_candidate(candidate_artifact_path=candidate_path)
    price_basis_compact = artifact["price_basis_date"]
    price_basis_ymd = artifact["used_date"]
    used_date_compact = price_basis_ymd.replace("-", "")

    packet_path = _validate_packet_path(
        series_packet_path if series_packet_path is not None
        else STATE_US_SHORT_DIR / f"us_short_batch5_full_universe_momentum_series_{price_basis_compact}_packet.json"
    )
    summary_resolved = _validate_summary_path(
        summary_path if summary_path is not None
        else ROOT / "docs" / f"us_short_batch5_full_universe_momentum_fetch_summary_{price_basis_compact}.json"
    )
    if packet_path == candidate_path:
        raise FullUniverseMomentumFetchError("series_packet_path must not overwrite the candidate artifact")
    ohlcv_packet_resolved = None
    if ohlcv_series_packet_path is not None:
        ohlcv_packet_resolved = _validate_packet_path(ohlcv_series_packet_path)
        if ohlcv_packet_resolved in {packet_path, candidate_path}:
            raise FullUniverseMomentumFetchError(
                "ohlcv_series_packet_path must be distinct from the momentum packet + candidate artifact")

    eligible = [
        t for t in (canonical_us_ticker(raw) for raw in artifact["eligible_tickers"]) if t is not None
    ]
    benchmarks = [b for b in (canonical_us_ticker(sym) for sym in BENCHMARK_SYMBOLS) if b is not None]
    wanted = set(eligible) | set(benchmarks)

    massive_key = os.environ.get("MASSIVE_API_KEY", "")
    fetch_seam = grouped_fetch if grouped_fetch is not None else _real_grouped_fetch(massive_key)

    calendar = universe_fetch.load_market_calendar(calendar_path)
    session_dates_desc = universe_fetch.adv_window_session_dates(
        used_date_compact, calendar, count=session_window + SESSION_FETCH_BUFFER
    )
    grouped_sessions, stats = _fetch_grouped_series_window(
        fetch_seam, session_dates_desc, wanted,
        window=session_window, min_sessions=min_sessions, interval_seconds=interval_seconds,
        required_latest_date=price_basis_ymd,
    )

    series_by_ticker = reconstruct_series_from_grouped(
        grouped_sessions,
        tickers=sorted(wanted),
        as_of=price_basis_ymd,
        session=SESSION_LABEL,
        adjustment_mode=ADJUSTMENT_MODE,
    )
    benchmarks_present = all(
        b in series_by_ticker and len(series_by_ticker[b]["points"]) >= min_sessions for b in benchmarks
    )
    if not benchmarks_present:
        raise FullUniverseMomentumFetchError(
            "SPY/QQQ benchmark series missing or too short in the fetched window; fail-closed rather than write a "
            "packet the producer will reject (relative-strength needs both benchmarks)"
        )

    packet = _build_packet(
        generated_at=generated_at,
        artifact=artifact,
        price_basis_ymd=price_basis_ymd,
        grouped_session_count=len(grouped_sessions),
        series_by_ticker=series_by_ticker,
    )
    _validate_schema(packet, PACKET_SCHEMA_PATH, label="full-universe momentum series packet")

    ohlcv_packet = None
    if ohlcv_packet_resolved is not None:
        # §4.3 overextension OHLCV (cut 2b-iii): reconstruct ELIGIBLE-ONLY (no benchmarks — overextension is a
        # per-ticker ABSOLUTE signal, and the 2b-ii-B producer's envelope requires packet keys ⊆ eligible) from the
        # SAME grouped window, retaining high/low for ATR. The momentum packet above is unaffected (byte-identical).
        ohlcv_series_by_ticker = reconstruct_ohlcv_series_from_grouped(
            grouped_sessions, tickers=sorted(eligible), as_of=price_basis_ymd,
            session=SESSION_LABEL, adjustment_mode=ADJUSTMENT_MODE,
        )
        ohlcv_packet = _build_ohlcv_packet(
            generated_at=generated_at, artifact=artifact, price_basis_ymd=price_basis_ymd,
            grouped_session_count=len(grouped_sessions), ohlcv_series_by_ticker=ohlcv_series_by_ticker,
        )
        _validate_schema(ohlcv_packet, OHLCV_PACKET_SCHEMA_PATH, label="full-universe OHLCV series packet")

    summary = _build_summary(
        generated_at=generated_at,
        artifact=artifact,
        price_basis_ymd=price_basis_ymd,
        eligible_count=len(eligible),
        benchmarks_present=benchmarks_present,
        stats=stats,
        points_stats=_points_stats(series_by_ticker),
        grouped_session_count=len(grouped_sessions),
        candidate_path=candidate_path,
        packet_path=packet_path,
        summary_path=summary_resolved,
        ohlcv_packet_path=ohlcv_packet_resolved,
    )
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="full-universe momentum fetch summary")
    # Secret-scan the tracked summary (key + provider-domain deny-list) BEFORE writing either artifact.
    universe_fetch._assert_text_safe(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", [massive_key])

    universe_fetch._write_json_atomic(packet, packet_path)
    written = [packet_path]
    try:
        if ohlcv_packet is not None:
            universe_fetch._write_json_atomic(ohlcv_packet, ohlcv_packet_resolved)
            written.append(ohlcv_packet_resolved)
        universe_fetch._write_summary_safe(summary, summary_resolved, [massive_key])
    except BaseException:
        for path in written:  # all-or-nothing: no orphan packet(s) if a later write fails
            path.unlink(missing_ok=True)
        raise
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "GATED (SR-PROVIDER-001) full-universe momentum grouped-window fetch: reuse the proven Massive "
            "grouped-daily path over ~64-90 sessions, reconstruct a bounded eligible+benchmark per-ticker series "
            "packet (gitignored), and write a counts-only secret-scanned tracked summary. Requires explicit user "
            "authorization + MASSIVE_API_KEY; never prints/stores the key/URL or the raw whole-market window."
        )
    )
    parser.add_argument("--candidate-artifact-path", type=Path, default=DEFAULT_CANDIDATE_ARTIFACT_PATH)
    parser.add_argument("--series-packet-path", type=Path, default=None)
    parser.add_argument("--ohlcv-series-packet-path", type=Path, default=None)
    parser.add_argument("--summary-path", type=Path, default=None)
    parser.add_argument("--calendar-path", type=Path, default=CALENDAR_PRESET)
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--session-window", type=int, default=SESSION_WINDOW_TARGET)
    parser.add_argument("--confirm-user-authorization", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_fetch(
        candidate_artifact_path=args.candidate_artifact_path,
        series_packet_path=args.series_packet_path,
        summary_path=args.summary_path,
        calendar_path=args.calendar_path,
        generated_at=args.generated_at,
        confirm_user_authorization=args.confirm_user_authorization,
        session_window=args.session_window,
        ohlcv_series_packet_path=args.ohlcv_series_packet_path,
    )
    print(json.dumps(
        {
            "status": summary["scope"]["status"],
            "sessions_with_data": summary["fetch_stats"]["sessions_with_data"],
            "grouped_calls_made": summary["fetch_stats"]["grouped_calls_made"],
            "series_ticker_count": summary["coverage"]["series_ticker_count"],
            "benchmarks_present": summary["coverage"]["benchmarks_present"],
            "summary_path": summary["paths"]["summary_path"],
        },
        ensure_ascii=False, indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
