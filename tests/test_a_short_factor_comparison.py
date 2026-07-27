"""D1/D3 private comparison track: frozen heads, forward-only settlement, no auto switch."""
from __future__ import annotations

import sys
import tempfile
import unittest
import json
import os
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_factor_comparison import (  # noqa: E402
    FACTOR_IDS, _evaluate, _holm_bonferroni, _iv_policy, _nonoverlap_blocks, build_realized_regime,
    capture_week, load_governance, settle_from_daily_payload, unavailable_realized_regime,
)
from runners.a_short_factor_comparison import _settlement_cache_required  # noqa: E402


def _root(tmp: str) -> Path:
    return Path(tmp) / "state" / "a_short" / "factor_comparison_private"


def _candidate(code="600000.SH", *, iv_pct=50.0, iv_value=0.2, hv_value=0.18, breakout=False) -> dict:
    series = []
    for index in range(30):
        close = 10.5 if index >= 20 else 10.2
        high = (21.0 if breakout else 15.0) if index in (22, 27) else close + 0.2
        low = 9.7 if index in (21, 26) else close - 0.2
        series.append({"trade_date": "20260202", "high": high, "low": low, "close": close})
    return {
        "ts_code": code, "name": code, "close": 10.5, "price_series": series,
        "egs_score": 90.0, "derived": {"breakout": breakout}, "event": {},
        "liquidity": {"avg_amount_5d": 1e9},
        "iv": {"iv_percentile_252d": iv_pct, "iv_value": iv_value, "hv_value": hv_value},
        "market_regime": "进攻期", "regime_fallback": {}, "stateful_risk": {},
    }


def _daily_payload(codes: list[str]) -> dict:
    dates = ["20260202"] + [f"202602{day:02d}" for day in range(3, 28)]
    rows = []
    for code in codes:
        for index, day in enumerate(dates):
            rows.append({"ts_code": code, "trade_date": day, "open": 10.3 + index * 0.05,
                         "close": 10.5 + index * 0.08, "adj_factor": 1.0})
    return {
        "stocks": pd.DataFrame(rows),
        "limits": pd.DataFrame(columns=["ts_code", "trade_date", "up_limit", "down_limit"]),
        "benchmarks": {},
    }


def _realized_regime(*, daily_return=0.003) -> dict:
    current = date(2026, 1, 5)
    rows = []
    close = 100.0
    while len(rows) < 21:
        if current.weekday() < 5:
            rows.append({"trade_date": current.strftime("%Y%m%d"), "close": close})
            close *= 1.0 + daily_return
        current += timedelta(days=1)
    return build_realized_regime(rows, decision_date="20260202", governance=load_governance())


def _write_evaluation_day(root: Path, decision: date, *, effect: float, label: str) -> None:
    day = root / decision.strftime("%Y%m%d")
    day.mkdir(parents=True)
    exit_date = (decision + timedelta(days=10)).strftime("%Y%m%d")
    manifest = {
        "forward_eligible": True,
        "comparison_realized_regime": {"status": "available", "label": label},
    }
    baseline = {"selection": {"selected_symbols": ["600000.SH"]},
                "outcome": {"horizons": {"h10": {"status": "settled", "net_return_pct": 0.0,
                                                     "bad_name_rate": 0.0, "evaluation_exit_date": exit_date}}}}
    factor = {"selection": {"selected_symbols": ["600001.SH"]},
              "outcome": {"horizons": {"h10": {"status": "settled", "net_return_pct": effect,
                                                   "bad_name_rate": 0.0, "evaluation_exit_date": exit_date}}}}
    (day / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (day / "baseline_result.json").write_text(json.dumps(baseline), encoding="utf-8")
    (day / "factor_entry_ma_pullback.json").write_text(json.dumps(factor), encoding="utf-8")


class CapturePolicyTests(unittest.TestCase):
    def test_registry_is_exact_and_iv_step_down_changes_only_iv_hard_gate(self):
        governance = load_governance()
        self.assertEqual(tuple(row["factor_id"] for row in governance["factor_registry"]), FACTOR_IDS)
        with tempfile.TemporaryDirectory() as tmp:
            result = capture_week(
                root=_root(tmp), decision_date="20260202",
                candidates=[_candidate(iv_pct=95.0, breakout=True)],
                run_identity={"run_id": "r1", "candidate_digest": "d1"}, forward_eligible=True,
                realized_regime=_realized_regime(),
            )
            day = Path(result["day"])
            baseline = __import__("json").loads((day / "baseline_result.json").read_text(encoding="utf-8"))
            step = __import__("json").loads((day / "factor_iv_step_down.json").read_text(encoding="utf-8"))
            joint = __import__("json").loads((day / "factor_iv_joint_stress.json").read_text(encoding="utf-8"))
            self.assertEqual(baseline["selection"]["decisions"][0]["status"], "hard_veto")
            self.assertEqual(step["selection"]["decisions"][0]["status"], "eligible")
            self.assertEqual(joint["selection"]["decisions"][0]["status"], "eligible")
            self.assertFalse(step["boundary"]["automatic_policy_switch"])

    def test_joint_stress_keeps_the_hard_gate_when_iv_hv_is_independently_stressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = capture_week(
                root=_root(tmp), decision_date="20260202",
                candidates=[_candidate(iv_pct=95.0, iv_value=0.30, hv_value=0.20, breakout=True)],
                run_identity={"run_id": "r2", "candidate_digest": "d2"}, forward_eligible=True,
                realized_regime=_realized_regime(),
            )
            day = Path(result["day"])
            joint = __import__("json").loads((day / "factor_iv_joint_stress.json").read_text(encoding="utf-8"))
            self.assertEqual(joint["selection"]["decisions"][0]["status"], "hard_veto")

    def test_iv_variants_never_relax_the_independent_contraction_hard_gate(self):
        candidate = _candidate(iv_pct=95.0, breakout=True)
        candidate["market_regime"] = "收缩期"
        factor_by_id = {row["factor_id"]: row for row in load_governance()["factor_registry"]}
        for factor_id in ("iv_step_down", "iv_joint_stress"):
            self.assertFalse(_iv_policy(candidate, factor_id, factor_by_id[factor_id], _realized_regime())["relax_iv_hard"])
        with tempfile.TemporaryDirectory() as tmp:
            result = capture_week(
                root=_root(tmp), decision_date="20260202", candidates=[candidate],
                run_identity={"run_id": "r2b", "candidate_digest": "d2b"}, forward_eligible=True,
                realized_regime=_realized_regime(),
            )
            day = Path(result["day"])
            for filename in ("factor_iv_step_down.json", "factor_iv_joint_stress.json"):
                payload = __import__("json").loads((day / filename).read_text(encoding="utf-8"))
                decision = payload["selection"]["decisions"][0]
                self.assertEqual(decision["status"], "hard_veto")

    def test_unavailable_realized_context_keeps_iv_joint_fail_closed(self):
        governance = load_governance()
        with tempfile.TemporaryDirectory() as tmp:
            result = capture_week(
                root=_root(tmp), decision_date="20260202", candidates=[_candidate(iv_pct=95.0, breakout=True)],
                run_identity={"run_id": "r2c", "candidate_digest": "d2c"}, forward_eligible=True,
                realized_regime=unavailable_realized_regime(governance, "test"),
            )
            payload = json.loads((Path(result["day"]) / "factor_iv_joint_stress.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["selection"]["decisions"][0]["status"], "hard_veto")

    def test_realized_regime_is_independent_of_production_regime_and_rejects_future_rows(self):
        regime = _realized_regime()
        self.assertEqual(regime["label"], "trend_up_vol_low")
        future = [{"trade_date": "20260203", "close": 100.0}]
        with self.assertRaises(ValueError):
            build_realized_regime(future, decision_date="20260202", governance=load_governance())

    def test_same_day_is_idempotent_but_changed_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            kwargs = dict(root=root, decision_date="20260202", candidates=[_candidate()],
                          run_identity={"run_id": "r3", "candidate_digest": "d3"}, forward_eligible=True,
                          realized_regime=_realized_regime())
            self.assertEqual(capture_week(**kwargs)["status"], "captured")
            self.assertEqual(capture_week(**kwargs)["status"], "already_captured")
            altered = dict(kwargs)
            altered["candidates"] = [_candidate(iv_pct=81.0)]
            with self.assertRaises(ValueError):
                capture_week(**altered)


class ForwardSettlementTests(unittest.TestCase):
    def test_settlement_counts_only_live_divergence_and_emits_no_auto_switch(self):
        # Baseline has no low-absorption entry; the MA-pullback head does, so this is a genuine D1 difference.
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            captured = capture_week(
                root=root, decision_date="20260202", candidates=[_candidate()],
                run_identity={"run_id": "r4", "candidate_digest": "d4"}, forward_eligible=True,
                realized_regime=_realized_regime(),
            )
            settled = settle_from_daily_payload(root=root, daily_payload=_daily_payload(["600000.SH"]))
            summary = __import__("json").loads((Path(captured["day"]) / "weekly_summary.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["factor_summaries"]["entry_ma_pullback"]["selection_diverged"])
            self.assertIsNotNone(summary["factor_summaries"]["entry_ma_pullback"]["paired_net_excess_h10_pct"])
            verdict = settled["verdicts"]["verdicts"]["entry_ma_pullback"]
            self.assertEqual(verdict["effective_difference_weeks"], 1)
            self.assertEqual(verdict["status"], "accumulating")
            self.assertFalse(verdict["automatic_production_switch"])

    def test_historical_snapshot_never_advances_the_forward_evidence_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            capture_week(
                root=root, decision_date="20260202", candidates=[_candidate()],
                run_identity={"run_id": "r5", "candidate_digest": "d5"}, forward_eligible=False,
                realized_regime=_realized_regime(),
            )
            settled = settle_from_daily_payload(root=root, daily_payload=_daily_payload(["600000.SH"]))
            verdict = settled["verdicts"]["verdicts"]["entry_ma_pullback"]
            self.assertEqual(verdict["effective_difference_weeks"], 0)
            self.assertEqual(verdict["status"], "accumulating")

    def test_production_or_nonprivate_result_root_is_rejected(self):
        with self.assertRaises(ValueError):
            capture_week(root=ROOT / "result" / "a_short", decision_date="20260202", candidates=[_candidate()],
                         run_identity={"run_id": "r6", "candidate_digest": "d6"}, forward_eligible=True,
                         realized_regime=_realized_regime())


class VerdictStatisticsTests(unittest.TestCase):
    def _verdict(self, *, effect: float, labels: list[str]):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            start = date(2024, 1, 1)
            for index in range(36):
                _write_evaluation_day(root, start + timedelta(days=14 * index), effect=effect,
                                      label=labels[index % len(labels)])
            verdicts, _ = _evaluate(root, load_governance())
            return verdicts["verdicts"]["entry_ma_pullback"]

    def test_nonoverlap_and_holm_cover_all_four_heads(self):
        rows = [
            {"decision_date": "20260102", "evaluation_exit_date": "20260116"},
            {"decision_date": "20260109", "evaluation_exit_date": "20260123"},
            {"decision_date": "20260123", "evaluation_exit_date": "20260206"},
        ]
        self.assertEqual([row["decision_date"] for row in _nonoverlap_blocks(rows)], ["20260102", "20260123"])
        adjusted = _holm_bonferroni({"a": 0.01, "b": None, "c": None, "d": None})
        self.assertEqual(adjusted["a"], 0.04)

    def test_two_independent_contexts_can_reach_adopt_path(self):
        verdict = self._verdict(effect=1.0, labels=["trend_up_vol_low", "trend_flat_vol_low"])
        self.assertEqual(verdict["status"], "recommend_adopt_change")
        self.assertEqual(verdict["nonoverlap_blocks"], 36)
        self.assertLessEqual(verdict["holm_bonferroni_adjusted_pvalue"], 0.05)

    def test_single_context_never_turns_good_effect_into_retire(self):
        verdict = self._verdict(effect=1.0, labels=["trend_up_vol_low"])
        self.assertEqual(verdict["status"], "inconclusive")

    def test_reliable_harm_can_retire_after_36_weeks(self):
        verdict = self._verdict(effect=-1.0, labels=["trend_up_vol_low", "trend_flat_vol_low"])
        self.assertEqual(verdict["status"], "recommend_retire_head")


class DirectRunnerInvocationTests(unittest.TestCase):
    def test_future_forward_snapshot_does_not_require_a_price_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            day = root / "20260720"
            day.mkdir(parents=True)
            (day / "manifest.json").write_text(json.dumps({
                "decision_date": "20260720", "forward_eligible": True,
            }), encoding="utf-8")
            (day / "baseline_result.json").write_text(json.dumps({
                "outcome": {"status": "pending_forward"},
            }), encoding="utf-8")
            required, reason = _settlement_cache_required(root, "20260718")
            self.assertFalse(required)
            self.assertIn("future-dated", reason)

    def test_past_pending_forward_snapshot_still_requires_a_price_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            day = root / "20260714"
            day.mkdir(parents=True)
            (day / "manifest.json").write_text(json.dumps({
                "decision_date": "20260714", "forward_eligible": True,
            }), encoding="utf-8")
            (day / "baseline_result.json").write_text(json.dumps({
                "outcome": {"status": "pending_forward"},
            }), encoding="utf-8")
            required, reason = _settlement_cache_required(root, "20260718")
            self.assertTrue(required)
            self.assertIn("may need settlement", reason)

    def test_settler_direct_script_invocation_bootstraps_project_root(self):
        """The weekly PowerShell entry invokes this file directly, not as -m."""
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            env["PYTHONIOENCODING"] = "utf-8"   # GOV-R6: pin both ends, never the ambient locale
            root = _root(tmp)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "runners" / "a_short_factor_comparison.py"),
                    "settle",
                    "--root",
                    str(root),
                    "--cache",
                    str(Path(tmp) / "missing_forward_daily.pkl"),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("no frozen comparison snapshots", completed.stdout)


if __name__ == "__main__":
    unittest.main()
