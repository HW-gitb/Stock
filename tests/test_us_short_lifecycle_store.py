# -*- coding: utf-8 -*-
"""Tests for US-short §13 lifecycle register persistence slice 2b (engine/us_short_lifecycle_store.py).

Covers: the FIRST lifecycle persister wiring the §18.0 P0 private-path guard (relative / in-repo-nonignored
refused; gitignored in-repo + outside-repo allowed; guard BEFORE validate), refusing to persist a not-clean
register; and load fail-closed on a missing / corrupt-JSON / not-clean / stale (as_of ahead of the run
decision_date) artifact, with idempotent same-date + forward-date loads OK. No provider/live; no A-share.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_lifecycle_store as store  # noqa: E402
from engine.us_short_private_paths import PrivatePathError  # noqa: E402

CAL = json.loads((ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json").read_text(encoding="utf-8"))
GOV_TITLE = {g["number"]: g["title"] for g in CAL["calibration_items"]}


def _full_register(as_of="20260112"):
    """A §13-clean baseline register (every §13.1 item enrolled, all counts 0, due False)."""
    return {"schema_name": "us_short_lifecycle_register", "schema_version": "1.0.0", "as_of": as_of,
            "items": [{"number": g["number"], "title": GOV_TITLE[g["number"]], "forward_observations": {},
                       "secondary_condition_met": False, "upgrade_margin_frozen": False, "due": False}
                      for g in CAL["calibration_items"]]}


def _not_clean_register():
    reg = _full_register()
    reg["items"] = reg["items"][:-1]  # coverage gap → not §13-clean
    return reg


class WriteGuardWiring(unittest.TestCase):
    def test_relative_path_refused(self):
        with self.assertRaises(PrivatePathError):
            store.write_lifecycle_register(_full_register(), "lifecycle_register.json")

    def test_in_repo_nonignored_refused(self):
        with self.assertRaises(PrivatePathError):
            store.write_lifecycle_register(_full_register(), store.ROOT / "lifecycle_x.json")

    def test_outside_repo_writes(self):
        with tempfile.TemporaryDirectory() as d:
            p = store.write_lifecycle_register(_full_register(), Path(d) / "reg.json")
            self.assertTrue(p.exists())

    def test_in_repo_gitignored_writes(self):
        p = store.LIFECYCLE_DIR / "_test_reg.json"   # state/us_short/lifecycle/ is gitignored
        try:
            store.write_lifecycle_register(_full_register(), p)
            self.assertTrue(p.exists())
        finally:
            if p.exists():
                p.unlink()


class WriteRefusesNotClean(unittest.TestCase):
    def test_not_clean_not_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "reg.json"
            with self.assertRaises(store.LifecycleRegisterError):
                store.write_lifecycle_register(_not_clean_register(), p)
            self.assertFalse(p.exists())  # not-clean → no file written

    def test_guard_runs_before_validate(self):
        # a not-clean register AND a bad (relative) path → the §18.0 guard raises FIRST (PrivatePathError),
        # not the clean-gate — the guard is the outermost fail-closed floor
        with self.assertRaises(PrivatePathError):
            store.write_lifecycle_register(_not_clean_register(), "rel.json")


class LoadFailClosed(unittest.TestCase):
    def _write(self, d, reg):
        p = Path(d) / "reg.json"
        store.write_lifecycle_register(reg, p)
        return p

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            reg = _full_register(as_of="20260112")
            self.assertEqual(store.load_lifecycle_register(self._write(d, reg)), reg)

    def test_missing_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(store.StaleLifecycleArtifactError):
                store.load_lifecycle_register(Path(d) / "nope.json")

    def test_corrupt_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"
            p.write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(store.StaleLifecycleArtifactError):
                store.load_lifecycle_register(p)

    def test_not_clean_content_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "nc.json"
            p.write_text(json.dumps(_not_clean_register(), ensure_ascii=False), encoding="utf-8")  # plant not-clean
            with self.assertRaises(store.LifecycleRegisterError):
                store.load_lifecycle_register(p)

    def test_stale_as_of_ahead_of_decision_date_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, _full_register(as_of="20260301"))  # persisted register is AHEAD of the run
            with self.assertRaises(store.StaleLifecycleArtifactError):
                store.load_lifecycle_register(p, expected_as_of="20260112")

    def test_same_as_of_idempotent_rerun_ok(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, _full_register(as_of="20260112"))
            self.assertEqual(store.load_lifecycle_register(p, expected_as_of="20260112")["as_of"], "20260112")

    def test_forward_as_of_ok(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, _full_register(as_of="20260112"))
            self.assertEqual(store.load_lifecycle_register(p, expected_as_of="20260119")["as_of"], "20260112")

    def test_bad_expected_as_of_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, _full_register(as_of="20260112"))
            with self.assertRaises(store.StaleLifecycleArtifactError):
                store.load_lifecycle_register(p, expected_as_of="20260231")  # not a real date

    def test_load_relative_source_refused(self):
        # symmetric §18.0 guard: a CWD-dependent relative source is refused before any read
        with self.assertRaises(PrivatePathError):
            store.load_lifecycle_register("some_relative_register.json")

    def test_load_in_repo_nonignored_source_refused(self):
        # R-USSHORT-BATCH3-R2-LIFECYCLE-LOAD-PRIVATE-PATH-GUARD-GAP: a register planted at a tracked
        # (non-gitignored) in-repo path must be refused at LOAD (symmetric with write) — a private artifact
        # is read only from a provably-private source, so a tracked-path register can't enter the pipeline
        p = store.ROOT / "_lifecycle_load_guard_TMP.json"   # repo root → not under state/*/lifecycle/ → not gitignored
        try:
            p.write_text(json.dumps(_full_register()), encoding="utf-8")  # plant a VALID register at a tracked path
            with self.assertRaises(PrivatePathError):
                store.load_lifecycle_register(p)
        finally:
            if p.exists():
                p.unlink()


if __name__ == "__main__":
    unittest.main()
