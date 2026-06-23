# -*- coding: utf-8 -*-
"""Tests for US-short weekly_report.md renderer skeleton (engine/us_short_weekly_report_renderer.py).

Covers: the 13 §11.2 sections render in the FROZEN contract order (single source); the mandatory honest banner
(④ price_clock ALWAYS shown, ①②③⑤ shown only when present); price_clock fail-closed (missing / incomplete /
blank field refuses to render); the §11.2 lifecycle-reminder count reconcile (section 1 == section 12, else
refuse); section coverage (a missing section refuses); malformed input fails closed. No provider/live; no
A-share crossing.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_weekly_report_renderer as wr  # noqa: E402

CONTRACT = json.loads((ROOT / "presets" / "us_short_weekly_report_contract_20260620.json").read_text(encoding="utf-8"))
SECTIONS = CONTRACT["sections"]
PC_FIELDS = CONTRACT["price_clock"]["fields"]


def _good(**over):
    d = {
        "banner": {"price_clock": {f: ("RTH" if f == "session_scope" else "20260619") for f in PC_FIELDS}},
        "lifecycle_reminder_count": {"section_1": 3, "section_12": 3},
        "sections": {str(i): ["(content %d)" % i] for i in range(1, len(SECTIONS) + 1)},
    }
    d.update(over)
    return d


class RenderStructure(unittest.TestCase):
    def test_renders_13_sections_in_frozen_order(self):
        out = wr.render_weekly_report(_good())
        idxs = []
        for i, title in enumerate(SECTIONS, 1):
            header = "## %d. %s" % (i, title)
            self.assertIn(header, out)        # the title comes from the FROZEN contract (single source)
            idxs.append(out.index(header))
        self.assertEqual(idxs, sorted(idxs))  # exact frozen order
        self.assertEqual(len(SECTIONS), 13)

    def test_section_content_rendered(self):
        out = wr.render_weekly_report(_good())
        self.assertIn("(content 5)", out)


class HonestBanner(unittest.TestCase):
    def test_price_clock_always_shown_with_all_fields(self):
        out = wr.render_weekly_report(_good())
        self.assertIn("④ price_clock", out)
        for f in PC_FIELDS:
            self.assertIn(f, out)

    def test_optional_elements_shown_when_present_omitted_when_absent(self):
        d = _good()
        d["banner"]["macro_cluster_warning"] = "ai_complex 40%"
        out = wr.render_weekly_report(d)
        self.assertIn("② macro_cluster_warning: ai_complex 40%", out)
        self.assertNotIn("true_false_observe_split", out)  # absent ① not rendered


class PriceClockFailClosed(unittest.TestCase):
    def test_missing_price_clock_refused(self):
        d = _good(); del d["banner"]["price_clock"]
        with self.assertRaises(wr.WeeklyReportRenderError):
            wr.render_weekly_report(d)

    def test_incomplete_price_clock_refused(self):
        d = _good(); d["banner"]["price_clock"] = {PC_FIELDS[0]: "20260619"}  # only 1 of 4
        with self.assertRaises(wr.WeeklyReportRenderError):
            wr.render_weekly_report(d)

    def test_blank_price_clock_field_refused(self):
        d = _good(); d["banner"]["price_clock"][PC_FIELDS[0]] = ""
        with self.assertRaises(wr.WeeklyReportRenderError):
            wr.render_weekly_report(d)


class CountReconcile(unittest.TestCase):
    def test_matching_counts_ok(self):
        wr.render_weekly_report(_good(lifecycle_reminder_count={"section_1": 5, "section_12": 5}))

    def test_mismatch_refused(self):
        with self.assertRaises(wr.WeeklyReportRenderError):
            wr.render_weekly_report(_good(lifecycle_reminder_count={"section_1": 5, "section_12": 4}))

    def test_non_int_or_missing_count_refused(self):
        for bad in ({"section_1": "5", "section_12": 5}, {"section_1": True, "section_12": True}, {"section_1": 3}):
            with self.assertRaises(wr.WeeklyReportRenderError):
                wr.render_weekly_report(_good(lifecycle_reminder_count=bad))


class SectionCoverage(unittest.TestCase):
    def test_missing_section_refused(self):
        d = _good(); del d["sections"]["7"]
        with self.assertRaises(wr.WeeklyReportRenderError):
            wr.render_weekly_report(d)


class SurfaceInvariantFailsClosed(unittest.TestCase):
    """R-USSHORT-BATCH3-WEEKLY-REPORT-SURFACE-INVARIANT-GAP: non-blank semantic content, non-blank price_clock,
    non-negative counts — a structurally-complete-but-empty/whitespace surface is refused."""

    def test_blank_section_bodies_refused(self):
        for bad in ("", "   ", [], [""], ["  "], [None], ["ok", ""], 5, {}):
            d = _good(); d["sections"]["7"] = bad
            with self.assertRaises(wr.WeeklyReportRenderError, msg=repr(bad)):
                wr.render_weekly_report(d)

    def test_whitespace_price_clock_refused(self):
        d = _good(); d["banner"]["price_clock"][PC_FIELDS[0]] = "   "
        with self.assertRaises(wr.WeeklyReportRenderError):
            wr.render_weekly_report(d)

    def test_negative_counts_refused(self):
        with self.assertRaises(wr.WeeklyReportRenderError):
            wr.render_weekly_report(_good(lifecycle_reminder_count={"section_1": -1, "section_12": -1}))

    def test_zero_counts_valid(self):  # positive control: 0 == 0 is a legitimate "no reminders" state
        wr.render_weekly_report(_good(lifecycle_reminder_count={"section_1": 0, "section_12": 0}))

    def test_blank_optional_banner_omitted(self):  # supplied-but-blank optional → omitted, never rendered as "②: "
        d = _good(); d["banner"]["macro_cluster_warning"] = "   "
        self.assertNotIn("macro_cluster_warning", wr.render_weekly_report(d))


class MalformedFailsClosed(unittest.TestCase):
    def test_non_dict_report_data_refused(self):
        for bad in (None, "x", 5, []):
            with self.assertRaises(wr.WeeklyReportRenderError):
                wr.render_weekly_report(bad)

    def test_non_dict_subfields_refused(self):
        for key in ("banner", "lifecycle_reminder_count", "sections"):
            d = _good(); d[key] = "nope"
            with self.assertRaises(wr.WeeklyReportRenderError):
                wr.render_weekly_report(d)


if __name__ == "__main__":
    unittest.main()
