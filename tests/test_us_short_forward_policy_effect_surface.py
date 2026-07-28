"""Contract tests for the A1 comparison-track effect-surface epoch."""
from __future__ import annotations

import hashlib
import unittest
from copy import deepcopy

from engine import us_short_forward_policy_effect_surface as effect_surface
from engine.us_short_forward_policy_effect_surface import (
    ForwardPolicyEffectSurfaceError,
    baseline_epoch_sha256,
    effect_surface_components,
    load_effect_surface_contract,
    required_effect_surface_paths,
    semantic_component_sha256,
    validate_effect_surface_contract,
)


class USShortForwardPolicyEffectSurfaceTests(unittest.TestCase):
    def test_declared_effect_surface_matches_the_static_selection_outcome_closure(self) -> None:
        contract = load_effect_surface_contract()
        components = effect_surface_components()

        self.assertEqual(tuple(contract["paths"]), required_effect_surface_paths())
        self.assertEqual(set(contract["paths"]), set(components))
        for required_path in (
            "engine/us_short_dynamic_seats.py",
            "engine/us_short_theme_selection.py",
            "engine/us_short_theme_lifecycle.py",
            "engine/us_short_hard_veto.py",
            "engine/us_short_canonical_asof.py",
            "engine/us_short_price_engine.py",
            "presets/us_short_scoring_profile_governance_20260620.json",
            "presets/us_short_theme_probe_governance_20260622.json",
            "presets/us_short_theme_lifecycle_governance_20260620.json",
        ):
            self.assertIn(required_path, contract["paths"])
        self.assertTrue(all(len(value) == 64 for value in components.values()))
        self.assertEqual(len(baseline_epoch_sha256()), 64)

        expected = hashlib.sha256(
            "".join(f"{path}:{components[path]}\n" for path in sorted(components)).encode("utf-8")
        ).hexdigest()
        self.assertEqual(baseline_epoch_sha256(), expected)

        omitted = deepcopy(contract)
        omitted["paths"].remove("engine/us_short_dynamic_seats.py")
        with self.assertRaises(ForwardPolicyEffectSurfaceError):
            validate_effect_surface_contract(omitted)

    def test_semantic_digests_ignore_python_comments_docstrings_and_json_formatting(self) -> None:
        self.assertEqual(
            semantic_component_sha256("engine/example.py", b'"""old docstring"""\nvalue = 1\n'),
            semantic_component_sha256("engine/example.py", b'"""new docstring"""\nvalue = 1\n# comment\n'),
        )
        self.assertEqual(
            semantic_component_sha256("presets/example.json", b'{"a":1,"b":[2]}'),
            semantic_component_sha256("presets/example.json", b'{\n  "b": [2],\n  "a": 1\n}'),
        )

    def test_effect_surface_memos_key_on_current_source_bytes_and_preserve_epoch(self) -> None:
        effect_surface._engine_imports_from_source.cache_clear()
        effect_surface._preset_dependencies_from_source.cache_clear()
        effect_surface.semantic_component_sha256.cache_clear()
        first = baseline_epoch_sha256()
        first_infos = (
            effect_surface._engine_imports_from_source.cache_info(),
            effect_surface._preset_dependencies_from_source.cache_info(),
            effect_surface.semantic_component_sha256.cache_info(),
        )
        self.assertEqual(baseline_epoch_sha256(), first)
        for before, after in zip(first_infos, (
            effect_surface._engine_imports_from_source.cache_info(),
            effect_surface._preset_dependencies_from_source.cache_info(),
            effect_surface.semantic_component_sha256.cache_info(),
        )):
            self.assertGreater(after.hits, before.hits)
            self.assertLess(after.currsize, after.maxsize)
        original = b"VALUE = 1\n"
        changed = b"VALUE = 2\n"
        self.assertNotEqual(
            semantic_component_sha256("engine/example.py", original),
            semantic_component_sha256("engine/example.py", changed),
        )
        self.assertEqual(
            effect_surface._engine_imports_from_source("engine/example.py", "import engine.us_short_alpha\n"),
            ("engine.us_short_alpha",),
        )
        self.assertEqual(
            effect_surface._engine_imports_from_source("engine/example.py", "import engine.us_short_beta\n"),
            ("engine.us_short_beta",),
        )
        self.assertEqual(
            effect_surface._preset_dependencies_from_source("engine/example.py", "PRESET = 'presets/one.json'\n"),
            frozenset({"presets/one.json"}),
        )
        self.assertEqual(
            effect_surface._preset_dependencies_from_source("engine/example.py", "PRESET = 'presets/two.json'\n"),
            frozenset({"presets/two.json"}),
        )


if __name__ == "__main__":
    unittest.main()
