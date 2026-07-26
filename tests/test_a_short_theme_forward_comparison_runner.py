"""The sole formal look is consumed only after its receipt is written."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import a_short_theme_forward_comparison as runner  # noqa: E402
from engine import a_short_theme_forward_comparison as comparison  # noqa: E402
from tests.test_a_short_theme_forward_comparison import _week  # noqa: E402


class ThemeForwardComparisonRunnerTests(unittest.TestCase):
    @staticmethod
    def _build_epoch(tracker: pd.DataFrame, epoch_id: str = "theme-v1") -> dict:
        as_of = str(tracker.iloc[0]["as_of"])
        with mock.patch.object(
            comparison, "_today_date", return_value=pd.Timestamp(as_of).date()
        ):
            return comparison.build_frozen_epoch(tracker, epoch_id, as_of)

    @staticmethod
    def _admit_pending(tracker: pd.DataFrame, epoch: dict) -> dict[str, dict]:
        with mock.patch.object(
            comparison, "_today_date",
            return_value=pd.Timestamp(str(tracker.iloc[0]["as_of"])).date(),
        ):
            receipt = comparison.build_cohort_admission_receipt(tracker, epoch, 5)
        assert receipt is not None
        receipts = {str(tracker.iloc[0]["as_of"]): receipt}
        epoch["admission_receipt_manifest"] = comparison.admission_receipt_manifest(receipts)
        return receipts

    def test_terminal_outcome_receipt_is_append_only_and_detects_restatement(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker["ret_10d_status"] = "pending_capture"
        tracker["ret_10d_t1_net"] = pd.NA
        tracker["ret_10d_t1_net"] = pd.NA
        epoch = self._build_epoch(tracker)
        admissions = self._admit_pending(tracker, epoch)
        tracker["ret_10d_status"] = "ok"
        tracker["ret_10d_t1_net"] = 1.0
        with tempfile.TemporaryDirectory() as temp:
            private_root = Path(temp) / "state" / "a_short" / "theme_forward_comparison_private" / "v1"
            active_epoch = Path(temp) / "epoch.json"
            with mock.patch.object(runner, "EPOCH_PATH", active_epoch):
                receipts = runner._sync_terminal_outcome_receipts(
                    tracker, epoch, private_root, admissions
                )
                self.assertEqual(set(receipts), {"20260102"})
                tracker.loc[tracker["ts_code"] == "000000.SZ", "ret_10d_t1_net"] = 99.0
                with self.assertRaisesRegex(SystemExit, "receipt mismatch"):
                    runner._sync_terminal_outcome_receipts(
                        tracker, epoch, private_root, admissions
                    )

    def test_deleted_terminal_receipt_cannot_rearm_a_rewritten_outcome(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker["ret_10d_status"] = "pending_capture"
        tracker["ret_10d_t1_net"] = pd.NA
        epoch = self._build_epoch(tracker)
        admissions = self._admit_pending(tracker, epoch)
        tracker["ret_10d_status"] = "ok"
        tracker["ret_10d_t1_net"] = 1.0
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private_root = root / "state" / "a_short" / "theme_forward_comparison_private" / "v1"
            with mock.patch.object(runner, "EPOCH_PATH", root / "epoch.json"):
                runner._sync_terminal_outcome_receipts(
                    tracker, epoch, private_root, admissions
                )
                receipt_path = private_root / "epochs" / "theme-v1" / "outcomes" / "20260102.json"
                receipt_path.unlink()
                tracker.loc[tracker["ts_code"] == "000000.SZ", "ret_10d_t1_net"] = 99.0
                with self.assertRaisesRegex(SystemExit, "manifest"):
                    runner._sync_terminal_outcome_receipts(
                        tracker, epoch, private_root, admissions
                    )

    def test_later_same_week_cohort_cannot_evict_an_immutable_admission_slot(self):
        first = pd.DataFrame(_week("20260102"))
        second = pd.DataFrame(_week("20260103"))
        for tracker in (first, second):
            tracker["ret_10d_status"] = "pending_capture"
            tracker["ret_10d_t1_net"] = pd.NA
        epoch = self._build_epoch(first)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private_root = root / "state" / "a_short" / "theme_forward_comparison_private" / "v1"
            with mock.patch.object(runner, "EPOCH_PATH", root / "epoch.json"), \
                    mock.patch.object(comparison, "_today_date", return_value=pd.Timestamp("20260103").date()):
                initial = runner._sync_cohort_admission_receipts(first, epoch, private_root)
                resumed = runner._sync_cohort_admission_receipts(
                    pd.concat([first, second], ignore_index=True), epoch, private_root
                )
            self.assertEqual(set(initial), {"20260102"})
            self.assertEqual(set(resumed), {"20260102"})
            self.assertEqual(epoch["admission_receipt_manifest"], comparison.admission_receipt_manifest(resumed))

    def test_admission_receipt_write_recovers_when_epoch_manifest_write_crashes(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker["ret_10d_status"] = "pending_capture"
        tracker["ret_10d_t1_net"] = pd.NA
        epoch = self._build_epoch(tracker)
        original_epoch = copy.deepcopy(epoch)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private_root = root / "state" / "a_short" / "theme_forward_comparison_private" / "v1"
            epoch_path = root / "epoch.json"
            real_write = runner._write_json_atomic
            def fail_epoch_pointer(path, payload):
                if path == epoch_path:
                    raise OSError("simulated manifest-pointer crash")
                return real_write(path, payload)
            with mock.patch.object(runner, "EPOCH_PATH", epoch_path), \
                    mock.patch.object(comparison, "_today_date", return_value=pd.Timestamp("20260102").date()), \
                    mock.patch.object(runner, "_write_json_atomic", side_effect=fail_epoch_pointer):
                with self.assertRaises(OSError):
                    runner._sync_cohort_admission_receipts(tracker, epoch, private_root)
            with mock.patch.object(runner, "EPOCH_PATH", epoch_path), \
                    mock.patch.object(comparison, "_today_date", return_value=pd.Timestamp("20260102").date()):
                resumed = runner._sync_cohort_admission_receipts(tracker, original_epoch, private_root)
        self.assertEqual(set(resumed), {"20260102"})
        self.assertEqual(original_epoch["admission_receipt_manifest"], comparison.admission_receipt_manifest(resumed))

    def test_terminal_receipt_write_recovers_when_epoch_manifest_write_crashes(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker["ret_10d_status"] = "pending_capture"
        tracker["ret_10d_t1_net"] = pd.NA
        epoch = self._build_epoch(tracker)
        admissions = self._admit_pending(tracker, epoch)
        tracker["ret_10d_status"] = "ok"
        tracker["ret_10d_t1_net"] = 1.0
        original_epoch = copy.deepcopy(epoch)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private_root = root / "state" / "a_short" / "theme_forward_comparison_private" / "v1"
            epoch_path = root / "epoch.json"
            real_write = runner._write_json_atomic
            def fail_epoch_pointer(path, payload):
                if path == epoch_path:
                    raise OSError("simulated outcome-manifest-pointer crash")
                return real_write(path, payload)
            with mock.patch.object(runner, "EPOCH_PATH", epoch_path), \
                    mock.patch.object(runner, "_write_json_atomic", side_effect=fail_epoch_pointer):
                with self.assertRaises(OSError):
                    runner._sync_terminal_outcome_receipts(tracker, epoch, private_root, admissions)
            with mock.patch.object(runner, "EPOCH_PATH", epoch_path):
                resumed = runner._sync_terminal_outcome_receipts(
                    tracker, original_epoch, private_root, admissions
                )
        self.assertEqual(set(resumed), {"20260102"})
        self.assertEqual(original_epoch["outcome_receipt_manifest"], comparison.outcome_receipt_manifest(resumed))

    def test_due_receipt_is_recorded_once_after_output_exists(self):
        epoch = {
            "mode": "frozen_enforced", "epoch_id": "theme-v1", "epoch_start_as_of": "20260904",
            "contract_fingerprint": "a" * 64, "epoch_identity_fingerprint": "e" * 64,
            "formal_decision": {"status": "not_recorded", "as_of": None, "packet_sha256": None},
        }
        packet = {
            "formal_verdict_allowed": True,
            "checkpoints": {"current_checkpoint": "formal_decision_due", "formal_decision_as_of": "20260904"},
            "epoch": {"epoch_id": "theme-v1", "epoch_start_as_of": "20260904", "contract_fingerprint": "a" * 64},
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            packet_path = root / "packet.json"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            epoch_path = root / "epoch.json"
            private_root = root / "state" / "a_short" / "theme_forward_comparison_private" / "v1"
            with mock.patch.object(runner, "EPOCH_PATH", epoch_path), \
                    mock.patch.object(runner, "load_epoch", return_value=epoch):
                runner._record_formal_decision_if_due(packet, packet_path, private_root)
            written = json.loads(epoch_path.read_text(encoding="utf-8"))
            receipt = json.loads((private_root / "epochs" / "theme-v1" / "formal_decision.json").read_text(encoding="utf-8"))
            archived_packet_exists = (private_root / receipt["archive_relative_path"]).is_file()
            archived_packet = (private_root / receipt["archive_relative_path"]).read_text(encoding="utf-8")
            packet_path.write_text(json.dumps({"later": "preview"}), encoding="utf-8")
            archived_packet_after_latest_overwrite = (
                private_root / receipt["archive_relative_path"]
            ).read_text(encoding="utf-8")
        self.assertEqual(written["formal_decision"]["status"], "recorded")
        self.assertEqual(written["formal_decision"]["as_of"], "20260904")
        self.assertRegex(written["formal_decision"]["packet_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(receipt["record_type"], "formal_decision")
        self.assertTrue(archived_packet_exists)
        self.assertEqual(archived_packet_after_latest_overwrite, archived_packet)

    def test_formal_decision_resumes_after_archive_write_before_receipt_or_epoch_commit(self):
        epoch = {
            "mode": "frozen_enforced", "epoch_id": "theme-v1", "epoch_start_as_of": "20260904",
            "contract_fingerprint": "a" * 64, "epoch_identity_fingerprint": "e" * 64,
            "formal_decision": {"status": "not_recorded", "as_of": None, "packet_sha256": None},
        }
        packet = {
            "formal_verdict_allowed": True,
            "checkpoints": {"current_checkpoint": "formal_decision_due", "formal_decision_as_of": "20260904"},
            "epoch": {"epoch_id": "theme-v1", "epoch_start_as_of": "20260904", "contract_fingerprint": "a" * 64},
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            packet_path = root / "packet.json"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            private_root = root / "state" / "a_short" / "theme_forward_comparison_private" / "v1"
            archive_path = private_root / "epochs" / "theme-v1" / "formal_packet.json"
            runner._write_json_exclusive(archive_path, packet)  # simulated crash after step one
            with mock.patch.object(runner, "EPOCH_PATH", root / "epoch.json"), \
                    mock.patch.object(runner, "load_epoch", return_value=epoch):
                runner._record_formal_decision_if_due(packet, packet_path, private_root)
            self.assertTrue((private_root / "epochs" / "theme-v1" / "formal_decision.json").is_file())
            self.assertEqual(json.loads((root / "epoch.json").read_text(encoding="utf-8"))["formal_decision"]["status"], "recorded")

    def test_private_root_inside_repo_must_be_gitignored(self):
        unsafe = ROOT / "state" / "a_short" / "not_private" / "v1"
        with self.assertRaisesRegex(SystemExit, "private root must end"):
            runner._private_root(unsafe)
        safe = ROOT / "state" / "a_short" / "theme_forward_comparison_private" / "v1"
        self.assertEqual(runner._private_root(safe), safe.resolve())

    def test_private_root_rejects_a_correct_suffix_when_git_does_not_ignore_it(self):
        safe_shape = ROOT / "state" / "a_short" / "theme_forward_comparison_private" / "v1"
        with mock.patch.object(runner.subprocess, "run", return_value=mock.Mock(returncode=1)):
            with self.assertRaisesRegex(SystemExit, "not a provably gitignored path"):
                runner._private_root(safe_shape)

    def test_due_packet_cannot_consume_a_replaced_epoch(self):
        epoch = {"mode": "frozen_enforced", "epoch_id": "theme-v2", "epoch_start_as_of": "20260911",
                 "contract_fingerprint": "b" * 64, "epoch_identity_fingerprint": "f" * 64,
                 "formal_decision": {"status": "not_recorded", "as_of": None, "packet_sha256": None}}
        packet = {"formal_verdict_allowed": True,
                  "checkpoints": {"current_checkpoint": "formal_decision_due", "formal_decision_as_of": "20260904"},
                  "epoch": {"epoch_id": "theme-v1", "epoch_start_as_of": "20260904", "contract_fingerprint": "a" * 64}}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "packet.json"
            path.write_text(json.dumps(packet), encoding="utf-8")
            with mock.patch.object(runner, "load_epoch", return_value=epoch):
                with self.assertRaises(SystemExit):
                    runner._record_formal_decision_if_due(
                        packet, path,
                        root / "state" / "a_short" / "theme_forward_comparison_private" / "v1",
                    )

    def test_explicit_start_then_reset_archives_old_epoch_and_arms_only_track_seven(self):
        pre_epoch = {
            "schema_name": "a_short_theme_forward_comparison_epoch", "schema_version": "1.3.0",
            "track": "theme_forward_comparison", "mode": "pre_freeze_audit_only", "epoch_id": None,
            "epoch_start_as_of": None, "governance_fingerprint": None, "contract_fingerprint": None,
            "epoch_identity_fingerprint": None,
            "frozen_theme_ids": [],
            "taxonomy_registry_fingerprint": None,
            "taxonomy_registry_effective_date": None,
            "source_configuration_fingerprints": None,
            "admission_receipt_manifest": comparison.admission_receipt_manifest({}),
            "outcome_receipt_manifest": comparison.outcome_receipt_manifest({}),
            "formal_decision": {
                "status": "not_recorded", "as_of": None, "packet_sha256": None,
                "archive_relative_path": None, "receipt_sha256": None,
            },
            "boundary": {"historical_replay_counts_as_forward": False, "automatic_promotion": False,
                         "production_replacement_authorized": False},
        }
        modes = {track: "pre_freeze_audit_only" for track in runner.epoch_mode.TRACKS}
        tracker = pd.DataFrame(_week("20260102"))
        tracker["ret_10d_status"] = "pending_capture"
        tracker["ret_10d_t1_net"] = pd.NA
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry_path = root / "registry.json"
            registry_path.write_text(json.dumps({"schema_name": "a_short_evidence_epoch_mode_registry",
                                                  "schema_version": "1.0.0", "track_modes": modes}), encoding="utf-8")
            active_path = root / "epoch.json"
            archive_dir = root / "archive"
            with mock.patch.object(runner, "EPOCH_PATH", active_path), \
                    mock.patch.object(runner, "EPOCH_ARCHIVE_DIR", archive_dir), \
                    mock.patch.object(runner.epoch_mode, "TRACK_MODE_REGISTRY_PATH", registry_path), \
                    mock.patch.object(runner, "load_epoch", return_value=pre_epoch), \
                    mock.patch.object(comparison, "_today_date", return_value=pd.Timestamp("20260102").date()):
                opened = runner._start_or_reset_epoch(
                    tracker, "theme-v1", "20260102",
                    root / "state" / "a_short" / "theme_forward_comparison_private" / "v1",
                    reset_epoch=False,
                )
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(opened["mode"], "frozen_enforced")
            self.assertTrue(opened["frozen_theme_ids"])
            self.assertEqual(registry["track_modes"]["theme_forward_comparison"], "frozen_enforced")
            self.assertTrue(all(registry["track_modes"][track] == "pre_freeze_audit_only"
                                for track in runner.epoch_mode.TRACKS if track != "theme_forward_comparison"))
            real_write = runner._write_json_atomic
            def fail_after_archive(path, payload):
                if path == active_path:
                    raise OSError("simulated reset-pointer crash")
                return real_write(path, payload)
            with mock.patch.object(runner, "EPOCH_PATH", active_path), \
                    mock.patch.object(runner, "EPOCH_ARCHIVE_DIR", archive_dir), \
                    mock.patch.object(runner.epoch_mode, "TRACK_MODE_REGISTRY_PATH", registry_path), \
                    mock.patch.object(runner, "load_epoch", return_value=opened), \
                    mock.patch.object(comparison, "_today_date", return_value=pd.Timestamp("20260102").date()), \
                    mock.patch.object(runner, "_write_json_atomic", side_effect=fail_after_archive):
                with self.assertRaisesRegex(OSError, "reset-pointer"):
                    runner._start_or_reset_epoch(
                        tracker, "theme-v2", "20260102",
                        root / "state" / "a_short" / "theme_forward_comparison_private" / "v1",
                        reset_epoch=True,
                    )
            with mock.patch.object(runner, "EPOCH_PATH", active_path), \
                    mock.patch.object(runner, "EPOCH_ARCHIVE_DIR", archive_dir), \
                    mock.patch.object(runner.epoch_mode, "TRACK_MODE_REGISTRY_PATH", registry_path), \
                    mock.patch.object(runner, "load_epoch", return_value=opened), \
                    mock.patch.object(comparison, "_today_date", return_value=pd.Timestamp("20260102").date()):
                replacement = runner._start_or_reset_epoch(
                    tracker, "theme-v2", "20260102",
                    root / "state" / "a_short" / "theme_forward_comparison_private" / "v1",
                    reset_epoch=True,
                )
            self.assertEqual(replacement["epoch_id"], "theme-v2")
            archived = json.loads((archive_dir / "theme-v1.json").read_text(encoding="utf-8"))
            self.assertEqual(archived["epoch_id"], "theme-v1")
            with mock.patch.object(runner, "EPOCH_PATH", active_path), \
                    mock.patch.object(runner, "EPOCH_ARCHIVE_DIR", archive_dir), \
                    mock.patch.object(runner.epoch_mode, "TRACK_MODE_REGISTRY_PATH", registry_path), \
                    mock.patch.object(runner, "load_epoch", return_value=replacement), \
                    mock.patch.object(comparison, "_today_date", return_value=pd.Timestamp("20260102").date()):
                with self.assertRaisesRegex(SystemExit, "already used"):
                    runner._start_or_reset_epoch(
                        tracker, "theme-v1", "20260102",
                        root / "state" / "a_short" / "theme_forward_comparison_private" / "v1",
                        reset_epoch=True,
                    )

    def test_interrupted_epoch_start_resumes_from_matching_admission_receipt(self):
        pre_epoch = {
            "schema_name": "a_short_theme_forward_comparison_epoch", "schema_version": "1.3.0",
            "track": "theme_forward_comparison", "mode": "pre_freeze_audit_only", "epoch_id": None,
            "epoch_start_as_of": None, "governance_fingerprint": None, "contract_fingerprint": None,
            "epoch_identity_fingerprint": None, "frozen_theme_ids": [],
            "taxonomy_registry_fingerprint": None, "taxonomy_registry_effective_date": None,
            "source_configuration_fingerprints": None,
            "admission_receipt_manifest": comparison.admission_receipt_manifest({}),
            "outcome_receipt_manifest": comparison.outcome_receipt_manifest({}),
            "formal_decision": {"status": "not_recorded", "as_of": None, "packet_sha256": None,
                                "archive_relative_path": None, "receipt_sha256": None},
            "boundary": {"historical_replay_counts_as_forward": False, "automatic_promotion": False,
                         "production_replacement_authorized": False},
        }
        modes = {track: "pre_freeze_audit_only" for track in runner.epoch_mode.TRACKS}
        tracker = pd.DataFrame(_week("20260102"))
        tracker["ret_10d_status"] = "pending_capture"
        tracker["ret_10d_t1_net"] = pd.NA
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry_path = root / "registry.json"
            registry_path.write_text(json.dumps({"schema_name": "a_short_evidence_epoch_mode_registry",
                "schema_version": "1.0.0", "track_modes": modes}), encoding="utf-8")
            active_path = root / "epoch.json"
            private_root = root / "state" / "a_short" / "theme_forward_comparison_private" / "v1"
            real_write = runner._write_json_atomic
            def fail_active(path, payload):
                if path == active_path:
                    raise OSError("simulated crash")
                return real_write(path, payload)
            common = {
                "EPOCH_PATH": active_path, "EPOCH_ARCHIVE_DIR": root / "archive",
            }
            with mock.patch.multiple(runner, **common), \
                    mock.patch.object(runner.epoch_mode, "TRACK_MODE_REGISTRY_PATH", registry_path), \
                    mock.patch.object(runner, "load_epoch", return_value=pre_epoch), \
                    mock.patch.object(comparison, "_today_date", return_value=pd.Timestamp("20260102").date()), \
                    mock.patch.object(runner, "_write_json_atomic", side_effect=fail_active):
                with self.assertRaises(OSError):
                    runner._start_or_reset_epoch(tracker, "theme-v1", "20260102", private_root, reset_epoch=False)
            with mock.patch.multiple(runner, **common), \
                    mock.patch.object(runner.epoch_mode, "TRACK_MODE_REGISTRY_PATH", registry_path), \
                    mock.patch.object(runner, "load_epoch", return_value=pre_epoch), \
                    mock.patch.object(comparison, "_today_date", return_value=pd.Timestamp("20260102").date()):
                resumed = runner._start_or_reset_epoch(tracker, "theme-v1", "20260102", private_root, reset_epoch=False)
            self.assertEqual(resumed["epoch_id"], "theme-v1")
            self.assertEqual(json.loads(registry_path.read_text(encoding="utf-8"))["track_modes"]["theme_forward_comparison"], "frozen_enforced")

    def test_normal_runner_reports_checkpoint_without_legacy_review_status_key(self):
        packet = {"checkpoints": {"current_checkpoint": "accumulating"}}
        with tempfile.TemporaryDirectory() as temp:
            tracker_path = Path(temp) / "tracker.csv"
            tracker_path.write_text("as_of,ts_code\n20260102,000001.SZ\n", encoding="utf-8")
            private_root = Path(temp) / "state" / "a_short" / "theme_forward_comparison_private" / "v1"
            pre_epoch = {"mode": "pre_freeze_audit_only"}
            with mock.patch.object(runner, "evaluate_theme_forward_comparison", return_value=packet), \
                    mock.patch.object(runner, "validate_comparison_packet"), \
                    mock.patch.object(runner, "load_epoch", return_value=pre_epoch), \
                    mock.patch.object(runner, "_sync_cohort_admission_receipts", return_value={}), \
                    mock.patch.object(runner, "_sync_terminal_outcome_receipts", return_value={}), \
                    mock.patch.object(runner, "_load_formal_decision_receipt", return_value=None), \
                    mock.patch.object(runner, "_record_formal_decision_if_due"):
                self.assertEqual(runner.main([
                    "--tracker", str(tracker_path), "--out", str(Path(temp) / "out.json"),
                    "--private-root", str(private_root),
                ]), 0)


if __name__ == "__main__":
    unittest.main()
