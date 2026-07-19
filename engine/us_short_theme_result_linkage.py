# -*- coding: utf-8 -*-
"""US-short Cut3 theme facts and lifecycle effects on the formal result chain."""
from __future__ import annotations

import hashlib
import json

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_result_effects import SOFT_RISK_CONFIDENCE_CAP, extend_result_effects
from engine.us_short_theme_lifecycle import THEME_STATES, lifecycle_effects
from engine.us_short_theme_selection import THEME_SOURCES


class ThemeResultLinkageError(ValueError):
    """Theme identity/reconciliation/effect data cannot be safely linked to official rows."""


_HOLDING_RECON_KEYS = {"schema_name", "schema_version", "as_of", "positions"}
_HOLDING_ROW_KEYS = {
    "ticker", "theme_id", "theme_source", "theme_lifecycle_state", "macro_cluster", "evidence_ref",
}
_IDENTITY_KEYS = ("theme_source", "theme_lifecycle_state", "macro_cluster")
_PROVENANCE_KEYS = {
    "as_of", "observed_at", "price_basis_date", "session", "adjustment", "row_count", "source_refs",
}


def _nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def _clean_theme_id(value, where):
    if not _nonblank(value):
        raise ThemeResultLinkageError(f"{where} 须为非空 str")
    return value.strip().casefold()


def _evidence_ref(value, *, as_of, where):
    if not (isinstance(value, dict) and set(value) == {"kind", "value", "as_of"}
            and value.get("kind") in {"provider row", "SEC filing", "source_id"}
            and _nonblank(value.get("value")) and value.get("as_of") == as_of):
        raise ThemeResultLinkageError(f"{where}.evidence_ref 非法或未绑定本次 decision_date")
    return {"kind": value["kind"], "value": value["value"].strip(), "as_of": as_of}


def _holding_theme_map(account_state, *, decision_date):
    positions = account_state.get("positions") if isinstance(account_state, dict) else None
    if not isinstance(positions, list):
        raise ThemeResultLinkageError("account_state.positions 须为 list")
    account_tickers = set()
    for position in positions:
        ticker = canonical_us_ticker(position.get("ticker")) if isinstance(position, dict) else None
        if ticker is None or ticker in account_tickers:
            raise ThemeResultLinkageError("account_state.positions 含非法/重复 ticker")
        account_tickers.add(ticker)
    reconciliation = account_state.get("holding_theme_reconciliation")
    if reconciliation is None:
        return {}, not account_tickers
    if not (isinstance(reconciliation, dict) and set(reconciliation) == _HOLDING_RECON_KEYS
            and reconciliation.get("schema_name") == "us_short_holding_theme_reconciliation"
            and reconciliation.get("schema_version") == "1.0.0"
            and reconciliation.get("as_of") == decision_date
            and isinstance(reconciliation.get("positions"), list)):
        raise ThemeResultLinkageError("holding_theme_reconciliation 顶层契约非法")
    out = {}
    for raw in reconciliation["positions"]:
        if not isinstance(raw, dict) or set(raw) != _HOLDING_ROW_KEYS:
            raise ThemeResultLinkageError("holding_theme_reconciliation.positions[] 字段漂移")
        ticker = canonical_us_ticker(raw["ticker"])
        if ticker is None or ticker in out:
            raise ThemeResultLinkageError("holding_theme_reconciliation 含非法/重复 ticker")
        source, lifecycle = raw["theme_source"], raw["theme_lifecycle_state"]
        if source not in THEME_SOURCES or lifecycle not in THEME_STATES:
            raise ThemeResultLinkageError(f"{ticker}: holding theme source/lifecycle 非法")
        if not _nonblank(raw["macro_cluster"]):
            raise ThemeResultLinkageError(f"{ticker}: holding macro_cluster 须为非空 str")
        out[ticker] = {
            "theme_id": _clean_theme_id(raw["theme_id"], f"{ticker}.theme_id"),
            "theme_source": source,
            "theme_lifecycle_state": lifecycle,
            "macro_cluster": raw["macro_cluster"].strip().casefold(),
            "evidence_ref": _evidence_ref(raw["evidence_ref"], as_of=decision_date, where=ticker),
        }
    if set(out) != account_tickers:
        raise ThemeResultLinkageError("holding_theme_reconciliation 必须恰覆盖账户持仓")
    return out, True


def _selection_provenance_digest(value, *, decision_date):
    if not (isinstance(value, dict) and set(value) == _PROVENANCE_KEYS
            and value.get("as_of") == decision_date
            and isinstance(value.get("observed_at"), str) and value["observed_at"].strip()
            and value.get("price_basis_date") is None and value.get("session") is None
            and value.get("adjustment") is None
            and isinstance(value.get("row_count"), int) and not isinstance(value["row_count"], bool)
            and value["row_count"] >= 0 and isinstance(value.get("source_refs"), list)
            and value["source_refs"]):
        raise ThemeResultLinkageError("selection_inputs run_provenance family 非法/未绑定本轮")
    for ref in value["source_refs"]:
        if not (isinstance(ref, dict) and set(ref) == {"role", "path"}
                and _nonblank(ref.get("role")) and _nonblank(ref.get("path"))):
            raise ThemeResultLinkageError("selection_inputs run_provenance source_ref 非法")
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def bind_theme_contexts(selection, rows, *, account_state, decision_date, selection_input_provenance):
    """Carry selected theme facts to rows and reconcile, but do not force holdings into the candidate contract.

    Returns ``(rows, holding_theme_complete)``.  A missing holding reconciliation yields ``theme_context=None``
    only for holding-only rows; later capacity/macro stages must then block new capacity while protective exits
    continue.  A present but malformed or conflicting reconciliation fails closed.
    """
    if not (isinstance(selection, dict) and isinstance(selection.get("selection_details"), list)
            and isinstance(rows, list)):
        raise ThemeResultLinkageError("selection/rows 形状非法")
    digest = selection.get("theme_contract_digest")
    if not (isinstance(digest, str) and len(digest) == 64
            and all(ch in "0123456789abcdef" for ch in digest)):
        raise ThemeResultLinkageError("selection 缺 theme contract sha256 digest")
    provenance_digest = _selection_provenance_digest(
        selection_input_provenance, decision_date=decision_date)
    selected = {}
    for detail in selection["selection_details"]:
        ticker = canonical_us_ticker(detail.get("ticker")) if isinstance(detail, dict) else None
        theme = detail.get("theme_selection") if isinstance(detail, dict) else None
        if ticker is None or ticker in selected or not isinstance(theme, dict):
            raise ThemeResultLinkageError("selection_details theme identity 非法/重复")
        if not _nonblank(theme.get("macro_cluster")):
            raise ThemeResultLinkageError(f"{ticker}: 候选缺 macro_cluster 来源事实")
        selected[ticker] = {
            **theme,
            "theme_id": _clean_theme_id(theme.get("theme_id"), f"{ticker}.theme_id"),
            "macro_cluster": theme["macro_cluster"].strip().casefold(),
            "evidence_ref": {
                "kind": "source_id",
                "value": (f"theme_selection_contract:sha256:{digest}:"
                          f"run_provenance:sha256:{provenance_digest}:ticker:{ticker}"),
                "as_of": decision_date,
            },
        }
    holding_map, complete = _holding_theme_map(account_state, decision_date=decision_date)

    # A theme id denotes one fact identity for the run, regardless of whether it arrived through candidate
    # selection or the private holding reconciliation.
    identity = {}
    for source_map in (selected, holding_map):
        for ticker, theme in source_map.items():
            key = theme["theme_id"]
            value = tuple(theme[field] for field in _IDENTITY_KEYS)
            prior = identity.get(key)
            if prior is not None and prior != value:
                raise ThemeResultLinkageError(
                    f"same theme_id {key!r} has conflicting source/lifecycle/macro identity")
            identity[key] = value
            if ticker in selected and ticker in holding_map:
                selected_value = tuple(selected[ticker][field] for field in _IDENTITY_KEYS)
                holding_value = tuple(holding_map[ticker][field] for field in _IDENTITY_KEYS)
                if selected[ticker]["theme_id"] != holding_map[ticker]["theme_id"] or selected_value != holding_value:
                    raise ThemeResultLinkageError(f"{ticker}: candidate/holding theme reconciliation conflict")

    out, seen = [], set()
    for row in rows:
        ticker = canonical_us_ticker(row.get("ticker")) if isinstance(row, dict) else None
        if ticker is None or ticker in seen:
            raise ThemeResultLinkageError("analysis rows 含非法/重复 ticker")
        seen.add(ticker)
        theme = selected.get(ticker)
        carried = row.get("selection_theme")
        if theme is not None:
            expected_carried = {key: value for key, value in theme.items() if key != "evidence_ref"}
            if not isinstance(carried, dict) or carried != expected_carried:
                raise ThemeResultLinkageError(f"{ticker}: _build_analysis_rows 未原样保留 selection theme")
        if theme is None and row.get("row_source") in {
            "holding_in_top15", "holding_pass2_only", "holding_account_only",
        }:
            theme = holding_map.get(ticker)
        if row.get("row_source") in {"top15_candidate", "holding_in_top15"} and theme is None:
            raise ThemeResultLinkageError(f"{ticker}: Top15 候选缺 source-bound theme facts")
        clean_row = {key: value for key, value in row.items() if key != "selection_theme"}
        out.append({**clean_row, "ticker": ticker,
                    "theme_context": dict(theme) if theme is not None else None})
    return out, complete


def apply_theme_lifecycle_effects(result, *, as_of):
    """Translate non-neutral lifecycle facts into the existing Cut2 result-effects reducer."""
    effects_by_ticker = {}
    for row in result.get("rows", []) if isinstance(result, dict) else []:
        ticker = row.get("ticker") if isinstance(row, dict) else None
        if not _nonblank(ticker):
            raise ThemeResultLinkageError("result row 缺 ticker")
        theme = row.get("theme_context")
        records = []
        if theme is not None:
            if not isinstance(theme, dict) or theme.get("theme_lifecycle_state") not in THEME_STATES:
                raise ThemeResultLinkageError(f"{ticker}: theme_context lifecycle 非法")
            state = theme["theme_lifecycle_state"]
            evidence = _evidence_ref(theme.get("evidence_ref"), as_of=as_of, where=ticker)
            governed = lifecycle_effects(state)
            is_holding = row.get("row_context") == "holding"
            tags, invalid, override, cap = [], [], None, None
            if is_holding:
                holding = governed["holding_effects"]
                if holding["mechanical_clear"]:
                    raise ThemeResultLinkageError("theme lifecycle must never mechanically clear a holding")
                if holding["theme_decay_tag"]:
                    tags.append("theme_decay:" + state)
                if holding["section9_reeval"]:
                    invalid.append("theme_lifecycle_section9_reeval")
                if holding["action_confidence_down"]:
                    cap = SOFT_RISK_CONFIDENCE_CAP
            elif governed["new_entry_routing"] in {"observe", "blocked_from_theme"}:
                tags.append("theme_decay:" + state)
                invalid.append("theme_lifecycle_blocks_new_entry:" + state)
                if row.get("final_action") == "建仓":
                    override = {"final_action": "观察", "observe_reason_type": "signal_not_ready"}
            if tags or invalid or override is not None or cap is not None:
                records.append({
                    "source": "theme_lifecycle:" + state,
                    "evidence_ref": evidence,
                    "risk_tags": tags,
                    "trigger_conditions": [],
                    "invalid_conditions": invalid,
                    "size_multiplier": None,
                    "confidence_cap": cap,
                    "action_override": override,
                })
        effects_by_ticker[ticker] = records
    return extend_result_effects(result, effects_by_ticker=effects_by_ticker, as_of=as_of)
