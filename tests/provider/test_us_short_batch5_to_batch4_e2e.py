from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_fmp_analyst_grades import resolve_analyst_grade_actions  # noqa: E402
from engine.us_short_massive_news import resolve_news_events  # noqa: E402
from engine.us_short_sec_offering_audit import resolve_offering_audit  # noqa: E402
from runners import us_short_batch5_to_batch4_weekend_e2e as e2e  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _GRADE_AS_OF,
    _NEWS_AS_OF,
    _OFFERING_AS_OF,
    _candidate_artifact,
    _constant_projection,
    _grade_source,
    _news_source,
    _offering_record,
)


STATE_DIR = ROOT / "state" / "us_short"
TEMPLATE = ROOT / "schemas" / "examples" / "us_short_weekend_batch4_context_packet.nonempty.example.json"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _empty_account() -> dict:
    return {
        "schema_name": "us_short_account_state",
        "schema_version": "1.0.0",
        "as_of": _DECISION_DATE,
        "us_market_equity": 30000.0,
        "us_short_bucket_capital": 10000.0,
        "us_short_available_cash": 4000.0,
        "positions": [],
        "manual_order_only": True,
        "broker_connection_allowed": False,
    }


def _no_build_template(path: Path) -> Path:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    payload["sizing_per_ticker"] = {}
    payload["basket_context"]["per_ticker"] = {}
    return _write_json(path, payload)


class Batch5ToBatch4E2ETest(unittest.TestCase):
    def setUp(self) -> None:
        self.slug = f"test_batch5_to_batch4_e2e_{os.getpid()}_{self._testMethodName}"
        self.paths = {
            "packet": STATE_DIR / f"{self.slug}_packet.json",
            "candidate": STATE_DIR / f"{self.slug}_candidate.json",
            "momentum": STATE_DIR / f"{self.slug}_momentum.json",
            "theme": STATE_DIR / f"{self.slug}_theme.json",
            "offering": STATE_DIR / f"{self.slug}_offering.json",
            "analyst": STATE_DIR / f"{self.slug}_analyst.json",
            "news": STATE_DIR / f"{self.slug}_news.json",
            "data_context": STATE_DIR / f"{self.slug}_data_context.json",
            "components": STATE_DIR / f"{self.slug}_context_components.json",
        }
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        self._write_source_packet()

    def tearDown(self) -> None:
        for path in self.paths.values():
            path.unlink(missing_ok=True)

    def _write_source_packet(self) -> None:
        targets = ("AAPL",)
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "LOWADV")))
        _write_json(
            self.paths["momentum"],
            _constant_projection("momentum_by_ticker", targets, "scored", score=50.0),
        )

        _write_json(
            self.paths["theme"],
            _constant_projection("theme_block_by_ticker", targets, "scored_theme_base", score=50.0),
        )
        _write_json(
            self.paths["offering"],
            resolve_offering_audit(as_of=_OFFERING_AS_OF, filings_by_ticker={"AAPL": _offering_record([])}),
        )
        _write_json(
            self.paths["analyst"],
            resolve_analyst_grade_actions(as_of=_GRADE_AS_OF, grades_by_ticker={"AAPL": _grade_source("AAPL", [])}),
        )
        _write_json(
            self.paths["news"],
            resolve_news_events(as_of=_NEWS_AS_OF, news_by_ticker={"AAPL": _news_source("AAPL", [])}),
        )
        _write_json(
            self.paths["packet"],
            {
                "schema_name": "us_short_batch5_data_context_source_packet",
                "schema_version": "1.0.0",
                "generated_at": "2026-06-15T08:05:00-04:00",
                "scope": {
                    "market": "US",
                    "lane": "us_short",
                    "batch": "batch5_provider_live",
                    "packet_status": "resolved_pass2_source_packet_ready_for_local_assembly",
                    "network_access_performed": False,
                    "provider_calls_performed": False,
                    "raw_payload_capture_performed": False,
                    "datahub_consumption_allowed": False,
                    "production_storage_allowed": False,
                    "ship_gate_evidence_claimed": False,
                    "broker_or_order_automation_allowed": False,
                    "a_share_crossing_allowed": False,
                },
                "decision_clock": {
                    "expected_decision_date": _DECISION_DATE,
                    "theme_opportunity_state": "no_strong_theme",
                },
                "paths": {
                    "candidate_artifact_path": _rel(self.paths["candidate"]),
                    "eligibility_governance_path": "presets/us_short_eligibility_governance_20260624.json",
                    "momentum_projection_path": _rel(self.paths["momentum"]),
                    "theme_projection_path": _rel(self.paths["theme"]),
                    "offering_audit_source_path": _rel(self.paths["offering"]),
                    "analyst_grade_actions_path": _rel(self.paths["analyst"]),
                    "massive_news_events_path": _rel(self.paths["news"]),
                    "catalyst_governance_path": "presets/us_short_catalyst_governance_20260630.json",
                    "output_data_context_path": _rel(self.paths["data_context"]),
                },
                "optional_inputs": {"holdings": [], "catalyst_recall_feed": None},
                "preflight_gates": {
                    "local_files_only": True,
                    "source_artifacts_must_exist": True,
                    "output_must_be_gitignored": True,
                    "no_provider_fetch": True,
                    "no_datahub_or_production": True,
                },
                "prohibited_claims": {
                    "provider_selection_complete": False,
                    "live_normalized_evidence": False,
                    "ship_gate_evidence": False,
                    "production_ready": False,
                    "datahub_consumed": False,
                },
            },
        )

    def test_vix_regime_override_changes_only_vix_axis(self) -> None:
        template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        original_axes = dict(template["market_axis_regimes"])
        components = {
            "data_context": {"selection_inputs": {"theme_opportunity_state": "no_strong_theme"}},
            "per_ticker_analysis": {},
            "run_provenance": {"as_of": _DECISION_DATE, "price_basis_date": "20260612"},
        }
        packet = e2e._assemble_batch4_packet(
            components=components,
            template=template,
            provider_health={"fmp": "ok", "sec_edgar": "ok"},
            account_state_path=Path("account.json"),
            calendar_path=Path("calendar.json"),
            governance_path=Path("governance.json"),
            private_root=Path("private"),
            official_output_root=None,
            now_et=datetime(2026, 6, 15, 9, 0, 0),
            vix_regime="防御",
        )
        self.assertEqual(packet["market_axis_regimes"]["vix"], "防御")
        self.assertEqual(packet["market_axis_regimes"]["market_trend"], original_axes["market_trend"])
        self.assertEqual(packet["market_axis_regimes"]["breadth"], original_axes["breadth"])

    def test_local_source_packet_to_private_weekly_report_and_action_table(self) -> None:
        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", {"fmp": "ok", "sec_edgar": "ok"})
            template = _no_build_template(private_root / "batch4_template.json")

            summary = e2e.run_e2e(
                source_packet_path=self.paths["packet"],
                batch4_template_path=template,
                account_state_path=account,
                provider_health_path=health,
                private_root=private_root,
                now_et=datetime(2026, 6, 15, 9, 0, 0),
                context_components_path=self.paths["components"],
                bootstrap_lifecycle=True,
                generated_at="2026-06-15T13:01:00Z",
            )

            self.assertEqual(summary["scope"]["status"], "batch5_source_packet_to_batch4_outputs_completed")
            self.assertFalse(summary["scope"]["network_access_required"])
            self.assertFalse(summary["scope"]["provider_calls_performed"])
            self.assertFalse(summary["scope"]["datahub_consumption_allowed"])
            self.assertFalse(summary["scope"]["ship_gate_evidence_claimed"])
            self.assertTrue(summary["batch4_run"]["emitted"])
            self.assertEqual(summary["batch4_run"]["decision_date"], _DECISION_DATE)
            self.assertEqual(summary["batch4_run"]["row_count"], 1)
            self.assertTrue((private_root / "weekly_private" / _DECISION_DATE / "weekly_report.md").exists())
            self.assertTrue((private_root / "weekly_private" / _DECISION_DATE / "action_table.csv").exists())
            self.assertTrue((private_root / "runs_private" / _DECISION_DATE / "machine_record.json").exists())
            self.assertTrue(self.paths["components"].exists())
            self.assertNotIn("AAPL", json.dumps(summary, ensure_ascii=False))

    def test_provider_health_is_required_before_any_batch4_output(self) -> None:
        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())

            with self.assertRaises(e2e.Batch5ToBatch4E2EError):
                e2e.run_e2e(
                    source_packet_path=self.paths["packet"],
                    batch4_template_path=TEMPLATE,
                    account_state_path=account,
                    provider_health_path=private_root / "missing_provider_health.json",
                    private_root=private_root,
                    now_et=datetime(2026, 6, 15, 9, 0, 0),
                    context_components_path=self.paths["components"],
                    bootstrap_lifecycle=True,
                )

            self.assertFalse((private_root / "weekly_private").exists())
            self.assertFalse((private_root / "runs_private").exists())
            self.assertFalse(self.paths["components"].exists())

    def test_cli_subprocess_writes_private_outputs_without_stdout_ticker_leak(self) -> None:
        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", {"fmp": "ok", "sec_edgar": "ok"})
            template = _no_build_template(private_root / "batch4_template.json")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "runners" / "us_short_batch5_to_batch4_weekend_e2e.py"),
                    "--source-packet",
                    str(self.paths["packet"]),
                    "--batch4-template",
                    str(template),
                    "--account",
                    str(account),
                    "--provider-health",
                    str(health),
                    "--private-root",
                    str(private_root),
                    "--now-et",
                    "2026-06-15T09:00:00",
                    "--context-components-out",
                    str(self.paths["components"]),
                    "--bootstrap-lifecycle",
                    "--generated-at",
                    "2026-06-15T13:01:00Z",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["scope"]["status"], "batch5_source_packet_to_batch4_outputs_completed")
            self.assertTrue((private_root / "weekly_private" / _DECISION_DATE / "weekly_report.md").exists())
            self.assertTrue((private_root / "weekly_private" / _DECISION_DATE / "action_table.csv").exists())
            self.assertTrue(self.paths["components"].exists())
            emitted_text = result.stdout + result.stderr
            self.assertNotIn("AAPL", emitted_text)
            self.assertNotIn("https://", emitted_text)
            self.assertNotIn("api_key", emitted_text.lower())

    def test_cli_batch4_failure_leaves_no_generated_residue_or_ticker_leak(self) -> None:
        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", {"fmp": "ok", "sec_edgar": "ok"})
            context_out = private_root / "context_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "runners" / "us_short_batch5_to_batch4_weekend_e2e.py"),
                    "--source-packet",
                    str(self.paths["packet"]),
                    "--batch4-template",
                    str(TEMPLATE),
                    "--account",
                    str(account),
                    "--provider-health",
                    str(health),
                    "--private-root",
                    str(private_root),
                    "--now-et",
                    "2026-06-15T09:00:00",
                    "--context-components-out",
                    str(self.paths["components"]),
                    "--context-out",
                    str(context_out),
                    "--bootstrap-lifecycle",
                    "--generated-at",
                    "2026-06-15T13:01:00Z",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            emitted_text = result.stdout + result.stderr
            self.assertNotIn("AAPL", emitted_text)
            self.assertNotIn("https://", emitted_text)
            self.assertNotIn("api_key", emitted_text.lower())
            self.assertFalse(self.paths["data_context"].exists())
            self.assertFalse(self.paths["components"].exists())
            self.assertFalse(context_out.exists())
            self.assertFalse(context_out.with_suffix(context_out.suffix + ".tmp").exists())
            self.assertFalse((private_root / "weekly_private").exists())
            self.assertFalse((private_root / "runs_private").exists())
            self.assertFalse((private_root / "lifecycle").exists())


if __name__ == "__main__":
    unittest.main()
