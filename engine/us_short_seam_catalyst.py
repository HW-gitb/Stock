"""US-short scoring-seam: catalyst block projection (batch5->batch4 Cut 6-c).

Pure offline glue. It consumes the already-resolved catalyst-source result,
validates that it is still coherent with the frozen source contract, calls the
existing catalyst rule-mapping engine, and projects usable values onto the target
row set that the later score composer will feed into core_score.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from engine.us_short_catalyst import catalyst_block
from engine.us_short_catalyst_source import (
    _COVERAGE_EMIT,
    _PARSER_EMIT,
    _PROVENANCE_FIELDS,
    _SOURCES,
)
from engine.us_short_eligibility_gate import canonical_us_ticker


BINDING_PATH = Path(__file__).resolve().parent.parent / "docs" / "us_short_seam_catalyst_binding_20260702.json"
PRODUCER_REFS = (
    "engine/us_short_catalyst_source.py::resolve_catalyst_signals",
    "engine/us_short_catalyst.py::catalyst_block",
)
PROJECTION_POLICY = "validated_source_result_then_catalyst_block_then_target_projection"

SIGNAL_VALUE_DATE_PAIRS = {value_key: date_key for value_key, date_key, _provider, _endpoint in _SOURCES.values()}
_VALUE_KEYS = frozenset(SIGNAL_VALUE_DATE_PAIRS)
_DATE_KEYS = frozenset(SIGNAL_VALUE_DATE_PAIRS.values())
_SIGNAL_ROW_KEYS = _VALUE_KEYS | _DATE_KEYS
_PROVENANCE_EXPECTED = {
    value_key: {"provider_id": provider, "endpoint_or_filing_type": endpoint}
    for value_key, _date_key, provider, endpoint in _SOURCES.values()
}

SOURCE_RESULT_KEYS = frozenset({"signals", "provenance", "excluded"})
CATALYST_RESULT_KEYS = frozenset({
    "catalyst_block",
    "neutral_fallback",
    "coverage_matrix",
    "neutral_catalyst_score",
    "as_of",
})
COVERAGE_ROW_KEYS = frozenset({"realized", "future_excluded", "unverified_excluded"})
BLOCK_MIN, BLOCK_MAX = 0.0, 100.0

OUTPUT_KEYS = (
    "catalyst_block_by_ticker",
    "neutral_fill_tickers",
    "coverage",
    "target_count",
    "scored_count",
)
DISPOSITION_SCORED_REALIZED = "scored_realized_catalyst"
DISPOSITION_NEUTRAL_NO_REALIZED = "neutral_no_realized_catalyst"
DISPOSITION_NEUTRAL_SOURCE_EXCLUDED = "neutral_source_excluded"
DISPOSITION_NEUTRAL_MISSING_SOURCE = "neutral_missing_catalyst_source"
COVERAGE_DISPOSITIONS = (
    DISPOSITION_SCORED_REALIZED,
    DISPOSITION_NEUTRAL_NO_REALIZED,
    DISPOSITION_NEUTRAL_SOURCE_EXCLUDED,
    DISPOSITION_NEUTRAL_MISSING_SOURCE,
)


class CatalystSeamError(ValueError):
    """Malformed source result, catalyst result, or target identity for Cut 6-c."""


def load_binding():
    return json.loads(BINDING_PATH.read_text(encoding="utf-8"))


def _require_exact_dict(value, *, name):
    if type(value) is not dict:
        raise CatalystSeamError(f"{name} must be an exact dict: {type(value).__name__}")
    return value


def _require_exact_list(value, *, name):
    if type(value) is not list:
        raise CatalystSeamError(f"{name} must be an exact list: {type(value).__name__}")
    return value


def _require_exact_str(value, *, name):
    if type(value) is not str:
        raise CatalystSeamError(f"{name} must be exact str: {type(value).__name__}")
    return value


def _key_set(value, *, name):
    _require_exact_dict(value, name=name)
    out = set()
    for key in value:
        out.add(_require_exact_str(key, name=f"{name} key"))
    return out


def _canonical_ticker(raw, *, where):
    _require_exact_str(raw, name=f"{where} ticker")
    ticker = canonical_us_ticker(raw)
    if ticker is None:
        raise CatalystSeamError(f"{where} ticker must be a canonicalizable US ticker")
    return ticker


def _canonical_targets(target_tickers):
    if type(target_tickers) is not list and type(target_tickers) is not tuple:
        raise CatalystSeamError(f"target_tickers must be exact list/tuple: {type(target_tickers).__name__}")
    out = []
    seen = set()
    for raw in target_tickers:
        ticker = _canonical_ticker(raw, where="target")
        if ticker in seen:
            raise CatalystSeamError(f"target_tickers contains duplicate canonical ticker: {ticker}")
        seen.add(ticker)
        out.append(ticker)
    return out


def _validate_signal_rows(raw_signals):
    _require_exact_dict(raw_signals, name="catalyst_source_result.signals")
    signals = {}
    signal_keys_by_ticker = {}
    for raw_ticker, raw_row in raw_signals.items():
        ticker = _canonical_ticker(raw_ticker, where="signals")
        if ticker in signals:
            raise CatalystSeamError(f"signals contains duplicate canonical ticker: {ticker}")
        _require_exact_dict(raw_row, name=f"signals[{ticker}]")
        keys = _key_set(raw_row, name=f"signals[{ticker}]")
        if not keys or not keys <= _SIGNAL_ROW_KEYS:
            raise CatalystSeamError("signals row keys drifted from catalyst-source value/date contract")
        emitted_value_keys = set()
        for value_key, date_key in SIGNAL_VALUE_DATE_PAIRS.items():
            has_value = value_key in keys
            has_date = date_key in keys
            if has_value != has_date:
                raise CatalystSeamError("signals row must carry each value/date pair together")
            if has_value:
                _require_exact_str(raw_row[date_key], name=f"signals[{ticker}].{date_key}")
                emitted_value_keys.add(value_key)
        if not emitted_value_keys:
            raise CatalystSeamError("signals row must contain at least one emitted catalyst value")
        signals[ticker] = dict(raw_row)
        signal_keys_by_ticker[ticker] = emitted_value_keys
    return signals, signal_keys_by_ticker


def _lineage_ref_is_source_bound(ref, *, provider_id, endpoint, source_as_of):
    if type(ref) is not str or not ref.isascii():
        return False
    prefix, sep, record_id = ref.rpartition("#")
    if sep != "#" or not record_id or any(c.isspace() for c in record_id) or ":" in record_id or "#" in record_id:
        return False
    return prefix == f"{provider_id}:{endpoint}:{source_as_of}"


def _validate_signal_provenance(raw_provenance, signal_keys_by_ticker):
    _require_exact_dict(raw_provenance, name="catalyst_source_result.provenance")
    provenance = {}
    for raw_ticker, raw_row in raw_provenance.items():
        ticker = _canonical_ticker(raw_ticker, where="provenance")
        if ticker in provenance:
            raise CatalystSeamError(f"provenance contains duplicate canonical ticker: {ticker}")
        _require_exact_dict(raw_row, name=f"provenance[{ticker}]")
        row_keys = _key_set(raw_row, name=f"provenance[{ticker}]")
        if row_keys != signal_keys_by_ticker.get(ticker, set()):
            raise CatalystSeamError("provenance keys must exactly cover emitted signal value keys")
        for value_key, raw_prov in raw_row.items():
            _require_exact_dict(raw_prov, name=f"provenance[{ticker}][{value_key}]")
            if _key_set(raw_prov, name=f"provenance[{ticker}][{value_key}]") != set(_PROVENANCE_FIELDS):
                raise CatalystSeamError("provenance field set drifted from catalyst-source contract")
            for field in _PROVENANCE_FIELDS:
                _require_exact_str(raw_prov[field], name=f"provenance[{ticker}][{value_key}].{field}")
            expected = _PROVENANCE_EXPECTED[value_key]
            if raw_prov["provider_id"] != expected["provider_id"]:
                raise CatalystSeamError("provenance provider_id drifted from catalyst-source contract")
            if raw_prov["endpoint_or_filing_type"] != expected["endpoint_or_filing_type"]:
                raise CatalystSeamError("provenance endpoint drifted from catalyst-source contract")
            if raw_prov["coverage_status"] != _COVERAGE_EMIT or raw_prov["parser_status"] != _PARSER_EMIT:
                raise CatalystSeamError("emitted signal provenance must be score-ready full/ok")
            if not _lineage_ref_is_source_bound(
                raw_prov["lineage_ref"],
                provider_id=expected["provider_id"],
                endpoint=expected["endpoint_or_filing_type"],
                source_as_of=raw_prov["source_as_of"],
            ):
                raise CatalystSeamError("provenance lineage_ref is not source-bound")
        provenance[ticker] = dict(raw_row)
    if set(provenance) != set(signal_keys_by_ticker):
        raise CatalystSeamError("provenance identities must exactly equal signals identities")
    return provenance


def _validate_excluded(raw_excluded, signal_keys_by_ticker):
    _require_exact_dict(raw_excluded, name="catalyst_source_result.excluded")
    excluded = {}
    for raw_ticker, raw_row in raw_excluded.items():
        ticker = _canonical_ticker(raw_ticker, where="excluded")
        if ticker in excluded:
            raise CatalystSeamError(f"excluded contains duplicate canonical ticker: {ticker}")
        _require_exact_dict(raw_row, name=f"excluded[{ticker}]")
        row_keys = _key_set(raw_row, name=f"excluded[{ticker}]")
        if not row_keys or not row_keys <= _VALUE_KEYS:
            raise CatalystSeamError("excluded row keys drifted from catalyst-source value contract")
        overlap = row_keys & signal_keys_by_ticker.get(ticker, set())
        if overlap:
            raise CatalystSeamError("excluded row overlaps emitted score-ready signals")
        for value_key, reason in raw_row.items():
            _require_exact_str(reason, name=f"excluded[{ticker}][{value_key}]")
            if not reason.strip():
                raise CatalystSeamError("excluded reason must be non-empty")
        excluded[ticker] = dict(raw_row)
    return excluded


def _validate_source_result(catalyst_source_result):
    _require_exact_dict(catalyst_source_result, name="catalyst_source_result")
    if _key_set(catalyst_source_result, name="catalyst_source_result") != SOURCE_RESULT_KEYS:
        raise CatalystSeamError("catalyst_source_result keys drifted from the Cut 6-c contract")
    signals, signal_keys_by_ticker = _validate_signal_rows(catalyst_source_result["signals"])
    _validate_signal_provenance(catalyst_source_result["provenance"], signal_keys_by_ticker)
    excluded = _validate_excluded(catalyst_source_result["excluded"], signal_keys_by_ticker)
    return signals, excluded


def _finite_block_value(value, *, name):
    if type(value) is not int and type(value) is not float:
        raise CatalystSeamError(f"{name} must be exact int/float in [0,100]: {type(value).__name__}")
    try:
        out = float(value)
    except OverflowError as exc:
        raise CatalystSeamError(f"{name} must be finite in [0,100]") from exc
    if not math.isfinite(out) or out < BLOCK_MIN or out > BLOCK_MAX:
        raise CatalystSeamError(f"{name} must be finite in [0,100]")
    return out


def _validate_coverage_list(raw, *, name):
    _require_exact_list(raw, name=name)
    out = []
    seen = set()
    for value_key in raw:
        _require_exact_str(value_key, name=name)
        if value_key not in _VALUE_KEYS:
            raise CatalystSeamError("catalyst coverage value_key drifted from source contract")
        if value_key in seen:
            raise CatalystSeamError("catalyst coverage list contains duplicate value_key")
        seen.add(value_key)
        out.append(value_key)
    return out


def _validate_catalyst_result(result, *, as_of):
    _require_exact_dict(result, name="catalyst_block result")
    if _key_set(result, name="catalyst_block result") != CATALYST_RESULT_KEYS:
        raise CatalystSeamError("catalyst_block result keys drifted from the Cut 6-c contract")
    if result["as_of"] != as_of:
        raise CatalystSeamError("catalyst_block result as_of drifted from input as_of")
    _finite_block_value(result["neutral_catalyst_score"], name="neutral_catalyst_score")

    block = {}
    for raw_ticker, value in _require_exact_dict(result["catalyst_block"], name="catalyst_block").items():
        ticker = _canonical_ticker(raw_ticker, where="catalyst_block")
        if ticker in block:
            raise CatalystSeamError(f"catalyst_block contains duplicate canonical ticker: {ticker}")
        block[ticker] = _finite_block_value(value, name=f"catalyst_block[{ticker}]")

    neutral = set()
    for raw_ticker in _require_exact_list(result["neutral_fallback"], name="neutral_fallback"):
        ticker = _canonical_ticker(raw_ticker, where="neutral_fallback")
        if ticker in neutral:
            raise CatalystSeamError(f"neutral_fallback contains duplicate canonical ticker: {ticker}")
        neutral.add(ticker)
    if not neutral <= set(block):
        raise CatalystSeamError("neutral_fallback must be a subset of catalyst_block identities")

    matrix = {}
    for raw_ticker, raw_row in _require_exact_dict(result["coverage_matrix"], name="coverage_matrix").items():
        ticker = _canonical_ticker(raw_ticker, where="coverage_matrix")
        if ticker in matrix:
            raise CatalystSeamError(f"coverage_matrix contains duplicate canonical ticker: {ticker}")
        _require_exact_dict(raw_row, name=f"coverage_matrix[{ticker}]")
        if _key_set(raw_row, name=f"coverage_matrix[{ticker}]") != COVERAGE_ROW_KEYS:
            raise CatalystSeamError("coverage_matrix row keys drifted from catalyst_block contract")
        realized = _validate_coverage_list(raw_row["realized"], name="coverage_matrix.realized")
        future = _validate_coverage_list(raw_row["future_excluded"], name="coverage_matrix.future_excluded")
        unverified = _validate_coverage_list(raw_row["unverified_excluded"], name="coverage_matrix.unverified_excluded")
        if (ticker in neutral) == bool(realized):
            raise CatalystSeamError("neutral_fallback must match catalyst_block realized coverage")
        matrix[ticker] = {
            "realized": realized,
            "future_excluded": future,
            "unverified_excluded": unverified,
        }
    if set(matrix) != set(block):
        raise CatalystSeamError("coverage_matrix identities must exactly equal catalyst_block identities")
    return block, neutral


def project_catalyst_block(*, catalyst_source_result, governance, as_of, target_tickers):
    """Project catalyst-source output to per-target 25% catalyst-block values.

    Score-ready source signals are first validated against the catalyst-source
    contract, then scored by engine.us_short_catalyst.catalyst_block. A target
    with no realized catalyst, only source exclusions, or no source presence is
    omitted from catalyst_block_by_ticker and surfaced in neutral_fill_tickers so
    the composer can apply core_score's neutral-block rule.
    """
    _require_exact_str(as_of, name="as_of")
    targets = _canonical_targets(target_tickers)
    signals, excluded = _validate_source_result(catalyst_source_result)
    raw_block = catalyst_block(signals, governance, as_of=as_of)
    block, neutral = _validate_catalyst_result(raw_block, as_of=as_of)

    catalyst_by_ticker = {}
    neutral_fill = []
    coverage = {}
    for ticker in targets:
        if ticker in block and ticker not in neutral:
            catalyst_by_ticker[ticker] = block[ticker]
            coverage[ticker] = DISPOSITION_SCORED_REALIZED
        else:
            neutral_fill.append(ticker)
            if ticker in block and ticker in neutral:
                coverage[ticker] = DISPOSITION_NEUTRAL_NO_REALIZED
            elif ticker in excluded:
                coverage[ticker] = DISPOSITION_NEUTRAL_SOURCE_EXCLUDED
            else:
                coverage[ticker] = DISPOSITION_NEUTRAL_MISSING_SOURCE
    return {
        "catalyst_block_by_ticker": catalyst_by_ticker,
        "neutral_fill_tickers": neutral_fill,
        "coverage": coverage,
        "target_count": len(targets),
        "scored_count": len(catalyst_by_ticker),
    }
