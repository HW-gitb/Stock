import tempfile
import unittest
from pathlib import Path

from engine.analyzer import state_manager


class StateManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_circuit_path = state_manager.CIRCUIT_BREAKER_PATH
        state_manager.CIRCUIT_BREAKER_PATH = Path(self.tmpdir.name) / "circuit_breaker.json"

    def tearDown(self):
        state_manager.CIRCUIT_BREAKER_PATH = self.old_circuit_path
        self.tmpdir.cleanup()

    def write_circuit(self, **overrides):
        payload = {
            "schema_version": "1.0.0",
            "preset": "a_short",
            "updated_at": None,
            "active": False,
            "reason": None,
            "triggered_at": None,
            "expires_at": None,
        }
        payload.update(overrides)
        state_manager.atomic_write_json(state_manager.CIRCUIT_BREAKER_PATH, payload)

    def test_inactive_circuit_breaker_is_false(self):
        self.write_circuit(active=False)
        self.assertFalse(state_manager.is_circuit_breaker_active("2026-05-25T00:00:00Z"))

    def test_active_without_expiry_is_true(self):
        self.write_circuit(active=True, expires_at=None)
        self.assertTrue(state_manager.is_circuit_breaker_active("2026-05-25T00:00:00Z"))

    def test_active_future_expiry_is_true(self):
        self.write_circuit(active=True, expires_at="2026-05-26T00:00:00Z")
        self.assertTrue(state_manager.is_circuit_breaker_active("2026-05-25T00:00:00Z"))

    def test_active_expired_is_false(self):
        self.write_circuit(active=True, expires_at="2026-05-24T00:00:00Z")
        self.assertFalse(state_manager.is_circuit_breaker_active("2026-05-25T00:00:00Z"))

    def test_malformed_expiry_stays_active(self):
        self.write_circuit(active=True, expires_at="not-a-date")
        self.assertTrue(state_manager.is_circuit_breaker_active("2026-05-25T00:00:00Z"))


if __name__ == "__main__":
    unittest.main()
