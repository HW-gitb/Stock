"""Runtime-authority guards for A-short screening configuration."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from engine.a_short_runtime_config import RuntimeConfigError, load_runtime_configuration


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "a_short_screening_threshold_governance.schema.json"
ARTIFACT_PATH = ROOT / "presets" / "a_short_screening_threshold_governance_20260602.json"
M67_ARTIFACT_PATH = ROOT / "presets" / "a_short_m67_runtime_policy_20260715.json"
EGS_MAIN_PATH = ROOT / "A-EGS" / "egs_main.py"


class AShortScreeningRuntimePolicyTests(unittest.TestCase):
    def _artifact(self) -> dict:
        return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

    def _temporary_root(self, mutate=None):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        preset_dir = root / "presets"
        preset_dir.mkdir()
        screening = self._artifact()
        m67 = json.loads(M67_ARTIFACT_PATH.read_text(encoding="utf-8"))
        if mutate:
            mutate(screening, m67)
        (preset_dir / ARTIFACT_PATH.name).write_text(json.dumps(screening, ensure_ascii=False), encoding="utf-8")
        (preset_dir / M67_ARTIFACT_PATH.name).write_text(json.dumps(m67, ensure_ascii=False), encoding="utf-8")
        (preset_dir / "a_short.yaml").write_text(
            "screening_threshold_governance:\n"
            "  schema_ref: schemas/a_short_screening_threshold_governance.schema.json\n"
            f"  artifact_ref: presets/{ARTIFACT_PATH.name}\n"
            "  status: runtime_json_authority\n\n"
            "m67_runtime_policy:\n"
            "  schema_ref: schemas/a_short_m67_runtime_policy.schema.json\n"
            f"  artifact_ref: presets/{M67_ARTIFACT_PATH.name}\n"
            "  status: runtime_json_authority\n",
            encoding="utf-8",
        )
        return temp, root

    def test_schema_and_active_policy_are_runtime_authority(self) -> None:
        try:
            from jsonschema import Draft7Validator
        except ModuleNotFoundError as exc:
            raise unittest.SkipTest("jsonschema is not installed in this interpreter") from exc
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        self.assertEqual(list(Draft7Validator(schema).iter_errors(self._artifact())), [])
        loaded = load_runtime_configuration()
        self.assertEqual(loaded["screening"], self._artifact()["thresholds"])
        self.assertEqual(len(loaded["lineage"]["policies"]), 2)

    def test_temp_json_change_is_loaded_and_egs_has_no_threshold_fallback(self) -> None:
        temp, root = self._temporary_root(
            lambda screening, _m67: screening["thresholds"].__setitem__("final_n", 3)
        )
        with temp:
            self.assertEqual(load_runtime_configuration(root=root)["screening"]["final_n"], 3)
        source = EGS_MAIN_PATH.read_text(encoding="utf-8")
        self.assertIn("**_SCREENING_THRESHOLDS", source)
        self.assertIn('CONF["final_n"]', source)
        self.assertNotIn('CONF.get("final_n"', source)

    def test_invalid_policy_fails_closed_before_any_runner_can_start(self) -> None:
        cases = {
            "missing": lambda screening, _m67: screening["thresholds"].pop("final_n"),
            "extra": lambda screening, _m67: screening["thresholds"].__setitem__("future_n", 1),
            "bool": lambda screening, _m67: screening["thresholds"].__setitem__("watch_n", True),
            "nan": lambda screening, _m67: screening["thresholds"].__setitem__("watch_n", float("nan")),
            "bad_order": lambda screening, _m67: screening["thresholds"].update({"final_n": 51, "watch_n": 15}),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                temp, root = self._temporary_root(mutate)
                with temp, self.assertRaises(RuntimeConfigError):
                    load_runtime_configuration(root=root)

    def test_policy_metadata_or_route_tamper_fails_closed(self) -> None:
        temp, root = self._temporary_root(
            lambda screening, _m67: screening.__setitem__("runtime_authority", False)
        )
        with temp, self.assertRaises(RuntimeConfigError):
            load_runtime_configuration(root=root)

        temp, root = self._temporary_root()
        with temp:
            preset = root / "presets" / "a_short.yaml"
            preset.write_text(preset.read_text(encoding="utf-8").replace(
                "runtime_json_authority", "mirror_only", 1), encoding="utf-8")
            with self.assertRaises(RuntimeConfigError):
                load_runtime_configuration(root=root)


if __name__ == "__main__":
    unittest.main()
