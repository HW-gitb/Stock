from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


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
    "universe_fetch", "momentum_fetch", "momentum_producer", "sic_fetch", "theme_producer",
    "projection_inputs", "pass2_preflight", "pass2_fetch", "weekly_bridge",
]


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
                         ["universe_fetch", "momentum_fetch", "sic_fetch", "pass2_fetch"])

    def test_intraday_now_et_fails_closed(self):
        # 07-09 11:00 ET is inside the RTH session [09:30, 16:00) -> §2.1 dead zone -> no canonical, no run.
        with self.assertRaises(WeeklyCapstoneError):
            self._run(datetime(2026, 7, 9, 11, 0, 0), dry_run=True)

    def test_live_run_requires_authorization(self):
        with self.assertRaises(WeeklyCapstoneError):
            self._run(datetime(2026, 7, 9, 8, 0, 0), dry_run=False, confirm_user_authorization=False)

    def test_tz_aware_now_et_rejected(self):
        from datetime import timezone
        with self.assertRaises(WeeklyCapstoneError):
            self._run(datetime(2026, 7, 9, 8, 0, 0, tzinfo=timezone.utc), dry_run=True)


class CapstoneFakeChainTest(unittest.TestCase):
    """Prove the orchestration (ordering, per-stage output validation, fail-fast, auth gating) with INJECTED fake
    stages that write canned outputs — no real runner, no network. state_dir is a tempdir so nothing touches the repo."""

    def setUp(self):
        self.state_dir = Path(tempfile.mkdtemp(prefix="cap_state_"))
        self.private_root = Path(tempfile.mkdtemp(prefix="cap_priv_"))

    def tearDown(self):
        shutil.rmtree(self.state_dir, ignore_errors=True)
        shutil.rmtree(self.private_root, ignore_errors=True)

    def _fake_stages(self, order_sink, *, break_stage=None, skip_output_stage=None):
        def outs_for(name):
            return {
                "universe_fetch": lambda c: [c.candidate_path],
                "momentum_fetch": lambda c: [c.series_packet_path],
                "momentum_producer": lambda c: [c.momentum_projection_path],
                "sic_fetch": lambda c: [c.classification_packet_path],
                "theme_producer": lambda c: [c.theme_projection_path],
                "projection_inputs": lambda c: [c.merged_momentum_path, c.merged_theme_path],
                "pass2_preflight": lambda c: [c.preflight_summary_path],
                "pass2_fetch": lambda c: [c.source_packet_path, c.context_components_path],
                "weekly_bridge": lambda c: [c.private_root / "weekly_private" / c.decision_date / "weekly_report.md"],
            }[name]

        stages = []
        for name in _STAGE_NAMES:
            outs = outs_for(name)
            gated = name in ("universe_fetch", "momentum_fetch", "sic_fetch", "pass2_fetch")

            def make_run(nm, outfn):
                def run(ctx):
                    order_sink.append(nm)
                    if nm == break_stage:
                        raise ValueError("boom in " + nm)
                    if nm != skip_output_stage:
                        for p in outfn(ctx):
                            Path(p).parent.mkdir(parents=True, exist_ok=True)
                            Path(p).write_text("{}", encoding="utf-8")
                    return {"stage": nm}
                return run

            stages.append(Stage(name, gated, lambda c: [], outs, make_run(name, outs)))
        return stages

    def _run(self, order_sink, **kw):
        return run_weekly_capstone(
            now_et=datetime(2026, 7, 9, 8, 0, 0),
            private_root=self.private_root,
            batch4_template_path=Path("template.json"),
            account_state_path=Path("account.json"),
            dry_run=False,
            confirm_user_authorization=True,
            state_dir=self.state_dir,
            **kw,
        )

    def test_full_chain_runs_in_order_and_emits(self):
        order: list[str] = []
        summary = self._run(order, stages=self._fake_stages(order))
        self.assertEqual(order, _STAGE_NAMES)                 # every stage ran, in dependency order
        self.assertEqual(summary["mode"], "live")
        self.assertEqual(summary["decision_date"], "20260709")
        self.assertTrue(summary["emitted_report"].endswith("weekly_report.md"))

    def test_stage_missing_output_fails_fast_with_stage_name(self):
        order: list[str] = []
        with self.assertRaises(WeeklyCapstoneError) as cm:
            self._run(order, stages=self._fake_stages(order, skip_output_stage="pass2_fetch"))
        self.assertIn("pass2_fetch", str(cm.exception))
        self.assertNotIn("weekly_bridge", order)             # aborted before the next stage

    def test_stage_exception_wrapped_with_stage_name(self):
        order: list[str] = []
        with self.assertRaises(WeeklyCapstoneError) as cm:
            self._run(order, stages=self._fake_stages(order, break_stage="momentum_fetch"))
        self.assertIn("momentum_fetch", str(cm.exception))
        self.assertEqual(order, ["universe_fetch", "momentum_fetch"])   # fail-fast, no further stages


class CapstoneAdapterSignatureTest(unittest.TestCase):
    """Regression guard: every kwarg each thin adapter passes must be a real parameter of the runner it wraps, so a
    future rename in a stage runner can't silently break the capstone until a live run. (Semantic path-validator
    behaviour is NOT covered here — that is verified on the first fresh-quota live run.)"""

    def test_every_adapter_kwarg_is_a_real_runner_parameter(self):
        import inspect

        from runners import us_short_weekly_capstone_stages as st

        checks = [
            (st._universe.run_fetch, ["now_et", "candidate_list_path", "generated_at", "confirm_user_authorization"]),
            (st._mom_fetch.run_fetch, ["candidate_artifact_path", "series_packet_path", "summary_path", "generated_at", "confirm_user_authorization"]),
            (st._sic.run_fetch, ["candidate_artifact_path", "classification_packet_path", "summary_path", "generated_at", "confirm_user_authorization"]),
            (st._pass2.run_full_candidate_live_source_packet, ["preflight_summary_path", "expected_total_call_budget", "source_artifact_prefix", "context_components_output_path", "summary_path", "confirm_user_authorization", "run_data_context", "generated_at", "observed_at", "provider_pace_seconds", "max_retries_per_call", "retry_backoff_seconds"]),
            (st._mom_prod.run_packet, ["candidate_artifact_path", "series_packet_path", "output_projection_path", "summary_path", "generated_at"]),
            (st._theme.run_packet, ["candidate_artifact_path", "series_packet_path", "classification_packet_path", "output_projection_path", "summary_path", "generated_at"]),
            (st._proj.run_packet, ["candidate_artifact_path", "expected_decision_date", "source_momentum_projection_path", "source_theme_projection_path", "output_momentum_projection_path", "output_theme_projection_path", "summary_path", "generated_at"]),
            (st._preflight.run_preflight, ["candidate_artifact_path", "expected_decision_date", "momentum_projection_path", "theme_projection_path", "summary_path", "confirm_user_authorization", "generated_at"]),
            (st._bridge.run_e2e, ["source_packet_path", "batch4_template_path", "account_state_path", "provider_health_path", "private_root", "now_et", "context_components_path", "run_mode", "bootstrap_lifecycle", "generated_at"]),
        ]
        for fn, kwargs in checks:
            params = set(inspect.signature(fn).parameters)
            bad = [k for k in kwargs if k not in params]
            self.assertEqual(bad, [], f"{fn.__module__}.{fn.__name__} rejects kwargs {bad}")


if __name__ == "__main__":
    unittest.main()
