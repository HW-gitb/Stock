from __future__ import annotations

import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/candidate_universe_overlap_audit.schema.json")


class CandidateUniverseOverlapAuditSchemaTest(unittest.TestCase):
    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        Draft7Validator.check_schema(schema)
        self.assertEqual(
            schema["properties"]["schema_name"]["const"],
            "candidate_universe_overlap_audit",
        )
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertIn("benchmark-policy evidence", schema["description"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(
            schema["required"],
            [
                "schema_name",
                "schema_version",
                "generated_at",
                "as_of",
                "scope",
                "inputs",
                "settings",
                "candidate_universe",
                "benchmarks",
                "conclusion",
                "limitations",
            ],
        )

    def test_scope_blocks_primary_switch_and_requires_csi_pair(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

        scope = schema["$defs"]["scope"]["properties"]
        self.assertEqual(scope["phase"]["const"], "6b")
        self.assertEqual(scope["audit_status"]["const"], "audit_only")
        self.assertEqual(scope["primary_switch_allowed"]["const"], False)

        benchmarks = schema["$defs"]["benchmarks"]
        self.assertEqual(benchmarks["required"], ["csi1000", "csi300"])
        self.assertFalse(benchmarks["additionalProperties"])

        settings = schema["$defs"]["settings"]["properties"]
        self.assertEqual(
            schema["$defs"]["settings"]["required"],
            [
                "candidate_symbol_source",
                "provider",
                "api_families",
                "membership_source",
                "membership_window",
                "overlap_method",
                "primary_benchmark",
                "secondary_benchmarks",
            ],
        )
        self.assertEqual(settings["provider"]["const"], "tushare")
        self.assertEqual(settings["api_families"]["const"], ["index_weight", "tushare_provider"])
        self.assertEqual(settings["primary_benchmark"]["const"], "csi1000")
        self.assertEqual(settings["secondary_benchmarks"]["items"]["const"], "csi300")

        conclusion = schema["$defs"]["conclusion"]["properties"]
        self.assertEqual(conclusion["primary_switch_allowed"]["const"], False)
        self.assertEqual(
            conclusion["benchmark_policy_action"]["const"],
            "no_primary_switch_from_single_audit",
        )


if __name__ == "__main__":
    unittest.main()
