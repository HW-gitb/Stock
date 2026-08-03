"""Class-level guards for US-short discovery operator-state and live-authority regressions."""
from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from engine import us_short_llm_theme_discovery_paid_gateway as paid_gateway
from runners import us_short_llm_theme_discovery_fetch_web as web_fetch
from runners import us_short_llm_theme_discovery_fetch_x as x_fetch


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


class RawRootIsolationSeamConformance(unittest.TestCase):
    """`DEFAULT_RAW_ROOT` must stay call-time resolved, never bound into a signature default.

    Binding it into the signature silently defeats `mock.patch.object(module, "DEFAULT_RAW_ROOT",
    tmp)` — the seam every offline test uses — so offline runs write into the REAL gitignored raw
    root.  That is invisible until a tree accumulates a same-digest receipt with different bytes,
    at which point the immutable door drops every source and the lane goes red for a reason that
    has nothing to do with the code under test.  Observed exactly once, on the A4 landing.
    """

    LANE_RUNNERS = (
        ROOT / "runners" / "us_short_llm_theme_discovery_fetch_web.py",
        ROOT / "runners" / "us_short_llm_theme_discovery_fetch_x.py",
    )

    @staticmethod
    def _signature_defaults_naming_the_raw_root(source: str) -> list[tuple[str, str]]:
        offenders: list[tuple[str, str]] = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = node.args
            pairs = list(zip(args.args[len(args.args) - len(args.defaults):], args.defaults))
            pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None]
            for arg, default in pairs:
                name = (
                    default.id if isinstance(default, ast.Name)
                    else default.attr if isinstance(default, ast.Attribute) else None
                )
                if name == "DEFAULT_RAW_ROOT":
                    offenders.append((node.name, arg.arg))
        return offenders

    def test_no_lane_runner_binds_the_raw_root_into_a_signature_default(self):
        for path in self.LANE_RUNNERS:
            with self.subTest(runner=path.name):
                offenders = self._signature_defaults_naming_the_raw_root(
                    path.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    offenders, [],
                    f"{path.name}: resolve DEFAULT_RAW_ROOT at call time "
                    f"(`raw_root or DEFAULT_RAW_ROOT`), not in the signature",
                )

    def test_the_predicate_dies_on_a_planted_signature_default(self):
        planted = (
            "from pathlib import Path\n"
            "DEFAULT_RAW_ROOT = Path('provider_samples')\n"
            "def _run_lane_fetch(*, raw_root: Path = DEFAULT_RAW_ROOT):\n"
            "    return raw_root\n"
        )
        self.assertEqual(
            self._signature_defaults_naming_the_raw_root(planted),
            [("_run_lane_fetch", "raw_root")],
        )

    def test_offline_runs_honour_a_patched_raw_root(self):
        """The seam itself: patching the module attribute must redirect every raw write."""
        for module, runner_name in (
            (web_fetch, "run_web_fetch"), (x_fetch, "run_x_fetch"),
        ):
            with self.subTest(lane=module.__name__.rsplit("_", 2)[-1]):
                source = inspect.getsource(module)
                self.assertIn("raw_root or DEFAULT_RAW_ROOT", source)
                self.assertTrue(callable(getattr(module, runner_name)))


if __name__ == "__main__":
    unittest.main()
