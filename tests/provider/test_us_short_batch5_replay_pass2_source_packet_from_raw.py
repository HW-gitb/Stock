from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_egs_sample_validation as sv  # noqa: E402
from runners import us_short_batch5_full_candidate_live_source_packet as live  # noqa: E402
from runners import us_short_batch5_replay_pass2_source_packet_from_raw as replay  # noqa: E402
from tests.provider.us_short_private_test_root import temporary_us_short_directory  # noqa: E402


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

    def _bound_summary(self, root: Path, summary_path: Path) -> dict:
        endpoint_results = []
        manifest_rows = []
        for wrapper_path in root.rglob("*.json"):
            wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
            endpoint_results.append({
                "provider_id": wrapper["provider_id"],
                "endpoint_family": wrapper["endpoint_family"],
                "symbol": wrapper["symbol"],
                "raw_sample_ref": sv.as_repo_relative(wrapper_path),
            })
            manifest_rows.append({
                "provider_id": wrapper["provider_id"],
                "endpoint_family": wrapper["endpoint_family"],
                "symbol": wrapper["symbol"],
                "sha256": hashlib.sha256(wrapper_path.read_bytes()).hexdigest(),
            })
        manifest_rows.sort(key=lambda row: (row["provider_id"], row["endpoint_family"], row["symbol"] or ""))
        summary = {
            "scope": {"network_access_performed": True, "provider_calls_performed": True},
            "decision_clock": {
                "observed_at": "2026-07-08T08:00:00-04:00",
                "expected_decision_date": "20260708",
                "source_as_of": "2026-07-08",
            },
            "storage": {
                "raw_payload_root": sv.as_repo_relative(root),
                "tracked_summary_path": sv.as_repo_relative(summary_path),
            },
            "endpoint_call_budget": {"max_total_endpoint_calls": 6, "actual_total_endpoint_calls": 6},
            "endpoint_results": endpoint_results,
            "raw_capture_manifest": {
                "endpoint_wrapper_sha256": manifest_rows,
                "manifest_sha256": hashlib.sha256(
                    json.dumps(manifest_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
            },
        }
        sv.write_json_atomic(summary, summary_path)
        return summary

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
            with self.assertRaises(replay.ReplayError):
                client.get_json(live.MASSIVE_NEWS_URL.format(ticker="ZZZZ", key="IGNORED"))

    def test_duplicate_or_extra_raw_wrapper_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._seed(root)
            # A second valid-shaped wrapper for the same provider/family/symbol must never silently win by traversal
            # order; a replay is source-bound to one exact raw capture, not a best-effort directory scan.
            (root / "duplicate.json").write_text(
                json.dumps(_wrapper("massive", "reference_news", "AAPL", {"results": [{"id": "rogue"}]})),
                encoding="utf-8",
            )
            with self.assertRaises(replay.ReplayError):
                replay.ReplayClient(root)

    def test_cik_collision_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._seed(root)
            sv.write_json_atomic(
                _wrapper("sec_edgar", "submissions", "MSFT", {"cik": "0000320193", "filings": {}}),
                sv.raw_sample_ref(root, "sec_edgar", "submissions", "MSFT"),
            )
            with self.assertRaises(replay.ReplayError):
                replay.ReplayClient(root)

    def test_bound_capture_rejects_root_alias_and_keeps_original_clock(self):
        root_context = temporary_us_short_directory(ROOT, Path("provider_samples"))
        provider_samples = Path(root_context.__enter__())
        self.addCleanup(root_context.__exit__, None, None, None)
        with tempfile.TemporaryDirectory(prefix="test_replay_source_", dir=str(provider_samples)) as root_dir, \
                tempfile.TemporaryDirectory(prefix="test_replay_output_", dir=str(provider_samples)) as replay_dir, \
                tempfile.TemporaryDirectory(prefix="test_replay_summary_", dir=str(provider_samples)) as summary_dir:
            root = Path(root_dir)
            replay_root = Path(replay_dir)
            summary_path = Path(summary_dir) / "capture_summary.json"
            self._seed(root)
            self._bound_summary(root, summary_path)
            with self.assertRaises(replay.ReplayError):
                replay.run_replay(
                    source_raw_root=root,
                    source_summary_path=summary_path,
                    preflight_summary_path=summary_path,
                    expected_total_call_budget=6,
                    output_prefix=replay_root / "out",
                    summary_path=replay_root / "summary.json",
                    replay_raw_root=root,
                )
            with mock.patch.object(replay.live_source_packet, "run_full_candidate_live_source_packet", return_value={}) as run, \
                    mock.patch.object(replay.live_source_packet, "_validate_preflight_path", return_value=summary_path), \
                    mock.patch.object(
                        replay.live_source_packet,
                        "_load_ready_preflight",
                        return_value={"decision_clock": {"expected_decision_date": "20260708"}},
                    ):
                replay.run_replay(
                    source_raw_root=root,
                    source_summary_path=summary_path,
                    preflight_summary_path=summary_path,
                    expected_total_call_budget=6,
                    output_prefix=replay_root / "out",
                    summary_path=replay_root / "summary.json",
                    replay_raw_root=replay_root,
                    observed_at="2026-07-08T08:00:00-04:00",
                )
            kwargs = run.call_args.kwargs
            self.assertFalse(kwargs["run_data_context"])
            self.assertEqual(kwargs["execution_mode"], "offline_replay")
            self.assertEqual(kwargs["observed_at"], "2026-07-08T08:00:00-04:00")
            self.assertTrue(kwargs["replay_source_capture"]["non_emittable"])
            self.assertEqual(kwargs["replay_source_capture"]["source_as_of"], "2026-07-08")

    def test_bound_capture_rejects_raw_mutation_and_wrong_preflight_date(self):
        root_context = temporary_us_short_directory(ROOT, Path("provider_samples"))
        provider_samples = Path(root_context.__enter__())
        self.addCleanup(root_context.__exit__, None, None, None)
        with tempfile.TemporaryDirectory(prefix="test_replay_source_", dir=str(provider_samples)) as root_dir, \
                tempfile.TemporaryDirectory(prefix="test_replay_summary_", dir=str(provider_samples)) as summary_dir:
            root = Path(root_dir)
            summary_path = Path(summary_dir) / "capture_summary.json"
            self._seed(root)
            self._bound_summary(root, summary_path)
            mutated = sv.raw_sample_ref(root, "massive", "reference_news", "AAPL")
            wrapper = json.loads(mutated.read_text(encoding="utf-8"))
            wrapper["payload"] = {"results": [{"id": "mutated"}]}
            sv.write_json_atomic(wrapper, mutated)
            with self.assertRaisesRegex(replay.ReplayError, "bytes drift"):
                replay._load_bound_source_capture(
                    source_summary_path=summary_path,
                    source_raw_root=root,
                    expected_total_call_budget=6,
                )
            self._seed(root)
            self._bound_summary(root, summary_path)
            with mock.patch.object(replay.live_source_packet, "_validate_preflight_path", return_value=summary_path), \
                    mock.patch.object(
                        replay.live_source_packet,
                        "_load_ready_preflight",
                        return_value={"decision_clock": {"expected_decision_date": "20260709"}},
                    ):
                with self.assertRaisesRegex(replay.ReplayError, "decision date"):
                    replay.run_replay(
                        source_raw_root=root,
                        source_summary_path=summary_path,
                        preflight_summary_path=summary_path,
                        expected_total_call_budget=6,
                        output_prefix=root / "out",
                        summary_path=root / "replay_summary.json",
                        replay_raw_root=root / "replay_raw",
                    )

    def test_direct_offline_mode_rejects_unbound_client(self):
        with self.assertRaisesRegex(live.FullCandidateLiveSourcePacketError, "manifest-bound ReplayClient"):
            live.run_full_candidate_live_source_packet(
                preflight_summary_path=Path("unused.json"),
                expected_total_call_budget=1,
                run_data_context=False,
                client=object(),
                execution_mode="offline_replay",
                replay_source_capture={},
            )

    def test_direct_bound_offline_mode_locks_clock_before_artifact_work(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._seed(root)
            expected = {}
            for wrapper_path in root.rglob("*.json"):
                wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
                key = (wrapper["provider_id"], wrapper["endpoint_family"], wrapper["symbol"])
                expected[key] = (wrapper_path.resolve(), hashlib.sha256(wrapper_path.read_bytes()).hexdigest())
            capture = {
                "source_observed_at": "2026-07-08T08:00:00-04:00",
                "source_expected_decision_date": "20260708",
                "source_as_of": "2026-07-08",
            }
            client = replay.ReplayClient(root, expected_records=expected, bound_capture=capture)
            with self.assertRaisesRegex(live.FullCandidateLiveSourcePacketError, "observed_at must match"):
                live.run_full_candidate_live_source_packet(
                    preflight_summary_path=Path("unused.json"),
                    expected_total_call_budget=1,
                    run_data_context=False,
                    client=client,
                    execution_mode="offline_replay",
                    replay_source_capture=capture,
                    observed_at="2026-07-09T08:00:00-04:00",
                )
            with mock.patch.object(live, "_validate_preflight_path", return_value=Path("unused.json")), \
                    mock.patch.object(
                        live,
                        "_load_ready_preflight",
                        return_value={"decision_clock": {"expected_decision_date": "20260709"}},
                    ):
                with self.assertRaisesRegex(live.FullCandidateLiveSourcePacketError, "preflight decision clock"):
                    live.run_full_candidate_live_source_packet(
                        preflight_summary_path=Path("unused.json"),
                        expected_total_call_budget=1,
                        run_data_context=False,
                        client=client,
                        execution_mode="offline_replay",
                        replay_source_capture=capture,
                    )

    def test_empty_raw_root_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(replay.ReplayError):
                replay.ReplayClient(Path(d))


if __name__ == "__main__":
    unittest.main()
