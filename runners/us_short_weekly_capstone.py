# -*- coding: utf-8 -*-
"""US-short weekly one-click capstone orchestrator (cut ⑥ closure) — SKELETON / draft.

Design authority: docs/us_short_system_design.md §2.1 (canonical decision_date / 盘中死区 fail-closed /
价格基准 / 幂等) + §18.3 (v1 engineering closure: "a weekly one-click path can use authorized real data
inputs to produce an honest weekly report and action table"). This module ONLY orchestrates the already-built
per-stage runners into ONE ordered path; it restates no selection/PIT semantics (single authority = the stages).

WHAT THIS IS. The nine v1 stages already exist as separate runners (universe fetch → momentum fetch/producer →
SEC-SIC fetch/theme producer → projection-inputs → Pass2 preflight → Pass2 live source packet → batch5→batch4
bridge). Today a weekly run means invoking ~7 commands by hand. This capstone chains them behind one entry with:
  * CANONICAL anchoring (§2.1): resolve decision_date + price_basis_date ONCE from the frozen NYSE calendar and
    thread the SAME dates through every stage; an intraday `now_et` fails closed (OutOfWindowError → no run).
  * A working offline DRY-RUN: print the full plan (every stage, gated-vs-offline, the exact input/output artifact
    paths, and which stages will hit a provider) WITHOUT any fetch — so the operator sees the gated boundary first.
  * GATED-stage authorization: the 4 provider stages (universe / momentum-fetch / SIC-fetch / Pass2) run live ONLY
    with an explicit per-execution `confirm_user_authorization` (the one-click run's single SR-PROVIDER-001 auth);
    they run SEQUENTIALLY (§18.3 Batch II "do not parallelize provider/live execution"). This is the RUN-TIME
    closure of the one-click goal, distinct from the BUILD-TIME per-cut review discipline.
  * FAIL-FAST with a stage label + no silent partial success; a gated stage that returns DEGRADED coverage
    (e.g. FMP 429) does NOT abort — the run proceeds to the bridge, whose provider_health gate decides emit/no-emit
    (exactly the honest 2026-07-08 behaviour).
  * HONEST provider_health DERIVED from the actual Pass2 outcome (fmp = ok iff grades were obtained, sec_edgar = ok
    iff submissions were obtained) — the health gate cannot be hand-waved past.

SKELETON status: the orchestration framework (canonical anchor, stage sequencing, dry-run plan, auth gating,
fail-fast, provider-health derivation, path threading) is implemented and offline-tested (dry-run + a full injected-
fake chain). The per-stage `run` adapters call the real runners with dates/paths from the context; that live wiring
gets its first real exercise on the next fresh-quota run (the gated stages cannot be network-tested offline). No
provider call, production, DataHub, ship-gate, broker path, or A-share crossing is authorized here.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_canonical_asof import OutOfWindowError, resolve_canonical_asof  # noqa: E402
from engine.us_short_market_calendar import load_market_calendar, sessions_for_window  # noqa: E402

CALENDAR_PRESET = ROOT / "presets" / "us_short_market_calendar_2026_2027.json"
STATE_DIR = ROOT / "state" / "us_short"
# The preflight summary is BOTH stage-7's OUTPUT and stage-8's preflight INPUT, so it must live where BOTH runners'
# fail-closed allowlists accept it. This mirrors
# runners.us_short_batch5_full_candidate_pass2_preflight.PROVIDER_SAMPLE_REL_ROOT (a conformance test pins equality)
# — a per-run gitignored sidecar under the reviewed provider_samples/ tree, decision-date-keyed in the filename.
_PREFLIGHT_SAMPLE_REL_ROOT = Path("provider_samples") / "us_short_batch5_full_candidate_pass2_preflight_20260706"


class WeeklyCapstoneError(RuntimeError):
    """Any capstone-orchestration failure (canonical resolution, a missing prerequisite, a stage abort)."""


# ---------------------------------------------------------------------------
# Canonical anchoring (§2.1) + the run context that threads dates/paths through every stage
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapstoneContext:
    """Immutable per-run anchor: the ONE canonical decision_date + price_basis_date (§2.1) plus the run clocks and
    the private/output roots. Every stage reads its input/output paths from here, so no stage re-resolves dates."""

    decision_date: str          # YYYYMMDD — canonical upcoming trading session (§2.1)
    price_basis_date: str       # YYYYMMDD — latest settled session (price basis, §2.1)
    now_et: datetime            # ET wall-clock decision instant (pre-open)
    generated_at: str           # RFC3339 — artifact generation clock
    observed_at: str            # RFC3339 — PIT observation instant (== generated_at; < decision open)
    private_root: Path          # provably-private root for weekly_report.md / action_table.csv
    batch4_template_path: Path
    account_state_path: Path
    confirm_user_authorization: bool = False
    provider_pace_seconds: float = 0.0
    max_retries_per_call: int = 0
    retry_backoff_seconds: float = 0.0
    state_dir: Path = STATE_DIR
    sample_root: Path = ROOT   # repo root that the runners' provider_samples/ allowlists resolve against (tests inject a tempdir)

    # --- derived artifact paths (all gitignored under state/us_short/, keyed by the canonical dates) ---
    def _s(self, name: str) -> Path:
        return self.state_dir / name

    @property
    def candidate_path(self) -> Path:
        return self._s(f"candidate_universe_{self.decision_date}.json")

    @property
    def series_packet_path(self) -> Path:
        return self._s(f"us_short_batch5_full_universe_momentum_series_{self.price_basis_date}_packet.json")

    @property
    def momentum_projection_path(self) -> Path:
        return self._s(f"us_short_batch5_full_universe_momentum_{self.price_basis_date}_momentum.json")

    @property
    def classification_packet_path(self) -> Path:
        return self._s(f"us_short_batch5_full_universe_sector_classification_{self.price_basis_date}_packet.json")

    @property
    def theme_projection_path(self) -> Path:
        return self._s(f"us_short_batch5_full_universe_theme_{self.price_basis_date}_theme.json")

    @property
    def merged_momentum_path(self) -> Path:
        return self._s(f"us_short_batch5_capstone_projection_inputs_{self.decision_date}_momentum.json")

    @property
    def merged_theme_path(self) -> Path:
        return self._s(f"us_short_batch5_capstone_projection_inputs_{self.decision_date}_theme.json")

    @property
    def preflight_summary_path(self) -> Path:
        # stage-7 preflight OUTPUT + stage-8 pass2 preflight INPUT — lives under the preflight runner's accepted
        # provider_samples/ root (both runners' allowlists accept it), NOT under state/us_short/ (which the runners
        # reject). Gitignored per-run sidecar, decision-date-keyed.
        return self.sample_root / _PREFLIGHT_SAMPLE_REL_ROOT / f"us_short_batch5_capstone_pass2_preflight_{self.decision_date}_summary.json"

    @property
    def source_artifact_prefix(self) -> Path:
        return self._s(f"us_short_batch5_capstone_{self.decision_date}")

    @property
    def source_packet_path(self) -> Path:
        return self._s(f"us_short_batch5_capstone_{self.decision_date}_source_packet.json")

    @property
    def context_components_path(self) -> Path:
        return self._s(f"us_short_batch5_capstone_{self.decision_date}_context_components.json")

    @property
    def data_context_path(self) -> Path:
        return self._s(f"us_short_batch5_capstone_{self.decision_date}_data_context.json")

    @property
    def provider_health_path(self) -> Path:
        return self._s(f"us_short_batch5_capstone_{self.decision_date}_provider_health.json")


def resolve_capstone_context(
    *,
    now_et: datetime,
    private_root: Path,
    batch4_template_path: Path,
    account_state_path: Path,
    calendar_path: Path = CALENDAR_PRESET,
    confirm_user_authorization: bool = False,
    provider_pace_seconds: float = 0.0,
    max_retries_per_call: int = 0,
    retry_backoff_seconds: float = 0.0,
    state_dir: Path = STATE_DIR,
    sample_root: Path = ROOT,
) -> CapstoneContext:
    """Resolve the §2.1 canonical decision_date + price_basis_date from `now_et` and the frozen calendar, and build
    the run context. Fail-closed: an intraday `now_et` (session dead zone) raises WeeklyCapstoneError (no run)."""
    if not isinstance(now_et, datetime) or now_et.tzinfo is not None:
        raise WeeklyCapstoneError("now_et must be a naive ET wall-clock datetime (Beijing→ET conversion upstream)")
    calendar = load_market_calendar(calendar_path)
    sessions = sessions_for_window(now_et.strftime("%Y%m%d"), calendar=calendar)
    try:
        resolved = resolve_canonical_asof(now_et, sessions)
    except OutOfWindowError as exc:
        raise WeeklyCapstoneError(
            "now_et is inside a trading session (§2.1 intraday dead zone) — the weekly run must be pre-open / "
            "post-close; fail-closed, no canonical decision_date") from exc
    except ValueError as exc:
        raise WeeklyCapstoneError(f"canonical decision_date resolution failed: {exc}") from exc
    generated_at = now_et.strftime("%Y-%m-%dT%H:%M:%S")  # naive ET; a later thin runner may pass a tz-aware instant
    return CapstoneContext(
        decision_date=resolved["decision_date"],
        price_basis_date=resolved["price_basis_date"],
        now_et=now_et,
        generated_at=generated_at,
        observed_at=generated_at,
        private_root=Path(private_root),
        batch4_template_path=Path(batch4_template_path),
        account_state_path=Path(account_state_path),
        confirm_user_authorization=confirm_user_authorization,
        provider_pace_seconds=provider_pace_seconds,
        max_retries_per_call=max_retries_per_call,
        retry_backoff_seconds=retry_backoff_seconds,
        state_dir=Path(state_dir),
        sample_root=Path(sample_root),
    )


# ---------------------------------------------------------------------------
# Stage descriptors + the ordered pipeline
# ---------------------------------------------------------------------------

@dataclass
class Stage:
    """One pipeline step. `gated` = performs a live provider fetch (SR-PROVIDER-001). `inputs`/`outputs` are the
    artifact paths (for the dry-run plan + prerequisite/output validation). `run(ctx)` executes it and returns a
    small result dict; it is only called on a live run and only after the gated-auth check for gated stages."""

    name: str
    gated: bool
    inputs: Callable[[CapstoneContext], list[Path]]
    outputs: Callable[[CapstoneContext], list[Path]]
    run: Callable[[CapstoneContext], dict[str, Any]]


def default_pipeline() -> list[Stage]:
    """The 9-stage v1 weekly pipeline in dependency order. Each `run` adapter calls the corresponding real runner
    with dates/paths from the context (imported lazily so an offline dry-run / a stage-injected test never imports a
    provider runner it will not call)."""
    from runners import us_short_weekly_capstone_stages as st  # thin adapters over the real runners
    return [
        Stage("universe_fetch", True, lambda c: [], lambda c: [c.candidate_path], st.run_universe),
        Stage("momentum_fetch", True, lambda c: [c.candidate_path], lambda c: [c.series_packet_path], st.run_momentum_fetch),
        Stage("momentum_producer", False, lambda c: [c.candidate_path, c.series_packet_path], lambda c: [c.momentum_projection_path], st.run_momentum_producer),
        Stage("sic_fetch", True, lambda c: [c.candidate_path], lambda c: [c.classification_packet_path], st.run_sic_fetch),
        Stage("theme_producer", False, lambda c: [c.candidate_path, c.series_packet_path, c.classification_packet_path], lambda c: [c.theme_projection_path], st.run_theme_producer),
        Stage("projection_inputs", False, lambda c: [c.momentum_projection_path, c.theme_projection_path], lambda c: [c.merged_momentum_path, c.merged_theme_path], st.run_projection_inputs),
        Stage("pass2_preflight", False, lambda c: [c.merged_momentum_path, c.merged_theme_path], lambda c: [c.preflight_summary_path], st.run_pass2_preflight),
        Stage("pass2_fetch", True, lambda c: [c.preflight_summary_path], lambda c: [c.source_packet_path, c.context_components_path], st.run_pass2_fetch),
        Stage("weekly_bridge", False, lambda c: [c.source_packet_path], lambda c: [c.private_root / "weekly_private" / c.decision_date / "weekly_report.md"], st.run_weekly_bridge),
    ]


def _plan(ctx: CapstoneContext, stages: list[Stage]) -> dict[str, Any]:
    """The dry-run plan: canonical dates + every stage's gated flag + I/O paths. No execution, no fetch."""
    return {
        "mode": "dry_run",
        "decision_date": ctx.decision_date,
        "price_basis_date": ctx.price_basis_date,
        "run_date": ctx.now_et.strftime("%Y%m%d"),
        "gated_stages_need_authorization": [s.name for s in stages if s.gated],
        "authorized": ctx.confirm_user_authorization,
        "stages": [
            {
                "name": s.name,
                "kind": "gated_live_fetch" if s.gated else "offline",
                "inputs": [_rel(p) for p in s.inputs(ctx)],
                "outputs": [_rel(p) for p in s.outputs(ctx)],
            }
            for s in stages
        ],
    }


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(p)


def run_weekly_capstone(
    *,
    now_et: datetime,
    private_root: Path,
    batch4_template_path: Path,
    account_state_path: Path,
    calendar_path: Path = CALENDAR_PRESET,
    confirm_user_authorization: bool = False,
    dry_run: bool = True,
    provider_pace_seconds: float = 0.0,
    max_retries_per_call: int = 0,
    retry_backoff_seconds: float = 0.0,
    stages: list[Stage] | None = None,
    state_dir: Path = STATE_DIR,
    sample_root: Path = ROOT,
) -> dict[str, Any]:
    """Orchestrate the weekly one-click path. `dry_run=True` (default) resolves the canonical dates and returns the
    full plan WITHOUT any fetch. A live run (`dry_run=False`) requires `confirm_user_authorization` (else it refuses
    before touching a provider), then runs each stage in order, validating each stage's declared outputs exist and
    aborting fast (with the stage name) on the first failure. `stages` is injectable for offline testing."""
    ctx = resolve_capstone_context(
        now_et=now_et, private_root=private_root, batch4_template_path=batch4_template_path,
        account_state_path=account_state_path, calendar_path=calendar_path,
        confirm_user_authorization=confirm_user_authorization, provider_pace_seconds=provider_pace_seconds,
        max_retries_per_call=max_retries_per_call, retry_backoff_seconds=retry_backoff_seconds, state_dir=state_dir,
        sample_root=sample_root,
    )
    pipeline = stages if stages is not None else default_pipeline()

    if dry_run:
        return _plan(ctx, pipeline)

    if not ctx.confirm_user_authorization:
        raise WeeklyCapstoneError(
            "a live weekly run performs gated provider fetches (universe / momentum / SIC / Pass2) and requires "
            "explicit per-execution authorization (confirm_user_authorization=True); re-run with --dry-run to review "
            "the plan first")

    results: list[dict[str, Any]] = []
    for stage in pipeline:
        try:
            result = stage.run(ctx)
        except Exception as exc:  # noqa: BLE001 — re-wrap with the stage label so a failure is never anonymous
            raise WeeklyCapstoneError(f"stage '{stage.name}' failed: {type(exc).__name__}: {exc}") from exc
        # The terminal bridge legitimately writes NO weekly_report.md on an HONEST no-emit (intraday out-of-window
        # or a non-clean provider_health, design §3.2 — e.g. the free-tier FMP-429 case): that is a correct outcome,
        # not a missing-output failure. Detect it from the bridge's own emit flag and return the honest no-emit.
        if stage.name == "weekly_bridge" and _bridge_emitted(result) is False:
            results.append({"name": stage.name, "gated": stage.gated, "result": result})
            return {
                "mode": "live",
                "decision_date": ctx.decision_date,
                "price_basis_date": ctx.price_basis_date,
                "emitted": False,
                "no_emit_reason": _bridge_no_emit_reason(result),
                "stages": results,
            }
        missing = [p for p in stage.outputs(ctx) if not Path(p).exists()]
        if missing:
            raise WeeklyCapstoneError(
                f"stage '{stage.name}' completed but did not produce: {[_rel(p) for p in missing]}")
        results.append({"name": stage.name, "gated": stage.gated, "result": result})

    return {
        "mode": "live",
        "decision_date": ctx.decision_date,
        "price_basis_date": ctx.price_basis_date,
        "emitted": True,
        "emitted_report": _rel(ctx.private_root / "weekly_private" / ctx.decision_date / "weekly_report.md"),
        "stages": results,
    }


def _bridge_emitted(result: Any) -> bool | None:
    """The weekend pipeline's honest emit flag surfaced by the bridge result (`batch4_run.emitted`), or None when the
    shape is unexpected (then the normal output-existence check applies). A `False` = a legitimate provider_health /
    out-of-window no-emit that wrote no weekly_report.md — NOT a stage failure."""
    if isinstance(result, dict):
        batch4 = result.get("batch4_run")
        if isinstance(batch4, dict) and isinstance(batch4.get("emitted"), bool):
            return batch4["emitted"]
    return None


def _bridge_no_emit_reason(result: Any) -> str | None:
    if isinstance(result, dict):
        batch4 = result.get("batch4_run")
        if isinstance(batch4, dict) and isinstance(batch4.get("no_emit_reason"), str):
            return batch4["no_emit_reason"]
    return None


def _parse_now_et(raw: str) -> datetime:
    dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S")
    return dt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="US-short weekly one-click capstone orchestrator (skeleton)")
    parser.add_argument("--now-et", required=True, type=_parse_now_et,
                        help="naive ET wall-clock decision instant, e.g. 2026-07-09T08:00:00 (Beijing→ET upstream)")
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--batch4-template-path", required=True, type=Path)
    parser.add_argument("--account-state-path", required=True, type=Path)
    parser.add_argument("--calendar-path", type=Path, default=CALENDAR_PRESET)
    parser.add_argument("--confirm-user-authorization", action="store_true")
    parser.add_argument("--live", action="store_true", help="execute (default is a dry-run plan only)")
    parser.add_argument("--provider-pace-seconds", type=float, default=1.0)
    parser.add_argument("--max-retries-per-call", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    try:
        summary = run_weekly_capstone(
            now_et=args.now_et, private_root=args.private_root,
            batch4_template_path=args.batch4_template_path, account_state_path=args.account_state_path,
            calendar_path=args.calendar_path, confirm_user_authorization=args.confirm_user_authorization,
            dry_run=not args.live, provider_pace_seconds=args.provider_pace_seconds,
            max_retries_per_call=args.max_retries_per_call, retry_backoff_seconds=args.retry_backoff_seconds,
        )
    except WeeklyCapstoneError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    import json
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
