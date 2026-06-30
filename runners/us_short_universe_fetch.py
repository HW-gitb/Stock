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

MASSIVE_GROUPED_URL = "https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/{date}?apiKey={key}"

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
                     "data.sec.gov", "www.sec.gov"):
        if fragment in lower:
            raise RuntimeError(f"tracked summary contains forbidden fragment: {fragment}")
    for value in sensitive:
        if value and value in text:
            raise RuntimeError("tracked summary contains a sensitive environment value")


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
# SEC: bulk shares outstanding via frames (latest per CIK across quarters)
# ---------------------------------------------------------------------------

def fetch_sec_shares(sec_ua: str, *, frames: list[str] = SEC_SHARE_FRAMES) -> dict[int, dict[str, Any]]:
    """Return {cik: {"shares": float, "end": str}} keeping the latest 'end' per CIK across frames."""
    by_cik: dict[int, dict[str, Any]] = {}
    for q in frames:
        try:
            data = _sec_get(SEC_FRAMES_URL.format(q=q), sec_ua)
        except Exception:
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
    for d in session_dates_desc:
        if len(collected) >= window:
            break
        try:
            results = _massive_grouped_for_date(d, key)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 429):
                raise RuntimeError(
                    f"Massive grouped daily HTTP {exc.code} (auth/quota — check MASSIVE_API_KEY / rate "
                    "limit); not a missing trading day"
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

        gate_row = {
            "ticker": sym, "exchange": meta["exchange"],
            "price": price, "adv_usd": adv_usd, "market_cap_usd": market_cap,
            "delisted": False, "halted": False, "bankruptcy": False, "otc": False,
        }
        verdict = cheap_eligible(gate_row, governance=governance)

        rows.append({
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
            "delisted": False, "halted": False, "bankruptcy": False, "otc": False,
            "status_flags_sourced": False,
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
        })
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
        "schema_version": "1.0.0",
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
    floor = governance["cheap_eligibility_thresholds"]["min_adv_usd"]
    for r in rows:
        if r["eligible"]:
            if r["reasons"]:
                raise RuntimeError("eligible 行不应带 reasons")
            if not (r["adv_coverage_ok"] and _is_finite(r["adv_usd"]) and r["adv_usd"] >= floor):
                raise RuntimeError("eligible 行的 ADV 须覆盖充分且达多日门槛（多日 ADV 语义）")
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

    print("[1/4] SEC NYSE/NASDAQ 列表 + CIK...", flush=True)
    sec_map = fetch_sec_tickers(sec_ua)
    print(f"      {len(sec_map)} tickers", flush=True)

    window_dates = adv_window_session_dates(
        price_basis_date, calendar,
        count=ADV_WINDOW_TRADING_DAYS + ADV_WINDOW_FETCH_BUFFER_SESSIONS,
    )
    print(f"[2/4] Massive grouped daily ADV 窗口 ({ADV_WINDOW_TRADING_DAYS} 交易日均额, "
          f"price_basis={price_basis_date})...", flush=True)
    used_date, observed_window_dates, market_data = fetch_massive_window(massive_key, window_dates)
    print(f"      used_date={used_date}  observed_days={len(observed_window_dates)}  "
          f"{len(market_data)} symbols with data", flush=True)

    print("[3/4] SEC 流通股 frames (bulk)...", flush=True)
    sec_shares = fetch_sec_shares(sec_ua)
    print(f"      {len(sec_shares)} CIK 有流通股", flush=True)

    _write_json_atomic(
        {"decision_date": decision_date, "price_basis_date": price_basis_date,
         "used_date": used_date, "observed_window_dates": observed_window_dates,
         "sec_shares_by_cik": {str(k): v for k, v in sec_shares.items()},
         "market_data": market_data},
        raw_root / "raw_universe_data.json",
    )

    print("[4/4] Pass1 准入 (市值=SEC流通股×收盘价; ADV=窗口日均成交额)...", flush=True)
    governance = load_eligibility_governance(governance_path)
    rows = apply_pass1(sec_map, sec_shares, market_data, governance=governance,
                       as_of=used_date, observed_at=generated_at)
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
                           as_of=used_date, observed_at=generated_at)
        summary_counts = summarize_rows(rows)
    elif fallback_targets and not fmp_key:
        print(f"      FMP 兜底跳过 (FMP_API_KEY 未设); {len(fallback_targets)} 缺市值未救回", flush=True)

    print(f"      eligible={summary_counts['eligible_count']}  "
          f"ineligible={summary_counts['ineligible_count']}  "
          f"no_price={summary_counts['no_price_count']}  no_shares={summary_counts['no_shares_count']}  "
          f"fmp_rescued={len(fmp_caps)}", flush=True)

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
        "schema_version": "1.1.0",
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
        "pass1_result": {**summary_counts, "eligible_tickers": eligible_tickers_from_rows(rows)},
        "status_screening": {
            "status_flags_sourced": False,
            "screening_scope": "exchange_price_adv_market_cap_only",
            "hardwired_status_flags": ["delisted", "halted", "bankruptcy", "otc"],
            "disclosure": (
                "Pass1 hardwires delisted/halted/bankruptcy/otc to False (no status source in round-1), "
                "so eligible_tickers reflects exchange/price/ADV/market-cap screening ONLY — NOT "
                "listing-status / halt / bankruptcy / OTC screening; the list may include non-tradable names."
            ),
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
            "Pass1 status flags (delisted/halted/bankruptcy/otc) are NOT sourced in round-1 — hardwired to False; eligible_tickers screens exchange/price/ADV/market-cap ONLY and may include non-tradable (delisted/halted/bankrupt/OTC) names. Real per-flag source frozen schema-first in docs/us_short_batch5_status_source_binding_20260629.json (R-USSHORT-BATCH5-PASS1-CRITICAL-STATUS-HEALTH-FAILOPEN), gated under SR-PROVIDER-001.",
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
                   help="ET wall clock YYYY-MM-DDTHH:MM:SS (resolves canonical decision_date; required for live)")
    p.add_argument("--calendar", dest="calendar_path", type=Path, default=CALENDAR_PRESET)
    # No --summary-path / --raw-root / --candidate-list-path: all dated outputs derive from the canonical
    # decision_date so a caller can't redirect a priced artifact to a non-gitignored / wrong-date path
    # (R-USSHORT-BATCH5-PASS1-LIQUIDITY-LINEAGE-CONTRACT-GAP). Tests use the run_fetch kwargs (private seam).
    p.add_argument("--generated-at")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    summary = run_fetch(
        now_et=args.now_et, calendar_path=args.calendar_path, generated_at=args.generated_at,
        confirm_user_authorization=args.confirm_user_authorization, dry_run_env=args.dry_run_env,
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
