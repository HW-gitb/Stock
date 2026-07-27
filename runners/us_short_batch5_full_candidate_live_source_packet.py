from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_catalyst import load_catalyst_governance  # noqa: E402
from engine.us_short_eligibility_gate import canonical_us_ticker, load_eligibility_governance  # noqa: E402
from engine.us_short_pass2_funnel import Pass2FunnelError, select_pass2_targets  # noqa: E402
from engine.us_short_projection_binding import (  # noqa: E402
    build_projection_binding,
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
from engine.us_short_fmp_analyst_grades import FmpGradesError, resolve_analyst_grade_actions  # noqa: E402
from engine.us_short_massive_news import MassiveNewsError, resolve_news_events  # noqa: E402
from engine.us_short_sec_offering_audit import (  # noqa: E402
    OfferingAuditError,
    build_offering_audit_from_sec_submissions,
)
from runners import us_egs_sample_validation as sample_validation  # noqa: E402
from runners import us_short_batch5_data_context as data_context_assembly  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402
from runners.us_short_batch5_data_context_source_packet import (  # noqa: E402
    FULL_CANDIDATE_LIVE_PROJECTION_BINDING,
    SourcePacketError,
    run_packet as run_local_source_packet,
    run_preflight as run_local_source_packet_preflight,
)


AUTHORIZATION_REF = "user_chat_20260706_us_short_full_candidate_live_source_packet"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_candidate_live_source_packet_summary.schema.json"
PREFLIGHT_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_candidate_pass2_preflight_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_full_candidate_live_source_packet_summary_20260706.json"
PREFLIGHT_SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_full_candidate_pass2_preflight_summary_20260706.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_full_candidate_live_source_packet_20260706")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
SOURCE_ARTIFACT_PREFIX = STATE_US_SHORT_DIR / "us_short_batch5_full_candidate_live_source_packet_20260706"
DEFAULT_OUTPUT_DATA_CONTEXT_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_full_candidate_live_source_packet_20260706_data_context.json"
)
DEFAULT_CONTEXT_COMPONENTS_OUTPUT_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_full_candidate_live_source_packet_20260706_context_components.json"
)
MASSIVE_NEWS_URL = "https://api.massive.com/v2/reference/news?ticker={ticker}&limit=10&apiKey={key}"
# Step 3 (R-USSHORT-BATCH5-MOMENTUM-TOPK-NARROWING-MISSING follow-on): the per-target split/dividend capture is
# offloaded from FMP to Massive so FMP stays under its 250/day free grade cap at K=200 (FMP per target drops 3->1,
# grades only). Endpoint paths confirmed by the 2026-07-07 live shape probe (GET /stocks/v1/{splits,dividends};
# Polygon-style {"results":[...]} envelope), NOT the Polygon /v3/reference/* a guess would have used.
MASSIVE_SPLITS_URL = "https://api.massive.com/stocks/v1/splits?ticker={ticker}&limit=10&apiKey={key}"
MASSIVE_DIVIDENDS_URL = "https://api.massive.com/stocks/v1/dividends?ticker={ticker}&limit=10&apiKey={key}"
FMP_FREE_DAILY_GRADE_CALL_CAP = 250   # mirror the preflight; the funnel target + within-cap invariant is RE-DERIVED here at the live boundary, not trusted from the preflight
# Mirror the preflight `_forecast_calls`: each Pass2 target costs 5 endpoint calls (3 source-packet: grades +
# submissions + reference-news; 2 corporate-action: splits + dividends) plus 1 shared SEC ticker->CIK mapping.
# The live-spend budget is RE-ANCHORED to the runner-RE-DERIVED target count (not the preflight-attested
# forecast/momentum_top_k), so a forged preflight cannot widen K/target_count without the operator independently
# authorizing the matching budget. Cross-checked against the preflight formula by test.
_SEC_TICKER_MAPPING_CALLS = 1
_PASS2_ENDPOINT_CALLS_PER_TARGET = 5
_EXECUTION_MODE_LIVE_PROVIDER_FETCH = "live_provider_fetch"
_EXECUTION_MODE_OFFLINE_REPLAY = "offline_replay"


class FullCandidateLiveSourcePacketError(ValueError):
    """The full-candidate live Pass2 source packet cannot be fetched or assembled safely."""


@dataclass
class HttpAttemptBudget:
    """Physical HTTP-attempt cap, distinct from the one-record-per-endpoint logical budget.

    A retry is allowed only when it leaves capacity for every still-reserved logical endpoint. This keeps a 429 from
    silently consuming the final planned call slot; more retries require an explicitly wider physical-attempt cap.
    """

    max_total_http_attempts: int
    used: int = 0

    def consume_required_attempt(self) -> None:
        if self.used >= self.max_total_http_attempts:
            raise FullCandidateLiveSourcePacketError(
                "physical HTTP-attempt budget would be exceeded before required endpoint fetch")
        self.used += 1

    def consume_retry_if_available(self, *, reserved_required_attempts: int) -> bool:
        if self.used + 1 + reserved_required_attempts > self.max_total_http_attempts:
            return False
        self.used += 1
        return True


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FullCandidateLiveSourcePacketError(f"failed to read JSON from {path}: {exc}") from exc


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
        raise FullCandidateLiveSourcePacketError(f"{field} must stay under the repository root") from exc
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


def _existing_file(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    if not resolved.exists() or not resolved.is_file():
        raise FullCandidateLiveSourcePacketError(f"{field} must be an existing file: {_display_path(resolved)}")
    return resolved


def _existing_state_json(path: Path | str, *, field: str) -> Path:
    resolved = _existing_file(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise FullCandidateLiveSourcePacketError(f"{field} must be a .json file")
    if not _git_ignored(resolved):
        raise FullCandidateLiveSourcePacketError(f"{field} must be gitignored")
    return resolved


def _validate_state_json_path(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise FullCandidateLiveSourcePacketError(f"{field} must be a .json path")
    if not _git_ignored(resolved):
        raise FullCandidateLiveSourcePacketError(f"{field} must be gitignored")
    return resolved


def _validate_source_artifact_prefix(prefix: Path | str) -> Path:
    resolved = _resolve_repo_path(prefix, field="source_artifact_prefix")
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError("source_artifact_prefix must stay under state/us_short/") from exc
    return resolved


def _source_paths(prefix: Path) -> dict[str, Path]:
    return {
        "candidate_subset": prefix.with_name(prefix.name + "_candidate_subset.json"),
        "offering_audit_source": prefix.with_name(prefix.name + "_offering_audit_source.json"),
        "analyst_grade_actions": prefix.with_name(prefix.name + "_analyst_grade_actions.json"),
        "massive_news_events": prefix.with_name(prefix.name + "_massive_news_events.json"),
        "theme_selection_contract": prefix.with_name(prefix.name + "_theme_selection_contract.json"),
        "corporate_action_capture": prefix.with_name(prefix.name + "_corporate_action_capture.json"),
        "momentum_projection": prefix.with_name(prefix.name + "_momentum_projection.json"),
        "theme_projection": prefix.with_name(prefix.name + "_theme_projection.json"),
        "source_packet": prefix.with_name(prefix.name + "_source_packet.json"),
    }


def _validate_raw_root(raw_root: Path | str) -> Path:
    resolved = _resolve_repo_path(raw_root, field="raw_root")
    approved = (ROOT / RAW_SAMPLE_REL_ROOT).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError(
            "raw_root must stay under provider_samples/us_short_batch5_full_candidate_live_source_packet_20260706/"
        ) from exc
    try:
        sample_validation.validate_raw_root(resolved)
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError(str(exc)) from exc
    return resolved


def _validate_summary_path(summary_path: Path | str) -> Path:
    resolved = _resolve_repo_path(summary_path, field="summary_path")
    if resolved.suffix != ".json":
        raise FullCandidateLiveSourcePacketError("summary_path must be a .json file")
    if resolved == SUMMARY_PATH.resolve():
        return resolved
    try:
        resolved.relative_to((ROOT / RAW_SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError(
            "summary_path must be the canonical tracked summary or under this runner's provider_samples folder"
        ) from exc
    if not _git_ignored(resolved):
        raise FullCandidateLiveSourcePacketError("non-canonical summary_path must be gitignored")
    return resolved


def _validate_preflight_path(preflight_summary_path: Path | str) -> Path:
    resolved = _existing_file(preflight_summary_path, field="preflight_summary_path")
    if resolved == PREFLIGHT_SUMMARY_PATH.resolve():
        return resolved
    try:
        resolved.relative_to((ROOT / "provider_samples/us_short_batch5_full_candidate_pass2_preflight_20260706").resolve())
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError(
            "preflight_summary_path must be the canonical tracked summary or under its provider_samples folder"
        ) from exc
    if not _git_ignored(resolved):
        raise FullCandidateLiveSourcePacketError("non-canonical preflight_summary_path must be gitignored")
    return resolved


def _provider_samples_gitignored() -> bool:
    gitignore = ROOT / ".gitignore"
    return gitignore.exists() and "provider_samples/" in gitignore.read_text(encoding="utf-8")


def _date8_to_ymd(value: Any) -> str:
    if not (type(value) is str and len(value) == 8 and value.isascii() and value.isdigit()):
        raise FullCandidateLiveSourcePacketError("expected_decision_date must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError("expected_decision_date must be a real calendar date") from exc


def _valid_observed_at(value: str) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _validate_json_schema(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise FullCandidateLiveSourcePacketError(f"jsonschema is required for {label} validation") from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise FullCandidateLiveSourcePacketError(f"{label} failed schema validation: {joined}")


def _approval_binding(approval: Any) -> dict[str, Any]:
    from runners.us_short_weekly_capstone import Pass2BudgetApproval

    if not isinstance(approval, Pass2BudgetApproval):
        raise FullCandidateLiveSourcePacketError("finalized Pass2 budget approval is required")
    try:
        return Pass2BudgetApproval.validate_binding_summary(approval.binding_summary())
    except (TypeError, ValueError) as exc:
        raise FullCandidateLiveSourcePacketError(str(exc)) from exc


def _load_ready_preflight(
    preflight_summary_path: Path,
    expected_total_call_budget: int,
    budget_approval: Any = None,
    *,
    require_budget_approval: bool = True,
) -> dict[str, Any]:
    if type(expected_total_call_budget) is not int or expected_total_call_budget <= 0:
        raise FullCandidateLiveSourcePacketError("expected_total_call_budget must be a positive integer")
    preflight = _read_json(preflight_summary_path)
    _validate_json_schema(preflight, PREFLIGHT_SCHEMA_PATH, label="full-candidate preflight summary")
    status = ((preflight.get("scope") or {}).get("status"))
    gate = preflight.get("execution_gate") or {}
    local = preflight.get("local_input_coverage") or {}
    forecast = ((preflight.get("endpoint_call_forecast") or {}).get("total_calls_for_pass2_target_cut"))
    targets = preflight.get("pass2_target_universe") or {}
    if targets.get("selection_mode") != "momentum_theme_top_k_plus_catalyst_recall_plus_forced_holdings":
        raise FullCandidateLiveSourcePacketError("preflight uses a legacy unbound Pass2 selection contract")
    if any(
        type(targets.get(field)) is not str or len(targets[field]) != 64
        for field in ("forced_holding_tickers_sha256", "catalyst_recall_tickers_sha256")
    ):
        raise FullCandidateLiveSourcePacketError("preflight lacks exact holding/recall lane bindings")
    for component in ("momentum_projection", "theme_projection"):
        coverage = local.get(component) or {}
        if not (
            type(coverage.get("artifact_sha256")) is str
            and len(coverage["artifact_sha256"]) == 64
            and type(coverage.get("producer_id")) is str
            and coverage["producer_id"]
        ):
            raise FullCandidateLiveSourcePacketError("preflight score projection lacks required artifact/source binding")
    if status != "ready_for_reviewed_live_execution" or gate.get("ready_to_run_full_candidate_live_packet") is not True:
        raise FullCandidateLiveSourcePacketError("preflight summary is not ready for reviewed live execution")
    if local.get("all_required_local_inputs_cover_candidates") is not True:
        raise FullCandidateLiveSourcePacketError("preflight local inputs are not fully covered")
    if targets.get("target_count") <= 0 or targets.get("fmp_grade_calls_within_free_daily_cap") is not True:
        raise FullCandidateLiveSourcePacketError("preflight Pass2 target universe is not free-budget ready")
    if forecast != expected_total_call_budget:
        raise FullCandidateLiveSourcePacketError(
            f"expected call budget must match preflight forecast: {expected_total_call_budget} != {forecast}"
        )
    actual_binding = gate.get("approval_binding")
    if require_budget_approval and budget_approval is None:
        raise FullCandidateLiveSourcePacketError(
            "finalized preflight requires the matching Pass2 budget approval before any provider request"
        )
    if budget_approval is not None:
        expected_binding = _approval_binding(budget_approval)
        if actual_binding != expected_binding:
            raise FullCandidateLiveSourcePacketError(
                "preflight approval binding does not match the stage context approval"
            )
        if expected_binding["exact_pass2_calls"] != expected_total_call_budget:
            raise FullCandidateLiveSourcePacketError(
                "budget exceeded before provider request: approved budget "
                f"{expected_binding['exact_pass2_calls']}, stage requires {expected_total_call_budget}"
            )
    return preflight


def _candidate_subset_artifact(
    *,
    candidate_artifact_path: Path,
    expected_decision_date: str,
    eligibility_governance: dict[str, Any],
    selected_symbols: list[str],
) -> dict[str, Any]:
    artifact = _read_json(candidate_artifact_path)
    try:
        artifact = universe_fetch.validate_candidate_artifact(
            artifact,
            expected_decision_date=expected_decision_date,
            governance=eligibility_governance,
        )
    except Exception as exc:
        raise FullCandidateLiveSourcePacketError(f"candidate artifact failed validation: {exc}") from exc
    rows_by_ticker = {row["ticker"]: row for row in artifact["rows"]}
    eligible = list(artifact["eligible_tickers"])
    eligible_set = set(eligible)
    if type(selected_symbols) is not list or not selected_symbols:
        raise FullCandidateLiveSourcePacketError("selected_symbols must be a non-empty exact list")
    seen: set[str] = set()
    for symbol in selected_symbols:
        if type(symbol) is not str or symbol in seen:
            raise FullCandidateLiveSourcePacketError("selected_symbols must contain unique exact ticker strings")
        if symbol not in eligible_set or symbol not in rows_by_ticker:
            raise FullCandidateLiveSourcePacketError("selected_symbols must stay inside the reviewed eligible candidate set")
        seen.add(symbol)
    rows = [rows_by_ticker[ticker] for ticker in selected_symbols]
    adv_window = artifact["adv_window"]
    subset = universe_fetch.build_candidate_artifact(
        rows=rows,
        decision_date=artifact["decision_date"],
        price_basis_date=artifact["price_basis_date"],
        used_date=artifact["used_date"],
        observed_window_dates=adv_window["observed_window_dates"],
        generated_at=artifact["generated_at"],
        calendar_verification_status=artifact["calendar_verification_status"],
        window_days=adv_window["trading_days"],
        min_days=adv_window["min_days_required"],
    )
    try:
        return universe_fetch.validate_candidate_artifact(
            subset,
            expected_decision_date=expected_decision_date,
            governance=eligibility_governance,
        )
    except Exception as exc:
        raise FullCandidateLiveSourcePacketError(f"candidate subset failed validation: {exc}") from exc


def _assert_endpoint_budget(records: list[sample_validation.FetchRecord], max_total_endpoint_calls: int) -> None:
    try:
        sample_validation.assert_endpoint_budget_available(records, max_total_endpoint_calls)
    except RuntimeError as exc:
        raise FullCandidateLiveSourcePacketError(
            f"budget exceeded before provider request: approved budget {max_total_endpoint_calls}; {exc}"
        ) from exc


def _fmp_stable_url(path_template: str, symbol: str, api_key: str) -> str:
    return sample_validation.fmp_url(path_template, symbol, {}, api_key, endpoint_mode="stable")


_MAX_RETRIES_PER_CALL_CAP = 6   # hard ceiling on the per-call 429 retry count (bounds worst-case physical spend)


def _fetch_with_retry(
    client: sample_validation.JsonHttpClient,
    *,
    url: str,
    provider_id: str,
    endpoint_family: str,
    symbol: str | None,
    raw_root: Path,
    headers: dict[str, str],
    pace_seconds: float,
    max_retries: int,
    retry_backoff_seconds: float,
    retry_stats: dict[str, int],
    attempt_budget: HttpAttemptBudget,
    reserved_required_attempts: int,
) -> sample_validation.FetchRecord:
    """Fetch one endpoint with bounded retry ONLY on HTTP 429 (rate-limit). A 402 paywall / 404 / any non-429
    outcome is returned as-is and NOT retried — retrying a paywall is pointless, and it makes a rate-limit
    (recoverable by waiting) observably distinct from a paywall/quota (not). Retries happen INSIDE this call (each
    physical attempt overwrites the same raw path); only the FINAL FetchRecord is returned, so the caller's LOGICAL
    endpoint-record count stays unchanged. Every initial call and retry consumes the separately explicit physical
    HTTP-attempt budget; a retry is skipped when it would steal capacity reserved for the remaining logical calls.
    `pace_seconds` spaces consecutive endpoints AFTER the final attempt to stay under the free-tier rate.
    `retry_stats["used"]` accumulates actual physical retries for reporting."""
    attempt_budget.consume_required_attempt()
    record = sample_validation.fetch_and_store(
        client, url=url, provider_id=provider_id, endpoint_family=endpoint_family,
        symbol=symbol, raw_root=raw_root, headers=headers,
    )
    attempt = 0
    while (not record.ok) and record.http_status == 429 and attempt < max_retries:
        if not attempt_budget.consume_retry_if_available(
            reserved_required_attempts=reserved_required_attempts,
        ):
            break
        time.sleep(retry_backoff_seconds * (2 ** attempt))   # exponential backoff on rate-limit
        retry_stats["used"] += 1
        attempt += 1
        record = sample_validation.fetch_and_store(
            client, url=url, provider_id=provider_id, endpoint_family=endpoint_family,
            symbol=symbol, raw_root=raw_root, headers=headers,
        )
    if pace_seconds:
        time.sleep(pace_seconds)
    return record


def _fetch_live_records(
    *,
    selected_symbols: list[str],
    raw_root: Path,
    client: sample_validation.JsonHttpClient,
    fmp_env: sample_validation.EnvValue,
    sec_env: sample_validation.EnvValue,
    massive_env: sample_validation.EnvValue,
    sec_sleep_seconds: float,
    max_total_endpoint_calls: int,
    max_total_http_attempts: int,
    provider_pace_seconds: float,
    max_retries_per_call: int,
    retry_backoff_seconds: float,
    fetch_fmp_grades: bool,
    budget_approval: Any = None,
    require_budget_approval: bool = True,
) -> tuple[list[sample_validation.FetchRecord], dict[str, str], int, int]:
    binding = None
    if require_budget_approval or budget_approval is not None:
        binding = _approval_binding(budget_approval)
        if binding["exact_pass2_calls"] != max_total_endpoint_calls:
            raise FullCandidateLiveSourcePacketError(
                "budget exceeded before provider request: approved budget "
                f"{binding['exact_pass2_calls']}, stage requires {max_total_endpoint_calls}"
            )
    records: list[sample_validation.FetchRecord] = []
    retry_stats = {"used": 0}
    attempt_budget = HttpAttemptBudget(max_total_http_attempts=max_total_http_attempts)

    def _fetch_required(**kwargs: Any) -> sample_validation.FetchRecord:
        attempt_budget.consume_required_attempt()
        return sample_validation.fetch_and_store(client, **kwargs)

    def _reserved_after_current() -> int:
        # The forecast is deliberately conservative when a CIK is missing: preserving all planned endpoints is safer
        # than spending an unapproved retry merely because a later SEC submission might be skipped.
        return max_total_endpoint_calls - (len(records) + 1)

    _assert_endpoint_budget(records, max_total_endpoint_calls)
    mapping = _fetch_required(
        url=sample_validation.sec_url("company_tickers_mapping"),
        provider_id="sec_edgar",
        endpoint_family="company_tickers_mapping",
        symbol=None,
        raw_root=raw_root,
        headers={"User-Agent": sec_env.value, "Host": "www.sec.gov"},
    )
    records.append(mapping)
    cik_by_symbol = sample_validation.parse_sec_cik_map(mapping.payload, selected_symbols)

    fmp_headers = {"User-Agent": "StockSystem/0.1 us-short-batch5-full-candidate-live-source-packet"}
    sec_headers = {"User-Agent": sec_env.value, "Host": "data.sec.gov"}
    massive_headers = {"User-Agent": "StockSystem/0.1 us-short-batch5-full-candidate-live-source-packet"}
    for symbol in selected_symbols:
        if fetch_fmp_grades:
            _assert_endpoint_budget(records, max_total_endpoint_calls)
            records.append(
                _fetch_with_retry(
                    client,
                    url=_fmp_stable_url("grades", symbol, fmp_env.value),
                    provider_id="financial_modeling_prep",
                    endpoint_family="grades",
                    symbol=symbol,
                    raw_root=raw_root,
                    headers=fmp_headers,
                    pace_seconds=provider_pace_seconds,
                    max_retries=max_retries_per_call,
                    retry_backoff_seconds=retry_backoff_seconds,
                    retry_stats=retry_stats,
                    attempt_budget=attempt_budget,
                    reserved_required_attempts=_reserved_after_current(),
                )
            )

        cik10 = cik_by_symbol.get(symbol)
        if cik10:
            _assert_endpoint_budget(records, max_total_endpoint_calls)
            time.sleep(sec_sleep_seconds)
            records.append(
                _fetch_required(
                    url=sample_validation.sec_url("submissions", cik10),
                    provider_id="sec_edgar",
                    endpoint_family="submissions",
                    symbol=symbol,
                    raw_root=raw_root,
                    headers=sec_headers,
                )
            )

        _assert_endpoint_budget(records, max_total_endpoint_calls)
        records.append(
            _fetch_with_retry(
                client,
                url=MASSIVE_NEWS_URL.format(ticker=symbol, key=massive_env.value),
                provider_id="massive",
                endpoint_family="reference_news",
                symbol=symbol,
                raw_root=raw_root,
                headers=massive_headers,
                pace_seconds=provider_pace_seconds,
                max_retries=max_retries_per_call,
                retry_backoff_seconds=retry_backoff_seconds,
                retry_stats=retry_stats,
                attempt_budget=attempt_budget,
                reserved_required_attempts=_reserved_after_current(),
            )
        )

        _assert_endpoint_budget(records, max_total_endpoint_calls)
        records.append(
            _fetch_with_retry(
                client,
                url=MASSIVE_SPLITS_URL.format(ticker=symbol, key=massive_env.value),
                provider_id="massive",
                endpoint_family="stock_splits",
                symbol=symbol,
                raw_root=raw_root,
                headers=massive_headers,
                pace_seconds=provider_pace_seconds,
                max_retries=max_retries_per_call,
                retry_backoff_seconds=retry_backoff_seconds,
                retry_stats=retry_stats,
                attempt_budget=attempt_budget,
                reserved_required_attempts=_reserved_after_current(),
            )
        )

        _assert_endpoint_budget(records, max_total_endpoint_calls)
        records.append(
            _fetch_with_retry(
                client,
                url=MASSIVE_DIVIDENDS_URL.format(ticker=symbol, key=massive_env.value),
                provider_id="massive",
                endpoint_family="dividends",
                symbol=symbol,
                raw_root=raw_root,
                headers=massive_headers,
                pace_seconds=provider_pace_seconds,
                max_retries=max_retries_per_call,
                retry_backoff_seconds=retry_backoff_seconds,
                retry_stats=retry_stats,
                attempt_budget=attempt_budget,
                reserved_required_attempts=_reserved_after_current(),
            )
        )
    validator = getattr(client, "assert_all_loaded_consumed", None)
    if callable(validator):
        validator()
    return records, cik_by_symbol, retry_stats["used"], attempt_budget.used


def _record_map(records: list[sample_validation.FetchRecord]) -> dict[tuple[str, str, str | None], sample_validation.FetchRecord]:
    return {(record.provider_id, record.endpoint_family, record.symbol): record for record in records}


def _target_scoped_projection(
    *,
    projection_path: Path,
    component: str,
    value_key: str,
    selected_symbols: list[str],
    generated_at: str,
    candidate_artifact: dict[str, Any],
) -> dict[str, Any]:
    raw = _read_json(projection_path)
    if type(raw) is not dict:
        raise FullCandidateLiveSourcePacketError(f"{value_key} projection must be an exact dict")
    values = raw.get(value_key)
    neutral = raw.get("neutral_fill_tickers")
    coverage = raw.get("coverage")
    if type(values) is not dict or type(neutral) is not list or type(coverage) is not dict:
        raise FullCandidateLiveSourcePacketError(f"{value_key} projection has an invalid shape")
    if not all(type(key) is str for key in values) or not all(type(key) is str for key in coverage):
        raise FullCandidateLiveSourcePacketError(f"{value_key} projection keys must be exact strings")
    if not all(type(ticker) is str for ticker in neutral):
        raise FullCandidateLiveSourcePacketError(f"{value_key} neutral_fill_tickers must contain exact strings")
    neutral_set = set(neutral)
    scoped_values: dict[str, Any] = {}
    scoped_neutral: list[str] = []
    scoped_coverage: dict[str, Any] = {}
    seen: set[str] = set()
    for symbol in selected_symbols:
        if symbol in seen:
            raise FullCandidateLiveSourcePacketError("selected_symbols contains a duplicate")
        seen.add(symbol)
        if symbol not in coverage:
            raise FullCandidateLiveSourcePacketError(f"{value_key} coverage is missing a selected target")
        if symbol in values:
            scoped_values[symbol] = values[symbol]
        elif symbol in neutral_set:
            scoped_neutral.append(symbol)
        else:
            raise FullCandidateLiveSourcePacketError(f"{value_key} projection partition misses a selected target")
        scoped_coverage[symbol] = coverage[symbol]
    scoped = {
        value_key: scoped_values,
        "neutral_fill_tickers": scoped_neutral,
        "coverage": scoped_coverage,
        "target_count": len(selected_symbols),
        "scored_count": len(scoped_values),
    }
    scoped["source_binding"] = build_projection_binding(
        component=component,
        producer_id="us_short_batch5_full_candidate_live_source_packet",
        generated_at=raw["source_binding"]["generated_at"],
        expected_decision_date=candidate_artifact["decision_date"],
        candidate_price_basis_date=candidate_artifact["price_basis_date"],
        source_as_of=candidate_artifact["used_date"],
        target_tickers=selected_symbols,
        projection=scoped,
        source_artifact_paths={f"parent_{component}_projection": projection_path},
    )
    return scoped


def _empty_provenance(
    *,
    provider_id: str,
    endpoint_or_filing_type: str,
    source_as_of: str,
    observed_at: str,
    coverage_status: str,
    parser_status: str,
    lineage_id: str,
) -> dict[str, Any]:
    return {
        "provider_id": provider_id,
        "endpoint_or_filing_type": endpoint_or_filing_type,
        "source_as_of": source_as_of,
        "observed_at": observed_at,
        "coverage_status": coverage_status,
        "parser_status": parser_status,
        "lineage_ref": f"{provider_id}:{endpoint_or_filing_type}:{source_as_of}#{lineage_id}",
    }


def _payload_list_status(record: sample_validation.FetchRecord | None) -> tuple[list[Any], str, str]:
    if record is None or not record.ok:
        return [], "missing", "failed"
    if isinstance(record.payload, list):
        return record.payload, "full", "ok"
    return [], "partial", "failed"


def _massive_news_payload_status(record: sample_validation.FetchRecord | None) -> tuple[list[Any], str, str]:
    if record is None or not record.ok:
        return [], "missing", "failed"
    if isinstance(record.payload, dict) and isinstance(record.payload.get("results"), list):
        return record.payload["results"], "full", "ok"
    if isinstance(record.payload, list):
        return record.payload, "full", "ok"
    return [], "partial", "failed"


def _resolved_source_artifacts(
    *,
    selected_symbols: list[str],
    source_as_of: str,
    observed_at: str,
    records: list[sample_validation.FetchRecord],
) -> dict[str, Any]:
    by_key = _record_map(records)
    submissions_by_ticker: dict[str, Any] = {}
    missing_sec: list[str] = []
    for symbol in selected_symbols:
        rec = by_key.get(("sec_edgar", "submissions", symbol))
        if rec is not None and rec.ok and isinstance(rec.payload, dict):
            submissions_by_ticker[symbol] = rec.payload
        else:
            missing_sec.append(symbol)
    try:
        offering_source = build_offering_audit_from_sec_submissions(
            as_of=source_as_of,
            observed_at=observed_at,
            submissions_by_ticker=submissions_by_ticker,
        )
    except OfferingAuditError as exc:
        raise FullCandidateLiveSourcePacketError(f"SEC offering source rejected: {exc}") from exc
    for symbol in missing_sec:
        offering_source["excluded"][symbol] = {"active_offering": "coverage=missing/parser=failed"}

    grades_by_ticker: dict[str, Any] = {}
    news_by_ticker: dict[str, Any] = {}
    for symbol in selected_symbols:
        grade_records, grade_coverage, grade_parser = _payload_list_status(
            by_key.get(("financial_modeling_prep", "grades", symbol))
        )
        grades_by_ticker[symbol] = {
            "records": grade_records,
            "provenance": _empty_provenance(
                provider_id="fmp",
                endpoint_or_filing_type="grades",
                source_as_of=source_as_of,
                observed_at=observed_at,
                coverage_status=grade_coverage,
                parser_status=grade_parser,
                lineage_id=f"{symbol.lower()}grades",
            ),
        }

        news_records, news_coverage, news_parser = _massive_news_payload_status(
            by_key.get(("massive", "reference_news", symbol))
        )
        news_by_ticker[symbol] = {
            "records": news_records,
            "provenance": _empty_provenance(
                provider_id="massive",
                endpoint_or_filing_type="reference_news",
                source_as_of=source_as_of,
                observed_at=observed_at,
                coverage_status=news_coverage,
                parser_status=news_parser,
                lineage_id=f"{symbol.lower()}news",
            ),
        }

    try:
        analyst_grade_actions = resolve_analyst_grade_actions(
            as_of=source_as_of,
            grades_by_ticker=grades_by_ticker,
        )
        massive_news_events = resolve_news_events(
            as_of=source_as_of,
            news_by_ticker=news_by_ticker,
        )
    except (FmpGradesError, MassiveNewsError) as exc:
        raise FullCandidateLiveSourcePacketError(f"Pass2 source resolver rejected live payloads: {exc}") from exc
    return {
        "offering_audit_source": offering_source,
        "analyst_grade_actions": analyst_grade_actions,
        "massive_news_events": massive_news_events,
    }


def _holding_rows_from_records(
    *,
    holding_symbols: list[str],
    source_as_of: str,
    observed_at: str,
    records: list[sample_validation.FetchRecord],
) -> list[dict[str, Any]]:
    if not holding_symbols:
        return []
    offering = _resolved_source_artifacts(
        selected_symbols=holding_symbols,
        source_as_of=source_as_of,
        observed_at=observed_at,
        records=records,
    )["offering_audit_source"]
    rows: list[dict[str, Any]] = []
    for ticker in holding_symbols:
        if ticker in offering["signals"]:
            signals = {"active_offering": dict(offering["signals"][ticker]["active_offering"])}
        elif ticker in offering["checked"]:
            signals = {}
        else:
            signals = {"critical_data_missing": True}
        rows.append({"ticker": ticker, "signals": signals})
    return rows


def _payload_shape_from_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return {"kind": "list", "row_count": len(payload)}
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            return {"kind": "object_results", "row_count": len(results)}
        recent = ((payload.get("filings") or {}).get("recent") or {})
        if isinstance(recent, dict) and isinstance(recent.get("form"), list):
            return {"kind": "sec_submissions", "row_count": len(recent["form"])}
        return {"kind": "object", "row_count": None}
    if payload is None:
        return {"kind": "null", "row_count": None}
    return {"kind": "scalar", "row_count": None}


def _payload_shape(record: sample_validation.FetchRecord) -> dict[str, Any]:
    return _payload_shape_from_payload(record.payload)


def _summarize_endpoint(record: sample_validation.FetchRecord) -> dict[str, Any]:
    return {
        "provider_id": record.provider_id,
        "endpoint_family": record.endpoint_family,
        "symbol": record.symbol,
        "status": "success" if record.ok else "error",
        "http_status": record.http_status,
        "error_type": record.error_type,
        "raw_sample_ref": record.raw_sample_ref,
        "raw_sample_ref_gitignored": record.raw_sample_ref.startswith(str(RAW_SAMPLE_REL_ROOT).replace("\\", "/")),
        "payload_shape": _payload_shape(record),
    }


def _event_count(record: sample_validation.FetchRecord | None) -> int:
    if record is None or not record.ok:
        return 0
    shape = _payload_shape(record)
    return int(shape["row_count"] or 0)


def _build_corporate_action_capture(
    *,
    generated_at: str,
    expected_decision_date: str,
    source_as_of: str,
    observed_at: str,
    selected_symbols: list[str],
    records: list[sample_validation.FetchRecord],
) -> dict[str, Any]:
    by_key = _record_map(records)
    by_ticker: dict[str, Any] = {}
    split_calls = 0
    dividend_calls = 0
    split_events = 0
    dividend_events = 0
    for symbol in selected_symbols:
        split_rec = by_key.get(("massive", "stock_splits", symbol))
        dividend_rec = by_key.get(("massive", "dividends", symbol))
        split_count = _event_count(split_rec)
        dividend_count = _event_count(dividend_rec)
        split_calls += 1 if split_rec is not None else 0
        dividend_calls += 1 if dividend_rec is not None else 0
        split_events += split_count
        dividend_events += dividend_count
        by_ticker[symbol] = {
            "split_endpoint": _summarize_endpoint(split_rec) if split_rec is not None else None,
            "dividend_endpoint": _summarize_endpoint(dividend_rec) if dividend_rec is not None else None,
            "split_event_count": split_count,
            "dividend_event_count": dividend_count,
        }
    return {
        "schema_name": "us_short_batch5_corporate_action_live_capture",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "decision_clock": {
            "expected_decision_date": expected_decision_date,
            "source_as_of": source_as_of,
            "observed_at": observed_at,
        },
        "scope": {
            "provider_calls_performed": True,
            "raw_payload_storage_performed": True,
            "corporate_action_reconciliation_performed": False,
            "return_calculation_performed": False,
            "paper_gate_confirmation_claimed": False,
            "ship_gate_or_production_authorized": False,
        },
        "aggregate_counts": {
            "ticker_count": len(selected_symbols),
            "split_endpoint_call_count": split_calls,
            "dividend_endpoint_call_count": dividend_calls,
            "split_event_count": split_events,
            "dividend_event_count": dividend_events,
        },
        "by_ticker": by_ticker,
        "limitations": [
            "This artifact captures split/dividend endpoint response shapes and raw refs only.",
            "It does not reconcile corporate actions to prices, calculate returns, or confirm paper-performance evaluability.",
        ],
    }


def _industry_ids_from_sector_map(classification: Any, *, fallback: dict[str, str], tickers: list[str]) -> dict[str, str]:
    """Map a `{sector_by_ticker: {...}}` classification onto `industry:<sector>` ids, keeping the isolated
    `industry:unclassified:<ticker>` fallback for any ticker the classification does not cover."""
    sectors = classification.get("sector_by_ticker") if type(classification) is dict else None
    if type(sectors) is not dict:
        raise FullCandidateLiveSourcePacketError("sector-classification packet lacks sector_by_ticker")
    identities = dict(fallback)
    for ticker in tickers:
        sector = sectors.get(ticker)
        if type(sector) is str and sector.strip():
            identities[ticker] = f"industry:{sector.strip().casefold()}"
    return identities


def _theme_contract_industry_ids(
    *,
    parent_theme_projection_path: Path,
    tickers: list[str],
    classification_packet_path: Path | None = None,
) -> dict[str, str]:
    """Return source-bound industry identities, falling back to isolated neutral identities only when unavailable.

    The full/capstone pipeline supplies the run's SIC packet directly via ``classification_packet_path``: the
    projection-inputs theme binding intentionally carries only candidate/source-theme roles (not the
    sector_classification role), so the merged theme this runner reads never re-exposes it. Using the packet the
    SIC stage already produced gives the contract real ``industry:<sector>`` identities — so the §4.5 same-theme
    seat cap groups by real industry (not per-ticker singletons) once a >no_strong_theme seat budget is enabled —
    instead of always falling back. A caller that instead binds the classification into the theme projection
    itself may omit the path and use that SHA-verified binding.
    """
    fallback = {ticker: f"industry:unclassified:{ticker.casefold()}" for ticker in tickers}
    if classification_packet_path is not None:
        classification = _read_json(
            _existing_state_json(classification_packet_path, field="sector_classification_packet_path"))
        return _industry_ids_from_sector_map(classification, fallback=fallback, tickers=tickers)
    parent = _read_json(parent_theme_projection_path)
    binding = parent.get("source_binding") if type(parent) is dict else None
    artifacts = binding.get("source_artifacts") if type(binding) is dict else None
    if type(artifacts) is not list:
        return fallback
    matches = [item for item in artifacts if type(item) is dict and item.get("role") == "sector_classification_packet"]
    if not matches:
        return fallback
    if len(matches) != 1:
        raise FullCandidateLiveSourcePacketError("theme projection has duplicate sector-classification bindings")
    artifact = matches[0]
    if set(artifact) != {"role", "path", "sha256"} or type(artifact["path"]) is not str \
            or type(artifact["sha256"]) is not str:
        raise FullCandidateLiveSourcePacketError("theme projection sector-classification binding is malformed")
    classification_path = _existing_state_json(artifact["path"], field="theme_projection.sector_classification_packet")
    if file_sha256(classification_path) != artifact["sha256"]:
        raise FullCandidateLiveSourcePacketError("theme projection sector-classification binding changed")
    return _industry_ids_from_sector_map(_read_json(classification_path), fallback=fallback, tickers=tickers)


def _validate_full_overextension_before_funnel(
    *,
    overextension_projection_path: Path | None,
    candidate_artifact_path: Path,
    expected_decision_date: str,
    eligibility_governance: dict[str, Any],
) -> dict[str, Any] | None:
    """Bind the full eligible universe before deriving a bounded Pass2 target."""
    if overextension_projection_path is None:
        return None
    try:
        return data_context_assembly.validate_overextension_projection(
            _read_json(overextension_projection_path),
            candidate_artifact=_read_json(candidate_artifact_path),
            expected_decision_date=expected_decision_date,
            eligibility_governance=eligibility_governance,
        )
    except data_context_assembly.DataContextAssemblyError as exc:
        raise FullCandidateLiveSourcePacketError(
            f"cannot bind full eligible universe to overextension source: {exc}"
        ) from exc


def _build_theme_selection_contract(
    *,
    candidate_subset: dict[str, Any],
    eligibility_governance: dict[str, Any],
    expected_decision_date: str,
    theme_opportunity_state: str,
    parent_theme_projection_path: Path,
    target_theme_projection: dict[str, Any],
    resolved_sources: dict[str, Any],
    catalyst_recall_tickers: list[str],
    validated_full_overextension: dict[str, Any] | None,
    classification_packet_path: Path | None = None,
) -> dict[str, Any]:
    """Materialize the current Pass2-clean theme contract from this run's bound inputs.

    The final selection set is only knowable after the offering-audit source resolves, so this is deliberately
    produced after the bounded fetch and before the local source packet is assembled.  It cannot be a stale
    operator input or a pre-run sidecar.
    """
    try:
        prepared = data_context_assembly._prepare_context_inputs(
            candidate_artifact=candidate_subset,
            expected_decision_date=expected_decision_date,
            eligibility_governance=eligibility_governance,
            candidate_pass2_signals=None,
            pass2_sources={"offering_audit": resolved_sources["offering_audit_source"]},
            catalyst_recall_feed=catalyst_recall_tickers or None,
        )
    except data_context_assembly.DataContextAssemblyError as exc:
        raise FullCandidateLiveSourcePacketError(
            f"cannot build theme selection contract from resolved Pass2 sources: {exc}"
        ) from exc
    pass2_clean = prepared["pass2_clean"]
    theme_values = target_theme_projection.get("theme_block_by_ticker")
    theme_coverage = target_theme_projection.get("coverage")
    if type(theme_values) is not dict or type(theme_coverage) is not dict:
        raise FullCandidateLiveSourcePacketError("target theme projection cannot build a selection contract")
    parent_theme_projection = _read_json(parent_theme_projection_path)
    audit_theme_values = parent_theme_projection.get("theme_block_by_ticker")
    if type(audit_theme_values) is not dict or not audit_theme_values:
        raise FullCandidateLiveSourcePacketError(
            "parent theme projection cannot build the full-universe hot-excluded audit"
        )
    audit_scores: dict[str, float] = {}
    for raw_ticker, raw_score in audit_theme_values.items():
        ticker = canonical_us_ticker(raw_ticker)
        if ticker is None:
            raise FullCandidateLiveSourcePacketError("parent theme projection has an invalid audit ticker")
        if type(raw_score) not in (int, float) or isinstance(raw_score, bool) \
                or not math.isfinite(float(raw_score)) or float(raw_score) < 0.0:
            raise FullCandidateLiveSourcePacketError("parent theme projection has an invalid audit score")
        if ticker in audit_scores:
            raise FullCandidateLiveSourcePacketError("parent theme projection has duplicate audit tickers")
        audit_scores[ticker] = float(raw_score)
    # Theme-block values are already 0-100 percentile scores.  The governance leaves the forward cutoff tunable;
    # the current producer uses percentile score >=80 and binds that cutoff plus the full projection into the
    # contract digest.  Re-percentiling these already-percentiled values would mislabel a flat 50-score week hot.
    hot_audit_threshold = 80.0
    identities = _theme_contract_industry_ids(
        parent_theme_projection_path=parent_theme_projection_path,
        tickers=pass2_clean,
        classification_packet_path=classification_packet_path,
    )
    overextension_states = {ticker: "none" for ticker in pass2_clean}
    if validated_full_overextension is not None:
        for ticker in pass2_clean:
            try:
                overextension_states[ticker] = validated_full_overextension["overextension_by_ticker"][ticker][
                    "overextension_state"
                ]
            except (KeyError, TypeError) as exc:
                raise FullCandidateLiveSourcePacketError(
                    "overextension source is missing a Pass2-clean theme-contract ticker"
                ) from exc
    per_ticker: dict[str, dict[str, Any]] = {}
    for ticker in pass2_clean:
        score = theme_values.get(ticker, 0.0)
        if type(score) not in (int, float) or isinstance(score, bool) or not math.isfinite(float(score)):
            raise FullCandidateLiveSourcePacketError("target theme projection score is invalid for theme contract")
        if ticker not in theme_coverage:
            raise FullCandidateLiveSourcePacketError("target theme projection coverage is missing a Pass2-clean ticker")
        per_ticker[ticker] = {
            "theme_id": identities[ticker],
            "theme_source": "industry_heat_v1",
            "theme_lifecycle_state": "confirmed_active",
            "theme_leader_rs": float(score),
            "membership_origin": "automatic_discovery",
            "market_confirmed": True,
            "individual_theme_gate_passed": True,
            "overextension_state": overextension_states[ticker],
            # No reviewed cross-industry macro mapping exists in this source packet.  Keep the source fact
            # explicit and conservative instead of letting the bridge guess from a theme label.
            "macro_cluster": "unclassified_conservative",
        }
    return {
        "as_of": expected_decision_date,
        "mode": "industry_heat_v1_cross_industry_disabled",
        "cross_industry_provisional_enabled": False,
        "theme_opportunity_state": theme_opportunity_state,
        "hot_excluded_audit": {
            "heat_threshold": hot_audit_threshold,
            "per_ticker": audit_scores,
        },
        "per_ticker": per_ticker,
    }


def _build_local_source_packet(
    *,
    generated_at: str,
    expected_decision_date: str,
    theme_opportunity_state: str,
    paths: dict[str, Path],
    momentum_projection_path: Path,
    theme_projection_path: Path,
    overextension_projection_path: Path | None,
    overextension_candidate_artifact_path: Path | None,
    yfinance_grade_actions_path: Path | None,
    output_data_context_path: Path,
    context_components_output_path: Path | None,
    holdings: list[dict[str, Any]],
    catalyst_recall_feed: list[str],
    theme_soft_boost_enabled: bool,
    soft_discovery_stage_result: dict[str, Any] | None,
    provisional_theme_stage_receipt_path: Path | None,
    provisional_theme_validation_path: Path | None,
    original_candidate_artifact_path: Path | None,
    classification_packet_path: Path | None,
    soft_boost_consumption_receipt_path: Path | None,
    soft_boost_shadow_receipt_path: Path | None,
    soft_boost_comparison_ledger_path: Path | None,
    soft_boost_state_dir: Path | None,
) -> dict[str, Any]:
    if (overextension_projection_path is None) != (overextension_candidate_artifact_path is None):
        raise FullCandidateLiveSourcePacketError(
            "overextension projection and its full eligible-universe candidate artifact must be paired"
        )
    packet_paths: dict[str, Any] = {
        "candidate_artifact_path": _repo_rel(paths["candidate_subset"]),
        "eligibility_governance_path": "presets/us_short_eligibility_governance_20260624.json",
        "momentum_projection_path": _repo_rel(momentum_projection_path),
        "theme_projection_path": _repo_rel(theme_projection_path),
        "offering_audit_source_path": _repo_rel(paths["offering_audit_source"]),
        "analyst_grade_actions_path": _repo_rel(paths["analyst_grade_actions"]),
        "massive_news_events_path": _repo_rel(paths["massive_news_events"]),
        "catalyst_governance_path": "presets/us_short_catalyst_governance_20260630.json",
        "theme_selection_contract_path": _repo_rel(paths["theme_selection_contract"]),
        "output_data_context_path": _repo_rel(output_data_context_path),
    }
    if overextension_projection_path is not None:
        packet_paths["overextension_projection_path"] = _repo_rel(overextension_projection_path)
        packet_paths["overextension_candidate_artifact_path"] = _repo_rel(overextension_candidate_artifact_path)
    if yfinance_grade_actions_path is not None:
        packet_paths["yfinance_grade_actions_path"] = _repo_rel(yfinance_grade_actions_path)
    if context_components_output_path is not None:
        packet_paths["output_context_components_path"] = _repo_rel(context_components_output_path)
    soft_paths = (
        provisional_theme_stage_receipt_path,
        provisional_theme_validation_path,
        original_candidate_artifact_path,
        classification_packet_path,
        soft_boost_consumption_receipt_path,
        soft_boost_shadow_receipt_path,
        soft_boost_comparison_ledger_path,
    )
    if theme_soft_boost_enabled:
        if type(soft_discovery_stage_result) is not dict:
            raise FullCandidateLiveSourcePacketError(
                "enabled K4b consumption requires this run's soft-discovery stage result"
            )
        if any(path is None for path in soft_paths):
            raise FullCandidateLiveSourcePacketError(
                "enabled K4b consumption requires every source and output path"
            )
        if soft_boost_state_dir is None:
            raise FullCandidateLiveSourcePacketError(
                "enabled K4b consumption requires its injected state root"
            )
        packet_paths["soft_boost_state_dir_path"] = _repo_rel(soft_boost_state_dir)
        for field, path in zip((
            "provisional_theme_stage_receipt_path",
            "provisional_theme_validation_path",
            "original_candidate_artifact_path",
            "classification_packet_path",
            "soft_boost_consumption_receipt_path",
            "soft_boost_shadow_receipt_path",
            "soft_boost_comparison_ledger_path",
        ), soft_paths):
            packet_paths[field] = _repo_rel(path)
    elif (
        soft_discovery_stage_result is not None
        or soft_boost_state_dir is not None
        or any(path is not None for path in soft_paths)
    ):
        raise FullCandidateLiveSourcePacketError(
            "disabled K4b consumption must not carry stage result or soft-boost paths"
        )
    source_artifact_sha256 = {
        field: hashlib.sha256(path.read_bytes()).hexdigest()
        for field, path in (
            ("offering_audit_source_path", paths["offering_audit_source"]),
            ("analyst_grade_actions_path", paths["analyst_grade_actions"]),
            ("massive_news_events_path", paths["massive_news_events"]),
            ("theme_selection_contract_path", paths["theme_selection_contract"]),
        )
    }
    if yfinance_grade_actions_path is not None:
        source_artifact_sha256["yfinance_grade_actions_path"] = hashlib.sha256(
            yfinance_grade_actions_path.read_bytes()
        ).hexdigest()
    optional_inputs = {
        "holdings": holdings,
        "catalyst_recall_feed": catalyst_recall_feed or None,
    }
    if theme_soft_boost_enabled:
        optional_inputs["theme_soft_boost_enabled"] = True
        optional_inputs["soft_discovery_stage_result"] = soft_discovery_stage_result
    return {
        "schema_name": "us_short_batch5_data_context_source_packet",
        "schema_version": "1.3.0",
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "packet_status": "resolved_pass2_source_packet_ready_for_local_assembly",
            "network_access_performed": False,
            "provider_calls_performed": False,
            "raw_payload_capture_performed": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {
            "expected_decision_date": expected_decision_date,
            "theme_opportunity_state": theme_opportunity_state,
        },
        "source_artifact_sha256": source_artifact_sha256,
        "paths": packet_paths,
        "optional_inputs": optional_inputs,
        "preflight_gates": {
            "local_files_only": True,
            "source_artifacts_must_exist": True,
            "output_must_be_gitignored": True,
            "no_provider_fetch": True,
            "no_datahub_or_production": True,
        },
        "prohibited_claims": {
            "provider_selection_complete": False,
            "live_normalized_evidence": False,
            "ship_gate_evidence": False,
            "production_ready": False,
            "datahub_consumed": False,
        },
    }


def _endpoint_count(records: list[sample_validation.FetchRecord], provider: str, family: str) -> int:
    return sum(1 for record in records if record.provider_id == provider and record.endpoint_family == family)


def _raw_capture_manifest(records: list[sample_validation.FetchRecord]) -> dict[str, Any]:
    """Bind a live summary to the exact wrapper bytes that the provider fetch wrote.

    The tracked summary carries only identities and SHA-256 values, never payload text or request URLs. Offline replay
    validates every wrapper against this immutable capture manifest before it is allowed to re-enter assembly.
    """
    rows: list[dict[str, Any]] = []
    for record in records:
        raw_path = (ROOT / record.raw_sample_ref).resolve()
        if not raw_path.is_file():
            raise FullCandidateLiveSourcePacketError("captured raw wrapper disappeared before summary binding")
        rows.append({
            "provider_id": record.provider_id,
            "endpoint_family": record.endpoint_family,
            "symbol": record.symbol,
            "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        })
    rows.sort(key=lambda row: (row["provider_id"], row["endpoint_family"], row["symbol"] or ""))
    identities = [(row["provider_id"], row["endpoint_family"], row["symbol"]) for row in rows]
    if len(set(identities)) != len(identities):
        raise FullCandidateLiveSourcePacketError("captured endpoint identities are not unique")
    manifest_sha256 = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"endpoint_wrapper_sha256": rows, "manifest_sha256": manifest_sha256}


def _require_bound_offline_replay_client(client: Any, replay_source_capture: dict[str, Any] | None) -> None:
    """Keep the offline label reachable only through the manifest-verifying replay entry point.

    ``run_full_candidate_live_source_packet`` remains the shared assembly engine, but its offline branch must not
    accept an arbitrary HTTP-like client or caller-made provenance object.  Importing here avoids the replay module's
    normal import cycle while making the executable boundary require the concrete, bound client.
    """
    from runners.us_short_batch5_replay_pass2_source_packet_from_raw import ReplayClient

    if not isinstance(client, ReplayClient) or not client.is_bound_to_capture(replay_source_capture):
        raise FullCandidateLiveSourcePacketError(
            "offline replay requires the manifest-bound ReplayClient created by the replay entry point"
        )


def _build_summary(
    *,
    generated_at: str,
    expected_decision_date: str,
    source_as_of: str,
    observed_at: str,
    env_summary: dict[str, Any],
    preflight_summary_path: Path,
    expected_total_call_budget: int,
    preflight_total_call_forecast: int,
    candidate_artifact_path: Path,
    candidate_artifact: dict[str, Any],
    pass2_target_universe: dict[str, Any],
    endpoint_records: list[sample_validation.FetchRecord],
    retry_count_allowed: int,
    retry_count_used: int,
    max_total_http_attempts: int,
    actual_total_http_attempts: int,
    execution_mode: str,
    replay_source_capture: dict[str, Any] | None,
    cik_by_symbol: dict[str, str],
    raw_root: Path,
    summary_path: Path,
    source_paths: dict[str, Path],
    source_packet_preflight: dict[str, Any] | None,
    source_packet_run: dict[str, Any] | None,
    run_data_context: bool,
    context_components_output_path: Path | None,
    yfinance_grade_actions_path: Path | None,
) -> dict[str, Any]:
    endpoint_errors = sum(1 for record in endpoint_records if not record.ok)
    eligible = list(candidate_artifact["eligible_tickers"])
    offline_replay = execution_mode == _EXECUTION_MODE_OFFLINE_REPLAY
    return {
        "schema_name": "us_short_batch5_full_candidate_live_source_packet_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_full_candidate_live_source_packet_summary.schema.json",
        "authorization_ref": (
            "offline_replay_from_bound_source_capture" if offline_replay else AUTHORIZATION_REF
        ),
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "execution_mode": execution_mode,
            "purpose": (
                "full_candidate_offline_replay_source_packet"
                if offline_replay else "full_candidate_live_pass2_resolved_source_packet"
            ),
            "status": (
                "offline_replay_source_packet_built_preflight_only"
                if offline_replay
                else "source_packet_built_and_data_context_written"
                if source_packet_run is not None
                else "source_packet_built_preflight_only"
            ),
            "network_access_performed": not offline_replay,
            "provider_calls_performed": not offline_replay,
            "raw_payload_storage_performed": True,
            "offline_replay_non_emittable": offline_replay,
            "resolved_source_artifacts_written": True,
            "corporate_action_capture_written": True,
            "source_packet_written": True,
            "data_context_written": source_packet_run is not None,
            "context_components_written": (
                source_packet_run is not None
                and source_packet_run["scope"]["context_components_written"] is True
            ),
            "corporate_action_reconciliation_performed": False,
            "return_calculation_performed": False,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "full_market_call_performed": False,
            "yfinance_consumption_performed": False,
            "broker_or_order_execution_performed": False,
            "ship_gate_or_live_normalized_evidence_claimed": False,
            "a_share_crossing_performed": False,
        },
        "decision_clock": {
            "expected_decision_date": expected_decision_date,
            "source_as_of": source_as_of,
            "observed_at": observed_at,
        },
        "environment": env_summary,
        "preflight_gate": {
            "preflight_summary_path": _repo_rel(preflight_summary_path),
            "preflight_status": "ready_for_reviewed_live_execution",
            "local_inputs_ready": True,
            "expected_total_call_budget": expected_total_call_budget,
            "preflight_total_call_forecast": preflight_total_call_forecast,
            "call_budget_matches_preflight": expected_total_call_budget == preflight_total_call_forecast,
        },
        "candidate_universe": {
            "candidate_artifact_path": _repo_rel(candidate_artifact_path),
            "candidate_artifact_path_gitignored": _git_ignored(candidate_artifact_path),
            "row_count": len(candidate_artifact["rows"]),
            "eligible_count": len(eligible),
            "eligible_symbol_sample": eligible[:10],
            "symbol_scope": "pass2_target_universe",
            "source_full_candidate_eligible_count": pass2_target_universe["eligible_count"],
            "full_market_sample": False,
        },
        "pass2_target_universe": {
            "selection_mode": pass2_target_universe["selection_mode"],
            "momentum_top_k": pass2_target_universe["momentum_top_k"],
            "target_count": pass2_target_universe["target_count"],
            "target_symbols": list(pass2_target_universe["target_symbols"]),
            "target_symbol_sample": list(pass2_target_universe["target_symbol_sample"]),
            "fmp_grade_call_cap": pass2_target_universe["fmp_grade_call_cap"],
            "fmp_grade_calls_within_free_daily_cap": pass2_target_universe["fmp_grade_calls_within_free_daily_cap"],
            "neutral_fill_tickers_excluded_from_expensive_pass2": (
                pass2_target_universe["neutral_fill_tickers_excluded_from_expensive_pass2"]
            ),
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": expected_total_call_budget,
            "actual_total_endpoint_calls": len(endpoint_records),
            "max_total_http_attempts": max_total_http_attempts,
            "actual_total_http_attempts": actual_total_http_attempts,
            "sec_ticker_reference_calls": _endpoint_count(endpoint_records, "sec_edgar", "company_tickers_mapping"),
            "fmp_grades_calls": _endpoint_count(endpoint_records, "financial_modeling_prep", "grades"),
            "sec_submissions_calls": _endpoint_count(endpoint_records, "sec_edgar", "submissions"),
            "massive_reference_news_calls": _endpoint_count(endpoint_records, "massive", "reference_news"),
            "massive_stock_split_calls": _endpoint_count(endpoint_records, "massive", "stock_splits"),
            "massive_dividend_calls": _endpoint_count(endpoint_records, "massive", "dividends"),
            "endpoint_error_count": endpoint_errors,
            "sec_cik_missing_count": len([symbol for symbol in eligible if symbol not in cik_by_symbol]),
            "retry_count_allowed": retry_count_allowed,
            "retry_count_used": retry_count_used,
            "within_budget": actual_total_http_attempts <= max_total_http_attempts,
        },
        "endpoint_results": [_summarize_endpoint(record) for record in endpoint_records],
        "raw_capture_manifest": _raw_capture_manifest(endpoint_records),
        "storage": {
            "raw_payload_root": _repo_rel(raw_root),
            "raw_payload_root_gitignored": True,
            "tracked_summary_path": _repo_rel(summary_path),
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_raw_payload": False,
            "tracked_summary_contains_request_urls": False,
            "tracked_summary_contains_secrets": False,
        },
        "source_artifacts": {
            "candidate_subset_path": _repo_rel(source_paths["candidate_subset"]),
            "offering_audit_source_path": _repo_rel(source_paths["offering_audit_source"]),
            "analyst_grade_actions_path": _repo_rel(source_paths["analyst_grade_actions"]),
            "yfinance_grade_actions_path": (
                _repo_rel(yfinance_grade_actions_path) if yfinance_grade_actions_path is not None else None
            ),
            "analyst_grade_actions_consumed_from": (
                "yfinance_grade_actions" if yfinance_grade_actions_path is not None else "fmp_analyst_grade_actions"
            ),
            "massive_news_events_path": _repo_rel(source_paths["massive_news_events"]),
            "corporate_action_capture_path": _repo_rel(source_paths["corporate_action_capture"]),
            "momentum_projection_path": _repo_rel(source_paths["momentum_projection"]),
            "theme_projection_path": _repo_rel(source_paths["theme_projection"]),
            "artifacts_gitignored": all(_git_ignored(source_paths[key]) for key in source_paths if key != "source_packet"),
        },
        "source_packet": {
            "path": _repo_rel(source_paths["source_packet"]),
            "preflight_status": (
                source_packet_preflight["scope"]["preflight_status"]
                if source_packet_preflight is not None
                else "not_run"
            ),
            "run_data_context_requested": run_data_context,
            "data_context_output_path": (
                source_packet_run["data_context"]["output_path"]
                if source_packet_run is not None
                else None
            ),
            "context_components_output_path": (
                _repo_rel(context_components_output_path) if context_components_output_path is not None else None
            ),
        },
        "replay_source_capture": replay_source_capture,
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_download_performed": False,
            "yfinance_used": yfinance_grade_actions_path is not None,
            "paid_access_used": False,
            "datahub_consumed": False,
            "production_readiness_claimed": False,
            "corporate_action_reconciliation_claimed": False,
            "return_calculation_performed": False,
            "ship_gate_evidence_claimed": False,
            "live_normalized_evidence_claimed": False,
            "broker_or_order_execution_performed": False,
            "a_share_crossing_performed": False,
        },
        "limitations": [
            "This source-packet run is narrowed to the reviewed Pass2 target universe, not full-market coverage evidence and not the full Pass1-eligible set.",
            "Split/dividend endpoints are captured as raw provider evidence only; this runner does not reconcile corporate actions or calculate returns.",
            "Raw payloads stay under gitignored provider_samples; tracked summary excludes request URLs, raw rows, and secrets.",
            "No provider selection, DataHub, production storage, broker/order execution, live-normalized, or ship-gate evidence is claimed.",
        ],
    }


def _assert_text_safe(text: str, sensitive_values: list[str]) -> None:
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
        "\"request_url\"",
        "\"raw_payload\"",
    )
    for fragment in forbidden:
        if fragment in lower:
            raise FullCandidateLiveSourcePacketError(f"tracked summary contains forbidden fragment: {fragment}")
    for value in sensitive_values:
        if value and value in text:
            raise FullCandidateLiveSourcePacketError("tracked summary contains a sensitive environment value")


def _validate_summary_against_schema(summary: dict[str, Any]) -> None:
    _validate_json_schema(summary, SUMMARY_SCHEMA_PATH, label="full-candidate live source-packet summary")
    gate = summary["preflight_gate"]
    budget = summary["endpoint_call_budget"]
    if gate["expected_total_call_budget"] != gate["preflight_total_call_forecast"]:
        raise FullCandidateLiveSourcePacketError("summary call budget does not match preflight forecast")
    if budget["max_total_endpoint_calls"] != gate["expected_total_call_budget"]:
        raise FullCandidateLiveSourcePacketError("summary max call budget does not match the expected budget")
    actual_family_calls = (
        budget["sec_ticker_reference_calls"]
        + budget["fmp_grades_calls"]
        + budget["sec_submissions_calls"]
        + budget["massive_reference_news_calls"]
        + budget["massive_stock_split_calls"]
        + budget["massive_dividend_calls"]
    )
    if actual_family_calls != budget["actual_total_endpoint_calls"]:
        raise FullCandidateLiveSourcePacketError("summary endpoint family counts do not equal actual calls")
    if budget["actual_total_endpoint_calls"] != len(summary["endpoint_results"]):
        raise FullCandidateLiveSourcePacketError("summary endpoint_results length does not equal actual calls")
    if budget["actual_total_http_attempts"] != budget["actual_total_endpoint_calls"] + budget["retry_count_used"]:
        raise FullCandidateLiveSourcePacketError("summary physical HTTP attempts do not equal logical calls plus retries")
    if budget["actual_total_http_attempts"] > budget["max_total_http_attempts"]:
        raise FullCandidateLiveSourcePacketError("summary physical HTTP-attempt budget exceeded")
    manifest = summary["raw_capture_manifest"]
    rows = manifest["endpoint_wrapper_sha256"]
    manifest_identities = {(row["provider_id"], row["endpoint_family"], row["symbol"]) for row in rows}
    endpoint_identities = {
        (row["provider_id"], row["endpoint_family"], row["symbol"])
        for row in summary["endpoint_results"]
    }
    if len(rows) != len(manifest_identities) or manifest_identities != endpoint_identities:
        raise FullCandidateLiveSourcePacketError("raw capture manifest identities drift from endpoint results")
    expected_manifest_sha256 = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if manifest["manifest_sha256"] != expected_manifest_sha256:
        raise FullCandidateLiveSourcePacketError("raw capture manifest digest is inconsistent")
    if summary["scope"]["execution_mode"] == _EXECUTION_MODE_OFFLINE_REPLAY:
        capture = summary["replay_source_capture"]
        clock = summary["decision_clock"]
        if not isinstance(capture, dict) \
                or capture.get("source_observed_at") != clock["observed_at"] \
                or capture.get("source_expected_decision_date") != clock["expected_decision_date"] \
                or capture.get("source_as_of") != clock["source_as_of"]:
            raise FullCandidateLiveSourcePacketError(
                "offline replay summary decision clock is not bound to the source capture"
            )


def _write_summary_validated(summary: dict[str, Any], summary_path: Path, sensitive_values: list[str]) -> None:
    _validate_summary_against_schema(summary)
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text, sensitive_values)
    _write_json_atomic(summary, summary_path)


def _canonical_forced_holdings(
    forced_holding_tickers: list[str] | tuple[str, ...] | None,
    *,
    eligible: set[str],
) -> set[str]:
    """Canonicalize the caller-supplied forced-holding tickers exactly as the preflight `_canonical_list_keys` does
    (the repo single US-ticker identity policy) and require each to be in the reviewed Pass1-eligible set, so the
    live target re-derivation matches the preflight rule `target = momentum-scored∩eligible ∪ forced-holdings`."""
    if forced_holding_tickers is None:
        return set()
    if type(forced_holding_tickers) not in (list, tuple):
        raise FullCandidateLiveSourcePacketError("forced_holding_tickers must be an exact list/tuple or None")
    out: set[str] = set()
    for raw in forced_holding_tickers:
        if type(raw) is not str:
            raise FullCandidateLiveSourcePacketError("forced_holding_tickers must contain exact ticker strings")
        canon = canonical_us_ticker(raw)
        if canon is None:
            raise FullCandidateLiveSourcePacketError("forced_holding_tickers contains a non-canonicalizable ticker")
        out.add(canon)
    return out


def _canonical_catalyst_recall(
    catalyst_recall_tickers: list[str] | tuple[str, ...] | None,
    *,
    eligible: set[str],
) -> set[str]:
    recall = _canonical_forced_holdings(catalyst_recall_tickers, eligible=eligible)
    stale = sorted(recall - eligible)
    if stale:
        raise FullCandidateLiveSourcePacketError(f"catalyst_recall_tickers must be Pass1-eligible: {stale[:10]}")
    return recall


def _rederive_and_verify_pass2_targets(
    *,
    candidate_artifact_path: Path,
    expected_decision_date: str,
    eligibility_governance: dict[str, Any],
    momentum_projection_path: Path,
    theme_projection_path: Path,
    forced_holding_tickers: list[str] | tuple[str, ...] | None,
    catalyst_recall_tickers: list[str] | tuple[str, ...] | None,
    reviewed_target_symbols: list[str],
    preflight_within_cap: Any,
    momentum_top_k: int,
    expected_momentum_sha256: str,
    expected_theme_sha256: str,
    expected_forced_holdings_sha256: str,
    expected_catalyst_recall_sha256: str,
) -> dict[str, Any]:
    """Independently RE-DERIVE the Step 1 funnel Pass2 target from the momentum projection + candidate artifact
    (mirrors the preflight `_pass2_target_universe` via the SAME `select_pass2_targets`: top-K by momentum score
    plus forced holdings, with the SAME K read from the reviewed preflight), and
    REJECT any preflight whose `target_symbols` / within-cap disagree — so the expensive live boundary does NOT
    trust the preflight's self-attestation. Closes R-USSHORT-BATCH5-LIVE-RUNNER-TRUSTS-PREFLIGHT-FUNNEL-NOT-
    REDERIVED (a forged preflight can otherwise inject a neutral-fill target or re-expand to the full 2404/12021).
    Returns the runner-verified target universe for the summary, so its const-true within-cap / neutral-excluded
    attestations are COMPUTED here (only reachable on the truly-true path), not copied from the preflight."""
    artifact = _read_json(candidate_artifact_path)
    try:
        artifact = universe_fetch.validate_candidate_artifact(
            artifact,
            expected_decision_date=expected_decision_date,
            governance=eligibility_governance,
        )
    except Exception as exc:
        raise FullCandidateLiveSourcePacketError(f"candidate artifact failed validation: {exc}") from exc
    eligible = set(artifact["eligible_tickers"])
    raw = _read_json(momentum_projection_path)
    if type(raw) is not dict or type(raw.get("momentum_by_ticker")) is not dict:
        raise FullCandidateLiveSourcePacketError("momentum projection has an invalid shape for target re-derivation")
    theme_raw = _read_json(theme_projection_path)
    if file_sha256(momentum_projection_path) != expected_momentum_sha256 or file_sha256(theme_projection_path) != expected_theme_sha256:
        raise FullCandidateLiveSourcePacketError("score projection artifact changed after reviewed preflight")
    try:
        validate_projection_binding(
            raw,
            component="momentum",
            expected_decision_date=expected_decision_date,
            candidate_price_basis_date=artifact["price_basis_date"],
            source_as_of=artifact["used_date"],
            target_tickers=list(artifact["eligible_tickers"]),
            expected_producer_id="us_short_batch5_full_candidate_projection_inputs",
            expected_source_roles=("candidate_artifact", "source_momentum_projection"),
            allowed_dispositions=MOMENTUM_COVERAGE_DISPOSITIONS,
            scored_dispositions={MOMENTUM_SCORED_DISPOSITION},
        )
        validate_projection_binding(
            theme_raw,
            component="theme",
            expected_decision_date=expected_decision_date,
            candidate_price_basis_date=artifact["price_basis_date"],
            source_as_of=artifact["used_date"],
            target_tickers=list(artifact["eligible_tickers"]),
            expected_producer_id="us_short_batch5_full_candidate_projection_inputs",
            expected_source_roles=("candidate_artifact", "source_theme_projection"),
            allowed_dispositions=THEME_COVERAGE_DISPOSITIONS,
            scored_dispositions={DISPOSITION_SCORED_THEME_BASE, DISPOSITION_SCORED_INDUSTRY_BASE},
        )
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError(f"score projection source binding rejected: {exc}") from exc
    momentum_projection = raw
    theme_projection = theme_raw
    forced = _canonical_forced_holdings(forced_holding_tickers, eligible=eligible)
    recall = _canonical_catalyst_recall(catalyst_recall_tickers, eligible=eligible)
    if ticker_partition_sha256(forced) != expected_forced_holdings_sha256:
        raise FullCandidateLiveSourcePacketError("forced holding lane changed after reviewed preflight")
    if ticker_partition_sha256(recall) != expected_catalyst_recall_sha256:
        raise FullCandidateLiveSourcePacketError("catalyst recall lane changed after reviewed preflight")
    # SINGLE-SOURCE funnel selection: the SAME select_pass2_targets the preflight used (top-K by momentum score +
    # forced holdings), with the SAME K read from the reviewed preflight, so the runner re-derivation is provably
    # identical to the preflight target. A hand-authored non-canonical-keyed projection fails closed HERE (before
    # any fetch) as a funnel mismatch rather than fetching and then failing downstream.
    try:
        expected_list = select_pass2_targets(
            momentum_scores=momentum_projection["momentum_by_ticker"],
            theme_scores=theme_projection["theme_block_by_ticker"],
            eligible=eligible,
            catalyst_recall=recall,
            forced_holdings=forced,
            top_k=momentum_top_k,
        )
    except Pass2FunnelError as exc:
        raise FullCandidateLiveSourcePacketError(f"re-derived Pass2 funnel target is invalid: {exc}") from exc
    expected = set(expected_list)
    if type(reviewed_target_symbols) is not list or set(reviewed_target_symbols) != expected:
        raise FullCandidateLiveSourcePacketError(
            "preflight target_symbols do not match the re-derived momentum/theme/recall/holdings funnel"
        )
    within_cap = len(expected) <= FMP_FREE_DAILY_GRADE_CALL_CAP
    if not within_cap or preflight_within_cap is not True:
        raise FullCandidateLiveSourcePacketError(
            "re-derived Pass2 target exceeds the FMP free daily grade-call cap or disagrees with the preflight within-cap flag"
        )
    targets = expected_list  # already sorted by select_pass2_targets
    return {
        "selection_mode": "momentum_theme_top_k_plus_catalyst_recall_plus_forced_holdings",
        "eligible_count": len(artifact["eligible_tickers"]),
        "momentum_top_k": momentum_top_k,
        "target_count": len(targets),
        "target_symbols": targets,
        "target_symbol_sample": targets[:10],
        "fmp_grade_call_cap": FMP_FREE_DAILY_GRADE_CALL_CAP,
        "fmp_grade_calls_within_free_daily_cap": within_cap,
        "neutral_fill_tickers_excluded_from_expensive_pass2": True,
        "_candidate_target_symbols": sorted(expected & eligible),
        "_holding_symbols": sorted(forced),
        "_catalyst_recall_symbols": sorted(recall),
    }


def run_full_candidate_live_source_packet(
    *,
    preflight_summary_path: Path = PREFLIGHT_SUMMARY_PATH,
    expected_total_call_budget: int,
    authorized_momentum_top_k: int = 200,
    output_data_context_path: Path = DEFAULT_OUTPUT_DATA_CONTEXT_PATH,
    context_components_output_path: Path | None = DEFAULT_CONTEXT_COMPONENTS_OUTPUT_PATH,
    overextension_projection_path: Path | None = None,
    sector_classification_packet_path: Path | None = None,
    yfinance_grade_actions_path: Path | None = None,
    source_artifact_prefix: Path = SOURCE_ARTIFACT_PREFIX,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
    budget_approval: Any = None,
    client: sample_validation.JsonHttpClient | None = None,
    confirm_user_authorization: bool = False,
    run_data_context: bool = False,
    generated_at: str | None = None,
    observed_at: str | None = None,
    theme_opportunity_state: str = "no_strong_theme",
    forced_holding_tickers: list[str] | tuple[str, ...] | None = None,
    catalyst_recall_tickers: list[str] | tuple[str, ...] | None = None,
    sec_sleep_seconds: float = sample_validation.SEC_FAIR_ACCESS_SLEEP_SECONDS,
    provider_pace_seconds: float = 0.0,
    max_retries_per_call: int = 0,
    retry_backoff_seconds: float = 0.0,
    max_total_http_attempts: int | None = None,
    execution_mode: str = _EXECUTION_MODE_LIVE_PROVIDER_FETCH,
    replay_source_capture: dict[str, Any] | None = None,
    theme_soft_boost_enabled: bool = False,
    soft_discovery_stage_result: dict[str, Any] | None = None,
    provisional_theme_stage_receipt_path: Path | None = None,
    provisional_theme_validation_path: Path | None = None,
    original_candidate_artifact_path: Path | None = None,
    classification_packet_path: Path | None = None,
    soft_boost_consumption_receipt_path: Path | None = None,
    soft_boost_shadow_receipt_path: Path | None = None,
    soft_boost_comparison_ledger_path: Path | None = None,
    soft_boost_state_dir: Path | None = None,
) -> dict[str, Any]:
    # This runner has no source-bound §4.3 theme-confirmation pool.  It must not accept a caller-selected strong
    # state that changes Top15 seats; the conservative state preserves the no-strong seat split until that producer
    # is explicitly wired and bound.
    if theme_opportunity_state != "no_strong_theme":
        raise FullCandidateLiveSourcePacketError(
            "theme_opportunity_state must remain no_strong_theme until a source-bound theme confirmation producer exists"
        )
    if type(theme_soft_boost_enabled) is not bool:
        raise FullCandidateLiveSourcePacketError("theme_soft_boost_enabled must be exact bool")
    soft_boost_paths = (
        provisional_theme_stage_receipt_path,
        provisional_theme_validation_path,
        original_candidate_artifact_path,
        classification_packet_path,
        soft_boost_consumption_receipt_path,
        soft_boost_shadow_receipt_path,
        soft_boost_comparison_ledger_path,
    )
    if theme_soft_boost_enabled:
        if type(soft_discovery_stage_result) is not dict or any(
            path is None for path in soft_boost_paths
        ):
            raise FullCandidateLiveSourcePacketError(
                "enabled K4b consumption requires this run's stage result and every path"
            )
        if soft_boost_state_dir is None:
            raise FullCandidateLiveSourcePacketError(
                "enabled K4b consumption requires its injected state root"
            )
    elif (
        soft_discovery_stage_result is not None
        or soft_boost_state_dir is not None
        or any(path is not None for path in soft_boost_paths)
    ):
        raise FullCandidateLiveSourcePacketError(
            "disabled K4b consumption must not carry stage result or soft-boost paths"
        )
    if not (isinstance(max_retries_per_call, int) and not isinstance(max_retries_per_call, bool)
            and 0 <= max_retries_per_call <= _MAX_RETRIES_PER_CALL_CAP):
        raise FullCandidateLiveSourcePacketError(
            f"max_retries_per_call must be an int in [0, {_MAX_RETRIES_PER_CALL_CAP}]")
    if execution_mode not in {_EXECUTION_MODE_LIVE_PROVIDER_FETCH, _EXECUTION_MODE_OFFLINE_REPLAY}:
        raise FullCandidateLiveSourcePacketError("execution_mode must be live_provider_fetch or offline_replay")
    if execution_mode == _EXECUTION_MODE_LIVE_PROVIDER_FETCH and not confirm_user_authorization:
        raise FullCandidateLiveSourcePacketError("full-candidate live provider execution requires explicit user authorization")
    if execution_mode == _EXECUTION_MODE_OFFLINE_REPLAY:
        if run_data_context:
            raise FullCandidateLiveSourcePacketError("offline replay must not write data_context or context components")
        if not isinstance(replay_source_capture, dict):
            raise FullCandidateLiveSourcePacketError("offline replay requires bound source-capture provenance")
        _require_bound_offline_replay_client(client, replay_source_capture)
    elif replay_source_capture is not None:
        raise FullCandidateLiveSourcePacketError("live provider fetch must not accept replay source-capture provenance")
    def _finite_pace(x: Any) -> bool:
        # strict-finite, NOT just >= 0: inf passes `>= 0` and then time.sleep(inf) hangs/crashes (bare OverflowError
        # outside the runner's error contract); an absurd-but-finite value would sleep for days. Bound to [0, 60]s.
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and 0 <= x <= 60
    if not (_finite_pace(provider_pace_seconds) and _finite_pace(retry_backoff_seconds)):
        raise FullCandidateLiveSourcePacketError(
            "provider_pace_seconds and retry_backoff_seconds must be finite numbers in [0, 60] seconds")
    generated_at = generated_at or iso_now()
    if execution_mode == _EXECUTION_MODE_OFFLINE_REPLAY:
        # This is deliberately duplicated from the replay CLI boundary.  The shared assembly function is callable
        # directly, so it must neither accept a caller-selected PIT clock nor wait until after artifact assembly to
        # discover a cross-date source capture.
        capture_observed_at = replay_source_capture.get("source_observed_at")  # type: ignore[union-attr]
        if not isinstance(capture_observed_at, str) or not _valid_observed_at(capture_observed_at):
            raise FullCandidateLiveSourcePacketError("offline replay source capture lacks a valid observation clock")
        if observed_at is not None and observed_at != capture_observed_at:
            raise FullCandidateLiveSourcePacketError("offline replay observed_at must match the source capture")
        observed_at = capture_observed_at
    else:
        observed_at = observed_at or generated_at
    if not _valid_observed_at(generated_at) or not _valid_observed_at(observed_at):
        raise FullCandidateLiveSourcePacketError("generated_at and observed_at must be timezone-aware RFC3339 instants")
    preflight_path = _validate_preflight_path(preflight_summary_path)
    preflight = _load_ready_preflight(
        preflight_path,
        expected_total_call_budget,
        budget_approval,
        require_budget_approval=execution_mode == _EXECUTION_MODE_LIVE_PROVIDER_FETCH,
    )
    if max_total_http_attempts is None:
        if max_retries_per_call:
            raise FullCandidateLiveSourcePacketError(
                "max_total_http_attempts must be explicit whenever 429 retries are enabled")
        max_total_http_attempts = expected_total_call_budget
    if not (type(max_total_http_attempts) is int
            and expected_total_call_budget <= max_total_http_attempts <= 20000):
        raise FullCandidateLiveSourcePacketError(
            "max_total_http_attempts must be an int from the logical call budget through 20000")
    expected_decision_date = preflight["decision_clock"]["expected_decision_date"]
    source_as_of = _date8_to_ymd(expected_decision_date)
    if execution_mode == _EXECUTION_MODE_OFFLINE_REPLAY:
        if replay_source_capture.get("source_expected_decision_date") != expected_decision_date \
                or replay_source_capture.get("source_as_of") != source_as_of:
            raise FullCandidateLiveSourcePacketError(
                "offline replay preflight decision clock must match the source capture"
            )
    if type(authorized_momentum_top_k) is not int or isinstance(authorized_momentum_top_k, bool) or authorized_momentum_top_k < 1:
        raise FullCandidateLiveSourcePacketError("authorized_momentum_top_k must be a positive exact int")
    execution_gate = preflight.get("execution_gate")
    if type(execution_gate) is not dict or execution_gate.get("authorized_momentum_top_k") != authorized_momentum_top_k:
        raise FullCandidateLiveSourcePacketError("preflight momentum_top_k does not match the independently authorized K")

    if not _provider_samples_gitignored():
        raise FullCandidateLiveSourcePacketError("provider_samples/ is not confirmed in .gitignore")
    candidate_path = _existing_state_json(
        preflight["candidate_universe"]["candidate_artifact_path"],
        field="preflight.candidate_artifact_path",
    )
    preflight_targets = preflight["pass2_target_universe"]
    reviewed_target_symbols = list(preflight_targets["target_symbols"])
    momentum_path = _existing_state_json(
        preflight["local_input_coverage"]["momentum_projection"]["path"],
        field="preflight.momentum_projection.path",
    )
    theme_path = _existing_state_json(
        preflight["local_input_coverage"]["theme_projection"]["path"],
        field="preflight.theme_projection.path",
    )
    overextension_path = (
        _existing_state_json(overextension_projection_path, field="overextension_projection_path")
        if overextension_projection_path is not None
        else None
    )
    yfinance_actions_path = (
        _existing_state_json(yfinance_grade_actions_path, field="yfinance_grade_actions_path")
        if yfinance_grade_actions_path is not None
        else None
    )
    output_path = _validate_state_json_path(output_data_context_path, field="output_data_context_path")
    components_path = (
        _validate_state_json_path(context_components_output_path, field="context_components_output_path")
        if context_components_output_path is not None
        else None
    )
    prefix = _validate_source_artifact_prefix(source_artifact_prefix)
    paths = _source_paths(prefix)
    for field, path in paths.items():
        _validate_state_json_path(path, field=f"source_artifact.{field}")
    raw_root_resolved = _validate_raw_root(raw_root)
    summary_resolved = _validate_summary_path(summary_path)

    eligibility_governance = load_eligibility_governance(ELIGIBILITY_GOVERNANCE_PATH)
    load_catalyst_governance()
    validated_full_overextension = _validate_full_overextension_before_funnel(
        overextension_projection_path=overextension_path,
        candidate_artifact_path=candidate_path,
        expected_decision_date=expected_decision_date,
        eligibility_governance=eligibility_governance,
    )
    verified_targets = _rederive_and_verify_pass2_targets(
        candidate_artifact_path=candidate_path,
        expected_decision_date=expected_decision_date,
        eligibility_governance=eligibility_governance,
        momentum_projection_path=momentum_path,
        theme_projection_path=theme_path,
        forced_holding_tickers=forced_holding_tickers,
        catalyst_recall_tickers=catalyst_recall_tickers,
        reviewed_target_symbols=reviewed_target_symbols,
        preflight_within_cap=preflight_targets.get("fmp_grade_calls_within_free_daily_cap"),
        momentum_top_k=authorized_momentum_top_k,
        expected_momentum_sha256=preflight["local_input_coverage"]["momentum_projection"]["artifact_sha256"],
        expected_theme_sha256=preflight["local_input_coverage"]["theme_projection"]["artifact_sha256"],
        expected_forced_holdings_sha256=preflight_targets.get("forced_holding_tickers_sha256"),
        expected_catalyst_recall_sha256=preflight_targets.get("catalyst_recall_tickers_sha256"),
    )
    # Re-anchor the live-spend budget to the RUNNER-re-derived target count (not the preflight-attested
    # forecast/momentum_top_k): the operator's authorized call budget must equal the forecast recomputed from the
    # re-derived Pass2 target count, so a forged preflight that widens momentum_top_k / target_count is rejected
    # BEFORE any provider call unless the operator independently authorized the matching wider budget. Closes the
    # circular-K seam where the re-derivation otherwise consumes K from the very summary it distrusts.
    rederived_call_forecast = _SEC_TICKER_MAPPING_CALLS + verified_targets["target_count"] * _PASS2_ENDPOINT_CALLS_PER_TARGET
    if rederived_call_forecast != expected_total_call_budget:
        raise FullCandidateLiveSourcePacketError(
            "expected call budget must match the forecast recomputed from the re-derived Pass2 target count: "
            f"{expected_total_call_budget} != {rederived_call_forecast}"
        )
    candidate_subset = _candidate_subset_artifact(
        candidate_artifact_path=candidate_path,
        expected_decision_date=expected_decision_date,
        eligibility_governance=eligibility_governance,
        selected_symbols=verified_targets["_candidate_target_symbols"],
    )
    selected_symbols = list(candidate_subset["eligible_tickers"])
    if selected_symbols != verified_targets["_candidate_target_symbols"]:
        raise FullCandidateLiveSourcePacketError("candidate target symbols drifted from the re-derived funnel")
    fetch_symbols = list(reviewed_target_symbols)

    fmp_env = sample_validation.read_required_env("FMP_API_KEY")
    sec_env = sample_validation.read_required_env("SEC_USER_AGENT")
    massive_env = sample_validation.read_required_env("MASSIVE_API_KEY")
    env_summary = {
        "fmp_api_key_present": True,
        "fmp_api_key_source": fmp_env.source,
        "sec_user_agent_present": True,
        "sec_user_agent_source": sec_env.source,
        "massive_api_key_present": True,
        "massive_api_key_source": massive_env.source,
        "environment_values_logged": False,
        "secrets_logged": False,
    }

    client = client or sample_validation.JsonHttpClient()
    records, cik_by_symbol, retry_count_used, actual_total_http_attempts = _fetch_live_records(
        selected_symbols=fetch_symbols,
        raw_root=raw_root_resolved,
        client=client,
        fmp_env=fmp_env,
        sec_env=sec_env,
        massive_env=massive_env,
        sec_sleep_seconds=sec_sleep_seconds,
        max_total_endpoint_calls=expected_total_call_budget,
        max_total_http_attempts=max_total_http_attempts,
        provider_pace_seconds=provider_pace_seconds,
        max_retries_per_call=max_retries_per_call,
        retry_backoff_seconds=retry_backoff_seconds,
        fetch_fmp_grades=yfinance_actions_path is None,
        budget_approval=budget_approval,
        require_budget_approval=execution_mode == _EXECUTION_MODE_LIVE_PROVIDER_FETCH,
    )
    resolved_sources = _resolved_source_artifacts(
        selected_symbols=selected_symbols,
        source_as_of=source_as_of,
        observed_at=observed_at,
        records=records,
    )
    corporate_action_capture = _build_corporate_action_capture(
        generated_at=generated_at,
        expected_decision_date=expected_decision_date,
        source_as_of=source_as_of,
        observed_at=observed_at,
        selected_symbols=selected_symbols,
        records=records,
    )
    target_momentum_projection = _target_scoped_projection(
        projection_path=momentum_path,
        component="momentum",
        value_key="momentum_by_ticker",
        selected_symbols=selected_symbols,
        generated_at=generated_at,
        candidate_artifact=candidate_subset,
    )
    target_theme_projection = _target_scoped_projection(
        projection_path=theme_path,
        component="theme",
        value_key="theme_block_by_ticker",
        selected_symbols=selected_symbols,
        generated_at=generated_at,
        candidate_artifact=candidate_subset,
    )
    holding_rows = _holding_rows_from_records(
        holding_symbols=verified_targets["_holding_symbols"],
        source_as_of=source_as_of,
        observed_at=observed_at,
        records=records,
    )
    theme_selection_contract = _build_theme_selection_contract(
        candidate_subset=candidate_subset,
        eligibility_governance=eligibility_governance,
        expected_decision_date=expected_decision_date,
        theme_opportunity_state=theme_opportunity_state,
        parent_theme_projection_path=theme_path,
        target_theme_projection=target_theme_projection,
        resolved_sources=resolved_sources,
        catalyst_recall_tickers=verified_targets["_catalyst_recall_symbols"],
        validated_full_overextension=validated_full_overextension,
        classification_packet_path=sector_classification_packet_path,
    )

    _write_json_atomic(candidate_subset, paths["candidate_subset"])
    _write_json_atomic(resolved_sources["offering_audit_source"], paths["offering_audit_source"])
    _write_json_atomic(resolved_sources["analyst_grade_actions"], paths["analyst_grade_actions"])
    _write_json_atomic(resolved_sources["massive_news_events"], paths["massive_news_events"])
    _write_json_atomic(corporate_action_capture, paths["corporate_action_capture"])
    _write_json_atomic(target_momentum_projection, paths["momentum_projection"])
    _write_json_atomic(target_theme_projection, paths["theme_projection"])
    _write_json_atomic(theme_selection_contract, paths["theme_selection_contract"])
    packet = _build_local_source_packet(
        generated_at=generated_at,
        expected_decision_date=expected_decision_date,
        theme_opportunity_state=theme_opportunity_state,
        paths=paths,
        momentum_projection_path=paths["momentum_projection"],
        theme_projection_path=paths["theme_projection"],
        overextension_projection_path=overextension_path,
        overextension_candidate_artifact_path=candidate_path if overextension_path is not None else None,
        yfinance_grade_actions_path=yfinance_actions_path,
        output_data_context_path=output_path,
        context_components_output_path=components_path,
        holdings=holding_rows,
        catalyst_recall_feed=verified_targets["_catalyst_recall_symbols"],
        theme_soft_boost_enabled=theme_soft_boost_enabled,
        soft_discovery_stage_result=soft_discovery_stage_result,
        provisional_theme_stage_receipt_path=provisional_theme_stage_receipt_path,
        provisional_theme_validation_path=provisional_theme_validation_path,
        original_candidate_artifact_path=original_candidate_artifact_path,
        classification_packet_path=classification_packet_path,
        soft_boost_consumption_receipt_path=soft_boost_consumption_receipt_path,
        soft_boost_shadow_receipt_path=soft_boost_shadow_receipt_path,
        soft_boost_comparison_ledger_path=soft_boost_comparison_ledger_path,
        soft_boost_state_dir=soft_boost_state_dir,
    )
    _write_json_atomic(packet, paths["source_packet"])

    try:
        packet_preflight = run_local_source_packet_preflight(paths["source_packet"], generated_at=generated_at)
        packet_run = (
            run_local_source_packet(
                paths["source_packet"],
                generated_at=generated_at,
                projection_binding_expectations=FULL_CANDIDATE_LIVE_PROJECTION_BINDING,
            )
            if run_data_context
            else None
        )
    except SourcePacketError as exc:
        raise FullCandidateLiveSourcePacketError(f"local source-packet runner rejected generated packet: {exc}") from exc

    summary = _build_summary(
        generated_at=generated_at,
        expected_decision_date=expected_decision_date,
        source_as_of=source_as_of,
        observed_at=observed_at,
        env_summary=env_summary,
        preflight_summary_path=preflight_path,
        expected_total_call_budget=expected_total_call_budget,
        preflight_total_call_forecast=preflight["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"],
        candidate_artifact_path=candidate_path,
        candidate_artifact=candidate_subset,
        pass2_target_universe=verified_targets,
        endpoint_records=records,
        retry_count_allowed=max_retries_per_call,
        retry_count_used=retry_count_used,
        max_total_http_attempts=max_total_http_attempts,
        actual_total_http_attempts=actual_total_http_attempts,
        execution_mode=execution_mode,
        replay_source_capture=replay_source_capture,
        cik_by_symbol=cik_by_symbol,
        raw_root=raw_root_resolved,
        summary_path=summary_resolved,
        source_paths=paths,
        source_packet_preflight=packet_preflight,
        source_packet_run=packet_run,
        run_data_context=run_data_context,
        context_components_output_path=components_path,
        yfinance_grade_actions_path=yfinance_actions_path,
    )
    _write_summary_validated(summary, summary_resolved, [fmp_env.value, sec_env.value, massive_env.value])
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the US-short Batch5 full-candidate live Pass2 resolved-source packet from reviewed "
            "preflight inputs, including split/dividend endpoint capture. This does not reconcile "
            "corporate actions, calculate returns, use DataHub, or claim production/ship-gate evidence."
        )
    )
    parser.add_argument("--preflight-summary-path", type=Path, default=PREFLIGHT_SUMMARY_PATH)
    parser.add_argument("--expected-total-call-budget", type=int, required=True)
    parser.add_argument("--authorized-momentum-top-k", type=int, required=True)
    parser.add_argument("--output-data-context-path", type=Path, default=DEFAULT_OUTPUT_DATA_CONTEXT_PATH)
    parser.add_argument("--context-components-out", type=Path, default=DEFAULT_CONTEXT_COMPONENTS_OUTPUT_PATH)
    parser.add_argument("--yfinance-grade-actions-path", type=Path)
    parser.add_argument("--source-artifact-prefix", type=Path, default=SOURCE_ARTIFACT_PREFIX)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_SAMPLE_ROOT)
    parser.add_argument("--generated-at")
    parser.add_argument("--observed-at")
    parser.add_argument("--theme-opportunity-state", default="no_strong_theme")
    parser.add_argument("--forced-holding-ticker", action="append", default=[])
    parser.add_argument("--catalyst-recall-ticker", action="append", default=[])
    parser.add_argument("--confirm-user-authorization", action="store_true")
    parser.add_argument("--run-data-context", action="store_true")
    parser.add_argument("--provider-pace-seconds", type=float, default=0.0,
                        help="sleep between consecutive FMP/Massive endpoint calls to stay under the free-tier rate (SEC has its own pace)")
    parser.add_argument("--max-retries-per-call", type=int, default=0,
                        help="bounded retries on HTTP 429 (rate-limit) per FMP/Massive call; a 402 paywall is NOT retried")
    parser.add_argument("--retry-backoff-seconds", type=float, default=0.0,
                        help="base for exponential backoff (backoff*2^attempt) between 429 retries")
    parser.add_argument("--max-total-http-attempts", type=int,
                        help="explicit physical HTTP-attempt cap; required when 429 retries are enabled")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run_full_candidate_live_source_packet(
            preflight_summary_path=args.preflight_summary_path,
            expected_total_call_budget=args.expected_total_call_budget,
            authorized_momentum_top_k=args.authorized_momentum_top_k,
            output_data_context_path=args.output_data_context_path,
            context_components_output_path=args.context_components_out,
            yfinance_grade_actions_path=args.yfinance_grade_actions_path,
            source_artifact_prefix=args.source_artifact_prefix,
            summary_path=args.summary_path,
            raw_root=args.raw_root,
            confirm_user_authorization=args.confirm_user_authorization,
            run_data_context=args.run_data_context,
            generated_at=args.generated_at,
            observed_at=args.observed_at,
            theme_opportunity_state=args.theme_opportunity_state,
            forced_holding_tickers=args.forced_holding_ticker,
            catalyst_recall_tickers=args.catalyst_recall_ticker,
            provider_pace_seconds=args.provider_pace_seconds,
            max_retries_per_call=args.max_retries_per_call,
            retry_backoff_seconds=args.retry_backoff_seconds,
            max_total_http_attempts=args.max_total_http_attempts,
            theme_soft_boost_enabled=False,
            soft_discovery_stage_result=None,
        )
    except FullCandidateLiveSourcePacketError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": summary["scope"]["status"],
                "eligible_count": summary["candidate_universe"]["eligible_count"],
                "actual_total_endpoint_calls": summary["endpoint_call_budget"]["actual_total_endpoint_calls"],
                "endpoint_error_count": summary["endpoint_call_budget"]["endpoint_error_count"],
                "summary_path": summary["storage"]["tracked_summary_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
