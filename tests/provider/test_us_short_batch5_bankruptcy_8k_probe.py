from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runners import us_short_batch5_bankruptcy_8k_probe as probe
from tests.provider.us_short_private_test_root_light import temporary_us_short_directory


ROOT = Path(".").resolve()
PACKET_PATH = Path("docs/us_short_batch5_bankruptcy_8k_access_packet_20260703.json")


def _submission_payload(*, forms: list[str], dates: list[str], accessions: list[str], items: list[str]) -> dict:
    return {
        "filings": {
            "recent": {
                "form": forms,
                "filingDate": dates,
                "accessionNumber": accessions,
                "items": items,
            }
        }
    }


class FakeBankruptcyHttpClient:
    def __init__(self, *, aapl_positive_accession: str = "0000320193-26-000001") -> None:
        self.aapl_positive_accession = aapl_positive_accession
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = probe.DEFAULT_TIMEOUT_SECONDS,
    ) -> tuple[object, int | None, bool, str | None]:
        del timeout_seconds
        self.calls.append((url, dict(headers or {})))
        if url.endswith("CIK0000320193.json"):
            return (
                _submission_payload(
                    forms=["8-K", "10-Q"],
                    dates=["2026-06-20", "2026-05-01"],
                    accessions=[self.aapl_positive_accession, "0000320193-26-000002"],
                    items=["1.03", "2.02"],
                ),
                200,
                True,
                None,
            )
        if url.endswith("CIK0000789019.json"):
            return (
                _submission_payload(
                    forms=["8-K"],
                    dates=["2026-06-21"],
                    accessions=["0000789019-26-000001"],
                    items=["2.02"],
                ),
                200,
                True,
                None,
            )
        if url.endswith("CIK0000019617.json"):
            return (
                _submission_payload(forms=[], dates=[], accessions=[], items=[]),
                200,
                True,
                None,
            )
        return {"unexpected": url}, 404, False, "unexpected_url"


class UsShortBatch5Bankruptcy8kProbeTest(unittest.TestCase):
    def _run_under_provider_samples(self, **kwargs: object) -> tuple[dict, FakeBankruptcyHttpClient, Path]:
        root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_bankruptcy_8k_20260703" / "raw"
        )
        private_root = Path(root_context.__enter__())
        base = private_root / "_unit_tests"
        self.addCleanup(root_context.__exit__, None, None, None)
        base.mkdir(parents=True, exist_ok=True)
        client = FakeBankruptcyHttpClient()
        temp_dir = tempfile.TemporaryDirectory(prefix="run_", dir=base)
        self.addCleanup(temp_dir.cleanup)
        temp_root = Path(temp_dir.name)
        summary_path = temp_root / "summary.json"
        raw_root = temp_root / "raw"
        with mock.patch.dict(
            probe.os.environ,
            {"SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com"},
            clear=True,
        ), mock.patch.object(probe.sample_validation, "_read_windows_environment_value", return_value=None):
            summary = probe.run_bankruptcy_8k_probe(
                access_packet_path=PACKET_PATH,
                summary_path=summary_path,
                raw_root=raw_root,
                generated_at="2026-07-03T00:00:00+00:00",
                source_observed_at="2026-07-02T23:50:43-04:00",
                status_as_of="2026-07-06",
                client=client,
                confirm_user_authorization=True,
                confirm_post_preflight_execute=True,
                **kwargs,
            )
        return summary, client, temp_root

    def test_probe_fetches_only_three_sec_submissions_and_summary_is_sanitized(self) -> None:
        summary, client, temp_root = self._run_under_provider_samples()
        summary_path = temp_root / "summary.json"

        self.assertEqual(summary["schema_name"], "us_short_batch5_bankruptcy_8k_probe_summary")
        self.assertEqual(summary["scope"]["probe_status"], "completed")
        self.assertTrue(summary["scope"]["bankruptcy_8k_probe_performed"])
        self.assertFalse(summary["scope"]["runner_consumption_allowed"])
        self.assertFalse(summary["scope"]["datahub_consumption_allowed"])
        self.assertFalse(summary["scope"]["ship_gate_evidence_claimed"])
        self.assertFalse(summary["scope"]["status_records_written"])
        self.assertFalse(summary["scope"]["run_fetch_bankruptcy_wiring_performed"])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 3)
        self.assertEqual(summary["endpoint_call_budget"]["retry_count_used"], 0)
        self.assertTrue(summary["endpoint_call_budget"]["within_budget"])

        self.assertEqual(
            [url.rsplit("/", 1)[-1] for url, _ in client.calls],
            ["CIK0000320193.json", "CIK0000789019.json", "CIK0000019617.json"],
        )
        self.assertEqual(
            [item["symbol"] for item in summary["endpoint_results"]],
            ["AAPL", "MSFT", "JPM"],
        )
        for endpoint in summary["endpoint_results"]:
            self.assertEqual(endpoint["status"], "ok")
            self.assertTrue(endpoint["raw_sample_ref"].startswith("provider_samples/"))
            local_raw_path = (
                temp_root
                / "raw"
                / "sec_edgar"
                / endpoint["symbol"]
                / "company_submissions_recent_filings.json"
            )
            self.assertTrue(local_raw_path.exists())

        self.assertEqual(
            summary["sample_shape_results"]["by_symbol"]["AAPL"]["bankruptcy_screen_status"],
            "bankrupt_8k_found",
        )
        self.assertEqual(
            summary["sample_shape_results"]["by_symbol"]["MSFT"]["bankruptcy_screen_status"],
            "screened_no_filing",
        )
        self.assertEqual(summary["aggregate_shape_metrics"]["bankruptcy_8k_positive_count"], 1)

        summary_text = summary_path.read_text(encoding="utf-8")
        self.assertNotIn("UnitTest/0.1 contact:test@example.com", summary_text)
        self.assertNotIn("https://", summary_text.lower())
        self.assertNotIn("data.sec.gov", summary_text.lower())
        self.assertNotIn("submissions/CIK", summary_text)
        self.assertNotIn("apikey=", summary_text.lower())
        self.assertNotIn('"filings"', summary_text)

    def test_live_probe_requires_confirmations_before_fetch_or_write(self) -> None:
        root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_bankruptcy_8k_20260703" / "raw"
        )
        private_root = Path(root_context.__enter__())
        base = private_root / "_unit_tests"
        self.addCleanup(root_context.__exit__, None, None, None)
        base.mkdir(parents=True, exist_ok=True)
        client = FakeBankruptcyHttpClient()
        with tempfile.TemporaryDirectory(prefix="missing_confirm_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            with mock.patch.dict(
                probe.os.environ,
                {"SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com"},
                clear=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "confirm-user-authorization"):
                    probe.run_bankruptcy_8k_probe(
                        access_packet_path=PACKET_PATH,
                        summary_path=temp_root / "summary.json",
                        raw_root=temp_root / "raw",
                        generated_at="2026-07-03T00:00:00+00:00",
                        source_observed_at="2026-07-02T23:50:43-04:00",
                        status_as_of="2026-07-06",
                        client=client,
                        confirm_user_authorization=False,
                        confirm_post_preflight_execute=True,
                    )

            self.assertEqual(client.calls, [])
            self.assertFalse((temp_root / "summary.json").exists())

    def test_dry_run_env_checks_boundary_without_fetching_or_writing(self) -> None:
        root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_bankruptcy_8k_20260703" / "raw"
        )
        private_root = Path(root_context.__enter__())
        base = private_root / "_unit_tests"
        self.addCleanup(root_context.__exit__, None, None, None)
        base.mkdir(parents=True, exist_ok=True)
        client = FakeBankruptcyHttpClient()
        with tempfile.TemporaryDirectory(prefix="dry_run_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            with mock.patch.dict(
                probe.os.environ,
                {"SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com"},
                clear=True,
            ), mock.patch.object(probe.sample_validation, "_read_windows_environment_value", return_value=None):
                summary = probe.run_bankruptcy_8k_probe(
                    access_packet_path=PACKET_PATH,
                    summary_path=temp_root / "summary.json",
                    raw_root=temp_root / "raw",
                    generated_at="2026-07-03T00:00:00+00:00",
                    source_observed_at="2026-07-02T23:50:43-04:00",
                    status_as_of="2026-07-06",
                    client=client,
                    dry_run_env=True,
                )

            self.assertEqual(summary["scope"]["probe_status"], "dry_run_env_only")
            self.assertFalse(summary["scope"]["bankruptcy_8k_probe_performed"])
            self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 0)
            self.assertEqual(client.calls, [])
            self.assertFalse((temp_root / "summary.json").exists())

    def test_schema_invalid_summary_is_not_written(self) -> None:
        root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_bankruptcy_8k_20260703" / "raw"
        )
        private_root = Path(root_context.__enter__())
        base = private_root / "_unit_tests"
        self.addCleanup(root_context.__exit__, None, None, None)
        base.mkdir(parents=True, exist_ok=True)
        client = FakeBankruptcyHttpClient()
        original_build_summary = probe.build_summary

        def invalid_build_summary(**kwargs: object) -> dict:
            summary = original_build_summary(**kwargs)
            summary["scope"]["runner_consumption_allowed"] = True
            return summary

        with tempfile.TemporaryDirectory(prefix="invalid_summary_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            summary_path = temp_root / "summary.json"
            with mock.patch.dict(
                probe.os.environ,
                {"SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com"},
                clear=True,
            ), mock.patch.object(probe.sample_validation, "_read_windows_environment_value", return_value=None), \
                    mock.patch.object(probe, "build_summary", side_effect=invalid_build_summary):
                with self.assertRaisesRegex(RuntimeError, "schema validation failed"):
                    probe.run_bankruptcy_8k_probe(
                        access_packet_path=PACKET_PATH,
                        summary_path=summary_path,
                        raw_root=temp_root / "raw",
                        generated_at="2026-07-03T00:00:00+00:00",
                        source_observed_at="2026-07-02T23:50:43-04:00",
                        status_as_of="2026-07-06",
                        client=client,
                        confirm_user_authorization=True,
                        confirm_post_preflight_execute=True,
                    )

            self.assertEqual(len(client.calls), 3)
            self.assertFalse(summary_path.exists())
            self.assertFalse(summary_path.with_name("summary.json.tmp").exists())

    def test_hostile_positive_accession_is_not_emitted_to_tracked_summary(self) -> None:
        root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_bankruptcy_8k_20260703" / "raw"
        )
        private_root = Path(root_context.__enter__())
        base = private_root / "_unit_tests"
        self.addCleanup(root_context.__exit__, None, None, None)
        base.mkdir(parents=True, exist_ok=True)
        client = FakeBankruptcyHttpClient(aapl_positive_accession="sk-live-token@example.com")
        with tempfile.TemporaryDirectory(prefix="hostile_accession_", dir=base) as tmp_dir:
            temp_root = Path(tmp_dir)
            summary_path = temp_root / "summary.json"
            with mock.patch.dict(
                probe.os.environ,
                {"SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com"},
                clear=True,
            ), mock.patch.object(probe.sample_validation, "_read_windows_environment_value", return_value=None):
                summary = probe.run_bankruptcy_8k_probe(
                    access_packet_path=PACKET_PATH,
                    summary_path=summary_path,
                    raw_root=temp_root / "raw",
                    generated_at="2026-07-03T00:00:00+00:00",
                    source_observed_at="2026-07-02T23:50:43-04:00",
                    status_as_of="2026-07-06",
                    client=client,
                    confirm_user_authorization=True,
                    confirm_post_preflight_execute=True,
                )

            self.assertEqual(len(client.calls), 3)
            self.assertFalse(summary["pre_execution_checks"]["parser_shape_validation_passed"])
            self.assertEqual(
                summary["sample_shape_results"]["by_symbol"]["AAPL"]["filing_accession_if_found"],
                None,
            )
            self.assertNotIn("sk-live-token@example.com", summary_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
