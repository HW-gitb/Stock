"""US-short FMP full-market universe fetch + Pass1 eligibility gate — batch5 provider/live.

Authorization: user_chat_20260626_sr_provider_001_fmp_full_market_universe_fetch
Design: docs/us_short_system_design.md §4.0 (Universe + Pass1) / §18.0 P0 / §18.1 #2 / §18.2 batch5
Authorization packet: docs/us_short_fmp_universe_fetch_authorization_20260626.json

Strategy (v1.1 — screener 404/403 on Basic plan; SEC exchange list used instead):
  1. SEC company_tickers_exchange.json (1 free call) → NYSE/NASDAQ symbol list (~7600 tickers)
  2. FMP stable/profile per symbol (up to max_fmp_calls, default 300) → price/ADV/marketCap
  3. Pass1 cheap_eligible gate → eligible candidates
  4. Write:
     - Raw SEC+FMP payloads → gitignored provider_samples/us_short_fmp_universe_fetch_20260626/raw/
     - Candidate symbol list → gitignored state/us_short/candidate_universe_20260626.json
     - Tracked summary       → docs/us_short_fmp_universe_fetch_summary_20260626.json
       (symbol list + counts + reason distribution; NO prices, NO secrets, NO request URLs)

Run requires --confirm-user-authorization for live calls.
--dry-run-env validates env/storage with no network.
--max-fmp-calls N overrides the default 300 call budget.

Boundary: no DataHub, no production storage, no ship-gate, no SEC parser, no yfinance, no Web/X,
no return calculation, no corporate-action reconciliation, no broker automation.
SR-PROVIDER-001 remains open for broader provider/live/production work.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
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
)
from runners import us_egs_sample_validation as _sv  # noqa: E402

AUTHORIZATION_ARTIFACT = ROOT / "docs" / "us_short_fmp_universe_fetch_authorization_20260626.json"
GOVERNANCE_PRESET = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_fmp_universe_fetch_summary_20260626.json"
RAW_ROOT = ROOT / "provider_samples" / "us_short_fmp_universe_fetch_20260626" / "raw"
CANDIDATE_LIST_PATH = ROOT / "state" / "us_short" / "candidate_universe_20260626.json"

AUTHORIZATION_REF = "user_chat_20260626_sr_provider_001_fmp_full_market_universe_fetch"
MAX_FMP_CALLS_DEFAULT = 300
SEC_MAX_CALLS = 1
FMP_STABLE_BASE_URL = "https://financialmodelingprep.com/stable"
SEC_EXCHANGE_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
EXCHANGE_WHITELIST = ("NYSE", "NASDAQ")
PRICE_FLOOR = 5.0
MARKET_CAP_FLOOR = 300_000_000.0
DEFAULT_TIMEOUT_SECONDS = 30
FMP_RATE_LIMIT_SLEEP = 0.25   # 240 req/min conservative; FMP Basic ~250/day but exact limit unknown
SEC_FAIR_ACCESS_SLEEP = 0.12  # SEC fair-access: ≤10 req/sec

def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


_FORBIDDEN_SUMMARY_FRAGMENTS = [
    "apikey=",
    "financialmodelingprep.com",
    '"request_url"',
    '"raw_payload"',
]


# ---------------------------------------------------------------------------
# Environment / storage guards
# ---------------------------------------------------------------------------

def _read_env() -> tuple[str, str]:
    """Return (fmp_key, sec_user_agent); raises if missing."""
    fmp_key = os.environ.get("FMP_API_KEY", "")
    sec_ua = os.environ.get("SEC_USER_AGENT", "")
    if not fmp_key:
        raise RuntimeError("FMP_API_KEY not set")
    if not sec_ua:
        raise RuntimeError("SEC_USER_AGENT not set")
    return fmp_key, sec_ua


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


def _assert_summary_safe(path: Path, fmp_key: str, sec_ua: str) -> None:
    text = path.read_text(encoding="utf-8")
    lower = text.lower()
    for frag in _FORBIDDEN_SUMMARY_FRAGMENTS:
        if frag.lower() in lower:
            raise RuntimeError(f"tracked summary contains forbidden fragment: {frag!r}")
    for secret in (fmp_key, sec_ua):
        if secret and secret in text:
            raise RuntimeError("tracked summary contains a sensitive environment value")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _fetch_json(url: str, headers: dict[str, str], *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Any:
    import gzip as _gzip
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw_bytes = resp.read()
        # Decompress gzip if needed (SEC returns gzip-encoded responses)
        if raw_bytes[:2] == b"\x1f\x8b":
            raw_bytes = _gzip.decompress(raw_bytes)
        return json.loads(raw_bytes.decode("utf-8"))


# ---------------------------------------------------------------------------
# Step 1: SEC company_tickers_exchange.json → NYSE/NASDAQ symbol list
# ---------------------------------------------------------------------------

def fetch_sec_exchange_tickers(sec_ua: str, *, raw_root: Path) -> list[str]:
    """Fetch SEC company_tickers_exchange.json, filter NYSE/NASDAQ, return sorted ticker list."""
    headers = {
        "User-Agent": sec_ua,
        "Host": "www.sec.gov",
        "Accept-Encoding": "gzip, deflate",
    }
    time.sleep(SEC_FAIR_ACCESS_SLEEP)
    data = _fetch_json(SEC_EXCHANGE_TICKERS_URL, headers)

    # Write raw SEC response (gitignored)
    raw_path = raw_root / "sec_company_tickers_exchange.json"
    _write_json_atomic(data, raw_path)

    # Parse: fields = ['cik', 'name', 'ticker', 'exchange']
    fields = data.get("fields", [])
    rows = data.get("data", [])
    if "ticker" not in fields or "exchange" not in fields:
        raise RuntimeError(f"SEC tickers response missing expected fields: {fields}")
    ticker_idx = fields.index("ticker")
    exchange_idx = fields.index("exchange")

    # SEC uses "Nasdaq" (capital N); normalize to match whitelist "NASDAQ"
    _exchange_norm = {"NYSE": "NYSE", "Nasdaq": "NASDAQ", "NASDAQ": "NASDAQ"}

    tickers = []
    for row in rows:
        raw_exch = row[exchange_idx] if exchange_idx < len(row) else ""
        norm_exch = _exchange_norm.get(str(raw_exch), "")
        if norm_exch not in EXCHANGE_WHITELIST:
            continue
        raw_ticker = row[ticker_idx] if ticker_idx < len(row) else ""
        from engine.us_short_eligibility_gate import canonical_us_ticker
        ct = canonical_us_ticker(raw_ticker)
        if ct:
            tickers.append(ct)

    return sorted(set(tickers))


# ---------------------------------------------------------------------------
# Step 2: FMP stable/profile per symbol
# ---------------------------------------------------------------------------

def _fmp_profile_url(symbol: str, fmp_key: str) -> str:
    params = urllib.parse.urlencode({"symbol": symbol, "apikey": fmp_key})
    return f"{FMP_STABLE_BASE_URL}/profile?{params}"


def fetch_fmp_profile(symbol: str, fmp_key: str, *, raw_root: Path) -> dict[str, Any] | None:
    """Fetch FMP profile for one symbol. Returns profile dict or None on error."""
    headers = {"User-Agent": "StockSystem/0.1 us-short-fmp-universe-fetch"}
    time.sleep(FMP_RATE_LIMIT_SLEEP)
    url = _fmp_profile_url(symbol, fmp_key)
    try:
        payload = _fetch_json(url, headers)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            # Rate limit or plan limit hit — stop fetching
            raise
        return None  # other HTTP errors → skip symbol
    except Exception:
        return None

    # FMP profile returns a list with one element
    if not isinstance(payload, list) or not payload:
        return None

    row = payload[0]
    if not isinstance(row, dict):
        return None

    # Write raw (gitignored)
    raw_path = raw_root / "fmp_profiles" / f"{symbol}.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(payload, raw_path)

    return row


# ---------------------------------------------------------------------------
# Step 3: map FMP profile row → cheap_eligible input
# ---------------------------------------------------------------------------

def _is_finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def map_profile_row(symbol: str, row: dict[str, Any]) -> dict[str, Any]:
    """Map FMP profile row to cheap_eligible format. Fail-closed on missing/invalid fields."""
    exchange_raw = row.get("exchangeShortName") or row.get("exchange") or ""
    exchange = str(exchange_raw).strip().upper() if exchange_raw else ""

    price = row.get("price")
    vol_avg = row.get("volAvg")
    volume = row.get("volume")
    market_cap = row.get("marketCap")
    is_actively = row.get("isActivelyTrading")
    is_etf = row.get("isEtf")

    # Dollar ADV: prefer volAvg (10-day avg daily shares), fallback to volume
    adv_usd: Any = None
    if _is_finite(vol_avg) and _is_finite(price) and vol_avg > 0:  # type: ignore[operator]
        adv_usd = float(vol_avg) * float(price)  # type: ignore[arg-type]
    elif _is_finite(volume) and _is_finite(price) and volume > 0:  # type: ignore[operator]
        adv_usd = float(volume) * float(price)  # type: ignore[arg-type]

    # Status flags: conservative inference from isActivelyTrading
    actively = is_actively is True
    delisted = not actively
    halted = not actively    # conservative; FMP doesn't expose halt status directly
    bankruptcy = not actively
    otc = exchange not in EXCHANGE_WHITELIST

    return {
        "ticker": symbol,  # use the already-canonical ticker from SEC list
        "exchange": exchange,
        "price": float(price) if _is_finite(price) else None,
        "adv_usd": adv_usd,
        "market_cap_usd": float(market_cap) if _is_finite(market_cap) else None,
        "delisted": delisted,
        "halted": halted,
        "bankruptcy": bankruptcy,
        "otc": otc,
    }


# ---------------------------------------------------------------------------
# Step 4: apply Pass1 gate
# ---------------------------------------------------------------------------

def apply_pass1_row(symbol: str, row: dict[str, Any] | None, *, governance: dict[str, Any]) -> dict[str, Any]:
    """Apply Pass1 gate to one profile row. Returns gate result dict."""
    if row is None:
        return {"ticker": symbol, "eligible": False, "reasons": ["fmp_profile_fetch_failed"]}
    gate_row = map_profile_row(symbol, row)
    return cheap_eligible(gate_row, governance=governance)


# ---------------------------------------------------------------------------
# Main run_fetch
# ---------------------------------------------------------------------------

def run_fetch(
    *,
    authorization_artifact_path: Path = AUTHORIZATION_ARTIFACT,
    governance_path: Path = GOVERNANCE_PRESET,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_ROOT,
    candidate_list_path: Path = CANDIDATE_LIST_PATH,
    generated_at: str | None = None,
    max_fmp_calls: int = MAX_FMP_CALLS_DEFAULT,
    confirm_user_authorization: bool = False,
    dry_run_env: bool = False,
) -> dict[str, Any]:
    if not confirm_user_authorization and not dry_run_env:
        raise RuntimeError("live execution requires --confirm-user-authorization")

    # Load authorization artifact
    with authorization_artifact_path.open(encoding="utf-8") as fh:
        auth = json.load(fh)
    if auth.get("authorization_ref") != AUTHORIZATION_REF:
        raise RuntimeError(f"authorization_ref mismatch: {auth.get('authorization_ref')!r}")
    if not auth.get("scope", {}).get("full_market_fetch_authorized"):
        raise RuntimeError("full_market_fetch_authorized must be true in authorization artifact")

    if not _check_gitignore():
        raise RuntimeError("provider_samples/ not confirmed in .gitignore")
    _sv.validate_raw_root(raw_root)

    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    if dry_run_env:
        fmp_key_source = "process" if os.environ.get("FMP_API_KEY") else "missing"
        sec_ua_source = "process" if os.environ.get("SEC_USER_AGENT") else "missing"
        return _build_summary(
            generated_at=generated_at, fmp_key_source=fmp_key_source,
            sec_ua_source=sec_ua_source, actual_sec_calls=0, actual_fmp_calls=0,
            dry_run_env=True, authorization_confirmed=confirm_user_authorization,
            sec_tickers_found=0, screener_rows_fetched=0,
            pass1_result={"eligible_tickers": [], "eligible_count": 0,
                          "ineligible_count": 0, "total_screener_rows": 0,
                          "fmp_fetch_failed": 0, "reason_distribution": {}},
            raw_ref=_rel(raw_root.parent),
            candidate_list_ref=_rel(candidate_list_path),
            budget_stopped=False, stop_reason=None,
        )

    fmp_key, sec_ua = _read_env()
    governance = load_eligibility_governance(governance_path)

    # --- Step 1: SEC exchange tickers ---
    sec_tickers = fetch_sec_exchange_tickers(sec_ua, raw_root=raw_root)
    sec_calls = 1

    # --- Step 2+3+4: FMP profile per symbol, up to budget ---
    eligible: list[str] = []
    ineligible: list[dict[str, Any]] = []
    fmp_fetch_failed = 0
    reason_counts: dict[str, int] = {}
    fmp_calls = 0
    budget_stopped = False
    stop_reason = None

    for symbol in sec_tickers:
        if fmp_calls >= max_fmp_calls:
            budget_stopped = True
            stop_reason = f"fmp_call_budget_reached_{max_fmp_calls}"
            break
        try:
            profile_row = fetch_fmp_profile(symbol, fmp_key, raw_root=raw_root)
            fmp_calls += 1
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                budget_stopped = True
                stop_reason = f"fmp_http_{exc.code}_plan_or_rate_limit"
                break
            fmp_fetch_failed += 1
            fmp_calls += 1
            profile_row = None
        except Exception:
            fmp_fetch_failed += 1
            fmp_calls += 1
            profile_row = None

        result = apply_pass1_row(symbol, profile_row, governance=governance)
        if result["eligible"]:
            ct = result["ticker"]
            if ct and ct not in eligible:
                eligible.append(ct)
        else:
            for r in result["reasons"]:
                reason_counts[r] = reason_counts.get(r, 0) + 1
            ineligible.append({"ticker": result["ticker"] or symbol, "reasons": result["reasons"]})

    pass1_result = {
        "eligible_tickers": eligible,
        "eligible_count": len(eligible),
        "ineligible_count": len(ineligible),
        "total_screener_rows": fmp_calls,
        "fmp_fetch_failed": fmp_fetch_failed,
        "reason_distribution": reason_counts,
    }

    # Write candidate list (gitignored)
    candidate_list_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic({
        "generated_at": generated_at,
        "authorization_ref": AUTHORIZATION_REF,
        "pass1_governance_preset": "presets/us_short_eligibility_governance_20260624.json",
        "sec_tickers_found": len(sec_tickers),
        "fmp_profiles_fetched": fmp_calls,
        "budget_stopped": budget_stopped,
        "stop_reason": stop_reason,
        "eligible_tickers": eligible,
        "eligible_count": len(eligible),
    }, candidate_list_path)

    summary = _build_summary(
        generated_at=generated_at,
        fmp_key_source="process",
        sec_ua_source="process",
        actual_sec_calls=sec_calls,
        actual_fmp_calls=fmp_calls,
        dry_run_env=False,
        authorization_confirmed=confirm_user_authorization,
        sec_tickers_found=len(sec_tickers),
        screener_rows_fetched=fmp_calls,
        pass1_result=pass1_result,
        raw_ref=_rel(raw_root / "fmp_profiles"),
        candidate_list_ref=_rel(candidate_list_path),
        budget_stopped=budget_stopped,
        stop_reason=stop_reason,
    )
    _write_json_atomic(summary, summary_path)
    _assert_summary_safe(summary_path, fmp_key, sec_ua)
    return summary


# ---------------------------------------------------------------------------
# Summary builder (pure, no I/O)
# ---------------------------------------------------------------------------

def _build_summary(
    *,
    generated_at: str,
    fmp_key_source: str,
    sec_ua_source: str,
    actual_sec_calls: int,
    actual_fmp_calls: int,
    dry_run_env: bool,
    authorization_confirmed: bool,
    sec_tickers_found: int,
    screener_rows_fetched: int,
    pass1_result: dict[str, Any],
    raw_ref: str,
    candidate_list_ref: str,
    budget_stopped: bool,
    stop_reason: str | None,
) -> dict[str, Any]:
    status = "dry_run_env_only" if dry_run_env else (
        "universe_fetch_partial_budget_stop" if budget_stopped else "universe_fetch_and_pass1_completed"
    )
    return {
        "schema_name": "us_short_fmp_universe_fetch_summary",
        "schema_version": "1.1.0",
        "authorization_ref": AUTHORIZATION_REF,
        "authorization_artifact": "docs/us_short_fmp_universe_fetch_authorization_20260626.json",
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "status": status,
            "full_market_fetch_performed": not dry_run_env,
            "pass1_gate_applied": not dry_run_env,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "ship_gate_evidence_claimed": False,
            "live_normalized_evidence_claimed": False,
        },
        "pre_execution_checks": {
            "authorization_confirmed": authorization_confirmed,
            "provider_samples_gitignored": True,
            "fmp_api_key_present": fmp_key_source == "process",
            "fmp_api_key_source": fmp_key_source,
            "sec_user_agent_present": sec_ua_source == "process",
            "sec_user_agent_source": sec_ua_source,
            "secrets_logged": False,
            "request_urls_logged": False,
        },
        "storage": {
            "raw_payload_root": raw_ref,
            "raw_payload_root_gitignored": True,
            "candidate_list_path": candidate_list_ref,
            "candidate_list_gitignored": True,
            "tracked_summary_path": "docs/us_short_fmp_universe_fetch_summary_20260626.json",
            "tracked_summary_contains_prices": False,
            "tracked_summary_contains_secrets": False,
            "tracked_summary_contains_request_urls": False,
        },
        "endpoint_call_budget": {
            "actual_sec_calls": actual_sec_calls,
            "actual_fmp_calls": actual_fmp_calls,
            "max_fmp_calls_configured": MAX_FMP_CALLS_DEFAULT,
            "retry_count": 0,
            "budget_stopped": budget_stopped,
            "stop_reason": stop_reason,
        },
        "universe": {
            "exchange_filter": list(EXCHANGE_WHITELIST),
            "price_floor_usd": PRICE_FLOOR,
            "market_cap_floor_usd": MARKET_CAP_FLOOR,
            "sec_tickers_found": sec_tickers_found,
            "fmp_profiles_fetched": screener_rows_fetched,
        },
        "pass1_result": pass1_result,
        "sr_provider_001_remains_open": True,
        "limitations": [
            "FMP Basic plan does not support bulk screener; per-symbol profile calls used.",
            "ADV computed as volAvg*price or volume*price; single-day proxy if volAvg absent.",
            "Status flags inferred from FMP isActivelyTrading; conservative (not-actively→all-flags=True).",
            "Budget may stop early if FMP call limit reached; eligible set covers budget window only.",
            "Does not authorize DataHub, production storage, ship-gate, live_normalized, or SEC parser.",
            "SR-PROVIDER-001 remains open for broader provider/live/production/ship-gate work.",
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch NYSE/NASDAQ universe via SEC exchange list + FMP per-symbol profile, then apply Pass1 gate.")
    p.add_argument("--confirm-user-authorization", action="store_true")
    p.add_argument("--dry-run-env", action="store_true")
    p.add_argument("--max-fmp-calls", type=int, default=MAX_FMP_CALLS_DEFAULT)
    p.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    p.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    p.add_argument("--candidate-list-path", type=Path, default=CANDIDATE_LIST_PATH)
    p.add_argument("--generated-at")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_fetch(
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        candidate_list_path=args.candidate_list_path,
        generated_at=args.generated_at,
        max_fmp_calls=args.max_fmp_calls,
        confirm_user_authorization=args.confirm_user_authorization,
        dry_run_env=args.dry_run_env,
    )
    r = summary["pass1_result"]
    print(f"sec_tickers: {summary['universe']['sec_tickers_found']}")
    print(f"fmp_calls:   {summary['endpoint_call_budget']['actual_fmp_calls']}")
    print(f"eligible:    {r['eligible_count']}")
    print(f"ineligible:  {r['ineligible_count']}")
    print(f"failed:      {r.get('fmp_fetch_failed', 0)}")
    print(f"stopped:     {summary['endpoint_call_budget']['budget_stopped']} ({summary['endpoint_call_budget']['stop_reason']})")
    print(f"status:      {summary['scope']['status']}")
    if r["eligible_count"] > 0:
        print(f"sample:      {r['eligible_tickers'][:5]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
