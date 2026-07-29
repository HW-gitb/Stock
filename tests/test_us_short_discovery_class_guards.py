"""Class-level guards for US-short discovery operator-state and live-authority regressions."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch


ROOT = Path(__file__).resolve().parent.parent
OPERATOR_STATE_DIR = ROOT / "state" / "us_short"
INITIAL_OPERATOR_FILES = frozenset(
    path.relative_to(OPERATOR_STATE_DIR).as_posix()
    for path in OPERATOR_STATE_DIR.rglob("*") if path.is_file()
)


class LaneResidueConformance(unittest.TestCase):
    """Tests/probes may not grow operator state; pre-existing authorized state is not an error."""

    @staticmethod
    def _growth(root: Path, baseline: frozenset[str]) -> list[str]:
        return sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*") if path.is_file()
            and path.relative_to(root).as_posix() not in baseline
        )

    def test_operator_state_does_not_grow_during_the_pack(self):
        self.assertEqual(
            self._growth(OPERATOR_STATE_DIR, INITIAL_OPERATOR_FILES), [],
            "state/us_short grew during tests: a test or probe wrote gitignored operator state",
        )

    def test_growth_predicate_dies_in_a_temporary_root(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "residue.json").write_text("{}", encoding="utf-8")
            self.assertEqual(self._growth(root, frozenset()), ["residue.json"])


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
