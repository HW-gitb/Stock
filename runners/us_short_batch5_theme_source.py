from __future__ import annotations

import argparse
import json
import math
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
from engine.us_short_industry_heat import IndustryHeatError, industry_heat_block  # noqa: E402
from engine.us_short_provisional_theme_heat import (  # noqa: E402
    ProvisionalThemeHeatError,
    provisional_theme_heat_block,
)
from engine.us_short_seam_theme import ThemeSeamError, project_theme_block  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402


PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_theme_source_packet.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_theme_source_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_theme_source_summary_20260705.json"
SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_theme_source_20260705")
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260706.json"
DEFAULT_SOURCE_PACKET_PATH = STATE_US_SHORT_DIR / "us_short_batch5_theme_source_20260705_packet.json"
DEFAULT_OUTPUT_PROJECTION_PATH = STATE_US_SHORT_DIR / "us_short_batch5_theme_source_20260705_theme.json"
BENCHMARK_SYMBOLS = ("SPY", "QQQ")
MAX_SYMBOLS = 3


class ThemeSourceError(ValueError):
    """Local theme/GICS source packet cannot be consumed safely."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _prepare_json_target(path: Path, *, field: str) -> None:
    if path.parent.exists() and not path.parent.is_dir():
        raise ThemeSourceError(f"{field} parent must be a directory: {_display_path(path.parent)}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ThemeSourceError(f"{field} parent could not be created: {_display_path(path.parent)}") from exc
    if path.exists() and path.is_dir():
        raise ThemeSourceError(f"{field} must be a file path, not a directory: {_display_path(path)}")


def _write_json_atomic(payload: Any, path: Path, *, field: str = "json output") -> None:
    _prepare_json_target(path, field=field)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ThemeSourceError(f"{field} could not be written atomically: {_display_path(path)}") from exc


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
        raise ThemeSourceError(f"{field} must stay under the repository root") from exc
    return resolved


def _existing_file(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    if not resolved.exists() or not resolved.is_file():
        raise ThemeSourceError(f"{field} must be an existing file: {_display_path(resolved)}")
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


def _validate_state_json_file(path: Path | str, *, field: str, must_exist: bool) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise ThemeSourceError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise ThemeSourceError(f"{field} must be a .json path")
    if must_exist and (not resolved.exists() or not resolved.is_file()):
        raise ThemeSourceError(f"{field} must be an existing file: {_display_path(resolved)}")
    if not _git_ignored(resolved):
        raise ThemeSourceError(f"{field} must be gitignored")
    return resolved


def _validate_summary_path(path: Path | str) -> Path:
    resolved = _resolve_repo_path(path, field="summary_path")
    if resolved.suffix != ".json":
        raise ThemeSourceError("summary_path must be a .json path")
    if resolved == SUMMARY_PATH.resolve():
        return resolved
    try:
        resolved.relative_to((ROOT / SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise ThemeSourceError(
            "summary_path must be the canonical tracked summary or under this runner's provider_samples folder"
        ) from exc
    if not _git_ignored(resolved):
        raise ThemeSourceError("non-canonical summary_path must be gitignored")
    return resolved


def _valid_observed_at(value: str) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _valid_ymd(value: Any):
    if not (type(value) is str and len(value) == 10):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _compact_to_ymd(value: str, *, field: str) -> str:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise ThemeSourceError(f"{field} must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise ThemeSourceError(f"{field} must be a real calendar date") from exc


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        out = float(value)
    except (OverflowError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _validate_schema(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise ThemeSourceError("jsonschema is required for theme source validation") from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise ThemeSourceError(f"{label} schema rejected {len(errors)} field(s): {joined}") from errors[0]


def _selected_symbols(value: list[str]) -> list[str]:
    if type(value) is not list or not value or len(value) > MAX_SYMBOLS:
        raise ThemeSourceError("source_contract.selected_symbols must be a 1-3 item list")
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if type(raw) is not str:
            raise ThemeSourceError("source_contract.selected_symbols must contain exact strings")
        ticker = canonical_us_ticker(raw)
        if ticker is None:
            raise ThemeSourceError("selected_symbols must be canonicalizable US tickers")
        if ticker in seen:
            raise ThemeSourceError(f"duplicate selected symbol: {ticker}")
        seen.add(ticker)
        out.append(ticker)
    return out


def _canonical_ticker(raw: Any, *, field: str) -> str:
    if type(raw) is not str:
        raise ThemeSourceError(f"{field} must contain exact ticker strings")
    ticker = canonical_us_ticker(raw)
    if ticker is None:
        raise ThemeSourceError(f"{field} must contain canonicalizable US tickers")
    return ticker


def _canonical_theme_id(raw: Any, *, field: str) -> str:
    if type(raw) is not str:
        raise ThemeSourceError(f"{field} theme_id must be exact string")
    theme_id = raw.strip()
    if not theme_id:
        raise ThemeSourceError(f"{field} theme_id must be non-empty")
    return theme_id


def _validated_candidate_context(
    *,
    candidate_artifact_path: Path,
    expected_decision_date: str,
    candidate_price_basis_date: str,
    selected_symbols: list[str],
) -> dict[str, Any]:
    artifact = _read_json(candidate_artifact_path)
    eligibility_governance = load_eligibility_governance(ELIGIBILITY_GOVERNANCE_PATH)
    try:
        universe_fetch.validate_candidate_artifact(
            artifact,
            expected_decision_date=expected_decision_date,
            governance=eligibility_governance,
        )
    except Exception as exc:
        raise ThemeSourceError(f"candidate artifact failed validation: {exc}") from exc
    if artifact["price_basis_date"] != candidate_price_basis_date:
        raise ThemeSourceError(
            "source packet candidate_price_basis_date must match the candidate artifact price_basis_date"
        )
    rows_by_ticker = {row["ticker"]: row for row in artifact["rows"]}
    eligible = set(artifact["eligible_tickers"])
    missing = [ticker for ticker in selected_symbols if ticker not in rows_by_ticker]
    not_eligible = [ticker for ticker in selected_symbols if ticker not in eligible]
    if missing or not_eligible:
        raise ThemeSourceError(
            f"selected_symbols must exist and be Pass1-eligible (missing {missing}, not_eligible {not_eligible})"
        )
    return {
        "decision_date": artifact["decision_date"],
        "candidate_price_basis_date": artifact["price_basis_date"],
        "price_basis_date": _compact_to_ymd(artifact["price_basis_date"], field="candidate.price_basis_date"),
        "eligible_count": len(artifact["eligible_tickers"]),
        "row_count": len(artifact["rows"]),
    }


def _validate_series_values(
    *,
    label: str,
    series: dict[str, Any],
    expected_as_of: str,
    session: str,
    adjustment_mode: str,
    min_points: int,
) -> None:
    if series["as_of"] != expected_as_of:
        raise ThemeSourceError(f"{label} series.as_of must equal the price_basis_date")
    if series["session"] != session:
        raise ThemeSourceError(f"{label} series.session mismatch")
    if series["adjustment_mode"] != adjustment_mode:
        raise ThemeSourceError(f"{label} series.adjustment_mode mismatch")
    as_of_date = _valid_ymd(expected_as_of)
    if as_of_date is None:
        raise ThemeSourceError("price_basis_date must be YYYY-MM-DD")
    points = series["points"]
    if len(points) < min_points:
        raise ThemeSourceError(f"{label} price series has fewer than {min_points} points")
    previous = None
    for point in points:
        date_value = _valid_ymd(point["date"])
        if date_value is None:
            raise ThemeSourceError(f"{label} point.date must be YYYY-MM-DD")
        if previous is not None and date_value <= previous:
            raise ThemeSourceError(f"{label} point dates must be strictly ascending")
        previous = date_value
        if date_value > as_of_date:
            raise ThemeSourceError(f"{label} source packet contains a future price point")
        close = _finite_number(point["close"])
        if close is None or close <= 0.0:
            raise ThemeSourceError(f"{label} point.close must be finite and positive")
        if "volume" in point and point["volume"] is not None:
            volume = _finite_number(point["volume"])
            if volume is None or volume < 0.0:
                raise ThemeSourceError(f"{label} point.volume must be finite and non-negative")


def _canonicalize_industry_members(
    raw: dict[str, Any],
    *,
    selected: list[str],
    expected_as_of: str,
    session: str,
    adjustment_mode: str,
    min_points: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw_ticker, row in raw.items():
        ticker = _canonical_ticker(raw_ticker, field="industry_members_by_ticker")
        if ticker in out:
            raise ThemeSourceError(f"duplicate canonical ticker in industry_members_by_ticker: {ticker}")
        sector = row["sector"].strip()
        if not sector:
            raise ThemeSourceError(f"{ticker} sector must be non-empty")
        _validate_series_values(
            label=f"industry_members_by_ticker.{ticker}",
            series=row["series"],
            expected_as_of=expected_as_of,
            session=session,
            adjustment_mode=adjustment_mode,
            min_points=min_points,
        )
        out[ticker] = {"sector": sector, "series": row["series"]}
    missing_selected = [ticker for ticker in selected if ticker not in out]
    if missing_selected:
        raise ThemeSourceError(f"selected symbols missing from full GICS peer pool: {missing_selected}")
    if len(out) <= len(selected):
        raise ThemeSourceError("industry_members_by_ticker must be wider than selected_symbols")
    return out


def _canonicalize_themes(
    themes_by_id: dict[str, Any],
    membership_by_id: dict[str, Any],
    *,
    expected_as_of: str,
    session: str,
    adjustment_mode: str,
    min_points: int,
) -> tuple[dict[str, Any], dict[str, list[str]], int]:
    out_themes: dict[str, Any] = {}
    out_membership: dict[str, list[str]] = {}
    normalized_theme_ids: set[str] = set()
    for raw_theme_id, theme in themes_by_id.items():
        theme_id = _canonical_theme_id(raw_theme_id, field="provisional_themes_by_id")
        if theme_id in normalized_theme_ids:
            raise ThemeSourceError("duplicate normalized theme_id in provisional_themes_by_id")
        normalized_theme_ids.add(theme_id)
        members: dict[str, Any] = {}
        for raw_ticker, series in theme["members"].items():
            ticker = _canonical_ticker(raw_ticker, field=f"provisional_themes_by_id.{theme_id}.members")
            if ticker in members:
                raise ThemeSourceError(f"duplicate canonical ticker in provisional theme {theme_id}")
            _validate_series_values(
                label=f"provisional_themes_by_id.{theme_id}.{ticker}",
                series=series,
                expected_as_of=expected_as_of,
                session=session,
                adjustment_mode=adjustment_mode,
                min_points=min_points,
            )
            members[ticker] = series
        out_themes[theme_id] = {"members": members}
    if set(out_themes) != {_canonical_theme_id(theme_id, field="theme_members_by_id") for theme_id in membership_by_id}:
        raise ThemeSourceError("theme_members_by_id keys must match provisional_themes_by_id")
    for raw_theme_id, raw_members in membership_by_id.items():
        theme_id = _canonical_theme_id(raw_theme_id, field="theme_members_by_id")
        if type(raw_members) is not list:
            raise ThemeSourceError("theme_members_by_id values must be exact lists")
        members: list[str] = []
        seen: set[str] = set()
        for raw_ticker in raw_members:
            ticker = _canonical_ticker(raw_ticker, field=f"theme_members_by_id.{theme_id}")
            if ticker in seen:
                raise ThemeSourceError(f"duplicate canonical ticker in theme_members_by_id.{theme_id}")
            seen.add(ticker)
            members.append(ticker)
        if set(members) != set(out_themes[theme_id]["members"]):
            raise ThemeSourceError("theme_members_by_id values must match provisional_themes_by_id member keys")
        out_membership[theme_id] = members
    unique_theme_members = {ticker for members in out_membership.values() for ticker in members}
    return out_themes, out_membership, len(unique_theme_members)


def _sector_members_by_label(industry_members: dict[str, Any]) -> dict[str, set[str]]:
    members_by_sector: dict[str, set[str]] = {}
    for ticker, row in industry_members.items():
        members_by_sector.setdefault(row["sector"], set()).add(ticker)
    return members_by_sector


def _assert_scored_groups_have_nonselected_support(
    *,
    selected: list[str],
    industry_members: dict[str, Any],
    theme_members_by_id: dict[str, list[str]],
    industry_result: dict[str, Any],
    provisional_theme_result: dict[str, Any],
) -> None:
    selected_set = set(selected)
    sector_members = _sector_members_by_label(industry_members)
    selected_only_sectors = sorted(
        sector
        for sector in industry_result["sector_heat"]
        if not (sector_members.get(sector, set()) - selected_set)
    )
    selected_only_themes = sorted(
        theme_id
        for theme_id in provisional_theme_result["theme_heat"]
        if not (set(theme_members_by_id.get(theme_id, [])) - selected_set)
    )
    if selected_only_sectors or selected_only_themes:
        raise ThemeSourceError(
            "scored sector/theme groups must include at least one non-selected member "
            f"(selected_only_sectors={selected_only_sectors}, selected_only_themes={selected_only_themes})"
        )


def _load_context(
    *,
    candidate_artifact_path: Path,
    source_packet_path: Path,
    output_projection_path: Path,
    summary_path: Path,
    generated_at: str | None,
) -> dict[str, Any]:
    generated_at = generated_at or iso_now()
    if not _valid_observed_at(generated_at):
        raise ThemeSourceError("generated_at must be a timezone-aware RFC3339 instant")
    packet = _read_json(source_packet_path)
    _validate_schema(packet, PACKET_SCHEMA_PATH, label="theme source packet")

    if packet["scope"]["full_gics_peer_pool"] is not True:
        raise ThemeSourceError("source packet must declare full_gics_peer_pool")
    contract = packet["source_contract"]
    selected = _selected_symbols(contract["selected_symbols"])
    if tuple(contract["benchmark_symbols"]) != BENCHMARK_SYMBOLS:
        raise ThemeSourceError("benchmark_symbols must be exactly SPY/QQQ")
    if contract["membership_pool_basis"] != "full_gics_peer_pool_and_provisional_theme_members":
        raise ThemeSourceError("membership_pool_basis must be full_gics_peer_pool_and_provisional_theme_members")
    if contract["full_gics_peer_pool"] is not True:
        raise ThemeSourceError("source_contract.full_gics_peer_pool must be true")

    expected_decision_date = packet["decision_clock"]["expected_decision_date"]
    candidate_price_basis_date = packet["decision_clock"]["candidate_price_basis_date"]
    price_basis_date = packet["decision_clock"]["price_basis_date"]
    source_as_of = packet["decision_clock"]["source_as_of"]
    if price_basis_date != source_as_of:
        raise ThemeSourceError("decision_clock.price_basis_date and source_as_of must match")
    if _compact_to_ymd(candidate_price_basis_date, field="decision_clock.candidate_price_basis_date") != price_basis_date:
        raise ThemeSourceError("candidate_price_basis_date must normalize to price_basis_date")
    candidate_context = _validated_candidate_context(
        candidate_artifact_path=candidate_artifact_path,
        expected_decision_date=expected_decision_date,
        candidate_price_basis_date=candidate_price_basis_date,
        selected_symbols=selected,
    )

    session = contract["session"]
    adjustment_mode = contract["adjustment_mode"]
    min_points = contract["min_points_per_series"]
    for benchmark in BENCHMARK_SYMBOLS:
        _validate_series_values(
            label=f"benchmark_series_by_ticker.{benchmark}",
            series=packet["benchmark_series_by_ticker"][benchmark],
            expected_as_of=price_basis_date,
            session=session,
            adjustment_mode=adjustment_mode,
            min_points=min_points,
        )
    industry_members = _canonicalize_industry_members(
        packet["industry_members_by_ticker"],
        selected=selected,
        expected_as_of=price_basis_date,
        session=session,
        adjustment_mode=adjustment_mode,
        min_points=min_points,
    )
    themes_by_id, theme_members_by_id, theme_member_count = _canonicalize_themes(
        packet["provisional_themes_by_id"],
        packet["theme_members_by_id"],
        expected_as_of=price_basis_date,
        session=session,
        adjustment_mode=adjustment_mode,
        min_points=min_points,
    )
    if output_projection_path in {candidate_artifact_path, source_packet_path}:
        raise ThemeSourceError("output_projection_path must not overwrite input files")
    return {
        "generated_at": generated_at,
        "packet": packet,
        "selected_symbols": selected,
        "industry_members": industry_members,
        "themes_by_id": themes_by_id,
        "theme_members_by_id": theme_members_by_id,
        "theme_member_count": theme_member_count,
        "candidate_context": candidate_context,
        "candidate_artifact_path": candidate_artifact_path,
        "source_packet_path": source_packet_path,
        "output_projection_path": output_projection_path,
        "summary_path": summary_path,
    }


def _build_projection(context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    packet = context["packet"]
    benchmarks = packet["benchmark_series_by_ticker"]
    try:
        industry_result = industry_heat_block(
            context["industry_members"],
            spy_series=benchmarks["SPY"],
            qqq_series=benchmarks["QQQ"],
        )
        provisional_theme_result = provisional_theme_heat_block(
            context["themes_by_id"],
            spy_series=benchmarks["SPY"],
            qqq_series=benchmarks["QQQ"],
        )
        _assert_scored_groups_have_nonselected_support(
            selected=context["selected_symbols"],
            industry_members=context["industry_members"],
            theme_members_by_id=context["theme_members_by_id"],
            industry_result=industry_result,
            provisional_theme_result=provisional_theme_result,
        )
        projection = project_theme_block(
            industry_result=industry_result,
            provisional_theme_result=provisional_theme_result,
            theme_members_by_id=context["theme_members_by_id"],
            target_tickers=context["selected_symbols"],
        )
    except (IndustryHeatError, ProvisionalThemeHeatError, ThemeSeamError, ValueError) as exc:
        raise ThemeSourceError("theme source packet failed local projection") from exc
    return projection, industry_result, provisional_theme_result


def _build_summary(
    *,
    context: dict[str, Any],
    projection: dict[str, Any],
    industry_result: dict[str, Any],
    provisional_theme_result: dict[str, Any],
) -> dict[str, Any]:
    packet = context["packet"]
    contract = packet["source_contract"]
    selected = context["selected_symbols"]
    return {
        "schema_name": "us_short_batch5_theme_source_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_theme_source_summary.schema.json",
        "generated_at": context["generated_at"],
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "local_full_gics_and_theme_source_to_projection",
            "status": "theme_projection_written",
            "network_access_performed_by_runner": False,
            "provider_calls_performed_by_runner": False,
            "raw_payload_storage_performed_by_runner": False,
            "source_packet_consumed": True,
            "theme_projection_written": True,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "full_market_call_performed": False,
            "yfinance_consumption_performed": False,
            "broker_or_order_execution_performed": False,
            "ship_gate_or_live_normalized_evidence_claimed": False,
            "a_share_crossing_performed": False,
        },
        "decision_clock": dict(packet["decision_clock"]),
        "sample_universe": {
            "symbol_source": "caller_selected_from_validated_candidate_artifact",
            "symbols": selected,
            "max_symbols": MAX_SYMBOLS,
            "full_market_sample": False,
            "candidate_artifact_row_count": context["candidate_context"]["row_count"],
            "candidate_artifact_eligible_count": context["candidate_context"]["eligible_count"],
        },
        "paths": {
            "candidate_artifact_path": _repo_rel(context["candidate_artifact_path"]),
            "source_packet_path": _repo_rel(context["source_packet_path"]),
            "output_projection_path": _repo_rel(context["output_projection_path"]),
            "summary_path": _repo_rel(context["summary_path"]),
        },
        "storage": {
            "source_packet_path_gitignored": _git_ignored(context["source_packet_path"]),
            "output_projection_path_gitignored": _git_ignored(context["output_projection_path"]),
            "summary_path_gitignored": _git_ignored(context["summary_path"]),
            "summary_contains_price_rows": False,
            "summary_contains_raw_payload": False,
            "summary_contains_request_urls": False,
            "summary_contains_secrets": False,
        },
        "theme_source": {
            "industry_member_count": len(context["industry_members"]),
            "selected_symbol_count": len(selected),
            "theme_count": len(context["themes_by_id"]),
            "theme_member_count": context["theme_member_count"],
            "benchmark_symbols": list(BENCHMARK_SYMBOLS),
            "session": contract["session"],
            "adjustment_mode": contract["adjustment_mode"],
            "min_points_per_series": contract["min_points_per_series"],
            "full_gics_peer_pool_consumed": True,
            "provisional_theme_membership_consumed": True,
            "selected_symbol_only_membership_rejected": True,
            "scored_sector_count": len(industry_result["sector_heat"]),
            "insufficient_sector_count": len(industry_result["insufficient_sectors"]),
            "scored_theme_count": len(provisional_theme_result["theme_heat"]),
            "insufficient_theme_count": len(provisional_theme_result["insufficient_themes"]),
        },
        "projection_contract": {
            "target_count": projection["target_count"],
            "theme_scored_count": projection["scored_count"],
            "neutral_fill_count": len(projection["neutral_fill_tickers"]),
            "real_theme_or_gics_source_consumed": True,
            "full_gics_peer_pool_consumed": True,
            "selected_symbol_only_membership_rejected": True,
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
            "This runner consumes an already-built local full GICS/theme source packet; it does not fetch provider endpoints.",
            "The tracked summary excludes price rows, raw payloads, request URLs, and secrets.",
            "This narrows local theme/GICS source consumption only; provider health, DataHub, production, and ship-gate evidence remain out of scope.",
        ],
    }


def _assert_text_safe(text: str) -> None:
    lower = text.lower()
    forbidden = (
        "apikey=",
        "financialmodelingprep.com",
        "api.massive.com",
        "data.sec.gov",
        "www.sec.gov",
        "bearer ",
        "token=",
        "key=",
        "http://",
        "https://",
        "akia",
        "@",
        "\"payload\"",
        "\"raw_payload\"",
        "\"request_url\"",
        "\"points\"",
    )
    for fragment in forbidden:
        if fragment in lower:
            raise ThemeSourceError(f"summary contains forbidden fragment: {fragment}")


def _write_summary_validated(summary: dict[str, Any], summary_path: Path) -> None:
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="theme source summary")
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text)
    _write_json_atomic(summary, summary_path, field="summary_path")


def run_preflight(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    source_packet_path: Path = DEFAULT_SOURCE_PACKET_PATH,
    output_projection_path: Path = DEFAULT_OUTPUT_PROJECTION_PATH,
    summary_path: Path = SUMMARY_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    candidate_path = _existing_file(candidate_artifact_path, field="candidate_artifact_path")
    source_path = _validate_state_json_file(source_packet_path, field="source_packet_path", must_exist=True)
    output_path = _validate_state_json_file(output_projection_path, field="output_projection_path", must_exist=False)
    summary_resolved = _validate_summary_path(summary_path)
    context = _load_context(
        candidate_artifact_path=candidate_path,
        source_packet_path=source_path,
        output_projection_path=output_path,
        summary_path=summary_resolved,
        generated_at=generated_at,
    )
    projection, industry_result, provisional_theme_result = _build_projection(context)
    return {
        "schema_name": "us_short_batch5_theme_source_preflight_result",
        "schema_version": "1.0.0",
        "generated_at": context["generated_at"],
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "preflight_status": "offline_preflight_passed",
            "network_access_required": False,
            "provider_calls_performed_by_runner": False,
            "raw_payloads_read": False,
            "projection_file_written": False,
            "summary_file_written": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "preflight_checks": {
            "candidate_artifact_validated": True,
            "source_packet_schema_validated": True,
            "selected_symbols_pass1_eligible": True,
            "benchmarks_present": True,
            "full_gics_peer_pool_declared": True,
            "selected_symbol_only_membership_rejected": True,
            "projection_output_gitignored": True,
            "summary_path_allowed": True,
            "no_provider_fetch_by_runner": True,
            "no_datahub_or_production": True,
        },
        "projection_preview": {
            "target_count": projection["target_count"],
            "theme_scored_count": projection["scored_count"],
            "neutral_fill_count": len(projection["neutral_fill_tickers"]),
            "scored_sector_count": len(industry_result["sector_heat"]),
            "scored_theme_count": len(provisional_theme_result["theme_heat"]),
        },
        "paths": {
            "candidate_artifact_path": _repo_rel(candidate_path),
            "source_packet_path": _repo_rel(source_path),
            "output_projection_path": _repo_rel(output_path),
            "summary_path": _repo_rel(summary_resolved),
        },
    }


def run_packet(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    source_packet_path: Path = DEFAULT_SOURCE_PACKET_PATH,
    output_projection_path: Path = DEFAULT_OUTPUT_PROJECTION_PATH,
    summary_path: Path = SUMMARY_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    candidate_path = _existing_file(candidate_artifact_path, field="candidate_artifact_path")
    source_path = _validate_state_json_file(source_packet_path, field="source_packet_path", must_exist=True)
    output_path = _validate_state_json_file(output_projection_path, field="output_projection_path", must_exist=False)
    summary_resolved = _validate_summary_path(summary_path)
    context = _load_context(
        candidate_artifact_path=candidate_path,
        source_packet_path=source_path,
        output_projection_path=output_path,
        summary_path=summary_resolved,
        generated_at=generated_at,
    )
    projection, industry_result, provisional_theme_result = _build_projection(context)
    summary = _build_summary(
        context=context,
        projection=projection,
        industry_result=industry_result,
        provisional_theme_result=provisional_theme_result,
    )
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="theme source summary")
    _assert_text_safe(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    _prepare_json_target(output_path, field="output_projection_path")
    _prepare_json_target(summary_resolved, field="summary_path")
    _write_json_atomic(projection, output_path, field="output_projection_path")
    _write_summary_validated(summary, summary_resolved)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a US-short Batch5 theme projection from an already-authorized local full GICS/theme "
            "source packet. This runner never fetches providers, stores raw payloads, uses DataHub, or "
            "claims production/ship-gate evidence."
        )
    )
    parser.add_argument("--candidate-artifact-path", type=Path, default=DEFAULT_CANDIDATE_ARTIFACT_PATH)
    parser.add_argument("--source-packet-path", type=Path, default=DEFAULT_SOURCE_PACKET_PATH)
    parser.add_argument("--output-projection-path", type=Path, default=DEFAULT_OUTPUT_PROJECTION_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--generated-at")
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    kwargs = {
        "candidate_artifact_path": args.candidate_artifact_path,
        "source_packet_path": args.source_packet_path,
        "output_projection_path": args.output_projection_path,
        "summary_path": args.summary_path,
        "generated_at": args.generated_at,
    }
    result = run_preflight(**kwargs) if args.preflight_only else run_packet(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
