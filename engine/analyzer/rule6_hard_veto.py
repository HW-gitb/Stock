"""Phase 3 deterministic hard-veto rules.

The public entry point is :func:`run_veto`. It accepts either a nested
``analysis_input.json`` candidate dict or a flattened rank-backtest row.
Missing or unparsable values produce diagnostics, not hard vetoes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


RULE_VERSIONS = {
    "chasing_high": 1,
    "overheat": 1,
    "l2_unknown": 1,
    "esp_non_positive": 1,
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
    rules = _normalize_rules(enabled_rules)
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


def _normalize_rules(enabled_rules) -> tuple[str, ...]:
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
    value = _first_present(candidate, [
        "chasing_high",
        "derived_flags.chasing_high",
    ])
    if value is not MISSING:
        parsed = _parse_bool(value)
        if parsed is True:
            return _reason("chasing_high", _last_field(candidate), value), diagnostics
        if parsed is None:
            diagnostics.append(_diag("chasing_high", _last_field(candidate), "data_unparseable", value))

    entry = _first_present(candidate, [
        "entry_flag",
        "entry_flag_group",
        "selection.entry_flag",
    ])
    if entry is not MISSING:
        text = str(entry)
        if "追高风险" in text:
            return _reason("chasing_high", _last_field(candidate), entry), diagnostics
        return None, diagnostics

    diagnostics.append(_diag("chasing_high", "chasing_high|selection.entry_flag", "data_missing"))
    return None, diagnostics


def _check_overheat(candidate: Mapping[str, Any]):
    diagnostics = []
    value = _first_present(candidate, [
        "overheat_flag",
        "derived_flags.overheat_flag",
    ])
    if value is not MISSING:
        parsed = _parse_bool(value)
        if parsed is True:
            return _reason("overheat", _last_field(candidate), value), diagnostics
        if parsed is None:
            diagnostics.append(_diag("overheat", _last_field(candidate), "data_unparseable", value))

    flag = _first_present(candidate, [
        "l4_flag",
        "l4_flag_group",
        "scores.l4_flag",
    ])
    if flag is not MISSING:
        text = str(flag).upper()
        if "OVERHEAT" in text:
            return _reason("overheat", _last_field(candidate), flag), diagnostics
        return None, diagnostics

    diagnostics.append(_diag("overheat", "overheat_flag|scores.l4_flag", "data_missing"))
    return None, diagnostics


def _check_l2_unknown(candidate: Mapping[str, Any]):
    value = _first_present(candidate, [
        "l2_name",
        "industry.sw_l2_name",
    ])
    if value is MISSING:
        return None, [_diag("l2_unknown", "l2_name|industry.sw_l2_name", "data_missing")]
    text = str(value).strip()
    if text.lower() in {"未知", "unknown", "unk"}:
        return _reason("l2_unknown", _last_field(candidate), value), []
    return None, []


def _check_esp_non_positive(candidate: Mapping[str, Any]):
    value = _first_present(candidate, [
        "esp_raw",
        "fundamental.expectation.esp_raw",
    ])
    if value is MISSING:
        return None, [_diag("esp_non_positive", "esp_raw|fundamental.expectation.esp_raw", "data_missing")]
    parsed = _parse_float(value)
    if parsed is None:
        return None, [_diag("esp_non_positive", _last_field(candidate), "data_unparseable", value)]
    if parsed <= 0:
        return _reason("esp_non_positive", _last_field(candidate), value), []
    return None, []


def _first_present(candidate: Mapping[str, Any], paths: list[str]) -> Any:
    for path in paths:
        value = _get_path(candidate, path)
        if value is not MISSING and not _is_missing_value(value):
            _first_present.last_field = path
            return value
    _first_present.last_field = paths[0] if paths else ""
    return MISSING


def _last_field(_candidate: Mapping[str, Any]) -> str:
    return getattr(_first_present, "last_field", "")


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
    try:
        # Handles pandas.NA / numpy.nan without importing pandas.
        return bool(value != value)
    except Exception:
        return False


def _jsonable(value: Any) -> Any:
    if _is_missing_value(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)

