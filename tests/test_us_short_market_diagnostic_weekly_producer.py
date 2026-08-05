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

    def test_every_engine_preset_is_classified_as_governed_or_excluded(self) -> None:
        """The counterpart that makes the list falsifiable.

        v1.0.0 omitted six presets that really do define selection and action —
        including the core-score weight profile, the biggest ranking lever — and
        nothing could tell, because a list with no complement cannot be wrong.
        A newly added rule preset must now fail here rather than be left out.
        """

        import re

        declaration = json.loads(producer.RULESET_PRESET_PATH.read_text(encoding="utf-8"))
        governed = set(declaration["governed_presets"])
        excluded = declaration["excluded_presets"]
        self.assertTrue(all(reason.strip() for reason in excluded.values()), "an exclusion must say why")
        self.assertEqual(set(), governed & set(excluded), "a preset cannot be both")

        loaded = set()
        for module in sorted((ROOT / "engine").glob("us_short_*.py")):
            source = module.read_text(encoding="utf-8")
            for match in re.finditer(r'"presets"\s*/\s*"(us_short_[a-z0-9_]+\.json)"', source):
                loaded.add(f"presets/{match.group(1)}")

        unclassified = sorted(loaded - governed - set(excluded))
        self.assertEqual(
            [],
            unclassified,
            "an engine loads these presets and the ruleset declaration says nothing about them; "
            "add each to governed_presets, or to excluded_presets with a reason",
        )
        # And the biggest ranking lever is governed, named explicitly so a refactor
        # of the scan above cannot quietly drop it.
        self.assertIn("presets/us_short_scoring_profile_governance_20260620.json", governed)

    def test_a_governed_preset_may_not_escape_the_repo(self) -> None:
        """An absolute or ../ path fingerprints something no reviewer will see in a diff."""

        declaration = json.loads(producer.RULESET_PRESET_PATH.read_text(encoding="utf-8"))
        for bad in ("C:/somewhere/else.json", "/etc/passwd", "../outside.json"):
            with self.subTest(bad):
                drifted = copy.deepcopy(declaration)
                drifted["governed_presets"].append(bad)
                with tempfile.TemporaryDirectory() as td:
                    path = Path(td) / "ruleset.json"
                    path.write_bytes(canonical_json_bytes(drifted))
                    original = producer.RULESET_PRESET_PATH
                    try:
                        producer.RULESET_PRESET_PATH = path
                        with self.assertRaises(MarketDiagnosticWeeklyProducerError) as ctx:
                            strategy_ruleset_fingerprint()
                    finally:
                        producer.RULESET_PRESET_PATH = original
                self.assertIn("repo-relative", str(ctx.exception))

    def test_reordering_or_duplicating_the_declaration_does_not_move_the_fingerprint(self) -> None:
        """What the docstring claims, pinned — the payload is a keyed map, not a list."""

        declaration = json.loads(producer.RULESET_PRESET_PATH.read_text(encoding="utf-8"))
        before = strategy_ruleset_fingerprint()
        for label, mutate in (
            ("reversed", lambda g: list(reversed(g))),
            ("duplicated", lambda g: g + [g[0]]),
        ):
            with self.subTest(label):
                drifted = copy.deepcopy(declaration)
                drifted["governed_presets"] = mutate(drifted["governed_presets"])
                with tempfile.TemporaryDirectory() as td:
                    path = Path(td) / "ruleset.json"
                    path.write_bytes(canonical_json_bytes(drifted))
                    original = producer.RULESET_PRESET_PATH
                    try:
                        producer.RULESET_PRESET_PATH = path
                        self.assertEqual(before, strategy_ruleset_fingerprint())
                    finally:
                        producer.RULESET_PRESET_PATH = original

    def test_a_governed_preset_that_will_not_parse_fails_closed(self) -> None:
        """Fingerprinting fifteen of sixteen rules silently is worse than refusing."""

        declaration = json.loads(producer.RULESET_PRESET_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            fake_root = Path(td) / "repo"
            for relative in declaration["governed_presets"]:
                target = fake_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            broken = declaration["governed_presets"][0]
            (fake_root / broken).write_text("{ not json", encoding="utf-8")
            ruleset = fake_root / "presets" / producer.RULESET_PRESET_PATH.name
            ruleset.parent.mkdir(parents=True, exist_ok=True)
            ruleset.write_bytes(canonical_json_bytes(declaration))
            original_root, original_preset = producer.ROOT, producer.RULESET_PRESET_PATH
            try:
                producer.ROOT = fake_root
                producer.RULESET_PRESET_PATH = ruleset
                with self.assertRaises(MarketDiagnosticWeeklyProducerError):
                    strategy_ruleset_fingerprint()
            finally:
                producer.ROOT, producer.RULESET_PRESET_PATH = original_root, original_preset

    def test_the_fingerprint_names_which_ruleset_it_is(self) -> None:
        declaration = json.loads(producer.RULESET_PRESET_PATH.read_text(encoding="utf-8"))
        drifted = copy.deepcopy(declaration)
        drifted.pop("ruleset_id")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ruleset.json"
            path.write_bytes(canonical_json_bytes(drifted))
            original = producer.RULESET_PRESET_PATH
            try:
                producer.RULESET_PRESET_PATH = path
                with self.assertRaises(MarketDiagnosticWeeklyProducerError) as ctx:
                    strategy_ruleset_fingerprint()
            finally:
                producer.RULESET_PRESET_PATH = original
        self.assertIn("ruleset_id", str(ctx.exception))

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

    def test_settle_week_attempts_publication_every_week(self) -> None:
        """A closing week must not depend on anybody remembering a second command."""

        from runners.us_short_market_diagnostic_weekly import settle_week

        self._open()
        packet_path = self.base / "packet.json"
        packet_path.write_bytes(canonical_json_bytes(self.packet))
        output_root = self.base / "public"

        result = settle_week(
            model_paper_root=self.paper,
            benchmark_packet_path=packet_path,
            root=self.store,
            as_of_date="20260801",
            output_root=output_root,
        )
        self.assertEqual("published", result["status"])
        self.assertEqual("not_ready", result["publication"]["status"], "week 1 closes no window")
        self.assertFalse(output_root.exists(), "a non-boundary week left public bytes behind")

    def test_no_publish_is_honoured_and_says_so(self) -> None:
        from runners.us_short_market_diagnostic_weekly import settle_week

        self._open()
        packet_path = self.base / "packet.json"
        packet_path.write_bytes(canonical_json_bytes(self.packet))
        result = settle_week(
            model_paper_root=self.paper,
            benchmark_packet_path=packet_path,
            root=self.store,
            as_of_date="20260801",
            publish=False,
            output_root=self.base / "public",
        )
        self.assertEqual("skipped", result["publication"]["status"])

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


class NoCountWeekTest(unittest.TestCase):
    """Design sections 3 and 5: an unevaluable week is recorded and still occupies its slot.

    Before this, one week the account could not settle stalled the whole weekly
    act: `settle-week` raised, and the next week refused with "must append 3, got
    4". The only way forward was hand-authoring a record with the exact decision
    date — the manual step this slice exists to remove.
    """

    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.store = Path(holder.name) / "market_diagnostic_private"
        self.rows = _weekly_rows()
        _open_clock(
            self.store,
            epoch=self.rows[0]["diagnostic_epoch"],
            first_decision_date=self.rows[0]["decision_date"],
        )

    def _packet_for(self, row) -> dict:
        packet = _packet()
        packet["diagnostic_epoch"] = row["diagnostic_epoch"]
        packet["window_id"] = row["window_id"]
        week = packet["weeks"][0]
        week["calendar_week_index"] = row["calendar_week_index"]
        week["decision_date"] = row["decision_date"]
        week["valuation_date"] = row["valuation_date"]
        # A settlement is the PRIOR week's decision, so it is never after this
        # week's valuation date.
        week["settlement_decision_date"] = self.rows[row["calendar_week_index"] - 2]["decision_date"]             if row["calendar_week_index"] > 1 else row["decision_date"]
        index = row["calendar_week_index"]
        prior_valuation = self.rows[index - 2]["valuation_date"] if index > 1 else None
        for symbol in packet["weeks"][0]["benchmarks"]:
            observation = packet["weeks"][0]["benchmarks"][symbol]
            observation["price_date"] = row["valuation_date"]
            observation["prior_price_date"] = prior_valuation
            if prior_valuation is None:
                observation["prior_close"] = None
        return packet

    def test_a_week_the_account_could_not_settle_is_recorded_and_keeps_its_slot(self) -> None:
        for row in self.rows[:2]:
            persist_settled_weekly_record(row, root=self.store)

        record = producer.build_no_count_record(
            benchmark_packet=self._packet_for(self.rows[2]),
            calendar_week_index=3,
            prior_nav=self.rows[1]["strategy"]["nav"],
            v1_1_reminder=self.rows[2]["v1_1_reminder"],
            reason="model_paper_week_not_settled",
        )
        self.assertTrue(record["strategy"]["no_count"])
        self.assertEqual("model_paper_week_not_settled", record["strategy"]["no_count_reason"])
        self.assertIsNone(record["strategy"]["weekly_return"])
        self.assertFalse(record["strategy"]["strategy_evaluable"])
        self.assertFalse(record["strategy"]["paper_evaluable"])
        self.assertEqual(self.rows[1]["strategy"]["nav"], record["strategy"]["nav"],
                         "an unsettled week did not move the account")

        result = persist_settled_weekly_record(record, root=self.store)
        self.assertEqual("published", result["status"])
        self.assertEqual(3, result["calendar_week_index"])

        # The slot is occupied, so week 4 appends normally instead of refusing.
        self.assertEqual(
            "published", persist_settled_weekly_record(self.rows[3], root=self.store)["status"]
        )
        register = load_lifecycle_register(self.store)
        self.assertEqual(4, register["calendar_week_count"])
        self.assertEqual(3, register["evaluable_week_count"], "the no_count week is not evaluable")
        self.assertEqual("26w-1-26", register["current_window_id"], "the window was not extended")

    def test_a_no_count_week_must_say_why(self) -> None:
        with self.assertRaises(MarketDiagnosticWeeklyProducerError):
            producer.build_no_count_record(
                benchmark_packet=self._packet_for(self.rows[0]),
                calendar_week_index=1,
                prior_nav=None,
                v1_1_reminder=self.rows[0]["v1_1_reminder"],
                reason="",
            )

    def test_an_unsettled_paper_week_is_detected_rather_than_raised(self) -> None:
        """A real account that simply has not settled this week yet is a gap, not a fault."""

        with tempfile.TemporaryDirectory() as td:
            paper = Path(td) / "model_paper_private"
            _start_local_paper_store(paper)  # settles 20260720 and 20260727
            packet = _packet()
            week = packet["weeks"][0]
            week["calendar_week_index"] = 2
            week["settlement_decision_date"] = "20260803"
            week["valuation_date"] = "20260807"
            week["decision_date"] = "20260810"
            self.assertFalse(producer.model_paper_week_is_settled(paper, packet, 2))
            # Week 1 IS settled in that store, so the same probe says so.
            self.assertTrue(producer.model_paper_week_is_settled(paper, _packet(), 1))

    def test_a_missing_model_paper_store_is_a_fault_not_a_no_count_week(self) -> None:
        """"The account has not settled this week" and "there is no account" are different."""

        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "model_paper_private"
            empty.mkdir()
            with self.assertRaises(MarketDiagnosticWeeklyProducerError) as ctx:
                producer.model_paper_week_is_settled(empty, _packet(), 1)
        self.assertIn("not initialized", str(ctx.exception))


class StoreStateTest(unittest.TestCase):
    """The four-way question three readers used to answer three different ways."""

    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.store = Path(holder.name) / "market_diagnostic_private"
        self.rows = _weekly_rows()

    def _open(self) -> None:
        _open_clock(
            self.store,
            epoch=self.rows[0]["diagnostic_epoch"],
            first_decision_date=self.rows[0]["decision_date"],
        )

    def test_a_clock_opened_this_week_is_fresh_not_broken(self) -> None:
        """Calling a normal first week "broken" teaches the operator to ignore the word."""

        from runners.us_short_market_diagnostic_weekly import clock_status

        self._open()
        self.assertEqual("fresh", producer.diagnostic_store_state(self.store)["state"])

        status = clock_status(root=self.store)
        self.assertEqual("fresh", status["clock_status"])
        self.assertEqual(0, status["calendar_week_count"])

        step = weekly_diagnostic_step(root=self.store)
        self.assertEqual("fresh", step["status"])
        self.assertNotIn("故障", step["report_lines"][0])

        # And the producer still knows it is week 1.
        self.assertEqual(1, next_week_inputs(self.store)["calendar_week_index"])

    def test_records_whose_receipt_and_register_are_both_gone_are_broken_everywhere(self) -> None:
        """The evidence of counted weeks is the weekly records, not the register beside them."""

        from runners.us_short_market_diagnostic_weekly import clock_status

        self._open()
        for row in self.rows[:3]:
            persist_settled_weekly_record(row, root=self.store)
        (self.store / "lifecycle_register.json").unlink()
        (self.store / "diagnostic_start_receipt.json").unlink()

        self.assertTrue(producer.has_counted_weeks(self.store))
        self.assertEqual("broken", producer.diagnostic_store_state(self.store)["state"])
        self.assertEqual("broken", clock_status(root=self.store)["clock_status"])
        self.assertEqual("broken", weekly_diagnostic_step(root=self.store)["status"])
        with self.assertRaises(MarketDiagnosticWeeklyProducerError) as ctx:
            next_week_inputs(self.store)
        self.assertIn("start receipt", str(ctx.exception))

    def test_a_store_fault_never_becomes_a_fresh_week_one(self) -> None:
        """A public builder that restarts the NAV series on a fault is a lie the store had to catch."""

        self._open()
        for row in self.rows[:3]:
            persist_settled_weekly_record(row, root=self.store)
        stray = self.store / "weeks" / "19991231" / "weekly_record.json"
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_bytes(canonical_json_bytes(self.rows[0]))

        self.assertEqual("broken", producer.diagnostic_store_state(self.store)["state"])
        with self.assertRaises(MarketDiagnosticWeeklyProducerError):
            next_week_inputs(self.store)
        with self.assertRaises(MarketDiagnosticWeeklyProducerError):
            build_next_weekly_record(
                model_paper_root=self.store, benchmark_packet=_packet(), root=self.store
            )

    def test_an_empty_directory_is_not_started(self) -> None:
        self.assertEqual("not_started", producer.diagnostic_store_state(self.store)["state"])
        self.assertFalse(producer.has_counted_weeks(self.store))


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

    def test_the_stage_reads_the_real_diagnostic_root_by_default(self) -> None:
        """The field shipped with no producer, so the stage could never read a clock.

        Weeks could be settled forever and the official weekly run would still say
        `not_started` — indistinguishable from a clock nobody opened, and section
        12.8 duty 4 wired but inert. The default is supplied by the diagnostic
        track itself, so this module never names the private store.
        """

        from unittest import mock

        import runners.us_short_weekly_capstone as capstone
        from engine.us_short_market_diagnostic_lifecycle import DEFAULT_ROOT as LIFECYCLE_ROOT

        with mock.patch(
            "engine.us_short_market_diagnostic_weekly_task.weekly_diagnostic_step",
            return_value={"status": "not_started", "report_lines": []},
        ) as step:
            capstone._run_market_diagnostic(self._ctx(None))
        step.assert_called_once()
        self.assertNotIn("root", step.call_args.kwargs, "the track must supply its own default")

        # And that default is the real private root, not something else.
        import inspect

        from engine.us_short_market_diagnostic_weekly_task import weekly_diagnostic_step

        self.assertEqual(
            LIFECYCLE_ROOT, inspect.signature(weekly_diagnostic_step).parameters["root"].default
        )

        # An explicit root still wins.
        with mock.patch(
            "engine.us_short_market_diagnostic_weekly_task.weekly_diagnostic_step",
            return_value={"status": "not_started", "report_lines": []},
        ) as step:
            capstone._run_market_diagnostic(self._ctx(self.store))
        self.assertEqual(self.store, step.call_args.kwargs["root"])

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

    def test_a_dormant_stage_cannot_abort_the_week_even_if_its_import_is_broken(self) -> None:
        """The lazy import must sit INSIDE the dormancy guard, not above it.

        Six modules in that import chain load a JSON schema at import time. With
        the import above the guard, a missing schema file raised out of a stage
        that was switched off, and because the stage is strict that rolled back a
        weekly_report.md the bridge had already written.
        """

        import sys
        from unittest import mock

        import runners.us_short_weekly_capstone as capstone

        name = "engine.us_short_market_diagnostic_weekly_task"
        with mock.patch.dict(sys.modules, {name: None}):
            dormant = capstone._run_market_diagnostic(self._ctx(None))
            armed = capstone._run_market_diagnostic(self._ctx(self.store))
        # Either way it is a reported fault, never a raise into the weekly run —
        # which is what stops a switched-off diagnostic discarding a finished report.
        self.assertEqual("broken", dormant["clock_status"])
        self.assertEqual("broken", armed["clock_status"])
        self.assertTrue(dormant["report_lines"])

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
