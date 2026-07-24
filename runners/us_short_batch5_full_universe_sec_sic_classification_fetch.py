# -*- coding: utf-8 -*-
"""US-short full-universe SEC SIC sector-classification GATED fetch (theme piece C step 2, SR-PROVIDER-001).

Design authority: docs/system_risk_register.md::R-USSHORT-BATCH5-FULL-UNIVERSE-THEME-PRODUCTION-MISSING.
The user chose the free SEC SIC classification source (a bounded 3-ticker shape probe confirmed SEC submissions
carry `sic` + `sicDescription`). This runner keeps immutable CIK-keyed local snapshots and refreshes only candidates
whose latest snapshot is missing, more than 90 calendar days old, or too new for the decision clock. It writes the
`{ticker: sector}` classification packet that the offline full-universe theme producer (piece B,
runners/us_short_batch5_full_universe_theme_producer.py) consumes.

COARSENING: `sic` is fine-grained (~400 4-digit industries — AAPL 3571 vs MSFT 7372), so at MIN_SECTOR_MEMBERS=3
over ~2404 tickers the raw industry would leave many groups insufficient. This runner coarsens to the SIC 2-DIGIT
MAJOR GROUP (`sic[:2]`, ~80 groups ≈ GICS-industry granularity) so peer pools are usable. classification_source is
honestly `sec_sic_major_group` (NOT GICS, NOT licensed data).

WHY SAFE / GATED: SR-PROVIDER-001 gated (a real SEC fetch is a user-authorized per-execution action). Fail-closed:
no `confirm_user_authorization` -> refuse; no `SEC_USER_AGENT` -> refuse; packet/snapshot paths not gitignored -> refuse;
zero tickers classified -> refuse (SEC unavailable, do not write an all-missing packet). A snapshot is usable only when
its observation is strictly before the target decision open and no more than 90 days old; a later snapshot is never
used for an earlier decision. The SEC endpoint is keyless
(User-Agent identified — no apiKey in the URL); the SEC User-Agent (an email) is NEVER printed/logged/written —
the tracked summary is counts-only and secret-scanned before write. The ~2404 raw submissions payloads are NOT
persisted (only the bounded `{ticker: sector}` packet), mirroring the momentum fetch's raw-window policy. A ticker
whose SEC submissions fail / lack a SIC is simply absent from the packet -> the theme producer dispositions it
neutral_missing (graceful).

Offline-testable: the ticker→CIK and per-ticker SIC lookups are injectable seams; tests pass fakes + zero pacing so no
network / SEC UA is touched. Snapshot files are local/private records, never raw SEC submissions. No DataHub/
production/ship-gate/broker; no A-share.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, time as datetime_time, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_eligibility_gate import canonical_us_ticker, load_eligibility_governance  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402


PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_sector_classification_packet.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_sec_sic_classification_fetch_summary.schema.json"
SNAPSHOT_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_sec_sic_classification_snapshot.schema.json"
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260706.json"
SUMMARY_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_full_universe_sec_sic_classification_fetch")
_CANONICAL_SUMMARY_RE = re.compile(r"^us_short_batch5_full_universe_sec_sic_classification_fetch_summary_[0-9]{8}\.json$")

CLASSIFICATION_SOURCE = "sec_sic_major_group"
SNAPSHOT_SCHEMA_NAME = "us_short_batch5_sec_sic_classification_snapshot"
SNAPSHOT_SCHEMA_VERSION = "1.0.0"
SNAPSHOT_REL_DIR = Path("state/us_short/sec_sic_classification_snapshots")
SNAPSHOT_FILE_PREFIX = "sec_sic_snapshot_"
CACHE_FRESHNESS_DAYS = 90
PARSER_VERSION = "1.0.0"
NEW_YORK = ZoneInfo("America/New_York")
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_FAIR_ACCESS_SLEEP = universe_fetch.SEC_FAIR_ACCESS_SLEEP


class FullUniverseSecSicClassificationFetchError(RuntimeError):
    """The gated full-universe SEC SIC classification fetch cannot proceed / complete safely (fail-closed)."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _resolve_repo_path(path: Path | str, *, field: str) -> Path:
    raw = Path(path)
    resolved = raw.resolve() if raw.is_absolute() else (ROOT / raw).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise FullUniverseSecSicClassificationFetchError(f"{field} must stay under the repository root") from exc
    return resolved


def _validate_packet_path(path: Path | str) -> Path:
    resolved = _resolve_repo_path(path, field="classification_packet_path")
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise FullUniverseSecSicClassificationFetchError("classification_packet_path must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise FullUniverseSecSicClassificationFetchError("classification_packet_path must be a .json path")
    if not universe_fetch._git_check_ignored(resolved):
        raise FullUniverseSecSicClassificationFetchError("classification_packet_path must be gitignored (real data stays private)")
    return resolved


def _validate_snapshot_root(path: Path | str) -> Path:
    resolved = _resolve_repo_path(path, field="snapshot_root")
    try:
        resolved.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise FullUniverseSecSicClassificationFetchError("snapshot_root must stay under state/us_short/") from exc
    if not universe_fetch._git_check_ignored(resolved / ".snapshot-ignore-probe.json"):
        raise FullUniverseSecSicClassificationFetchError("snapshot_root must be gitignored (classification snapshots stay private)")
    return resolved


def _validate_summary_path(path: Path | str) -> Path:
    resolved = _resolve_repo_path(path, field="summary_path")
    if resolved.suffix != ".json":
        raise FullUniverseSecSicClassificationFetchError("summary_path must be a .json path")
    if resolved.parent == (ROOT / "docs").resolve() and _CANONICAL_SUMMARY_RE.match(resolved.name):
        return resolved
    try:
        resolved.relative_to((ROOT / SUMMARY_SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise FullUniverseSecSicClassificationFetchError(
            "summary_path must be the canonical docs summary or under provider_samples/us_short_batch5_full_universe_sec_sic_classification_fetch/"
        ) from exc
    if not universe_fetch._git_check_ignored(resolved):
        raise FullUniverseSecSicClassificationFetchError("non-canonical summary_path must be gitignored")
    return resolved


def _compact_to_ymd(value: Any, *, field: str) -> str:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise FullUniverseSecSicClassificationFetchError(f"{field} must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise FullUniverseSecSicClassificationFetchError(f"{field} must be a real calendar date") from exc


def _validate_schema(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise FullUniverseSecSicClassificationFetchError("jsonschema is required for the SEC SIC classification fetch") from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise FullUniverseSecSicClassificationFetchError(f"{label} schema rejected {len(errors)} field(s): {joined}") from errors[0]


def _load_candidate(*, candidate_artifact_path: Path) -> dict[str, Any]:
    artifact = _read_json(candidate_artifact_path)
    governance = load_eligibility_governance(ELIGIBILITY_GOVERNANCE_PATH)
    try:
        validated = universe_fetch.validate_candidate_artifact(
            artifact, expected_decision_date=artifact.get("decision_date"), governance=governance,
        )
    except Exception as exc:
        raise FullUniverseSecSicClassificationFetchError(f"candidate artifact failed validation: {exc}") from exc
    return validated


def _real_cik_source(sec_ua: str, *, stats_out: dict[str, int] | None = None) -> Callable[[list[str]], dict[str, int]]:
    if not sec_ua:
        raise FullUniverseSecSicClassificationFetchError("SEC_USER_AGENT not set (a live SEC fetch requires it)")

    def source(eligible: list[str]) -> dict[str, int]:
        ticker_cik = universe_fetch.fetch_sec_tickers(sec_ua)  # {canonical_ticker: {cik, exchange}} (1 call)
        out: dict[str, int] = {}
        for ticker in eligible:
            rec = ticker_cik.get(ticker)
            cik = rec.get("cik") if isinstance(rec, dict) else None
            if type(cik) is int and not isinstance(cik, bool) and cik > 0:
                out[ticker] = cik
        if stats_out is not None:
            stats_out["ticker_reference_calls"] = 1
        return out

    return source


def _real_sic_source(
    sec_ua: str, cik_by_ticker: dict[str, int], *, interval_seconds: float,
    stats_out: dict[str, int] | None = None,
) -> Callable[[list[str]], dict[str, str]]:
    if not sec_ua:
        raise FullUniverseSecSicClassificationFetchError("SEC_USER_AGENT not set (a live SEC fetch requires it)")

    def source(eligible: list[str]) -> dict[str, str]:
        submissions_calls = 0
        out: dict[str, str] = {}
        fetched_ciks: dict[int, str | None] = {}
        first = True
        for ticker in eligible:
            cik = cik_by_ticker.get(ticker)
            if type(cik) is not int or isinstance(cik, bool) or cik <= 0:
                continue
            if cik in fetched_ciks:
                sic = fetched_ciks[cik]
                if sic is not None:
                    out[ticker] = sic
                continue
            if not first and interval_seconds > 0:
                time.sleep(interval_seconds)
            first = False
            submissions_calls += 1  # attempted call, including provider errors
            try:
                payload = universe_fetch._sec_get(SEC_SUBMISSIONS_URL.format(cik=cik), sec_ua)
            except Exception:
                fetched_ciks[cik] = None
                continue  # a failed / missing issuer is simply absent -> theme dispositions it neutral_missing
            sic = payload.get("sic") if isinstance(payload, dict) else None
            if isinstance(sic, str) and sic:
                fetched_ciks[cik] = sic
                out[ticker] = sic
            else:
                fetched_ciks[cik] = None
        if stats_out is not None:
            stats_out["submissions_calls"] = submissions_calls
        return out

    return source


def _sector_major_group(sic: Any) -> str | None:
    """Coarsen a raw SIC code string to its 2-digit MAJOR GROUP (the usable peer-pool granularity). Fail-closed
    on a non-str / too-short / non-numeric-prefix value (a malformed SIC is not a sector)."""
    if not (isinstance(sic, str) and len(sic) >= 2 and sic[:2].isascii() and sic[:2].isdigit()):
        return None
    return sic[:2]


def _validated_observation_date(generated_at: str, decision_date: str) -> str:
    try:
        observed = datetime.fromisoformat(generated_at[:-1] + "+00:00" if generated_at.endswith("Z") else generated_at)
    except (AttributeError, TypeError, ValueError) as exc:
        raise FullUniverseSecSicClassificationFetchError(
            "generated_at must be a timezone-aware RFC3339 instant"
        ) from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise FullUniverseSecSicClassificationFetchError("generated_at must be a timezone-aware RFC3339 instant")
    observed_et = observed.astimezone(NEW_YORK)
    try:
        decision_et_date = datetime.strptime(decision_date, "%Y%m%d").date()
    except (TypeError, ValueError) as exc:
        raise FullUniverseSecSicClassificationFetchError("candidate decision_date must be YYYYMMDD") from exc
    # §2.1 half-open window: the observation must be STRICTLY before the decision session's 09:30 ET open. A
    # weekend / pre-open run is VALID (canonical anchor already floors observed at the settled price basis) — this
    # is NOT a same-calendar-day requirement (that wrongly rejects the design's normal weekend prep run).
    if observed_et >= datetime.combine(decision_et_date, datetime_time(9, 30), NEW_YORK):
        raise FullUniverseSecSicClassificationFetchError(
            "current SEC SIC snapshot must be observed strictly before the decision date's 09:30 America/New_York open"
        )
    return observed_et.date().isoformat()


def _parse_observed_at(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise FullUniverseSecSicClassificationFetchError(f"{field} must be a timezone-aware RFC3339 instant")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise FullUniverseSecSicClassificationFetchError(f"{field} must be a timezone-aware RFC3339 instant") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FullUniverseSecSicClassificationFetchError(f"{field} must be a timezone-aware RFC3339 instant")
    return parsed


def _decision_open(decision_date: str) -> datetime:
    return datetime.combine(datetime.strptime(decision_date, "%Y%m%d").date(), datetime_time(9, 30), NEW_YORK)


def _snapshot_is_usable(snapshot: dict[str, Any], *, decision_date: str) -> bool:
    observed = _parse_observed_at(snapshot.get("observed_at"), field="snapshot.observed_at")
    observed_et = observed.astimezone(NEW_YORK)
    if observed_et >= _decision_open(decision_date):
        return False
    age_days = (datetime.strptime(decision_date, "%Y%m%d").date() - observed_et.date()).days
    return 0 <= age_days <= CACHE_FRESHNESS_DAYS


def _snapshot_identity(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_name": snapshot["schema_name"],
        "schema_version": snapshot["schema_version"],
        "classification_source": snapshot["classification_source"],
        "parser_version": snapshot["parser_version"],
        "observed_at": snapshot["observed_at"],
        "source_as_of": snapshot["source_as_of"],
        "entries": snapshot["entries"],
    }


def _snapshot_digest(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(_snapshot_identity(snapshot), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_cached_by_cik(snapshot_root: Path, *, decision_date: str) -> tuple[dict[int, dict[str, Any]], dict[str, int]]:
    chosen: dict[int, dict[str, Any]] = {}
    ticker_cik: dict[str, int] = {}
    for path in sorted(snapshot_root.glob(f"{SNAPSHOT_FILE_PREFIX}*.json")):
        payload = _read_json(path)
        _validate_schema(payload, SNAPSHOT_SCHEMA_PATH, label="SEC SIC classification snapshot")
        if not _snapshot_is_usable(payload, decision_date=decision_date):
            continue
        if payload["snapshot_id"] != _snapshot_digest(payload):
            raise FullUniverseSecSicClassificationFetchError("immutable SEC SIC snapshot digest mismatch")
        observed = _parse_observed_at(payload["observed_at"], field="snapshot.observed_at")
        for raw_cik, entry in payload["entries"].items():
            if not raw_cik.isdecimal() or str(int(raw_cik)) != raw_cik:
                raise FullUniverseSecSicClassificationFetchError("SEC SIC snapshot entry key must be a canonical CIK")
            cik = int(raw_cik)
            if entry["cik"] != cik:
                raise FullUniverseSecSicClassificationFetchError("SEC SIC snapshot entry CIK does not match its map key")
            canonical_tickers = [canonical_us_ticker(ticker) for ticker in entry["tickers"]]
            if any(ticker is None for ticker in canonical_tickers) or canonical_tickers != entry["tickers"]:
                raise FullUniverseSecSicClassificationFetchError("SEC SIC snapshot entry contains a non-canonical ticker")
            for ticker in canonical_tickers:
                prior_cik = ticker_cik.get(ticker)
                if prior_cik is not None and prior_cik != cik:
                    raise FullUniverseSecSicClassificationFetchError("conflicting immutable SEC SIC snapshots map one ticker to different CIKs")
                ticker_cik[ticker] = cik
            record = {**entry, "snapshot_id": payload["snapshot_id"], "source_as_of": payload["source_as_of"],
                      "observed_at": payload["observed_at"]}
            prior = chosen.get(cik)
            if prior is None or _parse_observed_at(prior["observed_at"], field="cached.observed_at") < observed:
                chosen[cik] = record
            elif _parse_observed_at(prior["observed_at"], field="cached.observed_at") == observed \
                    and (prior["sector"] != record["sector"] or prior["snapshot_id"] != record["snapshot_id"]):
                raise FullUniverseSecSicClassificationFetchError("conflicting immutable SEC SIC snapshots share an observation time")
    return chosen, ticker_cik


def _snapshot_payload(*, generated_at: str, source_as_of: str, entries: dict[int, dict[str, str]]) -> dict[str, Any]:
    canonical_entries = {str(cik): entries[cik] for cik in sorted(entries)}
    identity = {
        "schema_name": SNAPSHOT_SCHEMA_NAME,
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "classification_source": CLASSIFICATION_SOURCE,
        "parser_version": PARSER_VERSION,
        "observed_at": generated_at,
        "source_as_of": source_as_of,
        "entries": canonical_entries,
    }
    snapshot_id = _snapshot_digest(identity)
    return {**identity, "snapshot_id": snapshot_id}


def _write_snapshot(snapshot_root: Path, payload: dict[str, Any]) -> Path:
    _validate_schema(payload, SNAPSHOT_SCHEMA_PATH, label="SEC SIC classification snapshot")
    stamp = _parse_observed_at(payload["observed_at"], field="snapshot.observed_at").astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = snapshot_root / f"{SNAPSHOT_FILE_PREFIX}{stamp}_{payload['snapshot_id'][:16]}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    snapshot_root.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise FullUniverseSecSicClassificationFetchError("immutable SEC SIC snapshot path collision")
        return path
    universe_fetch._write_json_atomic(payload, path)
    return path


def _build_packet(*, generated_at: str, artifact: dict[str, Any], price_basis_ymd: str,
                  classification_source_as_of: str,
                  sector_by_ticker: dict[str, str], provenance_by_ticker: dict[str, dict[str, Any]],
                  provider_calls_performed: bool) -> dict[str, Any]:
    return {
        "schema_name": "us_short_batch5_full_universe_sector_classification_packet",
        "schema_version": "1.1.0",
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "packet_status": "full_universe_sector_classification_ready_for_local_theme_projection",
            "network_access_performed_by_packet_producer": provider_calls_performed,
            "provider_calls_performed_by_packet_producer": provider_calls_performed,
            "raw_payload_refs_gitignored": True,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {
            "expected_decision_date": artifact["decision_date"],
            "candidate_price_basis_date": artifact["price_basis_date"],
            "price_basis_date": price_basis_ymd,
            "source_as_of": classification_source_as_of,
        },
        "classification_contract": {
            "classification_source": CLASSIFICATION_SOURCE,
            "as_of": classification_source_as_of,
            "cache_identity": "immutable_cik_snapshot",
            "cache_freshness_days": CACHE_FRESHNESS_DAYS,
        },
        "provenance": {
            "provider_id": "sec_edgar",
            "endpoint_or_family": "submissions_sic",
            "source_as_of": classification_source_as_of,
            "observed_at": generated_at,
            "coverage_status": "full" if len(sector_by_ticker) == len(artifact["eligible_tickers"]) else "partial",
            "parser_status": "ok",
        },
        "sector_by_ticker": sector_by_ticker,
        "provenance_by_ticker": provenance_by_ticker,
    }


def _build_summary(*, generated_at: str, artifact: dict[str, Any], price_basis_ymd: str,
                   classification_source_as_of: str, eligible_count: int,
                   sic_resolved_count: int, sector_by_ticker: dict[str, str], candidate_path: Path,
                   packet_path: Path, summary_path: Path, provider_call_evidence: dict[str, Any],
                   cache_reused_count: int, cache_refreshed_count: int, cache_snapshot_count: int,
                   provider_calls_performed: bool) -> dict[str, Any]:
    return {
        "schema_name": "us_short_batch5_full_universe_sec_sic_classification_fetch_summary",
        "schema_version": "1.1.0",
        "schema_ref": "schemas/us_short_batch5_full_universe_sec_sic_classification_fetch_summary.schema.json",
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "full_universe_sec_sic_sector_classification_fetch",
            "status": "classification_packet_written",
            "network_access_performed": provider_calls_performed,
            "provider_calls_performed": provider_calls_performed,
            "raw_submissions_persisted": False,
            "gics_classification_claimed": False,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "yfinance_consumption_performed": False,
            "paid_access_performed": False,
            "broker_or_order_execution_performed": False,
            "ship_gate_or_live_normalized_evidence_claimed": False,
            "a_share_crossing_performed": False,
        },
        "decision_clock": {
            "expected_decision_date": artifact["decision_date"],
            "candidate_price_basis_date": artifact["price_basis_date"],
            "price_basis_date": price_basis_ymd,
            "source_as_of": classification_source_as_of,
        },
        "classification": {
            "classification_source": CLASSIFICATION_SOURCE,
            "coarsening": "sic_2digit_major_group",
            "provider_ids": ["sec_edgar"],
            "eligible_count": eligible_count,
            "sic_resolved_count": sic_resolved_count,
            "sic_missing_count": eligible_count - sic_resolved_count,
            "sector_group_count": len(set(sector_by_ticker.values())),
            "cache_identity": "immutable_cik_snapshot",
            "cache_freshness_days": CACHE_FRESHNESS_DAYS,
            "cache_reused_count": cache_reused_count,
            "cache_refreshed_count": cache_refreshed_count,
            "cache_snapshot_count": cache_snapshot_count,
        },
        "provider_call_evidence": provider_call_evidence,
        "paths": {
            "candidate_artifact_path": _repo_rel(candidate_path),
            "classification_packet_path": _repo_rel(packet_path),
            "summary_path": _repo_rel(summary_path),
        },
        "storage": {
            "classification_packet_path_gitignored": universe_fetch._git_check_ignored(packet_path),
            "raw_submissions_persisted": False,
            "summary_contains_ticker_lists": False,
            "summary_contains_sector_labels": False,
            "summary_contains_sec_user_agent": False,
            "summary_contains_request_urls": False,
            "summary_contains_secrets": False,
        },
        "prohibited_claims": {
            "provider_selected": False,
            "gics_classification_claimed": False,
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
            "Classification is SEC SIC coarsened to the 2-digit major group (sec_sic_major_group); it is NOT licensed GICS and does not assert GICS.",
            "Immutable CIK-keyed snapshots are reusable only when observed before the target decision open and no more than 90 days old; later snapshots are never backfilled into an earlier decision.",
            "Only local {ticker: sector} packets and CIK-keyed snapshot metadata are persisted; the raw SEC submissions payloads are not.",
            "The tracked summary is counts-only: no ticker lists, sector labels, SEC User-Agent, request URLs, or secrets.",
            "A ticker whose SEC submissions failed or lacked a SIC is absent from the packet and is dispositioned neutral by the theme producer.",
        ],
    }


def run_fetch(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    classification_packet_path: Path | None = None,
    summary_path: Path | None = None,
    snapshot_root: Path | None = None,
    generated_at: str | None = None,
    confirm_user_authorization: bool = False,
    sic_source: Callable[[list[str]], dict[str, str]] | None = None,
    cik_source: Callable[[list[str]], dict[str, int]] | None = None,
    interval_seconds: float = SEC_FAIR_ACCESS_SLEEP,
) -> dict[str, Any]:
    if not universe_fetch._check_gitignore():
        raise FullUniverseSecSicClassificationFetchError("provider_samples/ not confirmed in .gitignore")

    generated_at = generated_at or iso_now()
    candidate_path = _resolve_repo_path(candidate_artifact_path, field="candidate_artifact_path")
    if not candidate_path.exists() or not candidate_path.is_file():
        raise FullUniverseSecSicClassificationFetchError(f"candidate_artifact_path must be an existing file: {_repo_rel(candidate_path)}")
    artifact = _load_candidate(candidate_artifact_path=candidate_path)
    price_basis_compact = artifact["price_basis_date"]
    price_basis_ymd = artifact["used_date"]
    classification_source_as_of = _validated_observation_date(generated_at, artifact["decision_date"])

    packet_path = _validate_packet_path(
        classification_packet_path if classification_packet_path is not None
        else STATE_US_SHORT_DIR / f"us_short_batch5_full_universe_sector_classification_{price_basis_compact}_packet.json"
    )
    summary_resolved = _validate_summary_path(
        summary_path if summary_path is not None
        else ROOT / "docs" / f"us_short_batch5_full_universe_sec_sic_classification_fetch_summary_{price_basis_compact}.json"
    )
    if packet_path == candidate_path:
        raise FullUniverseSecSicClassificationFetchError("classification_packet_path must not overwrite the candidate artifact")
    snapshots = _validate_snapshot_root(snapshot_root if snapshot_root is not None else ROOT / SNAPSHOT_REL_DIR)

    eligible = [t for t in (canonical_us_ticker(raw) for raw in artifact["eligible_tickers"]) if t is not None]

    # Read/verify cache before any authorization or provider precondition. A fully covered, fresh,
    # integrity-bound cache is a local operation and must not need SEC credentials or make a probe call.
    cached_by_cik, cached_ticker_cik = _load_cached_by_cik(snapshots, decision_date=artifact["decision_date"])
    ticker_cik = {ticker: cached_ticker_cik[ticker] for ticker in eligible if ticker in cached_ticker_cik}
    cached_records_by_ticker = {ticker: cached_by_cik[cik] for ticker, cik in ticker_cik.items() if cik in cached_by_cik}
    missing_tickers = [ticker for ticker in eligible if ticker not in cached_records_by_ticker]

    sec_ua = os.environ.get("SEC_USER_AGENT", "")
    provider_call_stats: dict[str, int] = {}
    raw_sic_by_ticker: dict[str, str] = {}
    if missing_tickers:
        if not confirm_user_authorization:
            raise FullUniverseSecSicClassificationFetchError(
                "live SEC SIC classification fetch requires explicit user authorization (confirm_user_authorization=True)"
            )
        if sic_source is not None and cik_source is None:
            raise FullUniverseSecSicClassificationFetchError("injected sic_source requires injected cik_source for CIK-keyed snapshot safety")
        cik_lookup = cik_source if cik_source is not None else _real_cik_source(sec_ua, stats_out=provider_call_stats)
        ticker_cik_raw = cik_lookup(missing_tickers)
        fetched_ticker_cik = {
            ticker: cik for ticker, cik in ticker_cik_raw.items()
            if ticker in set(missing_tickers) and type(cik) is int and not isinstance(cik, bool) and cik > 0
        }
        ticker_cik.update(fetched_ticker_cik)
        for ticker, cik in fetched_ticker_cik.items():
            if cik in cached_by_cik:
                cached_records_by_ticker[ticker] = cached_by_cik[cik]
        unresolved_tickers = [ticker for ticker in missing_tickers if ticker not in cached_records_by_ticker]
        source = sic_source if sic_source is not None else _real_sic_source(
            sec_ua, ticker_cik, interval_seconds=interval_seconds, stats_out=provider_call_stats,
        )
        raw_sic_by_ticker = source(unresolved_tickers)
    eligible_set = set(eligible)
    sector_by_ticker: dict[str, str] = {}
    provenance_by_ticker: dict[str, dict[str, Any]] = {}
    fresh_entries: dict[int, dict[str, Any]] = {}
    for ticker, record in cached_records_by_ticker.items():
        sector_by_ticker[ticker] = record["sector"]
        provenance_by_ticker[ticker] = {
            "cik": ticker_cik[ticker], "snapshot_id": record["snapshot_id"], "source_as_of": record["source_as_of"],
            "observed_at": record["observed_at"], "cache_reused": True,
        }
    for ticker, sic in raw_sic_by_ticker.items():
        ct = canonical_us_ticker(ticker)
        cik = ticker_cik.get(ct) if ct is not None else None
        if ct is None or ct not in eligible_set or ct in sector_by_ticker or cik is None:
            continue  # ignore a stray / non-eligible / duplicate ticker from the source
        group = _sector_major_group(sic)
        if group is not None:
            sector_by_ticker[ct] = group
            existing = fresh_entries.get(cik)
            if existing is not None and existing["sector"] != group:
                raise FullUniverseSecSicClassificationFetchError("SEC SIC source returned conflicting sectors for one CIK")
            if existing is None:
                fresh_entries[cik] = {"cik": cik, "tickers": [ct], "sector": group}
            elif ct not in existing["tickers"]:
                existing["tickers"].append(ct)

    fresh_snapshot = None
    if fresh_entries:
        fresh_snapshot = _snapshot_payload(
            generated_at=generated_at, source_as_of=classification_source_as_of, entries=fresh_entries,
        )
        _write_snapshot(snapshots, fresh_snapshot)
        for ticker, cik in ticker_cik.items():
            if cik in fresh_entries:
                provenance_by_ticker[ticker] = {
                    "cik": cik, "snapshot_id": fresh_snapshot["snapshot_id"], "source_as_of": classification_source_as_of,
                    "observed_at": generated_at, "cache_reused": False,
                }

    if not sector_by_ticker:
        raise FullUniverseSecSicClassificationFetchError(
            "zero tickers classified (SEC unavailable / no SIC resolved); fail-closed rather than write an empty packet"
        )

    source_as_of = max(record["source_as_of"] for record in provenance_by_ticker.values())
    packet = _build_packet(
        generated_at=generated_at, artifact=artifact, price_basis_ymd=price_basis_ymd,
        classification_source_as_of=source_as_of,
        sector_by_ticker=sector_by_ticker, provenance_by_ticker=provenance_by_ticker,
        provider_calls_performed=bool(provider_call_stats),
    )
    _validate_schema(packet, PACKET_SCHEMA_PATH, label="full-universe sector classification packet")

    summary = _build_summary(
        generated_at=generated_at, artifact=artifact, price_basis_ymd=price_basis_ymd,
        classification_source_as_of=source_as_of,
        eligible_count=len(eligible), sic_resolved_count=len(sector_by_ticker),
        sector_by_ticker=sector_by_ticker, candidate_path=candidate_path, packet_path=packet_path,
        summary_path=summary_resolved,
        provider_call_evidence={
            "network_access_performed": bool(provider_call_stats),
            "provider_calls_performed": bool(provider_call_stats),
            "ticker_reference_calls": provider_call_stats.get("ticker_reference_calls", 0),
            "submissions_calls": provider_call_stats.get("submissions_calls", 0),
            "actual_total_calls": provider_call_stats.get("ticker_reference_calls", 0) + provider_call_stats.get("submissions_calls", 0),
        },
        cache_reused_count=sum(1 for record in provenance_by_ticker.values() if record["cache_reused"]),
        cache_refreshed_count=len(fresh_entries),
        cache_snapshot_count=len(list(snapshots.glob(f"{SNAPSHOT_FILE_PREFIX}*.json"))),
        provider_calls_performed=bool(provider_call_stats),
    )
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="full-universe SEC SIC classification fetch summary")
    # Secret-scan the tracked summary (SEC User-Agent + provider domains) BEFORE writing either artifact.
    universe_fetch._assert_text_safe(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", [sec_ua])

    universe_fetch._write_json_atomic(packet, packet_path)
    try:
        universe_fetch._write_summary_safe(summary, summary_resolved, [sec_ua])
    except BaseException:
        packet_path.unlink(missing_ok=True)  # all-or-nothing: no orphan packet if the summary write fails
        raise
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "GATED (SR-PROVIDER-001) full-universe SEC SIC sector-classification fetch: fetch SEC submissions SIC "
            "for all Pass1-eligible, coarsen to the 2-digit major group, and write the {ticker: sector} classification "
            "packet (gitignored) + a counts-only secret-scanned tracked summary. Requires user authorization + "
            "SEC_USER_AGENT; never prints/stores the SEC User-Agent, URLs, or raw submissions. Not GICS."
        )
    )
    parser.add_argument("--candidate-artifact-path", type=Path, default=DEFAULT_CANDIDATE_ARTIFACT_PATH)
    parser.add_argument("--classification-packet-path", type=Path, default=None)
    parser.add_argument("--summary-path", type=Path, default=None)
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--confirm-user-authorization", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_fetch(
        candidate_artifact_path=args.candidate_artifact_path,
        classification_packet_path=args.classification_packet_path,
        summary_path=args.summary_path,
        generated_at=args.generated_at,
        confirm_user_authorization=args.confirm_user_authorization,
    )
    print(json.dumps(
        {
            "status": summary["scope"]["status"],
            "eligible_count": summary["classification"]["eligible_count"],
            "sic_resolved_count": summary["classification"]["sic_resolved_count"],
            "sector_group_count": summary["classification"]["sector_group_count"],
            "summary_path": summary["paths"]["summary_path"],
        },
        ensure_ascii=False, indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
