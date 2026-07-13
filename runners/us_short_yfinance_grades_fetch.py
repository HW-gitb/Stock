"""Gated yfinance analyst-grade fetch for US-short Pass2 targets.

Default usage is dry-run only. A real yfinance call requires explicit
``confirm_user_authorization`` and an already-installed ``yfinance`` package.
This runner never installs dependencies and never treats yfinance grades as a
critical provider-health or emit gate. Dependency/rate-limit/provider-down cases
produce a neutral resolved-actions artifact for downstream §4.2 consumption.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_yfinance_analyst_grades import (  # noqa: E402
    ENDPOINT,
    PROVIDER_ID,
    YFinanceGradesError,
    resolve_yfinance_grade_actions,
)


AUTHORIZATION_REF = "user_chat_20260710_us_short_yfinance_grades_fetch"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_yfinance_grades_fetch_summary.schema.json"
PREFLIGHT_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_candidate_pass2_preflight_summary.schema.json"
PREFLIGHT_SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_full_candidate_pass2_preflight_summary_20260706.json"
RAW_REL_ROOT = Path("provider_samples/us_short_yfinance_grades_fetch_20260710")
RAW_ROOT = ROOT / RAW_REL_ROOT / "raw"
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
SOURCE_PACKAGE_PATH = STATE_US_SHORT_DIR / "us_short_yfinance_grades_fetch_20260710_source_package.json"
RESOLVED_ACTIONS_PATH = STATE_US_SHORT_DIR / "us_short_yfinance_grades_fetch_20260710_analyst_grade_actions.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_yfinance_grades_fetch_summary_20260710.json"
REQUIRED_ROW_FIELDS = ("Action", "Firm", "ToGrade", "FromGrade", "GradeDate")
DEFAULT_PACE_SECONDS = 1.0
_SUMMARY_FORBIDDEN = re.compile(r"(?i)(https?://|api[_-]?key|cookie|\btoken\b|\"request_url\"|\"payload\")")


class YFinanceGradesFetchError(ValueError):
    """The yfinance grades fetch cannot safely produce its bounded artifacts."""


class _YFinanceClient:
    def __init__(self, module: Any):
        self._module = module

    def ticker(self, symbol: str) -> Any:
        return self._module.Ticker(symbol)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise YFinanceGradesFetchError(f"failed to read JSON from {path}") from exc


def _write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _resolve_repo_path(path: Path | str, *, field: str) -> Path:
    raw = Path(path)
    resolved = raw.resolve() if raw.is_absolute() else (ROOT / raw).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise YFinanceGradesFetchError(f"{field} must stay under the repository root") from exc
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


def _validate_state_json_path(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise YFinanceGradesFetchError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise YFinanceGradesFetchError(f"{field} must be a .json path")
    if not _git_ignored(resolved):
        raise YFinanceGradesFetchError(f"{field} must be gitignored")
    return resolved


def _validate_raw_root(raw_root: Path | str) -> Path:
    resolved = _resolve_repo_path(raw_root, field="raw_root")
    approved = (ROOT / RAW_REL_ROOT).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise YFinanceGradesFetchError("raw_root must stay under provider_samples/us_short_yfinance_grades_fetch_20260710/") from exc
    if not _git_ignored(resolved):
        raise YFinanceGradesFetchError("raw_root must be gitignored")
    return resolved


def _validate_summary_path(summary_path: Path | str) -> Path:
    resolved = _resolve_repo_path(summary_path, field="summary_path")
    if resolved.suffix != ".json":
        raise YFinanceGradesFetchError("summary_path must be a .json file")
    if resolved == SUMMARY_PATH.resolve():
        return resolved
    try:
        resolved.relative_to((ROOT / RAW_REL_ROOT).resolve())
    except ValueError as exc:
        raise YFinanceGradesFetchError("summary_path must be the canonical tracked summary or under this runner's provider_samples folder") from exc
    if not _git_ignored(resolved):
        raise YFinanceGradesFetchError("non-canonical summary_path must be gitignored")
    return resolved


def _validate_preflight_path(preflight_summary_path: Path | str) -> Path:
    resolved = _resolve_repo_path(preflight_summary_path, field="preflight_summary_path")
    if not resolved.exists() or not resolved.is_file():
        raise YFinanceGradesFetchError("preflight_summary_path must be an existing file")
    if resolved == PREFLIGHT_SUMMARY_PATH.resolve():
        return resolved
    try:
        resolved.relative_to((ROOT / "provider_samples/us_short_batch5_full_candidate_pass2_preflight_20260706").resolve())
    except ValueError as exc:
        raise YFinanceGradesFetchError("preflight_summary_path must be canonical or under the preflight provider_samples root") from exc
    if not _git_ignored(resolved):
        raise YFinanceGradesFetchError("non-canonical preflight_summary_path must be gitignored")
    return resolved


def _valid_observed_at(value: Any) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _date8_to_ymd(value: Any) -> str:
    if not (type(value) is str and len(value) == 8 and value.isascii() and value.isdigit()):
        raise YFinanceGradesFetchError("expected_decision_date must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise YFinanceGradesFetchError("expected_decision_date must be a real calendar date") from exc


def _validate_json_schema(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise YFinanceGradesFetchError(f"jsonschema is required for {label} validation") from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise YFinanceGradesFetchError(f"{label} failed schema validation: {joined}")


def _load_ready_preflight(path: Path) -> tuple[dict[str, Any], str, str, list[str]]:
    preflight = _read_json(path)
    _validate_json_schema(preflight, PREFLIGHT_SCHEMA_PATH, label="full-candidate preflight summary")
    if (preflight.get("scope") or {}).get("status") != "ready_for_reviewed_live_execution":
        raise YFinanceGradesFetchError("preflight summary is not ready for reviewed live execution")
    if (preflight.get("execution_gate") or {}).get("ready_to_run_full_candidate_live_packet") is not True:
        raise YFinanceGradesFetchError("preflight execution gate is not ready")
    decision_date = preflight["decision_clock"]["expected_decision_date"]
    source_as_of = _date8_to_ymd(decision_date)
    target_symbols = (preflight.get("pass2_target_universe") or {}).get("target_symbols")
    if not (type(target_symbols) is list and target_symbols and all(type(symbol) is str for symbol in target_symbols)):
        raise YFinanceGradesFetchError("preflight target_symbols must be a non-empty exact string list")
    if len(set(target_symbols)) != len(target_symbols):
        raise YFinanceGradesFetchError("preflight target_symbols must be unique")
    return preflight, decision_date, source_as_of, list(target_symbols)


def _load_client(importer) -> _YFinanceClient:
    module = importer("yfinance")
    return _YFinanceClient(module)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _table_rows(table: Any) -> tuple[list[str], list[dict[str, Any]]]:
    if table is None:
        return [], []
    if isinstance(table, list):
        if not all(isinstance(row, dict) for row in table):
            raise YFinanceGradesFetchError("yfinance table list must contain objects")
        fields = sorted({str(key) for row in table for key in row})
        return fields, [{str(key): _jsonable(value) for key, value in row.items()} for row in table]
    if not (hasattr(table, "reset_index") and hasattr(table, "to_dict")):
        raise YFinanceGradesFetchError("yfinance table must be pandas-like or a list of objects")
    normalized = table.reset_index()
    fields = [str(column) for column in getattr(normalized, "columns", [])]
    records = normalized.to_dict(orient="records")
    if not (isinstance(records, list) and all(isinstance(row, dict) for row in records)):
        raise YFinanceGradesFetchError("yfinance table cannot be converted to records")
    return fields, [{str(key): _jsonable(value) for key, value in row.items()} for row in records]


def _date_value(value: Any) -> str | None:
    if hasattr(value, "date") and not isinstance(value, str):
        try:
            return value.date().isoformat()
        except (TypeError, ValueError, OverflowError):
            return None
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def _normalized_source_rows(symbol: str, fields: list[str], rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str, str]:
    if not rows:
        return [], "full", "ok"
    date_field = next((field for field in ("GradeDate", "Date", "Datetime", "date", "datetime", "index") if field in fields), None)
    required_without_date = ("Action", "Firm", "ToGrade", "FromGrade")
    if date_field is None or any(field not in fields for field in required_without_date):
        return [], "partial", "failed"
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in rows:
        grade_date = _date_value(row.get(date_field))
        if grade_date is None:
            return [], "partial", "failed"
        action = row.get("Action")
        firm = row.get("Firm")
        to_grade = row.get("ToGrade")
        from_grade = row.get("FromGrade")
        if not (
            type(action) is str
            and action.strip()
            and type(firm) is str
            and firm.strip()
            and type(to_grade) is str
            and to_grade.strip()
            and type(from_grade) is str
        ):
            return [], "partial", "failed"
        identity = (
            grade_date,
            " ".join(firm.split()).casefold(),
            " ".join(action.split()).casefold(),
            to_grade,
            from_grade,
        )
        if identity in seen:
            continue
        seen.add(identity)
        out.append({
            "symbol": symbol,
            "GradeDate": grade_date,
            "Action": action,
            "Firm": firm,
            "ToGrade": to_grade,
            "FromGrade": from_grade,
        })
    return out, "full", "ok"


def _error_category(exc: Exception) -> str:
    text = str(exc).lower()
    if "429" in text or "too many" in text or "crumb" in text:
        return "rate_limit_or_crumb_failure"
    return "fetch_error"


def _fetch_one(client: Any, symbol: str) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    try:
        ticker = client.ticker(symbol)
        fields, raw_rows = _table_rows(ticker.upgrades_downgrades)
        rows, coverage, parser = _normalized_source_rows(symbol, fields, raw_rows)
    except Exception as exc:
        return {"status": _error_category(exc), "records": [], "coverage": "missing", "parser": "failed"}, None
    status = "ok" if parser == "ok" else "parser_failed"
    return {"status": status, "records": rows, "coverage": coverage, "parser": parser}, raw_rows


def _empty_provenance(*, source_as_of: str, observed_at: str, coverage: str, parser: str, lineage_id: str) -> dict[str, Any]:
    return {
        "provider_id": PROVIDER_ID,
        "endpoint_or_filing_type": ENDPOINT,
        "source_as_of": source_as_of,
        "observed_at": observed_at,
        "coverage_status": coverage,
        "parser_status": parser,
        "lineage_ref": f"{PROVIDER_ID}:{ENDPOINT}:{source_as_of}#{lineage_id}",
    }


def _package_from_attempts(
    *,
    target_symbols: list[str],
    source_as_of: str,
    observed_at: str,
    attempts_by_symbol: dict[str, dict[str, Any]],
    force_down: bool,
) -> dict[str, Any]:
    by_ticker: dict[str, Any] = {}
    for symbol in target_symbols:
        attempt = attempts_by_symbol.get(symbol)
        if force_down or attempt is None or attempt["status"] in {"fetch_error", "rate_limit_or_crumb_failure"}:
            records: list[dict[str, Any]] = []
            coverage, parser = "missing", "failed"
        else:
            records = list(attempt["records"])
            coverage, parser = attempt["coverage"], attempt["parser"]
        by_ticker[symbol] = {
            "records": records,
            "provenance": _empty_provenance(
                source_as_of=source_as_of,
                observed_at=observed_at,
                coverage=coverage,
                parser=parser,
                lineage_id=f"{symbol.lower()}yfinancegrades",
            ),
        }
    return {
        "schema_name": "us_short_yfinance_grades_source_package",
        "schema_version": "1.0.0",
        "provider_id": PROVIDER_ID,
        "endpoint_or_filing_type": ENDPOINT,
        "source_as_of": source_as_of,
        "observed_at": observed_at,
        "grades_by_ticker": by_ticker,
    }


def _summary_status(
    *,
    dependency_missing: bool,
    rate_failures: int,
    fetch_errors: int,
    parser_failures: int,
    resolver_rejection: dict[str, str] | None,
    advisory_failure: dict[str, str] | None,
) -> tuple[str, str]:
    if advisory_failure is not None:
        return "advisory_stage_neutralized", "down"
    if resolver_rejection is not None:
        return "resolver_rejected_neutralized", "down"
    if dependency_missing:
        return "dependency_missing", "down"
    if rate_failures:
        return "halted_rate_limit_or_crumb_failure", "down"
    if fetch_errors or parser_failures:
        return "completed_with_fetch_errors", "ok"
    return "completed", "ok"


def _neutral_resolved_actions(target_symbols: list[str]) -> dict[str, Any]:
    return {
        "signals": {},
        "records": {},
        "provenance": {},
        "excluded": {symbol: "resolver_rejected_neutralized" for symbol in target_symbols},
        "checked": {},
    }


def _safe_resolver_rejection(exc: YFinanceGradesError) -> dict[str, str]:
    # Resolver messages can contain ticker-bearing validation context; the tracked summary must not.
    return {
        "error_class": type(exc).__name__,
        "message": "resolver rejected yfinance package; neutralized",
    }


def _safe_advisory_failure() -> dict[str, str]:
    return {
        "category": "post_structural_gate_failure",
        "message": "noncritical yfinance stage failed after structural gates; neutralized",
    }


def _build_summary(
    *,
    generated_at: str,
    expected_decision_date: str,
    source_as_of: str,
    observed_at: str,
    preflight_path: Path,
    target_count: int,
    attempts: list[dict[str, Any]],
    dependency_missing: bool,
    resolver_rejection: dict[str, str] | None,
    advisory_failure: dict[str, str] | None,
    pace_seconds: float,
    raw_root: Path,
    summary_path: Path,
    source_package_path: Path,
    resolved_actions_path: Path,
) -> dict[str, Any]:
    rate_failures = sum(item["status"] == "rate_limit_or_crumb_failure" for item in attempts)
    fetch_errors = sum(item["status"] == "fetch_error" for item in attempts)
    parser_failures = sum(item["status"] == "parser_failed" for item in attempts)
    successful = sum(item["status"] == "ok" for item in attempts)
    first_failure = None
    for idx, item in enumerate(attempts, start=1):
        if item["status"] != "ok":
            first_failure = idx
            break
    status, provider_status = _summary_status(
        dependency_missing=dependency_missing,
        rate_failures=rate_failures,
        fetch_errors=fetch_errors,
        parser_failures=parser_failures,
        resolver_rejection=resolver_rejection,
        advisory_failure=advisory_failure,
    )
    raw_written = successful > 0
    return {
        "schema_name": "us_short_yfinance_grades_fetch_summary",
        "schema_version": "1.1.0",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "yfinance_grades_noncritical_fetch",
            "status": status,
            "provider_status": provider_status,
            "network_access_performed": bool(attempts),
            "yfinance_import_attempted": True,
            "provider_calls_performed": bool(attempts),
            "raw_payload_storage_performed": raw_written,
            "source_package_written": True,
            "resolved_actions_written": True,
            "summary_written": True,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "emit_gate_or_provider_health_criticality_claimed": False,
            "ship_gate_or_live_normalized_evidence_claimed": False,
            "broker_or_order_execution_performed": False,
            "a_share_crossing_performed": False,
        },
        "decision_clock": {
            "expected_decision_date": expected_decision_date,
            "source_as_of": source_as_of,
            "observed_at": observed_at,
        },
        "preflight_gate": {
            "preflight_summary_path": _repo_rel(preflight_path),
            "preflight_status": "ready_for_reviewed_live_execution",
            "target_count": target_count,
            "target_symbols_in_summary": False,
        },
        "execution": {
            "attempted_symbol_count": len(attempts),
            "successful_symbol_count": successful,
            "parser_failed_symbol_count": parser_failures,
            "fetch_error_count": fetch_errors,
            "rate_limit_or_crumb_failure_count": rate_failures,
            "dependency_missing": dependency_missing,
            "resolver_rejection": resolver_rejection,
            "advisory_failure": advisory_failure,
            "first_failure_symbol_index": first_failure,
            "pace_seconds": pace_seconds,
        },
        "source_artifacts": {
            "source_package_path": _repo_rel(source_package_path),
            "resolved_actions_path": _repo_rel(resolved_actions_path),
            "source_package_gitignored": True,
            "resolved_actions_gitignored": True,
            "package_ticker_names_tracked": False,
            "resolved_shape": "fmp_compatible_resolved_grade_actions",
        },
        "storage": {
            "raw_payload_root": _repo_rel(raw_root),
            "raw_payload_root_gitignored": True,
            "tracked_summary_path": _repo_rel(summary_path),
            "tracked_summary_contains_tickers": False,
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_raw_payload": False,
            "tracked_summary_contains_request_urls": False,
            "tracked_summary_contains_secrets": False,
        },
        "prohibited_claims": {
            "provider_selected": False,
            "critical_provider_health_source": False,
            "emit_gate_source": False,
            "datahub_consumed": False,
            "production_readiness_claimed": False,
            "ship_gate_evidence_claimed": False,
            "live_normalized_evidence_claimed": False,
            "broker_or_order_execution_performed": False,
            "a_share_crossing_performed": False,
        },
        "limitations": [
            "yfinance is unofficial and low-trust; these grades are advisory only.",
            "Missing, dependency-down, rate-limited, or parser-failed yfinance grades resolve to neutral and must not block emit.",
            "Resolver-rejected yfinance packages resolve to neutral and must not block emit.",
            "Tracked summary is aggregate only; raw rows and ticker-bearing packages stay gitignored.",
        ],
    }


def _assert_summary_safe(summary: dict[str, Any], target_symbols: list[str], sensitive_values: list[str]) -> None:
    text = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    if _SUMMARY_FORBIDDEN.search(text):
        raise YFinanceGradesFetchError("tracked yfinance grades summary may not contain URLs, secrets, or raw payload fields")
    for symbol in target_symbols:
        if symbol and re.search(rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])", text):
            raise YFinanceGradesFetchError("tracked yfinance grades summary may not contain ticker names")
    for value in sensitive_values:
        if value and value in text:
            raise YFinanceGradesFetchError("tracked yfinance grades summary may not contain sensitive values")


def _write_summary_validated(summary: dict[str, Any], summary_path: Path, target_symbols: list[str]) -> None:
    _validate_json_schema(summary, SUMMARY_SCHEMA_PATH, label="yfinance grades fetch summary")
    _assert_summary_safe(summary, target_symbols, [])
    _write_json_atomic(summary, summary_path)


def _dry_run_result(preflight_path: Path, target_count: int) -> dict[str, Any]:
    return {
        "scope": {
            "status": "dry_run_only",
            "network_access_performed": False,
            "yfinance_import_attempted": False,
            "raw_payload_written": False,
            "tracked_summary_written": False,
        },
        "preflight": {
            "path": _repo_rel(preflight_path),
            "target_count": target_count,
            "target_symbols_in_output": False,
        },
        "live_requires": "--confirm-user-authorization",
    }


def _materialize_advisory_neutral_fallback(
    *,
    generated_at: str,
    decision_date: str,
    source_as_of: str,
    observed_at: str,
    preflight_path: Path,
    target_symbols: list[str],
    attempts: list[dict[str, Any]],
    pace_seconds: float,
    raw_root: Path,
    summary_path: Path,
    source_package_path: Path,
    resolved_actions_path: Path,
) -> dict[str, Any]:
    """Replace every downstream-visible artifact with a complete neutral set after a post-gate failure.

    All payloads are built and validated before any replacement.  Each final file uses the existing atomic writer,
    and an I/O failure still propagates so Pass2 can never consume an incomplete fallback set.
    """
    package = _package_from_attempts(
        target_symbols=target_symbols,
        source_as_of=source_as_of,
        observed_at=observed_at,
        attempts_by_symbol={},
        force_down=True,
    )
    resolved_actions = _neutral_resolved_actions(target_symbols)
    summary = _build_summary(
        generated_at=generated_at,
        expected_decision_date=decision_date,
        source_as_of=source_as_of,
        observed_at=observed_at,
        preflight_path=preflight_path,
        target_count=len(target_symbols),
        attempts=attempts,
        dependency_missing=False,
        resolver_rejection=None,
        advisory_failure=_safe_advisory_failure(),
        pace_seconds=pace_seconds,
        raw_root=raw_root,
        summary_path=summary_path,
        source_package_path=source_package_path,
        resolved_actions_path=resolved_actions_path,
    )
    _validate_json_schema(summary, SUMMARY_SCHEMA_PATH, label="neutral yfinance grades fetch summary")
    _assert_summary_safe(summary, target_symbols, [])
    _write_json_atomic(package, source_package_path)
    _write_json_atomic(resolved_actions, resolved_actions_path)
    _write_json_atomic(summary, summary_path)
    return summary


def _run_post_structural_gate(
    *,
    generated_at: str,
    decision_date: str,
    source_as_of: str,
    observed_at: str,
    preflight_path: Path,
    target_symbols: list[str],
    attempts: list[dict[str, Any]],
    pace_seconds: float,
    raw_root: Path,
    summary_path: Path,
    source_package_path: Path,
    resolved_actions_path: Path,
    client: Any,
    importer,
) -> dict[str, Any]:
    attempts_by_symbol: dict[str, dict[str, Any]] = {}
    dependency_missing = False
    try:
        yf_client = client if client is not None else _load_client(importer)
    except ImportError:
        dependency_missing = True
        yf_client = None

    if yf_client is not None:
        raw_root.mkdir(parents=True, exist_ok=True)
        for index, symbol in enumerate(target_symbols, start=1):
            attempt, raw_rows = _fetch_one(yf_client, symbol)
            attempts.append(attempt)
            attempts_by_symbol[symbol] = attempt
            if raw_rows is not None and attempt["status"] == "ok":
                _write_json_atomic({"ticker": symbol, "upgrades_downgrades": raw_rows}, raw_root / f"{symbol}.json")
            if attempt["status"] == "rate_limit_or_crumb_failure":
                break
            if index < len(target_symbols) and pace_seconds:
                time.sleep(float(pace_seconds))

    force_down = dependency_missing or any(item["status"] == "rate_limit_or_crumb_failure" for item in attempts)
    package = _package_from_attempts(
        target_symbols=target_symbols,
        source_as_of=source_as_of,
        observed_at=observed_at,
        attempts_by_symbol=attempts_by_symbol,
        force_down=force_down,
    )
    resolver_rejection: dict[str, str] | None = None
    try:
        resolved_actions = resolve_yfinance_grade_actions(
            as_of=source_as_of,
            grades_by_ticker=package["grades_by_ticker"],
        )
    except YFinanceGradesError as exc:
        resolver_rejection = _safe_resolver_rejection(exc)
        resolved_actions = _neutral_resolved_actions(target_symbols)

    _write_json_atomic(package, source_package_path)
    _write_json_atomic(resolved_actions, resolved_actions_path)
    summary = _build_summary(
        generated_at=generated_at,
        expected_decision_date=decision_date,
        source_as_of=source_as_of,
        observed_at=observed_at,
        preflight_path=preflight_path,
        target_count=len(target_symbols),
        attempts=attempts,
        dependency_missing=dependency_missing,
        resolver_rejection=resolver_rejection,
        advisory_failure=None,
        pace_seconds=pace_seconds,
        raw_root=raw_root,
        summary_path=summary_path,
        source_package_path=source_package_path,
        resolved_actions_path=resolved_actions_path,
    )
    _write_summary_validated(summary, summary_path, target_symbols)
    return summary


def run_yfinance_grades_fetch(
    *,
    preflight_summary_path: Path = PREFLIGHT_SUMMARY_PATH,
    output_source_package_path: Path = SOURCE_PACKAGE_PATH,
    output_resolved_actions_path: Path = RESOLVED_ACTIONS_PATH,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_ROOT,
    client: Any = None,
    importer=importlib.import_module,
    confirm_user_authorization: bool = False,
    generated_at: str | None = None,
    observed_at: str | None = None,
    pace_seconds: float = DEFAULT_PACE_SECONDS,
) -> dict[str, Any]:
    if not confirm_user_authorization:
        raise YFinanceGradesFetchError("yfinance grades fetch requires explicit user authorization")
    if not (isinstance(pace_seconds, (int, float)) and not isinstance(pace_seconds, bool) and math.isfinite(pace_seconds) and 0 <= pace_seconds <= 60):
        raise YFinanceGradesFetchError("pace_seconds must be finite and within [0, 60]")
    generated_at = generated_at or iso_now()
    observed_at = observed_at or generated_at
    if not _valid_observed_at(generated_at) or not _valid_observed_at(observed_at):
        raise YFinanceGradesFetchError("generated_at and observed_at must be timezone-aware RFC3339 instants")
    preflight_path = _validate_preflight_path(preflight_summary_path)
    _, decision_date, source_as_of, target_symbols = _load_ready_preflight(preflight_path)
    source_package_path = _validate_state_json_path(output_source_package_path, field="output_source_package_path")
    resolved_actions_path = _validate_state_json_path(output_resolved_actions_path, field="output_resolved_actions_path")
    raw_root_resolved = _validate_raw_root(raw_root)
    summary_resolved = _validate_summary_path(summary_path)

    attempts: list[dict[str, Any]] = []
    try:
        return _run_post_structural_gate(
            generated_at=generated_at,
            decision_date=decision_date,
            source_as_of=source_as_of,
            observed_at=observed_at,
            preflight_path=preflight_path,
            target_symbols=target_symbols,
            attempts=attempts,
            pace_seconds=float(pace_seconds),
            raw_root=raw_root_resolved,
            summary_path=summary_resolved,
            source_package_path=source_package_path,
            resolved_actions_path=resolved_actions_path,
            client=client,
            importer=importer,
        )
    except Exception:  # noqa: BLE001 — this boundary is intentionally phase-based, not exception-type sniffing
        return _materialize_advisory_neutral_fallback(
            generated_at=generated_at,
            decision_date=decision_date,
            source_as_of=source_as_of,
            observed_at=observed_at,
            preflight_path=preflight_path,
            target_symbols=target_symbols,
            attempts=attempts,
            pace_seconds=float(pace_seconds),
            raw_root=raw_root_resolved,
            summary_path=summary_resolved,
            source_package_path=source_package_path,
            resolved_actions_path=resolved_actions_path,
        )


def run_default(
    *,
    dry_run: bool = True,
    confirm_user_authorization: bool = False,
    preflight_summary_path: Path = PREFLIGHT_SUMMARY_PATH,
    importer=importlib.import_module,
) -> dict[str, Any]:
    preflight_path = _validate_preflight_path(preflight_summary_path)
    _, _, _, target_symbols = _load_ready_preflight(preflight_path)
    if dry_run:
        return _dry_run_result(preflight_path, len(target_symbols))
    return run_yfinance_grades_fetch(
        preflight_summary_path=preflight_path,
        importer=importer,
        confirm_user_authorization=confirm_user_authorization,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch low-trust yfinance analyst grades for reviewed US-short Pass2 targets. Default is dry-run."
    )
    parser.add_argument("--preflight-summary-path", type=Path, default=PREFLIGHT_SUMMARY_PATH)
    parser.add_argument("--output-source-package-path", type=Path, default=SOURCE_PACKAGE_PATH)
    parser.add_argument("--output-resolved-actions-path", type=Path, default=RESOLVED_ACTIONS_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--generated-at")
    parser.add_argument("--observed-at")
    parser.add_argument("--pace-seconds", type=float, default=DEFAULT_PACE_SECONDS)
    parser.add_argument("--confirm-user-authorization", action="store_true")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--run", dest="dry_run", action="store_false")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.dry_run:
            summary = run_default(dry_run=True, preflight_summary_path=args.preflight_summary_path)
        else:
            summary = run_yfinance_grades_fetch(
                preflight_summary_path=args.preflight_summary_path,
                output_source_package_path=args.output_source_package_path,
                output_resolved_actions_path=args.output_resolved_actions_path,
                summary_path=args.summary_path,
                raw_root=args.raw_root,
                generated_at=args.generated_at,
                observed_at=args.observed_at,
                pace_seconds=args.pace_seconds,
                confirm_user_authorization=args.confirm_user_authorization,
            )
    except YFinanceGradesFetchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": summary["scope"]["status"],
        "provider_status": summary["scope"].get("provider_status"),
        "target_count": summary.get("preflight_gate", {}).get("target_count"),
        "summary_path": summary.get("storage", {}).get("tracked_summary_path"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
