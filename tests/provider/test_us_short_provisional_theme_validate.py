from __future__ import annotations

import copy
import importlib
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.provider.test_us_short_batch5_full_universe_momentum_producer import (  # noqa: E402
    _ALL_ELIGIBLE,
    _candidate_artifact,
)
from tests.provider.test_us_short_batch5_full_universe_theme_producer import _classification_packet  # noqa: E402

STATE_DIR = ROOT / "state" / "us_short"
MODULE = "runners.us_short_provisional_theme_validate"
DECISION_DATE = "20260615"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _discovery(theme_count: int = 1) -> dict:
    refs = [
        {"source_id": "web:theme", "source_type": "web", "observed_at": "2026-06-12T12:00:00Z"},
        {"source_id": "x:theme", "source_type": "x", "observed_at": "2026-06-12T12:05:00Z"},
    ]
    themes = []
    for idx in range(theme_count):
        theme_id = f"theme_{idx:02d}"
        themes.append({
            "theme_id": theme_id,
            "display_name": f"Theme {idx}",
            "summary": "A provisional cross-industry theme.",
            "status": "provisional_discovered",
            "observed_at": "2026-06-12T12:10:00Z",
            "source_ref_ids": ["web:theme", "x:theme"],
            "members": [
                {"ticker": ticker, "membership_status": "provisional_unvalidated", "source_ref_ids": ["web:theme", "x:theme"]}
                for ticker in _ALL_ELIGIBLE[:4]
            ],
            "cross_industry_validation_status": "not_run",
            "market_confirmation_status": "not_run",
        })
    return {
        "schema_name": "us_short_llm_theme_discovery", "schema_version": "1.0.0",
        "generated_at": "2026-06-12T12:20:00Z", "input_sha256": "0" * 64,
        "decision_clock": {"expected_decision_date": DECISION_DATE, "cutoff_policy": "before_decision_open_et", "pit_enforced": True},
        "discovery_contract": {
            "producer_kind": "llm_theme_discovery", "input_mode": "offline_local_input", "membership_status": "provisional_unvalidated", "market_confirmation_status": "not_run",
            "scoring_eligible": False, "top15_effect_enabled": False, "operation_advice_effect_enabled": False, "dynamic_seats_enabled": False, "theme_probe_enabled": False, "lifecycle_actions_enabled": False,
        },
        "source_refs": refs, "themes": themes,
    }


class ProvisionalThemeValidationTests(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_provisional_validate_{os.getpid()}_{self._testMethodName}"
        self.paths = {
            "discovery": STATE_DIR / f"{self.slug}_discovery.json",
            "candidate": STATE_DIR / f"{self.slug}_candidate.json",
            "classification": STATE_DIR / f"{self.slug}_classification.json",
            "output": STATE_DIR / f"{self.slug}_output.json",
        }
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        _write(self.paths["discovery"], _discovery())
        _write(self.paths["candidate"], _candidate_artifact(_ALL_ELIGIBLE))
        _write(self.paths["classification"], _classification_packet({"AAPL": "10", "MSFT": "10", "GOOG": "10", "JPM": "20", "AMZN": "20"}))

    def tearDown(self):
        for path in self.paths.values():
            path.unlink(missing_ok=True)

    def runner(self):
        return importlib.import_module(MODULE)

    def kwargs(self):
        return {
            "discovery_path": self.paths["discovery"], "candidate_path": self.paths["candidate"],
            "classification_path": self.paths["classification"], "output_path": self.paths["output"],
            "expected_decision_date": DECISION_DATE, "generated_at": "2026-06-15T11:00:00Z",
        }

    def test_run_packet_is_inert_and_records_input_digests(self):
        result = self.runner().run_packet(**self.kwargs())
        self.assertEqual(result["status"], "offline_validation_artifact_written")
        artifact = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        self.assertEqual(artifact["summary"]["validated_theme_count"], 1)
        self.assertEqual(artifact["summary"]["validated_member_count"], 4)
        self.assertFalse(artifact["validation_contract"]["scoring_eligible"])
        self.assertFalse(artifact["validation_contract"]["top15_effect_enabled"])
        self.assertFalse(artifact["validation_contract"]["operation_advice_effect_enabled"])
        self.assertEqual(artifact["themes"][0]["members"][0]["source_types"], ["web", "x"])
        self.assertEqual(len(artifact["input_artifacts"]["discovery_artifact_sha256"]), 64)

    def test_single_source_drops_to_single_tier_without_losing_member(self):
        payload = _discovery()
        payload["themes"][0]["members"][0]["source_ref_ids"] = ["web:theme"]
        _write(self.paths["discovery"], payload)
        artifact = self.runner().build_artifact(
            self.runner()._load_inputs(self.paths["discovery"], self.paths["candidate"], self.paths["classification"], DECISION_DATE),
            generated_at="2026-06-15T11:00:00Z",
        )
        self.assertEqual(artifact["summary"]["validated_member_count"], 4)
        self.assertEqual(artifact["summary"]["dropped_member_count"], 0)
        self.assertEqual(artifact["themes"][0]["members"][0]["evidence_tier"], "single")

    def test_fewer_than_three_qualified_members_rejects_theme(self):
        payload = _discovery()
        payload["themes"][0]["members"] = payload["themes"][0]["members"][:2]
        _write(self.paths["discovery"], payload)
        artifact = self.runner().build_artifact(
            self.runner()._load_inputs(self.paths["discovery"], self.paths["candidate"], self.paths["classification"], DECISION_DATE),
            generated_at="2026-06-15T11:00:00Z",
        )
        self.assertEqual(artifact["themes"], [])
        self.assertEqual(artifact["summary"]["rejected_theme_count"], 1)

    def test_one_industry_rejects_theme(self):
        _write(self.paths["classification"], _classification_packet({ticker: "10" for ticker in _ALL_ELIGIBLE}))
        artifact = self.runner().run_packet(**self.kwargs())
        self.assertEqual(artifact["validated_theme_count"], 0)
        saved = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        self.assertIn("fewer_than_2_sec_sic_industries", [row["reason"] for row in saved["drop_ledger"]])

    def test_nine_themes_are_deterministically_truncated_to_eight(self):
        _write(self.paths["discovery"], _discovery(theme_count=9))
        artifact = self.runner().run_packet(**self.kwargs())
        self.assertEqual(artifact["validated_theme_count"], 8)
        saved = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        self.assertEqual(saved["themes"][0]["theme_id"], "theme_00")
        self.assertEqual(saved["summary"]["truncated_theme_count"], 1)

    def test_member_level_bad_binding_drops_member_but_keeps_theme(self):
        payload = _discovery()
        payload["themes"][0]["members"][0]["source_ref_ids"] = ["web:missing"]
        _write(self.paths["discovery"], payload)
        result = self.runner().run_packet(**self.kwargs())
        self.assertEqual(result["validated_theme_count"], 1)
        saved = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        self.assertEqual(saved["summary"]["validated_member_count"], 3)
        self.assertIn("unbound_member_source_ref", [row["reason"] for row in saved["drop_ledger"]])

    def test_duplicate_member_drops_only_duplicate(self):
        payload = _discovery()
        payload["themes"][0]["members"][1]["ticker"] = payload["themes"][0]["members"][0]["ticker"]
        _write(self.paths["discovery"], payload)
        result = self.runner().run_packet(**self.kwargs())
        self.assertEqual(result["validated_theme_count"], 1)
        saved = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        self.assertEqual(saved["summary"]["validated_member_count"], 3)
        self.assertIn("duplicate_member_ticker", [row["reason"] for row in saved["drop_ledger"]])

    def test_missing_independent_web_x_evidence_drops_only_member(self):
        payload = _discovery()
        payload["source_refs"].append({"source_id": "llm:theme", "source_type": "llm", "observed_at": "2026-06-12T12:01:00Z"})
        payload["themes"][0]["source_ref_ids"].append("llm:theme")
        payload["themes"][0]["members"][0]["source_ref_ids"] = ["llm:theme"]
        _write(self.paths["discovery"], payload)
        result = self.runner().run_packet(**self.kwargs())
        self.assertEqual(result["validated_theme_count"], 1)
        saved = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        self.assertEqual(saved["summary"]["validated_member_count"], 3)
        self.assertIn("missing_independent_web_x_evidence", [row["reason"] for row in saved["drop_ledger"]])

    def test_not_in_active_pass1_eligible_universe_drops_only_member(self):
        payload = _discovery()
        payload["themes"][0]["members"][0]["ticker"] = "ZZZZ"
        _write(self.paths["discovery"], payload)
        result = self.runner().run_packet(**self.kwargs())
        self.assertEqual(result["validated_theme_count"], 1)
        saved = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        self.assertEqual(saved["summary"]["validated_member_count"], 3)
        self.assertIn("not_in_active_pass1_eligible_universe", [row["reason"] for row in saved["drop_ledger"]])

    def test_missing_sec_sic_classification_drops_only_member(self):
        classification = _classification_packet({"MSFT": "10", "GOOG": "10", "JPM": "20", "AMZN": "20"})
        _write(self.paths["classification"], classification)
        result = self.runner().run_packet(**self.kwargs())
        self.assertEqual(result["validated_theme_count"], 1)
        saved = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        self.assertEqual(saved["summary"]["validated_member_count"], 3)
        self.assertIn("missing_sec_sic_classification", [row["reason"] for row in saved["drop_ledger"]])

    def test_invalid_canonical_us_ticker_drops_only_member(self):
        # The discovery schema rejects this identity before the member gate; call the gate directly to
        # prove malformed member identity is still a per-member drop rather than a whole-packet abort.
        payload = _discovery()
        payload["themes"][0]["members"][0]["ticker"] = "000001.SZ"
        themes, drops = self.runner().validate_provisional_themes(
            payload, eligible_tickers=set(_ALL_ELIGIBLE),
            sectors_by_ticker={"AAPL": "10", "MSFT": "10", "GOOG": "10", "JPM": "20", "AMZN": "20"},
        )
        self.assertEqual(len(themes), 1)
        self.assertEqual(len(themes[0]["members"]), 3)
        self.assertIn("invalid_canonical_us_ticker", [row["reason"] for row in drops])

    def test_llm_only_members_can_reject_theme_below_three_qualified(self):
        payload = _discovery()
        payload["source_refs"].append({"source_id": "llm:theme", "source_type": "llm", "observed_at": "2026-06-12T12:01:00Z"})
        payload["themes"][0]["source_ref_ids"].append("llm:theme")
        for member in payload["themes"][0]["members"][:2]:
            member["source_ref_ids"] = ["llm:theme"]
        _write(self.paths["discovery"], payload)
        result = self.runner().run_packet(**self.kwargs())
        self.assertEqual(result["validated_theme_count"], 0)
        saved = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        reasons = [row["reason"] for row in saved["drop_ledger"]]
        self.assertEqual(reasons.count("missing_independent_web_x_evidence"), 2)
        self.assertIn("fewer_than_3_qualified_members", reasons)

    def test_industry_codes_are_trimmed_before_diversity_gate(self):
        payload = _discovery()
        themes, drops = self.runner().validate_provisional_themes(
            payload, eligible_tickers=set(_ALL_ELIGIBLE),
            sectors_by_ticker={"AAPL": " 10 ", "MSFT": "10", "GOOG": "10", "JPM": " 20 ", "AMZN": "20"},
        )
        self.assertEqual(drops, [])
        self.assertEqual(themes[0]["validation"]["industry_codes"], ["10", "20"])

    def test_every_producer_emitted_artifact_is_consumable(self):
        """Producer<->consumer round trip (closes the defect CLASS behind R1/R5, not one shape).

        ANY artifact this validator emits must be consumable by the boost mapper: a member shape the
        producer accepts must never abort the whole week one layer down. Each shape independently
        re-derives the expected points from the emitted `evidence_tier`s, so a consumer that silently
        drops or inflates a member fails here too.
        """
        from engine.us_short_provisional_theme_boost import TIER_POINTS, build_provisional_theme_boost_map

        base_sectors = {"AAPL": "10", "MSFT": "10", "GOOG": "10", "JPM": "20", "AMZN": "20"}

        def _cite_llm(payload):
            payload["source_refs"].append(
                {"source_id": "llm:summary", "source_type": "llm", "observed_at": "2026-06-12T12:01:00Z"})
            payload["themes"][0]["source_ref_ids"].append("llm:summary")

        def _every_member_also_cited_by_llm(payload):
            _cite_llm(payload)
            for member in payload["themes"][0]["members"]:
                member["source_ref_ids"] = ["web:theme", "x:theme", "llm:summary"]

        def _one_llm_only_member(payload):
            _cite_llm(payload)
            payload["themes"][0]["members"][0]["source_ref_ids"] = ["llm:summary"]

        def _web_only_member(payload):
            payload["themes"][0]["members"][0]["source_ref_ids"] = ["web:theme"]

        def _x_only_member(payload):
            payload["themes"][0]["members"][1]["source_ref_ids"] = ["x:theme"]

        def _member_outside_universe(payload):
            payload["themes"][0]["members"][0]["ticker"] = "ZZZZ"

        def _duplicate_member(payload):
            payload["themes"][0]["members"][1]["ticker"] = payload["themes"][0]["members"][0]["ticker"]

        def _unbound_member_ref(payload):
            payload["themes"][0]["members"][0]["source_ref_ids"] = ["web:missing"]

        cases = [
            ("baseline both-tier", None, 1, None),
            ("one web-only member", _web_only_member, 1, None),
            ("one x-only member", _x_only_member, 1, None),
            ("every member also cited by an llm ref", _every_member_also_cited_by_llm, 1, None),
            ("one llm-only member", _one_llm_only_member, 1, None),
            ("member outside the eligible universe", _member_outside_universe, 1, None),
            ("duplicate member ticker", _duplicate_member, 1, None),
            ("member with an unbound source ref", _unbound_member_ref, 1, None),
            ("nine themes truncated to eight", None, 9, None),
            ("member missing its SEC-SIC row", None, 1,
             {"MSFT": "10", "GOOG": "10", "JPM": "20", "AMZN": "20"}),
        ]
        digest_keys = ("discovery_artifact_sha256", "candidate_artifact_sha256", "classification_packet_sha256")
        for label, mutate, theme_count, sectors in cases:
            with self.subTest(shape=label):
                payload = _discovery(theme_count)
                if mutate is not None:
                    mutate(payload)
                _write(self.paths["discovery"], payload)
                _write(self.paths["classification"], _classification_packet(sectors or base_sectors))
                runner = self.runner()
                artifact = runner.build_artifact(
                    runner._load_inputs(
                        self.paths["discovery"], self.paths["candidate"],
                        self.paths["classification"], DECISION_DATE,
                    ),
                    generated_at="2026-06-15T11:00:00Z",
                )
                expected = {ticker: 0.0 for ticker in _ALL_ELIGIBLE}
                for theme in artifact["themes"]:
                    for member in theme["members"]:
                        expected[member["ticker"]] = max(
                            expected[member["ticker"]], TIER_POINTS[member["evidence_tier"]])
                boosts = build_provisional_theme_boost_map(
                    artifact, target_tickers=list(_ALL_ELIGIBLE),
                    expected_decision_date=artifact["decision_clock"]["expected_decision_date"],
                    expected_input_digests={key: artifact["input_artifacts"][key] for key in digest_keys},
                )
                self.assertEqual({ticker: row["theme_soft_boost"] for ticker, row in boosts.items()}, expected)

    def test_llm_reference_does_not_improve_top8_priority(self):
        payload = _discovery(theme_count=9)
        payload["source_refs"].append({"source_id": "llm:theme", "source_type": "llm", "observed_at": "2026-06-12T12:01:00Z"})
        payload["themes"][-1]["source_ref_ids"].append("llm:theme")
        _write(self.paths["discovery"], payload)
        self.runner().run_packet(**self.kwargs())
        saved = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        self.assertEqual(saved["themes"][0]["theme_id"], "theme_00")

    def test_preflight_does_not_write(self):
        result = self.runner().run_preflight(**self.kwargs())
        self.assertFalse(self.paths["output"].exists())
        self.assertEqual(result["status"], "offline_preflight_passed")

    def test_duplicate_discovery_source_id_fails_closed(self):
        payload = _discovery()
        payload["source_refs"].append(copy.deepcopy(payload["source_refs"][0]))
        _write(self.paths["discovery"], payload)
        with self.assertRaisesRegex(self.runner().ProvisionalThemeValidationError, "duplicate source_id"):
            self.runner().run_preflight(**self.kwargs())
        self.assertFalse(self.paths["output"].exists())

    def test_candidate_decision_date_mismatch_fails_before_write(self):
        candidate = _candidate_artifact(_ALL_ELIGIBLE)
        candidate["decision_date"] = "20260616"
        _write(self.paths["candidate"], candidate)
        with self.assertRaises(self.runner().ProvisionalThemeValidationError):
            self.runner().run_packet(**self.kwargs())
        self.assertFalse(self.paths["output"].exists())

    def test_existing_receipt_reuses_only_same_immutable_inputs(self):
        first = self.runner().run_packet(**self.kwargs())
        second = self.runner().run_packet(**self.kwargs())
        self.assertEqual(first["status"], "offline_validation_artifact_written")
        self.assertEqual(second["status"], "offline_validation_artifact_reused")
        payload = _discovery()
        payload["themes"][0]["summary"] = "Changed after the first receipt."
        _write(self.paths["discovery"], payload)
        with self.assertRaisesRegex(self.runner().ProvisionalThemeValidationError, "different decision-date"):
            self.runner().run_packet(**self.kwargs())


if __name__ == "__main__":
    unittest.main()
