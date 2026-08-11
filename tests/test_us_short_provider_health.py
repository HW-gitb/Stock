# -*- coding: utf-8 -*-
"""Tests for US-short provider health-check offline structure (engine/us_short_provider_health.py).

    Covers: §3.2 run-state classification from injected functional health (all-ok → clean; advisory analyst
    grades degraded/down/missing → usable_with_fallback; critical SEC degraded → restricted and down/missing →
blocked; worst-of overall); the §18.1 #3 hard rule that the health check NEVER probes / considers an
UNAUTHORIZED source — passing one raises (so it structurally can't be touched); always-disabled_unapproved
list; malformed input fails closed. No provider/live; no A-share crossing.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_provider_health as ph  # noqa: E402


def _raw(**overrides):
    values = {key: "ok" for key in ph.REQUIRED_HEALTH_KEYS}
    values.update(overrides)
    return values


class Classify(unittest.TestCase):
    def test_all_authorized_ok_is_clean(self):
        r = ph.classify_provider_health(_raw())
        self.assertEqual(r["overall_run_state"], "clean")
        self.assertEqual(set(r["sources"]), set(ph.REQUIRED_HEALTH_KEYS))
        self.assertTrue(all(state == "clean" for state in r["sources"].values()))

    def test_advisory_fmp_degraded_uses_fallback(self):
        r = ph.classify_provider_health(_raw(analyst_grades="degraded"))
        self.assertEqual(r["sources"]["analyst_grades"], "usable_with_fallback")
        self.assertEqual(r["overall_run_state"], "usable_with_fallback")

    def test_advisory_fmp_down_uses_fallback(self):
        r = ph.classify_provider_health(_raw(analyst_grades="down"))
        self.assertEqual(r["sources"]["analyst_grades"], "usable_with_fallback")
        self.assertEqual(r["overall_run_state"], "usable_with_fallback")

    def test_missing_advisory_fmp_uses_fallback(self):
        raw = _raw()
        del raw["analyst_grades"]
        r = ph.classify_provider_health(raw)
        self.assertEqual(r["sources"]["analyst_grades"], "usable_with_fallback")
        self.assertEqual(r["overall_run_state"], "usable_with_fallback")

    def test_critical_sec_degraded_is_restricted(self):
        r = ph.classify_provider_health(_raw(sec_offering_audit="degraded"))
        self.assertEqual(r["sources"]["sec_offering_audit"], "restricted")
        self.assertEqual(r["overall_run_state"], "restricted")

    def test_critical_sec_down_is_blocked(self):
        r = ph.classify_provider_health(_raw(sec_offering_audit="down"))
        self.assertEqual(r["sources"]["sec_offering_audit"], "blocked")
        self.assertEqual(r["overall_run_state"], "blocked")

    def test_missing_authorized_source_is_blocked(self):
        raw = _raw()
        del raw["sec_offering_audit"]
        r = ph.classify_provider_health(raw)   # critical family absent → missing → blocked
        self.assertEqual(r["sources"]["sec_offering_audit"], "blocked")
        self.assertEqual(r["overall_run_state"], "blocked")

    def test_overall_is_worst_of(self):
        r = ph.classify_provider_health(_raw(sec_offering_audit="degraded"))
        self.assertEqual(r["overall_run_state"], "restricted")

    def test_criticality_and_emit_states_are_explicit(self):
        self.assertEqual(ph.CRITICAL_SOURCES, frozenset({"universe_status", "sec_offering_audit"}))
        self.assertEqual(ph.EMIT_ALLOWED_RUN_STATES, frozenset({"clean", "usable_with_fallback"}))

    def test_disabled_unapproved_always_listed(self):
        r = ph.classify_provider_health(_raw())
        self.assertEqual(set(r["disabled_unapproved"]), set(ph.UNAUTHORIZED_SOURCES))


class NeverTouchesUnauthorized(unittest.TestCase):
    """§18.1 #3 「健康检查绝不触达未授权源」 — the check refuses an unauthorized source's status outright."""

    def test_unauthorized_source_status_refused(self):
        self.assertNotIn("yfinance", ph.UNAUTHORIZED_SOURCES)
        for src in ("web_x", "fmp_full_market", "paid_borrow_options", "sec_parser"):
            with self.assertRaises(ph.ProviderHealthError, msg=src):
                ph.classify_provider_health({**_raw(), src: "ok"})

    def test_unknown_source_refused(self):
        with self.assertRaises(ph.ProviderHealthError):
            ph.classify_provider_health({**_raw(), "some_new_unreviewed_feed": "ok"})

    def test_unauthorized_never_in_authorized_set(self):  # the two sets are disjoint
        self.assertEqual(ph.AUTHORIZED_SOURCES & ph.UNAUTHORIZED_SOURCES, frozenset())


class MalformedFailsClosed(unittest.TestCase):
    def test_non_dict_refused(self):
        for bad in (None, "x", 5, ["fmp"]):
            with self.assertRaises(ph.ProviderHealthError):
                ph.classify_provider_health(bad)

    def test_invalid_status_refused(self):
        with self.assertRaises(ph.ProviderHealthError):
            ph.classify_provider_health(_raw(analyst_grades="totally_fine"))

    def test_validator_rejects_states_impossible_for_source_criticality(self):
        base = {
            "disabled_unapproved": sorted(ph.UNAUTHORIZED_SOURCES),
            "overall_run_state": "blocked",
            "sources": {key: "clean" for key in ph.REQUIRED_HEALTH_KEYS},
        }
        base["sources"]["massive_momentum"] = "blocked"
        self.assertFalse(ph.validate_provider_health_result(base))
        base["overall_run_state"] = "usable_with_fallback"
        base["sources"] = {key: "clean" for key in ph.REQUIRED_HEALTH_KEYS}
        base["sources"]["universe_status"] = "usable_with_fallback"
        self.assertFalse(ph.validate_provider_health_result(base))


class OfflineNoProbe(unittest.TestCase):
    def test_module_imports_no_network_or_provider(self):
        # offline: the module must not IMPORT any network / provider / live module (no live probe). Naming
        # yfinance / tushare as an unauthorized-source STRING is fine — the guarantee is no import, not no mention.
        import re
        src = (ROOT / "engine" / "us_short_provider_health.py").read_text(encoding="utf-8")
        imported = [m.group(1).lower() for m in (re.match(r"^\s*(?:from|import)\s+(\S+)", ln) for ln in src.splitlines()) if m]
        for mod in imported:
            for forbidden in ("requests", "urllib", "http", "socket", "subprocess", "ssl", "yfinance", "fmpsdk", "tushare"):
                self.assertNotIn(forbidden, mod, "provider_health imports %s" % mod)


if __name__ == "__main__":
    unittest.main()
