import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.a_short_run_revision import (
    RevisionIdentityConflict,
    RevisionSelectionBlocked,
    build_revision_manifest,
    new_run_revision_id,
    official_current_view_root,
    official_analysis_input_path,
    official_public_revision_root,
    phase4_reports_manifest_path,
    public_revision_root,
    read_official_revision,
    research_revision_root,
    select_official_revision,
    write_revision_manifest,
    write_phase4_reports_manifest,
)
from engine.a_short_run_paths import run_bundle_dir


class AShortRunRevisionTest(unittest.TestCase):
    def _bundle(self, root: Path, revision: str, *, payload: str = "same",
                extra_public_role: str | None = None) -> tuple[Path, dict]:
        public = public_revision_root(root, "20260810", revision)
        research = research_revision_root(root, "20260810", revision)
        public.mkdir(parents=True, exist_ok=True)
        research.mkdir(parents=True, exist_ok=True)
        analysis = public / "analysis_input.json"
        weekly = research / "weekly_m67.json"
        analysis.write_text(payload, encoding="utf-8")
        weekly.write_text(payload, encoding="utf-8")
        manifest_path = research / "revision_manifest.json"
        roles = {"analysis_input": analysis, "weekly_m67": weekly}
        if extra_public_role:
            extra = public / extra_public_role
            extra.write_text(f"{payload}:{extra_public_role}", encoding="utf-8")
            roles["extra_public_role"] = extra
        manifest = build_revision_manifest(
            project_root=root,
            manifest_path=manifest_path,
            decision_as_of="20260810",
            run_date="20260810",
            price_data_through="20260809",
            run_revision_id=revision,
            run_id="a-short-20260810-0123456789abcdef",
            candidate_digest="a" * 64,
            roles=roles,
        )
        return manifest_path, manifest

    def test_revision_id_and_paths_are_central_and_strict(self):
        revision = new_run_revision_id()
        self.assertRegex(revision, r"^[0-9a-f]{32}$")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(
                public_revision_root(root, "20260810", revision),
                root / "result" / "a_short" / "20260810" / "revisions" / revision,
            )
            self.assertEqual(
                research_revision_root(root, "20260810", revision),
                root / "research" / "results" / "a_short" / "20260810" / "revisions" / revision,
            )
            self.assertEqual(
                Path(run_bundle_dir(
                    "20260810", output_root="result/a_short", project_root=root,
                    run_revision_id=revision,
                )),
                root / "result" / "a_short" / "20260810" / "revisions" / revision,
            )

    def test_official_reader_resolves_pointer_and_legacy_is_read_only_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            revision = "a" * 32
            manifest_path, manifest = self._bundle(root, revision)
            write_revision_manifest(manifest_path, manifest)
            pointer = root / "research" / "results" / "a_short" / "20260810" / "official_revision.json"
            receipt = pointer.with_name("official_selection_receipt.json")
            select_official_revision(
                pointer_path=pointer, selection_receipt_path=receipt,
                manifest_path=manifest_path,
                transaction_dir=root / "state" / "a_short" / "revision_transactions" / "20260810",
                run_revision_id=revision, decision_as_of="20260810",
            )
            self.assertEqual(
                official_public_revision_root(root, "20260810"),
                public_revision_root(root, "20260810", revision),
            )
            self.assertEqual(
                official_analysis_input_path(root, "20260810"),
                public_revision_root(root, "20260810", revision) / "analysis_input.json",
            )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(
                official_analysis_input_path(root, "20260810"),
                root / "result" / "a_short" / "20260810" / "analysis_input.json",
            )

    def test_official_current_view_switch_replaces_managed_roles_but_preserves_legacy_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pointer = root / "research" / "results" / "a_short" / "20260810" / "official_revision.json"
            receipt = pointer.with_name("official_selection_receipt.json")
            transaction = root / "state" / "a_short" / "revision_transactions" / "20260810"

            first_path, first = self._bundle(
                root, "a" * 32, payload="first", extra_public_role="stale-managed.json"
            )
            write_revision_manifest(first_path, first)
            select_official_revision(
                pointer_path=pointer, selection_receipt_path=receipt,
                manifest_path=first_path, transaction_dir=transaction,
                run_revision_id="a" * 32, decision_as_of="20260810",
            )
            current = official_current_view_root(root, "20260810")
            legacy = current / "legacy-only.json"
            legacy.write_text("old", encoding="utf-8")
            stale_managed = current / "stale-managed.json"
            self.assertTrue(stale_managed.exists())

            second_path, second = self._bundle(root, "b" * 32, payload="changed")
            write_revision_manifest(second_path, second)
            result = select_official_revision(
                pointer_path=pointer, selection_receipt_path=receipt,
                manifest_path=second_path, transaction_dir=transaction,
                run_revision_id="b" * 32, decision_as_of="20260810",
            )

            self.assertEqual(result["status"], "selected")
            self.assertEqual((current / "analysis_input.json").read_text(encoding="utf-8"), "changed")
            self.assertTrue(legacy.exists())
            self.assertFalse(stale_managed.exists())
            self.assertEqual(
                (public_revision_root(root, "20260810", "a" * 32) / "analysis_input.json").read_text(encoding="utf-8"),
                "first",
            )

    def test_first_official_selection_never_deletes_unmanaged_legacy_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = official_current_view_root(root, "20260810")
            current.mkdir(parents=True)
            legacy = current / "candidates.csv"
            legacy.write_text("legacy-bytes", encoding="utf-8")
            manifest_path, manifest = self._bundle(root, "a" * 32, payload="first")
            write_revision_manifest(manifest_path, manifest)
            pointer = root / "research" / "results" / "a_short" / "20260810" / "official_revision.json"
            receipt = pointer.with_name("official_selection_receipt.json")
            select_official_revision(
                pointer_path=pointer, selection_receipt_path=receipt,
                manifest_path=manifest_path,
                transaction_dir=root / "state" / "a_short" / "revision_transactions" / "20260810",
                run_revision_id="a" * 32, decision_as_of="20260810",
            )
            self.assertEqual(legacy.read_text(encoding="utf-8"), "legacy-bytes")

    def test_first_official_selection_never_overwrites_same_named_legacy_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = official_current_view_root(root, "20260810")
            current.mkdir(parents=True)
            legacy = current / "analysis_input.json"
            legacy.write_text("legacy-bytes", encoding="utf-8")
            manifest_path, manifest = self._bundle(root, "a" * 32, payload="official-bytes")
            write_revision_manifest(manifest_path, manifest)
            pointer = root / "research" / "results" / "a_short" / "20260810" / "official_revision.json"
            receipt = pointer.with_name("official_selection_receipt.json")
            select_official_revision(
                pointer_path=pointer, selection_receipt_path=receipt,
                manifest_path=manifest_path,
                transaction_dir=root / "state" / "a_short" / "revision_transactions" / "20260810",
                run_revision_id="a" * 32, decision_as_of="20260810",
            )
            self.assertEqual(legacy.read_text(encoding="utf-8"), "legacy-bytes")

    def test_phase4_reports_are_revision_scoped_and_legacy_date_root_is_not_managed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = official_current_view_root(root, "20260810")
            legacy_reports = current / "reports"
            legacy_reports.mkdir(parents=True)
            legacy = legacy_reports / "legacy.md"
            legacy.write_text("legacy-bytes", encoding="utf-8")
            pointer = root / "research" / "results" / "a_short" / "20260810" / "official_revision.json"
            receipt = pointer.with_name("official_selection_receipt.json")
            transaction = root / "state" / "a_short" / "revision_transactions" / "20260810"

            def bundle_with_reports(revision: str, payload: str):
                manifest_path, _ = self._bundle(root, revision, payload=payload)
                public = public_revision_root(root, "20260810", revision)
                reports = public / "reports"
                reports.mkdir(parents=True, exist_ok=True)
                (reports / f"{revision[0]}.md").write_text(payload, encoding="utf-8")
                self.assertEqual(write_phase4_reports_manifest(root, "20260810", revision), "written")
                index = phase4_reports_manifest_path(root, "20260810", revision)
                manifest = build_revision_manifest(
                    project_root=root, manifest_path=manifest_path,
                    decision_as_of="20260810", run_date="20260810",
                    price_data_through="20260809", run_revision_id=revision,
                    run_id="a-short-20260810-0123456789abcdef",
                    candidate_digest="a" * 64,
                    roles={
                        "analysis_input": public / "analysis_input.json",
                        "weekly_m67": research_revision_root(root, "20260810", revision) / "weekly_m67.json",
                        "phase4_reports_manifest": index,
                    },
                )
                write_revision_manifest(manifest_path, manifest)
                return manifest_path

            first_path = bundle_with_reports("a" * 32, "first")
            select_official_revision(
                pointer_path=pointer, selection_receipt_path=receipt,
                manifest_path=first_path, transaction_dir=transaction,
                run_revision_id="a" * 32, decision_as_of="20260810",
            )
            self.assertTrue((public_revision_root(root, "20260810", "a" * 32) / "reports" / "a.md").is_file())
            self.assertTrue((current / "phase4_reports_manifest.json").is_file())
            self.assertEqual(legacy.read_text(encoding="utf-8"), "legacy-bytes")

            second_path = bundle_with_reports("b" * 32, "second")
            select_official_revision(
                pointer_path=pointer, selection_receipt_path=receipt,
                manifest_path=second_path, transaction_dir=transaction,
                run_revision_id="b" * 32, decision_as_of="20260810",
            )
            self.assertTrue((public_revision_root(root, "20260810", "a" * 32) / "reports" / "a.md").is_file())
            self.assertTrue((public_revision_root(root, "20260810", "b" * 32) / "reports" / "b.md").is_file())
            self.assertEqual(legacy.read_text(encoding="utf-8"), "legacy-bytes")

    def test_private_role_reference_is_deidentified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private = root / "state" / "a_short" / "weekly_private" / "weeks" / "20260810" / "revisions" / ("a" * 32)
            private.mkdir(parents=True)
            private_file = private / "weekly_m67.json"
            private_file.write_text("private", encoding="utf-8")
            manifest = build_revision_manifest(
                project_root=root,
                manifest_path=root / "research" / "results" / "a_short" / "20260810" / "revisions" / ("a" * 32) / "revision_manifest.json",
                decision_as_of="20260810", run_date="20260810", price_data_through="20260809",
                run_revision_id="a" * 32, run_id="run", candidate_digest="a" * 64,
                roles={"weekly_m67": private_file},
            )
            reference = manifest["roles"]["weekly_m67"]["relative_path"]
            self.assertTrue(reference.startswith("private://"))
            self.assertNotIn(str(root), reference)
            self.assertNotIn("state", reference)

    def test_manifest_must_live_in_its_revision_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, manifest = self._bundle(root, "a" * 32)
            with self.assertRaises(ValueError):
                write_revision_manifest(root / "revision_manifest.json", manifest)

    def test_same_revision_is_idempotent_and_changed_payload_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, manifest = self._bundle(Path(tmp), "a" * 32)
            self.assertEqual(write_revision_manifest(path, manifest), "written")
            before = path.read_bytes()
            self.assertEqual(write_revision_manifest(path, manifest), "already_current")
            self.assertEqual(path.read_bytes(), before)
            changed_path, changed = self._bundle(Path(tmp), "a" * 32, payload="changed")
            with self.assertRaises(RevisionIdentityConflict):
                write_revision_manifest(changed_path, changed)
            self.assertEqual(path.read_bytes(), before)

    def test_official_selection_pointer_and_receipt_share_rollback_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            revision = "a" * 32
            manifest_path, manifest = self._bundle(root, revision)
            write_revision_manifest(manifest_path, manifest)
            pointer = root / "research" / "results" / "a_short" / "20260810" / "official_revision.json"
            receipt = pointer.with_name("official_selection_receipt.json")
            transaction = root / "state" / "a_short" / "revision_transactions" / "20260810"
            result = select_official_revision(
                pointer_path=pointer, selection_receipt_path=receipt,
                manifest_path=manifest_path, transaction_dir=transaction,
                run_revision_id=revision, decision_as_of="20260810",
            )
            self.assertEqual(result["status"], "selected")
            self.assertEqual(read_official_revision(pointer)["selected_revision_id"], revision)
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["selected_revision_id"], revision)
            pointer_bytes = pointer.read_bytes()
            receipt_bytes = receipt.read_bytes()
            self.assertEqual(
                select_official_revision(
                    pointer_path=pointer, selection_receipt_path=receipt,
                    manifest_path=manifest_path, transaction_dir=transaction,
                    run_revision_id=revision, decision_as_of="20260810",
                )["status"],
                "already_current",
            )
            self.assertEqual(pointer.read_bytes(), pointer_bytes)
            self.assertEqual(receipt.read_bytes(), receipt_bytes)

    def test_equivalent_replay_does_not_switch_and_formal_switch_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_path, first = self._bundle(root, "a" * 32)
            write_revision_manifest(first_path, first)
            pointer = root / "research" / "results" / "a_short" / "20260810" / "official_revision.json"
            receipt = pointer.with_name("official_selection_receipt.json")
            transaction = root / "state" / "a_short" / "revision_transactions" / "20260810"
            select_official_revision(
                pointer_path=pointer, selection_receipt_path=receipt,
                manifest_path=first_path, transaction_dir=transaction,
                run_revision_id="a" * 32, decision_as_of="20260810",
            )
            second_path, second = self._bundle(root, "b" * 32)
            write_revision_manifest(second_path, second)
            self.assertEqual(
                select_official_revision(
                    pointer_path=pointer, selection_receipt_path=receipt,
                    manifest_path=second_path, transaction_dir=transaction,
                    run_revision_id="b" * 32, decision_as_of="20260810",
                )["status"],
                "equivalent_replay",
            )
            third_path, third = self._bundle(root, "c" * 32, payload="changed")
            write_revision_manifest(third_path, third)
            with self.assertRaises(RevisionSelectionBlocked):
                select_official_revision(
                    pointer_path=pointer, selection_receipt_path=receipt,
                    manifest_path=third_path, transaction_dir=transaction,
                    run_revision_id="c" * 32, decision_as_of="20260810",
                    formal_state_committed=True,
                )

    def test_pointer_and_receipt_remain_unchanged_when_publish_transaction_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest = self._bundle(root, "a" * 32)
            write_revision_manifest(manifest_path, manifest)
            pointer = root / "research" / "results" / "a_short" / "20260810" / "official_revision.json"
            receipt = pointer.with_name("official_selection_receipt.json")
            transaction = root / "state" / "a_short" / "revision_transactions" / "20260810"
            with patch("engine.a_short_run_revision.commit_artifact_set", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    select_official_revision(
                        pointer_path=pointer, selection_receipt_path=receipt,
                        manifest_path=manifest_path, transaction_dir=transaction,
                        run_revision_id="a" * 32, decision_as_of="20260810",
                    )
            self.assertFalse(pointer.exists())
            self.assertFalse(receipt.exists())

    def test_cutoff_blocks_initial_official_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest = self._bundle(root, "a" * 32)
            write_revision_manifest(manifest_path, manifest)
            with self.assertRaises(RevisionSelectionBlocked):
                select_official_revision(
                    pointer_path=root / "research" / "results" / "a_short" / "20260810" / "official_revision.json",
                    selection_receipt_path=root / "research" / "results" / "a_short" / "20260810" / "official_selection_receipt.json",
                    manifest_path=manifest_path,
                    transaction_dir=root / "state" / "a_short" / "revision_transactions" / "20260810",
                    run_revision_id="a" * 32, decision_as_of="20260810", cutoff_passed=True,
                )


if __name__ == "__main__":
    unittest.main()
