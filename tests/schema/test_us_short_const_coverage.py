# -*- coding: utf-8 -*-
"""Whole-class const-coverage guard for EVERY US-short batch-1 governance/contract schema
(F-1 fix from the 2026-06-21 batch-1 review).

Problem: the per-object negative-guard fixes (ship_gate safety booleans / exclusion hot_excluded /
field_registry loops) did NOT generalize. Governed const members across ~12 schemas had no guard
against schema-WEAKENING: if someone deleted a `"const": ...` from a schema (leaving a bare typed
field), every existing test stayed green — the positive tests read the PRESET (not the schema) and
each schema's `test_schema_const_equals_preset` only checked a hand-picked subset.

Fix (root, whole-class, lightweight, auto-covers future schemas): a centralized guard over EVERY
us_short preset+schema pair that
  (1) compares the schema's CURRENT set of const-bearing paths (top-level + nested objects) to a
      golden per-schema COUNT — deleting a const drops the count and FAILS here (a const added/removed
      intentionally requires a one-line golden update), and
  (2) for every current const path, asserts schema-const == preset value AND that a drift is rejected
      by jsonschema (proves the const actually enforces).
This deals only with real `const` paths, so it does not false-positive on legitimate non-const
constraints (e.g. scoring_profile.core_score_components = items.enum set-of-3) or free fields
(notes / status / reminder_threshold / banner element `ref`). Array-tuple const members (e.g. the
weekly_report banner element ids/tags) are covered by that schema's own dedicated tests.
"""
import copy
import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRESETS = ROOT / "presets"
SCHEMAS = ROOT / "schemas"

# Golden per-schema count of const-bearing paths (top-level scalars/arrays + nested-object members).
# Generated from the reviewed batch-1 schemas. A drop = a const was weakened/removed; a rise = a const
# was added — either way update this number deliberately (that is the whole point of the gate).
EXPECTED_CONST_PATH_COUNT = {
    "us_short_action_governance": 13,
    "us_short_action_table_contract": 20,
    "us_short_cash_allocation_governance": 10,
    # 14 -> 13: the per-stage rewrite retired the `covers_passes` const, which pinned exactly two
    # passes; there are now three stages. The promise it froze is carried by the public schema
    # (`stage_counts` required, all three keys) and by a behaviour assertion on real output.
    "us_short_exclusion_summary_governance": 13,
    "us_short_field_registry_governance": 13,
    "us_short_hard_veto_governance": 8,
    "us_short_lifecycle_calibration_governance": 9,
    "us_short_macro_cluster_governance": 15,
    "us_short_portfolio_guard_governance": 13,
    "us_short_regime_governance": 31,
    "us_short_scoring_profile_governance": 7,
    "us_short_ship_gate_sizing_governance": 8,
    "us_short_sizing_stack_governance": 9,
    "us_short_symbol_cooldown_governance": 9,
    "us_short_theme_lifecycle_governance": 11,
    # 12 -> 15: K4C pinned §4c and class-E pinned optional banners ⑧/⑨.
    "us_short_weekly_report_contract": 15,
}


def _load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _const_paths(props, path=()):
    """All const-bearing dotted paths: top-level + recursively into inline-`properties` objects."""
    for k, sub in (props or {}).items():
        if not isinstance(sub, dict):
            continue
        if "const" in sub:
            yield path + (k,)
        elif sub.get("type") == "object" and isinstance(sub.get("properties"), dict):
            yield from _const_paths(sub["properties"], path + (k,))


def _nav(obj, path):
    for p in path:
        obj = obj[p]
    return obj


def _drift(cv):
    if isinstance(cv, bool):
        return not cv
    if isinstance(cv, (int, float)):
        return cv + 1
    if isinstance(cv, str):
        return cv + "__DRIFT__"
    if isinstance(cv, list):
        return cv[:-1] if len(cv) > 0 else ["__X__"]
    if isinstance(cv, dict):
        return {**cv, "__drift__": 1}
    return "__DRIFT__"


def _pairs():
    out = []
    for pp in sorted(PRESETS.glob("us_short_*_20260620.json")):
        preset = _load(pp)
        name = preset.get("schema_name")
        if not name:
            continue
        sp = SCHEMAS / f"{name}.schema.json"
        if sp.exists():
            out.append((name, _load(sp), preset))
    return out


class UsShortConstCoverage(unittest.TestCase):
    def test_pairs_discovered(self):
        names = {n for n, _, _ in _pairs()}
        self.assertGreaterEqual(len(names), 16, "glob found too few us_short schema/preset pairs")
        # every discovered governance/contract schema must have a golden count (no schema escapes the gate)
        self.assertEqual(names, set(EXPECTED_CONST_PATH_COUNT),
                         "a us_short schema is missing from / extra in the golden const-count table")

    def test_const_path_count_matches_golden(self):
        # deleting a const drops the count -> FAIL here (this is the schema-weakening catch)
        for name, schema, _ in _pairs():
            n = len(list(_const_paths(schema.get("properties", {}))))
            self.assertEqual(
                n, EXPECTED_CONST_PATH_COUNT[name],
                f"{name}: const-path count {n} != golden {EXPECTED_CONST_PATH_COUNT[name]} "
                f"(a const was added/removed — if intentional, update EXPECTED_CONST_PATH_COUNT)",
            )

    def test_every_const_matches_preset_and_drift_rejected(self):
        total = 0
        for name, schema, preset in _pairs():
            for path in _const_paths(schema.get("properties", {})):
                cv = _const_at(schema["properties"], path)
                self.assertEqual(_nav(preset, path), cv, f"{name}:{'.'.join(path)} preset != schema const")
                bad = copy.deepcopy(preset)
                parent = _nav(bad, path[:-1]) if len(path) > 1 else bad
                parent[path[-1]] = _drift(cv)
                with self.assertRaises(jsonschema.ValidationError,
                                       msg=f"{name}:{'.'.join(path)} schema does not reject a drift"):
                    jsonschema.validate(bad, schema)
                total += 1
        self.assertGreaterEqual(total, 180, f"too few consts checked ({total})")


def _const_at(props, path):
    node = props
    for p in path[:-1]:
        node = node[p]["properties"]
    return node[path[-1]]["const"]


if __name__ == "__main__":
    unittest.main()
