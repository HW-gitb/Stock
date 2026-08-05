import hashlib
import json
import copy
from pathlib import Path
import unittest

import jsonschema

from engine import a_short_evidence_epoch_mode as epoch_mode
from tests._a_short_epoch_mode_test_utils import patched_epoch_modes


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

    def test_schema_pins_all_eight_contract_identities_and_order(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        mutations = []

        dropped = copy.deepcopy(artifact)
        dropped["frozen_contracts"].pop()
        mutations.append(dropped)

        duplicated = copy.deepcopy(artifact)
        duplicated["frozen_contracts"][-1] = dict(duplicated["frozen_contracts"][0])
        mutations.append(duplicated)

        renamed = copy.deepcopy(artifact)
        renamed["frozen_contracts"][2]["name"] = "same_shape_other_governance"
        mutations.append(renamed)

        repointed = copy.deepcopy(artifact)
        repointed["frozen_contracts"][2]["path"] = renamed["frozen_contracts"][1]["path"]
        mutations.append(repointed)

        reordered = copy.deepcopy(artifact)
        reordered["frozen_contracts"][0], reordered["frozen_contracts"][1] = (
            reordered["frozen_contracts"][1], reordered["frozen_contracts"][0],
        )
        mutations.append(reordered)

        for mutation in mutations:
            with self.subTest(
                    contracts=[
                        item.get("name") for item in mutation["frozen_contracts"]
                    ],
            ), self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(mutation, schema)

    def test_contract_inventory_has_one_identity_across_schema_runtime_and_packet(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        schema_inventory = {
            item["allOf"][1]["properties"]["name"]["const"]:
            item["allOf"][1]["properties"]["path"]["const"]
            for item in schema["properties"]["frozen_contracts"]["prefixItems"]
        }
        packet_inventory = {
            item["name"]: item["path"]
            for item in artifact["frozen_contracts"]
        }
        self.assertEqual(
            schema_inventory,
            epoch_mode._FIFTH_KNIFE_FROZEN_CONTRACTS,
        )
        self.assertEqual(packet_inventory, schema_inventory)

    def test_freeze_packet_cannot_claim_forward_evidence_or_promotion(self) -> None:
        artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(artifact["status"], "frozen_not_started")
        self.assertEqual(artifact["ship_gate"]["observed_forward_live_months"], 0)
        self.assertFalse(artifact["boundary"]["effectiveness_claimed"])
        self.assertFalse(artifact["boundary"]["production_promotion_allowed"])
        self.assertFalse(artifact["capture_contract"]["historical_replay_counts_as_forward"])

    def test_frozen_contracts_recompute_match_their_files(self) -> None:
        # The shipped registry is pre-freeze, so the live packet may honestly
        # carry stale hashes. Runtime enforcement is exercised against a
        # test-resealed packet; this test proves the transition re-arms through
        # every track rather than one P4a proxy.
        artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(artifact["status"], "frozen_not_started")
        for track in epoch_mode.TRACKS:
            with self.subTest(track=track), patched_epoch_modes(
                    "frozen_enforced", (track,)):
                self.assertTrue(epoch_mode.enforcement_enabled(track))

    def test_enforced_epoch_rejects_recorded_contract_drift(self) -> None:
        with patched_epoch_modes(
                "frozen_enforced", ("p2_target_policy",)):
            artifact_path = epoch_mode.FIFTH_KNIFE_FREEZE_PACKET_PATH
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifact["frozen_contracts"][0]["semantic_fingerprint"] = "0" * 64
            artifact["record_sha256"] = _digest({
                key: value for key, value in artifact.items()
                if key != "record_sha256"
            })
            artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
            with self.assertRaisesRegex(
                    epoch_mode.EvidenceEpochModeError,
                    "fifth-knife frozen contract semantic drift",
            ):
                epoch_mode.enforcement_enabled("p2_target_policy")


if __name__ == "__main__":
    unittest.main()
