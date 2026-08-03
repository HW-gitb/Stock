"""Offline regression coverage for the A-short derived financial cache contract."""

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
        spec = importlib.util.spec_from_file_location("egs_main_financial_cache_under_test", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


def _financial_frame(em, codes):
    rows = []
    for index, code in enumerate(codes, start=1):
        row = {}
        for column in em.FINANCIAL_CACHE_REQUIRED_COLUMNS:
            if column == "ts_code":
                row[column] = code
            elif column.endswith("_ann_date") or column.endswith("_end_date"):
                row[column] = "20260731"
            else:
                row[column] = float(index)
        rows.append(row)
    return pd.DataFrame(rows)


def _provider_frame(codes, period):
    return pd.DataFrame([
        {
            "ts_code": code,
            "ann_date": "20260731",
            "end_date": period,
            "dt_netprofit_yoy": float(index),
            "tr_yoy": float(index + 1),
            "ocf_to_profit": 1.0,
            "profit_dedt": float(index + 2),
            "dtprofit_to_profit": 0.9,
            "roe": 0.1,
        }
        for index, code in enumerate(codes, start=1)
    ])


class FinancialCacheContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.egs = _load_egs_module()

    def _identity(self, codes):
        em = self.egs
        quarters = tuple(em._latest_quarters(em.FINANCIAL_FETCH_QUARTERS))
        semantics = em._financial_semantics_fingerprint(quarters)
        return quarters, semantics

    def _observation(self, codes):
        em = self.egs
        quarters, semantics = self._identity(codes)
        return em._financial_observation(
            _financial_frame(em, codes), em.TODAY, list(codes), quarters, semantics,
        )

    def test_same_count_different_code_sets_have_different_keys(self):
        em = self.egs
        quarters, semantics = self._identity(["000001.SZ", "600000.SH"])
        left = em._financial_cache_key(
            em.TODAY, ["000001.SZ", "600000.SH"], quarters, semantics,
        )
        right = em._financial_cache_key(
            em.TODAY, ["000001.SZ", "600001.SH"], quarters, semantics,
        )
        self.assertNotEqual(left, right)
        self.assertIn("financial_v2", left)

    def test_code_order_does_not_change_identity(self):
        em = self.egs
        quarters, semantics = self._identity(["000001.SZ", "600000.SH"])
        left = em._financial_cache_key(
            em.TODAY, ["600000.SH", "000001.SZ"], quarters, semantics,
        )
        right = em._financial_cache_key(
            em.TODAY, ["000001.SZ", "600000.SH", "000001.SZ"], quarters, semantics,
        )
        self.assertEqual(left, right)

    def test_quarter_or_semantics_change_rotates_key(self):
        em = self.egs
        codes = ["000001.SZ", "600000.SH"]
        quarters, semantics = self._identity(codes)
        original = em._financial_cache_key(em.TODAY, codes, quarters, semantics)
        changed_quarters = tuple(list(quarters[:-1]) + ["20230331"])
        changed_window = em._financial_cache_key(em.TODAY, codes, changed_quarters, semantics)
        self.assertNotEqual(original, changed_window)
        with patch.object(em, "FINANCIAL_FETCH_QUARTERS", em.FINANCIAL_FETCH_QUARTERS + 1):
            changed_semantics = em._financial_cache_key(em.TODAY, codes, quarters)
        self.assertNotEqual(original, changed_semantics)

    def test_legacy_count_only_key_is_not_loaded(self):
        em = self.egs
        codes = ["000001.SZ", "600000.SH"]
        loaded_keys = []

        def load(key):
            loaded_keys.append(key)
            return None

        def fetch(_api, **kwargs):
            return _provider_frame(codes, kwargs["period"])

        with patch.object(em, "load_cache", side_effect=load), \
             patch.object(em, "safe_api", side_effect=fetch), \
             patch.object(em, "save_cache"):
            result = em.get_financial_data(codes)

        self.assertFalse(result.empty)
        self.assertEqual(len(loaded_keys), 1)
        self.assertIn("financial_v2", loaded_keys[0])
        self.assertNotEqual(loaded_keys[0], f"financial_{em.TODAY}_{len(codes)}")

    def test_exact_envelope_hit_does_not_refetch(self):
        em = self.egs
        codes = ["000001.SZ", "600000.SH"]
        cached = self._observation(codes)
        with patch.object(em, "load_cache", return_value=cached), \
             patch.object(em, "safe_api") as safe_api:
            result = em.get_financial_data(codes)
        safe_api.assert_not_called()
        pd.testing.assert_frame_equal(result, cached.frame)

    def test_same_count_foreign_cache_is_rejected_and_refetched(self):
        em = self.egs
        requested = ["000001.SZ", "600000.SH"]
        cached = self._observation(["000002.SZ", "600001.SH"])

        def fetch(_api, **kwargs):
            return _provider_frame(requested, kwargs["period"])

        with patch.object(em, "load_cache", return_value=cached), \
             patch.object(em, "safe_api", side_effect=fetch) as safe_api, \
             patch.object(em, "save_cache"):
            result = em.get_financial_data(requested)

        self.assertEqual(set(result["ts_code"]), set(requested))
        self.assertEqual(safe_api.call_count, len(em._latest_quarters(em.FINANCIAL_FETCH_QUARTERS)))

    def test_bare_dataframe_at_v2_key_is_rejected_and_refetched(self):
        em = self.egs
        codes = ["000001.SZ", "600000.SH"]

        def fetch(_api, **kwargs):
            return _provider_frame(codes, kwargs["period"])

        with patch.object(em, "load_cache", return_value=_financial_frame(em, codes)), \
             patch.object(em, "safe_api", side_effect=fetch) as safe_api, \
             patch.object(em, "save_cache"):
            result = em.get_financial_data(codes)

        self.assertEqual(set(result["ts_code"]), set(codes))
        self.assertEqual(safe_api.call_count, len(em._latest_quarters(em.FINANCIAL_FETCH_QUARTERS)))

    def test_metadata_tamper_is_rejected_and_old_frame_is_not_returned(self):
        em = self.egs
        codes = ["000001.SZ", "600000.SH"]
        cached = self._observation(codes)
        tampered = dataclasses.replace(cached, semantics_sha256="tampered")

        with patch.object(em, "load_cache", return_value=tampered), \
             patch.object(em, "safe_api", return_value=None) as safe_api, \
             patch.object(em, "save_cache"):
            result = em.get_financial_data(codes)

        self.assertTrue(result.empty)
        self.assertEqual(safe_api.call_count, len(em._latest_quarters(em.FINANCIAL_FETCH_QUARTERS)))

    def test_invalid_provider_result_is_not_cached_as_a_valid_observation(self):
        em = self.egs
        codes = ["000001.SZ"]
        bad = _financial_frame(em, ["999999.SZ"])
        with self.assertRaisesRegex(RuntimeError, "outside the requested universe"):
            em._financial_observation(
                bad, em.TODAY, codes,
                em._latest_quarters(em.FINANCIAL_FETCH_QUARTERS),
                em._financial_semantics_fingerprint(em._latest_quarters(em.FINANCIAL_FETCH_QUARTERS)),
            )


if __name__ == "__main__":
    unittest.main()
