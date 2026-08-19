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
from engine.us_short_run_origin import RunOriginError, require_research_live_provider_summary
from engine.us_short_soft_boost_comparison_adjudication import (
    SoftBoostComparisonAdjudicationError, append_pairwise_capture, apply_maturity_observations,
    build_adjudication_receipt, build_pairwise_capture, evaluate_pairwise_ledger, persist_pairwise_ledger,
    read_pairwise_ledger,
)
from engine import us_short_soft_boost_consumption as _soft_boost_consumption
from engine.us_short_forward_policy_source_capture import _validated_ohlcv_packet
from engine.us_short_regime import (
    REGIMES,
    UNKNOWN,
    classify_breadth,
    classify_market_trend,
)
from runners import us_short_batch5_data_context_source_packet as _source_packet
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
_CURRENT_UNIVERSE_SUMMARY_SCHEMA_VERSION = "1.3.0"
_LEGACY_UNIVERSE_SUMMARY_SCHEMA_VERSIONS = frozenset({"1.0.0", "1.2.0"})


def _market_axis_inputs(ctx) -> tuple[list[str], dict[str, Any], str]:
    """Validate the two existing same-round inputs used by the real market-axis producer."""
    try:
        candidate = json.loads(ctx.candidate_path.read_text(encoding="utf-8"))
        packet = json.loads(ctx.series_packet_path.read_text(encoding="utf-8"))
        jsonschema.validate(candidate, json.loads(_universe.CANDIDATE_SCHEMA_PATH.read_text(encoding="utf-8")))
        candidate = _universe.validate_candidate_artifact(
            candidate,
            expected_decision_date=ctx.decision_date,
            governance=load_eligibility_governance(_ELIGIBILITY_GOVERNANCE_PATH),
        )
        jsonschema.validate(packet, json.loads(_mom_fetch.PACKET_SCHEMA_PATH.read_text(encoding="utf-8")))
    except Exception as exc:
        raise ValueError("market-axis candidate or momentum packet failed existing schema validation") from exc

    price_basis_date = f"{ctx.price_basis_date[:4]}-{ctx.price_basis_date[4:6]}-{ctx.price_basis_date[6:]}"
    clock = packet["decision_clock"]
    contract = packet["series_contract"]
    provenance = packet["provenance"]
    if (
        candidate["decision_date"] != ctx.decision_date
        or candidate["price_basis_date"] != ctx.price_basis_date
        or candidate["used_date"] != price_basis_date
        or clock["expected_decision_date"] != ctx.decision_date
        or clock["candidate_price_basis_date"] != ctx.price_basis_date
        or clock["price_basis_date"] != price_basis_date
        or clock["source_as_of"] != price_basis_date
        or contract["as_of"] != price_basis_date
        or provenance["source_as_of"] != price_basis_date
        or contract["session"] != _mom_fetch.SESSION_LABEL
        or contract["adjustment_mode"] != _mom_fetch.ADJUSTMENT_MODE
        or contract["benchmark_symbols"] != list(_mom_fetch.BENCHMARK_SYMBOLS)
    ):
        raise ValueError("market-axis candidate and momentum packet clocks/contracts do not match")
    try:
        series_by_ticker = _mom_prod._canonical_series_by_ticker(
            series_by_ticker=packet["series_by_ticker"],
            allowed=set(candidate["eligible_tickers"]) | set(_mom_fetch.BENCHMARK_SYMBOLS),
            price_basis_date=price_basis_date,
            session=contract["session"],
            adjustment_mode=contract["adjustment_mode"],
        )
        for benchmark in _mom_fetch.BENCHMARK_SYMBOLS:
            if benchmark not in series_by_ticker:
                raise ValueError(f"required benchmark series missing: {benchmark}")
    except Exception as exc:
        raise ValueError("market-axis momentum packet series are not same-clock eligible inputs") from exc
    return list(candidate["eligible_tickers"]), series_by_ticker, price_basis_date


def _build_market_axis_regimes(ctx, *, vix_regime: str) -> dict[str, str]:
    eligible_tickers, series_by_ticker, price_basis_date = _market_axis_inputs(ctx)
    return {
        "vix": vix_regime,
        "market_trend": classify_market_trend(
            series_by_ticker,
            price_basis_date=price_basis_date,
            session=_mom_fetch.SESSION_LABEL,
            adjustment_mode=_mom_fetch.ADJUSTMENT_MODE,
        ),
        "breadth": classify_breadth(
            eligible_tickers,
            series_by_ticker,
            price_basis_date=price_basis_date,
            session=_mom_fetch.SESSION_LABEL,
            adjustment_mode=_mom_fetch.ADJUSTMENT_MODE,
        ),
    }


def _stage_summary_targets(ctx) -> dict[str, Path]:
    """The per-run summary sidecar EACH stage runner writes, keyed by stage. Each lands under the runner's OWN
    reviewed `provider_samples/<runner>/` root (referenced via the runner's exported constant so it can NEVER drift
    from that runner's fail-closed allowlist), with a decision-date-keyed filename. These runners were built as
    one-shot MILESTONE runners whose only accepted summary paths are a fixed-date `docs/…` file or their own
    gitignored `provider_samples/…` folder; the capstone reuses them as repeatable weekly PIPELINE stages, so it must
    route their per-run summaries into that gitignored folder (a `state/us_short/…` summary is rejected by every one).
    `sample_root` is the repo root the runners resolve provider_samples against (tests inject a tempdir). The
    preflight summary is NOT here — it is `ctx.preflight_summary_path` (also stage-8's INPUT, so it lives where BOTH
    runners accept it). The seven migrated paths are partitioned by `ctx.decision_date`; momentum-fetch and SIC keep
    their existing semantic roots."""
    def _p(rel_root: Path, name: str, *, dated: bool = False) -> Path:
        base = ctx.sample_root / rel_root
        if dated:
            base = base / ctx.decision_date
        return base / f"us_short_batch5_capstone_{ctx.decision_date}_{name}_summary.json"
    return {
        "momentum_fetch": _p(_mom_fetch.SUMMARY_SAMPLE_REL_ROOT, "momentum_fetch"),
        "momentum_producer": _p(_mom_prod.SAMPLE_REL_ROOT, "momentum_producer", dated=True),
        "overextension_producer": _p(_overextension.SAMPLE_REL_ROOT, "overextension_producer", dated=True),
        "sic_classification": _p(_sic.SUMMARY_SAMPLE_REL_ROOT, "sic_classification"),
        "theme_producer": _p(_theme.SAMPLE_REL_ROOT, "theme_producer", dated=True),
        "projection_inputs": _p(_proj.SAMPLE_REL_ROOT, "projection_inputs", dated=True),
        "yfinance_grades_fetch": _p(_yfinance_grades.RAW_REL_ROOT, "yfinance_grades_fetch", dated=True),
        "pass2": _p(_pass2.RAW_SAMPLE_REL_ROOT, "pass2", dated=True),
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
        ohlcv_series_packet_path=ctx.ohlcv_series_packet_path,
        sector_classification_packet_path=ctx.classification_packet_path,
        yfinance_grade_actions_path=ctx.yfinance_grade_actions_path,
        raw_root=ctx.sample_root / _pass2.RAW_SAMPLE_REL_ROOT / ctx.decision_date / "raw",
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
        decision_lock=getattr(ctx, "decision_lock", None),
    )
    return summary


def classify_soft_boost_artifact_state(ctx) -> dict[str, str]:
    """Thin context-bound adapter for the sole K4b artifact-usability contract."""
    requested = (
        getattr(ctx, "theme_soft_boost_enabled", None) is True
        and getattr(ctx, "soft_discovery_run_result", None) is not None
        and getattr(ctx, "soft_boost_run_result", None) is not None
    )
    return _soft_boost_consumption.classify_soft_boost_artifact_state(
        soft_boost_requested=requested,
        soft_boost_run_result=getattr(ctx, "soft_boost_run_result", None),
        consumption_receipt_path=(ctx.soft_boost_consumption_receipt_path if requested else None),
        shadow_receipt_path=(ctx.soft_boost_shadow_receipt_path if requested else None),
        comparison_ledger_path=(ctx.soft_boost_comparison_ledger_path if requested else None),
    )


def run_yfinance_grades_fetch(ctx) -> dict[str, Any]:
    _require_ctx_authorization(ctx)
    approval = _require_budget_approval(ctx)
    return _yfinance_grades.run_yfinance_grades_fetch(
        preflight_summary_path=ctx.preflight_summary_path,
        budget_approval=approval,
        output_source_package_path=ctx.yfinance_grade_source_package_path,
        output_resolved_actions_path=ctx.yfinance_grade_actions_path,
        summary_path=_stage_summary_targets(ctx)["yfinance_grades_fetch"],
        raw_root=ctx.sample_root / _yfinance_grades.RAW_REL_ROOT / ctx.decision_date / "raw",
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
    """Produce/observe the optional Serenity pair and expose the downstream preflight."""
    from datetime import datetime

    from engine.us_short_serenity_quality_forward import produce_annotation_for_week, run_quality_forward

    producer = produce_annotation_for_week(
        annotation_path=ctx.serenity_annotation_path,
        annotation_payload=getattr(ctx, "serenity_annotation_payload", None),
        soft_discovery_result=ctx.soft_discovery_run_result,
        decision_date=ctx.decision_date,
        root=ctx.sample_root,
        now=datetime.fromisoformat(ctx.generated_at),
    )
    result = run_quality_forward(
        annotation_path=ctx.serenity_annotation_path,
        review_path=ctx.serenity_quality_review_path,
        observation_path=ctx.serenity_quality_observation_path,
        ledger_path=ctx.serenity_quality_ledger_path,
        gate_path=ctx.serenity_quality_gate_path,
        decision_date=ctx.decision_date,
        observed_at=ctx.generated_at,
        root=ctx.sample_root,
        now=datetime.fromisoformat(ctx.generated_at),
        g1_decision_path=ctx.serenity_g1_decision_path,
        g1_preflight_path=ctx.serenity_g1_blade6_preflight_path,
    )
    result["annotation_producer"] = producer
    result["previous_review_settlement"] = getattr(ctx, "serenity_settlement_result", None)
    return result


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
        active_analyst_source="yfinance",
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
    try:
        _source_packet.validate_current_context_components(components)
    except _source_packet.SourcePacketError as exc:
        raise ValueError(f"forward-policy shadow context-components shape rejected: {exc}") from exc
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
        prior_regime=getattr(ctx, "prior_regime", None),
        prior_upgrade_count=getattr(ctx, "prior_upgrade_count", 0),
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
    artifact_state = classify_soft_boost_artifact_state(ctx)
    if artifact_state["state"] != "comparison_ready":
        return {
            "status": (
                "failed"
                if artifact_state["reason_code"] == "SOFT_BOOST_COMPARISON_ARTIFACT_INVALID"
                else "not_applicable"
            ),
            "reason_code": artifact_state["reason_code"],
            "comparison_capture_performed": False,
        }
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
        return {"status": result["status"], "reason_code": None, "comparison_capture_performed": True,
                "captured_week_count": ledger["captured_week_count"],
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


def _nonblocking_failure_rows(outcomes: Any) -> list[dict[str, str]]:
    """Project already-normalized pre-bridge failures for the operator banner."""
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    if not isinstance(outcomes, (list, tuple)):
        return rows
    for outcome in outcomes:
        if not isinstance(outcome, Mapping) or outcome.get("outcome_class") != "failed_nonblocking":
            continue
        stage = outcome.get("stage")
        reason_code = outcome.get("reason_code")
        if not isinstance(stage, str) or not isinstance(reason_code, str):
            continue
        key = (stage, reason_code)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"stage": stage, "reason_code": reason_code})
    return rows


def _render_nonblocking_failure_banner(rows: list[dict[str, str]]) -> str:
    lines = [f"非阻断阶段失败总数={len(rows)}"]
    lines.extend(f"{row['stage']}/{row['reason_code']}" for row in rows)
    lines.append("主报告已生成，但对应观察/比较证据可能缺失；不得把缺失解释为无事发生")
    return "\n".join(lines)


def _append_nonblocking_failure_banner(report_path: Path, banner_text: str) -> bool:
    """Atomically append banner ⑨ while leaving the ordinary report intact on failure."""
    temporary = report_path.with_name(report_path.name + ".nonblocking.tmp")
    try:
        report_text = report_path.read_text(encoding="utf-8")
        rendered = report_text + ("" if report_text.endswith("\n") else "\n")
        rendered += f"- ⑨ nonblocking_stage_failures: {banner_text}\n"
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(report_path)
        return True
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def run_weekly_bridge(ctx) -> dict[str, Any]:
    """Derive the closed-world eight-family provider health from stage outcomes, then bridge the source packet →
    weekly report / action table. The projection is not hand-written: each family is sourced from its owning stage,
    and a down critical family makes the orchestrator emit nothing (design §3.2)."""
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
    artifact_state = classify_soft_boost_artifact_state(ctx)
    formal_model_paper = getattr(ctx, "model_paper_store_root", None) is not None
    model_paper_track = getattr(ctx, "model_paper_track", None)
    if formal_model_paper and not isinstance(model_paper_track, dict):
        raise ValueError("formal model-paper context requires a model-paper paper_track object")
    soft_paths = (
        {
            "stage_receipt_path": None,
            "consumption_receipt_path": None,
            "shadow_receipt_path": None,
            "comparison_ledger_path": None,
            "adjudication_receipt_path": None,
            "artifact_state": "invalid",
        }
        if artifact_state["reason_code"] == "SOFT_BOOST_COMPARISON_ARTIFACT_INVALID"
        else None
    )
    if artifact_state["state"] == "consumption_only":
        soft_paths = {
            "stage_receipt_path": (
                str(ctx.soft_discovery_receipt_path)
                if ctx.soft_discovery_receipt_path.is_file() else None
            ),
            "consumption_receipt_path": str(ctx.soft_boost_consumption_receipt_path),
            "shadow_receipt_path": None,
            "comparison_ledger_path": None,
            "adjudication_receipt_path": None,
        }
    elif artifact_state["state"] == "comparison_ready":
        soft_paths = {
            "stage_receipt_path": (
                str(ctx.soft_discovery_receipt_path)
                if ctx.soft_discovery_receipt_path.is_file() else None
            ),
            "consumption_receipt_path": str(ctx.soft_boost_consumption_receipt_path),
            "shadow_receipt_path": str(ctx.soft_boost_shadow_receipt_path),
            "comparison_ledger_path": str(ctx.soft_boost_pairwise_ledger_path
                                           if ctx.soft_boost_pairwise_ledger_path.is_file()
                                           else ctx.soft_boost_comparison_ledger_path),
            "adjudication_receipt_path": (str(ctx.soft_boost_adjudication_receipt_path)
                                           if ctx.soft_boost_adjudication_receipt_path.is_file() else None),
        }
    market_axis_regimes = _build_market_axis_regimes(ctx, vix_regime=vix_regime)
    summary = _bridge.run_e2e(
        source_packet_path=ctx.source_packet_path,
        batch4_template_path=ctx.batch4_template_path,
        account_state_path=ctx.account_state_path,
        provider_health_path=ctx.provider_health_path,
        private_root=ctx.private_root,
        official_output_root=getattr(ctx, "official_output_root", None),
        prior_run_dir=getattr(ctx, "prior_run_dir", None),
        now_et=ctx.now_et,
        context_components_path=ctx.context_components_path,
        run_mode="mixed_source",   # real provider facts + receipt-bound caller action template; never research_live
        # mixed_source is CAPSTONE-INTERNAL and bound to REAL EXECUTION plus the exact Batch4 action-template digest.
        # A direct bridge call, an injected test pipeline, or a dry run carries None here → run_e2e refuses the mode.
        _research_live_capability=getattr(ctx, "research_live_capability", None),
        bootstrap_lifecycle=True,
        generated_at=ctx.generated_at,
        vix_regime=vix_regime,
        market_axis_regimes=market_axis_regimes,
        forward_policy_comparison_reminder=comparison_reminder,
        soft_discovery_receipt_paths=soft_paths,
        model_paper_track=model_paper_track if formal_model_paper else None,
        projection_binding_expectations=_bridge.FULL_CANDIDATE_LIVE_PROJECTION_BINDING,
    )
    delivery = _deliver_serenity_shadow_to_official_report(ctx, summary)
    _record_serenity_report_delivery(ctx, delivery)
    serenity_active = (
        isinstance(getattr(ctx, "serenity_shadow_result", None), Mapping)
        and getattr(ctx, "serenity_shadow_result").get("status") == "active"
    )
    serenity_report_delivery_status = "not_applicable"
    if serenity_active:
        serenity_report_delivery_status = (
            "delivered"
            if isinstance(delivery, Mapping) and delivery.get("report_block_delivered") is True
            else "failed"
        )

    failure_rows = _nonblocking_failure_rows(getattr(ctx, "pre_bridge_stage_outcomes", ()))
    if serenity_report_delivery_status == "failed":
        failure_rows.append({
            "stage": "serenity_report_delivery",
            "reason_code": "SERENITY_REPORT_DELIVERY_FAILED",
        })
    nonblocking_failure_banner_status = "not_applicable"
    if failure_rows:
        batch4 = summary.get("batch4_run") if isinstance(summary, Mapping) else None
        output_paths = batch4.get("output_paths") if isinstance(batch4, Mapping) else None
        report_value = output_paths.get("weekly_report_path") if isinstance(output_paths, Mapping) else None
        report_path = Path(report_value) if isinstance(report_value, str) and report_value else None
        nonblocking_failure_banner_status = (
            "delivered"
            if report_path is not None
            and _append_nonblocking_failure_banner(
                report_path,
                _render_nonblocking_failure_banner(failure_rows),
            )
            else "failed"
        )
    summary["serenity_report_delivery_status"] = serenity_report_delivery_status
    summary["nonblocking_failure_banner_status"] = nonblocking_failure_banner_status
    return summary


def _deliver_serenity_shadow_to_official_report(
    ctx, summary: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Best-effort report delivery after the bridge has emitted its ordinary report.

    The Blade4 consumer remains a pure text overlay.  This caller is the one
    weekly integration seam allowed to read/write the already-created private
    report.  Any optional delivery failure leaves the ordinary report intact.
    """
    shadow = getattr(ctx, "serenity_shadow_result", None)
    if not isinstance(shadow, Mapping) or shadow.get("status") != "active":
        return None
    batch4 = summary.get("batch4_run") if isinstance(summary, Mapping) else None
    output_paths = batch4.get("output_paths") if isinstance(batch4, Mapping) else None
    report_value = output_paths.get("weekly_report_path") if isinstance(output_paths, Mapping) else None
    if not isinstance(report_value, str) or not report_value:
        return {
            "report_block_delivered": False,
            "report_block_problem": "weekly report path is missing",
            "main_task_should_abort": False,
        }
    report_path = Path(report_value).resolve()
    private_root = Path(getattr(ctx, "official_output_root", None) or getattr(ctx, "private_root", report_path.parent)).resolve()
    temporary = None
    try:
        report_path.relative_to(private_root)
        report_text = report_path.read_text(encoding="utf-8")
        from engine.us_short_serenity_shadow_consumers import deliver_serenity_shadow_to_report

        delivered = deliver_serenity_shadow_to_report(report_text, shadow)
        if not delivered.get("report_block_delivered"):
            return delivered
        temporary = report_path.with_name(report_path.name + ".serenity.tmp")
        temporary.write_text(delivered["report_text"], encoding="utf-8")
        temporary.replace(report_path)
        return delivered
    except Exception as exc:
        try:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return {
            "report_block_delivered": False,
            "report_block_problem": f"{type(exc).__name__}: {str(exc).replace(chr(10), ' ')[:260]}",
            "main_task_should_abort": False,
        }


def _record_serenity_report_delivery(ctx, delivery: Mapping[str, Any] | None) -> None:
    """Persist the optional overlay outcome without making report delivery fatal."""
    if not isinstance(delivery, Mapping) or type(delivery.get("report_block_delivered")) is not bool:
        return
    delivered = delivery["report_block_delivered"]
    problem = delivery.get("report_block_problem")
    if problem is not None:
        problem = " ".join(str(problem).replace("\r", " ").replace("\n", " ").split())[:300]

    quality_result = getattr(ctx, "serenity_quality_run_result", None)
    if isinstance(quality_result, dict):
        quality_result["report_block_delivered"] = delivered
        quality_result["report_block_problem"] = problem
        observation = quality_result.get("observation")
        if isinstance(observation, dict):
            observation["report_block_delivered"] = delivered
            observation["report_block_problem"] = problem

    observation_path = getattr(ctx, "serenity_quality_observation_path", None)
    if not isinstance(observation_path, (str, Path)):
        return
    try:
        path = Path(observation_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_name") != "us_short_serenity_quality_forward_observation":
            return
        payload["report_block_delivered"] = delivered
        payload["report_block_problem"] = problem
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return


# --- canonical eight-family provider-health projection ---

# This is the only health projector. It consumes the already-verified stage results carried by the capstone receipt;
# analyst grades are projected from the selected yfinance stage summary or explicit FMP fallback in Pass2.
_HEALTH_PRODUCER_STAGES = (
    "universe_fetch", "momentum_fetch", "sic_fetch", "pass2_fetch", "yfinance_grades_fetch", "vix_regime",
)
_EVENT_FAMILIES = ("reference_news", "stock_splits", "dividends")


def _raw_state_from_summary_state(value: Any) -> str:
    """Map an existing producer run-state to the raw health vocabulary."""
    if value == "clean":
        return "ok"
    if value in {"usable_with_fallback", "restricted"}:
        return "degraded"
    if value == "blocked":
        return "down"
    return "missing"


def _universe_summary_is_complete_for_health(summary: Mapping[str, Any]) -> bool:
    if not isinstance(summary, Mapping):
        return False
    version = summary.get("schema_version")
    if version == _CURRENT_UNIVERSE_SUMMARY_SCHEMA_VERSION:
        return type(summary.get("complete")) is bool and summary["complete"] is True
    if version in _LEGACY_UNIVERSE_SUMMARY_SCHEMA_VERSIONS:
        scope = summary.get("scope")
        return isinstance(scope, Mapping) and scope.get("status") == "universe_fetch_and_pass1_completed"
    return False


def _universe_health(summary: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(summary, Mapping):
        return "universe_status", "missing"
    if not _universe_summary_is_complete_for_health(summary):
        return "universe_status", "missing"
    scope = summary.get("scope")
    if not isinstance(scope, Mapping) or not isinstance(scope.get("status"), str):
        return "universe_status", "missing"
    producer_health = summary.get("provider_health")
    if not isinstance(producer_health, Mapping):
        return "universe_status", "missing"
    status_sources = producer_health.get("status_sources")
    if not isinstance(status_sources, Mapping):
        return "universe_status", "missing"
    status_state = status_sources.get("state")
    outcome = status_sources.get("outcome")
    if not isinstance(status_state, str) or not isinstance(outcome, Mapping):
        return "universe_status", "missing"
    if type(outcome.get("block_or_no_emit")) is not bool \
            or type(outcome.get("critical_all_failed")) is not bool \
            or not isinstance(outcome.get("failed_sources"), list) \
            or not isinstance(outcome.get("critical_failed"), list) \
            or type(outcome.get("failed_count")) is not int \
            or type(outcome.get("total_sources")) is not int:
        return "universe_status", "missing"
    failed_sources = outcome["failed_sources"]
    critical_failed = outcome["critical_failed"]
    if any(not isinstance(value, str) or not value for value in (*failed_sources, *critical_failed)):
        return "universe_status", "missing"
    # An emit-critical family may not rest on vacuous evidence: recompute the failure lists from `per_source`
    # exactly as the canonical producer does, so "no sources at all" or "every source down but nothing failed"
    # can no longer read as healthy.
    from engine.us_short_status_source import CRITICAL_STATUS_SOURCES, STATUS_SOURCES, _SOURCE_FAIL, _SOURCE_STATES

    per_source = outcome.get("per_source")
    if not isinstance(per_source, Mapping) or set(per_source) != set(STATUS_SOURCES) \
            or any(per_source[src] not in _SOURCE_STATES for src in STATUS_SOURCES):
        return "universe_status", "missing"
    expected_failed = sorted(src for src in STATUS_SOURCES if per_source[src] in _SOURCE_FAIL)
    expected_critical_failed = sorted(src for src in CRITICAL_STATUS_SOURCES if per_source[src] in _SOURCE_FAIL)
    if (
        failed_sources != sorted(set(failed_sources))
        or critical_failed != sorted(set(critical_failed))
        or failed_sources != expected_failed
        or critical_failed != expected_critical_failed
        or outcome["failed_count"] != len(failed_sources)
        or outcome["total_sources"] != len(STATUS_SOURCES)
        or outcome["total_sources"] < outcome["failed_count"]
        or outcome["critical_all_failed"] is not (set(expected_critical_failed) == set(CRITICAL_STATUS_SOURCES))
        or outcome["block_or_no_emit"] is not outcome["critical_all_failed"]
    ):
        return "universe_status", "missing"
    expected_state = "blocked" if outcome["block_or_no_emit"] else (
        "restricted" if critical_failed else "clean"
    )
    if status_state != expected_state:
        return "universe_status", "missing"
    state = _raw_state_from_summary_state(status_state)
    if state == "missing":
        return "universe_status", "missing"
    screening = summary.get("status_screening")
    screening_outcome = screening.get("status_source_outcome") if isinstance(screening, Mapping) else None
    if screening_outcome is not None and screening_outcome != outcome:
        return "universe_status", "missing"
    return "universe_status", state


def _universe_market_cap_health(summary: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(summary, Mapping):
        return "universe_market_cap", "missing"
    if not _universe_summary_is_complete_for_health(summary):
        return "universe_market_cap", "missing"
    pass1 = summary.get("pass1_result")
    if not isinstance(pass1, Mapping):
        return "universe_market_cap", "missing"
    needs = pass1.get("needs_market_cap")
    if (not isinstance(needs, list) or any(not isinstance(value, str) or not value for value in needs)
            or len(set(needs)) != len(needs)):
        return "universe_market_cap", "missing"

    # The current producer supplies one conserved aggregate. Historical summaries predating this aggregate remain
    # readable through the legacy provider-health path below; they must never be mistaken for current yfinance evidence.
    if "market_cap_completion" in summary:
        completion = summary.get("market_cap_completion")
        required = (
            "needed_count", "sec_companyfacts_target_count", "sec_companyfacts_request_count",
            "sec_companyfacts_rescued_count", "yfinance_attempted_count", "yfinance_rescued_count",
            "massive_overview_attempted_count", "massive_overview_rescued_count", "final_unresolved_count",
        )
        if not isinstance(completion, Mapping) or any(
            type(completion.get(key)) is not int or completion[key] < 0 for key in required
        ):
            return "universe_market_cap", "down"
        needed = completion["needed_count"]
        sec_target = completion["sec_companyfacts_target_count"]
        sec_calls = completion["sec_companyfacts_request_count"]
        sec_rescued = completion["sec_companyfacts_rescued_count"]
        yfinance_attempted = completion["yfinance_attempted_count"]
        yfinance_rescued = completion["yfinance_rescued_count"]
        massive_attempted = completion["massive_overview_attempted_count"]
        massive_rescued = completion["massive_overview_rescued_count"]
        unresolved = completion["final_unresolved_count"]
        if (
            sec_target > needed or sec_calls > sec_target
            or yfinance_attempted > needed - sec_rescued
            or yfinance_rescued > yfinance_attempted
            or massive_attempted > needed - sec_rescued - yfinance_rescued
            or massive_rescued > massive_attempted
            or sec_rescued > needed
            or unresolved != len(needs)
            or needed != sec_rescued + yfinance_rescued + massive_rescued + unresolved
        ):
            return "universe_market_cap", "down"
        return "universe_market_cap", "ok" if unresolved == 0 else "degraded"

    unresolved = len(needs)
    fallback = ((summary.get("provider_health") or {}).get("opportunistic_fallbacks")
                if isinstance(summary.get("provider_health"), Mapping) else None)
    fallback = fallback.get("yfinance_market_cap") if isinstance(fallback, Mapping) else None
    if fallback is None:
        # Historical committed summaries used the retired FMP provider family; read them without upgrading the
        # evidence to the current yfinance path.
        legacy_health = ((summary.get("provider_health") or {}).get("opportunistic_fallbacks")
                         if isinstance(summary.get("provider_health"), Mapping) else None)
        fallback = legacy_health.get("fmp_profile_market_cap") if isinstance(legacy_health, Mapping) else None
    if isinstance(fallback, Mapping):
        raw_needed = fallback.get("needed_count")
        raw_unresolved = fallback.get("unresolved_count")
        if type(raw_needed) is int and raw_needed >= 0 and type(raw_unresolved) is int and raw_unresolved >= 0:
            unresolved = raw_unresolved
            if raw_needed == 0 or unresolved == 0:
                return "universe_market_cap", "ok"
            return "universe_market_cap", "down" if unresolved >= raw_needed else "degraded"
    return "universe_market_cap", "ok" if unresolved == 0 else "degraded"


def _momentum_health(summary: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(summary, Mapping):
        return "massive_momentum", "missing"
    stats = summary.get("fetch_stats")
    coverage = summary.get("coverage")
    if not isinstance(stats, Mapping) or not isinstance(coverage, Mapping):
        return "massive_momentum", "missing"
    sessions = stats.get("sessions_with_data")
    min_sessions = stats.get("min_sessions_required")
    eligible = coverage.get("eligible_count")
    series = coverage.get("series_ticker_count")
    benchmarks = coverage.get("benchmarks_present")
    if any(type(value) is not int or value < 0 for value in (sessions, min_sessions, eligible, series)) \
            or type(benchmarks) is not bool:
        return "massive_momentum", "missing"
    if eligible > 0 and series == 0:
        return "massive_momentum", "down"
    if sessions == 0 or sessions < min_sessions:
        return "massive_momentum", "down" if sessions == 0 else "degraded"
    if not benchmarks or series < eligible:
        return "massive_momentum", "degraded"
    return "massive_momentum", "ok"


def _sic_health(summary: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(summary, Mapping):
        return "sec_sic", "missing"
    classification = summary.get("classification")
    if not isinstance(classification, Mapping):
        return "sec_sic", "missing"
    eligible = classification.get("eligible_count")
    resolved = classification.get("sic_resolved_count")
    missing = classification.get("sic_missing_count")
    if any(type(value) is not int or value < 0 for value in (eligible, resolved, missing)) \
            or resolved + missing != eligible:
        return "sec_sic", "missing"
    if eligible == 0:
        return "sec_sic", "ok"
    if resolved == 0:
        return "sec_sic", "down"
    return "sec_sic", "ok" if resolved == eligible else "degraded"


def _pass2_rows(summary: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], list[str]] | None:
    if not isinstance(summary, Mapping) or not isinstance(summary.get("endpoint_results"), list):
        return None
    targets = ((summary.get("pass2_target_universe") or {}).get("target_symbols")
               if isinstance(summary.get("pass2_target_universe"), Mapping) else None)
    target_count = ((summary.get("pass2_target_universe") or {}).get("target_count")
                    if isinstance(summary.get("pass2_target_universe"), Mapping) else None)
    # The per-symbol type check MUST precede set()/hashing: an unhashable target (dict/list) would otherwise
    # raise TypeError out of a projector whose whole contract is to fail closed, never to crash.
    if type(targets) is not list or not targets or type(target_count) is not int \
            or any(type(symbol) is not str or not symbol for symbol in targets) \
            or target_count != len(targets) or len(set(targets)) != len(targets):
        return None
    rows = summary["endpoint_results"]
    if any(not isinstance(row, Mapping) or row.get("status") not in {"success", "error"}
           or not isinstance(row.get("provider_id"), str)
           or not isinstance(row.get("endpoint_family"), str)
           for row in rows):
        return None
    return rows, targets


def _fmp_analyst_grades_health(summary: Mapping[str, Any]) -> tuple[str, str]:
    parsed = _pass2_rows(summary)
    budget = summary.get("endpoint_call_budget") if isinstance(summary, Mapping) else None
    source_artifacts = summary.get("source_artifacts") if isinstance(summary, Mapping) else None
    if parsed is None or not isinstance(budget, Mapping) or not isinstance(source_artifacts, Mapping):
        return "analyst_grades", "missing"
    if source_artifacts.get("active_analyst_source") != "fmp" \
            or source_artifacts.get("analyst_grade_actions_consumed_from") != "fmp_analyst_grade_actions":
        return "analyst_grades", "down"
    rows, _ = parsed
    grade_rows = [row for row in rows
                  if row.get("provider_id") == "financial_modeling_prep" and row.get("endpoint_family") == "grades"]
    calls = budget.get("fmp_grades_calls")
    if type(calls) is not int or calls < 0 or calls != len(grade_rows):
        return "analyst_grades", "down"
    if calls == 0:
        return "analyst_grades", "down"
    successes = sum(1 for row in grade_rows if row.get("status") == "success")
    if successes == calls:
        return "analyst_grades", "ok"
    return "analyst_grades", "down" if successes == 0 else "degraded"


def _yfinance_analyst_grades_health(
    summary: Mapping[str, Any], pass2_summary: Mapping[str, Any],
) -> tuple[str, str]:
    """Validate the yfinance stage summary before projecting the non-critical analyst health family."""
    parsed = _pass2_rows(pass2_summary)
    if parsed is None or not isinstance(summary, Mapping):
        return "analyst_grades", "down"
    _, targets = parsed
    source_artifacts = pass2_summary.get("source_artifacts")
    if not isinstance(source_artifacts, Mapping) \
            or source_artifacts.get("active_analyst_source") != "yfinance" \
            or source_artifacts.get("analyst_grade_actions_consumed_from") != "yfinance_grade_actions":
        return "analyst_grades", "down"
    scope = summary.get("scope")
    clock = summary.get("decision_clock")
    gate = summary.get("preflight_gate")
    execution = summary.get("execution")
    if not all(isinstance(value, Mapping) for value in (scope, clock, gate, execution)):
        return "analyst_grades", "down"
    pass2_clock = pass2_summary.get("decision_clock")
    pass2_gate = pass2_summary.get("preflight_gate")
    pass2_targets = pass2_summary.get("pass2_target_universe")
    if not isinstance(pass2_clock, Mapping) or not isinstance(pass2_gate, Mapping) \
            or not isinstance(pass2_targets, Mapping):
        return "analyst_grades", "down"
    if (
        clock.get("expected_decision_date") != pass2_clock.get("expected_decision_date")
        or clock.get("source_as_of") != pass2_clock.get("source_as_of")
        or gate.get("preflight_summary_path") != pass2_gate.get("preflight_summary_path")
        or gate.get("target_count") != len(targets)
        or pass2_targets.get("target_count") != len(targets)
        or gate.get("target_symbols_in_summary") is not False
    ):
        return "analyst_grades", "down"
    count_fields = (
        "attempted_symbol_count", "successful_symbol_count", "parser_failed_symbol_count",
        "fetch_error_count", "rate_limit_or_crumb_failure_count",
    )
    counts = {field: execution.get(field) for field in count_fields}
    if any(type(value) is not int or value < 0 for value in counts.values()):
        return "analyst_grades", "down"
    attempted = counts["attempted_symbol_count"]
    if sum(counts[field] for field in count_fields[1:]) != attempted or attempted > len(targets):
        return "analyst_grades", "down"
    if any(type(scope.get(field)) is not bool for field in (
        "network_access_performed", "provider_calls_performed",
    )):
        return "analyst_grades", "down"
    if scope["provider_calls_performed"] is not (attempted > 0) \
            or scope["network_access_performed"] is not (attempted > 0):
        return "analyst_grades", "down"
    provider_status = scope.get("provider_status")
    status = scope.get("status")
    if provider_status not in {"ok", "down"} or not isinstance(status, str):
        return "analyst_grades", "down"
    resolver_rejection = execution.get("resolver_rejection")
    advisory_failure = execution.get("advisory_failure")
    dependency_missing = execution.get("dependency_missing")
    if type(dependency_missing) is not bool:
        return "analyst_grades", "down"
    if resolver_rejection is not None and not isinstance(resolver_rejection, Mapping):
        return "analyst_grades", "down"
    if advisory_failure is not None and not isinstance(advisory_failure, Mapping):
        return "analyst_grades", "down"
    forced_down = (
        dependency_missing
        or counts["rate_limit_or_crumb_failure_count"] > 0
        or resolver_rejection is not None
        or advisory_failure is not None
    )
    expected_status = (
        "advisory_stage_neutralized" if advisory_failure is not None else
        "resolver_rejected_neutralized" if resolver_rejection is not None else
        "dependency_missing" if dependency_missing else
        "halted_rate_limit_or_crumb_failure" if counts["rate_limit_or_crumb_failure_count"] else
        "completed_with_fetch_errors" if (
            counts["fetch_error_count"] or counts["parser_failed_symbol_count"]
        ) else "completed"
    )
    if status != expected_status or (provider_status == "down") is not forced_down:
        return "analyst_grades", "down"
    if forced_down or attempted != len(targets):
        return "analyst_grades", "down"
    return "analyst_grades", "ok" if counts["successful_symbol_count"] == attempted else "degraded"


def _analyst_grades_health(
    pass2_summary: Mapping[str, Any], yfinance_summary: Mapping[str, Any] | None,
) -> tuple[str, str]:
    source_artifacts = pass2_summary.get("source_artifacts") if isinstance(pass2_summary, Mapping) else None
    active_source = source_artifacts.get("active_analyst_source") if isinstance(source_artifacts, Mapping) else None
    if active_source == "yfinance":
        if yfinance_summary is None:
            return "analyst_grades", "down"
        return _yfinance_analyst_grades_health(yfinance_summary, pass2_summary)
    if active_source == "fmp":
        return _fmp_analyst_grades_health(pass2_summary)
    return "analyst_grades", "down"


def _sec_offering_health(summary: Mapping[str, Any]) -> tuple[str, str]:
    parsed = _pass2_rows(summary)
    if parsed is None:
        return "sec_offering_audit", "down"
    rows, targets = parsed
    target_set = set(targets)
    seen: dict[str, str] = {}
    malformed = False
    for row in rows:
        if row.get("provider_id") != "sec_edgar" or row.get("endpoint_family") != "submissions":
            continue
        symbol = row.get("symbol")
        if type(symbol) is not str or symbol not in target_set or symbol in seen:
            malformed = True
            continue
        seen[symbol] = row.get("status")
    if malformed or set(seen) != target_set or any(status != "success" for status in seen.values()):
        return "sec_offering_audit", "down"
    return "sec_offering_audit", "ok"


def _massive_events_health(summary: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(summary, Mapping):
        return "massive_events", "missing"
    coverage = summary.get("massive_batch_coverage")
    if not isinstance(coverage, Mapping) or set(coverage) != set(_EVENT_FAMILIES):
        return "massive_events", "missing"
    complete = 0
    for family in _EVENT_FAMILIES:
        item = coverage.get(family)
        if not isinstance(item, Mapping):
            return "massive_events", "down"
        page_count = item.get("page_count")
        result_count = item.get("result_count")
        query_window = item.get("query_window")
        if (
            type(page_count) is not int
            or page_count < 0
            or type(result_count) is not int
            or result_count < 0
            or not isinstance(query_window, Mapping)
            or not query_window.get("date_field")
            or not query_window.get("date_from")
            or not query_window.get("date_to")
        ):
            return "massive_events", "down"
        status = item.get("status")
        exhausted = item.get("pagination_exhausted")
        if status == "complete" and exhausted is True:
            complete += 1
        elif status == "incomplete" and isinstance(item.get("failure_reason"), str) and item["failure_reason"]:
            continue
        else:
            return "massive_events", "down"
    if complete == len(_EVENT_FAMILIES):
        return "massive_events", "ok"
    if complete == 0:
        return "massive_events", "down"
    return "massive_events", "degraded"


def _vix_health(summary: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(summary, Mapping):
        return "fmp_vix", "missing"
    status = summary.get("http_status")
    value = summary.get("vix_value")
    regime = summary.get("vix_regime")
    unknown = summary.get("vix_regime_is_unknown")
    if type(status) is not int or type(unknown) is not bool:
        return "fmp_vix", "missing"
    if status != 200 or type(value) not in (int, float) or isinstance(value, bool):
        return "fmp_vix", "down"
    try:
        numeric = float(value)                 # a 400-digit JSON int overflows float(); that is data, not a crash
    except (OverflowError, ValueError):
        return "fmp_vix", "down"
    if not math.isfinite(numeric):
        return "fmp_vix", "down"
    if regime not in (*REGIMES, UNKNOWN) or unknown is not (regime == UNKNOWN):
        return "fmp_vix", "degraded"
    return "fmp_vix", "degraded" if unknown else "ok"


def derive_capstone_provider_health(stage_results: Mapping[str, Any]) -> dict[str, str]:
    """Project exactly eight raw health families from same-run producer results.

    The function is pure and closed-world: missing or malformed producer facts never become ``ok``.  It does not
    inspect resolved analyst actions, and it performs no provider call.
    """
    if not isinstance(stage_results, Mapping):
        stage_results = {}
    universe = stage_results.get("universe_fetch")
    momentum = stage_results.get("momentum_fetch")
    sic = stage_results.get("sic_fetch")
    pass2 = stage_results.get("pass2_fetch")
    yfinance = stage_results.get("yfinance_grades_fetch") if "yfinance_grades_fetch" in stage_results else None
    vix = stage_results.get("vix_regime")
    pairs = (
        _universe_health(universe),
        _universe_market_cap_health(universe),
        _momentum_health(momentum),
        _sic_health(sic),
        _analyst_grades_health(pass2, yfinance),
        _sec_offering_health(pass2),
        _massive_events_health(pass2),
        _vix_health(vix),
    )
    return dict(pairs)


def derive_provider_health(summary) -> dict[str, str]:
    """Compatibility name delegating to the one canonical eight-family projector."""
    return derive_capstone_provider_health({"pass2_fetch": summary})


def _read_json_or_empty(path: Path) -> dict[str, Any]:
    if not isinstance(path, (str, Path)):
        return {}
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_provider_health(ctx) -> None:
    """Write the raw health map; production uses the already-issued receipt as the sole aggregation point."""
    receipt = getattr(ctx, "research_live_capability", None)
    summary_targets = _stage_summary_targets(ctx)
    producer_paths = {
        "universe_fetch": getattr(
            ctx, "universe_summary_path",
            ROOT / "docs" / f"us_short_universe_fetch_summary_{ctx.decision_date}.json",
        ),
        "momentum_fetch": summary_targets["momentum_fetch"],
        "sic_fetch": summary_targets["sic_classification"],
        "pass2_fetch": summary_targets["pass2"],
        "yfinance_grades_fetch": summary_targets["yfinance_grades_fetch"],
        "vix_regime": getattr(ctx, "vix_regime_summary_path", None),
    }
    if receipt is not None:
        from engine.us_short_provider_health import validate_provider_health_facts

        for stage_name in _HEALTH_PRODUCER_STAGES:
            path = producer_paths[stage_name]
            if not isinstance(path, (str, Path)) or not Path(path).is_file():
                raise RunOriginError(f"receipt-bound provider summary is missing: {stage_name}")
            summary = _read_json_or_empty(Path(path))
            if not summary:
                raise RunOriginError(f"receipt-bound provider summary is unreadable: {stage_name}")
            require_research_live_provider_summary(receipt, stage_name, summary)
            if stage_name == "pass2_fetch" and summary.get("schema_name") == "us_short_batch5_full_candidate_live_source_packet_summary":
                _pass2._validate_summary_against_schema(summary)
        facts = tuple(receipt.provider_health_facts)
        if not validate_provider_health_facts(facts):
            raise ValueError("receipt provider-health facts are not the exact eight-family contract")
        health = dict(facts)
    else:
        # Offline/direct unit seam only.  It still delegates to the same projector and never invents a healthy family.
        pass2_summary = _read_json_or_empty(producer_paths["pass2_fetch"])
        if pass2_summary.get("schema_name") == "us_short_batch5_full_candidate_live_source_packet_summary":
            # A persisted full Pass2 summary is a real consumer boundary: re-run its schema + analyst-source
            # semantic validator before allowing any health family to consume it.  On this seam a rejected
            # summary must DEGRADE (the pass2 families go missing/down and the map is still written), not abort
            # the stage — aborting leaves no provider_health.json at all.  The receipt branch above still raises.
            try:
                _pass2._validate_summary_against_schema(pass2_summary)
            except _pass2.FullCandidateLiveSourcePacketError:
                pass2_summary = {}
        health_inputs = {
            "universe_fetch": _read_json_or_empty(producer_paths["universe_fetch"]),
            "momentum_fetch": _read_json_or_empty(producer_paths["momentum_fetch"]),
            "sic_fetch": _read_json_or_empty(producer_paths["sic_fetch"]),
            "pass2_fetch": pass2_summary,
            "vix_regime": _read_json_or_empty(producer_paths["vix_regime"]),
        }
        yfinance_path = producer_paths["yfinance_grades_fetch"]
        if isinstance(yfinance_path, (str, Path)) and Path(yfinance_path).is_file():
            health_inputs["yfinance_grades_fetch"] = _read_json_or_empty(yfinance_path)
        health = derive_capstone_provider_health(health_inputs)
    ctx.provider_health_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(health, ensure_ascii=False, indent=2) + "\n"
    tmp = ctx.provider_health_path.with_name(ctx.provider_health_path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(ctx.provider_health_path)
