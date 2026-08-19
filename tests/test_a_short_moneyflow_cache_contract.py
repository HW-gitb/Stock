"""Offline regression coverage for the A-short moneyflow source contract."""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock
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

    def test_missing_target_session_keeps_complete_rows_and_records_missing_code(self):
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
        self.assertEqual(coverage["missing_target_codes"], [self.codes[1]])
        self.assertEqual(coverage["status"], "incomplete")
        result = em.score_l4(frame, observation, coverage)
        by_code = result.set_index("ts_code")
        self.assertGreater(float(by_code.loc[self.codes[0], "big_ratio"]), 0.15)
        self.assertTrue(pd.isna(by_code.loc[self.codes[1], "big_ratio"]))
        self.assertEqual(float(by_code.loc[self.codes[0], "l4_score"]), 55.0)
        self.assertEqual(float(by_code.loc[self.codes[1], "l4_score"]), 0.0)

    def test_three_missing_targets_score_complete_rows_but_four_skip_all(self):
        em = self.egs
        complete_code = self.codes[0]
        for missing_codes in (
            ("000002.SZ", "000003.SZ", "000004.SZ"),
            ("000002.SZ", "000003.SZ", "000004.SZ", "000005.SZ"),
        ):
            with self.subTest(missing_count=len(missing_codes)):
                target_codes = (complete_code,) + missing_codes
                observation = self._observation(codes=(complete_code,))
                frame = pd.DataFrame({
                    "ts_code": list(target_codes),
                    "l2_name": ["industry"] * len(target_codes),
                    "pct_20d_n": [10.0] + [9.0] * len(missing_codes),
                    "pct_5d": [2.0] * len(target_codes),
                })
                coverage = em._moneyflow_usage_receipt(observation, target_codes)
                self.assertEqual(
                    coverage["missing_target_codes"], sorted(missing_codes)
                )
                result = em.score_l4(frame, observation, coverage).set_index("ts_code")
                if len(missing_codes) == 3:
                    self.assertGreater(float(result.loc[complete_code, "big_ratio"]), 0.15)
                    self.assertEqual(float(result.loc[complete_code, "l4_score"]), 55.0)
                    self.assertTrue(result.loc[list(missing_codes), "big_ratio"].isna().all())
                else:
                    self.assertTrue(result["big_ratio"].isna().all())

    def test_incomplete_or_invalid_observation_never_enables_partial_target_bonus(self):
        em = self.egs
        frame = pd.DataFrame({
            "ts_code": [self.codes[0], self.codes[1]],
            "l2_name": ["industry", "industry"],
            "pct_20d_n": [10.0, 9.0],
            "pct_5d": [2.0, 2.0],
        })
        for status in ("incomplete", "invalid"):
            with self.subTest(status=status):
                observation = dataclasses.replace(
                    self._observation(codes=(self.codes[0],)),
                    status=status,
                    coverage_complete=False,
                )
                coverage = em._moneyflow_usage_receipt(
                    observation, list(frame["ts_code"])
                )
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


class MoneyflowDualClockTests(unittest.TestCase):
    """D0 may slip one session when it is simply not published -- never silently.

    The window used to be hard-anchored on D0 with no tolerance and no fallback,
    so a routine post-holiday publication delay killed the whole large-order
    factor (measured once: `target_complete_count=0/994`, `big_ratio` all NaN)
    while the artifact still published as complete.
    """

    @classmethod
    def setUpClass(cls):
        cls.egs = _load_egs_module()
        # Six sessions, newest first: D0..D5.  A one-session fallback consumes D5.
        cls.sessions = ("20260731", "20260730", "20260729", "20260728", "20260727", "20260724")
        cls.codes = ("000001.SZ", "600000.SH")

    def _frames(self, dates):
        return pd.concat([_provider_frame(self.egs, self.codes, date) for date in dates],
                         ignore_index=True)

    def _run(self, published):
        """Drive `get_moneyflow` with a provider that only knows `published`."""
        em = self.egs
        calls = []

        def fake_api(_fn, trade_date=None, **_kw):
            calls.append(trade_date)
            if trade_date not in published:
                return pd.DataFrame(columns=list(em.MONEYFLOW_PROVIDER_FIELDS))
            return _provider_frame(em, self.codes, trade_date)

        with mock.patch.object(em, "safe_api", side_effect=fake_api), \
                mock.patch.object(em, "load_cache", return_value=None), \
                mock.patch.object(em, "save_cache"), \
                mock.patch.object(em, "pro", mock.Mock()):
            return em.get_moneyflow(self.sessions), calls

    def test_a_complete_d0_window_does_not_reach_for_a_sixth_session(self):
        observation, calls = self._run(set(self.sessions[:5]))
        self.assertEqual(observation.status, "complete")
        self.assertEqual(observation.lag_sessions, 0)
        self.assertFalse(observation.fallback_applied)
        self.assertIsNone(observation.fallback_reason)
        self.assertEqual(observation.effective_ref_date, self.sessions[0])
        self.assertNotIn(self.sessions[5], calls, "D5 must not be fetched when D0 is complete")

    def test_an_unpublished_d0_slips_one_session_and_says_so(self):
        observation, calls = self._run(set(self.sessions[1:]))
        self.assertEqual(observation.status, "complete", "a complete D1 window still scores")
        self.assertEqual(observation.reference_date, self.sessions[0], "D0 must stay visible")
        self.assertEqual(observation.effective_ref_date, self.sessions[1])
        self.assertEqual(observation.lag_sessions, 1)
        self.assertTrue(observation.fallback_applied)
        self.assertEqual(observation.fallback_reason, "d0_not_published")
        self.assertEqual(tuple(observation.requested_trade_dates), self.sessions[1:6])
        self.assertLessEqual(len(calls), 6, "the whole rebuild must stay inside the 6-call ceiling")

    def test_a_partial_window_does_not_go_looking_for_a_cleaner_day(self):
        """D0 present, a middle session missing -> incomplete, no fallback."""
        observation, calls = self._run(set(self.sessions[:5]) - {self.sessions[2]})
        self.assertEqual(observation.status, "incomplete")
        self.assertFalse(observation.fallback_applied)
        self.assertEqual(observation.lag_sessions, 0)
        self.assertNotIn(self.sessions[5], calls)

    def test_a_malformed_d0_is_not_laundered_by_falling_back(self):
        em = self.egs
        bad = _provider_frame(em, self.codes, self.sessions[0]).assign(net_mf_amount="not-a-number")

        def fake_api(_fn, trade_date=None, **_kw):
            if trade_date == self.sessions[0]:
                return bad
            return _provider_frame(em, self.codes, trade_date)

        with mock.patch.object(em, "safe_api", side_effect=fake_api), \
                mock.patch.object(em, "load_cache", return_value=None), \
                mock.patch.object(em, "save_cache"), \
                mock.patch.object(em, "pro", mock.Mock()):
            with self.assertRaises(RuntimeError):
                em.get_moneyflow(self.sessions)

    def test_d0_empty_and_the_fallback_window_still_short_scores_nothing(self):
        observation, _calls = self._run(set(self.sessions[1:5]))     # D5 also missing
        self.assertEqual(observation.status, "unavailable")
        self.assertFalse(observation.coverage_complete)
        self.assertIsNone(observation.lag_sessions)
        self.assertIsNone(observation.effective_ref_date)

    def test_only_d2_available_is_beyond_tolerance_and_stays_unavailable(self):
        observation, _calls = self._run({self.sessions[2]})
        self.assertIn(observation.status, {"incomplete", "unavailable"})
        self.assertFalse(observation.coverage_complete)
        self.assertFalse(observation.fallback_applied)

    def test_the_d0_and_d1_windows_can_never_read_each_other_s_cache(self):
        em = self.egs
        d0_key = em._moneyflow_cache_key(self.sessions[:5], "fp")
        d1_key = em._moneyflow_cache_key(self.sessions[1:6], "fp")
        self.assertNotEqual(d0_key, d1_key)
        self.assertIn(f"lag{em.MONEYFLOW_MAX_LAG_SESSIONS}", d0_key,
                      "widening the tolerance must rotate keys, not reinterpret old hits")

    def test_a_fallback_window_must_carry_a_reason_and_move_backwards(self):
        em = self.egs
        frame = self._frames(self.sessions[1:6])
        with self.assertRaises(ValueError):        # moved window, no reason
            em._moneyflow_observation(frame, self.sessions[1:6], "fp",
                                      reference_date=self.sessions[0])
        with self.assertRaises(ValueError):        # "fallback" that moves forward
            em._moneyflow_observation(self._frames(self.sessions[:5]), self.sessions[:5], "fp",
                                      reference_date=self.sessions[1], fallback_reason="nope")

    def test_the_usage_receipt_carries_both_clocks_to_the_artifact(self):
        em = self.egs
        observation = em._moneyflow_observation(
            self._frames(self.sessions[1:6]), self.sessions[1:6], "fp",
            reference_date=self.sessions[0], fallback_reason="d0_not_published")
        coverage = em._moneyflow_usage_receipt(observation, self.codes)
        self.assertEqual(coverage["status"], "complete")
        self.assertEqual(coverage["reference_date"], self.sessions[0])
        self.assertEqual(coverage["effective_ref_date"], self.sessions[1])
        self.assertEqual(coverage["lag_sessions"], 1)
        self.assertTrue(coverage["fallback_applied"])
        self.assertEqual(coverage["fallback_reason"], "d0_not_published")

    def test_a_cache_hit_carries_the_dual_clock_instead_of_defaulting_it(self):
        """Closure 1: a cached fallback must come back with its clock intact.

        The hit path used to rebuild the observation from a hand-listed set of
        keyword arguments, so the four dual-clock fields fell back to their
        dataclass defaults: `status=complete` with `effective_ref_date=null` --
        an analysis_input that fails its own schema, and a fallback that
        vanishes.
        """
        em = self.egs
        shifted = self.sessions[1:6]
        cached = em._moneyflow_observation(
            self._frames(shifted), shifted, em._moneyflow_semantics_fingerprint(),
            reference_date=self.sessions[0], fallback_reason="d0_not_published")
        with mock.patch.object(em, "load_cache", return_value=cached), \
                mock.patch.object(em, "safe_api") as safe_api, \
                mock.patch.object(em, "save_cache"), \
                mock.patch.object(em, "pro", mock.Mock()):
            hit = em.get_moneyflow(shifted)
        safe_api.assert_not_called()
        for field in ("effective_ref_date", "lag_sessions", "fallback_applied",
                      "fallback_reason", "reference_date"):
            self.assertEqual(getattr(hit, field), getattr(cached, field), field)

    def test_a_cache_hit_still_satisfies_the_analysis_input_schema(self):
        """Closure 2: the complete-status payload a hit produces must validate."""
        import json as _json
        import jsonschema

        em = self.egs
        schema = _json.loads((ROOT / "schemas" / "analysis_input.schema.json")
                             .read_text(encoding="utf-8"))
        # carry the root's $defs so the node's internal $refs still resolve
        node = dict(schema["properties"]["market_context"]["properties"]["moneyflow_coverage"],
                    **{"$defs": schema["$defs"]})
        window = self.sessions[:5]
        cached = em._moneyflow_observation(
            self._frames(window), window, em._moneyflow_semantics_fingerprint())
        with mock.patch.object(em, "load_cache", return_value=cached), \
                mock.patch.object(em, "safe_api"), \
                mock.patch.object(em, "save_cache"), \
                mock.patch.object(em, "pro", mock.Mock()):
            hit = em.get_moneyflow(window)
        coverage = em._moneyflow_usage_receipt(hit, self.codes)
        self.assertEqual(coverage["status"], "complete")
        jsonschema.validate(coverage, node)

    def test_a_pre_dual_clock_cache_entry_is_refetched_not_trusted(self):
        """Closure 4: an old entry unpickles with defaults; that is not an observation."""
        import dataclasses as _dc
        em = self.egs
        window = self.sessions[:5]
        stale = _dc.replace(
            em._moneyflow_observation(self._frames(window), window,
                                      em._moneyflow_semantics_fingerprint()),
            effective_ref_date=None, lag_sessions=None)
        valid, reason = em._validate_moneyflow_observation(
            stale, window, em._moneyflow_semantics_fingerprint())
        self.assertFalse(valid)
        self.assertIn("dual clock", reason)

    def test_a_provider_error_on_d0_is_not_called_not_published(self):
        """A failed call is not evidence of anything; it may not move the window."""
        em = self.egs
        calls = []

        def fake_api(_fn, trade_date=None, errors=None, **_kw):
            calls.append(trade_date)
            if trade_date == self.sessions[0]:
                if errors is not None:
                    errors.append(RuntimeError("provider did not answer"))
                return None
            return _provider_frame(em, self.codes, trade_date)

        with mock.patch.object(em, "safe_api", side_effect=fake_api), \
                mock.patch.object(em, "load_cache", return_value=None), \
                mock.patch.object(em, "save_cache"), \
                mock.patch.object(em, "pro", mock.Mock()):
            observation = em.get_moneyflow(self.sessions)
        self.assertFalse(observation.fallback_applied,
                         "a provider outage must not be relabelled d0_not_published")
        self.assertEqual(observation.status, "incomplete")
        self.assertNotIn(self.sessions[5], calls, "no window rebuild on a failed call")

    def test_a_calendar_too_short_to_rebuild_degrades_instead_of_raising(self):
        """The short-calendar branch was unreachable: the helper raised first."""
        em = self.egs
        five = self.sessions[:5]                      # no sixth session to shift into
        observation, _calls = None, None
        published = set(five[1:])

        def fake_api(_fn, trade_date=None, errors=None, **_kw):
            if trade_date not in published:
                return pd.DataFrame(columns=list(em.MONEYFLOW_PROVIDER_FIELDS))
            return _provider_frame(em, self.codes, trade_date)

        with mock.patch.object(em, "safe_api", side_effect=fake_api), \
                mock.patch.object(em, "load_cache", return_value=None), \
                mock.patch.object(em, "save_cache"), \
                mock.patch.object(em, "pro", mock.Mock()):
            observation = em.get_moneyflow(five)      # must not raise
        self.assertEqual(observation.status, "unavailable")
        self.assertIsNone(observation.lag_sessions)

    def _health(self, coverage):
        em = self.egs
        ranked = pd.DataFrame({"ts_code": [self.codes[0]], "l2_name": ["industry"],
                               "pct_20d_n": [10.0], "pct_5d": [2.0]})
        analysis_input = {
            "schema_name": "analysis_input",
            "schema_version": em.ANALYSIS_INPUT_SCHEMA_VERSION,
            "price_data_through": coverage["reference_date"],
            "source": {"screening_engine_version": em.EGS_VERSION, "data_provider": "tushare"},
            "market_context": {"moneyflow_coverage": coverage},
            "candidates": [{"data_quality": {"completeness_score": 100}}],
        }
        return em.build_data_health(
            df_full=ranked, watch_df=ranked, tier1_final=ranked,
            analysis_input=analysis_input, latest_td=coverage["reference_date"],
            analysis_path=str(EGS_SCRIPT), snapshot_path=str(EGS_SCRIPT),
            candidates_path=str(EGS_SCRIPT), tier1_csv_path=str(EGS_SCRIPT),
            full_csv_path=str(EGS_SCRIPT), moneyflow_coverage=coverage,
        )

    def _codes_of(self, health):
        return {str(row.get("check") or row.get("code") or "")
                for row in (health.get("errors") or [])}

    def test_a_lie_about_the_effective_clock_blocks_the_official_publish(self):
        """The override's mutation evidence, executed rather than asserted in prose.

        `effective_ref_date` / `lag_sessions` / `fallback_applied` /
        `fallback_reason` are registered as reaching a live terminal, so each has
        to be able to turn `data_health` into an error -- which
        `publish_official_egs` refuses on.
        """
        em = self.egs
        honest = em._moneyflow_usage_receipt(
            em._moneyflow_observation(self._frames(self.sessions[1:6]), self.sessions[1:6], "fp",
                                      reference_date=self.sessions[0],
                                      fallback_reason="d0_not_published"),
            self.codes)
        self.assertNotIn("moneyflow_effective_clock", self._codes_of(self._health(honest)))
        for field, value in (("lag_sessions", 0), ("fallback_reason", None),
                             ("fallback_applied", False),
                             ("effective_ref_date", self.sessions[0])):
            with self.subTest(field):
                lying = dict(honest, **{field: value})
                self.assertIn("moneyflow_effective_clock", self._codes_of(self._health(lying)),
                              f"tampering with {field} must be caught")

    def test_an_unusable_window_reports_no_clock_rather_than_a_confident_zero(self):
        coverage = self.egs._default_moneyflow_coverage("20260731", self.sessions[:5])
        self.assertEqual(coverage["missing_target_codes"], [])
        self.assertIsNone(coverage["effective_ref_date"])
        self.assertIsNone(coverage["lag_sessions"])
        self.assertFalse(coverage["fallback_applied"])
        self.assertIsNone(coverage["fallback_reason"])


if __name__ == "__main__":
    unittest.main()
