"""Tests for the V14.3 regime comparison runner (slice 2b-impl ②b-2) — pure core + persistence.

Pins: iv_series_to_map validates the IV feed (reject dup/wrong-schema); make_feature_provider yields
valid rows; production-path guard; ledger/records/panel persistence; run_regime_step is
explicit-bootstrap-only (no-ledger+no-bootstrap raises; <252-day bootstrap raises; >=252 bootstrap
persists), supports weekly append with a ledger-spanning calendar + narrow daily window, and is
idempotent across reruns; CLI rejects a non-canonical --as-of before any fetch. The thin real Tushare
fetch is not unit-tested (it is the user-authorized 执行 layer).
"""
from __future__ import annotations

import sys
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_regime_comparison_runner import (  # noqa: E402
    iv_series_to_map, make_feature_provider, run_regime_step, save_panel, save_ledger,
    save_comparison_records, load_ledger, load_comparison_records, main, main_board_only,
    _latest_settled_as_of, save_action_records, render_action_review_reminder,
    run_candidate_effect_sidecar, write_candidate_effect_outcome,
)
from engine.a_short_regime_action_comparison import build_action_record  # noqa: E402
from engine.a_short_regime_features import compute_regime_daily_features  # noqa: E402
from engine.a_short_regime_ledger import build_ledger, BACKFILL_MIN_TRADING_DAYS  # noqa: E402


def _dates(n, start=date(2023, 1, 2)):
    return [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(n)]


def _daily(cal):
    return pd.DataFrame([(d, "A", 11.0, 10.0) for d in cal],
                        columns=["trade_date", "ts_code", "high", "close"])


def _limit(cal):
    return pd.DataFrame([(d, "A", 11.0, 9.0) for d in cal],
                        columns=["trade_date", "ts_code", "up_limit", "down_limit"])


def _idx(cal):
    return pd.DataFrame([(d, 100.0 + i) for i, d in enumerate(cal)], columns=["trade_date", "close"])


def _feed(cal):
    return {
        "schema_name": "a_short_iv_feed", "schema_version": "1.1.0", "generated_at": "x",
        "as_of": cal[-1], "underlying": "510050.SH",
        "params": {"risk_free": 0.02, "div_yield": 0.0, "const_maturity_days": 30, "min_t_days": 5,
                   "roll_window": 252, "min_roll_obs": 60, "hv_window": 21},
        "n_days": len(cal),
        "series": [{"trade_date": d, "iv_value": 0.2, "iv_percentile_252d": 50.0, "hv_value": 0.18} for d in cal],
        "boundary": {"production": False, "real_money": False, "satisfies_ship_gate": False,
                     "iv_method": "bs_atm_constant_maturity_feasibility_grade"},
    }


def _row(d):
    return {
        "schema_name": "a_short_market_regime_daily", "schema_version": "1.0.0",
        "as_of": d, "limit_up_count": 0, "limit_down_count": 0, "net_limit": 0,
        "max_limit_streak": 0, "promotion_rate": None, "failed_limit_rate": None,
        "iv_percentile_252d": 50.0, "csi300_ret_1d": None, "csi1000_ret_1d": None,
        "pct_above_ma20": None, "csi1000_below_ma20": None,
        "data_quality_flags": ["csi1000_unavailable"],
        "boundary": {"production": False, "comparison_only": True, "drives_phase5_risk_posture": False},
    }


def _stateful_rows(n: int, *, defense_last: bool = True) -> list[dict]:
    rows = []
    for d in _dates(n):
        rows.append({
            "schema_name": "a_short_market_regime_daily", "schema_version": "1.0.0",
            "as_of": d, "limit_up_count": 20, "limit_down_count": 5, "net_limit": 15,
            "max_limit_streak": 3, "promotion_rate": 0.30, "failed_limit_rate": 0.20,
            "iv_percentile_252d": 50.0, "csi300_ret_1d": 0.2, "csi1000_ret_1d": 0.3,
            "pct_above_ma20": 55.0, "csi1000_below_ma20": False, "data_quality_flags": [],
            "boundary": {"production": False, "comparison_only": True,
                         "drives_phase5_risk_posture": False},
        })
    if defense_last:
        rows[-1]["iv_percentile_252d"] = 95.0
    return rows


def _write_tracker(path: Path, as_of: str, *, digest: str, values: dict[str, float | None],
                   forward_live: bool = True, append: bool = False) -> None:
    columns = ["as_of", "ts_code", "candidate_digest", "run_id", "forward_live"]
    for days in (5, 10, 20):
        columns.extend((f"ret_{days}d_t1_net", f"ret_{days}d_excess_csi1000", f"ret_{days}d_status"))
    lines = (path.read_text(encoding="utf-8").rstrip().splitlines() if append and path.exists()
             else [",".join(columns)])
    for code, value in values.items():
        row = [as_of, code, digest, f"a-short-{as_of}-0123456789abcdef", str(forward_live)]
        for days in (5, 10, 20):
            if value is None:
                row.extend(("", "", "pending_capture"))
            else:
                # Stock return - CSI1000 return = excess.  The sidecar must recover the benchmark
                # from only these tracker fields rather than reading raw price inputs.
                row.extend((str(value), str(value + 0.5), "ok"))
        lines.append(",".join(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_m67(path: Path, as_of: str, *, digest: str, codes: list[str]) -> None:
    run_id = f"a-short-{as_of}-0123456789abcdef"
    path.write_text(json.dumps({
        "schema_name": "a_short_weekly_report", "as_of": as_of,
        "run_lineage": {
            "candidate_digest": digest, "run_id": run_id,
            "price_freshness": {"mode": "strict_as_of", "run_date": as_of,
                                 "price_data_through": as_of},
        },
        "reports": [{
            "ts_code": code, "row_source": "egs_candidate",
            "m67": {"table": {"操作": "建仓"}},
            "machine": {"stateful_risk": {"position_state": "flat"},
                        "rule6_gate": {"disposition": "clear"}, "layer": {"hard_veto": []}},
        } for code in codes],
    }, ensure_ascii=False), encoding="utf-8")
    path.with_name("weekly_m67.receipt.json").write_text(json.dumps({
        "schema_name": "a_short_weekly_publish_receipt", "schema_version": "1.0.0",
        "as_of": as_of, "run_id": run_id, "candidate_digest": digest,
        "stage_status": "complete",
    }, ensure_ascii=False), encoding="utf-8")


class PureHelperTests(unittest.TestCase):
    def test_action_review_reminder_state_matrix_preserves_no_auto_switch_boundary(self):
        base = {
            "total_forward_weeks": 12,
            "settled_divergence_h10": 8,
            "automatic_production_switch": False,
        }
        self.assertIsNone(render_action_review_reminder({**base, "status": "accumulating"}))

        candidate = render_action_review_reminder({**base, "status": "review_candidate_preferred"})
        self.assertIn("启动 V14.3 晋级证据复核", candidate)
        self.assertIn("≥2 年 PIT 回测", candidate)
        self.assertIn("comparison-only", candidate)
        self.assertNotIn("是否进入生产切换审查", candidate)

        baseline = render_action_review_reminder({**base, "status": "review_baseline_preferred"})
        self.assertIn("审查退役或继续收集", baseline)
        inconclusive = render_action_review_reminder({**base, "status": "review_inconclusive"})
        self.assertIn("审查退役或继续收集", inconclusive)

        with self.assertRaises(ValueError):
            render_action_review_reminder({**base, "status": "unknown"})
        with self.assertRaises(ValueError):
            render_action_review_reminder({**base, "status": "review_candidate_preferred",
                                            "automatic_production_switch": True})

    def test_latest_settled_as_of_caps_to_available_settled_day(self):
        # intraday: requested Monday(0615) but daily settled only through Friday(0612) → cap to Friday
        d = pd.DataFrame({"trade_date": ["20260611", "20260612"], "ts_code": ["A", "A"],
                          "high": [1.0, 1.0], "close": [1.0, 1.0]})
        self.assertEqual(_latest_settled_as_of(d, "20260615"), "20260612")
        # settled requested day present → no-op (max == requested)
        self.assertEqual(_latest_settled_as_of(d, "20260612"), "20260612")
        # rows after requested are ignored (only <= requested counts)
        d2 = pd.DataFrame({"trade_date": ["20260612", "20260618"], "ts_code": ["A", "A"],
                           "high": [1.0, 1.0], "close": [1.0, 1.0]})
        self.assertEqual(_latest_settled_as_of(d2, "20260615"), "20260612")
        # empty panel → requested (caller guards empty separately)
        self.assertEqual(_latest_settled_as_of(pd.DataFrame(columns=["trade_date"]), "20260615"), "20260615")

    def test_iv_series_to_map_validates(self):
        cal = _dates(3)
        self.assertEqual(iv_series_to_map(None), {})
        self.assertEqual(iv_series_to_map(_feed(cal))[cal[0]], 50.0)

    def test_iv_feed_duplicate_date_rejected(self):
        cal = _dates(3)
        feed = _feed(cal)
        feed["series"].append({"trade_date": cal[0], "iv_value": 0.2, "iv_percentile_252d": 95.0})
        feed["n_days"] = len(feed["series"])
        with self.assertRaises(Exception):
            iv_series_to_map(feed)

    def test_iv_feed_wrong_schema_rejected(self):
        feed = _feed(_dates(3))
        feed["schema_name"] = "bogus"
        with self.assertRaises(Exception):
            iv_series_to_map(feed)

    def test_make_feature_provider_yields_valid_row(self):
        cal = _dates(3)
        provider = make_feature_provider(_daily(cal), _limit(cal), _idx(cal), _idx(cal),
                                         iv_series_to_map(_feed(cal)))
        row = provider(cal[-1])
        self.assertEqual(row["as_of"], cal[-1])
        self.assertEqual(row["net_limit"], row["limit_up_count"] - row["limit_down_count"])

    def test_production_path_guard(self):
        with self.assertRaises(ValueError):
            save_panel("x", str(ROOT / "result" / "a_short" / "20240101" / "panel.md"))

    def test_main_board_only_filters_non_main(self):
        # R-V143-PREBOOTSTRAP-MAINBOARD-FILTER-BSHARE-LEAK: B-shares (200/900) must also be dropped.
        df = pd.DataFrame([("600000.SH",), ("000001.SZ",), ("002001.SZ",), ("003001.SZ",),
                           ("300750.SZ",), ("688981.SH",), ("920083.BJ",),
                           ("200001.SZ",), ("900901.SH",), ("garbage",)], columns=["ts_code"])
        kept = set(main_board_only(df)["ts_code"])
        self.assertEqual(kept, {"600000.SH", "000001.SZ", "002001.SZ", "003001.SZ"})

    def test_init_pro_delegates_to_sanctioned_init(self):
        # Optional: prove _init_pro uses the no-set_token sanctioned initializer, not ts.set_token.
        import os as _os, runners.a_short_regime_comparison_runner as r
        import runners.a_short_iv_feed_probe as probe
        from unittest import mock
        sentinel = object()
        with mock.patch.dict(_os.environ, {"TUSHARE_TOKEN": "tok"}), \
                mock.patch.object(probe, "init_tushare_pro", return_value=sentinel) as m:
            self.assertIs(r._init_pro(), sentinel)
            m.assert_called_once_with("tok")

    def test_main_board_filter_enables_compute(self):
        # mirrors the probe finding: a .BJ stock without stk_limit trips the fail-closed gate; filtering
        # to main board resolves it. d="20240105" canonical.
        d = "20240105"
        daily = pd.DataFrame([(d, "600000.SH", 11.0, 10.0), (d, "920083.BJ", 11.0, 10.0)],
                             columns=["trade_date", "ts_code", "high", "close"])
        stk_limit = pd.DataFrame([(d, "600000.SH", 11.0, 9.0)],   # no usable .BJ limit row
                                 columns=["trade_date", "ts_code", "up_limit", "down_limit"])
        with self.assertRaises(ValueError):                       # unfiltered → fail-closed on .BJ
            compute_regime_daily_features(d, daily, stk_limit, _idx([d]), _idx([d]))
        row = compute_regime_daily_features(d, main_board_only(daily), main_board_only(stk_limit),
                                            _idx([d]), _idx([d]))   # filtered → succeeds
        self.assertEqual(row["as_of"], d)

    def test_save_records_rejects_duplicate(self):
        from engine.a_short_regime_classifier import build_comparison_record
        rec = build_comparison_record([_row(_dates(1)[0])], "unknown", as_of=_dates(1)[0])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                save_comparison_records([rec, dict(rec)], str(Path(tmp) / "r.json"))


class CandidateEffectSidecarTests(unittest.TestCase):
    def test_nonupdated_outcome_is_deidentified_and_preserves_prior_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = root / "research/results/a_short/regime_candidate_effect_summary.json"
            outcome = root / "research/results/a_short/candidate_effect_outcome.json"
            summary.parent.mkdir(parents=True)
            prior = json.loads((ROOT / "research/results/a_short/regime_candidate_effect_summary.json").read_text(encoding="utf-8"))
            prior["latest_evidence_as_of"] = "20260720"
            prior["source_hash"] = "0" * 64
            summary.write_text(json.dumps(prior), encoding="utf-8")
            receipt = write_candidate_effect_outcome(
                as_of="20260727",
                result={
                    "status": "skipped_source_mismatch",
                    "reason_code": "run_identity_mismatch",
                },
                summary_path=str(summary),
                outcome_path=str(outcome),
            )
        self.assertEqual(receipt["observed_as_of"], "20260720")
        self.assertNotIn("ts_code", json.dumps(receipt))

    def test_nonupdated_outcome_drops_clock_from_an_invalid_prior_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = root / "research/results/a_short/regime_candidate_effect_summary.json"
            outcome = root / "research/results/a_short/candidate_effect_outcome.json"
            summary.parent.mkdir(parents=True)
            summary.write_text(json.dumps({"latest_evidence_as_of": "20260720"}), encoding="utf-8")
            receipt = write_candidate_effect_outcome(
                as_of="20260727",
                result={"status": "skipped_source_mismatch", "reason_code": "run_identity_mismatch"},
                summary_path=str(summary), outcome_path=str(outcome),
            )
        self.assertIsNone(receipt["observed_as_of"])

    def test_outcome_status_and_reason_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outcome = root / "research/results/a_short/candidate_effect_outcome.json"
            summary = json.loads(
                (ROOT / "research/results/a_short/regime_candidate_effect_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            with self.assertRaises(jsonschema.ValidationError):
                write_candidate_effect_outcome(
                    as_of="20260727",
                    result={
                        "status": "updated",
                        "reason_code": "m67_digest_drift",
                        "summary": summary,
                    },
                    summary_path=str(root / "unused-summary.json"),
                    outcome_path=str(outcome),
                )

    def _paths(self, tmp: str) -> dict:
        base = Path(tmp)
        return {
            "m67_report_path": str(base / "weekly_m67.json"),
            "tracker_path": str(base / "forward_tracker.csv"),
            "ledger_path": str(base / "private_candidate_effect.json"),
            "summary_path": str(base / "summary.json"),
            "markdown_path": str(base / "summary.md"),
        }

    def _run(self, paths: dict, as_of: str, *, run_date: str):
        with patch("runners.a_short_regime_comparison_runner._current_run_date", return_value=run_date):
            return run_candidate_effect_sidecar(
                decision_as_of=as_of, regime_ledger={"rows": _stateful_rows(BACKFILL_MIN_TRADING_DAYS)},
                **paths,
            )

    def test_freeze_idempotence_then_cache_only_mature_backfill_and_aggregate_mirror(self):
        as_of, digest = _dates(BACKFILL_MIN_TRADING_DAYS)[-1], "a" * 64
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            _write_tracker(Path(paths["tracker_path"]), as_of, digest=digest,
                           values={"000001.SZ": None, "000002.SZ": None})
            _write_m67(Path(paths["m67_report_path"]), as_of, digest=digest,
                       codes=["000001.SZ", "000002.SZ"])
            first = self._run(paths, as_of, run_date=as_of)
            first_bytes = Path(paths["ledger_path"]).read_bytes()
            second = self._run(paths, as_of, run_date=as_of)
            self.assertEqual(first["status"], "updated")
            self.assertEqual(second["status"], "updated")
            self.assertEqual(Path(paths["ledger_path"]).read_bytes(), first_bytes)

            _write_tracker(Path(paths["tracker_path"]), as_of, digest=digest,
                           values={"000001.SZ": -1.0, "000002.SZ": -3.0})
            mature = self._run(paths, as_of, run_date=as_of)
            summary = json.loads(Path(paths["summary_path"]).read_text(encoding="utf-8"))
            private = Path(paths["ledger_path"]).read_text(encoding="utf-8")
            markdown = Path(paths["markdown_path"]).read_text(encoding="utf-8")
        self.assertEqual(mature["status"], "updated")
        self.assertEqual(summary["evidence_progress"]["valid_divergence_stocks"], 2)
        self.assertEqual(summary["operation_effect"]["weekly_mean_improvement_pp"], 2.0)
        self.assertIn("comparison-only", markdown)
        self.assertNotIn("000001.SZ", json.dumps(summary, ensure_ascii=False))
        self.assertNotIn("000002.SZ", markdown)
        mirror = markdown.split("<!-- candidate-effect-summary-json:", 1)[1].split(" -->", 1)[0]
        self.assertEqual(json.loads(mirror), summary)
        self.assertNotIn("position_state", private)
        self.assertNotIn("account_snapshot", private)

    def test_m67_tracker_digest_mismatch_is_not_counted_or_written(self):
        as_of = _dates(BACKFILL_MIN_TRADING_DAYS)[-1]
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            _write_tracker(Path(paths["tracker_path"]), as_of, digest="a" * 64,
                           values={"000001.SZ": None})
            _write_m67(Path(paths["m67_report_path"]), as_of, digest="b" * 64, codes=["000001.SZ"])
            result = self._run(paths, as_of, run_date=as_of)
            self.assertEqual(result["status"], "skipped_source_mismatch")
            self.assertEqual(result["reason_code"], "run_identity_mismatch")
            self.assertFalse(Path(paths["ledger_path"]).exists())
            self.assertFalse(Path(paths["summary_path"]).exists())

    def test_historical_replay_is_persisted_but_never_counts_as_forward_evidence(self):
        as_of, digest = _dates(BACKFILL_MIN_TRADING_DAYS)[-1], "a" * 64
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            _write_tracker(Path(paths["tracker_path"]), as_of, digest=digest,
                           values={"000001.SZ": -1.0})
            _write_m67(Path(paths["m67_report_path"]), as_of, digest=digest, codes=["000001.SZ"])
            self._run(paths, as_of, run_date=_dates(BACKFILL_MIN_TRADING_DAYS + 1)[-1])
            summary = json.loads(Path(paths["summary_path"]).read_text(encoding="utf-8"))
        self.assertEqual(summary["evidence_progress"]["forward_live_weeks"], 0)
        self.assertEqual(summary["evidence_progress"]["historical_not_counted"], 1)

    def test_new_week_cache_only_backfills_mature_prior_week(self):
        as_of_1 = _dates(BACKFILL_MIN_TRADING_DAYS)[-1]
        as_of_2 = _dates(BACKFILL_MIN_TRADING_DAYS + 1)[-1]
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            _write_tracker(Path(paths["tracker_path"]), as_of_1, digest="a" * 64,
                           values={"000001.SZ": None})
            _write_m67(Path(paths["m67_report_path"]), as_of_1, digest="a" * 64, codes=["000001.SZ"])
            self._run(paths, as_of_1, run_date=as_of_1)
            _write_tracker(Path(paths["tracker_path"]), as_of_1, digest="a" * 64,
                           values={"000001.SZ": -2.0})
            _write_tracker(Path(paths["tracker_path"]), as_of_2, digest="b" * 64,
                           values={"000002.SZ": None}, append=True)
            _write_m67(Path(paths["m67_report_path"]), as_of_2, digest="b" * 64, codes=["000002.SZ"])
            self._run(paths, as_of_2, run_date=as_of_2)
            summary = json.loads(Path(paths["summary_path"]).read_text(encoding="utf-8"))
        self.assertEqual(summary["evidence_progress"]["forward_live_weeks"], 2)
        self.assertEqual(summary["evidence_progress"]["valid_divergence_stocks"], 1)
        self.assertEqual(summary["operation_effect"]["weekly_mean_improvement_pp"], 2.0)

    def test_same_date_authority_replacement_cannot_overwrite_mature_evidence(self):
        as_of, digest = _dates(BACKFILL_MIN_TRADING_DAYS)[-1], "a" * 64
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            _write_tracker(Path(paths["tracker_path"]), as_of, digest=digest,
                           values={"000001.SZ": -1.0})
            _write_m67(Path(paths["m67_report_path"]), as_of, digest=digest, codes=["000001.SZ"])
            self._run(paths, as_of, run_date=as_of)
            prior = Path(paths["ledger_path"]).read_bytes()
            _write_tracker(Path(paths["tracker_path"]), as_of, digest="b" * 64,
                           values={"000002.SZ": -9.0})
            _write_m67(Path(paths["m67_report_path"]), as_of, digest="b" * 64, codes=["000002.SZ"])
            result = self._run(paths, as_of, run_date=as_of)
            self.assertEqual(result["status"], "skipped_immutable_mature_week")
            self.assertEqual(Path(paths["ledger_path"]).read_bytes(), prior)

    def test_unmatured_same_date_tracker_authority_replacement_replaces_the_cohort(self):
        as_of = _dates(BACKFILL_MIN_TRADING_DAYS)[-1]
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            _write_tracker(Path(paths["tracker_path"]), as_of, digest="a" * 64,
                           values={"000001.SZ": None})
            _write_m67(Path(paths["m67_report_path"]), as_of, digest="a" * 64, codes=["000001.SZ"])
            self._run(paths, as_of, run_date=as_of)
            _write_tracker(Path(paths["tracker_path"]), as_of, digest="b" * 64,
                           values={"000002.SZ": None})
            _write_m67(Path(paths["m67_report_path"]), as_of, digest="b" * 64, codes=["000002.SZ"])
            result = self._run(paths, as_of, run_date=as_of)
            private = json.loads(Path(paths["ledger_path"]).read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "updated")
        groups = private["policy_groups"]
        records = next(iter(groups.values()))["records"]
        self.assertEqual([row["ts_code"] for row in records], ["000002.SZ"])

    def test_same_date_m67_sha_drift_is_not_counted_or_overwritten(self):
        as_of, digest = _dates(BACKFILL_MIN_TRADING_DAYS)[-1], "a" * 64
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp)
            _write_tracker(Path(paths["tracker_path"]), as_of, digest=digest,
                           values={"000001.SZ": None})
            _write_m67(Path(paths["m67_report_path"]), as_of, digest=digest, codes=["000001.SZ"])
            self._run(paths, as_of, run_date=as_of)
            prior = Path(paths["ledger_path"]).read_bytes()
            m67 = json.loads(Path(paths["m67_report_path"]).read_text(encoding="utf-8"))
            m67["same_day_rerun_marker"] = "changed-source-bytes"
            Path(paths["m67_report_path"]).write_text(json.dumps(m67), encoding="utf-8")
            result = self._run(paths, as_of, run_date=as_of)
            self.assertEqual(result["status"], "skipped_source_mismatch")
            self.assertEqual(Path(paths["ledger_path"]).read_bytes(), prior)

    def test_regime_runner_uses_the_same_m67_input_without_mutating_it(self):
        cal = _dates(BACKFILL_MIN_TRADING_DAYS)
        as_of, digest = cal[-1], "a" * 64
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            paths = self._paths(tmp)
            _write_tracker(Path(paths["tracker_path"]), as_of, digest=digest,
                           values={"000001.SZ": None})
            _write_m67(Path(paths["m67_report_path"]), as_of, digest=digest, codes=["000001.SZ"])
            before = Path(paths["m67_report_path"]).read_bytes()
            out = None
            with patch("runners.a_short_regime_comparison_runner._current_run_date", return_value=as_of):
                out = run_regime_step(
                    as_of=as_of, trade_calendar=cal, v14_2_regime="shock",
                    daily=pd.DataFrame(columns=["trade_date", "ts_code", "high", "close"]),
                    stk_limit=pd.DataFrame(columns=["trade_date", "ts_code", "up_limit", "down_limit"]),
                    csi300=_idx(cal), csi1000=_idx(cal), iv_feed=None,
                    ledger_path=str(base / "regime_ledger.json"),
                    records_path=str(base / "regime_records.json"), panel_path=str(base / "panel.md"),
                    bootstrap=True, feature_provider=lambda d: _row(d),
                    raw_v14_2_regime="unknown", m67_report_path=paths["m67_report_path"],
                    action_records_path=str(base / "actions.json"),
                    action_summary_path=str(base / "action_summary.json"), action_decision_as_of=as_of,
                    candidate_effect_ledger_path=paths["ledger_path"],
                    candidate_effect_summary_path=paths["summary_path"],
                    candidate_effect_markdown_path=paths["markdown_path"],
                    forward_tracker_path=paths["tracker_path"],
                )
            self.assertEqual(out["candidate_effect"]["status"], "updated")
            self.assertEqual(Path(paths["m67_report_path"]).read_bytes(), before)
            self.assertTrue(Path(paths["summary_path"]).exists())


class BootstrapPolicyTests(unittest.TestCase):
    # inject a fast fake feature_provider so the 252-scale orchestration/policy tests don't trigger
    # 252 real computes (the real compute is covered by test_a_short_regime_features + the provider
    # integration by test_make_feature_provider_yields_valid_row). csi1000 is real (used by backfill).
    def _kw(self, cal, tmp, bootstrap):
        empty_daily = pd.DataFrame(columns=["trade_date", "ts_code", "high", "close"])
        empty_limit = pd.DataFrame(columns=["trade_date", "ts_code", "up_limit", "down_limit"])
        return dict(as_of=cal[-1], trade_calendar=cal, v14_2_regime="unknown",
                    daily=empty_daily, stk_limit=empty_limit, csi300=_idx(cal), csi1000=_idx(cal),
                    iv_feed=None, ledger_path=str(Path(tmp) / "l.json"),
                    records_path=str(Path(tmp) / "r.json"), panel_path=str(Path(tmp) / "p.md"),
                    bootstrap=bootstrap, feature_provider=lambda d: _row(d))

    def test_no_ledger_without_bootstrap_raises(self):
        cal = _dates(6)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run_regime_step(**self._kw(cal, tmp, bootstrap=False))

    def test_insufficient_bootstrap_raises(self):
        cal = _dates(6)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run_regime_step(**self._kw(cal, tmp, bootstrap=True))   # 6 < 252

    def test_sufficient_bootstrap_persists(self):
        cal = _dates(BACKFILL_MIN_TRADING_DAYS)
        with tempfile.TemporaryDirectory() as tmp:
            out = run_regime_step(**self._kw(cal, tmp, bootstrap=True))
            self.assertEqual(out["ledger"]["coverage"]["n"], BACKFILL_MIN_TRADING_DAYS)
            self.assertEqual(out["evidence"]["total_weeks"], 1)
            self.assertEqual(len(load_ledger(str(Path(tmp) / "l.json"))["rows"]),
                             BACKFILL_MIN_TRADING_DAYS)

    def test_weekly_append_with_spanning_calendar_and_narrow_daily(self):
        # R-V143-SLICE2B-RUNNER-SHORT-CALENDAR-BLOCKS-WEEKLY-APPEND: 252-row ledger + 1 new day.
        n = BACKFILL_MIN_TRADING_DAYS
        cal = _dates(n + 1)                       # full span incl. the new day
        with tempfile.TemporaryDirectory() as tmp:
            lpath = str(Path(tmp) / "l.json")
            save_ledger(build_ledger([_row(d) for d in cal[:n]]), lpath,
                        as_of=cal[n - 1], trade_calendar=cal[:n])
            empty_daily = pd.DataFrame(columns=["trade_date", "ts_code", "high", "close"])
            empty_limit = pd.DataFrame(columns=["trade_date", "ts_code", "up_limit", "down_limit"])
            out = run_regime_step(as_of=cal[n], trade_calendar=cal, v14_2_regime="unknown",
                                  daily=empty_daily, stk_limit=empty_limit,
                                  csi300=_idx(cal), csi1000=_idx(cal), iv_feed=None,
                                  ledger_path=lpath, records_path=str(Path(tmp) / "r.json"),
                                  panel_path=str(Path(tmp) / "p.md"), bootstrap=False,
                                  feature_provider=lambda d: _row(d))
            self.assertEqual(out["ledger"]["coverage"]["n"], n + 1)

    def test_rerun_idempotent(self):
        cal = _dates(BACKFILL_MIN_TRADING_DAYS)
        with tempfile.TemporaryDirectory() as tmp:
            run_regime_step(**self._kw(cal, tmp, bootstrap=True))
            out2 = run_regime_step(**self._kw(cal, tmp, bootstrap=False))   # rerun weekly
            self.assertEqual(out2["ledger"]["coverage"]["n"], BACKFILL_MIN_TRADING_DAYS)
            self.assertEqual(out2["evidence"]["total_weeks"], 1)

    def test_d2_action_sidecar_freezes_raw_effective_and_source_digest(self):
        cal = _dates(BACKFILL_MIN_TRADING_DAYS)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            report = base / "weekly_m67.json"
            _write_m67(report, cal[-1], digest="a" * 64, codes=[])
            kw = self._kw(cal, tmp, bootstrap=True)
            kw.update(v14_2_regime="shock", raw_v14_2_regime="unknown",
                      m67_report_path=str(report), action_records_path=str(base / "actions.json"),
                      action_summary_path=str(base / "summary.json"), action_decision_as_of=cal[-1])
            with patch("runners.a_short_regime_comparison_runner._current_run_date", return_value=cal[-1]):
                out = run_regime_step(**kw)
            self.assertEqual(out["action_comparison"]["records"][0]["raw_v14_2_regime"], "unknown")
            self.assertEqual(out["action_comparison"]["records"][0]["effective_v14_2_regime"], "shock")
            self.assertTrue(out["action_comparison"]["records"][0]["forward_eligible"])
            self.assertTrue((base / "actions.json").exists())

    def test_d2_same_settled_week_rerun_keeps_first_frozen_m67_provenance(self):
        cal = _dates(BACKFILL_MIN_TRADING_DAYS)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            report = base / "weekly_m67.json"
            _write_m67(report, cal[-1], digest="a" * 64, codes=[])
            kw = self._kw(cal, tmp, bootstrap=True)
            kw.update(v14_2_regime="shock", raw_v14_2_regime="unknown",
                      m67_report_path=str(report), action_records_path=str(base / "actions.json"),
                      action_summary_path=str(base / "summary.json"), action_decision_as_of=cal[-1])
            with patch("runners.a_short_regime_comparison_runner._current_run_date", return_value=cal[-1]):
                first = run_regime_step(**kw)
                first_digest = first["action_comparison"]["records"][0]["m67_provenance"]["source_sha256"]
                report.write_text(json.dumps({"schema_name": "a_short_weekly_report", "as_of": cal[-1],
                                              "reports": [], "rerun_marker": "account_scope_changed"}),
                                  encoding="utf-8")
                second = run_regime_step(**{**kw, "bootstrap": False})
            self.assertEqual(second["action_comparison"]["records"][0]["m67_provenance"]["source_sha256"],
                             first_digest)

    def test_d2_candidate_review_reminder_is_persisted_to_comparison_panel(self):
        cal = _dates(BACKFILL_MIN_TRADING_DAYS)
        summary = {
            "total_forward_weeks": 12,
            "settled_divergence_h10": 8,
            "automatic_production_switch": False,
            "status": "review_candidate_preferred",
        }
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            report = base / "weekly_m67.json"
            _write_m67(report, cal[-1], digest="a" * 64, codes=[])
            kw = self._kw(cal, tmp, bootstrap=True)
            kw.update(v14_2_regime="shock", raw_v14_2_regime="unknown",
                      m67_report_path=str(report), action_records_path=str(base / "actions.json"),
                      action_summary_path=str(base / "summary.json"), action_decision_as_of=cal[-1])
            with patch("runners.a_short_regime_comparison_runner._current_run_date", return_value=cal[-1]), \
                    patch("runners.a_short_regime_comparison_runner.summarize_action_records", return_value=summary):
                out = run_regime_step(**kw)
            self.assertIn("启动 V14.3 晋级证据复核", out["action_comparison"]["review_reminder"])
            panel = (base / "p.md").read_text(encoding="utf-8")
            self.assertIn("V14.3 regime review reminder", panel)
            self.assertIn("启动 V14.3 晋级证据复核", panel)
            self.assertNotIn("是否进入生产切换审查", panel)

    def test_d2_historical_decision_is_derived_not_counted(self):
        cal = _dates(BACKFILL_MIN_TRADING_DAYS)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            report = base / "weekly_m67.json"
            _write_m67(report, cal[-1], digest="a" * 64, codes=[])
            historical_source = json.loads(report.read_text(encoding="utf-8"))
            historical_source["run_lineage"]["price_freshness"] = {
                "mode": "strict_as_of", "run_date": cal[-2], "price_data_through": cal[-2],
            }
            report.write_text(json.dumps(historical_source), encoding="utf-8")
            kw = self._kw(cal, tmp, bootstrap=True)
            kw.update(v14_2_regime="shock", raw_v14_2_regime="unknown", m67_report_path=str(report),
                      action_records_path=str(base / "actions.json"),
                      action_summary_path=str(base / "summary.json"),
                      action_decision_as_of=cal[-2])
            out = run_regime_step(**kw)
            row = out["action_comparison"]["records"][0]
            self.assertFalse(row["forward_eligible"])
            self.assertEqual(out["action_comparison"]["summary"]["total_forward_weeks"], 0)

    def test_d2_rejects_current_decision_date_for_historical_settlement_before_writes(self):
        cal = _dates(BACKFILL_MIN_TRADING_DAYS)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            report = base / "weekly_m67.json"
            _write_m67(report, cal[-1], digest="a" * 64, codes=[])
            kw = self._kw(cal, tmp, bootstrap=True)
            kw.update(v14_2_regime="shock", raw_v14_2_regime="unknown", m67_report_path=str(report),
                      action_records_path=str(base / "actions.json"),
                      action_summary_path=str(base / "summary.json"), action_decision_as_of="20260716")
            with patch("runners.a_short_regime_comparison_runner._current_run_date", return_value="20260716"):
                with self.assertRaises(ValueError):
                    run_regime_step(**kw)
            self.assertFalse(Path(kw["ledger_path"]).exists())

    def test_d2_action_writer_cannot_seed_historical_forward_row(self):
        regime = {
            "as_of": "20230102", "v14_3_raw_regime": "defense",
            "v14_3_fired_rule": "broad_index_crash",
            "forward_returns": {"h1": None, "h3": None, "h5": None, "h10": None},
            "forward_returns_pending": ["h1", "h3", "h5", "h10"],
        }
        forged = build_action_record(
            regime_record=regime, raw_v14_2_regime="shock", effective_v14_2_regime="shock",
            m67_source={"source_schema_name": "a_short_weekly_report", "source_as_of": "20230102",
                        "source_sha256": "a" * 64, "candidate_build_count": 0},
            forward_origin={"decision_as_of": "20230102", "run_date": "20230102",
                            "capture_mode": "live", "price_data_through": "20230102",
                            "source_receipt_complete": True, "price_day_latest_settled": True})
        self.assertTrue(forged["forward_eligible"])
        with tempfile.TemporaryDirectory() as tmp:
            with patch("runners.a_short_regime_comparison_runner._current_run_date", return_value="20260716"):
                with self.assertRaises(ValueError):
                    save_action_records([forged], str(Path(tmp) / "actions.json"), current_action=forged,
                                        regime_records=[])

    def test_partial_d2_action_configuration_aborts_before_comparison_writes(self):
        cal = _dates(BACKFILL_MIN_TRADING_DAYS)
        with tempfile.TemporaryDirectory() as tmp:
            kw = self._kw(cal, tmp, bootstrap=True)
            kw.update(raw_v14_2_regime="unknown")
            with self.assertRaises(ValueError):
                run_regime_step(**kw)
            self.assertFalse(Path(kw["ledger_path"]).exists())
            self.assertFalse(Path(kw["records_path"]).exists())
            self.assertFalse(Path(kw["panel_path"]).exists())


class CliGuardTests(unittest.TestCase):
    def test_cli_keeps_zero_exit_and_writes_outcome_when_candidate_source_mismatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {
                "ledger": str(root / "research/results/a_short/regime_daily_ledger.json"),
                "records": str(root / "research/results/a_short/regime_comparison_records.json"),
                "panel": str(root / "research/results/a_short/regime_comparison_panel.md"),
                "action_records": str(root / "research/results/a_short/regime_action_comparison_records.json"),
                "action_summary": str(root / "research/results/a_short/regime_action_comparison_summary.json"),
                "candidate_effect_ledger": str(root / "logs/a_short_regime_candidate_effect.json"),
                "candidate_effect_summary": str(root / "research/results/a_short/regime_candidate_effect_summary.json"),
                "candidate_effect_markdown": str(root / "research/results/a_short/regime_candidate_effect_summary.md"),
                "candidate_effect_outcome": str(root / "research/results/a_short/candidate_effect_outcome.json"),
                "forward_tracker": str(root / "logs/forward_tracker.csv"),
            }
            result = {
                "ledger": {"coverage": {"n": 1}},
                "evidence": "forward",
                "candidate_effect": {
                    "status": "skipped_source_mismatch",
                    "reason_code": "run_identity_mismatch",
                    "reason": "deidentified",
                },
            }
            with patch("runners.a_short_regime_comparison_runner.lane_paths", return_value=paths), \
                    patch("runners.a_short_regime_comparison_runner.load_ledger",
                          return_value={"rows": [{}], "coverage": {"start": "20260701"}}), \
                    patch("runners.a_short_regime_comparison_runner._init_pro", return_value=object()), \
                    patch("runners.a_short_regime_comparison_runner._fetch_trade_calendar",
                          return_value=["20260727"]), \
                    patch("runners.a_short_regime_comparison_runner._fetch_daily",
                          return_value=pd.DataFrame({"trade_date": ["20260727"]})), \
                    patch("runners.a_short_regime_comparison_runner._fetch_stk_limit",
                          return_value=pd.DataFrame()), \
                    patch("runners.a_short_regime_comparison_runner._fetch_index",
                          return_value=pd.DataFrame()), \
                    patch("runners.a_short_regime_comparison_runner.run_regime_step",
                          return_value=result):
                exit_code = main([
                    "--as-of", "20260727",
                    "--v14_2-raw-regime", "unknown",
                    "--m67-report", str(root / "weekly_m67.json"),
                    "--confirm-fetch-authorized",
                ])
            receipt = json.loads(Path(paths["candidate_effect_outcome"]).read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertEqual(receipt["status"], "skipped_source_mismatch")
        self.assertIsNone(receipt["observed_as_of"])

    def test_noncanonical_as_of_rejected_before_fetch(self):
        # R-V143-SLICE2B-RUNNER-CLI-ASOF-LENIENT-FETCH: malformed date fails before any provider call.
        with self.assertRaises(SystemExit):
            main(["--as-of", "2024011", "--confirm-fetch-authorized"])

    def test_cli_refuses_manual_d2_forward_eligibility_flag(self):
        with self.assertRaises(SystemExit):
            main(["--as-of", "20260714", "--d2-forward-eligible"])


if __name__ == "__main__":
    unittest.main()
