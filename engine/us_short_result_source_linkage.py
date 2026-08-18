# -*- coding: utf-8 -*-
"""US-short Cut4 source-to-result linkage.

This module is intentionally a narrow bridge.  It consumes already-resolved Batch5
source facts and the existing local OHLCV packet, turns them into one per-ticker
record, and later binds that record to the Batch4 row.  It never fetches a provider,
re-scores a catalyst, or invents price geometry: the existing score and price
engines remain the only owners of those computations.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema

from engine.us_short_coverage_honesty import CoverageHonestyError, build_row_coverage, validate_row_coverage
from engine.us_short_eligibility_gate import canonical_us_ticker


ROOT = Path(__file__).resolve().parent.parent
OHLCV_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_ohlcv_series_packet.schema.json"

_SOURCE_FACT_KEYS = frozenset({
    "ticker", "row_source", "as_of", "price_basis_date", "source_bundle_digest", "coverage",
    "catalyst", "price", "data_quality_tags", "execution_constraints", "evidence_ref",
})
_COVERAGE_KEYS = frozenset({"row_source", "data_checks", "coverage_status", "coverage_gap_tags"})
_CATALYST_KEYS = frozenset({"status", "coverage_disposition", "coverage_matrix", "provenance", "evidence_ref"})
_PRICE_KEYS = frozenset({"status", "input", "observed_at", "session", "adjustment_mode", "evidence_ref"})
_CHECK_STATUS = frozenset({"ok", "missing", "restricted", "blocked"})
_SOURCE_STATUS = frozenset({"ohlcv_ready", "close_only", "missing"})
_CATALYST_STATUS = frozenset({"realized", "neutral_unavailable", "gated"})
_MIN_OHLCV_BARS = 15   # a present series with fewer usable bars degrades that ticker to close-only (build+validate share this)


class ResultSourceLinkageError(ValueError):
    """A source fact cannot safely enter, or remain on, an official result row."""


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _finite_positive(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value)) and float(value) > 0.0
    except OverflowError:                       # huge int (e.g. 10**400) → not a usable price (mirror price_engine guard)
        return False


def _strict_yyyymmdd(value: Any) -> bool:
    if not (isinstance(value, str) and len(value) == 8 and value.isascii() and value.isdigit()):
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _iso_to_compact(value: Any, *, where: str) -> str:
    if not isinstance(value, str):
        raise ResultSourceLinkageError(f"{where} must be YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y%m%d")
    except ValueError as exc:
        raise ResultSourceLinkageError(f"{where} must be a real YYYY-MM-DD") from exc


def _source_bundle_digest(source_digests: dict[str, str]) -> str:
    if not isinstance(source_digests, dict) or not source_digests:
        raise ResultSourceLinkageError("source_digests must be a non-empty source-role digest map")
    rows = []
    for role, digest in source_digests.items():
        if not _nonblank(role) or not (isinstance(digest, str) and len(digest) == 64
                                       and digest.isascii()
                                       and all(c in "0123456789abcdef" for c in digest)):
            raise ResultSourceLinkageError("source_digests contains a non-canonical role or SHA-256")
        rows.append((role.strip(), digest))
    if len({role for role, _ in rows}) != len(rows):
        raise ResultSourceLinkageError("source_digests contains duplicate roles")
    return hashlib.sha256(json.dumps(sorted(rows), separators=(",", ":")).encode("ascii")).hexdigest()


def _ticker_members(value: Any) -> set[str]:
    if isinstance(value, dict):
        raw = value.keys()
    elif isinstance(value, list):
        raw = (item.get("ticker") if isinstance(item, dict) else item for item in value)
    else:
        return set()
    out = set()
    for item in raw:
        ticker = canonical_us_ticker(item)
        if ticker is not None:
            out.add(ticker)
    return out


def _source_check(source: Any, ticker: str) -> str:
    """A resolved source envelope's per-ticker availability, not a score conclusion."""
    if not isinstance(source, dict):
        return "blocked"
    excluded = _ticker_members(source.get("excluded"))
    if ticker in excluded:
        return "restricted"
    if ticker in _ticker_members(source.get("signals")) | _ticker_members(source.get("checked")) | _ticker_members(source.get("records")):
        return "ok"
    return "missing"


def _projection_check(disposition: Any) -> str:
    if not _nonblank(disposition):
        return "blocked"
    text = disposition.strip().casefold()
    if "blocked" in text:
        return "blocked"
    if "excluded" in text or "gated" in text or "restricted" in text:
        return "restricted"
    if "missing" in text or "unavailable" in text:
        return "missing"
    return "ok"


def _catalyst_status(disposition: Any) -> str:
    text = disposition.strip().casefold() if _nonblank(disposition) else ""
    if text == "scored_realized_catalyst":
        return "realized"
    if "excluded" in text or "gated" in text or "restricted" in text:
        return "gated"
    return "neutral_unavailable"


def _validate_ohlcv_packet(packet: Any, *, as_of: str, price_basis_date: str) -> dict[str, Any]:
    if not isinstance(packet, dict):
        raise ResultSourceLinkageError("OHLCV source packet must be an object")
    try:
        schema = json.loads(OHLCV_SCHEMA_PATH.read_text(encoding="utf-8"))
        errors = list(jsonschema.Draft7Validator(schema).iter_errors(packet))
    except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        raise ResultSourceLinkageError("OHLCV schema cannot be loaded") from exc
    if errors:
        raise ResultSourceLinkageError("OHLCV source packet violates its schema")
    clock = packet["decision_clock"]
    if (clock["expected_decision_date"] != as_of
            or clock["candidate_price_basis_date"] != price_basis_date
            or _iso_to_compact(clock["price_basis_date"], where="OHLCV price_basis_date") != price_basis_date
            or _iso_to_compact(clock["source_as_of"], where="OHLCV source_as_of") != price_basis_date):
        raise ResultSourceLinkageError("OHLCV decision clock does not bind this run's decision/price basis")
    contract, provenance = packet["series_contract"], packet["provenance"]
    if (_iso_to_compact(contract["as_of"], where="OHLCV series_contract.as_of") != price_basis_date
            or _iso_to_compact(provenance["source_as_of"], where="OHLCV provenance.source_as_of") != price_basis_date):
        raise ResultSourceLinkageError("OHLCV contract/provenance price basis does not bind this run")
    return packet


def _ohlcv_price(ohlcv_packet: dict[str, Any] | None, *, ticker: str, price_basis_date: str,
                 universe_close: Any, as_of: str, source_digest: str) -> tuple[dict[str, Any], str, list[str], list[str]]:
    evidence = {"kind": "source_id", "value": f"batch5_ohlcv:{source_digest}:{ticker}", "as_of": as_of}
    if ohlcv_packet is None:
        input_row = {"close": float(universe_close)} if _finite_positive(universe_close) else {}
        status = "close_only" if input_row else "missing"
        return ({"status": status, "input": input_row, "observed_at": "unavailable",
                 "session": "unknown_close_only", "adjustment_mode": "unknown_close_only", "evidence_ref": evidence},
                "missing" if status == "close_only" else "blocked",
                (["price:close_only"] if status == "close_only" else ["price:missing"]),
                (["price_structure:close_only_no_execution", "spread:unavailable_manual_check"]
                 if status == "close_only" else ["price_structure:missing", "spread:unavailable_manual_check"]))
    series = ohlcv_packet["series_by_ticker"].get(ticker)
    if not isinstance(series, dict):
        input_row = {"close": float(universe_close)} if _finite_positive(universe_close) else {}
        return ({"status": "close_only" if input_row else "missing", "input": input_row,
                 "observed_at": ohlcv_packet["provenance"]["observed_at"],
                 "session": ohlcv_packet["series_contract"]["session"],
                 "adjustment_mode": ohlcv_packet["series_contract"]["adjustment_mode"], "evidence_ref": evidence},
                "missing" if input_row else "blocked",
                ["price:series_missing"],
                ["price_structure:close_only_no_execution", "spread:unavailable_manual_check"])
    contract = ohlcv_packet["series_contract"]
    if (series.get("as_of") != contract["as_of"] or series.get("session") != contract["session"]
            or series.get("adjustment_mode") != contract["adjustment_mode"]):
        raise ResultSourceLinkageError(f"{ticker}: OHLCV series session/adjustment/as_of does not bind its packet")
    def _degrade(gap_tag: str) -> tuple[dict[str, Any], str, list[str], list[str]]:
        # A present-but-imperfect series degrades THIS ticker to close-only/observe, NOT a global raise (design §6
        # per-ticker "只有收盘价必须转观察" + the OHLCV packet schema's lenient contract: the engine dispositions a
        # bad ticker as insufficient_data). Packet-INTEGRITY failures above stay fatal; per-ticker DATA quality degrades here.
        close_row = {"close": float(universe_close)} if _finite_positive(universe_close) else {}
        return ({"status": "close_only" if close_row else "missing", "input": close_row,
                 "observed_at": ohlcv_packet["provenance"]["observed_at"], "session": contract["session"],
                 "adjustment_mode": contract["adjustment_mode"], "evidence_ref": evidence},
                "missing" if close_row else "blocked", [gap_tag],
                (["price_structure:close_only_no_execution", "spread:unavailable_manual_check"] if close_row
                 else ["price_structure:missing", "spread:unavailable_manual_check"]))
    points = series.get("points")
    if not isinstance(points, list) or not points:
        return _degrade("price:empty_series")
    previous = None
    bars = []
    for point in points:
        if not isinstance(point, dict) or not all(_finite_positive(point.get(key)) for key in ("high", "low", "close")):
            return _degrade("price:invalid_bar")
        date = point.get("date")
        if not isinstance(date, str) or (previous is not None and date <= previous):
            return _degrade("price:disordered")
        if float(point["high"]) < float(point["low"]) or not (float(point["low"]) <= float(point["close"]) <= float(point["high"])):
            return _degrade("price:bad_geometry")
        previous = date
        bar = {"high": float(point["high"]), "low": float(point["low"]), "close": float(point["close"])}
        if "volume" in point:
            bar["volume"] = point["volume"]
        bars.append(bar)
    try:
        final_compact = _iso_to_compact(points[-1]["date"], where=f"{ticker} OHLCV final point")
    except ResultSourceLinkageError:
        return _degrade("price:bad_final_date")
    if final_compact != price_basis_date:
        return _degrade("price:stale_last_bar")
    if len(bars) < _MIN_OHLCV_BARS:
        return _degrade("price:insufficient_history")
    packet_status = ohlcv_packet["provenance"]["coverage_status"]
    price_check = "ok" if packet_status == "full" and ohlcv_packet["provenance"]["parser_status"] == "ok" else "missing"
    tags = [] if price_check == "ok" else ["price:partial_ohlcv"]
    constraints = ["spread:unavailable_manual_check"]
    return ({"status": "ohlcv_ready", "input": {"close": bars[-1]["close"], "bars": bars},
             "observed_at": ohlcv_packet["provenance"]["observed_at"], "session": contract["session"],
             "adjustment_mode": contract["adjustment_mode"], "evidence_ref": evidence},
            price_check, tags, constraints)


def _unique_tags(values: list[str]) -> list[str]:
    out = []
    for value in values:
        if _nonblank(value) and value not in out:
            out.append(value)
    return out


def build_result_source_facts(
    *,
    context_components: dict[str, Any],
    source_payloads: dict[str, Any],
    source_digests: dict[str, str],
    ohlcv_packet: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build closed-world source facts for exactly the official per-ticker rows.

    All availability results are explicit: no source lookup is silently treated as
    clean.  Existing score/catalyst projections are *described*, never recomputed.
    """
    if not isinstance(context_components, dict):
        raise ResultSourceLinkageError("context_components must be an object")
    per = context_components.get("per_ticker_analysis")
    score = context_components.get("score_composition")
    data = context_components.get("data_context")
    provenance = context_components.get("run_provenance")
    if not (isinstance(per, dict) and isinstance(score, dict) and isinstance(data, dict) and isinstance(provenance, dict)):
        raise ResultSourceLinkageError("official context components lack source-bound analysis/score/data/provenance")
    as_of, price_basis = provenance.get("as_of"), provenance.get("price_basis_date")
    if not _strict_yyyymmdd(as_of) or not _strict_yyyymmdd(price_basis):
        raise ResultSourceLinkageError("run provenance lacks canonical decision/price basis dates")
    if ohlcv_packet is not None:
        _validate_ohlcv_packet(ohlcv_packet, as_of=as_of, price_basis_date=price_basis)
    source_digest = _source_bundle_digest(source_digests)
    coverage_by_ticker = score.get("coverage_by_ticker")
    if not isinstance(coverage_by_ticker, dict):
        raise ResultSourceLinkageError("score_composition.coverage_by_ticker must be an object")
    universe = {}
    for raw in data.get("universe") or []:
        if isinstance(raw, dict) and canonical_us_ticker(raw.get("ticker")) == raw.get("ticker"):
            universe[raw["ticker"]] = raw
    out: dict[str, dict[str, Any]] = {}
    for raw_ticker, row in per.items():
        ticker = canonical_us_ticker(raw_ticker)
        if ticker is None or ticker != raw_ticker or not isinstance(row, dict) or row.get("ticker") != ticker:
            raise ResultSourceLinkageError("per_ticker_analysis identity is not canonical")
        row_source = row.get("row_source")
        score_coverage = coverage_by_ticker.get(ticker)
        if isinstance(row.get("score_blocks"), dict) and not isinstance(score_coverage, dict):
            raise ResultSourceLinkageError(f"{ticker}: score coverage is absent")
        if not isinstance(score_coverage, dict):
            score_coverage = {}
        checks = {
            "analyst": _source_check(source_payloads.get("analyst_grade_actions_path"), ticker),
            "sec_parse": _source_check(source_payloads.get("offering_audit_source_path"), ticker),
            "event": _source_check(source_payloads.get("massive_news_events_path"), ticker),
            "price": "blocked",
        }
        if isinstance(row.get("score_blocks"), dict):
            for component in ("momentum", "theme", "catalyst"):
                checks[component] = _projection_check(score_coverage.get(component))
        price, price_check, price_tags, execution_constraints = _ohlcv_price(
            ohlcv_packet, ticker=ticker, price_basis_date=price_basis,
            universe_close=(universe.get(ticker) or {}).get("price"), as_of=as_of, source_digest=source_digest,
        )
        checks["price"] = price_check
        try:
            coverage = build_row_coverage(row_source, checks, required_categories=tuple(checks))
        except CoverageHonestyError as exc:
            raise ResultSourceLinkageError(f"{ticker}: source coverage is invalid: {exc}") from exc
        coverage = {**coverage, "data_checks": checks}
        catalyst_disposition = score_coverage.get("catalyst")
        catalyst = {
            "status": _catalyst_status(catalyst_disposition),
            "coverage_disposition": catalyst_disposition if _nonblank(catalyst_disposition) else "missing",
            "coverage_matrix": {"score_projection_disposition": catalyst_disposition if _nonblank(catalyst_disposition) else "missing"},
            "provenance": {"source_bundle_digest": source_digest},
            "evidence_ref": {"kind": "source_id", "value": f"batch5_catalyst:{source_digest}:{ticker}", "as_of": as_of},
        }
        quality = list(coverage["coverage_gap_tags"]) + price_tags
        if catalyst["status"] == "realized":
            quality.append("catalyst:realized")
        elif catalyst["status"] == "neutral_unavailable":
            quality.append("catalyst:neutral_unavailable")
        elif catalyst["status"] == "gated":
            quality.append("catalyst:gated")
        adv = (universe.get(ticker) or {}).get("adv_usd")
        if not _finite_positive(adv):
            execution_constraints.append("liquidity:adv_unavailable")
        else:
            execution_constraints.append("liquidity:adv_derived_cap")
        evidence = {"kind": "source_id", "value": f"batch5_source_bundle:{source_digest}:{ticker}", "as_of": as_of}
        out[ticker] = {
            "ticker": ticker,
            "row_source": row_source,
            "as_of": as_of,
            "price_basis_date": price_basis,
            "source_bundle_digest": source_digest,
            "coverage": coverage,
            "catalyst": catalyst,
            "price": price,
            "data_quality_tags": _unique_tags(quality),
            "execution_constraints": _unique_tags(execution_constraints),
            "evidence_ref": evidence,
        }
    if set(out) != set(per):
        raise ResultSourceLinkageError("source facts do not exactly cover official analysis rows")
    return out


def validate_result_source_fact(value: Any, *, ticker: str, row_source: str, as_of: str,
                                price_basis_date: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _SOURCE_FACT_KEYS:
        raise ResultSourceLinkageError(f"{ticker}: source_result_facts must be closed-world {sorted(_SOURCE_FACT_KEYS)}")
    if (value.get("ticker") != ticker or value.get("row_source") != row_source or value.get("as_of") != as_of
            or value.get("price_basis_date") != price_basis_date):
        raise ResultSourceLinkageError(f"{ticker}: source_result_facts identity/date binding mismatch")
    digest = value.get("source_bundle_digest")
    if not (isinstance(digest, str) and len(digest) == 64 and digest.isascii()
            and all(c in "0123456789abcdef" for c in digest)):
        raise ResultSourceLinkageError(f"{ticker}: source bundle digest is invalid")
    coverage = value.get("coverage")
    if not isinstance(coverage, dict) or set(coverage) != _COVERAGE_KEYS or coverage.get("row_source") != row_source:
        raise ResultSourceLinkageError(f"{ticker}: coverage source binding is invalid")
    checks = coverage.get("data_checks")
    if not isinstance(checks, dict) or not checks or any(status not in _CHECK_STATUS for status in checks.values()):
        raise ResultSourceLinkageError(f"{ticker}: coverage data_checks are invalid")
    try:
        expected = build_row_coverage(row_source, checks, required_categories=tuple(checks))
        validate_row_coverage(coverage)
    except CoverageHonestyError as exc:
        raise ResultSourceLinkageError(f"{ticker}: coverage record is invalid") from exc
    if {key: coverage[key] for key in ("row_source", "coverage_status", "coverage_gap_tags")} != expected:
        raise ResultSourceLinkageError(f"{ticker}: coverage is not the actual worst-of source checks")
    catalyst = value.get("catalyst")
    if (not isinstance(catalyst, dict) or set(catalyst) != _CATALYST_KEYS
            or catalyst.get("status") not in _CATALYST_STATUS
            or not isinstance(catalyst.get("coverage_matrix"), dict)
            or set(catalyst["coverage_matrix"]) != {"score_projection_disposition"}
            or not _nonblank(catalyst["coverage_matrix"]["score_projection_disposition"])
            or not isinstance(catalyst.get("provenance"), dict)
            or set(catalyst["provenance"]) != {"source_bundle_digest"}
            or catalyst["provenance"].get("source_bundle_digest") != digest):
        raise ResultSourceLinkageError(f"{ticker}: catalyst source fact is invalid")
    price = value.get("price")
    if (not isinstance(price, dict) or set(price) != _PRICE_KEYS or price.get("status") not in _SOURCE_STATUS
            or not _nonblank(price.get("observed_at")) or not _nonblank(price.get("session"))
            or not _nonblank(price.get("adjustment_mode"))):
        raise ResultSourceLinkageError(f"{ticker}: price source fact is invalid")
    price_input = price.get("input")
    if not isinstance(price_input, dict):
        raise ResultSourceLinkageError(f"{ticker}: price source input is invalid")
    if price["status"] == "ohlcv_ready":
        bars = price_input.get("bars")
        if not (_finite_positive(price_input.get("close")) and isinstance(bars, list) and len(bars) >= _MIN_OHLCV_BARS):
            raise ResultSourceLinkageError(f"{ticker}: OHLCV-ready price source needs close and >=15 bars")
    if price["status"] == "close_only" and not _finite_positive(price_input.get("close")):
        raise ResultSourceLinkageError(f"{ticker}: close-only source needs a positive source close")
    for key in ("data_quality_tags", "execution_constraints"):
        tags = value.get(key)
        if not isinstance(tags, list) or len(tags) != len(set(tags)) or not all(_nonblank(tag) for tag in tags):
            raise ResultSourceLinkageError(f"{ticker}: {key} must be unique non-blank tags")
    for where, ref in (("source", value.get("evidence_ref")), ("catalyst", catalyst.get("evidence_ref")), ("price", price.get("evidence_ref"))):
        if not (isinstance(ref, dict) and set(ref) == {"kind", "value", "as_of"}
                and ref.get("kind") == "source_id" and _nonblank(ref.get("value")) and ref.get("as_of") == as_of):
            raise ResultSourceLinkageError(f"{ticker}: {where} evidence ref is invalid")
    return value


def bind_result_source_facts(rows: list[dict[str, Any]], *, as_of: str, price_basis_date: str) -> list[dict[str, Any]]:
    """Make the source-bound price input and output fields the only row projection.

    Legacy fixture rows without source facts remain supported outside the Batch5 bridge.
    A row that claims to have Cut4 facts must be fully bound; a caller cannot mix a
    synthetic ``price_input`` beside source facts.
    """
    if not isinstance(rows, list):
        raise ResultSourceLinkageError("rows must be a list")
    has_facts = [isinstance(row, dict) and "source_result_facts" in row for row in rows]
    if any(has_facts) and not all(has_facts):
        raise ResultSourceLinkageError("source-bound and legacy analysis rows must not be mixed")
    if not any(has_facts):
        return rows
    out = []
    for row in rows:
        ticker = canonical_us_ticker(row.get("ticker")) if isinstance(row, dict) else None
        if ticker is None or not isinstance(row, dict) or row.get("ticker") != ticker:
            raise ResultSourceLinkageError("analysis row identity is invalid")
        fact = validate_result_source_fact(row.get("source_result_facts"), ticker=ticker,
                                           row_source=row.get("row_source"), as_of=as_of,
                                           price_basis_date=price_basis_date)
        engine_price_input = (dict(fact["price"]["input"])
                              if fact["price"]["status"] == "ohlcv_ready" else {})
        supplied = row.get("price_input")
        if supplied is not None and supplied != engine_price_input:
            raise ResultSourceLinkageError(f"{ticker}: caller price_input conflicts with source-bound price input")
        out.append({**row, "price_input": engine_price_input,
                    "source_result_facts": fact,
                    "coverage_status": fact["coverage"]["coverage_status"],
                    "coverage_gap_tags": list(fact["coverage"]["coverage_gap_tags"]),
                    "data_quality_tags": list(fact["data_quality_tags"]),
                    "execution_constraints": list(fact["execution_constraints"])})
    return out


def source_coverage_effect_records(rows: list[dict[str, Any]], *, as_of: str) -> dict[str, list[dict[str, Any]]]:
    """Turn non-full source coverage into the existing Cut2 reducer, once only."""
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        ticker = row.get("ticker") if isinstance(row, dict) else None
        fact = row.get("source_result_facts") if isinstance(row, dict) else None
        if fact is None:
            continue
        if not isinstance(ticker, str):
            raise ResultSourceLinkageError("source-effect row lacks ticker")
        coverage = fact["coverage"]
        status = coverage["coverage_status"]
        record = {
            "source": "source_coverage:" + status,
            "evidence_ref": fact["evidence_ref"],
            "risk_tags": (["source_coverage:" + status, *fact["data_quality_tags"]]
                          if status != "full" else []),
            "trigger_conditions": [],
            "invalid_conditions": (["source_coverage:" + status] if status != "full" else []),
            "size_multiplier": None,
            "confidence_cap": None,
            "action_override": None,
        }
        if status == "partial":
            record["confidence_cap"] = 0.75
        elif status in {"restricted", "blocked"}:
            record["confidence_cap"] = 0.50
            if row.get("final_action") == "建仓":
                record["action_override"] = {"final_action": "观察", "observe_reason_type": "data_restricted"}
        out[ticker] = [record]
    if out and set(out) != {row.get("ticker") for row in rows if isinstance(row, dict)}:
        raise ResultSourceLinkageError("source coverage effect records do not cover every source-bound row")
    return out
