"""B0 acceptance tests for the US-short test-root inventory and narrow static guard."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from collections import Counter
import json
import unittest

from tests.provider import us_short_test_io_inventory as inventory
from tests.provider.us_short_test_io_inventory import build_inventory, _accesses
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
EXPLICIT_UNRESOLVED_ALLOWLIST = frozenset(_BASELINE["unresolved_allowlist"])
EXPECTED_ALLOWLIST_COUNTS = {
    key: int(value) for key, value in _BASELINE["protected_write_finding_counts"].items()
}
RESIDUAL_WRITE_DISPOSITIONS = {
    "negative_input": frozenset({
        "tests/provider/test_us_short_batch5_bankruptcy_8k_source_packet.py:kwarg:packet_ref:state/us_short",
        "tests/provider/test_us_short_batch5_bankruptcy_8k_source_packet.py:kwarg:screen_path:state/us_short",
        "tests/provider/test_us_short_batch5_bankruptcy_8k_source_packet.py:kwarg:summary_path:provider_samples",
        "tests/provider/test_us_short_batch5_live_source_packet.py:kwarg:raw_sample_ref:provider_samples",
        "tests/provider/test_us_short_batch5_theme_source_packet.py:kwarg:raw_sample_ref:provider_samples",
    }),
    "static_overcount": frozenset({
        "tests/provider/test_us_short_batch5_incident_log_writer.py:TemporaryDirectory:state/us_short",
        "tests/provider/test_us_short_batch5_incident_log_writer.py:kwarg:incident_root:state/us_short",
        "tests/provider/test_us_short_batch5_incident_log_writer.py:mkdir:state/us_short",
        "tests/provider/test_us_short_batch5_incident_log_writer.py:write_text:state/us_short",
        "tests/provider/test_us_short_llm_theme_discovery_fetch_x_merge.py:mkdir:provider_samples,state/us_short",
        "tests/provider/test_us_short_llm_theme_discovery_fetch_x_merge.py:rename:provider_samples,state/us_short",
        "tests/provider/test_us_short_llm_theme_discovery_fetch_x_merge.py:unlink:provider_samples,state/us_short",
        "tests/provider/test_us_short_llm_theme_discovery_fetch_x_merge.py:write_bytes:provider_samples,state/us_short",
        "tests/provider/test_us_short_llm_theme_discovery_fetch_x_merge.py:write_text:provider_samples,state/us_short",
        "tests/provider/test_us_short_offline_production_entry_guard.py:write_text:provider_samples,state/us_short",
        "tests/provider/test_us_short_soft_discovery_query_quality_probe_assess.py:kwarg:row:provider_samples,state/us_short",
        "tests/provider/test_us_short_batch5_capstone_offline_e2e.py:kwarg:source_packet_path:provider_samples,state/us_short",
        "tests/provider/test_us_short_weekly_capstone.py:mkdir:state/us_short",
        "tests/provider/test_us_short_weekly_capstone.py:write_text:state/us_short",
        "tests/test_us_short_capstone_checkpoint.py:kwarg:input_logical_paths:state/us_short",
        "tests/test_us_short_capstone_checkpoint.py:kwarg:output_logical_paths:state/us_short",
        "tests/test_us_short_corporate_action_workflow.py:kwarg:lifecycle_observation:provider_samples,state/us_short",
        "tests/test_us_short_discovery_conformance.py:kwarg:resolved:provider_samples,state/us_short",
        "tests/test_us_short_forward_policy_outcome.py:kwarg:adjustment_evidence:provider_samples,state/us_short",
        "tests/test_us_short_forward_policy_private_week.py:kwarg:private_output_path:state/us_short",
        "tests/test_us_short_result_linkage_cut3.py:kwarg:selection_input_provenance:provider_samples,state/us_short",
        "tests/test_us_short_weekend_batch4_runner.py:write_text:provider_samples,state/us_short",
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
        first = self._inventory
        second = self._inventory
        self.assertEqual(first, second)
        self.assertEqual(first["module_count"], 279)
        self.assertEqual(
            first["classification_counts"],
            {
                "class0_no_direct_protected_io": 254,
                "class1_read_real_root": 8,
                "class2_write_real_root": 15,
                "class3_global_sentinel": 2,
                "class4_unresolved_write": 0,
            },
        )
        self.assertEqual(first["unallowlisted_write_findings"], [])
        observed_unresolved = frozenset(first["unresolved_write_finding_counts"])
        self.assertEqual(observed_unresolved, EXPLICIT_UNRESOLVED_ALLOWLIST)
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
