# -*- coding: utf-8 -*-
"""Tests for engine/us_short_catalyst.py (§4.2 catalyst block, 25%).

Pure/offline. Covers the frozen-governance runtime validator (drift fail-closed + module const == preset
triangulation), the rule-mapping bucket mappers (every boundary), the realized-only EXCLUSION rule (future →
§8.1 excluded, unverified date excluded), missing → neutral (§4.2 缺分量), strict numeric/date validation, and
positive/negative clamp controls.
"""
import copy
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_catalyst import (  # noqa: E402
    catalyst_block,
    load_catalyst_governance,
    validate_catalyst_governance,
    CatalystGovernanceError,
    _earnings_points,
    _revision_points,
    _event8k_points,
    _semantic_points,
    _finite_int,
    _parse_yyyymmdd,
    _V1_NEUTRAL,
    _V1_EARNINGS_POINTS,
    _V1_REVISION_POINTS,
    _V1_EVENT8K_POINTS,
    _V1_SEMANTIC_MAX_ABS_POINTS,
    _V1_SCORING_CALIBER_ITEM_ID,
)

_PRESET = ROOT / "presets" / "us_short_catalyst_governance_20260630.json"
GOV = load_catalyst_governance()           # the frozen v1 governance (validated)
AS_OF = "20260630"
PAST = "20260626"                          # <= as_of  → realized
FUTURE = "20260701"                        # >  as_of  → §8.1, excluded


def _big_beat(date=PAST):
    return {"earnings_surprise_pct": 15.0, "earnings_report_date": date}


class TestGovernanceValidation(unittest.TestCase):
    def test_loads_and_validates(self):
        self.assertEqual(GOV["schema_name"], "us_short_catalyst_governance")
        self.assertEqual(validate_catalyst_governance(copy.deepcopy(GOV)), GOV)

    def test_module_const_equals_preset(self):
        # triangulation: the consumer copy cannot silently drift from the committed preset.
        p = json.loads(_PRESET.read_text(encoding="utf-8"))
        self.assertEqual(_V1_NEUTRAL, p["neutral_catalyst_score"])
        self.assertEqual(_V1_EARNINGS_POINTS, p["earnings_surprise"]["points"])
        self.assertEqual(_V1_REVISION_POINTS, p["analyst_revision"]["points"])
        self.assertEqual(_V1_EVENT8K_POINTS, p["event_8k"]["points"])
        self.assertEqual(_V1_SEMANTIC_MAX_ABS_POINTS, p["semantic_advisory"]["max_abs_points"])
        self.assertEqual(_V1_SCORING_CALIBER_ITEM_ID, p["scoring_caliber_calibration_item_id"])

    def _rejects(self, mutate):
        bad = copy.deepcopy(GOV)
        mutate(bad)
        with self.assertRaises(CatalystGovernanceError):
            validate_catalyst_governance(bad)

    def test_rejects_non_dict(self):
        with self.assertRaises(CatalystGovernanceError):
            validate_catalyst_governance("nope")

    def test_rejects_extra_top_key(self):
        self._rejects(lambda c: c.__setitem__("extra", 1))

    def test_rejects_missing_key(self):
        self._rejects(lambda c: c.pop("event_8k"))

    def test_rejects_wrong_schema_name(self):
        self._rejects(lambda c: c.__setitem__("schema_name", "x"))

    def test_rejects_neutral_drift(self):
        self._rejects(lambda c: c.__setitem__("neutral_catalyst_score", 60.0))

    def test_rejects_earnings_point_drift(self):
        self._rejects(lambda c: c["earnings_surprise"]["points"].__setitem__("big_beat", 99.0))

    def test_rejects_earnings_bucket_drift(self):
        self._rejects(lambda c: c["earnings_surprise"]["bucket_bounds_pct"].__setitem__("big_beat_min", 1.0))

    def test_rejects_revision_point_drift(self):
        self._rejects(lambda c: c["analyst_revision"]["points"].__setitem__("strong_positive", 99.0))

    def test_rejects_semantic_cap_widening(self):
        self._rejects(lambda c: c["semantic_advisory"].__setitem__("max_abs_points", 50.0))

    def test_rejects_calibration_anchor_swap(self):
        self._rejects(lambda c: c.__setitem__("scoring_caliber_calibration_item_id", 21))

    def test_rejects_unreal_as_of(self):
        self._rejects(lambda c: c.__setitem__("as_of", "20261399"))


class TestDateParse(unittest.TestCase):
    def test_valid(self):
        self.assertIsNotNone(_parse_yyyymmdd("20260630"))

    def test_unreal_rejected(self):
        self.assertIsNone(_parse_yyyymmdd("20261399"))

    def test_wrong_shape_rejected(self):
        for s in ("2026-06-30", "2026630", None, 20260630, "2026063a"):
            self.assertIsNone(_parse_yyyymmdd(s))


class TestBucketMappers(unittest.TestCase):
    def test_earnings_buckets(self):
        self.assertEqual(_earnings_points(15.0, GOV), 20.0)    # big_beat (>=10)
        self.assertEqual(_earnings_points(10.0, GOV), 20.0)    # boundary
        self.assertEqual(_earnings_points(9.99, GOV), 10.0)    # beat
        self.assertEqual(_earnings_points(2.0, GOV), 10.0)     # beat boundary
        self.assertEqual(_earnings_points(1.99, GOV), 0.0)     # inline
        self.assertEqual(_earnings_points(0.0, GOV), 0.0)      # inline
        self.assertEqual(_earnings_points(-2.0, GOV), -10.0)   # miss boundary
        self.assertEqual(_earnings_points(-9.99, GOV), -10.0)  # miss
        self.assertEqual(_earnings_points(-10.0, GOV), -20.0)  # big_miss boundary (tested before miss)
        self.assertEqual(_earnings_points(-50.0, GOV), -20.0)  # deep miss is big_miss, not mislabelled

    def test_earnings_malformed_is_none(self):
        for bad in (True, float("nan"), float("inf"), "15", None):
            self.assertIsNone(_earnings_points(bad, GOV))

    def test_revision_buckets(self):
        self.assertEqual(_revision_points(5, GOV), 15.0)    # strong_positive
        self.assertEqual(_revision_points(3, GOV), 15.0)    # boundary
        self.assertEqual(_revision_points(2, GOV), 8.0)     # positive
        self.assertEqual(_revision_points(1, GOV), 8.0)     # boundary
        self.assertEqual(_revision_points(0, GOV), 0.0)     # neutral
        self.assertEqual(_revision_points(-1, GOV), -8.0)   # negative boundary
        self.assertEqual(_revision_points(-3, GOV), -15.0)  # strong_negative boundary

    def test_revision_rejects_fractional_and_malformed(self):
        # analyst_revision_net is an event/count field — a fractional / float / bool / string is NOT a valid count
        # (R-USSHORT-CATALYST-ANALYST-REVISION-FRACTIONAL-COUNT-GAP: the full adversarial set from the Required).
        for bad in (0.5, 2.9, 3.0, 3.1, -1.1, -2.9, -3.0, -3.1, True, False, "3", "-3",
                    float("nan"), float("inf"), None):
            self.assertIsNone(_revision_points(bad, GOV), f"{bad!r} must not score")

    def test_revision_accepts_legal_integer_counts(self):
        # positive controls retained for the legal integer counts named in the Required
        for n, pts in ((-3, -15.0), (-1, -8.0), (0, 0.0), (1, 8.0), (3, 15.0)):
            self.assertEqual(_revision_points(n, GOV), pts)

    def test_finite_int_strict(self):
        for ok in (3, -3, 0, 7):
            self.assertEqual(_finite_int(ok), ok)
        for bad in (3.0, 2.9, -1.1, True, False, "3", None, float("nan"), float("inf")):
            self.assertIsNone(_finite_int(bad))

    def test_event8k(self):
        self.assertEqual(_event8k_points("positive", GOV), 12.0)
        self.assertEqual(_event8k_points("neutral", GOV), 0.0)
        self.assertEqual(_event8k_points("negative", GOV), -12.0)
        self.assertIsNone(_event8k_points("unknown", GOV))
        self.assertIsNone(_event8k_points(None, GOV))

    def test_semantic_scale_and_cap(self):
        self.assertEqual(_semantic_points(1.0, GOV), 6.0)
        self.assertEqual(_semantic_points(-1.0, GOV), -6.0)
        self.assertEqual(_semantic_points(0.5, GOV), 3.0)
        self.assertEqual(_semantic_points(5.0, GOV), 6.0)    # clamped to +1 then scaled → cap
        self.assertEqual(_semantic_points(-5.0, GOV), -6.0)  # clamped to -1
        for bad in (True, "0.5", float("nan")):
            self.assertIsNone(_semantic_points(bad, GOV))


class TestCatalystBlock(unittest.TestCase):
    def test_positive_control_clamps_to_max(self):
        sig = {
            "earnings_surprise_pct": 15.0, "earnings_report_date": PAST,     # +20
            "analyst_revision_net": 5, "analyst_revision_date": PAST,        # +15
            "event_8k_class": "positive", "event_8k_date": PAST,             # +12
            "semantic_advisory_score": 1.0, "semantic_advisory_date": PAST,  # +6  → 50+53=103 → clamp 100
        }
        out = catalyst_block({"AAA": sig}, GOV, as_of=AS_OF)
        self.assertEqual(out["catalyst_block"]["AAA"], 100.0)
        self.assertEqual(out["neutral_fallback"], [])
        self.assertEqual(len(out["coverage_matrix"]["AAA"]["realized"]), 4)

    def test_negative_control_clamps_to_min(self):
        sig = {
            "earnings_surprise_pct": -15.0, "earnings_report_date": PAST,     # -20
            "analyst_revision_net": -5, "analyst_revision_date": PAST,        # -15
            "event_8k_class": "negative", "event_8k_date": PAST,             # -12
            "semantic_advisory_score": -1.0, "semantic_advisory_date": PAST,  # -6 → 50-53=-3 → clamp 0
        }
        out = catalyst_block({"BBB": sig}, GOV, as_of=AS_OF)
        self.assertEqual(out["catalyst_block"]["BBB"], 0.0)

    def test_single_beat(self):
        out = catalyst_block({"C": {"earnings_surprise_pct": 5.0, "earnings_report_date": PAST}}, GOV, as_of=AS_OF)
        self.assertEqual(out["catalyst_block"]["C"], 60.0)   # 50 + beat 10

    def test_no_signal_is_neutral_and_flagged(self):
        out = catalyst_block({"D": {}}, GOV, as_of=AS_OF)
        self.assertEqual(out["catalyst_block"]["D"], _V1_NEUTRAL)
        self.assertIn("D", out["neutral_fallback"])
        self.assertEqual(out["coverage_matrix"]["D"]["realized"], [])

    def test_inline_earnings_is_realized_not_fallback(self):
        # an inline realized earnings IS a realized catalyst (coverage), valued neutral but NOT a missing-data
        # fallback — distinct from a no-catalyst ticker.
        out = catalyst_block({"E": {"earnings_surprise_pct": 0.0, "earnings_report_date": PAST}}, GOV, as_of=AS_OF)
        self.assertEqual(out["catalyst_block"]["E"], 50.0)
        self.assertNotIn("E", out["neutral_fallback"])
        self.assertEqual(out["coverage_matrix"]["E"]["realized"], ["earnings_surprise_pct"])

    def test_future_event_excluded_not_scored(self):
        # the design-critical rule: a future-dated catalyst must NOT enter the selection score (→ §8.1).
        sig = {"earnings_surprise_pct": 15.0, "earnings_report_date": FUTURE}
        out = catalyst_block({"F": sig}, GOV, as_of=AS_OF)
        self.assertEqual(out["catalyst_block"]["F"], _V1_NEUTRAL)             # NOT 50+20
        self.assertIn("F", out["neutral_fallback"])
        self.assertEqual(out["coverage_matrix"]["F"]["future_excluded"], ["earnings_surprise_pct"])
        self.assertEqual(out["coverage_matrix"]["F"]["realized"], [])

    def test_future_signal_does_not_lift_realized_score(self):
        sig = {
            "earnings_surprise_pct": 5.0, "earnings_report_date": PAST,        # +10 realized
            "analyst_revision_net": 5, "analyst_revision_date": FUTURE,        # future → excluded
        }
        out = catalyst_block({"G": sig}, GOV, as_of=AS_OF)
        self.assertEqual(out["catalyst_block"]["G"], 60.0)                     # only the realized beat counts
        self.assertEqual(out["coverage_matrix"]["G"]["realized"], ["earnings_surprise_pct"])
        self.assertEqual(out["coverage_matrix"]["G"]["future_excluded"], ["analyst_revision_net"])

    def test_missing_date_is_unverified_excluded(self):
        sig = {"earnings_surprise_pct": 15.0}   # value present, no date → cannot prove realized
        out = catalyst_block({"H": sig}, GOV, as_of=AS_OF)
        self.assertEqual(out["catalyst_block"]["H"], _V1_NEUTRAL)
        self.assertEqual(out["coverage_matrix"]["H"]["unverified_excluded"], ["earnings_surprise_pct"])

    def test_unreal_date_is_unverified_excluded(self):
        sig = {"earnings_surprise_pct": 15.0, "earnings_report_date": "20261399"}
        out = catalyst_block({"I": sig}, GOV, as_of=AS_OF)
        self.assertEqual(out["coverage_matrix"]["I"]["unverified_excluded"], ["earnings_surprise_pct"])

    def test_strict_numeric_value_not_scored(self):
        # a bool / NaN / numeric-string value is not a usable signal (and is not silently scored)
        for bad in (True, float("nan"), "15"):
            out = catalyst_block({"J": {"earnings_surprise_pct": bad, "earnings_report_date": PAST}}, GOV, as_of=AS_OF)
            self.assertEqual(out["catalyst_block"]["J"], _V1_NEUTRAL)
            self.assertIn("J", out["neutral_fallback"])

    def test_negative_8k_only(self):
        out = catalyst_block({"K": {"event_8k_class": "negative", "event_8k_date": PAST}}, GOV, as_of=AS_OF)
        self.assertEqual(out["catalyst_block"]["K"], 38.0)   # 50 - 12

    def test_fractional_revision_not_scored_in_block(self):
        # Codex's exact probe: 2.9/3.1/-1.1 previously scored (58/65/42); a fractional net is now rejected → the
        # only signal is excluded → neutral fallback, NOT realized (the score can no longer move on a bad count).
        for frac in (2.9, 3.1, -1.1):
            out = catalyst_block({"Z": {"analyst_revision_net": frac, "analyst_revision_date": PAST}}, GOV, as_of=AS_OF)
            self.assertEqual(out["catalyst_block"]["Z"], _V1_NEUTRAL)
            self.assertIn("Z", out["neutral_fallback"])
            self.assertEqual(out["coverage_matrix"]["Z"]["realized"], [])

    def test_integer_revision_still_scores_in_block(self):
        out = catalyst_block({"Z": {"analyst_revision_net": 3, "analyst_revision_date": PAST}}, GOV, as_of=AS_OF)
        self.assertEqual(out["catalyst_block"]["Z"], 65.0)   # 50 + strong_positive 15
        self.assertEqual(out["coverage_matrix"]["Z"]["realized"], ["analyst_revision_net"])

    def test_invalid_as_of_raises(self):
        for bad in ("20261399", "2026-06-30", None, "", 20260630):
            with self.assertRaises(CatalystGovernanceError):
                catalyst_block({"X": _big_beat()}, GOV, as_of=bad)

    def test_drifted_governance_raises(self):
        bad = copy.deepcopy(GOV)
        bad["neutral_catalyst_score"] = 60.0
        with self.assertRaises(CatalystGovernanceError):
            catalyst_block({"X": _big_beat()}, bad, as_of=AS_OF)

    def test_non_dict_signals(self):
        out = catalyst_block("nope", GOV, as_of=AS_OF)
        self.assertEqual(out["catalyst_block"], {})
        self.assertEqual(out["neutral_fallback"], [])

    def test_non_dict_ticker_entry_is_neutral(self):
        out = catalyst_block({"L": None}, GOV, as_of=AS_OF)
        self.assertEqual(out["catalyst_block"]["L"], _V1_NEUTRAL)
        self.assertIn("L", out["neutral_fallback"])

    def test_result_shape(self):
        out = catalyst_block({"M": _big_beat()}, GOV, as_of=AS_OF)
        self.assertEqual(set(out), {"catalyst_block", "neutral_fallback", "coverage_matrix",
                                    "neutral_catalyst_score", "as_of"})
        self.assertEqual(out["as_of"], AS_OF)
        self.assertEqual(out["neutral_catalyst_score"], _V1_NEUTRAL)
        self.assertEqual(out["catalyst_block"]["M"], 70.0)   # 50 + big_beat 20

    def test_block_stays_within_bounds(self):
        out = catalyst_block(
            {"P": _big_beat(), "N": {"earnings_surprise_pct": -50.0, "earnings_report_date": PAST}},
            GOV, as_of=AS_OF)
        for v in out["catalyst_block"].values():
            self.assertTrue(0.0 <= v <= 100.0)


if __name__ == "__main__":
    unittest.main()
