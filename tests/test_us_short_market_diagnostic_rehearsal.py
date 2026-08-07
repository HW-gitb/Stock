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
                run_rehearsal(root=sandbox, first_decision_date=FIRST_MONDAY, weeks=2, no_count_weeks=(9,))
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
            no_count_weeks=(6,),
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
        self.assertTrue(starved["no_count"])
        self.assertEqual("waiting_for_inputs", starved["settle_status"])
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


class StarvedMiddleWeekTest(unittest.TestCase):
    """Starving a week that has a week after it — the case the other two never reach.

    Both existing starve cases starve the LAST week, and the failure lands on the
    week AFTER the starved one, so there was nothing after it to fail. The blind
    spot and the behaviour shared an assumption.

    What this pins is deliberately the CURRENT picture, not the intended one:
    `R-USSHORT-26W-DIAG-A-MISSED-WEEK-JAMS-THE-CLOCK-FOREVER-AND-NOTHING-WRITES-NO-COUNT`
    is a design decision that has not been taken. Until it is, the honest thing
    for the rehearsal to show is what the one-click path really does — every later
    week failed, the clock frozen on the last week that settled — rather than a
    traceback that shows nothing at all.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory(prefix="rehearsal_middle_")
        cls.summary = run_rehearsal(
            root=Path(cls._temp.name) / "run",
            first_decision_date=FIRST_MONDAY,
            weeks=4,
            no_count_weeks=(2,),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def test_the_harness_survives_and_records_every_week(self) -> None:
        self.assertEqual(4, len(self.summary["weeks"]))
        for week in self.summary["weeks"]:
            with self.subTest(week=week["calendar_week_index"]):
                self.assertTrue(week["report_lines_delivered"], "a failed week stopped reporting")

    def test_the_weeks_after_the_gap_report_the_jam_instead_of_hiding_it(self) -> None:
        statuses = [week["settle_status"] for week in self.summary["weeks"]]
        self.assertEqual(["published", "waiting_for_inputs", "failed", "failed"], statuses)
        for week in self.summary["weeks"][2:]:
            with self.subTest(week=week["calendar_week_index"]):
                self.assertIn("does not line up", week["problem"] or "")

    def test_the_clock_is_frozen_on_the_last_week_that_settled(self) -> None:
        """The registered reminder is where an operator would actually notice."""

        for week in self.summary["weeks"]:
            report = Path(week["report_path"]).read_text(encoding="utf-8")
            section = report.split("## 12.")[1].split("## 13.")[0]
            with self.subTest(week=week["calendar_week_index"]):
                self.assertIn("日历周=1", section)


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
                no_count_weeks=(3,),
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
