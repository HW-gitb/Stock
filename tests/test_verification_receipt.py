from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".tools"))
import verification_receipt as receipts  # noqa: E402


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_receipt_repo(repo: Path) -> None:
    (repo / "engine").mkdir(parents=True, exist_ok=True)
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    (repo / "engine" / "logic.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "docs" / "note.md").write_text("base\n", encoding="utf-8")
    (repo / "设计说明.md").write_text("base\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".tools/\n", encoding="utf-8")
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.email", "t@example.com")
    _run_git(repo, "config", "user.name", "t")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-m", "base")


def build_docs_only_merge(repo: Path) -> None:
    """A merge whose incoming side touches documents only, while ours touched code.

    This is the shape the gate used to walk straight past: the staged diff holds
    no code, so nothing asked for evidence -- even though the merge is the first
    time these two sides have ever existed together.
    """
    contract = repo / "engine" / "a_short_effect_contract.py"
    contract.parent.mkdir(parents=True, exist_ok=True)
    (repo / "docs").mkdir(exist_ok=True)
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.email", "t@example.com")
    _run_git(repo, "config", "user.name", "t")
    contract.write_text("BASE = 1\n", encoding="utf-8")
    (repo / "docs" / "note.md").write_text("base\n", encoding="utf-8")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-m", "base")

    _run_git(repo, "checkout", "-b", "incoming")
    (repo / "docs" / "note.md").write_text("incoming edits documents only\n", encoding="utf-8")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-m", "docs only")

    _run_git(repo, "checkout", "main")
    contract.write_text("BASE = 2\n", encoding="utf-8")   # our side moved a contract surface
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-m", "ours")
    subprocess.run(["git", "-C", str(repo), "merge", "--no-commit", "--no-ff", "incoming"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


class MergeCombinedStateTests(unittest.TestCase):
    def test_a_merge_widens_the_required_bundles_across_both_sides(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            build_docs_only_merge(repo)
            with patch.object(receipts, "ROOT", repo):
                self.assertTrue(receipts.merge_in_progress())
                # The staged diff is documents only, so the one-sided view asks for nothing...
                self.assertEqual(receipts.required_bundles_for_state({"@CODE_CONTENT": "x"}), ())
                # ...while the surface our own side moved since the base still has to be shown.
                self.assertIn("engine/a_short_effect_contract.py", receipts.merge_side_paths())
                self.assertEqual(
                    receipts.required_bundles_now({"@CODE_CONTENT": "x"}),
                    ("a_short_effect_contract",),
                )

    def test_without_a_merge_nothing_is_widened(self):
        # The widening has to be specific to merges; making every commit demand both sides
        # would be a different, much broader gate than the one that was asked for.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            build_docs_only_merge(repo)
            _run_git(repo, "merge", "--abort")
            with patch.object(receipts, "ROOT", repo):
                self.assertFalse(receipts.merge_in_progress())
                self.assertEqual(receipts.merge_side_paths(), frozenset())
                self.assertEqual(receipts.required_bundles_now({"@CODE_CONTENT": "x"}), ())


class VerificationReceiptTests(unittest.TestCase):
    EFFECT_ARGS = [
        "tests.test_a_short_effect_contract",
        "tests.test_a_short_effect_consumer_probe",
    ]

    def _receipt(self, state: dict[str, str], path: Path, args: list[str] | None = None) -> dict:
        with patch.object(receipts.sys, "executable", str(receipts.PINNED_PYTHON)):
            receipt = receipts.write_focused_receipt(
                result_status="PASS",
                result_exit_code=0,
                tests=17,
                elapsed_seconds=1.25,
                timeout_seconds=300,
                unittest_args=args or self.EFFECT_ARGS,
                state=state,
                path=path,
            )
        self.assertIsNotNone(receipt)
        return receipt or {}

    def test_every_recorded_field_is_inside_the_integrity_seal(self):
        """Class fix: no recorded field may sit outside receipt_id's hash.

        The first form hashed only code_fingerprint + unittest_args, so `tests`
        -- the number quoted as evidence -- could be inflated and still
        validate.  Mutating ANY field must now break the integrity check.
        """
        state = {"engine/a_short_effect_contract.py": "sha", "@CODE_CONTENT": "tree"}
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self._receipt(state, Path(tmp) / "r.json")
        mutations = {
            "tests": 99999,
            "elapsed_seconds": 0.001,
            "timeout_seconds": 1300,
            "recorded_at": "1999-01-01T00:00:00",
            "schema_version": "9.9",
            "tier": "full",
            "status": "PASS ",
            "exit_code": 0,
        }
        self.assertTrue(set(mutations).issubset(receipt), "a recorded field escaped this matrix")
        for field, value in mutations.items():
            if receipt[field] == value:
                continue
            tampered = dict(receipt, **{field: value})
            self.assertNotEqual(
                receipt["receipt_id"],
                receipts._receipt_id(tampered),
                f"{field} is outside the integrity seal",
            )
        # And the honest receipt still validates against its own seal.
        self.assertEqual(receipt["receipt_id"], receipts._receipt_id(receipt))

    def test_inflated_test_count_is_rejected_end_to_end(self):
        """The exact reviewer probe that found the hole: 17 -> 99999."""
        state = {"engine/a_short_effect_contract.py": "sha", "@CODE_CONTENT": "tree"}
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self._receipt(state, Path(tmp) / "r.json")
        inflated = dict(receipt, tests=99999)
        ok, reason = receipts.validate_receipt(inflated, state=state)
        self.assertFalse(ok)
        self.assertIn("integrity check failed", reason)

    def test_effect_surface_requires_both_contract_and_consumer_modules(self):
        state = {
            "engine/a_short_effect_contract.py": "sha",
            "@CODE_CONTENT": "tree",
        }
        self.assertEqual(
            receipts.required_bundles_for_state(state),
            ("a_short_effect_contract",),
        )
        self.assertEqual(
            receipts.bundle_for_args(self.EFFECT_ARGS),
            ("a_short_effect_contract",),
        )

    def test_free_text_focused_evidence_is_rejected(self):
        state = {"engine/x.py": "sha", "@CODE_CONTENT": "tree"}
        with tempfile.TemporaryDirectory() as tmp:
            _, reason = receipts.validate_focused_evidence(
                "focused=17 OK",
                state=state,
                path=Path(tmp) / "receipt.json",
            )
        self.assertIn("machine token", reason)

    def test_receipt_is_bound_to_code_state_and_token(self):
        # The seal is the `@` content key; the per-path entries beside it record
        # which files a commit touches and deliberately do not seal anything.
        state = {"engine/x.py": "sha", "@CODE_CONTENT": "content"}
        changed = {"engine/x.py": "sha", "@CODE_CONTENT": "different content"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            receipt = self._receipt(state, path, ["tests.test_example"])
            token = receipts.receipt_token(receipt)
            # This test isolates receipt/token binding.  Merge-side bundle
            # widening is covered by MergeCombinedStateTests above; patching
            # it here keeps the assertion deterministic when the real repo has
            # an unresolved, uncommitted merge.
            with patch.object(receipts, "merge_side_paths", return_value=frozenset()):
                loaded, reason = receipts.validate_focused_evidence(
                    token, state=state, path=path
                )
                self.assertEqual(reason, "OK")
                self.assertEqual(loaded, receipt)
                _, changed_reason = receipts.validate_focused_evidence(
                    token, state=changed, path=path
                )
                self.assertIn("current code state", changed_reason)

    def test_docs_only_mutation_keeps_receipt_valid_and_code_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            build_receipt_repo(repo)
            with patch.object(receipts, "ROOT", repo):
                before = receipts.collect_code_state()
                receipt_path = repo / ".tools" / "state" / "receipt.json"
                receipt = self._receipt(before, receipt_path, ["tests.test_example"])
                token = receipts.receipt_token(receipt)

                (repo / "docs" / "note.md").write_text("docs-only edit\n", encoding="utf-8")
                docs_state = receipts.collect_code_state()
                self.assertEqual(receipts.fingerprint(before), receipts.fingerprint(docs_state))
                loaded, reason = receipts.validate_focused_evidence(
                    token, state=docs_state, path=receipt_path,
                )
                self.assertEqual(reason, "OK")
                self.assertEqual(loaded, receipt)

                (repo / "engine" / "logic.py").write_text("VALUE = 2\n", encoding="utf-8")
                code_state = receipts.collect_code_state()
                self.assertNotEqual(receipts.fingerprint(before), receipts.fingerprint(code_state))
                _, reason = receipts.validate_focused_evidence(
                    token, state=code_state, path=receipt_path,
                )
                self.assertIn("current code state", reason)

    def test_staging_and_committing_the_tested_bytes_keeps_the_receipt_valid(self):
        """The seal answers "same bytes?", never "same git status?".

        A focused run tests file contents.  `git add` and `git commit` of those
        exact contents prove nothing new, so demanding a rerun for them is a
        rerun that can only reconfirm what was already confirmed.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            build_receipt_repo(repo)
            with patch.object(receipts, "ROOT", repo):
                receipt_path = repo / ".tools" / "state" / "receipt.json"
                # Edit code, then take the receipt: this is the real order.
                (repo / "engine" / "logic.py").write_text("VALUE = 2\n", encoding="utf-8")
                tested = receipts.collect_code_state()
                self.assertIn("@CODE_CONTENT", tested)
                self.assertNotIn("@CODE_TREE", tested)
                self.assertNotIn("@HEAD", tested)
                receipt = self._receipt(tested, receipt_path, ["tests.test_example"])
                token = receipts.receipt_token(receipt)

                _run_git(repo, "add", "engine/logic.py")
                staged = receipts.collect_code_state()
                self.assertEqual(receipts.fingerprint(tested), receipts.fingerprint(staged))

                _run_git(repo, "commit", "-m", "commit the exact tested bytes")
                committed = receipts.collect_code_state()
                self.assertEqual(receipts.fingerprint(tested), receipts.fingerprint(committed))
                self.assertEqual(committed["@CODE_CONTENT"], tested["@CODE_CONTENT"])
                # The changed-path view legitimately empties out; it is not sealed.
                self.assertEqual([k for k in committed if not k.startswith("@")], [])
                loaded, reason = receipts.validate_focused_evidence(
                    token, state=committed, path=receipt_path
                )
                self.assertEqual(reason, "OK")
                self.assertEqual(loaded, receipt)

    def test_docs_stay_out_while_any_real_code_content_change_invalidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            build_receipt_repo(repo)
            with patch.object(receipts, "ROOT", repo):
                before = receipts.collect_code_state()
                receipt_path = repo / ".tools" / "state" / "receipt.json"
                receipt = self._receipt(before, receipt_path, ["tests.test_example"])
                token = receipts.receipt_token(receipt)

                (repo / "docs" / "note.md").write_text("docs edit\n", encoding="utf-8")
                (repo / "设计说明.md").write_text("root markdown edit\n", encoding="utf-8")
                _run_git(repo, "add", "docs/note.md")
                _run_git(repo, "commit", "-m", "docs-only receipt control")
                docs_commit_state = receipts.collect_code_state()
                self.assertEqual(
                    receipts.fingerprint(before), receipts.fingerprint(docs_commit_state)
                )
                loaded, reason = receipts.validate_focused_evidence(
                    token, state=docs_commit_state, path=receipt_path
                )
                self.assertEqual(reason, "OK")
                self.assertEqual(loaded, receipt)

                # Each of these is a different byte-level truth and must break the seal.
                for label, mutate in (
                    ("edit", lambda: (repo / "engine" / "logic.py").write_text(
                        "VALUE = 99\n", encoding="utf-8")),
                    ("add", lambda: (repo / "engine" / "extra.py").write_text(
                        "NEW = 1\n", encoding="utf-8")),
                    ("delete", lambda: (repo / "engine" / "logic.py").unlink()),
                ):
                    with self.subTest(mutation=label):
                        mutate()
                        mutated = receipts.collect_code_state()
                        self.assertNotEqual(
                            receipts.fingerprint(before), receipts.fingerprint(mutated)
                        )
                        _, reason = receipts.validate_focused_evidence(
                            token, state=mutated, path=receipt_path
                        )
                        self.assertIn("current code state", reason)

    def test_retyping_a_path_without_touching_its_bytes_still_breaks_the_seal(self):
        """An id is not a file: the same blob typed as a symlink is a symlink.

        The retired tree hash covered mode and type because it hashed whole
        `ls-tree` lines.  Sealing the object id alone would have let a path be
        re-typed to `120000` (symlink) or `160000` (gitlink) -- which changes
        what a POSIX checkout executes -- without moving the fingerprint.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            build_receipt_repo(repo)
            with patch.object(receipts, "ROOT", repo):
                receipt_path = repo / ".tools" / "state" / "receipt.json"
                before = receipts.collect_code_state()
                receipt = self._receipt(before, receipt_path, ["tests.test_example"])
                token = receipts.receipt_token(receipt)
                blob = subprocess.run(
                    ["git", "-C", str(repo), "rev-parse", ":engine/logic.py"],
                    capture_output=True, text=True, check=True,
                ).stdout.strip()

                # `--chmod` isolates the mode: same blob, same bytes on disk, and
                # (with core.filemode off) git does not even report the path as
                # dirty -- so only sealing the mode itself can catch it.
                _run_git(repo, "update-index", "--chmod=+x", "engine/logic.py")
                chmodded = receipts.collect_code_state()
                self.assertNotEqual(
                    receipts.fingerprint(before), receipts.fingerprint(chmodded)
                )
                _, reason = receipts.validate_focused_evidence(
                    token, state=chmodded, path=receipt_path
                )
                self.assertIn("current code state", reason)

                _run_git(repo, "update-index", "--chmod=-x", "engine/logic.py")
                self.assertEqual(
                    receipts.fingerprint(before),
                    receipts.fingerprint(receipts.collect_code_state()),
                )

                # Same id, re-typed as a symlink: on a POSIX checkout that path
                # stops being the module and becomes a link named by its text.
                _run_git(repo, "update-index", "--cacheinfo", f"120000,{blob},engine/logic.py")
                self.assertNotEqual(
                    receipts.fingerprint(before),
                    receipts.fingerprint(receipts.collect_code_state()),
                )

    def test_explain_exit_code_mirrors_the_gate_it_explains(self):
        """`--explain` must be a superset of the check, never a softer one.

        The reason anyone reaches for it is an opaque FAIL, so an explain that
        always exited 0 would disarm the hook the first time someone wired it
        in for legibility.
        """
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            build_receipt_repo(repo)
            with patch.object(receipts, "ROOT", repo):
                receipt_path = repo / ".tools" / "state" / "receipt.json"
                state = receipts.collect_code_state()
                self._receipt(state, receipt_path, ["tests.test_example"])
                with patch.object(receipts, "pinned_python_error", return_value=None):
                    code, _ = receipts.explain(state=state, path=receipt_path)
                    self.assertEqual(code, 0)

                    (repo / "engine" / "logic.py").write_text("V = 9\n", encoding="utf-8")
                    code, lines = receipts.explain(
                        state=receipts.collect_code_state(), path=receipt_path
                    )
                    self.assertEqual(code, 1)
                    self.assertIn("verdict            : FAIL", "\n".join(lines))

                    code, _ = receipts.explain(state=state, path=repo / "absent.json")
                    self.assertEqual(code, 1)
                # a wrong interpreter is a FAIL for the plain gate, so also here
                with patch.object(receipts, "pinned_python_error", return_value="wrong python"):
                    code, _ = receipts.explain(state=state, path=receipt_path)
                    self.assertEqual(code, 1)

    def test_explain_names_what_the_gate_is_comparing(self):
        """A one-line FAIL cannot tell a missing receipt from a moved file."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            build_receipt_repo(repo)
            with patch.object(receipts, "ROOT", repo):
                receipt_path = repo / ".tools" / "state" / "receipt.json"
                state = receipts.collect_code_state()
                receipt = self._receipt(state, receipt_path, ["tests.test_example"])

                text = "\n".join(receipts.explain_lines(state=state, path=receipt_path))
                self.assertIn(receipt["receipt_id"], text)
                self.assertIn("fingerprints match : yes", text)
                self.assertIn("required bundles   : ()", text)
                self.assertIn("verdict            : PASS", text)

                (repo / "engine" / "logic.py").write_text("VALUE = 3\n", encoding="utf-8")
                moved = receipts.collect_code_state()
                text = "\n".join(receipts.explain_lines(state=moved, path=receipt_path))
                self.assertIn("fingerprints match : NO", text)
                self.assertIn("engine/logic.py", text)      # names the file that moved
                self.assertIn("verdict            : FAIL", text)

                missing = "\n".join(
                    receipts.explain_lines(state=moved, path=repo / "nope.json")
                )
                self.assertIn("receipt            : missing/unreadable", missing)

    def test_receipt_boundary_and_pre_commit_gate_keep_docs_out_but_code_in(self):
        self.assertFalse(receipts.is_code_path("docs/note.py"))
        self.assertFalse(receipts.is_code_path("notes/readme.md"))
        self.assertFalse(receipts.is_code_path("设计说明.md"))
        self.assertTrue(receipts.is_code_path("engine/logic.py"))
        hook = (receipts.ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
        self.assertIn("git diff --cached --name-only | grep -vE", hook)
        self.assertIn('if [ -n "$code_changed" ] || [ -n "$merging" ]; then', hook)
        self.assertIn('"$PY" .tools/verification_receipt.py', hook)

    def test_effect_receipt_without_consumer_bundle_is_rejected(self):
        state = {
            "runners/a_short_weekly_pipeline.py": "sha",
            "@CODE_CONTENT": "tree",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            receipt = self._receipt(state, path, ["tests.test_a_short_effect_contract"])
            _, reason = receipts.validate_focused_evidence(
                receipts.receipt_token(receipt), state=state, path=path
            )
        self.assertIn("missing bundle", reason)


if __name__ == "__main__":
    unittest.main()
