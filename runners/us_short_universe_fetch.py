"""US-short universe fetch via Massive + SEC (all free, no broker) + Pass1 gate — batch5 provider/live.

Authorization: user_chat_20260626_universe_fetch
Design: docs/us_short_system_design.md §4.0 (Universe + Pass1) / §2.1 (canonical 决策日) / §3.2 (lineage) /
        §18.0 P0 / §18.1 #2 / §18.2 batch5

Data path (all free, pure HTTP — NO broker, no order, no paid subscription):
  - Tickers + CIK + exchange : SEC company_tickers_exchange.json   (1 free call, ~7600 NYSE/NASDAQ)
  - Close price + volume      : Massive grouped daily — ONE call per trading day returns OHLCV for ALL US
                                stocks (/v2/aggs/grouped/locale/us/market/stocks/{date}). We fetch the
                                ADV WINDOW (the last N trading days, §13.1 #2 prior) so liquidity is a real
                                MULTI-DAY average, not one day's spike/dip.
  - Shares outstanding        : SEC XBRL frames API, merged over recent quarters, latest per CIK (~4 calls)
  - market_cap fallback       : FMP profile marketCap, bounded, only for SEC-missing-shares survivors
                                (multi-class / non-calendar-aligned names absent from SEC frames, e.g. GOOGL)
  - market_cap                : shares (SEC) × close (Massive); else FMP profile marketCap
  - ADV (avg daily $ volume)  : mean over the ADV window of (close × volume) per ticker. A ticker observed on
                                fewer than ADV_MIN_DAYS_REQUIRED days gets adv_usd=None (insufficient coverage
                                → conservative; the gate's adv floor is multi-day, governance preset $5M/day).

Why Massive (replaces the earlier IBKR snapshot attempt): IBKR delayed snapshot volume is unreliable
(0 / garbage deep into the weekend, timing-dependent) and pulling 7600 symbols needs ~19 min + a broker
connection. Massive grouped daily is one call per day, reliable official volume, no broker dependency — so
the us_short surface stays 100% broker-free (§1/§17 "不接券商" unchanged).

Outputs (paths bind to the canonical decision_date, §2.1 — NOT a hardcoded date):
  - Gitignored raw          → provider_samples/us_short_universe_fetch_<decision_date>/raw/
  - Gitignored per-run      → state/us_short/candidate_universe_<decision_date>.json   (per-row lineage
    candidate artifact        artifact: schema+semantic validated BEFORE write; summary recomputed from rows;
                              the path is BOUND to the canonical decision_date (must be exactly this gitignored
                              filename); non-canonical / wrong-date / non-gitignored fail closed, no CLI override)
  - Tracked no-secret summary→ docs/us_short_universe_fetch_summary_<decision_date>.json  (counts only, no prices)

Usage:
  python runners/us_short_universe_fetch.py --confirm-user-authorization --now-et 2026-06-29T08:00:00
Requires env: MASSIVE_API_KEY, SEC_USER_AGENT (FMP_API_KEY optional, for market-cap fallback).
"""
from __future__ import annotations

import argparse
import copy
import gzip as _gzip
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_eligibility_gate import (  # noqa: E402
    cheap_eligible,
    load_eligibility_governance,
    canonical_us_ticker,
)
from engine.us_short_canonical_asof import OutOfWindowError, resolve_canonical_asof  # noqa: E402
from engine.us_short_market_calendar import (  # noqa: E402
    build_sessions,
    load_market_calendar,
    sessions_for_window,
)
from engine import us_short_status_source as _status_source  # noqa: E402
from runners import us_egs_sample_validation as _sv  # noqa: E402

AUTHORIZATION_REF = "user_chat_20260626_universe_fetch"
GOVERNANCE_PRESET = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
CALENDAR_PRESET = ROOT / "presets" / "us_short_market_calendar_2026_2027.json"
CANDIDATE_SCHEMA_PATH = ROOT / "schemas" / "us_short_universe_candidate_artifact.schema.json"
SUMMARY_DIR = ROOT / "docs"
CANDIDATE_LIST_DIR = ROOT / "state" / "us_short"
RAW_ROOT_DIR = ROOT / "provider_samples"

SEC_EXCHANGE_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_FRAMES_URL = "https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/{q}.json"
SEC_SHARE_FRAMES = ["CY2026Q1I", "CY2025Q4I", "CY2025Q3I", "CY2025Q2I"]
SEC_FAIR_ACCESS_SLEEP = 0.15
EXCHANGE_WHITELIST = ("NYSE", "NASDAQ")
NASDAQ_TRADE_HALTS_RSS_URL = "https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts"

MASSIVE_GROUPED_URL = "https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/{date}?apiKey={key}"
MASSIVE_GROUPED_REQUEST_INTERVAL_SECONDS = 13.0
MASSIVE_RATE_LIMIT_RETRY_SECONDS = 65.0
MASSIVE_RATE_LIMIT_MAX_RETRIES = 2

# ADV window (§13.1 #2 liquidity prior — measurement methodology, recorded per-run in lineage so it is
# auditable and cannot silently drift to a 1-day spike). 20 trading days ≈ one trading month smooths a
# single-day spike/dip; a ticker observed on < MIN days has no trustworthy ADV → conservative null.
ADV_WINDOW_TRADING_DAYS = 20
ADV_MIN_DAYS_REQUIRED = 10
# Try this many extra recent sessions beyond the window to absorb Massive's delayed-data lag (recent
# sessions may not be published yet); we still collect only up to ADV_WINDOW_TRADING_DAYS days WITH data.
ADV_WINDOW_FETCH_BUFFER_SESSIONS = 12

PROVIDER_LABEL = "massive_grouped_daily + sec_shares (+ fmp mktcap fallback)"
ROW_PROVIDER_ID = "massive_grouped_daily+sec_xbrl_frames(+fmp_profile)"

FMP_PROFILE_URL = "https://financialmodelingprep.com/stable/profile?symbol={sym}&apikey={key}"
FMP_FALLBACK_SLEEP = 0.2
FMP_FREE_DAILY_CAP = 240
_RUN_STATE_SEVERITY = {"clean": 0, "usable_with_fallback": 1, "restricted": 2, "blocked": 3}


def _is_finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _iso_from_yyyymmdd(d: str) -> str:
    """'YYYYMMDD' -> 'YYYY-MM-DD' (Massive's grouped-daily date format)."""
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def _check_gitignore() -> bool:
    gi = ROOT / ".gitignore"
    return gi.exists() and "provider_samples/" in gi.read_text(encoding="utf-8")


def _git_check_ignored(path: Path) -> bool:
    """True if `path` is actually gitignored (real `git check-ignore`, not a hard-coded claim)."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", str(path)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


def _assert_text_safe(text: str, sensitive: list[str]) -> None:
    """Fail-closed scan of serialized summary text: no API key / request URL / provider-domain leak."""
    lower = text.lower()
    for fragment in ("apikey=", "api.massive.com", "financialmodelingprep.com",
                     "data.sec.gov", "www.sec.gov", "nasdaqtrader.com"):
        if fragment in lower:
            raise RuntimeError(f"tracked summary contains forbidden fragment: {fragment}")
    for value in sensitive:
        if value and value in text:
            raise RuntimeError("tracked summary contains a sensitive environment value")


def _worst_run_state(states: list[str]) -> str:
    return max(states, key=lambda state: _RUN_STATE_SEVERITY[state])


def _build_run_fetch_provider_health(
    *,
    status_source_outcome: dict[str, Any],
    fallback_needed_count: int,
    fmp_attempted: int,
    fmp_rescued: int,
) -> dict[str, Any]:
    """Summarize provider run-state from already-observed run outcomes.

    Massive grouped daily and SEC bulk calls are critical for this runner; if they fail, `run_fetch` raises before
    any completed summary is emitted. FMP market-cap fallback is opportunistic: it can rescue SEC-missing-share
    names, but partial/no rescue must not be laundered into provider-readiness evidence.
    """
    status_state = "clean"
    if status_source_outcome.get("block_or_no_emit"):
        status_state = "blocked"
    elif status_source_outcome.get("critical_failed"):
        status_state = "restricted"

    if fallback_needed_count <= 0:
        fmp_state = "clean"
    else:
        fmp_state = "usable_with_fallback"

    return {
        "overall_run_state": _worst_run_state(["clean", status_state, fmp_state]),
        "critical_sources": {
            "massive_grouped_daily": "clean",
            "sec_edgar": "clean",
        },
        "status_sources": {
            "state": status_state,
            "outcome": status_source_outcome,
        },
        "opportunistic_fallbacks": {
            "fmp_profile_market_cap": {
                "state": fmp_state,
                "needed_count": fallback_needed_count,
                "attempted_count": fmp_attempted,
                "rescued_count": fmp_rescued,
                "unresolved_count": max(fallback_needed_count - fmp_rescued, 0),
                "provider_readiness_evidence": False,
                "policy": "opportunistic_rescue_only_not_provider_readiness",
            },
        },
        "critical_failure_no_emit_policy": True,
        "provider_selection_or_production_claimed": False,
    }


def _assert_summary_safe(path: Path, sensitive: list[str]) -> None:
    """Fail-closed scan of the tracked summary FILE (post-write belt; the primary scan is pre-write)."""
    _assert_text_safe(path.read_text(encoding="utf-8"), sensitive)


def _write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp.replace(path)


def _write_summary_safe(summary: Any, path: Path, sensitive: list[str]) -> None:
    """Scan the serialized summary BEFORE any write (R-USSHORT-BATCH5-UNIVERSE-FETCH-SECRET-SCAN-GITIGNORE-GAP):
    a scan failure raises with NO new/replaced file and NO secret-bearing residue (the prior post-write scan left
    the rejected file on disk). The scanned text is byte-identical to what `_write_json_atomic` writes."""
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text, sensitive)        # fail-closed BEFORE the temp file / atomic replace exists
    _write_json_atomic(summary, path)


def _sec_get(url: str, sec_ua: str) -> Any:
    host = "data.sec.gov" if "data.sec.gov" in url else "www.sec.gov"
    headers = {"User-Agent": sec_ua, "Host": host, "Accept-Encoding": "gzip, deflate"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":
        raw = _gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------------------
# SEC: ticker + CIK + exchange
# ---------------------------------------------------------------------------

def fetch_sec_tickers(sec_ua: str) -> dict[str, dict[str, Any]]:
    """Return {canonical_ticker: {"cik": int, "exchange": str}} for NYSE/NASDAQ."""
    data = _sec_get(SEC_EXCHANGE_TICKERS_URL, sec_ua)
    fields = data.get("fields", [])
    rows = data.get("data", [])
    for req_field in ("ticker", "exchange", "cik"):
        if req_field not in fields:
            raise RuntimeError(f"SEC tickers response missing field {req_field!r}: {fields}")
    t_idx, e_idx, c_idx = fields.index("ticker"), fields.index("exchange"), fields.index("cik")
    norm = {"NYSE": "NYSE", "Nasdaq": "NASDAQ", "NASDAQ": "NASDAQ"}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        exch = norm.get(str(row[e_idx] if e_idx < len(row) else ""), "")
        if exch not in EXCHANGE_WHITELIST:
            continue
        ct = canonical_us_ticker(row[t_idx] if t_idx < len(row) else "")
        cik = row[c_idx] if c_idx < len(row) else None
        if ct and ct not in out and isinstance(cik, int):
            out[ct] = {"cik": cik, "exchange": exch}
    return out


# ---------------------------------------------------------------------------
# Status-source live producer: ticker reference + current exchange halt feed
# ---------------------------------------------------------------------------

def _status_as_of_from_decision_date(decision_date: str) -> str:
    if not (isinstance(decision_date, str) and len(decision_date) == 8 and decision_date.isdigit()):
        raise RuntimeError(f"decision_date must be YYYYMMDD for status-source as_of: {decision_date!r}")
    return _iso_from_yyyymmdd(decision_date)


def _ticker_reference_payload_from_sec_map(sec_map: dict[str, dict[str, Any]], *, observed_at: str) -> dict[str, Any]:
    active_listings: dict[str, dict[str, Any]] = {}
    for symbol, meta in sec_map.items():
        ct = canonical_us_ticker(symbol)
        exchange = meta.get("exchange") if isinstance(meta, dict) else None
        if ct is None or exchange not in EXCHANGE_WHITELIST:
            raise RuntimeError(f"SEC ticker map contains non-canonical / non-whitelisted listing: {symbol!r}")
        active_listings[ct] = {"active": True, "primary_exchange": exchange}
    return {
        "observed": True,
        "observed_at": observed_at,
        "coverage": "full",
        "active_listings": active_listings,
    }


def _local_xml_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _xml_child_text(item: ElementTree.Element, name: str) -> str:
    target = name.lower()
    for child in item:
        if _local_xml_name(child.tag).lower() == target:
            return "".join(child.itertext()).strip()
    return ""


def _symbol_from_halt_item(item: ElementTree.Element) -> str | None:
    issue_symbol = _xml_child_text(item, "IssueSymbol")
    if not issue_symbol:
        return None
    return canonical_us_ticker(issue_symbol)


def parse_halt_symbols_from_rss(xml_text: str) -> list[str]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise RuntimeError("Nasdaq trade-halt RSS did not parse as XML") from exc
    items = [elem for elem in root.iter() if _local_xml_name(elem.tag).lower() == "item"]
    symbols = set()
    unparseable = 0
    for item in items:
        symbol = _symbol_from_halt_item(item)
        if symbol is None:
            unparseable += 1
        else:
            symbols.add(symbol)
    if unparseable:
        raise RuntimeError(
            f"Nasdaq trade-halt RSS contained {unparseable} unparseable item(s); treating halt feed as down")
    return sorted(symbols)


def fetch_nasdaq_trade_halt_feed(*, observed_at: str) -> dict[str, Any]:
    req = urllib.request.Request(
        NASDAQ_TRADE_HALTS_RSS_URL,
        headers={"User-Agent": "StockSystem/0.1 us-short-status-source"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return {
        "observed": True,
        "observed_at": observed_at,
        "halted_symbols": parse_halt_symbols_from_rss(body),
    }


def _status_source_state_from_observed_payload(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return "missing"
    if isinstance(payload, dict) and payload.get("observed") is True:
        return "ok"
    return "down"


def build_live_status_records(
    sec_map: dict[str, dict[str, Any]],
    *,
    decision_date: str,
    observed_at: str,
    halt_feed: dict[str, Any] | None,
    halt_feed_state: str,
    bankruptcy_screen: dict[str, Any] | None = None,
    bankruptcy_submissions_by_ticker: dict[str, Any] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Build runner-consumable status_records from reviewed live status sources.

    This is the live 1b wiring for the already-reviewed offline status parser. It consumes the SEC ticker map
    already fetched by `fetch_sec_tickers` as the full active-listing reference, consumes the Nasdaq current halt
    feed, and can consume either a caller-supplied SEC 8-K Item 1.03 bankruptcy screen or caller-supplied SEC
    submissions payloads that are assembled into that screen. This function never fetches the bankruptcy payloads
    itself; `run_fetch` can now consume a reviewed, gitignored screen path when explicitly supplied. If both
    critical status sources fail, classify_status_source_outcomes blocks/no-emits before candidate artifacts can
    be written.
    """
    if bankruptcy_screen is not None and bankruptcy_submissions_by_ticker is not None:
        raise RuntimeError("provide only one bankruptcy source shape: screen or SEC submissions")
    status_as_of = _status_as_of_from_decision_date(decision_date)
    if bankruptcy_submissions_by_ticker is not None:
        bankruptcy_screen = _status_source.build_bankruptcy_screen_from_sec_submissions(
            as_of=status_as_of,
            observed_at=observed_at,
            submissions_by_ticker=bankruptcy_submissions_by_ticker,
        )
    ticker_reference = _ticker_reference_payload_from_sec_map(sec_map, observed_at=observed_at) if sec_map else None
    outcomes = {
        "ticker_reference": "ok" if ticker_reference is not None else "missing",
        "exchange_halt_feed": halt_feed_state,
        "sec_8k_item_103": _status_source_state_from_observed_payload(bankruptcy_screen),
    }
    status_source_outcome = _status_source.classify_status_source_outcomes(outcomes)
    if status_source_outcome["block_or_no_emit"]:
        raise RuntimeError("all critical status sources failed; refusing to emit a candidate artifact")

    records = {
        symbol: _status_source.resolve_status_record(
            symbol,
            ticker_reference=ticker_reference,
            halt_feed=halt_feed,
            bankruptcy_screen=bankruptcy_screen,
            as_of=status_as_of,
            observed_at=observed_at,
        )
        for symbol in sec_map
    }
    payloads = {
        "ticker_reference": ticker_reference,
        "exchange_halt_feed": halt_feed,
        "sec_8k_item_103": bankruptcy_screen,
    }
    return records, status_source_outcome, payloads


# ---------------------------------------------------------------------------
# SEC: bulk shares outstanding via frames (latest per CIK across quarters)
# ---------------------------------------------------------------------------

def fetch_sec_shares(sec_ua: str, *, frames: list[str] = SEC_SHARE_FRAMES) -> dict[int, dict[str, Any]]:
    """Return {cik: {"shares": float, "end": str}} keeping the latest 'end' per CIK across frames.

    F2 (cc_r1_v1): if EVERY frame request fails (SEC source down) RAISE — never return an empty map that
    silently yields a degraded near-empty eligible universe with NO health signal (asymmetric with the Massive
    auth path which already raises). A single failed frame is tolerated (other quarters still merge the latest
    shares per CIK)."""
    by_cik: dict[int, dict[str, Any]] = {}
    failed = 0
    for q in frames:
        try:
            data = _sec_get(SEC_FRAMES_URL.format(q=q), sec_ua)
        except Exception:
            failed += 1
            continue
        for item in data.get("data", []):
            cik = item.get("cik")
            val = item.get("val")
            end = item.get("end", "")
            if not isinstance(cik, int) or not _is_finite(val) or val <= 0:
                continue
            prev = by_cik.get(cik)
            if prev is None or end > prev["end"]:
                by_cik[cik] = {"shares": float(val), "end": end}
        time.sleep(SEC_FAIR_ACCESS_SLEEP)
    if failed == len(frames):
        raise RuntimeError(
            f"all {len(frames)} SEC share frames failed (SEC source unavailable); fail-closed rather than "
            "emit a silently-degraded universe with no shares/market-cap")
    return by_cik


# ---------------------------------------------------------------------------
# Massive: grouped daily (one call per trading day → all US stocks close + volume)
# ---------------------------------------------------------------------------

def _massive_grouped_for_date(date_str: str, key: str) -> list[dict[str, Any]]:
    url = MASSIVE_GROUPED_URL.format(date=date_str, key=key)
    req = urllib.request.Request(url, headers={"User-Agent": "StockSystem/0.1 us-short-universe"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("results") or []


def adv_window_session_dates(price_basis_date: str, calendar: dict, *, count: int) -> list[str]:
    """The last `count` market sessions with date <= price_basis_date (YYYYMMDD), newest-first, as YYYY-MM-DD.

    Sessions come from the FROZEN NYSE/NASDAQ calendar (holidays/half-days already excluded), so the only
    days that come back empty from Massive are delayed-not-yet-published days — which `fetch_massive_window`
    skips. This is the EXPECTED trading-day basis of the multi-day ADV average.
    """
    pbd = datetime.strptime(price_basis_date, "%Y%m%d").date()
    span = count * 2 + 21
    lo = max((pbd - timedelta(days=span)).strftime("%Y%m%d"), calendar["start_date"])
    sessions = build_sessions(lo, price_basis_date, calendar=calendar)  # ascending, inside frozen range
    dates = [s["date"] for s in sessions if s["date"] <= price_basis_date][-count:]
    return [_iso_from_yyyymmdd(d) for d in reversed(dates)]   # newest-first ISO


def _aggregate_window(collected: list[tuple[str, list[dict[str, Any]]]]) -> dict[str, dict[str, Any]]:
    """collected = [(date_iso, results), ...] newest-first -> {ticker: {close, volume, price_as_of,
    _adv_sum, adv_days_observed}}. price/volume captured from the NEWEST day the ticker appears; the ADV
    accumulator only counts days with BOTH a finite close and a finite volume."""
    md: dict[str, dict[str, Any]] = {}
    for date_iso, results in collected:   # newest-first
        for row in results:
            ct = canonical_us_ticker(row.get("T"))
            if not ct:
                continue
            close = row.get("c")
            vol = row.get("v")
            acc = md.setdefault(ct, {"close": None, "volume": None, "price_as_of": None,
                                     "_adv_sum": 0.0, "adv_days_observed": 0})
            if acc["close"] is None and _is_finite(close):
                acc["close"] = float(close)
                acc["volume"] = float(vol) if _is_finite(vol) else None
                acc["price_as_of"] = date_iso
            if _is_finite(close) and _is_finite(vol):
                acc["_adv_sum"] += float(close) * float(vol)
                acc["adv_days_observed"] += 1
    return md


def _finalize_adv(md: dict[str, dict[str, Any]], *, min_days: int) -> None:
    """adv_usd = mean dollar volume over observed days, or None if observed days < min_days (insufficient
    coverage → conservative; the gate then fails closed on adv_usd_unknown_or_invalid)."""
    for acc in md.values():
        n = acc["adv_days_observed"]
        s = acc.pop("_adv_sum")
        acc["adv_usd"] = (s / n) if n >= min_days else None


def fetch_massive_window(
    key: str,
    session_dates_desc: list[str],
    *,
    window: int = ADV_WINDOW_TRADING_DAYS,
    min_days: int = ADV_MIN_DAYS_REQUIRED,
) -> tuple[str, list[str], dict[str, dict[str, Any]]]:
    """Fetch the ADV window. `session_dates_desc` = candidate trading days (YYYY-MM-DD) newest-first.

    Steps through the candidates, fetching Massive grouped daily for each, SKIPPING empty days (Massive's
    delayed-data lag), and collects up to `window` days WITH data. Returns (used_date, observed_window_dates
    newest-first, market_data). An auth/quota HTTP error (401/403/429) is RAISED (never masked as a missing
    trading day, §3.7). If fewer than `min_days` days come back with data, raises (insufficient for ADV).
    """
    collected: list[tuple[str, list[dict[str, Any]]]] = []
    request_count = 0
    for d in session_dates_desc:
        if len(collected) >= window:
            break
        retry_count = 0
        try:
            while True:
                if request_count > 0 and retry_count == 0:
                    time.sleep(MASSIVE_GROUPED_REQUEST_INTERVAL_SECONDS)
                request_count += 1
                try:
                    results = _massive_grouped_for_date(d, key)
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code == 429 and retry_count < MASSIVE_RATE_LIMIT_MAX_RETRIES:
                        retry_count += 1
                        time.sleep(MASSIVE_RATE_LIMIT_RETRY_SECONDS)
                        continue
                    raise
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 429):
                raise RuntimeError(
                    f"Massive grouped daily HTTP {exc.code} (auth/quota/rate-limit after {retry_count} "
                    "retry attempt(s)); not a missing trading day"
                ) from exc
            continue
        if results:
            collected.append((d, results))
    if len(collected) < min_days:
        raise RuntimeError(
            f"Massive returned data for only {len(collected)} of the ADV window days (< min {min_days}); "
            "insufficient to compute a multi-day ADV"
        )
    used_date = collected[0][0]
    observed_dates = [d for d, _ in collected]
    market_data = _aggregate_window(collected)
    _finalize_adv(market_data, min_days=min_days)
    return used_date, observed_dates, market_data


# ---------------------------------------------------------------------------
# FMP fallback: market cap only for SEC-missing-shares survivors (bounded, free tier)
# ---------------------------------------------------------------------------

def fetch_fmp_market_caps(tickers: list[str], fmp_key: str, *, budget: int = FMP_FREE_DAILY_CAP) -> dict[str, float]:
    """Fetch marketCap from FMP stable/profile for a BOUNDED set (SEC-missing-shares survivors). Stops at
    `budget` calls or HTTP 429/403. Returns {ticker: market_cap}."""
    out: dict[str, float] = {}
    calls = 0
    for sym in tickers:
        if calls >= budget:
            break
        time.sleep(FMP_FALLBACK_SLEEP)
        url = FMP_PROFILE_URL.format(sym=urllib.parse.quote(sym), key=fmp_key)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "StockSystem/0.1 us-short-universe-mktcap"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                break
            calls += 1
            continue
        except Exception:
            calls += 1
            continue
        calls += 1
        row = payload[0] if isinstance(payload, list) and payload else (payload if isinstance(payload, dict) else None)
        if isinstance(row, dict):
            mc = row.get("marketCap")
            if _is_finite(mc) and mc > 0:
                out[sym] = float(mc)
    return out


# ---------------------------------------------------------------------------
# Pass1 gate → per-row lineage records (market_cap = SEC shares × close; ADV = multi-day average)
# ---------------------------------------------------------------------------

def _coverage_status(price: Any, shares: Any, adv_days: int, window_days: int, min_days: int) -> str:
    if not _is_finite(price):
        return "no_price"
    if adv_days < min_days:
        return "adv_insufficient"
    if not _is_finite(shares):
        return "no_shares"
    if adv_days < window_days:
        return "adv_partial"
    return "complete"


def apply_pass1(
    sec_tickers: dict[str, dict[str, Any]],
    sec_shares: dict[int, dict[str, Any]],
    market_data: dict[str, dict[str, Any]],
    *,
    governance: dict[str, Any],
    fmp_caps: dict[str, float] | None = None,
    status_records: dict[str, dict[str, Any]] | None = None,
    as_of: str,
    observed_at: str,
    window_days: int = ADV_WINDOW_TRADING_DAYS,
    min_days: int = ADV_MIN_DAYS_REQUIRED,
) -> list[dict[str, Any]]:
    """Pass1 over the universe -> ONE per-row lineage record per ticker (eligible AND not).

    price/volume/adv_usd come from `market_data` (Massive multi-day window: adv_usd is the AVERAGE daily
    dollar volume, None when coverage < min_days). market_cap = SEC shares × close (else fmp_caps[ticker]).
    Each row carries the Pass1 inputs, the gate verdict + reasons, and §3.2 lineage (price_source / ADV
    window coverage / shares source / market_cap source / as_of / observed_at). The summary is recomputed
    from these rows by `summarize_rows` (single source).
    """
    fmp_caps = fmp_caps or {}
    status_supplied = status_records is not None
    if status_supplied and not isinstance(status_records, dict):
        raise RuntimeError("status_records must be a dict keyed by canonical ticker")
    rows: list[dict[str, Any]] = []
    for sym, meta in sec_tickers.items():
        d = market_data.get(sym) or {}
        price = d.get("close")
        volume = d.get("volume")
        adv_usd = d.get("adv_usd")
        adv_days = int(d.get("adv_days_observed") or 0)
        price_as_of = d.get("price_as_of")
        shares_rec = sec_shares.get(meta["cik"])
        shares = shares_rec["shares"] if shares_rec else None

        market_cap = None
        market_cap_source = "none"
        shares_source = "sec_xbrl_frames" if _is_finite(shares) else "none"
        if _is_finite(shares) and _is_finite(price):
            market_cap = float(shares) * float(price)
            market_cap_source = "sec_shares_x_close"
        if market_cap is None and sym in fmp_caps and _is_finite(fmp_caps[sym]):
            market_cap = float(fmp_caps[sym])
            market_cap_source = "fmp_profile"

        status_values = {flag: False for flag in _status_source.DISQUALIFYING_FLAGS}
        status_record = None
        if status_supplied:
            if sym not in status_records:
                raise RuntimeError(f"missing status record for {sym}")
            status_record = status_records[sym]
            row_flags, _ = _status_source.status_flags_for_row(status_record, row_ticker=sym)
            status_values = {
                flag: row_flags[flag] if flag in row_flags else None
                for flag in _status_source.DISQUALIFYING_FLAGS
            }

        gate_row = {
            "ticker": sym, "exchange": meta["exchange"],
            "price": price, "adv_usd": adv_usd, "market_cap_usd": market_cap,
            "delisted": status_values["delisted"],
            "halted": status_values["halted"],
            "bankruptcy": status_values["bankruptcy"],
            "otc": status_values["otc"],
        }
        verdict = cheap_eligible(gate_row, governance=governance)

        row = {
            "ticker": verdict["ticker"] or sym,
            "exchange": meta["exchange"],
            "price": price if _is_finite(price) else None,
            "price_as_of": price_as_of,
            "volume": volume if _is_finite(volume) else None,
            "adv_usd": adv_usd if _is_finite(adv_usd) else None,
            "adv_days_observed": adv_days,
            "adv_coverage_ok": adv_days >= min_days,
            "shares": float(shares) if _is_finite(shares) else None,
            "market_cap_usd": market_cap if _is_finite(market_cap) else None,
            "market_cap_source": market_cap_source,
            "delisted": status_values["delisted"],
            "halted": status_values["halted"],
            "bankruptcy": status_values["bankruptcy"],
            "otc": status_values["otc"],
            "status_flags_sourced": status_supplied,
            "eligible": verdict["eligible"],
            "reasons": verdict["reasons"],
            "provider_id": ROW_PROVIDER_ID,
            "as_of": as_of,
            "observed_at": observed_at,
            "coverage_status": _coverage_status(price, shares, adv_days, window_days, min_days),
            "parser_status": "ok",
            "lineage": {
                "price_source": "massive_grouped_daily",
                "adv_window_trading_days": window_days,
                "adv_days_observed": adv_days,
                "shares_source": shares_source,
                "market_cap_source": market_cap_source,
            },
        }
        if status_supplied:
            row["status_provenance"] = copy.deepcopy(status_record)
        rows.append(row)
    return rows


def eligible_tickers_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    return [r["ticker"] for r in rows if r["eligible"]]


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute the Pass1 summary FROM the per-row records (single source of the counts; the artifact and
    the tracked summary both derive from this, and validation fails closed if a stored summary disagrees)."""
    reason_counts: dict[str, int] = {}
    ineligible = no_price = no_shares = 0
    needs_market_cap: list[str] = []
    for r in rows:
        if not r["eligible"]:
            ineligible += 1
            for rs in r["reasons"]:
                reason_counts[rs] = reason_counts.get(rs, 0) + 1
            if r["reasons"] == ["market_cap_usd_unknown_or_invalid"]:
                needs_market_cap.append(r["ticker"])
        if r["price"] is None:
            no_price += 1
        if r["shares"] is None:
            no_shares += 1
    return {
        "eligible_count": len(eligible_tickers_from_rows(rows)),
        "ineligible_count": ineligible,
        "no_price_count": no_price,
        "no_shares_count": no_shares,
        "needs_market_cap": needs_market_cap,
        "total_tickers": len(rows),
        "reason_distribution": reason_counts,
    }


# ---------------------------------------------------------------------------
# Per-run candidate artifact: build + schema/semantic validate BEFORE write
# ---------------------------------------------------------------------------

def build_candidate_artifact(
    *,
    rows: list[dict[str, Any]],
    decision_date: str,
    price_basis_date: str,
    used_date: str,
    observed_window_dates: list[str],
    generated_at: str,
    calendar_verification_status: str,
    window_days: int = ADV_WINDOW_TRADING_DAYS,
    min_days: int = ADV_MIN_DAYS_REQUIRED,
) -> dict[str, Any]:
    eligible = eligible_tickers_from_rows(rows)
    return {
        "schema_name": "us_short_universe_candidate_artifact",
        "schema_version": "1.1.0",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": generated_at,
        "decision_date": decision_date,
        "price_basis_date": price_basis_date,
        "used_date": used_date,
        "calendar_verification_status": calendar_verification_status,
        "provider": PROVIDER_LABEL,
        "adv_window": {
            "trading_days": window_days,
            "min_days_required": min_days,
            "observed_window_dates": observed_window_dates,
            "latest_date": used_date,
        },
        "rows": rows,
        "row_count": len(rows),
        "eligible_tickers": eligible,
        "eligible_count": len(eligible),
        "summary": summarize_rows(rows),
    }


def validate_candidate_artifact(artifact: dict[str, Any], *, expected_decision_date: str,
                                governance: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed schema + cross-field semantic validation of the per-run artifact BEFORE write.

    jsonschema (import-or-fail-closed) enforces the closed-world shape + per-row lineage; then the semantic
    layer enforces what schema can't: summary == recompute(rows), row_count/eligible consistency, path-bound
    decision_date, and that NO eligible row slipped through with a null / below-floor / under-covered ADV
    (the multi-day-ADV honesty the finding requires). Returns the artifact; raises on any violation.
    """
    try:
        import jsonschema
    except ImportError as exc:
        raise RuntimeError("jsonschema 未安装；无法校验 universe candidate artifact，拒绝降级写出") from exc
    schema = json.loads(CANDIDATE_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(artifact, schema)   # raises jsonschema.ValidationError on a shape/lineage gap

    rows = artifact["rows"]
    if artifact["summary"] != summarize_rows(rows):
        raise RuntimeError("artifact.summary 与按行重算不一致（summary 必须从行数据派生）")
    if artifact["row_count"] != len(rows):
        raise RuntimeError("artifact.row_count 与 rows 长度不一致")
    eligible = eligible_tickers_from_rows(rows)
    if artifact["eligible_tickers"] != eligible or artifact["eligible_count"] != len(eligible):
        raise RuntimeError("artifact.eligible_tickers/eligible_count 与行 verdict 不一致")
    if len(set(eligible)) != len(eligible):
        raise RuntimeError("eligible_tickers 含重复（候选集须唯一）")
    if artifact["decision_date"] != expected_decision_date:
        raise RuntimeError("artifact.decision_date 与输出路径绑定的 decision_date 不一致")

    # Per-row anti-forgery (F1, cc_r1_v1): re-derive EACH row's verdict / coverage / lineage / status /
    # clock from its OWN stored Pass1 inputs + the artifact's declared window+clock, and fail closed on ANY
    # disagreement. The prior validator re-derived only the AGGREGATION (summary / eligible set) and TRUSTED
    # the stored per-row verdict+lineage, so a tampered ineligible→eligible row on a non-ADV disqualifier
    # (price/market_cap/status below floor) passed — contradicting the artifact's "prove WHY a ticker entered"
    # guarantee. Now the whole per-row class is re-derived.
    used_date = artifact["used_date"]
    generated_at = artifact["generated_at"]
    aw = artifact["adv_window"]
    window_days = aw["trading_days"]
    min_days = aw["min_days_required"]
    if aw["latest_date"] != used_date:
        raise RuntimeError("adv_window.latest_date 须等于 used_date")
    for r in rows:
        gate_row = {"ticker": r["ticker"], "exchange": r["exchange"], "price": r["price"],
                    "adv_usd": r["adv_usd"], "market_cap_usd": r["market_cap_usd"],
                    "delisted": r["delisted"], "halted": r["halted"],
                    "bankruptcy": r["bankruptcy"], "otc": r["otc"]}
        v = cheap_eligible(gate_row, governance=governance)
        if r["eligible"] != v["eligible"] or r["reasons"] != v["reasons"]:
            raise RuntimeError(f"行 {r['ticker']} 的 eligible/reasons 与按存储输入重算的 cheap_eligible 不一致（反伪造）")
        if r["status_flags_sourced"] is False:
            if "status_provenance" in r or any(
                    r[f] is not False for f in _status_source.DISQUALIFYING_FLAGS):
                raise RuntimeError(
                    f"row {r['ticker']} unsourced status row must keep all status flags false")
        elif r["status_flags_sourced"] is True:
            status_record = r.get("status_provenance")
            row_flags, _ = _status_source.status_flags_for_row(status_record, row_ticker=r["ticker"])
            for flag in _status_source.DISQUALIFYING_FLAGS:
                expected = row_flags[flag] if flag in row_flags else None
                if r[flag] is not expected:
                    raise RuntimeError(
                        f"row {r['ticker']} status {flag} disagrees with stored status_provenance")
        else:
            raise RuntimeError(f"row {r['ticker']} status_flags_sourced must be bool")
        if r["adv_coverage_ok"] != (r["adv_days_observed"] >= min_days):
            raise RuntimeError(f"行 {r['ticker']} 的 adv_coverage_ok 与 adv_days_observed/min_days 不一致")
        if r["coverage_status"] != _coverage_status(r["price"], r["shares"], r["adv_days_observed"], window_days, min_days):
            raise RuntimeError(f"行 {r['ticker']} 的 coverage_status 与输入重算不一致")
        mcs, mc, sh, px = r["market_cap_source"], r["market_cap_usd"], r["shares"], r["price"]
        # market_cap_source re-derived by the PRODUCER PRECEDENCE (apply_pass1), not source-label-first
        # (Codex cc_r1_v1 residual): SEC shares×price wins WHENEVER both are finite — so a row with SEC
        # shares+price available can NOT carry market_cap_source=fmp_profile/none. fmp_profile is valid only
        # when SEC-derived cap is unavailable + a finite FMP cap is present; none only when no finite cap.
        if _is_finite(sh) and _is_finite(px):
            if mcs != "sec_shares_x_close" or not (_is_finite(mc) and math.isclose(mc, float(sh) * float(px), rel_tol=1e-9)):
                raise RuntimeError(f"行 {r['ticker']} SEC shares×price 可得时 market_cap 必须 sec_shares_x_close 且 == shares×price（producer 优先级反伪造）")
        elif mcs == "fmp_profile":
            if not _is_finite(mc):
                raise RuntimeError(f"行 {r['ticker']} market_cap_source=fmp_profile 但 market_cap_usd 非有限")
        elif mcs == "none":
            if mc is not None:
                raise RuntimeError(f"行 {r['ticker']} market_cap_source=none 但 market_cap_usd 非空")
        else:
            raise RuntimeError(f"行 {r['ticker']} market_cap_source={mcs!r} 但 SEC shares/price 不全可得（producer 优先级反伪造）")
        lin = r["lineage"]
        expected_shares_source = "sec_xbrl_frames" if _is_finite(sh) else "none"
        if (lin["adv_window_trading_days"] != window_days or lin["adv_days_observed"] != r["adv_days_observed"]
                or lin["market_cap_source"] != mcs or lin["shares_source"] != expected_shares_source
                or lin["price_source"] != "massive_grouped_daily"):
            raise RuntimeError(f"行 {r['ticker']} lineage 与存储输入/窗口不一致（反伪造）")
        if r["as_of"] != used_date or r["observed_at"] != generated_at:
            raise RuntimeError(f"行 {r['ticker']} as_of/observed_at 未绑定 run 时钟（as_of=used_date, observed_at=generated_at）")
    return artifact


def _candidate_path_for(decision_date: str) -> Path:
    return CANDIDATE_LIST_DIR / f"candidate_universe_{decision_date}.json"


def _summary_path_for(decision_date: str) -> Path:
    return SUMMARY_DIR / f"us_short_universe_fetch_summary_{decision_date}.json"


def _raw_root_for(decision_date: str) -> Path:
    return RAW_ROOT_DIR / f"us_short_universe_fetch_{decision_date}" / "raw"


def _validate_candidate_path(candidate_list_path: Path, decision_date: str) -> None:
    """Fail-closed BEFORE any provider fetch / write: the per-run candidate artifact carries per-row
    price / ADV / market_cap, so its path is BOUND to the canonical decision_date. It must be EXACTLY
    `state/us_short/candidate_universe_<decision_date>.json` (the gitignored canonical location). One
    rule closes both leak shapes of this finding: (a) a non-gitignored path can never receive prices, and
    (b) a wrong-date / wrong-version filename (e.g. `..._19000101.json` on a 20260629 run) can no longer be
    written, so the filename cannot lie about which decision-date bucket it represents and
    `storage.candidate_artifact_gitignored` can never be false on a completed run. The production CLI no
    longer exposes a `--candidate-list-path` override; the `candidate_list_path` kwarg is a private test
    seam and even it must equal the canonical path. R-USSHORT-BATCH5-PASS1-LIQUIDITY-LINEAGE-CONTRACT-GAP."""
    canonical = _candidate_path_for(decision_date)
    if candidate_list_path.resolve() != canonical.resolve():
        raise RuntimeError(
            "candidate artifact path must be the canonical "
            f"state/us_short/candidate_universe_{decision_date}.json bound to the run's decision_date "
            "(refusing a non-canonical / wrong-date / non-gitignored candidate path)"
        )
    if not _git_check_ignored(canonical):
        raise RuntimeError(
            "canonical candidate artifact path is not gitignored (real git check-ignore=false); "
            "refusing to write per-row prices/ADV/market_cap to a non-ignored location"
        )


def _canonical_bankruptcy_screen_path(path: Path) -> Path:
    raw = Path(path)
    candidate = raw if raw.is_absolute() else ROOT / raw
    canonical = candidate.resolve()
    try:
        canonical.relative_to(CANDIDATE_LIST_DIR.resolve())
    except ValueError as exc:
        raise RuntimeError(
            "bankruptcy screen path must be a gitignored JSON under state/us_short "
            "(refusing arbitrary local file input)"
        ) from exc
    if canonical.suffix.lower() != ".json":
        raise RuntimeError("bankruptcy screen path must be a .json file under state/us_short")
    if not canonical.exists():
        raise RuntimeError(f"bankruptcy screen path does not exist: {_rel(canonical)}")
    if not _git_check_ignored(canonical):
        raise RuntimeError(
            "bankruptcy screen path is not gitignored (real git check-ignore=false); "
            "refusing to consume local source packet output from a tracked location"
        )
    return canonical


def _parse_iso_instant(value: str) -> datetime:
    return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)


def _canonical_screen_rows(screen: dict[str, Any], *, decision_date: str, generated_at: str) -> dict[str, dict[str, Any]]:
    status_as_of = _status_as_of_from_decision_date(decision_date)
    if screen.get("observed") is not True:
        raise RuntimeError("bankruptcy screen payload must have observed=true")
    if not isinstance(screen.get("lookback_window"), str) or not screen["lookback_window"].strip():
        raise RuntimeError("bankruptcy screen payload must carry lookback_window")
    by_ticker = screen.get("by_ticker")
    if not isinstance(by_ticker, dict) or not by_ticker:
        raise RuntimeError("bankruptcy screen payload must carry a non-empty by_ticker object")
    # Let the status-source contract validate source clock/current-window semantics before any provider fetch.
    _status_source.resolve_status_record(
        "AAPL",
        ticker_reference=None,
        halt_feed=None,
        bankruptcy_screen=screen,
        as_of=status_as_of,
        observed_at=generated_at,
    )
    out: dict[str, dict[str, Any]] = {}
    for ticker, rec in by_ticker.items():
        ct = canonical_us_ticker(ticker)
        if ct is None:
            raise RuntimeError(f"bankruptcy screen by_ticker contains non-canonical ticker: {ticker!r}")
        if not isinstance(rec, dict):
            raise RuntimeError(f"bankruptcy screen by_ticker[{ct}] must be an object")
        screen_status = rec.get("screen_status")
        if screen_status not in {"bankrupt_8k_found", "screened_no_filing", "unscreened"}:
            raise RuntimeError(f"bankruptcy screen by_ticker[{ct}] has invalid screen_status: {screen_status!r}")
        if screen_status == "bankrupt_8k_found":
            _status_source.resolve_status_record(
                ct,
                ticker_reference=None,
                halt_feed=None,
                bankruptcy_screen=screen,
                as_of=status_as_of,
                observed_at=generated_at,
            )
        if ct in out and out[ct] != rec:
            raise RuntimeError(f"bankruptcy screen has conflicting duplicate ticker row: {ct}")
        out[ct] = copy.deepcopy(rec)
    return out


def _load_bankruptcy_screen_paths(
    paths: list[Path] | tuple[Path, ...] | None,
    *,
    decision_date: str,
    generated_at: str,
) -> tuple[dict[str, Any] | None, int]:
    if not paths:
        return None, 0
    merged_by_ticker: dict[str, dict[str, Any]] = {}
    observed_ats: list[str] = []
    lookback_window: str | None = None
    for raw_path in paths:
        path = _canonical_bankruptcy_screen_path(raw_path)
        try:
            screen = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"bankruptcy screen path is not valid JSON: {_rel(path)}") from exc
        if not isinstance(screen, dict):
            raise RuntimeError(f"bankruptcy screen path must contain a JSON object: {_rel(path)}")
        rows = _canonical_screen_rows(screen, decision_date=decision_date, generated_at=generated_at)
        lw = screen["lookback_window"]
        if lookback_window is None:
            lookback_window = lw
        elif lookback_window != lw:
            raise RuntimeError("bankruptcy screen paths use conflicting lookback_window values")
        observed_ats.append(screen["observed_at"])
        for ticker, rec in rows.items():
            if ticker in merged_by_ticker and merged_by_ticker[ticker] != rec:
                raise RuntimeError(f"bankruptcy screen paths contain conflicting duplicate ticker row: {ticker}")
            merged_by_ticker[ticker] = rec
    observed_at = max(observed_ats, key=_parse_iso_instant)
    merged = {
        "observed": True,
        "observed_at": observed_at,
        "lookback_window": lookback_window,
        "by_ticker": merged_by_ticker,
    }
    _canonical_screen_rows(merged, decision_date=decision_date, generated_at=generated_at)
    return merged, len(paths)


# ---------------------------------------------------------------------------
# Canonical decision_date (§2.1) — binds the output path; resolved offline from the frozen calendar
# ---------------------------------------------------------------------------

def _resolve_canonical(now_et: datetime, calendar: dict) -> dict[str, Any]:
    sessions = sessions_for_window(now_et.strftime("%Y%m%d"), calendar=calendar)
    try:
        return resolve_canonical_asof(now_et, sessions)
    except OutOfWindowError as exc:
        raise RuntimeError(
            "now_et 落在盘中死区（§2.1）；universe fetch 须在收盘后/开盘前跑，fail-closed、不解析 canonical"
        ) from exc


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_fetch(
    *,
    now_et: datetime | None = None,
    governance_path: Path = GOVERNANCE_PRESET,
    calendar_path: Path = CALENDAR_PRESET,
    summary_path: Path | None = None,
    raw_root: Path | None = None,
    candidate_list_path: Path | None = None,
    generated_at: str | None = None,
    confirm_user_authorization: bool = False,
    dry_run_env: bool = False,
    bankruptcy_screen_paths: list[Path] | tuple[Path, ...] | None = None,
    bankruptcy_submissions_by_ticker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not confirm_user_authorization and not dry_run_env:
        raise RuntimeError("live execution requires --confirm-user-authorization")
    if not _check_gitignore():
        raise RuntimeError("provider_samples/ not confirmed in .gitignore")

    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    sec_ua = os.environ.get("SEC_USER_AGENT", "")
    massive_key = os.environ.get("MASSIVE_API_KEY", "")

    if dry_run_env:
        return {"scope": {"status": "dry_run_env_only"},
                "pre_execution_checks": {
                    "massive_key_present": bool(massive_key),
                    "sec_user_agent_present": bool(sec_ua),
                    "fmp_key_present": bool(os.environ.get("FMP_API_KEY", "")),
                },
                "generated_at": generated_at}

    if not isinstance(now_et, datetime) or now_et.tzinfo is not None:
        raise RuntimeError("live execution requires --now-et（无时区 ET 墙钟 YYYY-MM-DDTHH:MM:SS）")
    if not sec_ua:
        raise RuntimeError("SEC_USER_AGENT not set")
    if not massive_key:
        raise RuntimeError("MASSIVE_API_KEY not set")

    calendar = load_market_calendar(calendar_path)
    canonical = _resolve_canonical(now_et, calendar)
    decision_date = canonical["decision_date"]
    price_basis_date = canonical["price_basis_date"]
    calendar_verification_status = calendar["data_provenance"]["verification_status"]

    summary_path = summary_path or _summary_path_for(decision_date)
    raw_root = raw_root or _raw_root_for(decision_date)
    candidate_list_path = candidate_list_path or _candidate_path_for(decision_date)
    _sv.validate_raw_root(raw_root)
    _validate_candidate_path(candidate_list_path, decision_date)   # gitignored-root gate BEFORE any fetch/write
    if bankruptcy_screen_paths and bankruptcy_submissions_by_ticker is not None:
        raise RuntimeError("provide only one bankruptcy source shape: screen path(s) or SEC submissions")
    bankruptcy_screen, bankruptcy_screen_file_count = _load_bankruptcy_screen_paths(
        bankruptcy_screen_paths, decision_date=decision_date, generated_at=generated_at)

    print("[1/5] SEC NYSE/NASDAQ 列表 + CIK...", flush=True)
    sec_map = fetch_sec_tickers(sec_ua)
    print(f"      {len(sec_map)} tickers", flush=True)

    print("[2/5] Status source (SEC active-listing reference + Nasdaq halt feed)...", flush=True)
    try:
        halt_feed = fetch_nasdaq_trade_halt_feed(observed_at=generated_at)
        halt_feed_state = "ok"
    except Exception:
        halt_feed = {"observed": False}
        halt_feed_state = "down"
    status_records, status_source_outcome, status_source_payloads = build_live_status_records(
        sec_map,
        decision_date=decision_date,
        observed_at=generated_at,
        halt_feed=halt_feed,
        halt_feed_state=halt_feed_state,
        bankruptcy_screen=bankruptcy_screen,
        bankruptcy_submissions_by_ticker=bankruptcy_submissions_by_ticker,
    )
    print(f"      status_records={len(status_records)}  "
          f"critical_failed={status_source_outcome['critical_failed']}", flush=True)

    window_dates = adv_window_session_dates(
        price_basis_date, calendar,
        count=ADV_WINDOW_TRADING_DAYS + ADV_WINDOW_FETCH_BUFFER_SESSIONS,
    )
    print(f"[3/5] Massive grouped daily ADV 窗口 ({ADV_WINDOW_TRADING_DAYS} 交易日均额, "
          f"price_basis={price_basis_date})...", flush=True)
    used_date, observed_window_dates, market_data = fetch_massive_window(massive_key, window_dates)
    print(f"      used_date={used_date}  observed_days={len(observed_window_dates)}  "
          f"{len(market_data)} symbols with data", flush=True)

    print("[4/5] SEC 流通股 frames (bulk)...", flush=True)
    sec_shares = fetch_sec_shares(sec_ua)
    print(f"      {len(sec_shares)} CIK 有流通股", flush=True)

    _write_json_atomic(
        {"decision_date": decision_date, "price_basis_date": price_basis_date,
         "used_date": used_date, "observed_window_dates": observed_window_dates,
         "status_source_payloads": status_source_payloads,
         "sec_shares_by_cik": {str(k): v for k, v in sec_shares.items()},
         "market_data": market_data},
        raw_root / "raw_universe_data.json",
    )

    print("[5/5] Pass1 准入 (市值=SEC流通股×收盘价; ADV=窗口日均成交额; status=sourced)...", flush=True)
    governance = load_eligibility_governance(governance_path)
    rows = apply_pass1(sec_map, sec_shares, market_data, governance=governance,
                       as_of=used_date, observed_at=generated_at, status_records=status_records)
    summary_counts = summarize_rows(rows)
    print(f"      pass-A eligible={summary_counts['eligible_count']}  "
          f"needs_mktcap={len(summary_counts['needs_market_cap'])}", flush=True)

    # FMP market-cap fallback for SEC-missing-shares survivors (bounded; pure HTTP, no broker)
    fmp_caps: dict[str, float] = {}
    fmp_key = os.environ.get("FMP_API_KEY", "")
    fallback_targets = summary_counts["needs_market_cap"]
    fmp_attempted = 0
    if fallback_targets and fmp_key:
        fmp_attempted = min(len(fallback_targets), FMP_FREE_DAILY_CAP)
        print(f"      FMP 市值兜底: {len(fallback_targets)} 缺市值 → 取前 {fmp_attempted}...", flush=True)
        fmp_caps = fetch_fmp_market_caps(fallback_targets, fmp_key)
        rows = apply_pass1(sec_map, sec_shares, market_data, governance=governance, fmp_caps=fmp_caps,
                           as_of=used_date, observed_at=generated_at, status_records=status_records)
        summary_counts = summarize_rows(rows)
    elif fallback_targets and not fmp_key:
        print(f"      FMP 兜底跳过 (FMP_API_KEY 未设); {len(fallback_targets)} 缺市值未救回", flush=True)

    print(f"      eligible={summary_counts['eligible_count']}  "
          f"ineligible={summary_counts['ineligible_count']}  "
          f"no_price={summary_counts['no_price_count']}  no_shares={summary_counts['no_shares_count']}  "
          f"fmp_rescued={len(fmp_caps)}", flush=True)
    if bankruptcy_screen is not None:
        bankruptcy_source = "injected_bankruptcy_screen"
        bankruptcy_input_count = len(bankruptcy_screen["by_ticker"])
    elif bankruptcy_submissions_by_ticker is not None:
        bankruptcy_source = "injected_sec_submissions"
        bankruptcy_input_count = len(bankruptcy_submissions_by_ticker)
    else:
        bankruptcy_source = "not_supplied"
        bankruptcy_input_count = 0
    bankruptcy_8k_scan_performed = bankruptcy_source != "not_supplied"
    if bankruptcy_source == "injected_bankruptcy_screen":
        bankruptcy_disclosure = (
            "Pass1 sources delisted/otc from the SEC active-listing reference, halted from the Nasdaq current "
            "halt feed, and bankruptcy from user-authorized gitignored SEC Item 1.03 screen output. The runner "
            "does not refetch per-issuer bankruptcy payloads in this step; unscreened tickers remain disclosed "
            "as unscreened, not proven clean."
        )
        bankruptcy_limitation = (
            "Pass1 consumed prebuilt gitignored SEC Item 1.03 bankruptcy screen output; this is status-source "
            "wiring only and does not authorize broader provider health / Pass2 / DataHub / production use."
        )
    elif bankruptcy_source == "injected_sec_submissions":
        bankruptcy_disclosure = (
            "Pass1 sources delisted/otc from the SEC active-listing reference, halted from the Nasdaq current halt "
            "feed, and bankruptcy from injected SEC company-submissions Item 1.03 screen output. The runner still "
            "does not fetch per-issuer bankruptcy payloads itself; supplied submissions are an explicitly injected "
            "provider-fed source and unscreened tickers remain disclosed as unscreened, not proven clean."
        )
        bankruptcy_limitation = (
            "Pass1 can consume injected SEC company-submissions Item 1.03 bankruptcy screen output in this test seam, "
            "but run_fetch still performs zero per-issuer bankruptcy SEC calls itself; broader provider health / Pass2 "
            "/ DataHub / production consumption remain gated under SR-PROVIDER-001."
        )
    else:
        bankruptcy_disclosure = (
            "Pass1 now sources delisted/otc from the SEC active-listing reference and halted from the "
            "Nasdaq current halt feed. Bankruptcy remains positive-detection-only and unscreened in this "
            "slice (zero 8-K calls), so it is recorded as unscreened provenance rather than proof of clean."
        )
        bankruptcy_limitation = (
            "Pass1 status flags are sourced only for the current SEC active-listing reference and Nasdaq current "
            "halt feed in this slice. Bankruptcy 8-K scanning remains zero-call/unscreened, and broader provider "
            "health / Pass2 / DataHub / production consumption remain gated under SR-PROVIDER-001."
        )
    provider_health = _build_run_fetch_provider_health(
        status_source_outcome=status_source_outcome,
        fallback_needed_count=len(fallback_targets),
        fmp_attempted=fmp_attempted,
        fmp_rescued=len(fmp_caps),
    )

    # Per-run candidate artifact: schema + semantic validate BEFORE the atomic write (carries prices →
    # gitignored state/ root). Validation re-derives the summary and rejects any drifted/forged content.
    artifact = build_candidate_artifact(
        rows=rows, decision_date=decision_date, price_basis_date=price_basis_date,
        used_date=used_date, observed_window_dates=observed_window_dates,
        generated_at=generated_at, calendar_verification_status=calendar_verification_status,
    )
    validate_candidate_artifact(artifact, expected_decision_date=decision_date, governance=governance)
    _write_json_atomic(artifact, candidate_list_path)

    summary = {
        "schema_name": "us_short_universe_fetch_summary",
        "schema_version": "1.2.0",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": generated_at,
        "scope": {
            "market": "US", "lane": "us_short", "batch": "batch5_provider_live",
            "status": "universe_fetch_and_pass1_completed",
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "ship_gate_evidence_claimed": False,
        },
        "decision_clock": {
            "decision_date": decision_date,
            "price_basis_date": price_basis_date,
            "used_date": used_date,
            "run_datetime_et": canonical["run_datetime_et"],
            "calendar_verification_status": calendar_verification_status,
        },
        "adv_window": {
            "trading_days": ADV_WINDOW_TRADING_DAYS,
            "min_days_required": ADV_MIN_DAYS_REQUIRED,
            "observed_days": len(observed_window_dates),
            "latest_date": used_date,
        },
        "data_path": {
            "tickers_cik_exchange": "SEC company_tickers_exchange.json",
            "price_volume": "Massive grouped daily (/v2/aggs/grouped/locale/us/market/stocks/{date}), one call per window day",
            "shares_outstanding": "SEC XBRL frames (dei/EntityCommonStockSharesOutstanding); FMP profile marketCap fallback",
            "market_cap": "SEC shares × Massive close; else FMP profile marketCap (bounded fallback)",
            "adv": f"mean of Massive (volume × close) over the {ADV_WINDOW_TRADING_DAYS}-trading-day window (multi-day average, not a single day)",
            "broker_used": False,
            "paid_subscription_used": False,
        },
        "universe": {
            "exchange_filter": list(EXCHANGE_WHITELIST),
            "decision_date": decision_date,
            "used_date": used_date,
            "sec_tickers": len(sec_map),
            "massive_symbols_with_data": len(market_data),
            "sec_ciks_with_shares": len(sec_shares),
            "fmp_mktcap_fallback_attempted": fmp_attempted,
            "fmp_mktcap_fallback_rescued": len(fmp_caps),
        },
        "provider_health": provider_health,
        "pass1_result": {**summary_counts, "eligible_tickers": eligible_tickers_from_rows(rows)},
        "status_screening": {
            "status_flags_sourced": True,
            "screening_scope": "exchange_price_adv_market_cap_with_ticker_reference_and_halt_feed_status",
            "status_source_outcome": status_source_outcome,
            "status_records_total": len(status_records),
            "bankruptcy_8k_scan_performed": bankruptcy_8k_scan_performed,
            "bankruptcy_8k_source": bankruptcy_source,
            "bankruptcy_8k_input_symbol_count": bankruptcy_input_count,
            "bankruptcy_8k_screen_file_count": bankruptcy_screen_file_count,
            "disclosure": bankruptcy_disclosure,
            "status_source_contract_ref": "docs/us_short_batch5_status_source_binding_20260629.json",
            "finding_ref": "R-USSHORT-BATCH5-PASS1-CRITICAL-STATUS-HEALTH-FAILOPEN",
        },
        "storage": {
            "raw_payload_root": _rel(raw_root),
            "raw_payload_root_gitignored": _git_check_ignored(raw_root),
            "candidate_artifact_path": _rel(candidate_list_path),
            "candidate_artifact_gitignored": _git_check_ignored(candidate_list_path),
            "candidate_artifact_schema": _rel(CANDIDATE_SCHEMA_PATH),
            "tracked_summary_contains_prices": False,
        },
        "sr_provider_001_remains_open": True,
        "limitations": [
            bankruptcy_limitation,
            f"ADV = mean daily dollar volume over the last {ADV_WINDOW_TRADING_DAYS} trading days ending at used_date (a real multi-day average, governance floor is $5M/day). A ticker observed on < {ADV_MIN_DAYS_REQUIRED} days has adv_usd=null (insufficient coverage) and fails the gate conservatively — it is never admitted on a one-day spike.",
            "decision_date / price_basis_date are resolved from the FROZEN NYSE/NASDAQ calendar, whose data_provenance.verification_status is recorded here; it is still pending_authoritative_cross_check until verified (SR-PROVIDER-001) — disclosed, not laundered.",
            "market_cap = latest SEC shares × Massive close; SEC-missing-shares names use FMP fallback (bounded by FMP free daily cap; overflow stays ineligible).",
            "Massive free tier is delayed data — fine for the §2.1 prior-close price clock; does NOT authorize DataHub/production/ship-gate.",
            "Non-common-stock SEC entries (warrants/units/preferreds) without a Massive close or SEC shares fall out as no_price / no_shares.",
        ],
    }
    _write_summary_safe(summary, summary_path, [massive_key, fmp_key])   # scan BEFORE write → no residue on failure
    return summary


def _parse_now_et(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("须为 ET 墙钟 YYYY-MM-DDTHH:MM:SS") from exc


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Fetch NYSE/NASDAQ universe via Massive+SEC (free, no broker) + Pass1 gate.")
    p.add_argument("--confirm-user-authorization", action="store_true")
    p.add_argument("--dry-run-env", action="store_true")
    p.add_argument("--now-et", dest="now_et", type=_parse_now_et, default=None,
                   help="ET wall clock YYYY-MM-DDTHH:MM:SS — must be Eastern Time, NOT Beijing time (a Beijing "
                        "wall-clock resolves a wrong decision_date silently; F8). Resolves canonical decision_date; required for live")
    p.add_argument("--calendar", dest="calendar_path", type=Path, default=CALENDAR_PRESET)
    # No --summary-path / --raw-root / --candidate-list-path: all dated outputs derive from the canonical
    # decision_date so a caller can't redirect a priced artifact to a non-gitignored / wrong-date path
    # (R-USSHORT-BATCH5-PASS1-LIQUIDITY-LINEAGE-CONTRACT-GAP). Tests use the run_fetch kwargs (private seam).
    p.add_argument("--bankruptcy-screen-path", dest="bankruptcy_screen_paths", type=Path, action="append",
                   default=None,
                   help="gitignored state/us_short/*.json SEC Item 1.03 bankruptcy screen output; repeatable")
    p.add_argument("--generated-at")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    summary = run_fetch(
        now_et=args.now_et, calendar_path=args.calendar_path, generated_at=args.generated_at,
        confirm_user_authorization=args.confirm_user_authorization, dry_run_env=args.dry_run_env,
        bankruptcy_screen_paths=args.bankruptcy_screen_paths,
    )
    if summary.get("scope", {}).get("status") == "dry_run_env_only":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    r = summary.get("pass1_result", {})
    u = summary.get("universe", {})
    a = summary.get("adv_window", {})
    print(f"\n=== 结果 ===")
    print(f"decision_date={u.get('decision_date')}  used_date={u.get('used_date')}  "
          f"ADV窗口={a.get('observed_days')}/{a.get('trading_days')}交易日")
    print(f"SEC tickers={u.get('sec_tickers',0)}  Massive data={u.get('massive_symbols_with_data',0)}  "
          f"shares-CIK={u.get('sec_ciks_with_shares',0)}")
    print(f"Eligible: {r.get('eligible_count',0)}  Ineligible: {r.get('ineligible_count',0)}  "
          f"no_price: {r.get('no_price_count',0)}  no_shares: {r.get('no_shares_count',0)}  "
          f"fmp_rescued: {u.get('fmp_mktcap_fallback_rescued',0)}")
    if r.get("eligible_count", 0) > 0:
        print(f"样本: {r.get('eligible_tickers',[])[:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
