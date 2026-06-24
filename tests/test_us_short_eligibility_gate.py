# -*- coding: utf-8 -*-
"""Tests for the US-short Pass1 cheap-eligibility gate + governance validator — batch4 slice 4c-ii-a.

Design authority: docs/us_short_system_design.md §4.0 / §4.1 / §18.2 build-vs-wire ④.

Adversarial focus (avoid the multi-round churn the calendar validator hit): exhaustively probe the
governance runtime validator (closed-world + type + frozen-v1 drift on whitelist / thresholds /
disqualifiers / anchors) AND the fail-closed Pass1 predicate (every floor, every status flag,
every missing/non-finite/bool/string field -> explicit reason, never a silent pass), plus a
conformance triangulation that the module v1 consts equal the committed preset.
"""
import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_eligibility_gate as eg  # noqa: E402

_PRESET = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"


def _gov():
    return eg.load_eligibility_governance(_PRESET)


def _row(**kw):
    r = {"ticker": "AAPL", "exchange": "NASDAQ", "price": 150.0,
         "adv_usd": 1.0e10, "market_cap_usd": 2.5e12,
         "delisted": False, "halted": False, "bankruptcy": False, "otc": False}
    r.update(kw)
    return r


class GovernanceValidatorTests(unittest.TestCase):
    def test_production_preset_loads_and_validates(self):
        gov = _gov()
        self.assertEqual(gov["schema_name"], "us_short_eligibility_governance")

    def test_module_consts_triangulate_preset(self):
        # The consumer copy must equal the committed preset (no silent drift).
        gov = _gov()
        self.assertEqual(list(eg._V1_EXCHANGE_WHITELIST), list(gov["exchange_whitelist"]))
        self.assertEqual(list(eg._V1_DISQUALIFYING_STATUS_FLAGS), list(gov["disqualifying_status_flags"]))
        self.assertEqual(eg._V1_THRESHOLDS, gov["cheap_eligibility_thresholds"])
        for k, v in eg._V1_ANCHORS.items():
            self.assertEqual(gov[k], v)

    def _rejects(self, mutate):
        bad = copy.deepcopy(_gov())
        mutate(bad)
        with self.assertRaises(eg.EligibilityGovernanceError):
            eg.validate_eligibility_governance(bad)

    def test_rejects_non_dict(self):
        with self.assertRaises(eg.EligibilityGovernanceError):
            eg.validate_eligibility_governance(["not", "a", "dict"])

    def test_rejects_extra_top_key(self):
        self._rejects(lambda g: g.__setitem__("unknown", "x"))

    def test_rejects_missing_key(self):
        self._rejects(lambda g: g.pop("cheap_eligibility_thresholds"))

    def test_rejects_bad_schema_name(self):
        self._rejects(lambda g: g.__setitem__("schema_name", "other"))

    def test_rejects_bad_as_of(self):
        self._rejects(lambda g: g.__setitem__("as_of", "20260631"))

    def test_rejects_whitelist_drift(self):
        self._rejects(lambda g: g.__setitem__("exchange_whitelist", ["OTC"]))

    def test_rejects_threshold_weakening(self):
        self._rejects(lambda g: g["cheap_eligibility_thresholds"].__setitem__("min_price_usd", 0.01))

    def test_rejects_disqualifier_drop(self):
        self._rejects(lambda g: g.__setitem__("disqualifying_status_flags", ["delisted", "bankruptcy", "otc"]))

    def test_rejects_anchor_swap(self):
        self._rejects(lambda g: g.__setitem__("thresholds_calibration_item_id", 19))


class CheapEligibleTests(unittest.TestCase):
    def setUp(self):
        self.gov = _gov()

    def _reasons(self, **kw):
        return eg.cheap_eligible(_row(**kw), governance=self.gov)["reasons"]

    def test_fully_eligible_row(self):
        out = eg.cheap_eligible(_row(), governance=self.gov)
        self.assertTrue(out["eligible"])
        self.assertEqual(out["reasons"], [])
        self.assertEqual(out["ticker"], "AAPL")

    def test_at_floor_is_eligible(self):
        out = eg.cheap_eligible(_row(price=5.0, adv_usd=5000000.0, market_cap_usd=300000000.0), governance=self.gov)
        self.assertTrue(out["eligible"])

    def test_exchange_not_whitelisted(self):
        self.assertIn("exchange_not_whitelisted", self._reasons(exchange="OTC"))

    def test_exchange_missing(self):
        self.assertIn("exchange_unknown_or_invalid", self._reasons(exchange=None))

    def test_price_below_floor(self):
        self.assertIn("price_below_floor", self._reasons(price=4.99))

    def test_adv_below_floor(self):
        self.assertIn("adv_usd_below_floor", self._reasons(adv_usd=4_999_999.0))

    def test_market_cap_below_floor(self):
        self.assertIn("market_cap_usd_below_floor", self._reasons(market_cap_usd=2.99e8))

    def test_price_none_invalid(self):
        self.assertIn("price_unknown_or_invalid", self._reasons(price=None))

    def test_price_nan_invalid(self):
        self.assertIn("price_unknown_or_invalid", self._reasons(price=float("nan")))

    def test_price_bool_invalid(self):
        self.assertIn("price_unknown_or_invalid", self._reasons(price=True))

    def test_price_string_invalid(self):
        self.assertIn("price_unknown_or_invalid", self._reasons(price="150"))

    def test_status_delisted(self):
        self.assertIn("status_delisted", self._reasons(delisted=True))

    def test_status_halted(self):
        self.assertIn("status_halted", self._reasons(halted=True))

    def test_status_bankruptcy(self):
        self.assertIn("status_bankruptcy", self._reasons(bankruptcy=True))

    def test_status_otc(self):
        self.assertIn("status_otc", self._reasons(otc=True))

    def test_status_non_bool_invalid(self):
        self.assertIn("status_delisted_unknown_or_invalid", self._reasons(delisted="yes"))

    def test_missing_each_status_flag_rejected(self):
        # §3.3: a critical status is NEVER clean by omission — absent flag fails closed.
        for flag in ("delisted", "halted", "bankruptcy", "otc"):
            row = _row()
            del row[flag]
            out = eg.cheap_eligible(row, governance=self.gov)
            self.assertIn(f"status_{flag}_unknown_or_invalid", out["reasons"])
            self.assertFalse(out["eligible"])

    def test_all_status_missing_rejected(self):
        row = {"ticker": "MSFT", "exchange": "NYSE", "price": 100.0, "adv_usd": 1e9, "market_cap_usd": 1e12}
        out = eg.cheap_eligible(row, governance=self.gov)
        self.assertFalse(out["eligible"])
        for flag in ("delisted", "halted", "bankruptcy", "otc"):
            self.assertIn(f"status_{flag}_unknown_or_invalid", out["reasons"])

    def test_all_status_explicit_false_eligible(self):
        # positive control: clean status = all four EXPLICITLY False, not omission
        self.assertTrue(eg.cheap_eligible(_row(), governance=self.gov)["eligible"])

    def test_ticker_missing(self):
        self.assertIn("ticker_unknown_or_invalid", self._reasons(ticker=""))

    def test_row_not_dict(self):
        out = eg.cheap_eligible("AAPL", governance=self.gov)
        self.assertFalse(out["eligible"])
        self.assertEqual(out["reasons"], ["row_not_dict"])

    def test_collects_all_reasons(self):
        reasons = self._reasons(exchange="OTC", price=1.0, delisted=True)
        for r in ("exchange_not_whitelisted", "price_below_floor", "status_delisted"):
            self.assertIn(r, reasons)

    def test_lowercase_ticker_canonicalized(self):
        out = eg.cheap_eligible(_row(ticker="aapl"), governance=self.gov)
        self.assertTrue(out["eligible"])
        self.assertEqual(out["ticker"], "AAPL")  # emitted canonical

    def test_whitespace_ticker_canonicalized(self):
        out = eg.cheap_eligible(_row(ticker=" AAPL "), governance=self.gov)
        self.assertTrue(out["eligible"])
        self.assertEqual(out["ticker"], "AAPL")

    def test_class_share_ticker_eligible(self):
        out = eg.cheap_eligible(_row(ticker="BRK.B"), governance=self.gov)
        self.assertTrue(out["eligible"])
        self.assertEqual(out["ticker"], "BRK.B")

    def test_a_share_code_ticker_rejected(self):
        out = eg.cheap_eligible(_row(ticker="000001.SZ"), governance=self.gov)
        self.assertIn("ticker_unknown_or_invalid", out["reasons"])
        self.assertFalse(out["eligible"])


class Pass2SafetyAdmitTests(unittest.TestCase):
    def test_clean_candidate_admitted(self):
        out = eg.pass2_safety_admit({}, row_context="candidate")
        self.assertTrue(out["admit_to_topn"])
        self.assertEqual(out["veto_tier"], "none")

    def test_delisted_candidate_not_admitted(self):
        out = eg.pass2_safety_admit({"delisted": True}, row_context="candidate")
        self.assertFalse(out["admit_to_topn"])
        self.assertEqual(out["veto_tier"], "entry_hard_veto")

    def test_holding_always_admitted_even_with_veto(self):
        # §4.0 强制含持仓: a vetoed holding is NOT excluded by the gate; the veto drives §9 action.
        out = eg.pass2_safety_admit({"delisted": True}, row_context="holding")
        self.assertTrue(out["admit_to_topn"])
        self.assertEqual(out["veto_tier"], "position_hard_veto")

    def test_bad_row_context_raises(self):
        with self.assertRaises(ValueError):
            eg.pass2_safety_admit({}, row_context="unknown")


class CatalystRecallSlotTests(unittest.TestCase):
    def test_feed_unavailable_unchanged(self):
        out = eg.inject_catalyst_recall(["A", "B"], recall_feed=None)
        self.assertEqual(out["candidates"], ["A", "B"])
        self.assertFalse(out["recall_available"])
        self.assertEqual(out["recall_added"], [])

    def test_feed_merges_new_dedup_order(self):
        out = eg.inject_catalyst_recall(["A", "B"], recall_feed=["B", "C", "D"])
        self.assertEqual(out["candidates"], ["A", "B", "C", "D"])  # B de-duped, order preserved
        self.assertTrue(out["recall_available"])
        self.assertEqual(out["recall_added"], ["C", "D"])

    def test_bad_recall_feed_non_list_raises(self):
        with self.assertRaises(ValueError):
            eg.inject_catalyst_recall(["A"], recall_feed="C")

    def test_bad_recall_feed_empty_item_raises(self):
        with self.assertRaises(ValueError):
            eg.inject_catalyst_recall(["A"], recall_feed=["", "C"])

    def test_bad_base_raises(self):
        with self.assertRaises(ValueError):
            eg.inject_catalyst_recall("A", recall_feed=None)

    def test_duplicate_base_raises(self):
        # candidate set must be UNIQUE; a duplicate base ticker is surfaced, not silently de-duped
        with self.assertRaises(ValueError):
            eg.inject_catalyst_recall(["AAPL", "AAPL"], recall_feed=["MSFT"])

    def test_duplicate_base_raises_even_with_none_feed(self):
        with self.assertRaises(ValueError):
            eg.inject_catalyst_recall(["AAPL", "AAPL"], recall_feed=None)

    def test_recall_internal_dup_deduped(self):
        out = eg.inject_catalyst_recall(["A"], recall_feed=["B", "B", "C"])
        self.assertEqual(out["candidates"], ["A", "B", "C"])
        self.assertEqual(out["recall_added"], ["B", "C"])

    def test_base_canonicalized(self):
        out = eg.inject_catalyst_recall(["aapl", " MSFT "], recall_feed=None)
        self.assertEqual(out["candidates"], ["AAPL", "MSFT"])  # emitted canonical

    def test_semantic_duplicate_base_raises(self):
        for dup in (["AAPL", "aapl"], ["AAPL", " AAPL "]):
            with self.assertRaises(ValueError):
                eg.inject_catalyst_recall(dup, recall_feed=None)

    def test_recall_semantic_dup_against_base_deduped(self):
        out = eg.inject_catalyst_recall(["AAPL"], recall_feed=["aapl", "MSFT"])
        self.assertEqual(out["candidates"], ["AAPL", "MSFT"])  # 'aapl' canonicalizes to base 'AAPL'
        self.assertEqual(out["recall_added"], ["MSFT"])

    def test_class_share_preserved(self):
        out = eg.inject_catalyst_recall(["BRK.B"], recall_feed=["BRK-A"])
        self.assertEqual(out["candidates"], ["BRK.B", "BRK-A"])

    def test_a_share_code_in_base_raises(self):
        with self.assertRaises(ValueError):
            eg.inject_catalyst_recall(["000001.SZ"], recall_feed=None)

    def test_a_share_code_in_recall_raises(self):
        with self.assertRaises(ValueError):
            eg.inject_catalyst_recall(["AAPL"], recall_feed=["000001.SZ"])


class CanonicalTickerTriangulationTests(unittest.TestCase):
    """engine `_canonical_us_ticker` must agree with the runner's `_parse_us_ticker` (no drift)."""

    def test_engine_canonical_matches_runner_parse(self):
        from runners.us_short_account_state_from_manual_tables import _parse_us_ticker, ConvertError
        for raw in (" aapl ", "BRK.B", "msft", "BRK-A"):  # valid -> same canonical
            self.assertEqual(eg._canonical_us_ticker(raw), _parse_us_ticker(raw, "t"))
        for raw in ("000001.SZ", "", "12345", "TOOLONGSYM"):  # invalid -> engine None, runner raises
            self.assertIsNone(eg._canonical_us_ticker(raw))
            with self.assertRaises(ConvertError):
                _parse_us_ticker(raw, "t")


if __name__ == "__main__":
    unittest.main()
