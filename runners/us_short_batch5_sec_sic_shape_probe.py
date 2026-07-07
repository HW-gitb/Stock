"""US-short batch5 SEC SIC classification RESPONSE-SHAPE PROBE — gated small sample (piece C step 1).

Authorization: user_chat_20260707_sec_sic_shape_probe  (SR-PROVIDER-001, this run only — the user chose the
free SEC SIC classification source for the full-universe theme leg).

PURPOSE — feasibility/shape ONLY, NOT a builder (memory lesson 15: read the probed raw before writing a
binding). Before building the full-universe SEC SIC classification fetch that writes the {ticker: sector}
packet for all ~2404 eligible, confirm the REAL SEC submissions field that carries the industry classification
(is it `sic` + `sicDescription`? is it populated?). This probe fetches a bounded 3-ticker sample from the SEC
submissions endpoint (already proven accessible by the bankruptcy 8-K scans), stores the raw under gitignored
provider_samples/, and writes a tracked diagnostic summary that records ONLY the top-level key names + the
public SIC classification field names/values for the probe tickers — NO SEC User-Agent (email/PII), NO request
URLs, NO raw filings rows. It selects no provider, builds no binding/parser, writes no private state, and
claims no production/ship-gate — SR-PROVIDER-001 stays open and every gate flag is pinned closed.

Reuses the proven SEC fetch (runners/us_short_universe_fetch.py::_sec_get — gzip + fair-access UA) and the
proven secret-scanning summary writer (_write_summary_safe scans for the SEC User-Agent + provider domains
BEFORE the atomic write).

Usage:
  python runners/us_short_batch5_sec_sic_shape_probe.py --dry-run-env
  python runners/us_short_batch5_sec_sic_shape_probe.py --confirm-user-authorization
Requires env: SEC_USER_AGENT (never written to the tracked summary).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if _PYTHON_LIBS.exists() and str(_PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(_PYTHON_LIBS))

from runners import us_short_universe_fetch as universe_fetch  # noqa: E402


AUTHORIZATION_REF = "user_chat_20260707_sec_sic_shape_probe"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_sec_sic_shape_probe_summary_20260707.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_sec_sic_shape_probe_20260707")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"
# Fixed, publicly-known CIKs for a diverse 3-ticker sample (Tech / Tech / Financials).
PROBE_SYMBOLS = (("AAPL", 320193), ("MSFT", 789019), ("JPM", 19617))
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
# The SEC submissions industry-classification fields we expect (per SEC EDGAR submissions API docs); the probe
# records which of these are actually present + their values so the full fetch binds to the REAL field name.
CLASSIFICATION_KEYS = ("sic", "sicDescription")
MAX_TOTAL_CALLS = 3


class SecSicShapeProbeError(RuntimeError):
    """The SEC SIC shape probe cannot run or record safely."""


def _classification_from(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"record_found": False, "top_level_keys": [], "classification_fields": {}}
    return {
        "record_found": True,
        "top_level_keys": sorted(str(k) for k in payload.keys()),
        "classification_fields": {k: payload.get(k) for k in CLASSIFICATION_KEYS if k in payload},
    }


def run_probe(*, confirm_user_authorization: bool, generated_at: str = "2026-07-07T00:00:00+00:00") -> dict[str, Any]:
    if not confirm_user_authorization:
        raise SecSicShapeProbeError("SEC SIC shape probe requires explicit per-execution user authorization")
    sec_ua = os.environ.get("SEC_USER_AGENT", "")
    if not sec_ua:
        raise SecSicShapeProbeError("SEC_USER_AGENT not set")
    if not universe_fetch._git_check_ignored(RAW_SAMPLE_ROOT):
        raise SecSicShapeProbeError(f"raw sample root is not confirmed gitignored: {RAW_SAMPLE_REL_ROOT}")
    RAW_SAMPLE_ROOT.mkdir(parents=True, exist_ok=True)

    endpoint_results: list[dict[str, Any]] = []
    for symbol, cik in PROBE_SYMBOLS:
        url = SEC_SUBMISSIONS_URL.format(cik=cik)
        try:
            payload = universe_fetch._sec_get(url, sec_ua)
            raw_ref = RAW_SAMPLE_ROOT / f"sec_submissions_{symbol}.json"
            raw_ref.write_text(json.dumps(payload), encoding="utf-8")
            shape = _classification_from(payload)
            endpoint_results.append({
                "symbol": symbol,
                "cik": cik,
                "ok": True,
                "error_type": None,
                "raw_sample_ref": (RAW_SAMPLE_REL_ROOT / "raw" / f"sec_submissions_{symbol}.json").as_posix(),
                "record_found": shape["record_found"],
                "top_level_key_count": len(shape["top_level_keys"]),
                "classification_field_names": sorted(shape["classification_fields"].keys()),
                "classification_field_values": shape["classification_fields"],  # public SIC code + description
            })
        except Exception as exc:  # noqa: BLE001 -- a probe records the failure class, never crashes
            endpoint_results.append({
                "symbol": symbol,
                "cik": cik,
                "ok": False,
                "error_type": type(exc).__name__,
                "raw_sample_ref": None,
                "record_found": False,
                "top_level_key_count": 0,
                "classification_field_names": [],
                "classification_field_values": {},
            })

    ok_results = [r for r in endpoint_results if r["ok"]]
    summary = {
        "scope": {
            "probe": "sec_sic_classification_shape",
            "authorization_ref": AUTHORIZATION_REF,
            "generated_at": generated_at,
            "purpose": "feasibility/shape only; not a builder",
            "classification_source_under_test": "sec_sic",
            "symbols": [s for s, _ in PROBE_SYMBOLS],
            "max_total_calls": MAX_TOTAL_CALLS,
            "actual_total_calls": len(endpoint_results),
        },
        "endpoint_results": endpoint_results,
        "shape_findings": {
            "all_ok": len(ok_results) == len(PROBE_SYMBOLS),
            "classification_field_names_union": sorted(
                {name for r in ok_results for name in r["classification_field_names"]}
            ),
            "sic_present_all": all("sic" in r["classification_field_names"] for r in ok_results) and bool(ok_results),
            "sic_description_present_all": all(
                "sicDescription" in r["classification_field_names"] for r in ok_results
            ) and bool(ok_results),
        },
        "storage": {
            "raw_payload_root": RAW_SAMPLE_REL_ROOT.as_posix(),
            "raw_payload_root_gitignored": True,
            "tracked_summary_contains_secrets": False,
            "tracked_summary_contains_sec_user_agent": False,
            "tracked_summary_contains_request_urls": False,
            "tracked_summary_contains_raw_filings_rows": False,
        },
        "gate_flags": {
            "provider_selected": False,
            "binding_or_parser_built": False,
            "full_universe_fetch_performed": False,
            "classification_packet_written": False,
            "private_state_written": False,
            "datahub_consumed": False,
            "production_or_ship_gate_claimed": False,
            "sr_provider_001_closed": False,
            "a_share_crossing_performed": False,
        },
    }
    universe_fetch._write_summary_safe(summary, SUMMARY_PATH, [sec_ua])
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SEC SIC classification shape probe (3-ticker bounded sample)")
    parser.add_argument("--confirm-user-authorization", action="store_true")
    parser.add_argument("--dry-run-env", action="store_true", help="check env + gitignore + plan; NO network")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.dry_run_env:
        print(f"SEC_USER_AGENT present: {bool(os.environ.get('SEC_USER_AGENT'))}")
        print(f"raw root gitignored: {universe_fetch._git_check_ignored(RAW_SAMPLE_ROOT)}")
        print(f"planned calls: {MAX_TOTAL_CALLS}; symbols: {[s for s, _ in PROBE_SYMBOLS]}")
        return 0
    try:
        summary = run_probe(confirm_user_authorization=args.confirm_user_authorization)
    except SecSicShapeProbeError as exc:
        print(f"ERROR: {exc}")
        return 2
    f = summary["shape_findings"]
    print(f"probe complete: {summary['scope']['actual_total_calls']} calls; all_ok={f['all_ok']}")
    print(f"  classification fields present: {f['classification_field_names_union']}")
    print(f"  sic_present_all={f['sic_present_all']} sic_description_present_all={f['sic_description_present_all']}")
    for r in summary["endpoint_results"]:
        print(f"  {r['symbol']}: ok={r['ok']} fields={r['classification_field_values']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
