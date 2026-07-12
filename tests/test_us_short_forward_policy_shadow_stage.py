from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from engine.us_short_eligibility_gate import load_eligibility_governance
from engine.us_short_forward_policy_shadow_stage import (
    ForwardPolicyShadowStageError,
    materialize_forward_policy_shadow,
)
from runners import us_short_weekly_capstone_stages as capstone_stages


ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE = load_eligibility_governance(ROOT / "presets" / "us_short_eligibility_governance_20260624.json")


def _risk():
    return {
        "components": {"history": 0.0, "current_event": 0.0, "analyst": 0.0},
        "points": 0.0,
        "hard_veto": False,
    }


def _overextension(state="none"):
    strip = state == "chasing_extreme"
    return {
        "overextension_state": state,
        "strips_theme_score": strip,
        "execution_flags": {},
        "conditions_met": 3 if strip else 0,
        "condition_names": ["vertical_run", "daily_move_ge_m_atr", "volume_climax"] if strip else [],
        "pit": {"as_of": "2026-07-10", "session": "RTH", "adjustment_mode": "split_div_adjusted", "n_points": 30},
        "disposition": "scored",
    }


def _theme_selection_contract(tickers):
    return {
        "as_of": "20260713",
        "mode": "industry_heat_v1_cross_industry_disabled",
        "cross_industry_provisional_enabled": False,
        "theme_opportunity_state": "no_strong_theme",
        "per_ticker": {
            ticker: {
                "theme_id": f"industry:{ticker.lower()}",
                "theme_source": "industry_heat_v1",
                "theme_lifecycle_state": "confirmed_active",
                "theme_leader_rs": 0.0,
                "membership_origin": "automatic_discovery",
                "market_confirmed": True,
                "individual_theme_gate_passed": True,
                "overextension_state": "none",
            }
            for ticker in tickers
        },
    }


def _inputs():
    blocks = {
        "ALFA": {"momentum": 60.0, "theme": 100.0, "catalyst": 50.0},
        "BETA": {"momentum": 70.0, "theme": 0.0, "catalyst": 50.0},
    }
    composition = {
        "selection_inputs": {
            "theme_opportunity_state": "no_strong_theme",
            "per_ticker": {
                "ALFA": {"core_score": 56.153, "theme_momentum_score": 0.0},
                "BETA": {"core_score": 62.5, "theme_momentum_score": 0.0},
            },
        },
        "analysis_by_ticker": {
            ticker: {"score_blocks": value, "risk_downgrade": _risk(), "scoring_profile": "balanced"}
            for ticker, value in blocks.items()
        },
        "coverage_by_ticker": {ticker: {} for ticker in blocks},
        "target_tickers": list(blocks),
        "scoring_profile": "balanced",
        "scored_component_counts": {"momentum": 2, "theme": 2, "catalyst": 2},
    }
    data_context = {
        "universe": [
            {"ticker": ticker, "exchange": "NASDAQ", "price": 20.0, "adv_usd": 10_000_000.0,
             "market_cap_usd": 1_000_000_000.0, "delisted": False, "halted": False,
             "bankruptcy": False, "otc": False}
            for ticker in blocks
        ],
        "catalyst_recall_feed": None,
        "holdings": [],
        "candidate_pass2_signals": {ticker: {} for ticker in blocks},
        "selection_inputs": {
            **composition["selection_inputs"],
            "theme_selection_contract": _theme_selection_contract(blocks),
        },
    }
    return data_context, composition, {"ALFA": _overextension("chasing_extreme"), "BETA": _overextension()}


class ForwardPolicyShadowStageTests(unittest.TestCase):
    def setUp(self):
        self.data_context, self.composition, self.overextension = _inputs()
        self.sessions = [{"date": "20260710"}, {"date": "20260713"}]
        self.now_et = datetime(2026, 7, 13, 8, 0, 0)

    def _materialize(self, root: Path, **overrides):
        kwargs = {
            "now_et": self.now_et,
            "sessions": self.sessions,
            "data_context": self.data_context,
            "eligibility_governance": GOVERNANCE,
            "score_composition": self.composition,
            "overextension_by_ticker": self.overextension,
            "decision_date": "20260713",
            "price_basis_date": "20260710",
            "generated_at": "2026-07-13T08:00:00-04:00",
            "source_context_sha256": "a" * 64,
            "private_output_path": root / "forward_policy_selection_20260713.json",
            "summary_output_path": root / "forward_policy_summary_20260713.json",
        }
        kwargs.update(overrides)
        return materialize_forward_policy_shadow(**kwargs)

    def test_materializes_all_six_heads_private_and_deidentified_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._materialize(Path(tmp))
            private_record = json.loads(Path(result["private_record_path"]).read_text(encoding="utf-8"))
            summary_text = Path(result["summary_path"]).read_text(encoding="utf-8")
            summary = json.loads(summary_text)

        self.assertEqual(private_record["selection_policies"], [
            "balanced", "theme_plus", "theme_aggressive", "theme_off", "catalyst_off", "overextension_selection_off",
        ])
        self.assertEqual(set(private_record["selection_decisions"]), set(private_record["selection_policies"]))
        self.assertEqual(summary["decision_date"], "20260713")
        self.assertEqual(summary["price_basis_date"], "20260710")
        self.assertNotIn("ALFA", summary_text)
        self.assertNotIn("BETA", summary_text)
        self.assertFalse(summary["boundary"]["shadow_counts_ship_gate"])
        self.assertFalse(summary["boundary"]["provider_calls_added"])

    def test_invalid_frozen_input_fails_before_writing_either_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = dict(self.overextension)
            del bad["BETA"]
            with self.assertRaises(ForwardPolicyShadowStageError):
                self._materialize(root, overextension_by_ticker=bad)
            self.assertFalse((root / "forward_policy_selection_20260713.json").exists())
            self.assertFalse((root / "forward_policy_summary_20260713.json").exists())

    def test_capstone_adapter_requires_one_matching_context_components_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "data_context.json"
            components_path = root / "context_components.json"
            data_path.write_text(json.dumps(self.data_context), encoding="utf-8")
            components_path.write_text(json.dumps({
                "data_context": self.data_context,
                "score_composition": self.composition,
                "overextension_by_ticker": self.overextension,
                "per_ticker_analysis": {},
                "run_provenance": {
                    "as_of": "20260713",
                    "price_basis_date": "20260710",
                    "families": {},
                },
            }), encoding="utf-8")

            class Context:
                now_et = self.now_et
                data_context_path = data_path
                context_components_path = components_path
                decision_date = "20260713"
                price_basis_date = "20260710"
                generated_at = "2026-07-13T08:00:00-04:00"
                forward_shadow_selection_private_path = root / "forward_policy_selection_20260713.json"
                forward_policy_summary_path = root / "forward_policy_summary_20260713.json"

            result = capstone_stages.run_forward_policy_shadow(Context())
            self.assertEqual(result["summary"]["selected_counts"]["balanced"], 2)
            self.assertTrue(Context.forward_shadow_selection_private_path.exists())
            self.assertTrue(Context.forward_policy_summary_path.exists())

            mismatched = dict(self.data_context)
            mismatched["selection_inputs"] = {
                **mismatched["selection_inputs"],
                "theme_opportunity_state": "strong",
            }
            data_path.write_text(json.dumps(mismatched), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mismatched"):
                capstone_stages.run_forward_policy_shadow(Context())

            data_path.write_text(json.dumps(self.data_context), encoding="utf-8")
            stale_provenance = json.loads(components_path.read_text(encoding="utf-8"))
            stale_provenance["run_provenance"]["as_of"] = "20260706"
            components_path.write_text(json.dumps(stale_provenance), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "provenance clock"):
                capstone_stages.run_forward_policy_shadow(Context())


if __name__ == "__main__":
    unittest.main()
