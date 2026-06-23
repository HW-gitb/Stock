# -*- coding: utf-8 -*-
"""Tests for US-short §12.2 upgrade-gate forward-obs discover (engine/us_short_upgrade_obs_discover.py).

Covers: discovering clean LIVE-FORWARD buckets (≤ run_as_of) ascending + de-identified {as_of}; SKIP (fail-closed)
of a future / stale bucket (look-ahead, §12.2 ①③), a malformed-JSON bucket, a mis-bucketed (filename ≠ content
as_of) bucket, non-canonical filenames, and a non-live observation_kind (research_backfill / historical_replay —
§12.2 ① only live_forward counts; 12 backfilled buckets can't advance to due); empty / nonexistent dir → []; bad
run_as_of refused; and the integration into build_upgrade_eval. Pure IO; no provider/live; no A-share crossing.
"""
import datetime
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
import engine.us_short_upgrade_obs_discover as disc  # noqa: E402
import engine.us_short_upgrade_gate as ug  # noqa: E402

POOL = [{"ticker": t, "blocks": {"momentum": 50, "theme": 50, "catalyst": 50}} for t in ("AAA", "BBB", "CCC")]


def _comp():
    return sc.build_shadow_comparison(POOL, top_n=2)


def _write(d, as_of, observation_kind="live_forward"):
    p = Path(d) / ("shadow_comparison_%s.json" % as_of)  # canonical bucket name in an external (tempdir) location
    store.write_shadow_comparison(_comp(), p, as_of=as_of, observation_kind=observation_kind)
    return p


class Discover(unittest.TestCase):
    def test_discovers_clean_buckets_ascending_deidentified(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "20260105"); _write(d, "20260119"); _write(d, "20260112")
            obs = disc.discover_forward_observations("20260330", buckets_dir=d)
            self.assertEqual([o["as_of"] for o in obs], ["20260105", "20260112", "20260119"])
            self.assertTrue(all(set(o) == {"as_of"} for o in obs))  # de-identified — only the decision-week date

    def test_skips_future_bucket(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "20260105"); _write(d, "20260801")  # 0801 > run 0330 → look-ahead → skipped (§12.2 ①③)
            obs = disc.discover_forward_observations("20260330", buckets_dir=d)
            self.assertEqual([o["as_of"] for o in obs], ["20260105"])

    def test_skips_malformed_json(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "20260105")
            (Path(d) / "shadow_comparison_20260112.json").write_text("{bad json", encoding="utf-8")
            obs = disc.discover_forward_observations("20260330", buckets_dir=d)
            self.assertEqual([o["as_of"] for o in obs], ["20260105"])

    def test_skips_misbucketed(self):
        with tempfile.TemporaryDirectory() as d:
            # filename says 20260112 but content as_of is 20260105 → store bucket-check rejects → skipped
            (Path(d) / "shadow_comparison_20260112.json").write_text(
                json.dumps({"as_of": "20260105", "comparison": _comp(), "observation_kind": "live_forward"}), encoding="utf-8")
            self.assertEqual(disc.discover_forward_observations("20260330", buckets_dir=d), [])

    def test_skips_non_live_kind(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "20260105", observation_kind="live_forward")
            _write(d, "20260112", observation_kind="research_backfill")  # §2.1 research-only → not counted
            _write(d, "20260119", observation_kind="historical_replay")
            obs = disc.discover_forward_observations("20260330", buckets_dir=d)
            self.assertEqual([o["as_of"] for o in obs], ["20260105"])  # only the live_forward bucket counts

    def test_backfilled_non_live_cannot_advance_to_due(self):
        # 12 contract-clean but research_backfill buckets must NOT advance the upgrade clock (§12.2 ①)
        with tempfile.TemporaryDirectory() as d:
            for i in range(12):
                _write(d, (datetime.date(2025, 1, 6) + datetime.timedelta(days=7 * i)).strftime("%Y%m%d"),
                       observation_kind="research_backfill")
            obs = disc.discover_forward_observations("20260623", buckets_dir=d)
            self.assertEqual(obs, [])
            ev = ug.build_upgrade_eval(obs, as_of="20260623")
            self.assertFalse(ev["upgrade_review_due"])  # backfill can't fake 12 live weeks

    def test_ignores_noncanonical_filenames(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "20260105")
            (Path(d) / "notes.json").write_text("{}", encoding="utf-8")
            (Path(d) / "shadow_comparison_bad.json").write_text("{}", encoding="utf-8")
            obs = disc.discover_forward_observations("20260330", buckets_dir=d)
            self.assertEqual([o["as_of"] for o in obs], ["20260105"])

    def test_nonexistent_dir_empty(self):
        self.assertEqual(disc.discover_forward_observations("20260330", buckets_dir=str(Path(tempfile.gettempdir()) / "no_such_dir_xyz_12345")), [])

    def test_bad_run_as_of_refused(self):
        with self.assertRaises(disc.UpgradeObsDiscoverError):
            disc.discover_forward_observations("20260231")  # not a real date

    def test_integration_feeds_upgrade_gate(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(12):
                _write(d, (datetime.date(2026, 1, 5) + datetime.timedelta(days=7 * i)).strftime("%Y%m%d"))
            obs = disc.discover_forward_observations("20260801", buckets_dir=d)
            self.assertEqual(len(obs), 12)
            ev = ug.build_upgrade_eval(obs, as_of="20260801")
            self.assertTrue(ev["upgrade_review_due"])
            self.assertEqual(ev["decision_status"], ug.REVIEW_DUE_MARGIN_PENDING)  # current governance: no frozen margin


if __name__ == "__main__":
    unittest.main()
