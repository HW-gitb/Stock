# -*- coding: utf-8 -*-
"""US-short formal-result effects — second-cut single per-row effect reducer.

The weekend pipeline has several already-built producers (forward known-date events, portfolio guard,
and symbol cooldown).  This module is the only place that turns their non-neutral outputs into formal
result effects: one action override, the harshest single sizing reduction, the strictest confidence cap,
deduplicated risk tags, trigger/invalid conditions, upcoming events, and source references.  It deliberately
does *not* consume ``risk_downgrade`` again: that producer already affects the selection score, and applying it
here would double-punish the same fact.

No provider/network/broker work happens here.  Inputs are typed producer records from the same offline pipeline;
missing or malformed evidence never becomes a clean recommendation.
"""
from __future__ import annotations

import math
import json
from pathlib import Path

from engine.us_short_portfolio_guard import PORTFOLIO_GUARD_STATES, classify_portfolio_guard
from engine.us_short_weekend_decision import action_reason_error


class ResultEffectsError(ValueError):
    """A result-effect producer or a projected result effect is malformed."""


_BUILD = "建仓"
_OBSERVE = "观察"
_EXIT_OR_REDUCE = frozenset({"减仓", "清仓-止损", "清仓-止盈", "清仓-事件"})
_EVENT_DIRECTIONS = frozenset({"none", "reduce_or_observe", "reduce_caution", "bounded_positive", "price_note"})
_COOLDOWN_STATUSES = frozenset({"none", "entering_cooldown", "in_cooldown", "reentry_allowed"})
_EVIDENCE_KINDS = frozenset({"provider row", "SEC filing", "source_id"})

# Conservative v1 priors.  They are deliberately named rather than hidden in call sites: a future calibration
# changes this single reducer, while the "harshest single discount" invariant remains unchanged.
STRONG_DOWNGRADE_SIZE_MULT = 0.50
STRONG_DOWNGRADE_CONFIDENCE_CAP = 0.60
SOFT_RISK_CONFIDENCE_CAP = 0.85
PORTFOLIO_CAUTION_SIZE_MULT = 0.50
PORTFOLIO_CAUTION_CONFIDENCE_CAP = 0.75
RECOVERY_MIN_CONFIDENCE = 0.90
PORTFOLIO_GUARD_STATE_FILENAME = "portfolio_guard_state.json"
_GUARD_STATE_KEYS = {"schema_name", "schema_version", "as_of", "state"}
_EXTENSION_EFFECT_KEYS = {
    "source", "evidence_ref", "risk_tags", "trigger_conditions", "invalid_conditions",
    "size_multiplier", "confidence_cap", "action_override",
}


def _finite_unit(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and 0.0 <= float(value) <= 1.0)


def _nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def _evidence_ref(value, *, as_of, where):
    """Normalize a source-bound ref to the machine-record evidence shape.

    The upstream seam may supply ``{"kind", "value"}`` or a full record whose as_of equals the run.  A
    bare string is intentionally not accepted: visible effects must retain an explicit evidence kind.
    """
    if not (isinstance(value, dict) and {"kind", "value"} <= set(value)
            and set(value) - {"kind", "value"} <= {"as_of"}):
        raise ResultEffectsError(f"{where}.evidence_ref 须为 {{kind,value}} 或 {{kind,value,as_of}}")
    kind, ref_value = value.get("kind"), value.get("value")
    if kind not in _EVIDENCE_KINDS or not _nonblank(ref_value):
        raise ResultEffectsError(f"{where}.evidence_ref kind/value 非法")
    supplied_as_of = value.get("as_of", as_of)
    if supplied_as_of != as_of:
        raise ResultEffectsError(f"{where}.evidence_ref.as_of 必须等于 decision_date")
    return {"kind": kind, "value": ref_value.strip(), "as_of": as_of}


def build_portfolio_guard_result(paper_track, *, prior_state, as_of):
    """Classify the run-level portfolio guard from a source-bound model-paper input.

    ``paper_track`` is an exact producer packet, not a caller-provided final status.  It keeps the paper track
    primary and the private account secondary/advisory by construction; a non-evaluable or malformed track is
    delegated to the existing fail-safe classifier and therefore cannot become ``normal``.
    """
    required = {"paper_evaluable", "consecutive_stops", "paper_drawdown_frac", "evidence_ref"}
    if not isinstance(paper_track, dict) or set(paper_track) != required:
        raise ResultEffectsError(f"paper_track 须为 closed-world {sorted(required)}")
    evidence_ref = _evidence_ref(paper_track["evidence_ref"], as_of=as_of, where="paper_track")
    result = classify_portfolio_guard(
        paper_track["paper_evaluable"], paper_track["consecutive_stops"],
        paper_track["paper_drawdown_frac"], prior_state=prior_state,
    )
    if result["state"] not in PORTFOLIO_GUARD_STATES:
        raise ResultEffectsError("portfolio guard producer returned an unknown state")
    return {**result, "evidence_ref": evidence_ref}


def load_portfolio_guard_state(path, *, decision_date):
    """Load the minimal private guard-memory record; a missing record is the explicit first-run state."""
    path = Path(path)
    if not path.exists():
        return {"schema_name": "us_short_portfolio_guard_state", "schema_version": "1.0.0",
                "as_of": decision_date, "state": "normal"}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ResultEffectsError(f"portfolio guard state 无法读取: {exc}") from exc
    if not isinstance(state, dict) or set(state) != _GUARD_STATE_KEYS:
        raise ResultEffectsError("portfolio guard state 顶层键非法")
    if state.get("schema_name") != "us_short_portfolio_guard_state" or state.get("schema_version") != "1.0.0":
        raise ResultEffectsError("portfolio guard state schema 名称/版本非法")
    if not _nonblank(state.get("as_of")) or state["as_of"] > decision_date or state.get("state") not in PORTFOLIO_GUARD_STATES:
        raise ResultEffectsError("portfolio guard state as_of/state 非法")
    return state


def build_next_portfolio_guard_state(result, *, decision_date):
    if not isinstance(result, dict) or result.get("state") not in PORTFOLIO_GUARD_STATES:
        raise ResultEffectsError("portfolio guard result 无法写入私有 state")
    return {"schema_name": "us_short_portfolio_guard_state", "schema_version": "1.0.0",
            "as_of": decision_date, "state": result["state"]}


def unavailable_cooldown_records(rows, *, as_of):
    """Fail closed when the manual cooldown reconciliation/private state cannot be trusted.

    The action-table vocabulary has no ``unknown`` value.  ``in_cooldown`` is the conservative state and carries
    an explicit source id so it cannot be confused with the former injected ``none`` business placeholder.
    """
    out = {}
    for row in rows:
        ticker = row.get("ticker") if isinstance(row, dict) else None
        if not _nonblank(ticker) or ticker in out:
            raise ResultEffectsError("cannot build unavailable cooldown record for malformed/duplicate ticker")
        out[ticker] = {"status": "in_cooldown", "cooldown_until": None,
                       "reentry_allowed_reason": "cooldown_state_unavailable",
                       "evidence_ref": {"kind": "source_id", "value": "symbol_cooldown_state_unavailable:" + ticker,
                                        "as_of": as_of}}
    return out


def _new_effects():
    return {
        "action_override": None,
        "size_reduction_candidates": [],
        "selected_size_multiplier": 1.0,
        "confidence_cap_candidates": [],
        "action_confidence": 1.0,
        "risk_tags": [],
        "trigger_conditions": [],
        "invalid_conditions": [],
        "upcoming_events": [],
        "evidence_refs": {},
    }


def _add_tag(effects, tag, *, evidence_ref=None):
    if tag not in effects["risk_tags"]:
        effects["risk_tags"].append(tag)
    if evidence_ref is not None:
        effects["evidence_refs"]["risk_tag:" + tag] = evidence_ref


def _add_cap(effects, source, cap, evidence_ref):
    if not _finite_unit(cap):
        raise ResultEffectsError(f"{source} confidence cap 非法")
    effects["confidence_cap_candidates"].append({"source": source, "cap": float(cap)})
    effects["evidence_refs"]["confidence:" + source] = evidence_ref


def _add_size_reduction(effects, source, multiplier, evidence_ref):
    if not _finite_unit(multiplier):
        raise ResultEffectsError(f"{source} size multiplier 非法")
    effects["size_reduction_candidates"].append({"source": source, "multiplier": float(multiplier)})
    effects["evidence_refs"]["size:" + source] = evidence_ref


def _event_effects(row, effects, *, as_of):
    forward = row.get("forward_event")
    if forward is None:
        return
    if not isinstance(forward, dict) or forward.get("direction") not in _EVENT_DIRECTIONS:
        raise ResultEffectsError("forward_event 形状或 direction 非法")
    if forward.get("in_window") is not True:
        return
    event_type = forward.get("event_type")
    days = forward.get("days_to_event")
    if not _nonblank(event_type) or not isinstance(days, (int, float)) or isinstance(days, bool) or not math.isfinite(days):
        raise ResultEffectsError("in-window forward_event 缺 event_type/days_to_event")
    evidence = _evidence_ref(forward.get("evidence_ref"), as_of=as_of, where="forward_event")
    direction = forward["direction"]
    effects["upcoming_events"].append({"event_type": event_type, "days_to_event": float(days), "direction": direction})
    effects["evidence_refs"]["upcoming_event:" + event_type] = evidence
    effects["trigger_conditions"].append("known_%s_within_window" % event_type)
    _add_tag(effects, "upcoming_event:" + event_type, evidence_ref=evidence)

    # Price/exit actions have higher priority than a cautionary calendar effect.  For an entry/hold, an earnings
    # window is an explicit observe instruction; it is never a fabricated forced sale.
    if direction == "reduce_or_observe":
        if row.get("final_action") in {_BUILD, "持有"}:
            effects["action_override"] = {"final_action": _OBSERVE, "observe_reason_type": "event_window",
                                          "source": "forward_event:" + event_type, "evidence_ref": evidence}
        return
    if direction == "reduce_caution":
        _add_size_reduction(effects, "forward_event:" + event_type, STRONG_DOWNGRADE_SIZE_MULT, evidence)
        _add_cap(effects, "forward_event:" + event_type, STRONG_DOWNGRADE_CONFIDENCE_CAP, evidence)
    elif direction == "bounded_positive":
        effects["trigger_conditions"].append("bounded_positive_%s" % event_type)
    elif direction == "price_note":
        effects["invalid_conditions"].append("verify_%s_price_basis" % event_type)


def _event_gap_effects(row, effects, *, as_of):
    gap = row.get("event_data_gap")
    if gap is None:
        return
    if not isinstance(gap, dict) or gap.get("status") not in {"ok", "restricted", "reduce_caution", "tag"}:
        raise ResultEffectsError("event_data_gap.status 非法")
    status = gap["status"]
    if status == "ok":
        return
    # A gap is a negative fact, not a provider claim.  Its source is the explicit producer classification tied
    # to this decision date, so it still remains reversibly traceable.
    evidence = {"kind": "source_id", "value": "event_data_gap:" + row["ticker"], "as_of": as_of}
    _add_tag(effects, "event_data_gap:" + status, evidence_ref=evidence)
    effects["invalid_conditions"].append("event_data_gap:" + status)
    if status == "reduce_caution":
        _add_size_reduction(effects, "event_data_gap", STRONG_DOWNGRADE_SIZE_MULT, evidence)
        _add_cap(effects, "event_data_gap", STRONG_DOWNGRADE_CONFIDENCE_CAP, evidence)
    elif status == "tag":
        _add_cap(effects, "event_data_gap", SOFT_RISK_CONFIDENCE_CAP, evidence)


def _portfolio_effects(portfolio_guard_result, effects):
    if not isinstance(portfolio_guard_result, dict) or portfolio_guard_result.get("state") not in PORTFOLIO_GUARD_STATES:
        raise ResultEffectsError("portfolio_guard_result 非法")
    evidence = portfolio_guard_result.get("evidence_ref")
    if not isinstance(evidence, dict):
        raise ResultEffectsError("portfolio_guard_result 缺 source-bound evidence_ref")
    state = portfolio_guard_result["state"]
    effects["evidence_refs"]["portfolio_guard"] = evidence
    if state == "normal":
        return
    _add_tag(effects, "portfolio_guard:" + state, evidence_ref=evidence)
    if state == "caution":
        _add_size_reduction(effects, "portfolio_guard:caution", PORTFOLIO_CAUTION_SIZE_MULT, evidence)
        _add_cap(effects, "portfolio_guard:caution", PORTFOLIO_CAUTION_CONFIDENCE_CAP, evidence)
    elif state == "recovery":
        effects["trigger_conditions"].append("portfolio_guard_recovery_high_confidence_only")
    elif state == "cooldown":
        effects["invalid_conditions"].append("portfolio_guard_cooldown_blocks_new_entry")


def _cooldown_effects(row, effects, cooldown):
    if not isinstance(cooldown, dict) or cooldown.get("status") not in _COOLDOWN_STATUSES:
        raise ResultEffectsError("symbol cooldown record 非法")
    evidence = cooldown.get("evidence_ref")
    if not isinstance(evidence, dict):
        raise ResultEffectsError("symbol cooldown record 缺 evidence_ref")
    status = cooldown["status"]
    effects["evidence_refs"]["symbol_cooldown"] = evidence
    if status in {"entering_cooldown", "in_cooldown"}:
        _add_tag(effects, "symbol_cooldown", evidence_ref=evidence)
        effects["invalid_conditions"].append("symbol_cooldown_active")
        if row.get("final_action") == _BUILD:
            effects["action_override"] = {"final_action": _OBSERVE, "observe_reason_type": "risk_cooldown",
                                          "source": "symbol_cooldown", "evidence_ref": evidence}
    elif status == "reentry_allowed":
        _add_tag(effects, "symbol_cooldown:reentry_allowed", evidence_ref=evidence)
        effects["trigger_conditions"].append("symbol_cooldown_reentry_all_conditions_met")


def _base_confidence(final_action):
    # Observed/rejected rows must never appear as a high-confidence recommendation.  Exits remain decisive but
    # still respect a real confidence cap from a concurrent non-neutral risk producer.
    return 0.0 if final_action in {_OBSERVE, "否决/避开"} else 1.0


def _finalize_effects(effects, final_action):
    if not isinstance(effects, dict):
        raise ResultEffectsError("result_effects 须为 dict")
    caps = effects.get("confidence_cap_candidates")
    reductions = effects.get("size_reduction_candidates")
    if not isinstance(caps, list) or not isinstance(reductions, list):
        raise ResultEffectsError("result_effects candidate lists 非法")
    cap_values = []
    for item in caps:
        if not (isinstance(item, dict) and _nonblank(item.get("source")) and _finite_unit(item.get("cap"))):
            raise ResultEffectsError("confidence_cap candidate 非法")
        cap_values.append(float(item["cap"]))
    mult_values = []
    for item in reductions:
        if not (isinstance(item, dict) and _nonblank(item.get("source")) and _finite_unit(item.get("multiplier"))):
            raise ResultEffectsError("size_reduction candidate 非法")
        mult_values.append(float(item["multiplier"]))
    return {**effects,
            "action_confidence": min([_base_confidence(final_action)] + cap_values),
            "selected_size_multiplier": min([1.0] + mult_values)}


def apply_result_effects(decision_result, *, portfolio_guard_result, cooldown_by_ticker, as_of):
    """Attach formal effects to every decided row before per-row sizing.

    ``cooldown_by_ticker`` must exactly cover the decision rows.  It is a real private-state resolution, not the
    former basket-context ``none`` placeholder.  The function returns the same stage shape plus a run-level
    ``portfolio_guard_result``; later sizing/basket stages consume those exact records.
    """
    if not (isinstance(decision_result, dict) and isinstance(decision_result.get("regime"), dict)
            and isinstance(decision_result.get("rows"), list)):
        raise ResultEffectsError("decision_result 须为含 regime/rows 的 dict")
    if not isinstance(cooldown_by_ticker, dict):
        raise ResultEffectsError("cooldown_by_ticker 须为 dict")
    guard_state = portfolio_guard_result.get("state") if isinstance(portfolio_guard_result, dict) else None
    if guard_state not in PORTFOLIO_GUARD_STATES:
        raise ResultEffectsError("portfolio_guard_result.state 非法")
    out = []
    seen = set()
    for row in decision_result["rows"]:
        if not isinstance(row, dict) or not _nonblank(row.get("ticker")):
            raise ResultEffectsError("decision row 缺 ticker")
        ticker = row["ticker"]
        if ticker in seen:
            raise ResultEffectsError("decision rows ticker 重复")
        seen.add(ticker)
        if ticker not in cooldown_by_ticker:
            raise ResultEffectsError(f"{ticker}: 缺真实 symbol cooldown record")
        effects = _new_effects()
        _event_effects(row, effects, as_of=as_of)
        _event_gap_effects(row, effects, as_of=as_of)
        _portfolio_effects(portfolio_guard_result, effects)
        cooldown = cooldown_by_ticker[ticker]
        _cooldown_effects(row, effects, cooldown)
        override = effects["action_override"]
        action = override["final_action"] if isinstance(override, dict) else row.get("final_action")
        reason = override["observe_reason_type"] if isinstance(override, dict) else row.get("observe_reason_type")
        err = action_reason_error(action, reason)
        if err:
            raise ResultEffectsError(err)
        effects = _finalize_effects(effects, action)
        out.append({**row, "final_action": action, "observe_reason_type": reason,
                    "result_effects": effects, "action_confidence": effects["action_confidence"],
                    "risk_tags": list(effects["risk_tags"]),
                    "trigger_conditions": list(effects["trigger_conditions"]),
                    "invalid_conditions": list(effects["invalid_conditions"]),
                    "upcoming_events": list(effects["upcoming_events"]),
                    "portfolio_guard_status": guard_state,
                    "symbol_cooldown_status": cooldown["status"],
                    "cooldown_until": cooldown.get("cooldown_until"),
                    "reentry_allowed_reason": cooldown.get("reentry_allowed_reason")})
    if set(cooldown_by_ticker) != seen:
        raise ResultEffectsError("cooldown_by_ticker 须恰覆盖 decision rows")
    return {**decision_result, "rows": out, "portfolio_guard_result": portfolio_guard_result}


def extend_result_effects(result, *, effects_by_ticker, as_of):
    """Add later typed producers to the same Cut2 reducer without creating a second effect stack.

    Every row is covered exactly once.  Each producer record carries its own source/evidence and may add an
    action override, one sizing candidate, one confidence cap, tags, triggers, and invalid conditions.  The
    reducer always re-selects the harshest single size multiplier and strictest confidence cap; it never
    multiplies a new discount into an already-sized result.
    """
    if not (isinstance(result, dict) and isinstance(result.get("rows"), list)):
        raise ResultEffectsError("result 须为含 rows 的 dict")
    if not isinstance(effects_by_ticker, dict):
        raise ResultEffectsError("effects_by_ticker 须为 dict")
    out, seen = [], set()
    for row in result["rows"]:
        if not isinstance(row, dict) or not _nonblank(row.get("ticker")):
            raise ResultEffectsError("result row 缺 ticker")
        ticker = row["ticker"]
        if ticker in seen or ticker not in effects_by_ticker:
            raise ResultEffectsError("effects_by_ticker 须恰覆盖且不重复 result rows")
        seen.add(ticker)
        records = effects_by_ticker[ticker]
        if not isinstance(records, list):
            raise ResultEffectsError(f"{ticker}: extension effects 须为 list")
        effects = row.get("result_effects")
        if not isinstance(effects, dict):
            raise ResultEffectsError(f"{ticker}: 缺 Cut2 result_effects")
        # Copy every mutable child before appending so the provisional first pass stays side-effect free.
        effects = {
            **effects,
            "size_reduction_candidates": list(effects.get("size_reduction_candidates") or []),
            "confidence_cap_candidates": list(effects.get("confidence_cap_candidates") or []),
            "risk_tags": list(effects.get("risk_tags") or []),
            "trigger_conditions": list(effects.get("trigger_conditions") or []),
            "invalid_conditions": list(effects.get("invalid_conditions") or []),
            "upcoming_events": list(effects.get("upcoming_events") or []),
            "evidence_refs": dict(effects.get("evidence_refs") or {}),
        }
        for idx, record in enumerate(records):
            where = f"effects_by_ticker[{ticker}][{idx}]"
            if not isinstance(record, dict) or set(record) != _EXTENSION_EFFECT_KEYS:
                raise ResultEffectsError(f"{where} 须为 closed-world {sorted(_EXTENSION_EFFECT_KEYS)}")
            source = record["source"]
            if not _nonblank(source):
                raise ResultEffectsError(f"{where}.source 须非空")
            source = source.strip()
            evidence = _evidence_ref(record["evidence_ref"], as_of=as_of, where=where)
            source_key = "effect:" + source
            if source_key in effects["evidence_refs"]:
                raise ResultEffectsError(f"{ticker}: duplicate extension source {source!r}")
            effects["evidence_refs"][source_key] = evidence

            tags = record["risk_tags"]
            triggers = record["trigger_conditions"]
            invalid = record["invalid_conditions"]
            if any(not isinstance(values, list) or any(not _nonblank(v) for v in values)
                   for values in (tags, triggers, invalid)):
                raise ResultEffectsError(f"{where} tags/conditions 须为非空 str list")
            for tag in tags:
                _add_tag(effects, tag.strip(), evidence_ref=evidence)
            for value, target in ((triggers, effects["trigger_conditions"]),
                                  (invalid, effects["invalid_conditions"])):
                for item in value:
                    item = item.strip()
                    if item not in target:
                        target.append(item)

            multiplier = record["size_multiplier"]
            if multiplier is not None:
                _add_size_reduction(effects, source, multiplier, evidence)
            cap = record["confidence_cap"]
            if cap is not None:
                _add_cap(effects, source, cap, evidence)
            override = record["action_override"]
            if override is not None:
                if not (isinstance(override, dict)
                        and set(override) == {"final_action", "observe_reason_type"}):
                    raise ResultEffectsError(f"{where}.action_override 形状非法")
                if effects.get("action_override") is not None:
                    raise ResultEffectsError(f"{ticker}: multiple action overrides are not allowed")
                if row.get("final_action") in _EXIT_OR_REDUCE:
                    raise ResultEffectsError(f"{ticker}: protective exit/reduce action cannot be overridden")
                err = action_reason_error(override["final_action"], override["observe_reason_type"])
                if err:
                    raise ResultEffectsError(err)
                effects["action_override"] = {
                    **override, "source": source, "evidence_ref": evidence,
                }

        override = effects.get("action_override")
        action = override["final_action"] if isinstance(override, dict) else row.get("final_action")
        reason = override["observe_reason_type"] if isinstance(override, dict) else row.get("observe_reason_type")
        err = action_reason_error(action, reason)
        if err:
            raise ResultEffectsError(err)
        effects = _finalize_effects(effects, action)
        out.append({
            **row,
            "final_action": action,
            "observe_reason_type": reason,
            "result_effects": effects,
            "action_confidence": effects["action_confidence"],
            "risk_tags": list(effects["risk_tags"]),
            "trigger_conditions": list(effects["trigger_conditions"]),
            "invalid_conditions": list(effects["invalid_conditions"]),
            "upcoming_events": list(effects["upcoming_events"]),
        })
    if set(effects_by_ticker) != seen:
        raise ResultEffectsError("effects_by_ticker 须恰覆盖 result rows")
    return {**result, "rows": out}


def finalize_result_effects(result):
    """Re-project final action-dependent confidence after basket/cash changes.

    This is intentionally the only late-stage recalculation: it does not re-derive any evidence or effect candidate;
    it merely applies the already-recorded confidence cap to the final action that survived all gates.
    """
    if not (isinstance(result, dict) and isinstance(result.get("rows"), list)):
        raise ResultEffectsError("result 须为含 rows 的 dict")
    rows = []
    for row in result["rows"]:
        if not isinstance(row, dict):
            raise ResultEffectsError("result row 须为 dict")
        action, reason = row.get("final_action"), row.get("observe_reason_type")
        err = action_reason_error(action, reason)
        if err:
            raise ResultEffectsError(err)
        effects = _finalize_effects(row.get("result_effects"), action)
        rows.append({**row, "result_effects": effects, "action_confidence": effects["action_confidence"]})
    return {**result, "rows": rows}


def validate_result_effects(row, *, as_of):
    """Reverse validator for the formal projections on one final machine row.

    It proves that tags, confidence, conditions, upcoming events and guard/cooldown columns are projections of the
    one actual ``result_effects`` record; a caller cannot plant a clean-looking tag or confidence value without the
    corresponding effect evidence.
    """
    if not isinstance(row, dict) or not _nonblank(row.get("ticker")):
        raise ResultEffectsError("machine row 缺 ticker")
    effects = _finalize_effects(row.get("result_effects"), row.get("final_action"))
    required = {"risk_tags", "trigger_conditions", "invalid_conditions", "upcoming_events"}
    for key in required:
        if row.get(key) != effects[key]:
            raise ResultEffectsError(f"{row['ticker']}: {key} 未从 result_effects 单源投影")
    if row.get("action_confidence") != effects["action_confidence"]:
        raise ResultEffectsError(f"{row['ticker']}: action_confidence 未从 result_effects 单源投影")
    if not _finite_unit(row.get("action_confidence")):
        raise ResultEffectsError(f"{row['ticker']}: action_confidence 须为 [0,1] 有限数")
    if row.get("portfolio_guard_status") not in PORTFOLIO_GUARD_STATES:
        raise ResultEffectsError(f"{row['ticker']}: portfolio_guard_status 非法")
    if row.get("symbol_cooldown_status") not in _COOLDOWN_STATUSES:
        raise ResultEffectsError(f"{row['ticker']}: symbol_cooldown_status 非法")
    evidence_refs = effects.get("evidence_refs")
    if not isinstance(evidence_refs, dict) or not evidence_refs:
        raise ResultEffectsError(f"{row['ticker']}: result_effects 必须保留 evidence_refs")
    for key, evidence in evidence_refs.items():
        _evidence_ref(evidence, as_of=as_of, where="result_effects." + str(key))
    override = effects.get("action_override")
    if override is not None:
        if not isinstance(override, dict) or row.get("final_action") != override.get("final_action"):
            raise ResultEffectsError(f"{row['ticker']}: action override 未落到 final_action")
        _evidence_ref(override.get("evidence_ref"), as_of=as_of, where="result_effects.action_override")
    return effects
