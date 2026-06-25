# -*- coding: utf-8 -*-
"""US-short weekend-pipeline lifecycle eval stage — batch4 slice 4d-ii-l (lifecycle-eval, 先于 render).

Design authority: docs/us_short_system_design.md §13 (`us_short_lifecycle_eval` 运行时阶段) / §13.1 #20 /
§12.2 (升级闸防自欺) / §2.1 (idempotent forward) / §11.6 (lifecycle 隐私) / §18.1 #11 #20 / §18.2 batch4 slice 4d.

The runtime LIFECYCLE EVAL stage. §13 makes this an INDEPENDENT stage that MUST run BEFORE the weekly_report
render (the hard ordering constraint, so the report never misses a §13.1 item that came due this run). This
slice WIRES the already-built lifecycle family into that one stage:

    load_lifecycle_register (store, §18.0 P0 private-path guard + §2.1/§18.1#20 stale-aware load + re-validate)
      → build_lifecycle_readiness (readiness, tracked de-identified due scan via evaluate_lifecycle)
      → [optionally write the readiness artifact]
      → lifecycle_banner (render, GBK-safe one-line runtime banner)

It returns the readiness + banner for the weekly_report renderer (4d-ii-m) to render the §11.2 lifecycle
section / top banner and reconcile the §11.2 count; the eval ITSELF runs here, before that render. Upgrade
eligibility is SURFACED, never acted on (§12.2: an upgrade always needs a USER decision, never
auto-production). This stage is a thin orchestrator — every fail-closed gate it relies on lives in the
called single-source modules and is NOT re-implemented here:

  * the §18.0 P0 private-path guard (a relative / in-repo-non-gitignored register source is refused) and the
    §2.1/§18.1#20 stale fail-closed (a persisted as_of NEWER than the run decision_date, an unreadable /
    corrupt / not-§13-clean register) are inside `load_lifecycle_register`;
  * the readiness de-identification gate (no ticker/$ on a tracked artifact) is inside the readiness module;
  * the banner contract / GBK-safe ASCII floor is inside the render module.

The register's WRITE (accumulate this run's forward observations) is a SEPARATE path
(`accumulate_lifecycle_observation` + `write_lifecycle_register`); this stage only READS + evaluates +
surfaces. In a real run the register exists (it enrols every §13.1 item); a missing one fails closed (a
setup error, never a silent empty scan). Pure/offline beyond the register read + the optional tracked
readiness write; no provider/live/network; no A-share crossing.
"""
from __future__ import annotations

from engine.us_short_lifecycle_readiness import build_lifecycle_readiness, write_lifecycle_readiness
from engine.us_short_lifecycle_render import lifecycle_banner
from engine.us_short_lifecycle_store import LIFECYCLE_REGISTER_PATH, load_lifecycle_register


def run_lifecycle_eval_stage(*, decision_date, register_path=None, readiness_out_path=None,
                             calibration=None, authority=None):
    """4d-ii-l lifecycle eval runtime stage — runs BEFORE the weekly_report render (§13 hard ordering).

    Loads the persisted lifecycle_register (stale-checked against ``decision_date`` — the §18.0 P0
    private-path guard + the §2.1/§18.1#20 stale / not-clean fail-closed live inside ``load_lifecycle_register``),
    evaluates the §13.1 due scan into the tracked de-identified readiness artifact, optionally writes it, and
    renders the GBK-safe runtime banner.

    decision_date = the run's canonical decision_date; passed as ``expected_as_of`` so a register persisted
        AHEAD of this run (a stale / misaligned bucket) fails closed (§2.1 / §18.1 #20).
    register_path = the lifecycle_register source; defaults to the canonical private location
        ``LIFECYCLE_REGISTER_PATH`` (state/us_short/lifecycle/, gitignored). An external absolute path is
        allowed (the user's own private location); a relative / in-repo-non-gitignored path is refused by the
        §18.0 guard.
    readiness_out_path = if given, the de-identified readiness artifact is written there (tracked-safe — the
        readiness schema is its own de-identification gate, so no §18.0 guard is needed); if None, the
        readiness is built but not persisted.
    calibration / authority = injectable §13 governance (tests); by default the frozen presets are read.

    Returns {"decision_date": str, "readiness": <de-identified readiness>, "banner": <GBK-safe one-line str>}.
    Raises (propagated, single-source): ``PrivatePathError`` (non-private register source),
    ``StaleLifecycleArtifactError`` (missing / corrupt / stale-ahead register),
    ``LifecycleRegisterError`` (not-§13-clean register), ``LifecycleReadinessError`` (readiness gate)."""
    register = load_lifecycle_register(
        register_path if register_path is not None else LIFECYCLE_REGISTER_PATH,
        expected_as_of=decision_date, calibration=calibration, authority=authority)

    # readiness = the de-identified due scan (build_lifecycle_readiness runs evaluate_lifecycle internally and
    # self-checks the de-identification + consistency gate). The banner reads the SAME readiness (it carries the
    # full eval-result contract lifecycle_banner validates), so the due scan is evaluated exactly once.
    readiness = build_lifecycle_readiness(register, calibration=calibration, authority=authority)
    if readiness_out_path is not None:
        write_lifecycle_readiness(readiness, readiness_out_path)
    banner = lifecycle_banner(readiness)

    return {"decision_date": decision_date, "readiness": readiness, "banner": banner}
