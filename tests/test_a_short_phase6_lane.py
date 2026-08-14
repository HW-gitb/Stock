"""Attach the phase6 suite to the a_short full lane.

The lane is selected by one filename pattern (`test_a_short*.py`), but every
module under `tests/phase6` belongs to A-short without carrying that prefix, so
the lane never ran any of them: a "full" a_short pack was silently missing 19
modules.  That is not theoretical -- two of those modules sat red for weeks
(`R-ASHORT-P1-4-*` review, `O-P14-1`/`O-P14-2`) while every lane run reported
green, and a default-value change to `safe_api` broke two more assertions that
the lane could not see.

`load_tests` is the one hook that lets a file the pattern DOES match pull in
files it does not, without renaming 19 modules whose names are quoted all over
the handoffs, and without teaching the ledger a second selector.  Discovery
still attributes every case to its own real module, so the parallel runner keeps
dispatching them separately and the count gate keeps comparing like with like.
"""
from __future__ import annotations

import unittest
from pathlib import Path

PHASE6_DIR = Path(__file__).resolve().parent / "phase6"
PHASE6_PATTERN = "test_*.py"


def _discover(loader: unittest.TestLoader) -> unittest.TestSuite:
    """Discover phase6 under the SAME top level the outer discovery resolved.

    A different top level would name the same file as a different module, and
    the worker that later imports that name would import a different module
    object than the serial run does.
    """
    top_level = getattr(loader, "_top_level_dir", None) or str(PHASE6_DIR.parent)
    return loader.discover(str(PHASE6_DIR), pattern=PHASE6_PATTERN, top_level_dir=top_level)


def load_tests(loader, standard_tests, pattern):
    """Expand only while the lane is being DISCOVERED, never when run by name.

    unittest passes the discovery pattern here and `None` when this module is
    loaded directly.  The parallel runner dispatches every discovered module by
    name, and this module is one of them, so expanding in both places would run
    the whole phase6 suite twice -- which is exactly what the lane's count gate
    reported the first time (`discovered=3093 ran=3338`).
    """
    if pattern is None:
        return standard_tests
    standard_tests.addTests(_discover(loader))
    return standard_tests


class Phase6LaneAttachmentTest(unittest.TestCase):
    """Guard the attachment itself, so a silent detach cannot look like a green lane."""

    def test_phase6_modules_are_reachable_from_the_lane(self) -> None:
        loader = unittest.TestLoader()
        loader._top_level_dir = str(PHASE6_DIR.parents[1])
        suite = _discover(loader)
        self.assertEqual(loader.errors, [], "phase6 discovery raised import errors")
        modules = {type(case).__module__ for case in _flatten(suite)}
        on_disk = {path.stem for path in PHASE6_DIR.glob(PHASE6_PATTERN)}
        self.assertTrue(on_disk, "phase6 holds no test modules; the pattern is wrong")
        reached = {name.rsplit(".", 1)[-1] for name in modules}
        self.assertEqual(on_disk - reached, set(), "phase6 modules the lane cannot reach")


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


if __name__ == "__main__":
    unittest.main()
