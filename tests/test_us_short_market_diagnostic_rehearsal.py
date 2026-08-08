"""The rehearsal harness: does the 26-week chain actually run, and does it stay in its sandbox.

Two questions, and the second one first. A harness whose whole purpose is to
exercise the real weekly path is one wrong root away from writing into the real
one, so the gate is tested before anything else and from three directions.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import socket
import tempfile
import unittest
from unittest import mock
import urllib.request

from runners.us_short_market_diagnostic_rehearsal import (
    REHEARSAL_BANNER,
    RehearsalError,
    rehearsal_root,
    run_rehearsal,
)

ROOT = Path(__file__).resolve().parents[1]
FIRST_MONDAY = "20260803"
# Only the roots this chain would write to if the gate ever failed. A wider
# snapshot would also see whatever an unrelated module is doing in another
# process during a parallel pack, and turn this red for somebody else's reason.
PROTECTED = ("state/us_short", "research/results/us_short")


def _files_under(relative: str) -> frozenset[str]:
    root = ROOT / relative
    if not root.exists():
        return frozenset()
    return frozenset(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


class GateTest(unittest.TestCase):
    """The one gate, from every direction it can be pushed."""

    def test_a_relative_root_is_refused(self) -> None:
        with self.assertRaises(RehearsalError) as ctx:
            rehearsal_root("rehearsal_sandbox")
        self.assertIn("absolute", str(ctx.exception))

    def test_a_root_inside_the_repository_is_refused(self) -> None:
        """One check, and it covers all five real roots at once.

        The diagnostic store, the weekly inputs root, the model-paper store,
        `runs_private` and the public scorecard root all live under the
        repository, so a list of five would be five things to keep in sync.
        """

        for inside in (
            ROOT,
            ROOT / "state" / "us_short" / "market_diagnostic_private",
            ROOT / "state" / "us_short" / "market_diagnostic_inputs_private",
            ROOT / "state" / "us_short" / "model_paper_private",
            ROOT / "state" / "us_short" / "runs_private",
            ROOT / "research" / "results" / "us_short" / "market_diagnostic_26w",
        ):
            with self.subTest(candidate=inside.name):
                with self.assertRaises(RehearsalError) as ctx:
                    rehearsal_root(inside)
                self.assertIn("inside the repository", str(ctx.exception))

    def test_a_non_empty_root_is_refused_rather_than_cleared(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rehearsal_gate_") as temp:
            occupied = Path(temp) / "occupied"
            occupied.mkdir()
            (occupied / "someone_elses.txt").write_text("keep me", encoding="utf-8")
            with self.assertRaises(RehearsalError) as ctx:
                rehearsal_root(occupied)
            self.assertIn("not empty", str(ctx.exception))
            self.assertTrue((occupied / "someone_elses.txt").is_file(), "the gate deleted something")

    def test_a_fresh_repo_external_root_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rehearsal_gate_") as temp:
            self.assertEqual(Path(temp).resolve() / "fresh", rehearsal_root(Path(temp) / "fresh"))

    def test_bad_dates_and_counts_are_refused_before_anything_is_written(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rehearsal_gate_") as temp:
            sandbox = Path(temp) / "run"
            with self.assertRaises(RehearsalError) as ctx:
                run_rehearsal(root=sandbox, first_decision_date="20260801", weeks=1)   # a Saturday
            self.assertIn("Monday", str(ctx.exception))
            with self.assertRaises(RehearsalError):
                run_rehearsal(root=sandbox, first_decision_date=FIRST_MONDAY, weeks=0)
            with self.assertRaises(RehearsalError):
                run_rehearsal(root=sandbox, first_decision_date=FIRST_MONDAY, weeks=2, starved_weeks=(9,))
            with self.assertRaises(RehearsalError):
                run_rehearsal(root=sandbox, first_decision_date=FIRST_MONDAY, weeks=2,
                              starved_weeks=(2,), skipped_weeks=(2,))
            self.assertFalse(sandbox.exists(), "a refused rehearsal created its sandbox anyway")


class ZeroNetworkTest(unittest.TestCase):
    def test_a_rehearsal_opens_no_socket(self) -> None:
        """The vendor seams are injected, so a real request is a bug, not a cost."""

        def poisoned(*args, **kwargs):
            raise AssertionError("the rehearsal reached the network")

        with tempfile.TemporaryDirectory(prefix="rehearsal_net_") as temp:
            with mock.patch.object(socket, "socket", poisoned), \
                    mock.patch.object(urllib.request, "urlopen", poisoned):
                summary = run_rehearsal(
                    root=Path(temp) / "run", first_decision_date=FIRST_MONDAY, weeks=2
                )
        self.assertEqual(2, len(summary["weeks"]))
        self.assertGreater(summary["provider_calls"], 0, "the injected vendor was never asked")


class RehearsalChainTest(unittest.TestCase):
    """Six weeks, one of them starved: the states an operator needs to recognise."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory(prefix="rehearsal_chain_")
        cls.summary = run_rehearsal(
            root=Path(cls._temp.name) / "run",
            first_decision_date=FIRST_MONDAY,
            weeks=6,
            starved_weeks=(6,),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def _section_12(self, week: dict) -> str:
        report = Path(week["report_path"]).read_text(encoding="utf-8")
        return report.split("## 12.")[1].split("## 13.")[0]

    def test_every_week_reaches_the_registered_reminder_block(self) -> None:
        for week in self.summary["weeks"]:
            with self.subTest(week=week["calendar_week_index"]):
                self.assertTrue(week["report_lines_delivered"])
                self.assertIn("us_short_market_diagnostic_v1_1", self._section_12(week))

    def test_every_report_says_it_is_a_rehearsal(self) -> None:
        for week in self.summary["weeks"]:
            with self.subTest(week=week["calendar_week_index"]):
                self.assertIn(REHEARSAL_BANNER, Path(week["report_path"]).read_text(encoding="utf-8"))
        self.assertTrue(self.summary["diagnostic_epoch"].startswith("rehearsal-"))

    def test_the_v1_1_counter_climbs_and_then_activates_on_its_own(self) -> None:
        """Design section 5.2, read off the artifact instead of off the code."""

        self.assertIn("1/4", self._section_12(self.summary["weeks"][0]))
        self.assertIn("3/4", self._section_12(self.summary["weeks"][2]))
        self.assertEqual("pending", self.summary["weeks"][2]["v1_1_status"])
        self.assertEqual("active", self.summary["weeks"][3]["v1_1_status"])
        self.assertIn("attribution_epoch=", self._section_12(self.summary["weeks"][4]))

    def test_a_starved_week_is_visible_and_still_occupies_its_slot(self) -> None:
        starved = self.summary["weeks"][5]
        self.assertTrue(starved["starved"])
        # Starved in its OWN week, which is not yet over: the honest answer is to
        # wait, because inputs that arrive on Wednesday are still this week's.
        self.assertEqual("waiting_for_inputs", starved["settle_status"])
        self.assertEqual([], starved["no_count_weeks"], "a week was written off while it was still live")
        # The window denominator is the calendar, not the weeks that happened to
        # have inputs: the reminder still reports the clock rather than going quiet.
        self.assertIn("日历周=5", self._section_12(starved))
        self.assertEqual("active", starved["v1_1_status"], "a starved week must not deactivate v1.1")

    def test_the_rehearsal_wrote_nothing_into_the_repository(self) -> None:
        """Snapshot taken inside this test, around a run of its own.

        Taken in `setUpClass` it would span every other test in the module, and
        under the module-per-process parallel pack it would also span whatever
        another process is doing — a red that belongs to somebody else.
        """

        before = {relative: _files_under(relative) for relative in PROTECTED}
        with tempfile.TemporaryDirectory(prefix="rehearsal_containment_") as temp:
            run_rehearsal(root=Path(temp) / "run", first_decision_date=FIRST_MONDAY, weeks=2)
        for relative in PROTECTED:
            with self.subTest(protected=relative):
                self.assertEqual(before[relative], _files_under(relative))


def _diagnostic_record(summary: dict, decision_date: str) -> dict:
    path = Path(summary["root"]) / "diag" / "weeks" / decision_date / "weekly_record.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _register(summary: dict) -> dict:
    path = Path(summary["root"]) / "diag" / "lifecycle_register.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _section_12_of(week: dict) -> str:
    report = Path(week["report_path"]).read_text(encoding="utf-8")
    return report.split("## 12.")[1].split("## 13.")[0]


class StarvedMiddleWeekTest(unittest.TestCase):
    """Inputs missing while the account carries on: the week is settled LATE, not lost.

    Design section 3 keeps `no_count` for weeks that *cannot* be evaluated. This
    one can — the account settled it, and its prices can still be fetched — so
    writing it off would destroy real evidence behind an immutable record. What
    the repair has to show instead is that the clock catches the calendar up in a
    single run rather than trailing it for ever.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory(prefix="rehearsal_middle_")
        cls.summary = run_rehearsal(
            root=Path(cls._temp.name) / "run",
            first_decision_date=FIRST_MONDAY,
            weeks=4,
            starved_weeks=(2,),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def test_the_harness_survives_and_records_every_week(self) -> None:
        self.assertEqual(4, len(self.summary["weeks"]))
        for week in self.summary["weeks"]:
            with self.subTest(week=week["calendar_week_index"]):
                self.assertTrue(week["report_lines_delivered"], "a week stopped reporting")
                self.assertIsNone(week["problem"], "a week failed instead of recovering")

    def test_the_gap_settles_late_and_the_clock_catches_up_in_one_run(self) -> None:
        statuses = [week["settle_status"] for week in self.summary["weeks"]]
        self.assertEqual(["published", "waiting_for_inputs", "published", "published"], statuses)
        # Week three's run settles BOTH weeks. One per run would leave the clock
        # permanently a week behind the calendar, which is the 26-week boundary
        # being pushed out by exactly what section 12.8 duty 3 forbids.
        self.assertEqual([[1], [], [2, 3], [4]],
                         [week["settled_weeks"] for week in self.summary["weeks"]])
        self.assertEqual([[], [], [], []],
                         [week["no_count_weeks"] for week in self.summary["weeks"]],
                         "a week that could be evaluated was written off instead")

    def test_no_week_is_lost_and_none_is_written_off(self) -> None:
        for decision_date in ("20260803", "20260810", "20260817", "20260824"):
            with self.subTest(week=decision_date):
                strategy = _diagnostic_record(self.summary, decision_date)["strategy"]
                self.assertFalse(strategy["no_count"])
                self.assertTrue(strategy["strategy_evaluable"])
        register = _register(self.summary)
        self.assertEqual(4, register["calendar_week_count"])
        self.assertEqual(4, register["evaluable_week_count"])
        self.assertEqual("26w-1-26", register["current_window_id"], "the window was extended")

    def test_the_recovered_week_compares_one_week_against_one_week(self) -> None:
        """The number the whole NAV finding was about, read off the artifact.

        Writing the outage week off with the prior NAV erased its real move and
        handed week three a TWO-week strategy return to compare against a one-week
        benchmark. Settling it instead keeps the NAV chain continuous, so every
        week's return spans its own week.
        """

        navs = [
            _diagnostic_record(self.summary, date)["strategy"]
            for date in ("20260803", "20260810", "20260817", "20260824")
        ]
        self.assertEqual(["100004.000000", "99984.000000", "100009.000000", "99989.000000"],
                         [row["nav"] for row in navs], "the account's real path was not recorded")
        for previous, current in zip(navs, navs[1:]):
            with self.subTest(nav=current["nav"]):
                self.assertEqual(previous["nav"], current["prior_nav"], "the NAV chain has a hole")
                self.assertAlmostEqual(
                    float(current["nav"]) / float(previous["nav"]) - 1.0,
                    current["weekly_return"], places=12,
                )

    def test_the_late_week_still_shows_its_own_market_window(self) -> None:
        packet = json.loads(
            (Path(self.summary["root"]) / "inputs" / "benchmark" / "20260810"
             / "benchmark_price_packet.json").read_text(encoding="utf-8")
        )["weeks"][0]
        # The paper week this diagnostic week wraps, found by walking back through
        # the account rather than reading a head that has long since moved on.
        self.assertEqual("20260803", packet["settlement_decision_date"])
        self.assertEqual("20260807", packet["valuation_date"])
        for symbol in ("VTI", "IWB", "SPY", "QQQ"):
            with self.subTest(symbol=symbol):
                # Its OWN week's window, back-captured, not a neighbour's copy.
                self.assertEqual("20260731", packet["benchmarks"][symbol]["prior_price_date"])


class StarvedFirstAndConsecutiveWeeksTest(unittest.TestCase):
    """The two edges of the same outage: it starts at week one, and it lasts."""

    def test_the_very_first_week_can_be_the_starved_one(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rehearsal_first_") as temp:
            summary = run_rehearsal(
                root=Path(temp) / "run", first_decision_date=FIRST_MONDAY,
                weeks=2, starved_weeks=(1,),
            )
            self.assertEqual(["waiting_for_inputs", "published"],
                             [w["settle_status"] for w in summary["weeks"]])
            self.assertEqual([1, 2], summary["weeks"][1]["settled_weeks"])
            self.assertEqual([], summary["weeks"][1]["no_count_weeks"])
            self.assertEqual(2, _register(summary)["evaluable_week_count"])

    def test_a_two_week_outage_is_caught_up_in_one_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rehearsal_run_") as temp:
            summary = run_rehearsal(
                root=Path(temp) / "run", first_decision_date=FIRST_MONDAY,
                weeks=4, starved_weeks=(2, 3),
            )
            self.assertEqual([2, 3, 4], summary["weeks"][3]["settled_weeks"])
            self.assertEqual([], summary["weeks"][3]["no_count_weeks"])
            register = _register(summary)
            self.assertEqual(4, register["calendar_week_count"])
            self.assertEqual(4, register["evaluable_week_count"])


class SkippedWeekTest(unittest.TestCase):
    """Nobody ran the weekly act at all — the outage that actually produces no_count.

    The common one in practice (holiday, machine off), and the one the harness
    could not produce until the account loop learned to skip too. Here the account
    has no week for it and never will, so nothing can ever make it evaluable:
    design section 3 says it is recorded as `no_count`, keeps its calendar slot,
    and the 26-week boundary does not move.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory(prefix="rehearsal_skip_")
        cls.summary = run_rehearsal(
            root=Path(cls._temp.name) / "run",
            first_decision_date=FIRST_MONDAY,
            weeks=4,
            skipped_weeks=(2,),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def test_the_clock_is_not_stuck_and_the_week_is_written_off(self) -> None:
        self.assertEqual(["published", "not_run", "published", "published"],
                         [w["settle_status"] for w in self.summary["weeks"]])
        self.assertEqual([2], self.summary["weeks"][2]["no_count_weeks"])
        self.assertEqual([3], self.summary["weeks"][2]["settled_weeks"])

    def test_the_unlived_week_says_why_and_cannot_pass_as_evaluable(self) -> None:
        strategy = _diagnostic_record(self.summary, "20260810")["strategy"]
        self.assertTrue(strategy["no_count"])
        self.assertFalse(strategy["strategy_evaluable"])
        self.assertFalse(strategy["paper_evaluable"])
        self.assertIsNone(strategy["weekly_return"])
        # Derived from what was actually missing, not a constant: the account
        # settled no week this one could wrap.
        self.assertEqual("no_settled_account_week_for_this_calendar_week",
                         strategy["no_count_reason"])
        # NAV is the prior one, and here that is the truth: the account really did
        # not move, because it never settled anything that week.
        self.assertEqual(_diagnostic_record(self.summary, "20260803")["strategy"]["nav"],
                         strategy["nav"])

    def test_the_week_after_it_is_recorded_but_not_compared(self) -> None:
        """Its strategy move spans two calendar weeks; its benchmarks span one.

        The account settled once across the skipped week, so week three's NAV move
        covers weeks two AND three while its benchmark window covers only week
        three. Both numbers are real and both are kept — what must not happen is
        pairing them, because that puts a two-week numerator over a few-days
        denominator in whichever direction the skipped week's market moved.
        """

        recovery = _diagnostic_record(self.summary, "20260817")
        self.assertFalse(recovery["windows_aligned"])
        self.assertEqual("strategy_return_spans_a_no_count_week",
                         recovery["windows_misaligned_reason"])
        # Both sides are individually fine — that is the whole point of the field.
        self.assertTrue(recovery["strategy"]["strategy_evaluable"])
        self.assertIsNotNone(recovery["strategy"]["weekly_return"])
        for symbol in ("VTI", "IWB", "SPY", "QQQ"):
            with self.subTest(symbol=symbol):
                self.assertTrue(recovery["benchmarks"][symbol]["benchmark_evaluable"])
                self.assertFalse(recovery["benchmarks"][symbol]["joint_evaluable"])
                self.assertIsNone(recovery["benchmarks"][symbol]["raw_excess"])
        # ...and the ordinary week after THAT is compared again.
        following = _diagnostic_record(self.summary, "20260824")
        self.assertTrue(following["windows_aligned"])
        self.assertTrue(following["benchmarks"]["VTI"]["joint_evaluable"])

    def test_the_unlived_week_keeps_its_slot_and_still_shows_the_market(self) -> None:
        register = _register(self.summary)
        self.assertEqual(4, register["calendar_week_count"])
        self.assertEqual(3, register["evaluable_week_count"])
        self.assertEqual("26w-1-26", register["current_window_id"], "the window was extended")
        record = _diagnostic_record(self.summary, "20260810")
        # Its valuation date is its own decision day: the account never valued it,
        # and the previous week's valuation is already taken.
        self.assertEqual("20260810", record["valuation_date"])
        for symbol in ("VTI", "IWB", "SPY", "QQQ"):
            with self.subTest(symbol=symbol):
                self.assertTrue(record["benchmarks"][symbol]["benchmark_evaluable"])
        self.assertIn("日历周=4", _section_12_of(self.summary["weeks"][-1]))
        self.assertIn("累计可评估周=3", _section_12_of(self.summary["weeks"][-1]))


class SkippedFirstAndConsecutiveWeeksTest(unittest.TestCase):
    """Week one skipped used to fail hard every week; two in a row exercise the loop."""

    def test_skipping_week_one_still_builds_a_register(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rehearsal_skip1_") as temp:
            summary = run_rehearsal(
                root=Path(temp) / "run", first_decision_date=FIRST_MONDAY,
                weeks=3, skipped_weeks=(1,),
            )
            self.assertEqual([1], summary["weeks"][1]["no_count_weeks"])
            for week in summary["weeks"][1:]:
                with self.subTest(week=week["calendar_week_index"]):
                    self.assertIsNone(week["problem"], "the run failed instead of writing it off")
            strategy = _diagnostic_record(summary, FIRST_MONDAY)["strategy"]
            self.assertTrue(strategy["no_count"])
            self.assertIsNone(strategy["prior_nav"], "week one has no prior week to continue from")
            # The frozen normalized capital, not a number invented for the gap.
            self.assertEqual(strategy["initial_capital"], strategy["nav"])
            self.assertEqual(3, _register(summary)["calendar_week_count"])

    def test_two_unlived_weeks_are_written_off_in_the_same_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="rehearsal_skip2_") as temp:
            summary = run_rehearsal(
                root=Path(temp) / "run", first_decision_date=FIRST_MONDAY,
                weeks=4, skipped_weeks=(2, 3),
            )
            self.assertEqual([2, 3], summary["weeks"][3]["no_count_weeks"])
            register = _register(summary)
            self.assertEqual(4, register["calendar_week_count"])
            self.assertEqual(2, register["evaluable_week_count"])
            self.assertEqual("26w-1-26", register["current_window_id"])


class TotalReturnSidecarTest(unittest.TestCase):
    """The flag exists for one reason: it is the only way to see v1.1's full identity."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory(prefix="rehearsal_sidecar_")
        cls.on = run_rehearsal(
            root=Path(cls._temp.name) / "on",
            first_decision_date=FIRST_MONDAY,
            weeks=5,
            with_total_return_sidecar=True,
        )
        cls.off = run_rehearsal(
            root=Path(cls._temp.name) / "off",
            first_decision_date=FIRST_MONDAY,
            weeks=5,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    @staticmethod
    def _v1_1_line(summary: dict) -> str:
        report = Path(summary["weeks"][-1]["report_path"]).read_text(encoding="utf-8")
        section = report.split("## 12.")[1].split("## 13.")[0]
        return next(line for line in section.splitlines() if line.startswith("v1.1 归因："))

    def test_with_the_sidecar_v1_1_prints_its_identity_instead_of_unavailable(self) -> None:
        line = self._v1_1_line(self.on)
        self.assertIn("全部 5 周可评估", line)
        self.assertIn("raw_excess=", line)
        # From `raw_excess=` onwards, or the `1.1` in the label counts as a number.
        numbers = [float(part) for part in re.findall(r"-?\d+\.\d+", line.split("raw_excess=")[1])]
        self.assertEqual(3, len(numbers), f"expected raw_excess and its two parts: {line}")
        raw, exposure, active = numbers
        self.assertAlmostEqual(raw, exposure + active, places=3,
                               msg="the published identity does not add up")

    def test_without_it_the_same_weeks_report_the_one_click_truth(self) -> None:
        """Default-off is not a lesser mode; it is what the one-click path really gives."""

        line = self._v1_1_line(self.off)
        self.assertIn("0/5 周可评估", line)
        self.assertIn("缺 VTI 总收益", line)
        self.assertNotIn("raw_excess=", line)

    def test_the_sidecar_is_built_from_the_packet_it_reconciles_against(self) -> None:
        sidecars = sorted(Path(self.on["root"]).rglob("total_return_sidecar.json"))
        self.assertEqual(5, len(sidecars), "one sidecar per settled week")
        for path in sidecars:
            with self.subTest(week=path.parent.name):
                packet = json.loads((path.parent / "benchmark_price_packet.json").read_text(encoding="utf-8"))
                sidecar = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(packet["window_id"], sidecar["window_id"])
                self.assertEqual(packet["diagnostic_epoch"], sidecar["diagnostic_epoch"])
                self.assertEqual(
                    packet["weeks"][0]["valuation_date"], sidecar["weeks"][0]["valuation_date"]
                )

    def test_a_starved_week_still_falls_through_to_the_honest_waiting_status(self) -> None:
        """With the flag on there is no packet to reconcile, and no packet is not a crash."""

        with tempfile.TemporaryDirectory(prefix="rehearsal_sidecar_gap_") as temp:
            summary = run_rehearsal(
                root=Path(temp) / "run",
                first_decision_date=FIRST_MONDAY,
                weeks=3,
                starved_weeks=(3,),
                with_total_return_sidecar=True,
            )
        self.assertEqual("waiting_for_inputs", summary["weeks"][2]["settle_status"])
        self.assertTrue(summary["weeks"][2]["report_lines_delivered"])


class FullWindowTest(unittest.TestCase):
    def test_twenty_six_weeks_reach_the_scorecard(self) -> None:
        """The claim the whole harness exists to test, and the only slow test here.

        Every knife was green on its own while the assembly was dead three times
        in one week. Nothing short of running the window proves the window runs.
        """

        with tempfile.TemporaryDirectory(prefix="rehearsal_window_") as temp:
            summary = run_rehearsal(
                root=Path(temp) / "run", first_decision_date=FIRST_MONDAY, weeks=26
            )
            final = summary["weeks"][-1]
            self.assertEqual(26, final["calendar_week_index"])
            self.assertEqual("published", final["publication"]["status"])
            self.assertEqual("26w-1-26", final["publication"]["window_id"])
            public = Path(summary["root"]) / "public"
            self.assertEqual(
                {"26w-1-26.json", "26w-1-26.md"},
                {path.name for path in public.rglob("*") if path.is_file()},
            )
            for week in summary["weeks"][:25]:
                self.assertEqual("not_ready", week["publication"]["status"],
                                 "a non-boundary week published a scorecard")


if __name__ == "__main__":
    unittest.main()
