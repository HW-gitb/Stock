#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""US-short manual tables -> us_short_account_state.json converter (batch 1, slice 1a).

Converts the user's locally maintained CSV tables (account / positions / optional trades / optional
holding_themes) into
`schemas/us_short_account_state.schema.json` v1.0.0, to be consumed (later) by the US-short
weekly report for holdings re-evaluation. Slice 1a built the account + positions input; slice 1b
adds the optional trades.csv (= §12 manual_actual_track / execution log) and an advisory
trades<->positions reconcile whose WARN-only result lands in the lineage sidecar (never overrides
positions). Cut3 adds holding_themes.csv as the private, exact-coverage source for holding theme/lifecycle/macro
facts; omitting it preserves protective exits but makes new theme/macro capacity unavailable.

Design boundaries (us_short_system_design §3.6 / §1 / §8 / §11.6 / §18):
- US-short OWN schema (not the A-share a_short_account_state); US tickers, NOT A-share codes; no
  A-share Rule12/Rule13 fields (US portfolio_guard / symbol_cooldown are paper-track / fill driven
  and derived later, not manual input). Does NOT cross A-share code/state/paths.
- v1 long-only: every position gets direction=long (the §1 marked door). No short logic.
- US-short bucket capital = us_market_equity / 3 (the system computes it; never guesses from a
  vague total). The (bucket == equity/3) cross-field invariant is enforced by validate_account_state.
- CSV is canonical input: diffable, testable, no openpyxl dependency, and the explicit parsers reject
  Excel coercions ("1000.0" / dropped leading zeros / date objects). Any malformed / out-of-contract
  input is FATAL (fail-fast, never silently degrade account state).
- Privacy (§11.6 / §18.0 P0 fail-closed guard): the output state + lineage carry real holdings/cost/
  cash, so they are refused on any in-repo path that `git check-ignore` does not ignore (fail-closed;
  also fail-closed if git cannot verify) AND on any relative / CWD-dependent path (pass an ABSOLUTE path —
  inside the gitignored state/us_short/ dir, or an external private location).
- NO broker / no order / no market fetch / no real-money automation.

Usage (--out / --lineage-out MUST be ABSOLUTE — the §11.6 / §18.0 privacy guard rejects a relative /
CWD-dependent path; use an absolute path inside the gitignored state/us_short/ dir, or an external private
location. --input-dir may stay relative. `--as-of` and `--price-basis-date` must come from the same
capstone dry-run's `decision_date` and `price_basis_date`; the dates below are placeholders only):
    python runners/us_short_account_state_from_manual_tables.py \
        --input-dir state/us_short/account_state_csv --as-of 20260622 \
        --price-basis-date 20260619 \
        --out <ABSOLUTE_PRIVATE_DIR>/us_short_account_state.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_eligibility_gate import canonical_us_ticker  # noqa: E402 — the repo's SINGLE US identity policy
from engine.us_short_holding_action import MAX_MANUAL_HOLDING_SHARES  # noqa: E402 — shared first-cut quantity ceiling
from engine.us_short_theme_lifecycle import THEME_STATES  # noqa: E402
from engine.us_short_theme_selection import THEME_SOURCES  # noqa: E402

ACCOUNT_SCHEMA_NAME = "us_short_account_state"
ACCOUNT_SCHEMA_VERSION = "1.0.0"
LINEAGE_SCHEMA_NAME = "us_short_account_state_lineage"
LINEAGE_SCHEMA_VERSION = "1.1.0"
BUCKET_DIVISOR = 3  # per-market capital policy: US-short bucket = us_market_equity / 3
_REL_EPS = 1e-9

ACCOUNT_SCHEMA_PATH = ROOT / "schemas" / "us_short_account_state.schema.json"
LINEAGE_SCHEMA_PATH = ROOT / "schemas" / "us_short_account_state_lineage.schema.json"

REQUIRED_TABLES = ("account", "positions")
OPTIONAL_TABLES = ("trades", "holding_themes")

REQUIRED_COLUMNS = {
    "account": ("as_of", "us_market_equity", "us_short_available_cash",
                "manual_order_only", "broker_connection_allowed"),
    "positions": ("ticker", "shares", "avg_cost_usd", "entry_date"),
    "trades": ("decision_date", "ticker", "suggested_action", "executed"),
    "holding_themes": ("as_of", "ticker", "theme_id", "theme_source", "theme_lifecycle_state",
                       "macro_cluster", "evidence_ref_kind", "evidence_ref_value"),
}
# Allowed columns (required + optional). Any column OUTSIDE this set is rejected (fail-fast, no silent
# drop): a typo'd / out-of-contract column — e.g. `direction=short` in positions, which v1 long-only
# would otherwise silently emit as `direction=long` and misstate a short as a long holding — must
# surface, not be ignored. This is the structural twin of the strict (anti-Excel-coercion) value parse.
EXPECTED_COLUMNS = {
    "account": ("as_of", "us_market_equity", "us_short_available_cash", "portfolio_total_equity",
                "manual_order_only", "broker_connection_allowed"),
    "positions": ("ticker", "shares", "avg_cost_usd", "entry_date", "current_stop", "notes"),
    "trades": ("decision_date", "ticker", "suggested_action", "executed",
               "fill_price", "fill_shares", "skip_reason", "manual_override", "failure_trigger"),
    "holding_themes": ("as_of", "ticker", "theme_id", "theme_source", "theme_lifecycle_state",
                       "macro_cluster", "evidence_ref_kind", "evidence_ref_value"),
}

# trades.suggested_action = the §9 final_action vocab (user-chosen 2026-06-20, Chinese values).
# Reconcile maps buy/sell direction; the execution log stores the action verbatim.
TRADE_BUY_ACTIONS = ("建仓", "加仓")
TRADE_SELL_ACTIONS = ("减仓", "清仓-止损", "清仓-止盈", "清仓-事件")
TRADE_NOFILL_ACTIONS = ("持有", "观察", "否决/避开")   # design-exact §9 values (no `否决` alias)
TRADE_ACTIONS = TRADE_BUY_ACTIONS + TRADE_SELL_ACTIONS + TRADE_NOFILL_ACTIONS

# US listing-symbol acceptance is delegated to engine `canonical_us_ticker` (single identity policy). Only the
# A-share pattern is kept here, ONLY to sharpen `_parse_us_ticker`'s diagnostic (not to make the accept/reject).
_A_SHARE_CODE_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$", re.IGNORECASE)


class ConvertError(SystemExit):
    """FATAL conversion error (fail-fast; never silently degrade account state)."""

    def __init__(self, msg: str):
        super().__init__(f"[FATAL] {msg}")


# -- explicit parsing (reject Excel coercion / dirty input; CSV gets the same strict parse) ----------
def _parse_date(raw, field: str) -> str:
    s = ("" if raw is None else str(raw)).strip()
    if not re.fullmatch(r"\d{8}", s):
        raise ConvertError(f"{field}={raw!r} is not 8-digit YYYYMMDD text (Excel may have coerced it to a number/date/dropped a leading zero)")
    try:
        datetime.strptime(s, "%Y%m%d")
    except ValueError:
        raise ConvertError(f"{field}={raw!r} is not a real calendar date")
    return s


def _parse_optional_date(raw, field: str):
    s = ("" if raw is None else str(raw)).strip()
    return None if s == "" else _parse_date(s, field)


def _parse_bool(raw, field: str) -> bool:
    s = ("" if raw is None else str(raw)).strip().lower()
    if s == "true":
        return True
    if s == "false":
        return False
    raise ConvertError(f"{field}={raw!r} must be TRUE/FALSE (not 1/0/yes/no, to avoid Excel coercion ambiguity)")


def _parse_float(raw, field: str, *, positive=False, allow_zero=True):
    s = ("" if raw is None else str(raw)).strip()
    if s == "":
        raise ConvertError(f"{field} is missing (required numeric)")
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        # plain decimal only — reject scientific notation (1e3), Python underscores (1_8 -> 18),
        # thousands separators (1,800), inf/nan: all are Excel/Python coercion vectors the strict
        # input contract must not silently accept (docstring: "reject Excel coercions").
        raise ConvertError(f"{field}={raw!r} is not a plain decimal number (no scientific notation / underscore / thousands separator / inf/nan)")
    v = float(s)
    if not math.isfinite(v):   # defensive; the regex already excludes inf/nan/exponent/underscore
        raise ConvertError(f"{field}={raw!r} is not finite (NaN/Inf rejected)")
    if positive and v <= 0:
        raise ConvertError(f"{field}={raw!r} must be > 0")
    if not allow_zero and v == 0:
        raise ConvertError(f"{field}={raw!r} must not be 0")
    return v


def _parse_optional_float(raw, field: str, **kwargs):
    s = ("" if raw is None else str(raw)).strip()
    return None if s == "" else _parse_float(s, field, **kwargs)


def _parse_int_shares(raw, field: str) -> int:
    s = ("" if raw is None else str(raw)).strip()
    if not re.fullmatch(r"\d+", s):
        raise ConvertError(f"{field}={raw!r} must be a positive integer share count (no decimals/scientific notation, to avoid Excel int->float coercion)")
    v = int(s)
    if v <= 0:
        raise ConvertError(f"{field}={raw!r} must be > 0")
    if v > MAX_MANUAL_HOLDING_SHARES:
        raise ConvertError(f"{field} exceeds the maximum supported manual holding share count")
    return v


def _parse_us_ticker(raw, field: str) -> str:
    # SINGLE US identity policy: delegate accept/reject to the engine `canonical_us_ticker` (ASCII-only, so a
    # non-ASCII key that `.upper()` would fold into a fake ticker — 'ſ'->'S' — is rejected; A-share codes + non-US
    # shapes rejected). This converter must NOT keep a divergent second policy
    # (R-USSHORT-PROVISIONAL-THEME-IDENTITY-AND-CLOCK-VALIDATION-GAP ripple: the shared canonicalizer now rejects
    # Unicode folds, so this mirror must too). The local A-share regex is kept ONLY to sharpen the diagnostic.
    ct = canonical_us_ticker(raw)
    if ct is not None:
        return ct
    s = ("" if raw is None else str(raw)).strip().upper()
    if isinstance(raw, str) and raw.isascii() and _A_SHARE_CODE_RE.fullmatch(s):
        raise ConvertError(f"{field}={raw!r} looks like an A-share code; US-short does NOT cross A-share. Manage A-share holdings with the A-share tools.")
    raise ConvertError(f"{field}={raw!r} is not a valid US listing symbol (uppercase, letter-first, e.g. AAPL / BRK.B)")


def _opt_str(raw):
    s = ("" if raw is None else str(raw)).strip()
    return None if s == "" else s


def _reject_unknown_columns(columns, name: str) -> None:
    """Fail-fast on any out-of-contract column/key (no silent drop). `None` is the csv.DictReader
    restkey for row-overflow cells, so it counts as unknown too."""
    allowed = set(EXPECTED_COLUMNS[name])
    extra = sorted({("<extra-cells>" if c is None else c) for c in columns if c not in allowed})
    if extra:
        raise ConvertError(
            f"{name} has unknown/out-of-contract column(s) {extra}; only {sorted(allowed)} are allowed "
            "(fail-fast, no silent drop — e.g. positions has no `direction` column, v1 is long-only)")


def _required_text(raw, field: str) -> str:
    value = _opt_str(raw)
    if value is None:
        raise ConvertError(f"{field} must be non-blank text")
    return value


def _build_holding_theme_reconciliation(rows, positions, decision_as_of):
    """Build the optional private Cut3 holding-theme reconciliation from holding_themes.csv."""
    if not rows:
        return None
    position_tickers = {position["ticker"] for position in positions}
    out, seen = [], set()
    for raw in rows:
        ticker = _parse_us_ticker(raw.get("ticker"), "holding_themes.ticker")
        if ticker in seen:
            raise ConvertError(f"holding_themes contains duplicate ticker {ticker}")
        seen.add(ticker)
        as_of = _parse_date(raw.get("as_of"), f"holding_themes {ticker} as_of")
        if as_of != decision_as_of:
            raise ConvertError(f"holding_themes {ticker} as_of must equal --as-of {decision_as_of}")
        source = _required_text(raw.get("theme_source"), f"holding_themes {ticker} theme_source")
        lifecycle = _required_text(
            raw.get("theme_lifecycle_state"), f"holding_themes {ticker} theme_lifecycle_state")
        if source not in THEME_SOURCES or lifecycle not in THEME_STATES:
            raise ConvertError(f"holding_themes {ticker} theme_source/lifecycle is outside governance")
        evidence_kind = _required_text(
            raw.get("evidence_ref_kind"), f"holding_themes {ticker} evidence_ref_kind")
        if evidence_kind not in {"provider row", "SEC filing", "source_id"}:
            raise ConvertError(f"holding_themes {ticker} evidence_ref_kind is invalid")
        out.append({
            "ticker": ticker,
            "theme_id": _required_text(raw.get("theme_id"), f"holding_themes {ticker} theme_id").casefold(),
            "theme_source": source,
            "theme_lifecycle_state": lifecycle,
            "macro_cluster": _required_text(
                raw.get("macro_cluster"), f"holding_themes {ticker} macro_cluster").casefold(),
            "evidence_ref": {
                "kind": evidence_kind,
                "value": _required_text(
                    raw.get("evidence_ref_value"), f"holding_themes {ticker} evidence_ref_value"),
                "as_of": as_of,
            },
        })
    if seen != position_tickers:
        raise ConvertError("holding_themes.csv must cover current positions exactly once")
    return {
        "schema_name": "us_short_holding_theme_reconciliation",
        "schema_version": "1.0.0",
        "as_of": decision_as_of,
        "positions": sorted(out, key=lambda item: item["ticker"]),
    }


# -- pure core: tables(dict[str, list[dict]]) + decision_as_of + expected_facts_as_of -> (account_state, lineage) -----------
def build_account_state(tables: dict, decision_as_of: str, expected_facts_as_of: str) -> tuple:
    """Build a schema-valid account_state dict + lineage dict from already-parsed table rows.

    Pure & deterministic: same tables + decision_as_of + expected_facts_as_of -> identical output (positions sorted by
    ticker; no wall-clock). Raises ConvertError (FATAL) on any malformed / out-of-contract input.
    """
    decision_as_of = _parse_date(decision_as_of, "--as-of")
    expected_facts_as_of = _parse_date(expected_facts_as_of, "--price-basis-date")
    if expected_facts_as_of > decision_as_of:
        raise ConvertError(
            f"--price-basis-date {expected_facts_as_of} > --as-of {decision_as_of} (latest settled facts are in the future; refusing to run)")
    for _name in ("account", "positions", "trades", "holding_themes"):  # strict input (pure path too)
        for _row in tables.get(_name, []):
            _reject_unknown_columns(_row.keys(), _name)
    facts_as_of, acct = _build_account_fields(tables["account"], decision_as_of, expected_facts_as_of)
    facts_staleness = "current" if facts_as_of == expected_facts_as_of else "stale_warning"
    positions = _build_positions(tables["positions"], decision_as_of)
    consistency_warnings = reconcile_trades_positions(tables.get("trades", []), positions, decision_as_of)
    holding_action_reconciliation = _build_holding_action_reconciliation(
        tables.get("trades", []), positions, decision_as_of)
    symbol_cooldown_reconciliation = _build_symbol_cooldown_reconciliation(
        tables.get("trades", []), decision_as_of)
    holding_theme_reconciliation = _build_holding_theme_reconciliation(
        tables.get("holding_themes", []), positions, decision_as_of)

    bucket = acct["us_market_equity"] / BUCKET_DIVISOR
    if acct["us_short_available_cash"] - bucket > _REL_EPS * max(1.0, bucket):
        raise ConvertError(
            f"account.us_short_available_cash {acct['us_short_available_cash']} exceeds the US-short bucket "
            f"{bucket} (= us_market_equity/{BUCKET_DIVISOR}); bucket-local cash must not exceed the bucket "
            "(capital policy: per-market 1/3 buckets, A/US cash non-fungible, runner ceiling <= its bucket)")
    account_state = {
        "schema_name": ACCOUNT_SCHEMA_NAME,
        "schema_version": ACCOUNT_SCHEMA_VERSION,
        "as_of": decision_as_of,
        "us_market_equity": acct["us_market_equity"],
        "us_short_bucket_capital": bucket,
        "us_short_available_cash": acct["us_short_available_cash"],
        "portfolio_total_equity": acct["portfolio_total_equity"],
        "positions": positions,
        "holding_action_reconciliation": holding_action_reconciliation,
        "symbol_cooldown_reconciliation": symbol_cooldown_reconciliation,
        "manual_order_only": True,
        "broker_connection_allowed": False,
    }
    if holding_theme_reconciliation is not None:
        account_state["holding_theme_reconciliation"] = holding_theme_reconciliation
    lineage = {
        "schema_name": LINEAGE_SCHEMA_NAME,
        "schema_version": LINEAGE_SCHEMA_VERSION,
        "generated_at": None,
        "decision_as_of": decision_as_of,
        "expected_facts_as_of": expected_facts_as_of,
        "facts_as_of": facts_as_of,
        "facts_staleness": facts_staleness,
        "bucket_basis": {
            "us_market_equity": acct["us_market_equity"],
            "divisor": BUCKET_DIVISOR,
            "us_short_bucket_capital": bucket,
        },
        "source_tables": [],          # filled by main() (needs file paths/hashes)
        "consistency_warnings": consistency_warnings,   # slice 1b trades<->positions reconcile (advisory)
    }
    return account_state, lineage


def _build_account_fields(rows: list, decision_as_of: str, expected_facts_as_of: str) -> tuple:
    if len(rows) != 1:
        raise ConvertError(f"account table must have exactly 1 row (portfolio-level state is unique), got {len(rows)}")
    a = rows[0]
    facts_as_of = _parse_date(a.get("as_of"), "account.as_of")
    if facts_as_of > expected_facts_as_of:
        raise ConvertError(
            f"account.as_of {facts_as_of} > --price-basis-date {expected_facts_as_of} (facts are after the latest settled clock; refusing to run)")
    if not _parse_bool(a.get("manual_order_only"), "account.manual_order_only"):
        raise ConvertError("account.manual_order_only must be TRUE")
    if _parse_bool(a.get("broker_connection_allowed"), "account.broker_connection_allowed"):
        raise ConvertError("account.broker_connection_allowed must be FALSE")
    cash = _parse_float(a.get("us_short_available_cash"), "account.us_short_available_cash", allow_zero=True)
    if cash < 0:
        raise ConvertError(f"account.us_short_available_cash={cash} must be >= 0")
    return facts_as_of, {
        "us_market_equity": _parse_float(a.get("us_market_equity"), "account.us_market_equity", positive=True),
        "us_short_available_cash": cash,
        "portfolio_total_equity": _parse_optional_float(
            a.get("portfolio_total_equity"), "account.portfolio_total_equity", positive=True),
    }


def _build_positions(rows: list, decision_as_of: str) -> list:
    positions = []
    seen = set()
    for i, r in enumerate(rows):
        ticker = _parse_us_ticker(r.get("ticker"), f"positions[{i}].ticker")
        if ticker in seen:
            raise ConvertError(f"positions has duplicate ticker {ticker}")
        seen.add(ticker)
        entry_date = _parse_date(r.get("entry_date"), f"positions[{i}].entry_date")
        if entry_date > decision_as_of:
            raise ConvertError(f"positions[{i}].entry_date {entry_date} > --as-of {decision_as_of} (future entry)")
        positions.append({
            "ticker": ticker,
            "direction": "long",
            "shares": _parse_int_shares(r.get("shares"), f"positions[{i}].shares"),
            "avg_cost_usd": _parse_float(r.get("avg_cost_usd"), f"positions[{i}].avg_cost_usd", positive=True),
            "entry_date": entry_date,
            "current_stop": _parse_optional_float(r.get("current_stop"), f"positions[{i}].current_stop", positive=True),
            "notes": _opt_str(r.get("notes")),
        })
    positions.sort(key=lambda p: p["ticker"])
    return positions


# -- slice 1b: trades<->positions reconcile (advisory WARN-only; never overrides positions) ----------
def reconcile_trades_positions(trades: list, positions: list, decision_as_of: str) -> list:
    """Parse each trade row strictly, net the EXECUTED buy/sell fills per ticker, and compare to
    positions.shares. WARN-only: positions stay authoritative (a mismatch can be partial history,
    dividends/splits, or fees). Returns [{ticker, kind, message}, ...]. Raises ConvertError on any
    malformed / out-of-contract trade row (fail-fast, same discipline as the rest of the input).
    `trades` is the execution log (§12 manual_actual_track); this slice only reconciles it."""
    pos_shares = {p["ticker"]: p["shares"] for p in positions}
    net = {}
    for i, r in enumerate(trades):
        ticker = _parse_us_ticker(r.get("ticker"), f"trades[{i}].ticker")
        decision_date = _parse_date(r.get("decision_date"), f"trades[{i}].decision_date")
        if decision_date > decision_as_of:
            raise ConvertError(f"trades[{i}].decision_date {decision_date} > --as-of {decision_as_of} (future trade)")
        action = _opt_str(r.get("suggested_action"))
        if action not in TRADE_ACTIONS:
            raise ConvertError(f"trades[{i}].suggested_action={r.get('suggested_action')!r} must be one of {list(TRADE_ACTIONS)} (§9 final_action vocab)")
        executed = _parse_bool(r.get("executed"), f"trades[{i}].executed")
        fill_price = _parse_optional_float(r.get("fill_price"), f"trades[{i}].fill_price", positive=True)
        fs_raw = _opt_str(r.get("fill_shares"))
        fill_shares = _parse_int_shares(fs_raw, f"trades[{i}].fill_shares") if fs_raw is not None else None
        skip_reason = _opt_str(r.get("skip_reason"))
        if executed:
            if action in TRADE_NOFILL_ACTIONS:
                raise ConvertError(f"trades[{i}] executed=TRUE but suggested_action={action} is a non-fill action; only {list(TRADE_BUY_ACTIONS + TRADE_SELL_ACTIONS)} can be executed")
            if fill_price is None or fill_shares is None:
                raise ConvertError(f"trades[{i}] executed=TRUE requires fill_price and fill_shares")
            sign = 1 if action in TRADE_BUY_ACTIONS else -1
            net[ticker] = net.get(ticker, 0) + sign * fill_shares
        else:
            if fill_price is not None or fill_shares is not None:
                raise ConvertError(f"trades[{i}] executed=FALSE must leave fill_price/fill_shares empty")
            if skip_reason is None:
                raise ConvertError(f"trades[{i}] executed=FALSE requires a skip_reason")
    warnings = []
    for ticker in sorted(net):
        n = net[ticker]
        if ticker not in pos_shares:
            if n > 0:   # net buy with no recorded position (net sell / 0 = normal full exit, not a warning)
                warnings.append({"ticker": ticker, "kind": "net_buy_not_in_positions",
                                 "message": f"trades net buy {n} shares but positions has no {ticker} (possible un-recorded holding; please verify)"})
        elif n != pos_shares[ticker]:
            warnings.append({"ticker": ticker, "kind": "shares_mismatch",
                             "message": f"{ticker}: positions {pos_shares[ticker]} shares vs trades net {n} (diff {pos_shares[ticker] - n}; may be partial history / dividends / splits / fees — advisory, please verify)"})
    return warnings


def _build_holding_action_reconciliation(trades: list, positions: list, decision_as_of: str) -> dict:
    """Derive TP1 completion only from an executed manual ``减仓`` record.

    This does not alter positions (they remain the authoritative account snapshot) and it deliberately
    carries no target price: the private planner sidecar owns only the prior system recommendation levels.
    """
    latest_reduce = {}
    for i, row in enumerate(trades):
        ticker = _parse_us_ticker(row.get("ticker"), f"trades[{i}].ticker")
        action = _opt_str(row.get("suggested_action"))
        date = _parse_date(row.get("decision_date"), f"trades[{i}].decision_date")
        executed = _parse_bool(row.get("executed"), f"trades[{i}].executed")
        if action == "减仓" and executed:
            latest_reduce[ticker] = max(date, latest_reduce.get(ticker, "00000000"))
    records = []
    for position in positions:
        ticker, entry_date, shares = position["ticker"], position["entry_date"], position["shares"]
        completed_at = latest_reduce.get(ticker)
        if completed_at is not None and completed_at < entry_date:
            completed_at = None
        completed = completed_at is not None
        ref_input = {"ticker": ticker, "entry_date": entry_date, "remaining_shares": shares,
                     "tp1_completed": completed, "tp1_completed_at": completed_at}
        digest = hashlib.sha256(json.dumps(ref_input, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        records.append({"ticker": ticker, "entry_date": entry_date, "remaining_shares": shares,
                        "tp1_completed": completed, "tp1_completed_at": completed_at,
                        "source_reconciliation_ref": "manual_account:" + digest})
    return {"schema_name": "us_short_holding_action_reconciliation", "schema_version": "1.0.0",
            "as_of": decision_as_of, "positions": records}


def _build_symbol_cooldown_reconciliation(trades: list, decision_as_of: str) -> dict:
    """Project only genuine filled failures from the manual execution log.

    An executed ``清仓-止损`` is a ``filled_then_stop_loss`` by default.  A user may explicitly classify the
    same filled stop as ``filled_then_breakout_failure`` in the optional ``failure_trigger`` column.  A skipped
    breakout, any unfilled trade, or any other action never enters the reconciliation and therefore can never
    create a symbol cooldown.
    """
    latest = {}
    allowed = {"filled_then_stop_loss", "filled_then_breakout_failure"}
    for i, row in enumerate(trades):
        ticker = _parse_us_ticker(row.get("ticker"), f"trades[{i}].ticker")
        date = _parse_date(row.get("decision_date"), f"trades[{i}].decision_date")
        action = _opt_str(row.get("suggested_action"))
        executed = _parse_bool(row.get("executed"), f"trades[{i}].executed")
        raw_trigger = _opt_str(row.get("failure_trigger"))
        if raw_trigger is not None and raw_trigger not in allowed:
            raise ConvertError(f"trades[{i}].failure_trigger={raw_trigger!r} must be one of {sorted(allowed)} or blank")
        if raw_trigger is not None and (not executed or action != "清仓-止损"):
            raise ConvertError("failure_trigger only applies to an executed 清仓-止损; unfilled breakout must remain blank")
        if not executed or action != "清仓-止损":
            continue
        trigger = raw_trigger or "filled_then_stop_loss"
        ref_input = {"ticker": ticker, "trigger": trigger, "triggered_at": date}
        digest = hashlib.sha256(json.dumps(ref_input, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        event = {"ticker": ticker, "trigger": trigger, "triggered_at": date,
                 "source_reconciliation_ref": "manual_account:" + digest}
        old = latest.get(ticker)
        if old is None or event["triggered_at"] >= old["triggered_at"]:
            latest[ticker] = event
    return {"schema_name": "us_short_symbol_cooldown_reconciliation", "schema_version": "1.0.0",
            "as_of": decision_as_of, "events": [latest[t] for t in sorted(latest)]}


# -- single validation source: JSON Schema + cross-field invariants ---------------------------------
def validate_account_state(state: dict, as_of: str) -> None:
    """The single source of truth for us_short_account_state validity. Raises ConvertError on failure.

    JSON Schema covers field shapes/consts/patterns; this adds the cross-field invariants Draft-07
    cannot express: bucket == us_market_equity / 3, unique US tickers, direction == long, and the
    as_of consistency with the run's decision date.
    """
    try:
        import jsonschema
    except ImportError:
        raise ConvertError("jsonschema is required to validate us_short_account_state; install it for this runtime")
    schema = json.loads(ACCOUNT_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(state, schema)
    except jsonschema.ValidationError as e:
        raise ConvertError(f"us_short_account_state failed schema: {e.message} (at {list(e.absolute_path)})")

    if state["as_of"] != as_of:
        raise ConvertError(
            f"account_state.as_of {state['as_of']} != run --as-of {as_of}; re-create the private account state "
            f"with --as-of {as_of} only after confirming the account and position facts remain current for that "
            "decision date"
        )
    # Date validity is enforced HERE, not only in the CSV builder: this validator is the single source
    # of truth, so a hand-edited / non-builder JSON must also be rejected for IMPOSSIBLE dates (the
    # schema pattern ^[0-9]{8}$ would accept 20260631) and FUTURE (PIT-violating) entry dates.
    # _parse_date re-runs strptime; YYYYMMDD string comparison is chronological.
    _parse_date(state["as_of"], "account_state.as_of")
    equity = state["us_market_equity"]
    bucket = state["us_short_bucket_capital"]
    expected = equity / BUCKET_DIVISOR
    if abs(bucket - expected) > _REL_EPS * max(1.0, abs(expected)):
        raise ConvertError(f"us_short_bucket_capital {bucket} != us_market_equity/{BUCKET_DIVISOR} ({expected})")
    cash = state["us_short_available_cash"]
    if cash - bucket > _REL_EPS * max(1.0, bucket):
        raise ConvertError(f"us_short_available_cash {cash} exceeds us_short_bucket_capital {bucket}; bucket-local cash must not exceed the bucket (capital policy: A/US cash non-fungible, runner ceiling <= its bucket)")
    seen = set()
    for p in state["positions"]:
        if p["direction"] != "long":
            raise ConvertError(f"position {p['ticker']} direction must be long (v1 long-only)")
        if p["ticker"] in seen:
            raise ConvertError(f"duplicate ticker {p['ticker']} in account_state")
        seen.add(p["ticker"])
        _parse_date(p["entry_date"], f"position {p['ticker']} entry_date")
        if p["entry_date"] > state["as_of"]:
            raise ConvertError(f"position {p['ticker']} entry_date {p['entry_date']} > as_of {state['as_of']} (future entry; PIT violation)")
    reconciliation = state.get("holding_action_reconciliation")
    if reconciliation is not None:
        if reconciliation["as_of"] != state["as_of"]:
            raise ConvertError("holding_action_reconciliation.as_of must equal account_state.as_of")
        by_ticker = {item["ticker"]: item for item in reconciliation["positions"]}
        if set(by_ticker) != seen or len(by_ticker) != len(reconciliation["positions"]):
            raise ConvertError("holding_action_reconciliation must cover account positions exactly once")
        for p in state["positions"]:
            item = by_ticker[p["ticker"]]
            if item["entry_date"] != p["entry_date"] or item["remaining_shares"] != p["shares"]:
                raise ConvertError(f"holding_action_reconciliation does not match position {p['ticker']}")
            if item["tp1_completed"] is False and item["tp1_completed_at"] is not None:
                raise ConvertError(f"holding_action_reconciliation {p['ticker']} has an impossible TP1 completion date")
            if item["tp1_completed"] is True:
                _parse_date(item["tp1_completed_at"], f"holding_action_reconciliation {p['ticker']} tp1_completed_at")
                if item["tp1_completed_at"] > state["as_of"]:
                    raise ConvertError(f"holding_action_reconciliation {p['ticker']} TP1 completion is future")
    cooldown_reconciliation = state.get("symbol_cooldown_reconciliation")
    if cooldown_reconciliation is not None:
        if cooldown_reconciliation["as_of"] != state["as_of"]:
            raise ConvertError("symbol_cooldown_reconciliation.as_of must equal account_state.as_of")
        cooldown_seen = set()
        for event in cooldown_reconciliation["events"]:
            if event["ticker"] in cooldown_seen:
                raise ConvertError(f"symbol_cooldown_reconciliation ticker duplicate: {event['ticker']}")
            cooldown_seen.add(event["ticker"])
            _parse_date(event["triggered_at"], f"symbol_cooldown_reconciliation {event['ticker']} triggered_at")
            if event["triggered_at"] > state["as_of"]:
                raise ConvertError(f"symbol_cooldown_reconciliation {event['ticker']} trigger is future")
    theme_reconciliation = state.get("holding_theme_reconciliation")
    if theme_reconciliation is not None:
        if theme_reconciliation["as_of"] != state["as_of"]:
            raise ConvertError("holding_theme_reconciliation.as_of must equal account_state.as_of")
        theme_by_ticker = {item["ticker"]: item for item in theme_reconciliation["positions"]}
        if set(theme_by_ticker) != seen or len(theme_by_ticker) != len(theme_reconciliation["positions"]):
            raise ConvertError("holding_theme_reconciliation must cover account positions exactly once")
        for ticker, item in theme_by_ticker.items():
            if item["evidence_ref"]["as_of"] != state["as_of"]:
                raise ConvertError(f"holding_theme_reconciliation {ticker} evidence_ref.as_of mismatch")


# -- fail-closed privacy guard (§18.0 P0): real-holdings output must land on a gitignored path -------
def _reject_nonprivate_account_output_path(out_path: str) -> None:
    """Refuse writing account_state/lineage (real holdings/cost/cash) to an in-repo path that git does
    not ignore. Fail-closed: an in-repo path that is not provably gitignored is rejected, and a
    git-check failure (git missing / non-0/1 rc) is ALSO rejected (we cannot prove the path is private).
    The ONLY sanctioned non-gitignored destination is OUTSIDE the repo (the user's own external private
    location). There is deliberately NO in-repo override flag: real holdings must never land on a
    tracked path, even on explicit request (us_short_system_design §11.6 / §18.0 fail-closed P0).
    """
    p = Path(out_path)
    if not p.is_absolute():
        # a relative path resolves against the process CWD, NOT the repo root, so from a non-root CWD it can
        # resolve outside the repo and slip through the outside-repo branch below, bypassing the git-check gate
        # (real holdings could land in an unintended CWD-relative location). Fail closed: require an absolute path.
        raise ConvertError(
            f"refusing a RELATIVE account output path {out_path!r}: a relative path is CWD-dependent "
            "(not repo-root-relative) and its privacy location cannot be proven. Pass an ABSOLUTE --out / "
            "--lineage-out — an external private location, or an in-repo path built from ROOT "
            "(e.g. ROOT / 'state/us_short/...')."
        )
    p = p.resolve()
    try:
        p.relative_to(ROOT)
    except ValueError:
        return  # outside the repo -> user's own external private location
    try:
        r = subprocess.run(["git", "check-ignore", "-q", "--", str(p)],
                           cwd=str(ROOT), stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (FileNotFoundError, OSError) as e:
        raise ConvertError(f"cannot verify {p} is gitignored (git check-ignore unavailable: {e}); fail-closed, refusing to write real account data")
    if r.returncode == 0:
        return  # ignored -> private -> OK
    if r.returncode == 1:
        raise ConvertError(f"refusing to write real account data to non-gitignored in-repo path {p} (would risk committing holdings/cost/cash). Put it under a gitignored private dir, e.g. state/us_short/, or write it OUTSIDE the repo. There is no in-repo override.")
    raise ConvertError(f"git check-ignore failed for {p} (rc={r.returncode}); fail-closed, refusing to write real account data")


# -- thin main: read CSV -> build -> validate -> privacy guard -> atomic write -----------------------
def _read_csv_table(path: Path, name: str) -> list:
    with open(path, encoding="utf-8-sig", newline="") as f:   # utf-8-sig tolerates an Excel-saved BOM
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        dupes = sorted({h for h in header if header.count(h) > 1})
        if dupes:   # csv.DictReader keeps only the last same-named column -> silent data drop
            raise ConvertError(f"{name}.csv has duplicate header column(s) {dupes}; each column must appear exactly once")
        missing = [c for c in REQUIRED_COLUMNS[name] if c not in header]
        if missing:
            raise ConvertError(f"{name}.csv missing required column(s): {missing} (header={header})")
        _reject_unknown_columns(header, name)   # strict input: reject unknown header columns (incl. 0-row CSV)
        return [{(k.strip() if k else k): v for k, v in raw.items()} for raw in reader]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_lineage(lineage: dict) -> None:
    """Validate the lineage sidecar against its own schema at runtime (mirrors validate_account_state;
    catches future builder/schema drift, not only the schema test's example)."""
    try:
        import jsonschema
    except ImportError:
        raise ConvertError("jsonschema is required to validate the lineage sidecar; install it for this runtime")
    schema = json.loads(LINEAGE_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(lineage, schema)
    except jsonschema.ValidationError as e:
        raise ConvertError(f"us_short_account_state_lineage failed schema: {e.message} (at {list(e.absolute_path)})")


def validate_account_lineage(
    lineage: dict,
    account_state: dict,
    decision_as_of: str,
    expected_facts_as_of: str,
) -> None:
    """Validate one account/lineage pair against the capstone's canonical clocks."""
    _validate_lineage(lineage)
    if not lineage["source_tables"]:
        raise ConvertError("lineage.source_tables must contain the converter input provenance")
    for field in ("us_market_equity", "us_short_bucket_capital"):
        state_value = account_state[field]
        lineage_value = lineage["bucket_basis"][field]
        if abs(lineage_value - state_value) > _REL_EPS * max(1.0, abs(state_value)):
            raise ConvertError(
                f"lineage.bucket_basis.{field} does not match account_state.{field}"
            )
    decision_as_of = _parse_date(decision_as_of, "run decision_as_of")
    expected_facts_as_of = _parse_date(expected_facts_as_of, "run price_basis_date")
    if lineage["decision_as_of"] != decision_as_of:
        raise ConvertError(
            f"lineage.decision_as_of {lineage['decision_as_of']} != run decision_as_of {decision_as_of}"
        )
    if lineage["expected_facts_as_of"] != expected_facts_as_of:
        raise ConvertError(
            f"lineage.expected_facts_as_of {lineage['expected_facts_as_of']} != run price_basis_date {expected_facts_as_of}"
        )
    if lineage["expected_facts_as_of"] > lineage["decision_as_of"]:
        raise ConvertError("lineage.expected_facts_as_of is after lineage.decision_as_of")
    if lineage["facts_as_of"] > lineage["expected_facts_as_of"]:
        raise ConvertError("lineage.facts_as_of is after lineage.expected_facts_as_of")
    expected_staleness = (
        "current" if lineage["facts_as_of"] == lineage["expected_facts_as_of"] else "stale_warning"
    )
    if lineage["facts_staleness"] != expected_staleness:
        raise ConvertError(
            f"lineage.facts_staleness {lineage['facts_staleness']} does not match the two facts dates"
        )


def _write_json_atomic(path: Path, payload) -> None:
    # Fail-closed privacy guard on EVERY write of account/lineage data (§11.6: "绕过脚本直接调管线也拦得住").
    # main() also pre-checks both paths up front (fail-fast atomicity); this guards any direct/future caller
    # of the write primitive so real holdings can never reach a non-gitignored in-repo path.
    _reject_nonprivate_account_output_path(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="US-short manual tables -> us_short_account_state.json converter")
    p.add_argument("--input-dir", required=True, help="dir containing account.csv + positions.csv")
    p.add_argument("--as-of", required=True, help="decision date YYYYMMDD (= account_state.as_of = weekly --as-of)")
    p.add_argument("--price-basis-date", required=True,
                   help="latest fully settled price/facts date YYYYMMDD (= expected_facts_as_of; must be <= --as-of)")
    p.add_argument("--out", required=True, help="output us_short_account_state.json path — must be ABSOLUTE "
                   "(privacy guard rejects relative/CWD-dependent paths); inside the gitignored state/us_short/ "
                   "dir, or an external private location")
    p.add_argument("--lineage-out", help="lineage sidecar path (ABSOLUTE; default <out dir>/<out stem>_lineage.json)")
    args = p.parse_args(argv)

    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        raise ConvertError(f"--input-dir does not exist or is not a directory: {input_dir}")

    tables = {}
    source_tables = []
    for name in REQUIRED_TABLES + OPTIONAL_TABLES:
        path = input_dir / f"{name}.csv"
        if not path.is_file():
            if name in REQUIRED_TABLES:
                raise ConvertError(f"missing required table {name}.csv ({path})")
            tables[name] = []   # optional table (trades) absent -> no reconcile
            continue
        rows = _read_csv_table(path, name)
        tables[name] = rows
        source_tables.append({"name": name, "path": str(path).replace("\\", "/"),
                              "sha256": _sha256(path), "row_count": len(rows)})

    account_state, lineage = build_account_state(tables, args.as_of, args.price_basis_date)
    lineage["source_tables"] = source_tables
    lineage["generated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    validate_account_state(account_state, account_state["as_of"])

    out_path = Path(args.out)
    lineage_path = Path(args.lineage_out) if args.lineage_out else out_path.with_name(out_path.stem + "_lineage.json")
    if out_path.resolve() == lineage_path.resolve():
        raise ConvertError(f"--out and --lineage-out must be different paths (both resolve to {out_path.resolve()}); "
                           f"the lineage write would silently overwrite the account_state")
    validate_account_lineage(lineage, account_state, args.as_of, args.price_basis_date)
    for _p in (out_path, lineage_path):
        _reject_nonprivate_account_output_path(str(_p))   # fail-fast: check both before any write (atomicity)
    _write_json_atomic(out_path, account_state)
    _write_json_atomic(lineage_path, lineage)

    _print_plain_summary(account_state, lineage)
    print(f"[OK] account_state -> {out_path}")
    print(f"[OK] lineage       -> {lineage_path}")
    return 0


def _print_plain_summary(account_state: dict, lineage: dict) -> None:
    """Plain-language summary of what the tables produced (US-short §11-style honesty)."""
    print(f"[US-short 4.x] decision {account_state['as_of']}; latest settled facts date "
          f"{lineage['expected_facts_as_of']}; facts as-of {lineage['facts_as_of']} "
          f"({lineage['facts_staleness']}). {len(account_state['positions'])} position(s); "
          f"US-short bucket = ${account_state['us_short_bucket_capital']:.2f} "
          f"(= us_market_equity ${account_state['us_market_equity']:.2f} / {BUCKET_DIVISOR}); "
          f"available cash ${account_state['us_short_available_cash']:.2f}.")
    if lineage["facts_staleness"] == "stale_warning":
        print(f"[WARN] facts as-of {lineage['facts_as_of']} is earlier than latest settled facts date "
              f"{lineage['expected_facts_as_of']}: "
              "later fills/holding changes may be missing; confirm the tables are up to date.")
    for w in (lineage.get("consistency_warnings") or []):   # slice 1b advisory reconcile (never overrides)
        print(f"[reconcile] {w['message']}")


if __name__ == "__main__":
    raise SystemExit(main())
