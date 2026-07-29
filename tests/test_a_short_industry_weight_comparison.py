"""Offline P5a contract, cache-only outcome and privacy regressions."""
from __future__ import annotations

import json
import hashlib
import copy
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pandas as pd
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_industry_weight_comparison import (  # noqa: E402
    ADMISSION_IDS, PROGRAM_ID, IndustryWeightComparisonError, _atomic_write, _boundary, _contract_fingerprint,
    _digest, _epoch_id, _runtime_source_fingerprint,
    _validate_private_record, build_public_progress, cache_consumer_windows,
    capture_after_published_weekly, load_governance, settle_from_daily_payload,
    validate_public_progress, write_public_progress,
)
from engine.a_short_experiment_admission_registry import admission_snapshot  # noqa: E402
from engine.egs_industry_heat import build_weight_comparison  # noqa: E402
from runners.a_short_factor_comparison_v2_cache_build import materialize_incremental_cache  # noqa: E402
from engine import a_short_evidence_epoch_mode as _epoch_mode
from tests._a_short_epoch_mode_test_utils import enter_patched_epoch_modes, patched_epoch_modes


DECISION = "20260202"
RUN = DECISION
SETTLE_AS_OF = "20260227"


def _p5_root(tmp: str) -> Path:
    return Path(tmp) / "state" / "a_short" / "industry_weight_comparison_private" / "v1"


def _v2_root(tmp: str) -> Path:
    return Path(tmp) / "state" / "a_short" / "factor_comparison_private" / "v2"


def _dates(start: date, count: int) -> list[str]:
    result = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return result


def _universe() -> pd.DataFrame:
    rows = []
    for index in range(18):
        rows.append({
            "ts_code": f"60{index:04d}.SH", "esp_score": 90.0 - index, "cat_score": 80.0 - index,
            "l4_score": 70.0 - index, "industry_heat_score": float((index % 4) * 20),
            "l2_flags": "", "cat_flag": "", "l1_flag": "", "itf_adj": False,
            "reduce_penalty": 0.0, "val_penalty": 0.0, "val_bonus": 0.0, "q0_dt_yoy": 1.0,
            "esp_raw": 1.0, "chasing_high": False, "overheat_flag": False, "l4_flag": "",
            "l1_name": f"L1-{index % 5}", "l2_name": f"L2-{index % 7}",
            "pct_20d_n": 100.0 - index, "pct_60d_n": 100.0 - index,
        })
    return pd.DataFrame(rows)


def _sources(tmp: str, *, same_profiles: bool = False) -> tuple[Path, Path, Path, dict]:
    comparison = build_weight_comparison(_universe(), as_of=DECISION)
    if same_profiles:
        balanced = comparison["profile_watch_pool_top15"]["profiles"]["balanced"]
        for profile in ("legacy", "aggressive", "theme_double"):
            comparison["profile_watch_pool_top15"]["profiles"][profile] = json.loads(json.dumps(balanced))
    comparison_path = Path(tmp) / "egs_weight_comparison.json"
    comparison_path.write_text(json.dumps(comparison), encoding="utf-8")
    balanced_codes = [row["ts_code"] for row in comparison["profile_watch_pool_top15"]["profiles"]["balanced"]]
    identity = {"run_id": "a-short-20260202-0123456789abcdef", "candidate_digest": "b" * 64}
    analysis = {"trade_date": DECISION, "source": {"run_identity": identity},
                "candidates": [{"ts_code": code} for code in balanced_codes]}
    analysis_path = Path(tmp) / "analysis_input.json"
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
    out = Path(tmp) / "weekly_m67.json"
    out.write_text(json.dumps({"as_of": DECISION, "run_lineage": {**identity,
                    "price_freshness": {"price_data_through": DECISION}}}), encoding="utf-8")
    out.with_suffix(".md").write_text("# weekly\n", encoding="utf-8")
    receipt = Path(tmp) / "weekly_m67.receipt.json"
    receipt.write_text(json.dumps({"stage_status": "complete", "as_of": DECISION,
                                    "run_id": identity["run_id"], "candidate_digest": identity["candidate_digest"],
                                    "outputs": ["weekly_m67.json", "weekly_m67.md"]}), encoding="utf-8")
    (Path(tmp) / "official_publish.json").write_text(json.dumps({
        "schema_name": "a_short_egs_official_publish", "schema_version": "1.0.0", "trade_date": DECISION,
        "run_id": identity["run_id"], "candidate_digest": identity["candidate_digest"], "stage_status": "complete",
        "files": {
            "analysis_input": {"path": analysis_path.name, "sha256": hashlib.sha256(analysis_path.read_bytes()).hexdigest()},
            "egs_weight_comparison": {"path": comparison_path.name, "sha256": hashlib.sha256(comparison_path.read_bytes()).hexdigest()},
        },
    }), encoding="utf-8")
    return analysis_path, comparison_path, out, identity


def _capture(root: Path, tmp: str, *, same_profiles: bool = False) -> dict:
    analysis, comparison, out, identity = _sources(tmp, same_profiles=same_profiles)
    with mock.patch("engine.a_short_industry_weight_comparison._today", return_value=RUN):
        return capture_after_published_weekly(root=root, decision_date=DECISION, run_date=RUN,
                                              analysis_input_path=analysis, weight_comparison_path=comparison,
                                              source_identity=identity, out_path=out,
                                              receipt_path=out.with_name("weekly_m67.receipt.json"),
                                              forward_eligible=True)


def _daily_cache(codes: list[str], *, missing_adjustment: bool = False) -> dict:
    stocks, limits = [], []
    for day_index, day in enumerate(_dates(date(2026, 2, 2), 24)):
        for code in codes:
            observed = not (missing_adjustment and day_index == 10)
            stocks.append({"ts_code": code, "trade_date": day, "open": 10.0 + day_index,
                           "close": 10.5 + day_index, "adj_factor": 2.0 if observed else None,
                           "adj_factor_observed": observed,
                           "adj_factor_source": "provider_observed" if observed else "provider_missing",
                           "corporate_action_verified": False})
            limits.append({"ts_code": code, "trade_date": day, "up_limit": 100.0})
    return {"schema_name": "a_short_factor_comparison_v2_daily_cache", "schema_version": "1.0.0",
            "stocks": stocks, "limits": limits,
            "meta": {"cache_kind": "test", "source": "test"}}


class FakeTushare:
    def __init__(self):
        self.calls = []

    @staticmethod
    def _days(start: str, end: str) -> list[str]:
        current, finish, result = date(int(start[:4]), int(start[4:6]), int(start[6:])), date(int(end[:4]), int(end[4:6]), int(end[6:])), []
        while current <= finish:
            if current.weekday() < 5:
                result.append(current.strftime("%Y%m%d"))
            current += timedelta(days=1)
        return result

    def trade_cal(self, **kwargs):
        self.calls.append(("trade_cal", kwargs)); return pd.DataFrame({"cal_date": self._days(kwargs["start_date"], kwargs["end_date"])})

    def daily(self, **kwargs):
        self.calls.append(("daily", kwargs)); return pd.DataFrame([{"ts_code": kwargs["ts_code"], "trade_date": day, "open": 10.0, "close": 10.2} for day in self._days(kwargs["start_date"], kwargs["end_date"])])

    def adj_factor(self, **kwargs):
        self.calls.append(("adj_factor", kwargs)); return pd.DataFrame([{"ts_code": kwargs["ts_code"], "trade_date": day, "adj_factor": 2.0} for day in self._days(kwargs["start_date"], kwargs["end_date"])])

    def stk_limit(self, **kwargs):
        self.calls.append(("stk_limit", kwargs)); return pd.DataFrame([{"ts_code": kwargs["ts_code"], "trade_date": day, "up_limit": 100.0} for day in self._days(kwargs["start_date"], kwargs["end_date"])])


class IndustryWeightComparisonTests(unittest.TestCase):
    def setUp(self):
        # These cases assert the ENFORCED epoch contract (the historical default).
        # Pre-freeze behaviour is covered by tests/test_a_short_evidence_epoch_mode.py.
        enter_patched_epoch_modes(self, "frozen_enforced")

    def test_governance_is_exactly_tied_to_production_profile_weights(self):
        governance = load_governance()
        self.assertEqual(governance["program_id"], PROGRAM_ID)
        self.assertEqual(governance["outcome_contract"]["horizons_trading_days"], [5, 10, 20])
        self.assertTrue(governance["boundary"]["comparison_only"])
        self.assertFalse(governance["boundary"]["automatic_policy_switch"])

    def test_runtime_source_drift_changes_p5_contract_fingerprint(self):
        governance = load_governance()
        baseline = _contract_fingerprint(governance)
        with mock.patch("engine.a_short_industry_weight_comparison._runtime_source_fingerprint",
                        return_value="runtime-source-drift"):
            self.assertNotEqual(_contract_fingerprint(governance), baseline)

    def test_pre_freeze_accepts_a_source_bound_bundle_published_before_parking(self):
        """Old valid P5 bundles must not become uncapturable when parking lands."""
        with tempfile.TemporaryDirectory() as tmp, \
                patched_epoch_modes("pre_freeze_audit_only", ("p5_industry_weight",)):
            root = _p5_root(tmp)
            analysis, comparison_path, out, identity = _sources(tmp)
            comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
            comparison["source_fingerprint"] = "a" * 64
            comparison_path.write_text(json.dumps(comparison), encoding="utf-8")
            marker_path = Path(tmp) / "official_publish.json"
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            marker["files"]["egs_weight_comparison"]["sha256"] = hashlib.sha256(
                comparison_path.read_bytes()
            ).hexdigest()
            marker_path.write_text(json.dumps(marker), encoding="utf-8")
            with mock.patch("engine.a_short_industry_weight_comparison._today", return_value=RUN):
                result = capture_after_published_weekly(
                    root=root, decision_date=DECISION, run_date=RUN,
                    analysis_input_path=analysis, weight_comparison_path=comparison_path,
                    source_identity=identity, out_path=out,
                    receipt_path=out.with_name("weekly_m67.receipt.json"),
                    forward_eligible=True,
                )
        self.assertEqual(result["status"], "captured_live_canonical")

    def test_frozen_capture_rejects_a_bundle_from_another_source_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _p5_root(tmp)
            analysis, comparison_path, out, identity = _sources(tmp)
            comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
            comparison["source_fingerprint"] = "a" * 64
            comparison_path.write_text(json.dumps(comparison), encoding="utf-8")
            marker_path = Path(tmp) / "official_publish.json"
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            marker["files"]["egs_weight_comparison"]["sha256"] = hashlib.sha256(
                comparison_path.read_bytes()
            ).hexdigest()
            marker_path.write_text(json.dumps(marker), encoding="utf-8")
            with mock.patch("engine.a_short_industry_weight_comparison._today", return_value=RUN):
                with self.assertRaises(IndustryWeightComparisonError):
                    capture_after_published_weekly(
                        root=root, decision_date=DECISION, run_date=RUN,
                        analysis_input_path=analysis, weight_comparison_path=comparison_path,
                        source_identity=identity, out_path=out,
                        receipt_path=out.with_name("weekly_m67.receipt.json"),
                        forward_eligible=True,
                    )

    def test_capture_is_source_bound_idempotent_and_drift_becomes_private_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _p5_root(tmp)
            self.assertEqual(_capture(root, tmp)["status"], "captured_live_canonical")
            self.assertEqual(_capture(root, tmp)["status"], "idempotent_existing_capture")
            comparison_path = Path(tmp) / "egs_weight_comparison.json"
            comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
            comparison["universe_digest"] = "f" * 64
            comparison_path.write_text(json.dumps(comparison), encoding="utf-8")
            marker_path = Path(tmp) / "official_publish.json"
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            marker["files"]["egs_weight_comparison"]["sha256"] = hashlib.sha256(comparison_path.read_bytes()).hexdigest()
            marker_path.write_text(json.dumps(marker), encoding="utf-8")
            analysis = Path(tmp) / "analysis_input.json"; out = Path(tmp) / "weekly_m67.json"
            identity = json.loads(analysis.read_text(encoding="utf-8"))["source"]["run_identity"]
            with mock.patch("engine.a_short_industry_weight_comparison._today", return_value=RUN):
                result = capture_after_published_weekly(root=root, decision_date=DECISION, run_date=RUN,
                    analysis_input_path=analysis, weight_comparison_path=comparison_path, source_identity=identity,
                    out_path=out, receipt_path=out.with_name("weekly_m67.receipt.json"), forward_eligible=True)
            self.assertEqual(result["status"], "conflict_recorded_no_count")
            self.assertTrue((root / "conflicts" / f"{DECISION}.json").is_file())

    def test_same_list_week_is_eligible_zero_effect_with_fixed_slots_qfq_and_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _p5_root(tmp)
            _capture(root, tmp, same_profiles=True)
            capture = json.loads((root / "weeks" / DECISION / "capture.json").read_text(encoding="utf-8"))
            codes = sorted({row["ts_code"] for arm in capture["payload"]["profiles"].values() for row in arm["selected"]})
            settle_from_daily_payload(root=root, daily_payload=_daily_cache(codes), as_of=SETTLE_AS_OF)
            outcome = json.loads((root / "weeks" / DECISION / "outcome.json").read_text(encoding="utf-8"))
            for question in outcome["payload"]["questions"]:
                h10 = question["horizons"]["h10"]
                self.assertEqual(h10["status"], "settled")
                self.assertEqual(h10["whole_policy_effect_pct"], 0.0)
                self.assertTrue(h10["same_list_zero_effect"])
                self.assertLess(outcome["payload"]["questions"][0]["arms"]["legacy"]["h10"]["portfolio_net_return_pct"], 100.0)
            progress = build_public_progress(root=root, as_of=SETTLE_AS_OF)
            self.assertTrue(all(row["progress"]["eligible_policy_weeks"] == 1 and row["progress"]["difference_weeks"] == 0 for row in progress["questions"]))

    def test_missing_observed_adjustment_is_no_count_not_zero_or_backfill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _p5_root(tmp)
            _capture(root, tmp, same_profiles=True)
            capture = json.loads((root / "weeks" / DECISION / "capture.json").read_text(encoding="utf-8"))
            codes = sorted({row["ts_code"] for arm in capture["payload"]["profiles"].values() for row in arm["selected"]})
            settle_from_daily_payload(root=root, daily_payload=_daily_cache(codes, missing_adjustment=True), as_of=SETTLE_AS_OF)
            progress = build_public_progress(root=root, as_of=SETTLE_AS_OF)
            self.assertTrue(all(row["progress"]["eligible_policy_weeks"] == 0 and row["progress"]["no_count_weeks"] == 1 and row["progress"]["mature_opportunities"] == 1 for row in progress["questions"]))

    def test_shared_cache_defers_p5_after_fixed_budget_without_v2_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            p5_root, v2_root = _p5_root(tmp), _v2_root(tmp)
            _capture(p5_root, tmp)
            provider = FakeTushare()
            v2_window = [{"decision_date": DECISION, "price_data_through": DECISION, "symbols": ["600999.SH"]}]
            with mock.patch("runners.a_short_factor_comparison_v2_cache_build._today", return_value=SETTLE_AS_OF), \
                    mock.patch("runners.a_short_factor_comparison_v2_cache_build._frozen_windows", return_value=v2_window):
                result = materialize_incremental_cache(root=v2_root, run_date=SETTLE_AS_OF,
                    max_provider_calls=4, pro=provider, industry_weight_root=p5_root)
            self.assertEqual(result["provider_calls"], 4)
            self.assertGreater(result["p5_deferred_due_to_budget"], 0)
            self.assertEqual([kind for kind, _ in provider.calls].count("daily"), 1)
            self.assertEqual([kwargs["ts_code"] for kind, kwargs in provider.calls if kind == "daily"], ["600999.SH"])
            self.assertTrue((v2_root / "daily_cache.json").is_file())

    def test_public_summary_is_deidentified_and_p5b_trigger_is_data_derived(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _p5_root(tmp); root.mkdir(parents=True)
            fingerprint = _contract_fingerprint(load_governance())
            epoch = _epoch_id(fingerprint)
            for index in range(36):
                decision = (date(2026, 1, 1) + timedelta(days=index)).strftime("%Y%m%d")
                capture_payload = {"admission_bindings": admission_snapshot(*ADMISSION_IDS),
                                   "contract_fingerprint": fingerprint}
                capture_payload["capture_payload_sha256"] = _digest(capture_payload)
                capture = {"schema_name": "a_short_industry_weight_comparison_private_record", "schema_version": "1.0.0",
                    "record_type": "capture", "program_id": PROGRAM_ID, "decision_date": decision, "epoch_id": epoch,
                    "contract_fingerprint": fingerprint, "payload": capture_payload, "boundary": _boundary()}
                outcome = {"schema_name": "a_short_industry_weight_comparison_private_record", "schema_version": "1.0.0",
                    "record_type": "outcome", "program_id": PROGRAM_ID, "decision_date": decision, "epoch_id": epoch,
                    "contract_fingerprint": fingerprint, "payload": {"questions": [{"question_id": question,
                        "same_list": False, "horizons": {"h10": {"status": "settled", "whole_policy_effect_pct": 0.1}}}
                        for question in ("balanced_vs_legacy", "aggressive_vs_balanced", "theme_double_vs_balanced")]}, "boundary": _boundary()}
                directory = root / "weeks" / decision; directory.mkdir(parents=True)
                (directory / "capture.json").write_text(json.dumps(capture), encoding="utf-8")
                (directory / "outcome.json").write_text(json.dumps(outcome), encoding="utf-8")
            summary = build_public_progress(root=root, as_of="20261231")
            validate_public_progress(summary)
            self.assertTrue(summary["p5b_implemented"])
            self.assertTrue(all(row["verdict"] in {"continue_accumulating", "manual_rollback_review_only", "do_not_promote"}
                                for row in summary["questions"]))
            json_path, md_path = Path(tmp) / "public.json", Path(tmp) / "public.md"
            write_public_progress(summary, json_path=json_path, markdown_path=md_path)
            public_text = json_path.read_text(encoding="utf-8").lower() + md_path.read_text(encoding="utf-8").lower()
            self.assertNotIn("ts_code", public_text)
            self.assertNotIn("price", public_text)
            self.assertNotIn("account", public_text)

    def test_public_writer_rejects_nonfinite_payload_without_creating_a_public_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "public.json"
            with self.assertRaises(ValueError):
                _atomic_write(path, {"nonfinite": float("nan")})
            self.assertFalse(path.exists())

    def test_tracked_public_pair_is_reproducible_from_the_writer_and_altered_field_is_detected(self):
        tracked_json = ROOT / "research" / "results" / "a_short" / "industry_weight_comparison_summary.json"
        tracked_md = tracked_json.with_suffix(".md")
        with patched_epoch_modes("pre_freeze_audit_only", ("p5_industry_weight",)):
            expected = build_public_progress(root=None, as_of="20260727")
            self.assertEqual(json.loads(tracked_json.read_text(encoding="utf-8")), expected)
            with tempfile.TemporaryDirectory() as tmp:
                generated_json, generated_md = Path(tmp) / "summary.json", Path(tmp) / "summary.md"
                write_public_progress(expected, json_path=generated_json, markdown_path=generated_md)
                self.assertEqual(tracked_md.read_text(encoding="utf-8"), generated_md.read_text(encoding="utf-8"))
            altered = copy.deepcopy(expected)
            altered["source_hash"] = "0" * 64
            self.assertNotEqual(json.loads(tracked_json.read_text(encoding="utf-8")), altered)

    def test_legacy_boundary_record_remains_readable(self):
        record = {"schema_name": "a_short_industry_weight_comparison_private_record", "schema_version": "1.0.0",
                  "record_type": "outcome", "program_id": PROGRAM_ID, "decision_date": DECISION,
                  "epoch_id": "a" * 64, "contract_fingerprint": "b" * 64, "payload": {},
                  "boundary": {**_boundary(), "p5b_implemented": False}}
        _validate_private_record(record)

    def test_historical_or_test_capture_never_starts_forward_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _p5_root(tmp)
            analysis, comparison, out, identity = _sources(tmp)
            result = capture_after_published_weekly(root=root, decision_date=DECISION, run_date=RUN,
                analysis_input_path=analysis, weight_comparison_path=comparison, source_identity=identity,
                out_path=out, receipt_path=out.with_name("weekly_m67.receipt.json"), forward_eligible=False)
            self.assertEqual(result["status"], "not_live_canonical_no_capture")
            self.assertFalse((root / "weeks").exists())

    def test_watch_pool_slot_count_matches_its_governance_declaration(self):
        """The fixed slot count exists in code and in governance; they must not drift.

        `selection_contract.selector` names `select_profile_watch_pool`, so
        `selection_contract.slots` and that function's `PROFILE_WATCH_POOL_TOP_N`
        are the same number described twice — and nothing compared them.
        """
        from engine import egs_industry_heat as heat
        governance = json.loads(
            (ROOT / "presets" / "a_short_industry_weight_comparison_governance_20260722.json")
            .read_text(encoding="utf-8"))
        selection = governance["selection_contract"]
        self.assertEqual(selection["selector"], "engine.egs_industry_heat.select_profile_watch_pool",
                         "the parity below is only valid while governance names this selector")
        self.assertEqual(selection["slots"], heat.PROFILE_WATCH_POOL_TOP_N)

    def test_weekly_p5_sidecar_is_schema_valid_and_does_not_change_m67_result(self):
        from runners.a_short_weekly_pipeline import SCHEMA_PATH, build_weekly_report, validate_weekly_report
        from tests.test_a_short_weekly_pipeline import _feed
        weekly = build_weekly_report([], "20260611", "2026-06-11T00:00:00+08:00")
        before = json.loads(json.dumps({key: weekly[key] for key in ("reports", "cash_allocation", "portfolio_risk", "boundary")}))
        weekly["industry_weight_comparison"] = build_public_progress(root=None, as_of="20260611")
        jsonschema.validate(weekly, json.loads(Path(SCHEMA_PATH).read_text(encoding="utf-8")))
        validate_weekly_report(weekly, _feed())
        self.assertEqual({key: weekly[key] for key in before}, before)


if __name__ == "__main__":
    unittest.main()
