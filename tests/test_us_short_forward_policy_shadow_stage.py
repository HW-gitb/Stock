from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from engine.us_short_eligibility_gate import load_eligibility_governance
from engine.us_short_forward_policy_heads import ForwardPolicyHeadError, build_selection_policy_heads
from engine.us_short_forward_policy_shadow_stage import (
    ForwardPolicyShadowStageError,
    materialize_forward_policy_shadow,
    validate_forward_shadow_selection_record,
)
from runners import us_short_weekly_capstone_stages as capstone_stages
from runners import us_short_batch5_data_context_source_packet as source_packet_runner


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
                "macro_cluster": "unclassified_conservative",
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
        self.assertEqual(private_record["schema_version"], "2.1.0")
        self.assertEqual(private_record["common_selection_pool"], ["ALFA", "BETA"])
        self.assertEqual(len(private_record["common_selection_pool_sha256"]), 64)
        self.assertEqual(len(private_record["comparison_contract_sha256"]), 64)
        self.assertEqual(private_record["baseline_epoch_sha256"], summary["baseline_epoch_sha256"])
        self.assertEqual(summary["common_selection_pool_count"], 2)
        self.assertEqual(summary["common_selection_pool_sha256"], private_record["common_selection_pool_sha256"])
        self.assertEqual(summary["comparison_contract_sha256"], private_record["comparison_contract_sha256"])
        self.assertEqual(summary["decision_date"], "20260713")
        self.assertEqual(summary["price_basis_date"], "20260710")
        self.assertNotIn("ALFA", summary_text)
        self.assertNotIn("BETA", summary_text)
        self.assertFalse(summary["boundary"]["shadow_counts_ship_gate"])
        self.assertFalse(summary["boundary"]["provider_calls_added"])
        # JSON writers sort object keys; the persisted policy-keyed map must remain valid after reload rather than
        # treating serialization order as a strategy-contract order.
        validate_forward_shadow_selection_record(private_record)

    def test_enabled_provisional_theme_boost_key_is_consumed_by_shadow_heads(self):
        bound = {
            "theme_soft_boost": 5.0,
            "evidence_tier": "both",
            "validated_theme_ids": ["theme_00"],
            "source_ref_ids": ["web:theme", "x:theme"],
            "observed_at": "2026-06-12T12:10:00Z",
            "validation_identity": {
                "expected_decision_date": "20260713",
                "input_digests": {
                    "discovery_artifact_sha256": "a" * 64,
                    "candidate_artifact_sha256": "b" * 64,
                    "classification_packet_sha256": "c" * 64,
                },
            },
            "boost_applied": True,
        }
        baseline = build_selection_policy_heads(
            self.composition, overextension_by_ticker=self.overextension,
            theme_selection_contract=self.data_context["selection_inputs"]["theme_selection_contract"],
        )
        # BETA is `none` in this fixture (ALFA is chasing_extreme), so BETA is the un-stripped case.
        enabled_composition = copy.deepcopy(self.composition)
        enabled_composition["analysis_by_ticker"]["BETA"]["provisional_theme_boost"] = bound
        enabled = build_selection_policy_heads(
            enabled_composition, overextension_by_ticker=self.overextension,
            theme_selection_contract=self.data_context["selection_inputs"]["theme_selection_contract"],
        )
        self.assertAlmostEqual(
            enabled["balanced"]["per_ticker"]["BETA"]["core_score"],
            baseline["balanced"]["per_ticker"]["BETA"]["core_score"] + 5.0,
        )
        # §12.2: theme_off is the theme-ablation counterfactual — a theme-derived boost must NOT ride into it,
        # or the forward A/B attribution measures the boost instead of the theme block.
        self.assertAlmostEqual(
            enabled["theme_off"]["per_ticker"]["BETA"]["core_score"],
            baseline["theme_off"]["per_ticker"]["BETA"]["core_score"],
        )
        # §4.3: ALFA is chasing_extreme — the heads must not refund the strip either, even if a record
        # reaches them with boost_applied=True (compose already suppresses it; this is the second latch).
        stripped_composition = copy.deepcopy(self.composition)
        stripped_composition["analysis_by_ticker"]["ALFA"]["provisional_theme_boost"] = bound
        with_stripped = build_selection_policy_heads(
            stripped_composition, overextension_by_ticker=self.overextension,
            theme_selection_contract=self.data_context["selection_inputs"]["theme_selection_contract"],
        )
        self.assertAlmostEqual(
            with_stripped["balanced"]["per_ticker"]["ALFA"]["core_score"],
            baseline["balanced"]["per_ticker"]["ALFA"]["core_score"],
        )

    def test_shadow_heads_reject_malformed_provisional_boost_record(self):
        bad = copy.deepcopy(self.composition)
        bad["analysis_by_ticker"]["ALFA"]["provisional_theme_boost"] = {
            "theme_soft_boost": 5.0, "evidence_tier": "both", "validated_theme_ids": [],
            "source_ref_ids": [], "observed_at": None, "boost_applied": True,
            "validation_identity": {"expected_decision_date": "20260713", "input_digests": {}},
        }
        with self.assertRaises(ForwardPolicyHeadError):
            build_selection_policy_heads(
                bad, overextension_by_ticker=self.overextension,
                theme_selection_contract=self.data_context["selection_inputs"]["theme_selection_contract"],
            )

    def test_shadow_heads_cap_provisional_boost_at_hundred(self):
        capped = copy.deepcopy(self.composition)
        capped["analysis_by_ticker"]["BETA"]["score_blocks"] = {
            "momentum": 100.0, "theme": 100.0, "catalyst": 100.0,
        }
        capped["analysis_by_ticker"]["BETA"]["provisional_theme_boost"] = {
            "theme_soft_boost": 5.0, "evidence_tier": "both", "validated_theme_ids": ["theme_00"],
            "source_ref_ids": ["web:theme", "x:theme"], "observed_at": "2026-06-12T12:10:00Z",
            "boost_applied": True,
            "validation_identity": {
                "expected_decision_date": "20260713",
                "input_digests": {"discovery_artifact_sha256": "a" * 64, "candidate_artifact_sha256": "b" * 64, "classification_packet_sha256": "c" * 64},
            },
        }
        heads_out = build_selection_policy_heads(
            capped, overextension_by_ticker=self.overextension,
            theme_selection_contract=self.data_context["selection_inputs"]["theme_selection_contract"],
        )
        self.assertEqual(heads_out["balanced"]["per_ticker"]["BETA"]["core_score"], 100.0)

    def test_common_pool_is_pass2_clean_and_identical_across_all_heads(self):
        self.data_context["universe"].append({
            "ticker": "VETO", "exchange": "NASDAQ", "price": 20.0, "adv_usd": 10_000_000.0,
            "market_cap_usd": 1_000_000_000.0, "delisted": False, "halted": False,
            "bankruptcy": False, "otc": False,
        })
        self.data_context["candidate_pass2_signals"]["VETO"] = {"bankruptcy": True}

        with tempfile.TemporaryDirectory() as tmp:
            result = self._materialize(Path(tmp))
            private_record = json.loads(Path(result["private_record_path"]).read_text(encoding="utf-8"))

        self.assertIn("VETO", private_record["selection_decisions"]["balanced"]["candidates"])
        self.assertNotIn("VETO", private_record["common_selection_pool"])
        self.assertTrue(all(
            set(decision["admitted"]).issubset(set(private_record["common_selection_pool"]))
            for decision in private_record["selection_decisions"].values()
        ))

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
            component_values = {
                "data_context": self.data_context,
                "score_composition": self.composition,
                "overextension_by_ticker": self.overextension,
                "per_ticker_analysis": {},
                "run_provenance": {
                    "as_of": "20260713",
                    "price_basis_date": "20260710",
                    "families": {},
                },
                "result_linkage_sources": {},
            }
            current_shape = next(reversed(source_packet_runner.CONTEXT_COMPONENT_SHAPES))
            components_path.write_text(json.dumps({
                key: component_values[key]
                for key in source_packet_runner.CONTEXT_COMPONENT_SHAPES[current_shape]
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
                ohlcv_series_packet_path = root / "ohlcv.json"
                batch4_template_path = root / "batch4_template.json"
                vix_regime_summary_path = root / "vix_regime.json"
                forward_policy_source_capture_private_path = root / "forward_policy_source_capture_20260713.json"

            Context.ohlcv_series_packet_path.write_text("{}", encoding="utf-8")
            Context.batch4_template_path.write_text("{}", encoding="utf-8")
            Context.vix_regime_summary_path.write_text("{}", encoding="utf-8")
            source_capture = {
                "private_source_capture_path": str(Context.forward_policy_source_capture_private_path),
                "decision_date": "20260713",
                "order_snapshot_status": "ready_for_outcome",
            }
            with mock.patch.object(
                capstone_stages, "materialize_forward_policy_source_capture", return_value=source_capture
            ) as capture, mock.patch.object(
                capstone_stages._bridge,
                "_load_template",
                return_value={
                    "market_axis_regimes": {"vix": "进攻", "market_trend": "进攻", "breadth": "进攻"},
                    "prior_regime": None,
                    "prior_upgrade_count": 0,
                },
            ):
                result = capstone_stages.run_forward_policy_shadow(Context())
            self.assertEqual(result["summary"]["selected_counts"]["balanced"], 2)
            self.assertEqual(result["source_capture"], source_capture)
            capture.assert_called_once()
            self.assertTrue(Context.forward_shadow_selection_private_path.exists())
            self.assertTrue(Context.forward_policy_summary_path.exists())

            current_components = json.loads(components_path.read_text(encoding="utf-8"))
            legacy_components = dict(current_components)
            legacy_components.pop("result_linkage_sources")
            components_path.write_text(json.dumps(legacy_components), encoding="utf-8")
            Context.forward_shadow_selection_private_path = root / "rejected_forward_policy_selection_20260713.json"
            Context.forward_policy_summary_path = root / "rejected_forward_policy_summary_20260713.json"
            with self.assertRaisesRegex(ValueError, "missing_keys=.*result_linkage_sources"):
                capstone_stages.run_forward_policy_shadow(Context())
            self.assertFalse(Context.forward_shadow_selection_private_path.exists())
            self.assertFalse(Context.forward_policy_summary_path.exists())

            components_path.write_text(json.dumps(current_components), encoding="utf-8")
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
