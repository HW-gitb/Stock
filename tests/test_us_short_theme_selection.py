# -*- coding: utf-8 -*-
"""Reverse controls for the §4.5 provisional theme gate keying.

The stricter provisional bar (market confirmation + individual gate) must fire on EITHER a
`provisional_discovered` source OR a `provisional_active` lifecycle — a source can label a theme
`industry_heat_v1` yet assert `provisional_active`, and that unconfirmed provisional-active name must not
take a theme seat / leader upgrade on the source label alone. Using OR (not replacing the source key) keeps
the existing bar for a discovered theme in any non-active lifecycle, so nothing is loosened.
"""
import unittest

from engine.us_short_theme_selection import (ThemeSelectionError, validate_theme_selection_contract,
                                             strong_theme_leader_upgrades, theme_seat_plan)


def _meta(*, source="industry_heat_v1", lifecycle="confirmed_active", market_confirmed=True,
          theme_id="t", leader_rs=1.0, origin="automatic_discovery", overextension="none"):
    return {
        "theme_id": theme_id, "theme_source": source, "theme_lifecycle_state": lifecycle,
        "theme_leader_rs": leader_rs, "membership_origin": origin, "market_confirmed": market_confirmed,
        "individual_theme_gate_passed": True, "overextension_state": overextension,
    }


def _ranked(metadata):
    scores = {t: {"theme_momentum_score": 80.0, "core_score": 70.0} for t in metadata}
    return set(theme_seat_plan(metadata_by_ticker=metadata, scores_by_ticker=scores, theme_seat_budget=5)["ranked"])


class ThemeSelectionProvisionalGateTest(unittest.TestCase):
    def test_contract_allows_only_hot_excluded_audit_optional_key(self):
        row = _meta()
        row["macro_cluster"] = "test_cluster"
        contract = {"as_of": "20260615", "mode": "industry_heat_v1_cross_industry_disabled",
                    "cross_industry_provisional_enabled": False, "theme_opportunity_state": "no_strong_theme",
                    "per_ticker": {"X": row}}
        validated = validate_theme_selection_contract(contract, expected_tickers=["X"], decision_date="20260615",
                                                      theme_opportunity_state="no_strong_theme")
        self.assertIn("X", validated["per_ticker"])
        with_audit = validate_theme_selection_contract(
            {**contract, "hot_excluded_audit": {"heat_threshold": 1.0, "per_ticker": {"X": 1.0}}},
            expected_tickers=["X"], decision_date="20260615", theme_opportunity_state="no_strong_theme")
        self.assertEqual(with_audit["hot_excluded_audit"]["per_ticker"], {"X": 1.0})
        with self.assertRaises(ThemeSelectionError):
            validate_theme_selection_contract({**contract, "rogue": True}, expected_tickers=["X"],
                                              decision_date="20260615", theme_opportunity_state="no_strong_theme")

    def test_provisional_active_industry_heat_row_needs_market_confirmation(self):
        # gap fixed: an industry_heat_v1 source can still assert provisional_active; unconfirmed → no theme seat.
        self.assertNotIn("X", _ranked({"X": _meta(source="industry_heat_v1", lifecycle="provisional_active",
                                                   market_confirmed=False)}))

    def test_confirmed_provisional_active_takes_a_seat(self):
        # positive control: a provisional_active name that IS market-confirmed + gated still qualifies.
        self.assertIn("X", _ranked({"X": _meta(source="industry_heat_v1", lifecycle="provisional_active",
                                                market_confirmed=True)}))

    def test_discovered_non_active_lifecycle_stays_excluded_not_loosened(self):
        # no-loosen: a provisional_discovered theme in a non-active lifecycle was excluded before and stays so
        # (keying on lifecycle ALONE would have loosened this; OR keeps the source bar).
        self.assertNotIn("Y", _ranked({"Y": _meta(source="provisional_discovered", lifecycle="cooling",
                                                   market_confirmed=False, theme_id="ty")}))

    def test_confirmed_active_industry_heat_row_is_not_over_tightened(self):
        # positive control: a confirmed_active industry-heat theme is not provisional and needs no mc bar.
        self.assertIn("Z", _ranked({"Z": _meta(source="industry_heat_v1", lifecycle="confirmed_active",
                                                market_confirmed=False, theme_id="tz")}))

    def test_provisional_active_leader_needs_confirmation_for_upgrade(self):
        meta = {f"T{i}": _meta(theme_id=f"t{i}", leader_rs=float(i)) for i in range(1, 9)}
        meta["T7"].update({"theme_lifecycle_state": "provisional_active", "market_confirmed": False})
        selected = [f"T{i}" for i in range(1, 9)]
        ranks = {t: i for i, t in enumerate(selected, start=1)}
        upgrades = strong_theme_leader_upgrades(
            selected_tickers=selected, metadata_by_ticker=meta, selection_ranks=ranks,
            theme_opportunity_state="strong", maximum=3)
        self.assertNotIn("T7", upgrades)


if __name__ == "__main__":
    unittest.main()
