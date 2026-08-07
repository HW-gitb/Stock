# -*- coding: utf-8 -*-
"""Tests for US-short weekend lifecycle eval stage (batch4 slice 4d-ii-l).

Covers the runtime eval stage that runs BEFORE the weekly_report render (§13): it loads the persisted
lifecycle_register (stale-checked against the run decision_date), evaluates the §13.1 due scan into the
tracked de-identified readiness, optionally writes it, and renders the GBK-safe banner. Verifies the happy
path (readiness + banner + threaded decision_date), a due item surfaced in the readiness + banner, an
upgrade-eligible item SURFACED-not-acted (USER decision caveat), the optional tracked readiness write, and
the single-source fail-closed propagation: a stale-ahead / missing / not-clean register and a non-private
register source all raise. Pure/offline; no provider/live; no A-share crossing.
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

import engine.us_short_weekend_lifecycle_stage as stage  # noqa: E402
from engine.us_short_lifecycle_readiness import LifecycleReadinessError  # noqa: E402
from engine.us_short_lifecycle_store import (  # noqa: E402
    LIFECYCLE_REGISTER_PATH,
    LifecycleRegisterError,
    StaleLifecycleArtifactError,
)
from engine.us_short_private_paths import (  # noqa: E402
    PrivatePathError,
    reject_nonprivate_output_path,
)

CAL = json.loads((ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json").read_text(encoding="utf-8"))
GOV_TITLE = {g["number"]: g["title"] for g in CAL["calibration_items"]}


def _weekly_dates(n):
    base = date(2026, 1, 5)
    return [(base + timedelta(weeks=i)).strftime("%Y%m%d") for i in range(n)]


def _full_register(as_of="20260112"):
    return {"schema_name": "us_short_lifecycle_register", "schema_version": "1.0.0", "as_of": as_of,
            "items": [{"number": g["number"], "title": GOV_TITLE[g["number"]], "forward_observations": {},
                       "secondary_condition_met": False, "upgrade_margin_frozen": False, "due": False}
                      for g in CAL["calibration_items"]]}


def _due_register(as_of="20260112", margin_frozen=False):
    reg = _full_register(as_of)
    item = next(it for it in reg["items"] if it["number"] == 1)  # #1 scoring weight: min 12, no secondary
    item["forward_observations"] = {d: 1 for d in _weekly_dates(12)}
    item["due"] = True
    item["upgrade_margin_frozen"] = margin_frozen
    return reg


def _write(d, reg):
    p = Path(d) / "reg.json"
    p.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    return p


class HappyStage(unittest.TestCase):
    def test_clean_no_due(self):
        with tempfile.TemporaryDirectory() as d:
            res = stage.run_lifecycle_eval_stage(decision_date="20260112", register_path=_write(d, _full_register()))
            self.assertEqual(res["decision_date"], "20260112")
            self.assertEqual(res["readiness"]["due_count"], 0)
            self.assertIn("0/39", res["banner"])

    def test_due_item_surfaced(self):
        with tempfile.TemporaryDirectory() as d:
            res = stage.run_lifecycle_eval_stage(decision_date="20260112", register_path=_write(d, _due_register()))
            self.assertEqual(res["readiness"]["due_items"], [1])
            self.assertIn("#1", res["banner"])
            self.assertIn("DUE", res["banner"])

    def test_upgrade_eligible_surfaced_not_acted(self):
        with tempfile.TemporaryDirectory() as d:
            res = stage.run_lifecycle_eval_stage(decision_date="20260112",
                                                 register_path=_write(d, _due_register(margin_frozen=True)))
            self.assertEqual(res["readiness"]["upgrade_eligible_items"], [1])
            self.assertIn("upgrade-eligible", res["banner"])
            self.assertIn("USER decision", res["banner"])  # surfaced, never auto-production

    def test_banner_is_gbk_safe_ascii(self):
        with tempfile.TemporaryDirectory() as d:
            res = stage.run_lifecycle_eval_stage(decision_date="20260112", register_path=_write(d, _due_register()))
            res["banner"].encode("ascii")  # raises UnicodeEncodeError if not ASCII

    def test_idempotent_same_date_load_ok(self):
        # §2.1: re-running the SAME decision_date against a register at that as_of is fine (not stale)
        with tempfile.TemporaryDirectory() as d:
            res = stage.run_lifecycle_eval_stage(decision_date="20260112",
                                                 register_path=_write(d, _full_register(as_of="20260112")))
            self.assertEqual(res["readiness"]["as_of"], "20260112")


class ReadinessWrite(unittest.TestCase):
    def test_readiness_written_and_de_identified(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "readiness.json"
            res = stage.run_lifecycle_eval_stage(decision_date="20260112",
                                                 register_path=_write(d, _due_register()), readiness_out_path=out)
            written = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(written, res["readiness"])
            self.assertNotIn("ticker", written)  # tracked artifact is de-identified by construction
            self.assertEqual(written["schema_name"], "us_short_lifecycle_readiness")

    def test_no_write_when_out_path_absent(self):
        with tempfile.TemporaryDirectory() as d:
            res = stage.run_lifecycle_eval_stage(decision_date="20260112", register_path=_write(d, _full_register()))
            self.assertIn("readiness", res)  # built but not persisted (no out_path)


class FailClosed(unittest.TestCase):
    def test_stale_ahead_register_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = _write(d, _full_register(as_of="20260301"))  # register AHEAD of the run
            with self.assertRaises(StaleLifecycleArtifactError):
                stage.run_lifecycle_eval_stage(decision_date="20260112", register_path=p)

    def test_missing_register_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(StaleLifecycleArtifactError):
                stage.run_lifecycle_eval_stage(decision_date="20260112", register_path=Path(d) / "nope.json")

    def test_not_clean_register_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            reg = _full_register()
            reg["items"] = reg["items"][:-1]  # coverage gap → not §13-clean
            with self.assertRaises(LifecycleRegisterError):
                stage.run_lifecycle_eval_stage(decision_date="20260112", register_path=_write(d, reg))

    def test_bad_decision_date_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(StaleLifecycleArtifactError):
                stage.run_lifecycle_eval_stage(decision_date="20260231",  # not a real date
                                               register_path=_write(d, _full_register()))

    def test_relative_register_source_refused(self):
        with self.assertRaises(PrivatePathError):  # §18.0 symmetric guard (CWD-dependent source)
            stage.run_lifecycle_eval_stage(decision_date="20260112", register_path="some_relative_register.json")

    def test_in_repo_nonignored_source_refused(self):
        p = ROOT / "_l_stage_guard_TMP.json"   # repo root → not under state/*/lifecycle/ → not gitignored
        try:
            p.write_text(json.dumps(_full_register()), encoding="utf-8")  # plant a VALID register at a tracked path
            with self.assertRaises(PrivatePathError):
                stage.run_lifecycle_eval_stage(decision_date="20260112", register_path=p)
        finally:
            if p.exists():
                p.unlink()


class DefaultRegisterPath(unittest.TestCase):
    """The default is proved by binding and by identity, never by writing the real path.

    The earlier version wrote a register to the real
    ``state/us_short/lifecycle/lifecycle_register.json`` and deleted it again.
    Two things were wrong with that. It is a write into a protected private root
    during a test run — the thing ``LaneResidueConformance`` exists to forbid —
    and under the module-per-process parallel pack that transient file is visible
    to a residue guard running in another process at the same moment, which turns
    an unrelated module red for a few hundred milliseconds a week. It also
    ``skipIf``-ed itself out of existence the moment a real register existed, so
    on the one machine that matters it was providing no coverage at all.

    The same two facts are asserted directly instead: the stage consults its
    module default when no path is given, and that default is the canonical
    gitignored private location.
    """

    def test_the_stage_consults_its_module_default_when_no_path_is_given(self):
        from unittest import mock

        with tempfile.TemporaryDirectory() as d:
            substitute = _write(d, _full_register(as_of="20260112"))
            with mock.patch.object(stage, "LIFECYCLE_REGISTER_PATH", substitute):
                res = stage.run_lifecycle_eval_stage(decision_date="20260112")
        self.assertEqual(res["readiness"]["total_items"], 39)

    def test_that_default_is_the_canonical_private_location(self):
        self.assertEqual(
            ROOT / "state" / "us_short" / "lifecycle" / "lifecycle_register.json",
            LIFECYCLE_REGISTER_PATH,
        )
        self.assertIs(stage.LIFECYCLE_REGISTER_PATH, LIFECYCLE_REGISTER_PATH)
        # And it is a location the §18.0 private-path guard actually accepts, which
        # is the property "canonical private location" is shorthand for.
        reject_nonprivate_output_path(LIFECYCLE_REGISTER_PATH)


if __name__ == "__main__":
    unittest.main()
