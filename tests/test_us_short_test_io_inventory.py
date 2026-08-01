"""B0 acceptance tests for the US-short test-root inventory and narrow static guard."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from collections import Counter
import json
import unittest

from tests.provider import us_short_test_io_inventory as inventory
from tests.provider.us_short_test_io_inventory import build_inventory, build_snapshot, _accesses
from tests.provider.us_short_private_test_root import temporary_us_short_state_directory


ROOT = Path(__file__).resolve().parents[1]

# B0 is an audit baseline, not permission for future writes.  B1/B2 remove entries as the
# corresponding modules move behind the shared temporary-root helper.  The checked-in snapshot
# stores stable (module, operation, roots) keys plus per-key counts, so unrelated line edits do not
# rewrite the allowlist while an added same-operation write still turns the count check red.
_BASELINE = json.loads(
    (ROOT / "docs" / "us_short_test_io_inventory_20260801.json").read_text(encoding="utf-8")
)
EXPLICIT_TEMPORARY_ALLOWLIST = frozenset(_BASELINE["allowlist"])
EXPECTED_ALLOWLIST_COUNTS = {
    key: int(value) for key, value in _BASELINE["protected_write_finding_counts"].items()
}


class USShortTestIOInventoryTests(unittest.TestCase):
    def test_b0_inventory_is_reproducible_and_allowlist_is_exact(self):
        first = build_inventory(ROOT, allowlist=EXPLICIT_TEMPORARY_ALLOWLIST)
        second = build_inventory(ROOT, allowlist=EXPLICIT_TEMPORARY_ALLOWLIST)
        self.assertEqual(first, second)
        self.assertEqual(first["module_count"], 279)
        self.assertEqual(
            first["classification_counts"],
            {
                "class0_no_direct_protected_io": 233,
                "class1_read_real_root": 8,
                "class2_write_real_root": 36,
                "class3_global_sentinel": 2,
            },
        )
        self.assertEqual(first["unallowlisted_write_findings"], [])
        observed = Counter(
            access["key"]
            for module in first["modules"]
            for access in module["accesses"]
            if access["mode"] != "read"
        )
        self.assertEqual(observed, Counter(EXPECTED_ALLOWLIST_COUNTS))
        for key in EXPLICIT_TEMPORARY_ALLOWLIST:
            module, rest = key.split(":", 1)
            operation, roots = rest.rsplit(":", 1)
            self.assertTrue(module.endswith(".py"))
            self.assertFalse(operation.split(":", 1)[0].isdigit())
            self.assertIn(roots, {"provider_samples", "state/us_short", "provider_samples,state/us_short"})

    def test_checked_in_inventory_snapshot_matches_current_source(self):
        expected = build_snapshot(ROOT, allowlist=EXPLICIT_TEMPORARY_ALLOWLIST)
        snapshot = json.loads(
            (ROOT / "docs" / "us_short_test_io_inventory_20260801.json").read_text(encoding="utf-8")
        )
        self.assertEqual(snapshot, expected)

    def test_planted_protected_write_is_not_silently_safe(self):
        source = '''
import os
import shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def _root():
    return ROOT / "provider_samples"
class Case:
    def setUp(self):
        self.raw_root = _root()
        runner(raw_root=self.raw_root)
        os.makedirs(self.raw_root, exist_ok=True)
        os.remove(self.raw_root / "bad.json")
        shutil.rmtree(self.raw_root, ignore_errors=True)
'''
        findings = [access for access in _accesses(source, "tests/planted_test_us_short.py")
                    if access.mode == "write"]
        self.assertEqual(
            {(access.operation, access.roots) for access in findings},
            {
                ("kwarg:raw_root", ("provider_samples",)),
                ("os.makedirs", ("provider_samples",)),
                ("os.remove", ("provider_samples",)),
                ("shutil.rmtree", ("provider_samples",)),
            },
        )

    def test_dynamic_open_mode_is_fail_closed(self):
        source = '''
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state" / "us_short"
def planted(mode):
    return (STATE_DIR / "bad.json").open(mode=mode)
'''
        findings = [access for access in _accesses(source, "tests/planted_test_us_short.py")
                    if access.mode != "read"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].mode, "unknown")

    def test_nonsemantic_alias_names_are_not_a_blind_spot(self):
        source = '''
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def planted():
    base = ROOT / "provider_samples" / "base"
    base.mkdir(parents=True, exist_ok=True)
    d = ROOT / "provider_samples" / "d"
    d.mkdir(parents=True, exist_ok=True)
    p = ROOT / "state" / "us_short" / "p.json"
    p.write_text("{}", encoding="utf-8")
    class Holder:
        def write(self):
            self.workspace = ROOT / "state" / "us_short" / "workspace"
            self.workspace.mkdir(parents=True, exist_ok=True)
'''
        findings = [access for access in _accesses(source, "tests/planted_test_us_short.py")
                    if access.mode != "read"]
        self.assertEqual(
            sum(access.operation == "mkdir" and access.roots == ("provider_samples",)
                for access in findings),
            2,
        )
        self.assertEqual(
            {(access.operation, access.roots) for access in findings},
            {
                ("mkdir", ("provider_samples",)),
                ("mkdir", ("state/us_short",)),
                ("write_text", ("state/us_short",)),
            },
        )

    def test_shared_helper_path_is_outside_static_guard_model(self):
        source = '''
from pathlib import Path
from tests.provider.us_short_private_test_root import temporary_us_short_state_directory
ROOT = Path(__file__).resolve().parents[1]
def planted_positive():
    with temporary_us_short_state_directory(ROOT) as temp_root:
        (Path(temp_root) / "ok.json").write_text("{}", encoding="utf-8")
'''
        self.assertEqual(_accesses(source, "tests/test_us_short_helper_positive.py"), ())
        original = inventory.TEMPORARY_ROOT_HELPERS
        try:
            inventory.TEMPORARY_ROOT_HELPERS = frozenset()
            findings = [
                access
                for access in _accesses(source, "tests/test_us_short_helper_positive.py")
                if access.mode != "read"
            ]
        finally:
            inventory.TEMPORARY_ROOT_HELPERS = original
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].roots, ("provider_samples", "state/us_short"))

    def test_repo_anchor_is_required_but_direct_relative_root_is_supported(self):
        source = '''
from pathlib import Path
def planted(tempdir):
    (Path(tempdir) / "state" / "us_short" / "bad.json").write_text("{}")
    (Path("state") / "us_short" / "bad.json").write_text("{}")
'''
        findings = [access for access in _accesses(source, "tests/planted_test_us_short.py")
                    if access.mode != "read"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].roots, ("state/us_short",))

    def test_shared_state_helper_cleans_its_owned_fake_root(self):
        with TemporaryDirectory() as temp_repo:
            repo_root = Path(temp_repo)
            with temporary_us_short_state_directory(repo_root) as temp_root:
                output = Path(temp_root) / "receipt.json"
                output.write_text("{}", encoding="utf-8")
                self.assertTrue(output.is_file())
            self.assertFalse(Path(temp_root).exists())


if __name__ == "__main__":
    unittest.main()
