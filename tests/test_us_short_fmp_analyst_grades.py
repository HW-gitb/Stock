# -*- coding: utf-8 -*-
"""Offline tests for the US-short Cut 5-c FMP analyst-grades source.

Covers the whole class: binding<->const triangulation + schema, canonical identity + hostile-key hardening +
symbol cross-check, §3.1 provenance + §3.5 PIT (date <= as_of; future excluded; recency window out-of-window),
direction from FMP's own action (upgrade/downgrade/else->neutral, never fabricated), the net/distinct-firms
summary, coverage/parser emission fitness, and structural fail-closed. No network / provider.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_fmp_analyst_grades as g  # noqa: E402

AS_OF = "2026-06-30"


def grade(*, date="2026-06-01", action="upgrade", company="BankX", new="Buy", prev="Hold", **extra):
    r = {"symbol": "AAPL", "date": date, "gradingCompany": company, "newGrade": new,
         "previousGrade": prev, "action": action}
    r.update(extra)
    return r


# default observation = 08:00 ET on as_of = PRE-OPEN (strictly before the 09:30 decision open)
PREOPEN = "2026-06-30T08:00:00-04:00"


def prov(*, source_as_of="2026-06-30", observed_at=PREOPEN, coverage="full", parser="ok", rid="aapl1"):
    return {"provider_id": "fmp", "endpoint_or_filing_type": "grades",
            "source_as_of": source_as_of, "observed_at": observed_at, "coverage_status": coverage,
            "parser_status": parser, "lineage_ref": f"fmp:grades:{source_as_of}#{rid}"}


def rec(records, **prov_kw):
    return {"records": records, "provenance": prov(**prov_kw)}


class BindingTriangulationTests(unittest.TestCase):
    def test_module_consts_equal_binding(self):
        b = g.load_binding()
        self.assertEqual(b["provider_id"], g.PROVIDER_ID)
        self.assertEqual(b["endpoint_or_filing_type"], g.ENDPOINT)
        self.assertEqual(b["decision_timezone"], g._DECISION_TZ_NAME)
        self.assertEqual(b["recency_window_days"], g._RECENCY_WINDOW_DAYS)
        self.assertEqual(tuple(b["record_fields_required"]), g._RECORD_REQUIRED)
        self.assertEqual(set(b["provenance_fields"]), g._PROVENANCE_FIELDS)
        self.assertEqual(set(b["coverage_status_allowed"]), g._COVERAGE_ALLOWED)
        self.assertEqual(set(b["parser_status_allowed"]), g._PARSER_ALLOWED)
        self.assertEqual(b["emission_fitness"]["coverage_status"], g._COVERAGE_EMIT)
        self.assertEqual(b["emission_fitness"]["parser_status"], g._PARSER_EMIT)
        dm = dict(b["direction_map"])
        self.assertEqual(dm.pop("_default"), g._DIRECTION_DEFAULT)
        self.assertEqual(dm, g._DIRECTION_MAP)
        # machine-policy consts (finding D)
        self.assertEqual(b["pit_clock_contract"]["observed_at_cutoff_operator"], g._CUTOFF_OPERATOR)
        self.assertEqual(b["pit_clock_contract"]["observed_at_cutoff_reference"], g._CUTOFF_REFERENCE)
        self.assertEqual(tuple(b["pit_clock_contract"]["chronology_order"]), g._CHRONOLOGY_ORDER)
        self.assertEqual(tuple(b["duplicate_policy"]["source_row_identity"]), g._DUPLICATE_IDENTITY)
        self.assertEqual(b["duplicate_policy"]["firm_identity_normalization"], g._FIRM_NORMALIZATION)
        self.assertEqual(b["duplicate_policy"]["on_duplicate"], g._DUPLICATE_POLICY)
        self.assertEqual(b["checked_empty_disposition"], g._CHECKED_EMPTY_DISPOSITION)
        self.assertEqual(b["lineage_ref_format"]["structure"], g._LINEAGE_REF_FORMAT)
        self.assertEqual(b["authorization_boundary"], g._AUTHORIZATION_BOUNDARY)

    def test_binding_matches_schema(self):
        import jsonschema
        schema = json.loads((ROOT / "schemas" / "us_short_cut5_fmp_analyst_grades_binding.schema.json")
                            .read_text(encoding="utf-8"))
        jsonschema.validate(g.load_binding(), schema)


class DirectionAndSummaryTests(unittest.TestCase):
    def test_direction_from_action(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={"AAPL": rec([
            grade(action="upgrade", company="A"),
            grade(action="downgrade", company="B"),
            grade(action="maintain", company="C"),
        ])})
        dirs = {r["action"]: r["direction"] for r in out["records"]["AAPL"]}
        self.assertEqual(dirs, {"upgrade": "up", "downgrade": "down", "maintain": "neutral"})

    def test_unknown_action_is_neutral_not_fabricated(self):
        for action in ("initiate", "reiterate", "hold", "xyzzy"):
            out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
                "AAPL": rec([grade(action=action)])})
            self.assertEqual(out["records"]["AAPL"][0]["direction"], "neutral")

    def test_summary_net_and_distinct_firms(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={"AAPL": rec([
            grade(action="upgrade", company="A"), grade(action="upgrade", company="B"),
            grade(action="downgrade", company="A"), grade(action="maintain", company="C"),
        ])})
        s = out["signals"]["AAPL"]["analyst_actions_recent"]
        self.assertEqual((s["upgrades"], s["downgrades"], s["neutrals"], s["net"]), (2, 1, 1, 1))
        self.assertEqual(s["distinct_firms"], 3)         # A, B, C distinct
        self.assertEqual(s["window_days"], 90)

    def test_records_sorted_by_date(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={"AAPL": rec([
            grade(date="2026-06-20"), grade(date="2026-05-05"), grade(date="2026-06-01")])})
        self.assertEqual([r["date"] for r in out["records"]["AAPL"]], ["2026-05-05", "2026-06-01", "2026-06-20"])

    def test_empty_previous_grade_allowed(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
            "AAPL": rec([grade(action="initiate", prev="")])})   # an initiate has no prior grade
        self.assertEqual(out["records"]["AAPL"][0]["previous_grade"], "")


class PitTests(unittest.TestCase):
    def test_future_date_excluded_and_counted(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={"AAPL": rec([
            grade(date="2026-06-01"), grade(date="2026-07-15")])})   # one fit, one future
        self.assertEqual(len(out["records"]["AAPL"]), 1)
        self.assertEqual(out["provenance"]["AAPL"]["future_excluded_count"], 1)

    def test_stale_out_of_window_counted_not_scored(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={"AAPL": rec([
            grade(date="2026-06-01"), grade(date="2026-01-01")])})   # one fit, one >90d stale
        self.assertEqual(len(out["records"]["AAPL"]), 1)
        self.assertEqual(out["provenance"]["AAPL"]["out_of_window_count"], 1)
        self.assertEqual(out["provenance"]["AAPL"]["total_record_count"], 2)

    def test_date_equal_as_of_included(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
            "AAPL": rec([grade(date=AS_OF)])})
        self.assertEqual(len(out["records"]["AAPL"]), 1)

    def test_zero_in_window_emits_checked(self):
        # finding C: only stale -> no recent activity -> no signal, but audited -> CHECKED coverage record
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
            "AAPL": rec([grade(date="2026-01-01")])})
        self.assertNotIn("AAPL", out["signals"])
        self.assertNotIn("AAPL", out["records"])
        self.assertEqual(out["checked"]["AAPL"]["disposition"], "checked_no_recent_activity")
        self.assertEqual(out["checked"]["AAPL"]["out_of_window_count"], 1)

    def test_malformed_date_raises(self):
        for bad in ("garbage", "2026/06/01", "2026-13-99", 20260601, ""):
            with self.assertRaises(g.FmpGradesError):
                g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
                    "AAPL": rec([grade(date=bad)])})

    def test_bad_as_of_raises(self):
        for bad in ("2026-6-30", "20260630", "２０２６-06-30"):
            with self.assertRaises(g.FmpGradesError):
                g.resolve_analyst_grade_actions(as_of=bad, grades_by_ticker={"AAPL": rec([grade()])})


class ProvenanceTests(unittest.TestCase):
    def _bad(self, **mut):
        p = prov(); p.update(mut)
        return g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
            "AAPL": {"records": [grade()], "provenance": p}})

    def test_missing_field_raises(self):
        p = prov(); del p["lineage_ref"]
        with self.assertRaises(g.FmpGradesError):
            g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
                "AAPL": {"records": [grade()], "provenance": p}})

    def test_wrong_provider_raises(self):
        with self.assertRaises(g.FmpGradesError):
            self._bad(provider_id="massive")

    def test_wrong_endpoint_raises(self):
        with self.assertRaises(g.FmpGradesError):
            self._bad(endpoint_or_filing_type="profile")

    def test_source_as_of_after_as_of_raises(self):
        with self.assertRaises(g.FmpGradesError):
            self._bad(source_as_of="2026-07-01")

    def test_naive_observed_at_raises(self):
        with self.assertRaises(g.FmpGradesError):
            self._bad(observed_at="2026-06-30T12:00:00")

    def test_observed_at_et_after_as_of_raises(self):
        with self.assertRaises(g.FmpGradesError):
            self._bad(observed_at="2026-07-01T12:00:00-04:00")

    def test_freeform_lineage_raises(self):
        with self.assertRaises(g.FmpGradesError):
            self._bad(lineage_ref="trust-me")

    def test_coverage_parser_value_type_raises(self):
        # residual-2 B class swept across siblings: list/dict/bool coverage or parser VALUE must raise, never TypeError
        for bad in (["full"], {"x": 1}, True, 1):
            with self.assertRaises(g.FmpGradesError):
                self._bad(coverage_status=bad)
            with self.assertRaises(g.FmpGradesError):
                self._bad(parser_status=bad)

    def test_provenance_value_str_subclass_raises(self):
        # WHOLE-CLASS (residual-2 B, swept from Cut 4): a str-subclass provenance VALUE must raise, never leak raw
        class _StrSub(str):
            pass
        for field, val in (("provider_id", "fmp"), ("source_as_of", "2026-06-30"),
                           ("observed_at", PREOPEN)):
            with self.assertRaises(g.FmpGradesError):
                self._bad(**{field: _StrSub(val)})

    def test_boundary_year_observed_at_raises_failclosed(self):
        # an absurd boundary-year observed_at (no real provider clock) must fail as FmpGradesError, NOT a raw
        # OverflowError leaking past the contract (tz conversion overflow guard)
        for bad in ("9999-12-31T23:59:59-14:00", "0001-01-01T00:00:00+14:00"):
            with self.assertRaises(g.FmpGradesError):
                self._bad(observed_at=bad)


class EmissionFitnessTests(unittest.TestCase):
    def test_partial_coverage_excluded(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
            "AAPL": rec([grade()], coverage="partial")})
        self.assertNotIn("AAPL", out["signals"])
        self.assertIn("AAPL", out["excluded"])

    def test_failed_parser_excluded(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
            "AAPL": rec([grade()], parser="failed")})
        self.assertIn("AAPL", out["excluded"])


class IdentityAndMalformedTests(unittest.TestCase):
    def test_lowercase_ticker_canonicalized(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
            "aapl": rec([grade(symbol="aapl")])})
        self.assertIn("AAPL", out["signals"])

    def test_a_share_code_dropped(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={"600519": rec([grade()])})
        self.assertEqual(out["signals"], {})

    def test_alias_collision_raises(self):
        with self.assertRaises(g.FmpGradesError):
            g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
                "AAPL": rec([grade()]), "aapl": rec([grade()])})

    def test_symbol_mismatch_raises(self):
        with self.assertRaises(g.FmpGradesError):
            g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
                "AAPL": rec([grade(symbol="MSFT")])})   # record symbol disagrees with ticker key

    def test_missing_symbol_key_tolerated(self):
        rr = grade(); del rr["symbol"]                  # symbol is optional (only cross-checked if present)
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={"AAPL": rec([rr])})
        self.assertIn("AAPL", out["signals"])

    def test_none_top_is_empty(self):
        self.assertEqual(g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker=None),
                         {"signals": {}, "records": {}, "provenance": {}, "excluded": {}, "checked": {}})

    def test_non_dict_top_raises(self):
        with self.assertRaises(g.FmpGradesError):
            g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker=[1, 2])

    def test_wrong_record_keys_raise(self):
        with self.assertRaises(g.FmpGradesError):
            g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
                "AAPL": {"records": [grade()], "provenance": prov(), "extra": 1}})

    def test_non_list_records_raise(self):
        with self.assertRaises(g.FmpGradesError):
            g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
                "AAPL": {"records": "nope", "provenance": prov()}})

    def test_record_missing_field_raises(self):
        rr = grade(); del rr["action"]
        with self.assertRaises(g.FmpGradesError):
            g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
                "AAPL": {"records": [rr], "provenance": prov()}})

    def test_non_str_action_raises(self):
        with self.assertRaises(g.FmpGradesError):
            g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
                "AAPL": rec([grade(action=1)])})

    def test_hostile_str_subclass_key_excluded(self):
        class Evil(str):
            def upper(self):
                raise RuntimeError("boom")
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={Evil("AAPL"): rec([grade()])})
        self.assertEqual(out["signals"], {})


class _Bomb(str):
    def isascii(self): raise RuntimeError("boom")
    def strip(self, *a): raise RuntimeError("boom")
    def split(self, *a): raise RuntimeError("boom")
    def upper(self): raise RuntimeError("boom")
    def casefold(self): raise RuntimeError("boom")
    def __repr__(self): raise RuntimeError("boom")


class HostileValueTests(unittest.TestCase):
    def test_no_raw_leak_from_hostile_str_subclass_values(self):
        # action -> _DIRECTION_MAP.get (hash); company -> .split()/.casefold(); new/prev_grade -> identity set (hash);
        # symbol -> canonical. Each must fail closed (FmpGradesError), never leak a raw RuntimeError.
        b = _Bomb("upgrade")
        cases = [
            lambda: g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={"AAPL": rec([grade(action=b)])}),
            lambda: g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={"AAPL": rec([grade(company=_Bomb("BankX"))])}),
            lambda: g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={"AAPL": rec([grade(new=_Bomb("Buy"))])}),
            lambda: g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={"AAPL": rec([grade(prev=_Bomb("Hold"))])}),
            lambda: g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={"AAPL": rec([grade(symbol=_Bomb("AAPL"))])}),
        ]
        for fn in cases:
            try:
                fn()
            except g.FmpGradesError:
                pass


class PitClockTests(unittest.TestCase):
    def test_exact_open_rejected(self):
        with self.assertRaises(g.FmpGradesError):
            g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
                "AAPL": rec([grade()], observed_at="2026-06-30T09:30:00-04:00")})   # exactly 09:30 ET

    def test_one_microsecond_before_open_accepted(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
            "AAPL": rec([grade()], observed_at="2026-06-30T09:29:59.999999-04:00")})
        self.assertIn("AAPL", out["signals"])

    def test_post_open_same_day_rejected(self):
        with self.assertRaises(g.FmpGradesError):
            g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
                "AAPL": rec([grade()], observed_at="2026-06-30T12:00:00-04:00")})

    def test_et_cutoff_not_utc(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
            "AAPL": rec([grade()], observed_at="2026-06-30T13:00:00+00:00")})   # 09:00 EDT, pre-open
        self.assertIn("AAPL", out["signals"])

    def test_same_day_grade_excluded_when_observed_prior_day(self):
        # a grade dated as_of but observed the day BEFORE (pre-open) is dated after the observation -> excluded
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
            "AAPL": rec([grade(date="2026-06-30")], observed_at="2026-06-29T08:00:00-04:00", source_as_of="2026-06-29")})
        self.assertNotIn("AAPL", out["signals"])          # date 06-30 > obs_date 06-29 -> future -> excluded
        self.assertEqual(out["checked"]["AAPL"]["future_excluded_count"], 1)


class SourceRowIdentityTests(unittest.TestCase):
    def test_duplicate_action_raises(self):
        # two byte-identical grade actions = a non-unique source-row identity -> fail-closed (no net/firm inflation)
        with self.assertRaises(g.FmpGradesError):
            g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={"AAPL": rec([
                grade(date="2026-06-01", action="downgrade", company="BankX", new="Sell", prev="Hold"),
                grade(date="2026-06-01", action="downgrade", company="BankX", new="Sell", prev="Hold")])})

    def test_firm_case_and_whitespace_variants_are_one_firm(self):
        # `BankX`, ` bankx `, `BANKX` are ONE firm (strip + casefold) -> distinct_firms == 1, not 3; the three
        # actions differ only by firm surface so their identities collapse in count but the actions differ by nothing
        # else -> they would be duplicates; use distinct grades (different new grade) to keep 3 actions, 1 firm.
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={"AAPL": rec([
            grade(date="2026-06-01", company="BankX", new="Buy"),
            grade(date="2026-06-02", company=" bankx ", new="Hold"),
            grade(date="2026-06-03", company="BANKX", new="Sell")])})
        self.assertEqual(out["signals"]["AAPL"]["analyst_actions_recent"]["distinct_firms"], 1)

    def test_whitespace_only_firm_raises(self):
        for bad in (" ", "\t", "\n"):
            with self.assertRaises(g.FmpGradesError):
                g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
                    "AAPL": rec([grade(company=bad)])})

    def test_distinct_firms_still_distinct(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={"AAPL": rec([
            grade(date="2026-06-01", company="Alpha"), grade(date="2026-06-02", company="Beta")])})
        self.assertEqual(out["signals"]["AAPL"]["analyst_actions_recent"]["distinct_firms"], 2)


class CheckedEmptyTests(unittest.TestCase):
    def test_full_ok_zero_fit_emits_checked(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
            "AAPL": rec([grade(date="2026-01-01")])})   # only stale
        self.assertEqual(out["signals"], {})
        chk = out["checked"]["AAPL"]
        self.assertEqual((chk["disposition"], chk["coverage_status"], chk["parser_status"]),
                         ("checked_no_recent_activity", "full", "ok"))
        self.assertEqual(out["provenance"]["AAPL"]["provider_id"], "fmp")

    def test_excluded_not_the_same_as_checked(self):
        out = g.resolve_analyst_grade_actions(as_of=AS_OF, grades_by_ticker={
            "AAPL": rec([grade()], coverage="partial")})
        self.assertIn("AAPL", out["excluded"])
        self.assertNotIn("AAPL", out["checked"])


if __name__ == "__main__":
    unittest.main()
