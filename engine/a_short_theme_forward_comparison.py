"""Live-only descriptive comparison for A-short industry/theme annotations.

This is deliberately an evaluator, not a promotion engine.  It reads the
forward tracker after its normal return backfill and produces grouped evidence
for a manual 12-week review.  Historical replay and any ambiguous cohort are
rejected or excluded rather than made to look like forward evidence.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any

import pandas as pd


WINDOWS = (5, 10, 20)
REQUIRED_COLUMNS = {
    "as_of", "run_id", "candidate_digest", "ts_code",
    "industry_heat_score", "industry_trend", "industry_trend_source_as_of",
    "industry_trend_classifier_version", "industry_trend_source_id",
    "industry_trend_headwind_max", "industry_trend_tailwind_min",
    "industry_trend_configuration_fingerprint", "industry_trend_validation_status",
    "raw_concept_ids", "canonical_themes_json", "canonical_theme_ids", "canonical_theme_roles",
    "canonical_theme_role_confidence", "theme_heat_score", "theme_breadth_pass",
    "theme_persistence_mult", "theme_fit_score", "theme_fit_pass",
    "theme_taxonomy_configuration_fingerprint", "theme_taxonomy_source_as_of",
    "theme_taxonomy_l3_provider", "theme_taxonomy_l3_snapshot_date",
    "theme_taxonomy_l3_coverage_digest", "theme_taxonomy_l3_coverage_complete",
    "theme_taxonomy_l3_scoring_universe", "theme_taxonomy_l3_validation_status",
    "forward_live", "historical_replay",
}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _as_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _validate_industry_trend_row(row: pd.Series, as_of: str) -> None:
    if _as_text(row.get("industry_trend_validation_status")) != "valid":
        raise ValueError(f"forward-live cohort {as_of} has unavailable industry_trend evidence")
    if _as_text(row.get("industry_trend_source_as_of")) != as_of:
        raise ValueError(f"forward-live cohort {as_of} has industry_trend source-clock mismatch")
    for column in ("industry_trend_classifier_version", "industry_trend_source_id",
                   "industry_trend_configuration_fingerprint"):
        if not _as_text(row.get(column)):
            raise ValueError(f"forward-live cohort {as_of} has missing {column}")
    score = _finite(row.get("industry_heat_score"))
    headwind_max = _finite(row.get("industry_trend_headwind_max"))
    tailwind_min = _finite(row.get("industry_trend_tailwind_min"))
    if (score is None or headwind_max is None or tailwind_min is None
            or not (0.0 <= score <= 100.0 and 0.0 <= headwind_max < tailwind_min <= 100.0)):
        raise ValueError(f"forward-live cohort {as_of} has invalid industry_trend value lineage")
    expected = "headwind" if score <= headwind_max else ("tailwind" if score >= tailwind_min else "neutral")
    if _as_text(row.get("industry_trend")) != expected:
        raise ValueError(f"forward-live cohort {as_of} has industry_trend classification mismatch")


def _validate_theme_l3_row(row: pd.Series, as_of: str) -> None:
    if _as_text(row.get("theme_taxonomy_l3_provider")) != "hithink_finance":
        raise ValueError(f"forward-live cohort {as_of} lacks a HiThink taxonomy provider receipt")
    if not _as_bool(row.get("theme_taxonomy_l3_coverage_complete")):
        raise ValueError(f"forward-live cohort {as_of} has incomplete taxonomy L3 coverage")
    if _as_text(row.get("theme_taxonomy_l3_scoring_universe")) != "a_share_main_board":
        raise ValueError(f"forward-live cohort {as_of} has taxonomy L3 scope mismatch")
    if _as_text(row.get("theme_taxonomy_l3_validation_status")) != "verified_complete":
        raise ValueError(f"forward-live cohort {as_of} has unverified taxonomy L3 provenance")
    digest = _as_text(row.get("theme_taxonomy_l3_coverage_digest"))
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"forward-live cohort {as_of} has invalid taxonomy L3 coverage digest")
    snapshot_date = _as_text(row.get("theme_taxonomy_l3_snapshot_date"))
    if len(snapshot_date) != 8 or not snapshot_date.isascii() or not snapshot_date.isdigit() or snapshot_date > as_of:
        raise ValueError(f"forward-live cohort {as_of} has invalid taxonomy L3 snapshot date")


def _parse_json(value: Any, expected: type, fallback: Any) -> Any:
    if isinstance(value, expected):
        return value
    text = _as_text(value)
    if not text:
        return fallback
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, expected) else fallback


def validate_tracker_lineage(tracker: pd.DataFrame) -> pd.DataFrame:
    """Validate identity/config cohesion and return eligible live rows only."""
    missing = sorted(REQUIRED_COLUMNS - set(tracker.columns))
    if missing:
        raise ValueError(f"forward tracker missing required columns: {missing}")
    df = tracker.copy()
    df["as_of"] = df["as_of"].map(_as_text)
    df["ts_code"] = df["ts_code"].map(_as_text)
    if (df["as_of"] == "").any() or (df["ts_code"] == "").any():
        raise ValueError("forward tracker has a blank as_of or ts_code")
    if df.duplicated(["as_of", "ts_code"]).any():
        raise ValueError("forward tracker has duplicate (as_of, ts_code) rows")

    live_mask = df["forward_live"].map(_as_bool)
    replay_mask = df["historical_replay"].map(_as_bool)
    if (live_mask & replay_mask).any():
        raise ValueError("a tracker row cannot be both forward_live and historical_replay")
    live = df[live_mask & ~replay_mask].copy()
    if live.empty:
        return live

    eligible = live[live["industry_trend_validation_status"].map(_as_text) == "valid"].copy()
    for as_of, cohort in live.groupby("as_of", dropna=False):
        identities = {( _as_text(row.run_id), _as_text(row.candidate_digest))
                      for row in cohort[["run_id", "candidate_digest"]].itertuples(index=False)}
        if len(identities) != 1 or not next(iter(identities))[0] or not next(iter(identities))[1]:
            raise ValueError(f"forward-live cohort {as_of} has ambiguous/missing run identity")
    # A valid forward-live cohort may contain no source-bound usable industry
    # signal yet.  That is insufficient comparison evidence, not an incoherent
    # configuration cohort; return it empty so the packet reports that state.
    if eligible.empty:
        return eligible
    for as_of, cohort in eligible.groupby("as_of", dropna=False):
        for column in (
            "industry_trend_configuration_fingerprint",
            "theme_taxonomy_configuration_fingerprint",
            "theme_taxonomy_source_as_of",
            "theme_taxonomy_l3_provider",
            "theme_taxonomy_l3_snapshot_date",
            "theme_taxonomy_l3_coverage_digest",
            "theme_taxonomy_l3_coverage_complete",
            "theme_taxonomy_l3_scoring_universe",
            "theme_taxonomy_l3_validation_status",
        ):
            values = {_as_text(v) for v in cohort[column]}
            if len(values) != 1 or not next(iter(values)):
                raise ValueError(f"forward-live cohort {as_of} has ambiguous/missing {column}")
        if _as_text(cohort.iloc[0]["theme_taxonomy_source_as_of"]) != _as_text(as_of):
            raise ValueError(f"forward-live cohort {as_of} has theme taxonomy source-clock mismatch")
        for _, row in cohort.iterrows():
            _validate_industry_trend_row(row, _as_text(as_of))
            _validate_theme_l3_row(row, _as_text(as_of))
    for column in (
        "industry_trend_configuration_fingerprint",
        "theme_taxonomy_configuration_fingerprint",
    ):
        values = {_as_text(value) for value in eligible[column]}
        if len(values) != 1:
            raise ValueError(f"forward-live evidence mixes {column}; start a separately reviewed comparison cohort")
    return eligible


def _summary(values: list[float | None]) -> dict[str, Any]:
    series = pd.Series(values, dtype="float64").dropna()
    if series.empty:
        return {"matured_count": 0, "mean": None, "median": None,
                "win_rate": None, "bad_stock_rate": None}
    return {
        "matured_count": int(len(series)),
        "mean": float(series.mean()),
        "median": float(series.median()),
        "win_rate": float((series > 0).mean()),
        "bad_stock_rate": float((series < 0).mean()),
    }


def _horizon_metrics(rows: list[dict[str, Any]], window: int) -> dict[str, Any]:
    status_col = f"ret_{window}d_status"
    net_col = f"ret_{window}d_t1_net"
    csi300_col = f"ret_{window}d_excess_csi300"
    csi1000_col = f"ret_{window}d_excess_csi1000"
    matured = [r for r in rows if _as_text(r.get(status_col)) == "ok"]
    return {
        "matured_count": len(matured),
        "immature_or_unavailable_count": len(rows) - len(matured),
        "coverage_rate": (float(len(matured) / len(rows)) if rows else None),
        "net": _summary([r.get(net_col) for r in matured]),
        "excess_csi300": _summary([r.get(csi300_col) for r in matured]),
        "excess_csi1000": _summary([r.get(csi1000_col) for r in matured]),
    }


def _group_rows(live: pd.DataFrame) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in live.to_dict(orient="records"):
        trend = _as_text(row.get("industry_trend")) or "unknown"
        grouped[("industry_trend", trend)].append(row)

        themes = _parse_json(row.get("canonical_theme_ids"), list, [])
        roles = _parse_json(row.get("canonical_theme_roles"), dict, {})
        theme_ids = [str(theme_id) for theme_id in themes if str(theme_id).strip()]
        if not theme_ids:
            grouped[("canonical_theme", "unknown_or_unclassified")].append(row)
            grouped[("business_role", "unknown")].append(row)
            continue
        for theme_id in sorted(set(theme_ids)):
            grouped[("canonical_theme", theme_id)].append(row)
            grouped[("business_role", _as_text(roles.get(theme_id)) or "unknown")].append(row)
    return grouped


def evaluate_theme_forward_comparison(tracker: pd.DataFrame) -> dict[str, Any]:
    """Return comparison-only evidence, never a trade or promotion decision."""
    live = validate_tracker_lineage(tracker)
    all_rows = int(len(tracker))
    forward_live_mask = tracker["forward_live"].map(_as_bool) & ~tracker["historical_replay"].map(_as_bool)
    forward_live_rows = int(forward_live_mask.sum())
    live_rows = int(len(live))
    all_as_of = sorted({_as_text(v) for v in live.get("as_of", pd.Series(dtype=str)) if _as_text(v)})
    review_due = len(all_as_of) >= 12
    groups = []
    for (dimension, key), rows in sorted(_group_rows(live).items()):
        groups.append({
            "dimension": dimension,
            "key": key,
            "forward_live_weeks": len({_as_text(r.get("as_of")) for r in rows}),
            "stock_sample_count": len(rows),
            "horizons": {f"{window}d": _horizon_metrics(rows, window) for window in WINDOWS},
        })
    cohorts = []
    for as_of, cohort in live.groupby("as_of", dropna=False):
        first = cohort.iloc[0]
        cohorts.append({
            "as_of": _as_text(as_of),
            "run_id": _as_text(first.get("run_id")),
            "candidate_digest": _as_text(first.get("candidate_digest")),
            "industry_trend_configuration_fingerprint": _as_text(first.get("industry_trend_configuration_fingerprint")),
            "theme_taxonomy_configuration_fingerprint": _as_text(first.get("theme_taxonomy_configuration_fingerprint")),
            "theme_taxonomy_source_as_of": _as_text(first.get("theme_taxonomy_source_as_of")),
            "theme_taxonomy_l3_provider": _as_text(first.get("theme_taxonomy_l3_provider")),
            "theme_taxonomy_l3_snapshot_date": _as_text(first.get("theme_taxonomy_l3_snapshot_date")),
            "theme_taxonomy_l3_coverage_digest": _as_text(first.get("theme_taxonomy_l3_coverage_digest")),
            "candidate_count": int(len(cohort)),
        })
    return {
        "schema_name": "a_short_theme_forward_comparison",
        "schema_version": "1.0.0",
        "comparison_boundary": {
            "forward_live_only": True,
            "historical_replay_counting": False,
            "minimum_forward_live_weeks_for_manual_review": 12,
            "automatic_promotion": False,
            "changes_official_star_risk_action_or_cash": False,
        },
        "tracker_rows_total": all_rows,
        "forward_live_rows_counted": live_rows,
        "excluded_non_live_or_replay_rows": all_rows - forward_live_rows,
        "excluded_unavailable_industry_rows": forward_live_rows - live_rows,
        "forward_live_weeks": len(all_as_of),
        "review_status": ("review_due" if review_due else
                          ("accumulating" if live_rows else "insufficient_data")),
        "manual_review_required": review_due,
        "cohorts": cohorts,
        "groups": groups,
    }
