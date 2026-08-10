# -*- coding: utf-8 -*-
"""Thin stage adapters for the weekly capstone orchestrator — map a CapstoneContext to each real stage runner.

Kept separate from `us_short_weekly_capstone` so the orchestrator's dry-run and injected-fake tests need not import
a provider runner they will not call. Each adapter is a THIN mapping (context → real runner kwargs) — the real
runners own ALL fetch / PIT / selection / scoring logic; this file adds none.

DRAFT wiring status: mapped against the 2026-07-08 stage signature contract. The OFFLINE adapters (producer /
theme / projection-inputs / preflight / bridge) are exercised by the orchestrator's fake-stage tests only insofar
as the framework calls them; the GATED adapters (universe / momentum-fetch / SIC-fetch / Pass2) perform live
provider fetches and get their FIRST real exercise on the next fresh-quota run — they cannot be network-tested
offline, so treat their exact kwargs/paths as draft until that run confirms them.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import jsonschema
from engine.us_short_eligibility_gate import load_eligibility_governance
from engine.us_short_forward_policy_comparison_ledger import (
    comparison_banner_from_private_ledger_path,
    empty_forward_policy_comparison_ledger,
    persist_source_bound_forward_policy_week,
)
from engine.us_short_forward_policy_shadow_stage import materialize_forward_policy_shadow
from engine.us_short_forward_policy_private_week import (
    ForwardPolicyPrivateWeekError,
    validate_forward_policy_private_week_record,
)
from engine.us_short_forward_policy_source_capture import (
    ForwardPolicySourceCaptureError,
    materialize_forward_policy_source_capture,
    materialize_forward_policy_source_maturity,
    validate_forward_policy_source_capture,
)
from engine.us_short_market_calendar import load_market_calendar, sessions_for_window
from engine.us_short_run_origin import require_research_live_provider_summary
from engine.us_short_soft_boost_comparison_adjudication import (
    SoftBoostComparisonAdjudicationError, append_pairwise_capture, apply_maturity_observations,
    build_adjudication_receipt, build_pairwise_capture, evaluate_pairwise_ledger, persist_pairwise_ledger,
    read_pairwise_ledger,
)
from engine import us_short_soft_boost_consumption as _soft_boost_consumption
from engine.us_short_forward_policy_source_capture import _validated_ohlcv_packet
from engine.us_short_regime import REGIMES, UNKNOWN
from runners import us_short_batch5_full_candidate_live_source_packet as _pass2
from runners import us_short_batch5_full_candidate_pass2_preflight as _preflight
from runners import us_short_batch5_full_candidate_projection_inputs as _proj
from runners import us_short_batch5_full_universe_momentum_fetch as _mom_fetch
from runners import us_short_batch5_full_universe_momentum_producer as _mom_prod
from runners import us_short_batch5_full_universe_overextension_producer as _overextension
from runners import us_short_batch5_full_universe_sec_sic_classification_fetch as _sic
from runners import us_short_batch5_full_universe_theme_producer as _theme
from runners import us_short_batch5_to_batch4_weekend_e2e as _bridge
from runners import us_short_universe_fetch as _universe
from runners import us_short_yfinance_grades_fetch as _yfinance_grades
from runners import us_short_vix_regime_fetch as _vix
from runners.us_short_account_state_from_manual_tables import validate_account_state


ROOT = Path(__file__).resolve().parents[1]
_ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
_CALENDAR_PATH = ROOT / "presets" / "us_short_market_calendar_2026_2027.json"


def _stage_summary_targets(ctx) -> dict[str, Path]:
    """The per-run summary sidecar EACH stage runner writes, keyed by stage. Each lands under the runner's OWN
    reviewed `provider_samples/<runner>/` root (referenced via the runner's exported constant so it can NEVER drift
    from that runner's fail-closed allowlist), with a decision-date-keyed filename. These runners were built as
    one-shot MILESTONE runners whose only accepted summary paths are a fixed-date `docs/…` file or their own
    gitignored `provider_samples/…` folder; the capstone reuses them as repeatable weekly PIPELINE stages, so it must
    route their per-run summaries into that gitignored folder (a `state/us_short/…` summary is rejected by every one).
    `sample_root` is the repo root the runners resolve provider_samples against (tests inject a tempdir). The
    preflight summary is NOT here — it is `ctx.preflight_summary_path` (also stage-8's INPUT, so it lives where BOTH
    runners accept it)."""
    def _p(rel_root: Path, name: str) -> Path:
        return ctx.sample_root / rel_root / f"us_short_batch5_capstone_{ctx.decision_date}_{name}_summary.json"
    return {
        "momentum_fetch": _p(_mom_fetch.SUMMARY_SAMPLE_REL_ROOT, "momentum_fetch"),
        "momentum_producer": _p(_mom_prod.SAMPLE_REL_ROOT, "momentum_producer"),
        "overextension_producer": _p(_overextension.SAMPLE_REL_ROOT, "overextension_producer"),
        "sic_classification": _p(_sic.SUMMARY_SAMPLE_REL_ROOT, "sic_classification"),
        "theme_producer": _p(_theme.SAMPLE_REL_ROOT, "theme_producer"),
        "projection_inputs": _p(_proj.SAMPLE_REL_ROOT, "projection_inputs"),
        "yfinance_grades_fetch": _p(_yfinance_grades.RAW_REL_ROOT, "yfinance_grades_fetch"),
        "pass2": _p(_pass2.RAW_SAMPLE_REL_ROOT, "pass2"),
    }


# --- authorization propagation (R-USSHORT-REVIEWQ-CAT1 Required B) ---

def _require_ctx_authorization(ctx) -> None:
    """Fail-closed per-execution authorization propagation: a gated capstone adapter must CONSUME the run context's
    authorization and refuse BEFORE invoking its wrapped provider runner when it is false — never self-assert
    ``confirm_user_authorization=True``. The top-level capstone gate protects only the orchestrated path; a direct
    adapter call with an unauthorized ctx must not silently self-authorize the underlying SR-PROVIDER-001 fetch."""
    if getattr(ctx, "confirm_user_authorization", False) is not True:   # strict: a truthy non-True must not authorize
        raise PermissionError(
            "capstone gated stage requires ctx.confirm_user_authorization=True (per-execution SR-PROVIDER-001 "
            "authorization); refusing before any provider fetch")


def _account_holding_tickers(ctx) -> list[str]:
    frozen = getattr(ctx, "frozen_holding_tickers", None)
    if frozen is not None:
        return list(frozen)
    state = json.loads(Path(ctx.account_state_path).read_text(encoding="utf-8"))
    validate_account_state(state, ctx.decision_date)
    return sorted(position["ticker"] for position in state["positions"])


def _require_frozen_funnel_authorization(ctx, *, allow_budget_preview: bool = False) -> None:
    approval = getattr(ctx, "budget_approval", None)
    if approval is not None:
        try:
            approval_budget = approval.exact_pass2_calls
            approval_k = approval.momentum_top_k
        except AttributeError as exc:
            raise PermissionError("Pass2 budget approval is malformed") from exc
        if (
            type(approval_budget) is not int
            or isinstance(approval_budget, bool)
            or approval_budget < 1
            or type(approval_k) is not int
            or isinstance(approval_k, bool)
            or not 1 <= approval_k <= 250
            or ctx.authorized_pass2_call_budget != approval_budget
            or ctx.authorized_momentum_top_k != approval_k
        ):
            raise PermissionError("Pass2 budget approval does not match the frozen K and exact call budget")
        return
    k_is_valid = (
        type(getattr(ctx, "authorized_momentum_top_k", None)) is int
        and not isinstance(ctx.authorized_momentum_top_k, bool)
        and 1 <= ctx.authorized_momentum_top_k <= 250
    )
    budget_is_valid = (
        type(getattr(ctx, "authorized_pass2_call_budget", None)) is int
        and not isinstance(ctx.authorized_pass2_call_budget, bool)
        and ctx.authorized_pass2_call_budget >= 1
    )
    if allow_budget_preview and k_is_valid and (budget_is_valid or getattr(ctx, "pass2_budget_preview", False) is True):
        return
    raise PermissionError("Pass2 stages require the single frozen Pass2 budget approval (frozen K and exact call budget)")


def _require_budget_approval(ctx):
    approval = getattr(ctx, "budget_approval", None)
    from runners.us_short_weekly_capstone import Pass2BudgetApproval

    if not isinstance(approval, Pass2BudgetApproval):
        raise PermissionError(
            "downstream Pass2 stages require the finalized Pass2 budget approval (frozen K and exact call budget)"
        )
    _require_frozen_funnel_authorization(ctx)
    return approval


# --- GATED stages (live provider fetch; SR-PROVIDER-001) ---

def run_universe(ctx) -> dict[str, Any]:
    _require_ctx_authorization(ctx)
    return _universe.run_fetch(
        now_et=ctx.now_et,
        candidate_list_path=ctx.candidate_path,
        generated_at=ctx.generated_at,
        confirm_user_authorization=ctx.confirm_user_authorization,
        scan_bankruptcy_for_eligible=True,
    )


def run_momentum_fetch(ctx) -> dict[str, Any]:
    _require_ctx_authorization(ctx)
    return _mom_fetch.run_fetch(
        candidate_artifact_path=ctx.candidate_path,
        series_packet_path=ctx.series_packet_path,
        ohlcv_series_packet_path=ctx.ohlcv_series_packet_path,
        summary_path=_stage_summary_targets(ctx)["momentum_fetch"],
        generated_at=ctx.generated_at,
        confirm_user_authorization=ctx.confirm_user_authorization,
    )


def run_sic_fetch(ctx) -> dict[str, Any]:
    _require_ctx_authorization(ctx)
    return _sic.run_fetch(
        candidate_artifact_path=ctx.candidate_path,
        classification_packet_path=ctx.classification_packet_path,
        summary_path=_stage_summary_targets(ctx)["sic_classification"],
        generated_at=ctx.generated_at,
        confirm_user_authorization=ctx.confirm_user_authorization,
    )


def run_pass2_fetch(ctx) -> dict[str, Any]:
    _require_ctx_authorization(ctx)
    approval = _require_budget_approval(ctx)
    soft_boost_enabled = (
        ctx.theme_soft_boost_enabled and ctx.soft_discovery_run_result is not None
    )
    summary = _pass2.run_full_candidate_live_source_packet(
        preflight_summary_path=ctx.preflight_summary_path,
        expected_total_call_budget=approval.exact_pass2_calls,
        authorized_momentum_top_k=approval.momentum_top_k,
        budget_approval=approval,
        source_artifact_prefix=ctx.source_artifact_prefix,
        context_components_output_path=ctx.context_components_path,
        output_data_context_path=ctx.data_context_path,   # decision-date-keyed (else the runner default is a stale 20260706 name)
        overextension_projection_path=ctx.overextension_projection_path,
        sector_classification_packet_path=ctx.classification_packet_path,
        yfinance_grade_actions_path=ctx.yfinance_grade_actions_path,
        summary_path=_stage_summary_targets(ctx)["pass2"],
        confirm_user_authorization=ctx.confirm_user_authorization,
        run_data_context=True,
        generated_at=ctx.generated_at,
        observed_at=ctx.observed_at,
        provider_pace_seconds=ctx.provider_pace_seconds,
        max_retries_per_call=ctx.max_retries_per_call,
        retry_backoff_seconds=ctx.retry_backoff_seconds,
        max_total_http_attempts=ctx.max_total_http_attempts,
        forced_holding_tickers=_account_holding_tickers(ctx),
        catalyst_recall_tickers=list(ctx.catalyst_recall_tickers),
        theme_soft_boost_enabled=soft_boost_enabled,
        soft_discovery_stage_result=(
            ctx.soft_discovery_run_result if soft_boost_enabled else None
        ),
        provisional_theme_stage_receipt_path=(
            ctx.soft_discovery_receipt_path if soft_boost_enabled else None
        ),
        provisional_theme_validation_path=(
            ctx.soft_discovery_validation_path if soft_boost_enabled else None
        ),
        original_candidate_artifact_path=ctx.candidate_path if soft_boost_enabled else None,
        classification_packet_path=(
            ctx.classification_packet_path if soft_boost_enabled else None
        ),
        soft_boost_consumption_receipt_path=(
            ctx.soft_boost_consumption_receipt_path if soft_boost_enabled else None
        ),
        soft_boost_shadow_receipt_path=(
            ctx.soft_boost_shadow_receipt_path if soft_boost_enabled else None
        ),
        soft_boost_comparison_ledger_path=(
            ctx.soft_boost_comparison_ledger_path if soft_boost_enabled else None
        ),
        soft_boost_state_dir=ctx.state_dir if soft_boost_enabled else None,
    )
    return summary


def run_yfinance_grades_fetch(ctx) -> dict[str, Any]:
    _require_ctx_authorization(ctx)
    approval = _require_budget_approval(ctx)
    return _yfinance_grades.run_yfinance_grades_fetch(
        preflight_summary_path=ctx.preflight_summary_path,
        budget_approval=approval,
        output_source_package_path=ctx.yfinance_grade_source_package_path,
        output_resolved_actions_path=ctx.yfinance_grade_actions_path,
        summary_path=_stage_summary_targets(ctx)["yfinance_grades_fetch"],
        raw_root=ctx.sample_root / _yfinance_grades.RAW_REL_ROOT / f"us_short_batch5_capstone_{ctx.decision_date}_raw",
        confirm_user_authorization=ctx.confirm_user_authorization,
        generated_at=ctx.generated_at,
        observed_at=ctx.observed_at,
        pace_seconds=ctx.provider_pace_seconds,
    )


def run_vix_regime(ctx) -> dict[str, Any]:
    _require_ctx_authorization(ctx)
    return _vix.run_fetch(
        confirm_user_authorization=ctx.confirm_user_authorization,
        summary_path=ctx.vix_regime_summary_path,
        generated_at=ctx.generated_at,
    )


# --- OFFLINE stages (pure / local; no network) ---

def run_soft_discovery(ctx) -> dict[str, Any]:
    from runners.us_short_weekly_capstone_soft_discovery import run_offline_stage

    return run_offline_stage(ctx)


def run_serenity_quality_forward(ctx) -> dict[str, Any]:
    """Observe the optional Serenity annotation/review pair without provider or active-effect access."""
    from datetime import datetime

    from engine.us_short_serenity_quality_forward import run_quality_forward

    return run_quality_forward(
        annotation_path=ctx.serenity_annotation_path,
        review_path=ctx.serenity_quality_review_path,
        observation_path=ctx.serenity_quality_observation_path,
        ledger_path=ctx.serenity_quality_ledger_path,
        gate_path=ctx.serenity_quality_gate_path,
        decision_date=ctx.decision_date,
        observed_at=ctx.generated_at,
        root=ctx.sample_root,
        now=datetime.fromisoformat(ctx.generated_at),
    )


def run_momentum_producer(ctx) -> dict[str, Any]:
    return _mom_prod.run_packet(
        candidate_artifact_path=ctx.candidate_path,
        series_packet_path=ctx.series_packet_path,
        output_projection_path=ctx.momentum_projection_path,
        summary_path=_stage_summary_targets(ctx)["momentum_producer"],
        generated_at=ctx.generated_at,
    )


def run_overextension_producer(ctx) -> dict[str, Any]:
    return _overextension.run_packet(
        candidate_artifact_path=ctx.candidate_path,
        series_packet_path=ctx.ohlcv_series_packet_path,
        output_projection_path=ctx.overextension_projection_path,
        summary_path=_stage_summary_targets(ctx)["overextension_producer"],
        generated_at=ctx.generated_at,
    )


def run_theme_producer(ctx) -> dict[str, Any]:
    return _theme.run_packet(
        candidate_artifact_path=ctx.candidate_path,
        series_packet_path=ctx.series_packet_path,
        classification_packet_path=ctx.classification_packet_path,
        output_projection_path=ctx.theme_projection_path,
        summary_path=_stage_summary_targets(ctx)["theme_producer"],
        generated_at=ctx.generated_at,
    )


def run_projection_inputs(ctx) -> dict[str, Any]:
    return _proj.run_packet(
        candidate_artifact_path=ctx.candidate_path,
        expected_decision_date=ctx.decision_date,
        source_momentum_projection_path=ctx.momentum_projection_path,
        source_theme_projection_path=ctx.theme_projection_path,
        output_momentum_projection_path=ctx.merged_momentum_path,
        output_theme_projection_path=ctx.merged_theme_path,
        summary_path=_stage_summary_targets(ctx)["projection_inputs"],
        generated_at=ctx.generated_at,
    )


def run_pass2_preflight(ctx) -> dict[str, Any]:
    _require_ctx_authorization(ctx)
    _require_frozen_funnel_authorization(ctx, allow_budget_preview=True)
    return _preflight.run_preflight(
        candidate_artifact_path=ctx.candidate_path,
        expected_decision_date=ctx.decision_date,
        momentum_projection_path=ctx.merged_momentum_path,
        theme_projection_path=ctx.merged_theme_path,
        summary_path=ctx.preflight_summary_path,
        forced_holding_tickers=_account_holding_tickers(ctx),
        catalyst_recall_tickers=list(ctx.catalyst_recall_tickers),
        momentum_top_k=ctx.authorized_momentum_top_k,
        authorized_total_call_budget=ctx.authorized_pass2_call_budget,
        confirm_user_authorization=ctx.confirm_user_authorization,
        generated_at=ctx.generated_at,
    )


def run_forward_policy_shadow(ctx) -> dict[str, Any]:
    """Materialize the six A1 Path-A selection heads from the exact, already-built decision snapshot.

    This stage is deliberately local: it reads the same-run Batch5 context-components sidecar, re-runs only the
    authoritative selection delegate with policy-specific selection inputs, and writes a private ticker-bearing
    record plus a count-only companion.  It makes no provider call and does not fabricate a paper outcome or a
    lifecycle observation before the forward week has actually resolved.
    """
    try:
        data_context_bytes = ctx.data_context_path.read_bytes()
        data_context = json.loads(data_context_bytes)
        components_bytes = ctx.context_components_path.read_bytes()
        components = json.loads(components_bytes)
    except (OSError, ValueError) as exc:
        raise ValueError("forward-policy shadow requires readable same-run data_context and context-components JSON") from exc
    expected_component_keys = {
        "data_context", "score_composition", "overextension_by_ticker", "per_ticker_analysis", "run_provenance"}
    if not isinstance(components, dict) or set(components) != expected_component_keys:
        raise ValueError("forward-policy shadow context-components shape is incomplete or stale")
    if components["data_context"] != data_context:
        raise ValueError("forward-policy shadow refuses mismatched data_context and context-components snapshots")
    if components["overextension_by_ticker"] is None:
        raise ValueError("forward-policy shadow requires the source-bound overextension map")
    provenance = components["run_provenance"]
    if not isinstance(provenance, dict) or provenance.get("as_of") != ctx.decision_date \
            or provenance.get("price_basis_date") != ctx.price_basis_date:
        raise ValueError("forward-policy shadow provenance clock differs from the capstone canonical clock")
    calendar = load_market_calendar(_CALENDAR_PATH)
    sessions = sessions_for_window(ctx.now_et.strftime("%Y%m%d"), calendar=calendar)
    shadow = materialize_forward_policy_shadow(
        now_et=ctx.now_et,
        sessions=sessions,
        data_context=data_context,
        eligibility_governance=load_eligibility_governance(_ELIGIBILITY_GOVERNANCE_PATH),
        score_composition=components["score_composition"],
        overextension_by_ticker=components["overextension_by_ticker"],
        decision_date=ctx.decision_date,
        price_basis_date=ctx.price_basis_date,
        generated_at=ctx.generated_at,
        source_context_sha256=hashlib.sha256(components_bytes).hexdigest(),
        private_output_path=ctx.forward_shadow_selection_private_path,
        summary_output_path=ctx.forward_policy_summary_path,
    )
    try:
        ohlcv_bytes = ctx.ohlcv_series_packet_path.read_bytes()
        ohlcv_packet = json.loads(ohlcv_bytes)
        template = _bridge._load_template(ctx.batch4_template_path)
        vix_summary = json.loads(ctx.vix_regime_summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, _bridge.Batch5ToBatch4E2EError) as exc:
        raise ValueError("forward-policy source capture requires readable same-run OHLCV, VIX, and action template inputs") from exc
    market_axes = dict(template["market_axis_regimes"])
    vix_regime = vix_summary.get("vix_regime") if isinstance(vix_summary, dict) else None
    if vix_regime not in (*REGIMES, UNKNOWN) \
            or vix_summary.get("vix_regime_is_unknown") is not (vix_regime == UNKNOWN):
        vix_regime = UNKNOWN
    market_axes["vix"] = vix_regime
    source_capture = materialize_forward_policy_source_capture(
        capture=json.loads(ctx.forward_shadow_selection_private_path.read_text(encoding="utf-8")),
        ohlcv_packet=ohlcv_packet,
        ohlcv_packet_sha256=hashlib.sha256(ohlcv_bytes).hexdigest(),
        source_context_sha256=hashlib.sha256(components_bytes).hexdigest(),
        overextension_by_ticker=components["overextension_by_ticker"],
        market_axis_regimes=market_axes,
        prior_regime=template["prior_regime"],
        prior_upgrade_count=template["prior_upgrade_count"],
        private_output_path=ctx.forward_policy_source_capture_private_path,
    )
    return {**shadow, "source_capture": source_capture}


def run_forward_policy_corporate_actions(ctx) -> dict[str, Any]:
    """Fetch comparison-only market-wide split/dividend coverage before H20 maturity."""
    _require_ctx_authorization(ctx)
    from runners.us_short_forward_policy_corporate_action_fetch import run_fetch

    return run_fetch(
        confirm_user_authorization=ctx.confirm_user_authorization,
        capability=ctx.corporate_action_live_capability,
        decision_date=ctx.decision_date,
        generated_at=ctx.generated_at,
        maturity_ohlcv_path=ctx.ohlcv_series_packet_path,
        sample_root=ctx.sample_root,
        private_root=ctx.forward_policy_comparison_ledger_path.parent,
        summary_path=ctx.forward_policy_corporate_action_summary_path,
    )


def run_forward_policy_maturity(ctx) -> dict[str, Any]:
    """Mature only post-deployment private source captures with the current already-fetched OHLCV packet.

    The private directory scan is deliberately narrow (the new source-capture filename only) and
    ignores today's/future capture.  It never reconstructs old selections.  Without independently
    verified corporate-action evidence the materializer writes an explicit no-count record; a receipt
    and ledger append occur only for a fully evaluable H20 packet.
    """
    root = ctx.forward_policy_comparison_ledger_path.parent
    try:
        ohlcv_bytes = ctx.ohlcv_series_packet_path.read_bytes()
        current_ohlcv = json.loads(ohlcv_bytes)
    except (OSError, ValueError) as exc:
        raise ValueError("forward-policy maturity requires the current readable OHLCV packet") from exc
    source_digest = hashlib.sha256(ohlcv_bytes).hexdigest()
    captures = sorted(root.glob("forward_policy_source_capture_????????.json"))
    ledger = None
    processed = ready = no_count = already_ready = awaiting_adjustment = 0
    no_count_by_reason: dict[str, int] = {}
    for capture_path in captures:
        try:
            source_capture = validate_forward_policy_source_capture(
                json.loads(capture_path.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, ForwardPolicySourceCaptureError) as exc:
            raise ValueError("forward-policy maturity found an invalid private source capture") from exc
        decision_date = source_capture["capture"]["decision_date"]
        if decision_date >= ctx.decision_date:
            continue
        evidence_path = root / f"forward_policy_adjustment_evidence_{decision_date}.json"
        adjustment_evidence = None
        if evidence_path.exists():
            try:
                adjustment_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError("forward-policy maturity adjustment-evidence sidecar is unreadable") from exc
        outcome_path = root / f"forward_policy_outcome_{decision_date}.json"
        prior_private_week = None
        if outcome_path.exists():
            try:
                prior_private_week = validate_forward_policy_private_week_record(
                    json.loads(outcome_path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError, ForwardPolicyPrivateWeekError) as exc:
                raise ValueError("forward-policy maturity prior private outcome is unreadable or invalid") from exc
            if prior_private_week["materialization_status"] == "ready_for_accumulation":
                already_ready += 1
                continue
            previous_inputs = prior_private_week["forward_inputs"]
            complete_prior_window = isinstance(previous_inputs, dict) and isinstance(
                previous_inputs.get("daily_bars_by_ticker"), dict
            ) and all(
                isinstance(previous_inputs["daily_bars_by_ticker"].get(ticker), list)
                and len(previous_inputs["daily_bars_by_ticker"][ticker]) == 20
                for ticker in source_capture["capture"]["common_selection_pool"]
            )
            if adjustment_evidence is None and complete_prior_window:
                awaiting_adjustment += 1
                reason = prior_private_week["degradation_reason"]
                no_count_by_reason[reason] = no_count_by_reason.get(reason, 0) + 1
                continue
        result = materialize_forward_policy_source_maturity(
            source_capture=source_capture,
            current_ohlcv_packet=current_ohlcv,
            current_ohlcv_packet_sha256=source_digest,
            maturity_as_of=ctx.decision_date,
            source_run_id=f"capstone-forward-policy-maturity-{ctx.decision_date}",
            adjustment_evidence=adjustment_evidence,
            private_outcome_path=outcome_path,
            prior_private_week_record=prior_private_week,
        )
        processed += 1
        if not result["counted_week_eligible"]:
            no_count += 1
            reason = result["maturity_observability"]["degradation_reason"]
            no_count_by_reason[reason] = no_count_by_reason.get(reason, 0) + 1
            continue
        if ledger is None:
            if ctx.forward_policy_comparison_ledger_path.exists():
                try:
                    ledger = json.loads(ctx.forward_policy_comparison_ledger_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise ValueError("forward-policy maturity comparison ledger is unreadable") from exc
            else:
                ledger = empty_forward_policy_comparison_ledger()
        persisted = persist_source_bound_forward_policy_week(
            ledger_path=ctx.forward_policy_comparison_ledger_path,
            ledger=ledger,
            private_week_record=json.loads(outcome_path.read_text(encoding="utf-8")),
            source_receipt=result["source_receipt"],
        )
        ledger = persisted["ledger"]
        ready += 1
    return {
        "source_captures_processed": processed,
        "maturity_as_of": ctx.decision_date,
        "ready_weeks_appended_or_confirmed": ready,
        "whole_week_no_count": no_count,
        "whole_week_no_count_by_reason": dict(sorted(no_count_by_reason.items())),
        "already_ready_weeks_untouched": already_ready,
        "awaiting_adjustment_evidence_untouched": awaiting_adjustment,
    }


def run_soft_boost_comparison_capture(ctx) -> dict[str, Any]:
    """Advance the private 4c comparison clock once per real decision week.

    Capture is receipt-bound and does not manufacture H10 outcomes.  Matured
    observations are optional local, source-bound inputs from a later maturity
    workflow; absent observations leave the capture visibly unmatured.
    """
    try:
        consumption_raw = ctx.soft_boost_consumption_receipt_path.read_bytes()
        shadow_raw = ctx.soft_boost_shadow_receipt_path.read_bytes()
        consumption = json.loads(consumption_raw.decode("utf-8"))
        shadow = json.loads(shadow_raw.decode("utf-8"))
        _soft_boost_consumption._validate(
            consumption, _soft_boost_consumption.CONSUMPTION_SCHEMA, label="current K4b consumption receipt",
        )
        _soft_boost_consumption._validate(
            shadow, _soft_boost_consumption.SHADOW_SCHEMA, label="current K4b shadow receipt",
        )
        if (not isinstance(consumption, dict) or not isinstance(shadow, dict)
                or consumption.get("decision_date") != ctx.decision_date
                or shadow.get("decision_date") != ctx.decision_date
                or not isinstance(shadow.get("on_top15"), list) or not isinstance(shadow.get("off_top15"), list)):
            raise SoftBoostComparisonAdjudicationError("current K4b receipts are not source-bound to this decision")
        capture = build_pairwise_capture(
            decision_date=ctx.decision_date,
            consumption_receipt_sha256=hashlib.sha256(consumption_raw).hexdigest(),
            shadow_receipt_sha256=hashlib.sha256(shadow_raw).hexdigest(),
            divergent=set(shadow["on_top15"]) != set(shadow["off_top15"]),
        )
        ledger = append_pairwise_capture(read_pairwise_ledger(ctx.soft_boost_pairwise_ledger_path), capture)
        observations = []
        pending_dates = {record["decision_date"] for record in ledger["records"] if not record["matured"]}
        if ctx.soft_boost_maturity_observation_root.is_dir():
            for path in sorted(ctx.soft_boost_maturity_observation_root.glob("*.json")):
                observation = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(observation, dict) and observation.get("decision_date") in pending_dates:
                    observations.append(observation)
        if observations:
            ledger = apply_maturity_observations(ledger, observations, maturity_as_of=ctx.decision_date)
        persist_pairwise_ledger(ctx.soft_boost_pairwise_ledger_path, ledger)
        result = evaluate_pairwise_ledger(ledger)
        if result["formal_look"] is not None:
            receipt = build_adjudication_receipt(ctx.soft_boost_pairwise_ledger_path, decision_date=ctx.decision_date)
            path = ctx.soft_boost_adjudication_receipt_path
            if path.exists() and json.loads(path.read_text(encoding="utf-8")) != receipt:
                raise SoftBoostComparisonAdjudicationError("immutable adjudication receipt conflicts with current ledger")
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        return {"status": result["status"], "captured_week_count": ledger["captured_week_count"],
                "matured_week_count": ledger["matured_week_count"],
                "eligible_divergence_week_count": ledger["eligible_divergence_week_count"],
                "formal_look": result["formal_look"]}
    except (OSError, UnicodeDecodeError, ValueError, SoftBoostComparisonAdjudicationError) as exc:
        raise ValueError("soft-boost comparison capture rejected") from exc


def _soft_boost_maturity_metrics(packet: object, *, tickers: list[str], decision_date: str) -> tuple[dict[str, float], dict[str, str]] | None:
    """Return an equal-weight, ten-session held-basket outcome or no observation.

    The first usable session on/after the frozen decision is entry; the tenth
    subsequent session is exit.  Missing bars, non-finite prices, or malformed
    series are no-count rather than fabricated zero metrics.
    """
    packet = _validated_ohlcv_packet(packet)
    if packet["series_contract"].get("adjustment_mode") not in {"split_adjusted", "split_dividend_adjusted"}:
        return None
    entry_iso = f"{decision_date[:4]}-{decision_date[4:6]}-{decision_date[6:]}"
    outcomes, drawdowns = [], []
    window: dict[str, str] | None = None
    for ticker in tickers:
        series = packet["series_by_ticker"].get(ticker)
        points = series.get("points") if isinstance(series, dict) else None
        if not isinstance(points, list):
            return None
        usable = [point for point in points if isinstance(point, dict) and point.get("date", "") >= entry_iso]
        if len(usable) < 11:
            return None
        bars = usable[:11]
        if any(not isinstance(bar.get("close"), (int, float)) or isinstance(bar.get("close"), bool)
               or not math.isfinite(bar["close"]) or bar["close"] <= 0 for bar in bars):
            return None
        if any(bars[index]["date"] >= bars[index + 1]["date"] for index in range(10)):
            return None
        closes = [float(bar["close"]) for bar in bars]
        outcomes.append(closes[-1] / closes[0] - 1.0)
        peak, drawdown = closes[0], 0.0
        for close in closes:
            peak = max(peak, close)
            drawdown = max(drawdown, (peak - close) / peak)
        drawdowns.append(drawdown)
        candidate_window = {"window_start": bars[0]["date"], "h10_session_date": bars[-1]["date"]}
        if window is None:
            window = candidate_window
        elif window != candidate_window:
            # Different ticker calendars make a common H10 basket unevaluable.
            return None
    if not outcomes or window is None:
        return None
    return ({
        "net_return": sum(outcomes) / len(outcomes), "max_drawdown": sum(drawdowns) / len(drawdowns),
        "bad_pick_rate": sum(outcome < 0.0 for outcome in outcomes) / len(outcomes),
        "tail_loss": max(0.0, -min(outcomes)), "fill_fraction": 1.0,
    }, window)


def _soft_boost_basket_turnover(*, current: list[str], previous: list[str]) -> float | None:
    """Return adjacent-week basket replacement rate; absent prior basket is no-count."""
    current_set, previous_set = set(current), set(previous)
    if not current_set or not previous_set:
        return None
    return 1.0 - len(current_set & previous_set) / max(len(current_set), len(previous_set))


def _soft_boost_maturity_vix_regime(ctx) -> tuple[str | None, str | None]:
    """Bind maturity to the capstone VIX axis; unknown/missing is deliberately unevaluable."""
    try:
        raw = ctx.vix_regime_summary_path.read_bytes()
        summary = json.loads(raw.decode("utf-8"))
    except (AttributeError, OSError, UnicodeDecodeError, ValueError):
        return None, None
    regime = summary.get("vix_regime") if isinstance(summary, dict) else None
    if regime not in REGIMES or summary.get("vix_regime_is_unknown") is not False:
        return None, hashlib.sha256(raw).hexdigest()
    return regime, hashlib.sha256(raw).hexdigest()


def _write_immutable_private_json(path: Path, payload: dict[str, Any]) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("immutable soft-boost maturity receipt conflicts with existing evidence")
        return raw
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)
    return raw


def run_soft_boost_comparison_maturity(ctx) -> dict[str, Any]:
    """Produce source-bound K4C H10 observations from already-fetched local OHLCV only."""
    try:
        ledger = read_pairwise_ledger(ctx.soft_boost_pairwise_ledger_path)
        if ledger is None:
            return {"maturity_as_of": ctx.decision_date, "matured_observations_written": 0, "whole_week_no_count": 0}
        raw_packet = ctx.ohlcv_series_packet_path.read_bytes()
        packet = json.loads(raw_packet.decode("utf-8"))
        _validated_ohlcv_packet(packet)
        if packet["decision_clock"].get("expected_decision_date") != ctx.decision_date:
            raise ValueError("soft-boost maturity packet clock mismatch")
        vix_regime, vix_regime_sha256 = _soft_boost_maturity_vix_regime(ctx)
        observation_root = ctx.soft_boost_maturity_observation_root
        receipt_root = observation_root.parent / "soft_boost_maturity_receipts"
        written = no_count = 0
        receipt_schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "us_short_soft_boost_maturity_receipt.schema.json").read_text(encoding="utf-8"))
        non_overlap_until = None
        for prior in ledger["records"]:
            if not (prior["matured"] and prior["eligible"] and prior["non_overlap_h10_block"]):
                continue
            for path in receipt_root.glob(f"us_short_soft_boost_maturity_receipt_{prior['decision_date']}_*.json"):
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != prior["maturity_receipt_sha256"]:
                    continue
                candidate = json.loads(raw.decode("utf-8"))
                jsonschema.validate(candidate, receipt_schema)
                if candidate["status"] == "matured":
                    non_overlap_until = max(non_overlap_until or "", candidate["window"]["h10_session_date"])
        for index, record in enumerate(ledger["records"]):
            date = record["decision_date"]
            if record["matured"] or date >= ctx.decision_date or (observation_root / f"{date}.json").exists():
                continue
            consumption_path = ctx.soft_boost_consumption_receipt_path.parent / f"us_short_soft_boost_consumption_receipt_{date}.json"
            shadow_path = ctx.soft_boost_shadow_receipt_path.parent / f"us_short_soft_boost_shadow_receipt_{date}.json"
            consumption_raw, shadow_raw = consumption_path.read_bytes(), shadow_path.read_bytes()
            consumption = json.loads(consumption_raw.decode("utf-8"))
            shadow = json.loads(shadow_raw.decode("utf-8"))
            _soft_boost_consumption._validate(consumption, _soft_boost_consumption.CONSUMPTION_SCHEMA, label="maturity K4b consumption receipt")
            _soft_boost_consumption._validate(shadow, _soft_boost_consumption.SHADOW_SCHEMA, label="maturity K4b shadow receipt")
            if (consumption.get("decision_date") != date or shadow.get("decision_date") != date
                    or hashlib.sha256(consumption_raw).hexdigest() != record["consumption_receipt_sha256"]
                    or hashlib.sha256(shadow_raw).hexdigest() != record["shadow_receipt_sha256"]):
                raise ValueError("soft-boost maturity source receipt binding mismatch")
            on, off = list(shadow["on_top15"]), list(shadow["off_top15"])
            prior_shadow = None
            if index:
                prior = ledger["records"][index - 1]
                prior_shadow_path = ctx.soft_boost_shadow_receipt_path.parent / f"us_short_soft_boost_shadow_receipt_{prior['decision_date']}.json"
                prior_shadow_raw = prior_shadow_path.read_bytes()
                prior_shadow = json.loads(prior_shadow_raw.decode("utf-8"))
                _soft_boost_consumption._validate(prior_shadow, _soft_boost_consumption.SHADOW_SCHEMA, label="maturity prior K4b shadow receipt")
                if (prior_shadow.get("decision_date") != prior["decision_date"]
                        or hashlib.sha256(prior_shadow_raw).hexdigest() != prior["shadow_receipt_sha256"]):
                    raise ValueError("soft-boost maturity prior shadow binding mismatch")
            on_result = _soft_boost_maturity_metrics(packet, tickers=on, decision_date=date)
            off_result = _soft_boost_maturity_metrics(packet, tickers=off, decision_date=date)
            on_turnover = _soft_boost_basket_turnover(current=on, previous=list(prior_shadow["on_top15"])) if prior_shadow else None
            off_turnover = _soft_boost_basket_turnover(current=off, previous=list(prior_shadow["off_top15"])) if prior_shadow else None
            receipt = {
                "schema_name": "us_short_soft_boost_maturity_receipt", "schema_version": "1.0.0",
                "decision_date": date, "maturity_as_of": ctx.decision_date,
                "consumption_receipt_sha256": record["consumption_receipt_sha256"],
                "shadow_receipt_sha256": record["shadow_receipt_sha256"],
                "maturity_ohlcv_packet_sha256": hashlib.sha256(raw_packet).hexdigest(),
                "vix_regime_summary_sha256": vix_regime_sha256, "market_risk_regime": vix_regime,
                "status": "matured" if on_result is not None and off_result is not None and on_turnover is not None and off_turnover is not None and vix_regime is not None else "whole_week_no_count",
            }
            if receipt["status"] != "matured":
                receipt["reason_code"] = ("VIX_REGIME_UNAVAILABLE" if vix_regime is None else
                                          "ADJACENT_BASKET_TURNOVER_UNAVAILABLE" if on_turnover is None or off_turnover is None else
                                          "H10_WINDOW_OR_ADJUSTMENT_UNAVAILABLE")
                receipt["window"] = None
                receipt["on"] = receipt["off"] = None
                no_count += 1
            else:
                on_metrics, on_window = on_result
                off_metrics, off_window = off_result
                if on_window != off_window:
                    raise ValueError("soft-boost ON/OFF maturity windows differ")
                receipt["reason_code"] = None
                receipt["window"] = on_window
                on_metrics["turnover"], off_metrics["turnover"] = on_turnover, off_turnover
                receipt["on"], receipt["off"] = on_metrics, off_metrics
                jsonschema.validate(receipt, receipt_schema)
                observation_root.mkdir(parents=True, exist_ok=True)
                observation = {
                    "decision_date": date, "consumption_receipt_sha256": record["consumption_receipt_sha256"],
                    "shadow_receipt_sha256": record["shadow_receipt_sha256"],
                    "maturity_receipt_sha256": "0" * 64, "market_risk_regime": vix_regime,
                    "eligible": bool(record["divergent"] and on and off),
                    "non_overlap_h10_block": bool(non_overlap_until is None or on_window["window_start"] > non_overlap_until),
                    **{f"on_{key}": value for key, value in on_metrics.items()},
                    **{f"off_{key}": value for key, value in off_metrics.items()},
                }
                receipt_path = receipt_root / f"us_short_soft_boost_maturity_receipt_{date}_{ctx.decision_date}_matured.json"
                observation["maturity_receipt_sha256"] = hashlib.sha256(_write_immutable_private_json(receipt_path, receipt)).hexdigest()
                _write_immutable_private_json(observation_root / f"{date}.json", observation)
                if observation["non_overlap_h10_block"]:
                    non_overlap_until = on_window["h10_session_date"]
                written += 1
                continue
            jsonschema.validate(receipt, receipt_schema)
            _write_immutable_private_json(
                receipt_root / (f"us_short_soft_boost_maturity_receipt_{date}_{ctx.decision_date}_"
                                f"{receipt['maturity_ohlcv_packet_sha256'][:12]}_"
                                f"{(vix_regime_sha256 or 'vix_unavailable')[:12]}_whole_week_no_count.json"), receipt)
        return {"maturity_as_of": ctx.decision_date, "matured_observations_written": written, "whole_week_no_count": no_count}
    except (OSError, UnicodeDecodeError, ValueError, jsonschema.ValidationError, SoftBoostComparisonAdjudicationError) as exc:
        raise ValueError("soft-boost comparison maturity rejected") from exc


def run_weekly_bridge(ctx) -> dict[str, Any]:
    """Derive HONEST provider_health from the actual Pass2 outcome, then bridge the source packet → weekly report /
    action table. provider_health is NOT hand-written: fmp = ok iff >=_HEALTH_MIN_SUCCESS_COVERAGE of grades calls
    succeeded; sec_edgar = ok iff every unique Pass2 target has exactly one successful SEC submissions record. A
    down critical source makes the orchestrator emit nothing (design §3.2)."""
    _write_provider_health(ctx)
    try:
        vix_summary = json.loads(ctx.vix_regime_summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        vix_summary = {}
    receipt = getattr(ctx, "research_live_capability", None)
    if receipt is not None:
        require_research_live_provider_summary(receipt, "vix_regime", vix_summary)
    vix_regime = vix_summary.get("vix_regime") if isinstance(vix_summary, dict) else None
    if vix_regime not in (*REGIMES, UNKNOWN) \
            or vix_summary.get("vix_regime_is_unknown") is not (vix_regime == UNKNOWN):
        vix_regime = UNKNOWN
    comparison_reminder = comparison_banner_from_private_ledger_path(
        ctx.forward_policy_comparison_ledger_path,
    )
    soft_paths = None
    if ctx.theme_soft_boost_enabled and ctx.soft_discovery_run_result is not None:
        soft_paths = {
            "stage_receipt_path": str(ctx.soft_discovery_receipt_path),
            "consumption_receipt_path": str(ctx.soft_boost_consumption_receipt_path),
            "shadow_receipt_path": str(ctx.soft_boost_shadow_receipt_path),
            "comparison_ledger_path": str(ctx.soft_boost_pairwise_ledger_path
                                           if ctx.soft_boost_pairwise_ledger_path.is_file()
                                           else ctx.soft_boost_comparison_ledger_path),
            "adjudication_receipt_path": (str(ctx.soft_boost_adjudication_receipt_path)
                                           if ctx.soft_boost_adjudication_receipt_path.is_file() else None),
        }
    summary = _bridge.run_e2e(
        source_packet_path=ctx.source_packet_path,
        batch4_template_path=ctx.batch4_template_path,
        account_state_path=ctx.account_state_path,
        provider_health_path=ctx.provider_health_path,
        private_root=ctx.private_root,
        official_output_root=getattr(ctx, "official_output_root", None),
        now_et=ctx.now_et,
        context_components_path=ctx.context_components_path,
        run_mode="mixed_source",   # real provider facts + receipt-bound caller action template; never research_live
        # mixed_source is CAPSTONE-INTERNAL and bound to REAL EXECUTION plus the exact Batch4 action-template digest.
        # A direct bridge call, an injected test pipeline, or a dry run carries None here → run_e2e refuses the mode.
        _research_live_capability=getattr(ctx, "research_live_capability", None),
        bootstrap_lifecycle=True,
        generated_at=ctx.generated_at,
        vix_regime=vix_regime,
        forward_policy_comparison_reminder=comparison_reminder,
        soft_discovery_receipt_paths=soft_paths,
        projection_binding_expectations=_bridge.FULL_CANDIDATE_LIVE_PROJECTION_BINDING,
    )
    _deliver_serenity_shadow_to_official_report(ctx, summary)
    return summary


def _deliver_serenity_shadow_to_official_report(ctx, summary: Mapping[str, Any]) -> None:
    """Best-effort report delivery after the bridge has emitted its ordinary report.

    The Blade4 consumer remains a pure text overlay.  This caller is the one
    weekly integration seam allowed to read/write the already-created private
    report.  Any optional delivery failure leaves the ordinary report intact.
    """
    shadow = getattr(ctx, "serenity_shadow_result", None)
    if not isinstance(shadow, Mapping) or shadow.get("status") != "active":
        return
    batch4 = summary.get("batch4_run") if isinstance(summary, Mapping) else None
    output_paths = batch4.get("output_paths") if isinstance(batch4, Mapping) else None
    report_value = output_paths.get("weekly_report_path") if isinstance(output_paths, Mapping) else None
    if not isinstance(report_value, str) or not report_value:
        return
    report_path = Path(report_value).resolve()
    private_root = Path(getattr(ctx, "official_output_root", None) or getattr(ctx, "private_root", report_path.parent)).resolve()
    try:
        report_path.relative_to(private_root)
        report_text = report_path.read_text(encoding="utf-8")
        from engine.us_short_serenity_shadow_consumers import deliver_serenity_shadow_to_report

        delivered = deliver_serenity_shadow_to_report(report_text, shadow)
        if not delivered.get("report_block_delivered"):
            return
        temporary = report_path.with_name(report_path.name + ".serenity.tmp")
        temporary.write_text(delivered["report_text"], encoding="utf-8")
        temporary.replace(report_path)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except (UnboundLocalError, OSError):
            pass
        return


# --- honest provider_health derivation from the real Pass2 summary ---

# FMP grades reads "ok" only if at least this fraction of its ATTEMPTED endpoint calls came back success. This is a
# coverage threshold, deliberately NOT "any single success" / "any call attempted": a run whose grades mostly 429'd
# reports that source as down instead of pretending coverage is healthy. SEC submissions is different: as the
# emit-critical audit source, every unique Pass2 target ticker needs exactly one successful submissions record.
# Downstream criticality is separate: FMP grades is advisory/fallback; SEC submissions remains emit-critical.
# 0.5 = a simple majority; tune here if the operational bar changes.
_HEALTH_MIN_SUCCESS_COVERAGE = 0.5


def derive_provider_health(summary) -> dict[str, str]:
    """Pure canonical provider-health projection from the receipt-bound Pass2 summary."""
    results = summary.get("endpoint_results", []) if isinstance(summary, dict) else []
    if not isinstance(results, list):
        results = []

    def _coverage_ok(provider: str, family: str) -> bool:
        # success COVERAGE over the family's ATTEMPTED calls (obtained, not merely attempted): a mostly-failed source
        # is down. Non-dict rows are ignored (fail-closed), so a hostile row can never inflate coverage or crash.
        rows = [r for r in results
                if isinstance(r, dict) and r.get("provider_id") == provider and r.get("endpoint_family") == family]
        if not rows:
            return False   # no attempted calls for this family -> not a usable source
        successes = sum(1 for r in rows if r.get("status") == "success")
        return successes / len(rows) >= _HEALTH_MIN_SUCCESS_COVERAGE

    def _sec_target_coverage_ok() -> bool:
        target_universe = summary.get("pass2_target_universe") if isinstance(summary, dict) else None
        targets = target_universe.get("target_symbols") if isinstance(target_universe, dict) else None
        if type(targets) is not list or not targets or any(type(symbol) is not str or not symbol for symbol in targets):
            return False
        target_set = set(targets)
        target_count = target_universe.get("target_count")
        if len(target_set) != len(targets) or type(target_count) is not int or target_count != len(targets):
            return False

        sec_status_by_symbol: dict[str, Any] = {}
        for row in results:
            if not isinstance(row, dict) \
                    or row.get("provider_id") != "sec_edgar" \
                    or row.get("endpoint_family") != "submissions":
                continue
            symbol = row.get("symbol")
            if type(symbol) is not str or symbol not in target_set or symbol in sec_status_by_symbol:
                return False
            sec_status_by_symbol[symbol] = row.get("status")

        return (
            set(sec_status_by_symbol) == target_set
            and all(status == "success" for status in sec_status_by_symbol.values())
        )

    return {
        "fmp": "ok" if _coverage_ok("financial_modeling_prep", "grades") else "down",
        "sec_edgar": "ok" if _sec_target_coverage_ok() else "down",
    }


def _write_provider_health(ctx) -> None:
    # Fail closed on a malformed/unreadable summary: any read / parse / container-shape problem -> empty results ->
    # both sources 'down', NEVER a crash. Downstream permits advisory FMP fallback but still blocks on critical SEC.
    # This is the gate's OWN defense-in-depth, not reliance on the orchestrator's blanket stage-exception handler.
    try:
        summary = json.loads(_stage_summary_targets(ctx)["pass2"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        summary = {}
    receipt = getattr(ctx, "research_live_capability", None)
    if receipt is not None:
        require_research_live_provider_summary(receipt, "pass2_fetch", summary)
    health = derive_provider_health(summary)
    ctx.provider_health_path.parent.mkdir(parents=True, exist_ok=True)
    # F3: atomic write (tmp + os.replace) so a crash mid-write never leaves a half-written provider_health JSON.
    text = json.dumps(health, ensure_ascii=False, indent=2) + "\n"
    tmp = ctx.provider_health_path.with_name(ctx.provider_health_path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(ctx.provider_health_path)
