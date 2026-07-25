from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


MODULE = "runners.us_short_llm_theme_discovery"
STATE_DIR = ROOT / "state" / "us_short"


def _runner():
    return importlib.import_module(MODULE)


def _payload():
    return {
        "source_refs": [
            {"source_id": "web:ai-storage-1", "source_type": "web", "observed_at": "2026-06-12T12:00:00Z"},
            {"source_id": "x:ai-storage-1", "source_type": "x", "observed_at": "2026-06-12T12:05:00Z"},
            {"source_id": "llm:ai-storage-1", "source_type": "llm", "observed_at": "2026-06-12T12:10:00Z"},
        ],
        "themes": [
            {
                "theme_id": "ai_storage",
                "display_name": "AI storage",
                "summary": "A provisional cross-industry theme discovered from local source references.",
                "observed_at": "2026-06-12T12:15:00Z",
                "source_ref_ids": ["web:ai-storage-1", "x:ai-storage-1", "llm:ai-storage-1"],
                "members": [
                    {"ticker": "msft", "source_ref_ids": ["llm:ai-storage-1"]},
                    {"ticker": "AAPL", "source_ref_ids": ["web:ai-storage-1", "x:ai-storage-1"]},
                ],
            }
        ],
    }


class OfflineLLMThemeDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_llm_theme_discovery_{os.getpid()}_{self._testMethodName}"
        self.input_path = STATE_DIR / f"{self.slug}_input.json"
        self.output_path = STATE_DIR / f"{self.slug}_output.json"
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.input_path.unlink(missing_ok=True)
        self.output_path.unlink(missing_ok=True)
        self.input_path.write_text(json.dumps(_payload(), ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.input_path.unlink(missing_ok=True)
        self.output_path.unlink(missing_ok=True)

    def test_run_packet_freezes_source_bound_provisional_artifact_without_effect(self):
        runner = _runner()
        summary = runner.run_packet(
            input_path=self.input_path,
            output_path=self.output_path,
            expected_decision_date="20260615",
            generated_at="2026-06-12T12:20:00Z",
        )
        self.assertTrue(self.output_path.exists())
        self.assertEqual(summary["status"], "offline_discovery_artifact_written")
        self.assertFalse(summary["network_access_performed"])
        self.assertFalse(summary["scoring_or_top15_effect"])
        self.assertFalse(summary["operation_advice_effect"])
        artifact = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertEqual(artifact["discovery_contract"]["membership_status"], "provisional_unvalidated")
        self.assertFalse(artifact["discovery_contract"]["scoring_eligible"])
        self.assertFalse(artifact["discovery_contract"]["top15_effect_enabled"])
        self.assertFalse(artifact["discovery_contract"]["operation_advice_effect_enabled"])
        self.assertEqual(artifact["themes"][0]["members"][0]["ticker"], "AAPL")
        self.assertEqual(artifact["themes"][0]["status"], "provisional_discovered")
        self.assertEqual(artifact["themes"][0]["market_confirmation_status"], "not_run")

    def test_preflight_does_not_write_output(self):
        runner = _runner()
        result = runner.run_preflight(
            input_path=self.input_path,
            output_path=self.output_path,
            expected_decision_date="20260615",
            generated_at="2026-06-12T12:20:00Z",
        )
        self.assertEqual(result["status"], "offline_preflight_passed")
        self.assertEqual(result["theme_count"], 1)
        self.assertEqual(result["member_count"], 2)
        self.assertFalse(self.output_path.exists())

    def test_future_source_is_rejected_before_write(self):
        payload = _payload()
        payload["source_refs"][0]["observed_at"] = "2026-06-15T13:31:00Z"  # 09:31 ET after the open
        self.input_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(_runner().LLMThemeDiscoveryError, "before the decision open"):
            _runner().run_packet(
                input_path=self.input_path,
                output_path=self.output_path,
                expected_decision_date="20260615",
                generated_at="2026-06-12T12:20:00Z",
            )
        self.assertFalse(self.output_path.exists())

    def test_member_source_must_be_bound_to_theme_sources(self):
        payload = _payload()
        payload["themes"][0]["members"][0]["source_ref_ids"] = ["web:not-declared"]
        self.input_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(_runner().LLMThemeDiscoveryError):
            _runner().run_preflight(
                input_path=self.input_path,
                output_path=self.output_path,
                expected_decision_date="20260615",
                generated_at="2026-06-12T12:20:00Z",
            )

    def test_operational_score_injection_is_rejected(self):
        payload = _payload()
        payload["themes"][0]["score"] = 99
        self.input_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(_runner().LLMThemeDiscoveryError, "operational fields"):
            _runner().run_preflight(
                input_path=self.input_path,
                output_path=self.output_path,
                expected_decision_date="20260615",
                generated_at="2026-06-12T12:20:00Z",
            )

    def test_non_ascii_or_a_share_identity_is_rejected(self):
        for ticker in ("ſAPL", "000001.SZ"):
            payload = _payload()
            payload["themes"][0]["members"][0]["ticker"] = ticker
            self.input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(_runner().LLMThemeDiscoveryError):
                _runner().run_preflight(
                    input_path=self.input_path,
                    output_path=self.output_path,
                    expected_decision_date="20260615",
                    generated_at="2026-06-12T12:20:00Z",
                )

    def test_secret_like_source_id_is_rejected(self):
        payload = _payload()
        payload["source_refs"][0]["source_id"] = "web:api_key"
        self.input_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(_runner().LLMThemeDiscoveryError):
            _runner().run_preflight(
                input_path=self.input_path,
                output_path=self.output_path,
                expected_decision_date="20260615",
                generated_at="2026-06-12T12:20:00Z",
            )


if __name__ == "__main__":
    unittest.main()
