"""Bounded source probe for v14.2 M1's undefined "涨停指数".

Row 14 of the A-short queue is blocked, and row 16 (the v14.2 market-regime
state machine) is blocked behind it, on one unanswered question: three of the
four M1 regimes key off a quantity the frozen spec calls 涨停指数 and never
defines -- no vendor, no index code, no construction method, no unit.  Nobody
has actually looked; the V14.3 design merely routed around it.

This runner looks.  It enumerates the index universes the account can reach
and reports which listed indices carry a limit-up-sentiment name, then, for
any candidate found, whether a daily series is retrievable and how far back it
goes.  Reaching a surface is evidence of availability only; it authorizes no
wiring, no regime classification and no consumer.

The probe is deliberately outside EGS and the weekly pipeline.  Vendor rows
stay under the gitignored ``provider_samples/`` root.  The tracked summary
carries shapes, counts and -- because a probe that cannot name what it found
is useless -- the code and name of matched candidates.  Those are public
reference identifiers, never quotes, balances or any market observation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from engine.a_short_tushare_client import init_tushare_pro


PROBE_DATE = "20260805"
CALL_BUDGET = 20
# A single ``index_basic`` call returns at most this many rows.  Observed, not
# assumed: the CSI universe returned exactly 8000 on the first pass and 863
# more at offset=8000.
INDEX_BASIC_PAGE_SIZE = 8000
RAW_ROOT = Path(f"provider_samples/a_short_limit_up_index_source_probe_{PROBE_DATE}")
SUMMARY_PATH = Path(f"docs/a_short_limit_up_index_source_probe_summary_{PROBE_DATE}.json")

# ``index_basic`` partitions the listed universe by publisher.  Probing every
# partition is what makes a negative result mean "not published anywhere we can
# reach" rather than "not in the one place I happened to look".
INDEX_BASIC_MARKETS = ("SSE", "SZSE", "CSI", "SW", "MSCI", "OTH", "CICC")

# 同花顺 concept boards are the only place a 昨日涨停-style index is publicly
# known to live, and they sit behind a separate entitlement.  Probed once; a
# permission error is itself a usable answer.
THS_INDEX_SPEC = {"endpoint": "ths_index", "parameters": {}}

# The project's own HiThink surface.  ``cn_concept`` is the taxonomy L3
# already consumes; the rest are probed so a miss means "not in any taxonomy
# this account can reach", not "not in the one I happened to ask for".
HITHINK_CATALOG_PATH_PREFIX = "/api/a-share-index/catalog/ths-index-list?tag="
HITHINK_CATALOG_TAGS = ("cn_concept", "cn_industry", "cn_region", "cn_style",
                        "cn_special", "cn_tech", "")

# A name carrying any of these is a candidate for what the spec meant.  Kept
# deliberately wide: a false positive costs one line of reading, a false
# negative costs the whole decision.
NAME_MARKERS = ("涨停", "跌停", "打板", "连板", "首板", "昨日涨停", "涨跌停")

# Only used when a candidate is found -- how deep is its history?
HISTORY_PROBE_WINDOWS = (
    {"label": "recent", "start_date": "20260720", "end_date": "20260804"},
    {"label": "about_three_years_back", "start_date": "20230731", "end_date": "20230804"},
)

_NAME_COLUMNS = ("name", "index_name", "fullname", "ts_name")
_CODE_COLUMNS = ("ts_code", "code", "index_code")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str, allow_nan=False),
        encoding="utf-8",
    )


def _sanitize_nonfinite(value: Any) -> Any:
    """Map vendor NaN/Inf to null for the raw file only.

    Vendor reference rows legitimately carry NaN for "no value" (an index with
    no expiry date, say).  The summary keeps ``allow_nan=False`` as a real
    guard against non-finite values we computed ourselves; a raw vendor dump
    must not be blocked by the vendor's own empties.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _sanitize_nonfinite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_nonfinite(item) for item in value]
    return value


def _raw_json_value(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return {"kind": "dataframe",
                "rows": _sanitize_nonfinite(value.to_dict(orient="records"))}
    if isinstance(value, pd.Series):
        return {"kind": "series", "values": value.to_dict()}
    if isinstance(value, dict):
        return value
    if isinstance(value, (list, tuple)):
        return list(value)
    return {"kind": type(value).__name__}


def _shape(value: Any) -> dict[str, Any]:
    """Columns, counts and per-column emptiness only -- never a market value."""
    if isinstance(value, pd.DataFrame):
        columns = [str(column) for column in value.columns]
        return {
            "kind": "dataframe",
            "row_count": int(len(value)),
            "columns": sorted(columns),
            "column_dtypes": {name: str(value[name].dtype) for name in columns},
            "all_null_columns": sorted(
                name for name in columns if bool(value[name].isna().all())
            ),
        }
    if isinstance(value, pd.Series):
        return {"kind": "series", "row_count": int(len(value)),
                "columns": sorted(str(index) for index in value.index),
                "column_dtypes": {}, "all_null_columns": []}
    if isinstance(value, dict):
        return {"kind": "object", "row_count": 1, "columns": sorted(str(k) for k in value),
                "column_dtypes": {}, "all_null_columns": []}
    if isinstance(value, (list, tuple)):
        keys = {str(key) for item in value if isinstance(item, dict) for key in item}
        return {"kind": "list", "row_count": len(value), "columns": sorted(keys),
                "column_dtypes": {}, "all_null_columns": []}
    return {"kind": type(value).__name__, "row_count": 0 if value is None else 1,
            "columns": [], "column_dtypes": {}, "all_null_columns": []}


def _error_category(exc: Exception) -> str:
    """Four distinguishable failure classes; collapsing them would defeat the probe."""
    message = str(exc).casefold()
    if any(m in message for m in ("权限", "积分", "permission", "entitlement", "access denied")):
        return "permission_or_entitlement"
    if any(m in message for m in ("token", "auth", "认证", "鉴权")):
        return "authentication"
    if any(m in message for m in ("每分钟", "频率", "rate", "too many", "limit")):
        return "rate_limited"
    if any(m in message for m in ("接口", "api name", "parameter", "参数", "not found", "不存在")):
        return "endpoint_or_parameter"
    return "provider_or_undetermined"


def _match_candidates(frame: Any, source: str) -> list[dict[str, str]]:
    """Return code+name of rows whose name carries a limit-up-sentiment marker."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    name_column = next((c for c in _NAME_COLUMNS if c in frame.columns), None)
    if name_column is None:
        return []
    code_column = next((c for c in _CODE_COLUMNS if c in frame.columns), None)
    matched: list[dict[str, str]] = []
    for _, row in frame.iterrows():
        name = row.get(name_column)
        if not isinstance(name, str):
            continue
        hits = [marker for marker in NAME_MARKERS if marker in name]
        if not hits:
            continue
        matched.append({
            "source": source,
            "code": str(row.get(code_column)) if code_column else "",
            "name": name,
            "matched_markers": hits,
        })
    return matched


def probe_hithink_catalog(requester: Any = None, api_key: str | None = None) -> dict[str, Any]:
    """Search the project's own HiThink (同花顺) board catalog for a limit-up board.

    Two facts decide this leg, and the second is the harder one.  First, whether
    any reachable taxonomy names such a board.  Second -- established from the
    client module rather than a call -- that this surface publishes a catalog
    and its constituents and nothing else: there is no quote endpoint, so even
    a board that existed would yield member stocks, never the index level that
    "涨停指数跌>3%" is a statement about.
    """
    from engine import a_short_hithink_l3 as hithink

    try:
        key = hithink._require_api_key(api_key)
    except Exception as exc:
        return {"status": "not_configured", "error_class": type(exc).__name__,
                "tags_reachable": [], "boards_searched": 0, "candidates": []}

    request_json = requester or hithink._default_requester
    headers = {"X-api-key": key}
    catalog_base = hithink.API_BASE_URL + HITHINK_CATALOG_PATH_PREFIX
    per_tag: dict[str, Any] = {}
    matched: list[dict[str, str]] = []
    for tag in HITHINK_CATALOG_TAGS:
        try:
            payload = request_json(catalog_base + tag, headers)
            rows = hithink._catalog_rows(hithink._response_items(payload, tag))
        except Exception as exc:
            per_tag[tag] = {"status": "unreachable", "error_class": type(exc).__name__}
            continue
        hits = [
            {"source": f"hithink:{tag or 'default'}", "code": row["code"], "name": row["name"],
             "matched_markers": [m for m in NAME_MARKERS if m in row["name"]]}
            for row in rows if any(m in row["name"] for m in NAME_MARKERS)
        ]
        matched.extend(hits)
        per_tag[tag] = {"status": "ok", "boards": len(rows), "hits": len(hits)}

    reachable = [tag for tag, result in per_tag.items() if result["status"] == "ok"]
    return {
        "status": "searched" if reachable else "no_reachable_taxonomy",
        "tags_probed": list(HITHINK_CATALOG_TAGS),
        "tags_reachable": reachable,
        "per_tag": per_tag,
        "boards_searched": max((per_tag[t].get("boards", 0) for t in reachable), default=0),
        # A statement about the client module, not about any response.  Kinds,
        # not paths: a tracked summary carries no request URL.
        "surface_endpoint_kinds": ["catalog", "constituents"],
        "surface_endpoint_count": 2,
        "publishes_index_level_or_return": False,
        "why_that_matters": (
            "the v14.2 predicate is a statement about an index's daily change; a "
            "catalog plus constituents can only yield membership"
        ),
        "candidates": matched,
    }


def run_probe(pro_client: Any, raw_root: Path = RAW_ROOT,
              hithink_probe: Any = None) -> dict[str, Any]:
    """Run a budgeted set of read-only index-reference calls against an injected client.

    ``hithink_probe`` is injectable for the same reason ``pro_client`` is: a
    unit test must never reach a vendor.
    """
    raw_root = Path(raw_root)
    results: list[dict[str, Any]] = []
    raw_by_label: dict[str, Any] = {}
    candidates: list[dict[str, str]] = []
    calls = 0

    def _call(label: str, endpoint: str, parameters: dict[str, Any]) -> tuple[dict[str, Any], Any]:
        nonlocal calls
        record: dict[str, Any] = {"label": label, "endpoint": endpoint,
                                  "parameters": dict(parameters)}
        if calls >= CALL_BUDGET:
            record["status"] = "budget_exhausted"
            results.append(record)
            return record, None
        method = getattr(pro_client, endpoint, None)
        if not callable(method):
            record["status"] = "sdk_method_missing"
            results.append(record)
            return record, None
        calls += 1
        try:
            payload = method(**parameters)
            raw_by_label[label] = _raw_json_value(payload)
            record.update({"status": "ok", "shape": _shape(payload)})
            results.append(record)
            return record, payload
        except Exception as exc:  # No vendor message, URL, body or token reaches the summary.
            record.update({"status": "error", "error_class": type(exc).__name__,
                           "error_category": _error_category(exc)})
            results.append(record)
            return record, None

    # Paginate.  A single ``index_basic`` call is capped at PAGE_SIZE rows, and
    # the CSI universe exceeds it -- taking the first page as the whole universe
    # is exactly the truncation that made row 22b's first lookback wrong.  A
    # universe only counts as searched once a short page proves it is exhausted.
    universe_coverage: dict[str, dict[str, Any]] = {}
    for market in INDEX_BASIC_MARKETS:
        offset, pages, rows, exhausted = 0, 0, 0, False
        while True:
            label = f"index_basic_{market}" if pages == 0 else f"index_basic_{market}_p{pages}"
            record, payload = _call(
                label, "index_basic",
                {"market": market, "offset": offset, "limit": INDEX_BASIC_PAGE_SIZE},
            )
            if record.get("status") != "ok":
                break
            page_rows = record["shape"]["row_count"]
            pages += 1
            rows += page_rows
            candidates.extend(_match_candidates(payload, f"index_basic:{market}"))
            if page_rows < INDEX_BASIC_PAGE_SIZE:
                exhausted = True
                break
            offset += INDEX_BASIC_PAGE_SIZE
        universe_coverage[market] = {
            "pages": pages, "rows": rows, "exhausted": exhausted,
            "page_size": INDEX_BASIC_PAGE_SIZE,
        }

    _, ths_payload = _call("ths_index", THS_INDEX_SPEC["endpoint"], THS_INDEX_SPEC["parameters"])
    candidates.extend(_match_candidates(ths_payload, "ths_index"))

    # Tushare's ths_index relay is entitlement-gated, but the project holds its
    # own HiThink (同花顺) credential and already uses that surface for L3.
    # Searching only the Tushare side would have declared the one taxonomy most
    # likely to publish a 昨日涨停 board "unseen" while we could in fact see it.
    hithink = (hithink_probe or probe_hithink_catalog)()
    candidates.extend(hithink.pop("candidates", []))

    # Only spend history calls if there is something to spend them on, and only
    # on the first candidate -- depth is a property of the surface, not of each
    # individual board.
    history_reach: dict[str, Any] = {}
    if candidates:
        first = candidates[0]
        endpoint = "ths_daily" if first["source"] == "ths_index" else "index_daily"
        for window in HISTORY_PROBE_WINDOWS:
            record, _ = _call(
                f"history_{window['label']}", endpoint,
                {"ts_code": first["code"],
                 "start_date": window["start_date"], "end_date": window["end_date"]},
            )
            history_reach[window["label"]] = (
                record["shape"]["row_count"] > 0 if record.get("status") == "ok" else None
            )

    for label, raw_payload in raw_by_label.items():
        _write_json(raw_root / f"{label}.json", raw_payload)

    reachable = [r for r in results if r.get("status") == "ok"]
    error_categories = sorted({r["error_category"] for r in results if r.get("error_category")})

    return {
        "schema_name": "a_short_limit_up_index_source_probe_summary",
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": {
            "market": "A-share",
            "purpose": "limit_up_index_source_binding_probe_only",
            "queue_row": 14,
            "question": "does a retrievable published index match v14.2 M1's undefined 涨停指数",
            "downstream_rows_blocked_until_reviewed": ["14_breadth", "16_market_regime"],
            "regime_classified": False,
            "consumer_wired": False,
            "egs_or_weekly_behavior_changed": False,
            "frozen_spec_modified": False,
            "production_or_ship_gate_claimed": False,
            "broker_or_order_action": False,
        },
        "call_budget": {"budget": CALL_BUDGET, "used": calls},
        "name_markers_searched": list(NAME_MARKERS),
        "universes_probed": list(INDEX_BASIC_MARKETS) + ["ths_index", "hithink_catalog"],
        "universes_reachable": sorted(r["label"] for r in reachable),
        "universe_coverage": universe_coverage,
        "universes_fully_searched": sorted(m for m, c in universe_coverage.items() if c["exhausted"]),
        "universes_left_incomplete": sorted(
            m for m, c in universe_coverage.items() if not c["exhausted"]
        ),
        "indices_searched": sum(c["rows"] for c in universe_coverage.values()),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "history_reach": history_reach,
        "hithink_catalog": hithink,
        "error_categories": error_categories,
        "calls": results,
        "raw_root": str(raw_root),
        "raw_root_is_gitignored": True,
        "verdict": (
            "candidates_found" if candidates
            else "no_matching_published_index_reachable"
            if all(c["exhausted"] for c in universe_coverage.values())
            and hithink["status"] == "searched"
            else "negative_but_universe_coverage_incomplete"
        ),
        "NOT_VERIFIED": [
            "whether any candidate is what the v14.2 author meant",
            "taxonomies this account cannot reach on either vendor surface",
            "construction method, unit and point-in-time semantics of any candidate",
            "independent review of this probe",
            "any decision between binding a source and adopting the V14.3 substitute",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", default=str(RAW_ROOT))
    parser.add_argument("--out", default=str(SUMMARY_PATH))
    parser.add_argument("--confirm-fetch-authorized", action="store_true", required=True)
    args = parser.parse_args(argv)

    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for the limit-up index source probe")
    summary = run_probe(init_tushare_pro(token), raw_root=Path(args.raw_root))
    _write_json(Path(args.out), summary)
    print(
        f"[limit-up-index-probe] verdict={summary['verdict']} "
        f"candidates={summary['candidate_count']} "
        f"calls={summary['call_budget']['used']}/{summary['call_budget']['budget']} "
        f"reachable={len(summary['universes_reachable'])}/{len(summary['universes_probed'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
