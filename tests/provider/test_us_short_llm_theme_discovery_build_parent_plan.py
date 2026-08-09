from __future__ import annotations

import copy
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import us_short_llm_theme_discovery_query_plan as query_plan
from engine import us_short_llm_theme_discovery_plan_budget as plan_budget
from runners import us_short_llm_theme_discovery_build_parent_plan as builder
from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch


class UsShortBuildParentPlanTests(unittest.TestCase):
    def _payload(self, *, decision_date: str = "20260809") -> dict:
        return builder.build_parent_plan_from_reviewed_policy(
            decision_date=decision_date,
            generated_at="2026-08-03T12:00:00+00:00",
        )

    def test_builds_directly_consumable_four_query_offline_plan(self) -> None:
        payload = self._payload()
        query_plan.validate_parent_plan(payload)
        core = payload["canonical_plan_core"]
        self.assertEqual(core["decision_date"], "20260809")
        self.assertEqual(core["policy_version"], "soft_discovery_query_policy_v0.2.0")
        self.assertEqual([row["query_id"] for row in core["stage1_queries"]], [
            "stage1_new_cross_industry_demand",
            "stage1_capex_orders_capacity",
            "stage1_supply_regulation_bottleneck",
            "stage1_earnings_bookings_guidance",
        ])
        self.assertEqual(core["provider_envelopes"], [
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
        ])
        self.assertEqual(payload["activation_status"], "candidate_offline")
        self.assertTrue(all(value is False for value in payload["effect_boundary"].values()))

    def test_rendered_queries_are_bound_to_an_independent_probe_packet(self) -> None:
        packet = json.loads(builder.DEFAULT_PROBE_PACKET_PATH.read_text(encoding="utf-8"))
        schema = json.loads(builder.PROBE_PACKET_SCHEMA_PATH.read_text(encoding="utf-8"))
        changed_text = "independent packet control text"
        packet["query_templates"][0]["text"] = changed_text
        schema["properties"]["query_templates"]["const"][0]["text"] = changed_text
        with tempfile.TemporaryDirectory(prefix="us_short_packet_control_", dir=str(builder.ROOT)) as raw:
            packet_path = Path(raw) / "packet.json"
            schema_path = Path(raw) / "packet.schema.json"
            packet_path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
            schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(builder, "DEFAULT_PROBE_PACKET_PATH", packet_path), mock.patch.object(
                builder, "PROBE_PACKET_SCHEMA_PATH", schema_path,
            ):
                with self.assertRaisesRegex(builder.ParentPlanBuilderError, "independent probe packet"):
                    self._payload()

    def test_both_fetch_lanes_preserve_every_reviewed_query_byte(self) -> None:
        queries = [
            row["query_text"]
            for row in self._payload()["canonical_plan_core"]["stage1_queries"]
        ]
        self.assertEqual(web._safe_queries(queries, deduplicate=False), queries)
        self.assertEqual(xfetch._safe_queries(queries, deduplicate=False), queries)

    def test_plan_bound_queries_preserve_spaces_and_backticks(self) -> None:
        queries = ["Keep  exact `query` bytes"]
        self.assertEqual(web._safe_queries(queries, deduplicate=False, preserve=True), queries)
        self.assertEqual(xfetch._safe_queries(queries, deduplicate=False, preserve=True), queries)

    def test_query_cli_input_is_not_an_entrypoint(self) -> None:
        signature = inspect.signature(builder.build_parent_plan_from_reviewed_policy)
        self.assertNotIn("query", signature.parameters)
        parser = builder.build_argument_parser()
        options = {option for action in parser._actions for option in action.option_strings}
        self.assertNotIn("--query", options)
        self.assertIn("--provider-envelope-json", options)

    def test_probe_packet_binds_decision_date_and_rejects_reused_slot(self) -> None:
        with self.assertRaisesRegex(builder.ParentPlanBuilderError, "decision date"):
            self._payload(decision_date="20260802")

    def test_honest_plan_reserves_and_forged_plan_is_rejected_before_ledger_write(self) -> None:
        honest = self._payload()
        forged = copy.deepcopy(honest)
        forged_core = forged["canonical_plan_core"]
        forged_core["policy_template_content_sha256"] = "0" * 64
        forged_core["stage1_queries"][0]["query_text"] = "operator supplied paid query"
        forged_core["stage2_rule_sha256"] = "0" * 64
        forged["plan_identity"] = query_plan._digest(forged_core)  # type: ignore[attr-defined]
        query_plan.validate_parent_plan(forged)
        with tempfile.TemporaryDirectory(prefix="us_short_plan_authority_", dir=str(builder.ROOT)) as raw:
            root = Path(raw)
            honest_state = root / "honest_state"
            forged_state = root / "forged_state"
            honest_budget = plan_budget.reserve_plan_budget(
                honest, lane=plan_budget.PLAN_LANE, state_dir=honest_state,
                root=builder.ROOT, gitignored=lambda _path: True,
                expected_decision_date="20260809", providers=("web",),
            )
            self.assertEqual(honest_budget.providers, ("web",))
            self.assertTrue(list(honest_state.glob("*.json")))
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "reviewed policy"):
                plan_budget.reserve_plan_budget(
                    forged, lane=plan_budget.PLAN_LANE, state_dir=forged_state,
                    root=builder.ROOT, gitignored=lambda _path: True,
                    expected_decision_date="20260809", providers=("web",),
                )
            self.assertFalse(forged_state.exists() and list(forged_state.rglob("*.json")))
            # A forged plan must not be able to switch the authority check off by simply
            # declaring a different policy_version.  Gating the check on the plan's own
            # field would let this reservation through with operator free text.
            drifted = copy.deepcopy(forged)
            drifted["canonical_plan_core"]["policy_version"] = "soft_discovery_query_policy_v0_9_9"
            drifted["plan_identity"] = query_plan._digest(  # type: ignore[attr-defined]
                drifted["canonical_plan_core"]
            )
            query_plan.validate_parent_plan(drifted)
            drifted_state = root / "drifted_state"
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "reviewed policy"):
                plan_budget.reserve_plan_budget(
                    drifted, lane=plan_budget.PLAN_LANE, state_dir=drifted_state,
                    root=builder.ROOT, gitignored=lambda _path: True,
                    expected_decision_date="20260809", providers=("web",),
                )
            self.assertFalse(drifted_state.exists() and list(drifted_state.rglob("*.json")))
            # Pin each gate independently: the end-to-end reservation above is satisfied by
            # EITHER door, so re-introducing the plan-controlled conditional in only one of
            # them would leave it green.  These two assertions make each one load-bearing.
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "reviewed policy version"):
                plan_budget._provider_envelopes(drifted)  # type: ignore[attr-defined]
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "reviewed policy version"):
                plan_budget.validate_run_decision_date(drifted, "20260809")
            self.assertEqual(sorted(plan_budget._provider_envelopes(honest)), ["web", "xai"])  # type: ignore[attr-defined]

    def test_current_repository_reader_rejects_forged_plan_before_consumption(self) -> None:
        forged = copy.deepcopy(self._payload())
        forged["canonical_plan_core"]["policy_template_content_sha256"] = "0" * 64
        forged["plan_identity"] = query_plan._digest(  # type: ignore[attr-defined]
            forged["canonical_plan_core"]
        )
        with tempfile.TemporaryDirectory(prefix="us_short_reader_authority_", dir=str(builder.ROOT)) as raw:
            state = Path(raw) / "state" / "us_short"
            path = query_plan.default_parent_plan_path(
                "20260809", forged["plan_identity"], state_dir=state,
            )
            query_plan.write_parent_plan(
                forged, path, state_dir=state, root=builder.ROOT,
                gitignored=lambda _path: True,
            )
            with self.assertRaisesRegex(query_plan.QueryPlanError, "reviewed policy"):
                query_plan.read_parent_plan(
                    path, root=builder.ROOT, state_dir=state, require_reviewed_policy=True,
                )

    def test_published_plan_round_trips_through_the_live_read_door(self) -> None:
        """The 08-09 opening sequence, forward leg: build -> publish -> read back -> derive.

        The sibling test above only proves a forged plan is refused.  A refusal-only pair
        would still pass if the door rejected everything, so this asserts the honest plan
        survives the same door and yields the reviewed queries to both lanes.
        """
        payload = self._payload()
        expected = [row["query_text"] for row in payload["canonical_plan_core"]["stage1_queries"]]
        with tempfile.TemporaryDirectory(prefix="us_short_plan_round_trip_", dir=str(builder.ROOT)) as raw:
            state = Path(raw) / "state" / "us_short"
            path = query_plan.default_parent_plan_path(
                "20260809", payload["plan_identity"], state_dir=state,
            )
            query_plan.write_parent_plan(
                payload, path, state_dir=state, root=builder.ROOT,
                gitignored=lambda _path: True,
            )
            document, artifact_sha256, relative_path = query_plan.read_parent_plan(
                path, root=builder.ROOT, state_dir=state, require_reviewed_policy=True,
            )
            self.assertEqual(len(artifact_sha256), 64)
            self.assertTrue(relative_path.endswith(".json"))
            for provider in ("web", "xai"):
                derived, records, _binding = query_plan.resolve_stage1_plan_binding(
                    document, provider=provider,
                )
                self.assertEqual(derived, expected)
                self.assertEqual(
                    [row["query_id"] for row in records],
                    [row["query_id"] for row in payload["canonical_plan_core"]["stage1_queries"]],
                )

    def test_provider_envelope_must_keep_four_query_no_retry_shape(self) -> None:
        bad = builder._default_provider_envelopes(4)
        bad[0]["max_dispatch_count"] = 9
        with self.assertRaisesRegex(builder.ParentPlanBuilderError, "four-query"):
            builder.build_parent_plan_from_reviewed_policy(
                decision_date="20260809",
                generated_at="2026-08-03T12:00:00+00:00",
                provider_envelopes=bad,
            )

    def test_publish_uses_the_identity_addressed_decision_slot(self) -> None:
        payload = self._payload()
        with mock.patch.object(builder.query_plan, "write_parent_plan") as write:
            path = builder.publish_parent_plan(payload)
        expected = builder.query_plan.default_parent_plan_path(
            "20260809", payload["plan_identity"], state_dir=builder.STATE_DIR,
        ).resolve()
        self.assertEqual(path, expected)
        write.assert_called_once()
        self.assertEqual(write.call_args.args[0], payload)
        self.assertEqual(write.call_args.args[1].resolve(), expected)


if __name__ == "__main__":
    unittest.main()
