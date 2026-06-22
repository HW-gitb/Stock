# -*- coding: utf-8 -*-
"""Tests for US-short §13 lifecycle eval slice 1 (engine/us_short_lifecycle_eval.py).

Covers: §13 coverage insurance (every §13.1 item enrolled, dynamic count, no missing/extra/duplicate);
the GOVERNED due — each item's threshold is DERIVED from us_short_lifecycle_threshold_authority by number,
so the mutable register cannot self-author / lower its bar (R-USSHORT-BATCH3-R2-LIFECYCLE-THRESHOLD-SELF-
AUTHORING-BYPASS); category-aware due (secondary required only when the governed category requires it);
§12.2② upgrade-eligibility needs a frozen margin; §13.1 title cross-ref; authority integrity; PIT as_of;
and fail-closed (never raises) on malformed / unhashable input.
"""
import copy
import json
import sys
import unittest
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


def _item(number, live_forward_count=0, secondary_condition_met=False, upgrade_margin_frozen=False):
    gov = _gov(number)
    due = (live_forward_count >= gov["min_count"]) and (secondary_condition_met or not gov["secondary_required"])
    return {"number": number, "title": GOV_TITLE[number], "live_forward_count": live_forward_count,
            "secondary_condition_met": secondary_condition_met, "upgrade_margin_frozen": upgrade_margin_frozen, "due": due}


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
        # set due=True with a count far below the governed min — the governed invariant rejects it
        reg = _full_register()
        reg["items"][_idx(NONSEC_NUM)]["live_forward_count"] = 1
        reg["items"][_idx(NONSEC_NUM)]["due"] = True
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


if __name__ == "__main__":
    unittest.main()
