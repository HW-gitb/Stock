# -*- coding: utf-8 -*-
"""Tests for US-short §11.5 coverage honesty (engine/us_short_coverage_honesty.py).

Covers: the worst-of coverage_status derivation (severity = frozen coverage_status order); the §11.5 honesty
invariant (coverage_status == "full" IFF zero gap_tags — both directions); closed-world + complete gating
category set (analyst / sec_parse / event); frozen-enum single-source for row_source + coverage_status; gap-tag
determinism; and whole malformed-input class fail-closed. Pure/offline; no provider/live; no A-share crossing.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_coverage_honesty as ch  # noqa: E402

ENUMS = json.loads((ROOT / "presets" / "us_short_action_table_contract_20260620.json").read_text(encoding="utf-8"))["design_locked_enums"]
ROW_SOURCES = ENUMS["row_source"]
COVERAGE_STATUSES = ENUMS["coverage_status"]
RS = ROW_SOURCES[0]  # a valid row_source for happy-path inputs


def _checks(analyst="ok", sec_parse="ok", event="ok"):
    return {"analyst": analyst, "sec_parse": sec_parse, "event": event}


class DeriveWorstOf(unittest.TestCase):
    def test_all_ok_is_full_no_gaps(self):
        c = ch.build_row_coverage(RS, _checks())
        self.assertEqual(c["coverage_status"], "full")
        self.assertEqual(c["coverage_gap_tags"], [])
        self.assertEqual(c["row_source"], RS)

    def test_single_missing_is_partial(self):
        c = ch.build_row_coverage(RS, _checks(analyst="missing"))
        self.assertEqual(c["coverage_status"], "partial")
        self.assertEqual(c["coverage_gap_tags"], ["analyst:missing"])

    def test_single_restricted_is_restricted(self):
        c = ch.build_row_coverage(RS, _checks(sec_parse="restricted"))
        self.assertEqual(c["coverage_status"], "restricted")
        self.assertEqual(c["coverage_gap_tags"], ["sec_parse:restricted"])

    def test_single_blocked_is_blocked(self):
        c = ch.build_row_coverage(RS, _checks(event="blocked"))
        self.assertEqual(c["coverage_status"], "blocked")
        self.assertEqual(c["coverage_gap_tags"], ["event:blocked"])

    def test_worst_of_wins(self):  # missing + blocked + ok -> blocked (worst), both gaps named, frozen category order
        c = ch.build_row_coverage(RS, _checks(analyst="missing", sec_parse="blocked", event="ok"))
        self.assertEqual(c["coverage_status"], "blocked")
        self.assertEqual(c["coverage_gap_tags"], ["analyst:missing", "sec_parse:blocked"])

    def test_missing_plus_restricted_is_restricted(self):
        c = ch.build_row_coverage(RS, _checks(analyst="missing", event="restricted"))
        self.assertEqual(c["coverage_status"], "restricted")  # restricted is worse than partial in the frozen order


class HonestyInvariant(unittest.TestCase):
    """The §11.5 heart: full IFF no gaps — never claim clean with a gap, never downgrade without naming it."""

    def test_full_with_gap_refused(self):
        with self.assertRaises(ch.CoverageHonestyError):
            ch.validate_row_coverage({"row_source": RS, "coverage_status": "full", "coverage_gap_tags": ["analyst:missing"]})

    def test_non_full_without_gap_refused(self):
        for status in ("partial", "restricted", "blocked"):
            with self.assertRaises(ch.CoverageHonestyError, msg=status):
                ch.validate_row_coverage({"row_source": RS, "coverage_status": status, "coverage_gap_tags": []})

    def test_full_no_gap_ok(self):  # positive control
        ch.validate_row_coverage({"row_source": RS, "coverage_status": "full", "coverage_gap_tags": []})

    def test_non_full_with_gap_ok(self):  # positive control
        ch.validate_row_coverage({"row_source": RS, "coverage_status": "partial", "coverage_gap_tags": ["event:missing"]})


class ClosedWorldAndMalformed(unittest.TestCase):
    def test_unknown_row_source_refused(self):
        with self.assertRaises(ch.CoverageHonestyError):
            ch.build_row_coverage("made_up_source", _checks())

    def test_incomplete_category_set_refused(self):
        with self.assertRaises(ch.CoverageHonestyError):
            ch.build_row_coverage(RS, {"analyst": "ok", "sec_parse": "ok"})  # missing event

    def test_extra_category_refused(self):
        with self.assertRaises(ch.CoverageHonestyError):
            ch.build_row_coverage(RS, {"analyst": "ok", "sec_parse": "ok", "event": "ok", "extra": "ok"})

    def test_non_dict_checks_refused(self):
        for bad in (None, "ok", 5, []):
            with self.assertRaises(ch.CoverageHonestyError, msg=repr(bad)):
                ch.build_row_coverage(RS, bad)

    def test_invalid_category_status_refused(self):
        for bad in ("clean", "nope", None, "", True):
            with self.assertRaises(ch.CoverageHonestyError, msg=repr(bad)):
                ch.build_row_coverage(RS, _checks(analyst=bad))


class ValidateRecordFailsClosed(unittest.TestCase):
    def test_bad_status_or_source_refused(self):
        with self.assertRaises(ch.CoverageHonestyError):
            ch.validate_row_coverage({"row_source": RS, "coverage_status": "clean", "coverage_gap_tags": []})
        with self.assertRaises(ch.CoverageHonestyError):
            ch.validate_row_coverage({"row_source": "x", "coverage_status": "full", "coverage_gap_tags": []})

    def test_bad_gap_tags_refused(self):
        for bad in ("event:missing", ["", "ok"], [None], ["  "], None):
            with self.assertRaises(ch.CoverageHonestyError, msg=repr(bad)):
                ch.validate_row_coverage({"row_source": RS, "coverage_status": "partial", "coverage_gap_tags": bad})

    def test_non_dict_refused(self):
        for bad in (None, "x", 5, []):
            with self.assertRaises(ch.CoverageHonestyError, msg=repr(bad)):
                ch.validate_row_coverage(bad)


class FrozenSingleSource(unittest.TestCase):
    def test_enums_match_frozen_contract(self):
        self.assertEqual(ch._row_sources(), ROW_SOURCES)
        self.assertEqual(ch._coverage_statuses(), COVERAGE_STATUSES)

    def test_every_frozen_row_source_accepted(self):
        for rs in ROW_SOURCES:
            self.assertEqual(ch.build_row_coverage(rs, _checks())["row_source"], rs)


class GapTagContractAndSeverity(unittest.TestCase):
    """R-USSHORT-BATCH3-COVERAGE-HONESTY-GAP-TAG-VALIDATOR-GAP: validate_row_coverage must parse gap_tags as
    <gating-category>:<non-ok-status> and require coverage_status == worst-of the tags — no arbitrary / ok /
    unknown tag, and no severity understatement (a blocked/restricted gap reported as partial)."""

    def _v(self, status, tags):
        return ch.validate_row_coverage({"row_source": RS, "coverage_status": status, "coverage_gap_tags": tags})

    def test_malformed_or_unknown_tags_refused(self):
        for tags in (["made_up_gap"], ["analyst"], ["analyst:ok"], ["unknown:missing"], ["analyst:weird"],
                     ["a:b:c"], ["analyst:missing", "analyst:blocked"]):  # last = duplicate category
            with self.assertRaises(ch.CoverageHonestyError, msg=repr(tags)):
                self._v("partial", tags)

    def test_severity_understatement_refused(self):  # Codex's probes: severe tag understated as partial
        for tags in (["event:blocked"], ["sec_parse:restricted"], ["analyst:missing", "event:blocked"]):
            with self.assertRaises(ch.CoverageHonestyError, msg=repr(tags)):
                self._v("partial", tags)

    def test_severity_overstatement_refused(self):
        with self.assertRaises(ch.CoverageHonestyError):
            self._v("blocked", ["analyst:missing"])  # claims blocked but only a missing gap

    def test_correct_severity_accepted(self):  # positive controls
        self._v("partial", ["analyst:missing"])
        self._v("restricted", ["sec_parse:restricted"])
        self._v("blocked", ["event:blocked"])
        self._v("blocked", ["analyst:missing", "event:blocked"])  # worst-of = blocked
        self._v("restricted", ["analyst:missing", "sec_parse:restricted"])  # worst-of = restricted

    def test_builder_output_still_validates(self):  # the deriver's records pass the strengthened gate
        for checks in (_checks(), _checks(analyst="missing"), _checks(analyst="missing", event="blocked"),
                       _checks(analyst="missing", sec_parse="restricted", event="blocked")):
            ch.validate_row_coverage(ch.build_row_coverage(RS, checks))


class RenderCoverageSection(unittest.TestCase):
    def test_aggregates_de_identified_nonblank(self):
        full = ch.build_row_coverage(RS, _checks())
        gap = ch.build_row_coverage(RS, _checks(analyst="missing"))
        lines = ch.render_coverage_section([full, gap, full])
        self.assertTrue(lines and all(isinstance(x, str) and x.strip() for x in lines))
        self.assertIn("3 行", lines[0])
        self.assertIn("full 2", lines[0])                 # 2 of the 3 rows full (zeros explicit elsewhere)
        self.assertIn("analyst:missing", " ".join(lines)) # the gap tag is named (不写 clean)

    def test_all_full_and_empty_nonblank(self):
        full = ch.build_row_coverage(RS, _checks())
        self.assertIn("无覆盖缺口", " ".join(ch.render_coverage_section([full])))
        empty = ch.render_coverage_section([])
        self.assertIn("0 行", empty[0])
        self.assertTrue(all(x.strip() for x in empty))    # non-blank even for an empty week

    def test_not_a_list_refused(self):
        with self.assertRaises(ch.CoverageHonestyError):
            ch.render_coverage_section({"x": 1})

    def test_invalid_record_refused(self):
        bad = ch.build_row_coverage(RS, _checks())
        bad["coverage_status"] = "blocked"                # full→blocked w/o gap_tags → §11.5 honesty invariant violated
        with self.assertRaises(ch.CoverageHonestyError):
            ch.render_coverage_section([bad])


if __name__ == "__main__":
    unittest.main()
