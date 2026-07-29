"""Class-level guards for US-short discovery operator-state and live-authority regressions."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch


ROOT = Path(__file__).resolve().parent.parent
PROTECTED_PRIVATE_ROOTS = {
    "state/us_short": ROOT / "state" / "us_short",
    "provider_samples": ROOT / "provider_samples",
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

    def test_provider_samples_is_a_protected_root(self):
        """Deleting the raw-evidence root from the pack predicate must turn this control red."""
        self.assertEqual(PROTECTED_PRIVATE_ROOTS.get("provider_samples"), ROOT / "provider_samples")

    def test_growth_predicate_dies_in_a_temporary_root(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            residue = root / "raw" / "receipt.json"
            residue.parent.mkdir()
            residue.write_text("{}", encoding="utf-8")
            self.assertEqual(self._growth(root, frozenset()), ["raw/receipt.json"])


class LiveTransportLifecycleConformance(unittest.TestCase):
    """One-shot tickets preserve normal-runner lifecycle correctness, not provenance."""

    LANES = {"web": (web, "run_web_fetch"), "x": (xfetch, "run_x_fetch")}
    @staticmethod
    def _closure(function):
        return dict(zip(function.__code__.co_freevars, (
            cell.cell_contents for cell in function.__closure__ or ()
        )))

    def test_ticket_registry_holds_objects_and_is_revoked_after_runner_error(self):
        for lane, (module, runner_name) in self.LANES.items():
            with self.subTest(lane=lane):
                cells = self._closure(getattr(module, runner_name))
                issue = cells["issue_ticket"]
                registry = self._closure(issue)["issued_tickets"]
                ticket = issue()
                self.assertIn(ticket, registry, f"{lane}: registry must keep the ticket object")
                cells["revoke_ticket"](ticket)
                self.assertNotIn(ticket, registry, f"{lane}: unconsumed ticket must be revoked")

    def test_ticket_is_one_shot_and_foreign_objects_are_refused(self):
        for lane, (module, runner_name) in self.LANES.items():
            with self.subTest(lane=lane):
                cells = self._closure(getattr(module, runner_name))
                transport = cells["new_transport"]()
                self.assertFalse(transport._consume_ticket(object()))
                ticket = cells["issue_ticket"]()
                self.assertTrue(transport._consume_ticket(ticket))
                self.assertFalse(transport._consume_ticket(ticket))


if __name__ == "__main__":
    unittest.main()
