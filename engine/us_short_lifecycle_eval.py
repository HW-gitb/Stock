# -*- coding: utf-8 -*-
"""US-short §13 lifecycle calibration eval — slice 1: lifecycle_register contract validator + due scan.

Design authority: docs/us_short_system_design.md §13 / §13.1 / §13.2 / §18.1 #20 / §12.2 (anti-self-deception).

This slice freezes + validates the lifecycle_register accumulator and computes the per-week due scan: which
§13.1 calibration items have accumulated enough LIVE-FORWARD observations to be reviewed, and which are
upgrade-eligible because their winning margin is frozen (§12.2②). The runtime STAGE that ACCUMULATES
observations, renders the weekly banner / lifecycle section, reconciles the count into the weekly report,
PERSISTS the register to the gitignored `state/us_short/lifecycle/` dir, and fails closed on a stale /
misaligned artifact bucket is the NEXT slice (it builds on this validated contract).

Coverage insurance (§13 reminder mechanism): the register MUST enrol EVERY §13.1 calibration item (no
missing / extra / duplicate number) — the item set is read from us_short_lifecycle_calibration_governance
(dynamic count, NOT hardcoded), so no calibration item can silently escape the reminder mechanism. The
§13.2 thresholds are prose, so they are pinned machine-readably (per category) in
us_short_lifecycle_threshold_authority and each item's threshold is DERIVED from that authority by number —
the register carries NO threshold metadata, so it cannot self-author / lower its own bar
(R-USSHORT-BATCH3-R2-LIFECYCLE-THRESHOLD-SELF-AUTHORING-BYPASS); `due` is the welded GOVERNED invariant
`live_forward_count >= governed_min_count AND (secondary_condition_met OR NOT governed_secondary_required)`.

Pure / offline: reads only the tracked register schema + §13.1 governance preset; persists nothing here
(the persister + private-path guard land with the runtime-stage slice). Malformed input fails closed.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
_REGISTER_SCHEMA = ROOT / "schemas" / "us_short_lifecycle_register.schema.json"
_CALIBRATION_PRESET = ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json"
_AUTHORITY_PRESET = ROOT / "presets" / "us_short_lifecycle_threshold_authority_20260622.json"
_AUTHORITY_SCHEMA = ROOT / "schemas" / "us_short_lifecycle_threshold_authority.schema.json"

# the register's native observation units (== the schema's count_type enum; triangulated in tests)
COUNT_TYPES = frozenset({"weeks", "samples", "triggers"})

_CACHE: dict = {}


class LifecycleRegisterError(ValueError):
    """Raised when the eval is asked to scan a register that fails the §13 integrity gate."""


def _load(path, key):
    if key not in _CACHE:
        _CACHE[key] = json.loads(Path(path).read_text(encoding="utf-8"))
    return _CACHE[key]


def _strict_yyyymmdd(s) -> bool:
    if not isinstance(s, str) or len(s) != 8 or not s.isascii() or not s.isdigit():
        return False
    try:
        datetime.strptime(s, "%Y%m%d")
        return True
    except ValueError:
        return False


def _int_not_bool(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def validate_lifecycle_register(register, *, calibration=None, authority=None) -> dict:
    """Validate a lifecycle_register against the §13 contract. Returns ``{'clean': bool, 'violations': [...]}``.

    Malformed input fails closed (clean False), never raises. The per-item review threshold is GOVERNED —
    it is DERIVED from the us_short_lifecycle_threshold_authority by number (count_type / min_count /
    secondary_required), so the mutable private register cannot self-author / lower its own bar
    (R-USSHORT-BATCH3-R2-LIFECYCLE-THRESHOLD-SELF-AUTHORING-BYPASS). Pass ``calibration`` / ``authority`` to
    inject governance (tests); by default the frozen presets are read (dynamic item set — coverage is
    anchored to the §13.1 governance, never a hardcoded 39).
    """
    cal = calibration if calibration is not None else _load(_CALIBRATION_PRESET, "cal")
    auth = authority if authority is not None else _load(_AUTHORITY_PRESET, "auth")
    gov_items = cal.get("calibration_items", []) if isinstance(cal, dict) else []
    gov_numbers = {it.get("number") for it in gov_items if isinstance(it, dict)}
    gov_title = {it.get("number"): it.get("title") for it in gov_items if isinstance(it, dict)}
    s132_categories = {row.get("object") for row in cal.get("default_reminder_thresholds", []) if isinstance(row, dict)}
    cat_thresholds = auth.get("category_thresholds", {}) if isinstance(auth, dict) else {}
    item_category = auth.get("item_category", {}) if isinstance(auth, dict) else {}

    violations: list = []

    def add(where, reason):
        violations.append({"where": where, "reason": reason})

    # structural gate: validate the register against its draft-07 schema (wrong types, missing/extra keys —
    # incl a smuggled-back threshold field rejected by additionalProperties:false — schema_name const, as_of
    # shape all fail closed).
    schema = _load(_REGISTER_SCHEMA, "schema")
    for err in jsonschema.Draft7Validator(schema).iter_errors(register):
        loc = "/".join(str(p) for p in err.absolute_path) or "register"
        add(loc, "lifecycle_register schema violation: %s" % err.message)

    # the authority must itself be a FROZEN, schema-valid contract: validate the loaded/injected authority
    # against its draft-07 schema (the 7 category thresholds AND the full 39-entry item_category map are
    # const-pinned), so a same-shape remap or a lowered threshold fails the clean gate at RUNTIME — not only
    # in the separate schema suite (R-USSHORT-BATCH3-R2-LIFECYCLE-AUTHORITY-SAME-SHAPE-DRIFT-BYPASS).
    auth_schema = _load(_AUTHORITY_SCHEMA, "auth_schema")
    for err in jsonschema.Draft7Validator(auth_schema).iter_errors(auth):
        loc = "/".join(str(p) for p in err.absolute_path) or "authority"
        add("authority/%s" % loc, "threshold-authority schema violation (drift): %s" % err.message)

    # threshold-authority cross-ref (the schema can't see the separate §13.1/§13.2 governance): the governed
    # categories must equal the §13.2 categories, each with a valid count unit + positive min, and the
    # item→category map must cover the §13.1 numbers with in-vocab categories.
    if not isinstance(cat_thresholds, dict) or (s132_categories and set(cat_thresholds) != s132_categories):
        add("authority.category_thresholds", "governed categories %s != the §13.2 categories %s"
            % (sorted(cat_thresholds) if isinstance(cat_thresholds, dict) else cat_thresholds, sorted(s132_categories)))
    for cat, th in (cat_thresholds.items() if isinstance(cat_thresholds, dict) else []):
        if not (isinstance(th, dict) and th.get("count_type") in COUNT_TYPES
                and _int_not_bool(th.get("min_count")) and th.get("min_count") >= 1
                and isinstance(th.get("secondary_required"), bool)):
            add("authority.category_thresholds", "category %r has a malformed governed threshold %r" % (cat, th))
    if not isinstance(item_category, dict):
        add("authority.item_category", "item_category is not a dict")
    else:
        mapped = {int(k) for k in item_category if isinstance(k, str) and k.isdigit()}
        if gov_numbers and mapped != gov_numbers:
            add("authority.item_category", "item→category map does not cover the §13.1 numbers — missing %s / extra %s"
                % (sorted(gov_numbers - mapped), sorted(mapped - gov_numbers)))
        for k, v in item_category.items():
            if isinstance(cat_thresholds, dict) and v not in cat_thresholds:
                add("authority.item_category", "item %s mapped to non-governed category %r" % (k, v))

    if not isinstance(register, dict):
        add("register", "lifecycle_register is not a dict")
        return {"clean": not violations, "violations": violations}
    if not _strict_yyyymmdd(register.get("as_of")):
        add("register.as_of", "as_of %r is not a strict real YYYYMMDD PIT anchor" % (register.get("as_of"),))
    items = register.get("items")
    if not isinstance(items, list):
        add("register.items", "items is not a list")
        return {"clean": not violations, "violations": violations}

    seen_numbers: list = []
    for i, it in enumerate(items):
        where = "items[%d]" % i
        if not isinstance(it, dict):
            add(where, "item is not a dict")
            continue
        num = it.get("number")
        # type-guard before using num as a dict/set key — a malformed (unhashable) value fails CLOSED, never raises
        num_ok = isinstance(num, int) and not isinstance(num, bool)
        if not num_ok:
            continue  # jsonschema already recorded the wrong number type; skip number-keyed checks (and coverage flags it missing)
        wid = "item#%s" % (num,)
        seen_numbers.append(num)
        if num in gov_title and it.get("title") != gov_title[num]:
            add(wid, "title %r != §13.1 governance title %r" % (it.get("title"), gov_title[num]))
        # GOVERNED due: derive this item's threshold from the authority by number — the register carries NONE,
        # so it cannot self-lower the bar. due == count >= governed_min AND (secondary OR not governed_secondary_required).
        gov_cat = item_category.get(str(num)) if isinstance(item_category, dict) else None
        gov = cat_thresholds.get(gov_cat) if isinstance(cat_thresholds, dict) and isinstance(gov_cat, str) else None
        cnt, sec, due = it.get("live_forward_count"), it.get("secondary_condition_met"), it.get("due")
        if not isinstance(gov, dict):
            add(wid, "no governed threshold for item #%s (category %r not in the authority)" % (num, gov_cat))
        elif (_int_not_bool(cnt) and isinstance(sec, bool) and isinstance(due, bool)
              and _int_not_bool(gov.get("min_count")) and isinstance(gov.get("secondary_required"), bool)):
            expected = (cnt >= gov["min_count"]) and (sec or not gov["secondary_required"])
            if due is not expected:
                add(wid, "due %r != governed (live_forward_count>=%r AND (secondary OR not secondary_required=%r))=%r"
                    % (due, gov["min_count"], gov["secondary_required"], expected))

    # coverage insurance (§13): the register must enrol EXACTLY the §13.1 numbers — no missing/extra/duplicate
    seen_set = set(seen_numbers)
    if len(seen_numbers) != len(seen_set):
        dups = sorted({n for n in seen_set if seen_numbers.count(n) > 1})
        add("register.items", "duplicate calibration item numbers: %s" % dups)
    if gov_numbers and seen_set != gov_numbers:
        add("register.items",
            "coverage gap vs the §13.1 registry — missing %s / extra %s (every calibration item must be enrolled)"
            % (sorted(gov_numbers - seen_set), sorted(seen_set - gov_numbers)))

    return {"clean": not violations, "violations": violations}


def evaluate_lifecycle(register, *, calibration=None, authority=None) -> dict:
    """Scan a §13-clean lifecycle_register → which items are due / upgrade-eligible (the per-week scan core).

    REFUSES a register that fails ``validate_lifecycle_register`` (raises ``LifecycleRegisterError`` — the
    eval never scans an un-validated accumulator). ``due`` = enough live-forward observations + secondary
    met; ``upgrade_eligible`` ADDITIONALLY requires the §12.2② frozen winning margin (a due item whose
    margin is NOT frozen is reported due but NOT upgrade-eligible — no upgrade may trigger on it). The
    banner text, weekly reconcile, persist, and stale-bucket fail-closed are the next slice.
    """
    result = validate_lifecycle_register(register, calibration=calibration, authority=authority)
    if not result["clean"]:
        raise LifecycleRegisterError(
            "refusing to scan a not-clean lifecycle_register; first violations: %s" % (result["violations"][:5],)
        )
    items = register["items"]
    due_items = sorted(it["number"] for it in items if it["due"])
    upgrade_eligible = sorted(it["number"] for it in items if it["due"] and it["upgrade_margin_frozen"])
    return {
        "as_of": register["as_of"],
        "total_items": len(items),
        "due_count": len(due_items),
        "due_items": due_items,
        "upgrade_eligible_items": upgrade_eligible,
    }
