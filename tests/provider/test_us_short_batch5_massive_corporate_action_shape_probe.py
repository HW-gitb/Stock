from __future__ import annotations

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

from runners import us_short_batch5_massive_corporate_action_shape_probe as probe  # noqa: E402
from runners import us_egs_sample_validation as sample_validation  # noqa: E402
from tests.provider.us_short_private_test_root_light import temporary_us_short_state_directory  # noqa: E402


_FAKE_KEY = "FAKE-MASSIVE-KEY-should-never-appear-in-tracked-summary"


class _FakeMassiveClient:
    """Returns a plausible Massive/Polygon-style corporate-action envelope; asserts the api key IS in the
    request URL (so the secret-scan test is meaningful), but the URL never reaches the tracked summary."""

    def __init__(self):
        self.urls: list[str] = []

    def get_json(self, url, headers=None, timeout_seconds=30):
        self.urls.append(url)
        assert _FAKE_KEY in url  # the key travels in the URL -> must be scrubbed from the tracked summary
        if "/splits" in url:
            payload = {
                "results": [
                    {"ticker": "AAPL", "execution_date": "2020-08-31", "split_from": 1, "split_to": 4},
                ],
                "status": "OK",
                "next_url": "https://api.massive.com/stocks/v1/splits?cursor=abc",
            }
        else:
            payload = {
                "results": [
                    {"ticker": "AAPL", "ex_dividend_date": "2026-05-09", "cash_amount": 0.25, "pay_date": "2026-05-16"},
                ],
                "status": "OK",
            }
        return (payload, 200, True, None)


class MassiveCorporateActionShapeProbeTest(unittest.TestCase):
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_root = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._orig_summary = probe.SUMMARY_PATH
        self._orig_raw = probe.RAW_SAMPLE_ROOT
        self._orig_read_env = sample_validation.read_required_env
        self._orig_gitignored = probe._provider_samples_gitignored
        slug = f"ca_shape_probe_{__import__('os').getpid()}"
        self.tmp_summary = self.state_root / f"{slug}_summary.json"
        self.tmp_raw = self.state_root / f"{slug}_raw"
        probe.SUMMARY_PATH = self.tmp_summary
        probe.RAW_SAMPLE_ROOT = self.tmp_raw
        probe._provider_samples_gitignored = lambda: True  # temp dir is not gitignored; bypass the check
        sample_validation.read_required_env = lambda name: sample_validation.EnvValue(value=_FAKE_KEY, source="test")

    def tearDown(self):
        probe.SUMMARY_PATH = self._orig_summary
        probe.RAW_SAMPLE_ROOT = self._orig_raw
        probe._provider_samples_gitignored = self._orig_gitignored
        sample_validation.read_required_env = self._orig_read_env

    def test_dry_run_env_makes_no_network_call(self):
        self.assertEqual(probe.main(["--dry-run-env"]), 0)
        self.assertFalse(self.tmp_summary.exists())

    def test_missing_authorization_aborts_before_any_fetch(self):
        with self.assertRaises(probe.MassiveCorporateActionShapeProbeError):
            probe.run_probe(confirm_user_authorization=False, client=_FakeMassiveClient())
        self.assertFalse(self.tmp_summary.exists())

    def test_off_allowlist_family_url_raises(self):
        with self.assertRaises(probe.MassiveCorporateActionShapeProbeError):
            probe._url_for("earnings", "AAPL", _FAKE_KEY)

    def test_probe_records_shape_and_writes_a_clean_secret_free_summary(self):
        client = _FakeMassiveClient()
        summary = probe.run_probe(confirm_user_authorization=True, client=client)

        # 2 symbols x 2 families = 4 calls; the key traveled in every request URL.
        self.assertEqual(summary["scope"]["actual_total_endpoint_calls"], 4)
        self.assertEqual(len(client.urls), 4)
        # Shape captured: the real field NAMES are recorded (so the binding can be built on them), no values.
        self.assertIn("split_to", summary["shape_findings"]["splits"]["event_item_key_names"])
        self.assertIn("ex_dividend_date", summary["shape_findings"]["dividends"]["event_item_key_names"])
        self.assertEqual(summary["shape_findings"]["splits"]["http_status_classes"], [200])
        # Gate flags all pinned closed.
        self.assertFalse(any(summary["gate_flags"].values()))
        # Tracked summary written, schema-valid, and carries NO secret / URL / raw payload.
        self.assertTrue(self.tmp_summary.exists())
        text = self.tmp_summary.read_text(encoding="utf-8")
        self.assertNotIn(_FAKE_KEY, text)
        self.assertNotIn("api.massive.com", text.lower())
        self.assertNotIn("https://", text.lower())
        self.assertNotIn("\"payload\"", text)
        # Raw payload IS stored under the (temp) gitignored root and DOES carry the values.
        raw_files = list(self.tmp_raw.rglob("*.json"))
        self.assertEqual(len(raw_files), 4)


if __name__ == "__main__":
    unittest.main()
