"""Offline regression tests for CNINFO advisory-source observability."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location(
            "egs_main_cninfo_health_under_test", EGS_SCRIPT
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


class CninfoAdvisoryHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    @staticmethod
    def _candidate_frame() -> pd.DataFrame:
        return pd.DataFrame([{
            "ts_code": "600900.SH",
            "name": "fixture",
            "final_score": 80.0,
            "l1_name": "银行",
            "l2_name": "银行",
        }])

    def _run_stage3(self, response=None, *, post_side_effect=None):
        with patch("requests.post", return_value=response, side_effect=post_side_effect):
            return self.egs_main.stage3_ai_clearing(
                self._candidate_frame(),
                {"veto_10d": set()},
                set(),
            )

    @staticmethod
    def _response(payload, *, status_code=200):
        response = Mock()
        response.status_code = status_code
        response.json.return_value = payload
        return response

    def test_http_200_empty_response_is_unknown_and_emits_health_warning(self) -> None:
        result, checked, health = self._run_stage3(
            self._response({
                "announcements": None,
                "totalRecordNum": 0,
                "totalAnnouncement": 0,
            })
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["cninfo_flag"], "未检查")
        self.assertEqual(checked, {})
        self.assertEqual(health["status"], "unknown")
        self.assertEqual(health["unknown_count"], 1)
        self.assertEqual(health["unknown_reasons"], {"empty_announcements": 1})
        warning = self.egs_main._cninfo_health_warning(health)
        self.assertEqual(warning["check"], "cninfo_regulatory_advisory")
        self.assertIn("不得视为通过", warning["message"])

    def test_known_clear_response_remains_through_without_health_warning(self) -> None:
        result, checked, health = self._run_stage3(
            self._response({"announcements": [{"announcementTitle": "普通公告"}]})
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["cninfo_flag"], "通过")
        self.assertEqual(checked, {"600900.SH": "通过"})
        self.assertEqual(health["status"], "complete")
        self.assertEqual(health["known_clear_count"], 1)
        self.assertIsNone(self.egs_main._cninfo_health_warning(health))

    def test_regulator_hit_is_advisory_and_does_not_delete_candidate(self) -> None:
        result, checked, health = self._run_stage3(
            self._response({"announcements": [{"announcementTitle": "立案调查公告"}]})
        )

        self.assertEqual(len(result), 1)
        self.assertTrue(result.iloc[0]["cninfo_flag"].startswith("立案调查"))
        self.assertTrue(checked["600900.SH"].startswith("立案调查"))
        self.assertEqual(health["status"], "complete")
        self.assertEqual(health["advisory_hit_count"], 1)

    def test_non_success_or_malformed_response_is_fail_closed_and_counted(self) -> None:
        cases = {
            "http_status": (self._response({}, status_code=500), None),
            "invalid_payload": (self._response([], status_code=200), None),
            "invalid_announcements": (
                self._response({"announcements": {"bad": "shape"}}),
                None,
            ),
            "exception": (None, RuntimeError("offline fixture")),
        }

        for label, (response, error) in cases.items():
            with self.subTest(response=label):
                result, checked, health = self._run_stage3(
                    response, post_side_effect=error,
                )

                self.assertEqual(len(result), 1)
                self.assertEqual(result.iloc[0]["cninfo_flag"], "未检查")
                self.assertEqual(checked, {})
                self.assertEqual(health["status"], "unknown")
                self.assertEqual(health["unknown_count"], 1)
                self.assertEqual(health["unknown_reasons"], {label: 1})


if __name__ == "__main__":
    unittest.main()
