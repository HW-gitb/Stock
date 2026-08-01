"""Small, reproducible inventory for US-short test I/O roots.

This is a narrow B0 static guard, not a general Python data-flow analyser.  It follows the
repo-root and direct relative protected-root path forms used by this test corpus, including
instance-attribute aliases, simple local function returns, runner-root keyword injection, and
``os``/``shutil`` filesystem primitives.  An unknown suffix under a repo-root anchor is treated
conservatively as possibly protected.  Runtime execution and arbitrary dynamic containers remain
out of scope; B1/B2 can shrink the explicit allowlist as tests move behind the shared helper.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable


TEST_GLOB = "test_us_short*.py"
PROTECTED_ROOTS = ("provider_samples", "state/us_short")
TEMPORARY_ROOT_HELPERS = frozenset({
    "temporary_provider_directory",
    "temporary_us_short_directory",
    "temporary_us_short_state_directory",
})
ALL_TEMPORARY_ROOT_HELPERS = frozenset(TEMPORARY_ROOT_HELPERS)
GLOBAL_SIDE_EFFECT_SENTINELS = frozenset({
    "tests/test_us_short_discovery_class_guards.py",
    "tests/test_us_short_discovery_conformance.py",
})

WRITE_METHODS = frozenset({
    "mkdir", "open", "touch", "unlink", "rmdir", "write_bytes", "write_text",
})
READ_METHODS = frozenset({
    "exists", "glob", "iterdir", "is_dir", "is_file", "read_bytes", "read_text",
    "rglob", "stat",
})
DESTINATION_CALLS = frozenset({"copy", "copy2", "copyfile", "copytree", "move"})
RENAME_CALLS = frozenset({"link", "rename", "replace"})
OS_WRITE_CALLS = frozenset({
    "makedirs", "mkdir", "remove", "removedirs", "rmdir", "unlink", "truncate",
    "link", "rename", "replace", "symlink",
})
SHUTIL_WRITE_CALLS = frozenset({
    "copy", "copy2", "copyfile", "copytree", "move", "rmtree",
})
NON_PATH_KEYWORDS = frozenset({
    "encoding", "errors", "exist_ok", "mode", "parents", "missing_ok", "newline",
})


@dataclass(frozen=True)
class _PathInfo:
    repo_anchor: bool = False
    segments: tuple[str, ...] = ()
    temporary: bool = False
    unknown: bool = False
    unresolved: bool = False


@dataclass(frozen=True)
class Access:
    module: str
    line: int
    operation: str
    mode: str
    roots: tuple[str, ...]
    source: str
    unresolved: bool = False

    @property
    def key(self) -> str:
        # The stable key deliberately excludes source line numbers.  Per-key counts in the
        # inventory/test snapshot still prevent a new same-operation write from hiding behind an
        # old allowance.
        return f"{self.module}:{self.operation}:{','.join(self.roots)}"

    @property
    def unresolved_key(self) -> str:
        return f"{self.key}:class4_unresolved_write"

    def as_dict(self, *, allowlisted: bool = False) -> dict[str, object]:
        return {
            "module": self.module,
            "line": self.line,
            "operation": self.operation,
            "mode": self.mode,
            "roots": list(self.roots),
            "source": self.source,
            "key": self.key,
            "classification": "class4_unresolved_write" if self.unresolved else "protected_write",
            "unresolved": self.unresolved,
            "allowlisted": allowlisted,
        }


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _literal_segments(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return tuple(part for part in node.value.replace("\\", "/").split("/") if part not in {"", "."})
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.extend(part for part in value.value.replace("\\", "/").split("/") if part not in {"", "."})
        return tuple(parts)
    return ()


def _relative_protected_anchor(segments: tuple[str, ...]) -> bool:
    lowered = tuple(part.lower() for part in segments)
    return lowered[:1] == ("provider_samples",) or lowered[:2] == ("state", "us_short")


def _combine(left: _PathInfo, right: _PathInfo) -> _PathInfo:
    if left.temporary or right.temporary:
        return _PathInfo(temporary=True)
    segments = left.segments + right.segments
    return _PathInfo(
        repo_anchor=left.repo_anchor or right.repo_anchor or left.unresolved or right.unresolved or (
            _relative_protected_anchor(segments) and not (left.unknown or right.unknown)
        ),
        segments=segments,
        unknown=left.unknown or right.unknown,
        unresolved=left.unresolved or right.unresolved,
    )


def _roots(info: _PathInfo) -> tuple[str, ...]:
    if info.temporary or not info.repo_anchor:
        return ()
    if info.unresolved:
        return PROTECTED_ROOTS
    segments = tuple(part.lower() for part in info.segments)
    roots: set[str] = set()
    if segments[:1] == ("provider_samples",):
        roots.add("provider_samples")
    if segments[:2] == ("state", "us_short"):
        roots.add("state/us_short")
    # A repo-root anchor followed by an unresolved imported constant/call is conservatively
    # considered capable of naming either protected root when no exact protected prefix is known.
    # This is the safe result for forms such as ``ROOT / probe.RAW_REL_ROOT`` without pretending
    # to resolve arbitrary imports.  Unknown dynamic suffixes after an exact prefix retain that
    # prefix only (for example ``provider_samples / f"run_{pid}"``).
    if not roots and info.unknown and (
        not segments
        or segments[:1] == ("state",)
        or (segments[:1] and segments[0] not in {
            "docs", "engine", "presets", "research", "result", "runners", "schemas", "skills", "tests"
        })
    ):
        return PROTECTED_ROOTS
    return tuple(sorted(roots))


def _target_key(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _target_key(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _merge_info(prior: _PathInfo, current: _PathInfo) -> _PathInfo:
    if current == _PathInfo():
        return prior
    if prior == _PathInfo() or prior == current:
        return current
    if prior.unresolved or current.unresolved:
        return _PathInfo(
            repo_anchor=prior.repo_anchor or current.repo_anchor,
            segments=prior.segments if prior.segments == current.segments else ("<unknown>",),
            unknown=True,
            unresolved=True,
        )
    if prior.unknown and not current.unknown:
        return current
    if current.unknown and not prior.unknown:
        return prior
    return _PathInfo(
        repo_anchor=prior.repo_anchor or current.repo_anchor,
        segments=prior.segments if prior.segments == current.segments else ("<unknown>",),
        unknown=True,
        unresolved=prior.unresolved or current.unresolved,
    )


def _path_info(
    node: ast.AST | None,
    aliases: dict[str, _PathInfo],
    function_returns: dict[str, _PathInfo] | None = None,
) -> _PathInfo:
    function_returns = function_returns or {}
    if node is None:
        return _PathInfo()
    if isinstance(node, ast.Name):
        if node.id == "ROOT":
            return _PathInfo(repo_anchor=True)
        return aliases.get(node.id, function_returns.get(node.id, _PathInfo(unknown=True)))
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        segments = _literal_segments(node)
        return _PathInfo(repo_anchor=_relative_protected_anchor(segments), segments=segments)
    if isinstance(node, ast.JoinedStr):
        info = _PathInfo()
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                info = _combine(info, _path_info(value.value, aliases, function_returns))
            else:
                info = _combine(info, _PathInfo(segments=_literal_segments(value)))
        return info
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _combine(
            _path_info(node.left, aliases, function_returns),
            _path_info(node.right, aliases, function_returns),
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        info = _combine(
            _path_info(node.left, aliases, function_returns),
            _path_info(node.right, aliases, function_returns),
        )
        if info.repo_anchor:
            return _PathInfo(
                repo_anchor=True,
                segments=info.segments,
                unknown=True,
                unresolved=True,
            )
        return info
    if isinstance(node, ast.Attribute):
        key = _target_key(node)
        if key in aliases:
            return aliases[key]
        # Imported runner modules expose an explicit repo-root ``ROOT`` constant.  Resolve this
        # one stable contract while keeping sibling constants (for example ``STATE_DIR``) in the
        # unresolved class until the caller proves their target.
        if node.attr == "ROOT":
            return _PathInfo(repo_anchor=True)
        return _path_info(node.value, aliases, function_returns)
    if isinstance(node, ast.Subscript):
        return _path_info(node.value, aliases, function_returns)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        info = _PathInfo()
        for element in node.elts:
            info = _combine(info, _path_info(element, aliases, function_returns))
        return info
    if isinstance(node, ast.Dict):
        info = _PathInfo()
        for element in (*node.keys, *node.values):
            info = _combine(info, _path_info(element, aliases, function_returns))
        return info
    if isinstance(node, ast.Call):
        name = _call_name(node)
        if name in function_returns:
            return function_returns[name]
        function_key = f"__function__:{name}" if name else None
        if function_key and function_key in aliases:
            return aliases[function_key]
        if name in ALL_TEMPORARY_ROOT_HELPERS:
            if name in TEMPORARY_ROOT_HELPERS:
                return _PathInfo(temporary=True)
            info = _PathInfo(unknown=True)
            for arg in node.args:
                info = _combine(info, _path_info(arg, aliases, function_returns))
            for keyword in node.keywords:
                info = _combine(info, _path_info(keyword.value, aliases, function_returns))
            return info
        if name in {"TemporaryDirectory", "NamedTemporaryFile", "mkdtemp"}:
            # Standard-library temporary roots are outside the repository unless an explicit
            # protected parent is supplied.  Keep the latter visible so B1 still requires the
            # shared in-repo helper for ``dir=ROOT/provider_samples`` or ``dir=ROOT/state/us_short``.
            parent = next((keyword.value for keyword in node.keywords if keyword.arg == "dir"), None)
            if parent is not None:
                parent_info = _path_info(parent, aliases, function_returns)
                if parent_info.temporary:
                    return _PathInfo(temporary=True)
                if _roots(parent_info):
                    return parent_info
                if parent_info.repo_anchor and not parent_info.unknown and not parent_info.unresolved:
                    return _PathInfo(temporary=True)
                # An explicit but unresolved ``dir=`` may point into either protected root.  Keep
                # it visible as class-4 instead of laundering it into the ordinary tempdir class.
                return _PathInfo(
                    repo_anchor=True,
                    segments=parent_info.segments,
                    unknown=True,
                    unresolved=True,
                )
            return _PathInfo(temporary=True)
        if name in {"Path", "PurePath", "WindowsPath", "PosixPath"}:
            info = _PathInfo()
            for arg in node.args:
                info = _combine(info, _path_info(arg, aliases, function_returns))
            if any(
                isinstance(arg, ast.Call)
                and _call_name(arg) in {"str", "fspath"}
                and _path_info(arg, aliases, function_returns).repo_anchor
                for arg in node.args
            ) and info.repo_anchor:
                return _PathInfo(
                    repo_anchor=True,
                    segments=info.segments,
                    unknown=True,
                    unresolved=True,
                )
            return info
        if name in {"str", "fspath"}:
            info = _PathInfo()
            for arg in node.args:
                info = _combine(info, _path_info(arg, aliases, function_returns))
            if info.repo_anchor and info.unknown:
                return _PathInfo(
                    repo_anchor=True,
                    segments=info.segments,
                    unknown=True,
                    unresolved=True,
                )
            return info
        if isinstance(node.func, ast.Attribute):
            info = _path_info(node.func.value, aliases, function_returns)
            if node.func.attr == "joinpath":
                for arg in node.args:
                    info = _combine(info, _path_info(arg, aliases, function_returns))
            elif node.func.attr == "format":
                for arg in node.args:
                    info = _combine(info, _path_info(arg, aliases, function_returns))
                if info.repo_anchor:
                    return _PathInfo(
                        repo_anchor=True,
                        segments=info.segments,
                        unknown=True,
                        unresolved=True,
                    )
            elif _target_key(node.func) == "os.path.join":
                for arg in node.args:
                    info = _combine(info, _path_info(arg, aliases, function_returns))
                if info.repo_anchor:
                    return _PathInfo(
                        repo_anchor=True,
                        segments=info.segments,
                        unknown=True,
                        unresolved=True,
                    )
            return info
        return _PathInfo(unknown=True)
    return _PathInfo(unknown=True)


def _assigned_targets(node: ast.AST) -> Iterable[str]:
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    else:
        targets = []
    for item in targets:
        target = _target_key(item)
        if target:
            yield target


def _aliases(tree: ast.AST) -> dict[str, _PathInfo]:
    aliases: dict[str, _PathInfo] = {}
    function_returns: dict[str, _PathInfo] = {}
    assignments = [node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))]
    with_bindings = [
        (item.optional_vars, item.context_expr)
        for node in ast.walk(tree)
        if isinstance(node, (ast.With, ast.AsyncWith))
        for item in node.items
        if item.optional_vars is not None
    ]
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    function_returns_nodes = {
        function.name: tuple(
            node.value for node in ast.walk(function) if isinstance(node, ast.Return)
        )
        for function in functions
    }
    for _ in range(len(assignments) + len(with_bindings) + len(functions) + 2):
        changed = False
        for node in assignments:
            value = node.value
            info = _path_info(value, aliases, function_returns)
            for name in _assigned_targets(node):
                if name == "ROOT":
                    info = _PathInfo(repo_anchor=True)
                merged = _merge_info(aliases.get(name, _PathInfo()), info)
                if aliases.get(name, _PathInfo()) != merged:
                    aliases[name] = merged
                    changed = True
        for target, value in with_bindings:
            name = _target_key(target)
            if not name:
                continue
            info = _path_info(value, aliases, function_returns)
            merged = _merge_info(aliases.get(name, _PathInfo()), info)
            if aliases.get(name, _PathInfo()) != merged:
                aliases[name] = merged
                changed = True
        for function in functions:
            info = _PathInfo()
            for value in function_returns_nodes[function.name]:
                info = _merge_info(info, _path_info(value, aliases, function_returns))
            prior = function_returns.get(function.name, _PathInfo())
            merged = _merge_info(prior, info)
            if prior != merged:
                function_returns[function.name] = merged
                changed = True
        if not changed:
            break
    aliases.update({f"__function__:{name}": info for name, info in function_returns.items()})
    return aliases


def _parameter_names(node: ast.AST, names: frozenset[str]) -> frozenset[str]:
    return frozenset(
        item.id
        for item in ast.walk(node)
        if isinstance(item, ast.Name) and item.id in names
    )


def _local_write_helpers(tree: ast.AST) -> dict[str, frozenset[str]]:
    """Find local/imported write wrappers whose path argument reaches a write primitive.

    The inventory is intentionally conservative: a helper named like ``_write_json`` or
    ``write_*`` is treated as a writer when its path-like parameter is passed to a filesystem
    write.  Calls are then attributed to the caller's path argument, so a module-level helper
    cannot hide a protected-root write from the class-2 inventory.
    """
    helpers: dict[str, frozenset[str]] = {}
    imported_hints: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_hints.update(
                alias.asname or alias.name.rsplit(".", 1)[-1]
                for alias in node.names
                if alias.name.startswith("_write") or alias.name.startswith("write_")
            )
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = frozenset(
            argument.arg
            for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        )
        if not params:
            continue
        alias_sources: dict[str, frozenset[str]] = {}
        assignments = [
            node for node in ast.walk(function)
            if isinstance(node, (ast.Assign, ast.AnnAssign))
        ]
        for _ in range(len(assignments) + 1):
            changed = False
            for assignment in assignments:
                value_sources = set(_parameter_names(assignment.value, params))
                for name in tuple(alias_sources):
                    if name in _parameter_names(assignment.value, frozenset(alias_sources)):
                        value_sources.update(alias_sources[name])
                if not value_sources:
                    continue
                targets = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]
                for target in targets:
                    name = _target_key(target)
                    if name and alias_sources.get(name) != frozenset(value_sources):
                        alias_sources[name] = frozenset(value_sources)
                        changed = True
            if not changed:
                break

        def path_sources(node: ast.AST | None) -> frozenset[str]:
            names = set(_parameter_names(node, params)) if node is not None else set()
            for name in _parameter_names(node, frozenset(alias_sources)) if node is not None else ():
                names.update(alias_sources[name])
            return frozenset(names)

        path_params: set[str] = set()
        for call in ast.walk(function):
            if not isinstance(call, ast.Call):
                continue
            name = _call_name(call)
            if isinstance(call.func, ast.Attribute) and name in WRITE_METHODS:
                path_params.update(path_sources(call.func.value))
            elif name == "open" and call.args:
                path_params.update(path_sources(call.args[0]))
            elif (
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id in {"os", "shutil"}
            ):
                qualified = call.func.value.id
                if qualified == "os" and name in OS_WRITE_CALLS:
                    path_params.update(path_sources(call.args[-1]) if call.args else ())
                elif qualified == "shutil" and name in SHUTIL_WRITE_CALLS:
                    index = 1 if name in DESTINATION_CALLS and len(call.args) > 1 else 0
                    path_params.update(path_sources(call.args[index]) if call.args else ())
            elif name in DESTINATION_CALLS | RENAME_CALLS and call.args:
                index = 1 if name in DESTINATION_CALLS and len(call.args) > 1 else len(call.args) - 1
                path_params.update(path_sources(call.args[index]))
        if path_params:
            helpers[function.name] = frozenset(path_params)
    helpers.update({name: frozenset() for name in imported_hints if name not in helpers})
    return helpers


def _mode(node: ast.Call, *, method: bool = False) -> str:
    if "mode" in {keyword.arg for keyword in node.keywords}:
        value = next(keyword.value for keyword in node.keywords if keyword.arg == "mode")
        return value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else "unknown"
    if method and node.args:
        value = node.args[0]
        return value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else "unknown"
    if not method and len(node.args) > 1:
        value = node.args[1]
        return value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else "unknown"
    return "read"


def _accesses(text: str, module: str) -> tuple[Access, ...]:
    tree = ast.parse(text)
    aliases = _aliases(tree)
    helper_specs = _local_write_helpers(tree)
    accesses: list[Access] = []

    def add(node: ast.Call, operation: str, path_node: ast.AST | None, mode: str) -> None:
        info = _path_info(path_node, aliases)
        roots = _roots(info)
        if roots:
            source = ast.get_source_segment(text, path_node) or "<path>"
            accesses.append(Access(module, node.lineno, operation, mode, roots, source, info.unresolved))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name in helper_specs:
            # Local wrappers conventionally take the destination first.  For a helper whose
            # implementation was imported, keep the same conservative first-path convention.
            candidates = list(node.args[:1])
            candidates.extend(
                keyword.value
                for keyword in node.keywords
                if keyword.arg in {"path", "output", "destination", "dest", "target", "file"}
            )
            seen: set[tuple[str, ...]] = set()
            for path_node in candidates:
                info = _path_info(path_node, aliases)
                roots = _roots(info)
                if not roots or roots in seen:
                    continue
                seen.add(roots)
                source = ast.get_source_segment(text, path_node) or "<path>"
                accesses.append(Access(module, node.lineno, f"helper:{name}", "write", roots, source, info.unresolved))
        if isinstance(node.func, ast.Attribute):
            receiver = node.func.value
            qualified_module = receiver.id if isinstance(receiver, ast.Name) else None
            if qualified_module == "os" and name in OS_WRITE_CALLS:
                path_node = node.args[-1] if name in {"link", "rename", "replace", "symlink"} else (
                    node.args[0] if node.args else None
                )
                add(node, f"os.{name}", path_node, "write")
            elif qualified_module == "shutil" and name in SHUTIL_WRITE_CALLS:
                path_node = node.args[1] if name in DESTINATION_CALLS and len(node.args) > 1 else (
                    node.args[0] if node.args else None
                )
                add(node, f"shutil.{name}", path_node, "write")
            if name in WRITE_METHODS:
                if name == "open":
                    raw_mode = _mode(node, method=True)
                    mode = "unknown" if raw_mode == "unknown" else (
                        "write" if any(flag in raw_mode for flag in "wax+") else "read"
                    )
                    add(node, name, receiver, mode)
                else:
                    add(node, name, receiver, "write")
            elif name in READ_METHODS:
                add(node, name, receiver, "read")
            elif name in RENAME_CALLS:
                add(node, name, node.args[-1] if node.args else None, "write")
            if name in {"TemporaryDirectory", "mkdtemp", "NamedTemporaryFile"}:
                directory = next((keyword.value for keyword in node.keywords if keyword.arg == "dir"), None)
                if directory is not None:
                    add(node, name, node, "write")
            for keyword in node.keywords:
                if keyword.arg is None or keyword.arg in NON_PATH_KEYWORDS or (
                    name in {"TemporaryDirectory", "mkdtemp", "NamedTemporaryFile"}
                    and keyword.arg == "dir"
                ):
                    continue
                add(node, f"kwarg:{keyword.arg}", keyword.value, "write")
            continue
        if name == "open":
            raw_mode = _mode(node)
            mode = "unknown" if raw_mode == "unknown" else (
                "write" if any(flag in raw_mode for flag in "wax+") else "read"
            )
            add(node, name, node.args[0] if node.args else None, mode)
        elif name in {"TemporaryDirectory", "mkdtemp", "NamedTemporaryFile"}:
            directory = next((keyword.value for keyword in node.keywords if keyword.arg == "dir"), None)
            if directory is not None:
                add(node, name, node, "write")
        elif name in DESTINATION_CALLS:
            add(node, name, node.args[1] if len(node.args) > 1 else None, "write")
        elif name in RENAME_CALLS:
            add(node, name, node.args[-1] if node.args else None, "write")
        for keyword in node.keywords:
            if keyword.arg is None or keyword.arg in NON_PATH_KEYWORDS or (
                name in {"TemporaryDirectory", "mkdtemp", "NamedTemporaryFile"}
                and keyword.arg == "dir"
            ):
                continue
            add(node, f"kwarg:{keyword.arg}", keyword.value, "write")
    return tuple(sorted(accesses, key=lambda item: (item.module, item.line, item.operation, item.key)))


def scan_test_module(path: Path, repo_root: Path) -> dict[str, object]:
    relative = path.relative_to(repo_root).as_posix()
    accesses = _accesses(path.read_text(encoding="utf-8"), relative)
    writes = tuple(item for item in accesses if item.mode != "read")
    if relative in GLOBAL_SIDE_EFFECT_SENTINELS:
        classification = "class3_global_sentinel"
    elif any(access.unresolved for access in writes):
        classification = "class4_unresolved_write"
    elif writes:
        classification = "class2_write_real_root"
    elif accesses:
        classification = "class1_read_real_root"
    else:
        classification = "class0_no_direct_protected_io"
    return {
        "module": relative,
        "classification": classification,
        "accesses": [item.as_dict() for item in accesses],
        "write_count": len(writes),
        "read_count": len(accesses) - len(writes),
        "unresolved_write_count": sum(access.unresolved for access in writes),
    }


def build_inventory(
    repo_root: Path,
    *,
    allowlist: Iterable[str] = (),
    unresolved_allowlist: Iterable[str] = (),
) -> dict[str, object]:
    repo_root = repo_root.resolve()
    allowlisted = frozenset(allowlist)
    unresolved_allowlisted = frozenset(unresolved_allowlist)
    modules = [
        scan_test_module(path, repo_root)
        for path in sorted(
            (repo_root / "tests").rglob(TEST_GLOB),
            key=lambda candidate: candidate.relative_to(repo_root).as_posix(),
        )
        if path.is_file()
    ]
    findings = [
        access
        for module in modules
        for access in module["accesses"]
        if access["mode"] != "read"
    ]
    unallowlisted = [
        access for access in findings
        if (access["key"] if not access["unresolved"] else f"{access['key']}:class4_unresolved_write")
        not in (allowlisted if not access["unresolved"] else unresolved_allowlisted)
    ]
    unresolved_findings = [access for access in findings if access["unresolved"]]
    protected_findings = [access for access in findings if not access["unresolved"]]
    return {
        "inventory_version": "us_short_test_io_inventory.v0.4.0",
        "scope": {"glob": "tests/**/test_us_short*.py", "protected_roots": list(PROTECTED_ROOTS)},
        "module_count": len(modules),
        "classification_counts": {
            category: sum(module["classification"] == category for module in modules)
            for category in (
                "class0_no_direct_protected_io",
                "class1_read_real_root",
                "class2_write_real_root",
                "class3_global_sentinel",
                "class4_unresolved_write",
            )
        },
        "allowlist": sorted(allowlisted),
        "unresolved_allowlist": sorted(unresolved_allowlisted),
        "unallowlisted_write_findings": unallowlisted,
        "unresolved_write_findings": unresolved_findings,
        "protected_write_finding_counts": {
            key: sum(access["key"] == key for access in protected_findings)
            for key in sorted({access["key"] for access in protected_findings})
        },
        "unresolved_write_finding_counts": {
            f"{access['key']}:class4_unresolved_write": sum(
                item["key"] == access["key"] and item["unresolved"] for item in unresolved_findings
            )
            for access in sorted(unresolved_findings, key=lambda item: item["key"])
        },
        "modules": modules,
    }


def build_snapshot(
    repo_root: Path,
    *,
    allowlist: Iterable[str] = (),
    unresolved_allowlist: Iterable[str] = (),
) -> dict[str, object]:
    """Return a compact tracked snapshot while retaining the full live inventory API.

    Class-0 modules have no direct protected-root I/O, so the snapshot records their count and a
    canonical path-list digest rather than repeating 245 empty rows.  Every module with a direct
    protected read/write or an explicit global sentinel remains listed with its access details.
    """
    full = build_inventory(
        repo_root,
        allowlist=allowlist,
        unresolved_allowlist=unresolved_allowlist,
    )
    names = [module["module"] for module in full["modules"]]
    modules = []
    for module in full["modules"]:
        if module["classification"] == "class0_no_direct_protected_io":
            continue
        roots = sorted({
            root
            for access in module["accesses"]
            for root in access["roots"]
        })
        modules.append({
            "module": module["module"],
            "classification": module["classification"],
            "protected_roots": roots,
            "read_count": module["read_count"],
            "write_count": module["write_count"],
        })
    write_keys = sorted({
        access["key"]
        for module in full["modules"]
        for access in module["accesses"]
        if access["mode"] != "read" and not access["unresolved"]
    })
    return {
        "inventory_version": full["inventory_version"],
        "scope": full["scope"],
        "module_count": full["module_count"],
        "classification_counts": full["classification_counts"],
        "class0_modules_omitted": True,
        "module_path_sha256": hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest(),
        "allowlist": full["allowlist"],
        "unresolved_allowlist": full["unresolved_allowlist"],
        "unallowlisted_write_findings": full["unallowlisted_write_findings"],
        "unresolved_write_finding_counts": full["unresolved_write_finding_counts"],
        "protected_write_finding_keys": write_keys,
        "protected_write_finding_counts": full["protected_write_finding_counts"],
        "modules": modules,
    }


def write_inventory(
    repo_root: Path,
    output: Path,
    *,
    allowlist: Iterable[str] = (),
    unresolved_allowlist: Iterable[str] = (),
) -> None:
    payload = build_snapshot(
        repo_root,
        allowlist=allowlist,
        unresolved_allowlist=unresolved_allowlist,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = build_inventory(args.repo_root)
    if args.output:
        write_inventory(args.repo_root, args.output)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
