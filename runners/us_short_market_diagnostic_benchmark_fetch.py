"""Knife 8 runner: land one week of benchmark ETF bars, then build the packet.

This is the network half of the Knife 8 pair. It exists because the frozen packet
schema pins ``boundary.provider_calls_performed`` to ``false``: a packet is only
well-formed if nothing was fetched while it was built, so the fetch has to happen
first, land as evidence, and be read back offline.

Per benchmark it writes ONE capture file and never rewrites it. A week already
captured is not re-fetched — that is what makes the weekly command idempotent and
what stops a re-run from quietly replacing the evidence a stored week was built
from. A symbol the vendor cannot serve still gets a capture, recording that it was
asked and came back empty; without that the whole week would have no provenance to
publish and the clock could not advance through an outage at all.

The runner never opens the clock, seeds an account, writes the diagnostic ledger,
or touches selection. Its only outputs are private capture files and one private
packet.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if _PYTHON_LIBS.exists() and str(_PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(_PYTHON_LIBS))

from engine.us_short_market_diagnostic import BENCHMARKS  # noqa: E402
from engine.us_short_market_diagnostic_benchmark_packet import (  # noqa: E402
    CAPTURE_SCHEMA_NAME,
    CAPTURE_SCHEMA_VERSION,
    FETCH_FAILED,
    FETCH_OK,
    BenchmarkPacketError,
    build_local_price_packet,
    validate_benchmark_capture,
)
from engine.us_short_model_paper_portfolio import (  # noqa: E402
    artifact_sha256,
    canonical_json_bytes,
)
from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path  # noqa: E402


DEFAULT_INPUTS_ROOT = ROOT / "state" / "us_short" / "market_diagnostic_inputs_private"
VENDOR = "yfinance"
PACKET_FILENAME = "benchmark_price_packet.json"


class BenchmarkFetchError(Exception):
    """The week cannot be captured or the packet cannot be built."""


def week_directory(decision_date: str, *, inputs_root: Path = DEFAULT_INPUTS_ROOT) -> Path:
    return Path(inputs_root).resolve() / "benchmark" / decision_date


def _write_private_json(path: Path, payload: Mapping[str, Any]) -> str:
    """Write once, never overwrite.

    Privacy is proven by ``capture_week`` on the whole week directory before any
    branch is taken, and every path here is that directory joined with a constant
    filename, so re-checking per file would be a second door for an input the
    first one already refused -- and two doors make it unclear which is real.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    payload_bytes = canonical_json_bytes(payload)
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as exc:
        raise BenchmarkFetchError(f"{path.name} already exists; captures are written once") from exc
    with os.fdopen(handle, "wb") as stream:
        stream.write(payload_bytes)
    return artifact_sha256(payload)


def _read_private_json(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkFetchError(f"{path.name} is not readable canonical JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise BenchmarkFetchError(f"{path.name} is not an object")
    return payload, artifact_sha256(payload)


def _yfinance_module() -> Any:
    try:
        import yfinance  # noqa: PLC0415 - imported here so the module loads without it
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise BenchmarkFetchError("yfinance is not installed in this interpreter") from exc
    return yfinance


def fetch_symbol_bars(
    symbol: str,
    *,
    start: str,
    end_exclusive: str,
    module: Any | None = None,
) -> list[dict[str, Any]]:
    """One vendor call for one symbol, returned as plain bars.

    ``auto_adjust=False`` is not a preference. With adjustment on, the close
    already carries the dividends, and the Knife 5 sidecar would later add the
    same cash again.
    """

    vendor = module if module is not None else _yfinance_module()
    frame = vendor.Ticker(symbol).history(
        start=start,
        end=end_exclusive,
        auto_adjust=False,
        actions=True,
        repair=False,
    )
    if frame is None or bool(getattr(frame, "empty", False)):
        return []
    bars: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        stamp = getattr(index, "date", None)
        day = stamp() if callable(stamp) else index
        bars.append(
            {
                "date": day.strftime("%Y%m%d"),
                "close": float(row["Close"]),
                "dividends": float(row.get("Dividends", 0.0) or 0.0),
                "splits": float(row.get("Stock Splits", 0.0) or 0.0),
                "capital_gains": float(row.get("Capital Gains", 0.0) or 0.0),
            }
        )
    return bars


def capture_symbol(
    symbol: str,
    *,
    start: str,
    end_exclusive: str,
    module: Any | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Capture one symbol, recording a failure as evidence instead of raising.

    A vendor outage degrades one symbol's week; it does not take down the other
    three, and it does not take down the weekly act. yfinance reads an unofficial
    endpoint that breaks periodically, so this is an expected path, not an
    exceptional one.
    """

    clock = now if now is not None else (lambda: datetime.now(timezone.utc))
    observed_at = clock().strftime("%Y-%m-%dT%H:%M:%SZ")
    status = FETCH_OK
    error_kind: str | None = None
    bars: list[dict[str, Any]] = []
    try:
        bars = fetch_symbol_bars(symbol, start=start, end_exclusive=end_exclusive, module=module)
    except Exception as exc:  # noqa: BLE001 - any vendor failure is one degraded symbol
        status = FETCH_FAILED
        error_kind = type(exc).__name__
        bars = []
    capture = {
        "schema_name": CAPTURE_SCHEMA_NAME,
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "symbol": symbol,
        "vendor": VENDOR,
        "auto_adjust": False,
        "observed_at": observed_at,
        "fetch_status": status,
        "error_kind": error_kind,
        "requested_start": start,
        "requested_end_exclusive": end_exclusive,
        "bars": bars,
    }
    validate_benchmark_capture(capture, symbol=symbol)
    return capture


def capture_week(
    *,
    decision_date: str,
    valuation_date: str,
    prior_valuation_date: str,
    calendar_week_index: int,
    settlement_decision_date: str,
    diagnostic_epoch: str,
    as_of_date: str | None = None,
    inputs_root: Path = DEFAULT_INPUTS_ROOT,
    module: Any | None = None,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Capture every benchmark for one week and build that week's packet."""

    directory = week_directory(decision_date, inputs_root=inputs_root)
    # Checked once, here, rather than only inside each write. A week whose
    # captures already exist takes the reuse branch and never writes anything, so
    # a guard that only sits on the write path lets a fully populated non-private
    # directory through in silence. Privacy is a property of the week's location,
    # not of one file operation.
    try:
        reject_nonprivate_output_path(directory)
    except PrivatePathError as exc:
        raise BenchmarkFetchError(f"refusing a non-private inputs directory: {exc}") from exc
    end_exclusive = (
        datetime.strptime(valuation_date, "%Y%m%d") + timedelta(days=1)
    ).strftime("%Y-%m-%d")
    start = datetime.strptime(prior_valuation_date, "%Y%m%d").strftime("%Y-%m-%d")

    captures: dict[str, dict[str, Any]] = {}
    reused: list[str] = []
    for symbol in BENCHMARKS:
        path = directory / f"{symbol}.json"
        if path.exists():
            # Already evidence. Re-fetching would spend a call to overwrite the
            # bytes a stored week may already have been built from.
            capture, digest = _read_private_json(path)
            validate_benchmark_capture(capture, symbol=symbol, as_of_date=as_of_date)
            captures[symbol] = {"capture": capture, "sha256": digest}
            reused.append(symbol)
            continue
        if dry_run:
            raise BenchmarkFetchError(
                f"--dry-run cannot capture {symbol}; it validates an already-captured week"
            )
        capture = capture_symbol(
            symbol, start=start, end_exclusive=end_exclusive, module=module, now=now
        )
        digest = _write_private_json(path, capture)
        captures[symbol] = {"capture": capture, "sha256": digest}

    try:
        packet = build_local_price_packet(
            captures=captures,
            calendar_week_index=calendar_week_index,
            decision_date=decision_date,
            settlement_decision_date=settlement_decision_date,
            valuation_date=valuation_date,
            prior_valuation_date=prior_valuation_date,
            diagnostic_epoch=diagnostic_epoch,
            as_of_date=as_of_date,
        )
    except BenchmarkPacketError as exc:
        raise BenchmarkFetchError(str(exc)) from exc

    packet_path = directory / PACKET_FILENAME
    if dry_run:
        return {
            "status": "dry_run",
            "packet_path": str(packet_path),
            "reused_captures": reused,
            "evaluable_symbols": _evaluable(packet),
        }
    if packet_path.exists():
        existing, _ = _read_private_json(packet_path)
        if canonical_json_bytes(existing) != canonical_json_bytes(packet):
            raise BenchmarkFetchError(
                "a different packet is already stored for this week; the week's inputs are immutable"
            )
        return {
            "status": "idempotent",
            "packet_path": str(packet_path),
            "reused_captures": reused,
            "evaluable_symbols": _evaluable(packet),
        }
    _write_private_json(packet_path, packet)
    return {
        "status": "captured",
        "packet_path": str(packet_path),
        "reused_captures": reused,
        "evaluable_symbols": _evaluable(packet),
    }


def _evaluable(packet: Mapping[str, Any]) -> list[str]:
    week = packet["weeks"][0]
    return [
        symbol
        for symbol in BENCHMARKS
        if week["benchmarks"][symbol]["close"] is not None
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--decision-date", required=True, help="YYYYMMDD")
    parser.add_argument("--valuation-date", required=True, help="YYYYMMDD")
    parser.add_argument("--prior-valuation-date", required=True, help="YYYYMMDD")
    parser.add_argument("--settlement-decision-date", required=True, help="YYYYMMDD")
    parser.add_argument("--calendar-week-index", required=True, type=int)
    parser.add_argument("--diagnostic-epoch", required=True)
    parser.add_argument("--as-of-date", help="YYYYMMDD; defaults to today so future bars fail closed")
    parser.add_argument("--inputs-root", type=Path, default=DEFAULT_INPUTS_ROOT)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="rebuild and validate an already-captured week without fetching or writing",
    )
    args = parser.parse_args(argv)
    as_of = args.as_of_date or datetime.now(timezone.utc).strftime("%Y%m%d")
    try:
        result = capture_week(
            decision_date=args.decision_date,
            valuation_date=args.valuation_date,
            prior_valuation_date=args.prior_valuation_date,
            settlement_decision_date=args.settlement_decision_date,
            calendar_week_index=args.calendar_week_index,
            diagnostic_epoch=args.diagnostic_epoch,
            as_of_date=as_of,
            inputs_root=args.inputs_root,
            dry_run=args.dry_run,
        )
    except (BenchmarkFetchError, BenchmarkPacketError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(
        f"{result['status']}: {result['packet_path']}  "
        f"evaluable={','.join(result['evaluable_symbols']) or 'none'}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
