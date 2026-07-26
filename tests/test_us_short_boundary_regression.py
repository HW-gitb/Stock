# -*- coding: utf-8 -*-
"""US-short boundary regression tests (§18.1 #12 / §1 / §17 / §12).

Pins the v1 hard boundaries across the WHOLE US-short executable/code surface (engine + runners, NOT just
engine — R-USSHORT-BATCH3-EF-BOUNDARY-REGRESSION-SCOPE-GAP) so a future change can't silently cross them:
  * 不交叉 A 股 — no us_short engine/runner module imports an A-share module (a_short / tushare / cninfo / A-EGS);
    and the account-state ticker contract rejects A-share digit codes (US-symbol letter-start).
  * 不接券商 / 全手动 — no us_short engine/runner module imports a broker / auto-order SDK (so the system can
    advise but never place an order).
  * cash 不互通 / A-US 隔离 — the us_short account-state ticker pattern admits only US listing symbols.
  * ship-gate 不放松 — the ship-gate governance still pins `ungraduated_not_full_size_license: true`
    (a paper / ungraduated track never auto-graduates to a full-size license, §12).

Static / contract assertions only (import-line scan of the source text — runner modules are NOT imported, so no
runtime dependency / side effect). A positive-control proves the import scan actually catches a synthetic
A-share / broker import. No provider/live; no A-share crossing.
"""
import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# the WHOLE US-short executable/code surface: engine modules + runner scripts (tests are not the system surface)
US_SHORT_CODE_FILES = sorted(list((ROOT / "engine").glob("us_short_*.py")) + list((ROOT / "runners").glob("*us_short*.py")))

A_SHARE_IMPORT_TOKENS = ("a_short", "tushare", "cninfo", "a_egs", "egs_main", "a_share")
# A legacy, literal standard-library load remains in the existing batch-5 dry-run probe.  Every other
# dynamic loader is forbidden: a computed target cannot be proven to honour the US/A-share boundary by
# static inspection, while `eval`/`exec` can manufacture the same import at runtime.
APPROVED_DYNAMIC_MODULE_LOADS = frozenset({("__import__", "os")})
# common broker / auto-order SDK import names (a us_short module importing any of these = an execution path).
# `tda` is the TD Ameritrade `tda-api` import (`from tda.auth import ...`) — its omission was the re-review gap.
BROKER_IMPORT_TOKENS = ("ib_insync", "ibapi", "interactive_brokers", "alpaca", "tda", "td_ameritrade",
                        "robin_stocks", "robinhood", "webull", "schwab", "etrade", "oanda", "kiteconnect", "ccxt", "broker")


def _scan_import_surface(text):
    """Return static module paths and dynamic-loader calls without importing a runner.

    Dynamic loaders are separately forbidden below: otherwise a computed target
    cannot be proven to preserve the US/A-share boundary by text inspection.
    Literal targets still join the ordinary token scan so the planted controls
    prove that `__import__` and `importlib.import_module` cannot hide a breach.
    """
    tree = ast.parse(text)
    modules: list[str] = []
    dynamic_calls: list[tuple[str, str]] = []
    importlib_modules: set[str] = set()
    import_module_functions: set[str] = set()
    builtin_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name.lower())
                if alias.name == "importlib":
                    importlib_modules.add(alias.asname or alias.name)
                if alias.name == "builtins":
                    builtin_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module.lower())
                modules.extend(f"{node.module}.{alias.name}".lower() for alias in node.names)
            if node.module == "importlib":
                import_module_functions.update(
                    alias.asname or alias.name for alias in node.names if alias.name == "import_module"
                )

    def call_name(node):
        if isinstance(node, ast.Name):
            if node.id == "__import__":
                return "__import__"
            if node.id in import_module_functions:
                return "importlib.import_module"
            if node.id in {"eval", "exec"}:
                return node.id
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.attr == "import_module" and node.value.id in importlib_modules:
                return "importlib.import_module"
            if node.attr == "__import__" and node.value.id in builtin_modules:
                return "builtins.__import__"
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (loader := call_name(node.func)):
            target = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) else "<computed>"
            dynamic_calls.append((loader, target))
            if loader in {"__import__", "importlib.import_module", "builtins.__import__"} and target != "<computed>":
                modules.append(target.lower())
    return modules, dynamic_calls


def _imported_modules(text):
    return _scan_import_surface(text)[0]


def _dynamic_loader_offenders(named_sources):
    return [(name, loader, target) for name, text in named_sources
            for loader, target in _scan_import_surface(text)[1]]


def _forbidden_dynamic_import_offenders(named_sources, tokens):
    return [(name, loader, target) for name, loader, target in _dynamic_loader_offenders(named_sources)
            if target != "<computed>" and any(token in target.lower() for token in tokens)]


def _unapproved_dynamic_loader_offenders(named_sources):
    offenders = []
    for name, loader, target in _dynamic_loader_offenders(named_sources):
        if loader in {"eval", "exec"}:
            offenders.append((name, loader, target))
        elif target == "<computed>" or (loader, target) not in APPROVED_DYNAMIC_MODULE_LOADS:
            offenders.append((name, loader, target))
    return offenders


def _forbidden_import_offenders(named_sources, tokens):
    """named_sources: iterable of (name, source_text). Returns [(name, imported_module), ...] for imports whose
    module path contains a forbidden token. Operates on source TEXT (no runner import / side effect)."""
    return [(name, mod) for name, text in named_sources
            for mod in _imported_modules(text) if any(tok in mod for tok in tokens)]


def _surface():
    return [(str(f.relative_to(ROOT)), f.read_text(encoding="utf-8")) for f in US_SHORT_CODE_FILES]


class SurfaceWiring(unittest.TestCase):
    def test_surface_covers_engine_and_runners(self):
        self.assertTrue(US_SHORT_CODE_FILES, "no us_short code files found (test wiring broke)")
        parents = {f.parent.name for f in US_SHORT_CODE_FILES}
        self.assertIn("engine", parents)
        self.assertIn("runners", parents, "boundary scan must cover the runner surface, not only engine")


class NoAShareCrossing(unittest.TestCase):
    def test_no_a_share_module_imported(self):
        self.assertEqual(_forbidden_import_offenders(_surface(), A_SHARE_IMPORT_TOKENS), [],
                         "a us_short engine/runner module imports an A-share module")

    def test_no_dynamic_a_share_target_can_hide_a_crossing(self):
        self.assertEqual(_forbidden_dynamic_import_offenders(_surface(), A_SHARE_IMPORT_TOKENS), [],
                         "a US-short module dynamically imports an A-share module")

    def test_no_unapproved_or_computed_dynamic_loader_can_hide_a_crossing(self):
        self.assertEqual(_unapproved_dynamic_loader_offenders(_surface()), [],
                         "a US-short module uses a computed or unreviewed dynamic loader/eval")

    def test_account_state_ticker_rejects_a_share_digit_codes(self):
        schema = json.loads((ROOT / "schemas" / "us_short_account_state.schema.json").read_text(encoding="utf-8"))
        self.assertIn("^[A-Z]", json.dumps(schema),
                      "account-state ticker pattern no longer requires a letter start (A-share codes could slip in)")


class NoBrokerAutoOrder(unittest.TestCase):
    def test_no_broker_sdk_imported(self):
        self.assertEqual(_forbidden_import_offenders(_surface(), BROKER_IMPORT_TOKENS), [],
                         "a us_short engine/runner module imports a broker / auto-order SDK")


class ShipGateDoesNotLoosen(unittest.TestCase):
    def test_ungraduated_never_gets_full_size_license(self):
        preset = json.loads((ROOT / "presets" / "us_short_ship_gate_sizing_governance_20260620.json").read_text(encoding="utf-8"))
        self.assertIs(preset.get("ungraduated_not_full_size_license"), True,
                      "ship-gate loosened: a paper / ungraduated track must NEVER get a full-size license (§12)")


class GuardDetectionIsReal(unittest.TestCase):
    """Positive control / planted-failure: the import scan genuinely catches a synthetic runner-side forbidden
    import (not a no-op that only ever sees clean engine files)."""

    def test_synthetic_a_share_import_is_caught(self):
        synth = [("runners/fake_us_short_runner.py", "import json\nimport tushare as ts\nfrom a_short.egs import x")]
        self.assertTrue(_forbidden_import_offenders(synth, A_SHARE_IMPORT_TOKENS))

    def test_synthetic_dynamic_a_share_import_is_caught_and_dynamic_loading_is_blocked(self):
        forms = (
            'import importlib\nimportlib.import_module("runners.a_short_hidden")',
            'from importlib import import_module as load\nload("a_short.hidden")',
            'import builtins as b\nb.__import__("engine.a_share_hidden")',
        )
        for source in forms:
            with self.subTest(source=source):
                named = [("runners/fake_us_short_runner.py", source)]
                self.assertTrue(_forbidden_import_offenders(named, A_SHARE_IMPORT_TOKENS))
                self.assertTrue(_forbidden_dynamic_import_offenders(named, A_SHARE_IMPORT_TOKENS))

    def test_synthetic_computed_loader_and_eval_are_blocked(self):
        forms = (
            'import importlib\nname = "runners.a_short_hidden"\nimportlib.import_module(name)',
            '__import__("runners." + "a_short_hidden")',
            'eval("__import__(\\\"runners.a_short_hidden\\\")")',
        )
        for source in forms:
            with self.subTest(source=source):
                named = [("runners/fake_us_short_runner.py", source)]
                self.assertTrue(_unapproved_dynamic_loader_offenders(named))

    def test_explicit_legacy_standard_library_dynamic_load_is_the_only_allowlisted_exception(self):
        named = [("runners/fake_us_short_runner.py", '__import__("os")')]
        self.assertEqual(_unapproved_dynamic_loader_offenders(named), [])

    def test_synthetic_broker_import_is_caught(self):
        # incl. tda (TD Ameritrade) `from tda.auth import ...` — the form the re-review found uncaught
        for imp in ("import ib_insync", "import tda", "from tda.auth import easy_client",
                    "import robin_stocks", "from alpaca.trading import client", "import webull"):
            self.assertTrue(_forbidden_import_offenders([("runners/fake_us_short_exec.py", imp)], BROKER_IMPORT_TOKENS), imp)

    def test_clean_source_not_flagged(self):  # no false positive
        synth = [("ok.py", "import json\nfrom pathlib import Path\nfrom engine.us_short_private_paths import reject_nonprivate_output_path")]
        self.assertEqual(_forbidden_import_offenders(synth, A_SHARE_IMPORT_TOKENS + BROKER_IMPORT_TOKENS), [])


if __name__ == "__main__":
    unittest.main()
