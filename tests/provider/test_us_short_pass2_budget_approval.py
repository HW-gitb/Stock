from __future__ import annotations

import json
import os
import shutil
import sys
import subprocess
import tempfile
import textwrap
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _candidate_artifact,
    _constant_projection,
)
from tests.provider.us_short_projection_binding_test_helpers import bound_projection  # noqa: E402
from tests.provider.us_short_private_test_root import temporary_provider_directory  # noqa: E402
from runners import us_short_batch5_full_candidate_pass2_preflight as pass2_preflight  # noqa: E402


DECISION_DATE = "20260615"
PRICE_BASIS_DATE = "20260612"
GENERATED_AT = "2026-06-13T10:00:00+00:00"


class Pass2BudgetApprovalScriptEntryTest(unittest.TestCase):
    def test_direct_script_entry_reuses_canonical_pass2_approval_class(self):
        probe = textwrap.dedent(
            r'''
            import importlib
            import importlib.util
            import sys
            from pathlib import Path
            from types import SimpleNamespace

            root = Path(sys.argv[1])
            capstone_path = root / "runners" / "us_short_weekly_capstone.py"
            spec = importlib.util.spec_from_file_location("us_short_capstone_script_entry", capstone_path)
            script_module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = script_module
            spec.loader.exec_module(script_module)

            canonical = importlib.import_module("runners.us_short_weekly_capstone")
            assert script_module.Pass2BudgetApproval is canonical.Pass2BudgetApproval

            approval = script_module.Pass2BudgetApproval(
                decision_date="20260813",
                candidate_price_basis_date="20260812",
                candidate_artifact_sha256="0" * 64,
                momentum_top_k=200,
                target_count=200,
                exact_pass2_calls=1001,
                authorization_mode="one_click_test",
                authorization_ref="one_click_test:direct-script",
                generated_at="2026-08-13T12:00:00+00:00",
            )
            ctx = SimpleNamespace(
                budget_approval=approval,
                authorized_momentum_top_k=approval.momentum_top_k,
                authorized_pass2_call_budget=approval.exact_pass2_calls,
            )

            from runners import us_short_batch5_full_candidate_live_source_packet as live_source
            from runners import us_short_weekly_capstone_stages as stages
            from runners import us_short_yfinance_grades_fetch as yfinance

            assert stages._require_budget_approval(ctx) is approval
            assert yfinance._approval_binding(approval) == approval.binding_summary()
            assert live_source._approval_binding(approval) == approval.binding_summary()
            '''
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe, str(ROOT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )


class Pass2BudgetApprovalContractTest(unittest.TestCase):
    def setUp(self):
        self.actual_clock_patch = mock.patch(
            "engine.us_short_live_provider_preflight._now_et_wall_clock",
            return_value=datetime(2026, 7, 9, 8, 0, 0),
        )
        self.actual_clock_patch.start()
        self.tempdir = temporary_provider_directory(
            ROOT,
            Path("provider_samples/us_short_batch5_full_candidate_pass2_preflight_20260706"),
        )
        self.test_root = Path(self.tempdir.__enter__())
        self.state_dir = self.test_root / "state" / "us_short"
        self.state_dir.mkdir(parents=True)
        from runners import us_short_batch5_full_candidate_pass2_preflight as preflight

        self.state_patch = mock.patch.object(
            preflight, "STATE_US_SHORT_DIR", self.state_dir,
        )
        self.state_patch.start()
        self.paths = {
            "candidate": self.state_dir / "candidate.json",
            "momentum": self.state_dir / "momentum.json",
            "theme": self.state_dir / "theme.json",
            "summary": self.test_root / "summary.json",
        }
        self._prepare(200)

    def tearDown(self):
        self.actual_clock_patch.stop()
        self.state_patch.stop()
        self.tempdir.__exit__(None, None, None)

    def _prepare(self, count: int):
        from runners import us_short_batch5_full_candidate_pass2_preflight as preflight

        tickers = tuple(f"X{index:03d}" for index in range(count))
        candidate = _candidate_artifact(tickers)
        self.paths["candidate"].write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for path, value_key, component, disposition in (
            (self.paths["momentum"], "momentum_by_ticker", "momentum", "scored"),
            (self.paths["theme"], "theme_block_by_ticker", "theme", "scored_theme_base"),
        ):
            projection = _constant_projection(value_key, tickers, disposition, score=50.0)
            path.write_text(
                json.dumps(
                    bound_projection(candidate_path=self.paths["candidate"], component=component, projection=projection),
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
        self.runner = preflight

    def _preview(self):
        return self.runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=DECISION_DATE,
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["summary"],
            momentum_top_k=200,
            confirm_user_authorization=True,
            generated_at=GENERATED_AT,
        )

    def _approval(self, summary):
        from runners.us_short_weekly_capstone import Pass2BudgetApproval

        return Pass2BudgetApproval(
            decision_date=summary["decision_clock"]["expected_decision_date"],
            candidate_price_basis_date=summary["decision_clock"]["candidate_price_basis_date"],
            candidate_artifact_sha256=summary["candidate_universe"]["candidate_artifact_sha256"],
            momentum_top_k=summary["pass2_target_universe"]["momentum_top_k"],
            target_count=summary["pass2_target_universe"]["target_count"],
            exact_pass2_calls=summary["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"],
            authorization_mode="one_click_test",
            authorization_ref="one_click_test:unit",
            generated_at=summary["generated_at"],
        )

    def test_one_click_preview_200_finalizes_to_1001_without_second_budget_derivation(self):
        with mock.patch.object(self.runner, "_forecast_calls", wraps=self.runner._forecast_calls) as forecast:
            preview = self._preview()
            approval = self._approval(preview)
            final = self.runner.finalize_preflight_from_existing_derivation(
                preflight_summary_path=self.paths["summary"],
                approval_binding=approval.binding_summary(),
            )

        self.assertEqual(preview["pass2_target_universe"]["target_count"], 200)
        self.assertEqual(preview["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"], 1001)
        self.assertEqual(forecast.call_count, 1)
        self.assertTrue(final["execution_gate"]["ready_to_run_full_candidate_live_packet"])
        self.assertTrue(final["execution_gate"]["authorized_budget_matches_rederived_forecast"])
        self.assertEqual(final["execution_gate"]["block_reasons"], [])
        self.assertEqual(final["execution_gate"]["approval_binding"], approval.binding_summary())

    def test_finalization_is_fail_closed_for_missing_or_mismatched_approval(self):
        preview = self._preview()
        approval = self._approval(preview)
        with self.assertRaisesRegex(self.runner.FullCandidatePass2PreflightError, "approval"):
            self.runner.finalize_preflight_from_existing_derivation(
                preflight_summary_path=self.paths["summary"], approval_binding=None)

        for field, value in (
            ("exact_pass2_calls", 1000),
            ("decision_date", "20260616"),
            ("candidate_artifact_sha256", "1" * 64),
            ("target_count", 199),
        ):
            with self.subTest(field=field):
                forged = replace(approval, **{field: value})
                with self.assertRaises(self.runner.FullCandidatePass2PreflightError):
                    self.runner.finalize_preflight_from_existing_derivation(
                        preflight_summary_path=self.paths["summary"],
                        approval_binding=forged.binding_summary(),
                    )

        forged_binding = approval.binding_summary()
        forged_binding["authorization_ref"] = "one_click_test:tampered"
        with self.assertRaisesRegex(self.runner.FullCandidatePass2PreflightError, "fingerprint"):
            self.runner.finalize_preflight_from_existing_derivation(
                preflight_summary_path=self.paths["summary"], approval_binding=forged_binding
            )

    def test_existing_manual_budget_conflict_cannot_be_overwritten_by_new_approval(self):
        preview = self._preview()
        approval = self._approval(preview)
        conflicted = json.loads(self.paths["summary"].read_text(encoding="utf-8"))
        conflicted["execution_gate"]["authorized_total_call_budget"] = 1000
        self.paths["summary"].write_text(
            json.dumps(conflicted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(self.runner.FullCandidatePass2PreflightError, "conflicts"):
            self.runner.finalize_preflight_from_existing_derivation(
                preflight_summary_path=self.paths["summary"], approval_binding=approval.binding_summary()
            )

    def test_finalized_preflight_requires_approval_at_direct_provider_boundaries(self):
        from runners import us_short_batch5_full_candidate_live_source_packet as live
        from runners import us_short_yfinance_grades_fetch as yfinance

        preview = self._preview()
        approval = self._approval(preview)
        self.runner.finalize_preflight_from_existing_derivation(
            preflight_summary_path=self.paths["summary"], approval_binding=approval.binding_summary()
        )
        with self.assertRaisesRegex(live.FullCandidateLiveSourcePacketError, "requires the matching Pass2 budget approval"):
            live._load_ready_preflight(self.paths["summary"], 1001)
        with self.assertRaisesRegex(live.FullCandidateLiveSourcePacketError, "finalized Pass2 budget approval"):
            live._fetch_live_records(
                selected_symbols=[],
                raw_root=self.paths["candidate"].parent,
                client=mock.Mock(),
                fmp_env=SimpleNamespace(value="fmp"),
                sec_env=SimpleNamespace(value="sec"),
                massive_env=SimpleNamespace(value="massive"),
                sec_sleep_seconds=0.0,
                max_total_endpoint_calls=1001,
                max_total_http_attempts=1001,
                provider_pace_seconds=0.0,
                max_retries_per_call=0,
                retry_backoff_seconds=0.0,
                fetch_fmp_grades=True,
                budget_approval=None,
            )
        with self.assertRaisesRegex(yfinance.YFinanceGradesFetchError, "requires the matching Pass2 budget approval"):
            yfinance._load_ready_preflight(self.paths["summary"])

        # A historical/direct preflight can be ready before this approval-binding
        # contract existed.  It must not become a legacy bypass at either live
        # provider boundary.
        legacy_ready = self.runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=DECISION_DATE,
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["summary"],
            momentum_top_k=200,
            authorized_total_call_budget=1001,
            confirm_user_authorization=True,
            generated_at=GENERATED_AT,
        )
        self.assertNotIn("approval_binding", legacy_ready["execution_gate"])
        with self.assertRaisesRegex(live.FullCandidateLiveSourcePacketError, "requires the matching Pass2 budget approval"):
            live._load_ready_preflight(self.paths["summary"], 1001)
        with self.assertRaisesRegex(yfinance.YFinanceGradesFetchError, "requires the matching Pass2 budget approval"):
            yfinance._load_ready_preflight(self.paths["summary"])

    def test_manual_checkpoint_restore_rehydrates_the_same_approval_binding(self):
        from runners import us_short_weekly_capstone as capstone

        preview = self._preview()
        approval = self._approval(preview)
        manual = replace(
            approval,
            authorization_mode="manual",
            authorization_ref="manual:unit",
        )
        final = self.runner.finalize_preflight_from_existing_derivation(
            preflight_summary_path=self.paths["summary"], approval_binding=manual.binding_summary()
        )
        ctx = SimpleNamespace(
            decision_date=DECISION_DATE,
            price_basis_date=PRICE_BASIS_DATE,
            candidate_path=self.paths["candidate"],
            authorized_momentum_top_k=200,
            authorized_pass2_call_budget=1001,
        )
        restored = capstone._restore_pass2_budget_approval(ctx, final)
        self.assertEqual(restored.binding_summary(), manual.binding_summary())

        auto = replace(manual, authorization_mode="one_click_test")
        auto_final = dict(final)
        auto_final["execution_gate"] = dict(final["execution_gate"])
        auto_final["execution_gate"]["approval_binding"] = auto.binding_summary()
        with self.assertRaisesRegex(capstone.WeeklyCapstoneError, "manually authorized"):
            capstone._restore_pass2_budget_approval(ctx, auto_final)

    def test_default_pipeline_resume_reaches_yfinance_and_pass2_with_same_manual_approval(self):
        from runners import us_short_weekly_capstone as capstone
        from runners import us_short_weekly_capstone_stages as stage_adapters
        from engine import us_short_capstone_checkpoint as checkpoint_store
        from tests.test_us_short_account_state_from_manual_tables import _build

        private_root = Path(tempfile.mkdtemp(prefix="pass2_resume_priv_"))
        state_dir = Path(tempfile.mkdtemp(prefix="pass2_resume_state_"))
        self.addCleanup(shutil.rmtree, private_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, state_dir, ignore_errors=True)
        account_state, _ = _build(positions=[], as_of="20260709")
        account_path = private_root.parent / f"pass2_resume_account_{os.getpid()}.json"
        account_path.write_text(json.dumps(account_state), encoding="utf-8")
        self.addCleanup(account_path.unlink, missing_ok=True)

        ctx = capstone.resolve_capstone_context(
            now_et=datetime(2026, 7, 9, 8, 0, 0),
            private_root=private_root,
            batch4_template_path=ROOT / "schemas" / "examples" / "us_short_weekend_batch4_context_packet.empty.example.json",
            account_state_path=account_path,
            authorized_momentum_top_k=200,
            authorized_pass2_call_budget=1001,
            confirm_user_authorization=True,
            state_dir=state_dir,
            sample_root=state_dir,
        )
        ctx.candidate_path.parent.mkdir(parents=True, exist_ok=True)
        ctx.candidate_path.write_text("{}\n", encoding="utf-8")
        candidate_sha = capstone._sha256_file(ctx.candidate_path)
        manual = capstone.Pass2BudgetApproval(
            decision_date=ctx.decision_date,
            candidate_price_basis_date=ctx.price_basis_date,
            candidate_artifact_sha256=candidate_sha,
            momentum_top_k=200,
            target_count=200,
            exact_pass2_calls=1001,
            authorization_mode="manual",
            authorization_ref="manual:resume-unit",
            generated_at="2026-07-09T08:00:00+00:00",
        )
        finalized = {
            "scope": {"status": "ready_for_reviewed_live_execution"},
            "generated_at": manual.generated_at,
            "decision_clock": {
                "expected_decision_date": ctx.decision_date,
                "candidate_price_basis_date": ctx.price_basis_date,
            },
            "candidate_universe": {
                "candidate_artifact_sha256": candidate_sha,
                "candidate_artifact_path": str(ctx.candidate_path),
            },
            "pass2_target_universe": {"momentum_top_k": 200, "target_count": 200},
            "endpoint_call_forecast": {"total_calls_for_pass2_target_cut": 1001},
            "execution_gate": {
                "ready_to_run_full_candidate_live_packet": True,
                "block_reasons": [],
                "authorized_momentum_top_k": 200,
                "authorized_total_call_budget": 1001,
                "approval_binding": manual.binding_summary(),
            },
        }
        ctx.preflight_summary_path.parent.mkdir(parents=True, exist_ok=True)
        ctx.preflight_summary_path.write_text(json.dumps(finalized), encoding="utf-8")

        def preflight_must_be_reused(_ctx):
            raise AssertionError("finalized preflight should be restored from checkpoint")

        def adapter_run(name, outputs):
            def run(adapter_ctx):
                self.assertEqual(adapter_ctx.budget_approval, manual)
                for output in outputs(adapter_ctx):
                    Path(output).parent.mkdir(parents=True, exist_ok=True)
                    Path(output).write_text("{}\n", encoding="utf-8")
                return {"stage": name, "approval_fingerprint": adapter_ctx.budget_approval.fingerprint}
            return run

        def bridge_run(bridge_ctx):
            outputs = [
                (bridge_ctx.official_output_root or bridge_ctx.private_root) / "weekly_private" / bridge_ctx.decision_date / "weekly_report.md",
                (bridge_ctx.official_output_root or bridge_ctx.private_root) / "weekly_private" / bridge_ctx.decision_date / "action_table.csv",
                (bridge_ctx.official_output_root or bridge_ctx.private_root) / "runs_private" / bridge_ctx.decision_date / "machine_record.json",
            ]
            for output in outputs:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("{}\n", encoding="utf-8")
            return {
                "batch4_run": {
                    "emitted": True,
                    "output_paths": {
                        "weekly_report_path": str(outputs[0]),
                        "action_table_path": str(outputs[1]),
                        "machine_record_path": str(outputs[2]),
                    },
                }
            }

        pipeline = [
            capstone.Stage(
                "pass2_preflight", False, lambda _c: [], lambda c: [c.preflight_summary_path],
                preflight_must_be_reused, reuse_policy="frozen_inputs",
            ),
            capstone.Stage(
                "yfinance_grades_fetch", True, lambda c: [c.preflight_summary_path],
                lambda c: [c.yfinance_grade_source_package_path, c.yfinance_grade_actions_path],
                adapter_run("yfinance_grades_fetch", lambda c: [c.yfinance_grade_source_package_path, c.yfinance_grade_actions_path]),
            ),
            capstone.Stage(
                "pass2_fetch", True, lambda c: [c.preflight_summary_path, c.yfinance_grade_actions_path],
                lambda c: [c.source_packet_path, c.context_components_path],
                adapter_run("pass2_fetch", lambda c: [c.source_packet_path, c.context_components_path]),
            ),
            capstone.Stage(
                "weekly_bridge", False, lambda c: [c.source_packet_path],
                lambda c: [
                    (c.official_output_root or c.private_root) / "weekly_private" / c.decision_date / "weekly_report.md",
                    (c.official_output_root or c.private_root) / "weekly_private" / c.decision_date / "action_table.csv",
                    (c.official_output_root or c.private_root) / "runs_private" / c.decision_date / "machine_record.json",
                ],
                bridge_run,
            ),
        ]
        checkpoint_path, manifest = checkpoint_store.create_manifest(
            private_root=private_root,
            decision_date=ctx.decision_date,
            price_basis_date=ctx.price_basis_date,
            generated_at=ctx.generated_at,
            run_contract=capstone._checkpoint_run_contract(ctx),
            stages=pipeline,
        )
        manifest = checkpoint_store.record_stage(
            manifest_path=checkpoint_path,
            manifest=manifest,
            stage=pipeline[0],
            execution_mode="executed",
            generated_at=manual.generated_at,
            observed_at=manual.generated_at,
            input_paths=[],
            input_logical_paths=[],
            output_paths=[ctx.preflight_summary_path],
            output_logical_paths=[str(ctx.preflight_summary_path.resolve())],
            result=finalized,
        )
        self.assertEqual(manifest["stages"][0]["name"], "pass2_preflight")

        with mock.patch.object(capstone, "default_pipeline", return_value=pipeline), \
             mock.patch.object(capstone, "_provider_execution_receipt", return_value={"test": "receipt"}):
            summary = capstone.run_weekly_capstone(
                now_et=datetime(2026, 7, 9, 8, 0, 0),
                private_root=private_root,
                batch4_template_path=ctx.batch4_template_path,
                account_state_path=account_path,
                authorized_momentum_top_k=200,
                authorized_pass2_call_budget=1001,
                dry_run=False,
                confirm_user_authorization=True,
                state_dir=state_dir,
                sample_root=state_dir,
                resume_from=checkpoint_path,
            )
        self.assertEqual([item["name"] for item in summary["stages"]], [stage.name for stage in pipeline])
        self.assertEqual(summary["stages"][0]["execution_mode"], "reused")
        self.assertEqual(summary["stages"][1]["result"]["approval_fingerprint"], manual.fingerprint)
        self.assertEqual(summary["stages"][2]["result"]["approval_fingerprint"], manual.fingerprint)

    def test_fake_approval_object_is_rejected_by_stage_and_provider_boundaries(self):
        from dataclasses import replace
        from runners import us_short_batch5_full_candidate_live_source_packet as live
        from runners import us_short_weekly_capstone_stages as stages
        from runners import us_short_yfinance_grades_fetch as yfinance

        preview = self._preview()
        approval = self._approval(preview)
        self.runner.finalize_preflight_from_existing_derivation(
            preflight_summary_path=self.paths["summary"], approval_binding=approval.binding_summary()
        )
        fake = SimpleNamespace(
            exact_pass2_calls=approval.exact_pass2_calls,
            momentum_top_k=approval.momentum_top_k,
            binding_summary=approval.binding_summary,
        )
        ctx = SimpleNamespace(
            budget_approval=fake,
            authorized_pass2_call_budget=approval.exact_pass2_calls,
            authorized_momentum_top_k=approval.momentum_top_k,
        )
        with self.assertRaises(PermissionError):
            stages._require_budget_approval(ctx)
        with self.assertRaisesRegex(live.FullCandidateLiveSourcePacketError, "finalized Pass2 budget approval"):
            live._approval_binding(fake)
        with self.assertRaisesRegex(yfinance.YFinanceGradesFetchError, "finalized Pass2 budget approval"):
            yfinance._approval_binding(fake)

    def test_capstone_approval_minting_binds_current_candidate_bytes(self):
        from runners import us_short_weekly_capstone as capstone

        preview = self._preview()
        ctx = SimpleNamespace(
            decision_date=DECISION_DATE,
            price_basis_date=PRICE_BASIS_DATE,
            candidate_path=self.paths["candidate"],
            authorized_momentum_top_k=200,
            authorized_pass2_call_budget=None,
            generated_at=GENERATED_AT,
        )
        approval = capstone._build_pass2_budget_approval(
            ctx, preview, authorization_mode="one_click_test")
        self.assertEqual(approval.target_count, 200)
        self.assertEqual(approval.exact_pass2_calls, 1001)
        self.assertNotIn("X000", approval.binding_summary()["authorization_ref"])

    def test_pass2_binding_mismatch_rejects_before_provider_client(self):
        from runners import us_short_batch5_full_candidate_live_source_packet as live

        preview = self._preview()
        approval = self._approval(preview)
        final = self.runner.finalize_preflight_from_existing_derivation(
            preflight_summary_path=self.paths["summary"],
            approval_binding=approval.binding_summary(),
        )
        self.assertTrue(final["execution_gate"]["ready_to_run_full_candidate_live_packet"])
        forged = replace(approval, exact_pass2_calls=1000)
        client = mock.Mock()
        with self.assertRaisesRegex(live.FullCandidateLiveSourcePacketError, "approval binding"):
            live.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["summary"],
                expected_total_call_budget=1001,
                budget_approval=forged,
                client=client,
                confirm_user_authorization=True,
                generated_at=GENERATED_AT,
                observed_at=GENERATED_AT,
            )
        client.assert_not_called()

    def test_current_candidate_mutation_rejects_before_finalization(self):
        preview = self._preview()
        approval = self._approval(preview)
        self.paths["candidate"].write_text(
            self.paths["candidate"].read_text(encoding="utf-8") + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(self.runner.FullCandidatePass2PreflightError, "current candidate artifact fingerprint"):
            self.runner.finalize_preflight_from_existing_derivation(
                preflight_summary_path=self.paths["summary"],
                approval_binding=approval.binding_summary(),
            )

    def test_yfinance_binding_mismatch_rejects_before_provider_client(self):
        from runners import us_short_yfinance_grades_fetch as yfinance

        preview = self._preview()
        approval = self._approval(preview)
        self.runner.finalize_preflight_from_existing_derivation(
            preflight_summary_path=self.paths["summary"],
            approval_binding=approval.binding_summary(),
        )
        forged = replace(approval, exact_pass2_calls=1000)
        client = mock.Mock()
        with self.assertRaisesRegex(yfinance.YFinanceGradesFetchError, "approval binding"):
            yfinance.run_yfinance_grades_fetch(
                preflight_summary_path=self.paths["summary"],
                budget_approval=forged,
                client=client,
                confirm_user_authorization=True,
                generated_at=GENERATED_AT,
                observed_at=GENERATED_AT,
            )
        client.assert_not_called()


class Problem7CatalystRecallCanonicalizerTest(unittest.TestCase):
    def test_canonicalizer_accepts_tuple_sorts_and_rejects_duplicates_or_bad_shapes(self) -> None:
        self.assertEqual(
            pass2_preflight.canonicalize_catalyst_recall_tickers(("msft", "AAPL")),
            ("AAPL", "MSFT"),
        )
        for value in (("AAPL", "aapl"), ["bad ticker!"], "AAPL", {"AAPL"}):
            with self.subTest(value=value), self.assertRaises(pass2_preflight.FullCandidatePass2PreflightError):
                pass2_preflight.canonicalize_catalyst_recall_tickers(value)


if __name__ == "__main__":
    unittest.main()
