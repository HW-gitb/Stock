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

import json
from pathlib import Path
from typing import Any

from engine.us_short_run_origin import require_research_live_provider_summary
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


def _require_frozen_funnel_authorization(ctx) -> None:
    if (
        type(getattr(ctx, "authorized_momentum_top_k", None)) is not int
        or isinstance(ctx.authorized_momentum_top_k, bool)
        or not 1 <= ctx.authorized_momentum_top_k <= 250
        or type(getattr(ctx, "authorized_pass2_call_budget", None)) is not int
        or isinstance(ctx.authorized_pass2_call_budget, bool)
        or ctx.authorized_pass2_call_budget < 1
    ):
        raise PermissionError("Pass2 stages require a frozen K and positive exact call budget in the run context")


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
    _require_frozen_funnel_authorization(ctx)
    summary = _pass2.run_full_candidate_live_source_packet(
        preflight_summary_path=ctx.preflight_summary_path,
        expected_total_call_budget=ctx.authorized_pass2_call_budget,
        authorized_momentum_top_k=ctx.authorized_momentum_top_k,
        source_artifact_prefix=ctx.source_artifact_prefix,
        context_components_output_path=ctx.context_components_path,
        output_data_context_path=ctx.data_context_path,   # decision-date-keyed (else the runner default is a stale 20260706 name)
        overextension_projection_path=ctx.overextension_projection_path,
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
    )
    return summary


def run_yfinance_grades_fetch(ctx) -> dict[str, Any]:
    _require_ctx_authorization(ctx)
    return _yfinance_grades.run_yfinance_grades_fetch(
        preflight_summary_path=ctx.preflight_summary_path,
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
    _require_frozen_funnel_authorization(ctx)
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


def run_weekly_bridge(ctx) -> dict[str, Any]:
    """Derive HONEST provider_health from the actual Pass2 outcome, then bridge the source packet → weekly report /
    action table. provider_health is NOT hand-written: fmp = ok iff >=_HEALTH_MIN_SUCCESS_COVERAGE of grades calls
    succeeded, sec_edgar = ok iff the same fraction of SEC submissions succeeded (a success-COVERAGE threshold, NOT
    any-single-success); a down critical source makes the orchestrator emit nothing (design §3.2)."""
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
    return _bridge.run_e2e(
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
        projection_binding_expectations=_bridge.FULL_CANDIDATE_LIVE_PROJECTION_BINDING,
    )


# --- honest provider_health derivation from the real Pass2 summary ---

# A source reads "ok" only if at least this fraction of its ATTEMPTED endpoint calls came back success. This is a
# coverage threshold, deliberately NOT "any single success" / "any call attempted": a run whose grades mostly 429'd
# (or whose SEC submissions mostly failed) reports that source as down instead of pretending coverage is healthy.
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

    return {
        "fmp": "ok" if _coverage_ok("financial_modeling_prep", "grades") else "down",
        "sec_edgar": "ok" if _coverage_ok("sec_edgar", "submissions") else "down",
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
