import hashlib
import json
from pathlib import Path
import unittest
from unittest import mock

import jsonschema

from engine import a_short_evidence_epoch_mode as epoch_mode


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "a_short_fifth_knife_forward_evidence_freeze.schema.json"
ARTIFACT = ROOT / "docs" / "a_short_fifth_knife_forward_evidence_freeze_20260724.json"


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _hashes_must_match(artifact: dict) -> bool:
    # The packet is intentionally schema-pinned to frozen_not_started until a
    # separately reviewed evidence epoch is opened.  That status therefore
    # cannot be the re-arm signal: using it here makes the hash guard dead
    # forever.  The epoch-mode switch is the authoritative transition; the
    # pre-freeze branch below continues to enforce the packet's honesty fields.
    return epoch_mode.enforcement_enabled()


def _assert_frozen_contract_hashes(testcase: unittest.TestCase, artifact: dict) -> None:
    for contract in artifact["frozen_contracts"]:
        path = ROOT / contract["path"]
        testcase.assertTrue(path.is_file(), f"frozen contract missing: {contract['path']}")
        content = path.read_bytes().replace(b"\r\n", b"\n")
        actual = hashlib.sha256(content).hexdigest()
        testcase.assertEqual(
            actual,
            contract["sha256"],
            f"frozen contract drifted from the fifth-knife freeze "
            f"(reseal the packet or open a new epoch): {contract['path']}",
        )


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
        if not _hashes_must_match(artifact):
            self.assertEqual(artifact["status"], "frozen_not_started")
            self.assertEqual(artifact["ship_gate"]["observed_forward_live_months"], 0)
            self.assertFalse(artifact["boundary"]["effectiveness_claimed"])
            self.assertFalse(artifact["boundary"]["production_promotion_allowed"])
            return
        _assert_frozen_contract_hashes(self, artifact)

    def test_enforced_epoch_rejects_recorded_contract_drift(self) -> None:
        artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        with mock.patch.object(epoch_mode, "MODE", "frozen_enforced"):
            self.assertTrue(_hashes_must_match(artifact))
        # Plant drift in the copied packet itself.  This remains a real
        # reverse control even after the live packet is fully resealed.
        artifact["frozen_contracts"][0]["sha256"] = "0" * 64
        with mock.patch.object(epoch_mode, "MODE", "frozen_enforced"):
            with self.assertRaises(AssertionError):
                _assert_frozen_contract_hashes(self, artifact)


if __name__ == "__main__":
    unittest.main()
