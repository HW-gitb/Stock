from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path


def _merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def write_content_bound_bundle(
    output: Path,
    weekly: dict,
    *,
    receipt_path: Path | None = None,
    markdown: str | None = None,
    published_at: str = "2026-07-10T10:00:00+08:00",
) -> Path:
    """Write a synthetic bundle using the production receipt's byte-binding shape."""
    from runners.a_short_m67_render import render_weekly_markdown
    from runners.a_short_weekly_pipeline import build_weekly_report
    from tests.test_a_short_weekly_pipeline import _weekly

    output.parent.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_path or output.with_suffix("").with_suffix(".receipt.json")
    markdown_path = output.with_suffix(".md")
    lineage = weekly.get("run_lineage") or {}
    price_freshness = lineage.get("price_freshness") or {}
    temporal_origin = lineage.get("temporal_origin") or {}
    as_of = str(weekly.get("as_of") or "")
    run_id = str(lineage.get("run_id") or "")
    candidate_digest = str(lineage.get("candidate_digest") or "")
    decision_as_of = str(weekly.get("decision_as_of") or as_of)
    run_date = str(
        weekly.get("run_date")
        or lineage.get("run_date")
        or price_freshness.get("run_date")
        or temporal_origin.get("run_date")
        or as_of
    )
    price_data_through = str(
        weekly.get("price_data_through")
        or lineage.get("price_data_through")
        or price_freshness.get("price_data_through")
        or temporal_origin.get("price_data_through")
        or as_of
    )
    weekly.setdefault("decision_as_of", decision_as_of)
    weekly.setdefault("run_date", run_date)
    weekly.setdefault("price_data_through", price_data_through)
    supplied = copy.deepcopy(weekly)
    supplied_reports = supplied.pop("reports", [])
    if {"boundary", "effect_contract_ledger", "margin_coverage"}.issubset(supplied):
        prepared = supplied
        prepared["reports"] = supplied_reports
    else:
        base = build_weekly_report(
            [], as_of, published_at, run_lineage=copy.deepcopy(lineage)
        )
        prepared = _merge(base, supplied)
        if supplied_reports:
            template = _weekly()["reports"][0]
            prepared["reports"] = [
                _merge(template, report) for report in supplied_reports
            ]
        else:
            prepared["reports"] = []
    prepared["n_stocks"] = len(prepared["reports"])
    weekly.clear()
    weekly.update(prepared)
    if output.name != "weekly_m67.json" or output.parent.name != as_of:
        raise ValueError("synthetic official bundle must use <as_of>/weekly_m67.json")
    if receipt_path.resolve() != output.with_suffix("").with_suffix(".receipt.json").resolve():
        raise ValueError("synthetic official receipt must be the canonical sibling")
    weekly_bytes = json.dumps(weekly, ensure_ascii=False).encode("utf-8")
    if markdown is None:
        markdown = render_weekly_markdown(weekly)
    markdown_bytes = markdown.encode("utf-8")
    receipt = {
        "schema_name": "a_short_weekly_publish_receipt",
        "schema_version": "1.1.0",
        "as_of": as_of,
        "decision_as_of": decision_as_of,
        "run_date": run_date,
        "price_data_through": price_data_through,
        "run_id": run_id,
        "candidate_digest": candidate_digest,
        "published_at": published_at,
        "account_snapshot": lineage.get("account_snapshot"),
        "stage_status": "complete",
        "outputs": [output.name, markdown_path.name],
        "outputs_digest": {
            output.name: {
                "sha256": hashlib.sha256(weekly_bytes).hexdigest(),
                "byte_length": len(weekly_bytes),
            },
            markdown_path.name: {
                "sha256": hashlib.sha256(markdown_bytes).hexdigest(),
                "byte_length": len(markdown_bytes),
            },
        },
    }
    output.write_bytes(weekly_bytes)
    markdown_path.write_bytes(markdown_bytes)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    return receipt_path
