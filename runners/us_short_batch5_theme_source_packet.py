from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
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
from runners import us_short_batch5_theme_source as theme_consumer  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402


AUTHORIZATION_REF = "user_chat_20260705_us_short_theme_source_packet"
PLAN_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_theme_source_packet_plan.schema.json"
PACKET_SCHEMA_PATH = theme_consumer.PACKET_SCHEMA_PATH
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_theme_source_packet_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_theme_source_packet_summary_20260705.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_theme_source_packet_20260705")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_PLAN_PATH = ROOT / "docs" / "us_short_batch5_theme_source_packet_plan_20260705.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260706.json"
DEFAULT_OUTPUT_SOURCE_PACKET_PATH = STATE_US_SHORT_DIR / "us_short_batch5_theme_source_20260705_packet.json"
DEFAULT_OUTPUT_PROJECTION_PATH = STATE_US_SHORT_DIR / "us_short_batch5_theme_source_20260705_theme.json"
DEFAULT_CONSUMER_SUMMARY_PATH = theme_consumer.SUMMARY_PATH

PROFILE_ENDPOINT_FAMILY = "profile_or_company_metadata"
PRICE_ENDPOINT_FAMILY = "ticker_daily_aggregates_adjusted"
BENCHMARK_SYMBOLS = ("SPY", "QQQ")
MAX_SELECTED_SYMBOLS = 3
MAX_TOTAL_ENDPOINT_CALLS = 18
MIN_POINTS_PER_SERIES = 64
LOOKBACK_CALENDAR_DAYS = 140
MASSIVE_SLEEP_SECONDS = 13.0
MASSIVE_DAILY_AGGS_URL = (
    "https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day/{frm}/{to}"
    "?adjusted=true&sort=asc&limit=300&apiKey={key}"
)


class ThemeSourcePacketError(ValueError):
    """The bounded full theme/GICS source packet cannot be fetched or written safely."""


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
        raise ThemeSourcePacketError(f"{field} must stay under the repository root") from exc
    return resolved


def _existing_file(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    if not resolved.exists() or not resolved.is_file():
        raise ThemeSourcePacketError(f"{field} must be an existing file: {_display_path(resolved)}")
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
        raise ThemeSourcePacketError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise ThemeSourcePacketError(f"{field} must be a .json path")
    if must_exist and (not resolved.exists() or not resolved.is_file()):
        raise ThemeSourcePacketError(f"{field} must be an existing file: {_display_path(resolved)}")
    if not _git_ignored(resolved):
        raise ThemeSourcePacketError(f"{field} must be gitignored")
    return resolved


def _validate_raw_root(raw_root: Path | str) -> Path:
    resolved = _resolve_repo_path(raw_root, field="raw_root")
    approved = (ROOT / RAW_SAMPLE_REL_ROOT).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ThemeSourcePacketError(
            "raw_root must stay under provider_samples/us_short_batch5_theme_source_packet_20260705/"
        ) from exc
    try:
        sample_validation.validate_raw_root(resolved)
    except ValueError as exc:
        raise ThemeSourcePacketError(str(exc)) from exc
    if not _git_ignored(resolved):
        raise ThemeSourcePacketError("raw_root must be gitignored")
    return resolved


def _validate_producer_summary_path(path: Path | str) -> Path:
    resolved = _resolve_repo_path(path, field="producer_summary_path")
    if resolved.suffix != ".json":
        raise ThemeSourcePacketError("producer_summary_path must be a .json path")
    if resolved == SUMMARY_PATH.resolve():
        return resolved
    try:
        resolved.relative_to((ROOT / RAW_SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise ThemeSourcePacketError(
            "producer_summary_path must be the canonical tracked summary or under this runner's provider_samples folder"
        ) from exc
    if not _git_ignored(resolved):
        raise ThemeSourcePacketError("non-canonical producer_summary_path must be gitignored")
    return resolved


def _prepare_json_target(path: Path, *, field: str) -> None:
    if path.parent.exists() and not path.parent.is_dir():
        raise ThemeSourcePacketError(f"{field} parent must be a directory: {_display_path(path.parent)}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ThemeSourcePacketError(f"{field} parent could not be created: {_display_path(path.parent)}") from exc
    if path.exists() and path.is_dir():
        raise ThemeSourcePacketError(f"{field} must be a file path, not a directory: {_display_path(path)}")


def _write_json_atomic(payload: Any, path: Path, *, field: str) -> None:
    _prepare_json_target(path, field=field)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ThemeSourcePacketError(f"{field} could not be written atomically: {_display_path(path)}") from exc


def _valid_observed_at(value: str) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _date8_to_ymd(value: str, *, field: str) -> str:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise ThemeSourcePacketError(f"{field} must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise ThemeSourcePacketError(f"{field} must be a real calendar date") from exc


def _ymd(value: str, *, field: str):
    if type(value) is not str or len(value) != 10:
        raise ThemeSourcePacketError(f"{field} must be YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ThemeSourcePacketError(f"{field} must be a real calendar date") from exc


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        x = float(value)
    except (OverflowError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _validate_schema(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise ThemeSourcePacketError("jsonschema is required for theme source packet validation") from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise ThemeSourcePacketError(f"{label} schema rejected {len(errors)} field(s): {joined}") from errors[0]


def _canonical_ticker(raw: Any, *, field: str) -> str:
    if type(raw) is not str:
        raise ThemeSourcePacketError(f"{field} must contain exact ticker strings")
    ticker = canonical_us_ticker(raw)
    if ticker is None:
        raise ThemeSourcePacketError(f"{field} must contain canonicalizable US tickers")
    if ticker in BENCHMARK_SYMBOLS:
        raise ThemeSourcePacketError(f"{field} may not include SPY/QQQ")
    return ticker


def _selected_symbols(value: list[str] | tuple[str, ...]) -> list[str]:
    if type(value) not in (list, tuple) or not value or len(value) > MAX_SELECTED_SYMBOLS:
        raise ThemeSourcePacketError("selected_symbols must be a 1-3 item list/tuple")
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        ticker = _canonical_ticker(raw, field="selected_symbols")
        if ticker in seen:
            raise ThemeSourcePacketError(f"duplicate selected symbol: {ticker}")
        seen.add(ticker)
        out.append(ticker)
    return out


def _candidate_context(
    *,
    candidate_artifact_path: Path,
    expected_decision_date: str,
    selected_symbols: list[str],
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
        raise ThemeSourcePacketError(f"candidate artifact failed validation: {exc}") from exc
    rows_by_ticker = {row["ticker"]: row for row in artifact["rows"]}
    eligible = set(artifact["eligible_tickers"])
    missing = [ticker for ticker in selected_symbols if ticker not in rows_by_ticker]
    not_eligible = [ticker for ticker in selected_symbols if ticker not in eligible]
    if missing or not_eligible:
        raise ThemeSourcePacketError(
            f"selected_symbols must exist and be Pass1-eligible (missing {missing}, not_eligible {not_eligible})"
        )
    price_basis_ymd = _date8_to_ymd(artifact["price_basis_date"], field="candidate.price_basis_date")
    return {
        "expected_decision_date": artifact["decision_date"],
        "candidate_price_basis_date": artifact["price_basis_date"],
        "price_basis_date": price_basis_ymd,
        "source_as_of": price_basis_ymd,
        "row_count": len(artifact["rows"]),
        "eligible_count": len(artifact["eligible_tickers"]),
    }


def _load_plan(plan_path: Path) -> dict[str, Any]:
    plan = _read_json(plan_path)
    _validate_schema(plan, PLAN_SCHEMA_PATH, label="theme source packet plan")
    selected = _selected_symbols(plan["selected_symbols"])
    selected_set = set(selected)
    contract = plan["source_contract"]
    if contract["max_total_endpoint_calls"] != MAX_TOTAL_ENDPOINT_CALLS:
        raise ThemeSourcePacketError("plan max_total_endpoint_calls drifted from runner budget")
    if contract["min_points_per_series"] < MIN_POINTS_PER_SERIES:
        raise ThemeSourcePacketError("plan min_points_per_series must be >=64")
    if contract["lookback_calendar_days"] < 90:
        raise ThemeSourcePacketError("plan lookback_calendar_days must be >=90")

    peers_by_selected: dict[str, list[str]] = {}
    industry_symbols: list[str] = []
    seen_industry: set[str] = set()
    for ticker in selected:
        if ticker not in plan["industry_peer_symbols_by_selected"]:
            raise ThemeSourcePacketError(f"plan missing industry peers for selected symbol {ticker}")
        peers: list[str] = []
        peer_seen: set[str] = set()
        for raw_peer in plan["industry_peer_symbols_by_selected"][ticker]:
            peer = _canonical_ticker(raw_peer, field=f"industry_peer_symbols_by_selected.{ticker}")
            if peer in peer_seen:
                raise ThemeSourcePacketError(f"duplicate peer symbol for {ticker}: {peer}")
            peer_seen.add(peer)
            peers.append(peer)
        if not (set(peers) - selected_set):
            raise ThemeSourcePacketError(f"{ticker} must have at least one non-selected industry peer")
        peers_by_selected[ticker] = peers
        for member in [ticker] + peers:
            if member not in seen_industry:
                seen_industry.add(member)
                industry_symbols.append(member)

    max_industry_symbols = int(contract["max_industry_symbols"])
    if len(industry_symbols) > max_industry_symbols:
        raise ThemeSourcePacketError(
            f"industry symbol plan exceeds max_industry_symbols: {len(industry_symbols)} > {max_industry_symbols}"
        )

    themes_by_id: dict[str, list[str]] = {}
    for raw_theme_id, raw_members in plan["provisional_themes_by_id"].items():
        if type(raw_theme_id) is not str or not raw_theme_id.strip():
            raise ThemeSourcePacketError("theme ids must be non-empty exact strings")
        theme_id = raw_theme_id.strip()
        members: list[str] = []
        member_seen: set[str] = set()
        for raw_member in raw_members:
            member = _canonical_ticker(raw_member, field=f"provisional_themes_by_id.{theme_id}")
            if member in member_seen:
                raise ThemeSourcePacketError(f"duplicate theme member for {theme_id}: {member}")
            member_seen.add(member)
            members.append(member)
        if not (set(members) & selected_set):
            raise ThemeSourcePacketError(f"theme {theme_id} must include at least one selected symbol")
        if not (set(members) - selected_set):
            raise ThemeSourcePacketError(f"theme {theme_id} must include at least one non-selected member")
        unknown = sorted(set(members) - set(industry_symbols))
        if unknown:
            raise ThemeSourcePacketError(f"theme {theme_id} contains symbols outside the industry plan: {unknown}")
        themes_by_id[theme_id] = members

    selected_without_theme = [ticker for ticker in selected if not any(ticker in members for members in themes_by_id.values())]
    if selected_without_theme:
        raise ThemeSourcePacketError(f"selected symbols must appear in at least one provisional theme: {selected_without_theme}")

    return {
        "plan": plan,
        "selected_symbols": selected,
        "industry_symbols": industry_symbols,
        "peers_by_selected": peers_by_selected,
        "themes_by_id": themes_by_id,
        "expected_decision_date": plan["decision_clock"]["expected_decision_date"],
        "min_points_per_series": int(contract["min_points_per_series"]),
        "lookback_calendar_days": int(contract["lookback_calendar_days"]),
        "max_total_endpoint_calls": int(contract["max_total_endpoint_calls"]),
    }


def _massive_url(*, ticker: str, source_as_of: str, lookback_calendar_days: int, api_key: str) -> str:
    to_date = _ymd(source_as_of, field="source_as_of")
    frm = (to_date - timedelta(days=lookback_calendar_days)).isoformat()
    safe_ticker = urllib.parse.quote(ticker, safe="")
    return MASSIVE_DAILY_AGGS_URL.format(ticker=safe_ticker, frm=frm, to=source_as_of, key=api_key)


def _fetch_profile_records(
    *,
    industry_symbols: list[str],
    raw_root: Path,
    client: sample_validation.JsonHttpClient,
    fmp_env: sample_validation.EnvValue,
    max_total_endpoint_calls: int,
    existing_records: list[sample_validation.FetchRecord],
) -> list[sample_validation.FetchRecord]:
    records: list[sample_validation.FetchRecord] = []
    headers = {"User-Agent": "StockSystem/0.1 us-short-batch5-theme-source-packet"}
    for ticker in industry_symbols:
        try:
            sample_validation.assert_endpoint_budget_available(existing_records + records, max_total_endpoint_calls)
        except RuntimeError as exc:
            raise ThemeSourcePacketError(str(exc)) from exc
        records.append(
            sample_validation.fetch_and_store(
                client,
                url=sample_validation.fmp_url("profile", ticker, {}, fmp_env.value, endpoint_mode="stable"),
                provider_id="financial_modeling_prep",
                endpoint_family=PROFILE_ENDPOINT_FAMILY,
                symbol=ticker,
                raw_root=raw_root,
                headers=headers,
            )
        )
    return records


def _fetch_price_records(
    *,
    required_symbols: list[str],
    source_as_of: str,
    raw_root: Path,
    client: sample_validation.JsonHttpClient,
    massive_env: sample_validation.EnvValue,
    lookback_calendar_days: int,
    massive_sleep_seconds: float,
    max_total_endpoint_calls: int,
    existing_records: list[sample_validation.FetchRecord],
) -> list[sample_validation.FetchRecord]:
    records: list[sample_validation.FetchRecord] = []
    headers = {"User-Agent": "StockSystem/0.1 us-short-batch5-theme-source-packet"}
    for idx, ticker in enumerate(required_symbols):
        if idx > 0 and massive_sleep_seconds > 0:
            time.sleep(massive_sleep_seconds)
        try:
            sample_validation.assert_endpoint_budget_available(
                existing_records + records,
                max_total_endpoint_calls,
            )
        except RuntimeError as exc:
            raise ThemeSourcePacketError(str(exc)) from exc
        records.append(
            sample_validation.fetch_and_store(
                client,
                url=_massive_url(
                    ticker=ticker,
                    source_as_of=source_as_of,
                    lookback_calendar_days=lookback_calendar_days,
                    api_key=massive_env.value,
                ),
                provider_id="massive",
                endpoint_family=PRICE_ENDPOINT_FAMILY,
                symbol=ticker,
                raw_root=raw_root,
                headers=headers,
            )
        )
    return records


def _profile_row(record: sample_validation.FetchRecord) -> dict[str, Any]:
    if not record.ok:
        raise ThemeSourcePacketError(f"FMP profile endpoint failed for {record.symbol}: {record.error_type}")
    payload = record.payload
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        row = payload[0]
    elif isinstance(payload, dict):
        row = payload
    else:
        raise ThemeSourcePacketError(f"FMP profile payload was not object/list for {record.symbol}")
    symbol = canonical_us_ticker(str(row.get("symbol") or record.symbol or ""))
    if symbol != record.symbol:
        raise ThemeSourcePacketError(f"FMP profile symbol mismatch for {record.symbol}")
    sector = row.get("sector")
    if type(sector) is not str or not sector.strip():
        raise ThemeSourcePacketError(f"FMP profile missing sector for {record.symbol}")
    return {"symbol": symbol, "sector": sector.strip()}


def _series_from_record(record: sample_validation.FetchRecord, *, min_points_per_series: int) -> dict[str, Any]:
    if not record.ok:
        raise ThemeSourcePacketError(f"Massive price endpoint failed for {record.symbol}: {record.error_type}")
    payload = record.payload
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ThemeSourcePacketError(f"Massive price payload missing results list for {record.symbol}")
    points: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        timestamp = _finite_number(row.get("t"))
        close = _finite_number(row.get("c"))
        if timestamp is None or close is None or close <= 0:
            continue
        volume = _finite_number(row.get("v"))
        try:
            dt = datetime.fromtimestamp(timestamp / 1000.0, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            continue
        points.append({"date": dt.date().isoformat(), "close": close, "volume": volume})
    points.sort(key=lambda item: item["date"])
    deduped: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    for point in points:
        if point["date"] in seen_dates:
            continue
        seen_dates.add(point["date"])
        deduped.append(point)
    if len(deduped) < min_points_per_series:
        raise ThemeSourcePacketError(
            f"Massive price series for {record.symbol} has {len(deduped)} valid points, "
            f"need >= {min_points_per_series}"
        )
    return {
        "as_of": deduped[-1]["date"],
        "session": "RTH",
        "adjustment_mode": "split_div_adjusted",
        "points": deduped,
    }


def _payload_shape(record: sample_validation.FetchRecord) -> dict[str, Any]:
    payload = record.payload
    if isinstance(payload, dict):
        rows = payload.get("results")
        return {
            "kind": "object_results" if isinstance(rows, list) else "object",
            "row_count": len(rows) if isinstance(rows, list) else None,
        }
    if isinstance(payload, list):
        return {"kind": "list", "row_count": len(payload)}
    if payload is None:
        return {"kind": "null", "row_count": None}
    return {"kind": "scalar", "row_count": None}


def _summarize_endpoint(record: sample_validation.FetchRecord) -> dict[str, Any]:
    return {
        "provider_id": record.provider_id,
        "endpoint_family": record.endpoint_family,
        "symbol": record.symbol,
        "status": "success" if record.ok else "error",
        "http_status": record.http_status,
        "error_type": record.error_type,
        "raw_sample_ref": record.raw_sample_ref,
        "raw_sample_ref_gitignored": record.raw_sample_ref.startswith("provider_samples/"),
        "payload_shape": _payload_shape(record),
    }


def _build_packet(
    *,
    generated_at: str,
    observed_at: str,
    plan_context: dict[str, Any],
    candidate_context: dict[str, Any],
    profile_records: list[sample_validation.FetchRecord],
    price_records: list[sample_validation.FetchRecord],
) -> dict[str, Any]:
    min_points = plan_context["min_points_per_series"]
    profile_by_symbol = {_profile_row(record)["symbol"]: _profile_row(record) for record in profile_records}
    series_by_symbol = {
        record.symbol: _series_from_record(record, min_points_per_series=min_points)
        for record in price_records
        if record.symbol is not None
    }
    required_price_symbols = set(plan_context["industry_symbols"]) | set(BENCHMARK_SYMBOLS)
    missing_profiles = sorted(set(plan_context["industry_symbols"]) - set(profile_by_symbol))
    missing_prices = sorted(required_price_symbols - set(series_by_symbol))
    if missing_profiles or missing_prices:
        raise ThemeSourcePacketError(
            f"missing source rows before packet build (profiles={missing_profiles}, prices={missing_prices})"
        )
    bad_as_of = sorted(
        ticker for ticker in required_price_symbols if series_by_symbol[ticker]["as_of"] != candidate_context["source_as_of"]
    )
    if bad_as_of:
        raise ThemeSourcePacketError(f"price series as_of must match candidate price basis date: {bad_as_of}")

    industry_members = {
        ticker: {
            "sector": profile_by_symbol[ticker]["sector"],
            "series": series_by_symbol[ticker],
        }
        for ticker in plan_context["industry_symbols"]
    }
    provisional_themes = {
        theme_id: {"members": {ticker: series_by_symbol[ticker] for ticker in members}}
        for theme_id, members in plan_context["themes_by_id"].items()
    }
    theme_members_by_id = {
        theme_id: list(members)
        for theme_id, members in plan_context["themes_by_id"].items()
    }
    packet = {
        "schema_name": "us_short_batch5_theme_source_packet",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "packet_status": "theme_source_packet_ready_for_local_projection",
            "network_access_performed_by_packet_producer": True,
            "provider_calls_performed_by_packet_producer": True,
            "raw_payload_refs_gitignored": True,
            "full_gics_peer_pool": True,
            "provisional_theme_membership_source": "reviewed_local_source_packet",
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {
            "expected_decision_date": candidate_context["expected_decision_date"],
            "candidate_price_basis_date": candidate_context["candidate_price_basis_date"],
            "price_basis_date": candidate_context["price_basis_date"],
            "source_as_of": candidate_context["source_as_of"],
        },
        "source_contract": {
            "symbol_source": "caller_selected_from_validated_candidate_artifact",
            "selected_symbols": plan_context["selected_symbols"],
            "benchmark_symbols": list(BENCHMARK_SYMBOLS),
            "session": "RTH",
            "adjustment_mode": "split_div_adjusted",
            "min_points_per_series": min_points,
            "membership_pool_basis": "full_gics_peer_pool_and_provisional_theme_members",
            "full_gics_peer_pool": True,
            "full_market_sample": False,
            "provisional_theme_membership_frozen": True,
        },
        "industry_members_by_ticker": industry_members,
        "provisional_themes_by_id": provisional_themes,
        "theme_members_by_id": theme_members_by_id,
        "benchmark_series_by_ticker": {
            benchmark: series_by_symbol[benchmark]
            for benchmark in BENCHMARK_SYMBOLS
        },
        "preflight_gates": {
            "local_files_only": True,
            "candidate_artifact_must_match_price_basis": True,
            "selected_symbols_must_be_pass1_eligible": True,
            "benchmarks_required": True,
            "full_gics_peer_pool_required": True,
            "selected_symbol_only_membership_rejected": True,
            "output_must_be_gitignored": True,
            "no_provider_fetch_by_runner": True,
            "no_datahub_or_production": True,
        },
        "prohibited_claims": {
            "provider_selection_complete": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "live_normalized_evidence": False,
            "ship_gate_evidence": False,
            "production_ready": False,
            "datahub_consumed": False,
        },
    }
    _validate_schema(packet, PACKET_SCHEMA_PATH, label="theme source packet")
    return packet


def _consumer_context_from_packet(
    *,
    generated_at: str,
    packet: dict[str, Any],
    candidate_context: dict[str, Any],
    candidate_artifact_path: Path,
    source_packet_path: Path,
    output_projection_path: Path,
    consumer_summary_path: Path,
) -> dict[str, Any]:
    contract = packet["source_contract"]
    try:
        industry_members = theme_consumer._canonicalize_industry_members(
            packet["industry_members_by_ticker"],
            selected=contract["selected_symbols"],
            expected_as_of=packet["decision_clock"]["price_basis_date"],
            session=contract["session"],
            adjustment_mode=contract["adjustment_mode"],
            min_points=contract["min_points_per_series"],
        )
        themes_by_id, theme_members_by_id, theme_member_count = theme_consumer._canonicalize_themes(
            packet["provisional_themes_by_id"],
            packet["theme_members_by_id"],
            expected_as_of=packet["decision_clock"]["price_basis_date"],
            session=contract["session"],
            adjustment_mode=contract["adjustment_mode"],
            min_points=contract["min_points_per_series"],
        )
    except Exception as exc:
        raise ThemeSourcePacketError("theme source packet failed consumer canonicalization") from exc
    return {
        "generated_at": generated_at,
        "packet": packet,
        "selected_symbols": contract["selected_symbols"],
        "industry_members": industry_members,
        "themes_by_id": themes_by_id,
        "theme_members_by_id": theme_members_by_id,
        "theme_member_count": theme_member_count,
        "candidate_context": candidate_context,
        "candidate_artifact_path": candidate_artifact_path,
        "source_packet_path": source_packet_path,
        "output_projection_path": output_projection_path,
        "summary_path": consumer_summary_path,
    }


def _build_summary(
    *,
    generated_at: str,
    plan_context: dict[str, Any],
    candidate_context: dict[str, Any],
    records: list[sample_validation.FetchRecord],
    raw_root: Path,
    source_packet_path: Path,
    output_projection_path: Path,
    producer_summary_path: Path,
    consumer_summary_path: Path,
    fmp_env: sample_validation.EnvValue,
    massive_env: sample_validation.EnvValue,
    packet: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, Any]:
    endpoint_errors = sum(1 for record in records if not record.ok)
    actual_profile_calls = sum(1 for record in records if record.provider_id == "financial_modeling_prep")
    actual_price_calls = sum(1 for record in records if record.provider_id == "massive")
    theme_member_count = sum(len(members) for members in packet["theme_members_by_id"].values())
    return {
        "schema_name": "us_short_batch5_theme_source_packet_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_theme_source_packet_summary.schema.json",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "bounded_full_theme_source_packet_producer",
            "status": "theme_source_packet_written_and_projection_written",
            "network_access_performed": True,
            "provider_calls_performed": True,
            "raw_payload_storage_performed": True,
            "source_packet_written": True,
            "theme_projection_written": True,
            "consumer_summary_written": True,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "full_market_call_performed": False,
            "yfinance_consumption_performed": False,
            "broker_or_order_execution_performed": False,
            "ship_gate_or_live_normalized_evidence_claimed": False,
            "a_share_crossing_performed": False,
        },
        "decision_clock": {
            "expected_decision_date": candidate_context["expected_decision_date"],
            "candidate_price_basis_date": candidate_context["candidate_price_basis_date"],
            "price_basis_date": candidate_context["price_basis_date"],
            "source_as_of": candidate_context["source_as_of"],
        },
        "environment": {
            "fmp_api_key_present": True,
            "fmp_api_key_source": fmp_env.source,
            "massive_api_key_present": True,
            "massive_api_key_source": massive_env.source,
            "environment_values_logged": False,
            "secrets_logged": False,
        },
        "sample_universe": {
            "symbol_source": "reviewed_local_peer_theme_plan",
            "symbols": plan_context["selected_symbols"],
            "max_symbols": MAX_SELECTED_SYMBOLS,
            "benchmark_symbols": list(BENCHMARK_SYMBOLS),
            "full_market_sample": False,
            "industry_member_count": len(packet["industry_members_by_ticker"]),
            "theme_count": len(packet["provisional_themes_by_id"]),
            "candidate_artifact_row_count": candidate_context["row_count"],
            "candidate_artifact_eligible_count": candidate_context["eligible_count"],
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "actual_total_endpoint_calls": len(records),
            "actual_profile_endpoint_calls": actual_profile_calls,
            "actual_price_endpoint_calls": actual_price_calls,
            "endpoint_error_count": endpoint_errors,
            "within_budget": len(records) <= MAX_TOTAL_ENDPOINT_CALLS,
        },
        "endpoint_results": [_summarize_endpoint(record) for record in records],
        "storage": {
            "raw_payload_root": _repo_rel(raw_root),
            "raw_payload_root_gitignored": _git_ignored(raw_root),
            "source_packet_path": _repo_rel(source_packet_path),
            "source_packet_path_gitignored": _git_ignored(source_packet_path),
            "theme_projection_path": _repo_rel(output_projection_path),
            "theme_projection_path_gitignored": _git_ignored(output_projection_path),
            "consumer_summary_path": _repo_rel(consumer_summary_path),
            "producer_summary_path": _repo_rel(producer_summary_path),
            "producer_summary_contains_price_rows": False,
            "producer_summary_contains_raw_payload": False,
            "producer_summary_contains_request_urls": False,
            "producer_summary_contains_secrets": False,
            "producer_summary_contains_sector_or_industry_labels": False,
        },
        "theme_source_packet": {
            "schema_ref": "schemas/us_short_batch5_theme_source_packet.schema.json",
            "profile_provider_ids": ["financial_modeling_prep"],
            "price_provider_ids": ["massive"],
            "full_gics_peer_pool": True,
            "industry_member_count": len(packet["industry_members_by_ticker"]),
            "theme_count": len(packet["provisional_themes_by_id"]),
            "theme_member_count": theme_member_count,
            "benchmark_symbols": list(BENCHMARK_SYMBOLS),
            "session": "RTH",
            "adjustment_mode": "split_div_adjusted",
            "min_points_per_series": plan_context["min_points_per_series"],
            "lookback_calendar_days": plan_context["lookback_calendar_days"],
            "corporate_action_reconciliation_performed": False,
        },
        "consumer_projection": {
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
            "This producer executes only the reviewed local peer/theme plan, not a full-market download.",
            "Raw provider payloads stay under gitignored provider_samples; tracked summaries exclude URLs, raw rows, sector labels, industry labels, and secrets.",
            "The output is a source packet and local projection for Batch5 source wiring; it is not provider selection, DataHub, production, or ship-gate evidence.",
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
        "\"results\"",
    )
    for fragment in forbidden:
        if fragment in lower:
            raise ThemeSourcePacketError(f"producer summary contains forbidden fragment: {fragment}")
    for value in sensitive_values:
        if value and value in text:
            raise ThemeSourcePacketError("producer summary contains a sensitive environment value")


def _write_summary_validated(summary: dict[str, Any], summary_path: Path, sensitive_values: list[str]) -> None:
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="theme source packet producer summary")
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text, sensitive_values)
    _write_json_atomic(summary, summary_path, field="producer_summary_path")


def run_theme_source_packet(
    *,
    plan_path: Path = DEFAULT_PLAN_PATH,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    output_source_packet_path: Path = DEFAULT_OUTPUT_SOURCE_PACKET_PATH,
    output_projection_path: Path = DEFAULT_OUTPUT_PROJECTION_PATH,
    producer_summary_path: Path = SUMMARY_PATH,
    consumer_summary_path: Path = DEFAULT_CONSUMER_SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
    client: sample_validation.JsonHttpClient | None = None,
    confirm_user_authorization: bool = False,
    generated_at: str | None = None,
    observed_at: str | None = None,
    massive_sleep_seconds: float = MASSIVE_SLEEP_SECONDS,
) -> dict[str, Any]:
    if confirm_user_authorization is not True:
        raise ThemeSourcePacketError("confirm_user_authorization is required before provider fetch")
    generated_at = generated_at or iso_now()
    observed_at = observed_at or generated_at
    if not _valid_observed_at(generated_at):
        raise ThemeSourcePacketError("generated_at must be a timezone-aware RFC3339 instant")
    if not _valid_observed_at(observed_at):
        raise ThemeSourcePacketError("observed_at must be a timezone-aware RFC3339 instant")
    if massive_sleep_seconds < 0:
        raise ThemeSourcePacketError("massive_sleep_seconds must be non-negative")

    plan_resolved = _existing_file(plan_path, field="plan_path")
    candidate_path = _existing_file(candidate_artifact_path, field="candidate_artifact_path")
    source_packet_path = _validate_state_json_path(
        output_source_packet_path,
        field="output_source_packet_path",
        must_exist=False,
    )
    projection_path = _validate_state_json_path(
        output_projection_path,
        field="output_projection_path",
        must_exist=False,
    )
    producer_summary_resolved = _validate_producer_summary_path(producer_summary_path)
    try:
        consumer_summary_resolved = theme_consumer._validate_summary_path(consumer_summary_path)
    except Exception as exc:
        raise ThemeSourcePacketError("consumer_summary_path is outside the theme consumer boundary") from exc
    raw_resolved = _validate_raw_root(raw_root)
    if source_packet_path in {candidate_path, projection_path}:
        raise ThemeSourcePacketError("output_source_packet_path must not overwrite an input or projection file")
    if projection_path == candidate_path:
        raise ThemeSourcePacketError("output_projection_path must not overwrite candidate_artifact_path")
    if producer_summary_resolved in {candidate_path, source_packet_path, projection_path}:
        raise ThemeSourcePacketError("producer_summary_path must not overwrite input/output state files")

    plan_context = _load_plan(plan_resolved)
    candidate_ctx = _candidate_context(
        candidate_artifact_path=candidate_path,
        expected_decision_date=plan_context["expected_decision_date"],
        selected_symbols=plan_context["selected_symbols"],
    )
    fmp_env = sample_validation.read_required_env("FMP_API_KEY")
    massive_env = sample_validation.read_required_env("MASSIVE_API_KEY")

    client = client or sample_validation.JsonHttpClient()
    profile_records = _fetch_profile_records(
        industry_symbols=plan_context["industry_symbols"],
        raw_root=raw_resolved,
        client=client,
        fmp_env=fmp_env,
        max_total_endpoint_calls=plan_context["max_total_endpoint_calls"],
        existing_records=[],
    )
    price_records = _fetch_price_records(
        required_symbols=plan_context["industry_symbols"] + list(BENCHMARK_SYMBOLS),
        source_as_of=candidate_ctx["source_as_of"],
        raw_root=raw_resolved,
        client=client,
        massive_env=massive_env,
        lookback_calendar_days=plan_context["lookback_calendar_days"],
        massive_sleep_seconds=massive_sleep_seconds,
        max_total_endpoint_calls=plan_context["max_total_endpoint_calls"],
        existing_records=profile_records,
    )
    records = profile_records + price_records
    packet = _build_packet(
        generated_at=generated_at,
        observed_at=observed_at,
        plan_context=plan_context,
        candidate_context=candidate_ctx,
        profile_records=profile_records,
        price_records=price_records,
    )
    consumer_context = _consumer_context_from_packet(
        generated_at=generated_at,
        packet=packet,
        candidate_context=candidate_ctx,
        candidate_artifact_path=candidate_path,
        source_packet_path=source_packet_path,
        output_projection_path=projection_path,
        consumer_summary_path=consumer_summary_resolved,
    )
    try:
        projection, _, _ = theme_consumer._build_projection(consumer_context)
    except Exception as exc:
        raise ThemeSourcePacketError("theme consumer projection rejected the built source packet") from exc
    summary = _build_summary(
        generated_at=generated_at,
        plan_context=plan_context,
        candidate_context=candidate_ctx,
        records=records,
        raw_root=raw_resolved,
        source_packet_path=source_packet_path,
        output_projection_path=projection_path,
        producer_summary_path=producer_summary_resolved,
        consumer_summary_path=consumer_summary_resolved,
        fmp_env=fmp_env,
        massive_env=massive_env,
        packet=packet,
        projection=projection,
    )
    sensitive_values = [fmp_env.value, massive_env.value]
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="theme source packet producer summary")
    _assert_text_safe(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", sensitive_values)

    _prepare_json_target(source_packet_path, field="output_source_packet_path")
    _prepare_json_target(projection_path, field="output_projection_path")
    _prepare_json_target(consumer_summary_resolved, field="consumer_summary_path")
    _prepare_json_target(producer_summary_resolved, field="producer_summary_path")
    _write_json_atomic(packet, source_packet_path, field="output_source_packet_path")
    theme_consumer.run_packet(
        candidate_artifact_path=candidate_path,
        source_packet_path=source_packet_path,
        output_projection_path=projection_path,
        summary_path=consumer_summary_resolved,
        generated_at=generated_at,
    )
    _write_summary_validated(summary, producer_summary_resolved, sensitive_values)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the authorized bounded US-short Batch5 full theme/GICS source packet from a reviewed local "
            "peer/theme plan, FMP stable profile rows, and Massive adjusted daily aggregates. This producer writes "
            "raw payloads only under provider_samples and never uses DataHub, production storage, yfinance, "
            "broker/order automation, or A-share paths."
        )
    )
    parser.add_argument("--plan-path", type=Path, default=DEFAULT_PLAN_PATH)
    parser.add_argument("--candidate-artifact-path", type=Path, default=DEFAULT_CANDIDATE_ARTIFACT_PATH)
    parser.add_argument("--output-source-packet-path", type=Path, default=DEFAULT_OUTPUT_SOURCE_PACKET_PATH)
    parser.add_argument("--output-projection-path", type=Path, default=DEFAULT_OUTPUT_PROJECTION_PATH)
    parser.add_argument("--producer-summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--consumer-summary-path", type=Path, default=DEFAULT_CONSUMER_SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_SAMPLE_ROOT)
    parser.add_argument("--generated-at")
    parser.add_argument("--observed-at")
    parser.add_argument("--massive-sleep-seconds", type=float, default=MASSIVE_SLEEP_SECONDS)
    parser.add_argument("--confirm-user-authorization", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_theme_source_packet(
        plan_path=args.plan_path,
        candidate_artifact_path=args.candidate_artifact_path,
        output_source_packet_path=args.output_source_packet_path,
        output_projection_path=args.output_projection_path,
        producer_summary_path=args.producer_summary_path,
        consumer_summary_path=args.consumer_summary_path,
        raw_root=args.raw_root,
        confirm_user_authorization=args.confirm_user_authorization,
        generated_at=args.generated_at,
        observed_at=args.observed_at,
        massive_sleep_seconds=args.massive_sleep_seconds,
    )
    print(
        json.dumps(
            {
                "status": summary["scope"]["status"],
                "symbols": summary["sample_universe"]["symbols"],
                "industry_member_count": summary["theme_source_packet"]["industry_member_count"],
                "theme_scored_count": summary["consumer_projection"]["theme_scored_count"],
                "producer_summary_path": summary["storage"]["producer_summary_path"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
