"""GOV-R6 class guard: a test that spawns a repo Python child and reads its text output
must pin BOTH ends of the pipe, never the ambient locale.

Why this exists as a derived scan rather than a fixed list: the defect it prevents is invisible
in the authoring shell.  A child's stdio encoding follows the `PYTHONIOENCODING` it inherits, and
`subprocess.run(..., text=True)` without `encoding=` decodes with the *runner's* locale.  On a
cp936 Windows checkout an ambient `PYTHONIOENCODING=utf-8` therefore turns every assertion on the
captured text into `UnicodeDecodeError -> stdout/stderr is None -> TypeError`, which is how nine
`FailClosedAndRedaction` guards went red while the same code was green in another shell.  A site
added tomorrow would reproduce it, so the rule is enforced by scanning, not by memory.
"""
from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
_SPAWNERS = {"run", "Popen", "check_output"}


def _decodes_text(kw: dict[str, ast.AST]) -> bool:
    return any(isinstance(kw.get(name), ast.Constant) and kw[name].value is True
               for name in ("text", "universal_newlines"))


def _is_python_child(call: ast.Call) -> bool:
    """True when argv[0] is this interpreter, i.e. the child is a repo Python script."""
    if not call.args:
        return False
    argv = call.args[0]
    if not isinstance(argv, (ast.List, ast.Tuple)) or not argv.elts:
        return False
    head = argv.elts[0]
    if isinstance(head, ast.Starred):
        head = head.value
    return (isinstance(head, ast.Attribute) and head.attr == "executable"
            and isinstance(head.value, ast.Name) and head.value.id == "sys")


def _spawn_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name not in _SPAWNERS:
            continue
        module = getattr(getattr(fn, "value", None), "id", "")
        if name != "check_output" and module != "subprocess":
            continue
        yield node


def _enclosing_source(source: str, tree: ast.AST, call: ast.Call) -> str:
    """Source of the smallest function enclosing `call` (falls back to the whole module)."""
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= call.lineno <= (node.end_lineno or node.lineno):
                if best is None or node.lineno > best.lineno:
                    best = node
    return ast.get_source_segment(source, best) or source if best is not None else source


def offenders(directory: Path) -> list[str]:
    """`<relpath>:<line>:<reason>` for every python-child text capture that trusts the locale."""
    found: list[str] = []
    for path in sorted(directory.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:                                   # not our business to police syntax
            continue
        for call in _spawn_calls(tree):
            kw = {k.arg: k.value for k in call.keywords if k.arg}
            if not _decodes_text(kw) or not _is_python_child(call):
                continue
            rel = path.relative_to(directory).as_posix()
            if "encoding" not in kw:
                found.append(f"{rel}:{call.lineno}:parent-decode-not-pinned")
            elif "PYTHONIOENCODING" not in _enclosing_source(source, tree, call):
                found.append(f"{rel}:{call.lineno}:child-encoding-not-pinned")
    return found


class SubprocessTextCaptureEncodingPin(unittest.TestCase):
    def test_no_python_child_text_capture_trusts_the_ambient_locale(self):
        self.assertEqual(offenders(TESTS), [])

    def test_the_scan_catches_both_halves_it_claims_to_enforce(self):
        """Planted failures — without these the empty result above would be vacuous."""
        cases = {
            "parent-decode-not-pinned": (
                "import os, subprocess, sys\n"
                "def f():\n"
                "    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}\n"
                "    return subprocess.run([sys.executable, 'x.py'], env=env,\n"
                "                          capture_output=True, text=True)\n"),
            "child-encoding-not-pinned": (
                "import subprocess, sys\n"
                "def f():\n"
                "    return subprocess.run([sys.executable, 'x.py'], capture_output=True,\n"
                "                          text=True, encoding='utf-8')\n"),
        }
        clean = ("import os, subprocess, sys\n"
                 "def f():\n"
                 "    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}\n"
                 "    return subprocess.run([sys.executable, 'x.py'], env=env, capture_output=True,\n"
                 "                          text=True, encoding='utf-8', errors='replace')\n")
        ignorable = ("import subprocess\n"
                     "def f():\n"
                     "    return subprocess.run(['git', 'check-ignore', '-q', 'x'],\n"
                     "                          capture_output=True, text=True)\n")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for reason, body in cases.items():
                (base / f"test_{reason.replace('-', '_')}.py").write_text(body, encoding="utf-8")
            (base / "test_clean.py").write_text(clean, encoding="utf-8")
            (base / "test_non_python_child.py").write_text(ignorable, encoding="utf-8")
            reported = offenders(base)
        self.assertEqual(sorted(row.split(":")[-1] for row in reported), sorted(cases))
        self.assertFalse([row for row in reported if "clean" in row or "non_python_child" in row])


if __name__ == "__main__":
    unittest.main()
