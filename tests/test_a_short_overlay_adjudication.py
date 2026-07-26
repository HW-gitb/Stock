"""P4a Stage3 rank-source comparison: frozen evidence only, no production effects."""
from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_overlay_adjudication import (  # noqa: E402
    OverlayAdjudicationError, build_public_summary, capture_after_published_weekly,
    _active_profile_binding, _adjudicate, _contract_fingerprint, _epoch_context, _monthly_cluster_t,
    _screening_runtime_recipe_binding, select_stage3_top5,
    settle_and_summarize_weekly, settle_from_daily_payload, validate_public_summary, write_public_summary,
)
from runners.a_short_factor_comparison_v2_cache_build import CONSUMER_PRIORITY  # noqa: E402
from engine import a_short_evidence_epoch_mode as _epoch_mode
from tests._a_short_epoch_mode_test_utils import enter_patched_epoch_modes

DECISION, RUN = "20260710", "20260710"


def _root(tmp: str) -> Path:
    return Path(tmp) / "state" / "a_short" / "overlay_adjudication_private" / "v1"


def _member(index: int, score: float | None = None) -> dict:
    return {"ts_code": f"600{index:03d}.SH", "final_score": float(score if score is not None else 100 - index),
            "l1_name": f"L1-{index}", "l2_name": f"L2-{index}", "tier": "Tier1",
            "overheat_flag": False, "chasing_high": False}


def _sources(tmp: str, *, mismatch: bool = False, same_scores: bool = False, members: int = 7) -> tuple[Path, Path, Path, Path, Path, dict]:
    directory = Path(tmp); eligible = [_member(i) for i in range(1, 8)]
    eligible = eligible[:members]
    baseline = select_stage3_top5(eligible, "final_score")
    snapshot = {"schema_name": "a_short_p4_stage3_selection_snapshot", "schema_version": "1.0.0", "as_of": DECISION,
                "run_id": "a-short-20260710-0123456789abcdef", "candidate_digest": "a" * 64,
                "active_industry_weight_profile": _active_profile_binding(), "top50": eligible, "stage3_eligible_pool": eligible,
                "screening_runtime_recipe": _screening_runtime_recipe_binding(),
                "official_tier1_final": baseline if not mismatch else list(reversed(baseline)), "boundary": {"comparison_only": True}}
    overlay = {"schema_name": "a_short_theme_overlay_comparison", "schema_version": "1.0.0", "as_of": DECISION,
               "track": "comparison_non_production", "boundary": {"production": False, "automatic_promotion": False},
               "candidates": [{"ts_code": row["ts_code"], "overlay_score": row["final_score"] if same_scores else float(index)} for index, row in enumerate(eligible, start=1)]}
    identity = {"run_id": snapshot["run_id"], "candidate_digest": "a" * 64}
    weekly = {"as_of": DECISION, "run_lineage": {**identity, "price_freshness": {"mode": "strict_as_of", "run_date": RUN, "price_data_through": DECISION}}}
    receipt = {"stage_status": "complete", "as_of": DECISION, **identity, "published_at": "2026-07-10T10:00:00+08:00",
               "outputs": ["weekly_m67.json", "weekly_m67.md"]}
    paths = (directory / "stage3_selection_snapshot.json", directory / "stage3_overlay_score.json", directory / "weekly_m67.json", directory / "weekly_m67.receipt.json")
    for path, value in zip(paths, (snapshot, overlay, weekly, receipt)):
        path.write_text(json.dumps(value), encoding="utf-8")
    paths[2].with_suffix(".md").write_text("# weekly\n", encoding="utf-8")
    marker = {"schema_name": "a_short_egs_official_publish", "schema_version": "1.0.0",
              "trade_date": DECISION, "run_id": snapshot["run_id"], "candidate_digest": "a" * 64,
              "published_at": "2026-07-10T09:00:00+08:00",
              "stage_status": "complete", "files": {
                  "p4_stage3_selection_snapshot": {"path": paths[0].name, "sha256": hashlib.sha256(paths[0].read_bytes()).hexdigest()},
                  "p4_stage3_overlay_score": {"path": paths[1].name, "sha256": hashlib.sha256(paths[1].read_bytes()).hexdigest()},
              }}
    marker_path = directory / "official_publish.json"
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    return (*paths, marker_path, identity)


def _daily(codes: list[str], *, missing_adjustment: bool = False) -> dict:
    dates = [f"202607{day:02d}" for day in range(10, 31)]
    stocks, limits, benchmarks = [], [], []
    for code in codes:
        for index, day in enumerate(dates):
            stocks.append({"ts_code": code, "trade_date": day, "open": 10.0 + index * .1, "high": 10.2 + index * .1,
                           "low": 9.9 + index * .1, "close": 10.1 + index * .1, "vol": 100.0,
                            "adj_factor": None if missing_adjustment else 1.0, "adj_factor_observed": not missing_adjustment,
                            "adj_factor_source": "provider_missing" if missing_adjustment else "provider_observed", "corporate_action_verified": False,
                            "suspended": False})
            limits.append({"ts_code": code, "trade_date": day, "up_limit": 99.0, "down_limit": 1.0})
    for benchmark in ("000852.SH", "000300.SH"):
        for index, day in enumerate(dates):
            benchmarks.append({"ts_code": benchmark, "trade_date": day, "open": 100.0 + index, "close": 100.5 + index, "provider_observed": True})
    rows = [{"ts_code": row["ts_code"], "trade_date": row["trade_date"], "open": row["open"], "high": row["high"], "low": row["low"],
             "close": row["close"], "volume": row["vol"], "suspended": row["suspended"], "up_limit": 99.0, "down_limit": 1.0,
             "raw_close": row["close"], "adj_factor": row["adj_factor"], "corporate_action_verified": False} for row in stocks]
    return {"schema_name": "a_short_factor_comparison_v2_daily_cache", "schema_version": "1.1.0", "stocks": stocks, "limits": limits,
            "benchmarks": benchmarks, "rows": rows, "meta": {"cache_kind": "a_short_shared_incremental",
            "source": "tushare:daily+adj_factor+stk_limit", "writer": "runners/a_short_factor_comparison_v2_cache_build.py",
            "last_run_date": "20260730", "consumers": ["p4_overlay_adjudication"], "provider_call_ceiling": 91,
            "deferred_due_to_budget": {}}}


class OverlayAdjudicationTests(unittest.TestCase):
    def setUp(self):
        # These cases assert the ENFORCED epoch contract (the historical default).
        # Pre-freeze behaviour is covered by tests/test_a_short_evidence_epoch_mode.py.
        enter_patched_epoch_modes(self, "frozen_enforced")

    def test_public_summary_rejects_older_as_of_but_allows_equal_or_newer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            json_path, markdown_path = Path(tmp) / "summary.json", Path(tmp) / "summary.md"
            current = build_public_summary(root=None, as_of="20260710")
            write_public_summary(current, json_path=json_path, markdown_path=markdown_path)
            older = build_public_summary(root=None, as_of="20260709")
            with self.assertRaisesRegex(OverlayAdjudicationError, "as_of_regressed"):
                write_public_summary(older, json_path=json_path, markdown_path=markdown_path)
            write_public_summary(build_public_summary(root=None, as_of="20260710"),
                                 json_path=json_path, markdown_path=markdown_path)
            write_public_summary(build_public_summary(root=None, as_of="20260711"),
                                 json_path=json_path, markdown_path=markdown_path)

    def _capture(self, tmp: str, **kwargs) -> Path:
        root = _root(tmp); stage3, overlay, weekly, receipt, marker, identity = _sources(tmp, **kwargs)
        with mock.patch("engine.a_short_overlay_adjudication._today", return_value=RUN):
            result = capture_after_published_weekly(root=root, decision_date=DECISION, run_date=RUN,
                stage3_snapshot_path=stage3, overlay_path=overlay, out_path=weekly, receipt_path=receipt,
                egs_publish_marker_path=marker, source_identity=identity, forward_eligible=True)
        self.assertEqual(result["status"], "captured_live_canonical")
        return root

    def test_baseline_must_exactly_match_official_and_overlay_cannot_change_pool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp); stage3, overlay, weekly, receipt, marker, identity = _sources(tmp, mismatch=True)
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value=RUN):
                with self.assertRaises(OverlayAdjudicationError):
                    capture_after_published_weekly(root=root, decision_date=DECISION, run_date=RUN, stage3_snapshot_path=stage3,
                        overlay_path=overlay, out_path=weekly, receipt_path=receipt, egs_publish_marker_path=marker, source_identity=identity, forward_eligible=True)

    def test_same_list_counts_with_zero_effect_and_historical_never_starts_clock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._capture(tmp, same_scores=True)
            capture = json.loads((root / "weeks" / DECISION / "capture.json").read_text(encoding="utf-8"))
            codes = sorted({row["ts_code"] for row in capture["payload"]["baseline_selected"] + capture["payload"]["candidate_selected"]})
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value="20260730"):
                settle_from_daily_payload(root=root, daily_payload=_daily(codes), as_of="20260730")
            outcome = json.loads((root / "weeks" / DECISION / "outcome.json").read_text(encoding="utf-8"))
            self.assertEqual(outcome["payload"]["horizons"]["h10"]["delta_pct"], 0.0)
            self.assertTrue(outcome["payload"]["horizons"]["h10"]["same_list_zero_effect"])
            summary = build_public_summary(root=root, as_of="20260730"); validate_public_summary(summary)
            self.assertEqual(summary["eligible_policy_weeks"], 1); self.assertEqual(summary["difference_weeks"], 0)
            stage3, overlay, weekly, receipt, marker, identity = _sources(tmp)
            result = capture_after_published_weekly(root=_root(tmp), decision_date="20260717", run_date="20260717",
                stage3_snapshot_path=stage3, overlay_path=overlay, out_path=weekly, receipt_path=receipt,
                egs_publish_marker_path=marker, source_identity=identity, forward_eligible=False)
            self.assertEqual(result["status"], "not_live_canonical_no_capture")

    def test_future_price_request_uses_settled_price_clock_not_decision_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp); stage3, overlay, weekly, receipt, marker, identity = _sources(tmp)
            for path in (stage3, overlay):
                doc = json.loads(path.read_text(encoding="utf-8")); doc["as_of"] = "20260720"
                path.write_text(json.dumps(doc), encoding="utf-8")
            weekly_doc = json.loads(weekly.read_text(encoding="utf-8"))
            weekly_doc["as_of"] = "20260720"
            weekly_doc["run_lineage"]["price_freshness"] = {
                "mode": "intraday_prior_settled", "run_date": "20260720", "price_data_through": "20260717"
            }
            weekly.write_text(json.dumps(weekly_doc), encoding="utf-8")
            receipt_doc = json.loads(receipt.read_text(encoding="utf-8")); receipt_doc.update(
                {"as_of": "20260720", "published_at": "2026-07-20T10:00:00+08:00"})
            receipt.write_text(json.dumps(receipt_doc), encoding="utf-8")
            marker_doc = json.loads(marker.read_text(encoding="utf-8")); marker_doc.update(
                {"trade_date": "20260720", "published_at": "2026-07-20T09:00:00+08:00"})
            marker_doc["files"]["p4_stage3_selection_snapshot"]["sha256"] = hashlib.sha256(stage3.read_bytes()).hexdigest()
            marker_doc["files"]["p4_stage3_overlay_score"]["sha256"] = hashlib.sha256(overlay.read_bytes()).hexdigest()
            marker.write_text(json.dumps(marker_doc), encoding="utf-8")
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value="20260720"):
                capture_after_published_weekly(root=root, decision_date="20260720", run_date="20260720",
                    stage3_snapshot_path=stage3, overlay_path=overlay, out_path=weekly, receipt_path=receipt,
                    egs_publish_marker_path=marker, source_identity=identity, forward_eligible=True)
            capture = json.loads((root / "weeks" / "20260720" / "capture.json").read_text(encoding="utf-8"))
            self.assertEqual(capture["payload"]["price_request"]["price_data_through"], "20260717")

    def test_same_week_replay_is_idempotent_but_content_drift_cannot_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._capture(tmp)
            stage3, overlay, weekly, receipt, marker, identity = _sources(tmp)
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value=RUN):
                self.assertEqual(capture_after_published_weekly(root=root, decision_date=DECISION, run_date=RUN,
                    stage3_snapshot_path=stage3, overlay_path=overlay, out_path=weekly, receipt_path=receipt,
                    egs_publish_marker_path=marker, source_identity=identity, forward_eligible=True)["status"], "idempotent_existing_capture")
                changed = json.loads(overlay.read_text(encoding="utf-8")); changed["candidates"][0]["overlay_score"] = 999.0; overlay.write_text(json.dumps(changed), encoding="utf-8")
                official = json.loads(marker.read_text(encoding="utf-8"))
                official["files"]["p4_stage3_overlay_score"]["sha256"] = hashlib.sha256(overlay.read_bytes()).hexdigest()
                marker.write_text(json.dumps(official), encoding="utf-8")
                self.assertEqual(capture_after_published_weekly(root=root, decision_date=DECISION, run_date=RUN,
                    stage3_snapshot_path=stage3, overlay_path=overlay, out_path=weekly, receipt_path=receipt,
                    egs_publish_marker_path=marker, source_identity=identity, forward_eligible=True)["status"], "conflict_recorded_no_count")
            self.assertTrue((root / "conflicts" / f"{DECISION}.json").is_file())

    def test_unbound_egs_sidecar_is_rejected_before_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp); stage3, overlay, weekly, receipt, marker, identity = _sources(tmp)
            official = json.loads(marker.read_text(encoding="utf-8")); official["files"].pop("p4_stage3_overlay_score")
            marker.write_text(json.dumps(official), encoding="utf-8")
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value=RUN):
                with self.assertRaisesRegex(OverlayAdjudicationError, "does not bind"):
                    capture_after_published_weekly(root=root, decision_date=DECISION, run_date=RUN,
                        stage3_snapshot_path=stage3, overlay_path=overlay, out_path=weekly, receipt_path=receipt,
                        egs_publish_marker_path=marker, source_identity=identity, forward_eligible=True)

    def test_historical_or_mixed_bundle_cannot_start_a_live_clock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp); stage3, overlay, weekly, receipt, marker, identity = _sources(tmp)
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value="20260730"):
                result = capture_after_published_weekly(root=root, decision_date=DECISION, run_date="20260730",
                    stage3_snapshot_path=stage3, overlay_path=overlay, out_path=weekly, receipt_path=receipt,
                    egs_publish_marker_path=marker, source_identity=identity, forward_eligible=True)
            self.assertEqual(result["status"], "not_live_canonical_no_capture")
            weekly_doc = json.loads(weekly.read_text(encoding="utf-8")); weekly_doc["run_lineage"]["run_id"] = "a-short-20260710-fedcba9876543210"
            weekly.write_text(json.dumps(weekly_doc), encoding="utf-8")
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value=RUN):
                with self.assertRaisesRegex(OverlayAdjudicationError, "run_id"):
                    capture_after_published_weekly(root=root, decision_date=DECISION, run_date=RUN,
                        stage3_snapshot_path=stage3, overlay_path=overlay, out_path=weekly, receipt_path=receipt,
                        egs_publish_marker_path=marker, source_identity=identity, forward_eligible=True)

    def test_marker_sidecars_must_share_the_canonical_bundle_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp); stage3, overlay, weekly, receipt, marker, identity = _sources(tmp)
            foreign = Path(tmp) / "foreign"; foreign.mkdir(); copied = foreign / stage3.name
            copied.write_bytes(stage3.read_bytes())
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value=RUN):
                with self.assertRaisesRegex(OverlayAdjudicationError, "one canonical EGS bundle"):
                    capture_after_published_weekly(root=root, decision_date=DECISION, run_date=RUN,
                        stage3_snapshot_path=copied, overlay_path=overlay, out_path=weekly, receipt_path=receipt,
                        egs_publish_marker_path=marker, source_identity=identity, forward_eligible=True)

    def test_same_members_reordered_are_zero_effect_not_difference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._capture(tmp, members=5)
            capture = json.loads((root / "weeks" / DECISION / "capture.json").read_text(encoding="utf-8"))
            self.assertTrue(capture["payload"]["same_list"])

    def test_active_profile_binding_changes_the_epoch_fingerprint(self) -> None:
        original = _contract_fingerprint()
        binding = _active_profile_binding(); changed = dict(binding); changed["active_profile"] = "test_other_profile"
        with mock.patch("engine.a_short_overlay_adjudication._active_profile_binding", return_value=changed):
            self.assertNotEqual(original, _contract_fingerprint())

    def test_runtime_recipe_change_starts_a_new_epoch_and_excludes_old_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._capture(tmp)
            capture = json.loads((root / "weeks" / DECISION / "capture.json").read_text(encoding="utf-8"))
            codes = sorted({row["ts_code"] for row in capture["payload"]["baseline_selected"] + capture["payload"]["candidate_selected"]})
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value="20260730"):
                settle_from_daily_payload(root=root, daily_payload=_daily(codes), as_of="20260730")
            self.assertEqual(build_public_summary(root=root, as_of="20260730")["eligible_policy_weeks"], 1)
            recipe = _screening_runtime_recipe_binding(); changed = dict(recipe); changed["sha256"] = "b" * 64
            with mock.patch("engine.a_short_overlay_adjudication._screening_runtime_recipe_binding", return_value=changed):
                summary = build_public_summary(root=root, as_of="20260730")
            self.assertEqual(summary["eligible_policy_weeks"], 0)

    def test_capture_rejects_published_stage3_snapshot_from_a_different_runtime_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp); stage3, overlay, weekly, receipt, marker, identity = _sources(tmp)
            recipe = _screening_runtime_recipe_binding(); changed = dict(recipe); changed["sha256"] = "b" * 64
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value=RUN), \
                    mock.patch("engine.a_short_overlay_adjudication._screening_runtime_recipe_binding", return_value=changed):
                with self.assertRaisesRegex(OverlayAdjudicationError, "screening-runtime recipe binding drifted"):
                    capture_after_published_weekly(root=root, decision_date=DECISION, run_date=RUN,
                        stage3_snapshot_path=stage3, overlay_path=overlay, out_path=weekly, receipt_path=receipt,
                        egs_publish_marker_path=marker, source_identity=identity, forward_eligible=True)

    def test_public_summary_reads_one_epoch_context_and_reuses_it(self) -> None:
        with mock.patch("engine.a_short_overlay_adjudication._epoch_context", wraps=_epoch_context) as context:
            summary = build_public_summary(root=None, as_of=DECISION)
        self.assertEqual(context.call_count, 1)
        self.assertEqual(summary["epoch_id"], _epoch_context()["epoch_id"])

    def test_weekly_settlement_and_summary_share_one_epoch_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._capture(tmp)
            capture = json.loads((root / "weeks" / DECISION / "capture.json").read_text(encoding="utf-8"))
            codes = sorted({row["ts_code"] for row in capture["payload"]["baseline_selected"] + capture["payload"]["candidate_selected"]})
            cache = Path(tmp) / "daily_cache.json"; cache.write_text(json.dumps(_daily(codes)), encoding="utf-8")
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value="20260730"), \
                    mock.patch("engine.a_short_overlay_adjudication._epoch_context", wraps=_epoch_context) as context:
                settle_and_summarize_weekly(root=root, daily_cache_path=cache, as_of="20260730",
                                             public_json_path=Path(tmp) / "public.json",
                                             public_markdown_path=Path(tmp) / "public.md")
            self.assertEqual(context.call_count, 1)

    def test_capture_rejects_stage3_profile_that_differs_from_its_epoch_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp); stage3, overlay, weekly, receipt, marker, identity = _sources(tmp)
            context = _epoch_context(); changed = dict(context); profile = dict(context["active_profile_binding"])
            profile["active_profile"] = "test_other_profile"; changed["active_profile_binding"] = profile
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value=RUN), \
                    mock.patch("engine.a_short_overlay_adjudication._epoch_context", return_value=changed):
                with self.assertRaisesRegex(OverlayAdjudicationError, "active-profile binding drifted"):
                    capture_after_published_weekly(root=root, decision_date=DECISION, run_date=RUN,
                        stage3_snapshot_path=stage3, overlay_path=overlay, out_path=weekly, receipt_path=receipt,
                        egs_publish_marker_path=marker, source_identity=identity, forward_eligible=True)

    def test_settlement_rejects_replay_or_noncanonical_shared_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._capture(tmp)
            capture = json.loads((root / "weeks" / DECISION / "capture.json").read_text(encoding="utf-8"))
            codes = sorted({row["ts_code"] for row in capture["payload"]["baseline_selected"] + capture["payload"]["candidate_selected"]})
            cache = _daily(codes); cache["meta"]["writer"] = "untrusted.py"
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value="20260730"):
                with self.assertRaisesRegex(OverlayAdjudicationError, "single-writer"):
                    settle_from_daily_payload(root=root, daily_payload=cache, as_of="20260730")
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value="20260731"):
                with self.assertRaisesRegex(OverlayAdjudicationError, "real current canonical"):
                    settle_from_daily_payload(root=root, daily_payload=_daily(codes), as_of="20260730")

    def test_weekly_settlement_path_cannot_bypass_canonical_cache_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._capture(tmp)
            capture = json.loads((root / "weeks" / DECISION / "capture.json").read_text(encoding="utf-8"))
            codes = sorted({row["ts_code"] for row in capture["payload"]["baseline_selected"] + capture["payload"]["candidate_selected"]})
            arbitrary = Path(tmp) / "hand_built_name.json"
            arbitrary.write_text(json.dumps(_daily(codes)), encoding="utf-8")
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value="20260730"):
                summary = settle_and_summarize_weekly(root=root, daily_cache_path=arbitrary, as_of="20260730",
                                                       public_json_path=Path(tmp) / "public.json",
                                                       public_markdown_path=Path(tmp) / "public.md")
            self.assertEqual(summary["status"], "evidence_unavailable_or_inconclusive")
            self.assertFalse((root / "weeks" / DECISION / "outcome.json").exists())

    def test_terminal_horizon_never_overwrites_and_conflict_is_no_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._capture(tmp)
            capture = json.loads((root / "weeks" / DECISION / "capture.json").read_text(encoding="utf-8"))
            codes = sorted({row["ts_code"] for row in capture["payload"]["baseline_selected"] + capture["payload"]["candidate_selected"]})
            cache = _daily(codes)
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value="20260730"):
                settle_from_daily_payload(root=root, daily_payload=cache, as_of="20260730")
                original = json.loads((root / "weeks" / DECISION / "outcome.json").read_text(encoding="utf-8"))
                for stock in cache["stocks"]:
                    if stock["ts_code"] == "600001.SH" and stock["trade_date"] == "20260720":
                        stock["close"] = 999.0
                for row in cache["rows"]:
                    if row["ts_code"] == "600001.SH" and row["trade_date"] == "20260720":
                        row["close"] = 999.0
                settle_from_daily_payload(root=root, daily_payload=cache, as_of="20260730")
            current = json.loads((root / "weeks" / DECISION / "outcome.json").read_text(encoding="utf-8"))
            self.assertEqual(current, original)
            self.assertTrue((root / "conflicts" / f"{DECISION}.json").is_file())
            summary = build_public_summary(root=root, as_of="20260730")
            self.assertEqual(summary["eligible_policy_weeks"], 0)
            self.assertEqual(summary["no_count_weeks"], 1)

    def test_missing_adjustment_is_no_count_and_p4_is_lowest_cache_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._capture(tmp)
            capture = json.loads((root / "weeks" / DECISION / "capture.json").read_text(encoding="utf-8"))
            codes = sorted({row["ts_code"] for row in capture["payload"]["baseline_selected"] + capture["payload"]["candidate_selected"]})
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value="20260730"):
                settle_from_daily_payload(root=root, daily_payload=_daily(codes, missing_adjustment=True), as_of="20260730")
            summary = build_public_summary(root=root, as_of="20260730")
            self.assertEqual(summary["eligible_policy_weeks"], 0); self.assertEqual(summary["no_count_weeks"], 1)
            self.assertGreater(CONSUMER_PRIORITY["p4_overlay_adjudication"], CONSUMER_PRIORITY["official_operation_evidence"])
            self.assertGreater(CONSUMER_PRIORITY["p4_overlay_adjudication"], CONSUMER_PRIORITY["p5_industry_weight"])

    def test_public_summary_has_no_symbol_price_or_account_surface(self) -> None:
        summary = build_public_summary(root=None, as_of=DECISION); validate_public_summary(summary)
        text = json.dumps(summary).lower()
        for forbidden in ("ts_code", "price", "account", "holding", "private", "selected"):
            self.assertNotIn(forbidden, text)
        self.assertFalse(summary["adjudication"]["automatic_policy_switch"])
        self.assertEqual(set(summary["checkpoints"]), {"12", "24", "36"})
        self.assertEqual(summary["checkpoint_progress"]["12"]["remaining_eligible_weeks"], 12)
        with tempfile.TemporaryDirectory() as tmp:
            markdown = Path(tmp) / "summary.md"
            write_public_summary(summary, json_path=Path(tmp) / "summary.json", markdown_path=markdown)
            rendered = markdown.read_text(encoding="utf-8").lower()
            self.assertIn("checkpoints", rendered)
            self.assertIn("checkpoint_progress", rendered)
            self.assertIn("failing_risk_or_statistical_gates", rendered)
            for forbidden in ("ts_code", "price", "account", "holding", "private", "selected"):
                self.assertNotIn(forbidden, rendered)

    def test_formal_promotion_and_terminal_negative_require_full_risk_contract(self) -> None:
        def row(index: int, *, bad_drawdown: bool = False) -> dict:
            month = index + 1
            decision = f"202{6 + index // 12}{month % 12 or 12:02d}01"
            base = {"entry_date": decision[:-2] + "02", "exit_date": decision[:-2] + "11",
                    "close_drawdown_pct": 0.0, "cash_drag_pct": 0.0, "unfilled_rate_pct": 0.0,
                    "positions": [{"ts_code": f"b{index}", "entry_status": "filled", "net_return_pct": .5}]}
            candidate = {"entry_date": base["entry_date"], "exit_date": base["exit_date"],
                         "close_drawdown_pct": -20.0 if bad_drawdown else 0.0,
                         "cash_drag_pct": 0.0, "unfilled_rate_pct": 0.0,
                         "positions": [{"ts_code": f"c{index}", "entry_status": "filled", "net_return_pct": 1.0}]}
            h10 = {"status": "settled", "delta_pct": .5, "baseline": base, "candidate": candidate,
                   "benchmarks": {"csi1000": {"candidate_excess_pct": .5}, "csi300": {"candidate_excess_pct": .5}}}
            return {"decision_date": decision, "same_list": False, "h5": {"status": "settled", "delta_pct": .5},
                    "h5_complete": True, "h10": h10, "h20": {"status": "settled", "delta_pct": .5}, "h20_complete": True}
        verdict, _ = _adjudicate([row(index) for index in range(24)], 24, 0)
        self.assertEqual(verdict, "candidate_for_manual_promotion")
        verdict, _ = _adjudicate([row(index, bad_drawdown=True) for index in range(36)], 36, 0)
        self.assertEqual(verdict, "do_not_promote")

    def test_missing_h5_benchmark_coverage_cannot_promote(self) -> None:
        def row(index: int) -> dict:
            month = index + 1
            decision = f"202{6 + index // 12}{month % 12 or 12:02d}01"
            arm = {"entry_date": decision[:-2] + "02", "exit_date": decision[:-2] + "11", "close_drawdown_pct": 0.0,
                   "cash_drag_pct": 0.0, "unfilled_rate_pct": 0.0,
                   "positions": [{"ts_code": f"s{index}", "entry_status": "filled", "net_return_pct": 1.0}]}
            return {"decision_date": decision, "same_list": False,
                    "h5": {"status": "no_count", "reason": "benchmark_provider_observed_price_missing"}, "h5_complete": False,
                    "h10": {"status": "settled", "delta_pct": .5, "baseline": arm, "candidate": arm,
                            "benchmarks": {"csi1000": {"candidate_excess_pct": .5}, "csi300": {"candidate_excess_pct": .5}}},
                    "h20": {"status": "settled", "delta_pct": .5}, "h20_complete": True}
        verdict, metrics = _adjudicate([row(index) for index in range(24)], 24, 0)
        self.assertEqual(verdict, "pending_h5_coverage")
        self.assertFalse(metrics["h5_coverage_ok"])

    def test_resampling_uses_nonoverlap_blocks_and_t_is_weekly_cluster_robust(self) -> None:
        def observation(day: str, delta: float) -> dict:
            arm = {"entry_date": day[:-2] + "02", "exit_date": day[:-2] + "20", "close_drawdown_pct": 0.0,
                   "cash_drag_pct": 0.0, "unfilled_rate_pct": 0.0,
                   "positions": [{"ts_code": day, "entry_status": "filled", "net_return_pct": 1.0}]}
            return {"decision_date": day, "same_list": False, "h5": {"status": "settled", "delta_pct": delta},
                    "h5_complete": True,
                    "h10": {"status": "settled", "delta_pct": delta, "baseline": arm, "candidate": arm,
                            "benchmarks": {"csi1000": {"candidate_excess_pct": 0.0}, "csi300": {"candidate_excess_pct": 0.0}}},
                    "h20": {"status": "settled", "delta_pct": delta}, "h20_complete": True}
        rows = [observation("20260101", -1.0), observation("20260102", 1.0)]
        seen = []
        with mock.patch("engine.a_short_overlay_adjudication._bootstrap_bounds", side_effect=lambda values: (seen.append(list(values)) or (0.0, 0.0))):
            _adjudicate(rows, 2, 0)
        self.assertEqual(seen, [[-1.0], [-1.0]])
        clustered_rows = [observation("20260101", 0.0), observation("20260108", 0.0), observation("20260115", 0.0), observation("20260201", 2.0)]
        t_stat, months = _monthly_cluster_t(clustered_rows)
        self.assertEqual(months, 2)
        self.assertAlmostEqual(t_stat, 2.0 / 3.0)

    def test_cash_slots_never_dilute_actual_traded_stock_risk_gates(self) -> None:
        cash_arm = {"entry_date": "20260711", "exit_date": "20260720", "close_drawdown_pct": 0.0,
                    "cash_drag_pct": 0.0, "unfilled_rate_pct": 0.0,
                    "positions": [{"ts_code": "cash", "entry_status": "cash", "net_return_pct": 0.0}]}
        row = {"decision_date": DECISION, "same_list": False, "h5": {"status": "settled", "delta_pct": 0.0},
               "h5_complete": True,
               "h10": {"status": "settled", "delta_pct": 0.0, "baseline": cash_arm, "candidate": cash_arm,
                       "benchmarks": {"csi1000": {"candidate_excess_pct": 0.0}, "csi300": {"candidate_excess_pct": 0.0}}},
               "h20": {"status": "settled", "delta_pct": 0.0}, "h20_complete": True}
        _, metrics = _adjudicate([row], 1, 0)
        self.assertFalse(metrics["risk_ok"])
        self.assertEqual(metrics["reason"], "actual_filled_stock_evidence_unavailable")

    def test_private_record_header_or_mature_outcome_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._capture(tmp)
            capture_path = root / "weeks" / DECISION / "capture.json"
            capture = json.loads(capture_path.read_text(encoding="utf-8"))
            capture["epoch_id"] = "b" * 64
            capture_path.write_text(json.dumps(capture), encoding="utf-8")
            with self.assertRaisesRegex(OverlayAdjudicationError, "record integrity|epoch/header"):
                build_public_summary(root=root, as_of="20260730")

        with tempfile.TemporaryDirectory() as tmp:
            root = self._capture(tmp)
            capture = json.loads((root / "weeks" / DECISION / "capture.json").read_text(encoding="utf-8"))
            codes = sorted({row["ts_code"] for row in capture["payload"]["baseline_selected"] + capture["payload"]["candidate_selected"]})
            with mock.patch("engine.a_short_overlay_adjudication._today", return_value="20260730"):
                settle_from_daily_payload(root=root, daily_payload=_daily(codes), as_of="20260730")
            outcome_path = root / "weeks" / DECISION / "outcome.json"
            outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
            outcome["payload"]["horizons"]["h10"]["delta_pct"] = 99.0
            outcome_path.write_text(json.dumps(outcome), encoding="utf-8")
            with self.assertRaisesRegex(OverlayAdjudicationError, "record integrity"):
                build_public_summary(root=root, as_of="20260730")


if __name__ == "__main__":
    unittest.main()
