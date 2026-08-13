from __future__ import annotations

import copy
import csv
import inspect
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft7Validator

import runners.a_short_entry_funnel_calibration as calibration
from runners.a_short_entry_funnel_calibration import (
    HISTORICAL_REPORT_SCHEMA_PATH,
    PREREG_PATH,
    PREREG_SCHEMA_PATH,
    REPORT_SCHEMA_PATH,
    _adjudicate_calibration,
    build_historical_report,
    build_report,
    load_json,
    main,
)


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_INPUT_SCHEMA_PATH = ROOT / "schemas" / "analysis_input.schema.json"
ANALYSIS_INPUT_EXAMPLE = ROOT / "schemas" / "examples" / "analysis_input.example.json"
HISTORICAL_AS_OF = "20260522"
HISTORICAL_GENERATED_AT = "2026-08-12T00:00:00+00:00"


class AShortEntryFunnelCalibrationTests(unittest.TestCase):
    def _historical_analysis_input(self) -> dict:
        payload = json.loads(ANALYSIS_INPUT_EXAMPLE.read_text(encoding="utf-8"))
        payload["trade_date"] = HISTORICAL_AS_OF
        payload["market_context"]["volatility"].update({
            "iv_symbol": "50ETF",
            "iv_value": 20.0,
            "hv_value": 15.0,
            "iv_percentile_252d": 50.0,
            "iv_change_abs_1d_pctpt": 0.5,
            "rule3_status": "normal",
            "awakening_status": "inactive",
            "cash_reclaim_pct": 0.0,
            "iv_feed_status": "ready",
            "source_status": "complete",
            "freshness_status": "aligned",
            "freshness_reason": "validated_feed",
            "source_as_of": HISTORICAL_AS_OF,
            "source_latest_trade_date": HISTORICAL_AS_OF,
            "source_ref": "iv_feed.json",
            "feed_sha256": "0" * 64,
        })
        return payload

    def _nonready_iv_projection(self, analysis_input: dict, status: str = "build_failed") -> None:
        if status not in {"not_requested", "build_failed", "digest_failed", "clock_mismatch"}:
            raise ValueError(f"unexpected non-ready status: {status}")
        analysis_input["market_context"]["volatility"].update({
            "iv_value": None,
            "hv_value": None,
            "iv_percentile_252d": None,
            "iv_change_abs_1d_pctpt": None,
            "rule3_status": "unknown",
            "awakening_status": "unknown",
            "cash_reclaim_pct": None,
            "iv_feed_status": status,
            "source_status": "unavailable",
            "freshness_status": "not_requested" if status == "not_requested" else "unavailable",
            "freshness_reason": f"iv_feed_{status}",
            "source_as_of": None,
            "source_latest_trade_date": None,
            "source_ref": None,
            "feed_sha256": None,
        })

    def _legacy_healthy_iv_projection(self, analysis_input: dict) -> None:
        volatility = analysis_input["market_context"]["volatility"]
        for key in (
            "iv_feed_status", "source_status", "freshness_status", "freshness_reason",
            "source_as_of", "source_latest_trade_date", "source_ref", "feed_sha256",
        ):
            volatility.pop(key, None)
        volatility.update({
            "iv_percentile_252d": 50.0,
            "rule3_status": "normal",
            "awakening_status": "inactive",
        })

    def _price_rows(self, count: int = 20) -> list[dict[str, str]]:
        start = date(2026, 5, 1)
        code = self._historical_analysis_input()["candidates"][0]["ts_code"]
        return [
            {
                "as_of": HISTORICAL_AS_OF,
                "ts_code": code,
                "trade_date": (start + timedelta(days=offset)).strftime("%Y%m%d"),
                "high": "11.0",
                "low": "9.0",
                "close": "10.0",
            }
            for offset in range(count)
        ]

    def _write_historical_root(
        self,
        root: Path,
        *,
        analysis_input: dict | None = None,
        rows: list[dict[str, str]] | None = None,
    ) -> None:
        input_path = root / "analysis_inputs" / HISTORICAL_AS_OF / "analysis_input.json"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text(
            json.dumps(analysis_input or self._historical_analysis_input(), ensure_ascii=False),
            encoding="utf-8",
        )
        with (root / "prices.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("as_of", "ts_code", "trade_date", "high", "low", "close"))
            writer.writeheader()
            writer.writerows(rows if rows is not None else self._price_rows())

    def _read_historical_report(self, path: Path) -> dict:
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(list(Draft7Validator(load_json(HISTORICAL_REPORT_SCHEMA_PATH)).iter_errors(report)), [])
        return report

    def _clear_rule6(self, candidate: dict) -> None:
        from engine.a_short_rule6_contract import RULE6_D_TIER_REASONS

        for check in candidate["event_risk"]["rule6_checks"]:
            check_id = check["id"]
            if check_id in RULE6_D_TIER_REASONS:
                check["status"] = "not_applicable"
                check["notes"] = RULE6_D_TIER_REASONS[check_id]
            else:
                check["status"] = "pass"

    def _write_minimum_15b_sequence(self, root: Path, *, weeks: int = 12,
                                    candidates_per_week: int = 10,
                                    legacy_healthy_iv: bool = False) -> None:
        all_rows = []
        first_as_of = date(2026, 1, 23)
        template = self._historical_analysis_input()
        if legacy_healthy_iv:
            self._legacy_healthy_iv_projection(template)
        for week_index in range(weeks):
            as_of_date = first_as_of + timedelta(days=7 * week_index)
            as_of = as_of_date.strftime("%Y%m%d")
            payload = copy.deepcopy(template)
            payload["trade_date"] = as_of
            payload["market_context"]["volatility"]["iv_percentile_252d"] = 50.0
            payload["candidates"] = []
            for candidate_index in range(candidates_per_week):
                candidate = copy.deepcopy(template["candidates"][0])
                candidate["ts_code"] = f"{week_index * candidates_per_week + candidate_index + 1:06d}.SZ"
                candidate["derived_flags"]["is_breakout"] = False
                candidate["derived_flags"]["hard_veto"] = False
                self._clear_rule6(candidate)
                payload["candidates"].append(candidate)
                for offset in range(20):
                    all_rows.append({
                        "as_of": as_of,
                        "ts_code": candidate["ts_code"],
                        "trade_date": (as_of_date - timedelta(days=19 - offset)).strftime("%Y%m%d"),
                        "high": "10.0",
                        "low": "9.95",
                        "close": "10.0",
                    })
            input_path = root / "analysis_inputs" / as_of / "analysis_input.json"
            input_path.parent.mkdir(parents=True, exist_ok=True)
            input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with (root / "prices.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=("as_of", "ts_code", "trade_date", "high", "low", "close"))
            writer.writeheader()
            writer.writerows(all_rows)

    def _require_frozen_sources(self) -> None:
        from runners.a_short_entry_funnel_calibration import verified_sources
        try:
            verified_sources(load_json(PREREG_PATH))
        except ValueError as exc:
            self.skipTest(f"frozen evidence replay unavailable in this checkout: {exc}")

    def test_frozen_future_boundary_never_relaxes_thresholds_or_becomes_advice(self) -> None:
        prereg = load_json(PREREG_PATH)
        self.assertEqual(prereg["decision_gates"]["future_confirmatory_min_weeks"], 12)
        self.assertEqual(prereg["overlay_policy"]["future_confirmatory_min_observations"], 12)
        self.assertFalse(prereg["scope"]["production_threshold_change"])
        self.assertFalse(prereg["overlay_policy"]["top_k_search_allowed"])
        report = load_json(Path(__file__).resolve().parents[1] / "research" / "results" / "a_short" /
                           "entry_funnel_calibration_20260713" / "calibration_report.json")
        self.assertEqual(
            list(Draft7Validator(load_json(REPORT_SCHEMA_PATH)).iter_errors(report)), []
        )
        self.assertEqual(report["boundary"]["lane_role"], "risk_filter_only")
        self.assertFalse(report["boundary"]["is_buy_advice"])

    def test_frozen_preregistration_and_real_seen_report_validate(self) -> None:
        self._require_frozen_sources()
        prereg = load_json(PREREG_PATH)
        self.assertEqual(
            list(Draft7Validator(load_json(PREREG_SCHEMA_PATH)).iter_errors(prereg)), []
        )
        report = build_report(prereg, "2026-07-13T18:30:00+08:00")
        self.assertEqual(
            list(Draft7Validator(load_json(REPORT_SCHEMA_PATH)).iter_errors(report)), []
        )
        self.assertEqual(report["funnel"]["candidate_count"], 38)
        self.assertEqual(report["funnel"]["hard_veto_count"], 8)
        self.assertEqual(report["funnel"]["ma_shape_failure_count"], 8)
        self.assertEqual(report["funnel"]["entry_trigger_failure_count"], 22)
        self.assertEqual(report["funnel"]["rr_plan_count"], 0)
        self.assertEqual(
            report["calibration_conclusion"]["status"],
            "insufficient_sample_with_entry_trigger_bottleneck",
        )

    def test_iv_boundary_and_overlay_seen_future_split_are_frozen(self) -> None:
        self._require_frozen_sources()
        report = build_report(load_json(PREREG_PATH), "2026-07-13T18:30:00+08:00")
        self.assertEqual(report["iv_boundary"]["observation_count"], 7)
        self.assertEqual(report["iv_boundary"]["above_80_count"], 4)
        self.assertEqual(report["iv_boundary"]["above_90_count"], 2)
        self.assertEqual(report["overlay_evidence"]["seen_observations"], 4)
        self.assertEqual(report["overlay_evidence"]["future_confirmatory_observations"], 0)
        self.assertFalse(report["overlay_evidence"]["promotion_evaluable"])

    def test_cli_writes_only_calibration_not_threshold_change(self) -> None:
        self._require_frozen_sources()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "calibration_report.json"
            self.assertEqual(main(["--out", str(out)]), 0)
            report = json.loads(out.read_text(encoding="utf-8"))
        self.assertFalse(report["calibration_conclusion"]["production_threshold_change"])
        self.assertFalse(report["boundary"]["full_size_allowed"])

    def test_historical_mode_writes_active_schema_from_valid_local_pit_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "historical"
            out = Path(tmpdir) / "active_report.json"
            self._write_historical_root(root)
            with patch.object(calibration, "HISTORICAL_DEFAULT_OUT", out):
                self.assertEqual(
                    calibration.main(["--historical-root", str(root), "--generated-at", HISTORICAL_GENERATED_AT]),
                    0,
                )
            report = self._read_historical_report(out)
        self.assertEqual(report["source_readiness"]["status"], "ready")
        self.assertEqual(report["source_readiness"]["input_filenames"], ["analysis_input.json", "prices.csv"])
        self.assertEqual(report["source_readiness"]["provider_calls"], 0)
        self.assertEqual(report["decision_policy"]["provider_calls"], 0)
        self.assertEqual(report["funnel"]["evaluable_candidate_count"], 1)
        self.assertEqual(report["funnel"]["not_evaluable_candidate_count"], 0)
        self.assertNotIn("sha256", json.dumps(report))
        self.assertNotIn(str(root), json.dumps(report))
        historical_source = inspect.getsource(calibration.build_historical_report)
        self.assertNotIn("a_short_tushare_client", historical_source)
        self.assertNotIn("init_tushare_pro", historical_source)

    def test_historical_mode_accepts_an_unconsumed_legacy_block(self) -> None:
        analysis_input = self._historical_analysis_input()
        analysis_input["schema_version"] = "analysis_input.v1.0"
        analysis_input["market_context"]["liquidity"] = {"legacy_only": True}
        self.assertNotEqual(list(Draft7Validator(load_json(ANALYSIS_INPUT_SCHEMA_PATH)).iter_errors(analysis_input)), [])
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "historical"
            out = Path(tmpdir) / "active_report.json"
            self._write_historical_root(root, analysis_input=analysis_input)
            frozen_input = (root / "analysis_inputs" / HISTORICAL_AS_OF / "analysis_input.json").read_bytes()
            self.assertEqual(main([
                "--historical-root", str(root), "--out", str(out),
                "--generated-at", HISTORICAL_GENERATED_AT,
            ]), 0)
            report = self._read_historical_report(out)
            self.assertEqual(
                (root / "analysis_inputs" / HISTORICAL_AS_OF / "analysis_input.json").read_bytes(),
                frozen_input,
            )
        self.assertEqual(report["source_readiness"]["analysis_input_schema_versions"], ["analysis_input.v1.0"])
        self.assertEqual(report["funnel"]["evaluable_candidate_count"], 1)

    def test_historical_mode_accepts_missing_legacy_schema_name(self) -> None:
        analysis_input = self._historical_analysis_input()
        analysis_input.pop("schema_name")
        analysis_input.pop("schema_version")
        self.assertNotEqual(list(Draft7Validator(load_json(ANALYSIS_INPUT_SCHEMA_PATH)).iter_errors(analysis_input)), [])
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "historical"
            out = Path(tmpdir) / "active_report.json"
            self._write_historical_root(root, analysis_input=analysis_input)
            self.assertEqual(main([
                "--historical-root", str(root), "--out", str(out),
                "--generated-at", HISTORICAL_GENERATED_AT,
            ]), 0)
            report = self._read_historical_report(out)
        self.assertEqual(report["funnel"]["evaluable_candidate_count"], 1)
        self.assertEqual(report["source_readiness"]["analysis_input_schema_versions"], [])

    def test_missing_historical_source_writes_a_schema_valid_source_missing_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "active_report.json"
            self.assertEqual(
                main([
                    "--historical-root", str(Path(tmpdir) / "missing"), "--out", str(out),
                    "--generated-at", HISTORICAL_GENERATED_AT,
                ]),
                2,
            )
            report = self._read_historical_report(out)
        self.assertEqual(report["source_readiness"]["status"], "source_missing")
        self.assertEqual(report["entry_diagnostic"]["status"], "source_missing")
        self.assertFalse(report["calibration_conclusion"]["sample_sufficient"])
        self.assertEqual(
            report["calibration_conclusion"]["next_evidence"],
            "provide_or_expand_authorized_historical_pit_source",
        )

    def test_historical_input_structure_defects_preserve_existing_active_report(self) -> None:
        mutations = {
            "future": lambda rows: rows[-1].update(trade_date="20260523"),
            "duplicate": lambda rows: rows.append(copy.deepcopy(rows[-1])),
            "nonfinite": lambda rows: rows[-1].update(high="NaN"),
            "as_of_mismatch": lambda rows: rows[-1].update(as_of="20260529"),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "historical"
            for label, mutate in mutations.items():
                with self.subTest(label=label):
                    rows = self._price_rows()
                    mutate(rows)
                    self._write_historical_root(root, rows=rows)
                    out = Path(tmpdir) / f"{label}_active_report.json"
                    original = b'{"keep":"existing-active-report"}\n'
                    out.write_bytes(original)
                    self.assertEqual(
                        main([
                            "--historical-root", str(root), "--out", str(out),
                            "--generated-at", HISTORICAL_GENERATED_AT,
                        ]),
                        1,
                    )
                    self.assertEqual(out.read_bytes(), original)

    def test_nonlist_candidates_preserve_existing_active_report(self) -> None:
        analysis_input = self._historical_analysis_input()
        analysis_input["candidates"] = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "historical"
            out = Path(tmpdir) / "active_report.json"
            self._write_historical_root(root, analysis_input=analysis_input)
            original = b'{"keep":"existing-active-report"}\n'
            out.write_bytes(original)
            self.assertEqual(main([
                "--historical-root", str(root), "--out", str(out),
                "--generated-at", HISTORICAL_GENERATED_AT,
            ]), 1)
            self.assertEqual(out.read_bytes(), original)

    def test_missing_candidate_facts_are_counted_not_guessed(self) -> None:
        analysis_input = self._historical_analysis_input()
        candidate = analysis_input["candidates"][0]
        del candidate["event_risk"]["rule6_checks"]
        candidate["derived_flags"]["is_breakout"] = None
        self.assertNotEqual(list(Draft7Validator(load_json(ANALYSIS_INPUT_SCHEMA_PATH)).iter_errors(analysis_input)), [])
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "historical"
            out = Path(tmpdir) / "active_report.json"
            self._write_historical_root(root, analysis_input=analysis_input, rows=self._price_rows(19))
            self.assertEqual(
                main([
                    "--historical-root", str(root), "--out", str(out),
                    "--generated-at", HISTORICAL_GENERATED_AT,
                ]),
                0,
            )
            report = self._read_historical_report(out)
        self.assertEqual(report["source_readiness"]["status"], "ready_with_candidate_gaps")
        self.assertEqual(report["funnel"]["evaluable_candidate_count"], 0)
        self.assertEqual(report["funnel"]["not_evaluable_candidate_count"], 1)
        self.assertEqual(
            report["funnel"]["not_evaluable_reason_counts"],
            {
                "missing_rule6_hard_veto": 1,
                "missing_egs_breakout": 1,
                "missing_m05_rule3": 0,
                "iv_feed_not_ready": 0,
                "insufficient_pit_price_window": 1,
            },
        )

    def test_nonready_iv_week_is_visible_and_excluded_from_the_diagnostic_denominator(self) -> None:
        analysis_input = self._historical_analysis_input()
        candidate = analysis_input["candidates"][0]
        self._clear_rule6(candidate)
        candidate["derived_flags"]["hard_veto"] = False
        self._nonready_iv_projection(analysis_input)
        self.assertEqual(list(Draft7Validator(load_json(ANALYSIS_INPUT_SCHEMA_PATH)).iter_errors(analysis_input)), [])
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "historical"
            out = Path(tmpdir) / "active_report.json"
            self._write_historical_root(root, analysis_input=analysis_input)
            self.assertEqual(
                main([
                    "--historical-root", str(root), "--out", str(out),
                    "--generated-at", HISTORICAL_GENERATED_AT,
                ]),
                0,
            )
            report = self._read_historical_report(out)
        self.assertEqual(report["source_readiness"]["status"], "ready_with_candidate_gaps")
        self.assertEqual(report["funnel"]["not_evaluable_reason_counts"]["iv_feed_not_ready"], 1)
        self.assertEqual(report["funnel"]["not_evaluable_reason_counts"]["missing_m05_rule3"], 0)
        self.assertEqual(report["funnel"]["evaluable_candidate_count"], 0)
        self.assertEqual(report["funnel"]["diagnostic_candidate_count"], 0)
        self.assertEqual(report["funnel"]["diagnostic_week_count"], 0)
        self.assertEqual(report["entry_diagnostic"]["metrics"]["decision"]["pre_capital_build_rate"], None)

    def test_ready_iv_week_remains_in_the_diagnostic_denominator(self) -> None:
        analysis_input = self._historical_analysis_input()
        candidate = analysis_input["candidates"][0]
        self._clear_rule6(candidate)
        candidate["derived_flags"]["hard_veto"] = False
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "historical"
            self._write_historical_root(root, analysis_input=analysis_input)
            report, exit_code = build_historical_report(root, HISTORICAL_GENERATED_AT)
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["funnel"]["not_evaluable_reason_counts"]["iv_feed_not_ready"], 0)
        self.assertEqual(report["funnel"]["diagnostic_candidate_count"], 1)
        self.assertEqual(report["funnel"]["diagnostic_week_count"], 1)

    def test_legacy_healthy_iv_week_remains_in_the_diagnostic_denominator(self) -> None:
        analysis_input = self._historical_analysis_input()
        self._legacy_healthy_iv_projection(analysis_input)
        candidate = analysis_input["candidates"][0]
        self._clear_rule6(candidate)
        candidate["derived_flags"]["hard_veto"] = False
        self.assertEqual(list(Draft7Validator(load_json(ANALYSIS_INPUT_SCHEMA_PATH)).iter_errors(analysis_input)), [])
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "historical"
            self._write_historical_root(root, analysis_input=analysis_input)
            report, exit_code = build_historical_report(root, HISTORICAL_GENERATED_AT)
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["funnel"]["not_evaluable_reason_counts"]["iv_feed_not_ready"], 0)
        self.assertEqual(report["funnel"]["diagnostic_candidate_count"], 1)
        self.assertEqual(report["funnel"]["diagnostic_week_count"], 1)

    def test_legacy_unknown_iv_week_is_excluded_as_missing_m05(self) -> None:
        analysis_input = self._historical_analysis_input()
        self._legacy_healthy_iv_projection(analysis_input)
        analysis_input["market_context"]["volatility"].update({
            "iv_percentile_252d": None,
            "rule3_status": "unknown",
            "awakening_status": "unknown",
        })
        candidate = analysis_input["candidates"][0]
        self._clear_rule6(candidate)
        candidate["derived_flags"]["hard_veto"] = False
        self.assertEqual(list(Draft7Validator(load_json(ANALYSIS_INPUT_SCHEMA_PATH)).iter_errors(analysis_input)), [])
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "historical"
            self._write_historical_root(root, analysis_input=analysis_input)
            report, exit_code = build_historical_report(root, HISTORICAL_GENERATED_AT)
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["funnel"]["not_evaluable_reason_counts"]["iv_feed_not_ready"], 0)
        self.assertEqual(report["funnel"]["not_evaluable_reason_counts"]["missing_m05_rule3"], 1)
        self.assertEqual(report["funnel"]["diagnostic_candidate_count"], 0)

    def test_15b_legacy_healthy_iv_sequence_can_satisfy_the_minimum_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "historical"
            self._write_minimum_15b_sequence(root, legacy_healthy_iv=True)
            report, exit_code = build_historical_report(root, HISTORICAL_GENERATED_AT)
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["funnel"]["diagnostic_week_count"], 12)
        self.assertEqual(report["funnel"]["diagnostic_candidate_count"], 120)

    def test_missing_consumed_m05_leaf_is_counted_not_rejected(self) -> None:
        analysis_input = self._historical_analysis_input()
        del analysis_input["market_context"]["volatility"]["rule3_status"]
        self.assertNotEqual(list(Draft7Validator(load_json(ANALYSIS_INPUT_SCHEMA_PATH)).iter_errors(analysis_input)), [])
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "historical"
            out = Path(tmpdir) / "active_report.json"
            self._write_historical_root(root, analysis_input=analysis_input)
            self.assertEqual(
                main([
                    "--historical-root", str(root), "--out", str(out),
                    "--generated-at", HISTORICAL_GENERATED_AT,
                ]),
                0,
            )
            report = self._read_historical_report(out)
        self.assertEqual(report["source_readiness"]["status"], "ready_with_candidate_gaps")
        self.assertEqual(report["funnel"]["evaluable_candidate_count"], 0)
        self.assertEqual(report["funnel"]["not_evaluable_reason_counts"]["missing_m05_rule3"], 1)

    def test_historical_mode_rejects_a_legacy_mode_mix_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "historical"
            out = Path(tmpdir) / "active_report.json"
            self._write_historical_root(root)
            self.assertEqual(
                main([
                    "--historical-root", str(root), "--preregistration", str(PREREG_PATH), "--out", str(out),
                ]),
                1,
            )
            self.assertFalse(out.exists())

    def test_legacy_mode_rejects_the_active_output_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "active_report.json"
            with patch.object(calibration, "HISTORICAL_DEFAULT_OUT", out):
                self.assertEqual(calibration.main(["--out", str(out)]), 1)
            self.assertFalse(out.exists())

    def test_15b_uses_production_geometry_with_the_minimum_12week_120candidate_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "historical"
            self._write_minimum_15b_sequence(root)
            report, exit_code = build_historical_report(root, HISTORICAL_GENERATED_AT)
        self.assertEqual(exit_code, 0)
        self.assertEqual(list(Draft7Validator(load_json(HISTORICAL_REPORT_SCHEMA_PATH)).iter_errors(report)), [])
        self.assertEqual(report["funnel"]["diagnostic_week_count"], 12)
        self.assertEqual(report["funnel"]["diagnostic_candidate_count"], 120)
        self.assertEqual(report["entry_diagnostic"]["capital_gate"], "not_evaluable_private_account")
        self.assertEqual(report["entry_diagnostic"]["pre_capital_plan_count"], 120)
        self.assertEqual(report["calibration_conclusion"]["status"], "too_lax")
        methods = report["entry_diagnostic"]["support_methods"]
        self.assertEqual(methods["effective_support"]["recent_low_20"]["count"], 120)
        self.assertTrue(all(len(methods[name]["band_observations"]) == 4 for name in methods))
        counterfactuals = report["entry_diagnostic"]["counterfactuals"]
        self.assertEqual(len(counterfactuals), 7)  # 2 support + 4 band + egs-only, never a 4x3 replay grid.

    def test_15b_adjudication_covers_all_five_dynamic_final_statuses(self) -> None:
        decision = lambda build, active: {"pre_capital_build_rate": build, "active_week_rate": active}
        cases = {
            "insufficient_sample": {
                "weeks": 11, "candidates": 120, "metrics": decision(0.10, 0.50), "counterfactuals": {},
                "next": "provide_or_expand_authorized_historical_pit_source",
            },
            "within_calibration_band": {
                "weeks": 12, "candidates": 120, "metrics": decision(0.10, 0.50), "counterfactuals": {},
                "next": "retain_production_baseline_and_seek_forward_confirmation",
            },
            "too_lax": {
                "weeks": 12, "candidates": 120, "metrics": decision(0.21, 0.50), "counterfactuals": {},
                "next": "open_reviewed_tightening_candidate",
            },
            "egs_entry_mismatch": {
                "weeks": 12, "candidates": 120, "metrics": decision(0.01, 0.10),
                "counterfactuals": {"egs_only_as_breakout": {"decision": decision(0.10, 0.50)}},
                "next": "manual_review_selection_entry_alignment_no_production_change",
            },
            "specific_gate_too_strict": {
                "weeks": 12, "candidates": 120, "metrics": decision(0.01, 0.10),
                "counterfactuals": {
                    "egs_only_as_breakout": {"decision": decision(0.01, 0.10)},
                    "support:ma20": {"decision": decision(0.10, 0.50)},
                },
                "next": "open_reviewed_rule_change_candidate",
            },
        }
        for expected_status, case in cases.items():
            with self.subTest(status=expected_status):
                conclusion = _adjudicate_calibration(
                    source_status="ready",
                    diagnostic_week_count=case["weeks"],
                    diagnostic_candidate_count=case["candidates"],
                    metrics=case["metrics"],
                    counterfactuals=case["counterfactuals"],
                )
                self.assertEqual(conclusion["status"], expected_status)
                self.assertEqual(conclusion["next_evidence"], case["next"])
                self.assertFalse(conclusion["production_threshold_change"])
        self.assertEqual(conclusion["candidate_gates"], [
            {"gate": "support:ma20", "metrics": decision(0.10, 0.50)},
        ])


if __name__ == "__main__":
    unittest.main()
