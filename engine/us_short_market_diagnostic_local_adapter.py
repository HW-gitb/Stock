"""Read-only local adapter for the US-short 26-week market diagnostic.

Knife 2 joins two already-local sources without starting an account or asking a
provider for data:

* the private model-paper store, whose head, settlement, portfolio state, and
  NAV are validated and digest-bound before they are projected;
* a small local benchmark price packet that keeps SPY/QQQ from the existing
  grouped market window and accepts the IWB/VTI local slice.

This adapter emits price-return diagnostics by default.  An optional,
source-bound Knife 5 dividend sidecar can be supplied to upgrade each
validated ETF-week to total-return evaluation; a failed or incomplete sidecar
keeps that ETF-week on price return with an explicit degradation reason.
Missing prices are left missing and become ``unavailable`` rather than
zero-filled.  The adapter does not write files, advance the model-paper head,
create the normalized $100,000 account, call a provider, or alter
selection/action/sizing/NAV decisions.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft7Validator

from engine.us_short_market_diagnostic import (
    BENCHMARKS,
    BOUNDARY,
    construct_simple_return,
    construct_weekly_return,
)
from engine.us_short_market_diagnostic_total_return import (
    TotalReturnSidecarError,
    build_total_return_benchmark_observation,
    validate_etf_total_return_sidecar,
)
from engine.us_short_model_paper_portfolio import (
    ModelPaperPortfolioError,
    artifact_sha256,
    canonical_json_bytes,
    validate_nav_snapshot,
    validate_portfolio_state,
    validate_settlement,
)
from engine.us_short_model_paper_store import ModelPaperStoreError, load_head
from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path


ROOT = Path(__file__).resolve().parent.parent
PRICE_PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_market_diagnostic_local_price_packet.schema.json"
_PRICE_PACKET_SCHEMA = json.loads(PRICE_PACKET_SCHEMA_PATH.read_text(encoding="utf-8"))
Draft7Validator.check_schema(_PRICE_PACKET_SCHEMA)
_PRICE_PACKET_VALIDATOR = Draft7Validator(_PRICE_PACKET_SCHEMA)

LOCAL_ADAPTER_BOUNDARY = {
    "local_only": True,
    "provider_calls_performed": False,
    "account_write_performed": False,
    "broker_or_order_automation": False,
}
_DATE8 = re.compile(r"^[0-9]{8}$")
_MONEY = re.compile(r"^(0|[1-9][0-9]*)\.[0-9]{6}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WINDOW_ID = re.compile(r"^26w-[1-9][0-9]*-[1-9][0-9]*$")


class LocalMarketDiagnosticAdapterError(ValueError):
    """Raised when local diagnostic inputs are missing, forged, or ambiguous."""


def _fail(message: str) -> None:
    raise LocalMarketDiagnosticAdapterError(message)


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{field} must be an object")
    return value


def _date8(value: object, field: str, *, allow_none: bool = False) -> date | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.isascii() or _DATE8.fullmatch(value) is None:
        _fail(f"{field} must be an ASCII YYYYMMDD date")
    try:
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    except ValueError as exc:
        raise LocalMarketDiagnosticAdapterError(f"{field} is not a real calendar date") from exc


def _as_of(value: object) -> date:
    parsed = _date8(value, "as_of_date")
    assert parsed is not None
    return parsed


def _not_future(value: date | None, field: str, as_of_date: date | None) -> None:
    if value is not None and as_of_date is not None and value > as_of_date:
        _fail(f"{field} is after as_of_date")


def _sha(value: object, field: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(f"{field} must be a lowercase sha256")
    return value


def _money(value: object, field: str, *, allow_none: bool = False) -> Decimal | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or _MONEY.fullmatch(value) is None:
        _fail(f"{field} must be a positive six-decimal money string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - regex already rejects this
        raise LocalMarketDiagnosticAdapterError(f"{field} is not valid money") from exc
    if result <= 0:
        _fail(f"{field} must be positive")
    return result


def _schema_validate(packet: Mapping[str, Any]) -> None:
    errors = sorted(_PRICE_PACKET_VALIDATOR.iter_errors(packet), key=lambda item: list(item.absolute_path))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "<root>"
        _fail(f"local price packet schema violation at {path}: {error.message}")


def validate_local_price_packet(
    packet: Mapping[str, Any], *, as_of_date: str | None = None
) -> dict[str, Any]:
    """Validate one local weekly benchmark price packet and return it unchanged."""

    _schema_validate(_mapping(packet, "price_packet"))
    as_of = _as_of(as_of_date) if as_of_date is not None else None
    if packet["benchmark_symbols"] != list(BENCHMARKS):
        _fail("price_packet.benchmark_symbols must be exactly VTI/IWB/SPY/QQQ")
    if not isinstance(packet["window_id"], str) or _WINDOW_ID.fullmatch(packet["window_id"]) is None:
        _fail("price_packet.window_id is malformed")
    weeks = packet["weeks"]
    previous_index: int | None = None
    previous_decision: date | None = None
    for index, raw_week in enumerate(weeks):
        week = _mapping(raw_week, f"price_packet.weeks[{index}]")
        week_index = week["calendar_week_index"]
        if previous_index is not None and week_index != previous_index + 1:
            _fail("local price packet weeks must be consecutive and ordered")
        decision = _date8(week["decision_date"], f"weeks[{index}].decision_date")
        settlement_decision = _date8(
            week["settlement_decision_date"],
            f"weeks[{index}].settlement_decision_date",
        )
        valuation = _date8(week["valuation_date"], f"weeks[{index}].valuation_date")
        _not_future(decision, f"weeks[{index}].decision_date", as_of)
        _not_future(settlement_decision, f"weeks[{index}].settlement_decision_date", as_of)
        _not_future(valuation, f"weeks[{index}].valuation_date", as_of)
        if settlement_decision > valuation:
            _fail("local price packet settlement_decision_date cannot be after valuation_date")
        if valuation > decision:
            _fail("local price packet valuation_date cannot be after decision_date")
        if previous_decision is not None and decision <= previous_decision:
            _fail("local price packet decision dates must be strictly increasing")
        benchmarks = _mapping(week["benchmarks"], f"weeks[{index}].benchmarks")
        if set(benchmarks) != set(BENCHMARKS):
            _fail("local price packet must contain exactly VTI, IWB, SPY, and QQQ")
        for symbol in BENCHMARKS:
            observation = _mapping(benchmarks[symbol], f"weeks[{index}].benchmarks.{symbol}")
            field = f"weeks[{index}].benchmarks.{symbol}"
            parsed_price_date = _date8(observation["price_date"], f"{field}.price_date", allow_none=True)
            parsed_prior_price_date = _date8(
                observation["prior_price_date"],
                f"{field}.prior_price_date",
                allow_none=True,
            )
            _not_future(parsed_price_date, f"{field}.price_date", as_of)
            _not_future(parsed_prior_price_date, f"{field}.prior_price_date", as_of)
            prior_close = _money(
                observation["prior_close"],
                f"weeks[{index}].benchmarks.{symbol}.prior_close",
                allow_none=True,
            )
            close = _money(
                observation["close"],
                f"weeks[{index}].benchmarks.{symbol}.close",
                allow_none=True,
            )
            if close is not None and parsed_price_date != valuation:
                _fail(f"{field}.price_date must equal valuation_date")
            if close is None and parsed_price_date is not None:
                _fail(f"{field}.missing close cannot carry price_date")
            if prior_close is not None and parsed_prior_price_date is None:
                _fail(f"{field}.prior close requires prior_price_date")
            if prior_close is None and parsed_prior_price_date is not None:
                _fail(f"{field}.missing prior close cannot carry prior_price_date")
            if (
                parsed_prior_price_date is not None
                and parsed_price_date is not None
                and parsed_prior_price_date >= parsed_price_date
            ):
                _fail(f"{field}.price interval must be strictly increasing")
            source_sha = _sha(
                observation["source_sha256"],
                f"weeks[{index}].benchmarks.{symbol}.source_sha256",
                allow_none=True,
            )
            if close is not None and source_sha is None:
                _fail(f"weeks[{index}].benchmarks.{symbol}.evaluable price requires source_sha256")
            if prior_close is not None and close is not None:
                construct_simple_return(prior_close, close, field=f"{symbol}.close")
            _sha(
                observation["dividend_sidecar_sha256"],
                f"weeks[{index}].benchmarks.{symbol}.dividend_sidecar_sha256",
                allow_none=True,
            )
        previous_index = week_index
        previous_decision = decision
    return dict(packet)


def _private_root(root: str | Path) -> Path:
    path = Path(root)
    if not path.is_absolute():
        _fail("model-paper root must be absolute")
    path = path.resolve()
    try:
        reject_nonprivate_output_path(path)
    except PrivatePathError as exc:
        raise LocalMarketDiagnosticAdapterError(f"model-paper root is not private: {path}") from exc
    return path


def _private_file(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise LocalMarketDiagnosticAdapterError("model-paper artifact escapes its private root") from exc
    try:
        reject_nonprivate_output_path(candidate)
    except PrivatePathError as exc:
        raise LocalMarketDiagnosticAdapterError(f"model-paper artifact is not private: {candidate}") from exc
    return candidate


def _read_canonical_json(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise LocalMarketDiagnosticAdapterError(f"cannot read local model-paper artifact: {path}") from exc
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalMarketDiagnosticAdapterError(f"local model-paper artifact is not UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        _fail(f"local model-paper artifact must be an object: {path}")
    try:
        if canonical_json_bytes(value) != payload:
            _fail(f"local model-paper artifact is not canonical JSON: {path}")
    except ModelPaperPortfolioError as exc:
        raise LocalMarketDiagnosticAdapterError(f"local model-paper artifact is not canonical JSON: {path}") from exc
    return value, hashlib.sha256(payload).hexdigest()


def load_model_paper_week(
    root: str | Path, decision_date: str, *, as_of_date: str | None = None
) -> dict[str, Any]:
    """Read one settled local model-paper week and re-check all cross-artifact digests."""

    requested_date = _date8(decision_date, "decision_date")
    as_of = _as_of(as_of_date) if as_of_date is not None else None
    _not_future(requested_date, "decision_date", as_of)
    store_root = _private_root(root)
    try:
        head = load_head(store_root)
    except ModelPaperStoreError as exc:
        raise LocalMarketDiagnosticAdapterError(f"cannot load model-paper head: {exc}") from exc
    last = head["last_settlement"]
    if last is None or requested_date > _date8(last["decision_date"], "head.last_settlement.decision_date"):
        _fail("diagnostic input requires a settled model-paper week")

    relative_base = f"weeks/{decision_date}"
    settlement, settlement_digest = _read_canonical_json(_private_file(store_root, f"{relative_base}/settlement.json"))
    state, state_digest = _read_canonical_json(_private_file(store_root, f"{relative_base}/portfolio_state.json"))
    nav, nav_digest = _read_canonical_json(_private_file(store_root, f"{relative_base}/nav_snapshot.json"))
    try:
        validate_settlement(settlement)
        validate_portfolio_state(state)
        validate_nav_snapshot(nav)
    except ModelPaperPortfolioError as exc:
        raise LocalMarketDiagnosticAdapterError(f"model-paper weekly artifact validation failed: {decision_date}") from exc

    if settlement["decision_date"] != decision_date:
        _fail("settlement decision_date does not match requested week")
    _not_future(_date8(settlement["decision_date"], "settlement.decision_date"), "settlement.decision_date", as_of)
    _not_future(_date8(settlement["maturity_as_of"], "settlement.maturity_as_of"), "settlement.maturity_as_of", as_of)
    _not_future(_date8(state["as_of"], "portfolio_state.as_of"), "portfolio_state.as_of", as_of)
    _not_future(_date8(nav["as_of"], "nav_snapshot.as_of"), "nav_snapshot.as_of", as_of)
    if state["as_of"] != settlement["maturity_as_of"] or nav["as_of"] != settlement["maturity_as_of"]:
        _fail("settlement, portfolio state, and NAV dates do not agree")
    if state_digest != settlement["post_state_sha256"]:
        _fail("settlement does not bind portfolio_state.json")
    if nav_digest != settlement["nav_snapshot_sha256"]:
        _fail("settlement does not bind nav_snapshot.json")
    if nav["state_sha256"] != state_digest:
        _fail("NAV does not bind portfolio_state.json")

    if last["decision_date"] == decision_date:
        if (
            last["settlement_sha256"] != settlement_digest
            or last["state_sha256"] != state_digest
            or last["nav_sha256"] != nav_digest
            or last["price_packet_sha256"] != settlement["price_packet_sha256"]
        ):
            _fail("head.last_settlement does not bind the requested weekly artifacts")

    unfilled = sum(
        outcome["status"] in {"not_filled", "held_action_unfilled"}
        for outcome in settlement["order_outcomes"]
    )
    return {
        "decision_date": decision_date,
        "valuation_date": nav["as_of"],
        "settlement": settlement,
        "state": state,
        "nav": nav,
        "unfilled_order_count": unfilled,
        "digests": {
            "settlement": settlement_digest,
            "state": state_digest,
            "nav": nav_digest,
            "price_packet": settlement["price_packet_sha256"],
        },
    }


def _packet_week(packet: Mapping[str, Any], calendar_week_index: int) -> Mapping[str, Any]:
    for week in packet["weeks"]:
        if week["calendar_week_index"] == calendar_week_index:
            return week
    _fail(f"local price packet has no calendar week {calendar_week_index}")


def _expected_price_intervals(packet: Mapping[str, Any]) -> dict[tuple[int, str], tuple[object, object]]:
    intervals: dict[tuple[int, str], tuple[object, object]] = {}
    for raw_week in packet["weeks"]:
        week = _mapping(raw_week, "price_packet.week")
        week_index = week["calendar_week_index"]
        benchmarks = _mapping(week["benchmarks"], f"price_packet.weeks[{week_index}].benchmarks")
        for symbol in BENCHMARKS:
            observation = _mapping(benchmarks[symbol], f"price_packet.weeks[{week_index}].benchmarks.{symbol}")
            intervals[(week_index, symbol)] = (
                observation["prior_price_date"],
                observation["price_date"],
            )
    return intervals


def adapt_benchmark_week(
    packet: Mapping[str, Any],
    calendar_week_index: int,
    *,
    strategy_evaluable: bool,
    strategy_weekly_return: float | None,
    total_return_sidecar: Mapping[str, Any] | None = None,
    windows_aligned: bool,
    as_of_date: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Project one local price week into the diagnostic weekly benchmark shape.

    The optional sidecar is already-captured input.  It is validated and
    reconciled locally; this function never obtains it from a provider.
    """

    packet = validate_local_price_packet(packet, as_of_date=as_of_date)
    week = _packet_week(packet, calendar_week_index)
    sidecar_benchmarks: Mapping[str, Any] | None = None
    if total_return_sidecar is not None:
        try:
            sidecar = validate_etf_total_return_sidecar(
                total_return_sidecar,
                expected_price_intervals=_expected_price_intervals(packet),
                as_of_date=as_of_date,
            )
        except TotalReturnSidecarError as exc:
            raise LocalMarketDiagnosticAdapterError(f"invalid ETF total-return sidecar: {exc}") from exc
        if sidecar["window_id"] != packet["window_id"]:
            _fail("total-return sidecar window_id does not match local price packet")
        if sidecar["diagnostic_epoch"] != packet["diagnostic_epoch"]:
            _fail("total-return sidecar diagnostic_epoch does not match local price packet")
        sidecar_week = next(
            (candidate for candidate in sidecar["weeks"] if candidate["calendar_week_index"] == calendar_week_index),
            None,
        )
        if sidecar_week is None:
            _fail(f"total-return sidecar has no calendar week {calendar_week_index}")
        if sidecar_week["valuation_date"] != week["valuation_date"]:
            _fail("total-return sidecar valuation_date does not match local price packet")
        sidecar_benchmarks = sidecar_week["benchmarks"]
    result: dict[str, dict[str, Any]] = {}
    for symbol in BENCHMARKS:
        observation = week["benchmarks"][symbol]
        if sidecar_benchmarks is not None:
            try:
                result[symbol] = build_total_return_benchmark_observation(
                    sidecar_observation=sidecar_benchmarks[symbol],
                    price_observation=observation,
                    strategy_evaluable=strategy_evaluable,
                    strategy_weekly_return=strategy_weekly_return,
                    windows_aligned=windows_aligned,
                    as_of_date=as_of_date,
                )
            except TotalReturnSidecarError as exc:
                raise LocalMarketDiagnosticAdapterError(
                    f"cannot reconcile {symbol} total-return sidecar: {exc}"
                ) from exc
            continue
        prior_close = observation["prior_close"]
        close = observation["close"]
        source_sha = observation["source_sha256"]
        if prior_close is not None and close is not None:
            prior_value = _money(prior_close, f"{symbol}.prior_close")
            close_value = _money(close, f"{symbol}.close")
            assert prior_value is not None and close_value is not None
            weekly_return = construct_simple_return(
                float(prior_value), float(close_value), field=f"{symbol}.close"
            )
            benchmark_evaluable = True
            return_quality = "price_return_diagnostic"
            reasons = ["dividend_sidecar_not_reconciled"]
        else:
            weekly_return = None
            benchmark_evaluable = False
            return_quality = "unavailable"
            reasons = ["price_missing" if close is None else "prior_price_missing"]
        # Both sides evaluable is necessary but not sufficient: they also have to
        # cover the same span, which they do not in the week after a no_count one.
        joint_evaluable = bool(strategy_evaluable and benchmark_evaluable and windows_aligned)
        raw_excess = (
            strategy_weekly_return - weekly_return
            if joint_evaluable and strategy_weekly_return is not None and weekly_return is not None
            else None
        )
        relative_wealth = (
            (1.0 + strategy_weekly_return) / (1.0 + weekly_return) - 1.0
            if joint_evaluable and strategy_weekly_return is not None and weekly_return is not None
            else None
        )
        result[symbol] = {
            "return_quality": return_quality,
            "benchmark_evaluable": benchmark_evaluable,
            "joint_evaluable": joint_evaluable,
            "weekly_return": weekly_return,
            "cumulative_return": None,
            "raw_excess": raw_excess,
            "relative_wealth": relative_wealth,
            "price_date": observation["price_date"],
            "price_source": observation["source_kind"],
            "price_packet_sha256": source_sha,
            "dividend_sidecar_sha256": None,
            "data_quality_reasons": reasons,
        }
    return result


def _dedupe_sha256(values: list[str | None]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value is not None and value not in result:
            result.append(value)
    return result


def build_weekly_record_from_local(
    *,
    model_paper_root: str | Path,
    benchmark_packet: Mapping[str, Any],
    calendar_week_index: int,
    diagnostic_policy_sha256: str,
    strategy_ruleset_fingerprint: str,
    v1_1_reminder: Mapping[str, Any],
    prior_nav: str | None,
    total_return_sidecar: Mapping[str, Any] | None = None,
    prior_week_was_no_count: bool,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Build one schema-shaped weekly record from already-settled local inputs.

    The caller supplies the frozen policy/ruleset/reminder metadata because
    lifecycle persistence belongs to Knife 3.  For week 1, ``prior_nav`` must
    be ``None`` and the normalized capital is the base; later weeks must carry
    the exact prior settled NAV rather than silently restarting the series.
    """

    packet = validate_local_price_packet(benchmark_packet, as_of_date=as_of_date)
    validated_total_return_sidecar: Mapping[str, Any] | None = None
    if total_return_sidecar is not None:
        try:
            validated_total_return_sidecar = validate_etf_total_return_sidecar(
                total_return_sidecar,
                expected_price_intervals=_expected_price_intervals(packet),
                as_of_date=as_of_date,
            )
        except TotalReturnSidecarError as exc:
            raise LocalMarketDiagnosticAdapterError(f"invalid ETF total-return sidecar: {exc}") from exc
    if isinstance(calendar_week_index, bool) or not isinstance(calendar_week_index, int) or calendar_week_index < 1:
        _fail("calendar_week_index must be a positive integer")
    week = _packet_week(packet, calendar_week_index)
    decision_date = week["decision_date"]
    settlement_decision_date = week["settlement_decision_date"]
    paper_week = load_model_paper_week(
        model_paper_root,
        settlement_decision_date,
        as_of_date=as_of_date,
    )
    if paper_week["decision_date"] != settlement_decision_date:
        _fail("model-paper settlement decision date does not match local benchmark week")
    if paper_week["valuation_date"] != week["valuation_date"]:
        _fail("model-paper valuation date does not match local benchmark week")
    if calendar_week_index == 1 and prior_nav is not None:
        _fail("week 1 must use the frozen normalized capital, not a supplied prior NAV")
    if calendar_week_index > 1 and prior_nav is None:
        _fail("weeks after week 1 require the prior settled NAV")
    if prior_nav is not None:
        _money(prior_nav, "prior_nav")
    _sha(diagnostic_policy_sha256, "diagnostic_policy_sha256")
    _sha(strategy_ruleset_fingerprint, "strategy_ruleset_fingerprint")
    reminder = _mapping(v1_1_reminder, "v1_1_reminder")
    if reminder.get("status") not in {"pending", "ready_for_v1_1_implementation", "overdue", "active"}:
        _fail("v1_1_reminder.status is unknown")
    if isinstance(reminder.get("evaluable_week_count"), bool) or not isinstance(
        reminder.get("evaluable_week_count"), int
    ) or reminder["evaluable_week_count"] < 0:
        _fail("v1_1_reminder.evaluable_week_count must be a non-negative integer")
    if not isinstance(reminder.get("text"), str) or not reminder["text"]:
        _fail("v1_1_reminder.text must be non-empty")

    # After a no_count week the account settled once across more than one calendar
    # week — the pending decision simply matured late — so this week's NAV move
    # spans that week too while the benchmarks span only this one. Both numbers are
    # real; the PAIR is not like-for-like, so it is recorded and excluded rather
    # than quietly averaged into the 26-week excess.
    windows_aligned = not prior_week_was_no_count
    nav = paper_week["nav"]
    strategy_weekly_return = construct_weekly_return(prior_nav, nav["nav"])
    initial = Decimal("100000.000000")
    cumulative_return = float(Decimal(nav["nav"]) / initial - Decimal("1"))
    strategy_evaluable = bool(nav["paper_evaluable"])
    benchmarks = adapt_benchmark_week(
        packet,
        calendar_week_index,
        strategy_evaluable=strategy_evaluable,
        strategy_weekly_return=strategy_weekly_return,
        total_return_sidecar=validated_total_return_sidecar,
        windows_aligned=windows_aligned,
        as_of_date=as_of_date,
    )
    source_refs = _dedupe_sha256(
        [
            *paper_week["digests"].values(),
            *packet["source_refs"],
            *(benchmark["price_packet_sha256"] for benchmark in benchmarks.values()),
            *(benchmark["dividend_sidecar_sha256"] for benchmark in benchmarks.values()),
        ]
    )
    if len(source_refs) > 32:
        _fail("weekly record would exceed the 32-source digest limit")
    return {
        "schema_name": "us_short_market_diagnostic_weekly_record",
        "schema_version": "1.1.0",
        "decision_date": decision_date,
        "valuation_date": paper_week["valuation_date"],
        "windows_aligned": windows_aligned,
        "windows_misaligned_reason": (
            None if windows_aligned else "strategy_return_spans_a_no_count_week"
        ),
        "calendar_week_index": calendar_week_index,
        "window_id": packet["window_id"],
        "diagnostic_epoch": packet["diagnostic_epoch"],
        "diagnostic_policy_sha256": diagnostic_policy_sha256,
        "strategy_ruleset_fingerprint": strategy_ruleset_fingerprint,
        "strategy": {
            "paper_evaluable": nav["paper_evaluable"],
            "performance_status": nav["performance_status"],
            "strategy_evaluable": strategy_evaluable,
            "initial_capital": "100000.000000",
            "prior_nav": prior_nav,
            "nav": nav["nav"],
            "weekly_return": strategy_weekly_return,
            "cumulative_return": cumulative_return,
            "cash": nav["cash"],
            "market_value": nav["market_value"],
            "cumulative_cost_paid": nav["cumulative_cost_paid"],
            "turnover": None,
            "unfilled_order_count": paper_week["unfilled_order_count"],
            "no_count": False,
            "no_count_reason": None,
            "source_sha256": paper_week["digests"]["nav"],
            "degradation_reasons": list(nav["degradation_reasons"]),
        },
        "benchmarks": benchmarks,
        "v1_1_reminder": dict(reminder),
        "source_refs": source_refs,
        "boundary": dict(BOUNDARY),
    }


__all__ = [
    "LOCAL_ADAPTER_BOUNDARY",
    "LocalMarketDiagnosticAdapterError",
    "adapt_benchmark_week",
    "build_weekly_record_from_local",
    "load_model_paper_week",
    "validate_local_price_packet",
]
