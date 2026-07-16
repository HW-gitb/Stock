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
from pathlib import Path

import jsonschema

from engine.a_short_regime_classifier import FORWARD_RETURN_BASIS, RAW_REGIMES, V14_2_REGIMES
from engine.a_short_regime_ledger import is_canonical_date


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "a_short_regime_action_comparison_weekly.schema.json"
GOVERNANCE_PATH = ROOT / "presets" / "a_short_regime_action_comparison_governance_20260714.json"


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
    decision_as_of = str(forward_origin.get("decision_as_of"))
    run_date = str(forward_origin.get("run_date"))
    if not is_canonical_date(decision_as_of) or not is_canonical_date(run_date):
        raise ValueError("forward origin requires real decision_as_of and run_date")
    # This is derived by the runner from its actual invocation date.  Callers cannot
    # self-label a historical replay as forward evidence with a Boolean flag.
    forward_eligible = decision_as_of == run_date
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
        "schema_version": "1.0.0",
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
        "forward_origin": {"decision_as_of": decision_as_of, "run_date": run_date},
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
    if record.get("forward_eligible") != (decision_as_of == run_date):
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
    ready = (len(forward_records) >= gate["forward_live_weeks_min"]
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
