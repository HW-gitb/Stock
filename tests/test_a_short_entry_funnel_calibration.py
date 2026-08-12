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
    ANALYSIS_INPUT_SCHEMA_PATH,
    HISTORICAL_REPORT_SCHEMA_PATH,
    PREREG_PATH,
    PREREG_SCHEMA_PATH,
    REPORT_SCHEMA_PATH,
    build_report,
    load_json,
    main,
)


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_INPUT_EXAMPLE = ROOT / "schemas" / "examples" / "analysis_input.example.json"
HISTORICAL_AS_OF = "20260522"
HISTORICAL_GENERATED_AT = "2026-08-12T00:00:00+00:00"


class AShortEntryFunnelCalibrationTests(unittest.TestCase):
    def _historical_analysis_input(self) -> dict:
        payload = json.loads(ANALYSIS_INPUT_EXAMPLE.read_text(encoding="utf-8"))
        payload["trade_date"] = HISTORICAL_AS_OF
        return payload

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
        self.assertEqual(report["entry_diagnostic"]["status"], "not_run_source_missing")
        self.assertFalse(report["calibration_conclusion"]["sample_sufficient"])
        self.assertEqual(
            report["calibration_conclusion"]["next_evidence"],
            "provide_authorized_historical_pit_source",
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

    def test_missing_candidate_facts_are_counted_not_guessed(self) -> None:
        analysis_input = self._historical_analysis_input()
        candidate = analysis_input["candidates"][0]
        candidate["event_risk"]["rule6_checks"] = []
        candidate["derived_flags"]["is_breakout"] = None
        self.assertEqual(list(Draft7Validator(load_json(ANALYSIS_INPUT_SCHEMA_PATH)).iter_errors(analysis_input)), [])
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
                "insufficient_pit_price_window": 1,
            },
        )

    def test_invalid_m05_rule3_input_preserves_existing_active_report(self) -> None:
        analysis_input = self._historical_analysis_input()
        del analysis_input["market_context"]["volatility"]["rule3_status"]
        self.assertNotEqual(list(Draft7Validator(load_json(ANALYSIS_INPUT_SCHEMA_PATH)).iter_errors(analysis_input)), [])
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "historical"
            out = Path(tmpdir) / "active_report.json"
            self._write_historical_root(root, analysis_input=analysis_input)
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


if __name__ == "__main__":
    unittest.main()
