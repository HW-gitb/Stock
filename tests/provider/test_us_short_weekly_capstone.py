from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from dataclasses import replace
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
    resolve_capstone_context,
    run_weekly_capstone,
)
from runners import us_short_weekly_capstone as capstone  # noqa: E402
from runners import us_short_weekly_capstone_stages as capstone_stages  # noqa: E402
from tests.provider import test_us_short_batch5_to_batch4_e2e as e2e_fixture  # noqa: E402
from tests.provider.us_short_private_test_root import temporary_us_short_state_directory  # noqa: E402

_STAGE_NAMES = [
    "universe_fetch", "momentum_fetch", "overextension_producer", "momentum_producer", "sic_fetch",
    "soft_discovery", "serenity_quality_forward", "theme_producer",
    "projection_inputs", "pass2_preflight", "yfinance_grades_fetch", "pass2_fetch", "vix_regime", "forward_policy_shadow",
    "forward_policy_corporate_actions", "forward_policy_maturity", "soft_boost_comparison_maturity", "soft_boost_comparison_capture", "weekly_bridge",
    # Post-bridge, no artifact. Knife 10b added the two that ADVANCE the 26-week
    # clock either side of the one that reads it; all three are inert while it is
    # dormant, and the fetch one is gated because it really does call a vendor.
    "market_diagnostic_fetch", "market_diagnostic_settle", "market_diagnostic",
]
_POST_BRIDGE_STAGE_NAMES = (
    "market_diagnostic_fetch", "market_diagnostic_settle", "market_diagnostic",
)
_PRE_BRIDGE_STAGE_NAMES = [
    name for name in _STAGE_NAMES if name not in {"weekly_bridge", *_POST_BRIDGE_STAGE_NAMES}
]
_PRE_BRIDGE_THROUGH_BRIDGE = _PRE_BRIDGE_STAGE_NAMES + ["weekly_bridge"]
_RECEIPT_STAGE_NAMES = tuple(
    name for name in _STAGE_NAMES if name not in {
        "soft_discovery", "serenity_quality_forward", "forward_policy_shadow", "forward_policy_corporate_actions",
        "forward_policy_maturity", "soft_boost_comparison_maturity", "soft_boost_comparison_capture", "weekly_bridge",
        "market_diagnostic", "market_diagnostic_fetch", "market_diagnostic_settle",
    }
)


def _health_facts(**overrides):
    keys = (
        "universe_status", "universe_market_cap", "massive_momentum", "sec_sic",
        "analyst_grades", "sec_offering_audit", "massive_events", "fmp_vix",
    )
    values = {key: "ok" for key in keys}
    values.update(overrides)
    return tuple((key, values[key]) for key in keys)


def _research_receipt(*, decision_date="20260709", source_path=None, generated_at="2026-07-09T08:00:00-04:00",
                      source_manifest=None, provider_summaries=None,
                      provider_health_facts=None, stage_executions=None):
    from engine.us_short_run_origin import _issue_capstone_research_live_receipt
    source = Path(source_path or (ROOT / "state" / "us_short" / "receipt_test_source.json")).resolve()
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else "1" * 64
    evidence_digest = "2" * 64
    source_manifest = source_manifest or (("test_source", str(source), source_digest),)
    provider_stages = (
        "universe_fetch", "momentum_fetch", "sic_fetch", "pass2_fetch", "yfinance_grades_fetch", "vix_regime",
    )
    summaries = {stage: {"stage": stage} for stage in provider_stages}
    summaries.update(provider_summaries or {})
    provider_summaries = summaries
    provider_summary_digests = tuple(
        (stage, hashlib.sha256(json.dumps(provider_summaries[stage], ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode("utf-8")).hexdigest())
        for stage in provider_stages
    )
    if provider_health_facts is None:
        provider_health_facts = _health_facts()
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

    def test_one_click_massive_retry_defaults_and_closed_override_matrix(self):
        self.assertEqual(
            capstone._normalize_capstone_retry_policy(None, None, auto_authorize_pass2_budget=True),
            (2, 65.0),
        )
        self.assertEqual(
            capstone._normalize_capstone_retry_policy(0, 0.0, auto_authorize_pass2_budget=True),
            (0, 0.0),
        )
        self.assertEqual(
            capstone._normalize_capstone_retry_policy(1, None, auto_authorize_pass2_budget=True),
            (1, 65.0),
        )
        self.assertEqual(
            capstone._normalize_capstone_retry_policy(2, 65.0, auto_authorize_pass2_budget=True),
            (2, 65.0),
        )
        with self.assertRaises(WeeklyCapstoneError):
            capstone._normalize_capstone_retry_policy(1, 64.0, auto_authorize_pass2_budget=True)
        with self.assertRaises(WeeklyCapstoneError):
            capstone._normalize_capstone_retry_policy(1, 0.0, auto_authorize_pass2_budget=True)
        with self.assertRaises(WeeklyCapstoneError):
            capstone._normalize_capstone_retry_policy(2, 0.0, auto_authorize_pass2_budget=True)
        self.assertEqual(
            capstone._automatic_pass2_http_attempt_cap(
                exact_pass2_calls=1001, target_count=200, max_retries=2,
            ),
            1121,
        )

    def test_retry_policy_is_not_checkpoint_identity(self):
        ctx = capstone.resolve_capstone_context(
            now_et=datetime(2026, 7, 9, 8, 0, 0),
            private_root=Path(tempfile.gettempdir()) / "capstone_checkpoint_identity_priv",
            batch4_template_path=Path("template.json"),
            account_state_path=Path("account.json"),
            max_retries_per_call=0,
            retry_backoff_seconds=0.0,
            max_total_http_attempts=None,
        )
        retry_ctx = replace(
            ctx,
            max_retries_per_call=2,
            retry_backoff_seconds=65.0,
            max_total_http_attempts=1121,
        )
        self.assertEqual(
            capstone._checkpoint_run_contract(ctx),
            capstone._checkpoint_run_contract(retry_ctx),
        )
        self.assertNotIn("max_retries_per_call", capstone._checkpoint_run_contract(retry_ctx))
        self.assertNotIn("retry_backoff_seconds", capstone._checkpoint_run_contract(retry_ctx))
        self.assertNotIn("max_total_http_attempts", capstone._checkpoint_run_contract(retry_ctx))

    def test_dry_run_resolves_canonical_and_plans_all_stages(self):
        plan = self._run(datetime(2026, 7, 9, 8, 0, 0), dry_run=True)   # Thu 07-09 08:00 ET = pre-open
        self.assertEqual(plan["mode"], "dry_run")
        self.assertEqual(plan["decision_date"], "20260709")
        self.assertEqual(plan["price_basis_date"], "20260708")   # latest settled session
        self.assertEqual(plan["stage_outcomes"], [])
        self.assertEqual(plan["stage_outcome_counts"], {
            "completed_work": 0,
            "no_work_expected": 0,
            "waiting_dependency": 0,
            "failed_nonblocking": 0,
        })
        self.assertEqual([s["name"] for s in plan["stages"]], _STAGE_NAMES)
        self.assertEqual(plan["gated_stages_need_authorization"],
                         ["universe_fetch", "momentum_fetch", "sic_fetch", "yfinance_grades_fetch", "pass2_fetch",
                          # Knife 10b: the benchmark and cash captures really do call a
                          # vendor, so the diagnostic fetch joins the authorization list
                          # rather than sneaking a request in behind an ungated stage.
                          "vix_regime", "forward_policy_corporate_actions", "market_diagnostic_fetch"])
        pass2 = next(stage for stage in plan["stages"] if stage["name"] == "pass2_fetch")
        self.assertEqual(pass2["contract_version"], "2.2.0")
        self.assertIn(
            "state/us_short/us_short_batch5_full_universe_ohlcv_series_20260708_packet.json",
            pass2["inputs"],
        )

    def test_context_binds_one_earlier_market_state_not_template_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prior = root / "runs_private" / "20260708"
            prior.mkdir(parents=True)
            (prior / "machine_record.json").write_text("{}", encoding="utf-8")
            (prior / "market_regime_state.json").write_text(json.dumps({
                "schema_name": "us_short_market_regime_state", "schema_version": "1.0.0",
                "as_of": "20260708", "market_risk_regime": "防御", "upgrade_count": 1,
            }), encoding="utf-8")
            ctx = resolve_capstone_context(
                now_et=datetime(2026, 7, 9, 8, 0, 0), private_root=root,
                batch4_template_path=Path("template.json"), account_state_path=Path("account.json"),
                state_dir=root / "state", sample_root=root,
            )
            self.assertEqual(ctx.prior_run_dir, prior)
            self.assertEqual((ctx.prior_regime, ctx.prior_upgrade_count), ("防御", 1))

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
        with self.assertRaisesRegex(WeeklyCapstoneError, "explicit per-execution authorization"):
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

    def test_invalid_physical_cap_fails_before_context_or_pipeline_stage(self):
        for invalid_cap in (0, -1, True, 1.5):
            with self.subTest(invalid_cap=invalid_cap):
                entered: list[str] = []
                stage = Stage(
                    "must_not_run",
                    False,
                    lambda _ctx: [],
                    lambda _ctx: [],
                    lambda _ctx: entered.append("stage") or {},
                )
                with self.assertRaisesRegex(WeeklyCapstoneError, "positive exact int"):
                    self._run(
                        datetime(2026, 7, 9, 8, 0, 0),
                        dry_run=False,
                        confirm_user_authorization=True,
                        max_retries_per_call=1,
                        max_total_http_attempts=invalid_cap,
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

    def test_default_capture_descriptor_uses_the_same_current_artifact_state(self):
        from runners import us_short_weekly_capstone_stages as st

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = capstone.resolve_capstone_context(
                now_et=datetime(2026, 7, 9, 8, 0, 0),
                private_root=root / "private",
                batch4_template_path=root / "template.json",
                account_state_path=root / "account.json",
                state_dir=root / "state",
                sample_root=root,
            )
            capture = next(stage for stage in capstone.default_pipeline()
                           if stage.name == "soft_boost_comparison_capture")
            disabled = replace(ctx, theme_soft_boost_enabled=False)
            self.assertEqual(capture.inputs(disabled), [])
            self.assertEqual(capture.outputs(disabled), [])
            discovery_disabled = replace(ctx, soft_discovery_enabled=False)
            self.assertEqual(st.classify_soft_boost_artifact_state(discovery_disabled), {
                "state": "none", "reason_code": "SOFT_BOOST_COMPARISON_NOT_REQUESTED",
            })
            self.assertEqual(capture.inputs(discovery_disabled), [])
            self.assertEqual(capture.outputs(discovery_disabled), [])
            for path in (
                ctx.soft_boost_consumption_receipt_path,
                ctx.soft_boost_shadow_receipt_path,
                ctx.soft_boost_comparison_ledger_path,
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")
            ready_result = {
                "requested_enabled": True,
                "status": "consumed_valid_nonempty",
                "reason_code": None,
                "effective_enabled": True,
                "evidence_bundle_written": True,
                "consumption_receipt_path": str(ctx.soft_boost_consumption_receipt_path),
                "shadow_receipt_path": str(ctx.soft_boost_shadow_receipt_path),
                "comparison_ledger_path": str(ctx.soft_boost_comparison_ledger_path),
                "provider_calls_performed": False,
            }
            ready = replace(ctx, soft_discovery_run_result={}, soft_boost_run_result=ready_result)
            self.assertEqual(capture.inputs(ready), [
                ctx.soft_boost_consumption_receipt_path,
                ctx.soft_boost_shadow_receipt_path,
            ])
            self.assertEqual(capture.outputs(ready), [ctx.soft_boost_pairwise_ledger_path])

    def test_k4b_current_run_artifact_exit_table_is_exhaustive(self):
        """Every current-run K4b exit maps to exactly one usable state.

        `pass2_preflight_only` and `legacy_checkpoint_without_soft_boost` are
        deliberately separate rows: their source summaries differ (null versus
        absent `soft_boost`), but the context adapter intentionally normalizes
        both to no K4b result for this run.  A present but malformed result is
        not that case and remains fail-closed.
        """
        from runners import us_short_weekly_capstone_stages as st

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = capstone.resolve_capstone_context(
                now_et=datetime(2026, 7, 9, 8, 0, 0),
                private_root=root / "private",
                batch4_template_path=root / "template.json",
                account_state_path=root / "account.json",
                state_dir=root / "state",
                sample_root=root,
            )
            zero_result = {
                "requested_enabled": True,
                "status": "zero_upstream_unavailable",
                "reason_code": "UPSTREAM_UNAVAILABLE",
                "effective_enabled": False,
                "evidence_bundle_written": False,
                "consumption_receipt_path": str(ctx.soft_boost_consumption_receipt_path),
                "shadow_receipt_path": None,
                "comparison_ledger_path": None,
                "provider_calls_performed": False,
            }
            ready_result = {
                **zero_result,
                "status": "consumed_valid_nonempty",
                "reason_code": None,
                "effective_enabled": True,
                "evidence_bundle_written": True,
                "shadow_receipt_path": str(ctx.soft_boost_shadow_receipt_path),
                "comparison_ledger_path": str(ctx.soft_boost_comparison_ledger_path),
            }
            cases = (
                (
                    "feature_disabled",
                    replace(ctx, theme_soft_boost_enabled=False),
                    {"state": "none", "reason_code": "SOFT_BOOST_COMPARISON_NOT_REQUESTED"},
                ),
                (
                    "soft_discovery_disabled",
                    replace(ctx, soft_discovery_run_result=None),
                    {"state": "none", "reason_code": "SOFT_BOOST_COMPARISON_NOT_REQUESTED"},
                ),
                (
                    "pass2_preflight_only_soft_boost_is_null",
                    replace(ctx, soft_discovery_run_result={}, soft_boost_run_result=None),
                    {"state": "none", "reason_code": "SOFT_BOOST_COMPARISON_NOT_REQUESTED"},
                ),
                (
                    "legacy_checkpoint_omits_soft_boost",
                    replace(ctx, soft_discovery_run_result={}, soft_boost_run_result=None),
                    {"state": "none", "reason_code": "SOFT_BOOST_COMPARISON_NOT_REQUESTED"},
                ),
                (
                    "current_k4b_result_is_malformed",
                    replace(ctx, soft_discovery_run_result={}, soft_boost_run_result={"requested_enabled": True}),
                    {"state": "none", "reason_code": "SOFT_BOOST_COMPARISON_ARTIFACT_INVALID"},
                ),
                (
                    "typed_zero_with_declared_receipt",
                    replace(ctx, soft_discovery_run_result={}, soft_boost_run_result=zero_result),
                    {"state": "consumption_only", "reason_code": "SOFT_BOOST_COMPARISON_NOT_APPLICABLE"},
                ),
                (
                    "valid_nonempty_with_complete_bundle",
                    replace(ctx, soft_discovery_run_result={}, soft_boost_run_result=ready_result),
                    {"state": "comparison_ready", "reason_code": "SOFT_BOOST_COMPARISON_READY"},
                ),
            )
            with mock.patch.object(Path, "is_file", return_value=True):
                for source_exit, case_ctx, expected in cases:
                    with self.subTest(source_exit=source_exit):
                        self.assertEqual(st.classify_soft_boost_artifact_state(case_ctx), expected)


class CapstoneStageOutcomeNormalizerTest(unittest.TestCase):
    def test_typed_stage_exit_table_is_closed_world(self):
        cases = (
            ("forward_policy_shadow", {}, "completed_work", "FORWARD_POLICY_SHADOW_CAPTURED"),
            ("forward_policy_corporate_actions", {"status": "complete"}, "completed_work", "CORPORATE_ACTIONS_CAPTURED"),
            ("forward_policy_corporate_actions", {"status": "no_eligible_mature_capture"}, "no_work_expected", "NO_ELIGIBLE_MATURE_CAPTURE"),
            ("forward_policy_corporate_actions", {"status": "incomplete_no_count"}, "failed_nonblocking", "CORPORATE_ACTIONS_INCOMPLETE_NO_COUNT"),
            ("forward_policy_maturity", {
                "ready_weeks_appended_or_confirmed": 0, "whole_week_no_count": 0,
                "already_ready_weeks_untouched": 0, "awaiting_adjustment_evidence_untouched": 0,
            }, "no_work_expected", "FORWARD_POLICY_MATURITY_NOT_DUE"),
            ("forward_policy_maturity", {
                "ready_weeks_appended_or_confirmed": 1, "whole_week_no_count": 0,
                "already_ready_weeks_untouched": 0, "awaiting_adjustment_evidence_untouched": 0,
            }, "completed_work", "FORWARD_POLICY_MATURITY_ADVANCED"),
            ("soft_boost_comparison_maturity", {"matured_observations_written": 0, "whole_week_no_count": 1}, "no_work_expected", "SOFT_BOOST_MATURITY_NO_COUNT"),
            ("soft_boost_comparison_maturity", {"matured_observations_written": 1, "whole_week_no_count": 0}, "completed_work", "SOFT_BOOST_MATURITY_ADVANCED"),
            ("soft_boost_comparison_capture", {
                "status": "not_applicable", "reason_code": "SOFT_BOOST_COMPARISON_NOT_REQUESTED",
                "comparison_capture_performed": False,
            }, "no_work_expected", "SOFT_BOOST_COMPARISON_NOT_REQUESTED"),
            ("soft_boost_comparison_capture", {
                "status": "failed", "reason_code": "SOFT_BOOST_COMPARISON_ARTIFACT_INVALID",
                "comparison_capture_performed": False,
            }, "failed_nonblocking", "SOFT_BOOST_COMPARISON_ARTIFACT_INVALID"),
            ("soft_discovery", {"status": "valid_nonempty"}, "completed_work", "SOFT_DISCOVERY_VALID_NONEMPTY"),
            ("soft_discovery", {"status": "valid_empty"}, "completed_work", "SOFT_DISCOVERY_VALID_EMPTY"),
            ("soft_discovery", {"status": "disabled"}, "no_work_expected", "SOFT_DISCOVERY_DISABLED"),
            ("soft_discovery", {"status": "upstream_unavailable", "reason_code": "MERGE_PAIR_UNAVAILABLE"}, "waiting_dependency", "MERGE_PAIR_UNAVAILABLE"),
            ("soft_discovery", {"status": "invalid_evidence", "reason_code": "INGEST_EVIDENCE_INVALID"}, "failed_nonblocking", "INGEST_EVIDENCE_INVALID"),
            ("serenity_quality_forward", {"status": "eligible"}, "completed_work", "SERENITY_QUALITY_ELIGIBLE"),
            ("serenity_quality_forward", {"status": "sleeping"}, "no_work_expected", "SERENITY_QUALITY_SLEEPING"),
            ("serenity_quality_forward", {
                "status": "not_evaluable", "observation": {"settlement_status": "pending_review"},
            }, "waiting_dependency", "SERENITY_REVIEW_PENDING"),
            ("serenity_quality_forward", {"status": "invalid_evidence"}, "failed_nonblocking", "SERENITY_INVALID_EVIDENCE"),
            ("market_diagnostic_fetch", {"fetch_status": "captured"}, "completed_work", "MARKET_DIAGNOSTIC_FETCH_CAPTURED"),
            ("market_diagnostic_fetch", {"fetch_status": "dormant"}, "no_work_expected", "MARKET_DIAGNOSTIC_DORMANT"),
            ("market_diagnostic_fetch", {"fetch_status": "waiting_for_paper_week"}, "waiting_dependency", "WAITING_FOR_PAPER_WEEK"),
            ("market_diagnostic_fetch", {"fetch_status": "capture_failed"}, "failed_nonblocking", "MARKET_DIAGNOSTIC_FETCH_FAILED"),
            ("market_diagnostic_settle", {"settle_status": "settled"}, "completed_work", "MARKET_DIAGNOSTIC_SETTLED"),
            ("market_diagnostic_settle", {"settle_status": "published"}, "completed_work", "MARKET_DIAGNOSTIC_SETTLED"),
            ("market_diagnostic_settle", {"settle_status": "idempotent"}, "completed_work", "MARKET_DIAGNOSTIC_SETTLED"),
            ("market_diagnostic_settle", {"settle_status": "recovered"}, "completed_work", "MARKET_DIAGNOSTIC_SETTLED"),
            ("market_diagnostic_settle", {"settle_status": "waiting_for_paper_week"}, "waiting_dependency", "WAITING_FOR_PAPER_WEEK"),
            ("market_diagnostic_settle", {"settle_status": "waiting_for_inputs"}, "waiting_dependency", "WAITING_FOR_INPUTS"),
            ("market_diagnostic_settle", {"settle_status": "stalled_on_a_finished_week"}, "waiting_dependency", "STALLED_ON_A_FINISHED_WEEK"),
            ("market_diagnostic_settle", {"settle_status": "dormant"}, "no_work_expected", "MARKET_DIAGNOSTIC_DORMANT"),
            ("market_diagnostic_settle", {"settle_status": "broken"}, "failed_nonblocking", "MARKET_DIAGNOSTIC_SETTLE_FAILED"),
            ("market_diagnostic_settle", {"settle_status": "failed"}, "failed_nonblocking", "MARKET_DIAGNOSTIC_SETTLE_FAILED"),
            ("market_diagnostic", {"clock_status": "not_started"}, "no_work_expected", "MARKET_DIAGNOSTIC_NOT_STARTED"),
            ("market_diagnostic", {"clock_status": "fresh"}, "waiting_dependency", "MARKET_DIAGNOSTIC_FIRST_WEEK_PENDING"),
            ("market_diagnostic", {"clock_status": "running", "report_lines": ["x"], "report_lines_delivered": True}, "completed_work", "MARKET_DIAGNOSTIC_REPORTED"),
            ("market_diagnostic", {"clock_status": "running", "report_lines": ["x"], "report_lines_delivered": False}, "failed_nonblocking", "MARKET_DIAGNOSTIC_REPORT_DELIVERY_FAILED"),
            ("market_diagnostic", {"clock_status": "running", "v1_1_status": "attribution_faulted", "report_lines": ["x"], "report_lines_delivered": True}, "failed_nonblocking", "MARKET_DIAGNOSTIC_FAULTED"),
            ("weekly_bridge", {"batch4_run": {"emitted": False, "no_emit_reason": "out_of_window"}}, "completed_work", "WEEKLY_REPORT_NOT_EMITTED_OUT_OF_WINDOW"),
            ("weekly_bridge", {"batch4_run": {"emitted": False, "no_emit_reason": "provider_health_blocked"}}, "waiting_dependency", "WEEKLY_REPORT_PROVIDER_HEALTH_BLOCKED"),
        )
        for stage_name, result, expected_class, expected_reason in cases:
            with self.subTest(stage_name=stage_name, result=result):
                self.assertEqual(
                    capstone._normalize_stage_outcome(stage_name, result),
                    {"outcome_class": expected_class, "reason_code": expected_reason},
                )

    def test_unknown_or_invalid_typed_result_fails_closed(self):
        for stage_name, result in (
            ("market_diagnostic_settle", {"settle_status": ["waiting_for_inputs"]}),
            ("market_diagnostic_settle", []),
            ("soft_discovery", {"status": "future_status"}),
            ("forward_policy_maturity", {"ready_weeks_appended_or_confirmed": 0}),
            ("soft_boost_comparison_capture", {"comparison_capture_performed": False, "status": "future_status"}),
            ("market_diagnostic", {"clock_status": "running", "report_lines": []}),
        ):
            with self.subTest(stage_name=stage_name):
                self.assertEqual(
                    capstone._normalize_stage_outcome(stage_name, result),
                    {"outcome_class": "failed_nonblocking", "reason_code": "OUTCOME_CONTRACT_UNRECOGNIZED"},
                )

    def test_failure_boundary_reasons_are_stable_and_do_not_include_exception_text(self):
        for failure_kind, reason_code in (
            ("input_gate", "STAGE_INPUT_UNREADABLE"),
            ("stage_run", "STAGE_EXECUTION_EXCEPTION"),
            ("fresh_output_missing", "FRESH_OUTPUT_MISSING"),
        ):
            with self.subTest(failure_kind=failure_kind):
                self.assertEqual(
                    capstone._normalize_stage_outcome("forward_policy_shadow", {}, failure_kind=failure_kind),
                    {"outcome_class": "failed_nonblocking", "reason_code": reason_code},
                )


class CapstoneFakeChainTest(unittest.TestCase):
    """Prove the orchestration (ordering, per-stage output validation, fail-fast, auth gating) with INJECTED fake
    stages that write canned outputs — no real runner, no network. state_dir is a tempdir so nothing touches the repo."""

    def setUp(self):
        self.state_dir = Path(tempfile.mkdtemp(prefix="cap_state_"))
        self.private_root = Path(tempfile.mkdtemp(prefix="cap_priv_"))

    def tearDown(self):
        shutil.rmtree(self.state_dir, ignore_errors=True)
        shutil.rmtree(self.private_root, ignore_errors=True)

    def _fake_stages(self, order_sink, *, break_stage=None, break_stages=None, skip_output_stage=None,
                     skip_output_stages=None, bridge_batch4=None,
                     missing_input_stage=None, present_input_stage=None, preflight_result=None,
                     omit_ohlcv_output=False):
        break_stages = set(break_stages or ())
        skip_output_stages = set(skip_output_stages or ())
        def outs_for(name):
            def momentum_outputs(c):
                outputs = [c.series_packet_path]
                if not omit_ohlcv_output:
                    outputs.append(c.ohlcv_series_packet_path)
                return outputs

            return {
                "universe_fetch": lambda c: [c.candidate_path],
                "momentum_fetch": momentum_outputs,
                "overextension_producer": lambda c: [c.overextension_projection_path],
                "momentum_producer": lambda c: [c.momentum_projection_path],
                "sic_fetch": lambda c: [c.classification_packet_path],
                "soft_discovery": lambda c: [c.soft_discovery_receipt_path],
                "serenity_quality_forward": lambda c: [
                    c.serenity_quality_observation_path,
                    c.serenity_quality_ledger_path,
                    c.serenity_quality_gate_path,
                    c.serenity_g1_blade6_preflight_path,
                ],
                "theme_producer": lambda c: [c.theme_projection_path],
                "projection_inputs": lambda c: [c.merged_momentum_path, c.merged_theme_path],
                "pass2_preflight": lambda c: [c.preflight_summary_path],
                "yfinance_grades_fetch": lambda c: [c.yfinance_grade_source_package_path, c.yfinance_grade_actions_path],
                "pass2_fetch": lambda c: [c.source_packet_path, c.context_components_path],
                "vix_regime": lambda c: [c.vix_regime_summary_path],
                "forward_policy_shadow": lambda c: [
                    c.forward_shadow_selection_private_path, c.forward_policy_summary_path,
                    c.forward_policy_source_capture_private_path,
                ],
                "forward_policy_corporate_actions": lambda c: [],
                "forward_policy_maturity": lambda c: [],
                "soft_boost_comparison_maturity": lambda c: [],
                "soft_boost_comparison_capture": lambda c: [c.soft_boost_pairwise_ledger_path],
                "weekly_bridge": lambda c: [
                    (c.official_output_root or c.private_root) / "weekly_private" / c.decision_date / "weekly_report.md",
                    (c.official_output_root or c.private_root) / "weekly_private" / c.decision_date / "action_table.csv",
                    (c.official_output_root or c.private_root) / "runs_private" / c.decision_date / "machine_record.json",
                ],
                # Read and advance the dormant 26-week diagnostic clock; no artifact.
                "market_diagnostic": lambda c: [],
                "market_diagnostic_fetch": lambda c: [],
                "market_diagnostic_settle": lambda c: [],
            }[name]

        stages = []
        for name in _STAGE_NAMES:
            outs = outs_for(name)
            gated = name in ("universe_fetch", "momentum_fetch", "sic_fetch", "yfinance_grades_fetch", "pass2_fetch",
                             "vix_regime", "forward_policy_corporate_actions", "market_diagnostic_fetch")

            def make_run(nm, outfn):
                def run(ctx):
                    order_sink.append(nm)
                    if nm == break_stage or nm in break_stages:
                        raise ValueError("boom in " + nm)
                    if nm != skip_output_stage and nm not in skip_output_stages:
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
                    if nm == "soft_discovery":
                        return {"status": "disabled", "reason_code": "SOFT_DISCOVERY_DISABLED"}
                    if nm == "serenity_quality_forward":
                        return {"status": "sleeping"}
                    if nm == "forward_policy_corporate_actions":
                        return {"status": "no_eligible_mature_capture"}
                    if nm == "forward_policy_maturity":
                        return {
                            "ready_weeks_appended_or_confirmed": 0,
                            "whole_week_no_count": 0,
                            "already_ready_weeks_untouched": 0,
                            "awaiting_adjustment_evidence_untouched": 0,
                        }
                    if nm == "soft_boost_comparison_maturity":
                        return {"matured_observations_written": 0, "whole_week_no_count": 0}
                    if nm == "soft_boost_comparison_capture":
                        return {
                            "status": "not_applicable",
                            "reason_code": "SOFT_BOOST_COMPARISON_NOT_REQUESTED",
                            "comparison_capture_performed": False,
                        }
                    if nm == "market_diagnostic_fetch":
                        return {"fetch_status": "dormant"}
                    if nm == "market_diagnostic_settle":
                        return {"settle_status": "dormant"}
                    if nm == "market_diagnostic":
                        return {"clock_status": "not_started", "report_lines": []}
                    return {"stage": nm}
                return run

            if name == missing_input_stage:
                ins = lambda c: [Path(c.private_root) / "_run_inputs" / "absent_declared_input.json"]
            elif name == present_input_stage:
                ins = lambda c: [c.candidate_path]   # produced by universe_fetch (stage 0) → present at this turn
            elif name == "pass2_fetch":
                ins = lambda c: [c.ohlcv_series_packet_path]
            else:
                ins = lambda c: []
            stages.append(Stage(
                name, gated, ins, outs, make_run(name, outs),
                best_effort=name in {
                    "forward_policy_shadow", "forward_policy_corporate_actions", "forward_policy_maturity",
                    "soft_boost_comparison_maturity",
                    "soft_boost_comparison_capture",
                },
            ))
        return stages

    def _run(self, order_sink, **kw):
        account_state_path = kw.pop("account_state_path", self.private_root / "account.json")
        runner = lambda: run_weekly_capstone(
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
        if kw.get("model_paper_store_root") is not None:
            with mock.patch(
                "engine.us_short_model_paper_activation.resolve_model_paper_activation",
                return_value={"status": "authorized", "receipt": {}},
            ):
                return runner()
        return runner()

    def test_unregistered_in_repo_root_fails_before_first_stage(self):
        from runners import us_short_weekly_capstone as cap

        order: list[str] = []
        bad_root = ROOT / "state" / "us_short" / "unregistered_capstone_root"
        with self.assertRaisesRegex(WeeklyCapstoneError, "private output preflight"):
            run_weekly_capstone(
                now_et=datetime(2026, 7, 9, 8, 0, 0),
                private_root=bad_root,
                batch4_template_path=bad_root / "batch4_template.json",
                account_state_path=bad_root / "account_state.json",
                dry_run=False,
                confirm_user_authorization=True,
                state_dir=self.state_dir,
                sample_root=self.state_dir,
                stages=self._fake_stages(order),
            )
        self.assertEqual(order, [])

        with temporary_us_short_state_directory(ROOT) as canonical_root_text:
            canonical_root = Path(canonical_root_text)

            def bridge_outputs(ctx):
                return cap._official_output_paths(ctx)

            def bridge_run(ctx):
                outputs = bridge_outputs(ctx)
                for path in outputs:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("{}", encoding="utf-8")
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

            summary = run_weekly_capstone(
                now_et=datetime(2026, 7, 9, 8, 0, 0),
                private_root=canonical_root,
                batch4_template_path=self.private_root / "batch4_template.json",
                account_state_path=canonical_root / "canonical_preflight_account.json",
                dry_run=False,
                confirm_user_authorization=True,
                state_dir=self.state_dir,
                sample_root=self.state_dir,
                stages=[Stage("weekly_bridge", False, lambda _ctx: [], bridge_outputs, bridge_run)],
            )
            self.assertEqual(summary["execution_mode"], "injected_pipeline")
            self.assertTrue(
                (canonical_root / "weekly_private" / "20260709" / "weekly_report.md").is_file()
            )
            self.assertTrue(
                (canonical_root / "weekly_private" / "20260709" / "action_table.csv").is_file()
            )
            self.assertTrue(
                (canonical_root / "runs_private" / "20260709" / "machine_record.json").is_file()
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

    def test_real_bridge_orchestrator_writer_twice_reuses_one_prior_and_publishes_four_states(self):
        """Exercise the dated state through the capstone transaction, not just the resolver or writer."""
        fixture = e2e_fixture.Batch5ToBatch4E2ETest(
            "test_local_source_packet_to_private_weekly_report_and_action_table")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        self.addCleanup(fixture._state_root_context.__exit__, None, None, None)

        decision_date = "20260615"
        prior_date = "20260612"
        prior_dir = self.private_root / "runs_private" / prior_date
        prior_dir.mkdir(parents=True)
        for name, payload in {
            "machine_record.json": {},
            "market_regime_state.json": {
                "schema_name": "us_short_market_regime_state", "schema_version": "1.0.0",
                "as_of": prior_date, "market_risk_regime": "防御", "upgrade_count": 1,
            },
            "holding_action_state.json": {
                "schema_name": "us_short_holding_action_state", "schema_version": "1.0.0",
                "as_of": prior_date, "positions": [],
            },
            "portfolio_guard_state.json": {
                "schema_name": "us_short_portfolio_guard_state", "schema_version": "1.0.0",
                "as_of": prior_date, "state": "normal",
            },
            "symbol_cooldown_state.json": {
                "schema_name": "us_short_symbol_cooldown_state", "schema_version": "1.0.0",
                "as_of": prior_date, "records": [],
            },
        }.items():
            (prior_dir / name).write_text(json.dumps(payload), encoding="utf-8")

        account_payload = e2e_fixture._empty_account()
        account = e2e_fixture._write_json(self.private_root / "account.json", account_payload)
        template = e2e_fixture._no_build_template(self.private_root / "batch4_template.json")
        seen_prior: list[Path | None] = []
        real_run_e2e = e2e_fixture.e2e.run_e2e

        def prepare_offline_health(ctx):
            ctx.provider_health_path.parent.mkdir(parents=True, exist_ok=True)
            ctx.provider_health_path.write_text(
                json.dumps(e2e_fixture._provider_health()), encoding="utf-8")
            ctx.vix_regime_summary_path.parent.mkdir(parents=True, exist_ok=True)
            ctx.vix_regime_summary_path.write_text(
                json.dumps({"vix_regime": "防御", "vix_regime_is_unknown": False}), encoding="utf-8")

        def offline_bridge(**kwargs):
            seen_prior.append(Path(kwargs["prior_run_dir"]).resolve() if kwargs["prior_run_dir"] else None)
            return real_run_e2e(
                **{
                    **kwargs,
                    "source_packet_path": fixture.paths["packet"],
                    "batch4_template_path": template,
                    "account_state_path": account,
                    "context_components_path": fixture.paths["components"],
                    "run_mode": "offline_test",
                    "_research_live_capability": None,
                    "projection_binding_expectations": e2e_fixture.e2e.PROJECTION_INPUTS_BINDING,
                }
            )

        stages = [Stage(
            "weekly_bridge", False, lambda _c: [fixture.paths["packet"]],
            capstone._official_output_paths, capstone_stages.run_weekly_bridge,
        )]
        run_kwargs = dict(
            now_et=datetime(2026, 6, 15, 8, 0, 0), private_root=self.private_root,
            batch4_template_path=template, account_state_path=account, dry_run=False,
            confirm_user_authorization=True, state_dir=self.state_dir, sample_root=self.state_dir,
            stages=stages,
        )
        with mock.patch.object(capstone_stages, "_write_provider_health", side_effect=prepare_offline_health), \
             mock.patch.object(capstone_stages._bridge, "run_e2e", side_effect=offline_bridge):
            first = run_weekly_capstone(**run_kwargs)
            first_state = json.loads(
                (self.private_root / "runs_private" / decision_date / "market_regime_state.json").read_text(
                    encoding="utf-8"))
            second = run_weekly_capstone(**run_kwargs)
        self.assertTrue(first["emitted"] and second["emitted"])
        self.assertEqual(seen_prior, [prior_dir.resolve(), prior_dir.resolve()])
        second_state = json.loads(
            (self.private_root / "runs_private" / decision_date / "market_regime_state.json").read_text(
                encoding="utf-8"))
        self.assertEqual(first_state, second_state)
        current = self.private_root / "runs_private" / decision_date
        self.assertTrue({
            "machine_record.json", "market_regime_state.json", "holding_action_state.json",
            "portfolio_guard_state.json", "symbol_cooldown_state.json",
        }.issubset({path.name for path in current.iterdir()}))
        dated_children = {path.name for path in (self.private_root / "runs_private").iterdir()
                          if path.is_dir() and path.name != "_superseded"}
        self.assertEqual(dated_children, {prior_date, decision_date})

    def test_pass2_summary_soft_boost_result_reaches_later_stage_context(self):
        order: list[str] = []
        stages = self._fake_stages(order)
        pass2 = next(stage for stage in stages if stage.name == "pass2_fetch")
        bridge = next(stage for stage in stages if stage.name == "weekly_bridge")
        original_pass2_run = pass2.run
        original_bridge_run = bridge.run
        expected = {
            "requested_enabled": True,
            "status": "zero_upstream_unavailable",
            "reason_code": "UPSTREAM_UNAVAILABLE",
            "effective_enabled": False,
            "evidence_bundle_written": False,
            "consumption_receipt_path": "state/us_short/current_consumption.json",
            "shadow_receipt_path": None,
            "comparison_ledger_path": None,
            "provider_calls_performed": False,
        }
        seen: dict[str, object] = {}

        def pass2_run(ctx):
            original_pass2_run(ctx)
            return {"stage": "pass2_fetch", "source_packet": {"soft_boost": expected}}

        def bridge_run(ctx):
            seen["soft_boost_run_result"] = ctx.soft_boost_run_result
            return original_bridge_run(ctx)

        pass2.run = pass2_run
        bridge.run = bridge_run
        self._run(order, stages=stages)
        self.assertEqual(seen["soft_boost_run_result"], expected)

    def test_typed_serenity_settlement_error_is_nonblocking(self):
        from engine.us_short_serenity_quality_forward import SerenityQualityForwardError

        order: list[str] = []
        with mock.patch(
            "engine.us_short_serenity_quality_forward.settle_pending_review",
            side_effect=SerenityQualityForwardError("legacy ledger"),
        ):
            summary = self._run(order, stages=self._fake_stages(order))
        self.assertEqual(order, _STAGE_NAMES)
        self.assertEqual(summary["mode"], "live")
        self.assertEqual(summary["execution_mode"], "injected_pipeline")

    def test_legacy_serenity_ledger_is_local_no_count_and_chain_continues(self):
        from engine import us_short_serenity_quality_forward as serenity_quality

        ledger = self.state_dir / "us_short_serenity_quality_forward_ledger.json"
        legacy = {
            "schema_name": serenity_quality.SCHEMA_NAME,
            "schema_version": serenity_quality.SCHEMA_VERSION,
            "quality_policy_version": serenity_quality.QUALITY_POLICY_VERSION,
            "cross_cohort_aggregation_allowed": False,
            "cohorts": [],
            "effects": dict(serenity_quality.EFFECT_BOUNDARY),
        }
        ledger.write_text(json.dumps(legacy, indent=2) + "\n", encoding="utf-8")
        order: list[str] = []
        settlement_result: dict[str, object] = {}
        original_settle = serenity_quality.settle_pending_review

        def settle_and_capture(**kwargs):
            result = original_settle(**kwargs)
            settlement_result.update(result)
            return result

        with mock.patch(
            "engine.us_short_serenity_quality_forward.settle_pending_review",
            side_effect=settle_and_capture,
        ) as settle:
            summary = self._run(order, stages=self._fake_stages(order))

        self.assertEqual(order, _STAGE_NAMES)
        self.assertEqual(summary["mode"], "live")
        self.assertEqual(settle.call_count, 1)
        self.assertEqual(settlement_result["status"], "no_count")
        self.assertEqual(settlement_result["evidence_status"], "invalid_evidence")

    def test_decision_lock_is_bound_to_the_injected_state_root_and_reacquirable(self):
        from runners import us_short_weekly_capstone as cap

        ctx = cap.resolve_capstone_context(
            now_et=datetime(2026, 7, 9, 8, 0, 0),
            private_root=self.private_root,
            batch4_template_path=Path("template.json"),
            account_state_path=Path("account.json"),
            state_dir=self.state_dir,
            sample_root=self.state_dir,
        )
        expected = (
            self.state_dir / "_transaction_locks" / f"{ctx.decision_date}.lock"
        ).resolve()
        self.assertEqual(cap._decision_lock_path(ctx), expected)
        first = cap._acquire_decision_lock(ctx)
        cap._release_decision_lock(first)
        second = cap._acquire_decision_lock(ctx)
        cap._release_decision_lock(second)

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

        self.assertEqual(order, _STAGE_NAMES[:_STAGE_NAMES.index("pass2_preflight") + 1])
        self.assertEqual(summary["mode"], "pass2_budget_preview")
        self.assertEqual(summary["pass2_call_budget"], 11)
        self.assertEqual(summary["pass2_target_count"], 2)
        self.assertEqual(summary["operational_use"], "not_authorized")
        self.assertIn("--pass2-call-budget 11", summary["next_required"])
        self.assertEqual(
            [row["stage"] for row in summary["stage_outcomes"]],
            [row["name"] for row in summary["stages"]],
        )
        self.assertTrue(all(row["execution_mode"] == "executed_budget_preview" for row in summary["stage_outcomes"]))
        self.assertEqual(sum(summary["stage_outcome_counts"].values()), len(summary["stage_outcomes"]))
        self.assertFalse((self.private_root / "weekly_private" / "20260709").exists())

    def test_one_click_production_shape_derives_and_threads_massive_physical_cap(self):
        # The operator wrapper must enter the real default-pipeline branch (stages=None), derive the approval from
        # the preflight target count, and hand the resulting physical cap to the Pass2 adapter before it runs.
        from runners import us_short_paper_one_click as one_click

        order: list[str] = []
        preflight_result = {
            "candidate_universe": {
                "candidate_artifact_sha256": hashlib.sha256(b"{}").hexdigest(),
            },
            "decision_clock": {
                "expected_decision_date": "20260709",
                "candidate_price_basis_date": "20260708",
            },
            "pass2_target_universe": {"momentum_top_k": 2, "target_count": 2},
            "endpoint_call_forecast": {"total_calls_for_pass2_target_cut": 11},
        }
        stages = self._fake_stages(order, preflight_result=preflight_result)
        pass2_stage = next(stage for stage in stages if stage.name == "pass2_fetch")
        original_pass2_run = pass2_stage.run
        observed: dict[str, object] = {}

        def capture_pass2_context(ctx):
            observed.update({
                "max_retries_per_call": ctx.max_retries_per_call,
                "retry_backoff_seconds": ctx.retry_backoff_seconds,
                "max_total_http_attempts": ctx.max_total_http_attempts,
                "exact_pass2_calls": ctx.budget_approval.exact_pass2_calls,
            })
            return original_pass2_run(ctx)

        pass2_stage.run = capture_pass2_context
        checkout_root = self.state_dir / "one_click_checkout"
        (checkout_root / "presets").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            ROOT / "presets" / "us_short_market_calendar_2026_2027.json",
            checkout_root / "presets" / "us_short_market_calendar_2026_2027.json",
        )
        with (
            mock.patch.object(one_click, "ROOT", checkout_root),
            mock.patch.object(one_click, "DEFAULT_STATE_DIR", self.state_dir),
            mock.patch.object(
                one_click,
                "resolve_model_paper_activation",
                return_value={"status": "authorized", "receipt": {}},
            ),
            mock.patch(
                "engine.us_short_model_paper_activation.resolve_model_paper_activation",
                return_value={"status": "authorized", "receipt": {}},
            ),
            mock.patch.object(capstone, "default_pipeline", return_value=stages),
            mock.patch.object(capstone, "_provider_execution_receipt", return_value=mock.Mock()),
            mock.patch(
                "runners.us_short_batch5_full_candidate_pass2_preflight.finalize_preflight_from_existing_derivation",
                return_value=preflight_result,
            ),
        ):
            summary = one_click.run_one_click(
                now_et=datetime(2026, 7, 9, 8, 0, 0),
                private_root=self.private_root,
                state_dir=self.state_dir,
                momentum_top_k=2,
                provider_pace_seconds=0.0,
            )

        self.assertEqual(summary["execution_mode"], "live_provider_fetch")
        self.assertEqual(observed, {
            "max_retries_per_call": 2,
            "retry_backoff_seconds": 65.0,
            "max_total_http_attempts": 13,
            "exact_pass2_calls": 11,
        })

    def test_shadow_failure_is_loud_nonblocking_and_bridge_emits(self):
        order: list[str] = []
        with mock.patch("builtins.print") as printed:
            summary = self._run(
                order,
                stages=self._fake_stages(order, break_stage="forward_policy_shadow"),
            )
        self.assertEqual(order, _STAGE_NAMES)
        self.assertTrue(summary["emitted"])
        self.assertNotIn("shadow_capture_failed", summary)
        shadow_outcome = next(item for item in summary["stage_outcomes"] if item["stage"] == "forward_policy_shadow")
        self.assertEqual(shadow_outcome["outcome_class"], "failed_nonblocking")
        self.assertEqual(shadow_outcome["reason_code"], "STAGE_EXECUTION_EXCEPTION")
        shadow_result = next(item for item in summary["stages"] if item["name"] == "forward_policy_shadow")
        self.assertTrue(shadow_result["best_effort"])
        self.assertEqual(shadow_result["result"], {
            "failure_kind": "stage_run", "error_type": "ValueError",
        })
        self.assertTrue(any(
            "US-SHORT STAGE FAILED" in str(call.args[0])
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
        shadow_outcome = next(item for item in summary["stage_outcomes"] if item["stage"] == "forward_policy_shadow")
        self.assertEqual(shadow_outcome["outcome_class"], "failed_nonblocking")
        self.assertEqual(shadow_outcome["reason_code"], "STAGE_INPUT_UNREADABLE")
        shadow_result = next(item for item in summary["stages"] if item["name"] == "forward_policy_shadow")
        self.assertTrue(shadow_result["best_effort"])
        self.assertEqual(shadow_result["result"], {
            "failure_kind": "input_gate", "error_type": "WeeklyCapstoneError",
        })
        self.assertTrue(any(
            "US-SHORT STAGE FAILED" in str(call.args[0])
            for call in printed.call_args_list
        ))

    def test_maturity_failure_is_loud_nonblocking_and_bridge_emits(self):
        order: list[str] = []
        with mock.patch("builtins.print") as printed:
            summary = self._run(
                order,
                stages=self._fake_stages(order, break_stage="forward_policy_maturity"),
            )
        self.assertTrue(summary["emitted"])
        self.assertEqual(order, _STAGE_NAMES)
        maturity_outcome = next(item for item in summary["stage_outcomes"] if item["stage"] == "forward_policy_maturity")
        self.assertEqual(maturity_outcome["outcome_class"], "failed_nonblocking")
        self.assertEqual(maturity_outcome["reason_code"], "STAGE_EXECUTION_EXCEPTION")
        maturity_result = next(item for item in summary["stages"] if item["name"] == "forward_policy_maturity")
        self.assertTrue(maturity_result["best_effort"])
        self.assertTrue(any(
            "US-SHORT STAGE FAILED" in str(call.args[0])
            for call in printed.call_args_list
        ))

    def test_multiple_nonblocking_failures_are_retained_in_stage_order_and_later_stages_continue(self):
        order: list[str] = []
        summary = self._run(
            order,
            stages=self._fake_stages(
                order,
                missing_input_stage="forward_policy_shadow",
                break_stages={"forward_policy_corporate_actions"},
                skip_output_stages={"soft_boost_comparison_capture"},
            ),
        )
        self.assertTrue(summary["emitted"])
        self.assertIn("weekly_bridge", order)
        failed = [
            row for row in summary["stage_outcomes"]
            if row["outcome_class"] == "failed_nonblocking"
        ]
        self.assertEqual(
            [(row["stage"], row["reason_code"]) for row in failed],
            [
                ("forward_policy_shadow", "STAGE_INPUT_UNREADABLE"),
                ("forward_policy_corporate_actions", "STAGE_EXECUTION_EXCEPTION"),
                ("soft_boost_comparison_capture", "FRESH_OUTPUT_MISSING"),
            ],
        )
        self.assertNotIn("shadow_capture_failed", summary)
        self.assertEqual(
            [row["name"] for row in summary["stages"] if row["name"] in {
                "forward_policy_shadow", "forward_policy_corporate_actions", "soft_boost_comparison_capture",
            }],
            ["forward_policy_shadow", "forward_policy_corporate_actions", "soft_boost_comparison_capture"],
        )
        self.assertEqual(
            sum(summary["stage_outcome_counts"].values()), len(summary["stage_outcomes"])
        )

    def test_stage_outcome_conservation_covers_executed_reused_and_refreshed_modes(self):
        for reuse_policy, expected_mode in (
            ("never", "executed"),
            ("frozen_inputs", "reused"),
            ("refresh_then_reuse_if_equivalent", "refreshed_equivalent"),
        ):
            with self.subTest(reuse_policy=reuse_policy):
                order: list[str] = []
                stage = Stage(
                    "outcome_probe", False, lambda _ctx: [], lambda _ctx: [],
                    lambda _ctx: order.append("outcome_probe") or {},
                    reuse_policy=reuse_policy,
                )
                with mock.patch.object(capstone, "default_pipeline", return_value=[stage]), \
                     mock.patch.object(capstone.checkpoint_store, "create_manifest", return_value=(self.state_dir / "checkpoint.json", {})), \
                     mock.patch.object(capstone.checkpoint_store, "load_manifest", return_value={}), \
                     mock.patch.object(capstone.checkpoint_store, "validate_resume_header"), \
                     mock.patch.object(capstone.checkpoint_store, "record_stage", return_value={}), \
                     mock.patch.object(capstone.checkpoint_store, "restore_stage", return_value=({}, "g", "o")), \
                     mock.patch.object(capstone.checkpoint_store, "refresh_output_from_equivalent_checkpoint", return_value=True), \
                     mock.patch.object(
                         capstone, "_publish_current_output_transaction",
                         side_effect=lambda _ctx, txn: capstone._abort_current_output_transaction(txn),
                     ):
                    summary = self._run(
                        order,
                        resume_from=self.state_dir / "resume.json",
                        authorized_pass2_call_budget=1,
                        model_paper_store_root=self.private_root / "model_paper_private",
                        model_paper_run_account_mode="paper_only",
                    )
                self.assertEqual(summary["stage_outcomes"], [{
                    "stage": "outcome_probe",
                    "execution_mode": expected_mode,
                    "outcome_class": "completed_work",
                    "reason_code": "STAGE_COMPLETED",
                }])
                self.assertEqual(sum(summary["stage_outcome_counts"].values()), 1)
                if expected_mode == "reused":
                    self.assertEqual(order, [])
                else:
                    self.assertEqual(order, ["outcome_probe"])

    def test_reused_stage_checkpoint_precedes_terminal_event(self):
        sequence: list[str] = []
        stage = Stage(
            "reused_order_probe", False, lambda _ctx: [], lambda _ctx: [],
            lambda _ctx: (_ for _ in ()).throw(AssertionError("reused stage must not run")),
            reuse_policy="frozen_inputs",
        )

        def record_stage(**_kwargs):
            sequence.append("checkpoint")
            return {}

        def diagnostic_event(event):
            if event.get("event") == "stage_completed":
                sequence.append("terminal")

        with mock.patch.object(capstone, "default_pipeline", return_value=[stage]), \
             mock.patch.object(capstone.checkpoint_store, "create_manifest", return_value=(self.state_dir / "checkpoint.json", {})), \
             mock.patch.object(capstone.checkpoint_store, "load_manifest", return_value={}), \
             mock.patch.object(capstone.checkpoint_store, "validate_resume_header"), \
             mock.patch.object(capstone.checkpoint_store, "record_stage", side_effect=record_stage), \
             mock.patch.object(capstone.checkpoint_store, "restore_stage", return_value=({}, "g", "o")), \
             mock.patch.object(
                 capstone, "_publish_current_output_transaction",
                         side_effect=lambda _ctx, txn: capstone._abort_current_output_transaction(txn),
             ):
            self._run(
                [],
                resume_from=self.state_dir / "resume.json",
                authorized_pass2_call_budget=1,
                model_paper_store_root=self.private_root / "model_paper_private",
                model_paper_run_account_mode="paper_only",
                diagnostic_event=diagnostic_event,
            )
        self.assertEqual(sequence, ["checkpoint", "terminal"])

    def test_best_effort_output_enumeration_is_recorded_nonblocking(self):
        order: list[str] = []
        events: list[dict] = []
        stages = self._fake_stages(order)
        shadow = next(stage for stage in stages if stage.name == "forward_policy_shadow")
        shadow.outputs = lambda _ctx: (_ for _ in ()).throw(ValueError("enumeration probe"))
        summary = self._run(order, stages=stages, diagnostic_event=events.append)
        self.assertTrue(summary["emitted"])
        self.assertNotIn("forward_policy_shadow", order)
        self.assertEqual(
            next(row for row in summary["stage_outcomes"] if row["stage"] == "forward_policy_shadow"),
            {
                "stage": "forward_policy_shadow",
                "execution_mode": "executed",
                "outcome_class": "failed_nonblocking",
                "reason_code": "STAGE_OUTPUT_ENUMERATION_FAILED",
            },
        )
        self.assertTrue(any(
            event.get("event") == "stage_failed"
            and event.get("stage") == "forward_policy_shadow"
            and event.get("failure_kind") == "output_enumeration"
            for event in events
        ))

    def test_only_comparison_capture_stages_may_be_best_effort(self):
        order: list[str] = []
        stages = self._fake_stages(order)
        next(stage for stage in stages if stage.name == "vix_regime").best_effort = True
        with self.assertRaisesRegex(WeeklyCapstoneError, "only comparison-capture stages"):
            self._run(order, stages=stages)
        self.assertEqual(order, [])

    def test_research_receipt_does_not_require_comparison_capture_stages(self):
        receipt = _research_receipt()
        self.assertNotIn("forward_policy_shadow", receipt.completed_stages)
        self.assertNotIn("forward_policy_corporate_actions", receipt.completed_stages)
        self.assertNotIn("forward_policy_maturity", receipt.completed_stages)

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

    def test_pass2_ohlcv_input_missing_fails_before_stage_body(self):
        order: list[str] = []
        with self.assertRaisesRegex(WeeklyCapstoneError, "pass2_fetch.*input"):
            self._run(
                order,
                stages=self._fake_stages(order, omit_ohlcv_output=True),
            )
        self.assertNotIn("pass2_fetch", order)

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

    def test_diagnostic_events_pin_the_last_stage_and_failure_class(self):
        order: list[str] = []
        events: list[dict] = []
        with self.assertRaisesRegex(WeeklyCapstoneError, "momentum_fetch"):
            self._run(
                order,
                stages=self._fake_stages(order, break_stage="momentum_fetch"),
                diagnostic_event=events.append,
            )
        self.assertIn(
            {"event": "stage_completed", "stage": "universe_fetch", "execution_mode": "executed"},
            [{key: item[key] for key in ("event", "stage", "execution_mode")} for item in events
             if item["event"] == "stage_completed"],
        )
        self.assertIn(
            {"event": "stage_failed", "stage": "momentum_fetch", "failure_kind": "stage_run", "error_type": "ValueError"},
            [{key: item[key] for key in ("event", "stage", "failure_kind", "error_type")} for item in events
             if item["event"] == "stage_failed"],
        )

    def test_bridge_provider_health_no_emit_is_waiting_dependency_not_no_work(self):
        # A blocked provider-health dependency honestly writes NO weekly_report.md, but it is not a no-work week.
        order: list[str] = []
        summary = self._run(order, stages=self._fake_stages(
            order, skip_output_stage="weekly_bridge",
            bridge_batch4={"emitted": False, "no_emit_reason": "provider_health_blocked"}))
        # A no-emit bridge aborts the output transaction and returns immediately, so
        # every post-bridge stage is skipped by design; the chain ran up to the bridge.
        self.assertEqual(order, _PRE_BRIDGE_THROUGH_BRIDGE)
        self.assertFalse(summary["emitted"])
        self.assertEqual(summary["no_emit_reason"], "provider_health_blocked")
        self.assertEqual(summary["stage_outcomes"][-1], {
            "stage": "weekly_bridge",
            "execution_mode": "executed",
            "outcome_class": "waiting_dependency",
            "reason_code": "WEEKLY_REPORT_PROVIDER_HEALTH_BLOCKED",
        })
        self.assertGreater(summary["stage_outcome_counts"]["waiting_dependency"], 0)
        self.assertEqual(sum(summary["stage_outcome_counts"].values()), len(summary["stage_outcomes"]))

    def test_bridge_out_of_window_no_emit_is_completed_work(self):
        order: list[str] = []
        summary = self._run(order, stages=self._fake_stages(
            order,
            skip_output_stage="weekly_bridge",
            bridge_batch4={"emitted": False, "no_emit_reason": "out_of_window"},
        ))
        self.assertFalse(summary["emitted"])
        self.assertEqual(summary["no_emit_reason"], "out_of_window")
        self.assertEqual(summary["stage_outcomes"][-1]["outcome_class"], "completed_work")
        self.assertEqual(summary["stage_outcomes"][-1]["reason_code"], "WEEKLY_REPORT_NOT_EMITTED_OUT_OF_WINDOW")

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
        self.assertTrue(wk.exists())                                        # abort restores the canonical prior slot
        self.assertTrue(rn.exists())
        self.assertEqual(self._superseded_files(), set())
        self.assertTrue(summary["superseded_prior_outputs"]["moved"])
        self.assertFalse((self.private_root / "weekly_private" / "_transaction_state" / "20260709.json").exists())

    def test_no_emit_restores_prior_for_next_week_resolution(self):
        from engine.us_short_weekend_private_write import resolve_prior_run_dir

        wk, rn = self._seed_prior_official_outputs()
        for name, payload in {
            "market_regime_state.json": {"as_of": "20260709"},
            "holding_action_state.json": {"as_of": "20260709"},
            "portfolio_guard_state.json": {"as_of": "20260709"},
            "symbol_cooldown_state.json": {"as_of": "20260709"},
        }.items():
            (rn / name).write_text(json.dumps(payload), encoding="utf-8")
        order: list[str] = []
        self._run(order, stages=self._fake_stages(
            order, skip_output_stage="weekly_bridge",
            bridge_batch4={"emitted": False, "no_emit_reason": "provider_health_blocked"}))

        self.assertTrue(wk.exists())
        self.assertTrue(rn.exists())
        self.assertEqual(resolve_prior_run_dir(self.private_root / "runs_private", "20260716"), rn)

    def test_stage_exception_supersedes_prior_same_date_current_outputs(self):
        wk, rn = self._seed_prior_official_outputs()
        order: list[str] = []
        with self.assertRaises(WeeklyCapstoneError):
            self._run(order, stages=self._fake_stages(order, break_stage="momentum_fetch"))
        self.assertTrue(wk.exists())
        self.assertTrue(rn.exists())
        self.assertEqual(self._superseded_files(), set())

    def test_missing_output_failure_supersedes_prior_same_date_current_outputs(self):
        # the third non-emitting outcome (a stage completes but does not produce its declared output) closes the class.
        wk, rn = self._seed_prior_official_outputs()
        order: list[str] = []
        with self.assertRaises(WeeklyCapstoneError):
            self._run(order, stages=self._fake_stages(order, skip_output_stage="pass2_fetch"))
        self.assertTrue(wk.exists())
        self.assertTrue(rn.exists())
        self.assertEqual(self._superseded_files(), set())

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
        self.assertTrue(wk.exists())
        self.assertTrue(rn.exists())
        self.assertEqual(self._superseded_files(), set())

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
        def reject_superseded_path(path):
            if "_superseded" in str(path):
                raise PrivatePathError("nonprivate")

        with mock.patch.object(cap, "reject_nonprivate_output_path", side_effect=reject_superseded_path):
            with self.assertRaises(WeeklyCapstoneError) as cm:
                self._run(order, stages=self._fake_stages(
                    order, skip_output_stage="weekly_bridge",
                    bridge_batch4={"emitted": False, "no_emit_reason": "x"}))
        self.assertIsInstance(cm.exception.__cause__, PrivatePathError)

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
        from dataclasses import replace
        from runners.us_short_weekly_capstone import Pass2BudgetApproval, resolve_capstone_context
        tmp = Path(tempfile.mkdtemp(prefix="cap_auth_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ctx = resolve_capstone_context(
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
        return replace(
            ctx,
            budget_approval=Pass2BudgetApproval(
                decision_date=ctx.decision_date,
                candidate_price_basis_date=ctx.price_basis_date,
                candidate_artifact_sha256="0" * 64,
                momentum_top_k=200,
                target_count=3,
                exact_pass2_calls=16,
                authorization_mode="manual",
                authorization_ref="test:capstone",
                generated_at=ctx.generated_at,
            ),
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
        from dataclasses import replace
        from runners import us_short_weekly_capstone_stages as st
        ctx = replace(
            self._ctx(authorized=True),
            soft_discovery_run_result={"status": "valid_nonempty"},
        )
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
                        self.assertIs(m.call_args.kwargs["budget_approval"], ctx.budget_approval)
                        self.assertIs(m.call_args.kwargs["theme_soft_boost_enabled"], True)
                        self.assertIs(
                            m.call_args.kwargs["soft_discovery_stage_result"],
                            ctx.soft_discovery_run_result,
                        )
                        self.assertEqual(
                            m.call_args.kwargs["provisional_theme_stage_receipt_path"],
                            ctx.soft_discovery_receipt_path,
                        )
                        self.assertEqual(
                            m.call_args.kwargs["provisional_theme_validation_path"],
                            ctx.soft_discovery_validation_path,
                        )
                        self.assertEqual(
                            m.call_args.kwargs["soft_boost_consumption_receipt_path"],
                            ctx.soft_boost_consumption_receipt_path,
                        )
                        self.assertEqual(
                            m.call_args.kwargs["soft_boost_state_dir"],
                            ctx.state_dir,
                        )
                    if adapter == "run_yfinance_grades_fetch":
                        self.assertIs(m.call_args.kwargs["budget_approval"], ctx.budget_approval)
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

    def test_pass2_fetch_explicit_soft_boost_off_forwards_no_k4b_paths(self):
        from dataclasses import replace
        from runners import us_short_weekly_capstone_stages as st

        ctx = replace(self._ctx(authorized=True), theme_soft_boost_enabled=False)
        with mock.patch.object(st, "_account_holding_tickers", return_value=[]), mock.patch.object(
            st._pass2, "run_full_candidate_live_source_packet", return_value={"ok": True}
        ) as run:
            st.run_pass2_fetch(ctx)
        self.assertIs(run.call_args.kwargs["theme_soft_boost_enabled"], False)
        self.assertIsNone(run.call_args.kwargs["soft_discovery_stage_result"])
        for field in (
            "provisional_theme_stage_receipt_path",
            "provisional_theme_validation_path",
            "original_candidate_artifact_path",
            "classification_packet_path",
            "soft_boost_consumption_receipt_path",
            "soft_boost_shadow_receipt_path",
            "soft_boost_comparison_ledger_path",
            "soft_boost_state_dir",
        ):
            self.assertIsNone(run.call_args.kwargs[field], field)

    def test_pass2_adapters_reject_missing_frozen_budget_before_wrapped_runner(self):
        from dataclasses import replace
        from runners import us_short_weekly_capstone_stages as st
        ctx = replace(self._ctx(authorized=True), authorized_pass2_call_budget=None, budget_approval=None)
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
            budget_approval=None,
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

    def test_bridge_passes_only_current_soft_boost_paths(self):
        from dataclasses import replace
        from runners import us_short_weekly_capstone_stages as st

        ctx = self._ctx(authorized=True)

        zero_result = {
            "requested_enabled": True,
            "status": "zero_upstream_unavailable",
            "reason_code": "UPSTREAM_UNAVAILABLE",
            "effective_enabled": False,
            "evidence_bundle_written": False,
            "consumption_receipt_path": str(ctx.soft_boost_consumption_receipt_path),
            "shadow_receipt_path": None,
            "comparison_ledger_path": None,
            "provider_calls_performed": False,
        }
        consumption_ctx = replace(
            ctx,
            theme_soft_boost_enabled=True,
            soft_discovery_run_result={},
            soft_boost_run_result=zero_result,
        )
        invalid_ctx = replace(
            ctx,
            theme_soft_boost_enabled=True,
            soft_discovery_run_result={},
            soft_boost_run_result={"requested_enabled": True},
        )
        not_requested_ctx = replace(
            ctx,
            theme_soft_boost_enabled=True,
            soft_discovery_run_result=None,
            soft_boost_run_result=None,
        )

        with mock.patch.object(st, "_write_provider_health"), \
             mock.patch.object(st, "comparison_banner_from_private_ledger_path", return_value=""), \
             mock.patch.object(st, "_deliver_serenity_shadow_to_official_report", return_value=None), \
             mock.patch.object(st, "_record_serenity_report_delivery"), \
             mock.patch.object(Path, "read_text", return_value="{}"), \
             mock.patch.object(Path, "is_file", return_value=True), \
             mock.patch.object(st._bridge, "run_e2e", return_value={}) as bridge:
            st.run_weekly_bridge(consumption_ctx)
            self.assertEqual(bridge.call_args.kwargs["soft_discovery_receipt_paths"], {
                "stage_receipt_path": str(ctx.soft_discovery_receipt_path),
                "consumption_receipt_path": str(ctx.soft_boost_consumption_receipt_path),
                "shadow_receipt_path": None,
                "comparison_ledger_path": None,
                "adjudication_receipt_path": None,
            })
            st.run_weekly_bridge(invalid_ctx)
            self.assertEqual(bridge.call_args.kwargs["soft_discovery_receipt_paths"], {
                "stage_receipt_path": None,
                "consumption_receipt_path": None,
                "shadow_receipt_path": None,
                "comparison_ledger_path": None,
                "adjudication_receipt_path": None,
                "artifact_state": "invalid",
            })
            st.run_weekly_bridge(not_requested_ctx)
            self.assertIsNone(bridge.call_args.kwargs["soft_discovery_receipt_paths"])

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
            self.assertIn("US-SHORT A1 对比轨", m.call_args.kwargs["forward_policy_comparison_reminder"])
            self.assertIn("仅建议，不自动切换 balanced", m.call_args.kwargs["forward_policy_comparison_reminder"])

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
                "best_effort": name in {
                    "forward_policy_shadow", "forward_policy_corporate_actions", "forward_policy_maturity",
                    "soft_boost_comparison_maturity",
                    "soft_boost_comparison_capture",
                },
                "result": provider_results.get(name, {}),
            }
            for name in _PRE_BRIDGE_STAGE_NAMES
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
            provider_health_facts=_health_facts(analyst_grades="down"),
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
                provider_health_facts=_health_facts(sec_offering_audit="down"),
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
            (st._universe.run_fetch, ["now_et", "candidate_list_path", "generated_at", "confirm_user_authorization"]),
            (st._mom_fetch.run_fetch, ["candidate_artifact_path", "series_packet_path", "ohlcv_series_packet_path", "summary_path", "generated_at", "confirm_user_authorization"]),
            (st._sic.run_fetch, ["candidate_artifact_path", "classification_packet_path", "summary_path", "generated_at", "confirm_user_authorization"]),
            (st._yfinance_grades.run_yfinance_grades_fetch, ["preflight_summary_path", "output_source_package_path", "output_resolved_actions_path", "summary_path", "raw_root", "confirm_user_authorization", "generated_at", "observed_at", "pace_seconds"]),
            (st._pass2.run_full_candidate_live_source_packet, ["preflight_summary_path", "expected_total_call_budget", "authorized_momentum_top_k", "forced_holding_tickers", "catalyst_recall_tickers", "source_artifact_prefix", "context_components_output_path", "output_data_context_path", "overextension_projection_path", "ohlcv_series_packet_path", "yfinance_grade_actions_path", "summary_path", "confirm_user_authorization", "run_data_context", "generated_at", "observed_at", "provider_pace_seconds", "max_retries_per_call", "retry_backoff_seconds", "max_total_http_attempts", "theme_soft_boost_enabled", "soft_discovery_stage_result", "provisional_theme_stage_receipt_path", "provisional_theme_validation_path", "original_candidate_artifact_path", "classification_packet_path", "soft_boost_consumption_receipt_path", "soft_boost_shadow_receipt_path", "soft_boost_comparison_ledger_path", "soft_boost_state_dir"]),
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

    def test_capstone_universe_adapter_leaves_bankruptcy_scan_for_pass2(self):
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

        self.assertNotIn("scan_bankruptcy_for_eligible", run_fetch.call_args.kwargs)

    def test_capstone_adapters_thread_same_window_ohlcv_to_projection_and_pass2(self):
        from dataclasses import replace
        from runners import us_short_weekly_capstone_stages as st
        from runners.us_short_weekly_capstone import Pass2BudgetApproval, resolve_capstone_context

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
            ctx = replace(
                ctx,
                budget_approval=Pass2BudgetApproval(
                    decision_date=ctx.decision_date,
                    candidate_price_basis_date=ctx.price_basis_date,
                    candidate_artifact_sha256="0" * 64,
                    momentum_top_k=200,
                    target_count=3,
                    exact_pass2_calls=16,
                    authorization_mode="manual",
                    authorization_ref="test:capstone",
                    generated_at=ctx.generated_at,
                ),
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
            self.assertEqual(pass2.call_args.kwargs["ohlcv_series_packet_path"], ctx.ohlcv_series_packet_path)
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
    """The receipt-bound projector derives the exact eight functional health families from stage results."""

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
            "source_artifacts": {"analyst_grade_actions_consumed_from": "fmp_analyst_grade_actions"},
        }),
                        encoding="utf-8")
        # The direct projector is the canonical unit; the write seam is covered separately below.
        return st.derive_capstone_provider_health({
            "universe_fetch": {
                "scope": {"status": "universe_fetch_and_pass1_completed"},
                "provider_health": {
                    "overall_run_state": "clean",
                    "status_sources": {
                        "state": "clean",
                        "outcome": {
                            "per_source": {"ticker_reference": "ok", "exchange_halt_feed": "ok", "sec_8k_item_103": "ok"},
                            "failed_sources": [], "failed_count": 0, "total_sources": 3,
                            "critical_failed": [], "critical_all_failed": False, "block_or_no_emit": False,
                        },
                    },
                },
                "pass1_result": {"needs_market_cap": []},
            },
            "momentum_fetch": {
                "fetch_stats": {"sessions_with_data": 5, "min_sessions_required": 3},
                "coverage": {"eligible_count": 1, "series_ticker_count": 1, "benchmarks_present": True},
            },
            "sic_fetch": {
                "classification": {"eligible_count": 1, "sic_resolved_count": 1, "sic_missing_count": 0},
            },
            "pass2_fetch": json.loads(summ.read_text(encoding="utf-8")),
            "vix_regime": {
                "http_status": 200, "vix_value": 18.0, "vix_regime": "进攻", "vix_regime_is_unknown": False,
            },
        })

    @staticmethod
    def _row(provider, family, ok):
        return {"provider_id": provider, "endpoint_family": family, "status": "success" if ok else "error"}

    def _receipt_branch_ctx(self, tmp):
        """Lay every producer summary on disk where _write_provider_health looks for it (O-P6R-6).

        The pre-existing receipt test wrote only the pass2 summary, so the loop raised on the FIRST stage
        (universe_fetch) and nothing downstream of it — including the receipt-bound facts themselves — was ever
        exercised. This builds the whole set so the production branch actually runs to completion.
        """
        from types import SimpleNamespace

        from runners import us_short_weekly_capstone_stages as st

        ctx = SimpleNamespace(
            sample_root=tmp,
            decision_date="20260709",
            provider_health_path=tmp / "provider_health.json",
            universe_summary_path=tmp / "universe_summary.json",
            vix_regime_summary_path=tmp / "vix_summary.json",
            research_live_capability=None,
        )
        targets = st._stage_summary_targets(ctx)
        paths = {
            "universe_fetch": ctx.universe_summary_path,
            "momentum_fetch": targets["momentum_fetch"],
            "sic_fetch": targets["sic_classification"],
            "pass2_fetch": targets["pass2"],
            "yfinance_grades_fetch": targets["yfinance_grades_fetch"],
            "vix_regime": ctx.vix_regime_summary_path,
        }
        summaries = {stage: {"stage": stage} for stage in paths}
        receipt = _research_receipt(provider_summaries=summaries)
        for stage, path in paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(summaries[stage], ensure_ascii=False), encoding="utf-8")
        ctx.research_live_capability = receipt
        return ctx, paths, receipt

    def test_receipt_branch_writes_exactly_the_receipt_bound_eight_family_facts(self):
        from runners import us_short_weekly_capstone_stages as st

        tmp = Path(tempfile.mkdtemp(prefix="cap_health_receipt_full_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ctx, _paths, receipt = self._receipt_branch_ctx(tmp)

        st._write_provider_health(ctx)

        written = json.loads(ctx.provider_health_path.read_text(encoding="utf-8"))
        self.assertEqual(written, dict(receipt.provider_health_facts))
        self.assertEqual(tuple(written), tuple(k for k, _ in receipt.provider_health_facts))

    def test_receipt_branch_rejects_any_producer_summary_edited_after_the_receipt(self):
        from engine.us_short_run_origin import RunOriginError
        from runners import us_short_weekly_capstone_stages as st

        for tampered_stage in ("universe_fetch", "pass2_fetch", "vix_regime"):
            with self.subTest(stage=tampered_stage):
                tmp = Path(tempfile.mkdtemp(prefix="cap_health_receipt_tamper_"))
                self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
                ctx, paths, _receipt = self._receipt_branch_ctx(tmp)
                paths[tampered_stage].write_text(
                    json.dumps({"stage": tampered_stage, "edited": True}, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(RunOriginError):
                    st._write_provider_health(ctx)
                self.assertFalse(ctx.provider_health_path.exists())

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
        self.assertEqual(health["analyst_grades"], "ok")
        self.assertEqual(health["sec_offering_audit"], "ok")

    def test_zero_grades_success_is_down(self):
        # every grades call errored -> no success row -> _family_ok False -> budget fallback also False
        # (endpoint_error_count>0) -> fmp down. This is the honest 2026-07-08/09 free-tier-429 outcome.
        rows = ([self._row("financial_modeling_prep", "grades", False) for _ in range(5)]
                + [self._row("sec_edgar", "submissions", True) for _ in range(5)])
        health = self._derive(rows, {"fmp_grades_calls": 5, "sec_submissions_calls": 5, "endpoint_error_count": 5})
        self.assertEqual(health["analyst_grades"], "down")
        self.assertEqual(health["sec_offering_audit"], "ok")

    def test_low_grades_coverage_is_down(self):
        # item 2 (a): ONE success among 199 failures = 0.5% coverage < threshold -> fmp='down' (was 'ok' under the
        # old any-single-success leniency). The raw health remains transparent; the classifier treats this advisory
        # grades leg as usable_with_fallback while critical SEC remains ok.
        rows = ([self._row("financial_modeling_prep", "grades", True)]
                + [self._row("financial_modeling_prep", "grades", False) for _ in range(199)]
                + [self._row("sec_edgar", "submissions", True)])
        health = self._derive(rows, {"fmp_grades_calls": 200, "sec_submissions_calls": 1, "endpoint_error_count": 199})
        self.assertEqual(health["analyst_grades"], "degraded")

    def test_sec_no_calls_is_down(self):
        # No exact target SEC submission coverage -> down.
        rows = [self._row("financial_modeling_prep", "grades", True)]
        health = self._derive(rows, {"fmp_grades_calls": 1, "sec_submissions_calls": 0, "endpoint_error_count": 0})
        self.assertEqual(health["sec_offering_audit"], "down")

    def test_sec_all_failed_is_down(self):
        # item 2 (a): ALL SEC submissions failed = 0% coverage -> sec_edgar='down' (was 'ok' under the old
        # attempted-only fallback). Fixes attempted != obtained: a call being MADE is no longer enough.
        rows = ([self._row("financial_modeling_prep", "grades", True) for _ in range(5)]
                + [self._row("sec_edgar", "submissions", False) for _ in range(5)])
        health = self._derive(rows, {"fmp_grades_calls": 5, "sec_submissions_calls": 5, "endpoint_error_count": 5})
        self.assertEqual(health["sec_offering_audit"], "down")

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

        self.assertEqual(health["sec_offering_audit"], "down")

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

        self.assertEqual(health["sec_offering_audit"], "down")

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

        self.assertEqual(health["sec_offering_audit"], "down")

    def test_sec_coverage_rejects_noninteger_target_count(self):
        from runners import us_short_weekly_capstone_stages as st

        health = st.derive_provider_health({
            "pass2_target_universe": {"target_count": True, "target_symbols": ["AAPL"]},
            "endpoint_results": [
                {"provider_id": "financial_modeling_prep", "endpoint_family": "grades", "status": "success"},
                {"provider_id": "sec_edgar", "endpoint_family": "submissions", "symbol": "AAPL", "status": "success"},
            ],
        })

        self.assertEqual(health["sec_offering_audit"], "down")

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
                self.assertEqual(st.derive_provider_health(summary)["sec_offering_audit"], "down")

    def test_fmp_coverage_exactly_at_threshold_is_ok_but_partial_sec_target_coverage_is_down(self):
        # The FMP threshold remains inclusive; SEC's emit-critical contract instead requires every target identity.
        rows = ([self._row("financial_modeling_prep", "grades", i < 5) for i in range(10)]
                + [self._row("sec_edgar", "submissions", i < 5) for i in range(10)])
        health = self._derive(rows, {"fmp_grades_calls": 10, "sec_submissions_calls": 10, "endpoint_error_count": 10})
        self.assertEqual(health["analyst_grades"], "degraded")
        self.assertEqual(health["sec_offering_audit"], "down")

    def test_coverage_just_below_threshold_is_down(self):
        # boundary: 4/10 = 0.4 < 0.5 -> down.
        rows = ([self._row("financial_modeling_prep", "grades", i < 4) for i in range(10)]
                + [self._row("sec_edgar", "submissions", True) for _ in range(10)])
        health = self._derive(rows, {"fmp_grades_calls": 10, "sec_submissions_calls": 10, "endpoint_error_count": 6})
        self.assertEqual(health["analyst_grades"], "degraded")

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
            self.assertEqual(
                self._run_on_raw(bad),
                {"universe_status": "missing", "universe_market_cap": "missing", "massive_momentum": "missing",
                 "sec_sic": "missing", "analyst_grades": "missing", "sec_offering_audit": "down",
                 "massive_events": "missing", "fmp_vix": "missing"},
                f"input={bad!r}",
            )

    def test_unreadable_or_invalid_json_fails_closed(self):
        # invalid JSON and an empty/0-byte file -> fail closed to down, no crash.
        expected = {
            "universe_status": "missing", "universe_market_cap": "missing", "massive_momentum": "missing",
            "sec_sic": "missing", "analyst_grades": "missing", "sec_offering_audit": "down",
            "massive_events": "missing", "fmp_vix": "missing",
        }
        self.assertEqual(self._run_on_raw("{not valid json"), expected)
        self.assertEqual(self._run_on_raw(""), expected)


if __name__ == "__main__":
    unittest.main()
