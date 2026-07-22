"""Offline contract tests for the first A-short formal-operation capture knife."""
from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_official_operation_evidence import (  # noqa: E402
    OfficialOperationEvidenceError,
    _boundary,
    _decision_from_report,
    _digest,
    _private_root,
    _portfolio_only_decision,
    _source_identity,
    capture_after_published_weekly,
    settle_and_summarize,
)
from engine.a_short_managed_exit import evaluate_managed_exit  # noqa: E402

FIXTURE_DIR = ROOT / "research" / "results" / "a_short" / "20260720"
FIXTURE_AS_OF = "20260720"


def _private_root_path(base: Path) -> Path:
    return base / "state" / "a_short" / "operation_evidence_private" / "v1"


def _write_frozen_official_capture(root: Path, *, decision_date: str = "20260202") -> tuple[dict, dict]:
    """Write a schema-valid private capture with one genuine qfq execution plan."""
    source = {
        "as_of": decision_date,
        "price_data_through": decision_date,
        "run_id": "official-operation-test",
        "candidate_digest": "a" * 64,
        "official_m67_sha256": "b" * 64,
        "official_receipt_sha256": "c" * 64,
        "account_snapshot_digest": None,
        "weekly_schema_version": "1.0.0",
        "m67_schema_versions": ["1.0.0"],
        "runtime_configuration": {"schema_name": "test", "schema_version": "1", "configuration_fingerprint": "d",
                                  "policies": []},
        "rule_parameter_versions": {},
        "effect_contract_ledger_sha256": "d" * 64,
    }
    decision = {
        "decision_id": "e" * 64,
        "symbol": "600300.SH",
        "scope": "new_candidate",
        "final_action": "建仓",
        "holding_disposition": None,
        "display": {},
        "constraints": {},
        "prices": {
            "entry_type": "低吸",
            "managed_exit_plan": {
                "decision_date": decision_date,
                "entry_low": 10.0,
                "entry_high": 10.5,
                "stop": 9.0,
                "t1": 12.0,
                "t2": 13.0,
                "atr_multiplier": 1.0,
                "price_basis": "qfq",
                "reference_trade_date": decision_date,
                "reference_close": 10.0,
                "policy_version": "official_m67_v1",
            },
            "managed_exit_plan_unavailable_reason": None,
        },
        "sizing": {},
        "portfolio": {},
        "environment": {},
        "evidence_modes": {},
    }
    capture = {
        "schema_name": "a_short_official_operation_evidence_private_capture",
        "schema_version": "1.1.0",
        "record_type": "decision_capture",
        "program_id": "a_short_official_operation_evidence",
        "as_of": decision_date,
        "source_identity": source,
        "decisions": [decision],
        "boundary": _boundary(),
    }
    capture["capture_sha256"] = _digest(capture)
    path = root / "weeks" / decision_date / "capture.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(capture), encoding="utf-8")
    return capture, decision


def _qfq_execution_rows(*, decision_date: str = "20260202", count: int = 21) -> list[dict]:
    rows = [{"trade_date": decision_date, "open": 20.0, "high": 21.0, "low": 19.0, "close": 20.0,
             "raw_close": 10.0, "adj_factor": 2.0, "volume": 1000.0, "suspended": False,
             "up_limit": 22.0, "down_limit": 18.0}]
    for day in range(3, count + 3):
        rows.append({"trade_date": f"202602{day:02d}", "open": 20.0, "high": 21.0, "low": 19.0,
                     "close": 20.0, "raw_close": 10.0, "adj_factor": 2.0, "volume": 1000.0,
                     "suspended": False, "up_limit": 22.0, "down_limit": 18.0})
    return rows


def _publish(base: Path) -> tuple[Path, Path]:
    """Copy a committed, account-free official bundle without reconstructing a recommendation.

    This fixture is deliberately the published source shape, not an approximate M6.7
    reconstruction. The live builder's effect-contract guard is tested in its own
    module; this suite isolates the capture consumer's receipt/schema boundary.
    """
    output = base / FIXTURE_AS_OF / "weekly_m67.json"
    output.parent.mkdir(parents=True)
    for name in ("weekly_m67.json", "weekly_m67.md", "weekly_m67.receipt.json"):
        shutil.copy2(FIXTURE_DIR / name, output.parent / name)
    return output, output.with_suffix("").with_suffix(".receipt.json")


class OfficialOperationEvidenceCaptureTests(unittest.TestCase):
    @staticmethod
    def _execution_rows(*, ambiguous_stop: bool = False) -> list[dict]:
        rows = []
        for day in range(1, 36):
            rows.append({"trade_date": f"202601{day:02d}", "open": 10.5, "high": 11.0,
                         "low": 10.0, "close": 10.5, "volume": 1000, "suspended": False,
                         "up_limit": 12.0, "down_limit": 8.0})
        # The twentieth post-decision session is day 21.  Day 2 is entry; day 3
        # reaches TP1 and day 4 reaches TP2, unless the adversarial same-bar
        # stop/profit case is requested.
        rows[1].update({"open": 10.5, "high": 11.0, "low": 10.2, "close": 10.8})
        rows[2].update({"open": 11.0, "high": 12.4 if not ambiguous_stop else 13.5,
                        "low": 10.5 if not ambiguous_stop else 8.5, "close": 11.8})
        rows[3].update({"open": 12.0, "high": 13.5, "low": 11.5, "close": 13.0})
        return rows

    def test_official_policy_reuses_exit_core_and_records_tp2_or_stop_first_ambiguity(self):
        plan = {"decision_date": "20260101", "entry_low": 10.0, "entry_high": 11.0,
                "stop": 9.0, "t1": 12.0, "t2": 13.0, "atr_multiplier": 1.0,
                "price_basis": "execution_raw_x_adj"}
        settled = evaluate_managed_exit(plan, self._execution_rows(), policy_version="official_m67_v1")
        self.assertEqual(settled["status"], "settled")
        self.assertEqual([event["kind"] for event in settled["events"][:2]], ["t1", "t2"])
        self.assertFalse(settled["official_path"]["execution_path_ambiguous"])

        partial_then_stop_rows = self._execution_rows()
        partial_then_stop_rows[3].update({"open": 9.5, "high": 11.0, "low": 8.5, "close": 9.0})
        partial_then_stop = evaluate_managed_exit(plan, partial_then_stop_rows, policy_version="official_m67_v1")
        self.assertEqual([event["kind"] for event in partial_then_stop["events"][:2]], ["t1", "stop_or_trailing"])
        self.assertEqual([event["weight"] for event in partial_then_stop["events"][:2]], [0.5, 0.5])

        ambiguous = evaluate_managed_exit(plan, self._execution_rows(ambiguous_stop=True),
                                          policy_version="official_m67_v1")
        self.assertEqual(ambiguous["status"], "settled")
        self.assertEqual(ambiguous["events"][0]["kind"], "stop_or_trailing")
        self.assertTrue(ambiguous["official_path"]["same_bar_both_triggered"])
        self.assertTrue(ambiguous["official_path"]["execution_path_ambiguous"])

    def test_official_fill_requires_frozen_entry_range_without_changing_default_policy(self):
        plan = {"decision_date": "20260101", "entry_low": 10.0, "entry_high": 10.5,
                "stop": 9.0, "t1": 12.0, "t2": 13.0, "atr_multiplier": 1.0,
                "price_basis": "execution_raw_x_adj"}
        rows = self._execution_rows()
        for row in rows[1:]:
            row.update({"open": 20.0, "high": 20.5, "low": 19.5, "close": 20.0})
        self.assertEqual(evaluate_managed_exit(plan, rows)["status"], "settled")
        official = evaluate_managed_exit(plan, rows, policy_version="official_m67_v1")
        self.assertEqual((official["status"], official["reason"]), ("no_count", "entry_outside_frozen_range"))

    def test_qfq_plan_requires_a_provable_execution_conversion_reference(self):
        plan = {"decision_date": "20260202", "entry_low": 10.0, "entry_high": 10.5,
                "stop": 9.0, "t1": 12.0, "t2": 13.0, "atr_multiplier": 1.0,
                "price_basis": "qfq", "reference_trade_date": "20260202", "reference_close": 10.0}
        settled = evaluate_managed_exit(plan, _qfq_execution_rows(), policy_version="official_m67_v1")
        self.assertEqual(settled["status"], "settled")
        missing_reference = _qfq_execution_rows()
        missing_reference[0]["adj_factor"] = None
        no_count = evaluate_managed_exit(plan, missing_reference, policy_version="official_m67_v1")
        self.assertEqual((no_count["status"], no_count["reason"]), ("no_count", "price_basis_mismatch"))

    def test_capture_is_source_bound_idempotent_and_private(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            output, receipt = _publish(base)
            root = _private_root_path(base)
            first = capture_after_published_weekly(root=root, out_path=output, receipt_path=receipt)
            second = capture_after_published_weekly(root=root, out_path=output, receipt_path=receipt)
            self.assertEqual((first["status"], second["status"]), ("captured", "idempotent_existing_capture"))
            capture = json.loads((root / "weeks" / FIXTURE_AS_OF / "capture.json").read_text(encoding="utf-8"))
            self.assertEqual(capture["source_identity"]["as_of"], FIXTURE_AS_OF)
            self.assertTrue(capture["source_identity"]["official_m67_sha256"])
            self.assertTrue(capture["source_identity"]["official_receipt_sha256"])
            self.assertIn("runtime_configuration_fingerprint", capture["source_identity"]["rule_parameter_versions"])
            self.assertTrue(capture["decisions"])
            decision = capture["decisions"][0]
            self.assertEqual(decision["scope"], "new_candidate")
            self.assertEqual(decision["final_action"], decision["display"]["table"]["操作"])
            self.assertEqual(decision["constraints"]["hard_veto"], decision["final_action"] == "否决")
            self.assertEqual(capture["boundary"]["outcome_settlement_implemented"], False)
            self.assertEqual(capture["boundary"]["modifies_m67"], False)

    def test_same_canonical_decision_with_changed_official_bytes_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            output, receipt = _publish(base)
            root = _private_root_path(base)
            capture_after_published_weekly(root=root, out_path=output, receipt_path=receipt)
            weekly = json.loads(output.read_text(encoding="utf-8"))
            output.write_text(json.dumps(weekly, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(OfficialOperationEvidenceError, "source_conflict"):
                capture_after_published_weekly(root=root, out_path=output, receipt_path=receipt)
            self.assertTrue((root / "conflicts" / f"{FIXTURE_AS_OF}.json").is_file())
            original = json.loads((root / "weeks" / FIXTURE_AS_OF / "capture.json").read_text(encoding="utf-8"))
            self.assertNotEqual(original["source_identity"]["official_m67_sha256"], "")

    def test_account_snapshot_mismatch_is_rejected_before_any_capture_write(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            output, receipt = _publish(base)
            bad = json.loads(receipt.read_text(encoding="utf-8"))
            bad["account_snapshot"] = {"snapshot_digest": "not-the-published-account"}
            receipt.write_text(json.dumps(bad, ensure_ascii=False) + "\n", encoding="utf-8")
            root = _private_root_path(base)
            with self.assertRaisesRegex(OfficialOperationEvidenceError, "account_snapshot_mismatch"):
                capture_after_published_weekly(root=root, out_path=output, receipt_path=receipt)
            self.assertFalse((root / "weeks" / FIXTURE_AS_OF / "capture.json").exists())

    def test_missing_runtime_configuration_binding_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            output, receipt = _publish(Path(td))
            weekly = json.loads(output.read_text(encoding="utf-8"))
            weekly["run_lineage"]["runtime_configuration"] = {}
            with self.assertRaisesRegex(OfficialOperationEvidenceError, "runtime_configuration_unbound"):
                _source_identity(weekly, output, receipt)

    def test_existing_holding_keeps_final_action_and_disposition_independent(self):
        with tempfile.TemporaryDirectory() as td:
            output, receipt = _publish(Path(td))
            weekly = json.loads(output.read_text(encoding="utf-8"))
            report = copy.deepcopy(weekly["reports"][0])
            table = report["m67"]["table"]
            table.update({"操作": "持有", "持仓处置": "建议减仓复核", "禁止加仓": True,
                          "减仓价": 12.3, "清仓价": 9.8, "减仓比例": "1/3"})
            report["machine"]["stateful_risk"] = {"position_state": "held"}
            report["machine"]["blocked_add_required"] = True
            report["machine"]["operation_impact"] = [{"veto_class": "m67_advisory_veto"}]
            source = _source_identity(weekly, output, receipt)
            decision = _decision_from_report(weekly, source, report)
            self.assertEqual(decision["scope"], "existing_holding")
            self.assertEqual(decision["final_action"], "持有")
            self.assertEqual(decision["holding_disposition"], "建议减仓复核")
            self.assertTrue(decision["constraints"]["blocked_add"])
            self.assertTrue(decision["constraints"]["advisory_downgrade"])
            self.assertEqual(decision["prices"]["holding_reduce_price"], 12.3)
            self.assertEqual(decision["prices"]["holding_clear_price"], 9.8)

    def test_new_build_freezes_qfq_reference_without_holding_only_current_close(self):
        with tempfile.TemporaryDirectory() as td:
            output, receipt = _publish(Path(td))
            weekly = json.loads(output.read_text(encoding="utf-8"))
            report = copy.deepcopy(weekly["reports"][0])
            report["m67"]["table"]["操作"] = "建仓"
            report["machine"]["entry_exit_size_star"]["plan"] = {
                "entry": 10.25, "entry_low": 10.0, "entry_high": 10.5, "stop": 9.0, "t1": 12.0, "t2": 13.0,
            }
            report["machine"].pop("current_close", None)
            decision = _decision_from_report(weekly, _source_identity(weekly, output, receipt), report)
            frozen = decision["prices"]["managed_exit_plan"]
            self.assertEqual(frozen["price_basis"], "qfq")
            self.assertEqual(frozen["reference_trade_date"], weekly["run_lineage"]["price_freshness"]["price_data_through"])
            self.assertEqual(frozen["reference_close"], 10.25)
            self.assertEqual(frozen["t2"], 13.0)

            report["machine"]["entry_exit_size_star"]["plan"].pop("entry")
            unavailable = _decision_from_report(weekly, _source_identity(weekly, output, receipt), report)
            self.assertIsNone(unavailable["prices"]["managed_exit_plan"])
            self.assertEqual(unavailable["prices"]["managed_exit_plan_unavailable_reason"],
                             "frozen_qfq_conversion_reference_unavailable")

    def test_terminal_outcome_survives_later_progress_but_conflicts_on_window_drift(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = _private_root_path(base)
            _write_frozen_official_capture(root)
            cache_path = base / "daily_cache.json"
            cache_path.write_text(json.dumps({"rows": [
                {"ts_code": "600300.SH", **row} for row in _qfq_execution_rows()
            ]}), encoding="utf-8")
            first = settle_and_summarize(
                root=root, as_of="20260222", daily_cache_path=cache_path,
                public_json_path=base / "public" / "summary.json",
                public_markdown_path=base / "public" / "summary.md",
            )
            self.assertEqual(first["outcomes_updated"], 1)
            outcome_path = next((root / "outcomes").glob("*.json"))
            first_outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            later_row = dict(payload["rows"][-1])
            later_row["trade_date"] = "20260224"
            payload["rows"].append(later_row)
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
            later = settle_and_summarize(
                root=root, as_of="20260301", daily_cache_path=cache_path,
                public_json_path=base / "public" / "summary.json",
                public_markdown_path=base / "public" / "summary.md",
            )
            self.assertEqual(later["outcomes_updated"], 0)
            self.assertEqual(json.loads(outcome_path.read_text(encoding="utf-8")), first_outcome)
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            payload["rows"][20]["close"] = 21.0
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(OfficialOperationEvidenceError, "terminal_conflict"):
                settle_and_summarize(
                    root=root, as_of="20260308", daily_cache_path=cache_path,
                    public_json_path=base / "public" / "summary.json",
                    public_markdown_path=base / "public" / "summary.md",
                )
            self.assertTrue(list((root / "conflicts").glob("outcome_*.json")))

    def test_portfolio_only_never_fabricates_stock_trade_fields(self):
        with tempfile.TemporaryDirectory() as td:
            output, receipt = _publish(Path(td))
            weekly = json.loads(output.read_text(encoding="utf-8"))
            weekly["portfolio_risk"] = {"summary": {"status": "manual_review_required"}, "stock_results": []}
            source = _source_identity(weekly, output, receipt)
            decision = _portfolio_only_decision(weekly, source)
            self.assertEqual((decision["scope"], decision["symbol"], decision["final_action"]),
                             ("portfolio_only", None, None))
            self.assertIsNone(decision["prices"]["entry_range"]["display"])
            self.assertIsNone(decision["sizing"]["suggested_shares"])

    def test_pipeline_wires_private_capture_only_after_official_publish(self):
        pipeline = (ROOT / "runners" / "a_short_weekly_pipeline.py").read_text(encoding="utf-8")
        published = pipeline.index("receipt_path = publish_weekly_bundle(")
        capture = pipeline.index("[official-operation-evidence] capture=")
        factor_v2 = pipeline.index("[factor-comparison-v2] capture=")
        self.assertIn("--official-operation-evidence-root", pipeline)
        self.assertIn("--official-operation-evidence-daily-cache", pipeline)
        self.assertGreater(capture, published)
        self.assertLess(capture, factor_v2)
        wrapper = (ROOT / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8")
        live_block = wrapper[wrapper.index("if (-not $IsHistoricalAsOf) {"):wrapper.index("if (Test-Path $OverlayPath)")]
        self.assertIn("--official-operation-evidence-root", live_block)
        self.assertIn("--official-operation-evidence-daily-cache', $FactorComparisonV2Cache", live_block)
        self.assertIn("--official-operation-evidence-root $OfficialOperationEvidenceRoot", live_block)

    def test_repo_private_root_is_provably_gitignored(self):
        expected = ROOT / "state" / "a_short" / "operation_evidence_private" / "v1"
        self.assertEqual(_private_root(expected), expected.resolve())

    def test_second_knife_writes_only_progress_ledger_and_deidentified_small_cohort_summary(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            output, receipt = _publish(base)
            root = _private_root_path(base)
            capture_after_published_weekly(root=root, out_path=output, receipt_path=receipt)
            result = settle_and_summarize(
                root=root, as_of=FIXTURE_AS_OF,
                public_json_path=base / "public" / "summary.json",
                public_markdown_path=base / "public" / "summary.md",
            )
            ledger = json.loads((root / "ledger.json").read_text(encoding="utf-8"))
            self.assertTrue(ledger["boundary"]["program_progress_ledger_only"])
            self.assertFalse(ledger["boundary"]["portfolio_state_created"])
            self.assertFalse(ledger["boundary"]["cash_or_positions_created"])
            self.assertEqual(result["summary"]["boundary"]["contains_symbols"], False)
            self.assertNotIn("ts_code", (base / "public" / "summary.json").read_text(encoding="utf-8"))
