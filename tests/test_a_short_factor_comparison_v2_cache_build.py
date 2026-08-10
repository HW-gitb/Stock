"""P0 proofs for the bounded, provenance-preserving v2 cache builder."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import a_short_factor_comparison as v1  # noqa: E402
from engine.a_short_factor_comparison_v2 import ComparisonV2Error, capture_v2_week  # noqa: E402
from engine.a_short_managed_exit import evaluate_managed_exit  # noqa: E402
from runners.a_short_final_action_validation_runner import (  # noqa: E402
    _active_epoch as active_p3_epoch,
    _capture_digest as p3_capture_digest,
    _initial_ledger as new_p3_ledger,
    _load_execution_cache as load_p3_cache,
)
from runners.a_short_factor_comparison_v2_cache_build import (  # noqa: E402
    _cache_build_outcome_payload,
    main as cache_build_main,
    materialize_incremental_cache,
)
from runners.a_short_official_operation_evidence import _boundary, _digest  # noqa: E402
from runners.a_short_target_policy_comparison_runner import (  # noqa: E402
    TRACK_ADMISSIONS,
    _active_epoch as active_p2_epoch,
    _capture_digest as p2_capture_digest,
    _load_execution_cache as load_p2_cache,
    _new_ledger as new_p2_ledger,
)
from engine.a_short_experiment_admission_registry import admission_snapshot  # noqa: E402


DECISION_DATE = "20260202"
RUN_DATE = "20260227"


def _root(tmp: str) -> Path:
    return Path(tmp) / "state" / "a_short" / "factor_comparison_private" / "v2"


def _official_operation_root(tmp: str) -> Path:
    return Path(tmp) / "state" / "a_short" / "operation_evidence_private" / "v1"


def _write_official_operation_capture(root: Path) -> None:
    source = {
        "as_of": DECISION_DATE, "price_data_through": DECISION_DATE,
        "run_id": "official-operation-cache-test", "candidate_digest": "a" * 64,
        "official_m67_sha256": "b" * 64, "official_receipt_sha256": "c" * 64,
        "account_snapshot_digest": None, "weekly_schema_version": "1.0.0",
        "m67_schema_versions": ["1.0.0"],
        "runtime_configuration": {"schema_name": "test", "schema_version": "1",
                                  "configuration_fingerprint": "d", "policies": []},
        "rule_parameter_versions": {}, "effect_contract_ledger_sha256": "d" * 64,
    }
    decision = {
        "decision_id": "e" * 64, "symbol": "600300.SH", "scope": "new_candidate",
        "final_action": "建仓", "holding_disposition": None, "display": {}, "constraints": {},
        "prices": {"managed_exit_plan": {
            "decision_date": DECISION_DATE, "entry_low": 10.0, "entry_high": 10.5,
            "stop": 9.0, "t1": 12.0, "t2": 13.0, "atr_multiplier": 1.0,
            "price_basis": "qfq", "reference_trade_date": DECISION_DATE,
            "reference_close": 10.5, "policy_version": "official_m67_v1",
        }, "managed_exit_plan_unavailable_reason": None},
        "sizing": {}, "portfolio": {}, "environment": {}, "evidence_modes": {},
    }
    capture = {
        "schema_name": "a_short_official_operation_evidence_private_capture", "schema_version": "1.1.0",
        "record_type": "decision_capture", "program_id": "a_short_official_operation_evidence",
        "as_of": DECISION_DATE, "source_identity": source, "decisions": [decision], "boundary": _boundary(),
    }
    capture["capture_sha256"] = _digest(capture)
    path = root / "weeks" / DECISION_DATE / "capture.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(capture), encoding="utf-8")


def _legacy_cache() -> dict:
    return {
        "schema_name": "a_short_factor_comparison_v2_daily_cache", "schema_version": "1.0.0",
        "stocks": [{"ts_code": "600000.SH", "trade_date": DECISION_DATE, "open": 99.0, "close": 10.5,
                    "adj_factor": 2.0, "adj_factor_observed": True,
                    "adj_factor_source": "provider_observed", "corporate_action_verified": False}],
        "limits": [],
        "meta": {"cache_kind": "a_short_factor_comparison_v2_incremental", "source": "tushare:daily+adj_factor+stk_limit"},
    }


def _trading_dates(start: date, count: int) -> list[str]:
    result = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return result


def _candidate(index: int) -> dict:
    history = _trading_dates(date(2025, 12, 23), 30)
    series = []
    for day_index, day in enumerate(history):
        close = 10.5 if day_index >= 20 else 10.2
        series.append({"trade_date": day, "high": 15.0 if day_index in (22, 27) else close + 0.2,
                       "low": 9.7 if day_index in (21, 26) else close - 0.2, "close": close})
    assert history[-1] == DECISION_DATE
    return {
        "ts_code": f"60000{index}.SH", "name": f"name-{index}", "close": 10.5,
        "price_series": series,
        "egs_score": 100.0 - index, "derived": {}, "event": {},
        "liquidity": {"avg_amount_5d": 1e9},
        "iv": {"iv_percentile_252d": 50.0, "iv_value": 0.20, "hv_value": 0.18},
        "market_regime": "attack", "regime_fallback": {}, "stateful_risk": {},
    }


def _capture(root: Path) -> dict:
    candidates = [_candidate(index) for index in range(5)]
    identity = {
        "run_id": "p0-cache-test", "run_date": DECISION_DATE, "source_as_of": DECISION_DATE,
        "price_data_through": DECISION_DATE,
        "candidate_digest": v1._digest([v1._safe_candidate(row) for row in candidates]),
        "official_m67_digest": "a" * 64,
    }
    return capture_v2_week(root=root, decision_date=DECISION_DATE, candidates=candidates,
                           run_identity=identity, forward_eligible=False)


class FakeTushare:
    def __init__(self, *, missing_adj: bool = False, adjustment_jump: bool = False):
        self.missing_adj = missing_adj
        self.adjustment_jump = adjustment_jump
        self.calls: list[tuple[str, dict]] = []

    @staticmethod
    def _days(start: str, end: str) -> list[str]:
        current = datetime_from(start)
        finish = datetime_from(end)
        result = []
        while current <= finish:
            if current.weekday() < 5:
                result.append(current.strftime("%Y%m%d"))
            current += timedelta(days=1)
        return result

    def trade_cal(self, **kwargs):
        self.calls.append(("trade_cal", kwargs))
        return pd.DataFrame({"cal_date": self._days(kwargs["start_date"], kwargs["end_date"])})

    def daily(self, **kwargs):
        self.calls.append(("daily", kwargs))
        return pd.DataFrame([{ "ts_code": kwargs["ts_code"], "trade_date": day, "open": 10.0,
                               "high": 10.8, "low": 9.8, "close": 10.5, "vol": 1000.0 }
                             for day in self._days(kwargs["start_date"], kwargs["end_date"])])

    def adj_factor(self, **kwargs):
        self.calls.append(("adj_factor", kwargs))
        dates = self._days(kwargs["start_date"], kwargs["end_date"])
        if self.missing_adj:
            dates = dates[1:]
        midpoint = len(dates) // 2
        return pd.DataFrame([{ "ts_code": kwargs["ts_code"], "trade_date": day,
                               "adj_factor": 3.0 if self.adjustment_jump and index >= midpoint else 2.0 }
                             for index, day in enumerate(dates)])

    def stk_limit(self, **kwargs):
        self.calls.append(("stk_limit", kwargs))
        return pd.DataFrame([{ "ts_code": kwargs["ts_code"], "trade_date": day,
                               "up_limit": 11.0, "down_limit": 9.0 }
                             for day in self._days(kwargs["start_date"], kwargs["end_date"])])

    def index_daily(self, **kwargs):
        self.calls.append(("index_daily", kwargs))
        return pd.DataFrame([{ "ts_code": kwargs["ts_code"], "trade_date": day,
                               "open": 100.0, "close": 101.0 }
                             for day in self._days(kwargs["start_date"], kwargs["end_date"])])


def datetime_from(value: str) -> date:
    return date(int(value[:4]), int(value[4:6]), int(value[6:]))


def _write_p2_ledger(path: Path, record: dict) -> None:
    ledger = new_p2_ledger()
    decision_date = record["decision_date"]
    source = {
        "run_id": "cache-build-test", "candidate_digest": "a" * 64,
        "official_m67_sha256": "b" * 64, "price_data_through": decision_date,
        **(record.get("source_identity") or {}),
    }
    for track, entry_key, difference_key in (
            ("target_exit", "target_entries", "target_difference"),
            ("breakout_entry", "breakout_entries", "breakout_difference")):
        entries = record.get(entry_key) or []
        if not entries:
            continue
        epoch = active_p2_epoch(ledger, create=True, track=track)
        assert epoch is not None
        current = {
            "decision_date": decision_date, "forward_eligible": bool(record.get("forward_eligible")),
            "source_identity": source, "component_id": track,
            "admission_binding": admission_snapshot(TRACK_ADMISSIONS[track]),
            "component_epoch_fingerprint": epoch["contract_fingerprint"],
            entry_key: entries, difference_key: bool(record.get(difference_key, True)),
        }
        current["capture_sha256"] = p2_capture_digest(current)
        epoch["records"].append(current)
    path.write_text(json.dumps(ledger), encoding="utf-8")


def _write_p3_ledger(path: Path, record: dict) -> None:
    ledger = new_p3_ledger()
    epoch = active_p3_epoch(ledger, create=True)
    assert epoch is not None
    current = dict(record)
    current["epoch_fingerprint"] = epoch["contract_fingerprint"]
    current["admission_bindings"] = admission_snapshot(
        "p3_selected_vs_candidate_pool", "p3_selected_vs_csi1000", "p3_managed_exit_vs_hold"
    )
    current["capture_sha256"] = p3_capture_digest(current)
    epoch["records"].append(current)
    path.write_text(json.dumps(ledger), encoding="utf-8")


class ComparisonV2CacheBuildTests(unittest.TestCase):
    def test_cli_writes_contract_bound_outcome_receipt_for_no_frozen_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            receipt_path = Path(tmp) / "weekly" / "shared_cache_build.outcome.json"
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                self.assertEqual(cache_build_main([
                    "--root", str(root), "--run-date", RUN_DATE,
                    "--outcome-json", str(receipt_path),
                ]), 0)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt, {
                "schema_name": "a_short_shared_cache_build_outcome",
                "schema_version": "1.0.0",
                "run_date": RUN_DATE,
                "status": "no_frozen_v2_captures",
                "provider_calls": 0,
                "deferred_symbols_by_consumer": {},
                "production_unchanged": True,
            })
            self.assertEqual(set(receipt), {
                "schema_name", "schema_version", "run_date", "status",
                "provider_calls", "deferred_symbols_by_consumer", "production_unchanged",
            })

    def test_outcome_projection_rejects_degraded_status_without_deferred_count(self):
        with self.assertRaisesRegex(ComparisonV2Error, "positive deferred count"):
            _cache_build_outcome_payload(
                result={"status": "cache_updated_with_deferrals", "provider_calls": 1},
                run_date=RUN_DATE,
            )

    def test_outcome_projection_rejects_provider_calls_for_no_frozen_status(self):
        # Pointed negative control for the producer-side closed-world invariant:
        # a no-frozen receipt must never claim that the provider was called.
        with self.assertRaisesRegex(ComparisonV2Error, "zero provider calls"):
            _cache_build_outcome_payload(
                result={"status": "no_frozen_v2_captures", "provider_calls": 1},
                run_date=RUN_DATE,
            )

    def test_p4_is_last_and_gets_provider_observed_benchmarks_only_when_budget_remains(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp); provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE), \
                    mock.patch("runners.a_short_factor_comparison_v2_cache_build._p4_windows", return_value=[{
                        "consumer": "p4_overlay_adjudication", "decision_date": DECISION_DATE,
                        "price_data_through": DECISION_DATE, "window_mode": "managed_exit", "pre_history_days": 0,
                        "horizon_days": 20, "symbols": ["600777.SH"],
                    }]):
                result = materialize_incremental_cache(root=root, run_date=RUN_DATE, max_provider_calls=20, pro=provider,
                                                       overlay_adjudication_root=Path(tmp) / "p4")
            self.assertEqual(result["provider_calls"], 6)
            self.assertEqual([kind for kind, _ in provider.calls].count("index_daily"), 2)
            cache = json.loads((root / "daily_cache.json").read_text(encoding="utf-8"))
            self.assertEqual({row["ts_code"] for row in cache["benchmarks"]}, {"000852.SH", "000300.SH"})
    def test_no_frozen_capture_makes_no_provider_call_or_empty_success_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            root.mkdir(parents=True)
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                result = materialize_incremental_cache(root=root, run_date=RUN_DATE, pro=provider)
            self.assertEqual(result["status"], "no_frozen_v2_captures")
            self.assertEqual(provider.calls, [])
            self.assertFalse((root / "daily_cache.json").exists())

    def test_terminal_capture_is_not_refetched_when_its_cache_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            capture = _capture(root)["capture"]
            terminal = {
                "schema_name": "a_short_factor_comparison_v2_weekly", "schema_version": "2.0.0",
                "record_type": "outcome", "program_id": "a_short_factor_comparison_v2",
                "decision_date": DECISION_DATE, "epoch_id": capture["epoch_id"],
                "payload": {"questions": [{"status": "settled"}]}, "boundary": capture["boundary"],
            }
            (root / "weeks" / DECISION_DATE / "outcome.json").write_text(json.dumps(terminal), encoding="utf-8")
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                result = materialize_incremental_cache(root=root, run_date=RUN_DATE, pro=provider)
            self.assertEqual(result["status"], "no_frozen_v2_captures")
            self.assertEqual(provider.calls, [])

    def test_fetches_only_frozen_selected_union_and_marks_direct_adjustment_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            capture = _capture(root)["capture"]
            selected = sorted({code for question in capture["payload"]["questions"] for arm in question["arms"]
                               for code in arm["selected_symbols"]})
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                result = materialize_incremental_cache(root=root, run_date=RUN_DATE, pro=provider)
            self.assertEqual(result["status"], "cache_updated")
            self.assertEqual(result["provider_calls"], 1 + 3 * len(selected))
            self.assertEqual(sorted({call[1].get("ts_code") for call in provider.calls if call[0] == "daily"}), selected)
            cache = json.loads((root / "daily_cache.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted({row["ts_code"] for row in cache["stocks"]}), selected)
            self.assertTrue(all(row["adj_factor_observed"] is True for row in cache["stocks"]))
            self.assertTrue(all(row["adj_factor_source"] == "provider_observed" for row in cache["stocks"]))
            self.assertTrue(all(row["corporate_action_verified"] is False for row in cache["stocks"]))
            self.assertEqual(cache["stocks"][0]["open"], 10.0, "raw daily price must not be double-adjusted")

    def test_missing_adjustment_is_recorded_as_missing_not_forward_filled_or_defaulted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            provider = FakeTushare(missing_adj=True)
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                materialize_incremental_cache(root=root, run_date=RUN_DATE, pro=provider)
            cache = json.loads((root / "daily_cache.json").read_text(encoding="utf-8"))
            first_by_symbol = {}
            for row in cache["stocks"]:
                first_by_symbol.setdefault(row["ts_code"], row)
            self.assertTrue(all(row["adj_factor"] is None for row in first_by_symbol.values()))
            self.assertTrue(all(row["adj_factor_observed"] is False for row in first_by_symbol.values()))
            self.assertTrue(all(row["adj_factor_source"] == "provider_missing" for row in first_by_symbol.values()))

    def test_empty_cache_cannot_defer_v2_fixed_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                with self.assertRaisesRegex(ComparisonV2Error, "v2 cache builder provider-call budget exceeded"):
                    materialize_incremental_cache(root=root, run_date=RUN_DATE,
                                                  max_provider_calls=1, pro=provider)
            self.assertEqual(provider.calls, [])
            self.assertFalse((root / "daily_cache.json").exists())

    def test_existing_complete_cache_is_checked_before_symbol_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                materialize_incremental_cache(root=root, run_date=RUN_DATE, pro=FakeTushare())
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                result = materialize_incremental_cache(root=root, run_date=RUN_DATE,
                                                       max_provider_calls=1, pro=provider)
            self.assertEqual(result["status"], "cache_current")
            self.assertEqual([name for name, _kwargs in provider.calls], ["trade_cal"])

    def test_p2_and_p3_share_the_same_cache_and_execution_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            root.mkdir(parents=True)
            p2 = Path(tmp) / "logs" / "a_short_target_policy_comparison.json"
            p3 = Path(tmp) / "logs" / "a_short_final_action_validation.json"
            p2.parent.mkdir(parents=True)
            _write_p2_ledger(p2, {
                "decision_date": DECISION_DATE,
                "forward_eligible": True,
                "source_identity": {"price_data_through": DECISION_DATE},
                "target_entries": [{
                    "ts_code": "600100.SH", "changed": True,
                    "baseline": {"reference_trade_date": DECISION_DATE},
                    "challenger": {"reference_trade_date": DECISION_DATE},
                    "outcomes": {"status": "pending"},
                }],
                "breakout_entries": [],
            })
            _write_p3_ledger(p3, {
                "decision_date": DECISION_DATE,
                "forward_eligible": True,
                "selected_codes": ["600200.SH"],
                "managed_plans": {"600200.SH": {"reference_trade_date": DECISION_DATE}},
                "full_edge_result": {"status": "no_count", "reason": "execution_cache_unavailable"},
            })
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                result = materialize_incremental_cache(
                    root=root, run_date=RUN_DATE, pro=provider,
                    target_policy_root=p2, final_action_validation_root=p3,
                )
            self.assertEqual(result["status"], "cache_updated")
            self.assertEqual(result["consumers"], ["p2_target_policy", "p3_final_action_validation"])
            cache = json.loads((root / "daily_cache.json").read_text(encoding="utf-8"))
            self.assertEqual({row["ts_code"] for row in cache["rows"]}, {"600100.SH", "600200.SH"})
            sample = cache["rows"][0]
            self.assertEqual(sample["raw_close"], 10.5)
            self.assertEqual(sample["close"], 21.0)
            self.assertEqual(sample["high"], 21.6)
            self.assertEqual(sample["low"], 19.6)
            self.assertEqual(sample["up_limit"], 22.0)
            self.assertEqual(sample["down_limit"], 18.0)
            self.assertEqual(sample["volume"], 1000.0)
            self.assertFalse(sample["suspended"])
            self.assertEqual(load_p2_cache(root / "daily_cache.json"),
                             load_p3_cache(root / "daily_cache.json"))

    def test_official_operation_evidence_is_a_late_shared_cache_consumer_not_a_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            root.mkdir(parents=True)
            official_root = _official_operation_root(tmp)
            _write_official_operation_capture(official_root)
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                result = materialize_incremental_cache(
                    root=root, run_date=RUN_DATE, pro=provider,
                    official_operation_evidence_root=official_root,
                )
            self.assertEqual(result["status"], "cache_updated")
            self.assertEqual(result["consumers"], ["official_operation_evidence"])
            cache = json.loads((root / "daily_cache.json").read_text(encoding="utf-8"))
            self.assertEqual({row["ts_code"] for row in cache["rows"]}, {"600300.SH"})
            self.assertTrue(all(key in cache["rows"][0] for key in ("high", "low", "volume", "down_limit")))
            daily_call = next(kwargs for name, kwargs in provider.calls if name == "daily")
            self.assertLess(daily_call["start_date"], DECISION_DATE)

    def test_v2_missing_symbols_are_scheduled_before_p2_under_the_shared_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            capture = _capture(root)["capture"]
            v2_symbols = sorted({code for question in capture["payload"]["questions"]
                                 for arm in question["arms"] for code in arm["selected_symbols"]})
            p2 = Path(tmp) / "logs" / "a_short_target_policy_comparison.json"
            p2.parent.mkdir(parents=True)
            _write_p2_ledger(p2, {
                "decision_date": DECISION_DATE, "forward_eligible": True,
                "target_entries": [{
                        "ts_code": f"601{index:03}.SH", "changed": True,
                        "baseline": {"reference_trade_date": DECISION_DATE},
                        "challenger": {"reference_trade_date": DECISION_DATE},
                        "outcomes": {"status": "pending"},
                } for index in range(10)],
                "breakout_entries": [],
            })
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                result = materialize_incremental_cache(
                    root=root, run_date=RUN_DATE, pro=provider,
                    target_policy_root=p2, max_provider_calls=1 + 3 * len(v2_symbols),
                )
            self.assertEqual(result["status"], "cache_updated_with_deferrals")
            fetched = sorted(call[1]["ts_code"] for call in provider.calls if call[0] == "daily")
            self.assertEqual(fetched, v2_symbols)
            self.assertEqual(result["deferred_symbols_by_consumer"]["p2_target_policy"], 10)

    def test_p5_is_scheduled_after_v2_and_before_p2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            capture = _capture(root)["capture"]
            v2_symbols = sorted({code for question in capture["payload"]["questions"]
                                 for arm in question["arms"] for code in arm["selected_symbols"]})
            p2 = Path(tmp) / "logs" / "a_short_target_policy_comparison.json"
            p2.parent.mkdir(parents=True)
            _write_p2_ledger(p2, {
                "decision_date": DECISION_DATE, "forward_eligible": True,
                "target_entries": [{
                    "ts_code": "601001.SH", "changed": True,
                    "baseline": {"reference_trade_date": DECISION_DATE},
                    "challenger": {"reference_trade_date": DECISION_DATE},
                    "outcomes": {"status": "pending"},
                }],
                "breakout_entries": [],
            })
            p5_window = [{
                "consumer": "p5_industry_weight", "decision_date": DECISION_DATE,
                "price_data_through": DECISION_DATE, "window_mode": "captured_start",
                "horizon_days": 20, "symbols": ["600500.SH"],
            }]
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE), \
                    mock.patch("runners.a_short_factor_comparison_v2_cache_build._p5_frozen_windows", return_value=p5_window):
                result = materialize_incremental_cache(
                    root=root, run_date=RUN_DATE, pro=provider,
                    industry_weight_root=Path(tmp) / "p5", target_policy_root=p2,
                    max_provider_calls=1 + 3 * (len(v2_symbols) + 1),
                )
            fetched = sorted(call[1]["ts_code"] for call in provider.calls if call[0] == "daily")
            self.assertEqual(fetched, sorted([*v2_symbols, "600500.SH"]))
            self.assertEqual(result["p5_deferred_due_to_budget"], 0)
            self.assertEqual(result["deferred_symbols_by_consumer"]["p2_target_policy"], 1)

    def test_unverified_adjustment_jump_cannot_become_a_managed_exit_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            root.mkdir(parents=True)
            p2 = Path(tmp) / "logs" / "a_short_target_policy_comparison.json"
            p2.parent.mkdir(parents=True)
            _write_p2_ledger(p2, {
                "decision_date": DECISION_DATE, "forward_eligible": True,
                "target_entries": [{
                        "ts_code": "600100.SH", "changed": True,
                        "baseline": {"reference_trade_date": DECISION_DATE},
                        "challenger": {"reference_trade_date": DECISION_DATE},
                        "outcomes": {"status": "pending"},
                }],
                "breakout_entries": [],
            })
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                materialize_incremental_cache(root=root, run_date=RUN_DATE,
                                              target_policy_root=p2,
                                              pro=FakeTushare(adjustment_jump=True))
            rows = load_p2_cache(root / "daily_cache.json")["600100.SH"]
            self.assertTrue(any(row["adj_factor"] is None for row in rows))
            result = evaluate_managed_exit({
                "decision_date": DECISION_DATE,
                "entry_low": 20.0, "entry_high": 21.0, "stop": 18.0,
                "t1": 23.0, "t2": 25.0, "atr_multiplier": 1.25,
                "price_basis": "qfq", "reference_trade_date": DECISION_DATE,
                "reference_close": 21.0,
            }, rows)
            self.assertEqual(result["status"], "no_count")

    def test_stale_p2_epoch_cannot_request_provider_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            root.mkdir(parents=True)
            p2 = Path(tmp) / "logs" / "a_short_target_policy_comparison.json"
            p2.parent.mkdir(parents=True)
            _write_p2_ledger(p2, {
                "decision_date": DECISION_DATE, "forward_eligible": True,
                "target_entries": [{
                    "ts_code": "600100.SH", "changed": True,
                    "baseline": {}, "challenger": {}, "outcomes": {"status": "pending"},
                }],
            })
            ledger = json.loads(p2.read_text(encoding="utf-8"))
            ledger["epochs"].append({
                "epoch_id": "stale", "contract_fingerprint": "stale",
                "records": [{
                    "decision_date": "20260105", "forward_eligible": True,
                    "target_entries": [{
                        "ts_code": "600999.SH", "changed": True,
                        "baseline": {}, "challenger": {}, "outcomes": {"status": "pending"},
                    }],
                    "breakout_entries": [],
                }],
            })
            p2.write_text(json.dumps(ledger), encoding="utf-8")
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                materialize_incremental_cache(root=root, run_date=RUN_DATE,
                                              target_policy_root=p2, pro=provider)
            fetched = {call[1]["ts_code"] for call in provider.calls if call[0] == "daily"}
            self.assertEqual(fetched, {"600100.SH"})

    def test_tampered_non_main_board_consumer_symbol_fails_before_provider_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            root.mkdir(parents=True)
            p2 = Path(tmp) / "logs" / "a_short_target_policy_comparison.json"
            p2.parent.mkdir(parents=True)
            _write_p2_ledger(p2, {
                "decision_date": DECISION_DATE, "forward_eligible": True,
                "target_entries": [{
                    "ts_code": "300001.SZ", "changed": True,
                    "baseline": {}, "challenger": {}, "outcomes": {"status": "pending"},
                }],
                "breakout_entries": [],
            })
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                with self.assertRaisesRegex(ComparisonV2Error, "non-main-board"):
                    materialize_incremental_cache(root=root, run_date=RUN_DATE,
                                                  target_policy_root=p2, pro=provider)
            self.assertEqual(provider.calls, [])

    def test_legacy_1_0_cache_is_discarded_and_rebuilt_as_1_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            root.mkdir(parents=True, exist_ok=True)
            path = root / "daily_cache.json"
            path.write_text(json.dumps(_legacy_cache()), encoding="utf-8")
            provider = FakeTushare()
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                result = materialize_incremental_cache(root=root, run_date=RUN_DATE, pro=provider)
            rebuilt = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "cache_updated")
            self.assertEqual(rebuilt["schema_version"], "1.1.0")
            self.assertTrue(rebuilt["rows"])
            self.assertTrue(all(row["open"] != 99.0 for row in rebuilt["stocks"]))

    def test_legacy_1_0_cache_is_unchanged_when_rebuild_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            root.mkdir(parents=True, exist_ok=True)
            path = root / "daily_cache.json"
            original = json.dumps(_legacy_cache())
            path.write_text(original, encoding="utf-8")
            provider = FakeTushare()
            with mock.patch.object(provider, "daily", side_effect=RuntimeError("provider unavailable")), \
                    mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=RUN_DATE):
                with self.assertRaises(RuntimeError):
                    materialize_incremental_cache(root=root, run_date=RUN_DATE, pro=provider)
            self.assertEqual(path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
