from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_eligibility_gate import canonical_us_ticker, load_eligibility_governance  # noqa: E402
from engine.us_short_pass2_funnel import select_pass2_targets  # noqa: E402
from engine.us_short_projection_binding import (  # noqa: E402
    file_sha256,
    ticker_partition_sha256,
    validate_projection_binding,
)
from engine.us_short_seam_momentum import (  # noqa: E402
    COVERAGE_DISPOSITIONS as MOMENTUM_COVERAGE_DISPOSITIONS,
    DISPOSITION_SCORED as MOMENTUM_SCORED_DISPOSITION,
)
from engine.us_short_seam_theme import (  # noqa: E402
    COVERAGE_DISPOSITIONS as THEME_COVERAGE_DISPOSITIONS,
    DISPOSITION_SCORED_INDUSTRY_BASE,
    DISPOSITION_SCORED_THEME_BASE,
)
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402


AUTHORIZATION_REF = "user_chat_20260706_us_short_full_candidate_pass2_preflight"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_candidate_pass2_preflight_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_full_candidate_pass2_preflight_summary_20260706.json"
PROVIDER_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_full_candidate_pass2_preflight_20260706")
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260706.json"
DEFAULT_MOMENTUM_PROJECTION_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_full_candidate_projection_inputs_20260706_momentum.json"
)
DEFAULT_THEME_PROJECTION_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_full_candidate_projection_inputs_20260706_theme.json"
)
BENCHMARK_SYMBOLS = ("SPY", "QQQ")
FMP_FREE_DAILY_GRADE_CALL_CAP = 250
PASS2_TARGET_SELECTION_MODE = "momentum_theme_top_k_plus_catalyst_recall_plus_forced_holdings"
MOMENTUM_TOP_K_DEFAULT = 200


class FullCandidatePass2PreflightError(ValueError):
    """The full-candidate Pass2 live cut is not ready to execute safely."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(path)


def _repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _display_path(path: Path) -> str:
    try:
        return _repo_rel(path)
    except ValueError:
        return str(path)


def _resolve_repo_path(path: Path | str, *, field: str) -> Path:
    raw = Path(path)
    resolved = raw.resolve() if raw.is_absolute() else (ROOT / raw).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise FullCandidatePass2PreflightError(f"{field} must stay under the repository root") from exc
    return resolved


def _git_ignored(path: Path) -> bool:
    rel = _repo_rel(path)
    result = subprocess.run(
        ["git", "-c", "core.excludesFile=", "check-ignore", "-q", "--", rel],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _existing_state_json(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise FullCandidatePass2PreflightError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise FullCandidatePass2PreflightError(f"{field} must be a .json file")
    if not resolved.exists() or not resolved.is_file():
        raise FullCandidatePass2PreflightError(f"{field} must be an existing file: {_display_path(resolved)}")
    if not _git_ignored(resolved):
        raise FullCandidatePass2PreflightError(f"{field} must be gitignored")
    return resolved


def _validate_summary_path(path: Path | str) -> Path:
    resolved = _resolve_repo_path(path, field="summary_path")
    if resolved.suffix != ".json":
        raise FullCandidatePass2PreflightError("summary_path must be a .json file")
    if resolved == SUMMARY_PATH.resolve():
        return resolved
    try:
        resolved.relative_to((ROOT / PROVIDER_SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise FullCandidatePass2PreflightError(
            "summary_path must be the canonical tracked summary or under this runner's provider_samples folder"
        ) from exc
    if not _git_ignored(resolved):
        raise FullCandidatePass2PreflightError("non-canonical summary_path must be gitignored")
    return resolved


def _valid_observed_at(value: str) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _format_price_basis_date(value: Any) -> str:
    if not (type(value) is str and len(value) == 8 and value.isascii() and value.isdigit()):
        raise FullCandidatePass2PreflightError("price_basis_date must be canonical YYYYMMDD")
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise FullCandidatePass2PreflightError("price_basis_date must be a real calendar date") from exc
    return parsed.strftime("%Y-%m-%d")


def _canonical_keys(value: Any, *, field: str) -> set[str]:
    if type(value) is not dict:
        raise FullCandidatePass2PreflightError(f"{field} must be an exact dict")
    out: set[str] = set()
    for raw in value:
        ticker = canonical_us_ticker(raw)
        if ticker is None:
            raise FullCandidatePass2PreflightError(f"{field} contains a non-canonicalizable ticker key")
        if ticker in out:
            raise FullCandidatePass2PreflightError(f"{field} contains duplicate canonical ticker: {ticker}")
        out.add(ticker)
    return out


def _canonical_list_keys(value: Any, *, field: str) -> set[str]:
    if type(value) is not list:
        raise FullCandidatePass2PreflightError(f"{field} must be an exact list")
    out: set[str] = set()
    for raw in value:
        if type(raw) is not str:
            raise FullCandidatePass2PreflightError(f"{field} must contain exact ticker strings")
        ticker = canonical_us_ticker(raw)
        if ticker is None:
            raise FullCandidatePass2PreflightError(f"{field} contains a non-canonicalizable ticker")
        if ticker in out:
            raise FullCandidatePass2PreflightError(f"{field} contains duplicate canonical ticker: {ticker}")
        out.add(ticker)
    return out


def _canonical_score_map(value: Any, *, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise FullCandidatePass2PreflightError(f"{field} must be an exact dict")
    out: dict[str, Any] = {}
    for raw_ticker, raw_score in value.items():
        ticker = canonical_us_ticker(raw_ticker)
        if ticker is None:
            raise FullCandidatePass2PreflightError(f"{field} contains a non-canonicalizable ticker key")
        if ticker in out:
            raise FullCandidatePass2PreflightError(f"{field} contains duplicate canonical ticker: {ticker}")
        out[ticker] = raw_score
    return out


def _projection_coverage(
    *,
    projection: Any,
    projection_name: str,
    value_key: str,
    expected_tickers: list[str],
    allowed_dispositions: set[str] | frozenset[str] | tuple[str, ...],
    scored_dispositions: set[str] | frozenset[str] | tuple[str, ...],
) -> dict[str, Any]:
    if type(projection) is not dict:
        raise FullCandidatePass2PreflightError(f"{projection_name} must be an exact dict")
    value_keys = _canonical_keys(projection.get(value_key), field=f"{projection_name}.{value_key}")
    neutral_keys = _canonical_list_keys(
        projection.get("neutral_fill_tickers"),
        field=f"{projection_name}.neutral_fill_tickers",
    )
    if value_keys & neutral_keys:
        raise FullCandidatePass2PreflightError(f"{projection_name} has scored/neutral overlap")
    coverage_keys = _canonical_keys(projection.get("coverage"), field=f"{projection_name}.coverage")
    allowed = set(allowed_dispositions)
    if any(type(value) is not str or value not in allowed for value in projection["coverage"].values()):
        raise FullCandidatePass2PreflightError(f"{projection_name}.coverage contains an invalid disposition")
    scored_allowed = set(scored_dispositions)
    if any(projection["coverage"][ticker] not in scored_allowed for ticker in value_keys):
        raise FullCandidatePass2PreflightError(f"{projection_name} scored ticker has a neutral disposition")
    if any(projection["coverage"][ticker] in scored_allowed for ticker in neutral_keys):
        raise FullCandidatePass2PreflightError(f"{projection_name} neutral ticker has a scored disposition")
    partition_keys = value_keys | neutral_keys
    expected = set(expected_tickers)
    covered = expected & partition_keys & coverage_keys
    missing = sorted(expected - covered)
    stale = sorted((partition_keys | coverage_keys) - expected)
    return {
        "status": "full_coverage" if not missing and not stale else "missing_or_stale",
        "path": None,
        "covered_count": len(covered),
        "missing_count": len(missing),
        "stale_count": len(stale),
        "neutral_fill_count": len(neutral_keys),
        "_scored_tickers": sorted(value_keys),
        "_scored_score_map": _canonical_score_map(projection.get(value_key), field=f"{projection_name}.{value_key}"),
        "_neutral_tickers": sorted(neutral_keys),
        "missing_sample": missing[:10],
        "stale_sample": stale[:10],
        "target_count": projection.get("target_count") if type(projection.get("target_count")) is int else None,
        "scored_count": projection.get("scored_count") if type(projection.get("scored_count")) is int else None,
    }


def _load_candidate_artifact(
    *,
    candidate_artifact_path: Path,
    expected_decision_date: str,
) -> dict[str, Any]:
    artifact = _read_json(candidate_artifact_path)
    governance = load_eligibility_governance(ELIGIBILITY_GOVERNANCE_PATH)
    try:
        return universe_fetch.validate_candidate_artifact(
            artifact,
            expected_decision_date=expected_decision_date,
            governance=governance,
        )
    except Exception as exc:
        raise FullCandidatePass2PreflightError(f"candidate artifact failed validation: {exc}") from exc


def _public_projection_coverage(coverage: dict[str, Any], *, path: Path) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(coverage, path=_repo_rel(path)).items()
        if not key.startswith("_")
    }


def _pass2_target_universe(
    *,
    eligible_tickers: list[str],
    momentum_coverage: dict[str, Any],
    theme_coverage: dict[str, Any],
    catalyst_recall_tickers: list[str] | tuple[str, ...] | None,
    forced_holding_tickers: list[str] | tuple[str, ...] | None,
    momentum_top_k: int,
) -> dict[str, Any]:
    eligible = set(eligible_tickers)
    momentum_scores = momentum_coverage["_scored_score_map"]
    momentum_scored_candidate_count = len([ticker for ticker in momentum_scores if ticker in eligible])
    if forced_holding_tickers is None:
        forced_raw: list[str] = []
    elif type(forced_holding_tickers) in (list, tuple):
        forced_raw = list(forced_holding_tickers)
    else:
        raise FullCandidatePass2PreflightError("forced_holding_tickers must be an exact list/tuple or None")
    forced = _canonical_list_keys(forced_raw, field="forced_holding_tickers")
    if catalyst_recall_tickers is None:
        recall_raw: list[str] = []
    elif type(catalyst_recall_tickers) in (list, tuple):
        recall_raw = list(catalyst_recall_tickers)
    else:
        raise FullCandidatePass2PreflightError("catalyst_recall_tickers must be an exact list/tuple or None")
    recall = _canonical_list_keys(recall_raw, field="catalyst_recall_tickers")
    targets = select_pass2_targets(
        momentum_scores=momentum_scores,
        theme_scores=theme_coverage["_scored_score_map"],
        eligible=eligible,
        catalyst_recall=recall,
        forced_holdings=forced,
        top_k=momentum_top_k,
    )
    target_count = len(targets)
    full_eligible = target_count == len(eligible_tickers)
    within_cap = target_count <= FMP_FREE_DAILY_GRADE_CALL_CAP
    return {
        "selection_mode": PASS2_TARGET_SELECTION_MODE,
        "eligible_count": len(eligible_tickers),
        "momentum_scored_candidate_count": momentum_scored_candidate_count,
        "theme_scored_candidate_count": len([ticker for ticker in theme_coverage["_scored_score_map"] if ticker in eligible]),
        "momentum_top_k": momentum_top_k,
        "catalyst_recall_count": len(recall),
        "catalyst_recall_tickers_sha256": ticker_partition_sha256(recall),
        "forced_holding_count": len(forced),
        "forced_holding_tickers_sha256": ticker_partition_sha256(forced),
        "target_count": target_count,
        "target_symbols": targets,
        "target_symbol_sample": targets[:10],
        "fmp_grade_call_cap": FMP_FREE_DAILY_GRADE_CALL_CAP,
        "fmp_grade_calls_within_free_daily_cap": within_cap,
        "neutral_fill_tickers_excluded_from_expensive_pass2": True,
        "expensive_pass2_targets_full_eligible_set": full_eligible,
    }


def _forecast_calls(pass2_target_count: int, full_candidate_count: int) -> dict[str, Any]:
    pass2 = {
        "sec_company_tickers_mapping_calls": 1,
        "fmp_grades_calls": pass2_target_count,
        "sec_submissions_calls": pass2_target_count,
        "massive_reference_news_calls": pass2_target_count,
        "total_calls": 1 + (pass2_target_count * 3),
    }
    corporate_action = {
        "massive_split_calls": pass2_target_count,
        "massive_dividend_calls": pass2_target_count,
        "total_calls": pass2_target_count * 2,
        "corporate_action_reconciliation_performed_by_preflight": False,
    }
    momentum_refresh = {
        "massive_daily_aggregates_calls": pass2_target_count + len(BENCHMARK_SYMBOLS),
        "benchmark_symbols": list(BENCHMARK_SYMBOLS),
        "not_in_total_until_separate_price_packet_review": True,
    }
    total = pass2["total_calls"] + corporate_action["total_calls"]
    hypothetical_full_candidate_total = 1 + (full_candidate_count * 3) + (full_candidate_count * 2)
    return {
        "families": {
            "pass2_source_packet": pass2,
            "corporate_action_live_half": corporate_action,
            "momentum_price_refresh_if_local_projection_missing": momentum_refresh,
        },
        "forecast_basis": "pass2_target_universe_not_full_eligible_count",
        "total_calls_for_pass2_target_cut": total,
        "total_calls_for_full_candidate_cut": hypothetical_full_candidate_total,
        "total_calls_for_full_candidate_cut_is_hypothetical": True,
        "call_budget_must_be_explicit_before_network": True,
        "full_market_call_performed": False,
    }


def _build_summary(
    *,
    generated_at: str,
    candidate_path: Path,
    momentum_path: Path,
    theme_path: Path,
    summary_path: Path,
    artifact: dict[str, Any],
    momentum_coverage: dict[str, Any],
    theme_coverage: dict[str, Any],
    catalyst_recall_tickers: list[str] | tuple[str, ...] | None,
    forced_holding_tickers: list[str] | tuple[str, ...] | None,
    momentum_top_k: int,
    authorized_total_call_budget: int | None,
) -> dict[str, Any]:
    eligible = list(artifact["eligible_tickers"])
    candidate_count = len(eligible)
    pass2_targets = _pass2_target_universe(
        eligible_tickers=eligible,
        momentum_coverage=momentum_coverage,
        theme_coverage=theme_coverage,
        catalyst_recall_tickers=catalyst_recall_tickers,
        forced_holding_tickers=forced_holding_tickers,
        momentum_top_k=momentum_top_k,
    )
    local_ready = (
        momentum_coverage["status"] == "full_coverage"
        and theme_coverage["status"] == "full_coverage"
    )
    pass2_targets_ready = pass2_targets["target_count"] > 0 and pass2_targets["fmp_grade_calls_within_free_daily_cap"]
    forecast = _forecast_calls(pass2_targets["target_count"], candidate_count)
    # A missing budget is a preview, never an implicit authorization.  The forecast is intentionally visible so the
    # operator can make the independently authorized exact-budget rerun, but downstream live-source runners still
    # require a ready gate whose budget exactly matches this value.
    budget_ready = (
        authorized_total_call_budget is not None
        and authorized_total_call_budget == forecast["total_calls_for_pass2_target_cut"]
    )
    ready = local_ready and pass2_targets_ready and budget_ready
    status = (
        "ready_for_reviewed_live_execution"
        if ready
        else "blocked_missing_local_inputs"
        if not local_ready
        else "blocked_execution_constraints"
    )
    block_reasons: list[str] = []
    if not local_ready:
        block_reasons.append("missing_or_stale_local_score_projection_inputs")
    if pass2_targets["target_count"] <= 0:
        block_reasons.append("no_momentum_scored_or_forced_holding_pass2_targets")
    if not pass2_targets["fmp_grade_calls_within_free_daily_cap"]:
        block_reasons.append("pass2_target_count_exceeds_fmp_free_daily_grade_call_cap")
    if authorized_total_call_budget is None:
        block_reasons.append("pass2_call_budget_not_yet_authorized")
    elif not budget_ready:
        block_reasons.append("authorized_call_budget_does_not_match_rederived_target_forecast")
    momentum_coverage = _public_projection_coverage(momentum_coverage, path=momentum_path)
    theme_coverage = _public_projection_coverage(theme_coverage, path=theme_path)
    return {
        "schema_name": "us_short_batch5_full_candidate_pass2_preflight_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_full_candidate_pass2_preflight_summary.schema.json",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "full_candidate_pass2_live_source_packet_preflight",
            "status": status,
            "network_access_performed": False,
            "provider_calls_performed": False,
            "raw_payload_storage_performed": False,
            "source_packet_written": False,
            "data_context_written": False,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "full_market_call_performed": False,
            "yfinance_consumption_performed": False,
            "broker_or_order_execution_performed": False,
            "ship_gate_or_live_normalized_evidence_claimed": False,
            "a_share_crossing_performed": False,
        },
        "decision_clock": {
            "expected_decision_date": artifact["decision_date"],
            "candidate_price_basis_date": artifact["price_basis_date"],
            "price_basis_date": _format_price_basis_date(artifact["price_basis_date"]),
            "used_date": artifact["used_date"],
        },
        "candidate_universe": {
            "candidate_artifact_path": _repo_rel(candidate_path),
            "candidate_artifact_path_gitignored": _git_ignored(candidate_path),
            "row_count": len(artifact["rows"]),
            "eligible_count": candidate_count,
            "eligible_symbol_sample": eligible[:10],
            "symbol_scope": "full_pass1_eligible_candidate_set",
            "full_market_sample": False,
        },
        "local_input_coverage": {
            "momentum_projection": momentum_coverage,
            "theme_projection": theme_coverage,
            "all_required_local_inputs_cover_candidates": local_ready,
        },
        "pass2_target_universe": pass2_targets,
        "endpoint_call_forecast": forecast,
        "execution_gate": dict({
            "ready_to_run_full_candidate_live_packet": ready,
            "block_reasons": block_reasons,
            "requires_separate_network_tool_approval": True,
            "requires_explicit_call_budget": True,
            "authorized_momentum_top_k": momentum_top_k,
            "authorized_budget_matches_rederived_forecast": budget_ready,
            "provider_selection_claimed": False,
            "corporate_action_reconciliation_claimed": False,
            "datahub_or_production_allowed": False,
            "ship_gate_evidence_allowed": False,
        }, **({
            "authorized_total_call_budget": authorized_total_call_budget,
        } if authorized_total_call_budget is not None else {})),
        "storage": {
            "tracked_summary_path": _repo_rel(summary_path),
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_raw_payload": False,
            "tracked_summary_contains_request_urls": False,
            "tracked_summary_contains_secrets": False,
        },
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "paid_access_used": False,
            "datahub_consumed": False,
            "production_readiness_claimed": False,
            "ship_gate_evidence_claimed": False,
            "live_normalized_evidence_claimed": False,
            "broker_or_order_execution_performed": False,
            "a_share_crossing_performed": False,
        },
        "limitations": [
            "This preflight performs no provider calls and writes no source packet; it only computes Pass2 target readiness and call forecast.",
            "The full Pass1-eligible candidate set remains the local score coverage basis; expensive Pass2 live fetch is narrowed to momentum-scored candidates plus forced holdings.",
            "Corporate-action live half is forecast as split/dividend endpoint capture only; reconciliation, returns, DataHub, production, and ship-gate evidence remain out of scope.",
            "Automated broader peer-theme discovery remains separate; this preflight only verifies whether the provided local theme projection already covers all candidates.",
        ],
    }


def _validate_summary_against_schema(summary: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise FullCandidatePass2PreflightError("jsonschema is required for preflight summary validation") from exc
    schema = _read_json(SUMMARY_SCHEMA_PATH)
    errors = sorted(Draft7Validator(schema).iter_errors(summary), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise FullCandidatePass2PreflightError(
            f"full-candidate Pass2 preflight summary failed schema validation: {joined}"
        ) from errors[0]


def _assert_text_safe(text: str) -> None:
    lower = text.lower()
    forbidden = (
        "apikey=",
        "financialmodelingprep.com",
        "api.massive.com",
        "data.sec.gov",
        "www.sec.gov",
        "http://",
        "https://",
        "\"payload\"",
        "\"raw_payload\"",
        "\"request_url\"",
        "bearer ",
        "token=",
    )
    for fragment in forbidden:
        if fragment in lower:
            raise FullCandidatePass2PreflightError(f"tracked summary contains forbidden fragment: {fragment}")


def _write_summary_validated(summary: dict[str, Any], summary_path: Path) -> None:
    _validate_summary_against_schema(summary)
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text)
    _write_json_atomic(summary, summary_path)


def run_preflight(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    expected_decision_date: str,
    momentum_projection_path: Path = DEFAULT_MOMENTUM_PROJECTION_PATH,
    theme_projection_path: Path = DEFAULT_THEME_PROJECTION_PATH,
    summary_path: Path = SUMMARY_PATH,
    forced_holding_tickers: list[str] | tuple[str, ...] | None = None,
    catalyst_recall_tickers: list[str] | tuple[str, ...] | None = None,
    momentum_top_k: int = MOMENTUM_TOP_K_DEFAULT,
    authorized_total_call_budget: int | None = None,
    confirm_user_authorization: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if not confirm_user_authorization:
        raise FullCandidatePass2PreflightError("full-candidate Pass2 preflight requires explicit user authorization")
    if authorized_total_call_budget is not None and (
        type(authorized_total_call_budget) is not int
        or isinstance(authorized_total_call_budget, bool)
        or authorized_total_call_budget < 1
    ):
        raise FullCandidatePass2PreflightError("authorized_total_call_budget must be a positive exact int")
    generated_at = generated_at or iso_now()
    if not _valid_observed_at(generated_at):
        raise FullCandidatePass2PreflightError("generated_at must be a timezone-aware RFC3339 instant")
    candidate_path = _existing_state_json(candidate_artifact_path, field="candidate_artifact_path")
    momentum_path = _existing_state_json(momentum_projection_path, field="momentum_projection_path")
    theme_path = _existing_state_json(theme_projection_path, field="theme_projection_path")
    summary_resolved = _validate_summary_path(summary_path)
    artifact = _load_candidate_artifact(
        candidate_artifact_path=candidate_path,
        expected_decision_date=expected_decision_date,
    )
    _format_price_basis_date(artifact["price_basis_date"])
    eligible = list(artifact["eligible_tickers"])
    momentum_projection = _read_json(momentum_path)
    theme_projection = _read_json(theme_path)
    try:
        validate_projection_binding(
            momentum_projection,
            component="momentum",
            expected_decision_date=expected_decision_date,
            candidate_price_basis_date=artifact["price_basis_date"],
            source_as_of=artifact["used_date"],
            target_tickers=None,
            expected_producer_id="us_short_batch5_full_candidate_projection_inputs",
            expected_source_roles=("candidate_artifact", "source_momentum_projection"),
            allowed_dispositions=MOMENTUM_COVERAGE_DISPOSITIONS,
            scored_dispositions={MOMENTUM_SCORED_DISPOSITION},
        )
        validate_projection_binding(
            theme_projection,
            component="theme",
            expected_decision_date=expected_decision_date,
            candidate_price_basis_date=artifact["price_basis_date"],
            source_as_of=artifact["used_date"],
            target_tickers=None,
            expected_producer_id="us_short_batch5_full_candidate_projection_inputs",
            expected_source_roles=("candidate_artifact", "source_theme_projection"),
            allowed_dispositions=THEME_COVERAGE_DISPOSITIONS,
            scored_dispositions={DISPOSITION_SCORED_THEME_BASE, DISPOSITION_SCORED_INDUSTRY_BASE},
        )
    except ValueError as exc:
        raise FullCandidatePass2PreflightError(f"score projection source binding rejected: {exc}") from exc
    momentum_coverage = _projection_coverage(
        projection=momentum_projection,
        projection_name="momentum_projection",
        value_key="momentum_by_ticker",
        expected_tickers=eligible,
        allowed_dispositions=MOMENTUM_COVERAGE_DISPOSITIONS,
        scored_dispositions=(MOMENTUM_SCORED_DISPOSITION,),
    )
    theme_coverage = _projection_coverage(
        projection=theme_projection,
        projection_name="theme_projection",
        value_key="theme_block_by_ticker",
        expected_tickers=eligible,
        allowed_dispositions=THEME_COVERAGE_DISPOSITIONS,
        scored_dispositions=(DISPOSITION_SCORED_THEME_BASE, DISPOSITION_SCORED_INDUSTRY_BASE),
    )
    momentum_coverage["artifact_sha256"] = file_sha256(momentum_path)
    momentum_coverage["producer_id"] = momentum_projection["source_binding"]["producer_id"]
    theme_coverage["artifact_sha256"] = file_sha256(theme_path)
    theme_coverage["producer_id"] = theme_projection["source_binding"]["producer_id"]
    summary = _build_summary(
        generated_at=generated_at,
        candidate_path=candidate_path,
        momentum_path=momentum_path,
        theme_path=theme_path,
        summary_path=summary_resolved,
        artifact=artifact,
        momentum_coverage=momentum_coverage,
        theme_coverage=theme_coverage,
        catalyst_recall_tickers=catalyst_recall_tickers,
        forced_holding_tickers=forced_holding_tickers,
        momentum_top_k=momentum_top_k,
        authorized_total_call_budget=authorized_total_call_budget,
    )
    _write_summary_validated(summary, summary_resolved)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight the US-short Batch5 full-candidate Pass2 live source-packet cut. "
            "This computes readiness and call forecast only; it performs no provider calls."
        )
    )
    parser.add_argument("--candidate-artifact-path", type=Path, default=DEFAULT_CANDIDATE_ARTIFACT_PATH)
    parser.add_argument("--decision-date", required=True, help="Expected decision date as YYYYMMDD.")
    parser.add_argument("--momentum-projection-path", type=Path, default=DEFAULT_MOMENTUM_PROJECTION_PATH)
    parser.add_argument("--theme-projection-path", type=Path, default=DEFAULT_THEME_PROJECTION_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--forced-holding-ticker", action="append", default=[])
    parser.add_argument("--catalyst-recall-ticker", action="append", default=[])
    parser.add_argument("--momentum-top-k", type=int, default=MOMENTUM_TOP_K_DEFAULT)
    budget_mode = parser.add_mutually_exclusive_group(required=True)
    budget_mode.add_argument("--authorized-total-call-budget", type=int)
    budget_mode.add_argument(
        "--print-budget",
        action="store_true",
        help="derive the exact Pass2 call forecast only; leaves execution explicitly blocked",
    )
    parser.add_argument("--generated-at")
    parser.add_argument("--confirm-user-authorization", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run_preflight(
            candidate_artifact_path=args.candidate_artifact_path,
            expected_decision_date=args.decision_date,
            momentum_projection_path=args.momentum_projection_path,
            theme_projection_path=args.theme_projection_path,
            summary_path=args.summary_path,
            forced_holding_tickers=args.forced_holding_ticker,
            catalyst_recall_tickers=args.catalyst_recall_ticker,
            momentum_top_k=args.momentum_top_k,
            authorized_total_call_budget=args.authorized_total_call_budget,
            confirm_user_authorization=args.confirm_user_authorization,
            generated_at=args.generated_at,
        )
    except FullCandidatePass2PreflightError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "mode": "budget_preview" if args.print_budget else "authorization_check",
                "status": summary["scope"]["status"],
                "eligible_count": summary["candidate_universe"]["eligible_count"],
                "pass2_target_count": summary["pass2_target_universe"]["target_count"],
                "forecast_calls": summary["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"],
                "summary_path": summary["storage"]["tracked_summary_path"],
                **({
                    "next_required": (
                        "re-run with --authorized-total-call-budget "
                        f"{summary['endpoint_call_forecast']['total_calls_for_pass2_target_cut']} "
                        "after independent authorization"
                    ),
                } if args.print_budget else {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
