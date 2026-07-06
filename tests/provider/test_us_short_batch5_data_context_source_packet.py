from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_catalyst import load_catalyst_governance  # noqa: E402
from engine.us_short_fmp_analyst_grades import resolve_analyst_grade_actions  # noqa: E402
from engine.us_short_massive_news import resolve_news_events  # noqa: E402
from engine.us_short_sec_offering_audit import resolve_offering_audit  # noqa: E402
from runners.us_short_batch5_data_context_source_packet import (  # noqa: E402
    SourcePacketError,
    run_packet,
    run_preflight,
)
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _GRADE_AS_OF,
    _NEWS_AS_OF,
    _OFFERING_AS_OF,
    _candidate_artifact,
    _checked_offering,
    _constant_projection,
    _grade_record,
    _grade_source,
    _news_item,
    _news_source,
    _offering_record,
    _offering_source,
)


STATE_DIR = ROOT / "state" / "us_short"


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class Batch5DataContextSourcePacketTest(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_source_packet_{os.getpid()}_{self._testMethodName}"
        self.paths = {
            "packet": STATE_DIR / f"{self.slug}_packet.json",
            "candidate": STATE_DIR / f"{self.slug}_candidate.json",
            "momentum": STATE_DIR / f"{self.slug}_momentum.json",
            "theme": STATE_DIR / f"{self.slug}_theme.json",
            "offering": STATE_DIR / f"{self.slug}_offering.json",
            "analyst": STATE_DIR / f"{self.slug}_analyst.json",
            "news": STATE_DIR / f"{self.slug}_news.json",
            "output": STATE_DIR / f"{self.slug}_data_context.json",
            "components": STATE_DIR / f"{self.slug}_context_components.json",
            "raw_payload": ROOT / "provider_samples" / f"{self.slug}_raw_payload.json",
        }
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        self.packet = self._write_sources_and_packet()

    def tearDown(self):
        for path in self.paths.values():
            path.unlink(missing_ok=True)

    def _write_sources_and_packet(self):
        targets = ("AAPL", "MSFT")
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "MSFT", "JPM")))
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
            _offering_source(
                checked={
                    "AAPL": {"active_offering": _checked_offering()},
                    "MSFT": {"active_offering": _checked_offering()},
                },
                excluded={"JPM": {"active_offering": "coverage=partial/parser=ok"}},
            ),
        )
        _write_json(
            self.paths["analyst"],
            resolve_analyst_grade_actions(
                as_of=_GRADE_AS_OF,
                grades_by_ticker={
                    "AAPL": _grade_source(
                        "AAPL",
                        [
                            _grade_record("AAPL", date="2026-06-10", company="BankA"),
                            _grade_record("AAPL", date="2026-06-11", company="BankB"),
                        ],
                    ),
                    "MSFT": _grade_source("MSFT", []),
                },
            ),
        )
        _write_json(
            self.paths["news"],
            resolve_news_events(
                as_of=_NEWS_AS_OF,
                news_by_ticker={
                    "AAPL": _news_source("AAPL", [_news_item(id="a", sentiment="positive")]),
                    "MSFT": _news_source("MSFT", []),
                },
            ),
        )
        packet = {
            "schema_name": "us_short_batch5_data_context_source_packet",
            "schema_version": "1.0.0",
            "generated_at": "2026-07-04T00:00:00Z",
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
                "theme_opportunity_state": "strong",
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
                "output_data_context_path": _rel(self.paths["output"]),
            },
            "optional_inputs": {
                "holdings": [],
                "catalyst_recall_feed": None,
            },
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
        }
        return _write_json(self.paths["packet"], packet)

    def _packet_payload(self):
        return json.loads(self.paths["packet"].read_text(encoding="utf-8"))

    def test_preflight_validates_local_source_packet_without_writing_output(self):
        result = run_preflight(self.packet, generated_at="2026-07-04T00:00:01Z")

        self.assertFalse(self.paths["output"].exists())
        self.assertEqual(result["scope"]["preflight_status"], "offline_preflight_passed")
        self.assertFalse(result["scope"]["network_access_required"])
        self.assertFalse(result["scope"]["provider_calls_performed"])
        self.assertTrue(result["preflight_checks"]["packet_contract_validated"])
        self.assertTrue(result["preflight_checks"]["output_path_gitignored"])

    def test_run_packet_writes_data_context_from_resolved_sources(self):
        result = run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")

        self.assertEqual(result["scope"]["assembly_status"], "data_context_assembled_from_resolved_sources")
        self.assertFalse(result["scope"]["network_access_required"])
        self.assertFalse(result["scope"]["provider_calls_performed"])
        self.assertEqual(result["data_context"]["output_path"], _rel(self.paths["output"]))
        written = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        self.assertEqual(written["candidate_pass2_signals"]["JPM"], {"critical_data_missing": True})
        self.assertEqual(set(written["selection_inputs"]["per_ticker"]), {"AAPL", "MSFT"})
        self.assertAlmostEqual(written["selection_inputs"]["per_ticker"]["AAPL"]["core_score"], 43.5)
        self.assertAlmostEqual(written["selection_inputs"]["per_ticker"]["MSFT"]["core_score"], 50.0)

    def test_run_packet_optionally_writes_official_context_components(self):
        _write_json(
            self.paths["offering"],
            resolve_offering_audit(
                as_of=_OFFERING_AS_OF,
                filings_by_ticker={
                    "AAPL": _offering_record([]),
                    "MSFT": _offering_record([]),
                    "JPM": _offering_record([], coverage="partial"),
                },
            ),
        )
        packet = self._packet_payload()
        packet["paths"]["output_context_components_path"] = _rel(self.paths["components"])
        _write_json(self.paths["packet"], packet)

        result = run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")

        self.assertTrue(result["scope"]["context_components_written"])
        self.assertEqual(result["context_components"]["output_path"], _rel(self.paths["components"]))
        components = json.loads(self.paths["components"].read_text(encoding="utf-8"))
        self.assertEqual(set(components), {"data_context", "per_ticker_analysis", "run_provenance"})
        self.assertEqual(set(components["per_ticker_analysis"]), {"AAPL", "MSFT"})
        self.assertEqual(
            components["per_ticker_analysis"]["AAPL"]["row_source"],
            "top15_candidate",
        )
        source_refs = components["run_provenance"]["families"]["candidate_pass2_signals"]["source_refs"]
        self.assertIn(
            {"role": "offering_audit_source", "path": _rel(self.paths["offering"])},
            source_refs,
        )

    def test_output_path_must_be_gitignored_state_file(self):
        packet = self._packet_payload()
        packet["paths"]["output_data_context_path"] = "docs/us_short_leaky_data_context.json"
        _write_json(self.paths["packet"], packet)

        with self.assertRaises(SourcePacketError):
            run_packet(self.packet, generated_at="2026-07-04T00:00:03Z")
        self.assertFalse((ROOT / "docs" / "us_short_leaky_data_context.json").exists())

    def test_scope_creep_flag_is_rejected(self):
        packet = self._packet_payload()
        packet["scope"]["network_access_performed"] = True
        _write_json(self.paths["packet"], packet)

        with self.assertRaises(SourcePacketError):
            run_preflight(self.packet)
        self.assertFalse(self.paths["output"].exists())

    def test_missing_source_artifact_rejected_before_write(self):
        self.paths["news"].unlink()

        with self.assertRaises(SourcePacketError):
            run_packet(self.packet, generated_at="2026-07-04T00:00:04Z")
        self.assertFalse(self.paths["output"].exists())

    def test_source_artifacts_must_not_point_at_provider_samples_raw_payloads(self):
        _write_json(self.paths["raw_payload"], {"raw": True})
        packet = self._packet_payload()
        packet["paths"]["massive_news_events_path"] = _rel(self.paths["raw_payload"])
        _write_json(self.paths["packet"], packet)

        with self.assertRaises(SourcePacketError):
            run_preflight(self.packet, generated_at="2026-07-04T00:00:05Z")
        self.assertFalse(self.paths["output"].exists())

    def test_preflight_rejects_non_gitignored_packet_path_before_write(self):
        leaky_packet = ROOT / "docs" / f"{self.slug}_packet.json"
        self.addCleanup(leaky_packet.unlink, missing_ok=True)
        _write_json(leaky_packet, self._packet_payload())

        with self.assertRaises(SourcePacketError):
            run_preflight(leaky_packet, generated_at="2026-07-04T00:00:05Z")
        self.assertFalse(self.paths["output"].exists())

    def test_malformed_catalyst_governance_is_wrapped_by_packet_runner(self):
        bad_governance = STATE_DIR / f"{self.slug}_bad_catalyst_governance.json"
        self.paths["bad_governance"] = bad_governance
        _write_json(bad_governance, {"broken": True})
        packet = self._packet_payload()
        packet["paths"]["catalyst_governance_path"] = _rel(bad_governance)
        _write_json(self.paths["packet"], packet)

        with self.assertRaises(SourcePacketError):
            run_packet(self.packet, generated_at="2026-07-04T00:00:06Z")
        self.assertFalse(self.paths["output"].exists())

    def test_preflight_rejects_wrong_shape_root_packet(self):
        _write_json(self.paths["packet"], ["not", "an", "object"])

        with self.assertRaises(SourcePacketError):
            run_preflight(self.packet)


if __name__ == "__main__":
    unittest.main()
