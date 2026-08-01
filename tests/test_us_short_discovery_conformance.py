# -*- coding: utf-8 -*-
"""Executable conformance pack for the US-short soft-discovery lane.

Why this file exists: every recurrence in this lane had ONE shape — a policy applied at
N-1 of N call sites.  Immutability lived in one of three writers (K3-R43), the credential
check in three of five sinks (K3-R44), the date-keyed slot in the writers but not the
readers (K3-R45), the format checker in six of seven validators (K3-R48), the identity
canonicalizer in six of seven identity sites (K3-R41), the per-item boundary at the top
level but not the member level (K3-R42), a dying test at four of five armings (K3-R47).
Reviewing harder cannot fix that: a reviewer can only enumerate the sites that exist today.
So each row below ENUMERATES its sites from the code and asserts the policy at every one.

Two rules learned from an adversarial pass over this pack itself:
  * the ENUMERATOR must be DERIVED, never hand-listed — a hand-listed surface reproduces the
    very N-1-of-N defect inside the checker (a new lane file was invisible to every row);
  * a row must be provably able to fail — each carries planted-failure controls, and the guard
    registry proves its own evidence (the named test must exist, run exactly one case, pass
    unmutated and fail mutated), because a renamed or deleted test otherwise reads as coverage.

Residual scope, stated rather than implied: the rows cover the derived lane surface (the
discovery/provisional-theme family plus anything importing its shared modules).  A module
outside that family that bypasses the shared door entirely is beyond this pack; the
repository-wide US-short boundary scan is what covers cross-market imports there.
"""
from __future__ import annotations

from contextlib import contextmanager
import ast
import copy
from functools import lru_cache
import importlib
import inspect
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHARED_MODULES = (
    "runners/us_short_discovery_publish_policy.py",
    "engine/us_short_persisted_text_safety.py",
    "engine/us_short_schema_formats.py",
)
WRITE_DOOR = "runners/us_short_discovery_publish_policy.py"
LANE_NAME_MARKERS = ("llm_theme_discovery", "provisional_theme", "discovery_publish_policy",
                     "persisted_text_safety", "schema_formats")
EFFECT_FLAGS = (
    "scoring_eligible", "top15_effect_enabled", "operation_advice_effect_enabled",
    "dynamic_seats_enabled", "theme_probe_enabled", "lifecycle_actions_enabled",
)
# Batch-level raises that are DECLARED system-boundary failures rather than untrusted-item
# rejections: query validation before any fetch, the receipt secret backstop, raw-storage
# integrity.  Pinned per (file, message) so a new raise cannot inherit the exemption by
# copying one of these strings into another module.
DECLARED_BATCH_RAISES = {
    ("runners/us_short_llm_theme_discovery_fetch_web.py", "query is empty or secret-like"),
    ("runners/us_short_llm_theme_discovery_fetch_web.py",
     "receipt carries a credential-bearing locator; refusing to persist"),
    ("runners/us_short_llm_theme_discovery_fetch_web.py", "raw receipt path must be gitignored before writing"),
    ("runners/us_short_llm_theme_discovery_fetch_web.py", "live source is missing a gitignored raw receipt"),
    ("runners/us_short_llm_theme_discovery_fetch_x.py", "query is empty or secret-like"),
    ("runners/us_short_llm_theme_discovery_fetch_x.py", "raw receipt path must be gitignored before writing"),
}
FS_MUTATING_NAMES = frozenset({
    "write_text", "write_bytes", "unlink", "rmdir", "symlink_to", "hardlink_to", "touch",
    "remove", "truncate", "fdopen", "mkstemp", "mkdtemp", "copy", "copy2", "copyfile",
    "copytree", "move", "rmtree", "dump", "NamedTemporaryFile", "TemporaryFile",
})
# `.lower()` is legitimate URL/theme-key canonicalization; only UPPER-folding can forge an
# ASCII ticker out of a Unicode lookalike, which is the K3-R41 mechanism.
CASE_FOLDING_FORBIDDEN = frozenset({"upper", "casefold", "title", "swapcase"})
CASE_FOLDING_NAMES = CASE_FOLDING_FORBIDDEN | {"lower"}
IDENTITY_FOLD_ALLOWED_FUNCTIONS = frozenset({"_canonical_industry_code", "canonical_industry_code"})
LOOKALIKE_TICKERS = ("\u0131BM", "\u017fAPL", "\u212aAPL", "\uff21APL", "AAPL\u00a0",
                     "600519", "BAD TICKER")
RETIRED_SLOT_NAMES = frozenset({
    "us_short_llm_theme_discovery.json",
    "us_short_provisional_theme_validation.json",
    "candidate_universe_20260706.json",
})


@lru_cache(maxsize=None)
def _source(rel: str) -> str:
    """Read an immutable repository source once per conformance process."""
    return (ROOT / rel).read_text(encoding="utf-8")


def _tree(text: str) -> ast.AST:
    return ast.parse(text)


def derived_lane_files() -> tuple[str, ...]:
    """The lane surface, derived from the repository instead of hand-listed."""
    candidates = sorted(
        {path.relative_to(ROOT).as_posix() for path in (ROOT / "engine").glob("us_short_*.py")}
        | {path.relative_to(ROOT).as_posix() for path in (ROOT / "runners").glob("*us_short*.py")}
    )
    shared_stems = tuple(Path(rel).stem for rel in SHARED_MODULES)
    lane = set(SHARED_MODULES)
    for rel in candidates:
        text = _source(rel)
        if any(marker in rel for marker in LANE_NAME_MARKERS) or any(stem in text for stem in shared_stems):
            lane.add(rel)
    return tuple(sorted(lane))


def derived_lane_schemas() -> tuple[str, ...]:
    """Every schema the lane's own modules name."""
    schemas: set[str] = set()
    sources = [_source(rel) for rel in derived_lane_files()]
    for candidate in (ROOT / "schemas").glob("*.json"):
        if any(candidate.name in text for text in sources):
            schemas.add(candidate.relative_to(ROOT).as_posix())
    return tuple(sorted(schemas))


LANE_FILES = derived_lane_files()
MATRIX_FILES = tuple(sorted(set(LANE_FILES) | {"runners/us_short_weekly_capstone.py"}))
LANE_SCHEMAS = derived_lane_schemas()
# Test-owned expected contract.  The production registry is checked against this
# independent source; it is never used to manufacture the expected rows.
K4A_INDEPENDENT_STAGE_POLICY_REGISTRY = {
    "strict": ("required", "required"),
    "zero_effect": ("optional", "optional_result_only"),
}
K4A_LIFECYCLE_CALL_NAMES = frozenset({
    "inputs", "outputs", "run", "restore_stage", "_degrade_stage_boundary",
    "_unchanged_soft_discovery_receipt_matches", "record_stage",
    "_publish_current_output_transaction",
})
# `_build_pass2_budget_approval` is deliberately outside this optional-stage
# matrix: it is a mandatory strict approval seam, with its own Pass2 approval
# conformance pack and fail-closed contract.  It is not a zero-effect boundary.
# Schemas this lane WRITES (its own contracts) versus schemas it only reads from another lane.
LANE_OWNED_SCHEMAS = tuple(
    rel for rel in LANE_SCHEMAS
    if Path(rel).name.startswith(("us_short_llm_theme_discovery", "us_short_provisional_theme"))
)
PRODUCER_FILES = tuple(rel for rel in LANE_FILES if "_ProviderItemRejected" in _source(rel))


def _enclosing_functions(tree: ast.AST) -> dict[ast.AST, str]:
    """Map each node to its INNERMOST enclosing function (a nested helper is its own scope)."""
    owner: dict[ast.AST, str] = {}

    def descend(node: ast.AST, current: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else current
            owner[child] = name
            descend(child, name)

    descend(tree, "<module>")
    return owner


def _called_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def write_primitive_offenders(text: str) -> list[str]:
    """Every filesystem-mutating call, matched by SYMBOL NAME in either call form.

    Name-based matching is deliberate: `from os import replace`, `import json as j`,
    `shutil.move`, `os.fdopen` and `getattr(p, "write_text")()` all evaded a receiver-based rule.
    """
    offenders: list[str] = []
    for node in ast.walk(_tree(text)):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node.func)
        if name is None:
            continue
        if name in FS_MUTATING_NAMES:
            offenders.append(f"line {node.lineno}: {name}")
            continue
        if name in {"replace", "rename", "link"}:
            # A BARE `replace(...)`/`rename(...)`/`link(...)` can only be `from os import ...`;
            # `str.replace` is always an attribute call and always takes >= 2 arguments.
            receiver_is_os = isinstance(node.func, ast.Name) or (
                isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"os", "shutil"})
            # `str.replace` takes >= 2 arguments; the filesystem forms take one, and an
            # `os.`/`shutil.` receiver is always the filesystem form.
            if receiver_is_os or len(node.args) == 1:
                offenders.append(f"line {node.lineno}: {name}(filesystem)")
            continue
        if name == "open":
            literals = [arg.value for arg in node.args[1:] if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
            literals += [kw.value.value for kw in node.keywords
                         if kw.arg == "mode" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)]
            unknown_mode = any(kw.arg == "mode" and not isinstance(kw.value, ast.Constant) for kw in node.keywords)
            unknown_mode = unknown_mode or (len(node.args) > 1 and not isinstance(node.args[1], ast.Constant))
            if unknown_mode or any(flag in mode for mode in literals for flag in ("w", "x", "a", "+")):
                offenders.append(f"line {node.lineno}: open(write)")
            continue
        if name == "getattr" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            attribute = node.args[1].value
            if isinstance(attribute, str) and (attribute in FS_MUTATING_NAMES
                                               or attribute in {"replace", "rename", "link", "open"}):
                offenders.append(f"line {node.lineno}: getattr({attribute!r})")
    return offenders


def unarmed_validators(text: str) -> list[str]:
    """Every jsonschema validator in the lane must be built with the lane's own checker.

    The keyword's PRESENCE is not enough: `format_checker=None` disarms it completely.
    """
    offenders: list[str] = []
    for node in ast.walk(_tree(text)):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node.func)
        if name is None:
            continue
        if name in {"validate", "validator_for"} and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "jsonschema":
            offenders.append(f"line {node.lineno}: jsonschema.{name} bypasses the validator policy")
            continue
        if not name.endswith("Validator"):
            continue
        checker = next((kw.value for kw in node.keywords if kw.arg == "format_checker"), None)
        if checker is None:
            offenders.append(f"line {node.lineno}: {name} built without format_checker")
            continue
        armed = ((isinstance(checker, ast.Name) and checker.id == "FORMAT_CHECKER")
                 or (isinstance(checker, ast.Attribute) and checker.attr == "FORMAT_CHECKER"))
        if not armed:
            offenders.append(f"line {node.lineno}: {name} format_checker is not the lane's FORMAT_CHECKER")
    return offenders


def case_folding_offenders(text: str) -> list[str]:
    """Upper-case folding may only appear in an industry-code canonicalizer.

    K3-R41 was `_safe_text(raw_ticker).upper()`: folding BEFORE the repo's single identity
    canonicalizer saw the raw value, which let `ıBM` mint the real ticker `IBM`.
    """
    tree = _tree(text)
    owner = _enclosing_functions(tree)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node.func)
        folded: str | None = None
        if name in CASE_FOLDING_FORBIDDEN and isinstance(node.func, ast.Attribute):
            folded = name
        elif name == "getattr" and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) \
                and node.args[1].value in CASE_FOLDING_NAMES:
            folded = f"getattr({node.args[1].value!r})"
        elif name == "normalize" and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "unicodedata":
            folded = "unicodedata.normalize"
        if folded is None:
            continue
        if owner.get(node, "<module>") in IDENTITY_FOLD_ALLOWED_FUNCTIONS:
            continue
        offenders.append(f"line {node.lineno}: {folded} inside {owner.get(node, '<module>')}")
    return offenders


def batch_raise_offenders(text: str, rel: str = "<synthetic>") -> list[str]:
    """Inside any item loop, only `_ProviderItemRejected` may be raised (§五 red-line #4)."""
    offenders: list[str] = []
    for node in ast.walk(_tree(text)):
        if not isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Raise):
                continue
            if inner.exc is None:
                offenders.append(f"line {inner.lineno}: bare re-raise inside an item loop")
                continue
            raised = inner.exc.func if isinstance(inner.exc, ast.Call) else inner.exc
            name = _called_name(raised) or ""
            if "ProviderItemRejected" in name:
                continue
            first = inner.exc.args[0] if isinstance(inner.exc, ast.Call) and inner.exc.args else None
            message = ""
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                message = first.value
            elif isinstance(first, ast.JoinedStr):
                message = "".join(part.value for part in first.values if isinstance(part, ast.Constant))
            if (rel, message) in DECLARED_BATCH_RAISES:
                continue
            offenders.append(f"line {inner.lineno}: {name}({message[:48]!r})")
    return offenders


def loose_object_schemas(schema: Any, *, path: str = "$") -> list[str]:
    """Every object schema in the lane must be closed, or an unknown field rides along."""
    offenders: list[str] = []
    if isinstance(schema, dict):
        declared = schema.get("type")
        types = declared if isinstance(declared, list) else [declared]
        # `if`/`then`/`allOf` branches CONSTRAIN named properties without declaring an object,
        # so only a real declaration is required to be closed.
        in_conditional = any(marker in path for marker in (".if", ".then", ".else", ".allOf[",
                                                           ".anyOf[", ".oneOf["))
        declares_object = "object" in types or (
            not in_conditional and any(key in schema for key in ("properties", "patternProperties")))
        if declares_object and schema.get("additionalProperties") is not False:
            offenders.append(path)
        for key, value in schema.items():
            if key in {"properties", "definitions", "$defs", "patternProperties", "dependencies"} \
                    and isinstance(value, dict):
                for name, child in value.items():
                    offenders.extend(loose_object_schemas(child, path=f"{path}.{key}.{name}"))
            elif key in {"items", "not", "contains", "additionalItems", "propertyNames",
                         "unevaluatedProperties", "if", "then", "else"}:
                if isinstance(value, list):
                    for index, child in enumerate(value):
                        offenders.extend(loose_object_schemas(child, path=f"{path}.{key}[{index}]"))
                else:
                    offenders.extend(loose_object_schemas(value, path=f"{path}.{key}"))
            elif key in {"allOf", "anyOf", "oneOf"} and isinstance(value, list):
                for index, child in enumerate(value):
                    offenders.extend(loose_object_schemas(child, path=f"{path}.{key}[{index}]"))
    return offenders


def flag_pins(schema: Any) -> list[tuple[str, Any]]:
    """Effect-flag pins, accepting either `const: false` or a single-value `enum: [false]`."""
    found: list[tuple[str, Any]] = []
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key in EFFECT_FLAGS and isinstance(value, dict):
                if "const" in value:
                    found.append((key, value["const"]))
                elif isinstance(value.get("enum"), list) and len(value["enum"]) == 1:
                    found.append((key, value["enum"][0]))
                else:
                    found.append((key, None))
            elif isinstance(value, (dict, list)):
                found.extend(flag_pins(value))
    elif isinstance(schema, list):
        for item in schema:
            found.extend(flag_pins(item))
    return found


class LaneSurfaceConformance(unittest.TestCase):
    def test_repository_source_reads_are_cached_without_changing_source_bytes(self):
        rel = SHARED_MODULES[0]
        expected = (ROOT / rel).read_text(encoding="utf-8")
        self.assertEqual(_source(rel), expected)
        before = _source.cache_info()
        self.assertEqual(_source(rel), expected)
        after = _source.cache_info()
        self.assertEqual(after.hits, before.hits + 1)
        self.assertEqual(after.misses, before.misses)

    def test_read_only_schemas_stay_valid_json(self):
        for rel in LANE_SCHEMAS:
            with self.subTest(schema=rel):
                self.assertIsInstance(json.loads(_source(rel)), dict)

    def test_the_lane_surface_is_derived_not_hand_listed(self):
        self.assertEqual(LANE_FILES, derived_lane_files())
        self.assertEqual(LANE_SCHEMAS, derived_lane_schemas())
        for rel in SHARED_MODULES:
            self.assertIn(rel, LANE_FILES)
        self.assertGreaterEqual(len(LANE_FILES), 9)
        self.assertGreaterEqual(len(LANE_SCHEMAS), 5)
        self.assertGreaterEqual(len(PRODUCER_FILES), 2)

    def test_a_new_discovery_family_module_would_enter_the_surface(self):
        for planted in ("runners/us_short_llm_theme_discovery_fetch_reddit.py",
                        "engine/us_short_provisional_theme_confirm.py"):
            with self.subTest(planted=planted):
                self.assertTrue(any(marker in planted for marker in LANE_NAME_MARKERS))

    def test_producer_scope_is_derived_from_the_per_item_contract(self):
        self.assertEqual(set(PRODUCER_FILES),
                         {rel for rel in LANE_FILES if "_ProviderItemRejected" in _source(rel)})


class LaneWriteDoorConformance(unittest.TestCase):
    def test_only_the_publish_policy_module_touches_the_filesystem(self):
        for rel in LANE_FILES:
            with self.subTest(module=rel):
                offenders = write_primitive_offenders(_source(rel))
                if rel == WRITE_DOOR:
                    self.assertTrue(offenders, "the write door must be the module that writes")
                else:
                    self.assertEqual(offenders, [], f"{rel} writes outside the lane's single write door")

    def test_write_door_row_is_load_bearing(self):
        for planted in (
            "from pathlib import Path\n\n\ndef publish(p, s):\n    Path(p).write_text(s)\n",
            "def publish(p, s):\n    with open(p, 'w') as handle:\n        handle.write(s)\n",
            "def publish(p, s, mode):\n    with open(p, mode) as handle:\n        handle.write(s)\n",
            "import json\n\n\ndef publish(handle, payload):\n    json.dump(payload, handle)\n",
            "from json import dump\n\n\ndef publish(handle, payload):\n    dump(payload, handle)\n",
            "def publish(tmp, path):\n    tmp.replace(path)\n",
            "from os import replace\n\n\ndef publish(tmp, path):\n    replace(tmp, path)\n",
            "import shutil\n\n\ndef publish(a, b):\n    shutil.move(a, b)\n",
            "import os\n\n\ndef publish(path):\n    os.remove(path)\n",
            "import os\n\n\ndef publish(fd, data):\n    os.fdopen(fd, 'wb').write(data)\n",
            "def publish(path):\n    path.touch()\n",
            "def publish(p, s):\n    getattr(p, 'write_text')(s)\n",
            "from tempfile import NamedTemporaryFile\n\n\ndef publish(s):\n    NamedTemporaryFile(delete=False)\n",
        ):
            with self.subTest(planted=planted.splitlines()[-1].strip()[:44]):
                self.assertTrue(write_primitive_offenders(planted))
        for benign in ("x = 'a'.replace('a', 'b')\n", "y = text.replace(old, new)\n",
                       "with open(path) as handle:\n    data = handle.read()\n",
                       "with open(path, 'r', encoding='utf-8') as handle:\n    data = handle.read()\n"):
            with self.subTest(benign=benign.splitlines()[0].strip()[:44]):
                self.assertEqual(write_primitive_offenders(benign), [])


class LaneValidatorConformance(unittest.TestCase):
    def test_every_lane_validator_is_armed_with_the_format_checker(self):
        for rel in LANE_FILES:
            with self.subTest(module=rel):
                self.assertEqual(unarmed_validators(_source(rel)), [])

    def test_validator_row_is_load_bearing(self):
        for planted in (
            "def check(s, p):\n    return Draft7Validator(s).iter_errors(p)\n",
            "def check(s, p):\n    return Draft7Validator(s, format_checker=None).iter_errors(p)\n",
            "from jsonschema import FormatChecker\n\n\ndef check(s, p):\n"
            "    return Draft7Validator(s, format_checker=FormatChecker()).iter_errors(p)\n",
            "import jsonschema\n\n\ndef check(s, p):\n    return jsonschema.Draft7Validator(s).iter_errors(p)\n",
            "import jsonschema\n\n\ndef check(s, p):\n    return jsonschema.validate(p, s)\n",
            "import jsonschema\n\n\ndef check(s, p):\n    return jsonschema.validator_for(s)(s).iter_errors(p)\n",
        ):
            with self.subTest(planted=planted.splitlines()[-1].strip()[:44]):
                self.assertTrue(unarmed_validators(planted))
        armed = "def check(s, p):\n    return Draft7Validator(s, format_checker=FORMAT_CHECKER).iter_errors(p)\n"
        self.assertEqual(unarmed_validators(armed), [])

    def test_the_armed_checker_rejects_non_rfc3339_and_keeps_producer_shapes(self):
        from engine.us_short_schema_formats import FORMAT_CHECKER

        for bad in ("banana", "9999-99-99T99:99:99Z", "2026-07-24T10:00:00", "2026-07-24 10:00:00Z",
                    "2026-07-24\t10:00:00+00:00", "2026-07-24T10:00:00\x00Z", "2026-07-24T10:00:00+0000",
                    "2026-07-24T10:00:00+00:00:30", "2026-07-24T10:00:00,5+00:00", "2026-07-24t10:00:00z", "",
                    "2026-07-24T10:00:00." + "1" * 4000 + "Z"):
            with self.subTest(value=bad[:24]):
                self.assertFalse(FORMAT_CHECKER.conforms(bad, "date-time"))
        for good in ("2026-07-24T10:00:00Z", "2026-07-24T10:00:00+00:00", "2026-07-24T10:00:00-04:00",
                     "2026-07-24T10:00:00.123456+00:00", "2026-07-26T07:40:07.323647+00:00"):
            with self.subTest(value=good):
                self.assertTrue(FORMAT_CHECKER.conforms(good, "date-time"))

    def test_a_str_subclass_cannot_slip_past_the_format_check(self):
        from engine.us_short_schema_formats import FORMAT_CHECKER

        class Sneaky(str):
            pass

        self.assertFalse(FORMAT_CHECKER.conforms(Sneaky("banana"), "date-time"))
        self.assertTrue(FORMAT_CHECKER.conforms(Sneaky("2026-07-24T10:00:00Z"), "date-time"))


class LaneSlotConformance(unittest.TestCase):
    def test_every_reader_default_resolves_to_its_writer_slot(self):
        ingest = importlib.import_module("runners.us_short_llm_theme_discovery")
        validate = importlib.import_module("runners.us_short_provisional_theme_validate")
        universe = importlib.import_module("runners.us_short_universe_fetch")
        for date in ("20260727", "20260803", "20261231"):
            with self.subTest(decision_date=date):
                # Full resolved paths, not basenames: the same name in another directory is a
                # different slot.
                self.assertEqual(validate.default_discovery_path(date).resolve(),
                                 ingest.default_output_path(date).resolve())
                self.assertEqual(validate.default_candidate_path(date).resolve(),
                                 universe.default_candidate_path(date).resolve())

    def test_no_reader_default_computes_a_retired_slot_name(self):
        for module_name in (rel.replace("/", ".")[:-3] for rel in LANE_FILES):
            module = importlib.import_module(module_name)
            for attribute in dir(module):
                if not (attribute.startswith("default_") and attribute.endswith("_path")):
                    continue
                helper = getattr(module, attribute)
                if not callable(helper):
                    continue
                with self.subTest(helper=f"{module_name}.{attribute}"):
                    # Assert on the COMPUTED value: a retired name assembled by concatenation or
                    # an f-string would evade a source-text check.
                    self.assertNotIn(helper("20260727").name, RETIRED_SLOT_NAMES)


class LaneSchemaConformance(unittest.TestCase):
    def test_every_object_schema_in_the_lane_is_closed(self):
        self.assertGreaterEqual(len(LANE_OWNED_SCHEMAS), 5)
        for rel in LANE_OWNED_SCHEMAS:
            with self.subTest(schema=rel):
                self.assertEqual(loose_object_schemas(json.loads(_source(rel))), [])

    def test_schema_row_is_load_bearing(self):
        for planted in (
            {"type": "object", "properties": {"a": {"type": "string"}}},
            {"properties": {"a": {"type": "string"}}},
            {"type": ["object", "null"], "properties": {"a": {"type": "string"}}},
            {"type": "object", "additionalProperties": False,
             "properties": {"a": {"$defs": {"b": {"type": "object", "properties": {}}}}}},
            {"type": "object", "additionalProperties": False,
             "properties": {"a": {"contains": {"type": "object", "properties": {}}}}},
            {"type": "object", "additionalProperties": False,
             "properties": {"a": {"items": [{"type": "object", "properties": {}}]}}},
        ):
            with self.subTest(planted=json.dumps(planted)[:52]):
                self.assertTrue(loose_object_schemas(planted))
        self.assertEqual(loose_object_schemas(
            {"type": "object", "additionalProperties": False, "properties": {"a": {"type": "string"}}}), [])

    def test_every_effect_flag_in_the_lane_is_pinned_false(self):
        pinned_schemas = 0
        for rel in LANE_OWNED_SCHEMAS:
            pins = flag_pins(json.loads(_source(rel)))
            if not pins:
                continue
            pinned_schemas += 1
            for flag, constant in pins:
                with self.subTest(schema=rel, flag=flag):
                    self.assertIs(constant, False)
            # A contract schema must pin the WHOLE set, not a subset.
            with self.subTest(schema=rel, check="complete flag set"):
                self.assertGreaterEqual(len({flag for flag, _ in pins}), len(EFFECT_FLAGS))
        self.assertGreaterEqual(pinned_schemas, 3)

    def test_effect_flag_row_accepts_enum_pins_and_catches_true_or_unpinned(self):
        self.assertEqual(flag_pins({"scoring_eligible": {"enum": [False]}}), [("scoring_eligible", False)])
        self.assertEqual(flag_pins({"scoring_eligible": {"const": True}}), [("scoring_eligible", True)])
        self.assertEqual(flag_pins({"scoring_eligible": {"type": "boolean"}}), [("scoring_eligible", None)])


class LaneIdentityConformance(unittest.TestCase):
    def test_no_case_folding_precedes_the_identity_canonicalizer(self):
        for rel in LANE_FILES:
            with self.subTest(module=rel):
                self.assertEqual(case_folding_offenders(_source(rel)), [])

    def test_identity_row_is_load_bearing(self):
        for planted in (
            "def intake(item):\n    return safe_text(item['ticker']).upper()\n",
            "def intake(item):\n    return safe_text(item['ticker']).casefold()\n",
            "def intake(item):\n    return safe_text(item['ticker']).title()\n",
            "def intake(item):\n    return getattr(item['ticker'], 'upper')()\n",
            "import unicodedata\n\n\ndef intake(item):\n    return unicodedata.normalize('NFKC', item['ticker'])\n",
            "def _intake_industry_ticker(item):\n    return item['ticker'].upper()\n",
        ):
            with self.subTest(planted=planted.splitlines()[-1].strip()[:44]):
                self.assertTrue(case_folding_offenders(planted))
        self.assertEqual(case_folding_offenders(
            "def _canonical_industry_code(value):\n    return value.strip().upper()\n"), [])
        self.assertEqual(case_folding_offenders("def canon(u):\n    return u.scheme.lower()\n"), [])

    def test_every_intake_entrypoint_drops_lookalike_tickers_per_member(self):
        web = importlib.import_module("runners.us_short_llm_theme_discovery_fetch_web")
        xfetch = importlib.import_module("runners.us_short_llm_theme_discovery_fetch_x")
        row_web = {"url": "https://web.example/story", "title": "T", "content": "power",
                   "published_date": "2026-07-24T10:00:00Z"}
        row_x = {"url": "https://x.example/p/1", "title": "T", "text": "power",
                 "created_at": "2026-07-24T10:00:00Z"}
        for lane, builder, rows, ref in (
            ("web", web.build_web_fetch_packet, {"search_results": [row_web]},
             web._source_id(web._canonical_locator(row_web["url"]))),
            ("x", xfetch.build_x_fetch_packet, {"results": [row_x]},
             xfetch._source_id(web._canonical_locator(row_x["url"]))),
        ):
            for lookalike in LOOKALIKE_TICKERS:
                with self.subTest(lane=lane, ticker=lookalike.encode("unicode_escape").decode()):
                    reply = json.dumps({"themes": [{
                        "theme_id": "ai_boom", "display_name": "AI", "summary": "AI boom",
                        "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": [ref],
                        "members": [{"ticker": t, "source_ref_ids": [ref]}
                                    for t in ("AAPL", "MSFT", lookalike)]}]})
                    payload = dict(rows)
                    payload["llm_response" if lane == "web" else "grok_response"] = reply
                    artifact, receipt, _ = builder(
                        queries=["q"], expected_decision_date="20260725",
                        generated_at="2026-07-25T08:00:00Z", **payload)
                    kept = {member["ticker"] for theme in artifact["themes"] for member in theme["members"]}
                    self.assertEqual(kept, {"AAPL", "MSFT"})
                    self.assertTrue(receipt["drop_ledger"])


class LanePerItemConformance(unittest.TestCase):
    def test_no_undeclared_batch_level_raise_inside_an_item_loop(self):
        for rel in PRODUCER_FILES:
            with self.subTest(module=rel):
                self.assertEqual(batch_raise_offenders(_source(rel), rel), [])

    def test_per_item_row_is_load_bearing(self):
        for planted in (
            ("class E(ValueError):\n    pass\n\n\ndef intake(items):\n    for item in items:\n"
             "        if not item:\n            raise E('malformed item')\n"),
            ("class E(ValueError):\n    pass\n\n\ndef intake(items):\n    while items:\n"
             "        raise E('malformed item')\n"),
            ("def intake(items):\n    for item in items:\n        try:\n            parse(item)\n"
             "        except ValueError:\n            raise\n"),
            # A message copied from the declared allowlist must not inherit its exemption in
            # another file: the allowlist is pinned per (file, message).
            ("class E(ValueError):\n    pass\n\n\ndef intake(items):\n    for item in items:\n"
             "        raise E('query is empty or secret-like')\n"),
        ):
            with self.subTest(planted=planted.splitlines()[-1].strip()[:44]):
                self.assertTrue(batch_raise_offenders(planted, "runners/us_short_new_producer.py"))
        compliant = ("class _ProviderItemRejected(ValueError):\n    pass\n\n\ndef intake(items):\n"
                     "    for item in items:\n        raise _ProviderItemRejected('malformed', 'x')\n")
        self.assertEqual(batch_raise_offenders(compliant, "runners/us_short_new_producer.py"), [])


class LaneBoundaryCoverageConformance(unittest.TestCase):
    def test_the_repository_boundary_scan_covers_every_lane_module(self):
        boundary = importlib.import_module("tests.test_us_short_boundary_regression")
        scanned = {path.relative_to(ROOT).as_posix() for path in boundary.US_SHORT_CODE_FILES}
        self.assertEqual([rel for rel in LANE_FILES if rel not in scanned], [])


class K4bExecutableCoverage:
    """Repository-derived K4b entry/callsite axes; each structural assertion carries a planted red."""

    @staticmethod
    def _k4b_files() -> tuple[str, ...]:
        candidates = (
            list((ROOT / "engine").glob("us_short_*.py"))
            + list((ROOT / "runners").glob("us_short_*.py"))
        )
        return tuple(sorted(
            path.relative_to(ROOT).as_posix()
            for path in candidates
            if "theme_soft_boost" in path.read_text(encoding="utf-8")
            or "provisional_theme_boost" in path.read_text(encoding="utf-8")
        ))

    @staticmethod
    def _bool_consumers() -> set[str]:
        names: set[str] = set()
        for rel in K4bExecutableCoverage._k4b_files():
            for node in ast.walk(ast.parse(_source(rel))):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if any(arg.arg == "theme_soft_boost_enabled" for arg in (
                    *node.args.args, *node.args.kwonlyargs,
                )):
                    names.add(node.name)
        return names

    @classmethod
    def _bool_callsites(cls) -> list[tuple[str, str, ast.Call]]:
        targets = cls._bool_consumers()
        rows = []
        for rel in cls._k4b_files():
            tree = ast.parse(_source(rel))
            owners = _enclosing_functions(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _called_name(node.func) in targets:
                    rows.append((rel, owners.get(node, "<module>"), node))
        return rows

    @staticmethod
    def _call_has_exact_bool_keyword(call: ast.Call) -> bool:
        return "theme_soft_boost_enabled" in {kw.arg for kw in call.keywords}

    def test_every_derived_k4b_bool_callsite_is_explicit_and_the_check_can_die(self):
        rows = self._bool_callsites()
        self.assertTrue(rows, "no K4b exact-bool callsite was derived")
        for rel, owner, call in rows:
            with self.subTest(file=rel, owner=owner, line=call.lineno):
                keywords = {kw.arg for kw in call.keywords}
                self.assertIn("theme_soft_boost_enabled", keywords)
                planted = copy.deepcopy(call)
                planted.keywords = [
                    kw for kw in planted.keywords if kw.arg != "theme_soft_boost_enabled"
                ]
                with self.assertRaises(
                    AssertionError,
                    msg="removing the exact-bool coordinate must make this cell red",
                ):
                    self.assertTrue(self._call_has_exact_bool_keyword(planted))

    def test_k4b_consumer_axis_is_derived_from_actual_boost_reads(self):
        consumers = {
            rel for rel in self._k4b_files()
            if "theme_soft_boost" in _source(rel) or "provisional_theme_boost" in _source(rel)
        }
        expected = {
            "runners/us_short_batch5_data_context.py",
            "engine/us_short_seam_score.py",
            "engine/us_short_forward_policy_heads.py",
        }
        self.assertEqual(expected - consumers, set())
        for rel in expected:
            with self.subTest(consumer=rel):
                planted = consumers - {rel}
                self.assertIn(rel, consumers)
                self.assertNotIn(rel, planted, "removing a consumer coordinate must make coverage red")

    def test_k4b_receipt_binding_axis_is_schema_derived_and_required(self):
        schema = json.loads(
            (ROOT / "schemas/us_short_soft_boost_consumption_receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        required = set(schema["properties"]["bindings"]["required"])
        self.assertEqual(required, {"stage_receipt", "validation_artifact"})
        valid = {
            "schema_name": "us_short_soft_boost_consumption_receipt",
            "schema_version": "1.0.0",
            "generated_at": "2026-06-15T08:31:00-04:00",
            "decision_date": "20260615",
            "requested_enabled": True,
            "effective_enabled": True,
            "status": "consumed_valid_nonempty",
            "reason_code": None,
            "bindings": {
                field: {"path": f"state/us_short/{field}.json", "sha256": "a" * 64}
                for field in required
            },
            "per_ticker": [],
            "top15_impact": {"entered": [], "exited": [], "changed": False},
            "effects": {
                "core_score_effect_enabled": False,
                "top15_effect_enabled": False,
                "operation_advice_effect_claimed": False,
                "dynamic_seats_enabled": False,
                "theme_probe_enabled": False,
                "lifecycle_actions_enabled": False,
                "provider_calls_performed": False,
            },
        }
        from jsonschema import Draft7Validator
        validator = Draft7Validator(schema)
        self.assertEqual(list(validator.iter_errors(valid)), [])
        for field in required:
            with self.subTest(binding=field):
                planted = copy.deepcopy(valid)
                planted["bindings"].pop(field)
                self.assertTrue(
                    list(validator.iter_errors(planted)),
                    "removing a receipt binding coordinate must make schema validation red",
                )

    def test_k4b_score_values_are_schema_derived_and_mutants_are_rejected(self):
        schema = json.loads(
            (ROOT / "schemas/us_short_soft_boost_consumption_receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        actual_values = set(
            schema["properties"]["per_ticker"]["items"]["properties"]["actual_boost"]["enum"]
        )
        boost = importlib.import_module("engine.us_short_provisional_theme_boost")
        self.assertEqual(actual_values, {0.0, *map(float, boost.TIER_POINTS.values())})
        planted = copy.deepcopy(schema)
        planted["properties"]["per_ticker"]["items"]["properties"]["actual_boost"]["enum"].append(7.0)
        self.assertIn(
            7.0,
            planted["properties"]["per_ticker"]["items"]["properties"]["actual_boost"]["enum"],
            "the planted cap mutation must differ from the repository-derived set",
        )
        self.assertNotEqual(
            set(planted["properties"]["per_ticker"]["items"]["properties"]["actual_boost"]["enum"]),
            {0.0, *map(float, boost.TIER_POINTS.values())},
        )
        consumer = importlib.import_module("engine.us_short_soft_boost_consumption")
        resolved = {
            "decision_date": "20260615",
            "requested_enabled": True,
            "effective_enabled": True,
            "status": "consumed_valid_nonempty",
            "reason_code": None,
            "stage_receipt": {"path": "state/us_short/stage.json", "sha256": "a" * 64},
            "validation_artifact": {
                "path": "state/us_short/validation.json", "sha256": "b" * 64,
            },
        }
        with self.assertRaises(
            consumer.SoftBoostConsumptionError,
            msg="the production receipt builder must reject a planted +7 score",
        ):
            consumer.build_consumption_receipt(
                resolved=resolved,
                generated_at="2026-06-15T08:31:00-04:00",
                on_selection={"AAPL": 57.0},
                off_selection={"AAPL": 50.0},
                boost_records={"AAPL": {"theme_soft_boost": 7.0, "evidence_tier": "both"}},
                on_top15=["AAPL"],
                off_top15=["AAPL"],
            )


class ExecutableClosureMatrix:
    """Repository-derived class x exit matrix for the Knife4a A-D recurrence families."""

    NAMED_NON_CELLS = {
        "wrong_requirement": "only forward evidence can disprove the requirement itself",
        "offline_document_corroboration": "offline files cannot prove two real documents; K3 Optional (a)",
    }
    A_BEHAVIOR = {
        "_run_pass2_budget_preview": (
            "tests.provider.test_us_short_weekly_capstone_soft_discovery"
            ".WeeklyCapstoneSoftDiscoveryStageTest"
            ".test_budget_preview_entry_degrades_any_soft_stage_exception_and_continues"
        ),
        "run_weekly_capstone": (
            "tests.provider.test_us_short_weekly_capstone_soft_discovery"
            ".WeeklyCapstoneSoftDiscoveryStageTest"
            ".test_capstone_full_entry_degrades_any_soft_stage_exception_and_reaches_terminal"
        ),
    }
    A_STAGE_BEHAVIOR = (
        "tests.provider.test_us_short_weekly_capstone_soft_discovery"
        ".WeeklyCapstoneSoftDiscoveryStageTest"
        ".test_capstone_boundary_contains_the_real_soft_stage_public_entry"
    )
    A_FROZEN_BEHAVIOR = (
        "tests.provider.test_us_short_weekly_capstone_soft_discovery"
        ".WeeklyCapstoneSoftDiscoveryStageTest"
        ".test_capstone_accepts_every_bound_unusable_canonical_receipt_as_zero_effect"
    )
    # Behaviour tests that `test_c` must still execute even though no GUARDS row
    # names them: they are what makes some derived callsites reachable at all, and
    # membership here also gives a test first pick as a mutation candidate
    # (priority 0).  The four `test_same_day_*` entries are siblings of the single
    # transition bound at `_guard_existing_artifact_hashes` — the five were split
    # out of one aggregate test — so moving or dropping that GUARDS binding has to
    # account for these four as well, or the conflict matrix silently loses reach.
    ADDITIONAL_BEHAVIOR = (
        "tests.provider.test_us_short_provisional_theme_validate"
        ".ProvisionalThemeValidationTests.test_run_packet_is_inert_and_records_input_digests",
        "tests.provider.test_us_short_weekly_capstone_soft_discovery"
        ".WeeklyCapstoneSoftDiscoveryStageTest"
        ".test_merge_consumer_guards_are_load_bearing_at_the_public_entry",
        "tests.provider.test_us_short_weekly_capstone_soft_discovery"
        ".WeeklyCapstoneSoftDiscoveryStageTest"
        ".test_production_checkpoint_records_artifactless_optional_failure_and_terminal_emits",
        "tests.provider.test_us_short_weekly_capstone_soft_discovery"
        ".WeeklyCapstoneSoftDiscoveryStageTest"
        ".test_capstone_boundary_failure_binds_existing_artifact_hashes",
        "tests.provider.test_us_short_weekly_capstone_soft_discovery"
        ".WeeklyCapstoneSoftDiscoveryStageTest"
        ".test_same_day_invalid_to_valid_reaches_terminal_with_bound_conflict_receipt",
        "tests.provider.test_us_short_weekly_capstone_soft_discovery"
        ".WeeklyCapstoneSoftDiscoveryStageTest"
        ".test_same_day_unavailable_to_invalid_reaches_terminal_with_bound_conflict_receipt",
        "tests.provider.test_us_short_weekly_capstone_soft_discovery"
        ".WeeklyCapstoneSoftDiscoveryStageTest"
        ".test_same_day_valid_to_unavailable_reaches_terminal_with_bound_conflict_receipt",
        "tests.provider.test_us_short_weekly_capstone_soft_discovery"
        ".WeeklyCapstoneSoftDiscoveryStageTest"
        ".test_same_day_valid_to_replaced_valid_reaches_terminal_with_bound_conflict_receipt",
    )
    REDUNDANT_REPLAY_TERMS = frozenset({
        "runners.us_short_llm_theme_discovery_merge._guard_input_artifact_hashes",
        "runners.us_short_llm_theme_discovery_merge._guard_member_evidence_tier",
        "runners.us_short_llm_theme_discovery_merge._guard_merge_consumer_clock",
        "runners.us_short_llm_theme_discovery_merge._guard_raw_content_digest",
        "runners.us_short_llm_theme_discovery_merge._guard_source_identity",
        "runners.us_short_llm_theme_discovery_merge._guard_summary_counts",
    })
    REDUNDANT_REPLAY_TEST = (
        "tests.provider.test_us_short_weekly_capstone_soft_discovery"
        ".WeeklyCapstoneSoftDiscoveryStageTest"
        ".test_merge_consumer_redundant_guards_fall_through_to_replay_gate"
    )
    K4A_GUARD_MODULES = frozenset({
        "runners.us_short_discovery_publish_policy",
        "runners.us_short_llm_theme_discovery_merge",
        "runners.us_short_weekly_capstone_soft_discovery",
    })
    NAMED_NON_GUARD_RAISERS = {
        "runners.us_short_discovery_publish_policy": {
            "_gitignored": "internal gitignore adapter covered by exact-slot policy tests",
            "_repo_relative": "internal containment primitive covered by the public slot validator",
            "_staged_temp": "internal staging primitive covered by all three public writer mutations",
        },
        "runners.us_short_weekly_capstone_soft_discovery": {
            "_artifact": "receipt value constructor; leaf path/schema guards are enumerated",
            "_immutable_conflict_receipt": "conflict orchestrator; leaf slot/read/schema guards are enumerated",
            "_publish_failure_receipt": "failure publisher; leaf slot/schema guards are enumerated",
            "_publish_receipt": "receipt publisher; leaf slot/read/schema guards are enumerated",
            "_receipt": "receipt constructor; schema guard is enumerated",
            "_relative_or_none": "nullable adapter; non-null containment guard is enumerated",
        },
    }
    NAMED_NON_GUARD_TESTS = {
        "runners.us_short_weekly_capstone_soft_discovery": {
            "_artifact": "tests.provider.test_us_short_weekly_capstone_soft_discovery"
            ".WeeklyCapstoneSoftDiscoveryStageTest.test_all_five_states_are_distinct_and_invalid_is_not_valid_empty",
            "_immutable_conflict_receipt": "tests.provider.test_us_short_weekly_capstone_soft_discovery"
            ".WeeklyCapstoneSoftDiscoveryStageTest.test_same_day_unavailable_to_valid_reaches_terminal_with_bound_conflict_receipt",
            "_publish_failure_receipt": "tests.provider.test_us_short_weekly_capstone_soft_discovery"
            ".WeeklyCapstoneSoftDiscoveryStageTest.test_all_five_states_are_distinct_and_invalid_is_not_valid_empty",
            "_publish_receipt": "tests.provider.test_us_short_weekly_capstone_soft_discovery"
            ".WeeklyCapstoneSoftDiscoveryStageTest.test_receipt_publisher_writes_and_reloads_a_schema_valid_payload",
            "_receipt": "tests.provider.test_us_short_weekly_capstone_soft_discovery"
            ".WeeklyCapstoneSoftDiscoveryStageTest.test_all_five_states_are_distinct_and_invalid_is_not_valid_empty",
            "_relative_or_none": "tests.provider.test_us_short_weekly_capstone_soft_discovery"
            ".WeeklyCapstoneSoftDiscoveryStageTest.test_all_five_states_are_distinct_and_invalid_is_not_valid_empty",
        },
    }
    # Explicit local evidence decision: persisted raw evidence now reaches the capstone fixture,
    # including the `raw_available` branch.  Its three calls must have a real dying mutation;
    # no raw-evidence coordinate is allowed to survive as a manually frozen exception.
    FROZEN_PERSISTED_RAW_COORDINATES = frozenset()

    @staticmethod
    def _function_calls(function: ast.FunctionDef, callee: str) -> list[ast.Call]:
        return [
            node for node in ast.walk(function)
            if isinstance(node, ast.Call) and _called_name(node.func) == callee
        ]

    @classmethod
    def _derived_soft_execution_exits(cls) -> dict[str, ast.FunctionDef]:
        tree = ast.parse(_source("runners/us_short_weekly_capstone.py"))
        exits: dict[str, ast.FunctionDef] = {}
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            has_stage_run = any(
                isinstance(call.func, ast.Attribute) and call.func.attr == "run"
                for call in ast.walk(node) if isinstance(call, ast.Call)
            )
            # Derive every stage-loop entry from its orchestration shape. A
            # path that forgets to mention the optional stage is the mutation
            # this row must expose, so name/string predicates are forbidden.
            if has_stage_run:
                exits[node.name] = node
        return exits

    def test_a_every_derived_capstone_exit_has_a_load_bearing_soft_failure_boundary(self):
        exits = self._derived_soft_execution_exits()
        self.assertTrue(exits, "no soft-discovery execution exit was derived")
        self.assertEqual(
            set(exits), set(self.A_BEHAVIOR),
            f"unmapped A coordinates: {sorted(set(exits) ^ set(self.A_BEHAVIOR))}",
        )
        for name, function in exits.items():
            with self.subTest(exit=name):
                calls = self._function_calls(function, "_degrade_stage_boundary")
                self.assertTrue(calls, f"A/{name} lacks the structural zero-effect boundary")
                planted = ast.fix_missing_locations(ast.parse(ast.unparse(function)).body[0])
                for node in ast.walk(planted):
                    if isinstance(node, ast.Call) and _called_name(node.func) == "_degrade_stage_boundary":
                        node.func = ast.Name(id="_planted_missing_soft_boundary", ctx=ast.Load())
                self.assertFalse(
                    self._function_calls(planted, "_degrade_soft_discovery_boundary"),
                    f"A/{name} planted failure did not disarm the assertion",
                )
                run, red, resolved = LaneGuardRegistryConformance._run(self.A_BEHAVIOR[name])
                self.assertTrue(resolved)
                self.assertEqual((run, red), (1, 0))
                capstone = importlib.import_module("runners.us_short_weekly_capstone")
                with mock.patch.object(
                    capstone,
                    "_degrade_stage_boundary",
                    lambda *_args, **_kwargs: None,
                ):
                    planted_run, planted_red, _ = LaneGuardRegistryConformance._run(
                        self.A_BEHAVIOR[name]
                    )
                self.assertEqual(planted_run, 1)
                self.assertGreater(
                    planted_red,
                    0,
                    f"A/{name} still passes with its zero-effect boundary removed",
                )
        stages_tree = ast.parse(_source("runners/us_short_weekly_capstone_stages.py"))
        stage_entries = {
            node.func.id
            for node in ast.walk(stages_tree)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "run_offline_stage"
            )
        }
        self.assertEqual(stage_entries, {"run_offline_stage"})
        for test_path in (self.A_STAGE_BEHAVIOR, self.A_FROZEN_BEHAVIOR):
            run, red, resolved = LaneGuardRegistryConformance._run(test_path)
            self.assertTrue(resolved)
            self.assertEqual((run, red), (1, 0))

    @classmethod
    def _derived_lifecycle_sites(cls) -> list[tuple[str, str, str, int]]:
        """Derive route × lifecycle coordinates from the orchestrator AST.

        Route labels come from the public entrypoint's actual signature/branches, while
        lifecycle columns come from calls in the entrypoint bodies.  No production
        registry or human-maintained matrix row is used to create this set.
        """
        tree = ast.parse(_source("runners/us_short_weekly_capstone.py"))
        functions = {
            node.name: node for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        routes = {
            "normal": functions["run_weekly_capstone"],
            "resume": functions["run_weekly_capstone"],
            "injected": functions["run_weekly_capstone"],
            "preview": functions["_run_pass2_budget_preview"],
        }
        sites: list[tuple[str, str, str, int]] = []
        for route, function in routes.items():
            for node in ast.walk(function):
                if not isinstance(node, ast.Call):
                    continue
                callee = _called_name(node.func)
                if callee in K4A_LIFECYCLE_CALL_NAMES:
                    sites.append((route, function.name, callee, node.lineno))
        return sorted(set(sites))

    @classmethod
    def _derived_lifecycle_cells(cls) -> list[tuple[str, str, str, int]]:
        sites = cls._derived_lifecycle_sites()
        return [
            (route, policy, callee, lineno)
            for route, _owner, callee, lineno in sites
            for policy in K4A_INDEPENDENT_STAGE_POLICY_REGISTRY
        ]

    def test_a_matrix_is_independent_derived_and_mutation_load_bearing(self):
        self.assertIn("runners/us_short_weekly_capstone.py", MATRIX_FILES)
        sites = self._derived_lifecycle_sites()
        self.assertTrue(sites, "no orchestrator lifecycle sites were derived")
        derived_columns = {callee for _route, _owner, callee, _line in sites}
        self.assertTrue(
            K4A_LIFECYCLE_CALL_NAMES <= derived_columns,
            f"orchestrator lifecycle columns missing from derived matrix: "
            f"{sorted(K4A_LIFECYCLE_CALL_NAMES - derived_columns)}",
        )
        route_tests = {
            "normal": (
                "tests.provider.test_us_short_weekly_capstone_soft_discovery"
                ".WeeklyCapstoneSoftDiscoveryStageTest"
                ".test_capstone_boundary_degrades_optional_input_output_and_freshness_failures"
            ),
            "resume": (
                "tests.test_us_short_capstone_checkpoint.CapstoneResumeIntegrationTest"
                ".test_resume_refreshes_volatile_stage_and_reuses_bound_frozen_stage_only_when_equivalent"
            ),
            "injected": self.A_STAGE_BEHAVIOR,
            "preview": self.A_BEHAVIOR["_run_pass2_budget_preview"],
        }

        def observe_route(route: str, path: str) -> set[tuple[str, int]]:
            capstone = importlib.import_module("runners.us_short_weekly_capstone")
            observed: set[tuple[str, int]] = set()
            originals: dict[tuple[Any, str], Any] = {}

            def recorder(name: str, original):
                def wrapped(*args, **kwargs):
                    frame = inspect.currentframe().f_back
                    if frame is not None and frame.f_globals.get("__name__") == capstone.__name__:
                        observed.add((name, frame.f_lineno))
                    return original(*args, **kwargs)
                return wrapped

            for name in K4A_LIFECYCLE_CALL_NAMES:
                owner = capstone.checkpoint_store if name in {"record_stage", "restore_stage"} else capstone
                if hasattr(owner, name):
                    original = getattr(owner, name)
                    originals[(owner, name)] = original
                    setattr(owner, name, recorder(name, original))
            original_stage = capstone.Stage

            def stage_factory(*args, **kwargs):
                stage = original_stage(*args, **kwargs)
                for name in ("inputs", "outputs", "run"):
                    original = getattr(stage, name)
                    setattr(stage, name, recorder(name, original))
                return stage

            if route != "normal":
                capstone.Stage = stage_factory
            try:
                run, red, resolved = LaneGuardRegistryConformance._run(path)
                self.assertTrue(resolved, f"route precondition did not resolve: {path}")
                self.assertEqual((run, red), (1, 0), f"route baseline failed: {path}")
            finally:
                capstone.Stage = original_stage
                for (owner, name), original in originals.items():
                    setattr(owner, name, original)
            return observed

        observed_routes = {route: observe_route(route, path) for route, path in route_tests.items()}
        self.assertEqual(set(observed_routes), {"normal", "resume", "injected", "preview"})
        ast_callees = {callee for _route, _owner, callee, _line in sites}
        observed_coordinates = set().union(*observed_routes.values())
        observed_callees = {callee for callee, _line in observed_coordinates}
        self.assertEqual(
            ast_callees,
            observed_callees,
            "every derived orchestrator lifecycle column must be reached by a real route probe",
        )
        expected_coordinates = {(callee, lineno) for _route, _owner, callee, lineno in sites}
        self.assertEqual(
            expected_coordinates,
            observed_coordinates,
            "every derived lifecycle callsite must be reached exactly; "
            f"missing={sorted(expected_coordinates - observed_coordinates)} "
            f"extra={sorted(observed_coordinates - expected_coordinates)}",
        )
        # Keep only AST-derived coordinates that the actual route probe reached;
        # a route alias with no runtime branch is a precondition failure, not a green cell.
        route_sites = {
            route: [site for site in sites if (site[2], site[3]) in observed_routes[route]]
            for route in route_tests
        }
        self.assertTrue(all(route_sites.values()), "a route probe reached no derived lifecycle callsite")

        capstone = importlib.import_module("runners.us_short_weekly_capstone")
        stages = capstone.default_pipeline()
        actual_pairs = {
            stage.failure_policy: (stage.output_policy, stage.checkpoint_policy)
            for stage in stages
        }
        self.assertEqual(actual_pairs, K4A_INDEPENDENT_STAGE_POLICY_REGISTRY)
        self.assertEqual(
            capstone.STAGE_LIFECYCLE_POLICY_REGISTRY,
            {
                policy: {"output_policy": output, "checkpoint_policy": checkpoint}
                for policy, (output, checkpoint) in K4A_INDEPENDENT_STAGE_POLICY_REGISTRY.items()
            },
        )
        optional = [stage for stage in stages if stage.failure_policy == "zero_effect"]
        self.assertEqual([stage.name for stage in optional], ["soft_discovery"])
        self.assertEqual(optional[0].reuse_policy, "never")

        # Every derived lifecycle column has a real planted-failure control.  The
        # controls are test paths (not production policy) and are intentionally
        # checked as real one-case tests so a renamed/deleted control is red.
        probes = {
            "inputs": (
                "tests.provider.test_us_short_weekly_capstone_soft_discovery"
                ".WeeklyCapstoneSoftDiscoveryStageTest"
                ".test_capstone_boundary_degrades_optional_input_output_and_freshness_failures"
            ),
            "outputs": (
                "tests.provider.test_us_short_weekly_capstone_soft_discovery"
                ".WeeklyCapstoneSoftDiscoveryStageTest"
                ".test_capstone_boundary_degrades_optional_input_output_and_freshness_failures"
            ),
            "run": self.A_BEHAVIOR["run_weekly_capstone"],
            "_degrade_stage_boundary": self.A_BEHAVIOR["run_weekly_capstone"],
            "_unchanged_soft_discovery_receipt_matches": self.A_FROZEN_BEHAVIOR,
            "record_stage": (
                "tests.provider.test_us_short_weekly_capstone_soft_discovery"
                ".WeeklyCapstoneSoftDiscoveryStageTest"
                ".test_production_checkpoint_records_artifactless_optional_failure_and_terminal_emits"
            ),
            "restore_stage": (
                "tests.test_us_short_capstone_checkpoint.CapstoneResumeIntegrationTest"
                ".test_resume_refreshes_volatile_stage_and_reuses_bound_frozen_stage_only_when_equivalent"
            ),
            "_publish_current_output_transaction": (
                "tests.provider.test_us_short_weekly_capstone.CapstoneFakeChainTest"
                ".test_publish_second_move_failure_leaves_current_empty"
            ),
        }
        self.assertEqual(derived_columns, set(probes))
        cells = [
            (route, policy, callee, lineno)
            for route, route_rows in route_sites.items()
            for _route, _owner, callee, lineno in route_rows
            for policy in K4A_INDEPENDENT_STAGE_POLICY_REGISTRY
        ]
        self.assertEqual(len(cells), sum(len(rows) for rows in route_sites.values()) * 2)

        def mutate_route(route: str, policy: str, callee: str, lineno: int, path: str) -> tuple[int, int, bool]:
            capstone = importlib.import_module("runners.us_short_weekly_capstone")
            originals: list[tuple[Any, str, Any]] = []

            def planted(*_args, **_kwargs):
                frame = inspect.currentframe().f_back
                if frame is not None and frame.f_globals.get("__name__") == capstone.__name__ \
                        and frame.f_lineno == lineno:
                    raise AssertionError(f"planted lifecycle mutation {route}:{callee}:{lineno}")
                return None

            try:
                if callee in {"inputs", "outputs", "run"}:
                    original_stage = capstone.Stage

                    def stage_factory(*args, **kwargs):
                        stage = original_stage(*args, **kwargs)
                        if stage.name == "soft_discovery":
                            stage.failure_policy = policy
                            stage.output_policy, stage.checkpoint_policy = K4A_INDEPENDENT_STAGE_POLICY_REGISTRY[policy]
                        original = getattr(stage, callee)

                        def wrapped(*a, **kw):
                            frame = inspect.currentframe().f_back
                            if frame is not None and frame.f_globals.get("__name__") == capstone.__name__ \
                                    and frame.f_lineno == lineno:
                                raise AssertionError(f"planted lifecycle mutation {route}:{callee}:{lineno}")
                            return original(*a, **kw)

                        setattr(stage, callee, wrapped)
                        return stage

                    capstone.Stage = stage_factory
                    # Optional method failures must still die when the boundary
                    # is removed; this prevents a caught injected fault reading green.
                    originals.append((capstone, "_degrade_stage_boundary", capstone._degrade_stage_boundary))
                    capstone._degrade_stage_boundary = planted
                    originals.append((capstone, "Stage", original_stage))
                else:
                    owner = capstone.checkpoint_store if callee in {"record_stage", "restore_stage"} else capstone
                    original = getattr(owner, callee)
                    originals.append((owner, callee, original))
                    setattr(owner, callee, planted)
                return LaneGuardRegistryConformance._run(path)
            finally:
                for owner, name, original in reversed(originals):
                    setattr(owner, name, original)

        for route, policy, callee, lineno in cells:
            with self.subTest(route=route, policy=policy, lifecycle=f"{callee}:{lineno}"):
                run, red, resolved = mutate_route(route, policy, callee, lineno, route_tests[route])
                self.assertTrue(resolved, f"missing mutation control for {callee}")
                self.assertGreater(run, 0)
                self.assertGreater(red, 0, f"mutation did not kill {route}:{callee}:{lineno}")

    def test_strict_pass2_approval_callsite_has_independent_load_bearing_control(self):
        """Keep the mandatory approval seam covered without weakening it into fail-soft."""
        tree = ast.parse(_source("runners/us_short_weekly_capstone.py"))
        run_weekly = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_weekly_capstone"
        )
        callsites = [
            node for node in ast.walk(run_weekly)
            if isinstance(node, ast.Call) and _called_name(node.func) == "_build_pass2_budget_approval"
        ]
        self.assertEqual(len(callsites), 1, "strict Pass2 approval must have one pinned orchestrator callsite")
        capstone = importlib.import_module("runners.us_short_weekly_capstone")
        path = (
            "tests.provider.test_us_short_pass2_budget_approval.Pass2BudgetApprovalContractTest"
            ".test_capstone_approval_minting_binds_current_candidate_bytes"
        )
        baseline_run, baseline_red, resolved = LaneGuardRegistryConformance._run(path)
        self.assertTrue(resolved)
        self.assertEqual((baseline_run, baseline_red), (1, 0))
        original = capstone._build_pass2_budget_approval
        with mock.patch.object(
            capstone,
            "_build_pass2_budget_approval",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                capstone.WeeklyCapstoneError("planted strict Pass2 approval callsite failure")
            ),
        ):
            mutated_run, mutated_red, _ = LaneGuardRegistryConformance._run(path)
        self.assertEqual(mutated_run, 1)
        self.assertGreater(mutated_red, 0, "deleting strict approval enforcement must turn the control red")
        self.assertIs(capstone._build_pass2_budget_approval, original)

    def test_named_non_guard_raisers_each_have_a_real_dying_behavior_control(self):
        clean_baselines: dict[str, tuple[int, int, bool]] = {}
        for module_name, entries in self.NAMED_NON_GUARD_TESTS.items():
            module = importlib.import_module(module_name)
            for attribute, test_path in entries.items():
                with self.subTest(module=module_name, attribute=attribute):
                    if test_path not in clean_baselines:
                        clean_baselines[test_path] = LaneGuardRegistryConformance._run(
                            test_path
                        )
                    baseline_run, baseline_red, resolved = clean_baselines[test_path]
                    self.assertTrue(resolved)
                    self.assertEqual((baseline_run, baseline_red), (1, 0))
                    original = getattr(module, attribute)
                    with mock.patch.object(
                        module,
                        attribute,
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            AssertionError(f"planted {module_name}.{attribute} failure")
                        ),
                    ):
                        mutated_run, mutated_red, _ = LaneGuardRegistryConformance._run(test_path)
                    self.assertEqual(mutated_run, 1)
                    self.assertGreater(mutated_red, 0)
                    self.assertIs(getattr(module, attribute), original)

    def test_b_every_derived_merge_revalidation_call_supplies_mandatory_upstream_pairs(self):
        coordinates: list[tuple[str, str, ast.Call]] = []
        for rel in LANE_FILES:
            tree = ast.parse(_source(rel))
            owners = _enclosing_functions(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _called_name(node.func) == "validate_merged_packet":
                    coordinates.append((rel, owners.get(node, "<module>"), node))
        self.assertTrue(coordinates, "no merge revalidation call was derived")
        for rel, owner, call in coordinates:
            with self.subTest(exit=f"{rel}:{owner}:{call.lineno}"):
                keywords = {kw.arg for kw in call.keywords}
                self.assertIn("upstream_pairs", keywords)
                self.assertTrue(
                    any(kw.arg == "upstream_pairs" for kw in call.keywords),
                    "B callsite must carry the mandatory upstream pair binding",
                )
        merge_tree = ast.parse(_source("runners/us_short_llm_theme_discovery_merge.py"))
        entry = next(
            node for node in merge_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "validate_merged_packet"
        )
        upstream_arg = next(
            arg for arg in entry.args.kwonlyargs if arg.arg == "upstream_pairs"
        )
        index = entry.args.kwonlyargs.index(upstream_arg)
        self.assertIsNone(entry.args.kw_defaults[index], "anchoring must not be opt-in")
        run, red, resolved = LaneGuardRegistryConformance._run(
            "tests.provider.test_us_short_weekly_capstone_soft_discovery"
            ".WeeklyCapstoneSoftDiscoveryStageTest"
            ".test_upstream_pairs_are_required_replayed_and_honestly_labelled"
        )
        self.assertTrue(resolved)
        self.assertEqual((run, red), (1, 0))

    @staticmethod
    def _declared_guard_origins() -> dict[str, set[str]]:
        origins: dict[str, set[str]] = {}
        for rel in MATRIX_FILES:
            module_name = rel.replace("/", ".")[:-3]
            if module_name not in ExecutableClosureMatrix.K4A_GUARD_MODULES:
                continue
            if module_name == "runners.us_short_weekly_capstone":
                derived = {"_degrade_stage_boundary"}
            else:
                derived = ExecutableClosureMatrix._reachable_private_raisers(rel)
            derived -= set(ExecutableClosureMatrix.NAMED_NON_GUARD_RAISERS.get(module_name, {}))
            declared = getattr(importlib.import_module(module_name), "CONFORMANCE_GUARDS", ())
            derived.update(declared)
            for consumer_rel in MATRIX_FILES:
                for node in ast.parse(_source(consumer_rel)).body:
                    if isinstance(node, ast.ImportFrom) and node.module == module_name:
                        derived.update(
                            alias.name for alias in node.names if alias.name.startswith("_")
                        )
            if derived:
                origins[module_name] = derived
        return origins

    @staticmethod
    def _reachable_private_raisers(rel: str) -> set[str]:
        tree = ast.parse(_source(rel))
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        graph = {
            name: {
                node.id
                for node in ast.walk(function)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                for node in (node.func,)
                if node.id in functions
            }
            for name, function in functions.items()
        }
        reachable = {name for name in functions if not name.startswith("_")}
        frontier = list(reachable)
        while frontier:
            caller = frontier.pop()
            for callee in graph[caller] - reachable:
                reachable.add(callee)
                frontier.append(callee)
        can_raise = {
            name for name, function in functions.items()
            if any(isinstance(node, ast.Raise) for node in ast.walk(function))
        }
        changed = True
        while changed:
            changed = False
            for caller, callees in graph.items():
                if caller not in can_raise and callees & can_raise:
                    can_raise.add(caller)
                    changed = True
        return {
            name for name in reachable
            if name.startswith("_") and name in can_raise
        }

    @classmethod
    def _derived_guard_callsites(
        cls,
    ) -> list[tuple[str, str, str, str, str, int, int, bool]]:
        origins = cls._declared_guard_origins()
        coordinates: list[tuple[str, str, str, str, str, int, int, bool]] = []
        for rel in MATRIX_FILES:
            consumer_name = rel.replace("/", ".")[:-3]
            tree = ast.parse(_source(rel))
            owners = _enclosing_functions(tree)
            parents = {
                child: parent
                for parent in ast.walk(tree)
                for child in ast.iter_child_nodes(parent)
            }
            bindings: dict[str, tuple[str, str]] = {}
            module_aliases: dict[str, str] = {}
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and node.module in origins:
                    for alias in node.names:
                        if alias.name in origins[node.module]:
                            bindings[alias.asname or alias.name] = (node.module, alias.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in origins:
                            module_aliases[alias.asname or alias.name] = alias.name
            if consumer_name in origins:
                bindings.update({
                    attribute: (consumer_name, attribute)
                    for attribute in origins[consumer_name]
                })
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                patch_owner = consumer_name
                if isinstance(node.func, ast.Name) and node.func.id in bindings:
                    bound_name = node.func.id
                    origin_name, attribute = bindings[bound_name]
                elif (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in module_aliases
                    and node.func.attr in origins[module_aliases[node.func.value.id]]
                ):
                    origin_name = module_aliases[node.func.value.id]
                    attribute = node.func.attr
                    bound_name = attribute
                    patch_owner = origin_name
                else:
                    continue
                ancestor = parents.get(node)
                frozen_raw_branch = False
                while ancestor is not None:
                    if isinstance(ancestor, ast.If):
                        condition = ast.unparse(ancestor.test)
                        if any(marker in condition for marker in (
                            "raw_ref", "raw_available", "live_authorized",
                        )):
                            frozen_raw_branch = True
                            break
                    ancestor = parents.get(ancestor)
                coordinates.append((
                    consumer_name, owners.get(node, "<module>"), patch_owner, bound_name,
                    f"{origin_name}.{attribute}", node.lineno,
                    getattr(node, "end_lineno", node.lineno), frozen_raw_branch,
                ))
        return sorted(set(coordinates))

    def test_c_every_repo_derived_guard_callsite_has_a_real_dying_mutation(self):
        coordinates = self._derived_guard_callsites()
        self.assertTrue(coordinates, "no C guard callsite was derived")
        registry = LaneGuardRegistryConformance
        registered_terms = {
            f"{module}.{attribute}" for module, attribute, _test in registry.GUARDS
        }
        all_tests = tuple(dict.fromkeys(
            [test for _module, _attribute, test in registry.GUARDS]
            + list(self.ADDITIONAL_BEHAVIOR)
        ))
        coverage = {coordinate: [] for coordinate in coordinates}
        active_test = ""
        grouped: dict[
            tuple[str, str], list[tuple[str, str, str, str, str, int, int, bool]]
        ] = {}
        for coordinate in coordinates:
            grouped.setdefault((coordinate[2], coordinate[3]), []).append(coordinate)
        recording_patches = []
        for (patch_owner, bound_name), sites in grouped.items():
            owner_module = importlib.import_module(patch_owner)
            original = getattr(owner_module, bound_name)

            def recording(*args, __original=original, __sites=sites, **kwargs):
                caller_frame = inspect.currentframe().f_back
                if caller_frame is not None:
                    for site in __sites:
                        (
                            _consumer, caller, _patch_owner, _bound, _origin,
                            lineno, end_lineno, _frozen,
                        ) = site
                        if (
                            caller_frame.f_globals.get("__name__") == _consumer
                            and caller_frame.f_code.co_name == caller
                            and lineno <= caller_frame.f_lineno <= end_lineno
                        ):
                            coverage[site].append(active_test)
                return __original(*args, **kwargs)

            recording_patches.append(mock.patch.object(owner_module, bound_name, recording))
        for patch in recording_patches:
            patch.start()
        try:
            for active_test in all_tests:
                registry._run(active_test)
        finally:
            for patch in reversed(recording_patches):
                patch.stop()

        missing: list[str] = []
        a_boundary_coordinates = []
        frozen_live_raw_coordinates = set()
        redundant_replay_baseline: tuple[int, int, bool] | None = None
        for (
            consumer_name, caller, patch_owner, bound_name, origin_term, lineno,
            end_lineno, frozen_raw_branch,
        ) in coordinates:
            coordinate = f"C/{consumer_name}:{caller}:{lineno}->{origin_term}"
            if origin_term not in registered_terms:
                missing.append(f"{coordinate}: unregistered")
                continue
            origin_name, attribute = origin_term.rsplit(".", 1)
            reachable = tuple(dict.fromkeys(coverage[
                (
                    consumer_name, caller, patch_owner, bound_name, origin_term,
                    lineno, end_lineno, frozen_raw_branch,
                )
            ]))
            priority = {
                test: min(
                    ((
                        1 if module == origin_name and registered_attribute == attribute
                        else 2 if module == consumer_name
                        else 3
                    )
                    for module, registered_attribute, row_test in registry.GUARDS
                    if row_test == test),
                    default=0 if test in self.ADDITIONAL_BEHAVIOR else 3,
                )
                for test in reachable
            }
            candidates = tuple(sorted(reachable, key=lambda test: (priority[test], test)))
            if not candidates and frozen_raw_branch and caller == "_verify_receipt":
                frozen_live_raw_coordinates.add((
                    consumer_name, caller, origin_term, lineno,
                ))
                continue
            if (
                candidates
                and caller == "validate_merged_packet"
                and origin_term in self.REDUNDANT_REPLAY_TERMS
            ):
                if redundant_replay_baseline is None:
                    redundant_replay_baseline = registry._run(
                        self.REDUNDANT_REPLAY_TEST
                    )
                run, red, resolved = redundant_replay_baseline
                if resolved and (run, red) == (1, 0):
                    continue
            owner_module = importlib.import_module(patch_owner)
            original = getattr(owner_module, bound_name)
            mutant = registry._neutered(attribute)
            hit = False

            def targeted(*args, __original=original, __mutant=mutant, **kwargs):
                nonlocal hit
                caller_frame = inspect.currentframe().f_back
                if (
                    caller_frame is not None
                    and caller_frame.f_globals.get("__name__") == consumer_name
                    and caller_frame.f_code.co_name == caller
                    and lineno <= caller_frame.f_lineno <= end_lineno
                ):
                    hit = True
                    return __mutant(*args, **kwargs)
                return __original(*args, **kwargs)

            died = False
            with mock.patch.object(owner_module, bound_name, targeted):
                for test_path in candidates:
                    run, red, resolved = registry._run(test_path)
                    if hit and resolved and run == 1 and red > 0:
                        died = True
                        break
            if not hit:
                missing.append(f"{coordinate}: no registered behavior test reaches callsite")
            elif not died:
                siblings = [
                    other
                    for other in coordinates
                    if other != (
                        consumer_name, caller, patch_owner, bound_name, origin_term,
                        lineno, end_lineno, frozen_raw_branch,
                    )
                    and other[4] == origin_term
                    and set(coverage[other]) & set(candidates)
                ]
                if not siblings:
                    missing.append(
                        f"{coordinate}: bypass stayed green without a reached redundant sibling"
                    )
        self.assertEqual(
            frozen_live_raw_coordinates,
            set(self.FROZEN_PERSISTED_RAW_COORDINATES),
            "the frozen persisted-raw branch changed; every new or removed coordinate "
            "requires an explicit local evidence decision",
        )
        self.assertEqual(missing, [], f"unmapped or non-load-bearing C coordinates: {missing}")

    def test_d_repo_shared_resource_tests_inject_state_and_lock_roots(self):
        from tests.provider.us_short_private_test_root import (
            temporary_provider_directory,
        )

        with tempfile.TemporaryDirectory() as clean_root:
            clean_repo = Path(clean_root)
            private_parent = clean_repo / "provider_samples"
            self.assertFalse(private_parent.exists())
            first = temporary_provider_directory(clean_repo)
            first_path = Path(first.__enter__())
            second = temporary_provider_directory(clean_repo)
            second_path = Path(second.__enter__())
            self.assertTrue(first_path.is_dir())
            self.assertTrue(second_path.is_dir())
            self.assertEqual((first_path / ".gitignore").read_text(encoding="utf-8"), "*\n")
            self.assertEqual((second_path / ".gitignore").read_text(encoding="utf-8"), "*\n")
            first.__exit__(None, None, None)
            self.assertTrue(
                private_parent.exists(),
                "one overlapping test removed another test's private parent",
            )
            second.__exit__(None, None, None)
            self.assertFalse(
                private_parent.exists(),
                "overlapping clean-checkout helpers left an ignored parent behind",
            )
            errors: list[BaseException] = []
            first_entered = threading.Event()
            allow_first_exit = threading.Event()
            second_attempting = threading.Event()
            second_entered = threading.Event()

            def first_worker():
                try:
                    with temporary_provider_directory(clean_repo):
                        first_entered.set()
                        allow_first_exit.wait(timeout=5)
                except BaseException as exc:
                    errors.append(exc)

            def second_worker():
                try:
                    second_attempting.set()
                    with temporary_provider_directory(clean_repo):
                        second_entered.set()
                except BaseException as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=first_worker),
                threading.Thread(target=second_worker),
            ]
            threads[0].start()
            self.assertTrue(first_entered.wait(timeout=5))
            threads[1].start()
            self.assertTrue(second_attempting.wait(timeout=5))
            self.assertFalse(
                second_entered.wait(timeout=0.1),
                "same-root test helpers were not serialized",
            )
            allow_first_exit.set()
            for thread in threads:
                thread.join(timeout=10)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertTrue(second_entered.is_set())
            self.assertEqual(errors, [])
            self.assertFalse(
                private_parent.exists(),
                "serialized helper exits left an ignored parent behind",
            )

        def snapshot(root: Path) -> dict[str, bytes]:
            if not root.exists():
                return {}
            return {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*") if path.is_file()
            }

        def test_ids(module: str) -> list[str]:
            suite = unittest.defaultTestLoader.loadTestsFromName(module)
            found: list[str] = []

            def collect(node):
                if isinstance(node, unittest.TestSuite):
                    for child in node:
                        collect(child)
                else:
                    found.append(node.id())

            collect(suite)
            return found

        state_modules: set[str] = set()
        lock_modules: set[str] = set()
        for path in (ROOT / "tests").rglob("test_*.py"):
            if path.resolve() == Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
            module = path.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")
            if any(
                (
                    isinstance(node, ast.Name) and node.id == "STATE_US_SHORT_DIR"
                ) or (
                    isinstance(node, ast.Attribute) and node.attr == "STATE_US_SHORT_DIR"
                ) or (
                    isinstance(node, ast.Constant) and node.value == "STATE_US_SHORT_DIR"
                )
                for node in ast.walk(tree)
            ):
                state_modules.add(module)
            if any(
                isinstance(node, ast.Call)
                and _called_name(node.func) in {"run_weekly_capstone", "_acquire_decision_lock"}
                for node in ast.walk(tree)
            ):
                lock_modules.add(module)
        self.assertTrue(state_modules, "no D state-root injection coordinate was derived")
        self.assertTrue(lock_modules, "no D lock-root injection coordinate was derived")
        resource_modules = state_modules | lock_modules
        selected_by_module = {module: test_ids(module) for module in sorted(resource_modules)}
        mapped_modules = {module for module, tests in selected_by_module.items() if tests}
        self.assertEqual(
            resource_modules - mapped_modules,
            set(),
            "D resource module has no isolated executable behavior coordinate",
        )
        selected = [
            test for module in sorted(selected_by_module) for test in selected_by_module[module]
        ]
        state_root = ROOT / "state" / "us_short"
        legacy_lock_root = (
            ROOT / "provider_samples" / "us_short_weekly_capstone" / "_transaction_locks"
        )
        state_before = snapshot(state_root)
        legacy_locks_before = snapshot(legacy_lock_root)
        capstone = importlib.import_module("runners.us_short_weekly_capstone")
        lock_binding_test = (
            "tests.provider.test_us_short_weekly_capstone.CapstoneFakeChainTest"
            ".test_decision_lock_is_bound_to_the_injected_state_root_and_reacquirable"
        )
        with mock.patch.object(
            capstone,
            "_decision_lock_path",
            lambda ctx: (legacy_lock_root / f"{ctx.decision_date}.lock").resolve(),
        ):
            planted_run, planted_red, planted_resolved = (
                LaneGuardRegistryConformance._run(lock_binding_test)
            )
        self.assertTrue(planted_resolved)
        self.assertEqual(planted_run, 1)
        self.assertGreater(
            planted_red, 0,
            "D planted repository-global lock root did not kill its binding test",
        )

        original_acquire = capstone._acquire_decision_lock
        original_release = capstone._release_decision_lock
        lock_contexts: dict[Path, Any] = {}
        probing = False

        def recording_acquire(ctx):
            lock = original_acquire(ctx)
            lock_contexts[lock.path] = ctx
            return lock

        def proving_release(lock):
            nonlocal probing
            original_release(lock)
            if probing:
                return
            probing = True
            try:
                probe = original_acquire(lock_contexts[lock.path])
                original_release(probe)
            finally:
                probing = False

        with mock.patch.object(capstone, "_acquire_decision_lock", recording_acquire), \
             mock.patch.object(capstone, "_release_decision_lock", proving_release):
            for order in (selected, list(reversed(selected))):
                for test_path in order:
                    run, red, resolved = LaneGuardRegistryConformance._run(test_path)
                    with self.subTest(resource_test=test_path):
                        self.assertTrue(resolved)
                        self.assertEqual((run, red), (1, 0))
                self.assertEqual(
                    snapshot(state_root), state_before,
                    "a resource test changed repository state/us_short",
                )
                self.assertEqual(
                    snapshot(legacy_lock_root), legacy_locks_before,
                    "a resource test changed the legacy repository lock root",
                )
        self.assertEqual(set(self.NAMED_NON_CELLS), {
            "wrong_requirement", "offline_document_corroboration",
        })


class LaneGuardRegistryConformance(unittest.TestCase):
    """Every fail-closed term in the lane's shared modules must have a test that DIES with it.

    This is the mechanical form of the class that recurred as K3-R3, K3-R33, K3-R47 and the
    format-checker arming.  The row proves its own evidence: each named test must EXIST, run
    exactly one case, pass unmutated and fail mutated — otherwise a renamed or deleted test,
    or a fabricated module path, would read as "guard covered".
    """

    GUARDS = (
        ("runners.us_short_discovery_publish_policy", "validate_exact_decision_slot",
         "tests.provider.test_us_short_llm_theme_discovery.OfflineLLMThemeDiscoveryTests"
         ".test_only_own_decision_date_slot_can_be_published"),
        ("runners.us_short_discovery_publish_policy", "write_immutable_json",
         "tests.provider.test_us_short_llm_theme_discovery.OfflineLLMThemeDiscoveryTests"
         ".test_immutable_retry_reuses_only_same_evidence"),
        ("runners.us_short_discovery_publish_policy", "frozen_artifact_matches",
         "tests.provider.test_us_short_llm_theme_discovery.OfflineLLMThemeDiscoveryTests"
         ".test_immutable_retry_reuses_only_same_evidence"),
        ("runners.us_short_discovery_publish_policy", "evidence_bytes",
         "tests.provider.test_us_short_llm_theme_discovery_fetch_x_merge.XFetchAndMergeTests"
         ".test_merge_retry_publish_property_same_evidence_different_clocks_is_idempotent"),
        ("runners.us_short_discovery_publish_policy", "_serialized_payload",
         "tests.provider.test_us_short_llm_theme_discovery.OfflineLLMThemeDiscoveryTests"
         ".test_shared_publish_policy_guard_terms_are_independently_live"),
        ("runners.us_short_discovery_publish_policy", "_serialized_sha256",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_in_memory_discovery_digest_must_hash_the_payload"),
        ("engine.us_short_soft_boost_consumption", "_read_canonical_json",
         "tests.test_us_short_soft_boost_consumption.SoftBoostConsumptionTest"
         ".test_evidence_epoch_digest_is_invariant_to_tracked_json_line_endings"),
        ("runners.us_short_discovery_publish_policy", "publish_immutable_pair",
         "tests.provider.test_us_short_llm_theme_discovery_fetch_web.WebFetchTests"
         ".test_public_packet_pair_rolls_back_if_second_publish_fails"),
        ("runners.us_short_discovery_publish_policy", "write_mutable_ledger",
         "tests.provider.test_us_short_llm_theme_discovery_fetch_web.WebFetchTests"
         ".test_identical_later_refetch_is_idempotent_and_budget_is_per_decision_date"),
        ("runners.us_short_discovery_publish_policy", "mutable_ledger_lock",
         "tests.provider.test_us_short_llm_theme_discovery_fetch_web.BudgetMutexTests"
         ".test_budget_ledger_lock_serializes_two_contenders_without_a_state_file"),
        ("engine.us_short_persisted_text_safety", "persisted_text_violation",
         "tests.provider.test_us_short_llm_theme_discovery.OfflineLLMThemeDiscoveryTests"
         ".test_credential_bearing_url_is_rejected_before_persisting"),
        ("engine.us_short_persisted_text_safety", "credential_query_keys",
         "tests.provider.test_us_short_llm_theme_discovery.OfflineLLMThemeDiscoveryTests"
         ".test_credential_bearing_url_is_rejected_before_persisting"),
        ("engine.us_short_schema_formats", "FORMAT_CHECKER",
         "tests.provider.test_us_short_llm_theme_discovery_offline_invariants.OfflineDiscoveryInvariantTests"
         ".test_schema_date_time_formats_are_enforced_at_every_discovery_boundary"),
        ("runners.us_short_weekly_capstone_soft_discovery", "_schema_validate",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest.test_receipt_schema_rejects_cross_field_and_unknown_reason_drift"),
        ("runners.us_short_weekly_capstone_soft_discovery", "validate_exact_decision_slot",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest.test_stage_fail_closed_terms_have_direct_dying_controls"),
        ("runners.us_short_weekly_capstone_soft_discovery", "_relative",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest.test_stage_fail_closed_terms_have_direct_dying_controls"),
        ("runners.us_short_weekly_capstone_soft_discovery", "_read_json_with_sha",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest.test_stage_fail_closed_terms_have_direct_dying_controls"),
        ("runners.us_short_weekly_capstone_soft_discovery", "_require_complete_pair",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest.test_stage_fail_closed_terms_have_direct_dying_controls"),
        ("runners.us_short_weekly_capstone_soft_discovery", "_conflict_receipt_path",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest.test_stage_fail_closed_terms_have_direct_dying_controls"),
        ("runners.us_short_weekly_capstone_soft_discovery", "_guard_existing_artifact_hashes",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_same_day_unavailable_to_valid_reaches_terminal_with_bound_conflict_receipt"),
        ("runners.us_short_weekly_capstone_soft_discovery", "_published_sha256",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_reused_artifact_digest_records_actual_frozen_file_bytes"),
        ("runners.us_short_llm_theme_discovery_merge", "_guard_generated_clock",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest.test_merge_fail_closed_terms_have_direct_dying_controls"),
        ("runners.us_short_llm_theme_discovery_merge", "_instant",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_merge_entry_points_reject_post_open_upstream_generated_clocks"),
        ("runners.us_short_llm_theme_discovery_merge", "_validate_discovery",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_merge_discovery_shape_guard_is_load_bearing_at_the_public_producer"),
        ("runners.us_short_llm_theme_discovery_merge", "_schema_validate",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_merge_manifest_schema_guard_is_load_bearing_at_the_public_producer"),
        ("runners.us_short_llm_theme_discovery_merge", "_verify_receipt",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_upstream_pairs_are_required_replayed_and_honestly_labelled"),
        ("runners.us_short_llm_theme_discovery_merge", "_guard_source_identity",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest.test_merge_fail_closed_terms_have_direct_dying_controls"),
        ("runners.us_short_llm_theme_discovery_merge", "_guard_source_pit",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_merge_producer_rejects_after_open_fetched_at_for_web_and_x"),
        ("runners.us_short_llm_theme_discovery_merge", "_guard_source_pit",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_merge_consumer_rejects_after_open_fetched_at_for_web_and_x"),
        ("runners.us_short_llm_theme_discovery_merge", "_guard_raw_content_digest",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest.test_merge_fail_closed_terms_have_direct_dying_controls"),
        ("runners.us_short_llm_theme_discovery_merge", "_guard_member_evidence_tier",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest.test_merge_fail_closed_terms_have_direct_dying_controls"),
        ("runners.us_short_llm_theme_discovery_merge", "_guard_summary_counts",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest.test_merge_fail_closed_terms_have_direct_dying_controls"),
        ("runners.us_short_llm_theme_discovery_merge", "_guard_unique_manifest_rows",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest.test_merge_fail_closed_terms_have_direct_dying_controls"),
        ("runners.us_short_llm_theme_discovery_merge", "_guard_merge_producer_clock",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_merge_and_manifest_generated_clocks_are_pit_bounded_and_equal"),
        ("runners.us_short_llm_theme_discovery_merge", "_guard_merge_consumer_clock",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_merge_consumer_clock_guard_has_a_direct_reverse_control"),
        ("runners.us_short_llm_theme_discovery_merge", "_guard_input_artifact_hashes",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_input_artifact_digest_anchor_guard_has_a_direct_reverse_control"),
        ("runners.us_short_llm_theme_discovery_merge", "_guard_upstream_generated_clocks",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_merge_entry_points_reject_post_open_upstream_generated_clocks"),
        ("runners.us_short_llm_theme_discovery_merge", "_raw_receipt_path",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_raw_receipt_traversal_is_rejected_before_filesystem_lookup"),
        ("runners.us_short_llm_theme_discovery_merge", "_verify_provider_response_ref",
         "tests.provider.test_us_short_llm_theme_discovery_fetch_x_merge"
         ".XFetchAndMergeTests"
         ".test_k3_r93_merge_rejects_missing_or_redigested_provider_raw_response"),
        ("runners.us_short_provisional_theme_validate", "_guard_discovery_digest",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest.test_in_memory_discovery_digest_must_hash_the_payload"),
        ("runners.us_short_llm_theme_discovery_fetch_web", "_guard_generated_before_open",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_web_and_x_producer_generated_at_guards_have_direct_controls"),
        ("runners.us_short_llm_theme_discovery_fetch_x", "_guard_generated_before_open",
         "tests.provider.test_us_short_weekly_capstone_soft_discovery"
         ".WeeklyCapstoneSoftDiscoveryStageTest"
         ".test_web_and_x_producer_generated_at_guards_have_direct_controls"),
    )
    # Declared non-guards: exercised through a registered term rather than on their own.
    # `is_rfc3339_date_time` is only reachable via `FORMAT_CHECKER`, which IS registered
    # (the checker holds a bound copy, so patching the function name proves nothing).
    NON_GUARDS = frozenset({"is_rfc3339_date_time"})

    @staticmethod
    def _neutered(name: str):
        """A mutant that disables exactly one guard term, so the dying test is unambiguous."""
        @contextmanager
        def unlocked_ledger(*_args, **_kwargs):
            yield

        def blind_write(payload: dict[str, Any], path: Path, **_kwargs) -> bool:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return False

        def blind_pair(items: Any, **_kwargs) -> None:
            for payload, path in items:
                blind_write(payload, path)

        mutants = {
            "validate_exact_decision_slot": lambda path, expected_path, **_kwargs: Path(path),
            "write_immutable_json": blind_write,
            "publish_immutable_pair": blind_pair,
            "write_mutable_ledger": lambda payload, path, **_kwargs: None,
            "mutable_ledger_lock": unlocked_ledger,
            "frozen_artifact_matches": lambda payload, path, **_kwargs: False,
            "evidence_bytes": lambda payload, **_kwargs: json.dumps(payload, sort_keys=True).encode("utf-8"),
            "_serialized_payload": lambda payload: (
                json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
            ).encode("utf-8"),
            "_serialized_sha256": lambda *_args, **_kwargs: "f" * 64,
            "_read_canonical_json": lambda path: __import__(
                "engine.us_short_soft_boost_consumption", fromlist=["_read_json_bytes"]
            )._read_json_bytes(path),
            "persisted_text_violation": lambda value: None,
            "credential_query_keys": lambda query: [],
            "_schema_validate": lambda *_args, **_kwargs: None,
            "_relative": lambda path: Path(path).as_posix(),
            "_read_json_with_sha": lambda _path, **_kwargs: ({}, "0" * 64),
            "_require_complete_pair": lambda *_args, **_kwargs: None,
            "_conflict_receipt_path": lambda _date, _key, *, state_dir: (
                Path(state_dir) / "unvalidated_conflict.json"
            ),
            "_guard_generated_clock": lambda *_args, **_kwargs: None,
            "_instant": lambda *_args, **_kwargs: __import__(
                "runners.us_short_llm_theme_discovery_fetch_web",
                fromlist=["_parse_dt"],
            )._parse_dt("2026-06-15T13:29:00Z", field="generated_at"),
            "_validate_discovery": lambda *_args, **_kwargs: None,
            "_verify_receipt": lambda artifact, _receipt, *, source_type, **_kwargs: {
                ref["source_id"]: source_type for ref in artifact.get("source_refs", [])
            },
            "_guard_source_identity": lambda *_args, **_kwargs: None,
            "_guard_source_pit": lambda *_args, **_kwargs: None,
            "_guard_raw_content_digest": lambda *_args, **_kwargs: None,
            "_guard_member_evidence_tier": lambda *_args, **_kwargs: None,
            "_guard_summary_counts": lambda *_args, **_kwargs: None,
            "_guard_unique_manifest_rows": lambda rows, *, key, **_kwargs: {
                row[key]: row for row in rows
            },
            "_guard_discovery_digest": lambda *_args, **_kwargs: None,
            "_guard_generated_before_open": lambda *_args, **_kwargs: None,
            "_guard_existing_artifact_hashes": lambda paths: {
                key: "f" * 64 for key in paths
            },
            "_published_sha256": lambda *_args, **_kwargs: "f" * 64,
            "_guard_merge_producer_clock": lambda value, **_kwargs: (
                __import__("runners.us_short_llm_theme_discovery_fetch_web",
                           fromlist=["_parse_dt"])._parse_dt(value, field="generated_at")
            ),
            "_guard_merge_consumer_clock": lambda *_args, **_kwargs: None,
            "_guard_input_artifact_hashes": lambda *_args, **_kwargs: None,
            "_guard_upstream_generated_clocks": lambda *_args, **_kwargs: None,
            "_raw_receipt_path": lambda raw_ref: ROOT / str(raw_ref),
            "_verify_provider_response_ref": lambda *_args, **_kwargs: 0,
            "_degrade_stage_boundary": lambda *_args, **_kwargs: None,
        }
        if name in mutants:
            return mutants[name]
        if name == "FORMAT_CHECKER":
            from jsonschema import FormatChecker

            permissive = FormatChecker()
            permissive.checks("date-time")(lambda value: True)
            return permissive
        raise AssertionError(f"no mutant declared for {name}")

    @staticmethod
    def _run(test_path: str) -> tuple[int, int, bool]:
        """Return (cases run, failures+errors, whether the path resolved to a REAL test)."""
        suite = unittest.defaultTestLoader.loadTestsFromNames([test_path])
        cases: list[Any] = [suite]
        flattened: list[Any] = []
        while cases:
            item = cases.pop()
            if isinstance(item, unittest.TestSuite):
                cases.extend(item)
            else:
                flattened.append(item)
        resolved = bool(flattened) and not any(
            type(case).__name__ == "_FailedTest" or case.id().startswith("unittest.loader")
            for case in flattened
        )
        result = unittest.TextTestRunner(verbosity=0, stream=io.StringIO()).run(suite)
        return result.testsRun, len(result.failures) + len(result.errors), resolved

    def test_the_registry_covers_every_public_term_of_its_shared_modules(self):
        """A guard can also be lost by never being REGISTERED, so the registry is enumerated too."""
        registered = {attribute for _module, attribute, _test in self.GUARDS}
        self.assertGreaterEqual(len(self.GUARDS), 9)
        for module_rel in SHARED_MODULES:
            tree = ast.parse(_source(module_rel))
            public = {
                node.name for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
            }
            public |= {
                target.id for node in tree.body if isinstance(node, ast.Assign)
                for target in node.targets
                if isinstance(target, ast.Name) and target.id.endswith("CHECKER")
            }
            with self.subTest(module=module_rel):
                self.assertEqual(sorted(public - registered - self.NON_GUARDS), [],
                                 f"{module_rel} exposes unregistered fail-closed terms")

    def test_every_declared_lane_guard_is_registered(self):
        registered = {(module, attribute) for module, attribute, _test in self.GUARDS}
        derived_origins = ExecutableClosureMatrix._declared_guard_origins()
        derived_terms = {
            origin_term
            for _consumer, _caller, _patch_owner, _bound, origin_term, _line, _end, _frozen
            in ExecutableClosureMatrix._derived_guard_callsites()
        }
        declared_modules = 0
        for rel in LANE_FILES:
            module_name = rel.replace("/", ".")[:-3]
            module = importlib.import_module(module_name)
            declared = getattr(module, "CONFORMANCE_GUARDS", None)
            tree = ast.parse(_source(rel))
            defined_guards = {
                node.name for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("_guard_")
            }
            if declared is None:
                if defined_guards:
                    self.fail(
                        f"{rel} defines fail-closed guards but has no CONFORMANCE_GUARDS declaration"
                    )
                continue
            declared_modules += 1
            self.assertEqual(
                {(module_name, attribute) for attribute in declared}
                - registered,
                set(),
                f"{rel} declares a guard without a dying-test registry row",
            )
            self.assertEqual(
                defined_guards - set(declared),
                set(),
                f"{rel} defines a guard that can evade the dying-test declaration",
            )
            if module_name in ExecutableClosureMatrix.K4A_GUARD_MODULES:
                named_non_guards = set(
                    ExecutableClosureMatrix.NAMED_NON_GUARD_RAISERS.get(module_name, {})
                )
                self.assertEqual(
                    ExecutableClosureMatrix._reachable_private_raisers(rel)
                    - set(declared)
                    - named_non_guards,
                    set(),
                    f"{rel} has an unclassified reachable private raiser",
                )
                self.assertEqual(
                    {
                        (module_name, attribute)
                        for attribute in derived_origins.get(module_name, set())
                    } - registered,
                    set(),
                    f"{rel} has a repository-derived enforcement term without a dying test",
                )
            self.assertEqual(
                {
                    attribute for attribute in declared
                    if (
                        f"{module_name}.{attribute}" not in derived_terms
                        if module_name in ExecutableClosureMatrix.K4A_GUARD_MODULES
                        else attribute not in {
                            _called_name(node.func)
                            for node in ast.walk(tree)
                            if isinstance(node, ast.Call)
                        }
                    )
                },
                set(),
                f"{rel} declares a guard that no derived production callsite uses",
            )
        self.assertGreaterEqual(declared_modules, 3)

    def test_upstream_clock_guard_is_called_inside_receipt_verification(self):
        tree = ast.parse(_source("runners/us_short_llm_theme_discovery_merge.py"))
        verify = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_verify_receipt"
        )
        calls = {
            _called_name(node.func)
            for node in ast.walk(verify)
            if isinstance(node, ast.Call)
        }
        self.assertIn("_guard_upstream_generated_clocks", calls)

    def test_every_registered_guard_has_a_real_dying_test(self):
        # Several independent guards intentionally share one broad dying test.
        # Its clean baseline only proves that the named test exists and is green,
        # so run that identical fact once per unique test path.  Every guard's
        # planted mutation below still runs separately and must still turn red.
        baseline_by_test: dict[str, tuple[int, int, bool]] = {}
        for module_name, attribute, test_path in self.GUARDS:
            guard = f"{module_name}.{attribute}"
            if test_path not in baseline_by_test:
                baseline_by_test[test_path] = self._run(test_path)
            baseline_run, baseline_red, resolved = baseline_by_test[test_path]
            with self.subTest(guard=guard, phase="baseline"):
                self.assertTrue(resolved, f"registered dying test does not exist: {test_path}")
                self.assertEqual(baseline_run, 1, "the dying test must be exactly one case")
                self.assertEqual(baseline_red, 0, "the dying test must be green before mutation")

            module = importlib.import_module(module_name)
            mutant = self._neutered(attribute)
            patches = [mock.patch.object(module, attribute, mutant)]
            # Callers bind these symbols directly, so the caller's name must be patched too or
            # the mutation silently does nothing (this exact mistake produced a false "no dying
            # test" reading during review).
            for consumer_name in (rel.replace("/", ".")[:-3] for rel in LANE_FILES):
                consumer = importlib.import_module(consumer_name)
                if getattr(consumer, attribute, None) is not None:
                    patches.append(mock.patch.object(consumer, attribute, mutant))
            for patch in patches:
                patch.start()
            try:
                mutated_run, mutated_red, _ = self._run(test_path)
            finally:
                for patch in reversed(patches):
                    patch.stop()
            with self.subTest(guard=guard, phase="planted_failure"):
                self.assertEqual(mutated_run, 1)
                self.assertGreater(mutated_red, 0, f"neutering {attribute} broke no test in {test_path}")

    def test_registry_row_rejects_fabricated_evidence(self):
        for fabricated in (
            "tests.provider.test_us_short_llm_theme_discovery.OfflineLLMThemeDiscoveryTests.test_missing",
            "tests.provider.test_us_short_llm_theme_discovery.NoSuchClass.test_whatever",
            "tests.provider.test_no_such_module_at_all.C.test_x",
        ):
            with self.subTest(path=fabricated):
                _run, _red, resolved = self._run(fabricated)
                self.assertFalse(resolved, "a nonexistent test path must not count as a dying test")


class ConformanceTierPairingConformance(unittest.TestCase):
    """The slow tier lives in a sibling module; nothing else makes that pairing observable.

    Deleting or renaming that module would silently retire every mutation test in it, and the
    only tell would be a drop in the lane's total test count that nobody is obliged to compare.
    The import stays inside the test so loading THIS module never collects the slow tier twice.
    """

    SLOW_TIER = ("K4bExecutableCoverage", "ExecutableClosureMatrix")

    def test_slow_tier_is_paired_with_its_executable_module(self):
        from tests import test_us_short_discovery_conformance_executable as executable

        self.assertTrue(
            executable.__name__.rpartition(".")[2].startswith("test_us_short"),
            "the executable tier must keep a name the US-short lane selector collects",
        )
        for name in self.SLOW_TIER:
            with self.subTest(cls=name):
                base = globals()[name]
                runner = getattr(executable, name, None)
                self.assertFalse(
                    issubclass(base, unittest.TestCase),
                    f"{name} must stay a plain base here, or the focused pack pays for it again",
                )
                self.assertTrue(
                    isinstance(runner, type) and issubclass(runner, (base, unittest.TestCase)),
                    f"{name} has no TestCase runner in the executable module; its tests are retired",
                )
                methods = self._callable_tests(base)
                self.assertTrue(methods, f"{name} carries no test method; the pairing check is vacuous")
                self.assertEqual(
                    self._callable_tests(runner), methods,
                    f"{name} runs a different test set than it declares",
                )

    @staticmethod
    def _callable_tests(cls):
        # callable, not merely named: a method neutered to None keeps its name in dir()
        return {m for m in dir(cls) if m.startswith("test") and callable(getattr(cls, m, None))}


if __name__ == "__main__":
    unittest.main()
