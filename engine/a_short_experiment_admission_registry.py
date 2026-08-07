"""Frozen A-short admissions for the existing P0/P1/P2/P3/P5 evidence lanes.

The registry is deliberately a control-plane adapter: each lane keeps its own
ledger and evaluator.  These sealed definitions only bind the identity,
one-change boundary, forward/PIT contract and statistics that must be frozen
before a new governed epoch can count evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from engine import a_short_experiment_governance as governance
from engine import egs_industry_heat as industry_heat
from engine.a_short_experiment_governance import seal_experiment_admission, validate_experiment_admission


ROOT = Path(__file__).resolve().parents[1]

# Active experiment arms are a reviewed source inventory.  Keep this separate
# from each admission payload: otherwise an editor could alter both an arm and
# its in-payload frozen digest, reseal it, and call the result one-change-only.
_TRUSTED_ARM_INVENTORY: dict[str, tuple[str, str]] = {
    "a_short_p0_d1_entry_anchor_entry_ma_pullback": ("1ca544c94725491d8c5226d80ce0886ccd1ccc8721572eefc761ff465ed0f323", "a258989c442c2774a7d8c499efe83d63ef9e1eca8fb8e253fe42e2ecb9b18147"),
    "a_short_p0_d1_entry_anchor_entry_range_pullback": ("1ca544c94725491d8c5226d80ce0886ccd1ccc8721572eefc761ff465ed0f323", "c1186a030b75faba5eec7d8da698e702c5620b8a12bc68112b57b41cc2ad75ec"),
    "a_short_p0_d3_iv_policy_iv_joint_stress": ("1ca544c94725491d8c5226d80ce0886ccd1ccc8721572eefc761ff465ed0f323", "34a62e65f731ae7dee474379ae07ff4578f1175a6036837cb674730e4bc6fa49"),
    "a_short_p0_d3_iv_policy_iv_step_down": ("1ca544c94725491d8c5226d80ce0886ccd1ccc8721572eefc761ff465ed0f323", "0961d6c1b9ea919458dd8764dade3432242e59e743384b494c10d8001225a89d"),
    "a_short_p1_regime_action_proxy": ("f1385fadf3236c62471291b0755731828021effc19e159bcb65bfcce8e92af0f", "ef0f576ac36f471fbb478a5b8f806efe2b465ef95ee206e7cc7043e1bd692140"),
    "a_short_p2_breakout_entry_policy": ("5aa68bee5f17ae6403da1eb0b4ec3649a528d242bee6268af3a6d5fdef42e0c1", "f53c6a3104cba74cefc43746a8359afec52bfea800b79368be6735ecb8a79ac4"),
    "a_short_p2_target_exit_policy": ("b1ba903ec0da9ec4e31d811918d323fbd9dca40adceac9e08d47235751d10fbc", "157ce64fbe1b924156a5ff73e4e89e576a05932496f5664fa0f715aebcf7d60e"),
    "a_short_p3_managed_exit_vs_hold": ("2d7c929ba2de0054b6e53638227760cad68f5928693f111c06d5024325ae789c", "68fd825ee08a4280127f67dda2d9574b98dcc82df35954fcfbd4d5a3cfd4fdde"),
    "a_short_p3_selected_vs_candidate_pool": ("80af1ea097f8a5be1289d4b782a0f3ae91afc5e5953afcaa3ca6a721d908e3d8", "48a46e61c850f36cf1b55b3c3640619b3f0ecf37c4d811e0f97327d18331458c"),
    "a_short_p3_selected_vs_csi1000": ("c205915ae1d658065b9f7939f8fb3bbb897e31f51ee8a70e1b977c4a03df5bf1", "7e40434737a0493e8ab0dbc91f55ebe16e3936fa57791719a851bccc63081f23"),
    "a_short_p4_stage3_rank_source": ("c7813e9a08fdbda17bacb4cca362dec909a35c64c9c1282cbc1370191508f982", "dde389285ed91cbb6815b6fbdc1660a89b54f7d27c679f4f03b26802ed2cf7f9"),
    "a_short_p5_aggressive_vs_balanced": ("1712bfa088135fdc2b165e19b747f0cc0ae7ed05e2c3051dd46d23dabd4e90fe", "6d6b2cc0196f85885c6dfd65a236cdf20fd712c029a4a45161ffc863f453810b"),
    "a_short_p5_balanced_vs_legacy": ("c2c6994835b3396f4a06b69aa249125279b2731de643f5bfe117af87b0db098e", "1712bfa088135fdc2b165e19b747f0cc0ae7ed05e2c3051dd46d23dabd4e90fe"),
    "a_short_p5_theme_double_vs_balanced": ("1712bfa088135fdc2b165e19b747f0cc0ae7ed05e2c3051dd46d23dabd4e90fe", "ed94724306ac3f62925cce0dba3ff77ac681b746f5fb602a165ab05de71a1e2a"),
}


def trusted_arm_inventory(experiment_id: object) -> tuple[str, str] | None:
    """Return the independently reviewed arm inventory for an active experiment."""
    return _TRUSTED_ARM_INVENTORY.get(str(experiment_id))


class AdmissionRegistryError(ValueError):
    """The current lane contracts cannot be bound to a registered admission."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _load(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdmissionRegistryError(f"cannot read frozen admission source {path.name}") from exc
    if not isinstance(payload, dict):
        raise AdmissionRegistryError(f"frozen admission source {path.name} must be an object")
    return payload


def _admission(*, program_id: str, experiment_id: str, track_mode: str, component_id: str,
               effect_surface: str, baseline: dict, candidate: dict, pit_forward: dict,
               statistical: dict, dependencies: list[dict], dependents: list[str], allowed_path: str) -> dict:
    payload = {
        "schema_name": "a_short_experiment_admission",
        "schema_version": "1.0.0",
        "program_id": program_id,
        "experiment_id": experiment_id,
        "track_mode": track_mode,
        "component_id": component_id,
        "effect_surface": effect_surface,
        "baseline": {"arm_id": baseline["arm_id"], "definition": copy.deepcopy(baseline)},
        "candidate": {"arm_id": candidate["arm_id"], "definition": copy.deepcopy(candidate)},
        "one_change_only": {
            "changed_component_ids": [component_id],
            "unchanged_contract_sha256": _digest({"effect_surface": effect_surface, "dependencies": dependencies}),
            # These are source-built inventory anchors, not re-sealed from an
            # edited admission.  They make an undeclared extra arm/rule change
            # fail even when its ordinary definition/identity hashes are reset.
            "frozen_baseline_definition_sha256": _digest(baseline),
            "frozen_candidate_definition_sha256": _digest(candidate),
            "proof_sha256": "0" * 64,
        },
        "pit_forward_contract": {
            "contract_sha256": _digest(pit_forward),
            "pit_as_of_required": True,
            "forward_only": True,
            "historical_replay_counts_as_forward": False,
        },
        "statistical_contract": {"definition": copy.deepcopy(statistical), "definition_sha256": "0" * 64},
        "dependency_components": copy.deepcopy(dependencies),
        "dependent_experiment_ids": list(dependents),
        "epoch_restart_conditions": {
            "baseline_definition_change": True,
            "candidate_definition_change": True,
            "pit_forward_contract_change": True,
            "statistical_contract_change": True,
            "dependency_component_baseline_change": True,
        },
        "allowed_configuration_path": allowed_path,
        "identity_sha256": "0" * 64,
        "boundary": {
            "comparison_only": True,
            "automatic_adjudication_recommendation_only": True,
            "automatic_production_config_write": False,
            "shared_business_ledger": False,
        },
    }
    return json.loads(_sealed_admission_from_payload(
        _canonical(payload), trusted_arm_inventory(experiment_id), _sealing_cache_context()
    ))


def _sealing_cache_context() -> tuple[bytes, int, int]:
    """Bind memoized admissions to the live schema and sealing entry points."""
    try:
        schema_source = governance.ADMISSION_SCHEMA_PATH.read_bytes()
    except OSError as exc:
        raise AdmissionRegistryError(
            "cannot read admission schema for sealed registry cache: "
            f"{governance.ADMISSION_SCHEMA_PATH.name}"
        ) from exc
    return schema_source, id(seal_experiment_admission), id(validate_experiment_admission)


@lru_cache(maxsize=32)
def _sealed_admission_from_payload(payload_source: str,
                                   trusted_inventory: tuple[str, str] | None,
                                   sealing_context: tuple[bytes, int, int]) -> str:
    """Seal and validate one immutable admission per exact payload and live context."""
    del trusted_inventory, sealing_context  # Both bind the cache key; validation reads live inventory/schema.
    sealed = seal_experiment_admission(json.loads(payload_source))
    validate_experiment_admission(sealed)
    return _canonical(sealed)


def _dependency(component_id: str, definition: Any) -> dict:
    return {"component_id": component_id, "baseline_definition_sha256": _digest(definition)}


def _p0_admissions() -> dict[str, dict]:
    v2 = _load(ROOT / "presets" / "a_short_factor_comparison_v2_governance_20260718.json")
    legacy = _load(ROOT / "presets" / "a_short_factor_comparison_governance_20260714.json")
    factor_map = {row["factor_id"]: row for row in legacy.get("factor_registry") or []}
    common = {
        "program": v2["program_id"], "baseline": v2["baseline"],
        "outcome": v2["outcome_contract"], "adjustment": v2["adjustment_contract"],
        "risk": v2["risk_evidence"], "formal": v2["formal_adjudication_contract"],
        "adjudication": v2["adjudication_contract"],
    }
    deps = [
        _dependency("pit_candidate_universe", {"common_pool": "same_pit_candidate_universe_after_non_iv_immutable_hard_gates"}),
        _dependency("qfq_price_identity", {"adjustment_contract": v2["adjustment_contract"]}),
        _dependency("execution_cost_contract", v2["outcome_contract"]),
    ]
    admissions: dict[str, dict] = {}
    for question in v2["questions"]:
        baseline = next(arm for arm in question["arms"] if arm["kind"] == "baseline")
        for arm in question["arms"]:
            if arm["kind"] != "challenger":
                continue
            factor_id = arm.get("factor_id")
            if factor_id not in factor_map:
                raise AdmissionRegistryError(f"P0 arm {arm['arm_id']} has no frozen single-factor definition")
            admission_id = f"p0_{question['question_id']}_{arm['arm_id']}"
            admissions[admission_id] = _admission(
                program_id=v2["program_id"], experiment_id=f"a_short_{admission_id}", track_mode="switchable",
                component_id=f"factor_{factor_id}", effect_surface=question["effect_surface"],
                baseline={"arm_id": baseline["arm_id"], "policy": common},
                candidate={"arm_id": arm["arm_id"], "factor": factor_map[factor_id], "policy": common},
                pit_forward={"live_canonical_only": True, "run_date_real": True,
                             "decision_date_canonical": True, "price_basis": v2["outcome_contract"]["price_basis"],
                             "source_receipt_required": True},
                statistical={"question_id": question["question_id"], "multiplicity_family": question["multiplicity_family_id"],
                             "formal": v2["formal_adjudication_contract"], "adjudication": v2["adjudication_contract"]},
                dependencies=deps, dependents=["a_short_p4_stage3_rank_source"],
                allowed_path=f"presets/a_short_factor_comparison_v2_governance_20260718.json#/questions/{question['question_id']}/arms/{arm['arm_id']}",
            )
    return admissions


def _p1_admission() -> dict:
    gov = _load(ROOT / "presets" / "a_short_regime_action_comparison_governance_20260714.json")
    policy = gov["candidate_effect_policy"]
    return _admission(
        program_id="a_short_regime_candidate_effect", experiment_id="a_short_p1_regime_action_proxy",
        track_mode="diagnostic_only", component_id="regime_action_proxy_policy",
        effect_surface="v14_3_proxy_action_vs_current_baseline",
        baseline={"arm_id": "current_build", "description": policy["baseline_description"]},
        candidate={"arm_id": "v14_3_proxy", "description": policy["candidate_proxy_description"],
                   "action_matrix": gov["action_matrix"]},
        pit_forward={"live_canonical_only": True, "m67_receipt_required": True, "tracker_forward_live_required": True,
                     "return_basis": {"unit": policy["return_unit"], "cost": policy["return_cost_basis"], "benchmark": policy["benchmark"]}},
        statistical={"primary_window": "h10", "mean_improvement_pp_min": policy["practical_improvement_pp_min"],
                     "favorable_week_ratio_min": policy["favorable_weeks_ratio_min"], "weekly_median_improvement_pp": ">0",
                     "h20_must_not_reverse_worsen": True, "minimums": {"forward_weeks": 12, "divergence_weeks": 8, "evaluable_objects": 20}},
        dependencies=[_dependency("v14_2_baseline_policy", {"baseline": gov["baseline_policy_id"], "epoch": gov["baseline_policy_epoch"]}),
                      _dependency("candidate_universe", {"row_source": policy["eligible_row_source"], "m67_action": policy["eligible_m67_action"]}),
                      _dependency("csi1000_benchmark", policy["benchmark"])],
        dependents=["a_short_v14_3_formal_production_policy"], allowed_path="presets/a_short_regime_action_comparison_governance_20260714.json#/candidate_effect_policy",
    )


def _p2_admissions() -> dict[str, dict]:
    common = {"horizons": [5, 10, 20], "entry": "t_plus_1_open", "cost_pct": 0.16,
              "price_basis": "qfq_provider_observed", "forward_only": True}
    target_deps = [_dependency("published_m67_bundle", "source_receipt_and_run_identity"),
                   _dependency("target_exit_baseline", "official_t1_t2_managed_exit"),
                   _dependency("managed_exit_contract", "engine.a_short_managed_exit"),
                   _dependency("qfq_price_identity", common)]
    breakout_deps = [_dependency("published_m67_bundle", "source_receipt_and_run_identity"),
                     _dependency("breakout_entry_baseline", "legacy_momentum_confirmed"),
                     _dependency("managed_exit_contract", "same_frozen_exit_plan_after_entry_qualification"),
                     _dependency("qfq_price_identity", common)]
    target = _admission(
        program_id="a_short_target_policy_comparison", experiment_id="a_short_p2_target_exit_policy",
        track_mode="switchable", component_id="target_exit_policy", effect_surface="target_exit_policy",
        baseline={"arm_id": "legacy_target_exit", "policy": "frozen_official_t1_t2"},
        candidate={"arm_id": "true_pressure_target_exit", "policy": "true_pressure_targets_and_managed_exit"},
        pit_forward=common,
        statistical={"minimums": {"forward_weeks": 12, "difference_weeks": 8, "evaluable_plans": 20},
                     "primary_window": "h20", "mean_net_improvement_pp_min": 0.30, "weekly_median": ">0",
                     "favorable_week_ratio_min": 0.60, "max_drawdown_worsening_pp_max": 2.0,
                     "h5_h10_not_both_materially_adverse": True, "formal_adjudication_implemented": True},
        dependencies=target_deps, dependents=["a_short_p3_managed_exit_vs_hold", "a_short_p3_managed_exit_vs_csi1000"],
        allowed_path="A-EGS/egs_main.py#/target_exit_policy",
    )
    breakout = _admission(
        program_id="a_short_target_policy_comparison", experiment_id="a_short_p2_breakout_entry_policy",
        track_mode="switchable", component_id="breakout_entry_policy", effect_surface="breakout_entry_policy",
        baseline={"arm_id": "momentum_confirmed", "policy": "legacy_momentum_confirmed"},
        candidate={"arm_id": "true_breakout", "policy": "true_breakout_qualification"}, pit_forward=common,
        statistical={"minimums": {"forward_weeks": 12, "difference_weeks": 8, "evaluable_plans": 20},
                     "primary_window": "h20", "reports": ["new_old_entry_week_portfolios", "excluded_vs_csi1000", "missed_large_moves", "risk_outcomes"],
                     "formal_adjudication_implemented": False},
        dependencies=breakout_deps, dependents=["a_short_p2_breakout_policy_followup"], allowed_path="A-EGS/egs_main.py#/breakout_entry_policy",
    )
    return {"p2_target_exit_policy": target, "p2_breakout_entry_policy": breakout}


def _p3_admissions() -> dict[str, dict]:
    common = {"primary_window": "h20", "diagnostic_windows": ["h5", "h10"], "cost_pct": 0.16,
              "week_unit": "one_equal_weighted_weekly_portfolio", "forward_only": True}
    deps = [_dependency("model_selection_definition", "model_build_eligible"),
            _dependency("candidate_cohort", "published_forward_tracker_cohort"),
            _dependency("qfq_price_identity", common)]
    stats = {"primary_window": "h20", "hac": {"method": "newey_west", "maxlags": 4, "t_min": 2.0},
             "minimums": {"full_edge_forward_weeks": 26, "mature_managed_plans": 20},
             "operation": {"mean_improvement_pp_min": 0.30, "median": ">0", "favorable_week_ratio_min": 0.60,
                           "max_drawdown_worsening_pp_max": 2.0}, "formal_hac_adjudication_implemented": True}
    definitions = (
        ("p3_selected_vs_candidate_pool", "selected_set_vs_candidate_pool", "model_selection_policy", "candidate_pool_hold"),
        ("p3_selected_vs_csi1000", "selected_set_vs_csi1000", "model_selection_policy", "csi1000_hold"),
        ("p3_managed_exit_vs_hold", "managed_exit_vs_simple_hold", "managed_exit_policy", "simple_hold"),
    )
    return {
        key: _admission(program_id="a_short_final_action_validation", experiment_id=f"a_short_{key}",
                        track_mode="diagnostic_only", component_id=component, effect_surface=surface,
                        baseline={"arm_id": baseline, "comparison": baseline},
                        candidate={"arm_id": "selected_or_managed", "comparison": surface}, pit_forward=common,
                        statistical=stats, dependencies=deps, dependents=["a_short_p3b_public_overview"],
                        allowed_path=f"A-EGS/egs_main.py#/{component}")
        for key, surface, component, baseline in definitions
    }


def _p5_admissions() -> dict[str, dict]:
    gov = _load(ROOT / "presets" / "a_short_industry_weight_comparison_governance_20260722.json")
    common = {"outcome": gov["outcome_contract"], "clock": gov["clock_contract"],
              "statistics": gov["risk_and_statistics_contract"]}
    deps = [_dependency("profile_watch_pool_selector", gov["selection_contract"]),
            _dependency("pit_candidate_universe", "same_egs_universe"),
            _dependency("qfq_price_identity", gov["outcome_contract"])]
    admissions = {}
    for question in gov["questions"]:
        key = f"p5_{question['question_id']}"
        admissions[key] = _admission(
            program_id=gov["program_id"], experiment_id=f"a_short_{key}", track_mode="switchable",
            component_id="industry_weight_profile", effect_surface="industry_weight_profile",
            baseline={"arm_id": question["baseline"], "profile_weights": gov["profiles"][question["baseline"]]},
            candidate={"arm_id": question["challenger"], "profile_weights": gov["profiles"][question["challenger"]]},
            pit_forward={"live_canonical_only": True, "official_publish_marker_required": True,
                         "qfq_provider_observed_only": True, "outcome": gov["outcome_contract"]},
            statistical={
                "question_id": question["question_id"],
                **common,
                # Knife 8D0: frozen P5b governance only.  The P5b adjudicator
                # and its public surface remain 8D1 work.
                "p5b_adjudication_governance": {
                    "p_value_method": "engine.a_short_overlay_adjudication._signflip_p",
                    # The phase names are the 8D0 decision.  Numeric clock
                    # gates remain solely in the preset clock contract above.
                    "checkpoint_stages": {"12": "preliminary", "24": "formal", "36": "terminal"},
                },
            }, dependencies=deps,
            dependents=["a_short_p4_stage3_rank_source"],
            allowed_path="presets/egs_industry_heat_governance_20260611.json#/active_profile",
        )
    return admissions


def _p4_admission() -> dict:
    """The P4a rank-source comparison is one switchable, bounded component.

    It deliberately does not reuse the older overlay sidecar's evidence.  The
    P4a runner binds a newly published EGS/Stage3/M6.7 bundle before it starts
    a fresh epoch, while this registry seals the business boundary that makes
    that runner's evidence interpretable.
    """
    outcome = {
        "entry": "t_plus_1_open", "windows": [5, 10, 20], "primary_window": "h10",
        "price_basis": "qfq_provider_observed", "round_trip_cost_pct": 0.16,
        "fixed_slots": 5, "equal_slot_pct": 20.0, "cash_not_reallocated": True,
        "benchmarks": ["csi1000", "csi300"],
    }
    statistical = {
        "eligible_checkpoints": [12, 24, 36], "difference_minimums": {"12": 6, "24": 12, "36": 18},
        "nonoverlap_block_minimums": {"12": 6, "24": 12, "36": 12},
        "nonoverlap": {"window": "h10", "strict_entry_after_prior_exit": True},
        "preliminary": {"mean_delta_pp_min": 0.25, "block_win_rate_min": 0.55,
                          "negative_mean_delta_pp_max": -0.25},
        "promotion": {"mean_delta_pp_min": 0.25, "bootstrap_lower_pp_min": 0.25,
                      "signflip_p_max": 0.025, "monthly_cluster_t_min": 2.0,
                      "minimum_months": 6, "adjustment_coverage_pct": 100.0,
                      "no_count_rate_pct_max": 20.0, "h20_required_at_24_36": True},
        "risk": {"close_drawdown_pct_max": 15.0, "drawdown_worsening_pp_max": 2.0,
                 "bad_ticket_rate_pct_max": 35.0, "bad_ticket_delta_pp_max": 5.0,
                 "tail_h10_pct_min": -10.0, "tail_worsening_pp_max": 2.0,
                 "false_negative_delta_pp_max": 5.0, "cash_drag_pct_max": 50.0,
                 "unfilled_rate_pct_max": 50.0},
        "negative_at_36": {"mean_delta_pp_max": -0.25, "bootstrap_upper_pp_max": 0.0},
        "automatic_production_write": False,
    }
    # Written in the direct `_load(ROOT / ...)` form on purpose: the authority
    # guard reads call sites statically and treats indirection as unreadable.
    governance = _load(ROOT / "presets" / "egs_industry_heat_governance_20260611.json")
    governance_path = ROOT / "presets" / "egs_industry_heat_governance_20260611.json"
    try:
        active_profile = str(governance["active_profile"])
        active_weights = governance["profiles"][active_profile]
    except (KeyError, TypeError) as exc:
        raise AdmissionRegistryError("P4 active industry profile is malformed") from exc
    if not isinstance(active_weights, dict) or not active_weights:
        raise AdmissionRegistryError("P4 active industry profile weights are malformed")
    active_profile_dependency = {
        "governance_path": str(governance_path.relative_to(ROOT)),
        "governance_sha256": industry_heat.canonical_governance_digest(governance_path),
        "active_profile": active_profile,
        "weights": active_weights,
    }
    dependencies = [
        _dependency("active_industry_weight_profile", active_profile_dependency),
        _dependency("official_watch_pool_selector", "engine.egs_industry_heat.select_profile_watch_pool"),
        _dependency("stage3_eligibility_builder", "A-EGS/egs_main.py#stage3_ai_clearing_pre_rank_filters"),
        _dependency("stage3_l1_l2_concentration", {"l1_max": 0.4, "l2_max": 0.3, "top_k": 5}),
        _dependency("top5_selector", "A-EGS/egs_main.py#stage3_ai_clearing._finalize_stage3"),
        _dependency("overlay_scorer_contract", "schemas/a_short_theme_overlay_comparison.schema.json@1.0.0"),
        _dependency("pit_qfq_price_identity", outcome),
    ]
    return _admission(
        program_id="a_short_overlay_adjudication_p4a", experiment_id="a_short_p4_stage3_rank_source",
        track_mode="switchable", component_id="stage3_rank_source", effect_surface="official_stage3_top5_rank_source",
        baseline={"arm_id": "final_score", "rank_source": "final_score", "selector": "frozen_stage3_top5"},
        candidate={"arm_id": "overlay_score", "rank_source": "overlay_score", "selector": "frozen_stage3_top5"},
        pit_forward={"live_canonical_only": True, "official_egs_publish_marker_required": True,
                     "official_m67_publish_receipt_required": True, "same_run_stage3_snapshot_required": True,
                     "forward_only": True, "outcome": outcome},
        statistical=statistical, dependencies=dependencies, dependents=["a_short_p4b_portfolio_overlay_activation"],
        allowed_path="A-EGS/egs_main.py#/stage3_rank_source",
    )


#: Every file `admissions()` reads.  The registry cache below keys on these
#: exact bytes (plus the sealing context), so an edited preset re-runs the full
#: revalidation instead of ever returning a stale registry.  Adding a `_load`
#: to a builder without extending this tuple would break that authority;
#: `tests/test_a_short_experiment_admission_registry.py::
#: AdmissionSourcePresetGuardTests` pins this module's `_load(ROOT / ...)`
#: call sites to exactly this list and fails loudly on shapes it cannot read.
_ADMISSION_SOURCE_PRESETS = (
    "presets/a_short_factor_comparison_v2_governance_20260718.json",
    "presets/a_short_factor_comparison_governance_20260714.json",
    "presets/a_short_regime_action_comparison_governance_20260714.json",
    "presets/a_short_industry_weight_comparison_governance_20260722.json",
    # The guard exposed this fifth read the original enumeration missed: the
    # P4 builder loads the industry-heat governance behind a variable, so an
    # edit to it would have silently kept serving the stale cached registry.
    "presets/egs_industry_heat_governance_20260611.json",
)


def _registry_authority_key() -> tuple:
    """The complete external input of `admissions()`, as content, for caching."""
    reads = []
    for rel in _ADMISSION_SOURCE_PRESETS:
        try:
            reads.append((rel, (ROOT / rel).read_bytes()))
        except OSError as exc:
            raise AdmissionRegistryError(f"cannot read frozen admission source {rel}") from exc
    return tuple(reads) + (_sealing_cache_context(),)


@lru_cache(maxsize=4)
def _cached_registry(authority_key: tuple) -> dict[str, dict]:
    """One fully revalidated registry per exact byte-content of its inputs.

    Comparison-track fingerprints call `admission_snapshot` per record, and the
    uncached build re-sealed and re-parsed every admission each time -- ~36ms a
    call, one of the two largest sinks in the whole A-short lane by profile.
    The key holds the raw bytes of everything the build reads, so this is the
    same revalidation, just not repeated for identical inputs.  The returned
    object is shared and read-only inside this module; public callers get
    copies.
    """
    del authority_key  # binds the cache key; the builders below re-read live
    out = {}
    for source in (_p0_admissions(), {"p1_regime_action_proxy": _p1_admission()}, _p2_admissions(), _p3_admissions(),
                   {"p4_stage3_rank_source": _p4_admission()}, _p5_admissions()):
        overlap = set(out) & set(source)
        if overlap:
            raise AdmissionRegistryError(f"duplicate admission id: {sorted(overlap)}")
        out.update(source)
    return out


def admissions() -> dict[str, dict]:
    """Return every active P0/P1/P2/P3/P4/P5 admission, fully revalidated."""
    return copy.deepcopy(_cached_registry(_registry_authority_key()))


def get_admission(admission_id: str) -> dict:
    try:
        return copy.deepcopy(_cached_registry(_registry_authority_key())[admission_id])
    except KeyError as exc:
        raise AdmissionRegistryError(f"unknown active admission {admission_id!r}") from exc


def admission_snapshot(*admission_ids: str) -> dict[str, dict]:
    """Public-safe identity data used by a lane's private epoch and public summary."""
    registry = _cached_registry(_registry_authority_key())
    selected = {}
    for admission_id in admission_ids:
        admission = registry.get(admission_id)
        if admission is None:
            raise AdmissionRegistryError(f"unknown active admission {admission_id!r}")
        selected[admission_id] = {
            "experiment_id": admission["experiment_id"], "component_id": admission["component_id"],
            "track_mode": admission["track_mode"], "identity_sha256": admission["identity_sha256"],
            "statistical_contract_sha256": admission["statistical_contract"]["definition_sha256"],
            "pit_forward_contract_sha256": admission["pit_forward_contract"]["contract_sha256"],
            "dependency_components": copy.deepcopy(admission["dependency_components"]),
        }
    return selected


@lru_cache(maxsize=64)
def _snapshot_sha256_from_authority(admission_ids: tuple[str, ...], authority_key: tuple) -> str:
    del authority_key  # binds the cache key; the snapshot reads the cached registry
    return _digest(admission_snapshot(*admission_ids))


def admission_snapshot_sha256(*admission_ids: str) -> str:
    return _snapshot_sha256_from_authority(tuple(admission_ids), _registry_authority_key())


def p3b_external_comparison_tracks() -> tuple[dict[str, Any], ...]:
    """Frozen P3b external-track roster and implementation predicates.

    A track with no implemented adjudicator has no vote.  Keep this control
    plane here rather than in P3's consumer so adding a future track cannot
    silently change P3b semantics.
    """
    registry = admissions()
    from engine.a_short_industry_weight_adjudication import P5B_IMPLEMENTED
    return (
        {"track_id": "p1_regime_candidate_effect",
         "public_summary_path": "research/results/a_short/regime_candidate_effect_summary.json",
         "implementation": {"kind": "constant", "value": True},
         "public_verdict_contract": {"terminal_verdicts": ("candidate_better", "baseline_better", "no_material_difference")}},
        {"track_id": "p2_target_exit_policy",
         "public_summary_path": "research/results/a_short/target_policy_comparison_summary.json",
         "implementation": {"kind": "admission_statistical_flag", "admission_id": "p2_target_exit_policy",
                            "flag": "formal_adjudication_implemented",
                            "value": bool(registry["p2_target_exit_policy"]["statistical_contract"]["definition"]["formal_adjudication_implemented"])},
         "public_verdict_contract": {"terminal_verdicts": ("edge_positive", "edge_not_supported")}},
        {"track_id": "p5_industry_weight",
         "public_summary_path": "research/results/a_short/industry_weight_comparison_summary.json",
         "implementation": {"kind": "adjudicator_public_surface", "module": "engine.a_short_industry_weight_adjudication",
                            "flag": "p5b_implemented", "value": bool(P5B_IMPLEMENTED)},
         "public_verdict_contract": {"terminal_verdicts": ("retain_balanced_only", "next_reviewed_candidate_only", "manual_rollback_review_only", "do_not_promote"),
                                     "terminal_stage_field": "adjudication_stage", "terminal_stage_value": "terminal"}},
    )
