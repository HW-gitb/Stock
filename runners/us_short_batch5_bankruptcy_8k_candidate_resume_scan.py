from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_eligibility_gate import canonical_us_ticker, load_eligibility_governance  # noqa: E402
from runners import us_egs_sample_validation as sample_validation  # noqa: E402
from runners import us_short_batch5_bankruptcy_8k_source_packet as source_packet_runner  # noqa: E402
from runners import us_short_batch5_bankruptcy_8k_source_packet_producer as bounded_producer  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402


AUTHORIZATION_REF = "user_chat_20260705_us_short_bankruptcy_8k_candidate_resume_scan_3_rounds"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_bankruptcy_8k_candidate_resume_scan_summary.schema.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_bankruptcy_8k_candidate_resume_scan_20260705")
RAW_SAMPLE_BASE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
DOCS_DIR = ROOT / "docs"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260706.json"
DEFAULT_MANIFEST_PATH = STATE_US_SHORT_DIR / "us_short_batch5_bankruptcy_8k_candidate_resume_scan_20260705_manifest.json"

SEC_TICKER_MAP_URL = bounded_producer.SEC_TICKER_MAP_URL
ENDPOINT_TICKER_MAP = bounded_producer.ENDPOINT_TICKER_MAP
ENDPOINT_SUBMISSIONS = bounded_producer.ENDPOINT_SUBMISSIONS
SOURCE_PACKET_INPUT_SOURCE = bounded_producer.SOURCE_PACKET_INPUT_SOURCE
LOOKBACK_DAYS = bounded_producer.LOOKBACK_DAYS
SEC_SLEEP_SECONDS = sample_validation.SEC_FAIR_ACCESS_SLEEP_SECONDS
SHARD_SIZE = 25
MAX_ROUNDS_TOTAL = 3
MAX_SHARDS_PER_ROUND = 35
DEFAULT_PRECOMPLETED_SHARD_INDICES = (0, 1)


class Bankruptcy8kCandidateResumeScanError(ValueError):
    """The resumable candidate-universe bankruptcy 8-K scan cannot run safely."""


@dataclass
class FetchRecord:
    provider_id: str
    endpoint_family: str
    symbol: str | None
    raw_sample_ref: str
    ok: bool
    http_status: int | None
    error_type: str | None
    payload: Any


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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
        raise Bankruptcy8kCandidateResumeScanError(f"{field} must stay under the repository root") from exc
    return resolved


def _git_ignored(path: Path) -> bool:
    rel = _repo_rel(path)
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", rel],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _validate_state_json_path(path: Path | str, *, field: str, must_exist: bool = False) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise Bankruptcy8kCandidateResumeScanError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise Bankruptcy8kCandidateResumeScanError(f"{field} must be a .json path")
    if must_exist and (not resolved.exists() or not resolved.is_file()):
        raise Bankruptcy8kCandidateResumeScanError(f"{field} must be an existing file: {_display_path(resolved)}")
    if not _git_ignored(resolved):
        raise Bankruptcy8kCandidateResumeScanError(f"{field} must be gitignored")
    return resolved


def _validate_summary_path(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    if resolved.suffix != ".json":
        raise Bankruptcy8kCandidateResumeScanError(f"{field} must be a .json path")
    try:
        resolved.parent.relative_to(DOCS_DIR.resolve())
    except ValueError as exc:
        raise Bankruptcy8kCandidateResumeScanError(f"{field} must stay under docs/") from exc
    if _git_ignored(resolved):
        raise Bankruptcy8kCandidateResumeScanError(f"{field} must not be gitignored")
    return resolved


def _validate_raw_root(raw_root: Path | str) -> Path:
    resolved = _resolve_repo_path(raw_root, field="raw_root")
    try:
        resolved.relative_to(RAW_SAMPLE_BASE_ROOT.resolve())
    except ValueError as exc:
        raise Bankruptcy8kCandidateResumeScanError(
            "raw_root must stay under provider_samples/us_short_batch5_bankruptcy_8k_candidate_resume_scan_20260705/"
        ) from exc
    try:
        sample_validation.validate_raw_root(resolved)
    except ValueError as exc:
        raise Bankruptcy8kCandidateResumeScanError(str(exc)) from exc
    if not _git_ignored(resolved):
        raise Bankruptcy8kCandidateResumeScanError("raw_root must be gitignored")
    return resolved


def _resolve_manifest_raw_ref(raw_ref: Any, *, raw_root: Path) -> Path:
    if not isinstance(raw_ref, str) or not raw_ref.strip():
        raise Bankruptcy8kCandidateResumeScanError("manifest raw ref must be a non-empty repo-relative string")
    if Path(raw_ref).is_absolute():
        raise Bankruptcy8kCandidateResumeScanError("manifest raw ref must be repo-relative")
    raw_path = (ROOT / raw_ref).resolve()
    try:
        raw_path.relative_to(raw_root.resolve())
    except ValueError as exc:
        raise Bankruptcy8kCandidateResumeScanError("manifest raw ref must stay under the round raw_root") from exc
    if not _git_ignored(raw_path):
        raise Bankruptcy8kCandidateResumeScanError("manifest raw ref must be gitignored")
    if not raw_path.is_file():
        raise Bankruptcy8kCandidateResumeScanError(f"manifest raw ref does not exist: {raw_ref}")
    return raw_path


def _write_json_atomic(payload: Any, path: Path, *, field: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_dir():
        raise Bankruptcy8kCandidateResumeScanError(f"{field} must be a file path: {_display_path(path)}")
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise Bankruptcy8kCandidateResumeScanError(f"{field} could not be written atomically") from exc


def _validate_schema(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise Bankruptcy8kCandidateResumeScanError("jsonschema is required for resume scan validation") from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise Bankruptcy8kCandidateResumeScanError(f"{label} schema rejected {len(errors)} field(s): {joined}") from errors[0]


def _date8_to_ymd(value: str, *, field: str) -> str:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise Bankruptcy8kCandidateResumeScanError(f"{field} must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise Bankruptcy8kCandidateResumeScanError(f"{field} must be a real calendar date") from exc


def _canonical_symbol_list(raw_symbols: list[str] | tuple[str, ...] | None, *, field: str) -> list[str]:
    if raw_symbols is None:
        return []
    if type(raw_symbols) not in (list, tuple):
        raise Bankruptcy8kCandidateResumeScanError(f"{field} must be a list/tuple")
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_symbols:
        if type(raw) is not str:
            raise Bankruptcy8kCandidateResumeScanError(f"{field} must contain strings")
        ticker = canonical_us_ticker(raw)
        if ticker is None:
            raise Bankruptcy8kCandidateResumeScanError(f"{field} must contain canonicalizable US tickers")
        if ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


def _candidate_context(
    *,
    candidate_artifact_path: Path,
    expected_decision_date: str,
    exclude_symbols: list[str] | tuple[str, ...] | None,
) -> dict[str, Any]:
    artifact = _read_json(candidate_artifact_path)
    governance = load_eligibility_governance(ELIGIBILITY_GOVERNANCE_PATH)
    try:
        universe_fetch.validate_candidate_artifact(
            artifact,
            expected_decision_date=expected_decision_date,
            governance=governance,
        )
    except Exception as exc:
        raise Bankruptcy8kCandidateResumeScanError(f"candidate artifact failed validation: {exc}") from exc
    excluded = _canonical_symbol_list(exclude_symbols, field="exclude_symbols")
    excluded_set = set(excluded)
    eligible = [ticker for ticker in artifact["eligible_tickers"] if ticker not in excluded_set]
    if not eligible:
        raise Bankruptcy8kCandidateResumeScanError("candidate artifact has no eligible symbols after exclusions")
    return {
        "artifact": artifact,
        "eligible_symbols": eligible,
        "excluded_symbols": excluded,
        "expected_decision_date": artifact["decision_date"],
        "status_as_of": _date8_to_ymd(artifact["decision_date"], field="candidate.decision_date"),
        "candidate_artifact_row_count": len(artifact["rows"]),
        "candidate_artifact_eligible_count": len(artifact["eligible_tickers"]),
        "eligible_after_exclusions_count": len(eligible),
        "total_shard_count": ceil(len(eligible) / SHARD_SIZE),
    }


def _validate_round_controls(round_index: int, max_shards_per_round: int) -> None:
    if type(round_index) is not int or round_index < 1 or round_index > MAX_ROUNDS_TOTAL:
        raise Bankruptcy8kCandidateResumeScanError("round_index must be 1, 2, or 3")
    if type(max_shards_per_round) is not int or max_shards_per_round < 1 or max_shards_per_round > MAX_SHARDS_PER_ROUND:
        raise Bankruptcy8kCandidateResumeScanError(f"max_shards_per_round must be 1-{MAX_SHARDS_PER_ROUND}")


def _shard_symbols(eligible_symbols: list[str], shard_index: int) -> list[str]:
    start = shard_index * SHARD_SIZE
    return eligible_symbols[start:start + SHARD_SIZE]


def _seed_completed_shards(precompleted: list[int], context: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    total = context["total_shard_count"]
    for shard_index in sorted(set(precompleted)):
        if shard_index < 0 or shard_index >= total:
            raise Bankruptcy8kCandidateResumeScanError("precompleted_shard_indices must be within candidate shard range")
        symbols = _shard_symbols(context["eligible_symbols"], shard_index)
        out.append(
            {
                "shard_index": shard_index,
                "source": "preexisting_candidate_scan",
                "round_index": None,
                "symbols": symbols,
                "raw_refs_by_symbol": {},
                "completed_at": None,
            }
        )
    return out


def _manifest_base(
    *,
    context: dict[str, Any],
    candidate_artifact_path: Path,
    manifest_path: Path,
    precompleted_shard_indices: list[int],
    generated_at: str,
) -> dict[str, Any]:
    completed = _seed_completed_shards(precompleted_shard_indices, context)
    return {
        "schema_name": "us_short_batch5_bankruptcy_8k_candidate_resume_scan_manifest",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "updated_at": generated_at,
        "candidate_artifact_path": _repo_rel(candidate_artifact_path),
        "expected_decision_date": context["expected_decision_date"],
        "excluded_symbols": context["excluded_symbols"],
        "shard_size": SHARD_SIZE,
        "max_rounds_total": MAX_ROUNDS_TOTAL,
        "max_shards_per_round_cap": MAX_SHARDS_PER_ROUND,
        "eligible_after_exclusions_count": context["eligible_after_exclusions_count"],
        "total_shard_count": context["total_shard_count"],
        "precompleted_shard_indices": sorted(set(precompleted_shard_indices)),
        "completed_shards": completed,
        "round_runs": [],
        "manifest_path": _repo_rel(manifest_path),
    }


def _load_or_init_manifest(
    *,
    context: dict[str, Any],
    candidate_artifact_path: Path,
    manifest_path: Path,
    precompleted_shard_indices: list[int],
    generated_at: str,
) -> dict[str, Any]:
    if manifest_path.exists():
        try:
            manifest = _read_json(manifest_path)
        except Exception as exc:
            raise Bankruptcy8kCandidateResumeScanError("manifest JSON could not be read") from exc
    else:
        manifest = _manifest_base(
            context=context,
            candidate_artifact_path=candidate_artifact_path,
            manifest_path=manifest_path,
            precompleted_shard_indices=precompleted_shard_indices,
            generated_at=generated_at,
        )
    _validate_manifest_compatible(manifest, context=context, candidate_artifact_path=candidate_artifact_path)
    return manifest


def _validate_manifest_compatible(manifest: dict[str, Any], *, context: dict[str, Any], candidate_artifact_path: Path) -> None:
    required = {
        "schema_name": "us_short_batch5_bankruptcy_8k_candidate_resume_scan_manifest",
        "schema_version": "1.0.0",
        "candidate_artifact_path": _repo_rel(candidate_artifact_path),
        "expected_decision_date": context["expected_decision_date"],
        "shard_size": SHARD_SIZE,
        "max_rounds_total": MAX_ROUNDS_TOTAL,
        "eligible_after_exclusions_count": context["eligible_after_exclusions_count"],
        "total_shard_count": context["total_shard_count"],
    }
    for field, expected in required.items():
        if manifest.get(field) != expected:
            raise Bankruptcy8kCandidateResumeScanError(f"manifest {field} does not match current candidate context")
    if manifest.get("excluded_symbols") != context["excluded_symbols"]:
        raise Bankruptcy8kCandidateResumeScanError("manifest excluded_symbols does not match current invocation")
    if not isinstance(manifest.get("completed_shards"), list) or not isinstance(manifest.get("round_runs"), list):
        raise Bankruptcy8kCandidateResumeScanError("manifest completed_shards/round_runs must be arrays")


def _completed_indices(manifest: dict[str, Any]) -> set[int]:
    out: set[int] = set()
    for entry in manifest["completed_shards"]:
        if not isinstance(entry, dict) or type(entry.get("shard_index")) is not int:
            raise Bankruptcy8kCandidateResumeScanError("manifest completed_shards entries must carry shard_index")
        out.add(entry["shard_index"])
    return out


def _resume_completed_indices(manifest: dict[str, Any]) -> list[int]:
    return sorted(
        entry["shard_index"]
        for entry in manifest["completed_shards"]
        if isinstance(entry, dict) and entry.get("source") == "resume_scan"
    )


def _round_already_recorded(manifest: dict[str, Any], round_index: int) -> bool:
    return any(isinstance(row, dict) and row.get("round_index") == round_index for row in manifest["round_runs"])


def _build_round_plan(
    *,
    context: dict[str, Any],
    manifest: dict[str, Any],
    round_index: int,
    max_shards_per_round: int,
) -> dict[str, Any]:
    if _round_already_recorded(manifest, round_index):
        raise Bankruptcy8kCandidateResumeScanError(f"round_index {round_index} is already recorded in manifest")
    completed = _completed_indices(manifest)
    total_shards = context["total_shard_count"]
    all_indices = list(range(total_shards))
    precompleted = sorted(manifest["precompleted_shard_indices"])
    if precompleted != list(range(len(precompleted))):
        raise Bankruptcy8kCandidateResumeScanError("precompleted_shard_indices must be the initial contiguous shard prefix")
    round_start = len(precompleted) + (round_index - 1) * max_shards_per_round
    round_end = min(round_start + max_shards_per_round, total_shards)
    if round_start >= total_shards:
        raise Bankruptcy8kCandidateResumeScanError("round_index is beyond the candidate shard range")
    round_window = list(range(round_start, round_end))
    target = [idx for idx in round_window if idx not in completed]
    finalize_only = False
    if not target:
        if any(idx not in completed for idx in round_window):
            raise Bankruptcy8kCandidateResumeScanError("round window has no unfinished shards")
        finalize_only = True
    target_symbol_count = sum(len(_shard_symbols(context["eligible_symbols"], idx)) for idx in target)
    remaining_after = len([idx for idx in all_indices if idx not in completed and idx not in set(target)])
    remaining_capacity = (MAX_ROUNDS_TOTAL - round_index) * max_shards_per_round
    if remaining_after > remaining_capacity:
        raise Bankruptcy8kCandidateResumeScanError("round controls cannot finish the remaining shards within 3 rounds")
    return {
        "round_index": round_index,
        "max_rounds_total": MAX_ROUNDS_TOTAL,
        "max_shards_per_round": max_shards_per_round,
        "shard_size": SHARD_SIZE,
        "total_shard_count": context["total_shard_count"],
        "precompleted_shard_indices": manifest["precompleted_shard_indices"],
        "completed_before_round": len(completed),
        "round_window_shard_indices": round_window,
        "finalize_only": finalize_only,
        "target_shard_indices": target,
        "target_symbol_count": target_symbol_count,
        "remaining_shards_after_round": remaining_after,
        "full_candidate_universe_scan_completed_if_round_succeeds": remaining_after == 0,
    }


def _default_round_paths(round_index: int) -> dict[str, Path]:
    tag = f"round{round_index:02d}"
    return {
        "raw_root": RAW_SAMPLE_BASE_ROOT / tag / "raw",
        "source_packet": STATE_US_SHORT_DIR / f"us_short_batch5_bankruptcy_8k_candidate_resume_scan_{tag}_20260705_packet.json",
        "screen": STATE_US_SHORT_DIR / f"us_short_batch5_bankruptcy_8k_candidate_resume_scan_{tag}_20260705_screen.json",
        "summary": DOCS_DIR / f"us_short_batch5_bankruptcy_8k_candidate_resume_scan_{tag}_summary_20260705.json",
        "consumer_summary": DOCS_DIR / f"us_short_batch5_bankruptcy_8k_candidate_resume_scan_{tag}_consumer_summary_20260705.json",
    }


def _resolve_default_path(path: Path | str | None, *, round_index: int, key: str) -> Path:
    if path is not None:
        return Path(path)
    return _default_round_paths(round_index)[key]


def _raw_ref_for(raw_root: Path, endpoint_family: str, *, round_index: int, shard_index: int | None = None, symbol: str | None = None) -> Path:
    if endpoint_family == ENDPOINT_TICKER_MAP:
        return raw_root / f"round{round_index:02d}" / "sec_edgar" / "company_tickers_exchange.json"
    assert symbol is not None and shard_index is not None
    return raw_root / f"round{round_index:02d}" / f"shard{shard_index:04d}" / "sec_edgar" / symbol / "company_submissions_recent_filings.json"


def _fetch_and_store(
    *,
    client: sample_validation.JsonHttpClient,
    url: str,
    headers: dict[str, str],
    raw_root: Path,
    endpoint_family: str,
    round_index: int,
    shard_index: int | None = None,
    symbol: str | None = None,
) -> FetchRecord:
    payload, http_status, ok, error_type = client.get_json(url, headers=headers)
    raw_path = _raw_ref_for(
        raw_root,
        endpoint_family,
        round_index=round_index,
        shard_index=shard_index,
        symbol=symbol,
    )
    _write_json_atomic(
        {
            "provider_id": "sec_edgar",
            "endpoint_family": endpoint_family,
            "symbol": symbol,
            "http_status": http_status,
            "ok": ok,
            "error_type": error_type,
            "payload": payload,
        },
        raw_path,
        field="raw_sample",
    )
    return FetchRecord(
        provider_id="sec_edgar",
        endpoint_family=endpoint_family,
        symbol=symbol,
        raw_sample_ref=_repo_rel(raw_path),
        ok=ok,
        http_status=http_status,
        error_type=error_type,
        payload=payload,
    )


def _submissions_url(cik: int) -> str:
    return bounded_producer._submissions_url(cik)


def _summarize_endpoint(record: FetchRecord) -> dict[str, Any]:
    return {
        "provider_id": record.provider_id,
        "endpoint_family": record.endpoint_family,
        "symbol": record.symbol,
        "status": "success" if record.ok else "error",
        "http_status": record.http_status,
        "error_type": record.error_type,
        "raw_sample_ref": record.raw_sample_ref,
        "raw_sample_ref_gitignored": record.raw_sample_ref.startswith("provider_samples/"),
        "payload_shape": bounded_producer._payload_shape(record),
    }


def _save_manifest(manifest: dict[str, Any], manifest_path: Path, *, updated_at: str) -> None:
    manifest["updated_at"] = updated_at
    manifest["completed_shard_indices"] = sorted(_completed_indices(manifest))
    manifest["resume_completed_shard_indices"] = _resume_completed_indices(manifest)
    _write_json_atomic(manifest, manifest_path, field="resume_manifest")


def _record_completed_shard(
    *,
    manifest: dict[str, Any],
    context: dict[str, Any],
    shard_index: int,
    round_index: int,
    records: list[FetchRecord],
    completed_at: str,
) -> None:
    raw_refs = {record.symbol: record.raw_sample_ref for record in records if record.endpoint_family == ENDPOINT_SUBMISSIONS}
    symbols = _shard_symbols(context["eligible_symbols"], shard_index)
    if set(raw_refs) != set(symbols):
        raise Bankruptcy8kCandidateResumeScanError(f"completed shard {shard_index} is missing raw submissions")
    existing = _completed_indices(manifest)
    if shard_index in existing:
        return
    manifest["completed_shards"].append(
        {
            "shard_index": shard_index,
            "source": "resume_scan",
            "round_index": round_index,
            "symbols": symbols,
            "raw_refs_by_symbol": {symbol: raw_refs[symbol] for symbol in symbols},
            "completed_at": completed_at,
        }
    )


def _load_resume_submissions(manifest: dict[str, Any], *, raw_root: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for entry in sorted(manifest["completed_shards"], key=lambda row: row["shard_index"]):
        if entry.get("source") != "resume_scan":
            continue
        for symbol in entry["symbols"]:
            rel = entry["raw_refs_by_symbol"][symbol]
            raw_path = _resolve_manifest_raw_ref(rel, raw_root=raw_root)
            wrapper = _read_json(raw_path)
            if wrapper.get("ok") is not True or wrapper.get("endpoint_family") != ENDPOINT_SUBMISSIONS:
                raise Bankruptcy8kCandidateResumeScanError(f"manifest raw ref is not a successful SEC submissions payload: {rel}")
            out[symbol] = wrapper["payload"]
    if not out:
        raise Bankruptcy8kCandidateResumeScanError("resume manifest contains no completed SEC submissions payloads")
    return out


def _fetch_record_from_wrapper(raw_ref: Any, *, raw_root: Path) -> FetchRecord:
    raw_path = _resolve_manifest_raw_ref(raw_ref, raw_root=raw_root)
    wrapper = _read_json(raw_path)
    if wrapper.get("ok") is not True:
        raise Bankruptcy8kCandidateResumeScanError(f"manifest raw ref is not a successful provider payload: {raw_ref}")
    return FetchRecord(
        provider_id=wrapper.get("provider_id", "sec_edgar"),
        endpoint_family=wrapper.get("endpoint_family"),
        symbol=wrapper.get("symbol"),
        raw_sample_ref=raw_ref,
        ok=wrapper.get("ok"),
        http_status=wrapper.get("http_status"),
        error_type=wrapper.get("error_type"),
        payload=wrapper.get("payload"),
    )


def _records_from_manifest_round(
    *,
    manifest: dict[str, Any],
    raw_root: Path,
    round_index: int,
    shard_indices: list[int],
) -> list[FetchRecord]:
    records: list[FetchRecord] = []
    ticker_ref = _raw_ref_for(raw_root, ENDPOINT_TICKER_MAP, round_index=round_index)
    if ticker_ref.exists():
        records.append(_fetch_record_from_wrapper(_repo_rel(ticker_ref), raw_root=raw_root))
    entries = {
        entry["shard_index"]: entry
        for entry in manifest["completed_shards"]
        if isinstance(entry, dict) and entry.get("source") == "resume_scan" and entry.get("shard_index") in set(shard_indices)
    }
    for shard_index in shard_indices:
        entry = entries.get(shard_index)
        if entry is None:
            raise Bankruptcy8kCandidateResumeScanError(f"manifest is missing completed shard {shard_index}")
        for symbol in entry["symbols"]:
            records.append(_fetch_record_from_wrapper(entry["raw_refs_by_symbol"][symbol], raw_root=raw_root))
    return records


def _build_source_packet(
    *,
    generated_at: str,
    observed_at: str,
    status_as_of: str,
    screen_path: Path,
    submissions_by_ticker: dict[str, Any],
) -> dict[str, Any]:
    try:
        return bounded_producer._build_source_packet(
            generated_at=generated_at,
            observed_at=observed_at,
            status_as_of=status_as_of,
            screen_path=screen_path,
            submissions_by_ticker=submissions_by_ticker,
        )
    except bounded_producer.Bankruptcy8kSourcePacketProducerError as exc:
        raise Bankruptcy8kCandidateResumeScanError(str(exc)) from exc


def _screen_counts(consumer_summary: dict[str, Any]) -> dict[str, int | bool]:
    metrics = consumer_summary["aggregate_shape_metrics"]
    return {
        "bankruptcy_screen_written": True,
        "screen_symbol_count": metrics["screen_symbol_count"],
        "bankruptcy_8k_positive_count": metrics["bankruptcy_8k_positive_count"],
        "screened_no_filing_count": metrics["screened_no_filing_count"],
        "parser_error_count": metrics["parser_error_count"],
    }


def _build_summary(
    *,
    generated_at: str,
    observed_at: str,
    context: dict[str, Any],
    manifest: dict[str, Any],
    round_plan: dict[str, Any],
    records: list[FetchRecord],
    raw_root: Path,
    manifest_path: Path,
    source_packet_path: Path,
    screen_path: Path,
    summary_path: Path,
    consumer_summary_path: Path,
    sec_user_agent: sample_validation.EnvValue,
    consumer_summary: dict[str, Any],
) -> dict[str, Any]:
    completed_indices = _completed_indices(manifest)
    completed_symbol_count = sum(len(entry["symbols"]) for entry in manifest["completed_shards"])
    full_complete = len(completed_indices) == context["total_shard_count"]
    return {
        "schema_name": "us_short_batch5_bankruptcy_8k_candidate_resume_scan_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_bankruptcy_8k_candidate_resume_scan_summary.schema.json",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "resumable_candidate_universe_bankruptcy_8k_sec_submissions_scan",
            "status": "full_candidate_universe_scan_completed" if full_complete else "resume_round_source_packet_and_bankruptcy_screen_written",
            "network_access_performed": True,
            "provider_calls_performed": True,
            "raw_payload_storage_performed": True,
            "source_packet_written": True,
            "bankruptcy_screen_written_by_consumer": True,
            "consumer_summary_written": True,
            "run_fetch_invoked": False,
            "status_records_written": False,
            "full_market_scan_performed": False,
            "full_candidate_universe_scan_completed": full_complete,
            "candidate_artifact_written": False,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "broker_or_order_execution_performed": False,
            "ship_gate_or_live_normalized_evidence_claimed": False,
            "a_share_crossing_performed": False,
        },
        "decision_clock": {
            "expected_decision_date": context["expected_decision_date"],
            "status_as_of": context["status_as_of"],
            "source_observed_at": observed_at,
        },
        "environment": {
            "sec_fair_access_user_agent_present": True,
            "sec_fair_access_user_agent_source": sec_user_agent.source,
            "environment_values_logged": False,
            "secrets_logged": False,
            "sec_credentials_required": False,
        },
        "round_plan": round_plan,
        "manifest": {
            "manifest_path": _repo_rel(manifest_path),
            "manifest_gitignored": _git_ignored(manifest_path),
            "candidate_artifact_row_count": context["candidate_artifact_row_count"],
            "candidate_artifact_eligible_count": context["candidate_artifact_eligible_count"],
            "eligible_after_exclusions_count": context["eligible_after_exclusions_count"],
            "completed_shard_count": len(completed_indices),
            "resume_completed_shard_count": len(_resume_completed_indices(manifest)),
            "completed_symbol_count": completed_symbol_count,
            "round_runs_recorded": len(manifest["round_runs"]),
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls_per_round": 1 + round_plan["max_shards_per_round"] * SHARD_SIZE,
            "actual_total_endpoint_calls": len(records),
            "sec_ticker_reference_calls": sum(1 for record in records if record.endpoint_family == ENDPOINT_TICKER_MAP),
            "sec_company_submissions_calls": sum(1 for record in records if record.endpoint_family == ENDPOINT_SUBMISSIONS),
            "endpoint_error_count": sum(1 for record in records if not record.ok),
            "retry_count_allowed": 0,
            "retry_count_used": 0,
            "within_budget": len(records) <= 1 + round_plan["max_shards_per_round"] * SHARD_SIZE,
        },
        "endpoint_results": [_summarize_endpoint(record) for record in records],
        "storage": {
            "raw_payload_root": _repo_rel(raw_root),
            "raw_payload_root_gitignored": _git_ignored(raw_root),
            "source_packet_path": _repo_rel(source_packet_path),
            "source_packet_path_gitignored": _git_ignored(source_packet_path),
            "bankruptcy_screen_output_path": _repo_rel(screen_path),
            "bankruptcy_screen_output_gitignored": _git_ignored(screen_path),
            "producer_tracked_summary_path": _repo_rel(summary_path),
            "consumer_tracked_summary_path": _repo_rel(consumer_summary_path),
            "tracked_summaries_contain_raw_payload": False,
            "tracked_summaries_contain_request_urls": False,
            "tracked_summaries_contain_secrets": False,
        },
        "source_packet": {
            "schema_ref": "schemas/us_short_batch5_bankruptcy_8k_source_packet.schema.json",
            "input_symbol_count": consumer_summary["aggregate_shape_metrics"]["input_symbol_count"],
            "source_contract_input_source": SOURCE_PACKET_INPUT_SOURCE,
        },
        "consumer_screen": _screen_counts(consumer_summary),
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_scan_performed": False,
            "full_candidate_universe_scan_completed_only_by_scan": full_complete,
            "status_records_written": False,
            "run_fetch_invoked": False,
            "candidate_artifact_written": False,
            "datahub_consumed": False,
            "production_ready_claimed": False,
            "ship_gate_evidence_claimed": False,
            "live_normalized_evidence_claimed": False,
            "broker_or_order_automation": False,
            "a_share_crossing_performed": False,
        },
        "limitations": [
            "This producer only scans SEC company submissions for bankruptcy 8-K Item 1.03 signals; it does not invoke run_fetch or write status_records.",
            "The three-round guarantee depends on max_shards_per_round=35 and the first two 25-symbol shards being precompleted.",
            "Raw SEC payloads stay gitignored; tracked summaries exclude request URLs, raw SEC arrays, accessions, and environment values.",
            "No DataHub, production storage, provider selection, live-normalized evidence, ship-gate evidence, broker/order automation, or A-share crossing is claimed.",
        ],
    }


def _assert_summary_safe_text(text: str, sensitive_values: list[str]) -> None:
    try:
        bounded_producer._assert_summary_safe_text(text, sensitive_values)
    except bounded_producer.Bankruptcy8kSourcePacketProducerError as exc:
        raise Bankruptcy8kCandidateResumeScanError(str(exc)) from exc


def _write_summary_validated(summary: dict[str, Any], path: Path, sensitive_values: list[str]) -> None:
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="resume scan summary")
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_summary_safe_text(text, sensitive_values)
    _write_json_atomic(summary, path, field="resume_scan_summary")


def _common_preflight(
    *,
    candidate_artifact_path: Path | str,
    expected_decision_date: str,
    manifest_path: Path | str,
    output_source_packet_path: Path | str | None,
    output_screen_path: Path | str | None,
    summary_path: Path | str | None,
    consumer_summary_path: Path | str | None,
    raw_root: Path | str | None,
    round_index: int,
    max_shards_per_round: int,
    exclude_symbols: list[str] | tuple[str, ...] | None,
    precompleted_shard_indices: list[int] | tuple[int, ...],
    generated_at: str | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Path]]:
    _validate_round_controls(round_index, max_shards_per_round)
    generated_at = generated_at or iso_now()
    candidate_path = _validate_state_json_path(candidate_artifact_path, field="candidate_artifact_path", must_exist=True)
    manifest_path = _validate_state_json_path(manifest_path, field="manifest_path")
    source_packet_path = _validate_state_json_path(
        _resolve_default_path(output_source_packet_path, round_index=round_index, key="source_packet"),
        field="output_source_packet_path",
    )
    screen_path = _validate_state_json_path(
        _resolve_default_path(output_screen_path, round_index=round_index, key="screen"),
        field="output_screen_path",
    )
    summary_path = _validate_summary_path(
        _resolve_default_path(summary_path, round_index=round_index, key="summary"),
        field="summary_path",
    )
    consumer_summary_path = _validate_summary_path(
        _resolve_default_path(consumer_summary_path, round_index=round_index, key="consumer_summary"),
        field="consumer_summary_path",
    )
    raw_root = _validate_raw_root(_resolve_default_path(raw_root, round_index=round_index, key="raw_root"))
    context = _candidate_context(
        candidate_artifact_path=candidate_path,
        expected_decision_date=expected_decision_date,
        exclude_symbols=exclude_symbols,
    )
    precompleted = [int(value) for value in precompleted_shard_indices]
    manifest = _load_or_init_manifest(
        context=context,
        candidate_artifact_path=candidate_path,
        manifest_path=manifest_path,
        precompleted_shard_indices=precompleted,
        generated_at=generated_at,
    )
    plan = _build_round_plan(
        context=context,
        manifest=manifest,
        round_index=round_index,
        max_shards_per_round=max_shards_per_round,
    )
    paths = {
        "candidate": candidate_path,
        "manifest": manifest_path,
        "source_packet": source_packet_path,
        "screen": screen_path,
        "summary": summary_path,
        "consumer_summary": consumer_summary_path,
        "raw_root": raw_root,
    }
    return context, manifest, plan, paths


def run_preflight(
    *,
    candidate_artifact_path: Path | str = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    expected_decision_date: str = "20260706",
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    output_source_packet_path: Path | str | None = None,
    output_screen_path: Path | str | None = None,
    summary_path: Path | str | None = None,
    consumer_summary_path: Path | str | None = None,
    raw_root: Path | str | None = None,
    round_index: int = 1,
    max_shards_per_round: int = MAX_SHARDS_PER_ROUND,
    exclude_symbols: list[str] | tuple[str, ...] | None = ("NVDA", "MSFT", "AAPL"),
    precompleted_shard_indices: list[int] | tuple[int, ...] = DEFAULT_PRECOMPLETED_SHARD_INDICES,
    generated_at: str | None = None,
) -> dict[str, Any]:
    context, manifest, plan, paths = _common_preflight(
        candidate_artifact_path=candidate_artifact_path,
        expected_decision_date=expected_decision_date,
        manifest_path=manifest_path,
        output_source_packet_path=output_source_packet_path,
        output_screen_path=output_screen_path,
        summary_path=summary_path,
        consumer_summary_path=consumer_summary_path,
        raw_root=raw_root,
        round_index=round_index,
        max_shards_per_round=max_shards_per_round,
        exclude_symbols=exclude_symbols,
        precompleted_shard_indices=precompleted_shard_indices,
        generated_at=generated_at,
    )
    return {
        "schema_name": "us_short_batch5_bankruptcy_8k_candidate_resume_scan_preflight_result",
        "schema_version": "1.0.0",
        "generated_at": generated_at or iso_now(),
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "preflight_status": "offline_preflight_passed_authorization_required_for_resume_round_fetch",
            "network_access_performed": False,
            "provider_calls_performed": False,
            "manifest_written": False,
            "source_packet_written": False,
            "bankruptcy_screen_written": False,
            "run_fetch_invoked": False,
            "status_records_written": False,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "ship_gate_evidence_claimed": False,
        },
        "round_plan": plan,
        "candidate_scope": {
            "candidate_artifact_path": _repo_rel(paths["candidate"]),
            "expected_decision_date": context["expected_decision_date"],
            "eligible_after_exclusions_count": context["eligible_after_exclusions_count"],
            "total_shard_count": context["total_shard_count"],
            "excluded_symbols": context["excluded_symbols"],
        },
        "paths": {
            "manifest_path": _repo_rel(paths["manifest"]),
            "raw_root": _repo_rel(paths["raw_root"]),
            "source_packet_path": _repo_rel(paths["source_packet"]),
            "screen_path": _repo_rel(paths["screen"]),
            "summary_path": _repo_rel(paths["summary"]),
            "consumer_summary_path": _repo_rel(paths["consumer_summary"]),
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls_per_round": 1 + max_shards_per_round * SHARD_SIZE,
            "planned_total_endpoint_calls": 0 if plan["finalize_only"] else 1 + plan["target_symbol_count"],
            "retry_count_allowed": 0,
        },
        "manifest_existing_completed_shards": sorted(_completed_indices(manifest)),
    }


def run_resume_round(
    *,
    candidate_artifact_path: Path | str = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    expected_decision_date: str = "20260706",
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    output_source_packet_path: Path | str | None = None,
    output_screen_path: Path | str | None = None,
    summary_path: Path | str | None = None,
    consumer_summary_path: Path | str | None = None,
    raw_root: Path | str | None = None,
    round_index: int = 1,
    max_shards_per_round: int = MAX_SHARDS_PER_ROUND,
    exclude_symbols: list[str] | tuple[str, ...] | None = ("NVDA", "MSFT", "AAPL"),
    precompleted_shard_indices: list[int] | tuple[int, ...] = DEFAULT_PRECOMPLETED_SHARD_INDICES,
    client: sample_validation.JsonHttpClient | None = None,
    confirm_user_authorization: bool = False,
    generated_at: str | None = None,
    observed_at: str | None = None,
    sec_sleep_seconds: float = SEC_SLEEP_SECONDS,
) -> dict[str, Any]:
    context, manifest, plan, paths = _common_preflight(
        candidate_artifact_path=candidate_artifact_path,
        expected_decision_date=expected_decision_date,
        manifest_path=manifest_path,
        output_source_packet_path=output_source_packet_path,
        output_screen_path=output_screen_path,
        summary_path=summary_path,
        consumer_summary_path=consumer_summary_path,
        raw_root=raw_root,
        round_index=round_index,
        max_shards_per_round=max_shards_per_round,
        exclude_symbols=exclude_symbols,
        precompleted_shard_indices=precompleted_shard_indices,
        generated_at=generated_at,
    )
    if not confirm_user_authorization:
        raise Bankruptcy8kCandidateResumeScanError("resume scan round requires confirm_user_authorization")
    generated_at = generated_at or iso_now()
    observed_at = observed_at or generated_at
    sec_user_agent = sample_validation.read_required_env("SEC_USER_AGENT")
    client = client or sample_validation.JsonHttpClient()
    records: list[FetchRecord] = []
    headers = {"User-Agent": sec_user_agent.value}

    if plan["finalize_only"]:
        records = _records_from_manifest_round(
            manifest=manifest,
            raw_root=paths["raw_root"],
            round_index=round_index,
            shard_indices=plan["round_window_shard_indices"],
        )
    else:
        ticker_ref = _fetch_and_store(
            client=client,
            url=SEC_TICKER_MAP_URL,
            headers={**headers, "Host": "www.sec.gov"},
            raw_root=paths["raw_root"],
            endpoint_family=ENDPOINT_TICKER_MAP,
            round_index=round_index,
        )
        records.append(ticker_ref)
        if not ticker_ref.ok:
            raise Bankruptcy8kCandidateResumeScanError("SEC ticker reference fetch failed")
        try:
            cik_by_symbol = bounded_producer._parse_sec_ticker_map(ticker_ref.payload)
        except bounded_producer.Bankruptcy8kSourcePacketProducerError as exc:
            raise Bankruptcy8kCandidateResumeScanError(str(exc)) from exc

        submission_count = 0
        for shard_index in plan["target_shard_indices"]:
            shard_records: list[FetchRecord] = []
            symbols = _shard_symbols(context["eligible_symbols"], shard_index)
            missing = [symbol for symbol in symbols if symbol not in cik_by_symbol]
            if missing:
                raise Bankruptcy8kCandidateResumeScanError(f"SEC ticker reference missing CIK for selected symbols: {missing}")
            for symbol in symbols:
                if submission_count > 0 and sec_sleep_seconds > 0:
                    time.sleep(sec_sleep_seconds)
                record = _fetch_and_store(
                    client=client,
                    url=_submissions_url(cik_by_symbol[symbol]),
                    headers={**headers, "Host": "data.sec.gov"},
                    raw_root=paths["raw_root"],
                    endpoint_family=ENDPOINT_SUBMISSIONS,
                    round_index=round_index,
                    shard_index=shard_index,
                    symbol=symbol,
                )
                records.append(record)
                shard_records.append(record)
                submission_count += 1
                if not record.ok:
                    raise Bankruptcy8kCandidateResumeScanError(f"SEC submissions fetch failed for {symbol}")
            _record_completed_shard(
                manifest=manifest,
                context=context,
                shard_index=shard_index,
                round_index=round_index,
                records=shard_records,
                completed_at=observed_at,
            )
            _save_manifest(manifest, paths["manifest"], updated_at=observed_at)

    submissions = _load_resume_submissions(manifest, raw_root=paths["raw_root"])
    packet = _build_source_packet(
        generated_at=generated_at,
        observed_at=observed_at,
        status_as_of=context["status_as_of"],
        screen_path=paths["screen"],
        submissions_by_ticker=submissions,
    )
    _write_json_atomic(packet, paths["source_packet"], field="source_packet")
    try:
        consumer_summary = source_packet_runner.run_packet(
            paths["source_packet"],
            summary_path=paths["consumer_summary"],
            generated_at=generated_at,
        )
    except source_packet_runner.BankruptcySourcePacketError as exc:
        raise Bankruptcy8kCandidateResumeScanError(str(exc)) from exc
    manifest["round_runs"].append(
        {
            "round_index": round_index,
            "summary_path": _repo_rel(paths["summary"]),
            "consumer_summary_path": _repo_rel(paths["consumer_summary"]),
            "target_shard_indices": plan["target_shard_indices"],
            "finalized_shard_indices": plan["round_window_shard_indices"] if plan["finalize_only"] else plan["target_shard_indices"],
            "finalize_only": plan["finalize_only"],
            "target_symbol_count": plan["target_symbol_count"],
            "completed_at": observed_at,
        }
    )
    _save_manifest(manifest, paths["manifest"], updated_at=observed_at)

    summary = _build_summary(
        generated_at=generated_at,
        observed_at=observed_at,
        context=context,
        manifest=manifest,
        round_plan=plan,
        records=records,
        raw_root=paths["raw_root"],
        manifest_path=paths["manifest"],
        source_packet_path=paths["source_packet"],
        screen_path=paths["screen"],
        summary_path=paths["summary"],
        consumer_summary_path=paths["consumer_summary"],
        sec_user_agent=sec_user_agent,
        consumer_summary=consumer_summary,
    )
    _write_summary_validated(summary, paths["summary"], [sec_user_agent.value])
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "US-short Batch5 resumable bankruptcy 8-K candidate-universe SEC scan. "
            "Runs at most 35 25-symbol shards per round, records a gitignored resume manifest, writes one aggregate "
            "source packet/screen per round, and never invokes run_fetch/status_records/DataHub/production/ship-gate."
        )
    )
    parser.add_argument("--candidate-artifact-path", type=Path, default=DEFAULT_CANDIDATE_ARTIFACT_PATH)
    parser.add_argument("--expected-decision-date", default="20260706")
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--round-index", type=int, required=True)
    parser.add_argument("--max-shards-per-round", type=int, default=MAX_SHARDS_PER_ROUND)
    parser.add_argument("--exclude-symbols", nargs="*", default=["NVDA", "MSFT", "AAPL"])
    parser.add_argument("--precompleted-shard-indices", type=int, nargs="*", default=list(DEFAULT_PRECOMPLETED_SHARD_INDICES))
    parser.add_argument("--output-source-packet-path", type=Path)
    parser.add_argument("--output-screen-path", type=Path)
    parser.add_argument("--summary-path", type=Path)
    parser.add_argument("--consumer-summary-path", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--generated-at")
    parser.add_argument("--observed-at")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--confirm-user-authorization", action="store_true")
    parser.add_argument("--sec-sleep-seconds", type=float, default=SEC_SLEEP_SECONDS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    kwargs = {
        "candidate_artifact_path": args.candidate_artifact_path,
        "expected_decision_date": args.expected_decision_date,
        "manifest_path": args.manifest_path,
        "output_source_packet_path": args.output_source_packet_path,
        "output_screen_path": args.output_screen_path,
        "summary_path": args.summary_path,
        "consumer_summary_path": args.consumer_summary_path,
        "raw_root": args.raw_root,
        "round_index": args.round_index,
        "max_shards_per_round": args.max_shards_per_round,
        "exclude_symbols": args.exclude_symbols,
        "precompleted_shard_indices": args.precompleted_shard_indices,
        "generated_at": args.generated_at,
    }
    if args.preflight_only:
        result = run_preflight(**kwargs)
    else:
        result = run_resume_round(
            **kwargs,
            confirm_user_authorization=args.confirm_user_authorization,
            observed_at=args.observed_at,
            sec_sleep_seconds=args.sec_sleep_seconds,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
