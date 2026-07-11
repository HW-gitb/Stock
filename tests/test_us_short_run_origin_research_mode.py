from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_run_origin import (  # noqa: E402
    NO_UNCLEAN_CLAIM_MARK,
    OFFLINE_DISCLOSURE_SENTINEL,
    OFFLINE_TEST_RUN_ORIGIN,
    PROVIDER_AUTHORITATIVE_CLEAN_MARK,
    MIXED_SOURCE_DISCLOSURE_SENTINEL,
    MIXED_SOURCE_RUN_ORIGIN,
    RESEARCH_DISCLOSURE_SENTINEL,
    RESEARCH_LIVE_RUN_ORIGIN,
    RunOriginError,
    assert_offline_report_invariants,
    build_offline_honesty,
    build_run_status,
    canonical_offline_sections,
    canonical_section_1,
    offline_disclosure_lines,
    run_origin_for_mode,
    validate_run_origin,
)


def _report_data(origin):
    """A minimal valid report_data whose §1/§11/§13 are canonically rendered for `origin`."""
    honesty = build_offline_honesty("clean", 0)
    run_status = build_run_status("20260710", 1, 0, 0, 1, 0)
    s11, s13 = canonical_offline_sections(honesty, origin)
    sections = {str(i): ["filler %d" % i] for i in range(1, 14)}
    sections["1"] = canonical_section_1(origin, run_status)
    sections["11"] = s11
    sections["13"] = s13
    return {"sections": sections, "run_origin": origin, "run_status": run_status, "offline_honesty": honesty}


class ResearchLiveHonestyFact(unittest.TestCase):
    """The second batch4 honesty track (2026-07-09, option a): real provider data, pre-authoritative, NOT operational.
    Lets the capstone emit an honest real-data research report without the offline_test fixture lie — while `live`
    (operational-authoritative) stays hard-gated (option b, batch5). All fail-closed guarantees are preserved."""

    def test_research_fact_is_real_data_but_not_authorized(self):
        self.assertEqual(RESEARCH_LIVE_RUN_ORIGIN["run_mode"], "research_live")
        self.assertEqual(RESEARCH_LIVE_RUN_ORIGIN["data_origin"], "real_provider_pre_authoritative")
        self.assertEqual(RESEARCH_LIVE_RUN_ORIGIN["operational_use"], "not_authorized")

    def test_mixed_source_fact_discloses_template_bound_action_inputs(self):
        """A real provider fetch with caller template action inputs is never labelled research_live."""
        self.assertEqual(MIXED_SOURCE_RUN_ORIGIN["run_mode"], "mixed_source")
        self.assertEqual(MIXED_SOURCE_RUN_ORIGIN["data_origin"], "real_provider_plus_caller_template")
        self.assertEqual(MIXED_SOURCE_RUN_ORIGIN["operational_use"], "not_authorized")
        self.assertEqual(offline_disclosure_lines(MIXED_SOURCE_RUN_ORIGIN)[0], MIXED_SOURCE_DISCLOSURE_SENTINEL)
        self.assertEqual(run_origin_for_mode("mixed_source"), MIXED_SOURCE_RUN_ORIGIN)

    def test_both_facts_validate_and_for_mode_maps_them(self):
        self.assertEqual(validate_run_origin(OFFLINE_TEST_RUN_ORIGIN), OFFLINE_TEST_RUN_ORIGIN)
        self.assertEqual(validate_run_origin(RESEARCH_LIVE_RUN_ORIGIN), RESEARCH_LIVE_RUN_ORIGIN)
        self.assertEqual(run_origin_for_mode("offline_test"), OFFLINE_TEST_RUN_ORIGIN)
        self.assertEqual(run_origin_for_mode("research_live"), RESEARCH_LIVE_RUN_ORIGIN)

    def test_live_and_unknown_modes_still_fail_closed(self):
        # `live` (operational-authoritative) is NOT producible by batch4 — it is hard-gated upstream (→ batch5).
        with self.assertRaises(RunOriginError):
            run_origin_for_mode("live")
        with self.assertRaises(RunOriginError):
            run_origin_for_mode("whatever")

    def test_mismatched_pairing_and_operational_forgery_rejected(self):
        for bad in (
            {"run_mode": "offline_test", "data_origin": "real_provider_pre_authoritative", "operational_use": "not_authorized"},
            {"run_mode": "research_live", "data_origin": "caller_supplied_fixture", "operational_use": "not_authorized"},
            {"run_mode": "research_live", "data_origin": "real_provider_pre_authoritative", "operational_use": "authorized"},
            {"run_mode": "live", "data_origin": "real_provider_pre_authoritative", "operational_use": "authorized"},
        ):
            with self.assertRaises(RunOriginError):
                validate_run_origin(bad)

    def test_research_disclosure_says_real_data_not_fixture_still_disclaims_execution(self):
        lines = offline_disclosure_lines(RESEARCH_LIVE_RUN_ORIGIN)
        self.assertEqual(lines[0], RESEARCH_DISCLOSURE_SENTINEL)
        self.assertIn("研究运行", lines[0])
        self.assertIn("真实 provider", lines[1])
        self.assertNotIn("fixture", lines[1])         # research is NOT a fixture claim
        self.assertIn("不构成可执行", lines[1])          # but still not executable operational advice

    def test_offline_disclosure_unchanged_still_fixture(self):
        lines = offline_disclosure_lines(OFFLINE_TEST_RUN_ORIGIN)
        self.assertEqual(lines[0], OFFLINE_DISCLOSURE_SENTINEL)
        self.assertIn("fixture", lines[1])

    def test_research_sections_carry_no_operational_authority_marks(self):
        s11, s13 = canonical_offline_sections(build_offline_honesty("clean", 0), RESEARCH_LIVE_RUN_ORIGIN)
        joined = "\n".join(s11 + s13)
        self.assertIn("真实 provider 调用", s11[0])
        self.assertIn("未经 ship-gate 运营核准", s13[0])
        self.assertNotIn(PROVIDER_AUTHORITATIVE_CLEAN_MARK, joined)   # never "结构化、权威"
        self.assertNotIn(NO_UNCLEAN_CLAIM_MARK, joined)              # never "本周无不 clean"

    def test_report_invariants_accept_research_report(self):
        assert_offline_report_invariants(_report_data(RESEARCH_LIVE_RUN_ORIGIN), RESEARCH_LIVE_RUN_ORIGIN)

    def test_mode_swap_report_fails_closed(self):
        # a research run whose §1 wears the OFFLINE fixture sentinel (mode swap) must fail closed — the canonical
        # recompute for the real origin will not match.
        rd = _report_data(RESEARCH_LIVE_RUN_ORIGIN)
        rd["sections"] = dict(rd["sections"])
        rd["sections"]["1"] = canonical_section_1(OFFLINE_TEST_RUN_ORIGIN, rd["run_status"])
        with self.assertRaises(RunOriginError):
            assert_offline_report_invariants(rd, RESEARCH_LIVE_RUN_ORIGIN)

    def test_origin_mismatch_between_report_and_boundary_rejected(self):
        # report_data carries the research fact but the boundary is told it is offline → three-way reconcile fails.
        with self.assertRaises(RunOriginError):
            assert_offline_report_invariants(_report_data(RESEARCH_LIVE_RUN_ORIGIN), OFFLINE_TEST_RUN_ORIGIN)

    def test_mixed_int_and_str_section_key_rejected(self):
        # §6a hardening (pre-existing latent gap): a sections dict with BOTH int 1 and str "1" could diverge the
        # int-first validator from the str-first renderer so a forged operational body rides the alternate key.
        rd = _report_data(RESEARCH_LIVE_RUN_ORIGIN)
        rd["sections"] = dict(rd["sections"])
        rd["sections"][1] = rd["sections"]["1"]                        # canonical body on the int key
        rd["sections"]["1"] = ["⚠ 补充声明：可直接执行的运营周报"]        # forged operational body on the str key
        with self.assertRaises(RunOriginError):
            assert_offline_report_invariants(rd, RESEARCH_LIVE_RUN_ORIGIN)


if __name__ == "__main__":
    unittest.main()
