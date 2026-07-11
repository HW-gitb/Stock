# -*- coding: utf-8 -*-
"""US-short A1 live shadow selection-policy heads.

Consumes the already validated, PIT-frozen score composition from
``compose_score_inputs`` and builds deterministic, shadow-only selection inputs
for the policy grid. It fetches nothing and cannot change the primary track.

The current cut implements the six decision-time selection policies. The
seventh policy (``overextension_execution_off``) is a second-wave-live slot:
it begins only when a later shadow branch ledger exists and is not silently
approximated or replayed here.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from engine.us_short_core_score import CORE_COMPONENTS, PRIMARY_PROFILE, core_score
from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_overextension import validate_overextension_result
from engine.us_short_risk_downgrade import validate_risk_downgrade_input
from engine.us_short_weekend_pipeline import run_selection


ROOT = Path(__file__).resolve().parent.parent
GRID_PATH = ROOT / "presets" / "us_short_forward_policy_grid_20260711.json"
_GRID = json.loads(GRID_PATH.read_text(encoding="utf-8"))

SELECTION_POLICY_IDS = tuple(_GRID["selection_policies"])
SECOND_WAVE_LIVE_POLICY_IDS = tuple(_GRID["second_wave_live_policies"])
_POLICIES = _GRID["policies"]
_CATALYST_OFF_WEIGHTS = _POLICIES["catalyst_off"]["score_weights"]
_EXPECTED_SELECTION_POLICY_IDS = (
    "balanced", "theme_plus", "theme_aggressive", "theme_off",
    "catalyst_off", "overextension_selection_off",
)


class ForwardPolicyHeadError(ValueError):
    """A frozen score composition or policy-grid invariant is invalid."""


def _assert_grid() -> None:
    if tuple(SELECTION_POLICY_IDS) != _EXPECTED_SELECTION_POLICY_IDS:
        raise ForwardPolicyHeadError("forward policy grid selection policy set/order drifted")
    if tuple(SECOND_WAVE_LIVE_POLICY_IDS) != ("overextension_execution_off",):
        raise ForwardPolicyHeadError("forward policy grid second-wave-live policy set/order drifted")
    if _GRID.get("primary_policy") != PRIMARY_PROFILE:
        raise ForwardPolicyHeadError("forward policy grid primary must match core-score primary")
    if set(_CATALYST_OFF_WEIGHTS) != set(CORE_COMPONENTS):
        raise ForwardPolicyHeadError("catalyst_off weights must exactly cover core components")
    if not math.isclose(sum(_CATALYST_OFF_WEIGHTS.values()), 1.0, abs_tol=1e-12):
        raise ForwardPolicyHeadError("catalyst_off weights must sum to one")
    if _CATALYST_OFF_WEIGHTS != {
        "momentum": 0.5333333333333333,
        "theme": 0.4666666666666667,
        "catalyst": 0.0,
    }:
        raise ForwardPolicyHeadError("catalyst_off weights drifted from the frozen 40:35 reallocation")


_assert_grid()


def _exact_dict(value, *, where: str) -> dict:
    if type(value) is not dict:
        raise ForwardPolicyHeadError(f"{where} must be an exact dict")
    return value


def _canonical_targets(value) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ForwardPolicyHeadError("score composition target_tickers must be a non-empty list")
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        ticker = canonical_us_ticker(raw)
        if ticker is None or ticker != raw or ticker in seen:
            raise ForwardPolicyHeadError("target_tickers must be unique canonical US tickers")
        seen.add(ticker)
        out.append(ticker)
    return tuple(out)


def _finite_score(value, *, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ForwardPolicyHeadError(f"{where} must be a finite numeric score")
    out = float(value)
    if not 0.0 <= out <= 100.0:
        raise ForwardPolicyHeadError(f"{where} must be in 0..100")
    return out


def _validated_composition(score_composition):
    comp = _exact_dict(score_composition, where="score_composition")
    expected = {
        "selection_inputs", "analysis_by_ticker", "coverage_by_ticker",
        "target_tickers", "scoring_profile", "scored_component_counts",
    }
    if set(comp) != expected:
        raise ForwardPolicyHeadError("score_composition must be the closed-world compose_score_inputs output")
    if comp["scoring_profile"] != PRIMARY_PROFILE:
        raise ForwardPolicyHeadError("A1 forward policy heads require the frozen balanced primary composition")
    targets = _canonical_targets(comp["target_tickers"])
    analysis = _exact_dict(comp["analysis_by_ticker"], where="analysis_by_ticker")
    selection = _exact_dict(comp["selection_inputs"], where="selection_inputs")
    if set(selection) != {"theme_opportunity_state", "per_ticker"}:
        raise ForwardPolicyHeadError("selection_inputs must have the canonical two keys")
    rows = _exact_dict(selection["per_ticker"], where="selection_inputs.per_ticker")
    if set(analysis) != set(targets) or set(rows) != set(targets):
        raise ForwardPolicyHeadError("score composition analysis/selection rows must exactly cover targets")
    for ticker in targets:
        analysis_row = _exact_dict(analysis[ticker], where=f"analysis_by_ticker[{ticker}]")
        if set(analysis_row) != {"score_blocks", "risk_downgrade", "scoring_profile"}:
            raise ForwardPolicyHeadError(f"analysis_by_ticker[{ticker}] drifted from compose contract")
        _exact_dict(analysis_row["score_blocks"], where=f"analysis_by_ticker[{ticker}].score_blocks")
        try:
            validate_risk_downgrade_input(analysis_row["risk_downgrade"])
        except ValueError as exc:
            raise ForwardPolicyHeadError(f"analysis_by_ticker[{ticker}] risk downgrade is invalid") from exc
        row = _exact_dict(rows[ticker], where=f"selection_inputs.per_ticker[{ticker}]")
        if set(row) != {"core_score", "theme_momentum_score"}:
            raise ForwardPolicyHeadError(f"selection_inputs.per_ticker[{ticker}] drifted from selection contract")
        _finite_score(row["core_score"], where=f"selection_inputs[{ticker}].core_score")
        _finite_score(row["theme_momentum_score"], where=f"selection_inputs[{ticker}].theme_momentum_score")
    return comp, targets, analysis, selection


def _validated_stripped_targets(overextension_by_ticker, targets: tuple[str, ...]) -> set[str]:
    rows = _exact_dict(overextension_by_ticker, where="overextension_by_ticker")
    if set(rows) != set(targets):
        raise ForwardPolicyHeadError("overextension_by_ticker must exactly cover score-composition targets")
    out: set[str] = set()
    for ticker in targets:
        record = _exact_dict(rows[ticker], where=f"overextension_by_ticker[{ticker}]")
        try:
            validate_overextension_result(record)
        except ValueError as exc:
            raise ForwardPolicyHeadError(f"overextension_by_ticker[{ticker}] is invalid") from exc
        if record["strips_theme_score"] is True:
            out.add(ticker)
    return out


def _normalized_score_inputs(analysis_row: dict, *, profile: str, strip_theme_score: bool = False):
    risk = validate_risk_downgrade_input(analysis_row["risk_downgrade"])
    score = core_score(
        analysis_row["score_blocks"], profile=profile,
        risk_downgrade_points=risk["points"], strip_theme_score=strip_theme_score,
    )
    return score, risk


def _theme_seat_score(score: dict, *, strip: bool, policy_id: str) -> float:
    if strip or _POLICIES[policy_id]["theme_momentum_seat"] == "zero":
        return 0.0
    if "theme" in score["missing_blocks"]:
        return 0.0
    return _finite_score(score["blocks_used"]["theme"], where=f"{policy_id}.theme_momentum_score")


def _score_for_policy(policy_id: str, analysis_row: dict, *, stripped: bool) -> tuple[float, float]:
    policy = _POLICIES[policy_id]
    strip = stripped and policy["overextension_selection_strip"] == "retain"
    if policy_id == "overextension_selection_off":
        strip = False
    if policy_id == "catalyst_off":
        # catalyst_off keeps its 40:35 pro-rata weights; a chasing strip removes ONLY the theme
        # contribution with NO reallocation — mirroring core_score(strip_theme_score=True) / §4.3:
        # a penalty must never raise the score by moving theme weight onto momentum.
        base_score, _ = _normalized_score_inputs(analysis_row, profile=PRIMARY_PROFILE)
        used = base_score["blocks_used"]
        raw = sum(_CATALYST_OFF_WEIGHTS[name] * used[name] for name in CORE_COMPONENTS)
        if strip:
            raw -= _CATALYST_OFF_WEIGHTS["theme"] * used["theme"]
        core = max(0.0, raw - base_score["risk_downgrade"])
        return core, _theme_seat_score(base_score, strip=strip, policy_id=policy_id)
    # Scoring-profile heads strip a chasing ticker's theme via strip_theme_score on THIS profile
    # (no reallocation), matching the real balanced selection track; theme_off's reallocation is
    # reserved for the dedicated theme_off shadow-attribution head only (§12.2).
    score, _ = _normalized_score_inputs(analysis_row, profile=policy["score_profile"], strip_theme_score=strip)
    return score["core_score"], _theme_seat_score(score, strip=strip, policy_id=policy_id)


def build_selection_policy_heads(score_composition, *, overextension_by_ticker) -> dict:
    """Return every A1 immediate selection head from one frozen primary composition.

    The output maps policy id to the exact ``selection_inputs`` shape consumed by
    ``run_selection``. It contains no outcome, paper ledger, or provider data;
    the live caller must record it as its shadow output at the decision time.
    """
    _, targets, analysis, selection = _validated_composition(score_composition)
    stripped_targets = _validated_stripped_targets(overextension_by_ticker, targets)
    heads: dict[str, dict] = {}
    for policy_id in SELECTION_POLICY_IDS:
        per_ticker: dict[str, dict[str, float]] = {}
        for ticker in targets:
            core, theme = _score_for_policy(policy_id, analysis[ticker], stripped=ticker in stripped_targets)
            per_ticker[ticker] = {"core_score": core, "theme_momentum_score": theme}
        heads[policy_id] = {
            "theme_opportunity_state": selection["theme_opportunity_state"],
            "per_ticker": per_ticker,
        }
    return heads


def build_selection_policy_decisions(*, now_et, sessions, data_context, eligibility_governance,
                                     score_composition, overextension_by_ticker) -> dict:
    """Run the existing deterministic selection engine once per immediate A1 head.

    This is pure local policy branching: each invocation deep-copies the caller's
    frozen context, replaces only ``selection_inputs``, and delegates all
    eligibility, Pass2 veto, dynamic-seat, and tie-break semantics to the single
    authoritative ``run_selection`` engine.
    """
    heads = build_selection_policy_heads(score_composition, overextension_by_ticker=overextension_by_ticker)
    decisions: dict[str, dict] = {}
    for policy_id, selection_inputs in heads.items():
        context = copy.deepcopy(data_context)
        context["selection_inputs"] = selection_inputs
        decisions[policy_id] = run_selection(
            now_et, sessions, context, eligibility_governance=eligibility_governance,
        )
    return {"selection_heads": heads, "selection_decisions": decisions}
