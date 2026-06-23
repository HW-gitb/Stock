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
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# the WHOLE US-short executable/code surface: engine modules + runner scripts (tests are not the system surface)
US_SHORT_CODE_FILES = sorted(list((ROOT / "engine").glob("us_short_*.py")) + list((ROOT / "runners").glob("*us_short*.py")))

_IMPORT = re.compile(r"^\s*(?:from|import)\s+(\S+)")
A_SHARE_IMPORT_TOKENS = ("a_short", "tushare", "cninfo", "a_egs", "egs_main", "a_share")
# common broker / auto-order SDK import names (a us_short module importing any of these = an execution path).
# `tda` is the TD Ameritrade `tda-api` import (`from tda.auth import ...`) — its omission was the re-review gap.
BROKER_IMPORT_TOKENS = ("ib_insync", "ibapi", "interactive_brokers", "alpaca", "tda", "td_ameritrade",
                        "robin_stocks", "robinhood", "webull", "schwab", "etrade", "oanda", "kiteconnect", "ccxt", "broker")


def _imported_modules(text):
    return [m.group(1).lower() for m in (_IMPORT.match(ln) for ln in text.splitlines()) if m]


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
