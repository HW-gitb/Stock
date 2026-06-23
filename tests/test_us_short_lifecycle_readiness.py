# -*- coding: utf-8 -*-
"""Tests for US-short §13 lifecycle readiness artifact slice 2c-second-cut (engine/us_short_lifecycle_readiness.py).

Covers: build the TRACKED de-identified readiness from a §13-clean register (via evaluate_lifecycle), refuse a
not-clean register; the readiness is de-identified by construction (exactly the schema's numeric keys, no
ticker/$); write validates the de-identification + consistency gate BEFORE writing (a smuggled ticker field or
an inconsistent due_count / upgrade-not-subset / out-of-range id is refused, no file); roundtrip. No
provider/live; no A-share crossing.
"""
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_lifecycle_readiness as rd  # noqa: E402
import engine.us_short_lifecycle_eval as lc  # noqa: E402

CAL = json.loads((ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json").read_text(encoding="utf-8"))
GOV_TITLE = {g["number"]: g["title"] for g in CAL["calibration_items"]}
READINESS_KEYS = {"schema_name", "schema_version", "as_of", "total_items", "due_count", "due_items", "upgrade_eligible_items"}


def _weekly_dates(n):
    base = date(2026, 1, 5)
    return [(base + timedelta(weeks=i)).strftime("%Y%m%d") for i in range(n)]


def _full_register(as_of="20260112"):
    return {"schema_name": "us_short_lifecycle_register", "schema_version": "1.0.0", "as_of": as_of,
            "items": [{"number": g["number"], "title": GOV_TITLE[g["number"]], "forward_observations": {},
                       "secondary_condition_met": False, "upgrade_margin_frozen": False, "due": False}
                      for g in CAL["calibration_items"]]}


def _due_register(as_of="20260112"):
    reg = _full_register(as_of)
    item = next(it for it in reg["items"] if it["number"] == 1)  # #1 scoring weight: min 12, no secondary
    item["forward_observations"] = {d: 1 for d in _weekly_dates(12)}
    item["due"] = True
    return reg


class BuildReadiness(unittest.TestCase):
    def test_build_from_clean_no_due(self):
        r = rd.build_lifecycle_readiness(_full_register())
        self.assertEqual(r["schema_name"], "us_short_lifecycle_readiness")
        self.assertEqual(r["total_items"], 39)
        self.assertEqual(r["due_count"], 0)
        self.assertEqual(r["due_items"], [])

    def test_build_with_due(self):
        r = rd.build_lifecycle_readiness(_due_register())
        self.assertEqual(r["due_count"], 1)
        self.assertEqual(r["due_items"], [1])

    def test_readiness_is_de_identified(self):
        # exactly the schema's numeric keys — no ticker / $ / performance can be present
        r = rd.build_lifecycle_readiness(_due_register())
        self.assertEqual(set(r), READINESS_KEYS)

    def test_build_refuses_not_clean_register(self):
        reg = _full_register()
        reg["items"] = reg["items"][:-1]  # coverage gap → not §13-clean
        with self.assertRaises(lc.LifecycleRegisterError):
            rd.build_lifecycle_readiness(reg)

    def test_built_readiness_conforms_to_schema(self):
        import jsonschema
        schema = json.loads((ROOT / "schemas" / "us_short_lifecycle_readiness.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft7Validator(schema).validate(rd.build_lifecycle_readiness(_due_register()))


class WriteReadiness(unittest.TestCase):
    def _good(self):
        return rd.build_lifecycle_readiness(_due_register())

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = rd.write_lifecycle_readiness(self._good(), Path(d) / "readiness.json")
            self.assertEqual(json.loads(p.read_text(encoding="utf-8")), self._good())

    def test_refuses_smuggled_ticker_field(self):
        with tempfile.TemporaryDirectory() as d:
            bad = self._good()
            bad["ticker"] = "AAPL"  # additionalProperties:false IS the de-identification gate
            p = Path(d) / "readiness.json"
            with self.assertRaises(rd.LifecycleReadinessError):
                rd.write_lifecycle_readiness(bad, p)
            self.assertFalse(p.exists())

    def test_refuses_inconsistent(self):
        with tempfile.TemporaryDirectory() as d:
            for mutate in (lambda r: r.update(due_count=9),
                           lambda r: r.update(upgrade_eligible_items=[2]),
                           lambda r: r.update(due_items=[999], due_count=1)):
                bad = self._good()
                mutate(bad)
                p = Path(d) / "readiness.json"
                with self.assertRaises(rd.LifecycleReadinessError):
                    rd.write_lifecycle_readiness(bad, p)
                self.assertFalse(p.exists())


class ReadinessConsistencyGate(unittest.TestCase):
    def test_due_count_mismatch_rejected(self):
        bad = rd.build_lifecycle_readiness(_due_register()); bad["due_count"] = 5
        with self.assertRaises(rd.LifecycleReadinessError):
            rd._assert_readiness(bad)

    def test_upgrade_not_subset_rejected(self):
        bad = rd.build_lifecycle_readiness(_due_register()); bad["upgrade_eligible_items"] = [2]
        with self.assertRaises(rd.LifecycleReadinessError):
            rd._assert_readiness(bad)

    def test_id_out_of_range_rejected(self):
        bad = rd.build_lifecycle_readiness(_due_register()); bad["due_items"] = [999]; bad["due_count"] = 1
        with self.assertRaises(rd.LifecycleReadinessError):
            rd._assert_readiness(bad)

    def test_shipped_build_passes_gate(self):  # positive control
        rd._assert_readiness(rd.build_lifecycle_readiness(_due_register()))


class ReadinessAsOfRealDate(unittest.TestCase):
    """R-USSHORT-BATCH3-R2-LIFECYCLE-READINESS-ASOF-REAL-DATE-GAP: as_of must be a strict REAL YYYYMMDD,
    not just 8 digits (the schema pattern can't reject an impossible calendar date like 20260231)."""

    def _good(self):
        return rd.build_lifecycle_readiness(_due_register())

    def test_assert_rejects_impossible_date(self):
        bad = self._good(); bad["as_of"] = "20260231"   # Feb 31 — passes the 8-digit pattern, NOT a real date
        with self.assertRaises(rd.LifecycleReadinessError):
            rd._assert_readiness(bad)

    def test_write_rejects_impossible_date_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as d:
            bad = self._good(); bad["as_of"] = "20260231"
            p = Path(d) / "readiness.json"
            with self.assertRaises(rd.LifecycleReadinessError):
                rd.write_lifecycle_readiness(bad, p)
            self.assertFalse(p.exists())

    def test_rejects_malformed_as_of(self):
        # wrong-len / non-digit / non-string / non-ASCII — fail closed (schema pattern + the strict gate)
        for bad_as_of in ("2026", "2026-01-12", "abcdefgh", 20260112, "2026013１"):
            bad = self._good(); bad["as_of"] = bad_as_of
            with self.assertRaises(rd.LifecycleReadinessError):
                rd._assert_readiness(bad)

    def test_valid_real_date_passes(self):  # positive control: a real date built by evaluate_lifecycle
        rd._assert_readiness(self._good())


if __name__ == "__main__":
    unittest.main()
