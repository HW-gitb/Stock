"""Offline acceptance tests for the A2 policy container and A3 planner."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from engine import us_short_llm_theme_discovery_query_plan as query_plan
from engine import us_short_llm_theme_discovery_query_policy as policy_module
from engine import us_short_llm_theme_discovery_stage2_planner as planner


STAMP = "2026-08-02T12:00:00Z"
DECISION_DATE = "20260808"


def _stage1() -> dict:
    return {
        "schema_name": "us_short_llm_theme_discovery",
        "schema_version": "1.0.0",
        "generated_at": STAMP,
        "decision_clock": {
            "expected_decision_date": DECISION_DATE,
            "cutoff_policy": "before_decision_open_et",
            "pit_enforced": True,
        },
        "discovery_contract": {
            "producer_kind": "llm_theme_discovery",
            "input_mode": "offline_local_input",
            "membership_status": "provisional_unvalidated",
            "market_confirmation_status": "not_run",
            "scoring_eligible": False,
            "top15_effect_enabled": False,
            "operation_advice_effect_enabled": False,
            "dynamic_seats_enabled": False,
            "theme_probe_enabled": False,
            "lifecycle_actions_enabled": False,
        },
        "source_refs": [
            {"source_id": "web:source-1", "source_type": "web", "observed_at": STAMP},
            {"source_id": "web:source-2", "source_type": "web", "observed_at": STAMP},
        ],
        "themes": [
            {
                "theme_id": "theme-a",
                "display_name": "AI Grid",
                "summary": "A source-bound development.",
                "status": "provisional_discovered",
                "observed_at": STAMP,
                "source_ref_ids": ["web:source-2", "web:source-1"],
                "members": [{
                    "ticker": "AAPL",
                    "membership_status": "provisional_unvalidated",
                    "source_ref_ids": ["web:source-2"],
                }],
                "cross_industry_validation_status": "not_run",
                "market_confirmation_status": "not_run",
            },
            {
                "theme_id": "theme-b",
                "display_name": "ai   grid",
                "summary": "The same normalized concept from another source.",
                "status": "provisional_discovered",
                "observed_at": STAMP,
                "source_ref_ids": ["web:source-1"],
                "members": [{
                    "ticker": "MSFT",
                    "membership_status": "provisional_unvalidated",
                    "source_ref_ids": ["web:source-1"],
                }],
                "cross_industry_validation_status": "not_run",
                "market_confirmation_status": "not_run",
            },
            {
                "theme_id": "theme-c",
                "display_name": "Power",
                "summary": "Another source-bound development.",
                "status": "provisional_discovered",
                "observed_at": STAMP,
                "source_ref_ids": ["web:source-1"],
                "members": [{
                    "ticker": "AAPL",
                    "membership_status": "provisional_unvalidated",
                    "source_ref_ids": ["web:source-1"],
                }],
                "cross_industry_validation_status": "not_run",
                "market_confirmation_status": "not_run",
            },
        ],
    }


class QueryPolicyAndPlannerTests(unittest.TestCase):
    def test_policy_renders_the_four_exact_probe_templates_and_stays_candidate_offline(self):
        policy = policy_module.load_query_policy()
        packet = json.loads(
            (Path(__file__).resolve().parents[1] / "docs" /
             "us_short_soft_discovery_query_quality_probe_packet_20260730.json").read_text(encoding="utf-8")
        )
        expected = [
            {"query_id": row["query_id"], "query_text": row["text"]}
            for row in packet["query_templates"]
        ]
        self.assertEqual(policy_module.render_stage1_queries(policy), expected)
        self.assertEqual(policy["activation_status"], "candidate_offline")
        self.assertFalse(policy["production_query_policy_activated"])
        self.assertTrue(all(value is False for value in policy["effect_boundary"].values()))

    def test_policy_rejects_free_text_stage1_placeholder_even_if_digest_is_resealed(self):
        policy = policy_module.load_query_policy()
        broken = copy.deepcopy(policy)
        broken["policy_core"]["stage1_templates"][0]["text"] = "Find {ticker} this week."
        broken["policy_content_sha256"] = hashlib.sha256(
            json.dumps(
                broken["policy_core"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(policy_module.QueryPolicyError, "free-text placeholders"):
            policy_module.validate_query_policy(broken)

    def test_planner_normalizes_deduplicates_sorts_and_binds_terms(self):
        stage1 = _stage1()
        before = copy.deepcopy(stage1)
        result = planner.derive_stage2_plan_inputs(stage1)
        self.assertEqual(stage1, before)
        self.assertEqual(
            [(row["term_type"], row["term"], row["source_ref_ids"]) for row in result["focus_terms"]],
            [
                ("ticker", "AAPL", ["web:source-1", "web:source-2"]),
                ("ticker", "MSFT", ["web:source-1"]),
                ("concept", "ai grid", ["web:source-1", "web:source-2"]),
                ("concept", "power", ["web:source-1"]),
            ],
        )
        self.assertEqual(
            [row["source_ref_ids"] for row in result["stage2_queries"]],
            [row["source_ref_ids"] for row in result["focus_terms"]],
        )
        self.assertTrue(all("source-bound Stage-1 evidence" in row["query_text"] for row in result["stage2_queries"]))

    def test_same_frozen_stage1_bytes_reproduce_identical_plan_and_stage2_can_be_frozen(self):
        stage1 = _stage1()
        first = planner.derive_stage2_plan_inputs(stage1)
        second = planner.derive_stage2_plan_inputs(json.loads(json.dumps(stage1)))
        self.assertEqual(first, second)
        self.assertEqual(
            json.dumps(first, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            json.dumps(second, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state" / "us_short"
            state.mkdir(parents=True)
            parent = query_plan.build_parent_plan(
                decision_date=DECISION_DATE,
                policy_version=policy_module.EXPECTED_POLICY_VERSION,
                policy_template_content_sha256=policy_module.EXPECTED_POLICY_CONTENT_SHA256,
                stage1_queries=policy_module.render_stage1_queries(),
                stage2_rule_sha256=hashlib.sha256(b"stage2-rule-v0.1.0").hexdigest(),
                provider_envelopes=[{
                    "provider": "web",
                    "stage1_max_dispatch_count": 4,
                    "stage2_max_dispatch_count": 8,
                    "retry_max_dispatch_count": 2,
                    "max_dispatch_count": 14,
                }],
                generated_at=STAMP,
            )
            parent_path = state / (
                f"us_short_llm_theme_discovery_query_plan_parent_{DECISION_DATE}_{parent['plan_identity']}.json"
            )
            query_plan.write_parent_plan(parent, parent_path, state_dir=state, root=root, gitignored=lambda _path: True)
            stage1_path = root / "fixture" / "stage1.json"
            stage1_path.parent.mkdir()
            stage1_path.write_text(json.dumps(stage1, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            stage2 = query_plan.build_stage2_plan(
                parent_plan=parent,
                parent_plan_path=parent_path,
                stage1_artifact_path=stage1_path,
                focus_terms=first["focus_terms"],
                stage2_queries=first["stage2_queries"],
                generated_at=STAMP,
                root=root,
            )
            self.assertEqual(stage2["activation_status"], "candidate_offline")
            self.assertEqual(
                [row["source_ref_ids"] for row in stage2["canonical_stage2_core"]["stage2_queries"]],
                [row["source_ref_ids"] for row in first["stage2_queries"]],
            )

    def test_planner_rejects_ghost_source_and_stage2_only_evidence(self):
        ghost = _stage1()
        ghost["themes"][0]["source_ref_ids"] = ["web:ghost"]
        with self.assertRaisesRegex(planner.Stage2PlannerError, "absent from frozen Stage-1"):
            planner.derive_stage2_plan_inputs(ghost)

        stage2_only = _stage1()
        stage2_only["stage2_results"] = [{"source_id": "web:source-1"}]
        with self.assertRaisesRegex(planner.Stage2PlannerError, "frozen Stage-1 artifact rejected"):
            planner.derive_stage2_plan_inputs(stage2_only)

    def test_planner_rejects_more_than_the_per_type_limit(self):
        stage1 = _stage1()
        stage1["themes"] = []
        for index in range(9):
            stage1["themes"].append({
                "theme_id": f"theme-{index}",
                "display_name": f"Concept {index}",
                "summary": "A source-bound development.",
                "status": "provisional_discovered",
                "observed_at": STAMP,
                "source_ref_ids": ["web:source-1"],
                "members": [{
                    "ticker": "AAPL",
                    "membership_status": "provisional_unvalidated",
                    "source_ref_ids": ["web:source-1"],
                }],
                "cross_industry_validation_status": "not_run",
                "market_confirmation_status": "not_run",
            })
        with self.assertRaisesRegex(planner.Stage2PlannerError, "concept term count exceeds"):
            planner.derive_stage2_plan_inputs(stage1)


if __name__ == "__main__":
    unittest.main()
