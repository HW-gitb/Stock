import hashlib
import json
from pathlib import Path
import unittest

import jsonschema


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "a_short_fifth_knife_forward_evidence_freeze.schema.json"
ARTIFACT = ROOT / "docs" / "a_short_fifth_knife_forward_evidence_freeze_20260724.json"


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class AShortFifthKnifeForwardEvidenceFreezeTests(unittest.TestCase):
    def test_freeze_packet_matches_schema_and_self_hash(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        jsonschema.validate(artifact, schema)
        self.assertEqual(artifact["record_sha256"], _digest({k: v for k, v in artifact.items() if k != "record_sha256"}))

    def test_freeze_packet_cannot_claim_forward_evidence_or_promotion(self) -> None:
        artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(artifact["status"], "frozen_not_started")
        self.assertEqual(artifact["ship_gate"]["observed_forward_live_months"], 0)
        self.assertFalse(artifact["boundary"]["effectiveness_claimed"])
        self.assertFalse(artifact["boundary"]["production_promotion_allowed"])
        self.assertFalse(artifact["capture_contract"]["historical_replay_counts_as_forward"])

    def test_frozen_contracts_recompute_match_their_files(self) -> None:
        # Guard the frozen-contract integrity itself: recompute each contract's
        # LF-canonical sha256 (checkout-independent) and require it to equal the
        # recorded hash. A silent change to any frozen contract must fail this test,
        # forcing a fifth-knife reseal or a new evidence epoch instead of drifting.
        artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        for contract in artifact["frozen_contracts"]:
            path = ROOT / contract["path"]
            self.assertTrue(path.is_file(), f"frozen contract missing: {contract['path']}")
            content = path.read_bytes().replace(b"\r\n", b"\n")
            actual = hashlib.sha256(content).hexdigest()
            self.assertEqual(
                actual,
                contract["sha256"],
                f"frozen contract drifted from the fifth-knife freeze "
                f"(reseal the packet or open a new epoch): {contract['path']}",
            )


if __name__ == "__main__":
    unittest.main()
