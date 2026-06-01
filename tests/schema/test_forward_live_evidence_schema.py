from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path("schemas/forward_live_evidence.schema.json")
EXAMPLE_PATH = Path("schemas/examples/forward_live_evidence.example.json")


class ForwardLiveEvidenceSchemaTest(unittest.TestCase):
    def _load_schema(self) -> dict:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _load_example(self) -> dict:
        return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

    def test_schema_meta_validates_when_jsonschema_available(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        schema = self._load_schema()

        Draft7Validator.check_schema(schema)
        self.assertIn("/1.0.0/", schema["$id"])
        self.assertEqual(schema["properties"]["schema_name"]["const"], "forward_live_evidence")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "1.0.0")
        self.assertIn("reviewed forward-live evidence", schema["description"])
        self.assertIn("actual-position reconciliation", schema["description"])
        self.assertFalse(schema["additionalProperties"])

    def test_example_validates(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        errors = list(Draft7Validator(self._load_schema()).iter_errors(self._load_example()))

        self.assertEqual(errors, [])

    def test_artifact_must_be_reviewed_live_normalized_and_reconciled(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        base = self._load_example()
        cases = [
            ("review_status", "draft"),
            ("evidence_level", "paper"),
            ("position_reconciliation.actual_position_reconciliation_available", False),
            ("position_reconciliation.reconciliation_status", "paper_no_actual_position"),
            ("scope_locks.paper_evidence_allowed_for_ship_gate", True),
            ("scope_locks.full_size_manual_use_authorized_by_this_artifact", True),
        ]
        validator = Draft7Validator(self._load_schema())
        for dotted_path, value in cases:
            with self.subTest(dotted_path=dotted_path):
                invalid = copy.deepcopy(base)
                target = invalid
                parts = dotted_path.split(".")
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = value

                errors = list(validator.iter_errors(invalid))

                self.assertGreater(len(errors), 0)

    def test_tracker_artifact_refs_are_required(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc

        invalid = self._load_example()
        invalid["provenance"]["tracker_artifact_refs"] = []

        errors = list(Draft7Validator(self._load_schema()).iter_errors(invalid))

        self.assertGreater(len(errors), 0)


if __name__ == "__main__":
    unittest.main()
