from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

# Self-contained fixture; tests must not depend on live result/ data because
# that directory churns each weekly run and would break CI / fresh clones.
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "analysis_input_minimal.json"

from engine.analyzer import state_manager
from engine.analyzer.rule6_hard_veto import RULE_VERSIONS, run_veto
from runners.run_analysis_report import (
    apply_enrichment,
    build_report,
    find_candidate,
    load_analysis_input,
    load_enrichment,
    render_markdown,
    validate_enrichment,
    write_report,
)

class RunAnalysisReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        state_root = Path(self._tmp.name)
        self._original_paths = (
            state_manager.POSITIONS_PATH,
            state_manager.VETO_LOG_PATH,
            state_manager.CIRCUIT_BREAKER_PATH,
        )
        state_manager.POSITIONS_PATH = state_root / "positions.json"
        state_manager.VETO_LOG_PATH = state_root / "veto_log.json"
        state_manager.CIRCUIT_BREAKER_PATH = state_root / "circuit_breaker.json"

    def tearDown(self) -> None:
        (
            state_manager.POSITIONS_PATH,
            state_manager.VETO_LOG_PATH,
            state_manager.CIRCUIT_BREAKER_PATH,
        ) = self._original_paths
        self._tmp.cleanup()

    def test_build_report_replays_phase3_analyzer(self) -> None:
        payload = load_analysis_input("ignored", input_path=FIXTURE_PATH)
        candidate = find_candidate(payload, "600000.SH")
        report = build_report(
            payload,
            candidate,
            generated_at="2026-05-25T00:00:00+08:00",
        )

        self.assertEqual(report["schema_name"], "deterministic_report")
        self.assertEqual(report["schema_version"], "1.0.0")
        self.assertEqual(report["ts_code"], "600000.SH")
        self.assertEqual(report["veto"], run_veto(candidate))
        self.assertEqual(
            {item["code"] for item in report["data_lineage"]["analyzer_rules"]},
            set(RULE_VERSIONS),
        )
        self.assertIn(report["decision"]["action"], {"skip", "watch"})
        self.assertFalse(report["llm_notes"]["enabled"])
        self.assertIn(
            "entry_plan.price",
            {item["field"] for item in report["unknowns"]},
        )

    def test_markdown_renders_m67_table(self) -> None:
        payload = load_analysis_input("ignored", input_path=FIXTURE_PATH)
        candidate = find_candidate(payload, "600000.SH")
        report = build_report(
            payload,
            candidate,
            generated_at="2026-05-25T00:00:00+08:00",
        )

        markdown = render_markdown(report)

        self.assertIn("# M6.7 Deterministic Report - 600000.SH", markdown)
        self.assertIn("## M6.7 Table", markdown)
        self.assertIn("| target | action | shares | entry/tp1/tp2/stop |", markdown)
        self.assertIn("pending_llm_enrich", markdown)

    def test_llm_tasks_map_to_prompt_sections(self) -> None:
        # Uses the fixture's second candidate (FIXT_L2_UNKNOWN_WITH_TASKS),
        # which carries the same three llm_tasks as the historical backtest
        # generated fixture used to: industry_trend, regulatory_check (aliased
        # to prompts/regulatory_48h.md), and policy_news. Also has l2_name="未知"
        # to exercise the l2_unknown veto path.
        payload = load_analysis_input("ignored", input_path=FIXTURE_PATH)
        candidate = find_candidate(payload, "600001.SH")
        report = build_report(
            payload,
            candidate,
            generated_at="2026-05-25T00:00:00+08:00",
        )
        sections = {item["code"]: item for item in report["llm_notes"]["sections"]}
        markdown = render_markdown(report)

        self.assertEqual(
            set(sections),
            {"industry_trend", "regulatory_check", "policy_news"},
        )
        self.assertEqual(
            sections["regulatory_check"]["prompt_ref"],
            "skills/a_short_analysis/prompts/regulatory_48h.md",
        )
        self.assertIn("analyzer_hard_veto:l2_unknown", markdown)

    def test_apply_enrichment_only_replaces_llm_notes(self) -> None:
        payload = load_analysis_input("ignored", input_path=FIXTURE_PATH)
        candidate = find_candidate(payload, "600000.SH")
        report = build_report(
            payload,
            candidate,
            generated_at="2026-05-25T00:00:00+08:00",
        )
        original_decision = report["decision"]
        enrichment = {
            "target": {
                "as_of": "20260522",
                "ts_code": "600000.SH",
                "report_schema_version": "1.0.0",
            },
            "llm_notes": {
                "enabled": True,
                "sections": [{
                    "code": "industry_trend",
                    "title": "Industry Trend",
                    "status": "completed",
                    "prompt_ref": "skills/a_short_analysis/prompts/industry_trend.md",
                    "content": "neutral",
                    "confidence": "low",
                }],
            },
        }

        merged = apply_enrichment(report, enrichment)

        self.assertEqual(merged["decision"], original_decision)
        self.assertTrue(merged["llm_notes"]["enabled"])
        self.assertEqual(merged["llm_notes"]["sections"][0]["code"], "industry_trend")
        self.assertIn("- enabled: true", render_markdown(merged))

    def test_find_candidate_empty_candidates_distinguishable_error(self) -> None:
        # Phase 3 audit (2026-05-25): distinguish "input has zero candidates"
        # from "ts_code not found among candidates" so the user can route the
        # fix correctly (re-run egs_main vs check ts_code spelling).
        from runners.run_analysis_report import find_candidate

        with self.assertRaisesRegex(ValueError, "no candidates"):
            find_candidate({"candidates": []}, "600000.SH")
        with self.assertRaisesRegex(ValueError, "no candidates"):
            find_candidate({}, "600000.SH")
        with self.assertRaisesRegex(ValueError, "not in analysis_input"):
            find_candidate({"candidates": [{"ts_code": "000001.SZ"}]}, "600000.SH")

    def test_apply_enrichment_returns_deep_copy(self) -> None:
        payload = load_analysis_input("ignored", input_path=FIXTURE_PATH)
        candidate = find_candidate(payload, "600000.SH")
        report = build_report(
            payload,
            candidate,
            generated_at="2026-05-25T00:00:00+08:00",
        )
        enrichment = {
            "target": {
                "as_of": "20260522",
                "ts_code": "600000.SH",
                "report_schema_version": "1.0.0",
            },
            "llm_notes": {"enabled": True, "sections": []},
        }
        merged = apply_enrichment(report, enrichment)

        # Mutating merged should not bleed back into the source report.
        merged["risk_flags"].append({"code": "synthetic", "severity": "info",
                                     "source": "llm", "detail": {}})
        self.assertNotIn(
            "synthetic",
            {f.get("code") for f in report["risk_flags"]},
            "apply_enrichment leaked a shared list reference",
        )

    def test_decision_reason_code_uses_comma_join(self) -> None:
        # B5: reason_code separator changed from '|' to ',' since '|' collides
        # with Markdown table cells. esp_non_positive < 0 should fire here.
        payload = load_analysis_input("ignored", input_path=FIXTURE_PATH)
        candidate = dict(find_candidate(payload, "600000.SH"))
        # Inject esp_raw < 0 to trigger esp_non_positive veto deterministically.
        fundamental = dict(candidate.get("fundamental") or {})
        expectation = dict(fundamental.get("expectation") or {})
        expectation["esp_raw"] = -10
        fundamental["expectation"] = expectation
        candidate["fundamental"] = fundamental
        report = build_report(
            payload,
            candidate,
            generated_at="2026-05-25T00:00:00+08:00",
        )
        self.assertEqual(report["decision"]["action"], "skip")
        self.assertIn("esp_non_positive", report["decision"]["reason_code"])
        self.assertNotIn("|", report["decision"]["reason_code"])

    def test_apply_enrichment_rejects_target_mismatch(self) -> None:
        payload = load_analysis_input("ignored", input_path=FIXTURE_PATH)
        candidate = find_candidate(payload, "600000.SH")
        report = build_report(
            payload,
            candidate,
            generated_at="2026-05-25T00:00:00+08:00",
        )
        enrichment = {
            "target": {
                "as_of": "20260522",
                "ts_code": "999999.SH",  # mismatch vs report ts_code 600000.SH
                "report_schema_version": "1.0.0",
            },
            "llm_notes": {"enabled": True, "sections": []},
        }

        with self.assertRaisesRegex(ValueError, "ts_code"):
            apply_enrichment(report, enrichment)

    def test_write_report_validates_schema_when_jsonschema_available(self) -> None:
        try:
            import jsonschema  # noqa: F401
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        payload = load_analysis_input("ignored", input_path=FIXTURE_PATH)
        candidate = find_candidate(payload, "600000.SH")
        report = build_report(
            payload,
            candidate,
            generated_at="2026-05-25T00:00:00+08:00",
        )
        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_report(report, Path(tmp))

            with json_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(data["ts_code"], "600000.SH")
            self.assertTrue(md_path.exists())

    def test_enrichment_example_validates_when_jsonschema_available(self) -> None:
        try:
            import jsonschema  # noqa: F401
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        enrichment = load_enrichment(
            Path("schemas/examples/deterministic_report_enrichment.example.json")
        )

        validate_enrichment(enrichment)


if __name__ == "__main__":
    unittest.main()
