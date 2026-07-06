import copy
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_candidate_pass2_preflight_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_full_candidate_pass2_preflight_summary_20260706.json"


def _validator():
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError as exc:
        raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
    return Draft7Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def _summary():
    return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))


class UsShortBatch5FullCandidatePass2PreflightSummarySchemaTest(unittest.TestCase):
    def test_tracked_summary_validates(self):
        _validator().validate(_summary())

    def test_rejects_scope_creep_claims(self):
        for path, value in (
            (("scope", "network_access_performed"), True),
            (("scope", "source_packet_written"), True),
            (("scope", "datahub_consumption_performed"), True),
            (("execution_gate", "corporate_action_reconciliation_claimed"), True),
            (("prohibited_claims", "ship_gate_evidence_claimed"), True),
        ):
            mutated = copy.deepcopy(_summary())
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertFalse(_validator().is_valid(mutated), path)

    def test_rejects_untracked_or_raw_like_summary_path(self):
        mutated = _summary()
        mutated["storage"]["tracked_summary_path"] = "provider_samples/other/raw/payload.json"
        self.assertFalse(_validator().is_valid(mutated))


if __name__ == "__main__":
    unittest.main()
