from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from engine import us_short_soft_boost_consumption as consumption
from engine import us_short_soft_boost_comparison_adjudication as comparison_adjudication
from engine import us_short_soft_discovery_weekly_report as weekly
from engine import us_short_weekly_report_renderer as renderer
from runners import us_short_weekly_capstone_stages as capstone_stages
# The FIXTURE, not the TestCase beside it: importing the latter made unittest
# discover its ten cases here as well, so they ran twice on every full lane.
from tests.test_us_short_soft_boost_consumption import DATE, SoftBoostFixture, _write

ROOT = Path(__file__).resolve().parents[1]


class SoftDiscoveryWeeklyReportTests(SoftBoostFixture, unittest.TestCase):
    """§4c snapshots are built solely from the already-tested K4a/K4b receipt fixtures."""

    def _publish(self, resolved, *, on=None, off=None, boosts=None, on_top15=None, off_top15=None):
        receipt = consumption.build_consumption_receipt(
            resolved=resolved, generated_at="2026-06-15T08:31:00-04:00",
            on_selection=on or {}, off_selection=off or {}, boost_records=boosts or {},
            on_top15=on_top15 or [], off_top15=off_top15 or [],
        )
        shadow = consumption.build_shadow_receipt(
            resolved=resolved, generated_at="2026-06-15T08:31:00-04:00",
            on_top15=on_top15 or [], off_top15=off_top15 or [], common_input_sha256="a" * 64,
        )
        consumption.write_evidence_bundle(
            consumption_receipt=receipt, consumption_path=self.paths["consumption"],
            shadow_receipt=shadow, shadow_path=self.paths["shadow"], ledger_path=self.paths["ledger"],
            state_dir=self.fixture_root,
        )

    def _record(self):
        return weekly.build_weekly_record(
            decision_date=DATE, stage_receipt_path=self.paths["stage"],
            consumption_receipt_path=self.paths["consumption"], shadow_receipt_path=self.paths["shadow"],
            comparison_ledger_path=self.paths["ledger"],
        )

    def test_disabled_has_no_banner_and_keeps_legacy_render_surface_absent(self):
        record = weekly.build_weekly_record(decision_date=DATE, stage_receipt_path=None,
                                            consumption_receipt_path=None, comparison_ledger_path=None)
        self.assertEqual(record["state"], "disabled")
        self.assertIsNone(weekly.render_weekly_banner(record))
        base = {"banner": {"price_clock": {"price_data_through": "20260619", "news_window_through": "20260619",
                                               "session_scope": "RTH", "decision_date": "20260622"}},
                "lifecycle_reminder_count": {"section_1": 0, "section_12": 0},
                "sections": {str(i): ["x"] for i in range(1, 14)}}
        old_bytes = renderer.render_weekly_report(base).encode("utf-8")
        self.assertEqual(renderer.render_weekly_report(base).encode("utf-8"), old_bytes)

    def test_valid_nonempty_snapshot_lists_only_consumed_labels_and_actual_2_5_scores(self):
        self._publish(self._resolve(), on={"AAPL": 100.0, "MSFT": 52.0}, off={"AAPL": 95.0, "MSFT": 50.0},
                      boosts={"AAPL": {"theme_soft_boost": 5.0, "evidence_tier": "both"},
                              "MSFT": {"theme_soft_boost": 2.0, "evidence_tier": "single"}},
                      on_top15=["AAPL"], off_top15=["MSFT"])
        record = self._record()
        self.assertEqual(record["state"], "valid_nonempty")
        self.assertEqual(record["bindings"]["stage_receipt"]["path"], self.paths["stage"].relative_to(ROOT).as_posix())
        self.assertEqual(record["bindings"]["consumption_receipt"]["path"], self.paths["consumption"].relative_to(ROOT).as_posix())
        self.assertEqual(record["consumed"]["labels"], ["Theme"])
        self.assertEqual(record["consumed"]["boosts"], [{"ticker": "AAPL", "actual_boost": 5.0},
                                                           {"ticker": "MSFT", "actual_boost": 2.0}])
        self.assertFalse(record["consumed"]["operation_advice_effect_claimed"])
        self.assertIn("未确认软发现", weekly.render_weekly_banner(record))
        self.assertNotIn("强主题", weekly.render_weekly_banner(record))
        self.assertIn("不改变操作建议", weekly.render_weekly_banner(record))

    def test_valid_nonempty_banner_has_one_comparison_prefix(self):
        self._publish(self._resolve(), on={"AAPL": 100.0}, off={"AAPL": 95.0},
                      boosts={"AAPL": {"theme_soft_boost": 5.0, "evidence_tier": "both"}},
                      on_top15=["AAPL"], off_top15=["MSFT"])
        self.assertNotIn("对比=对比进度", weekly.render_weekly_banner(self._record()))

    def test_label_derivation_breaks_closed_when_consumed_ticker_has_no_validated_theme_member(self):
        self._publish(self._resolve(), on={"AAPL": 100.0}, off={"AAPL": 95.0},
                      boosts={"AAPL": {"theme_soft_boost": 5.0, "evidence_tier": "both"}},
                      on_top15=["AAPL"], off_top15=["MSFT"])
        validation = copy.deepcopy(self.validation)
        validation["themes"][0]["members"][0]["ticker"] = "MSFT"
        _write(self.paths["validation"], validation)
        record = self._record()
        self.assertEqual(record["state"], "invalid_evidence")
        self.assertEqual(record["reason_code"], "K4C_RECEIPT_REJECTED")

    def test_valid_empty_is_not_an_invalid_or_unavailable_banner(self):
        validation = copy.deepcopy(self.validation)
        validation["themes"] = []
        validation["summary"]["validated_theme_count"] = 0
        validation["summary"]["validated_member_count"] = 0
        validation_sha = _write(self.paths["validation"], validation)
        stage = copy.deepcopy(self.stage)
        stage["status"] = "valid_empty"
        stage["validated_theme_count"] = 0
        stage["boostable_ticker_count"] = 0
        stage["artifacts"]["validation"]["sha256"] = validation_sha
        _write(self.paths["stage"], stage)
        self._publish(self._resolve(current_stage_result=stage))
        record = self._record()
        self.assertEqual(record["state"], "valid_empty")
        self.assertIn("本周无合格主题", weekly.render_weekly_banner(record))

    def test_upstream_unavailable_and_invalid_evidence_are_never_presented_as_empty(self):
        stage = copy.deepcopy(self.stage)
        stage.update({"status": "upstream_unavailable", "reason_code": "CANDIDATE_INPUT_UNAVAILABLE",
                      "validated_theme_count": 0, "boostable_ticker_count": 0,
                      "error_summary": {"code": "CANDIDATE_INPUT_UNAVAILABLE", "error_type": "FixtureError"}})
        _write(self.paths["stage"], stage)
        self._publish(self._resolve(current_stage_result=stage))
        unavailable = self._record()
        self.assertEqual(unavailable["state"], "upstream_unavailable")
        self.assertIn("不可用/未完成", weekly.render_weekly_banner(unavailable))

        self.paths["consumption"].write_text("{bad", encoding="utf-8")
        invalid = self._record()
        self.assertEqual(invalid["state"], "invalid_evidence")
        self.assertIn("证据无效", weekly.render_weekly_banner(invalid))
        self.assertNotIn("无合格主题", weekly.render_weekly_banner(invalid))

    def test_corrupt_or_cross_week_ledger_cannot_reuse_a_recommendation(self):
        self._publish(self._resolve(), on={"AAPL": 55.0}, off={"AAPL": 50.0},
                      boosts={"AAPL": {"theme_soft_boost": 5.0, "evidence_tier": "both"}},
                      on_top15=["AAPL"], off_top15=["MSFT"])
        ledger = json.loads(self.paths["ledger"].read_text(encoding="utf-8"))
        ledger["records"][0]["decision_date"] = "20991230"
        self.paths["ledger"].write_text(json.dumps(ledger), encoding="utf-8")
        record = self._record()
        self.assertEqual(record["comparison"]["status"], "comparison_unavailable")
        self.assertEqual(record["comparison"]["recommendation"], "comparison_unavailable")

    def test_prelook_banner_uses_accumulation_not_a_postlook_recommendation(self):
        self._publish(self._resolve(), on={"AAPL": 55.0}, off={"AAPL": 50.0},
                      boosts={"AAPL": {"theme_soft_boost": 5.0, "evidence_tier": "both"}},
                      on_top15=["AAPL"], off_top15=["MSFT"])
        banner = weekly.render_weekly_banner(self._record())
        self.assertIn("continue_accumulating", banner)
        self.assertNotIn("continue_on", banner)
        self.assertNotIn("recommend_switch_off", banner)
        self.assertNotIn("insufficient_evidence", banner)

    def test_comparison_capture_stage_advances_two_decision_dates_and_rejects_backfill(self):
        self._publish(self._resolve(), on={"AAPL": 55.0}, off={"AAPL": 50.0},
                      boosts={"AAPL": {"theme_soft_boost": 5.0, "evidence_tier": "both"}},
                      on_top15=["AAPL"], off_top15=["MSFT"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            consumption_path, shadow_path = root / "on.json", root / "off.json"
            consumption_path.write_bytes(self.paths["consumption"].read_bytes())
            shadow_path.write_bytes(self.paths["shadow"].read_bytes())
            ctx = SimpleNamespace(
                decision_date=DATE, soft_boost_consumption_receipt_path=consumption_path,
                soft_boost_shadow_receipt_path=shadow_path, soft_boost_pairwise_ledger_path=root / "pairwise.json",
                soft_boost_maturity_observation_root=root / "maturity", soft_boost_adjudication_receipt_path=root / "adj.json",
            )
            self.assertEqual(capstone_stages.run_soft_boost_comparison_capture(ctx)["captured_week_count"], 1)
            next_date = "21000101"
            for path in (consumption_path, shadow_path):
                value = json.loads(path.read_text(encoding="utf-8"))
                value["decision_date"] = next_date
                path.write_text(json.dumps(value), encoding="utf-8")
            ctx.decision_date = next_date
            self.assertEqual(capstone_stages.run_soft_boost_comparison_capture(ctx)["captured_week_count"], 2)
            ctx.decision_date = DATE
            with self.assertRaises(ValueError):
                capstone_stages.run_soft_boost_comparison_capture(ctx)

    def test_capture_stage_preserves_24_matured_weeks_and_emits_formal_user_decision_record(self):
        self._publish(self._resolve(), on={"AAPL": 55.0}, off={"AAPL": 50.0},
                      boosts={"AAPL": {"theme_soft_boost": 5.0, "evidence_tier": "both"}},
                      on_top15=["AAPL"], off_top15=["MSFT"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            consumption_path, shadow_path = root / "on.json", root / "off.json"
            consumption_path.write_bytes(self.paths["consumption"].read_bytes())
            shadow_path.write_bytes(self.paths["shadow"].read_bytes())
            pairwise_path = root / "pairwise.json"
            pairwise_path.write_text(json.dumps(comparison_adjudication.build_pairwise_ledger([
                {**row, "on_net_return": 0.0, "off_net_return": 0.03}
                for row in self._formal_pairwise_rows()
            ])), encoding="utf-8")
            adjudication_path = root / "adj.json"
            ctx = SimpleNamespace(
                decision_date=DATE, soft_boost_consumption_receipt_path=consumption_path,
                soft_boost_shadow_receipt_path=shadow_path, soft_boost_pairwise_ledger_path=pairwise_path,
                soft_boost_maturity_observation_root=root / "maturity", soft_boost_adjudication_receipt_path=adjudication_path,
            )
            stage = capstone_stages.run_soft_boost_comparison_capture(ctx)
            self.assertEqual((stage["captured_week_count"], stage["eligible_divergence_week_count"], stage["formal_look"]), (25, 24, 24))
            record = weekly.build_weekly_record(
                decision_date=DATE, stage_receipt_path=self.paths["stage"],
                consumption_receipt_path=consumption_path, shadow_receipt_path=shadow_path,
                comparison_ledger_path=pairwise_path, adjudication_receipt_path=adjudication_path,
            )
            self.assertEqual(record["comparison"]["status"], "formal_adjudicated")
            self.assertTrue(record["comparison"]["user_decision_required"])

    def test_maturity_stage_writes_source_bound_h10_observation_then_capture_consumes_it(self):
        self._publish(self._resolve(), on={"AAPL": 55.0}, off={"AAPL": 50.0},
                      boosts={"AAPL": {"theme_soft_boost": 5.0, "evidence_tier": "both"}},
                      on_top15=["AAPL"], off_top15=["MSFT"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior_date = "20251201"
            old_date = "20260101"
            consumption_root, shadow_root = root / "receipts", root / "shadow"
            consumption_root.mkdir(); shadow_root.mkdir()
            old_consumption = json.loads(self.paths["consumption"].read_text(encoding="utf-8"))
            old_shadow = json.loads(self.paths["shadow"].read_text(encoding="utf-8"))
            old_consumption["decision_date"] = old_date; old_shadow["decision_date"] = old_date
            old_consumption_path = consumption_root / f"us_short_soft_boost_consumption_receipt_{old_date}.json"
            old_shadow_path = shadow_root / f"us_short_soft_boost_shadow_receipt_{old_date}.json"
            old_consumption_path.write_text(json.dumps(old_consumption), encoding="utf-8")
            old_shadow_path.write_text(json.dumps(old_shadow), encoding="utf-8")
            prior_consumption = dict(old_consumption); prior_shadow = dict(old_shadow)
            prior_consumption["decision_date"] = prior_date; prior_shadow["decision_date"] = prior_date
            prior_consumption_path = consumption_root / f"us_short_soft_boost_consumption_receipt_{prior_date}.json"
            prior_shadow_path = shadow_root / f"us_short_soft_boost_shadow_receipt_{prior_date}.json"
            prior_consumption_path.write_text(json.dumps(prior_consumption), encoding="utf-8")
            prior_shadow_path.write_text(json.dumps(prior_shadow), encoding="utf-8")
            prior_capture = comparison_adjudication.build_pairwise_capture(
                decision_date=prior_date, consumption_receipt_sha256=hashlib.sha256(prior_consumption_path.read_bytes()).hexdigest(),
                shadow_receipt_sha256=hashlib.sha256(prior_shadow_path.read_bytes()).hexdigest(), divergent=True,
            )
            old_capture = comparison_adjudication.build_pairwise_capture(
                decision_date=old_date, consumption_receipt_sha256=hashlib.sha256(old_consumption_path.read_bytes()).hexdigest(),
                shadow_receipt_sha256=hashlib.sha256(old_shadow_path.read_bytes()).hexdigest(), divergent=True,
            )
            pairwise_path = root / "pairwise.json"
            pairwise_path.write_text(json.dumps(comparison_adjudication.append_pairwise_capture(
                comparison_adjudication.append_pairwise_capture(None, prior_capture), old_capture)), encoding="utf-8")
            current_consumption = consumption_root / f"us_short_soft_boost_consumption_receipt_{DATE}.json"
            current_shadow = shadow_root / f"us_short_soft_boost_shadow_receipt_{DATE}.json"
            current_consumption.write_bytes(self.paths["consumption"].read_bytes())
            current_shadow.write_bytes(self.paths["shadow"].read_bytes())
            ohlcv_path = root / "ohlcv.json"
            vix_path = root / "vix.json"
            vix_path.write_text(json.dumps({"vix_regime": capstone_stages.REGIMES[0], "vix_regime_is_unknown": False}), encoding="utf-8")
            no_count_packet = self._maturity_packet()
            no_count_packet["series_by_ticker"]["MSFT"]["points"] = no_count_packet["series_by_ticker"]["MSFT"]["points"][:10]
            ohlcv_path.write_text(json.dumps(no_count_packet), encoding="utf-8")
            ctx = SimpleNamespace(
                decision_date=DATE, ohlcv_series_packet_path=ohlcv_path,
                soft_boost_consumption_receipt_path=current_consumption, soft_boost_shadow_receipt_path=current_shadow,
                soft_boost_pairwise_ledger_path=pairwise_path, soft_boost_maturity_observation_root=root / "observations",
                soft_boost_adjudication_receipt_path=root / "adj.json", vix_regime_summary_path=vix_path,
            )
            no_count = capstone_stages.run_soft_boost_comparison_maturity(ctx)
            self.assertEqual((no_count["matured_observations_written"], no_count["whole_week_no_count"]), (0, 2))
            self.assertFalse((ctx.soft_boost_maturity_observation_root / f"{old_date}.json").exists())
            ohlcv_path.write_text(json.dumps(self._maturity_packet()), encoding="utf-8")
            vix_path.write_text(json.dumps({"vix_regime": capstone_stages.UNKNOWN, "vix_regime_is_unknown": True}), encoding="utf-8")
            unknown_regime = capstone_stages.run_soft_boost_comparison_maturity(ctx)
            self.assertEqual((unknown_regime["matured_observations_written"], unknown_regime["whole_week_no_count"]), (0, 2))
            self.assertFalse((ctx.soft_boost_maturity_observation_root / f"{old_date}.json").exists())
            vix_path.write_text(json.dumps({"vix_regime": capstone_stages.REGIMES[0], "vix_regime_is_unknown": False}), encoding="utf-8")
            matured = capstone_stages.run_soft_boost_comparison_maturity(ctx)
            self.assertEqual((matured["matured_observations_written"], matured["whole_week_no_count"]), (1, 1))
            observation = json.loads((ctx.soft_boost_maturity_observation_root / f"{old_date}.json").read_text(encoding="utf-8"))
            self.assertTrue(observation["non_overlap_h10_block"])
            self.assertEqual(observation["market_risk_regime"], capstone_stages.REGIMES[0])
            self.assertEqual(observation["on_turnover"], 0.0)
            self.assertEqual(capstone_stages.run_soft_boost_comparison_capture(ctx)["matured_week_count"], 1)

    @staticmethod
    def _maturity_packet():
        def points(offset):
            return [{"date": f"2026-01-{index:02d}", "high": 101 + index + offset, "low": 99 + index + offset,
                     "close": 100 + index + offset} for index in range(1, 12)]
        return {"schema_name": "us_short_batch5_full_universe_ohlcv_series_packet", "schema_version": "1.0.0",
                "generated_at": "2026-01-20T00:00:00Z",
                "scope": {"market": "US", "lane": "us_short", "batch": "batch5_provider_live",
                          "packet_status": "full_universe_per_ticker_ohlcv_series_ready_for_local_overextension_projection",
                          "full_market_reconstruction": True, "network_access_performed_by_packet_producer": False,
                          "provider_calls_performed_by_packet_producer": False, "raw_payload_refs_gitignored": True,
                          "datahub_consumption_allowed": False, "production_storage_allowed": False,
                          "ship_gate_evidence_claimed": False, "broker_or_order_automation_allowed": False,
                          "a_share_crossing_allowed": False},
                "decision_clock": {"expected_decision_date": DATE, "candidate_price_basis_date": "20260101",
                                   "price_basis_date": "2026-01-01", "source_as_of": "2026-01-11"},
                "series_contract": {"session": "RTH", "adjustment_mode": "split_adjusted", "as_of": "2026-01-11", "grouped_session_count": 11},
                "provenance": {"provider_id": "fixture", "endpoint_or_family": "fixture", "source_as_of": "2026-01-11",
                               "observed_at": "2026-01-20T00:00:00Z", "coverage_status": "full", "parser_status": "ok"},
                "series_by_ticker": {"AAPL": {"as_of": "2026-01-11", "session": "RTH", "adjustment_mode": "split_adjusted", "points": points(0)},
                                     "MSFT": {"as_of": "2026-01-11", "session": "RTH", "adjustment_mode": "split_adjusted", "points": points(5)}}}


    # Machine guards: evaluate only observations emitted by the real H10 producer.
    _MATURITY_AS_OF = "20260120"

    def _write_capture_sources(self, root, *, decision_date, on_top15, off_top15):
        consumption_root, shadow_root = root / "receipts", root / "shadow"
        consumption_root.mkdir(parents=True, exist_ok=True); shadow_root.mkdir(parents=True, exist_ok=True)
        resolved = self._resolve()
        receipt = consumption.build_consumption_receipt(
            resolved=resolved, generated_at="2026-06-15T08:31:00-04:00", on_selection={}, off_selection={},
            boost_records={}, on_top15=on_top15, off_top15=off_top15,
        )
        shadow = consumption.build_shadow_receipt(
            resolved=resolved, generated_at="2026-06-15T08:31:00-04:00", on_top15=on_top15,
            off_top15=off_top15, common_input_sha256="a" * 64,
        )
        receipt["decision_date"] = decision_date; shadow["decision_date"] = decision_date
        consumption_path = consumption_root / f"us_short_soft_boost_consumption_receipt_{decision_date}.json"
        shadow_path = shadow_root / f"us_short_soft_boost_shadow_receipt_{decision_date}.json"
        consumption_path.write_text(json.dumps(receipt), encoding="utf-8")
        shadow_path.write_text(json.dumps(shadow), encoding="utf-8")
        return consumption_path, shadow_path

    def _real_observation(self, root, *, index, on_wins, regime, replacement_rate, divergent=True, overlap=False, lossy=False):
        """Make one actual producer output; only source receipts and price/VIX inputs vary."""
        base = dt.date(2024, 1, 1) + dt.timedelta(days=index * 2)
        prior_date, decision_date = base.strftime("%Y%m%d"), (base + dt.timedelta(days=1)).strftime("%Y%m%d")
        prior_on, prior_off = (["AAPL"], ["MSFT"])
        current_on, current_off = ((["MSFT"], ["AAPL"]) if replacement_rate else (prior_on, prior_off))
        prior_consumption, prior_shadow = self._write_capture_sources(root, decision_date=prior_date,
                                                                        on_top15=prior_on, off_top15=prior_off)
        current_consumption, current_shadow = self._write_capture_sources(root, decision_date=decision_date,
                                                                            on_top15=current_on, off_top15=current_off)
        prior_capture = comparison_adjudication.build_pairwise_capture(
            decision_date=prior_date, consumption_receipt_sha256=hashlib.sha256(prior_consumption.read_bytes()).hexdigest(),
            shadow_receipt_sha256=hashlib.sha256(prior_shadow.read_bytes()).hexdigest(), divergent=True,
        )
        current_capture = comparison_adjudication.build_pairwise_capture(
            decision_date=decision_date, consumption_receipt_sha256=hashlib.sha256(current_consumption.read_bytes()).hexdigest(),
            shadow_receipt_sha256=hashlib.sha256(current_shadow.read_bytes()).hexdigest(), divergent=divergent,
        )
        pairwise_path = root / "pairwise.json"
        pairwise_path.write_text(json.dumps(comparison_adjudication.append_pairwise_capture(
            comparison_adjudication.append_pairwise_capture(None, prior_capture), current_capture)), encoding="utf-8")
        packet = SoftDiscoveryWeeklyReportTests._maturity_packet()
        packet["decision_clock"]["expected_decision_date"] = self._MATURITY_AS_OF
        if on_wins:
            packet["series_by_ticker"]["AAPL"]["points"][-1]["close"] = 130.0
            packet["series_by_ticker"]["MSFT"]["points"][-1]["close"] = 90.0 if lossy else packet["series_by_ticker"]["MSFT"]["points"][0]["close"]
        else:
            packet["series_by_ticker"]["AAPL"]["points"][-1]["close"] = 90.0 if lossy else packet["series_by_ticker"]["AAPL"]["points"][0]["close"]
            packet["series_by_ticker"]["MSFT"]["points"][-1]["close"] = 130.0
        ohlcv_path = root / "ohlcv.json"; ohlcv_path.write_text(json.dumps(packet), encoding="utf-8")
        vix_path = root / "vix.json"
        vix_path.write_text(json.dumps({"vix_regime": regime, "vix_regime_is_unknown": False}), encoding="utf-8")
        ctx = SimpleNamespace(
            decision_date=self._MATURITY_AS_OF, ohlcv_series_packet_path=ohlcv_path,
            soft_boost_consumption_receipt_path=current_consumption, soft_boost_shadow_receipt_path=current_shadow,
            soft_boost_pairwise_ledger_path=pairwise_path, soft_boost_maturity_observation_root=root / "observations",
            soft_boost_adjudication_receipt_path=root / "adj.json", vix_regime_summary_path=vix_path,
        )
        stage = capstone_stages.run_soft_boost_comparison_maturity(ctx)
        self.assertEqual(stage["matured_observations_written"], 1)
        observation = json.loads((ctx.soft_boost_maturity_observation_root / f"{decision_date}.json").read_text(encoding="utf-8"))
        if not overlap:
            return observation
        matured = comparison_adjudication.apply_maturity_observations(
            comparison_adjudication.read_pairwise_ledger(pairwise_path), [observation], maturity_as_of=self._MATURITY_AS_OF)
        overlap_date = (dt.datetime.strptime(decision_date, "%Y%m%d").date() + dt.timedelta(days=1)).strftime("%Y%m%d")
        overlap_consumption, overlap_shadow = self._write_capture_sources(
            root, decision_date=overlap_date, on_top15=current_on, off_top15=current_off)
        overlap_capture = comparison_adjudication.build_pairwise_capture(
            decision_date=overlap_date, consumption_receipt_sha256=hashlib.sha256(overlap_consumption.read_bytes()).hexdigest(),
            shadow_receipt_sha256=hashlib.sha256(overlap_shadow.read_bytes()).hexdigest(), divergent=divergent,
        )
        comparison_adjudication.persist_pairwise_ledger(
            pairwise_path, comparison_adjudication.append_pairwise_capture(matured, overlap_capture))
        ctx.soft_boost_consumption_receipt_path = overlap_consumption
        ctx.soft_boost_shadow_receipt_path = overlap_shadow
        stage = capstone_stages.run_soft_boost_comparison_maturity(ctx)
        self.assertEqual(stage["matured_observations_written"], 1)
        return json.loads((ctx.soft_boost_maturity_observation_root / f"{overlap_date}.json").read_text(encoding="utf-8"))

    def test_real_producer_constant_input_detector_has_only_documented_structural_exemptions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            observations = [
                self._real_observation(root / "a", index=0, on_wins=True, regime=capstone_stages.REGIMES[0], replacement_rate=False),
                self._real_observation(root / "b", index=1, on_wins=False, regime=capstone_stages.REGIMES[1], replacement_rate=True, overlap=True),
                self._real_observation(root / "c", index=2, on_wins=False, regime=capstone_stages.REGIMES[0], replacement_rate=False, divergent=False, lossy=True),
                self._real_observation(root / "d", index=3, on_wins=True, regime=capstone_stages.REGIMES[1], replacement_rate=False, lossy=True),
                self._real_observation(root / "e", index=4, on_wins=True, regime=capstone_stages.REGIMES[0], replacement_rate=True),
            ]
        schema = json.loads((ROOT / "schemas" / "us_short_soft_boost_maturity_observation.schema.json").read_text(encoding="utf-8"))
        exemptions = comparison_adjudication.STRUCTURAL_DECISION_INPUT_EXEMPTIONS
        self.assertEqual(set(exemptions), {"on_fill_fraction", "off_fill_fraction"})
        self.assertTrue(all(isinstance(reason, str) and reason for reason in exemptions.values()))
        for field in schema["required"]:
            if field in exemptions:
                continue
            self.assertGreater(len({row[field] for row in observations}), 1, field)
        self.assertEqual({row["on_fill_fraction"] for row in observations}, {1.0})
        self.assertEqual({row["off_fill_fraction"] for row in observations}, {1.0})

    def _real_ledger(self, root, *, on_wins):
        observations = [self._real_observation(
            root / str(index), index=index, on_wins=on_wins,
            regime=capstone_stages.REGIMES[index % 2], replacement_rate=False,
        ) for index in range(24)]
        captures = [comparison_adjudication.build_pairwise_capture(
            decision_date=row["decision_date"], consumption_receipt_sha256=row["consumption_receipt_sha256"],
            shadow_receipt_sha256=row["shadow_receipt_sha256"], divergent=True,
        ) for row in observations]
        return comparison_adjudication.apply_maturity_observations(
            comparison_adjudication.build_pairwise_ledger(captures), observations, maturity_as_of="99991231")

    def test_real_producer_24_week_conclusions_are_reachable_in_both_directions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            on_result = comparison_adjudication.evaluate_pairwise_ledger(self._real_ledger(root / "on", on_wins=True))
            off_result = comparison_adjudication.evaluate_pairwise_ledger(self._real_ledger(root / "off", on_wins=False))
        self.assertEqual(on_result["recommendation"], "continue_on", on_result)
        self.assertEqual(off_result["recommendation"], "recommend_switch_off", off_result)

    def test_premature_formal_adjudication_cannot_reuse_a_recommendation(self):
        self._publish(self._resolve(), on={"AAPL": 55.0}, off={"AAPL": 50.0},
                      boosts={"AAPL": {"theme_soft_boost": 5.0, "evidence_tier": "both"}},
                      on_top15=["AAPL"], off_top15=["MSFT"])
        adjudication = self.paths["ledger"].with_name("us_short_soft_boost_adjudication_receipt_%s.json" % DATE)
        _write(adjudication, {"schema_name": "us_short_soft_boost_adjudication_receipt", "schema_version": "1.0.0",
                              "epoch_id": "us_short_soft_boost_k4b_20260727", "decision_date": DATE,
                              "comparison_ledger_sha256": hashlib.sha256(self.paths["ledger"].read_bytes()).hexdigest(),
                              "formal_look": 24, "recommendation": "recommend_switch_off", "user_decision": "defer",
                              "automatic_replacement_allowed": False, "production_flag": False})
        record = weekly.build_weekly_record(decision_date=DATE, stage_receipt_path=self.paths["stage"],
            consumption_receipt_path=self.paths["consumption"], shadow_receipt_path=self.paths["shadow"],
            comparison_ledger_path=self.paths["ledger"], adjudication_receipt_path=adjudication)
        self.assertEqual(record["comparison"]["recommendation"], "comparison_unavailable")
        self.assertFalse(record["comparison"]["user_decision_required"])
        self.assertFalse(record["comparison"]["automatic_replacement_allowed"])
        adjudication.unlink()

    def test_formal_pairwise_receipt_binds_current_on_off_and_ledger_into_machine_record(self):
        self._publish(self._resolve(), on={"AAPL": 55.0}, off={"AAPL": 50.0},
                      boosts={"AAPL": {"theme_soft_boost": 5.0, "evidence_tier": "both"}},
                      on_top15=["AAPL"], off_top15=["MSFT"])
        consumption_sha = hashlib.sha256(self.paths["consumption"].read_bytes()).hexdigest()
        shadow_sha = hashlib.sha256(self.paths["shadow"].read_bytes()).hexdigest()
        rows = self._formal_pairwise_rows()
        rows[-1].update({"decision_date": DATE, "consumption_receipt_sha256": consumption_sha,
                         "shadow_receipt_sha256": shadow_sha})
        ledger = comparison_adjudication.build_pairwise_ledger(rows)
        self.paths["ledger"].write_text(json.dumps(ledger), encoding="utf-8")
        adjudication = self.paths["ledger"].with_name("us_short_soft_boost_adjudication_receipt_%s.json" % DATE)
        _write(adjudication, comparison_adjudication.build_adjudication_receipt(
            self.paths["ledger"], decision_date=DATE, user_decision="defer"))
        record = weekly.build_weekly_record(decision_date=DATE, stage_receipt_path=self.paths["stage"],
            consumption_receipt_path=self.paths["consumption"], shadow_receipt_path=self.paths["shadow"],
            comparison_ledger_path=self.paths["ledger"], adjudication_receipt_path=adjudication)
        self.assertEqual((record["comparison"]["status"], record["comparison"]["recommendation"]),
                         ("formal_adjudicated", "recommend_switch_off"))
        self.assertTrue(record["comparison"]["user_decision_required"])
        self.assertEqual(record["bindings"]["shadow_receipt"]["sha256"], shadow_sha)
        self.assertEqual(record["bindings"]["adjudication_receipt"]["path"], adjudication.relative_to(ROOT).as_posix())

        receipt = json.loads(adjudication.read_text(encoding="utf-8"))
        receipt["formal_evidence"]["off_gate_passed"] = False
        _write(adjudication, receipt)
        rejected = weekly.build_weekly_record(decision_date=DATE, stage_receipt_path=self.paths["stage"],
            consumption_receipt_path=self.paths["consumption"], shadow_receipt_path=self.paths["shadow"],
            comparison_ledger_path=self.paths["ledger"], adjudication_receipt_path=adjudication)
        self.assertEqual(rejected["comparison"]["status"], "comparison_unavailable")

    @staticmethod
    def _formal_pairwise_rows():
        rows = []
        for index in range(24):
            rows.append({
                "decision_date": f"202601{index + 1:02d}", "consumption_receipt_sha256": f"{index + 1:064x}",
                "shadow_receipt_sha256": f"{index + 101:064x}", "maturity_receipt_sha256": f"{index + 201:064x}",
                "market_risk_regime": "risk_on" if index < 12 else "risk_off", "divergent": True,
                "matured": True, "eligible": True, "non_overlap_h10_block": True,
                "on_net_return": 0.0, "off_net_return": 0.03,
                "on_max_drawdown": 0.05, "off_max_drawdown": 0.05, "on_bad_pick_rate": 0.10, "off_bad_pick_rate": 0.10,
                "on_tail_loss": 0.02, "off_tail_loss": 0.02, "on_turnover": 0.10, "off_turnover": 0.10,
                "on_fill_fraction": 0.90, "off_fill_fraction": 0.90,
            })
        return rows


if __name__ == "__main__":
    unittest.main()
