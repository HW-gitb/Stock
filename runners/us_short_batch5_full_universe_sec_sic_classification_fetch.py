# -*- coding: utf-8 -*-
"""US-short full-universe SEC SIC sector-classification GATED fetch (theme piece C step 2, SR-PROVIDER-001).

Design authority: docs/system_risk_register.md::R-USSHORT-BATCH5-FULL-UNIVERSE-THEME-PRODUCTION-MISSING.
The user chose the free SEC SIC classification source (a bounded 3-ticker shape probe confirmed SEC submissions
carry `sic` + `sicDescription`). This runner fetches the SIC classification for ALL Pass1-eligible candidates and
writes the `{ticker: sector}` classification packet that the offline full-universe theme producer (piece B,
runners/us_short_batch5_full_universe_theme_producer.py) consumes.

COARSENING: `sic` is fine-grained (~400 4-digit industries — AAPL 3571 vs MSFT 7372), so at MIN_SECTOR_MEMBERS=3
over ~2404 tickers the raw industry would leave many groups insufficient. This runner coarsens to the SIC 2-DIGIT
MAJOR GROUP (`sic[:2]`, ~80 groups ≈ GICS-industry granularity) so peer pools are usable. classification_source is
honestly `sec_sic_major_group` (NOT GICS, NOT licensed data).

WHY SAFE / GATED: SR-PROVIDER-001 gated (a real SEC fetch is a user-authorized per-execution action). Fail-closed:
no `confirm_user_authorization` -> refuse; no `SEC_USER_AGENT` -> refuse; packet path not gitignored -> refuse; zero
tickers classified -> refuse (SEC unavailable, do not write an all-missing packet). The SEC endpoint is keyless
(User-Agent identified — no apiKey in the URL); the SEC User-Agent (an email) is NEVER printed/logged/written —
the tracked summary is counts-only and secret-scanned before write. The ~2404 raw submissions payloads are NOT
persisted (only the bounded `{ticker: sector}` packet), mirroring the momentum fetch's raw-window policy. A ticker
whose SEC submissions fail / lack a SIC is simply absent from the packet -> the theme producer dispositions it
neutral_missing (graceful).

Offline-testable: the per-ticker SIC lookup is an injectable `sic_source(eligible)->{ticker: sic}` seam (default
binds to the real SEC fetch: fetch_sec_tickers for CIKs + paced submissions calls); tests pass a fake seam + zero
pacing so no network / SEC UA is touched. Pure otherwise. No DataHub/production/ship-gate/broker; no A-share.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


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
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260706.json"
SUMMARY_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_full_universe_sec_sic_classification_fetch")
_CANONICAL_SUMMARY_RE = re.compile(r"^us_short_batch5_full_universe_sec_sic_classification_fetch_summary_[0-9]{8}\.json$")

CLASSIFICATION_SOURCE = "sec_sic_major_group"
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


def _real_sic_source(sec_ua: str, *, interval_seconds: float) -> Callable[[list[str]], dict[str, str]]:
    if not sec_ua:
        raise FullUniverseSecSicClassificationFetchError("SEC_USER_AGENT not set (a live SEC fetch requires it)")

    def source(eligible: list[str]) -> dict[str, str]:
        ticker_cik = universe_fetch.fetch_sec_tickers(sec_ua)  # {canonical_ticker: {cik, exchange}} (1 call)
        out: dict[str, str] = {}
        first = True
        for ticker in eligible:
            rec = ticker_cik.get(ticker)
            if not isinstance(rec, dict) or "cik" not in rec:
                continue
            if not first and interval_seconds > 0:
                time.sleep(interval_seconds)
            first = False
            try:
                payload = universe_fetch._sec_get(SEC_SUBMISSIONS_URL.format(cik=int(rec["cik"])), sec_ua)
            except Exception:
                continue  # a failed / missing issuer is simply absent -> theme dispositions it neutral_missing
            sic = payload.get("sic") if isinstance(payload, dict) else None
            if isinstance(sic, str) and sic:
                out[ticker] = sic
        return out

    return source


def _sector_major_group(sic: Any) -> str | None:
    """Coarsen a raw SIC code string to its 2-digit MAJOR GROUP (the usable peer-pool granularity). Fail-closed
    on a non-str / too-short / non-numeric-prefix value (a malformed SIC is not a sector)."""
    if not (isinstance(sic, str) and len(sic) >= 2 and sic[:2].isascii() and sic[:2].isdigit()):
        return None
    return sic[:2]


def _build_packet(*, generated_at: str, artifact: dict[str, Any], price_basis_ymd: str,
                  sector_by_ticker: dict[str, str]) -> dict[str, Any]:
    return {
        "schema_name": "us_short_batch5_full_universe_sector_classification_packet",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "packet_status": "full_universe_sector_classification_ready_for_local_theme_projection",
            "network_access_performed_by_packet_producer": True,
            "provider_calls_performed_by_packet_producer": True,
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
            "source_as_of": price_basis_ymd,
        },
        "classification_contract": {"classification_source": CLASSIFICATION_SOURCE, "as_of": price_basis_ymd},
        "provenance": {
            "provider_id": "sec_edgar",
            "endpoint_or_family": "submissions_sic",
            "source_as_of": price_basis_ymd,
            "observed_at": generated_at,
            "coverage_status": "full" if len(sector_by_ticker) == len(artifact["eligible_tickers"]) else "partial",
            "parser_status": "ok",
        },
        "sector_by_ticker": sector_by_ticker,
    }


def _build_summary(*, generated_at: str, artifact: dict[str, Any], price_basis_ymd: str, eligible_count: int,
                   sic_resolved_count: int, sector_by_ticker: dict[str, str], candidate_path: Path,
                   packet_path: Path, summary_path: Path) -> dict[str, Any]:
    return {
        "schema_name": "us_short_batch5_full_universe_sec_sic_classification_fetch_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_full_universe_sec_sic_classification_fetch_summary.schema.json",
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "full_universe_sec_sic_sector_classification_fetch",
            "status": "classification_packet_written",
            "network_access_performed": True,
            "provider_calls_performed": True,
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
            "source_as_of": price_basis_ymd,
        },
        "classification": {
            "classification_source": CLASSIFICATION_SOURCE,
            "coarsening": "sic_2digit_major_group",
            "provider_ids": ["sec_edgar"],
            "eligible_count": eligible_count,
            "sic_resolved_count": sic_resolved_count,
            "sic_missing_count": eligible_count - sic_resolved_count,
            "sector_group_count": len(set(sector_by_ticker.values())),
        },
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
            "Only the bounded {ticker: sector} packet (gitignored) is persisted; the ~2404 raw SEC submissions payloads are not.",
            "The tracked summary is counts-only: no ticker lists, sector labels, SEC User-Agent, request URLs, or secrets.",
            "A ticker whose SEC submissions failed or lacked a SIC is absent from the packet and is dispositioned neutral by the theme producer.",
        ],
    }


def run_fetch(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    classification_packet_path: Path | None = None,
    summary_path: Path | None = None,
    generated_at: str | None = None,
    confirm_user_authorization: bool = False,
    sic_source: Callable[[list[str]], dict[str, str]] | None = None,
    interval_seconds: float = SEC_FAIR_ACCESS_SLEEP,
) -> dict[str, Any]:
    if not confirm_user_authorization:
        raise FullUniverseSecSicClassificationFetchError(
            "live SEC SIC classification fetch requires explicit user authorization (confirm_user_authorization=True)"
        )
    if not universe_fetch._check_gitignore():
        raise FullUniverseSecSicClassificationFetchError("provider_samples/ not confirmed in .gitignore")

    generated_at = generated_at or iso_now()
    candidate_path = _resolve_repo_path(candidate_artifact_path, field="candidate_artifact_path")
    if not candidate_path.exists() or not candidate_path.is_file():
        raise FullUniverseSecSicClassificationFetchError(f"candidate_artifact_path must be an existing file: {_repo_rel(candidate_path)}")
    artifact = _load_candidate(candidate_artifact_path=candidate_path)
    price_basis_compact = artifact["price_basis_date"]
    price_basis_ymd = _compact_to_ymd(price_basis_compact, field="candidate.price_basis_date")

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

    eligible = [t for t in (canonical_us_ticker(raw) for raw in artifact["eligible_tickers"]) if t is not None]

    sec_ua = os.environ.get("SEC_USER_AGENT", "")
    source = sic_source if sic_source is not None else _real_sic_source(sec_ua, interval_seconds=interval_seconds)

    raw_sic_by_ticker = source(eligible)
    eligible_set = set(eligible)
    sector_by_ticker: dict[str, str] = {}
    for ticker, sic in raw_sic_by_ticker.items():
        ct = canonical_us_ticker(ticker)
        if ct is None or ct not in eligible_set or ct in sector_by_ticker:
            continue  # ignore a stray / non-eligible / duplicate ticker from the source
        group = _sector_major_group(sic)
        if group is not None:
            sector_by_ticker[ct] = group

    if not sector_by_ticker:
        raise FullUniverseSecSicClassificationFetchError(
            "zero tickers classified (SEC unavailable / no SIC resolved); fail-closed rather than write an empty packet"
        )

    packet = _build_packet(
        generated_at=generated_at, artifact=artifact, price_basis_ymd=price_basis_ymd,
        sector_by_ticker=sector_by_ticker,
    )
    _validate_schema(packet, PACKET_SCHEMA_PATH, label="full-universe sector classification packet")

    summary = _build_summary(
        generated_at=generated_at, artifact=artifact, price_basis_ymd=price_basis_ymd,
        eligible_count=len(eligible), sic_resolved_count=len(sector_by_ticker),
        sector_by_ticker=sector_by_ticker, candidate_path=candidate_path, packet_path=packet_path,
        summary_path=summary_resolved,
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
