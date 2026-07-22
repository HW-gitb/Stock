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
    _decision_from_report,
    _private_root,
    _portfolio_only_decision,
    _source_identity,
    capture_after_published_weekly,
)

FIXTURE_DIR = ROOT / "research" / "results" / "a_short" / "20260720"
FIXTURE_AS_OF = "20260720"


def _private_root_path(base: Path) -> Path:
    return base / "state" / "a_short" / "operation_evidence_private" / "v1"


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
        self.assertGreater(capture, published)
        self.assertLess(capture, factor_v2)
        wrapper = (ROOT / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8")
        live_block = wrapper[wrapper.index("if (-not $IsHistoricalAsOf) {"):wrapper.index("if (Test-Path $OverlayPath)")]
        self.assertIn("--official-operation-evidence-root", live_block)

    def test_repo_private_root_is_provably_gitignored(self):
        expected = ROOT / "state" / "a_short" / "operation_evidence_private" / "v1"
        self.assertEqual(_private_root(expected), expected.resolve())
