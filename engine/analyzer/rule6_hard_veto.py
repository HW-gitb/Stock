"""Phase 3 deterministic hard-veto rules.

The public entry point is :func:`run_veto`. It accepts either a nested
``analysis_input.json`` candidate dict or a flattened rank-backtest row.
Missing or unparsable values produce diagnostics, not hard vetoes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


RULE_VERSIONS = {
    "chasing_high": 1,
    "overheat": 1,
    "l2_unknown": 1,
    "esp_non_positive": 2,
}

DEFAULT_RULES = tuple(RULE_VERSIONS.keys())
HARD = "hard"
MISSING = object()


def run_veto(candidate_dict: Mapping[str, Any], enabled_rules=None) -> dict[str, Any]:
    """Return the hard-veto decision for one candidate.

    Args:
        candidate_dict: Nested analysis candidate or flattened backtest row.
        enabled_rules: Optional iterable of rule codes. Unknown codes raise
            ValueError because misspelled ablation flags would corrupt stats.
    """
    rules = normalize_rules(enabled_rules)
    reasons: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    checks = {
        "chasing_high": _check_chasing_high,
        "overheat": _check_overheat,
        "l2_unknown": _check_l2_unknown,
        "esp_non_positive": _check_esp_non_positive,
    }
    for code in rules:
        reason, diag = checks[code](candidate_dict)
        if reason:
            reasons.append(reason)
        diagnostics.extend(diag)

    return {
        "vetoed": bool(reasons),
        "reasons": reasons,
        "diagnostics": diagnostics,
        "enabled_rules": list(rules),
    }


def normalize_rules(enabled_rules) -> tuple[str, ...]:
    """Public API: parse and validate a rule list.

    Accepts None (returns DEFAULT_RULES), a comma-separated str, or an
    iterable of code strings. Raises ValueError on any unknown rule code.
    Used both internally by run_veto and externally by CLI parsers in
    runners/backtest_rank.py to fail fast on misspelled flags.
    """
    if enabled_rules is None:
        return DEFAULT_RULES
    if isinstance(enabled_rules, str):
        parts = [p.strip() for p in enabled_rules.split(",") if p.strip()]
    else:
        parts = [str(p).strip() for p in enabled_rules if str(p).strip()]
    unknown = sorted(set(parts) - set(RULE_VERSIONS))
    if unknown:
        raise ValueError(f"unknown veto rule(s): {', '.join(unknown)}")
    return tuple(parts)


# Backwards-compat private alias; older imports may reference _normalize_rules.
_normalize_rules = normalize_rules


def _reason(code: str, field: str, value: Any) -> dict[str, Any]:
    return {
        "code": code,
        "version": RULE_VERSIONS[code],
        "severity": HARD,
        "detail": {
            "field": field,
            "value": _jsonable(value),
        },
    }


def _diag(code: str, field: str, status: str, value: Any = None) -> dict[str, Any]:
    out = {
        "code": code,
        "version": RULE_VERSIONS[code],
        "severity": "diagnostic",
        "status": status,
        "field": field,
    }
    if value is not None:
        out["value"] = _jsonable(value)
    return out


def _check_chasing_high(candidate: Mapping[str, Any]):
    diagnostics = []
    bool_paths = ["chasing_high", "derived_flags.chasing_high"]
    value, field = _first_present(candidate, bool_paths)
    if value is not MISSING:
        parsed = _parse_bool(value)
        if parsed is True:
            return _reason("chasing_high", field, value), diagnostics
        if parsed is None:
            diagnostics.append(_diag("chasing_high", field, "data_unparseable", value))

    entry_paths = ["entry_flag", "entry_flag_group", "selection.entry_flag"]
    entry, entry_field = _first_present(candidate, entry_paths)
    if entry is not MISSING:
        if "追高风险" in str(entry):
            return _reason("chasing_high", entry_field, entry), diagnostics
        return None, diagnostics

    diagnostics.append(_diag("chasing_high", "|".join(bool_paths + entry_paths), "data_missing"))
    return None, diagnostics


def _check_overheat(candidate: Mapping[str, Any]):
    diagnostics = []
    bool_paths = ["overheat_flag", "derived_flags.overheat_flag"]
    value, field = _first_present(candidate, bool_paths)
    if value is not MISSING:
        parsed = _parse_bool(value)
        if parsed is True:
            return _reason("overheat", field, value), diagnostics
        if parsed is None:
            diagnostics.append(_diag("overheat", field, "data_unparseable", value))

    flag_paths = ["l4_flag", "l4_flag_group", "scores.l4_flag"]
    flag, flag_field = _first_present(candidate, flag_paths)
    if flag is not MISSING:
        # Token match, not substring. Substring would falsely match labels like
        # "NO_OVERHEAT" or "OVERHEAT_CLEARED" if EGS ever extends the flag
        # vocabulary. Tokens are pipe/comma/space-separated per existing
        # backtest_rank.has_l4_overheat convention.
        tokens = {t.strip().upper() for t in re.split(r"[|,\s]+", str(flag)) if t.strip()}
        if "OVERHEAT" in tokens:
            return _reason("overheat", flag_field, flag), diagnostics
        return None, diagnostics

    diagnostics.append(_diag("overheat", "|".join(bool_paths + flag_paths), "data_missing"))
    return None, diagnostics


# Treat these literals as "industry name explicitly unknown".
# Backtest's build_group_columns has historically also flagged "" as unknown
# for downstream stats coverage, but the analyzer stays stricter: missing or
# empty strings are not equivalent to an explicit "未知" label and must not
# trigger a hard veto. See Phase 3 spec §3: "missing 不等于 negative".
_L2_UNKNOWN_LITERALS_CJK = {"未知"}
_L2_UNKNOWN_LITERALS_ASCII = {"unknown", "unk"}


def _check_l2_unknown(candidate: Mapping[str, Any]):
    paths = ["l2_name", "industry.sw_l2_name"]
    value, field = _first_present(candidate, paths)
    if value is MISSING:
        return None, [_diag("l2_unknown", "|".join(paths), "data_missing")]
    text = str(value).strip()
    if not text:
        # Empty / whitespace-only string is data_missing, not an explicit
        # "未知" label. _is_missing_value only catches None / NaN, so the
        # empty-string case is filtered here.
        return None, [_diag("l2_unknown", field, "data_missing", value)]
    if text in _L2_UNKNOWN_LITERALS_CJK or text.lower() in _L2_UNKNOWN_LITERALS_ASCII:
        return _reason("l2_unknown", field, value), []
    return None, []


def _check_esp_non_positive(candidate: Mapping[str, Any]):
    paths = ["esp_raw", "fundamental.expectation.esp_raw"]
    value, field = _first_present(candidate, paths)
    if value is MISSING:
        return None, [_diag("esp_non_positive", "|".join(paths), "data_missing")]
    parsed = _parse_float(value)
    if parsed is None:
        return None, [_diag("esp_non_positive", field, "data_unparseable", value)]
    # float("nan") parses successfully but every comparison is False; treat as
    # data_unparseable so the diagnostic surfaces instead of silently dropping.
    if parsed != parsed:
        return None, [_diag("esp_non_positive", field, "data_unparseable", value)]
    if parsed < 0:
        return _reason("esp_non_positive", field, value), []
    if parsed == 0:
        return None, [_diag("esp_non_positive", field, "neutral_zero_not_vetoed", value)]
    return None, []


def _first_present(candidate: Mapping[str, Any], paths: list[str]) -> tuple[Any, str]:
    """Return (value, path) for the first path that resolves to a real value.

    Returns (MISSING, "") if no path resolves. The path is returned alongside
    the value so reasons/diagnostics can record exactly which field fired —
    previously this was stored on a function attribute (implicit global state).
    """
    for path in paths:
        value = _get_path(candidate, path)
        if value is not MISSING and not _is_missing_value(value):
            return value, path
    return MISSING, ""


def _get_path(obj: Mapping[str, Any], path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if isinstance(cur, Mapping):
            if part not in cur:
                return MISSING
            cur = cur[part]
            continue
        if hasattr(cur, "get"):
            cur = cur.get(part, MISSING)
            if cur is MISSING:
                return MISSING
            continue
        return MISSING
    return cur


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    # Numeric 0/1 (and 0.0/1.0) — these flow through when pandas auto-converts
    # bool-like columns to numeric. Order matters: bool must be checked before
    # int because `True` is `isinstance(True, int)`.
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _parse_float(value: Any) -> float | None:
    try:
        # pandas.NA raises TypeError on float().
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    # NaN check: NaN != NaN is the canonical detection. Works for float('nan')
    # and numpy.nan directly. For pandas.NA / pd.NaT the comparison returns
    # NA which raises TypeError on bool(); we catch that and explicitly treat
    # NA-like sentinels as missing (the prior `return False` here was a latent
    # bug — pd.NA would slip through as a "present" value).
    try:
        is_nan = bool(value != value)
        return is_nan
    except TypeError:
        # pd.NA, pd.NaT, and similar sentinels raise TypeError on bool(). They
        # all represent missing values; return True.
        return True
    except Exception:
        return False


def _jsonable(value: Any) -> Any:
    if _is_missing_value(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
