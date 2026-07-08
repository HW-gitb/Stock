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

from runners import us_short_batch5_full_candidate_live_source_packet as _pass2
from runners import us_short_batch5_full_candidate_pass2_preflight as _preflight
from runners import us_short_batch5_full_candidate_projection_inputs as _proj
from runners import us_short_batch5_full_universe_momentum_fetch as _mom_fetch
from runners import us_short_batch5_full_universe_momentum_producer as _mom_prod
from runners import us_short_batch5_full_universe_sec_sic_classification_fetch as _sic
from runners import us_short_batch5_full_universe_theme_producer as _theme
from runners import us_short_batch5_to_batch4_weekend_e2e as _bridge
from runners import us_short_universe_fetch as _universe


def _summary_path(ctx, name: str) -> Path:
    """A gitignored per-run summary sidecar under state/us_short/ (not the tracked docs/ milestone summary)."""
    return ctx.state_dir / f"us_short_batch5_capstone_{ctx.decision_date}_{name}_summary.json"


# --- GATED stages (live provider fetch; SR-PROVIDER-001) ---

def run_universe(ctx) -> dict[str, Any]:
    return _universe.run_fetch(
        now_et=ctx.now_et,
        candidate_list_path=ctx.candidate_path,
        generated_at=ctx.generated_at,
        confirm_user_authorization=True,
    )


def run_momentum_fetch(ctx) -> dict[str, Any]:
    return _mom_fetch.run_fetch(
        candidate_artifact_path=ctx.candidate_path,
        series_packet_path=ctx.series_packet_path,
        summary_path=_summary_path(ctx, "momentum_fetch"),
        generated_at=ctx.generated_at,
        confirm_user_authorization=True,
    )


def run_sic_fetch(ctx) -> dict[str, Any]:
    return _sic.run_fetch(
        candidate_artifact_path=ctx.candidate_path,
        classification_packet_path=ctx.classification_packet_path,
        summary_path=_summary_path(ctx, "sic_classification"),
        generated_at=ctx.generated_at,
        confirm_user_authorization=True,
    )


def run_pass2_fetch(ctx) -> dict[str, Any]:
    summary = _pass2.run_full_candidate_live_source_packet(
        preflight_summary_path=ctx.preflight_summary_path,
        expected_total_call_budget=_preflight_call_budget(ctx),
        source_artifact_prefix=ctx.source_artifact_prefix,
        context_components_output_path=ctx.context_components_path,
        summary_path=_summary_path(ctx, "pass2"),
        confirm_user_authorization=True,
        run_data_context=True,
        generated_at=ctx.generated_at,
        observed_at=ctx.observed_at,
        provider_pace_seconds=ctx.provider_pace_seconds,
        max_retries_per_call=ctx.max_retries_per_call,
        retry_backoff_seconds=ctx.retry_backoff_seconds,
    )
    return summary


# --- OFFLINE stages (pure / local; no network) ---

def run_momentum_producer(ctx) -> dict[str, Any]:
    return _mom_prod.run_packet(
        candidate_artifact_path=ctx.candidate_path,
        series_packet_path=ctx.series_packet_path,
        output_projection_path=ctx.momentum_projection_path,
        summary_path=_summary_path(ctx, "momentum_producer"),
        generated_at=ctx.generated_at,
    )


def run_theme_producer(ctx) -> dict[str, Any]:
    return _theme.run_packet(
        candidate_artifact_path=ctx.candidate_path,
        series_packet_path=ctx.series_packet_path,
        classification_packet_path=ctx.classification_packet_path,
        output_projection_path=ctx.theme_projection_path,
        summary_path=_summary_path(ctx, "theme_producer"),
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
        summary_path=_summary_path(ctx, "projection_inputs"),
        generated_at=ctx.generated_at,
    )


def run_pass2_preflight(ctx) -> dict[str, Any]:
    return _preflight.run_preflight(
        candidate_artifact_path=ctx.candidate_path,
        expected_decision_date=ctx.decision_date,
        momentum_projection_path=ctx.merged_momentum_path,
        theme_projection_path=ctx.merged_theme_path,
        summary_path=ctx.preflight_summary_path,
        confirm_user_authorization=True,
        generated_at=ctx.generated_at,
    )


def run_weekly_bridge(ctx) -> dict[str, Any]:
    """Derive HONEST provider_health from the actual Pass2 outcome, then bridge the source packet → weekly report /
    action table. provider_health is NOT hand-written: fmp = ok iff grades were obtained, sec_edgar = ok iff SEC
    submissions were obtained; a down critical source makes the orchestrator emit nothing (design §3.2)."""
    _write_provider_health(ctx)
    return _bridge.run_e2e(
        source_packet_path=ctx.source_packet_path,
        batch4_template_path=ctx.batch4_template_path,
        account_state_path=ctx.account_state_path,
        provider_health_path=ctx.provider_health_path,
        private_root=ctx.private_root,
        now_et=ctx.now_et,
        context_components_path=ctx.context_components_path,
        run_mode="live",
        bootstrap_lifecycle=True,
        generated_at=ctx.generated_at,
    )


# --- honest provider_health derivation from the real Pass2 summary ---

def _write_provider_health(ctx) -> None:
    summary = json.loads(_summary_path(ctx, "pass2").read_text(encoding="utf-8"))
    budget = summary.get("endpoint_call_budget", {})
    results = summary.get("endpoint_results", [])

    def _family_ok(provider: str, family: str) -> bool:
        # ok iff at least one endpoint of this (provider, family) came back ok=True in the run.
        return any(
            r.get("provider_id") == provider and r.get("endpoint_family") == family and r.get("status") == "success"
            for r in results
        )

    # Fallback to the family CALL counts if endpoint_results lacks per-row provider/family (draft-tolerant).
    fmp_ok = _family_ok("financial_modeling_prep", "grades") or (
        budget.get("fmp_grades_calls", 0) > 0 and budget.get("endpoint_error_count", 1) == 0)
    sec_ok = _family_ok("sec_edgar", "submissions") or budget.get("sec_submissions_calls", 0) > 0
    health = {"fmp": "ok" if fmp_ok else "down", "sec_edgar": "ok" if sec_ok else "down"}
    ctx.provider_health_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.provider_health_path.write_text(json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _preflight_call_budget(ctx) -> int:
    """The Pass2 authorized call budget = the forecast recomputed from the reviewed preflight (1 SEC mapping +
    target_count × 5 endpoints). Read it from the preflight summary the orchestrator just produced."""
    summary = json.loads(ctx.preflight_summary_path.read_text(encoding="utf-8"))
    forecast = summary.get("endpoint_call_forecast", {})
    total = forecast.get("total_calls_for_pass2_target_cut")
    if not isinstance(total, int) or total < 1:
        raise ValueError("preflight summary missing a valid total_calls_for_pass2_target_cut")
    return total
