# -*- coding: utf-8 -*-
"""Tests for the US-short weekend-pipeline run/input provenance reconciliation (batch4 round-2 slice 1a).

Closes R-USSHORT-BATCH4-PIPELINE-PIT-HEALTH-CALENDAR-GATE-GAP (provenance half): every CONSUMED input family's
as_of / observed_at / price-basis / session / adjustment is reconciled against the ONE §2.1 canonical clock,
fail-closed on future / stale / cross-run / mixed-session / mixed-adjustment / malformed input. Exhaustive
reverse matrix (each guard × a wrong value) + positive controls. Pure/offline; no provider/live.
"""
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_run_provenance import (  # noqa: E402
    EXPECTED_FAMILIES,
    PRICE_BEARING_FAMILIES,
    RunProvenanceError,
    reconcile_run_provenance,
)

_NOW = datetime(2026, 6, 13, 10, 0)   # Sat 10:00 ET run wall clock
_DD = "20260615"                       # canonical decision_date (upcoming Mon)
_PB = "20260612"                       # price basis = prior Fri
_RUN = "20260613"                      # run_date (Sat)
_OBS = "2026-06-13T08:00:00"           # an observation safely before the run wall clock


_EMPTY_PAYLOADS = {"universe": [], "candidate_pass2_signals": {}, "per_ticker_analysis": {},
                   "selection_inputs": {"per_ticker": {}}}


def _manifest(row_count=0, **over):
    price = {"as_of": _DD, "observed_at": _OBS, "price_basis_date": _PB,
             "session": "RTH", "adjustment": "split_div_adjusted", "row_count": row_count}
    nonprice = {"as_of": _DD, "observed_at": _OBS, "price_basis_date": None, "session": None,
                "adjustment": None, "row_count": row_count}
    m = {"as_of": _DD, "price_basis_date": _PB,
         "families": {"universe": dict(price), "per_ticker_analysis": dict(price),
                      "candidate_pass2_signals": dict(nonprice), "selection_inputs": dict(nonprice)}}
    m.update(over)
    return m


def _run(m, payloads=None, **clock):
    kw = {"now_et": _NOW, "decision_date": _DD, "price_basis_date": _PB, "run_date": _RUN,
          "payloads": _EMPTY_PAYLOADS if payloads is None else payloads}
    kw.update(clock)
    return reconcile_run_provenance(m, **kw)


class PositiveControl(unittest.TestCase):
    def test_clean_manifest_reconciles(self):
        out = _run(_manifest())
        self.assertEqual(out["as_of"], _DD)
        self.assertEqual(out["price_basis_date"], _PB)
        self.assertEqual(out["run_date"], _RUN)
        self.assertEqual(out["session"], "RTH")
        self.assertEqual(out["adjustment"], "split_div_adjusted")
        self.assertEqual(set(out["families"]), EXPECTED_FAMILIES)

    def test_observed_at_equal_to_now_is_allowed(self):   # boundary: observed_at == now_et is NOT future
        m = _manifest()
        for fam in m["families"].values():
            fam["observed_at"] = _NOW.isoformat()
        self.assertEqual(_run(m)["session"], "RTH")

    def test_families_set_is_exactly_the_consumed_families(self):
        self.assertEqual(EXPECTED_FAMILIES, {"universe", "per_ticker_analysis",
                                             "candidate_pass2_signals", "selection_inputs"})
        self.assertTrue(PRICE_BEARING_FAMILIES <= EXPECTED_FAMILIES)


class ResolverClockGuards(unittest.TestCase):
    def test_non_yyyymmdd_resolver_dates_rejected(self):
        for bad in ({"decision_date": "2026-06-15"}, {"price_basis_date": "20261301"}, {"run_date": "bad"}):
            with self.assertRaises(RunProvenanceError):
                _run(_manifest(), **bad)

    def test_illegal_clock_order_rejected(self):
        # run_date after decision_date violates price_basis <= run <= decision
        with self.assertRaises(RunProvenanceError):
            _run(_manifest(as_of="20260615"), run_date="20260616")

    def test_now_et_must_be_naive_datetime(self):
        with self.assertRaises(RunProvenanceError):
            _run(_manifest(), now_et="2026-06-13T10:00:00")
        from datetime import timezone
        with self.assertRaises(RunProvenanceError):
            _run(_manifest(), now_et=datetime(2026, 6, 13, 10, 0, tzinfo=timezone.utc))


class ManifestShape(unittest.TestCase):
    def test_non_dict_manifest_rejected(self):
        with self.assertRaises(RunProvenanceError):
            _run(["not", "a", "dict"])

    def test_missing_or_extra_top_key_rejected(self):
        m = _manifest(); m.pop("price_basis_date")
        with self.assertRaises(RunProvenanceError):
            _run(m)
        m2 = _manifest(); m2["EXTRA"] = 1
        with self.assertRaises(RunProvenanceError):
            _run(m2)

    def test_missing_family_rejected(self):
        m = _manifest(); del m["families"]["selection_inputs"]
        with self.assertRaises(RunProvenanceError):
            _run(m)

    def test_extra_family_rejected(self):
        m = _manifest(); m["families"]["unexpected_family"] = dict(m["families"]["universe"])
        with self.assertRaises(RunProvenanceError):
            _run(m)

    def test_family_wrong_keys_rejected(self):
        m = _manifest(); m["families"]["universe"].pop("adjustment")
        with self.assertRaises(RunProvenanceError):
            _run(m)
        m2 = _manifest(); m2["families"]["candidate_pass2_signals"]["EXTRA"] = 1
        with self.assertRaises(RunProvenanceError):
            _run(m2)


class CrossRun(unittest.TestCase):
    def test_top_level_as_of_must_equal_decision_date(self):
        with self.assertRaises(RunProvenanceError):
            _run(_manifest(as_of="20990101"))

    def test_top_level_price_basis_must_equal_canonical(self):
        with self.assertRaises(RunProvenanceError):
            _run(_manifest(price_basis_date="20260605"))

    def test_per_family_as_of_must_equal_decision_date(self):
        # the exact finding vector: a single family tagged for another run fails closed
        for fam in EXPECTED_FAMILIES:
            m = _manifest(); m["families"][fam]["as_of"] = "20990101"
            with self.assertRaises(RunProvenanceError):
                _run(m)


class FutureAndStale(unittest.TestCase):
    def test_future_observed_at_rejected(self):
        for fam in EXPECTED_FAMILIES:
            m = _manifest(); m["families"][fam]["observed_at"] = "2099-01-01T00:00:00"
            with self.assertRaises(RunProvenanceError):
                _run(m)

    def test_non_iso_observed_at_rejected(self):
        m = _manifest(); m["families"]["universe"]["observed_at"] = "20260613"
        with self.assertRaises(RunProvenanceError):
            _run(m)

    def test_tz_aware_observed_at_rejected(self):
        m = _manifest(); m["families"]["universe"]["observed_at"] = "2026-06-13T08:00:00+00:00"
        with self.assertRaises(RunProvenanceError):
            _run(m)

    def test_stale_price_basis_in_price_family_rejected(self):
        m = _manifest(); m["families"]["per_ticker_analysis"]["price_basis_date"] = "20260605"
        with self.assertRaises(RunProvenanceError):
            _run(m)


class PriceLineage(unittest.TestCase):
    def test_price_family_missing_session_or_adjustment_rejected(self):
        for key in ("session", "adjustment"):
            for bad in (None, "", "   "):
                m = _manifest(); m["families"]["universe"][key] = bad
                with self.assertRaises(RunProvenanceError):
                    _run(m)

    def test_non_price_family_must_not_declare_price_lineage(self):
        for key, bad in (("price_basis_date", _PB), ("session", "RTH"), ("adjustment", "split_div_adjusted")):
            m = _manifest(); m["families"]["selection_inputs"][key] = bad
            with self.assertRaises(RunProvenanceError):
                _run(m)

    def test_illegal_session_rejected_even_if_consistent(self):
        # both price families AGREE on ETH, but the official price clock is RTH — equal-but-illegal still fails
        m = _manifest()
        for fam in ("universe", "per_ticker_analysis"):
            m["families"][fam]["session"] = "ETH"
        with self.assertRaises(RunProvenanceError):
            _run(m)

    def test_illegal_adjustment_rejected_even_if_consistent(self):
        m = _manifest()
        for fam in ("universe", "per_ticker_analysis"):
            m["families"][fam]["adjustment"] = "unknown_raw"
        with self.assertRaises(RunProvenanceError):
            _run(m)

    def test_mixed_session_across_price_families_rejected(self):
        m = _manifest(); m["families"]["per_ticker_analysis"]["session"] = "ETH"   # universe RTH ≠ analysis ETH
        with self.assertRaises(RunProvenanceError):
            _run(m)

    def test_mixed_adjustment_across_price_families_rejected(self):
        m = _manifest(); m["families"]["per_ticker_analysis"]["adjustment"] = "unadjusted"
        with self.assertRaises(RunProvenanceError):
            _run(m)


class PayloadBinding(unittest.TestCase):
    """R-USSHORT-BATCH4-PIPELINE-... (①a): the manifest is BOUND to the actual payload — per-family row_count must
    match the real payload, and a payload row whose OWN as_of/observed_at contradicts the manifest fails closed
    (the clean-manifest/dirty-payload guard)."""

    def _payloads(self, **ov):
        p = {"universe": [{"ticker": "AAPL"}], "candidate_pass2_signals": {"AAPL": {}},
             "per_ticker_analysis": {"AAPL": {}}, "selection_inputs": {"per_ticker": {"AAPL": {}}}}
        p.update(ov)
        return p

    def test_row_count_mismatch_rejected(self):
        m = _manifest(); m["families"]["universe"]["row_count"] = 1   # manifest says 1, the empty payload has 0
        with self.assertRaises(RunProvenanceError):
            _run(m)

    def test_dirty_row_as_of_rejected(self):
        # the exact probe: a clean manifest but a universe payload row carrying its OWN as_of=2099
        m = _manifest(row_count=1)
        with self.assertRaises(RunProvenanceError):
            _run(m, payloads=self._payloads(universe=[{"ticker": "AAPL", "as_of": "20990101"}]))

    def test_dirty_row_observed_at_rejected(self):
        m = _manifest(row_count=1)
        with self.assertRaises(RunProvenanceError):
            _run(m, payloads=self._payloads(per_ticker_analysis={"AAPL": {"observed_at": "2099-01-01T00:00:00"}}))

    def test_payload_bound_positive_control(self):
        m = _manifest(row_count=1)
        out = _run(m, payloads=self._payloads(universe=[{"ticker": "AAPL", "as_of": _DD, "observed_at": _OBS}]))
        self.assertEqual(out["as_of"], _DD)

    def test_payloads_closed_world_rejected(self):
        with self.assertRaises(RunProvenanceError):
            _run(_manifest(), payloads={"universe": []})   # missing families


if __name__ == "__main__":
    unittest.main()
