"""Offline regression coverage for the A-short derived financial cache contract."""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
import unittest
from datetime import datetime
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


def _provider_frame_with_profit(codes, period, profit_by_period):
    frame = _provider_frame(codes, period)
    frame["profit_dedt"] = [profit_by_period.get(period) for _ in codes]
    return frame


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

    def test_financial_fetch_window_is_exactly_five_and_provider_calls_match(self):
        em = self.egs
        codes = ["000001.SZ"]
        as_of = "20260817"
        as_of_dt = datetime(2026, 8, 17)
        with patch.multiple(em, TODAY=as_of, TODAY_DT=as_of_dt):
            quarters = em._latest_quarters(em.FINANCIAL_FETCH_QUARTERS)
            self.assertEqual(em.FINANCIAL_FETCH_QUARTERS, 5)
            self.assertEqual(len(quarters), 5)
            calls = []

            def fetch(_api, **kwargs):
                calls.append(kwargs["period"])
                return _provider_frame_with_profit(codes, kwargs["period"], {
                    period: 10.0 for period in quarters
                })

            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "safe_api", side_effect=fetch), \
                 patch.object(em, "save_cache"):
                result = em.get_financial_data(codes)

        self.assertFalse(result.empty)
        self.assertEqual(calls, quarters)

    def test_all_future_announcements_return_empty_without_q0_merge_crash(self):
        em = self.egs
        codes = ["000001.SZ"]
        as_of = "20260817"
        as_of_dt = datetime(2026, 8, 17)

        def fetch(_api, **kwargs):
            frame = _provider_frame(codes, kwargs["period"])
            frame["ann_date"] = "20990101"
            return frame

        with patch.multiple(em, TODAY=as_of, TODAY_DT=as_of_dt), \
             patch.object(em, "load_cache", return_value=None), \
             patch.object(em, "safe_api", side_effect=fetch), \
             patch.object(em, "save_cache"):
            result = em.get_financial_data(codes)

        self.assertTrue(result.empty)

    def test_ttm_profit_dedt_uses_non_overlapping_ytd_formula(self):
        em = self.egs
        codes = ["000001.SZ"]
        as_of = "20260817"
        as_of_dt = datetime(2026, 8, 17)
        with patch.multiple(em, TODAY=as_of, TODAY_DT=as_of_dt):
            quarters = em._latest_quarters(5)
            q0 = quarters[0]
            prior_year = str(int(q0[:4]) - 1)
            annual = f"{prior_year}1231"
            prior_same_period = f"{prior_year}{q0[4:]}"
            profit_by_period = {
                period: 10.0 for period in quarters
            }
            profit_by_period.update({q0: 70.0, annual: 100.0, prior_same_period: 40.0})

            def fetch(_api, **kwargs):
                return _provider_frame_with_profit(codes, kwargs["period"], profit_by_period)

            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "safe_api", side_effect=fetch), \
                 patch.object(em, "save_cache"):
                result = em.get_financial_data(codes)

        self.assertAlmostEqual(float(result.iloc[0]["ttm_profit_dedt"]), 130.0)
        self.assertNotEqual(float(result.iloc[0]["ttm_profit_dedt"]), 190.0)

    def test_annual_q0_ttm_equals_the_annual_cumulative_value(self):
        em = self.egs
        codes = ["000001.SZ"]
        as_of = "20270101"
        as_of_dt = datetime(2027, 1, 1)
        with patch.multiple(em, TODAY=as_of, TODAY_DT=as_of_dt):
            quarters = em._latest_quarters(5)
            self.assertTrue(quarters[0].endswith("1231"))
            q0 = quarters[0]
            profit_by_period = {period: 10.0 for period in quarters}
            profit_by_period[q0] = 77.0

            def fetch(_api, **kwargs):
                return _provider_frame_with_profit(codes, kwargs["period"], profit_by_period)

            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "safe_api", side_effect=fetch), \
                 patch.object(em, "save_cache"):
                result = em.get_financial_data(codes)

        self.assertAlmostEqual(float(result.iloc[0]["ttm_profit_dedt"]), 77.0)

    def test_missing_ttm_component_is_nan_without_four_quarter_fallback(self):
        em = self.egs
        codes = ["000001.SZ"]
        as_of = "20260817"
        as_of_dt = datetime(2026, 8, 17)
        for missing_component in ("q0", "annual", "prior_same_period"):
            with self.subTest(missing_component=missing_component), \
                 patch.multiple(em, TODAY=as_of, TODAY_DT=as_of_dt):
                quarters = em._latest_quarters(5)
                q0 = quarters[0]
                prior_year = str(int(q0[:4]) - 1)
                annual = f"{prior_year}1231"
                prior_same_period = f"{prior_year}{q0[4:]}"
                profit_by_period = {period: 10.0 for period in quarters}
                profit_by_period.update({q0: 70.0, annual: 100.0, prior_same_period: 40.0})
                profit_by_period[{"q0": q0, "annual": annual,
                                 "prior_same_period": prior_same_period}[missing_component]] = None

                def fetch(_api, **kwargs):
                    return _provider_frame_with_profit(codes, kwargs["period"], profit_by_period)

                with patch.object(em, "load_cache", return_value=None), \
                     patch.object(em, "safe_api", side_effect=fetch), \
                     patch.object(em, "save_cache"):
                    result = em.get_financial_data(codes)

                self.assertTrue(pd.isna(result.iloc[0]["ttm_profit_dedt"]))

    def test_non_numeric_or_non_finite_ttm_component_is_nan(self):
        em = self.egs
        codes = ["000001.SZ"]
        as_of = "20260817"
        as_of_dt = datetime(2026, 8, 17)
        for invalid_value in ("not-a-number", float("inf"), float("-inf")):
            with self.subTest(invalid_value=invalid_value), \
                 patch.multiple(em, TODAY=as_of, TODAY_DT=as_of_dt):
                quarters = em._latest_quarters(5)
                q0 = quarters[0]
                prior_year = str(int(q0[:4]) - 1)
                annual = f"{prior_year}1231"
                prior_same_period = f"{prior_year}{q0[4:]}"
                profit_by_period = {period: 10.0 for period in quarters}
                profit_by_period.update({q0: 70.0, annual: 100.0, prior_same_period: 40.0})
                profit_by_period[q0] = invalid_value

                def fetch(_api, **kwargs):
                    return _provider_frame_with_profit(codes, kwargs["period"], profit_by_period)

                with patch.object(em, "load_cache", return_value=None), \
                     patch.object(em, "safe_api", side_effect=fetch), \
                     patch.object(em, "save_cache"):
                    result = em.get_financial_data(codes)

                self.assertTrue(pd.isna(result.iloc[0]["ttm_profit_dedt"]))

    def test_pit_uses_latest_announced_row_and_rejects_future_announcement(self):
        em = self.egs
        codes = ["000001.SZ"]
        as_of = "20260817"
        as_of_dt = datetime(2026, 8, 17)
        with patch.multiple(em, TODAY=as_of, TODAY_DT=as_of_dt):
            quarters = em._latest_quarters(5)
            q0 = quarters[0]
            prior_year = str(int(q0[:4]) - 1)
            annual = f"{prior_year}1231"
            prior_same_period = f"{prior_year}{q0[4:]}"
            profit_by_period = {period: 10.0 for period in quarters}
            profit_by_period.update({q0: 60.0, annual: 100.0, prior_same_period: 40.0})

            def fetch(_api, **kwargs):
                period = kwargs["period"]
                frame = _provider_frame_with_profit(codes, period, profit_by_period)
                if period != q0:
                    frame["ann_date"] = "20260801"
                    return frame
                older = frame.copy()
                older["ann_date"] = "20260101"
                older["profit_dedt"] = 60.0
                latest = frame.copy()
                latest["ann_date"] = "20260801"
                latest["profit_dedt"] = 70.0
                future = frame.copy()
                future["ann_date"] = "20260901"
                future["profit_dedt"] = 999.0
                return pd.concat([older, latest, future], ignore_index=True)

            with patch.object(em, "load_cache", return_value=None), \
                 patch.object(em, "safe_api", side_effect=fetch), \
                 patch.object(em, "save_cache"):
                result = em.get_financial_data(codes)

        self.assertAlmostEqual(float(result.iloc[0]["ttm_profit_dedt"]), 130.0)

    def test_latest_quarters_five_covers_ttm_components_across_four_phases(self):
        em = self.egs
        phases = (
            ("20260501", datetime(2026, 5, 1)),
            ("20260901", datetime(2026, 9, 1)),
            ("20261101", datetime(2026, 11, 1)),
            ("20270101", datetime(2027, 1, 1)),
        )
        for as_of, as_of_dt in phases:
            with self.subTest(as_of=as_of), patch.multiple(em, TODAY=as_of, TODAY_DT=as_of_dt):
                quarters = em._latest_quarters(5)
                self.assertEqual(len(quarters), 5)
                self.assertEqual(len(set(quarters)), 5)
                q0 = quarters[0]
                if q0.endswith("1231"):
                    self.assertIn(q0, quarters)
                else:
                    prior_year = str(int(q0[:4]) - 1)
                    self.assertIn(f"{prior_year}1231", quarters)
                    self.assertIn(f"{prior_year}{q0[4:]}", quarters)


if __name__ == "__main__":
    unittest.main()
