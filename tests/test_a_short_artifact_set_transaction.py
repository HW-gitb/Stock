"""The artifact-set transaction must be all-or-nothing, including across a crash."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_artifact_set_transaction import (  # noqa: E402
    ArtifactSetTransactionError,
    BACKUP_DIR_NAME,
    JOURNAL_NAME,
    commit_artifact_set,
    read_journal,
    recover,
)
from engine import a_short_artifact_set_transaction as transaction  # noqa: E402


class ArtifactSetTransactionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.journal_dir = self.base / "private" / "journal"
        self.public = self.base / "public"
        self.public.mkdir(parents=True)
        self.old = {
            self.public / "summary.json": b'{"as_of": "20260727"}\n',
            self.public / "summary.md": b"# old\n",
        }
        for path, payload in self.old.items():
            path.write_bytes(payload)
        self.new = {
            self.public / "summary.json": b'{"as_of": "20260803"}\n',
            self.public / "summary.md": b"# new\n",
        }
        self.addCleanup(self._tmp.cleanup)

    def _on_disk(self):
        return {path: path.read_bytes() if path.is_file() else None for path in self.old}

    def _residue(self):
        return sorted(p.name for p in self.public.iterdir() if p.name.startswith("."))

    def _fail_on_target_replace(self, nth, targets=None):
        """Fail the nth replace of a *public target*, passing everything else through.

        The journal is written with the same primitive, so counting raw calls
        would silently move the injection onto the journal instead of the file
        it is meant to interrupt.
        """
        watched = {str(p) for p in (targets if targets is not None else self.old)}
        # The rollback replaces onto the same paths, so a raw tally keeps rising
        # after the injection; `fired` is what the assertions care about.
        seen = {"n": 0, "fired": False}
        real_replace = os.replace

        def replace(src, dst):
            if str(dst) in watched:
                seen["n"] += 1
                if seen["n"] == nth:
                    seen["fired"] = True
                    raise OSError(f"injected failure on target replace #{nth}")
            return real_replace(src, dst)

        return replace, seen

    def test_a_whole_set_lands_together(self):
        commit_artifact_set(self.journal_dir, self.new)
        self.assertEqual(self._on_disk(), self.new)
        self.assertIsNone(read_journal(self.journal_dir))
        self.assertEqual(self._residue(), [])

    def test_a_failure_on_the_nth_replace_restores_every_old_byte(self):
        replace, calls = self._fail_on_target_replace(2)
        with mock.patch.object(transaction.os, "replace", side_effect=replace):
            with self.assertRaises(OSError):
                commit_artifact_set(self.journal_dir, self.new)
        self.assertTrue(calls["fired"], "the injection must land on the 2nd target, not the journal")
        self.assertEqual(self._on_disk(), self.old)
        self.assertIsNone(read_journal(self.journal_dir))
        self.assertEqual(self._residue(), [])

    def test_a_target_that_did_not_exist_is_removed_again_on_failure(self):
        # Targets commit in sorted order, so `extra.json` -- a file that did not
        # exist before -- is created first and the injection lands after it.
        third = self.public / "extra.json"
        payloads = dict(self.new)
        payloads[third] = b"{}\n"
        replace, calls = self._fail_on_target_replace(2, targets=payloads)
        with mock.patch.object(transaction.os, "replace", side_effect=replace):
            with self.assertRaises(OSError):
                commit_artifact_set(self.journal_dir, payloads)
        self.assertTrue(calls["fired"])
        self.assertTrue(third.name < "summary.json", "extra.json must sort first to be created")
        self.assertEqual(self._on_disk(), self.old)
        self.assertFalse(third.exists(), "a target created by the failed set must not survive")
        self.assertEqual(self._residue(), [])

    def test_a_dead_process_is_rolled_back_before_the_next_read(self):
        # Simulate the crash: commit half the set and leave the journal behind,
        # exactly the state a killed process leaves.
        replace, calls = self._fail_on_target_replace(1)
        with mock.patch.object(transaction, "_clear"):
            with mock.patch.object(transaction, "_undo"):
                with mock.patch.object(transaction.os, "replace", side_effect=replace):
                    with self.assertRaises(OSError):
                        commit_artifact_set(self.journal_dir, self.new)
        self.assertTrue(calls["fired"])
        journal = read_journal(self.journal_dir)
        self.assertIsNotNone(journal, "a killed run must leave its journal on disk")
        self.assertEqual(len(journal["entries"]), 2)

        report = recover(self.journal_dir)
        self.assertEqual(self._on_disk(), self.old)
        self.assertTrue(report["recovered"])
        self.assertIsNone(read_journal(self.journal_dir))
        self.assertFalse((self.journal_dir / BACKUP_DIR_NAME).exists())

    def test_a_second_commit_recovers_the_stale_journal_before_writing(self):
        (self.journal_dir).mkdir(parents=True)
        stale = {
            "schema_name": "a_short_artifact_set_journal",
            "schema_version": "1.0.0",
            "entries": [{"target": str(self.public / "summary.md"), "backup": "000.bak"}],
        }
        backup_dir = self.journal_dir / BACKUP_DIR_NAME
        backup_dir.mkdir()
        (backup_dir / "000.bak").write_bytes(b"# recovered\n")
        (self.journal_dir / JOURNAL_NAME).write_text(json.dumps(stale), encoding="utf-8")
        # a later run must not write new bytes over the unresolved backup set
        commit_artifact_set(self.journal_dir, {self.public / "summary.json": b"{}\n"})
        self.assertEqual((self.public / "summary.md").read_bytes(), b"# recovered\n")
        self.assertEqual((self.public / "summary.json").read_bytes(), b"{}\n")
        self.assertIsNone(read_journal(self.journal_dir))

    def test_recover_is_a_no_op_without_a_journal(self):
        self.assertIsNone(recover(self.journal_dir))
        self.assertEqual(self._on_disk(), self.old)

    def _strand_journal_without_backups(self):
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        stranded = {
            "schema_name": "a_short_artifact_set_journal",
            "schema_version": "1.0.0",
            "entries": [{"target": str(path), "backup": f"{i:03d}.bak"}
                        for i, path in enumerate(sorted(self.old, key=lambda p: p.as_posix()))],
        }
        (self.journal_dir / JOURNAL_NAME).write_text(json.dumps(stranded), encoding="utf-8")

    def test_a_journal_whose_backups_are_gone_does_not_refuse_the_track(self):
        """Closure 1: the reviewer's exact probe -- journal present, backups deleted."""
        self._strand_journal_without_backups()
        report = recover(self.journal_dir)
        self.assertTrue(report["unrestorable"], "the missing backups must be reported")
        self.assertIsNone(read_journal(self.journal_dir), "the journal must not survive")
        commit_artifact_set(self.journal_dir, self.new)
        self.assertEqual(self._on_disk(), self.new)

    def test_a_stranded_journal_is_cleared_by_the_next_commit_itself(self):
        """The same probe without an explicit recover(): commit must still go through."""
        self._strand_journal_without_backups()
        commit_artifact_set(self.journal_dir, self.new)
        self.assertEqual(self._on_disk(), self.new)
        self.assertIsNone(read_journal(self.journal_dir))

    def test_a_torn_journal_does_not_refuse_the_track(self):
        """Closure 2: the reviewer's other probe -- zero-byte and half-JSON journals."""
        for corrupt in (b"", b'{"entries": [{"target"'):
            with self.subTest(corrupt=corrupt):
                self.journal_dir.mkdir(parents=True, exist_ok=True)
                (self.journal_dir / JOURNAL_NAME).write_bytes(corrupt)
                report = recover(self.journal_dir)
                self.assertTrue(report["journal_unreadable"])
                self.assertIsNone(read_journal(self.journal_dir))
                commit_artifact_set(self.journal_dir, self.new)
                self.assertEqual(self._on_disk(), self.new)
                for path, payload in self.old.items():
                    path.write_bytes(payload)

    def test_a_real_half_applied_state_is_still_rolled_back(self):
        """Closure 3: relaxing the two cases above must not relax a genuine rollback."""
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        backup_dir = self.journal_dir / BACKUP_DIR_NAME
        backup_dir.mkdir(exist_ok=True)
        entries = []
        for i, path in enumerate(sorted(self.old, key=lambda p: p.as_posix())):
            (backup_dir / f"{i:03d}.bak").write_bytes(self.old[path])
            entries.append({"target": str(path), "backup": f"{i:03d}.bak"})
            path.write_bytes(self.new[path])          # the half-applied new bytes
        (self.journal_dir / JOURNAL_NAME).write_text(json.dumps(
            {"schema_name": "a_short_artifact_set_journal", "schema_version": "1.0.0",
             "entries": entries}), encoding="utf-8")
        report = recover(self.journal_dir)
        self.assertEqual(report["unrestorable"], [])
        self.assertEqual(self._on_disk(), self.old, "a real half-applied set must be undone")

    def test_an_in_flight_rollback_failure_still_propagates(self):
        """Non-strict recovery must not soften the in-flight rollback path."""
        with mock.patch.object(transaction, "_replace_durably",
                               side_effect=OSError("disk gone")):
            with self.assertRaises(OSError):
                commit_artifact_set(self.journal_dir, self.new)

    def test_the_clear_order_is_what_prevents_the_wedge(self):
        """Closure 4 (planted): put the old `backups first` order back -- closure 1 reds."""
        real_clear = transaction._clear

        def backups_first(journal_dir):
            journal_path, backup_dir = transaction._journal_paths(Path(journal_dir))
            if backup_dir.is_dir():
                for child in backup_dir.iterdir():
                    child.unlink(missing_ok=True)
                backup_dir.rmdir()
            raise OSError("killed between deleting the backups and the journal")

        self.assertIsNot(backups_first, real_clear)
        commit_dir = self.journal_dir
        with mock.patch.object(transaction, "_clear", side_effect=backups_first):
            with self.assertRaises(OSError):
                commit_artifact_set(commit_dir, self.new)
        # exactly the state the reviewer reproduced: journal present, backups gone
        self.assertIsNotNone(read_journal(commit_dir))
        self.assertFalse((commit_dir / BACKUP_DIR_NAME).exists())
        # and the repaired recovery still refuses to wedge on it
        commit_artifact_set(commit_dir, self.new)
        self.assertEqual(self._on_disk(), self.new)

    def test_the_journal_may_not_live_in_published_results(self):
        published = self.base / "research" / "results" / "a_short" / "journal"
        with self.assertRaises(ArtifactSetTransactionError):
            commit_artifact_set(published, self.new)
        self.assertEqual(self._on_disk(), self.old)
        self.assertFalse(published.exists())

    def test_an_empty_set_touches_nothing(self):
        commit_artifact_set(self.journal_dir, {})
        self.assertEqual(self._on_disk(), self.old)
        self.assertFalse(self.journal_dir.exists())


if __name__ == "__main__":
    unittest.main()
