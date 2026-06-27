"""US-short universe fetch via Massive + SEC (all free, no broker) + Pass1 gate — batch5 provider/live.

Authorization: user_chat_20260626_universe_fetch
Design: docs/us_short_system_design.md §4.0 (Universe + Pass1) / §18.0 P0 / §18.1 #2 / §18.2 batch5

Data path (all free, pure HTTP — NO broker, no order, no paid subscription):
  - Tickers + CIK + exchange : SEC company_tickers_exchange.json   (1 free call, ~7600 NYSE/NASDAQ)
  - Close price + volume      : Massive grouped daily — ONE call returns OHLCV for ALL US stocks for the
                                last trading day (/v2/aggs/grouped/locale/us/market/stocks/{date}).
                                ADV = close × volume (official consolidated, market-hours-independent).
  - Shares outstanding        : SEC XBRL frames API, merged over recent quarters, latest per CIK (~4 calls)
  - market_cap fallback       : FMP profile marketCap, bounded, only for SEC-missing-shares survivors
                                (multi-class / non-calendar-aligned names absent from SEC frames, e.g. GOOGL)
  - market_cap                : shares (SEC) × close (Massive); else FMP profile marketCap

Why Massive (replaces the earlier IBKR snapshot attempt): IBKR delayed snapshot volume is unreliable
(0 / garbage deep into the weekend, timing-dependent) and pulling 7600 symbols needs ~19 min + a broker
connection. Massive grouped daily is ONE call, reliable official volume, no broker dependency — so the
us_short surface stays 100% broker-free (§1/§17 "不接券商" unchanged).

Outputs:
  - Gitignored raw          → provider_samples/us_short_universe_fetch_20260626/raw/
  - Gitignored candidate    → state/us_short/candidate_universe_20260626.json
  - Tracked no-secret summary→ docs/us_short_universe_fetch_summary_20260626.json

Usage:
  python runners/us_short_universe_fetch.py --confirm-user-authorization [--date YYYY-MM-DD]
Requires env: MASSIVE_API_KEY, SEC_USER_AGENT (FMP_API_KEY optional, for market-cap fallback).
"""
from __future__ import annotations

import argparse
import gzip as _gzip
import json
import math
import os
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
from runners import us_egs_sample_validation as _sv  # noqa: E402

AUTHORIZATION_REF = "user_chat_20260626_universe_fetch"
GOVERNANCE_PRESET = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_universe_fetch_summary_20260626.json"
RAW_ROOT = ROOT / "provider_samples" / "us_short_universe_fetch_20260626" / "raw"
CANDIDATE_LIST_PATH = ROOT / "state" / "us_short" / "candidate_universe_20260626.json"

SEC_EXCHANGE_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_FRAMES_URL = "https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/{q}.json"
SEC_SHARE_FRAMES = ["CY2026Q1I", "CY2025Q4I", "CY2025Q3I", "CY2025Q2I"]
SEC_FAIR_ACCESS_SLEEP = 0.15
EXCHANGE_WHITELIST = ("NYSE", "NASDAQ")

MASSIVE_GROUPED_URL = "https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/{date}?apiKey={key}"
MASSIVE_LOOKBACK_DAYS = 7  # step back up to N days to find the last trading day with data

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


def _check_gitignore() -> bool:
    gi = ROOT / ".gitignore"
    return gi.exists() and "provider_samples/" in gi.read_text(encoding="utf-8")


def _write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp.replace(path)


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
# Massive: grouped daily (one call → all US stocks close + volume)
# ---------------------------------------------------------------------------

def _massive_grouped_for_date(date_str: str, key: str) -> list[dict[str, Any]]:
    url = MASSIVE_GROUPED_URL.format(date=date_str, key=key)
    req = urllib.request.Request(url, headers={"User-Agent": "StockSystem/0.1 us-short-universe"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("results") or []


def fetch_massive_universe(key: str, *, as_of_date: str | None = None,
                           lookback: int = MASSIVE_LOOKBACK_DAYS) -> tuple[str, dict[str, dict[str, Any]]]:
    """Return (used_date, {canonical_ticker: {"close": float, "volume": float}}). If as_of_date is None,
    step back from yesterday up to `lookback` days to find the last trading day with non-empty results."""
    if as_of_date:
        candidates = [as_of_date]
    else:
        today = datetime.now(timezone.utc).date()
        candidates = [(today - timedelta(days=i)).isoformat() for i in range(1, lookback + 1)]

    for d in candidates:
        try:
            results = _massive_grouped_for_date(d, key)
        except urllib.error.HTTPError:
            continue
        if not results:
            continue
        out: dict[str, dict[str, Any]] = {}
        for row in results:
            ct = canonical_us_ticker(row.get("T"))
            close = row.get("c")
            vol = row.get("v")
            if ct and ct not in out and _is_finite(close):
                out[ct] = {"close": float(close),
                           "volume": float(vol) if _is_finite(vol) else None}
        if out:
            return d, out
    raise RuntimeError(f"Massive grouped daily returned no data for any of {candidates}")


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
# Pass1 gate (joins SEC shares × Massive close → market cap; Massive volume × close → ADV)
# ---------------------------------------------------------------------------

def apply_pass1(
    sec_tickers: dict[str, dict[str, Any]],
    sec_shares: dict[int, dict[str, Any]],
    market_data: dict[str, dict[str, Any]],
    *,
    governance: dict[str, Any],
    fmp_caps: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Pass1 over the universe. price/volume from Massive grouped daily; market_cap = SEC shares × close
    (else fmp_caps[ticker]); adv = volume × close. `needs_market_cap` = tickers whose ONLY failure is a
    missing market cap and which pass price/ADV/exchange/status (the bounded set an FMP top-up can rescue)."""
    fmp_caps = fmp_caps or {}
    eligible: list[str] = []
    seen: set[str] = set()
    reason_counts: dict[str, int] = {}
    ineligible = 0
    no_price = 0
    no_shares = 0
    needs_market_cap: list[str] = []

    for sym, meta in sec_tickers.items():
        d = market_data.get(sym) or {}
        price = d.get("close")
        volume = d.get("volume")
        shares_rec = sec_shares.get(meta["cik"])
        shares = shares_rec["shares"] if shares_rec else None

        adv_usd = float(volume) * float(price) if _is_finite(volume) and _is_finite(price) else None
        market_cap = float(shares) * float(price) if _is_finite(shares) and _is_finite(price) else None
        if market_cap is None and sym in fmp_caps and _is_finite(fmp_caps[sym]):
            market_cap = float(fmp_caps[sym])

        if not _is_finite(price):
            no_price += 1
        if not _is_finite(shares):
            no_shares += 1

        gate_row = {
            "ticker": sym, "exchange": meta["exchange"],
            "price": price, "adv_usd": adv_usd, "market_cap_usd": market_cap,
            "delisted": False, "halted": False, "bankruptcy": False, "otc": False,
        }
        result = cheap_eligible(gate_row, governance=governance)
        if result["eligible"]:
            ct = result["ticker"]
            if ct and ct not in seen:
                eligible.append(ct)
                seen.add(ct)
        else:
            reasons = result["reasons"]
            for r in reasons:
                reason_counts[r] = reason_counts.get(r, 0) + 1
            ineligible += 1
            if reasons == ["market_cap_usd_unknown_or_invalid"]:
                needs_market_cap.append(sym)

    return {
        "eligible_tickers": eligible,
        "eligible_count": len(eligible),
        "ineligible_count": ineligible,
        "no_price_count": no_price,
        "no_shares_count": no_shares,
        "needs_market_cap": needs_market_cap,
        "total_tickers": len(sec_tickers),
        "reason_distribution": reason_counts,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_fetch(
    *,
    governance_path: Path = GOVERNANCE_PRESET,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_ROOT,
    candidate_list_path: Path = CANDIDATE_LIST_PATH,
    as_of_date: str | None = None,
    generated_at: str | None = None,
    confirm_user_authorization: bool = False,
    dry_run_env: bool = False,
) -> dict[str, Any]:
    if not confirm_user_authorization and not dry_run_env:
        raise RuntimeError("live execution requires --confirm-user-authorization")
    if not _check_gitignore():
        raise RuntimeError("provider_samples/ not confirmed in .gitignore")
    _sv.validate_raw_root(raw_root)

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
    if not sec_ua:
        raise RuntimeError("SEC_USER_AGENT not set")
    if not massive_key:
        raise RuntimeError("MASSIVE_API_KEY not set")

    print("[1/4] SEC NYSE/NASDAQ 列表 + CIK...", flush=True)
    sec_map = fetch_sec_tickers(sec_ua)
    print(f"      {len(sec_map)} tickers", flush=True)

    print("[2/4] Massive grouped daily (1 call → 全美股收盘价+成交量)...", flush=True)
    used_date, market_data = fetch_massive_universe(massive_key, as_of_date=as_of_date)
    print(f"      date={used_date}  {len(market_data)} symbols with price", flush=True)

    print("[3/4] SEC 流通股 frames (bulk)...", flush=True)
    sec_shares = fetch_sec_shares(sec_ua)
    print(f"      {len(sec_shares)} CIK 有流通股", flush=True)

    _write_json_atomic(
        {"massive_date": used_date,
         "sec_shares_by_cik": {str(k): v for k, v in sec_shares.items()},
         "market_data": market_data},
        raw_root / "raw_universe_data.json",
    )

    print("[4/4] Pass1 准入 (市值=SEC流通股×收盘价; ADV=成交量×收盘价)...", flush=True)
    governance = load_eligibility_governance(governance_path)
    pass1 = apply_pass1(sec_map, sec_shares, market_data, governance=governance)
    print(f"      pass-A eligible={pass1['eligible_count']}  needs_mktcap={len(pass1['needs_market_cap'])}",
          flush=True)

    # FMP market-cap fallback for SEC-missing-shares survivors (bounded; pure HTTP, no broker)
    fmp_caps: dict[str, float] = {}
    fmp_key = os.environ.get("FMP_API_KEY", "")
    fallback_targets = pass1["needs_market_cap"]
    fmp_attempted = 0
    if fallback_targets and fmp_key:
        fmp_attempted = min(len(fallback_targets), FMP_FREE_DAILY_CAP)
        print(f"      FMP 市值兜底: {len(fallback_targets)} 缺市值 → 取前 {fmp_attempted}...", flush=True)
        fmp_caps = fetch_fmp_market_caps(fallback_targets, fmp_key)
        pass1 = apply_pass1(sec_map, sec_shares, market_data, governance=governance, fmp_caps=fmp_caps)
    elif fallback_targets and not fmp_key:
        print(f"      FMP 兜底跳过 (FMP_API_KEY 未设); {len(fallback_targets)} 缺市值未救回", flush=True)

    print(f"      eligible={pass1['eligible_count']}  ineligible={pass1['ineligible_count']}  "
          f"no_price={pass1['no_price_count']}  no_shares={pass1['no_shares_count']}  "
          f"fmp_rescued={len(fmp_caps)}", flush=True)

    _write_json_atomic({
        "generated_at": generated_at,
        "authorization_ref": AUTHORIZATION_REF,
        "provider": "massive_grouped_daily + sec_shares (+ fmp mktcap fallback)",
        "massive_date": used_date,
        "eligible_tickers": pass1["eligible_tickers"],
        "eligible_count": pass1["eligible_count"],
    }, candidate_list_path)

    summary = {
        "schema_name": "us_short_universe_fetch_summary",
        "schema_version": "1.0.0",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": generated_at,
        "scope": {
            "market": "US", "lane": "us_short", "batch": "batch5_provider_live",
            "status": "universe_fetch_and_pass1_completed",
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "ship_gate_evidence_claimed": False,
        },
        "data_path": {
            "tickers_cik_exchange": "SEC company_tickers_exchange.json",
            "price_volume": "Massive grouped daily (/v2/aggs/grouped/locale/us/market/stocks/{date}), 1 call",
            "shares_outstanding": "SEC XBRL frames (dei/EntityCommonStockSharesOutstanding); FMP profile marketCap fallback",
            "market_cap": "SEC shares × Massive close; else FMP profile marketCap (bounded fallback)",
            "adv": "Massive volume × Massive close",
            "broker_used": False,
            "paid_subscription_used": False,
        },
        "universe": {
            "exchange_filter": list(EXCHANGE_WHITELIST),
            "massive_date": used_date,
            "sec_tickers": len(sec_map),
            "massive_symbols_with_price": len(market_data),
            "sec_ciks_with_shares": len(sec_shares),
            "fmp_mktcap_fallback_attempted": fmp_attempted,
            "fmp_mktcap_fallback_rescued": len(fmp_caps),
        },
        "pass1_result": pass1,
        "storage": {
            "raw_payload_root": _rel(raw_root),
            "raw_payload_root_gitignored": True,
            "candidate_list_path": _rel(candidate_list_path),
            "candidate_list_gitignored": True,
            "tracked_summary_contains_prices": False,
        },
        "sr_provider_001_remains_open": True,
        "limitations": [
            "Price/volume = Massive grouped daily for one trading day (used_date); ADV is that day's dollar volume, not a multi-day average.",
            "market_cap = latest SEC shares × Massive close; SEC-missing-shares names use FMP fallback (bounded by FMP free daily cap; overflow stays ineligible).",
            "Massive free tier is delayed data — fine for the §2.1 prior-close price clock; does NOT authorize DataHub/production/ship-gate.",
            "Non-common-stock SEC entries (warrants/units/preferreds) without a Massive close or SEC shares fall out as no_price / no_shares.",
        ],
    }
    _write_json_atomic(summary, summary_path)
    return summary


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Fetch NYSE/NASDAQ universe via Massive+SEC (free, no broker) + Pass1 gate.")
    p.add_argument("--confirm-user-authorization", action="store_true")
    p.add_argument("--dry-run-env", action="store_true")
    p.add_argument("--date", dest="as_of_date", default=None, help="Trading date YYYY-MM-DD (default: last trading day)")
    p.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    p.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    p.add_argument("--candidate-list-path", type=Path, default=CANDIDATE_LIST_PATH)
    p.add_argument("--generated-at")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    summary = run_fetch(
        summary_path=args.summary_path, raw_root=args.raw_root,
        candidate_list_path=args.candidate_list_path, as_of_date=args.as_of_date,
        generated_at=args.generated_at,
        confirm_user_authorization=args.confirm_user_authorization, dry_run_env=args.dry_run_env,
    )
    r = summary.get("pass1_result", {})
    u = summary.get("universe", {})
    print(f"\n=== 结果 ===")
    print(f"date={u.get('massive_date')}  SEC tickers={u.get('sec_tickers',0)}  "
          f"Massive price={u.get('massive_symbols_with_price',0)}  shares-CIK={u.get('sec_ciks_with_shares',0)}")
    print(f"Eligible: {r.get('eligible_count',0)}  Ineligible: {r.get('ineligible_count',0)}  "
          f"no_price: {r.get('no_price_count',0)}  no_shares: {r.get('no_shares_count',0)}  "
          f"fmp_rescued: {u.get('fmp_mktcap_fallback_rescued',0)}")
    if r.get("eligible_count", 0) > 0:
        print(f"样本: {r.get('eligible_tickers',[])[:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
