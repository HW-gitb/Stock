from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft7Validator

from engine.us_short_market_diagnostic_local_adapter import (
    LocalMarketDiagnosticAdapterError,
    adapt_benchmark_week,
    build_weekly_record_from_local,
    load_model_paper_week,
    validate_local_price_packet,
)
from engine.us_short_model_paper_portfolio import canonical_json_bytes
from runners.us_short_model_paper_weekly_capstone import run_offline_model_paper_capstone
from tests.test_us_short_model_paper_weekly import _order, _plan, _point, _raw_for
from tests.test_us_short_market_diagnostic_total_return import _sidecar


ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = ("VTI", "IWB", "SPY", "QQQ")


def _packet() -> dict:
    def observation(symbol: str) -> dict:
        source_kind = "grouped_market_window" if symbol in {"SPY", "QQQ"} else "local_etf_price_packet"
        source_seed = 10 + BENCHMARKS.index(symbol)
        return {
            "price_date": "20260724",
            "prior_price_date": "20260723",
            "prior_close": "100.000000",
            "close": "101.000000",
            "source_kind": source_kind,
            "source_sha256": f"{source_seed:064x}",
            "dividend_sidecar_sha256": None,
        }

    return {
        "schema_name": "us_short_market_diagnostic_local_price_packet",
        "schema_version": "1.1.0",
        "window_id": "26w-1-26",
        "diagnostic_epoch": "us_short_market_diagnostic_26w_v1",
        "price_basis": "split_adjusted_close",
        "benchmark_symbols": list(BENCHMARKS),
        "weeks": [
            {
                "calendar_week_index": 1,
                "decision_date": "20260727",
                "settlement_decision_date": "20260720",
                "valuation_date": "20260724",
                "benchmarks": {symbol: observation(symbol) for symbol in BENCHMARKS},
            }
        ],
        "source_refs": [f"{50:064x}"],
        "boundary": {
            "local_only": True,
            "provider_calls_performed": False,
            "account_write_performed": False,
            "broker_or_order_automation": False,
        },
    }


def _start_local_paper_store(root: Path) -> None:
    run_offline_model_paper_capstone(
        run_account_mode="paper_only",
        store_root=str(root),
        decision_date="20260720",
        price_basis_date="20260717",
        created_at="2026-07-20T08:00:00Z",
        arrived_ohlcv_packet=_raw_for("20260720", "20260717", []),
        paper_plan_factory=_plan(_order("建仓", shares=100)),
    )
    run_offline_model_paper_capstone(
        run_account_mode="paper_only",
        store_root=str(root),
        decision_date="20260727",
        price_basis_date="20260724",
        created_at="2026-07-27T08:00:00Z",
        arrived_ohlcv_packet=_raw_for(
            "20260727",
            "20260724",
            [_point("20260720", 10.0, 10.2, 9.9, 10.0), _point("20260724", 10.0, 10.2, 9.9, 10.1)],
        ),
        paper_plan_factory=_plan(_order("持有", shares=None)),
    )


class UsShortMarketDiagnosticLocalAdapterTest(unittest.TestCase):
    def test_local_price_packet_accepts_grouped_spy_qqq_and_local_iwb_vti(self) -> None:
        packet = validate_local_price_packet(_packet())
        self.assertEqual("grouped_market_window", packet["weeks"][0]["benchmarks"]["SPY"]["source_kind"])
        self.assertEqual("grouped_market_window", packet["weeks"][0]["benchmarks"]["QQQ"]["source_kind"])
        self.assertEqual("local_etf_price_packet", packet["weeks"][0]["benchmarks"]["IWB"]["source_kind"])
        self.assertEqual("local_etf_price_packet", packet["weeks"][0]["benchmarks"]["VTI"]["source_kind"])

    def test_missing_prior_price_is_unavailable_and_never_zero_filled(self) -> None:
        packet = _packet()
        packet["weeks"][0]["benchmarks"]["VTI"]["prior_close"] = None
        packet["weeks"][0]["benchmarks"]["VTI"]["prior_price_date"] = None
        benchmark = adapt_benchmark_week(
            packet,
            1,
            strategy_evaluable=True,
            strategy_weekly_return=0.01,
            windows_aligned=True,
        )["VTI"]
        self.assertEqual("unavailable", benchmark["return_quality"])
        self.assertFalse(benchmark["benchmark_evaluable"])
        self.assertFalse(benchmark["joint_evaluable"])
        self.assertIsNone(benchmark["weekly_return"])
        self.assertIn("prior_price_missing", benchmark["data_quality_reasons"])

    def test_local_model_paper_week_is_digest_bound_and_output_is_schema_shaped(self) -> None:
        packet = _packet()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "model_paper_private"
            _start_local_paper_store(root)
            before = {
                path: path.read_bytes()
                for path in root.rglob("*.json")
            }
            record = build_weekly_record_from_local(
                model_paper_root=root,
                benchmark_packet=packet,
                calendar_week_index=1,
                diagnostic_policy_sha256="b" * 64,
                strategy_ruleset_fingerprint="c" * 64,
                v1_1_reminder={
                    "status": "pending",
                    "evaluable_week_count": 0,
                    "text": "v1.1 remains a later attribution explanation step.",
                },
                prior_nav=None,
                prior_week_was_no_count=False,
            )
            after = {path: path.read_bytes() for path in root.rglob("*.json")}

        errors = list(
            Draft7Validator(
                json.loads(
                    (ROOT / "schemas" / "us_short_market_diagnostic_weekly_record.schema.json").read_text(
                        encoding="utf-8"
                    )
                )
            ).iter_errors(record)
        )
        self.assertEqual([], errors)
        self.assertEqual(before, after)
        self.assertEqual("20260727", record["decision_date"])
        self.assertEqual("20260724", record["valuation_date"])
        self.assertFalse(record["strategy"]["paper_evaluable"])
        self.assertFalse(record["benchmarks"]["VTI"]["joint_evaluable"])
        self.assertEqual("price_return_diagnostic", record["benchmarks"]["VTI"]["return_quality"])
        self.assertEqual("20260724", record["benchmarks"]["VTI"]["price_date"])
        self.assertEqual("local_etf_price_packet", record["benchmarks"]["VTI"]["price_source"])
        self.assertIsNone(record["benchmarks"]["VTI"]["dividend_sidecar_sha256"])
        self.assertGreater(record["strategy"]["weekly_return"], 0)
        self.assertGreaterEqual(len(record["source_refs"]), 5)

    def test_complete_sidecar_upgrades_each_benchmark_without_writing_model_paper(self) -> None:
        packet = _packet()
        sidecar = _sidecar()
        direct = adapt_benchmark_week(
            packet,
            1,
            strategy_evaluable=True,
            strategy_weekly_return=0.03,
            total_return_sidecar=sidecar,
            windows_aligned=True,
        )
        self.assertEqual(set(BENCHMARKS), set(direct))
        for benchmark in direct.values():
            self.assertEqual("total_return_evaluable", benchmark["return_quality"])
            self.assertAlmostEqual(0.02, benchmark["weekly_return"])
            self.assertIsNotNone(benchmark["dividend_sidecar_sha256"])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "model_paper_private"
            _start_local_paper_store(root)
            before = {path: path.read_bytes() for path in root.rglob("*.json")}
            record = build_weekly_record_from_local(
                model_paper_root=root,
                benchmark_packet=packet,
                calendar_week_index=1,
                diagnostic_policy_sha256="b" * 64,
                strategy_ruleset_fingerprint="c" * 64,
                v1_1_reminder={
                    "status": "pending",
                    "evaluable_week_count": 0,
                    "text": "v1.1 remains a later attribution explanation step.",
                },
                prior_nav=None,
                total_return_sidecar=sidecar,
                prior_week_was_no_count=False,
            )
            after = {path: path.read_bytes() for path in root.rglob("*.json")}

        errors = list(
            Draft7Validator(
                json.loads(
                    (ROOT / "schemas" / "us_short_market_diagnostic_weekly_record.schema.json").read_text(
                        encoding="utf-8"
                    )
                )
            ).iter_errors(record)
        )
        self.assertEqual([], errors)
        self.assertEqual(before, after)
        for symbol in BENCHMARKS:
            self.assertEqual("total_return_evaluable", record["benchmarks"][symbol]["return_quality"])
            self.assertAlmostEqual(0.02, record["benchmarks"][symbol]["weekly_return"])
            self.assertIn(record["benchmarks"][symbol]["dividend_sidecar_sha256"], record["source_refs"])

    def test_sidecar_window_mismatch_is_rejected_before_projection(self) -> None:
        packet = _packet()
        sidecar = _sidecar()
        sidecar["window_id"] = "26w-27-52"
        with self.assertRaises(LocalMarketDiagnosticAdapterError):
            adapt_benchmark_week(
                packet,
                1,
                strategy_evaluable=True,
                strategy_weekly_return=0.03,
                total_return_sidecar=sidecar,
                windows_aligned=True,
            )

    def test_sidecar_price_interval_must_bind_to_local_price_packet(self) -> None:
        sidecar = _sidecar(prior_price_date="20260722")
        with self.assertRaises(LocalMarketDiagnosticAdapterError):
            adapt_benchmark_week(
                _packet(),
                1,
                strategy_evaluable=True,
                strategy_weekly_return=0.03,
                total_return_sidecar=sidecar,
                windows_aligned=True,
            )

    def test_model_paper_week_tamper_is_rejected_before_projection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "model_paper_private"
            _start_local_paper_store(root)
            nav_path = root / "weeks" / "20260720" / "nav_snapshot.json"
            nav = json.loads(nav_path.read_text(encoding="utf-8"))
            nav["cash"] = "99999.000000"
            nav_path.write_bytes(canonical_json_bytes(nav))
            with self.assertRaises(LocalMarketDiagnosticAdapterError):
                load_model_paper_week(root, "20260720")

    def test_price_date_clock_and_future_data_fail_closed(self) -> None:
        bad_date = _packet()
        bad_date["weeks"][0]["benchmarks"]["VTI"]["price_date"] = "20260716"
        with self.assertRaises(LocalMarketDiagnosticAdapterError):
            validate_local_price_packet(bad_date)

        future = _packet()
        future["weeks"][0]["decision_date"] = "20260720"
        future["weeks"][0]["valuation_date"] = "20260721"
        for benchmark in future["weeks"][0]["benchmarks"].values():
            benchmark["price_date"] = "20260721"
        with self.assertRaises(LocalMarketDiagnosticAdapterError):
            validate_local_price_packet(future)

        with self.assertRaises(LocalMarketDiagnosticAdapterError):
            validate_local_price_packet(_packet(), as_of_date="20260723")

        missing_source = _packet()
        missing_source["weeks"][0]["benchmarks"]["VTI"]["source_sha256"] = None
        with self.assertRaises(LocalMarketDiagnosticAdapterError):
            validate_local_price_packet(missing_source)

    def test_adapter_module_is_local_read_only_and_has_no_provider_import(self) -> None:
        source = (ROOT / "engine" / "us_short_market_diagnostic_local_adapter.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module.split(".")[0])
        self.assertNotIn("requests", imports)
        self.assertNotIn("urllib", imports)
        self.assertNotIn("provider", imports)
        self.assertNotIn("write_text", source)
        self.assertNotIn("write_bytes", source)
        self.assertNotIn("open(", source)
        self.assertNotIn("subprocess", imports)


if __name__ == "__main__":
    unittest.main()
