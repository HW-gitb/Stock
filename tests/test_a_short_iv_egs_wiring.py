"""Sequence 15: one IV producer, EGS projection, and fail-closed source binding."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"
PS1_SCRIPT = ROOT / "runners" / "weekly_screening.ps1"
ANALYSIS_SCHEMA = ROOT / "schemas" / "analysis_input.schema.json"

from runners.a_short_iv_feed_build import (  # noqa: E402
    build_feed_summary,
    build_m05_state,
    validate_feed_artifact,
    validate_feed_summary_consistency,
)
from runners.a_short_weekly_pipeline import (  # noqa: E402
    _validate_analysis_input_m05_binding,
    _validate_nonready_analysis_input_iv_binding,
    latest_m05_state,
)


def _load_egs_module():
    old_argv = sys.argv[:]
    sys.argv = [str(EGS_SCRIPT), "--help"]
    try:
        spec = importlib.util.spec_from_file_location("egs_main_iv_wiring_under_test", EGS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = old_argv


def _valid_feed() -> dict:
    dates = [
        (pd.Timestamp("2026-01-02") + pd.tseries.offsets.BDay(i)).strftime("%Y%m%d")
        for i in range(70)
    ]
    frame = pd.DataFrame({
        "trade_date": dates,
        "iv_value": [0.15 + 0.001 * i for i in range(len(dates))],
        "hv_value": [0.14 + 0.001 * i for i in range(len(dates))],
    })
    feed = build_feed_summary(
        frame,
        dates[-1],
        "2026-08-08T00:00:00+08:00",
        trade_calendar=dates,
        calendar_source="tushare.trade_cal",
        trade_dates_probed=dates,
    )
    validate_feed_artifact(feed)
    return feed


class EgsIvProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.egs_main = _load_egs_module()

    def test_no_feed_is_explicit_unknown_and_not_a_hidden_default(self) -> None:
        projection = self.egs_main._load_iv_feed_projection(None, "20260808", "20260807")
        self.assertEqual(projection["source_status"], "unavailable")
        self.assertEqual(projection["iv_feed_status"], "not_requested")
        self.assertEqual(projection["freshness_status"], "not_requested")
        self.assertEqual(projection["freshness_reason"], "iv_feed_not_requested")
        self.assertIsNone(projection["iv_percentile_252d"])
        self.assertIsNone(projection["hv_value"])
        self.assertEqual(projection["rule3_status"], "unknown")

    def test_each_nonready_status_is_rendered_without_inference_or_abort(self) -> None:
        for status in ("not_requested", "build_failed", "digest_failed", "clock_mismatch"):
            projection = self.egs_main._load_iv_feed_projection(
                None, "20260808", "20260807", iv_feed_status=status
            )
            self.assertEqual(projection["iv_feed_status"], status)
            self.assertEqual(
                projection["freshness_status"],
                "not_requested" if status == "not_requested" else "unavailable",
            )
            self.assertEqual(projection["freshness_reason"], f"iv_feed_{status}")
            self.assertIsNone(projection["iv_percentile_252d"])
            self.assertIsNone(projection["iv_value"])
            self.assertIsNone(projection["hv_value"])
            self.assertEqual(projection["rule3_status"], "unknown")

    def test_nonready_status_cannot_smuggle_a_feed_path(self) -> None:
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            path = Path(tmp) / "iv_feed.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                self.egs_main._load_iv_feed_projection(
                    str(path), "20260808", "20260807", iv_feed_status="build_failed"
                )

    def test_valid_feed_projection_carries_exact_latest_values_and_digest(self) -> None:
        feed = _valid_feed()
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            path = Path(tmp) / "iv_feed.json"
            path.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            projection = self.egs_main._load_iv_feed_projection(
                str(path), feed["as_of"], feed["as_of"], iv_feed_status="ready"
            )
            latest = feed["series"][-1]
            self.assertEqual(projection["source_status"], "complete")
            self.assertEqual(projection["iv_feed_status"], "ready")
            self.assertEqual(projection["freshness_status"], "aligned")
            self.assertEqual(projection["source_as_of"], feed["as_of"])
            self.assertEqual(projection["source_latest_trade_date"], latest["trade_date"])
            for field in (
                "iv_value", "hv_value", "iv_percentile_252d", "iv_change_abs_1d_pctpt",
                "rule3_status", "awakening_status", "cash_reclaim_pct",
            ):
                self.assertEqual(projection[field], latest[field])
            self.assertEqual(
                projection["source_ref"],
                os.path.relpath(path.resolve(), ROOT).replace("\\", "/"),
            )
            self.assertEqual(len(projection["feed_sha256"]), 64)

    def test_stale_future_asof_and_tampered_state_reject_before_projection(self) -> None:
        feed = _valid_feed()
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            path = Path(tmp) / "iv_feed.json"

            path.write_text(json.dumps(feed), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.egs_main._load_iv_feed_projection(
                    str(path), "20991231", feed["as_of"], iv_feed_status="ready"
                )
            with self.assertRaises(ValueError):
                self.egs_main._load_iv_feed_projection(
                    str(path), feed["as_of"], "20991231", iv_feed_status="ready"
                )

            tampered = copy.deepcopy(feed)
            tampered["series"][-1]["rule3_status"] = "normal"
            path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.egs_main._load_iv_feed_projection(
                    str(path), feed["as_of"], feed["as_of"], iv_feed_status="ready"
                )

    def test_tampered_percentile_is_recomputed_and_rejected(self) -> None:
        feed = _valid_feed()
        tampered = copy.deepcopy(feed)
        tampered["series"][-1]["iv_percentile_252d"] = 3.0
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            path = Path(tmp) / "iv_feed.json"
            path.write_text(json.dumps(tampered), encoding="utf-8")
            # Name the door: a bare ValueError here would also be raised by the
            # older per-row state comparison, so the assertion has to say which
            # gate answered or it keeps passing after the recomputation is gone.
            with self.assertRaisesRegex(ValueError, "rolling_percentile_252"):
                self.egs_main._load_iv_feed_projection(
                    str(path), feed["as_of"], feed["as_of"], iv_feed_status="ready"
                )

    def test_ready_status_without_a_feed_path_is_rejected(self) -> None:
        # Without naming the door this passes on the FileNotFoundError that
        # `os.path.abspath(str(None))` produces one line later.
        with self.assertRaisesRegex(ValueError, "ready IV feed status requires"):
            self.egs_main._load_iv_feed_projection(
                None, "20260808", "20260807", iv_feed_status="ready"
            )

    def test_missing_or_nonfinite_numeric_content_is_rejected(self) -> None:
        feed = _valid_feed()
        for mutation in ("missing_percentile", "nonfinite_iv"):
            tampered = copy.deepcopy(feed)
            if mutation == "missing_percentile":
                tampered["series"][-1].pop("iv_percentile_252d")
            else:
                tampered["series"][-1]["iv_value"] = float("nan")
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
                path = Path(tmp) / "iv_feed.json"
                path.write_text(json.dumps(tampered), encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.egs_main._load_iv_feed_projection(
                        str(path), feed["as_of"], feed["as_of"], iv_feed_status="ready"
                    )

    def test_analysis_schema_locks_complete_and_unknown_shapes(self) -> None:
        schema = json.loads(ANALYSIS_SCHEMA.read_text(encoding="utf-8"))
        fixture = json.loads(
            (ROOT / "schemas" / "examples" / "analysis_input.example.json").read_text(encoding="utf-8")
        )
        unknown = copy.deepcopy(fixture)
        unknown["market_context"]["volatility"] = self.egs_main._unknown_iv_projection()
        jsonschema.validate(unknown, schema)
        unknown["market_context"]["volatility"]["iv_percentile_252d"] = 50.0
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(unknown, schema)

        complete = copy.deepcopy(fixture)
        complete["market_context"]["volatility"].update({
            "source_status": "complete",
            "freshness_status": "aligned",
            "freshness_reason": "validated_feed",
        })
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(complete, schema)
        complete["market_context"]["volatility"].update({
            "iv_feed_status": "ready",
            "source_as_of": "20260808",
            "source_latest_trade_date": "20260807",
            "source_ref": "research/results/a_short/iv_feed.json",
            "feed_sha256": "a" * 64,
        })
        jsonschema.validate(complete, schema)


class WeeklyIvSourceBindingTests(unittest.TestCase):
    def test_complete_projection_requires_exact_ai_values_and_feed_bytes(self) -> None:
        import importlib

        egs_main = importlib.import_module("egs_main_iv_wiring_under_test") \
            if "egs_main_iv_wiring_under_test" in sys.modules else _load_egs_module()
        feed = _valid_feed()
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as tmp:
            path = Path(tmp) / "iv_feed.json"
            path.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            projection = egs_main._load_iv_feed_projection(
                str(path), feed["as_of"], feed["as_of"], iv_feed_status="ready"
            )
            ai = {
                "decision_as_of": feed["as_of"],
                "price_data_through": feed["as_of"],
                "market_context": {"volatility": projection},
            }
            _validate_analysis_input_m05_binding(
                ai, feed, latest_m05_state(feed), iv_feed_path=str(path)
            )

            forged = copy.deepcopy(ai)
            forged["market_context"]["volatility"]["iv_value"] += 0.01
            with self.assertRaises(ValueError):
                _validate_analysis_input_m05_binding(
                    forged, feed, latest_m05_state(feed), iv_feed_path=str(path)
                )

            forged = copy.deepcopy(ai)
            forged["market_context"]["volatility"]["feed_sha256"] = "b" * 64
            with self.assertRaises(ValueError):
                _validate_analysis_input_m05_binding(
                    forged, feed, latest_m05_state(feed), iv_feed_path=str(path)
                )

    def test_nonready_projection_requires_exact_cli_status_and_unknown_values(self) -> None:
        egs_main = importlib.import_module("egs_main_iv_wiring_under_test") \
            if "egs_main_iv_wiring_under_test" in sys.modules else _load_egs_module()
        for status in ("not_requested", "build_failed", "digest_failed", "clock_mismatch"):
            with self.subTest(status=status):
                projection = egs_main._unknown_iv_projection(status)
                ai = {"market_context": {"volatility": projection}}
                _validate_nonready_analysis_input_iv_binding(ai, status)

                forged = copy.deepcopy(ai)
                forged["market_context"]["volatility"]["hv_value"] = 0.20
                with self.assertRaisesRegex(ValueError, "hv_value"):
                    _validate_nonready_analysis_input_iv_binding(forged, status)

                forged = copy.deepcopy(ai)
                forged["market_context"]["volatility"]["iv_feed_status"] = "digest_failed"
                if status != "digest_failed":
                    with self.assertRaisesRegex(ValueError, "iv_feed_status"):
                        _validate_nonready_analysis_input_iv_binding(forged, status)


class IvFeedTrustRootTests(unittest.TestCase):
    """The read door certifies these numbers, so each check must be killable."""

    _STATE_FIELDS = (
        "iv_change_abs_1d_pctpt", "rule3_status", "awakening_status", "cash_reclaim_pct",
        "awakening_baseline_iv", "awakening_trigger_date", "awakening_release_date",
    )

    def _edit_percentile_self_consistently(self, feed: dict, percentile: float) -> dict:
        """Edit the stored percentile the way a wrong upstream value would.

        The producer's own state machine is re-run over the edited series, so
        every derived M0.5 field and the awakening block stay internally
        consistent.  Only re-deriving the percentile itself can catch this.
        """
        out = copy.deepcopy(feed)
        out["series"][-1]["iv_percentile_252d"] = percentile
        state = build_m05_state(pd.DataFrame([
            {"trade_date": row["trade_date"], "iv_value": row["iv_value"],
             "iv_percentile_252d": row["iv_percentile_252d"]}
            for row in out["series"]
        ]), trade_calendar=[row["trade_date"] for row in out["series"]])
        for index, recomputed_row in state.iterrows():
            for field in self._STATE_FIELDS:
                value = recomputed_row[field]
                out["series"][index][field] = None if pd.isna(value) else value
        latest = out["series"][-1]
        out["awakening"].update({
            "iv_change_abs_1d_pctpt": latest["iv_change_abs_1d_pctpt"],
            "rule3_status": latest["rule3_status"],
            "status": latest["awakening_status"],
            "cash_reclaim_pct": latest["cash_reclaim_pct"],
            "baseline_iv": latest["awakening_baseline_iv"],
            "trigger_date": latest["awakening_trigger_date"],
            "release_date": latest["awakening_release_date"],
        })
        return out

    def test_self_consistent_percentile_edit_still_fails_the_read_door(self) -> None:
        feed = _valid_feed()
        self.assertEqual(feed["series"][-1]["rule3_status"], "no_trade")
        forged = self._edit_percentile_self_consistently(feed, 3.0)
        # The state machine followed the edit, so every row-consistency check
        # agrees with it; the market state has flipped all the same.
        self.assertEqual(forged["series"][-1]["rule3_status"], "normal")
        with self.assertRaisesRegex(ValueError, "rolling_percentile_252"):
            validate_feed_artifact(forged)

    def test_honest_feed_is_not_caught_by_the_recomputation(self) -> None:
        validate_feed_artifact(_valid_feed())

    def test_non_finite_series_value_is_named_and_rejected(self) -> None:
        for field in ("iv_value", "iv_percentile_252d", "hv_value",
                      "iv_change_abs_1d_pctpt", "cash_reclaim_pct",
                      "awakening_baseline_iv"):
            with self.subTest(field=field):
                feed = _valid_feed()
                feed["series"][-1][field] = float("inf")
                with self.assertRaisesRegex(
                    ValueError, rf"series\.{field} must be finite"
                ):
                    validate_feed_summary_consistency(feed)

    def test_non_finite_awakening_value_is_named_and_rejected(self) -> None:
        for field in ("iv_change_abs_1d_pctpt", "cash_reclaim_pct", "baseline_iv"):
            with self.subTest(field=field):
                feed = _valid_feed()
                feed["awakening"][field] = float("inf")
                # The mirror check further down reports the same field name for
                # a plain mismatch, so the assertion has to pin this door.
                with self.assertRaisesRegex(
                    ValueError, rf"awakening\.{field} must be finite"
                ):
                    validate_feed_summary_consistency(feed)


class WeeklyIvOrderingTests(unittest.TestCase):
    def test_builder_is_before_egs_and_is_not_rebuilt_in_stage_four(self) -> None:
        text = PS1_SCRIPT.read_text(encoding="utf-8")
        builder_call = "& $PythonExe runners\\a_short_iv_feed_build.py"
        self.assertEqual(text.count(builder_call), 1)
        self.assertLess(text.index(builder_call), text.index("& $PythonExe @EgsArgs"))
        self.assertIn("if ($script:IvFeedReady) {", text)
        self.assertIn("$EgsArgs += @('--iv-feed', $IvFeed)", text)
        self.assertIn("--iv-feed-status", text)
        self.assertIn("--price-data-through $PriceAsOf", text)
        self.assertIn("$script:IvFeedStatus", text)
        self.assertIn("$KnownIvFeedStatus = [string]$script:IvFeedStatus", text)
        self.assertIn("$KnownIvFeedStatus = 'not_requested'", text)
        self.assertIn("-IvFeedStatus $KnownIvFeedStatus", text)
        self.assertIn("attempted_before_egs", text)
        self.assertIn("feed_sha256", text)
        self.assertNotIn("Set-M67Failure -Reason 'iv_feed_failed'", text)
        self.assertIn("'--iv-feed-status', $script:IvFeedStatus", text)
        self.assertIn("if ($script:IvFeedReady) { $M67Args += @('--iv-feed', $IvFeed) }", text)
        egs = text.index("& $PythonExe @EgsArgs")
        self.assertGreater(text.index("runners\\data_canary.py --as-of"), egs)
        self.assertGreater(text.index("runners\\forward_tracker.py capture"), egs)


if __name__ == "__main__":
    unittest.main()
