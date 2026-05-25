from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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
        payload = load_analysis_input("20260522")
        candidate = find_candidate(payload, "600415.SH")
        report = build_report(
            payload,
            candidate,
            generated_at="2026-05-25T00:00:00+08:00",
        )

        self.assertEqual(report["schema_name"], "deterministic_report")
        self.assertEqual(report["schema_version"], "1.0.0")
        self.assertEqual(report["ts_code"], "600415.SH")
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
        payload = load_analysis_input("20260522")
        candidate = find_candidate(payload, "600415.SH")
        report = build_report(
            payload,
            candidate,
            generated_at="2026-05-25T00:00:00+08:00",
        )

        markdown = render_markdown(report)

        self.assertIn("# M6.7 Deterministic Report - 600415.SH", markdown)
        self.assertIn("## M6.7 Table", markdown)
        self.assertIn("| target | action | shares | entry/tp1/tp2/stop |", markdown)
        self.assertIn("pending_llm_enrich", markdown)

    def test_llm_tasks_map_to_prompt_sections(self) -> None:
        payload = load_analysis_input(
            "20260522",
            input_path=Path("result/a_short/backtest/generated/20260522/analysis_input.json"),
        )
        candidate = find_candidate(payload, "603298.SH")
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
        payload = load_analysis_input("20260522")
        candidate = find_candidate(payload, "600415.SH")
        report = build_report(
            payload,
            candidate,
            generated_at="2026-05-25T00:00:00+08:00",
        )
        original_decision = report["decision"]
        enrichment = {
            "target": {
                "as_of": "20260522",
                "ts_code": "600415.SH",
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

    def test_apply_enrichment_rejects_target_mismatch(self) -> None:
        payload = load_analysis_input("20260522")
        candidate = find_candidate(payload, "600415.SH")
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

        with self.assertRaisesRegex(ValueError, "ts_code"):
            apply_enrichment(report, enrichment)

    def test_write_report_validates_schema_when_jsonschema_available(self) -> None:
        try:
            import jsonschema  # noqa: F401
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        payload = load_analysis_input("20260522")
        candidate = find_candidate(payload, "600415.SH")
        report = build_report(
            payload,
            candidate,
            generated_at="2026-05-25T00:00:00+08:00",
        )
        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_report(report, Path(tmp))

            with json_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            self.assertEqual(data["ts_code"], "600415.SH")
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
