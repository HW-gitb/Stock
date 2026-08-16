from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_egs_sample_validation as sample_validation  # noqa: E402
from runners import us_short_massive_corporate_action_validation as validation  # noqa: E402
from tests.provider.us_short_private_test_root_light import temporary_us_short_state_directory  # noqa: E402


_FAKE_KEY = "FAKE-MASSIVE-KEY-must-not-appear-in-summary"


class _FakeMassiveClient:
    def __init__(self):
        self.urls: list[str] = []

    def get_json(self, url, headers=None, timeout_seconds=30):
        self.urls.append(url)
        assert _FAKE_KEY in url
        if "/stocks/v1/splits" in url:
            return ({"results": [{"ticker": "AAPL", "execution_date": "2020-08-31", "split_from": 1, "split_to": 4}]}, 200, True, None)
        if "/stocks/v1/dividends" in url:
            return ({"results": [{"ticker": "MSFT", "ex_dividend_date": "2026-05-14", "cash_amount": 0.83}]}, 200, True, None)
        assert "adjusted=" in url
        return ({"results": [{"ticker": "AAPL", "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 1000, "t": 1}]}, 200, True, None)


class MassiveCorporateActionValidationTest(unittest.TestCase):
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_root = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._orig_read_env = sample_validation.read_required_env
        self._orig_raw_ignored = validation._raw_root_is_gitignored
        self._orig_path = validation._repo_relative_path
        slug = f"massive_ca_validation_{__import__('os').getpid()}"
        self.tmp_raw = self.state_root / f"{slug}_raw"
        self.tmp_summary = self.state_root / f"{slug}_summary.json"
        sample_validation.read_required_env = lambda name: sample_validation.EnvValue(value=_FAKE_KEY, source="test")
        validation._raw_root_is_gitignored = lambda path: True

        def _temp_path(value, *, field):
            if field == "raw_payload_root":
                return self.tmp_raw
            if field == "tracked_summary_path":
                return self.tmp_summary
            raise AssertionError(field)

        validation._repo_relative_path = _temp_path

    def tearDown(self):
        sample_validation.read_required_env = self._orig_read_env
        validation._raw_root_is_gitignored = self._orig_raw_ignored
        validation._repo_relative_path = self._orig_path

    def test_frozen_packet_validates_and_has_exact_12_call_scope(self):
        packet = validation.load_packet()
        self.assertEqual([item["symbol"] for item in packet["sample"]], ["AAPL", "MSFT", "TSLA"])
        self.assertEqual(packet["scope"]["endpoint_families"], ["splits", "dividends", "daily_adjusted", "daily_unadjusted"])
        self.assertEqual(packet["execution"]["max_total_endpoint_calls"], 12)
        self.assertFalse(packet["boundary"]["corporate_action_reconciliation_performed"])

    def test_frozen_packet_rejects_extra_symbol_before_any_fetch(self):
        packet = validation.load_packet()
        broken = copy.deepcopy(packet)
        broken["sample"][2]["symbol"] = "NVDA"
        path = self.state_root / "massive_ca_validation_bad_packet.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(broken), encoding="utf-8")
        try:
            with self.assertRaises(validation.MassiveCorporateActionValidationError):
                validation.load_packet(path)
        finally:
            path.unlink(missing_ok=True)

    def test_missing_confirmation_aborts_before_fetch(self):
        client = _FakeMassiveClient()
        with self.assertRaises(validation.MassiveCorporateActionValidationError):
            validation.run_capture(confirm_user_authorization=False, client=client)
        self.assertEqual(client.urls, [])
        self.assertFalse(self.tmp_summary.exists())

    def test_non_gitignored_raw_root_aborts_before_key_read_or_fetch(self):
        client = _FakeMassiveClient()
        validation._raw_root_is_gitignored = lambda path: False
        with self.assertRaises(validation.MassiveCorporateActionValidationError):
            validation.run_capture(confirm_user_authorization=True, client=client)
        self.assertEqual(client.urls, [])
        self.assertFalse(self.tmp_summary.exists())

    def test_capture_hits_every_frozen_symbol_family_and_keeps_summary_value_free(self):
        client = _FakeMassiveClient()
        pauses: list[float] = []
        summary = validation.run_capture(
            confirm_user_authorization=True,
            client=client,
            sleep_func=pauses.append,
        )

        self.assertEqual(summary["scope"]["actual_total_endpoint_calls"], 12)
        self.assertEqual(len(client.urls), 12)
        self.assertEqual(pauses, [13] * 11)
        pairs = {(item["symbol"], item["endpoint_family"]) for item in summary["endpoint_results"]}
        self.assertEqual(len(pairs), 12)
        self.assertIn(("AAPL", "splits"), pairs)
        self.assertIn(("MSFT", "dividends"), pairs)
        self.assertIn(("TSLA", "daily_unadjusted"), pairs)
        self.assertTrue(self.tmp_summary.exists())
        text = self.tmp_summary.read_text(encoding="utf-8")
        self.assertNotIn(_FAKE_KEY, text)
        self.assertNotIn("api.massive.com", text.lower())
        self.assertNotIn('"payload"', text)
        self.assertNotIn("100.5", text)
        self.assertFalse(any(summary["boundary"].values()))
        self.assertEqual(len(list(self.tmp_raw.rglob("*.json"))), 12)


if __name__ == "__main__":
    unittest.main()
