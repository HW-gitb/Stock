import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import runners.forward_tracker as forward_tracker


def _trade_dates(start: str = "20240131", periods: int = 30) -> list[str]:
    return pd.bdate_range(start, periods=periods).strftime("%Y%m%d").tolist()


def _cache_payload(
    benchmarks: dict[str, pd.DataFrame],
    stock_trade_dates: list[str] | None = None,
    meta_end_date: str | None = None,
) -> dict:
    stock_trade_dates = stock_trade_dates or _trade_dates()
    meta_end_date = meta_end_date or stock_trade_dates[-1]
    return {
        "meta": {
            "start_date": "20240101",
            "end_date": meta_end_date,
            "adj": "qfq_via_adj_factor",
            "benchmarks": sorted(forward_tracker.BENCHMARKS.keys()),
        },
        "stocks": pd.DataFrame([
            {"ts_code": "000001.SZ", "trade_date": trade_date}
            for trade_date in stock_trade_dates
        ]),
        "limits": pd.DataFrame([
            {"ts_code": "000001.SZ", "trade_date": trade_date}
            for trade_date in stock_trade_dates
        ]),
        "benchmarks": benchmarks,
    }


def _settlement_cache_payload(
    stock_trade_dates: list[str],
    *,
    meta_end_date: str,
    ts_code: str = "000001.SZ",
) -> dict:
    """Build a small same-anchor cache with real stock rows for backfill tests."""
    stocks = pd.DataFrame([
        {
            "ts_code": ts_code,
            "trade_date": trade_date,
            "open": 10.0,
            "close": 11.0,
            "adj_factor": 1.0,
        }
        for trade_date in stock_trade_dates
    ])
    same_anchor = pd.DataFrame([
        {"trade_date": trade_date, "open": 3000.0, "close": 3010.0}
        for trade_date in stock_trade_dates
    ])
    return {
        "meta": {
            "start_date": stock_trade_dates[0],
            "end_date": meta_end_date,
            "adj": "qfq_via_adj_factor",
            "benchmarks": sorted(forward_tracker.BENCHMARKS.keys()),
        },
        "stocks": stocks,
        "limits": pd.DataFrame([
            {"ts_code": ts_code, "trade_date": trade_date, "up_limit": 100.0}
            for trade_date in stock_trade_dates
        ]),
        "benchmarks": {
            name: same_anchor.copy() for name in forward_tracker.BENCHMARKS
        },
    }


def _tracker_row(
    as_of: str,
    ts_code: str,
    *,
    run_date: str | None = None,
    price_data_through: str | None = None,
    run_revision_id: str | None = None,
) -> dict:
    row = {col: pd.NA for col in forward_tracker.SCHEMA_COLUMNS}
    row.update({
        "as_of": as_of,
        "captured_at": "2026-06-01T00:00:00+00:00",
        "run_date": run_date,
        "price_data_through": price_data_through,
        "ts_code": ts_code,
        "name": ts_code,
        "tier": "Tier1",
        "final_score": 60,
        "ret_5d_status": "pending_capture",
        "ret_10d_status": "pending_capture",
        "ret_20d_status": "pending_capture",
        "run_revision_id": run_revision_id,
    })
    return row


class ForwardTrackerCacheGuardTests(unittest.TestCase):
    def test_official_backfill_keeps_each_due_date_revision_not_only_current_invocation(self) -> None:
        old_revision = "a" * 32
        current_revision = "b" * 32
        nonofficial_revision = "c" * 32
        frame = pd.DataFrame([
            _tracker_row("20240131", "000001.SZ", run_revision_id=old_revision),
            _tracker_row("20240201", "000002.SZ", run_revision_id=current_revision),
            _tracker_row("20240202", "000003.SZ", run_revision_id=nonofficial_revision),
            _tracker_row("20240203", "000004.SZ"),
        ])

        def selected(_root, as_of, *, require):
            return {
                "20240131": {"selected_revision_id": old_revision},
                "20240201": {"selected_revision_id": current_revision},
                "20240202": {"selected_revision_id": old_revision},
                "20240203": {"selected_revision_id": old_revision},
            }.get(str(as_of))

        with patch.object(forward_tracker, "resolve_official_revision", side_effect=selected):
            filtered = forward_tracker._filter_official_revision(
                frame, Path("/tmp/official"), current_revision,
            )

        self.assertEqual(filtered["ts_code"].tolist(), ["000001.SZ", "000002.SZ"])
        self.assertEqual(filtered["run_revision_id"].tolist(), [old_revision, current_revision])

    def _write_cache(
        self,
        path: Path,
        benchmarks: dict[str, pd.DataFrame],
        stock_trade_dates: list[str] | None = None,
        meta_end_date: str | None = None,
    ) -> None:
        with path.open("wb") as f:
            pickle.dump(
                _cache_payload(
                    benchmarks,
                    stock_trade_dates=stock_trade_dates,
                    meta_end_date=meta_end_date,
                ),
                f,
            )

    def test_cache_coverage_rejects_close_only_benchmark_frames_before_refetch(self) -> None:
        close_only = pd.DataFrame([
            {"trade_date": "20240131", "close": 3000.0},
            {"trade_date": "20240229", "close": 3100.0},
        ])
        benchmarks = {name: close_only.copy() for name in forward_tracker.BENCHMARKS}

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            self._write_cache(cache_path, benchmarks)
            with patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path):
                ok, msg = forward_tracker._check_cache_coverage(["20240131"], 20)

        self.assertFalse(ok)
        self.assertIn("same-anchor", msg)
        self.assertIn("trade_date/open/close", msg)
        self.assertIn("csi300", msg)
        self.assertIn("csi1000", msg)

    def test_cache_coverage_accepts_same_anchor_benchmark_frames(self) -> None:
        same_anchor = pd.DataFrame([
            {"trade_date": "20240131", "open": 3000.0, "close": 3010.0},
            {"trade_date": "20240229", "open": 3050.0, "close": 3100.0},
        ])
        benchmarks = {name: same_anchor.copy() for name in forward_tracker.BENCHMARKS}

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            self._write_cache(cache_path, benchmarks)
            with patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path):
                ok, msg = forward_tracker._check_cache_coverage(["20240131"], 20)

        self.assertTrue(ok)
        self.assertEqual(msg, "ok")

    def test_cache_coverage_rejects_when_cached_trading_dates_do_not_reach_window(self) -> None:
        same_anchor = pd.DataFrame([
            {"trade_date": "20240131", "open": 3000.0, "close": 3010.0},
            {"trade_date": "20240229", "open": 3050.0, "close": 3100.0},
        ])
        benchmarks = {name: same_anchor.copy() for name in forward_tracker.BENCHMARKS}

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            self._write_cache(
                cache_path,
                benchmarks,
                stock_trade_dates=["20240131", "20240201", "20240202"],
                meta_end_date="20240229",
            )
            with patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path):
                ok, msg = forward_tracker._check_cache_coverage(["20240131"], 5)

        self.assertFalse(ok)
        self.assertIn("trading-date coverage insufficient", msg)
        self.assertIn("needs +5 trading days", msg)

    def test_cache_coverage_uses_cached_trading_dates_not_calendar_range(self) -> None:
        same_anchor = pd.DataFrame([
            {"trade_date": "20240131", "open": 3000.0, "close": 3010.0},
            {"trade_date": "20240229", "open": 3050.0, "close": 3100.0},
        ])
        benchmarks = {name: same_anchor.copy() for name in forward_tracker.BENCHMARKS}

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            self._write_cache(
                cache_path,
                benchmarks,
                stock_trade_dates=["20240131", "20240219", "20240220", "20240221"],
                meta_end_date="20240205",
            )
            with patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path):
                ok, msg = forward_tracker._check_cache_coverage(["20240131"], 3)

        self.assertTrue(ok)
        self.assertEqual(msg, "ok")

    def test_cache_coverage_rejects_missing_asof_trading_date(self) -> None:
        same_anchor = pd.DataFrame([
            {"trade_date": "20240131", "open": 3000.0, "close": 3010.0},
            {"trade_date": "20240229", "open": 3050.0, "close": 3100.0},
        ])
        benchmarks = {name: same_anchor.copy() for name in forward_tracker.BENCHMARKS}

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            self._write_cache(
                cache_path,
                benchmarks,
                stock_trade_dates=["20240201", "20240202", "20240205", "20240206"],
            )
            with patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path):
                ok, msg = forward_tracker._check_cache_coverage(["20240131"], 2)

        self.assertFalse(ok)
        self.assertIn("missing as_of trading dates: 20240131", msg)

    def test_benchmark_cache_hint_uses_benchmark_only_helper(self) -> None:
        hint = "\n".join(
            forward_tracker._cache_refresh_hint(
                "forward_daily cache benchmark input is not same-anchor ready"
            )
        )

        self.assertIn("refresh_forward_daily_benchmark_open_tushare.py", hint)
        self.assertIn("CSI300/CSI1000 index_daily", hint)
        self.assertNotIn("--refresh-forward-daily", hint)

    def test_mature_as_ofs_ignores_terminal_failure_statuses(self) -> None:
        df = pd.DataFrame(
            [
                _tracker_row("20240131", "000001.SZ"),
                _tracker_row("20240201", "000002.SZ"),
            ]
        )
        for window in [5, 10, 20]:
            df.at[0, f"ret_{window}d_status"] = "pending_missing_future_close"
            df.at[1, f"ret_{window}d_status"] = "pending_capture"

        mature = forward_tracker._mature_as_ofs(df, "20240301", [5, 10, 20])

        self.assertEqual(mature, ["20240201"])

    def test_write_tracker_uses_same_directory_temp_file_and_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker_path = Path(tmp) / "forward_tracker.csv"
            df = pd.DataFrame([
                _tracker_row("20240202", "000002.SZ"),
                _tracker_row("20240131", "000001.SZ"),
            ])

            with (
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(forward_tracker.os, "replace", wraps=forward_tracker.os.replace) as replace_spy,
            ):
                forward_tracker._write_tracker(df)

            replace_spy.assert_called_once()
            tmp_arg, target_arg = replace_spy.call_args.args
            tmp_path = Path(tmp_arg)
            self.assertEqual(Path(target_arg), tracker_path)
            self.assertEqual(tmp_path.parent, tracker_path.parent)
            self.assertTrue(tmp_path.name.startswith(f".{tracker_path.name}."))
            self.assertTrue(tmp_path.name.endswith(".tmp"))
            self.assertFalse(tmp_path.exists())

            written = pd.read_csv(tracker_path, dtype={"as_of": str, "ts_code": str})
            self.assertEqual(list(written.columns), forward_tracker.SCHEMA_COLUMNS)
            self.assertEqual(written["as_of"].tolist(), ["20240131", "20240202"])
            self.assertEqual(written["ts_code"].tolist(), ["000001.SZ", "000002.SZ"])

    def test_write_tracker_preserves_existing_file_when_csv_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker_path = Path(tmp) / "forward_tracker.csv"
            tracker_path.write_text("original\n", encoding="utf-8")
            df = pd.DataFrame([_tracker_row("20240131", "000001.SZ")])

            with (
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(pd.DataFrame, "to_csv", side_effect=RuntimeError("boom")),
            ):
                with self.assertRaises(RuntimeError):
                    forward_tracker._write_tracker(df)

            self.assertEqual(tracker_path.read_text(encoding="utf-8"), "original\n")
            self.assertEqual(list(tracker_path.parent.glob(f".{tracker_path.name}.*.tmp")), [])

    def test_partition_asof_coverage_passes_every_cached_asof_to_attach(self) -> None:
        same_anchor = pd.DataFrame([
            {"trade_date": "20260105", "open": 3000.0, "close": 3010.0},
            {"trade_date": "20260112", "open": 3050.0, "close": 3100.0},
        ])
        benchmarks = {name: same_anchor.copy() for name in forward_tracker.BENCHMARKS}
        # 6 cached trading dates.
        stock_dates = ["20260105", "20260106", "20260107", "20260108", "20260109", "20260112"]

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            self._write_cache(cache_path, benchmarks, stock_trade_dates=stock_dates)
            with patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path):
                ready, needs_refresh, immature, cached, block = forward_tracker._partition_asof_coverage(
                    ["20260112", "20260105", "20260201"], max_window=3
                )

        self.assertIsNone(block)
        self.assertIsNotNone(cached)
        self.assertEqual(ready, ["20260105", "20260112"])
        self.assertEqual(immature, [])
        self.assertEqual(needs_refresh, ["20260201"])  # absent from cache -> stale, refresh helps

    def test_backfill_passes_cached_cohorts_to_attach_without_max_window_gate(self) -> None:
        # A missing +20 row must not stop attach_forward_returns from settling
        # real +5/+10 rows for the same cached cohort.
        stock_dates = pd.bdate_range("20260105", periods=9).strftime("%Y%m%d").tolist()
        ready_asof, partial_asof = stock_dates[0], stock_dates[7]
        same_anchor = pd.DataFrame([
            {"trade_date": stock_dates[0], "open": 3000.0, "close": 3010.0},
            {"trade_date": stock_dates[-1], "open": 3050.0, "close": 3100.0},
        ])
        benchmarks = {name: same_anchor.copy() for name in forward_tracker.BENCHMARKS}

        seen = {}

        def _attach_spy(work, windows, payload):
            seen["as_ofs"] = sorted(work["as_of"].astype(str).unique().tolist())
            work = work.copy()
            work["entry_date"] = stock_dates[1]
            work["entry_unbuyable_reason"] = pd.NA
            for w in windows:
                work[f"ret_{w}d_status"] = "ok"
                work[f"ret_{w}d_t1_net"] = 0.05
                for b in forward_tracker.BENCHMARKS:
                    work[f"ret_{w}d_excess_{b}"] = 0.01
            return work

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            tracker_path = Path(tmp) / "forward_tracker.csv"
            self._write_cache(cache_path, benchmarks, stock_trade_dates=stock_dates)
            df = pd.DataFrame([
                _tracker_row(ready_asof, "000001.SZ"),
                _tracker_row(partial_asof, "000002.SZ"),
            ])
            with patch.object(forward_tracker, "TRACKER_CSV", tracker_path):
                forward_tracker._write_tracker(df)
            with (
                patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path),
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(forward_tracker, "_today_yyyymmdd", return_value="20260301"),
                patch.object(forward_tracker, "attach_forward_returns", side_effect=_attach_spy),
            ):
                rc = forward_tracker.backfill([5])
            written = pd.read_csv(tracker_path, dtype={"as_of": str, "ts_code": str}).set_index("as_of")

        self.assertEqual(rc, 0)
        self.assertEqual(seen["as_ofs"], [ready_asof, partial_asof])
        self.assertEqual(written.loc[ready_asof, "ret_5d_status"], "ok")            # settled
        self.assertEqual(written.loc[partial_asof, "ret_5d_status"], "ok")            # also passed through

    def test_backfill_classifies_stale_windows_by_calendar_age_after_partial_write(self) -> None:
        # Cache ends 20260731 while the run is 20260809.  Short windows with
        # real rows settle; only calendar-mature missing windows stall.
        stock_dates = pd.bdate_range("20260622", "20260731").strftime("%Y%m%d").tolist()
        cohorts = ["20260706", "20260713", "20260720", "20260727"]

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            tracker_path = Path(tmp) / "forward_tracker.csv"
            with cache_path.open("wb") as handle:
                pickle.dump(
                    _settlement_cache_payload(stock_dates, meta_end_date="20260803"),
                    handle,
                )
            with patch.object(forward_tracker, "TRACKER_CSV", tracker_path):
                forward_tracker._write_tracker(
                    pd.DataFrame([_tracker_row(as_of, "000001.SZ") for as_of in cohorts])
                )

            with (
                patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path),
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(forward_tracker, "_today_yyyymmdd", return_value="20260809"),
            ):
                rc = forward_tracker.backfill([5, 10, 20])
            written = pd.read_csv(tracker_path, dtype={"as_of": str}).set_index("as_of")

        self.assertEqual(rc, forward_tracker.EXIT_LEDGER_STALLED)
        self.assertEqual(written.loc["20260706", "ret_5d_status"], "ok")
        self.assertEqual(written.loc["20260706", "ret_10d_status"], "ok")
        self.assertEqual(written.loc["20260706", "ret_20d_status"], "pending_immature_asof")
        self.assertEqual(written.loc["20260713", "ret_5d_status"], "ok")
        self.assertEqual(written.loc["20260713", "ret_10d_status"], "ok")
        self.assertEqual(written.loc["20260713", "ret_20d_status"], "pending_immature_asof")
        self.assertEqual(written.loc["20260720", "ret_5d_status"], "ok")
        self.assertEqual(written.loc["20260720", "ret_10d_status"], "pending_immature_asof")
        self.assertEqual(written.loc["20260727", "ret_5d_status"], "pending_immature_asof")

    def test_in_cache_immature_window_does_not_emit_stale_after_attach(self) -> None:
        # The cohort is present in cache and attach_forward_returns is reached;
        # only its +20d window is still younger than the calendar approximation.
        # This is the O10 guard against over-reporting after the post-attach
        # stale classification.
        import io
        from contextlib import redirect_stdout

        as_of = "20260713"
        stock_dates = pd.bdate_range(as_of, "20260731").strftime("%Y%m%d").tolist()

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            tracker_path = Path(tmp) / "forward_tracker.csv"
            with cache_path.open("wb") as handle:
                pickle.dump(
                    _settlement_cache_payload(stock_dates, meta_end_date="20260803"),
                    handle,
                )
            with patch.object(forward_tracker, "TRACKER_CSV", tracker_path):
                forward_tracker._write_tracker(pd.DataFrame([_tracker_row(as_of, "000001.SZ")]))
            buf = io.StringIO()
            with (
                patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path),
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(forward_tracker, "_today_yyyymmdd", return_value="20260809"),
                redirect_stdout(buf),
            ):
                rc = forward_tracker.backfill([5, 10, 20])
            written = pd.read_csv(tracker_path, dtype={"as_of": str}).set_index("as_of")

        self.assertEqual(rc, 0)
        self.assertEqual(written.loc[as_of, "ret_5d_status"], "ok")
        self.assertEqual(written.loc[as_of, "ret_10d_status"], "ok")
        self.assertEqual(written.loc[as_of, "ret_20d_status"], "pending_immature_asof")
        self.assertNotIn("FORWARD-TRACKER CACHE STALE", buf.getvalue())

    def test_current_cache_does_not_call_holiday_stretch_stale(self) -> None:
        # Twenty available exchange sessions can span more than the calendar
        # approximation when a long holiday sits inside the interval.  Both a
        # Friday run and the following Sunday run must compare against the
        # same latest settled session, not the Sunday wall date (P2).
        import io
        from contextlib import redirect_stdout

        as_of = "20260102"
        holiday_dates = {"20260112", "20260113", "20260114", "20260115", "20260116", "20260119"}
        stock_dates = [
            date
            for date in pd.bdate_range(as_of, "20260206").strftime("%Y%m%d").tolist()
            if date not in holiday_dates
        ]
        self.assertEqual(len(stock_dates), 20)
        self.assertEqual(stock_dates[-1], "20260206")

        for today in ("20260206", "20260208"):
            with self.subTest(today=today), tempfile.TemporaryDirectory() as tmp:
                cache_path = Path(tmp) / "forward_daily.pkl"
                tracker_path = Path(tmp) / "forward_tracker.csv"
                with cache_path.open("wb") as handle:
                    pickle.dump(
                        _settlement_cache_payload(stock_dates, meta_end_date="20260206"),
                        handle,
                    )
                with patch.object(forward_tracker, "TRACKER_CSV", tracker_path):
                    forward_tracker._write_tracker(pd.DataFrame([_tracker_row(as_of, "000001.SZ")]))
                buf = io.StringIO()
                with (
                    patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path),
                    patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                    patch.object(forward_tracker, "_today_yyyymmdd", return_value=today),
                    redirect_stdout(buf),
                ):
                    rc = forward_tracker.backfill([20])
                written = pd.read_csv(tracker_path, dtype={"as_of": str}).set_index("as_of")

                self.assertEqual(rc, 0)
                self.assertEqual(written.loc[as_of, "ret_20d_status"], "pending_immature_asof")
                self.assertNotIn("FORWARD-TRACKER CACHE STALE", buf.getvalue())

    def test_current_capture_uses_prior_settled_clock_before_next_session(self) -> None:
        # A current weekly capture can run on a Monday/holiday wall date while
        # its accepted price clock is Friday.  That source-bound hint must win
        # over the weekday fallback or a current cache is falsely stale.
        import io
        from contextlib import redirect_stdout

        as_of = "20260102"
        today = "20260209"
        settled = "20260206"
        holiday_dates = {"20260112", "20260113", "20260114", "20260115", "20260116", "20260119"}
        stock_dates = [
            date
            for date in pd.bdate_range(as_of, settled).strftime("%Y%m%d").tolist()
            if date not in holiday_dates
        ]

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            tracker_path = Path(tmp) / "forward_tracker.csv"
            with cache_path.open("wb") as handle:
                pickle.dump(_settlement_cache_payload(stock_dates, meta_end_date=settled), handle)
            with patch.object(forward_tracker, "TRACKER_CSV", tracker_path):
                forward_tracker._write_tracker(pd.DataFrame([_tracker_row(
                    as_of,
                    "000001.SZ",
                    run_date=today,
                    price_data_through=settled,
                )]))
            buf = io.StringIO()
            with (
                patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path),
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(forward_tracker, "_today_yyyymmdd", return_value=today),
                redirect_stdout(buf),
            ):
                rc = forward_tracker.backfill([20])

        self.assertEqual(rc, 0)
        self.assertNotIn("FORWARD-TRACKER CACHE STALE", buf.getvalue())

    def test_prior_capture_clock_covers_holiday_weekday_without_same_day_capture(self) -> None:
        # A backfill can run on a holiday weekday before that week's capture row
        # lands.  Reuse the latest source-bound prior capture rather than treating
        # the weekday wall date as an unsettled session (O12).
        import io
        from contextlib import redirect_stdout

        as_of = "20260102"
        today = "20260209"
        prior_run = "20260206"
        settled = "20260206"
        holiday_dates = {"20260112", "20260113", "20260114", "20260115", "20260116", "20260119"}
        stock_dates = [
            date
            for date in pd.bdate_range(as_of, settled).strftime("%Y%m%d").tolist()
            if date not in holiday_dates
        ]

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            tracker_path = Path(tmp) / "forward_tracker.csv"
            with cache_path.open("wb") as handle:
                pickle.dump(_settlement_cache_payload(stock_dates, meta_end_date=settled), handle)
            with patch.object(forward_tracker, "TRACKER_CSV", tracker_path):
                forward_tracker._write_tracker(pd.DataFrame([_tracker_row(
                    as_of,
                    "000001.SZ",
                    run_date=prior_run,
                    price_data_through=settled,
                )]))
            buf = io.StringIO()
            with (
                patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path),
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(forward_tracker, "_today_yyyymmdd", return_value=today),
                redirect_stdout(buf),
            ):
                rc = forward_tracker.backfill([20])

        self.assertEqual(rc, 0)
        self.assertNotIn("FORWARD-TRACKER CACHE STALE", buf.getvalue())

    def test_fully_covered_fresh_cache_settles_without_stale_exit(self) -> None:
        stock_dates = pd.bdate_range("20260706", periods=25).strftime("%Y%m%d").tolist()
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            tracker_path = Path(tmp) / "forward_tracker.csv"
            with cache_path.open("wb") as handle:
                pickle.dump(
                    _settlement_cache_payload(stock_dates, meta_end_date=stock_dates[-1]),
                    handle,
                )
            with patch.object(forward_tracker, "TRACKER_CSV", tracker_path):
                forward_tracker._write_tracker(pd.DataFrame([_tracker_row(stock_dates[0], "000001.SZ")]))
            with (
                patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path),
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(forward_tracker, "_today_yyyymmdd", return_value="20260809"),
            ):
                rc = forward_tracker.backfill([5, 10, 20])
            written = pd.read_csv(tracker_path, dtype={"as_of": str})

        self.assertEqual(rc, 0)
        self.assertTrue((written[["ret_5d_status", "ret_10d_status", "ret_20d_status"]] == "ok").all().all())

    def test_backfill_emits_stale_banner_when_cohort_missing_from_cache(self) -> None:
        import io
        from contextlib import redirect_stdout

        same_anchor = pd.DataFrame([
            {"trade_date": "20260201", "open": 3000.0, "close": 3010.0},
            {"trade_date": "20260220", "open": 3050.0, "close": 3100.0},
        ])
        benchmarks = {name: same_anchor.copy() for name in forward_tracker.BENCHMARKS}
        stale_dates = pd.bdate_range("20260201", periods=15).strftime("%Y%m%d").tolist()

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            tracker_path = Path(tmp) / "forward_tracker.csv"
            self._write_cache(cache_path, benchmarks, stock_trade_dates=stale_dates)
            df = pd.DataFrame([_tracker_row("20260515", "000001.SZ")])  # after the stale cache end
            with patch.object(forward_tracker, "TRACKER_CSV", tracker_path):
                forward_tracker._write_tracker(df)
            buf = io.StringIO()
            with (
                patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path),
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(forward_tracker, "_today_yyyymmdd", return_value="20260701"),
                redirect_stdout(buf),
            ):
                rc = forward_tracker.backfill([5, 10, 20])

        out = buf.getvalue()
        # The banner alone dies with the terminal, so a stalled ledger must also leave a
        # distinct exit code for the launcher to record.
        self.assertEqual(rc, forward_tracker.EXIT_LEDGER_STALLED)
        self.assertNotEqual(rc, 0)
        self.assertIn("FORWARD-TRACKER CACHE STALE", out)
        self.assertIn("forward_tracker.py refresh", out)
        self.assertIn("20260515", out)

    def test_globally_blocked_cache_also_reports_stalled_not_success(self) -> None:
        # The other way the ledger freezes: the cache is readable but its benchmark
        # frames are not same-anchor, so every cohort is blocked at once.
        import io
        from contextlib import redirect_stdout

        no_anchor = pd.DataFrame([
            {"trade_date": "20260201", "close": 3010.0},   # no `open` -> not same-anchor
            {"trade_date": "20260220", "close": 3100.0},
        ])
        benchmarks = {name: no_anchor.copy() for name in forward_tracker.BENCHMARKS}
        dates = pd.bdate_range("20260201", periods=40).strftime("%Y%m%d").tolist()

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            tracker_path = Path(tmp) / "forward_tracker.csv"
            self._write_cache(cache_path, benchmarks, stock_trade_dates=dates)
            df = pd.DataFrame([_tracker_row("20260202", "000001.SZ")])
            with patch.object(forward_tracker, "TRACKER_CSV", tracker_path):
                forward_tracker._write_tracker(df)
            buf = io.StringIO()
            with (
                patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path),
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(forward_tracker, "_today_yyyymmdd", return_value="20260701"),
                redirect_stdout(buf),
            ):
                rc = forward_tracker.backfill([5, 10, 20])

        self.assertEqual(rc, forward_tracker.EXIT_LEDGER_STALLED)
        self.assertIn("FORWARD-TRACKER CACHE STALE", buf.getvalue())

    def test_nothing_to_settle_is_not_reported_as_stalled(self) -> None:
        # An empty tracker and a tracker with no matured cohort are both honest zeros:
        # the ledger is not stuck, there is simply nothing owed.
        import io
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as tmp:
            tracker_path = Path(tmp) / "forward_tracker.csv"
            buf = io.StringIO()
            with (
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(forward_tracker, "_today_yyyymmdd", return_value="20260701"),
                redirect_stdout(buf),
            ):
                self.assertEqual(forward_tracker.backfill([5, 10, 20]), 0)
            df = pd.DataFrame([_tracker_row("20260630", "000001.SZ")])   # captured yesterday
            with patch.object(forward_tracker, "TRACKER_CSV", tracker_path):
                forward_tracker._write_tracker(df)
            with (
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(forward_tracker, "_today_yyyymmdd", return_value="20260701"),
                redirect_stdout(buf),
            ):
                self.assertEqual(forward_tracker.backfill([5, 10, 20]), 0)

    def test_truly_young_cohort_does_not_emit_stale_banner(self) -> None:
        import io
        from contextlib import redirect_stdout

        as_of = "20260801"
        stock_dates = pd.bdate_range(as_of, periods=3).strftime("%Y%m%d").tolist()
        same_anchor = pd.DataFrame([
            {"trade_date": as_of, "open": 3000.0, "close": 3010.0},
            {"trade_date": stock_dates[-1], "open": 3050.0, "close": 3100.0},
        ])
        benchmarks = {name: same_anchor.copy() for name in forward_tracker.BENCHMARKS}

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "forward_daily.pkl"
            tracker_path = Path(tmp) / "forward_tracker.csv"
            self._write_cache(cache_path, benchmarks, stock_trade_dates=stock_dates)
            with patch.object(forward_tracker, "TRACKER_CSV", tracker_path):
                forward_tracker._write_tracker(pd.DataFrame([_tracker_row(as_of, "000001.SZ")]))
            buf = io.StringIO()
            with (
                patch.object(forward_tracker, "FORWARD_DAILY_CACHE", cache_path),
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(forward_tracker, "_today_yyyymmdd", return_value="20260803"),
                redirect_stdout(buf),
            ):
                rc = forward_tracker.backfill([5, 10, 20])

        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("no calendar-age eligible as_of with pending rows", out)
        self.assertNotIn("FORWARD-TRACKER CACHE STALE", out)

    def test_refresh_fetches_with_refresh_true_for_matured_cohorts(self) -> None:
        df = pd.DataFrame([_tracker_row("20260515", "000001.SZ")])
        fake_payload = {
            "meta": {"start_date": "20260515", "end_date": "20260701", "stock_rows": 100, "stock_codes": 10},
            "stocks": pd.DataFrame(), "limits": pd.DataFrame(), "benchmarks": {},
        }

        with tempfile.TemporaryDirectory() as tmp:
            tracker_path = Path(tmp) / "forward_tracker.csv"
            with patch.object(forward_tracker, "TRACKER_CSV", tracker_path):
                forward_tracker._write_tracker(df)
            with (
                patch.object(forward_tracker, "TRACKER_CSV", tracker_path),
                patch.object(forward_tracker, "_today_yyyymmdd", return_value="20260701"),
                patch.object(forward_tracker, "fetch_forward_daily", return_value=fake_payload) as fetch_mock,
                patch.object(
                    forward_tracker, "_partition_asof_coverage",
                    return_value=(["20260515"], [], [], fake_payload, None),
                ),
            ):
                rc = forward_tracker.refresh([5, 10, 20])

        self.assertEqual(rc, 0)
        fetch_mock.assert_called_once()
        args, kwargs = fetch_mock.call_args
        self.assertEqual(args[0], ["20260515"])   # only the tracker's matured pending cohort
        self.assertEqual(kwargs.get("refresh"), True)


if __name__ == "__main__":
    unittest.main()
