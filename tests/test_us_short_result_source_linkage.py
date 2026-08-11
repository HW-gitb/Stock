from __future__ import annotations

import json
import unittest

from engine.us_short_result_source_linkage import (
    ResultSourceLinkageError,
    bind_result_source_facts,
    source_coverage_effect_records,
    validate_result_source_fact,
)


_AS_OF = "20260615"
_PRICE_BASIS = "20260612"
_DIGEST = "a" * 64


def _fact(*, ticker="AAPL", row_source="top15_candidate", status="full"):
    checks = {"analyst": "ok", "sec_parse": "ok", "event": "ok", "price": "ok"}
    gaps = []
    if status == "partial":
        checks["price"], gaps = "missing", ["price:missing"]
    elif status == "restricted":
        checks["event"], gaps = "restricted", ["event:restricted"]
    bars = [{"high": 101.0 + idx, "low": 99.0 + idx, "close": 100.0 + idx} for idx in range(15)]
    evidence = {"kind": "source_id", "value": "bundle:" + ticker, "as_of": _AS_OF}
    return {
        "ticker": ticker,
        "row_source": row_source,
        "as_of": _AS_OF,
        "price_basis_date": _PRICE_BASIS,
        "source_bundle_digest": _DIGEST,
        "coverage": {
            "row_source": row_source,
            "data_checks": checks,
            "coverage_status": status,
            "coverage_gap_tags": gaps,
        },
        "catalyst": {
            "status": "realized",
            "coverage_disposition": "scored_realized_catalyst",
            "coverage_matrix": {"score_projection_disposition": "scored_realized_catalyst"},
            "provenance": {"source_bundle_digest": _DIGEST},
            "evidence_ref": {"kind": "source_id", "value": "catalyst:" + ticker, "as_of": _AS_OF},
        },
        "price": {
            "status": "ohlcv_ready",
            "input": {"close": bars[-1]["close"], "bars": bars},
            "observed_at": "2026-06-15T00:00:00Z",
            "session": "RTH",
            "adjustment_mode": "adjusted",
            "evidence_ref": {"kind": "source_id", "value": "ohlcv:" + ticker, "as_of": _AS_OF},
        },
        "data_quality_tags": gaps + ["catalyst:realized"],
        "execution_constraints": ["spread:unavailable_manual_check"],
        "evidence_ref": evidence,
    }


class ResultSourceLinkageTest(unittest.TestCase):
    def test_sorted_json_round_trip_preserves_multigap_source_fact(self):
        fact = _fact()
        checks = {
            "analyst": "ok",
            "sec_parse": "restricted",
            "event": "ok",
            "momentum": "ok",
            "theme": "ok",
            "catalyst": "blocked",
            "price": "ok",
        }
        fact["coverage"] = {
            "row_source": "top15_candidate",
            "data_checks": checks,
            "coverage_status": "blocked",
            "coverage_gap_tags": ["sec_parse:restricted", "catalyst:blocked"],
        }
        fact["catalyst"] = {
            **fact["catalyst"],
            "status": "gated",
            "coverage_disposition": "blocked",
            "coverage_matrix": {"score_projection_disposition": "blocked"},
        }
        fact["data_quality_tags"] = ["sec_parse:restricted", "catalyst:blocked", "catalyst:gated"]
        round_tripped = json.loads(json.dumps(fact, ensure_ascii=False, sort_keys=True))
        validated = validate_result_source_fact(
            round_tripped,
            ticker="AAPL",
            row_source="top15_candidate",
            as_of=_AS_OF,
            price_basis_date=_PRICE_BASIS,
        )
        self.assertEqual(validated["coverage"], fact["coverage"])
        self.assertEqual(validated["data_quality_tags"], fact["data_quality_tags"])

    def test_swapped_ticker_or_date_source_fact_fails_before_price_binding(self):
        swapped = _fact(ticker="MSFT")
        row = {"ticker": "AAPL", "row_source": "top15_candidate", "source_result_facts": swapped}
        with self.assertRaises(ResultSourceLinkageError):
            bind_result_source_facts([row], as_of=_AS_OF, price_basis_date=_PRICE_BASIS)

        stale = _fact()
        stale["as_of"] = "20260622"
        with self.assertRaises(ResultSourceLinkageError):
            validate_result_source_fact(stale, ticker="AAPL", row_source="top15_candidate",
                                        as_of=_AS_OF, price_basis_date=_PRICE_BASIS)

    def test_restricted_source_blocks_new_build_but_never_overrides_protective_exit(self):
        build = {"ticker": "AAPL", "final_action": "\u5efa\u4ed3", "source_result_facts": _fact(status="restricted")}
        exit_row = {"ticker": "MSFT", "final_action": "\u6e05\u4ed3-\u6b62\u635f",
                    "source_result_facts": _fact(ticker="MSFT", status="restricted")}
        records = source_coverage_effect_records([build, exit_row], as_of=_AS_OF)
        self.assertEqual(records["AAPL"][0]["action_override"],
                         {"final_action": "\u89c2\u5bdf", "observe_reason_type": "data_restricted"})
        self.assertIsNone(records["MSFT"][0]["action_override"])
        self.assertEqual(records["MSFT"][0]["confidence_cap"], 0.50)

    def test_partial_source_lowers_confidence_with_named_gap(self):
        row = {"ticker": "AAPL", "final_action": "\u5efa\u4ed3", "source_result_facts": _fact(status="partial")}
        record = source_coverage_effect_records([row], as_of=_AS_OF)["AAPL"][0]
        self.assertEqual(record["confidence_cap"], 0.75)
        self.assertIn("price:missing", record["risk_tags"])

    def test_price_receipt_requires_observed_session_and_adjustment_binding(self):
        for field in ("observed_at", "session", "adjustment_mode"):
            malformed = _fact()
            malformed["price"][field] = ""
            with self.subTest(field=field), self.assertRaises(ResultSourceLinkageError):
                validate_result_source_fact(malformed, ticker="AAPL", row_source="top15_candidate",
                                            as_of=_AS_OF, price_basis_date=_PRICE_BASIS)
