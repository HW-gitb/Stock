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

from engine.us_short_run_origin import _CAPSTONE_RESEARCH_LIVE_CAPABILITY
from runners import us_short_batch5_full_candidate_live_source_packet as _pass2
from runners import us_short_batch5_full_candidate_pass2_preflight as _preflight
from runners import us_short_batch5_full_candidate_projection_inputs as _proj
from runners import us_short_batch5_full_universe_momentum_fetch as _mom_fetch
from runners import us_short_batch5_full_universe_momentum_producer as _mom_prod
from runners import us_short_batch5_full_universe_sec_sic_classification_fetch as _sic
from runners import us_short_batch5_full_universe_theme_producer as _theme
from runners import us_short_batch5_to_batch4_weekend_e2e as _bridge
from runners import us_short_universe_fetch as _universe


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
        "sic_classification": _p(_sic.SUMMARY_SAMPLE_REL_ROOT, "sic_classification"),
        "theme_producer": _p(_theme.SAMPLE_REL_ROOT, "theme_producer"),
        "projection_inputs": _p(_proj.SAMPLE_REL_ROOT, "projection_inputs"),
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
    summary = _pass2.run_full_candidate_live_source_packet(
        preflight_summary_path=ctx.preflight_summary_path,
        expected_total_call_budget=_preflight_call_budget(ctx),
        source_artifact_prefix=ctx.source_artifact_prefix,
        context_components_output_path=ctx.context_components_path,
        output_data_context_path=ctx.data_context_path,   # decision-date-keyed (else the runner default is a stale 20260706 name)
        summary_path=_stage_summary_targets(ctx)["pass2"],
        confirm_user_authorization=ctx.confirm_user_authorization,
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
        summary_path=_stage_summary_targets(ctx)["momentum_producer"],
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
    return _preflight.run_preflight(
        candidate_artifact_path=ctx.candidate_path,
        expected_decision_date=ctx.decision_date,
        momentum_projection_path=ctx.merged_momentum_path,
        theme_projection_path=ctx.merged_theme_path,
        summary_path=ctx.preflight_summary_path,
        confirm_user_authorization=ctx.confirm_user_authorization,
        generated_at=ctx.generated_at,
    )


def run_weekly_bridge(ctx) -> dict[str, Any]:
    """Derive HONEST provider_health from the actual Pass2 outcome, then bridge the source packet → weekly report /
    action table. provider_health is NOT hand-written: fmp = ok iff >=_HEALTH_MIN_SUCCESS_COVERAGE of grades calls
    succeeded, sec_edgar = ok iff the same fraction of SEC submissions succeeded (a success-COVERAGE threshold, NOT
    any-single-success); a down critical source makes the orchestrator emit nothing (design §3.2)."""
    _write_provider_health(ctx)
    return _bridge.run_e2e(
        source_packet_path=ctx.source_packet_path,
        batch4_template_path=ctx.batch4_template_path,
        account_state_path=ctx.account_state_path,
        provider_health_path=ctx.provider_health_path,
        private_root=ctx.private_root,
        now_et=ctx.now_et,
        context_components_path=ctx.context_components_path,
        run_mode="research_live",   # real provider data, pre-authoritative research report (NOT operational; live→batch5)
        # research_live is CAPSTONE-INTERNAL (R-USSHORT-REVIEWQ-CAT1 Required A): the capstone mints the process-internal
        # capability ONLY on an authorized run (it refuses before any stage unless ctx.confirm_user_authorization, so
        # reaching this bridge attests the gated universe/momentum/SIC/Pass2 fetch ran under per-execution authorization).
        # run_e2e refuses research_live for any caller lacking this exact object, so a standalone/fixture bridge call (or
        # a forged True) fails closed. Unauthorized ctx → None → fail closed.
        _research_live_capability=(_CAPSTONE_RESEARCH_LIVE_CAPABILITY if ctx.confirm_user_authorization is True else None),
        bootstrap_lifecycle=True,
        generated_at=ctx.generated_at,
    )


# --- honest provider_health derivation from the real Pass2 summary ---

# A source reads "ok" only if at least this fraction of its ATTEMPTED endpoint calls came back success. This is a
# coverage threshold, deliberately NOT "any single success" / "any call attempted": a run whose grades mostly 429'd
# (or whose SEC submissions mostly failed) is NOT a healthy source, so it must NO-EMIT rather than emit a "healthy"
# report on near-zero real coverage. 0.5 = a simple majority; tune here if the operational bar changes.
_HEALTH_MIN_SUCCESS_COVERAGE = 0.5


def _write_provider_health(ctx) -> None:
    # Fail closed on a malformed/unreadable summary: any read / parse / container-shape problem -> empty results ->
    # both sources 'down' (no emit), NEVER a crash. This is the gate's OWN defense-in-depth, not a reliance on the
    # orchestrator's blanket stage-exception handler.
    try:
        summary = json.loads(_stage_summary_targets(ctx)["pass2"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        summary = {}
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

    health = {
        "fmp": "ok" if _coverage_ok("financial_modeling_prep", "grades") else "down",
        "sec_edgar": "ok" if _coverage_ok("sec_edgar", "submissions") else "down",
    }
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
