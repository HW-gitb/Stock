# -*- coding: utf-8 -*-
"""Tests for the US-short market risk-regime engine (engine/us_short_regime.py) — §7.

Adversarial focus (fewer FAIL->修复 rounds): the load-bearing safety gate is never-default-
aggressive on incomplete data, plus anti-chatter (downgrade fast / upgrade slow) and the frozen
cap ladder. Conformance triangulates the engine's cap ladder + anti-chatter run count against
the frozen us_short_regime_governance preset.
"""
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_regime as rg  # noqa: E402

_GOV = ROOT / "presets" / "us_short_regime_governance_20260620.json"


def _r(vix=None, trend=None, breadth=None):
    d = {}
    if vix is not None:
        d["vix"] = vix
    if trend is not None:
        d["market_trend"] = trend
    if breadth is not None:
        d["breadth"] = breadth
    return d


_AXIS_BASIS = "2026-08-14"


def _axis_series(latest, *, prior=100.0, future=None, count=50):
    basis = date.fromisoformat(_AXIS_BASIS)
    points = [
        {"date": (basis - timedelta(days=count - 1 - index)).isoformat(), "close": prior}
        for index in range(count - 1)
    ]
    points.append({"date": _AXIS_BASIS, "close": latest})
    if future is not None:
        points.append({"date": (basis + timedelta(days=1)).isoformat(), "close": future})
    return {"as_of": _AXIS_BASIS, "session": "RTH", "adjustment_mode": "split_adjusted", "points": points}


class MarketAxisFormulaTests(unittest.TestCase):
    def test_market_trend_table_includes_sma50_and_qqq_ratio_cut(self):
        exact_boundary_prior = (50 * 100.0 - 90.0) / 49.0
        cases = (
            ("both above", 101.0, 101.0, 100.0, "进攻"),
            ("one above", 101.0, 99.0, 100.0, "震荡"),
            ("qqq ratio above .90", 99.0, 90.0, 100.0, "防御"),
            ("qqq ratio at .90", 99.0, 90.0, exact_boundary_prior, "极度防御"),
        )
        for label, spy_latest, qqq_latest, qqq_prior, expected in cases:
            with self.subTest(label=label):
                self.assertEqual(
                    rg.classify_market_trend(
                        {"SPY": _axis_series(spy_latest), "QQQ": _axis_series(qqq_latest, prior=qqq_prior)},
                        price_basis_date=_AXIS_BASIS,
                    ),
                    expected,
                )

    def test_market_trend_uses_basis_or_earlier_and_unknowns_short_benchmark(self):
        future_only_signal = {
            "SPY": _axis_series(99.0, future=150.0),
            "QQQ": _axis_series(99.0, future=150.0),
        }
        self.assertEqual(rg.classify_market_trend(future_only_signal, price_basis_date=_AXIS_BASIS), "防御")
        short = {
            "SPY": _axis_series(101.0, count=49),
            "QQQ": _axis_series(101.0),
        }
        self.assertEqual(rg.classify_market_trend(short, price_basis_date=_AXIS_BASIS), rg.UNKNOWN)

    def test_breadth_table_covers_80_60_40_25_boundaries(self):
        cases = (
            (5, 5, 3, "进攻"),
            (5, 5, 2, "震荡"),
            (5, 4, 1, "防御"),
            (5, 5, 1, "极度防御"),
            (5, 4, 4, "进攻"),
            (5, 3, 3, rg.UNKNOWN),
        )
        for eligible_count, computable_count, above_count, expected in cases:
            with self.subTest(eligible_count=eligible_count, computable_count=computable_count, above_count=above_count):
                tickers = [f"T{index}" for index in range(eligible_count)]
                series = {
                    ticker: _axis_series(101.0 if index < above_count else 99.0)
                    for index, ticker in enumerate(tickers[:computable_count])
                }
                self.assertEqual(
                    rg.classify_breadth(tickers, series, price_basis_date=_AXIS_BASIS),
                    expected,
                )


class MarketAxisBridgeInputTests(unittest.TestCase):
    def test_weekly_bridge_reads_same_round_candidate_and_momentum_packet(self):
        from types import SimpleNamespace

        from runners import us_short_weekly_capstone_stages as stages
        from tests.provider import test_us_short_batch5_full_universe_momentum_producer as fixture

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            series = fixture._base_series_map()
            for ticker in fixture._ALL_ELIGIBLE:
                series[ticker] = fixture._series(start=100.0, step=1.0)
            candidate_path = root / "candidate.json"
            packet_path = root / "momentum.json"
            candidate_path.write_text(
                json.dumps(fixture._candidate_artifact(fixture._ALL_ELIGIBLE)), encoding="utf-8"
            )
            packet_path.write_text(json.dumps(fixture._series_packet(series)), encoding="utf-8")
            ctx = SimpleNamespace(
                candidate_path=candidate_path,
                series_packet_path=packet_path,
                decision_date=fixture._DECISION_DATE,
                price_basis_date=fixture._PRICE_BASIS_DATE,
            )
            self.assertEqual(
                stages._build_market_axis_regimes(ctx, vix_regime="进攻"),
                {"vix": "进攻", "market_trend": "进攻", "breadth": "进攻"},
            )

            packet = fixture._series_packet(series)
            packet["decision_clock"]["price_basis_date"] = "2026-06-11"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "market-axis"):
                stages._build_market_axis_regimes(ctx, vix_regime="进攻")


class ClassifyVixTests(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(rg.classify_vix(12.0), "进攻")
        self.assertEqual(rg.classify_vix(20.0), "震荡")
        self.assertEqual(rg.classify_vix(30.0), "防御")
        self.assertEqual(rg.classify_vix(40.0), "极度防御")

    def test_boundaries_are_lower_inclusive(self):
        self.assertEqual(rg.classify_vix(17.999), "进攻")
        self.assertEqual(rg.classify_vix(18.0), "震荡")   # >= 18 leaves 进攻
        self.assertEqual(rg.classify_vix(25.0), "防御")
        self.assertEqual(rg.classify_vix(35.0), "极度防御")

    def test_unknown_never_guessed(self):
        for bad in (None, float("nan"), float("inf"), "x"):
            self.assertEqual(rg.classify_vix(bad), rg.UNKNOWN)
        self.assertEqual(rg.classify_vix("18"), "震荡")   # numeric string parses, not unknown


class WorstOfAndDegradationTests(unittest.TestCase):
    def test_worst_of_full_data(self):
        self.assertEqual(rg.compute_market_risk_regime(_r("进攻", "进攻", "进攻"))["market_risk_regime"], "进攻")
        self.assertEqual(rg.compute_market_risk_regime(_r("进攻", "震荡", "防御"))["market_risk_regime"], "防御")

    def test_unknown_axis_never_stays_aggressive(self):
        # REVERSE-FAILURE control: a missing/unknown axis must NOT pass as 进攻 (never_default_aggressive)
        out = rg.compute_market_risk_regime(_r(rg.UNKNOWN, "进攻", "进攻"))
        self.assertNotEqual(out["market_risk_regime"], "进攻")
        self.assertEqual(out["market_risk_regime"], "震荡")   # 1 missing -> one conservative downgrade
        self.assertEqual(out["missing_axes"], ["vix"])

    def test_missing_critical_trend_floors_at_defensive(self):
        out = rg.compute_market_risk_regime(_r(vix="进攻", breadth="进攻"))   # market_trend absent (critical)
        self.assertEqual(out["market_risk_regime"], "防御")

    def test_all_axes_missing_is_restricted_most_defensive(self):
        out = rg.compute_market_risk_regime({})
        self.assertEqual(out["market_risk_regime"], "极度防御")
        self.assertTrue(out["restricted"])
        self.assertEqual(out["position_cap"], 0.0)
        self.assertFalse(out["new_entry_permitted"])

    def test_more_missing_is_more_defensive(self):
        one = rg.compute_market_risk_regime(_r("进攻", "进攻"))["market_risk_regime"]   # breadth missing
        two = rg.compute_market_risk_regime(_r("进攻"))["market_risk_regime"]            # trend+breadth missing
        self.assertGreaterEqual(rg._SEVERITY[two], rg._SEVERITY[one])

    def test_non_dict_axis_input_is_restricted_not_crash(self):
        # a truthy non-dict axis_regimes (list/str/int) must fail closed to restricted/极度防御, never crash
        for bad in (["进攻"], "进攻", 1, ("震荡",)):
            out = rg.compute_market_risk_regime(bad)
            self.assertEqual(out["market_risk_regime"], "极度防御", repr(bad))
            self.assertTrue(out["restricted"], repr(bad))
            self.assertFalse(out["new_entry_permitted"], repr(bad))


class AntiChatterTests(unittest.TestCase):
    def test_downgrade_is_immediate(self):
        out = rg.compute_market_risk_regime(_r("防御", "防御", "防御"), prior_regime="进攻")
        self.assertEqual(out["market_risk_regime"], "防御")
        self.assertEqual(out["upgrade_count"], 0)

    def test_upgrade_needs_two_consecutive_better_runs(self):
        first = rg.compute_market_risk_regime(_r("进攻", "进攻", "进攻"), prior_regime="防御", prior_upgrade_count=0)
        self.assertEqual(first["market_risk_regime"], "防御")   # held, not yet upgraded
        self.assertEqual(first["upgrade_count"], 1)
        second = rg.compute_market_risk_regime(_r("进攻", "进攻", "进攻"), prior_regime="防御", prior_upgrade_count=1)
        self.assertEqual(second["market_risk_regime"], "进攻")  # confirmed -> upgrade
        self.assertEqual(second["upgrade_count"], 0)

    def test_equal_regime_no_chatter(self):
        out = rg.compute_market_risk_regime(_r("震荡", "震荡", "震荡"), prior_regime="震荡")
        self.assertEqual(out["market_risk_regime"], "震荡")


class DatedStateTests(unittest.TestCase):
    def test_formal_analysis_builds_fixed_five_key_state(self):
        state = rg.build_market_regime_state(
            "20260810",
            {"regime": {"market_risk_regime": "防御", "upgrade_count": 1}},
        )
        self.assertEqual(
            set(state),
            {"schema_name", "schema_version", "as_of", "market_risk_regime", "upgrade_count"},
        )
        self.assertEqual("防御", state["market_risk_regime"])
        self.assertEqual(1, state["upgrade_count"])

    def test_loader_rejects_missing_or_corrupt_selected_state(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / rg.MARKET_REGIME_STATE_FILENAME
            with self.assertRaises(rg.MarketRegimeStateError):
                rg.load_market_regime_state(path, decision_date="20260810")
            path.write_text(json.dumps({
                "schema_name": rg.MARKET_REGIME_STATE_SCHEMA_NAME,
                "schema_version": rg.MARKET_REGIME_STATE_SCHEMA_VERSION,
                "as_of": "20260809",
                "market_risk_regime": "防御",
                "upgrade_count": True,
            }), encoding="utf-8")
            with self.assertRaises(rg.MarketRegimeStateError):
                rg.load_market_regime_state(path, decision_date="20260810")


class ContractConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gov = json.loads(_GOV.read_text(encoding="utf-8"))

    def test_cap_ladder_matches_preset(self):
        preset = {c["regime"]: c["position_cap"] for c in self.gov["market_risk_regime_caps"]}
        self.assertEqual(preset, rg.POSITION_CAP)
        self.assertEqual(set(preset), set(rg.REGIMES))

    def test_anti_chatter_run_count_matches_preset(self):
        self.assertEqual(self.gov["anti_chatter"]["upgrade_confirmation_weekly_runs"], rg.UPGRADE_CONFIRM_RUNS)

    def test_each_regime_emits_its_frozen_cap(self):
        for regime, cap in rg.POSITION_CAP.items():
            out = rg.compute_market_risk_regime(_r(regime, regime, regime))
            self.assertEqual(out["market_risk_regime"], regime)
            self.assertEqual(out["position_cap"], cap)

    def test_scope_is_not_hard_veto(self):
        # §7 scope: regime affects sizing/new-entry, never a hard veto — the engine emits no veto field.
        out = rg.compute_market_risk_regime(_r("极度防御", "极度防御", "极度防御"))
        self.assertNotIn("veto_tier", out)
        self.assertNotIn("hard_veto", out)
        self.assertTrue(self.gov["scope"]["not_hard_veto"])


if __name__ == "__main__":
    unittest.main()
