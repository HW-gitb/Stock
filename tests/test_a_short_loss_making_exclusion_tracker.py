import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from engine.a_short_loss_making_admission import (
    LOSS_MAKING_REASON,
    UNAVAILABLE_REASON,
    apply_loss_making_admission,
    merge_loss_making_exclusion_tracker,
    update_loss_making_exclusion_tracker,
    validate_loss_making_exclusion_tracker,
)
from engine.a_short_regime_classifier import FORWARD_RETURN_BASIS


ROOT = Path(__file__).resolve().parents[1]
EGS_SCRIPT = ROOT / "A-EGS" / "egs_main.py"
_EGS_MAIN = None


def _scored(values):
    rows = []
    for code, profit in values:
        rows.append({
            "ts_code": code,
            "ttm_profit_dedt": profit,
            "final_score": 90.0 - len(rows),
            "l4_score": 80.0,
            "pct_20d_n": 5.0,
            "tier": "Tier1",
        })
    return pd.DataFrame(rows)


def _rank_csv(path, revision="a" * 32):
    global _EGS_MAIN
    if _EGS_MAIN is None:
        old_argv = sys.argv[:]
        sys.argv = [str(EGS_SCRIPT), "--help"]
        try:
            spec = importlib.util.spec_from_file_location("egs_main_tracker_producer", EGS_SCRIPT)
            _EGS_MAIN = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(_EGS_MAIN)
        finally:
            sys.argv = old_argv

    scored = pd.DataFrame([
        {"ts_code": "600000.SH", "ttm_profit_dedt": -1.0, "final_score": 88.0,
         "l4_score": 80.0, "pct_20d_n": 5.0, "tier": "Tier1"},
        {"ts_code": "600001.SH", "ttm_profit_dedt": None, "final_score": 87.0,
         "l4_score": 79.0, "pct_20d_n": 4.0, "tier": "Tier1"},
        {"ts_code": "600002.SH", "ttm_profit_dedt": 1.0, "final_score": 86.0,
         "l4_score": 78.0, "pct_20d_n": 3.0, "tier": "Tier1"},
    ])
    admitted, reasons, audit = apply_loss_making_admission(scored)
    audit["decision_as_of"] = "20260817"
    audit["run_revision_id"] = revision
    audit["pre_admission_top15"] = True
    audit["post_admission_top15"] = audit["reason"].isna()
    features = pd.DataFrame({
        "ts_code": scored["ts_code"],
        "name": ["A", "B", "C"],
        "l1_name": ["L1"] * 3,
        "l2_name": ["L2"] * 3,
        "total_mv": [100.0] * 3,
        "pct_20d": [1.0] * 3,
        "avg_amount_20d": [1000.0] * 3,
    })
    _summary, detail = _EGS_MAIN.build_rank_universe_reconciliation(
        df_l0=scored[["ts_code"]],
        feature_source=features,
        stages=[
            ("master_join", scored, False, "master_join_loss"),
            ("l5_rank", scored, False, "l5_unexpected_row_loss"),
            ("loss_making_admission", admitted, True, reasons),
        ],
        sources={},
        rank_annotations=audit,
    )
    _EGS_MAIN.write_csv_atomic(detail, str(path), index=False)
    marker = {
        "schema_name": "a_short_egs_official_publish",
        "stage_status": "complete",
        "trade_date": "20260817",
        "decision_as_of": "20260817",
        "run_revision_id": revision,
        "files": {
            "rank_universe_reconciliation": {
                "path": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        },
    }
    (path.parent / "official_publish.json").write_text(
        json.dumps(marker), encoding="utf-8"
    )


class LossMakingAdmissionTests(unittest.TestCase):
    def test_partition_is_hard_fail_closed_and_does_not_rescore(self):
        source = _scored([
            ("600000.SH", 10.0),
            ("600001.SH", 0.0),
            ("600002.SH", -1.0),
            ("600003.SH", None),
            ("600004.SH", float("nan")),
            ("600005.SH", float("inf")),
            ("600006.SH", "not-a-number"),
        ])
        before = source.copy(deep=True)
        admitted, reasons, audit = apply_loss_making_admission(source)

        self.assertEqual(admitted["ts_code"].tolist(), ["600000.SH"])
        self.assertEqual(set(reasons), {
            "600001.SH", "600002.SH", "600003.SH", "600004.SH",
            "600005.SH", "600006.SH",
        })
        self.assertEqual(reasons["600001.SH"], LOSS_MAKING_REASON)
        self.assertEqual(reasons["600003.SH"], UNAVAILABLE_REASON)
        self.assertEqual(admitted.iloc[0]["final_score"], 90.0)
        pd.testing.assert_frame_equal(source, before)
        self.assertEqual(set(audit), {
            "ts_code", "ttm_profit_dedt", "final_score",
            "pre_admission_rank", "reason",
        })

    def test_pe_and_quarter_proxy_do_not_enter_gate(self):
        frame = _scored([("600000.SH", 1.0), ("600001.SH", -1.0)])
        frame["pe_ttm"] = [None, 20.0]
        frame["q0_profit_dedt"] = [-2.0, 2.0]
        admitted, reasons, _audit = apply_loss_making_admission(frame)
        self.assertEqual(admitted["ts_code"].tolist(), ["600000.SH"])
        self.assertEqual(reasons["600001.SH"], LOSS_MAKING_REASON)


class LossMakingTrackerTests(unittest.TestCase):
    def test_official_binding_shared_backfill_and_idempotent_merge(self):
        revision = "a" * 32
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            rank = root / "result" / "a_short" / "20260817" / "revisions" / revision / "rank_universe_reconciliation.csv"
            rank.parent.mkdir(parents=True)
            _rank_csv(rank, revision)
            tracker = root / "loss_making_exclusion_tracker.json"
            csi = pd.DataFrame({
                "trade_date": ["20260817", "20260818", "20260819", "20260820", "20260821",
                               "20260824", "20260825", "20260826", "20260827", "20260828", "20260831"],
                "close": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0],
            })

            payload = update_loss_making_exclusion_tracker(
                tracker,
                official_rank_csv_path=rank,
                as_of="20260817",
                run_revision_id=revision,
                csi1000=csi,
                as_of_now="20260831",
                project_root=root,
            )
            self.assertEqual(payload["forward_return_basis"], FORWARD_RETURN_BASIS)
            self.assertEqual(len(payload["records"]), 2)
            self.assertEqual(payload["records"][0]["forward_returns"]["h1"], 1.0)
            validate_loss_making_exclusion_tracker(payload)
            first_bytes = tracker.read_bytes()

            again = update_loss_making_exclusion_tracker(
                tracker,
                official_rank_csv_path=rank,
                as_of="20260817",
                run_revision_id=revision,
                csi1000=csi,
                as_of_now="20260831",
                project_root=root,
            )
            self.assertEqual(again, payload)
            self.assertEqual(tracker.read_bytes(), first_bytes)

    def test_same_key_source_conflict_preserves_bytes_and_revision_is_separate(self):
        base = {
            "schema_name": "a_short_loss_making_exclusion_tracker",
            "schema_version": "1.0.0",
            "forward_return_basis": FORWARD_RETURN_BASIS,
            "records": [{
                "as_of": "20260817", "run_revision_id": "a" * 32,
                "official_rank_reconciliation": "result/a_short/20260817/revisions/" + "a" * 32 + "/rank_universe_reconciliation.csv",
                "ts_code": "600000.SH", "ttm_profit_dedt": -1.0,
                "final_score": 88.0, "pre_admission_rank": 1,
                "exclusion_reason": LOSS_MAKING_REASON,
                "forward_returns": {"h1": None, "h3": None, "h5": None, "h10": None},
                "forward_returns_pending": ["h1", "h3", "h5", "h10"],
                "backfill_complete": False,
            }],
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            path = Path(tmp) / "tracker.json"
            path.write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
            before = path.read_bytes()
            conflict = dict(base["records"][0], final_score=87.0)
            with self.assertRaises(ValueError):
                merge_loss_making_exclusion_tracker(path, [conflict])
            self.assertEqual(path.read_bytes(), before)
            separate = dict(base["records"][0], run_revision_id="b" * 32,
                            official_rank_reconciliation="result/a_short/20260817/revisions/" + "b" * 32 + "/rank_universe_reconciliation.csv")
            merged = merge_loss_making_exclusion_tracker(path, [separate])
            self.assertEqual(len(merged["records"]), 2)


if __name__ == "__main__":
    unittest.main()
