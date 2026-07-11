from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime
from pathlib import Path

from engine import us_short_forward_policy_heads as heads
from engine.us_short_eligibility_gate import load_eligibility_governance


ROOT = Path(__file__).resolve().parents[1]
GRID_PATH = ROOT / "presets" / "us_short_forward_policy_grid_20260711.json"
_ELIGIBILITY_GOVERNANCE = load_eligibility_governance(
    ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
)


def _risk(points=0.0):
    return {
        "components": {
            "history": 0.0,
            "current_event": 0.0,
            "analyst": 0.0,
        },
        "points": points,
        "hard_veto": False,
    }


def _overextension(*, strip=False):
    return {
        "overextension_state": "chasing_extreme" if strip else "none",
        "strips_theme_score": strip,
        "execution_flags": {},
        "conditions_met": 3 if strip else 0,
        "condition_names": ["vertical_run", "daily_move_ge_m_atr", "volume_climax"] if strip else [],
        "pit": {
            "as_of": "2026-07-10",
            "session": "RTH",
            "adjustment_mode": "split_div_adjusted",
            "n_points": 30,
        },
        "disposition": "scored",
    }


def _composition():
    rows = {
        "ALFA": {"momentum": 60.0, "theme": 100.0, "catalyst": 50.0},
        "BETA": {"momentum": 70.0, "theme": 0.0, "catalyst": 50.0},
        "CATA": {"momentum": 50.0, "theme": 50.0, "catalyst": 100.0},
        "DELT": {"momentum": 65.0, "theme": 65.0, "catalyst": 0.0},
    }
    analysis = {
        ticker: {"score_blocks": blocks, "risk_downgrade": _risk(), "scoring_profile": "theme_off" if ticker == "ALFA" else "balanced"}
        for ticker, blocks in rows.items()
    }
    return {
        "selection_inputs": {
            "theme_opportunity_state": "no_strong_theme",
            "per_ticker": {
                "ALFA": {"core_score": 56.153, "theme_momentum_score": 0.0},
                "BETA": {"core_score": 62.5, "theme_momentum_score": 0.0},
                "CATA": {"core_score": 62.5, "theme_momentum_score": 50.0},
                "DELT": {"core_score": 48.75, "theme_momentum_score": 65.0},
            },
        },
        "analysis_by_ticker": analysis,
        "coverage_by_ticker": {ticker: {} for ticker in rows},
        "target_tickers": list(rows),
        "scoring_profile": "balanced",
        "scored_component_counts": {"momentum": 4, "theme": 4, "catalyst": 4},
    }


def _overextension_map():
    return {"ALFA": _overextension(strip=True), "BETA": _overextension(), "CATA": _overextension(), "DELT": _overextension()}


class ForwardPolicyHeadTests(unittest.TestCase):
    def test_grid_exposes_exact_live_selection_and_second_wave_sets(self):
        self.assertEqual(
            heads.SELECTION_POLICY_IDS,
            ("balanced", "theme_plus", "theme_aggressive", "theme_off", "catalyst_off", "overextension_selection_off"),
        )
        self.assertEqual(heads.SECOND_WAVE_LIVE_POLICY_IDS, ("overextension_execution_off",))

    def test_path_a_has_no_delayed_materialization_contract_surfaces(self):
        grid = json.loads(GRID_PATH.read_text(encoding="utf-8"))
        self.assertEqual(grid["status"], "initial_live_shadow_policy_grid")
        self.assertEqual(grid["second_wave_live_policies"], ["overextension_execution_off"])
        self.assertNotIn("deferred_sequential_policies", grid)
        self.assertEqual(
            grid["policies"]["overextension_execution_off"]["materialization"],
            "second_wave_live",
        )
        for relative_path in (
            "docs/us_short_forward_policy_materialization_contract.md",
            "engine/us_short_forward_policy_store.py",
            "schemas/us_short_forward_policy_manifest.schema.json",
            "tests/test_us_short_forward_policy_store.py",
            "tests/schema/test_us_short_forward_policy_manifest_schema.py",
        ):
            self.assertFalse((ROOT / relative_path).exists(), relative_path)
        design = (ROOT / "docs" / "us_short_system_design.md").read_text(encoding="utf-8")
        self.assertNotIn("precommitted_delayed_materialization", design)
        self.assertNotIn("forward_policy_private", design)
        self.assertNotIn("sequential materialization", design)
        self.assertNotIn("forward_policy_private", (ROOT / ".gitignore").read_text(encoding="utf-8"))

    def test_catalyst_off_reallocates_only_catalyst_weight(self):
        out = heads.build_selection_policy_heads(_composition(), overextension_by_ticker=_overextension_map())
        self.assertAlmostEqual(out["catalyst_off"]["per_ticker"]["CATA"]["core_score"], 50.0)
        self.assertAlmostEqual(out["catalyst_off"]["per_ticker"]["DELT"]["core_score"], 65.0)
        self.assertEqual(out["catalyst_off"]["per_ticker"]["CATA"]["theme_momentum_score"], 50.0)

    def test_catalyst_off_chasing_strips_theme_without_realloc(self):
        # catalyst_off weights {mom 0.5333, theme 0.4667, cat 0}; a chasing strip removes the theme
        # contribution with NO reallocation (strip_theme_score), NOT momentum-only: ALFA -> 0.5333*60 = 32.
        out = heads.build_selection_policy_heads(_composition(), overextension_by_ticker=_overextension_map())
        alfa = out["catalyst_off"]["per_ticker"]["ALFA"]
        self.assertAlmostEqual(alfa["core_score"], 32.0)
        self.assertEqual(alfa["theme_momentum_score"], 0.0)

    def test_overextension_selection_off_restores_only_selection_effect(self):
        out = heads.build_selection_policy_heads(_composition(), overextension_by_ticker=_overextension_map())
        baseline = out["balanced"]["per_ticker"]["ALFA"]
        ablated = out["overextension_selection_off"]["per_ticker"]["ALFA"]
        # chasing ALFA in the balanced head: strip_theme_score on balanced (0.40*60 + 0.25*50 = 36.5),
        # a real penalty (< the 71.5 unstripped balanced), NOT the old theme_off realloc 56.15.
        self.assertAlmostEqual(baseline["core_score"], 36.5)
        self.assertEqual(baseline["theme_momentum_score"], 0.0)
        self.assertAlmostEqual(ablated["core_score"], 71.5)
        self.assertEqual(ablated["theme_momentum_score"], 100.0)

    def test_balanced_head_chasing_matches_real_strip_theme_score(self):
        # The balanced head is the A/B control: on a chasing ticker it must equal the real balanced
        # track (core_score strip_theme_score=True), NOT the theme_off reallocation.
        from engine.us_short_core_score import core_score
        out = heads.build_selection_policy_heads(_composition(), overextension_by_ticker=_overextension_map())
        blocks = _composition()["analysis_by_ticker"]["ALFA"]["score_blocks"]
        expected = core_score(blocks, profile="balanced", strip_theme_score=True)["core_score"]
        self.assertAlmostEqual(out["balanced"]["per_ticker"]["ALFA"]["core_score"], expected)

    def test_theme_off_zeros_theme_seat_for_all_rows(self):
        out = heads.build_selection_policy_heads(_composition(), overextension_by_ticker=_overextension_map())
        self.assertTrue(all(row["theme_momentum_score"] == 0.0 for row in out["theme_off"]["per_ticker"].values()))

    def test_invalid_or_incomplete_overextension_map_fails_closed(self):
        bad = _overextension_map()
        del bad["DELT"]
        with self.assertRaises(heads.ForwardPolicyHeadError):
            heads.build_selection_policy_heads(_composition(), overextension_by_ticker=bad)
        bad = _overextension_map()
        bad["ALFA"] = copy.deepcopy(bad["ALFA"])
        bad["ALFA"]["strips_theme_score"] = False
        with self.assertRaises(heads.ForwardPolicyHeadError):
            heads.build_selection_policy_heads(_composition(), overextension_by_ticker=bad)

    def test_policy_decisions_delegate_to_existing_selection_pipeline(self):
        comp = _composition()
        universe = [
            {
                "ticker": ticker,
                "exchange": "NASDAQ",
                "price": 20.0,
                "adv_usd": 10_000_000.0,
                "market_cap_usd": 1_000_000_000.0,
                "delisted": False,
                "halted": False,
                "bankruptcy": False,
                "otc": False,
            }
            for ticker in comp["target_tickers"]
        ]
        context = {
            "universe": universe,
            "catalyst_recall_feed": None,
            "holdings": [],
            "candidate_pass2_signals": {ticker: {} for ticker in comp["target_tickers"]},
            "selection_inputs": comp["selection_inputs"],
        }
        sessions = [{"date": "20260710"}, {"date": "20260713"}]
        out = heads.build_selection_policy_decisions(
            now_et=datetime(2026, 7, 13, 8, 0), sessions=sessions, data_context=context,
            eligibility_governance=_ELIGIBILITY_GOVERNANCE, score_composition=comp,
            overextension_by_ticker=_overextension_map(),
        )
        self.assertEqual(set(out["selection_heads"]), set(heads.SELECTION_POLICY_IDS))
        self.assertEqual(set(out["selection_decisions"]), set(heads.SELECTION_POLICY_IDS))
        self.assertFalse(out["selection_decisions"]["balanced"]["out_of_window"])
        self.assertEqual(context["selection_inputs"], comp["selection_inputs"])


if __name__ == "__main__":
    unittest.main()
