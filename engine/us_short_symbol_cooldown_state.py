# -*- coding: utf-8 -*-
"""US-short private per-symbol cooldown state for the formal-result second cut.

Only a reconciled manual *filled* failure can create a cooldown.  The state stores the frozen trigger date and
its derived expiry so a later weekly run cannot forget a stop merely because the current positions snapshot no
longer contains that ticker.  An expired cooldown is still not a free re-buy: the resolver delegates the all-three
new-catalyst + new-structure + expired gate to ``us_short_symbol_cooldown``.

Private JSON only; no broker/order/provider/network operation is performed here.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_symbol_cooldown import ENTERS_COOLDOWN_ON, symbol_cooldown_status


STATE_FILENAME = "symbol_cooldown_state.json"
STATE_SCHEMA_NAME = "us_short_symbol_cooldown_state"
STATE_SCHEMA_VERSION = "1.0.0"
COOLDOWN_CALENDAR_DAYS = 20  # §13 #23 v1 forward prior; the trigger and all-three re-entry gate are design-locked.


class SymbolCooldownStateError(ValueError):
    """The private cooldown state, reconciliation, or re-entry proof is malformed."""


def _date(value, where):
    if not (isinstance(value, str) and len(value) == 8 and value.isascii() and value.isdigit()):
        raise SymbolCooldownStateError(f"{where} 须为严格 YYYYMMDD")
    try:
        _dt.datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise SymbolCooldownStateError(f"{where} 不是实际日期") from exc
    return value


def _plus_days(value, days):
    return (_dt.datetime.strptime(value, "%Y%m%d").date() + _dt.timedelta(days=days)).strftime("%Y%m%d")


def _nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def _validate_evidence_ref(value, where):
    if not (isinstance(value, dict) and {"kind", "value"} <= set(value)
            and set(value) - {"kind", "value"} <= {"as_of"}):
        raise SymbolCooldownStateError(f"{where}.evidence_ref 须为 {{kind,value}} 或 {{kind,value,as_of}}")
    if value.get("kind") not in {"provider row", "SEC filing", "source_id"} or not _nonblank(value.get("value")):
        raise SymbolCooldownStateError(f"{where}.evidence_ref kind/value 非法")
    return value


def _empty_state(as_of):
    return {"schema_name": STATE_SCHEMA_NAME, "schema_version": STATE_SCHEMA_VERSION,
            "as_of": as_of, "records": []}


def validate_symbol_cooldown_state(state, *, decision_date):
    _date(decision_date, "decision_date")
    if not isinstance(state, dict) or set(state) != {"schema_name", "schema_version", "as_of", "records"}:
        raise SymbolCooldownStateError("symbol cooldown state 顶层键非法")
    if state["schema_name"] != STATE_SCHEMA_NAME or state["schema_version"] != STATE_SCHEMA_VERSION:
        raise SymbolCooldownStateError("symbol cooldown state schema 名称/版本非法")
    _date(state["as_of"], "cooldown_state.as_of")
    if state["as_of"] > decision_date:
        raise SymbolCooldownStateError("cooldown_state.as_of 不得晚于 decision_date")
    if not isinstance(state["records"], list):
        raise SymbolCooldownStateError("cooldown_state.records 须为 list")
    seen = set()
    for record in state["records"]:
        if not isinstance(record, dict) or set(record) != {
                "ticker", "trigger", "triggered_at", "cooldown_until", "source_reconciliation_ref"}:
            raise SymbolCooldownStateError("cooldown record 键非法")
        ticker = canonical_us_ticker(record["ticker"])
        if ticker is None or ticker != record["ticker"] or ticker in seen:
            raise SymbolCooldownStateError("cooldown record ticker 非法/重复")
        seen.add(ticker)
        if record["trigger"] not in ENTERS_COOLDOWN_ON:
            raise SymbolCooldownStateError("cooldown record trigger 非法")
        triggered_at, until = _date(record["triggered_at"], "cooldown.triggered_at"), _date(record["cooldown_until"], "cooldown.cooldown_until")
        if until != _plus_days(triggered_at, COOLDOWN_CALENDAR_DAYS):
            raise SymbolCooldownStateError("cooldown_until 与冻结 cooldown 天数不符")
        if triggered_at > decision_date or not _nonblank(record["source_reconciliation_ref"]):
            raise SymbolCooldownStateError("cooldown record 日期/来源非法")


def load_symbol_cooldown_state(path, *, decision_date):
    path = Path(path)
    if not path.exists():
        return _empty_state(decision_date)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SymbolCooldownStateError(f"cooldown state 无法读取: {exc}") from exc
    validate_symbol_cooldown_state(state, decision_date=decision_date)
    return state


def _validate_reconciliation(reconciliation, *, decision_date):
    if not isinstance(reconciliation, dict) or set(reconciliation) != {"schema_name", "schema_version", "as_of", "events"}:
        raise SymbolCooldownStateError("symbol_cooldown_reconciliation 顶层键非法")
    if reconciliation["schema_name"] != "us_short_symbol_cooldown_reconciliation" or reconciliation["schema_version"] != "1.0.0":
        raise SymbolCooldownStateError("symbol_cooldown_reconciliation schema 名称/版本非法")
    if reconciliation["as_of"] != decision_date:
        raise SymbolCooldownStateError("symbol_cooldown_reconciliation.as_of 须等于 decision_date")
    if not isinstance(reconciliation["events"], list):
        raise SymbolCooldownStateError("symbol_cooldown_reconciliation.events 须为 list")
    seen = set()
    out = []
    for event in reconciliation["events"]:
        if not isinstance(event, dict) or set(event) != {"ticker", "trigger", "triggered_at", "source_reconciliation_ref"}:
            raise SymbolCooldownStateError("symbol_cooldown_reconciliation event 键非法")
        ticker = canonical_us_ticker(event["ticker"])
        date = _date(event["triggered_at"], "cooldown reconciliation.triggered_at")
        if (ticker is None or ticker != event["ticker"] or ticker in seen or event["trigger"] not in ENTERS_COOLDOWN_ON
                or date > decision_date or not _nonblank(event["source_reconciliation_ref"])):
            raise SymbolCooldownStateError("symbol_cooldown_reconciliation event 值非法/重复")
        seen.add(ticker)
        out.append({**event, "ticker": ticker})
    return out


def build_next_symbol_cooldown_state(prior_state, reconciliation, *, decision_date):
    """Merge latest reconciled filled-failure events into the private state.

    A manual reconciliation may retain full history; only the latest event for each ticker survives.  Events can
    never be invented from an unfilled order because the converter emits only ``filled_then_*`` triggers.
    """
    _date(decision_date, "decision_date")
    validate_symbol_cooldown_state(prior_state, decision_date=decision_date)
    events = _validate_reconciliation(reconciliation, decision_date=decision_date)
    records = {record["ticker"]: dict(record) for record in prior_state["records"]}
    for event in events:
        old = records.get(event["ticker"])
        if old is None or event["triggered_at"] >= old["triggered_at"]:
            records[event["ticker"]] = {
                "ticker": event["ticker"], "trigger": event["trigger"], "triggered_at": event["triggered_at"],
                "cooldown_until": _plus_days(event["triggered_at"], COOLDOWN_CALENDAR_DAYS),
                "source_reconciliation_ref": event["source_reconciliation_ref"],
            }
    state = {"schema_name": STATE_SCHEMA_NAME, "schema_version": STATE_SCHEMA_VERSION,
             "as_of": decision_date, "records": [records[t] for t in sorted(records)]}
    validate_symbol_cooldown_state(state, decision_date=decision_date)
    return state


def _reentry_flags(raw, *, decision_date, ticker):
    """Read the optional source-bound re-entry producer from an analysis row.

    No record means False/False — an expired cooldown cannot silently permit a re-buy.  A claimed positive flag
    needs its own evidence ref; this leaves future catalyst/source work free to produce the evidence without
    reopening the cooldown state machine.
    """
    if raw is None:
        return False, False, []
    if not isinstance(raw, dict) or set(raw) != {"new_catalyst", "new_structure"}:
        raise SymbolCooldownStateError(f"{ticker}: reentry_evidence 须为 new_catalyst/new_structure")
    flags, refs = [], []
    for key in ("new_catalyst", "new_structure"):
        item = raw[key]
        if not isinstance(item, dict) or set(item) != {"present", "evidence_ref"} or not isinstance(item["present"], bool):
            raise SymbolCooldownStateError(f"{ticker}: reentry_evidence.{key} 形状非法")
        if item["present"]:
            ref = _validate_evidence_ref(item["evidence_ref"], f"{ticker}.reentry_evidence.{key}")
            if ref.get("as_of", decision_date) != decision_date:
                raise SymbolCooldownStateError(f"{ticker}: reentry evidence as_of 须等于 decision_date")
            refs.append({"kind": ref["kind"], "value": ref["value"], "as_of": decision_date})
        elif item["evidence_ref"] is not None:
            raise SymbolCooldownStateError(f"{ticker}: 未满足的 reentry 条件不得携带 evidence_ref")
        flags.append(item["present"])
    return flags[0], flags[1], refs


def resolve_symbol_cooldowns(state, analysis_rows, *, decision_date):
    """Resolve each selected ticker's actual cooldown record for this run.

    Returns a ticker-keyed map consumed by ``result_effects``.  A prior triggered state remains active through its
    inclusive ``cooldown_until`` date.  On expiry, only evidenced new catalyst + new structure opens re-entry.
    """
    validate_symbol_cooldown_state(state, decision_date=decision_date)
    if not isinstance(analysis_rows, list):
        raise SymbolCooldownStateError("analysis_rows 须为 list")
    records = {r["ticker"]: r for r in state["records"]}
    out, seen = {}, set()
    for row in analysis_rows:
        ticker = canonical_us_ticker(row.get("ticker")) if isinstance(row, dict) else None
        if ticker is None or ticker in seen:
            raise SymbolCooldownStateError("analysis_rows ticker 非法/重复")
        seen.add(ticker)
        record = records.get(ticker)
        if record is None:
            out[ticker] = {"status": "none", "cooldown_until": None, "reentry_allowed_reason": None,
                           "evidence_ref": {"kind": "source_id", "value": "symbol_cooldown_state:%s:none" % ticker,
                                            "as_of": decision_date}}
            continue
        new_catalyst, new_structure, reentry_refs = _reentry_flags(row.get("reentry_evidence"), decision_date=decision_date,
                                                                     ticker=ticker)
        expired = decision_date > record["cooldown_until"]
        status = symbol_cooldown_status(True, trigger=record["trigger"], new_catalyst=new_catalyst,
                                        new_structure=new_structure, cooldown_expired=expired)
        reason = ("new_catalyst+new_structure+cooldown_expired" if status["reentry_allowed"]
                  else "waiting_for_new_catalyst+new_structure+cooldown_expired")
        refs = [{"kind": "source_id", "value": record["source_reconciliation_ref"], "as_of": decision_date}] + reentry_refs
        # A deterministic composite source id preserves the manual reconciliation as the root while avoiding a
        # fake provider claim.  The detailed refs remain in the private state/analysis inputs.
        out[ticker] = {"status": status["status"], "cooldown_until": record["cooldown_until"],
                       "reentry_allowed_reason": reason,
                       "evidence_ref": {"kind": "source_id", "value": "symbol_cooldown:" + record["source_reconciliation_ref"],
                                        "as_of": decision_date},
                       "component_evidence_refs": refs}
    return out
