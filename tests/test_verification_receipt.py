from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".tools"))
import verification_receipt as receipts  # noqa: E402


class VerificationReceiptTests(unittest.TestCase):
    EFFECT_ARGS = [
        "tests.test_a_short_effect_contract",
        "tests.test_a_short_effect_consumer_probe",
    ]

    def _receipt(self, state: dict[str, str], path: Path, args: list[str] | None = None) -> dict:
        with patch.object(receipts.sys, "executable", str(receipts.PINNED_PYTHON)):
            receipt = receipts.write_focused_receipt(
                result_status="PASS",
                result_exit_code=0,
                tests=17,
                elapsed_seconds=1.25,
                timeout_seconds=300,
                unittest_args=args or self.EFFECT_ARGS,
                state=state,
                path=path,
            )
        self.assertIsNotNone(receipt)
        return receipt or {}

    def test_every_recorded_field_is_inside_the_integrity_seal(self):
        """Class fix: no recorded field may sit outside receipt_id's hash.

        The first form hashed only code_fingerprint + unittest_args, so `tests`
        -- the number quoted as evidence -- could be inflated and still
        validate.  Mutating ANY field must now break the integrity check.
        """
        state = {"engine/a_short_effect_contract.py": "sha", "@HEAD": "head"}
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self._receipt(state, Path(tmp) / "r.json")
        mutations = {
            "tests": 99999,
            "elapsed_seconds": 0.001,
            "timeout_seconds": 1300,
            "recorded_at": "1999-01-01T00:00:00",
            "schema_version": "9.9",
            "tier": "full",
            "status": "PASS ",
            "exit_code": 0,
        }
        self.assertTrue(set(mutations).issubset(receipt), "a recorded field escaped this matrix")
        for field, value in mutations.items():
            if receipt[field] == value:
                continue
            tampered = dict(receipt, **{field: value})
            self.assertNotEqual(
                receipt["receipt_id"],
                receipts._receipt_id(tampered),
                f"{field} is outside the integrity seal",
            )
        # And the honest receipt still validates against its own seal.
        self.assertEqual(receipt["receipt_id"], receipts._receipt_id(receipt))

    def test_inflated_test_count_is_rejected_end_to_end(self):
        """The exact reviewer probe that found the hole: 17 -> 99999."""
        state = {"engine/a_short_effect_contract.py": "sha", "@HEAD": "head"}
        with tempfile.TemporaryDirectory() as tmp:
            receipt = self._receipt(state, Path(tmp) / "r.json")
        inflated = dict(receipt, tests=99999)
        ok, reason = receipts.validate_receipt(inflated, state=state)
        self.assertFalse(ok)
        self.assertIn("integrity check failed", reason)

    def test_effect_surface_requires_both_contract_and_consumer_modules(self):
        state = {
            "engine/a_short_effect_contract.py": "sha",
            "@HEAD": "head",
        }
        self.assertEqual(
            receipts.required_bundles_for_state(state),
            ("a_short_effect_contract",),
        )
        self.assertEqual(
            receipts.bundle_for_args(self.EFFECT_ARGS),
            ("a_short_effect_contract",),
        )

    def test_free_text_focused_evidence_is_rejected(self):
        state = {"engine/x.py": "sha", "@HEAD": "head"}
        with tempfile.TemporaryDirectory() as tmp:
            _, reason = receipts.validate_focused_evidence(
                "focused=17 OK",
                state=state,
                path=Path(tmp) / "receipt.json",
            )
        self.assertIn("machine token", reason)

    def test_receipt_is_bound_to_code_state_and_token(self):
        state = {"engine/x.py": "sha", "@HEAD": "head"}
        changed = {"engine/x.py": "changed", "@HEAD": "head"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            receipt = self._receipt(state, path, ["tests.test_example"])
            token = receipts.receipt_token(receipt)
            loaded, reason = receipts.validate_focused_evidence(token, state=state, path=path)
            self.assertEqual(reason, "OK")
            self.assertEqual(loaded, receipt)
            _, changed_reason = receipts.validate_focused_evidence(token, state=changed, path=path)
            self.assertIn("current code state", changed_reason)

    def test_effect_receipt_without_consumer_bundle_is_rejected(self):
        state = {
            "runners/a_short_weekly_pipeline.py": "sha",
            "@HEAD": "head",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            receipt = self._receipt(state, path, ["tests.test_a_short_effect_contract"])
            _, reason = receipts.validate_focused_evidence(
                receipts.receipt_token(receipt), state=state, path=path
            )
        self.assertIn("missing bundle", reason)


if __name__ == "__main__":
    unittest.main()
