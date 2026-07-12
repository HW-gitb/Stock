# -*- coding: utf-8 -*-
"""US-short A1 Cut C: private per-ticker decision-diff log for six policy heads.

Consumes the reviewed Cut-A private capture and derives a deterministic balanced-vs-policy diff over the
selection surface that Cut A actually contains: non-selection gates, ranks, and Top15 membership. It does not
replay downstream analysis, actions, sizing, paper outcomes, providers, or ship-gate evidence.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from engine.us_short_forward_policy_heads import SELECTION_POLICY_IDS
from engine.us_short_forward_policy_shadow_stage import (
    ForwardPolicyShadowStageError,
    validate_forward_shadow_selection_record,
)


ROOT = Path(__file__).resolve().parent.parent
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_decision_diff_summary.schema.json"
BOUNDARY = {
    "track": "comparison_non_production",
    "evidence_level": "shadow_decision_diff_only",
    "shadow_counts_ship_gate": False,
    "full_size_ship_gate_allowed": False,
    "provider_calls_added": False,
    "broker_or_order_automation_allowed": False,
    "changes_primary_selection": False,
}
UNAVAILABLE = {
    "action_change": "not_available_in_cut_a_capture",
    "size_change": "not_available_in_cut_a_capture",
}
PRIVATE_KEYS = frozenset({
    "schema_name", "schema_version", "decision_date", "price_basis_date", "source_context_sha256",
    "selection_policies", "primary_policy", "diffs_vs_balanced", "unavailable_surfaces", "boundary",
})
SUMMARY_KEYS = frozenset({
    "schema_name", "schema_version", "decision_date", "price_basis_date", "source_context_sha256",
    "selection_policies", "primary_policy", "diff_counts_vs_balanced", "unavailable_surfaces", "boundary",
})
DIFF_BLOCK_KEYS = frozenset({"ticker_diffs", "counts"})
TICKER_DIFF_KEYS = frozenset({
    "ticker", "balanced_rank", "policy_rank", "top15_membership_change", "selection_gate_pass_change",
    "rank_delta", "balanced_selection_bucket", "policy_selection_bucket", "selection_bucket_change",
    "action_change", "size_change",
})
COUNT_KEYS = frozenset({
    "balanced_only_count", "policy_only_count", "overlap_count", "top15_membership_changed_count",
    "rank_changed_count", "selection_bucket_changed_count", "action_changed_count", "size_changed_count",
})


class ForwardPolicyDecisionDiffError(ValueError):
    """The Cut-C decision-diff input or output contract is invalid."""


def _require_capture(capture: object) -> dict:
    try:
        record = validate_forward_shadow_selection_record(capture)
    except ForwardPolicyShadowStageError as exc:
        raise ForwardPolicyDecisionDiffError("Cut-A private capture rejected: %s" % exc) from exc
    if record.get("selection_policies") != list(SELECTION_POLICY_IDS):
        raise ForwardPolicyDecisionDiffError("Cut-C requires the frozen six immediate policy namespace")
    _assert_non_selection_gates_constant(record["selection_decisions"])
    return record


def _non_top15_exclusions(decision: dict) -> list:
    return [
        row for row in decision["exclusion_records"]
        if not (isinstance(row, dict) and row.get("stage") == "top15_selection")
    ]


def _assert_non_selection_gates_constant(decisions: dict) -> None:
    primary = decisions[SELECTION_POLICY_IDS[0]]
    stable_fields = (
        "cheap_eligible", "candidates", "recall_available", "recall_added", "recall_excluded", "holdings",
    )
    for policy_id in SELECTION_POLICY_IDS[1:]:
        decision = decisions[policy_id]
        for field in stable_fields:
            if decision.get(field) != primary.get(field):
                raise ForwardPolicyDecisionDiffError(
                    "policy %r changed non-selection gate field %r" % (policy_id, field))
        if _non_top15_exclusions(decision) != _non_top15_exclusions(primary):
            raise ForwardPolicyDecisionDiffError(
                "policy %r changed non-selection gate exclusion records" % (policy_id,))


def _rank_map(decision: dict) -> dict:
    admitted = decision["admitted"]
    details = decision.get("selection_details")
    buckets = {}
    if isinstance(details, list):
        for row in details:
            if isinstance(row, dict) and row.get("ticker") in admitted:
                buckets[row["ticker"]] = row.get("selection_bucket")
    return {
        ticker: {"rank": index, "selection_bucket": buckets.get(ticker)}
        for index, ticker in enumerate(admitted, start=1)
    }


def _membership_change(balanced_rank, policy_rank) -> str:
    if balanced_rank is not None and policy_rank is not None:
        return "shared_top15"
    if balanced_rank is not None:
        return "balanced_only"
    return "policy_only"


def _gate_change(balanced_rank, policy_rank) -> str:
    if balanced_rank is not None and policy_rank is not None:
        return "unchanged_selected"
    if balanced_rank is not None:
        return "dropped_from_top15"
    return "added_to_top15"


def _ticker_diffs(primary: dict, policy: dict) -> list[dict]:
    balanced = _rank_map(primary)
    selected = _rank_map(policy)
    rows = []
    for ticker in sorted(set(balanced) | set(selected)):
        balanced_info = balanced.get(ticker)
        policy_info = selected.get(ticker)
        balanced_rank = balanced_info["rank"] if balanced_info else None
        policy_rank = policy_info["rank"] if policy_info else None
        rank_delta = None if balanced_rank is None or policy_rank is None else policy_rank - balanced_rank
        balanced_bucket = balanced_info["selection_bucket"] if balanced_info else None
        policy_bucket = policy_info["selection_bucket"] if policy_info else None
        rows.append({
            "ticker": ticker,
            "balanced_rank": balanced_rank,
            "policy_rank": policy_rank,
            "top15_membership_change": _membership_change(balanced_rank, policy_rank),
            "selection_gate_pass_change": _gate_change(balanced_rank, policy_rank),
            "rank_delta": rank_delta,
            "balanced_selection_bucket": balanced_bucket,
            "policy_selection_bucket": policy_bucket,
            "selection_bucket_change": balanced_bucket != policy_bucket,
            "action_change": UNAVAILABLE["action_change"],
            "size_change": UNAVAILABLE["size_change"],
        })
    return rows


def _counts(rows: list[dict]) -> dict:
    balanced_only = sum(1 for row in rows if row["top15_membership_change"] == "balanced_only")
    policy_only = sum(1 for row in rows if row["top15_membership_change"] == "policy_only")
    overlap = sum(1 for row in rows if row["top15_membership_change"] == "shared_top15")
    return {
        "balanced_only_count": balanced_only,
        "policy_only_count": policy_only,
        "overlap_count": overlap,
        "top15_membership_changed_count": balanced_only + policy_only,
        "rank_changed_count": sum(1 for row in rows if row["rank_delta"] not in (None, 0)),
        "selection_bucket_changed_count": sum(1 for row in rows if row["selection_bucket_change"] is True),
        "action_changed_count": 0,
        "size_changed_count": 0,
    }


def build_forward_policy_decision_diff_log(capture: object) -> dict:
    """Return private ticker-bearing Cut-C diff plus a de-identified counts summary."""
    record = _require_capture(capture)
    decisions = record["selection_decisions"]
    primary_policy = SELECTION_POLICY_IDS[0]
    diffs = {}
    summary_counts = {}
    for policy_id in SELECTION_POLICY_IDS[1:]:
        rows = _ticker_diffs(decisions[primary_policy], decisions[policy_id])
        counts = _counts(rows)
        diffs[policy_id] = {"ticker_diffs": rows, "counts": counts}
        summary_counts[policy_id] = dict(counts)
    private = {
        "schema_name": "us_short_forward_policy_decision_diff_log",
        "schema_version": "1.0.0",
        "decision_date": record["decision_date"],
        "price_basis_date": record["price_basis_date"],
        "source_context_sha256": record["source_context_sha256"],
        "selection_policies": list(SELECTION_POLICY_IDS),
        "primary_policy": primary_policy,
        "diffs_vs_balanced": diffs,
        "unavailable_surfaces": dict(UNAVAILABLE),
        "boundary": dict(BOUNDARY),
    }
    summary = {
        "schema_name": "us_short_forward_policy_decision_diff_summary",
        "schema_version": "1.0.0",
        "decision_date": record["decision_date"],
        "price_basis_date": record["price_basis_date"],
        "source_context_sha256": record["source_context_sha256"],
        "selection_policies": list(SELECTION_POLICY_IDS),
        "primary_policy": primary_policy,
        "diff_counts_vs_balanced": summary_counts,
        "unavailable_surfaces": dict(UNAVAILABLE),
        "boundary": dict(BOUNDARY),
    }
    validate_forward_policy_decision_diff_log(private)
    validate_forward_policy_decision_diff_summary(summary)
    return {"private": private, "summary": summary}


def validate_forward_policy_decision_diff_log(log: object) -> None:
    """Validate the ticker-bearing private Cut-C diff and rederive all counts."""
    if not isinstance(log, dict) or set(log) != PRIVATE_KEYS:
        raise ForwardPolicyDecisionDiffError("decision-diff private log key set drifted")
    _validate_common(log, schema_name="us_short_forward_policy_decision_diff_log")
    diffs = log["diffs_vs_balanced"]
    if not isinstance(diffs, dict) or tuple(diffs) != SELECTION_POLICY_IDS[1:]:
        raise ForwardPolicyDecisionDiffError("decision-diff private log must cover exactly the five shadow policies")
    for policy_id in SELECTION_POLICY_IDS[1:]:
        block = diffs[policy_id]
        if not isinstance(block, dict) or set(block) != DIFF_BLOCK_KEYS:
            raise ForwardPolicyDecisionDiffError("decision-diff block for %r is malformed" % (policy_id,))
        rows = block["ticker_diffs"]
        if not isinstance(rows, list):
            raise ForwardPolicyDecisionDiffError("decision-diff ticker rows for %r must be a list" % (policy_id,))
        _validate_ticker_rows(rows, policy_id=policy_id)
        if block["counts"] != _counts(rows):
            raise ForwardPolicyDecisionDiffError("decision-diff counts for %r are inconsistent with ticker rows" % (policy_id,))


def validate_forward_policy_decision_diff_summary(summary: object) -> None:
    """Validate the de-identified Cut-C counts summary."""
    if not isinstance(summary, dict) or set(summary) != SUMMARY_KEYS:
        raise ForwardPolicyDecisionDiffError("decision-diff summary key set drifted")
    try:
        jsonschema.validate(summary, json.loads(SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8")))
    except jsonschema.ValidationError as exc:
        raise ForwardPolicyDecisionDiffError("decision-diff summary schema rejected: %s" % exc.message) from exc
    _validate_common(summary, schema_name="us_short_forward_policy_decision_diff_summary")
    counts_by_policy = summary["diff_counts_vs_balanced"]
    if not isinstance(counts_by_policy, dict) or tuple(counts_by_policy) != SELECTION_POLICY_IDS[1:]:
        raise ForwardPolicyDecisionDiffError("decision-diff summary must cover exactly the five shadow policies")
    for policy_id, counts in counts_by_policy.items():
        _validate_counts(counts, policy_id=policy_id)


def _validate_common(payload: dict, *, schema_name: str) -> None:
    if payload.get("schema_name") != schema_name or payload.get("schema_version") != "1.0.0":
        raise ForwardPolicyDecisionDiffError("decision-diff identity drifted")
    if payload.get("selection_policies") != list(SELECTION_POLICY_IDS) or payload.get("primary_policy") != SELECTION_POLICY_IDS[0]:
        raise ForwardPolicyDecisionDiffError("decision-diff policy namespace drifted")
    if payload.get("unavailable_surfaces") != UNAVAILABLE:
        raise ForwardPolicyDecisionDiffError("decision-diff action/size unavailable marker drifted")
    if payload.get("boundary") != BOUNDARY:
        raise ForwardPolicyDecisionDiffError("decision-diff boundary drifted")
    digest = payload.get("source_context_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ForwardPolicyDecisionDiffError("decision-diff source digest is invalid")


def _validate_ticker_rows(rows: list, *, policy_id: str) -> None:
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != TICKER_DIFF_KEYS:
            raise ForwardPolicyDecisionDiffError("decision-diff row for %r is malformed" % (policy_id,))
        ticker = row["ticker"]
        if not isinstance(ticker, str) or not ticker or ticker in seen:
            raise ForwardPolicyDecisionDiffError("decision-diff row ticker for %r is invalid" % (policy_id,))
        seen.add(ticker)
        balanced_rank, policy_rank = row["balanced_rank"], row["policy_rank"]
        for rank in (balanced_rank, policy_rank):
            if rank is not None and (not isinstance(rank, int) or isinstance(rank, bool) or rank <= 0):
                raise ForwardPolicyDecisionDiffError("decision-diff rank for %r is invalid" % (policy_id,))
        expected_membership = _membership_change(balanced_rank, policy_rank)
        if row["top15_membership_change"] != expected_membership:
            raise ForwardPolicyDecisionDiffError("decision-diff membership for %r is inconsistent" % (policy_id,))
        if row["selection_gate_pass_change"] != _gate_change(balanced_rank, policy_rank):
            raise ForwardPolicyDecisionDiffError("decision-diff gate-pass marker for %r is inconsistent" % (policy_id,))
        expected_delta = None if balanced_rank is None or policy_rank is None else policy_rank - balanced_rank
        if row["rank_delta"] != expected_delta:
            raise ForwardPolicyDecisionDiffError("decision-diff rank delta for %r is inconsistent" % (policy_id,))
        if row["selection_bucket_change"] != (row["balanced_selection_bucket"] != row["policy_selection_bucket"]):
            raise ForwardPolicyDecisionDiffError("decision-diff bucket marker for %r is inconsistent" % (policy_id,))
        if row["action_change"] != UNAVAILABLE["action_change"] or row["size_change"] != UNAVAILABLE["size_change"]:
            raise ForwardPolicyDecisionDiffError("Cut-A capture cannot support action or size diff claims")


def _validate_counts(counts: object, *, policy_id: str) -> None:
    if not isinstance(counts, dict) or set(counts) != COUNT_KEYS:
        raise ForwardPolicyDecisionDiffError("decision-diff counts for %r are malformed" % (policy_id,))
    for key, value in counts.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ForwardPolicyDecisionDiffError("decision-diff count %s for %r is invalid" % (key, policy_id))
    if counts["action_changed_count"] != 0 or counts["size_changed_count"] != 0:
        raise ForwardPolicyDecisionDiffError("Cut-A capture cannot support nonzero action or size diff counts")
    if counts["top15_membership_changed_count"] != counts["balanced_only_count"] + counts["policy_only_count"]:
        raise ForwardPolicyDecisionDiffError("decision-diff membership counts for %r are inconsistent" % (policy_id,))
