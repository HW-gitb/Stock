# -*- coding: utf-8 -*-
"""Tests for US-short §12.2 shadow comparison persistence (engine/us_short_shadow_compare_store.py).

Covers: the FIRST shadow-compare persister wiring the §18.0 P0 private-path guard (relative / in-repo-nonignored
refused; gitignored in-repo + outside-repo allowed; guard BEFORE validate); refusing to persist a malformed
comparison / bad date (no file written); the dated record {as_of, comparison} contract; the canonical dated
bucket helper; the store-specific BUCKET / NAMESPACE guard (§2.1 桶名=as_of + A-vs-US lane isolation — in-repo must
be the canonical SHADOW_COMPARE_PRIVATE_DIR/shadow_comparison_<as_of>.json; model_paper_private / a_short / us_long
dirs + filename-date mismatch refused on write AND load; external non-canonical allowed); and load fail-closed on
a missing / corrupt-JSON / bad-record / bad-comparison / stale (as_of ahead of the run decision_date) artifact,
with idempotent same-date + forward (older) loads OK + symmetric load guard. Pure structure-over-IO; no
provider/live; no A-share crossing.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_shadow_compare as sc  # noqa: E402
import engine.us_short_shadow_compare_store as store  # noqa: E402
from engine.us_short_private_paths import PrivatePathError  # noqa: E402

POOL = [{"ticker": t, "blocks": {"momentum": 50, "theme": 50, "catalyst": 50}} for t in ("AAA", "BBB", "CCC")]


def _comparison():
    return sc.build_shadow_comparison(POOL, top_n=2)


def _bad_comparison():
    c = _comparison()
    c["boundary"]["shadow_counts_ship_gate"] = True  # breaks the frozen ship-gate-isolation boundary
    return c


class WriteGuardWiring(unittest.TestCase):
    def test_relative_path_refused(self):
        with self.assertRaises(PrivatePathError):
            store.write_shadow_comparison(_comparison(), "shadow_comparison.json", as_of="20260112")

    def test_in_repo_nonignored_refused(self):
        with self.assertRaises(PrivatePathError):
            store.write_shadow_comparison(_comparison(), store.ROOT / "shadow_x.json", as_of="20260112")

    def test_outside_repo_writes(self):
        with tempfile.TemporaryDirectory() as d:
            p = store.write_shadow_comparison(_comparison(), Path(d) / "c.json", as_of="20260112")
            self.assertTrue(p.exists())

    def test_in_repo_canonical_bucket_writes(self):
        p = store.shadow_comparison_path("20260112")  # canonical state/us_short/shadow_compare_private/shadow_comparison_20260112.json (gitignored)
        try:
            store.write_shadow_comparison(_comparison(), p, as_of="20260112")
            self.assertTrue(p.exists())
        finally:
            if p.exists():
                p.unlink()


class WriteRefusesMalformed(unittest.TestCase):
    def test_bad_comparison_not_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            with self.assertRaises(sc.ShadowCompareError):  # base — validate_shadow_comparison rejects
                store.write_shadow_comparison(_bad_comparison(), p, as_of="20260112")
            self.assertFalse(p.exists())  # malformed → no file written

    def test_bad_as_of_not_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            with self.assertRaises(store.ShadowCompareStoreError):
                store.write_shadow_comparison(_comparison(), p, as_of="20260231")  # not a real date
            self.assertFalse(p.exists())

    def test_guard_runs_before_validate(self):
        # a bad date AND a bad (relative) path → the §18.0 guard raises FIRST (PrivatePathError), not the
        # record gate — the guard is the outermost fail-closed floor
        with self.assertRaises(PrivatePathError):
            store.write_shadow_comparison(_comparison(), "rel.json", as_of="not-a-date")


class BucketPath(unittest.TestCase):
    def test_canonical_dated_bucket(self):
        p = store.shadow_comparison_path("20260112")
        self.assertEqual(p.parent, store.SHADOW_COMPARE_PRIVATE_DIR)
        self.assertEqual(p.name, "shadow_comparison_20260112.json")

    def test_bad_as_of_bucket_refused(self):
        for bad in ("20260231", "2026011", "abcd0112", 20260112, None):
            with self.assertRaises(store.ShadowCompareStoreError):
                store.shadow_comparison_path(bad)


class BucketNamespaceGuard(unittest.TestCase):
    """§2.1 桶名=as_of + A-vs-US lane isolation (BEYOND the §18.0 privacy guard): an in-repo path must be the
    canonical SHADOW_COMPARE_PRIVATE_DIR/shadow_comparison_<as_of>.json; a canonical-looking external filename must
    match as_of. The wrong-dir paths below are all gitignored (confirmed), so §18.0 passes and the bucket guard is
    what must reject them — and it fires before mkdir/write so no file is created."""

    def test_in_repo_filename_date_mismatch_refused(self):
        p = store.SHADOW_COMPARE_PRIVATE_DIR / "shadow_comparison_20260119.json"  # canonical dir, filename date != as_of
        with self.assertRaises(store.ShadowCompareStoreError):
            store.write_shadow_comparison(_comparison(), p, as_of="20260112")
        self.assertFalse(p.exists())

    def test_wrong_us_short_private_dir_refused(self):
        p = store.ROOT / "state" / "us_short" / "model_paper_private" / "shadow_comparison_20260112.json"
        with self.assertRaises(store.ShadowCompareStoreError):
            store.write_shadow_comparison(_comparison(), p, as_of="20260112")
        self.assertFalse(p.exists())

    def test_a_short_private_dir_refused(self):
        p = store.ROOT / "state" / "a_short" / "shadow_compare_private" / "shadow_comparison_20260112.json"
        with self.assertRaises(store.ShadowCompareStoreError):
            store.write_shadow_comparison(_comparison(), p, as_of="20260112")
        self.assertFalse(p.exists())

    def test_us_long_private_dir_refused(self):
        p = store.ROOT / "state" / "us_long" / "shadow_compare_private" / "shadow_comparison_20260112.json"
        with self.assertRaises(store.ShadowCompareStoreError):
            store.write_shadow_comparison(_comparison(), p, as_of="20260112")
        self.assertFalse(p.exists())

    def test_external_canonical_filename_date_mismatch_refused_on_write(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "shadow_comparison_20260119.json"  # canonical-LOOKING external name, date != as_of
            with self.assertRaises(store.ShadowCompareStoreError):
                store.write_shadow_comparison(_comparison(), p, as_of="20260112")
            self.assertFalse(p.exists())

    def test_load_filename_date_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "shadow_comparison_20260119.json"  # content as_of disagrees with the canonical-looking name
            p.write_text(json.dumps({"as_of": "20260112", "comparison": _comparison()}), encoding="utf-8")
            with self.assertRaises(store.ShadowCompareStoreError):
                store.load_shadow_comparison(p)

    def test_canonical_in_repo_bucket_roundtrip(self):
        p = store.shadow_comparison_path("20260112")  # positive control: the canonical in-repo bucket writes + loads
        try:
            store.write_shadow_comparison(_comparison(), p, as_of="20260112")
            self.assertEqual(store.load_shadow_comparison(p)["as_of"], "20260112")
        finally:
            if p.exists():
                p.unlink()


class LoadFailClosed(unittest.TestCase):
    def _write(self, d, as_of="20260112", comparison=None):
        p = Path(d) / "c.json"
        store.write_shadow_comparison(comparison or _comparison(), p, as_of=as_of)
        return p

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            comp = _comparison()
            rec = store.load_shadow_comparison(self._write(d, as_of="20260112", comparison=comp))
            self.assertEqual(rec, {"as_of": "20260112", "comparison": comp})

    def test_missing_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(store.StaleShadowComparisonError):
                store.load_shadow_comparison(Path(d) / "nope.json")

    def test_corrupt_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.json"
            p.write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(store.StaleShadowComparisonError):
                store.load_shadow_comparison(p)

    def test_bad_record_shape_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "nr.json"
            p.write_text(json.dumps({"as_of": "20260112"}), encoding="utf-8")  # missing comparison key
            with self.assertRaises(store.ShadowCompareStoreError):
                store.load_shadow_comparison(p)

    def test_bad_comparison_content_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bc.json"
            p.write_text(json.dumps({"as_of": "20260112", "comparison": _bad_comparison()}), encoding="utf-8")
            with self.assertRaises(sc.ShadowCompareError):
                store.load_shadow_comparison(p)

    def test_stale_as_of_ahead_of_decision_date_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, as_of="20260301")  # persisted comparison is AHEAD of the run
            with self.assertRaises(store.StaleShadowComparisonError):
                store.load_shadow_comparison(p, expected_as_of="20260112")

    def test_same_as_of_idempotent_rerun_ok(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, as_of="20260112")
            self.assertEqual(store.load_shadow_comparison(p, expected_as_of="20260112")["as_of"], "20260112")

    def test_forward_older_as_of_ok(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, as_of="20260112")  # an older week's comparison loaded for the accumulator
            self.assertEqual(store.load_shadow_comparison(p, expected_as_of="20260119")["as_of"], "20260112")

    def test_bad_expected_as_of_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, as_of="20260112")
            with self.assertRaises(store.StaleShadowComparisonError):
                store.load_shadow_comparison(p, expected_as_of="20260231")  # not a real date

    def test_load_relative_source_refused(self):
        with self.assertRaises(PrivatePathError):
            store.load_shadow_comparison("some_relative_comparison.json")

    def test_load_in_repo_nonignored_source_refused(self):
        # symmetric §18.0 guard: a comparison planted at a tracked (non-gitignored) in-repo path must be refused
        # at LOAD — a private artifact is read only from a provably-private source
        p = store.ROOT / "_shadow_compare_load_guard_TMP.json"  # repo root → not gitignored
        try:
            p.write_text(json.dumps({"as_of": "20260112", "comparison": _comparison()}), encoding="utf-8")
            with self.assertRaises(PrivatePathError):
                store.load_shadow_comparison(p)
        finally:
            if p.exists():
                p.unlink()


if __name__ == "__main__":
    unittest.main()
