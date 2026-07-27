"""A-short D2 regime-action comparison (pure, comparison-only).

The older V14.3 ledger records a raw regime label and an index return.  This
module adds the missing decision audit: every forward week freezes the raw
V14.2 input, the effective fallback actually used for the baseline, both
comparison-policy epochs, and the two *advisory* exposure actions.  It is a
market-regime proxy only; it cannot change M6.7, sizing, vetoes, or orders.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from statistics import median
from pathlib import Path

import jsonschema

from engine import a_short_evidence_epoch_mode as _epoch_mode

from engine.a_short_regime_classifier import (
    FORWARD_RETURN_BASIS, RAW_REGIMES, STATEFUL_REGIMES, V14_2_REGIMES,
)
from engine.a_short_regime_ledger import is_canonical_date
from engine.a_short_experiment_admission_registry import admission_snapshot


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "a_short_regime_action_comparison_weekly.schema.json"
GOVERNANCE_PATH = ROOT / "presets" / "a_short_regime_action_comparison_governance_20260714.json"
GOVERNANCE_SCHEMA_PATH = ROOT / "schemas" / "a_short_regime_action_comparison_governance.schema.json"
CANDIDATE_EFFECT_SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "a_short_regime_candidate_effect_summary.schema.json"
CANDIDATE_EFFECT_HORIZONS = ("h5", "h10", "h20")
ACTION_RECORD_SCHEMA_VERSION = "1.1.0"
ACTION_FORWARD_ORIGIN_FIELDS = frozenset({
    "decision_as_of", "run_date", "capture_mode", "price_data_through",
    "source_receipt_complete", "price_day_latest_settled",
})


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def governance() -> dict:
    return _load_json(GOVERNANCE_PATH)


def action_for_regime(regime: str) -> dict:
    """Return the frozen comparison-only action for a non-unknown effective regime."""
    actions = governance()["action_matrix"]
    if regime not in actions:
        raise ValueError(f"no frozen comparison action for regime {regime!r}")
    return dict(actions[regime])


def candidate_effect_policy() -> dict:
    """Return the P1 Cut1 policy after schema validation.

    It deliberately references the classifier governance for state-machine parameters.  This file
    owns only candidate eligibility/evidence thresholds, so confirmation-day constants cannot
    drift into a second source of truth.
    """
    gov = governance()
    try:
        jsonschema.validate(gov, _load_json(GOVERNANCE_SCHEMA_PATH))
    except jsonschema.ValidationError as exc:
        raise ValueError(f"candidate-effect governance schema: {exc.message}") from exc
    return dict(gov["candidate_effect_policy"])


def _runtime_policy_source_fingerprint() -> str:
    """Pin semantic result-shaping code, not whole files that contain unrelated prose."""
    from engine import a_short_regime_classifier as classifier
    from engine import a_short_regime_ledger as ledger
    from runners import a_short_regime_comparison_runner as runner
    from runners import forward_tracker

    payload = {
        "module_sources": {
            "action": _epoch_mode.semantic_module_contract(sys.modules[__name__]),
            "runner": _epoch_mode.semantic_module_contract(runner),
            "classifier": _epoch_mode.semantic_module_contract(classifier),
            "ledger": _epoch_mode.semantic_module_contract(ledger),
            "forward_tracker": _epoch_mode.semantic_module_contract(forward_tracker),
        },
        "constants": {"forward_return_basis": FORWARD_RETURN_BASIS, "raw_regimes": RAW_REGIMES,
                      "stateful_regimes": STATEFUL_REGIMES, "v14_2_regimes": V14_2_REGIMES},
        "json_contracts": {
            "runtime_policy": _load_json(ROOT / "presets" / "a_short_m67_runtime_policy_20260715.json"),
            "weekly_schema": _load_json(ROOT / "schemas" / "a_short_weekly_report.schema.json"),
            "effect_contract": _load_json(ROOT / "schemas" / "a_short_m67_effect_contract.json"),
            "governance_schema": _load_json(GOVERNANCE_SCHEMA_PATH),
            "candidate_summary_schema": _load_json(CANDIDATE_EFFECT_SUMMARY_SCHEMA_PATH),
        },
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def candidate_effect_policy_fingerprint() -> str:
    """Fingerprint every result-shaping P1 Cut1 policy component, not just its version label.

    Pre-freeze this is a stable constant (see ``engine/a_short_evidence_epoch_mode``);
    the real binding below hashes 13 whole files and invalidated the ledger on
    edits unrelated to this comparison.
    """
    return _epoch_mode.fingerprint_or_pre_freeze(
        "p1_regime_candidate_effect", _real_candidate_effect_policy_fingerprint)


def _real_candidate_effect_policy_fingerprint() -> str:
    gov = governance()
    payload = {
        "candidate_effect_policy": candidate_effect_policy(),
        "action_matrix": gov["action_matrix"],
        "boundary": gov["boundary"],
        "runtime_source_fingerprint": _runtime_policy_source_fingerprint(),
        "admission_binding": admission_snapshot("p1_regime_action_proxy"),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def m67_provenance(path: str | Path, *, as_of: str) -> dict:
    """Read only a digest and candidate build count from M6.7; never persist rows/account data."""
    raw = Path(path).read_bytes()
    doc = json.loads(raw.decode("utf-8"))
    source_as_of = str((doc or {}).get("as_of"))
    if not isinstance(doc, dict) or not is_canonical_date(source_as_of) or not is_canonical_date(str(as_of)):
        raise ValueError("M6.7 source and settled regime date must both be real dates")
    # A canonical Monday run legally uses Friday's settled regime row.  More than a week apart is a
    # stale or wrong source, not a legitimate intraday settlement seam.
    from datetime import datetime
    if abs((datetime.strptime(source_as_of, "%Y%m%d") - datetime.strptime(str(as_of), "%Y%m%d")).days) > 7:
        raise ValueError("M6.7 source is more than seven calendar days from the settled regime date")
    reports = doc.get("reports")
    if not isinstance(reports, list):
        raise ValueError("M6.7 source missing reports list")
    builds = 0
    for report in reports:
        table = ((report or {}).get("m67") or {}).get("table") or {}
        source = str((report or {}).get("row_source") or "egs_candidate")
        if table.get("操作") == "建仓" and source in {"egs_candidate", "egs_candidate_with_position"}:
            builds += 1
    return {
        "source_schema_name": str(doc.get("schema_name") or "a_short_weekly_report"),
        "source_as_of": source_as_of,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "candidate_build_count": builds,
    }


def _returns_from_regime_record(record: dict) -> tuple[dict, list[str], bool]:
    returns = dict(record.get("forward_returns") or {})
    pending = list(record.get("forward_returns_pending") or [])
    if set(returns) != {"h1", "h3", "h5", "h10"}:
        raise ValueError("regime record has invalid forward return horizons")
    expected_pending = [h for h in ("h1", "h3", "h5", "h10") if returns[h] is None]
    if pending != expected_pending:
        raise ValueError("regime record forward return pending state is inconsistent")
    return returns, pending, not pending


def build_action_record(*, regime_record: dict, raw_v14_2_regime: str,
                        effective_v14_2_regime: str, m67_source: dict,
                        forward_origin: dict) -> dict:
    """Build and validate one immutable comparison decision record.

    ``raw_v14_2_regime`` may be unknown, but the effective label must be the
    fail-closed production fallback used for the baseline.  This separation is
    why old unknown-only ledger rows are never silently mixed into D2 results.
    """
    if raw_v14_2_regime not in V14_2_REGIMES:
        raise ValueError("raw V14.2 regime is invalid")
    if effective_v14_2_regime not in RAW_REGIMES:
        raise ValueError("effective V14.2 regime must be a concrete fail-closed label")
    if not isinstance(forward_origin, dict):
        raise ValueError("forward origin must be an object")
    missing_origin_fields = sorted(ACTION_FORWARD_ORIGIN_FIELDS - set(forward_origin))
    if missing_origin_fields:
        raise ValueError(f"forward origin missing required fields: {missing_origin_fields}")
    decision_as_of = str(forward_origin.get("decision_as_of"))
    run_date = str(forward_origin.get("run_date"))
    if not is_canonical_date(decision_as_of) or not is_canonical_date(run_date):
        raise ValueError("forward origin requires real decision_as_of and run_date")
    capture_mode = forward_origin.get("capture_mode")
    if capture_mode not in {"live", "historical_replay"}:
        raise ValueError("forward origin capture_mode is invalid")
    price_data_through = str(forward_origin.get("price_data_through"))
    if not is_canonical_date(price_data_through) or price_data_through > decision_as_of:
        raise ValueError("forward origin price_data_through must be a settled date <= decision_as_of")
    source_receipt_complete = forward_origin.get("source_receipt_complete")
    price_day_latest_settled = forward_origin.get("price_day_latest_settled")
    if not isinstance(source_receipt_complete, bool) or not isinstance(price_day_latest_settled, bool):
        raise ValueError("forward origin evidence fields must be booleans")
    # A prospective canonical decision (Sunday->Monday) is live evidence when
    # the source receipt and the independently bound settled-price clock are complete.
    forward_eligible = (
        capture_mode == "live"
        and decision_as_of >= run_date
        and source_receipt_complete
        and price_day_latest_settled
    )
    candidate = str(regime_record.get("v14_3_raw_regime"))
    if candidate not in RAW_REGIMES:
        raise ValueError("regime record missing valid V14.3 raw label")
    as_of = str(regime_record.get("as_of"))
    if not is_canonical_date(as_of):
        raise ValueError("regime record as_of is invalid")
    returns, pending, complete = _returns_from_regime_record(regime_record)
    gov = governance()
    baseline_action = action_for_regime(effective_v14_2_regime)
    candidate_action = action_for_regime(candidate)
    record = {
        "schema_name": "a_short_regime_action_comparison_weekly",
        "schema_version": ACTION_RECORD_SCHEMA_VERSION,
        "as_of": as_of,
        "raw_v14_2_regime": raw_v14_2_regime,
        "effective_v14_2_regime": effective_v14_2_regime,
        "baseline_policy_id": gov["baseline_policy_id"],
        "baseline_policy_epoch": gov["baseline_policy_epoch"],
        "candidate_v14_3_raw_regime": candidate,
        "candidate_v14_3_fired_rule": str(regime_record.get("v14_3_fired_rule")),
        "candidate_policy_id": gov["candidate_policy_id"],
        "candidate_policy_epoch": gov["candidate_policy_epoch"],
        "baseline_action": baseline_action,
        "candidate_action": candidate_action,
        "action_diverges": baseline_action != candidate_action,
        "m67_provenance": dict(m67_source),
        "forward_origin": {
            "decision_as_of": decision_as_of,
            "run_date": run_date,
            "capture_mode": capture_mode,
            "price_data_through": price_data_through,
            "source_receipt_complete": source_receipt_complete,
            "price_day_latest_settled": price_day_latest_settled,
        },
        "forward_eligible": forward_eligible,
        "forward_market_returns": returns,
        "forward_returns_pending": pending,
        "backfill_complete": complete,
        "forward_return_basis": dict(FORWARD_RETURN_BASIS),
        "boundary": dict(gov["boundary"]),
    }
    validate_action_record(record)
    return record


def validate_action_record(record: dict) -> None:
    """Schema plus relations JSON Schema cannot express."""
    schema = _load_json(SCHEMA_PATH)
    try:
        jsonschema.validate(record, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"action comparison schema: {exc.message}") from exc
    if not is_canonical_date(str(record.get("as_of"))):
        raise ValueError("action comparison as_of is not a real date")
    origin = record.get("forward_origin") or {}
    decision_as_of = str(origin.get("decision_as_of"))
    run_date = str(origin.get("run_date"))
    if not is_canonical_date(decision_as_of) or not is_canonical_date(run_date):
        raise ValueError("action comparison forward origin is invalid")
    capture_mode = origin.get("capture_mode")
    price_data_through = str(origin.get("price_data_through") or "")
    if capture_mode not in {"live", "historical_replay"} or not is_canonical_date(price_data_through):
        raise ValueError("action comparison forward origin clock is invalid")
    if price_data_through > decision_as_of:
        raise ValueError("action comparison price_data_through is after decision_as_of")
    expected_forward = (
        capture_mode == "live"
        and decision_as_of >= run_date
        and origin.get("source_receipt_complete") is True
        and origin.get("price_day_latest_settled") is True
    )
    if record.get("forward_eligible") != expected_forward:
        raise ValueError("action comparison forward eligibility must be derived from its run origin")
    expected_pending = [h for h in ("h1", "h3", "h5", "h10")
                        if (record.get("forward_market_returns") or {}).get(h) is None]
    if record.get("forward_returns_pending") != expected_pending:
        raise ValueError("action comparison pending horizons must equal null returns")
    if bool(record.get("backfill_complete")) != (not expected_pending):
        raise ValueError("action comparison backfill_complete contradicts pending horizons")
    baseline = record.get("baseline_action")
    candidate = record.get("candidate_action")
    if record.get("action_diverges") != (baseline != candidate):
        raise ValueError("action_diverges contradicts frozen actions")
    if baseline != action_for_regime(record["effective_v14_2_regime"]):
        raise ValueError("baseline action does not match its frozen regime matrix")
    if candidate != action_for_regime(record["candidate_v14_3_raw_regime"]):
        raise ValueError("candidate action does not match its frozen regime matrix")


def migrate_action_record_from_published_m67(record: dict, *, m67_path: str | Path,
                                             receipt_path: str | Path) -> dict:
    """Migrate one pre-clock action row using its hash-bound published M6.7 source.

    This is an explicit one-time data migration, not a runtime legacy fallback.  It refuses
    to invent clock fields, and it verifies the source receipt identity before deriving the
    new forward eligibility.
    """
    if not isinstance(record, dict):
        raise ValueError("action record migration requires an object")
    origin = record.get("forward_origin") or {}
    if ACTION_FORWARD_ORIGIN_FIELDS.issubset(origin):
        migrated = dict(record)
        validate_action_record(migrated)
        return migrated
    m67_file = Path(m67_path)
    receipt_file = Path(receipt_path)
    raw = m67_file.read_bytes()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    expected_sha256 = str((record.get("m67_provenance") or {}).get("source_sha256") or "")
    if source_sha256 != expected_sha256:
        raise ValueError("action migration source SHA does not match m67_provenance")
    m67 = json.loads(raw.decode("utf-8"))
    lineage = m67.get("run_lineage") or {}
    source_as_of = str((record.get("m67_provenance") or {}).get("source_as_of") or "")
    if str(m67.get("as_of") or "") != source_as_of:
        raise ValueError("action migration M6.7 as_of does not match m67_provenance")
    receipt = _load_json(receipt_file)
    if (
        receipt.get("stage_status") != "complete"
        or str(receipt.get("as_of")) != source_as_of
        or receipt.get("run_id") != lineage.get("run_id")
        or receipt.get("candidate_digest") != lineage.get("candidate_digest")
    ):
        raise ValueError("action migration receipt is not bound to the published M6.7 source")
    freshness = lineage.get("price_freshness") or {}
    capture_mode = "live" if str(origin.get("decision_as_of")) >= str(origin.get("run_date")) else "historical_replay"
    price_data_through = str(freshness.get("price_data_through") or "")
    source_receipt_complete = True
    if freshness.get("mode") == "intraday_prior_settled":
        price_day_latest_settled = (
            str(freshness.get("accepted_prior_settled_date") or "") == price_data_through
            and price_data_through < str(origin.get("decision_as_of"))
        )
    elif freshness.get("mode") == "strict_as_of":
        price_day_latest_settled = price_data_through == str(origin.get("decision_as_of"))
    else:
        raise ValueError("action migration M6.7 price freshness mode is unsupported")
    migrated = dict(record)
    migrated["schema_version"] = ACTION_RECORD_SCHEMA_VERSION
    migrated["forward_origin"] = {
        "decision_as_of": str(origin.get("decision_as_of")),
        "run_date": str(origin.get("run_date")),
        "capture_mode": capture_mode,
        "price_data_through": price_data_through,
        "source_receipt_complete": source_receipt_complete,
        "price_day_latest_settled": price_day_latest_settled,
    }
    migrated["forward_eligible"] = (
        capture_mode == "live"
        and migrated["forward_origin"]["decision_as_of"] >= migrated["forward_origin"]["run_date"]
        and source_receipt_complete
        and price_day_latest_settled
    )
    validate_action_record(migrated)
    return migrated


def merge_action_records(existing: list[dict], current: dict) -> list[dict]:
    """Append a new week or require exact immutable rerun equality."""
    validate_action_record(current)
    out = []
    seen = set()
    for row in existing:
        validate_action_record(row)
        key = str(row["as_of"])
        if key in seen:
            raise ValueError(f"duplicate action comparison as_of {key}")
        seen.add(key)
        if key == current["as_of"]:
            if row != current:
                raise ValueError("same-week action comparison conflicts with immutable history")
        else:
            out.append(row)
    out.append(current)
    return sorted(out, key=lambda r: str(r["as_of"]))


def refresh_action_records(existing: list[dict], regime_records: list[dict]) -> list[dict]:
    """Carry audited index-return backfills into the action history without changing a decision."""
    by_date = {str(row.get("as_of")): row for row in regime_records}
    refreshed = []
    for row in existing:
        validate_action_record(row)
        regime = by_date.get(str(row["as_of"]))
        if regime is None:
            raise ValueError("action comparison has no matching regime record")
        rebuilt = build_action_record(
            regime_record=regime,
            raw_v14_2_regime=row["raw_v14_2_regime"],
            effective_v14_2_regime=row["effective_v14_2_regime"],
            m67_source=row["m67_provenance"],
            forward_origin=row["forward_origin"],
        )
        immutable = ("raw_v14_2_regime", "effective_v14_2_regime", "candidate_v14_3_raw_regime",
                     "candidate_v14_3_fired_rule", "baseline_policy_id", "baseline_policy_epoch",
                     "candidate_policy_id", "candidate_policy_epoch", "baseline_action",
                     "candidate_action", "m67_provenance", "forward_origin", "forward_eligible", "boundary")
        if any(rebuilt[k] != row[k] for k in immutable):
            raise ValueError("action comparison immutable classification conflicts with regime history")
        refreshed.append(rebuilt)
    return refreshed


def summarize_action_records(records: list[dict]) -> dict:
    """Summarize only comparable post-D2 rows; unknown legacy records have no place here."""
    for row in records:
        validate_action_record(row)
    forward_records = [r for r in records if r["forward_eligible"]]
    forward_run_dates = [str(r["forward_origin"]["run_date"]) for r in forward_records]
    if len(set(forward_run_dates)) != len(forward_run_dates):
        raise ValueError("action comparison has multiple forward-eligible records from one runner date")
    divergent = [r for r in forward_records if r["action_diverges"]]
    h10 = [r for r in divergent if r["forward_market_returns"]["h10"] is not None]
    favorable = 0
    unfavorable = 0
    for row in h10:
        ret = float(row["forward_market_returns"]["h10"])
        delta = int(row["candidate_action"]["max_exposure_pct"]) - int(row["baseline_action"]["max_exposure_pct"])
        proxy = ret * delta
        if proxy > 0:
            favorable += 1
        elif proxy < 0:
            unfavorable += 1
    gate = governance()["review_gate"]
    ready = (_epoch_mode.evidence_counts_toward_clock("p1_regime_candidate_effect")
             and len(forward_records) >= gate["forward_live_weeks_min"]
             and len(h10) >= gate["divergence_h10_samples_min"])
    if not ready:
        status = "accumulating"
    elif favorable > unfavorable:
        status = "review_candidate_preferred"
    elif unfavorable > favorable:
        status = "review_baseline_preferred"
    else:
        status = "review_inconclusive"
    return {
        "total_forward_weeks": len(forward_records),
        "historical_not_counted": len(records) - len(forward_records),
        "divergent_action_weeks": len(divergent),
        "settled_divergence_h10": len(h10),
        "favorable_exposure_proxy_h10": favorable,
        "unfavorable_exposure_proxy_h10": unfavorable,
        "review_gate": dict(gate),
        "status": status,
        "automatic_production_switch": False,
        "scope": "market_regime_exposure_proxy_not_stock_selection_or_trade_execution",
    }


# ---- P1 Cut1 per-stock candidate-effect comparison (pure; no weekly wiring) -----------------

def candidate_effect_eligibility(candidate: dict) -> tuple[bool, str]:
    """Return whether a public M6.7 candidate row can enter the P1 comparison.

    The cut accepts only a normal EGS candidate with a final ``建仓`` action.  Position, watch,
    veto, and manual-review rows are excluded before any return calculation; no account data is
    consumed or persisted by this pure helper.
    """
    policy = candidate_effect_policy()
    if str(candidate.get("row_source")) != policy["eligible_row_source"]:
        return False, "row_source_not_egs_candidate"
    if str(candidate.get("m67_action")) != policy["eligible_m67_action"]:
        return False, "m67_action_not_build"
    for key, reason in (
        ("is_holding", "holding_excluded"),
        ("is_watch", "watch_excluded"),
        ("is_vetoed", "veto_excluded"),
        ("manual_review", "manual_review_excluded"),
    ):
        if candidate.get(key) is True:
            return False, reason
    return True, "eligible"


def _finite_return_map(values: dict | None, *, field: str) -> dict:
    if not isinstance(values, dict) or set(values) != set(CANDIDATE_EFFECT_HORIZONS):
        raise ValueError(f"{field} must contain exactly {CANDIDATE_EFFECT_HORIZONS}")
    out = {}
    for horizon in CANDIDATE_EFFECT_HORIZONS:
        value = values[horizon]
        if value is None:
            out[horizon] = None
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            out[horizon] = float(value)
        else:
            raise ValueError(f"{field}.{horizon} must be a finite number or null")
    return out


def build_candidate_effect_record(*, candidate: dict, stateful_regime: dict,
                                  forward_returns: dict, evidence_origin: dict) -> dict | None:
    """Build one P1 candidate-effect observation or return ``None`` when it is excluded.

    ``forward_returns`` supplies already-measured net stock returns and CSI1000 returns in percent
    for h5/h10/h20.  The function never reads ``forward_tracker``: Cut2 alone will map those
    values from the existing tracker, read-only.  A forbidden candidate is modeled as cash 0% only
    when its stock return is mature; a missing return remains null rather than being fabricated as
    a 0% outcome.
    """
    eligible, _ = candidate_effect_eligibility(candidate)
    if not eligible:
        return None
    policy = candidate_effect_policy()
    as_of = str(candidate.get("as_of"))
    ts_code = str(candidate.get("ts_code") or "")
    if not is_canonical_date(as_of) or not ts_code:
        raise ValueError("candidate effect requires canonical as_of and non-empty ts_code")
    if str(stateful_regime.get("as_of")) != as_of:
        raise ValueError("candidate effect stateful regime as_of must equal candidate as_of")
    state = stateful_regime.get("stateful_regime")
    state_evaluable = bool(stateful_regime.get("state_evaluable")) and state in STATEFUL_REGIMES
    if not isinstance(evidence_origin, dict):
        raise ValueError("candidate effect evidence_origin must be an object")
    capture_mode = evidence_origin.get("capture_mode")
    if capture_mode not in {"live", "historical_replay"}:
        raise ValueError("candidate effect capture_mode must be live or historical_replay")
    if str(evidence_origin.get("decision_as_of")) != as_of:
        raise ValueError("candidate effect evidence_origin.decision_as_of must equal candidate as_of")

    stock = _finite_return_map(forward_returns.get("stock_net_returns"), field="stock_net_returns")
    benchmark = _finite_return_map(forward_returns.get("csi1000_returns"), field="csi1000_returns")
    forbidden = state_evaluable and action_for_regime(state)["new_build"] == "forbidden"
    baseline_net = dict(stock)
    candidate_net = {}
    for horizon in CANDIDATE_EFFECT_HORIZONS:
        candidate_net[horizon] = (0.0 if forbidden else stock[horizon]) if stock[horizon] is not None else None
    operation_improvement = {
        h: (candidate_net[h] - baseline_net[h] if candidate_net[h] is not None else None)
        for h in CANDIDATE_EFFECT_HORIZONS
    }
    baseline_excess = {
        h: (baseline_net[h] - benchmark[h] if baseline_net[h] is not None and benchmark[h] is not None else None)
        for h in CANDIDATE_EFFECT_HORIZONS
    }
    candidate_excess = {
        h: (candidate_net[h] - benchmark[h] if candidate_net[h] is not None and benchmark[h] is not None else None)
        for h in CANDIDATE_EFFECT_HORIZONS
    }
    return {
        "as_of": as_of,
        "ts_code": ts_code,
        "row_source": policy["eligible_row_source"],
        "m67_action": policy["eligible_m67_action"],
        "stateful_regime": state if state_evaluable else None,
        "state_evaluable": state_evaluable,
        "candidate_new_build_forbidden": forbidden,
        "evidence_origin": {"capture_mode": capture_mode, "decision_as_of": as_of},
        "policy_id": policy["policy_id"],
        "policy_epoch": policy["policy_epoch"],
        "policy_fingerprint": candidate_effect_policy_fingerprint(),
        "admission_binding": admission_snapshot("p1_regime_action_proxy"),
        "baseline_net_returns": baseline_net,
        "candidate_net_returns": candidate_net,
        "csi1000_returns": benchmark,
        "operation_improvement_pp": operation_improvement,
        "baseline_excess_csi1000_pp": baseline_excess,
        "candidate_excess_csi1000_pp": candidate_excess,
        "boundary": {"comparison_only": True, "automatic_production_switch": False},
    }


def _validate_candidate_effect_record(record: dict) -> None:
    policy = candidate_effect_policy()
    if not isinstance(record, dict):
        raise ValueError("candidate effect record must be an object")
    if not is_canonical_date(str(record.get("as_of"))) or not str(record.get("ts_code") or ""):
        raise ValueError("candidate effect record requires canonical as_of and ts_code")
    if record.get("row_source") != policy["eligible_row_source"] or record.get("m67_action") != policy["eligible_m67_action"]:
        raise ValueError("candidate effect record violates frozen candidate eligibility")
    if record.get("policy_id") != policy["policy_id"] or record.get("policy_epoch") != policy["policy_epoch"]:
        raise ValueError("candidate effect record has another policy version")
    if record.get("policy_fingerprint") != candidate_effect_policy_fingerprint():
        raise ValueError("candidate effect record policy fingerprint does not match current policy")
    if record.get("admission_binding") != admission_snapshot("p1_regime_action_proxy"):
        raise ValueError("candidate effect record admission binding does not match current policy")
    if record.get("boundary") != {"comparison_only": True, "automatic_production_switch": False}:
        raise ValueError("candidate effect record is not comparison-only")
    origin = record.get("evidence_origin") or {}
    if origin.get("capture_mode") not in {"live", "historical_replay"} or str(origin.get("decision_as_of")) != record["as_of"]:
        raise ValueError("candidate effect record has invalid evidence origin")
    state = record.get("stateful_regime")
    if record.get("state_evaluable"):
        if state not in STATEFUL_REGIMES:
            raise ValueError("evaluable candidate effect record has invalid stateful regime")
        expected_forbidden = action_for_regime(state)["new_build"] == "forbidden"
        if record.get("candidate_new_build_forbidden") != expected_forbidden:
            raise ValueError("candidate effect forbidden action contradicts stateful regime")
    elif state is not None or record.get("candidate_new_build_forbidden"):
        raise ValueError("non-evaluable candidate effect record must not invent a state or cash action")
    baseline = _finite_return_map(record.get("baseline_net_returns"), field="baseline_net_returns")
    candidate = _finite_return_map(record.get("candidate_net_returns"), field="candidate_net_returns")
    benchmark = _finite_return_map(record.get("csi1000_returns"), field="csi1000_returns")
    improvement = _finite_return_map(record.get("operation_improvement_pp"), field="operation_improvement_pp")
    baseline_excess = _finite_return_map(record.get("baseline_excess_csi1000_pp"), field="baseline_excess_csi1000_pp")
    candidate_excess = _finite_return_map(record.get("candidate_excess_csi1000_pp"), field="candidate_excess_csi1000_pp")
    for horizon in CANDIDATE_EFFECT_HORIZONS:
        expected = candidate[horizon] - baseline[horizon] if candidate[horizon] is not None else None
        if improvement[horizon] != expected:
            raise ValueError("candidate effect operation improvement contradicts returns")
        if record.get("candidate_new_build_forbidden") and baseline[horizon] is not None and candidate[horizon] != 0.0:
            raise ValueError("forbidden candidate must use the documented cash 0% proxy")
        if not record.get("candidate_new_build_forbidden") and candidate[horizon] != baseline[horizon]:
            raise ValueError("allowed or non-evaluable candidate must equal the frozen baseline return")
        expected_baseline_excess = (
            baseline[horizon] - benchmark[horizon]
            if baseline[horizon] is not None and benchmark[horizon] is not None else None
        )
        expected_candidate_excess = (
            candidate[horizon] - benchmark[horizon]
            if candidate[horizon] is not None and benchmark[horizon] is not None else None
        )
        if baseline_excess[horizon] != expected_baseline_excess or candidate_excess[horizon] != expected_candidate_excess:
            raise ValueError("candidate effect CSI1000 excess contradicts net returns")


def _mean_or_none(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_candidate_effect_records(records: list[dict]) -> dict:
    """Summarize P1 records by equal-weighted week, never by pooled individual stocks.

    Missing/immature returns and historical replays remain visible in the progress counters but are
    never coerced to zero or counted toward the forward evidence gate.
    """
    seen_candidate_keys = set()
    for record in records:
        _validate_candidate_effect_record(record)
        key = (record["as_of"], record["ts_code"])
        if key in seen_candidate_keys:
            raise ValueError("candidate-effect duplicate (as_of, ts_code) cannot be counted twice")
        seen_candidate_keys.add(key)
    policy = candidate_effect_policy()
    policy_groups = {(r["policy_id"], r["policy_epoch"], r["policy_fingerprint"]) for r in records}
    if len(policy_groups) > 1:
        raise ValueError("candidate-effect records with different policy versions/fingerprints cannot mix")

    live_records = [r for r in records if r["evidence_origin"]["capture_mode"] == "live"]
    historical_not_counted = len(records) - len(live_records)
    live_weeks = {r["as_of"] for r in live_records}
    divergent_h10: dict[str, list[dict]] = {}
    immature_or_missing = 0
    for record in live_records:
        if not record["state_evaluable"] or not record["candidate_new_build_forbidden"]:
            continue
        if record["operation_improvement_pp"]["h10"] is None:
            immature_or_missing += 1
            continue
        divergent_h10.setdefault(record["as_of"], []).append(record)

    weekly_h10 = []
    weekly_h20 = []
    forbidden_h10_excess = []
    mature_divergence_stocks = 0
    h20_pending_weeks = 0
    for as_of in sorted(divergent_h10):
        group = divergent_h10[as_of]
        h20 = [r["operation_improvement_pp"]["h20"] for r in group]
        if all(value is not None for value in h20):
            h10 = [float(r["operation_improvement_pp"]["h10"]) for r in group]
            weekly_h10.append(sum(h10) / len(h10))
            weekly_h20.append(sum(float(value) for value in h20) / len(h20))
            mature_divergence_stocks += len(group)
            forbidden_h10_excess.extend(
                float(r["baseline_excess_csi1000_pp"]["h10"])
                for r in group if r["baseline_excess_csi1000_pp"]["h10"] is not None
            )
        else:
            h20_pending_weeks += 1
            immature_or_missing += sum(value is None for value in h20)

    mean_h10 = _mean_or_none(weekly_h10)
    median_h10 = float(median(weekly_h10)) if weekly_h10 else None
    favorable_ratio = (
        sum(value > 0 for value in weekly_h10) / len(weekly_h10) if weekly_h10 else None
    )
    mean_h20 = _mean_or_none(weekly_h20)
    # `weekly_h10` and `weekly_h20` are appended in lockstep above (one closed H20-mature
    # cohort feeds every reported statistic), so `len(weekly_h10) == len(weekly_h20)` ALWAYS
    # and the two minimums below are the same predicate while both are frozen at 8:
    # `h20_mature_weeks_min` only bites once it is raised above `divergence_weeks_min`.
    # Both gates are kept explicit so a future governance edit to either one is honoured;
    # `tests/test_a_short_regime_action_comparison.py` pins the equality so nobody "fixes"
    # one counter without the other.  See register
    # R-ASHORT-CANDIDATE-EFFECT-NONMONOTONIC-AND-HEALTH-FALSE-GREEN Optional (c).
    ready = (
        # Pre-freeze evidence is audit-only and must never reach a verdict.
        _epoch_mode.evidence_counts_toward_clock("p1_regime_candidate_effect")
        and len(live_weeks) >= policy["forward_live_weeks_min"]
        and len(weekly_h10) >= policy["divergence_weeks_min"]
        and len(weekly_h20) >= policy["h20_mature_weeks_min"]
        and mature_divergence_stocks >= policy["divergence_stocks_min"]
    )
    if not ready:
        verdict = "insufficient_data"
    elif (mean_h10 >= policy["practical_improvement_pp_min"]
          and favorable_ratio >= policy["favorable_weeks_ratio_min"]
          and median_h10 > 0 and mean_h20 >= 0):
        verdict = "candidate_better"
    elif (mean_h10 <= -policy["practical_improvement_pp_min"]
          and (1 - favorable_ratio) >= policy["favorable_weeks_ratio_min"]
          and median_h10 < 0 and mean_h20 <= 0):
        verdict = "baseline_better"
    else:
        verdict = "no_material_difference"

    underperformed = sum(value < 0 for value in forbidden_h10_excess)
    if not forbidden_h10_excess:
        selection_status = "not_evaluable"
    elif underperformed * 2 > len(forbidden_h10_excess):
        selection_status = "supportive"
    elif underperformed == 0:
        selection_status = "not_supportive"
    else:
        selection_status = "mixed"
    summary = {
        "schema_name": "a_short_regime_candidate_effect_summary",
        "schema_version": "1.1.0",
        "latest_evidence_as_of": max(live_weeks) if live_weeks else None,
        "policy": {
            "policy_id": policy["policy_id"],
            "policy_epoch": policy["policy_epoch"],
            "policy_fingerprint": candidate_effect_policy_fingerprint(),
            "h20_mature_weeks_min": policy["h20_mature_weeks_min"],
            "baseline_description": policy["baseline_description"],
            "candidate_proxy_description": policy["candidate_proxy_description"],
        },
        "admission": admission_snapshot("p1_regime_action_proxy"),
        "evidence_progress": {
            "forward_live_weeks": len(live_weeks),
            "valid_divergence_weeks": len(weekly_h10),
            "valid_divergence_stocks": mature_divergence_stocks,
            "h20_mature_weeks": len(weekly_h20),
            "h20_pending_weeks": h20_pending_weeks,
            "historical_not_counted": historical_not_counted,
            "immature_or_missing_not_counted": immature_or_missing,
            "ready_for_verdict": ready,
        },
        "data_quality": {"policy_groups": len(policy_groups), "same_week_equal_weighting": True},
        "operation_effect": {
            "primary_horizon_days": policy["primary_horizon_trading_days"],
            "weekly_mean_improvement_pp": mean_h10,
            "weekly_median_improvement_pp": median_h10,
            "favorable_week_ratio": favorable_ratio,
            "auxiliary_h20_mean_improvement_pp": mean_h20,
        },
        "selection_accuracy": {
            "forbidden_stock_count": len(forbidden_h10_excess),
            "forbidden_stock_underperformed_csi1000_count": underperformed,
            "status": selection_status,
        },
        "verdict": verdict,
        "boundary": {"comparison_only": True, "automatic_production_switch": False},
    }
    validate_candidate_effect_summary(summary)
    return summary


def validate_candidate_effect_summary(summary: dict) -> None:
    """Fail closed before public P1 JSON or Markdown is written."""
    try:
        jsonschema.validate(summary, _load_json(CANDIDATE_EFFECT_SUMMARY_SCHEMA_PATH))
    except jsonschema.ValidationError as exc:
        raise ValueError(f"candidate effect summary schema: {exc.message}") from exc
    if summary.get("admission") != admission_snapshot("p1_regime_action_proxy"):
        raise ValueError("candidate effect summary admission binding does not match current policy")
    if (summary.get("policy") or {}).get("policy_fingerprint") != candidate_effect_policy_fingerprint():
        raise ValueError("candidate effect summary policy fingerprint does not match current policy")
