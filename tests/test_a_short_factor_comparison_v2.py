"""Knife-1 v2 comparison evidence: capture/epoch/cache-only outcome boundaries."""
from __future__ import annotations

import copy
import hashlib
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
from engine import a_short_evidence_epoch_mode as _epoch_mode  # noqa: E402
from engine import a_short_factor_comparison_v2 as _p0  # noqa: E402
from engine.a_short_factor_comparison_v2 import (  # noqa: E402
    ComparisonV2Error, _ensure_program, _immutable_common_pool, _materialize_question, _maximum_drawdown, _position_outcomes, _resolve_epoch,
    build_v2_public_progress, capture_v2_week, is_current_governed_capture, load_v2_governance,
    settle_v2_from_daily_payload, validate_v2_decision_receipt, validate_v2_governance,
)
from engine.a_short_factor_comparison_v2_adjudication import adjudicate_v2_from_private_ledger  # noqa: E402
from tests._a_short_epoch_mode_test_utils import patched_epoch_modes  # noqa: E402


def _root(tmp: str) -> Path:
    return Path(tmp) / "state" / "a_short" / "factor_comparison_private" / "v2"


def _candidate(code: str, score: float) -> dict:
    series = []
    current = date(2025, 12, 23)
    for index in range(30):
        while current.weekday() >= 5:
            current += timedelta(days=1)
        close = 10.5 if index >= 20 else 10.2
        high = 15.0 if index in (22, 27) else close + 0.2
        low = 9.7 if index in (21, 26) else close - 0.2
        series.append({"trade_date": current.strftime("%Y%m%d"), "high": high,
                       "low": low, "close": close})
        current += timedelta(days=1)
    return {
        "ts_code": code, "name": code, "close": 10.5, "price_series": series,
        "egs_score": score, "derived": {}, "event": {}, "liquidity": {"avg_amount_5d": 1e9},
        "iv": {"iv_percentile_252d": 50.0, "iv_value": 0.20, "hv_value": 0.18},
        "market_regime": "进攻期", "regime_fallback": {}, "stateful_risk": {},
    }


def _candidates() -> list[dict]:
    return [_candidate(f"60000{index}.SH", 100.0 - index) for index in range(5)]


def _identity(decision_date: str = "20260202", candidates: list[dict] | None = None) -> dict:
    normalized = [v1._safe_candidate(row) for row in (candidates if candidates is not None else _candidates())]
    return {
        "run_id": f"offline-{decision_date}", "run_date": decision_date, "source_as_of": decision_date,
        "price_data_through": decision_date,
        "candidate_digest": v1._digest(normalized), "official_m67_digest": "b" * 64,
    }


def _dates(count: int) -> list[str]:
    current = date(2026, 2, 2)
    out = []
    while len(out) < count:
        if current.weekday() < 5:
            out.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return out


def _daily_payload(*, count: int = 24, observed: bool = True, source: str = "provider_observed",
                   adjustment_jump: bool = False, qfq_gap: bool = False) -> dict:
    rows = []
    for code_index in range(5):
        factor = 1.0
        for index, trade_date in enumerate(_dates(count)):
            if adjustment_jump and index == 8:
                factor = 5.0
            close = 10.5 if index == 0 else 10.0
            if qfq_gap and index == 8:
                close = 30.0
            rows.append({
                "ts_code": f"60000{code_index}.SH", "trade_date": trade_date,
                "open": 10.0, "close": close, "adj_factor": factor,
                "adj_factor_observed": observed, "adj_factor_source": source,
                "corporate_action_verified": False,
            })
    limits = [
        {"ts_code": row["ts_code"], "trade_date": row["trade_date"],
         "up_limit": 11.0, "down_limit": 9.0, "provider_observed": True}
        for row in rows
    ]
    return {
        "stocks": pd.DataFrame(rows),
        "limits": pd.DataFrame(limits),
        "meta": {"cache_kind": "fixture_only"},
    }


def _capture(root: Path, *, decision_date: str = "20260202", governance: dict | None = None,
             candidates: list[dict] | None = None, forward_eligible: bool = True) -> dict:
    snapshot = _candidates() if candidates is None else candidates
    kwargs = {
        "root": root, "decision_date": decision_date, "candidates": snapshot,
        "run_identity": _identity(decision_date, snapshot), "forward_eligible": forward_eligible,
        "governance": governance,
    }
    if forward_eligible:
        with mock.patch("engine.a_short_factor_comparison_v2._today", return_value=decision_date):
            return capture_v2_week(**kwargs)
    return capture_v2_week(**kwargs)


class GovernanceAndCaptureTests(unittest.TestCase):
    def test_governance_is_dynamic_but_ordered_arms_are_the_only_authority(self):
        governance = load_v2_governance()
        self.assertEqual([row["question_id"] for row in governance["questions"]], ["d1_entry_anchor", "d3_iv_policy"])
        reordered_object_keys = json.loads(json.dumps(governance, ensure_ascii=False, sort_keys=True))
        validate_v2_governance(reordered_object_keys)
        broken = copy.deepcopy(governance)
        broken["questions"][0]["arms"] = list(reversed(broken["questions"][0]["arms"]))
        with self.assertRaises(ComparisonV2Error):
            validate_v2_governance(broken)

    def test_baseline_parity_reuses_current_phase5_primitives_not_a_second_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            result = _capture(root)
            capture = result["capture"]
            question = capture["payload"]["questions"][0]
            captured = question["arms"][0]
            v1_governance = v1.load_governance()
            candidates = [v1._safe_candidate(row) for row in _candidates()]
            direct = v1._policy_result(
                candidates, "baseline", None, v1_governance, "20260202", True, v1._digest(candidates),
                v1.unavailable_realized_regime(v1_governance, "v2_capture_not_weekly_wired"),
            )
            self.assertEqual(captured["selected_symbols"], direct["selection"]["selected_symbols"])
            self.assertEqual(captured["decisions"], direct["selection"]["decisions"])

    def test_capture_is_idempotent_but_rejects_input_and_date_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            self.assertEqual(_capture(root)["status"], "captured")
            self.assertEqual(_capture(root)["status"], "already_captured")
            altered = _candidates()
            altered[0]["iv"]["iv_percentile_252d"] = 95.0
            with self.assertRaises(ComparisonV2Error):
                _capture(root, candidates=altered)
            identity = _identity()
            identity["run_date"] = "20260203"
            with self.assertRaises(ComparisonV2Error):
                capture_v2_week(root=root, decision_date="20260202", candidates=_candidates(),
                                run_identity=identity, forward_eligible=True)
            missing_price_clock = _identity()
            missing_price_clock.pop("price_data_through")
            with self.assertRaises(ComparisonV2Error):
                capture_v2_week(root=root, decision_date="20260202", candidates=_candidates(),
                                run_identity=missing_price_clock, forward_eligible=False)
            future = _candidates()
            future[0]["price_series"][-1]["trade_date"] = "20260203"
            with self.assertRaises(ComparisonV2Error):
                _capture(Path(tmp) / "other" / "state" / "a_short" / "factor_comparison_private" / "v2",
                         candidates=future)
            stale = _candidates()
            stale[0]["price_series"][-1]["trade_date"] = "20260130"
            with self.assertRaises(ComparisonV2Error):
                _capture(Path(tmp) / "stale" / "state" / "a_short" / "factor_comparison_private" / "v2",
                         candidates=stale)

    def test_pre_registered_combination_batch_runs_capture_ledger_and_adjudication_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            batch_id = "batch_d1_d3_combo_001"
            registry_path = root / "experiment_batches.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["combination_batches"].append({
                    "experiment_batch_id": batch_id, "component_question_ids": ["d1_entry_anchor", "d3_iv_policy"],
                    "accepted_components": [
                        {"question_id": "d1_entry_anchor", "arm_id": "entry_ma_pullback", "receipt_sha256": "1" * 64},
                        {"question_id": "d3_iv_policy", "arm_id": "iv_step_down", "receipt_sha256": "2" * 64},
                    ], "accepted_receipt_sha256s": ["1" * 64, "2" * 64],
                    "new_forward_evidence_required": True, "historical_backfill_forbidden": True,
                    "pre_registered_combination_question_required": True,
                })
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            governance = load_v2_governance()
            governance["questions"].append({
                "question_id": "d1_d3_entry_ma_iv_step_combo", "title": "D1+D3 pre-registered combination",
                "question_type": "combination_policy", "experiment_batch_id": batch_id,
                "multiplicity_family_id": "d1_d3_combo_family", "allow_combination": True,
                "component_factor_ids": ["entry_ma_pullback", "iv_step_down"],
                "effect_surface": "combined_policy",
                "common_pool_seam": "same_pit_candidate_universe_after_non_iv_immutable_hard_gates",
                "ordered_arm_ids": ["baseline", "entry_ma_iv_step_combo"],
                "arms": [
                    {"arm_id": "baseline", "kind": "baseline", "factor_id": None, "effect_surface": "none", "one_change_only": True},
                    {"arm_id": "entry_ma_iv_step_combo", "kind": "challenger", "factor_id": "entry_ma_iv_step_combo",
                     "effect_surface": "combined_policy", "one_change_only": True},
                ],
            })
            candidates = _candidates()
            current = date(2026, 2, 3)
            while current <= date(2026, 2, 9):
                if current.weekday() < 5:
                    for candidate in candidates:
                        candidate["price_series"].append({"trade_date": current.strftime("%Y%m%d"),
                                                          "high": 10.7, "low": 10.3, "close": 10.5})
                current += timedelta(days=1)
            with self.assertRaises(ComparisonV2Error):
                _capture(root, decision_date="20260209", candidates=candidates, governance=governance)
            receipts = []
            for question_id, arm_id, digest in [
                ("d1_entry_anchor", "entry_ma_pullback", "1" * 64),
                ("d3_iv_policy", "iv_step_down", "2" * 64),
            ]:
                receipts.append({"receipt_sha256": digest, "receipt": {
                    "schema_name": "a_short_factor_comparison_v2_decision_receipt", "schema_version": "2.0.0",
                    "program_id": "a_short_factor_comparison_v2", "question_id": question_id, "arm_id": arm_id,
                    "epoch_id": "epoch-0123456789ab",
                    "experiment_batch_id": "batch_20260718_d1_entry_anchor" if question_id.startswith("d1") else "batch_20260718_d3_iv_policy",
                    "verdict_sha256": digest, "comparison_contract_sha256": "3" * 64,
                    "arm_definition_sha256": "4" * 64, "status": "pending", "decision": None,
                    "decided_at": None, "boundary": {"production": False, "automatic_policy_switch": False},
                }})
            receipt_path = root / "decision_receipts.json"
            receipt_path.write_text(json.dumps({"schema_name": "a_short_factor_comparison_v2_decision_receipts",
                                                 "schema_version": "2.0.0", "program_id": "a_short_factor_comparison_v2",
                                                 "receipts": receipts,
                                                 "boundary": {"production": False, "automatic_policy_switch": False}}),
                                    encoding="utf-8")
            with self.assertRaises(ComparisonV2Error):
                _capture(root, decision_date="20260209", candidates=candidates, governance=governance)
            for row in receipts:
                row["receipt"]["status"] = "accepted"
                row["receipt"]["decision"] = "accepted"
                row["receipt"]["decided_at"] = "20260209T000000Z"
            receipt_path.write_text(json.dumps({"schema_name": "a_short_factor_comparison_v2_decision_receipts",
                                                 "schema_version": "2.0.0", "program_id": "a_short_factor_comparison_v2",
                                                 "receipts": receipts,
                                                 "boundary": {"production": False, "automatic_policy_switch": False}}),
                                    encoding="utf-8")
            wrong_component_question = copy.deepcopy(registry)
            wrong_component_question["combination_batches"][0]["accepted_components"][1]["question_id"] = "d1_entry_anchor"
            registry_path.write_text(json.dumps(wrong_component_question), encoding="utf-8")
            with self.assertRaises(ComparisonV2Error):
                _capture(root, decision_date="20260209", candidates=candidates, governance=governance)
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            capture = _capture(root, decision_date="20260209", candidates=candidates, governance=governance)["capture"]
            combo_capture = next(row for row in capture["payload"]["questions"]
                                 if row["question_id"] == "d1_d3_entry_ma_iv_step_combo")
            self.assertEqual(combo_capture["experiment_batch_id"], batch_id)
            daily = _daily_payload(count=30)
            daily["stocks"].loc[daily["stocks"]["trade_date"] == "20260209", "close"] = 10.5
            settle_v2_from_daily_payload(root=root, daily_payload=daily, governance=governance)
            ledger = json.loads((root / "ledger.json").read_text(encoding="utf-8"))
            self.assertTrue(any(row["question_id"] == "d1_d3_entry_ma_iv_step_combo" and
                                row["experiment_batch_id"] == batch_id for row in ledger["entries"]))
            result = adjudicate_v2_from_private_ledger(root=root, governance=governance)
            combo = next(row for row in result["adjudication"]["questions"]
                         if row["question_id"] == "d1_d3_entry_ma_iv_step_combo")
            self.assertEqual(combo["experiment_batch_id"], batch_id)
            self.assertEqual(combo["effective_difference_weeks"], 1)
            restarted_registry = json.loads(registry_path.read_text(encoding="utf-8"))
            combo_batch = next(row for row in restarted_registry["questions"]
                               if row["question_id"] == "d1_d3_entry_ma_iv_step_combo")
            combo_batch["prior_experiment_batch_ids"].append(batch_id)
            combo_batch["active_experiment_batch_id"] = "batch_d1_d3_combo_002"
            combo_batch["activation_kind"] = "new_forward_combination_batch"
            registry_path.write_text(json.dumps(restarted_registry), encoding="utf-8")
            restarted = adjudicate_v2_from_private_ledger(root=root, governance=governance)["adjudication"]
            restarted_combo = next(row for row in restarted["questions"]
                                   if row["question_id"] == "d1_d3_entry_ma_iv_step_combo")
            self.assertEqual(restarted_combo["experiment_batch_id"], "batch_d1_d3_combo_002")
            self.assertEqual(restarted_combo["effective_difference_weeks"], 0)

    def test_capture_rejects_a_run_identity_digest_not_derived_from_the_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidates = _candidates()
            identity = _identity(candidates=candidates)
            identity["candidate_digest"] = "a" * 64
            with mock.patch("engine.a_short_factor_comparison_v2._today", return_value="20260202"):
                with self.assertRaises(ComparisonV2Error):
                    capture_v2_week(root=_root(tmp), decision_date="20260202", candidates=candidates,
                                    run_identity=identity, forward_eligible=True)

    def test_forward_flag_cannot_be_minted_for_a_noncurrent_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("engine.a_short_factor_comparison_v2._today", return_value="20260203"):
                with self.assertRaises(ComparisonV2Error):
                    capture_v2_week(root=_root(tmp), decision_date="20260202", candidates=_candidates(),
                                    run_identity=_identity(), forward_eligible=True)

    def test_hidden_second_effect_or_reallocation_is_rejected_before_capture(self):
        governance = load_v2_governance()
        governance["questions"][0]["arms"][1]["effect_surface"] = "iv_policy"
        with self.assertRaises(ComparisonV2Error):
            validate_v2_governance(governance)
        governance = load_v2_governance()
        governance["questions"][0]["arms"][1]["allocation"] = "hidden_reallocation"
        with self.assertRaises(Exception):
            validate_v2_governance(governance)

    def test_common_pool_defers_only_iv_and_excludes_contraction(self):
        iv_only = _candidate("600000.SH", 100.0)
        iv_only["iv"]["iv_percentile_252d"] = 95.0
        contraction = _candidate("600001.SH", 99.0)
        contraction["iv"]["iv_percentile_252d"] = 95.0
        contraction["market_regime"] = "收缩期"

        pool = _immutable_common_pool([iv_only, contraction])

        self.assertEqual(pool["seam"], "same_pit_candidate_universe_after_non_iv_immutable_hard_gates")
        self.assertIn(iv_only["ts_code"], pool["symbols"])
        self.assertIn(iv_only["ts_code"], pool["iv_policy_deferred"])
        self.assertNotIn(contraction["ts_code"], pool["symbols"])
        self.assertEqual(pool["rejected"][contraction["ts_code"]], ["market_regime:contraction_no_new_entry"])

        question = load_v2_governance()["questions"][1]
        materialized = _materialize_question(
            question, [iv_only, contraction], decision_date="20260202", forward_eligible=True,
            v1_governance=v1.load_governance(), common_pool=pool,
            experiment_batch_id=question["experiment_batch_id"],
        )
        for arm in materialized["arms"]:
            self.assertNotIn(contraction["ts_code"], [row["ts_code"] for row in arm["decisions"]])

    def test_private_v2_root_and_legacy_v1_root_cannot_be_mixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ComparisonV2Error):
                _capture(Path(tmp) / "state" / "a_short" / "factor_comparison_private")
            with self.assertRaises(ComparisonV2Error):
                _capture(ROOT / "result" / "a_short" / "factor_comparison_private" / "v2")

    def test_partial_week_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            day = root / "weeks" / "20260202"
            day.mkdir(parents=True)
            (day / "orphan.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ComparisonV2Error):
                _capture(root)


class ProgramManifestTests(unittest.TestCase):
    def test_pre_freeze_accepts_legacy_raw_schema_digests_without_rewriting_manifest(self):
        with tempfile.TemporaryDirectory() as tmp, patched_epoch_modes(
                "pre_freeze_audit_only", ("p0_factor_comparison_v2",)):
            root = _root(tmp)
            governance = load_v2_governance()
            _ensure_program(root, governance)
            path = root / "program_manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            schema_paths = {
                "governance_schema_sha256": _p0.PROGRAM_SCHEMA_PATH,
                "weekly_schema_sha256": _p0.WEEKLY_SCHEMA_PATH,
                "ledger_schema_sha256": _p0.LEDGER_SCHEMA_PATH,
                "decision_receipt_schema_sha256": _p0.RECEIPT_SCHEMA_PATH,
            }
            raw_digests = {
                field: hashlib.sha256(schema_path.read_bytes()).hexdigest()
                for field, schema_path in schema_paths.items()
            }
            self.assertTrue(any(manifest[field] != value for field, value in raw_digests.items()))
            manifest.update(raw_digests)
            path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            before = path.read_bytes()
            _ensure_program(root, governance)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(_capture(root, governance=governance)["status"], "captured")
            self.assertFalse(_epoch_mode.evidence_counts_toward_clock("p0_factor_comparison_v2"))

    def test_pre_freeze_still_rejects_program_identity_and_boundary_drift(self):
        for field, value in (("program_id", "other_program"), ("boundary", {"production": True})):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp, patched_epoch_modes(
                    "pre_freeze_audit_only", ("p0_factor_comparison_v2",)):
                root = _root(tmp)
                governance = load_v2_governance()
                _ensure_program(root, governance)
                path = root / "program_manifest.json"
                manifest = json.loads(path.read_text(encoding="utf-8"))
                manifest[field] = value
                path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(ComparisonV2Error, "v2 program manifest drifted"):
                    _ensure_program(root, governance)

    def test_pre_freeze_rejects_malformed_digest_shape(self):
        for value in (None, "not-a-digest", "0" * 63, "g" * 64):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp, patched_epoch_modes(
                    "pre_freeze_audit_only", ("p0_factor_comparison_v2",)):
                root = _root(tmp)
                governance = load_v2_governance()
                _ensure_program(root, governance)
                path = root / "program_manifest.json"
                manifest = json.loads(path.read_text(encoding="utf-8"))
                manifest["weekly_schema_sha256"] = value
                path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(ComparisonV2Error, "v2 program manifest drifted"):
                    _ensure_program(root, governance)

    def test_frozen_manifest_digest_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patched_epoch_modes(
                "frozen_enforced", ("p0_factor_comparison_v2",)):
            root = _root(tmp)
            governance = load_v2_governance()
            _ensure_program(root, governance)
            path = root / "program_manifest.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["weekly_schema_sha256"] = "0" * 64
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ComparisonV2Error, "v2 program manifest drifted"):
                _ensure_program(root, governance)


class EpochTests(unittest.TestCase):
    def test_each_orthogonality_dimension_starts_a_new_epoch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            governance = load_v2_governance()
            original = __import__("engine.a_short_factor_comparison_v2", fromlist=["_canonical_contracts"])._canonical_contracts(governance)
            for field in ("decision_delta_contract", "immutable_common_pool_contract", "outcome_contract",
                          "runtime_wiring_contract"):
                changed = copy.deepcopy(original)
                changed[field] = "f" * 64
                with mock.patch("engine.a_short_factor_comparison_v2._canonical_contracts", return_value=changed):
                    epoch = _resolve_epoch(root, governance, "20260302")
                self.assertEqual(epoch["reason"], "nonorthogonal_contract_change")
            epochs = json.loads((root / "epochs.json").read_text(encoding="utf-8"))["epochs"]
            self.assertEqual(len(epochs), 5)


class CacheOutcomeTests(unittest.TestCase):
    def test_public_progress_has_only_epoch_arm_hashes_and_no_private_capture_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            settle_v2_from_daily_payload(root=root, daily_payload=_daily_payload())
            summary = build_v2_public_progress(root=root, as_of="20260306")
            self.assertIsNotNone(summary["current_epoch_id"])
            self.assertTrue(summary["evidence"])
            self.assertTrue(all(row["activation_permitted"] is False and row["verdict"] == "not_adjudicated"
                                for row in summary["evidence"]))
            public_text = json.dumps(summary, ensure_ascii=False).lower()
            for forbidden in ("ts_code", "price_series", "close", "account", "holding"):
                self.assertNotIn(forbidden, public_text)

    def test_runtime_epoch_signature_drift_excludes_old_capture_from_current_settlement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            capture = _capture(root)["capture"]
            self.assertTrue(is_current_governed_capture(capture))
            capture["payload"]["orthogonality_signature"]["runtime_wiring_contract"] = "0" * 64
            self.assertFalse(is_current_governed_capture(capture))

    def test_settlement_rehashes_capture_and_rejects_tampered_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            capture_path = root / "weeks" / "20260202" / "capture.json"
            capture = json.loads(capture_path.read_text(encoding="utf-8"))
            capture["payload"]["candidate_universe"][0]["close"] = 99.0
            capture_path.write_text(json.dumps(capture), encoding="utf-8")
            with self.assertRaises(ComparisonV2Error):
                settle_v2_from_daily_payload(root=root, daily_payload=_daily_payload())

    def test_settlement_rejects_capture_rewritten_without_a_matching_source_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            capture_path = root / "weeks" / "20260202" / "capture.json"
            capture = json.loads(capture_path.read_text(encoding="utf-8"))
            capture["payload"]["questions"][0]["arms"][0]["eligible_symbols"] = ["tampered.SH"]
            unsigned = {key: value for key, value in capture["payload"].items() if key != "capture_sha256"}
            capture["payload"]["capture_sha256"] = v1._digest(unsigned)
            capture_path.write_text(json.dumps(capture), encoding="utf-8")
            with self.assertRaises(ComparisonV2Error):
                settle_v2_from_daily_payload(root=root, daily_payload=_daily_payload())

    def test_complete_observed_adjustment_produces_private_cache_only_evidence_and_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            result = settle_v2_from_daily_payload(root=root, daily_payload=_daily_payload())
            self.assertEqual(result["status"], "settled_from_existing_cache")
            outcome = json.loads((root / "weeks" / "20260202" / "outcome.json").read_text(encoding="utf-8"))
            self.assertEqual([row["status"] for row in outcome["payload"]["questions"]], ["settled", "settled"])
            for question in outcome["payload"]["questions"]:
                for arm in question["arms"]:
                    self.assertIn("max_drawdown_pct", arm["outcome"]["risk_evidence"])
                    self.assertEqual(arm["outcome"]["risk_evidence"]["adjustment_coverage_pct"], 100.0)
            ledger = json.loads((root / "ledger.json").read_text(encoding="utf-8"))
            self.assertEqual(len(ledger["entries"]), 2)
            self.assertTrue(all(row["outcome_status"] == "settled" for row in ledger["entries"]))
            self.assertEqual({row["experiment_batch_id"] for row in ledger["entries"]},
                             {"batch_20260718_d1_entry_anchor", "batch_20260718_d3_iv_policy"})
            capture = json.loads((root / "weeks" / "20260202" / "capture.json").read_text(encoding="utf-8"))
            self.assertEqual([row["experiment_batch_id"] for row in capture["payload"]["questions"]],
                             ["batch_20260718_d1_entry_anchor", "batch_20260718_d3_iv_policy"])
            self.assertTrue(result["production_unchanged"])

    def test_unmatured_h20_stays_pending_without_a_fake_effective_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            settle_v2_from_daily_payload(root=root, daily_payload=_daily_payload(count=12))
            outcome = json.loads((root / "weeks" / "20260202" / "outcome.json").read_text(encoding="utf-8"))
            self.assertEqual([row["status"] for row in outcome["payload"]["questions"]], ["pending", "pending"])
            ledger = json.loads((root / "ledger.json").read_text(encoding="utf-8"))
            self.assertTrue(all(row["outcome_status"] == "pending" for row in ledger["entries"]))

    def test_ffill_default_or_missing_adjustment_provenance_keeps_question_pending_and_records_each_arm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            settle_v2_from_daily_payload(root=root, daily_payload=_daily_payload(observed=False, source="provider_ffill"))
            outcome = json.loads((root / "weeks" / "20260202" / "outcome.json").read_text(encoding="utf-8"))
            question = outcome["payload"]["questions"][0]
            self.assertEqual(question["status"], "pending")
            self.assertEqual(question["reason"], "adj_factor_not_observed")
            self.assertTrue(all(row["pending_count"] == 1 for row in question["arms"]))

    def test_unverified_adjustment_or_qfq_price_jump_keeps_question_pending(self):
        for payload in (_daily_payload(adjustment_jump=True), _daily_payload(qfq_gap=True)):
            with self.subTest(payload=payload):
                with tempfile.TemporaryDirectory() as tmp:
                    root = _root(tmp)
                    _capture(root)
                    settle_v2_from_daily_payload(root=root, daily_payload=payload)
                    outcome = json.loads((root / "weeks" / "20260202" / "outcome.json").read_text(encoding="utf-8"))
                    self.assertEqual(outcome["payload"]["questions"][0]["status"], "pending")

    def test_d3_measured_iv_gate_uses_the_same_adjustment_pending_rule_when_it_selects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            candidates = _candidates()
            for candidate in candidates:
                candidate["iv"]["iv_percentile_252d"] = 95.0
                candidate["derived"]["breakout"] = True
                for index, row in enumerate(candidate["price_series"]):
                    row["low"] = 10.4
                    if index in (22, 27):
                        row["high"] = 15.0
            _capture(root, candidates=candidates)
            settle_v2_from_daily_payload(root=root, daily_payload=_daily_payload(observed=False, source="provider_ffill"))
            outcome = json.loads((root / "weeks" / "20260202" / "outcome.json").read_text(encoding="utf-8"))
            d3 = outcome["payload"]["questions"][1]
            self.assertEqual(d3["status"], "pending")
            self.assertTrue(any(row["selected_symbols"] for row in d3["arms"]))

    def test_terminal_source_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            settle_v2_from_daily_payload(root=root, daily_payload=_daily_payload())
            drifted = _daily_payload()
            drifted["stocks"].loc[0, "close"] = 11.0
            with self.assertRaises(ComparisonV2Error):
                settle_v2_from_daily_payload(root=root, daily_payload=drifted)

    def test_settled_capture_replay_is_still_idempotent_and_unrelated_cache_growth_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root)
            settle_v2_from_daily_payload(root=root, daily_payload=_daily_payload())
            self.assertEqual(_capture(root)["status"], "already_captured")
            grown = _daily_payload()
            grown["stocks"] = pd.concat([
                grown["stocks"],
                pd.DataFrame([{"ts_code": "999999.SH", "trade_date": "20260306", "open": 1.0, "close": 1.0,
                               "adj_factor": 1.0, "adj_factor_observed": True,
                               "adj_factor_source": "provider_observed", "corporate_action_verified": False}]),
            ], ignore_index=True)
            self.assertEqual(settle_v2_from_daily_payload(root=root, daily_payload=grown)["status"],
                             "settled_from_existing_cache")
            ledger = json.loads((root / "ledger.json").read_text(encoding="utf-8"))
            self.assertEqual(len(ledger["entries"]), 2)

    def test_historical_capture_can_be_diagnosed_but_is_explicitly_not_forward_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _capture(root, forward_eligible=False)
            settle_v2_from_daily_payload(root=root, daily_payload=_daily_payload())
            ledger = json.loads((root / "ledger.json").read_text(encoding="utf-8"))
            self.assertTrue(all(row["forward_eligible"] is False for row in ledger["entries"]))


class ReceiptSchemaTests(unittest.TestCase):
    def test_future_decision_receipt_schema_is_frozen_without_emitting_a_decision_in_knife_one(self):
        receipt = {
            "schema_name": "a_short_factor_comparison_v2_decision_receipt", "schema_version": "2.0.0",
            "program_id": "a_short_factor_comparison_v2", "question_id": "d1_entry_anchor",
            "arm_id": "entry_ma_pullback", "epoch_id": "epoch-0123456789ab", "experiment_batch_id": "batch-a",
            "verdict_sha256": "c" * 64, "comparison_contract_sha256": "d" * 64,
            "arm_definition_sha256": "e" * 64, "status": "pending", "decision": None, "decided_at": None,
            "boundary": {"production": False, "automatic_policy_switch": False},
        }
        validate_v2_decision_receipt(receipt)


class RiskEvidenceTests(unittest.TestCase):
    def _single_position_inputs(self, *, close_path: list[float]) -> tuple[dict, dict, dict, dict, list[str], dict]:
        dates = _dates(21)
        code = "600000.SH"
        lookup = {
            (code, trade_date): {
                "open": 100.0,
                "close": close_path[index],
                "adj_factor": 1.0,
                "raw_provider_observed": True,
                "adj_factor_observed": True,
                "adj_factor_source": "provider_observed",
            }
            for index, trade_date in enumerate(dates)
        }
        arm = {
            "decision_date": dates[0], "slots": 1, "selected_symbols": [code],
            "decisions": [{"ts_code": code, "selected": True,
                           "plan": {"entry": 100.0, "entry_low": 50.0, "entry_high": 150.0}}],
        }
        governance = load_v2_governance()
        governance["outcome_contract"]["cost_pct"] = 0.0
        return arm, {code: {"close": close_path[0]}}, {day: index for index, day in enumerate(dates)}, lookup, dates, governance

    def test_max_drawdown_uses_cumulative_nav_path_not_period_compounding(self):
        self.assertAlmostEqual(_maximum_drawdown([5.0, -10.0, 5.0]), 14.2857142857, places=8)
        self.assertAlmostEqual(_maximum_drawdown([30.0, 10.0, 30.0]), 15.3846153846, places=8)

        arm, candidates, date_pos, lookup, dates, governance = self._single_position_inputs(
            close_path=[100.0, 130.0, 110.0] + [130.0] * 18,
        )
        limits = {("600000.SH", day): 110.0 for day in dates}
        outcome, _ = _position_outcomes(arm=arm, candidates=candidates, price_data_through=dates[0], date_pos=date_pos, dates=dates,
                                        lookup=lookup, limits=limits, governance=governance)
        self.assertAlmostEqual(outcome["risk_evidence"]["max_drawdown_pct"], 15.3846153846, places=8)

    def test_settlement_requires_frozen_decision_close(self):
        arm, candidates, date_pos, lookup, dates, governance = self._single_position_inputs(
            close_path=[100.0] * 21,
        )
        candidates["600000.SH"]["close"] = 99.0
        with self.assertRaisesRegex(ComparisonV2Error, "price_data_through close drifts"):
            limits = {("600000.SH", day): 110.0 for day in dates}
            _position_outcomes(arm=arm, candidates=candidates, price_data_through=dates[0], date_pos=date_pos, dates=dates,
                               lookup=lookup, limits=limits, governance=governance)

    def test_loss_distribution_is_filled_only_and_records_its_basis(self):
        dates = _dates(21)
        filled_code = "600000.SH"
        unfilled_codes = [f"60000{index}.SH" for index in range(1, 6)]
        codes = [filled_code, *unfilled_codes]
        lookup = {}
        for code in codes:
            for index, trade_date in enumerate(dates):
                lookup[(code, trade_date)] = {
                "open": 100.0,
                "close": 100.0 if index == 0 else 90.0,
                "adj_factor": 1.0,
                "raw_provider_observed": True,
                "adj_factor_observed": True,
                "adj_factor_source": "provider_observed",
                }
        arm = {
            "decision_date": dates[0], "slots": 6, "selected_symbols": codes,
            "decisions": [
                {"ts_code": code, "selected": True, "plan": {
                    "entry": 100.0,
                    "entry_low": 50.0 if code == filled_code else 200.0,
                    "entry_high": 150.0 if code == filled_code else 300.0,
                }}
                for code in codes
            ],
        }
        governance = load_v2_governance()
        governance["outcome_contract"]["cost_pct"] = 0.0
        outcome, counts = _position_outcomes(
            arm=arm, candidates={code: {"close": 100.0} for code in codes},
            price_data_through=dates[0],
            date_pos={day: index for index, day in enumerate(dates)}, dates=dates,
            lookup=lookup,
            limits={(code, day): 110.0 for code in codes for day in dates},
            governance=governance,
        )
        risk = outcome["risk_evidence"]
        self.assertEqual(counts, {"selected_count": 6, "filled_count": 1})
        self.assertEqual(risk["loss_distribution_basis"], "filled_positions_only")
        self.assertEqual(risk["loss_distribution_count"], 1)
        self.assertEqual(risk["bad_name_rate"], 1.0)
        self.assertAlmostEqual(risk["tail_loss_pct"], -10.0)
        self.assertAlmostEqual(risk["cash_drag_pct"], 100.0 * 5.0 / 6.0)


if __name__ == "__main__":
    unittest.main()
