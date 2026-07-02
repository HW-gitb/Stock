import unittest
from datetime import date, timedelta

from engine import us_short_seam_catalyst as catalyst_seam
from engine import us_short_seam_momentum as momentum_seam
from engine import us_short_seam_score as score_seam
from engine import us_short_seam_theme as theme_seam
from engine.us_short_catalyst import load_catalyst_governance
from engine.us_short_catalyst_source import resolve_catalyst_signals
from engine.us_short_industry_heat import industry_heat_block
from engine.us_short_momentum import momentum_block
from engine.us_short_provisional_theme_heat import provisional_theme_heat_block
from engine.us_short_risk_downgrade import risk_downgrade
from engine.us_short_seam_catalyst import project_catalyst_block
from engine.us_short_seam_momentum import project_momentum_block
from engine.us_short_seam_theme import project_theme_block
from engine.us_short_weekend_analysis import analyze_rows
from engine.us_short_seam_score import (
    BINDING_PATH,
    COMPONENT_KEYS,
    OUTPUT_KEYS,
    SCORE_BLOCK_KEYS,
    THEME_MOMENTUM_NEUTRAL_SCORE,
    ScoreSeamError,
    compose_score_inputs,
    load_binding,
)


_AGGRESSIVE = {"vix": "进攻", "market_trend": "进攻", "breadth": "进攻"}
_AS_OF_ISO = "2026-06-30"
_CATALYST_AS_OF = "20260630"
_SERIES_LEN = 64
_CATALYST_GOVERNANCE = load_catalyst_governance()
_SRC_PROV = {
    "earnings": ("fmp", "earnings_surprises"),
    "analyst": ("fmp", "analyst_estimate_revisions"),
}


def _zero_rd():
    return risk_downgrade()


def _dates(n):
    end = date.fromisoformat(_AS_OF_ISO)
    return [(end - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


def _dated_series(closes, volumes=None):
    points = []
    for idx, close in enumerate(closes):
        point = {"date": _dates(len(closes))[idx], "close": close}
        if volumes is not None:
            point["volume"] = volumes[idx]
        points.append(point)
    return {
        "as_of": _AS_OF_ISO,
        "session": "RTH",
        "adjustment_mode": "split_div_adjusted",
        "points": points,
    }


def _rising(start=100.0, step=1.0):
    return [float(start + step * idx) for idx in range(_SERIES_LEN)]


def _declining(start=200.0, step=-1.0):
    return [float(start + step * idx) for idx in range(_SERIES_LEN)]


def _surging_volume():
    return [1000.0] * 54 + [6000.0] * 10


def _flat_volume():
    return [1000.0] * _SERIES_LEN


def _hot_member():
    return _dated_series(_rising(), _surging_volume())


def _cold_member():
    return _dated_series(_declining(), _flat_volume())


def _sector_members():
    return {
        "AAPL": {"sector": "Technology", "series": _hot_member()},
        "MSFT": {"sector": "Technology", "series": _hot_member()},
        "NVDA": {"sector": "Technology", "series": _hot_member()},
        "JPM": {"sector": "Financials", "series": _cold_member()},
        "BAC": {"sector": "Financials", "series": _cold_member()},
        "WFC": {"sector": "Financials", "series": _cold_member()},
        "XOM": {"sector": "Energy", "series": _hot_member()},
        "CVX": {"sector": "Energy", "series": _hot_member()},
        "COP": {"sector": "Energy", "series": _hot_member()},
    }


def _producer_themes():
    return {
        "AI": {"members": {"AAPL": _hot_member(), "MSFT": _hot_member(), "NVDA": _hot_member()}},
        "BANKS": {"members": {"JPM": _cold_member(), "BAC": _cold_member(), "WFC": _cold_member()}},
        "SMALL": {"members": {"XOM": _hot_member(), "TSLA": _hot_member()}},
    }


def _theme_membership_from_producer_input(themes):
    return {theme_id: list(theme["members"].keys()) for theme_id, theme in themes.items()}


def _prov(source="earnings", **kw):
    provider, endpoint = _SRC_PROV[source]
    out = {
        "provider_id": provider,
        "endpoint_or_filing_type": endpoint,
        "source_as_of": _CATALYST_AS_OF,
        "observed_at": "2026-06-30T08:00:00-04:00",
        "coverage_status": "full",
        "parser_status": "ok",
        "lineage_ref": f"{provider}:{endpoint}:{_CATALYST_AS_OF}#rec1",
    }
    out.update(kw)
    return out


def _earn(pct=15.0, date="20260625", prov=None):
    return {
        "earnings_surprise_pct": pct,
        "earnings_report_date": date,
        "provenance": _prov("earnings") if prov is None else prov,
    }


def _analyst(net=4, date="20260624", prov=None):
    return {
        "analyst_revision_net": net,
        "analyst_revision_date": date,
        "provenance": _prov("analyst") if prov is None else prov,
    }


def _momentum_projection():
    return {
        "momentum_by_ticker": {"AAPL": 80.0, "TSLA": 20.0},
        "neutral_fill_tickers": ["MSFT"],
        "coverage": {"AAPL": "scored", "MSFT": "insufficient_history", "TSLA": "scored"},
        "target_count": 3,
        "scored_count": 2,
    }


def _theme_projection():
    return {
        "theme_block_by_ticker": {"AAPL": 90.0, "TSLA": 40.0},
        "neutral_fill_tickers": ["MSFT"],
        "coverage": {
            "AAPL": "scored_theme_base",
            "MSFT": "neutral_missing_theme_and_industry_base",
            "TSLA": "scored_industry_base",
        },
        "target_count": 3,
        "scored_count": 2,
    }


def _catalyst_projection():
    return {
        "catalyst_block_by_ticker": {"AAPL": 70.0},
        "neutral_fill_tickers": ["MSFT", "TSLA"],
        "coverage": {
            "AAPL": "scored_realized_catalyst",
            "MSFT": "neutral_no_realized_catalyst",
            "TSLA": "neutral_source_excluded",
        },
        "target_count": 3,
        "scored_count": 1,
    }


def _risk_map():
    return {
        "AAPL": _zero_rd(),
        "MSFT": risk_downgrade(history_score=5.0),
        "TSLA": _zero_rd(),
    }


def _compose(**overrides):
    args = {
        "target_tickers": ["AAPL", "MSFT", "TSLA"],
        "momentum_projection": _momentum_projection(),
        "theme_projection": _theme_projection(),
        "catalyst_projection": _catalyst_projection(),
        "risk_downgrade_by_ticker": _risk_map(),
        "theme_opportunity_state": "strong",
    }
    args.update(overrides)
    return compose_score_inputs(**args)


class ScoreComposerHappyPathTest(unittest.TestCase):
    def test_compose_score_inputs_emits_selection_and_analysis_from_one_source(self):
        out = _compose()

        self.assertEqual(set(out), set(OUTPUT_KEYS))
        self.assertEqual(out["target_tickers"], ["AAPL", "MSFT", "TSLA"])
        self.assertEqual(out["scoring_profile"], "balanced")
        self.assertEqual(out["scored_component_counts"], {"momentum": 2, "theme": 2, "catalyst": 1})
        self.assertEqual(out["selection_inputs"]["theme_opportunity_state"], "strong")

        per = out["selection_inputs"]["per_ticker"]
        self.assertAlmostEqual(per["AAPL"]["core_score"], 81.0)
        self.assertAlmostEqual(per["MSFT"]["core_score"], 45.0)
        self.assertAlmostEqual(per["TSLA"]["core_score"], 34.5)
        self.assertEqual(
            {ticker: per[ticker]["theme_momentum_score"] for ticker in per},
            {"AAPL": 90.0, "MSFT": THEME_MOMENTUM_NEUTRAL_SCORE, "TSLA": 40.0},
        )

        self.assertEqual(out["analysis_by_ticker"]["AAPL"]["score_blocks"],
                         {"momentum": 80.0, "theme": 90.0, "catalyst": 70.0})
        self.assertEqual(out["analysis_by_ticker"]["MSFT"]["score_blocks"], {})
        self.assertEqual(out["analysis_by_ticker"]["TSLA"]["score_blocks"], {"momentum": 20.0, "theme": 40.0})
        self.assertEqual(out["coverage_by_ticker"]["MSFT"], {
            "momentum": "insufficient_history",
            "theme": "neutral_missing_theme_and_industry_base",
            "catalyst": "neutral_no_realized_catalyst",
        })

    def test_analysis_rows_recompute_same_core_score_as_selection_inputs(self):
        composed = _compose()
        row = {
            "ticker": "AAPL",
            "row_source": "top15_candidate",
            "signals": {},
            "price_input": {"close": 101.0, "bars": []},
            "selection_record": {
                "selection_rank": 1,
                "selection_bucket": "core_top",
                **composed["selection_inputs"]["per_ticker"]["AAPL"],
            },
        }
        row.update(composed["analysis_by_ticker"]["AAPL"])

        analyzed = analyze_rows([row], market_axis_regimes=_AGGRESSIVE)["rows"][0]

        self.assertAlmostEqual(analyzed["score"]["core_score"], 81.0)
        self.assertAlmostEqual(analyzed["score"]["core_score"], row["selection_record"]["core_score"])


class ScoreComposerRealProducerPositiveControlTest(unittest.TestCase):
    def test_real_component_seams_feed_composer_and_reconcile_selection_analysis_scores(self):
        targets = ["AAPL", "MSFT", "TSLA", "AMZN"]
        momentum_projection = project_momentum_block(
            momentum_block({
                "AAPL": {
                    "ret_1m": 0.30,
                    "ret_3m": 0.55,
                    "ret_5d": 0.08,
                    "ret_10d": 0.14,
                    "rel_spy_1m": 0.18,
                    "rel_qqq_1m": 0.15,
                    "vol_surge": 2.5,
                },
                "MSFT": {
                    "ret_1m": 0.18,
                    "ret_3m": 0.32,
                    "ret_5d": 0.04,
                    "ret_10d": 0.09,
                    "rel_spy_1m": 0.08,
                    "rel_qqq_1m": 0.06,
                    "vol_surge": 1.7,
                },
                "NVDA": {
                    "ret_1m": 0.40,
                    "ret_3m": 0.70,
                    "ret_5d": 0.12,
                    "ret_10d": 0.20,
                    "rel_spy_1m": 0.25,
                    "rel_qqq_1m": 0.21,
                    "vol_surge": 3.0,
                },
                "TSLA": {"ret_1m": 0.01},
            }),
            targets,
        )
        industry_result = industry_heat_block(
            _sector_members(),
            spy_series=_dated_series(_rising(100.0, 0.2)),
            qqq_series=_dated_series(_rising(100.0, 0.2)),
        )
        themes_by_id = _producer_themes()
        theme_projection = project_theme_block(
            industry_result=industry_result,
            provisional_theme_result=provisional_theme_heat_block(
                themes_by_id,
                spy_series=_dated_series(_rising(100.0, 0.2)),
                qqq_series=_dated_series(_rising(100.0, 0.2)),
            ),
            theme_members_by_id=_theme_membership_from_producer_input(themes_by_id),
            target_tickers=targets,
        )
        catalyst_projection = project_catalyst_block(
            catalyst_source_result=resolve_catalyst_signals(
                as_of=_CATALYST_AS_OF,
                earnings={"AAPL": _earn(15.0), "MSFT": _earn("15")},
                analyst={"AAPL": _analyst(4)},
            ),
            governance=_CATALYST_GOVERNANCE,
            as_of=_CATALYST_AS_OF,
            target_tickers=targets,
        )

        composed = compose_score_inputs(
            target_tickers=targets,
            momentum_projection=momentum_projection,
            theme_projection=theme_projection,
            catalyst_projection=catalyst_projection,
            risk_downgrade_by_ticker={ticker: _zero_rd() for ticker in targets},
            theme_opportunity_state="strong",
        )

        self.assertEqual(set(composed["selection_inputs"]["per_ticker"]), set(targets))
        self.assertEqual(composed["scored_component_counts"], {
            "momentum": momentum_projection["scored_count"],
            "theme": theme_projection["scored_count"],
            "catalyst": catalyst_projection["scored_count"],
        })
        self.assertEqual(
            set(composed["analysis_by_ticker"]["AAPL"]["score_blocks"]),
            {"momentum", "theme", "catalyst"},
        )
        self.assertEqual(composed["analysis_by_ticker"]["AMZN"]["score_blocks"], {})
        self.assertEqual(
            composed["coverage_by_ticker"]["AMZN"],
            {
                "momentum": "absent_from_pool",
                "theme": "neutral_missing_theme_and_industry_base",
                "catalyst": "neutral_missing_catalyst_source",
            },
        )

        rows = []
        for rank, ticker in enumerate(("AAPL", "AMZN"), start=1):
            row = {
                "ticker": ticker,
                "row_source": "top15_candidate",
                "signals": {},
                "price_input": {"close": 101.0, "bars": []},
                "selection_record": {
                    "selection_rank": rank,
                    "selection_bucket": "core_top",
                    **composed["selection_inputs"]["per_ticker"][ticker],
                },
            }
            row.update(composed["analysis_by_ticker"][ticker])
            rows.append(row)

        analyzed_by_ticker = {
            row["ticker"]: row
            for row in analyze_rows(rows, market_axis_regimes=_AGGRESSIVE)["rows"]
        }
        for ticker in ("AAPL", "AMZN"):
            self.assertAlmostEqual(
                analyzed_by_ticker[ticker]["score"]["core_score"],
                composed["selection_inputs"]["per_ticker"][ticker]["core_score"],
            )


class ScoreComposerValidationTest(unittest.TestCase):
    def test_projection_must_cover_target_set_exactly(self):
        bad = _momentum_projection()
        bad["coverage"] = {"AAPL": "scored", "MSFT": "insufficient_history"}

        with self.assertRaises(ScoreSeamError):
            _compose(momentum_projection=bad)

    def test_scored_and_neutral_partition_must_be_exact(self):
        bad = _theme_projection()
        bad["neutral_fill_tickers"] = []

        with self.assertRaises(ScoreSeamError):
            _compose(theme_projection=bad)

    def test_projection_scored_count_must_match_values(self):
        bad = _catalyst_projection()
        bad["scored_count"] = 2

        with self.assertRaises(ScoreSeamError):
            _compose(catalyst_projection=bad)

    def test_missing_risk_downgrade_for_target_fails_closed(self):
        bad = _risk_map()
        del bad["MSFT"]

        with self.assertRaises(ScoreSeamError):
            _compose(risk_downgrade_by_ticker=bad)

    def test_malformed_risk_downgrade_fails_closed(self):
        bad = _risk_map()
        bad["AAPL"] = {
            "points": 5.0,
            "hard_veto": False,
            "components": {"history": 1.0, "current_event": 1.0, "analyst": 1.0},
        }

        with self.assertRaises(ScoreSeamError):
            _compose(risk_downgrade_by_ticker=bad)

    def test_duplicate_target_identity_rejected(self):
        with self.assertRaises(ScoreSeamError):
            _compose(target_tickers=["AAPL", "aapl"])

    def test_bad_component_value_rejected(self):
        bad = _momentum_projection()
        bad["momentum_by_ticker"]["AAPL"] = "80"

        with self.assertRaises(ScoreSeamError):
            _compose(momentum_projection=bad)


class ScoreComposerBindingConformanceTest(unittest.TestCase):
    def test_binding_matches_engine_contract(self):
        binding = load_binding()

        self.assertTrue(str(BINDING_PATH).endswith(binding["artifact_id"] + ".json"))
        self.assertEqual(tuple(binding["component_keys"]), COMPONENT_KEYS)
        self.assertEqual(tuple(binding["score_block_keys"]), SCORE_BLOCK_KEYS)
        self.assertEqual(tuple(binding["output_contract"]["required_keys"]), OUTPUT_KEYS)
        self.assertEqual(
            binding["theme_momentum_neutral_score"],
            THEME_MOMENTUM_NEUTRAL_SCORE,
        )
        self.assertEqual(score_seam.COMPONENT_VALUE_KEYS, binding["input_contract"]["component_value_maps"])
        self.assertEqual(
            {
                component: score_seam._COMPONENT_SPECS[component]["value_key"]
                for component in COMPONENT_KEYS
            },
            binding["input_contract"]["component_value_maps"],
        )
        self.assertEqual(
            binding["input_contract"]["component_value_maps"],
            {
                "momentum": momentum_seam._PROJECTION_OUTPUT_KEYS[0],
                "theme": theme_seam.OUTPUT_KEYS[0],
                "catalyst": catalyst_seam.OUTPUT_KEYS[0],
            },
        )
        self.assertEqual(
            binding["authorization_boundary"],
            {
                "provider_call": False,
                "live_data": False,
                "datahub_write": False,
                "production_runner": False,
                "broker_or_order_execution": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
