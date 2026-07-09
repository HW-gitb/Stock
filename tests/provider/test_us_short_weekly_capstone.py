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

    def _fake_stages(self, order_sink, *, break_stage=None, skip_output_stage=None, bridge_batch4=None):
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
                    if nm == "weekly_bridge" and bridge_batch4 is not None:
                        return {"batch4_run": bridge_batch4}   # exercise the real bridge return shape (emitted/no_emit_reason)
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
            sample_root=self.state_dir,   # keep the preflight provider_samples sidecar inside the tempdir (isolation)
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
            (st._pass2.run_full_candidate_live_source_packet, ["preflight_summary_path", "expected_total_call_budget", "source_artifact_prefix", "context_components_output_path", "output_data_context_path", "summary_path", "confirm_user_authorization", "run_data_context", "generated_at", "observed_at", "provider_pace_seconds", "max_retries_per_call", "retry_backoff_seconds"]),
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
            "sic_classification": st._sic._validate_summary_path,
            "theme_producer": st._theme._validate_summary_path,
            "projection_inputs": st._proj._validate_summary_path,
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
    derivation). A source reads 'ok' only if its success COVERAGE over attempted calls is >= _HEALTH_MIN_SUCCESS_COVERAGE
    (item 2, option a) — this closed the earlier any-single-success (grades) / attempted-only (sec) leniencies."""

    def _derive(self, endpoint_results, budget):
        import json
        from types import SimpleNamespace

        from runners import us_short_weekly_capstone_stages as st
        tmp = Path(tempfile.mkdtemp(prefix="cap_health_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ctx = SimpleNamespace(sample_root=tmp, decision_date="20260710",
                              provider_health_path=tmp / "provider_health.json")
        summ = st._stage_summary_targets(ctx)["pass2"]
        summ.parent.mkdir(parents=True, exist_ok=True)
        summ.write_text(json.dumps({"endpoint_call_budget": budget, "endpoint_results": endpoint_results}),
                        encoding="utf-8")
        st._write_provider_health(ctx)
        return json.loads(ctx.provider_health_path.read_text(encoding="utf-8"))

    @staticmethod
    def _row(provider, family, ok):
        return {"provider_id": provider, "endpoint_family": family, "status": "success" if ok else "error"}

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
        # old any-single-success leniency). A near-zero-coverage grades run now correctly NO-EMITs.
        rows = ([self._row("financial_modeling_prep", "grades", True)]
                + [self._row("financial_modeling_prep", "grades", False) for _ in range(199)]
                + [self._row("sec_edgar", "submissions", True)])
        health = self._derive(rows, {"fmp_grades_calls": 200, "sec_submissions_calls": 1, "endpoint_error_count": 199})
        self.assertEqual(health["fmp"], "down")

    def test_sec_no_calls_is_down(self):
        # sec_ok = any-sec-success OR sec_submissions_calls>0; zero sec calls and no success -> down.
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

    def test_coverage_exactly_at_threshold_is_ok(self):
        # boundary: successes/attempted == threshold (0.5) is INCLUSIVE (>=) -> ok, for both legs.
        rows = ([self._row("financial_modeling_prep", "grades", i < 5) for i in range(10)]
                + [self._row("sec_edgar", "submissions", i < 5) for i in range(10)])
        health = self._derive(rows, {"fmp_grades_calls": 10, "sec_submissions_calls": 10, "endpoint_error_count": 10})
        self.assertEqual(health, {"fmp": "ok", "sec_edgar": "ok"})

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
