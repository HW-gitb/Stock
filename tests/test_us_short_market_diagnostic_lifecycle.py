from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

import engine.us_short_market_diagnostic as diagnostic
import engine.us_short_market_diagnostic_lifecycle as lifecycle
from engine.us_short_market_diagnostic import (
    validate_weekly_record,
    window_containing_week,
    window_for_week,
)
from engine.us_short_market_diagnostic_lifecycle import (
    MarketDiagnosticLifecycleError,
    build_v1_1_reminder,
    load_lifecycle_register,
    persist_settled_weekly_record,
    render_weekly_report_reminder,
)
from engine.us_short_model_paper_portfolio import canonical_json_bytes
from tests.test_us_short_market_diagnostic import _weekly_rows


ROOT = Path(__file__).resolve().parents[1]


class UsShortMarketDiagnosticLifecycleTest(unittest.TestCase):
    def test_v1_1_reminder_has_plain_language_thresholds(self) -> None:
        self.assertEqual("pending", build_v1_1_reminder(0)["status"])
        self.assertEqual("pending", build_v1_1_reminder(3)["status"])
        self.assertEqual("ready_for_v1_1_implementation", build_v1_1_reminder(4)["status"])
        self.assertEqual("ready_for_v1_1_implementation", build_v1_1_reminder(7)["status"])
        self.assertEqual("overdue", build_v1_1_reminder(8)["status"])
        text = build_v1_1_reminder(4)["text"]
        self.assertIn("仓位/现金", text)
        self.assertIn("主动系统能力", text)
        self.assertIn("当前v1只能告诉总成绩", text)

    def test_persists_immutable_weeks_and_derives_counter_and_report_block(self) -> None:
        rows = _weekly_rows()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            outputs = [persist_settled_weekly_record(row, root=root) for row in rows[:8]]
            register = load_lifecycle_register(root)
            register_bytes = (root / "lifecycle_register.json").read_bytes()
            weekly_bytes = (root / "weeks" / "20260102" / "weekly_record.json").read_bytes()

            self.assertEqual("pending", outputs[0]["v1_1_reminder"]["status"])
            self.assertEqual("ready_for_v1_1_implementation", outputs[3]["v1_1_reminder"]["status"])
            self.assertEqual("overdue", outputs[7]["v1_1_reminder"]["status"])
            self.assertEqual(8, register["calendar_week_count"])
            self.assertEqual(8, register["evaluable_week_count"])
            self.assertEqual(8, register["last_calendar_week_index"])
            self.assertEqual("26w-1-26", register["current_window_id"])
            self.assertEqual(8, register["current_window_week_count"])
            self.assertEqual(8, len(list((root / "weeks").rglob("weekly_record.json"))))
            self.assertIn("可评估周=8", render_weekly_report_reminder(register))
            self.assertIn("v1.1归因", outputs[-1]["weekly_report_reminder"]["text"])
            self.assertEqual(register_bytes, (root / "lifecycle_register.json").read_bytes())
            self.assertEqual(weekly_bytes, (root / "weeks" / "20260102" / "weekly_record.json").read_bytes())

    def test_lifecycle_and_week_validation_delegate_to_single_window_source(self) -> None:
        row = copy.deepcopy(_weekly_rows()[0])
        original = diagnostic.WINDOW_WEEKS
        try:
            diagnostic.WINDOW_WEEKS = 13
            canonical = window_containing_week(1)
            row["window_id"] = canonical["window_id"]
            identity = validate_weekly_record(row)
            register = lifecycle._register_from_records([row])

            self.assertEqual(canonical, window_for_week(13))
            self.assertEqual(canonical["window_id"], identity["window_id"])
            self.assertEqual(canonical["window_id"], register["current_window_id"])
            self.assertEqual(1, register["current_window_week_count"])
            self.assertEqual(13, canonical["calendar_weeks"])
        finally:
            diagnostic.WINDOW_WEEKS = original

    def test_same_week_is_idempotent_but_changed_content_is_rejected(self) -> None:
        row = _weekly_rows()[0]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            first = persist_settled_weekly_record(row, root=root)
            replay = copy.deepcopy(row)
            replay["v1_1_reminder"] = {
                "status": "overdue",
                "evaluable_week_count": 999,
                "text": "caller cannot author lifecycle state",
            }
            second = persist_settled_weekly_record(replay, root=root)
            self.assertEqual("idempotent", second["status"])
            self.assertEqual(first["weekly_record_sha256"], second["weekly_record_sha256"])

            conflict = copy.deepcopy(row)
            conflict["source_refs"] = ["f" * 64]
            with self.assertRaises(MarketDiagnosticLifecycleError):
                persist_settled_weekly_record(conflict, root=root)

    def test_non_evaluable_paper_week_stays_in_calendar_count_but_not_v1_1_count(self) -> None:
        rows = _weekly_rows(paper_false_weeks={1})
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            first = persist_settled_weekly_record(rows[0], root=root)
            self.assertEqual(1, first["calendar_week_count"])
            self.assertEqual(0, first["evaluable_week_count"])
            second = persist_settled_weekly_record(rows[1], root=root)
            self.assertEqual(2, second["calendar_week_count"])
            self.assertEqual(1, second["evaluable_week_count"])
            register = load_lifecycle_register(root)
            self.assertEqual(1, register["non_evaluable_week_count"])

    def test_gap_epoch_and_register_drift_fail_closed(self) -> None:
        rows = _weekly_rows()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            persist_settled_weekly_record(rows[0], root=root)
            with self.assertRaises(MarketDiagnosticLifecycleError):
                persist_settled_weekly_record(rows[2], root=root)

            epoch_drift = copy.deepcopy(rows[1])
            epoch_drift["diagnostic_epoch"] = "us_short_market_diagnostic_26w_v2"
            with self.assertRaises(MarketDiagnosticLifecycleError):
                persist_settled_weekly_record(epoch_drift, root=root)

            persist_settled_weekly_record(rows[1], root=root)
            path = root / "lifecycle_register.json"
            register = json.loads(path.read_text(encoding="utf-8"))
            register["evaluable_week_count"] = 999
            path.write_bytes(canonical_json_bytes(register))
            with self.assertRaises(MarketDiagnosticLifecycleError):
                load_lifecycle_register(root)

    def test_private_path_guard_blocks_tracked_diagnostic_output(self) -> None:
        with self.assertRaises(MarketDiagnosticLifecycleError):
            persist_settled_weekly_record(_weekly_rows()[0], root=ROOT / "docs" / "diagnostic_private")


if __name__ == "__main__":
    unittest.main()
