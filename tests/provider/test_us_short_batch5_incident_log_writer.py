from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import us_short_batch5_incident_log_writer as writer
from tests.schema.test_us_short_batch5_incident_log_record_schema import valid_record


class UsShortBatch5IncidentLogWriterTest(unittest.TestCase):
    def _private_incident_root(self) -> Path:
        base = writer.ROOT / "state" / "us_short" / "runs_private" / "provider_incidents"
        base.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.TemporaryDirectory(prefix="unit_writer_", dir=base)
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_writer_appends_private_jsonl_and_private_summary_only(self) -> None:
        incident_root = self._private_incident_root()
        record = valid_record()

        summary = writer.write_incident_record(
            record,
            decision_date="20260625",
            incident_root=incident_root,
        )

        log_path = incident_root / "20260625" / "incident_log.jsonl"
        summary_path = incident_root / "20260625" / "incident_summary.json"
        self.assertTrue(log_path.exists())
        self.assertTrue(summary_path.exists())
        self.assertEqual(json.loads(log_path.read_text(encoding="utf-8").strip()), record)
        self.assertEqual(summary["incident_count"], 1)
        self.assertEqual(summary["latest_incident_id"], record["incident_id"])
        self.assertEqual(summary["incident_type_counts"], {"quota_or_rate_limit": 1})
        self.assertFalse(summary["scope"]["provider_calls_performed_by_writer"])
        self.assertFalse(summary["scope"]["status_page_polled_by_writer"])
        self.assertFalse(summary["scope"]["fallback_execution_performed_by_writer"])
        self.assertFalse(summary["scope"]["datahub_consumption_performed_by_writer"])
        self.assertFalse(summary["storage"]["tracked_files_written"])
        self.assertEqual(
            summary["storage"]["private_log_path"],
            log_path.relative_to(writer.ROOT).as_posix(),
        )

        summary_text = summary_path.read_text(encoding="utf-8").lower()
        for forbidden in [
            "apikey=",
            "financialmodelingprep.com",
            "data.sec.gov",
            "\"request_url\"",
            "\"raw_payload\"",
            "\"provider_response_body\"",
        ]:
            self.assertNotIn(forbidden, summary_text)

    def test_writer_rejects_implausible_detected_at_year(self) -> None:
        # F7 (cc_r1_v1): detected_at must be real AND plausible — a far-future year (9999) is rejected.
        incident_root = self._private_incident_root()
        rec = valid_record()
        rec["detected_at"] = "9999-01-01T00:00:00+00:00"
        with self.assertRaisesRegex(writer.IncidentLogWriterError, "plausible"):
            writer.write_incident_record(rec, decision_date="20260625", incident_root=incident_root)

    def test_summary_write_failure_leaves_valid_log_no_corrupt_residue(self) -> None:
        # F3 (cc_r1_v1): the log is written via atomic tmp-then-replace; a failure during the summary write
        # cannot leave a half-written/corrupt log (it stays a complete parseable JSONL of all records) and no
        # .tmp residue. The summary momentarily lags but self-heals from the log on the next write.
        incident_root = self._private_incident_root()
        rec = valid_record()
        with mock.patch.object(writer, "_write_json_atomic", side_effect=RuntimeError("summary write boom")):
            with self.assertRaises(RuntimeError):
                writer.write_incident_record(rec, decision_date="20260625", incident_root=incident_root)
        log_path = incident_root / "20260625" / "incident_log.jsonl"
        self.assertTrue(log_path.exists())
        lines = [ln for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), rec)                                  # complete, not corrupt
        self.assertFalse(log_path.with_name("incident_log.jsonl.tmp").exists())      # no tmp residue

    def test_writer_rejects_output_root_outside_batch5_private_incident_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="outside_incident_", dir=writer.ROOT) as tmpdir:
            with self.assertRaisesRegex(writer.IncidentLogWriterError, "private incident root"):
                writer.write_incident_record(
                    valid_record(),
                    decision_date="20260625",
                    incident_root=Path(tmpdir),
                )
            self.assertFalse((Path(tmpdir) / "20260625" / "incident_log.jsonl").exists())

    def test_writer_rejects_unignored_private_root(self) -> None:
        incident_root = self._private_incident_root()
        with mock.patch.object(writer, "_git_check_ignored", return_value=False):
            with self.assertRaisesRegex(writer.IncidentLogWriterError, "gitignored"):
                writer.write_incident_record(
                    valid_record(),
                    decision_date="20260625",
                    incident_root=incident_root,
                )

    def test_writer_rejects_request_urls_secrets_and_raw_payload_values(self) -> None:
        bad_records = []

        request_url = valid_record()
        request_url["endpoint_family"] = (
            "https://financialmodelingprep.com/api/v3/profile/AAPL?apikey=SECRET"
        )
        bad_records.append(request_url)

        raw_payload = valid_record()
        raw_payload["trigger_summary"] = "{\"payload\": [{\"symbol\": \"AAPL\"}]}"
        bad_records.append(raw_payload)

        secret_ref = valid_record()
        secret_ref["raw_payload_storage_ref"] = (
            "provider_samples/us_short_batch5_provider_incidents/raw/AAPL.json?apikey=SECRET"
        )
        bad_records.append(secret_ref)

        incident_root = self._private_incident_root()
        for record in bad_records:
            with self.subTest(record=record):
                with self.assertRaises(writer.IncidentLogWriterError):
                    writer.write_incident_record(
                        record,
                        decision_date="20260625",
                        incident_root=incident_root,
                    )

        self.assertFalse((incident_root / "20260625" / "incident_log.jsonl").exists())

    def test_writer_rejects_incident_mapping_traceback_drift(self) -> None:
        incident_root = self._private_incident_root()

        bad_severity = valid_record()
        bad_severity["severity"] = "evidence_blocker"
        with self.assertRaisesRegex(writer.IncidentLogWriterError, "severity"):
            writer.write_incident_record(
                bad_severity,
                decision_date="20260625",
                incident_root=incident_root,
            )

        bad_action = valid_record()
        bad_action["immediate_action"] = "use_reviewed_audit_source_only"
        with self.assertRaisesRegex(writer.IncidentLogWriterError, "immediate_action"):
            writer.write_incident_record(
                bad_action,
                decision_date="20260625",
                incident_root=incident_root,
            )

    def test_writer_rejects_duplicate_incident_id_without_mutating_log_or_summary(self) -> None:
        incident_root = self._private_incident_root()
        record = valid_record()

        first_summary = writer.write_incident_record(
            record,
            decision_date="20260625",
            incident_root=incident_root,
        )
        with self.assertRaisesRegex(writer.IncidentLogWriterError, "duplicate incident_id"):
            writer.write_incident_record(
                record,
                decision_date="20260625",
                incident_root=incident_root,
            )

        log_path = incident_root / "20260625" / "incident_log.jsonl"
        summary_path = incident_root / "20260625" / "incident_summary.json"
        lines = log_path.read_text(encoding="utf-8").splitlines()
        summary_after_rejection = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["incident_id"], record["incident_id"])
        self.assertEqual(summary_after_rejection, first_summary)

    def test_writer_rejects_existing_log_with_duplicate_ids_before_any_file_mutation(self) -> None:
        incident_root = self._private_incident_root()
        target_dir = incident_root / "20260625"
        target_dir.mkdir(parents=True)
        log_path = target_dir / "incident_log.jsonl"
        summary_path = target_dir / "incident_summary.json"
        first = valid_record()
        duplicate = valid_record()
        duplicate["detected_by"] = "unit_test_offline_writer_second"
        new_record = valid_record()
        new_record["incident_id"] = "batch5-incident-20260625-0002"
        new_record["incident_type"] = "http_401_403_auth_scope"
        new_record["severity"] = "evidence_blocker"
        new_record["immediate_action"] = "manual_review"
        existing_text = (
            json.dumps(first, ensure_ascii=False, sort_keys=True)
            + "\n"
            + json.dumps(duplicate, ensure_ascii=False, sort_keys=True)
            + "\n"
        )
        log_path.write_text(existing_text, encoding="utf-8", newline="\n")

        with self.assertRaisesRegex(writer.IncidentLogWriterError, "duplicate incident_id"):
            writer.write_incident_record(
                new_record,
                decision_date="20260625",
                incident_root=incident_root,
            )

        self.assertEqual(log_path.read_text(encoding="utf-8"), existing_text)
        self.assertFalse(summary_path.exists())

    def test_writer_rejects_corrupt_existing_log_before_any_file_mutation(self) -> None:
        incident_root = self._private_incident_root()
        target_dir = incident_root / "20260625"
        target_dir.mkdir(parents=True)
        log_path = target_dir / "incident_log.jsonl"
        summary_path = target_dir / "incident_summary.json"
        log_path.write_text("{not valid json}\n", encoding="utf-8", newline="\n")

        with self.assertRaisesRegex(writer.IncidentLogWriterError, "invalid existing incident_log"):
            writer.write_incident_record(
                valid_record(),
                decision_date="20260625",
                incident_root=incident_root,
            )

        self.assertEqual(log_path.read_text(encoding="utf-8"), "{not valid json}\n")
        self.assertFalse(summary_path.exists())

    def test_writer_appends_without_relabeling_as_live_or_ship_gate(self) -> None:
        incident_root = self._private_incident_root()
        first = valid_record()
        second = valid_record()
        second["incident_id"] = "batch5-incident-20260625-0002"
        second["incident_type"] = "http_401_403_auth_scope"
        second["severity"] = "evidence_blocker"
        second["immediate_action"] = "manual_review"

        writer.write_incident_record(first, decision_date="20260625", incident_root=incident_root)
        summary = writer.write_incident_record(second, decision_date="20260625", incident_root=incident_root)

        lines = (incident_root / "20260625" / "incident_log.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(summary["incident_count"], 2)
        self.assertEqual(
            summary["incident_type_counts"],
            {
                "http_401_403_auth_scope": 1,
                "quota_or_rate_limit": 1,
            },
        )
        self.assertFalse(summary["prohibited_claims"]["live_normalized_evidence_claimed"])
        self.assertFalse(summary["prohibited_claims"]["ship_gate_evidence_claimed"])
        self.assertFalse(summary["prohibited_claims"]["production_readiness_claimed"])


class UsShortBatch5IncidentTimeSemanticsTest(unittest.TestCase):
    """R-USSHORT-BATCH5-INCIDENT-TIME-SEMANTICS-GAP: detected_at / affected_date_window / decision_date must be
    real timezone-aware / calendar values, not just format/pattern-shaped strings."""

    def test_valid_record_passes_time_semantics(self):
        writer.validate_incident_record(valid_record())   # positive control

    def test_detected_at_not_real_datetime_rejected(self):
        for bad in ("not-a-real-datetime00", "2026-13-01T00:00:00Z", "2026-02-30T00:00:00Z"):
            rec = valid_record(); rec["detected_at"] = bad
            with self.assertRaises(writer.IncidentLogWriterError):
                writer.validate_incident_record(rec)

    def test_detected_at_without_timezone_rejected(self):
        rec = valid_record(); rec["detected_at"] = "2026-06-25T10:00:00"   # no offset/Z
        with self.assertRaises(writer.IncidentLogWriterError):
            writer.validate_incident_record(rec)

    def test_affected_date_window_unreal_date_rejected(self):
        for start, end in (("2026-99-99", "2026-06-25"), ("2026-00-00", "2026-06-25")):
            rec = valid_record(); rec["affected_date_window"] = {"start": start, "end": end}
            with self.assertRaises(writer.IncidentLogWriterError):
                writer.validate_incident_record(rec)

    def test_affected_date_window_inverted_rejected(self):
        rec = valid_record(); rec["affected_date_window"] = {"start": "2026-06-26", "end": "2026-06-25"}
        with self.assertRaises(writer.IncidentLogWriterError):
            writer.validate_incident_record(rec)

    def test_decision_date_must_be_real_calendar_date(self):
        writer._validate_decision_date("20260625")        # positive control: a real date passes
        for bad in ("20261399", "20260229", "2026062a"):  # month 13 / Feb 29 in a non-leap year / non-digit
            with self.assertRaises(writer.IncidentLogWriterError):
                writer._validate_decision_date(bad)


if __name__ == "__main__":
    unittest.main()
