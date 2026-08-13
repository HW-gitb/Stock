from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_corporate_action_event_recorder as recorder  # noqa: E402
from engine import us_short_corporate_action_workflow as workflow  # noqa: E402
from engine import us_short_sec_simple_corporate_action_parser as sec_parser  # noqa: E402
from engine import us_short_security_identity as identity  # noqa: E402
from engine import us_short_yfinance_corporate_action_alarm as yf_alarm  # noqa: E402


def security(ticker: str = "TWTR", *, cik: str = "1418091") -> dict:
    return identity.record_security_identity(
        issuer_cik=cik,
        security_class="COMMON",
        current_ticker=ticker,
        issuer_name="Example Issuer",
        primary_exchange="NYSE",
        observed_as_of="20260713",
        source_id="manual_seed",
        source_ref_sha256="a" * 64,
    )


def sec_candidate(record: dict) -> dict:
    text = "Each outstanding share became effective on October 28, 2022 and has the right to receive $54.20 in cash."
    return sec_parser.parse_simple_sec_corporate_action(
        identity_record=record,
        filing={
            "provider_id": "sec_edgar",
            "issuer_cik": record["issuer_cik"],
            "form_type": "8-K",
            "accession_number": "0001418091-22-000001",
            "filed_date": "2022-10-28",
            "accepted_at": "2022-10-28T20:00:00Z",
            "observed_at": "2026-07-13T12:00:00Z",
            "document_ref_sha256": "b" * 64,
            "document_text": text,
            "network_access_performed": False,
        },
    )


def yfinance_alarm(record: dict, *, split: float = 0.0) -> dict:
    return yf_alarm.evaluate_yfinance_daily_alarm(
        record,
        {
            "source_ticker": record["current_ticker"],
            "returned_ticker": record["current_ticker"],
            "expected_price_date": "2026-07-10",
            "observed_at": "2026-07-13T12:00:00Z",
            "fetch_status": "ok",
            "price_date": "2026-07-10",
            "close": 10.0,
            "stock_splits": split,
            "dividends": 0.0,
            "network_access_performed": False,
        },
    )


def lifecycle(ticker: str = "TWTR") -> dict:
    return {
        "schema_name": "us_short_forward_lifecycle_observation",
        "schema_version": "1.0.0",
        "forward_start_date": "20260701",
        "decision_date": "20260713",
        "observed_at": "2026-07-13T12:00:00Z",
        "snapshot_ref": {"path": "state/us_short/forward_universe_snapshot_20260701.json", "sha256": "c" * 64},
        "candidate_ref": {"path": "state/us_short/candidate_universe_20260713.json", "sha256": "d" * 64},
        "events": [{
            "event_id": f"{ticker}-inactive",
            "symbol": ticker,
            "event_type": "inactive_or_ticker_change_unresolved",
            "decision_date": "20260713",
            "observed_at": "2026-07-13T12:00:00Z",
            "manual_review_required": True,
            "new_entry_blocked": True,
            "automatic_conversion_or_cash_valuation_performed": False,
        }],
        "coverage": {
            "frozen_symbol_count": 1,
            "current_candidate_row_count": 0,
            "matched_frozen_symbol_count": 0,
            "missing_frozen_symbol_count": 1,
            "known_clear_symbol_count": 0,
            "blocked_symbol_count": 1,
            "critical_status_unknown_symbol_count": 0,
        },
        "retention_policy": {"forward_snapshot_symbols_deleted": False, "lifecycle_events_retained": True},
        "boundary": {
            "network_access_performed": False,
            "provider_calls_performed": False,
            "raw_payload_capture_performed": False,
            "merger_or_ticker_change_semantics_confirmed": False,
            "automatic_corporate_action_processing_performed": False,
            "return_calculation_performed": False,
            "selection_or_ranking_changed": False,
            "datahub_consumption_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
        },
    }


def massive_assessment(ticker: str = "TWTR") -> dict:
    return {
        "schema_name": "us_short_massive_corporate_action_assessment",
        "schema_version": "1.0.0",
        "evidence_binding": {
            "evidence_schema_name": "us_short_massive_corporate_action_reconciliation_evidence",
            "decision_date": "20260713",
            "symbol": ticker,
            "source_binding_sha256": "e" * 64,
            "event_price_windows_sha256": "f" * 64,
        },
        "event_assessments": [{
            "event_id": f"{ticker}-dividend",
            "event_type": "dividend",
            "status": "dividend_adjustment_semantics_unresolved",
        }],
        "coverage": {
            "split_exact_match_count": 0,
            "split_mismatch_or_rounding_unresolved_count": 0,
            "dividend_semantics_unresolved_count": 1,
            "insufficient_price_window_count": 0,
        },
        "boundary": {
            "split_factor_assessment_performed": True,
            "provider_call_performed_during_derivation": False,
            "raw_payload_adapter_performed": False,
            "full_corporate_action_reconciliation_performed": False,
            "return_calculation_performed": False,
            "paper_gate_evaluable_claimed": False,
            "ship_gate_or_production_authorized": False,
        },
    }


def account_state(ticker: str = "TWTR") -> dict:
    return {
        "schema_name": "us_short_account_state",
        "schema_version": "1.0.0",
        "as_of": "20260713",
        "us_market_equity": 30000.0,
        "us_short_bucket_capital": 10000.0,
        "us_short_available_cash": 4000.0,
        "portfolio_total_equity": None,
        "positions": [{
            "ticker": ticker,
            "direction": "long",
            "shares": 5,
            "avg_cost_usd": 10.0,
            "entry_date": "20260601",
            "current_stop": None,
            "notes": None,
        }],
        "symbol_cooldown_reconciliation": {
            "schema_name": "us_short_symbol_cooldown_reconciliation", "schema_version": "1.0.0",
            "as_of": "20260713", "events": []},
        "manual_order_only": True,
        "broker_connection_allowed": False,
    }


def manual_input(record: dict) -> dict:
    accession = "0001418091-22-000001"
    return {
        "security_identity": record,
        "old_ticker": record["current_ticker"],
        "event_type": "cash_consideration",
        "successor_ticker": None,
        "successor_security_identity": None,
        "stock_ratio_numerator": None,
        "stock_ratio_denominator": None,
        "cash_per_old_share_usd": "54.20",
        "effective_date": "2022-10-28",
        "sec_accession": accession,
        "sec_url": f"https://www.sec.gov/Archives/edgar/data/1418091/{accession.replace('-', '')}/event.htm",
        "unsupported_consideration": None,
    }


class CorporateActionWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.identity = security()
        self.candidate = sec_candidate(self.identity)

    def test_sources_without_confirmed_manual_record_stop_at_review(self):
        result = workflow.build_corporate_action_workflow(
            identity_record=self.identity,
            lifecycle_observation=lifecycle(),
            sec_parse_candidate=self.candidate,
            yfinance_daily_alarm=yfinance_alarm(self.identity, split=2.0),
            massive_assessment=massive_assessment(),
            manual_event_record=None,
            disposition_ticket=None,
        )
        self.assertEqual(result["workflow_status"], "manual_review_required")
        self.assertFalse(result["disposition"]["private_ticket_prepared"])
        self.assertIn("manual_event_missing", result["blocking_reasons"])
        self.assertTrue(result["paper_confirmation_state"]["paper_performance_blocked"])
        self.assertFalse(result["boundary"]["corporate_action_semantics_auto_confirmed"])

    def test_confirmed_matching_record_allows_only_private_manual_ticket(self):
        state = account_state()
        record = recorder.record_manual_corporate_action(
            manual_input(self.identity), account_state=state, confirm=True
        )
        ticket = recorder.build_private_disposition(state, record)
        result = workflow.build_corporate_action_workflow(
            identity_record=self.identity,
            lifecycle_observation=lifecycle(),
            sec_parse_candidate=self.candidate,
            yfinance_daily_alarm=yfinance_alarm(self.identity),
            massive_assessment=massive_assessment(),
            manual_event_record=record,
            disposition_ticket=ticket,
        )
        self.assertEqual(result["workflow_status"], "private_disposition_prepared")
        self.assertEqual(result["blocking_reasons"], [])
        self.assertTrue(result["disposition"]["private_ticket_prepared"])
        self.assertFalse(result["boundary"]["account_state_mutated"])
        self.assertFalse(result["boundary"]["broker_order_placed"])
        self.assertFalse(result["paper_confirmation_state"]["paper_performance_evaluable"])
        forged = copy.deepcopy(result)
        forged["boundary"]["paper_gate_confirmation_claimed"] = True
        with self.assertRaises(workflow.CorporateActionWorkflowError):
            workflow.validate_corporate_action_workflow(forged)
        forged = copy.deepcopy(result)
        forged["input_evidence"]["manual_event_record"]["status"] = "manual_review"
        with self.assertRaises(workflow.CorporateActionWorkflowError):
            workflow.validate_corporate_action_workflow(forged)

    def test_extracted_sec_terms_must_match_the_human_confirmed_record(self):
        state = account_state()
        record = recorder.record_manual_corporate_action(
            manual_input(self.identity), account_state=state, confirm=True
        )
        mismatch = copy.deepcopy(self.candidate)
        mismatch["event_candidate"]["cash_per_share_cents"] = 5300
        result = workflow.build_corporate_action_workflow(
            identity_record=self.identity,
            lifecycle_observation=lifecycle(),
            sec_parse_candidate=mismatch,
            yfinance_daily_alarm=None,
            massive_assessment=None,
            manual_event_record=record,
            disposition_ticket=None,
        )
        self.assertEqual(result["workflow_status"], "manual_review_required")
        self.assertIn("sec_candidate_confirmed_event_mismatch", result["blocking_reasons"])
        self.assertFalse(result["disposition"]["private_ticket_prepared"])

    def test_every_source_is_identity_bound_and_forged_authority_is_rejected(self):
        with self.assertRaises(workflow.CorporateActionWorkflowError):
            workflow.build_corporate_action_workflow(
                identity_record=self.identity,
                lifecycle_observation=lifecycle("MSFT"),
                sec_parse_candidate=None,
                yfinance_daily_alarm=None,
                massive_assessment=None,
                manual_event_record=None,
                disposition_ticket=None,
            )
        bad_alarm = yfinance_alarm(self.identity)
        bad_alarm["boundary"]["paper_performance_confirmation_allowed"] = True
        with self.assertRaises(workflow.CorporateActionWorkflowError):
            workflow.build_corporate_action_workflow(
                identity_record=self.identity,
                lifecycle_observation=None,
                sec_parse_candidate=None,
                yfinance_daily_alarm=bad_alarm,
                massive_assessment=None,
                manual_event_record=None,
                disposition_ticket=None,
            )


if __name__ == "__main__":
    unittest.main()
