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

# The week's OWN canonical decision date, which is what the capstone passes every
# week. The previous value ran ten days late, and under the repaired clock a run
# that late is itself the missed-week condition — so it was quietly testing the
# recovery path in every case that meant to test the ordinary one.
AS_OF = "20260727"
# Same week, run six days late (still live) and seven days late (over).
LATE_IN_THE_WEEK = "20260802"
NEXT_DECISION_DAY = "20260803"


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


class _WeeklyAdvanceFixture:
    """The sandbox and the four calls both classes below drive it with.

    Deliberately NOT a ``TestCase``: subclassing one to reuse a fixture makes
    unittest discover the owner's tests a second time under the borrower's module
    (`R-USSHORT-A-SHARED-FIXTURE-DRAGGED-ITS-OWNERS-TESTS-INTO-A-SECOND-MODULE`).
    """

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
            confirm_user_authorization=True,
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


class WeeklyAdvanceTest(_WeeklyAdvanceFixture, unittest.TestCase):
    """Knife 10b: the clock finally moves without anybody typing a command."""

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

    def test_a_failure_after_the_benchmark_calls_still_reports_them(self) -> None:
        """Four requests went out; the failure must not report them as none.

        The count is recorded before each request and carried through the
        failure, so a paid boundary is never described by inferring from whether
        the capture returned normally.
        """

        import unittest.mock as mock

        self._open_clock()
        with mock.patch.object(
            advance, "capture_cash_week", side_effect=advance.CashFetchError("FRED refused")
        ):
            result = self._fetch()
        self.assertEqual("capture_failed", result["status"])
        self.assertEqual(4, result["provider_calls"], "the benchmark requests were reported as none")

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
        with self.assertRaises(advance.WeeklyAdvanceError) as ctx:
            self._identity_with(
                self._fake_head(settlement_decision="20260724", valuation="20260722")
            )
        self.assertIn("does not line up", str(ctx.exception))

    def test_an_account_past_this_week_is_placed_against_the_week_it_wraps(self) -> None:
        """The jam, and the only thing that ends it.

        The head has moved on to a valuation AFTER this diagnostic week's decision
        date, which is what one absent price packet does to a clock whose account
        keeps settling weekly. Read off the head alone the ordering rule can never
        hold again; walking back to the paper week this week actually wraps is
        what makes the stuck week describable, and therefore recoverable.
        """

        self._open_clock()
        identity = self._identity_with(
            self._fake_head(settlement_decision="20260720", valuation="20260730")
        )
        self.assertEqual(1, identity["calendar_week_index"])
        self.assertEqual("20260720", identity["settlement_decision_date"])
        self.assertEqual("20260724", identity["valuation_date"])
        self.assertLessEqual(identity["valuation_date"], identity["decision_date"])

    def test_a_corrupted_settled_week_is_refused_rather_than_stepped_over(self) -> None:
        """The walk-back is a search, and a search must not route around damage.

        Skipping an unreadable week to reach an older one that happens to fit would
        bind this diagnostic week to the WRONG paper week, silently. Asserted on
        the reason rather than on any refusal: turn the raise into a `continue` and
        the search still ends in an error, just a different one about finding
        nothing — which says nothing about the damaged week.
        """

        self._open_clock()
        settlement = self.paper / "weeks" / "20260720" / "settlement.json"
        settlement.write_text("{ not canonical json", encoding="utf-8")
        with self.assertRaises(advance.WeeklyAdvanceError) as ctx:
            self._identity_with(
                self._fake_head(settlement_decision="20260720", valuation="20260730")
            )
        self.assertIn("cannot be read", str(ctx.exception))
        self.assertIn("20260720", str(ctx.exception))

    def test_the_benchmark_cli_declares_the_flag_its_gate_reads(self) -> None:
        """It read `args.confirm_user_authorization` and never declared it.

        Every CLI invocation died of AttributeError before reaching the gate, so
        the door was unreachable rather than shut. Fail-closed by accident is still
        a broken entry point.
        """

        import io
        from contextlib import redirect_stdout

        from runners import us_short_market_diagnostic_benchmark_fetch as fetch_cli

        printed = io.StringIO()
        with redirect_stdout(printed):
            exit_code = fetch_cli.main([
                "--decision-date", "20260727", "--valuation-date", "20260724",
                "--prior-valuation-date", "20260717", "--settlement-decision-date", "20260720",
                "--calendar-week-index", "1", "--diagnostic-epoch", "e",
                "--inputs-root", str(self.inputs), "--as-of-date", AS_OF,
            ])
        # Reached the gate and was refused BY it — not killed on the way there.
        self.assertEqual(1, exit_code)
        self.assertIn("requires explicit user authorization", printed.getvalue())

    def test_an_account_with_no_week_this_one_could_wrap_is_still_refused(self) -> None:
        """The walk-back is a search, not a licence to settle against anything.

        Same shape as above, except the head names a last settlement older than
        every week on disk, so nothing qualifies. Inventing a paper week here — or
        falling back to the head that does not fit — is what the search must not
        do.
        """

        self._open_clock()
        with self.assertRaises(advance.WeeklyAdvanceError) as ctx:
            self._identity_with(
                self._fake_head(settlement_decision="20260713", valuation="20260730")
            )
        self.assertIn("no settled week valued on or before", str(ctx.exception))

    def test_the_target_exposure_leg_reaches_the_attribution_gate(self) -> None:
        """Knife 10a end to end: the note the decision took becomes g*.

        The gate re-derives ``g* = min(...)`` and the binding constraints from
        these five numbers rather than trusting them, which is what stops a
        filled position passing itself off as the rule-implied one. Here the
        account wants 0.60 and may hold 0.50, so the cash capacity binds — the
        exact case v1.1 exists to explain.
        """

        from engine.us_short_decision_exposure import (
            build_decision_exposure_record, write_decision_exposure)

        self._open_clock()
        self._fetch()
        self._settle()
        decision_date = self.packet["weeks"][0]["decision_date"]
        runs = self.base / "runs_private"
        write_decision_exposure(
            build_decision_exposure_record(
                decision_date=decision_date,
                account_state={
                    "us_short_bucket_capital": 100000.0,
                    "us_short_available_cash": 30000.0,
                },
                regime={"market_risk_regime": "谨慎", "position_cap": 0.8},
                rows=[{
                    "cash_allocation_status": "allocated",
                    "cash_required_at_entry_high": 40000.0,
                }],
                portfolio_capacity={"existing_positions": [
                    {"ticker": "AAA", "shares": 100, "mark_price": 200.0}
                ]},
            ),
            runs_private_root=runs,
        )
        targets = advance.load_target_exposures(
            root=self.store, runs_private_root=runs, as_of_date=AS_OF
        )
        self.assertEqual([1], sorted(targets))
        self.assertEqual(decision_date, targets[1]["as_of_date"])

        from engine.us_short_market_diagnostic_attribution import (
            build_attribution_input, build_attribution_report)
        from tests.test_us_short_market_diagnostic import _weekly_rows

        rows = _weekly_rows()[:1]
        rows[0]["decision_date"] = decision_date
        rows[0]["valuation_date"] = self.packet["weeks"][0]["valuation_date"]
        packet = build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week={1: targets[1]},
            cash_return_by_week=advance.load_cash_returns(
                root=self.store, inputs_root=self.inputs, as_of_date=AS_OF),
            as_of_date=AS_OF,
        )
        report = build_attribution_report(packet, as_of_date=AS_OF)
        week = report["weeks"][0]
        self.assertAlmostEqual(0.50, week["g_star"], places=9)
        self.assertEqual(["cash_capacity_exposure"], week["binding_constraints"])
        self.assertAlmostEqual(0.60, week["requested_exposure"], places=9)

    def test_a_week_with_no_exposure_note_is_absent_rather_than_guessed(self) -> None:
        self._open_clock()
        self._fetch()
        self._settle()
        self.assertEqual(
            {},
            advance.load_target_exposures(
                root=self.store, runs_private_root=self.base / "runs_private", as_of_date=AS_OF
            ),
        )

    def test_an_unavailable_exposure_note_is_not_offered_as_a_target(self) -> None:
        """Its own producer already said it could not be trusted."""

        from engine.us_short_decision_exposure import (
            build_decision_exposure_record, write_decision_exposure)

        self._open_clock()
        self._fetch()
        self._settle()
        runs = self.base / "runs_private"
        write_decision_exposure(
            build_decision_exposure_record(
                decision_date=self.packet["weeks"][0]["decision_date"],
                account_state={"us_short_bucket_capital": 0.0, "us_short_available_cash": 0.0},
                regime={"position_cap": 0.8},
                rows=[],
                portfolio_capacity={"existing_positions": []},
            ),
            runs_private_root=runs,
        )
        self.assertEqual(
            {},
            advance.load_target_exposures(root=self.store, runs_private_root=runs, as_of_date=AS_OF),
        )

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


class MissedWeekTest(_WeeklyAdvanceFixture, unittest.TestCase):
    """When a week ends without inputs, and what must NOT happen before it does.

    Design section 3 and section 12.8 duty 3: the week is written off as
    ``no_count``, keeps its calendar slot, and the 26-week boundary does not move.
    The kill moment is the next week's decision day, so everything up to it is the
    reverse control — inputs that arrive late are still this week's inputs.
    """

    def _record(self, decision_date: str = "20260727") -> dict:
        return json.loads(
            (self.store / "weeks" / decision_date / "weekly_record.json").read_text(
                encoding="utf-8"
            )
        )

    def test_inputs_that_arrive_late_in_the_same_week_still_settle_as_an_ordinary_week(
        self,
    ) -> None:
        """Six days late is late, not missed. Nothing is written off."""

        self._open_clock()
        self._fetch(as_of_date=LATE_IN_THE_WEEK)
        settled = self._settle(as_of_date=LATE_IN_THE_WEEK)
        self.assertIn(settled["status"], {"settled", "published", "recorded"})
        self.assertEqual([], settled["no_count_weeks"], "a live week was written off")
        strategy = self._record()["strategy"]
        self.assertFalse(strategy["no_count"])
        self.assertIsNotNone(strategy["weekly_return"], "the week settled with no return")
        register = load_lifecycle_register(self.store, as_of_date=LATE_IN_THE_WEEK)
        self.assertEqual(1, register["calendar_week_count"])

    def test_a_week_whose_inputs_arrived_after_it_ended_is_settled_not_written_off(self) -> None:
        """Design section 3 keeps no_count for weeks that CANNOT be evaluated.

        This one can: the account settled it and the prices are on disk. Spending a
        calendar slot on it would destroy real evidence behind an immutable record
        and stamp it with a reason — "the inputs were missing" — that is not true.
        """

        self._open_clock()
        self._fetch(as_of_date=NEXT_DECISION_DAY)
        settled = self._settle(as_of_date=NEXT_DECISION_DAY)
        self.assertEqual([], settled["no_count_weeks"], "an evaluable week was written off")
        self.assertEqual([1], settled["settled_weeks"])
        strategy = self._record()["strategy"]
        self.assertFalse(strategy["no_count"])
        self.assertIsNotNone(strategy["weekly_return"])
        register = load_lifecycle_register(self.store, as_of_date=NEXT_DECISION_DAY)
        self.assertEqual(1, register["calendar_week_count"])
        self.assertEqual("26w-1-26", register["current_window_id"], "the window was extended")

    def test_a_future_as_of_cannot_spend_a_week_the_account_has_not_lived_through(self) -> None:
        """The kill rule needs the ACCOUNT's agreement, not just the caller's date.

        `as_of_date` is caller-supplied; on its own it would let one mistyped date
        burn a run of live weeks into immutable no_count records. The account
        cannot have moved past a week that has not happened, so it is the half of
        the rule nobody can fake.
        """

        far_future = "20261231"
        self._open_clock()
        self._fetch(as_of_date=far_future)
        settled = self._settle(as_of_date=far_future)
        self.assertEqual([], settled["no_count_weeks"], "a live week was burned by a future date")
        self.assertEqual([1], settled["settled_weeks"])
        self.assertFalse(self._record()["strategy"]["no_count"])

    def test_settling_twice_in_the_same_week_does_not_spend_two_calendar_weeks(self) -> None:
        """Idempotence, on the path that WRITES rather than the one that reads."""

        self._open_clock()
        self._fetch(as_of_date=NEXT_DECISION_DAY)
        self._settle(as_of_date=NEXT_DECISION_DAY)
        self._fetch(as_of_date=NEXT_DECISION_DAY)
        again = self._settle(as_of_date=NEXT_DECISION_DAY)
        self.assertEqual([], again["no_count_weeks"], "the same week was written off twice")
        self.assertEqual([], again["settled_weeks"], "the same week was settled twice")
        self.assertEqual(
            1,
            load_lifecycle_register(self.store, as_of_date=NEXT_DECISION_DAY)[
                "calendar_week_count"
            ],
        )

    def _jam_the_account_past_week_one(self):
        """Head says the account has moved past week one, so the week is 'over'."""

        return {
            "last_settlement": {"decision_date": "20260720"},
            "current_state": {"as_of": "20260730"},
            "seed_state": {"relative_path": "seed/portfolio_state.json"},
        }

    def test_a_corrupted_account_week_is_reported_as_a_fault_not_spent_as_a_week(self) -> None:
        """A fault must never be laundered into an immutable `no_count` record.

        Design section 3 keeps `no_count` for weeks that CANNOT be evaluated. An
        artifact that will not parse is a week that cannot be read *today* — repair
        the file and it evaluates fine — so spending a calendar slot on it burns
        one of the 26 irreversibly and stamps it with a reason that is false.
        """

        import unittest.mock as mock

        self._open_clock()
        self._fetch(as_of_date=AS_OF)
        (self.paper / "weeks" / "20260720" / "settlement.json").write_text(
            "{ broken", encoding="utf-8"
        )
        with mock.patch.object(advance, "load_head", return_value=self._jam_the_account_past_week_one()):
            with self.assertRaises(advance.WeeklyAdvanceError) as ctx:
                self._settle(as_of_date=NEXT_DECISION_DAY)
        self.assertIn("cannot be read", str(ctx.exception))
        self.assertFalse((self.store / "weeks" / "20260727" / "weekly_record.json").is_file())
        self.assertFalse((self.store / "lifecycle_register.json").exists())

    def test_a_week_whose_dates_contradict_each_other_is_also_not_spent(self) -> None:
        """The same `except` swallowed this leg too, so it is closed as a class.

        Injected at the seam that really raises it rather than by neutering a
        guard: `_identity_for` refuses a week whose three dates do not line up, and
        what is under test is whether the classifier above it turns that refusal
        into a spent calendar week.
        """

        import unittest.mock as mock

        self._open_clock()
        self._fetch(as_of_date=AS_OF)
        misaligned = advance.WeeklyAdvanceError(
            "week 1 does not line up: the paper week decided 20260724 and was "
            "valued 20260722, but this diagnostic week decides 20260727"
        )
        with mock.patch.object(advance, "load_head", return_value=self._jam_the_account_past_week_one()), \
                mock.patch.object(advance, "_identity_for", side_effect=misaligned):
            with self.assertRaises(advance.WeeklyAdvanceError) as ctx:
                self._settle(as_of_date=NEXT_DECISION_DAY)
        self.assertIn("does not line up", str(ctx.exception))
        self.assertFalse((self.store / "lifecycle_register.json").exists())

    def test_a_genuine_absence_is_still_written_off(self) -> None:
        """The positive control the tightening must not break.

        `WeeklyAdvanceNoPaperWeek` says the account settled no week this one could
        ever wrap — an absence, not a fault — and it must still become `no_count`.
        """

        import unittest.mock as mock

        self._open_clock()
        self._fetch(as_of_date=AS_OF)
        refusals = [
            advance.WeeklyAdvanceNoPaperWeek(
                "the account has no settled week valued on or before 20260727, so the "
                "diagnostic week deciding that day has no paper week to wrap"
            ),
            # Week two: the account has simply not produced it, which ends the run.
            advance.WeeklyAdvanceNotReady("the model-paper account has not settled a week yet"),
        ]
        with mock.patch.object(advance, "load_head", return_value=self._jam_the_account_past_week_one()), \
                mock.patch.object(advance, "_identity_for", side_effect=refusals):
            settled = self._settle(as_of_date=NEXT_DECISION_DAY)
        self.assertEqual([1], settled["no_count_weeks"])
        self.assertTrue(self._record()["strategy"]["no_count"])

    def test_a_scorecard_emitted_mid_catch_up_is_still_announced(self) -> None:
        """The only artifact this track produces must not be silently dropped.

        A run that catches up past a window boundary settles week 26 — which emits
        the scorecard — and then week 27, whose own publication is a `not_ready`.
        Reporting the last settlement's publication would leave the scorecard on
        disk and unmentioned in the week it was made. Asserted on the helper
        because the end-to-end costs a 27-week rehearsal (measured 315s) for an
        Optional; the loop hands it the value this pins.
        """

        published = {"status": "published", "window_id": "26w-1-26"}
        outcome = advance._settle_outcome(
            "settled", {"status": "published", "calendar_week_index": 27,
                        "publication": {"status": "not_ready"}},
            [26, 27], [], publication=published,
        )
        self.assertEqual(published, outcome["publication"])
        # ...and the clock's position is the last week settled, not whatever the
        # last `settle_week` happened to echo back.
        self.assertEqual(27, outcome["calendar_week_index"])
        self.assertEqual([26, 27], outcome["settled_weeks"])

    def test_a_stopped_clock_does_not_report_the_same_thing_as_a_healthy_one(self) -> None:
        """The label, which is what an operator actually reads.

        Waiting on a week still in progress and waiting on a week that ended weeks
        ago are the same sentence to the code and opposite news to a reader. They
        used to be the same status, so a dead clock was indistinguishable from the
        ordinary state every healthy week ends in.
        """

        self._open_clock()
        live = self._settle(as_of_date=AS_OF)
        self.assertEqual("waiting_for_inputs", live["status"])
        stopped = self._settle(as_of_date=NEXT_DECISION_DAY)
        self.assertEqual("stalled_on_a_finished_week", stopped["status"])
        # Neither invents a week: with no packet there is nothing to project a
        # no_count week's benchmarks from, and section 5 requires them.
        self.assertEqual([], stopped["no_count_weeks"])
        self.assertFalse((self.store / "lifecycle_register.json").exists())

    def test_without_an_as_of_date_no_week_is_ever_written_off(self) -> None:
        """A caller that did not say when it is may not spend calendar weeks."""

        self._open_clock()
        self._fetch(as_of_date=None)
        settled = self._settle(as_of_date=None)
        self.assertIn(settled["status"], {"settled", "published", "recorded"})
        self.assertEqual([], settled["no_count_weeks"])
        self.assertFalse(self._record()["strategy"]["no_count"])

    def test_a_packet_for_another_week_cannot_be_written_off_as_this_one(self) -> None:
        """Which week is spent comes from the store, never from the packet handed in.

        A caller that could choose the index could burn a calendar week that the
        clock is not waiting for — the same shape `build_next_weekly_record` had
        its own parameters removed for.
        """

        from engine.us_short_market_diagnostic_weekly_producer import (
            MarketDiagnosticWeeklyProducerError, settle_missed_week)

        self._open_clock()
        self._fetch(as_of_date=NEXT_DECISION_DAY)
        packet_path = (
            advance.benchmark_week_directory("20260727", inputs_root=self.inputs)
            / advance.PACKET_FILENAME
        )
        elsewhere = json.loads(packet_path.read_text(encoding="utf-8"))
        elsewhere["weeks"][0]["calendar_week_index"] = 2
        with self.assertRaises(MarketDiagnosticWeeklyProducerError) as ctx:
            settle_missed_week(
                benchmark_packet=elsewhere,
                root=self.store,
                reason="planted",
                as_of_date=NEXT_DECISION_DAY,
            )
        # Refused because the packet does not describe the week the STORE is
        # waiting for. Asserted on that reason rather than on any refusal: read
        # the index off the packet instead and a week-2 record is built happily,
        # then bounced one layer down by the append rule — a different door, and
        # one that says nothing about which week this packet is for.
        self.assertIn("cannot be projected", str(ctx.exception))
        self.assertFalse((self.store / "lifecycle_register.json").exists())

    def test_the_current_week_is_captured_in_the_same_run_as_the_one_it_writes_off(self) -> None:
        """Otherwise the clock heals one week per week and never catches up.

        Two diagnostic weeks are due at once here, and the fetch step has to land
        both: the older one so it can be written off with its benchmarks
        projected, the current one so it can settle in this very run.
        """

        self._open_clock()
        fetched = self._fetch(as_of_date=NEXT_DECISION_DAY)
        self.assertEqual("captured", fetched["status"])
        # Week two is not reachable in this fixture (the account has not settled
        # another week), so exactly one week is due and nothing was back-filled.
        self.assertEqual(0, fetched["backfilled_week_count"])
        self.assertEqual(1, fetched["calendar_week_index"])


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
        # `calls_unknown` marks the one stage that can reach a vendor. When it
        # dies before anything counted, "no provider call" is a claim nobody can
        # support, so it must NOT report False -- an unknown at a paid boundary is
        # not a zero. The two that never call anything report False truthfully.
        for runner, key, module, symbol, calls_unknown in (
            (capstone._run_market_diagnostic_fetch, "fetch_status", fetch_module, "fetch_next_week", True),
            (capstone._run_market_diagnostic_settle, "settle_status", fetch_module, "settle_captured_week", False),
            (capstone._run_market_diagnostic, "clock_status", task_module, "weekly_diagnostic_step", False),
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
                self.assertEqual(calls_unknown, result["provider_calls_performed"])

    def test_a_capture_that_dies_part_way_still_reports_the_calls_it_made(self) -> None:
        """The reviewer's second point on F3, at the boundary that matters.

        Reporting `provider_calls_performed: False` after real requests went out
        is a false statement about a paid boundary. The count is now carried
        through the failure rather than inferred from whether the capture
        returned normally.
        """

        import unittest.mock as mock

        from runners import us_short_weekly_capstone as capstone
        from runners import us_short_market_diagnostic_weekly_fetch as fetch_module

        class _Ctx:
            decision_date = "20260727"
            market_diagnostic_root = None

        with mock.patch.object(
            fetch_module,
            "fetch_next_week",
            return_value={"status": "capture_failed", "problem": "vendor died",
                          "provider_calls": 3, "report_lines": []},
        ):
            result = capstone._run_market_diagnostic_fetch(_Ctx())
        self.assertEqual("capture_failed", result["fetch_status"])
        self.assertTrue(result["provider_calls_performed"], "three real requests were reported as none")

    def test_a_written_off_week_is_reported_to_the_operator(self) -> None:
        """A spent calendar week that nobody is told about is a silently shorter window.

        Section 12.8 duty 3 keeps a no_count week in the 26-week denominator, so a
        reader who never sees it cannot tell a 26-week verdict from a 24-week one.
        """

        import unittest.mock as mock

        from runners import us_short_weekly_capstone as capstone
        from runners import us_short_market_diagnostic_weekly_fetch as fetch_module

        class _Ctx:
            decision_date = "20260727"
            market_diagnostic_root = None

        with mock.patch.object(
            fetch_module,
            "settle_captured_week",
            return_value={"status": "published", "calendar_week_index": 4,
                          "no_count_weeks": [2, 3], "report_lines": []},
        ):
            result = capstone._run_market_diagnostic_settle(_Ctx())
        self.assertEqual([2, 3], result["no_count_weeks"])
        line = "".join(result["report_lines"])
        self.assertIn("no_count", line)
        self.assertIn("第 2、3 周", line)
        # ...and a healthy week says nothing new, so the report stays quiet.
        with mock.patch.object(
            fetch_module,
            "settle_captured_week",
            return_value={"status": "published", "calendar_week_index": 4,
                          "no_count_weeks": [], "report_lines": []},
        ):
            healthy = capstone._run_market_diagnostic_settle(_Ctx())
        self.assertEqual([], healthy["report_lines"])

    def test_a_stopped_clock_reads_differently_from_a_week_in_progress(self) -> None:
        """Two waits, opposite news. The report has to say which one it is."""

        import unittest.mock as mock

        from runners import us_short_weekly_capstone as capstone
        from runners import us_short_market_diagnostic_weekly_fetch as fetch_module

        class _Ctx:
            decision_date = "20260727"
            market_diagnostic_root = None

        lines = {}
        for status in ("waiting_for_inputs", "stalled_on_a_finished_week"):
            with mock.patch.object(
                fetch_module, "settle_captured_week",
                return_value={"status": status, "calendar_week_index": 2,
                              "no_count_weeks": [], "report_lines": []},
            ):
                lines[status] = "".join(
                    capstone._run_market_diagnostic_settle(_Ctx())["report_lines"]
                )
        self.assertTrue(all(lines.values()), "a stalled clock said nothing at all")
        self.assertNotEqual(lines["waiting_for_inputs"], lines["stalled_on_a_finished_week"])
        self.assertIn("已经过去", lines["stalled_on_a_finished_week"])

    def test_the_reader_is_handed_both_legs_that_were_captured(self) -> None:
        """Otherwise v1.1 reports `unavailable` beside files holding the answer.

        Both legs, not one: the cash rate and the rule-implied target exposure are
        produced separately and either one going missing silently leaves the
        attribution dark for a different reason.
        """

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
        self.assertIn("target_exposure_by_week", step.call_args.kwargs)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
