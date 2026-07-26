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

import ast
import importlib
import io
import json
import sys
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


def _source(rel: str) -> str:
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
LANE_SCHEMAS = derived_lane_schemas()
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
        ("runners.us_short_discovery_publish_policy", "publish_immutable_pair",
         "tests.provider.test_us_short_llm_theme_discovery_fetch_web.WebFetchTests"
         ".test_public_packet_pair_rolls_back_if_second_publish_fails"),
        ("runners.us_short_discovery_publish_policy", "write_mutable_ledger",
         "tests.provider.test_us_short_llm_theme_discovery_fetch_web.WebFetchTests"
         ".test_identical_later_refetch_is_idempotent_and_budget_is_per_decision_date"),
        ("engine.us_short_persisted_text_safety", "persisted_text_violation",
         "tests.provider.test_us_short_llm_theme_discovery.OfflineLLMThemeDiscoveryTests"
         ".test_credential_bearing_url_is_rejected_before_persisting"),
        ("engine.us_short_persisted_text_safety", "credential_query_keys",
         "tests.provider.test_us_short_llm_theme_discovery.OfflineLLMThemeDiscoveryTests"
         ".test_credential_bearing_url_is_rejected_before_persisting"),
        ("engine.us_short_schema_formats", "FORMAT_CHECKER",
         "tests.provider.test_us_short_llm_theme_discovery_offline_invariants.OfflineDiscoveryInvariantTests"
         ".test_schema_date_time_formats_are_enforced_at_every_discovery_boundary"),
    )
    # Declared non-guards: exercised through a registered term rather than on their own.
    # `is_rfc3339_date_time` is only reachable via `FORMAT_CHECKER`, which IS registered
    # (the checker holds a bound copy, so patching the function name proves nothing).
    NON_GUARDS = frozenset({"is_rfc3339_date_time"})

    @staticmethod
    def _neutered(name: str):
        """A mutant that disables exactly one guard term, so the dying test is unambiguous."""
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
            "frozen_artifact_matches": lambda payload, path, **_kwargs: False,
            "evidence_bytes": lambda payload, **_kwargs: json.dumps(payload, sort_keys=True).encode("utf-8"),
            "persisted_text_violation": lambda value: None,
            "credential_query_keys": lambda query: [],
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

    def test_every_registered_guard_has_a_real_dying_test(self):
        for module_name, attribute, test_path in self.GUARDS:
            with self.subTest(guard=f"{module_name}.{attribute}"):
                baseline_run, baseline_red, resolved = self._run(test_path)
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


if __name__ == "__main__":
    unittest.main()
