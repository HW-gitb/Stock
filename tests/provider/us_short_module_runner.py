"""Run the US-short unittest lane with a per-module private-root residue guard."""
from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROTECTED_ROOTS = {
    "provider_samples": ROOT / "provider_samples",
    "state/us_short": ROOT / "state" / "us_short",
}


def snapshot_protected_entries(
    roots: dict[str, Path] = PROTECTED_ROOTS,
) -> frozenset[tuple[str, str, str]]:
    """Return stable per-root entry identities, including directories and files."""
    entries: set[tuple[str, str, str]] = set()
    for label, root in roots.items():
        root = root.resolve()
        if not root.is_dir():
            continue
        for entry in root.rglob("*"):
            try:
                relative = entry.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            kind = "dir" if entry.is_dir() else "file" if entry.is_file() else "other"
            entries.add((label, kind, relative))
    return frozenset(entries)


class _ResidueFailure(unittest.TestCase):
    def __init__(self, module: str, entries: tuple[tuple[str, str, str], ...]) -> None:
        super().__init__("runTest")
        self.module = module
        self.entries = entries

    def id(self) -> str:
        return f"{self.module}.test_private_root_residue"

    def shortDescription(self) -> str:
        return "per-module protected-root residue guard"

    def runTest(self) -> None:
        self.fail(
            "new protected-root entries survived module "
            f"{self.module}: {list(self.entries)!r}"
        )


class GuardedModuleSuite(unittest.TestSuite):
    def __init__(self, module: str, tests: unittest.TestSuite) -> None:
        super().__init__(tests)
        self.module = module

    def run(self, result: unittest.TestResult, debug: bool = False):
        before = snapshot_protected_entries()
        super().run(result, debug=debug)
        after = snapshot_protected_entries()
        growth = tuple(sorted(after - before))
        if growth and not result.shouldStop:
            residue = _ResidueFailure(self.module, growth)
            result.startTest(residue)
            try:
                result.addFailure(residue, (AssertionError, AssertionError(residue.id()), None))
            finally:
                result.stopTest(residue)
        return result


def module_names() -> tuple[str, ...]:
    return tuple(
        path.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")
        for path in sorted(
            (ROOT / "tests").rglob("test_us_short*.py"),
            key=lambda candidate: candidate.relative_to(ROOT).as_posix(),
        )
        if path.is_file()
    )


def build_suite(loader: unittest.TestLoader | None = None) -> unittest.TestSuite:
    loader = loader or unittest.defaultTestLoader
    return unittest.TestSuite(
        GuardedModuleSuite(module, loader.loadTestsFromName(module))
        for module in module_names()
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-b", "--buffer", action="store_true")
    parser.add_argument("-f", "--failfast", action="store_true")
    parser.add_argument("--durations", type=int, default=0)
    options = parser.parse_args(argv)
    runner = unittest.TextTestRunner(
        verbosity=1,
        buffer=options.buffer,
        failfast=options.failfast,
    )
    result = runner.run(build_suite())
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
