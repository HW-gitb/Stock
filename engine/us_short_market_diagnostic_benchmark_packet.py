"""Knife 8: turn already-captured local ETF bars into one weekly benchmark price packet.

Knife 7b landed ``settle-week`` and its docstring said the quiet part out loud:
the benchmark packet "is a file the caller names because nothing in the repo
produces one yet".  This module is that producer's offline half.

The split between this module and its fetch runner is not stylistic — the frozen
packet schema pins ``boundary.provider_calls_performed`` to the constant
``false``, so a packet is only well-formed if no provider was called while it was
built.  Network access therefore lives entirely in the runner, which lands one
capture file per benchmark; this module reads those files and nothing else.

One packet describes ONE decision week.  A cumulative packet would put every
week's raw digest into ``source_refs``, and the weekly record that consumes it
caps its rolled-up provenance at 32 digests — the same ceiling that made Knife 6
unreachable at week 24 before it was found.  Four digests a week stays clear of
it forever.

What this module deliberately does NOT refuse:

* a stock split — the packet's ``price_basis`` is the constant
  ``split_adjusted_close`` and the vendor back-adjusts the whole series, so a
  split is handled by the stated basis rather than a defect against it;
* a capital-gains distribution — this packet publishes PRICE return, which a
  distribution does not make wrong.  It makes a TOTAL-return claim wrong, and
  total return arrives through the Knife 5 sidecar, which is captured in the
  same gated weekly step and bound to this packet before settlement.

Both are captured, digest-bound and discoverable rather than silently dropped.
The one thing that IS refused is a capture taken with dividend adjustment on:
those closes already contain the dividends, so pairing them with a dividend
sidecar later would count the same cash twice.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from engine.us_short_market_diagnostic import BENCHMARKS, window_containing_week
from engine.us_short_market_diagnostic_local_adapter import (
    LOCAL_ADAPTER_BOUNDARY,
    LocalMarketDiagnosticAdapterError,
    validate_local_price_packet,
)


CAPTURE_SCHEMA_NAME = "us_short_market_diagnostic_benchmark_capture"
CAPTURE_SCHEMA_VERSION = "1.0.0"
PACKET_SCHEMA_NAME = "us_short_market_diagnostic_local_price_packet"
PACKET_SCHEMA_VERSION = "1.1.0"
PRICE_BASIS = "split_adjusted_close"
# `local_etf_price_packet` is the enum member for "this price came from a
# dedicated local ETF file" — which is exactly what a capture is. The vendor is
# not encoded here; it is recorded inside the capture the digest points at.
SOURCE_KIND_PRESENT = "local_etf_price_packet"
SOURCE_KIND_MISSING = "missing"

FETCH_OK = "ok"
FETCH_FAILED = "failed"

_DATE8 = re.compile(r"^[0-9]{8}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL_LIKE = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")


class BenchmarkPacketError(Exception):
    """A capture or a packet-build request that cannot be trusted."""


def _fail(message: str) -> None:
    raise BenchmarkPacketError(message)


def _date8(value: object, field: str) -> date:
    if not isinstance(value, str) or _DATE8.fullmatch(value) is None:
        _fail(f"{field} must be YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").date()  # type: ignore[arg-type]
    except ValueError as exc:
        raise BenchmarkPacketError(f"{field} is not a real date") from exc


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(f"{field} must be a lowercase sha256")
    return value  # type: ignore[return-value]


def _money(value: object, field: str) -> str:
    """Six-decimal positive money, from a vendor float or a decimal string.

    Goes through ``Decimal(str(...))`` rather than ``Decimal(float)`` so a price
    of 379.65 becomes 379.650000 and not the binary expansion beneath it.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        _fail(f"{field} must be a number or a decimal string")
    text = value if isinstance(value, str) else repr(float(value))
    if isinstance(value, str) and _DECIMAL_LIKE.fullmatch(value) is None:
        _fail(f"{field} is not a decimal number")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise BenchmarkPacketError(f"{field} is not a decimal number") from exc
    if not amount.is_finite() or amount <= 0:
        # A non-positive or non-finite close is corruption, not absence: a real
        # ETF never prints one, so treating it as "missing" would hide a bad feed.
        _fail(f"{field} must be a positive finite price, got {value!r}")
    return f"{amount.quantize(Decimal('0.000001')):f}"


def _optional_amount(value: object, field: str) -> Decimal:
    """Dividends / splits / capital gains: zero is normal, negative is not."""

    if value is None:
        return Decimal(0)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        _fail(f"{field} must be a number")
    try:
        amount = Decimal(value if isinstance(value, str) else repr(float(value)))
    except InvalidOperation as exc:
        raise BenchmarkPacketError(f"{field} is not a decimal number") from exc
    if not amount.is_finite() or amount < 0:
        _fail(f"{field} must be a non-negative finite number, got {value!r}")
    return amount


def validate_benchmark_capture(capture: object, *, symbol: str, as_of_date: str | None = None) -> dict[str, Any]:
    """Validate one landed capture file and return it unchanged.

    A capture is written for every benchmark every week, INCLUDING a week the
    vendor could not serve. The evidence that we looked and found nothing is
    provenance too, and without it a total outage would leave the packet with an
    empty ``source_refs`` — which the schema forbids, so the clock could not
    advance through the outage at all.
    """

    if not isinstance(capture, Mapping):
        _fail(f"{symbol} capture must be an object")
    if capture.get("schema_name") != CAPTURE_SCHEMA_NAME:
        _fail(f"{symbol} capture schema_name is not {CAPTURE_SCHEMA_NAME}")
    if capture.get("schema_version") != CAPTURE_SCHEMA_VERSION:
        _fail(f"{symbol} capture schema_version is not {CAPTURE_SCHEMA_VERSION}")
    if capture.get("symbol") != symbol:
        _fail(f"capture is for {capture.get('symbol')!r}, not {symbol}")
    if capture.get("auto_adjust") is not False:
        # The whole reason this is checked rather than assumed. With adjustment
        # ON the close already contains the dividends, so a later total-return
        # sidecar would add the same cash a second time.
        _fail(
            f"{symbol} capture must declare auto_adjust=false; adjusted closes already "
            "contain their dividends and would be counted twice"
        )
    status = capture.get("fetch_status")
    if status not in {FETCH_OK, FETCH_FAILED}:
        _fail(f"{symbol} capture fetch_status must be {FETCH_OK!r} or {FETCH_FAILED!r}")
    if not isinstance(capture.get("vendor"), str) or not capture["vendor"]:
        _fail(f"{symbol} capture must name its vendor")
    observed = capture.get("observed_at")
    if not isinstance(observed, str) or not observed.endswith("Z"):
        _fail(f"{symbol} capture observed_at must be a UTC timestamp ending in Z")
    bars = capture.get("bars")
    if not isinstance(bars, list):
        _fail(f"{symbol} capture bars must be a list")
    if status == FETCH_FAILED and bars:
        _fail(f"{symbol} capture claims the fetch failed but carries bars")
    as_of = _date8(as_of_date, "as_of_date") if as_of_date is not None else None
    seen: set[str] = set()
    previous: date | None = None
    for index, raw_bar in enumerate(bars):
        field = f"{symbol} capture bars[{index}]"
        if not isinstance(raw_bar, Mapping):
            _fail(f"{field} must be an object")
        bar_date = _date8(raw_bar.get("date"), f"{field}.date")
        if raw_bar["date"] in seen:
            _fail(f"{field}.date is repeated")
        seen.add(raw_bar["date"])
        if previous is not None and bar_date <= previous:
            _fail(f"{field}.date must be strictly increasing")
        previous = bar_date
        if as_of is not None and bar_date > as_of:
            _fail(f"{field}.date is after as_of_date")
        _money(raw_bar.get("close"), f"{field}.close")
        for name in ("dividends", "splits", "capital_gains"):
            _optional_amount(raw_bar.get(name), f"{field}.{name}")
    return dict(capture)


def _bar_close(capture: Mapping[str, Any], day: date) -> str | None:
    for bar in capture["bars"]:
        if bar["date"] == day.strftime("%Y%m%d"):
            return _money(bar["close"], "bar.close")
    return None


def _missing_observation() -> dict[str, Any]:
    return {
        "price_date": None,
        "prior_price_date": None,
        "prior_close": None,
        "close": None,
        "source_kind": SOURCE_KIND_MISSING,
        "source_sha256": None,
        "dividend_sidecar_sha256": None,
    }


def build_local_price_packet(
    *,
    captures: Mapping[str, Mapping[str, Any]],
    calendar_week_index: int,
    decision_date: str,
    settlement_decision_date: str,
    valuation_date: str,
    prior_valuation_date: str,
    diagnostic_epoch: str,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Build and self-validate one week's benchmark price packet.

    ``captures`` maps every benchmark symbol to ``{"capture": ..., "sha256": ...}``.
    All four must be named: a symbol quietly left out of the mapping is exactly the
    silent-omission failure this track exists to catch, so it is refused rather
    than treated as missing.
    """

    if not isinstance(calendar_week_index, int) or isinstance(calendar_week_index, bool):
        _fail("calendar_week_index must be an integer")
    if calendar_week_index < 1:
        _fail("calendar_week_index must be at least 1")
    if not isinstance(diagnostic_epoch, str) or not diagnostic_epoch:
        _fail("diagnostic_epoch must be a non-empty string")
    if not isinstance(captures, Mapping) or set(captures) != set(BENCHMARKS):
        _fail(f"captures must name exactly {', '.join(BENCHMARKS)}")

    decision = _date8(decision_date, "decision_date")
    settlement = _date8(settlement_decision_date, "settlement_decision_date")
    valuation = _date8(valuation_date, "valuation_date")
    prior_valuation = _date8(prior_valuation_date, "prior_valuation_date")
    if valuation > decision:
        _fail("valuation_date cannot be after decision_date")
    if settlement > valuation:
        _fail("settlement_decision_date cannot be after valuation_date")
    if prior_valuation >= valuation:
        _fail("prior_valuation_date must be strictly before valuation_date")

    window_id = window_containing_week(calendar_week_index)["window_id"]

    observations: dict[str, dict[str, Any]] = {}
    source_refs: list[str] = []
    for symbol in BENCHMARKS:
        entry = captures[symbol]
        if not isinstance(entry, Mapping) or "capture" not in entry or "sha256" not in entry:
            _fail(f"captures[{symbol}] must carry both its capture and its sha256")
        digest = _sha(entry["sha256"], f"captures[{symbol}].sha256")
        capture = validate_benchmark_capture(entry["capture"], symbol=symbol, as_of_date=as_of_date)
        # The digest of the attempt joins the walk whether or not it found a bar,
        # so an outage week still carries the evidence that it was looked for.
        if digest not in source_refs:
            source_refs.append(digest)
        close = _bar_close(capture, valuation) if capture["fetch_status"] == FETCH_OK else None
        prior_close = _bar_close(capture, prior_valuation) if capture["fetch_status"] == FETCH_OK else None
        if close is None or prior_close is None:
            # Missing stays missing on BOTH legs: a close without its prior close
            # cannot produce a weekly return, and half an observation invites a
            # reader to compute one anyway.
            observations[symbol] = _missing_observation()
            continue
        observations[symbol] = {
            "price_date": valuation.strftime("%Y%m%d"),
            "prior_price_date": prior_valuation.strftime("%Y%m%d"),
            "prior_close": prior_close,
            "close": close,
            "source_kind": SOURCE_KIND_PRESENT,
            "source_sha256": digest,
            # Price return only. Section 3.5 keeps strict total return behind the
            # four-ETF reconciliation, so this stays null and the week is honestly
            # labelled price_return_diagnostic downstream.
            "dividend_sidecar_sha256": None,
        }

    packet = {
        "schema_name": PACKET_SCHEMA_NAME,
        "schema_version": PACKET_SCHEMA_VERSION,
        "window_id": window_id,
        "diagnostic_epoch": diagnostic_epoch,
        "price_basis": PRICE_BASIS,
        "benchmark_symbols": list(BENCHMARKS),
        "weeks": [
            {
                "calendar_week_index": calendar_week_index,
                "decision_date": decision.strftime("%Y%m%d"),
                "settlement_decision_date": settlement.strftime("%Y%m%d"),
                "valuation_date": valuation.strftime("%Y%m%d"),
                "benchmarks": observations,
            }
        ],
        "source_refs": sorted(source_refs),
        "boundary": dict(LOCAL_ADAPTER_BOUNDARY),
    }
    try:
        # Built here, judged by the consumer's own gate. If the two ever drift,
        # this producer stops rather than emitting something settle-week refuses.
        validate_local_price_packet(packet, as_of_date=as_of_date)
    except LocalMarketDiagnosticAdapterError as exc:
        raise BenchmarkPacketError(f"the built packet fails the consumer's gate: {exc}") from exc
    return packet
