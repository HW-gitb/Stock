"""Knife-3 tests for the v2 weekly adapter; all data is synthetic and cache-only."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import a_short_factor_comparison as v1  # noqa: E402
from engine.a_short_factor_comparison_v2 import (  # noqa: E402
    ComparisonV2Error,
    _validate_capture_integrity,
    _price_close_matches,
    build_v2_public_progress,
    capture_v2_week,
)
from engine.a_short_factor_comparison_v2_weekly import (  # noqa: E402
    DAILY_CACHE_NAME,
    PUBLIC_STATUS_CURRENT,
    PUBLIC_STATUS_UNAVAILABLE,
    _admission_binding,
    capture_v2_after_published_weekly,
    capture_error_code,
    is_capture_replay_drift,
    load_v2_daily_cache,
    settle_and_summarize_v2_weekly,
    unavailable_public_summary,
    validate_v2_public_summary,
)
from tests._a_short_weekly_publish_test_utils import write_content_bound_bundle  # noqa: E402


def _root(tmp: str) -> Path:
    return Path(tmp) / "state" / "a_short" / "factor_comparison_private" / "v2"


def _trading_dates(start: date, count: int) -> list[str]:
    dates = []
    current = start
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


DECISION_DATE = "20260202"


def _candidate(index: int) -> dict:
    history = _trading_dates(date(2025, 12, 22), 31)
    assert history[-1] == DECISION_DATE
    return {
        "ts_code": f"60000{index}.SH", "name": f"name-{index}", "close": 10.5,
        "price_series": [{"trade_date": day, "high": 10.7, "low": 9.9, "close": 10.5}
                         for day in history],
        "egs_score": 100.0 - index, "derived": {}, "event": {},
        "liquidity": {"avg_amount_5d": 1e9},
        "iv": {"iv_percentile_252d": 50.0, "iv_value": 0.20, "hv_value": 0.18},
        "market_regime": "attack", "regime_fallback": {}, "stateful_risk": {},
    }


def _candidates() -> list[dict]:
    return [_candidate(index) for index in range(5)]


def _identity(candidates: list[dict]) -> dict:
    return {
        "run_id": "knife3-test", "run_date": DECISION_DATE, "source_as_of": DECISION_DATE,
        "price_data_through": DECISION_DATE,
        "candidate_digest": v1._digest([v1._safe_candidate(row) for row in candidates]),
        "official_m67_digest": "b" * 64,
    }


def _daily_cache() -> dict:
    rows = []
    for code_index in range(5):
        for day in _trading_dates(date(2026, 2, 2), 25):
            rows.append({
                "ts_code": f"60000{code_index}.SH", "trade_date": day,
                "open": 10.0, "close": 10.5 if day == DECISION_DATE else 10.0,
                "adj_factor": 1.0, "adj_factor_observed": True,
                "adj_factor_source": "provider_observed", "corporate_action_verified": False,
            })
    return {
        "schema_name": "a_short_factor_comparison_v2_daily_cache", "schema_version": "1.0.0",
        "stocks": rows, "limits": [], "meta": {"cache_kind": "synthetic", "source": "test"},
    }


def _public_progress() -> dict:
    return build_v2_public_progress(root=None, as_of=DECISION_DATE)


class ComparisonV2WeeklyAdapterTests(unittest.TestCase):
    def _capture(self, root: Path) -> list[dict]:
        candidates = _candidates()
        with mock.patch("engine.a_short_factor_comparison_v2._today", return_value=DECISION_DATE):
            capture_v2_week(root=root, decision_date=DECISION_DATE, candidates=candidates,
                            run_identity=_identity(candidates), forward_eligible=True)
        return candidates

    def test_public_unavailable_summary_never_opens_private_root(self):
        summary = unavailable_public_summary(DECISION_DATE)
        self.assertEqual(summary["status"], PUBLIC_STATUS_UNAVAILABLE)
        self.assertEqual(summary["reminder_count"], 0)
        validate_v2_public_summary(summary)

    def test_capture_accepts_same_price_with_binary_float_representation_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            candidates = _candidates()
            candidates[0]["close"] = 11.909999999999998
            candidates[0]["price_series"][-1]["close"] = 11.91
            with mock.patch("engine.a_short_factor_comparison_v2._today", return_value=DECISION_DATE):
                result = capture_v2_week(root=root, decision_date=DECISION_DATE, candidates=candidates,
                                         run_identity=_identity(candidates), forward_eligible=True)
            self.assertEqual(result["status"], "captured")
            _validate_capture_integrity(result["capture"])
        self.assertTrue(_price_close_matches(11.909999999999998, 11.91))

    def test_capture_rejects_material_close_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            candidates = _candidates()
            candidates[0]["close"] = 11.92
            candidates[0]["price_series"][-1]["close"] = 11.91
            with mock.patch("engine.a_short_factor_comparison_v2._today", return_value=DECISION_DATE):
                with self.assertRaisesRegex(ComparisonV2Error, "last_close mismatch"):
                    capture_v2_week(root=root, decision_date=DECISION_DATE, candidates=candidates,
                                    run_identity=_identity(candidates), forward_eligible=True)

    def test_capture_error_code_is_allowlisted_and_does_not_relay_exception_text(self):
        private_value = "candidate 600598.SH at C:\\private\\token.txt"
        self.assertEqual(capture_error_code(ValueError(private_value)), "candidate_shape")
        self.assertNotIn("600598.SH", capture_error_code(ValueError(private_value)))
        self.assertEqual(capture_error_code(RuntimeError(private_value)), "unknown")
        class BadStringError(Exception):
            def __str__(self):
                raise RuntimeError("secret rendering failure")
        self.assertEqual(capture_error_code(BadStringError()), "unknown")
        replay = ValueError("20260202: v2 capture replay input drifted")
        self.assertTrue(is_capture_replay_drift(replay))
        self.assertEqual(capture_error_code(replay), "unknown")

    def test_existing_private_cache_settles_and_uses_the_freshly_written_reminder_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            self._capture(root)
            (root / DAILY_CACHE_NAME).write_text(json.dumps(_daily_cache()), encoding="utf-8")
            first_carrier = {}
            summary = settle_and_summarize_v2_weekly(
                root=root, as_of=DECISION_DATE, sidecar_result=first_carrier,
            )
            self.assertEqual(summary["status"], PUBLIC_STATUS_CURRENT)
            self.assertEqual(summary["reminder_count"], 0)
            self.assertIsInstance(first_carrier.get("outcomes_updated"), int)
            self.assertGreaterEqual(first_carrier["outcomes_updated"], 0)
            second_carrier = {}
            settle_and_summarize_v2_weekly(
                root=root, as_of=DECISION_DATE, sidecar_result=second_carrier,
            )
            self.assertIsInstance(second_carrier.get("outcomes_updated"), int)
            self.assertGreaterEqual(second_carrier["outcomes_updated"], 0)
            self.assertTrue((root / "reminder.json").is_file())
            self.assertIn("current_epoch_id", summary["public_progress"])
            rendered = json.dumps(summary["public_progress"], ensure_ascii=False).lower()
            self.assertFalse(any(f'"{field}"' in rendered for field in ("ts_code", "account", "holding", "price")))
            leaked = copy.deepcopy(summary)
            leaked["public_progress"]["evidence"][0]["ts_code"] = "600000.SH"
            with self.assertRaises(ComparisonV2Error):
                validate_v2_public_summary(leaked)
            leaked = copy.deepcopy(summary)
            leaked["public_progress"]["admissions"][next(iter(leaked["public_progress"]["admissions"]))]["dependency_components"][0]["ts_code"] = "600000.SH"
            with self.assertRaises(ComparisonV2Error):
                validate_v2_public_summary(leaked)

    def test_missing_cache_never_relays_a_stale_reminder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            self._capture(root)
            (root / "reminder.json").write_text(json.dumps({
                "schema_name": "a_short_factor_comparison_v2_reminder", "schema_version": "2.0.0",
                "program_id": "a_short_factor_comparison_v2", "reminders": [{"private": "stale"}],
                "production_unchanged": True,
            }), encoding="utf-8")
            summary = settle_and_summarize_v2_weekly(root=root, as_of=DECISION_DATE)
            self.assertEqual(summary["status"], PUBLIC_STATUS_UNAVAILABLE)
            self.assertEqual(summary["reminder_count"], 0)
            self.assertNotIn("stale", summary["message"])

    def test_daily_cache_must_stay_under_the_private_v2_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            root.mkdir(parents=True)
            outside = Path(tmp) / "outside.json"
            outside.write_text(json.dumps(_daily_cache()), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_v2_daily_cache(root=root, daily_cache_path=outside)

    def test_capture_requires_the_matching_published_bundle_before_freezing_current_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            out = Path(tmp) / DECISION_DATE / "weekly_m67.json"
            md = out.with_suffix(".md")
            receipt_path = out.with_suffix("").with_suffix(".receipt.json")
            candidates = _candidates()
            source_identity = {"run_id": "official-run", "candidate_digest": "a" * 64}
            weekly = {
                "as_of": DECISION_DATE,
                "run_lineage": {
                    "run_id": "official-run", "candidate_digest": "a" * 64,
                    "price_freshness": {"run_date": DECISION_DATE, "price_data_through": DECISION_DATE},
                },
                "factor_comparison_v2": {
                    "summary_id": "a_short_factor_comparison_v2", "status": "not_configured",
                    "reminder_count": 0,
                    "admission_binding": _admission_binding(),
                    "public_progress": _public_progress(),
                    "message": "对比轨 v2：未配置；未读取或写入对比证据，生产结论不变。",
                    "production_unchanged": True,
                },
            }
            receipt_path = write_content_bound_bundle(out, weekly)
            result = capture_v2_after_published_weekly(
                root=root, decision_date=DECISION_DATE, candidates=candidates,
                source_identity=source_identity, out_path=out, receipt_path=receipt_path,
                forward_eligible=False)
            self.assertEqual(result["status"], "captured")
            receipt_path.unlink()
            with self.assertRaises(ValueError):
                capture_v2_after_published_weekly(
                    root=root, decision_date=DECISION_DATE, candidates=candidates,
                    source_identity=source_identity, out_path=out, receipt_path=receipt_path,
                forward_eligible=False)

    def test_weekend_canonical_capture_binds_friday_price_but_keeps_monday_decision_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            out = Path(tmp) / DECISION_DATE / "weekly_m67.json"
            md = out.with_suffix(".md")
            receipt_path = out.with_suffix("").with_suffix(".receipt.json")
            run_date, price_data_through = "20260131", "20260130"
            candidates = _candidates()
            for candidate in candidates:
                candidate["price_series"] = candidate["price_series"][:-1]
                self.assertEqual(candidate["price_series"][-1]["trade_date"], price_data_through)
                candidate["close"] = candidate["price_series"][-1]["close"]
            source_identity = {"run_id": "official-run", "candidate_digest": "a" * 64}
            weekly = {
                "as_of": DECISION_DATE,
                "run_lineage": {
                    "run_id": "official-run", "candidate_digest": "a" * 64,
                    "price_freshness": {
                        "mode": "intraday_prior_settled", "run_date": run_date,
                        "accepted_prior_settled_date": price_data_through,
                        "price_data_through": price_data_through,
                    },
                },
                "factor_comparison_v2": {
                    "summary_id": "a_short_factor_comparison_v2", "status": "not_configured",
                    "reminder_count": 0,
                    "admission_binding": _admission_binding(),
                    "public_progress": _public_progress(),
                    "message": "对比轨 v2：未配置；未读取或写入对比证据，生产结论不变。",
                    "production_unchanged": True,
                },
            }
            receipt_path = write_content_bound_bundle(out, weekly)
            with mock.patch("engine.a_short_factor_comparison_v2._today", return_value=run_date):
                result = capture_v2_after_published_weekly(
                    root=root, decision_date=DECISION_DATE, candidates=candidates,
                    source_identity=source_identity, out_path=out, receipt_path=receipt_path,
                    forward_eligible=True)
            self.assertEqual(result["status"], "captured")
            identity = result["capture"]["payload"]["run_identity"]
            self.assertEqual(identity["run_date"], run_date)
            self.assertEqual(identity["price_data_through"], price_data_through)
            self.assertEqual(result["capture"]["decision_date"], DECISION_DATE)
            _validate_capture_integrity(result["capture"])

            tampered = copy.deepcopy(result["capture"])
            tampered["payload"]["run_identity"]["price_data_through"] = "20260129"
            tampered["payload"]["capture_sha256"] = v1._digest({
                key: value for key, value in tampered["payload"].items() if key != "capture_sha256"
            })
            with self.assertRaisesRegex(ComparisonV2Error, "does not end at frozen price_data_through"):
                _validate_capture_integrity(tampered)

    def test_forward_capture_rejects_forged_or_mismatched_price_freshness_lineage(self):
        # Negative guards for the weekend/live-canonical forward binding: a forward capture must match the
        # official M6.7 price_freshness lineage. A forged mode or an unbound price_data_through must raise
        # (mirrors the positive weekend test above, which is the only path allowed to succeed).
        run_date, price_data_through = "20260131", "20260130"
        source_identity = {"run_id": "official-run", "candidate_digest": "a" * 64}

        def _attempt(mode: str, accepted: str):
            with tempfile.TemporaryDirectory() as tmp:
                root = _root(tmp)
                out = Path(tmp) / DECISION_DATE / "weekly_m67.json"
                md = out.with_suffix(".md")
                receipt_path = out.with_suffix("").with_suffix(".receipt.json")
                weekly = {
                    "as_of": DECISION_DATE,
                    "run_lineage": {
                        "run_id": "official-run", "candidate_digest": "a" * 64,
                        "price_freshness": {
                            "mode": mode, "run_date": run_date,
                            "accepted_prior_settled_date": accepted,
                            "price_data_through": price_data_through,
                        },
                    },
                    "factor_comparison_v2": {
                        "summary_id": "a_short_factor_comparison_v2", "status": "not_configured",
                        "reminder_count": 0,
                        "admission_binding": _admission_binding(),
                        "public_progress": _public_progress(),
                        "message": "对比轨 v2：未配置；未读取或写入对比证据，生产结论不变。",
                        "production_unchanged": True,
                    },
                }
                receipt_path = write_content_bound_bundle(out, weekly)
                with mock.patch("engine.a_short_factor_comparison_v2._today", return_value=run_date):
                    capture_v2_after_published_weekly(
                        root=root, decision_date=DECISION_DATE, candidates=_candidates(),
                        source_identity=source_identity, out_path=out, receipt_path=receipt_path,
                        forward_eligible=True)

        # (a) wrong price-freshness mode (not the live-canonical intraday_prior_settled) for a weekend forward capture
        with self.assertRaisesRegex(ComparisonV2Error, "live canonical price-freshness mode"):
            _attempt(mode="strict_as_of", accepted=price_data_through)
        # (b) price_data_through != decision_date AND not bound to the official accepted prior-settled date
        with self.assertRaisesRegex(ComparisonV2Error, "prior-settled binding"):
            _attempt(mode="intraday_prior_settled", accepted="20260129")


if __name__ == "__main__":
    unittest.main()
