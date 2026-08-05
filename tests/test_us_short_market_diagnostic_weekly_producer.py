"""Knife 7b — the producer and the weekly step, tested as the missing halves they are.

Before this slice the track could validate, store, gate and aggregate a weekly
record, and nothing computed one; and the v1.1 state the design says the weekly
task reads automatically had no reader. Both gaps are the same shape: a consumer
with no producer. These tests exist to keep that shape from coming back.
"""
from __future__ import annotations

import copy
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest

import engine.us_short_market_diagnostic_weekly_producer as producer
from engine.us_short_market_diagnostic_lifecycle import (
    load_lifecycle_register,
    persist_settled_weekly_record,
)
from engine.us_short_market_diagnostic_start_receipt import issue_start_receipt
from engine.us_short_market_diagnostic_weekly_producer import (
    MarketDiagnosticWeeklyProducerError,
    build_next_weekly_record,
    diagnostic_policy_sha256,
    next_week_inputs,
    settle_next_week,
    strategy_ruleset_fingerprint,
)
from engine.us_short_market_diagnostic_weekly_task import weekly_diagnostic_step
from engine.us_short_model_paper_portfolio import artifact_sha256, canonical_json_bytes
from tests.test_us_short_market_diagnostic import _weekly_rows
from tests.test_us_short_market_diagnostic_local_adapter import _packet, _start_local_paper_store


ROOT = Path(__file__).resolve().parents[1]


def _open_clock(root: Path, *, epoch: str, first_decision_date: str) -> None:
    """Open the clock a few days before the week it freezes, as a real decision would."""

    frozen = date(
        int(first_decision_date[0:4]), int(first_decision_date[4:6]), int(first_decision_date[6:8])
    )
    issued = (frozen - timedelta(days=3)).strftime("%Y-%m-%dT00:00:00+00:00")
    issue_start_receipt(
        diagnostic_epoch=epoch,
        completion_notification={
            "issued_at": issued,
            "issuer": "codex",
            "notification_text": "US-short 26-week diagnostic design is complete; open the clock.",
        },
        first_decision_date=first_decision_date,
        root=root,
    )


class RulesetFingerprintTest(unittest.TestCase):
    """Section 6 wants a value stable week to week that moves when the rules move."""

    def test_the_policy_digest_is_the_frozen_preset_canonicalized(self) -> None:
        preset = json.loads(producer.POLICY_PRESET_PATH.read_text(encoding="utf-8"))
        self.assertEqual(artifact_sha256(preset), diagnostic_policy_sha256())

    def test_the_fingerprint_is_stable_across_calls(self) -> None:
        self.assertEqual(strategy_ruleset_fingerprint(), strategy_ruleset_fingerprint())

    def test_changing_any_governed_rule_moves_the_fingerprint(self) -> None:
        """The whole point: a rule upgrade must be visible in the weekly record."""

        before = strategy_ruleset_fingerprint()
        declaration = json.loads(producer.RULESET_PRESET_PATH.read_text(encoding="utf-8"))
        governed = declaration["governed_presets"]
        self.assertGreater(len(governed), 1, "a one-preset ruleset would not be worth fingerprinting")

        with tempfile.TemporaryDirectory() as td:
            fake_root = Path(td) / "repo"
            edited = governed[0]
            for relative in governed:
                source = ROOT / relative
                target = fake_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                value = json.loads(source.read_text(encoding="utf-8"))
                if relative == edited:
                    value["__rule_upgrade_probe__"] = True
                target.write_bytes(canonical_json_bytes(value))
            (fake_root / "presets").mkdir(parents=True, exist_ok=True)
            (fake_root / "presets" / producer.RULESET_PRESET_PATH.name).write_bytes(
                canonical_json_bytes(declaration)
            )
            original = producer.ROOT
            try:
                producer.ROOT = fake_root
                producer.RULESET_PRESET_PATH = fake_root / "presets" / producer.RULESET_PRESET_PATH.name
                after = strategy_ruleset_fingerprint()
            finally:
                producer.ROOT = original
                producer.RULESET_PRESET_PATH = original / "presets" / producer.RULESET_PRESET_PATH.name
        self.assertNotEqual(before, after)

    def test_a_declared_preset_that_is_gone_fails_closed(self) -> None:
        """Silently fingerprinting eight of nine rules would be worse than refusing."""

        declaration = json.loads(producer.RULESET_PRESET_PATH.read_text(encoding="utf-8"))
        declaration["governed_presets"].append("presets/never_existed.json")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ruleset.json"
            path.write_bytes(canonical_json_bytes(declaration))
            original = producer.RULESET_PRESET_PATH
            try:
                producer.RULESET_PRESET_PATH = path
                with self.assertRaises(MarketDiagnosticWeeklyProducerError) as ctx:
                    strategy_ruleset_fingerprint()
            finally:
                producer.RULESET_PRESET_PATH = original
        self.assertIn("never_existed.json", str(ctx.exception))

    def test_every_declared_preset_exists_right_now(self) -> None:
        declaration = json.loads(producer.RULESET_PRESET_PATH.read_text(encoding="utf-8"))
        missing = [p for p in declaration["governed_presets"] if not (ROOT / p).is_file()]
        self.assertEqual([], missing)


class ProducerTest(unittest.TestCase):
    """The gap: a clock could be opened and then had no way to advance."""

    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.base = Path(holder.name)
        self.store = self.base / "market_diagnostic_private"
        self.paper = self.base / "model_paper_private"
        self.packet = _packet()
        _start_local_paper_store(self.paper)

    def _open(self) -> None:
        _open_clock(self.store, epoch=self.packet["diagnostic_epoch"], first_decision_date="20260727")

    def test_a_week_cannot_be_produced_before_the_clock_is_opened(self) -> None:
        with self.assertRaises(MarketDiagnosticWeeklyProducerError) as ctx:
            next_week_inputs(self.store)
        self.assertIn("has not been opened", str(ctx.exception))

    def test_week_one_is_computed_from_local_inputs_and_stored(self) -> None:
        self._open()
        result = settle_next_week(
            model_paper_root=self.paper,
            benchmark_packet=self.packet,
            root=self.store,
            as_of_date="20260801",
        )
        self.assertEqual("published", result["status"])
        self.assertEqual(1, result["calendar_week_index"])
        register = load_lifecycle_register(self.store, as_of_date="20260801")
        self.assertEqual(1, register["calendar_week_count"])
        self.assertEqual(self.packet["diagnostic_epoch"], register["diagnostic_epoch"])

    def test_the_stored_week_carries_the_real_policy_and_ruleset_identity(self) -> None:
        self._open()
        record = build_next_weekly_record(
            model_paper_root=self.paper,
            benchmark_packet=self.packet,
            root=self.store,
            as_of_date="20260801",
        )
        self.assertEqual(diagnostic_policy_sha256(), record["diagnostic_policy_sha256"])
        self.assertEqual(strategy_ruleset_fingerprint(), record["strategy_ruleset_fingerprint"])

    def test_the_week_index_and_prior_nav_come_from_the_store_not_the_caller(self) -> None:
        """No parameter to choose them, so a caller cannot restart the NAV series."""

        import inspect

        for func in (build_next_weekly_record, settle_next_week):
            params = set(inspect.signature(func).parameters)
            self.assertNotIn("calendar_week_index", params, func.__name__)
            self.assertNotIn("prior_nav", params, func.__name__)
            self.assertNotIn("v1_1_reminder", params, func.__name__)

        self._open()
        inputs = next_week_inputs(self.store, as_of_date="20260801")
        self.assertEqual(1, inputs["calendar_week_index"])
        self.assertIsNone(inputs["prior_nav"], "week 1 must start from the normalized capital")

    def test_a_packet_from_another_epoch_is_refused_before_anything_is_written(self) -> None:
        self._open()
        drifted = copy.deepcopy(self.packet)
        drifted["diagnostic_epoch"] = "us_short_market_diagnostic_26w_other"
        with self.assertRaises(MarketDiagnosticWeeklyProducerError) as ctx:
            settle_next_week(
                model_paper_root=self.paper,
                benchmark_packet=drifted,
                root=self.store,
                as_of_date="20260801",
            )
        self.assertIn("different diagnostic epoch", str(ctx.exception))
        self.assertFalse((self.store / "lifecycle_register.json").exists())

    def test_producing_the_same_week_twice_is_idempotent(self) -> None:
        self._open()
        first = settle_next_week(
            model_paper_root=self.paper, benchmark_packet=self.packet,
            root=self.store, as_of_date="20260801",
        )
        second = settle_next_week(
            model_paper_root=self.paper, benchmark_packet=self.packet,
            root=self.store, as_of_date="20260801",
        )
        self.assertEqual("published", first["status"])
        self.assertEqual("idempotent", second["status"])
        self.assertEqual(1, load_lifecycle_register(self.store, as_of_date="20260801")["calendar_week_count"])

    def test_the_producer_never_writes_the_model_paper_account(self) -> None:
        self._open()
        before = {p: p.read_bytes() for p in self.paper.rglob("*.json")}
        settle_next_week(
            model_paper_root=self.paper, benchmark_packet=self.packet,
            root=self.store, as_of_date="20260801",
        )
        self.assertEqual(before, {p: p.read_bytes() for p in self.paper.rglob("*.json")})


class WeeklyStepTest(unittest.TestCase):
    """Section 12.8 duty 4: the weekly task reads v1.1 by itself, or it is not automatic."""

    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.store = Path(holder.name) / "market_diagnostic_private"
        self.rows = _weekly_rows()

    def _running(self, weeks: int) -> None:
        _open_clock(
            self.store,
            epoch=self.rows[0]["diagnostic_epoch"],
            first_decision_date=self.rows[0]["decision_date"],
        )
        for row in self.rows[:weeks]:
            persist_settled_weekly_record(row, root=self.store)

    def test_a_dormant_clock_contributes_nothing_at_all(self) -> None:
        """The weekly report must be byte-identical while the track is asleep."""

        step = weekly_diagnostic_step(root=self.store)
        self.assertEqual("not_started", step["status"])
        self.assertEqual([], step["report_lines"])
        self.assertIsNone(step["attribution"])
        self.assertFalse(self.store.exists(), "a dormant step created state")

    def test_a_broken_store_is_reported_as_broken_not_as_silence(self) -> None:
        self._running(2)
        (self.store / "lifecycle_register.json").write_text("{ truncated", encoding="utf-8")
        step = weekly_diagnostic_step(root=self.store)
        self.assertEqual("broken", step["status"])
        self.assertTrue(step["problem"])
        self.assertTrue(step["report_lines"], "a broken store must say something")
        self.assertIn("故障", step["report_lines"][0])

    def test_a_missing_receipt_is_broken_too_not_never_started(self) -> None:
        self._running(2)
        (self.store / "diagnostic_start_receipt.json").unlink()
        step = weekly_diagnostic_step(root=self.store)
        self.assertEqual("broken", step["status"])

    def test_a_pending_clock_only_reminds(self) -> None:
        self._running(2)
        step = weekly_diagnostic_step(root=self.store)
        self.assertEqual("running", step["status"])
        self.assertEqual("pending", step["v1_1_status"])
        self.assertIsNone(step["attribution"], "v1.1 must not run before it activates")
        self.assertEqual(1, len(step["report_lines"]))
        self.assertIn("v1.1", step["report_lines"][0])

    def test_activation_calls_knife_6_without_anyone_remembering_to(self) -> None:
        self._running(5)
        step = weekly_diagnostic_step(root=self.store)
        self.assertEqual("active", step["v1_1_status"])
        self.assertIsNotNone(step["attribution"])
        self.assertEqual(2, len(step["report_lines"]))

    def test_a_knife6_fault_is_not_dressed_up_as_a_missing_input(self) -> None:
        """The two must read differently, or a broken calculator looks like patience.

        Knife 6 has a known structural refusal (its 256-digest ceiling) that has
        nothing to do with data availability. Reporting it in the same
        "waiting for inputs" wording is exactly the silence-and-breakage
        confusion this track keeps finding in itself.
        """

        from unittest import mock

        from engine.us_short_market_diagnostic_attribution import AttributionError

        self._running(5)
        with mock.patch(
            "engine.us_short_market_diagnostic_weekly_task.build_attribution_input",
            side_effect=AttributionError("attribution source_refs contains too many source digests"),
        ):
            step = weekly_diagnostic_step(root=self.store)
        self.assertEqual("attribution_faulted", step["v1_1_status"])
        self.assertIn("too many source digests", step["attribution_error"])
        line = step["report_lines"][1]
        self.assertIn("计算本身失败", line)
        self.assertNotIn("不补零", line, "a fault must not borrow the missing-input wording")
        self.assertIsNone(step["attribution"])

    def test_missing_target_and_cash_inputs_degrade_rather_than_block(self) -> None:
        """No zero fill, no substituted rate, and no request for manual work."""

        self._running(5)
        step = weekly_diagnostic_step(root=self.store)
        report = step["attribution"]
        assert report is not None
        self.assertEqual("unavailable", report["status"])
        summary = report["summary"]
        self.assertEqual(0, summary["evaluable_weeks"])
        self.assertIsNone(summary["raw_excess"], "an unavailable window must not report a number")
        self.assertIn("不补零", step["report_lines"][1])
        for week in report["weeks"]:
            self.assertTrue(week["unavailable_reasons"])


class WeeklyHostStageTest(unittest.TestCase):
    """7b-iv: the stage that finally makes the weekly task read this track."""

    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.store = Path(holder.name) / "market_diagnostic_private"
        self.rows = _weekly_rows()

    @staticmethod
    def _ctx(root):
        from runners.us_short_weekly_capstone import CapstoneContext

        context = CapstoneContext.__new__(CapstoneContext)
        object.__setattr__(context, "market_diagnostic_root", root)
        object.__setattr__(context, "decision_date", "20260801")
        return context

    def test_the_stage_is_registered_in_the_weekly_plan(self) -> None:
        """The whole point of 7b-iv: the official weekly task reaches this track."""

        from runners.us_short_weekly_capstone import default_pipeline

        stages = default_pipeline(include_model_paper=True, include_soft_discovery=True)
        self.assertIn("market_diagnostic", [stage.name for stage in stages])
        stage = next(s for s in stages if s.name == "market_diagnostic")
        self.assertFalse(stage.gated, "the diagnostic stage must never perform a provider fetch")
        self.assertEqual([], stage.outputs(self._ctx(None)), "it must claim no artifact")
        self.assertFalse(
            stage.best_effort,
            "best_effort is reserved for comparison-capture stages; totality lives in the adapter",
        )
        self.assertEqual("strict", stage.failure_policy)

    def test_a_dormant_clock_makes_the_stage_a_no_op(self) -> None:
        from runners.us_short_weekly_capstone import _run_market_diagnostic

        for root in (None, self.store):
            with self.subTest(root=root):
                result = _run_market_diagnostic(self._ctx(root))
                self.assertEqual("not_started", result["clock_status"])
                self.assertEqual([], result["report_lines"])
                self.assertFalse(result["provider_calls_performed"])
        self.assertFalse(self.store.exists(), "a dormant weekly run created diagnostic state")

    def test_a_replayed_week_continues_from_its_own_predecessor_not_the_first_row(self) -> None:
        """The NAV series must be continued from week target-1, whichever week that is."""

        import engine.us_short_market_diagnostic_weekly_producer as prod

        _open_clock(
            self.store,
            epoch=self.rows[0]["diagnostic_epoch"],
            first_decision_date=self.rows[0]["decision_date"],
        )
        for row in self.rows[:3]:
            persist_settled_weekly_record(row, root=self.store)
        inputs = prod.next_week_inputs(self.store)
        self.assertEqual(4, inputs["calendar_week_index"])

        target, prior = prod._target_week(
            {"weeks": [{"calendar_week_index": 3}]}, inputs, self.store, as_of_date=None
        )
        self.assertEqual(3, target)
        self.assertEqual(self.rows[1]["strategy"]["nav"], prior)
        self.assertNotEqual(self.rows[0]["strategy"]["nav"], prior)

        target, prior = prod._target_week(
            {"weeks": [{"calendar_week_index": 1}]}, inputs, self.store, as_of_date=None
        )
        self.assertEqual((1, None), (target, prior), "week 1 starts from the normalized capital")

    def test_a_packet_ahead_of_the_clock_cannot_skip_a_gap(self) -> None:
        import engine.us_short_market_diagnostic_weekly_producer as prod

        _open_clock(
            self.store,
            epoch=self.rows[0]["diagnostic_epoch"],
            first_decision_date=self.rows[0]["decision_date"],
        )
        persist_settled_weekly_record(self.rows[0], root=self.store)
        inputs = prod.next_week_inputs(self.store)
        with self.assertRaises(MarketDiagnosticWeeklyProducerError) as ctx:
            prod._target_week(
                {"weeks": [{"calendar_week_index": 9}]}, inputs, self.store, as_of_date=None
            )
        self.assertIn("gap cannot be skipped", str(ctx.exception))

    def test_a_broken_clock_is_surfaced_but_never_raises_into_the_weekly_run(self) -> None:
        from runners.us_short_weekly_capstone import _run_market_diagnostic

        _open_clock(
            self.store,
            epoch=self.rows[0]["diagnostic_epoch"],
            first_decision_date=self.rows[0]["decision_date"],
        )
        for row in self.rows[:2]:
            persist_settled_weekly_record(row, root=self.store)
        (self.store / "diagnostic_start_receipt.json").unlink()

        result = _run_market_diagnostic(self._ctx(self.store))
        self.assertEqual("broken", result["clock_status"])
        self.assertTrue(result["problem"])
        self.assertTrue(result["report_lines"])

    def test_an_unexpected_failure_is_reported_not_raised_into_the_weekly_run(self) -> None:
        """The stage is strict, so its adapter has to be total or a diagnostic read kills the week."""

        from unittest import mock

        import runners.us_short_weekly_capstone as capstone

        with mock.patch(
            "engine.us_short_market_diagnostic_weekly_task.weekly_diagnostic_step",
            side_effect=RuntimeError("disk went away"),
        ):
            result = capstone._run_market_diagnostic(self._ctx(self.store))
        self.assertEqual("broken", result["clock_status"])
        self.assertIn("disk went away", result["problem"])
        self.assertFalse(result["provider_calls_performed"])


if __name__ == "__main__":
    unittest.main()
