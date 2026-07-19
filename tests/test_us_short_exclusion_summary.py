# -*- coding: utf-8 -*-
"""Tests for US-short §11.4 exclusion_summary (engine/us_short_exclusion_summary.py).

Covers: the privacy split (public = de-identified counts only, no tickers; private = real-holding detail);
the public schema de-identification gate (a re-identifying / extra-key dict is refused before it can land on a
tracked path); closed-world + complete category set (unknown category refused, all 8 frozen categories always
present, omitted → 0); count invariants (total == sum, non-negative-int counts, whole malformed class refused);
as_of strict real date; the §18.0 private-path guard on write_exclusion_private (symmetric to the lifecycle
store) vs the un-guarded de-identified write_exclusion_public; the §11.2 section render (non-blank, all 8
categories, hot_excluded audit, de-identified); and the structural audit-only property (no admission/veto
output). Pure/offline; no provider/live; no A-share crossing.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_exclusion_summary as es  # noqa: E402
from engine.us_short_private_paths import PrivatePathError  # noqa: E402

GOV = json.loads((ROOT / "presets" / "us_short_exclusion_summary_governance_20260620.json").read_text(encoding="utf-8"))
CATS = GOV["exclusion_categories"]
PASSES = GOV["covers_passes"]


def _good_input(**over):
    d = {
        "as_of": "20260619",
        "categories": {
            CATS[0]: {"public_count": 3, "holdings": ["AAPL", "MSFT"]},
            CATS[1]: {"public_count": 1, "holdings": []},
            CATS[7]: {"public_count": 2},  # holdings omitted
        },
        "hot_excluded": {"public_heat_count": 2, "unevaluable_count": 1,
                         "holdings": [{"ticker": "NVDA", "reason": "liquidity_gate"}]},
    }
    d.update(over)
    return d


class PrivacySplit(unittest.TestCase):
    def test_public_is_de_identified_private_carries_holdings(self):
        out = es.build_exclusion_summary(_good_input())
        pub, priv = out["public"], out["private"]
        # PUBLIC carries no ticker anywhere (de-identified by construction)
        dumped = json.dumps(pub, ensure_ascii=False)
        for ticker in ("AAPL", "MSFT", "NVDA"):
            self.assertNotIn(ticker, dumped)
        # PRIVATE carries the real-holding detail
        self.assertIn("AAPL", priv["categories"][CATS[0]])
        self.assertEqual(priv["hot_excluded"]["holdings"][0]["ticker"], "NVDA")

    def test_public_counts_match_input(self):
        pub = es.build_exclusion_summary(_good_input())["public"]
        self.assertEqual(pub["category_counts"][CATS[0]], 3)
        self.assertEqual(pub["total_excluded"], 3 + 1 + 2)
        self.assertEqual(pub["hot_excluded_public_heat_count"], 2)
        self.assertEqual(pub["hot_excluded_unevaluable_count"], 1)

    def test_result_keys_are_only_public_private(self):  # structural: a summary producer, never an admission/veto path
        self.assertEqual(set(es.build_exclusion_summary(_good_input())), {"public", "private"})


class CompleteClosedWorldCategories(unittest.TestCase):
    def test_all_eight_frozen_categories_present_omitted_is_zero(self):
        pub = es.build_exclusion_summary(_good_input())["public"]
        self.assertEqual(set(pub["category_counts"]), set(CATS))
        # an omitted category counts 0 (CATS[2] never supplied)
        self.assertEqual(pub["category_counts"][CATS[2]], 0)

    def test_unknown_category_refused(self):
        with self.assertRaises(es.ExclusionSummaryError):
            es.build_exclusion_summary(_good_input(categories={"不存在的类别": {"public_count": 1}}))

    def test_covers_passes_from_frozen_governance(self):
        self.assertEqual(set(es.build_exclusion_summary(_good_input())["public"]["covers_passes"]), set(PASSES))


class CountWholeClassFailsClosed(unittest.TestCase):
    def test_bad_public_count_refused(self):
        for bad in (True, 1.5, "3", -1, None):
            with self.assertRaises(es.ExclusionSummaryError, msg=repr(bad)):
                es.build_exclusion_summary(_good_input(categories={CATS[0]: {"public_count": bad}}))

    def test_bad_hot_heat_count_refused(self):
        for bad in (True, 1.5, "2", -1):
            with self.assertRaises(es.ExclusionSummaryError, msg=repr(bad)):
                es.build_exclusion_summary(_good_input(hot_excluded={"public_heat_count": bad}))

    def test_bad_hot_unevaluable_count_refused(self):
        for bad in (True, 1.5, "2", -1):
            with self.assertRaises(es.ExclusionSummaryError, msg=repr(bad)):
                es.build_exclusion_summary(_good_input(
                    hot_excluded={"public_heat_count": 0, "unevaluable_count": bad}))

    def test_zero_exclusions_valid(self):  # positive control: an empty quiet week is legitimate
        pub = es.build_exclusion_summary(_good_input(categories={}, hot_excluded={}))["public"]
        self.assertEqual(pub["total_excluded"], 0)
        self.assertEqual(pub["hot_excluded_public_heat_count"], 0)
        self.assertEqual(set(pub["category_counts"]), set(CATS))


class AsOfStrictRealDate(unittest.TestCase):
    def test_bad_as_of_refused(self):
        for bad in ("20260231", "2026-06-19", "x", None, 20260619):
            with self.assertRaises(es.ExclusionSummaryError, msg=repr(bad)):
                es.build_exclusion_summary(_good_input(as_of=bad))


class MalformedContainersFailClosed(unittest.TestCase):
    def test_non_dict_top_level_refused(self):
        for bad in (None, "x", 5, []):
            with self.assertRaises(es.ExclusionSummaryError):
                es.build_exclusion_summary(bad)

    def test_non_dict_subcontainers_refused(self):
        for key in ("categories", "hot_excluded"):
            with self.assertRaises(es.ExclusionSummaryError):
                es.build_exclusion_summary(_good_input(**{key: "nope"}))

    def test_non_dict_category_entry_refused(self):
        with self.assertRaises(es.ExclusionSummaryError):
            es.build_exclusion_summary(_good_input(categories={CATS[0]: 5}))

    def test_non_list_holdings_refused(self):
        with self.assertRaises(es.ExclusionSummaryError):
            es.build_exclusion_summary(_good_input(categories={CATS[0]: {"public_count": 1, "holdings": "AAPL"}}))
        with self.assertRaises(es.ExclusionSummaryError):
            es.build_exclusion_summary(_good_input(hot_excluded={"public_heat_count": 1, "holdings": "NVDA"}))


class PublicSchemaDeIdGate(unittest.TestCase):
    """_assert_public is the de-identification floor: a re-identifying / tampered public dict is refused."""

    def _pub(self):
        return es.build_exclusion_summary(_good_input())["public"]

    def test_holdings_list_in_category_counts_refused(self):  # integer-only counts → no ticker list can hide
        p = self._pub(); p["category_counts"][CATS[0]] = ["AAPL"]
        with self.assertRaises(es.ExclusionSummaryError):
            es._assert_public(p)

    def test_extra_top_level_key_refused(self):  # additionalProperties:false → no smuggled ticker field
        p = self._pub(); p["tickers"] = ["AAPL"]
        with self.assertRaises(es.ExclusionSummaryError):
            es._assert_public(p)

    def test_total_mismatch_refused(self):
        p = self._pub(); p["total_excluded"] = p["total_excluded"] + 1
        with self.assertRaises(es.ExclusionSummaryError):
            es._assert_public(p)

    def test_incomplete_category_set_refused(self):
        p = self._pub(); del p["category_counts"][CATS[0]]
        with self.assertRaises(es.ExclusionSummaryError):
            es._assert_public(p)

    def test_covers_passes_tamper_refused(self):
        p = self._pub(); p["covers_passes"] = ["pass1_eligibility"]  # dropped pass2
        with self.assertRaises(es.ExclusionSummaryError):
            es._assert_public(p)

    def test_impossible_as_of_refused(self):
        p = self._pub(); p["as_of"] = "20260231"
        with self.assertRaises(es.ExclusionSummaryError):
            es._assert_public(p)


class SectionRender(unittest.TestCase):
    def test_renders_all_categories_total_and_hot(self):
        pub = es.build_exclusion_summary(_good_input())["public"]
        lines = es.render_exclusion_section(pub)
        self.assertTrue(all(isinstance(x, str) and x.strip() for x in lines))  # every line non-blank
        joined = "\n".join(lines)
        for cat in CATS:
            self.assertIn(cat, joined)
        self.assertIn("本周剔除 6 只", joined)
        self.assertIn("hot_excluded", joined)
        self.assertIn("未能评估", joined)
        self.assertIn("绝不救回", joined)  # audit-only intent surfaced (never rescues hard veto)
        for ticker in ("AAPL", "MSFT", "NVDA"):  # de-identified section
            self.assertNotIn(ticker, joined)

    def test_zero_week_still_non_blank(self):
        pub = es.build_exclusion_summary(_good_input(categories={}, hot_excluded={}))["public"]
        lines = es.render_exclusion_section(pub)
        self.assertTrue(lines and all(x.strip() for x in lines))
        self.assertIn("本周剔除 0 只", "\n".join(lines))

    def test_render_refuses_bad_public(self):
        pub = es.build_exclusion_summary(_good_input())["public"]; pub["total_excluded"] = 999
        with self.assertRaises(es.ExclusionSummaryError):
            es.render_exclusion_section(pub)


class PrivatePathGuardSymmetric(unittest.TestCase):
    """write_exclusion_private wires the §18.0 P0 guard (real holdings → private only); write_exclusion_public is
    un-guarded because the de-id schema proves it tracked-safe."""

    def setUp(self):
        out = es.build_exclusion_summary(_good_input())
        self.pub, self.priv = out["public"], out["private"]

    def test_private_relative_path_refused(self):
        with self.assertRaises(PrivatePathError):
            es.write_exclusion_private(self.priv, "rel_excl_detail.json")

    def test_private_tracked_in_repo_path_refused(self):
        with self.assertRaises(PrivatePathError):
            es.write_exclusion_private(self.priv, ROOT / "docs" / "_nonprivate_excl_probe.json")
        self.assertFalse((ROOT / "docs" / "_nonprivate_excl_probe.json").exists())  # refused before any write

    def test_private_outside_repo_ok(self):
        d = Path(tempfile.mkdtemp())
        try:
            p = es.write_exclusion_private(self.priv, d / "excl_private.json")
            self.assertTrue(p.exists())
            self.assertIn("AAPL", json.loads(p.read_text(encoding="utf-8"))["categories"][CATS[0]])
        finally:
            for f in d.glob("*"):
                f.unlink()
            d.rmdir()

    def test_public_write_unguarded_de_identified(self):
        d = Path(tempfile.mkdtemp())
        try:
            p = es.write_exclusion_public(self.pub, d / "excl_public.json")
            written = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(written["total_excluded"], 6)
            self.assertNotIn("AAPL", p.read_text(encoding="utf-8"))
        finally:
            for f in d.glob("*"):
                f.unlink()
            d.rmdir()

    def test_public_write_refuses_bad_dict(self):
        d = Path(tempfile.mkdtemp())
        try:
            bad = dict(self.pub); bad["total_excluded"] = 999
            with self.assertRaises(es.ExclusionSummaryError):
                es.write_exclusion_public(bad, d / "x.json")
        finally:
            d.rmdir()


class PrivateDetailContractFailsClosed(unittest.TestCase):
    """R-USSHORT-BATCH3-EXCLUSION-SUMMARY-PRIVATE-DETAIL-CONTRACT-GAP: the private side is the §11.4 audit trail
    (which holdings excluded + why high-heat dropped), so a malformed holding / hot_excluded row, or a malformed
    direct write payload, must fail closed before becoming official private output."""

    def test_build_refuses_malformed_category_holdings(self):
        for bad in ([None], [""], ["  "], ["AAPL", ""], [123], [["AAPL"]], [{"ticker": "AAPL"}]):
            with self.assertRaises(es.ExclusionSummaryError, msg=repr(bad)):
                es.build_exclusion_summary(_good_input(categories={CATS[0]: {"public_count": 1, "holdings": bad}}))

    def test_build_refuses_malformed_hot_rows(self):
        for bad in ([None], ["NVDA"], [{"ticker": "NVDA"}], [{"reason": "x"}], [{"ticker": "", "reason": "x"}],
                    [{"ticker": "NVDA", "reason": "  "}], [{"ticker": "NVDA", "reason": None}]):
            with self.assertRaises(es.ExclusionSummaryError, msg=repr(bad)):
                es.build_exclusion_summary(_good_input(hot_excluded={"public_heat_count": 1, "holdings": bad}))

    def test_build_accepts_legitimate_private_rows(self):  # positive control: well-formed holdings + ticker/reason rows
        priv = es.build_exclusion_summary(_good_input())["private"]
        self.assertEqual(priv["categories"][CATS[0]], ["AAPL", "MSFT"])
        self.assertEqual(priv["categories"][CATS[7]], [])  # omitted category -> empty holding list (valid)
        self.assertEqual(priv["hot_excluded"]["holdings"][0]["reason"], "liquidity_gate")

    def test_write_private_refuses_malformed_direct_payload(self):
        d = Path(tempfile.mkdtemp())  # outside-repo -> §18.0 guard passes, so the SHAPE gate is what must refuse
        full = {cat: [] for cat in CATS}
        bad_cat = dict(full); bad_cat[CATS[0]] = [None]
        try:
            payloads = [
                {"as_of": "notadate", "categories": dict(full), "hot_excluded": {"holdings": []}},
                {"as_of": "20260231", "categories": dict(full), "hot_excluded": {"holdings": []}},   # impossible date
                {"as_of": "20260619", "categories": "bad", "hot_excluded": {"holdings": []}},
                {"as_of": "20260619", "categories": {CATS[0]: []}, "hot_excluded": {"holdings": []}},  # incomplete set
                {"as_of": "20260619", "categories": bad_cat, "hot_excluded": {"holdings": []}},        # None ticker
                {"as_of": "20260619", "categories": dict(full), "hot_excluded": {"holdings": "not-list"}},
                {"as_of": "20260619", "categories": dict(full), "hot_excluded": {"holdings": [{"ticker": "NVDA"}]}},  # no reason
            ]
            for p in payloads:
                with self.assertRaises(es.ExclusionSummaryError, msg=repr(p)[:70]):
                    es.write_exclusion_private(p, d / "x.json")
            self.assertFalse((d / "x.json").exists())  # nothing written on any refusal
        finally:
            for f in d.glob("*"):
                f.unlink()
            d.rmdir()

    def test_write_private_accepts_built_payload(self):  # positive control: a built private writes fine
        priv = es.build_exclusion_summary(_good_input())["private"]
        d = Path(tempfile.mkdtemp())
        try:
            self.assertTrue(es.write_exclusion_private(priv, d / "ok.json").exists())
        finally:
            for f in d.glob("*"):
                f.unlink()
            d.rmdir()


class MixedTypeKeyDiagnosticFailsClosed(unittest.TestCase):
    """R-USSHORT-BATCH3-EXCLUSION-SUMMARY-PRIVATE-DETAIL-CONTRACT-GAP (re-open): a categories / category_counts
    dict carrying a NON-STRING key (frozen string keys + a non-string sibling) must yield the sanctioned
    ExclusionSummaryError, NEVER a raw TypeError from sorting mixed-type keys in the diagnostic message. Swept
    across all three call paths (write/validate_private, _assert_public, build) — the `sorted(map(str, ...))` class."""

    def test_write_private_mixed_key_categories(self):  # Codex's write_mixed_key_cats probe
        payload = {"as_of": "20260619", "categories": {c: [] for c in CATS}, "hot_excluded": {"holdings": []}}
        payload["categories"][5] = []  # non-string sibling key
        d = Path(tempfile.mkdtemp())
        try:
            with self.assertRaises(es.ExclusionSummaryError):  # not a raw TypeError
                es.write_exclusion_private(payload, d / "x.json")
            self.assertFalse((d / "x.json").exists())
        finally:
            for f in d.glob("*"):
                f.unlink()
            d.rmdir()

    def test_assert_public_mixed_key_counts(self):
        pub = es.build_exclusion_summary(_good_input())["public"]
        pub["category_counts"][7] = 0  # non-string sibling key alongside the frozen strings
        with self.assertRaises(es.ExclusionSummaryError):
            es._assert_public(pub)

    def test_build_mixed_key_categories(self):
        with self.assertRaises(es.ExclusionSummaryError):
            es.build_exclusion_summary(_good_input(categories={5: {"public_count": 1}, "x_unknown": {"public_count": 1}}))


if __name__ == "__main__":
    unittest.main()
