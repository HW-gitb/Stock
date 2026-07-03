# -*- coding: utf-8 -*-
"""US-short status-source OFFLINE layer (batch5 Cut 1, slice 1a) — engine tests.

Covers: triangulation (flag set / per-flag source / gate policy == the frozen binding + eligibility gate);
per-flag resolution incl. the full/partial-coverage absence rule and the bankruptcy positive_detection_only
policy; the cheap_eligible integration (unknown stays unknown -> conservative reject; bankruptcy unscreened
does NOT reject); failure classification (critical-all-fail -> block, best-effort sec_8k non-critical); and
validate_status_record anti-fabrication. No network/provider call (pure offline)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_status_source as ss
from engine.us_short_eligibility_gate import (
    _V1_DISQUALIFYING_STATUS_FLAGS,
    cheap_eligible,
    load_eligibility_governance,
)

GOVERNANCE = load_eligibility_governance(ROOT / "presets" / "us_short_eligibility_governance_20260624.json")
BINDING = json.loads(
    (ROOT / "docs" / "us_short_batch5_status_source_binding_20260629.json").read_text(encoding="utf-8"))

# PIT: observed_at MUST be on or before as_of (the decision clock) — a status observation from after the
# decision is look-ahead (design §3.3/§3.5/§62 `observed_at <= 运行时刻`). The fixture is same-day valid.
AS_OF, OBSERVED_AT = "2026-06-30", "2026-06-30T12:00:00+00:00"


def _ref(coverage="full", listings=None, *, observed_at=OBSERVED_AT):
    return {"observed": True, "observed_at": observed_at, "coverage": coverage,
            "active_listings": listings if listings is not None else {
                "AAPL": {"active": True, "primary_exchange": "NASDAQ"},
                "OTCX": {"active": True, "primary_exchange": "OTC"},
                "DEAD": {"active": False, "primary_exchange": "NYSE"}}}


def _halt(symbols=("HALT",), *, observed_at=OBSERVED_AT):
    return {"observed": True, "observed_at": observed_at, "halted_symbols": list(symbols)}


def _bank(by=None, *, observed_at=OBSERVED_AT):
    return {"observed": True, "observed_at": observed_at, "lookback_window": "P90D",
            "by_ticker": by if by is not None else {
                "BANKR": {"screen_status": "bankrupt_8k_found", "filing_accession": "0001140361-26-000001"},
                "AAPL": {"screen_status": "screened_no_filing"}}}


def _sec_submissions(*, forms, filing_dates, accessions, items):
    return {"filings": {"recent": {
        "form": list(forms),
        "filingDate": list(filing_dates),
        "accessionNumber": list(accessions),
        "items": list(items),
    }}}


def _record(ticker, **kw):
    return ss.resolve_status_record(ticker, as_of=AS_OF, observed_at=OBSERVED_AT, **kw)


class TriangulationTest(unittest.TestCase):
    def test_flag_set_matches_eligibility_gate(self):
        self.assertEqual(set(ss.DISQUALIFYING_FLAGS), set(_V1_DISQUALIFYING_STATUS_FLAGS))

    def test_flag_source_and_policy_match_binding(self):
        rows = {r["flag_id"]: r for r in BINDING["status_flag_bindings"]}
        self.assertEqual(set(rows), set(ss.DISQUALIFYING_FLAGS))
        # per-flag authorized source == binding
        for flag, src in ss.FLAG_SOURCE.items():
            self.assertEqual(rows[flag]["authorized_source_id"], src, flag)
        # gate policy maps from the binding unknown_policy: conservative_reject stays; bankruptcy's
        # mark_unscreened_not_clean is realised as positive_detection_only at the gate.
        expected_policy = {"conservative_reject": "conservative_reject",
                           "mark_unscreened_not_clean": "positive_detection_only"}
        for flag, pol in ss.FLAG_GATE_POLICY.items():
            self.assertEqual(expected_policy[rows[flag]["unknown_policy"]], pol, flag)

    def test_critical_sources_are_the_conservative_reject_sources(self):
        # only sec_8k (the best-effort positive-detection source) is non-critical
        self.assertEqual(set(ss.CRITICAL_STATUS_SOURCES), {"ticker_reference", "exchange_halt_feed"})
        self.assertNotIn("sec_8k_item_103", ss.CRITICAL_STATUS_SOURCES)


class ResolveDelistedOtcTest(unittest.TestCase):
    def test_active_whitelisted_is_clean(self):
        r = _record("AAPL", ticker_reference=_ref())
        self.assertIs(r["flags"]["delisted"]["value"], False)
        self.assertIs(r["flags"]["otc"]["value"], False)
        self.assertEqual(r["flags"]["otc"]["primary_exchange_value"], "NASDAQ")

    def test_inactive_is_delisted(self):
        self.assertIs(_record("DEAD", ticker_reference=_ref())["flags"]["delisted"]["value"], True)

    def test_otc_venue_flags_otc(self):
        r = _record("OTCX", ticker_reference=_ref())
        self.assertIs(r["flags"]["otc"]["value"], True)
        self.assertIs(r["flags"]["delisted"]["value"], False)

    def test_absent_full_coverage_is_delisted(self):
        self.assertIs(_record("MSFT", ticker_reference=_ref("full"))["flags"]["delisted"]["value"], True)

    def test_absent_partial_coverage_is_unknown(self):
        # a sample (partial) reference must NOT mass-mark non-sampled names delisted
        r = _record("MSFT", ticker_reference=_ref("partial"))
        self.assertIsNone(r["flags"]["delisted"]["value"])
        self.assertIsNone(r["flags"]["otc"]["value"])

    def test_source_not_observed_is_unknown(self):
        r = _record("AAPL", ticker_reference=None)
        self.assertIsNone(r["flags"]["delisted"]["value"])
        self.assertIsNone(r["flags"]["otc"]["value"])
        self.assertEqual(r["flags"]["delisted"]["coverage"], "not_consulted")

    def test_missing_primary_exchange_is_unknown_otc(self):
        r = _record("X", ticker_reference=_ref(listings={"X": {"active": True}}))
        self.assertIs(r["flags"]["delisted"]["value"], False)
        self.assertIsNone(r["flags"]["otc"]["value"])


class ResolveHaltedTest(unittest.TestCase):
    def test_in_feed_is_halted(self):
        self.assertIs(_record("HALT", halt_feed=_halt())["flags"]["halted"]["value"], True)

    def test_absent_from_observed_feed_is_clean(self):
        self.assertIs(_record("AAPL", halt_feed=_halt())["flags"]["halted"]["value"], False)

    def test_feed_not_observed_is_unknown(self):
        self.assertIsNone(_record("AAPL", halt_feed=None)["flags"]["halted"]["value"])


class ResolveBankruptcyTest(unittest.TestCase):
    def test_found_is_true(self):
        r = _record("BANKR", bankruptcy_screen=_bank())
        self.assertIs(r["flags"]["bankruptcy"]["value"], True)
        self.assertEqual(r["flags"]["bankruptcy"]["screen_status"], "bankrupt_8k_found")
        self.assertTrue(r["flags"]["bankruptcy"]["filing_accession_if_found"])

    def test_screened_no_filing_is_false(self):
        r = _record("AAPL", bankruptcy_screen=_bank())
        self.assertIs(r["flags"]["bankruptcy"]["value"], False)
        self.assertEqual(r["flags"]["bankruptcy"]["screen_status"], "screened_no_filing")

    def test_unscreened_is_false_but_recorded(self):
        # positive_detection_only + mark_unscreened_not_clean: gate False, provenance discloses unscreened
        r = _record("MSFT", bankruptcy_screen=_bank())   # not in by_ticker
        self.assertIs(r["flags"]["bankruptcy"]["value"], False)
        self.assertEqual(r["flags"]["bankruptcy"]["screen_status"], "unscreened")

    def test_screen_not_observed_is_unscreened_false(self):
        r = _record("AAPL", bankruptcy_screen=None)
        self.assertIs(r["flags"]["bankruptcy"]["value"], False)
        self.assertEqual(r["flags"]["bankruptcy"]["screen_status"], "unscreened")

    def test_found_without_accession_raises(self):
        bad = {"observed": True, "observed_at": OBSERVED_AT,
               "by_ticker": {"BANKR": {"screen_status": "bankrupt_8k_found"}}}
        with self.assertRaises(ss.StatusSourceError):
            _record("BANKR", bankruptcy_screen=bad)

    def test_observed_screen_requires_nonempty_lookback(self):
        for lookback in (None, "", "   "):
            screen = {"observed": True, "observed_at": OBSERVED_AT, "lookback_window": lookback,
                      "by_ticker": {"AAPL": {"screen_status": "screened_no_filing"}}}
            with self.assertRaises(ss.StatusSourceError):
                _record("AAPL", bankruptcy_screen=screen)

    def test_non_string_screen_status_rejected_without_typeerror(self):
        for screen_status in ([], {}, 1, ("x",)):
            with self.subTest(screen_status=repr(screen_status)):
                screen = {
                    "observed": True,
                    "observed_at": OBSERVED_AT,
                    "lookback_window": "P90D",
                    "by_ticker": {"AAPL": {"screen_status": screen_status}},
                }
                with self.assertRaises(ss.StatusSourceError):
                    _record("AAPL", bankruptcy_screen=screen)


class BuildBankruptcyScreenFromSecSubmissionsTest(unittest.TestCase):
    def test_item_103_8k_builds_screen_consumed_by_status_record(self):
        screen = ss.build_bankruptcy_screen_from_sec_submissions(
            as_of=AS_OF,
            observed_at=OBSERVED_AT,
            submissions_by_ticker={
                "AAPL": _sec_submissions(
                    forms=["8-K", "10-K"],
                    filing_dates=["2026-06-20", "2026-06-21"],
                    accessions=["0000320193-26-000111", "0000320193-26-000112"],
                    items=["1.03,9.01", "1.03"],
                ),
                "MSFT": _sec_submissions(
                    forms=["8-K", "8-K/A", "10-K"],
                    filing_dates=["2026-06-20", "2026-03-01", "2026-06-21"],
                    accessions=["0000789019-26-000111", "0000789019-26-000112", "0000789019-26-000113"],
                    items=["9.01", "1.03", "1.03"],
                ),
            },
        )

        self.assertEqual(screen["observed"], True)
        self.assertEqual(screen["observed_at"], OBSERVED_AT)
        self.assertEqual(screen["lookback_window"], "P90D")
        self.assertEqual(
            screen["by_ticker"]["AAPL"],
            {"screen_status": "bankrupt_8k_found", "filing_accession": "0000320193-26-000111"},
        )
        self.assertEqual(screen["by_ticker"]["MSFT"], {"screen_status": "screened_no_filing"})

        found = _record("AAPL", bankruptcy_screen=screen)
        clean = _record("MSFT", bankruptcy_screen=screen)
        self.assertTrue(ss.validate_status_record(found))
        self.assertTrue(ss.validate_status_record(clean))
        self.assertIs(found["flags"]["bankruptcy"]["value"], True)
        self.assertIs(clean["flags"]["bankruptcy"]["value"], False)

    def test_malformed_recent_arrays_raise_without_screened_no_filing(self):
        bad = {"filings": {"recent": {
            "form": ["8-K"],
            "filingDate": ["2026-06-20"],
            "accessionNumber": ["0000320193-26-000111"],
            "items": [],
        }}}
        with self.assertRaises(ss.StatusSourceError):
            ss.build_bankruptcy_screen_from_sec_submissions(
                as_of=AS_OF,
                observed_at=OBSERVED_AT,
                submissions_by_ticker={"AAPL": bad},
            )

    def test_duplicate_canonical_ticker_keys_raise(self):
        payload = _sec_submissions(forms=[], filing_dates=[], accessions=[], items=[])
        with self.assertRaises(ss.StatusSourceError):
            ss.build_bankruptcy_screen_from_sec_submissions(
                as_of=AS_OF,
                observed_at=OBSERVED_AT,
                submissions_by_ticker={"AAPL": payload, "aapl": payload},
            )


class CheapEligibleIntegrationTest(unittest.TestCase):
    """status_flags_for_row -> cheap_eligible end to end."""

    BASE = {"ticker": "AAPL", "exchange": "NASDAQ", "price": 150.0,
            "adv_usd": 50_000_000.0, "market_cap_usd": 2_000_000_000_000.0}

    def _verdict(self, ticker, base_ticker=None, **payloads):
        rec = _record(ticker, **payloads)
        rt = base_ticker or ticker
        row_flags, _ = ss.status_flags_for_row(rec, row_ticker=rt)   # record.ticker == rt (bound)
        row = {**self.BASE, "ticker": rt, **row_flags}
        return cheap_eligible(row, governance=GOVERNANCE)

    def test_all_clean_is_eligible(self):
        v = self._verdict("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())
        self.assertTrue(v["eligible"], v["reasons"])

    def test_unknown_delisted_omitted_then_conservative_reject(self):
        v = self._verdict("AAPL", ticker_reference=None, halt_feed=_halt(), bankruptcy_screen=_bank())
        self.assertFalse(v["eligible"])
        self.assertIn("status_delisted_unknown_or_invalid", v["reasons"])
        self.assertIn("status_otc_unknown_or_invalid", v["reasons"])

    def test_known_delisted_rejected(self):
        v = self._verdict("DEAD", base_ticker="DEAD", ticker_reference=_ref(), halt_feed=_halt(),
                          bankruptcy_screen=_bank())
        self.assertFalse(v["eligible"])
        self.assertIn("status_delisted", v["reasons"])

    def test_halted_rejected(self):
        v = self._verdict("HALT", base_ticker="HALT", ticker_reference=_ref(
            listings={"HALT": {"active": True, "primary_exchange": "NYSE"}}),
            halt_feed=_halt(("HALT",)), bankruptcy_screen=_bank())
        self.assertFalse(v["eligible"])
        self.assertIn("status_halted", v["reasons"])

    def test_bankruptcy_found_rejected(self):
        v = self._verdict("BANKR", base_ticker="BANKR", ticker_reference=_ref(
            listings={"BANKR": {"active": True, "primary_exchange": "NYSE"}}),
            halt_feed=_halt(), bankruptcy_screen=_bank())
        self.assertFalse(v["eligible"])
        self.assertIn("status_bankruptcy", v["reasons"])

    def test_bankruptcy_unscreened_does_not_reject(self):
        # the universe-collapse guard: not scanning bankruptcy must NOT reject an otherwise-clean name
        v = self._verdict("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=None)
        self.assertTrue(v["eligible"], v["reasons"])


class ClassifyOutcomesTest(unittest.TestCase):
    def test_all_ok_no_block(self):
        out = ss.classify_status_source_outcomes(
            {"ticker_reference": "ok", "exchange_halt_feed": "ok", "sec_8k_item_103": "ok"})
        self.assertFalse(out["block_or_no_emit"])
        self.assertEqual(out["failed_count"], 0)

    def test_one_critical_down_not_block(self):
        out = ss.classify_status_source_outcomes(
            {"ticker_reference": "down", "exchange_halt_feed": "ok", "sec_8k_item_103": "ok"})
        self.assertFalse(out["block_or_no_emit"])     # only one critical failed
        self.assertEqual(out["critical_failed"], ["ticker_reference"])
        self.assertEqual(out["failed_count"], 1)

    def test_both_critical_down_blocks(self):
        out = ss.classify_status_source_outcomes(
            {"ticker_reference": "down", "exchange_halt_feed": "missing", "sec_8k_item_103": "ok"})
        self.assertTrue(out["block_or_no_emit"])
        self.assertTrue(out["critical_all_failed"])

    def test_sec_8k_down_only_not_block(self):
        out = ss.classify_status_source_outcomes(
            {"ticker_reference": "ok", "exchange_halt_feed": "ok", "sec_8k_item_103": "down"})
        self.assertFalse(out["block_or_no_emit"])     # best-effort source is not critical
        self.assertEqual(out["failed_sources"], ["sec_8k_item_103"])

    def test_unaccounted_source_is_missing_failed(self):
        out = ss.classify_status_source_outcomes({"ticker_reference": "ok", "exchange_halt_feed": "ok"})
        self.assertEqual(out["per_source"]["sec_8k_item_103"], "missing")
        self.assertIn("sec_8k_item_103", out["failed_sources"])

    def test_unknown_source_raises(self):
        with self.assertRaises(ss.StatusSourceError):
            ss.classify_status_source_outcomes({"fmp_full_market": "ok"})

    def test_invalid_state_raises(self):
        with self.assertRaises(ss.StatusSourceError):
            ss.classify_status_source_outcomes({"ticker_reference": "great"})


class ValidateStatusRecordTest(unittest.TestCase):
    def test_real_record_validates(self):
        self.assertTrue(ss.validate_status_record(
            _record("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())))

    def test_fabricated_minimal_rejected(self):
        self.assertFalse(ss.validate_status_record({"ticker": "AAPL", "flags": {}}))

    def test_missing_flag_rejected(self):
        rec = _record("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())
        rec["flags"].pop("otc")
        self.assertFalse(ss.validate_status_record(rec))

    def test_wrong_source_id_rejected(self):
        rec = _record("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())
        rec["flags"]["delisted"]["source_id"] = "exchange_halt_feed"
        self.assertFalse(ss.validate_status_record(rec))

    def test_bankruptcy_none_value_rejected(self):
        rec = _record("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())
        rec["flags"]["bankruptcy"]["value"] = None     # bankruptcy gate value must be a strict bool
        self.assertFalse(ss.validate_status_record(rec))

    def test_extra_top_key_rejected(self):
        rec = _record("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())
        rec["surprise"] = 1
        self.assertFalse(ss.validate_status_record(rec))

    def test_status_flags_for_row_rejects_fabricated(self):
        with self.assertRaises(ss.StatusSourceError):
            ss.status_flags_for_row({"ticker": "AAPL", "flags": {}}, row_ticker="AAPL")

    def test_non_strict_flag_values_rejected_without_typeerror(self):
        bad_values = (0, 1, 1.0, "True", [], {})
        for flag in ss.DISQUALIFYING_FLAGS:
            for bad in bad_values:
                rec = _record("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())
                rec["flags"][flag]["value"] = bad
                self.assertFalse(ss.validate_status_record(rec), (flag, bad))
        found = _record("BANKR", ticker_reference=_ref(
            listings={"BANKR": {"active": True, "primary_exchange": "NYSE"}}),
            halt_feed=_halt(), bankruptcy_screen=_bank())
        found["flags"]["bankruptcy"]["value"] = 1
        self.assertFalse(ss.validate_status_record(found))

    def test_non_str_coverage_and_bankruptcy_status_rejected_without_typeerror(self):
        for flag in ss.DISQUALIFYING_FLAGS:
            rec = _record("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())
            rec["flags"][flag]["coverage"] = []
            self.assertFalse(ss.validate_status_record(rec), flag)
        rec = _record("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())
        rec["flags"]["bankruptcy"]["screen_status"] = []
        self.assertFalse(ss.validate_status_record(rec))


class MalformedPayloadTest(unittest.TestCase):
    def test_non_dict_payload_raises(self):
        with self.assertRaises(ss.StatusSourceError):
            _record("AAPL", ticker_reference=["not", "a", "dict"])

    def test_non_bool_observed_raises(self):
        with self.assertRaises(ss.StatusSourceError):
            _record("AAPL", ticker_reference={"observed": "yes", "coverage": "full", "active_listings": {}})

    def test_bad_coverage_raises(self):
        with self.assertRaises(ss.StatusSourceError):
            _record("AAPL", ticker_reference={"observed": True, "observed_at": OBSERVED_AT,
                                                "coverage": "some", "active_listings": {}})

    def test_non_canonical_ticker_raises(self):
        with self.assertRaises(ss.StatusSourceError):
            _record("000001.SZ", ticker_reference=_ref())


class RecordRowBindingTest(unittest.TestCase):
    """R-USSHORT-BATCH5-STATUS-RECORD-ROW-BINDING-GAP closure: record<->row identity binding at the conversion
    boundary + closed-world validation of the WHOLE record (every flag/field, not just the probe legs)."""

    def _clean(self, ticker="AAPL"):
        return _record(ticker, ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())

    # --- A. record <-> row identity binding (Codex probe 1: AAPL clean record applied to a DEAD row) ---
    def test_clean_record_to_other_ticker_row_raises(self):
        with self.assertRaises(ss.StatusSourceError):
            ss.status_flags_for_row(self._clean("AAPL"), row_ticker="DEAD")

    def test_record_to_same_ticker_row_ok(self):
        row_flags, _ = ss.status_flags_for_row(self._clean("AAPL"), row_ticker="AAPL")
        self.assertEqual(row_flags, {"delisted": False, "halted": False, "otc": False, "bankruptcy": False})

    def test_row_ticker_case_insensitive_binds(self):
        row_flags, _ = ss.status_flags_for_row(self._clean("AAPL"), row_ticker=" aapl ")  # canonicalises to AAPL
        self.assertIn("delisted", row_flags)

    def test_noncanonical_row_ticker_raises(self):
        with self.assertRaises(ss.StatusSourceError):
            ss.status_flags_for_row(self._clean("AAPL"), row_ticker="000001.SZ")

    # --- B. noncanonical top-level record ticker (Codex probe 2a) ---
    def test_noncanonical_top_ticker_rejected(self):
        rec = self._clean("AAPL"); rec["ticker"] = "000001.SZ"
        self.assertFalse(ss.validate_status_record(rec))

    def test_lowercase_top_ticker_rejected(self):
        rec = self._clean("AAPL"); rec["ticker"] = "aapl"      # resolver only ever emits the canonical form
        self.assertFalse(ss.validate_status_record(rec))

    # --- C/D. per-flag as_of binds to the record; source clocks must satisfy the source-owned PIT contract ---
    def test_per_flag_as_of_mismatch_rejected_all_flags(self):
        for flag in ss.DISQUALIFYING_FLAGS:
            rec = self._clean("AAPL"); rec["flags"][flag]["as_of"] = "1900-01-01"
            self.assertFalse(ss.validate_status_record(rec), flag)

    def test_per_flag_observed_at_mismatch_rejected_all_flags(self):
        for flag in ss.DISQUALIFYING_FLAGS:
            rec = self._clean("AAPL"); rec["flags"][flag]["observed_at"] = "1900-01-01T00:00:00+00:00"
            self.assertFalse(ss.validate_status_record(rec), flag)

    # --- E. coverage closed-world per flag (probe 2c only showed delisted.coverage) ---
    def test_invalid_coverage_rejected_all_flags(self):
        for flag in ss.DISQUALIFYING_FLAGS:
            rec = self._clean("AAPL"); rec["flags"][flag]["coverage"] = "nonsense"
            self.assertFalse(ss.validate_status_record(rec), flag)

    # --- F/G. (value, coverage[, screen_status]) must be resolver-emittable + source-specific value types ---
    def test_delisted_value_coverage_combo_forgery_rejected(self):
        rec = self._clean("AAPL")
        rec["flags"]["delisted"].update(value=False, coverage="absent_full")  # resolver never emits this pair
        self.assertFalse(ss.validate_status_record(rec))

    def test_bankruptcy_observed_unscreened_forgery_rejected(self):
        rec = self._clean("AAPL")
        rec["flags"]["bankruptcy"].update(value=False, coverage="observed", screen_status="unscreened")
        self.assertFalse(ss.validate_status_record(rec))

    def test_bankruptcy_value_screen_status_mismatch_rejected(self):
        rec = self._clean("AAPL")
        rec["flags"]["bankruptcy"].update(value=True, screen_status="screened_no_filing")  # True only if found
        self.assertFalse(ss.validate_status_record(rec))

    def test_bankruptcy_found_without_accession_rejected(self):
        rec = self._clean("AAPL")
        rec["flags"]["bankruptcy"].update(value=True, coverage="observed",
                                          screen_status="bankrupt_8k_found", filing_accession_if_found=None)
        self.assertFalse(ss.validate_status_record(rec))

    def test_nonfound_with_stray_accession_rejected(self):
        rec = self._clean("AAPL")
        rec["flags"]["bankruptcy"]["filing_accession_if_found"] = "0001-stray"  # screened_no_filing carries none
        self.assertFalse(ss.validate_status_record(rec))

    def test_halt_feed_observed_non_bool_rejected(self):
        rec = self._clean("AAPL"); rec["flags"]["halted"]["halt_feed_observed"] = "yes"
        self.assertFalse(ss.validate_status_record(rec))

    def test_halt_observed_value_inconsistent_rejected(self):
        rec = self._clean("AAPL")
        rec["flags"]["halted"].update(halt_feed_observed=True, coverage="not_consulted", value=None)
        self.assertFalse(ss.validate_status_record(rec))

    def test_otc_primary_exchange_non_str_rejected(self):
        rec = self._clean("AAPL"); rec["flags"]["otc"]["primary_exchange_value"] = 123
        self.assertFalse(ss.validate_status_record(rec))

    def test_delisted_reference_active_value_bad_type_rejected(self):
        rec = self._clean("AAPL"); rec["flags"]["delisted"]["reference_active_value"] = "x"
        self.assertFalse(ss.validate_status_record(rec))

    # --- positive controls: every real resolver output validates + binds (no over-constraint, C gate) ---
    def test_positive_resolver_outputs_validate_and_bind(self):
        cases = [
            self._clean("AAPL"),                                                                       # clean
            _record("DEAD", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank()),    # delisted
            _record("OTCX", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank()),    # otc
            _record("HALT", ticker_reference=_ref(listings={"HALT": {"active": True, "primary_exchange": "NYSE"}}),
                    halt_feed=_halt(("HALT",)), bankruptcy_screen=_bank()),                            # halted
            _record("BANKR", ticker_reference=_ref(listings={"BANKR": {"active": True, "primary_exchange": "NYSE"}}),
                    halt_feed=_halt(), bankruptcy_screen=_bank()),                                     # bankruptcy found
            _record("MSFT", ticker_reference=_ref("partial"), halt_feed=_halt(), bankruptcy_screen=_bank()),  # absent partial + unscreened
            _record("AAPL", ticker_reference=None, halt_feed=None, bankruptcy_screen=None),            # nothing observed
        ]
        for rec in cases:
            self.assertTrue(ss.validate_status_record(rec), rec["ticker"])
            ss.status_flags_for_row(rec, row_ticker=rec["ticker"])   # binds + emits without raising


class SourceKeyCanonicalizationTest(unittest.TestCase):
    """Self-review F-A: source-payload ticker KEYS must be canonicalized before lookup (mirrors the halt feed),
    else a non-canonical bankruptcy key misses a found 8-K (fail-OPEN) and a non-canonical listing over-rejects."""

    def test_bankruptcy_noncanonical_key_still_detected(self):
        # by_ticker keyed 'bankr' (lowercase) must still be found for canonical 'BANKR' (was a fail-open)
        screen = {"observed": True, "observed_at": OBSERVED_AT, "lookback_window": "P90D", "by_ticker": {
            "bankr": {"screen_status": "bankrupt_8k_found", "filing_accession": "0001-x"}}}
        self.assertIs(_record("BANKR", bankruptcy_screen=screen)["flags"]["bankruptcy"]["value"], True)

    def test_listings_noncanonical_key_resolves_clean(self):
        # 'aapl' active listing must resolve canonical 'AAPL' as clean (was over-rejected as delisted-absent)
        ref = {"observed": True, "observed_at": OBSERVED_AT, "coverage": "full",
               "active_listings": {"aapl": {"active": True, "primary_exchange": "NASDAQ"}}}
        rec = _record("AAPL", ticker_reference=ref)
        self.assertIs(rec["flags"]["delisted"]["value"], False)
        self.assertIs(rec["flags"]["otc"]["value"], False)

    def test_listings_canonical_collision_raises(self):
        ref = {"observed": True, "observed_at": OBSERVED_AT, "coverage": "full",
               "active_listings": {"AAPL": {"active": True, "primary_exchange": "NASDAQ"},
                                   "aapl": {"active": False, "primary_exchange": "OTC"}}}
        with self.assertRaises(ss.StatusSourceError):
            _record("AAPL", ticker_reference=ref)

    def test_bankruptcy_canonical_collision_raises(self):
        screen = {"observed": True, "observed_at": OBSERVED_AT, "lookback_window": "P90D", "by_ticker": {
            "BANKR": {"screen_status": "screened_no_filing"},
            "bankr": {"screen_status": "bankrupt_8k_found", "filing_accession": "0001-x"}}}
        with self.assertRaises(ss.StatusSourceError):
            _record("BANKR", bankruptcy_screen=screen)

    def test_bankruptcy_garbage_key_raises_not_dropped(self):
        # F-E (deeper self-review): a NON-canonicalizable by_ticker key must RAISE (fail-closed), not be
        # silently dropped — dropping a found-bankruptcy record keyed by garbage would re-open the fail-open.
        screen = {"observed": True, "observed_at": OBSERVED_AT, "lookback_window": "P90D", "by_ticker": {
            "NOT A TICKER!": {"screen_status": "bankrupt_8k_found", "filing_accession": "0001-x"}}}
        with self.assertRaises(ss.StatusSourceError):
            _record("AAPL", bankruptcy_screen=screen)

    def test_listings_garbage_key_raises_not_dropped(self):
        ref = {"observed": True, "observed_at": OBSERVED_AT, "coverage": "full",
               "active_listings": {"NOT A TICKER!": {"active": True, "primary_exchange": "NASDAQ"}}}
        with self.assertRaises(ss.StatusSourceError):
            _record("AAPL", ticker_reference=ref)

    def test_halt_noncanonical_entry_still_detected(self):
        # the pre-existing halt-feed canonicalization the other two sources are brought up to match
        self.assertIs(_record("HALT", halt_feed={"observed": True, "observed_at": OBSERVED_AT,
                                                  "halted_symbols": ["halt"]})
                      ["flags"]["halted"]["value"], True)


class ExchangeWhitelistSingleSourceTest(unittest.TestCase):
    """Self-review F-B: otc uses the SAME §3.1 whitelist as the cheap-eligibility gate (single source, no drift)."""

    def test_default_whitelist_is_the_eligibility_gate_whitelist(self):
        from engine.us_short_eligibility_gate import _V1_EXCHANGE_WHITELIST
        self.assertEqual(ss._DEFAULT_EXCHANGE_WHITELIST, _V1_EXCHANGE_WHITELIST)

    def test_bare_string_whitelist_rejected(self):
        # tuple('NYSE') footgun: a bare string must not be silently char-split into a 4-letter whitelist
        with self.assertRaises(ss.StatusSourceError):
            ss.resolve_status_record("AAPL", ticker_reference=_ref(), as_of=AS_OF, observed_at=OBSERVED_AT,
                                     exchange_whitelist="NYSE")


class StatusClockTest(unittest.TestCase):
    """Codex finding A (R-USSHORT-BATCH5-STATUS-SOURCE-CLOCK-AND-ACCESS-PACKET-PIN-GAP): the status clock
    (top-level as_of / observed_at) must be a parseable PIT date/timestamp, not free text — at BOTH the
    resolver input and the validator boundary."""

    def test_invalid_as_of_raises_in_resolve(self):
        with self.assertRaises(ss.StatusSourceError):
            ss.resolve_status_record("AAPL", ticker_reference=_ref(), as_of="not-a-date", observed_at=OBSERVED_AT)

    def test_invalid_observed_at_raises_in_resolve(self):
        with self.assertRaises(ss.StatusSourceError):
            ss.resolve_status_record("AAPL", ticker_reference=_ref(), as_of=AS_OF, observed_at="not-a-time")

    def test_validate_rejects_invalid_as_of(self):
        rec = _record("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())
        rec["as_of"] = "not-a-date"
        self.assertFalse(ss.validate_status_record(rec))

    def test_validate_rejects_invalid_observed_at(self):
        rec = _record("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())
        rec["observed_at"] = "not-a-time"
        self.assertFalse(ss.validate_status_record(rec))

    def test_valid_clock_accepted(self):
        # positive control: real YYYY-MM-DD as_of + ISO-8601 observed_at both resolve + validate
        rec = _record("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())
        self.assertTrue(ss.validate_status_record(rec))

    def test_non_ascii_as_of_rejected(self):
        # `datetime.strptime` accepts Unicode decimal digits, so a fullwidth / Arabic-Indic `as_of` would parse
        # as a "date" — a non-ASCII clock must NOT pass (observed_at via fromisoformat already rejects them;
        # _valid_as_of now mirrors the market_calendar .isascii() guard).
        for bad in ("２０２６-06-30", "2026-06-3٠"):    # fullwidth year / Arabic-Indic day digit
            self.assertFalse(ss._valid_as_of(bad), bad)
            with self.assertRaises(ss.StatusSourceError):
                ss.resolve_status_record("AAPL", ticker_reference=_ref(), as_of=bad, observed_at=OBSERVED_AT)
            rec = _record("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())
            rec["as_of"] = bad
            self.assertFalse(ss.validate_status_record(rec), bad)

    def test_date_only_or_naive_observed_at_rejected(self):
        # Codex residual A: date-only / no-timezone / space-separated observed_at is ambiguous PIT evidence → reject
        for bad in ("2026-06-30", "2026-06-30T12:00:00", "2026-06-30 12:00:00"):
            with self.assertRaises(ss.StatusSourceError):
                ss.resolve_status_record("AAPL", ticker_reference=_ref(), as_of=AS_OF, observed_at=bad)
            rec = _record("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())
            rec["observed_at"] = bad
            self.assertFalse(ss.validate_status_record(rec), bad)

    def test_tzaware_observed_at_accepted(self):
        # positive control: both an explicit offset and a 'Z' UTC observed_at resolve + validate
        for ok in ("2026-06-30T08:00:00-04:00", "2026-06-30T12:00:00Z"):
            r = ss.resolve_status_record(
                "AAPL", ticker_reference=_ref(observed_at=ok), as_of=AS_OF, observed_at=ok)
            self.assertTrue(ss.validate_status_record(r), ok)

    def test_future_observed_at_rejected(self):
        # Residual A (look-ahead): an observed_at whose ET date is AFTER as_of must reject at resolver, validator,
        # AND the consumer boundary. Values are future IN ET (as_of=2026-06-30).
        for future in ("2026-07-01T12:00:00+00:00",     # ET 2026-07-01 08:00 → next day
                       "2099-01-01T00:00:00+00:00"):    # far future
            with self.assertRaises(ss.StatusSourceError):
                ss.resolve_status_record("AAPL", ticker_reference=_ref(), as_of=AS_OF, observed_at=future)
            rec = _record("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())
            rec["observed_at"] = future
            for flag in rec["flags"].values():
                flag["observed_at"] = future
            self.assertFalse(ss.validate_status_record(rec), future)
            with self.assertRaises(ss.StatusSourceError):
                ss.status_flags_for_row(rec, row_ticker="AAPL")   # the consumer boundary also fails closed

    def test_timezone_normalized_to_et_not_caller_offset(self):
        # Residual A1: the PIT date is the instant normalized to ET (America/New_York), NOT the caller's local
        # date. Both are Codex's exact probes (as_of=2026-06-30).
        # (a) 2026-06-30T23:59:59-12:00 == 2026-07-01 07:59 ET → look-ahead → a caller offset must NOT admit it.
        with self.assertRaises(ss.StatusSourceError):
            ss.resolve_status_record("AAPL", ticker_reference=_ref(), as_of=AS_OF,
                                     observed_at="2026-06-30T23:59:59-12:00")
        # (b) 2026-06-30T00:30:00Z == 2026-06-29 20:30 ET → legal overnight decision window.
        overnight = "2026-06-30T00:30:00Z"
        r = ss.resolve_status_record(
            "AAPL", ticker_reference=_ref(observed_at=overnight), as_of=AS_OF, observed_at=overnight)
        self.assertTrue(ss.validate_status_record(r))

    def test_dst_winter_offset_normalized(self):
        # Winter ET is UTC-5 (EST). 2026-01-15T13:00Z == 08:00 EST, inside the pre-open decision window.
        winter = "2026-01-15T13:00:00Z"
        r = ss.resolve_status_record(
            "AAPL", ticker_reference=_ref(observed_at=winter), as_of="2026-01-15", observed_at=winter)
        self.assertTrue(ss.validate_status_record(r))

    def test_far_stale_observed_at_rejected(self):
        # A record outside the exact prior-close -> decision-open window cannot clear critical unknowns.
        for stale in ("2020-01-01T00:00:00+00:00",          # ~6 years old
                      "2026-06-22T13:30:00+00:00"):         # ET 06-22 = 8 days < as_of-7 (06-23)
            with self.assertRaises(ss.StatusSourceError):
                ss.resolve_status_record("AAPL", ticker_reference=_ref(), as_of=AS_OF, observed_at=stale)
            rec = _record("AAPL", ticker_reference=_ref(), halt_feed=_halt(), bankruptcy_screen=_bank())
            rec["observed_at"] = stale
            for flag in rec["flags"].values():
                flag["observed_at"] = stale
            self.assertFalse(ss.validate_status_record(rec), stale)
            with self.assertRaises(ss.StatusSourceError):
                ss.status_flags_for_row(rec, row_ticker="AAPL")

    def test_prior_session_weekend_within_window_retained(self):
        # Exact market-calendar window: previous-session close, overnight, and pre-open are all valid.
        for prior in ("2026-06-29T20:00:00+00:00",          # ET 06-29 16:00 (window opens)
                      "2026-06-30T00:30:00+00:00",          # ET 06-29 20:30 (overnight)
                      "2026-06-30T13:00:00+00:00"):         # ET 06-30 09:00 (pre-open)
            r = ss.resolve_status_record(
                "AAPL", ticker_reference=_ref(observed_at=prior), as_of=AS_OF, observed_at=prior)
            self.assertTrue(ss.validate_status_record(r), prior)


class SourceSpecificClockTest(unittest.TestCase):
    def test_record_before_prior_session_close_rejected(self):
        with self.assertRaises(ss.StatusSourceError):
            ss.resolve_status_record(
                "AAPL", as_of=AS_OF, observed_at="2026-06-29T19:00:00Z",
                ticker_reference=_ref(observed_at="2026-06-29T19:00:00Z"))

    def test_record_at_or_after_decision_open_rejected(self):
        for observed_at in ("2026-06-30T13:30:00Z", "2026-06-30T14:00:00Z"):
            with self.assertRaises(ss.StatusSourceError):
                ss.resolve_status_record(
                    "AAPL", as_of=AS_OF, observed_at=observed_at,
                    ticker_reference=_ref(observed_at=observed_at))

    def test_stale_halt_feed_cannot_emit_clean_false(self):
        stale = "2026-06-23T13:30:00Z"
        r = ss.resolve_status_record(
            "AAPL", as_of=AS_OF, observed_at=OBSERVED_AT,
            ticker_reference=_ref(), halt_feed=_halt((), observed_at=stale), bankruptcy_screen=_bank())
        self.assertIsNone(r["flags"]["halted"]["value"])
        self.assertEqual(r["flags"]["halted"]["coverage"], "stale")
        row_flags, _ = ss.status_flags_for_row(r, row_ticker="AAPL")
        self.assertNotIn("halted", row_flags)

    def test_stale_ticker_reference_does_not_poison_fresh_halt_feed(self):
        stale = "2026-06-23T13:30:00Z"
        r = ss.resolve_status_record(
            "AAPL", as_of=AS_OF, observed_at=OBSERVED_AT,
            ticker_reference=_ref(observed_at=stale), halt_feed=_halt(()), bankruptcy_screen=_bank())
        self.assertIsNone(r["flags"]["delisted"]["value"])
        self.assertIsNone(r["flags"]["otc"]["value"])
        self.assertIs(r["flags"]["halted"]["value"], False)
        self.assertEqual(r["flags"]["delisted"]["observed_at"], stale)
        self.assertEqual(r["flags"]["halted"]["observed_at"], OBSERVED_AT)

    def test_stale_positive_bankruptcy_detection_is_not_erased(self):
        stale = "2026-06-23T13:30:00Z"
        r = ss.resolve_status_record(
            "BANKR", as_of=AS_OF, observed_at=OBSERVED_AT,
            bankruptcy_screen=_bank(observed_at=stale))
        self.assertIs(r["flags"]["bankruptcy"]["value"], True)
        self.assertEqual(r["flags"]["bankruptcy"]["coverage"], "stale_positive")
        self.assertTrue(ss.validate_status_record(r))

    def test_observed_source_requires_own_clock(self):
        with self.assertRaises(ss.StatusSourceError):
            ss.resolve_status_record(
                "AAPL", as_of=AS_OF, observed_at=OBSERVED_AT,
                halt_feed={"observed": True, "halted_symbols": []})

    def test_source_clock_after_record_clock_rejected(self):
        with self.assertRaises(ss.StatusSourceError):
            ss.resolve_status_record(
                "AAPL", as_of=AS_OF, observed_at=OBSERVED_AT,
                halt_feed=_halt((), observed_at="2026-06-30T12:00:01Z"))

    def test_holiday_weekend_prior_close_is_valid(self):
        record_clock = "2026-09-06T16:00:00Z"
        source_clock = "2026-09-04T20:00:00Z"
        r = ss.resolve_status_record(
            "AAPL", as_of="2026-09-08", observed_at=record_clock,
            ticker_reference=_ref(observed_at=source_clock),
            halt_feed=_halt((), observed_at=source_clock),
            bankruptcy_screen=_bank(observed_at=source_clock))
        self.assertTrue(ss.validate_status_record(r))
        self.assertIs(r["flags"]["halted"]["value"], False)

    def test_half_day_close_opens_window_at_1300_et(self):
        before_close = "2026-11-27T17:59:59Z"
        with self.assertRaises(ss.StatusSourceError):
            ss.resolve_status_record(
                "AAPL", as_of="2026-11-30", observed_at=before_close,
                ticker_reference=_ref(observed_at=before_close))
        at_close = "2026-11-27T18:00:00Z"
        r = ss.resolve_status_record(
            "AAPL", as_of="2026-11-30", observed_at=at_close,
            ticker_reference=_ref(observed_at=at_close), halt_feed=_halt((), observed_at=at_close))
        self.assertTrue(ss.validate_status_record(r))

    def test_validator_rejects_stale_clock_laundered_as_observed(self):
        stale = "2026-06-23T13:30:00Z"
        r = ss.resolve_status_record(
            "AAPL", as_of=AS_OF, observed_at=OBSERVED_AT,
            ticker_reference=_ref(), halt_feed=_halt((), observed_at=stale))
        r["flags"]["halted"]["coverage"] = "observed"
        r["flags"]["halted"]["value"] = False
        self.assertFalse(ss.validate_status_record(r))


if __name__ == "__main__":
    unittest.main()
