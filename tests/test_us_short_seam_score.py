import copy
import unittest
from datetime import date, timedelta

from engine import us_short_seam_catalyst as catalyst_seam
from engine import us_short_seam_momentum as momentum_seam
from engine import us_short_seam_score as score_seam
from engine import us_short_seam_theme as theme_seam
from engine.us_short_catalyst import load_catalyst_governance
from engine.us_short_catalyst_source import resolve_catalyst_signals
from engine.us_short_core_score import PROFILE_NAMES, core_score
from engine.us_short_industry_heat import industry_heat_block
from engine.us_short_momentum import momentum_block
from engine.us_short_overextension import classify_overextension
from engine.us_short_provisional_theme_heat import provisional_theme_heat_block
from engine.us_short_risk_downgrade import risk_downgrade
from engine.us_short_seam_catalyst import project_catalyst_block
from engine.us_short_seam_momentum import project_momentum_block
from engine.us_short_seam_theme import project_theme_block
from engine.us_short_weekend_analysis import WeekendAnalysisError, analyze_rows
from engine.us_short_weekend_pipeline import _select_top15
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
from tests.schema.test_us_short_provisional_theme_validation_schema import _artifact as _validated_theme_artifact


_AGGRESSIVE = {"vix": "进攻", "market_trend": "进攻", "breadth": "进攻"}
_AS_OF_ISO = "2026-06-30"
_CATALYST_AS_OF = "20260630"
_SERIES_LEN = 64
_CATALYST_GOVERNANCE = load_catalyst_governance()
_SRC_PROV = {
    "earnings": ("fmp", "earnings_surprises"),
    "analyst": ("fmp", "analyst_estimate_revisions"),
}


def _top15_inputs(per_ticker, state="strong"):
    return {
        "theme_opportunity_state": state,
        "theme_selection_contract": {
            "as_of": "20260630", "mode": "industry_heat_v1_cross_industry_disabled",
            "cross_industry_provisional_enabled": False, "theme_opportunity_state": state,
            "per_ticker": {ticker: {"theme_id": f"industry:{ticker.lower()}", "theme_source": "industry_heat_v1",
                                      "theme_lifecycle_state": "confirmed_active", "theme_leader_rs": 0.0,
                                      "membership_origin": "automatic_discovery", "market_confirmed": True,
                                      "individual_theme_gate_passed": True, "overextension_state": "none",
                                      "macro_cluster": "unclassified_conservative"}
                           for ticker in per_ticker},
        },
        "per_ticker": per_ticker,
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
    def test_provisional_theme_boost_is_off_by_default_and_both_tier_adds_five_once(self):
        baseline = _compose()
        self.assertNotIn("provisional_theme_boost", baseline["analysis_by_ticker"]["AAPL"])
        artifact = _validated_theme_artifact()
        self.assertEqual(
            baseline,
            _compose(provisional_theme_validation=artifact, theme_soft_boost_enabled=False),
        )
        duplicate_membership = copy.deepcopy(artifact["themes"][0])
        duplicate_membership["theme_id"] = "theme_02"
        duplicate_membership["validation"]["selection_rank"] = 2
        artifact["themes"].append(duplicate_membership)
        enabled = _compose(
            provisional_theme_validation=artifact,
            theme_soft_boost_enabled=True,
            provisional_theme_expected_decision_date="20260615",
            provisional_theme_input_digests={
                "discovery_artifact_sha256": "a" * 64,
                "candidate_artifact_sha256": "b" * 64,
                "classification_packet_sha256": "c" * 64,
            },
        )
        self.assertAlmostEqual(baseline["selection_inputs"]["per_ticker"]["AAPL"]["core_score"], 81.0)
        self.assertAlmostEqual(enabled["selection_inputs"]["per_ticker"]["AAPL"]["core_score"], 86.0)
        self.assertAlmostEqual(enabled["selection_inputs"]["per_ticker"]["TSLA"]["core_score"], 34.5)
        self.assertEqual(enabled["analysis_by_ticker"]["AAPL"]["provisional_theme_boost"]["evidence_tier"], "both")

    def test_single_tier_adds_two_and_not_five(self):
        artifact = _validated_theme_artifact()
        member = next(row for row in artifact["themes"][0]["members"] if row["ticker"] == "MSFT")
        member["source_types"] = ["web"]
        member["evidence_tier"] = "single"
        member["source_ref_ids"] = ["web:theme"]
        enabled = _compose(
            provisional_theme_validation=artifact,
            theme_soft_boost_enabled=True,
            provisional_theme_expected_decision_date="20260615",
            provisional_theme_input_digests={
                "discovery_artifact_sha256": "a" * 64,
                "candidate_artifact_sha256": "b" * 64,
                "classification_packet_sha256": "c" * 64,
            },
        )
        self.assertAlmostEqual(enabled["selection_inputs"]["per_ticker"]["MSFT"]["core_score"], 47.0)

    def test_consumer_schema_gate_is_load_bearing(self):
        """The consumer's >=3-member, <=8-theme and effect-flag gates live ONLY in its `_schema_validate`
        call, so they need a test that dies with it. Each artifact below is rejected by the schema alone —
        the mapper's own Python checks (industry re-derivation, tier/ref binding) all pass on them."""
        boost_kwargs = dict(
            theme_soft_boost_enabled=True,
            provisional_theme_expected_decision_date="20260615",
            provisional_theme_input_digests={
                "discovery_artifact_sha256": "a" * 64,
                "candidate_artifact_sha256": "b" * 64,
                "classification_packet_sha256": "c" * 64,
            },
        )

        def _two_member_theme(artifact):
            theme = artifact["themes"][0]
            theme["members"] = [row for row in theme["members"] if row["ticker"] != "JPM"]
            theme["validation"]["qualified_member_count"] = 2
            theme["validation"]["industry_codes"] = ["10"]
            theme["validation"]["industry_count"] = 1

        def _nine_themes(artifact):
            base = artifact["themes"][0]
            artifact["themes"] = []
            for index in range(9):
                clone = copy.deepcopy(base)
                clone["theme_id"] = f"theme_{index:02d}"
                clone["validation"]["selection_rank"] = index + 1
                artifact["themes"].append(clone)

        def _claims_top15_effect(artifact):
            artifact["validation_contract"]["top15_effect_enabled"] = True

        for label, mutate in (("2-member theme", _two_member_theme),
                              ("9 themes", _nine_themes),
                              ("self-declared top15 effect", _claims_top15_effect)):
            with self.subTest(artifact=label):
                artifact = _validated_theme_artifact()
                mutate(artifact)
                with self.assertRaises(ScoreSeamError):
                    _compose(provisional_theme_validation=artifact, **boost_kwargs)

    def test_chasing_extreme_strip_suppresses_the_provisional_boost(self):
        """§4.3: a chasing_extreme ticker has its theme contribution stripped from core — an unconfirmed
        provisional theme must not refund part of that penalty. Provenance survives; the points do not."""
        boost_kwargs = dict(
            provisional_theme_validation=_validated_theme_artifact(),
            theme_soft_boost_enabled=True,
            provisional_theme_expected_decision_date="20260615",
            provisional_theme_input_digests={
                "discovery_artifact_sha256": "a" * 64,
                "candidate_artifact_sha256": "b" * 64,
                "classification_packet_sha256": "c" * 64,
            },
        )
        chasing = _overext_map(chasing=["AAPL"])
        stripped_only = _compose(overextension_by_ticker=chasing)
        boosted = _compose(overextension_by_ticker=chasing, **boost_kwargs)
        self.assertAlmostEqual(stripped_only["selection_inputs"]["per_ticker"]["AAPL"]["core_score"], 49.5)
        self.assertAlmostEqual(boosted["selection_inputs"]["per_ticker"]["AAPL"]["core_score"], 49.5)
        record = boosted["analysis_by_ticker"]["AAPL"]["provisional_theme_boost"]
        self.assertFalse(record["boost_applied"])
        self.assertEqual(record["theme_soft_boost"], 0.0)
        self.assertIsNone(record["evidence_tier"])
        self.assertTrue(record["validated_theme_ids"])
        self.assertTrue(boosted["analysis_by_ticker"]["MSFT"]["provisional_theme_boost"]["boost_applied"])

    def test_mismatched_evidence_tier_fails_closed(self):
        artifact = _validated_theme_artifact()
        artifact["themes"][0]["members"][0]["evidence_tier"] = "single"
        with self.assertRaises(ValueError):
            _compose(
                provisional_theme_validation=artifact, theme_soft_boost_enabled=True,
                provisional_theme_expected_decision_date="20260615",
                provisional_theme_input_digests={
                    "discovery_artifact_sha256": "a" * 64,
                    "candidate_artifact_sha256": "b" * 64,
                    "classification_packet_sha256": "c" * 64,
                },
            )

    def test_enabled_theme_boost_requires_expected_identity_receipt(self):
        with self.assertRaises(ValueError):
            _compose(provisional_theme_validation=_validated_theme_artifact(), theme_soft_boost_enabled=True)

    def test_enabled_theme_boost_rejects_forged_source_type_binding(self):
        artifact = _validated_theme_artifact()
        artifact["source_ref_types"]["web:theme"] = "x"
        with self.assertRaises(ValueError):
            _compose(
                provisional_theme_validation=artifact, theme_soft_boost_enabled=True,
                provisional_theme_expected_decision_date="20260615",
                provisional_theme_input_digests={
                    "discovery_artifact_sha256": "a" * 64,
                    "candidate_artifact_sha256": "b" * 64,
                    "classification_packet_sha256": "c" * 64,
                },
            )

    def test_llm_explanatory_ref_does_not_abort_web_x_boost_consumer(self):
        artifact = _validated_theme_artifact()
        artifact["source_ref_types"]["llm:summary"] = "llm"
        theme = artifact["themes"][0]
        theme["source_ref_ids"].append("llm:summary")
        for member in theme["members"]:
            member["source_ref_ids"].append("llm:summary")
        enabled = _compose(
            provisional_theme_validation=artifact, theme_soft_boost_enabled=True,
            provisional_theme_expected_decision_date="20260615",
            provisional_theme_input_digests={
                "discovery_artifact_sha256": "a" * 64,
                "candidate_artifact_sha256": "b" * 64,
                "classification_packet_sha256": "c" * 64,
            },
        )
        self.assertAlmostEqual(enabled["selection_inputs"]["per_ticker"]["AAPL"]["core_score"], 86.0)

    def test_enabled_theme_boost_rejects_locator_source_ids(self):
        artifact = _validated_theme_artifact()
        artifact["source_ref_types"]["https://example.invalid/source"] = "web"
        with self.assertRaises(ValueError):
            _compose(
                provisional_theme_validation=artifact, theme_soft_boost_enabled=True,
                provisional_theme_expected_decision_date="20260615",
                provisional_theme_input_digests={
                    "discovery_artifact_sha256": "a" * 64,
                    "candidate_artifact_sha256": "b" * 64,
                    "classification_packet_sha256": "c" * 64,
                },
            )

    def test_provisional_theme_boost_recomputes_in_analysis_seam(self):
        composed = _compose(
            provisional_theme_validation=_validated_theme_artifact(),
            theme_soft_boost_enabled=True,
            provisional_theme_expected_decision_date="20260615",
            provisional_theme_input_digests={
                "discovery_artifact_sha256": "a" * 64,
                "candidate_artifact_sha256": "b" * 64,
                "classification_packet_sha256": "c" * 64,
            },
        )
        row = {
            "ticker": "AAPL", "row_source": "top15_candidate", "signals": {},
            "price_input": {"close": 101.0, "bars": []},
            "selection_record": {
                "selection_rank": 1, "selection_bucket": "core_top",
                **composed["selection_inputs"]["per_ticker"]["AAPL"],
            },
        }
        row.update(composed["analysis_by_ticker"]["AAPL"])
        analyzed = analyze_rows([row], market_axis_regimes=_AGGRESSIVE)["rows"][0]
        self.assertAlmostEqual(analyzed["score"]["core_score"], 86.0)

    def test_legal_soft_boost_alone_moves_a_boundary_ticker_into_top15_core(self):
        core_names = [
            "AAPL", "MSFT", "TSLA", "NVDA", "JPM", "BAC",
            "WFC", "XOM", "CVX", "COP", "AMZN", "GOOGL",
        ]
        theme_names = ["META", "NFLX", "INTC", "AMD", "IBM", "CRM", "ADBE", "QCOM"]
        target = "ORCL"
        off = {
            ticker: {"core_score": 100.0 - index, "theme_momentum_score": 0.0}
            for index, ticker in enumerate(core_names)
        }
        off.update({
            ticker: {"core_score": 20.0, "theme_momentum_score": 100.0 - index}
            for index, ticker in enumerate(theme_names)
        })
        off[target] = {"core_score": 92.0, "theme_momentum_score": 0.0}
        on = copy.deepcopy(off)
        on[target]["core_score"] = 97.0
        off_top = _select_top15(
            list(off), _top15_inputs(off), decision_date="20260630",
        )
        on_top = _select_top15(
            list(on), _top15_inputs(on), decision_date="20260630",
        )
        self.assertNotIn(target, off_top["admitted"])
        self.assertIn(target, on_top["admitted"])
        detail = next(row for row in on_top["selection_details"] if row["ticker"] == target)
        self.assertEqual(detail["selection_bucket"], "core_top")

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


# ── §4.3 overextension chasing theme-strip (Slice B) ──────────────────────────────────────────
def _chasing_record():
    return {"overextension_state": "chasing_extreme", "strips_theme_score": True, "execution_flags": {}}


def _warning_record():
    return {"overextension_state": "warning", "strips_theme_score": False,
            "execution_flags": {"force_pullback": True, "reduce_size": True, "raise_rr_gate": True}}


def _none_record():
    return {"overextension_state": "none", "strips_theme_score": False, "execution_flags": {}}


def _overext_map(*, chasing=(), warning=(), targets=("AAPL", "MSFT", "TSLA")):
    """A full-EXACT-coverage §4.3 overextension map over targets (compose requires exact coverage)."""
    chasing, warning = set(chasing), set(warning)
    out = {}
    for ticker in targets:
        if ticker in chasing:
            out[ticker] = _chasing_record()
        elif ticker in warning:
            out[ticker] = _warning_record()
        else:
            out[ticker] = _none_record()
    return out


_AAPL_BLOCKS = {"momentum": 80.0, "theme": 90.0, "catalyst": 70.0}
_TSLA_BLOCKS = {"momentum": 20.0, "theme": 40.0}


class ScoreComposerOverextensionStripTest(unittest.TestCase):
    def test_chasing_penalty_never_raises_a_low_theme_high_momentum_score(self):
        # R3 issue 5 reverse control: the shadow-only `theme_off` profile reallocates the removed theme
        # weight, so it could RAISE a low-theme/high-momentum-catalyst score. A penalty may only subtract.
        low_theme = _theme_projection()
        low_theme["theme_block_by_ticker"]["AAPL"] = 10.0
        high_momentum = _momentum_projection()
        high_momentum["momentum_by_ticker"]["AAPL"] = 100.0
        high_catalyst = _catalyst_projection()
        high_catalyst["catalyst_block_by_ticker"]["AAPL"] = 100.0

        baseline = _compose(
            momentum_projection=high_momentum,
            theme_projection=low_theme,
            catalyst_projection=high_catalyst,
        )
        chasing = _compose(
            momentum_projection=high_momentum,
            theme_projection=low_theme,
            catalyst_projection=high_catalyst,
            overextension_by_ticker=_overext_map(chasing=["AAPL"]),
        )

        self.assertLessEqual(
            chasing["selection_inputs"]["per_ticker"]["AAPL"]["core_score"],
            baseline["selection_inputs"]["per_ticker"]["AAPL"]["core_score"],
        )

    def test_theme_strip_never_raises_any_frozen_profile(self):
        blocks = {"momentum": 100.0, "theme": 10.0, "catalyst": 100.0}
        for profile in PROFILE_NAMES:
            with self.subTest(profile=profile):
                baseline = core_score(blocks, profile)["core_score"]
                stripped = core_score(blocks, profile, strip_theme_score=True)["core_score"]
                self.assertLessEqual(stripped, baseline)

    def test_non_bool_theme_strip_flag_fails_closed(self):
        for bad in ("true", 1, 0, 1.0, None):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    core_score(_AAPL_BLOCKS, strip_theme_score=bad)

    def test_absent_map_is_identical_to_pre_strip_behavior(self):
        # a full none-map strips nothing → byte-identical to passing no map at all (backward-compat)
        self.assertEqual(_compose(), _compose(overextension_by_ticker=_overext_map()))

    def test_chasing_strips_theme_contribution_and_zeros_theme_momentum(self):
        out = _compose(overextension_by_ticker=_overext_map(chasing=["AAPL"]))
        per = out["selection_inputs"]["per_ticker"]

        self.assertAlmostEqual(
            per["AAPL"]["core_score"],
            core_score(_AAPL_BLOCKS, "balanced", strip_theme_score=True)["core_score"],
        )
        self.assertLess(per["AAPL"]["core_score"], 81.0)      # theme was boosting AAPL → strip lowers the score
        self.assertEqual(per["AAPL"]["theme_momentum_score"], THEME_MOMENTUM_NEUTRAL_SCORE)   # no §4.5 theme seat
        self.assertEqual(out["analysis_by_ticker"]["AAPL"]["scoring_profile"], "balanced")
        # non-chasing tickers untouched (score, theme seat, and profile stay on the balanced track)
        self.assertAlmostEqual(per["MSFT"]["core_score"], 45.0)
        self.assertAlmostEqual(per["TSLA"]["core_score"], 34.5)
        self.assertEqual(per["TSLA"]["theme_momentum_score"], 40.0)
        self.assertEqual(out["analysis_by_ticker"]["TSLA"]["scoring_profile"], "balanced")
        self.assertEqual(out["scoring_profile"], "balanced")   # top-level = the run's TRACK profile, not per-ticker

    def test_strip_makes_core_score_independent_of_theme_block(self):
        hot, cold = _theme_projection(), _theme_projection()
        hot["theme_block_by_ticker"]["AAPL"] = 90.0
        cold["theme_block_by_ticker"]["AAPL"] = 10.0
        chasing = _overext_map(chasing=["AAPL"])
        a = _compose(theme_projection=hot, overextension_by_ticker=chasing)
        b = _compose(theme_projection=cold, overextension_by_ticker=chasing)
        # theme weight is 0 under the strip → the theme block value cannot move a stripped ticker's core_score
        self.assertAlmostEqual(a["selection_inputs"]["per_ticker"]["AAPL"]["core_score"],
                               b["selection_inputs"]["per_ticker"]["AAPL"]["core_score"])

    def test_none_and_warning_tiers_never_strip(self):
        base = _compose()
        for label, mp in (("none", _overext_map()),
                          ("warning", _overext_map(warning=["AAPL", "MSFT", "TSLA"]))):
            with self.subTest(tier=label):
                # warning is the execution-side tier (cut 2c) — it KEEPS the theme score, no selection strip here
                self.assertEqual(_compose(overextension_by_ticker=mp), base)

    def test_multiple_chasing_tickers_all_strip(self):
        out = _compose(overextension_by_ticker=_overext_map(chasing=["AAPL", "TSLA"]))
        per = out["selection_inputs"]["per_ticker"]
        self.assertAlmostEqual(
            per["AAPL"]["core_score"],
            core_score(_AAPL_BLOCKS, "balanced", strip_theme_score=True)["core_score"],
        )
        self.assertAlmostEqual(
            per["TSLA"]["core_score"],
            core_score(_TSLA_BLOCKS, "balanced", strip_theme_score=True)["core_score"],
        )
        self.assertEqual(per["AAPL"]["theme_momentum_score"], THEME_MOMENTUM_NEUTRAL_SCORE)
        self.assertEqual(per["TSLA"]["theme_momentum_score"], THEME_MOMENTUM_NEUTRAL_SCORE)
        self.assertAlmostEqual(per["MSFT"]["core_score"], 45.0)   # untouched

    def test_real_classify_output_shape_flows_through(self):
        # positive control: a REAL classify_overextension chasing result (carries conditions_met / condition_names,
        # not just the three consumed fields) must be consumed without drift.
        real = classify_overextension({"close": 200.0, "atr": 5.0, "ma5": 150.0, "ma10": 140.0, "ma20": 130.0,
                                       "vol_ratio": 3.0, "daily_change": 20.0, "vertical_run": True,
                                       "weak_retrace": True})
        self.assertEqual(real["overextension_state"], "chasing_extreme")
        self.assertIs(real["strips_theme_score"], True)
        mp = _overext_map()
        mp["AAPL"] = real
        out = _compose(overextension_by_ticker=mp)
        self.assertAlmostEqual(
            out["selection_inputs"]["per_ticker"]["AAPL"]["core_score"],
            core_score(_AAPL_BLOCKS, "balanced", strip_theme_score=True)["core_score"],
        )


class ScoreComposerOverextensionReconciliationTest(unittest.TestCase):
    def test_chasing_analysis_recompute_matches_stripped_selection_no_fork(self):
        composed = _compose(overextension_by_ticker=_overext_map(chasing=["AAPL"]))
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
            "overextension": _overext_map(chasing=["AAPL"])["AAPL"],
        }
        row.update(composed["analysis_by_ticker"]["AAPL"])
        analyzed = analyze_rows([row], market_axis_regimes=_AGGRESSIVE)["rows"][0]
        # The attached chasing record makes analysis remove the same theme contribution, preserving the
        # one-core_score-per-run invariant.
        self.assertAlmostEqual(analyzed["score"]["core_score"],
                               composed["selection_inputs"]["per_ticker"]["AAPL"]["core_score"])
        self.assertEqual(analyzed["score"]["profile"], "balanced")

    def test_induced_selection_analysis_strip_mismatch_is_caught(self):
        # reverse control for the 承重接缝: if a chasing ticker were stripped at selection but a STALE UNSTRIPPED
        # score reached selection_record, the 1e-6 fork assertion MUST fire — proving the reconciliation guard is
        # LIVE, not merely non-triggering on the happy path (a disabled guard would pass the positive test above).
        composed = _compose(overextension_by_ticker=_overext_map(chasing=["AAPL"]))
        row = {
            "ticker": "AAPL",
            "row_source": "top15_candidate",
            "signals": {},
            "price_input": {"close": 101.0, "bars": []},
            "selection_record": {
                "selection_rank": 1,
                "selection_bucket": "core_top",
                "core_score": 81.0,               # UNSTRIPPED balanced score — forks vs the theme-stripped recompute
                "theme_momentum_score": 0.0,
            },
            "overextension": _overext_map(chasing=["AAPL"])["AAPL"],
        }
        row.update(composed["analysis_by_ticker"]["AAPL"])
        with self.assertRaises(WeekendAnalysisError):
            analyze_rows([row], market_axis_regimes=_AGGRESSIVE)

    def test_selection_details_carry_stripped_score_and_zeroed_theme_seat(self):
        composed = _compose(overextension_by_ticker=_overext_map(chasing=["AAPL"]))
        top = _select_top15(
            ["AAPL", "MSFT", "TSLA"], _top15_inputs(composed["selection_inputs"]["per_ticker"]),
            decision_date="20260630")
        details = {d["ticker"]: d for d in top["selection_details"]}
        self.assertAlmostEqual(
            details["AAPL"]["core_score"],
            core_score(_AAPL_BLOCKS, "balanced", strip_theme_score=True)["core_score"],
        )
        self.assertEqual(details["AAPL"]["theme_momentum_score"], THEME_MOMENTUM_NEUTRAL_SCORE)

    def test_strip_reorders_top15_ranking(self):
        # the exact per_ticker values compose emits for a chasing AAPL whose theme was ranking it above MSFT
        base = _select_top15(["AAPL", "MSFT"], _top15_inputs(
            {"AAPL": {"core_score": 67.5, "theme_momentum_score": 100.0},
             "MSFT": {"core_score": 64.0, "theme_momentum_score": 60.0}}), decision_date="20260630")
        self.assertEqual([d["ticker"] for d in base["selection_details"]], ["AAPL", "MSFT"])
        stripped = _select_top15(["AAPL", "MSFT"], _top15_inputs(
            {"AAPL": {"core_score": 50.0, "theme_momentum_score": 0.0},
             "MSFT": {"core_score": 64.0, "theme_momentum_score": 60.0}}), decision_date="20260630")
        # stripped AAPL core 50.0 < MSFT 64.0 → MSFT now ranks first: the strip changed Top15 order
        self.assertEqual([d["ticker"] for d in stripped["selection_details"]], ["MSFT", "AAPL"])

    def test_zeroed_theme_momentum_loses_a_contended_theme_seat(self):
        # 8 high-core names fill core_top(8); 8 low-core contenders vie for theme(7) seats (strong = 8+7 = 15) so
        # the 16th is EXCLUDED. A borderline contender included on its theme_momentum is dropped when it is zeroed.
        core_names = ["AAPL", "MSFT", "TSLA", "NVDA", "JPM", "BAC", "WFC", "XOM"]
        contenders = ["CVX", "COP", "AMZN", "GOOGL", "META", "NFLX", "INTC", "ORCL"]
        theme_mom = {"CVX": 60.0, "COP": 59.0, "AMZN": 58.0, "GOOGL": 57.0,
                     "META": 56.0, "NFLX": 55.0, "INTC": 54.0, "ORCL": 53.0}
        all_names = core_names + contenders

        def inputs(nflx_theme):
            per = {t: {"core_score": 90.0 - i, "theme_momentum_score": 0.0} for i, t in enumerate(core_names)}
            for t in contenders:
                per[t] = {"core_score": 50.0,
                          "theme_momentum_score": (nflx_theme if t == "NFLX" else theme_mom[t])}
            return _top15_inputs(per)

        unstripped = set(_select_top15(all_names, inputs(55.0), decision_date="20260630")["admitted"])
        stripped = set(_select_top15(all_names, inputs(0.0), decision_date="20260630")["admitted"])
        self.assertIn("NFLX", unstripped)        # wins a theme seat on its 55 theme_momentum
        self.assertNotIn("ORCL", unstripped)     # 53 is the odd-one-out (16th)
        self.assertNotIn("NFLX", stripped)       # zeroed theme_momentum → drops out of the 7 theme seats
        self.assertIn("ORCL", stripped)          # ORCL takes the freed seat


class ScoreComposerOverextensionFailClosedTest(unittest.TestCase):
    def test_non_dict_map_rejected(self):
        with self.assertRaises(ScoreSeamError):
            _compose(overextension_by_ticker=["AAPL"])

    def test_non_dict_record_rejected(self):
        mp = _overext_map()
        mp["AAPL"] = "chasing_extreme"
        with self.assertRaises(ScoreSeamError):
            _compose(overextension_by_ticker=mp)

    def test_illegal_overextension_state_rejected(self):
        mp = _overext_map()
        mp["AAPL"]["overextension_state"] = "parabolic"
        with self.assertRaises(ScoreSeamError):
            _compose(overextension_by_ticker=mp)

    def test_non_bool_strips_theme_score_rejected(self):
        for bad in ("true", 1, 0, 1.0, 0.0, None):   # ints/floats/str/None all non-bool → not a strip decision
            with self.subTest(value=bad):
                mp = _overext_map()
                mp["AAPL"]["strips_theme_score"] = bad
                with self.assertRaises(ScoreSeamError):
                    _compose(overextension_by_ticker=mp)

    def test_non_dict_execution_flags_rejected(self):
        mp = _overext_map()
        mp["AAPL"]["execution_flags"] = None
        with self.assertRaises(ScoreSeamError):
            _compose(overextension_by_ticker=mp)

    def test_state_effect_mismatches_rejected_closed_world(self):
        mutations = (
            ("warning_strips", {"overextension_state": "warning", "strips_theme_score": True,
                                "execution_flags": dict(_warning_record()["execution_flags"])}),
            ("chasing_does_not_strip", {"overextension_state": "chasing_extreme", "strips_theme_score": False,
                                        "execution_flags": {}}),
            ("none_carries_warning_flags", {"overextension_state": "none", "strips_theme_score": False,
                                             "execution_flags": dict(_warning_record()["execution_flags"])}),
            ("warning_missing_flag", {"overextension_state": "warning", "strips_theme_score": False,
                                      "execution_flags": {"force_pullback": True, "reduce_size": True}}),
            ("warning_extra_flag", {"overextension_state": "warning", "strips_theme_score": False,
                                    "execution_flags": {**_warning_record()["execution_flags"], "extra": True}}),
            ("warning_non_bool_flag", {"overextension_state": "warning", "strips_theme_score": False,
                                       "execution_flags": {**_warning_record()["execution_flags"],
                                                           "reduce_size": 1}}),
        )
        for label, bad in mutations:
            with self.subTest(case=label):
                mp = _overext_map()
                mp["AAPL"] = bad
                with self.assertRaises(ScoreSeamError):
                    _compose(overextension_by_ticker=mp)

    def test_duplicate_canonical_ticker_rejected(self):
        mp = _overext_map()
        mp["aapl"] = _none_record()   # canonicalizes to AAPL → duplicate identity
        with self.assertRaises(ScoreSeamError):
            _compose(overextension_by_ticker=mp)

    def test_missing_target_coverage_rejected(self):
        mp = _overext_map()
        del mp["MSFT"]
        with self.assertRaises(ScoreSeamError):
            _compose(overextension_by_ticker=mp)

    def test_stray_ticker_outside_targets_rejected(self):
        mp = _overext_map()
        mp["NVDA"] = _none_record()   # not in the target set → exact-coverage violation
        with self.assertRaises(ScoreSeamError):
            _compose(overextension_by_ticker=mp)

    def test_non_canonical_ticker_key_rejected(self):
        mp = _overext_map()
        mp["123!"] = _none_record()
        with self.assertRaises(ScoreSeamError):
            _compose(overextension_by_ticker=mp)


class ScoreComposerThemeStripNonConflationTest(unittest.TestCase):
    def test_whole_track_theme_off_shadow_vs_per_ticker_strip_are_distinct(self):
        # §12.2 WHOLE-TRACK theme_off shadow: scoring_profile="theme_off", NO overextension map → ALL tickers use
        # theme_off and the top-level + every analysis row reports theme_off.
        whole = _compose(scoring_profile="theme_off")
        self.assertEqual(whole["scoring_profile"], "theme_off")
        for ticker in ("AAPL", "MSFT", "TSLA"):
            self.assertEqual(whole["analysis_by_ticker"][ticker]["scoring_profile"], "theme_off")

        # PER-TICKER strip within the balanced track: all rows retain the balanced profile, while only the chasing
        # ticker removes its theme contribution; the whole-track shadow remains a distinct mechanism.
        per = _compose(overextension_by_ticker=_overext_map(chasing=["AAPL"]))
        self.assertEqual(per["scoring_profile"], "balanced")
        self.assertEqual(per["analysis_by_ticker"]["AAPL"]["scoring_profile"], "balanced")
        self.assertEqual(per["analysis_by_ticker"]["MSFT"]["scoring_profile"], "balanced")
        self.assertEqual(per["analysis_by_ticker"]["TSLA"]["scoring_profile"], "balanced")

    def test_unknown_track_profile_fails_closed_even_when_all_chasing(self):
        # the up-front profile gate must not be bypassable by an all-chasing run (every ticker → theme_off)
        with self.assertRaises(ScoreSeamError):
            _compose(scoring_profile="garbage",
                     overextension_by_ticker=_overext_map(chasing=["AAPL", "MSFT", "TSLA"]))


if __name__ == "__main__":
    unittest.main()
