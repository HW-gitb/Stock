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


def _row(ticker, *, eligible, adv_usd, reasons):
    return {
        "ticker": ticker, "exchange": "NYSE",
        "price": 200.0, "price_as_of": "2026-06-26", "volume": 600000.0,
        "adv_usd": adv_usd, "adv_days_observed": 20, "adv_coverage_ok": True,
        "shares": 15000000000.0, "market_cap_usd": 3e12, "market_cap_source": "sec_shares_x_close",
        "delisted": False, "halted": False, "bankruptcy": False, "otc": False,
        "status_flags_sourced": False,
        "eligible": eligible, "reasons": reasons,
        "provider_id": "massive_grouped_daily+sec_xbrl_frames(+fmp_profile)",
        "as_of": "2026-06-26", "observed_at": "2026-06-29T12:00:00+00:00",
        "coverage_status": "complete", "parser_status": "ok",
        "lineage": {
            "price_source": "massive_grouped_daily", "adv_window_trading_days": 20,
            "adv_days_observed": 20, "shares_source": "sec_xbrl_frames",
            "market_cap_source": "sec_shares_x_close",
        },
    }


def _valid_artifact() -> dict:
    rows = [_row("AAPL", eligible=True, adv_usd=1e10, reasons=[]),
            _row("LOW", eligible=False, adv_usd=1000.0, reasons=["adv_usd_below_floor"])]
    return {
        "schema_name": "us_short_universe_candidate_artifact",
        "schema_version": "1.0.0",
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
        # F4: round-1 honesty invariant pinned IN the schema (status source is gated → must be false).
        a = copy.deepcopy(_valid_artifact())
        a["rows"][0]["status_flags_sourced"] = True
        self.assertTrue(self._errors(a))

    def test_status_flag_true_rejected(self):
        # F4: delisted/halted/bankruptcy/otc const false in round-1 (never sourced-true by omission).
        a = copy.deepcopy(_valid_artifact())
        a["rows"][0]["delisted"] = True
        self.assertTrue(self._errors(a))


if __name__ == "__main__":
    unittest.main()
