"""US-short benchmark-ETF DIVIDEND COVERAGE probe — gated 4-call Massive sample.

Authorization: user_chat_20260804_massive_benchmark_etf_dividend_coverage_probe  (SR-PROVIDER-001, this run only)

PURPOSE — a single go/no-go feasibility fact, NOT a builder. The planned 26-week market-performance
diagnostic track needs a TOTAL-RETURN benchmark leg, which requires each benchmark ETF's ex-dividend date
plus per-share cash amount. Every Massive corporate-action fetch this repo has ever run queried INDIVIDUAL
STOCKS only (`us_short_batch5_massive_corporate_action_shape_probe` = AAPL/MSFT; the 20260712 validation =
AAPL/MSFT/TSLA); NO ETF has ever been queried, and the market-wide window query in
`runners/us_short_forward_policy_corporate_action_fetch.py` has never been executed live. So "does Massive's
dividend corpus cover SPY/QQQ/IWB/VTI" is an UNVERIFIED ASSUMPTION. It must be settled BEFORE the diagnostic
track's method is frozen, because a no-coverage answer is a DESIGN FORK (switch the dividend source), not a
detail — and discovering it after 26 weeks of accumulation would invalidate the benchmark leg retroactively.

This probe fetches a bounded 4-ticker x 1-family Massive sample, stores raw under gitignored
provider_samples/, and writes a tracked diagnostic summary recording ONLY status classes, response-shape key
names, counts and derived booleans — NO secrets, NO request URLs, NO raw payload rows/values. It selects no
provider, builds no binding/parser, computes no return or adjustment, writes no private state, consumes no
DataHub, wires no diagnostic track, and claims no production/ship-gate/reconciliation. SR-PROVIDER-001 stays
open and every gate flag in the summary is pinned closed.

FALSE-POSITIVE GUARD (why row_count alone is not the answer): if the provider ignored an unrecognised
`ticker` filter and returned market-wide rows, a naive `event_count > 0` would read as "covered" when the ETF
is in fact absent. So each returned row's own `ticker` field is compared against the queried symbol and only
the COUNT of matches is recorded; ANY non-matching / malformed / ticker-less row makes the verdict
`rows_do_not_match_queried_ticker` rather than `covered` (fail-closed toward "not verified").

Endpoint-family allowlist (fail-closed): dividends. Anything else aborts before network. Splits are
deliberately OUT of scope — the benchmark price series is already split-adjusted (Massive grouped-daily),
so only the dividend leg is unknown.

Outputs (research-only):
  - Gitignored raw  -> provider_samples/us_short_benchmark_etf_dividend_coverage_probe_20260804/raw/
  - Tracked summary -> docs/us_short_benchmark_etf_dividend_coverage_probe_summary_20260804.json
                       (schema-validated + secret-scanned BEFORE the atomic write, so a schema-invalid or
                       secret/url/raw-bearing summary is never written)

Usage:
  python runners/us_short_benchmark_etf_dividend_coverage_probe.py --dry-run-env
  python runners/us_short_benchmark_etf_dividend_coverage_probe.py --confirm-user-authorization
Requires env: MASSIVE_API_KEY (never printed or logged).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if _PYTHON_LIBS.exists() and str(_PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(_PYTHON_LIBS))

from runners import us_egs_sample_validation as sample_validation  # noqa: E402


AUTHORIZATION_REF = "user_chat_20260804_massive_benchmark_etf_dividend_coverage_probe"
SUMMARY_PATH = ROOT / "docs" / "us_short_benchmark_etf_dividend_coverage_probe_summary_20260804.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_benchmark_etf_dividend_coverage_probe_summary.schema.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_benchmark_etf_dividend_coverage_probe_20260804")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"

# The four benchmark candidates of the planned 26-week diagnostic track (design 15 + ship-gate 6):
# IWB = Russell 1000 ETF proxy (provisional primary), SPY = broad market, QQQ = growth/tech style control,
# VTI = continuity with the ship-gate economic-alpha primary benchmark.
BENCHMARK_ETF_SYMBOLS = ("SPY", "QQQ", "IWB", "VTI")
ENDPOINT_FAMILY_ALLOWLIST = ("dividends",)
MASSIVE_DIVIDENDS_URL = "https://api.massive.com/stocks/v1/dividends?ticker={ticker}&limit=10&apiKey={key}"
MAX_TOTAL_ENDPOINT_CALLS = 4  # 4 symbols x 1 family; no retry, no headroom

# The exact field names the total-return benchmark leg would consume. Recorded as NAMES only.
REQUIRED_DIVIDEND_FIELD_NAMES = ("ex_dividend_date", "cash_amount")


class BenchmarkEtfDividendCoverageProbeError(RuntimeError):
    """The benchmark-ETF dividend coverage probe cannot run or record safely."""


def _url_for(family: str, ticker: str, key: str) -> str:
    if family == "dividends":
        return MASSIVE_DIVIDENDS_URL.format(ticker=ticker, key=key)
    raise BenchmarkEtfDividendCoverageProbeError(f"endpoint family outside allowlist: {family!r}")


def _provider_samples_gitignored() -> bool:
    try:
        import subprocess

        result = subprocess.run(
            ["git", "check-ignore", str(RAW_SAMPLE_ROOT)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def _result_container(payload: Any) -> tuple[str | None, list[Any]]:
    """Locate the event list inside a provider payload WITHOUT reading any value. Massive/Polygon-style
    envelopes carry events under `results`; bare-list or `data`/`historical` shapes are also probed so the
    real container key is discovered rather than assumed."""
    if isinstance(payload, list):
        return "<root-list>", payload
    if isinstance(payload, dict):
        for key in ("results", "data", "historical", "dividends"):
            value = payload.get(key)
            if isinstance(value, list):
                return key, value
    return None, []


def _shape_of(payload: Any) -> dict[str, Any]:
    """Record ONLY structural metadata: payload type, top-level key names, the event-list container key +
    length, and the union of KEY NAMES across event items (field names, never values)."""
    container_key, events = _result_container(payload)
    item_keys: list[str] = []
    for item in events:
        if isinstance(item, dict):
            for key in item.keys():
                if key not in item_keys:
                    item_keys.append(str(key))
    return {
        "payload_type": type(payload).__name__,
        "top_level_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
        "event_container_key": container_key,
        "event_count": len(events),
        "event_item_key_names": sorted(item_keys),  # field NAMES only, no values
        "has_pagination_field": isinstance(payload, dict)
        and any(k in payload for k in ("next_url", "next", "cursor")),
    }


def _rows_matching_queried_ticker(payload: Any, queried_symbol: str) -> int:
    """COUNT (never emit) the rows whose own `ticker` equals the queried symbol. Guards the false positive
    where a provider ignores an unrecognised ticker filter and returns market-wide rows. A row that is not a
    dict, lacks `ticker`, or carries a non-string / different ticker is NOT counted (fail-closed)."""
    _, events = _result_container(payload)
    wanted = queried_symbol.strip().upper()
    matched = 0
    for item in events:
        if not isinstance(item, dict):
            continue
        value = item.get("ticker")
        if isinstance(value, str) and value.strip().upper() == wanted:
            matched += 1
    return matched


def _coverage_verdict(*, ok: bool, row_count: int, matched_rows: int, required_fields_present: bool) -> str:
    """Fail-closed ordering: only a fully clean result may read as `covered`."""
    if not ok:
        return "endpoint_error"
    if row_count == 0:
        return "queried_ok_but_no_rows"
    if matched_rows != row_count:
        return "rows_do_not_match_queried_ticker"
    if not required_fields_present:
        return "rows_missing_required_fields"
    return "covered"


def _source_viability(symbol_results: list[dict[str, Any]]) -> str:
    """Roll the per-symbol verdicts into ONE go/no-go for the diagnostic track's dividend leg."""
    if not symbol_results:
        return "endpoint_error"
    if all(r["coverage_verdict"] == "endpoint_error" for r in symbol_results):
        return "endpoint_error"
    covered = sum(1 for r in symbol_results if r["coverage_verdict"] == "covered")
    if covered == len(symbol_results):
        return "viable_all"
    if covered > 0:
        return "viable_partial"
    return "not_viable"


def _validate_summary_schema(summary: dict[str, Any]) -> None:
    from jsonschema import Draft7Validator

    schema = json.loads(SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft7Validator(schema).iter_errors(summary), key=lambda e: e.path)
    if errors:
        raise BenchmarkEtfDividendCoverageProbeError(
            f"probe summary failed schema validation: {errors[0].message}"
        )


def _scan_summary_safe(text: str, sensitive_values: list[str]) -> None:
    lower = text.lower()
    for fragment in ("apikey=", "api.massive.com", "http://", "https://", '"payload"', '"raw_payload"'):
        if fragment in lower:
            raise BenchmarkEtfDividendCoverageProbeError(
                f"probe summary contains a forbidden fragment: {fragment}"
            )
    for value in sensitive_values:
        if value and value in text:
            raise BenchmarkEtfDividendCoverageProbeError(
                "probe summary contains a sensitive environment value"
            )


def _write_summary_validated(summary: dict[str, Any], sensitive_values: list[str]) -> None:
    _validate_summary_schema(summary)
    text = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _scan_summary_safe(text, sensitive_values)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SUMMARY_PATH.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(SUMMARY_PATH)


def run_probe(
    *,
    confirm_user_authorization: bool,
    client: sample_validation.JsonHttpClient | None = None,
    generated_at: str = "2026-08-04T00:00:00+00:00",
) -> dict[str, Any]:
    if not confirm_user_authorization:
        raise BenchmarkEtfDividendCoverageProbeError(
            "benchmark-ETF dividend coverage probe requires explicit per-execution user authorization"
        )
    if not _provider_samples_gitignored():
        raise BenchmarkEtfDividendCoverageProbeError(
            f"raw sample root is not confirmed gitignored: {RAW_SAMPLE_REL_ROOT}"
        )
    massive_env = sample_validation.read_required_env("MASSIVE_API_KEY")
    client = client or sample_validation.JsonHttpClient()
    headers = {"User-Agent": "StockSystem/0.1 us-short-benchmark-etf-dividend-coverage-probe"}

    records: list[sample_validation.FetchRecord] = []
    symbol_results: list[dict[str, Any]] = []
    for symbol in BENCHMARK_ETF_SYMBOLS:
        for family in ENDPOINT_FAMILY_ALLOWLIST:
            if family not in ENDPOINT_FAMILY_ALLOWLIST:  # defense-in-depth: never fetch off the allowlist
                raise BenchmarkEtfDividendCoverageProbeError(
                    f"endpoint family outside allowlist: {family!r}"
                )
            sample_validation.assert_endpoint_budget_available(records, MAX_TOTAL_ENDPOINT_CALLS)
            record = sample_validation.fetch_and_store(
                client,
                url=_url_for(family, symbol, massive_env.value),
                provider_id="massive",
                endpoint_family=family,
                symbol=symbol,
                raw_root=RAW_SAMPLE_ROOT,
                headers=headers,
            )
            records.append(record)

            shape = _shape_of(record.payload) if record.ok else None
            row_count = shape["event_count"] if shape else 0
            matched_rows = _rows_matching_queried_ticker(record.payload, symbol) if record.ok else 0
            required_fields_present = bool(
                shape
                and all(name in shape["event_item_key_names"] for name in REQUIRED_DIVIDEND_FIELD_NAMES)
            )
            symbol_results.append(
                {
                    "symbol": symbol,
                    "endpoint_family": family,
                    "http_status": record.http_status,
                    "ok": bool(record.ok),
                    "error_type": record.error_type,
                    "raw_sample_ref": record.raw_sample_ref,
                    "response_shape": shape,
                    "row_count": row_count,
                    "rows_matching_queried_ticker": matched_rows,
                    "required_field_names_present": required_fields_present,
                    "coverage_verdict": _coverage_verdict(
                        ok=bool(record.ok),
                        row_count=row_count,
                        matched_rows=matched_rows,
                        required_fields_present=required_fields_present,
                    ),
                }
            )

    summary = {
        "scope": {
            "probe": "benchmark_etf_dividend_coverage",
            "authorization_ref": AUTHORIZATION_REF,
            "generated_at": generated_at,
            "purpose": "go/no-go source-availability fact for the planned 26w diagnostic total-return benchmark leg; not a builder",
            "endpoint_family_allowlist": list(ENDPOINT_FAMILY_ALLOWLIST),
            "symbols": list(BENCHMARK_ETF_SYMBOLS),
            "required_dividend_field_names": list(REQUIRED_DIVIDEND_FIELD_NAMES),
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "actual_total_endpoint_calls": len(records),
        },
        "symbol_results": symbol_results,
        "coverage_findings": {
            "benchmark_dividend_source_viable": _source_viability(symbol_results),
            "covered_symbol_count": sum(1 for r in symbol_results if r["coverage_verdict"] == "covered"),
            "http_status_classes": sorted({r["http_status"] for r in symbol_results}, key=lambda s: (s is None, s)),
            "observed_event_item_key_names": sorted(
                {
                    key
                    for r in symbol_results
                    if r["response_shape"]
                    for key in r["response_shape"]["event_item_key_names"]
                }
            ),
        },
        "storage": {
            "raw_payload_root": str(RAW_SAMPLE_REL_ROOT).replace("\\", "/"),
            "raw_payload_root_gitignored": True,
            "tracked_summary_contains_secrets": False,
            "tracked_summary_contains_request_urls": False,
            "tracked_summary_contains_raw_payload_rows": False,
        },
        "gate_flags": {
            "provider_selected": False,
            "binding_or_parser_built": False,
            "total_return_calculation_performed": False,
            "market_diagnostic_track_wired": False,
            "corporate_action_reconciliation_claimed": False,
            "private_state_written": False,
            "datahub_consumed": False,
            "production_or_ship_gate_claimed": False,
            "sr_provider_001_closed": False,
            "a_share_crossing_performed": False,
        },
    }
    _write_summary_validated(summary, [massive_env.value])
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark-ETF (SPY/QQQ/IWB/VTI) Massive dividend coverage probe")
    parser.add_argument("--confirm-user-authorization", action="store_true")
    parser.add_argument("--dry-run-env", action="store_true", help="check env + gitignore + plan; NO network")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.dry_run_env:
        env_ok = bool(__import__("os").environ.get("MASSIVE_API_KEY"))
        print(f"MASSIVE_API_KEY present: {env_ok}")
        print(f"raw root gitignored: {_provider_samples_gitignored()}")
        print(f"planned calls: {len(BENCHMARK_ETF_SYMBOLS) * len(ENDPOINT_FAMILY_ALLOWLIST)} (max {MAX_TOTAL_ENDPOINT_CALLS})")
        print(f"families: {ENDPOINT_FAMILY_ALLOWLIST}; symbols: {BENCHMARK_ETF_SYMBOLS}")
        return 0
    try:
        summary = run_probe(confirm_user_authorization=args.confirm_user_authorization)
    except BenchmarkEtfDividendCoverageProbeError as exc:
        print(f"ERROR: {exc}")
        return 2
    findings = summary["coverage_findings"]
    print(f"probe complete: {summary['scope']['actual_total_endpoint_calls']} calls")
    print(f"  verdict: {findings['benchmark_dividend_source_viable']} "
          f"({findings['covered_symbol_count']}/{len(BENCHMARK_ETF_SYMBOLS)} covered)")
    for result in summary["symbol_results"]:
        print(f"  {result['symbol']}: {result['coverage_verdict']} "
              f"(status={result['http_status']} rows={result['row_count']} "
              f"matched={result['rows_matching_queried_ticker']} fields_ok={result['required_field_names_present']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
