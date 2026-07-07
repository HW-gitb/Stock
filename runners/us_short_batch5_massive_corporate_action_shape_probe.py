"""US-short batch5 Massive corporate-action (splits/dividends) RESPONSE-SHAPE PROBE — gated small sample.

Authorization: user_chat_20260707_massive_corporate_action_shape_probe  (SR-PROVIDER-001, this run only)
Design: docs/us_short_batch5_massive_quota_access_bounded_probe_packet_20260706.json pins the endpoint
        families `GET /stocks/v1/splits` + `GET /stocks/v1/dividends`; register
        `R-USSHORT-BATCH5-MOMENTUM-TOPK-NARROWING-MISSING` (Step 3 = offload the funnel's per-target
        split/dividend fetches from FMP -> Massive so FMP stays under its 250/day free grade cap at K=200).

PURPOSE — feasibility/shape ONLY, NOT a builder. Step 3's Massive split/dividend binding must be built on
the REAL response shape (field names / event-count container / date fields), not a guessed one (memory
lesson 15: read the probed raw before writing a binding). This probe fetches a bounded 2-ticker x 2-family
Massive sample, stores the raw under gitignored provider_samples/, and writes a tracked diagnostic summary
that records ONLY status classes + response-shape key names + counts — NO secrets, NO request URLs, NO raw
payload rows/values. It selects no provider, builds no binding/parser, writes no private state, consumes no
DataHub, and claims no production/ship-gate/reconciliation — SR-PROVIDER-001 stays open and every gate flag
in the summary is pinned closed.

Endpoint-family allowlist (fail-closed): splits, dividends. Anything else aborts before network.

Outputs (research-only):
  - Gitignored raw  -> provider_samples/us_short_batch5_massive_corporate_action_shape_probe_20260707/raw/
  - Tracked summary -> docs/us_short_batch5_massive_corporate_action_shape_probe_summary_20260707.json
                       (schema-validated + secret-scanned BEFORE the atomic write, so a schema-invalid or
                       secret/url/raw-bearing summary is never written)

Usage:
  python runners/us_short_batch5_massive_corporate_action_shape_probe.py --dry-run-env
  python runners/us_short_batch5_massive_corporate_action_shape_probe.py --confirm-user-authorization
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


AUTHORIZATION_REF = "user_chat_20260707_massive_corporate_action_shape_probe"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_massive_corporate_action_shape_probe_summary_20260707.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_massive_corporate_action_shape_probe_summary.schema.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_massive_corporate_action_shape_probe_20260707")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"

EXPECTED_SYMBOLS = ("AAPL", "MSFT")
# The pinned Massive endpoint families (from the quota/access probe packet's public-docs review). A 404/403 here
# is a REAL finding (the account/tier may gate it), which is exactly what this probe exists to record.
ENDPOINT_FAMILY_ALLOWLIST = ("splits", "dividends")
MASSIVE_SPLITS_URL = "https://api.massive.com/stocks/v1/splits?ticker={ticker}&limit=10&apiKey={key}"
MASSIVE_DIVIDENDS_URL = "https://api.massive.com/stocks/v1/dividends?ticker={ticker}&limit=10&apiKey={key}"
MAX_TOTAL_ENDPOINT_CALLS = 6  # 2 symbols x 2 families = 4; headroom to 6


class MassiveCorporateActionShapeProbeError(RuntimeError):
    """The Massive corporate-action shape probe cannot run or record safely."""


def _url_for(family: str, ticker: str, key: str) -> str:
    if family == "splits":
        return MASSIVE_SPLITS_URL.format(ticker=ticker, key=key)
    if family == "dividends":
        return MASSIVE_DIVIDENDS_URL.format(ticker=ticker, key=key)
    raise MassiveCorporateActionShapeProbeError(f"endpoint family outside allowlist: {family!r}")


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
        for key in ("results", "data", "historical", "splits", "dividends"):
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


def _validate_summary_schema(summary: dict[str, Any]) -> None:
    from jsonschema import Draft7Validator

    schema = json.loads(SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft7Validator(schema).iter_errors(summary), key=lambda e: e.path)
    if errors:
        raise MassiveCorporateActionShapeProbeError(
            f"probe summary failed schema validation: {errors[0].message}"
        )


def _scan_summary_safe(text: str, sensitive_values: list[str]) -> None:
    lower = text.lower()
    for fragment in ("apikey=", "api.massive.com", "http://", "https://", '"payload"', "\"raw_payload\""):
        if fragment in lower:
            raise MassiveCorporateActionShapeProbeError(
                f"probe summary contains a forbidden fragment: {fragment}"
            )
    for value in sensitive_values:
        if value and value in text:
            raise MassiveCorporateActionShapeProbeError("probe summary contains a sensitive environment value")


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
    generated_at: str = "2026-07-07T00:00:00+00:00",
) -> dict[str, Any]:
    if not confirm_user_authorization:
        raise MassiveCorporateActionShapeProbeError(
            "Massive corporate-action shape probe requires explicit per-execution user authorization"
        )
    if not _provider_samples_gitignored():
        raise MassiveCorporateActionShapeProbeError(
            f"raw sample root is not confirmed gitignored: {RAW_SAMPLE_REL_ROOT}"
        )
    massive_env = sample_validation.read_required_env("MASSIVE_API_KEY")
    client = client or sample_validation.JsonHttpClient()
    headers = {"User-Agent": "StockSystem/0.1 us-short-batch5-massive-corporate-action-shape-probe"}

    records: list[sample_validation.FetchRecord] = []
    endpoint_summaries: list[dict[str, Any]] = []
    for symbol in EXPECTED_SYMBOLS:
        for family in ENDPOINT_FAMILY_ALLOWLIST:
            if family not in ENDPOINT_FAMILY_ALLOWLIST:  # defense-in-depth: never fetch off the allowlist
                raise MassiveCorporateActionShapeProbeError(f"endpoint family outside allowlist: {family!r}")
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
            endpoint_summaries.append(
                {
                    "symbol": symbol,
                    "endpoint_family": family,
                    "http_status": record.http_status,
                    "ok": bool(record.ok),
                    "error_type": record.error_type,
                    "raw_sample_ref": record.raw_sample_ref,
                    "response_shape": _shape_of(record.payload) if record.ok else None,
                }
            )

    by_family = {family: [s for s in endpoint_summaries if s["endpoint_family"] == family] for family in ENDPOINT_FAMILY_ALLOWLIST}
    summary = {
        "scope": {
            "probe": "massive_corporate_action_shape",
            "authorization_ref": AUTHORIZATION_REF,
            "generated_at": generated_at,
            "purpose": "feasibility/shape only; not a builder",
            "endpoint_family_allowlist": list(ENDPOINT_FAMILY_ALLOWLIST),
            "symbols": list(EXPECTED_SYMBOLS),
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "actual_total_endpoint_calls": len(records),
        },
        "endpoint_results": endpoint_summaries,
        "shape_findings": {
            family: {
                "any_ok": any(s["ok"] for s in by_family[family]),
                "http_status_classes": sorted({s["http_status"] for s in by_family[family]}),
                "event_item_key_names": sorted(
                    {
                        key
                        for s in by_family[family]
                        if s["response_shape"]
                        for key in s["response_shape"]["event_item_key_names"]
                    }
                ),
            }
            for family in ENDPOINT_FAMILY_ALLOWLIST
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
            "corporate_action_reconciliation_claimed": False,
            "return_or_adjustment_calculation_performed": False,
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
    parser = argparse.ArgumentParser(description="Massive corporate-action (splits/dividends) shape probe")
    parser.add_argument("--confirm-user-authorization", action="store_true")
    parser.add_argument("--dry-run-env", action="store_true", help="check env + gitignore + plan; NO network")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.dry_run_env:
        env_ok = bool(__import__("os").environ.get("MASSIVE_API_KEY"))
        print(f"MASSIVE_API_KEY present: {env_ok}")
        print(f"raw root gitignored: {_provider_samples_gitignored()}")
        print(f"planned calls: {len(EXPECTED_SYMBOLS) * len(ENDPOINT_FAMILY_ALLOWLIST)} (max {MAX_TOTAL_ENDPOINT_CALLS})")
        print(f"families: {ENDPOINT_FAMILY_ALLOWLIST}; symbols: {EXPECTED_SYMBOLS}")
        return 0
    try:
        summary = run_probe(confirm_user_authorization=args.confirm_user_authorization)
    except MassiveCorporateActionShapeProbeError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(f"probe complete: {summary['scope']['actual_total_endpoint_calls']} calls")
    for family, finding in summary["shape_findings"].items():
        print(f"  {family}: any_ok={finding['any_ok']} status={finding['http_status_classes']} keys={finding['event_item_key_names']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
