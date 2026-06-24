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
import re
from datetime import datetime
from pathlib import Path

from engine.us_short_hard_veto import classify_hard_veto  # §5 (reused, NOT re-written) for Pass2

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


# Canonical US listing symbol = strip + uppercase + shape-validate; A-share digit code rejected.
# MIRRORS runners/us_short_account_state_from_manual_tables.py::_parse_us_ticker (a test
# triangulates the two so they cannot drift). Class shares (BRK.B / BRK-A) preserved; the engine
# layer returns canonical-or-None (no runner-specific raise). One identity per security.
_US_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}([.\-][A-Z]{1,3})?$")
_A_SHARE_CODE_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$", re.IGNORECASE)


def _canonical_us_ticker(raw):
    """raw -> canonical US ticker (stripped + uppercased + shape-validated) or None if not a valid
    US listing symbol (blank / wrong shape / A-share digit code all -> None)."""
    if not isinstance(raw, str):
        return None
    s = raw.strip().upper()
    if _A_SHARE_CODE_RE.fullmatch(s) or not _US_TICKER_RE.fullmatch(s):
        return None
    return s


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

    row = {"ticker": str (canonicalized to a US listing symbol — strip+upper+shape),
           "exchange": str, "price"/"adv_usd"/"market_cap_usd": finite number,
           "delisted"/"halted"/"bankruptcy"/"otc": REQUIRED bool (absent or non-bool ->
           conservative unknown, §3.3 — a critical status is NEVER assumed clean by omission)}.
    governance = a dict already passed through validate_eligibility_governance.

    Returns {"ticker", "eligible": bool, "reasons": [str, ...]}. eligible == (reasons == []). The
    returned `ticker` is the CANONICAL form; a non-canonical / A-share-code / blank ticker ->
    `ticker_unknown_or_invalid` + ineligible (the candidate set has ONE identity per security).
    A missing / non-finite / wrong-type field yields an explicit reason and ineligibility (key
    unknown → conservative, §3.3) — never a silent pass. Collects ALL failing reasons (not
    short-circuit) so the audit view is complete.
    """
    reasons = []
    if not isinstance(row, dict):
        return {"ticker": None, "eligible": False, "reasons": ["row_not_dict"]}
    ticker = _canonical_us_ticker(row.get("ticker"))  # strip+upper+shape; None if not a US symbol
    if ticker is None:
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


# ---- Pass2 audit-safety-gate (reuses §5 hard_veto; NO new veto logic, §18.2 build-vs-wire ②) ----
_PASS2_CONTEXTS = ("candidate", "holding")


def pass2_safety_admit(signals, *, row_context):
    """Pass2 audit-safety-gate admit decision over one row, REUSING engine/us_short_hard_veto.

    §4.0: a candidate that fails the audit safety gate does NOT enter Top15; a HOLDING is forced
    into Pass2 (强制含持仓) and is never excluded BY THE GATE — a holding's veto instead drives the
    §9 position action (reduce / clear / re-evaluate) downstream. No new veto logic here: the tier
    comes entirely from `classify_hard_veto`.

    Returns {"admit_to_topn": bool, "veto_tier": str, "effect": str, "reasons": [str, ...],
             "row_context": str}. candidate: admit_to_topn = veto_tier != 'entry_hard_veto';
    holding: admit_to_topn is always True (the veto is surfaced, not used to exclude).
    """
    if row_context not in _PASS2_CONTEXTS:
        raise ValueError(f"row_context 须 ∈ {_PASS2_CONTEXTS}: {row_context!r}")
    v = classify_hard_veto(signals, row_context=row_context)
    admit = True if row_context == "holding" else (v["veto_tier"] != "entry_hard_veto")
    return {"admit_to_topn": admit, "veto_tier": v["veto_tier"], "effect": v["effect"],
            "reasons": list(v["reasons"]), "row_context": row_context}


# ---- catalyst_recall injection slot (real market-level feed = batch5, §18.2 build-vs-wire ③) ----
def inject_catalyst_recall(cheap_eligible_tickers, *, recall_feed):
    """Inject catalyst_recall_lane names into the cheap-eligible candidate set (STRUCTURAL slot only).

    §4.0: a market-level feed (recent earnings beats / rating changes / 8-K) pulls catalyst-strong
    but momentum-weak names that the cheap gate alone would miss. The REAL feed is batch5
    (SR-PROVIDER-001); this wires only the injection slot + honest provenance.

    Both `cheap_eligible_tickers` and a non-None `recall_feed` are CANONICALIZED (strip+upper+US-
    symbol-shape) BEFORE any uniqueness check, so case / whitespace variants ('AAPL' / 'aapl' /
    ' AAPL ') collapse to one identity. `candidates` is a UNIQUE set of canonical tickers
    (cheap-eligible first, then recall extras de-duplicated against the base and each other,
    order-preserving).
    recall_feed = None -> candidates (canonical) unchanged + {recall_available: False} (NEVER
                  fabricate coverage when the feed is unavailable, §4.0).
    Returns {"candidates": [...], "recall_available": bool, "recall_added": [...]}.
    Fail-closed (ValueError): a non-list `cheap_eligible_tickers` or non-None/non-list `recall_feed`;
    any non-canonical / A-share-code / blank item; OR a (post-canonical) duplicate base ticker (the
    candidate set must be unique — an upstream duplicate is surfaced, NOT silently de-duped).
    """
    if not isinstance(cheap_eligible_tickers, list):
        raise ValueError("cheap_eligible_tickers 须为 list")
    base = []
    for t in cheap_eligible_tickers:
        c = _canonical_us_ticker(t)
        if c is None:
            raise ValueError(f"cheap_eligible_tickers 含非规范 US ticker（须 strip+大写+合法形、非 A 股码）: {t!r}")
        base.append(c)
    if len(set(base)) != len(base):
        # the candidate set is a SET of canonical tickers, not a row-multiset; a (post-canonical)
        # duplicate base ticker is an upstream defect — surface it, do NOT silently de-dup.
        raise ValueError("cheap_eligible_tickers 含（规范化后）重复 ticker（候选集须唯一；上游重复行须先修，不静默去重以免掩盖缺陷）")
    if recall_feed is None:
        return {"candidates": base, "recall_available": False, "recall_added": []}
    if not isinstance(recall_feed, list):
        raise ValueError("recall_feed 须为 None 或 list（畸形 feed 不当作 no-recall）")
    seen = set(base)
    added = []
    for t in recall_feed:
        c = _canonical_us_ticker(t)
        if c is None:
            raise ValueError(f"recall_feed 含非规范 US ticker: {t!r}")
        if c not in seen:
            seen.add(c)
            added.append(c)
    return {"candidates": base + added, "recall_available": True, "recall_added": added}
