# -*- coding: utf-8 -*-
"""Tests for US-short §13 lifecycle eval slices 1+2a (engine/us_short_lifecycle_eval.py).

Covers: §13 coverage insurance (every §13.1 item enrolled, dynamic count, no missing/extra/duplicate);
the GOVERNED due — each item's threshold is DERIVED from us_short_lifecycle_threshold_authority by number,
so the mutable register cannot self-author / lower its bar (R-USSHORT-BATCH3-R2-LIFECYCLE-THRESHOLD-SELF-
AUTHORING-BYPASS); category-aware due (secondary required only when the governed category requires it);
§12.2② upgrade-eligibility needs a frozen margin; §13.1 title cross-ref; authority integrity; PIT as_of;
and fail-closed (never raises) on malformed / unhashable input. Slice 2a: live_forward_count DERIVED from a
dated forward_observations ledger (no bare self-authored count; strict-real-date keys; weeks-type 0/1 per
decision_date so one run can't forge N weeks) + accumulate_lifecycle_observation (idempotent by decision_date
per §2.1, pure, clean-in→clean-out, fails closed on malformed input / not-clean base/result).
"""
import copy
import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_lifecycle_eval as lc  # noqa: E402

CALIBRATION = json.loads((ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json").read_text(encoding="utf-8"))
AUTHORITY = json.loads((ROOT / "presets" / "us_short_lifecycle_threshold_authority_20260622.json").read_text(encoding="utf-8"))
CAT_TH = AUTHORITY["category_thresholds"]
ITEM_CAT = AUTHORITY["item_category"]
GOV_TITLE = {g["number"]: g["title"] for g in CALIBRATION["calibration_items"]}

# representative items: #1 = "scoring weight" (min 12, secondary NOT required); #7 = "hard_veto candidate"
# (min 10, secondary required) — pinned via assertions so the test stays honest if the priors are refined
NONSEC_NUM, NONSEC_MIN = 1, 12
SEC_NUM, SEC_MIN = 7, 10


def _gov(number):
    return CAT_TH[ITEM_CAT[str(number)]]


def _weekly_dates(n):
    """n distinct strict-real weekly decision_dates (Mondays from 2026-01-05) — one per live-forward week."""
    base = date(2026, 1, 5)  # a Monday
    return [(base + timedelta(weeks=i)).strftime("%Y%m%d") for i in range(n)]


def _item(number, live_forward_count=0, secondary_condition_met=False, upgrade_margin_frozen=False):
    gov = _gov(number)
    due = (live_forward_count >= gov["min_count"]) and (secondary_condition_met or not gov["secondary_required"])
    # the dated forward_observations ledger sums to live_forward_count (1 per distinct week → satisfies a
    # weeks-type category's 0/1 rule AND sums correctly for triggers/samples)
    return {"number": number, "title": GOV_TITLE[number],
            "forward_observations": {d: 1 for d in _weekly_dates(live_forward_count)},
            "secondary_condition_met": secondary_condition_met,
            "upgrade_margin_frozen": upgrade_margin_frozen, "due": due}


def _full_register(as_of="20260622"):
    return {"schema_name": "us_short_lifecycle_register", "schema_version": "1.0.0", "as_of": as_of,
            "items": [_item(g["number"]) for g in CALIBRATION["calibration_items"]]}


def _idx(number):
    return number - 1  # items are built in §13.1 order 1..39


class FixtureSanity(unittest.TestCase):
    def test_priors_match_what_the_tests_assume(self):
        self.assertEqual(_gov(NONSEC_NUM), {"count_type": "weeks", "min_count": NONSEC_MIN, "secondary_required": False})
        self.assertEqual(_gov(SEC_NUM), {"count_type": "triggers", "min_count": SEC_MIN, "secondary_required": True})


class ValidBaseline(unittest.TestCase):
    def test_full_register_is_clean(self):
        out = lc.validate_lifecycle_register(_full_register())
        self.assertTrue(out["clean"], out["violations"])

    def test_evaluate_clean_baseline_no_due(self):
        res = lc.evaluate_lifecycle(_full_register())
        self.assertEqual(res["total_items"], 39)
        self.assertEqual(res["due_count"], 0)


class GovernedDue(unittest.TestCase):
    def test_non_secondary_due_at_governed_min(self):
        reg = _full_register()
        reg["items"][_idx(NONSEC_NUM)] = _item(NONSEC_NUM, live_forward_count=NONSEC_MIN)  # no secondary needed
        self.assertTrue(lc.validate_lifecycle_register(reg)["clean"])
        self.assertIn(NONSEC_NUM, lc.evaluate_lifecycle(reg)["due_items"])

    def test_non_secondary_below_min_not_due(self):
        reg = _full_register()
        reg["items"][_idx(NONSEC_NUM)] = _item(NONSEC_NUM, live_forward_count=NONSEC_MIN - 1)
        self.assertTrue(lc.validate_lifecycle_register(reg)["clean"])
        self.assertNotIn(NONSEC_NUM, lc.evaluate_lifecycle(reg)["due_items"])

    def test_secondary_category_needs_secondary(self):
        reg = _full_register()
        reg["items"][_idx(SEC_NUM)] = _item(SEC_NUM, live_forward_count=SEC_MIN, secondary_condition_met=False)
        self.assertTrue(lc.validate_lifecycle_register(reg)["clean"])
        self.assertNotIn(SEC_NUM, lc.evaluate_lifecycle(reg)["due_items"])  # count met but secondary missing
        reg["items"][_idx(SEC_NUM)] = _item(SEC_NUM, live_forward_count=SEC_MIN, secondary_condition_met=True)
        self.assertTrue(lc.validate_lifecycle_register(reg)["clean"])
        self.assertIn(SEC_NUM, lc.evaluate_lifecycle(reg)["due_items"])


class SelfAuthoringBlocked(unittest.TestCase):
    """The register carries NO threshold metadata; the threshold is governed → it cannot self-lower its bar."""

    def test_smuggled_threshold_min_count_rejected(self):
        reg = _full_register()
        reg["items"][0]["threshold_min_count"] = 1  # additionalProperties:false rejects it
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])

    def test_smuggled_threshold_category_rejected(self):
        reg = _full_register()
        reg["items"][0]["threshold_category"] = "provider fallback"
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])

    def test_smuggled_count_type_rejected(self):
        reg = _full_register()
        reg["items"][0]["count_type"] = "samples"
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])

    def test_cannot_be_due_below_governed_min(self):
        # set due=True with a derived count far below the governed min — the governed invariant rejects it
        reg = _full_register()
        reg["items"][_idx(NONSEC_NUM)]["forward_observations"] = {"20260105": 1}
        reg["items"][_idx(NONSEC_NUM)]["due"] = True
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])

    def test_smuggled_bare_live_forward_count_rejected(self):
        # the count is DERIVED from forward_observations — a bare stored count is no longer a field;
        # additionalProperties:false rejects smuggling it back to self-author a count without dated evidence
        reg = _full_register()
        reg["items"][0]["live_forward_count"] = 99
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])


class DueConsistency(unittest.TestCase):
    def test_due_true_when_should_be_false(self):
        reg = _full_register()  # all counts 0 → all due False
        reg["items"][0]["due"] = True
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])

    def test_due_false_when_should_be_true(self):
        reg = _full_register()
        reg["items"][_idx(NONSEC_NUM)] = _item(NONSEC_NUM, live_forward_count=NONSEC_MIN)
        reg["items"][_idx(NONSEC_NUM)]["due"] = False  # should be True
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])


class UpgradeEligibility(unittest.TestCase):
    def test_due_with_frozen_margin_is_upgrade_eligible(self):
        reg = _full_register()
        reg["items"][_idx(NONSEC_NUM)] = _item(NONSEC_NUM, live_forward_count=NONSEC_MIN, upgrade_margin_frozen=True)
        self.assertIn(NONSEC_NUM, lc.evaluate_lifecycle(reg)["upgrade_eligible_items"])

    def test_due_without_frozen_margin_is_not_upgrade_eligible(self):  # §12.2②
        reg = _full_register()
        reg["items"][_idx(NONSEC_NUM)] = _item(NONSEC_NUM, live_forward_count=NONSEC_MIN, upgrade_margin_frozen=False)
        res = lc.evaluate_lifecycle(reg)
        self.assertIn(NONSEC_NUM, res["due_items"])
        self.assertEqual(res["upgrade_eligible_items"], [])


class AuthorityIntegrity(unittest.TestCase):
    def test_authority_missing_item_fails(self):
        auth = copy.deepcopy(AUTHORITY)
        del auth["item_category"]["5"]
        self.assertFalse(lc.validate_lifecycle_register(_full_register(), authority=auth)["clean"])

    def test_authority_categories_must_equal_the_7_s132(self):
        auth = copy.deepcopy(AUTHORITY)
        auth["category_thresholds"]["surprise_category"] = {"count_type": "weeks", "min_count": 12, "secondary_required": False}
        self.assertFalse(lc.validate_lifecycle_register(_full_register(), authority=auth)["clean"])

    def test_authority_item_mapped_to_nongoverned_category_fails(self):
        auth = copy.deepcopy(AUTHORITY)
        auth["item_category"]["1"] = "not a real category"
        self.assertFalse(lc.validate_lifecycle_register(_full_register(), authority=auth)["clean"])

    def test_authority_malformed_threshold_fails(self):
        auth = copy.deepcopy(AUTHORITY)
        auth["category_thresholds"]["scoring weight"] = {"count_type": "years", "min_count": 12, "secondary_required": False}
        self.assertFalse(lc.validate_lifecycle_register(_full_register(), authority=auth)["clean"])

    def test_real_authority_covers_all_39_in_vocab(self):  # positive control: the shipped authority is integral
        mapped = {int(k) for k in ITEM_CAT}
        self.assertEqual(mapped, set(range(1, 40)))
        self.assertTrue(set(ITEM_CAT.values()) <= set(CAT_TH))
        self.assertEqual(set(CAT_TH), {row["object"] for row in CALIBRATION["default_reminder_thresholds"]})


class CoverageInsurance(unittest.TestCase):
    def test_missing_item_fails(self):
        reg = _full_register()
        reg["items"] = [it for it in reg["items"] if it["number"] != 5]
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])

    def test_extra_item_fails(self):
        reg = _full_register()
        reg["items"].append(_full_register()["items"][0])  # adds a duplicate / out-of-set entry
        reg["items"][-1]["number"] = 99
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])

    def test_duplicate_item_fails(self):
        reg = _full_register()
        reg["items"].append(copy.deepcopy(reg["items"][0]))
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])


class RuntimeAuthorityDrift(unittest.TestCase):
    """The authority is a FROZEN contract: validate_lifecycle_register validates the loaded/injected
    authority against its schema at RUNTIME (the 7 thresholds AND the full 39-entry item_category map are
    const-pinned), so a same-shape remap or a lowered threshold fails the CLEAN GATE — not only the schema
    suite (R-USSHORT-BATCH3-R2-LIFECYCLE-AUTHORITY-SAME-SHAPE-DRIFT-BYPASS)."""

    def test_remapping_a_trigger_item_to_scoring_weight_fails(self):
        # #6 price_engine / #7 hard_veto / #9 provider / #22 future_event / #30 lifecycle-cluster -> no-secondary 12wk
        for num in (6, 7, 9, 22, 30):
            auth = copy.deepcopy(AUTHORITY)
            auth["item_category"][str(num)] = "scoring weight"
            self.assertFalse(lc.validate_lifecycle_register(_full_register(), authority=auth)["clean"], "remap #%d not rejected" % num)

    def test_lowering_a_category_threshold_fails_at_runtime(self):
        auth = copy.deepcopy(AUTHORITY)
        auth["category_thresholds"]["scoring weight"] = {"count_type": "weeks", "min_count": 1, "secondary_required": False}
        self.assertFalse(lc.validate_lifecycle_register(_full_register(), authority=auth)["clean"])

    def test_shipped_authority_is_clean(self):  # positive control
        self.assertTrue(lc.validate_lifecycle_register(_full_register())["clean"])


class Integrity(unittest.TestCase):
    def test_title_mismatch_fails(self):
        reg = _full_register()
        reg["items"][0]["title"] = "WRONG TITLE"
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])

    def test_impossible_as_of_fails(self):
        self.assertFalse(lc.validate_lifecycle_register(_full_register(as_of="20260231"))["clean"])

    def test_missing_as_of_fails(self):
        reg = _full_register()
        reg.pop("as_of")
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])


class MalformedFailsClosed(unittest.TestCase):
    def test_non_dict_or_non_list_items_fails_closed(self):
        for bad in (None, "x", 5, {"items": "nope"}):
            self.assertFalse(lc.validate_lifecycle_register(bad)["clean"], repr(bad))

    def test_unhashable_number_fails_closed_no_raise(self):
        # R-USSHORT-BATCH3-R2-LIFECYCLE-MALFORMED-INPUT-RAISES: a list/dict number is used as a set key →
        # must fail CLOSED, never raise TypeError
        for bad_num in ([1], {"x": 1}):
            reg = _full_register()
            reg["items"][0]["number"] = bad_num
            self.assertFalse(lc.validate_lifecycle_register(reg)["clean"], repr(bad_num))

    def test_item_not_a_dict_fails_closed(self):
        reg = _full_register()
        reg["items"][0] = "not a dict"
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])


class EvalRefusesNotClean(unittest.TestCase):
    def test_evaluate_raises_on_not_clean(self):
        reg = _full_register()
        reg["items"] = [it for it in reg["items"] if it["number"] != 5]
        with self.assertRaises(lc.LifecycleRegisterError):
            lc.evaluate_lifecycle(reg)

    def test_evaluate_refuses_unhashable_without_raw_typeerror(self):
        reg = _full_register()
        reg["items"][0]["number"] = ["bad"]
        with self.assertRaises(lc.LifecycleRegisterError):  # NOT a raw TypeError
            lc.evaluate_lifecycle(reg)


class DerivedForwardCount(unittest.TestCase):
    """live_forward_count is DERIVED from the dated forward_observations ledger (§2.1)."""

    def test_count_is_sum_of_dated_contributions(self):
        reg = _full_register()
        reg["items"][_idx(NONSEC_NUM)] = _item(NONSEC_NUM, live_forward_count=NONSEC_MIN)
        self.assertEqual(len(reg["items"][_idx(NONSEC_NUM)]["forward_observations"]), NONSEC_MIN)
        self.assertTrue(lc.validate_lifecycle_register(reg)["clean"])
        self.assertIn(NONSEC_NUM, lc.evaluate_lifecycle(reg)["due_items"])

    def test_weeks_item_rejects_multi_contribution_in_one_date(self):
        # a weeks-type category: one decision_date may contribute at most 1 (no single-run week forging)
        reg = _full_register()
        item = reg["items"][_idx(NONSEC_NUM)]
        item["forward_observations"] = {"20260105": NONSEC_MIN}  # would forge 12 weeks from one run
        item["due"] = True
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])

    def test_triggers_item_allows_multi_contribution_in_one_date(self):
        # a triggers-type category (#7) counts events, so >1 per decision_date is legitimate
        reg = _full_register()
        reg["items"][_idx(SEC_NUM)] = {"number": SEC_NUM, "title": GOV_TITLE[SEC_NUM],
                                       "forward_observations": {"20260105": SEC_MIN}, "secondary_condition_met": True,
                                       "upgrade_margin_frozen": False, "due": True}
        out = lc.validate_lifecycle_register(reg)
        self.assertTrue(out["clean"], out["violations"])
        self.assertIn(SEC_NUM, lc.evaluate_lifecycle(reg)["due_items"])

    def test_non_real_date_key_rejected(self):
        reg = _full_register()
        reg["items"][0]["forward_observations"] = {"20260231": 1}  # passes the 8-digit pattern, not a real date
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])

    def test_negative_contribution_rejected(self):
        reg = _full_register()
        reg["items"][0]["forward_observations"] = {"20260105": -1}
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])

    def test_bool_contribution_rejected(self):
        reg = _full_register()
        reg["items"][0]["forward_observations"] = {"20260105": True}  # bool is not an integer contribution
        self.assertFalse(lc.validate_lifecycle_register(reg)["clean"])


class AccumulateIdempotent(unittest.TestCase):
    """accumulate_lifecycle_observation: idempotent by decision_date, pure, clean-in→clean-out (§2.1)."""

    def test_apply_same_date_twice_does_not_double_count(self):
        reg = _full_register(as_of="20260105")
        reg1 = lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": 1}})
        reg2 = lc.accumulate_lifecycle_observation(reg1, decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": 1}})
        self.assertEqual(lc._derive_count(reg1["items"][_idx(NONSEC_NUM)]), 1)
        self.assertEqual(lc._derive_count(reg2["items"][_idx(NONSEC_NUM)]), 1)  # NOT 2 — re-run overwrote, didn't add

    def test_distinct_dates_accumulate_and_advance_as_of(self):
        reg = _full_register(as_of="20260105")
        reg = lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": 1}})
        reg = lc.accumulate_lifecycle_observation(reg, decision_date="20260119", observations={NONSEC_NUM: {"forward_contribution": 1}})
        self.assertEqual(lc._derive_count(reg["items"][_idx(NONSEC_NUM)]), 2)
        self.assertEqual(reg["as_of"], "20260119")

    def test_overwrite_corrects_a_week(self):
        reg = _full_register(as_of="20260105")
        reg = lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": 1}})
        reg = lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": 0}})
        self.assertEqual(lc._derive_count(reg["items"][_idx(NONSEC_NUM)]), 0)

    def test_accumulating_governed_weeks_makes_item_due(self):
        reg = _full_register(as_of="20260105")
        for d in _weekly_dates(NONSEC_MIN):
            reg = lc.accumulate_lifecycle_observation(reg, decision_date=d, observations={NONSEC_NUM: {"forward_contribution": 1}})
        self.assertTrue(lc.validate_lifecycle_register(reg)["clean"])
        self.assertIn(NONSEC_NUM, lc.evaluate_lifecycle(reg)["due_items"])

    def test_sets_secondary_and_margin_for_upgrade_eligibility(self):
        reg = _full_register(as_of="20260105")
        # a triggers item (#7): one decision_date can carry its full trigger count; secondary + margin set together
        reg = lc.accumulate_lifecycle_observation(reg, decision_date="20260112",
            observations={SEC_NUM: {"forward_contribution": SEC_MIN, "secondary_condition_met": True, "upgrade_margin_frozen": True}})
        res = lc.evaluate_lifecycle(reg)
        self.assertIn(SEC_NUM, res["due_items"])
        self.assertIn(SEC_NUM, res["upgrade_eligible_items"])

    def test_input_register_not_mutated(self):
        reg = _full_register(as_of="20260105")
        snapshot = copy.deepcopy(reg)
        lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": 1}})
        self.assertEqual(reg, snapshot)  # pure — original untouched

    def test_untouched_items_preserved(self):
        reg = _full_register(as_of="20260105")
        out = lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": 1}})
        self.assertEqual(out["items"][_idx(SEC_NUM)]["forward_observations"], {})

    def test_as_of_does_not_go_backward_on_backfill(self):
        reg = _full_register(as_of="20260301")
        out = lc.accumulate_lifecycle_observation(reg, decision_date="20260105", observations={NONSEC_NUM: {"forward_contribution": 1}})
        self.assertEqual(out["as_of"], "20260301")  # an older backfill date keeps the latest as_of


class AccumulateFailsClosed(unittest.TestCase):
    def test_bad_decision_date_raises(self):
        reg = _full_register(as_of="20260105")
        for bad in ("20260231", "2026", 5, None, "2026-01-05"):
            with self.assertRaises(lc.LifecycleObservationError):
                lc.accumulate_lifecycle_observation(reg, decision_date=bad, observations={NONSEC_NUM: {"forward_contribution": 1}})

    def test_observation_for_unenrolled_item_raises(self):
        reg = _full_register(as_of="20260105")
        with self.assertRaises(lc.LifecycleObservationError):
            lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations={999: {"forward_contribution": 1}})

    def test_negative_contribution_raises(self):
        reg = _full_register(as_of="20260105")
        with self.assertRaises(lc.LifecycleObservationError):
            lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": -1}})

    def test_weeks_forge_via_accumulate_raises(self):
        # a weeks-type item: contribution > 1 in one decision_date fails the clean gate → the producer raises
        reg = _full_register(as_of="20260105")
        with self.assertRaises(lc.LifecycleObservationError):
            lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": 2}})

    def test_non_bool_flag_raises(self):
        reg = _full_register(as_of="20260105")
        with self.assertRaises(lc.LifecycleObservationError):
            lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations={NONSEC_NUM: {"secondary_condition_met": "yes"}})

    def test_non_dict_observation_value_raises(self):
        reg = _full_register(as_of="20260105")
        with self.assertRaises(lc.LifecycleObservationError):
            lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations={NONSEC_NUM: "nope"})

    def test_refuses_not_clean_base(self):
        reg = _full_register(as_of="20260105")
        reg["items"] = [it for it in reg["items"] if it["number"] != 5]  # coverage gap → not-clean base
        with self.assertRaises(lc.LifecycleObservationError):
            lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": 1}})

    def test_non_dict_observations_arg_raises(self):
        reg = _full_register(as_of="20260105")
        with self.assertRaises(lc.LifecycleObservationError):
            lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations="nope")


class AccumulateClosedWorldKeys(unittest.TestCase):
    """R-USSHORT-BATCH3-R2-LIFECYCLE-MALFORMED-INPUT-EDGES finding 1: accumulate is closed-world — an
    unknown per-item update key raises BEFORE any mutation (no silent drop / partial apply / undercount)."""

    def test_typo_only_key_raises_and_does_not_mutate(self):
        reg = _full_register(as_of="20260105")
        snap = copy.deepcopy(reg)
        with self.assertRaises(lc.LifecycleObservationError):
            lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution_typo": 1}})
        self.assertEqual(reg, snap)

    def test_valid_plus_extra_key_raises_before_partial_apply(self):
        reg = _full_register(as_of="20260105")
        snap = copy.deepcopy(reg)
        with self.assertRaises(lc.LifecycleObservationError):
            lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": 1, "unexpected": 123}})
        self.assertEqual(reg, snap)  # the valid field must NOT have been partially applied

    def test_extra_boolean_like_flag_raises(self):
        reg = _full_register(as_of="20260105")
        with self.assertRaises(lc.LifecycleObservationError):
            lc.accumulate_lifecycle_observation(reg, decision_date="20260112", observations={NONSEC_NUM: {"secondary_condition_met": False, "extra_flag": True}})


class AuthorityMalformedFailsClosed(unittest.TestCase):
    """Finding 2: malformed authority values fail the clean gate WITHOUT a raw TypeError, and accumulate
    refuses the same bad authority through LifecycleObservationError (the unhashable-membership class swept
    across the validator — item_category values, category_thresholds.count_type, AND the calibration legs)."""

    def _bad_authorities(self):
        outs = []
        for badval in (["bad"], {"bad": 1}):
            a = copy.deepcopy(AUTHORITY); a["item_category"]["1"] = badval; outs.append(("item_category[1]=%r" % (badval,), a))
            a = copy.deepcopy(AUTHORITY); a["category_thresholds"]["scoring weight"]["count_type"] = badval; outs.append(("count_type=%r" % (badval,), a))
        return outs

    def test_validate_fails_closed_no_typeerror(self):
        for label, auth in self._bad_authorities():
            try:
                out = lc.validate_lifecycle_register(_full_register(), authority=auth)
            except TypeError as e:
                self.fail("raw TypeError for %s: %s" % (label, e))
            self.assertFalse(out["clean"], label)

    def test_accumulate_refuses_bad_authority(self):
        for label, auth in self._bad_authorities():
            with self.assertRaises(lc.LifecycleObservationError):
                lc.accumulate_lifecycle_observation(_full_register(as_of="20260105"),
                    decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": 1}}, authority=auth)

    def test_malformed_calibration_value_fails_closed_no_typeerror(self):
        # whole-class sweep: the same unhashable guard covers an injected malformed CALIBRATION (number /
        # §13.2 object), not only the authority — a list number / list object must fail closed, not crash
        for mutate in (
            lambda c: c["calibration_items"][0].__setitem__("number", ["bad"]),
            lambda c: c["default_reminder_thresholds"][0].__setitem__("object", ["bad"]),
        ):
            cal = copy.deepcopy(CALIBRATION); mutate(cal)
            try:
                out = lc.validate_lifecycle_register(_full_register(), calibration=cal)
            except TypeError as e:
                self.fail("raw TypeError on malformed calibration: %s" % e)
            self.assertFalse(out["clean"])


class GovernanceEdgeFailClosed(unittest.TestCase):
    """R-USSHORT-BATCH3-R2-LIFECYCLE-GOVERNANCE-EDGE-FAILCLOSED-GAP: the remaining governance-edge legs —
    a mixed-type authority key must not raw-raise in a diagnostic, and a malformed SCALAR / extra calibration
    row must fail closed (runtime calibration-schema validation), not be silently dropped."""

    def test_mixed_type_authority_key_fails_closed_no_typeerror(self):
        auth = copy.deepcopy(AUTHORITY)
        auth["category_thresholds"][1] = {"count_type": "weeks", "min_count": 12, "secondary_required": False}  # int key among str keys
        try:
            out = lc.validate_lifecycle_register(_full_register(), authority=auth)
        except TypeError as e:
            self.fail("raw TypeError sorting mixed-type authority keys: %s" % e)
        self.assertFalse(out["clean"])

    def test_accumulate_refuses_mixed_type_authority_key(self):
        auth = copy.deepcopy(AUTHORITY)
        auth["category_thresholds"][1] = {"count_type": "weeks", "min_count": 12, "secondary_required": False}
        with self.assertRaises(lc.LifecycleObservationError):
            lc.accumulate_lifecycle_observation(_full_register(as_of="20260105"),
                decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": 1}}, authority=auth)

    def test_malformed_scalar_calibration_number_fails_closed(self):
        cal = copy.deepcopy(CALIBRATION)
        cal["calibration_items"].append({"number": "40", "title": "x"})  # bad SCALAR number (string) + extra row
        self.assertFalse(lc.validate_lifecycle_register(_full_register(), calibration=cal)["clean"])

    def test_malformed_scalar_reminder_object_fails_closed(self):
        cal = copy.deepcopy(CALIBRATION)
        cal["default_reminder_thresholds"].append({"object": 1})  # bad SCALAR object (int)
        self.assertFalse(lc.validate_lifecycle_register(_full_register(), calibration=cal)["clean"])

    def test_accumulate_refuses_malformed_calibration(self):
        cal = copy.deepcopy(CALIBRATION)
        cal["calibration_items"].append({"number": "40", "title": "x"})
        with self.assertRaises(lc.LifecycleObservationError):
            lc.accumulate_lifecycle_observation(_full_register(as_of="20260105"),
                decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": 1}}, calibration=cal)

    def test_shipped_governance_is_clean(self):  # positive control: real calibration + authority stay clean
        self.assertTrue(lc.validate_lifecycle_register(_full_register())["clean"])


class GovernanceOuterContainerFailClosed(unittest.TestCase):
    """R-USSHORT-BATCH3-R2-LIFECYCLE-GOVERNANCE-EDGE-FAILCLOSED-GAP (3rd round, closed STRUCTURALLY): a
    wrong-CONTAINER-type governance object or sub-field must fail closed in validate (clean=False, no raw
    raise) and be refused by accumulate (LifecycleObservationError, never a raw TypeError/AttributeError).
    Whole-class: non-dict cal/auth; non-list calibration_items / default_reminder_thresholds; non-dict
    category_thresholds / item_category."""

    def _bad_cals(self):
        out = [("cal=[]", []), ("cal=str", "x")]
        for field in ("calibration_items", "default_reminder_thresholds"):
            c = copy.deepcopy(CALIBRATION); c[field] = None; out.append(("%s=None" % field, c))
        c = copy.deepcopy(CALIBRATION); c["calibration_items"] = {"bad": 1}; out.append(("calibration_items=dict", c))
        return out

    def _bad_auths(self):
        out = [("auth=[]", [])]
        for field in ("category_thresholds", "item_category"):
            a = copy.deepcopy(AUTHORITY); a[field] = None; out.append(("%s=None" % field, a))
        return out

    def test_validate_outer_container_fails_closed_without_raise(self):
        for label, cal in self._bad_cals():
            try:
                self.assertFalse(lc.validate_lifecycle_register(_full_register(), calibration=cal)["clean"], label)
            except Exception as e:  # noqa: BLE001 — proving NO raw raise of any kind
                self.fail("validate raw-raised on %s: %r" % (label, e))
        for label, auth in self._bad_auths():
            try:
                self.assertFalse(lc.validate_lifecycle_register(_full_register(), authority=auth)["clean"], label)
            except Exception as e:  # noqa: BLE001
                self.fail("validate raw-raised on %s: %r" % (label, e))

    def test_accumulate_refuses_outer_container_via_observation_error(self):
        for label, cal in self._bad_cals():
            with self.assertRaises(lc.LifecycleObservationError, msg=label):
                lc.accumulate_lifecycle_observation(_full_register(as_of="20260105"),
                    decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": 1}}, calibration=cal)
        for label, auth in self._bad_auths():
            with self.assertRaises(lc.LifecycleObservationError, msg=label):
                lc.accumulate_lifecycle_observation(_full_register(as_of="20260105"),
                    decision_date="20260112", observations={NONSEC_NUM: {"forward_contribution": 1}}, authority=auth)

    def test_shipped_governance_still_clean(self):  # positive control: normalization didn't break the happy path
        self.assertTrue(lc.validate_lifecycle_register(_full_register())["clean"])


if __name__ == "__main__":
    unittest.main()
