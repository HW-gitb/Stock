"""Find tests that write into the real working tree, so the lane can go parallel.

Parallel workers share one checkout.  A test that writes a repository file --
even one that faithfully restores it afterwards -- can make a concurrent worker
read the probe bytes and go red for no reason.  This scanner produces the list
of tests that do that, so they can be sealed (temp tree / injected path) or, as
a last resort, kept on a serial tail.

**Fail-closed by construction.**  A path expression this scanner cannot resolve
is reported as ``unresolved``, never assumed temporary.  That assumption is the
exact defect ``R-USSHORT-INVENTORY-UNRESOLVABLE-TEMPDIR-PARENT-LAUNDERS-THE-REAL-ROOT``
records: an analyser defaulted ``TemporaryDirectory(dir=<unresolvable>)`` to
temporary, and a real root disappeared from the model.  Here an unresolvable
``dir=`` makes the whole derived subtree unresolved, not safe.

Offline and read-only: it parses source, runs nothing, writes nothing except
the report the caller asks for.
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Top-level repository directories.  A relative path literal starting with one
#: of these names is a real-tree path even without an explicit ``ROOT``.
_REPO_TOP_LEVEL = frozenset({
    ".githooks", ".tools", "A-EGS", "docs", "engine", "presets", "research",
    "result", "runners", "schemas", "skills", "state", "tests", "provider_samples",
})

#: Gitignored shared roots.  Writes here do not dirty git status, but two
#: workers still collide inside them, so they are reported separately.
_SHARED_GITIGNORED = ("state", "provider_samples", "result", "data")

#: Attribute names that denote a real root when imported from another module
#: (`fetch.STATE_DIR`, `runner.RAW_ROOT`, ...).  Matching by shape rather than
#: by an enumerated list is deliberate: an enumerated list is the unguarded
#: hand-written tuple this project has already been burned by.
_ROOT_ATTR_TOKENS = ("ROOT", "DIR", "PATH", "FILE")

#: Calls that mutate the filesystem at a path argument.
#: ``writelines`` is deliberately absent: it belongs to file objects, not to
#: ``Path``, so every hit would be a handle rather than a path.
_PATH_METHOD_SINKS = frozenset({
    "write_text", "write_bytes", "touch", "unlink", "mkdir",
    "rmdir", "rename", "replace", "chmod", "symlink_to", "hardlink_to",
})
_OS_SINKS = frozenset({
    "remove", "unlink", "rename", "replace", "rmdir", "removedirs", "makedirs",
    "mkdir", "utime", "chmod", "truncate", "link", "symlink",
})
_SHUTIL_SINKS = frozenset({
    "copy", "copy2", "copyfile", "copytree", "move", "rmtree", "make_archive",
})
_WRITE_MODES = ("w", "a", "x", "+")

TEMP = "temp"
REPO = "repo"
UNRESOLVED = "unresolved"


def _combine(states: list[str]) -> str:
    """Fail-closed join: repo beats unresolved beats temp."""
    if REPO in states:
        return REPO
    if UNRESOLVED in states:
        return UNRESOLVED
    return TEMP if states else UNRESOLVED


def _is_root_attribute(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr.isupper()
        and any(token in node.attr for token in _ROOT_ATTR_TOKENS)
    )


class _ScopeModel:
    """Module-wide three-state model of which names hold real-tree paths.

    Bindings are collected per NAME across the whole module (including
    ``self.x`` / ``cls.x``, which unittest spreads over ``setUp`` and the test
    methods) and merged fail-closed: a name bound to a real-tree path anywhere
    counts as real-tree everywhere.  That over-reports when one name means two
    things in two methods -- the safe direction, and the whole point of the
    scan is to hand a human the list worth looking at.
    """

    def __init__(self, bindings: dict[str, str]) -> None:
        self.bindings = bindings

    def classify(self, node: ast.AST | None) -> str:
        if node is None:
            return UNRESOLVED
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                head = node.value.replace("\\", "/").lstrip("./").split("/")[0]
                return REPO if head in _REPO_TOP_LEVEL else TEMP
            return TEMP
        if isinstance(node, ast.Name):
            return self.bindings.get(node.id, UNRESOLVED)
        if _is_root_attribute(node):
            return REPO
        if isinstance(node, ast.Attribute):
            key = _attribute_key(node)
            if key is not None and key in self.bindings:
                return self.bindings[key]
            return self.classify(node.value)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return _combine([self.classify(node.left), self.classify(node.right)])
        if isinstance(node, ast.Call):
            return self._classify_call(node)
        if isinstance(node, (ast.JoinedStr, ast.FormattedValue)):
            parts = [self.classify(value) for value in ast.walk(node)
                     if isinstance(value, (ast.Name, ast.Attribute))]
            return _combine(parts or [UNRESOLVED])
        if isinstance(node, (ast.Tuple, ast.List)):
            return _combine([self.classify(item) for item in node.elts] or [TEMP])
        return UNRESOLVED

    def _classify_call(self, node: ast.Call) -> str:
        name = _call_name(node)
        if name in {"TemporaryDirectory", "NamedTemporaryFile", "mkdtemp", "mkstemp"}:
            parent = _keyword(node, "dir")
            if parent is None:
                return TEMP          # stdlib default temp root
            # An explicit parent that cannot be proven outside the tree keeps
            # the whole subtree unresolved.  Never silently temporary.
            state = self.classify(parent)
            return TEMP if state == TEMP else state
        if name in {"Path", "PurePath", "resolve", "absolute", "joinpath",
                    "with_name", "with_suffix", "expanduser", "as_posix"}:
            args = [*node.args, *(kw.value for kw in node.keywords)]
            if isinstance(node.func, ast.Attribute):
                args.append(node.func.value)
            return _combine([self.classify(arg) for arg in args] or [UNRESOLVED])
        if isinstance(node.func, ast.Attribute):
            return self.classify(node.func.value)
        return UNRESOLVED


def _attribute_key(node: ast.Attribute) -> str | None:
    """`self.tmp` -> 'self.tmp'; nested/computed bases are not keyed."""
    if isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


def _bound_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        key = _attribute_key(target)
        return [key] if key else []
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for item in target.elts for name in _bound_names(item)]
    return []


def _collect_bindings(tree: ast.Module, seed: dict[str, str]) -> dict[str, str]:
    """Fail-closed merge of every binding, propagated to a fixed point."""
    sites: list[tuple[list[str], ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                names = _bound_names(target)
                if names:
                    sites.append((names, node.value))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    names = _bound_names(item.optional_vars)
                    if names:
                        sites.append((names, item.context_expr))
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            # `for path in self.raw_root.rglob("*")` makes `path` a real-tree
            # path; without this the commonest cleanup loop reads unresolved.
            names = _bound_names(node.target)
            if names:
                sites.append((names, node.iter))
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for generator in node.generators:
                names = _bound_names(generator.target)
                if names:
                    sites.append((names, generator.iter))

    bindings = dict(seed)
    for _ in range(4):          # short chains; 4 passes reach the fixed point
        changed = False
        model = _ScopeModel(bindings)
        for names, value in sites:
            state = model.classify(value)
            for name in names:
                if name in seed:            # module-level real roots are pinned
                    continue
                merged = _combine([bindings[name], state]) if name in bindings else state
                if bindings.get(name) != merged:
                    bindings[name] = merged
                    changed = True
        if not changed:
            break
    return bindings


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _call_qualifier(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
        return node.func.value.id
    return None


def _keyword(node: ast.Call, name: str) -> ast.AST | None:
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _module_repo_names(tree: ast.Module) -> set[str]:
    """Module-level names anchored on the checkout (`ROOT = Path(__file__)...`)."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and "__file__" in ast.dump(node.value):
            for target in node.targets:
                names.update(_bound_names(target))
    return names


def _sink_path_args(node: ast.Call) -> list[ast.AST] | None:
    """Return the path arguments of a filesystem-mutating call, else None."""
    name = _call_name(node)
    qualifier = _call_qualifier(node)
    if name in _PATH_METHOD_SINKS and isinstance(node.func, ast.Attribute):
        return [node.func.value]
    if qualifier == "os" and name in _OS_SINKS:
        return list(node.args[:2])
    if qualifier == "shutil" and name in _SHUTIL_SINKS:
        return list(node.args[:2])
    if name == "open" and node.args:
        mode = node.args[1] if len(node.args) > 1 else _keyword(node, "mode")
        if isinstance(mode, ast.Constant) and isinstance(mode.value, str) \
                and any(flag in mode.value for flag in _WRITE_MODES):
            return [node.args[0]]
        return None
    return None


def scan_source(source: str, relative: str) -> list[dict]:
    """Return one evidence row per filesystem write that is not provably temp."""
    tree = ast.parse(source)
    seed = {name: REPO for name in _module_repo_names(tree)}
    scope = _ScopeModel(_collect_bindings(tree, seed))
    enclosing = _enclosing_function_names(tree)
    findings: list[dict] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        targets = _sink_path_args(node)
        if targets is None:
            continue
        state = _combine([scope.classify(target) for target in targets])
        if state == TEMP:
            continue
        findings.append({
            "module": relative,
            "line": node.lineno,
            "function": enclosing.get(node.lineno, "<module>"),
            "sink": _call_name(node),
            "state": state,
            "expression": ast.unparse(targets[0])[:120] if targets else "",
        })
    return findings


def _enclosing_function_names(tree: ast.Module) -> dict[int, str]:
    """Line -> innermost function name, for readable evidence rows."""
    spans: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            for line in range(node.lineno, end + 1):
                spans[line] = node.name
    return spans


def _shared_gitignored(expression: str) -> bool:
    return any(f"'{root}'" in expression or f'"{root}"' in expression
               for root in _SHARED_GITIGNORED)


def classify_module(findings: list[dict]) -> str:
    """A-sealed / B-shared-gitignored / C-real-tree / U-unresolved."""
    if not findings:
        return "A_sealed"
    if any(row["state"] == UNRESOLVED for row in findings):
        return "U_unresolved"
    if all(_shared_gitignored(row["expression"]) for row in findings):
        return "B_shared_gitignored"
    return "C_real_tree_write"


def scan_tree(tests_root: Path) -> dict:
    modules: dict[str, dict] = {}
    for path in sorted(tests_root.rglob("test_*.py")):
        relative = path.relative_to(ROOT).as_posix()
        try:
            findings = scan_source(path.read_text(encoding="utf-8"), relative)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            # Unreadable is unresolved, never silently clean.
            modules[relative] = {"classification": "U_unresolved",
                                 "findings": [{"module": relative, "line": 0,
                                               "function": "<unreadable>",
                                               "sink": type(exc).__name__,
                                               "state": UNRESOLVED, "expression": ""}]}
            continue
        classification = classify_module(findings)
        if classification == "A_sealed":
            continue
        modules[relative] = {"classification": classification, "findings": findings}

    counts: dict[str, int] = {}
    for entry in modules.values():
        counts[entry["classification"]] = counts.get(entry["classification"], 0) + 1
    return {
        "schema_name": "a_short_test_isolation_scan",
        "schema_version": "1.0.0",
        "tests_root": tests_root.relative_to(ROOT).as_posix(),
        "not_parallel_safe_modules": sorted(modules),
        "counts": counts,
        "modules": modules,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan tests for real-tree writes")
    parser.add_argument("--tests-root", type=Path, default=ROOT / "tests")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    report = scan_tree(args.tests_root)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
    print(f"[test-isolation-scan] modules_needing_attention="
          f"{len(report['not_parallel_safe_modules'])} counts={report['counts']}")
    for name in report["not_parallel_safe_modules"]:
        entry = report["modules"][name]
        print(f"  {entry['classification']:22} {name} ({len(entry['findings'])} write(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
