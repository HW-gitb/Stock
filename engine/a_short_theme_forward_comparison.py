"""Audit-only field-policy evidence for the A-short theme comparison track.

The module compares seven frozen field policies with the same-week official
``analysis_role=final`` selection.  It is deliberately unable to authorize a
production change.  Its explicit start/reset operation owns epoch freezing,
contract drift stopping, and countable-clock transitions for this track.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import math
import numbers
import re
import textwrap
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import NormalDist
from typing import Any, Callable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE_PATH = ROOT / "presets" / "a_short_theme_forward_comparison_governance_20260725.json"
GOVERNANCE_SCHEMA_PATH = ROOT / "schemas" / "a_short_theme_forward_comparison_governance.schema.json"
EPOCH_PATH = ROOT / "docs" / "a_short_theme_forward_comparison_epoch_20260725.json"
EPOCH_SCHEMA_PATH = ROOT / "schemas" / "a_short_theme_forward_comparison_epoch.schema.json"
RUNNER_PATH = ROOT / "runners" / "a_short_theme_forward_comparison.py"
BACKTEST_RANK_PATH = ROOT / "runners" / "backtest_rank.py"
FORWARD_TRACKER_PATH = ROOT / "runners" / "forward_tracker.py"
TAXONOMY_PATH = ROOT / "presets" / "a_short_theme_taxonomy.json"
TAXONOMY_SCHEMA_PATH = ROOT / "schemas" / "a_short_theme_taxonomy.schema.json"
TRACK_ID = "theme_forward_comparison"
PRIVATE_RECEIPT_SCHEMA = "a_short_theme_forward_comparison_private_receipt"
ADMISSION_TIME_PROVENANCE = "local_private_receipt_not_independently_timestamped"
CONTRACT_FUNCTION_SEMANTICS_EXCLUSIONS = frozenset({
    "_semantic_function_digest", "_strip_docstrings", "_contract_function_semantics",
})
CRITERION_IDS = (
    "industry_trend", "business_role", "industry_heat", "persistence",
    "theme_breadth_pass", "theme_fit_pass", "theme_heat",
)

RETURN_WINDOW_DAYS = 10
RETURN_UNIT = "percentage_points"
RETURN_STATUS_COLUMN = f"ret_{RETURN_WINDOW_DAYS}d_status"
RETURN_COLUMN = f"ret_{RETURN_WINDOW_DAYS}d_t1_net"
RETURN_UNIT_COLUMN = f"{RETURN_COLUMN}_unit"
RETURN_EXIT_DATE_COLUMN = f"ret_{RETURN_WINDOW_DAYS}d_exit_date"
DECISION_AS_OF_COLUMN = "decision_as_of"
RUN_DATE_COLUMN = "run_date"
PRICE_DATA_THROUGH_COLUMN = "price_data_through"
CANDIDATE_COUNT_COLUMN = "stage3_candidate_count"
RUNTIME_CONFIGURATION_FINGERPRINT_COLUMN = "runtime_configuration_fingerprint"
MAX_DECISION_LEAD_CALENDAR_DAYS = 14
# A weekly run may be delayed by a weekend or one operational failure, but an
# admission must still be sealed well before any H10 outcome can be known.
ADMISSION_GRACE_CALENDAR_DAYS = 3
TERMINAL_CASH_STATUSES = {"pending_no_entry_limit_up"}
UNOBSERVED_RETURN_STATUSES = {
    "pending_capture", "pending_no_future_price", "pending_no_t_plus_one",
    "pending_immature_asof", "pending_asof_not_in_future_cache",
}
THEME_ROLE_VALUES = {"core", "key_supplier", "adjacent", "weak_link", "unknown"}

REQUIRED_COLUMNS = {
    "as_of", "captured_at", "run_id", "candidate_digest", "ts_code", "final_score",
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
    "chasing_high", "overheat_flag", "forward_live", "historical_replay",
    RETURN_STATUS_COLUMN, RETURN_COLUMN,
}

# These columns were added after the first tracker rows existed.  Their
# absence is an honest exclusion from policy evidence, not a malformed CSV.
LEGACY_OPTIONAL_COLUMNS = (
    "analysis_role", "primary_canonical_theme_id", RETURN_UNIT_COLUMN,
    DECISION_AS_OF_COLUMN, RUN_DATE_COLUMN, PRICE_DATA_THROUGH_COLUMN,
    CANDIDATE_COUNT_COLUMN, RUNTIME_CONFIGURATION_FINGERPRINT_COLUMN,
    "entry_date", RETURN_EXIT_DATE_COLUMN,
)


class ThemeForwardComparisonError(ValueError):
    """Raised for malformed comparison evidence or governance."""


def _today_date():
    return datetime.now().date()


def _as_bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        raise ThemeForwardComparisonError("boolean field is missing")
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        number = float(value)
        if math.isfinite(number) and number in (0.0, 1.0):
            return bool(int(number))
        raise ThemeForwardComparisonError(f"invalid numeric boolean: {value!r}")
    text = str(value).strip().lower()
    if text in {"1", "1.0", "true", "yes"}:
        return True
    if text in {"0", "0.0", "false", "no"}:
        return False
    raise ThemeForwardComparisonError(f"invalid boolean value: {value!r}")


def _as_text(value: Any) -> str:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
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


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_governance(path: Path = GOVERNANCE_PATH) -> dict[str, Any]:
    """Load and schema-validate the sole comparison-policy authority."""
    try:
        import jsonschema
    except ModuleNotFoundError as exc:  # pragma: no cover - project Python pins this dependency
        raise ThemeForwardComparisonError("jsonschema is required for comparison governance") from exc
    try:
        governance = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(GOVERNANCE_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ThemeForwardComparisonError(f"cannot load comparison governance: {exc}") from exc
    try:
        jsonschema.validate(governance, schema)
    except jsonschema.ValidationError as exc:
        raise ThemeForwardComparisonError(f"invalid comparison governance: {exc.message}") from exc
    return governance


def load_taxonomy_registry(path: Path = TAXONOMY_PATH) -> dict[str, Any]:
    """Load the complete schema-validated canonical-theme registry."""
    try:
        import jsonschema
    except ModuleNotFoundError as exc:  # pragma: no cover - project Python pins this dependency
        raise ThemeForwardComparisonError("jsonschema is required for theme taxonomy registry") from exc
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(TAXONOMY_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(registry, schema)
    except (OSError, ValueError, jsonschema.ValidationError) as exc:
        raise ThemeForwardComparisonError(f"cannot load valid theme taxonomy registry: {exc}") from exc
    theme_ids = [_as_text(item.get("theme_id")) for item in registry.get("canonical_themes", [])]
    if not theme_ids or any(not value for value in theme_ids) or len(theme_ids) != len(set(theme_ids)):
        raise ThemeForwardComparisonError("theme taxonomy registry has blank or duplicate canonical theme ids")
    return registry


def load_epoch(path: Path | None = None, *, verify_identity: bool = True) -> dict[str, Any]:
    """Load the active epoch record; it is the only authority for this track's clock."""
    path = path or EPOCH_PATH
    try:
        import jsonschema
    except ModuleNotFoundError as exc:  # pragma: no cover - project Python pins this dependency
        raise ThemeForwardComparisonError("jsonschema is required for comparison epoch") from exc
    try:
        epoch = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(EPOCH_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ThemeForwardComparisonError(f"cannot load comparison epoch: {exc}") from exc
    try:
        jsonschema.validate(epoch, schema)
    except jsonschema.ValidationError as exc:
        raise ThemeForwardComparisonError(f"invalid comparison epoch: {exc.message}") from exc
    if verify_identity and epoch["mode"] == "frozen_enforced" and \
            epoch.get("epoch_identity_fingerprint") != epoch_identity_fingerprint(epoch):
        raise ThemeForwardComparisonError("active comparison epoch identity fingerprint mismatch")
    return epoch


def _yyyymmdd(value: Any, field: str) -> date:
    text = _as_text(value)
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as exc:
        raise ThemeForwardComparisonError(f"invalid {field}: {value!r}") from exc


def _forward_flags(row: pd.Series) -> tuple[bool, bool] | None:
    live_text = _as_text(row.get("forward_live"))
    replay_text = _as_text(row.get("historical_replay"))
    if not live_text and not replay_text:
        return None
    if not live_text or not replay_text:
        raise ThemeForwardComparisonError("forward_live and historical_replay must both be present or both be legacy-blank")
    live, replay = _as_bool(row.get("forward_live")), _as_bool(row.get("historical_replay"))
    if live and replay:
        raise ThemeForwardComparisonError("a tracker row cannot be both forward_live and historical_replay")
    return live, replay


def _validate_industry_trend_row(row: pd.Series, as_of: str, expected_source_as_of: str) -> None:
    if _as_text(row.get("industry_trend_validation_status")) != "valid":
        raise ThemeForwardComparisonError(f"forward-live cohort {as_of} has unavailable industry_trend evidence")
    if _as_text(row.get("industry_trend_source_as_of")).removesuffix(".0") != expected_source_as_of:
        raise ThemeForwardComparisonError(f"forward-live cohort {as_of} has industry_trend source-clock mismatch")
    for column in ("industry_trend_classifier_version", "industry_trend_source_id",
                   "industry_trend_configuration_fingerprint"):
        if not _as_text(row.get(column)):
            raise ThemeForwardComparisonError(f"forward-live cohort {as_of} has missing {column}")
    score = _finite(row.get("industry_heat_score"))
    headwind_max = _finite(row.get("industry_trend_headwind_max"))
    tailwind_min = _finite(row.get("industry_trend_tailwind_min"))
    if (score is None or headwind_max is None or tailwind_min is None
            or not (0.0 <= score <= 100.0 and 0.0 <= headwind_max < tailwind_min <= 100.0)):
        raise ThemeForwardComparisonError(f"forward-live cohort {as_of} has invalid industry_trend value lineage")
    expected = "headwind" if score <= headwind_max else ("tailwind" if score >= tailwind_min else "neutral")
    if _as_text(row.get("industry_trend")) != expected:
        raise ThemeForwardComparisonError(f"forward-live cohort {as_of} has industry_trend classification mismatch")


def _validate_theme_l3_row(row: pd.Series, as_of: str, price_data_through: str) -> None:
    if _as_text(row.get("theme_taxonomy_l3_provider")) != "hithink_finance":
        raise ThemeForwardComparisonError(f"forward-live cohort {as_of} lacks a HiThink taxonomy provider receipt")
    if not _as_bool(row.get("theme_taxonomy_l3_coverage_complete")):
        raise ThemeForwardComparisonError(f"forward-live cohort {as_of} has incomplete taxonomy L3 coverage")
    if _as_text(row.get("theme_taxonomy_l3_scoring_universe")) != "a_share_main_board":
        raise ThemeForwardComparisonError(f"forward-live cohort {as_of} has taxonomy L3 scope mismatch")
    if _as_text(row.get("theme_taxonomy_l3_validation_status")) != "verified_complete":
        raise ThemeForwardComparisonError(f"forward-live cohort {as_of} has unverified taxonomy L3 provenance")
    digest = _as_text(row.get("theme_taxonomy_l3_coverage_digest"))
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ThemeForwardComparisonError(f"forward-live cohort {as_of} has invalid taxonomy L3 coverage digest")
    snapshot_date = _as_text(row.get("theme_taxonomy_l3_snapshot_date")).removesuffix(".0")
    if len(snapshot_date) != 8 or not snapshot_date.isascii() or not snapshot_date.isdigit() or snapshot_date > price_data_through:
        raise ThemeForwardComparisonError(f"forward-live cohort {as_of} has invalid taxonomy L3 snapshot date")


def validate_tracker_lineage(tracker: pd.DataFrame) -> pd.DataFrame:
    """Return non-replay forward rows without silently shrinking a cohort.

    Legacy rows whose two forward-boundary flags are both blank remain
    diagnostic-only.  Every newer live row is retained here; all-or-nothing
    formal cohort eligibility is decided by ``eligible_formal_cohorts``.
    """
    missing = sorted(REQUIRED_COLUMNS - set(tracker.columns))
    if missing:
        raise ThemeForwardComparisonError(f"forward tracker missing required columns: {missing}")
    df = tracker.copy()
    for column in LEGACY_OPTIONAL_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    df["as_of"] = df["as_of"].map(_as_text)
    df["ts_code"] = df["ts_code"].map(_as_text)
    if (df["as_of"] == "").any() or (df["ts_code"] == "").any():
        raise ThemeForwardComparisonError("forward tracker has a blank as_of or ts_code")
    if df.duplicated(["as_of", "ts_code"]).any():
        raise ThemeForwardComparisonError("forward tracker has duplicate (as_of, ts_code) rows")

    live_indexes: list[Any] = []
    for index, row in df.iterrows():
        flags = _forward_flags(row)
        if flags is not None and flags == (True, False):
            live_indexes.append(index)
    live = df.loc[live_indexes].copy()
    if live.empty:
        return live
    for _, row in live.iterrows():
        clocks = [_as_text(row.get(column)).removesuffix(".0") for column in (
            DECISION_AS_OF_COLUMN, RUN_DATE_COLUMN, PRICE_DATA_THROUGH_COLUMN
        )]
        if any(clocks) and not all(clocks):
            raise ThemeForwardComparisonError("forward-live row has a partially populated decision clock")
        if all(clocks):
            decision_date = _yyyymmdd(clocks[0], DECISION_AS_OF_COLUMN)
            run_date = _yyyymmdd(clocks[1], RUN_DATE_COLUMN)
            price_date = _yyyymmdd(clocks[2], PRICE_DATA_THROUGH_COLUMN)
            try:
                captured_date = datetime.fromisoformat(_as_text(row.get("captured_at"))).date()
            except ValueError as exc:
                raise ThemeForwardComparisonError("forward-live row has invalid captured_at") from exc
            if decision_date != _yyyymmdd(row.get("as_of"), "as_of") or \
                    not price_date <= run_date <= decision_date or captured_date != run_date:
                raise ThemeForwardComparisonError("forward-live row has invalid decision/run/price/capture clock order")
            if run_date > _today_date() or decision_date > _today_date() + timedelta(
                    days=MAX_DECISION_LEAD_CALENDAR_DAYS
            ):
                raise ThemeForwardComparisonError("forward-live decision clock is unreasonably in the future")
        unit = _as_text(row.get(RETURN_UNIT_COLUMN))
        if unit and unit != RETURN_UNIT:
            raise ThemeForwardComparisonError("forward tracker has a return-unit mismatch")

    for as_of, cohort in live.groupby("as_of", dropna=False):
        identities = {(_as_text(row.run_id), _as_text(row.candidate_digest))
                      for row in cohort[["run_id", "candidate_digest"]].itertuples(index=False)}
        if len(identities) != 1 or not next(iter(identities))[0] or not next(iter(identities))[1]:
            raise ThemeForwardComparisonError(f"forward-live cohort {as_of} has ambiguous/missing run identity")
    return live


def _cohort_formal_error(
    cohort: pd.DataFrame, top_n: int, *, require_decision_effective: bool = True
) -> str | None:
    """Return why the complete source cohort is ineligible, or ``None``."""
    if cohort.empty:
        return "empty_cohort"
    as_of = _as_text(cohort.iloc[0]["as_of"]).removesuffix(".0")
    required_text = (
        DECISION_AS_OF_COLUMN, RUN_DATE_COLUMN, PRICE_DATA_THROUGH_COLUMN,
        CANDIDATE_COUNT_COLUMN, RUNTIME_CONFIGURATION_FINGERPRINT_COLUMN,
        RETURN_UNIT_COLUMN,
    )
    for column in required_text:
        values = {_as_text(value).removesuffix(".0") for value in cohort[column]}
        if len(values) != 1 or not next(iter(values)):
            return f"ambiguous_or_missing_{column}"
    captured_values = {_as_text(value) for value in cohort["captured_at"]}
    if len(captured_values) != 1 or not next(iter(captured_values)):
        return "ambiguous_or_missing_captured_at"
    try:
        decision_date = _yyyymmdd(cohort.iloc[0][DECISION_AS_OF_COLUMN], DECISION_AS_OF_COLUMN)
        run_date = _yyyymmdd(cohort.iloc[0][RUN_DATE_COLUMN], RUN_DATE_COLUMN)
        price_date = _yyyymmdd(cohort.iloc[0][PRICE_DATA_THROUGH_COLUMN], PRICE_DATA_THROUGH_COLUMN)
        captured_date = datetime.fromisoformat(_as_text(cohort.iloc[0]["captured_at"])).date()
    except (ThemeForwardComparisonError, ValueError):
        return "invalid_clock_lineage"
    if decision_date != _yyyymmdd(as_of, "as_of") or not price_date <= run_date <= decision_date:
        return "clock_order_mismatch"
    if captured_date != run_date or run_date > _today_date():
        return "capture_run_clock_mismatch"
    if decision_date > _today_date() + timedelta(days=MAX_DECISION_LEAD_CALENDAR_DAYS):
        return "decision_clock_too_far_ahead"
    if require_decision_effective and decision_date > _today_date():
        return "decision_not_effective_yet"
    expected_count = _finite(cohort.iloc[0][CANDIDATE_COUNT_COLUMN])
    if expected_count is None or int(expected_count) != expected_count or int(expected_count) != len(cohort):
        return "stage3_candidate_count_mismatch"
    roles = cohort["analysis_role"].map(_as_text)
    if not roles.isin({"final", "watch"}).all() or int((roles == "final").sum()) != top_n:
        return "analysis_role_or_primary_top5_incomplete"
    if (cohort[RETURN_UNIT_COLUMN].map(_as_text) != RETURN_UNIT).any():
        return "return_unit_mismatch"
    all_scores = [_finite(value) for value in cohort["final_score"]]
    if any(value is None for value in all_scores):
        return "nonfinite_stage3_final_score"
    # One conversion serves both row loops below.  ``iterrows`` builds a Series
    # per row and pays a pandas indexing call per field read; this function runs
    # once per cohort per admission/outcome receipt, which by profile made it a
    # top sink of the whole theme suite.  Row consumers only use ``.get``, which
    # behaves identically on these dict rows.
    cohort_rows = cohort.to_dict(orient="records")
    for row in cohort_rows:
        theme_error = _theme_row_error(row)
        if theme_error:
            return theme_error
        industry_heat = _finite(row.get("industry_heat_score"))
        theme_heat = _finite(row.get("theme_heat_score"))
        persistence = _finite(row.get("theme_persistence_mult"))
        if industry_heat is None or not 0.0 <= industry_heat <= 100.0:
            return "invalid_industry_heat_score"
        if theme_heat is None or not 0.0 <= theme_heat <= 100.0:
            return "invalid_theme_heat_score"
        if persistence is None or persistence < 0.0:
            return "invalid_theme_persistence_mult"
        try:
            for field in (
                "theme_fit_pass", "theme_breadth_pass", "chasing_high", "overheat_flag",
            ):
                _as_bool(row.get(field))
        except ThemeForwardComparisonError:
            return "invalid_boolean_policy_input"
    common_columns = (
        "industry_trend_configuration_fingerprint", "theme_taxonomy_configuration_fingerprint",
        "theme_taxonomy_source_as_of", "theme_taxonomy_l3_provider",
        "theme_taxonomy_l3_snapshot_date", "theme_taxonomy_l3_coverage_digest",
        "theme_taxonomy_l3_coverage_complete", "theme_taxonomy_l3_scoring_universe",
        "theme_taxonomy_l3_validation_status",
    )
    for column in common_columns:
        values = {_as_text(value).removesuffix(".0") for value in cohort[column]}
        if len(values) != 1 or not next(iter(values)):
            return f"ambiguous_or_missing_{column}"
    if _as_text(cohort.iloc[0]["theme_taxonomy_source_as_of"]).removesuffix(".0") != as_of:
        return "theme_taxonomy_source_clock_mismatch"
    try:
        for row in cohort_rows:
            _validate_industry_trend_row(row, as_of, price_date.strftime("%Y%m%d"))
            _validate_theme_l3_row(row, as_of, price_date.strftime("%Y%m%d"))
    except ThemeForwardComparisonError as exc:
        return str(exc)
    return None


def eligible_formal_cohorts(
    live: pd.DataFrame, top_n: int, *, require_decision_effective: bool = True
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Admit complete Stage3 cohorts atomically; never drop individual rows."""
    eligible: list[pd.DataFrame] = []
    rejected: dict[str, str] = {}
    for as_of, cohort in live.groupby("as_of", dropna=False):
        reason = _cohort_formal_error(
            cohort, top_n, require_decision_effective=require_decision_effective
        )
        if reason is None:
            eligible.append(cohort)
        else:
            rejected[_as_text(as_of)] = reason
    return (pd.concat(eligible, ignore_index=True) if eligible else live.iloc[0:0].copy()), rejected


def _theme_references_within_epoch(live: pd.DataFrame, frozen_theme_ids: list[str]) -> bool:
    frozen = set(frozen_theme_ids)
    for row in live.to_dict(orient="records"):
        if _theme_row_error(row):
            return False
        canonical_ids = {
            _as_text(value) for value in _parse_json(row.get("canonical_theme_ids"), list, [])
            if _as_text(value)
        }
        canonical_json_ids = {
            _as_text(item.get("theme_id"))
            for item in _parse_json(row.get("canonical_themes_json"), list, [])
            if isinstance(item, dict) and _as_text(item.get("theme_id"))
        }
        role_ids = {
            _as_text(value)
            for value in _parse_json(row.get("canonical_theme_roles"), dict, {}).keys()
            if _as_text(value)
        }
        primary = _as_text(row.get("primary_canonical_theme_id"))
        if not (canonical_ids | canonical_json_ids | role_ids).issubset(frozen):
            return False
        if primary and (primary not in frozen or primary not in canonical_ids):
            return False
    return True


def _theme_row_error(row: dict[str, Any] | pd.Series) -> str | None:
    def parsed(value: Any, expected: type):
        if isinstance(value, expected):
            return value
        text = _as_text(value)
        if not text:
            raise ValueError
        value = json.loads(text)
        if not isinstance(value, expected):
            raise ValueError
        return value

    try:
        ids = parsed(row.get("canonical_theme_ids"), list)
        themes = parsed(row.get("canonical_themes_json"), list)
        roles = parsed(row.get("canonical_theme_roles"), dict)
    except (TypeError, ValueError, json.JSONDecodeError):
        return "malformed_theme_structure"
    if any(not isinstance(value, str) or not value.strip() for value in ids) or \
            len(ids) != len(set(ids)):
        return "invalid_or_duplicate_canonical_theme_ids"
    theme_map: dict[str, str] = {}
    for item in themes:
        if not isinstance(item, dict):
            return "malformed_canonical_themes_json"
        theme_id = item.get("theme_id")
        role = item.get("role")
        if not isinstance(theme_id, str) or not theme_id.strip() or \
                not isinstance(role, str) or role not in THEME_ROLE_VALUES or \
                theme_id in theme_map:
            return "invalid_canonical_theme_item"
        theme_map[theme_id] = role
    if any(not isinstance(key, str) or not key.strip() or
           not isinstance(value, str) or value not in THEME_ROLE_VALUES
           for key, value in roles.items()):
        return "invalid_canonical_theme_roles"
    if set(ids) != set(theme_map) or set(ids) != set(roles) or any(
            roles[theme_id] != theme_map[theme_id] for theme_id in ids):
        return "inconsistent_theme_identity_or_role"
    primary = _as_text(row.get("primary_canonical_theme_id"))
    if primary and primary not in set(ids):
        return "primary_theme_not_in_canonical_set"
    return None


def _criterion_predicate(spec: dict[str, Any]) -> Callable[[dict[str, Any]], bool]:
    field = spec["field"]
    operator = spec["operator"]
    value = spec.get("value")
    if operator == "equals":
        return lambda row: _as_text(row.get(field)) == str(value)
    if operator == "boolean_true":
        return lambda row: _as_bool(row.get(field))
    if operator == "gte":
        return lambda row: (_finite(row.get(field)) is not None and _finite(row.get(field)) >= float(value))
    if operator == "primary_theme_role_equals":
        def matches(row: dict[str, Any]) -> bool:
            primary = _as_text(row.get("primary_canonical_theme_id"))
            roles = _parse_json(row.get("canonical_theme_roles"), dict, {})
            return bool(primary) and _as_text(roles.get(primary)) == str(value)
        return matches
    if operator == "any_boolean_true":
        fields = tuple(spec["fields"])
        return lambda row: any(_as_bool(row.get(name)) for name in fields)
    raise ThemeForwardComparisonError(f"unsupported criterion operator: {operator}")


def _criterion_negative_predicate(spec: dict[str, Any]) -> Callable[[dict[str, Any]], bool]:
    field = spec["field"]
    operator = spec["operator"]
    value = spec.get("value")
    if operator == "equals":
        return lambda row: _as_text(row.get(field)) == str(spec["negative_value"])
    if operator == "boolean_true":
        return lambda row: not _as_bool(row.get(field))
    if operator == "gte":
        return lambda row: (_finite(row.get(field)) is not None and _finite(row.get(field)) < float(value))
    if operator == "primary_theme_role_equals":
        def not_core(row: dict[str, Any]) -> bool:
            primary = _as_text(row.get("primary_canonical_theme_id"))
            roles = _parse_json(row.get("canonical_theme_roles"), dict, {})
            role = _as_text(roles.get(primary)) if primary else ""
            return role in set(spec["negative_values"])
        return not_core
    if operator == "any_boolean_true":
        fields = tuple(spec["fields"])
        return lambda row: not any(_as_bool(row.get(name)) for name in fields)
    raise ThemeForwardComparisonError(f"unsupported negative criterion operator: {operator}")


def _score_sorted(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        score = _finite(row.get("final_score"))
        if score is not None:
            scored.append((score, _as_text(row.get("ts_code")), row))
    return [row for _, _, row in sorted(scored, key=lambda item: (-item[0], item[1]))]


def _selection_return(rows: list[dict[str, Any]], top_n: int, *, require_full_selection: bool = False) -> tuple[float | None, str]:
    """Return fixed-slot policy return; empty slots and known no-entry are cash."""
    if require_full_selection and len(rows) != top_n:
        return None, f"primary_baseline_unavailable:{len(rows)}/{top_n}"
    total = 0.0
    for row in rows[:top_n]:
        status = _as_text(row.get(RETURN_STATUS_COLUMN))
        if status == "ok":
            value = _finite(row.get(RETURN_COLUMN))
            if value is None:
                return None, "invalid_ok_return"
            total += value
        elif status in TERMINAL_CASH_STATUSES:
            continue
        else:
            return None, f"unmatured_or_unavailable:{status or 'blank'}"
    return total / float(top_n), "ok"


def _realized_positions(rows: list[dict[str, Any]], top_n: int) -> int:
    """Count actually entered positions; terminal no-entry slots remain cash."""
    return sum(
        _as_text(row.get(RETURN_STATUS_COLUMN)) == "ok"
        for row in rows[:top_n]
    )


def _complete_cohort_interval(rows: list[dict[str, Any]]) -> list[str] | None:
    """Return one common realized interval only when every cohort row carries it."""
    if not rows:
        return None
    entry_values = [_as_text(row.get("entry_date")).removesuffix(".0") for row in rows]
    exit_values = [_as_text(row.get(RETURN_EXIT_DATE_COLUMN)).removesuffix(".0") for row in rows]
    if any(not value for value in entry_values + exit_values):
        return None
    entry_dates = set(entry_values)
    exit_dates = set(exit_values)
    if len(entry_dates) != 1 or len(exit_dates) != 1:
        return None
    entry_date, exit_date = next(iter(entry_dates)), next(iter(exit_dates))
    try:
        if _yyyymmdd(entry_date, "entry_date") > _yyyymmdd(exit_date, RETURN_EXIT_DATE_COLUMN):
            return None
    except ThemeForwardComparisonError:
        return None
    return [entry_date, exit_date]


def _policy_week(rows: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool], top_n: int,
                 challenger_eligibility: Callable[[dict[str, Any]], bool] | None = None) -> dict[str, Any]:
    primary = _score_sorted([row for row in rows if _as_text(row.get("analysis_role")) == "final"])[:top_n]
    eligibility = challenger_eligibility or (lambda row: True)
    challenger = _score_sorted([row for row in rows if eligibility(row) and predicate(row)])[:top_n]
    primary_return, primary_status = _selection_return(primary, top_n, require_full_selection=True)
    challenger_return, challenger_status = _selection_return(challenger, top_n)
    primary_executed = _realized_positions(primary, top_n)
    challenger_executed = _realized_positions(challenger, top_n)
    interval = _complete_cohort_interval(rows)
    return {
        "primary_selected_count": len(primary),
        "challenger_selected_count": len(challenger),
        "primary_executed_positions": primary_executed,
        "challenger_executed_positions": challenger_executed,
        "primary_cash_slots": top_n - primary_executed,
        "challenger_cash_slots": top_n - challenger_executed,
        "primary_cash_slot_rate": (
            None if primary_return is None else float(top_n - primary_executed) / float(top_n)
        ),
        "challenger_cash_slot_rate": float(top_n - challenger_executed) / float(top_n),
        "primary_return": primary_return,
        "challenger_return": challenger_return,
        "primary_status": primary_status,
        "challenger_status": challenger_status,
        "evidence_interval": interval,
        "delta": (challenger_return - primary_return
                  if challenger_return is not None and primary_return is not None else None),
    }


def _select_nonoverlap_evidence_blocks(
    weekly: list[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Select the one sealed source-week set used by statistics and all gates."""
    candidates: list[dict[str, Any]] = []
    for as_of, data in weekly:
        interval = data.get("evidence_interval")
        delta = data.get("delta")
        if interval is None or delta is None:
            continue
        candidates.append({
            "as_of": _as_text(as_of),
            "entry_date": _as_text(interval[0]),
            "exit_date": _as_text(interval[1]),
            "delta_pp": float(delta),
            "primary_selected_candidates": int(data["primary_selected_count"]),
            "challenger_selected_candidates": int(data["challenger_selected_count"]),
            "primary_executed_positions": int(data["primary_executed_positions"]),
            "primary_cash_slots": int(data["primary_cash_slots"]),
            "challenger_executed_positions": int(data["challenger_executed_positions"]),
            "challenger_cash_slots": int(data["challenger_cash_slots"]),
        })
    selected: list[dict[str, Any]] = []
    last_exit: date | None = None
    for block in sorted(candidates, key=lambda value: (
            value["entry_date"], value["exit_date"], value["as_of"])):
        entry_date = _yyyymmdd(block["entry_date"], "entry_date")
        exit_date = _yyyymmdd(block["exit_date"], RETURN_EXIT_DATE_COLUMN)
        if exit_date < entry_date:
            raise ThemeForwardComparisonError("H10 evidence interval exits before entry")
        if last_exit is not None and entry_date <= last_exit:
            continue
        selected.append(block)
        last_exit = exit_date
    return selected


def _nonoverlap_blocks(values: list[tuple[str, str, float]]) -> list[float]:
    """Compatibility helper for independent scalar-only callers."""
    weekly = [
        (str(index), {
            "evidence_interval": [entry_text, exit_text], "delta": value,
            "primary_selected_count": 0, "challenger_selected_count": 0,
            "primary_executed_positions": 0, "primary_cash_slots": 0,
            "challenger_executed_positions": 0, "challenger_cash_slots": 0,
        })
        for index, (entry_text, exit_text, value) in enumerate(values)
    ]
    return [block["delta_pp"] for block in _select_nonoverlap_evidence_blocks(weekly)]


def _coverage_from_evidence_blocks(blocks: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any]:
    """Coverage is defined only on the same non-overlapping blocks as statistics."""
    challenger = [int(block["challenger_executed_positions"]) for block in blocks]
    primary = [int(block["primary_executed_positions"]) for block in blocks]
    top_n = int(policy["top_n"])
    full = sum(count == top_n for count in challenger)
    min_count = int(policy["minimum_counted_block_executed_positions"])
    deployable = bool(challenger) and min(challenger) >= min_count and \
        float(np.mean(challenger)) >= float(policy["minimum_average_selected_positions"]) and \
        (full / len(challenger)) >= float(policy["minimum_full_slot_week_rate"])
    return {
        "evidence_block_as_ofs": [block["as_of"] for block in blocks],
        "evidence_block_count": len(blocks),
        "counted_block_execution_profile": [{
            "as_of": block["as_of"],
            "entry_date": block["entry_date"],
            "exit_date": block["exit_date"],
            "challenger_selected_candidates": block["challenger_selected_candidates"],
            "challenger_executed_positions": block["challenger_executed_positions"],
            "challenger_cash_slots": block["challenger_cash_slots"],
            "primary_selected_candidates": block["primary_selected_candidates"],
            "primary_executed_positions": block["primary_executed_positions"],
            "primary_cash_slots": block["primary_cash_slots"],
        } for block in blocks],
        "minimum_counted_block_executed_positions": min_count,
        "minimum_observed_counted_block_positions": min(challenger) if challenger else 0,
        "average_selected_positions": float(np.mean(challenger)) if challenger else 0.0,
        "average_cash_slots": float(top_n - np.mean(challenger)) if challenger else float(top_n),
        "cash_slot_rate": float(1.0 - (np.mean(challenger) / float(top_n))) if challenger else 1.0,
        "full_slot_week_rate": float(full / len(challenger)) if challenger else 0.0,
        "primary_average_executed_positions": float(np.mean(primary)) if primary else 0.0,
        "primary_average_cash_slots": float(top_n - np.mean(primary)) if primary else float(top_n),
        "primary_cash_slot_rate": float(1.0 - (np.mean(primary) / float(top_n))) if primary else 1.0,
        "primary_full_slot_week_rate": float(sum(count == top_n for count in primary) / len(primary)) if primary else 0.0,
        "deployable": deployable,
    }


def _bootstrap_summary(values: list[float], policy: dict[str, Any], seed_offset: int) -> dict[str, Any]:
    if not values:
        return {"block_count": 0, "mean_delta_pp": None, "ci_95_pp": None,
                "family_adjusted_ci_pp": None, "raw_two_sided_practical_p": None,
                "minimum_detectable_effect_pp": None}
    samples = int(policy["bootstrap_resamples"])
    rng = np.random.default_rng(int(policy["bootstrap_seed"]) + seed_offset)
    array = np.asarray(values, dtype=float)
    boot = rng.choice(array, size=(samples, len(array)), replace=True).mean(axis=1)
    margin = float(policy["practical_margin_pp"])
    p_superior = (float(np.count_nonzero(boot <= margin)) + 1.0) / (samples + 1.0)
    p_harmful = (float(np.count_nonzero(boot >= -margin)) + 1.0) / (samples + 1.0)
    family_alpha = float(policy["holm_alpha"])
    alpha_per_comparison = family_alpha / float(len(CRITERION_IDS))
    z_alpha = NormalDist().inv_cdf(1.0 - alpha_per_comparison / 2.0)
    z_power = NormalDist().inv_cdf(float(policy["power_target"]))
    standard_error = (float(array.std(ddof=1)) / math.sqrt(len(array))) if len(array) > 1 else None
    return {
        "block_count": int(len(array)),
        "mean_delta_pp": float(array.mean()),
        "ci_95_pp": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
        "family_adjusted_ci_pp": [
            float(np.quantile(boot, alpha_per_comparison / 2.0)),
            float(np.quantile(boot, 1.0 - alpha_per_comparison / 2.0)),
        ],
        "family_adjustment": {
            "method": policy["familywise_interval_method"],
            "family_size": len(CRITERION_IDS),
            "family_alpha": family_alpha,
            "per_comparison_two_sided_alpha": alpha_per_comparison,
            "power_target": float(policy["power_target"]),
        },
        "raw_two_sided_practical_p": min(1.0, 2.0 * min(p_superior, p_harmful)),
        "minimum_detectable_effect_pp": (
            float((z_alpha + z_power) * standard_error) if standard_error is not None else None
        ),
    }


def _holm_adjust(raw_p_values: list[float | None], family_size: int) -> list[float | None]:
    out: list[float | None] = [None] * len(raw_p_values)
    indexed = sorted((value, index) for index, value in enumerate(raw_p_values) if value is not None)
    running = 0.0
    for rank, (value, index) in enumerate(indexed):
        adjusted = min(1.0, float(value) * (family_size - rank))
        running = max(running, adjusted)
        out[index] = running
    return out


def _additional_blocks_needed(stats: dict[str, Any], policy: dict[str, Any]) -> int | None:
    mde = stats["minimum_detectable_effect_pp"]
    if mde is None or mde <= 0:
        return None
    current = stats["block_count"]
    target = float(policy["practical_margin_pp"])
    required = math.ceil(current * (mde / target) ** 2)
    return max(0, required - current)


def _predictive_summary(rows: list[dict[str, Any]], positive: Callable[[dict[str, Any]], bool],
                        negative: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    deltas = []
    positive_n = negative_n = 0
    if not rows:
        return {
            "status": "diagnostic_only_not_in_holm_family",
            "positive_stock_observations": 0,
            "negative_stock_observations": 0,
            "paired_week_count": 0,
            "mean_weekly_difference_pp": None,
        }
    for _, cohort in pd.DataFrame(rows).groupby("as_of", dropna=False):
        pos_values = [_finite(row.get(RETURN_COLUMN)) for row in cohort.to_dict(orient="records")
                      if positive(row) and _as_text(row.get(RETURN_STATUS_COLUMN)) == "ok"]
        neg_values = [_finite(row.get(RETURN_COLUMN)) for row in cohort.to_dict(orient="records")
                      if negative(row) and _as_text(row.get(RETURN_STATUS_COLUMN)) == "ok"]
        pos = [value for value in pos_values if value is not None]
        neg = [value for value in neg_values if value is not None]
        positive_n += len(pos)
        negative_n += len(neg)
        if pos and neg:
            deltas.append(float(np.mean(pos) - np.mean(neg)))
    return {
        "status": "diagnostic_only_not_in_holm_family",
        "positive_stock_observations": positive_n,
        "negative_stock_observations": negative_n,
        "paired_week_count": len(deltas),
        "mean_weekly_difference_pp": float(np.mean(deltas)) if deltas else None,
    }


def _row_theme_ids(row: dict[str, Any]) -> set[str]:
    return {
        _as_text(value)
        for value in _parse_json(row.get("canonical_theme_ids"), list, [])
        if _as_text(value)
    }


def _theme_groups(live: pd.DataFrame, policy: dict[str, Any],
                  frozen_theme_ids: list[str] | None = None) -> list[dict[str, Any]]:
    frozen = set(frozen_theme_ids or [])
    # Converted and parsed once, outside the per-theme loop.  The old form
    # re-ran ``to_dict``/``_parse_json`` for every theme over the same frame --
    # ~1,500 conversions in one 36-week test by profile -- for byte-identical
    # inputs.  Rows are read-only throughout this function.
    live_rows = [(row, _row_theme_ids(row)) for row in live.to_dict(orient="records")]
    observed = {theme_id for _, ids in live_rows for theme_id in ids}
    cohort_data = []
    for _, cohort in live.groupby("as_of", dropna=False):
        cohort_rows = cohort.to_dict(orient="records")
        interval = _complete_cohort_interval(cohort_rows)
        if interval is None:
            continue
        usable = []
        for row in cohort_rows:
            if _as_text(row.get(RETURN_STATUS_COLUMN)) != "ok":
                continue
            value = _finite(row.get(RETURN_COLUMN))
            if value is None:
                continue
            usable.append((value, _row_theme_ids(row)))
        cohort_data.append((interval, usable))
    family = sorted(frozen or observed)
    results = []
    for index, theme_id in enumerate(family):
        rows = [row for row, ids in live_rows if theme_id in ids]
        weeks = len({_as_text(row.get("as_of")) for row in rows})
        paired: list[tuple[str, str, float]] = []
        for interval, usable in cohort_data:
            member = []
            nonmember = []
            for value, ids in usable:
                (member if theme_id in ids else nonmember).append(value)
            if member and nonmember:
                paired.append((interval[0], interval[1], float(np.mean(member) - np.mean(nonmember))))
        # Theme comparisons use their own member/nonmember exploratory sample,
        # never the policy-vs-primary evidence set and never an actionable gate.
        stats = _bootstrap_summary(_nonoverlap_blocks(paired), policy, 1000 + index)
        sample_eligible = (
            weeks >= int(policy["exploratory_theme_min_weeks"])
            and len(rows) >= int(policy["exploratory_theme_min_stock_weeks"])
        )
        ci = stats["ci_95_pp"]
        verdict = "insufficient_sample"
        if sample_eligible and ci is None:
            verdict = "insufficient_contrast"
        elif sample_eligible and ci[0] > 0:
            verdict = "exploratory_positive"
        elif sample_eligible and ci[1] < 0:
            verdict = "exploratory_negative"
        elif sample_eligible:
            verdict = "exploratory_inconclusive"
        results.append({
            "theme_id": theme_id,
            "forward_live_weeks": weeks,
            "stock_week_count": len(rows),
            "sample_eligible": sample_eligible,
            "paired_week_count": len(paired),
            "nonoverlap_h10_block_count": stats["block_count"],
            "mean_member_minus_nonmember_pp": stats["mean_delta_pp"],
            "exploratory_ci_95_pp": ci,
            "exploratory_verdict": verdict,
            "evidence_scope": "exploratory_theme_member_vs_nonmember_only",
            "actionable": False,
            "status": ("exploratory_only_frozen_epoch_family" if frozen
                       else "exploratory_only_epoch_registry_must_be_frozen_before_formal_use"),
        })
    return results


def _policy_result(live: pd.DataFrame, spec: dict[str, Any], policy: dict[str, Any], seed_offset: int) -> dict[str, Any]:
    predicate = _criterion_predicate(spec)
    negative = _criterion_negative_predicate(spec)
    eligibility = (lambda row: bool(_as_text(row.get("primary_canonical_theme_id")))) \
        if spec["criterion_id"] == "business_role" else (lambda row: True)
    weekly: list[tuple[str, dict[str, Any]]] = []
    excluded_missing_primary = 0
    for as_of, cohort in live.groupby("as_of", dropna=False):
        raw_rows = cohort.to_dict(orient="records")
        excluded_missing_primary += sum(not eligibility(row) for row in raw_rows)
        weekly.append((_as_text(as_of), _policy_week(raw_rows, predicate, int(policy["top_n"]), eligibility)))
    evidence_blocks = _select_nonoverlap_evidence_blocks(weekly)
    blocks = [block["delta_pp"] for block in evidence_blocks]
    stats = _bootstrap_summary(blocks, policy, seed_offset)
    selected = [data["challenger_selected_count"] for _, data in weekly]
    coverage = _coverage_from_evidence_blocks(evidence_blocks, policy)
    weekly_selection_summary = {
        "all_eligible_week_average_selected_candidates": float(np.mean(selected)) if selected else 0.0,
        "all_eligible_week_count": len(weekly),
    }
    adjudication = {
        "verdict": "audit_only_pre_freeze",
        "reason": "formal decisions require the separately frozen theme_forward_comparison epoch",
        "holm_adjusted_two_sided_practical_p": None,
        "additional_nonoverlap_blocks_estimate": _additional_blocks_needed(stats, policy),
    }
    return {
        "strategy": spec["strategy"],
        "weekly_cohort_count": len(weekly),
        "matured_paired_week_count": len(evidence_blocks),
        "excluded_missing_primary_canonical_theme_id_rows": excluded_missing_primary,
        "coverage": coverage,
        "weekly_selection_summary": weekly_selection_summary,
        "nonoverlap_h10_blocks": stats,
        "exploratory": {
            "raw_two_sided_practical_p": stats["raw_two_sided_practical_p"],
            "actionable": False,
        },
        "predictive_discrimination": _predictive_summary(live.to_dict(orient="records"), predicate, negative),
        "adjudication": adjudication,
        "policy_vs_primary": {
            "weekly_cohort_count": len(weekly),
            "matured_paired_week_count": len(evidence_blocks),
            "coverage": coverage,
            "weekly_selection_summary": weekly_selection_summary,
            "nonoverlap_h10_blocks": stats,
            "adjudication": adjudication,
        },
    }


def _negative_control(live: pd.DataFrame, policy: dict[str, Any], seed_offset: int) -> dict[str, Any]:
    spec = policy["negative_control"]
    data = _policy_result(live, spec, policy, seed_offset)
    data["method_validity_status"] = (
        "not_assessable_zero_observation"
        if data["predictive_discrimination"]["positive_stock_observations"] == 0
        else "audit_only_pre_freeze"
    )
    data["method_validity_rule"] = (
        "future significant unexpected benefit blocks replacement recommendations; "
        "expected harm supports only a method-consistency check; inconclusive does not invalidate the family"
    )
    return data


def _replacement_evidence_block_reason(status: str) -> str | None:
    """Name the actual negative-control failure mode; never relabel no-data as a warning."""
    if status == "unexpected_benefit_method_validity_warning":
        return "negative_control_method_validity_warning"
    if status == "not_assessable_zero_observation":
        return "negative_control_not_assessable_zero_observation"
    if status == "not_assessable_low_coverage":
        return "negative_control_not_assessable_low_coverage"
    if status.startswith("not_assessable_"):
        return "negative_control_not_assessable"
    return None


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    """Keep prose edits out of a semantic epoch contract."""
    class StripDocstrings(ast.NodeTransformer):
        def _strip(self, node: ast.AST) -> ast.AST:
            self.generic_visit(node)
            body = getattr(node, "body", None)
            if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and \
                    isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                body.pop(0)
            return node

        visit_Module = _strip
        visit_FunctionDef = _strip
        visit_AsyncFunctionDef = _strip
        visit_ClassDef = _strip

    return StripDocstrings().visit(tree)


def _semantic_function_digest(function: Callable[..., Any]) -> str:
    """Digest executable semantics while deliberately ignoring comments/formatting/docs."""
    tree = _strip_docstrings(ast.parse(textwrap.dedent(inspect.getsource(function))))
    return ast.dump(tree, include_attributes=False)


def _semantic_file_contract_digest(path: Path, function_names: set[str],
                                   constant_names: set[str]) -> str:
    """Bind a transitive producer closure and every referenced module constant by default."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    closure = set(function_names)
    pending = list(function_names)
    while pending:
        name = pending.pop()
        node = functions.get(name)
        if node is None:
            continue
        for call in (item for item in ast.walk(node) if isinstance(item, ast.Call)):
            if isinstance(call.func, ast.Name) and call.func.id in functions and call.func.id not in closure:
                closure.add(call.func.id)
                pending.append(call.func.id)
    assigned_constants: dict[str, ast.stmt] = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    assigned_constants[target.id] = node
    referenced_constants = {
        item.id for name in closure for item in ast.walk(functions[name])
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load) and
        item.id in assigned_constants
    }
    required_constants = set(constant_names) | referenced_constants
    selected: list[ast.stmt] = []
    found_functions: set[str] = set()
    found_constants: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in closure:
            selected.append(node)
            found_functions.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {
                target.id for target in targets
                if isinstance(target, ast.Name) and target.id in required_constants
            }
            if names:
                selected.append(node)
                found_constants.update(names)
    if found_functions != closure or found_constants != required_constants:
        raise ThemeForwardComparisonError(
            f"missing frozen producer semantics in {path.name}: "
            f"functions={sorted(closure - found_functions)}, "
            f"constants={sorted(required_constants - found_constants)}"
        )
    return ast.dump(
        _strip_docstrings(ast.Module(body=selected, type_ignores=[])),
        include_attributes=False,
    )


def _contract_constant_semantics() -> dict[str, str]:
    """Bind every module constant, so a new gate constant cannot escape the contract.

    Functions already bind by default through `_contract_function_semantics`, but
    the module's own constants were enumerated by hand inside
    `comparison_contract_fingerprint`: a constant added later and used in a gate
    could change behaviour without moving the fingerprint.  This binds the
    checked-in assignment statements themselves — the same AST polarity the
    external producer files already get from `_semantic_file_contract_digest`.

    Path constants need no exclusion.  Only an *evaluated* path is
    machine-dependent; the source expression (`ROOT / "presets" / ...`) is not,
    and re-pointing one at a different preset is a real contract change that
    SHOULD move the fingerprint.  Comments and formatting are absent from the
    AST, so prose edits still cannot open a new epoch.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    bound: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                bound[target.id] = ast.dump(node, include_attributes=False)
    if not bound:
        raise ThemeForwardComparisonError("module_constant_contract_is_empty")
    return dict(sorted(bound.items()))


def _contract_function_semantics() -> dict[str, str]:
    """Bind every local runtime function; a monkeypatch removes or changes it."""
    return {
        name: _semantic_function_digest(value)
        for name, value in sorted(globals().items())
        if inspect.isfunction(value) and value.__module__ == __name__ and
        name not in CONTRACT_FUNCTION_SEMANTICS_EXCLUSIONS
    }


def epoch_identity_fingerprint(epoch: dict[str, Any]) -> str:
    """Seal immutable epoch fields while receipts/decision advance monotonically."""
    return _digest({
        key: epoch.get(key)
        for key in (
            "schema_name", "schema_version", "track", "mode", "epoch_id", "epoch_start_as_of",
            "governance_fingerprint", "contract_fingerprint", "freeze_packet_identity",
            "frozen_theme_ids",
            "taxonomy_registry_fingerprint", "taxonomy_registry_effective_date",
            "source_configuration_fingerprints", "boundary",
        )
    })


def _canonical_receipt_value(value: Any) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if isinstance(value, dict):
        return {str(key): _canonical_receipt_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical_receipt_value(item) for item in value]
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return str(value)


def _cohort_evidence_digest(cohort: pd.DataFrame) -> str:
    """Bind every input field that can shape this component's result."""
    columns = sorted((REQUIRED_COLUMNS | set(LEGACY_OPTIONAL_COLUMNS)) & set(cohort.columns))
    rows = [
        {column: _canonical_receipt_value(row.get(column)) for column in columns}
        for row in cohort.to_dict(orient="records")
    ]
    rows.sort(key=lambda row: (_as_text(row.get("ts_code")), _as_text(row.get("analysis_role"))))
    return _digest({"columns": columns, "rows": rows})


def _cohort_admission_digest(cohort: pd.DataFrame) -> str:
    """Bind decision-time candidates and strategy inputs, excluding later H10 settlement fields."""
    mutable_outcome_columns = {
        RETURN_STATUS_COLUMN, RETURN_COLUMN, RETURN_UNIT_COLUMN,
        "entry_date", RETURN_EXIT_DATE_COLUMN,
    }
    columns = sorted(
        ((REQUIRED_COLUMNS | set(LEGACY_OPTIONAL_COLUMNS)) - mutable_outcome_columns)
        & set(cohort.columns)
    )
    rows = [
        {column: _canonical_receipt_value(row.get(column)) for column in columns}
        for row in cohort.to_dict(orient="records")
    ]
    rows.sort(key=lambda row: (_as_text(row.get("ts_code")), _as_text(row.get("analysis_role"))))
    return _digest({"columns": columns, "rows": rows})


def _seal_private_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    record = dict(payload)
    record["record_sha256"] = _digest(record)
    return record


def _validate_private_receipt_seal(receipt: dict[str, Any], record_type: str) -> None:
    if receipt.get("schema_name") != PRIVATE_RECEIPT_SCHEMA or \
            receipt.get("schema_version") != "1.0.0" or \
            receipt.get("record_type") != record_type or \
            receipt.get("track") != TRACK_ID:
        raise ThemeForwardComparisonError(f"invalid private {record_type} receipt identity")
    expected = _digest({key: value for key, value in receipt.items() if key != "record_sha256"})
    if receipt.get("record_sha256") != expected:
        raise ThemeForwardComparisonError(f"private {record_type} receipt seal mismatch")


def outcome_receipt_manifest(receipts: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    """Return the monotonic outcome-receipt chain committed by the epoch."""
    entries = [
        {"as_of": as_of, "record_sha256": _as_text(receipt.get("record_sha256"))}
        for as_of, receipt in sorted((receipts or {}).items())
    ]
    return {
        "receipt_count": len(entries),
        "chain_head_sha256": _digest(entries),
        "last_as_of": entries[-1]["as_of"] if entries else None,
    }


def admission_receipt_manifest(receipts: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    """Return the monotonic decision-time admission chain committed by the epoch."""
    return outcome_receipt_manifest(receipts)


def _cohort_outcomes_are_unobserved(cohort: pd.DataFrame) -> bool:
    return all(
        _finite(row.get(RETURN_COLUMN)) is None
        and _as_text(row.get(RETURN_STATUS_COLUMN)) in UNOBSERVED_RETURN_STATUSES
        for row in cohort.to_dict(orient="records")
    )


def _decision_time_projection(cohort: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct only the decision fields used to create an admission receipt.

    This is an integrity projection, not an independently trusted timestamp:
    a local operator who can rewrite both the private receipt chain and epoch
    pointer can still state a false past admission time.  That boundary is
    explicit in the receipt and design contract.
    """
    projected = cohort.copy()
    projected[RETURN_STATUS_COLUMN] = "pending_capture"
    projected[RETURN_COLUMN] = pd.NA
    for column in ("entry_date", RETURN_EXIT_DATE_COLUMN):
        if column in projected.columns:
            projected[column] = pd.NA
    return projected


def _admission_receipt_fields(
    cohort: pd.DataFrame, epoch: dict[str, Any], top_n: int, admission_date: date,
) -> dict[str, Any] | None:
    """Return immutable decision-time facts; later H10 settlement is deliberately excluded."""
    if cohort.empty or _cohort_formal_error(
            cohort, top_n, require_decision_effective=False) is not None:
        return None
    as_ofs = {_as_text(value) for value in cohort["as_of"]}
    if len(as_ofs) != 1 or next(iter(as_ofs)) < _as_text(epoch["epoch_start_as_of"]):
        return None
    decision_date = _yyyymmdd(next(iter(as_ofs)), "as_of")
    deadline = decision_date + timedelta(days=ADMISSION_GRACE_CALENDAR_DAYS)
    if admission_date > deadline or not _theme_references_within_epoch(cohort, epoch["frozen_theme_ids"]):
        return None
    return {
        "epoch_id": epoch["epoch_id"],
        "epoch_identity_fingerprint": epoch["epoch_identity_fingerprint"],
        "freeze_packet_identity": epoch["freeze_packet_identity"],
        "as_of": next(iter(as_ofs)),
        "row_count": int(len(cohort)),
        "admission_recorded_on": admission_date.strftime("%Y%m%d"),
        "admission_deadline": deadline.strftime("%Y%m%d"),
        "outcomes_unobserved_at_admission": True,
        "admission_time_provenance": ADMISSION_TIME_PROVENANCE,
        "cohort_admission_sha256": _cohort_admission_digest(cohort),
    }


def build_cohort_admission_receipt(
    cohort: pd.DataFrame, epoch: dict[str, Any], top_n: int, *,
    admission_date: date | None = None,
) -> dict[str, Any] | None:
    """Seal an atomic cohort before any H10 outcome is observable."""
    fields = _admission_receipt_fields(cohort, epoch, top_n, admission_date or _today_date())
    if fields is None or not _cohort_outcomes_are_unobserved(cohort):
        return None
    return _seal_private_receipt({
        "schema_name": PRIVATE_RECEIPT_SCHEMA,
        "schema_version": "1.0.0",
        "record_type": "cohort_admission",
        "track": TRACK_ID,
        **fields,
    })


def validate_cohort_admission_receipt(
    receipt: dict[str, Any], cohort: pd.DataFrame, epoch: dict[str, Any], top_n: int
) -> None:
    _validate_private_receipt_seal(receipt, "cohort_admission")
    try:
        admitted_on = _yyyymmdd(receipt.get("admission_recorded_on"), "admission_recorded_on")
    except ThemeForwardComparisonError as exc:
        raise ThemeForwardComparisonError("admitted cohort has no valid recorded-on date") from exc
    expected = build_cohort_admission_receipt(
        _decision_time_projection(cohort), epoch, top_n, admission_date=admitted_on,
    )
    if expected is None or receipt != expected:
        raise ThemeForwardComparisonError(
            "admitted cohort is no longer formally eligible; admission receipt no longer matches decision evidence"
        )


def build_terminal_outcome_receipt(
    cohort: pd.DataFrame, epoch: dict[str, Any], top_n: int,
    admission_receipt: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a sealed immutable cohort receipt only after every H10 outcome is terminal."""
    if cohort.empty:
        return None
    if admission_receipt is None:
        return None
    try:
        validate_cohort_admission_receipt(admission_receipt, cohort, epoch, top_n)
    except ThemeForwardComparisonError:
        return None
    as_ofs = {_as_text(value) for value in cohort["as_of"]}
    if len(as_ofs) != 1:
        raise ThemeForwardComparisonError("terminal outcome receipt must contain exactly one cohort")
    rows = cohort.to_dict(orient="records")
    for row in rows:
        status = _as_text(row.get(RETURN_STATUS_COLUMN))
        if status == "ok":
            if _finite(row.get(RETURN_COLUMN)) is None:
                return None
        elif status not in TERMINAL_CASH_STATUSES:
            return None
    if _complete_cohort_interval(rows) is None:
        return None
    primary = _score_sorted([row for row in rows if _as_text(row.get("analysis_role")) == "final"])[:top_n]
    if _selection_return(primary, top_n, require_full_selection=True)[0] is None:
        return None
    return _seal_private_receipt({
        "schema_name": PRIVATE_RECEIPT_SCHEMA,
        "schema_version": "1.0.0",
        "record_type": "terminal_outcome",
        "track": TRACK_ID,
        "epoch_id": epoch["epoch_id"],
        "epoch_identity_fingerprint": epoch["epoch_identity_fingerprint"],
        "freeze_packet_identity": epoch["freeze_packet_identity"],
        "as_of": next(iter(as_ofs)),
        "row_count": int(len(cohort)),
        "admission_receipt_sha256": admission_receipt["record_sha256"],
        "cohort_evidence_sha256": _cohort_evidence_digest(cohort),
    })


def validate_terminal_outcome_receipt(receipt: dict[str, Any], cohort: pd.DataFrame,
                                      epoch: dict[str, Any], top_n: int,
                                      admission_receipt: dict[str, Any] | None = None) -> None:
    _validate_private_receipt_seal(receipt, "terminal_outcome")
    expected = build_terminal_outcome_receipt(
        cohort, epoch, top_n, admission_receipt=admission_receipt
    )
    if expected is None or receipt != expected:
        raise ThemeForwardComparisonError("terminal outcome receipt no longer matches tracker evidence")


def build_formal_decision_receipt(epoch: dict[str, Any], as_of: str, packet_sha256: str,
                                  archive_relative_path: str | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9]{8}", _as_text(as_of)) or \
            not re.fullmatch(r"[0-9a-f]{64}", _as_text(packet_sha256)) or \
            not re.fullmatch(r"epochs/[A-Za-z0-9][A-Za-z0-9._-]*/formal_packet\.json",
                             _as_text(archive_relative_path)):
        raise ThemeForwardComparisonError("formal decision receipt has invalid date, digest, or archive path")
    return _seal_private_receipt({
        "schema_name": PRIVATE_RECEIPT_SCHEMA,
        "schema_version": "1.0.0",
        "record_type": "formal_decision",
        "track": TRACK_ID,
        "epoch_id": epoch["epoch_id"],
        "epoch_identity_fingerprint": epoch["epoch_identity_fingerprint"],
        "freeze_packet_identity": epoch["freeze_packet_identity"],
        "as_of": _as_text(as_of),
        "packet_sha256": _as_text(packet_sha256),
        "archive_relative_path": _as_text(archive_relative_path),
    })


def validate_formal_decision_receipt(receipt: dict[str, Any], epoch: dict[str, Any]) -> None:
    _validate_private_receipt_seal(receipt, "formal_decision")
    decision = epoch["formal_decision"]
    if decision["status"] != "recorded" or any(
        receipt.get(key) != expected
        for key, expected in (
            ("epoch_id", epoch["epoch_id"]),
            ("epoch_identity_fingerprint", epoch["epoch_identity_fingerprint"]),
            ("freeze_packet_identity", epoch["freeze_packet_identity"]),
            ("as_of", decision["as_of"]),
            ("packet_sha256", decision["packet_sha256"]),
            ("archive_relative_path", decision["archive_relative_path"]),
            ("record_sha256", decision["receipt_sha256"]),
        )
    ):
        raise ThemeForwardComparisonError("formal decision receipt does not match active epoch")


def comparison_contract_fingerprint(governance: dict[str, Any], frozen_theme_ids: list[str] | None = None,
                                    source_configuration_fingerprints: dict[str, str] | None = None,
                                    freeze_packet_identity: dict[str, str] | None = None) -> str:
    """Bind the full local execution dependency closure and frozen policy."""
    return _digest({
        "governance": governance,
        "return_window_days": RETURN_WINDOW_DAYS,
        "return_unit": RETURN_UNIT,
        "return_columns": [
            RETURN_STATUS_COLUMN, RETURN_COLUMN, RETURN_UNIT_COLUMN, RETURN_EXIT_DATE_COLUMN,
        ],
        "clock_contract": {
            "decision_as_of_column": DECISION_AS_OF_COLUMN,
            "run_date_column": RUN_DATE_COLUMN,
            "price_data_through_column": PRICE_DATA_THROUGH_COLUMN,
            "candidate_count_column": CANDIDATE_COUNT_COLUMN,
            "max_decision_lead_calendar_days": MAX_DECISION_LEAD_CALENDAR_DAYS,
            "admission_grace_calendar_days": ADMISSION_GRACE_CALENDAR_DAYS,
        },
        "terminal_cash_statuses": sorted(TERMINAL_CASH_STATUSES),
        "unobserved_return_statuses": sorted(UNOBSERVED_RETURN_STATUSES),
        "theme_role_values": sorted(THEME_ROLE_VALUES),
        "track_id": TRACK_ID,
        "fifth_knife_freeze_packet_identity": freeze_packet_identity,
        "private_receipt_schema": PRIVATE_RECEIPT_SCHEMA,
        "required_columns": sorted(REQUIRED_COLUMNS),
        "legacy_optional_columns": list(LEGACY_OPTIONAL_COLUMNS),
        "criterion_ids": list(CRITERION_IDS),
        "frozen_theme_ids": sorted(set(frozen_theme_ids or [])),
        "source_configuration_fingerprints": source_configuration_fingerprints or {},
        "schema_contract_fingerprint": {
            label: _digest(json.loads(path.read_text(encoding="utf-8")))
            for label, path in (
                ("governance", GOVERNANCE_SCHEMA_PATH),
                ("epoch", EPOCH_SCHEMA_PATH),
                ("taxonomy", TAXONOMY_SCHEMA_PATH),
            )
        },
        "receipt_semantics": _semantic_file_contract_digest(
            RUNNER_PATH,
            {
                "_write_json_atomic", "_write_json_exclusive", "_private_root",
                "_epoch_private_dir", "_load_private_receipts",
                "_sync_cohort_admission_receipts", "_sync_terminal_outcome_receipts",
                "_load_formal_decision_receipt", "_load_recorded_formal_packet",
                "_record_formal_decision_if_due", "_start_or_reset_epoch", "main",
            },
            {
                "DEFAULT_TRACKER", "DEFAULT_OUTPUT", "EPOCH_ARCHIVE_DIR",
                "DEFAULT_PRIVATE_ROOT", "TRACKER_STRING_COLUMNS",
            },
        ),
        "return_producer_semantics": _semantic_file_contract_digest(
            BACKTEST_RANK_PATH,
            {
                "_tushare_pro", "_fn_label", "_ts_call", "_trade_calendar", "_shift_yyyymmdd",
                "_benchmark_frame_has_same_anchor_fields", "_normalize_benchmark_daily_frame",
                "_write_forward_daily_cache", "fetch_forward_daily", "_benchmark_returns",
                "_fallback_limit_ratio", "_is_entry_limit_up", "attach_forward_returns",
            },
            {"DEFAULT_COST_PCT", "BENCHMARKS"},
        ),
        "tracker_producer_semantics": _semantic_file_contract_digest(
            FORWARD_TRACKER_PATH,
            {
                "_candidate_row", "_load_existing_tracker", "_write_tracker", "capture",
                "_today_yyyymmdd", "_mature_as_ofs", "_pending_backfill_mask", "backfill",
                "_load_cache_for_coverage", "_check_cache_coverage", "_cached_stock_trade_dates",
                "_partition_asof_coverage", "_board_from_code",
            },
            {
                "TRACKER_CSV", "LIVE_RESULT_ROOT", "SCHEMA_COLUMNS",
                "TRACKER_STRING_COLUMNS", "DEFAULT_WINDOWS",
                "MATURE_BUFFER_CALENDAR_DAYS", "TERMINAL_FORWARD_STATUSES",
                "DECISION_TIME_COLUMNS",
            },
        ),
        "policy_semantics": _contract_function_semantics(),
        # Bound by default rather than by the hand-written list above, which is
        # kept only as a readable subset; see `_contract_constant_semantics`.
        "policy_constants": _contract_constant_semantics(),
    })


def _recorded_formal_packet_matches(packet: dict[str, Any] | None, epoch: dict[str, Any]) -> bool:
    archived_epoch = (packet or {}).get("epoch") or {}
    return isinstance(packet, dict) and bool(packet.get("formal_verdict_allowed")) and \
        (packet.get("checkpoints") or {}).get("current_checkpoint") == "formal_decision_due" and \
        all(
            archived_epoch.get(key) == epoch.get(key)
            for key in (
                "epoch_id", "epoch_start_as_of", "contract_fingerprint",
                "freeze_packet_identity",
            )
        )


def _epoch_context(
    governance: dict[str, Any],
    formal_decision_receipt: dict[str, Any] | None = None,
    recorded_formal_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed on any registry/epoch/fingerprint disagreement."""
    from engine import a_short_evidence_epoch_mode as epoch_mode

    epoch = load_epoch(verify_identity=False)
    current_packet_identity = epoch_mode.validated_frozen_packet_identity(TRACK_ID)
    registry_enforced = current_packet_identity is not None
    epoch_enforced = epoch["mode"] == "frozen_enforced"
    if registry_enforced != epoch_enforced:
        return {"state": "epoch_mode_mismatch", "epoch": epoch}
    if not epoch_enforced:
        return {"state": "audit_only_pre_freeze", "epoch": epoch}
    if epoch.get("epoch_identity_fingerprint") != epoch_identity_fingerprint(epoch):
        return {"state": "epoch_identity_mismatch", "epoch": epoch}
    if epoch.get("freeze_packet_identity") != current_packet_identity:
        return {"state": "epoch_contract_mismatch", "epoch": epoch}
    frozen_theme_ids = epoch["frozen_theme_ids"]
    if not frozen_theme_ids:
        return {"state": "epoch_contract_mismatch", "epoch": epoch}
    registry = load_taxonomy_registry()
    registry_ids = sorted(_as_text(item["theme_id"]) for item in registry["canonical_themes"])
    if registry_ids != frozen_theme_ids or _digest(registry) != epoch["taxonomy_registry_fingerprint"] or \
            _as_text(registry.get("effective_date")) != epoch["taxonomy_registry_effective_date"]:
        return {"state": "epoch_contract_mismatch", "epoch": epoch}
    current = comparison_contract_fingerprint(
        governance, frozen_theme_ids, epoch["source_configuration_fingerprints"],
        current_packet_identity,
    )
    if current != epoch["contract_fingerprint"] or _digest(governance) != epoch["governance_fingerprint"]:
        return {"state": "epoch_contract_mismatch", "epoch": epoch}
    if epoch["formal_decision"]["status"] == "recorded":
        try:
            if formal_decision_receipt is None:
                raise ThemeForwardComparisonError("recorded formal decision has no immutable receipt")
            validate_formal_decision_receipt(formal_decision_receipt, epoch)
            if not _recorded_formal_packet_matches(recorded_formal_packet, epoch):
                raise ThemeForwardComparisonError("recorded formal packet is missing or malformed")
        except ThemeForwardComparisonError:
            return {"state": "epoch_formal_decision_mismatch", "epoch": epoch}
    elif formal_decision_receipt is not None:
        return {"state": "epoch_formal_decision_mismatch", "epoch": epoch}
    return {"state": "frozen_counting", "epoch": epoch}


def _formal_policy_verdict(item: dict[str, Any], policy: dict[str, Any], formal_allowed: bool) -> str:
    if not formal_allowed:
        return "audit_only_pre_freeze"
    stats = item["nonoverlap_h10_blocks"]
    if stats["block_count"] < int(policy["minimum_nonoverlap_h10_blocks"]):
        return "insufficient_evidence"
    if not item["coverage"]["deployable"]:
        return "not_deployable"
    adjusted = item["adjudication"]["holm_adjusted_two_sided_practical_p"]
    ci = stats["family_adjusted_ci_pp"]
    margin = float(policy["practical_margin_pp"])
    if adjusted is not None and adjusted <= float(policy["holm_alpha"]):
        if ci[0] >= margin:
            return "supported"
        if ci[1] <= -margin:
            return "harmful"
    if ci[1] < margin:
        return "not_practically_superior"
    if stats["minimum_detectable_effect_pp"] is None or stats["minimum_detectable_effect_pp"] > margin:
        return "underpowered"
    return "not_supported"


def _formal_negative_control_verdict(control: dict[str, Any], policy: dict[str, Any], formal_allowed: bool) -> str:
    if not formal_allowed:
        return "audit_only_pre_freeze"
    if control["predictive_discrimination"]["positive_stock_observations"] == 0:
        return "not_assessable_zero_observation"
    if not control["coverage"]["deployable"]:
        return "not_assessable_low_coverage"
    stats = control["nonoverlap_h10_blocks"]
    if stats["block_count"] < int(policy["minimum_nonoverlap_h10_blocks"]):
        return "insufficient_evidence"
    ci = stats["ci_95_pp"]
    margin = float(policy["practical_margin_pp"])
    if ci[1] <= -margin:
        return "expected_harm_observed"
    if ci[0] >= margin:
        return "unexpected_benefit_method_validity_warning"
    return "inconclusive_does_not_invalidate_family"


def _matured_primary_as_ofs(live: pd.DataFrame, top_n: int) -> list[str]:
    """Return only weeks whose official final-policy H10 outcome is settled."""
    matured: list[str] = []
    for as_of, cohort in live.groupby("as_of", dropna=False):
        rows = cohort.to_dict(orient="records")
        primary = _score_sorted([row for row in rows if _as_text(row.get("analysis_role")) == "final"])[:top_n]
        primary_return, _ = _selection_return(primary, top_n, require_full_selection=True)
        if primary_return is not None:
            matured.append(_as_text(as_of))
    return sorted(value for value in matured if value)


def _weekly_matured_as_ofs(matured_as_ofs: list[str]) -> list[str]:
    """Collapse multiple daily cohorts into one deterministic clock cohort per ISO week."""
    selected: list[str] = []
    seen_weeks: set[tuple[int, int]] = set()
    for value in sorted(matured_as_ofs):
        date_value = datetime.strptime(value, "%Y%m%d").date()
        week_key = (date_value.isocalendar().year, date_value.isocalendar().week)
        if week_key in seen_weeks:
            continue
        seen_weeks.add(week_key)
        selected.append(value)
    return selected


def _weekly_latest_as_ofs(
    as_ofs: list[str], sealed_as_ofs: set[str] | None = None,
) -> list[str]:
    """Choose one cohort per ISO week; an immutable sealed cohort always wins."""
    latest: dict[tuple[int, int], str] = {}
    sealed_by_week: dict[tuple[int, int], str] = {}
    for value in sorted(sealed_as_ofs or set()):
        date_value = datetime.strptime(value, "%Y%m%d").date()
        week_key = (date_value.isocalendar().year, date_value.isocalendar().week)
        if week_key in sealed_by_week and sealed_by_week[week_key] != value:
            raise ThemeForwardComparisonError("multiple immutable cohorts occupy one ISO-week evidence slot")
        sealed_by_week[week_key] = value
    for value in sorted(as_ofs):
        date_value = datetime.strptime(value, "%Y%m%d").date()
        week_key = (date_value.isocalendar().year, date_value.isocalendar().week)
        if week_key not in sealed_by_week:
            latest[week_key] = value
    latest.update(sealed_by_week)
    return sorted(latest.values())


def _validated_admission_receipt_as_ofs(
    live: pd.DataFrame, epoch: dict[str, Any], top_n: int,
    receipts: dict[str, dict[str, Any]] | None,
) -> tuple[set[str], bool]:
    receipts = receipts or {}
    if admission_receipt_manifest(receipts) != epoch["admission_receipt_manifest"]:
        return set(), True
    valid: set[str] = set()
    cohorts = {_as_text(as_of): cohort for as_of, cohort in live.groupby("as_of", dropna=False)}
    try:
        for as_of, receipt in receipts.items():
            if as_of not in cohorts:
                raise ThemeForwardComparisonError("sealed admitted cohort disappeared from tracker")
            validate_cohort_admission_receipt(receipt, cohorts[as_of], epoch, top_n)
            valid.add(as_of)
    except ThemeForwardComparisonError:
        return set(), True
    return valid, False


def _validated_outcome_receipt_as_ofs(
    live: pd.DataFrame, epoch: dict[str, Any], top_n: int,
    receipts: dict[str, dict[str, Any]] | None,
    admission_receipts: dict[str, dict[str, Any]] | None,
) -> tuple[set[str], bool]:
    """Return immutable cohorts eligible to count and flag any receipt/evidence disagreement."""
    receipts = receipts or {}
    if outcome_receipt_manifest(receipts) != epoch["outcome_receipt_manifest"]:
        return set(), True
    valid: set[str] = set()
    cohorts = {_as_text(as_of): cohort for as_of, cohort in live.groupby("as_of", dropna=False)}
    try:
        for as_of, receipt in receipts.items():
            if as_of not in cohorts:
                raise ThemeForwardComparisonError("sealed terminal cohort disappeared from tracker")
            validate_terminal_outcome_receipt(
                receipt, cohorts[as_of], epoch, top_n,
                admission_receipt=(admission_receipts or {}).get(as_of),
            )
            valid.add(as_of)
    except ThemeForwardComparisonError:
        return set(), True
    return valid, False


def frozen_theme_ids_from_taxonomy_registry() -> tuple[list[str], str, str]:
    """Freeze the full registry family, not merely themes observed at start."""
    registry = load_taxonomy_registry()
    theme_ids = sorted(_as_text(item["theme_id"]) for item in registry["canonical_themes"])
    effective_date = _as_text(registry.get("effective_date")).removesuffix(".0")
    if not re.fullmatch(r"[0-9]{8}", effective_date):
        raise ThemeForwardComparisonError("theme taxonomy registry effective_date is invalid")
    return theme_ids, _digest(registry), effective_date


def source_configuration_fingerprints_from_start_cohort(tracker: pd.DataFrame, start_as_of: str) -> dict[str, str]:
    """Bind an epoch to the source configuration of its latest start cohort."""
    live = validate_tracker_lineage(tracker)
    cohort = live[live["as_of"].map(_as_text) == _as_text(start_as_of)]
    values = {
        column: {_as_text(value) for value in cohort[column]}
        for column in (
            "industry_trend_configuration_fingerprint",
            "theme_taxonomy_configuration_fingerprint",
            RUNTIME_CONFIGURATION_FINGERPRINT_COLUMN,
        )
    }
    if any(len(value) != 1 or not next(iter(value)) for value in values.values()):
        raise ThemeForwardComparisonError("epoch start cohort has ambiguous source configuration fingerprints")
    return {column: next(iter(value)) for column, value in values.items()}


def build_frozen_epoch(
    tracker: pd.DataFrame, epoch_id: str, start_as_of: str, *,
    freeze_packet_identity: dict[str, str],
) -> dict[str, Any]:
    """Build, but never implicitly persist, a new explicit frozen epoch."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", _as_text(epoch_id)):
        raise ThemeForwardComparisonError("epoch_id must be a safe non-empty slug")
    governance = load_governance()
    frozen_theme_ids, taxonomy_fingerprint, taxonomy_effective_date = \
        frozen_theme_ids_from_taxonomy_registry()
    start_live = validate_tracker_lineage(tracker)
    available_as_ofs = sorted({_as_text(value) for value in start_live["as_of"] if _as_text(value)})
    if not available_as_ofs or _as_text(start_as_of) != available_as_ofs[-1]:
        raise ThemeForwardComparisonError(
            "epoch start must be the latest source-bound forward-live cohort; historic evidence cannot be back-counted"
        )
    eligible_start, rejected = eligible_formal_cohorts(
        start_live[start_live["as_of"].map(_as_text) == _as_text(start_as_of)].copy(),
        int(governance["policy"]["top_n"]),
        require_decision_effective=False,
    )
    if eligible_start.empty:
        raise ThemeForwardComparisonError(
            f"epoch start cohort is not a complete atomic Stage3 cohort: {rejected.get(_as_text(start_as_of), 'missing')}"
        )
    if _today_date() > _yyyymmdd(start_as_of, "epoch_start_as_of") + timedelta(
            days=ADMISSION_GRACE_CALENDAR_DAYS):
        raise ThemeForwardComparisonError(
            "epoch start missed the decision-time admission window"
        )
    if not _theme_references_within_epoch(eligible_start, frozen_theme_ids):
        raise ThemeForwardComparisonError(
            "epoch start cohort references themes outside the frozen taxonomy registry"
        )
    source_configuration_fingerprints = source_configuration_fingerprints_from_start_cohort(
        tracker, start_as_of
    )
    if not _cohort_outcomes_are_unobserved(eligible_start):
        raise ThemeForwardComparisonError(
            "epoch start entire atomic Stage3 cohort must have unobserved H10 outcomes"
        )
    epoch = {
        "schema_name": "a_short_theme_forward_comparison_epoch",
        "schema_version": "1.4.0",
        "track": TRACK_ID,
        "mode": "frozen_enforced",
        "epoch_id": _as_text(epoch_id),
        "epoch_start_as_of": _as_text(start_as_of),
        "governance_fingerprint": _digest(governance),
        "contract_fingerprint": comparison_contract_fingerprint(
            governance, frozen_theme_ids, source_configuration_fingerprints,
            freeze_packet_identity,
        ),
        "freeze_packet_identity": freeze_packet_identity,
        "frozen_theme_ids": frozen_theme_ids,
        "taxonomy_registry_fingerprint": taxonomy_fingerprint,
        "taxonomy_registry_effective_date": taxonomy_effective_date,
        "source_configuration_fingerprints": source_configuration_fingerprints,
        "admission_receipt_manifest": admission_receipt_manifest({}),
        "outcome_receipt_manifest": outcome_receipt_manifest({}),
        "formal_decision": {
            "status": "not_recorded", "as_of": None, "packet_sha256": None,
            "archive_relative_path": None, "receipt_sha256": None,
        },
        "boundary": {"historical_replay_counts_as_forward": False, "automatic_promotion": False,
                     "production_replacement_authorized": False},
    }
    epoch["epoch_identity_fingerprint"] = epoch_identity_fingerprint(epoch)
    return epoch


def _source_configuration_matches_epoch(live: pd.DataFrame, epoch: dict[str, Any]) -> bool:
    expected = epoch["source_configuration_fingerprints"]
    return all({_as_text(value) for value in live[column]} == {fingerprint}
               for column, fingerprint in expected.items())


def validate_comparison_packet(packet: dict[str, Any]) -> None:
    """Fail closed before the runner can persist an ambiguous evidence receipt."""
    boundary = packet.get("comparison_boundary") or {}
    if packet.get("schema_name") != "a_short_theme_forward_comparison" or packet.get("schema_version") != "2.0.0":
        raise ThemeForwardComparisonError("invalid comparison packet identity")
    if any(boundary.get(key) for key in ("automatic_promotion", "activation_authorized",
                                         "changes_official_star_risk_action_or_cash")):
        raise ThemeForwardComparisonError("comparison packet crossed the production boundary")
    if boundary.get("return_unit") != RETURN_UNIT:
        raise ThemeForwardComparisonError("comparison packet return unit drift")
    packet_epoch = packet.get("epoch") or {}
    packet_freeze_identity = packet_epoch.get("freeze_packet_identity")
    if packet_epoch.get("mode") == "frozen_enforced":
        if not isinstance(packet_freeze_identity, dict) or \
                set(packet_freeze_identity) != {
                    "freeze_id", "schema_version", "record_sha256",
                } or \
                not _as_text(packet_freeze_identity.get("freeze_id")) or \
                packet_freeze_identity.get("schema_version") != "1.0.0" or \
                not re.fullmatch(
                    r"[0-9a-f]{64}",
                    _as_text(packet_freeze_identity.get("record_sha256")),
                ):
            raise ThemeForwardComparisonError(
                "comparison packet has no exact freeze-packet identity"
            )
    elif packet_freeze_identity is not None:
        raise ThemeForwardComparisonError(
            "pre-freeze comparison packet cannot claim a frozen packet identity"
        )
    criteria = packet.get("criteria")
    if not isinstance(criteria, list) or tuple(row.get("criterion_id") for row in criteria) != CRITERION_IDS:
        raise ThemeForwardComparisonError("comparison packet must carry the frozen seven-criterion family")
    for item in criteria:
        if not isinstance(item.get("predictive_discrimination"), dict) or \
                not isinstance(item.get("policy_vs_primary"), dict):
            raise ThemeForwardComparisonError("comparison criterion must expose independent predictive and policy layers")
        coverage = item["policy_vs_primary"].get("coverage") or {}
        if any(key not in coverage for key in (
                "evidence_block_as_ofs", "evidence_block_count",
                "counted_block_execution_profile",
                "minimum_counted_block_executed_positions",
                "minimum_observed_counted_block_positions",
                "average_selected_positions", "average_cash_slots", "cash_slot_rate",
                "full_slot_week_rate", "primary_average_executed_positions",
                "primary_average_cash_slots", "primary_cash_slot_rate",
                "primary_full_slot_week_rate", "deployable",
        )):
            raise ThemeForwardComparisonError("policy layer coverage is incomplete")
        if coverage["evidence_block_count"] != item["nonoverlap_h10_blocks"]["block_count"] or \
                len(coverage["evidence_block_as_ofs"]) != coverage["evidence_block_count"]:
            raise ThemeForwardComparisonError("coverage and statistical evidence blocks diverged")
        profiles = coverage["counted_block_execution_profile"]
        if not isinstance(profiles, list) or len(profiles) != coverage["evidence_block_count"] or \
                [profile.get("as_of") for profile in profiles] != coverage["evidence_block_as_ofs"] or \
                any(any(key not in profile for key in (
                    "entry_date", "exit_date", "challenger_selected_candidates",
                    "challenger_executed_positions", "challenger_cash_slots",
                    "primary_selected_candidates", "primary_executed_positions", "primary_cash_slots",
                )) for profile in profiles):
            raise ThemeForwardComparisonError("counted-block execution profile is incomplete or unbound")
        if (item.get("exploratory") or {}).get("actionable") is not False:
            raise ThemeForwardComparisonError("criterion exploratory result became actionable")
    receipt = packet.get("receipt") or {}
    if receipt.get("next_action") != "separate_reviewed_activation_route_required" or \
            receipt.get("production_replacement_recommendation") is not False or \
            receipt.get("p4a_modified") is not False:
        raise ThemeForwardComparisonError("comparison receipt crossed the review-only boundary")
    if any((item or {}).get("actionable") is not False
           for item in packet.get("exploratory_themes") or []):
        raise ThemeForwardComparisonError("exploratory theme result became actionable")
    if packet.get("formal_verdict_allowed") and \
            (packet.get("checkpoints") or {}).get("current_checkpoint") != "formal_decision_due":
        raise ThemeForwardComparisonError("formal verdict escaped its one fixed boundary")
    recorded = ((packet.get("epoch") or {}).get("formal_decision") or {}).get("status") == "recorded"
    requires_visible_record = recorded and packet.get("adjudication_mode") != \
        "epoch_formal_decision_mismatch"
    if requires_visible_record != isinstance(packet.get("recorded_formal_decision"), dict):
        raise ThemeForwardComparisonError("recorded formal decision must remain visible in the public packet")
    control_status = _as_text((packet.get("negative_control") or {}).get("method_validity_status"))
    control_blocks = control_status == "unexpected_benefit_method_validity_warning" or \
        control_status.startswith("not_assessable_")
    if control_blocks != bool((packet.get("receipt") or {}).get("replacement_evidence_blocked")):
        raise ThemeForwardComparisonError("negative-control status must bind the replacement-evidence block")
    if (packet.get("receipt") or {}).get("replacement_evidence_block_reason") != \
            _replacement_evidence_block_reason(control_status):
        raise ThemeForwardComparisonError("negative-control block reason must name its actual status")
    formal_verdicts = {
        "supported", "harmful", "not_practically_superior", "underpowered",
        "not_supported", "insufficient_evidence", "not_deployable",
    }
    nonformal_verdicts = {
        "audit_only_pre_freeze", "accumulating", "preview_only", "evidence_blocked",
    }
    criterion_verdicts = {
        (item.get("adjudication") or {}).get("verdict") for item in criteria
    }
    checkpoint = (packet.get("checkpoints") or {}).get("current_checkpoint")
    if packet.get("formal_verdict_allowed"):
        allowed = formal_verdicts
    elif checkpoint == "formal_decision_recorded":
        allowed = formal_verdicts
    else:
        allowed = nonformal_verdicts
    if not criterion_verdicts.issubset(allowed):
        raise ThemeForwardComparisonError("criterion verdict is inconsistent with the epoch checkpoint")


def evaluate_theme_forward_comparison(
    tracker: pd.DataFrame,
    *,
    admission_receipts: dict[str, dict[str, Any]] | None = None,
    outcome_receipts: dict[str, dict[str, Any]] | None = None,
    formal_decision_receipt: dict[str, Any] | None = None,
    recorded_formal_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return frozen-policy evidence without a trade, promotion, or activation decision."""
    governance = load_governance()
    live = validate_tracker_lineage(tracker)
    epoch_context = _epoch_context(
        governance, formal_decision_receipt, recorded_formal_packet
    )
    all_rows = int(len(tracker))
    flag_values = [_forward_flags(row) for row in tracker.to_dict(orient="records")]
    forward_live_rows = sum(flags == (True, False) for flags in flag_values)
    legacy_boundary_rows = sum(flags is None for flags in flag_values)
    policy_live = live
    if epoch_context["epoch"]["mode"] == "frozen_enforced" and epoch_context["state"] == "frozen_counting":
        policy_live = live[live["as_of"].map(_as_text) >= epoch_context["epoch"]["epoch_start_as_of"]].copy()
        if not _source_configuration_matches_epoch(policy_live, epoch_context["epoch"]):
            epoch_context = {**epoch_context, "state": "epoch_source_configuration_mismatch"}
        elif not _theme_references_within_epoch(
                policy_live, epoch_context["epoch"]["frozen_theme_ids"]):
            epoch_context = {**epoch_context, "state": "epoch_theme_family_mismatch"}
    admission_live, admission_rejected_cohorts = eligible_formal_cohorts(
        policy_live, int(governance["policy"]["top_n"]),
        require_decision_effective=False,
    )
    sealed_admission_as_ofs = set(admission_receipts or {}) \
        if epoch_context["state"] == "frozen_counting" else set()
    admission_weekly_as_ofs = set(_weekly_latest_as_ofs(
        [_as_text(value) for value in admission_live["as_of"] if _as_text(value)],
        sealed_admission_as_ofs,
    ))
    admission_live = admission_live[
        admission_live["as_of"].map(_as_text).isin(admission_weekly_as_ofs)
    ].copy()
    policy_live, rejected_cohorts = eligible_formal_cohorts(
        admission_live, int(governance["policy"]["top_n"])
    )
    rejected_cohorts = {**admission_rejected_cohorts, **rejected_cohorts}
    atomic_formal_rows = int(len(policy_live))
    policy_ready = policy_live.copy()
    admission_as_ofs = sorted({
        _as_text(value) for value in admission_live.get("as_of", pd.Series(dtype=str))
        if _as_text(value)
    })
    unadmitted_eligible_as_ofs = sorted(
        set(admission_as_ofs) - set(admission_receipts or {})
    ) if epoch_context["state"] == "frozen_counting" else []
    as_ofs = sorted({_as_text(value) for value in policy_live.get("as_of", pd.Series(dtype=str)) if _as_text(value)})
    policy = governance["policy"]
    if epoch_context["state"] == "frozen_counting":
        admitted_as_ofs, admission_mismatch = _validated_admission_receipt_as_ofs(
            admission_live, epoch_context["epoch"], int(policy["top_n"]), admission_receipts
        )
        if admission_mismatch:
            epoch_context = {**epoch_context, "state": "epoch_admission_receipt_mismatch"}
            policy_ready = policy_ready.iloc[0:0].copy()
        else:
            policy_ready = policy_ready[
                policy_ready["as_of"].map(_as_text).isin(admitted_as_ofs)
            ].copy()
    if epoch_context["state"] == "frozen_counting":
        receipt_as_ofs, receipt_mismatch = _validated_outcome_receipt_as_ofs(
            policy_ready, epoch_context["epoch"], int(policy["top_n"]),
            outcome_receipts, admission_receipts,
        )
        if receipt_mismatch:
            epoch_context = {**epoch_context, "state": "epoch_outcome_receipt_mismatch"}
            policy_ready = policy_ready.iloc[0:0].copy()
        else:
            policy_ready = policy_ready[policy_ready["as_of"].map(_as_text).isin(receipt_as_ofs)].copy()
    matured_primary_as_ofs = _weekly_matured_as_ofs(
        _matured_primary_as_ofs(policy_ready, int(policy["top_n"]))
    )
    epoch_clock_weeks = len(matured_primary_as_ofs) if epoch_context["state"] == "frozen_counting" else 0
    formal_due = epoch_context["state"] == "frozen_counting" and \
        epoch_context["epoch"]["formal_decision"]["status"] == "not_recorded" and \
        epoch_clock_weeks >= int(policy["formal_at_weeks"])
    formal_as_ofs = matured_primary_as_ofs[:int(policy["formal_at_weeks"])]
    decision_ready = (
        policy_ready[policy_ready["as_of"].map(_as_text).isin(formal_as_ofs)].copy()
        if formal_due else policy_ready
    )
    criteria = []
    for index, spec in enumerate(governance["criteria"]):
        result = _policy_result(decision_ready, spec, policy, index)
        result["criterion_id"] = spec["criterion_id"]
        criteria.append(result)
    criteria_by_id = {item["criterion_id"]: item for item in criteria}
    criteria = [criteria_by_id[criterion_id] for criterion_id in CRITERION_IDS]
    raw_p = [item["nonoverlap_h10_blocks"]["raw_two_sided_practical_p"] for item in criteria]
    for item, adjusted in zip(criteria, _holm_adjust(raw_p, family_size=len(CRITERION_IDS))):
        item["adjudication"]["holm_adjusted_two_sided_practical_p"] = adjusted
        item["adjudication"]["verdict"] = _formal_policy_verdict(
            item, policy, formal_due
        )
        if not formal_due and epoch_context["state"] == "frozen_counting":
            item["adjudication"]["verdict"] = (
                "preview_only" if epoch_clock_weeks >= int(policy["preview_at_weeks"])
                else "accumulating"
            )
        elif not formal_due and epoch_context["state"] != "audit_only_pre_freeze":
            item["adjudication"]["verdict"] = "evidence_blocked"
        if item["adjudication"]["verdict"] != "audit_only_pre_freeze":
            item["adjudication"]["reason"] = "frozen epoch statistical and deployability gate"
    negative_control = _negative_control(decision_ready, policy, len(criteria) + 1)
    negative_control["method_validity_status"] = _formal_negative_control_verdict(
        negative_control, policy, formal_due
    )
    if not formal_due and epoch_context["state"] == "frozen_counting":
        negative_control["method_validity_status"] = (
            "preview_only" if epoch_clock_weeks >= int(policy["preview_at_weeks"])
            else "accumulating"
        )
    elif not formal_due and epoch_context["state"] != "audit_only_pre_freeze":
        negative_control["method_validity_status"] = "evidence_blocked"
    replacement_evidence_blocked = (
        negative_control["method_validity_status"] == "unexpected_benefit_method_validity_warning" or
        negative_control["method_validity_status"].startswith("not_assessable_")
    )
    recorded_formal_summary = None
    if epoch_context["state"] == "frozen_counting" and \
            epoch_context["epoch"]["formal_decision"]["status"] == "recorded":
        expected_epoch = epoch_context["epoch"]
        if _recorded_formal_packet_matches(recorded_formal_packet, expected_epoch):
            criteria = copy.deepcopy(recorded_formal_packet["criteria"])
            negative_control = copy.deepcopy(recorded_formal_packet["negative_control"])
            replacement_evidence_blocked = bool(
                (recorded_formal_packet.get("receipt") or {}).get(
                    "replacement_evidence_blocked"
                )
            )
            recorded_formal_summary = {
                "status": "recorded",
                "as_of": expected_epoch["formal_decision"]["as_of"],
                "packet_sha256": expected_epoch["formal_decision"]["packet_sha256"],
                "criteria": copy.deepcopy(criteria),
                "negative_control": copy.deepcopy(negative_control),
            }
    packet = {
        "schema_name": "a_short_theme_forward_comparison",
        "schema_version": "2.0.0",
        "governance_fingerprint": _digest(governance),
        "comparison_boundary": {
            "forward_live_only": True,
            "historical_replay_counting": False,
            "return_window_trading_days": RETURN_WINDOW_DAYS,
            "return_unit": RETURN_UNIT,
            "automatic_promotion": False,
            "activation_authorized": False,
            "changes_official_star_risk_action_or_cash": False,
            "policy_verdict_is_historical_evidence_only": True,
        },
        "adjudication_mode": epoch_context["state"],
        "formal_verdict_allowed": formal_due,
        "recorded_formal_decision": recorded_formal_summary,
        "tracker_rows_total": all_rows,
        "forward_live_rows_counted": int(len(policy_live)),
        "excluded_non_live_or_replay_rows": all_rows - forward_live_rows,
        "excluded_legacy_boundary_rows": legacy_boundary_rows,
        "excluded_atomic_cohort_rows": forward_live_rows - atomic_formal_rows,
        "rejected_atomic_cohorts": rejected_cohorts,
        "eligible_unadmitted_cohorts": unadmitted_eligible_as_ofs,
        "excluded_unavailable_industry_rows": sum(
            "industry_trend" in reason for reason in rejected_cohorts.values()
        ),
        "excluded_legacy_missing_analysis_role_rows": int(
            (live["analysis_role"].map(_as_text) == "").sum()
        ),
        "excluded_missing_return_unit_rows": int(
            (live[RETURN_UNIT_COLUMN].map(_as_text) != RETURN_UNIT).sum()
        ),
        "latest_evidence_as_of": admission_as_ofs[-1] if admission_as_ofs else None,
        "forward_live_weeks": len(as_ofs),
        "matured_primary_h10_weeks": len(matured_primary_as_ofs),
        "epoch_clock_weeks": epoch_clock_weeks,
        "checkpoints": {
            "preview_at_weeks": int(policy["preview_at_weeks"]),
            "formal_at_weeks": int(policy["formal_at_weeks"]),
            "formal_decision_as_of": formal_as_ofs[-1] if formal_due else None,
            "current_checkpoint": (epoch_context["state"] if epoch_context["state"] in {
                                       "epoch_contract_mismatch", "epoch_identity_mismatch",
                                       "epoch_source_configuration_mismatch", "epoch_mode_mismatch",
                                       "epoch_theme_family_mismatch",
                                       "epoch_admission_receipt_mismatch",
                                       "epoch_outcome_receipt_mismatch", "epoch_formal_decision_mismatch",
                                   }
                                   else "formal_decision_recorded" if epoch_context["epoch"]["formal_decision"]["status"] == "recorded"
                                   else "formal_decision_due" if formal_due
                                   else "formal_boundary_reached_audit_only" if len(matured_primary_as_ofs) >= int(policy["formal_at_weeks"])
                                   else "preview_only" if len(matured_primary_as_ofs) >= int(policy["preview_at_weeks"])
                                   else "accumulating"),
        },
        "criteria": criteria,
        "negative_control": negative_control,
        "exploratory_themes": _theme_groups(
            decision_ready, policy,
            epoch_context["epoch"]["frozen_theme_ids"] if epoch_context["state"] == "frozen_counting" else None,
        ),
        "receipt": {
            "next_action": "separate_reviewed_activation_route_required",
            "production_replacement_recommendation": False,
            "replacement_evidence_blocked": replacement_evidence_blocked,
            "replacement_evidence_block_reason": _replacement_evidence_block_reason(
                _as_text(negative_control["method_validity_status"])
            ),
            "p4a_modified": False,
        },
        "epoch": {
            "mode": epoch_context["epoch"]["mode"],
            "epoch_id": epoch_context["epoch"]["epoch_id"],
            "epoch_start_as_of": epoch_context["epoch"]["epoch_start_as_of"],
            "contract_fingerprint": epoch_context["epoch"]["contract_fingerprint"],
            "freeze_packet_identity": epoch_context["epoch"]["freeze_packet_identity"],
            "formal_decision": epoch_context["epoch"]["formal_decision"],
        },
    }
    validate_comparison_packet(packet)
    return packet
