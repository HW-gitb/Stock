from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))

SCHEMA_PATH = ROOT / "schemas" / "us_short_universe_candidate_artifact.schema.json"


def _status_provenance(ticker="AAPL", *, delisted=False, halted=False, bankruptcy=False, otc=False):
    return {
        "ticker": ticker,
        "as_of": "2026-06-29",
        "observed_at": "2026-06-29T12:00:00+00:00",
        "status_flags_sourced": True,
        "flags": {
            "delisted": {
                "value": delisted, "source_id": "ticker_reference", "as_of": "2026-06-29",
                "observed_at": "2026-06-29T12:00:00+00:00",
                "reference_active_value": False if delisted else True, "coverage": "observed",
            },
            "halted": {
                "value": halted, "source_id": "exchange_halt_feed", "as_of": "2026-06-29",
                "observed_at": "2026-06-29T12:00:00+00:00",
                "halt_feed_observed": True, "coverage": "observed",
            },
            "bankruptcy": {
                "value": bankruptcy, "source_id": "sec_8k_item_103", "as_of": "2026-06-29",
                "observed_at": "2026-06-29T12:00:00+00:00",
                "lookback_window": "P90D",
                "filing_accession_if_found": "0001140361-26-000001" if bankruptcy else None,
                "coverage": "observed",
                "screen_status": "bankrupt_8k_found" if bankruptcy else "screened_no_filing",
            },
            "otc": {
                "value": otc, "source_id": "ticker_reference", "as_of": "2026-06-29",
                "observed_at": "2026-06-29T12:00:00+00:00",
                "primary_exchange_value": "OTC" if otc else "NYSE", "coverage": "observed",
            },
        },
    }


def _row(ticker, *, eligible, adv_usd, reasons, status_sourced=False, status_values=None):
    status_values = status_values or {}
    row = {
        "ticker": ticker, "exchange": "NYSE",
        "price": 200.0, "price_as_of": "2026-06-26", "volume": 600000.0,
        "adv_usd": adv_usd, "adv_days_observed": 20, "adv_coverage_ok": True,
        "shares": 15000000000.0, "market_cap_usd": 3e12, "market_cap_source": "sec_shares_x_close",
        "delisted": status_values.get("delisted", False),
        "halted": status_values.get("halted", False),
        "bankruptcy": status_values.get("bankruptcy", False),
        "otc": status_values.get("otc", False),
        "status_flags_sourced": bool(status_sourced),
        "eligible": eligible, "reasons": reasons,
        "provider_id": "massive_grouped_daily+sec_xbrl_frames_or_companyfacts(+yfinance_info,+massive_ticker_overview)",
        "as_of": "2026-06-26", "observed_at": "2026-06-29T12:00:00+00:00",
        "coverage_status": "complete", "parser_status": "ok",
        "lineage": {
            "price_source": "massive_grouped_daily", "adv_window_trading_days": 20,
            "adv_days_observed": 20, "shares_source": "sec_xbrl_frames",
            "market_cap_source": "sec_shares_x_close",
        },
    }
    if status_sourced:
        row["status_provenance"] = _status_provenance(
            ticker,
            delisted=row["delisted"] is True,
            halted=row["halted"] is True,
            bankruptcy=row["bankruptcy"] is True,
            otc=row["otc"] is True,
        )
        for flag, value in status_values.items():
            if value is None:
                row["status_provenance"]["flags"][flag]["value"] = None
    return row


def _valid_artifact() -> dict:
    rows = [_row("AAPL", eligible=True, adv_usd=1e10, reasons=[]),
            _row("LOW", eligible=False, adv_usd=1000.0, reasons=["adv_usd_below_floor"])]
    return {
        "schema_name": "us_short_universe_candidate_artifact",
        "schema_version": "1.3.0",
        "authorization_ref": "user_chat_20260626_universe_fetch",
        "generated_at": "2026-06-29T12:00:00+00:00",
        "decision_date": "20260629",
        "price_basis_date": "20260626",
        "used_date": "2026-06-26",
        "calendar_verification_status": "pending_authoritative_cross_check",
        "provider": "massive_grouped_daily + sec_shares (+ fmp mktcap fallback)",
        "adv_window": {
            "trading_days": 20, "min_days_required": 10,
            "observed_window_dates": ["2026-06-26", "2026-06-25"], "latest_date": "2026-06-26",
        },
        "rows": rows,
        "row_count": 2,
        "eligible_tickers": ["AAPL"],
        "eligible_count": 1,
        "summary": {
            "eligible_count": 1, "ineligible_count": 1, "no_price_count": 0, "no_shares_count": 0,
            "needs_market_cap": [], "total_tickers": 2,
            "reason_distribution": {"adv_usd_below_floor": 1},
        },
    }


class UsShortUniverseCandidateArtifactSchemaTest(unittest.TestCase):
    def _schema(self) -> dict:
        self.assertTrue(SCHEMA_PATH.exists(), f"missing schema: {SCHEMA_PATH}")
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _errors(self, payload: dict) -> list:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return list(Draft7Validator(self._schema()).iter_errors(payload))

    def test_valid_artifact_passes(self):
        self.assertEqual(self._errors(_valid_artifact()), [])

    def test_missing_adv_window_rejected(self):
        a = copy.deepcopy(_valid_artifact())
        del a["adv_window"]
        self.assertTrue(self._errors(a))

    def test_missing_row_lineage_rejected(self):
        a = copy.deepcopy(_valid_artifact())
        del a["rows"][0]["lineage"]
        self.assertTrue(self._errors(a))

    def test_missing_lineage_subfield_rejected(self):
        a = copy.deepcopy(_valid_artifact())
        del a["rows"][0]["lineage"]["adv_window_trading_days"]
        self.assertTrue(self._errors(a))

    def test_missing_row_as_of_rejected(self):
        a = copy.deepcopy(_valid_artifact())
        del a["rows"][0]["as_of"]
        self.assertTrue(self._errors(a))

    def test_unknown_top_level_key_rejected(self):
        a = copy.deepcopy(_valid_artifact())
        a["surprise"] = 1
        self.assertTrue(self._errors(a))

    def test_unknown_row_key_rejected(self):
        a = copy.deepcopy(_valid_artifact())
        a["rows"][0]["surprise"] = 1
        self.assertTrue(self._errors(a))

    def test_adv_usd_null_allowed(self):
        # null adv (insufficient coverage) is a legal SHAPE; the runner's semantic floor check, not the
        # schema, forbids an *eligible* row from carrying a null/under-covered ADV.
        a = copy.deepcopy(_valid_artifact())
        a["rows"][1]["adv_usd"] = None
        a["rows"][1]["adv_coverage_ok"] = False
        a["rows"][1]["coverage_status"] = "adv_insufficient"
        self.assertEqual(self._errors(a), [])

    def test_bad_decision_date_pattern_rejected(self):
        a = copy.deepcopy(_valid_artifact())
        a["decision_date"] = "2026-06-29"   # must be YYYYMMDD (8 digits, no dashes)
        self.assertTrue(self._errors(a))

    def test_bad_market_cap_source_enum_rejected(self):
        a = copy.deepcopy(_valid_artifact())
        a["rows"][0]["market_cap_source"] = "guess"
        self.assertTrue(self._errors(a))

    def test_yfinance_snapshot_requires_retrieval_lineage(self):
        a = copy.deepcopy(_valid_artifact())
        row = a["rows"][0]
        row["shares"] = None
        row["market_cap_source"] = "yfinance_info_market_cap_snapshot"
        row["lineage"]["shares_source"] = "none"
        row["lineage"]["market_cap_source"] = "yfinance_info_market_cap_snapshot"
        row["lineage"]["market_cap_source_observed_at"] = "2026-06-29T12:00:00+00:00"
        row["lineage"]["market_cap_clock_semantics"] = "retrieval_snapshot_no_historical_asof"
        self.assertEqual(self._errors(a), [])
        del row["lineage"]["market_cap_source_observed_at"]
        self.assertTrue(self._errors(a))

    def test_yfinance_shares_close_requires_basis_shares_and_clock(self):
        a = copy.deepcopy(_valid_artifact())
        row = a["rows"][0]
        row["shares"] = None
        row["market_cap_source"] = "yfinance_info_shares_x_massive_close"
        row["lineage"]["shares_source"] = "none"
        row["lineage"]["market_cap_source"] = "yfinance_info_shares_x_massive_close"
        row["lineage"]["market_cap_basis_shares"] = 15_000_000_000.0
        row["lineage"]["market_cap_source_observed_at"] = "2026-06-29T12:00:00+00:00"
        row["lineage"]["market_cap_clock_semantics"] = "massive_observed_close_plus_retrieval_snapshot_shares"
        self.assertEqual(self._errors(a), [])
        del row["lineage"]["market_cap_basis_shares"]
        self.assertTrue(self._errors(a))

    def test_non_yfinance_source_rejects_yfinance_lineage(self):
        a = copy.deepcopy(_valid_artifact())
        row = a["rows"][0]
        row["lineage"]["market_cap_source_observed_at"] = "2026-06-29T12:00:00+00:00"
        self.assertTrue(self._errors(a))

    def test_wrong_schema_name_rejected(self):
        a = copy.deepcopy(_valid_artifact())
        a["schema_name"] = "something_else"
        self.assertTrue(self._errors(a))

    def test_forged_schema_version_rejected(self):
        # F4 (cc_r1_v1): schema_version const-pinned (was minLength:1) — self-sufficient like sibling schemas.
        a = copy.deepcopy(_valid_artifact())
        a["schema_version"] = "9.9.9-forged"
        self.assertTrue(self._errors(a))

    def test_forged_authorization_ref_rejected(self):
        # F4: authorization_ref const-pinned.
        a = copy.deepcopy(_valid_artifact())
        a["authorization_ref"] = "totally_unauthorized_ref"
        self.assertTrue(self._errors(a))

    def test_status_flags_sourced_true_rejected(self):
        # A sourced row without its per-row status provenance is still a forgery.
        a = copy.deepcopy(_valid_artifact())
        a["rows"][0]["status_flags_sourced"] = True
        self.assertTrue(self._errors(a))

    def test_status_flag_true_rejected(self):
        # Unsourced round-1 rows still pin status flags to false (never sourced-true by omission).
        a = copy.deepcopy(_valid_artifact())
        a["rows"][0]["delisted"] = True
        self.assertTrue(self._errors(a))

    def test_status_sourced_row_with_provenance_passes(self):
        a = _valid_artifact()
        a["rows"][0] = _row("AAPL", eligible=True, adv_usd=1e10, reasons=[], status_sourced=True)
        self.assertEqual(self._errors(a), [])

    def test_status_sourced_unknown_flag_null_allowed(self):
        a = _valid_artifact()
        a["rows"][0] = _row(
            "AAPL", eligible=False, adv_usd=1e10,
            reasons=["status_delisted_unknown_or_invalid"],
            status_sourced=True, status_values={"delisted": None},
        )
        a["eligible_tickers"] = []
        a["eligible_count"] = 0
        a["summary"]["eligible_count"] = 0
        a["summary"]["ineligible_count"] = 2
        a["summary"]["reason_distribution"] = {
            "status_delisted_unknown_or_invalid": 1,
            "adv_usd_below_floor": 1,
        }
        self.assertEqual(self._errors(a), [])

    def test_status_provenance_unknown_key_rejected(self):
        a = _valid_artifact()
        a["rows"][0] = _row("AAPL", eligible=True, adv_usd=1e10, reasons=[], status_sourced=True)
        a["rows"][0]["status_provenance"]["surprise"] = 1
        self.assertTrue(self._errors(a))

    def test_status_provenance_missing_flag_rejected(self):
        a = _valid_artifact()
        a["rows"][0] = _row("AAPL", eligible=True, adv_usd=1e10, reasons=[], status_sourced=True)
        del a["rows"][0]["status_provenance"]["flags"]["halted"]
        self.assertTrue(self._errors(a))


if __name__ == "__main__":
    unittest.main()
