from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_massive_corporate_action_reconciliation as reconciliation  # noqa: E402


def source_refs():
    return {
        "splits": "a" * 64,
        "dividends": "b" * 64,
        "daily_adjusted": "c" * 64,
        "daily_unadjusted": "d" * 64,
    }


def evidence(*, split_complete: bool = True):
    prices = [
        {"symbol": "AAPL", "session_date": "2020-08-28", "adjustment_mode": "adjusted", "source_family": "daily_adjusted", "close": 25},
        {"symbol": "AAPL", "session_date": "2020-08-28", "adjustment_mode": "unadjusted", "source_family": "daily_unadjusted", "close": 100},
        {"symbol": "AAPL", "session_date": "2020-08-31", "adjustment_mode": "unadjusted", "source_family": "daily_unadjusted", "close": 26},
        {"symbol": "AAPL", "session_date": "2021-05-06", "adjustment_mode": "adjusted", "source_family": "daily_adjusted", "close": 130},
        {"symbol": "AAPL", "session_date": "2021-05-07", "adjustment_mode": "adjusted", "source_family": "daily_adjusted", "close": 131},
        {"symbol": "AAPL", "session_date": "2021-05-06", "adjustment_mode": "unadjusted", "source_family": "daily_unadjusted", "close": 131},
        {"symbol": "AAPL", "session_date": "2021-05-07", "adjustment_mode": "unadjusted", "source_family": "daily_unadjusted", "close": 130},
    ]
    if split_complete:
        prices.append(
            {"symbol": "AAPL", "session_date": "2020-08-31", "adjustment_mode": "adjusted", "source_family": "daily_adjusted", "close": 26}
        )
    return reconciliation.build_event_price_reconciliation_evidence(
        decision_date="20260712",
        symbol="AAPL",
        normalized_event_rows=[
            {"event_id": "AAPL-split-20200831", "symbol": "AAPL", "event_type": "split", "event_date": "2020-08-31", "source_family": "splits"},
            {"event_id": "AAPL-dividend-20210507", "symbol": "AAPL", "event_type": "dividend", "event_date": "2021-05-07", "source_family": "dividends"},
        ],
        normalized_price_rows=prices,
        source_ref_sha256=source_refs(),
    )


def factor_rows():
    return [
        {
            "event_id": "AAPL-split-20200831",
            "split_from": 1,
            "split_to": 4,
            "adjusted_prior_close": 25,
            "adjusted_event_close": 26,
            "unadjusted_prior_close": 100,
            "unadjusted_event_close": 26,
        }
    ]


def measurement_refs():
    refs = source_refs()
    return {key: refs[key] for key in ("splits", "daily_adjusted", "daily_unadjusted")}


class MassiveCorporateActionAssessmentTest(unittest.TestCase):
    def assess(self, *, evidence_value=None, rows=None, refs=None):
        return reconciliation.assess_split_factor_reconciliation(
            event_price_evidence=evidence() if evidence_value is None else evidence_value,
            split_factor_rows=factor_rows() if rows is None else rows,
            measurement_source_ref_sha256=measurement_refs() if refs is None else refs,
        )

    def test_exact_split_factor_match_is_value_free_but_dividend_remains_unresolved(self):
        assessment = self.assess()

        self.assertEqual(
            assessment["event_assessments"],
            [
                {"event_id": "AAPL-split-20200831", "event_type": "split", "status": "split_factor_exact_match"},
                {
                    "event_id": "AAPL-dividend-20210507",
                    "event_type": "dividend",
                    "status": "dividend_adjustment_semantics_unresolved",
                },
            ],
        )
        self.assertEqual(
            assessment["coverage"],
            {
                "split_exact_match_count": 1,
                "split_mismatch_or_rounding_unresolved_count": 0,
                "dividend_semantics_unresolved_count": 1,
                "insufficient_price_window_count": 0,
            },
        )
        self.assertTrue(assessment["boundary"]["split_factor_assessment_performed"])
        self.assertFalse(assessment["boundary"]["full_corporate_action_reconciliation_performed"])
        self.assertFalse(assessment["boundary"]["paper_gate_evaluable_claimed"])
        self.assertNotIn("100", json.dumps(assessment, sort_keys=True))

    def test_split_factor_mismatch_stays_unresolved_not_reconciled(self):
        rows = factor_rows()
        rows[0]["adjusted_event_close"] = 25
        assessment = self.assess(rows=rows)

        self.assertEqual(
            assessment["event_assessments"][0],
            {
                "event_id": "AAPL-split-20200831",
                "event_type": "split",
                "status": "split_factor_mismatch_or_rounding_unresolved",
            },
        )
        self.assertEqual(assessment["coverage"]["split_exact_match_count"], 0)
        self.assertEqual(assessment["coverage"]["split_mismatch_or_rounding_unresolved_count"], 1)
        self.assertFalse(assessment["boundary"]["full_corporate_action_reconciliation_performed"])

    def test_subprecision_split_mismatch_is_not_rounded_into_an_exact_match(self):
        rows = factor_rows()
        rows[0].update(
            {
                "split_from": "1",
                "split_to": "3",
                "adjusted_prior_close": "1",
                "unadjusted_prior_close": "1",
                "adjusted_event_close": str(3 * 10**60),
                "unadjusted_event_close": str(10**60 + 1),
            }
        )
        assessment = self.assess(rows=rows)
        self.assertEqual(
            assessment["event_assessments"][0]["status"],
            "split_factor_mismatch_or_rounding_unresolved",
        )

    def test_incomplete_window_cannot_accept_factor_measurement(self):
        incomplete = evidence(split_complete=False)
        assessment = self.assess(evidence_value=incomplete, rows=[])
        self.assertEqual(assessment["event_assessments"][0]["status"], "insufficient_price_window")

        with self.assertRaises(reconciliation.MassiveCorporateActionReconciliationError):
            self.assess(evidence_value=incomplete, rows=factor_rows())

    def test_missing_extra_or_unbound_factor_measurements_fail_closed(self):
        with self.assertRaises(reconciliation.MassiveCorporateActionReconciliationError):
            self.assess(rows=[])

        extra = factor_rows() + [dict(factor_rows()[0], event_id="AAPL-dividend-20210507")]
        with self.assertRaises(reconciliation.MassiveCorporateActionReconciliationError):
            self.assess(rows=extra)

        bad_refs = measurement_refs()
        bad_refs["daily_unadjusted"] = "e" * 64
        with self.assertRaises(reconciliation.MassiveCorporateActionReconciliationError):
            self.assess(refs=bad_refs)

        bad_coverage = evidence()
        bad_coverage["coverage"]["split_event_count"] = 99
        with self.assertRaises(reconciliation.MassiveCorporateActionReconciliationError):
            self.assess(evidence_value=bad_coverage)

        unknown_field = factor_rows()
        unknown_field[0]["raw_request_url"] = "not-allowed"
        with self.assertRaises(reconciliation.MassiveCorporateActionReconciliationError):
            self.assess(rows=unknown_field)

    def test_nonfinite_or_identity_split_fails_closed(self):
        for field, value in (("adjusted_event_close", float("nan")), ("split_to", 1)):
            rows = factor_rows()
            rows[0][field] = value
            with self.subTest(field=field):
                with self.assertRaises(reconciliation.MassiveCorporateActionReconciliationError):
                    self.assess(rows=rows)


if __name__ == "__main__":
    unittest.main()
