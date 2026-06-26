"""Tests for runners/us_short_fmp_universe_fetch.py.

Covers:
- Authorization artifact validation (must have correct authorization_ref + full_market_fetch_authorized)
- Screener row mapping → cheap_eligible fields (including ADV computation + status inference)
- Pass1 gate application (eligible/ineligible with reasons)
- Dry-run-env mode (no network, no writes)
- Boundary guards: no secrets in summary, gitignore required, budget enforced
- Adversarial: missing fields fail closed, invalid ADV ineligible, bad exchange ineligible

No live FMP calls run here. All tests use offline fixtures.
"""
from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runners.us_short_fmp_universe_fetch as _mod


# ---------------------------------------------------------------------------
# Helpers / minimal fixtures
# ---------------------------------------------------------------------------

_VALID_SCREENER_ROW = {
    "symbol": "AAPL",
    "exchangeShortName": "NASDAQ",
    "exchange": "NASDAQ",
    "price": 175.0,
    "volAvg": 60_000_000,
    "volume": 55_000_000,
    "marketCap": 2_700_000_000_000.0,
    "isActivelyTrading": True,
    "isEtf": False,
    "companyName": "Apple Inc.",
}

_VALID_GOV_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"


def _load_gov():
    from engine.us_short_eligibility_gate import load_eligibility_governance
    return load_eligibility_governance(_VALID_GOV_PATH)


# ---------------------------------------------------------------------------
# Authorization artifact
# ---------------------------------------------------------------------------

class TestAuthorizationArtifact(unittest.TestCase):
    def setUp(self):
        self.auth_path = ROOT / "docs" / "us_short_fmp_universe_fetch_authorization_20260626.json"

    def test_artifact_exists(self):
        self.assertTrue(self.auth_path.exists(), "authorization artifact must exist")

    def test_authorization_ref_correct(self):
        with self.auth_path.open(encoding="utf-8") as fh:
            auth = json.load(fh)
        self.assertEqual(auth["authorization_ref"], _mod.AUTHORIZATION_REF)

    def test_full_market_fetch_authorized_true(self):
        with self.auth_path.open(encoding="utf-8") as fh:
            auth = json.load(fh)
        self.assertTrue(auth["scope"]["full_market_fetch_authorized"])

    def test_all_prohibited_actions_false(self):
        with self.auth_path.open(encoding="utf-8") as fh:
            auth = json.load(fh)
        for key, val in auth["prohibited_actions"].items():
            self.assertFalse(val, f"prohibited_actions.{key} must be false")

    def test_schema_validates_artifact(self):
        sys.path.insert(0, str(ROOT / ".tools" / "python_libs"))
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not available")
        schema_path = ROOT / "schemas" / "us_short_fmp_universe_fetch_authorization.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        with self.auth_path.open(encoding="utf-8") as fh:
            artifact = json.load(fh)
        errors = list(jsonschema.Draft7Validator(schema).iter_errors(artifact))
        self.assertEqual(errors, [], f"schema errors: {errors}")


# ---------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------

class TestMapScreenerRow(unittest.TestCase):
    def test_valid_row_with_volavg(self):
        row = _VALID_SCREENER_ROW.copy()
        mapped = _mod.map_screener_row(row)
        self.assertEqual(mapped["ticker"], "AAPL")
        self.assertEqual(mapped["exchange"], "NASDAQ")
        self.assertAlmostEqual(mapped["price"], 175.0)
        # adv_usd = volAvg * price = 60M * 175 = 10.5B
        self.assertAlmostEqual(mapped["adv_usd"], 60_000_000 * 175.0)
        self.assertAlmostEqual(mapped["market_cap_usd"], 2_700_000_000_000.0)
        self.assertFalse(mapped["delisted"])
        self.assertFalse(mapped["halted"])
        self.assertFalse(mapped["bankruptcy"])
        self.assertFalse(mapped["otc"])

    def test_adv_fallback_to_volume_when_volavg_absent(self):
        row = {**_VALID_SCREENER_ROW, "volAvg": None, "volume": 50_000_000}
        mapped = _mod.map_screener_row(row)
        # adv_usd = volume * price = 50M * 175
        self.assertAlmostEqual(mapped["adv_usd"], 50_000_000 * 175.0)

    def test_adv_none_when_both_volume_fields_absent(self):
        row = {**_VALID_SCREENER_ROW, "volAvg": None, "volume": None}
        mapped = _mod.map_screener_row(row)
        self.assertIsNone(mapped["adv_usd"])

    def test_otc_true_for_non_whitelist_exchange(self):
        row = {**_VALID_SCREENER_ROW, "exchangeShortName": "OTC"}
        mapped = _mod.map_screener_row(row)
        self.assertTrue(mapped["otc"])

    def test_delisted_true_when_not_actively_trading(self):
        row = {**_VALID_SCREENER_ROW, "isActivelyTrading": False}
        mapped = _mod.map_screener_row(row)
        self.assertTrue(mapped["delisted"])
        self.assertTrue(mapped["halted"])
        self.assertTrue(mapped["bankruptcy"])

    def test_missing_price_gives_none(self):
        row = {**_VALID_SCREENER_ROW, "price": None}
        mapped = _mod.map_screener_row(row)
        self.assertIsNone(mapped["price"])

    def test_missing_market_cap_gives_none(self):
        row = {**_VALID_SCREENER_ROW, "marketCap": None}
        mapped = _mod.map_screener_row(row)
        self.assertIsNone(mapped["market_cap_usd"])


# ---------------------------------------------------------------------------
# Pass1 application
# ---------------------------------------------------------------------------

class TestApplyPass1(unittest.TestCase):
    def setUp(self):
        self.gov = _load_gov()

    def _make_row(self, **overrides):
        row = _VALID_SCREENER_ROW.copy()
        row.update(overrides)
        return row

    def test_valid_row_eligible(self):
        result = _mod.apply_pass1([_VALID_SCREENER_ROW], governance=self.gov)
        self.assertEqual(result["eligible_count"], 1)
        self.assertIn("AAPL", result["eligible_tickers"])
        self.assertEqual(result["ineligible_count"], 0)

    def test_price_below_floor_ineligible(self):
        row = self._make_row(price=4.99)
        result = _mod.apply_pass1([row], governance=self.gov)
        self.assertEqual(result["eligible_count"], 0)
        self.assertIn("price_below_floor", result["reason_distribution"])

    def test_market_cap_below_floor_ineligible(self):
        row = self._make_row(marketCap=299_000_000.0)
        result = _mod.apply_pass1([row], governance=self.gov)
        self.assertEqual(result["eligible_count"], 0)
        self.assertIn("market_cap_usd_below_floor", result["reason_distribution"])

    def test_adv_below_floor_ineligible(self):
        # volume*price = 100 * 175 = $17,500 (well below $5M floor)
        row = self._make_row(volAvg=None, volume=100)
        result = _mod.apply_pass1([row], governance=self.gov)
        self.assertEqual(result["eligible_count"], 0)
        self.assertIn("adv_usd_below_floor", result["reason_distribution"])

    def test_missing_adv_fails_closed(self):
        row = self._make_row(volAvg=None, volume=None)
        result = _mod.apply_pass1([row], governance=self.gov)
        self.assertEqual(result["eligible_count"], 0)
        self.assertIn("adv_usd_unknown_or_invalid", result["reason_distribution"])

    def test_non_whitelist_exchange_ineligible(self):
        row = self._make_row(exchangeShortName="AMEX")
        result = _mod.apply_pass1([row], governance=self.gov)
        self.assertEqual(result["eligible_count"], 0)

    def test_otc_exchange_ineligible(self):
        row = self._make_row(exchangeShortName="OTC")
        result = _mod.apply_pass1([row], governance=self.gov)
        self.assertEqual(result["eligible_count"], 0)
        self.assertIn("status_otc", result["reason_distribution"])

    def test_delisted_ineligible(self):
        row = self._make_row(isActivelyTrading=False)
        result = _mod.apply_pass1([row], governance=self.gov)
        self.assertEqual(result["eligible_count"], 0)
        self.assertIn("status_delisted", result["reason_distribution"])

    def test_mixed_rows_counts_correct(self):
        rows = [
            _VALID_SCREENER_ROW,
            {**_VALID_SCREENER_ROW, "symbol": "MSFT", "price": 3.0},  # below price floor
        ]
        result = _mod.apply_pass1(rows, governance=self.gov)
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["ineligible_count"], 1)
        self.assertEqual(result["total_screener_rows"], 2)

    def test_no_duplicate_eligible_tickers(self):
        # Same symbol twice → should deduplicate
        rows = [_VALID_SCREENER_ROW, _VALID_SCREENER_ROW.copy()]
        result = _mod.apply_pass1(rows, governance=self.gov)
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["eligible_tickers"].count("AAPL"), 1)


# ---------------------------------------------------------------------------
# Authorization guard: run_fetch raises without authorization flag
# ---------------------------------------------------------------------------

class TestAuthorizationGuard(unittest.TestCase):
    def test_requires_authorization_flag_for_live(self):
        with self.assertRaises(RuntimeError) as ctx:
            _mod.run_fetch(confirm_user_authorization=False, dry_run_env=False)
        self.assertIn("confirm-user-authorization", str(ctx.exception))

    def test_dry_run_env_does_not_require_authorization(self):
        # Should not raise even without confirm_user_authorization
        with patch.object(_mod, "_check_gitignore", return_value=True):
            summary = _mod.run_fetch(dry_run_env=True, confirm_user_authorization=False)
        self.assertEqual(summary["scope"]["status"], "dry_run_env_only")
        self.assertFalse(summary["scope"]["full_market_fetch_performed"])


# ---------------------------------------------------------------------------
# Summary safety
# ---------------------------------------------------------------------------

class TestSummarySafety(unittest.TestCase):
    def _write_summary(self, path, content_str):
        path.write_text(content_str, encoding="utf-8")

    def test_summary_with_secret_raises(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as fh:
            fh.write('{"apikey=": "value"}')
            path = Path(fh.name)
        try:
            with self.assertRaises(RuntimeError) as ctx:
                _mod._assert_summary_safe(path, "my_secret_key")
            self.assertIn("forbidden", str(ctx.exception))
        finally:
            path.unlink(missing_ok=True)

    def test_summary_with_request_url_raises(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as fh:
            fh.write('{"request_url": "https://financialmodelingprep.com/stable?apikey=xxx"}')
            path = Path(fh.name)
        try:
            with self.assertRaises(RuntimeError):
                _mod._assert_summary_safe(path, "")
        finally:
            path.unlink(missing_ok=True)

    def test_clean_summary_passes(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as fh:
            fh.write('{"eligible_count": 1500, "status": "ok"}')
            path = Path(fh.name)
        try:
            _mod._assert_summary_safe(path, "secret_key_value")  # no raise
        finally:
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------

class TestBudgetEnforcement(unittest.TestCase):
    def test_budget_exceeded_raises(self):
        call_counter = [_mod.MAX_FMP_CALLS]  # already at max
        with self.assertRaises(RuntimeError) as ctx:
            _mod.fetch_screener("fake_key", call_counter=call_counter)
        self.assertIn("budget exhausted", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
