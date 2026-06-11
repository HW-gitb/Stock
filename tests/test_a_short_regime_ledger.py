"""Tests for the V14.3 regime daily-feature ledger cadence logic (slice 2b-cadence, pure).

Pins: bootstrap backfills the last 252 trading days <= as_of; steady-state appends only new days;
gaps self-heal; reruns are idempotent; no look-ahead; merge is append-only with immutable existing
dates; validate_ledger enforces sorted/contiguous/PIT rows, coverage match, const policy parity,
comparison-only boundary, guard-safe lane, and per-row daily-schema validity. No data fetch.
"""
from __future__ import annotations

import sys
import json
import unittest
from datetime import date, timedelta
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_regime_ledger import (  # noqa: E402
    plan_append, merge_rows, build_ledger, validate_ledger, validate_ledger_envelope,
    validate_ledger_for_append, LEDGER_POLICY, BACKFILL_MIN_TRADING_DAYS,
)

LEDGER_SCHEMA = ROOT / "schemas" / "a_short_regime_daily_ledger.schema.json"


def _cal(n: int) -> list[str]:
    # real consecutive calendar dates (canonical YYYYMMDD), ascending — the ledger gate now
    # strptime-validates dates, so synthetic 20240132-style strings would (correctly) be rejected.
    start = date(2023, 1, 2)
    return [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


def _row(as_of: str) -> dict:
    return {
        "schema_name": "a_short_market_regime_daily", "schema_version": "1.0.0",
        "as_of": as_of, "limit_up_count": 20, "limit_down_count": 5, "net_limit": 15,
        "max_limit_streak": 3, "promotion_rate": 0.30, "failed_limit_rate": 0.20,
        "iv_percentile_252d": 50.0, "csi300_ret_1d": 0.2, "csi1000_ret_1d": 0.3,
        "pct_above_ma20": 55.0, "csi1000_below_ma20": False, "data_quality_flags": [],
        "boundary": {"production": False, "comparison_only": True, "drives_phase5_risk_posture": False},
    }


class PlanAppendTests(unittest.TestCase):
    def test_bootstrap_backfills_last_252(self):
        cal = _cal(300)
        out = plan_append([], cal[-1], cal)
        self.assertEqual(len(out), BACKFILL_MIN_TRADING_DAYS)
        self.assertEqual(out, cal[-252:])

    def test_bootstrap_caps_at_as_of(self):
        cal = _cal(300)
        as_of = cal[260]                      # mid-calendar run
        out = plan_append([], as_of, cal)
        self.assertEqual(out[-1], as_of)      # never beyond as_of
        self.assertEqual(out, cal[9:261])     # last 252 <= as_of

    def test_steady_state_appends_only_new(self):
        cal = _cal(300)
        existing = cal[:260]
        as_of = cal[264]
        out = plan_append(existing, as_of, cal)
        self.assertEqual(out, cal[260:265])   # the 5 new trading days

    def test_gap_self_heal(self):
        cal = _cal(300)
        existing = cal[:200]                  # missed many weeks
        as_of = cal[230]
        out = plan_append(existing, as_of, cal)
        self.assertEqual(out, cal[200:231])   # fills the whole gap up to as_of

    def test_idempotent_rerun_returns_empty(self):
        cal = _cal(300)
        existing = cal[:265]
        out = plan_append(existing, cal[264], cal)   # ledger already at/after as_of
        self.assertEqual(out, [])

    def test_never_returns_future(self):
        cal = _cal(300)
        as_of = cal[270]
        out = plan_append(cal[:200], as_of, cal)
        self.assertTrue(all(d <= as_of for d in out))

    def test_thin_calendar_returns_all_available(self):
        cal = _cal(100)
        out = plan_append([], cal[-1], cal)
        self.assertEqual(out, cal)            # fewer than 252 → all available


class MergeRowsTests(unittest.TestCase):
    def test_append_new_rows_sorted(self):
        existing = [_row(d) for d in _cal(3)]
        new = [_row(d) for d in _cal(5)[3:]]
        merged = merge_rows(existing, new, _cal(5)[-1])
        self.assertEqual([r["as_of"] for r in merged], _cal(5))

    def test_reject_future_row(self):
        with self.assertRaises(ValueError):
            merge_rows([], [_row("20240110")], "20240105")

    def test_reject_immutable_conflict(self):
        existing = [_row("20240101")]
        changed = _row("20240101")
        changed["limit_up_count"] = 999
        with self.assertRaises(ValueError):
            merge_rows(existing, [changed], "20240101")

    def test_identical_reappend_is_noop(self):
        existing = [_row("20240101")]
        merged = merge_rows(existing, [_row("20240101")], "20240101")
        self.assertEqual(len(merged), 1)


class ValidateLedgerTests(unittest.TestCase):
    def _schema(self):
        return json.loads(LEDGER_SCHEMA.read_text(encoding="utf-8"))

    def _valid(self, n=10):
        cal = _cal(n)
        return build_ledger([_row(d) for d in cal]), cal

    def test_valid_ledger_passes(self):
        led, cal = self._valid()
        self.assertTrue(validate_ledger(led, as_of=cal[-1], trade_calendar=cal))
        jsonschema.validate(led, self._schema())

    def test_reject_unsorted_rows(self):
        led, cal = self._valid()
        led["rows"] = list(reversed(led["rows"]))
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal)

    def test_reject_duplicate_dates(self):
        led, cal = self._valid()
        led["rows"].append(led["rows"][-1])
        led["coverage"]["n"] += 1
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal)

    def test_reject_coverage_mismatch(self):
        led, cal = self._valid()
        led["coverage"]["n"] = 999
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal)

    def test_reject_policy_mutation(self):
        led, cal = self._valid()
        led["policy"]["percentile_window"] = 100
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal)

    def test_reject_non_comparison_boundary(self):
        led, cal = self._valid()
        led["boundary"]["drives_phase5_risk_posture"] = True
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal)

    def test_reject_production_lane_root(self):
        led, cal = self._valid()
        led["boundary"]["lane_root"] = "result/a_short"
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal)

    def test_reject_gap_in_contiguity(self):
        cal = _cal(10)
        rows = [_row(d) for d in cal if d != cal[5]]   # drop a middle trading day
        led = build_ledger(rows)
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal)

    def test_reject_date_not_on_calendar(self):
        led, cal = self._valid()
        led["rows"].append(_row("29991231"))
        led = build_ledger(led["rows"])
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal)

    def test_reject_invalid_row(self):
        led, cal = self._valid()
        led["rows"][3]["limit_up_count"] = "not-an-int"
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal)

    def test_reject_schema_envelope_invalid(self):
        led, cal = self._valid()
        del led["policy"]
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal)


class PITGateTests(unittest.TestCase):
    """R-V143-SLICE2B-LEDGER-PIT-ASOF-GAP: future rows / non-contiguity must not survive the gate."""

    def _schema(self):
        return json.loads(LEDGER_SCHEMA.read_text(encoding="utf-8"))

    def test_merge_rejects_existing_future_row(self):
        with self.assertRaises(ValueError):
            merge_rows([_row("20240108")], [], "20240105")

    def test_plan_append_rejects_future_contaminated_ledger(self):
        cal = _cal(300)
        with self.assertRaises(ValueError):
            plan_append(["20240108"], "20240105", cal)   # existing date > as_of

    def test_validate_rejects_future_row_with_as_of(self):
        cal = _cal(20)
        led = build_ledger([_row(d) for d in cal[:10]])   # rows through cal[9]
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[4], trade_calendar=cal)   # as_of before last row

    def test_validate_requires_as_of_and_calendar(self):
        led, cal = build_ledger([_row(d) for d in _cal(10)]), _cal(10)
        with self.assertRaises(TypeError):
            validate_ledger(led)                          # as_of + trade_calendar are mandatory
        with self.assertRaises(TypeError):
            validate_ledger(led, trade_calendar=cal)      # as_of still missing

    def test_reject_stale_but_contiguous_ledger(self):
        # R-V143-SLICE2B-LEDGER-STALE-COVERAGE-GAP: contiguous + PIT but last row earlier than the
        # latest trading day <= as_of must be rejected (else classifier reads old features for as_of).
        cal = _cal(12)
        led = build_ledger([_row(d) for d in cal[:5]])     # rows through cal[4]
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[9], trade_calendar=cal)

    def test_current_through_as_of_passes(self):
        cal = _cal(12)
        led = build_ledger([_row(d) for d in cal[:10]])    # rows through cal[9]
        self.assertTrue(validate_ledger(led, as_of=cal[9], trade_calendar=cal))

    def test_empty_ledger_passes_pre_bootstrap(self):
        cal = _cal(12)
        led = build_ledger([])
        self.assertTrue(validate_ledger(led, as_of=cal[5], trade_calendar=cal))

    def test_envelope_is_context_free_but_misses_pit_and_gaps(self):
        # a gappy / future-dated ledger passes the envelope (no calendar/as_of) but the full gate
        # must reject it — proving the envelope is not a substitute for validate_ledger.
        cal = _cal(20)
        gappy = build_ledger([_row(d) for d in cal[:10] if d != cal[5]])
        self.assertTrue(validate_ledger_envelope(gappy))   # envelope alone accepts it
        with self.assertRaises(ValueError):
            validate_ledger(gappy, as_of=cal[9], trade_calendar=cal)   # full gate rejects the gap


class RowContractIntegrityTests(unittest.TestCase):
    """Comprehensive re-审查 round: finite / date-semantics / net_limit / no-bypass / dup-collapse."""

    def _valid(self, n=10):
        cal = _cal(n)
        return build_ledger([_row(d) for d in cal]), cal

    def test_reject_non_finite_daily_feature(self):
        # R-V143-SLICE2B-LEDGER-NONFINITE-DAILY-FEATURES
        for field in ("promotion_rate", "failed_limit_rate", "iv_percentile_252d",
                      "csi300_ret_1d", "csi1000_ret_1d", "pct_above_ma20"):
            for bad in (float("nan"), float("inf"), float("-inf")):
                led, cal = self._valid()
                led["rows"][3][field] = bad
                with self.assertRaises(ValueError):
                    validate_ledger(led, as_of=cal[-1], trade_calendar=cal)

    def test_reject_malformed_as_of(self):
        # R-V143-SLICE2B-LEDGER-DATE-SEMANTICS-GAP (as_of param)
        led, cal = self._valid()
        for bad in ("20240231", "20240199", "202401105"):
            with self.assertRaises(ValueError):
                validate_ledger(led, as_of=bad, trade_calendar=cal)
            with self.assertRaises(ValueError):
                plan_append([], bad, cal)

    def test_reject_noncanonical_calendar_entry(self):
        led, cal = self._valid()
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal + ["20240231"])

    def test_reject_impossible_row_date(self):
        led, cal = self._valid()
        led["rows"][3]["as_of"] = "20240231"   # passes ^[0-9]{8}$ but is not a real date
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal)

    def test_reject_net_limit_inconsistent(self):
        # R-V143-SLICE2B-LEDGER-NET-LIMIT-INVARIANT-GAP
        led, cal = self._valid()
        led["rows"][2]["net_limit"] = 999   # != 20 - 5
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal)

    def test_no_validate_rows_bypass(self):
        # R-V143-SLICE2B-LEDGER-ROW-VALIDATION-BYPASS: the sanctioned gate has no row-validation flag
        led, cal = self._valid()
        with self.assertRaises(TypeError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal, validate_rows=False)
        led["rows"][3]["limit_up_count"] = "bad"
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal)

    def test_merge_rejects_duplicate_existing_conflicting(self):
        # R-V143-SLICE2B-MERGE-EXISTING-DUPLICATE-COLLAPSE
        a = _row("20240101")
        b = _row("20240101")
        b["limit_up_count"] = 99
        with self.assertRaises(ValueError):
            merge_rows([a, b], [], "20240101")

    def test_merge_rejects_duplicate_existing_identical(self):
        a = _row("20240101")
        with self.assertRaises(ValueError):
            merge_rows([a, dict(a)], [], "20240101")


class CanonicalDateStrictnessTests(unittest.TestCase):
    """R-V143-SLICE2B-CANONICAL-DATE-LENIENCY-GAP: strptime alone parses 2024011 / '202401 1'."""

    def _valid(self, n=10):
        cal = _cal(n)
        return build_ledger([_row(d) for d in cal]), cal

    def test_validate_rejects_lenient_as_of(self):
        led, cal = self._valid()
        for bad in ("2024011", "202401 1", " 20240101", "20240101 "):
            with self.assertRaises(ValueError):
                validate_ledger(led, as_of=bad, trade_calendar=cal)

    def test_plan_append_rejects_lenient_as_of(self):
        cal = _cal(10)
        for bad in ("2024011", "202401 1"):
            with self.assertRaises(ValueError):
                plan_append([], bad, cal)

    def test_validate_rejects_lenient_calendar_entry(self):
        led, cal = self._valid()
        with self.assertRaises(ValueError):
            validate_ledger(led, as_of=cal[-1], trade_calendar=cal + ["2024011"])

    def test_plan_append_rejects_lenient_calendar_entry(self):
        cal = _cal(10)
        with self.assertRaises(ValueError):
            plan_append([], cal[-1], cal + ["202401 1"])


class AppendPregateTests(unittest.TestCase):
    """R-V143-SLICE2B-APPEND-PREGATE-CONTRADICTION: the pre-append gate must accept the normal
    (stale-but-contiguous through prior run date) ledger, while the current/read gate rejects it."""

    def test_for_append_accepts_stale_but_contiguous(self):
        cal = _cal(12)
        existing = build_ledger([_row(d) for d in cal[:5]])    # ends at cal[4] (prior run date)
        self.assertTrue(validate_ledger_for_append(existing, as_of=cal[9], trade_calendar=cal))
        # the same ledger must FAIL the current/read gate (freshness)
        with self.assertRaises(ValueError):
            validate_ledger(existing, as_of=cal[9], trade_calendar=cal)

    def test_for_append_rejects_gappy_existing(self):
        cal = _cal(12)
        gappy = build_ledger([_row(d) for d in cal[:6] if d != cal[3]])
        with self.assertRaises(ValueError):
            validate_ledger_for_append(gappy, as_of=cal[9], trade_calendar=cal)

    def test_for_append_rejects_future_row(self):
        cal = _cal(12)
        led = build_ledger([_row(d) for d in cal[:8]])
        with self.assertRaises(ValueError):
            validate_ledger_for_append(led, as_of=cal[4], trade_calendar=cal)

    def test_full_weekly_workflow_pregate_plan_merge_current(self):
        cal = _cal(12)
        existing_rows = [_row(d) for d in cal[:5]]              # through cal[4]
        existing = build_ledger(existing_rows)
        as_of = cal[9]
        # 1) pre-append historical gate accepts the prior-date ledger
        self.assertTrue(validate_ledger_for_append(existing, as_of=as_of, trade_calendar=cal))
        # 2) plan the new days
        todo = plan_append([r["as_of"] for r in existing_rows], as_of, cal)
        self.assertEqual(todo, cal[5:10])
        # 3) merge the computed rows
        merged_rows = merge_rows(existing_rows, [_row(d) for d in todo], as_of)
        merged = build_ledger(merged_rows)
        # 4) the current/read gate now passes (fresh through as_of)
        self.assertTrue(validate_ledger(merged, as_of=as_of, trade_calendar=cal))


class ApiHardeningTests(unittest.TestCase):
    """R-V143-SLICE2B-API-HARDENING-DOC-DRIFT: generator calendar, backfill_min, duplicate existing."""

    def test_validate_accepts_generator_calendar(self):
        # calendar consumed once → a one-shot generator must not be falsely rejected.
        cal = _cal(10)
        led = build_ledger([_row(d) for d in cal])
        self.assertTrue(validate_ledger(led, as_of=cal[-1], trade_calendar=(d for d in cal)))

    def test_plan_append_accepts_generator_calendar(self):
        cal = _cal(10)
        out = plan_append([], cal[-1], (d for d in cal), backfill_min=5)
        self.assertEqual(out, cal[-5:])

    def test_plan_append_rejects_nonpositive_backfill_min(self):
        cal = _cal(10)
        for bad in (0, -1):
            with self.assertRaises(ValueError):
                plan_append([], cal[-1], cal, backfill_min=bad)

    def test_plan_append_rejects_duplicate_existing(self):
        cal = _cal(10)
        with self.assertRaises(ValueError):
            plan_append([cal[0], cal[0]], cal[-1], cal)


class PolicyParityTests(unittest.TestCase):
    def test_policy_matches_schema_consts(self):
        schema = json.loads(LEDGER_SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]["policy"]["properties"]
        for k, v in LEDGER_POLICY.items():
            self.assertEqual(props[k]["const"], v, f"policy.{k} drift between code and schema")


if __name__ == "__main__":
    unittest.main()
