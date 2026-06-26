"""US-short IBKR universe fetch + Pass1 eligibility gate — batch5 provider/live.

Authorization: user_chat_20260626_ibkr_account_universe_fetch
Replaces: runners/us_short_fmp_universe_fetch.py (FMP Basic daily limit insufficient)
Design: docs/us_short_system_design.md §4.0 / §18.0 P0 / §18.1 #2 / §18.2 batch5

Strategy:
  1. SEC company_tickers_exchange.json (1 free call) → NYSE/NASDAQ symbol list (~7,600)
  2. IB Gateway connection (user opens IB Gateway before running)
  3. IBKR snapshot + fundamental ratios (tick 258) per batch of 50 symbols:
     - price (NPRICE or last)
     - market cap in millions (MKTCAP)
     - 3-month avg daily volume in thousands (VOL3MAVG)
  4. Pass1 cheap_eligible gate
  5. Write:
     - Candidate symbol list → gitignored state/us_short/candidate_universe_ibkr_{date}.json
     - Tracked summary       → docs/us_short_ibkr_universe_fetch_summary_20260626.json
       (symbol list + counts; NO prices, NO secrets)

Requires:
  - IB Gateway (or TWS) running on 127.0.0.1:4002 (paper) or 4001 (live)
  - SEC_USER_AGENT env var
  - --confirm-user-authorization flag

No FMP calls. No DataHub. No production storage. No ship-gate claim.
SR-PROVIDER-001 remains open for DataHub/production/SEC parser/ship-gate work.
"""
from __future__ import annotations

import argparse
import gzip as _gzip
import json
import math
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
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

AUTHORIZATION_REF = "user_chat_20260626_ibkr_account_universe_fetch"
GOVERNANCE_PRESET = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_ibkr_universe_fetch_summary_20260626.json"
RAW_ROOT = ROOT / "provider_samples" / "us_short_ibkr_universe_fetch_20260626" / "raw"
CANDIDATE_LIST_PATH = ROOT / "state" / "us_short" / "candidate_universe_ibkr_20260626.json"

SEC_EXCHANGE_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_FAIR_ACCESS_SLEEP = 0.12
EXCHANGE_WHITELIST = ("NYSE", "NASDAQ")

IBKR_HOST = "127.0.0.1"
IBKR_SNAPSHOT_TIMEOUT = 3.0    # seconds to wait for each snapshot batch
IBKR_BATCH_SIZE = 50           # contracts per snapshot batch
IBKR_BATCH_SLEEP = 0.2         # seconds between batches
FUNDAMENTAL_TICK = "258"        # IBKR generic tick for fundamental ratios


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Step 1: SEC company_tickers_exchange.json
# ---------------------------------------------------------------------------

def fetch_sec_nyse_nasdaq_tickers(sec_ua: str) -> list[str]:
    headers = {"User-Agent": sec_ua, "Host": "www.sec.gov",
               "Accept-Encoding": "gzip, deflate"}
    req = urllib.request.Request(SEC_EXCHANGE_TICKERS_URL, headers=headers)
    time.sleep(SEC_FAIR_ACCESS_SLEEP)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":
        raw = _gzip.decompress(raw)
    data = json.loads(raw.decode("utf-8"))

    fields = data.get("fields", [])
    rows = data.get("data", [])
    if "ticker" not in fields or "exchange" not in fields:
        raise RuntimeError(f"SEC tickers response missing fields: {fields}")
    t_idx = fields.index("ticker")
    e_idx = fields.index("exchange")

    _norm = {"NYSE": "NYSE", "Nasdaq": "NASDAQ", "NASDAQ": "NASDAQ"}
    tickers = []
    for row in rows:
        exch = _norm.get(str(row[e_idx] if e_idx < len(row) else ""), "")
        if exch not in EXCHANGE_WHITELIST:
            continue
        ct = canonical_us_ticker(row[t_idx] if t_idx < len(row) else "")
        if ct:
            tickers.append(ct)
    return sorted(set(tickers))


# ---------------------------------------------------------------------------
# Step 2: IBKR snapshot with fundamental ratios
# ---------------------------------------------------------------------------

def _connect_ibkr(port: int, client_id: int = 1):
    """Return connected ib_insync IB instance."""
    try:
        from ib_insync import IB  # type: ignore[import]
    except ImportError:
        raise RuntimeError("ib_insync not installed — run: pip install ib_insync")
    ib = IB()
    ib.connect(IBKR_HOST, port, clientId=client_id, timeout=10)
    return ib


def _fetch_batch_snapshots(ib, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Request snapshot data for a batch of symbols. Returns {symbol: data_dict}."""
    from ib_insync import Stock  # type: ignore[import]

    contracts = []
    sym_map = {}  # conId or symbol → original symbol
    for sym in symbols:
        c = Stock(sym, "SMART", "USD")
        contracts.append(c)

    tickers = ib.reqTickers(*contracts, regulatorySnapshot=False)
    # Also request fundamental ratios via snapshot mkt data
    # Re-request with genericTickList for fundamental ratios
    mkt_tickers = []
    for c in contracts:
        t = ib.reqMktData(c, genericTickList=FUNDAMENTAL_TICK, snapshot=True)
        mkt_tickers.append(t)
    ib.sleep(IBKR_SNAPSHOT_TIMEOUT)

    results = {}
    for sym, ticker, mkt_ticker in zip(symbols, tickers, mkt_tickers):
        # Price: prefer last, fall back to close
        price = ticker.last if _is_finite(ticker.last) else ticker.close
        if not _is_finite(price):
            price = None

        # Volume (current day)
        volume = ticker.volume if _is_finite(getattr(ticker, "volume", None)) else None

        # Fundamental ratios from tick 258
        fr = getattr(mkt_ticker, "fundamentalRatios", None) or {}
        if hasattr(fr, "__dict__"):
            fr = fr.__dict__

        # Market cap (MKTCAP in millions → convert to USD)
        mktcap_m = fr.get("MKTCAP") if fr else None
        market_cap_usd = float(mktcap_m) * 1_000_000 if _is_finite(mktcap_m) else None

        # 3-month avg daily volume in thousands → convert to shares
        vol3m_k = fr.get("VOL3MAVG") if fr else None
        vol_avg = float(vol3m_k) * 1000 if _is_finite(vol3m_k) else None

        # ADV in USD
        adv_usd = None
        if _is_finite(vol_avg) and _is_finite(price) and vol_avg > 0:
            adv_usd = vol_avg * float(price)
        elif _is_finite(volume) and _is_finite(price) and volume > 0:
            adv_usd = float(volume) * float(price)

        # Exchange from contract
        exch = getattr(ticker.contract, "primaryExch", "") or ""
        exch = exch.upper()
        if exch not in EXCHANGE_WHITELIST:
            # SMART routing — fallback to the symbol's exchange from SEC
            exch = ""  # will be inferred from SEC data

        results[sym] = {
            "price": price,
            "adv_usd": adv_usd,
            "market_cap_usd": market_cap_usd,
            "exchange": exch,
            "vol_avg_shares": vol_avg,
            "volume_today": volume,
        }

    # Cancel market data subscriptions to avoid hitting data line limits
    for t in mkt_tickers:
        try:
            ib.cancelMktData(t.contract)
        except Exception:
            pass

    return results


def fetch_ibkr_data(
    tickers: list[str],
    *,
    port: int,
    progress_cb=None,
) -> dict[str, dict[str, Any]]:
    """Fetch IBKR snapshot data for all tickers in batches. Returns {symbol: data_dict}."""
    ib = _connect_ibkr(port)
    all_results: dict[str, dict[str, Any]] = {}

    try:
        batches = [tickers[i:i + IBKR_BATCH_SIZE]
                   for i in range(0, len(tickers), IBKR_BATCH_SIZE)]
        for idx, batch in enumerate(batches):
            batch_results = _fetch_batch_snapshots(ib, batch)
            all_results.update(batch_results)
            time.sleep(IBKR_BATCH_SLEEP)
            if progress_cb:
                progress_cb(idx + 1, len(batches), len(all_results))
    finally:
        ib.disconnect()

    return all_results


# ---------------------------------------------------------------------------
# Step 3: Pass1 gate
# ---------------------------------------------------------------------------

def apply_pass1(
    tickers: list[str],
    ibkr_data: dict[str, dict[str, Any]],
    sec_exchange: dict[str, str],
    *,
    governance: dict[str, Any],
) -> dict[str, Any]:
    eligible: list[str] = []
    reason_counts: dict[str, int] = {}
    ineligible_count = 0
    no_data_count = 0

    for sym in tickers:
        row_data = ibkr_data.get(sym, {})
        sec_exch = sec_exchange.get(sym, "")

        # Resolve exchange: prefer IBKR (more accurate), fall back to SEC
        exch = row_data.get("exchange") or sec_exch

        price = row_data.get("price")
        adv_usd = row_data.get("adv_usd")
        market_cap_usd = row_data.get("market_cap_usd")

        if not row_data:
            no_data_count += 1
            reason_counts["no_ibkr_data"] = reason_counts.get("no_ibkr_data", 0) + 1
            ineligible_count += 1
            continue

        gate_row = {
            "ticker": sym,
            "exchange": exch,
            "price": price,
            "adv_usd": adv_usd,
            "market_cap_usd": market_cap_usd,
            # Active stocks from SEC + IBKR snapshot → conservative False for status flags
            "delisted": False,
            "halted": False,
            "bankruptcy": False,
            "otc": exch not in EXCHANGE_WHITELIST if exch else True,
        }
        result = cheap_eligible(gate_row, governance=governance)
        if result["eligible"]:
            ct = result["ticker"]
            if ct and ct not in eligible:
                eligible.append(ct)
        else:
            for r in result["reasons"]:
                reason_counts[r] = reason_counts.get(r, 0) + 1
            ineligible_count += 1

    return {
        "eligible_tickers": eligible,
        "eligible_count": len(eligible),
        "ineligible_count": ineligible_count,
        "no_ibkr_data_count": no_data_count,
        "total_tickers": len(tickers),
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
    port: int = 4002,
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
    if not sec_ua and not dry_run_env:
        raise RuntimeError("SEC_USER_AGENT not set")

    if dry_run_env:
        return {"scope": {"status": "dry_run_env_only"}, "generated_at": generated_at}

    # Step 1: SEC symbol list
    print(f"[1/3] Fetching SEC NYSE/NASDAQ ticker list...")
    all_tickers = fetch_sec_nyse_nasdaq_tickers(sec_ua)
    print(f"      {len(all_tickers)} tickers found")

    # Build sec_exchange lookup
    # (re-fetch for exchange info per symbol)
    headers = {"User-Agent": sec_ua, "Host": "www.sec.gov", "Accept-Encoding": "gzip, deflate"}
    req = urllib.request.Request(SEC_EXCHANGE_TICKERS_URL, headers=headers)
    time.sleep(SEC_FAIR_ACCESS_SLEEP)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":
        raw = _gzip.decompress(raw)
    sec_data = json.loads(raw.decode("utf-8"))
    fields = sec_data.get("fields", [])
    rows = sec_data.get("data", [])
    _norm = {"NYSE": "NYSE", "Nasdaq": "NASDAQ", "NASDAQ": "NASDAQ"}
    t_idx = fields.index("ticker")
    e_idx = fields.index("exchange")
    sec_exchange = {}
    for row in rows:
        ct = canonical_us_ticker(row[t_idx] if t_idx < len(row) else "")
        exch = _norm.get(str(row[e_idx] if e_idx < len(row) else ""), "")
        if ct and exch:
            sec_exchange[ct] = exch

    # Step 2: IBKR snapshot data
    print(f"[2/3] Fetching IBKR snapshot data (port {port})...")
    n_batches = math.ceil(len(all_tickers) / IBKR_BATCH_SIZE)

    def _progress(done, total, found):
        pct = int(done / total * 100)
        print(f"      batch {done}/{total} ({pct}%) — {found} data points so far", end="\r")

    ibkr_data = fetch_ibkr_data(all_tickers, port=port, progress_cb=_progress)
    print(f"\n      {len(ibkr_data)} symbols with IBKR data")

    # Write raw data (gitignored)
    raw_path = raw_root / "ibkr_snapshot_data.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(ibkr_data, raw_path)

    # Step 3: Pass1 gate
    print(f"[3/3] Applying Pass1 eligibility gate...")
    governance = load_eligibility_governance(governance_path)
    pass1_result = apply_pass1(all_tickers, ibkr_data, sec_exchange, governance=governance)
    print(f"      eligible: {pass1_result['eligible_count']}, "
          f"ineligible: {pass1_result['ineligible_count']}")

    # Write candidate list (gitignored)
    _write_json_atomic({
        "generated_at": generated_at,
        "authorization_ref": AUTHORIZATION_REF,
        "provider": "ibkr",
        "eligible_tickers": pass1_result["eligible_tickers"],
        "eligible_count": pass1_result["eligible_count"],
    }, candidate_list_path)

    summary = {
        "schema_name": "us_short_ibkr_universe_fetch_summary",
        "schema_version": "1.0.0",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": generated_at,
        "scope": {
            "market": "US", "lane": "us_short", "batch": "batch5_provider_live",
            "status": "universe_fetch_and_pass1_completed",
            "full_market_fetch_performed": True,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "ship_gate_evidence_claimed": False,
        },
        "universe": {
            "exchange_filter": list(EXCHANGE_WHITELIST),
            "sec_tickers_found": len(all_tickers),
            "ibkr_snapshots_fetched": len(ibkr_data),
        },
        "pass1_result": pass1_result,
        "storage": {
            "raw_payload_root": _rel(raw_path.parent),
            "raw_payload_root_gitignored": True,
            "candidate_list_path": _rel(candidate_list_path),
            "candidate_list_gitignored": True,
            "tracked_summary_contains_prices": False,
            "tracked_summary_contains_secrets": False,
        },
        "sr_provider_001_remains_open": True,
        "limitations": [
            "Market cap from IBKR fundamental ratios (MKTCAP field); may be missing for some tickers.",
            "ADV from 3-month avg volume (VOL3MAVG) × price; falls back to current-day volume.",
            "Status flags (delisted/halted/bankruptcy) set to False for active SEC-listed tickers.",
            "Requires IB Gateway running; data quality depends on market data subscriptions.",
        ],
    }
    _write_json_atomic(summary, summary_path)
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Fetch NYSE/NASDAQ universe via SEC list + IBKR snapshot, then apply Pass1 gate.")
    p.add_argument("--confirm-user-authorization", action="store_true")
    p.add_argument("--dry-run-env", action="store_true")
    p.add_argument("--port", type=int, default=4002,
                   help="IB Gateway port (4002=paper, 4001=live)")
    p.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    p.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    p.add_argument("--candidate-list-path", type=Path, default=CANDIDATE_LIST_PATH)
    p.add_argument("--generated-at")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    summary = run_fetch(
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        candidate_list_path=args.candidate_list_path,
        port=args.port,
        generated_at=args.generated_at,
        confirm_user_authorization=args.confirm_user_authorization,
        dry_run_env=args.dry_run_env,
    )
    r = summary.get("pass1_result", {})
    print(f"\n=== 结果 ===")
    print(f"SEC tickers:  {summary.get('universe',{}).get('sec_tickers_found',0)}")
    print(f"IBKR data:    {summary.get('universe',{}).get('ibkr_snapshots_fetched',0)}")
    print(f"Eligible:     {r.get('eligible_count',0)}")
    print(f"Ineligible:   {r.get('ineligible_count',0)}")
    if r.get("eligible_count", 0) > 0:
        print(f"Sample:       {r.get('eligible_tickers',[])[:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
