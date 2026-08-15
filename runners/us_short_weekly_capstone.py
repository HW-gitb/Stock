# -*- coding: utf-8 -*-
"""US-short weekly one-click capstone orchestrator (cut ⑥ closure) — SKELETON / draft.

Design authority: docs/us_short_system_design.md §2.1 (canonical decision_date / 盘中死区 fail-closed /
价格基准 / 幂等) + §18.3 (v1 engineering closure: "a weekly one-click path can use authorized real data
inputs to produce an honest weekly report and action table"). This module ONLY orchestrates the already-built
per-stage runners into ONE ordered path; it restates no selection/PIT semantics (single authority = the stages).

WHAT THIS IS. The v1 stages already exist as separate runners (universe fetch → momentum fetch/producer →
SEC-SIC fetch/theme producer → projection-inputs → Pass2 preflight → Pass2 live source packet → batch5→batch4
bridge). Today a weekly run means invoking ~7 commands by hand. This capstone chains them behind one entry with:
  * CANONICAL anchoring (§2.1): resolve decision_date + price_basis_date ONCE from the frozen NYSE calendar and
    thread the SAME dates through every stage; an intraday `now_et` fails closed (OutOfWindowError → no run).
  * A working offline DRY-RUN: print the full plan (every stage, gated-vs-offline, the exact input/output artifact
    paths, and which stages will hit a provider) WITHOUT any fetch — so the operator sees the gated boundary first.
  * GATED-stage execution: provider stages (universe / momentum-fetch / SIC-fetch / yfinance / Pass2 / VIX)
    run live only after the user explicitly selects `--live`; the one-click wrapper derives the Pass2 budget in that
    same run while the exact approval remains bound through every downstream stage;
    they run SEQUENTIALLY (§18.3 Batch II "do not parallelize provider/live execution"). This is the RUN-TIME
    closure of the one-click goal, distinct from the BUILD-TIME per-cut review discipline.
  * FAIL-FAST with a stage label + no silent partial success; a gated stage that returns DEGRADED coverage
    (e.g. FMP 429) does NOT abort — the run proceeds to the bridge, whose provider_health gate decides emit/no-emit
    (exactly the honest 2026-07-08 behaviour).
  * HONEST provider_health DERIVED from the five stage outcomes into the closed-world eight functional families —
    the health gate cannot be hand-waved past or widened by an unrelated vendor status.

SKELETON status: the orchestration framework (canonical anchor, stage sequencing, dry-run plan, auth gating,
fail-fast, provider-health derivation, path threading) is implemented and offline-tested (dry-run + a full injected-
fake chain). The per-stage `run` adapters call the real runners with dates/paths from the context; that live wiring
gets its first real exercise on the next fresh-quota run (the gated stages cannot be network-tested offline). No
provider call, production, DataHub, ship-gate, broker path, or A-share crossing is authorized here.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import shutil
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.modules.setdefault("runners.us_short_weekly_capstone", sys.modules[__name__])

from engine.us_short_canonical_asof import OutOfWindowError, resolve_canonical_asof  # noqa: E402
from engine import us_short_capstone_checkpoint as checkpoint_store  # noqa: E402
from engine.us_short_live_provider_preflight import (  # noqa: E402
    inspect_live_provider_clock,
    validate_provider_pace_seconds,
)
from engine.us_short_market_calendar import load_market_calendar, sessions_for_window  # noqa: E402
from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path  # noqa: E402
from engine.us_short_regime import (
    MARKET_REGIME_STATE_FILENAME,
    MarketRegimeStateError,
    load_market_regime_state,
)  # noqa: E402
from engine.us_short_run_origin import _issue_capstone_research_live_receipt  # noqa: E402
from engine.us_short_weekend_private_write import (
    WeekendPrivateWriteError,
    resolve_prior_run_dir,
)  # noqa: E402
from runners import us_short_batch5_data_context_source_packet as source_packet_runner  # noqa: E402
from runners.us_short_batch5_full_candidate_pass2_preflight import (  # noqa: E402
    FullCandidatePass2PreflightError,
    canonicalize_catalyst_recall_tickers,
)
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402

CALENDAR_PRESET = ROOT / "presets" / "us_short_market_calendar_2026_2027.json"
STATE_DIR = ROOT / "state" / "us_short"
# The preflight summary is BOTH stage-7's OUTPUT and stage-8's preflight INPUT, so it must live where BOTH runners'
# fail-closed allowlists accept it. This mirrors
# runners.us_short_batch5_full_candidate_pass2_preflight.PROVIDER_SAMPLE_REL_ROOT (a conformance test pins equality)
# — a per-run gitignored sidecar under the reviewed provider_samples/ tree, decision-date-keyed in the filename.
_PREFLIGHT_SAMPLE_REL_ROOT = Path("provider_samples") / "us_short_batch5_full_candidate_pass2_preflight_20260706"
MASSIVE_RATE_LIMIT_WINDOW_CAPACITY = universe_fetch.MASSIVE_RATE_LIMIT_WINDOW_CAPACITY


def _normalize_capstone_retry_policy(
    max_retries_per_call: int | None,
    retry_backoff_seconds: float | None,
    *,
    auto_authorize_pass2_budget: bool,
) -> tuple[int, float]:
    """Normalize one-click defaults while keeping the reviewed Massive policy closed-world."""
    retries = (
        universe_fetch.MASSIVE_RATE_LIMIT_MAX_RETRIES
        if max_retries_per_call is None and auto_authorize_pass2_budget
        else 0
        if max_retries_per_call is None
        else max_retries_per_call
    )
    if type(retries) is not int or not 0 <= retries <= universe_fetch.MASSIVE_RATE_LIMIT_MAX_RETRIES:
        raise WeeklyCapstoneError(
            "max_retries_per_call must be an int in [0, 2]"
        )
    if retry_backoff_seconds is None:
        backoff = 0.0 if retries == 0 else universe_fetch.MASSIVE_RATE_LIMIT_RETRY_SECONDS
    elif (
        isinstance(retry_backoff_seconds, (int, float))
        and not isinstance(retry_backoff_seconds, bool)
        and math.isfinite(retry_backoff_seconds)
        and retry_backoff_seconds == (
            0.0 if retries == 0 else universe_fetch.MASSIVE_RATE_LIMIT_RETRY_SECONDS
        )
    ):
        backoff = float(retry_backoff_seconds)
    else:
        raise WeeklyCapstoneError(
            "retry_backoff_seconds must be omitted/0 when retries are disabled or exactly 65.0 when retries are enabled"
        )
    return retries, float(backoff)


def _automatic_pass2_http_attempt_cap(*, exact_pass2_calls: int, target_count: int, max_retries: int) -> int:
    massive_logical_calls = target_count * 3
    retry_headroom = max_retries * (
        (massive_logical_calls + MASSIVE_RATE_LIMIT_WINDOW_CAPACITY - 1)
        // MASSIVE_RATE_LIMIT_WINDOW_CAPACITY
    )
    return exact_pass2_calls + retry_headroom


class WeeklyCapstoneError(RuntimeError):
    """Any capstone-orchestration failure (canonical resolution, a missing prerequisite, a stage abort)."""


@dataclass(frozen=True)
class Pass2BudgetApproval:
    """The one immutable Pass2 approval shared by every downstream stage in a run.

    The approval binds only safe run facts.  It never carries candidate symbols,
    provider credentials, URLs, or raw provider payloads; the preflight summary
    remains the derived audit artifact and this object is the execution binding.
    """

    decision_date: str
    candidate_price_basis_date: str
    candidate_artifact_sha256: str
    momentum_top_k: int
    target_count: int
    exact_pass2_calls: int
    authorization_mode: str
    authorization_ref: str
    generated_at: str

    def __post_init__(self) -> None:
        for field_name in ("decision_date", "candidate_price_basis_date"):
            value = getattr(self, field_name)
            if type(value) is not str or not re.fullmatch(r"[0-9]{8}", value):
                raise ValueError(f"{field_name} must be ASCII YYYYMMDD")
            try:
                datetime.strptime(value, "%Y%m%d")
            except ValueError as exc:
                raise ValueError(f"{field_name} must be a real calendar date") from exc
        if type(self.candidate_artifact_sha256) is not str or not re.fullmatch(
            r"[0-9a-f]{64}", self.candidate_artifact_sha256
        ):
            raise ValueError("candidate_artifact_sha256 must be a lowercase SHA-256 fingerprint")
        for field_name in ("momentum_top_k", "target_count", "exact_pass2_calls"):
            value = getattr(self, field_name)
            if type(value) is not int or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field_name} must be a positive exact int")
        if not (1 <= self.momentum_top_k <= 250):
            raise ValueError("momentum_top_k must be in [1, 250]")
        if self.authorization_mode not in {"manual", "one_click_test"}:
            raise ValueError("authorization_mode must be manual or one_click_test")
        if type(self.authorization_ref) is not str or not self.authorization_ref.strip():
            raise ValueError("authorization_ref must be a non-empty safe reference")
        lower_ref = self.authorization_ref.lower()
        if any(fragment in lower_ref for fragment in ("http://", "https://", "api_key", "token=", "raw_payload")):
            raise ValueError("authorization_ref must not contain secrets, URLs, or raw payload references")
        if type(self.generated_at) is not str:
            raise ValueError("generated_at must be a timezone-aware RFC3339 instant")
        try:
            generated = datetime.fromisoformat(self.generated_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("generated_at must be a timezone-aware RFC3339 instant") from exc
        if generated.tzinfo is None:
            raise ValueError("generated_at must be a timezone-aware RFC3339 instant")

    def _fingerprint_payload(self) -> dict[str, Any]:
        return {
            "decision_date": self.decision_date,
            "candidate_price_basis_date": self.candidate_price_basis_date,
            "candidate_artifact_sha256": self.candidate_artifact_sha256,
            "momentum_top_k": self.momentum_top_k,
            "target_count": self.target_count,
            "exact_pass2_calls": self.exact_pass2_calls,
            "authorization_mode": self.authorization_mode,
            "authorization_ref": self.authorization_ref,
            "generated_at": self.generated_at,
        }

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            self._fingerprint_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def binding_summary(self) -> dict[str, Any]:
        return {**self._fingerprint_payload(), "fingerprint": self.fingerprint}

    @classmethod
    def validate_binding_summary(cls, binding: Any) -> dict[str, Any]:
        """Validate both the closed binding shape and its content-derived fingerprint."""
        fields = (
            "decision_date",
            "candidate_price_basis_date",
            "candidate_artifact_sha256",
            "momentum_top_k",
            "target_count",
            "exact_pass2_calls",
            "authorization_mode",
            "authorization_ref",
            "generated_at",
        )
        if type(binding) is not dict or set(binding) != set(fields) | {"fingerprint"}:
            raise ValueError("Pass2 budget approval binding has an unexpected shape")
        if type(binding["fingerprint"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", binding["fingerprint"]):
            raise ValueError("Pass2 budget approval fingerprint is invalid")
        try:
            approval = cls(**{field: binding[field] for field in fields})
        except (TypeError, ValueError) as exc:
            raise ValueError("Pass2 budget approval binding is invalid") from exc
        if approval.fingerprint != binding["fingerprint"]:
            raise ValueError("Pass2 budget approval fingerprint does not match its binding fields")
        return dict(binding)


def _emit_diagnostic_event(
    diagnostic_event: Callable[[dict[str, Any]], None] | None,
    event: str,
    **details: Any,
) -> None:
    """Observability is best-effort and must never change a capstone decision."""
    if diagnostic_event is None:
        return
    try:
        diagnostic_event({"event": event, **details})
    except Exception:
        return


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
    authorized_momentum_top_k: int = 200
    authorized_pass2_call_budget: int | None = None
    pass2_budget_preview: bool = False
    budget_approval: Pass2BudgetApproval | None = None
    catalyst_recall_tickers: tuple[str, ...] = ()
    frozen_holding_tickers: tuple[str, ...] | None = None
    account_lineage_status: dict[str, str] | None = None
    confirm_user_authorization: bool = False
    provider_pace_seconds: float = 0.0
    live_provider_preflight: dict[str, Any] | None = None
    max_retries_per_call: int = 0
    retry_backoff_seconds: float = 0.0
    max_total_http_attempts: int | None = None
    model_paper_store_root: Path | None = None
    model_paper_run_account_mode: str | None = None
    model_paper_track: dict[str, Any] | None = None
    prior_run_dir: Path | None = None
    prior_regime: str | None = None
    prior_upgrade_count: int = 0
    market_diagnostic_root: Path | None = None
    soft_discovery_enabled: bool = True
    theme_soft_boost_enabled: bool = True
    soft_discovery_run_result: dict[str, Any] | None = None
    soft_boost_run_result: dict[str, Any] | None = None
    serenity_annotation_payload: dict[str, Any] | None = None
    serenity_settlement_result: dict[str, Any] | None = None
    serenity_quality_run_result: dict[str, Any] | None = None
    serenity_shadow_result: dict[str, Any] | None = None
    state_dir: Path = STATE_DIR
    sample_root: Path = ROOT   # repo root that the runners' provider_samples/ allowlists resolve against (tests inject a tempdir)
    research_live_capability: Any = None   # A1: minted by run_weekly_capstone ONLY for a genuine production run — never by resolve_capstone_context / a caller
    corporate_action_live_capability: Any = None  # minted only for the real zero-event provider stage
    official_output_root: Path | None = None  # C3: run-scoped staging root; lifecycle remains under private_root
    decision_lock: Any = None  # capability from this run's existing decision-date transaction only

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
    def ohlcv_series_packet_path(self) -> Path:
        return self._s(f"us_short_batch5_full_universe_ohlcv_series_{self.price_basis_date}_packet.json")

    @property
    def momentum_projection_path(self) -> Path:
        return self._s(f"us_short_batch5_full_universe_momentum_{self.price_basis_date}_momentum.json")

    @property
    def overextension_projection_path(self) -> Path:
        return self._s(f"us_short_batch5_full_universe_overextension_{self.price_basis_date}_overextension.json")

    @property
    def classification_packet_path(self) -> Path:
        return self._s(f"us_short_batch5_full_universe_sector_classification_{self.price_basis_date}_packet.json")

    @property
    def soft_discovery_merge_path(self) -> Path:
        from runners import us_short_llm_theme_discovery_merge as merge
        from runners.us_short_weekly_capstone_soft_discovery import rerooted_default_path
        return rerooted_default_path(merge.default_discovery_path, self.decision_date, state_dir=self.state_dir)

    @property
    def soft_discovery_merge_manifest_path(self) -> Path:
        from runners import us_short_llm_theme_discovery_merge as merge
        from runners.us_short_weekly_capstone_soft_discovery import rerooted_default_path
        return rerooted_default_path(merge.default_manifest_path, self.decision_date, state_dir=self.state_dir)

    @property
    def soft_discovery_ingest_path(self) -> Path:
        from runners import us_short_llm_theme_discovery as ingest
        from runners.us_short_weekly_capstone_soft_discovery import rerooted_default_path
        return rerooted_default_path(ingest.default_output_path, self.decision_date, state_dir=self.state_dir)

    @property
    def soft_discovery_validation_path(self) -> Path:
        from runners import us_short_provisional_theme_validate as validate
        from runners.us_short_weekly_capstone_soft_discovery import rerooted_default_path
        return rerooted_default_path(validate.default_output_path, self.decision_date, state_dir=self.state_dir)

    @property
    def soft_discovery_receipt_path(self) -> Path:
        from runners.us_short_weekly_capstone_soft_discovery import default_receipt_path
        return default_receipt_path(self.decision_date, state_dir=self.state_dir)

    @property
    def serenity_annotation_path(self) -> Path:
        return self._s(f"us_short_serenity_structural_theme_annotation_{self.decision_date}.json")

    @property
    def serenity_quality_review_path(self) -> Path:
        return self._s(f"us_short_serenity_quality_review_{self.decision_date}.json")

    @property
    def serenity_quality_observation_path(self) -> Path:
        return self._s(f"us_short_serenity_quality_observation_{self.decision_date}.json")

    @property
    def serenity_quality_ledger_path(self) -> Path:
        return self._s("us_short_serenity_quality_forward_ledger.json")

    @property
    def serenity_quality_gate_path(self) -> Path:
        return self._s(f"us_short_serenity_quality_gate_{self.decision_date}.json")

    @property
    def serenity_g1_decision_path(self) -> Path:
        return self._s("us_short_serenity_g1_decision.json")

    @property
    def serenity_g1_blade6_preflight_path(self) -> Path:
        return self._s(f"us_short_serenity_g1_blade6_preflight_{self.decision_date}.json")

    @property
    def soft_boost_consumption_receipt_path(self) -> Path:
        return self._s(f"us_short_soft_boost_consumption_receipt_{self.decision_date}.json")

    @property
    def soft_boost_shadow_receipt_path(self) -> Path:
        return self._s("shadow_compare_private") / (
            f"us_short_soft_boost_shadow_receipt_{self.decision_date}.json"
        )

    @property
    def soft_boost_comparison_ledger_path(self) -> Path:
        return self._s("shadow_compare_private") / (
            f"us_short_soft_boost_comparison_ledger_{self.decision_date}.json"
        )

    @property
    def soft_boost_pairwise_ledger_path(self) -> Path:
        return self._s("shadow_compare_private") / "us_short_soft_boost_pairwise_ledger.json"

    @property
    def soft_boost_maturity_observation_root(self) -> Path:
        return self._s("shadow_compare_private") / "soft_boost_maturity_observations"

    @property
    def soft_boost_adjudication_receipt_path(self) -> Path:
        return self._s("shadow_compare_private") / (
            f"us_short_soft_boost_adjudication_receipt_{self.decision_date}.json"
        )

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
    def yfinance_grade_source_package_path(self) -> Path:
        return self._s(f"us_short_batch5_capstone_{self.decision_date}_yfinance_grade_source_package.json")

    @property
    def yfinance_grade_actions_path(self) -> Path:
        return self._s(f"us_short_batch5_capstone_{self.decision_date}_yfinance_grade_actions.json")

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
    def context_packet_path(self) -> Path:
        return self.private_root / "batch5_to_batch4_context_packet.json"

    @property
    def data_context_path(self) -> Path:
        return self._s(f"us_short_batch5_capstone_{self.decision_date}_data_context.json")

    @property
    def provider_health_path(self) -> Path:
        return self._s(f"us_short_batch5_capstone_{self.decision_date}_provider_health.json")

    @property
    def forward_shadow_selection_private_path(self) -> Path:
        return self._s("shadow_compare_private") / f"forward_policy_selection_{self.decision_date}.json"

    @property
    def forward_policy_source_capture_private_path(self) -> Path:
        return self._s("shadow_compare_private") / f"forward_policy_source_capture_{self.decision_date}.json"

    @property
    def forward_policy_summary_path(self) -> Path:
        # Count-only and intentionally outside the private state tree: this is the §11.6 trackable companion to the
        # ticker-bearing shadow record.  Tests inject sample_root, while production uses the repository root.
        return self.sample_root / "research" / "results" / "us_short_forward_policy_shadow" / \
            f"forward_policy_summary_{self.decision_date}.json"

    @property
    def forward_policy_corporate_action_summary_path(self) -> Path:
        from runners.us_short_forward_policy_corporate_action_fetch import SUMMARY_REL_ROOT
        return self.sample_root / SUMMARY_REL_ROOT / f"coverage_summary_{self.decision_date}.json"

    @property
    def forward_policy_comparison_ledger_path(self) -> Path:
        return self._s("shadow_compare_private") / "forward_policy_comparison_ledger.json"

    @property
    def vix_regime_summary_path(self) -> Path:
        from runners.us_short_vix_regime_fetch import SUMMARY_SAMPLE_REL_ROOT
        return self.sample_root / SUMMARY_SAMPLE_REL_ROOT / \
            f"us_short_batch5_capstone_{self.decision_date}_vix_regime_summary.json"


def _model_paper_enabled(ctx: CapstoneContext) -> bool:
    return ctx.model_paper_store_root is not None


def _dormant_model_paper_summary(ctx: CapstoneContext) -> dict[str, Any]:
    print(
        "[US-SHORT PAPER] DORMANT: 尚未收到并完成 US-short 设计完成激活；"
        "未执行 provider、账户播种或 model-paper 写入。",
        file=sys.stderr,
    )
    return {
        "mode": "dormant",
        "execution_mode": "dormant",
        "report_mode": "offline_test",
        "operational_use": "not_authorized",
        "decision_date": ctx.decision_date,
        "price_basis_date": ctx.price_basis_date,
        "activation_status": "dormant",
        "model_paper_started": False,
        "provider_calls_performed": False,
        "account_write": False,
        "model_paper_store_write": False,
        "stages": [],
        "stage_outcomes": [],
        "stage_outcome_counts": {
            "completed_work": 0,
            "no_work_expected": 0,
            "waiting_dependency": 0,
            "failed_nonblocking": 0,
        },
    }


def _update_model_paper_context(ctx: CapstoneContext, result: dict[str, Any]) -> CapstoneContext:
    if not _model_paper_enabled(ctx):
        return ctx
    holdings = result.get("frozen_holding_tickers")
    if not isinstance(holdings, list) or any(not isinstance(ticker, str) for ticker in holdings):
        raise WeeklyCapstoneError("model-paper adapter did not return canonical holding tickers")
    adapter = result.get("adapter")
    track = adapter.get("paper_track") if isinstance(adapter, dict) else None
    if not isinstance(track, dict):
        raise WeeklyCapstoneError(
            "model-paper adapter did not return a source-bound paper_track object"
        )
    return replace(
        ctx,
        frozen_holding_tickers=tuple(holdings),
        model_paper_track=copy.deepcopy(track),
    )


# The lines the two advance stages contribute. Fixed strings by construction: a
# stage's `problem` carries absolute paths, and the cash capture's errors can echo
# a URL that contains an API key, so what goes into the report is a sentence and
# the detail stays in the run summary and the checkpoint.
_DIAGNOSTIC_FETCH_FAILED_LINE = (
    "26 周诊断轨：本周基准价格或现金数据抓取失败，诊断周未推进；原因见本次运行摘要。"
    "不影响选股与操作建议。"
)
# Only the settle stage speaks for "the week did not advance". Both stages derive
# the next week from the same two stores in the same run, so a waiting fetch is
# always a waiting settle, and saying it twice would only teach a reader to skim.
# `broken` is likewise left to the reader stage below, which is last, always runs,
# and already reports it with the reason.
_DIAGNOSTIC_SETTLE_LINES = {
    "waiting_for_paper_week": (
        "26 周诊断轨：model-paper 账户本周还没有结算出新的一周，诊断周未推进。"
        "不影响选股与操作建议。"
    ),
    "waiting_for_inputs": (
        "26 周诊断轨：本周的基准与现金输入没有捕获到，诊断周未推进。"
        "不影响选股与操作建议。"
    ),
    # Deliberately NOT worded like the line above. That one is a week still in
    # progress; this one is a clock that has stopped and will stay stopped until
    # the inputs for a week that is already over can be captured. The two used to
    # read the same, so a reader could not tell a dead clock from a healthy one.
    "stalled_on_a_finished_week": (
        "26 周诊断轨：诊断周已停在一个**已经过去**的周上——它的基准输入至今抓不到，"
        "在补到之前钟不会前进。不影响选股与操作建议。"
    ),
    "failed": (
        "26 周诊断轨：本周结算失败，诊断周未推进；原因见本次运行摘要。"
        "不影响选股与操作建议。"
    ),
}
# The one line that reports a calendar week having been spent without a strategy
# result. Only week numbers are interpolated; everything else is fixed.
_DIAGNOSTIC_NO_COUNT_LINE = (
    "26 周诊断轨：第 {weeks} 周整周没有跑过一键、账户也没有结算，已按设计记为 no_count，"
    "仍占用该日历周、不顺延 26 周边界。不影响选股与操作建议。"
)


# Stages that touch THIS run's still-unpublished official artifacts, and so must be
# handed the staging root instead of the published one. A live run keeps
# `weekly_private/<decision_date>/` empty until the terminal publish moves staging
# into it, so a stage left off this list would look for the weekly report where
# there is not one yet — wired and inert, which is the exact failure this track
# keeps finding in itself. Membership is asserted against the pipeline in
# `tests/test_us_short_market_diagnostic_weekly_producer.py`, so a fourth
# diagnostic stage joins by existing rather than by being remembered.
_OFFICIAL_ARTIFACT_STAGES = frozenset({
    "weekly_bridge",
    "model_paper_weekly",
    "market_diagnostic_fetch",
    "market_diagnostic_settle",
    "market_diagnostic",
})


_STAGE_OUTCOME_CLASSES = (
    "completed_work",
    "no_work_expected",
    "waiting_dependency",
    "failed_nonblocking",
)
_STAGE_OUTCOME_EVENT_NAMES = {
    "completed_work": "stage_completed",
    "no_work_expected": "stage_no_work",
    "waiting_dependency": "stage_waiting",
    "failed_nonblocking": "stage_failed",
}
_REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,95}$")


def _outcome_reason(value: Any, fallback: str) -> str:
    """Accept only the existing privacy-safe reason-code vocabulary."""
    return value if isinstance(value, str) and _REASON_CODE_RE.fullmatch(value) else fallback


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _normalize_stage_outcome(
    stage_name: str,
    result: Any,
    *,
    failure_kind: str | None = None,
) -> dict[str, str]:
    """Map one typed stage result to the four-state capstone outcome contract.

    This is deliberately the only stage-outcome mapping.  It consumes producer
    status/summary fields; it never infers a waiting or no-work state from a
    missing result, missing output, or exception.
    """

    if failure_kind is not None:
        return {
            "outcome_class": "failed_nonblocking",
            "reason_code": {
                "input_gate": "STAGE_INPUT_UNREADABLE",
                "stage_run": "STAGE_EXECUTION_EXCEPTION",
                "fresh_output_missing": "FRESH_OUTPUT_MISSING",
                "output_enumeration": "STAGE_OUTPUT_ENUMERATION_FAILED",
            }.get(failure_kind, "STAGE_FAILURE"),
        }
    if not isinstance(result, dict):
        return {"outcome_class": "failed_nonblocking", "reason_code": "OUTCOME_CONTRACT_UNRECOGNIZED"}

    if stage_name == "soft_discovery":
        status = result.get("status")
        if isinstance(status, str) and status in {"valid_nonempty", "valid_empty"}:
            return {"outcome_class": "completed_work", "reason_code": f"SOFT_DISCOVERY_{status.upper()}"}
        if status == "disabled":
            return {"outcome_class": "no_work_expected", "reason_code": "SOFT_DISCOVERY_DISABLED"}
        if status == "upstream_unavailable":
            return {"outcome_class": "waiting_dependency", "reason_code": _outcome_reason(result.get("reason_code"), "UPSTREAM_UNAVAILABLE")}
        if status == "invalid_evidence":
            return {"outcome_class": "failed_nonblocking", "reason_code": _outcome_reason(result.get("reason_code"), "INVALID_EVIDENCE")}
        return {"outcome_class": "failed_nonblocking", "reason_code": "OUTCOME_CONTRACT_UNRECOGNIZED"}

    if stage_name == "serenity_quality_forward":
        status = result.get("status")
        if status == "eligible":
            return {"outcome_class": "completed_work", "reason_code": "SERENITY_QUALITY_ELIGIBLE"}
        if status == "sleeping":
            return {"outcome_class": "no_work_expected", "reason_code": "SERENITY_QUALITY_SLEEPING"}
        if status == "not_evaluable":
            observation = result.get("observation")
            settlement_status = observation.get("settlement_status") if isinstance(observation, dict) else None
            producer = result.get("annotation_producer")
            if settlement_status == "pending_review" or (
                isinstance(producer, dict) and producer.get("status") == "pending"
            ):
                return {"outcome_class": "waiting_dependency", "reason_code": "SERENITY_REVIEW_PENDING"}
            return {"outcome_class": "no_work_expected", "reason_code": "SERENITY_NO_COUNT"}
        if status == "invalid_evidence":
            error = result.get("error")
            reason = error.get("code") if isinstance(error, dict) else None
            return {"outcome_class": "failed_nonblocking", "reason_code": _outcome_reason(reason, "SERENITY_INVALID_EVIDENCE")}
        return {"outcome_class": "failed_nonblocking", "reason_code": "OUTCOME_CONTRACT_UNRECOGNIZED"}

    if stage_name == "forward_policy_shadow":
        return {"outcome_class": "completed_work", "reason_code": "FORWARD_POLICY_SHADOW_CAPTURED"}

    if stage_name == "forward_policy_corporate_actions":
        status = result.get("status")
        if status == "complete":
            return {"outcome_class": "completed_work", "reason_code": "CORPORATE_ACTIONS_CAPTURED"}
        if status == "no_eligible_mature_capture":
            return {"outcome_class": "no_work_expected", "reason_code": "NO_ELIGIBLE_MATURE_CAPTURE"}
        if isinstance(status, str) and status in {"incomplete_no_count", "incomplete"}:
            return {"outcome_class": "failed_nonblocking", "reason_code": _outcome_reason(result.get("failure_reason"), "CORPORATE_ACTIONS_INCOMPLETE_NO_COUNT")}
        return {"outcome_class": "failed_nonblocking", "reason_code": "OUTCOME_CONTRACT_UNRECOGNIZED"}

    if stage_name == "forward_policy_maturity":
        fields = (
            "ready_weeks_appended_or_confirmed",
            "whole_week_no_count",
            "already_ready_weeks_untouched",
            "awaiting_adjustment_evidence_untouched",
        )
        if any(not _nonnegative_int(result.get(field)) for field in fields):
            return {"outcome_class": "failed_nonblocking", "reason_code": "OUTCOME_CONTRACT_UNRECOGNIZED"}
        if result["ready_weeks_appended_or_confirmed"] > 0:
            return {"outcome_class": "completed_work", "reason_code": "FORWARD_POLICY_MATURITY_ADVANCED"}
        if result["awaiting_adjustment_evidence_untouched"] > 0:
            reason = "H20_WINDOW_OR_ADJUSTMENT_UNAVAILABLE"
        elif result["whole_week_no_count"] > 0:
            reason = "FORWARD_POLICY_MATURITY_NO_COUNT"
        else:
            reason = "FORWARD_POLICY_MATURITY_NOT_DUE"
        return {"outcome_class": "no_work_expected", "reason_code": reason}

    if stage_name == "soft_boost_comparison_maturity":
        if not _nonnegative_int(result.get("matured_observations_written")) or not _nonnegative_int(result.get("whole_week_no_count")):
            return {"outcome_class": "failed_nonblocking", "reason_code": "OUTCOME_CONTRACT_UNRECOGNIZED"}
        if result["matured_observations_written"] > 0:
            return {"outcome_class": "completed_work", "reason_code": "SOFT_BOOST_MATURITY_ADVANCED"}
        return {"outcome_class": "no_work_expected", "reason_code": "SOFT_BOOST_MATURITY_NO_COUNT" if result["whole_week_no_count"] else "SOFT_BOOST_MATURITY_NOT_DUE"}

    if stage_name == "soft_boost_comparison_capture":
        performed = result.get("comparison_capture_performed")
        status = result.get("status")
        reason_code = result.get("reason_code")
        if type(performed) is not bool:
            return {"outcome_class": "failed_nonblocking", "reason_code": "OUTCOME_CONTRACT_UNRECOGNIZED"}
        if performed:
            return {"outcome_class": "completed_work", "reason_code": "SOFT_BOOST_COMPARISON_CAPTURED"}
        if reason_code == "SOFT_BOOST_COMPARISON_ARTIFACT_INVALID" or status == "failed":
            return {"outcome_class": "failed_nonblocking", "reason_code": _outcome_reason(reason_code, "SOFT_BOOST_COMPARISON_FAILED")}
        if (
            isinstance(status, str)
            and status in {"not_applicable", "disabled", "no_op"}
            and (reason_code is None or isinstance(reason_code, str))
            and reason_code in {
                None, "SOFT_BOOST_COMPARISON_NOT_REQUESTED", "SOFT_BOOST_COMPARISON_NOT_APPLICABLE",
            }
        ):
            return {"outcome_class": "no_work_expected", "reason_code": _outcome_reason(reason_code, "SOFT_BOOST_COMPARISON_NOT_REQUESTED")}
        return {"outcome_class": "failed_nonblocking", "reason_code": "OUTCOME_CONTRACT_UNRECOGNIZED"}

    if stage_name == "market_diagnostic_fetch":
        status = result.get("fetch_status")
        if status == "captured":
            return {"outcome_class": "completed_work", "reason_code": "MARKET_DIAGNOSTIC_FETCH_CAPTURED"}
        if status == "dormant":
            return {"outcome_class": "no_work_expected", "reason_code": "MARKET_DIAGNOSTIC_DORMANT"}
        if status == "waiting_for_paper_week":
            return {"outcome_class": "waiting_dependency", "reason_code": "WAITING_FOR_PAPER_WEEK"}
        if isinstance(status, str) and status in {"broken", "failed", "capture_failed"}:
            return {"outcome_class": "failed_nonblocking", "reason_code": "MARKET_DIAGNOSTIC_FETCH_FAILED"}
        return {"outcome_class": "failed_nonblocking", "reason_code": "OUTCOME_CONTRACT_UNRECOGNIZED"}

    if stage_name == "market_diagnostic_settle":
        status = result.get("settle_status")
        if isinstance(status, str) and status in {"settled", "published", "idempotent", "recovered"}:
            return {"outcome_class": "completed_work", "reason_code": "MARKET_DIAGNOSTIC_SETTLED"}
        if status == "dormant":
            return {"outcome_class": "no_work_expected", "reason_code": "MARKET_DIAGNOSTIC_DORMANT"}
        if isinstance(status, str) and status in {"waiting_for_paper_week", "waiting_for_inputs", "stalled_on_a_finished_week"}:
            return {"outcome_class": "waiting_dependency", "reason_code": status.upper()}
        if isinstance(status, str) and status in {"broken", "failed"}:
            return {"outcome_class": "failed_nonblocking", "reason_code": "MARKET_DIAGNOSTIC_SETTLE_FAILED"}
        return {"outcome_class": "failed_nonblocking", "reason_code": "OUTCOME_CONTRACT_UNRECOGNIZED"}

    if stage_name == "market_diagnostic":
        status = result.get("clock_status")
        if status == "not_started":
            return {"outcome_class": "no_work_expected", "reason_code": "MARKET_DIAGNOSTIC_NOT_STARTED"}
        if status == "fresh":
            return {"outcome_class": "waiting_dependency", "reason_code": "MARKET_DIAGNOSTIC_FIRST_WEEK_PENDING"}
        if status == "broken" or result.get("v1_1_status") == "attribution_faulted":
            return {"outcome_class": "failed_nonblocking", "reason_code": "MARKET_DIAGNOSTIC_FAULTED"}
        if status == "running" and result.get("report_lines_delivered") is True:
            return {"outcome_class": "completed_work", "reason_code": "MARKET_DIAGNOSTIC_REPORTED"}
        if status == "running" and result.get("report_lines") and result.get("report_lines_delivered") is False:
            return {"outcome_class": "failed_nonblocking", "reason_code": "MARKET_DIAGNOSTIC_REPORT_DELIVERY_FAILED"}
        return {"outcome_class": "failed_nonblocking", "reason_code": "OUTCOME_CONTRACT_UNRECOGNIZED"}

    if stage_name == "weekly_bridge" and _bridge_emitted(result) is False:
        no_emit_reason = _bridge_no_emit_reason(result)
        if no_emit_reason == "out_of_window":
            return {"outcome_class": "completed_work", "reason_code": "WEEKLY_REPORT_NOT_EMITTED_OUT_OF_WINDOW"}
        provider_health_reason_codes = {
            "provider_health_restricted": "WEEKLY_REPORT_PROVIDER_HEALTH_RESTRICTED",
            "provider_health_blocked": "WEEKLY_REPORT_PROVIDER_HEALTH_BLOCKED",
        }
        if no_emit_reason in provider_health_reason_codes:
            return {
                "outcome_class": "waiting_dependency",
                "reason_code": provider_health_reason_codes[no_emit_reason],
            }
        return {"outcome_class": "failed_nonblocking", "reason_code": "OUTCOME_CONTRACT_UNRECOGNIZED"}
    return {"outcome_class": "completed_work", "reason_code": "STAGE_COMPLETED"}


def _stage_outcome_counts(outcomes: list[dict[str, Any]]) -> dict[str, int]:
    counts = {key: 0 for key in _STAGE_OUTCOME_CLASSES}
    for outcome in outcomes:
        outcome_class = outcome.get("outcome_class")
        if outcome_class not in counts:
            raise WeeklyCapstoneError("stage outcome list contains an unknown outcome class")
        counts[outcome_class] += 1
    return counts


def _deliver_diagnostic_report_lines(ctx: CapstoneContext, result: dict[str, Any]) -> dict[str, Any]:
    """Hand this stage's lines to the weekly report, or record why they did not land.

    Knife 10c. Every diagnostic stage already produced ``report_lines`` and no
    code path in the repository consumed one, so the whole track was invisible in
    the only artifact an operator reads. The lines go into the section the
    reminder registers itself under; this module does not choose a location and
    does not invent a banner of its own (design section 1.3).

    Total, like the adapters that call it: a report that cannot be annotated is
    reported through the stage result, never raised into the weekly run.
    """

    lines = result.get("report_lines") or []
    if not lines:
        # No lines is the dormant path, and it must not so much as open the file.
        return result
    try:
        from engine.us_short_market_diagnostic_weekly_task import splice_diagnostic_report_lines

        result["report_lines_delivered"] = splice_diagnostic_report_lines(
            _official_output_paths(ctx)[0], lines
        )
    except Exception as exc:  # noqa: BLE001 — a diagnostic may never block selection
        result["report_lines_delivered"] = False
        result["report_lines_problem"] = f"{type(exc).__name__}: {exc}"
    return result


def _run_market_diagnostic(ctx: CapstoneContext) -> dict[str, Any]:
    """Read the 26-week diagnostic clock once a week, or say nothing at all.

    Knife 7b-iv. Design section 12.8 duty 4 wants the official weekly task to read
    ``v1_1_attribution`` by itself and call Knife 6 the moment it activates,
    without depending on anybody remembering. Until this stage existed, nothing in
    any runner had ever read it.

    Dormant is the normal state and has to be free: with no clock opened the step
    returns ``not_started``, this stage writes nothing, contributes no report
    line, and the weekly report is byte-identical to a run without it. A store
    that cannot be read is reported as ``broken`` rather than swallowed into
    silence — but it still never fails the weekly run, because a diagnostic track
    may never block selection or action.

    Knife 10c: whatever it does say now reaches the weekly report's registered
    lifecycle-reminder section. This stage claims no artifact of its own and
    still declares none — it annotates the report the bridge already produced,
    and only in the weeks it has something to say.
    """

    try:
        # Imported inside the try, not above it. Six modules in this chain load a
        # JSON schema at import time; with the import outside, a missing or corrupt
        # schema file raised out of a DORMANT stage, and because this stage is
        # strict that aborted the output transaction and rolled back a
        # weekly_report.md the bridge had already produced. A diagnostic that is
        # not even switched on must not be able to discard a finished week.
        from engine.us_short_market_diagnostic_weekly_task import weekly_diagnostic_step

        # Omitting ``root`` lets the diagnostic track supply its own default,
        # rather than this module naming the private store — which would put all
        # ~90 functions here into the diagnostic authorization surface.
        overrides = {} if ctx.market_diagnostic_root is None else {"root": ctx.market_diagnostic_root}
        # Knife 10b: the cash leg is now produced weekly, so hand it over instead
        # of leaving v1.1 to report `unavailable` beside a file that holds the
        # answer. Loaded by the diagnostic track's own reader, keyed off the
        # ledger's settled weeks rather than off whatever a directory happens to
        # contain. (`target_exposure_by_week` stays absent: its two constraint
        # inputs are never landed by the selection path, and inventing them is
        # what section 12.7 forbids.)
        from runners.us_short_market_diagnostic_weekly_fetch import (
            load_cash_returns, load_target_exposures)

        step = weekly_diagnostic_step(
            as_of_date=ctx.decision_date,
            cash_return_by_week=load_cash_returns(as_of_date=ctx.decision_date, **overrides),
            target_exposure_by_week=load_target_exposures(as_of_date=ctx.decision_date, **overrides),
            **overrides,
        )
    except Exception as exc:  # noqa: BLE001 — see below; this is the whole point of the stage
        # The one broad catch in this file, and it is load-bearing. Design section
        # 1.2: the diagnostic track may never change or block selection. It also
        # cannot be `best_effort` (reserved for comparison capture) or
        # `zero_effect` (that policy means the soft-discovery receipt shape), so
        # the only honest way to keep a read-only diagnostic from taking down a
        # week of stock selection is for its adapter to be total. The failure is
        # reported, not hidden.
        result = {
            "clock_status": "broken",
            "problem": f"{type(exc).__name__}: {exc}",
            "report_lines": [
                "26 周诊断轨：本周读取失败，已记为故障；不影响选股与操作建议。"
            ],
            "provider_calls_performed": False,
        }
    else:
        result = {
            "clock_status": step["status"],
            "v1_1_status": step.get("v1_1_status"),
            "calendar_week_count": step.get("calendar_week_count"),
            "report_lines": step["report_lines"],
            "problem": step.get("problem"),
            "provider_calls_performed": False,
        }
    return _deliver_diagnostic_report_lines(ctx, result)


def _diagnostic_overrides(ctx: CapstoneContext) -> dict[str, Any]:
    """Only ever an override; the default root stays the diagnostic track's own.

    Naming the private store here would pull every function in this module into
    that track's authorization surface — the ~90-exemption shape Knife 7b hit and
    backed out of.
    """

    return {} if ctx.market_diagnostic_root is None else {"root": ctx.market_diagnostic_root}


def _run_market_diagnostic_fetch(ctx: CapstoneContext) -> dict[str, Any]:
    """Knife 10b: capture benchmark prices, ETF total return, and cash, or do nothing.

    The first of the two steps that finally make the clock ADVANCE rather than
    only be read. Dormant is free in the strongest sense: with no clock opened
    this performs no request and writes no byte, so a weekly run is unchanged by
    whether the diagnostic track exists.
    """

    try:
        from runners.us_short_market_diagnostic_weekly_fetch import fetch_next_week

        # This stage is `gated`, so the pipeline has already made the operator
        # authorize a live fetch before it runs; passing that through is what the
        # direct and CLI paths now also have to do explicitly.
        outcome = fetch_next_week(
            as_of_date=ctx.decision_date,
            confirm_user_authorization=True,
            **_diagnostic_overrides(ctx),
        )
    except Exception as exc:  # noqa: BLE001 — a diagnostic may never block selection
        result = {
            "fetch_status": "failed",
            "problem": f"{type(exc).__name__}: {exc}",
            # A capture that died is exactly the week a reader must not have to
            # infer from the report saying nothing.
            "report_lines": [_DIAGNOSTIC_FETCH_FAILED_LINE],
            # Unknown, and an unknown at a paid boundary is not a `False`. Nothing
            # reached the point of counting, so the honest answer is that we
            # cannot say -- reported as True so a reader is never told "no
            # provider call" on the strength of an exception.
            "provider_calls_performed": True,
        }
    else:
        result = {
            "fetch_status": outcome["status"],
            "calendar_week_index": outcome.get("calendar_week_index"),
            "cash_status": outcome.get("cash_status"),
            "evaluable_symbols": outcome.get("evaluable_symbols"),
            "total_return_status": outcome.get("total_return_status"),
            "total_return_evaluable_symbols": outcome.get("total_return_evaluable_symbols"),
            "problem": outcome.get("problem"),
            "report_lines": (
                [_DIAGNOSTIC_FETCH_FAILED_LINE] if outcome["status"] == "capture_failed" else []
            ),
            # The count the capture actually kept, not an inference from its status.
            "provider_calls_performed": bool(outcome.get("provider_calls", 0)),
        }
    return _deliver_diagnostic_report_lines(ctx, result)


def _run_market_diagnostic_settle(ctx: CapstoneContext) -> dict[str, Any]:
    """Knife 10b: settle the captured week, and let a closed window publish itself."""

    try:
        from runners.us_short_market_diagnostic_weekly_fetch import settle_captured_week

        outcome = settle_captured_week(as_of_date=ctx.decision_date, **_diagnostic_overrides(ctx))
    except Exception as exc:  # noqa: BLE001 — same rule as the stage above
        result = {
            "settle_status": "failed",
            "problem": f"{type(exc).__name__}: {exc}",
            "report_lines": [_DIAGNOSTIC_SETTLE_LINES["failed"]],
            "provider_calls_performed": False,
        }
    else:
        status = outcome["status"]
        stalled = _DIAGNOSTIC_SETTLE_LINES.get(status)
        lines = [stalled] if stalled is not None else []
        no_count_weeks = outcome.get("no_count_weeks") or []
        if no_count_weeks:
            # A calendar week was spent without a strategy result. Section 12.8
            # duty 3 keeps it in the 26-week denominator, so a reader who is never
            # told cannot tell a 26-week verdict apart from a 24-week one. Week
            # numbers only — the reason is a fixed string for the same privacy
            # rule as the lines above.
            lines.append(_DIAGNOSTIC_NO_COUNT_LINE.format(
                weeks="、".join(str(week) for week in no_count_weeks)
            ))
        result = {
            "settle_status": status,
            "calendar_week_index": outcome.get("calendar_week_index"),
            "publication": outcome.get("publication"),
            "no_count_weeks": no_count_weeks,
            # A week that did not advance says so; a week that settled is already
            # described by the reader stage's registered reminder line.
            "report_lines": lines,
            "provider_calls_performed": False,
        }
    return _deliver_diagnostic_report_lines(ctx, result)


def _write_private_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _run_model_paper_adapter(ctx: CapstoneContext) -> dict[str, Any]:
    """Local pre-plan seam: mature in memory, then replace the generated paper account with its adapter."""
    if not _model_paper_enabled(ctx):
        return {"model_paper_enabled": False, "provider_calls_performed": False}
    from runners.us_short_model_paper_weekly_capstone import prepare_offline_model_paper_adapter

    preview = prepare_offline_model_paper_adapter(
        store_root=str(ctx.model_paper_store_root), decision_date=ctx.decision_date,
        price_basis_date=ctx.price_basis_date,
        arrived_ohlcv_packet=json.loads(ctx.ohlcv_series_packet_path.read_text(encoding="utf-8")),
    )
    _write_private_json(ctx.account_state_path, preview.pop("account_state"))
    return preview


def _run_model_paper_weekly(ctx: CapstoneContext) -> dict[str, Any]:
    """Terminal local seam: bind the emitted machine record, atomically mature/freeze, then add seven report facts."""
    if not _model_paper_enabled(ctx):
        return {"model_paper_enabled": False, "provider_calls_performed": False}
    from runners.us_short_model_paper_weekly_capstone import (
        append_fixed_weekly_portfolio_section,
        fixed_weekly_portfolio_metrics,
        paper_plan_factory_from_machine_record,
        run_offline_model_paper_capstone,
    )

    root = ctx.official_output_root or ctx.private_root
    machine_path = root / "runs_private" / ctx.decision_date / "machine_record.json"
    report_path = root / "weekly_private" / ctx.decision_date / "weekly_report.md"
    result = run_offline_model_paper_capstone(
        run_account_mode=ctx.model_paper_run_account_mode or "paper_only",
        store_root=str(ctx.model_paper_store_root), decision_date=ctx.decision_date,
        price_basis_date=ctx.price_basis_date, created_at=ctx.generated_at,
        arrived_ohlcv_packet=json.loads(ctx.ohlcv_series_packet_path.read_text(encoding="utf-8")),
        paper_plan_factory=paper_plan_factory_from_machine_record(machine_path),
    )
    metrics = fixed_weekly_portfolio_metrics(store_root=str(ctx.model_paper_store_root))
    append_fixed_weekly_portfolio_section(report_path, metrics)
    return {**result, "model_paper_enabled": True, "weekly_portfolio_metrics": metrics}


def _tz_aware_et_or_fail(now_et: datetime) -> datetime:
    """Attach America/New_York to a naive ET wall-clock, failing closed on a DST transition (F6 completeness).

    A weekly pre-open/post-close run never legitimately lands in a DST transition, so a spring-forward GAP (a
    nonexistent wall-clock) or a fall-back FOLD (an ambiguous wall-clock) is a bad `now_et` — reject it rather than
    silently pick one UTC offset. A normal time is neither and passes through DST-correctly.
    """
    et = ZoneInfo("America/New_York")
    aware = now_et.replace(tzinfo=et)
    in_gap = aware.astimezone(timezone.utc).astimezone(et).replace(tzinfo=None) != now_et
    is_ambiguous = aware.utcoffset() != aware.replace(fold=1).utcoffset()
    if in_gap or is_ambiguous:
        raise WeeklyCapstoneError(
            "now_et is inside a DST transition (nonexistent spring-forward or ambiguous fall-back wall-clock); "
            "supply an unambiguous pre-open/post-close ET time")
    return aware


def _format_live_provider_clock_error(preflight: dict[str, Any]) -> str:
    requested = preflight.get("requested") if isinstance(preflight.get("requested"), dict) else {}
    actual = preflight.get("actual") if isinstance(preflight.get("actual"), dict) else {}
    return (
        "live_provider_clock_incompatible "
        f"[{preflight.get('reason_code', 'UNKNOWN')}] "
        f"requested decision_date={requested.get('decision_date') or '<unresolved>'} "
        f"price_basis_date={requested.get('price_basis_date') or '<unresolved>'}; "
        f"actual decision_date={actual.get('decision_date') or '<unresolved>'} "
        f"price_basis_date={actual.get('price_basis_date') or '<unresolved>'} "
        f"window_state={preflight.get('actual_window_state') or '<unresolved>'}; "
        "live provider only supports the real current canonical window; "
        "historical analysis use frozen raw/offline replay"
    )


def prepare_live_provider_context(
    ctx: CapstoneContext,
    *,
    calendar_path: Path,
    requested_now_et: datetime | None = None,
) -> CapstoneContext:
    """Gate a provider run and replace requested clocks with the actual ET clock."""

    calendar = load_market_calendar(calendar_path)
    requested_clock = getattr(ctx, "now_et", requested_now_et)
    if not isinstance(requested_clock, datetime):
        raise WeeklyCapstoneError("live provider clock preflight requires a requested naive ET clock")
    preflight = inspect_live_provider_clock(
        requested_now_et=requested_clock,
        calendar=calendar,
    )
    if preflight["compatible"] is not True:
        raise WeeklyCapstoneError(_format_live_provider_clock_error(preflight))
    actual_now_et = datetime.fromisoformat(preflight["actual"]["now_et"])
    actual_generated_at = _tz_aware_et_or_fail(actual_now_et).isoformat(timespec="seconds")
    values = {
        "now_et": actual_now_et,
        "generated_at": actual_generated_at,
        "observed_at": actual_generated_at,
        "live_provider_preflight": preflight,
    }
    if isinstance(ctx, CapstoneContext):
        return replace(ctx, **values)
    updated = copy.copy(ctx)
    for name, value in values.items():
        setattr(updated, name, value)
    return updated


def resolve_capstone_context(
    *,
    now_et: datetime,
    private_root: Path,
    batch4_template_path: Path,
    account_state_path: Path,
    authorized_momentum_top_k: int = 200,
    authorized_pass2_call_budget: int | None = None,
    pass2_budget_preview: bool = False,
    catalyst_recall_tickers: tuple[str, ...] = (),
    calendar_path: Path = CALENDAR_PRESET,
    confirm_user_authorization: bool = False,
    provider_pace_seconds: float = 0.0,
    max_retries_per_call: int = 0,
    retry_backoff_seconds: float = 0.0,
    max_total_http_attempts: int | None = None,
    model_paper_store_root: Path | None = None,
    model_paper_run_account_mode: str | None = None,
    soft_discovery_enabled: bool = True,
    theme_soft_boost_enabled: bool = True,
    state_dir: Path = STATE_DIR,
    sample_root: Path = ROOT,
) -> CapstoneContext:
    """Resolve the §2.1 canonical decision_date + price_basis_date from `now_et` and the frozen calendar, and build
    the run context. Fail-closed: an intraday `now_et` (session dead zone) raises WeeklyCapstoneError (no run)."""
    if type(soft_discovery_enabled) is not bool:
        raise WeeklyCapstoneError("soft_discovery_enabled must be an exact bool")
    if type(theme_soft_boost_enabled) is not bool:
        raise WeeklyCapstoneError("theme_soft_boost_enabled must be an exact bool")
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
    # PIT observation instant = the ET run wall-clock made TZ-AWARE. The status source + Cut5 engines REQUIRE a
    # tz-aware observed_at (a naive string is rejected as a non-PIT clock); America/New_York is DST-correct.
    generated_at = _tz_aware_et_or_fail(now_et).isoformat(timespec="seconds")
    try:
        prior_run_dir = resolve_prior_run_dir(
            Path(private_root).resolve() / "runs_private", resolved["decision_date"])
        if prior_run_dir is None:
            prior_regime, prior_upgrade_count = None, 0
        else:
            prior_state = load_market_regime_state(
                prior_run_dir / MARKET_REGIME_STATE_FILENAME,
                decision_date=resolved["decision_date"],
            )
            if prior_state["as_of"] != prior_run_dir.name:
                raise MarketRegimeStateError("prior market-regime state date does not match its dated directory")
            prior_regime = prior_state["market_risk_regime"]
            prior_upgrade_count = prior_state["upgrade_count"]
    except PrivatePathError as exc:
        raise WeeklyCapstoneError("private output preflight rejected prior state root") from exc
    except (WeekendPrivateWriteError, MarketRegimeStateError, OSError, ValueError) as exc:
        raise WeeklyCapstoneError("selected prior cross-week state is unavailable") from exc
    return CapstoneContext(
        decision_date=resolved["decision_date"],
        price_basis_date=resolved["price_basis_date"],
        now_et=now_et,
        generated_at=generated_at,
        observed_at=generated_at,
        private_root=Path(private_root),
        batch4_template_path=Path(batch4_template_path),
        account_state_path=Path(account_state_path),
        authorized_momentum_top_k=authorized_momentum_top_k,
        authorized_pass2_call_budget=authorized_pass2_call_budget,
        pass2_budget_preview=pass2_budget_preview,
        catalyst_recall_tickers=tuple(catalyst_recall_tickers),
        confirm_user_authorization=confirm_user_authorization,
        provider_pace_seconds=provider_pace_seconds,
        max_retries_per_call=max_retries_per_call,
        retry_backoff_seconds=retry_backoff_seconds,
        max_total_http_attempts=max_total_http_attempts,
        model_paper_store_root=Path(model_paper_store_root) if model_paper_store_root is not None else None,
        model_paper_run_account_mode=model_paper_run_account_mode,
        # ``None`` means "the diagnostic track's own default root", resolved
        # lazily in the stage adapter. The default is NOT spelled out here: naming
        # the private root in this module would drag all ~90 of its functions into
        # the diagnostic authorization surface, where they would need ~90
        # exemptions — and an exemption list that large is an off switch, not a
        # list of exceptions.
        prior_run_dir=prior_run_dir,
        prior_regime=prior_regime,
        prior_upgrade_count=prior_upgrade_count,
        soft_discovery_enabled=soft_discovery_enabled,
        theme_soft_boost_enabled=theme_soft_boost_enabled,
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
    best_effort: bool = False
    contract_version: str = "1.0.0"
    reuse_policy: str = "never"
    # Lifecycle policy defaults are deliberately strict.  A stage must opt into
    # optional zero-effect handling explicitly; an unannotated/new stage can
    # therefore never silently inherit the soft-discovery boundary.
    failure_policy: str = "strict"
    output_policy: str = "required"
    checkpoint_policy: str = "required"
    failure_handler: Callable[["Stage", CapstoneContext, Exception], dict[str, Any]] | None = None


STAGE_FAILURE_POLICIES = frozenset({"strict", "zero_effect"})
STAGE_OUTPUT_POLICIES = frozenset({"required", "optional"})
STAGE_CHECKPOINT_POLICIES = frozenset({"required", "optional_result_only"})
STAGE_LIFECYCLE_POLICY_REGISTRY = {
    "strict": {"output_policy": "required", "checkpoint_policy": "required"},
    "zero_effect": {"output_policy": "optional", "checkpoint_policy": "optional_result_only"},
}


def _stage_is_optional(stage: Stage) -> bool:
    return stage.failure_policy == "zero_effect"


def _validate_stage_lifecycle(stages: list[Stage]) -> None:
    """Validate the finite lifecycle policy before any stage can run."""
    for stage in stages:
        if stage.failure_policy not in STAGE_FAILURE_POLICIES:
            raise WeeklyCapstoneError(f"stage '{stage.name}' has an unknown failure policy")
        if stage.output_policy not in STAGE_OUTPUT_POLICIES:
            raise WeeklyCapstoneError(f"stage '{stage.name}' has an unknown output policy")
        if stage.checkpoint_policy not in STAGE_CHECKPOINT_POLICIES:
            raise WeeklyCapstoneError(f"stage '{stage.name}' has an unknown checkpoint policy")
        expected = STAGE_LIFECYCLE_POLICY_REGISTRY[stage.failure_policy]
        if stage.output_policy != expected["output_policy"] or stage.checkpoint_policy != expected["checkpoint_policy"]:
            if stage.failure_policy == "strict":
                raise WeeklyCapstoneError(
                    f"strict stage '{stage.name}' cannot use optional output/checkpoint policy"
                )
            else:
                raise WeeklyCapstoneError(
                    f"zero-effect stage '{stage.name}' must declare optional output/checkpoint policy"
                )
        if stage.failure_policy == "zero_effect":
            if stage.failure_handler is None:
                raise WeeklyCapstoneError(f"zero-effect stage '{stage.name}' lacks a failure handler")
            if stage.reuse_policy != "never":
                raise WeeklyCapstoneError(
                    f"zero-effect stage '{stage.name}' must never reuse an artifact-less result"
                )


def default_pipeline(
    *, include_model_paper: bool = False, include_soft_discovery: bool = True,
) -> list[Stage]:
    """The weekly pipeline in dependency order. Each `run` adapter calls the corresponding real runner
    with dates/paths from the context (imported lazily so an offline dry-run / a stage-injected test never imports a
    provider runner it will not call)."""
    if type(include_soft_discovery) is not bool:
        raise WeeklyCapstoneError("include_soft_discovery must be an exact bool")
    from runners import us_short_weekly_capstone_stages as st  # thin adapters over the real runners
    stages = [
        Stage("universe_fetch", True, lambda c: [], lambda c: [c.candidate_path], st.run_universe,
              contract_version="1.1.0", reuse_policy="refresh_then_reuse_if_equivalent"),
        Stage("momentum_fetch", True, lambda c: [c.candidate_path],
              lambda c: [c.series_packet_path, c.ohlcv_series_packet_path], st.run_momentum_fetch,
              contract_version="1.0.0", reuse_policy="frozen_inputs"),
        Stage("model_paper_adapter", False,
              lambda c: [c.ohlcv_series_packet_path] if _model_paper_enabled(c) else [],
              lambda c: [c.account_state_path] if _model_paper_enabled(c) else [], _run_model_paper_adapter,
              contract_version="1.0.0", reuse_policy="never"),
        Stage("overextension_producer", False, lambda c: [c.candidate_path, c.ohlcv_series_packet_path],
              lambda c: [c.overextension_projection_path], st.run_overextension_producer,
              contract_version="1.0.0", reuse_policy="frozen_inputs"),
        Stage("momentum_producer", False, lambda c: [c.candidate_path, c.series_packet_path],
              lambda c: [c.momentum_projection_path], st.run_momentum_producer,
              contract_version="1.0.0", reuse_policy="frozen_inputs"),
        Stage("sic_fetch", True, lambda c: [c.candidate_path], lambda c: [c.classification_packet_path],
              st.run_sic_fetch, contract_version="1.0.0", reuse_policy="frozen_inputs"),
        Stage("soft_discovery", False, lambda c: [],
              lambda c: [c.soft_discovery_receipt_path], st.run_soft_discovery,
              contract_version="1.0.0", reuse_policy="never",
              failure_policy="zero_effect", output_policy="optional",
              checkpoint_policy="optional_result_only",
              failure_handler=_degrade_soft_discovery_boundary),
        Stage("serenity_quality_forward", False,
              lambda c: [c.soft_discovery_receipt_path] if c.soft_discovery_run_result is not None else [],
              lambda c: [c.serenity_quality_observation_path, c.serenity_quality_ledger_path,
                          c.serenity_quality_gate_path, c.serenity_g1_blade6_preflight_path],
              st.run_serenity_quality_forward,
              contract_version="1.0.0", reuse_policy="never",
              failure_policy="zero_effect", output_policy="optional",
              checkpoint_policy="optional_result_only",
              failure_handler=_degrade_serenity_quality_boundary),
        Stage("theme_producer", False,
              lambda c: [c.candidate_path, c.series_packet_path, c.classification_packet_path],
              lambda c: [c.theme_projection_path], st.run_theme_producer,
              contract_version="1.0.0", reuse_policy="frozen_inputs"),
        Stage("projection_inputs", False, lambda c: [c.momentum_projection_path, c.theme_projection_path],
              lambda c: [c.merged_momentum_path, c.merged_theme_path], st.run_projection_inputs,
              contract_version="1.0.0", reuse_policy="frozen_inputs"),
        Stage("pass2_preflight", False, lambda c: [c.merged_momentum_path, c.merged_theme_path],
              lambda c: [c.preflight_summary_path], st.run_pass2_preflight,
              contract_version="1.0.0", reuse_policy="frozen_inputs"),
        Stage("yfinance_grades_fetch", True, lambda c: [c.preflight_summary_path],
              lambda c: [c.yfinance_grade_source_package_path, c.yfinance_grade_actions_path],
              st.run_yfinance_grades_fetch, contract_version="1.1.0"),
        Stage("pass2_fetch", True, lambda c: [c.preflight_summary_path, c.overextension_projection_path,
                                               c.yfinance_grade_actions_path, c.ohlcv_series_packet_path],
              lambda c: [c.source_packet_path, c.context_components_path], st.run_pass2_fetch,
              contract_version="2.2.0"),
        Stage("vix_regime", True, lambda c: [], lambda c: [c.vix_regime_summary_path], st.run_vix_regime),
        Stage("forward_policy_shadow", False,
              lambda c: [c.data_context_path, c.context_components_path, c.ohlcv_series_packet_path,
                         c.vix_regime_summary_path, c.batch4_template_path],
              lambda c: [c.forward_shadow_selection_private_path, c.forward_policy_summary_path,
                         c.forward_policy_source_capture_private_path],
              st.run_forward_policy_shadow, best_effort=True),
        Stage("forward_policy_corporate_actions", True, lambda c: [c.ohlcv_series_packet_path],
              lambda c: [c.forward_policy_corporate_action_summary_path],
              st.run_forward_policy_corporate_actions, best_effort=True),
        Stage("forward_policy_maturity", False, lambda c: [c.ohlcv_series_packet_path], lambda c: [],
              st.run_forward_policy_maturity, best_effort=True),
        Stage("soft_boost_comparison_maturity", False,
              lambda c: ([c.ohlcv_series_packet_path] if c.theme_soft_boost_enabled
                         and c.soft_boost_pairwise_ledger_path.is_file() else []), lambda c: [],
              st.run_soft_boost_comparison_maturity, best_effort=True,
              contract_version="1.0.0", reuse_policy="never"),
        Stage("soft_boost_comparison_capture", False,
              lambda c: ([c.soft_boost_consumption_receipt_path, c.soft_boost_shadow_receipt_path]
                         if st.classify_soft_boost_artifact_state(c)["state"] == "comparison_ready" else []),
              lambda c: ([c.soft_boost_pairwise_ledger_path]
                         if st.classify_soft_boost_artifact_state(c)["state"] == "comparison_ready" else []),
              st.run_soft_boost_comparison_capture, best_effort=True,
              contract_version="1.0.0", reuse_policy="never"),
        Stage("weekly_bridge", False, lambda c: [c.source_packet_path], _official_output_paths, st.run_weekly_bridge),
        Stage("model_paper_weekly", False,
              lambda c: ([c.ohlcv_series_packet_path, _official_output_paths(c)[0], _official_output_paths(c)[2]]
                         if _model_paper_enabled(c) else []),
              lambda c: [_official_output_paths(c)[0]] if _model_paper_enabled(c) else [], _run_model_paper_weekly,
              contract_version="1.0.0", reuse_policy="never"),
        # Last, and deliberately inert: it reads a clock that is not running yet
        # and claims no artifact. Ordinary strict policy — `best_effort` is
        # reserved for comparison-capture stages and `zero_effect` carries the
        # soft-discovery receipt shape; this stage is neither and must not
        # borrow either label. Its adapter is total instead.
        # Knife 10b: the two steps that make the clock advance, not merely be
        # read. Both are total adapters for the same reason the reader below is,
        # and both are inert while the clock is dormant.
        Stage("market_diagnostic_fetch", True, lambda c: [], lambda c: [],
              _run_market_diagnostic_fetch, contract_version="1.0.0", reuse_policy="never"),
        Stage("market_diagnostic_settle", False, lambda c: [], lambda c: [],
              _run_market_diagnostic_settle, contract_version="1.0.0", reuse_policy="never"),
        Stage("market_diagnostic", False, lambda c: [], lambda c: [], _run_market_diagnostic,
              contract_version="1.0.0", reuse_policy="never"),
    ]
    excluded = set()
    if not include_model_paper:
        excluded.update({"model_paper_adapter", "model_paper_weekly"})
    if not include_soft_discovery:
        excluded.add("soft_discovery")
    return [stage for stage in stages if stage.name not in excluded]


def _official_output_paths(ctx: CapstoneContext) -> list[Path]:
    """All three official siblings for one run; the report alone is not a commit marker."""
    root = ctx.official_output_root or ctx.private_root
    return [
        root / "weekly_private" / ctx.decision_date / "weekly_report.md",
        root / "weekly_private" / ctx.decision_date / "action_table.csv",
        root / "runs_private" / ctx.decision_date / "machine_record.json",
    ]


def _preflight_private_output_paths(ctx: CapstoneContext) -> None:
    """Prove every private leaf before live settlement, checkpoints, or provider stages begin."""
    paths: list[tuple[Path, str]] = [
        (ctx.account_state_path, "account_state_path"),
        (ctx.context_packet_path, "context_packet_path"),
        (ctx.private_root / "lifecycle" / "lifecycle_register.json", "lifecycle_register_path"),
    ]
    paths.extend(
        (path, label)
        for path, label in zip(
            _official_output_paths(ctx),
            ("weekly_report_path", "action_table_path", "machine_record_path"),
        )
    )
    if _model_paper_enabled(ctx):
        paths.append((ctx.model_paper_store_root / "head_manifest.json", "model_paper_head_manifest_path"))
    for path, label in paths:
        try:
            reject_nonprivate_output_path(path)
        except PrivatePathError as exc:
            raise WeeklyCapstoneError(
                f"private output preflight rejected {label}: {Path(path).resolve()}"
            ) from exc


def _plan(ctx: CapstoneContext, stages: list[Stage], *, resume_from: Path | None = None) -> dict[str, Any]:
    """The dry-run plan: canonical dates + every stage's gated flag + I/O paths. No execution, no fetch."""
    return {
        "mode": "dry_run",
        "decision_date": ctx.decision_date,
        "price_basis_date": ctx.price_basis_date,
        "run_date": ctx.now_et.strftime("%Y%m%d"),
        "live_provider_preflight": copy.deepcopy(ctx.live_provider_preflight),
        "gated_stages_need_authorization": [s.name for s in stages if s.gated],
        "authorized": ctx.confirm_user_authorization,
        "resume_from": str(Path(resume_from).resolve()) if resume_from is not None else None,
        "stage_outcomes": [],
        "stage_outcome_counts": _stage_outcome_counts([]),
        "stages": [
            {
                "name": s.name,
                "kind": "gated_live_fetch" if s.gated else "offline",
                "best_effort": s.best_effort,
                "contract_version": s.contract_version,
                "reuse_policy": s.reuse_policy,
                "failure_policy": s.failure_policy,
                "output_policy": s.output_policy,
                "checkpoint_policy": s.checkpoint_policy,
                "inputs": [_rel(p) for p in s.inputs(ctx)],
                "outputs": [_rel(p) for p in s.outputs(ctx)],
            }
            for s in stages
        ],
    }


def _checkpoint_run_contract(ctx: CapstoneContext) -> dict[str, Any]:
    """Non-file inputs that can change frozen-stage output despite identical artifact SHA-256s."""
    approval = ctx.budget_approval
    annotation = ctx.serenity_annotation_payload
    annotation_identity = annotation.get("identity_envelope") if isinstance(annotation, dict) else None
    return {
        "authorized_momentum_top_k": ctx.authorized_momentum_top_k,
        "authorized_pass2_call_budget": (
            approval.exact_pass2_calls if approval is not None else ctx.authorized_pass2_call_budget
        ),
        "catalyst_recall_tickers": list(ctx.catalyst_recall_tickers),
        "frozen_holding_tickers": list(ctx.frozen_holding_tickers or ()),
        "theme_soft_boost_enabled": ctx.theme_soft_boost_enabled,
        "serenity_annotation_payload_identity": {
            key: annotation_identity.get(key)
            for key in (
                "upstream_input_packet_id", "upstream_decision_result_id", "upstream_policy_version",
                "upstream_decision_date", "rubric_version", "annotation_author_kind",
                "prompt_or_protocol_id", "model_identity", "generated_at",
            )
        } if isinstance(annotation_identity, dict) else None,
    }


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(p)


def _assert_input_outside_archived_outputs(ctx: CapstoneContext, path: Path, label: str) -> None:
    """C3 footgun guard. A live run ARCHIVES the whole weekly_private/<decision_date>/ and runs_private/<decision_date>/
    trees (moves them under _superseded/) BEFORE any stage runs, so an operator input colocated there would be moved
    mid-run and the terminal bridge would fail reading it only AFTER a full provider fetch. Reject such a path up front
    (checked for dry-run too, so the plan preview surfaces it) — before touching a provider."""
    resolved = Path(path).resolve()
    for surface in ("weekly_private", "runs_private"):
        archived = (ctx.private_root / surface / ctx.decision_date).resolve()
        if resolved == archived or archived in resolved.parents:
            raise WeeklyCapstoneError(
                f"{label} ({_rel(resolved)}) is inside {surface}/{ctx.decision_date}/, which a live run archives "
                f"before fetching (C3) — place run inputs OUTSIDE the per-decision output dir "
                f"(e.g. under weekly_private/_run_inputs/)")


def _safe_tag(generated_at: str) -> str:
    """A filesystem-safe historical tag from the RFC3339 generated_at (non-alphanumerics → '-')."""
    return "".join(c if c.isalnum() else "-" for c in generated_at) or "run"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_pass2_budget_approval(
    ctx: CapstoneContext,
    preflight: dict[str, Any],
    *,
    authorization_mode: str,
) -> Pass2BudgetApproval:
    """Mint the single approval from the already-written preflight derivation."""
    try:
        candidate = preflight["candidate_universe"]
        clock = preflight["decision_clock"]
        targets = preflight["pass2_target_universe"]
        forecast = preflight["endpoint_call_forecast"]
        candidate_sha = candidate["candidate_artifact_sha256"]
        derived = {
            "decision_date": clock["expected_decision_date"],
            "candidate_price_basis_date": clock["candidate_price_basis_date"],
            "momentum_top_k": targets["momentum_top_k"],
            "target_count": targets["target_count"],
            "exact_pass2_calls": forecast["total_calls_for_pass2_target_cut"],
        }
    except (KeyError, TypeError) as exc:
        raise WeeklyCapstoneError("pass2 preflight lacks the immutable approval derivation fields") from exc
    if derived["decision_date"] != ctx.decision_date:
        raise WeeklyCapstoneError("Pass2 budget approval decision_date does not match the capstone context")
    if derived["candidate_price_basis_date"] != ctx.price_basis_date:
        raise WeeklyCapstoneError("Pass2 budget approval candidate price basis date does not match the capstone context")
    if type(candidate_sha) is not str or candidate_sha != _sha256_file(ctx.candidate_path):
        raise WeeklyCapstoneError("Pass2 budget approval candidate artifact fingerprint does not match current bytes")
    if derived["momentum_top_k"] != ctx.authorized_momentum_top_k:
        raise WeeklyCapstoneError("Pass2 budget approval momentum_top_k does not match the capstone context")
    if type(ctx.authorized_pass2_call_budget) is int and not isinstance(ctx.authorized_pass2_call_budget, bool):
        if ctx.authorized_pass2_call_budget != derived["exact_pass2_calls"]:
            raise WeeklyCapstoneError(
                "Pass2 budget approval exact call budget does not match the existing preflight derivation: "
                f"approved {ctx.authorized_pass2_call_budget}, derived {derived['exact_pass2_calls']}"
            )
    approval = Pass2BudgetApproval(
        **derived,
        candidate_artifact_sha256=candidate_sha,
        authorization_mode=authorization_mode,
        authorization_ref=f"{authorization_mode}:{ctx.decision_date}:{ctx.generated_at}",
        generated_at=ctx.generated_at,
    )
    return approval


def _restore_pass2_budget_approval(ctx: CapstoneContext, preflight: dict[str, Any]) -> Pass2BudgetApproval:
    """Restore the immutable manual approval from a finalized checkpointed preflight."""
    if not isinstance(preflight, dict):
        raise WeeklyCapstoneError("checkpointed Pass2 preflight result is not an object")
    gate = preflight.get("execution_gate")
    binding = gate.get("approval_binding") if isinstance(gate, dict) else None
    try:
        binding = Pass2BudgetApproval.validate_binding_summary(binding)
    except (TypeError, ValueError) as exc:
        raise WeeklyCapstoneError(f"checkpointed Pass2 preflight approval binding is invalid: {exc}") from exc
    if binding["authorization_mode"] != "manual":
        raise WeeklyCapstoneError("only a manually authorized Pass2 checkpoint may be resumed")
    if preflight.get("scope", {}).get("status") != "ready_for_reviewed_live_execution":
        raise WeeklyCapstoneError("checkpointed Pass2 preflight is not finalized for execution")
    if gate.get("ready_to_run_full_candidate_live_packet") is not True or gate.get("block_reasons") != []:
        raise WeeklyCapstoneError("checkpointed Pass2 preflight execution gate is not finalized")
    candidate = preflight.get("candidate_universe")
    clock = preflight.get("decision_clock")
    targets = preflight.get("pass2_target_universe")
    forecast = preflight.get("endpoint_call_forecast")
    if not all(isinstance(value, dict) for value in (candidate, clock, targets, forecast)):
        raise WeeklyCapstoneError("checkpointed Pass2 preflight lacks approval binding inputs")
    checks = (
        ("decision_date", ctx.decision_date, clock.get("expected_decision_date"), binding["decision_date"]),
        ("candidate_price_basis_date", ctx.price_basis_date, clock.get("candidate_price_basis_date"), binding["candidate_price_basis_date"]),
        ("momentum_top_k", ctx.authorized_momentum_top_k, targets.get("momentum_top_k"), binding["momentum_top_k"]),
        ("target_count", targets.get("target_count"), binding["target_count"], binding["target_count"]),
        ("exact_pass2_calls", forecast.get("total_calls_for_pass2_target_cut"), binding["exact_pass2_calls"], binding["exact_pass2_calls"]),
        ("generated_at", preflight.get("generated_at"), binding["generated_at"], binding["generated_at"]),
    )
    for field, context_value, derived_value, binding_value in checks:
        if context_value != derived_value or derived_value != binding_value:
            raise WeeklyCapstoneError(f"checkpointed Pass2 approval {field} does not match current run")
    candidate_sha = candidate.get("candidate_artifact_sha256")
    if candidate_sha != binding["candidate_artifact_sha256"] or candidate_sha != _sha256_file(ctx.candidate_path):
        raise WeeklyCapstoneError("checkpointed Pass2 approval candidate artifact fingerprint does not match current bytes")
    if gate.get("authorized_momentum_top_k") != binding["momentum_top_k"]:
        raise WeeklyCapstoneError("checkpointed Pass2 approval momentum_top_k is not authorized in the gate")
    if gate.get("authorized_total_call_budget") != binding["exact_pass2_calls"]:
        raise WeeklyCapstoneError("checkpointed Pass2 approval call budget is not authorized in the gate")
    if ctx.authorized_pass2_call_budget != binding["exact_pass2_calls"]:
        raise WeeklyCapstoneError("checkpointed Pass2 approval call budget does not match the current run")
    return Pass2BudgetApproval(**{
        field: binding[field]
        for field in (
            "decision_date", "candidate_price_basis_date", "candidate_artifact_sha256",
            "momentum_top_k", "target_count", "exact_pass2_calls", "authorization_mode",
            "authorization_ref", "generated_at",
        )
    })


def _output_fingerprint(path: Path):
    try:
        stat = Path(path).stat()
        return (stat.st_size, stat.st_mtime_ns, _sha256_file(Path(path)))
    except OSError:
        return None


def _input_readable(path: Path) -> bool:
    """A declared stage input is usable this run iff it exists as a readable file. Existence + readability ONLY —
    schema / date / identity / digest stay each business runner's job (design: the capstone does NOT duplicate a
    second validation framework). Missing / unreadable / a directory in the input slot all fail closed."""
    try:
        with Path(path).open("rb") as handle:
            handle.read(1)
    except OSError:
        return False
    return True


def _unchanged_soft_discovery_receipt_matches(
    stage: Stage, result: dict[str, Any], expected_outputs: list[Path],
) -> bool:
    if not _stage_is_optional(stage) or len(expected_outputs) != 1:
        return False
    try:
        frozen_bytes = expected_outputs[0].read_bytes()
    except OSError:
        return False
    try:
        if json.loads(frozen_bytes.decode("utf-8")) == result:
            return True
    except (UnicodeDecodeError, ValueError):
        pass
    if not (
        isinstance(result, dict)
        and result.get("status") == "invalid_evidence"
        and result.get("reason_code") == "SOFT_DISCOVERY_IMMUTABLE_CONFLICT"
        and result.get("validated_theme_count") == 0
        and result.get("boostable_ticker_count") == 0
    ):
        return False
    try:
        from runners.us_short_weekly_capstone_soft_discovery import _schema_validate

        _schema_validate(result)
    except Exception:
        return False
    effects = result.get("effects")
    if type(effects) is not dict or any(value is not False for value in effects.values()):
        return False
    binding = result.get("immutable_conflict")
    canonical = binding.get("canonical_receipt") if isinstance(binding, dict) else None
    if not isinstance(canonical, dict):
        return False
    try:
        expected_relative = expected_outputs[0].resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return False
    return (
        canonical.get("path") == expected_relative
        and canonical.get("sha256") == hashlib.sha256(frozen_bytes).hexdigest()
    )


def _unchanged_serenity_quality_outputs_match(
    stage: Stage, result: dict[str, Any], expected_outputs: list[Path],
) -> bool:
    """Accept an idempotent frozen-week rewrite without pretending it is a fresh observation."""
    if stage.name != "serenity_quality_forward" or len(expected_outputs) != 4:
        return False
    artifact_names = ("observation", "ledger", "quality_gate", "g1_blade6_preflight")
    artifacts = result.get("artifacts")
    result_values = (
        result.get("observation"), result.get("ledger"), result.get("quality_gate"),
        result.get("g1_blade6_preflight"),
    )
    if not isinstance(artifacts, dict) or any(not isinstance(value, str) for value in artifacts.values()):
        return False
    for name, path, value in zip(artifact_names, expected_outputs, result_values):
        if artifacts.get(name) != str(path):
            return False
        if not isinstance(value, dict):
            return False
        try:
            if json.loads(path.read_text(encoding="utf-8")) != value:
                return False
        except (OSError, UnicodeDecodeError, ValueError):
            return False
    return True


def _is_typed_zero_effect_result(result: Any) -> bool:
    if not isinstance(result, dict) or result.get("status") != "invalid_evidence":
        return False
    effects = result.get("effects")
    return (
        isinstance(effects, dict)
        and effects
        and all(value is False for value in effects.values())
        and result.get("validated_theme_count") == 0
        and result.get("boostable_ticker_count") == 0
    )


def _degrade_soft_discovery_boundary(
    stage: Stage, ctx: CapstoneContext, exc: Exception,
) -> dict[str, Any]:
    from runners.us_short_weekly_capstone_soft_discovery import (
        degrade_capstone_boundary_failure,
    )

    try:
        return degrade_capstone_boundary_failure(ctx, exc)
    except Exception:
        unbound = {"path": None, "sha256": None}
        return {
            "schema_name": "us_short_provisional_theme_stage_receipt",
            "schema_version": "1.0.0",
            "generated_at": ctx.generated_at,
            "decision_date": ctx.decision_date,
            "status": "invalid_evidence",
            "reason_code": "SOFT_DISCOVERY_STAGE_EXCEPTION",
            "artifacts": {
                key: dict(unbound)
                for key in ("merge", "merge_manifest", "ingest", "validation")
            },
            "evidence_anchor": {
                "upstream_pair_anchored": False,
                "document_content_anchored": False,
                "upstream_artifacts": {
                    key: dict(unbound)
                    for key in ("web_discovery", "web_receipt", "x_discovery", "x_receipt")
                },
            },
            "immutable_conflict": None,
            "validated_theme_count": 0,
            "boostable_ticker_count": 0,
            "drop_summary": {
                "merge_dropped_theme_count": 0,
                "validation_drop_count": 0,
            },
            "error_summary": {
                "code": "SOFT_DISCOVERY_STAGE_EXCEPTION",
                "error_type": type(exc).__name__,
            },
            "effects": {
                "network_access_performed": False,
                "provider_calls_performed": False,
                "scoring_eligible": False,
                "top15_effect_enabled": False,
                "operation_advice_effect_enabled": False,
                "dynamic_seats_enabled": False,
                "theme_probe_enabled": False,
                "lifecycle_actions_enabled": False,
            },
        }


def _degrade_serenity_quality_boundary(
    stage: Stage, ctx: CapstoneContext, exc: Exception,
) -> dict[str, Any]:
    """Typed local fallback for the optional quality observer; the ordinary week keeps running."""
    return {
        "stage": "serenity_quality_forward",
        "schema_name": "us_short_serenity_quality_forward_observation",
        "schema_version": "1.0.0",
        "generated_at": ctx.generated_at,
        "observed_at": ctx.observed_at,
        "decision_date": ctx.decision_date,
        "status": "invalid_evidence",
        "main_task_should_abort": False,
        "validated_theme_count": 0,
        "boostable_ticker_count": 0,
        "effects": {
            "scoring_eligible": False,
            "top15_effect_enabled": False,
            "operation_advice_effect_enabled": False,
            "provider_calls_performed": False,
            "network_access_performed": False,
            "main_task_should_abort": False,
        },
        "error": {
            "code": "SERENITY_QUALITY_STAGE_EXCEPTION",
            "message": f"{type(exc).__name__}: local quality observation was degraded",
        },
    }


def _degrade_stage_boundary(stage: Stage, ctx: CapstoneContext, exc: Exception) -> dict[str, Any]:
    """Apply the explicitly declared optional-stage failure handler."""
    if not _stage_is_optional(stage) or stage.failure_handler is None:
        raise exc
    try:
        result = stage.failure_handler(stage, ctx, exc)
        if not _is_typed_zero_effect_result(result):
            raise WeeklyCapstoneError(
                f"optional stage '{stage.name}' failure handler returned a non-zero-effect result"
            )
        return result
    except Exception:
        # The handler itself is part of the optional boundary.  Its fallback is
        # still a typed zero-effect result; official output transaction errors
        # remain outside this helper and stay strict.
        return _degrade_soft_discovery_boundary(stage, ctx, exc)


def _provider_execution_receipt(ctx: CapstoneContext, results: list[dict[str, Any]]):
    """Build the A1 receipt from exact completed stages and their provider-call evidence."""
    required_results = tuple(
        item for item in results
        if not item.get("best_effort", False)
        and item.get("name") not in {"model_paper_adapter", "soft_discovery", "serenity_quality_forward"}
    )
    completed = tuple(item.get("name") for item in required_results)
    expected = tuple(
        stage.name for stage in default_pipeline()
        if stage.name not in {
            # Post-bridge and adapter stages: this receipt binds the PRE-bridge
            # provider-relevant sequence, and market_diagnostic runs after the
            # bridge, reads only a local clock, and performs no provider call.
            "weekly_bridge", "model_paper_adapter", "model_paper_weekly", "soft_discovery",
            "serenity_quality_forward",
            # All three diagnostic steps sit after the bridge. The fetch one is
            # gated because it really does call a vendor, but it is not part of
            # the PRE-bridge provider-relevant sequence this receipt binds.
            "market_diagnostic", "market_diagnostic_fetch", "market_diagnostic_settle",
        } and not stage.best_effort
    )
    if completed != expected:
        raise WeeklyCapstoneError("research_live receipt requires the exact completed pre-bridge stage sequence")
    by_name = {item["name"]: item.get("result") for item in required_results}

    def _result(name):
        value = by_name.get(name)
        if not isinstance(value, dict):
            raise WeeklyCapstoneError(f"{name} lacks provider evidence")
        return value

    stage_executions = tuple(
        (
            item["name"],
            item.get("execution_mode", "executed"),
            item.get("stage_generated_at")
            if isinstance(item.get("stage_generated_at"), str)
            else item.get("result", {}).get("generated_at", ctx.generated_at),
            item.get("stage_observed_at")
            if isinstance(item.get("stage_observed_at"), str)
            else item.get("result", {}).get("observed_at", ctx.observed_at),
            hashlib.sha256(json.dumps(
                item.get("result", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")).hexdigest(),
        )
        for item in required_results
    )

    universe = _result("universe_fetch")
    if universe.get("decision_clock", {}).get("decision_date") != ctx.decision_date:
        raise WeeklyCapstoneError("universe provider evidence decision_date mismatch")
    universe_evidence = universe.get("provider_call_evidence", {})
    if universe_evidence.get("network_access_performed") is not True \
            or universe_evidence.get("provider_calls_performed") is not True:
        raise WeeklyCapstoneError("universe fetch lacks explicit provider-call evidence")
    universe_calls = universe_evidence.get("actual_total_calls")

    momentum = _result("momentum_fetch")
    momentum_scope = momentum.get("scope", {})
    if momentum_scope.get("network_access_performed") is not True \
            or momentum_scope.get("provider_calls_performed") is not True \
            or momentum.get("decision_clock", {}).get("expected_decision_date") != ctx.decision_date:
        raise WeeklyCapstoneError("momentum fetch lacks source-bound provider-call evidence")
    momentum_calls = momentum.get("fetch_stats", {}).get("grouped_calls_made")

    sic = _result("sic_fetch")
    sic_scope = sic.get("scope", {})
    sic_evidence = sic.get("provider_call_evidence", {})
    sic_calls = sic_evidence.get("actual_total_calls")
    sic_cache = sic.get("classification", {})
    sic_cache_only = (
        sic_scope.get("network_access_performed") is False
        and sic_scope.get("provider_calls_performed") is False
        and sic_evidence.get("network_access_performed") is False
        and sic_evidence.get("provider_calls_performed") is False
        and sic_calls == 0
        and sic_cache.get("cache_identity") == "immutable_cik_snapshot"
        and type(sic_cache.get("cache_reused_count")) is int
        and sic_cache.get("cache_reused_count") == sic_cache.get("sic_resolved_count")
        and sic_cache.get("sic_resolved_count", 0) > 0
        and sic_cache.get("cache_refreshed_count") == 0
        and sic_cache.get("cache_snapshot_count", 0) > 0
    )
    sic_same_run_provider = (
        sic_scope.get("network_access_performed") is True
        and sic_scope.get("provider_calls_performed") is True
        and sic_evidence.get("network_access_performed") is True
        and sic_evidence.get("provider_calls_performed") is True
        and type(sic_calls) is int and sic_calls > 0
    )
    if not (sic_cache_only or sic_same_run_provider) \
            or sic.get("decision_clock", {}).get("expected_decision_date") != ctx.decision_date:
        raise WeeklyCapstoneError("SIC fetch lacks verified cache provenance or same-run provider-call evidence")

    pass2 = _result("pass2_fetch")
    pass2_scope = pass2.get("scope", {})
    budget = pass2.get("endpoint_call_budget", {})
    endpoint_results = pass2.get("endpoint_results")
    logical_pass2_calls = budget.get("actual_total_endpoint_calls")
    pass2_calls = budget.get("actual_total_http_attempts")
    max_http_attempts = budget.get("max_total_http_attempts")
    retry_count_used = budget.get("retry_count_used")
    if pass2_scope.get("network_access_performed") is not True \
            or pass2_scope.get("provider_calls_performed") is not True \
            or pass2.get("decision_clock", {}).get("expected_decision_date") != ctx.decision_date \
            or type(logical_pass2_calls) is not int or logical_pass2_calls < 1 \
            or type(pass2_calls) is not int or pass2_calls < logical_pass2_calls \
            or type(max_http_attempts) is not int or pass2_calls > max_http_attempts \
            or type(retry_count_used) is not int or retry_count_used < 0 \
            or pass2_calls != logical_pass2_calls + retry_count_used \
            or budget.get("within_budget") is not True \
            or not isinstance(endpoint_results, list) or len(endpoint_results) != logical_pass2_calls \
            or any(not isinstance(row, dict) or not isinstance(row.get("provider_id"), str)
                   or not isinstance(row.get("endpoint_family"), str) or row.get("status") not in {"success", "error"}
                   for row in endpoint_results):
        raise WeeklyCapstoneError("Pass2 lacks complete same-run endpoint-call evidence")

    vix = _result("vix_regime")
    if vix.get("provider") != "financial_modeling_prep" \
            or vix.get("source_endpoint") != "stable/quote" \
            or vix.get("symbol") != "^VIX" \
            or type(vix.get("http_status")) is not int \
            or vix.get("observed_at") != ctx.generated_at:
        raise WeeklyCapstoneError("VIX stage lacks complete same-run provider observation evidence")

    call_counts = (
        ("universe_fetch", universe_calls), ("momentum_fetch", momentum_calls),
        ("sic_fetch", sic_calls), ("pass2_fetch", pass2_calls),
    )
    if any(type(count) is not int or count < (0 if name == "sic_fetch" and sic_cache_only else 1)
           for name, count in call_counts):
        raise WeeklyCapstoneError("every required provider stage must prove at least one call")
    evidence = {
        name: {
            "call_count": dict(call_counts).get(name, 0),
            "summary_sha256": hashlib.sha256(
                json.dumps(by_name[name], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
        for name in (*dict(call_counts), "yfinance_grades_fetch", "vix_regime")
    }
    evidence_sha256 = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    source_path = ctx.source_packet_path.resolve()
    source_sha256 = _sha256_file(source_path)
    source_manifest = source_packet_runner.source_packet_input_manifest(source_path)
    action_template_path = ctx.batch4_template_path.resolve()
    if not action_template_path.is_file():
        raise WeeklyCapstoneError("mixed-source receipt requires an existing Batch4 action template")
    action_input_manifest = (("batch4_action_template", str(action_template_path), _sha256_file(action_template_path)),)
    source_manifest_sha256 = hashlib.sha256(
        json.dumps(source_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    provider_summary_digests = tuple(
        (name, evidence[name]["summary_sha256"])
        for name in (*dict(call_counts), "yfinance_grades_fetch", "vix_regime")
    )
    from runners import us_short_weekly_capstone_stages as stage_adapters
    health_stage_results = {
        name: _result(name)
        for name in ("universe_fetch", "momentum_fetch", "sic_fetch", "pass2_fetch", "yfinance_grades_fetch", "vix_regime")
    }
    provider_health = stage_adapters.derive_capstone_provider_health(health_stage_results)
    provider_health_facts = tuple(provider_health.items())
    run_id = hashlib.sha256(
        f"{ctx.decision_date}|{ctx.generated_at}|{source_path}|{source_sha256}|"
        f"{source_manifest_sha256}|{action_input_manifest[0][2]}|{evidence_sha256}|{stage_executions}".encode("utf-8")
    ).hexdigest()
    return _issue_capstone_research_live_receipt(
        run_id=run_id,
        decision_date=ctx.decision_date,
        generated_at=ctx.generated_at,
        completed_stages=completed,
        source_packet_path=source_path,
        source_packet_sha256=source_sha256,
        source_artifact_manifest=source_manifest,
        action_input_manifest=action_input_manifest,
        provider_call_counts=call_counts,
        provider_summary_digests=provider_summary_digests,
        provider_health_facts=provider_health_facts,
        provider_evidence_sha256=evidence_sha256,
        stage_executions=stage_executions,
    )


@dataclass(frozen=True)
class _DecisionDateLock:
    path: Path
    handle: Any


def _decision_lock_path(ctx: CapstoneContext) -> Path:
    # One lock per decision date and artifact state root. Production callers share the canonical state root,
    # while tests and isolated replays inject their own root and must not contend through repository-global state.
    return (
        ctx.state_dir / "_transaction_locks" / f"{ctx.decision_date}.lock"
    ).resolve()


def _acquire_decision_lock(ctx: CapstoneContext) -> _DecisionDateLock:
    """Take a kernel-owned non-blocking lock; the OS releases it automatically after crash/process exit."""
    path = _decision_lock_path(ctx)
    reject_nonprivate_output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise WeeklyCapstoneError(
            f"another capstone process already owns decision_date {ctx.decision_date}"
        ) from exc
    return _DecisionDateLock(path=path, handle=handle)


def _release_decision_lock(lock: _DecisionDateLock) -> None:
    handle = lock.handle
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
        object.__setattr__(lock, "handle", None)


@dataclass(frozen=True)
class _CurrentOutputTransaction:
    tag: str
    journal_path: Path
    staging_root: Path
    archived_paths: tuple[Path, ...]
    context: CapstoneContext
    decision_lock: _DecisionDateLock


def _transaction_paths(ctx: CapstoneContext, tag: str, surface: str) -> tuple[Path, Path, Path]:
    current = (ctx.private_root / surface / ctx.decision_date).resolve()
    history = (ctx.private_root / surface / "_superseded" / f"{ctx.decision_date}__{tag}").resolve()
    staging_root = (ctx.private_root / "weekly_private" / "_transactions" / tag).resolve()
    staged = staging_root / surface / ctx.decision_date
    return current, history, staged


def _transaction_journal_path(ctx: CapstoneContext) -> Path:
    return (ctx.private_root / "weekly_private" / "_transaction_state" / f"{ctx.decision_date}.json").resolve()


def _write_transaction_journal(path: Path, *, tag: str, phase: str) -> None:
    reject_nonprivate_output_path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    reject_nonprivate_output_path(tmp)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps({"version": 1, "tag": tag, "phase": phase}, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_transaction_journal(path: Path) -> dict[str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WeeklyCapstoneError("cannot recover malformed current-output transaction journal") from exc
    if not isinstance(value, dict) or set(value) != {"version", "tag", "phase"} or value.get("version") != 1:
        raise WeeklyCapstoneError("invalid current-output transaction journal shape")
    tag, phase = value.get("tag"), value.get("phase")
    if not isinstance(tag, str) or _safe_tag(tag) != tag or not isinstance(phase, str):
        raise WeeklyCapstoneError("invalid current-output transaction journal values")
    return {"tag": tag, "phase": phase}


def _recover_current_output_transaction(ctx: CapstoneContext) -> None:
    journal = _transaction_journal_path(ctx)
    if not journal.exists():
        return
    state = _read_transaction_journal(journal)
    tag, phase = state["tag"], state["phase"]
    paths = [_transaction_paths(ctx, tag, surface) for surface in ("weekly_private", "runs_private")]
    try:
        if phase in {"archiving_prior", "archive_recovery_required"}:
            for current, history, _ in reversed(paths):
                if history.exists():
                    if current.exists():
                        raise WeeklyCapstoneError("archive recovery found both current and history copies")
                    current.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(history), str(current))
        elif phase in {"running", "publishing", "publish_recovery_required"}:
            # The previous run never committed. Remove any partially published current outputs via staging, then
            # discard staging. Prior outputs remain safely under _superseded.
            for current, _, staged in reversed(paths):
                if current.exists():
                    if staged.exists():
                        raise WeeklyCapstoneError("publish recovery found both current and staged copies")
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(current), str(staged))
        elif phase == "published":
            if any(not current.exists() for current, _, _ in paths):
                raise WeeklyCapstoneError("published transaction is missing an official current surface")
        else:
            raise WeeklyCapstoneError(f"unknown current-output transaction phase {phase!r}")
        staging_root = paths[0][2].parents[1]
        if staging_root.exists():
            shutil.rmtree(staging_root)
        journal.unlink(missing_ok=True)
    except Exception as exc:
        raise WeeklyCapstoneError(f"current-output transaction recovery failed in phase {phase}") from exc


def _begin_current_output_transaction(ctx: CapstoneContext) -> _CurrentOutputTransaction:
    decision_lock = _acquire_decision_lock(ctx)
    try:
        return _begin_current_output_transaction_locked(ctx, decision_lock)
    except Exception:
        _release_decision_lock(decision_lock)
        raise


def _begin_current_output_transaction_locked(
    ctx: CapstoneContext, decision_lock: _DecisionDateLock,
) -> _CurrentOutputTransaction:
    _recover_current_output_transaction(ctx)
    tag = _safe_tag(ctx.generated_at)
    while any(_transaction_paths(ctx, tag, surface)[1].exists()
              for surface in ("weekly_private", "runs_private")):
        tag += "_x"
    journal = _transaction_journal_path(ctx)
    _write_transaction_journal(journal, tag=tag, phase="archiving_prior")
    moved: list[tuple[Path, Path]] = []
    try:
        for surface in ("weekly_private", "runs_private"):
            current, history, _ = _transaction_paths(ctx, tag, surface)
            if not current.exists():
                continue
            reject_nonprivate_output_path(current)
            reject_nonprivate_output_path(history)
            history.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current), str(history))
            moved.append((current, history))
    except Exception as primary:
        rollback_errors = []
        for current, history in reversed(moved):
            try:
                current.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(history), str(current))
            except Exception as rollback:
                rollback_errors.append(rollback)
        if rollback_errors:
            journal_errors = []
            try:
                _write_transaction_journal(journal, tag=tag, phase="archive_recovery_required")
            except Exception as journal_error:
                journal_errors.append(journal_error)
            causes = ExceptionGroup(
                "pre-run archive primary, rollback, and recovery-journal failures",
                [primary, *rollback_errors, *journal_errors],
            )
            recovery_state = "recovery journal retained" if not journal_errors else "recovery journal write also failed"
            raise WeeklyCapstoneError(
                f"pre-run archive failed and rollback also failed ({len(rollback_errors)} error(s)); {recovery_state}"
            ) from causes
        journal.unlink(missing_ok=True)
        raise WeeklyCapstoneError("pre-run archive failed before any provider stage; prior current outputs restored") from primary
    _write_transaction_journal(journal, tag=tag, phase="running")
    staging_root = _transaction_paths(ctx, tag, "weekly_private")[2].parents[1]
    return _CurrentOutputTransaction(
        tag=tag,
        journal_path=journal,
        staging_root=staging_root,
        archived_paths=tuple(history for _, history in moved),
        context=ctx,
        decision_lock=decision_lock,
    )


def _abort_current_output_transaction(txn: _CurrentOutputTransaction) -> None:
    try:
        if txn.staging_root.exists():
            shutil.rmtree(txn.staging_root)
        if txn.archived_paths:
            # Reuse the existing journal-driven recovery primitive immediately so an aborted run never leaves the
            # canonical prior week absent. If recovery itself fails, its journal remains as the next-startup guard.
            _write_transaction_journal(txn.journal_path, tag=txn.tag, phase="archiving_prior")
            _recover_current_output_transaction(txn.context)
        else:
            txn.journal_path.unlink(missing_ok=True)
    finally:
        _release_decision_lock(txn.decision_lock)


def _publish_current_output_transaction(ctx: CapstoneContext, txn: _CurrentOutputTransaction) -> None:
    paths = [_transaction_paths(ctx, txn.tag, surface) for surface in ("runs_private", "weekly_private")]
    for current, _, staged in paths:
        reject_nonprivate_output_path(current)
        reject_nonprivate_output_path(staged)
        if current.exists() or not staged.exists():
            raise WeeklyCapstoneError("cannot publish official outputs: current must be empty and staging complete")
    _write_transaction_journal(txn.journal_path, tag=txn.tag, phase="publishing")
    published: list[tuple[Path, Path]] = []
    try:
        for current, _, staged in paths:  # machine first, report/action surface last
            current.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staged), str(current))
            published.append((current, staged))
        # The current surfaces are committed only when the published marker is durable. Marker failure is part of
        # the publish transaction and rolls every moved surface back to staging.
        _write_transaction_journal(txn.journal_path, tag=txn.tag, phase="published")
    except Exception as primary:
        rollback_errors = []
        for current, staged in reversed(published):
            try:
                staged.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(current), str(staged))
            except Exception as rollback:
                rollback_errors.append(rollback)
        if rollback_errors:
            journal_errors = []
            try:
                _write_transaction_journal(txn.journal_path, tag=txn.tag, phase="publish_recovery_required")
            except Exception as journal_error:
                journal_errors.append(journal_error)
            causes = ExceptionGroup(
                "official-output publish primary, rollback, and recovery-journal failures",
                [primary, *rollback_errors, *journal_errors],
            )
            recovery_state = "recovery journal retained" if not journal_errors else "recovery journal write also failed"
            raise WeeklyCapstoneError(
                f"official-output publish failed and rollback also failed ({len(rollback_errors)} error(s)); {recovery_state}"
            ) from causes
        _abort_current_output_transaction(txn)
        raise WeeklyCapstoneError("official-output publish failed; current remains empty") from primary
    try:
        if txn.staging_root.exists():
            shutil.rmtree(txn.staging_root)
        txn.journal_path.unlink(missing_ok=True)
    except OSError:
        # The durable published marker is the commit point. Cleanup is recoverable on the next locked startup and
        # must not turn a committed run into a reported failure while its complete current surfaces are visible.
        pass
    finally:
        _release_decision_lock(txn.decision_lock)


def _run_pass2_budget_preview(ctx: CapstoneContext, pipeline: list[Stage]) -> dict[str, Any]:
    """Run only the real upstream funnel through local Pass2 preflight and return its exact call forecast.

    This deliberately creates neither a checkpoint nor an official-output transaction and never invokes yfinance,
    Pass2, VIX, or the weekly bridge.  The resulting forecast remains non-authorizing: it must be supplied again as
    an independently approved exact budget to the normal full run.
    """
    _validate_stage_lifecycle(pipeline)
    results: list[dict[str, Any]] = []
    for stage in pipeline:
        try:
            input_paths = [Path(p) for p in stage.inputs(ctx)]
        except Exception as exc:  # noqa: BLE001 - optional lifecycle boundary
            if not _stage_is_optional(stage):
                raise WeeklyCapstoneError(f"stage '{stage.name}' input enumeration failed: {type(exc).__name__}: {exc}") from exc
            input_paths = []
            result = _degrade_stage_boundary(stage, ctx, exc)
            soft_degraded = True
        else:
            soft_degraded = False
        unreadable_inputs = [path for path in input_paths if not _input_readable(path)]
        if unreadable_inputs:
            unreadable = WeeklyCapstoneError(
                f"stage '{stage.name}' cannot start: declared input(s) missing or unreadable this run: "
                f"{[_rel(p) for p in unreadable_inputs]}"
            )
            if not _stage_is_optional(stage):
                raise unreadable
            input_paths = []
            result = _degrade_stage_boundary(stage, ctx, unreadable)
            soft_degraded = True
        try:
            expected_outputs = [Path(p) for p in stage.outputs(ctx)]
        except Exception as exc:  # noqa: BLE001 - optional lifecycle boundary
            if not _stage_is_optional(stage):
                raise WeeklyCapstoneError(f"stage '{stage.name}' output enumeration failed: {type(exc).__name__}: {exc}") from exc
            expected_outputs = []
            result = _degrade_stage_boundary(stage, ctx, exc)
            soft_degraded = True
        before = {str(path.resolve()): _output_fingerprint(path) for path in expected_outputs}
        if not soft_degraded:
            try:
                result = stage.run(ctx)
            except Exception as exc:  # noqa: BLE001 - optional lifecycle boundary
                if not _stage_is_optional(stage):
                    raise WeeklyCapstoneError(f"stage '{stage.name}' failed: {type(exc).__name__}: {exc}") from exc
                result = _degrade_stage_boundary(stage, ctx, exc)
                soft_degraded = True
        if not isinstance(result, dict):
            if not _stage_is_optional(stage):
                raise WeeklyCapstoneError(f"stage '{stage.name}' returned a non-object result")
            result = _degrade_stage_boundary(
                stage, ctx, WeeklyCapstoneError(f"stage '{stage.name}' returned a non-object result"),
            )
            soft_degraded = True
        missing = [
            path for path in expected_outputs
            if _output_fingerprint(path) is None
            or _output_fingerprint(path) == before[str(path.resolve())]
        ]
        if soft_degraded:
            missing = []
        elif missing == expected_outputs and _unchanged_soft_discovery_receipt_matches(
            stage, result, expected_outputs,
        ):
            missing = []
        elif missing == expected_outputs and _unchanged_serenity_quality_outputs_match(
            stage, result, expected_outputs,
        ):
            missing = []
        elif missing and _stage_is_optional(stage):
            if not _is_typed_zero_effect_result(result):
                result = _degrade_stage_boundary(
                    stage, ctx, WeeklyCapstoneError("optional stage did not produce a fresh output"),
                )
            soft_degraded = True
            missing = []
        if missing:
            raise WeeklyCapstoneError(
                f"stage '{stage.name}' completed but did not produce a fresh output this run: {[_rel(p) for p in missing]}"
            )
        generated = result.get("generated_at") if isinstance(result, dict) else None
        decision_clock = result.get("decision_clock") if isinstance(result, dict) else None
        observed = result.get("observed_at") if isinstance(result, dict) else None
        if not isinstance(observed, str) and isinstance(decision_clock, dict):
            observed = decision_clock.get("observed_at")
        results.append({
            "name": stage.name,
            "gated": stage.gated,
            "best_effort": False,
            "execution_mode": "executed_budget_preview",
            "stage_generated_at": generated if isinstance(generated, str) else ctx.generated_at,
            "stage_observed_at": observed if isinstance(observed, str) else ctx.observed_at,
            "result": result,
        })

    preflight = results[-1]["result"] if results else None
    try:
        forecast = preflight["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"]
        target_count = preflight["pass2_target_universe"]["target_count"]
        gate = preflight["execution_gate"]
    except (KeyError, TypeError) as exc:
        raise WeeklyCapstoneError("pass2_preflight budget preview returned an incomplete forecast contract") from exc
    if type(forecast) is not int or isinstance(forecast, bool) or forecast < 1:
        raise WeeklyCapstoneError("pass2_preflight budget preview returned a non-positive exact call forecast")
    if type(target_count) is not int or isinstance(target_count, bool) or target_count < 1:
        raise WeeklyCapstoneError("pass2_preflight budget preview returned an invalid Pass2 target count")
    if (
        not isinstance(gate, dict)
        or gate.get("ready_to_run_full_candidate_live_packet") is not False
        or "pass2_call_budget_not_yet_authorized" not in gate.get("block_reasons", [])
    ):
        raise WeeklyCapstoneError(
            "pass2_preflight budget preview must remain explicitly blocked until the exact call budget is independently authorized"
        )
    stage_outcomes = [
        {
            "stage": item["name"],
            "execution_mode": item["execution_mode"],
            **_normalize_stage_outcome(item["name"], item["result"]),
        }
        for item in results
    ]
    return {
        "mode": "pass2_budget_preview",
        "execution_mode": "live_preflight_provider_fetch",
        "operational_use": "not_authorized",
        "decision_date": ctx.decision_date,
        "price_basis_date": ctx.price_basis_date,
        "account_lineage": copy.deepcopy(ctx.account_lineage_status),
        "pass2_call_budget": forecast,
        "pass2_target_count": target_count,
        "next_required": (
            "independently authorize this exact budget, then rerun the full capstone with "
            f"--pass2-call-budget {forecast}"
        ),
        "stages": results,
        "stage_outcomes": stage_outcomes,
        "stage_outcome_counts": _stage_outcome_counts(stage_outcomes),
    }


def run_weekly_capstone(
    *,
    now_et: datetime,
    private_root: Path,
    batch4_template_path: Path,
    account_state_path: Path,
    account_lineage_path: Path | None = None,
    authorized_momentum_top_k: int = 200,
    authorized_pass2_call_budget: int | None = None,
    catalyst_recall_tickers: tuple[str, ...] = (),
    calendar_path: Path = CALENDAR_PRESET,
    confirm_user_authorization: bool = False,
    dry_run: bool = True,
    provider_pace_seconds: float = 0.0,
    max_retries_per_call: int | None = None,
    retry_backoff_seconds: float | None = None,
    max_total_http_attempts: int | None = None,
    stages: list[Stage] | None = None,
    state_dir: Path = STATE_DIR,
    sample_root: Path = ROOT,
    resume_from: Path | None = None,
    prepare_pass2_budget: bool = False,
    auto_authorize_pass2_budget: bool = False,
    model_paper_store_root: Path | None = None,
    model_paper_run_account_mode: str | None = None,
    soft_discovery_enabled: bool = True,
    theme_soft_boost_enabled: bool = True,
    serenity_annotation_payload: dict[str, Any] | None = None,
    diagnostic_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Orchestrate the weekly one-click path. `dry_run=True` (default) resolves the canonical dates and returns the
    full plan WITHOUT any fetch. A live run (`dry_run=False`) is authorized by the explicit live/budget command, then
    runs each stage in order, validating each stage's declared inputs are readable
    before it starts and its declared outputs exist after, aborting fast (with the stage name) on the first failure.
    `stages` is injectable for offline testing."""
    max_retries_per_call, retry_backoff_seconds = _normalize_capstone_retry_policy(
        max_retries_per_call,
        retry_backoff_seconds,
        auto_authorize_pass2_budget=auto_authorize_pass2_budget,
    )
    if (
        max_total_http_attempts is not None
        and (
            type(max_total_http_attempts) is not int
            or isinstance(max_total_http_attempts, bool)
            or max_total_http_attempts < 1
        )
    ):
        raise WeeklyCapstoneError(
            "max_total_http_attempts must be a positive exact int"
        )
    if max_retries_per_call and max_total_http_attempts is None and not auto_authorize_pass2_budget:
        raise WeeklyCapstoneError(
            "max_total_http_attempts must be explicit whenever live 429 retries are enabled"
        )
    if auto_authorize_pass2_budget and dry_run:
        raise WeeklyCapstoneError("auto Pass2 budget authorization is available only for an executing default run")
    if auto_authorize_pass2_budget and prepare_pass2_budget:
        raise WeeklyCapstoneError("auto Pass2 budget authorization cannot be combined with --prepare-pass2-budget")
    if auto_authorize_pass2_budget and stages is not None:
        raise WeeklyCapstoneError("auto Pass2 budget authorization is available only on the default pipeline")
    if auto_authorize_pass2_budget and authorized_pass2_call_budget is not None:
        raise WeeklyCapstoneError("auto Pass2 budget authorization must derive the budget; do not supply one")
    if auto_authorize_pass2_budget and resume_from is not None:
        raise WeeklyCapstoneError("auto Pass2 budget authorization cannot resume a pre-budget checkpoint")
    ctx = resolve_capstone_context(
        now_et=now_et, private_root=private_root, batch4_template_path=batch4_template_path,
        account_state_path=account_state_path, calendar_path=calendar_path,
        authorized_momentum_top_k=authorized_momentum_top_k,
        authorized_pass2_call_budget=authorized_pass2_call_budget,
        pass2_budget_preview=prepare_pass2_budget or auto_authorize_pass2_budget,
        catalyst_recall_tickers=catalyst_recall_tickers,
        confirm_user_authorization=confirm_user_authorization, provider_pace_seconds=provider_pace_seconds,
        max_retries_per_call=max_retries_per_call, retry_backoff_seconds=retry_backoff_seconds,
        max_total_http_attempts=max_total_http_attempts, state_dir=state_dir,
        model_paper_store_root=model_paper_store_root,
        model_paper_run_account_mode=model_paper_run_account_mode,
        soft_discovery_enabled=soft_discovery_enabled,
        theme_soft_boost_enabled=theme_soft_boost_enabled,
        sample_root=sample_root,
    )
    if serenity_annotation_payload is not None:
        ctx = replace(ctx, serenity_annotation_payload=dict(serenity_annotation_payload))
    try:
        canonical_recall = canonicalize_catalyst_recall_tickers(catalyst_recall_tickers)
    except FullCandidatePass2PreflightError as exc:
        raise WeeklyCapstoneError(str(exc)) from None
    try:
        provider_pace_seconds = validate_provider_pace_seconds(provider_pace_seconds)
    except ValueError as exc:
        raise WeeklyCapstoneError(str(exc)) from None
    ctx = replace(ctx, catalyst_recall_tickers=canonical_recall, provider_pace_seconds=provider_pace_seconds)
    if prepare_pass2_budget and dry_run:
        raise WeeklyCapstoneError(
            "--prepare-pass2-budget executes the upstream live preflight; use the ordinary dry-run to inspect its plan"
        )
    if prepare_pass2_budget and stages is not None:
        raise WeeklyCapstoneError("--prepare-pass2-budget is available only on the real default capstone pipeline")
    full_pipeline = stages if stages is not None else default_pipeline(
        include_model_paper=_model_paper_enabled(ctx),
        include_soft_discovery=ctx.soft_discovery_enabled,
    )
    pipeline = full_pipeline
    if prepare_pass2_budget:
        preflight_indexes = [i for i, stage in enumerate(full_pipeline) if stage.name == "pass2_preflight"]
        if len(preflight_indexes) != 1:
            raise WeeklyCapstoneError("default capstone pipeline must contain exactly one pass2_preflight")
        pipeline = full_pipeline[:preflight_indexes[0] + 1]
    _validate_stage_lifecycle(pipeline)
    if any(stage.best_effort and stage.name not in {
        "forward_policy_shadow", "forward_policy_corporate_actions", "forward_policy_maturity",
        "soft_boost_comparison_maturity",
        "soft_boost_comparison_capture",
    } for stage in pipeline):
        raise WeeklyCapstoneError("only comparison-capture stages may be best_effort")
    if any(stage.reuse_policy not in {"never", "frozen_inputs", "refresh_then_reuse_if_equivalent"}
           for stage in pipeline):
        raise WeeklyCapstoneError("capstone stage has an unknown checkpoint reuse policy")

    # C3 footgun guard: reject an operator input colocated under the per-decision output dir a live run archives,
    # before any fetch (dry-run too, so the plan preview catches it). See _assert_input_outside_archived_outputs.
    for _input_path, _input_label in ((ctx.account_state_path, "--account-state-path"),
                                      (ctx.batch4_template_path, "--batch4-template-path")):
        _assert_input_outside_archived_outputs(ctx, Path(_input_path), _input_label)

    if dry_run:
        if stages is None:
            calendar = load_market_calendar(calendar_path)
            ctx = replace(
                ctx,
                live_provider_preflight=inspect_live_provider_clock(
                    requested_now_et=ctx.now_et,
                    calendar=calendar,
                ),
            )
        return _plan(ctx, pipeline, resume_from=resume_from)

    if _model_paper_enabled(ctx):
        try:
            from engine.us_short_model_paper_activation import resolve_model_paper_activation

            activation = resolve_model_paper_activation()
        except Exception as exc:  # noqa: BLE001 - activation is a fail-closed boundary
            raise WeeklyCapstoneError(
                f"activation_gate_broken: {type(exc).__name__}"
            ) from None
        if not isinstance(activation, dict) or activation.get("status") not in {"dormant", "authorized"}:
            raise WeeklyCapstoneError("activation_gate_broken: model-paper activation result is invalid")
        if activation["status"] == "dormant":
            return _dormant_model_paper_summary(ctx)

    if stages is None:
        ctx = prepare_live_provider_context(
            ctx, calendar_path=calendar_path, requested_now_et=now_et,
        )
        _emit_diagnostic_event(
            diagnostic_event,
            "capstone_context_resolved",
            decision_date=ctx.decision_date,
            price_basis_date=ctx.price_basis_date,
        )
    else:
        _emit_diagnostic_event(
            diagnostic_event,
            "capstone_context_resolved",
            decision_date=ctx.decision_date,
            price_basis_date=ctx.price_basis_date,
        )

    if not ctx.confirm_user_authorization:
        raise WeeklyCapstoneError(
            "a live weekly run performs gated provider fetches (universe / momentum / SIC / Pass2 / VIX) and requires "
            "explicit per-execution authorization (confirm_user_authorization=True); re-run with --dry-run to review "
            "the plan first"
        )
    production_run = (stages is None) and (ctx.confirm_user_authorization is True) and not prepare_pass2_budget
    auto_budget_run = auto_authorize_pass2_budget and production_run
    budget_preview_run = (stages is None) and (ctx.confirm_user_authorization is True) and prepare_pass2_budget
    if resume_from is not None and not production_run:
        raise WeeklyCapstoneError("--resume is available only on the real default capstone pipeline")
    k_is_valid = (
        type(ctx.authorized_momentum_top_k) is int
        and not isinstance(ctx.authorized_momentum_top_k, bool)
        and 1 <= ctx.authorized_momentum_top_k <= 250
    )
    budget_is_valid = (
        type(ctx.authorized_pass2_call_budget) is int
        and not isinstance(ctx.authorized_pass2_call_budget, bool)
        and ctx.authorized_pass2_call_budget >= 1
    )
    if production_run and (not k_is_valid or (not budget_is_valid and not auto_budget_run)):
        raise WeeklyCapstoneError(
            "live default pipeline requires momentum_top_k (1..250) and a positive exact Pass2 call budget; "
            "first run --prepare-pass2-budget with the same K to derive the forecast, then re-run with "
            "--pass2-call-budget N"
        )
    if budget_preview_run and (not k_is_valid or ctx.authorized_pass2_call_budget is not None):
        raise WeeklyCapstoneError(
            "--prepare-pass2-budget requires momentum_top_k (1..250) and no Pass2 call budget; "
            "it derives the exact execution budget"
        )
    if production_run:
        from runners import us_short_batch5_to_batch4_weekend_e2e as batch4_bridge

        try:
            batch4_bridge.load_batch4_action_template(ctx.batch4_template_path)
        except Exception as exc:  # noqa: BLE001 - convert only the safe bridge error text
            raise WeeklyCapstoneError(f"batch4 template preflight rejected: {exc}") from None
    # Prove every private leaf after operator/budget validation, but before any pre-stage settlement,
    # checkpoint, transaction, or provider stage.
    _preflight_private_output_paths(ctx)
    if not prepare_pass2_budget and any(stage.name == "serenity_quality_forward" for stage in pipeline):
        from engine import us_short_serenity_quality_forward as serenity_quality

        try:
            settlement = serenity_quality.settle_pending_review(
                ledger_path=ctx.serenity_quality_ledger_path,
                current_decision_date=ctx.decision_date,
                observed_at=ctx.observed_at,
                state_dir=ctx.state_dir,
                root=ctx.sample_root,
                now=datetime.fromisoformat(ctx.observed_at),
                g1_decision_path=ctx.serenity_g1_decision_path,
                g1_preflight_path=ctx.serenity_g1_blade6_preflight_path,
            )
        except serenity_quality.SerenityQualityForwardError as exc:
            # This pre-stage settlement is outside the normal optional-stage boundary.  A stale/legacy local
            # ledger is invalid quality evidence, never a reason to abort the ordinary zero-effect weekly task.
            settlement = serenity_quality.ledger_rejected_settlement(exc)
        ctx = replace(ctx, serenity_settlement_result=dict(settlement))
    if (production_run or budget_preview_run) and not _model_paper_enabled(ctx):
        from runners.us_short_account_state_from_manual_tables import (
            ConvertError,
            validate_account_lineage,
            validate_account_state,
        )

        lineage_path = (
            Path(account_lineage_path)
            if account_lineage_path is not None
            else ctx.account_state_path.with_name(ctx.account_state_path.stem + "_lineage.json")
        )
        try:
            account_state = json.loads(ctx.account_state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WeeklyCapstoneError(
                f"cannot read --account-state-path {ctx.account_state_path}: {type(exc).__name__}"
            ) from None
        try:
            lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WeeklyCapstoneError(
                f"cannot read --account-lineage-path {lineage_path}: {type(exc).__name__}"
            ) from None
        try:
            validate_account_state(account_state, ctx.decision_date)
        except ConvertError as exc:
            raise WeeklyCapstoneError(
                f"invalid --account-state-path {ctx.account_state_path}: {exc}"
            ) from None
        try:
            validate_account_lineage(lineage, account_state, ctx.decision_date, ctx.price_basis_date)
        except ConvertError as exc:
            raise WeeklyCapstoneError(
                f"invalid --account-lineage-path {lineage_path}: {exc}"
            ) from None
        ctx = replace(
            ctx,
            frozen_holding_tickers=tuple(sorted(position["ticker"] for position in account_state["positions"])),
            account_lineage_status={
                "facts_as_of": lineage["facts_as_of"],
                "facts_staleness": lineage["facts_staleness"],
            },
        )
    if budget_preview_run:
        return _run_pass2_budget_preview(ctx, pipeline)
    resume_manifest = None
    resume_manifest_path = None
    if resume_from is not None:
        resume_manifest_path = Path(resume_from).resolve()
        try:
            resume_manifest = checkpoint_store.load_manifest(resume_manifest_path)
            checkpoint_store.validate_resume_header(
                resume_manifest,
                decision_date=ctx.decision_date,
                price_basis_date=ctx.price_basis_date,
                run_contract=_checkpoint_run_contract(ctx),
                stages=pipeline,
            )
        except checkpoint_store.CapstoneCheckpointError as exc:
            raise WeeklyCapstoneError(f"resume checkpoint rejected: {exc}") from exc
    checkpoint_manifest_path = None
    checkpoint_manifest = None
    # The checkpoint schema binds the exact Pass2 budget at creation time.
    # Auto-budget mode learns that integer at pass2_preflight, so it runs
    # without a resumable checkpoint; the ordinary manually budget-authorized
    # production path keeps the checkpoint unchanged.
    if production_run and not auto_budget_run:
        try:
            checkpoint_manifest_path, checkpoint_manifest = checkpoint_store.create_manifest(
                private_root=ctx.private_root,
                decision_date=ctx.decision_date,
                price_basis_date=ctx.price_basis_date,
                generated_at=ctx.generated_at,
                run_contract=_checkpoint_run_contract(ctx),
                stages=pipeline,
            )
        except checkpoint_store.CapstoneCheckpointError as exc:
            raise WeeklyCapstoneError(f"cannot initialize capstone checkpoint: {exc}") from exc
        print(f"[US-SHORT CHECKPOINT] {checkpoint_manifest_path}", file=sys.stderr)

    # C3: archive any prior current outputs BEFORE provider execution. A failure here rolls back before this run
    # starts; once it succeeds, every later no-emit/failure has an empty current slot. Official outputs are written
    # under a private run-scoped staging root and published only after all three siblings validate.
    transaction = _begin_current_output_transaction(ctx)
    ctx = replace(ctx, decision_lock=transaction.decision_lock)
    results: list[dict[str, Any]] = []
    stage_outcomes: list[dict[str, str]] = []

    def stage_clocks(result: dict[str, Any], *, fallback_generated_at: str) -> tuple[str, str | None]:
        generated = result.get("generated_at") if isinstance(result.get("generated_at"), str) else fallback_generated_at
        decision_clock = result.get("decision_clock") if isinstance(result.get("decision_clock"), dict) else {}
        observed = result.get("observed_at") if isinstance(result.get("observed_at"), str) else decision_clock.get("observed_at")
        return generated, observed if isinstance(observed, str) else generated

    def append_stage_result(
        stage: Stage, result: dict[str, Any], *, execution_mode: str,
        stage_generated_at: str, stage_observed_at: str | None,
    ) -> None:
        results.append({
            "name": stage.name,
            "gated": stage.gated,
            "best_effort": stage.best_effort,
            "execution_mode": execution_mode,
            "stage_generated_at": stage_generated_at,
            "stage_observed_at": stage_observed_at,
            "result": result,
        })

    def record_stage_terminal(
        stage: Stage,
        result: dict[str, Any],
        *,
        execution_mode: str,
        stage_generated_at: str,
        stage_observed_at: str | None,
        failure_kind: str | None = None,
    ) -> None:
        append_stage_result(
            stage, result, execution_mode=execution_mode,
            stage_generated_at=stage_generated_at, stage_observed_at=stage_observed_at,
        )
        normalized = _normalize_stage_outcome(stage.name, result, failure_kind=failure_kind)
        outcome = {
            "stage": stage.name,
            "execution_mode": execution_mode,
            **normalized,
        }
        stage_outcomes.append(outcome)
        event = {
            "stage": stage.name,
            "execution_mode": execution_mode,
            **normalized,
        }
        if failure_kind is not None:
            event["failure_kind"] = failure_kind
            event["error_type"] = result.get("error_type")
        _emit_diagnostic_event(
            diagnostic_event,
            _STAGE_OUTCOME_EVENT_NAMES[normalized["outcome_class"]],
            **event,
        )

    def pass2_soft_boost_result(result: dict[str, Any]) -> dict[str, Any] | None:
        source_packet = result.get("source_packet")
        value = source_packet.get("soft_boost") if type(source_packet) is dict else None
        return dict(value) if type(value) is dict else None

    def record_nonblocking_failure(stage: Stage, exc: Exception, *, failure_kind: str) -> None:
        result = {"failure_kind": failure_kind, "error_type": type(exc).__name__}
        print(
            f"[US-SHORT STAGE FAILED] stage={stage.name} failure_kind={failure_kind} "
            f"error_type={type(exc).__name__}",
            file=sys.stderr,
        )
        record_stage_terminal(
            stage, result, execution_mode="executed",
            stage_generated_at=ctx.generated_at, stage_observed_at=ctx.observed_at,
            failure_kind=failure_kind,
        )

    try:
        for stage in pipeline:
            stage_ctx = ctx
            if stage.name == "forward_policy_corporate_actions" and production_run:
                from runners.us_short_forward_policy_corporate_action_fetch import _issue_weekly_capstone_capability

                stage_ctx = replace(
                    ctx,
                    corporate_action_live_capability=_issue_weekly_capstone_capability(
                        decision_date=ctx.decision_date,
                        generated_at=ctx.generated_at,
                        sample_root=ctx.sample_root,
                        private_root=ctx.forward_policy_comparison_ledger_path.parent,
                    ),
                )
            if stage.name in _OFFICIAL_ARTIFACT_STAGES:
                # These stages operate on this transaction's unpublished official
                # artifacts.  Only the bridge consumes the provider receipt;
                # model-paper terminal merely reads the bridge outputs, and the
                # diagnostic stages annotate the report's registered section.
                receipt = _provider_execution_receipt(ctx, results) if production_run and stage.name == "weekly_bridge" else None
                stage_ctx = replace(
                    ctx,
                    research_live_capability=receipt,
                    official_output_root=transaction.staging_root,
                )
            _emit_diagnostic_event(
                diagnostic_event,
                "stage_started",
                stage=stage.name,
                gated=stage.gated,
                best_effort=stage.best_effort,
            )
            # Pre-stage input gate: a stage's declared inputs (prior stages' outputs, or pre-existing external files)
            # must be readable BEFORE it starts — else fail fast with the stage name instead of letting the stage crash
            # deeper on a stale/missing/cross-run input. Existence+readability only; each runner still owns its own
            # schema/date/identity/digest checks. Empty input lists (e.g. universe_fetch, vix_regime) pass trivially.
            # A best_effort (shadow) stage routes an unreadable input through the SAME shadow-capture-failure path as a
            # run failure: a missing/partial shadow input must never abort the real weekly report (best_effort intent).
            try:
                input_paths = [Path(p) for p in stage.inputs(stage_ctx)]
            except Exception as exc:  # noqa: BLE001 - optional lifecycle boundary
                if not _stage_is_optional(stage):
                    raise WeeklyCapstoneError(
                        f"stage '{stage.name}' input enumeration failed: {type(exc).__name__}: {exc}"
                    ) from exc
                input_paths = []
                result = _degrade_stage_boundary(stage, stage_ctx, exc)
                soft_degraded = True
            else:
                soft_degraded = False
            unreadable_inputs = [path for path in input_paths if not _input_readable(path)]
            if unreadable_inputs:
                unreadable = WeeklyCapstoneError(
                    f"stage '{stage.name}' cannot start: declared input(s) missing or unreadable this run: "
                    f"{[_rel(p) for p in unreadable_inputs]}")
                if stage.best_effort:
                    record_nonblocking_failure(stage, unreadable, failure_kind="input_gate")
                    continue
                if _stage_is_optional(stage):
                    input_paths = []
                    result = _degrade_stage_boundary(stage, stage_ctx, unreadable)
                    soft_degraded = True
                    _emit_diagnostic_event(
                        diagnostic_event,
                        "stage_degraded",
                        stage=stage.name,
                        failure_kind="input_gate",
                        error_type=type(unreadable).__name__,
                    )
                else:
                    _emit_diagnostic_event(
                        diagnostic_event,
                        "stage_failed",
                        stage=stage.name,
                        failure_kind="input_gate",
                        error_type=type(unreadable).__name__,
                    )
                    raise unreadable
            try:
                expected_outputs = [Path(p) for p in stage.outputs(stage_ctx)]
            except Exception as exc:  # noqa: BLE001 - optional lifecycle boundary
                if stage.best_effort:
                    record_nonblocking_failure(stage, exc, failure_kind="output_enumeration")
                    continue
                if not _stage_is_optional(stage):
                    raise WeeklyCapstoneError(
                        f"stage '{stage.name}' output enumeration failed: {type(exc).__name__}: {exc}"
                    ) from exc
                expected_outputs = []
                result = _degrade_stage_boundary(stage, stage_ctx, exc)
                soft_degraded = True
                _emit_diagnostic_event(
                    diagnostic_event,
                    "stage_degraded",
                    stage=stage.name,
                    failure_kind="output_enumeration",
                    error_type=type(exc).__name__,
                )
            if resume_manifest is not None and stage.reuse_policy == "frozen_inputs":
                try:
                    restored = checkpoint_store.restore_stage(
                        source_manifest_path=resume_manifest_path,
                        source_manifest=resume_manifest,
                        stage=stage,
                        input_paths=input_paths,
                        input_logical_paths=[_rel(path) for path in input_paths],
                        output_paths=expected_outputs,
                        output_logical_paths=[_rel(path) for path in expected_outputs],
                    )
                except checkpoint_store.CapstoneCheckpointError as exc:
                    raise WeeklyCapstoneError(f"resume checkpoint restore failed at stage '{stage.name}': {exc}") from exc
                if restored is not None:
                    result, stage_generated_at, stage_observed_at = restored
                    if production_run and stage.name == "pass2_preflight":
                        try:
                            approval = _restore_pass2_budget_approval(ctx, result)
                        except Exception as exc:  # noqa: BLE001 - preserve fail-closed resume boundary
                            _emit_diagnostic_event(
                                diagnostic_event,
                                "budget_approval_resume_rejected",
                                error_type=type(exc).__name__,
                            )
                            raise WeeklyCapstoneError(
                                f"Pass2 budget approval could not be restored from checkpoint: {type(exc).__name__}: {exc}"
                            ) from exc
                        ctx = replace(ctx, budget_approval=approval, pass2_budget_preview=False)
                        _emit_diagnostic_event(
                            diagnostic_event,
                            "budget_approval_restored",
                            authorization_mode=approval.authorization_mode,
                            authorization_ref=approval.authorization_ref,
                            target_count=approval.target_count,
                            exact_pass2_calls=approval.exact_pass2_calls,
                            approval_fingerprint=approval.fingerprint,
                        )
                    if stage.name == "soft_discovery":
                        ctx = replace(ctx, soft_discovery_run_result=dict(result))
                    if stage.name == "pass2_fetch":
                        ctx = replace(ctx, soft_boost_run_result=pass2_soft_boost_result(result))
                    if stage.name == "serenity_quality_forward":
                        shadow = result.get("shadow_consumption")
                        ctx = replace(
                            ctx,
                            serenity_quality_run_result=dict(result),
                            serenity_shadow_result=(
                                dict(shadow)
                                if isinstance(shadow, dict) and shadow.get("status") == "active"
                                else None
                            ),
                        )
                    try:
                        checkpoint_manifest = checkpoint_store.record_stage(
                            manifest_path=checkpoint_manifest_path, manifest=checkpoint_manifest, stage=stage,
                            execution_mode="reused", generated_at=stage_generated_at, observed_at=stage_observed_at,
                            input_paths=input_paths, input_logical_paths=[_rel(path) for path in input_paths],
                            output_paths=expected_outputs, output_logical_paths=[_rel(path) for path in expected_outputs],
                            result=result,
                        )
                    except checkpoint_store.CapstoneCheckpointError as exc:
                        raise WeeklyCapstoneError(f"cannot persist reused stage '{stage.name}': {exc}") from exc
                    record_stage_terminal(
                        stage, result, execution_mode="reused",
                        stage_generated_at=stage_generated_at, stage_observed_at=stage_observed_at,
                    )
                    continue
            before = {str(path.resolve()): _output_fingerprint(path) for path in expected_outputs}
            try:
                result = result if soft_degraded else stage.run(stage_ctx)
            except Exception as exc:  # noqa: BLE001 — re-wrap with the stage label so a failure is never anonymous
                if stage.best_effort:
                    record_nonblocking_failure(stage, exc, failure_kind="stage_run")
                    continue
                if not _stage_is_optional(stage):
                    _emit_diagnostic_event(
                        diagnostic_event,
                        "stage_failed",
                        stage=stage.name,
                        failure_kind="stage_run",
                        error_type=type(exc).__name__,
                    )
                    raise WeeklyCapstoneError(f"stage '{stage.name}' failed: {type(exc).__name__}: {exc}") from exc
                result = _degrade_stage_boundary(stage, stage_ctx, exc)
                soft_degraded = True
                _emit_diagnostic_event(
                    diagnostic_event,
                    "stage_degraded",
                    stage=stage.name,
                    failure_kind="stage_run",
                    error_type=type(exc).__name__,
                )
            if not isinstance(result, dict) and _stage_is_optional(stage):
                result = _degrade_stage_boundary(
                    stage,
                    stage_ctx,
                    WeeklyCapstoneError(f"stage '{stage.name}' returned a non-object result"),
                )
                if not isinstance(result, dict):
                    raise WeeklyCapstoneError(
                        f"optional stage '{stage.name}' failure handler returned no result"
                    )
                soft_degraded = True
            elif not isinstance(result, dict):
                raise WeeklyCapstoneError(f"stage '{stage.name}' returned a non-object result")
            # The terminal bridge legitimately writes NO weekly_report.md on an HONEST no-emit (intraday out-of-window
            # or a non-clean provider_health, design §3.2 — e.g. the free-tier FMP-429 case): that is a correct outcome,
            # not a missing-output failure. Detect it from the bridge's own emit flag and return the honest no-emit.
            bridge_emitted = _bridge_emitted(result) if stage.name == "weekly_bridge" else None
            if stage.name == "weekly_bridge" and bridge_emitted is False:
                stage_generated_at, stage_observed_at = stage_clocks(result, fallback_generated_at=ctx.generated_at)
                record_stage_terminal(
                    stage, result, execution_mode="executed",
                    stage_generated_at=stage_generated_at, stage_observed_at=stage_observed_at,
                )
                _abort_current_output_transaction(transaction)
                summary = {
                    "mode": "live",
                    "execution_mode": "live_provider_fetch" if production_run else "injected_pipeline",
                    "report_mode": "mixed_source" if production_run else "offline_test",
                    "operational_use": "not_authorized",
                    "decision_date": ctx.decision_date,
                    "price_basis_date": ctx.price_basis_date,
                    "account_lineage": copy.deepcopy(ctx.account_lineage_status),
                    "emitted": False,
                    "no_emit_reason": _bridge_no_emit_reason(result),
                    "superseded_prior_outputs": {
                        "reason": "pre_run_archive",
                        "moved": [_rel(path) for path in transaction.archived_paths],
                    },
                    "stages": results,
                    "stage_outcomes": stage_outcomes,
                    "stage_outcome_counts": _stage_outcome_counts(stage_outcomes),
                    "checkpoint_manifest": str(checkpoint_manifest_path) if checkpoint_manifest_path else None,
                }
                return summary
            if stage.name == "weekly_bridge" and bridge_emitted is not True:
                raise WeeklyCapstoneError(
                    "weekly_bridge result must explicitly report batch4_run.emitted as a boolean"
                )
            if stage.name == "weekly_bridge":
                batch4 = result.get("batch4_run") if isinstance(result, dict) else None
                output_paths = batch4.get("output_paths") if isinstance(batch4, dict) else None
                expected_manifest = {
                    "weekly_report_path": str(expected_outputs[0].resolve()),
                    "action_table_path": str(expected_outputs[1].resolve()),
                    "machine_record_path": str(expected_outputs[2].resolve()),
                }
                reported_manifest = {
                    key: str(Path(value).resolve()) for key, value in output_paths.items()
                } if isinstance(output_paths, dict) and all(
                    isinstance(key, str) and isinstance(value, str) for key, value in output_paths.items()
                ) else {}
                if reported_manifest != expected_manifest:
                    raise WeeklyCapstoneError(
                        "weekly_bridge emitted=True but its commit evidence does not bind all three official outputs"
                    )
            missing = [
                path for path in expected_outputs
                if _output_fingerprint(path) is None
                or _output_fingerprint(path) == before[str(path.resolve())]
            ]
            if soft_degraded:
                missing = []
            elif missing == expected_outputs and _unchanged_soft_discovery_receipt_matches(
                stage, result, expected_outputs,
            ):
                missing = []
            elif missing == expected_outputs and _unchanged_serenity_quality_outputs_match(
                stage, result, expected_outputs,
            ):
                missing = []
            elif missing and _stage_is_optional(stage):
                if not _is_typed_zero_effect_result(result):
                    result = _degrade_stage_boundary(
                        stage,
                        stage_ctx,
                        WeeklyCapstoneError("optional stage did not produce a fresh output"),
                    )
                soft_degraded = True
                missing = []
            if missing:
                if stage.best_effort:
                    record_nonblocking_failure(
                        stage,
                        WeeklyCapstoneError(
                            f"stage '{stage.name}' completed but did not produce a fresh output this run: "
                            f"{[_rel(p) for p in missing]}"
                        ),
                        failure_kind="fresh_output_missing",
                    )
                    continue
                raise WeeklyCapstoneError(
                    f"stage '{stage.name}' completed but did not produce a fresh output this run: {[_rel(p) for p in missing]}")
            if production_run and stage.name == "pass2_preflight":
                authorization_mode = "one_click_test" if auto_budget_run else "manual"
                try:
                    approval = _build_pass2_budget_approval(
                        ctx, result, authorization_mode=authorization_mode)
                    from runners import us_short_batch5_full_candidate_pass2_preflight as _preflight

                    result = _preflight.finalize_preflight_from_existing_derivation(
                        preflight_summary_path=ctx.preflight_summary_path,
                        approval_binding=approval.binding_summary(),
                    )
                except Exception as exc:  # noqa: BLE001 - preserve fail-closed approval boundary
                    _emit_diagnostic_event(
                        diagnostic_event,
                        "budget_approval_mismatch",
                        error_type=type(exc).__name__,
                        approved_budget=ctx.authorized_pass2_call_budget,
                        derived_budget=(
                            result.get("endpoint_call_forecast", {}).get("total_calls_for_pass2_target_cut")
                            if isinstance(result, dict) else None
                        ),
                    )
                    raise WeeklyCapstoneError(
                        f"Pass2 budget approval could not finalize the existing preflight: {type(exc).__name__}: {exc}"
                    ) from exc
                # The one-click paper launcher and the manual path both carry
                # this same frozen object into every downstream stage. The
                # finalized summary is the derived audit view, not a second
                # editable authorization.
                ctx = replace(
                    ctx,
                    budget_approval=approval,
                    authorized_pass2_call_budget=approval.exact_pass2_calls,
                    pass2_budget_preview=False,
                )
                automatic_cap = _automatic_pass2_http_attempt_cap(
                    exact_pass2_calls=approval.exact_pass2_calls,
                    target_count=approval.target_count,
                    max_retries=ctx.max_retries_per_call,
                )
                requested_cap = ctx.max_total_http_attempts
                if requested_cap is None:
                    effective_cap = automatic_cap
                elif (
                    type(requested_cap) is not int
                    or isinstance(requested_cap, bool)
                    or requested_cap < approval.exact_pass2_calls
                    or requested_cap > automatic_cap
                ):
                    raise WeeklyCapstoneError(
                        "max_total_http_attempts must cover the exact Pass2 logical budget and not exceed "
                        "the reviewed Massive minute-window retry headroom"
                    )
                else:
                    effective_cap = requested_cap
                ctx = replace(ctx, max_total_http_attempts=effective_cap)
                _emit_diagnostic_event(
                    diagnostic_event,
                    "budget_approval_created",
                    authorization_mode=approval.authorization_mode,
                    authorization_ref=approval.authorization_ref,
                    target_count=approval.target_count,
                    exact_pass2_calls=approval.exact_pass2_calls,
                    approval_fingerprint=approval.fingerprint,
                )
                if auto_budget_run:
                    print(
                        f"[US-SHORT AUTO-BUDGET] target_count={approval.target_count} exact_pass2_calls={approval.exact_pass2_calls}",
                        file=sys.stderr,
                    )
            if stage.name == "model_paper_adapter" and _model_paper_enabled(ctx):
                ctx = _update_model_paper_context(ctx, result)
            if stage.name == "soft_discovery":
                ctx = replace(ctx, soft_discovery_run_result=dict(result))
            if stage.name == "pass2_fetch":
                ctx = replace(ctx, soft_boost_run_result=pass2_soft_boost_result(result))
            if stage.name == "serenity_quality_forward":
                shadow = result.get("shadow_consumption")
                ctx = replace(
                    ctx,
                    serenity_quality_run_result=dict(result),
                    serenity_shadow_result=(
                        dict(shadow)
                        if isinstance(shadow, dict) and shadow.get("status") == "active"
                        else None
                    ),
                )
            execution_mode = "executed"
            if resume_manifest is not None and stage.reuse_policy == "refresh_then_reuse_if_equivalent":
                try:
                    if checkpoint_store.refresh_output_from_equivalent_checkpoint(
                        source_manifest_path=resume_manifest_path,
                        source_manifest=resume_manifest,
                        stage=stage,
                        output_paths=expected_outputs,
                        output_logical_paths=[_rel(path) for path in expected_outputs],
                    ):
                        execution_mode = "refreshed_equivalent"
                except checkpoint_store.CapstoneCheckpointError as exc:
                    raise WeeklyCapstoneError(
                        f"resume equivalence refresh failed at stage '{stage.name}': {exc}"
                    ) from exc
            stage_generated_at, stage_observed_at = stage_clocks(result, fallback_generated_at=ctx.generated_at)
            record_stage_terminal(
                stage, result, execution_mode=execution_mode,
                stage_generated_at=stage_generated_at, stage_observed_at=stage_observed_at,
            )
            if checkpoint_manifest_path is not None and stage.name != "weekly_bridge":
                try:
                    checkpoint_manifest = checkpoint_store.record_stage(
                        manifest_path=checkpoint_manifest_path, manifest=checkpoint_manifest, stage=stage,
                        execution_mode=execution_mode, generated_at=stage_generated_at,
                        observed_at=stage_observed_at, input_paths=input_paths,
                        input_logical_paths=[_rel(path) for path in input_paths], output_paths=expected_outputs,
                        output_logical_paths=[_rel(path) for path in expected_outputs], result=result,
                        allow_unavailable=_stage_is_optional(stage),
                    )
                except Exception as exc:
                    if not _stage_is_optional(stage):
                        raise WeeklyCapstoneError(
                            f"cannot persist stage checkpoint '{stage.name}': "
                            f"{type(exc).__name__}: {exc}"
                        ) from exc
                    # A broken private checkpoint root is itself an optional
                    # observation failure.  Keep the terminal weekly report
                    # and expose the missing checkpoint as a diagnostic; never
                    # fabricate a bundle or reuse this row later.
                    if results and results[-1].get("name") == stage.name:
                        results[-1]["checkpoint"] = {
                            "output_availability": "unavailable",
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    _emit_diagnostic_event(
                        diagnostic_event,
                        "stage_checkpoint_unavailable",
                        stage=stage.name,
                        error_type=type(exc).__name__,
                    )
        _publish_current_output_transaction(ctx, transaction)
    except Exception:
        try:
            if transaction.journal_path.exists():
                state = _read_transaction_journal(transaction.journal_path)
                if state["phase"] == "running":
                    _abort_current_output_transaction(transaction)
        finally:
            _release_decision_lock(transaction.decision_lock)
        raise

    summary = {
        "mode": "live",
        "execution_mode": "live_provider_fetch" if production_run else "injected_pipeline",
        "report_mode": "mixed_source" if production_run else "offline_test",
        "operational_use": "not_authorized",
        "decision_date": ctx.decision_date,
        "price_basis_date": ctx.price_basis_date,
        "account_lineage": copy.deepcopy(ctx.account_lineage_status),
        "authorized_momentum_top_k": ctx.authorized_momentum_top_k,
        "authorized_pass2_call_budget": ctx.authorized_pass2_call_budget,
        "emitted": True,
        "emitted_report": _rel(ctx.private_root / "weekly_private" / ctx.decision_date / "weekly_report.md"),
        "stages": results,
        "stage_outcomes": stage_outcomes,
        "stage_outcome_counts": _stage_outcome_counts(stage_outcomes),
        "checkpoint_manifest": str(checkpoint_manifest_path) if checkpoint_manifest_path else None,
    }
    return summary


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
    parser.add_argument("--private-root", type=Path, default=STATE_DIR,
                        help="private (gitignored) output root; default state/us_short, relative to the checkout you "
                             "run from — the weekly report / action table land under <root>/weekly_private/"
                             "<decision_date>/ and the machine record under <root>/runs_private/<decision_date>/. "
                             "Running from the main D:/cnhea/Stock checkout therefore writes under "
                             "D:/cnhea/Stock/state/us_short/; a feature worktree writes under its own tree.")
    parser.add_argument("--batch4-template-path", required=True, type=Path)
    parser.add_argument("--account-state-path", required=True, type=Path)
    parser.add_argument(
        "--account-lineage-path",
        type=Path,
        help="account lineage sidecar; default <account-state stem>_lineage.json",
    )
    parser.add_argument("--momentum-top-k", type=int, default=200)
    parser.add_argument("--pass2-call-budget", type=int)
    parser.add_argument("--catalyst-recall-ticker", action="append", default=[])
    parser.add_argument("--calendar-path", type=Path, default=CALENDAR_PRESET)
    parser.add_argument("--confirm-user-authorization", action="store_true",
                        help="required with --live; the reviewed PowerShell -Live entrypoint supplies it")
    parser.add_argument("--live", action="store_true", help="execute (default is a dry-run plan only)")
    parser.add_argument(
        "--prepare-pass2-budget",
        action="store_true",
        help=(
            "run only the authorized upstream funnel through Pass2 preflight and print its exact call forecast; "
            "does not authorize or execute yfinance, Pass2, VIX, or the weekly bridge"
        ),
    )
    parser.add_argument(
        "--auto-pass2-budget",
        action="store_true",
        help=(
            "derive and apply the exact Pass2 call budget from this same run's preflight; intended for the "
            "one-click paper launcher and cannot be combined with --prepare-pass2-budget or a supplied budget"
        ),
    )
    parser.add_argument("--provider-pace-seconds", type=float, default=1.0)
    parser.add_argument("--max-retries-per-call", type=int, default=None,
                        help="Massive HTTP 429 retries per call (0, 1, or 2; one-click default is 2)")
    parser.add_argument("--retry-backoff-seconds", type=float, default=None,
                        help="Massive HTTP 429 wait; omitted/0 normalizes to the fixed 65-second policy")
    parser.add_argument("--max-total-http-attempts", type=int,
                        help="explicit physical HTTP-attempt cap required for live 429 retries")
    parser.add_argument("--resume", type=Path,
                        help="explicit checkpoint_manifest.json bundle to validate/import; never scans other worktrees")
    parser.add_argument(
        "--disable-soft-discovery",
        dest="soft_discovery_enabled",
        action="store_false",
        default=True,
        help="emergency opt-out; the one-click path otherwise consumes the frozen Knife3 pair offline and never fetches",
    )
    parser.add_argument(
        "--disable-theme-soft-boost",
        dest="theme_soft_boost_enabled",
        action="store_false",
        default=True,
        help="emergency K4b score opt-out; low-level score/data-context APIs remain explicit-OFF by default",
    )
    args = parser.parse_args(argv)
    try:
        summary = run_weekly_capstone(
            now_et=args.now_et, private_root=args.private_root,
            batch4_template_path=args.batch4_template_path, account_state_path=args.account_state_path,
            account_lineage_path=args.account_lineage_path,
            authorized_momentum_top_k=args.momentum_top_k,
            authorized_pass2_call_budget=args.pass2_call_budget,
            catalyst_recall_tickers=tuple(args.catalyst_recall_ticker),
            calendar_path=args.calendar_path, confirm_user_authorization=args.confirm_user_authorization,
            dry_run=not (args.live or args.prepare_pass2_budget), provider_pace_seconds=args.provider_pace_seconds,
            max_retries_per_call=args.max_retries_per_call, retry_backoff_seconds=args.retry_backoff_seconds,
            max_total_http_attempts=args.max_total_http_attempts,
            resume_from=args.resume,
            prepare_pass2_budget=args.prepare_pass2_budget,
            auto_authorize_pass2_budget=args.auto_pass2_budget,
            soft_discovery_enabled=args.soft_discovery_enabled,
            theme_soft_boost_enabled=args.theme_soft_boost_enabled,
        )
    except WeeklyCapstoneError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    import json
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
