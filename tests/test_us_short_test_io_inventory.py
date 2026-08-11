"""B2 acceptance tests for the US-short test-root inventory and narrow static guard."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from collections import Counter
import json
import unittest

from tests.provider import us_short_test_io_inventory as inventory
from tests.provider.us_short_test_io_inventory import (
    GLOBAL_SIDE_EFFECT_SENTINEL_REASONS,
    GLOBAL_SIDE_EFFECT_SENTINELS,
    _accesses,
    build_inventory,
)
from tests.provider.us_short_private_test_root import temporary_us_short_state_directory


ROOT = Path(__file__).resolve().parents[1]

# The checked-in snapshot stores stable (module, operation, roots) keys plus per-key counts.  The
# class-4 list is an explicit reviewed disposition, not a permission for new unresolved writes:
# an added same-operation write still turns this acceptance red.
_BASELINE = json.loads(
    (ROOT / "docs" / "us_short_test_io_inventory_20260801.json").read_text(encoding="utf-8")
)
EXPLICIT_TEMPORARY_ALLOWLIST = frozenset(_BASELINE["allowlist"])
EXPLICIT_UNRESOLVED_ALLOWLIST = frozenset(_BASELINE["unresolved_allowlist"])
EXPECTED_ALLOWLIST_COUNTS = {
    key: int(value) for key, value in _BASELINE["protected_write_finding_counts"].items()
}
RESIDUAL_WRITE_DISPOSITIONS = {
    "negative_or_contract_fixture": frozenset({
        "tests/provider/test_us_short_batch5_bankruptcy_8k_source_packet.py:kwarg:packet_ref:state/us_short",
        "tests/provider/test_us_short_batch5_bankruptcy_8k_source_packet.py:kwarg:screen_path:state/us_short",
        "tests/provider/test_us_short_batch5_live_source_packet.py:kwarg:raw_sample_ref:provider_samples",
        "tests/provider/test_us_short_batch5_theme_source_packet.py:kwarg:raw_sample_ref:provider_samples",
        "tests/schema/test_us_short_soft_discovery_query_quality_probe_packet_schema.py:kwarg:state_dir:state/us_short",
    }),
    "carrier_root_contract_fixture": frozenset({
        "tests/provider/test_us_short_weekly_capstone.py:kwarg:account_state_path:state/us_short",
        "tests/provider/test_us_short_weekly_capstone.py:kwarg:batch4_template_path:state/us_short",
        "tests/provider/test_us_short_weekly_capstone.py:kwarg:private_root:state/us_short",
        "tests/test_us_short_model_paper_capstone_wiring.py:kwarg:official_output_root:state/us_short",
        "tests/test_us_short_model_paper_capstone_wiring.py:kwarg:private_root:state/us_short",
    }),
    "static_contract_write": frozenset({
        "tests/provider/test_us_short_batch5_incident_log_writer.py:TemporaryDirectory:provider_samples,state/us_short",
        "tests/provider/test_us_short_batch5_incident_log_writer.py:kwarg:incident_root:provider_samples,state/us_short",
        "tests/provider/test_us_short_batch5_incident_log_writer.py:mkdir:provider_samples,state/us_short",
        "tests/provider/test_us_short_batch5_incident_log_writer.py:write_text:provider_samples,state/us_short",
        "tests/test_us_short_capstone_checkpoint.py:kwarg:input_logical_paths:state/us_short",
        "tests/test_us_short_capstone_checkpoint.py:kwarg:output_logical_paths:state/us_short",
        "tests/test_us_short_forward_policy_private_week.py:kwarg:private_output_path:state/us_short",
        "tests/provider/test_us_short_llm_theme_discovery_fetch_web.py:kwarg:artifact_path:state/us_short",
        "tests/provider/test_us_short_llm_theme_discovery_fetch_x_merge.py:kwarg:artifact_path:state/us_short",
        "tests/test_us_short_llm_theme_discovery_plan_budget.py:kwarg:artifact_path:state/us_short",
    }),
}


class USShortTestIOInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._inventory = build_inventory(
            ROOT,
            allowlist=EXPLICIT_TEMPORARY_ALLOWLIST,
            unresolved_allowlist=EXPLICIT_UNRESOLVED_ALLOWLIST,
        )
        cls._snapshot = inventory.snapshot_from_inventory(cls._inventory)

    def test_b0_inventory_is_reproducible_and_allowlist_is_exact(self):
        # Determinism is proved by re-scanning real modules below.  Comparing the one cached
        # inventory with itself would read like a reproducibility check and could never fail.
        first = self._inventory
        for relative in (
            "tests/provider/test_us_short_batch5_bankruptcy_8k_probe.py",
            "tests/provider/test_us_short_batch5_status_source_probe.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertEqual(_accesses(source, relative), _accesses(source, relative))
        self.assertEqual(first["module_count"], _BASELINE["module_count"])
        self.assertEqual(first["classification_counts"], _BASELINE["classification_counts"])
        self.assertEqual(first["unallowlisted_write_findings"], [])
        sentinel_modules = {
            module["module"]
            for module in first["modules"]
            if module["classification"] == "class3_global_sentinel"
        }
        self.assertEqual(sentinel_modules, set(GLOBAL_SIDE_EFFECT_SENTINELS))
        self.assertEqual(sentinel_modules, set(GLOBAL_SIDE_EFFECT_SENTINEL_REASONS))
        self.assertTrue(all(GLOBAL_SIDE_EFFECT_SENTINEL_REASONS[name] for name in sentinel_modules))
        observed_unresolved = frozenset(first["unresolved_write_finding_counts"])
        self.assertEqual(observed_unresolved, EXPLICIT_UNRESOLVED_ALLOWLIST)
        observed = Counter(
            access["key"]
            for module in first["modules"]
            for access in module["accesses"]
            if access["mode"] != "read" and not access["unresolved"]
        )
        self.assertEqual(observed, Counter(EXPECTED_ALLOWLIST_COUNTS))
        observed_unresolved_counts = Counter(
            f"{access['key']}:class4_unresolved_write"
            for module in first["modules"]
            for access in module["accesses"]
            if access["mode"] != "read" and access["unresolved"]
        )
        self.assertEqual(observed_unresolved_counts, Counter(
            first["unresolved_write_finding_counts"]
        ))
        for key in EXPLICIT_TEMPORARY_ALLOWLIST:
            module, rest = key.split(":", 1)
            operation, roots = rest.rsplit(":", 1)
            self.assertTrue(module.endswith(".py"))
            self.assertFalse(operation.split(":", 1)[0].isdigit())
            self.assertIn(roots, {"provider_samples", "state/us_short", "provider_samples,state/us_short"})

    def test_residual_write_findings_have_explicit_class_disposition(self):
        self.assertEqual(
            set(EXPLICIT_TEMPORARY_ALLOWLIST),
            set().union(*RESIDUAL_WRITE_DISPOSITIONS.values()),
        )
        self.assertTrue(
            all(not (left & right)
                for index, left in enumerate(RESIDUAL_WRITE_DISPOSITIONS.values())
                for right in list(RESIDUAL_WRITE_DISPOSITIONS.values())[index + 1:])
        )

    def test_checked_in_inventory_snapshot_matches_current_source(self):
        expected = self._snapshot
        snapshot = json.loads(
            (ROOT / "docs" / "us_short_test_io_inventory_20260801.json").read_text(encoding="utf-8")
        )
        snapshot_modules = {row["module"]: row for row in snapshot.get("modules", [])}
        expected_modules = {row["module"]: row for row in expected.get("modules", [])}
        module_diffs = sorted(
            name
            for name in set(snapshot_modules) | set(expected_modules)
            if snapshot_modules.get(name) != expected_modules.get(name)
        )
        top_level_diffs = sorted(
            key for key in set(snapshot) | set(expected)
            if snapshot.get(key) != expected.get(key)
        )
        # A legitimate future compact-snapshot shape may replace the module table; if so, update
        # this diagnostic with that schema.  Until then, a stale count must name its owner rather
        # than hiding behind unittest's truncated whole-document diff.
        self.assertEqual(
            snapshot,
            expected,
            f"inventory snapshot drift modules={module_diffs} top_level={top_level_diffs}",
        )

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

    def test_local_write_helper_is_scanned_by_class(self):
        source = '''
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state" / "us_short"
def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
def planted():
    _write_json(STATE_DIR / "bad.json", {})
'''
        findings = [
            access for access in _accesses(source, "tests/planted_test_us_short.py")
            if access.mode != "read"
        ]
        self.assertIn(("helper:_write_json", ("state/us_short",)), {
            (access.operation, access.roots) for access in findings
        })

    def test_imported_write_helper_hint_is_scanned_by_class(self):
        source = '''
from pathlib import Path
from tests.provider.test_us_short_batch5_data_context import _write_json
ROOT = Path(__file__).resolve().parents[1]
def planted():
    _write_json(ROOT / "provider_samples" / "bad.json", {})
'''
        findings = [
            access for access in _accesses(source, "tests/planted_test_us_short.py")
            if access.mode != "read"
        ]
        self.assertIn(("helper:_write_json", ("provider_samples",)), {
            (access.operation, access.roots) for access in findings
        })

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

    def test_unresolved_tempdir_parent_is_a_visible_class4_write(self):
        source = (
            '''
import tempfile
from runners import us_short_llm_theme_discovery_fetch_web as fetch
tempfile.TemporaryDirectory(dir=fetch.
''' + "STATE_DIR" + '''
)
tempfile.mkdtemp(dir=fetch.
''' + "STATE_DIR" + '''
)
tempfile.NamedTemporaryFile(dir=fetch.
''' + "STATE_DIR" + '''
)
def planted(parent):
    tempfile.TemporaryDirectory(dir=parent)
'''
        )
        findings = [
            access for access in _accesses(source, "tests/planted_test_us_short.py")
            if access.mode != "read"
        ]
        self.assertEqual(len(findings), 4)
        self.assertTrue(all(access.unresolved for access in findings))
        self.assertEqual(
            {(access.operation, access.roots, access.unresolved) for access in findings},
            {
                ("TemporaryDirectory", ("provider_samples", "state/us_short"), True),
                ("mkdtemp", ("provider_samples", "state/us_short"), True),
                ("NamedTemporaryFile", ("provider_samples", "state/us_short"), True),
            },
        )

    def test_unresolved_path_shapes_are_visible_class4_writes(self):
        source = '''
from pathlib import Path
import os
ROOT = Path(__file__).resolve().parents[1]
def planted():
    open(os.path.join(str(ROOT), "provider_samples", "join.json"), "w")
    open("%s/provider_samples/mod.json" % ROOT, "w")
    open("{}/provider_samples/format.json".format(ROOT), "w")
    open(Path(str(ROOT), "provider_samples", "path.json"), "w")
'''
        findings = [
            access for access in _accesses(source, "tests/planted_test_us_short.py")
            if access.mode != "read"
        ]
        self.assertEqual(len(findings), 4)
        self.assertTrue(all(access.unresolved for access in findings))

    def test_known_repo_root_tempdir_is_not_unresolved(self):
        source = (
            '''
import tempfile
from runners import us_short_batch5_provider_live_probe as probe
tempfile.TemporaryDirectory(dir=probe.
''' + "ROOT" + ''')
'''
        )
        self.assertEqual(_accesses(source, "tests/planted_test_us_short.py"), ())

    def test_local_write_helper_tracks_derived_path_alias(self):
        source = '''
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def _write_json(path, payload):
    target = path / "nested.json"
    target.write_text("{}")
def planted():
    _write_json(ROOT / "state" / "us_short", {})
'''
        findings = [
            access for access in _accesses(source, "tests/planted_test_us_short.py")
            if access.mode != "read"
        ]
        self.assertIn(("helper:_write_json", ("state/us_short",)), {
            (access.operation, access.roots) for access in findings
        })

    def test_dict_path_container_is_not_a_static_guard_escape(self):
        source = '''
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
paths = {"state": ROOT / "state" / "us_short" / "bad.json"}
def planted():
    paths["state"].write_text("{}")
'''
        findings = [
            access for access in _accesses(source, "tests/planted_test_us_short.py")
            if access.mode != "read"
        ]
        self.assertEqual(len(findings), 1)
        self.assertFalse(findings[0].unresolved)
        self.assertEqual(findings[0].roots, ("state/us_short",))

    def test_list_path_container_is_not_a_static_guard_escape(self):
        source = '''
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
paths = [ROOT / "provider_samples" / "bad.json"]
def planted():
    paths[0].write_text("{}")
'''
        findings = [
            access for access in _accesses(source, "tests/planted_test_us_short.py")
            if access.mode != "read"
        ]
        self.assertEqual(len(findings), 1)
        self.assertFalse(findings[0].unresolved)
        self.assertEqual(findings[0].roots, ("provider_samples",))

    def test_unknown_write_path_is_visible_as_unresolved_class4(self):
        source = '''
def planted(path):
    path.write_text("{}")
'''
        findings = [
            access for access in _accesses(source, "tests/planted_test_us_short.py")
            if access.mode != "read"
        ]
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].unresolved)
        self.assertEqual(findings[0].roots, ("provider_samples", "state/us_short"))

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
        self.assertEqual(len(findings), 2)
        self.assertEqual(
            {(access.roots, access.unresolved) for access in findings},
            {
                (("provider_samples", "state/us_short"), True),
                (("state/us_short",), False),
            },
        )

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
