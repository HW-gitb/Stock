from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_egs_sample_validation as sv  # noqa: E402
from runners import us_short_batch5_full_candidate_live_source_packet as live  # noqa: E402
from runners import us_short_batch5_replay_pass2_source_packet_from_raw as replay  # noqa: E402


def _wrapper(provider_id, endpoint_family, symbol, payload, *, http_status=200, ok=True, error_type=None):
    return {"provider_id": provider_id, "endpoint_family": endpoint_family, "symbol": symbol,
            "http_status": http_status, "ok": ok, "error_type": error_type, "payload": payload}


class ReplayClientTest(unittest.TestCase):
    """The ReplayClient must resolve each URL the stage-5 runner builds back to the persisted wrapper and return its
    OWN (payload, http_status, ok, error_type) -- including replaying a rate-limited (ok=False) call as ok=False so
    the runner's graceful-degradation path is exercised exactly as during the real fetch."""

    def _seed(self, root: Path) -> None:
        # SEC ticker->CIK mapping (symbol=None -> _market bucket) + two per-ticker submissions with a `cik`.
        sv.write_json_atomic(_wrapper("sec_edgar", "company_tickers_mapping", None, {"0": {"cik_str": 320193, "ticker": "AAPL"}}),
                             sv.raw_sample_ref(root, "sec_edgar", "company_tickers_mapping", None))
        sv.write_json_atomic(_wrapper("sec_edgar", "submissions", "AAPL", {"cik": "0000320193", "filings": {}}),
                             sv.raw_sample_ref(root, "sec_edgar", "submissions", "AAPL"))
        sv.write_json_atomic(_wrapper("financial_modeling_prep", "grades", "AAPL", None, http_status=429, ok=False, error_type="http_error"),
                             sv.raw_sample_ref(root, "financial_modeling_prep", "grades", "AAPL"))
        sv.write_json_atomic(_wrapper("massive", "reference_news", "AAPL", {"results": [{"id": "n1"}]}),
                             sv.raw_sample_ref(root, "massive", "reference_news", "AAPL"))
        sv.write_json_atomic(_wrapper("massive", "stock_splits", "AAPL", {"results": []}),
                             sv.raw_sample_ref(root, "massive", "stock_splits", "AAPL"))
        sv.write_json_atomic(_wrapper("massive", "dividends", "AAPL", {"results": []}),
                             sv.raw_sample_ref(root, "massive", "dividends", "AAPL"))

    def test_each_url_resolves_to_its_persisted_wrapper(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._seed(root)
            client = replay.ReplayClient(root)

            # SEC mapping.
            payload, status, ok, err = client.get_json(sv.sec_url("company_tickers_mapping"))
            self.assertTrue(ok)
            self.assertEqual(payload["0"]["ticker"], "AAPL")

            # SEC submissions: URL carries CIK, resolved back to symbol via the submissions index.
            payload, status, ok, err = client.get_json(sv.sec_url("submissions", "0000320193"))
            self.assertTrue(ok)
            self.assertEqual(payload["cik"], "0000320193")

            # FMP grades replays the real 429 (ok=False) verbatim.
            payload, status, ok, err = client.get_json(live._fmp_stable_url("grades", "AAPL", "IGNORED_KEY"))
            self.assertFalse(ok)
            self.assertEqual(status, 429)

            # Massive news / splits / dividends resolve by ticker + path family.
            payload, status, ok, err = client.get_json(live.MASSIVE_NEWS_URL.format(ticker="AAPL", key="IGNORED"))
            self.assertEqual(payload["results"][0]["id"], "n1")
            for url_tpl in (live.MASSIVE_SPLITS_URL, live.MASSIVE_DIVIDENDS_URL):
                payload, status, ok, err = client.get_json(url_tpl.format(ticker="AAPL", key="IGNORED"))
                self.assertTrue(ok)
                self.assertEqual(payload["results"], [])

    def test_uncaptured_url_replays_as_failed_fetch(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._seed(root)
            client = replay.ReplayClient(root)
            payload, status, ok, err = client.get_json(live.MASSIVE_NEWS_URL.format(ticker="ZZZZ", key="IGNORED"))
            self.assertIsNone(payload)
            self.assertFalse(ok)
            self.assertEqual(err, "replay_missing")

    def test_empty_raw_root_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(replay.ReplayError):
                replay.ReplayClient(Path(d))


if __name__ == "__main__":
    unittest.main()
