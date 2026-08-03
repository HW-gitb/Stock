from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from engine.us_short_schema_formats import FORMAT_CHECKER
from engine import us_short_llm_theme_discovery_plan_budget as plan_budget
from engine import us_short_llm_theme_discovery_query_plan as query_plan
from engine import us_short_soft_discovery_query_quality_probe_paths as probe_paths
from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as x


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "us_short_soft_discovery_query_quality_probe_packet.schema.json"
ARTIFACT_PATH = ROOT / "docs" / "us_short_soft_discovery_query_quality_probe_packet_20260730.json"


class UsShortSoftDiscoveryQueryQualityProbePacketSchemaTest(unittest.TestCase):
    def _schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _artifact(self) -> dict:
        return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

    def _validator(self, *, armed: bool = True):
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        return Draft7Validator(
            self._schema(),
            format_checker=FORMAT_CHECKER if armed else None,
        )

    def _errors(self, payload: dict, *, armed: bool = True) -> list:
        return list(self._validator(armed=armed).iter_errors(payload))

    @staticmethod
    def _set_path(payload: dict, path: tuple[str | int, ...], value: object) -> None:
        target = payload
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value

    @staticmethod
    def _get_path(payload: dict, path: tuple[str | int, ...]) -> object:
        target = payload
        for part in path:
            target = target[part]
        return target

    @classmethod
    def _leaf_paths(cls, value: object, path: tuple[str | int, ...] = ()) -> list[tuple[str | int, ...]]:
        if isinstance(value, dict):
            return [
                leaf
                for key, child in value.items()
                for leaf in cls._leaf_paths(child, path + (key,))
            ]
        return [path]

    @classmethod
    def _formatted_paths(
        cls,
        schema: dict,
        path: tuple[str | int, ...] = (),
        *,
        root_schema: dict | None = None,
        artifact_node: object | None = None,
    ) -> list[tuple[str | int, ...]]:
        root_schema = schema if root_schema is None else root_schema
        ref = schema.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            resolved = root_schema
            for part in ref[2:].split("/"):
                resolved = resolved[part.replace("~1", "/").replace("~0", "~")]
            return cls._formatted_paths(
                resolved,
                path,
                root_schema=root_schema,
                artifact_node=artifact_node,
            )
        paths = [path] if schema.get("format") == "date-time" else []
        for key, child in schema.get("properties", {}).items():
            child_artifact = artifact_node.get(key) if isinstance(artifact_node, dict) else None
            paths.extend(
                cls._formatted_paths(
                    child,
                    path + (key,),
                    root_schema=root_schema,
                    artifact_node=child_artifact,
                )
            )
        item_schema = schema.get("items")
        if isinstance(item_schema, dict) and isinstance(artifact_node, list):
            for index, child_artifact in enumerate(artifact_node):
                paths.extend(
                    cls._formatted_paths(
                        item_schema,
                        path + (index,),
                        root_schema=root_schema,
                        artifact_node=child_artifact,
                    )
                )
        return paths

    @staticmethod
    def _mutated_value(value: object) -> object:
        if isinstance(value, bool):
            return not value
        if isinstance(value, int):
            return value + 1
        if isinstance(value, float):
            return value + 0.125
        if isinstance(value, str):
            return value + "__mutated"
        raise AssertionError(f"unsupported mutation type: {type(value).__name__}")

    @staticmethod
    def _error_paths(errors: list) -> set[tuple[str | int, ...]]:
        return {tuple(error.absolute_path) for error in errors}

    @staticmethod
    def _repo_relative(path: Path) -> str:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()

    def test_schema_and_artifact_validate(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        Draft7Validator.check_schema(self._schema())
        self.assertEqual(self._errors(self._artifact()), [])

    def test_every_declared_date_time_is_checked_and_checker_is_load_bearing(self) -> None:
        packet = self._artifact()
        schema = self._schema()
        paths = self._formatted_paths(schema, root_schema=schema, artifact_node=packet)
        self.assertGreater(len(paths), 0)
        for path in paths:
            with self.subTest(path=path):
                invalid = copy.deepcopy(packet)
                self._set_path(invalid, path, "not-a-date-time")
                self.assertIn(path, self._error_paths(self._errors(invalid)))
                self.assertNotIn(path, self._error_paths(self._errors(invalid, armed=False)))

    def test_exact_stage1_templates_are_const_pinned_bounded_and_have_no_obvious_seed_topic(self) -> None:
        packet = self._artifact()
        templates = packet["query_templates"]
        self.assertEqual(len(templates), 4)
        self.assertEqual(len({row["query_id"] for row in templates}), 4)
        self.assertTrue(all(1 <= len(row["text"]) <= 300 for row in templates))
        self.assertTrue(all(row["query_id"].startswith("stage1_") for row in templates))
        self.assertTrue(all("US-listed companies" in row["text"] for row in templates))
        forbidden_seed_literals = {
            "AAPL", "MSFT", "NVDA", "AMZN", "BRK.B",
            "semiconductor", "utility", "nuclear", "robotics", "data center",
        }
        combined = " ".join(row["text"] for row in templates).casefold()
        for literal in forbidden_seed_literals:
            with self.subTest(literal=literal):
                self.assertNotIn(literal.casefold(), combined)

    def test_probe_is_not_execution_authorization_or_production_policy(self) -> None:
        packet = self._artifact()
        scope = packet["scope"]
        self.assertEqual(scope["status"], "offline_probe_packet_not_executed")
        self.assertFalse(scope["network_access_performed"])
        self.assertFalse(scope["provider_calls_performed"])
        self.assertFalse(scope["provider_execution_authorized_by_this_packet"])
        self.assertTrue(scope["explicit_user_authorization_required_for_execution"])
        self.assertTrue(scope["test_level_only"])
        self.assertFalse(scope["production_query_policy_activated"])
        self.assertTrue(all(value is False for value in packet["prohibited_effects"].values()))

    def test_decision_slot_and_call_arithmetic_are_exact(self) -> None:
        packet = self._artifact()
        boundary = packet["probe_boundary"]
        budget = packet["provider_budget"]
        self.assertEqual(boundary["expected_decision_date"], "20260802")
        self.assertNotIn(boundary["expected_decision_date"], boundary["forbidden_reused_decision_dates"])
        self.assertEqual(boundary["lanes"], ["web", "x"])
        self.assertEqual(boundary["stage"], "stage1_only")
        self.assertEqual(boundary["query_count_per_lane"], 4)
        self.assertEqual(boundary["retry_or_rerun_count"], 0)
        self.assertEqual(budget["xai"]["max_actual_calls"], 4)
        self.assertEqual(budget["tavily"]["max_actual_calls"], 4)
        self.assertEqual(budget["deepseek"]["structural_max_actual_calls"], 4)
        self.assertEqual(budget["max_actual_provider_calls"], 12)
        self.assertEqual(budget["current_ledger_reservation_units"], 12)
        self.assertTrue(budget["reservation_units_are_not_actual_spend"])

    def test_execution_slot_map_is_exactly_derived_from_runner_defaults(self) -> None:
        packet = self._artifact()
        slots = packet["execution_slot_map"]
        decision_date = packet["probe_boundary"]["expected_decision_date"]
        self.assertEqual(slots["expected_decision_date"], decision_date)
        self.assertEqual(
            slots["decision_outputs"],
            {
                "web_discovery": self._repo_relative(web.default_discovery_path(decision_date)),
                "web_receipt": self._repo_relative(web.default_receipt_path(decision_date)),
                "x_discovery": self._repo_relative(x.default_discovery_path(decision_date)),
                "x_receipt": self._repo_relative(x.default_receipt_path(decision_date)),
            },
        )
        self.assertEqual(
            slots["budget_ledgers"],
            {
                "web": self._repo_relative(
                    plan_budget.default_plan_budget_path(
                        "web", decision_date, state_dir=ROOT / "state" / "us_short"
                    )
                ),
                "xai": self._repo_relative(
                    plan_budget.default_plan_budget_path(
                        "xai", decision_date, state_dir=ROOT / "state" / "us_short"
                    )
                ),
            },
        )
        self.assertEqual(
            slots["raw_roots"],
            {
                "web": self._repo_relative(web.DEFAULT_RAW_ROOT),
                "x": self._repo_relative(x.DEFAULT_RAW_ROOT),
            },
        )
        self.assertEqual(
            slots["assessment_path"],
            self._repo_relative(probe_paths.default_assessment_path(decision_date)),
        )
        self.assertFalse(slots["output_or_receipt_overrides_allowed"])
        self.assertFalse(slots["raw_root_overrides_allowed"])
        self.assertFalse(slots["unregistered_slots_allowed"])
        self.assertEqual(
            probe_paths.validate_assessment_path(slots["assessment_path"], decision_date),
            probe_paths.default_assessment_path(decision_date).resolve(),
        )
        with self.assertRaises(probe_paths.QueryQualityProbePathError):
            probe_paths.validate_assessment_path(
                ROOT / "docs" / "unregistered_query_quality_assessment.json",
                decision_date,
            )

    def test_runner_publish_preflight_rejects_each_unregistered_output_override(self) -> None:
        decision_date = self._artifact()["probe_boundary"]["expected_decision_date"]
        lane_paths = {
            "web": (
                web.default_discovery_path(decision_date),
                web.default_receipt_path(decision_date),
            ),
            "x": (
                x.default_discovery_path(decision_date),
                x.default_receipt_path(decision_date),
            ),
        }
        for lane, (discovery, receipt) in lane_paths.items():
            self.assertEqual(
                web._decision_publish_paths(discovery, discovery, receipt, receipt),
                (discovery.resolve(), receipt.resolve()),
            )
            for field, first, second in (
                ("discovery", discovery.with_name(discovery.stem + "_override.json"), receipt),
                ("receipt", discovery, receipt.with_name(receipt.stem + "_override.json")),
            ):
                with self.subTest(lane=lane, field=field):
                    with self.assertRaises(web.WebThemeDiscoveryError):
                        web._decision_publish_paths(first, discovery, second, receipt)

    def test_each_live_cli_rejects_an_unregistered_raw_root_before_provider_access(self) -> None:
        decision_date = self._artifact()["probe_boundary"]["expected_decision_date"]
        generated_at = "2026-07-30T10:00:00Z"
        alternate = ROOT / "provider_samples" / "unregistered_query_quality_probe"
        parent = query_plan.build_parent_plan(
            decision_date=decision_date,
            policy_version="soft_discovery_query_policy_v0.1.0",
            policy_template_content_sha256="a" * 64,
            stage1_queries=[{"query_id": "stage1-a", "query_text": "offline boundary probe"}],
            stage2_rule_sha256="b" * 64,
            provider_envelopes=[
                {"provider": "web", "stage1_max_dispatch_count": 1, "stage2_max_dispatch_count": 0, "retry_max_dispatch_count": 1, "max_dispatch_count": 2},
                {"provider": "xai", "stage1_max_dispatch_count": 1, "stage2_max_dispatch_count": 0, "retry_max_dispatch_count": 1, "max_dispatch_count": 2},
            ],
            generated_at="2026-07-30T08:00:00Z",
        )
        plan_path = ROOT / "docs" / "test_query_quality_probe_parent_plan.json"
        lanes = {
            "web": (
                web.main,
                [
                    "--parent-plan", str(plan_path),
                    "--expected-decision-date", decision_date,
                    "--generated-at", generated_at,
                    "--live",
                    "--raw-root", str(alternate),
                ],
                web.WebThemeDiscoveryError,
            ),
            "x": (
                x.main,
                [
                    "--parent-plan", str(plan_path),
                    "--expected-decision-date", decision_date,
                    "--generated-at", generated_at,
                    "--live",
                    "--raw-root", str(alternate),
                ],
                web.WebThemeDiscoveryError,
            ),
        }
        for lane, (main, argv, error) in lanes.items():
            with self.subTest(lane=lane):
                with mock.patch.object(
                    web.query_plan,
                    "read_parent_plan",
                    return_value=(parent, "a" * 64, "docs/test_query_quality_probe_parent_plan.json"),
                ):
                    with self.assertRaisesRegex(error, "live CLI raw_root must use the lane default"):
                        main(argv)

    def test_each_live_cli_default_raw_root_passes_the_shared_exact_preflight(self) -> None:
        for lane, raw_root in (("web", web.DEFAULT_RAW_ROOT), ("x", x.DEFAULT_RAW_ROOT)):
            with self.subTest(lane=lane):
                self.assertEqual(
                    web._validate_cli_raw_root(raw_root, raw_root, live=True),
                    raw_root.resolve(),
                )

    def test_quality_thresholds_are_preregistered_and_keep_execution_failure_inconclusive(self) -> None:
        evaluation = self._artifact()["preregistered_evaluation"]
        per_lane = evaluation["per_lane_quality_thresholds"]
        combined = evaluation["combined_quality_thresholds"]
        self.assertEqual(per_lane["minimum_validated_theme_count"], 1)
        self.assertEqual(per_lane["minimum_source_bound_member_count"], 3)
        self.assertEqual(per_lane["minimum_member_bound_source_ratio"], 0.5)
        self.assertEqual(combined["distinct_candidate_theme_ids_diagnostic_target"], 2)
        self.assertFalse(combined["breadth_diagnostic_is_pass_gate"])
        self.assertTrue(combined["both_lanes_must_meet_per_lane_thresholds"])
        self.assertIn("provider_auth_or_transport_failure", evaluation["transport_inconclusive_conditions"])
        self.assertEqual(
            evaluation["inconclusive_verdict"],
            "provider_or_execution_inconclusive_do_not_grade_templates",
        )
        self.assertTrue(evaluation["no_posthoc_threshold_change"])
        definitions = evaluation["metric_definitions"]
        self.assertIn("distinct canonical member tickers", definitions["source_bound_member_count"])
        self.assertIn("divided by accepted_source_count", definitions["member_bound_source_ratio"])

    def test_web_and_x_raw_roots_are_separate_and_non_production(self) -> None:
        packet = self._artifact()
        roots = packet["execution_slot_map"]["raw_roots"]
        self.assertNotEqual(roots["web"], roots["x"])
        self.assertEqual(
            web._validate_raw_root(web.DEFAULT_RAW_ROOT, require_gitignored=True),
            web.DEFAULT_RAW_ROOT.resolve(),
        )
        self.assertEqual(
            web._validate_raw_root(x.DEFAULT_RAW_ROOT, require_gitignored=True),
            x.DEFAULT_RAW_ROOT.resolve(),
        )
        storage = self._artifact()["storage_and_secret_boundary"]
        self.assertEqual(storage["raw_roots_source"], "execution_slot_map.raw_roots")
        self.assertEqual(storage["assessment_path_source"], "execution_slot_map.assessment_path")
        self.assertTrue(storage["raw_must_be_gitignored"])
        self.assertFalse(storage["tracked_raw_rows_allowed"])
        self.assertFalse(storage["tracked_request_urls_allowed"])
        self.assertFalse(storage["tracked_secrets_allowed"])
        self.assertFalse(storage["production_storage_authorized"])

    def test_every_security_boundary_leaf_rejects_one_mutation_at_a_time(self) -> None:
        packet = self._artifact()
        guarded_sections = (
            "scope",
            "provider_budget",
            "pre_execution_gates",
            "execution_slot_map",
            "prohibited_effects",
        )
        paths = [
            (section,) + leaf
            for section in guarded_sections
            for leaf in self._leaf_paths(packet[section])
        ]
        paths.append(("probe_boundary", "expected_decision_date"))
        for threshold_group in ("per_lane_quality_thresholds", "combined_quality_thresholds"):
            paths.extend(
                ("preregistered_evaluation", threshold_group) + leaf
                for leaf in self._leaf_paths(
                    packet["preregistered_evaluation"][threshold_group]
                )
            )
        self.assertGreater(len(paths), 0)
        for path in paths:
            with self.subTest(path=path):
                invalid = copy.deepcopy(packet)
                self._set_path(
                    invalid,
                    path,
                    self._mutated_value(self._get_path(invalid, path)),
                )
                self.assertIn(path, self._error_paths(self._errors(invalid)))

    def test_each_query_is_independently_const_pinned(self) -> None:
        packet = self._artifact()
        for index, template in enumerate(packet["query_templates"]):
            with self.subTest(query_id=template["query_id"]):
                invalid = copy.deepcopy(packet)
                invalid["query_templates"][index]["text"] += " mutated"
                self.assertIn(
                    ("query_templates",),
                    self._error_paths(self._errors(invalid)),
                )


if __name__ == "__main__":
    unittest.main()
