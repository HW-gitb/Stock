# -*- coding: utf-8 -*-
"""US-short §13 lifecycle calibration eval — slices 1+2a: lifecycle_register contract validator + due scan + idempotent accumulate.

Design authority: docs/us_short_system_design.md §13 / §13.1 / §13.2 / §18.1 #20 / §2.1 (idempotent forward) / §12.2 (anti-self-deception).

These slices freeze + validate the lifecycle_register accumulator, compute the per-week due scan (which
§13.1 calibration items have accumulated enough LIVE-FORWARD observations to be reviewed, and which are
upgrade-eligible because their winning margin is frozen, §12.2②), and APPLY one decision_date's observation
to the register IDEMPOTENTLY (accumulate_lifecycle_observation — §2.1 重跑不重复计数). The remaining
runtime-stage work — PERSIST the register to the gitignored `state/us_short/lifecycle/` dir (behind the
§18.0 P0 private-path guard), render the weekly banner / lifecycle section, reconcile the count into the
weekly report, and fail closed on a stale / misaligned artifact bucket — is the NEXT slice.

Coverage insurance (§13 reminder mechanism): the register MUST enrol EVERY §13.1 calibration item (no
missing / extra / duplicate number) — the item set is read from us_short_lifecycle_calibration_governance
(dynamic count, NOT hardcoded), so no calibration item can silently escape the reminder mechanism. The
§13.2 thresholds are prose, so they are pinned machine-readably (per category) in
us_short_lifecycle_threshold_authority and each item's threshold is DERIVED from that authority by number —
the register carries NO threshold metadata, so it cannot self-author / lower its own bar
(R-USSHORT-BATCH3-R2-LIFECYCLE-THRESHOLD-SELF-AUTHORING-BYPASS). live_forward_count is itself DERIVED — the
sum of a DATED forward_observations ledger (decision_date → contribution), so the count cannot be
self-authored without dated evidence and a re-run of the same decision_date is idempotent; for a weeks-type
category each contribution must be 0 or 1 (one decision_date = at most one week, no single-run week forging).
`due` is the welded GOVERNED invariant `derived_count >= governed_min_count AND (secondary_condition_met OR
NOT governed_secondary_required)`.

Pure / offline: reads only the tracked register schema + §13.1 governance preset; persists nothing here —
the persister + §18.0 private-path guard + stale-load fail-closed are in engine/us_short_lifecycle_store.py
(slice 2b); the honest banner / weekly reconcile / readiness artifact are the next slice (2c). Malformed
register input fails closed (validate never raises); accumulate raises on malformed input or a not-clean
base/result (a producer never emits a not-clean accumulator).
"""
from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
_REGISTER_SCHEMA = ROOT / "schemas" / "us_short_lifecycle_register.schema.json"
_CALIBRATION_PRESET = ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json"
_AUTHORITY_PRESET = ROOT / "presets" / "us_short_lifecycle_threshold_authority_20260622.json"
_AUTHORITY_SCHEMA = ROOT / "schemas" / "us_short_lifecycle_threshold_authority.schema.json"
_CALIBRATION_SCHEMA = ROOT / "schemas" / "us_short_lifecycle_calibration_governance.schema.json"

# the register's native observation units (== the schema's count_type enum; triangulated in tests)
COUNT_TYPES = frozenset({"weeks", "samples", "triggers"})

# accumulate is CLOSED-WORLD: a per-item observation update may carry ONLY these keys — an unknown key
# (typo / stale producer field) raises instead of being silently dropped (which would lose a lifecycle
# observation in the undercount direction while reporting success).
_ALLOWED_OBSERVATION_KEYS = frozenset({"forward_contribution", "secondary_condition_met", "upgrade_margin_frozen"})

_CACHE: dict = {}


class LifecycleRegisterError(ValueError):
    """Raised when the eval is asked to scan a register that fails the §13 integrity gate."""


class LifecycleObservationError(ValueError):
    """Raised when accumulate is given malformed input, a not-clean base, or would emit a not-clean result."""


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


def _as_dict(x) -> dict:
    """Fail-closed container coercion: a non-dict governance object/sub-field → {} (so derivation can't
    raw-raise; the schema gate on the RAW input still records the wrong-type drift → clean=False)."""
    return x if isinstance(x, dict) else {}


def _as_list(x) -> list:
    """Fail-closed container coercion: a non-list governance sub-field → [] (so iteration can't raw-raise)."""
    return x if isinstance(x, list) else []


def _derive_count(item) -> int:
    """live_forward_count DERIVED as the sum of the dated forward_observations contributions (type-guarded:
    only non-negative ints count; bool/float/garbage contribute 0 — the schema gate already flags those)."""
    obs = item.get("forward_observations") if isinstance(item, dict) else None
    if not isinstance(obs, dict):
        return 0
    return sum(v for v in obs.values() if _int_not_bool(v) and v >= 0)


def _governed_due(count, secondary, gov) -> bool:
    """Single source of the GOVERNED `due` invariant (used by BOTH validate and accumulate so they cannot
    drift): due == count >= governed_min AND (secondary OR NOT governed_secondary_required)."""
    return (count >= gov["min_count"]) and (bool(secondary) or not gov["secondary_required"])


def validate_lifecycle_register(register, *, calibration=None, authority=None) -> dict:
    """Validate a lifecycle_register against the §13 contract. Returns ``{'clean': bool, 'violations': [...]}``.

    Malformed input fails closed (clean False), never raises. The per-item review threshold is GOVERNED —
    it is DERIVED from the us_short_lifecycle_threshold_authority by number (count_type / min_count /
    secondary_required), so the mutable private register cannot self-author / lower its own bar
    (R-USSHORT-BATCH3-R2-LIFECYCLE-THRESHOLD-SELF-AUTHORING-BYPASS). Pass ``calibration`` / ``authority`` to
    inject governance (tests); by default the frozen presets are read (dynamic item set — coverage is
    anchored to the §13.1 governance, never a hardcoded 39).
    """
    cal_raw = calibration if calibration is not None else _load(_CALIBRATION_PRESET, "cal")
    auth_raw = authority if authority is not None else _load(_AUTHORITY_PRESET, "auth")
    # fail-closed CONTAINER normalization (R-USSHORT-BATCH3-R2-LIFECYCLE-GOVERNANCE-EDGE-FAILCLOSED-GAP):
    # coerce EVERY governance container to a safe shape up front, so a wrong-CONTAINER-type governance object
    # or sub-field (a non-dict cal/auth, a non-list calibration_items / default_reminder_thresholds, a
    # non-dict category_thresholds / item_category) can NOT raw-raise while deriving the lookups below. The
    # schema gates validate the RAW inputs (cal_raw / auth_raw), so the malformed shape is still recorded →
    # clean=False. This closes the malformed-input class STRUCTURALLY (one place) instead of leg-by-leg.
    cal, auth = _as_dict(cal_raw), _as_dict(auth_raw)
    gov_items = _as_list(cal.get("calibration_items"))
    reminder_rows = _as_list(cal.get("default_reminder_thresholds"))
    # build the governance lookups from HASHABLE values only — a malformed (e.g. list/dict) number or
    # category must not be used as a set element / dict key (raw TypeError); it is dropped here and the
    # coverage / membership checks below then record the resulting mismatch as a violation (fail closed).
    gov_numbers = {it.get("number") for it in gov_items if isinstance(it, dict) and _int_not_bool(it.get("number"))}
    gov_title = {it.get("number"): it.get("title") for it in gov_items if isinstance(it, dict) and _int_not_bool(it.get("number"))}
    s132_categories = {row.get("object") for row in reminder_rows if isinstance(row, dict) and isinstance(row.get("object"), str)}
    cat_thresholds = _as_dict(auth.get("category_thresholds"))
    item_category = _as_dict(auth.get("item_category"))

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
    for err in jsonschema.Draft7Validator(auth_schema).iter_errors(auth_raw):
        loc = "/".join(str(p) for p in err.absolute_path) or "authority"
        add("authority/%s" % loc, "threshold-authority schema violation (drift): %s" % err.message)

    # the §13.1/§13.2 calibration governance must ALSO be a schema-valid frozen contract: validate the
    # loaded/injected calibration against its schema so a malformed SCALAR row (bad number/object), an extra
    # row, or schema-const drift fails the clean gate — not silently dropped from the derived governance sets
    # (R-USSHORT-BATCH3-R2-LIFECYCLE-GOVERNANCE-EDGE-FAILCLOSED-GAP). Mirrors the authority runtime validation.
    cal_schema = _load(_CALIBRATION_SCHEMA, "cal_schema")
    for err in jsonschema.Draft7Validator(cal_schema).iter_errors(cal_raw):
        loc = "/".join(str(p) for p in err.absolute_path) or "calibration"
        add("calibration/%s" % loc, "lifecycle-calibration schema violation: %s" % err.message)

    # threshold-authority cross-ref (the schema can't see the separate §13.1/§13.2 governance): the governed
    # categories must equal the §13.2 categories, each with a valid count unit + positive min, and the
    # item→category map must cover the §13.1 numbers with in-vocab categories.
    if not isinstance(cat_thresholds, dict) or (s132_categories and set(cat_thresholds) != s132_categories):
        # sorted(map(str, ...)) so a mixed-type / non-string authority key (e.g. an extra int key) renders
        # the diagnostic without a raw `'<' not supported between int and str` TypeError
        add("authority.category_thresholds", "governed categories %s != the §13.2 categories %s"
            % (sorted(map(str, cat_thresholds)) if isinstance(cat_thresholds, dict) else cat_thresholds, sorted(s132_categories)))
    for cat, th in (cat_thresholds.items() if isinstance(cat_thresholds, dict) else []):
        # isinstance(count_type, str) guards the `in COUNT_TYPES` membership against an unhashable value
        if not (isinstance(th, dict) and isinstance(th.get("count_type"), str) and th.get("count_type") in COUNT_TYPES
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
            # a non-string (e.g. list/dict) category value is itself a violation AND must not be used as an
            # unhashable membership key — `not isinstance(v, str)` short-circuits before `v not in cat_thresholds`
            if isinstance(cat_thresholds, dict) and (not isinstance(v, str) or v not in cat_thresholds):
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
        # forward_observations ledger: the keys must be strict real decision_dates and — for a weeks-type
        # governed category — each contribution must be 0 or 1 (one decision_date = at most one week, so a
        # single run can NOT forge N weeks, §2.1). live_forward_count is then DERIVED from the ledger.
        obs = it.get("forward_observations")
        if isinstance(obs, dict):
            gov_count_type = gov.get("count_type") if isinstance(gov, dict) else None
            for d, contrib in obs.items():
                if not _strict_yyyymmdd(d):
                    add(wid, "forward_observations key %r is not a strict real YYYYMMDD decision_date" % (d,))
                if gov_count_type == "weeks" and _int_not_bool(contrib) and contrib not in (0, 1):
                    add(wid, "weeks-type item #%s decision_date %r contributes %r (must be 0 or 1 — one run can't forge a week)"
                        % (num, d, contrib))
        cnt, sec, due = _derive_count(it), it.get("secondary_condition_met"), it.get("due")
        if not isinstance(gov, dict):
            add(wid, "no governed threshold for item #%s (category %r not in the authority)" % (num, gov_cat))
        elif (isinstance(sec, bool) and isinstance(due, bool)
              and _int_not_bool(gov.get("min_count")) and isinstance(gov.get("secondary_required"), bool)):
            expected = _governed_due(cnt, sec, gov)
            if due is not expected:
                add(wid, "due %r != governed (derived_count=%r>=%r AND (secondary OR not secondary_required=%r))=%r"
                    % (due, cnt, gov["min_count"], gov["secondary_required"], expected))

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


def accumulate_lifecycle_observation(register, *, decision_date, observations, calibration=None, authority=None) -> dict:
    """Apply ONE decision_date's live-forward observation to a §13-clean register → a NEW §13-clean register.

    IDEMPOTENT by decision_date (§2.1 幂等不灌前向证据 / 重跑不重复计数): each touched item's
    ``forward_observations[decision_date]`` is SET (overwrite), never added, so re-running the same
    decision_date does not double-count. ``observations`` maps an enrolled §13.1 item number → an update dict
    ``{"forward_contribution"?: int>=0, "secondary_condition_met"?: bool, "upgrade_margin_frozen"?: bool}`` —
    CLOSED-WORLD: an unknown update key (typo / stale producer field) RAISES before any mutation, so an
    observation can never be silently dropped or partially applied. An item absent from the map is left
    untouched; an item present with no ``forward_contribution`` keeps its ledger (only its booleans change).
    The derived count + GOVERNED ``due`` are recomputed from the authority
    (single-source ``_governed_due``). ``as_of`` advances to max(old, decision_date) — a backfill never moves
    it backward.

    Returns a NEW register (the input is NOT mutated). Clean-in → clean-out: it REFUSES a not-clean base and
    RAISES ``LifecycleObservationError`` on malformed input or if the result is not §13-clean — a producer
    never emits (or launders) a not-clean accumulator (e.g. a weeks-type forge of contribution > 1 fails the
    clean gate and raises). Pure / offline: no persist (that is the next slice).
    """
    if not _strict_yyyymmdd(decision_date):
        raise LifecycleObservationError("decision_date %r is not a strict real YYYYMMDD" % (decision_date,))
    if not isinstance(observations, dict):
        raise LifecycleObservationError("observations must be a dict of {item_number: update}")
    if not isinstance(register, dict) or not isinstance(register.get("items"), list):
        raise LifecycleObservationError("register must be a dict with an items list")

    # clean-in: refuse to accumulate onto a not-clean base (so a forged base can't be laundered into a clean
    # result — due is recomputed below, which would otherwise mask a hand-tampered due/coverage gap).
    base = validate_lifecycle_register(register, calibration=calibration, authority=authority)
    if not base["clean"]:
        raise LifecycleObservationError(
            "refusing to accumulate onto a not-clean base register; first violations: %s" % (base["violations"][:5],)
        )

    auth = authority if authority is not None else _load(_AUTHORITY_PRESET, "auth")
    cat_thresholds = auth.get("category_thresholds", {}) if isinstance(auth, dict) else {}
    item_category = auth.get("item_category", {}) if isinstance(auth, dict) else {}

    new = copy.deepcopy(register)
    by_number = {it["number"]: it for it in new["items"] if isinstance(it, dict) and _int_not_bool(it.get("number"))}

    for raw_num, upd in observations.items():
        if not _int_not_bool(raw_num):
            raise LifecycleObservationError("observation item number %r must be an int" % (raw_num,))
        if raw_num not in by_number:
            raise LifecycleObservationError("observation for item #%s, which is not enrolled in the register" % (raw_num,))
        if not isinstance(upd, dict):
            raise LifecycleObservationError("observation for item #%s must be a dict" % (raw_num,))
        extra_keys = set(upd) - _ALLOWED_OBSERVATION_KEYS
        if extra_keys:  # closed-world: reject unknown keys BEFORE any partial mutation for this item
            raise LifecycleObservationError(
                "observation for item #%s has unknown update key(s) %s (allowed: %s)"
                % (raw_num, sorted(map(str, extra_keys)), sorted(_ALLOWED_OBSERVATION_KEYS)))
        item = by_number[raw_num]
        if "forward_contribution" in upd:
            contrib = upd["forward_contribution"]
            if not _int_not_bool(contrib) or contrib < 0:
                raise LifecycleObservationError(
                    "forward_contribution for item #%s must be a non-negative int, got %r" % (raw_num, contrib))
            obs = item.get("forward_observations")
            if not isinstance(obs, dict):
                obs = item["forward_observations"] = {}
            obs[decision_date] = contrib  # SET (overwrite), not add → idempotent by decision_date (§2.1)
        for flag in ("secondary_condition_met", "upgrade_margin_frozen"):
            if flag in upd:
                if not isinstance(upd[flag], bool):
                    raise LifecycleObservationError("%s for item #%s must be a bool, got %r" % (flag, raw_num, upd[flag]))
                item[flag] = upd[flag]

    old_as_of = register.get("as_of")
    new["as_of"] = max(old_as_of, decision_date) if isinstance(old_as_of, str) and _strict_yyyymmdd(old_as_of) else decision_date

    # recompute the GOVERNED due for every item from the authority (single-source invariant) so the result
    # re-validates clean — a weeks-type forge or a below-min count produces the correct due / a clean-gate fail.
    for it in new["items"]:
        if not (isinstance(it, dict) and _int_not_bool(it.get("number"))):
            continue
        gov_cat = item_category.get(str(it["number"])) if isinstance(item_category, dict) else None
        gov = cat_thresholds.get(gov_cat) if isinstance(cat_thresholds, dict) and isinstance(gov_cat, str) else None
        if isinstance(gov, dict) and _int_not_bool(gov.get("min_count")) and isinstance(gov.get("secondary_required"), bool):
            it["due"] = _governed_due(_derive_count(it), it.get("secondary_condition_met"), gov)

    result = validate_lifecycle_register(new, calibration=calibration, authority=authority)
    if not result["clean"]:
        raise LifecycleObservationError(
            "accumulate would produce a not-clean register; first violations: %s" % (result["violations"][:5],)
        )
    return new
