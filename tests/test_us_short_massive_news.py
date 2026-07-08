# -*- coding: utf-8 -*-
"""Offline tests for the US-short Cut 5-d Massive news source.

Covers the whole class: binding<->const triangulation + schema, canonical identity + hostile-key hardening +
ticker-coverage cross-check, §3.1 provenance + §3.5 PIT (published_utc ET <= as_of; future excluded; recency
window), PER-TICKER sentiment extraction from Massive insights (this ticker's insight, never another's; missing /
out-of-enum -> unknown, never fabricated), the sentiment tally, coverage/parser emission fitness, boundary-year
fail-closed, and structural fail-closed. No network / provider.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_massive_news as nw  # noqa: E402

AS_OF = "2026-06-30"


def insight(ticker="AAPL", sentiment="positive", reasoning="because reasons"):
    return {"ticker": ticker, "sentiment": sentiment, "sentiment_reasoning": reasoning}


def news(*, id="n1", published="2026-06-25T12:00:00Z", publisher="The Motley Fool", title="AAPL news",
         tickers=None, insights=None, article_url="https://x/y", **extra):
    r = {"id": id, "published_utc": published, "publisher": {"name": publisher, "homepage_url": "https://p"},
         "title": title, "tickers": tickers if tickers is not None else ["AAPL"],
         "insights": insights if insights is not None else [insight()], "article_url": article_url,
         "author": "A", "description": "D", "keywords": ["k"], "image_url": "https://i"}
    r.update(extra)
    return r


# default observation = 08:00 ET on as_of = PRE-OPEN (strictly before the 09:30 decision open); default news is
# published 2026-06-25 (5 days earlier), comfortably <= observed.
PREOPEN = "2026-06-30T08:00:00-04:00"


def prov(*, source_as_of="2026-06-30", observed_at=PREOPEN, coverage="full", parser="ok", rid="aapl1"):
    return {"provider_id": "massive", "endpoint_or_filing_type": "reference_news",
            "source_as_of": source_as_of, "observed_at": observed_at, "coverage_status": coverage,
            "parser_status": parser, "lineage_ref": f"massive:reference_news:{source_as_of}#{rid}"}


def rec(records, **prov_kw):
    return {"records": records, "provenance": prov(**prov_kw)}


class BindingTriangulationTests(unittest.TestCase):
    def test_module_consts_equal_binding(self):
        b = nw.load_binding()
        self.assertEqual(b["provider_id"], nw.PROVIDER_ID)
        self.assertEqual(b["endpoint_or_filing_type"], nw.ENDPOINT)
        self.assertEqual(b["decision_timezone"], nw._DECISION_TZ_NAME)
        self.assertEqual(b["recency_window_days"], nw._RECENCY_WINDOW_DAYS)
        self.assertEqual(set(b["sentiment_allowed"]), nw._SENTIMENT_ALLOWED)
        self.assertEqual(b["sentiment_unknown"], nw._SENTIMENT_UNKNOWN)
        self.assertEqual(tuple(b["record_fields_required"]), nw._RECORD_REQUIRED)
        self.assertEqual(set(b["provenance_fields"]), nw._PROVENANCE_FIELDS)
        self.assertEqual(set(b["coverage_status_allowed"]), nw._COVERAGE_ALLOWED)
        self.assertEqual(set(b["parser_status_allowed"]), nw._PARSER_ALLOWED)
        self.assertEqual(b["emission_fitness"]["coverage_status"], nw._COVERAGE_EMIT)
        self.assertEqual(b["emission_fitness"]["parser_status"], nw._PARSER_EMIT)
        # machine-policy consts (finding D)
        self.assertEqual(b["pit_clock_contract"]["observed_at_cutoff_operator"], nw._CUTOFF_OPERATOR)
        self.assertEqual(b["pit_clock_contract"]["observed_at_cutoff_reference"], nw._CUTOFF_REFERENCE)
        self.assertEqual(tuple(b["pit_clock_contract"]["chronology_order"]), nw._CHRONOLOGY_ORDER)
        self.assertEqual(b["duplicate_policy"]["source_row_identity"], nw._DUPLICATE_IDENTITY)
        self.assertEqual(b["duplicate_policy"]["publisher_identity_normalization"], nw._PUBLISHER_NORMALIZATION)
        self.assertEqual(b["duplicate_policy"]["on_duplicate"], nw._DUPLICATE_POLICY)
        self.assertEqual(b["checked_empty_disposition"], nw._CHECKED_EMPTY_DISPOSITION)
        self.assertEqual(b["lineage_ref_format"]["structure"], nw._LINEAGE_REF_FORMAT)
        self.assertEqual(b["authorization_boundary"], nw._AUTHORIZATION_BOUNDARY)

    def test_binding_matches_schema(self):
        import jsonschema
        schema = json.loads((ROOT / "schemas" / "us_short_cut5_massive_news_binding.schema.json")
                            .read_text(encoding="utf-8"))
        jsonschema.validate(nw.load_binding(), schema)


class SentimentTests(unittest.TestCase):
    def test_per_ticker_sentiment_picks_this_ticker(self):
        # a multi-ticker article: AAPL insight is negative, TSLA insight is positive -> AAPL must get negative
        item = news(tickers=["AAPL", "TSLA"], insights=[insight("TSLA", "positive"), insight("AAPL", "negative")])
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([item])})
        self.assertEqual(out["records"]["AAPL"][0]["sentiment"], "negative")

    def test_no_matching_insight_is_unknown(self):
        item = news(tickers=["AAPL", "TSLA"], insights=[insight("TSLA", "positive")])  # no AAPL insight
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([item])})
        self.assertEqual(out["records"]["AAPL"][0]["sentiment"], "unknown")

    def test_out_of_enum_sentiment_is_unknown_not_fabricated(self):
        item = news(insights=[insight("AAPL", "bullish")])   # not in {positive,negative,neutral}
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([item])})
        self.assertEqual(out["records"]["AAPL"][0]["sentiment"], "unknown")

    def test_unhashable_sentiment_is_unknown_not_crash(self):
        # an unhashable (list/dict) or non-str sentiment from a hostile payload must fold to unknown per the
        # out-of-enum contract, NOT raise a raw TypeError past the MassiveNewsError contract
        for bad in (["positive"], {"label": "positive"}, 1, None, True):
            item = news(insights=[{"ticker": "AAPL", "sentiment": bad}])
            out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([item])})
            self.assertEqual(out["records"]["AAPL"][0]["sentiment"], "unknown")

    def test_non_dict_insight_elements_tolerated(self):
        item = news(insights=["junk", None, 42, insight("AAPL", "positive")])
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([item])})
        self.assertEqual(out["records"]["AAPL"][0]["sentiment"], "positive")

    def test_sentiment_tally_and_net(self):
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([
            news(id="a", publisher="P1", insights=[insight("AAPL", "positive")]),
            news(id="b", publisher="P2", insights=[insight("AAPL", "positive")]),
            news(id="c", publisher="P1", insights=[insight("AAPL", "negative")]),
            news(id="d", publisher="P3", insights=[insight("AAPL", "neutral")]),
            news(id="e", publisher="P3", insights=[]),   # unknown
        ])})
        s = out["signals"]["AAPL"]["news_recent"]
        self.assertEqual((s["positive"], s["negative"], s["neutral"], s["unknown"]), (2, 1, 1, 1))
        self.assertEqual(s["net_sentiment"], 1)          # 2 - 1
        self.assertEqual(s["news_count"], 5)
        self.assertEqual(s["distinct_publishers"], 3)    # P1, P2, P3

    def test_carries_id_title_url_reasoning(self):
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([news()])})
        r = out["records"]["AAPL"][0]
        self.assertEqual(r["id"], "n1")                  # id carried into output (reverse-lookup / dedup)
        self.assertEqual(r["title"], "AAPL news")
        self.assertEqual(r["article_url"], "https://x/y")
        self.assertEqual(r["sentiment_reasoning"], "because reasons")


class TickerCoverageTests(unittest.TestCase):
    def test_item_not_covering_ticker_raises(self):
        item = news(tickers=["TSLA", "MSFT"])            # AAPL not in tickers -> mis-attribution
        with self.assertRaises(nw.MassiveNewsError):
            nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([item])})

    def test_lowercase_ticker_in_coverage_ok(self):
        item = news(tickers=["aapl", "tsla"])            # canonicalizes to AAPL -> covered
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([item])})
        self.assertIn("AAPL", out["signals"])


class PitTests(unittest.TestCase):
    def test_future_item_excluded_and_counted(self):
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([
            news(id="a", published="2026-06-25T12:00:00Z"),
            news(id="b", published="2026-07-15T12:00:00Z")])})   # future
        self.assertEqual(len(out["records"]["AAPL"]), 1)
        self.assertEqual(out["provenance"]["AAPL"]["future_excluded_count"], 1)

    def test_stale_out_of_window_counted(self):
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([
            news(id="a", published="2026-06-25T12:00:00Z"),
            news(id="b", published="2026-05-01T12:00:00Z")])})   # ~60d > 30d window
        self.assertEqual(len(out["records"]["AAPL"]), 1)
        self.assertEqual(out["provenance"]["AAPL"]["out_of_window_count"], 1)

    def test_stale_window_uses_et_date(self):
        # published 2026-06-01T02:00:00Z == 2026-05-31 22:00 ET; the recency window measures from the ET date, so a
        # boundary item lands on ET 2026-05-31 (29 days before as_of, in the 30d window) not UTC 2026-06-01
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={
            "AAPL": rec([news(published="2026-06-01T02:00:00Z")])})
        self.assertIn("AAPL", out["signals"])

    def test_zero_in_window_emits_checked(self):
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={
            "AAPL": rec([news(published="2026-05-01T12:00:00Z")])})   # only stale
        self.assertNotIn("AAPL", out["signals"])
        self.assertEqual(out["checked"]["AAPL"]["disposition"], "checked_no_recent_news")
        self.assertEqual(out["checked"]["AAPL"]["out_of_window_count"], 1)

    def test_malformed_published_raises(self):
        for bad in ("2026-06-25", "2026-06-25 12:00:00", "garbage", 20260625, "2026-06-25T12:00:00"):  # date-only/naive/etc
            with self.assertRaises(nw.MassiveNewsError):
                nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([news(published=bad)])})

    def test_boundary_year_published_raises_failclosed(self):
        with self.assertRaises(nw.MassiveNewsError):
            nw.resolve_news_events(as_of=AS_OF, news_by_ticker={
                "AAPL": rec([news(published="9999-12-31T23:59:59-14:00")])})

    def test_bad_as_of_raises(self):
        for bad in ("2026-6-30", "20260630", "２０２６-06-30"):
            with self.assertRaises(nw.MassiveNewsError):
                nw.resolve_news_events(as_of=bad, news_by_ticker={"AAPL": rec([news()])})


class ProvenanceTests(unittest.TestCase):
    def _bad(self, **mut):
        p = prov(); p.update(mut)
        return nw.resolve_news_events(as_of=AS_OF, news_by_ticker={
            "AAPL": {"records": [news()], "provenance": p}})

    def test_missing_field_raises(self):
        p = prov(); del p["lineage_ref"]
        with self.assertRaises(nw.MassiveNewsError):
            nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": {"records": [news()], "provenance": p}})

    def test_wrong_provider_raises(self):
        with self.assertRaises(nw.MassiveNewsError):
            self._bad(provider_id="fmp")

    def test_wrong_endpoint_raises(self):
        with self.assertRaises(nw.MassiveNewsError):
            self._bad(endpoint_or_filing_type="reference_financials")

    def test_source_as_of_after_as_of_raises(self):
        with self.assertRaises(nw.MassiveNewsError):
            self._bad(source_as_of="2026-07-01")

    def test_naive_observed_at_raises(self):
        with self.assertRaises(nw.MassiveNewsError):
            self._bad(observed_at="2026-06-30T12:00:00")

    def test_observed_at_et_after_as_of_raises(self):
        with self.assertRaises(nw.MassiveNewsError):
            self._bad(observed_at="2026-07-01T12:00:00-04:00")

    def test_freeform_lineage_raises(self):
        with self.assertRaises(nw.MassiveNewsError):
            self._bad(lineage_ref="trust-me")

    def test_coverage_parser_value_type_raises(self):
        # residual-2 B class swept across siblings: list/dict/bool coverage or parser VALUE must raise, never TypeError
        for bad in (["full"], {"x": 1}, True, 1):
            with self.assertRaises(nw.MassiveNewsError):
                self._bad(coverage_status=bad)
            with self.assertRaises(nw.MassiveNewsError):
                self._bad(parser_status=bad)

    def test_provenance_value_str_subclass_raises(self):
        # WHOLE-CLASS (residual-2 B, swept from Cut 4): a str-subclass provenance VALUE must raise, never leak raw
        class _StrSub(str):
            pass
        for field, val in (("provider_id", "massive"), ("source_as_of", "2026-06-30"),
                           ("observed_at", PREOPEN)):
            with self.assertRaises(nw.MassiveNewsError):
                self._bad(**{field: _StrSub(val)})


class EmissionFitnessTests(unittest.TestCase):
    def test_partial_coverage_excluded(self):
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([news()], coverage="partial")})
        self.assertNotIn("AAPL", out["signals"])
        self.assertIn("AAPL", out["excluded"])

    def test_failed_parser_excluded(self):
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([news()], parser="failed")})
        self.assertIn("AAPL", out["excluded"])


class IdentityAndMalformedTests(unittest.TestCase):
    def test_lowercase_ticker_canonicalized(self):
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"aapl": rec([news(tickers=["AAPL"])])})
        self.assertIn("AAPL", out["signals"])

    def test_a_share_code_dropped(self):
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"600519": rec([news()])})
        self.assertEqual(out["signals"], {})

    def test_alias_collision_raises(self):
        with self.assertRaises(nw.MassiveNewsError):
            nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([news()]), "aapl": rec([news()])})

    def test_none_top_is_empty(self):
        self.assertEqual(nw.resolve_news_events(as_of=AS_OF, news_by_ticker=None),
                         {"signals": {}, "records": {}, "provenance": {}, "excluded": {}, "checked": {}})

    def test_non_dict_top_raises(self):
        with self.assertRaises(nw.MassiveNewsError):
            nw.resolve_news_events(as_of=AS_OF, news_by_ticker=[1, 2])

    def test_wrong_record_keys_raise(self):
        with self.assertRaises(nw.MassiveNewsError):
            nw.resolve_news_events(as_of=AS_OF, news_by_ticker={
                "AAPL": {"records": [news()], "provenance": prov(), "extra": 1}})

    def test_non_list_records_raise(self):
        with self.assertRaises(nw.MassiveNewsError):
            nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": {"records": "no", "provenance": prov()}})

    def test_item_missing_field_raises(self):
        item = news(); del item["title"]          # a genuinely-required field (insights is now OPTIONAL, see below)
        with self.assertRaises(nw.MassiveNewsError):
            nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": {"records": [item], "provenance": prov()}})

    def test_missing_insights_is_optional_unknown(self):
        # A real Massive article may carry NO `insights` key (2026-07-08 live run: ~21% of 1001 articles) -> the item
        # is classified with `unknown` sentiment, NOT fail-closed. R-USSHORT-BATCH5-MASSIVE-NEWS-INSIGHTS-OPTIONAL.
        item = news(); del item["insights"]
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([item])})
        self.assertIn("AAPL", out["signals"])
        self.assertEqual(out["records"]["AAPL"][0]["sentiment"], nw._SENTIMENT_UNKNOWN)

    def test_null_insights_is_optional_unknown(self):
        item = news(); item["insights"] = None    # explicit JSON null == absent -> unknown, not fail-closed
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([item])})
        self.assertIn("AAPL", out["signals"])
        self.assertEqual(out["records"]["AAPL"][0]["sentiment"], nw._SENTIMENT_UNKNOWN)

    def test_publisher_without_name_raises(self):
        item = news(); item["publisher"] = {"homepage_url": "https://x"}
        with self.assertRaises(nw.MassiveNewsError):
            nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([item])})

    def test_non_list_insights_raises(self):
        item = news(); item["insights"] = {"ticker": "AAPL"}
        with self.assertRaises(nw.MassiveNewsError):
            nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([item])})

    def test_hostile_str_subclass_key_excluded(self):
        class Evil(str):
            def upper(self):
                raise RuntimeError("boom")
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={Evil("AAPL"): rec([news()])})
        self.assertEqual(out["signals"], {})


class PitClockTests(unittest.TestCase):
    def test_exact_open_rejected(self):
        with self.assertRaises(nw.MassiveNewsError):
            nw.resolve_news_events(as_of=AS_OF, news_by_ticker={
                "AAPL": rec([news()], observed_at="2026-06-30T09:30:00-04:00")})   # exactly 09:30 ET

    def test_one_microsecond_before_open_accepted(self):
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={
            "AAPL": rec([news()], observed_at="2026-06-30T09:29:59.999999-04:00")})
        self.assertIn("AAPL", out["signals"])

    def test_post_open_same_day_rejected(self):
        with self.assertRaises(nw.MassiveNewsError):
            nw.resolve_news_events(as_of=AS_OF, news_by_ticker={
                "AAPL": rec([news()], observed_at="2026-06-30T12:00:00-04:00")})

    def test_et_cutoff_not_utc(self):
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={
            "AAPL": rec([news()], observed_at="2026-06-30T13:00:00+00:00")})   # 09:00 EDT, pre-open
        self.assertIn("AAPL", out["signals"])


class EventChronologyTests(unittest.TestCase):
    def test_published_after_observation_excluded(self):
        # a news item published 16:00 ET, observed 08:00 ET -> event-after-observation -> excluded -> CHECKED
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={
            "AAPL": rec([news(published="2026-06-30T16:00:00-04:00")], observed_at="2026-06-30T08:00:00-04:00")})
        self.assertNotIn("AAPL", out["signals"])
        self.assertIn("AAPL", out["checked"])
        self.assertEqual(out["checked"]["AAPL"]["future_excluded_count"], 1)

    def test_same_instant_published_and_observed_included(self):
        # published exactly at the observation instant (<=) is in-window
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={
            "AAPL": rec([news(published="2026-06-30T08:00:00-04:00")], observed_at="2026-06-30T08:00:00-04:00")})
        self.assertIn("AAPL", out["signals"])


class SourceRowIdentityTests(unittest.TestCase):
    def test_duplicate_id_raises(self):
        # two items sharing one id = a non-unique source-row identity -> fail-closed (no count/net inflation)
        with self.assertRaises(nw.MassiveNewsError):
            nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([
                news(id="dup", insights=[insight("AAPL", "negative")]),
                news(id="dup", insights=[insight("AAPL", "negative")])])})

    def test_publisher_case_and_whitespace_variants_are_one(self):
        # `The Motley Fool`, ` the motley fool `, `THE MOTLEY FOOL` are ONE publisher (strip + casefold)
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([
            news(id="a", publisher="The Motley Fool"),
            news(id="b", publisher=" the motley fool "),
            news(id="c", publisher="THE  MOTLEY  FOOL")])})
        self.assertEqual(out["signals"]["AAPL"]["news_recent"]["distinct_publishers"], 1)

    def test_whitespace_only_publisher_raises(self):
        for bad in (" ", "\t", "\n"):
            item = news(); item["publisher"] = {"name": bad}
            with self.assertRaises(nw.MassiveNewsError):
                nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([item])})

    def test_distinct_publishers_still_distinct(self):
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([
            news(id="a", publisher="Reuters"), news(id="b", publisher="Bloomberg")])})
        self.assertEqual(out["signals"]["AAPL"]["news_recent"]["distinct_publishers"], 2)


class _Bomb(str):
    """A str subclass whose every dispatched method raises — proves a value guarded only by isinstance would leak a
    raw exception, and that the exact-str (`type(x) is str`) guard rejects it BEFORE any dispatch."""
    def isascii(self): raise RuntimeError("boom")
    def strip(self, *a): raise RuntimeError("boom")
    def split(self, *a): raise RuntimeError("boom")
    def startswith(self, *a): raise RuntimeError("boom")
    def upper(self): raise RuntimeError("boom")
    def casefold(self): raise RuntimeError("boom")
    def __repr__(self): raise RuntimeError("boom")


class HostileValueTests(unittest.TestCase):
    def test_no_raw_leak_from_hostile_str_subclass_values(self):
        # each injects a hostile str-subclass VALUE (not key) at a site that canonicalizes / splits / hashes / repr's
        # it; the engine must fail closed (MassiveNewsError) or handle it cleanly — never leak a raw RuntimeError.
        b = _Bomb("AAPL")
        cases = [
            lambda: nw.resolve_news_events(as_of=AS_OF, news_by_ticker={
                "AAPL": rec([news(insights=[{"ticker": _Bomb("AAPL"), "sentiment": "positive"}])])}),
            lambda: nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([news(tickers=[b])])}),
            lambda: nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([news(id=_Bomb("n1"))])}),
            lambda: nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([news(publisher=_Bomb("Pub"))])}),
        ]
        for fn in cases:
            try:
                fn()
            except nw.MassiveNewsError:
                pass   # a domain error is fine; a raw RuntimeError would propagate and fail this test


class CheckedEmptyTests(unittest.TestCase):
    def test_full_ok_zero_fit_emits_checked(self):
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={
            "AAPL": rec([news(published="2026-05-01T12:00:00Z")])})   # only stale
        self.assertEqual(out["signals"], {})
        chk = out["checked"]["AAPL"]
        self.assertEqual((chk["disposition"], chk["coverage_status"], chk["parser_status"]),
                         ("checked_no_recent_news", "full", "ok"))
        self.assertEqual(out["provenance"]["AAPL"]["provider_id"], "massive")

    def test_excluded_not_the_same_as_checked(self):
        out = nw.resolve_news_events(as_of=AS_OF, news_by_ticker={"AAPL": rec([news()], coverage="partial")})
        self.assertIn("AAPL", out["excluded"])
        self.assertNotIn("AAPL", out["checked"])


if __name__ == "__main__":
    unittest.main()
