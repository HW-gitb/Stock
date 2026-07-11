# -*- coding: utf-8 -*-
"""US-short full-universe THEME producer (offline half — §4.3 35% theme block, industry-heat base).

Design authority: docs/system_risk_register.md::R-USSHORT-BATCH5-FULL-UNIVERSE-THEME-PRODUCTION-MISSING
(+ docs/us_short_system_design.md §4.2/§4.3). This is the THEME analog of
runners/us_short_batch5_full_universe_momentum_producer.py: it scores the §4.3 industry/theme heat block for ALL
Pass1-eligible candidates, unlike the deliberately curated <=3-symbol theme producers (runners/us_short_batch5_
theme_source*.py, all MAX_SYMBOLS=3), which cannot compute honest industry heat (a sector needs its FULL peer pool,
not a 3-name subset — the §4.3 self-certification contract).

WHAT THIS IS: consume (1) the SAME full-universe per-ticker price-series packet the momentum producer consumes
(engine/us_short_industry_heat.py needs only per-ticker CLOSE series + SPY/QQQ — the price data is already fetched)
and (2) a per-ticker sector CLASSIFICATION packet (the ONLY new data; written by the gated classification fetch,
SR-PROVIDER-001), reuse the PROVEN engines VERBATIM — industry_heat_block (full peer pool → per-sector heat → each
member inherits its sector's cross-sector percentile) -> project_theme_block (35% block assembly) — over ALL
eligible, and emit the same funnel-consumable theme projection shape
(theme_block_by_ticker / neutral_fill_tickers / coverage / target_count / scored_count) + a counts-only no-secret
summary. The projection feeds runners/us_short_batch5_full_candidate_projection_inputs.py (its theme leg).

v1 SCOPE = INDUSTRY BASE ONLY. §4.3's 35% block has two overlapping sources — GICS industry heat + cross-sector
provisional theme heat. This v1 computes the INDUSTRY half (the §13.1 #38 fail-safe base) and feeds an EMPTY
provisional-theme result, so assemble_theme_block ranks every scored row by its industry base (a valid block —
the provisional cross-sector theme is a later additive residual, not a prerequisite). The summary records
`provisional_cross_sector_theme_consumed=false` so this is never overstated.

GRACEFUL DISPOSITION (like the momentum producer): a ticker whose sector is below MIN_SECTOR_MEMBERS, or that has
no sector / no series / too-short history, is NEVER a hard raise — the engine dispositions it and
project_theme_block projects it to `neutral_missing_theme_and_industry_base`. The run always completes with an
honest per-ticker disposition. Envelope corruption (clock mismatch, missing benchmark, non-uniform series clock)
fails closed with no partial write.

WHAT THIS IS NOT: not a fetch (the classification fetch is SR-PROVIDER-001 gated, separate), not the provisional
cross-sector theme discovery, not momentum/catalyst, not Pass2/selection/top-K. The `classification_source` is
whatever the packet declares (GICS or a labelled free proxy such as SEC SIC) — this producer does NOT assert GICS.
Pure/offline; no provider/live/network/DataHub/production/ship-gate/broker path; no A-share crossing.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, time as datetime_time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_eligibility_gate import canonical_us_ticker, load_eligibility_governance  # noqa: E402
from engine.us_short_projection_binding import build_projection_binding  # noqa: E402
from engine.us_short_industry_heat import IndustryHeatError, industry_heat_block  # noqa: E402
from engine.us_short_seam_theme import (  # noqa: E402
    COVERAGE_DISPOSITIONS,
    DISPOSITION_NEUTRAL_INSUFFICIENT_THEME_NO_INDUSTRY,
    DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE,
    DISPOSITION_SCORED_INDUSTRY_BASE,
    DISPOSITION_SCORED_THEME_BASE,
    project_theme_block,
)
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402


SERIES_PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_momentum_series_packet.schema.json"
CLASSIFICATION_PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_sector_classification_packet.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_theme_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_full_universe_theme_summary_20260707.json"
SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_full_universe_theme_20260707")
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260702.json"
DEFAULT_SERIES_PACKET_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_full_universe_momentum_series_20260702_packet.json"
)
DEFAULT_CLASSIFICATION_PACKET_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_full_universe_sector_classification_20260702_packet.json"
)
DEFAULT_OUTPUT_PROJECTION_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_full_universe_theme_20260702_theme.json"
)
BENCHMARK_SYMBOLS = ("SPY", "QQQ")
SAFE_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# v1 industry-base only: a well-formed EMPTY provisional-theme result (§4.3 provisional cross-sector theme is a
# separate later producer). project_theme_block validates this shape and adds no theme base.
_EMPTY_PROVISIONAL_THEME_RESULT = {
    "theme_heat": {},
    "confirm_flags": {},
    "theme_metrics": {},
    "insufficient_themes": [],
    "min_theme_members": 3,
}


class FullUniverseThemeProducerError(ValueError):
    """A full-universe theme series/classification packet cannot be consumed into a projection safely."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _prepare_json_target(path: Path, *, field: str) -> None:
    if path.parent.exists() and not path.parent.is_dir():
        raise FullUniverseThemeProducerError(f"{field} parent must be a directory: {_display_path(path.parent)}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FullUniverseThemeProducerError(f"{field} parent could not be created: {_display_path(path.parent)}") from exc
    if path.exists() and path.is_dir():
        raise FullUniverseThemeProducerError(f"{field} must be a file path, not a directory: {_display_path(path)}")


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
        raise FullUniverseThemeProducerError(f"{field} could not be written atomically: {_display_path(path)}") from exc


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
        raise FullUniverseThemeProducerError(f"{field} must stay under the repository root") from exc
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


def _validate_state_json_file(path: Path | str, *, field: str, must_exist: bool) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise FullUniverseThemeProducerError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise FullUniverseThemeProducerError(f"{field} must be a .json path")
    if must_exist and (not resolved.exists() or not resolved.is_file()):
        raise FullUniverseThemeProducerError(f"{field} must be an existing file: {_display_path(resolved)}")
    if not _git_ignored(resolved):
        raise FullUniverseThemeProducerError(f"{field} must be gitignored")
    return resolved


def _validate_summary_path(path: Path | str) -> Path:
    resolved = _resolve_repo_path(path, field="summary_path")
    if resolved.suffix != ".json":
        raise FullUniverseThemeProducerError("summary_path must be a .json path")
    if resolved == SUMMARY_PATH.resolve():
        return resolved
    try:
        resolved.relative_to((ROOT / SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise FullUniverseThemeProducerError(
            "summary_path must be the canonical tracked summary or under this runner's provider_samples folder"
        ) from exc
    if not _git_ignored(resolved):
        raise FullUniverseThemeProducerError("non-canonical summary_path must be gitignored")
    return resolved


def _valid_observed_at(value: str) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _validate_classification_observation(
    *, observed_at: str, source_as_of: str, expected_decision_date: str
) -> None:
    try:
        observed_et = datetime.fromisoformat(
            observed_at[:-1] + "+00:00" if observed_at.endswith("Z") else observed_at
        ).astimezone(ZoneInfo("America/New_York"))
        decision_et_date = datetime.strptime(expected_decision_date, "%Y%m%d").date()
    except (TypeError, ValueError) as exc:
        raise FullUniverseThemeProducerError("classification observation clock is invalid") from exc
    if observed_et.date() != decision_et_date or observed_et.time() >= datetime_time(9, 30):
        raise FullUniverseThemeProducerError(
            "current classification snapshot must be observed on the decision date before the 09:30 ET open"
        )
    if source_as_of != observed_et.date().isoformat():
        raise FullUniverseThemeProducerError("classification source_as_of must equal the ET observation date")


def _compact_to_ymd(value: Any, *, field: str) -> str:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise FullUniverseThemeProducerError(f"{field} must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise FullUniverseThemeProducerError(f"{field} must be a real calendar date") from exc


def _safe_provider_id(value: Any, *, field: str) -> str:
    if type(value) is not str or SAFE_PROVIDER_ID_RE.fullmatch(value) is None:
        raise FullUniverseThemeProducerError(f"{field} must be a lowercase provider slug")
    return value


def _canonical_ticker(raw: Any, *, field: str) -> str:
    if type(raw) is not str:
        raise FullUniverseThemeProducerError(f"{field} must be an exact ticker string")
    ticker = canonical_us_ticker(raw)
    if ticker is None:
        raise FullUniverseThemeProducerError(f"{field} must be a canonicalizable US ticker")
    return ticker


def _validate_schema(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise FullUniverseThemeProducerError("jsonschema is required for full-universe theme validation") from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise FullUniverseThemeProducerError(f"{label} schema rejected {len(errors)} field(s): {joined}") from errors[0]


def _load_candidate_artifact(*, candidate_artifact_path: Path, expected_decision_date: str) -> dict[str, Any]:
    artifact = _read_json(candidate_artifact_path)
    governance = load_eligibility_governance(ELIGIBILITY_GOVERNANCE_PATH)
    try:
        validated = universe_fetch.validate_candidate_artifact(
            artifact,
            expected_decision_date=expected_decision_date,
            governance=governance,
        )
    except Exception as exc:
        raise FullUniverseThemeProducerError(f"candidate artifact failed validation: {exc}") from exc
    return validated


def _canonical_series_by_ticker(
    *,
    series_by_ticker: dict[str, Any],
    allowed: set[str],
    price_basis_date: str,
    session: str,
    adjustment_mode: str,
) -> dict[str, dict[str, Any]]:
    """Canonicalize the series packet keys and enforce ENVELOPE coherence (fail-closed corrupt-packet signals,
    mirroring the momentum producer): a non-canonical / duplicate / stray (not eligible-or-benchmark) ticker, or a
    per-ticker look-ahead / mismatched clock (as_of != price_basis_date, or session / adjustment_mode != the
    series_contract), is a corrupt/forged packet and raises. Per-ticker DATA quality is judged downstream by the
    engine (graceful)."""
    canonical: dict[str, dict[str, Any]] = {}
    for raw_key, series in series_by_ticker.items():
        ticker = _canonical_ticker(raw_key, field="series_by_ticker key")
        if ticker in canonical:
            raise FullUniverseThemeProducerError(f"series_by_ticker contains duplicate canonical ticker: {ticker}")
        if ticker not in allowed:
            raise FullUniverseThemeProducerError(
                f"series_by_ticker contains a ticker outside the eligible+benchmark set: {ticker}"
            )
        if series["as_of"] != price_basis_date:
            raise FullUniverseThemeProducerError(f"{ticker} series.as_of must equal the price_basis_date")
        if series["session"] != session:
            raise FullUniverseThemeProducerError(f"{ticker} series.session must match the series_contract")
        if series["adjustment_mode"] != adjustment_mode:
            raise FullUniverseThemeProducerError(f"{ticker} series.adjustment_mode must match the series_contract")
        canonical[ticker] = series
    return canonical


def _canonical_sector_by_ticker(*, sector_by_ticker: dict[str, Any], allowed: set[str]) -> dict[str, str]:
    """Canonicalize the classification keys; reject a non-canonical / duplicate / stray (not-eligible) ticker
    (a stray classification is a corrupt/forged packet)."""
    canonical: dict[str, str] = {}
    for raw_key, sector in sector_by_ticker.items():
        ticker = _canonical_ticker(raw_key, field="sector_by_ticker key")
        if ticker in canonical:
            raise FullUniverseThemeProducerError(f"sector_by_ticker contains duplicate canonical ticker: {ticker}")
        if ticker not in allowed:
            raise FullUniverseThemeProducerError(
                f"sector_by_ticker contains a ticker outside the eligible set: {ticker}"
            )
        canonical[ticker] = sector
    return canonical


def _load_context(
    *,
    candidate_artifact_path: Path,
    series_packet_path: Path,
    classification_packet_path: Path,
    output_projection_path: Path,
    summary_path: Path,
    generated_at: str | None,
) -> dict[str, Any]:
    generated_at = generated_at or iso_now()
    if not _valid_observed_at(generated_at):
        raise FullUniverseThemeProducerError("generated_at must be a timezone-aware RFC3339 instant")

    series_packet = _read_json(series_packet_path)
    _validate_schema(series_packet, SERIES_PACKET_SCHEMA_PATH, label="full-universe momentum series packet")
    classification = _read_json(classification_packet_path)
    _validate_schema(classification, CLASSIFICATION_PACKET_SCHEMA_PATH, label="full-universe sector classification packet")

    series_clock = series_packet["decision_clock"]
    class_clock = classification["decision_clock"]
    price_basis_date = series_clock["price_basis_date"]
    if class_clock["price_basis_date"] != price_basis_date:
        raise FullUniverseThemeProducerError("series and classification packets must share one price_basis_date")
    if series_packet["series_contract"]["as_of"] != price_basis_date:
        raise FullUniverseThemeProducerError("series_contract.as_of must equal the price_basis_date")
    class_source_as_of = class_clock["source_as_of"]
    if classification["classification_contract"]["as_of"] != class_source_as_of:
        raise FullUniverseThemeProducerError("classification_contract.as_of must equal decision_clock.source_as_of")
    if classification["provenance"]["source_as_of"] != class_source_as_of:
        raise FullUniverseThemeProducerError("classification provenance.source_as_of must equal decision_clock.source_as_of")
    series_provider_id = _safe_provider_id(series_packet["provenance"]["provider_id"], field="series provenance.provider_id")
    class_provider_id = _safe_provider_id(classification["provenance"]["provider_id"], field="classification provenance.provider_id")
    classification_source = classification["classification_contract"]["classification_source"]

    artifact = _load_candidate_artifact(
        candidate_artifact_path=candidate_artifact_path,
        expected_decision_date=series_clock["expected_decision_date"],
    )
    if series_clock["candidate_price_basis_date"] != artifact["price_basis_date"]:
        raise FullUniverseThemeProducerError("series candidate_price_basis_date must match the candidate artifact")
    if class_clock["candidate_price_basis_date"] != artifact["price_basis_date"]:
        raise FullUniverseThemeProducerError("classification candidate_price_basis_date must match the candidate artifact")
    if artifact["used_date"] != price_basis_date:
        raise FullUniverseThemeProducerError("candidate used_date must match the packet price_basis_date")
    if class_clock["expected_decision_date"] != series_clock["expected_decision_date"]:
        raise FullUniverseThemeProducerError("series and classification packets must share one expected_decision_date")
    _validate_classification_observation(
        observed_at=classification["provenance"]["observed_at"],
        source_as_of=class_source_as_of,
        expected_decision_date=series_clock["expected_decision_date"],
    )
    eligible = [_canonical_ticker(t, field="candidate.eligible_tickers") for t in artifact["eligible_tickers"]]
    benchmarks = tuple(_canonical_ticker(sym, field="benchmark") for sym in BENCHMARK_SYMBOLS)

    canonical_series = _canonical_series_by_ticker(
        series_by_ticker=series_packet["series_by_ticker"],
        allowed=set(eligible) | set(benchmarks),
        price_basis_date=price_basis_date,
        session=series_packet["series_contract"]["session"],
        adjustment_mode=series_packet["series_contract"]["adjustment_mode"],
    )
    canonical_sector = _canonical_sector_by_ticker(
        sector_by_ticker=classification["sector_by_ticker"],
        allowed=set(eligible),
    )
    for bench in benchmarks:
        if bench not in canonical_series:
            raise FullUniverseThemeProducerError(f"required benchmark series missing from series packet: {bench}")

    if output_projection_path in {candidate_artifact_path, series_packet_path, classification_packet_path}:
        raise FullUniverseThemeProducerError("output_projection_path must not overwrite input files")

    return {
        "generated_at": generated_at,
        "series_packet": series_packet,
        "classification": classification,
        "series_provider_id": series_provider_id,
        "class_provider_id": class_provider_id,
        "classification_source": classification_source,
        "price_basis_date": price_basis_date,
        "artifact": artifact,
        "eligible": eligible,
        "benchmarks": benchmarks,
        "canonical_series": canonical_series,
        "canonical_sector": canonical_sector,
        "candidate_artifact_path": candidate_artifact_path,
        "series_packet_path": series_packet_path,
        "classification_packet_path": classification_packet_path,
        "output_projection_path": output_projection_path,
        "summary_path": summary_path,
    }


def _disposition_counts(coverage: dict[str, str]) -> dict[str, int]:
    counts = Counter(coverage.values())
    return {
        "scored_theme_base": counts.get(DISPOSITION_SCORED_THEME_BASE, 0),
        "scored_industry_base": counts.get(DISPOSITION_SCORED_INDUSTRY_BASE, 0),
        "neutral_insufficient_theme_no_industry": counts.get(DISPOSITION_NEUTRAL_INSUFFICIENT_THEME_NO_INDUSTRY, 0),
        "neutral_missing_theme_and_industry_base": counts.get(DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE, 0),
    }


def _build_projection(context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    canonical_series = context["canonical_series"]
    canonical_sector = context["canonical_sector"]
    eligible = context["eligible"]
    spy_ticker, qqq_ticker = context["benchmarks"]

    # BASE peer pool = every eligible ticker that has BOTH a sector label AND a price series (the §4.3
    # self-certification contract wants the FULL peer pool, which the full eligible set is). A ticker missing
    # either is excluded here and project_theme_block dispositions it to neutral_missing.
    members_by_ticker: dict[str, dict[str, Any]] = {}
    for ticker in eligible:
        series = canonical_series.get(ticker)
        sector = canonical_sector.get(ticker)
        if series is None or sector is None:
            continue
        members_by_ticker[ticker] = {"sector": sector, "series": series}

    try:
        industry_result = industry_heat_block(
            members_by_ticker,
            spy_series=canonical_series[spy_ticker],
            qqq_series=canonical_series[qqq_ticker],
        )
    except IndustryHeatError:
        # A non-uniform decision clock across the injected series = a corrupt packet -> fail closed. Do NOT chain
        # the cause (its message echoes packet clock tuples; keep the typed error clean).
        raise FullUniverseThemeProducerError(
            "industry heat rejected a non-uniform decision clock across the series packet (fail-closed)"
        ) from None

    projection = project_theme_block(
        industry_result=industry_result,
        provisional_theme_result=_EMPTY_PROVISIONAL_THEME_RESULT,
        theme_members_by_id={},
        target_tickers=eligible,
    )
    projection["source_binding"] = build_projection_binding(
        component="theme",
        generated_at=context["generated_at"],
        expected_decision_date=context["series_packet"]["decision_clock"]["expected_decision_date"],
        candidate_price_basis_date=context["artifact"]["price_basis_date"],
        source_as_of=context["artifact"]["used_date"],
        target_tickers=eligible,
        source_artifact_paths={
            "candidate_artifact": context["candidate_artifact_path"],
            "momentum_series_packet": context["series_packet_path"],
            "sector_classification_packet": context["classification_packet_path"],
        },
    )
    details = {
        "members_with_sector_and_series_count": len(members_by_ticker),
        "sector_count": len({rec["sector"] for rec in members_by_ticker.values()}),
        "scored_sector_count": len(industry_result["sector_heat"]),
        "insufficient_sector_count": len(industry_result["insufficient_sectors"]),
        "min_sector_members": industry_result["min_sector_members"],
        "disposition_counts": _disposition_counts(projection["coverage"]),
    }
    return projection, details


def _build_summary(*, context: dict[str, Any], projection: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    series_packet = context["series_packet"]
    classification = context["classification"]
    artifact = context["artifact"]
    eligible = context["eligible"]
    return {
        "schema_name": "us_short_batch5_full_universe_theme_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_full_universe_theme_summary.schema.json",
        "generated_at": context["generated_at"],
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "full_universe_sector_classification_plus_series_to_theme_projection",
            "status": "full_universe_theme_projection_written",
            "network_access_performed_by_runner": False,
            "provider_calls_performed_by_runner": False,
            "raw_payload_storage_performed_by_runner": False,
            "series_packet_consumed": True,
            "classification_packet_consumed": True,
            "theme_projection_written": True,
            "provisional_cross_sector_theme_consumed": False,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "full_market_call_performed": False,
            "yfinance_consumption_performed": False,
            "broker_or_order_execution_performed": False,
            "ship_gate_or_live_normalized_evidence_claimed": False,
            "a_share_crossing_performed": False,
        },
        "decision_clock": dict(series_packet["decision_clock"]),
        "candidate_universe": {
            "row_count": len(artifact["rows"]),
            "eligible_count": len(eligible),
            "symbol_scope": "full_pass1_eligible_candidate_set",
            "full_market_sample": False,
        },
        "theme_source": {
            "classification_source": context["classification_source"],
            "classification_provider_ids": [context["class_provider_id"]],
            "series_provider_ids": [context["series_provider_id"]],
            "members_with_sector_and_series_count": details["members_with_sector_and_series_count"],
            "sector_count": details["sector_count"],
            "scored_sector_count": details["scored_sector_count"],
            "insufficient_sector_count": details["insufficient_sector_count"],
            "min_sector_members": details["min_sector_members"],
        },
        "projection_contract": {
            "target_count": projection["target_count"],
            "theme_scored_count": projection["scored_count"],
            "neutral_fill_count": len(projection["neutral_fill_tickers"]),
            "disposition_counts": details["disposition_counts"],
            "coverage_exactly_matches_full_candidate_set": True,
            "real_industry_heat_source_consumed": projection["scored_count"] > 0,
            "provisional_cross_sector_theme_consumed": False,
        },
        "paths": {
            "candidate_artifact_path": _repo_rel(context["candidate_artifact_path"]),
            "series_packet_path": _repo_rel(context["series_packet_path"]),
            "classification_packet_path": _repo_rel(context["classification_packet_path"]),
            "output_projection_path": _repo_rel(context["output_projection_path"]),
            "summary_path": _repo_rel(context["summary_path"]),
        },
        "storage": {
            "series_packet_path_gitignored": _git_ignored(context["series_packet_path"]),
            "classification_packet_path_gitignored": _git_ignored(context["classification_packet_path"]),
            "output_projection_path_gitignored": _git_ignored(context["output_projection_path"]),
            "summary_path_gitignored": _git_ignored(context["summary_path"]),
            "summary_contains_ticker_lists": False,
            "summary_contains_sector_labels": False,
            "summary_contains_raw_payload": False,
            "summary_contains_request_urls": False,
            "summary_contains_secrets": False,
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
            "gics_classification_claimed_when_proxy": False,
            "broker_or_order_execution_performed": False,
            "a_share_crossing_performed": False,
        },
        "limitations": [
            "v1 = INDUSTRY base only: the §4.3 provisional cross-sector theme heat is not consumed (a later additive residual); the summary records provisional_cross_sector_theme_consumed=false.",
            "The classification_source is whatever the packet declares (GICS or a labelled free proxy such as SEC SIC); this producer does not assert GICS.",
            "This runner consumes already-built local packets; it performs no provider fetch. The tracked summary is counts-only (no ticker lists, sector labels, raw payloads, request URLs, or secrets).",
            "The gated classification fetch that builds the classification packet, DataHub, production storage, broker/order, live-normalized and ship-gate evidence remain out of scope (SR-PROVIDER-001).",
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
        "\"results\"",
        "\"sector_by_ticker\"",
    )
    for fragment in forbidden:
        if fragment in lower:
            raise FullUniverseThemeProducerError(f"summary contains forbidden fragment: {fragment}")


def _write_summary_validated(summary: dict[str, Any], summary_path: Path) -> None:
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="full-universe theme summary")
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text)
    _write_json_atomic(summary, summary_path, field="summary_path")


def _resolve_paths(
    *,
    candidate_artifact_path: Path,
    series_packet_path: Path,
    classification_packet_path: Path,
    output_projection_path: Path,
    summary_path: Path,
) -> dict[str, Path]:
    candidate_path = _validate_state_json_file(candidate_artifact_path, field="candidate_artifact_path", must_exist=True)
    series_path = _validate_state_json_file(series_packet_path, field="series_packet_path", must_exist=True)
    class_path = _validate_state_json_file(classification_packet_path, field="classification_packet_path", must_exist=True)
    output_path = _validate_state_json_file(output_projection_path, field="output_projection_path", must_exist=False)
    summary_resolved = _validate_summary_path(summary_path)
    if len({candidate_path, series_path, class_path, output_path}) != 4:
        raise FullUniverseThemeProducerError("candidate / series / classification / output paths must be distinct")
    return {
        "candidate": candidate_path,
        "series": series_path,
        "classification": class_path,
        "output": output_path,
        "summary": summary_resolved,
    }


def run_preflight(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    series_packet_path: Path = DEFAULT_SERIES_PACKET_PATH,
    classification_packet_path: Path = DEFAULT_CLASSIFICATION_PACKET_PATH,
    output_projection_path: Path = DEFAULT_OUTPUT_PROJECTION_PATH,
    summary_path: Path = SUMMARY_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    paths = _resolve_paths(
        candidate_artifact_path=candidate_artifact_path,
        series_packet_path=series_packet_path,
        classification_packet_path=classification_packet_path,
        output_projection_path=output_projection_path,
        summary_path=summary_path,
    )
    context = _load_context(
        candidate_artifact_path=paths["candidate"],
        series_packet_path=paths["series"],
        classification_packet_path=paths["classification"],
        output_projection_path=paths["output"],
        summary_path=paths["summary"],
        generated_at=generated_at,
    )
    projection, details = _build_projection(context)
    return {
        "schema_name": "us_short_batch5_full_universe_theme_preflight_result",
        "schema_version": "1.0.0",
        "generated_at": context["generated_at"],
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "preflight_status": "offline_preflight_passed",
            "network_access_required": False,
            "projection_file_written": False,
            "summary_file_written": False,
        },
        "projection_preview": {
            "target_count": projection["target_count"],
            "theme_scored_count": projection["scored_count"],
            "classification_source": context["classification_source"],
            "scored_sector_count": details["scored_sector_count"],
            "disposition_counts": details["disposition_counts"],
        },
        "paths": {
            "candidate_artifact_path": _repo_rel(paths["candidate"]),
            "series_packet_path": _repo_rel(paths["series"]),
            "classification_packet_path": _repo_rel(paths["classification"]),
            "output_projection_path": _repo_rel(paths["output"]),
            "summary_path": _repo_rel(paths["summary"]),
        },
    }


def run_packet(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    series_packet_path: Path = DEFAULT_SERIES_PACKET_PATH,
    classification_packet_path: Path = DEFAULT_CLASSIFICATION_PACKET_PATH,
    output_projection_path: Path = DEFAULT_OUTPUT_PROJECTION_PATH,
    summary_path: Path = SUMMARY_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    paths = _resolve_paths(
        candidate_artifact_path=candidate_artifact_path,
        series_packet_path=series_packet_path,
        classification_packet_path=classification_packet_path,
        output_projection_path=output_projection_path,
        summary_path=summary_path,
    )
    context = _load_context(
        candidate_artifact_path=paths["candidate"],
        series_packet_path=paths["series"],
        classification_packet_path=paths["classification"],
        output_projection_path=paths["output"],
        summary_path=paths["summary"],
        generated_at=generated_at,
    )
    projection, details = _build_projection(context)
    summary = _build_summary(context=context, projection=projection, details=details)
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="full-universe theme summary")
    _assert_text_safe(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    _prepare_json_target(paths["output"], field="output_projection_path")
    _prepare_json_target(paths["summary"], field="summary_path")
    _write_json_atomic(projection, paths["output"], field="output_projection_path")
    try:
        _write_summary_validated(summary, paths["summary"])
    except BaseException:
        paths["output"].unlink(missing_ok=True)  # all-or-nothing: no orphan projection if the summary write fails
        raise
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Score the §4.3 theme block (industry-heat base) for ALL Pass1-eligible candidates from an already-built "
            "local full-universe series packet + a sector classification packet, emitting the funnel-consumable theme "
            "projection with honest per-ticker dispositions. Never fetches providers, stores raw payloads, uses "
            "DataHub, or claims GICS / production / ship-gate evidence."
        )
    )
    parser.add_argument("--candidate-artifact-path", type=Path, default=DEFAULT_CANDIDATE_ARTIFACT_PATH)
    parser.add_argument("--series-packet-path", type=Path, default=DEFAULT_SERIES_PACKET_PATH)
    parser.add_argument("--classification-packet-path", type=Path, default=DEFAULT_CLASSIFICATION_PACKET_PATH)
    parser.add_argument("--output-projection-path", type=Path, default=DEFAULT_OUTPUT_PROJECTION_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--generated-at")
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    kwargs = {
        "candidate_artifact_path": args.candidate_artifact_path,
        "series_packet_path": args.series_packet_path,
        "classification_packet_path": args.classification_packet_path,
        "output_projection_path": args.output_projection_path,
        "summary_path": args.summary_path,
        "generated_at": args.generated_at,
    }
    result = run_preflight(**kwargs) if args.preflight_only else run_packet(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
