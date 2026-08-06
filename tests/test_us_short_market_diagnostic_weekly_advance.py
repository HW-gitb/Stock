from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from engine.us_short_market_diagnostic_lifecycle import load_lifecycle_register
from engine.us_short_market_diagnostic_start_receipt import issue_start_receipt
from runners import us_short_market_diagnostic_weekly_fetch as advance
from tests.test_us_short_market_diagnostic_benchmark_packet import _FakeVendor
from tests.test_us_short_market_diagnostic_local_adapter import _packet, _start_local_paper_store

AS_OF = "20260806"


def _fred_rows(*days: str) -> list[dict]:
    rows = []
    for day in days:
        published = f"{day[:4]}-{day[4:6]}-{int(day[6:]) + 1:02d}"
        rows.append(
            {
                "realtime_start": published,
                "realtime_end": "9999-12-31",
                "date": f"{day[:4]}-{day[4:6]}-{day[6:]}",
                "value": "3.87",
            }
        )
    return rows


class WeeklyAdvanceTest(unittest.TestCase):
    """Knife 10b: the clock finally moves without anybody typing a command."""

    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.base = Path(holder.name)
        self.store = self.base / "market_diagnostic_private"
        self.paper = self.base / "model_paper_private"
        self.inputs = self.base / "market_diagnostic_inputs_private"
        self.public = self.base / "public"
        self.requests: list[str] = []
        self.packet = _packet()

    def _opener(self, url: str) -> bytes:
        self.requests.append(url)
        return json.dumps({"observations": _fred_rows("20260723", "20260724")}).encode("utf-8")

    def _open_clock(self) -> None:
        _start_local_paper_store(self.paper)
        issue_start_receipt(
            diagnostic_epoch=self.packet["diagnostic_epoch"],
            completion_notification={
                "issued_at": "2026-07-24T00:00:00+00:00",
                "issuer": "codex",
                "notification_text": "US-short 26-week diagnostic design is complete; open the clock.",
            },
            first_decision_date=self.packet["weeks"][0]["decision_date"],
            root=self.store,
        )

    def _fetch(self, vendor=None, **overrides):
        kwargs = dict(
            root=self.store,
            model_paper_root=self.paper,
            inputs_root=self.inputs,
            as_of_date=AS_OF,
            benchmark_module=vendor if vendor is not None else _FakeVendor(),
            cash_opener=self._opener,
            cash_api_key="k" * 32,
        )
        kwargs.update(overrides)
        return advance.fetch_next_week(**kwargs)

    def _settle(self, **overrides):
        kwargs = dict(
            root=self.store,
            model_paper_root=self.paper,
            inputs_root=self.inputs,
            output_root=self.public,
            as_of_date=AS_OF,
        )
        kwargs.update(overrides)
        return advance.settle_captured_week(**kwargs)

    def test_a_dormant_clock_costs_nothing_at_all(self) -> None:
        """Not merely 'no error': no request, and no byte.

        This is the property that lets the diagnostic hang off the weekly
        one-click at all. If a clock nobody opened could still reach a vendor or
        touch the disk, every week of stock selection would be paying for a
        track that is not running.
        """

        self.assertEqual("dormant", self._fetch()["status"])
        self.assertEqual("dormant", self._settle()["status"])
        self.assertEqual([], self.requests)
        self.assertFalse(self.inputs.exists(), "a dormant clock wrote bytes")
        self.assertFalse(self.public.exists())

    def test_a_broken_store_is_reported_and_still_fetches_nothing(self) -> None:
        self._open_clock()
        (self.store / "diagnostic_start_receipt.json").write_text("{", encoding="utf-8")
        result = self._fetch()
        self.assertEqual("broken", result["status"])
        self.assertEqual([], self.requests)
        self.assertEqual("broken", self._settle()["status"])

    def test_one_pass_captures_and_settles_a_real_week(self) -> None:
        """Fetch, then settle: the clock moves from zero to one."""

        self._open_clock()
        fetched = self._fetch()
        self.assertEqual("captured", fetched["status"])
        self.assertEqual(1, fetched["calendar_week_index"])
        self.assertEqual("evaluable", fetched["cash_status"])
        self.assertEqual(1, len(self.requests))

        settled = self._settle()
        self.assertIn(settled["status"], {"settled", "published", "recorded"})
        register = load_lifecycle_register(self.store, as_of_date=AS_OF)
        self.assertEqual(1, register["calendar_week_count"])

    def test_settling_before_the_inputs_exist_waits_rather_than_inventing_them(self) -> None:
        """Saying 'waiting' beats settling a week from inputs nobody captured."""

        self._open_clock()
        result = self._settle()
        self.assertEqual("waiting_for_inputs", result["status"])
        register_path = self.store / "lifecycle_register.json"
        self.assertFalse(register_path.exists(), "a week was recorded with no inputs")

    def test_a_second_pass_in_the_same_week_re_requests_nothing(self) -> None:
        self._open_clock()
        self._fetch()
        self._settle()
        self.assertEqual(1, len(self.requests))

        # ...and once the week is settled, the account has not produced another
        # one yet. That is the ordinary state for most of any week, so it is a
        # WAITING answer rather than a fault — an operator shown "failed" every
        # week stops reading the word.
        again = self._fetch()
        self.assertEqual("waiting_for_paper_week", again["status"])
        self.assertEqual(1, len(self.requests), "the vendor was asked again with nothing to fetch")
        self.assertEqual("waiting_for_paper_week", self._settle()["status"])

    def test_the_week_identity_comes_from_the_stores_not_the_caller(self) -> None:
        """No parameter names a date, so no caller can point at another week."""

        import inspect

        for name in ("next_week_identity", "fetch_next_week", "settle_captured_week"):
            with self.subTest(name):
                params = set(inspect.signature(getattr(advance, name)).parameters)
                for forbidden in (
                    "decision_date",
                    "valuation_date",
                    "calendar_week_index",
                    "diagnostic_epoch",
                ):
                    self.assertNotIn(forbidden, params)

        self._open_clock()
        identity = advance.next_week_identity(
            root=self.store, model_paper_root=self.paper, as_of_date=AS_OF
        )
        self.assertEqual(1, identity["calendar_week_index"])
        self.assertEqual(self.packet["diagnostic_epoch"], identity["diagnostic_epoch"])
        # Week one prices the benchmarks from the account's own seeding date, so
        # both sides of the comparison start on the same day.
        self.assertLess(identity["prior_valuation_date"], identity["valuation_date"])

    def _fake_head(self, *, settlement_decision: str, valuation: str):
        """A head whose dates I control, so week two can be reached in one step.

        Settling a second real paper week takes a whole account cycle; what the
        rules below actually depend on is the two dates the head reports, so those
        are what the fake supplies. Every other input still comes from the real
        diagnostic store.
        """

        return {
            "last_settlement": {"decision_date": settlement_decision},
            "current_state": {"as_of": valuation},
            "seed_state": {"relative_path": "seed/portfolio_state.json"},
        }

    def _identity_with(self, head, **overrides):
        import unittest.mock as mock

        with mock.patch.object(advance, "load_head", return_value=head):
            kwargs = dict(root=self.store, model_paper_root=self.paper, as_of_date=AS_OF)
            kwargs.update(overrides)
            return advance.next_week_identity(**kwargs)

    def test_week_two_decides_exactly_seven_days_after_week_one(self) -> None:
        """The canonical cadence, and the only week-one test cannot see it.

        With `7 * (index - 1)` the first week's offset is zero, so every day count
        agrees on week one and none of them agrees on week two.
        """

        self._open_clock()
        self._fetch()
        self._settle()
        identity = self._identity_with(
            self._fake_head(settlement_decision="20260727", valuation="20260731")
        )
        self.assertEqual(2, identity["calendar_week_index"])
        self.assertEqual("20260803", identity["decision_date"])
        # ...and the prior valuation is the LEDGER's week-one valuation, not
        # whatever the account happens to report now.
        self.assertEqual("20260724", identity["prior_valuation_date"])

    def test_a_week_whose_three_dates_do_not_line_up_is_refused(self) -> None:
        """settlement <= valuation <= decision, which the consumer also requires.

        Without it the packet is built and only rejected two layers down, by a
        message about a price date rather than about the week being misaligned.
        """

        self._open_clock()
        for label, head in (
            (
                "valued before the paper week decided",
                self._fake_head(settlement_decision="20260724", valuation="20260722"),
            ),
            (
                "valued after this week's decision",
                self._fake_head(settlement_decision="20260720", valuation="20260730"),
            ),
        ):
            with self.subTest(label):
                with self.assertRaises(advance.WeeklyAdvanceError) as ctx:
                    self._identity_with(head)
                self.assertIn("does not line up", str(ctx.exception))

    def test_the_cash_reader_keys_off_the_ledger_not_off_a_directory(self) -> None:
        """A stray folder must not be able to introduce a week nobody counted."""

        self._open_clock()
        self._fetch()
        self._settle()
        loaded = advance.load_cash_returns(
            root=self.store, inputs_root=self.inputs, as_of_date=AS_OF
        )
        self.assertEqual([1], sorted(loaded))
        self.assertEqual("pit_3m_tbill", loaded[1]["instrument"])

        stray = advance.cash_week_directory("20991231", inputs_root=self.inputs)
        stray.mkdir(parents=True, exist_ok=True)
        (stray / advance.OBSERVATION_FILENAME).write_text(
            json.dumps({"calendar_week_index": 99, "observation": {"status": "evaluable"}}),
            encoding="utf-8",
        )
        self.assertEqual(
            [1],
            sorted(
                advance.load_cash_returns(
                    root=self.store, inputs_root=self.inputs, as_of_date=AS_OF
                )
            ),
            "a directory nobody settled introduced a week",
        )

    def test_a_cash_file_whose_week_disagrees_with_the_ledger_is_ignored(self) -> None:
        """Same file, wrong week: the ledger decides which week a file is for."""

        self._open_clock()
        self._fetch()
        self._settle()
        path = (
            advance.cash_week_directory(
                self.packet["weeks"][0]["decision_date"], inputs_root=self.inputs
            )
            / advance.OBSERVATION_FILENAME
        )
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored["calendar_week_index"] = 7
        path.write_text(json.dumps(stored), encoding="utf-8")
        self.assertEqual(
            {},
            advance.load_cash_returns(root=self.store, inputs_root=self.inputs, as_of_date=AS_OF),
        )


class CapstoneStageTest(unittest.TestCase):
    """The stages exist, are ordered, and the fetch one is declared gated."""

    def test_the_two_advancing_stages_sit_before_the_reader(self) -> None:
        from runners.us_short_weekly_capstone import default_pipeline

        names = [stage.name for stage in default_pipeline(include_model_paper=True)]
        for name in ("market_diagnostic_fetch", "market_diagnostic_settle", "market_diagnostic"):
            self.assertIn(name, names)
        self.assertLess(names.index("market_diagnostic_fetch"), names.index("market_diagnostic_settle"))
        self.assertLess(names.index("market_diagnostic_settle"), names.index("market_diagnostic"))
        # ...and after the paper account has settled, per design section 1.3.
        self.assertLess(names.index("model_paper_weekly"), names.index("market_diagnostic_fetch"))

    def test_only_the_fetching_stage_is_gated(self) -> None:
        """A real vendor call must not ride in behind an ungated stage."""

        from runners.us_short_weekly_capstone import default_pipeline

        gated = {stage.name: stage.gated for stage in default_pipeline(include_model_paper=True)}
        self.assertTrue(gated["market_diagnostic_fetch"])
        self.assertFalse(gated["market_diagnostic_settle"])
        self.assertFalse(gated["market_diagnostic"])

    def test_every_diagnostic_stage_is_a_total_adapter(self) -> None:
        """A diagnostic may never take down a week of stock selection.

        An unreadable root is NOT enough to test this: it reads as a clock that
        was never opened, so the stage returns dormant and the adapter is never
        exercised. Each underlying call is made to raise something no narrow
        `except` clause would name.
        """

        import unittest.mock as mock

        from runners import us_short_weekly_capstone as capstone
        from runners import us_short_market_diagnostic_weekly_fetch as fetch_module
        from engine import us_short_market_diagnostic_weekly_task as task_module

        class _Ctx:
            decision_date = "20260727"
            market_diagnostic_root = None

        boom = RuntimeError("the store exploded in a way nobody enumerated")
        for runner, key, module, symbol in (
            (capstone._run_market_diagnostic_fetch, "fetch_status", fetch_module, "fetch_next_week"),
            (capstone._run_market_diagnostic_settle, "settle_status", fetch_module, "settle_captured_week"),
            (capstone._run_market_diagnostic, "clock_status", task_module, "weekly_diagnostic_step"),
        ):
            with self.subTest(runner.__name__):
                with mock.patch.object(module, symbol, side_effect=boom):
                    result = runner(_Ctx())
                self.assertIn(key, result)
                # The reader calls its fault "broken"; the two advancing stages
                # call theirs "failed". Either way it is REPORTED, with the cause
                # carried, rather than raised into the weekly run.
                self.assertIn(result[key], {"failed", "broken"})
                self.assertIn("RuntimeError", result["problem"])
                self.assertFalse(result["provider_calls_performed"])

    def test_the_reader_is_handed_the_cash_leg_that_was_captured(self) -> None:
        """Otherwise v1.1 reports `unavailable` beside a file holding the answer."""

        import unittest.mock as mock

        from runners import us_short_weekly_capstone as capstone
        from engine import us_short_market_diagnostic_weekly_task as task_module

        class _Ctx:
            decision_date = "20260727"
            market_diagnostic_root = None

        with mock.patch.object(
            task_module, "weekly_diagnostic_step", return_value={"status": "not_started", "report_lines": []}
        ) as step:
            capstone._run_market_diagnostic(_Ctx())
        self.assertIn("cash_return_by_week", step.call_args.kwargs)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
