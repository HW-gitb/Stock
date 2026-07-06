from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))

from jsonschema import Draft7Validator  # noqa: E402


SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_candidate_projection_inputs_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_full_candidate_projection_inputs_summary_20260706.json"


class UsShortBatch5FullCandidateProjectionInputsSummarySchemaTest(unittest.TestCase):
    def test_tracked_summary_validates(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))

        Draft7Validator(schema).validate(summary)

    def test_schema_rejects_scope_creep_and_false_evidence_claims(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        validator = Draft7Validator(schema)

        for path, value in (
            (("scope", "provider_calls_performed"), True),
            (("scope", "full_market_call_performed"), True),
            (("scope", "ship_gate_or_live_normalized_evidence_claimed"), True),
            (("output_projection_contract", "full_candidate_local_inputs_ready"), False),
            (("prohibited_claims", "datahub_consumed"), True),
            (("prohibited_claims", "ship_gate_evidence_claimed"), True),
        ):
            mutated = json.loads(json.dumps(summary))
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertGreater(len(list(validator.iter_errors(mutated))), 0, path)


if __name__ == "__main__":
    unittest.main()
