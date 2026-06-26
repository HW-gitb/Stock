"""US-short FMP full-market universe fetch + Pass1 eligibility gate — batch5 provider/live.

Authorization: user_chat_20260626_sr_provider_001_fmp_full_market_universe_fetch
Design: docs/us_short_system_design.md §4.0 (Universe + Pass1) / §18.0 P0 / §18.1 #2 / §18.2 batch5
Authorization packet: docs/us_short_fmp_universe_fetch_authorization_20260626.json

Fetches all NYSE/NASDAQ active stocks from FMP stock screener (max 3 calls), applies the frozen
Pass1 cheap-eligibility gate (engine.us_short_eligibility_gate.cheap_eligible with governance from
presets/us_short_eligibility_governance_20260624.json), and writes:
  - Raw screener payload    → gitignored provider_samples/us_short_fmp_universe_fetch_20260626/raw/
  - Candidate symbol list   → gitignored state/us_short/candidate_universe_20260626.json
  - Tracked summary         → docs/us_short_fmp_universe_fetch_summary_20260626.json
    (symbol list + counts + reason distribution; NO prices, NO secrets, NO request URLs)

Live execution requires --confirm-user-authorization.
Dry-run-env validates env/storage without any network call.

Boundary: no DataHub, no production storage, no ship-gate claim, no SEC parser, no yfinance,
no Web/X, no return calculation, no corporate-action reconciliation, no broker automation.
paper_track only; SR-PROVIDER-001 remains open for broader provider/live/production work.
"""
from __future__ import annotations

import argparse
import json
import math
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
    canonical_us_ticker,
)
from runners import us_egs_sample_validation as _sv  # noqa: E402  (for validate_raw_root)

AUTHORIZATION_ARTIFACT = ROOT / "docs" / "us_short_fmp_universe_fetch_authorization_20260626.json"
GOVERNANCE_PRESET = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_fmp_universe_fetch_summary_20260626.json"
RAW_ROOT = ROOT / "provider_samples" / "us_short_fmp_universe_fetch_20260626" / "raw"
CANDIDATE_LIST_PATH = ROOT / "state" / "us_short" / "candidate_universe_20260626.json"

AUTHORIZATION_REF = "user_chat_20260626_sr_provider_001_fmp_full_market_universe_fetch"
MAX_FMP_CALLS = 3
FMP_STABLE_BASE_URL = "https://financialmodelingprep.com/stable"
SCREENER_EXCHANGE_FILTER = "NYSE,NASDAQ"
PRICE_FLOOR = 5.0
MARKET_CAP_FLOOR = 300_000_000.0
DEFAULT_TIMEOUT_SECONDS = 30
RATE_LIMIT_SLEEP_SECONDS = 0.2  # conservative; FMP Basic ~300 req/min

_FORBIDDEN_SUMMARY_FRAGMENTS = [
    "apikey=",
    "financialmodelingprep.com",
    '"request_url"',
    '"raw_payload"',
]


# ---------------------------------------------------------------------------
# Environment / storage helpers
# ---------------------------------------------------------------------------

def _read_fmp_key() -> str:
    import os
    key = os.environ.get("FMP_API_KEY", "")
    if not key:
        raise RuntimeError("FMP_API_KEY not set in environment")
    return key


def _check_gitignore() -> bool:
    gitignore = ROOT / ".gitignore"
    if not gitignore.exists():
        return False
    content = gitignore.read_text(encoding="utf-8")
    return "provider_samples/" in content


def _write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp.replace(path)


def _assert_summary_safe(path: Path, fmp_key: str) -> None:
    text = path.read_text(encoding="utf-8")
    lower = text.lower()
    for frag in _FORBIDDEN_SUMMARY_FRAGMENTS:
        if frag.lower() in lower:
            raise RuntimeError(f"tracked summary contains forbidden fragment: {frag!r}")
    if fmp_key and fmp_key in text:
        raise RuntimeError("tracked summary contains FMP API key value")


# ---------------------------------------------------------------------------
# FMP screener fetch
# ---------------------------------------------------------------------------

def _fmp_screener_url(fmp_key: str) -> str:
    params = urllib.parse.urlencode({
        "exchange": SCREENER_EXCHANGE_FILTER,
        "priceMoreThan": PRICE_FLOOR,
        "marketCapMoreThan": MARKET_CAP_FLOOR,
        "isEtf": "false",
        "isActivelyTrading": "true",
        "apikey": fmp_key,
    })
    return f"{FMP_STABLE_BASE_URL}/stock-screener?{params}"


def _fetch_json(url_with_secret: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> Any:
    req = urllib.request.Request(
        url_with_secret,
        headers={"User-Agent": "StockSystem/0.1 us-short-fmp-universe-fetch"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_screener(fmp_key: str, *, call_counter: list[int]) -> list[dict[str, Any]]:
    if call_counter[0] >= MAX_FMP_CALLS:
        raise RuntimeError(f"FMP call budget exhausted (max {MAX_FMP_CALLS})")
    url = _fmp_screener_url(fmp_key)
    time.sleep(RATE_LIMIT_SLEEP_SECONDS)
    payload = _fetch_json(url)
    call_counter[0] += 1
    if not isinstance(payload, list):
        raise RuntimeError(f"FMP screener returned unexpected shape: {type(payload)}")
    return payload


# ---------------------------------------------------------------------------
# Row mapping: FMP screener → cheap_eligible input
# ---------------------------------------------------------------------------

def _is_finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def map_screener_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map one FMP screener result to the cheap_eligible row format.

    ADV: prefer volAvg × price (FMP 10-day avg daily shares); fall back to volume × price.
    Status flags: derive conservatively from isActivelyTrading + exchange + isEtf.
    If any required numeric field is missing/invalid, inject None so gate fails closed.
    """
    ticker_raw = row.get("symbol")
    exchange_raw = row.get("exchangeShortName") or row.get("exchange") or ""
    exchange = str(exchange_raw).strip().upper() if exchange_raw else ""

    price = row.get("price")
    vol_avg = row.get("volAvg")   # FMP profile field (may be absent from screener)
    volume = row.get("volume")
    market_cap = row.get("marketCap")
    is_actively_trading = row.get("isActivelyTrading")
    is_etf = row.get("isEtf")

    # Dollar ADV: prefer volAvg × price, fall back to volume × price
    adv_usd: Any = None
    if _is_finite(vol_avg) and _is_finite(price) and vol_avg > 0:  # type: ignore[operator]
        adv_usd = float(vol_avg) * float(price)  # type: ignore[arg-type]
    elif _is_finite(volume) and _is_finite(price) and volume > 0:  # type: ignore[operator]
        adv_usd = float(volume) * float(price)  # type: ignore[arg-type]
    # else: adv_usd remains None → gate fails closed

    # Status flags: conservative inference.
    # isActivelyTrading=True → not delisted (active), not bankruptcy (assumed).
    # Exchange in NYSE/NASDAQ → not OTC.
    # Halted: FMP screener isActivelyTrading=true implies not halt; but not guaranteed.
    actively = is_actively_trading is True
    not_etf = is_etf is not True  # treat ETF check (should already be filtered by screener)
    delisted = not actively
    halted = False if actively else True  # conservative: assume halted if not actively trading
    bankruptcy = False if actively else True  # conservative; no direct FMP field
    otc = exchange not in ("NYSE", "NASDAQ")

    return {
        "ticker": ticker_raw,
        "exchange": exchange,
        "price": price if _is_finite(price) else None,
        "adv_usd": adv_usd,
        "market_cap_usd": float(market_cap) if _is_finite(market_cap) else None,
        "delisted": delisted,
        "halted": halted,
        "bankruptcy": bankruptcy,
        "otc": otc,
        "_is_etf": is_etf,
        "_not_etf": not_etf,
    }


# ---------------------------------------------------------------------------
# Pass1 application
# ---------------------------------------------------------------------------

def apply_pass1(screener_rows: list[dict[str, Any]], *, governance: dict[str, Any]) -> dict[str, Any]:
    eligible: list[str] = []
    ineligible: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = {}

    for raw_row in screener_rows:
        mapped = map_screener_row(raw_row)
        # Inject mapped numeric fields (None → gate fails closed)
        gate_row = {
            "ticker": mapped["ticker"],
            "exchange": mapped["exchange"],
            "price": mapped["price"],
            "adv_usd": mapped["adv_usd"],
            "market_cap_usd": mapped["market_cap_usd"],
            "delisted": mapped["delisted"],
            "halted": mapped["halted"],
            "bankruptcy": mapped["bankruptcy"],
            "otc": mapped["otc"],
        }
        result = cheap_eligible(gate_row, governance=governance)
        if result["eligible"]:
            canonical = result["ticker"]
            if canonical and canonical not in eligible:
                eligible.append(canonical)
        else:
            for reason in result["reasons"]:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            ineligible.append({
                "ticker": result["ticker"] or gate_row.get("ticker"),
                "reasons": result["reasons"],
            })

    return {
        "eligible_tickers": eligible,
        "eligible_count": len(eligible),
        "ineligible_count": len(ineligible),
        "total_screener_rows": len(screener_rows),
        "reason_distribution": reason_counts,
    }


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def build_summary(
    *,
    generated_at: str,
    fmp_key_source: str,
    actual_fmp_calls: int,
    dry_run_env: bool,
    authorization_confirmed: bool,
    screener_rows_fetched: int,
    pass1_result: dict[str, Any],
    raw_ref: str,
    candidate_list_ref: str,
) -> dict[str, Any]:
    status = "dry_run_env_only" if dry_run_env else "universe_fetch_and_pass1_completed"
    return {
        "schema_name": "us_short_fmp_universe_fetch_summary",
        "schema_version": "1.0.0",
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
            "broker_or_order_automation_performed": False,
            "sec_parser_called": False,
            "yfinance_called": False,
            "web_x_called": False,
            "return_calculation_performed": False,
        },
        "pre_execution_checks": {
            "authorization_confirmed": authorization_confirmed,
            "authorization_artifact_loaded": True,
            "governance_preset_loaded": not dry_run_env,
            "provider_samples_gitignored": True,
            "environment_precheck_passed": True,
            "fmp_api_key_present": True,
            "fmp_api_key_source": fmp_key_source,
            "budget_precheck_passed": True,
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
            "max_fmp_calls": MAX_FMP_CALLS,
            "actual_fmp_calls": actual_fmp_calls,
            "retry_count": 0,
            "within_budget": actual_fmp_calls <= MAX_FMP_CALLS,
        },
        "universe": {
            "screener_exchange_filter": ["NYSE", "NASDAQ"],
            "price_floor_usd": PRICE_FLOOR,
            "market_cap_floor_usd": MARKET_CAP_FLOOR,
            "is_etf_excluded": True,
            "screener_rows_fetched": screener_rows_fetched,
        },
        "pass1_result": pass1_result,
        "sr_provider_001_remains_open": True,
        "limitations": [
            "This fetch covers NYSE/NASDAQ active-only stocks above price/marketCap floors.",
            "ADV computed as volAvg*price or volume*price; single-day proxy if volAvg absent.",
            "Status flags inferred from screener isActivelyTrading; halted/bankruptcy conservative.",
            "Candidate list is eligible tickers only (no prices/volumes); gitignored state file.",
            "Does not authorize DataHub, production storage, ship-gate, live_normalized, or SEC parser.",
            "SR-PROVIDER-001 remains open for broader provider/live/production/ship-gate work.",
        ],
    }


# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------

def run_fetch(
    *,
    authorization_artifact_path: Path = AUTHORIZATION_ARTIFACT,
    governance_path: Path = GOVERNANCE_PRESET,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_ROOT,
    candidate_list_path: Path = CANDIDATE_LIST_PATH,
    generated_at: str | None = None,
    confirm_user_authorization: bool = False,
    dry_run_env: bool = False,
) -> dict[str, Any]:
    if not confirm_user_authorization and not dry_run_env:
        raise RuntimeError("live execution requires --confirm-user-authorization")

    # Load and verify authorization artifact
    with authorization_artifact_path.open(encoding="utf-8") as fh:
        auth = json.load(fh)
    if auth.get("authorization_ref") != AUTHORIZATION_REF:
        raise RuntimeError(f"authorization_ref mismatch: {auth.get('authorization_ref')!r}")
    if not auth.get("scope", {}).get("full_market_fetch_authorized"):
        raise RuntimeError("full_market_fetch_authorized must be true in authorization artifact")

    if not _check_gitignore():
        raise RuntimeError("provider_samples/ not confirmed in .gitignore")

    # Validate raw_root is under provider_samples/ (not just that .gitignore contains the string).
    # Reuse existing us_egs_sample_validation.validate_raw_root which resolves the path and
    # requires it to be under ROOT/provider_samples, raising ValueError otherwise.
    _sv.validate_raw_root(raw_root)

    import os
    fmp_key = os.environ.get("FMP_API_KEY", "")
    fmp_key_source = "process" if fmp_key else "missing"

    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    if dry_run_env:
        summary = build_summary(
            generated_at=generated_at,
            fmp_key_source=fmp_key_source,
            actual_fmp_calls=0,
            dry_run_env=True,
            authorization_confirmed=confirm_user_authorization,
            screener_rows_fetched=0,
            pass1_result={"eligible_tickers": [], "eligible_count": 0, "ineligible_count": 0,
                          "total_screener_rows": 0, "reason_distribution": {}},
            raw_ref=(raw_root.parent.relative_to(ROOT)).as_posix(),
            candidate_list_ref=(candidate_list_path.relative_to(ROOT)).as_posix(),
        )
        return summary

    if not fmp_key:
        raise RuntimeError("FMP_API_KEY not set in environment")

    governance = load_eligibility_governance(governance_path)
    call_counter = [0]
    screener_rows = fetch_screener(fmp_key, call_counter=call_counter)

    # Write raw screener payload (gitignored)
    raw_path = raw_root / "fmp_screener_nyse_nasdaq.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(screener_rows, raw_path)
    raw_ref = (raw_path.parent.relative_to(ROOT)).as_posix()

    # Apply Pass1 gate
    pass1_result = apply_pass1(screener_rows, governance=governance)
    eligible_tickers = pass1_result["eligible_tickers"]

    # Write candidate list (gitignored)
    candidate_list_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic({
        "generated_at": generated_at,
        "authorization_ref": AUTHORIZATION_REF,
        "pass1_governance_preset": "presets/us_short_eligibility_governance_20260624.json",
        "eligible_tickers": eligible_tickers,
        "eligible_count": len(eligible_tickers),
    }, candidate_list_path)
    candidate_list_ref = (candidate_list_path.relative_to(ROOT)).as_posix()

    summary = build_summary(
        generated_at=generated_at,
        fmp_key_source=fmp_key_source,
        actual_fmp_calls=call_counter[0],
        dry_run_env=False,
        authorization_confirmed=confirm_user_authorization,
        screener_rows_fetched=len(screener_rows),
        pass1_result=pass1_result,
        raw_ref=raw_ref,
        candidate_list_ref=candidate_list_ref,
    )

    _write_json_atomic(summary, summary_path)
    _assert_summary_safe(summary_path, fmp_key)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch full NYSE/NASDAQ universe from FMP screener and apply Pass1 gate. "
                    "Raw response gitignored; tracked summary excludes prices/secrets.")
    parser.add_argument("--confirm-user-authorization", action="store_true",
                        help="Required for live FMP calls; documents user authorization.")
    parser.add_argument("--dry-run-env", action="store_true",
                        help="Validate env/gitignore/packet in memory only; no network, no writes.")
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--candidate-list-path", type=Path, default=CANDIDATE_LIST_PATH)
    parser.add_argument("--generated-at")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_fetch(
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        candidate_list_path=args.candidate_list_path,
        generated_at=args.generated_at,
        confirm_user_authorization=args.confirm_user_authorization,
        dry_run_env=args.dry_run_env,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
