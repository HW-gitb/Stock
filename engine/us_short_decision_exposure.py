"""Write down the exposure limits the weekly decision already computed.

Every week the selection path works out how much equity its own rules allow it to
hold — the environment's position cap, what the cash on hand can fund, what is
already carried, and what this week's plan asks to add. It uses all four to
decide, and then discards them. Nothing is written down.

That is why v1.1 attribution cannot run. Its whole job is to separate "we picked
badly" from "the rules had us at half position", and it needs the position the
rules IMPLIED, not the one that ended up filled. Design section 12.7 forbids
recovering that from fills or from a later NAV, and re-deriving it afterwards
would mean re-running the rules against data they never saw. So the only honest
source is a note taken at the moment the numbers exist.

This module takes that note. It computes nothing new: every input is a value the
decision already had in hand, and no selection, action, size or NAV depends on
anything here. If any input is missing, the record says so rather than guessing —
an invented exposure is worse than none, because it would be read as verified.

Not a public artifact. The record carries ratios only, never the account's
capital or cash amounts, so a copy of it discloses no balance.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math
import os
from pathlib import Path
import re
from typing import Any

from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path

SCHEMA_NAME = "us_short_decision_exposure"
SCHEMA_VERSION = "1.0.0"
FILENAME = "decision_exposure.json"
LONG_ONLY_CAP = 1.0

REASON_NO_MARK = "carried_holding_has_no_decision_time_mark"
REASON_NO_PLANNED_COST = "planned_build_has_no_cash_requirement"
REASON_BAD_ACCOUNT = "account_capital_or_cash_is_unusable"
REASON_BAD_REGIME = "regime_position_cap_is_unusable"
REASON_OUT_OF_RANGE = "a_derived_exposure_fell_outside_zero_to_one"

_DATE8 = re.compile(r"^[0-9]{8}$")


class DecisionExposureError(Exception):
    """The record cannot be built or written."""


def _positive(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0.0 else None


def _non_negative(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0.0 else None


def _unavailable(decision_date: str, reasons: list[str]) -> dict[str, Any]:
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "decision_date": decision_date,
        "status": "unavailable",
        "market_risk_regime": None,
        "carried_holdings_exposure": None,
        "new_order_exposure": None,
        "cash_capacity_exposure": None,
        "environment_position_cap": None,
        "long_only_cap": None,
        "unavailable_reasons": sorted(set(reasons)),
    }


def build_decision_exposure_record(
    *,
    decision_date: str,
    account_state: Mapping[str, Any],
    regime: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    portfolio_capacity: Mapping[str, Any],
) -> dict[str, Any]:
    """The four exposure limits this decision worked to, as fractions of the bucket."""

    if not isinstance(decision_date, str) or _DATE8.fullmatch(decision_date) is None:
        raise DecisionExposureError("decision_date must be YYYYMMDD")
    if not isinstance(account_state, Mapping) or not isinstance(regime, Mapping):
        raise DecisionExposureError("account_state and regime must be objects")
    if not isinstance(portfolio_capacity, Mapping) or not isinstance(rows, Sequence):
        raise DecisionExposureError("portfolio_capacity must be an object and rows a sequence")

    reasons: list[str] = []
    bucket = _positive(account_state.get("us_short_bucket_capital"))
    cash = _non_negative(account_state.get("us_short_available_cash"))
    if bucket is None or cash is None:
        reasons.append(REASON_BAD_ACCOUNT)
    cap = _non_negative(regime.get("position_cap"))
    if cap is None or cap > 1.0:
        reasons.append(REASON_BAD_REGIME)
    if reasons:
        return _unavailable(decision_date, reasons)
    assert bucket is not None and cash is not None and cap is not None

    carried_value = 0.0
    for position in portfolio_capacity.get("existing_positions") or []:
        mark = _positive(position.get("mark_price") if isinstance(position, Mapping) else None)
        shares = position.get("shares") if isinstance(position, Mapping) else None
        if mark is None or not isinstance(shares, int) or isinstance(shares, bool) or shares < 0:
            # A holding the decision could not price is a hole in the carried
            # exposure, and a hole cannot be filled with a zero: that would report
            # the account as holding less than it does and blame the gap on the
            # stock picking.
            reasons.append(REASON_NO_MARK)
            break
        carried_value += float(shares) * mark

    planned_value = 0.0
    for row in rows:
        if not isinstance(row, Mapping) or row.get("cash_allocation_status") != "allocated":
            continue
        required = _positive(row.get("cash_required_at_entry_high"))
        if required is None:
            reasons.append(REASON_NO_PLANNED_COST)
            break
        planned_value += required

    if reasons:
        return _unavailable(decision_date, reasons)

    carried = carried_value / bucket
    new_order = planned_value / bucket
    # What the cash constraint permits is what is already held plus what the cash
    # could still buy. Above 1 it simply does not bind — the long-only ceiling is
    # already there — so it is expressed at that ceiling rather than as a number
    # outside the domain the rule works in.
    cash_capacity = min((carried_value + cash) / bucket, LONG_ONLY_CAP)
    values = {
        "carried_holdings_exposure": carried,
        "new_order_exposure": new_order,
        "cash_capacity_exposure": cash_capacity,
        "environment_position_cap": cap,
    }
    if any(not (0.0 <= value <= 1.0) for value in values.values()):
        # Long-only and unlevered, so none of these can honestly exceed one. If
        # one does, something upstream is not what this module thinks it is.
        return _unavailable(decision_date, [REASON_OUT_OF_RANGE])

    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "decision_date": decision_date,
        "status": "evaluable",
        "market_risk_regime": regime.get("market_risk_regime"),
        **values,
        "long_only_cap": LONG_ONLY_CAP,
        "unavailable_reasons": [],
    }


def exposure_path(decision_date: str, *, runs_private_root: str | Path) -> Path:
    return Path(runs_private_root).resolve() / decision_date / FILENAME


def write_decision_exposure(
    record: Mapping[str, Any], *, runs_private_root: str | Path
) -> Path:
    """Write the note once. A second run of the same week leaves the first in place."""

    if not isinstance(record, Mapping) or record.get("schema_name") != SCHEMA_NAME:
        raise DecisionExposureError("record is not a decision exposure record")
    decision_date = record.get("decision_date")
    if not isinstance(decision_date, str) or _DATE8.fullmatch(decision_date) is None:
        raise DecisionExposureError("record decision_date must be YYYYMMDD")
    path = exposure_path(decision_date, runs_private_root=runs_private_root)
    try:
        reject_nonprivate_output_path(path)
    except PrivatePathError as exc:
        raise DecisionExposureError(f"refusing a non-private destination: {exc}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        # Idempotent by leaving the first note alone: the decision it describes is
        # the one that was made, and a re-run must not restate it.
        return path
    with os.fdopen(handle, "wb") as stream:
        stream.write(payload)
    return path


def load_decision_exposure(
    decision_date: str, *, runs_private_root: str | Path
) -> dict[str, Any] | None:
    """The note for one week, or ``None`` if that week never took one."""

    path = exposure_path(decision_date, runs_private_root=runs_private_root)
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DecisionExposureError(f"{FILENAME} for {decision_date} is unreadable: {exc}") from exc
    if not isinstance(record, dict) or record.get("schema_name") != SCHEMA_NAME:
        raise DecisionExposureError(f"{FILENAME} for {decision_date} is not a decision exposure record")
    if record.get("decision_date") != decision_date:
        raise DecisionExposureError(
            f"the exposure note filed under {decision_date} describes {record.get('decision_date')!r}"
        )
    return record
