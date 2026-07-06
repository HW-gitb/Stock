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
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402


AUTHORIZATION_REF = "user_chat_20260706_us_short_full_candidate_pass2_preflight"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_candidate_pass2_preflight_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_full_candidate_pass2_preflight_summary_20260706.json"
PROVIDER_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_full_candidate_pass2_preflight_20260706")
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260706.json"
DEFAULT_MOMENTUM_PROJECTION_PATH = STATE_US_SHORT_DIR / "us_short_batch5_momentum_price_source_20260705_momentum.json"
DEFAULT_THEME_PROJECTION_PATH = STATE_US_SHORT_DIR / "us_short_batch5_theme_source_20260705_theme.json"
BENCHMARK_SYMBOLS = ("SPY", "QQQ")


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


def _projection_coverage(
    *,
    projection: Any,
    projection_name: str,
    value_key: str,
    expected_tickers: list[str],
) -> dict[str, Any]:
    if type(projection) is not dict:
        raise FullCandidatePass2PreflightError(f"{projection_name} must be an exact dict")
    value_keys = _canonical_keys(projection.get(value_key), field=f"{projection_name}.{value_key}")
    coverage_keys = _canonical_keys(projection.get("coverage"), field=f"{projection_name}.coverage")
    expected = set(expected_tickers)
    covered = expected & value_keys & coverage_keys
    missing = sorted(expected - covered)
    stale = sorted((value_keys | coverage_keys) - expected)
    return {
        "status": "full_coverage" if not missing and not stale else "missing_or_stale",
        "path": None,
        "covered_count": len(covered),
        "missing_count": len(missing),
        "stale_count": len(stale),
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


def _forecast_calls(candidate_count: int) -> dict[str, Any]:
    pass2 = {
        "sec_company_tickers_mapping_calls": 1,
        "fmp_grades_calls": candidate_count,
        "sec_submissions_calls": candidate_count,
        "massive_reference_news_calls": candidate_count,
        "total_calls": 1 + (candidate_count * 3),
    }
    corporate_action = {
        "fmp_split_calls": candidate_count,
        "fmp_dividend_calls": candidate_count,
        "total_calls": candidate_count * 2,
        "corporate_action_reconciliation_performed_by_preflight": False,
    }
    momentum_refresh = {
        "massive_daily_aggregates_calls": candidate_count + len(BENCHMARK_SYMBOLS),
        "benchmark_symbols": list(BENCHMARK_SYMBOLS),
        "not_in_total_until_separate_price_packet_review": True,
    }
    total = pass2["total_calls"] + corporate_action["total_calls"]
    return {
        "families": {
            "pass2_source_packet": pass2,
            "corporate_action_live_half": corporate_action,
            "momentum_price_refresh_if_local_projection_missing": momentum_refresh,
        },
        "total_calls_for_full_candidate_cut": total,
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
) -> dict[str, Any]:
    eligible = list(artifact["eligible_tickers"])
    candidate_count = len(eligible)
    local_ready = (
        momentum_coverage["status"] == "full_coverage"
        and theme_coverage["status"] == "full_coverage"
    )
    status = "ready_for_reviewed_live_execution" if local_ready else "blocked_missing_local_inputs"
    momentum_coverage = dict(momentum_coverage, path=_repo_rel(momentum_path))
    theme_coverage = dict(theme_coverage, path=_repo_rel(theme_path))
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
        "endpoint_call_forecast": _forecast_calls(candidate_count),
        "execution_gate": {
            "ready_to_run_full_candidate_live_packet": local_ready,
            "block_reasons": [] if local_ready else ["missing_or_stale_local_score_projection_inputs"],
            "requires_separate_network_tool_approval": True,
            "requires_explicit_call_budget": True,
            "provider_selection_claimed": False,
            "corporate_action_reconciliation_claimed": False,
            "datahub_or_production_allowed": False,
            "ship_gate_evidence_allowed": False,
        },
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
            "This preflight performs no provider calls and writes no source packet; it only computes full-candidate readiness and call forecast.",
            "Full-candidate means the current Pass1-eligible candidate set, not full-market coverage evidence.",
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
    confirm_user_authorization: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if not confirm_user_authorization:
        raise FullCandidatePass2PreflightError("full-candidate Pass2 preflight requires explicit user authorization")
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
    eligible = list(artifact["eligible_tickers"])
    momentum_coverage = _projection_coverage(
        projection=_read_json(momentum_path),
        projection_name="momentum_projection",
        value_key="momentum_by_ticker",
        expected_tickers=eligible,
    )
    theme_coverage = _projection_coverage(
        projection=_read_json(theme_path),
        projection_name="theme_projection",
        value_key="theme_block_by_ticker",
        expected_tickers=eligible,
    )
    summary = _build_summary(
        generated_at=generated_at,
        candidate_path=candidate_path,
        momentum_path=momentum_path,
        theme_path=theme_path,
        summary_path=summary_resolved,
        artifact=artifact,
        momentum_coverage=momentum_coverage,
        theme_coverage=theme_coverage,
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
            confirm_user_authorization=args.confirm_user_authorization,
            generated_at=args.generated_at,
        )
    except FullCandidatePass2PreflightError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": summary["scope"]["status"],
                "eligible_count": summary["candidate_universe"]["eligible_count"],
                "forecast_calls": summary["endpoint_call_forecast"]["total_calls_for_full_candidate_cut"],
                "summary_path": summary["storage"]["tracked_summary_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
