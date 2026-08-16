"""P2 true-pressure, shared-exit, and shadow-ledger regression tests."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_managed_exit import evaluate_managed_exit  # noqa: E402
from engine import a_short_managed_exit as managed_exit  # noqa: E402
from runners import a_short_phase5_engine as phase5_engine  # noqa: E402
from runners.a_short_phase5_engine import build_true_pressure_targets  # noqa: E402
from runners.a_short_target_policy_comparison_runner import (  # noqa: E402
    TargetPolicyError,
    _active_epoch,
    _capture_digest,
    _contract_fingerprint,
    _new_ledger,
    _progress,
    _render_summary_markdown,
    _summary_from_ledger,
    _validate_ledger,
    capture_after_published_weekly,
    settle_and_summarize,
    validate_public_summary,
    write_public_summary,
)
from runners.a_short_weekly_pipeline import build_weekly_report, validate_weekly_report  # noqa: E402
from runners.a_short_m67_render import render_weekly_markdown  # noqa: E402
from tests.test_a_short_weekly_pipeline import _feed, _normalized  # noqa: E402
from engine import a_short_evidence_epoch_mode as _epoch_mode
from tests._a_short_epoch_mode_test_utils import enter_patched_epoch_modes, patched_epoch_modes
from tests._a_short_weekly_publish_test_utils import write_content_bound_bundle


def _dated_series(days: int = 253, *, spike: bool = False) -> list[dict]:
    start = date(2025, 4, 24)  # 253 calendar rows end on 2026-01-01 for cache fixtures below.
    rows = []
    for index in range(days):
        trade_date = (start + timedelta(days=index)).strftime("%Y%m%d")
        high = 10.2
        if index in (days - 62, days - 61):
            high = 12.0
        if spike and index == days - 10:
            high = 15.0
        rows.append({"trade_date": trade_date, "high": high, "low": 9.8, "close": 10.0})
    rows[-1] = {"trade_date": rows[-1]["trade_date"], "high": 12.6, "low": 10.0, "close": 12.5}
    return rows


def _candidate(series: list[dict]) -> dict:
    return {
        "ts_code": "600000.SH",
        "close": series[-1]["close"],
        "price_series": series,
        "derived": {"breakout": True},
        "market_regime": "震荡期",
    }


def _official_plan() -> dict:
    return {"entry_low": 10.0, "entry_high": 10.5, "stop": 9.9, "t1": 13.0, "t2": 14.0,
            "t1_basis": "rr_floor_fallback"}


def _execution_rows(*, stop_on_day: int | None = None) -> list[dict]:
    rows = [{"trade_date": "20260101", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.0,
             "volume": 1000, "raw_close": 10.0, "adj_factor": 1.0, "up_limit": 11.0, "down_limit": 9.0}]
    for day in range(1, 21):
        trade_date = f"202601{day + 1:02d}"
        row = {"trade_date": trade_date, "open": 10.0, "high": 10.4, "low": 9.9, "close": 10.1,
               "volume": 1000, "raw_close": 10.1, "adj_factor": 1.0, "up_limit": 11.1, "down_limit": 9.1}
        if day == 2:
            row.update(high=12.2, low=10.1, close=12.0, raw_close=12.0, up_limit=13.2, down_limit=10.8)
        elif day > 2:
            row.update(open=12.0, high=12.4, low=11.8, close=12.1, raw_close=12.1,
                       up_limit=13.3, down_limit=10.9)
        if stop_on_day == day:
            row.update(high=13.0, low=8.5, close=9.0, raw_close=9.0, up_limit=9.9, down_limit=8.1)
        rows.append(row)
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


def _managed_plan() -> dict:
    return {"decision_date": "20260101", "entry_low": 9.9, "entry_high": 10.5, "stop": 9.0,
            "t1": 12.0, "t2": 14.0, "atr_multiplier": 1.25, "price_basis": "qfq",
            "reference_trade_date": "20260101", "reference_close": 10.0}


class TruePressureTests(unittest.TestCase):
    def test_true_breakout_targets_are_prior_bar_only_and_clustered(self):
        series = _dated_series(spike=True)
        ladder = build_true_pressure_targets(_candidate(series), _official_plan(), series[-1]["trade_date"])
        self.assertTrue(ladder["true_breakout"])
        self.assertEqual(ladder["status"], "available")
        self.assertEqual(ladder["t1"]["price"], 12.0)  # 15.0 one-day spike was despiked.
        self.assertEqual(ladder["t1"]["price_basis"], "qfq")
        self.assertIsNone(ladder["t2"])                 # 20/60/120/252 duplicates are one zone.
        self.assertGreaterEqual(ladder["history_bars"], 252)
        self.assertTrue(all(item["source_date"] < series[-1]["trade_date"]
                            for item in ladder["t1"]["cluster_sources"]))

    def test_no_upper_pressure_needs_252_history_before_trailing_only(self):
        series = _dated_series(days=100)
        for row in series[:-1]:
            row["high"] = 10.2
        ladder = build_true_pressure_targets(_candidate(series), _official_plan(), series[-1]["trade_date"])
        self.assertEqual(ladder["status"], "unavailable")
        self.assertEqual(ladder["reason"], "insufficient_history_to_clear_upper_pressure")

    def test_lone_swing_without_window_or_second_touch_is_not_formal_target(self):
        series = _dated_series()
        for row in series[:-1]:
            row.update(high=10.2, low=9.8, close=10.0)
        series[-15]["high"] = series[-13]["high"] = 15.0  # repeated formal window pressure
        series[-33]["high"] = 12.0  # one confirmed swing, but never a window high
        ladder = build_true_pressure_targets(_candidate(series), _official_plan(), series[-1]["trade_date"])
        lone_swing_zone = next(zone for zone in ladder["zones"] if zone["price"] == 12.0)
        self.assertFalse(lone_swing_zone["formal"])
        self.assertEqual(ladder["t1"]["price"], 15.0)

    def test_future_price_bar_is_rejected(self):
        series = _dated_series()
        with self.assertRaises(ValueError):
            build_true_pressure_targets(_candidate(series), _official_plan(), "20250101")

    def test_huge_integer_price_is_a_typed_rejection_not_an_overflow(self):
        series = _dated_series()
        series[-2]["high"] = 10 ** 400
        with self.assertRaisesRegex(ValueError, "P2 price non-finite"):
            build_true_pressure_targets(_candidate(series), _official_plan(), series[-1]["trade_date"])


class ManagedExitTests(unittest.TestCase):
    def test_unverified_action_outside_plan_window_does_not_block_settlement(self):
        result = evaluate_managed_exit(_managed_plan(), _execution_rows_with_stale_unverified_action())
        self.assertEqual(result["status"], "settled")
        self.assertEqual(result["entry_date"], "20260102")

    def test_unverified_action_inside_plan_window_remains_no_count(self):
        rows = _execution_rows()
        rows[-1].update(open=None, high=None, low=None, close=None, raw_close=None, adj_factor=None)
        result = evaluate_managed_exit(_managed_plan(), rows)
        self.assertEqual((result["status"], result["reason"]), ("no_count", "non_finite_price"))

    def test_unverified_action_after_h20_does_not_block_settlement(self):
        rows = _execution_rows()
        rows.append({"trade_date": "20260201", "open": None, "high": None, "low": None, "close": None,
                     "volume": 1000, "raw_close": None, "adj_factor": None,
                     "up_limit": None, "down_limit": None})
        result = evaluate_managed_exit(_managed_plan(), rows)
        self.assertEqual(result["status"], "settled")
        self.assertEqual(result["h20_date"], "20260121")

    def test_t1_half_then_h20_mark_and_single_cost(self):
        result = evaluate_managed_exit(_managed_plan(), _execution_rows())
        self.assertEqual(result["status"], "settled")
        self.assertEqual(result["events"][0]["kind"], "t1")
        self.assertEqual(result["events"][0]["weight"], 0.5)
        self.assertEqual(result["events"][-1]["kind"], "h20_mark")
        self.assertTrue(result["unrealized_at_h20"])
        self.assertAlmostEqual(result["gross_return_pct"] - result["net_return_pct"], 0.16, places=8)
        self.assertEqual(result["diagnostics"]["h5"]["status"], "mark_to_market")
        self.assertTrue(result["diagnostics"]["h5"]["unrealized"])
        self.assertAlmostEqual(result["diagnostics"]["h20"]["net_return_pct"], result["net_return_pct"])

    def test_stop_has_priority_over_same_day_t1_and_entry_day_cannot_sell(self):
        rows = _execution_rows(stop_on_day=2)
        rows[1].update(high=13.0, low=8.0)  # entry day looks like both events but T+1 forbids sale.
        result = evaluate_managed_exit(_managed_plan(), rows)
        self.assertEqual(result["status"], "settled")
        self.assertEqual(result["events"][0]["kind"], "stop_or_trailing")
        self.assertEqual(result["events"][0]["trade_date"], rows[2]["trade_date"])
        self.assertEqual(result["events"][0]["weight"], 1.0)

    def test_trailing_uses_completed_predecision_execution_history(self):
        history = [
            {"trade_date": f"202512{day:02d}", "open": 10.0, "high": 10.3, "low": 9.7,
             "close": 10.0, "volume": 1000, "raw_close": 10.0, "adj_factor": 1.0,
             "up_limit": 11.0, "down_limit": 9.0}
            for day in range(17, 32)
        ]
        rows = history + _execution_rows()
        rows[len(history) + 2]["low"] = 9.2  # T+1 day: below a valid historical-ATR trailing line.
        result = evaluate_managed_exit(_managed_plan(), rows)
        self.assertEqual(result["status"], "settled")
        self.assertEqual(result["events"][0]["kind"], "stop_or_trailing")
        self.assertEqual(result["events"][0]["trade_date"], "20260103")
        self.assertGreater(result["events"][0]["price"], 9.0)

    def test_stop_waits_through_suspension_zero_volume_and_one_price_down(self):
        rows = _execution_rows()
        for row in rows[2:]:
            row.update(open=10.0, high=10.4, low=9.9, close=10.0, raw_close=10.0,
                       up_limit=11.0, down_limit=9.0)
        rows[2].update(suspended=True, low=8.5)
        rows[3].update(volume=0, low=8.5)
        rows[4].update(open=9.0, high=9.0, low=9.0, close=9.0, raw_close=9.0, down_limit=9.0)
        rows[5].update(open=8.8, high=10.0, low=8.5, close=9.0, raw_close=9.0)
        result = evaluate_managed_exit(_managed_plan(), rows)
        self.assertEqual(result["status"], "settled")
        self.assertEqual(result["events"][0]["kind"], "stop_or_trailing")
        self.assertEqual(result["events"][0]["trade_date"], rows[5]["trade_date"])
        self.assertEqual(result["events"][0]["price"], 8.8)

    def test_upper_limit_is_sellable_and_t1_gap_uses_open(self):
        rows = _execution_rows()
        rows[2].update(open=12.5, high=12.5, low=12.5, close=12.5, raw_close=12.5,
                       up_limit=12.5, down_limit=10.5)
        result = evaluate_managed_exit(_managed_plan(), rows)
        self.assertEqual(result["events"][0]["kind"], "t1")
        self.assertEqual(result["events"][0]["price"], 12.5)

    def test_all_one_price_upper_sessions_make_entry_no_count(self):
        rows = _execution_rows()
        for row in rows[1:]:
            row.update(open=11.0, high=11.0, low=11.0, close=11.0, raw_close=11.0,
                       up_limit=11.0, down_limit=9.0)
        result = evaluate_managed_exit(_managed_plan(), rows)
        self.assertEqual((result["status"], result["reason"]), ("no_count", "entry_unfillable"))

    def test_qfq_plan_is_converted_to_execution_price_basis(self):
        rows = _execution_rows()
        for row in rows:
            for key in ("open", "high", "low", "close", "up_limit", "down_limit"):
                row[key] *= 2.0
            row["raw_close"] = row["close"] / 2.0
            row["adj_factor"] = 2.0
        result = evaluate_managed_exit(_managed_plan(), rows)
        self.assertEqual(result["status"], "settled")
        self.assertEqual(result["conversion_ratio"], 2.0)
        self.assertEqual(result["entry_price"], 20.0)
        self.assertEqual(result["events"][0]["price"], 24.0)

    def test_price_basis_mismatch_is_no_count(self):
        rows = _execution_rows()
        rows[0]["close"] = 9.9  # raw_close x adj_factor no longer proves the execution close.
        result = evaluate_managed_exit(_managed_plan(), rows)
        self.assertEqual((result["status"], result["reason"]), ("no_count", "price_basis_mismatch"))

    def test_huge_integer_execution_price_is_no_count_not_an_overflow(self):
        rows = _execution_rows()
        rows[1]["high"] = 10 ** 400
        result = evaluate_managed_exit(_managed_plan(), rows)
        self.assertEqual((result["status"], result["reason"]), ("no_count", "non_finite_price"))


class TargetLedgerTests(unittest.TestCase):
    def setUp(self):
        # These cases assert the ENFORCED epoch contract (the historical default).
        # Pre-freeze behaviour is covered by tests/test_a_short_evidence_epoch_mode.py.
        enter_patched_epoch_modes(self, "frozen_enforced")

    def test_threshold_evidence_is_not_review_due_pre_freeze_then_is_due_when_enforced(self):
        settled = {"changed": True, "outcomes": {"status": "settled"}}
        records = [
            {"forward_eligible": True, "target_difference": True,
             "target_entries": [dict(settled), dict(settled)],
             "breakout_difference": True, "breakout_entries": [dict(settled), dict(settled)]}
            for _ in range(12)
        ]
        with patched_epoch_modes("pre_freeze_audit_only"):
            self.assertEqual(_progress(records, "target_exit", "not_reviewed")["review_state"], "not_due")
            self.assertEqual(_progress(records, "breakout_entry", "not_reviewed")["review_state"], "not_due")
        with patched_epoch_modes("frozen_enforced"):
            self.assertEqual(_progress(records, "target_exit", "not_reviewed")["review_state"], "due")
            self.assertEqual(_progress(records, "breakout_entry", "not_reviewed")["review_state"], "due")

    def test_public_summary_rejects_older_as_of_but_allows_equal_or_newer(self):
        with tempfile.TemporaryDirectory() as td:
            summary_path, markdown_path = Path(td) / "summary.json", Path(td) / "summary.md"
            current = _summary_from_ledger(_new_ledger(), "20260727")
            write_public_summary(current, summary_path=summary_path, markdown_path=markdown_path)
            older = _summary_from_ledger(_new_ledger(), "20260726")
            with self.assertRaisesRegex(TargetPolicyError, "as_of_regressed"):
                write_public_summary(older, summary_path=summary_path, markdown_path=markdown_path)
            write_public_summary(_summary_from_ledger(_new_ledger(), "20260727"),
                                 summary_path=summary_path, markdown_path=markdown_path)
            write_public_summary(_summary_from_ledger(_new_ledger(), "20260728"),
                                 summary_path=summary_path, markdown_path=markdown_path)

    def test_public_writer_replaces_only_the_complete_pre_8b_summary_shape(self):
        with tempfile.TemporaryDirectory() as td:
            summary_path, markdown_path = Path(td) / "summary.json", Path(td) / "summary.md"
            current = _summary_from_ledger(_new_ledger(), "20260727")
            legacy = copy.deepcopy(current)
            for key in (
                "verdict", "progress", "fingerprint", "source_hash", "target_exit_adjudication",
                "breakout_entry_reports", "breakout_entry_verdict",
            ):
                legacy.pop(key)
            summary_path.write_text(json.dumps(legacy), encoding="utf-8")

            write_public_summary(current, summary_path=summary_path, markdown_path=markdown_path)
            written = json.loads(summary_path.read_text(encoding="utf-8"))
            validate_public_summary(written)
            self.assertEqual(written, current)
            self.assertIn("只显示脱敏进度", markdown_path.read_text(encoding="utf-8"))

            malformed = copy.deepcopy(current)
            malformed.pop("verdict")
            summary_path.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaisesRegex(TargetPolicyError, "existing_public_summary_unreadable"):
                write_public_summary(current, summary_path=summary_path, markdown_path=markdown_path)

    def test_pre_freeze_epoch_retains_its_capture_admission_but_frozen_epoch_rejects_drift(self):
        ledger = _new_ledger()
        epoch = _active_epoch(ledger, create=True, track="target_exit")
        assert epoch is not None
        historical = copy.deepcopy(epoch["admission_binding"])
        historical["p2_target_exit_policy"]["identity_sha256"] = "0" * 64
        epoch["admission_binding"] = historical

        with patched_epoch_modes("pre_freeze_audit_only"):
            _validate_ledger(ledger)
        with patched_epoch_modes("frozen_enforced"):
            with self.assertRaisesRegex(TargetPolicyError, "private_epoch_admission_binding_drifted"):
                _validate_ledger(ledger)

    def test_cross_fingerprint_legacy_epoch_never_enters_public_progress(self):
        ledger = _new_ledger()
        epoch = _active_epoch(ledger, create=True, track="target_exit")
        assert epoch is not None
        legacy_fingerprint = "a" * 64
        epoch["epoch_id"] = legacy_fingerprint
        epoch["contract_fingerprint"] = legacy_fingerprint
        record = {
            "decision_date": "20260727", "forward_eligible": True,
            "source_identity": {"run_id": "legacy-run", "candidate_digest": "b" * 64,
                                "official_m67_sha256": "c" * 64, "price_data_through": "20260727"},
            "component_id": "target_exit", "admission_binding": copy.deepcopy(epoch["admission_binding"]),
            "component_epoch_fingerprint": legacy_fingerprint, "target_entries": [], "target_difference": False,
        }
        record["capture_sha256"] = _capture_digest(record)
        epoch["records"].append(record)
        for mode in ("pre_freeze_audit_only", "frozen_enforced"):
            with self.subTest(mode=mode), patched_epoch_modes(mode):
                summary = _summary_from_ledger(ledger, "20260727")
            self.assertEqual(summary["target_exit"]["forward_weeks"], 0)
            self.assertEqual(summary["progress"]["forward_weeks"], 0)
            self.assertIsNone(summary["data_through"])
            self.assertEqual(summary["target_exit"]["review_state"], "not_due")

    def test_tracked_public_summary_is_a_valid_matched_writer_pair_without_private_ledger(self):
        """The tracked pair stays reproducible without consulting ignored private state."""
        tracked_json = ROOT / "research" / "results" / "a_short" / "target_policy_comparison_summary.json"
        tracked_markdown = tracked_json.with_suffix(".md")
        tracked = json.loads(tracked_json.read_text(encoding="utf-8"))
        validate_public_summary(tracked)
        self.assertEqual(tracked_markdown.read_text(encoding="utf-8"), _render_summary_markdown(tracked))

        with tempfile.TemporaryDirectory() as td:
            reproduced_json = Path(td) / "summary.json"
            reproduced_markdown = Path(td) / "summary.md"
            write_public_summary(tracked, summary_path=reproduced_json, markdown_path=reproduced_markdown)
            self.assertEqual(json.loads(reproduced_json.read_text(encoding="utf-8")), tracked)
            self.assertEqual(reproduced_markdown.read_text(encoding="utf-8"),
                             tracked_markdown.read_text(encoding="utf-8"))

    def _published_bundle(self, directory: Path, as_of: str) -> tuple[Path, Path, dict, list[dict]]:
        series = _dated_series()
        candidate = _candidate(series)
        candidate_digest = "a" * 64
        weekly = {
            "as_of": as_of,
            "run_lineage": {"run_id": "run-1", "candidate_digest": candidate_digest,
                            "price_freshness": {"mode": "intraday_prior_settled", "run_date": as_of,
                                                "price_data_through": as_of}},
            "reports": [{"ts_code": candidate["ts_code"],
                         "machine": {"entry_exit_size_star": {"plan": _official_plan()}}}],
        }
        out = directory / as_of / "weekly_m67.json"
        receipt = out.with_name("weekly_m67.receipt.json")
        write_content_bound_bundle(out, weekly, receipt_path=receipt)
        return out, receipt, {"run_id": "run-1", "candidate_digest": candidate_digest}, [candidate]

    def test_capture_is_idempotent_and_settlement_uses_existing_cache_only(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            ledger = directory / "logs" / "a_short_target_policy_comparison.json"
            public = directory / "public.json"
            markdown = directory / "public.md"
            as_of = _dated_series()[-1]["trade_date"]
            out, receipt, identity, candidates = self._published_bundle(directory, as_of)
            first = capture_after_published_weekly(
                root=ledger, decision_date=as_of, candidates=candidates, source_identity=identity,
                out_path=out, receipt_path=receipt, forward_eligible=True,
                summary_path=public, markdown_path=markdown)
            self.assertEqual(first["status"], "captured")
            self.assertEqual(first["record"]["target_entries"][0]["baseline_t1_basis"], "rr_floor_fallback")
            summary = json.loads(public.read_text(encoding="utf-8"))
            validate_public_summary(summary)
            leaked = copy.deepcopy(summary)
            leaked["admissions"]["p2_target_exit_policy"]["dependency_components"][0]["ts_code"] = "600000.SH"
            with self.assertRaises(TargetPolicyError):
                validate_public_summary(leaked)
            self.assertEqual(summary["target_exit"]["forward_weeks"], 1)
            second = capture_after_published_weekly(
                root=ledger, decision_date=as_of, candidates=candidates, source_identity=identity,
                out_path=out, receipt_path=receipt, forward_eligible=True,
                summary_path=public, markdown_path=markdown)
            self.assertEqual(second["status"], "idempotent")
            changed = copy.deepcopy(candidates)
            changed[0]["price_series"][-2]["high"] = 19.0
            with self.assertRaises(TargetPolicyError):
                capture_after_published_weekly(
                    root=ledger, decision_date=as_of, candidates=changed, source_identity=identity,
                    out_path=out, receipt_path=receipt, forward_eligible=True,
                    summary_path=public, markdown_path=markdown)

            cache = directory / "execution_cache.json"
            cache.write_text(json.dumps({"rows": [dict(row, ts_code="600000.SH")
                                                   for row in _execution_rows_with_stale_unverified_action()]}),
                             encoding="utf-8")
            first_carrier = {}
            refreshed = settle_and_summarize(
                root=ledger, as_of=as_of, daily_cache_path=cache,
                summary_path=public, markdown_path=markdown,
                sidecar_result=first_carrier,
            )
            self.assertEqual(refreshed["status"], "accumulating")
            self.assertEqual(refreshed["target_exit"]["evaluable_plans"], 1)
            self.assertGreater(first_carrier["outcomes_updated"], 0)
            second_carrier = {}
            settle_and_summarize(
                root=ledger, as_of=as_of, daily_cache_path=cache,
                summary_path=public, markdown_path=markdown,
                sidecar_result=second_carrier,
            )
            self.assertEqual(second_carrier["outcomes_updated"], 0)
            self.assertIn("只显示脱敏进度", markdown.read_text(encoding="utf-8"))

    def test_corrupt_private_state_never_replays_a_review_reminder(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "ledger.json"
            root.write_text("{broken", encoding="utf-8")
            summary = settle_and_summarize(root=root, as_of="20260121",
                                            summary_path=Path(td) / "summary.json",
                                            markdown_path=Path(td) / "summary.md")
            self.assertEqual(summary["status"], "evidence_unavailable_or_inconclusive")

    def test_one_bad_shadow_candidate_cannot_drop_same_week_good_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            ledger = directory / "logs" / "p2.json"
            as_of = _dated_series()[-1]["trade_date"]
            out, receipt, identity, candidates = self._published_bundle(directory, as_of)
            bad = copy.deepcopy(candidates[0])
            bad["ts_code"] = "600001.SH"
            bad["price_series"][-2]["high"] = 10 ** 400
            captured = capture_after_published_weekly(
                root=ledger, decision_date=as_of, candidates=candidates + [bad], source_identity=identity,
                out_path=out, receipt_path=receipt, forward_eligible=True,
                summary_path=directory / "public.json", markdown_path=directory / "public.md")
            entries = {entry["ts_code"]: entry for entry in captured["record"]["target_entries"]}
            self.assertEqual(entries["600001.SH"]["target_reason"], "candidate_input_invalid")
            self.assertNotEqual(entries["600000.SH"]["target_status"], "unavailable")

    def test_breakout_track_settles_independently_of_target_change(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            ledger, public, markdown = (directory / "logs" / "p2.json", directory / "public.json",
                                        directory / "public.md")
            as_of = _dated_series()[-1]["trade_date"]
            out, receipt, identity, candidates = self._published_bundle(directory, as_of)
            candidate = candidates[0]
            candidate["price_series"][-1].update(high=10.4, low=9.9, close=10.1)
            weekly = json.loads(out.read_text(encoding="utf-8"))
            weekly["reports"][0]["machine"]["entry_exit_size_star"]["plan"]["t1"] = 12.0
            write_content_bound_bundle(out, weekly, receipt_path=receipt)
            capture_after_published_weekly(
                root=ledger, decision_date=as_of, candidates=candidates, source_identity=identity,
                out_path=out, receipt_path=receipt, forward_eligible=True,
                summary_path=public, markdown_path=markdown)
            epochs = json.loads(ledger.read_text(encoding="utf-8"))["epochs"]
            target = next(epoch for epoch in epochs if epoch["component_id"] == "target_exit")["records"][0]
            breakout = next(epoch for epoch in epochs if epoch["component_id"] == "breakout_entry")["records"][0]
            self.assertFalse(target["target_difference"])
            self.assertTrue(breakout["breakout_difference"])

            rows = _execution_rows()
            rows[0].update(close=10.1, raw_close=10.1)
            cache = directory / "execution_cache.json"
            cache.write_text(json.dumps({"rows": [dict(row, ts_code="600000.SH") for row in rows]}),
                             encoding="utf-8")
            refreshed = settle_and_summarize(root=ledger, as_of=as_of, daily_cache_path=cache,
                                              summary_path=public, markdown_path=markdown)
            self.assertEqual(refreshed["target_exit"]["evaluable_plans"], 0)
            self.assertEqual(refreshed["breakout_entry"]["evaluable_plans"], 1)
            settled = next(epoch for epoch in json.loads(ledger.read_text(encoding="utf-8"))["epochs"]
                           if epoch["component_id"] == "breakout_entry")["records"][0]["breakout_entries"][0]
            self.assertEqual(settled["outcomes"]["status"], "settled")
            self.assertGreater(settled["outcomes"]["old_h20_net_return_pct"], 0)
            self.assertEqual(settled["outcomes"]["new_h20_net_return_pct"], 0.0)

    def test_contract_fingerprint_opens_a_new_epoch(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            ledger = directory / "logs" / "p2.json"
            as_of = _dated_series()[-1]["trade_date"]
            out, receipt, identity, candidates = self._published_bundle(directory, as_of)
            with patch("runners.a_short_target_policy_comparison_runner._contract_fingerprint",
                       return_value="a" * 64):
                capture_after_published_weekly(
                    root=ledger, decision_date=as_of, candidates=candidates, source_identity=identity,
                    out_path=out, receipt_path=receipt, forward_eligible=True,
                    summary_path=directory / "public.json", markdown_path=directory / "public.md")
            next_as_of = "20260102"
            out, receipt, identity, candidates = self._published_bundle(directory, next_as_of)
            with patch("runners.a_short_target_policy_comparison_runner._contract_fingerprint",
                       return_value="b" * 64):
                capture_after_published_weekly(
                    root=ledger, decision_date=next_as_of, candidates=candidates, source_identity=identity,
                    out_path=out, receipt_path=receipt, forward_eligible=True,
                    summary_path=directory / "public.json", markdown_path=directory / "public.md")
            epochs = json.loads(ledger.read_text(encoding="utf-8"))["epochs"]
            self.assertEqual([epoch["epoch_id"] for epoch in epochs], ["a" * 64, "a" * 64, "b" * 64, "b" * 64])
            self.assertEqual([epoch["component_id"] for epoch in epochs],
                             ["target_exit", "breakout_entry", "target_exit", "breakout_entry"])
            self.assertEqual([len(epoch["records"]) for epoch in epochs], [1, 1, 1, 1])

    def test_component_specific_and_shared_contract_surfaces_restart_only_affected_epochs(self):
        target, breakout = _contract_fingerprint("target_exit"), _contract_fingerprint("breakout_entry")
        with patch("runners.a_short_target_policy_comparison_runner._target_contract_surface",
                   return_value={"target_only": "changed"}):
            self.assertNotEqual(_contract_fingerprint("target_exit"), target)
            self.assertEqual(_contract_fingerprint("breakout_entry"), breakout)
        with patch("runners.a_short_target_policy_comparison_runner._breakout_contract_surface",
                   return_value={"breakout_only": "changed"}):
            self.assertEqual(_contract_fingerprint("target_exit"), target)
            self.assertNotEqual(_contract_fingerprint("breakout_entry"), breakout)
        with patch("runners.a_short_target_policy_comparison_runner._shared_contract_surface",
                   return_value={"shared": "changed"}):
            self.assertNotEqual(_contract_fingerprint("target_exit"), target)
            self.assertNotEqual(_contract_fingerprint("breakout_entry"), breakout)

    def test_executed_wrappers_and_transitive_constants_restart_only_affected_component(self):
        target, breakout = _contract_fingerprint("target_exit"), _contract_fingerprint("breakout_entry")

        def target_wrapper_change(*_args, **_kwargs):
            return None, None, {"status": "observe"}

        with patch("runners.a_short_target_policy_comparison_runner._target_entry", target_wrapper_change):
            self.assertNotEqual(_contract_fingerprint("target_exit"), target)
            self.assertEqual(_contract_fingerprint("breakout_entry"), breakout)

        def target_ladder_wrapper_change(*_args, **_kwargs):
            return {"status": "observe"}

        with patch.object(phase5_engine, "build_p2_target_ladder", target_ladder_wrapper_change):
            self.assertNotEqual(_contract_fingerprint("target_exit"), target)
            self.assertEqual(_contract_fingerprint("breakout_entry"), breakout)

        def breakout_wrapper_change(*_args, **_kwargs):
            return None, {"true_breakout": False, "momentum_confirmed": False}

        with patch("runners.a_short_target_policy_comparison_runner._breakout_entry", breakout_wrapper_change):
            self.assertEqual(_contract_fingerprint("target_exit"), target)
            self.assertNotEqual(_contract_fingerprint("breakout_entry"), breakout)

        def breakout_qualification_wrapper_change(*_args, **_kwargs):
            return {"true_breakout": False, "momentum_confirmed": False}

        with patch.object(phase5_engine, "build_p2_breakout_qualification", breakout_qualification_wrapper_change):
            self.assertEqual(_contract_fingerprint("target_exit"), target)
            self.assertNotEqual(_contract_fingerprint("breakout_entry"), breakout)

        with patch.object(phase5_engine, "RR_FLOOR", {"changed_target_rule": 9.0}):
            self.assertNotEqual(_contract_fingerprint("target_exit"), target)
            self.assertEqual(_contract_fingerprint("breakout_entry"), breakout)
        with patch.object(phase5_engine, "RESISTANCE_LOOKBACK", phase5_engine.RESISTANCE_LOOKBACK + 1):
            self.assertNotEqual(_contract_fingerprint("target_exit"), target)
            self.assertNotEqual(_contract_fingerprint("breakout_entry"), breakout)

        with patch.object(phase5_engine, "SR_SPIKE_ATR", phase5_engine.SR_SPIKE_ATR + 1.0):
            self.assertNotEqual(_contract_fingerprint("target_exit"), target)
            self.assertNotEqual(_contract_fingerprint("breakout_entry"), breakout)

        def ma_change(values, _window):
            return None if not values else values[-1]

        with patch.object(phase5_engine, "ma", ma_change):
            self.assertNotEqual(_contract_fingerprint("target_exit"), target)
            self.assertNotEqual(_contract_fingerprint("breakout_entry"), breakout)

        def tick_up_change(value):
            return value

        with patch.object(managed_exit, "tick_up", tick_up_change):
            self.assertNotEqual(_contract_fingerprint("target_exit"), target)
            self.assertNotEqual(_contract_fingerprint("breakout_entry"), breakout)

        with patch.object(phase5_engine, "ATR_MULT", {"shared_exit_multiplier": 9.0}):
            self.assertNotEqual(_contract_fingerprint("target_exit"), target)
            self.assertNotEqual(_contract_fingerprint("breakout_entry"), breakout)

    def test_settlement_semantics_restart_only_the_affected_component_epoch(self):
        target, breakout = _contract_fingerprint("target_exit"), _contract_fingerprint("breakout_entry")

        def target_settlement_change(*_args, **_kwargs):
            return None

        with patch("runners.a_short_target_policy_comparison_runner._settle_target_records", target_settlement_change):
            self.assertNotEqual(_contract_fingerprint("target_exit"), target)
            self.assertEqual(_contract_fingerprint("breakout_entry"), breakout)

        def breakout_settlement_change(*_args, **_kwargs):
            return None

        with patch("runners.a_short_target_policy_comparison_runner._settle_breakout_records", breakout_settlement_change):
            self.assertEqual(_contract_fingerprint("target_exit"), target)
            self.assertNotEqual(_contract_fingerprint("breakout_entry"), breakout)

        def cache_loader_change(*_args, **_kwargs):
            return {}

        with patch("runners.a_short_target_policy_comparison_runner._load_execution_cache", cache_loader_change):
            self.assertNotEqual(_contract_fingerprint("target_exit"), target)
            self.assertNotEqual(_contract_fingerprint("breakout_entry"), breakout)

    def test_current_epoch_rejects_unbound_records_and_stale_epoch_pass(self):
        ledger = _new_ledger()
        epoch = _active_epoch(ledger, create=True, track="target_exit")
        assert epoch is not None
        epoch["records"].append({"decision_date": "20260101", "forward_eligible": True})
        with self.assertRaises(TargetPolicyError):
            _validate_ledger(ledger)

        ledger = _new_ledger()
        epoch = _active_epoch(ledger, create=True, track="target_exit")
        assert epoch is not None
        ledger["review_status_by_epoch"]["target_exit"][epoch["epoch_id"]] = "pass"
        with patch("runners.a_short_target_policy_comparison_runner._contract_fingerprint",
                   side_effect=lambda track=None: ("next-" + str(track)) if track else "next-all"):
            self.assertEqual(_summary_from_ledger(ledger, "20260101")["status"], "accumulating")

    def test_legacy_records_and_top_level_pass_never_enter_current_admission_progress(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            ledger = directory / "p2.json"
            dates = [(date(2026, 1, 1) + timedelta(days=index)).strftime("%Y%m%d") for index in range(12)]
            records = []
            for index, decision_date in enumerate(dates):
                changed = index < 8
                outcomes = {"status": "settled"} if index < 10 else None
                count = 3 if index < 4 else 2
                records.append({
                    "decision_date": decision_date,
                    "forward_eligible": True,
                    "target_difference": changed,
                    "breakout_difference": changed,
                    "target_entries": [{"changed": changed, "outcomes": outcomes} for _ in range(count)],
                    "breakout_entries": [{"changed": changed, "outcomes": outcomes} for _ in range(count)],
                })
            from runners.a_short_target_policy_comparison_runner import _contract_fingerprint
            fingerprint = _contract_fingerprint()
            ledger.write_text(json.dumps({
                "schema_name": "a_short_target_policy_comparison_ledger", "schema_version": "1.0.0",
                "epochs": [{"epoch_id": fingerprint, "contract_fingerprint": fingerprint, "records": records}],
                "review_status": {"target_exit": "not_reviewed", "breakout_entry": "not_reviewed"},
                "boundary": {"production": False, "automatic_policy_switch": False},
            }), encoding="utf-8")
            summary = settle_and_summarize(root=ledger, as_of=dates[-1],
                                            summary_path=directory / "public.json",
                                            markdown_path=directory / "public.md")
            self.assertEqual(summary["status"], "accumulating")
            self.assertEqual(summary["target_exit"]["forward_weeks"], 0)
            self.assertEqual(summary["breakout_entry"]["forward_weeks"], 0)
            private = json.loads(ledger.read_text(encoding="utf-8"))
            private["review_status"] = {"target_exit": "pass", "breakout_entry": "pass"}
            ledger.write_text(json.dumps(private), encoding="utf-8")
            confirmed = settle_and_summarize(root=ledger, as_of=dates[-1],
                                              summary_path=directory / "public.json",
                                              markdown_path=directory / "public.md")
            self.assertEqual(confirmed["status"], "accumulating")


class WeeklySurfaceTests(unittest.TestCase):
    def test_p2_summary_is_rendered_but_cannot_change_m67_rows(self):
        weekly = build_weekly_report([_normalized()], "20260609", "t")
        before = [(row["m67"]["table"]["操作"], row["m67"]["table"]["股数"],
                   row["m67"]["table"]["盈一"]) for row in weekly["reports"]]
        summary = settle_and_summarize(root=None, as_of="20260609")
        weekly["target_policy_comparison"] = summary
        validate_weekly_report(weekly, _feed())
        after = [(row["m67"]["table"]["操作"], row["m67"]["table"]["股数"],
                  row["m67"]["table"]["盈一"]) for row in weekly["reports"]]
        self.assertEqual(before, after)
        self.assertIn(summary["message"], render_weekly_markdown(weekly))
