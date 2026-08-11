"""Offline V5-A/B/C/D revision identity, official gate, and matrix checks."""
from __future__ import annotations

import ast
import copy
import json
import tempfile
import unittest
from pathlib import Path

from engine.a_short_run_revision import (
    RevisionSelectionBlocked,
    build_revision_manifest,
    official_current_view_root,
    public_revision_root,
    read_official_revision,
    research_revision_root,
    select_official_revision,
    write_revision_manifest,
)
from engine.a_short_factor_comparison_v2 import (
    build_v2_public_progress, settle_v2_from_daily_payload,
)
from runners.a_short_official_settlement import settle_official_revision
from tests.test_a_short_factor_comparison_v2 import _capture, _daily_payload, _root as factor_root


ROOT = Path(__file__).resolve().parents[1]
DATE = "20260810"


REVISION_MATRIX = (
    ("EGS", "A-EGS/egs_main.py", "run_revision_id"),
    ("IV", "runners/a_short_iv_feed_build.py", "run_revision_id"),
    ("M67", "runners/a_short_weekly_pipeline.py", "run_revision_id"),
    ("launcher outcomes", "runners/weekly_screening.ps1", "RunRevisionId"),
    ("pipeline outcomes", "runners/a_short_weekly_pipeline.py", "run_revision_id"),
    ("sidecar health", "runners/a_short_weekly_sidecar_health.py", "run_revision_id"),
    ("official operation", "runners/a_short_official_operation_evidence.py", "official_project_root"),
    ("factor v2", "engine/a_short_factor_comparison_v2_weekly.py", "official_project_root"),
    ("margin overheat", "engine/a_short_margin_overheat_cash_control.py", "official_project_root"),
    ("industry weight", "engine/a_short_industry_weight_comparison.py", "official_project_root"),
    ("target policy", "runners/a_short_target_policy_comparison_runner.py", "official_project_root"),
    ("final action", "runners/a_short_final_action_validation_runner.py", "official_project_root"),
    ("overlay", "engine/a_short_overlay_adjudication.py", "official_project_root"),
    ("forward", "runners/forward_tracker.py", "official_project_root"),
    ("theme", "runners/a_short_theme_forward_comparison.py", "official_project_root"),
    ("crash veto", "runners/a_short_crash_veto_tracker.py", "official_project_root"),
)


def _source_tree(relative: str) -> ast.AST:
    return ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)


def _call_uses_keyword(tree: ast.AST, call_names: set[str], keyword: str) -> bool:
    """Require a real production call, not a declaration or string marker."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = function.attr if isinstance(function, ast.Attribute) else function.id if isinstance(function, ast.Name) else ""
        if name in call_names and any(argument.arg == keyword for argument in node.keywords):
            return True
    return False


def _function_has_keyword(relative: str, function_names: set[str], keyword: str) -> bool:
    tree = _source_tree(relative)
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and
        node.name in function_names and
        keyword in {arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}
        for node in ast.walk(tree)
    )


OFFICIAL_CONSUMERS = {
    "official operation": ({"settle_and_summarize"}, "runners/a_short_official_operation_evidence.py"),
    "factor v2": ({"settle_and_summarize_v2_weekly"}, "engine/a_short_factor_comparison_v2_weekly.py"),
    "margin overheat": ({"settle_and_summarize_margin_overheat_weekly"}, "engine/a_short_margin_overheat_cash_control.py"),
    "industry weight": ({"settle_and_summarize_weekly"}, "engine/a_short_industry_weight_comparison.py"),
    "target policy": ({"settle_and_summarize"}, "runners/a_short_target_policy_comparison_runner.py"),
    "final action": ({"settle_and_summarize"}, "runners/a_short_final_action_validation_runner.py"),
    "overlay": ({"settle_and_summarize_weekly"}, "engine/a_short_overlay_adjudication.py"),
}


class AShortV5RevisionMatrixTests(unittest.TestCase):
    def test_sixteen_point_writer_consumer_matrix_proves_production_consumption(self):
        self.assertEqual(len(REVISION_MATRIX), 16)
        self.assertEqual(len({name for name, _, _ in REVISION_MATRIX}), 16)
        # These are production-entry assertions.  Removing the call site (while
        # leaving a parameter declaration or help text behind) must turn this
        # matrix red.
        self.assertTrue(_call_uses_keyword(_source_tree("A-EGS/egs_main.py"), {"export_analysis_input", "publish_egs_run_manifest"}, "run_revision_id"))
        iv_text = (ROOT / "runners/a_short_iv_feed_build.py").read_text(encoding="utf-8")
        self.assertIn("output_parent.name != revision_id", iv_text)
        self.assertIn("failure_parent != output_parent", iv_text)
        self.assertTrue(_call_uses_keyword(_source_tree("runners/a_short_weekly_pipeline.py"), {"settle_and_summarize_v2_weekly"}, "official_project_root"))
        launcher_text = (ROOT / "runners/weekly_screening.ps1").read_text(encoding="utf-8")
        self.assertRegex(launcher_text, r"\$M67Args\s*=.*'--run-revision-id',\s*\$RunRevisionId")
        self.assertTrue(_call_uses_keyword(_source_tree("runners/a_short_weekly_pipeline.py"), {"_write_pipeline_sidecar_outcomes"}, "run_revision_id"))
        self.assertTrue(_call_uses_keyword(_source_tree("runners/a_short_weekly_sidecar_health.py"), {"build_health"}, "run_revision_id"))
        settlement_tree = _source_tree("runners/a_short_official_settlement.py")
        for name, (call_names, consumer) in OFFICIAL_CONSUMERS.items():
            with self.subTest(name=name):
                self.assertTrue((ROOT / consumer).is_file(), consumer)
                self.assertTrue(_call_uses_keyword(settlement_tree, call_names, "official_project_root"))
                self.assertTrue(_function_has_keyword(consumer, {"settle_and_summarize", "settle_and_summarize_weekly", "settle_and_summarize_v2_weekly", "settle_and_summarize_margin_overheat_weekly"}, "official_project_root"))
        self.assertTrue(_call_uses_keyword(settlement_tree, {"backfill"}, "official_project_root"))
        self.assertIn("--official-project-root", (ROOT / "runners/a_short_official_settlement.py").read_text(encoding="utf-8"))
        self.assertTrue(_call_uses_keyword(settlement_tree, {"settle_existing"}, "official_project_root"))
        self.assertRegex(launcher_text, r"forward_tracker\.py backfill[^\r\n]*--official-project-root\s+\$ProjectRoot")
        self.assertRegex(launcher_text, r"--run-revision-id \$RunRevisionId --official-project-root \$ProjectRoot")

    def _bundle(self, root: Path, revision: str, payload: str) -> Path:
        public = public_revision_root(root, DATE, revision)
        research = research_revision_root(root, DATE, revision)
        public.mkdir(parents=True, exist_ok=True)
        research.mkdir(parents=True, exist_ok=True)
        (public / "analysis_input.json").write_text(payload, encoding="utf-8")
        (research / "weekly_m67.json").write_text(payload, encoding="utf-8")
        manifest_path = research / "revision_manifest.json"
        manifest = build_revision_manifest(
            project_root=root, manifest_path=manifest_path,
            decision_as_of=DATE, run_date=DATE, price_data_through="20260809",
            run_revision_id=revision, run_id="v5-matrix-run",
            candidate_digest="a" * 64,
            roles={"analysis_input": public / "analysis_input.json",
                   "weekly_m67": research / "weekly_m67.json"},
        )
        write_revision_manifest(manifest_path, manifest)
        return manifest_path

    def test_five_segment_replay_keeps_all_revisions_and_only_changed_data_switches(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pointer = root / "research" / "results" / "a_short" / DATE / "official_revision.json"
            receipt = pointer.with_name("official_selection_receipt.json")
            transaction = root / "state" / "a_short" / "revision_transactions" / DATE

            first = "a" * 32
            first_path = self._bundle(root, first, "same")
            self.assertEqual(
                select_official_revision(
                    pointer_path=pointer, selection_receipt_path=receipt,
                    manifest_path=first_path, transaction_dir=transaction,
                    run_revision_id=first, decision_as_of=DATE,
                )["status"],
                "selected",
            )
            for revision in ("b" * 32, "c" * 32):
                replay_path = self._bundle(root, revision, "same")
                self.assertEqual(
                    select_official_revision(
                        pointer_path=pointer, selection_receipt_path=receipt,
                        manifest_path=replay_path, transaction_dir=transaction,
                        run_revision_id=revision, decision_as_of=DATE,
                    )["status"],
                    "equivalent_replay",
                )
            changed = "d" * 32
            changed_path = self._bundle(root, changed, "new-data")
            self.assertEqual(
                select_official_revision(
                    pointer_path=pointer, selection_receipt_path=receipt,
                    manifest_path=changed_path, transaction_dir=transaction,
                    run_revision_id=changed, decision_as_of=DATE,
                )["status"],
                "selected",
            )
            validation = "e" * 32
            validation_path = self._bundle(root, validation, "validation-only")
            with self.assertRaises(RevisionSelectionBlocked):
                select_official_revision(
                    pointer_path=pointer, selection_receipt_path=receipt,
                    manifest_path=validation_path, transaction_dir=transaction,
                    run_revision_id=validation, decision_as_of=DATE,
                    cutoff_passed=True,
                )
            self.assertEqual(read_official_revision(pointer)["selected_revision_id"], changed)
            for revision in (first, "b" * 32, "c" * 32, changed, validation):
                self.assertTrue(public_revision_root(root, DATE, revision).is_dir())
            self.assertEqual(
                (official_current_view_root(root, DATE) / "analysis_input.json").read_text(encoding="utf-8"),
                "new-data",
            )

    def test_legacy_is_zero_count_and_selected_revision_is_the_only_formal_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy = settle_official_revision(
                project_root=root, as_of=DATE, run_revision_id=None, include_forward=False,
            )
            self.assertEqual(legacy["status"], "legacy_audit_only")
            self.assertEqual(legacy["formal_count"], 0)
            with self.assertRaises(RevisionSelectionBlocked):
                settle_official_revision(
                    project_root=root, as_of=DATE, run_revision_id="a" * 32,
                    include_forward=False,
                )

    def test_post_selector_settlement_runs_against_selected_revision(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            revision = "a" * 32
            manifest_path = self._bundle(root, revision, "selected")
            pointer = root / "research" / "results" / "a_short" / DATE / "official_revision.json"
            receipt = pointer.with_name("official_selection_receipt.json")
            select_official_revision(
                pointer_path=pointer, selection_receipt_path=receipt,
                manifest_path=manifest_path,
                transaction_dir=root / "state" / "a_short" / "revision_transactions" / DATE,
                run_revision_id=revision, decision_as_of=DATE,
            )
            result = settle_official_revision(
                project_root=root, as_of=DATE, run_revision_id=revision,
                include_forward=False,
            )
            self.assertEqual(result["status"], "settled")
            self.assertEqual(result["official_revision_id"], revision)
            self.assertEqual(result["formal_count"], 1)
            self.assertTrue(result["tracks"])
            self.assertTrue(all(track["official_revision_id"] == revision for track in result["tracks"]))

    def test_factor_public_progress_resolves_three_official_dates_before_current_id(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            private = factor_root(td)
            _capture(private)
            settle_v2_from_daily_payload(root=private, daily_payload=_daily_payload())
            ledger_path = private / "ledger.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            template = ledger["entries"]
            revisions = ("a" * 32, "b" * 32, "c" * 32)
            dates = ("20260202", "20260203", "20260204")
            entries = []
            for decision_date, revision in zip(dates, revisions):
                for row in template:
                    entry = copy.deepcopy(row)
                    entry["decision_date"] = decision_date
                    entry["run_revision_id"] = revision
                    entries.append(entry)
            nonofficial = copy.deepcopy(template[0])
            nonofficial["decision_date"] = "20260205"
            nonofficial["run_revision_id"] = "d" * 32
            entries.append(nonofficial)
            ledger["entries"] = entries
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

            for decision_date, revision in zip(dates, revisions):
                public = public_revision_root(project, decision_date, revision)
                research = research_revision_root(project, decision_date, revision)
                public.mkdir(parents=True, exist_ok=True)
                research.mkdir(parents=True, exist_ok=True)
                analysis = public / "analysis_input.json"
                weekly = research / "weekly_m67.json"
                analysis.write_text(decision_date, encoding="utf-8")
                weekly.write_text(revision, encoding="utf-8")
                manifest_path = research / "revision_manifest.json"
                manifest = build_revision_manifest(
                    project_root=project, manifest_path=manifest_path,
                    decision_as_of=decision_date, run_date=decision_date,
                    price_data_through=decision_date, run_revision_id=revision,
                    run_id="matrix-" + decision_date, candidate_digest="a" * 64,
                    roles={"analysis_input": analysis, "weekly_m67": weekly},
                )
                write_revision_manifest(manifest_path, manifest)
                select_official_revision(
                    pointer_path=project / "research" / "results" / "a_short" / decision_date / "official_revision.json",
                    selection_receipt_path=project / "research" / "results" / "a_short" / decision_date / "official_selection_receipt.json",
                    manifest_path=manifest_path,
                    transaction_dir=project / "state" / "a_short" / "revision_transactions" / decision_date,
                    run_revision_id=revision, decision_as_of=decision_date,
                )

            summary = build_v2_public_progress(
                root=private, as_of="20260210", run_revision_id=revisions[-1],
                official_project_root=project,
            )
            evidence = {row["component_id"]: row for row in summary["evidence"]}
            self.assertTrue(evidence)
            self.assertTrue(all(row["forward_weeks"] == 3 for row in evidence.values()))
            self.assertTrue(all(row["settled_weeks"] == 3 for row in evidence.values()))

    def test_pre_selector_legacy_or_rejected_revision_cannot_create_formal_factor_count(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            private = factor_root(td)
            _capture(private)
            result = settle_v2_from_daily_payload(
                root=private, daily_payload=_daily_payload(),
                run_revision_id="b" * 32, official_project_root=project,
            )
            self.assertEqual(result["status"], "no_official_v2_captures")
            self.assertFalse((private / "weeks" / DATE / "outcome.json").exists())
            progress = build_v2_public_progress(
                root=private, as_of=DATE, run_revision_id="b" * 32,
                official_project_root=project,
            )
            self.assertTrue(progress["evidence"])
            self.assertTrue(all(row["forward_weeks"] == 0 for row in progress["evidence"]))
            self.assertTrue(all(row["settled_weeks"] == 0 for row in progress["evidence"]))


if __name__ == "__main__":
    unittest.main()
