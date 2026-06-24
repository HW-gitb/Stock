# -*- coding: utf-8 -*-
"""US-short Pass1 cheap-eligibility gate + frozen-governance runtime validator — batch4 slice 4c-ii-a.

Design authority: docs/us_short_system_design.md §4.0 (Universe + two-pass) / §4.1 (安全闸) /
§18.2 build-vs-wire ④. Consumes the FROZEN eligibility governance contract
(presets/us_short_eligibility_governance_20260624.json, slice 4c-i).

This module is the RUNTIME consumer-validation edge for that governance artifact: the JSON schema
(+ its schema-test) is the CI gate, but jsonschema may be absent at runtime (cf. the market-calendar
slice), so `validate_eligibility_governance` re-enforces the const-pinned v1 semantics here against
module consts. A conformance test triangulates module const == committed preset, so this consumer
copy cannot silently drift (mirrors engine/us_short_regime.py::POSITION_CAP). Calibration of the
§13.1 #2 priors is a reviewed schema+preset+module version bump, never a silent edit.

`cheap_eligible` (Pass1) is a pure boolean narrowing over an injected universe row: exchange ∈
whitelist + price/ADV/market-cap ≥ floors + no disqualifying status flag. It is FAIL-CLOSED — a
missing / non-finite / wrong-type field makes the row ineligible with an explicit reason (key
unknown → conservative, §3.3), never a silent pass. Momentum / theme / catalyst SCORING is not here
(§4.2+); the authoritative Pass2 audit-safety-gate reuses engine/us_short_hard_veto.py (slice
4c-ii-b). Pure/offline; no provider/live/network; no A-share crossing.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

# Frozen v1 governed semantics (== presets/us_short_eligibility_governance_20260624.json; a
# conformance test triangulates module const == preset so this consumer copy cannot drift).
_V1_EXCHANGE_WHITELIST = ("NYSE", "NASDAQ")
_V1_DISQUALIFYING_STATUS_FLAGS = ("delisted", "halted", "bankruptcy", "otc")
_V1_THRESHOLDS = {"min_price_usd": 5.0, "min_adv_usd": 5000000.0, "min_market_cap_usd": 300000000.0}
_V1_ANCHORS = {
    "thresholds_calibration_item_id": 2,
    "candidate_set_calibration_item_id": 19,
    "catalyst_recall_calibration_item_id": 21,
}
_REQUIRED_GOV_KEYS = {
    "schema_name", "schema_version", "as_of", "status",
    "exchange_whitelist", "cheap_eligibility_thresholds", "disqualifying_status_flags",
    "thresholds_calibration_item_id", "candidate_set_calibration_item_id",
    "catalyst_recall_calibration_item_id", "notes",
}


class EligibilityGovernanceError(Exception):
    """The loaded eligibility governance artifact is malformed or has drifted from the frozen v1
    contract (fail-closed)."""


def _is_finite_number(x):
    """Strict: a real finite number — rejects bool, None, strings, NaN/Inf."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate_eligibility_governance(gov):
    """Fail-closed runtime gate: the loaded governance must BE the frozen v1 contract.

    Structural (closed-world top-level key set, types) + semantic (the governed v1 values —
    exchange whitelist / threshold floors / disqualifier set / §13.1 anchors — must equal the
    frozen v1 consts). Metadata (schema_version / as_of / status / notes) is type-checked, not
    value-pinned (it varies across versions). Returns the dict on success; raises otherwise.
    """
    if not isinstance(gov, dict):
        raise EligibilityGovernanceError("governance 须为 object")
    if set(gov) != _REQUIRED_GOV_KEYS:
        raise EligibilityGovernanceError(
            f"governance 顶层键须恰为 {sorted(_REQUIRED_GOV_KEYS)}（closed-world）: {sorted(gov)}")
    if gov["schema_name"] != "us_short_eligibility_governance":
        raise EligibilityGovernanceError(f"schema_name 非法: {gov['schema_name']!r}")
    if not (isinstance(gov["schema_version"], str) and gov["schema_version"]):
        raise EligibilityGovernanceError("schema_version 须为非空字符串")
    if not (isinstance(gov["as_of"], str) and len(gov["as_of"]) == 8 and gov["as_of"].isascii()
            and gov["as_of"].isdigit()):
        raise EligibilityGovernanceError(f"as_of 须为 8 位 ASCII YYYYMMDD: {gov['as_of']!r}")
    try:
        datetime.strptime(gov["as_of"], "%Y%m%d")
    except ValueError:
        raise EligibilityGovernanceError(f"as_of 非真实日历日: {gov['as_of']!r}")
    if not (isinstance(gov["status"], str) and gov["status"].strip()):
        raise EligibilityGovernanceError("status 须为非空字符串")
    if not (isinstance(gov["notes"], dict) and gov["notes"]):
        raise EligibilityGovernanceError("notes 须为非空 object")

    # Governed v1 values — must equal the frozen consts (drift fails closed at runtime).
    if list(gov["exchange_whitelist"]) != list(_V1_EXCHANGE_WHITELIST):
        raise EligibilityGovernanceError(
            f"exchange_whitelist 偏离冻结 v1 {list(_V1_EXCHANGE_WHITELIST)}（校准须 reviewed 版本变更）: {gov['exchange_whitelist']!r}")
    if list(gov["disqualifying_status_flags"]) != list(_V1_DISQUALIFYING_STATUS_FLAGS):
        raise EligibilityGovernanceError(
            f"disqualifying_status_flags 偏离冻结 v1 {list(_V1_DISQUALIFYING_STATUS_FLAGS)}: {gov['disqualifying_status_flags']!r}")
    th = gov["cheap_eligibility_thresholds"]
    if not isinstance(th, dict) or set(th) != set(_V1_THRESHOLDS):
        raise EligibilityGovernanceError(f"cheap_eligibility_thresholds 键须恰为 {sorted(_V1_THRESHOLDS)}: {th!r}")
    for k, expected in _V1_THRESHOLDS.items():
        if not _is_finite_number(th[k]) or float(th[k]) != expected:
            raise EligibilityGovernanceError(
                f"cheap_eligibility_thresholds.{k} 偏离冻结 v1 prior {expected}（校准须 reviewed 版本变更）: {th[k]!r}")
    for k, expected in _V1_ANCHORS.items():
        if not (isinstance(gov[k], int) and not isinstance(gov[k], bool) and gov[k] == expected):
            raise EligibilityGovernanceError(f"{k} 偏离冻结 §13.1 锚 {expected}: {gov[k]!r}")
    return gov


def load_eligibility_governance(path):
    """Load + fail-closed-validate the frozen eligibility governance artifact (offline; no network)."""
    with open(Path(path), encoding="utf-8") as f:
        gov = json.load(f)
    return validate_eligibility_governance(gov)


# Pass1 row contract (injected universe row; batch5 maps the FMP profile to these cheap fields).
_REQUIRED_ROW_NUMERIC = ("price", "adv_usd", "market_cap_usd")
_FLOOR_OF = {"price": "min_price_usd", "adv_usd": "min_adv_usd", "market_cap_usd": "min_market_cap_usd"}


def cheap_eligible(row, *, governance):
    """Pass1 cheap-eligibility predicate over one injected universe row (FAIL-CLOSED).

    row = {"ticker": str, "exchange": str, "price"/"adv_usd"/"market_cap_usd": finite number,
           "delisted"/"halted"/"bankruptcy"/"otc": REQUIRED bool (absent or non-bool ->
           conservative unknown, §3.3 — a critical status is NEVER assumed clean by omission)}.
    governance = a dict already passed through validate_eligibility_governance.

    Returns {"ticker", "eligible": bool, "reasons": [str, ...]}. eligible == (reasons == []).
    A missing / non-finite / wrong-type field yields an explicit reason and ineligibility (key
    unknown → conservative, §3.3) — never a silent pass. Collects ALL failing reasons (not
    short-circuit) so the audit view is complete.
    """
    reasons = []
    ticker = row.get("ticker") if isinstance(row, dict) else None
    if not (isinstance(row, dict)):
        return {"ticker": None, "eligible": False, "reasons": ["row_not_dict"]}
    if not (isinstance(ticker, str) and ticker.strip()):
        reasons.append("ticker_unknown_or_invalid")

    exch = row.get("exchange")
    if not isinstance(exch, str) or not exch:
        reasons.append("exchange_unknown_or_invalid")
    elif exch not in governance["exchange_whitelist"]:
        reasons.append("exchange_not_whitelisted")

    th = governance["cheap_eligibility_thresholds"]
    for field in _REQUIRED_ROW_NUMERIC:
        val = row.get(field)
        if not _is_finite_number(val):
            reasons.append(f"{field}_unknown_or_invalid")
        elif float(val) < th[_FLOOR_OF[field]]:
            reasons.append(f"{field}_below_floor")

    for flag in governance["disqualifying_status_flags"]:
        if flag not in row or not isinstance(row[flag], bool):
            # absent OR non-bool critical status -> conservative unknown (§3.3); NEVER clean by
            # omission (uniform with the numeric fields above — absence always fails closed).
            reasons.append(f"status_{flag}_unknown_or_invalid")
        elif row[flag] is True:
            reasons.append(f"status_{flag}")
        # row[flag] is False -> confirmed clean

    return {"ticker": ticker, "eligible": not reasons, "reasons": reasons}
