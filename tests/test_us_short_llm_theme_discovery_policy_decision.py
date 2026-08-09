from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from engine import us_short_llm_theme_discovery_policy_decision as decision
from engine import us_short_llm_theme_discovery_query_plan as query_plan
from engine import us_short_llm_theme_discovery_query_policy as policy


ROOT = Path(__file__).resolve().parents[1]
PACKET_REF = "docs/us_short_soft_discovery_query_quality_probe_packet_20260809.json"
PACKET_PATH = ROOT / PACKET_REF
PACKET_SHA256 = hashlib.sha256(PACKET_PATH.read_bytes()).hexdigest()
GENERATED_AT = "2026-08-09T05:00:00Z"


class VersionedPolicyDecisionTests(unittest.TestCase):
    def _build(
        self,
        *,
        policy_version: str,
        decision_date: str = "20260809",
        disposition: str = "KEEP",
        generated_at: str = GENERATED_AT,
        root: Path = ROOT,
    ) -> dict:
        return decision.build_policy_decision_result(
            input_packet_id="us_short_soft_discovery_query_quality_probe_packet_20260809",
            input_packet_ref=PACKET_REF,
            input_packet_sha256=PACKET_SHA256,
            decision_date=decision_date,
            policy_version=policy_version,
            policy_disposition=disposition,
            generated_at=generated_at,
            root=root,
        )

    def test_v03_changes_only_the_supply_chain_constraint_angle(self) -> None:
        v02 = policy.load_query_policy_for_version(policy.EXPECTED_POLICY_VERSION)
        v03 = policy.load_query_policy_for_version(policy.V0_3_POLICY_VERSION)
        self.assertEqual(v03["policy_version"], policy.V0_3_POLICY_VERSION)
        self.assertNotIn("source_packet", v03)
        self.assertEqual(
            [row["query_id"] for row in v02["policy_core"]["stage1_templates"]],
            [row["query_id"] for row in v03["policy_core"]["stage1_templates"]],
        )
        for old, new in zip(v02["policy_core"]["stage1_templates"], v03["policy_core"]["stage1_templates"]):
            if old["query_id"] != "stage1_supply_regulation_bottleneck":
                self.assertEqual(old, new)
        supply = v03["policy_core"]["stage1_templates"][2]["text"]
        self.assertIn("physical constraint layer", supply)
        self.assertIn("certification queue", supply)
        self.assertIn("source-bound evidence", supply)
        self.assertTrue(all(value is False for value in v03["effect_boundary"].values()))
        self.assertFalse(policy.get_policy_spec(policy.V0_3_POLICY_VERSION).provider_execution_allowed)

    def test_same_packet_and_policy_reproduce_one_stable_result_identity(self) -> None:
        first = self._build(policy_version=policy.V0_3_POLICY_VERSION)
        second = self._build(
            policy_version=policy.V0_3_POLICY_VERSION,
            generated_at="2026-08-09T06:00:00Z",
        )
        self.assertEqual(first["decision_result_id"], second["decision_result_id"])
        self.assertEqual(first["canonical_decision"], second["canonical_decision"])
        self.assertEqual(first["canonical_decision"]["input_packet_id"], "us_short_soft_discovery_query_quality_probe_packet_20260809")
        self.assertEqual(first["canonical_decision"]["policy_version"], policy.V0_3_POLICY_VERSION)

    def test_same_packet_can_hold_v02_and_v03_results_without_overwrite(self) -> None:
        v02 = self._build(policy_version=policy.EXPECTED_POLICY_VERSION)
        v03 = self._build(policy_version=policy.V0_3_POLICY_VERSION)
        self.assertNotEqual(v02["decision_result_id"], v03["decision_result_id"])
        v02_path = decision.policy_decision_result_path(
            input_packet_id=v02["canonical_decision"]["input_packet_id"],
            decision_date=v02["canonical_decision"]["decision_date"],
            policy_version=v02["canonical_decision"]["policy_version"],
        )
        v03_path = decision.policy_decision_result_path(
            input_packet_id=v03["canonical_decision"]["input_packet_id"],
            decision_date=v03["canonical_decision"]["decision_date"],
            policy_version=v03["canonical_decision"]["policy_version"],
        )
        self.assertNotEqual(v02_path, v03_path)
        self.assertIn(policy.EXPECTED_POLICY_VERSION, v02_path.name)
        self.assertIn(policy.V0_3_POLICY_VERSION, v03_path.name)

    def test_new_decision_date_does_not_change_policy_version(self) -> None:
        result = self._build(
            policy_version=policy.V0_3_POLICY_VERSION,
            decision_date="20260815",
            disposition="KEEP",
        )
        self.assertEqual(result["canonical_decision"]["decision_date"], "20260815")
        self.assertEqual(result["canonical_decision"]["policy_version"], policy.V0_3_POLICY_VERSION)
        self.assertEqual(result["canonical_decision"]["policy_disposition"], "KEEP")

    def test_all_policy_dispositions_are_explicit_and_no_other_state_is_accepted(self) -> None:
        for disposition in decision.POLICY_DISPOSITIONS:
            with self.subTest(disposition=disposition):
                result = self._build(
                    policy_version=policy.V0_3_POLICY_VERSION,
                    disposition=disposition,
                )
                self.assertEqual(result["canonical_decision"]["policy_disposition"], disposition)
        with self.assertRaisesRegex(decision.PolicyDecisionError, "KEEP, REVIEW, or BLOCKED"):
            self._build(policy_version=policy.V0_3_POLICY_VERSION, disposition="AUTO_UPGRADE")

    def test_four_upstream_identity_fields_locate_one_versioned_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            packet_path = root / PACKET_REF
            packet_path.parent.mkdir(parents=True)
            shutil.copyfile(PACKET_PATH, packet_path)
            result = self._build(policy_version=policy.V0_3_POLICY_VERSION, root=root)
            result_path = decision.policy_decision_result_path(
                input_packet_id=result["canonical_decision"]["input_packet_id"],
                decision_date=result["canonical_decision"]["decision_date"],
                policy_version=result["canonical_decision"]["policy_version"],
                root=root,
            )
            input_packet_id = result["canonical_decision"]["input_packet_id"]
            decision_date = result["canonical_decision"]["decision_date"]
            policy_version = result["canonical_decision"]["policy_version"]
            artifact_path = root / "docs" / (
                f"us_short_llm_theme_discovery_policy_decision_{input_packet_id}_{decision_date}_{policy_version}.json"
            )
            self.assertEqual(result_path, artifact_path)
            artifact_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            upstream = decision.upstream_identity_for_policy_decision_result(result, root=root)
            self.assertEqual(set(upstream), set(decision.UPSTREAM_IDENTITY_FIELDS))
            self.assertNotIn("policy_disposition", upstream)
            located = decision.locate_policy_decision_result(root=root, **upstream)
            self.assertEqual(located, result)
            wrong_policy = dict(upstream, upstream_policy_version=policy.EXPECTED_POLICY_VERSION)
            with self.assertRaisesRegex(decision.PolicyDecisionError, "unavailable|identity"):
                decision.locate_policy_decision_result(root=root, **wrong_policy)
            wrong_result = dict(upstream, upstream_decision_result_id="0" * 64)
            with self.assertRaisesRegex(decision.PolicyDecisionError, "identity"):
                decision.locate_policy_decision_result(root=root, **wrong_result)

    def test_v03_parent_plan_is_structural_only_and_cannot_authorize_provider_dispatch(self) -> None:
        v03 = policy.load_query_policy_for_version(policy.V0_3_POLICY_VERSION)
        parent = query_plan.build_parent_plan(
            decision_date="20260815",
            policy_version=v03["policy_version"],
            policy_template_content_sha256=v03["policy_content_sha256"],
            stage1_queries=policy.render_stage1_queries(v03),
            stage2_rule_sha256=policy.stage2_rule_sha256(v03),
            provider_envelopes=[
                {
                    "provider": "web",
                    "stage1_max_dispatch_count": 4,
                    "stage2_max_dispatch_count": 4,
                    "retry_max_dispatch_count": 0,
                    "max_dispatch_count": 8,
                },
                {
                    "provider": "xai",
                    "stage1_max_dispatch_count": 4,
                    "stage2_max_dispatch_count": 0,
                    "retry_max_dispatch_count": 0,
                    "max_dispatch_count": 4,
                },
            ],
            generated_at=GENERATED_AT,
        )
        query_plan.validate_parent_plan(parent)
        with self.assertRaisesRegex(query_plan.QueryPlanError, "offline-only"):
            query_plan.validate_parent_plan_against_reviewed_policy(parent)


if __name__ == "__main__":
    unittest.main()
