from __future__ import annotations

import json
import shutil
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_short_massive_corporate_action_normalize as normalizer  # noqa: E402
from tests.provider.us_short_private_test_root import temporary_us_short_directory  # noqa: E402


def _ny_midnight_ms(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=ZoneInfo("America/New_York")).timestamp() * 1000)


def _wrapper(symbol: str, family: str) -> dict:
    if family.startswith("daily_"):
        adjusted = family == "daily_adjusted"
        payload = {
            "status": "OK",
            "ticker": symbol,
            "adjusted": adjusted,
            "results": [
                {"t": _ny_midnight_ms("2020-08-28"), "c": 25 if adjusted else 100},
                {"t": _ny_midnight_ms("2020-08-31"), "c": 26},
            ],
        }
    elif family == "splits":
        payload = {
            "status": "OK",
            "results": [
                {
                    "id": f"{symbol}-split-id",
                    "ticker": symbol,
                    "execution_date": "2020-08-31",
                    "split_from": 1,
                    "split_to": 4,
                }
            ],
        }
    else:
        payload = {
            "status": "OK",
            "results": []
            if symbol == "TSLA"
            else [
                {
                    "id": f"{symbol}-dividend-id",
                    "ticker": symbol,
                    "ex_dividend_date": "2021-05-07",
                }
            ],
        }
    return {
        "provider_id": "massive",
        "endpoint_family": family,
        "symbol": symbol,
        "http_status": 200,
        "ok": True,
        "error_type": None,
        "payload": payload,
    }


class MassiveCorporateActionNormalizeTest(unittest.TestCase):
    def setUp(self):
        self._sample_root_context = temporary_us_short_directory(ROOT, Path("provider_samples"))
        self.sample_root = Path(self._sample_root_context.__enter__())
        self.addCleanup(self._sample_root_context.__exit__, None, None, None)
        self.root = self.sample_root / f"test_massive_ca_normalize_{__import__('os').getpid()}"
        self.raw_root = self.root / "raw"
        self.output_root = self.root / "normalized"
        self._write_all_wrappers()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write_all_wrappers(self):
        for symbol in ("AAPL", "MSFT", "TSLA"):
            for family in ("splits", "dividends", "daily_adjusted", "daily_unadjusted"):
                self._write_wrapper(symbol, family, _wrapper(symbol, family))

    def _wrapper_path(self, symbol: str, family: str) -> Path:
        return self.raw_root / "massive" / symbol / f"{family}.json"

    def _write_wrapper(self, symbol: str, family: str, wrapper: dict) -> None:
        path = self._wrapper_path(symbol, family)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(wrapper), encoding="utf-8")

    def run_normalize(self, *, confirm=True):
        return normalizer.normalize_capture(
            confirm_user_authorization=confirm,
            raw_root=self.raw_root,
            output_root=self.output_root,
        )

    def test_normalizes_all_frozen_wrappers_into_private_source_bound_packets(self):
        result = self.run_normalize()
        self.assertEqual(result, {"normalized_packet_count": 3, "raw_wrapper_count": 12})
        packets = sorted(self.output_root.glob("*.json"))
        self.assertEqual(len(packets), 3)

        aapl = json.loads((self.output_root / "AAPL.json").read_text(encoding="utf-8"))
        self.assertEqual(aapl["schema_name"], "us_short_massive_corporate_action_normalized_packet")
        self.assertEqual(aapl["capture_binding"]["session_timezone"], "America/New_York")
        self.assertEqual(len(aapl["capture_binding"]["raw_wrapper_sha256"]), 4)
        self.assertEqual([event["event_type"] for event in aapl["normalized_events"]], ["split", "dividend"])
        self.assertEqual(len(aapl["normalized_price_rows"]), 4)
        self.assertTrue(aapl["boundary"]["raw_payload_read_and_normalized"])
        self.assertFalse(aapl["boundary"]["corporate_action_reconciliation_performed"])
        self.assertNotIn("payload", aapl)
        self.assertNotIn("request_url", aapl)

    def test_missing_confirmation_rejects_before_any_output(self):
        with self.assertRaises(normalizer.MassiveCorporateActionNormalizeError):
            self.run_normalize(confirm=False)
        self.assertFalse(self.output_root.exists())

    def test_non_new_york_midnight_timestamp_rejects_before_any_output(self):
        broken = _wrapper("AAPL", "daily_adjusted")
        broken["payload"]["results"][0]["t"] += 12 * 60 * 60 * 1000
        self._write_wrapper("AAPL", "daily_adjusted", broken)

        with self.assertRaises(normalizer.MassiveCorporateActionNormalizeError):
            self.run_normalize()
        self.assertFalse(self.output_root.exists())

    def test_mismatched_wrapper_identity_and_missing_wrapper_fail_closed(self):
        broken = _wrapper("AAPL", "splits")
        broken["payload"]["results"][0]["ticker"] = "MSFT"
        self._write_wrapper("AAPL", "splits", broken)
        with self.assertRaises(normalizer.MassiveCorporateActionNormalizeError):
            self.run_normalize()
        self.assertFalse(self.output_root.exists())

        self._write_wrapper("AAPL", "splits", _wrapper("AAPL", "splits"))
        self._wrapper_path("TSLA", "dividends").unlink()
        with self.assertRaises(normalizer.MassiveCorporateActionNormalizeError):
            self.run_normalize()
        self.assertFalse(self.output_root.exists())


if __name__ == "__main__":
    unittest.main()
