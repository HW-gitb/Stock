from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from engine.us_short_decision_exposure import (
    FILENAME,
    LONG_ONLY_CAP,
    REASON_BAD_ACCOUNT,
    REASON_BAD_REGIME,
    REASON_NO_MARK,
    REASON_NO_PLANNED_COST,
    REASON_OUT_OF_RANGE,
    SCHEMA_NAME,
    DecisionExposureError,
    build_decision_exposure_record,
    exposure_path,
    load_decision_exposure,
    write_decision_exposure,
)

DECISION = "20260803"


def _account(bucket: float = 100000.0, cash: float = 30000.0) -> dict:
    return {
        "as_of": DECISION,
        "us_short_bucket_capital": bucket,
        "us_short_available_cash": cash,
        "positions": [],
    }


def _capacity(*positions) -> dict:
    return {
        "short_bucket_dollars": 100000.0,
        "existing_positions": list(positions) or [
            {"ticker": "AAA", "shares": 100, "mark_price": 200.0, "theme": None}
        ],
    }


def _rows(*, allocated: float | None = 40000.0) -> list[dict]:
    rows = [
        {"ticker": "BBB", "cash_allocation_status": "allocated", "cash_required_at_entry_high": allocated},
        # Rows that were not funded contribute nothing, by design: they are not
        # part of what the plan asked for once cash had its say.
        {"ticker": "CCC", "cash_allocation_status": "insufficient_cash", "cash_required_at_entry_high": 9999.0},
        {"ticker": "DDD", "cash_allocation_status": None, "cash_required_at_entry_high": None},
    ]
    return rows


def _build(**overrides) -> dict:
    kwargs = dict(
        decision_date=DECISION,
        account_state=_account(),
        regime={"market_risk_regime": "谨慎", "position_cap": 0.8},
        rows=_rows(),
        portfolio_capacity=_capacity(),
    )
    kwargs.update(overrides)
    return build_decision_exposure_record(**kwargs)


class DecisionExposureRecordTest(unittest.TestCase):
    def test_the_four_limits_are_the_ones_the_decision_worked_to(self) -> None:
        """Pinned to the numbers, not to the formulas restated.

        A hundred shares marked at 200 is 20,000 of a 100,000 bucket, so carried
        is 0.20; the funded build asks 40,000, so new orders are 0.40; and what
        the cash constraint permits is what is held plus what 30,000 of cash can
        buy, which is 0.50. The account therefore wants 0.60 and may hold 0.50 —
        exactly the case v1.1 exists to explain.
        """

        record = _build()
        self.assertEqual("evaluable", record["status"])
        self.assertAlmostEqual(0.20, record["carried_holdings_exposure"])
        self.assertAlmostEqual(0.40, record["new_order_exposure"])
        self.assertAlmostEqual(0.50, record["cash_capacity_exposure"])
        self.assertAlmostEqual(0.80, record["environment_position_cap"])
        self.assertEqual(LONG_ONLY_CAP, record["long_only_cap"])
        self.assertEqual("谨慎", record["market_risk_regime"])

    def test_the_record_never_carries_an_account_balance(self) -> None:
        """Ratios only, so a copy of it discloses no capital or cash amount."""

        record = _build()
        text = json.dumps(record, ensure_ascii=False)
        for amount in ("100000", "30000", "40000", "20000"):
            with self.subTest(amount):
                self.assertNotIn(amount, text)

    def test_a_holding_the_decision_could_not_price_makes_the_week_unavailable(self) -> None:
        """A hole in carried exposure cannot be filled with a zero.

        Zero would report the account as holding less than it does, and v1.1
        would then charge the difference to stock picking — the exact wrong
        answer this whole track exists to prevent.
        """

        record = _build(
            portfolio_capacity=_capacity(
                {"ticker": "AAA", "shares": 100, "mark_price": 200.0, "theme": None},
                {"ticker": "ZZZ", "shares": 50, "mark_price": None, "theme": None},
            )
        )
        self.assertEqual("unavailable", record["status"])
        self.assertEqual([REASON_NO_MARK], record["unavailable_reasons"])
        self.assertIsNone(record["carried_holdings_exposure"])

    def test_a_funded_build_with_no_cost_makes_the_week_unavailable(self) -> None:
        record = _build(rows=_rows(allocated=None))
        self.assertEqual("unavailable", record["status"])
        self.assertEqual([REASON_NO_PLANNED_COST], record["unavailable_reasons"])

    def test_an_unusable_account_or_regime_is_refused_rather_than_guessed(self) -> None:
        for label, overrides, reason in (
            ("no bucket", {"account_state": _account(bucket=0.0)}, REASON_BAD_ACCOUNT),
            ("negative cash", {"account_state": _account(cash=-1.0)}, REASON_BAD_ACCOUNT),
            ("cap above one", {"regime": {"position_cap": 1.5}}, REASON_BAD_REGIME),
            ("cap missing", {"regime": {}}, REASON_BAD_REGIME),
        ):
            with self.subTest(label):
                record = _build(**overrides)
                self.assertEqual("unavailable", record["status"])
                self.assertIn(reason, record["unavailable_reasons"])

    def test_a_cash_capacity_above_one_is_expressed_at_the_long_only_ceiling(self) -> None:
        """It does not bind there; reporting 1.3 would leave the rule's domain."""

        record = _build(account_state=_account(cash=200000.0))
        self.assertEqual(LONG_ONLY_CAP, record["cash_capacity_exposure"])
        self.assertEqual("evaluable", record["status"])

    def test_an_exposure_outside_zero_to_one_is_refused_rather_than_published(self) -> None:
        """Long-only and unlevered, so this cannot honestly happen.

        If it does, something upstream is not what this module thinks it is —
        a bucket that is not the denominator these marks belong to, say — and
        publishing the number anyway would put a 2.0 into a rule whose whole
        domain is [0, 1].
        """

        record = _build(
            portfolio_capacity=_capacity(
                {"ticker": "AAA", "shares": 1000, "mark_price": 200.0, "theme": None}
            )
        )
        self.assertEqual("unavailable", record["status"])
        self.assertEqual([REASON_OUT_OF_RANGE], record["unavailable_reasons"])

    def test_an_empty_account_is_a_real_zero_not_a_missing_value(self) -> None:
        record = _build(portfolio_capacity={"existing_positions": []})
        self.assertEqual("evaluable", record["status"])
        self.assertEqual(0.0, record["carried_holdings_exposure"])
        self.assertAlmostEqual(0.30, record["cash_capacity_exposure"])


class DecisionExposureStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.runs = Path(holder.name) / "runs_private"

    def test_the_note_is_written_once_and_a_re_run_leaves_it_alone(self) -> None:
        """The decision it describes is the one that was made."""

        first = _build()
        path = write_decision_exposure(first, runs_private_root=self.runs)
        self.assertEqual(exposure_path(DECISION, runs_private_root=self.runs), path)
        original = path.read_bytes()

        write_decision_exposure(_build(regime={"position_cap": 0.1}), runs_private_root=self.runs)
        self.assertEqual(original, path.read_bytes(), "a re-run restated the decision")

    def test_a_non_private_destination_is_refused(self) -> None:
        """The note carries no balance, but it does describe a real account."""

        from engine.us_short_private_paths import ROOT

        with self.assertRaises(DecisionExposureError) as ctx:
            write_decision_exposure(_build(), runs_private_root=ROOT / "docs")
        self.assertIn("non-private", str(ctx.exception))
        self.assertFalse((ROOT / "docs" / DECISION).exists())

    def test_reading_back_a_week_that_never_took_a_note(self) -> None:
        self.assertIsNone(load_decision_exposure(DECISION, runs_private_root=self.runs))

    def test_a_note_filed_under_the_wrong_week_is_refused(self) -> None:
        """The filename is not evidence; the record has to agree with it."""

        write_decision_exposure(_build(), runs_private_root=self.runs)
        path = exposure_path(DECISION, runs_private_root=self.runs)
        record = json.loads(path.read_text(encoding="utf-8"))
        record["decision_date"] = "20260810"
        path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(DecisionExposureError) as ctx:
            load_decision_exposure(DECISION, runs_private_root=self.runs)
        self.assertIn("describes", str(ctx.exception))

    def test_something_that_is_not_an_exposure_note_is_refused(self) -> None:
        path = exposure_path(DECISION, runs_private_root=self.runs)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_name": "something_else"}), encoding="utf-8")
        with self.assertRaises(DecisionExposureError):
            load_decision_exposure(DECISION, runs_private_root=self.runs)

    def test_writing_something_that_is_not_a_record_is_refused(self) -> None:
        with self.assertRaises(DecisionExposureError):
            write_decision_exposure({"schema_name": "not_this"}, runs_private_root=self.runs)


class SelectionIsUnaffectedTest(unittest.TestCase):
    """Design section 1.3: the diagnostic note may never change or block selection."""

    def test_the_orchestrator_never_reads_what_it_wrote(self) -> None:
        """A note nothing consumes cannot change a decision."""

        import inspect

        from engine import us_short_weekend_orchestrator as orchestrator

        source = inspect.getsource(orchestrator)
        self.assertEqual(1, source.count("write_decision_exposure("))
        self.assertNotIn("load_decision_exposure", source)

    def test_a_failing_note_does_not_take_down_the_week(self) -> None:
        """The whole reason the call sits inside a total adapter.

        If the note could raise, a diagnostic that is not even switched on would
        be able to abort a week of stock selection.
        """

        import inspect

        from engine import us_short_weekend_orchestrator as orchestrator

        source = inspect.getsource(orchestrator)
        index = source.index("write_decision_exposure(")
        window = source[index : index + 900]
        self.assertIn("except Exception", window)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
