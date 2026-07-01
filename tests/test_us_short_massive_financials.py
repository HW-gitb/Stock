# -*- coding: utf-8 -*-
"""Offline tests for the US-short Cut 5-b Massive actual-financials source.

Covers the whole class: binding<->const triangulation + schema, canonical identity + hostile-key hardening,
§3.1 provenance + §3.5 PIT (source/observed not after as_of; filing_date is the PIT anchor, period_end is NOT),
timeframe gating (ttm excluded), null/future filing_date exclusion, bound line-item flattening (finite incl
negative; absent concept recorded-missing not fabricated; malformed value/unit fails closed), coverage/parser
emission fitness, and structural fail-closed. No network / provider.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_massive_financials as mf  # noqa: E402

AS_OF = "2026-06-30"


def concept(v, unit="USD"):
    return {"value": v, "unit": unit, "label": "X", "order": 100}


def financials(**overrides):
    f = {
        "income_statement": {
            "revenues": concept(451e9), "gross_profit": concept(180e9),
            "operating_income_loss": concept(120e9), "net_income_loss": concept(100e9),
            "diluted_earnings_per_share": concept(6.5, "USD / shares"),
            "basic_earnings_per_share": concept(6.6, "USD / shares"),
        },
        "balance_sheet": {
            "assets": concept(371e9), "liabilities": concept(300e9), "equity": concept(71e9),
            "current_assets": concept(150e9), "current_liabilities": concept(140e9),
            "long_term_debt": concept(90e9),
        },
        "cash_flow_statement": {"net_cash_flow_from_operating_activities": concept(110e9)},
        "comprehensive_income": {},
    }
    f.update(overrides)
    return f


def period(*, timeframe="quarterly", filing_date="2026-05-01", fiscal_period="Q2", fiscal_year="2026",
           start_date="2025-12-28", end_date="2026-03-28", acceptance="2026-05-01T10:01:00Z", fin=None, **extra):
    p = {
        "timeframe": timeframe, "fiscal_period": fiscal_period, "fiscal_year": fiscal_year,
        "start_date": start_date, "end_date": end_date, "filing_date": filing_date,
        "acceptance_datetime": acceptance, "financials": fin if fin is not None else financials(),
        "cik": "0000320193", "company_name": "Apple Inc.", "sic": "3571", "tickers": ["AAPL"],  # extra, tolerated
    }
    p.update(extra)
    return p


# default observation = 08:00 ET on as_of = PRE-OPEN (strictly before the 09:30 decision open); a 12:00/22:00 ET
# observation would now be look-ahead under the half-open instant cutoff.
PREOPEN = "2026-06-30T08:00:00-04:00"


def prov(*, source_as_of="2026-06-30", observed_at=PREOPEN, coverage="full", parser="ok", rid="cik320193"):
    return {"provider_id": "massive", "endpoint_or_filing_type": "reference_financials",
            "source_as_of": source_as_of, "observed_at": observed_at, "coverage_status": coverage,
            "parser_status": parser, "lineage_ref": f"massive:reference_financials:{source_as_of}#{rid}"}


def rec(periods, **prov_kw):
    return {"periods": periods, "provenance": prov(**prov_kw)}


class BindingTriangulationTests(unittest.TestCase):
    def test_module_consts_equal_binding(self):
        b = mf.load_binding()
        self.assertEqual(b["provider_id"], mf.PROVIDER_ID)
        self.assertEqual(b["endpoint_or_filing_type"], mf.ENDPOINT)
        self.assertEqual(b["decision_timezone"], mf._DECISION_TZ_NAME)
        self.assertEqual(tuple(b["allowed_timeframes"]), mf._ALLOWED_TIMEFRAMES)
        self.assertEqual(set(b["provenance_fields"]), mf._PROVENANCE_FIELDS)
        self.assertEqual(set(b["coverage_status_allowed"]), mf._COVERAGE_ALLOWED)
        self.assertEqual(set(b["parser_status_allowed"]), mf._PARSER_ALLOWED)
        self.assertEqual(b["emission_fitness"]["coverage_status"], mf._COVERAGE_EMIT)
        self.assertEqual(b["emission_fitness"]["parser_status"], mf._PARSER_EMIT)
        self.assertEqual(set(b["bound_line_items"]), set(mf._BOUND_LINE_ITEMS))
        for stmt, concepts in mf._BOUND_LINE_ITEMS.items():
            self.assertEqual(tuple(b["bound_line_items"][stmt]), concepts)
        # machine-policy consts (finding D)
        self.assertEqual(b["pit_clock_contract"]["observed_at_cutoff_operator"], mf._CUTOFF_OPERATOR)
        self.assertEqual(b["pit_clock_contract"]["observed_at_cutoff_reference"], mf._CUTOFF_REFERENCE)
        self.assertEqual(tuple(b["pit_clock_contract"]["chronology_order"]), mf._CHRONOLOGY_ORDER)
        self.assertEqual(tuple(b["duplicate_policy"]["source_row_identity"]), mf._DUPLICATE_IDENTITY)
        self.assertEqual(b["duplicate_policy"]["on_duplicate"], mf._DUPLICATE_POLICY)
        self.assertEqual(b["checked_empty_disposition"], mf._CHECKED_EMPTY_DISPOSITION)
        self.assertEqual(b["lineage_ref_format"]["structure"], mf._LINEAGE_REF_FORMAT)
        self.assertEqual(b["authorization_boundary"], mf._AUTHORIZATION_BOUNDARY)

    def test_binding_matches_schema(self):
        import jsonschema
        schema = json.loads((ROOT / "schemas" / "us_short_cut5_massive_actual_financials_binding.schema.json")
                            .read_text(encoding="utf-8"))
        jsonschema.validate(mf.load_binding(), schema)


class HappyPathTests(unittest.TestCase):
    def test_quarterly_record_flattened_pit_anchored(self):
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={"AAPL": rec([period()])})
        r = out["records"]["AAPL"]
        self.assertEqual(len(r), 1)
        rec0 = r[0]
        self.assertEqual(rec0["filing_date"], "2026-05-01")
        self.assertEqual(rec0["fiscal_period"], "Q2")
        self.assertEqual(rec0["line_items"]["revenues"], 451e9)
        self.assertEqual(rec0["line_items"]["net_cash_flow_from_operating_activities"], 110e9)
        self.assertEqual(rec0["line_items_missing"], [])
        self.assertEqual(out["provenance"]["AAPL"]["skipped_period_count"], 0)

    def test_negative_value_is_legal(self):
        fin = financials()
        fin["income_statement"]["net_income_loss"] = concept(-5e9)   # a net LOSS is legal
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={"AAPL": rec([period(fin=fin)])})
        self.assertEqual(out["records"]["AAPL"][0]["line_items"]["net_income_loss"], -5e9)

    def test_absent_concept_recorded_missing_not_fabricated(self):
        fin = financials()
        del fin["income_statement"]["gross_profit"]                  # genuinely absent -> recorded missing
        del fin["balance_sheet"]                                     # whole statement absent -> all missing
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={"AAPL": rec([period(fin=fin)])})
        rec0 = out["records"]["AAPL"][0]
        self.assertNotIn("gross_profit", rec0["line_items"])
        self.assertIn("income_statement.gross_profit", rec0["line_items_missing"])
        self.assertIn("balance_sheet.assets", rec0["line_items_missing"])

    def test_records_sorted_by_filing_date(self):
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={"AAPL": rec([
            period(filing_date="2026-05-01", fiscal_period="Q2"),
            period(filing_date="2026-02-01", fiscal_period="Q1", timeframe="quarterly"),
        ])})
        self.assertEqual([r["filing_date"] for r in out["records"]["AAPL"]], ["2026-02-01", "2026-05-01"])


class LineItemMalformedTests(unittest.TestCase):
    def test_non_finite_value_raises(self):
        for bad in (float("nan"), float("inf"), True, "451", None):
            fin = financials()
            fin["income_statement"]["revenues"] = {"value": bad, "unit": "USD"}
            with self.assertRaises(mf.MassiveFinancialsError):
                mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={"AAPL": rec([period(fin=fin)])})

    def test_missing_unit_raises(self):
        fin = financials()
        fin["income_statement"]["revenues"] = {"value": 1.0, "unit": ""}
        with self.assertRaises(mf.MassiveFinancialsError):
            mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={"AAPL": rec([period(fin=fin)])})

    def test_non_dict_concept_raises(self):
        fin = financials()
        fin["income_statement"]["revenues"] = 451e9   # bare number, not {value,unit}
        with self.assertRaises(mf.MassiveFinancialsError):
            mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={"AAPL": rec([period(fin=fin)])})

    def test_non_dict_statement_raises(self):
        with self.assertRaises(mf.MassiveFinancialsError):
            mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
                "AAPL": rec([period(fin=financials(income_statement="nope"))])})


class PitTests(unittest.TestCase):
    def test_ttm_timeframe_excluded(self):
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
            "AAPL": rec([period(timeframe="ttm", filing_date=None, fiscal_period="TTM")])})
        self.assertNotIn("AAPL", out["records"])          # no PIT-fit period
        self.assertIn("AAPL", out["checked"])              # but audited -> CHECKED coverage record (finding C)
        self.assertEqual(out["provenance"]["AAPL"]["skipped_period_count"], 1)

    def test_null_filing_date_excluded(self):
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
            "AAPL": rec([period(filing_date=None)])})
        self.assertNotIn("AAPL", out["records"])
        self.assertIn("AAPL", out["checked"])

    def test_malformed_filing_date_raises_not_silently_excluded(self):
        # a bad-SHAPE (non-null, non-YYYY-MM-DD) filing_date is CORRUPT, not a legit null -> fail closed (raise),
        # so a real filed period cannot silently vanish (sibling us_short_sec_offering_audit parity).
        for bad in ("garbagexxxx", "2026/05/01", "2026-13-99", 20260501, 2026.05, " 2026-05-01", "2026-05-01x", ""):
            with self.assertRaises(mf.MassiveFinancialsError):
                mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
                    "AAPL": rec([period(filing_date=bad)])})

    def test_future_acceptance_datetime_excluded(self):
        # a period with a past filing_date but an acceptance instant AFTER as_of is look-ahead evidence -> excluded
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
            "AAPL": rec([period(filing_date="2026-05-01", acceptance="2027-06-01T10:00:00Z")])})
        self.assertNotIn("AAPL", out["records"])

    def test_future_filing_date_excluded(self):
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
            "AAPL": rec([period(filing_date="2026-07-15")])})
        self.assertNotIn("AAPL", out["records"])

    def test_period_end_not_used_as_pit(self):
        # a period whose end_date is <= as_of but whose filing_date is in the FUTURE must be excluded
        # (period_end is not a public date; using it would be look-ahead)
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
            "AAPL": rec([period(end_date="2026-06-28", filing_date="2026-07-30")])})
        self.assertNotIn("AAPL", out["records"])

    def test_skipped_period_counted_alongside_fit(self):
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={"AAPL": rec([
            period(filing_date="2026-05-01"),               # fit
            period(timeframe="ttm", filing_date=None, fiscal_period="TTM"),   # skipped
            period(filing_date="2026-08-01"),               # skipped (future)
        ])})
        self.assertEqual(len(out["records"]["AAPL"]), 1)
        self.assertEqual(out["provenance"]["AAPL"]["skipped_period_count"], 2)

    def test_bad_as_of_raises(self):
        for bad in ("2026-6-30", "20260630", "2026-13-01", "２０２６-06-30"):
            with self.assertRaises(mf.MassiveFinancialsError):
                mf.resolve_actual_financials(as_of=bad, financials_by_ticker={"AAPL": rec([period()])})

    def test_bad_period_dates_raise(self):
        with self.assertRaises(mf.MassiveFinancialsError):
            mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
                "AAPL": rec([period(start_date="2026-03-28", end_date="2025-12-28")])})  # start>end


class ProvenanceTests(unittest.TestCase):
    def _bad(self, **mut):
        p = prov(); p.update(mut)
        return mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
            "AAPL": {"periods": [period()], "provenance": p}})

    def test_missing_field_raises(self):
        p = prov(); del p["lineage_ref"]
        with self.assertRaises(mf.MassiveFinancialsError):
            mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
                "AAPL": {"periods": [period()], "provenance": p}})

    def test_wrong_provider_raises(self):
        with self.assertRaises(mf.MassiveFinancialsError):
            self._bad(provider_id="fmp")

    def test_wrong_endpoint_raises(self):
        with self.assertRaises(mf.MassiveFinancialsError):
            self._bad(endpoint_or_filing_type="aggs")

    def test_source_as_of_after_as_of_raises(self):
        with self.assertRaises(mf.MassiveFinancialsError):
            self._bad(source_as_of="2026-07-01")

    def test_naive_observed_at_raises(self):
        with self.assertRaises(mf.MassiveFinancialsError):
            self._bad(observed_at="2026-06-30T12:00:00")

    def test_observed_at_et_after_as_of_raises(self):
        with self.assertRaises(mf.MassiveFinancialsError):
            self._bad(observed_at="2026-07-01T12:00:00-04:00")

    def test_freeform_lineage_raises(self):
        with self.assertRaises(mf.MassiveFinancialsError):
            self._bad(lineage_ref="trust-me")

    def test_coverage_parser_value_type_raises(self):
        # residual-2 B class swept across siblings: list/dict/bool coverage or parser VALUE must raise, never TypeError
        for bad in (["full"], {"x": 1}, True, 1):
            with self.assertRaises(mf.MassiveFinancialsError):
                self._bad(coverage_status=bad)
            with self.assertRaises(mf.MassiveFinancialsError):
                self._bad(parser_status=bad)

    def test_provenance_value_str_subclass_raises(self):
        # WHOLE-CLASS (residual-2 B, swept from Cut 4): a str-subclass provenance VALUE must raise, never leak raw
        class _StrSub(str):
            pass
        for field, val in (("provider_id", "massive"), ("source_as_of", "2026-06-30"),
                           ("observed_at", PREOPEN)):
            with self.assertRaises(mf.MassiveFinancialsError):
                self._bad(**{field: _StrSub(val)})


class EmissionFitnessTests(unittest.TestCase):
    def test_partial_coverage_excluded(self):
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
            "AAPL": rec([period()], coverage="partial")})
        self.assertNotIn("AAPL", out["records"])
        self.assertIn("AAPL", out["excluded"])

    def test_failed_parser_excluded(self):
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
            "AAPL": rec([period()], parser="failed")})
        self.assertIn("AAPL", out["excluded"])


class IdentityAndMalformedTests(unittest.TestCase):
    def test_lowercase_ticker_canonicalized(self):
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={"aapl": rec([period()])})
        self.assertIn("AAPL", out["records"])

    def test_a_share_code_dropped(self):
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={"600519": rec([period()])})
        self.assertEqual(out["records"], {})

    def test_alias_collision_raises(self):
        with self.assertRaises(mf.MassiveFinancialsError):
            mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
                "AAPL": rec([period()]), "aapl": rec([period()])})

    def test_none_top_is_empty(self):
        self.assertEqual(mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker=None),
                         {"records": {}, "provenance": {}, "excluded": {}, "checked": {}})

    def test_non_dict_top_raises(self):
        with self.assertRaises(mf.MassiveFinancialsError):
            mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker=[1, 2])

    def test_wrong_record_keys_raise(self):
        with self.assertRaises(mf.MassiveFinancialsError):
            mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
                "AAPL": {"periods": [period()], "provenance": prov(), "extra": 1}})

    def test_non_list_periods_raise(self):
        with self.assertRaises(mf.MassiveFinancialsError):
            mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
                "AAPL": {"periods": "nope", "provenance": prov()}})

    def test_period_missing_required_field_raises(self):
        p = period(); del p["filing_date"]
        with self.assertRaises(mf.MassiveFinancialsError):
            mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
                "AAPL": {"periods": [p], "provenance": prov()}})

    def test_hostile_str_subclass_key_excluded(self):
        class Evil(str):
            def upper(self):
                raise RuntimeError("boom")
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={Evil("AAPL"): rec([period()])})
        self.assertEqual(out["records"], {})


class _Bomb(str):
    def isascii(self): raise RuntimeError("boom")
    def strip(self, *a): raise RuntimeError("boom")
    def split(self, *a): raise RuntimeError("boom")
    def upper(self): raise RuntimeError("boom")
    def __eq__(self, o): raise RuntimeError("boom")
    def __hash__(self): raise RuntimeError("boom")
    def __repr__(self): raise RuntimeError("boom")


class HostileValueTests(unittest.TestCase):
    def test_no_raw_leak_from_hostile_str_subclass_values(self):
        # timeframe -> `in _ALLOWED_TIMEFRAMES` (==); fiscal_period/fiscal_year -> identity set (hash) + label.
        # Each must fail closed (MassiveFinancialsError) or be excluded cleanly, never leak a raw RuntimeError.
        cases = [
            lambda: mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
                "AAPL": rec([period(timeframe=_Bomb("quarterly"))])}),
            lambda: mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
                "AAPL": rec([period(fiscal_period=_Bomb("Q2"))])}),
            lambda: mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
                "AAPL": rec([period(fiscal_year=_Bomb("2026"))])}),
        ]
        for fn in cases:
            try:
                fn()
            except mf.MassiveFinancialsError:
                pass


class PitClockTests(unittest.TestCase):
    def test_exact_open_rejected(self):
        with self.assertRaises(mf.MassiveFinancialsError):
            mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
                "AAPL": rec([period()], observed_at="2026-06-30T09:30:00-04:00")})   # exactly 09:30 ET -> out-of-window

    def test_one_microsecond_before_open_accepted(self):
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
            "AAPL": rec([period()], observed_at="2026-06-30T09:29:59.999999-04:00")})
        self.assertIn("AAPL", out["records"])

    def test_post_open_same_day_rejected(self):
        with self.assertRaises(mf.MassiveFinancialsError):
            mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
                "AAPL": rec([period()], observed_at="2026-06-30T12:00:00-04:00")})

    def test_et_cutoff_not_utc(self):
        # 13:00Z == 09:00 EDT (pre-open, ACCEPT); a naive UTC-vs-09:30 compare would reject -> proves ET cutoff
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
            "AAPL": rec([period()], observed_at="2026-06-30T13:00:00+00:00")})
        self.assertIn("AAPL", out["records"])

    def test_observed_after_source_as_of_raises(self):
        with self.assertRaises(mf.MassiveFinancialsError):
            mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
                "AAPL": rec([period()], observed_at="2026-06-30T08:00:00-04:00", source_as_of="2026-06-29")})


class EventChronologyTests(unittest.TestCase):
    def test_event_after_observation_excluded(self):
        # a period accepted 16:00 ET (after the 08:00 ET observation) is not premarket-known -> excluded -> CHECKED
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
            "AAPL": rec([period(filing_date="2026-06-30", acceptance="2026-06-30T16:00:00-04:00")])})
        self.assertNotIn("AAPL", out["records"])
        self.assertIn("AAPL", out["checked"])

    def test_same_day_preopen_period_included(self):
        # accepted 07:00 ET, observed 08:00 ET, all on as_of -> premarket-known -> INCLUDED
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
            "AAPL": rec([period(filing_date="2026-06-30", acceptance="2026-06-30T07:00:00-04:00")])})
        self.assertIn("AAPL", out["records"])


class SourceRowIdentityTests(unittest.TestCase):
    def test_duplicate_fiscal_identity_raises(self):
        # two periods sharing (timeframe, fiscal_year, fiscal_period) = non-unique source-row identity -> fail-closed
        with self.assertRaises(mf.MassiveFinancialsError):
            mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={"AAPL": rec([
                period(filing_date="2026-05-01", fiscal_period="Q2", fiscal_year="2026"),
                period(filing_date="2026-05-02", fiscal_period="Q2", fiscal_year="2026")])})

    def test_distinct_periods_both_kept(self):
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={"AAPL": rec([
            period(filing_date="2026-02-01", fiscal_period="Q1", fiscal_year="2026"),
            period(filing_date="2026-05-01", fiscal_period="Q2", fiscal_year="2026")])})
        self.assertEqual(len(out["records"]["AAPL"]), 2)

    def test_same_period_different_timeframe_not_duplicate(self):
        # a quarterly Q4 and an annual FY are distinct identities (different timeframe) -> both kept
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={"AAPL": rec([
            period(timeframe="quarterly", filing_date="2026-02-01", fiscal_period="Q4", fiscal_year="2025"),
            period(timeframe="annual", filing_date="2026-02-01", fiscal_period="FY", fiscal_year="2025")])})
        self.assertEqual(len(out["records"]["AAPL"]), 2)


class CheckedEmptyTests(unittest.TestCase):
    def test_full_ok_zero_fit_emits_checked(self):
        # finding C: a full/ok ticker with only excluded periods emits a CHECKED coverage proof, retaining provenance
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
            "AAPL": rec([period(timeframe="ttm", filing_date=None, fiscal_period="TTM")])})
        self.assertEqual(out["records"], {})
        chk = out["checked"]["AAPL"]
        self.assertEqual(chk["disposition"], "checked_no_pit_fit_period")
        self.assertEqual((chk["coverage_status"], chk["parser_status"]), ("full", "ok"))
        self.assertEqual(chk["skipped_period_count"], 1)
        self.assertEqual(out["provenance"]["AAPL"]["provider_id"], "massive")

    def test_excluded_not_the_same_as_checked(self):
        out = mf.resolve_actual_financials(as_of=AS_OF, financials_by_ticker={
            "AAPL": rec([period()], coverage="partial")})
        self.assertIn("AAPL", out["excluded"])
        self.assertNotIn("AAPL", out["checked"])


if __name__ == "__main__":
    unittest.main()
