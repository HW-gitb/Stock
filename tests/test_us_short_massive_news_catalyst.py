import unittest
from importlib import import_module

from engine.us_short_catalyst import load_catalyst_governance
from engine.us_short_core_score import core_score
from engine.us_short_massive_news import resolve_news_events
from engine.us_short_massive_news_catalyst import (
    BINDING_PATH,
    COVERAGE_DISPOSITIONS,
    OUTPUT_KEYS,
    PRODUCER_REFS,
    PROJECTION_POLICY,
    MassiveNewsCatalystSeamError,
    load_binding,
    project_massive_news_catalyst,
)


NEWS_AS_OF = "2026-06-30"
CATALYST_AS_OF = "20260630"
GOV = load_catalyst_governance()


def _insight(ticker="AAPL", sentiment="positive"):
    return {
        "ticker": ticker,
        "sentiment": sentiment,
        "sentiment_reasoning": "source sentiment",
    }


def _news(*, id="n1", ticker="AAPL", published="2026-06-25T12:00:00Z", sentiment="positive"):
    return {
        "id": id,
        "published_utc": published,
        "publisher": {"name": "Publisher"},
        "title": f"{ticker} news",
        "article_url": "https://example.test/news",
        "tickers": [ticker],
        "insights": [_insight(ticker, sentiment)],
    }


def _prov(*, ticker="AAPL", coverage="full", parser="ok", rid="source1"):
    return {
        "provider_id": "massive",
        "endpoint_or_filing_type": "reference_news",
        "source_as_of": NEWS_AS_OF,
        "observed_at": "2026-06-30T08:00:00-04:00",
        "coverage_status": coverage,
        "parser_status": parser,
        "lineage_ref": f"massive:reference_news:{NEWS_AS_OF}#{ticker.lower()}-{rid}",
    }


def _record(records, *, ticker="AAPL", coverage="full", parser="ok"):
    return {
        "records": records,
        "provenance": _prov(ticker=ticker, coverage=coverage, parser=parser),
    }


class MassiveNewsCatalystProjectionTest(unittest.TestCase):
    def test_projects_real_massive_news_output_to_catalyst_score_and_neutral_states(self):
        source = resolve_news_events(
            as_of=NEWS_AS_OF,
            news_by_ticker={
                "AAPL": _record([
                    _news(id="a", sentiment="positive"),
                    _news(id="b", sentiment="positive"),
                    _news(id="c", sentiment="neutral"),
                ]),
                "MSFT": _record([], ticker="MSFT"),
                "JPM": _record([_news(ticker="JPM")], ticker="JPM", coverage="partial"),
            },
        )

        result = project_massive_news_catalyst(
            news_events=source,
            governance=GOV,
            as_of=CATALYST_AS_OF,
            target_tickers=["AAPL", "MSFT", "JPM", "AMZN"],
        )

        self.assertEqual(result["target_count"], 4)
        self.assertEqual(result["scored_count"], 1)
        self.assertAlmostEqual(result["catalyst_block_by_ticker"]["AAPL"], 54.0)
        self.assertEqual(result["neutral_fill_tickers"], ["MSFT", "JPM", "AMZN"])
        self.assertEqual(
            result["coverage"],
            {
                "AAPL": "scored_realized_catalyst",
                "MSFT": "neutral_no_realized_catalyst",
                "JPM": "neutral_source_excluded",
                "AMZN": "neutral_missing_catalyst_source",
            },
        )

    def test_negative_news_cluster_lowers_the_bounded_catalyst_score(self):
        source = resolve_news_events(
            as_of=NEWS_AS_OF,
            news_by_ticker={
                "AAPL": _record([
                    _news(id="a", sentiment="negative"),
                    _news(id="b", sentiment="negative"),
                ]),
            },
        )

        result = project_massive_news_catalyst(
            news_events=source,
            governance=GOV,
            as_of=CATALYST_AS_OF,
            target_tickers=["AAPL"],
        )

        self.assertEqual(result["coverage"]["AAPL"], "scored_realized_catalyst")
        self.assertAlmostEqual(result["catalyst_block_by_ticker"]["AAPL"], 44.0)

    def test_projection_can_feed_core_score_as_the_catalyst_block(self):
        source = resolve_news_events(
            as_of=NEWS_AS_OF,
            news_by_ticker={
                "AAPL": _record([_news(id="a", sentiment="positive")]),
            },
        )
        result = project_massive_news_catalyst(
            news_events=source,
            governance=GOV,
            as_of=CATALYST_AS_OF,
            target_tickers=["AAPL"],
        )

        scored = core_score({
            "momentum": 50.0,
            "theme": 50.0,
            "catalyst": result["catalyst_block_by_ticker"]["AAPL"],
        })

        self.assertAlmostEqual(scored["core_score"], 51.5)

    def test_rejects_tally_drift_before_scoring(self):
        source = resolve_news_events(
            as_of=NEWS_AS_OF,
            news_by_ticker={"AAPL": _record([_news(sentiment="positive")])},
        )
        source["signals"]["AAPL"]["news_recent"]["net_sentiment"] = 2

        with self.assertRaisesRegex(MassiveNewsCatalystSeamError, "tally"):
            project_massive_news_catalyst(
                news_events=source,
                governance=GOV,
                as_of=CATALYST_AS_OF,
                target_tickers=["AAPL"],
            )

    def test_rejects_duplicate_target_identity(self):
        source = resolve_news_events(
            as_of=NEWS_AS_OF,
            news_by_ticker={"AAPL": _record([_news(sentiment="positive")])},
        )

        with self.assertRaisesRegex(MassiveNewsCatalystSeamError, "duplicate"):
            project_massive_news_catalyst(
                news_events=source,
                governance=GOV,
                as_of=CATALYST_AS_OF,
                target_tickers=["AAPL", " aapl "],
            )

    def test_rejects_bad_news_events_shape(self):
        source = resolve_news_events(
            as_of=NEWS_AS_OF,
            news_by_ticker={"AAPL": _record([_news(sentiment="positive")])},
        )
        source["extra"] = True

        with self.assertRaisesRegex(MassiveNewsCatalystSeamError, "keys"):
            project_massive_news_catalyst(
                news_events=source,
                governance=GOV,
                as_of=CATALYST_AS_OF,
                target_tickers=["AAPL"],
            )

    def test_binding_conformance(self):
        binding = load_binding()

        self.assertTrue(str(BINDING_PATH).endswith(binding["artifact_id"] + ".json"))
        self.assertEqual(OUTPUT_KEYS, tuple(binding["output_contract"]["required_keys"]))
        self.assertEqual(PRODUCER_REFS, tuple(binding["producer_refs"]))
        self.assertEqual(PROJECTION_POLICY, binding["projection_policy"])
        self.assertEqual(COVERAGE_DISPOSITIONS, tuple(binding["output_contract"]["coverage_dispositions"]))
        self.assertEqual(binding["scoring_transform"]["score_formula"], "net_sentiment / news_count")
        self.assertEqual(
            binding["authorization_boundary"],
            {
                "provider_call": False,
                "live_data": False,
                "llm_call": False,
                "datahub_write": False,
                "production_runner": False,
                "broker_or_order_execution": False,
            },
        )

    def test_binding_producer_refs_resolve_to_callables(self):
        for ref in load_binding()["producer_refs"]:
            module_path, func_name = ref.split("::", 1)
            module_name = module_path[:-3].replace("/", ".")
            self.assertTrue(callable(getattr(import_module(module_name), func_name)), ref)


if __name__ == "__main__":
    unittest.main()
