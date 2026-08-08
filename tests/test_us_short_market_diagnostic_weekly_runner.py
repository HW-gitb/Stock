"""The operator's only door, tested as an operator actually uses it.

This file exists because the runner shipped with none. Every guard underneath it
had tests; the CLI wrapping them had zero, and that is exactly where the two
worst failures lived — a ``--dry-run`` that validated nothing and therefore
accepted the mistyped date it exists to catch, and a ``status`` that reported a
destroyed store as a healthy clock with no weeks yet.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from engine.us_short_model_paper_portfolio import canonical_json_bytes
from engine.us_short_market_diagnostic_lifecycle import persist_settled_weekly_record
from runners.us_short_market_diagnostic_weekly import (
    MarketDiagnosticWeeklyRunnerError,
    clock_status,
    main,
    open_clock,
    publish_window,
    record_week,
)
from tests.test_us_short_market_diagnostic import _weekly_rows


NOTIFICATION = "US-short 26-week diagnostic design is complete; open the clock.\n"
ISSUED_AT = "2025-12-29T00:00:00+00:00"


class _StoreCase(unittest.TestCase):
    """One temporary store per test, in a shape the test-IO guard can resolve.

    Deliberately setUp attributes rather than a fixture object: the repo's static
    test-IO inventory follows local temp roots and instance aliases, but a path
    handed back by a constructor it cannot resolve is reported as a write that
    might land in the real protected roots. Keeping the shape resolvable is
    cheaper than an exemption, and an exemption here would be indistinguishable
    from the thing that guard exists to catch.
    """

    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.rows = _weekly_rows()
        self.store = Path(holder.name) / "market_diagnostic_private"
        self.notify = Path(holder.name) / "notification.txt"
        self.notify.write_text(NOTIFICATION, encoding="utf-8")
        self.inbox = Path(holder.name) / "records"
        self.inbox.mkdir()

    @property
    def epoch(self) -> str:
        return self.rows[0]["diagnostic_epoch"]

    @property
    def week1(self) -> str:
        return self.rows[0]["decision_date"]

    def _open(self, **overrides):
        kwargs = {
            "confirm_design_complete": True,
            "notification_path": self.notify,
            "issued_at": ISSUED_AT,
            "diagnostic_epoch": self.epoch,
            "first_decision_date": self.week1,
            "root": self.store,
        }
        kwargs.update(overrides)
        return open_clock(**kwargs)

    def _record(self, index: int, *, as_of_date: str = "20260801"):
        path = self.inbox / f"week{index + 1}.json"
        path.write_bytes(canonical_json_bytes(self.rows[index]))
        return record_week(weekly_record_path=path, root=self.store, as_of_date=as_of_date)


class DryRunTest(_StoreCase):
    """A dry run that only echoes its inputs back is not a dry run."""

    def test_a_dry_run_refuses_the_mistakes_the_real_run_refuses(self) -> None:
        bad = [
            ({"first_decision_date": "20260104"}, "canonical decision week"),   # a Sunday
            ({"first_decision_date": "20260107"}, "canonical decision week"),   # a Wednesday
            ({"first_decision_date": "20260230"}, "real calendar date"),
            ({"first_decision_date": "2026-01-02"}, "eight-digit"),
            ({"issued_at": "2025-12-29T00:00:00"}, "timezone"),
            ({"issued_at": "whenever"}, "valid timestamp"),
            ({"diagnostic_epoch": "!!! not an identifier !!!"}, "schema violation"),
            ({"first_decision_date": "20200103"}, "back-fill"),
            ({"first_decision_date": "20301230"}, "too far after"),
        ]
        for overrides, expected in bad:
            with self.subTest(**overrides):
                with self.assertRaises(MarketDiagnosticWeeklyRunnerError) as ctx:
                    self._open(dry_run=True, confirm_design_complete=False, **overrides)
                self.assertIn(expected, str(ctx.exception))

    def test_a_dry_run_refuses_a_root_the_real_run_would_refuse(self) -> None:
        with self.assertRaises(MarketDiagnosticWeeklyRunnerError) as ctx:
            self._open(dry_run=True, root=Path(__file__).resolve().parent)
        self.assertIn("not private", str(ctx.exception))

    def test_a_dry_run_accepts_a_good_plan_and_writes_nothing(self) -> None:
        result = self._open(dry_run=True, confirm_design_complete=False)
        self.assertEqual("dry_run", result["status"])
        self.assertEqual(self.week1, result["first_decision_date"])
        self.assertFalse(self.store.exists(), "a dry run created the private store")
        self.assertEqual(
            {"clock_status": "not_started", "diagnostic_epoch": None, "calendar_week_count": 0},
            clock_status(root=self.store),
        )


class ClockStatusTest(_StoreCase):
    """"Started with no weeks" and "eighteen weeks unreadable" must not look the same."""

    def test_status_reports_a_clock_that_has_not_been_opened(self) -> None:
        self.assertEqual("not_started", clock_status(root=self.store)["clock_status"])

    def test_status_reports_a_running_clock_with_its_weeks(self) -> None:
        self._open()
        self._record(0)
        self._record(1)
        status = clock_status(root=self.store)
        self.assertEqual("started", status["clock_status"])
        self.assertEqual(2, status["calendar_week_count"])
        self.assertEqual(self.week1, status["first_decision_date"])

    def test_a_corrupt_register_is_reported_as_broken_not_as_zero_weeks(self) -> None:
        self._open()
        self._record(0)
        (self.store / "lifecycle_register.json").write_text("{ truncated", encoding="utf-8")
        status = clock_status(root=self.store)
        self.assertEqual("broken", status["clock_status"])
        self.assertIsNone(status["calendar_week_count"])
        self.assertTrue(status["problem"])
        self.assertEqual(2, main(["--root", str(self.store), "status"]))

    def test_a_tampered_register_is_reported_as_broken(self) -> None:
        self._open()
        self._record(0)
        path = self.store / "lifecycle_register.json"
        register = json.loads(path.read_bytes().decode("utf-8"))
        register["calendar_week_count"] = 26
        path.write_bytes(canonical_json_bytes(register))
        self.assertEqual("broken", clock_status(root=self.store)["clock_status"])

    def test_a_corrupt_receipt_is_reported_as_broken_not_as_never_started(self) -> None:
        self._open()
        self._record(0)
        (self.store / "diagnostic_start_receipt.json").write_text("{ truncated", encoding="utf-8")
        status = clock_status(root=self.store)
        self.assertEqual("broken", status["clock_status"])
        self.assertNotEqual("not_started", status["clock_status"])


class OperatorMistakeTest(_StoreCase):
    def test_opening_the_clock_needs_an_explicit_confirmation(self) -> None:
        with self.assertRaises(MarketDiagnosticWeeklyRunnerError) as ctx:
            self._open(confirm_design_complete=False)
        self.assertIn("--confirm-design-complete", str(ctx.exception))
        self.assertFalse(self.store.exists())

    def test_opening_twice_is_idempotent_and_re_anchoring_is_refused(self) -> None:
        self.assertEqual("issued", self._open()["status"])
        self.assertEqual("idempotent", self._open()["status"])
        with self.assertRaises(MarketDiagnosticWeeklyRunnerError) as ctx:
            self._open(first_decision_date="20260112")
        self.assertIn("already anchors", str(ctx.exception))

    def test_recording_the_same_week_twice_is_idempotent(self) -> None:
        self._open()
        self.assertEqual("published", self._record(0)["status"])
        self.assertEqual("idempotent", self._record(0)["status"])
        self.assertEqual(1, clock_status(root=self.store)["calendar_week_count"])

    def test_a_week_dated_after_the_as_of_date_fails_closed(self) -> None:
        self._open()
        with self.assertRaises(MarketDiagnosticWeeklyRunnerError):
            self._record(0, as_of_date="20251231")

    def test_a_week_cannot_be_recorded_before_the_clock_is_open(self) -> None:
        with self.assertRaises(MarketDiagnosticWeeklyRunnerError) as ctx:
            self._record(0)
        self.assertIn("start receipt", str(ctx.exception))

    def test_a_missing_or_malformed_record_file_is_named_precisely(self) -> None:
        self._open()
        missing = self.inbox / "absent.json"
        with self.assertRaises(MarketDiagnosticWeeklyRunnerError) as ctx:
            record_week(weekly_record_path=missing, root=self.store)
        self.assertIn("cannot read", str(ctx.exception))

        garbage = self.inbox / "garbage.json"
        garbage.write_text("not json", encoding="utf-8")
        with self.assertRaises(MarketDiagnosticWeeklyRunnerError) as ctx:
            record_week(weekly_record_path=garbage, root=self.store)
        self.assertIn("not valid JSON", str(ctx.exception))

        listy = self.inbox / "listy.json"
        listy.write_text("[]", encoding="utf-8")
        with self.assertRaises(MarketDiagnosticWeeklyRunnerError) as ctx:
            record_week(weekly_record_path=listy, root=self.store)
        self.assertIn("must be a JSON object", str(ctx.exception))

    def test_a_short_notification_is_not_a_notification(self) -> None:
        self.notify.write_text("done\n", encoding="utf-8")
        with self.assertRaises(MarketDiagnosticWeeklyRunnerError) as ctx:
            self._open(dry_run=True, confirm_design_complete=False)
        self.assertIn("too short", str(ctx.exception))

    def test_main_reports_a_refusal_as_a_nonzero_exit(self) -> None:
        self.assertEqual(
            2,
            main(
                [
                    "--root", str(self.store),
                    "open-clock",
                    "--dry-run",
                    "--notification-path", str(self.notify),
                    "--issued-at", ISSUED_AT,
                    "--diagnostic-epoch", self.epoch,
                    "--first-decision-date", "20260104",
                ]
            ),
        )
        self.assertFalse(self.store.exists())


class ScorecardTriggerTest(_StoreCase):
    """The one artifact this whole track exists to produce, and its trigger.

    The engine has been able to publish since Knife 4; nothing ever called it. So
    this covers the trigger, not the aggregation: does a scorecard appear exactly
    when a 26-week window closes, and never before.
    """

    def _fill(self, weeks: int) -> None:
        self._open()
        for row in self.rows[:weeks]:
            persist_settled_weekly_record(row, root=self.store, as_of_date="20260801")

    def test_no_scorecard_before_the_window_closes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_root = Path(td) / "public"
            self._fill(25)
            self.assertEqual(
                "not_ready", publish_window(root=self.store, output_root=output_root, as_of_date="20260801")["status"]
            )
            self.assertFalse(output_root.exists(), "a non-boundary week left public bytes behind")

    def test_the_scorecard_appears_at_week_26_and_a_rerun_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_root = Path(td) / "public"
            self._fill(26)
            first = publish_window(root=self.store, output_root=output_root, as_of_date="20260801")
            self.assertEqual("published", first["status"])
            self.assertEqual("26w-1-26", first["window_id"])
            self.assertEqual(26, first["last_calendar_week_index"])
            json_bytes = (output_root / "26w-1-26.json").read_bytes()
            markdown_bytes = (output_root / "26w-1-26.md").read_bytes()

            second = publish_window(root=self.store, output_root=output_root, as_of_date="20260801")
            self.assertEqual("idempotent", second["status"])
            self.assertEqual(json_bytes, (output_root / "26w-1-26.json").read_bytes())
            self.assertEqual(markdown_bytes, (output_root / "26w-1-26.md").read_bytes())

            self.assertEqual(
                0,
                main([
                    "--root", str(self.store), "publish",
                    "--output-root", str(output_root), "--as-of-date", "20260801",
                ]),
            )

    def test_publishing_from_a_store_that_never_started_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output_root = Path(td) / "public"
            self.assertEqual(
                {"status": "not_started"},
                publish_window(root=self.store, output_root=output_root, as_of_date="20260801"),
            )
            self.assertFalse(output_root.exists())


if __name__ == "__main__":
    unittest.main()
