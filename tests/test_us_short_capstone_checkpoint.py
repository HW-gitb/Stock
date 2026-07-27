from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from engine import us_short_capstone_checkpoint as checkpoint
from engine.us_short_private_paths import PrivatePathError
from runners import us_short_weekly_capstone as capstone


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


class CapstoneCheckpointTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="us_short_checkpoint_")
        self.root = Path(self.temp.name)
        self.universe = SimpleNamespace(
            name="universe_fetch", contract_version="1.0.0",
            reuse_policy="refresh_then_reuse_if_equivalent",
        )
        self.momentum = SimpleNamespace(
            name="momentum_fetch", contract_version="1.0.0", reuse_policy="frozen_inputs",
        )
        self.stages = [self.universe, self.momentum]
        self.run_contract = {
            "authorized_momentum_top_k": 200, "authorized_pass2_call_budget": 10,
            "catalyst_recall_tickers": [], "frozen_holding_tickers": [],
            "theme_soft_boost_enabled": True,
        }
        self.manifest_path, self.manifest = checkpoint.create_manifest(
            private_root=self.root / "private",
            decision_date="20260713",
            price_basis_date="20260710",
            generated_at="2026-07-12T08:00:00-04:00",
            run_contract=self.run_contract,
            stages=self.stages,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_checkpoint_write_fails_closed_when_destination_is_not_provably_private(self):
        with mock.patch.object(
            checkpoint, "reject_nonprivate_output_path", side_effect=PrivatePathError("not private"),
        ), self.assertRaisesRegex(checkpoint.CapstoneCheckpointError, "provably private"):
            checkpoint.create_manifest(
                private_root=self.root / "blocked", decision_date="20260713", price_basis_date="20260710",
                generated_at="2026-07-12T08:00:00-04:00", run_contract=self.run_contract, stages=self.stages,
            )
        self.assertFalse((self.root / "blocked").exists())

    def test_in_repo_production_checkpoint_destination_is_gitignored_private(self):
        production_path = checkpoint.ROOT / "state" / "us_short" / "capstone_checkpoints_private" / \
            "20260713" / ("a" * 64) / "checkpoint_manifest.json"
        checkpoint._guard_private(production_path)
        self.assertFalse(production_path.exists())

    def test_record_stage_rolls_back_bundle_when_manifest_write_fails(self):
        stage = SimpleNamespace(
            name="soft_discovery", contract_version="1.0.0", reuse_policy="never",
            failure_policy="zero_effect", output_policy="optional",
            checkpoint_policy="optional_result_only",
        )
        manifest_path, manifest = checkpoint.create_manifest(
            private_root=self.root / "optional", decision_date="20260713", price_basis_date="20260710",
            generated_at="2026-07-12T08:00:00-04:00", run_contract=self.run_contract, stages=[stage],
        )
        output = _write(self.root / "source" / "soft_discovery.json", {"status": "invalid_evidence"})
        with mock.patch.object(
            checkpoint, "_write_manifest", side_effect=OSError("injected manifest write failure"),
        ), self.assertRaisesRegex(OSError, "injected manifest write failure"):
            checkpoint.record_stage(
                manifest_path=manifest_path, manifest=manifest, stage=stage,
                execution_mode="executed", generated_at="2026-07-12T08:10:00-04:00",
                observed_at="2026-07-12T08:10:00-04:00", input_paths=[], input_logical_paths=[],
                output_paths=[output], output_logical_paths=["state/us_short/soft_discovery.json"],
                result={"status": "invalid_evidence"},
            )
        self.assertFalse((manifest_path.parent / "artifacts").exists())
        self.assertFalse((manifest_path.parent / "checkpoint_manifest.json.tmp").exists())

    def test_cross_root_restore_requires_exact_input_and_bundle_digest(self):
        candidate = _write(self.root / "source" / "candidate.json", {"facts": [1, 2, 3]})
        series = _write(self.root / "source" / "series.json", {"points": [10, 11]})
        self.manifest = checkpoint.record_stage(
            manifest_path=self.manifest_path, manifest=self.manifest, stage=self.momentum,
            execution_mode="executed", generated_at="2026-07-12T08:10:00-04:00",
            observed_at="2026-07-12T08:10:00-04:00",
            input_paths=[candidate], input_logical_paths=["state/us_short/candidate.json"],
            output_paths=[series], output_logical_paths=["state/us_short/series.json"], result={"ok": True},
        )

        imported_candidate = _write(self.root / "other_worktree" / "candidate.json", {"facts": [1, 2, 3]})
        imported_series = self.root / "other_worktree" / "series.json"
        restored = checkpoint.restore_stage(
            source_manifest_path=self.manifest_path, source_manifest=self.manifest, stage=self.momentum,
            input_paths=[imported_candidate], input_logical_paths=["state/us_short/candidate.json"],
            output_paths=[imported_series], output_logical_paths=["state/us_short/series.json"],
        )
        self.assertIsNotNone(restored)
        self.assertEqual(json.loads(imported_series.read_text(encoding="utf-8")), {"points": [10, 11]})

        _write(imported_candidate, {"facts": [9]})
        self.assertIsNone(checkpoint.restore_stage(
            source_manifest_path=self.manifest_path, source_manifest=self.manifest, stage=self.momentum,
            input_paths=[imported_candidate], input_logical_paths=["state/us_short/candidate.json"],
            output_paths=[imported_series], output_logical_paths=["state/us_short/series.json"],
        ))

        bundled = self.manifest_path.parent / self.manifest["stages"][0]["output_manifest"][0]["bundle_path"]
        bundled.write_text("tampered", encoding="utf-8")
        _write(imported_candidate, {"facts": [1, 2, 3]})
        with self.assertRaisesRegex(checkpoint.CapstoneCheckpointError, "digest mismatch"):
            checkpoint.restore_stage(
                source_manifest_path=self.manifest_path, source_manifest=self.manifest, stage=self.momentum,
                input_paths=[imported_candidate], input_logical_paths=["state/us_short/candidate.json"],
                output_paths=[imported_series], output_logical_paths=["state/us_short/series.json"],
            )

    def test_volatile_refresh_reuses_old_bound_output_only_when_non_clock_facts_match(self):
        old = _write(self.root / "source" / "candidate.json", {
            "generated_at": "old", "rows": [{"ticker": "AAA", "observed_at": "old", "status": "active"}],
        })
        self.manifest = checkpoint.record_stage(
            manifest_path=self.manifest_path, manifest=self.manifest, stage=self.universe,
            execution_mode="executed", generated_at="old", observed_at="old",
            input_paths=[], input_logical_paths=[], output_paths=[old],
            output_logical_paths=["state/us_short/candidate.json"], result={"provider_calls": 1},
        )
        refreshed = _write(self.root / "new" / "candidate.json", {
            "generated_at": "new", "rows": [{"ticker": "AAA", "observed_at": "new", "status": "active"}],
        })
        self.assertTrue(checkpoint.refresh_output_from_equivalent_checkpoint(
            source_manifest_path=self.manifest_path, source_manifest=self.manifest, stage=self.universe,
            output_paths=[refreshed], output_logical_paths=["state/us_short/candidate.json"],
        ))
        self.assertEqual(json.loads(refreshed.read_text(encoding="utf-8"))["generated_at"], "old")

        _write(refreshed, {
            "generated_at": "newer", "rows": [{"ticker": "AAA", "observed_at": "newer", "status": "halted"}],
        })
        self.assertFalse(checkpoint.refresh_output_from_equivalent_checkpoint(
            source_manifest_path=self.manifest_path, source_manifest=self.manifest, stage=self.universe,
            output_paths=[refreshed], output_logical_paths=["state/us_short/candidate.json"],
        ))
        self.assertEqual(json.loads(refreshed.read_text(encoding="utf-8"))["rows"][0]["status"], "halted")

    def test_clock_or_pipeline_mismatch_rejects_bundle_before_restore(self):
        loaded = checkpoint.load_manifest(self.manifest_path)
        with self.assertRaisesRegex(checkpoint.CapstoneCheckpointError, "decision/price clock"):
            checkpoint.validate_resume_header(
                loaded, decision_date="20260714", price_basis_date="20260710", stages=self.stages,
                run_contract=self.run_contract,
            )
        drifted = [self.universe, SimpleNamespace(
            name="momentum_fetch", contract_version="1.0.1", reuse_policy="frozen_inputs",
        )]
        with self.assertRaisesRegex(checkpoint.CapstoneCheckpointError, "pipeline contract"):
            checkpoint.validate_resume_header(
                loaded, decision_date="20260713", price_basis_date="20260710",
                run_contract=self.run_contract, stages=drifted,
            )
        changed_contract = dict(self.run_contract, frozen_holding_tickers=["AAPL"])
        with self.assertRaisesRegex(checkpoint.CapstoneCheckpointError, "non-file run contract"):
            checkpoint.validate_resume_header(
                loaded, decision_date="20260713", price_basis_date="20260710",
                run_contract=changed_contract, stages=self.stages,
            )

    def test_restore_rejects_output_cardinality_mismatch(self):
        with self.assertRaisesRegex(checkpoint.CapstoneCheckpointError, "counts differ"):
            checkpoint.restore_stage(
                source_manifest_path=self.manifest_path, source_manifest=self.manifest, stage=self.momentum,
                input_paths=[], input_logical_paths=[], output_paths=[],
                output_logical_paths=["state/us_short/series.json"],
            )

    def test_create_manifest_prunes_superseded_older_decision_checkpoints(self):
        base = (self.root / "private" / "capstone_checkpoints_private").resolve()
        self.assertTrue((base / "20260713").is_dir())  # setUp created the current-week bundle
        checkpoint.create_manifest(
            private_root=self.root / "private", decision_date="20260701", price_basis_date="20260630",
            generated_at="2026-06-30T08:00:00-04:00", run_contract=self.run_contract, stages=self.stages,
        )
        decoy = base / "keepme"
        decoy.mkdir(parents=True, exist_ok=True)
        (decoy / "x.json").write_text("{}", encoding="utf-8")
        self.assertTrue((base / "20260701").is_dir())
        # a new current-week run prunes strictly-older 8-digit-date dirs, keeps the current date + the non-date decoy
        checkpoint.create_manifest(
            private_root=self.root / "private", decision_date="20260713", price_basis_date="20260710",
            generated_at="2026-07-12T09:00:00-04:00", run_contract=self.run_contract, stages=self.stages,
        )
        self.assertFalse((base / "20260701").exists())
        self.assertTrue((base / "20260713").is_dir())
        self.assertTrue(decoy.is_dir())


class CapstoneResumeIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="us_short_resume_integration_")
        self.root = Path(self.temp.name)
        self.private = self.root / "private"
        self.state = self.root / "state"
        self.inputs = self.private / "_run_inputs"
        _write(self.inputs / "account.json", {"positions": []})
        _write(self.inputs / "template.json", {"template": True})

    def tearDown(self):
        self.temp.cleanup()

    def _pipeline(self, order: list[str], *, universe_fact: str):
        def universe(ctx):
            order.append("universe_fetch")
            _write(ctx.candidate_path, {
                "generated_at": ctx.generated_at,
                "rows": [{"ticker": "AAA", "observed_at": ctx.observed_at, "status": universe_fact}],
            })
            return {"generated_at": ctx.generated_at, "provider_calls": 1}

        def momentum(ctx):
            order.append("momentum_fetch")
            _write(ctx.series_packet_path, {"candidate_sha": checkpoint._sha256_file(ctx.candidate_path)})
            return {"generated_at": ctx.generated_at, "provider_calls": 1}

        def bridge(ctx):
            order.append("weekly_bridge")
            outputs = [
                (ctx.official_output_root or ctx.private_root) / "weekly_private" / ctx.decision_date / "weekly_report.md",
                (ctx.official_output_root or ctx.private_root) / "weekly_private" / ctx.decision_date / "action_table.csv",
                (ctx.official_output_root or ctx.private_root) / "runs_private" / ctx.decision_date / "machine_record.json",
            ]
            for output in outputs:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("ok", encoding="utf-8")
            return {"batch4_run": {"emitted": True, "output_paths": {
                "weekly_report_path": str(outputs[0]), "action_table_path": str(outputs[1]),
                "machine_record_path": str(outputs[2]),
            }}}

        return [
            capstone.Stage(
                "universe_fetch", True, lambda _c: [], lambda c: [c.candidate_path], universe,
                contract_version="1.0.0", reuse_policy="refresh_then_reuse_if_equivalent",
            ),
            capstone.Stage(
                "momentum_fetch", True, lambda c: [c.candidate_path], lambda c: [c.series_packet_path], momentum,
                contract_version="1.0.0", reuse_policy="frozen_inputs",
            ),
            capstone.Stage(
                "weekly_bridge", False, lambda c: [c.series_packet_path],
                lambda c: [
                    (c.official_output_root or c.private_root) / "weekly_private" / c.decision_date / "weekly_report.md",
                    (c.official_output_root or c.private_root) / "weekly_private" / c.decision_date / "action_table.csv",
                    (c.official_output_root or c.private_root) / "runs_private" / c.decision_date / "machine_record.json",
                ], bridge,
            ),
        ]

    def _run(self, *, now_et, pipeline, resume_from=None):
        with mock.patch.object(capstone, "default_pipeline", return_value=pipeline), \
                mock.patch.object(capstone, "_provider_execution_receipt", return_value=object()), \
                mock.patch("runners.us_short_account_state_from_manual_tables.validate_account_state"):
            return capstone.run_weekly_capstone(
                now_et=now_et,
                private_root=self.private,
                batch4_template_path=self.inputs / "template.json",
                account_state_path=self.inputs / "account.json",
                authorized_momentum_top_k=200,
                authorized_pass2_call_budget=10,
                confirm_user_authorization=True,
                dry_run=False,
                state_dir=self.state,
                sample_root=self.root,
                resume_from=resume_from,
            )

    def test_resume_refreshes_volatile_stage_and_reuses_bound_frozen_stage_only_when_equivalent(self):
        from datetime import datetime

        first_order: list[str] = []
        first = self._run(
            now_et=datetime(2026, 7, 9, 8, 0, 0), pipeline=self._pipeline(first_order, universe_fact="active"),
        )
        second_order: list[str] = []
        second = self._run(
            now_et=datetime(2026, 7, 9, 8, 30, 0), pipeline=self._pipeline(second_order, universe_fact="active"),
            resume_from=Path(first["checkpoint_manifest"]),
        )
        self.assertEqual(first_order, ["universe_fetch", "momentum_fetch", "weekly_bridge"])
        self.assertEqual(second_order, ["universe_fetch", "weekly_bridge"])
        modes = {row["name"]: row["execution_mode"] for row in second["stages"]}
        self.assertEqual(modes["universe_fetch"], "refreshed_equivalent")
        self.assertEqual(modes["momentum_fetch"], "reused")
        self.assertEqual(modes["weekly_bridge"], "executed")

        changed_order: list[str] = []
        changed = self._run(
            now_et=datetime(2026, 7, 9, 8, 45, 0), pipeline=self._pipeline(changed_order, universe_fact="halted"),
            resume_from=Path(first["checkpoint_manifest"]),
        )
        self.assertEqual(changed_order, ["universe_fetch", "momentum_fetch", "weekly_bridge"])
        self.assertEqual(
            {row["name"]: row["execution_mode"] for row in changed["stages"]}["momentum_fetch"], "executed",
        )

    def test_resume_restore_failure_is_fail_closed(self):
        from datetime import datetime

        first_order: list[str] = []
        first = self._run(
            now_et=datetime(2026, 7, 9, 8, 0, 0), pipeline=self._pipeline(first_order, universe_fact="active"),
        )
        with mock.patch.object(
            checkpoint, "restore_stage", side_effect=checkpoint.CapstoneCheckpointError("injected restore failure"),
        ), self.assertRaisesRegex(capstone.WeeklyCapstoneError, "resume checkpoint restore failed"):
            self._run(
                now_et=datetime(2026, 7, 9, 8, 30, 0),
                pipeline=self._pipeline([], universe_fact="active"),
                resume_from=Path(first["checkpoint_manifest"]),
            )

    def test_resume_recovers_a_published_transaction_journal_before_stage_execution(self):
        from datetime import datetime

        first_order: list[str] = []
        first = self._run(
            now_et=datetime(2026, 7, 9, 8, 0, 0), pipeline=self._pipeline(first_order, universe_fact="active"),
        )
        crash_tag = "interrupted-published"
        journal = self.private / "weekly_private" / "_transaction_state" / "20260709.json"
        capstone._write_transaction_journal(journal, tag=crash_tag, phase="published")
        histories = []
        stagings = []
        for surface in ("weekly_private", "runs_private"):
            _current, history, staging = capstone._transaction_paths(
                capstone.resolve_capstone_context(
                    now_et=datetime(2026, 7, 9, 8, 15, 0), private_root=self.private,
                    batch4_template_path=self.inputs / "template.json",
                    account_state_path=self.inputs / "account.json", state_dir=self.state, sample_root=self.root,
                ), crash_tag, surface,
            )
            _write(history / "leftover.json", {"stale": True})
            _write(staging / "leftover.json", {"stale": True})
            histories.append(history)
            stagings.append(staging)

        resumed_order: list[str] = []
        self._run(
            now_et=datetime(2026, 7, 9, 8, 30, 0), pipeline=self._pipeline(resumed_order, universe_fact="active"),
            resume_from=Path(first["checkpoint_manifest"]),
        )
        self.assertFalse(journal.exists())
        self.assertTrue(all(path.exists() for path in histories))
        self.assertTrue(all(not path.exists() for path in stagings))
        self.assertEqual(resumed_order, ["universe_fetch", "weekly_bridge"])


if __name__ == "__main__":
    unittest.main()
