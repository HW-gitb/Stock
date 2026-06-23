# -*- coding: utf-8 -*-
"""Tests for US-short §13 lifecycle runtime banner slice 2c-first-cut (engine/us_short_lifecycle_render.py).

Covers: the due-scan banner content (no-due / due-items-listed / upgrade-eligible surfaced-not-acted);
fail-closed on the FULL eval-result contract (non-dict, missing/mismatched due_count, negative/zero/too-small
total, non-int/bool/emoji ids, upgrade-not-due, non-ASCII/invalid as_of → UNAVAILABLE, never a misleading
0-due banner, never a silent empty string); the GBK-safe / ASCII-guaranteed property (every banner — incl.
malformed non-ASCII input — encodes on GBK and never leaks the bad bytes); and an integration banner from
evaluate_lifecycle. No provider/live; no A-share crossing. The banner module has NO jsonschema dependency, so
this suite runs even when jsonschema is unavailable (only the evaluate_lifecycle integration test skips).
"""
import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_lifecycle_render as render  # noqa: E402  (standalone — no jsonschema)

CAL = json.loads((ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json").read_text(encoding="utf-8"))
GOV_TITLE = {g["number"]: g["title"] for g in CAL["calibration_items"]}
EMOJI = "\U0001F389"  # 🎉 — a non-ASCII, non-GBK-encodable code point


def _weekly_dates(n):
    base = date(2026, 1, 5)  # a Monday
    return [(base + timedelta(weeks=i)).strftime("%Y%m%d") for i in range(n)]


def _full_register(as_of="20260112"):
    return {"schema_name": "us_short_lifecycle_register", "schema_version": "1.0.0", "as_of": as_of,
            "items": [{"number": g["number"], "title": GOV_TITLE[g["number"]], "forward_observations": {},
                       "secondary_condition_met": False, "upgrade_margin_frozen": False, "due": False}
                      for g in CAL["calibration_items"]]}


def _res(**kw):
    """A base-VALID evaluate_lifecycle result; override fields to build adversarial cases."""
    base = {"as_of": "20260112", "total_items": 39, "due_count": 1, "due_items": [1], "upgrade_eligible_items": []}
    base.update(kw)
    return base


class BannerContent(unittest.TestCase):
    def test_no_due(self):
        b = render.lifecycle_banner(_res(due_count=0, due_items=[]))
        self.assertIn("0/39", b)
        self.assertIn("due for review", b)

    def test_due_items_listed_with_user_decision_caveat(self):
        b = render.lifecycle_banner(_res(due_count=2, due_items=[1, 7]))
        self.assertIn("2/39", b)
        self.assertIn("#1", b)
        self.assertIn("#7", b)
        self.assertIn("DUE", b)
        self.assertIn("USER decision", b)

    def test_upgrade_eligible_surfaced_not_acted(self):
        b = render.lifecycle_banner(_res(due_count=1, due_items=[1], upgrade_eligible_items=[1]))
        self.assertIn("upgrade-eligible", b)
        self.assertIn("never auto-production", b)

    def test_as_of_absent_renders_unknown(self):
        r = _res(due_count=0, due_items=[])
        del r["as_of"]
        self.assertIn("as_of=unknown", render.lifecycle_banner(r))


class BannerContractFailsClosed(unittest.TestCase):
    """R-USSHORT-BATCH3-R2-LIFECYCLE-BANNER-FAILCLOSED-GBK-GAP: the FULL eval-result contract is validated;
    any violation → the conservative UNAVAILABLE banner (never a misleading normal banner)."""

    def _u(self, label, result):
        self.assertEqual(render.lifecycle_banner(result),
                         render._UNAVAILABLE, "%s should be UNAVAILABLE" % label)

    def test_non_dict(self):
        for bad in (None, "x", 5, [], True):
            self._u(repr(bad), bad)

    def test_due_count_missing_or_mismatched(self):
        r = _res(due_count=0, due_items=[1]); del r["due_count"]
        self._u("missing due_count", r)
        self._u("due_count too high", _res(due_count=2, due_items=[1]))
        self._u("due_count too low", _res(due_count=1, due_items=[1, 7]))
        self._u("due_count negative", _res(due_count=-1, due_items=[]))

    def test_total_items_invalid(self):
        self._u("total negative", _res(total_items=-1, due_count=0, due_items=[]))
        self._u("total zero", _res(total_items=0, due_count=0, due_items=[]))
        self._u("total non-int", _res(total_items="39", due_count=0, due_items=[]))
        self._u("total bool", _res(total_items=True, due_count=0, due_items=[]))
        self._u("len(due) > total", _res(total_items=2, due_count=3, due_items=[1, 2, 3]))

    def test_bad_due_ids(self):
        self._u("id out of range", _res(due_count=1, due_items=[99]))
        self._u("id non-int", _res(due_count=1, due_items=["1"]))
        self._u("id bool", _res(due_count=1, due_items=[True]))
        self._u("id emoji", _res(due_count=1, due_items=[EMOJI]))
        self._u("id duplicate", _res(due_count=2, due_items=[1, 1]))
        self._u("due not a list", _res(due_count=0, due_items="no"))

    def test_bad_upgrade_ids(self):
        self._u("upgrade non-int", _res(due_count=1, due_items=[1], upgrade_eligible_items=["1"]))
        self._u("upgrade emoji", _res(due_count=1, due_items=[1], upgrade_eligible_items=[EMOJI]))
        self._u("upgrade not due", _res(due_count=1, due_items=[1], upgrade_eligible_items=[2]))
        self._u("upgrade not a list", _res(due_count=1, due_items=[1], upgrade_eligible_items="no"))

    def test_bad_as_of(self):
        self._u("as_of emoji", _res(due_count=0, due_items=[], as_of=EMOJI))
        self._u("as_of wrong len", _res(due_count=0, due_items=[], as_of="2026"))
        self._u("as_of impossible date", _res(due_count=0, due_items=[], as_of="20260231"))
        self._u("as_of int", _res(due_count=0, due_items=[], as_of=20260112))

    def test_never_silent_empty_string(self):
        for bad in (None, {}, _res(due_count=9, due_items=[])):
            self.assertTrue(render.lifecycle_banner(bad).strip())


class BannerAsciiGbkSafe(unittest.TestCase):
    """§13 GBK-safe 运行时横幅: every banner (valid OR malformed-non-ASCII input) encodes on GBK and never
    leaks non-ASCII bytes into the output."""

    def test_valid_and_malformed_paths_encode_gbk_and_ascii(self):
        cases = [None, {}, _res(due_count=0, due_items=[]), _res(due_count=2, due_items=[1, 7]),
                 _res(due_count=1, due_items=[1], upgrade_eligible_items=[1]),
                 _res(due_count=1, due_items=[EMOJI]), _res(due_count=0, due_items=[], as_of=EMOJI),
                 _res(due_count=1, due_items=[1], upgrade_eligible_items=[EMOJI])]
        for c in cases:
            b = render.lifecycle_banner(c)
            b.encode("gbk")     # GBK-safe (must not raise)
            b.encode("ascii")   # ASCII-guaranteed (must not raise)
            self.assertNotIn(EMOJI, b)  # malformed non-ASCII input must never leak into the banner


class BannerIntegration(unittest.TestCase):
    def test_banner_from_evaluate_lifecycle(self):
        try:
            import engine.us_short_lifecycle_eval as lc  # imports jsonschema — skip if the runtime lacks it
        except ImportError as e:  # pragma: no cover - environment-dependent
            self.skipTest("evaluate_lifecycle unavailable (%s)" % e)
        reg = _full_register("20260112")
        item = next(it for it in reg["items"] if it["number"] == 1)  # #1 scoring weight: min 12, no secondary
        item["forward_observations"] = {d: 1 for d in _weekly_dates(12)}
        item["due"] = True
        b = render.lifecycle_banner(lc.evaluate_lifecycle(reg))
        self.assertIn("#1", b)
        self.assertIn("DUE", b)
        b.encode("gbk")
        b.encode("ascii")


if __name__ == "__main__":
    unittest.main()
