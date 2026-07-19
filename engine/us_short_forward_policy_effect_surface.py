# -*- coding: utf-8 -*-
"""Content-address the A1 comparison selection/outcome effect surface.

The comparison epoch is derived from the complete static Python import closure
of the selection-to-H10 path plus its directly consumed presets.  Python is
normalised as an AST without comments, source locations, or docstrings; JSON
is canonicalised.  A cosmetic edit therefore cannot throw away a forward
epoch, while a selection/outcome dependency omitted from the contract fails
closed during validation.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "presets" / "us_short_forward_policy_effect_surface_20260718.json"
SCHEMA_PATH = ROOT / "schemas" / "us_short_forward_policy_effect_surface.schema.json"
_EFFECT_ROOTS = (
    "engine/us_short_forward_policy_heads.py",
    "engine/us_short_weekend_pipeline.py",
    "engine/us_short_forward_policy_shadow_stage.py",
    "engine/us_short_forward_policy_order_snapshot.py",
    "engine/us_short_weekend_analysis.py",
    "engine/us_short_forward_policy_outcome.py",
)
_CONTROL_PRESETS = (
    "presets/us_short_forward_policy_grid_20260711.json",
    "presets/us_short_forward_policy_comparison_execution_20260717.json",
)
_NON_EFFECT_TRANSITIVE_PATHS = frozenset({
    "engine/us_short_forward_policy_effect_surface.py",
    "engine/us_short_forward_policy_shadow_stage.py",
    "engine/us_short_forward_policy_statistical_plan.py",
    "engine/us_short_private_paths.py",
    "engine/us_short_selection_exclusions.py",
    "engine/us_short_hot_excluded.py",
})


class ForwardPolicyEffectSurfaceError(ValueError):
    """The frozen A1 effect-surface manifest is missing, malformed, or drifted."""


class _StripLeadingDocstrings(ast.NodeTransformer):
    @staticmethod
    def _strip(node: ast.AST) -> ast.AST:
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            node.body = body[1:]
        return node

    def visit_Module(self, node: ast.Module) -> ast.AST:
        return self.generic_visit(self._strip(node))

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        return self.generic_visit(self._strip(node))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self.generic_visit(self._strip(node))

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self.generic_visit(self._strip(node))


def _load_json(path: Path, *, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ForwardPolicyEffectSurfaceError(f"cannot load {label}") from exc
    if type(value) is not dict:
        raise ForwardPolicyEffectSurfaceError(f"{label} must be an object")
    return value


def _engine_path_from_module(module: str | None) -> str | None:
    if not isinstance(module, str) or not module.startswith("engine.us_short_"):
        return None
    relative_path = f"engine/{module.rsplit('.', 1)[-1]}.py"
    if not (ROOT / relative_path).is_file():
        raise ForwardPolicyEffectSurfaceError(f"selection/outcome import has no source file: {module}")
    return relative_path


def _python_tree(relative_path: str) -> ast.AST:
    try:
        return ast.parse((ROOT / relative_path).read_text(encoding="utf-8"), filename=relative_path)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise ForwardPolicyEffectSurfaceError(f"cannot parse effect-surface Python: {relative_path}") from exc


def selection_and_outcome_engine_closure() -> tuple[str, ...]:
    """Return the static ``engine.us_short_*`` import closure from A1 roots."""
    pending, discovered = list(_EFFECT_ROOTS), set()
    while pending:
        relative_path = pending.pop()
        if relative_path in discovered:
            continue
        discovered.add(relative_path)
        for node in ast.walk(_python_tree(relative_path)):
            modules = [node.module] if isinstance(node, ast.ImportFrom) else []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                imported = _engine_path_from_module(module)
                if imported is not None and imported not in discovered:
                    pending.append(imported)
    return tuple(sorted(discovered - _NON_EFFECT_TRANSITIVE_PATHS))


def _preset_dependencies(relative_path: str) -> set[str]:
    """Find runtime preset paths from assignments in one closure module."""
    result: set[str] = set()
    for node in ast.walk(_python_tree(relative_path)):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        strings = {
            value.value for value in ast.walk(node.value)
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        }
        for value in strings:
            if value.startswith("presets/") and value.endswith(".json"):
                result.add(value)
            elif value.startswith("us_short_") and value.endswith(".json") and "presets" in strings:
                result.add(f"presets/{value}")
    return result


def required_effect_surface_paths() -> tuple[str, ...]:
    """Return the non-self-referential A1 source/configuration dependency closure."""
    engines = selection_and_outcome_engine_closure()
    presets = set(_CONTROL_PRESETS)
    for relative_path in engines:
        presets.update(_preset_dependencies(relative_path))
    required = set(engines) | presets
    if any(not (ROOT / relative_path).is_file() for relative_path in required):
        raise ForwardPolicyEffectSurfaceError("effect-surface dependency is missing from the repository")
    return tuple(sorted(required))


def semantic_component_sha256(relative_path: str, payload: bytes) -> str:
    """Hash Python semantics or JSON semantics, never source formatting."""
    try:
        if relative_path.endswith(".py"):
            tree = ast.parse(payload.decode("utf-8"), filename=relative_path)
            tree = _StripLeadingDocstrings().visit(tree)
            normalized = ast.dump(ast.fix_missing_locations(tree), annotate_fields=True, include_attributes=False)
        elif relative_path.endswith(".json"):
            normalized = json.dumps(
                json.loads(payload.decode("utf-8")), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
            )
        else:
            raise ForwardPolicyEffectSurfaceError(f"unsupported effect-surface file type: {relative_path}")
    except (UnicodeDecodeError, SyntaxError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ForwardPolicyEffectSurfaceError(f"cannot normalise effect-surface path: {relative_path}") from exc
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def validate_effect_surface_contract(contract: object) -> dict:
    if type(contract) is not dict:
        raise ForwardPolicyEffectSurfaceError("effect-surface contract must be an exact dict")
    schema = _load_json(SCHEMA_PATH, label="effect-surface schema")
    try:
        jsonschema.validate(contract, schema)
    except jsonschema.ValidationError as exc:
        raise ForwardPolicyEffectSurfaceError(f"effect-surface schema rejected: {exc.message}") from exc
    if tuple(contract["paths"]) != required_effect_surface_paths():
        raise ForwardPolicyEffectSurfaceError("effect-surface path closure drifted")
    return contract


def load_effect_surface_contract() -> dict:
    return validate_effect_surface_contract(_load_json(CONTRACT_PATH, label="effect-surface contract"))


def effect_surface_components() -> dict[str, str]:
    """Return the semantic digest for every required effect-surface dependency."""
    contract = load_effect_surface_contract()
    components: dict[str, str] = {}
    for relative_path in contract["paths"]:
        try:
            payload = (ROOT / relative_path).read_bytes()
        except OSError as exc:
            raise ForwardPolicyEffectSurfaceError(f"cannot read effect-surface path: {relative_path}") from exc
        components[relative_path] = semantic_component_sha256(relative_path, payload)
    return components


def baseline_epoch_sha256() -> str:
    """Return the canonical current A1 baseline epoch digest."""
    components = effect_surface_components()
    canonical = "".join(f"{path}:{components[path]}\n" for path in sorted(components))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
