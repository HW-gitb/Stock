"""Offline tests for the bounded margin-overheat evidence runner (queue row 19)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.a_short_margin_overheat as margin_overheat  # noqa: E402
import runners.a_short_margin_overheat_percentile as runner  # noqa: E402
from tests.test_a_short_margin_overheat_wiring import (  # noqa: E402
    BSE_BALANCE,
    DENOMINATOR_FLOAT_MV,
    EVIDENCE_SESSIONS,
    SSE_BALANCE,
    SZSE_BALANCE,
    WINDOW_SESSIONS,
    _denominator_rows,
    _margin_rows,
    _sessions,
)


SCHEMA = json.loads(
    (ROOT / "schemas" / "a_short_margin_overheat_percentile_evidence.schema.json")
    .read_text(encoding="utf-8")
)


class _Client:
    """Injected provider stand-in; records every call it is asked to make."""

    def __init__(self, sessions, rows, *, calendar_rows=None, denominator_rows=None):
        self.sessions = sessions
        self.rows = rows
        self.calendar_rows = calendar_rows
        self.denominator_rows = (
            _denominator_rows(sessions) if denominator_rows is None else denominator_rows
        )
        self.calls = []

    def trade_cal(self, **kwargs):
        self.calls.append(("trade_cal", kwargs))
        rows = self.calendar_rows
        if rows is None:
            rows = [{"cal_date": date} for date in sorted(self.sessions)]
        return pd.DataFrame(rows)

    def _windowed(self, rows, kwargs):
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        window = frame[(frame["trade_date"] >= kwargs["start_date"])
                       & (frame["trade_date"] <= kwargs["end_date"])]
        return window.reset_index(drop=True)

    def margin(self, **kwargs):
        self.calls.append(("margin", kwargs))
        return self._windowed(self.rows, kwargs)

    def index_dailybasic(self, **kwargs):
        self.calls.append(("index_dailybasic", kwargs))
        return self._windowed(self.denominator_rows, kwargs)


class MarginOverheatEvidenceRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raw_root = ROOT / "provider_samples" / f"_test_margin_overheat_{id(self)}"
        self.addCleanup(self._cleanup_raw)

    def _cleanup_raw(self):
        for path in sorted(self.raw_root.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        if self.raw_root.is_dir():
            self.raw_root.rmdir()

    def _run(self, sessions, rows, **kwargs):
        client = _Client(sessions, rows, **kwargs)
        as_of = sessions[0] if sessions else runner.PROBE_DATE
        summary = runner.run_probe(client, as_of=as_of, raw_root=self.raw_root)
        return client, summary

    def test_a_complete_window_produces_schema_valid_threshold_evidence(self):
        sessions = _sessions(WINDOW_SESSIONS)
        client, summary = self._run(sessions, _margin_rows(sessions))
        jsonschema.validate(summary, SCHEMA)
        self.assertTrue(summary["coverage_complete"])
        self.assertEqual(summary["current_percentile"], 1.0)
        self.assertAlmostEqual(
            summary["current_balance_yuan"],
            (SSE_BALANCE + SZSE_BALANCE + BSE_BALANCE) * 2.0,
            delta=1e4,
        )
        self.assertEqual(summary["status"], "PARTIAL")   # warm-up weeks are disclosed
        self.assertEqual(
            [row["percentile_threshold"] for row in summary["threshold_evidence"]["by_threshold"]],
            [0.80, 0.85, 0.90, 0.95],
        )
        self.assertEqual(summary["execution"]["calls_made"], len(client.calls))
        self.assertLessEqual(summary["execution"]["calls_made"], runner.CALL_BUDGET)
        self.assertTrue(summary["execution"]["within_budget"])
        self.assertEqual(summary["source_binding"]["margin_unit"], "CNY")
        self.assertEqual(summary["exchange_observed_session_count"],
                         {"SSE": len(sessions), "SZSE": len(sessions), "BSE": len(sessions)})

    def test_the_fetch_never_exceeds_the_reviewed_call_budget(self):
        sessions = _sessions(WINDOW_SESSIONS)
        client, summary = self._run(sessions, _margin_rows(sessions))
        endpoints = [name for name, _ in client.calls]
        self.assertEqual(endpoints.count("trade_cal"), 1)
        self.assertLessEqual(len(endpoints), runner.CALL_BUDGET)
        for _, kwargs in client.calls:
            self.assertNotIn("token", kwargs)

    def test_a_window_needing_more_segments_than_the_budget_aborts_instead_of_partially_fetching(self):
        sessions = _sessions(WINDOW_SESSIONS)
        with patch.object(margin_overheat, "MARGIN_FETCH_SEGMENT_MAX_SESSIONS", 50):
            client, summary = self._run(sessions, _margin_rows(sessions))
        self.assertEqual([name for name, _ in client.calls], ["trade_cal"])
        self.assertFalse(summary["coverage_complete"])
        self.assertIsNone(summary["current_percentile"])
        self.assertEqual(summary["status"], "NOT_VERIFIED")
        self.assertEqual(summary["margin_fetch"]["status"], "not_attempted")
        jsonschema.validate(summary, SCHEMA)

    def test_the_live_and_evidence_windows_are_reported_separately(self):
        # A six-year history with a three-year live window: the top-level
        # counts must describe the LIVE window only, so a reader can never
        # compute a bogus coverage ratio out of two different windows, nor
        # read current_percentile as spanning the evidence history.
        sessions = _sessions(EVIDENCE_SESSIONS)
        _client, summary = self._run(sessions, _margin_rows(sessions))
        jsonschema.validate(summary, SCHEMA)
        self.assertTrue(summary["coverage_complete"])
        self.assertEqual(
            summary["requested_session_count"], summary["observed_session_count"],
            msg="a complete live window must not look half-covered",
        )
        self.assertLess(summary["requested_session_count"], len(sessions))
        live_start = margin_overheat.window_start(summary["window_end"])
        self.assertGreaterEqual(summary["window_start"], live_start)
        self.assertEqual(summary["evidence_window"]["session_count"], len(sessions))
        self.assertEqual(summary["evidence_window"]["start"], sessions[-1])
        self.assertEqual(summary["evidence_window"]["end"], sessions[0])
        self.assertLess(summary["evidence_window"]["start"], summary["window_start"])

    def test_the_publication_lag_at_the_front_edge_still_yields_a_full_window(self):
        # Reproduces the real 2026-08-05 run: the calendar has today, the vendor
        # does not publish today's balance until tomorrow.
        calendar = _sessions(WINDOW_SESSIONS + 1)
        rows = _margin_rows(calendar[1:])
        client = _Client(calendar, rows)
        summary = runner.run_probe(client, as_of=calendar[0], raw_root=self.raw_root)
        jsonschema.validate(summary, SCHEMA)
        self.assertTrue(summary["coverage_complete"])
        self.assertEqual(summary["window_end"], calendar[1])
        self.assertEqual(summary["requested_session_count"], len(calendar) - 1)
        self.assertIsNotNone(summary["current_percentile"])

    def test_a_stale_market_beyond_the_lag_produces_no_percentile(self):
        calendar = _sessions(WINDOW_SESSIONS + 4)
        rows = _margin_rows(calendar[4:])
        client = _Client(calendar, rows)
        summary = runner.run_probe(client, as_of=calendar[0], raw_root=self.raw_root)
        jsonschema.validate(summary, SCHEMA)
        self.assertFalse(summary["coverage_complete"])
        self.assertIsNone(summary["current_percentile"])
        self.assertIn("normal publication lag", " ".join(summary["not_verified"]))

    def test_a_capped_calendar_response_is_treated_as_truncated(self):
        sessions = _sessions(WINDOW_SESSIONS)
        capped = [{"cal_date": f"2026{index:04d}"}
                  for index in range(margin_overheat.MARGIN_PROVIDER_ROW_CAP)]
        client, summary = self._run(sessions, _margin_rows(sessions), calendar_rows=capped)
        self.assertEqual([name for name, _ in client.calls], ["trade_cal"])
        self.assertEqual(summary["requested_session_count"], 0)
        self.assertFalse(summary["coverage_complete"])
        self.assertIn("no trading calendar was observed for the requested window",
                      " ".join(summary["not_verified"]))

    def test_a_gap_in_the_margin_window_yields_no_percentile_and_no_evidence(self):
        sessions = _sessions(WINDOW_SESSIONS)
        dropped = sorted(sessions)[13]
        rows = [row for row in _margin_rows(sessions) if row["trade_date"] != dropped]
        _client, summary = self._run(sessions, rows)
        jsonschema.validate(summary, SCHEMA)
        self.assertFalse(summary["coverage_complete"])
        self.assertIsNone(summary["current_percentile"])
        self.assertEqual(summary["threshold_evidence"]["by_threshold"], [])
        self.assertEqual(summary["status"], "NOT_VERIFIED")

    def test_replay_rebuilds_the_same_evidence_without_a_new_call(self):
        sessions = _sessions(WINDOW_SESSIONS)
        _client, first = self._run(sessions, _margin_rows(sessions))
        out = Path(self.tmp.name) / "evidence.json"
        out.write_text(json.dumps(first, ensure_ascii=False), encoding="utf-8")
        replayed = runner.replay_raw(
            as_of=sessions[0], raw_root=self.raw_root, existing_summary=out
        )
        for key in ("current_percentile", "current_balance_yuan", "coverage_complete",
                    "observed_session_count", "threshold_evidence"):
            self.assertEqual(replayed[key], first[key], msg=key)
        jsonschema.validate(replayed, SCHEMA)

    def test_raw_must_stay_under_provider_samples_and_out_must_stay_out_of_result(self):
        with self.assertRaisesRegex(ValueError, "provider_samples"):
            runner._assert_raw_root(Path("state/a_short/margin"))
        with self.assertRaisesRegex(ValueError, "result/a_short"):
            runner._assert_not_production_output(Path("result/a_short/20260805/evidence.json"))
        runner._assert_not_production_output(runner.SUMMARY_PATH)

    def test_a_truncated_window_publishes_no_threshold_evidence(self):
        # R-ASHORT-SEQ19-EVIDENCE-LEG-SKIPS-THE-MIN-WINDOW-FLOOR closure ①:
        # a window below the 600-session rolling floor that reconciles cleanly
        # per exchange must not be scored into a four-threshold table.
        for count in (500, WINDOW_SESSIONS - 1):
            sessions = _sessions(count)
            client, summary = self._run(sessions, _margin_rows(sessions))
            jsonschema.validate(summary, SCHEMA)
            self.assertEqual(summary["status"], "NOT_VERIFIED", msg=count)
            self.assertEqual(summary["threshold_evidence"]["by_threshold"], [], msg=count)
            self.assertEqual(summary["threshold_evidence"]["weeks"], [], msg=count)
            self.assertIsNone(summary["current_percentile"], msg=count)
            self.assertTrue(
                any("rolling-window floor" in note and str(count) in note
                    for note in summary["not_verified"]),
                msg=summary["not_verified"],
            )
            self._cleanup_raw()

    def test_the_full_window_still_publishes_the_table_as_partial(self):
        # Closure ②: the honest 725-session run is unchanged by the floor gate.
        sessions = _sessions(WINDOW_SESSIONS)
        _client, summary = self._run(sessions, _margin_rows(sessions))
        self.assertEqual(summary["status"], "PARTIAL")
        self.assertEqual(len(summary["threshold_evidence"]["by_threshold"]), 4)
        self.assertEqual(summary["current_percentile"], 1.0)

    def test_a_budget_abort_names_the_budget_and_keeps_the_calendar(self):
        # Review Optional O-4: an abort is a decision not to call, not a
        # missing calendar and not a failed provider call.
        sessions = _sessions(WINDOW_SESSIONS)
        with patch.object(margin_overheat, "MARGIN_FETCH_SEGMENT_MAX_SESSIONS", 50):
            client, summary = self._run(sessions, _margin_rows(sessions))
        self.assertEqual([name for name, _ in client.calls], ["trade_cal"])
        notes = " | ".join(summary["not_verified"])
        self.assertIn("reviewed budget", notes)
        self.assertIn("no data call was attempted", notes)
        self.assertNotIn("no trading calendar was observed", notes)
        self.assertNotIn("did not return a usable payload", notes)
        self.assertEqual(summary["requested_session_count"], 0)
        self.assertEqual(summary["margin_fetch"]["status"], "not_attempted")

    def test_replay_output_is_marked_and_never_claims_live_provider_calls(self):
        # Review Optional O-1: a rebuilt artifact must be distinguishable from
        # a live fetch even when a prior live summary exists to copy from.
        sessions = _sessions(WINDOW_SESSIONS)
        _client, live = self._run(sessions, _margin_rows(sessions))
        out = Path(self.tmp.name) / "evidence.json"
        out.write_text(json.dumps(live, ensure_ascii=False), encoding="utf-8")
        replayed = runner.replay_raw(
            as_of=sessions[0], raw_root=self.raw_root, existing_summary=out
        )
        jsonschema.validate(replayed, SCHEMA)
        self.assertEqual(replayed["execution"]["calls_made"], 0)
        self.assertEqual(replayed["execution"]["tushare_version"], "replayed_without_new_call")
        self.assertEqual(replayed["status"], "PARTIAL")
        self.assertTrue(any("without any new provider call" in note
                            for note in replayed["not_verified"]))
        self.assertEqual(replayed["current_percentile"], live["current_percentile"])
        self.assertEqual(replayed["margin_fetch"]["segment_count"],
                         live["margin_fetch"]["segment_count"])

    def test_a_non_finite_balance_still_persists_raw_and_fails_closed(self):
        # Review Optional O-3: the budget is already spent when a NaN arrives;
        # the raw capture must land on disk while the evidence fails closed.
        sessions = _sessions(WINDOW_SESSIONS)
        rows = _margin_rows(sessions)
        rows[7] = dict(rows[7], rzye=float("nan"))
        _client, summary = self._run(sessions, rows)
        self.assertFalse(summary["coverage_complete"])
        self.assertIsNone(summary["current_percentile"])
        self.assertEqual(summary["threshold_evidence"]["by_threshold"], [])
        raw = json.loads((self.raw_root / "margin_window.json").read_text(encoding="utf-8"))
        self.assertEqual(len(raw["rows"]), len(rows))
        self.assertEqual(sum(1 for row in raw["rows"] if row["rzye"] == "NaN"), 1)

    def test_the_runner_proposes_no_threshold_and_never_enables_production_effect(self):
        source = (ROOT / "runners" / "a_short_margin_overheat_percentile.py").read_text(
            encoding="utf-8")
        self.assertNotIn("MARGIN_OVERHEAT_PERCENTILE_THRESHOLD =", source)
        self.assertNotIn("MARGIN_OVERHEAT_CASH_FACTOR =", source)
        self.assertNotIn("production_effect_enabled=True", source)
        sessions = _sessions(WINDOW_SESSIONS)
        _client, summary = self._run(sessions, _margin_rows(sessions))
        self.assertFalse(summary["production_effect_enabled"])
        self.assertTrue(summary["comparison_only"])


if __name__ == "__main__":
    unittest.main()
