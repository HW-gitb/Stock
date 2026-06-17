"""Tests for the A-short overlay §6 readiness + promotion-review reminder harness.

Verifies the forward-obs discovery (forward-only, fail-closed on malformed), the readiness
decision (accumulating / review_due_margin_pending / review_due_ready), the eval-summary build +
consistency + schema, the reminder banner, and main's write path. Synthetic overlay fixtures; no
network, no production touch.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_overlay_eval import (  # noqa: E402
    discover_forward_overlays, promotion_readiness, margin_frozen, build_eval_summary,
    validate_eval_summary_consistency, write_eval_summary, readiness_banner, _load_governance,
    assert_non_production_out, main, SCHEMA_PATH, GOV_PATH,
    DECISION_ACCUMULATING, DECISION_DUE_MARGIN_PENDING, DECISION_DUE_READY,
)


def _write_overlay_mismatch(root: Path, bucket: str, internal_as_of: str, concept: str = "forward") -> None:
    """把 internal_as_of 的 overlay 写进名为 bucket 的目录(bucket != internal_as_of → 错位 artifact)。"""
    d = root / bucket
    d.mkdir(parents=True, exist_ok=True)
    (d / "overlay.json").write_text(json.dumps(_overlay(internal_as_of, concept)), encoding="utf-8")


def _overlay(as_of: str, concept: str = "forward") -> dict:
    """Minimal schema-valid + consistency-valid overlay.json (empty candidate pool)."""
    return {
        "schema_name": "a_short_theme_overlay_comparison",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-17T00:00:00+08:00",
        "as_of": as_of,
        "preset": "a_short",
        "track": "comparison_non_production",
        "weights": {"esp": 0.15, "l4": 0.45, "theme": 0.25, "industry": 0.15},
        "thresholds": {
            "theme_window_blend": {"d5": 0.5, "d20": 0.5},
            "pass_percentile": 70.0, "breadth_up_frac_min": 0.5, "breadth_vol_frac_min": 0.4,
            "persistence_top_quantile": 0.3, "persistence_window_days": 5, "fit_floor": 0.4,
            "eligibility_min_pass": 2,
        },
        "pit_source": {"concept_membership": concept, "sw_mapping": "forward"},
        "candidate_count": 0,
        "candidates": [],
        "dropped_at_l0_l5": [],
        "boundary": {"production": False, "changes_final_score_or_tier": False,
                     "is_buy_advice": False, "satisfies_ship_gate": False},
    }


def _write_overlay(root: Path, as_of: str, concept: str = "forward") -> None:
    d = root / as_of
    d.mkdir(parents=True, exist_ok=True)
    (d / "overlay.json").write_text(json.dumps(_overlay(as_of, concept)), encoding="utf-8")


def _obs(n: int) -> list:
    return [{"as_of": f"202601{i:02d}", "generated_at": "t", "candidate_count": 3} for i in range(1, n + 1)]


class DiscoverTests(unittest.TestCase):
    def test_counts_only_forward(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_overlay(root, "20260101", "forward")
            _write_overlay(root, "20260102", "pit")          # 回放,不计
            _write_overlay(root, "20260103", "forward")
            _write_overlay(root, "20260104", "unavailable")  # 无概念,不计
            out = discover_forward_overlays(str(root))
            self.assertEqual([o["as_of"] for o in out], ["20260101", "20260103"])

    def test_skips_malformed_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_overlay(root, "20260101", "forward")
            bad = root / "20260102"
            bad.mkdir()
            (bad / "overlay.json").write_text('{"schema_name": "a_short_theme_overlay_comparison", "as_of": "20260102"}',
                                              encoding="utf-8")   # 缺字段 → schema fail → 跳过
            out = discover_forward_overlays(str(root))
            self.assertEqual([o["as_of"] for o in out], ["20260101"])

    def test_empty_or_missing_root(self):
        self.assertEqual(discover_forward_overlays(str(ROOT / "no_such_dir_xyz")), [])
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(discover_forward_overlays(d), [])

    def test_non_date_dirs_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "iv_feed_20260605").mkdir()               # 非 8 位日期目录
            _write_overlay(root, "20260101", "forward")
            out = discover_forward_overlays(str(root))
            self.assertEqual([o["as_of"] for o in out], ["20260101"])


class ReadinessTests(unittest.TestCase):
    def test_accumulating_below_min(self):
        r = promotion_readiness(11, 12, False)
        self.assertFalse(r["promotion_review_due"])
        self.assertEqual(r["decision_status"], DECISION_ACCUMULATING)

    def test_due_margin_pending(self):
        r = promotion_readiness(12, 12, False)
        self.assertTrue(r["promotion_review_due"])
        self.assertEqual(r["decision_status"], DECISION_DUE_MARGIN_PENDING)

    def test_due_ready_when_margin_frozen(self):
        r = promotion_readiness(13, 12, True)
        self.assertTrue(r["promotion_review_due"])
        self.assertEqual(r["decision_status"], DECISION_DUE_READY)

    def test_margin_frozen_detection(self):
        self.assertFalse(margin_frozen({"stable_win_margin_pending": "...", "min_forward_observations": 12}))
        self.assertTrue(margin_frozen({"stable_win_margin": 0.05}))

    def test_real_governance_margin_not_frozen_min_12(self):
        gov = _load_governance()
        pr = gov["promotion_rule"]
        self.assertEqual(pr["min_forward_observations"], 12)
        self.assertFalse(margin_frozen(pr))                   # v1 未冻 → 暂不授权升级


class BuildValidateSchemaTests(unittest.TestCase):
    def setUp(self):
        self.gov = _load_governance()
        self.schema = json.loads(Path(SCHEMA_PATH).read_text(encoding="utf-8"))

    def test_accumulating_summary_valid(self):
        s = build_eval_summary(_obs(5), "20260110", "t", self.gov)
        self.assertEqual(s["n_forward_observations"], 5)
        self.assertFalse(s["promotion_review_due"])
        self.assertEqual(s["decision_status"], DECISION_ACCUMULATING)
        jsonschema.validate(s, self.schema)
        validate_eval_summary_consistency(s)

    def test_due_margin_pending_summary_valid(self):
        s = build_eval_summary(_obs(12), "20260112", "t", self.gov)
        self.assertTrue(s["promotion_review_due"])
        self.assertEqual(s["decision_status"], DECISION_DUE_MARGIN_PENDING)
        self.assertFalse(s["stable_win_margin_frozen"])
        jsonschema.validate(s, self.schema)
        validate_eval_summary_consistency(s)

    def test_validate_rejects_count_mismatch(self):
        s = build_eval_summary(_obs(5), "20260110", "t", self.gov)
        s["n_forward_observations"] = 4
        with self.assertRaises(ValueError):
            validate_eval_summary_consistency(s)

    def test_validate_rejects_due_flag_mismatch(self):
        s = build_eval_summary(_obs(12), "20260112", "t", self.gov)
        s["promotion_review_due"] = False                     # 12>=12 却标 not due
        with self.assertRaises(ValueError):
            validate_eval_summary_consistency(s)

    def test_validate_rejects_status_mismatch(self):
        s = build_eval_summary(_obs(12), "20260112", "t", self.gov)
        s["decision_status"] = DECISION_DUE_READY             # margin 未冻却标 ready
        with self.assertRaises(ValueError):
            validate_eval_summary_consistency(s)

    def test_validate_rejects_nonascending_obs(self):
        s = build_eval_summary(_obs(3), "20260110", "t", self.gov)
        s["forward_observations"][1]["as_of"] = s["forward_observations"][0]["as_of"]   # 重复
        with self.assertRaises(ValueError):
            validate_eval_summary_consistency(s)

    def test_schema_extra_field_rejected(self):
        s = build_eval_summary(_obs(1), "20260110", "t", self.gov)
        s["unexpected"] = 1
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(s, self.schema)

    def test_schema_boundary_production_true_rejected(self):
        s = build_eval_summary(_obs(1), "20260110", "t", self.gov)
        s["boundary"]["production"] = True
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(s, self.schema)


class BannerTests(unittest.TestCase):
    def setUp(self):
        self.gov = _load_governance()

    def test_banner_not_due(self):
        b = readiness_banner(build_eval_summary(_obs(5), "20260110", "t", self.gov))
        self.assertIn("未到", b)
        self.assertIn("5/12", b)

    def test_banner_due_margin_pending(self):
        b = readiness_banner(build_eval_summary(_obs(12), "20260112", "t", self.gov))
        self.assertIn("升级复审到期", b)
        self.assertIn("stable_win_margin", b)
        self.assertIn("R-ASHORT-OVERLAY-EVAL-METRICS-FOLLOWUP", b)


class MainTests(unittest.TestCase):
    def test_main_writes_summary(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "buckets"
            for a in ("20260101", "20260102", "20260103"):
                _write_overlay(root, a, "forward")
            _write_overlay(root, "20260104", "pit")
            out = Path(d) / "overlay_eval_summary.json"
            rc = main(["--results-root", str(root), "--out", str(out), "--as-of", "20260110"])
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())
            s = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(s["n_forward_observations"], 3)   # pit 不计
            self.assertEqual(s["as_of"], "20260110")
            validate_eval_summary_consistency(s)

    def test_main_check_readiness_no_write(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "buckets"
            _write_overlay(root, "20260101", "forward")
            out = Path(d) / "overlay_eval_summary.json"
            rc = main(["--results-root", str(root), "--out", str(out), "--as-of", "20260110",
                       "--check-readiness"])
            self.assertEqual(rc, 0)
            self.assertFalse(out.exists())                     # --check-readiness 不写


class LineageGuardTests(unittest.TestCase):
    """R-ASHORT-OVERLAY-EVAL-ARTIFACT-LINEAGE-GUARD:桶目录名必须 == artifact as_of,错位 artifact 不得推进时钟。"""

    def test_bucket_name_mismatch_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_overlay(root, "20260101", "forward")             # 桶名==as_of → 计
            _write_overlay_mismatch(root, "20260102", "20260101")   # 桶 20260102 内含 as_of 20260101 → 错位 → 不计
            self.assertEqual([o["as_of"] for o in discover_forward_overlays(str(root))], ["20260101"])

    def test_mismatched_does_not_advance_threshold(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for i in range(1, 12):                                   # 11 个合法匹配
                _write_overlay(root, f"202601{i:02d}", "forward")
            _write_overlay_mismatch(root, "20260112", "20260201")    # 错位 → 不计;若守护失效会变 12 → due
            s = build_eval_summary(discover_forward_overlays(str(root)), "20260112", "t", _load_governance())
            self.assertEqual(s["n_forward_observations"], 11)
            self.assertFalse(s["promotion_review_due"])              # 错位不得把 11 推到 12


class ProductionOutGuardTests(unittest.TestCase):
    """R-ASHORT-OVERLAY-EVAL-PRODUCTION-OUT-GUARD:非生产 eval summary 绝不写进生产桶 result/a_short。"""

    def _summary(self):
        return build_eval_summary(_obs(1), "20260110", "t", _load_governance())

    def test_assert_helper_rejects_result_a_short(self):
        with self.assertRaises(ValueError):
            assert_non_production_out(str(Path("anything") / "result" / "a_short" / "x" / "s.json"))

    def test_write_rejects_result_a_short_no_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "result" / "a_short" / "20260110" / "overlay_eval_summary.json"
            with self.assertRaises(ValueError):
                write_eval_summary(self._summary(), str(out))
            self.assertFalse(out.exists())

    def test_main_rejects_result_a_short_no_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "buckets"
            _write_overlay(root, "20260101", "forward")
            out = Path(d) / "result" / "a_short" / "20260110" / "overlay_eval_summary.json"
            with self.assertRaises(ValueError):
                main(["--results-root", str(root), "--out", str(out), "--as-of", "20260110"])
            self.assertFalse(out.exists())

    def test_research_lane_out_ok(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "research" / "results" / "a_short" / "overlay_eval_summary.json"   # sanctioned
            write_eval_summary(self._summary(), str(out))
            self.assertTrue(out.exists())


class GovernanceNoteTests(unittest.TestCase):
    """R-ASHORT-OVERLAY-EVAL-GOVERNANCE-MODE-DRIFT:overlay governance 现契约 = pit + live today,'pit only' 不得复现。"""

    def test_overlay_governance_note_not_pit_only(self):
        gov = json.loads(Path(GOV_PATH).read_text(encoding="utf-8"))
        note = gov["scope"]["egs_main_runtime_change_note"].lower()
        self.assertNotIn("pit only", note)
        self.assertIn("today", note)                                # pit + live today 双模式
        self.assertIn("forward", note)
        self.assertTrue(gov["scope"]["egs_main_runtime_changed"])
        self.assertFalse(gov["scope"]["egs_main_production_behavior_changed"])


class BannerEncodingTests(unittest.TestCase):
    """R-ASHORT-OVERLAY-EVAL-BANNER-ENCODING:横幅须 GBK-safe(Windows 控制台 stdout=gbk 时到点不崩)。"""

    def test_all_banner_states_gbk_encodable(self):
        import copy as _copy
        gov = _load_governance()
        frozen = _copy.deepcopy(gov)
        frozen["promotion_rule"]["stable_win_margin"] = 0.05
        for s in (build_eval_summary(_obs(5), "20260110", "t", gov),       # accumulating
                  build_eval_summary(_obs(12), "20260112", "t", gov),      # review_due_margin_pending
                  build_eval_summary(_obs(12), "20260112", "t", frozen)):  # review_due_ready
            readiness_banner(s).encode("gbk")                             # 不抛 = Windows gbk 控制台安全


if __name__ == "__main__":
    unittest.main()
