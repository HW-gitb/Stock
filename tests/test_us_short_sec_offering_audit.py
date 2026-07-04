# -*- coding: utf-8 -*-
"""Offline tests for the US-short Cut 5-a SEC offering-audit source.

Covers the whole class the source must get right: binding<->const triangulation + schema, canonical identity +
hostile-key hardening, §3.1 provenance + §3.5 PIT (the observed INSTANT strictly before the 09:30 ET decision open;
per-filing acceptance_datetime <= observed; source/observed not after as_of), source-row (accession) identity +
duplicate rejection, coverage/parser emission fitness, the §5.1a status derivation (recent 424B takedown -> active;
bare recent shelf -> registered_shelf; stale -> stale), materiality-always-null, the audited-clean CHECKED coverage
record, and that the emitted active_offering feeds classify_hard_veto to the design-required tier. No network / provider.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_sec_offering_audit as oa  # noqa: E402
from engine.us_short_hard_veto import classify_hard_veto  # noqa: E402

AS_OF = "2026-06-30"
# default observation = 08:00 ET on as_of = PRE-OPEN (strictly before the 09:30 decision open), so the happy path
# is in-window under the half-open instant cutoff (a 12:00/22:00 ET observation would now be look-ahead).
PREOPEN = AS_OF + "T08:00:00-04:00"


def prov(*, source_as_of=AS_OF, observed_at=PREOPEN, coverage="full", parser="ok", rid="cik320193"):
    return {
        "provider_id": "sec_edgar", "endpoint_or_filing_type": "submissions",
        "source_as_of": source_as_of, "observed_at": observed_at,
        "coverage_status": coverage, "parser_status": parser,
        "lineage_ref": f"sec_edgar:submissions:{source_as_of}#{rid}",
    }


def filing(form, filing_date, accession=None, acceptance=None):
    # default acceptance = 16:00 ET on the filing date (an EDGAR public instant well before the default 08:00-ET
    # next-window observation); default accession is unique per (form, filing_date) so multi-filing fixtures do not
    # trip the duplicate-accession guard.
    return {
        "form": form, "filing_date": filing_date,
        "acceptance_datetime": acceptance if acceptance is not None else filing_date + "T16:00:00-04:00",
        "accession": accession if accession is not None else f"acc-{form}-{filing_date}",
    }


def rec(filings, **prov_kw):
    return {"filings": filings, "provenance": prov(**prov_kw)}


def submissions(*, forms, filing_dates, acceptances, accessions):
    return {"filings": {"recent": {
        "form": list(forms),
        "filingDate": list(filing_dates),
        "acceptanceDateTime": list(acceptances),
        "accessionNumber": list(accessions),
    }}}


class BindingTriangulationTests(unittest.TestCase):
    def test_module_consts_equal_binding(self):
        b = oa.load_binding()
        self.assertEqual(b["provider_id"], oa.PROVIDER_ID)
        self.assertEqual(b["endpoint_or_filing_type"], oa.ENDPOINT)
        self.assertEqual(b["decision_timezone"], oa._DECISION_TZ_NAME)   # ET-laundering defense, triangulated
        self.assertEqual(b["recency_window_days"], oa._RECENCY_WINDOW_DAYS)
        self.assertEqual(b["takedown_family"], oa._TAKEDOWN_FAMILY)
        self.assertEqual(set(b["provenance_fields"]), oa._PROVENANCE_FIELDS)
        self.assertEqual(set(b["coverage_status_allowed"]), oa._COVERAGE_ALLOWED)
        self.assertEqual(set(b["parser_status_allowed"]), oa._PARSER_ALLOWED)
        self.assertEqual(b["emission_fitness"]["coverage_status"], oa._COVERAGE_EMIT)
        self.assertEqual(b["emission_fitness"]["parser_status"], oa._PARSER_EMIT)
        self.assertEqual(set(b["offering_form_families"]), set(oa._OFFERING_FAMILIES))   # no extra/missing family
        for family, (matcher, patterns, role) in oa._OFFERING_FAMILIES.items():
            bf = b["offering_form_families"][family]
            self.assertEqual(bf["match"], matcher)
            self.assertEqual(tuple(bf["forms"]), patterns)
            self.assertEqual(bf["dilution_role"], role)
        # machine-policy consts (finding D): PIT clock / duplicate / checked-empty / lineage / authorization boundary
        self.assertEqual(set(b["filing_fields"]), oa._FILING_KEYS)
        self.assertEqual(b["pit_clock_contract"]["observed_at_cutoff_operator"], oa._CUTOFF_OPERATOR)
        self.assertEqual(b["pit_clock_contract"]["observed_at_cutoff_reference"], oa._CUTOFF_REFERENCE)
        self.assertEqual(tuple(b["pit_clock_contract"]["chronology_order"]), oa._CHRONOLOGY_ORDER)
        self.assertEqual(b["duplicate_policy"]["source_row_identity"], oa._DUPLICATE_IDENTITY)
        self.assertEqual(b["duplicate_policy"]["on_duplicate"], oa._DUPLICATE_POLICY)
        self.assertEqual(b["checked_empty_disposition"], oa._CHECKED_EMPTY_DISPOSITION)
        self.assertEqual(b["lineage_ref_format"]["structure"], oa._LINEAGE_REF_FORMAT)
        self.assertEqual(b["authorization_boundary"], oa._AUTHORIZATION_BOUNDARY)

    def test_binding_matches_schema(self):
        import jsonschema
        schema = json.loads((ROOT / "schemas" / "us_short_cut5_sec_offering_audit_binding.schema.json")
                            .read_text(encoding="utf-8"))
        jsonschema.validate(oa.load_binding(), schema)   # raises on drift


class StatusDerivationTests(unittest.TestCase):
    def test_recent_424b_takedown_is_active(self):
        out = oa.resolve_offering_audit(
            as_of=AS_OF, filings_by_ticker={"AAPL": rec([filing("424B5", "2026-05-01")])})
        sig = out["signals"]["AAPL"]["active_offering"]
        self.assertEqual(sig, {"recency": "recent", "status": "active", "materiality": None})
        # feeds hard_veto -> recent+active+materiality-null -> strong_downgrade (没数据≠安全)
        v = classify_hard_veto({"active_offering": sig}, "candidate")
        self.assertEqual(v["veto_tier"], "strong_downgrade")

    def test_recent_shelf_only_is_registered_shelf(self):
        out = oa.resolve_offering_audit(
            as_of=AS_OF, filings_by_ticker={"MSFT": rec([filing("S-3", "2026-05-01")])})
        sig = out["signals"]["MSFT"]["active_offering"]
        self.assertEqual(sig, {"recency": "recent", "status": "registered_shelf", "materiality": None})
        # bare recent shelf (挂着的 shelf ≠ 马上增发) -> hard_veto soft_risk_tag
        v = classify_hard_veto({"active_offering": sig}, "candidate")
        self.assertEqual(v["veto_tier"], "soft_risk_tag")

    def test_s3asr_matched_by_shelf_family(self):
        out = oa.resolve_offering_audit(
            as_of=AS_OF, filings_by_ticker={"NVDA": rec([filing("S-3ASR", "2026-06-01")])})
        self.assertEqual(out["signals"]["NVDA"]["active_offering"]["status"], "registered_shelf")

    def test_foreign_issuer_f3_shelf_matched(self):
        # a NYSE/NASDAQ-listed ADR files F-3 (not S-3) for a shelf; a domestic-only family set would MISS it
        out = oa.resolve_offering_audit(
            as_of=AS_OF, filings_by_ticker={"BABA": rec([filing("F-3", "2026-06-01")])})
        self.assertEqual(out["signals"]["BABA"]["active_offering"]["status"], "registered_shelf")

    def test_foreign_f1_and_reit_s11_matched(self):
        for form in ("F-1", "F-3ASR", "S-11"):
            out = oa.resolve_offering_audit(
                as_of=AS_OF, filings_by_ticker={"XYZ": rec([filing(form, "2026-06-01")])})
            self.assertIn("XYZ", out["signals"], f"{form} must be an offering registration")

    def test_s1_not_matched_by_s11_lookalikes(self):
        # S-1MEF is not a listed offering form -> zero offering filings -> audited-clean CHECKED record
        out = oa.resolve_offering_audit(
            as_of=AS_OF, filings_by_ticker={"AAPL": rec([filing("S-1MEF", "2026-06-01")])})
        self.assertNotIn("AAPL", out["signals"])
        self.assertIn("AAPL", out["checked"])

    def test_stale_offering_is_stale(self):
        out = oa.resolve_offering_audit(
            as_of=AS_OF, filings_by_ticker={"AAPL": rec([filing("424B5", "2026-01-01")])})  # ~180d > 90
        sig = out["signals"]["AAPL"]["active_offering"]
        self.assertEqual(sig["recency"], "stale")
        v = classify_hard_veto({"active_offering": sig}, "candidate")
        self.assertEqual(v["veto_tier"], "soft_risk_tag")

    def test_recent_takedown_wins_status_over_older_shelf(self):
        out = oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
            "AAPL": rec([filing("S-3", "2026-02-01"), filing("424B5", "2026-06-15")])})
        sig = out["signals"]["AAPL"]["active_offering"]
        self.assertEqual((sig["recency"], sig["status"]), ("recent", "active"))

    def test_materiality_always_null(self):
        out = oa.resolve_offering_audit(
            as_of=AS_OF, filings_by_ticker={"AAPL": rec([filing("424B5", "2026-05-01")])})
        self.assertIsNone(out["signals"]["AAPL"]["active_offering"]["materiality"])


class NonOfferingAndCleanTests(unittest.TestCase):
    def test_s8_and_25nse_and_8k_ignored(self):
        # all non-offering forms -> zero offering filings -> audited-clean CHECKED record (never a signal/excluded)
        out = oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
            "AAPL": rec([filing("S-8", "2026-05-01"), filing("25-NSE", "2026-05-02"),
                         filing("8-K", "2026-05-03"), filing("10-K", "2026-05-04")])})
        self.assertNotIn("AAPL", out["signals"])
        self.assertNotIn("AAPL", out["excluded"])
        self.assertEqual(out["checked"]["AAPL"]["active_offering"]["disposition"], "audited_no_active_offering")

    def test_full_ok_no_offering_is_audited_checked(self):
        # finding C: a full/ok ticker with NO offering filing emits a CHECKED coverage proof (audited clean),
        # DISTINCT from a never-queried ticker; its provenance is retained, not silently dropped.
        out = oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={"AAPL": rec([])})
        self.assertEqual(out["signals"], {})
        self.assertEqual(out["excluded"], {})
        chk = out["checked"]["AAPL"]["active_offering"]
        self.assertEqual(chk, {"disposition": "audited_no_active_offering",
                               "coverage_status": "full", "parser_status": "ok"})
        self.assertEqual(out["provenance"]["AAPL"]["active_offering"]["contributing_filings"], [])
        self.assertEqual(out["provenance"]["AAPL"]["active_offering"]["provider_id"], "sec_edgar")

    def test_s1_amendment_matched(self):
        out = oa.resolve_offering_audit(
            as_of=AS_OF, filings_by_ticker={"AAPL": rec([filing("S-1/A", "2026-06-01")])})
        self.assertIn("AAPL", out["signals"])


class EmissionFitnessTests(unittest.TestCase):
    def test_partial_coverage_excluded(self):
        out = oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
            "AAPL": rec([filing("424B5", "2026-05-01")], coverage="partial")})
        self.assertNotIn("AAPL", out["signals"])
        self.assertIn("AAPL", out["excluded"])
        self.assertNotIn("AAPL", out["checked"])   # excluded is NOT the same as audited-clean

    def test_failed_parser_excluded(self):
        out = oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
            "AAPL": rec([filing("424B5", "2026-05-01")], parser="failed")})
        self.assertNotIn("AAPL", out["signals"])
        self.assertIn("AAPL", out["excluded"])


class PitClockTests(unittest.TestCase):
    def test_exact_open_rejected(self):
        # exactly 09:30 ET is OUT-OF-WINDOW (half-open, matches resolve_canonical_asof)
        with self.assertRaises(oa.OfferingAuditError):
            oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                "AAPL": rec([filing("424B5", "2026-05-01")], observed_at="2026-06-30T09:30:00-04:00")})

    def test_one_microsecond_before_open_accepted(self):
        out = oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
            "AAPL": rec([filing("424B5", "2026-05-01")], observed_at="2026-06-30T09:29:59.999999-04:00")})
        self.assertIn("AAPL", out["signals"])

    def test_post_open_same_day_rejected(self):
        # a 12:00 ET same-day observation is look-ahead now (the old ET-date-only gate let it through)
        with self.assertRaises(oa.OfferingAuditError):
            oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                "AAPL": rec([filing("424B5", "2026-05-01")], observed_at="2026-06-30T12:00:00-04:00")})

    def test_et_cutoff_not_utc(self):
        # 2026-06-30T13:00:00+00:00 == 09:00 EDT (pre-open, ACCEPT). A naive UTC-vs-09:30 compare would reject it;
        # accepting it proves the cutoff is ET-normalized, not raw UTC (guards a tz flip in the cutoff).
        out = oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
            "AAPL": rec([filing("424B5", "2026-05-01")], observed_at="2026-06-30T13:00:00+00:00")})
        self.assertIn("AAPL", out["signals"])

    def test_utc_z_preopen_accepted(self):
        # 2026-06-30T13:29:00Z == 09:29 EDT (pre-open) -> accepted (Z parsing + ET normalization)
        out = oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
            "AAPL": rec([filing("424B5", "2026-05-01")], observed_at="2026-06-30T13:29:00Z")})
        self.assertIn("AAPL", out["signals"])

    def test_observed_at_next_day_raises(self):
        with self.assertRaises(oa.OfferingAuditError):
            oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                "AAPL": rec([filing("424B5", "2026-05-01")], observed_at="2026-07-01T08:00:00-04:00")})

    def test_offset_cannot_backdate_across_day(self):
        # 2026-07-01T01:00:00-04:00 is ET 2026-07-01 (after the cutoff) -> must raise (offset can't launder look-ahead)
        with self.assertRaises(oa.OfferingAuditError):
            oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                "AAPL": rec([filing("424B5", "2026-05-01")], observed_at="2026-07-01T01:00:00-04:00")})

    def test_observed_before_source_as_of_still_ok(self):
        # observed date == source_as_of == as_of is the boundary; observed date AFTER source_as_of must raise
        with self.assertRaises(oa.OfferingAuditError):
            oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                "AAPL": rec([filing("424B5", "2026-05-01")], source_as_of="2026-06-29")})   # obs 06-30 > src 06-29


class EventChronologyTests(unittest.TestCase):
    def test_same_day_preopen_filing_included(self):
        # a filing accepted 07:00 ET, observed 08:00 ET, all on as_of -> genuinely premarket-known -> INCLUDED
        out = oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
            "AAPL": rec([filing("424B5", "2026-06-30", acceptance="2026-06-30T07:00:00-04:00")])})
        self.assertEqual(out["signals"]["AAPL"]["active_offering"]["status"], "active")

    def test_event_after_observation_excluded(self):
        # a filing accepted 16:00 ET (after the 08:00 ET observation) is NOT premarket evidence -> excluded;
        # the only filing being excluded leaves an audited-clean CHECKED record, never a signal.
        out = oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
            "AAPL": rec([filing("424B5", "2026-06-30", acceptance="2026-06-30T16:00:00-04:00")])})
        self.assertNotIn("AAPL", out["signals"])
        self.assertIn("AAPL", out["checked"])

    def test_bad_acceptance_datetime_raises(self):
        for bad in ("2026-06-30", "2026-06-30T07:00:00", "not-a-time"):   # date-only / naive / garbage
            with self.assertRaises(oa.OfferingAuditError):
                oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                    "AAPL": rec([filing("424B5", "2026-05-01", acceptance=bad)])})


class PitTests(unittest.TestCase):
    def test_future_filing_excluded_from_audit(self):
        # a future-dated (accepted after observation) offering filing must NOT contribute; only one -> audited-clean
        out = oa.resolve_offering_audit(
            as_of=AS_OF, filings_by_ticker={"AAPL": rec([filing("424B5", "2026-07-15")])})
        self.assertNotIn("AAPL", out["signals"])
        self.assertIn("AAPL", out["checked"])

    def test_future_filing_does_not_shift_recency(self):
        out = oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
            "AAPL": rec([filing("424B5", "2026-01-01"), filing("424B5", "2026-07-15")])})  # stale + future
        self.assertEqual(out["signals"]["AAPL"]["active_offering"]["recency"], "stale")   # future ignored

    def test_source_as_of_after_as_of_raises(self):
        with self.assertRaises(oa.OfferingAuditError):
            oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                "AAPL": rec([filing("424B5", "2026-05-01")], source_as_of="2026-07-01")})

    def test_bad_as_of_raises(self):
        for bad in ("2026-6-30", "20260630", "2026-13-01", "not-a-date", "２０２６-06-30"):
            with self.assertRaises(oa.OfferingAuditError):
                oa.resolve_offering_audit(as_of=bad, filings_by_ticker={"AAPL": rec([])})


class ProvenanceTests(unittest.TestCase):
    def _run_bad_prov(self, **mut):
        p = prov()
        p.update(mut)
        return oa.resolve_offering_audit(
            as_of=AS_OF, filings_by_ticker={"AAPL": {"filings": [filing("424B5", "2026-05-01")], "provenance": p}})

    def test_missing_provenance_field_raises(self):
        p = prov(); del p["lineage_ref"]
        with self.assertRaises(oa.OfferingAuditError):
            oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                "AAPL": {"filings": [filing("424B5", "2026-05-01")], "provenance": p}})

    def test_wrong_provider_raises(self):
        with self.assertRaises(oa.OfferingAuditError):
            self._run_bad_prov(provider_id="fmp")

    def test_wrong_endpoint_raises(self):
        with self.assertRaises(oa.OfferingAuditError):
            self._run_bad_prov(endpoint_or_filing_type="company_facts")

    def test_bad_source_as_of_raises(self):
        with self.assertRaises(oa.OfferingAuditError):
            self._run_bad_prov(source_as_of="20260501")

    def test_naive_observed_at_raises(self):
        with self.assertRaises(oa.OfferingAuditError):
            self._run_bad_prov(observed_at="2026-05-01T12:00:00")   # no tz

    def test_bad_coverage_enum_raises(self):
        with self.assertRaises(oa.OfferingAuditError):
            self._run_bad_prov(coverage_status="complete")

    def test_freeform_lineage_raises(self):
        with self.assertRaises(oa.OfferingAuditError):
            self._run_bad_prov(lineage_ref="trust-me")

    def test_coverage_parser_value_type_raises(self):
        # residual-2 B class swept across siblings: a list/dict/bool coverage or parser VALUE must raise the
        # engine error, never a raw TypeError (unhashable) — type-checked before the enum membership test.
        for bad in (["full"], {"x": 1}, True, 1):
            with self.assertRaises(oa.OfferingAuditError):
                self._run_bad_prov(coverage_status=bad)
            with self.assertRaises(oa.OfferingAuditError):
                self._run_bad_prov(parser_status=bad)

    def test_provenance_value_str_subclass_raises(self):
        # WHOLE-CLASS (residual-2 B, swept from Cut 4): a str-subclass provenance VALUE must raise, never leak a
        # raw exception through a !=/<=/parse — exact-str guards on provider/endpoint + type-is-str validators.
        class _StrSub(str):
            pass
        for field, val in (("provider_id", "sec_edgar"), ("source_as_of", "2026-06-30"),
                           ("observed_at", PREOPEN)):
            with self.assertRaises(oa.OfferingAuditError):
                self._run_bad_prov(**{field: _StrSub(val)})

    def test_provenance_carried_with_contributing_filings(self):
        out = oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
            "AAPL": rec([filing("424B5", "2026-05-01", "ACC-1", acceptance="2026-05-01T16:00:00-04:00")])})
        p = out["provenance"]["AAPL"]["active_offering"]
        self.assertEqual(p["provider_id"], "sec_edgar")
        self.assertEqual(p["contributing_filings"], [{"form": "424B5", "filing_date": "2026-05-01",
                                                      "acceptance_datetime": "2026-05-01T16:00:00-04:00",
                                                      "accession": "ACC-1"}])


class SourceRowIdentityTests(unittest.TestCase):
    def test_duplicate_accession_raises(self):
        # two filings sharing one accession = a non-unique source-row identity -> fail-closed (no silent double-count)
        with self.assertRaises(oa.OfferingAuditError):
            oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={"AAPL": rec([
                filing("424B5", "2026-05-01", accession="DUP-1"),
                filing("S-3", "2026-05-02", accession="DUP-1")])})

    def test_blank_accession_raises(self):
        with self.assertRaises(oa.OfferingAuditError):
            oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                "AAPL": rec([filing("424B5", "2026-05-01", accession="")])})

    def test_whitespace_accession_raises(self):
        for bad in (" ", "AC C", "AC\tC", "AC\n"):   # any interior/edge whitespace breaks traceability
            with self.assertRaises(oa.OfferingAuditError):
                oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                    "AAPL": rec([filing("424B5", "2026-05-01", accession=bad)])})

    def test_distinct_accessions_both_kept(self):
        out = oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={"AAPL": rec([
            filing("S-3", "2026-02-01", accession="A-1"), filing("424B5", "2026-06-15", accession="A-2")])})
        cf = out["provenance"]["AAPL"]["active_offering"]["contributing_filings"]
        self.assertEqual([f["accession"] for f in cf], ["A-1", "A-2"])


class _Bomb(str):
    def isascii(self): raise RuntimeError("boom")
    def strip(self, *a): raise RuntimeError("boom")
    def startswith(self, *a): raise RuntimeError("boom")
    def upper(self): raise RuntimeError("boom")
    def __repr__(self): raise RuntimeError("boom")


class HostileValueTests(unittest.TestCase):
    def test_no_raw_leak_from_hostile_str_subclass_values(self):
        # form -> _form_matches (.startswith/==); accession -> `in seen`/repr. Each must fail closed or handle cleanly,
        # never leak a raw RuntimeError.
        cases = [
            lambda: oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                "AAPL": rec([filing(_Bomb("424B5"), "2026-05-01")])}),
            lambda: oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                "AAPL": rec([filing("424B5", "2026-05-01", accession=_Bomb("ACC-1"))])}),
        ]
        for fn in cases:
            try:
                fn()
            except oa.OfferingAuditError:
                pass


class IdentityAndMalformedTests(unittest.TestCase):
    def test_build_from_sec_submissions_rejects_non_sec_accession_shape(self):
        with self.assertRaises(oa.OfferingAuditError):
            oa.build_offering_audit_from_sec_submissions(
                as_of=AS_OF,
                observed_at=PREOPEN,
                submissions_by_ticker={
                    "AAPL": submissions(
                        forms=["424B5"],
                        filing_dates=["2026-05-01"],
                        acceptances=["2026-05-01T16:00:00-04:00"],
                        accessions=["aapl-424b5"],
                    )
                },
            )

    def test_build_from_sec_submissions_rejects_misaligned_recent_arrays(self):
        with self.assertRaises(oa.OfferingAuditError):
            oa.build_offering_audit_from_sec_submissions(
                as_of=AS_OF,
                observed_at=PREOPEN,
                submissions_by_ticker={
                    "AAPL": submissions(
                        forms=["424B5", "10-Q"],
                        filing_dates=["2026-05-01"],
                        acceptances=["2026-05-01T16:00:00-04:00"],
                        accessions=["0000320193-26-000111"],
                    )
                },
            )

    def test_lowercase_ticker_canonicalized(self):
        out = oa.resolve_offering_audit(
            as_of=AS_OF, filings_by_ticker={"aapl": rec([filing("424B5", "2026-05-01")])})
        self.assertIn("AAPL", out["signals"])

    def test_a_share_code_dropped(self):
        out = oa.resolve_offering_audit(
            as_of=AS_OF, filings_by_ticker={"600519": rec([filing("424B5", "2026-05-01")])})
        self.assertEqual(out["signals"], {})   # cross-market key dropped (fail-closed)

    def test_alias_collision_raises(self):
        with self.assertRaises(oa.OfferingAuditError):
            oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                "AAPL": rec([filing("424B5", "2026-05-01")]),
                "aapl": rec([filing("S-3", "2026-05-01")])})

    def test_non_dict_top_raises(self):
        with self.assertRaises(oa.OfferingAuditError):
            oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker=[1, 2, 3])

    def test_none_top_is_empty(self):
        out = oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker=None)
        self.assertEqual(out, {"signals": {}, "provenance": {}, "excluded": {}, "checked": {}})

    def test_wrong_record_keys_raise(self):
        with self.assertRaises(oa.OfferingAuditError):
            oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                "AAPL": {"filings": [], "provenance": prov(), "extra": 1}})

    def test_non_list_filings_raise(self):
        with self.assertRaises(oa.OfferingAuditError):
            oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                "AAPL": {"filings": "nope", "provenance": prov()}})

    def test_wrong_filing_keys_raise(self):
        with self.assertRaises(oa.OfferingAuditError):
            oa.resolve_offering_audit(as_of=AS_OF, filings_by_ticker={
                "AAPL": {"filings": [{"form": "424B5", "filing_date": "2026-05-01"}], "provenance": prov()}})

    def test_hostile_str_subclass_key_excluded(self):
        class Evil(str):
            def upper(self):
                raise RuntimeError("boom")
        # a str-subclass ticker key is excluded (type(k) is not str) BEFORE canonical_us_ticker touches it
        out = oa.resolve_offering_audit(
            as_of=AS_OF, filings_by_ticker={Evil("AAPL"): rec([filing("424B5", "2026-05-01")])})
        self.assertEqual(out["signals"], {})


if __name__ == "__main__":
    unittest.main()
