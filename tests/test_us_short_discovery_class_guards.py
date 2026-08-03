"""Class-level guards for US-short discovery operator-state and live-authority regressions."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from engine import us_short_llm_theme_discovery_paid_gateway as paid_gateway


ROOT = Path(__file__).resolve().parent.parent
PROTECTED_PRIVATE_ROOTS = {
    "state/us_short": ROOT / "state" / "us_short",
    "provider_samples": ROOT / "provider_samples",
    "docs": ROOT / "docs",
    "presets": ROOT / "presets",
    "schemas": ROOT / "schemas",
    "research": ROOT / "research",
}
INITIAL_PRIVATE_FILES = {
    label: frozenset(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
    for label, root in PROTECTED_PRIVATE_ROOTS.items()
}


class LaneResidueConformance(unittest.TestCase):
    """Tests/probes may not leave private-state growth; pre-existing authorized captures are legal.

    The import-time baselines deliberately tolerate state or raw receipts that an earlier authorized
    run left behind.  In the sequential unittest pack, any file still present below either protected
    root when this guard runs was written by a preceding test/probe and is a residue.  Tests that
    need raw files must use a temporary provider directory and clean it before returning.
    """

    @staticmethod
    def _growth(root: Path, baseline: frozenset[str]) -> list[str]:
        return sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*") if path.is_file()
            and path.relative_to(root).as_posix() not in baseline
        )

    def test_private_roots_do_not_grow_during_the_pack(self):
        for label, root in PROTECTED_PRIVATE_ROOTS.items():
            with self.subTest(root=label):
                self.assertEqual(
                    self._growth(root, INITIAL_PRIVATE_FILES[label]), [],
                    f"{label} grew during tests: a test or probe left gitignored private evidence",
                )

    def test_required_private_and_tracked_roots_are_protected(self):
        """Deleting a tracked output root from the pack predicate must turn this control red."""
        for label in ("provider_samples", "state/us_short", "docs", "presets", "schemas", "research"):
            with self.subTest(root=label):
                self.assertEqual(PROTECTED_PRIVATE_ROOTS.get(label), ROOT / label)

    def test_growth_predicate_dies_in_a_temporary_root(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            residue = root / "raw" / "receipt.json"
            residue.parent.mkdir()
            residue.write_text("{}", encoding="utf-8")
            self.assertEqual(self._growth(root, frozenset()), ["raw/receipt.json"])


class LiveTransportLifecycleConformance(unittest.TestCase):
    """One-shot tickets preserve normal-runner lifecycle correctness, not provenance."""

    LANES = {"web": ("tavily", "deepseek"), "x": ("xai",)}

    def test_ticket_registry_holds_objects_and_is_revoked_after_runner_error(self):
        for lane, providers in self.LANES.items():
            with self.subTest(lane=lane):
                ticket = paid_gateway.issue_ticket()
                registry = paid_gateway._CAPABILITY_TICKETS
                self.assertIn(ticket, registry, f"{lane}: registry must keep the ticket object")
                paid_gateway.revoke_ticket(ticket)
                self.assertNotIn(ticket, registry, f"{lane}: unconsumed ticket must be revoked")

    def test_ticket_is_one_shot_and_foreign_objects_are_refused(self):
        for lane, providers in self.LANES.items():
            with self.subTest(lane=lane):
                transport = paid_gateway.new_transport(*providers)
                self.assertFalse(transport._consume_ticket(object()))
                ticket = paid_gateway.issue_ticket()
                self.assertTrue(transport._consume_ticket(ticket))
                self.assertFalse(transport._consume_ticket(ticket))


if __name__ == "__main__":
    unittest.main()
