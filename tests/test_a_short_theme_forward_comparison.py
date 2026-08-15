"""Local synthetic tests for the audit-only theme field adjudicator."""
from __future__ import annotations

import copy
import contextlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import a_short_evidence_epoch_mode as epoch_mode  # noqa: E402
from engine import a_short_theme_forward_comparison as comparison  # noqa: E402
from runners import a_short_theme_forward_comparison as theme_runner  # noqa: E402
from tests._a_short_epoch_mode_test_utils import _resealed_freeze_packet  # noqa: E402

# Synthetic fixtures intentionally span the full 36-week design window.
def _fixed_test_today():
    return pd.Timestamp("2026-12-31").date()


_fixed_test_today.__module__ = comparison.__name__


def _row(as_of: str, ts_code: str, *, score: float, role: str = "watch", ret: float = 0.0,
         trend: str = "headwind", theme_role: str = "core", primary_theme: str = "physical_ai",
         themes: list[str] | None = None, overheat: bool = False, chasing: bool = False) -> dict:
    themes = themes or [primary_theme]
    as_of_date = pd.Timestamp(as_of)
    entry_date = (as_of_date + pd.Timedelta(days=1)).strftime("%Y%m%d")
    exit_date = (as_of_date + pd.Timedelta(days=14)).strftime("%Y%m%d")
    roles = {theme_id: (theme_role if theme_id == primary_theme else "core") for theme_id in themes}
    row = {
        "as_of": as_of, "captured_at": f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}T15:00:00+08:00",
        "ts_code": ts_code, "run_id": f"run-{as_of}",
        "candidate_digest": f"digest-{as_of}", "analysis_role": role, "final_score": score,
        "decision_as_of": as_of, "run_date": as_of, "price_data_through": as_of,
        "stage3_candidate_count": 10,
        "runtime_configuration_fingerprint": "f" * 64,
        "industry_heat_score": 80.0 if trend == "tailwind" else 20.0,
        "industry_trend": trend, "industry_trend_source_as_of": as_of,
        "industry_trend_classifier_version": "industry_heat_trend_v1",
        "industry_trend_source_id": "A-EGS.industry_heat_score",
        "industry_trend_headwind_max": 20.0, "industry_trend_tailwind_min": 80.0,
        "industry_trend_configuration_fingerprint": "a" * 64,
        "industry_trend_validation_status": "valid",
        "raw_concept_ids": json.dumps(["c1"]),
        "canonical_themes_json": json.dumps([{"theme_id": theme_id, "role": roles[theme_id]} for theme_id in themes]),
        "canonical_theme_ids": json.dumps(themes),
        "primary_canonical_theme_id": primary_theme,
        "canonical_theme_roles": json.dumps(roles),
        "canonical_theme_role_confidence": json.dumps({theme_id: "medium" for theme_id in themes}),
        "theme_taxonomy_configuration_fingerprint": "b" * 64,
        "theme_taxonomy_source_as_of": as_of,
        "theme_taxonomy_l3_provider": "hithink_finance",
        "theme_taxonomy_l3_snapshot_date": as_of,
        "theme_taxonomy_l3_coverage_digest": "c" * 64,
        "theme_taxonomy_l3_coverage_complete": True,
        "theme_taxonomy_l3_scoring_universe": "a_share_main_board",
        "theme_taxonomy_l3_validation_status": "verified_complete",
        "theme_heat_score": 80.0, "theme_breadth_pass": True,
        "theme_persistence_mult": 1.0, "theme_fit_score": 0.8, "theme_fit_pass": True,
        "chasing_high": chasing, "overheat_flag": overheat,
        "forward_live": True, "historical_replay": False,
        "ret_10d_status": "ok", "ret_10d_t1_net": ret,
        "ret_10d_t1_net_unit": "percentage_points",
        "entry_date": entry_date, "ret_10d_exit_date": exit_date,
    }
    return row


def _week(as_of: str, *, winner_return: float = 1.0) -> list[dict]:
    rows = []
    for index in range(5):
        rows.append(_row(as_of, f"600{index:03d}.SH", score=100 - index, role="final", ret=0.0,
                         trend="headwind", theme_role="adjacent"))
    for index in range(5):
        rows.append(_row(as_of, f"000{index:03d}.SZ", score=90 - index, role="watch", ret=winner_return,
                         trend="tailwind", theme_role="core"))
    return rows


def _mutated_matured_primary_as_ofs(_live, _top_n):
    return []


def _mutated_as_bool(_value):
    return False


def _mutated_contract_helper(*_args, **_kwargs):
    return None


class ThemeForwardComparisonTests(unittest.TestCase):
    def setUp(self):
        self._freeze_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._freeze_temp.cleanup)
        self.freeze_packet_path = Path(self._freeze_temp.name) / "freeze_packet.json"
        _resealed_freeze_packet(self.freeze_packet_path)
        freeze_packet = json.loads(
            self.freeze_packet_path.read_text(encoding="utf-8")
        )
        self.freeze_packet_identity = {
            "freeze_id": freeze_packet["freeze_id"],
            "schema_version": freeze_packet["schema_version"],
            "record_sha256": freeze_packet["record_sha256"],
        }
        patcher = mock.patch.object(comparison, "_today_date", _fixed_test_today)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_private_artifact_digest_ignores_runtime_timestamps_but_detects_evidence_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "state" / "a_short" / "theme_forward_comparison_private" / "v1"
            private_root.mkdir(parents=True)
            artifact = private_root / "receipt.json"
            artifact.write_text(json.dumps({
                "evidence": "same",
                "generated_at": "2026-08-15T00:00:00Z",
                "updated_at": "2026-08-15T00:00:00Z",
            }), encoding="utf-8")
            first = theme_runner._private_artifact_digest(private_root)
            artifact.write_text(json.dumps({
                "evidence": "same",
                "generated_at": "2026-08-16T00:00:00Z",
                "updated_at": "2026-08-16T00:00:00Z",
            }), encoding="utf-8")
            timestamp_only = theme_runner._private_artifact_digest(private_root)
            artifact.write_text(json.dumps({
                "evidence": "changed",
                "generated_at": "2026-08-16T00:00:00Z",
                "updated_at": "2026-08-16T00:00:00Z",
            }), encoding="utf-8")
            evidence_changed = theme_runner._private_artifact_digest(private_root)
        self.assertEqual(first, timestamp_only)
        self.assertNotEqual(first, evidence_changed)

    def _build_epoch_at_decision(
        self, tracker: pd.DataFrame, epoch_id: str, start_as_of: str
    ) -> dict:
        with mock.patch.object(
            comparison, "_today_date", return_value=pd.Timestamp(start_as_of).date()
        ):
            return comparison.build_frozen_epoch(
                tracker, epoch_id, start_as_of,
                freeze_packet_identity=self.freeze_packet_identity,
            )

    def _packet(self, weeks: int = 12):
        dates = pd.date_range("2026-01-02", periods=weeks, freq="7D").strftime("%Y%m%d")
        return comparison.evaluate_theme_forward_comparison(pd.DataFrame([row for day in dates for row in _week(day)]))

    def _frozen_registry(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp = tempfile.TemporaryDirectory()
        path = Path(temp.name) / "registry.json"
        modes = {track: "pre_freeze_audit_only" for track in epoch_mode.TRACKS}
        modes[comparison.TRACK_ID] = "frozen_enforced"
        path.write_text(json.dumps({"schema_name": "a_short_evidence_epoch_mode_registry",
                                    "schema_version": "1.0.0",
                                    "design_completion_authorization": {
                                        "status": "authorized",
                                        "directive": "test-only explicit design completion",
                                    },
                                    "track_modes": modes}), encoding="utf-8")
        return temp, path

    @contextlib.contextmanager
    def _frozen_context(self, epoch: dict):
        temp, registry_path = self._frozen_registry()
        epoch_path = Path(temp.name) / "epoch.json"
        epoch_path.write_text(json.dumps(epoch), encoding="utf-8")
        with temp, mock.patch.object(comparison, "EPOCH_PATH", epoch_path), \
                mock.patch.object(epoch_mode, "TRACK_MODE_REGISTRY_PATH", registry_path), \
                mock.patch.object(
                    epoch_mode, "FIFTH_KNIFE_FREEZE_PACKET_PATH",
                    self.freeze_packet_path,
                ):
            yield

    def _frozen_epoch(self, governance: dict, *, themes: list[str] | None = None,
                      decision: dict | None = None) -> dict:
        registry = comparison.load_taxonomy_registry()
        themes = themes or sorted(item["theme_id"] for item in registry["canonical_themes"])
        source = {"industry_trend_configuration_fingerprint": "a" * 64,
                  "theme_taxonomy_configuration_fingerprint": "b" * 64,
                  "runtime_configuration_fingerprint": "f" * 64}
        normalized_decision = copy.deepcopy(decision) if decision else {
            "status": "not_recorded", "as_of": None, "packet_sha256": None,
            "archive_relative_path": None, "receipt_sha256": None,
        }
        normalized_decision.setdefault("archive_relative_path", None)
        normalized_decision.setdefault("receipt_sha256", None)
        if normalized_decision["status"] == "recorded":
            normalized_decision["archive_relative_path"] = (
                normalized_decision["archive_relative_path"] or "epochs/theme-v1/formal_packet.json"
            )
            normalized_decision["receipt_sha256"] = normalized_decision["receipt_sha256"] or "f" * 64
        freeze_packet_identity = self.freeze_packet_identity
        epoch = {
            "schema_name": "a_short_theme_forward_comparison_epoch", "schema_version": "1.4.0",
            "track": "theme_forward_comparison", "mode": "frozen_enforced", "epoch_id": "theme-v1",
            "epoch_start_as_of": "20260102", "governance_fingerprint": comparison._digest(governance),
            "contract_fingerprint": comparison.comparison_contract_fingerprint(
                governance, themes, source, freeze_packet_identity,
            ),
            "freeze_packet_identity": freeze_packet_identity,
            "frozen_theme_ids": themes,
            "taxonomy_registry_fingerprint": comparison._digest(registry),
            "taxonomy_registry_effective_date": registry["effective_date"],
            "source_configuration_fingerprints": source,
            "admission_receipt_manifest": comparison.admission_receipt_manifest({}),
            "outcome_receipt_manifest": comparison.outcome_receipt_manifest({}),
            "formal_decision": normalized_decision,
            "boundary": {"historical_replay_counts_as_forward": False, "automatic_promotion": False,
                         "production_replacement_authorized": False},
        }
        epoch["epoch_identity_fingerprint"] = comparison.epoch_identity_fingerprint(epoch)
        return epoch

    @staticmethod
    def _admission_receipts(tracker: pd.DataFrame, epoch: dict) -> dict[str, dict]:
        live = comparison.validate_tracker_lineage(tracker)
        live = live[
            (live["as_of"].map(str) >= epoch["epoch_start_as_of"])
            & (live[comparison.RETURN_UNIT_COLUMN].map(str) == comparison.RETURN_UNIT)
            & live["analysis_role"].map(str).isin({"final", "watch"})
        ].copy()
        weekly = set(comparison._weekly_latest_as_ofs(list(live["as_of"].map(str))))
        live = live[live["as_of"].map(str).isin(weekly)]
        top_n = int(comparison.load_governance()["policy"]["top_n"])
        receipts = {}
        for as_of, cohort in live.groupby("as_of", dropna=False):
            decision_cohort = cohort.copy()
            decision_cohort[comparison.RETURN_STATUS_COLUMN] = "pending_capture"
            decision_cohort[comparison.RETURN_COLUMN] = pd.NA
            with mock.patch.object(
                comparison, "_today_date", return_value=pd.Timestamp(str(as_of)).date()
            ):
                receipt = comparison.build_cohort_admission_receipt(
                    decision_cohort, epoch, top_n
                )
            if receipt is not None:
                receipts[str(as_of)] = receipt
        epoch["admission_receipt_manifest"] = comparison.admission_receipt_manifest(receipts)
        return receipts

    @staticmethod
    def _outcome_receipts(
        tracker: pd.DataFrame, epoch: dict, admissions: dict[str, dict]
    ) -> dict[str, dict]:
        live = comparison.validate_tracker_lineage(tracker)
        weekly = set(comparison._weekly_latest_as_ofs(list(live["as_of"].map(str))))
        live = live[live["as_of"].map(str).isin(weekly)]
        top_n = int(comparison.load_governance()["policy"]["top_n"])
        receipts = {}
        for as_of, cohort in live.groupby("as_of", dropna=False):
            receipt = comparison.build_terminal_outcome_receipt(
                cohort, epoch, top_n, admission_receipt=admissions.get(str(as_of))
            )
            if receipt is not None:
                receipts[str(as_of)] = receipt
        epoch["outcome_receipt_manifest"] = comparison.outcome_receipt_manifest(receipts)
        return receipts

    @classmethod
    def _frozen_evaluate(cls, tracker: pd.DataFrame, epoch: dict) -> dict:
        formal = None
        recorded_packet = None
        if epoch["formal_decision"]["status"] == "recorded":
            decision = epoch["formal_decision"]
            decision["archive_relative_path"] = (
                decision.get("archive_relative_path") or f"epochs/{epoch['epoch_id']}/formal_packet.json"
            )
            formal = comparison.build_formal_decision_receipt(
                epoch, decision["as_of"], decision["packet_sha256"], decision["archive_relative_path"]
            )
            decision["receipt_sha256"] = formal["record_sha256"]
        admissions = cls._admission_receipts(tracker, epoch)
        receipts = cls._outcome_receipts(tracker, epoch, admissions)
        if formal is not None:
            open_epoch = copy.deepcopy(epoch)
            open_epoch["formal_decision"] = {
                "status": "not_recorded", "as_of": None, "packet_sha256": None,
                "archive_relative_path": None, "receipt_sha256": None,
            }
            comparison.EPOCH_PATH.write_text(json.dumps(open_epoch), encoding="utf-8")
            recorded_packet = comparison.evaluate_theme_forward_comparison(
                tracker,
                admission_receipts=admissions,
                outcome_receipts=receipts,
            )
        comparison.EPOCH_PATH.write_text(json.dumps(epoch), encoding="utf-8")
        return comparison.evaluate_theme_forward_comparison(
            tracker,
            admission_receipts=admissions,
            outcome_receipts=receipts,
            formal_decision_receipt=formal,
            recorded_formal_packet=recorded_packet,
        )

    def test_audit_only_has_seven_frozen_policies_and_never_authorizes_activation(self):
        packet = self._packet()
        self.assertEqual(packet["adjudication_mode"], "audit_only_pre_freeze")
        self.assertFalse(packet["formal_verdict_allowed"])
        self.assertEqual([row["criterion_id"] for row in packet["criteria"]], [
            "industry_trend", "business_role", "industry_heat", "persistence",
            "theme_breadth_pass", "theme_fit_pass", "theme_heat",
        ])
        self.assertTrue(all(row["adjudication"]["verdict"] == "audit_only_pre_freeze" for row in packet["criteria"]))
        self.assertEqual(packet["epoch_clock_weeks"], 0)
        self.assertFalse(packet["receipt"]["production_replacement_recommendation"])
        self.assertFalse(packet["comparison_boundary"]["activation_authorized"])

    def test_unit_and_margin_are_percentage_points_not_return_ratios(self):
        governance = comparison.load_governance()
        self.assertEqual(comparison.RETURN_UNIT, "percentage_points")
        self.assertEqual(governance["policy"]["return_unit"], "percentage_points")
        self.assertEqual(governance["policy"]["practical_margin_pp"], 0.25)

    def test_packet_keeps_predictive_and_policy_layers_separate(self):
        packet = self._packet(1)
        criterion = packet["criteria"][0]
        self.assertIn("predictive_discrimination", criterion)
        self.assertIn("policy_vs_primary", criterion)
        self.assertIsNot(criterion["predictive_discrimination"], criterion["policy_vs_primary"])

    def test_cash_slots_remain_in_policy_return_and_are_not_dropped(self):
        rows = [_row("20260102", f"600{index:03d}.SH", score=100 - index, role="final", ret=0.0,
                     trend="headwind", theme_role="adjacent") for index in range(5)]
        rows.append(_row("20260102", "000001.SZ", score=99.0, role="watch", ret=1.0,
                         trend="tailwind", theme_role="core"))
        rows.extend(_row("20260102", f"300{index:03d}.SZ", score=50 - index, role="watch", ret=0.0,
                         trend="headwind", theme_role="adjacent") for index in range(4))
        packet = comparison.evaluate_theme_forward_comparison(pd.DataFrame(rows))
        trend = next(row for row in packet["criteria"] if row["criterion_id"] == "industry_trend")
        self.assertEqual(trend["coverage"]["average_selected_positions"], 1.0)
        self.assertEqual(trend["nonoverlap_h10_blocks"]["mean_delta_pp"], 0.2)
        self.assertFalse(trend["coverage"]["deployable"])

    def test_unbuyable_selected_candidates_are_cash_and_not_deployable(self):
        rows = _week("20260102", winner_return=2.0)
        for row in rows:
            if row["analysis_role"] == "watch":
                row["ret_10d_status"] = "pending_no_entry_limit_up"
                row["ret_10d_t1_net"] = pd.NA
        packet = comparison.evaluate_theme_forward_comparison(pd.DataFrame(rows))
        trend = next(row for row in packet["criteria"] if row["criterion_id"] == "industry_trend")
        self.assertEqual(
            trend["weekly_selection_summary"]["all_eligible_week_average_selected_candidates"], 5.0
        )
        self.assertEqual(trend["coverage"]["average_selected_positions"], 0.0)
        self.assertEqual(trend["coverage"]["cash_slot_rate"], 1.0)
        self.assertFalse(trend["coverage"]["deployable"])

    def test_missing_primary_top5_is_not_a_zero_return_baseline(self):
        rows = _week("20260102", winner_return=2.0)
        for row in rows:
            if row["analysis_role"] == "final":
                row["analysis_role"] = "watch"
        week = comparison._policy_week(
            rows,
            comparison._criterion_predicate(comparison.load_governance()["criteria"][0]),
            5,
        )
        self.assertIsNone(week["primary_return"])
        self.assertEqual(week["primary_status"], "primary_baseline_unavailable:0/5")
        self.assertIsNone(week["delta"])

    def test_historical_replay_float_is_excluded_from_forward_evidence(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker["historical_replay"] = 1.0
        tracker["forward_live"] = 0.0
        packet = comparison.evaluate_theme_forward_comparison(tracker)
        self.assertEqual(packet["forward_live_rows_counted"], 0)
        self.assertEqual(packet["excluded_non_live_or_replay_rows"], len(tracker))

    def test_business_role_missing_primary_only_removes_challenger(self):
        rows = _week("20260102")
        rows[-1]["primary_canonical_theme_id"] = ""
        business_spec = next(
            item for item in comparison.load_governance()["criteria"]
            if item["criterion_id"] == "business_role"
        )
        week = comparison._policy_week(
            rows,
            comparison._criterion_predicate(business_spec),
            5,
            lambda row: bool(str(row.get("primary_canonical_theme_id") or "").strip()),
        )
        self.assertEqual(week["primary_selected_count"], 5)
        self.assertEqual(week["challenger_selected_count"], 4)
        self.assertIsNotNone(week["primary_return"])

    def test_negative_control_with_no_positive_observations_is_not_validated(self):
        live = pd.DataFrame(_week("20260102"))
        control = comparison._negative_control(live, comparison.load_governance()["policy"], 8)
        self.assertEqual(control["predictive_discrimination"]["positive_stock_observations"], 0)
        self.assertEqual(control["method_validity_status"], "not_assessable_zero_observation")

    def test_daily_matured_cohorts_consume_one_clock_slot_per_iso_week(self):
        dates = pd.date_range("20260102", periods=36, freq="D").strftime("%Y%m%d")
        self.assertEqual(len(comparison._weekly_matured_as_ofs(list(dates))), 6)
        self.assertLess(len(comparison._weekly_matured_as_ofs(list(dates))), len(dates))
        self.assertEqual(len(comparison._weekly_latest_as_ofs(list(dates))), 6)

    def test_realized_h10_intervals_not_calendar_spacing_define_independent_blocks(self):
        values = [
            ("20260105", "20260130", 1.0),
            ("20260123", "20260206", 2.0),
            ("20260209", "20260220", 3.0),
        ]
        self.assertEqual(comparison._nonoverlap_blocks(values), [1.0, 3.0])

    def test_friday_capture_for_monday_decision_is_legal_but_not_counted_early(self):
        rows = _week("20260727")
        for row in rows:
            row["run_date"] = "20260724"
            row["price_data_through"] = "20260724"
            row["captured_at"] = "2026-07-24T15:00:00+08:00"
            row["industry_trend_source_as_of"] = "20260724"
            row["theme_taxonomy_source_as_of"] = "20260724"
            row["theme_taxonomy_l3_snapshot_date"] = "20260724"
        with mock.patch.object(comparison, "_today_date", return_value=pd.Timestamp("2026-07-26").date()):
            live = comparison.validate_tracker_lineage(pd.DataFrame(rows))
            eligible, rejected = comparison.eligible_formal_cohorts(live, 5)
        self.assertTrue(eligible.empty)
        self.assertEqual(rejected["20260727"], "decision_not_effective_yet")

    def test_friday_capture_can_be_admitted_before_monday_but_not_counted(self):
        rows = _week("20260727")
        for row in rows:
            row["run_date"] = "20260724"
            row["price_data_through"] = "20260724"
            row["captured_at"] = "2026-07-24T15:00:00+08:00"
            row["industry_trend_source_as_of"] = "20260724"
            row["theme_taxonomy_source_as_of"] = "20260724"
            row["theme_taxonomy_l3_snapshot_date"] = "20260724"
            row["ret_10d_status"] = "pending_capture"
            row["ret_10d_t1_net"] = pd.NA
        tracker = pd.DataFrame(rows)
        with mock.patch.object(comparison, "_today_date", return_value=pd.Timestamp("2026-07-24").date()):
            epoch = comparison.build_frozen_epoch(
                tracker, "theme-v1", "20260727",
                freeze_packet_identity=self.freeze_packet_identity,
            )
            receipt = comparison.build_cohort_admission_receipt(tracker, epoch, 5)
            eligible, rejected = comparison.eligible_formal_cohorts(
                comparison.validate_tracker_lineage(tracker), 5
            )
        self.assertIsNotNone(receipt)
        self.assertTrue(eligible.empty)
        self.assertEqual(rejected["20260727"], "decision_not_effective_yet")
        epoch["admission_receipt_manifest"] = comparison.admission_receipt_manifest(
            {"20260727": receipt}
        )
        with self._frozen_context(epoch), mock.patch.object(
            comparison, "_today_date", return_value=pd.Timestamp("2026-07-24").date()
        ):
            packet = comparison.evaluate_theme_forward_comparison(
                tracker, admission_receipts={"20260727": receipt}
            )
        self.assertEqual(packet["adjudication_mode"], "frozen_counting")
        self.assertEqual(packet["epoch_clock_weeks"], 0)

    def test_0810_theme_snapshot_is_not_bound_to_friday_price_clock(self):
        rows = _week("20260810")
        for row in rows:
            row["run_date"] = "20260810"
            row["price_data_through"] = "20260807"
            row["industry_trend_source_as_of"] = "20260807"
            row["theme_taxonomy_source_as_of"] = "20260810"
            row["theme_taxonomy_l3_snapshot_date"] = "20260810"
        with mock.patch.object(
            comparison, "_today_date", return_value=pd.Timestamp("2026-08-11").date()
        ):
            live = comparison.validate_tracker_lineage(pd.DataFrame(rows))
            eligible, rejected = comparison.eligible_formal_cohorts(live, 5)
        self.assertEqual(set(eligible["as_of"]), {"20260810"})
        self.assertEqual(rejected, {})

    def test_theme_source_must_match_snapshot_and_snapshot_must_not_exceed_run(self):
        rows = _week("20260810")
        for row in rows:
            row["run_date"] = "20260807"
            row["price_data_through"] = "20260807"
            row["captured_at"] = "2026-08-07T15:00:00+08:00"
            row["industry_trend_source_as_of"] = "20260807"
            row["theme_taxonomy_source_as_of"] = "20260810"
            row["theme_taxonomy_l3_snapshot_date"] = "20260810"
        with mock.patch.object(
            comparison, "_today_date", return_value=pd.Timestamp("2026-08-11").date()
        ):
            live = comparison.validate_tracker_lineage(pd.DataFrame(rows))
            eligible, rejected = comparison.eligible_formal_cohorts(live, 5)
        self.assertTrue(eligible.empty)
        self.assertIn("invalid taxonomy L3 snapshot date", rejected["20260810"])

        rows = _week("20260810")
        for row in rows:
            row["run_date"] = "20260810"
            row["price_data_through"] = "20260807"
            row["industry_trend_source_as_of"] = "20260807"
            row["theme_taxonomy_source_as_of"] = "20260810"
            row["theme_taxonomy_l3_snapshot_date"] = "20260807"
        with mock.patch.object(
            comparison, "_today_date", return_value=pd.Timestamp("2026-08-11").date()
        ):
            live = comparison.validate_tracker_lineage(pd.DataFrame(rows))
            eligible, rejected = comparison.eligible_formal_cohorts(live, 5)
        self.assertTrue(eligible.empty)
        self.assertEqual(rejected["20260810"], "theme_taxonomy_source_clock_mismatch")

    def test_weekend_theme_snapshot_is_admissible_only_after_monday_effective(self):
        rows = _week("20260727")
        for row in rows:
            row["run_date"] = "20260726"
            row["price_data_through"] = "20260724"
            row["captured_at"] = "2026-07-26T15:00:00+08:00"
            row["industry_trend_source_as_of"] = "20260724"
            row["theme_taxonomy_source_as_of"] = "20260726"
            row["theme_taxonomy_l3_snapshot_date"] = "20260726"
        with mock.patch.object(
            comparison, "_today_date", return_value=pd.Timestamp("2026-07-27").date()
        ):
            live = comparison.validate_tracker_lineage(pd.DataFrame(rows))
            eligible, rejected = comparison.eligible_formal_cohorts(live, 5)
        self.assertEqual(set(eligible["as_of"]), {"20260727"})
        self.assertEqual(rejected, {})

    def test_pending_tracker_cannot_be_first_admitted_after_bounded_recovery_window(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker["ret_10d_status"] = "pending_capture"
        tracker["ret_10d_t1_net"] = pd.NA
        epoch = self._frozen_epoch(comparison.load_governance())
        with mock.patch.object(
            comparison, "_today_date", return_value=pd.Timestamp("20260106").date()
        ):
            receipt = comparison.build_cohort_admission_receipt(tracker, epoch, 5)
        self.assertIsNone(receipt)

    def test_admission_receipt_validates_creation_deadline_without_rejecting_later_settlement(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker["ret_10d_status"] = "pending_capture"
        tracker["ret_10d_t1_net"] = pd.NA
        epoch = self._build_epoch_at_decision(tracker, "theme-v1", "20260102")
        with mock.patch.object(comparison, "_today_date", return_value=pd.Timestamp("20260103").date()):
            receipt = comparison.build_cohort_admission_receipt(tracker, epoch, 5)
        self.assertIsNotNone(receipt)
        tracker["ret_10d_status"] = "ok"
        tracker["ret_10d_t1_net"] = 1.0
        comparison.validate_cohort_admission_receipt(receipt, tracker, epoch, 5)
        forged = dict(receipt)
        forged["admission_recorded_on"] = "20260106"
        forged["record_sha256"] = comparison._digest({
            key: value for key, value in forged.items() if key != "record_sha256"
        })
        with self.assertRaisesRegex(comparison.ThemeForwardComparisonError, "eligible"):
            comparison.validate_cohort_admission_receipt(forged, tracker, epoch, 5)

    def test_local_backdated_admission_is_explicitly_unverifiable_without_an_external_anchor(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker["ret_10d_status"] = "pending_capture"
        tracker["ret_10d_t1_net"] = pd.NA
        epoch = self._build_epoch_at_decision(tracker, "theme-v1", "20260102")
        with mock.patch.object(comparison, "_today_date", return_value=pd.Timestamp("20260103").date()):
            genuine = comparison.build_cohort_admission_receipt(tracker, epoch, 5)
        self.assertIsNotNone(genuine)
        tracker["ret_10d_status"] = "ok"
        tracker["ret_10d_t1_net"] = 1.0
        with mock.patch.object(comparison, "_today_date", return_value=pd.Timestamp("20260103").date()):
            self.assertIsNone(comparison.build_cohort_admission_receipt(tracker, epoch, 5))
        reconstructed = comparison.build_cohort_admission_receipt(
            comparison._decision_time_projection(tracker), epoch, 5,
            admission_date=pd.Timestamp("20260103").date(),
        )
        self.assertEqual(reconstructed, genuine)
        comparison.validate_cohort_admission_receipt(reconstructed, tracker, epoch, 5)
        self.assertEqual(
            reconstructed["admission_time_provenance"],
            "local_private_receipt_not_independently_timestamped",
        )
        self.assertNotIn("admission_outcome_state_sha256", reconstructed)

    def test_coverage_is_derived_from_the_same_blocks_as_statistics(self):
        dates = pd.date_range("2026-01-02", periods=8, freq="7D").strftime("%Y%m%d")
        rows = [row for day in dates for row in _week(day)]
        tracker = pd.DataFrame(rows)
        # The non-overlap selector keeps alternate weeks.  Make only those blocks
        # cash-heavy; all-week coverage must not hide them.
        for day in dates[::2]:
            mask = (tracker["as_of"] == day) & (tracker["analysis_role"] == "watch")
            tracker.loc[mask & tracker["ts_code"].ne("000000.SZ"), "ret_10d_status"] = "pending_no_entry_limit_up"
        live = comparison.validate_tracker_lineage(tracker)
        result = comparison._policy_result(
            live, comparison.load_governance()["criteria"][0], comparison.load_governance()["policy"], 0,
        )
        coverage = result["coverage"]
        self.assertEqual(coverage["evidence_block_count"], result["nonoverlap_h10_blocks"]["block_count"])
        self.assertEqual(len(coverage["evidence_block_as_ofs"]), coverage["evidence_block_count"])
        self.assertEqual(
            [item["as_of"] for item in coverage["counted_block_execution_profile"]],
            coverage["evidence_block_as_ofs"],
        )
        self.assertTrue(all(
            item["challenger_executed_positions"] + item["challenger_cash_slots"] == 5
            for item in coverage["counted_block_execution_profile"]
        ))
        self.assertLess(coverage["minimum_observed_counted_block_positions"], 3)
        self.assertFalse(coverage["deployable"])

    def test_atomic_cohort_rejects_one_dropped_stage3_row(self):
        tracker = pd.DataFrame(_week("20260102")[:-1])
        live = comparison.validate_tracker_lineage(tracker)
        eligible, rejected = comparison.eligible_formal_cohorts(live, 5)
        self.assertTrue(eligible.empty)
        self.assertEqual(rejected["20260102"], "stage3_candidate_count_mismatch")

    def test_atomic_cohort_rejects_nonfinite_watch_score(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker.loc[tracker["analysis_role"] == "watch", "final_score"] = float("nan")
        eligible, rejected = comparison.eligible_formal_cohorts(
            comparison.validate_tracker_lineage(tracker), 5
        )
        self.assertTrue(eligible.empty)
        self.assertEqual(rejected["20260102"], "nonfinite_stage3_final_score")

    def test_atomic_cohort_rejects_inconsistent_theme_truths(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker.loc[tracker.index[-1], "canonical_theme_roles"] = json.dumps(
            {"physical_ai": "adjacent"}
        )
        eligible, rejected = comparison.eligible_formal_cohorts(
            comparison.validate_tracker_lineage(tracker), 5
        )
        self.assertTrue(eligible.empty)
        self.assertEqual(
            rejected["20260102"], "inconsistent_theme_identity_or_role"
        )

    def test_atomic_cohort_rejects_missing_policy_input(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker.loc[tracker.index[-1], "theme_heat_score"] = pd.NA
        eligible, rejected = comparison.eligible_formal_cohorts(
            comparison.validate_tracker_lineage(tracker), 5
        )
        self.assertTrue(eligible.empty)
        self.assertEqual(rejected["20260102"], "invalid_theme_heat_score")

    def test_terminal_outcome_without_realized_interval_never_gets_a_receipt(self):
        tracker = pd.DataFrame(_week("20260102"))
        epoch = self._frozen_epoch(comparison.load_governance())
        tracker["ret_10d_exit_date"] = pd.NA
        self.assertIsNone(comparison.build_terminal_outcome_receipt(tracker, epoch, 5))

    def test_one_missing_realized_interval_row_never_gets_a_receipt(self):
        tracker = pd.DataFrame(_week("20260102"))
        epoch = self._frozen_epoch(comparison.load_governance())
        admissions = self._admission_receipts(tracker, epoch)
        tracker.loc[tracker.index[-1], "ret_10d_exit_date"] = pd.NA
        self.assertIsNone(comparison.build_terminal_outcome_receipt(
            tracker, epoch, 5, admission_receipt=admissions["20260102"]
        ))

    def test_both_blank_forward_flags_are_legacy_diagnostic_only(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker["forward_live"] = pd.NA
        tracker["historical_replay"] = pd.NA
        self.assertTrue(comparison.validate_tracker_lineage(tracker).empty)

    def test_one_missing_forward_flag_fails_closed(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker["historical_replay"] = pd.NA
        with self.assertRaisesRegex(comparison.ThemeForwardComparisonError, "must both be present"):
            comparison.validate_tracker_lineage(tracker)

    def test_as_of_later_than_capture_is_rejected(self):
        row = _row("20260102", "000001.SZ", score=1.0)
        row["captured_at"] = "2026-01-01T15:00:00+08:00"
        with self.assertRaisesRegex(comparison.ThemeForwardComparisonError, "clock order"):
            comparison.validate_tracker_lineage(pd.DataFrame([row]))

    def test_future_as_of_is_rejected_even_when_capture_timestamp_is_also_future(self):
        row = _row("20991231", "000001.SZ", score=1.0)
        row["captured_at"] = "2099-12-31T15:00:00+08:00"
        with self.assertRaisesRegex(comparison.ThemeForwardComparisonError, "future"):
            comparison.validate_tracker_lineage(pd.DataFrame([row]))

    def test_wrong_return_unit_is_rejected_instead_of_silently_rescaled(self):
        row = _row("20260102", "000001.SZ", score=1.0)
        row["ret_10d_t1_net_unit"] = "ratio"
        with self.assertRaisesRegex(comparison.ThemeForwardComparisonError, "return-unit mismatch"):
            comparison.validate_tracker_lineage(pd.DataFrame([row]))

    def test_legacy_missing_analysis_role_is_excluded_not_reinterpreted(self):
        tracker = pd.DataFrame(_week("20260102")).drop(columns=["analysis_role"])
        packet = comparison.evaluate_theme_forward_comparison(tracker)
        self.assertEqual(packet["excluded_legacy_missing_analysis_role_rows"], 10)
        self.assertEqual(packet["criteria"][0]["matured_paired_week_count"], 0)

    def test_business_role_uses_only_primary_theme_and_never_double_counts(self):
        rows = _week("20260102")
        for row in rows[5:]:
            row["canonical_theme_roles"] = json.dumps({"physical_ai": "adjacent"})
            row["canonical_themes_json"] = json.dumps([
                {"theme_id": "physical_ai", "role": "adjacent"}
            ])
        rows[5]["canonical_theme_ids"] = json.dumps(["physical_ai", "robotics"])
        rows[5]["canonical_theme_roles"] = json.dumps({"physical_ai": "core", "robotics": "core"})
        rows[5]["canonical_themes_json"] = json.dumps([
            {"theme_id": "physical_ai", "role": "core"},
            {"theme_id": "robotics", "role": "core"},
        ])
        packet = comparison.evaluate_theme_forward_comparison(pd.DataFrame(rows))
        business = next(row for row in packet["criteria"] if row["criterion_id"] == "business_role")
        self.assertEqual(business["coverage"]["average_selected_positions"], 1.0)
        self.assertEqual(business["excluded_missing_primary_canonical_theme_id_rows"], 0)
        self.assertEqual(len(packet["exploratory_themes"]), 2)

    def test_business_role_excludes_rows_without_primary_theme_from_both_arms(self):
        rows = _week("20260102")
        rows[-1]["primary_canonical_theme_id"] = ""
        packet = comparison.evaluate_theme_forward_comparison(pd.DataFrame(rows))
        business = next(row for row in packet["criteria"] if row["criterion_id"] == "business_role")
        self.assertEqual(business["excluded_missing_primary_canonical_theme_id_rows"], 1)
        self.assertEqual(business["coverage"]["average_selected_positions"], 4.0)

    def test_frozen_epoch_can_support_a_field_only_after_holm_and_capacity_gates(self):
        dates = pd.date_range("2026-01-02", periods=36, freq="7D").strftime("%Y%m%d")
        tracker = pd.DataFrame([row for day in dates for row in _week(day)])
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance)
        with self._frozen_context(epoch):
            packet = self._frozen_evaluate(tracker, epoch)
            self.assertTrue(epoch_mode.enforcement_enabled(comparison.TRACK_ID))
            self.assertFalse(epoch_mode.enforcement_enabled("p4a_overlay_adjudication"))
        trend = next(row for row in packet["criteria"] if row["criterion_id"] == "industry_trend")
        self.assertTrue(packet["formal_verdict_allowed"])
        self.assertEqual(trend["adjudication"]["verdict"], "supported")
        self.assertLessEqual(trend["adjudication"]["holm_adjusted_two_sided_practical_p"], 0.025)

    def test_frozen_contract_drift_stops_clock_and_rejects_formal_verdict(self):
        tracker = pd.DataFrame([row for row in _week("20260102")])
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance, themes=["tampered_theme"])
        epoch["contract_fingerprint"] = comparison.comparison_contract_fingerprint(
            governance, ["physical_ai"], epoch["source_configuration_fingerprints"]
        )
        epoch["epoch_identity_fingerprint"] = comparison.epoch_identity_fingerprint(epoch)
        with self._frozen_context(epoch):
            packet = self._frozen_evaluate(tracker, epoch)
        self.assertEqual(packet["adjudication_mode"], "epoch_contract_mismatch")
        self.assertFalse(packet["formal_verdict_allowed"])
        self.assertEqual(packet["epoch_clock_weeks"], 0)
        self.assertEqual(packet["checkpoints"]["current_checkpoint"], "epoch_contract_mismatch")

    def test_maturity_semantic_change_is_bound_to_the_frozen_contract(self):
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance)
        with self._frozen_context(epoch), \
                mock.patch.object(comparison, "_matured_primary_as_ofs", _mutated_matured_primary_as_ofs):
            tracker = pd.DataFrame(_week("20260102"))
            packet = self._frozen_evaluate(tracker, epoch)
        self.assertEqual(packet["adjudication_mode"], "epoch_contract_mismatch")

    def test_row_admission_helper_and_column_contract_are_fingerprint_bound(self):
        governance = comparison.load_governance()
        baseline = comparison.comparison_contract_fingerprint(governance, ["physical_ai"], {
            "industry_trend_configuration_fingerprint": "a" * 64,
            "theme_taxonomy_configuration_fingerprint": "b" * 64,
        })
        with mock.patch.object(comparison, "_as_bool", _mutated_as_bool):
            helper_drift = comparison.comparison_contract_fingerprint(governance, ["physical_ai"], {
                "industry_trend_configuration_fingerprint": "a" * 64,
                "theme_taxonomy_configuration_fingerprint": "b" * 64,
            })
        with mock.patch.object(comparison, "REQUIRED_COLUMNS", comparison.REQUIRED_COLUMNS | {"new_admission_field"}):
            column_drift = comparison.comparison_contract_fingerprint(governance, ["physical_ai"], {
                "industry_trend_configuration_fingerprint": "a" * 64,
                "theme_taxonomy_configuration_fingerprint": "b" * 64,
            })
        self.assertNotEqual(helper_drift, baseline)
        self.assertNotEqual(column_drift, baseline)

    def test_every_previously_unbound_engine_helper_is_fingerprint_bound(self):
        governance = comparison.load_governance()
        source = {
            "industry_trend_configuration_fingerprint": "a" * 64,
            "theme_taxonomy_configuration_fingerprint": "b" * 64,
        }
        baseline = comparison.comparison_contract_fingerprint(governance, ["physical_ai"], source)
        for name in (
            "_today_date", "_predictive_summary", "_theme_groups", "_canonical_receipt_value",
            "_seal_private_receipt", "_validate_private_receipt_seal", "load_epoch",
        ):
            with self.subTest(name=name), mock.patch.object(comparison, name, _mutated_contract_helper):
                self.assertNotEqual(
                    comparison.comparison_contract_fingerprint(governance, ["physical_ai"], source),
                    baseline,
                )

    def test_contract_constant_semantics_binds_every_module_constant_by_default(self):
        """Constants bind by default, in the same AST polarity as external files.

        The three that used to escape the hand-written list are the point:
        `ADMISSION_TIME_PROVENANCE` (the trust-boundary label stamped on every
        receipt), `CONTRACT_FUNCTION_SEMANTICS_EXCLUSIONS` (which decides what
        else is bound) and `RUNTIME_CONFIGURATION_FINGERPRINT_COLUMN`.
        """
        source = Path(comparison.__file__).read_text(encoding="utf-8")
        tree = comparison.ast.parse(source)
        declared = set()
        for node in tree.body:
            if not isinstance(node, (comparison.ast.Assign, comparison.ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, comparison.ast.Assign) else [node.target]
            declared |= {
                target.id for target in targets
                if isinstance(target, comparison.ast.Name) and target.id.isupper()
            }
        bound = comparison._contract_constant_semantics()
        self.assertEqual(set(bound), declared, "a module constant escaped the contract")
        for name in ("ADMISSION_TIME_PROVENANCE", "CONTRACT_FUNCTION_SEMANTICS_EXCLUSIONS",
                     "RUNTIME_CONFIGURATION_FINGERPRINT_COLUMN", "GOVERNANCE_PATH"):
            self.assertIn(name, bound)

    def test_constant_contract_ignores_prose_but_moves_on_a_value_change(self):
        """Two-directional control for the constant leg, mirroring the function leg."""
        source = Path(comparison.__file__).read_text(encoding="utf-8")
        baseline = comparison._contract_constant_semantics()

        def contract_from(text):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "variant.py"
                path.write_text(text, encoding="utf-8")
                with mock.patch.object(comparison, "__file__", str(path)):
                    return comparison._contract_constant_semantics()

        commented = source.replace(
            "ADMISSION_TIME_PROVENANCE = ",
            "# simulated comment-only edit\nADMISSION_TIME_PROVENANCE = ", 1)
        self.assertNotEqual(commented, source)
        self.assertEqual(contract_from(commented), baseline,
                         "a comment moved the constant contract")

        revalued = source.replace(
            'ADMISSION_TIME_PROVENANCE = "local_private_receipt_not_independently_timestamped"',
            'ADMISSION_TIME_PROVENANCE = "independently_timestamped"', 1)
        self.assertNotEqual(revalued, source)
        self.assertNotEqual(contract_from(revalued), baseline,
                            "re-labelling the trust boundary did not move the contract")

        repointed = source.replace(
            'GOVERNANCE_PATH = ROOT / "presets"', 'GOVERNANCE_PATH = ROOT / "other"', 1)
        self.assertNotEqual(repointed, source)
        self.assertNotEqual(contract_from(repointed), baseline,
                            "re-pointing a path constant did not move the contract")

    def test_contract_function_semantics_exemptions_are_exact_and_exhaustive(self):
        self.assertEqual(
            comparison.CONTRACT_FUNCTION_SEMANTICS_EXCLUSIONS,
            frozenset({"_semantic_function_digest", "_strip_docstrings", "_contract_function_semantics"}),
        )
        local_functions = {
            name for name, value in vars(comparison).items()
            if comparison.inspect.isfunction(value) and value.__module__ == comparison.__name__
        }
        self.assertEqual(
            set(comparison._contract_function_semantics()),
            local_functions - comparison.CONTRACT_FUNCTION_SEMANTICS_EXCLUSIONS,
        )

    def test_return_and_tracker_producer_semantics_are_fingerprint_bound(self):
        governance = comparison.load_governance()
        source = {
            "industry_trend_configuration_fingerprint": "a" * 64,
            "theme_taxonomy_configuration_fingerprint": "b" * 64,
        }
        baseline = comparison.comparison_contract_fingerprint(governance, ["physical_ai"], source)
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            backtest_path = temp_root / "backtest_rank.py"
            backtest_path.write_text(
                comparison.BACKTEST_RANK_PATH.read_text(encoding="utf-8").replace(
                    "DEFAULT_COST_PCT = 0.16", "DEFAULT_COST_PCT = 0.99", 1
                ),
                encoding="utf-8",
            )
            with mock.patch.object(comparison, "BACKTEST_RANK_PATH", backtest_path):
                self.assertNotEqual(
                    comparison.comparison_contract_fingerprint(governance, ["physical_ai"], source),
                    baseline,
                )

            tracker_path = temp_root / "forward_tracker.py"
            tracker_path.write_text(
                comparison.FORWARD_TRACKER_PATH.read_text(encoding="utf-8").replace(
                    '    "ok",', '    "changed_ok",', 1
                ),
                encoding="utf-8",
            )
            with mock.patch.object(comparison, "FORWARD_TRACKER_PATH", tracker_path):
                self.assertNotEqual(
                    comparison.comparison_contract_fingerprint(governance, ["physical_ai"], source),
                    baseline,
                )

    def test_semantic_file_contract_binds_referenced_constants_without_opt_in_listing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "producer.py"
            path.write_text(
                "RESULT_LIMIT = 3\n\ndef choose():\n    return RESULT_LIMIT\n",
                encoding="utf-8",
            )
            baseline = comparison._semantic_file_contract_digest(path, {"choose"}, set())
            path.write_text(
                "RESULT_LIMIT = 4\n\ndef choose():\n    return RESULT_LIMIT\n",
                encoding="utf-8",
            )
            changed = comparison._semantic_file_contract_digest(path, {"choose"}, set())
        self.assertNotEqual(baseline, changed)

    def test_admission_status_and_runner_dtype_contracts_are_fingerprint_bound(self):
        governance = comparison.load_governance()
        source = {
            "industry_trend_configuration_fingerprint": "a" * 64,
            "theme_taxonomy_configuration_fingerprint": "b" * 64,
            "runtime_configuration_fingerprint": "f" * 64,
        }
        baseline = comparison.comparison_contract_fingerprint(
            governance, ["physical_ai"], source
        )
        with mock.patch.object(
            comparison, "UNOBSERVED_RETURN_STATUSES", {"tampered_pending"}
        ):
            self.assertNotEqual(
                comparison.comparison_contract_fingerprint(
                    governance, ["physical_ai"], source
                ),
                baseline,
            )
        with tempfile.TemporaryDirectory() as temp:
            runner_path = Path(temp) / "a_short_theme_forward_comparison.py"
            runner_path.write_text(
                comparison.RUNNER_PATH.read_text(encoding="utf-8").replace(
                    '"ts_code": str,', '"ts_code": object,', 1
                ),
                encoding="utf-8",
            )
            with mock.patch.object(comparison, "RUNNER_PATH", runner_path):
                self.assertNotEqual(
                    comparison.comparison_contract_fingerprint(
                        governance, ["physical_ai"], source
                    ),
                    baseline,
                )

    def test_schema_line_endings_do_not_change_contract_fingerprint(self):
        governance = comparison.load_governance()
        source = {
            "industry_trend_configuration_fingerprint": "a" * 64,
            "theme_taxonomy_configuration_fingerprint": "b" * 64,
            "runtime_configuration_fingerprint": "f" * 64,
        }
        baseline = comparison.comparison_contract_fingerprint(
            governance, ["physical_ai"], source
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "governance.schema.json"
            text = comparison.GOVERNANCE_SCHEMA_PATH.read_text(encoding="utf-8")
            path.write_text(text.replace("\n", "\r\n"), encoding="utf-8", newline="")
            with mock.patch.object(comparison, "GOVERNANCE_SCHEMA_PATH", path):
                self.assertEqual(
                    comparison.comparison_contract_fingerprint(
                        governance, ["physical_ai"], source
                    ),
                    baseline,
                )

    def test_epoch_start_mutation_stops_clock_even_when_contract_is_unchanged(self):
        tracker = pd.DataFrame(_week("20260102"))
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance)
        epoch["epoch_start_as_of"] = "20260109"
        with self._frozen_context(epoch):
            packet = comparison.evaluate_theme_forward_comparison(tracker)
        self.assertEqual(packet["adjudication_mode"], "epoch_identity_mismatch")
        self.assertEqual(packet["epoch_clock_weeks"], 0)

    def test_rewritten_matured_outcome_invalidates_its_immutable_receipt(self):
        tracker = pd.DataFrame(_week("20260102"))
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance)
        admissions = self._admission_receipts(tracker, epoch)
        receipts = self._outcome_receipts(tracker, epoch, admissions)
        tracker.loc[tracker["ts_code"] == "000000.SZ", "ret_10d_t1_net"] = 99.0
        with self._frozen_context(epoch):
            packet = comparison.evaluate_theme_forward_comparison(
                tracker, admission_receipts=admissions, outcome_receipts=receipts
            )
        self.assertEqual(packet["adjudication_mode"], "epoch_outcome_receipt_mismatch")
        self.assertEqual(packet["epoch_clock_weeks"], 0)

    def test_decision_fields_cannot_change_after_admission(self):
        tracker = pd.DataFrame(_week("20260102"))
        epoch = self._frozen_epoch(comparison.load_governance())
        admissions = self._admission_receipts(tracker, epoch)
        tracker.loc[tracker["ts_code"] == "000000.SZ", "final_score"] = 999.0
        with self.assertRaisesRegex(
            comparison.ThemeForwardComparisonError, "admission receipt"
        ):
            comparison.validate_cohort_admission_receipt(
                admissions["20260102"], tracker, epoch, 5
            )

    def test_recorded_formal_decision_without_immutable_receipt_fails_closed(self):
        tracker = pd.DataFrame(_week("20260102"))
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(
            governance,
            decision={"status": "recorded", "as_of": "20260102", "packet_sha256": "d" * 64},
        )
        with self._frozen_context(epoch):
            packet = comparison.evaluate_theme_forward_comparison(tracker)
        self.assertEqual(packet["adjudication_mode"], "epoch_formal_decision_mismatch")
        self.assertFalse(packet["formal_verdict_allowed"])

    def test_only_matured_primary_h10_weeks_advance_the_36_week_clock(self):
        dates = pd.date_range("2026-01-02", periods=36, freq="7D").strftime("%Y%m%d")
        rows = [row for day in dates for row in _week(day)]
        for row in rows[-20:]:
            row["ret_10d_status"] = "pending_capture"
            row["ret_10d_t1_net"] = pd.NA
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance)
        with self._frozen_context(epoch):
            packet = self._frozen_evaluate(pd.DataFrame(rows), epoch)
        self.assertEqual(packet["epoch_clock_weeks"], 34)
        self.assertFalse(packet["formal_verdict_allowed"])
        self.assertEqual(packet["checkpoints"]["current_checkpoint"], "preview_only")

    def test_24_mature_h10_weeks_are_preview_only(self):
        dates = pd.date_range("2026-01-02", periods=24, freq="7D").strftime("%Y%m%d")
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance)
        with self._frozen_context(epoch):
            tracker = pd.DataFrame([row for day in dates for row in _week(day)])
            packet = self._frozen_evaluate(tracker, epoch)
        self.assertEqual(packet["epoch_clock_weeks"], 24)
        self.assertFalse(packet["formal_verdict_allowed"])
        self.assertEqual(packet["checkpoints"]["current_checkpoint"], "preview_only")
        self.assertTrue(all(
            item["adjudication"]["verdict"] == "preview_only"
            for item in packet["criteria"]
        ))

    def test_37th_mature_week_uses_the_first_36_sealed_cohorts_once(self):
        dates = pd.date_range("2026-01-02", periods=37, freq="7D").strftime("%Y%m%d")
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance)
        with self._frozen_context(epoch):
            tracker = pd.DataFrame([row for day in dates for row in _week(day)])
            packet = self._frozen_evaluate(tracker, epoch)
        self.assertEqual(packet["epoch_clock_weeks"], 37)
        self.assertTrue(packet["formal_verdict_allowed"])
        self.assertEqual(packet["checkpoints"]["current_checkpoint"], "formal_decision_due")
        self.assertEqual(packet["criteria"][0]["weekly_cohort_count"], 36)
        self.assertEqual(packet["checkpoints"]["formal_decision_as_of"], dates[35])

    def test_epoch_start_rejects_an_old_forward_cohort(self):
        tracker = pd.DataFrame(_week("20260102") + _week("20260109"))
        with self.assertRaisesRegex(comparison.ThemeForwardComparisonError, "latest source-bound"):
            comparison.build_frozen_epoch(
                tracker, "theme-v1", "20260102",
                freeze_packet_identity=self.freeze_packet_identity,
            )

    def test_epoch_start_rejects_any_observed_challenger_outcome(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker.loc[tracker["analysis_role"] == "final", "ret_10d_status"] = "pending_capture"
        tracker.loc[tracker["analysis_role"] == "final", "ret_10d_t1_net"] = pd.NA
        with self.assertRaisesRegex(comparison.ThemeForwardComparisonError, "entire atomic"):
            self._build_epoch_at_decision(tracker, "theme-v1", "20260102")

    def test_epoch_start_rejects_unsafe_archive_id(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker["ret_10d_status"] = "pending_capture"
        tracker["ret_10d_t1_net"] = pd.NA
        with self.assertRaisesRegex(comparison.ThemeForwardComparisonError, "safe non-empty slug"):
            comparison.build_frozen_epoch(
                tracker, "../escape", "20260102",
                freeze_packet_identity=self.freeze_packet_identity,
            )

    def test_source_configuration_drift_stops_only_the_active_epoch(self):
        rows = _week("20260102") + _week("20260109")
        for row in rows[10:]:
            row["industry_trend_configuration_fingerprint"] = "d" * 64
            row["theme_taxonomy_configuration_fingerprint"] = "e" * 64
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance)
        with self._frozen_context(epoch):
            packet = self._frozen_evaluate(pd.DataFrame(rows), epoch)
        self.assertEqual(packet["adjudication_mode"], "epoch_source_configuration_mismatch")
        self.assertEqual(packet["epoch_clock_weeks"], 0)

    def test_runtime_configuration_drift_stops_the_epoch(self):
        rows = _week("20260102") + _week("20260109")
        for row in rows[10:]:
            row["runtime_configuration_fingerprint"] = "0" * 64
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance)
        with self._frozen_context(epoch):
            packet = self._frozen_evaluate(pd.DataFrame(rows), epoch)
        self.assertEqual(packet["adjudication_mode"], "epoch_source_configuration_mismatch")
        self.assertEqual(packet["epoch_clock_weeks"], 0)

    def test_mid_epoch_unknown_theme_stops_the_epoch(self):
        rows = _week("20260102")
        for row in rows:
            row["canonical_theme_ids"] = json.dumps(["not_frozen"])
            row["canonical_themes_json"] = json.dumps([{"theme_id": "not_frozen", "role": "core"}])
            row["canonical_theme_roles"] = json.dumps({"not_frozen": "core"})
            row["primary_canonical_theme_id"] = "not_frozen"
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance)
        with self._frozen_context(epoch):
            packet = comparison.evaluate_theme_forward_comparison(pd.DataFrame(rows))
        self.assertEqual(packet["adjudication_mode"], "epoch_theme_family_mismatch")
        self.assertEqual(packet["epoch_clock_weeks"], 0)

    def test_new_epoch_can_freeze_the_latest_configuration_after_old_history_exists(self):
        rows = _week("20260102") + _week("20260109")
        for row in rows[10:]:
            row["industry_trend_configuration_fingerprint"] = "d" * 64
            row["theme_taxonomy_configuration_fingerprint"] = "e" * 64
            row["ret_10d_status"] = "pending_capture"
            row["ret_10d_t1_net"] = pd.NA
        epoch = self._build_epoch_at_decision(pd.DataFrame(rows), "theme-v2", "20260109")
        self.assertEqual(epoch["source_configuration_fingerprints"], {
            "industry_trend_configuration_fingerprint": "d" * 64,
            "theme_taxonomy_configuration_fingerprint": "e" * 64,
            "runtime_configuration_fingerprint": "f" * 64,
        })

    def test_fixed_holm_family_does_not_shrink_when_fields_are_unavailable(self):
        self.assertAlmostEqual(comparison._holm_adjust([0.01, None, None, None, None, None, None], 7)[0], 0.07)

    def test_policy_stats_expose_family_adjusted_interval_and_power_mde(self):
        stats = comparison._bootstrap_summary([0.5, 0.6, 0.4, 0.7], comparison.load_governance()["policy"], 0)
        self.assertEqual(stats["family_adjustment"]["family_size"], 7)
        self.assertEqual(stats["family_adjustment"]["method"], "bonferroni_simultaneous_bootstrap")
        self.assertLessEqual(stats["family_adjusted_ci_pp"][0], stats["ci_95_pp"][0])
        self.assertGreaterEqual(stats["family_adjusted_ci_pp"][1], stats["ci_95_pp"][1])
        self.assertIsNotNone(stats["minimum_detectable_effect_pp"])

    def test_epoch_freezes_full_taxonomy_registry_not_only_observed_theme(self):
        tracker = pd.DataFrame(_week("20260102"))
        tracker["ret_10d_status"] = "pending_capture"
        tracker["ret_10d_t1_net"] = pd.NA
        epoch = self._build_epoch_at_decision(tracker, "theme-v1", "20260102")
        registry_ids = sorted(item["theme_id"] for item in comparison.load_taxonomy_registry()["canonical_themes"])
        self.assertEqual(epoch["frozen_theme_ids"], registry_ids)
        self.assertRegex(epoch["taxonomy_registry_fingerprint"], r"^[0-9a-f]{64}$")

    def test_frozen_theme_report_keeps_zero_observation_registry_members(self):
        rows = comparison._theme_groups(
            pd.DataFrame(_week("20260102")),
            comparison.load_governance()["policy"],
            ["physical_ai", "never_seen"],
        )
        by_id = {row["theme_id"]: row for row in rows}
        self.assertEqual(set(by_id), {"physical_ai", "never_seen"})
        self.assertEqual(by_id["never_seen"]["forward_live_weeks"], 0)
        self.assertEqual(by_id["never_seen"]["stock_week_count"], 0)

    def test_frozen_theme_result_includes_effect_interval_and_exploratory_verdict(self):
        dates = pd.date_range("2026-01-02", periods=12, freq="14D").strftime("%Y%m%d")
        rows = [row for day in dates for row in _week(day)]
        for row in rows:
            if row["analysis_role"] == "final":
                row["canonical_theme_ids"] = "[]"
                row["canonical_themes_json"] = "[]"
                row["canonical_theme_roles"] = "{}"
                row["primary_canonical_theme_id"] = ""
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance)
        with self._frozen_context(epoch):
            packet = self._frozen_evaluate(pd.DataFrame(rows), epoch)
        theme = next(
            item for item in packet["exploratory_themes"]
            if item["theme_id"] == "physical_ai"
        )
        self.assertTrue(theme["sample_eligible"])
        self.assertGreater(theme["mean_member_minus_nonmember_pp"], 0.0)
        self.assertIsNotNone(theme["exploratory_ci_95_pp"])
        self.assertEqual(theme["exploratory_verdict"], "exploratory_positive")
        self.assertEqual(theme["evidence_scope"], "exploratory_theme_member_vs_nonmember_only")
        self.assertFalse(theme["actionable"])

    def test_negative_control_warning_blocks_future_replacement_evidence(self):
        dates = pd.date_range("2026-01-02", periods=36, freq="7D").strftime("%Y%m%d")
        rows = [row for day in dates for row in _week(day)]
        for row in rows:
            if row["analysis_role"] == "watch":
                row["overheat_flag"] = True
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance)
        with self._frozen_context(epoch):
            packet = self._frozen_evaluate(pd.DataFrame(rows), epoch)
        self.assertEqual(packet["negative_control"]["method_validity_status"], "unexpected_benefit_method_validity_warning")
        self.assertTrue(packet["receipt"]["replacement_evidence_blocked"])
        self.assertEqual(
            packet["receipt"]["replacement_evidence_block_reason"],
            "negative_control_method_validity_warning",
        )

    def test_sparse_negative_control_blocks_replacement_but_not_evidence_collection(self):
        dates = pd.date_range("2026-01-02", periods=36, freq="7D").strftime("%Y%m%d")
        rows = [row for day in dates for row in _week(day)]
        for day in dates:
            next(row for row in rows if row["as_of"] == day and row["analysis_role"] == "watch")[
                "overheat_flag"
            ] = True
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance)
        with self._frozen_context(epoch):
            packet = self._frozen_evaluate(pd.DataFrame(rows), epoch)
        self.assertEqual(
            packet["negative_control"]["method_validity_status"],
            "not_assessable_low_coverage",
        )
        self.assertTrue(packet["receipt"]["replacement_evidence_blocked"])
        self.assertEqual(
            packet["receipt"]["replacement_evidence_block_reason"],
            "negative_control_not_assessable_low_coverage",
        )

    def test_eligible_unadmitted_cohorts_are_reported_without_counting_them(self):
        dates = pd.date_range("2026-01-02", periods=2, freq="7D").strftime("%Y%m%d")
        tracker = pd.DataFrame([row for day in dates for row in _week(day)])
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance)
        admissions = self._admission_receipts(tracker, epoch)
        admissions.pop(dates[-1])
        epoch["admission_receipt_manifest"] = comparison.admission_receipt_manifest(admissions)
        with self._frozen_context(epoch):
            packet = comparison.evaluate_theme_forward_comparison(tracker, admission_receipts=admissions)
        self.assertEqual(packet["eligible_unadmitted_cohorts"], [dates[-1]])
        self.assertEqual(packet["epoch_clock_weeks"], 0)

    def test_packet_validator_rejects_production_or_family_drift(self):
        packet = self._packet()
        production = copy.deepcopy(packet)
        production["comparison_boundary"]["activation_authorized"] = True
        with self.assertRaises(comparison.ThemeForwardComparisonError):
            comparison.validate_comparison_packet(production)
        family = copy.deepcopy(packet)
        family["criteria"] = family["criteria"][:-1]
        with self.assertRaises(comparison.ThemeForwardComparisonError):
            comparison.validate_comparison_packet(family)
        recommendation = copy.deepcopy(packet)
        recommendation["receipt"]["production_replacement_recommendation"] = True
        with self.assertRaises(comparison.ThemeForwardComparisonError):
            comparison.validate_comparison_packet(recommendation)
        profile = copy.deepcopy(packet)
        profile["criteria"][0]["coverage"]["counted_block_execution_profile"] = []
        with self.assertRaises(comparison.ThemeForwardComparisonError):
            comparison.validate_comparison_packet(profile)

    def test_frozen_public_packet_requires_exact_freeze_packet_identity(self):
        tracker = pd.DataFrame(_week("20260102"))
        epoch = self._frozen_epoch(comparison.load_governance())
        with self._frozen_context(epoch):
            packet = self._frozen_evaluate(tracker, epoch)
        for mutation in (
            "missing", "empty_freeze_id", "old_version", "record_hash", "extra",
        ):
            candidate = copy.deepcopy(packet)
            if mutation == "missing":
                candidate["epoch"].pop("freeze_packet_identity")
            elif mutation == "empty_freeze_id":
                candidate["epoch"]["freeze_packet_identity"]["freeze_id"] = ""
            elif mutation == "old_version":
                candidate["epoch"]["freeze_packet_identity"][
                    "schema_version"
                ] = "0.9.0"
            elif mutation == "record_hash":
                candidate["epoch"]["freeze_packet_identity"][
                    "record_sha256"
                ] = "not-a-sha256"
            else:
                candidate["epoch"]["freeze_packet_identity"]["extra"] = "bad"
            with self.subTest(mutation=mutation), self.assertRaisesRegex(
                comparison.ThemeForwardComparisonError,
                "exact freeze-packet identity",
            ):
                comparison.validate_comparison_packet(candidate)

    def test_formal_receipt_rejects_freeze_packet_identity_drift(self):
        epoch = self._frozen_epoch(
            comparison.load_governance(),
            decision={"status": "recorded", "as_of": "20260102",
                      "packet_sha256": "d" * 64},
        )
        receipt = comparison.build_formal_decision_receipt(
            epoch, "20260102", "d" * 64,
            "epochs/theme-v1/formal_packet.json",
        )
        epoch["formal_decision"]["receipt_sha256"] = receipt["record_sha256"]
        candidate = copy.deepcopy(receipt)
        candidate["freeze_packet_identity"]["freeze_id"] = "other-freeze"
        candidate["record_sha256"] = comparison._digest({
            key: value for key, value in candidate.items()
            if key != "record_sha256"
        })
        epoch["formal_decision"]["receipt_sha256"] = candidate["record_sha256"]
        with self.assertRaisesRegex(
            comparison.ThemeForwardComparisonError,
            "does not match active epoch",
        ):
            comparison.validate_formal_decision_receipt(candidate, epoch)

    def test_recorded_epoch_cannot_reopen_the_same_36_week_decision(self):
        dates = pd.date_range("2026-01-02", periods=36, freq="7D").strftime("%Y%m%d")
        tracker = pd.DataFrame([row for day in dates for row in _week(day)])
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(governance, decision={"status": "recorded", "as_of": "20260904", "packet_sha256": "d" * 64})
        with self._frozen_context(epoch):
            packet = self._frozen_evaluate(tracker, epoch)
        self.assertFalse(packet["formal_verdict_allowed"])
        self.assertEqual(packet["checkpoints"]["current_checkpoint"], "formal_decision_recorded")
        self.assertIsNotNone(packet["recorded_formal_decision"])
        self.assertEqual(
            packet["recorded_formal_decision"]["packet_sha256"],
            epoch["formal_decision"]["packet_sha256"],
        )
        self.assertTrue(all(
            item["adjudication"]["verdict"] != "audit_only_pre_freeze"
            for item in packet["criteria"]
        ))

    def test_malformed_recorded_packet_fails_closed_before_clock_or_preview(self):
        dates = pd.date_range("2026-01-02", periods=36, freq="7D").strftime("%Y%m%d")
        tracker = pd.DataFrame([row for day in dates for row in _week(day)])
        governance = comparison.load_governance()
        epoch = self._frozen_epoch(
            governance,
            decision={"status": "recorded", "as_of": dates[35], "packet_sha256": "d" * 64},
        )
        formal = comparison.build_formal_decision_receipt(
            epoch, dates[35], "d" * 64, "epochs/theme-v1/formal_packet.json"
        )
        epoch["formal_decision"]["receipt_sha256"] = formal["record_sha256"]
        admissions = self._admission_receipts(tracker, epoch)
        receipts = self._outcome_receipts(tracker, epoch, admissions)
        with self._frozen_context(epoch):
            packet = comparison.evaluate_theme_forward_comparison(
                tracker,
                admission_receipts=admissions,
                outcome_receipts=receipts,
                formal_decision_receipt=formal,
                recorded_formal_packet={"malformed": True},
            )
        self.assertEqual(packet["adjudication_mode"], "epoch_formal_decision_mismatch")
        self.assertEqual(packet["epoch_clock_weeks"], 0)
        self.assertTrue(all(
            item["adjudication"]["verdict"] == "evidence_blocked"
            for item in packet["criteria"]
        ))


class MixedDtypeRowEquivalenceTests(unittest.TestCase):
    """The `iterrows -> to_dict(records)` hoists must not change row semantics.

    `iterrows` upcasts a mixed-dtype row (int becomes float, `_as_text` then
    yields `"1.0"`); `to_dict(orient="records")` keeps each column's own dtype
    (`"1"`).  The repaired consumers must reach the same verdict either way
    (review `R-ASHORT-SPEED-KNIFE-BATCH-CACHE-REVIEW` dtype note).
    """

    def test_repaired_row_consumers_agree_between_series_and_dict_rows(self):
        frame = pd.DataFrame([
            {"forward_live": 1, "historical_replay": 0, "weight": 0.5},
            {"forward_live": 0, "historical_replay": 1, "weight": 1.5},
        ])
        # Mixed dtypes force the iterrows upcast this test is about.
        self.assertEqual(str(frame["forward_live"].dtype), "int64")
        self.assertEqual(str(frame["weight"].dtype), "float64")
        dict_rows = frame.to_dict(orient="records")
        series_rows = [row for _, row in frame.iterrows()]
        for dict_row, series_row in zip(dict_rows, series_rows):
            self.assertEqual(
                comparison._forward_flags(dict_row),
                comparison._forward_flags(series_row),
            )

    def test_upcast_text_forms_are_absorbed_by_the_clock_suffix_strip(self):
        # The `"1.0"`-vs-`"1"` divergence is real for _as_text; the date-like
        # consumers strip the upcast suffix, so both row forms agree there too.
        frame = pd.DataFrame([{"industry_trend_source_as_of": 20260609, "weight": 0.5}])
        dict_text = comparison._as_text(frame.to_dict(orient="records")[0].get("industry_trend_source_as_of"))
        series_text = comparison._as_text(next(iter(frame.iterrows()))[1].get("industry_trend_source_as_of"))
        self.assertEqual(dict_text.removesuffix(".0"), series_text.removesuffix(".0"))
        self.assertNotEqual(dict_text, series_text)  # the divergence exists ...
        # ... and the repaired loops feed such values only through the
        # suffix-stripping clock comparisons, never through raw string equality.


if __name__ == "__main__":
    unittest.main()
