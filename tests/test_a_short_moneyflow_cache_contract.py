"""Offline regression coverage for the A-short moneyflow source contract."""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_main_moneyflow_cache_under_test", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


def _provider_frame(em, codes, date):
    rows = []
    for index, code in enumerate(codes, start=1):
        rows.append({
            "ts_code": code,
            "trade_date": date,
            "buy_elg_amount": 100.0 * index,
            "sell_elg_amount": 1.0,
            "buy_lg_amount": 100.0 * index,
            "sell_lg_amount": 1.0,
            "buy_md_amount": 5.0,
            "sell_md_amount": 5.0,
            "buy_sm_amount": 5.0,
            "sell_sm_amount": 5.0,
            "net_mf_amount": 188.0 * index,
        })
    return pd.DataFrame(rows, columns=list(em.MONEYFLOW_PROVIDER_FIELDS))


class MoneyflowCacheContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.egs = _load_egs_module()
        cls.dates = ("20260731", "20260730", "20260729", "20260728", "20260727")
        cls.codes = ("000001.SZ", "600000.SH")

    def _observation(self, codes=None, dates=None):
        em = self.egs
        codes = tuple(codes or self.codes)
        dates = tuple(dates or self.dates)
        frame = pd.concat(
            [_provider_frame(em, codes, date) for date in dates],
            ignore_index=True,
        )
        return em._moneyflow_observation(
            frame, dates, em._moneyflow_semantics_fingerprint()
        )

    def test_cache_key_is_versioned_and_window_bound(self):
        em = self.egs
        left = em._moneyflow_cache_key(self.dates)
        right = em._moneyflow_cache_key(
            (self.dates[0], "20260726", "20260725", "20260724", "20260723")
        )
        self.assertIn("moneyflow_v2", left)
        self.assertNotEqual(left, right)

    def test_semantics_change_rotates_fingerprint(self):
        em = self.egs
        original = em._moneyflow_semantics_fingerprint()
        with patch.object(em, "MONEYFLOW_FETCH_SESSIONS", 6):
            changed = em._moneyflow_semantics_fingerprint()
        self.assertNotEqual(original, changed)

    def test_legacy_key_is_not_loaded(self):
        em = self.egs
        loaded_keys = []

        def load(key):
            loaded_keys.append(key)
            return None

        with patch.object(em, "load_cache", side_effect=load), \
             patch.object(em, "safe_api", return_value=None), \
             patch.object(em, "save_cache"):
            result = em.get_moneyflow(self.dates)

        self.assertEqual(len(loaded_keys), 1)
        self.assertIn("moneyflow_v2", loaded_keys[0])
        self.assertNotEqual(loaded_keys[0], f"moneyflow_{self.dates[0]}")
        self.assertEqual(result.status, "unavailable")

    def test_exact_envelope_hit_does_not_refetch(self):
        em = self.egs
        cached = self._observation()
        with patch.object(em, "load_cache", return_value=cached), \
             patch.object(em, "safe_api") as safe_api:
            result = em.get_moneyflow(self.dates)
        safe_api.assert_not_called()
        self.assertIsInstance(result, em.MoneyflowObservation)
        self.assertIsNot(result.frame, cached.frame)
        pd.testing.assert_frame_equal(result.frame, cached.frame)

    def test_bare_dataframe_at_v2_key_is_rejected_and_refetched(self):
        em = self.egs

        def fetch(_api, **kwargs):
            return _provider_frame(em, self.codes, kwargs["trade_date"])

        with patch.object(em, "load_cache", return_value=_provider_frame(em, self.codes, self.dates[0])), \
             patch.object(em, "safe_api", side_effect=fetch) as safe_api, \
             patch.object(em, "save_cache"):
            result = em.get_moneyflow(self.dates)

        self.assertEqual(result.status, "complete")
        self.assertEqual(safe_api.call_count, len(self.dates))

    def test_metadata_tamper_is_rejected_and_old_frame_is_not_returned(self):
        em = self.egs
        cached = self._observation()
        tampered = dataclasses.replace(cached, semantics_sha256="tampered")
        with patch.object(em, "load_cache", return_value=tampered), \
             patch.object(em, "safe_api", return_value=None) as safe_api, \
             patch.object(em, "save_cache"):
            result = em.get_moneyflow(self.dates)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(safe_api.call_count, len(self.dates))

    def test_partial_window_is_not_cached_and_usage_is_incomplete(self):
        em = self.egs
        values = [_provider_frame(em, self.codes, date) for date in self.dates]
        values[2] = None
        with patch.object(em, "load_cache", return_value=None), \
             patch.object(em, "safe_api", side_effect=values), \
             patch.object(em, "save_cache") as save_cache:
            result = em.get_moneyflow(self.dates)
        self.assertEqual(result.status, "incomplete")
        self.assertFalse(result.coverage_complete)
        save_cache.assert_not_called()
        receipt = em._moneyflow_usage_receipt(result, list(self.codes))
        self.assertEqual(receipt["status"], "incomplete")
        self.assertFalse(receipt["coverage_complete"])

    def test_all_failed_window_is_unavailable_and_not_cached(self):
        em = self.egs
        with patch.object(em, "load_cache", return_value=None), \
             patch.object(em, "safe_api", return_value=None), \
             patch.object(em, "save_cache") as save_cache:
            result = em.get_moneyflow(self.dates)
        self.assertEqual(result.status, "unavailable")
        save_cache.assert_not_called()

    def test_malformed_provider_frame_fails_closed_before_cache_write(self):
        em = self.egs
        malformed = _provider_frame(em, self.codes, self.dates[0]).drop(columns=["net_mf_amount"])
        with patch.object(em, "load_cache", return_value=None), \
             patch.object(em, "safe_api", return_value=malformed), \
             patch.object(em, "save_cache") as save_cache:
            with self.assertRaisesRegex(RuntimeError, "provider payload is invalid"):
                em.get_moneyflow(self.dates)
        save_cache.assert_not_called()

    def test_complete_target_receipt_enables_moneyflow_bonus(self):
        em = self.egs
        observation = self._observation(codes=(self.codes[0],))
        frame = pd.DataFrame({
            "ts_code": [self.codes[0]],
            "l2_name": ["industry"],
            "pct_20d_n": [10.0],
            "pct_5d": [2.0],
        })
        before = em.score_l4(frame, observation, em._moneyflow_usage_receipt(observation, list(frame["ts_code"])))
        self.assertGreater(before.loc[0, "big_ratio"], 0.15)
        self.assertEqual(float(before.loc[0, "l4_score"]), 55.0)

    def test_missing_target_session_disables_bonus(self):
        em = self.egs
        observation = self._observation(codes=(self.codes[0],))
        frame = pd.DataFrame({
            "ts_code": [self.codes[0], self.codes[1]],
            "l2_name": ["industry", "industry"],
            "pct_20d_n": [10.0, 9.0],
            "pct_5d": [2.0, 2.0],
        })
        coverage = em._moneyflow_usage_receipt(observation, list(frame["ts_code"]))
        self.assertEqual(coverage["target_complete_count"], 1)
        self.assertEqual(coverage["target_universe_size"], 2)
        self.assertEqual(coverage["status"], "incomplete")
        result = em.score_l4(frame, observation, coverage)
        self.assertTrue(result["big_ratio"].isna().all())

    def test_invalid_observation_never_enables_bonus(self):
        em = self.egs
        frame = pd.DataFrame({
            "ts_code": [self.codes[0]],
            "l2_name": ["industry"],
            "pct_20d_n": [10.0],
            "pct_5d": [2.0],
        })
        result = em.score_l4(frame, pd.DataFrame())
        self.assertTrue(result["big_ratio"].isna().all())


if __name__ == "__main__":
    unittest.main()
