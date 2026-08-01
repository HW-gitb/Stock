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

from runners import us_short_batch5_bankruptcy_8k_source_packet as runner  # noqa: E402
from tests.provider.us_short_private_test_root import (  # noqa: E402
    temporary_us_short_directory,
    temporary_us_short_state_directory,
)


STATE_DIR = ROOT / "state" / "us_short"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _sec_submissions(*, forms, filing_dates, accessions, items):
    return {
        "filings": {
            "recent": {
                "form": list(forms),
                "filingDate": list(filing_dates),
                "accessionNumber": list(accessions),
                "items": list(items),
            }
        }
    }


class UsShortBatch5Bankruptcy8kSourcePacketTest(unittest.TestCase):
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_dir = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._sample_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_bankruptcy_8k_source_packet_20260705"
        )
        self.sample_root = Path(self._sample_root_context.__enter__())
        self.addCleanup(self._sample_root_context.__exit__, None, None, None)
        self.slug = f"test_bankruptcy_8k_source_{os.getpid()}_{self._testMethodName}"
        self.paths = {
            "packet": self.state_dir / f"{self.slug}_packet.json",
            "screen": self.state_dir / f"{self.slug}_screen.json",
            "summary": ROOT / "docs" / f"{self.slug}_summary.json",
        }
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        self.packet = self._write_packet()

    def tearDown(self):
        for path in self.paths.values():
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".tmp").unlink(missing_ok=True)

    def _packet_payload(self):
        return json.loads(self.paths["packet"].read_text(encoding="utf-8"))

    def _write_packet(self):
        packet = {
            "schema_name": "us_short_batch5_bankruptcy_8k_source_packet",
            "schema_version": "1.0.0",
            "generated_at": "2026-07-05T00:00:00+00:00",
            "source_packet_ref": "reviewed_local_sec_submissions_source_packet",
            "scope": {
                "market": "US",
                "lane": "us_short",
                "batch": "batch5_provider_live",
                "purpose": "local_sec_submissions_to_bankruptcy_8k_screen",
                "packet_status": "local_source_packet_ready_for_bankruptcy_screen",
                "network_access_performed": False,
                "provider_calls_performed": False,
                "raw_payload_capture_performed": False,
                "full_market_scan_performed": False,
                "candidate_artifact_written": False,
                "status_records_written": False,
                "run_fetch_invoked": False,
                "datahub_consumption_allowed": False,
                "production_storage_allowed": False,
                "ship_gate_evidence_claimed": False,
                "broker_or_order_automation_allowed": False,
                "a_share_crossing_allowed": False,
            },
            "decision_clock": {
                "status_as_of": "2026-06-30",
                "source_observed_at": "2026-06-30T12:00:00+00:00",
            },
            "source_contract": {
                "source_id": "sec_8k_item_103",
                "provider_id": "sec_edgar",
                "endpoint_family": "company_submissions_recent_filings",
                "parser_ref": "engine.us_short_status_source.build_bankruptcy_screen_from_sec_submissions",
                "input_source": "reviewed_local_sec_submissions_source_packet",
                "lookback_days": 90,
            },
            "paths": {
                "bankruptcy_screen_output_path": _rel(self.paths["screen"]),
            },
            "sec_submissions_by_ticker": {
                "AAPL": _sec_submissions(
                    forms=["8-K", "10-Q"],
                    filing_dates=["2026-06-20", "2026-06-21"],
                    accessions=["0000320193-26-000111", "0000320193-26-000112"],
                    items=["9.01", "1.03"],
                ),
                "BANKR": _sec_submissions(
                    forms=["8-K", "10-Q"],
                    filing_dates=["2026-06-20", "2026-06-21"],
                    accessions=["0001140361-26-000001", "0001140361-26-000002"],
                    items=["1.03,9.01", "2.02"],
                ),
            },
            "preflight_gates": {
                "local_files_only": True,
                "source_packet_must_be_gitignored": True,
                "output_screen_must_be_gitignored": True,
                "no_provider_fetch": True,
                "no_datahub_or_production": True,
                "tracked_summary_must_exclude_raw_payload": True,
            },
            "prohibited_claims": {
                "provider_selected": False,
                "full_market_scan_performed": False,
                "candidate_artifact_written": False,
                "status_records_runner_consumable": False,
                "datahub_consumed": False,
                "production_ready_claimed": False,
                "ship_gate_evidence_claimed": False,
                "broker_or_order_automation": False,
                "a_share_crossing_performed": False,
            },
        }
        return _write_json(self.paths["packet"], packet)

    def test_run_packet_writes_gitignored_bankruptcy_screen_and_sanitized_summary(self):
        result = runner.run_packet(
            self.packet,
            summary_path=self.paths["summary"],
            generated_at="2026-07-05T00:00:01+00:00",
        )

        self.assertEqual(result["scope"]["status"], "bankruptcy_screen_written")
        self.assertFalse(result["scope"]["network_access_performed"])
        self.assertFalse(result["scope"]["provider_calls_performed"])
        self.assertFalse(result["scope"]["status_records_written"])
        self.assertTrue(self.paths["screen"].exists())
        screen = json.loads(self.paths["screen"].read_text(encoding="utf-8"))
        self.assertEqual(screen["by_ticker"]["AAPL"], {"screen_status": "screened_no_filing"})
        self.assertEqual(
            screen["by_ticker"]["BANKR"],
            {"screen_status": "bankrupt_8k_found", "filing_accession": "0001140361-26-000001"},
        )
        self.assertEqual(result["aggregate_shape_metrics"]["bankruptcy_8k_positive_count"], 1)
        self.assertEqual(result["aggregate_shape_metrics"]["screened_no_filing_count"], 1)

        text = self.paths["summary"].read_text(encoding="utf-8")
        self.assertNotIn('"filings"', text)
        self.assertNotIn('"recent"', text)
        self.assertNotIn('"form"', text)
        self.assertNotIn('"filingDate"', text)
        self.assertNotIn('"accessionNumber"', text)
        self.assertNotIn('"items"', text)
        self.assertNotIn("data.sec.gov", text.lower())
        self.assertNotIn("https://", text.lower())
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn("token=", text.lower())

    def test_summary_safe_guard_allows_form_ticker_but_rejects_raw_form_key(self):
        runner._assert_summary_safe({"source_packet": {"input_symbols": ["FORM"]}})
        with self.assertRaises(runner.BankruptcySourcePacketError):
            runner._assert_summary_safe({"raw": {"form": ["8-K"]}})

    def test_preflight_rejects_non_gitignored_packet_path_before_write(self):
        leaky_packet = ROOT / "docs" / f"{self.slug}_packet.json"
        self.addCleanup(leaky_packet.unlink, missing_ok=True)
        self.addCleanup(leaky_packet.with_name(leaky_packet.name + ".tmp").unlink, missing_ok=True)
        _write_json(leaky_packet, self._packet_payload())

        with self.assertRaises(runner.BankruptcySourcePacketError):
            runner.run_packet(
                leaky_packet,
                summary_path=self.paths["summary"],
                generated_at="2026-07-05T00:00:02+00:00",
            )
        self.assertFalse(self.paths["screen"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_output_screen_must_stay_gitignored_state_path(self):
        packet = self._packet_payload()
        packet["paths"]["bankruptcy_screen_output_path"] = f"docs/{self.slug}_screen.json"
        _write_json(self.paths["packet"], packet)

        with self.assertRaises(runner.BankruptcySourcePacketError):
            runner.run_packet(
                self.packet,
                summary_path=self.paths["summary"],
                generated_at="2026-07-05T00:00:03+00:00",
            )
        self.assertFalse((ROOT / "docs" / f"{self.slug}_screen.json").exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_summary_path_must_be_tracked_docs_path_before_write(self):
        ignored_summary = (
            ROOT
            / "provider_samples"
            / "us_short_batch5_bankruptcy_8k_source_packet_20260705"
            / self.slug
            / "summary.json"
        )

        with self.assertRaises(runner.BankruptcySourcePacketError):
            runner.run_packet(
                self.packet,
                summary_path=ignored_summary,
                generated_at="2026-07-05T00:00:03+00:00",
            )
        self.assertFalse(self.paths["screen"].exists())
        self.assertFalse(ignored_summary.exists())

    def test_malformed_submissions_fail_closed_without_output_or_summary(self):
        packet = self._packet_payload()
        packet["sec_submissions_by_ticker"]["AAPL"]["filings"]["recent"]["items"] = []
        _write_json(self.paths["packet"], packet)

        with self.assertRaises(runner.BankruptcySourcePacketError):
            runner.run_packet(
                self.packet,
                summary_path=self.paths["summary"],
                generated_at="2026-07-05T00:00:04+00:00",
            )
        self.assertFalse(self.paths["screen"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_duplicate_canonical_ticker_keys_fail_closed(self):
        packet = self._packet_payload()
        packet["sec_submissions_by_ticker"]["bankr"] = copy.deepcopy(packet["sec_submissions_by_ticker"]["BANKR"])
        _write_json(self.paths["packet"], packet)

        with self.assertRaises(runner.BankruptcySourcePacketError):
            runner.run_packet(
                self.packet,
                summary_path=self.paths["summary"],
                generated_at="2026-07-05T00:00:05+00:00",
            )
        self.assertFalse(self.paths["screen"].exists())
        self.assertFalse(self.paths["summary"].exists())

    def test_summary_schema_rejects_scope_creep_flags(self):
        good = runner.build_summary(
            packet_ref="state/us_short/example_packet.json",
            screen_path="state/us_short/example_screen.json",
            generated_at="2026-07-05T00:00:06+00:00",
            status_as_of="2026-06-30",
            source_observed_at="2026-06-30T12:00:00+00:00",
            input_symbol_count=1,
            screen={"observed": True, "observed_at": "2026-06-30T12:00:00+00:00", "lookback_window": "P90D", "by_ticker": {"AAPL": {"screen_status": "screened_no_filing"}}},
        )
        schema = json.loads(runner.SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))
        import jsonschema

        for path, value in (
            (("scope", "full_market_scan_performed"), True),
            (("scope", "status_records_written"), True),
            (("scope", "datahub_consumption_allowed"), True),
            (("scope", "ship_gate_evidence_claimed"), True),
            (("prohibited_claims", "status_records_runner_consumable"), True),
            (("storage", "tracked_summary_path"), "provider_samples/ignored_summary.json"),
        ):
            mutant = copy.deepcopy(good)
            target = mutant
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.assertRaises(jsonschema.ValidationError, msg=".".join(path)):
                jsonschema.Draft7Validator(schema).validate(mutant)


if __name__ == "__main__":
    unittest.main()
