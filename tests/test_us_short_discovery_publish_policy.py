from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from runners import us_short_discovery_publish_policy as policy


class _LookalikeLock:
    pass


class DiscoveryPublishPolicyTransitionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="us_short_publish_policy_")
        self.addCleanup(self.tempdir.cleanup)
        self.test_root = Path(self.tempdir.name)

    def test_zero_to_valid_upgrade_policy_has_closed_transition_table(self):
        """Only the named, lock-held zero-to-valid transition may replace a frozen slot."""

        def payload(status, evidence, generated_at, *, decision_date="20260615"):
            return {
                "decision_date": decision_date,
                "generated_at": generated_at,
                "status": status,
                "evidence": evidence,
                "bindings": {
                    "stage_receipt": {"sha256": "a" * 64},
                    "validation_artifact": {"sha256": "b" * 64},
                },
            }

        def slot_and_lock():
            case_root = self.test_root / self._case_name
            slot = case_root / "us_short_soft_boost_consumption_receipt_20260615.json"
            lock_path = case_root / "_transaction_locks" / "20260615.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_bytes(b"\\0")
            handle = lock_path.open("a+b")
            self.addCleanup(handle.close)
            return slot, SimpleNamespace(path=lock_path, handle=handle)

        def write_matching_shadow(receipt):
            shadow = self.test_root / self._case_name / "shadow_compare_private" / (
                "us_short_soft_boost_shadow_receipt_20260615.json"
            )
            shadow.parent.mkdir(parents=True, exist_ok=True)
            shadow.write_text(json.dumps({
                "decision_date": receipt["decision_date"],
                "stage_receipt_sha256": receipt["bindings"]["stage_receipt"]["sha256"],
                "validation_artifact_sha256": receipt["bindings"]["validation_artifact"]["sha256"],
            }), encoding="utf-8")

        valid = payload("consumed_valid_nonempty", "valid", "2026-06-12T12:25:00Z")
        for status in (
            "zero_valid_empty",
            "zero_upstream_unavailable",
            "zero_invalid_evidence",
        ):
            with self.subTest(allowed=status):
                self._case_name = f"allowed_{status}"
                slot, lock = slot_and_lock()
                self.assertFalse(policy.write_immutable_json(payload(status, status, "2026-06-12T12:20:00Z"), slot))
                write_matching_shadow(valid)
                self.assertFalse(policy.write_immutable_json(
                    valid, slot, replacement_policy=policy.ZERO_TO_VALID_UPGRADE,
                    decision_lock=lock,
                ))
                self.assertEqual(json.loads(slot.read_text(encoding="utf-8"))["status"], "consumed_valid_nonempty")

        rejected = (
            ("downgrade", valid, payload("zero_valid_empty", "zero", "2026-06-12T12:30:00Z")),
            ("valid_to_valid", valid, payload("consumed_valid_nonempty", "other", "2026-06-12T12:30:00Z")),
            ("zero_to_zero", payload("zero_valid_empty", "zero", "2026-06-12T12:20:00Z"),
             payload("zero_upstream_unavailable", "other", "2026-06-12T12:30:00Z")),
        )
        for name, existing, replacement in rejected:
            with self.subTest(rejected=name):
                self._case_name = f"rejected_{name}"
                slot, lock = slot_and_lock()
                self.assertFalse(policy.write_immutable_json(existing, slot))
                with self.assertRaises(policy.DiscoveryPublishPolicyError):
                    policy.write_immutable_json(
                        replacement, slot, replacement_policy=policy.ZERO_TO_VALID_UPGRADE,
                        decision_lock=lock,
                    )

        self._case_name = "rejected_unreadable"
        _slot, lock = slot_and_lock()
        unreadable = self.test_root / self._case_name / "us_short_soft_boost_consumption_receipt_20260615.json"
        unreadable.parent.mkdir(parents=True, exist_ok=True)
        unreadable.write_text("{not-json", encoding="utf-8")
        with self.assertRaises(policy.DiscoveryPublishPolicyError):
            policy.write_immutable_json(
                valid, unreadable, replacement_policy=policy.ZERO_TO_VALID_UPGRADE,
                decision_lock=lock,
            )

        self._case_name = "no_policy"
        no_policy, lock = slot_and_lock()
        self.assertFalse(policy.write_immutable_json(
            payload("zero_valid_empty", "zero", "2026-06-12T12:20:00Z"), no_policy,
        ))
        with self.assertRaises(policy.DiscoveryPublishPolicyError):
            policy.write_immutable_json(valid, no_policy, decision_lock=lock)

        self._case_name = "no_lock"
        no_lock, _ = slot_and_lock()
        self.assertFalse(policy.write_immutable_json(
            payload("zero_valid_empty", "zero", "2026-06-12T12:20:00Z"), no_lock,
        ))
        with self.assertRaisesRegex(policy.DiscoveryPublishPolicyError, "live decision-date lock"):
            policy.write_immutable_json(
                valid, no_lock, replacement_policy=policy.ZERO_TO_VALID_UPGRADE,
            )

    def test_zero_to_valid_upgrade_binds_target_slot_existing_receipt_and_frozen_shadow(self):
        def payload(*, decision_date="20260615", stage_sha="a", validation_sha="b"):
            return {
                "decision_date": decision_date,
                "generated_at": "2026-06-12T12:25:00Z",
                "status": "consumed_valid_nonempty",
                "bindings": {
                    "stage_receipt": {"sha256": stage_sha * 64},
                    "validation_artifact": {"sha256": validation_sha * 64},
                },
            }

        def setup():
            case_root = self.test_root / self._case_name
            slot = case_root / "us_short_soft_boost_consumption_receipt_20260615.json"
            lock_path = case_root / "_transaction_locks" / "20260615.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_bytes(b"\\0")
            handle = lock_path.open("a+b")
            self.addCleanup(handle.close)
            return slot, SimpleNamespace(path=lock_path, handle=handle)

        def write_shadow(*, decision_date="20260615", stage_sha="a", validation_sha="b"):
            shadow = self.test_root / self._case_name / "shadow_compare_private" / (
                "us_short_soft_boost_shadow_receipt_20260615.json"
            )
            shadow.parent.mkdir(parents=True, exist_ok=True)
            shadow.write_text(json.dumps({
                "decision_date": decision_date,
                "stage_receipt_sha256": stage_sha * 64,
                "validation_artifact_sha256": validation_sha * 64,
            }), encoding="utf-8")

        for name, existing, replacement, shadow in (
            (
                "caller_claimed_different_date",
                {**payload(), "status": "zero_valid_empty"},
                payload(decision_date="20260622"),
                ("20260615", "a", "b"),
            ),
            (
                "frozen_receipt_has_different_date",
                {**payload(decision_date="20260614"), "status": "zero_valid_empty"},
                payload(),
                ("20260615", "a", "b"),
            ),
            (
                "frozen_shadow_has_different_stage_binding",
                {**payload(), "status": "zero_valid_empty"},
                payload(),
                ("20260615", "c", "b"),
            ),
        ):
            with self.subTest(rejected=name):
                self._case_name = name
                slot, lock = setup()
                self.assertFalse(policy.write_immutable_json(existing, slot))
                write_shadow(decision_date=shadow[0], stage_sha=shadow[1], validation_sha=shadow[2])
                with self.assertRaises(policy.DiscoveryPublishPolicyError):
                    policy.write_immutable_json(
                        replacement, slot, replacement_policy=policy.ZERO_TO_VALID_UPGRADE,
                        decision_lock=lock,
                    )

        self._case_name = "lookalike_lock"
        slot, lock = setup()
        existing = {**payload(), "status": "zero_valid_empty"}
        self.assertFalse(policy.write_immutable_json(existing, slot))
        write_shadow()
        lookalike = _LookalikeLock()
        lookalike.path = lock.path
        lookalike.handle = object()
        with self.assertRaisesRegex(policy.DiscoveryPublishPolicyError, "live decision-date lock"):
            policy.write_immutable_json(
                payload(), slot, replacement_policy=policy.ZERO_TO_VALID_UPGRADE,
                decision_lock=lookalike,
            )

    def test_publish_policy_optional_parameter_paths_are_exercised(self):
        projection = lambda value: value["body"]
        first = self.test_root / "projected_first.json"
        second = self.test_root / "projected_second.json"
        payload = {"generated_at": "2026-06-12T12:20:00Z", "body": {"evidence": "frozen"}}
        self.assertEqual(
            policy.evidence_bytes(payload, evidence_projection=projection),
            b'{"evidence":"frozen"}',
        )
        self.assertFalse(policy.write_immutable_json(payload, first))
        self.assertTrue(policy.frozen_artifact_matches(
            {"generated_at": "2026-06-12T12:25:00Z", "body": {"evidence": "frozen"}},
            first, evidence_projection=projection,
        ))
        policy.publish_immutable_pair(
            ((payload, second),), clock_keys=("generated_at",), recursive=True,
            verifiers=(lambda value: self.assertEqual(value["body"]["evidence"], "frozen"),),
            evidence_projections=(projection,),
        )

    def test_private_diagnostic_json_can_be_replaced(self):
        state_dir = self.test_root / "state" / "us_short"
        path = state_dir / "runs_private" / "replay.json"
        ignored = lambda _path: True
        policy._write_mutable_private_json(
            {"attempt": 1}, path, root=self.test_root, state_dir=state_dir,
            gitignored=ignored,
        )
        policy._write_mutable_private_json(
            {"attempt": 2}, path, root=self.test_root, state_dir=state_dir,
            gitignored=ignored,
        )
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"attempt": 2})

    def test_private_diagnostic_json_rejects_formal_decision_slot(self):
        state_dir = self.test_root / "state" / "us_short"
        formal_slot = state_dir / "us_short_soft_boost_consumption_receipt_20260615.json"
        with self.assertRaisesRegex(policy.DiscoveryPublishPolicyError, "runs_private"):
            policy._write_mutable_private_json(
                {"attempt": 1}, formal_slot, root=self.test_root,
                state_dir=state_dir, gitignored=lambda _path: True,
            )
        self.assertFalse(formal_slot.exists())
