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
    load_settled_weekly_records,
    persist_settled_weekly_record,
    render_weekly_report_reminder,
)
from engine.us_short_market_diagnostic_start_receipt import (
    issue_start_receipt,
    load_start_receipt,
    start_receipt_sha256,
)
from engine.us_short_model_paper_portfolio import canonical_json_bytes
from tests.test_us_short_market_diagnostic import _weekly_rows


ROOT = Path(__file__).resolve().parents[1]



def _open_clock(root, row):
    """Issue the start receipt that Knife 7 now requires before week 1.

    These tests exercise the store, not the gate, so they need a genuine receipt
    rather than a relaxed store. The gate itself is proven separately in
    tests/test_us_short_market_diagnostic_start_receipt.py.
    """

    return issue_start_receipt(
        diagnostic_epoch=row["diagnostic_epoch"],
        completion_notification={
            "issued_at": "2025-12-29T00:00:00+00:00",
            "issuer": "codex",
            "notification_text": "US-short 26-week diagnostic design is complete.",
        },
        first_decision_date=row["decision_date"],
        root=root,
    )


class UsShortMarketDiagnosticLifecycleTest(unittest.TestCase):
    def test_v1_1_reminder_has_plain_language_thresholds(self) -> None:
        self.assertEqual(
            "pending",
            build_v1_1_reminder(0, consecutive_paper_evaluable_week_count=0)["status"],
        )
        self.assertEqual(
            "pending",
            build_v1_1_reminder(3, consecutive_paper_evaluable_week_count=3)["status"],
        )
        self.assertEqual(
            "active",
            build_v1_1_reminder(4, consecutive_paper_evaluable_week_count=4)["status"],
        )
        self.assertEqual(
            "active",
            build_v1_1_reminder(7, consecutive_paper_evaluable_week_count=7)["status"],
        )
        self.assertEqual(
            "active",
            build_v1_1_reminder(8, consecutive_paper_evaluable_week_count=8)["status"],
        )
        text = build_v1_1_reminder(
            4, consecutive_paper_evaluable_week_count=4
        )["text"]
        self.assertIn("仓位和现金", text)
        self.assertIn("主动系统能力", text)
        self.assertIn("自动启用", text)

    def test_persists_immutable_weeks_and_derives_counter_and_report_block(self) -> None:
        rows = _weekly_rows()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            _open_clock(root, rows[0])
            outputs = [persist_settled_weekly_record(row, root=root) for row in rows[:8]]
            register = load_lifecycle_register(root)
            register_bytes = (root / "lifecycle_register.json").read_bytes()
            weekly_bytes = (root / "weeks" / "20260102" / "weekly_record.json").read_bytes()

            self.assertEqual("pending", outputs[0]["v1_1_reminder"]["status"])
            self.assertEqual("active", outputs[3]["v1_1_reminder"]["status"])
            self.assertEqual("active", outputs[7]["v1_1_reminder"]["status"])
            self.assertEqual(8, register["calendar_week_count"])
            self.assertEqual(8, register["evaluable_week_count"])
            self.assertEqual(8, register["consecutive_paper_evaluable_week_count"])
            self.assertEqual("active", register["v1_1_attribution"]["status"])
            self.assertEqual(4, register["v1_1_attribution"]["activation_trigger_week_index"])
            self.assertEqual(5, register["v1_1_attribution"]["effective_from_week_index"])
            self.assertTrue(register["v1_1_attribution"]["attribution_epoch"])
            self.assertEqual(8, register["last_calendar_week_index"])
            self.assertEqual("26w-1-26", register["current_window_id"])
            self.assertEqual(8, register["current_window_week_count"])
            self.assertEqual(8, len(list((root / "weeks").rglob("weekly_record.json"))))
            self.assertIn("连续可评估周=8", render_weekly_report_reminder(register))
            self.assertIn("v1.1 归因", outputs[-1]["weekly_report_reminder"]["text"])
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
            _open_clock(root, row)
            first = persist_settled_weekly_record(row, root=root)
            replay = copy.deepcopy(row)
            replay["v1_1_reminder"] = {
                "status": "active",
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
            _open_clock(root, rows[0])
            first = persist_settled_weekly_record(rows[0], root=root)
            self.assertEqual(1, first["calendar_week_count"])
            self.assertEqual(0, first["evaluable_week_count"])
            second = persist_settled_weekly_record(rows[1], root=root)
            self.assertEqual(2, second["calendar_week_count"])
            self.assertEqual(1, second["evaluable_week_count"])
            register = load_lifecycle_register(root)
            self.assertEqual(1, register["non_evaluable_week_count"])
            self.assertEqual(1, register["consecutive_paper_evaluable_week_count"])
            self.assertEqual("pending", register["v1_1_attribution"]["status"])

    def test_v1_1_activation_requires_four_consecutive_paper_evaluable_weeks_and_is_sticky(self) -> None:
        rows = _weekly_rows(paper_false_weeks={3, 8})
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            _open_clock(root, rows[0])
            outputs = [persist_settled_weekly_record(row, root=root) for row in rows[:8]]
            register = load_lifecycle_register(root)

            self.assertEqual("pending", outputs[5]["v1_1_reminder"]["status"])
            self.assertEqual("active", outputs[6]["v1_1_reminder"]["status"])
            self.assertEqual("active", outputs[7]["v1_1_reminder"]["status"])
            self.assertEqual(0, register["consecutive_paper_evaluable_week_count"])
            self.assertEqual(7, register["v1_1_attribution"]["activation_trigger_week_index"])
            self.assertEqual(8, register["v1_1_attribution"]["effective_from_week_index"])
            self.assertEqual("active", register["v1_1_attribution"]["status"])

    def test_gap_epoch_and_register_drift_fail_closed(self) -> None:
        rows = _weekly_rows()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            _open_clock(root, rows[0])
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

    def test_lifecycle_as_of_date_rejects_future_week(self) -> None:
        row = _weekly_rows()[0]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            _open_clock(root, row)
            with self.assertRaises(MarketDiagnosticLifecycleError):
                persist_settled_weekly_record(row, root=root, as_of_date="20260101")
            persist_settled_weekly_record(row, root=root, as_of_date="20260102")
            with self.assertRaises(MarketDiagnosticLifecycleError):
                load_lifecycle_register(root, as_of_date="20260101")
            self.assertEqual(1, load_lifecycle_register(root, as_of_date="20260102")["calendar_week_count"])


class OrphanRecoveryTest(unittest.TestCase):
    """The crash-between-writes path, which had a gate and no other coverage.

    The weekly record is written before the register, so a process killed between
    them leaves a record with no register. Retrying the same week must recover;
    every other shape of orphan must refuse, because adopting an unknown file is
    how a store silently acquires a week nobody recorded.
    """

    def setUp(self) -> None:
        self.rows = _weekly_rows()
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.store = Path(holder.name) / "market_diagnostic_private"
        _open_clock(self.store, self.rows[0])

    def _orphan(self, row) -> None:
        """Reproduce the crash: the record lands, the register never does."""

        persist_settled_weekly_record(row, root=self.store)
        (self.store / "lifecycle_register.json").unlink()

    def test_retrying_the_interrupted_week_recovers_the_register(self) -> None:
        self._orphan(self.rows[0])
        result = persist_settled_weekly_record(self.rows[0], root=self.store)
        self.assertEqual("recovered", result["status"])
        self.assertEqual(1, result["calendar_week_index"])
        self.assertEqual(1, load_lifecycle_register(self.store)["calendar_week_count"])
        # And the recovered clock keeps counting.
        self.assertEqual("published", persist_settled_weekly_record(self.rows[1], root=self.store)["status"])

    def test_a_recovered_register_is_still_bound_to_the_start_receipt(self) -> None:
        self._orphan(self.rows[0])
        persist_settled_weekly_record(self.rows[0], root=self.store)
        register = load_lifecycle_register(self.store)
        self.assertEqual(
            register["start_receipt_sha256"],
            start_receipt_sha256(load_start_receipt(self.store)),
        )

    def test_recovery_is_refused_when_the_clock_was_never_authorized(self) -> None:
        self._orphan(self.rows[0])
        (self.store / "diagnostic_start_receipt.json").unlink()
        with self.assertRaises(MarketDiagnosticLifecycleError) as ctx:
            persist_settled_weekly_record(self.rows[0], root=self.store)
        self.assertIn("start receipt", str(ctx.exception))

    def test_a_different_week_may_not_adopt_the_orphan(self) -> None:
        self._orphan(self.rows[0])
        with self.assertRaises(MarketDiagnosticLifecycleError) as ctx:
            persist_settled_weekly_record(self.rows[1], root=self.store)
        self.assertIn("conflicts with the retry input", str(ctx.exception))

    def test_an_orphan_that_is_not_week_one_is_not_a_recovery_candidate(self) -> None:
        persist_settled_weekly_record(self.rows[0], root=self.store)
        persist_settled_weekly_record(self.rows[1], root=self.store)
        (self.store / "lifecycle_register.json").unlink()
        week1 = self.store / lifecycle._record_relative_path(self.rows[0])
        week1.unlink()
        with self.assertRaises(MarketDiagnosticLifecycleError) as ctx:
            persist_settled_weekly_record(self.rows[1], root=self.store)
        self.assertIn("not a valid week-1 recovery candidate", str(ctx.exception))

    def test_more_than_one_orphan_is_never_silently_reconstructed(self) -> None:
        persist_settled_weekly_record(self.rows[0], root=self.store)
        persist_settled_weekly_record(self.rows[1], root=self.store)
        (self.store / "lifecycle_register.json").unlink()
        with self.assertRaises(MarketDiagnosticLifecycleError) as ctx:
            persist_settled_weekly_record(self.rows[0], root=self.store)
        self.assertIn("refuse silent reconstruction", str(ctx.exception))

    def test_dropping_the_repeated_pass_did_not_drop_the_checking(self) -> None:
        """The control for removing the whole-store revalidation from the read path.

        `load_lifecycle_register` used to validate every record twice per call and
        `load_settled_weekly_records` three times, which is the O(N²) that took the
        26-week rehearsal from 52 to 232 seconds. The repetition is gone; the
        checking is not. Both readers must still refuse a record that was changed
        under them — on every call, because nothing is cached between calls.
        """

        for row in self.rows[:2]:
            persist_settled_weekly_record(row, root=self.store)
        self.assertEqual(2, len(load_settled_weekly_records(self.store)))

        path = self.store / lifecycle._record_relative_path(self.rows[1])
        record = json.loads(path.read_bytes().decode("utf-8"))
        record["strategy"]["nav"] = "999999.000000"
        path.write_bytes(canonical_json_bytes(record))

        for reader in (load_lifecycle_register, load_settled_weekly_records):
            with self.subTest(reader=reader.__name__):
                with self.assertRaises(MarketDiagnosticLifecycleError):
                    reader(self.store)

    def test_a_tampered_orphan_cannot_be_adopted_by_its_own_retry(self) -> None:
        self._orphan(self.rows[0])
        path = self.store / lifecycle._record_relative_path(self.rows[0])
        record = json.loads(path.read_bytes().decode("utf-8"))
        record["strategy"]["nav"] = "999999.000000"
        path.write_bytes(canonical_json_bytes(record))
        with self.assertRaises(MarketDiagnosticLifecycleError):
            persist_settled_weekly_record(self.rows[0], root=self.store)


if __name__ == "__main__":
    unittest.main()
