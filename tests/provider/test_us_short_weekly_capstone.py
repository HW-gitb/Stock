from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.us_short_weekly_capstone import (  # noqa: E402
    Stage,
    WeeklyCapstoneError,
    run_weekly_capstone,
)

_STAGE_NAMES = [
    "universe_fetch", "momentum_fetch", "overextension_producer", "momentum_producer", "sic_fetch", "theme_producer",
    "projection_inputs", "pass2_preflight", "yfinance_grades_fetch", "pass2_fetch", "forward_policy_shadow", "vix_regime", "weekly_bridge",
]
_RECEIPT_STAGE_NAMES = tuple(
    name for name in _STAGE_NAMES if name not in {"forward_policy_shadow", "weekly_bridge"}
)


def _research_receipt(*, decision_date="20260709", source_path=None, generated_at="2026-07-09T08:00:00-04:00",
                      source_manifest=None, provider_summaries=None,
                      provider_health_facts=(("fmp", "ok"), ("sec_edgar", "ok")), stage_executions=None):
    from engine.us_short_run_origin import _issue_capstone_research_live_receipt
    source = Path(source_path or (ROOT / "state" / "us_short" / "receipt_test_source.json")).resolve()
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else "1" * 64
    evidence_digest = "2" * 64
    source_manifest = source_manifest or (("test_source", str(source), source_digest),)
    provider_stages = ("universe_fetch", "momentum_fetch", "sic_fetch", "pass2_fetch", "vix_regime")
    summaries = {stage: {"stage": stage} for stage in provider_stages}
    summaries.update(provider_summaries or {})
    provider_summaries = summaries
    provider_summary_digests = tuple(
        (stage, hashlib.sha256(json.dumps(provider_summaries[stage], ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode("utf-8")).hexdigest())
        for stage in provider_stages
    )
    run_id = hashlib.sha256(
        f"{decision_date}|{generated_at}|{source}|{source_digest}|{evidence_digest}".encode("utf-8")
    ).hexdigest()
    return _issue_capstone_research_live_receipt(
        run_id=run_id,
        decision_date=decision_date,
        generated_at=generated_at,
        completed_stages=_RECEIPT_STAGE_NAMES,
        source_packet_path=source,
        source_packet_sha256=source_digest,
        source_artifact_manifest=source_manifest,
        provider_call_counts=(("universe_fetch", 1), ("momentum_fetch", 1), ("sic_fetch", 1),
                              ("pass2_fetch", 1)),
        provider_summary_digests=provider_summary_digests,
        provider_health_facts=provider_health_facts,
        provider_evidence_sha256=evidence_digest,
        stage_executions=stage_executions,
    )


class CapstoneDryRunTest(unittest.TestCase):
    def _run(self, now_et, **kw):
        return run_weekly_capstone(
            now_et=now_et,
            private_root=Path(tempfile.gettempdir()) / "cap_priv",
            batch4_template_path=Path("template.json"),
            account_state_path=Path("account.json"),
            **kw,
        )

    def test_dry_run_resolves_canonical_and_plans_all_stages(self):
        plan = self._run(datetime(2026, 7, 9, 8, 0, 0), dry_run=True)   # Thu 07-09 08:00 ET = pre-open
        self.assertEqual(plan["mode"], "dry_run")
        self.assertEqual(plan["decision_date"], "20260709")
        self.assertEqual(plan["price_basis_date"], "20260708")   # latest settled session
        self.assertEqual([s["name"] for s in plan["stages"]], _STAGE_NAMES)
        self.assertEqual(plan["gated_stages_need_authorization"],
                         ["universe_fetch", "momentum_fetch", "sic_fetch", "yfinance_grades_fetch", "pass2_fetch",
                          "vix_regime"])

    def test_cli_default_private_root_lands_in_gitignored_state_dir(self):
        """--private-root omitted on the CLI defaults to the gitignored state/us_short tree, so the weekly report /
        action table / machine record land on a provably-private path with no explicit flag (privacy contract)."""
        import io
        from contextlib import redirect_stdout
        from runners import us_short_weekly_capstone as cap
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cap.main([
                "--now-et", "2026-07-09T08:00:00",
                "--batch4-template-path", "template.json",
                "--account-state-path", "account.json",
            ])
        self.assertEqual(rc, 0)
        plan = json.loads(buf.getvalue())
        bridge = next(s for s in plan["stages"] if s["name"] == "weekly_bridge")
        self.assertEqual(bridge["outputs"], [
            "state/us_short/weekly_private/20260709/weekly_report.md",
            "state/us_short/weekly_private/20260709/action_table.csv",
            "state/us_short/runs_private/20260709/machine_record.json",
        ])

    def test_intraday_now_et_fails_closed(self):
        # 07-09 11:00 ET is inside the RTH session [09:30, 16:00) -> §2.1 dead zone -> no canonical, no run.
        with self.assertRaises(WeeklyCapstoneError):
            self._run(datetime(2026, 7, 9, 11, 0, 0), dry_run=True)

    def test_live_run_requires_authorization(self):
        with self.assertRaises(WeeklyCapstoneError):
            self._run(datetime(2026, 7, 9, 8, 0, 0), dry_run=False, confirm_user_authorization=False)

    def test_live_run_without_budget_explains_the_budget_preview_then_exact_rerun(self):
        with self.assertRaisesRegex(WeeklyCapstoneError, "prepare-pass2-budget"):
            self._run(
                datetime(2026, 7, 9, 8, 0, 0),
                dry_run=False,
                confirm_user_authorization=True,
            )

    def test_retry_without_physical_cap_fails_before_any_pipeline_stage(self):
        entered: list[str] = []
        stage = Stage(
            "must_not_run",
            False,
            lambda _ctx: [],
            lambda _ctx: [],
            lambda _ctx: entered.append("stage") or {},
        )
        with self.assertRaisesRegex(WeeklyCapstoneError, "max_total_http_attempts"):
            self._run(
                datetime(2026, 7, 9, 8, 0, 0),
                dry_run=False,
                confirm_user_authorization=True,
                max_retries_per_call=1,
                stages=[stage],
            )
        self.assertEqual(entered, [])

    def test_tz_aware_now_et_rejected(self):
        from datetime import timezone
        with self.assertRaises(WeeklyCapstoneError):
            self._run(datetime(2026, 7, 9, 8, 0, 0, tzinfo=timezone.utc), dry_run=True)

    def test_input_colocated_under_archived_output_dir_is_rejected(self):
        # C3 footgun guard: an operator input inside the per-decision output dir a live run archives must be rejected
        # up front (dry-run too), before any provider fetch — else it is moved to _superseded/ mid-run and the bridge
        # fails only after a full fetch. decision_date for 2026-07-09 08:00 ET = 20260709.
        priv = Path(tempfile.gettempdir()) / "cap_priv"
        with self.assertRaisesRegex(WeeklyCapstoneError, "weekly_private/20260709"):
            run_weekly_capstone(
                now_et=datetime(2026, 7, 9, 8, 0, 0), private_root=priv,
                batch4_template_path=Path("template.json"),
                account_state_path=priv / "weekly_private" / "20260709" / "account.json",
                dry_run=True,
            )
        with self.assertRaisesRegex(WeeklyCapstoneError, "runs_private/20260709"):
            run_weekly_capstone(
                now_et=datetime(2026, 7, 9, 8, 0, 0), private_root=priv,
                batch4_template_path=priv / "runs_private" / "20260709" / "template.json",
                account_state_path=Path("account.json"),
                dry_run=True,
            )

    def test_input_under_run_inputs_sibling_is_accepted(self):
        # positive control: inputs under weekly_private/_run_inputs/<date>/ (NOT the archived <date> dir) pass — the
        # documented relocation. Ensures the guard is not over-broad.
        priv = Path(tempfile.gettempdir()) / "cap_priv"
        plan = run_weekly_capstone(
            now_et=datetime(2026, 7, 9, 8, 0, 0), private_root=priv,
            batch4_template_path=priv / "weekly_private" / "_run_inputs" / "20260709" / "template.json",
            account_state_path=priv / "weekly_private" / "_run_inputs" / "20260709" / "account.json",
            dry_run=True,
        )
        self.assertEqual(plan["decision_date"], "20260709")

    def test_dst_transition_now_et_fails_closed(self):
        # F6: a DST-transition wall-clock is nonexistent (spring-forward GAP) or ambiguous (fall-back FOLD) — the
        # tz-aware conversion must fail closed rather than silently pick one UTC offset; a normal pre-open time passes.
        from runners.us_short_weekly_capstone import _tz_aware_et_or_fail
        with self.assertRaises(WeeklyCapstoneError):
            _tz_aware_et_or_fail(datetime(2026, 3, 8, 2, 30, 0))     # spring-forward gap (02:00->03:00)
        with self.assertRaises(WeeklyCapstoneError):
            _tz_aware_et_or_fail(datetime(2026, 11, 1, 1, 30, 0))    # fall-back fold (02:00->01:00)
        aware = _tz_aware_et_or_fail(datetime(2026, 7, 9, 8, 0, 0))  # normal pre-open EDT
        self.assertEqual(aware.utcoffset().total_seconds(), -4 * 3600)

    def test_observed_at_is_tz_aware(self):
        # regression: the first real run failed because a NAIVE observed_at was rejected by the status source
        # (and the Cut5 engines) which require a tz-aware PIT clock. resolve_capstone_context must localize the
        # naive ET now_et to a tz-aware ET instant.
        from runners.us_short_weekly_capstone import resolve_capstone_context
        ctx = resolve_capstone_context(
            now_et=datetime(2026, 7, 8, 21, 16, 1),
            private_root=Path(tempfile.gettempdir()) / "cap_priv",
            batch4_template_path=Path("t.json"), account_state_path=Path("a.json"))
        parsed = datetime.fromisoformat(ctx.observed_at)
        self.assertIsNotNone(parsed.tzinfo, "observed_at must be tz-aware (status source rejects a naive clock)")
        self.assertEqual(ctx.generated_at, ctx.observed_at)


class CapstoneFakeChainTest(unittest.TestCase):
    """Prove the orchestration (ordering, per-stage output validation, fail-fast, auth gating) with INJECTED fake
    stages that write canned outputs — no real runner, no network. state_dir is a tempdir so nothing touches the repo."""

    def setUp(self):
        self.state_dir = Path(tempfile.mkdtemp(prefix="cap_state_"))
        self.private_root = Path(tempfile.mkdtemp(prefix="cap_priv_"))

    def tearDown(self):
        shutil.rmtree(self.state_dir, ignore_errors=True)
        shutil.rmtree(self.private_root, ignore_errors=True)

    def _fake_stages(self, order_sink, *, break_stage=None, skip_output_stage=None, bridge_batch4=None,
                     missing_input_stage=None, present_input_stage=None, preflight_result=None):
        def outs_for(name):
            return {
                "universe_fetch": lambda c: [c.candidate_path],
                "momentum_fetch": lambda c: [c.series_packet_path, c.ohlcv_series_packet_path],
                "overextension_producer": lambda c: [c.overextension_projection_path],
                "momentum_producer": lambda c: [c.momentum_projection_path],
                "sic_fetch": lambda c: [c.classification_packet_path],
                "theme_producer": lambda c: [c.theme_projection_path],
                "projection_inputs": lambda c: [c.merged_momentum_path, c.merged_theme_path],
                "pass2_preflight": lambda c: [c.preflight_summary_path],
                "yfinance_grades_fetch": lambda c: [c.yfinance_grade_source_package_path, c.yfinance_grade_actions_path],
                "pass2_fetch": lambda c: [c.source_packet_path, c.context_components_path],
                "forward_policy_shadow": lambda c: [c.forward_shadow_selection_private_path, c.forward_policy_summary_path],
                "vix_regime": lambda c: [c.vix_regime_summary_path],
                "weekly_bridge": lambda c: [
                    (c.official_output_root or c.private_root) / "weekly_private" / c.decision_date / "weekly_report.md",
                    (c.official_output_root or c.private_root) / "weekly_private" / c.decision_date / "action_table.csv",
                    (c.official_output_root or c.private_root) / "runs_private" / c.decision_date / "machine_record.json",
                ],
            }[name]

        stages = []
        for name in _STAGE_NAMES:
            outs = outs_for(name)
            gated = name in ("universe_fetch", "momentum_fetch", "sic_fetch", "yfinance_grades_fetch", "pass2_fetch",
                             "vix_regime")

            def make_run(nm, outfn):
                def run(ctx):
                    order_sink.append(nm)
                    if nm == break_stage:
                        raise ValueError("boom in " + nm)
                    if nm != skip_output_stage:
                        for p in outfn(ctx):
                            Path(p).parent.mkdir(parents=True, exist_ok=True)
                            Path(p).write_text("{}", encoding="utf-8")
                    if nm == "weekly_bridge":
                        if bridge_batch4 is not None:
                            return {"batch4_run": bridge_batch4}
                        outputs = outfn(ctx)
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
                    if nm == "pass2_preflight" and preflight_result is not None:
                        return preflight_result
                    return {"stage": nm}
                return run

            if name == missing_input_stage:
                ins = lambda c: [Path(c.private_root) / "_run_inputs" / "absent_declared_input.json"]
            elif name == present_input_stage:
                ins = lambda c: [c.candidate_path]   # produced by universe_fetch (stage 0) → present at this turn
            else:
                ins = lambda c: []
            stages.append(Stage(
                name, gated, ins, outs, make_run(name, outs),
                best_effort=(name == "forward_policy_shadow"),
            ))
        return stages

    def _run(self, order_sink, **kw):
        account_state_path = kw.pop("account_state_path", Path("account.json"))
        return run_weekly_capstone(
            now_et=datetime(2026, 7, 9, 8, 0, 0),
            private_root=self.private_root,
            batch4_template_path=Path("template.json"),
            account_state_path=account_state_path,
            dry_run=False,
            confirm_user_authorization=True,
            state_dir=self.state_dir,
            sample_root=self.state_dir,   # keep the preflight provider_samples sidecar inside the tempdir (isolation)
            **kw,
        )

    def test_full_chain_runs_in_order_and_emits(self):
        order: list[str] = []
        summary = self._run(order, stages=self._fake_stages(order))
        self.assertEqual(order, _STAGE_NAMES)                 # every stage ran, in dependency order
        self.assertEqual(summary["mode"], "live")
        self.assertEqual(summary["execution_mode"], "injected_pipeline")
        self.assertEqual(summary["report_mode"], "offline_test")
        self.assertEqual(summary["operational_use"], "not_authorized")
        self.assertEqual(summary["decision_date"], "20260709")
        self.assertTrue(summary["emitted_report"].endswith("weekly_report.md"))
        self.assertNotIn("shadow_capture_failed", summary)

    def test_budget_preview_uses_default_prefix_only_and_never_authorizes_pass2(self):
        # P2 end-to-end control: the one-click preview uses the real default-pipeline shape, stops immediately after
        # preflight, emits the forecast, and does not mint a checkpoint/output transaction or run later stages.
        from tests.test_us_short_account_state_from_manual_tables import _build

        state, _ = _build(positions=[], as_of="20260709")
        account_path = self.private_root / "account.json"
        account_path.write_text(json.dumps(state), encoding="utf-8")
        order: list[str] = []
        preflight_result = {
            "scope": {"status": "blocked_execution_constraints"},
            "endpoint_call_forecast": {"total_calls_for_pass2_target_cut": 11},
            "pass2_target_universe": {"target_count": 2},
            "execution_gate": {
                "ready_to_run_full_candidate_live_packet": False,
                "block_reasons": ["pass2_call_budget_not_yet_authorized"],
            },
        }
        fake_pipeline = self._fake_stages(order, preflight_result=preflight_result)
        with mock.patch("runners.us_short_weekly_capstone.default_pipeline", return_value=fake_pipeline):
            summary = self._run(
                order,
                account_state_path=account_path,
                prepare_pass2_budget=True,
                authorized_momentum_top_k=2,
            )

        self.assertEqual(order, _STAGE_NAMES[:8])
        self.assertEqual(summary["mode"], "pass2_budget_preview")
        self.assertEqual(summary["pass2_call_budget"], 11)
        self.assertEqual(summary["pass2_target_count"], 2)
        self.assertEqual(summary["operational_use"], "not_authorized")
        self.assertIn("--pass2-call-budget 11", summary["next_required"])
        self.assertFalse((self.private_root / "weekly_private" / "20260709").exists())

    def test_shadow_failure_is_loud_nonblocking_and_bridge_emits(self):
        order: list[str] = []
        with mock.patch("builtins.print") as printed:
            summary = self._run(
                order,
                stages=self._fake_stages(order, break_stage="forward_policy_shadow"),
            )
        self.assertEqual(order, _STAGE_NAMES)
        self.assertTrue(summary["emitted"])
        self.assertEqual(summary["shadow_capture_failed"]["stage"], "forward_policy_shadow")
        self.assertEqual(summary["shadow_capture_failed"]["error_type"], "ValueError")
        self.assertIn("boom in forward_policy_shadow", summary["shadow_capture_failed"]["error"])
        shadow_result = next(item for item in summary["stages"] if item["name"] == "forward_policy_shadow")
        self.assertTrue(shadow_result["best_effort"])
        self.assertEqual(shadow_result["result"]["shadow_capture_failed"], summary["shadow_capture_failed"])
        self.assertTrue(any(
            "US-SHORT SHADOW CAPTURE FAILED" in str(call.args[0])
            for call in printed.call_args_list
        ))

    def test_shadow_unreadable_input_is_best_effort_and_bridge_emits(self):
        # symmetric to the shadow RUN-failure case: an unreadable shadow INPUT (e.g. a pass2_fetch partial write that
        # leaves data_context absent while source_packet is present) must ALSO route through the best-effort
        # shadow-capture-failure path — loud marker + continue — never aborting the real weekly report.
        order: list[str] = []
        with mock.patch("builtins.print") as printed:
            summary = self._run(
                order,
                stages=self._fake_stages(order, missing_input_stage="forward_policy_shadow"),
            )
        self.assertTrue(summary["emitted"])
        self.assertNotIn("forward_policy_shadow", order)          # skipped at the input gate, before its run body
        self.assertIn("weekly_bridge", order)                     # the real report still ran
        self.assertEqual(summary["shadow_capture_failed"]["stage"], "forward_policy_shadow")
        self.assertEqual(summary["shadow_capture_failed"]["error_type"], "WeeklyCapstoneError")
        self.assertIn("input", summary["shadow_capture_failed"]["error"].lower())
        shadow_result = next(item for item in summary["stages"] if item["name"] == "forward_policy_shadow")
        self.assertTrue(shadow_result["best_effort"])
        self.assertTrue(any(
            "US-SHORT SHADOW CAPTURE FAILED" in str(call.args[0])
            for call in printed.call_args_list
        ))

    def test_only_shadow_stage_may_be_best_effort(self):
        order: list[str] = []
        stages = self._fake_stages(order)
        next(stage for stage in stages if stage.name == "vix_regime").best_effort = True
        with self.assertRaisesRegex(WeeklyCapstoneError, "only forward_policy_shadow"):
            self._run(order, stages=stages)
        self.assertEqual(order, [])

    def test_research_receipt_does_not_require_shadow_stage(self):
        receipt = _research_receipt()
        self.assertNotIn("forward_policy_shadow", receipt.completed_stages)

    def test_receipt_v2_preserves_reused_stage_times_without_rewriting_them(self):
        stage_executions = tuple(
            (
                name,
                "reused" if name == "momentum_fetch" else "executed",
                "2026-07-08T08:00:00-04:00" if name == "momentum_fetch" else "2026-07-09T08:00:00-04:00",
                "2026-07-08T08:00:00-04:00" if name == "momentum_fetch" else "2026-07-09T08:00:00-04:00",
                hashlib.sha256(name.encode("utf-8")).hexdigest(),
            )
            for name in _RECEIPT_STAGE_NAMES
        )
        receipt = _research_receipt(stage_executions=stage_executions)
        self.assertEqual(receipt.stage_executions, stage_executions)
        self.assertEqual(dict((row[0], row[1]) for row in receipt.stage_executions)["momentum_fetch"], "reused")
        self.assertNotEqual(receipt.stage_executions[1][2], receipt.generated_at)

    def test_stage_missing_output_fails_fast_with_stage_name(self):
        order: list[str] = []
        with self.assertRaises(WeeklyCapstoneError) as cm:
            self._run(order, stages=self._fake_stages(order, skip_output_stage="pass2_fetch"))
        self.assertIn("pass2_fetch", str(cm.exception))
        self.assertNotIn("weekly_bridge", order)             # aborted before the next stage

    def test_stage_missing_input_fails_fast_before_stage_runs(self):
        # symmetric to the missing-output guard: a stage whose declared input is absent this run aborts UP FRONT
        # (with the stage name), before entering the stage body — not a deeper crash. pass2_fetch's declared input
        # here is a path no prior fake stage produced.
        order: list[str] = []
        with self.assertRaises(WeeklyCapstoneError) as cm:
            self._run(order, stages=self._fake_stages(order, missing_input_stage="pass2_fetch"))
        self.assertIn("pass2_fetch", str(cm.exception))
        self.assertIn("input", str(cm.exception).lower())
        self.assertNotIn("pass2_fetch", order)               # aborted BEFORE the stage's run body
        self.assertIn("yfinance_grades_fetch", order)        # earlier (empty-input) stages still ran

    def test_stage_present_declared_input_passes_and_chain_completes(self):
        # positive control: a stage whose declared input WAS produced by an earlier stage passes the pre-stage gate
        # and the full chain still emits — the gate is not over-broad (does not false-fail present inputs).
        order: list[str] = []
        summary = self._run(order, stages=self._fake_stages(order, present_input_stage="momentum_fetch"))
        self.assertEqual(order, _STAGE_NAMES)
        self.assertTrue(summary["emitted_report"].endswith("weekly_report.md"))

    def test_stage_exception_wrapped_with_stage_name(self):
        order: list[str] = []
        with self.assertRaises(WeeklyCapstoneError) as cm:
            self._run(order, stages=self._fake_stages(order, break_stage="momentum_fetch"))
        self.assertIn("momentum_fetch", str(cm.exception))
        self.assertEqual(order, ["universe_fetch", "momentum_fetch"])   # fail-fast, no further stages

    def test_bridge_no_emit_is_honest_success_not_failure(self):
        # design §3.2: a non-clean provider_health (e.g. free-tier FMP-429) → the bridge honestly writes NO
        # weekly_report.md. That must be a clean no-emit result, NOT a "missing output" hard failure.
        order: list[str] = []
        summary = self._run(order, stages=self._fake_stages(
            order, skip_output_stage="weekly_bridge",
            bridge_batch4={"emitted": False, "no_emit_reason": "provider_health_blocked"}))
        self.assertEqual(order, _STAGE_NAMES)                 # ran the whole chain
        self.assertFalse(summary["emitted"])
        self.assertEqual(summary["no_emit_reason"], "provider_health_blocked")

    def test_bridge_emitted_true_but_missing_report_still_fails(self):
        # an emit=True bridge that did NOT actually write the report is a real failure — the no-emit tolerance must
        # not swallow it.
        order: list[str] = []
        with self.assertRaises(WeeklyCapstoneError) as cm:
            self._run(order, stages=self._fake_stages(
                order, skip_output_stage="weekly_bridge", bridge_batch4={"emitted": True}))
        self.assertIn("weekly_bridge", str(cm.exception))

    def test_bridge_missing_explicit_emitted_status_fails_closed(self):
        order: list[str] = []
        stages = self._fake_stages(order)
        bridge = next(stage for stage in stages if stage.name == "weekly_bridge")
        original = bridge.run
        bridge.run = lambda ctx: (original(ctx), {"batch4_run": {}})[1]
        with self.assertRaises(WeeklyCapstoneError) as cm:
            self._run(order, stages=stages)
        self.assertIn("explicitly report", str(cm.exception))
        self.assertFalse((self.private_root / "weekly_private" / "20260709").exists())
        self.assertFalse((self.private_root / "runs_private" / "20260709").exists())

    def test_bridge_commit_manifest_requires_exact_output_keys(self):
        order: list[str] = []
        stages = self._fake_stages(order)
        bridge = next(stage for stage in stages if stage.name == "weekly_bridge")
        original = bridge.run

        def wrong_keys(ctx):
            result = original(ctx)
            values = list(result["batch4_run"]["output_paths"].values())
            result["batch4_run"]["output_paths"] = dict(zip(("report", "action", "machine"), values))
            return result

        bridge.run = wrong_keys
        with self.assertRaises(WeeklyCapstoneError):
            self._run(order, stages=stages)
        self.assertFalse((self.private_root / "weekly_private" / "20260709").exists())
        self.assertFalse((self.private_root / "runs_private" / "20260709").exists())

    # --- C (R-USSHORT-REVIEWQ-CAT1 Required C): a NON-emitting outcome (no-emit / stage exception / missing output)
    #     must not leave a PRIOR same-decision-date report discoverable as THIS week's current advice; history is
    #     preserved under an explicit _superseded identity. ---
    _OFFICIAL_SIBLINGS = {"weekly_report.md", "action_table.csv", "machine_record.json"}

    def _seed_prior_official_outputs(self, decision_date="20260709"):
        """Simulate a PRIOR emitted run's 3 official output siblings under the private root."""
        wk = self.private_root / "weekly_private" / decision_date
        rn = self.private_root / "runs_private" / decision_date
        wk.mkdir(parents=True, exist_ok=True)
        rn.mkdir(parents=True, exist_ok=True)
        (wk / "weekly_report.md").write_text("PRIOR REPORT", encoding="utf-8")
        (wk / "action_table.csv").write_text("prior,row\n", encoding="utf-8")
        (rn / "machine_record.json").write_text("{}", encoding="utf-8")
        return wk, rn

    def _superseded_files(self):
        # C2: superseded history now lives UNDER each already-gitignored surface (weekly_private/runs_private).
        files = set()
        for surface in ("weekly_private", "runs_private"):
            sup = self.private_root / surface / "_superseded"
            if sup.exists():
                files |= {p.name for p in sup.rglob("*") if p.is_file()}
        return files

    def test_no_emit_supersedes_prior_same_date_current_outputs(self):
        wk, rn = self._seed_prior_official_outputs()
        order: list[str] = []
        summary = self._run(order, stages=self._fake_stages(
            order, skip_output_stage="weekly_bridge",
            bridge_batch4={"emitted": False, "no_emit_reason": "provider_health_blocked"}))
        self.assertFalse(summary["emitted"])
        self.assertFalse(wk.exists())                                       # current slot emptied ...
        self.assertFalse(rn.exists())
        self.assertEqual(self._superseded_files(), self._OFFICIAL_SIBLINGS)  # ... history preserved (all 3 siblings)
        self.assertTrue(summary["superseded_prior_outputs"]["moved"])

    def test_stage_exception_supersedes_prior_same_date_current_outputs(self):
        wk, rn = self._seed_prior_official_outputs()
        order: list[str] = []
        with self.assertRaises(WeeklyCapstoneError):
            self._run(order, stages=self._fake_stages(order, break_stage="momentum_fetch"))
        self.assertFalse(wk.exists())
        self.assertFalse(rn.exists())
        self.assertEqual(self._superseded_files(), self._OFFICIAL_SIBLINGS)

    def test_missing_output_failure_supersedes_prior_same_date_current_outputs(self):
        # the third non-emitting outcome (a stage completes but does not produce its declared output) closes the class.
        wk, rn = self._seed_prior_official_outputs()
        order: list[str] = []
        with self.assertRaises(WeeklyCapstoneError):
            self._run(order, stages=self._fake_stages(order, skip_output_stage="pass2_fetch"))
        self.assertFalse(wk.exists())
        self.assertFalse(rn.exists())
        self.assertEqual(self._superseded_files(), self._OFFICIAL_SIBLINGS)

    def test_no_emit_without_prior_outputs_is_noop(self):
        # reverse control: a no-emit with NO prior same-date report supersedes nothing (no crash, no _superseded dir).
        order: list[str] = []
        summary = self._run(order, stages=self._fake_stages(
            order, skip_output_stage="weekly_bridge",
            bridge_batch4={"emitted": False, "no_emit_reason": "provider_health_blocked"}))
        self.assertFalse(summary["emitted"])
        self.assertEqual(summary["superseded_prior_outputs"]["moved"], [])
        self.assertFalse((self.private_root / "_superseded").exists())

    def test_successful_emit_does_not_supersede(self):
        # reverse control: a normal emit must NOT archive to _superseded (only non-emitting outcomes do).
        order: list[str] = []
        summary = self._run(order, stages=self._fake_stages(order))
        self.assertTrue(summary["emitted"])
        self.assertEqual(self._superseded_files(), set())

    def test_injected_pipeline_never_mints_research_live_capability(self):
        # A1: an injected (test) pipeline is NOT a production run (stages is not None), so run_weekly_capstone never
        # injects the capability — the bridge stage's ctx carries research_live_capability=None (research_live refused).
        order: list[str] = []
        stages = self._fake_stages(order)
        bridge = next(s for s in stages if s.name == "weekly_bridge")
        inner, captured = bridge.run, {}
        bridge.run = lambda ctx: (captured.__setitem__("cap", getattr(ctx, "research_live_capability", "MISSING")),
                                  inner(ctx))[1]
        self._run(order, stages=stages)
        self.assertIsNone(captured["cap"])

    def test_emitted_true_but_stale_report_fails_freshness_and_supersedes(self):
        # C1: a prior same-date report exists; a bridge that reports emitted=True but writes NOTHING must NOT be
        # accepted (the stale file satisfies Path.exists but is not FRESH this run) — it fails + supersedes the prior.
        wk, rn = self._seed_prior_official_outputs()
        order: list[str] = []
        with self.assertRaises(WeeklyCapstoneError):
            self._run(order, stages=self._fake_stages(
                order, skip_output_stage="weekly_bridge", bridge_batch4={"emitted": True}))
        self.assertFalse(wk.exists())
        self.assertEqual(self._superseded_files(), self._OFFICIAL_SIBLINGS)

    def test_fresh_report_without_action_and_machine_cannot_commit(self):
        # C1: the bridge commit contract is all three siblings. Producing only a fresh report in staging cannot publish
        # while action_table.csv / machine_record.json are absent.
        order: list[str] = []
        stages = self._fake_stages(order, skip_output_stage="weekly_bridge")
        bridge = next(stage for stage in stages if stage.name == "weekly_bridge")

        def report_only(ctx):
            order.append("weekly_bridge")
            outputs = bridge.outputs(ctx)
            outputs[0].parent.mkdir(parents=True, exist_ok=True)
            outputs[0].write_text("fresh report", encoding="utf-8")
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

        bridge.run = report_only
        with self.assertRaises(WeeklyCapstoneError):
            self._run(order, stages=stages)
        self.assertFalse((self.private_root / "weekly_private" / "20260709").exists())
        self.assertFalse((self.private_root / "runs_private" / "20260709").exists())

    def test_superseded_destination_is_gitignored(self):
        # C2: the supersede destination lives UNDER the already-gitignored weekly_private/runs_private trees, so real
        # ticker/holding history is never moved to a tracked-eligible path — verified with the ACTUAL repo ignore rules.
        import subprocess
        from runners.us_short_weekly_capstone import ROOT
        for surface in ("weekly_private", "runs_private"):
            p = ROOT / "state" / "us_short" / surface / "_superseded" / "20260709__tag" / "weekly_report.md"
            r = subprocess.run(["git", "check-ignore", "-q", "--", str(p)], cwd=str(ROOT),
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.assertEqual(r.returncode, 0, f"{surface}/_superseded must be gitignored: {p}")

    def test_supersede_applies_private_path_guard(self):
        # C2: the supersede routes source + destination through the fail-closed private-path guard; if it rejects (a
        # non-private path), the cleanup fails closed rather than leaking real history to a tracked-eligible path.
        from engine.us_short_private_paths import PrivatePathError
        from runners import us_short_weekly_capstone as cap
        self._seed_prior_official_outputs()
        order: list[str] = []
        with mock.patch.object(cap, "reject_nonprivate_output_path", side_effect=PrivatePathError("nonprivate")):
            with self.assertRaises(PrivatePathError):
                self._run(order, stages=self._fake_stages(
                    order, skip_output_stage="weekly_bridge",
                    bridge_batch4={"emitted": False, "no_emit_reason": "x"}))

    def test_pre_run_archive_failure_restores_prior_before_any_stage(self):
        # C3: prior outputs are archived BEFORE provider execution. A second-move fault rolls back while the prior run
        # is still legitimately current, and no stage of the new run starts.
        from runners import us_short_weekly_capstone as cap
        wk, rn = self._seed_prior_official_outputs()
        order: list[str] = []
        real_move, calls = cap.shutil.move, {"n": 0}

        def flaky_move(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("boom on the second move")
            return real_move(src, dst)

        with mock.patch.object(cap.shutil, "move", side_effect=flaky_move):
            with self.assertRaises(WeeklyCapstoneError):
                self._run(order, stages=self._fake_stages(
                    order, skip_output_stage="weekly_bridge",
                    bridge_batch4={"emitted": False, "no_emit_reason": "x"}))
        self.assertEqual(order, [])
        # rollback happened before a new run outcome: both prior-current slots are restored and no history is split.
        self.assertTrue((wk / "weekly_report.md").exists())
        self.assertTrue((rn / "machine_record.json").exists())
        self.assertEqual(self._superseded_files(), set())

    def test_pre_run_archive_and_rollback_errors_are_both_preserved(self):
        from runners import us_short_weekly_capstone as cap

        self._seed_prior_official_outputs()
        order: list[str] = []
        real_move, calls = cap.shutil.move, {"n": 0}

        def doubly_flaky_move(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("archive primary failure")
            if calls["n"] == 3:
                raise OSError("archive rollback failure")
            return real_move(src, dst)

        with mock.patch.object(cap.shutil, "move", side_effect=doubly_flaky_move):
            with self.assertRaises(WeeklyCapstoneError) as cm:
                self._run(order, stages=self._fake_stages(order))
        self.assertIsInstance(cm.exception.__cause__, ExceptionGroup)
        self.assertEqual(
            [str(exc) for exc in cm.exception.__cause__.exceptions],
            ["archive primary failure", "archive rollback failure"],
        )
        self.assertEqual(order, [])

    def test_archive_recovery_journal_error_preserves_all_three_failures(self):
        from runners import us_short_weekly_capstone as cap

        self._seed_prior_official_outputs()
        order: list[str] = []
        real_move, calls = cap.shutil.move, {"n": 0}
        original_journal = cap._write_transaction_journal

        def doubly_flaky_move(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("archive primary failure")
            if calls["n"] == 3:
                raise OSError("archive rollback failure")
            return real_move(src, dst)

        def flaky_journal(path, *, tag, phase):
            if phase == "archive_recovery_required":
                raise OSError("archive recovery journal failure")
            return original_journal(path, tag=tag, phase=phase)

        with mock.patch.object(cap.shutil, "move", side_effect=doubly_flaky_move), \
             mock.patch.object(cap, "_write_transaction_journal", side_effect=flaky_journal):
            with self.assertRaises(WeeklyCapstoneError) as cm:
                self._run(order, stages=self._fake_stages(order))
        self.assertIn("journal write also failed", str(cm.exception))
        self.assertEqual(
            [str(exc) for exc in cm.exception.__cause__.exceptions],
            ["archive primary failure", "archive rollback failure", "archive recovery journal failure"],
        )

    def test_publish_second_move_failure_leaves_current_empty(self):
        # C3: official outputs are staged. If publishing the report/action surface fails after the machine move, the
        # machine move is rolled back to staging and the failed run leaves no current output.
        from runners import us_short_weekly_capstone as cap
        order: list[str] = []
        real_move, calls = cap.shutil.move, {"n": 0}

        def flaky_move(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("publish weekly surface failed")
            return real_move(src, dst)

        with mock.patch.object(cap.shutil, "move", side_effect=flaky_move):
            with self.assertRaises(WeeklyCapstoneError):
                self._run(order, stages=self._fake_stages(order))
        self.assertFalse((self.private_root / "weekly_private" / "20260709").exists())
        self.assertFalse((self.private_root / "runs_private" / "20260709").exists())

    def test_published_marker_failure_rolls_back_all_current_outputs(self):
        from runners import us_short_weekly_capstone as cap

        order: list[str] = []
        original = cap._write_transaction_journal

        def fail_published(path, *, tag, phase):
            if phase == "published":
                raise OSError("published marker failed")
            return original(path, tag=tag, phase=phase)

        with mock.patch.object(cap, "_write_transaction_journal", side_effect=fail_published):
            with self.assertRaises(WeeklyCapstoneError):
                self._run(order, stages=self._fake_stages(order))
        self.assertFalse((self.private_root / "weekly_private" / "20260709").exists())
        self.assertFalse((self.private_root / "runs_private" / "20260709").exists())
        self.assertFalse(
            (self.private_root / "weekly_private" / "_transaction_state" / "20260709.json").exists()
        )

    def test_post_commit_cleanup_failure_remains_success_and_recovers(self):
        from runners import us_short_weekly_capstone as cap

        order: list[str] = []
        with mock.patch.object(cap.shutil, "rmtree", side_effect=OSError("cleanup failed")):
            summary = self._run(order, stages=self._fake_stages(order))
        self.assertTrue(summary["emitted"])
        self.assertTrue((self.private_root / "weekly_private" / "20260709" / "weekly_report.md").exists())
        self.assertTrue((self.private_root / "runs_private" / "20260709" / "machine_record.json").exists())
        journal = self.private_root / "weekly_private" / "_transaction_state" / "20260709.json"
        self.assertEqual(json.loads(journal.read_text(encoding="utf-8"))["phase"], "published")
        ctx = cap.resolve_capstone_context(
            now_et=datetime(2026, 7, 9, 8, 0, 0),
            private_root=self.private_root,
            batch4_template_path=Path("template.json"),
            account_state_path=Path("account.json"),
            state_dir=self.state_dir,
            sample_root=self.state_dir,
        )
        lock = cap._acquire_decision_lock(ctx)
        try:
            cap._recover_current_output_transaction(ctx)
        finally:
            cap._release_decision_lock(lock)
        self.assertFalse(journal.exists())
        self.assertTrue((self.private_root / "weekly_private" / "20260709" / "weekly_report.md").exists())

    def test_publish_rollback_failure_is_journaled_and_recoverable(self):
        # C3: do not swallow rollback failure. Keep the journal, then the next startup recovery removes the
        # uncommitted partial current surface.
        from runners import us_short_weekly_capstone as cap
        order: list[str] = []
        real_move, calls = cap.shutil.move, {"n": 0}

        def doubly_flaky_move(src, dst):
            calls["n"] += 1
            if calls["n"] in {2, 3}:
                raise OSError(f"fault {calls['n']}")
            return real_move(src, dst)

        with mock.patch.object(cap.shutil, "move", side_effect=doubly_flaky_move):
            with self.assertRaises(WeeklyCapstoneError) as cm:
                self._run(order, stages=self._fake_stages(order))
        self.assertIn("rollback also failed", str(cm.exception))
        self.assertIsInstance(cm.exception.__cause__, ExceptionGroup)
        self.assertEqual([str(exc) for exc in cm.exception.__cause__.exceptions], ["fault 2", "fault 3"])
        journal = self.private_root / "weekly_private" / "_transaction_state" / "20260709.json"
        self.assertTrue(journal.exists())
        ctx = cap.resolve_capstone_context(
            now_et=datetime(2026, 7, 9, 8, 0, 0), private_root=self.private_root,
            batch4_template_path=Path("template.json"), account_state_path=Path("account.json"),
            confirm_user_authorization=True, state_dir=self.state_dir, sample_root=self.state_dir,
        )
        cap._recover_current_output_transaction(ctx)
        self.assertFalse(journal.exists())
        self.assertFalse((self.private_root / "weekly_private" / "20260709").exists())
        self.assertFalse((self.private_root / "runs_private" / "20260709").exists())

    def test_publish_recovery_journal_error_preserves_all_three_failures(self):
        from runners import us_short_weekly_capstone as cap

        order: list[str] = []
        real_move, calls = cap.shutil.move, {"n": 0}
        original_journal = cap._write_transaction_journal

        def doubly_flaky_move(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("publish primary failure")
            if calls["n"] == 3:
                raise OSError("publish rollback failure")
            return real_move(src, dst)

        def flaky_journal(path, *, tag, phase):
            if phase == "publish_recovery_required":
                raise OSError("publish recovery journal failure")
            return original_journal(path, tag=tag, phase=phase)

        with mock.patch.object(cap.shutil, "move", side_effect=doubly_flaky_move), \
             mock.patch.object(cap, "_write_transaction_journal", side_effect=flaky_journal):
            with self.assertRaises(WeeklyCapstoneError) as cm:
                self._run(order, stages=self._fake_stages(order))
        self.assertIn("journal write also failed", str(cm.exception))
        self.assertEqual(
            [str(exc) for exc in cm.exception.__cause__.exceptions],
            ["publish primary failure", "publish rollback failure", "publish recovery journal failure"],
        )

    def test_same_decision_date_second_transaction_is_locked_out(self):
        from runners import us_short_weekly_capstone as cap

        ctx = cap.resolve_capstone_context(
            now_et=datetime(2026, 7, 9, 8, 0, 0),
            private_root=self.private_root,
            batch4_template_path=Path("template.json"),
            account_state_path=Path("account.json"),
            state_dir=self.state_dir,
            sample_root=self.state_dir,
        )
        other_private_root = Path(tempfile.mkdtemp(prefix="cap_priv_parallel_"))
        self.addCleanup(shutil.rmtree, other_private_root, ignore_errors=True)
        other_ctx = cap.resolve_capstone_context(
            now_et=datetime(2026, 7, 9, 8, 0, 0),
            private_root=other_private_root,
            batch4_template_path=Path("template.json"),
            account_state_path=Path("account.json"),
            state_dir=self.state_dir,
            sample_root=self.state_dir,
        )
        first = cap._begin_current_output_transaction(ctx)
        try:
            with self.assertRaises(WeeklyCapstoneError) as cm:
                cap._begin_current_output_transaction(other_ctx)
            self.assertIn("already owns decision_date", str(cm.exception))
            self.assertTrue(first.journal_path.exists())
        finally:
            cap._abort_current_output_transaction(first)


class CapstoneStageAuthAndSourceBindingTest(unittest.TestCase):
    """R-USSHORT-REVIEWQ-CAT1 Required B (authorization propagation) + Required A (research_live source-binding). The
    gated adapters must CONSUME ctx.confirm_user_authorization and fail closed BEFORE the wrapped runner when it is
    false (never self-assert True); the bridge binds research_live to that per-execution authorization; and the generic
    batch4 / e2e entry points (CLI + function) cannot select research_live for an arbitrary fixture packet."""

    # gated adapters plus preflight that previously hardcoded confirm_user_authorization=True
    _WRAPPED = {
        "run_universe": ("_universe", "run_fetch"),
        "run_momentum_fetch": ("_mom_fetch", "run_fetch"),
        "run_sic_fetch": ("_sic", "run_fetch"),
        "run_yfinance_grades_fetch": ("_yfinance_grades", "run_yfinance_grades_fetch"),
        "run_pass2_fetch": ("_pass2", "run_full_candidate_live_source_packet"),
        "run_vix_regime": ("_vix", "run_fetch"),
        "run_pass2_preflight": ("_preflight", "run_preflight"),
    }

    def _ctx(self, *, authorized):
        from runners.us_short_weekly_capstone import resolve_capstone_context
        tmp = Path(tempfile.mkdtemp(prefix="cap_auth_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return resolve_capstone_context(
            now_et=datetime(2026, 7, 9, 8, 0, 0),
            private_root=tmp / "priv",
            batch4_template_path=tmp / "template.json",
            account_state_path=tmp / "account.json",
            authorized_momentum_top_k=200,
            authorized_pass2_call_budget=16,
            catalyst_recall_tickers=("CAT",),
            confirm_user_authorization=authorized,
            state_dir=tmp / "state",
            sample_root=tmp,
        )

    def test_gated_adapter_refuses_unauthorized_ctx_before_calling_runner(self):
        # Required B: a direct adapter call with an UNAUTHORIZED ctx must raise BEFORE invoking the wrapped provider
        # runner — closed-world over every gated adapter plus the authorization-bound preflight
        # (no silent self-authorization on any).
        from runners import us_short_weekly_capstone_stages as st
        ctx = self._ctx(authorized=False)
        for adapter, (mod_attr, fn) in self._WRAPPED.items():
            with mock.patch.object(getattr(st, mod_attr), fn) as m:
                with self.assertRaises(PermissionError, msg=adapter):
                    getattr(st, adapter)(ctx)
                m.assert_not_called()

    def test_gated_adapter_forwards_ctx_authorization_when_authorized(self):
        # Required B (reverse): with an AUTHORIZED ctx each adapter forwards ctx.confirm_user_authorization (True) to
        # its runner — the value is CONSUMED from the context, not hardcoded.
        from runners import us_short_weekly_capstone_stages as st
        ctx = self._ctx(authorized=True)
        with mock.patch.object(st, "_account_holding_tickers", return_value=["HOLD"]):
            for adapter, (mod_attr, fn) in self._WRAPPED.items():
                with mock.patch.object(getattr(st, mod_attr), fn, return_value={"ok": True}) as m:
                    getattr(st, adapter)(ctx)
                    m.assert_called_once()
                    self.assertIs(m.call_args.kwargs.get("confirm_user_authorization"), True, adapter)
                    if adapter in {"run_pass2_fetch", "run_pass2_preflight"}:
                        self.assertEqual(m.call_args.kwargs["forced_holding_tickers"], ["HOLD"])
                        self.assertEqual(m.call_args.kwargs["catalyst_recall_tickers"], ["CAT"])
                        self.assertEqual(m.call_args.kwargs["momentum_top_k" if adapter == "run_pass2_preflight" else "authorized_momentum_top_k"], 200)
                    if adapter == "run_pass2_fetch":
                        self.assertEqual(m.call_args.kwargs["expected_total_call_budget"], 16)
                    if adapter == "run_pass2_preflight":
                        self.assertEqual(m.call_args.kwargs["authorized_total_call_budget"], 16)

    def test_account_positions_are_the_authoritative_forced_holding_source(self):
        from runners import us_short_weekly_capstone_stages as st
        from tests.test_us_short_account_state_from_manual_tables import _build
        ctx = self._ctx(authorized=True)
        state, _ = _build(
            positions=[
                {"ticker": "MSFT", "shares": "2", "avg_cost_usd": "100", "entry_date": ctx.decision_date},
                {"ticker": "AAPL", "shares": "1", "avg_cost_usd": "90", "entry_date": ctx.decision_date},
            ],
            as_of=ctx.decision_date,
        )
        ctx.account_state_path.write_text(json.dumps(state), encoding="utf-8")
        self.assertEqual(st._account_holding_tickers(ctx), ["AAPL", "MSFT"])

    def test_pass2_adapters_reject_missing_frozen_budget_before_wrapped_runner(self):
        from dataclasses import replace
        from runners import us_short_weekly_capstone_stages as st
        ctx = replace(self._ctx(authorized=True), authorized_pass2_call_budget=None)
        for adapter in (st.run_pass2_preflight, st.run_pass2_fetch):
            with mock.patch.object(
                st._preflight if adapter is st.run_pass2_preflight else st._pass2,
                "run_preflight" if adapter is st.run_pass2_preflight else "run_full_candidate_live_source_packet",
            ) as call:
                with self.assertRaisesRegex(PermissionError, "frozen K"):
                    adapter(ctx)
                call.assert_not_called()

    def test_preflight_allows_budget_preview_but_pass2_fetch_still_requires_exact_budget(self):
        from dataclasses import replace
        from runners import us_short_weekly_capstone_stages as st
        ctx = replace(
            self._ctx(authorized=True),
            authorized_pass2_call_budget=None,
            pass2_budget_preview=True,
        )
        with mock.patch.object(st, "_account_holding_tickers", return_value=[]), \
             mock.patch.object(st._preflight, "run_preflight", return_value={"ok": True}) as preflight:
            self.assertEqual(st.run_pass2_preflight(ctx), {"ok": True})
        self.assertIsNone(preflight.call_args.kwargs["authorized_total_call_budget"])
        with mock.patch.object(st._pass2, "run_full_candidate_live_source_packet") as packet:
            with self.assertRaisesRegex(PermissionError, "frozen K"):
                st.run_pass2_fetch(ctx)
            packet.assert_not_called()

    def test_bridge_forwards_ctx_mixed_source_capability_not_self_mint(self):
        # A1: the bridge NO LONGER self-mints from ctx.confirm_user_authorization — it forwards ctx.research_live_capability
        # VERBATIM (run_weekly_capstone injects it ONLY for a genuine production run). An authorized ctx that lacks the
        # injected capability (the default from resolve_capstone_context) forwards None → run_e2e refuses research_live.
        from dataclasses import replace
        from runners import us_short_weekly_capstone_stages as st
        receipt = _research_receipt()
        for cap in (receipt, None):
            ctx = replace(self._ctx(authorized=True), research_live_capability=cap)
            vix_summary = {"stage": "vix_regime"}
            ctx.vix_regime_summary_path.parent.mkdir(parents=True, exist_ok=True)
            ctx.vix_regime_summary_path.write_text(json.dumps(vix_summary), encoding="utf-8")
            with mock.patch.object(st, "_write_provider_health"), \
                 mock.patch.object(st._bridge, "run_e2e", return_value={"batch4_run": {"emitted": True}}) as m:
                st.run_weekly_bridge(ctx)
                self.assertEqual(m.call_args.kwargs.get("run_mode"), "mixed_source")
                self.assertIs(m.call_args.kwargs.get("_research_live_capability"), cap)
        # authorized BUT capability not injected (the default) → None forwarded (the auth flag alone does not mint it)
        with mock.patch.object(st, "_write_provider_health"), \
             mock.patch.object(st._bridge, "run_e2e", return_value={"batch4_run": {"emitted": True}}) as m:
            st.run_weekly_bridge(self._ctx(authorized=True))
            self.assertIsNone(m.call_args.kwargs.get("_research_live_capability"))

    def test_bridge_binds_and_injects_vix_regime_without_gating_emit(self):
        from dataclasses import replace
        from runners import us_short_weekly_capstone_stages as st

        for regime in ("防御", "unknown"):
            ctx = self._ctx(authorized=True)
            summary = {
                "schema_name": "us_short_vix_regime_fetch_summary",
                "schema_version": "1.0.0",
                "authorization_ref": "user_chat_20260709_vix_regime_fetch",
                "generated_at": ctx.generated_at,
                "observed_at": ctx.generated_at,
                "provider": "financial_modeling_prep",
                "source_endpoint": "stable/quote",
                "symbol": "^VIX",
                "http_status": 200 if regime != "unknown" else 429,
                "vix_regime": regime,
                "vix_regime_is_unknown": regime == "unknown",
            }
            provider_summaries = {
                stage: ({"stage": stage} if stage != "vix_regime" else summary)
                for stage in ("universe_fetch", "momentum_fetch", "sic_fetch", "pass2_fetch", "vix_regime")
            }
            receipt = _research_receipt(provider_summaries=provider_summaries)
            ctx = replace(ctx, research_live_capability=receipt)
            ctx.vix_regime_summary_path.parent.mkdir(parents=True, exist_ok=True)
            ctx.vix_regime_summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with mock.patch.object(st, "_write_provider_health"), \
                 mock.patch.object(st._bridge, "run_e2e", return_value={"batch4_run": {"emitted": True}}) as m:
                out = st.run_weekly_bridge(ctx)
            self.assertTrue(out["batch4_run"]["emitted"])
            self.assertEqual(m.call_args.kwargs["vix_regime"], regime)

            ctx.vix_regime_summary_path.write_text(
                json.dumps({**summary, "vix_regime": "进攻", "vix_regime_is_unknown": False}),
                encoding="utf-8",
            )
            from engine.us_short_run_origin import RunOriginError
            with mock.patch.object(st, "_write_provider_health"), \
                 mock.patch.object(st._bridge, "run_e2e"):
                with self.assertRaises(RunOriginError):
                    st.run_weekly_bridge(ctx)

    def test_receipt_binds_exact_stages_calls_decision_and_source_digest(self):
        # A1: receipt issuance consumes the exact completed stage sequence plus positive provider-call evidence and
        # binds the source packet path/digest. A changed packet cannot reuse the receipt.
        from engine.us_short_run_origin import RunOriginError, require_research_live_receipt_binding
        from runners import us_short_weekly_capstone as cap
        ctx = self._ctx(authorized=True)
        ctx.source_packet_path.parent.mkdir(parents=True, exist_ok=True)
        ctx.source_packet_path.write_text('{"packet":"one"}', encoding="utf-8")
        ctx.batch4_template_path.write_text('{"template":"one"}', encoding="utf-8")
        provider_results = {
            "universe_fetch": {
                "generated_at": ctx.generated_at,
                "decision_clock": {"decision_date": ctx.decision_date},
                "provider_call_evidence": {
                    "network_access_performed": True,
                    "provider_calls_performed": True,
                    "actual_total_calls": 23,
                },
            },
            "momentum_fetch": {
                "generated_at": ctx.generated_at,
                "scope": {"network_access_performed": True, "provider_calls_performed": True},
                "decision_clock": {"expected_decision_date": ctx.decision_date},
                "fetch_stats": {"grouped_calls_made": 70},
            },
            "sic_fetch": {
                "generated_at": ctx.generated_at,
                "scope": {"network_access_performed": True, "provider_calls_performed": True},
                "decision_clock": {"expected_decision_date": ctx.decision_date},
                "classification": {"sic_resolved_count": 100},
                "provider_call_evidence": {
                    "network_access_performed": True,
                    "provider_calls_performed": True,
                    "actual_total_calls": 101,
                },
            },
            "pass2_fetch": {
                "generated_at": ctx.generated_at,
                "scope": {"network_access_performed": True, "provider_calls_performed": True},
                "decision_clock": {"expected_decision_date": ctx.decision_date},
                "endpoint_call_budget": {
                    "actual_total_endpoint_calls": 1,
                    "max_total_http_attempts": 2,
                    "actual_total_http_attempts": 2,
                    "retry_count_used": 1,
                    "within_budget": True,
                },
                "endpoint_results": [{"provider_id": "sec_edgar", "endpoint_family": "submissions", "status": "success"}],
            },
            "vix_regime": {
                "schema_name": "us_short_vix_regime_fetch_summary",
                "schema_version": "1.0.0",
                "generated_at": ctx.generated_at,
                "observed_at": ctx.generated_at,
                "provider": "financial_modeling_prep",
                "source_endpoint": "stable/quote",
                "symbol": "^VIX",
                "http_status": 200,
                "vix_regime": "进攻",
                "vix_regime_is_unknown": False,
            },
        }
        results = [
            {
                "name": name,
                "gated": False,
                "best_effort": name == "forward_policy_shadow",
                "result": provider_results.get(name, {}),
            }
            for name in _STAGE_NAMES[:-1]
        ]
        manifest = (("candidate_artifact_path", str(ctx.source_packet_path.resolve()),
                     hashlib.sha256(ctx.source_packet_path.read_bytes()).hexdigest()),)
        action_manifest = (("batch4_action_template", str(ctx.batch4_template_path.resolve()),
                            hashlib.sha256(ctx.batch4_template_path.read_bytes()).hexdigest()),)
        with mock.patch.object(cap.source_packet_runner, "source_packet_input_manifest", return_value=manifest):
            receipt = cap._provider_execution_receipt(ctx, results)
        require_research_live_receipt_binding(
            receipt,
            decision_date=ctx.decision_date,
            source_packet_path=ctx.source_packet_path,
            source_packet_sha256=hashlib.sha256(ctx.source_packet_path.read_bytes()).hexdigest(),
            source_artifact_manifest=manifest,
            action_input_manifest=action_manifest,
        )
        ctx.source_packet_path.write_text('{"packet":"changed"}', encoding="utf-8")
        with self.assertRaises(RunOriginError):
            require_research_live_receipt_binding(
                receipt,
                decision_date=ctx.decision_date,
                source_packet_path=ctx.source_packet_path,
                source_packet_sha256=hashlib.sha256(ctx.source_packet_path.read_bytes()).hexdigest(),
            )
        ctx.batch4_template_path.write_text('{"template":"changed"}', encoding="utf-8")
        with self.assertRaises(RunOriginError):
            require_research_live_receipt_binding(
                receipt,
                action_input_manifest=((
                    "batch4_action_template", str(ctx.batch4_template_path.resolve()),
                    hashlib.sha256(ctx.batch4_template_path.read_bytes()).hexdigest(),
                ),),
            )
        from dataclasses import replace
        tampered = replace(receipt, source_packet_sha256="3" * 64)
        with self.assertRaises(RunOriginError):
            require_research_live_receipt_binding(tampered)
        tampered_manifest = replace(
            receipt,
            source_artifact_manifest=((manifest[0][0], manifest[0][1], "4" * 64),),
        )
        with self.assertRaises(RunOriginError):
            require_research_live_receipt_binding(tampered_manifest)
        provider_results["pass2_fetch"]["endpoint_call_budget"]["actual_total_http_attempts"] = 3
        with self.assertRaises(WeeklyCapstoneError):
            with mock.patch.object(cap.source_packet_runner, "source_packet_input_manifest", return_value=manifest):
                cap._provider_execution_receipt(ctx, results)
        provider_results["pass2_fetch"]["endpoint_call_budget"]["actual_total_http_attempts"] = 2
        provider_results["pass2_fetch"]["endpoint_call_budget"]["actual_total_endpoint_calls"] = 0
        with self.assertRaises(WeeklyCapstoneError):
            with mock.patch.object(cap.source_packet_runner, "source_packet_input_manifest", return_value=manifest):
                cap._provider_execution_receipt(ctx, results)

    def test_e2e_function_refuses_research_live_without_or_with_forged_capability(self):
        # Required A at the e2e function boundary: research_live without the EXACT capstone capability fails closed —
        # an ABSENT capability AND a FORGED one (True / a look-alike object) are both refused before any packet
        # read/output (the identity check defeats the earlier forgeable-boolean bypass).
        from runners import us_short_batch5_to_batch4_weekend_e2e as e2e
        for forged in (None, True, object()):
            kwargs = {} if forged is None else {"_research_live_capability": forged}
            with self.assertRaises(e2e.Batch5ToBatch4E2EError):
                e2e.run_e2e(
                    source_packet_path=Path("fixture.json"), batch4_template_path=Path("t.json"),
                    account_state_path=Path("a.json"), provider_health_path=Path("h.json"), private_root=Path("p"),
                    now_et=datetime(2026, 6, 15, 9, 0, 0), run_mode="research_live", **kwargs)

    def test_batch4_function_refuses_research_live_without_or_with_forged_capability(self):
        # Required A at the batch4 function boundary (the other entry point): absent + forged capability both fail
        # closed before the packet is read.
        from runners import us_short_weekend_batch4 as b4
        for forged in (None, True, object()):
            kwargs = {} if forged is None else {"_research_live_capability": forged}
            with self.assertRaises(b4.Batch4RunnerError):
                b4.run_packet(Path("nonexistent.json"), now_et=datetime(2026, 6, 15, 9, 0, 0),
                              run_mode="research_live", **kwargs)

    def test_cli_rejects_research_live_run_mode(self):
        # Required A: research_live is removed from BOTH generic CLIs' choices (operator-unselectable).
        from runners import us_short_batch5_to_batch4_weekend_e2e as e2e
        from runners import us_short_weekend_batch4 as b4
        with self.assertRaises(SystemExit):
            e2e.parse_args([
                "--source-packet", "s.json", "--batch4-template", "t.json", "--account", "a.json",
                "--provider-health", "h.json", "--private-root", "p", "--now-et", "2026-06-15T09:00:00",
                "--run-mode", "research_live"])
        with self.assertRaises(SystemExit):
            b4.parse_args(["--context", "c.json", "--now-et", "2026-06-15T09:00:00", "--run-mode", "research_live"])

    def test_orchestrator_refuses_research_live_without_capability(self):
        # Required A at the DEEPEST published surface: run_weekend_pipeline (signature published in README/CURRENT)
        # mints the research_live run_origin, so a DIRECT caller must ALSO hold the capstone capability. Absent/forged
        # capabilities fail closed at the gate (before any pipeline work); the EXACT capability passes the gate (then
        # errors later on the trivial context — proving only the gate rejected the forgeries, not the run_mode itself).
        from engine.us_short_weekend_orchestrator import WeekendOrchestratorError, run_weekend_pipeline
        now = datetime(2026, 6, 15, 9, 0, 0)
        for forged in (None, True, object()):
            kwargs = {} if forged is None else {"research_live_capability": forged}
            with self.assertRaises(WeekendOrchestratorError) as cm:
                run_weekend_pipeline(now, {}, run_mode="research_live", **kwargs)
            self.assertIn("capstone", str(cm.exception))     # the capability gate fired (not the pipeline_context check)
        with self.assertRaises(WeekendOrchestratorError) as cm:
            run_weekend_pipeline(now, {}, run_mode="research_live",
                                 research_live_capability=_research_receipt(decision_date="20260615"))
        self.assertIn("pipeline_context", str(cm.exception))  # capability accepted → next error is the context check

    def test_consumer_producers_refuse_hand_built_research_live_without_capability(self):
        # Required A (4th surface): the run_origin is a dict of PUBLIC strings, so a generic caller could hand-type a
        # research_live origin and drive the PUBLIC engine producers DIRECTLY (assemble_machine_record /
        # build_weekly_report / write_run_private), bypassing the entry+orchestrator gates. Each producer now
        # fail-closes at a consumer-layer guard (its FIRST statement) unless handed the capstone capability.
        from engine.us_short_run_origin import RunOriginError, require_research_live_capability
        from engine.us_short_weekend_machine_record import WeekendMachineRecordError, assemble_machine_record
        from engine.us_short_weekend_private_write import write_run_private
        from engine.us_short_weekend_report import build_weekly_report
        FORGED = {"run_mode": "research_live", "data_origin": "real_provider_pre_authoritative",
                  "operational_use": "not_authorized"}
        # the shared guard: research_live needs the EXACT capability; offline_test / non-research_live is a no-op
        for bad in (None, True, object()):
            with self.assertRaises(RunOriginError):
                require_research_live_capability(FORGED, bad)
        receipt = _research_receipt(decision_date="20260615")
        require_research_live_capability(FORGED, receipt, decision_date="20260615")   # ok — no raise
        advisory_receipt = _research_receipt(
            decision_date="20260615",
            provider_health_facts=(("fmp", "down"), ("sec_edgar", "ok")),
        )
        require_research_live_capability(FORGED, advisory_receipt, decision_date="20260615")
        require_research_live_capability({"run_mode": "offline_test"}, None)           # offline_test no-op
        # each producer fail-closes FIRST on a hand-built research_live origin with an absent/forged capability
        # (the guard precedes all other processing, so the garbage positional args are never reached)
        for forged in (None, True, object()):
            cap = {} if forged is None else {"research_live_capability": forged}
            with self.assertRaises(RunOriginError):
                assemble_machine_record(object(), as_of="20260615", run_origin=FORGED, **cap)
            with self.assertRaises(RunOriginError):
                build_weekly_report(object(), object(), report_context={}, run_context={}, stage_status={},
                                    selection={}, run_origin=FORGED, **cap)
            with self.assertRaises(RunOriginError):
                write_run_private(decision_date="20260615", machine_record={}, weekly_report_md="x", report_data={},
                                  provider_health={}, coverage_inputs={}, lifecycle_result={}, run_origin=FORGED, **cap)
        # A2: the STANDALONE official action-table persister is ALSO gated (the earlier "3 producers" grep MISSED it —
        # it takes the flattened record, not run_origin directly). A private out_path reaches the research_live gate.
        from engine.us_short_action_table_renderer import write_action_table
        with tempfile.TemporaryDirectory() as _td:
            _out = Path(_td) / "action_table.csv"
            for forged in (None, True, object()):
                cap = {} if forged is None else {"research_live_capability": forged}
                with self.assertRaises(RunOriginError):
                    write_action_table({"run_origin": FORGED, "rows": []}, _out, **cap)
            critical_down_receipt = _research_receipt(
                decision_date="20260615",
                provider_health_facts=(("fmp", "ok"), ("sec_edgar", "down")),
            )
            with self.assertRaises(RunOriginError):
                assemble_machine_record(object(), as_of="20260615", run_origin=FORGED,
                                        research_live_capability=critical_down_receipt)
            with self.assertRaises(RunOriginError):
                build_weekly_report(object(), object(), report_context={}, run_context={}, stage_status={},
                                    selection={}, run_origin=FORGED, research_live_capability=critical_down_receipt)
            with self.assertRaises(RunOriginError):
                write_run_private(decision_date="20260615", machine_record={}, weekly_report_md="x", report_data={},
                                  provider_health={}, coverage_inputs={}, lifecycle_result={}, run_origin=FORGED,
                                  research_live_capability=critical_down_receipt)
            with self.assertRaises(RunOriginError):
                write_action_table({"run_origin": FORGED, "rows": []}, _out,
                                   research_live_capability=critical_down_receipt)
        # positive control: WITH the exact capability the guard PASSES (the producer then fails on the garbage args
        # with its OWN typed error, NOT RunOriginError — proving the guard never blocks a legit research_live run)
        with self.assertRaises(WeekendMachineRecordError):
            assemble_machine_record({"regime": {}, "rows": []}, as_of="20260615", run_origin=FORGED,
                                    research_live_capability=receipt)
        with self.assertRaises(WeekendMachineRecordError):
            assemble_machine_record({"regime": {}, "rows": []}, as_of="20260615", run_origin=FORGED,
                                    research_live_capability=advisory_receipt)


class CapstoneAdapterSignatureTest(unittest.TestCase):
    """Regression guard: every kwarg each thin adapter passes must be a real parameter of the runner it wraps, so a
    future rename in a stage runner can't silently break the capstone until a live run. (Semantic path-validator
    behaviour is NOT covered here — that is verified on the first fresh-quota live run.)"""

    def test_every_adapter_kwarg_is_a_real_runner_parameter(self):
        import inspect

        from runners import us_short_weekly_capstone_stages as st

        checks = [
            (st._universe.run_fetch, ["now_et", "candidate_list_path", "generated_at", "confirm_user_authorization", "scan_bankruptcy_for_eligible"]),
            (st._mom_fetch.run_fetch, ["candidate_artifact_path", "series_packet_path", "ohlcv_series_packet_path", "summary_path", "generated_at", "confirm_user_authorization"]),
            (st._sic.run_fetch, ["candidate_artifact_path", "classification_packet_path", "summary_path", "generated_at", "confirm_user_authorization"]),
            (st._yfinance_grades.run_yfinance_grades_fetch, ["preflight_summary_path", "output_source_package_path", "output_resolved_actions_path", "summary_path", "raw_root", "confirm_user_authorization", "generated_at", "observed_at", "pace_seconds"]),
            (st._pass2.run_full_candidate_live_source_packet, ["preflight_summary_path", "expected_total_call_budget", "authorized_momentum_top_k", "forced_holding_tickers", "catalyst_recall_tickers", "source_artifact_prefix", "context_components_output_path", "output_data_context_path", "overextension_projection_path", "yfinance_grade_actions_path", "summary_path", "confirm_user_authorization", "run_data_context", "generated_at", "observed_at", "provider_pace_seconds", "max_retries_per_call", "retry_backoff_seconds", "max_total_http_attempts"]),
            (st._mom_prod.run_packet, ["candidate_artifact_path", "series_packet_path", "output_projection_path", "summary_path", "generated_at"]),
            (st._overextension.run_packet, ["candidate_artifact_path", "series_packet_path", "output_projection_path", "summary_path", "generated_at"]),
            (st._theme.run_packet, ["candidate_artifact_path", "series_packet_path", "classification_packet_path", "output_projection_path", "summary_path", "generated_at"]),
            (st._proj.run_packet, ["candidate_artifact_path", "expected_decision_date", "source_momentum_projection_path", "source_theme_projection_path", "output_momentum_projection_path", "output_theme_projection_path", "summary_path", "generated_at"]),
            (st._preflight.run_preflight, ["candidate_artifact_path", "expected_decision_date", "momentum_projection_path", "theme_projection_path", "summary_path", "forced_holding_tickers", "catalyst_recall_tickers", "momentum_top_k", "authorized_total_call_budget", "confirm_user_authorization", "generated_at"]),
            (st._bridge.run_e2e, ["source_packet_path", "batch4_template_path", "account_state_path", "provider_health_path", "private_root", "official_output_root", "now_et", "context_components_path", "run_mode", "_research_live_capability", "bootstrap_lifecycle", "generated_at"]),
        ]
        for fn, kwargs in checks:
            params = set(inspect.signature(fn).parameters)
            bad = [k for k in kwargs if k not in params]
            self.assertEqual(bad, [], f"{fn.__module__}.{fn.__name__} rejects kwargs {bad}")

    def test_capstone_universe_adapter_requires_integrated_fresh_bankruptcy_scan(self):
        from runners import us_short_weekly_capstone_stages as st
        from runners.us_short_weekly_capstone import resolve_capstone_context

        ctx = resolve_capstone_context(
            now_et=datetime(2026, 7, 9, 8, 0, 0),
            private_root=Path(tempfile.gettempdir()) / "cap_priv_bankruptcy",
            batch4_template_path=Path("template.json"),
            account_state_path=Path("account.json"),
            confirm_user_authorization=True,
        )
        with mock.patch.object(st._universe, "run_fetch", return_value={}) as run_fetch:
            st.run_universe(ctx)

        self.assertIs(run_fetch.call_args.kwargs["scan_bankruptcy_for_eligible"], True)

    def test_capstone_adapters_thread_same_window_ohlcv_to_projection_and_pass2(self):
        from runners import us_short_weekly_capstone_stages as st
        from runners.us_short_weekly_capstone import resolve_capstone_context

        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            ctx = resolve_capstone_context(
                now_et=datetime(2026, 7, 9, 8, 0, 0),
                private_root=root_path / "private",
                batch4_template_path=root_path / "template.json",
                account_state_path=root_path / "account.json",
                authorized_momentum_top_k=200,
                authorized_pass2_call_budget=16,
                confirm_user_authorization=True,
                state_dir=root_path / "state",
                sample_root=root_path,
            )
            ctx.preflight_summary_path.parent.mkdir(parents=True, exist_ok=True)
            ctx.preflight_summary_path.write_text(
                json.dumps({"endpoint_call_forecast": {"total_calls_for_pass2_target_cut": 16}}),
                encoding="utf-8",
            )
            with mock.patch.object(st._mom_fetch, "run_fetch", return_value={}) as momentum_fetch, \
                 mock.patch.object(st._overextension, "run_packet", return_value={}) as overextension, \
                 mock.patch.object(st._pass2, "run_full_candidate_live_source_packet", return_value={}) as pass2, \
                 mock.patch.object(st, "_account_holding_tickers", return_value=[]):
                st.run_momentum_fetch(ctx)
                st.run_overextension_producer(ctx)
                st.run_pass2_fetch(ctx)

            self.assertEqual(momentum_fetch.call_args.kwargs["ohlcv_series_packet_path"], ctx.ohlcv_series_packet_path)
            self.assertEqual(overextension.call_args.kwargs["series_packet_path"], ctx.ohlcv_series_packet_path)
            self.assertEqual(overextension.call_args.kwargs["output_projection_path"], ctx.overextension_projection_path)
            self.assertEqual(pass2.call_args.kwargs["overextension_projection_path"], ctx.overextension_projection_path)
            self.assertEqual(pass2.call_args.kwargs["yfinance_grade_actions_path"], ctx.yfinance_grade_actions_path)


class CapstoneStageSummaryPathTest(unittest.TestCase):
    """Regression guard for the exact seam a fake-stage chain structurally CANNOT cover: each per-run summary sidecar
    the capstone routes to a stage runner must be ACCEPTED by that runner's real fail-closed path validator. This is
    the check that would have caught the DRAFT path-allowlist break before a real run burned a provider fetch."""

    def _ctx(self):
        from runners.us_short_weekly_capstone import resolve_capstone_context
        # default sample_root = repo ROOT, so the paths resolve against the real provider_samples/ tree the runners
        # validate against.
        return resolve_capstone_context(
            now_et=datetime(2026, 7, 9, 8, 0, 0),
            private_root=Path(tempfile.gettempdir()) / "cap_priv",
            batch4_template_path=Path("template.json"),
            account_state_path=Path("account.json"),
        )

    def test_every_stage_summary_path_accepted_by_its_runner_validator(self):
        from runners import us_short_weekly_capstone_stages as st
        ctx = self._ctx()
        targets = st._stage_summary_targets(ctx)
        validators = {
            "momentum_fetch": st._mom_fetch._validate_summary_path,
            "momentum_producer": st._mom_prod._validate_summary_path,
            "overextension_producer": st._overextension._validate_summary_path,
            "sic_classification": st._sic._validate_summary_path,
            "theme_producer": st._theme._validate_summary_path,
            "projection_inputs": st._proj._validate_summary_path,
            "yfinance_grades_fetch": st._yfinance_grades._validate_summary_path,
            "pass2": st._pass2._validate_summary_path,
        }
        self.assertEqual(set(targets), set(validators))   # every routed summary has a validator checked
        for stage, path in targets.items():
            try:
                validators[stage](path)   # returns the resolved path; raises if the runner would reject it
            except Exception as exc:  # noqa: BLE001
                self.fail(f"stage '{stage}' summary path {path} rejected by its runner validator: {exc}")

    def test_preflight_summary_path_accepted_as_both_output_and_input(self):
        from runners import us_short_weekly_capstone_stages as st
        ctx = self._ctx()
        st._preflight._validate_summary_path(ctx.preflight_summary_path)   # stage-7 write location — must not raise
        # stage-8 reads the SAME path as its preflight INPUT: the path SHAPE must be accepted (it errors only because
        # the file is not written yet at validation time — proving it is NOT an allowlist rejection).
        with self.assertRaises(st._pass2.FullCandidateLiveSourcePacketError) as cm:
            st._pass2._validate_preflight_path(ctx.preflight_summary_path)
        self.assertIn("existing file", str(cm.exception))


class CapstoneProviderHealthDerivationTest(unittest.TestCase):
    """_write_provider_health derives {fmp, sec_edgar} from the REAL Pass2 summary (endpoint_results rows carry
    provider_id/endpoint_family/status per _summarize_endpoint). This is the emit-critical unit the stopped 2026-07-09
    run never reached and the fake-chain tests structurally cannot cover (they inject the bridge RESULT, not the
    derivation). FMP grades reads 'ok' only at its success-coverage threshold; emit-critical SEC instead requires
    exactly one successful submissions record for every unique Pass2 target identity."""

    def _derive(self, endpoint_results, budget):
        import json
        from types import SimpleNamespace

        from runners import us_short_weekly_capstone_stages as st
        endpoint_results = [dict(row) if isinstance(row, dict) else row for row in endpoint_results]
        sec_target_symbols = []
        for index, row in enumerate(endpoint_results):
            if isinstance(row, dict) and row.get("provider_id") == "sec_edgar" \
                    and row.get("endpoint_family") == "submissions":
                symbol = f"S{index:04d}"
                row.setdefault("symbol", symbol)
                sec_target_symbols.append(row["symbol"])
        tmp = Path(tempfile.mkdtemp(prefix="cap_health_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ctx = SimpleNamespace(sample_root=tmp, decision_date="20260710",
                              provider_health_path=tmp / "provider_health.json")
        summ = st._stage_summary_targets(ctx)["pass2"]
        summ.parent.mkdir(parents=True, exist_ok=True)
        summ.write_text(json.dumps({
            "endpoint_call_budget": budget,
            "endpoint_results": endpoint_results,
            "pass2_target_universe": {
                "target_count": len(sec_target_symbols),
                "target_symbols": sec_target_symbols,
            },
        }),
                        encoding="utf-8")
        st._write_provider_health(ctx)
        return json.loads(ctx.provider_health_path.read_text(encoding="utf-8"))

    @staticmethod
    def _row(provider, family, ok):
        return {"provider_id": provider, "endpoint_family": family, "status": "success" if ok else "error"}

    def test_provider_health_rejects_summary_changed_after_receipt(self):
        from types import SimpleNamespace

        from engine.us_short_run_origin import RunOriginError
        from runners import us_short_weekly_capstone_stages as st

        signed = {
            "endpoint_call_budget": {"actual_total_endpoint_calls": 2},
            "endpoint_results": [
                self._row("financial_modeling_prep", "grades", False),
                self._row("sec_edgar", "submissions", False),
            ],
        }
        provider_summaries = {
            stage: ({"stage": stage} if stage != "pass2_fetch" else signed)
            for stage in ("universe_fetch", "momentum_fetch", "sic_fetch", "pass2_fetch")
        }
        receipt = _research_receipt(provider_summaries=provider_summaries)
        tmp = Path(tempfile.mkdtemp(prefix="cap_health_receipt_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ctx = SimpleNamespace(
            sample_root=tmp,
            decision_date="20260709",
            provider_health_path=tmp / "provider_health.json",
            research_live_capability=receipt,
        )
        summary_path = st._stage_summary_targets(ctx)["pass2"]
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        tampered = {
            "endpoint_call_budget": {"actual_total_endpoint_calls": 2},
            "endpoint_results": [
                self._row("financial_modeling_prep", "grades", True),
                self._row("sec_edgar", "submissions", True),
            ],
        }
        summary_path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaises(RunOriginError):
            st._write_provider_health(ctx)
        self.assertFalse(ctx.provider_health_path.exists())

    def test_full_grades_and_sec_success_is_ok(self):
        rows = ([self._row("financial_modeling_prep", "grades", True) for _ in range(5)]
                + [self._row("sec_edgar", "submissions", True) for _ in range(5)])
        health = self._derive(rows, {"fmp_grades_calls": 5, "sec_submissions_calls": 5, "endpoint_error_count": 0})
        self.assertEqual(health, {"fmp": "ok", "sec_edgar": "ok"})

    def test_zero_grades_success_is_down(self):
        # every grades call errored -> no success row -> _family_ok False -> budget fallback also False
        # (endpoint_error_count>0) -> fmp down. This is the honest 2026-07-08/09 free-tier-429 outcome.
        rows = ([self._row("financial_modeling_prep", "grades", False) for _ in range(5)]
                + [self._row("sec_edgar", "submissions", True) for _ in range(5)])
        health = self._derive(rows, {"fmp_grades_calls": 5, "sec_submissions_calls": 5, "endpoint_error_count": 5})
        self.assertEqual(health["fmp"], "down")
        self.assertEqual(health["sec_edgar"], "ok")

    def test_low_grades_coverage_is_down(self):
        # item 2 (a): ONE success among 199 failures = 0.5% coverage < threshold -> fmp='down' (was 'ok' under the
        # old any-single-success leniency). The raw health remains transparent; the classifier treats this advisory
        # grades leg as usable_with_fallback while critical SEC remains ok.
        rows = ([self._row("financial_modeling_prep", "grades", True)]
                + [self._row("financial_modeling_prep", "grades", False) for _ in range(199)]
                + [self._row("sec_edgar", "submissions", True)])
        health = self._derive(rows, {"fmp_grades_calls": 200, "sec_submissions_calls": 1, "endpoint_error_count": 199})
        self.assertEqual(health["fmp"], "down")

    def test_sec_no_calls_is_down(self):
        # No exact target SEC submission coverage -> down.
        rows = [self._row("financial_modeling_prep", "grades", True)]
        health = self._derive(rows, {"fmp_grades_calls": 1, "sec_submissions_calls": 0, "endpoint_error_count": 0})
        self.assertEqual(health["sec_edgar"], "down")

    def test_sec_all_failed_is_down(self):
        # item 2 (a): ALL SEC submissions failed = 0% coverage -> sec_edgar='down' (was 'ok' under the old
        # attempted-only fallback). Fixes attempted != obtained: a call being MADE is no longer enough.
        rows = ([self._row("financial_modeling_prep", "grades", True) for _ in range(5)]
                + [self._row("sec_edgar", "submissions", False) for _ in range(5)])
        health = self._derive(rows, {"fmp_grades_calls": 5, "sec_submissions_calls": 5, "endpoint_error_count": 5})
        self.assertEqual(health["sec_edgar"], "down")

    def test_sec_partial_target_coverage_is_down_even_when_every_attempt_succeeds(self):
        # R3: endpoint-success coverage is not target-identity coverage. Two successful SEC calls cannot make a
        # three-ticker Pass2 target look clean when the third ticker was never covered.
        from runners import us_short_weekly_capstone_stages as st

        health = st.derive_provider_health({
            "pass2_target_universe": {"target_count": 3, "target_symbols": ["AAPL", "MSFT", "NVDA"]},
            "endpoint_results": [
                {"provider_id": "financial_modeling_prep", "endpoint_family": "grades", "status": "success"},
                {"provider_id": "sec_edgar", "endpoint_family": "submissions", "symbol": "AAPL", "status": "success"},
                {"provider_id": "sec_edgar", "endpoint_family": "submissions", "symbol": "MSFT", "status": "success"},
            ],
        })

        self.assertEqual(health["sec_edgar"], "down")

    def test_sec_error_for_any_required_target_is_down(self):
        from runners import us_short_weekly_capstone_stages as st

        health = st.derive_provider_health({
            "pass2_target_universe": {"target_count": 2, "target_symbols": ["AAPL", "MSFT"]},
            "endpoint_results": [
                {"provider_id": "financial_modeling_prep", "endpoint_family": "grades", "status": "success"},
                {"provider_id": "sec_edgar", "endpoint_family": "submissions", "symbol": "AAPL", "status": "success"},
                {"provider_id": "sec_edgar", "endpoint_family": "submissions", "symbol": "MSFT", "status": "error"},
            ],
        })

        self.assertEqual(health["sec_edgar"], "down")

    def test_sec_coverage_rejects_target_count_drift(self):
        from runners import us_short_weekly_capstone_stages as st

        health = st.derive_provider_health({
            "pass2_target_universe": {"target_count": 3, "target_symbols": ["AAPL", "MSFT"]},
            "endpoint_results": [
                {"provider_id": "financial_modeling_prep", "endpoint_family": "grades", "status": "success"},
                {"provider_id": "sec_edgar", "endpoint_family": "submissions", "symbol": "AAPL", "status": "success"},
                {"provider_id": "sec_edgar", "endpoint_family": "submissions", "symbol": "MSFT", "status": "success"},
            ],
        })

        self.assertEqual(health["sec_edgar"], "down")

    def test_sec_coverage_rejects_noninteger_target_count(self):
        from runners import us_short_weekly_capstone_stages as st

        health = st.derive_provider_health({
            "pass2_target_universe": {"target_count": True, "target_symbols": ["AAPL"]},
            "endpoint_results": [
                {"provider_id": "financial_modeling_prep", "endpoint_family": "grades", "status": "success"},
                {"provider_id": "sec_edgar", "endpoint_family": "submissions", "symbol": "AAPL", "status": "success"},
            ],
        })

        self.assertEqual(health["sec_edgar"], "down")

    def test_sec_coverage_rejects_duplicate_or_foreign_submission_identity(self):
        from runners import us_short_weekly_capstone_stages as st

        base = {
            "pass2_target_universe": {"target_count": 2, "target_symbols": ["AAPL", "MSFT"]},
            "endpoint_results": [
                {"provider_id": "financial_modeling_prep", "endpoint_family": "grades", "status": "success"},
                {"provider_id": "sec_edgar", "endpoint_family": "submissions", "symbol": "AAPL", "status": "success"},
                {"provider_id": "sec_edgar", "endpoint_family": "submissions", "symbol": "MSFT", "status": "success"},
            ],
        }
        for extra in (
            {"provider_id": "sec_edgar", "endpoint_family": "submissions", "symbol": "AAPL", "status": "success"},
            {"provider_id": "sec_edgar", "endpoint_family": "submissions", "symbol": "NVDA", "status": "success"},
        ):
            with self.subTest(extra=extra["symbol"]):
                summary = {**base, "endpoint_results": [*base["endpoint_results"], extra]}
                self.assertEqual(st.derive_provider_health(summary)["sec_edgar"], "down")

    def test_fmp_coverage_exactly_at_threshold_is_ok_but_partial_sec_target_coverage_is_down(self):
        # The FMP threshold remains inclusive; SEC's emit-critical contract instead requires every target identity.
        rows = ([self._row("financial_modeling_prep", "grades", i < 5) for i in range(10)]
                + [self._row("sec_edgar", "submissions", i < 5) for i in range(10)])
        health = self._derive(rows, {"fmp_grades_calls": 10, "sec_submissions_calls": 10, "endpoint_error_count": 10})
        self.assertEqual(health, {"fmp": "ok", "sec_edgar": "down"})

    def test_coverage_just_below_threshold_is_down(self):
        # boundary: 4/10 = 0.4 < 0.5 -> down.
        rows = ([self._row("financial_modeling_prep", "grades", i < 4) for i in range(10)]
                + [self._row("sec_edgar", "submissions", True) for _ in range(10)])
        health = self._derive(rows, {"fmp_grades_calls": 10, "sec_submissions_calls": 10, "endpoint_error_count": 6})
        self.assertEqual(health["fmp"], "down")

    def _run_on_raw(self, raw_text):
        import json
        from types import SimpleNamespace

        from runners import us_short_weekly_capstone_stages as st
        tmp = Path(tempfile.mkdtemp(prefix="cap_health_raw_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ctx = SimpleNamespace(sample_root=tmp, decision_date="20260710",
                              provider_health_path=tmp / "provider_health.json")
        summ = st._stage_summary_targets(ctx)["pass2"]
        summ.parent.mkdir(parents=True, exist_ok=True)
        summ.write_text(raw_text, encoding="utf-8")
        st._write_provider_health(ctx)   # must NOT raise
        return json.loads(ctx.provider_health_path.read_text(encoding="utf-8"))

    def test_malformed_summary_fails_closed_no_crash(self):
        # §6a P3 fix: container-level-malformed summaries must fail closed to {down, down}, never crash (the gate's
        # own defense-in-depth + honouring its fail-closed contract). Covers top-level non-dict, non-list/null
        # endpoint_results, and a missing results key.
        import json
        for bad in ("[]", "null", "42", '"hello"', "true",
                    json.dumps({"endpoint_results": None}), json.dumps({"endpoint_results": 5}),
                    json.dumps({"no_results_key": 1})):
            self.assertEqual(self._run_on_raw(bad), {"fmp": "down", "sec_edgar": "down"}, f"input={bad!r}")

    def test_unreadable_or_invalid_json_fails_closed(self):
        # invalid JSON and an empty/0-byte file -> fail closed to down, no crash.
        self.assertEqual(self._run_on_raw("{not valid json"), {"fmp": "down", "sec_edgar": "down"})
        self.assertEqual(self._run_on_raw(""), {"fmp": "down", "sec_edgar": "down"})


if __name__ == "__main__":
    unittest.main()
