"""P3 final-action validation: source binding, no-counts and public isolation."""
from __future__ import annotations

import csv
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_managed_exit import (  # noqa: E402
    ManagedExitError,
    ROUND_TRIP_COST_FRACTION,
    net_excess_after_round_trip_cost_pct,
)
from runners.a_short_final_action_validation_runner import (  # noqa: E402
    FinalActionValidationError,
    ROUND_TRIP_COST_PCT,
    _contract_fingerprint,
    _freeze_plan as freeze_p3_plan,
    _load_or_initialize,
    _summary_from_ledger,
    capture_after_published_weekly,
    settle_and_summarize,
    validate_public_summary,
)
from runners.a_short_phase5_engine import ATR_MULT  # noqa: E402
from runners.a_short_target_policy_comparison_runner import _freeze_plan as freeze_p2_plan  # noqa: E402
from engine import a_short_evidence_epoch_mode as _epoch_mode
from tests._a_short_epoch_mode_test_utils import enter_patched_epoch_modes, patched_epoch_modes


AS_OF = "20260101"
IDENTITY = {"run_id": "run-1", "candidate_digest": "candidate-digest"}
PLAN = {"entry_low": 9.9, "entry_high": 10.5, "stop": 9.0, "t1": 12.0, "t2": 14.0}


def _candidate(code: str) -> dict:
    return {
        "ts_code": code,
        "market_regime": "震荡期",
        "price_series": [{"trade_date": AS_OF, "high": 10.2, "low": 9.8, "close": 10.0}],
    }


def _tracker(path: Path) -> None:
    fields = ["as_of", "run_id", "candidate_digest", "ts_code", "forward_live",
              "ret_5d_t1_net", "ret_5d_excess_csi1000", "ret_5d_status",
              "ret_10d_t1_net", "ret_10d_excess_csi1000", "ret_10d_status",
              "ret_20d_t1_net", "ret_20d_excess_csi1000", "ret_20d_status"]
    rows = [
        {"as_of": AS_OF, "run_id": "run-1", "candidate_digest": "candidate-digest", "ts_code": "600000.SH",
         "forward_live": "True", "ret_5d_t1_net": "10.0", "ret_5d_excess_csi1000": "3.0", "ret_5d_status": "ok",
         "ret_10d_t1_net": "10.0", "ret_10d_excess_csi1000": "3.0", "ret_10d_status": "ok",
         "ret_20d_t1_net": "10.0", "ret_20d_excess_csi1000": "3.0", "ret_20d_status": "ok"},
        {"as_of": AS_OF, "run_id": "run-1", "candidate_digest": "candidate-digest", "ts_code": "600001.SH",
         "forward_live": "True", "ret_5d_t1_net": "4.0", "ret_5d_excess_csi1000": "-3.0", "ret_5d_status": "ok",
         "ret_10d_t1_net": "4.0", "ret_10d_excess_csi1000": "-3.0", "ret_10d_status": "ok",
         "ret_20d_t1_net": "4.0", "ret_20d_excess_csi1000": "-3.0", "ret_20d_status": "ok"},
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _execution_rows() -> list[dict]:
    rows = [{"trade_date": AS_OF, "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0,
             "volume": 1000, "raw_close": 10.0, "adj_factor": 1.0, "up_limit": 11.0, "down_limit": 9.0}]
    for day in range(2, 22):
        rows.append({"trade_date": f"202601{day:02d}", "open": 10.0, "high": 10.4, "low": 9.9,
                     "close": 10.1, "volume": 1000, "raw_close": 10.1, "adj_factor": 1.0,
                     "up_limit": 11.1, "down_limit": 9.1})
    return rows


def _execution_rows_with_stale_unverified_action() -> list[dict]:
    stale = {"trade_date": "20251130", "open": None, "high": None, "low": None, "close": None,
             "volume": 1000, "raw_close": None, "adj_factor": None, "up_limit": None, "down_limit": None}
    history = [
        {"trade_date": f"202512{day:02d}", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0,
         "volume": 1000, "raw_close": 10.0, "adj_factor": 1.0, "up_limit": 11.0, "down_limit": 9.0}
        for day in range(1, 21)
    ]
    return [stale, *history, *_execution_rows()]


class FinalActionValidationTests(unittest.TestCase):
    def setUp(self):
        # These cases assert the ENFORCED epoch contract (the historical default).
        # Pre-freeze behaviour is covered by tests/test_a_short_evidence_epoch_mode.py.
        enter_patched_epoch_modes(self, "frozen_enforced")

    def test_threshold_evidence_keeps_all_reminders_accumulating_pre_freeze_then_rearms(self):
        records = [
            {"decision_date": "20250101", "forward_eligible": True, "conflict": False,
             "hold_result": {"status": "settled", "selected_minus_pool_pct": 1.0,
                             "selected_minus_csi1000_pct": 1.0},
             "full_edge_result": {"status": "settled", "managed_minus_simple_hold_pct": 1.0,
                                  "managed_minus_csi1000_pct": 1.0, "managed_plan_count": 1}}
            for _ in range(26)
        ]
        def ledger_for_current_mode():
            return {"epochs": [{"contract_fingerprint": _contract_fingerprint(), "records": records}]}

        with patched_epoch_modes("pre_freeze_audit_only"):
            audit_only = _summary_from_ledger(ledger_for_current_mode(), "20260102")
        self.assertEqual(audit_only["status"], "accumulating")
        self.assertTrue(all(row["status"] == "accumulating" for row in audit_only["reminders"]))

        with patched_epoch_modes("frozen_enforced"):
            enforced = _summary_from_ledger(ledger_for_current_mode(), "20260102")
        self.assertEqual(enforced["status"], "review_due")
        self.assertEqual([row["status"] for row in enforced["reminders"][:4]], ["review_due"] * 4)

    def test_forward_tracker_runtime_drift_opens_a_new_epoch(self):
        """A code change upstream opens a new epoch; a comment there must not.

        P3 now binds its dependencies through the shared AST contract, so the
        drift probe edits the checked-in source rather than `inspect.getsource`.
        """
        import ast
        import tempfile
        from engine import a_short_evidence_epoch_mode as epoch_mode
        from runners import forward_tracker

        baseline = _contract_fingerprint()
        real_source = Path(forward_tracker.__file__).read_text(encoding="utf-8")
        tree = ast.parse(real_source)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "capture":
                node.body.insert(0, ast.parse("_adversarial_drift = 1").body[0])
                break
        else:  # pragma: no cover - `capture` must stay a bound top-level function
            self.fail("forward_tracker.capture is no longer a top-level function")
        variants = {
            "code": ast.unparse(ast.fix_missing_locations(tree)),
            "comment": "# adversarial comment-only edit\n" + real_source,
        }
        original_getsourcefile = epoch_mode.inspect.getsourcefile
        with tempfile.TemporaryDirectory() as temp:
            for kind, source_text in variants.items():
                path = Path(temp) / f"forward_tracker_{kind}.py"
                path.write_text(source_text, encoding="utf-8")

                def redirected(module, _path=path):
                    if getattr(module, "__name__", "") == "runners.forward_tracker":
                        return str(_path)
                    return original_getsourcefile(module)

                with patch.object(epoch_mode.inspect, "getsourcefile", redirected):
                    if kind == "code":
                        self.assertNotEqual(_contract_fingerprint(), baseline)
                    else:
                        self.assertEqual(_contract_fingerprint(), baseline)

    def _bundle(self, directory: Path) -> tuple[Path, Path, list[dict]]:
        weekly = {
            "as_of": AS_OF,
            "run_lineage": {"run_id": "run-1", "candidate_digest": "candidate-digest",
                            "price_freshness": {"mode": "intraday_prior_settled", "run_date": AS_OF,
                                                "price_data_through": AS_OF}},
            "reports": [
                {"ts_code": "600000.SH", "row_source": "egs_candidate",
                 "machine": {"model_build_eligible": True, "entry_exit_size_star": {"plan": PLAN}}},
                {"ts_code": "600001.SH", "row_source": "egs_candidate",
                 "machine": {"model_build_eligible": False, "entry_exit_size_star": {"plan": PLAN}}},
            ],
        }
        out = directory / "weekly.json"
        out.write_text(json.dumps(weekly), encoding="utf-8")
        out.with_suffix(".md").write_text("# weekly\n", encoding="utf-8")
        receipt = directory / "receipt.json"
        receipt.write_text(json.dumps({"stage_status": "complete", "as_of": AS_OF, **IDENTITY}), encoding="utf-8")
        return out, receipt, [_candidate("600000.SH"), _candidate("600001.SH")]

    def test_hold_and_full_edge_are_weekly_equal_weighted_and_public_is_deidentified(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            out, receipt, candidates = self._bundle(directory)
            tracker = directory / "forward_tracker.csv"
            _tracker(tracker)
            ledger, public, markdown = directory / "ledger.json", directory / "summary.json", directory / "summary.md"
            captured = capture_after_published_weekly(
                root=ledger, decision_date=AS_OF, candidates=candidates, source_identity=IDENTITY,
                out_path=out, receipt_path=receipt, forward_eligible=True, tracker_path=tracker,
                summary_path=public, markdown_path=markdown)
            self.assertEqual(captured["status"], "captured")
            first = json.loads(public.read_text(encoding="utf-8"))
            validate_public_summary(first)
            self.assertEqual(first["hold_based"]["forward_weeks"], 1)
            self.assertEqual(first["full_edge"]["forward_weeks"], 0)
            self.assertAlmostEqual(first["hold_based"]["selection_minus_pool"]["mean_pct"], 3.0)
            self.assertAlmostEqual(first["hold_based"]["selection_minus_csi1000"]["mean_pct"], 2.84)
            self.assertNotIn("600000.SH", public.read_text(encoding="utf-8"))
            self.assertNotIn("600001.SH", public.read_text(encoding="utf-8"))

            cache = directory / "execution_cache.json"
            cache.write_text(json.dumps({"rows": [dict(row, ts_code="600000.SH")
                                                   for row in _execution_rows_with_stale_unverified_action()]}),
                             encoding="utf-8")
            settled = settle_and_summarize(root=ledger, as_of=AS_OF, tracker_path=tracker,
                                           daily_cache_path=cache, summary_path=public, markdown_path=markdown)
            self.assertEqual(settled["full_edge"]["forward_weeks"], 1)
            self.assertEqual(settled["full_edge"]["managed_plan_count"], 1)

    def test_p2_and_p3_freeze_same_atr_plan_for_every_runtime_regime(self):
        series = _candidate("600000.SH")["price_series"]
        for regime, multiplier in ATR_MULT.items():
            with self.subTest(regime=regime):
                p3 = freeze_p3_plan(PLAN, series, AS_OF, regime)
                p2 = freeze_p2_plan(PLAN, series, AS_OF, regime, t1=PLAN["t1"], t2=PLAN["t2"])
                self.assertEqual(p3, p2)
                self.assertEqual(p3["atr_multiplier"], multiplier)
        self.assertAlmostEqual(ROUND_TRIP_COST_PCT, ROUND_TRIP_COST_FRACTION * 100.0)

    def test_market_net_excess_deducts_cost_once_and_rejects_nonfinite_input(self):
        self.assertAlmostEqual(net_excess_after_round_trip_cost_pct(3.0), 2.84)
        with self.assertRaises(ManagedExitError):
            net_excess_after_round_trip_cost_pct("nan")

    def test_mature_source_change_is_conflict_and_never_recounted(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            out, receipt, candidates = self._bundle(directory)
            tracker = directory / "forward_tracker.csv"
            _tracker(tracker)
            ledger = directory / "ledger.json"
            capture_after_published_weekly(root=ledger, decision_date=AS_OF, candidates=candidates,
                                           source_identity=IDENTITY, out_path=out, receipt_path=receipt,
                                           forward_eligible=True, tracker_path=tracker,
                                           summary_path=directory / "summary.json", markdown_path=directory / "summary.md")
            weekly = json.loads(out.read_text(encoding="utf-8"))
            weekly["reports"][0]["machine"]["entry_exit_size_star"]["plan"]["t1"] = 13.0
            out.write_text(json.dumps(weekly), encoding="utf-8")
            replay = capture_after_published_weekly(root=ledger, decision_date=AS_OF, candidates=candidates,
                                                    source_identity=IDENTITY, out_path=out, receipt_path=receipt,
                                                    forward_eligible=True, tracker_path=tracker,
                                                    summary_path=directory / "summary.json", markdown_path=directory / "summary.md")
            self.assertEqual(replay["status"], "conflict")
            self.assertEqual(json.loads((directory / "summary.json").read_text(encoding="utf-8"))
                             ["hold_based"]["forward_weeks"], 0)
            summary = settle_and_summarize(root=ledger, as_of=AS_OF, tracker_path=tracker,
                                            summary_path=directory / "summary.json", markdown_path=directory / "summary.md")
            self.assertEqual(summary["hold_based"]["forward_weeks"], 0)

    def test_old_epoch_is_diagnostic_only_and_rebound_capture_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            out, receipt, candidates = self._bundle(directory)
            tracker = directory / "forward_tracker.csv"
            _tracker(tracker)
            ledger, public, markdown = directory / "ledger.json", directory / "summary.json", directory / "summary.md"
            capture_after_published_weekly(
                root=ledger, decision_date=AS_OF, candidates=candidates, source_identity=IDENTITY,
                out_path=out, receipt_path=receipt, forward_eligible=True, tracker_path=tracker,
                summary_path=public, markdown_path=markdown)
            original = json.loads(ledger.read_text(encoding="utf-8"))
            rebound = json.loads(json.dumps(original))
            rebound["epochs"][0]["contract_fingerprint"] = "f" * 64
            rebound["epochs"][0]["records"][0]["epoch_fingerprint"] = "f" * 64
            # The copied evidence cannot be made current merely by changing its
            # public epoch fields: capture_sha256 binds the original epoch input.
            ledger.write_text(json.dumps(rebound), encoding="utf-8")
            with patch("runners.a_short_final_action_validation_runner._contract_fingerprint", return_value="f" * 64):
                with self.assertRaises(FinalActionValidationError):
                    _load_or_initialize(ledger)

            ledger.write_text(json.dumps(original), encoding="utf-8")
            with patch("runners.a_short_final_action_validation_runner._contract_fingerprint", return_value="e" * 64):
                summary = settle_and_summarize(root=ledger, as_of=AS_OF, tracker_path=tracker,
                                                summary_path=public, markdown_path=markdown)
            self.assertEqual(summary["hold_based"]["forward_weeks"], 0)
            self.assertEqual(summary["full_edge"]["forward_weeks"], 0)

    def test_p3b_reminder_counts_only_complete_external_public_verdicts(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            invalid, valid = directory / "invalid.json", directory / "valid.json"
            invalid.write_text(json.dumps({
                "verdict": "edge_positive", "progress": {}, "fingerprint": "g" * 64,
                "as_of": AS_OF, "source_hash": "a" * 64,
            }), encoding="utf-8")
            valid.write_text(json.dumps({
                "verdict": "edge_positive", "progress": {}, "fingerprint": "b" * 64,
                "as_of": AS_OF, "source_hash": "c" * 64,
            }), encoding="utf-8")
            with patch("runners.a_short_final_action_validation_runner.P3B_EXTERNAL_PUBLIC_SUMMARIES",
                       (invalid, valid)):
                from runners.a_short_final_action_validation_runner import _valid_external_public_verdicts
                self.assertEqual(_valid_external_public_verdicts(), 0)
