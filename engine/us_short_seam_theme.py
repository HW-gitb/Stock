# -*- coding: utf-8 -*-
"""US-short scoring-seam: theme/industry block projection (batch5->batch4 Cut 6-b).

This module is pure offline glue. It consumes two already-computed batch5 producer
outputs:

* engine/us_short_industry_heat.py::industry_heat_block
* engine/us_short_provisional_theme_heat.py::provisional_theme_heat_block

assembles the 35% theme block on the full producer/membership pool, then projects
the already-computed block values onto the target row set that the later score
composer will feed into core_score. It does not fetch data, re-run producers, select a
provider, write DataHub state, or compose the final score.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_theme_block import assemble_theme_block


BINDING_PATH = Path(__file__).resolve().parent.parent / "docs" / "us_short_seam_theme_binding_20260702.json"
PRODUCER_REFS = (
    "engine/us_short_industry_heat.py::industry_heat_block",
    "engine/us_short_provisional_theme_heat.py::provisional_theme_heat_block",
)


def load_binding():
    return json.loads(BINDING_PATH.read_text(encoding="utf-8"))


BLOCK_MIN, BLOCK_MAX = 0.0, 100.0
INDUSTRY_RESULT_KEYS = frozenset({
    "industry_heat_by_ticker",
    "sector_heat",
    "sector_metrics",
    "insufficient_sectors",
    "min_sector_members",
})
THEME_RESULT_KEYS = frozenset({
    "theme_heat",
    "confirm_flags",
    "theme_metrics",
    "insufficient_themes",
    "min_theme_members",
})
CONFIRM_FLAG_KEYS = (
    "theme_breadth_up_frac",
    "theme_volume_confirm_frac",
    "theme_leader_rs",
    "theme_member_count",
)
OUTPUT_KEYS = (
    "theme_block_by_ticker",
    "neutral_fill_tickers",
    "coverage",
    "target_count",
    "scored_count",
)
DISPOSITION_SCORED_THEME_BASE = "scored_theme_base"
DISPOSITION_SCORED_INDUSTRY_BASE = "scored_industry_base"
DISPOSITION_NEUTRAL_INSUFFICIENT_THEME_NO_INDUSTRY = "neutral_insufficient_theme_no_industry"
DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE = "neutral_missing_theme_and_industry_base"
COVERAGE_DISPOSITIONS = (
    DISPOSITION_SCORED_THEME_BASE,
    DISPOSITION_SCORED_INDUSTRY_BASE,
    DISPOSITION_NEUTRAL_INSUFFICIENT_THEME_NO_INDUSTRY,
    DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE,
)
THEME_MEMBERSHIP_POLICY = "one_primary_theme_per_ticker_fail_closed"
PROJECTION_BASIS_POLICY = (
    "full_producer_membership_pool_then_target_projection"
)


class ThemeSeamError(ValueError):
    """Malformed producer result, membership map, or target set for the Cut 6-b seam."""


def _require_exact_dict(value, *, name):
    if type(value) is not dict:
        raise ThemeSeamError(f"{name} must be an exact dict: {type(value).__name__}")
    return value


def _require_exact_list(value, *, name):
    if type(value) is not list:
        raise ThemeSeamError(f"{name} must be an exact list: {type(value).__name__}")
    return value


def _require_str_key(key, *, name):
    if type(key) is not str:
        raise ThemeSeamError(f"{name} keys must be exact str: {type(key).__name__}")
    return key


def _dict_key_set(value, *, name):
    _require_exact_dict(value, name=name)
    keys = set()
    for key in value.keys():
        keys.add(_require_str_key(key, name=name))
    return keys


def _finite_block_value(value, *, name):
    if type(value) is not int and type(value) is not float:
        raise ThemeSeamError(f"{name} value must be exact int/float in [0,100]: {type(value).__name__}")
    try:
        out = float(value)
    except OverflowError as exc:
        raise ThemeSeamError(f"{name} value must be finite in [0,100]") from exc
    if not math.isfinite(out) or out < BLOCK_MIN or out > BLOCK_MAX:
        raise ThemeSeamError(f"{name} value must be finite in [0,100]")
    return out


def _exact_positive_int(value, *, name):
    if type(value) is not int or value < 1:
        raise ThemeSeamError(f"{name} must be an exact positive int: {type(value).__name__}")
    return value


def _canonical_theme_id(raw, *, where):
    if type(raw) is not str:
        raise ThemeSeamError(f"{where} theme_id must be exact str: {type(raw).__name__}")
    theme_id = raw.strip()
    if not theme_id:
        raise ThemeSeamError(f"{where} theme_id must be non-empty")
    return theme_id


def _canonical_ticker(raw, *, where):
    if type(raw) is not str:
        raise ThemeSeamError(f"{where} ticker must be exact str: {type(raw).__name__}")
    ticker = canonical_us_ticker(raw)
    if ticker is None:
        raise ThemeSeamError(f"{where} ticker must be a canonicalizable US ticker")
    return ticker


def _canonical_targets(target_tickers):
    if type(target_tickers) is not list and type(target_tickers) is not tuple:
        raise ThemeSeamError(f"target_tickers must be exact list/tuple: {type(target_tickers).__name__}")
    targets = []
    seen = set()
    for raw in target_tickers:
        ticker = _canonical_ticker(raw, where="target")
        if ticker in seen:
            raise ThemeSeamError(f"target_tickers contains duplicate canonical ticker: {ticker}")
        seen.add(ticker)
        targets.append(ticker)
    return targets


def _validate_heat_by_ticker(raw, *, name):
    _require_exact_dict(raw, name=name)
    out = {}
    for key, value in raw.items():
        ticker = _canonical_ticker(key, where=name)
        if ticker in out:
            raise ThemeSeamError(f"{name} contains duplicate canonical ticker: {ticker}")
        out[ticker] = _finite_block_value(value, name=name)
    return out


def _validate_heat_by_theme(raw, *, name):
    _require_exact_dict(raw, name=name)
    out = {}
    for key, value in raw.items():
        theme_id = _canonical_theme_id(key, where=name)
        if theme_id in out:
            raise ThemeSeamError(f"{name} contains duplicate canonical theme_id")
        out[theme_id] = _finite_block_value(value, name=name)
    return out


def _validate_label_heat(raw, *, name):
    _require_exact_dict(raw, name=name)
    out = {}
    for key, value in raw.items():
        label = _canonical_theme_id(key, where=name)
        if label in out:
            raise ThemeSeamError(f"{name} contains duplicate normalized label")
        out[label] = _finite_block_value(value, name=name)
    return out


def _validate_label_list(raw, *, name):
    _require_exact_list(raw, name=name)
    out = []
    seen = set()
    for item in raw:
        label = _canonical_theme_id(item, where=name)
        if label in seen:
            raise ThemeSeamError(f"{name} contains duplicate normalized label")
        seen.add(label)
        out.append(label)
    return out


def _validate_label_rows(raw, *, name):
    _require_exact_dict(raw, name=name)
    out = {}
    for key, row in raw.items():
        label = _canonical_theme_id(key, where=name)
        if label in out:
            raise ThemeSeamError(f"{name} contains duplicate normalized label")
        _require_exact_dict(row, name=f"{name} row")
        out[label] = row
    return out


def _validate_industry_result(industry_result):
    _require_exact_dict(industry_result, name="industry_result")
    if _dict_key_set(industry_result, name="industry_result") != set(INDUSTRY_RESULT_KEYS):
        raise ThemeSeamError("industry_result keys drifted from the Cut 6-b contract")
    _validate_label_heat(industry_result["sector_heat"], name="sector_heat")
    _validate_label_rows(industry_result["sector_metrics"], name="sector_metrics")
    _validate_label_list(industry_result["insufficient_sectors"], name="insufficient_sectors")
    _exact_positive_int(industry_result["min_sector_members"], name="min_sector_members")
    return _validate_heat_by_ticker(industry_result["industry_heat_by_ticker"], name="industry_heat_by_ticker")


def _validate_confirm_flags(confirm_flags, theme_ids):
    _require_exact_dict(confirm_flags, name="confirm_flags")
    normalized_theme_ids = set()
    for key in confirm_flags.keys():
        theme_id = _canonical_theme_id(key, where="confirm_flags")
        if theme_id in normalized_theme_ids:
            raise ThemeSeamError("duplicate normalized theme_id in confirm_flags")
        normalized_theme_ids.add(theme_id)
    if normalized_theme_ids != set(theme_ids):
        raise ThemeSeamError("confirm_flags keys must exactly equal scored theme_heat keys")
    out = {}
    for raw_theme_id, row in confirm_flags.items():
        theme_id = _canonical_theme_id(raw_theme_id, where="confirm_flags")
        _require_exact_dict(row, name="confirm_flags row")
        if _dict_key_set(row, name="confirm_flags row") != set(CONFIRM_FLAG_KEYS):
            raise ThemeSeamError("confirm_flags row keys drifted from the Cut 6-b contract")
        for flag in CONFIRM_FLAG_KEYS:
            if type(row[flag]) is not bool:
                raise ThemeSeamError(f"confirm_flags.{flag} must be exact bool")
        out[theme_id] = dict(row)
    return out


def _validate_theme_result(provisional_theme_result):
    _require_exact_dict(provisional_theme_result, name="provisional_theme_result")
    if _dict_key_set(provisional_theme_result, name="provisional_theme_result") != set(THEME_RESULT_KEYS):
        raise ThemeSeamError("provisional_theme_result keys drifted from the Cut 6-b contract")
    theme_heat = _validate_heat_by_theme(provisional_theme_result["theme_heat"], name="theme_heat")
    insufficient = set(_validate_label_list(provisional_theme_result["insufficient_themes"], name="insufficient_themes"))
    if set(theme_heat) & insufficient:
        raise ThemeSeamError("theme_id cannot be both scored and insufficient")
    _validate_confirm_flags(provisional_theme_result["confirm_flags"], theme_heat.keys())
    metrics = _require_exact_dict(provisional_theme_result["theme_metrics"], name="theme_metrics")
    metrics_by_theme = {}
    for raw_theme_id, row in metrics.items():
        theme_id = _canonical_theme_id(raw_theme_id, where="theme_metrics")
        if theme_id in metrics_by_theme:
            raise ThemeSeamError("duplicate normalized theme_id in theme_metrics")
        _require_exact_dict(row, name="theme_metrics row")
        metrics_by_theme[theme_id] = row
    if set(metrics_by_theme) != set(theme_heat):
        raise ThemeSeamError("theme_metrics keys must exactly equal scored theme_heat keys")
    _exact_positive_int(provisional_theme_result["min_theme_members"], name="min_theme_members")
    return theme_heat, insufficient


def _validate_theme_membership(theme_members_by_id, *, known_theme_ids):
    _require_exact_dict(theme_members_by_id, name="theme_members_by_id")
    ticker_to_theme = {}
    seen_theme_ids = set()
    for raw_theme_id, members in theme_members_by_id.items():
        theme_id = _canonical_theme_id(raw_theme_id, where="theme_members_by_id")
        if theme_id in seen_theme_ids:
            raise ThemeSeamError("duplicate normalized theme_id in theme_members_by_id")
        seen_theme_ids.add(theme_id)
        if theme_id not in known_theme_ids:
            raise ThemeSeamError("unknown theme_id in theme_members_by_id")
        _require_exact_list(members, name="theme_members_by_id row")
        seen_in_theme = set()
        for raw_ticker in members:
            ticker = _canonical_ticker(raw_ticker, where="theme_members_by_id")
            if ticker in seen_in_theme:
                raise ThemeSeamError("duplicate ticker within one theme membership row")
            if ticker in ticker_to_theme:
                raise ThemeSeamError("duplicate theme membership for ticker")
            seen_in_theme.add(ticker)
            ticker_to_theme[ticker] = theme_id
    return ticker_to_theme


def _theme_row_and_base_source(ticker, *, industry_heat, theme_heat, insufficient_themes, ticker_to_theme):
    row = {"theme_is_cross_sector": False}
    theme_id = ticker_to_theme.get(ticker)
    if theme_id in theme_heat:
        row["theme_heat_score"] = theme_heat[theme_id]
        row["theme_is_cross_sector"] = True
        base_source = "theme"
        if ticker in industry_heat:
            row["industry_heat_score"] = industry_heat[ticker]
    elif ticker in industry_heat:
        row["industry_heat_score"] = industry_heat[ticker]
        base_source = "industry"
    elif theme_id in insufficient_themes:
        base_source = "insufficient_theme"
    else:
        base_source = "missing"
    return row, base_source


def project_theme_block(*, industry_result, provisional_theme_result, theme_members_by_id, target_tickers):
    """Project industry/theme producer outputs to per-target 35% theme-block values.

    A scored cross-sector provisional theme is the selected base. If the target's
    theme is only in `insufficient_themes`, the seam does not fabricate a theme
    value; it falls back to GICS industry heat when present. Missing selected base
    values are omitted and surfaced in `neutral_fill_tickers`.

    The percentile reference pool is the full canonical union of producer industry
    heat identities and theme-membership identities. The target set only projects
    those already-computed pool values; it never re-percentiles the block inside
    the target subset.
    """
    targets = _canonical_targets(target_tickers)
    industry_heat = _validate_industry_result(industry_result)
    theme_heat, insufficient_themes = _validate_theme_result(provisional_theme_result)
    known_theme_ids = set(theme_heat) | set(insufficient_themes)
    ticker_to_theme = _validate_theme_membership(theme_members_by_id, known_theme_ids=known_theme_ids)

    pool_tickers = sorted(set(industry_heat) | set(ticker_to_theme))
    rows = []
    base_source_by_ticker = {}
    for ticker in pool_tickers:
        row, base_source = _theme_row_and_base_source(
            ticker,
            industry_heat=industry_heat,
            theme_heat=theme_heat,
            insufficient_themes=insufficient_themes,
            ticker_to_theme=ticker_to_theme,
        )
        rows.append(row)
        base_source_by_ticker[ticker] = base_source

    block_values = assemble_theme_block(rows)
    pool_block_by_ticker = {}
    for ticker, block_value in zip(pool_tickers, block_values):
        if block_value is not None:
            pool_block_by_ticker[ticker] = float(block_value)

    theme_block_by_ticker = {}
    neutral_fill = []
    coverage = {}
    for ticker in targets:
        base_source = base_source_by_ticker.get(ticker, "missing")
        if ticker in pool_block_by_ticker:
            theme_block_by_ticker[ticker] = pool_block_by_ticker[ticker]
            if base_source_by_ticker[ticker] == "theme":
                coverage[ticker] = DISPOSITION_SCORED_THEME_BASE
            else:
                coverage[ticker] = DISPOSITION_SCORED_INDUSTRY_BASE
        else:
            neutral_fill.append(ticker)
            if base_source == "insufficient_theme":
                coverage[ticker] = DISPOSITION_NEUTRAL_INSUFFICIENT_THEME_NO_INDUSTRY
            else:
                coverage[ticker] = DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE
    return {
        "theme_block_by_ticker": theme_block_by_ticker,
        "neutral_fill_tickers": neutral_fill,
        "coverage": coverage,
        "target_count": len(targets),
        "scored_count": len(theme_block_by_ticker),
    }
