# -*- coding: utf-8 -*-
"""Tests for US-short §11.2 ④ / §21 price-clock consistency (engine/us_short_price_clock.py).

Covers: the frozen field set; session_scope == RTH; strict real dates; the ordering (price_data_through STRICTLY
before decision_date = a prior closed day, stale/forward refused; news window within [price_data, decision]);
the optional §3.5 machine-layer as_of / session cross-check; and malformed fail-closed (non-dict, wrong field
set, mixed-type keys). Pure/offline; no provider/live; no A-share crossing.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_price_clock as pc  # noqa: E402

FIELDS = json.loads((ROOT / "presets" / "us_short_weekly_report_contract_20260620.json").read_text(encoding="utf-8"))["price_clock"]["fields"]


def _clock(pdt="20260619", nwt="20260619", session="RTH", dd="20260622"):
    return {"price_data_through": pdt, "news_window_through": nwt, "session_scope": session, "decision_date": dd}


class Valid(unittest.TestCase):
    def test_canonical_clock_passes(self):
        pc.validate_price_clock(_clock())  # Fri price, news through Fri, Mon decision

    def test_news_window_boundaries_ok(self):  # positive controls: news == price day, and news == decision day
        pc.validate_price_clock(_clock(nwt="20260619"))   # == price_data_through
        pc.validate_price_clock(_clock(nwt="20260620"))   # weekend, between
        pc.validate_price_clock(_clock(nwt="20260622"))   # == decision_date (Mon early news)

    def test_fields_from_frozen_contract(self):
        self.assertEqual(set(_clock()), set(FIELDS))


class SessionScope(unittest.TestCase):
    def test_non_rth_refused(self):
        for bad in ("ETH", "rth", "RTH ", "", "PRE", None):
            with self.assertRaises(pc.PriceClockError, msg=repr(bad)):
                pc.validate_price_clock(_clock(session=bad))


class Dates(unittest.TestCase):
    def test_non_real_dates_refused(self):
        for bad in ("20260231", "2026-06-19", "x", None, 20260619, "2026061"):
            with self.assertRaises(pc.PriceClockError, msg="pdt=%r" % (bad,)):
                pc.validate_price_clock(_clock(pdt=bad))
            with self.assertRaises(pc.PriceClockError, msg="dd=%r" % (bad,)):
                pc.validate_price_clock(_clock(dd=bad))
            with self.assertRaises(pc.PriceClockError, msg="nwt=%r" % (bad,)):
                pc.validate_price_clock(_clock(nwt=bad))

    def test_unicode_digit_dates_refused(self):  # R-USSHORT-BATCH3-PRICE-CLOCK-DATE-ASCII-GAP: isascii() guard
        self.assertTrue(pc._strict_yyyymmdd("20260619"))  # ASCII positive control
        for bad in ("٢٠٢٦٠٦١٩", "２０２６０６１９"):  # Arabic-Indic / fullwidth "20260619" — pass isdigit() but not isascii()
            self.assertFalse(pc._strict_yyyymmdd(bad), repr(bad))
            with self.assertRaises(pc.PriceClockError):
                pc.validate_price_clock(_clock(pdt=bad))


class Ordering(unittest.TestCase):
    def test_price_data_must_be_strictly_before_decision(self):
        with self.assertRaises(pc.PriceClockError):  # == decision day → stale/forward
            pc.validate_price_clock(_clock(pdt="20260622", nwt="20260622", dd="20260622"))
        with self.assertRaises(pc.PriceClockError):  # after decision day → forward leak
            pc.validate_price_clock(_clock(pdt="20260623", nwt="20260623", dd="20260622"))

    def test_news_window_must_be_within_range(self):
        with self.assertRaises(pc.PriceClockError):  # news after decision day → future news
            pc.validate_price_clock(_clock(nwt="20260623"))
        with self.assertRaises(pc.PriceClockError):  # news older than price data
            pc.validate_price_clock(_clock(pdt="20260619", nwt="20260618"))


class MachineCrossCheck(unittest.TestCase):
    def test_as_of_must_match_when_given(self):
        pc.validate_price_clock(_clock(), machine_as_of="20260619")  # matches price_data_through
        with self.assertRaises(pc.PriceClockError):
            pc.validate_price_clock(_clock(), machine_as_of="20260618")

    def test_session_must_match_when_given(self):
        pc.validate_price_clock(_clock(), machine_session="RTH")
        with self.assertRaises(pc.PriceClockError):
            pc.validate_price_clock(_clock(), machine_session="ETH")

    def test_none_machine_skips_cross_check(self):  # positive control: no machine context → internal-only
        pc.validate_price_clock(_clock(), machine_as_of=None, machine_session=None)


class MalformedFailsClosed(unittest.TestCase):
    def test_non_dict_refused(self):
        for bad in (None, "x", 5, []):
            with self.assertRaises(pc.PriceClockError, msg=repr(bad)):
                pc.validate_price_clock(bad)

    def test_wrong_field_set_refused(self):
        d = _clock(); del d["session_scope"]
        with self.assertRaises(pc.PriceClockError):
            pc.validate_price_clock(d)
        d2 = _clock(); d2["extra"] = "x"
        with self.assertRaises(pc.PriceClockError):
            pc.validate_price_clock(d2)

    def test_mixed_type_key_is_sanctioned_error(self):  # frozen str fields + a non-string key → PriceClockError, not raw TypeError
        d = _clock(); d[5] = "x"
        with self.assertRaises(pc.PriceClockError):
            pc.validate_price_clock(d)


if __name__ == "__main__":
    unittest.main()
