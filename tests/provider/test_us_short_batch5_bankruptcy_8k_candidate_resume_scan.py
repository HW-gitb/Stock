from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402
from tests.provider.test_us_short_batch5_bankruptcy_8k_candidate_scan import (  # noqa: E402
    FakeSecClient,
    _candidate_artifact_many,
    _read_json,
    _write_json,
)
from tests.provider.test_us_short_batch5_data_context import _DECISION_DATE  # noqa: E402
from tests.provider.us_short_private_test_root import (  # noqa: E402
    temporary_us_short_directory,
    temporary_us_short_state_directory,
)


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_bankruptcy_8k_candidate_resume_scan_20260705"
MODULE = "runners.us_short_batch5_bankruptcy_8k_candidate_resume_scan"


def _symbols(count: int) -> tuple[str, ...]:
    return tuple(f"T{idx:03d}" for idx in range(count))


class Bankruptcy8kCandidateResumeScanTest(unittest.TestCase):
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_dir = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._sample_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_bankruptcy_8k_candidate_resume_scan_20260705"
        )
        self.sample_root = Path(self._sample_root_context.__enter__())
        self.addCleanup(self._sample_root_context.__exit__, None, None, None)
        import importlib

        producer = importlib.import_module(MODULE)
        original_git_ignored = producer._git_ignored
        state_root = self.state_dir.resolve()

        def _git_ignored_for_private_test(path):
            resolved = Path(path).resolve()
            if resolved == state_root or state_root in resolved.parents:
                return True
            return original_git_ignored(path)

        producer._git_ignored = _git_ignored_for_private_test
        self.addCleanup(setattr, producer, "_git_ignored", original_git_ignored)
        self.slug = f"test_b8kresume_{os.getpid()}_{self._testMethodName[:20]}"
        self.symbols = _symbols(115)
        self.paths = {
            "candidate": self.state_dir / f"{self.slug}_candidate.json",
            "manifest": self.state_dir / f"{self.slug}_manifest.json",
            "source_packet": self.state_dir / f"{self.slug}_packet.json",
            "screen": self.state_dir / f"{self.slug}_screen.json",
            "producer_summary": ROOT / "docs" / f"{self.slug}_summary.json",
            "consumer_summary": ROOT / "docs" / f"{self.slug}_consumer_summary.json",
        }
        self.raw_root = self.sample_root / self.slug / "raw"
        for path in self.paths.values():
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".tmp").unlink(missing_ok=True)
        _write_json(self.paths["candidate"], _candidate_artifact_many(self.symbols))

    def tearDown(self):
        for path in self.paths.values():
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".tmp").unlink(missing_ok=True)

    def _env(self, producer):
        return mock.patch.dict(
            producer.sample_validation.os.environ,
            {"SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com"},
            clear=False,
        )

    def _successful_submission_wrapper(self, producer, symbol: str = "T050") -> dict:
        return {
            "ok": True,
            "provider_id": "sec_edgar",
            "endpoint_family": producer.ENDPOINT_SUBMISSIONS,
            "symbol": symbol,
            "http_status": 200,
            "error_type": None,
            "payload": {"filings": {"recent": {"form": [], "filingDate": [], "accessionNumber": [], "items": []}}},
        }

    def _manifest_with_raw_ref(self, raw_ref: str, symbol: str = "T050") -> dict:
        return {
            "completed_shards": [
                {
                    "shard_index": 2,
                    "source": "resume_scan",
                    "round_index": 1,
                    "symbols": [symbol],
                    "raw_refs_by_symbol": {symbol: raw_ref},
                    "completed_at": "2026-07-05T12:00:00+00:00",
                }
            ]
        }

    def test_preflight_selects_next_unfinished_shards_and_writes_nothing(self):
        import importlib

        producer = importlib.import_module(MODULE)
        result = producer.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            manifest_path=self.paths["manifest"],
            output_source_packet_path=self.paths["source_packet"],
            output_screen_path=self.paths["screen"],
            summary_path=self.paths["producer_summary"],
            consumer_summary_path=self.paths["consumer_summary"],
            raw_root=self.raw_root,
            round_index=1,
            max_shards_per_round=2,
            precompleted_shard_indices=[0, 1],
            generated_at="2026-07-05T12:00:00+00:00",
        )

        self.assertEqual(result["round_plan"]["target_shard_indices"], [2, 3])
        self.assertEqual(result["round_plan"]["target_symbol_count"], 50)
        self.assertEqual(result["endpoint_call_budget"]["planned_total_endpoint_calls"], 51)
        self.assertFalse(result["scope"]["network_access_performed"])
        self.assertFalse(self.paths["manifest"].exists())
        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["producer_summary"].exists())

    def test_preflight_resume_stays_inside_the_same_round_window(self):
        import importlib

        producer = importlib.import_module(MODULE)
        wide_symbols = _symbols(180)
        _write_json(self.paths["candidate"], _candidate_artifact_many(wide_symbols))
        context = producer._candidate_context(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            exclude_symbols=[],
        )
        manifest = producer._manifest_base(
            context=context,
            candidate_artifact_path=self.paths["candidate"],
            manifest_path=self.paths["manifest"],
            precompleted_shard_indices=[0, 1],
            generated_at="2026-07-05T12:00:00+00:00",
        )
        manifest["completed_shards"].append(
            {
                "shard_index": 2,
                "source": "resume_scan",
                "round_index": 1,
                "symbols": context["eligible_symbols"][50:75],
                "raw_refs_by_symbol": {},
                "completed_at": "2026-07-05T12:00:00+00:00",
            }
        )
        manifest["completed_shard_indices"] = [0, 1, 2]
        manifest["resume_completed_shard_indices"] = [2]
        _write_json(self.paths["manifest"], manifest)

        result = producer.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            manifest_path=self.paths["manifest"],
            output_source_packet_path=self.paths["source_packet"],
            output_screen_path=self.paths["screen"],
            summary_path=self.paths["producer_summary"],
            consumer_summary_path=self.paths["consumer_summary"],
            raw_root=self.raw_root,
            round_index=1,
            max_shards_per_round=3,
            exclude_symbols=[],
            precompleted_shard_indices=[0, 1],
            generated_at="2026-07-05T12:00:00+00:00",
        )

        self.assertEqual(result["round_plan"]["target_shard_indices"], [3, 4])
        self.assertEqual(result["round_plan"]["target_symbol_count"], 50)

    def test_preflight_allows_finalize_only_when_round_window_already_fetched(self):
        import importlib

        producer = importlib.import_module(MODULE)
        wide_symbols = _symbols(180)
        _write_json(self.paths["candidate"], _candidate_artifact_many(wide_symbols))
        context = producer._candidate_context(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            exclude_symbols=[],
        )
        manifest = producer._manifest_base(
            context=context,
            candidate_artifact_path=self.paths["candidate"],
            manifest_path=self.paths["manifest"],
            precompleted_shard_indices=[0, 1],
            generated_at="2026-07-05T12:00:00+00:00",
        )
        for shard_index in [2, 3, 4]:
            manifest["completed_shards"].append(
                {
                    "shard_index": shard_index,
                    "source": "resume_scan",
                    "round_index": 1,
                    "symbols": context["eligible_symbols"][shard_index * 25 : (shard_index + 1) * 25],
                    "raw_refs_by_symbol": {},
                    "completed_at": "2026-07-05T12:00:00+00:00",
                }
            )
        manifest["completed_shard_indices"] = [0, 1, 2, 3, 4]
        manifest["resume_completed_shard_indices"] = [2, 3, 4]
        _write_json(self.paths["manifest"], manifest)

        result = producer.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            manifest_path=self.paths["manifest"],
            output_source_packet_path=self.paths["source_packet"],
            output_screen_path=self.paths["screen"],
            summary_path=self.paths["producer_summary"],
            consumer_summary_path=self.paths["consumer_summary"],
            raw_root=self.raw_root,
            round_index=1,
            max_shards_per_round=3,
            exclude_symbols=[],
            precompleted_shard_indices=[0, 1],
            generated_at="2026-07-05T12:00:00+00:00",
        )

        self.assertTrue(result["round_plan"]["finalize_only"])
        self.assertEqual(result["round_plan"]["target_shard_indices"], [])
        self.assertEqual(result["endpoint_call_budget"]["planned_total_endpoint_calls"], 0)

    def test_authorized_round_fetches_many_shards_once_and_writes_manifest_packet_screen(self):
        import importlib

        producer = importlib.import_module(MODULE)
        client = FakeSecClient(self.symbols)
        with self._env(producer), mock.patch.object(
            producer.sample_validation, "_read_windows_environment_value", return_value=None
        ), mock.patch.object(producer.time, "sleep"):
            summary = producer.run_resume_round(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                manifest_path=self.paths["manifest"],
                output_source_packet_path=self.paths["source_packet"],
                output_screen_path=self.paths["screen"],
                summary_path=self.paths["producer_summary"],
                consumer_summary_path=self.paths["consumer_summary"],
                raw_root=self.raw_root,
                round_index=1,
                max_shards_per_round=2,
                precompleted_shard_indices=[0, 1],
                client=client,
                confirm_user_authorization=True,
                generated_at="2026-07-05T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
                sec_sleep_seconds=0,
            )

        self.assertEqual(summary["round_plan"]["round_index"], 1)
        self.assertEqual(summary["round_plan"]["target_shard_indices"], [2, 3])
        self.assertEqual(summary["round_plan"]["target_symbol_count"], 50)
        self.assertEqual(len(client.urls), 51)
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 51)
        self.assertFalse(summary["scope"]["full_candidate_universe_scan_completed"])
        self.assertFalse(summary["scope"]["run_fetch_invoked"])
        self.assertFalse(summary["scope"]["status_records_written"])
        self.assertFalse(summary["scope"]["datahub_consumption_performed"])

        manifest = _read_json(self.paths["manifest"])
        self.assertEqual(manifest["completed_shard_indices"], [0, 1, 2, 3])
        self.assertEqual(manifest["resume_completed_shard_indices"], [2, 3])
        self.assertEqual(len(manifest["completed_shards"]), 4)

        packet = _read_json(self.paths["source_packet"])
        self.assertEqual(len(packet["sec_submissions_by_ticker"]), 50)
        consumer_summary = _read_json(self.paths["consumer_summary"])
        self.assertEqual(consumer_summary["aggregate_shape_metrics"]["screen_symbol_count"], 50)

        text = self.paths["producer_summary"].read_text(encoding="utf-8")
        self.assertNotIn("UnitTest/0.1 contact:test@example.com", text)
        self.assertNotIn("https://", text.lower())
        self.assertNotIn("data.sec.gov", text.lower())
        self.assertNotIn('"filings"', text)
        self.assertNotIn('"accessionNumber"', text)

    def test_finalize_only_round_uses_existing_raw_without_refetch(self):
        import importlib

        producer = importlib.import_module(MODULE)
        first_client = FakeSecClient(self.symbols)
        with self._env(producer), mock.patch.object(
            producer.sample_validation, "_read_windows_environment_value", return_value=None
        ), mock.patch.object(producer.time, "sleep"):
            producer.run_resume_round(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                manifest_path=self.paths["manifest"],
                output_source_packet_path=self.paths["source_packet"],
                output_screen_path=self.paths["screen"],
                summary_path=self.paths["producer_summary"],
                consumer_summary_path=self.paths["consumer_summary"],
                raw_root=self.raw_root,
                round_index=1,
                max_shards_per_round=2,
                precompleted_shard_indices=[0, 1],
                client=first_client,
                confirm_user_authorization=True,
                generated_at="2026-07-05T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
                sec_sleep_seconds=0,
            )
        manifest = _read_json(self.paths["manifest"])
        manifest["round_runs"] = []
        _write_json(self.paths["manifest"], manifest)

        second_client = FakeSecClient(self.symbols)
        with self._env(producer), mock.patch.object(
            producer.sample_validation, "_read_windows_environment_value", return_value=None
        ), mock.patch.object(producer.time, "sleep"):
            summary = producer.run_resume_round(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                manifest_path=self.paths["manifest"],
                output_source_packet_path=self.paths["source_packet"],
                output_screen_path=self.paths["screen"],
                summary_path=self.paths["producer_summary"],
                consumer_summary_path=self.paths["consumer_summary"],
                raw_root=self.raw_root,
                round_index=1,
                max_shards_per_round=2,
                precompleted_shard_indices=[0, 1],
                client=second_client,
                confirm_user_authorization=True,
                generated_at="2026-07-05T12:01:00+00:00",
                observed_at="2026-06-15T12:01:00+00:00",
                sec_sleep_seconds=0,
            )

        self.assertEqual(second_client.urls, [])
        self.assertTrue(summary["round_plan"]["finalize_only"])
        self.assertEqual(summary["round_plan"]["target_shard_indices"], [])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 51)
        self.assertEqual(summary["endpoint_call_budget"]["sec_ticker_reference_calls"], 1)
        self.assertEqual(summary["endpoint_call_budget"]["sec_company_submissions_calls"], 50)

    def test_manifest_raw_refs_must_stay_under_round_raw_root(self):
        import importlib

        producer = importlib.import_module(MODULE)
        rogue = self.state_dir / f"{self.slug}_rogue_raw.json"
        self.addCleanup(rogue.unlink, missing_ok=True)
        _write_json(rogue, self._successful_submission_wrapper(producer))
        manifest = self._manifest_with_raw_ref(producer._repo_rel(rogue))

        with self.assertRaisesRegex(producer.Bankruptcy8kCandidateResumeScanError, "raw_root"):
            producer._records_from_manifest_round(
                manifest=manifest,
                raw_root=self.raw_root,
                round_index=1,
                shard_indices=[2],
            )

    def test_manifest_raw_refs_must_be_gitignored(self):
        import importlib

        producer = importlib.import_module(MODULE)
        raw_path = producer._raw_ref_for(
            self.raw_root,
            producer.ENDPOINT_SUBMISSIONS,
            round_index=1,
            shard_index=2,
            symbol="T050",
        )
        _write_json(raw_path, self._successful_submission_wrapper(producer))
        manifest = self._manifest_with_raw_ref(producer._repo_rel(raw_path))

        with mock.patch.object(producer, "_git_ignored", return_value=False):
            with self.assertRaisesRegex(producer.Bankruptcy8kCandidateResumeScanError, "gitignored"):
                producer._records_from_manifest_round(
                    manifest=manifest,
                    raw_root=self.raw_root,
                    round_index=1,
                    shard_indices=[2],
                )

    def test_missing_manifest_raw_ref_raises_domain_error(self):
        import importlib

        producer = importlib.import_module(MODULE)
        raw_path = producer._raw_ref_for(
            self.raw_root,
            producer.ENDPOINT_SUBMISSIONS,
            round_index=1,
            shard_index=2,
            symbol="T050",
        )
        manifest = self._manifest_with_raw_ref(producer._repo_rel(raw_path))

        with self.assertRaisesRegex(producer.Bankruptcy8kCandidateResumeScanError, "does not exist"):
            producer._records_from_manifest_round(
                manifest=manifest,
                raw_root=self.raw_root,
                round_index=1,
                shard_indices=[2],
            )

    def test_final_round_marks_full_complete_only_after_all_shards_are_covered(self):
        import importlib

        producer = importlib.import_module(MODULE)
        small_symbols = _symbols(55)
        _write_json(self.paths["candidate"], _candidate_artifact_many(small_symbols))
        client = FakeSecClient(small_symbols)
        with self._env(producer), mock.patch.object(
            producer.sample_validation, "_read_windows_environment_value", return_value=None
        ), mock.patch.object(producer.time, "sleep"):
            summary = producer.run_resume_round(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                manifest_path=self.paths["manifest"],
                output_source_packet_path=self.paths["source_packet"],
                output_screen_path=self.paths["screen"],
                summary_path=self.paths["producer_summary"],
                consumer_summary_path=self.paths["consumer_summary"],
                raw_root=self.raw_root,
                round_index=1,
                max_shards_per_round=35,
                precompleted_shard_indices=[0, 1],
                client=client,
                confirm_user_authorization=True,
                generated_at="2026-07-05T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
                sec_sleep_seconds=0,
            )

        self.assertEqual(summary["round_plan"]["target_shard_indices"], [2])
        self.assertTrue(summary["scope"]["full_candidate_universe_scan_completed"])
        self.assertTrue(summary["prohibited_claims"]["full_candidate_universe_scan_completed_only_by_scan"])
        self.assertFalse(summary["prohibited_claims"]["status_records_written"])

        schema = _read_json(producer.SUMMARY_SCHEMA_PATH)
        validator = Draft7Validator(schema)
        mutated = json.loads(json.dumps(summary))
        mutated["scope"]["run_fetch_invoked"] = True
        self.assertGreater(len(list(validator.iter_errors(mutated))), 0)

    def test_requires_authorization_before_network_or_writes(self):
        import importlib

        producer = importlib.import_module(MODULE)
        client = FakeSecClient(self.symbols)
        with self.assertRaises(producer.Bankruptcy8kCandidateResumeScanError):
            producer.run_resume_round(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                manifest_path=self.paths["manifest"],
                output_source_packet_path=self.paths["source_packet"],
                output_screen_path=self.paths["screen"],
                summary_path=self.paths["producer_summary"],
                consumer_summary_path=self.paths["consumer_summary"],
                raw_root=self.raw_root,
                round_index=1,
                max_shards_per_round=2,
                precompleted_shard_indices=[0, 1],
                client=client,
                confirm_user_authorization=False,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["manifest"].exists())
        self.assertFalse(self.paths["producer_summary"].exists())


if __name__ == "__main__":
    unittest.main()
