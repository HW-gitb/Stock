from __future__ import annotations

import copy
from datetime import date, datetime, timezone
from pathlib import Path
import tempfile
import unittest

from engine.us_short_market_diagnostic import BENCHMARKS
from engine.us_short_market_diagnostic_benchmark_packet import (
    CAPTURE_SCHEMA_NAME,
    CAPTURE_SCHEMA_VERSION,
    FETCH_FAILED,
    FETCH_OK,
    BenchmarkPacketError,
    build_local_price_packet,
    validate_benchmark_capture,
)
from engine.us_short_market_diagnostic_local_adapter import validate_local_price_packet
from runners import us_short_market_diagnostic_benchmark_fetch as fetch

EPOCH = "us_short_market_diagnostic_26w_v1"
DECISION = "20260727"
VALUATION = "20260724"
PRIOR = "20260723"
SETTLEMENT = "20260720"
AS_OF = "20260806"


def _bar(day: str, close: float, *, dividends: float = 0.0, splits: float = 0.0, capital_gains: float = 0.0) -> dict:
    return {
        "date": day,
        "close": close,
        "dividends": dividends,
        "splits": splits,
        "capital_gains": capital_gains,
    }


def _capture(symbol: str, *, bars: list[dict] | None = None, status: str = FETCH_OK, **overrides) -> dict:
    capture = {
        "schema_name": CAPTURE_SCHEMA_NAME,
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "symbol": symbol,
        "vendor": "yfinance",
        "auto_adjust": False,
        "observed_at": "2026-08-06T12:00:00Z",
        "fetch_status": status,
        "error_kind": None,
        "requested_start": "2026-07-23",
        "requested_end_exclusive": "2026-07-25",
        "bars": [_bar(PRIOR, 100.0), _bar(VALUATION, 101.0)] if bars is None else bars,
    }
    capture.update(overrides)
    return capture


def _captures(**per_symbol) -> dict:
    """Four well-formed captures, with per-symbol overrides by keyword."""

    result = {}
    for index, symbol in enumerate(BENCHMARKS):
        capture = per_symbol.get(symbol, _capture(symbol))
        result[symbol] = {"capture": capture, "sha256": f"{(700 + index):064x}"}
    return result


def _build(captures=None, **overrides) -> dict:
    kwargs = dict(
        captures=_captures() if captures is None else captures,
        calendar_week_index=1,
        decision_date=DECISION,
        settlement_decision_date=SETTLEMENT,
        valuation_date=VALUATION,
        prior_valuation_date=PRIOR,
        diagnostic_epoch=EPOCH,
        as_of_date=AS_OF,
    )
    kwargs.update(overrides)
    return build_local_price_packet(**kwargs)


class BenchmarkCaptureTest(unittest.TestCase):
    def test_a_dividend_adjusted_capture_is_refused(self) -> None:
        """The one trap that silently doubles money.

        With ``auto_adjust=True`` the close already contains the dividends, so
        pairing it with a Knife 5 dividend sidecar counts the same cash twice.
        Nothing downstream can detect it: both numbers look like prices.
        """

        with self.assertRaises(BenchmarkPacketError) as ctx:
            validate_benchmark_capture(_capture("VTI", auto_adjust=True), symbol="VTI")
        self.assertIn("counted twice", str(ctx.exception))

    def test_a_capture_for_the_wrong_symbol_is_refused(self) -> None:
        with self.assertRaises(BenchmarkPacketError) as ctx:
            validate_benchmark_capture(_capture("SPY"), symbol="VTI")
        self.assertIn("not VTI", str(ctx.exception))

    def test_a_failed_capture_may_not_carry_bars(self) -> None:
        """Otherwise 'the fetch failed' and 'here are the prices' coexist."""

        capture = _capture("VTI", status=FETCH_FAILED)
        with self.assertRaises(BenchmarkPacketError) as ctx:
            validate_benchmark_capture(capture, symbol="VTI")
        self.assertIn("carries bars", str(ctx.exception))

    def test_a_bar_after_the_as_of_date_is_refused(self) -> None:
        capture = _capture("VTI", bars=[_bar(PRIOR, 100.0), _bar("20260901", 101.0)])
        with self.assertRaises(BenchmarkPacketError) as ctx:
            validate_benchmark_capture(capture, symbol="VTI", as_of_date=AS_OF)
        self.assertIn("after as_of_date", str(ctx.exception))

    def test_bars_must_be_ordered_and_distinct(self) -> None:
        for label, bars in (
            ("repeated", [_bar(PRIOR, 100.0), _bar(PRIOR, 101.0)]),
            ("backwards", [_bar(VALUATION, 101.0), _bar(PRIOR, 100.0)]),
        ):
            with self.subTest(label):
                with self.assertRaises(BenchmarkPacketError):
                    validate_benchmark_capture(_capture("VTI", bars=bars), symbol="VTI")

    def test_a_non_positive_close_is_corruption_not_absence(self) -> None:
        """An ETF never prints one, so treating it as 'missing' would hide a bad feed."""

        for bad in (0.0, -1.0):
            with self.subTest(close=bad):
                capture = _capture("VTI", bars=[_bar(PRIOR, 100.0), _bar(VALUATION, bad)])
                with self.assertRaises(BenchmarkPacketError) as ctx:
                    validate_benchmark_capture(capture, symbol="VTI")
                self.assertIn("positive finite price", str(ctx.exception))

    def test_a_negative_distribution_is_refused(self) -> None:
        capture = _capture("VTI", bars=[_bar(PRIOR, 100.0), _bar(VALUATION, 101.0, dividends=-1.0)])
        with self.assertRaises(BenchmarkPacketError):
            validate_benchmark_capture(capture, symbol="VTI")


class BenchmarkPacketTest(unittest.TestCase):
    def test_a_built_packet_satisfies_the_consumer_gate(self) -> None:
        """Built here, judged by settle-week's own validator, not by this test."""

        packet = _build()
        validate_local_price_packet(packet, as_of_date=AS_OF)
        self.assertEqual("26w-1-26", packet["window_id"])
        self.assertEqual(list(BENCHMARKS), packet["benchmark_symbols"])
        self.assertEqual("split_adjusted_close", packet["price_basis"])
        self.assertEqual(4, len(packet["source_refs"]))
        observation = packet["weeks"][0]["benchmarks"]["VTI"]
        self.assertEqual("101.000000", observation["close"])
        self.assertEqual("100.000000", observation["prior_close"])
        self.assertIsNone(observation["dividend_sidecar_sha256"])

    def test_a_symbol_left_out_of_the_mapping_is_refused(self) -> None:
        """Silent omission is the failure this whole track exists to catch."""

        captures = _captures()
        del captures["IWB"]
        with self.assertRaises(BenchmarkPacketError) as ctx:
            _build(captures)
        self.assertIn("exactly", str(ctx.exception))

    def test_a_missing_bar_becomes_null_on_both_legs_never_zero(self) -> None:
        """Half an observation invites a reader to compute a return from it."""

        for label, bars in (
            ("no close", [_bar(PRIOR, 100.0)]),
            ("no prior close", [_bar(VALUATION, 101.0)]),
            ("nothing at all", []),
        ):
            with self.subTest(label):
                packet = _build(_captures(VTI=_capture("VTI", bars=bars)))
                observation = packet["weeks"][0]["benchmarks"]["VTI"]
                self.assertEqual(
                    {"price_date", "prior_price_date", "prior_close", "close", "source_sha256"},
                    {key for key, value in observation.items() if value is None} - {"dividend_sidecar_sha256"},
                )
                self.assertEqual("missing", observation["source_kind"])
                # ...and the other three are untouched.
                self.assertEqual("101.000000", packet["weeks"][0]["benchmarks"]["SPY"]["close"])

    def test_a_total_vendor_outage_still_produces_a_publishable_week(self) -> None:
        """Section 2.2: a no_count week keeps its calendar slot.

        If an outage left the packet with no ``source_refs`` the schema would
        refuse it, ``settle-week`` would have no week to target, and the clock
        would stall until the vendor came back -- which is precisely the
        window-extension the design forbids. The evidence that we looked is what
        keeps the walk non-empty.
        """

        captures = _captures(
            **{symbol: _capture(symbol, status=FETCH_FAILED, bars=[]) for symbol in BENCHMARKS}
        )
        packet = _build(captures)
        validate_local_price_packet(packet, as_of_date=AS_OF)
        self.assertEqual(4, len(packet["source_refs"]))
        for symbol in BENCHMARKS:
            self.assertIsNone(packet["weeks"][0]["benchmarks"][symbol]["close"])

    def test_splits_and_capital_gains_are_captured_rather_than_refused(self) -> None:
        """A deliberate non-refusal, recorded so it is not mistaken for an oversight.

        ``price_basis`` is the constant ``split_adjusted_close`` and the vendor
        back-adjusts the series, so a split is handled BY the stated basis. A
        capital-gains distribution does not make a PRICE return wrong; it makes a
        TOTAL-return claim wrong, and total return arrives through the Knife 5
        sidecar, which reads the same capture. Refusing here would burn a calendar
        week over a non-problem.
        """

        capture = _capture(
            "VTI",
            bars=[_bar(PRIOR, 100.0), _bar(VALUATION, 101.0, splits=2.0, capital_gains=0.35)],
        )
        packet = _build(_captures(VTI=capture))
        self.assertEqual("101.000000", packet["weeks"][0]["benchmarks"]["VTI"]["close"])
        # The evidence is still reachable: the observation's digest is the capture's.
        self.assertIn(
            packet["weeks"][0]["benchmarks"]["VTI"]["source_sha256"], packet["source_refs"]
        )

    def test_the_week_dates_must_be_ordered(self) -> None:
        for label, override in (
            ("valuation after decision", {"valuation_date": "20260728"}),
            ("settlement after valuation", {"settlement_decision_date": "20260725"}),
            ("prior not before valuation", {"prior_valuation_date": VALUATION}),
        ):
            with self.subTest(label):
                with self.assertRaises(BenchmarkPacketError):
                    _build(**override)

    def test_an_empty_epoch_or_a_zero_week_index_is_refused(self) -> None:
        with self.assertRaises(BenchmarkPacketError):
            _build(diagnostic_epoch="")
        with self.assertRaises(BenchmarkPacketError):
            _build(calendar_week_index=0)

    def test_a_capture_without_its_digest_is_refused(self) -> None:
        captures = _captures()
        captures["VTI"] = {"capture": _capture("VTI")}
        with self.assertRaises(BenchmarkPacketError) as ctx:
            _build(captures)
        self.assertIn("sha256", str(ctx.exception))


class _FakeIndex:
    def __init__(self, day: date) -> None:
        self._day = day

    def date(self) -> date:
        return self._day


class _FakeFrame:
    def __init__(self, rows: list) -> None:
        self._rows = rows
        self.empty = not rows

    def iterrows(self):
        return iter(self._rows)


class _FakeTicker:
    def __init__(self, symbol: str, vendor: "_FakeVendor") -> None:
        self._symbol = symbol
        self._vendor = vendor

    def history(self, **kwargs):
        self._vendor.calls.append((self._symbol, kwargs))
        if self._symbol in self._vendor.broken:
            raise RuntimeError("vendor endpoint changed shape")
        rows = [
            (
                _FakeIndex(date(2026, 7, 23)),
                {"Close": 100.0, "Dividends": 0.0, "Stock Splits": 0.0, "Capital Gains": 0.0},
            ),
            (
                _FakeIndex(date(2026, 7, 24)),
                {"Close": 101.0, "Dividends": 0.25, "Stock Splits": 0.0, "Capital Gains": 0.0},
            ),
        ]
        return _FakeFrame(rows)


class _FakeVendor:
    def __init__(self, broken: set[str] | None = None) -> None:
        self.calls: list = []
        self.broken = broken or set()

    def Ticker(self, symbol: str) -> _FakeTicker:  # noqa: N802 - mirrors the vendor API
        return _FakeTicker(symbol, self)


class BenchmarkFetchRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        # Outside the repo: `reject_nonprivate_output_path` treats an external
        # absolute path as the operator's own private location.
        self.inputs = Path(holder.name) / "market_diagnostic_inputs_private"

    def _capture_week(self, vendor, **overrides):
        kwargs = dict(
            decision_date=DECISION,
            valuation_date=VALUATION,
            prior_valuation_date=PRIOR,
            settlement_decision_date=SETTLEMENT,
            calendar_week_index=1,
            diagnostic_epoch=EPOCH,
            as_of_date=AS_OF,
            inputs_root=self.inputs,
            module=vendor,
            now=lambda: datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc),
        )
        kwargs.update(overrides)
        return fetch.capture_week(**kwargs)

    def test_a_week_is_captured_once_and_never_re_fetched(self) -> None:
        """Idempotence with a cost: a re-run must not spend a call to overwrite
        the bytes a stored week was already built from."""

        vendor = _FakeVendor()
        first = self._capture_week(vendor)
        self.assertEqual("captured", first["status"])
        self.assertEqual(4, len(vendor.calls))
        self.assertEqual(list(BENCHMARKS), first["evaluable_symbols"])

        second = self._capture_week(vendor)
        self.assertEqual("idempotent", second["status"])
        self.assertEqual(4, len(vendor.calls), "a second run re-fetched the vendor")
        self.assertEqual(list(BENCHMARKS), second["reused_captures"])

    def test_auto_adjust_is_off_on_every_vendor_call(self) -> None:
        """The double-count trap, checked at the call site as well as the gate."""

        vendor = _FakeVendor()
        self._capture_week(vendor)
        for symbol, kwargs in vendor.calls:
            with self.subTest(symbol):
                self.assertFalse(kwargs["auto_adjust"])
                self.assertTrue(kwargs["actions"], "dividends are the Knife 5 evidence")

    def test_one_broken_symbol_degrades_only_itself(self) -> None:
        vendor = _FakeVendor(broken={"IWB"})
        result = self._capture_week(vendor)
        self.assertEqual("captured", result["status"])
        self.assertEqual(["VTI", "SPY", "QQQ"], result["evaluable_symbols"])
        stored = fetch.week_directory(DECISION, inputs_root=self.inputs) / "IWB.json"
        self.assertTrue(stored.exists(), "a failed fetch still leaves its evidence")

    def test_a_dry_run_of_an_uncaptured_week_writes_nothing(self) -> None:
        with self.assertRaises(fetch.BenchmarkFetchError):
            self._capture_week(_FakeVendor(), dry_run=True)
        self.assertFalse(fetch.week_directory(DECISION, inputs_root=self.inputs).exists())

    def test_a_dry_run_revalidates_a_captured_week_without_fetching(self) -> None:
        vendor = _FakeVendor()
        self._capture_week(vendor)
        result = self._capture_week(vendor, dry_run=True)
        self.assertEqual("dry_run", result["status"])
        self.assertEqual(4, len(vendor.calls))

    def test_a_capture_file_is_written_once_and_refuses_a_second_write(self) -> None:
        """The last line of defence, and the ordinary path never reaches it.

        Every normal re-run is stopped by the ``exists()`` check above, so this
        one had no coverage at all: downgrading the exclusive create to a
        truncating one left every other test green while making a stored week's
        evidence quietly replaceable.
        """

        path = fetch.week_directory(DECISION, inputs_root=self.inputs) / "VTI.json"
        digest = fetch.write_private_json_once(path, _capture("VTI"))
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        with self.assertRaises(fetch.BenchmarkFetchError) as ctx:
            fetch.write_private_json_once(path, _capture("VTI", observed_at="2026-08-07T12:00:00Z"))
        self.assertIn("written once", str(ctx.exception))
        self.assertIn('"2026-08-06T12:00:00Z"', path.read_text(encoding="utf-8"))

    def test_a_non_private_destination_is_refused_before_anything_is_fetched(self) -> None:
        """Checked on the week's directory, not on each write.

        A week whose captures already exist takes the reuse branch and writes
        nothing, so a guard living only on the write path would let a populated
        non-private directory through in silence. What separates the two
        placements is measured here WITHOUT writing anything into the tree: an
        up-front guard refuses having asked the vendor nothing, while a
        write-path one would have spent four requests first.
        """

        vendor = _FakeVendor()
        outside = Path(fetch.ROOT) / "docs"
        with self.assertRaises(fetch.BenchmarkFetchError) as ctx:
            self._capture_week(vendor, inputs_root=outside)
        self.assertIn("non-private", str(ctx.exception))
        self.assertEqual([], vendor.calls, "it reached the vendor before refusing")
        self.assertFalse((outside / "benchmark").exists(), "the refusal left bytes behind")

    def test_a_conflicting_packet_for_the_same_week_is_refused(self) -> None:
        """Same captures, different week identity: the inputs of a week are immutable."""

        vendor = _FakeVendor()
        self._capture_week(vendor)
        with self.assertRaises(fetch.BenchmarkFetchError) as ctx:
            self._capture_week(vendor, diagnostic_epoch="some_other_epoch")
        self.assertIn("immutable", str(ctx.exception))


class BenchmarkPacketEndToEndTest(unittest.TestCase):
    """The acceptance criterion: this packet really settles a week."""

    def test_a_built_packet_settles_a_real_week_on_a_rehearsal_store(self) -> None:
        from engine.us_short_market_diagnostic_lifecycle import load_lifecycle_register
        from engine.us_short_market_diagnostic_start_receipt import issue_start_receipt
        from engine.us_short_market_diagnostic_weekly_producer import settle_next_week
        from tests.test_us_short_market_diagnostic_local_adapter import _start_local_paper_store

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            store = base / "market_diagnostic_private"
            paper = base / "model_paper_private"
            _start_local_paper_store(paper)
            issue_start_receipt(
                diagnostic_epoch=EPOCH,
                completion_notification={
                    "issued_at": "2026-07-24T00:00:00+00:00",
                    "issuer": "codex",
                    "notification_text": "US-short 26-week diagnostic design is complete; open the clock.",
                },
                first_decision_date=DECISION,
                root=store,
            )
            packet = _build()
            result = settle_next_week(
                model_paper_root=paper,
                benchmark_packet=packet,
                root=store,
                as_of_date=AS_OF,
            )
            self.assertEqual("published", result["status"])
            self.assertEqual(1, result["calendar_week_index"])
            register = load_lifecycle_register(store, as_of_date=AS_OF)
            self.assertEqual(1, register["calendar_week_count"])
            self.assertEqual(EPOCH, register["diagnostic_epoch"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
