from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_eligibility_gate import load_eligibility_governance, pass2_safety_admit  # noqa: E402
from engine.us_short_fmp_analyst_grades import resolve_analyst_grade_actions  # noqa: E402
from engine.us_short_catalyst import load_catalyst_governance  # noqa: E402
from engine.us_short_massive_news import resolve_news_events  # noqa: E402
from engine.us_short_risk_downgrade import ANALYST_DOWNGRADE_PENALTY, risk_downgrade  # noqa: E402
from engine.us_short_run_provenance import reconcile_run_provenance  # noqa: E402
from engine.us_short_sec_offering_audit import (  # noqa: E402
    build_offering_audit_from_sec_submissions,
    resolve_offering_audit,
)
from engine.us_short_core_score import core_score  # noqa: E402
from engine.us_short_seam_score import compose_score_inputs  # noqa: E402
from engine.us_short_weekend_analysis import analyze_rows  # noqa: E402
from engine.us_short_weekend_pipeline import run_selection  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402
from runners.us_short_batch5_data_context import (  # noqa: E402
    DataContextAssemblyError,
    assemble_data_context,
    assemble_data_context_from_sec_offering_submissions,
    assemble_data_context_from_resolved_pass2_sources,
    assemble_official_context_components_from_resolved_pass2_sources,
    assemble_data_context_with_analyst_grade_risk,
    assemble_data_context_with_massive_news_catalyst,
)


_GOV_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
_DECISION_DATE = "20260615"
_PRICE_BASIS_DATE = "20260612"
_USED_DATE = "2026-06-12"
_GENERATED_AT = "2026-06-13T10:00:00+00:00"
_OFFERING_AS_OF = "2026-06-15"
_OFFERING_OBSERVED_AT = "2026-06-15T08:00:00-04:00"
_GRADE_AS_OF = "2026-06-15"
_GRADE_OBSERVED_AT = "2026-06-15T08:00:00-04:00"
_NEWS_AS_OF = "2026-06-15"
_NEWS_OBSERVED_AT = "2026-06-15T08:00:00-04:00"
_NOW_ET = datetime(2026, 6, 13, 10, 0, 0)
_SESSIONS = [{"date": "20260612"}, {"date": "20260615"}, {"date": "20260616"}]
_DATA_CONTEXT_KEYS = {
    "universe",
    "catalyst_recall_feed",
    "holdings",
    "candidate_pass2_signals",
    "selection_inputs",
}
_UNIVERSE_ROW_KEYS = {
    "ticker",
    "exchange",
    "price",
    "adv_usd",
    "market_cap_usd",
    "delisted",
    "halted",
    "bankruptcy",
    "otc",
}


def _gov():
    return load_eligibility_governance(_GOV_PATH)


def _market_data(price, adv_usd):
    return {
        "close": price,
        "volume": 100_000,
        "adv_usd": adv_usd,
        "adv_days_observed": 20,
        "price_as_of": _USED_DATE,
    }


def _candidate_artifact(tickers=("AAPL", "LOWADV")):
    specs = {
        "AAPL": {
            "cik": 320193,
            "exchange": "NASDAQ",
            "shares": 15_000_000_000,
            "price": 200.0,
            "adv_usd": 50_000_000.0,
        },
        "MSFT": {
            "cik": 789019,
            "exchange": "NASDAQ",
            "shares": 7_000_000_000,
            "price": 400.0,
            "adv_usd": 80_000_000.0,
        },
        "JPM": {
            "cik": 19617,
            "exchange": "NYSE",
            "shares": 3_000_000_000,
            "price": 200.0,
            "adv_usd": 70_000_000.0,
        },
        "LOWADV": {
            "cik": 5,
            "exchange": "NYSE",
            "shares": 1_000_000_000,
            "price": 10.0,
            "adv_usd": 1_000.0,
        },
    }
    sec_tickers = {
        ticker: {"cik": specs[ticker]["cik"], "exchange": specs[ticker]["exchange"]}
        for ticker in tickers
    }
    sec_shares = {
        specs[ticker]["cik"]: {"shares": specs[ticker]["shares"], "end": "2026-03-31"}
        for ticker in tickers
    }
    market_data = {
        ticker: _market_data(specs[ticker]["price"], specs[ticker]["adv_usd"])
        for ticker in tickers
    }
    rows = universe_fetch.apply_pass1(
        sec_tickers,
        sec_shares,
        market_data,
        governance=_gov(),
        as_of=_USED_DATE,
        observed_at=_GENERATED_AT,
    )
    return universe_fetch.build_candidate_artifact(
        rows=rows,
        decision_date=_DECISION_DATE,
        price_basis_date=_PRICE_BASIS_DATE,
        used_date=_USED_DATE,
        observed_window_dates=[_USED_DATE, "2026-06-11"],
        generated_at=_GENERATED_AT,
        calendar_verification_status="pending_authoritative_cross_check",
    )


def _projection(value_key, targets, disposition):
    return {
        value_key: {ticker: 75.0 - idx for idx, ticker in enumerate(targets)},
        "neutral_fill_tickers": [],
        "coverage": {ticker: disposition for ticker in targets},
        "target_count": len(targets),
        "scored_count": len(targets),
    }


def _score_composition(targets):
    return compose_score_inputs(
        target_tickers=list(targets),
        momentum_projection=_projection("momentum_by_ticker", targets, "scored"),
        theme_projection=_projection("theme_block_by_ticker", targets, "scored_theme_base"),
        catalyst_projection=_projection("catalyst_block_by_ticker", targets, "scored_realized_catalyst"),
        risk_downgrade_by_ticker={ticker: risk_downgrade() for ticker in targets},
        theme_opportunity_state="strong",
    )


def _constant_projection(value_key, targets, disposition, *, score=50.0):
    return {
        value_key: {ticker: score for ticker in targets},
        "neutral_fill_tickers": [],
        "coverage": {ticker: disposition for ticker in targets},
        "target_count": len(targets),
        "scored_count": len(targets),
    }


def _offering_source(*, signals=None, checked=None, excluded=None):
    return {
        "signals": dict(signals or {}),
        "checked": dict(checked or {}),
        "excluded": dict(excluded or {}),
        "provenance": {},
    }


def _checked_offering():
    return {
        "disposition": "audited_no_active_offering",
        "coverage_status": "full",
        "parser_status": "ok",
    }


def _offering_provenance(*, coverage="full", parser="ok", rid="cik320193"):
    return {
        "provider_id": "sec_edgar",
        "endpoint_or_filing_type": "submissions",
        "source_as_of": _OFFERING_AS_OF,
        "observed_at": _OFFERING_OBSERVED_AT,
        "coverage_status": coverage,
        "parser_status": parser,
        "lineage_ref": f"sec_edgar:submissions:{_OFFERING_AS_OF}#{rid}",
    }


def _offering_filing(form, filing_date, accession):
    return {
        "form": form,
        "filing_date": filing_date,
        "acceptance_datetime": filing_date + "T16:00:00-04:00",
        "accession": accession,
    }


def _offering_record(filings, **provenance_kwargs):
    return {
        "filings": list(filings),
        "provenance": _offering_provenance(**provenance_kwargs),
    }


def _sec_submissions(*, forms, filing_dates, acceptances, accessions):
    return {
        "filings": {
            "recent": {
                "form": list(forms),
                "filingDate": list(filing_dates),
                "acceptanceDateTime": list(acceptances),
                "accessionNumber": list(accessions),
            }
        }
    }


def _grade_provenance(ticker, *, coverage="full", parser="ok"):
    return {
        "provider_id": "fmp",
        "endpoint_or_filing_type": "grades",
        "source_as_of": _GRADE_AS_OF,
        "observed_at": _GRADE_OBSERVED_AT,
        "coverage_status": coverage,
        "parser_status": parser,
        "lineage_ref": f"fmp:grades:{_GRADE_AS_OF}#{ticker.lower()}grades",
    }


def _grade_record(ticker, *, date, action="downgrade", company="BankA", new="Sell", prev="Hold"):
    return {
        "symbol": ticker,
        "date": date,
        "gradingCompany": company,
        "newGrade": new,
        "previousGrade": prev,
        "action": action,
    }


def _grade_source(ticker, records, **provenance_kwargs):
    return {
        "records": list(records),
        "provenance": _grade_provenance(ticker, **provenance_kwargs),
    }


def _news_insight(ticker="AAPL", sentiment="positive"):
    return {
        "ticker": ticker,
        "sentiment": sentiment,
        "sentiment_reasoning": "source sentiment",
    }


def _news_item(*, id="n1", ticker="AAPL", published="2026-06-12T12:00:00Z", sentiment="positive"):
    return {
        "id": id,
        "published_utc": published,
        "publisher": {"name": "Publisher"},
        "title": f"{ticker} news",
        "article_url": "https://example.test/news",
        "tickers": [ticker],
        "insights": [_news_insight(ticker, sentiment)],
    }


def _news_provenance(ticker, *, coverage="full", parser="ok"):
    return {
        "provider_id": "massive",
        "endpoint_or_filing_type": "reference_news",
        "source_as_of": _NEWS_AS_OF,
        "observed_at": _NEWS_OBSERVED_AT,
        "coverage_status": coverage,
        "parser_status": parser,
        "lineage_ref": f"massive:reference_news:{_NEWS_AS_OF}#{ticker.lower()}news",
    }


def _news_source(ticker, records, **provenance_kwargs):
    return {
        "records": list(records),
        "provenance": _news_provenance(ticker, **provenance_kwargs),
    }


def _assemble(artifact, score_targets=("AAPL",), pass2=None):
    return assemble_data_context(
        candidate_artifact=artifact,
        expected_decision_date=_DECISION_DATE,
        eligibility_governance=_gov(),
        score_composition=_score_composition(score_targets),
        candidate_pass2_signals=pass2 if pass2 is not None else {"AAPL": {}},
    )


def _family(*, row_count, price_bearing):
    return {
        "as_of": _DECISION_DATE,
        "observed_at": "2026-06-13T10:00:00",
        "price_basis_date": _PRICE_BASIS_DATE if price_bearing else None,
        "session": "RTH" if price_bearing else None,
        "adjustment": "split_div_adjusted" if price_bearing else None,
        "row_count": row_count,
        "source_refs": [{"role": "test_fixture", "path": "tests/provider/test_us_short_batch5_data_context.py"}],
    }


def _overext_record(state):
    if state == "chasing_extreme":
        return {"overextension_state": "chasing_extreme", "strips_theme_score": True, "execution_flags": {}}
    if state == "warning":
        return {"overextension_state": "warning", "strips_theme_score": False,
                "execution_flags": {"force_pullback": True, "reduce_size": True, "raise_rr_gate": True}}
    return {"overextension_state": "none", "strips_theme_score": False, "execution_flags": {}}


def _overext_map(*, chasing=(), warning=(), targets=("AAPL", "MSFT", "JPM")):
    """A full §4.3 overextension producer map over the Pass1-eligible set (keys = ALL eligible; the data_context
    _scope_overextension scopes it down to the Pass2-clean targets)."""
    chasing, warning = set(chasing), set(warning)
    return {t: _overext_record("chasing_extreme" if t in chasing else "warning" if t in warning else "none")
            for t in targets}


def _official_kwargs():
    # 3 eligible; JPM is Pass2-excluded (partial offering coverage) → pass2_clean = {AAPL, MSFT}. theme=90 (>momentum
    # 50) so the theme_off strip visibly lowers a chasing ticker's core_score; empty grades/news keep risk/catalyst clean.
    return dict(
        candidate_artifact=_candidate_artifact(("AAPL", "MSFT", "JPM")),
        expected_decision_date=_DECISION_DATE,
        eligibility_governance=_gov(),
        momentum_projection=_constant_projection("momentum_by_ticker", ("AAPL", "MSFT"), "scored"),
        theme_projection=_constant_projection("theme_block_by_ticker", ("AAPL", "MSFT"), "scored_theme_base", score=90.0),
        offering_audit_source=resolve_offering_audit(
            as_of=_OFFERING_AS_OF,
            filings_by_ticker={"AAPL": _offering_record([]), "MSFT": _offering_record([]),
                               "JPM": _offering_record([], coverage="partial")}),
        analyst_grade_actions=resolve_analyst_grade_actions(
            as_of=_GRADE_AS_OF,
            grades_by_ticker={"AAPL": _grade_source("AAPL", []), "MSFT": _grade_source("MSFT", [])}),
        massive_news_events=resolve_news_events(
            as_of=_NEWS_AS_OF,
            news_by_ticker={"AAPL": _news_source("AAPL", []), "MSFT": _news_source("MSFT", [])}),
        catalyst_governance=load_catalyst_governance(),
        theme_opportunity_state="strong",
        source_ref_paths={
            "candidate_artifact_path": "state/us_short/test_candidate.json",
            "eligibility_governance_path": "presets/us_short_eligibility_governance_20260624.json",
            "momentum_projection_path": "state/us_short/test_momentum.json",
            "theme_projection_path": "state/us_short/test_theme.json",
            "offering_audit_source_path": "state/us_short/test_offering.json",
            "analyst_grade_actions_path": "state/us_short/test_analyst.json",
            "massive_news_events_path": "state/us_short/test_news.json",
            "catalyst_governance_path": "presets/us_short_catalyst_governance_20260630.json",
        },
    )


class Batch5DataContextAssemblyTest(unittest.TestCase):
    def test_assembles_batch4_data_context_from_candidate_artifact_and_score_seam(self):
        artifact = _candidate_artifact()
        composed = _score_composition(["AAPL"])

        data_context = assemble_data_context(
            candidate_artifact=artifact,
            expected_decision_date=_DECISION_DATE,
            eligibility_governance=_gov(),
            score_composition=composed,
            candidate_pass2_signals={"AAPL": {}},
        )

        self.assertEqual(set(data_context), _DATA_CONTEXT_KEYS)
        self.assertEqual([row["ticker"] for row in data_context["universe"]], ["AAPL", "LOWADV"])
        for row in data_context["universe"]:
            self.assertEqual(set(row), _UNIVERSE_ROW_KEYS)
            for provider_only_key in ("as_of", "observed_at", "provider_id", "lineage", "eligible", "reasons"):
                self.assertNotIn(provider_only_key, row)
        self.assertEqual(data_context["candidate_pass2_signals"], {"AAPL": {}})
        self.assertEqual(data_context["selection_inputs"], composed["selection_inputs"])

        selected = run_selection(_NOW_ET, _SESSIONS, data_context, eligibility_governance=_gov())
        self.assertEqual(selected["decision_date"], _DECISION_DATE)
        self.assertEqual(selected["price_basis_date"], _PRICE_BASIS_DATE)
        self.assertEqual(selected["cheap_eligible"], ["AAPL"])
        self.assertEqual(selected["admitted"], ["AAPL"])

    def test_sec_offering_pass2_source_feeds_data_context_without_manual_signal_map(self):
        active_offering = {
            "recency": "recent",
            "status": "active",
            "materiality": None,
        }
        data_context = assemble_data_context(
            candidate_artifact=_candidate_artifact(("AAPL", "MSFT")),
            expected_decision_date=_DECISION_DATE,
            eligibility_governance=_gov(),
            score_composition=_score_composition(("AAPL", "MSFT")),
            candidate_pass2_signals=None,
            pass2_sources={
                "offering_audit": _offering_source(
                    signals={"MSFT": {"active_offering": active_offering}},
                    checked={"AAPL": {"active_offering": _checked_offering()}},
                )
            },
        )

        self.assertEqual(
            data_context["candidate_pass2_signals"]["MSFT"]["active_offering"],
            active_offering,
        )
        self.assertEqual(data_context["candidate_pass2_signals"]["AAPL"], {})
        verdict = pass2_safety_admit(data_context["candidate_pass2_signals"]["MSFT"], row_context="candidate")
        self.assertEqual(verdict["veto_tier"], "strong_downgrade")
        self.assertTrue(verdict["admit_to_topn"])
        self.assertEqual(list(data_context["selection_inputs"]["per_ticker"]), ["AAPL", "MSFT"])

    def test_real_sec_offering_audit_output_feeds_pass2_source_seam(self):
        source = resolve_offering_audit(
            as_of=_OFFERING_AS_OF,
            filings_by_ticker={
                "AAPL": _offering_record(
                    [_offering_filing("424B5", "2026-06-01", "aapl-424b5")],
                    rid="aapl",
                ),
                "MSFT": _offering_record([], rid="msft"),
                "JPM": _offering_record(
                    [_offering_filing("424B5", "2026-06-01", "jpm-424b5")],
                    coverage="partial",
                    rid="jpm",
                ),
            },
        )
        self.assertEqual(
            source["signals"]["AAPL"]["active_offering"],
            {"recency": "recent", "status": "active", "materiality": None},
        )
        self.assertEqual(source["checked"]["MSFT"]["active_offering"], _checked_offering())
        self.assertIsInstance(source["excluded"]["JPM"]["active_offering"], str)

        data_context = assemble_data_context(
            candidate_artifact=_candidate_artifact(("AAPL", "MSFT", "JPM")),
            expected_decision_date=_DECISION_DATE,
            eligibility_governance=_gov(),
            score_composition=_score_composition(("AAPL", "MSFT")),
            candidate_pass2_signals=None,
            pass2_sources={"offering_audit": source},
        )

        pass2 = data_context["candidate_pass2_signals"]
        self.assertEqual(pass2["AAPL"], {"active_offering": source["signals"]["AAPL"]["active_offering"]})
        aapl_verdict = pass2_safety_admit(pass2["AAPL"], row_context="candidate")
        self.assertEqual(aapl_verdict["veto_tier"], "strong_downgrade")
        self.assertTrue(aapl_verdict["admit_to_topn"])
        self.assertEqual(pass2["MSFT"], {})
        self.assertTrue(pass2_safety_admit(pass2["MSFT"], row_context="candidate")["admit_to_topn"])
        self.assertEqual(pass2["JPM"], {"critical_data_missing": True})
        jpm_verdict = pass2_safety_admit(pass2["JPM"], row_context="candidate")
        self.assertEqual(jpm_verdict["veto_tier"], "entry_hard_veto")
        self.assertFalse(jpm_verdict["admit_to_topn"])
        self.assertEqual(list(data_context["selection_inputs"]["per_ticker"]), ["AAPL", "MSFT"])

    def test_sec_submissions_offering_audit_source_feeds_data_context(self):
        source = build_offering_audit_from_sec_submissions(
            as_of=_OFFERING_AS_OF,
            observed_at=_OFFERING_OBSERVED_AT,
            submissions_by_ticker={
                "AAPL": _sec_submissions(
                    forms=["424B5", "10-Q"],
                    filing_dates=["2026-06-01", "2026-05-01"],
                    acceptances=["2026-06-01T07:00:00-04:00", "2026-05-01T16:00:00-04:00"],
                    accessions=["0000320193-26-000111", "0000320193-26-000112"],
                ),
                "MSFT": _sec_submissions(
                    forms=["10-Q"],
                    filing_dates=["2026-05-01"],
                    acceptances=["2026-05-01T16:00:00-04:00"],
                    accessions=["0000789019-26-000111"],
                ),
                "JPM": _sec_submissions(
                    forms=["8-K"],
                    filing_dates=["2026-05-01"],
                    acceptances=["2026-05-01T16:00:00-04:00"],
                    accessions=["0000019617-26-000111"],
                ),
            },
        )
        self.assertEqual(
            source["signals"]["AAPL"]["active_offering"],
            {"recency": "recent", "status": "active", "materiality": None},
        )
        self.assertEqual(source["checked"]["MSFT"]["active_offering"], _checked_offering())
        self.assertEqual(source["checked"]["JPM"]["active_offering"], _checked_offering())

        data_context = assemble_data_context(
            candidate_artifact=_candidate_artifact(("AAPL", "MSFT", "JPM")),
            expected_decision_date=_DECISION_DATE,
            eligibility_governance=_gov(),
            score_composition=_score_composition(("AAPL", "MSFT", "JPM")),
            candidate_pass2_signals=None,
            pass2_sources={"offering_audit": source},
        )

        pass2 = data_context["candidate_pass2_signals"]
        self.assertEqual(pass2["AAPL"], {"active_offering": source["signals"]["AAPL"]["active_offering"]})
        self.assertEqual(pass2["MSFT"], {})
        self.assertEqual(pass2["JPM"], {})
        aapl_verdict = pass2_safety_admit(pass2["AAPL"], row_context="candidate")
        self.assertEqual(aapl_verdict["veto_tier"], "strong_downgrade")
        self.assertTrue(aapl_verdict["admit_to_topn"])
        self.assertEqual(list(data_context["selection_inputs"]["per_ticker"]), ["AAPL", "MSFT", "JPM"])

    def test_sec_submissions_wrapper_feeds_data_context_without_prebuilt_source(self):
        data_context = assemble_data_context_from_sec_offering_submissions(
            candidate_artifact=_candidate_artifact(("AAPL", "MSFT", "JPM")),
            expected_decision_date=_DECISION_DATE,
            eligibility_governance=_gov(),
            score_composition=_score_composition(("AAPL", "MSFT", "JPM")),
            offering_as_of=_OFFERING_AS_OF,
            offering_observed_at=_OFFERING_OBSERVED_AT,
            offering_submissions_by_ticker={
                "AAPL": _sec_submissions(
                    forms=["424B5"],
                    filing_dates=["2026-06-01"],
                    acceptances=["2026-06-01T07:00:00-04:00"],
                    accessions=["0000320193-26-000111"],
                ),
                "MSFT": _sec_submissions(
                    forms=["10-Q"],
                    filing_dates=["2026-05-01"],
                    acceptances=["2026-05-01T16:00:00-04:00"],
                    accessions=["0000789019-26-000111"],
                ),
                "JPM": _sec_submissions(
                    forms=["8-K"],
                    filing_dates=["2026-05-01"],
                    acceptances=["2026-05-01T16:00:00-04:00"],
                    accessions=["0000019617-26-000111"],
                ),
            },
        )

        pass2 = data_context["candidate_pass2_signals"]
        self.assertEqual(
            pass2["AAPL"]["active_offering"],
            {"recency": "recent", "status": "active", "materiality": None},
        )
        self.assertEqual(pass2["MSFT"], {})
        self.assertEqual(pass2["JPM"], {})
        self.assertEqual(list(data_context["selection_inputs"]["per_ticker"]), ["AAPL", "MSFT", "JPM"])

    def test_sec_submissions_wrapper_rejects_missing_candidate_source(self):
        with self.assertRaises(DataContextAssemblyError):
            assemble_data_context_from_sec_offering_submissions(
                candidate_artifact=_candidate_artifact(("AAPL", "MSFT")),
                expected_decision_date=_DECISION_DATE,
                eligibility_governance=_gov(),
                score_composition=_score_composition(("AAPL", "MSFT")),
                offering_as_of=_OFFERING_AS_OF,
                offering_observed_at=_OFFERING_OBSERVED_AT,
                offering_submissions_by_ticker={
                    "AAPL": _sec_submissions(
                        forms=["10-Q"],
                        filing_dates=["2026-05-01"],
                        acceptances=["2026-05-01T16:00:00-04:00"],
                        accessions=["0000320193-26-000111"],
                    )
                },
            )

    def test_sec_offering_pass2_source_missing_candidate_disposition_rejected(self):
        with self.assertRaises(DataContextAssemblyError):
            assemble_data_context(
                candidate_artifact=_candidate_artifact(("AAPL", "MSFT")),
                expected_decision_date=_DECISION_DATE,
                eligibility_governance=_gov(),
                score_composition=_score_composition(("AAPL", "MSFT")),
                candidate_pass2_signals=None,
                pass2_sources={
                    "offering_audit": _offering_source(
                        checked={"AAPL": {"active_offering": _checked_offering()}}
                    )
                },
            )

    def test_sec_offering_pass2_source_excluded_candidate_fails_closed(self):
        data_context = assemble_data_context(
            candidate_artifact=_candidate_artifact(("AAPL", "MSFT")),
            expected_decision_date=_DECISION_DATE,
            eligibility_governance=_gov(),
            score_composition=_score_composition(("MSFT",)),
            candidate_pass2_signals=None,
            pass2_sources={
                "offering_audit": _offering_source(
                    excluded={
                        "AAPL": {
                            "active_offering": "coverage=partial/parser=ok",
                        }
                    },
                    checked={"MSFT": {"active_offering": _checked_offering()}},
                )
            },
        )

        self.assertEqual(
            data_context["candidate_pass2_signals"]["AAPL"],
            {"critical_data_missing": True},
        )
        self.assertEqual(list(data_context["selection_inputs"]["per_ticker"]), ["MSFT"])

    def test_sec_offering_pass2_source_duplicate_disposition_rejected(self):
        with self.assertRaises(DataContextAssemblyError):
            assemble_data_context(
                candidate_artifact=_candidate_artifact(("AAPL",)),
                expected_decision_date=_DECISION_DATE,
                eligibility_governance=_gov(),
                score_composition=_score_composition(("AAPL",)),
                candidate_pass2_signals=None,
                pass2_sources={
                    "offering_audit": _offering_source(
                        signals={
                            "AAPL": {
                                "active_offering": {
                                    "recency": "recent",
                                    "status": "active",
                                    "materiality": None,
                                }
                            }
                        },
                        checked={"AAPL": {"active_offering": _checked_offering()}},
                    )
                },
            )

    def test_analyst_grade_source_feeds_data_context_score_without_manual_risk_map(self):
        targets = ("AAPL", "MSFT")
        analyst_grade_actions = resolve_analyst_grade_actions(
            as_of=_GRADE_AS_OF,
            grades_by_ticker={
                "AAPL": _grade_source("AAPL", [
                    _grade_record("AAPL", date="2026-06-10", company="BankA"),
                    _grade_record("AAPL", date="2026-06-11", company="BankB"),
                ]),
                "MSFT": _grade_source("MSFT", []),
            },
        )

        data_context = assemble_data_context_with_analyst_grade_risk(
            candidate_artifact=_candidate_artifact(targets),
            expected_decision_date=_DECISION_DATE,
            eligibility_governance=_gov(),
            momentum_projection=_constant_projection("momentum_by_ticker", targets, "scored"),
            theme_projection=_constant_projection("theme_block_by_ticker", targets, "scored_theme_base"),
            catalyst_projection=_constant_projection(
                "catalyst_block_by_ticker",
                targets,
                "scored_realized_catalyst",
            ),
            analyst_grade_actions=analyst_grade_actions,
            theme_opportunity_state="strong",
            candidate_pass2_signals={"AAPL": {}, "MSFT": {}},
        )

        scores = data_context["selection_inputs"]["per_ticker"]
        self.assertAlmostEqual(scores["AAPL"]["core_score"], 50.0 - ANALYST_DOWNGRADE_PENALTY)
        self.assertAlmostEqual(scores["MSFT"]["core_score"], 50.0)
        self.assertEqual(data_context["candidate_pass2_signals"], {"AAPL": {}, "MSFT": {}})

    def test_analyst_grade_wrapper_scores_only_pass2_clean_candidates(self):
        analyst_grade_actions = resolve_analyst_grade_actions(
            as_of=_GRADE_AS_OF,
            grades_by_ticker={
                "AAPL": _grade_source("AAPL", [
                    _grade_record("AAPL", date="2026-06-10", company="BankA"),
                    _grade_record("AAPL", date="2026-06-11", company="BankB"),
                ]),
            },
        )

        data_context = assemble_data_context_with_analyst_grade_risk(
            candidate_artifact=_candidate_artifact(("AAPL", "MSFT")),
            expected_decision_date=_DECISION_DATE,
            eligibility_governance=_gov(),
            momentum_projection=_constant_projection("momentum_by_ticker", ("AAPL",), "scored"),
            theme_projection=_constant_projection("theme_block_by_ticker", ("AAPL",), "scored_theme_base"),
            catalyst_projection=_constant_projection("catalyst_block_by_ticker", ("AAPL",), "scored_realized_catalyst"),
            analyst_grade_actions=analyst_grade_actions,
            theme_opportunity_state="strong",
            candidate_pass2_signals={"AAPL": {}, "MSFT": {"critical_data_missing": True}},
        )

        self.assertEqual(list(data_context["selection_inputs"]["per_ticker"]), ["AAPL"])
        self.assertEqual(set(data_context["candidate_pass2_signals"]), {"AAPL", "MSFT"})

    def test_analyst_grade_wrapper_rejects_malformed_source(self):
        with self.assertRaises(DataContextAssemblyError):
            assemble_data_context_with_analyst_grade_risk(
                candidate_artifact=_candidate_artifact(("AAPL",)),
                expected_decision_date=_DECISION_DATE,
                eligibility_governance=_gov(),
                momentum_projection=_constant_projection("momentum_by_ticker", ("AAPL",), "scored"),
                theme_projection=_constant_projection("theme_block_by_ticker", ("AAPL",), "scored_theme_base"),
                catalyst_projection=_constant_projection(
                    "catalyst_block_by_ticker",
                    ("AAPL",),
                    "scored_realized_catalyst",
                ),
                analyst_grade_actions={"signals": {"AAPL": {"analyst_actions_recent": {"downgrades": "2"}}}},
                theme_opportunity_state="strong",
                candidate_pass2_signals={"AAPL": {}},
            )

    def test_massive_news_source_feeds_data_context_score_without_manual_catalyst_projection(self):
        targets = ("AAPL", "MSFT")
        news_events = resolve_news_events(
            as_of=_NEWS_AS_OF,
            news_by_ticker={
                "AAPL": _news_source("AAPL", [_news_item(id="a", sentiment="positive")]),
                "MSFT": _news_source("MSFT", []),
            },
        )

        data_context = assemble_data_context_with_massive_news_catalyst(
            candidate_artifact=_candidate_artifact(targets),
            expected_decision_date=_DECISION_DATE,
            eligibility_governance=_gov(),
            momentum_projection=_constant_projection("momentum_by_ticker", targets, "scored"),
            theme_projection=_constant_projection("theme_block_by_ticker", targets, "scored_theme_base"),
            massive_news_events=news_events,
            catalyst_governance=load_catalyst_governance(),
            theme_opportunity_state="strong",
            candidate_pass2_signals={"AAPL": {}, "MSFT": {}},
        )

        scores = data_context["selection_inputs"]["per_ticker"]
        self.assertAlmostEqual(scores["AAPL"]["core_score"], 51.5)
        self.assertAlmostEqual(scores["MSFT"]["core_score"], 50.0)
        self.assertEqual(data_context["candidate_pass2_signals"], {"AAPL": {}, "MSFT": {}})

    def test_massive_news_wrapper_scores_only_pass2_clean_candidates(self):
        news_events = resolve_news_events(
            as_of=_NEWS_AS_OF,
            news_by_ticker={
                "AAPL": _news_source("AAPL", [_news_item(id="a", sentiment="positive")]),
                "MSFT": _news_source("MSFT", [_news_item(id="m", ticker="MSFT", sentiment="positive")]),
            },
        )

        data_context = assemble_data_context_with_massive_news_catalyst(
            candidate_artifact=_candidate_artifact(("AAPL", "MSFT")),
            expected_decision_date=_DECISION_DATE,
            eligibility_governance=_gov(),
            momentum_projection=_constant_projection("momentum_by_ticker", ("AAPL",), "scored"),
            theme_projection=_constant_projection("theme_block_by_ticker", ("AAPL",), "scored_theme_base"),
            massive_news_events=news_events,
            catalyst_governance=load_catalyst_governance(),
            theme_opportunity_state="strong",
            candidate_pass2_signals={"AAPL": {}, "MSFT": {"critical_data_missing": True}},
        )

        self.assertEqual(list(data_context["selection_inputs"]["per_ticker"]), ["AAPL"])
        self.assertEqual(set(data_context["candidate_pass2_signals"]), {"AAPL", "MSFT"})

    def test_massive_news_wrapper_rejects_source_clock_mismatch(self):
        news_events = resolve_news_events(
            as_of="2026-06-30",
            news_by_ticker={
                "AAPL": {
                    "records": [_news_item(id="a", sentiment="positive")],
                    "provenance": {
                        **_news_provenance("AAPL"),
                        "source_as_of": "2026-06-30",
                        "lineage_ref": "massive:reference_news:2026-06-30#aaplnews",
                    },
                }
            },
        )

        with self.assertRaises(DataContextAssemblyError):
            assemble_data_context_with_massive_news_catalyst(
                candidate_artifact=_candidate_artifact(("AAPL",)),
                expected_decision_date=_DECISION_DATE,
                eligibility_governance=_gov(),
                momentum_projection=_constant_projection("momentum_by_ticker", ("AAPL",), "scored"),
                theme_projection=_constant_projection("theme_block_by_ticker", ("AAPL",), "scored_theme_base"),
                massive_news_events=news_events,
                catalyst_governance=load_catalyst_governance(),
                theme_opportunity_state="strong",
                candidate_pass2_signals={"AAPL": {}},
            )

    def test_massive_news_wrapper_wraps_malformed_catalyst_governance(self):
        news_events = resolve_news_events(
            as_of=_NEWS_AS_OF,
            news_by_ticker={
                "AAPL": _news_source("AAPL", [_news_item(id="a", sentiment="positive")]),
            },
        )

        with self.assertRaises(DataContextAssemblyError):
            assemble_data_context_with_massive_news_catalyst(
                candidate_artifact=_candidate_artifact(("AAPL",)),
                expected_decision_date=_DECISION_DATE,
                eligibility_governance=_gov(),
                momentum_projection=_constant_projection("momentum_by_ticker", ("AAPL",), "scored"),
                theme_projection=_constant_projection("theme_block_by_ticker", ("AAPL",), "scored_theme_base"),
                massive_news_events=news_events,
                catalyst_governance={"broken": True},
                theme_opportunity_state="strong",
                candidate_pass2_signals={"AAPL": {}},
            )

    def test_resolved_pass2_sources_compose_offering_analyst_and_news_in_one_data_context(self):
        offering_source = _offering_source(
            checked={
                "AAPL": {"active_offering": _checked_offering()},
                "MSFT": {"active_offering": _checked_offering()},
            },
            excluded={
                "JPM": {"active_offering": "coverage=partial/parser=ok"},
            },
        )
        analyst_grade_actions = resolve_analyst_grade_actions(
            as_of=_GRADE_AS_OF,
            grades_by_ticker={
                "AAPL": _grade_source("AAPL", [
                    _grade_record("AAPL", date="2026-06-10", company="BankA"),
                    _grade_record("AAPL", date="2026-06-11", company="BankB"),
                ]),
                "JPM": _grade_source("JPM", [
                    _grade_record("JPM", date="2026-06-10", company="BankA"),
                    _grade_record("JPM", date="2026-06-11", company="BankB"),
                ]),
            },
        )
        news_events = resolve_news_events(
            as_of=_NEWS_AS_OF,
            news_by_ticker={
                "AAPL": _news_source("AAPL", [_news_item(id="a", sentiment="positive")]),
                "JPM": _news_source("JPM", [_news_item(id="j", ticker="JPM", sentiment="positive")]),
            },
        )

        data_context = assemble_data_context_from_resolved_pass2_sources(
            candidate_artifact=_candidate_artifact(("AAPL", "MSFT", "JPM")),
            expected_decision_date=_DECISION_DATE,
            eligibility_governance=_gov(),
            momentum_projection=_constant_projection("momentum_by_ticker", ("AAPL", "MSFT"), "scored"),
            theme_projection=_constant_projection("theme_block_by_ticker", ("AAPL", "MSFT"), "scored_theme_base"),
            offering_audit_source=offering_source,
            analyst_grade_actions=analyst_grade_actions,
            massive_news_events=news_events,
            catalyst_governance=load_catalyst_governance(),
            theme_opportunity_state="strong",
        )

        pass2 = data_context["candidate_pass2_signals"]
        self.assertEqual(pass2["AAPL"], {})
        self.assertEqual(pass2["MSFT"], {})
        self.assertEqual(pass2["JPM"], {"critical_data_missing": True})
        self.assertEqual(set(data_context["selection_inputs"]["per_ticker"]), {"AAPL", "MSFT"})
        scores = data_context["selection_inputs"]["per_ticker"]
        self.assertAlmostEqual(scores["AAPL"]["core_score"], 51.5 - ANALYST_DOWNGRADE_PENALTY)
        self.assertAlmostEqual(scores["MSFT"]["core_score"], 50.0)

    def test_resolved_pass2_sources_emit_official_components_with_source_refs(self):
        offering_source = resolve_offering_audit(
            as_of=_OFFERING_AS_OF,
            filings_by_ticker={
                "AAPL": _offering_record([]),
                "MSFT": _offering_record([]),
                "JPM": _offering_record([], coverage="partial"),
            },
        )
        analyst_grade_actions = resolve_analyst_grade_actions(
            as_of=_GRADE_AS_OF,
            grades_by_ticker={
                "AAPL": _grade_source(
                    "AAPL",
                    [
                        _grade_record("AAPL", date="2026-06-10", company="BankA"),
                        _grade_record("AAPL", date="2026-06-11", company="BankB"),
                    ],
                ),
                "MSFT": _grade_source("MSFT", []),
            },
        )
        news_events = resolve_news_events(
            as_of=_NEWS_AS_OF,
            news_by_ticker={
                "AAPL": _news_source("AAPL", [_news_item(id="a", sentiment="positive")]),
                "MSFT": _news_source("MSFT", []),
            },
        )
        source_ref_paths = {
            "candidate_artifact_path": "state/us_short/test_candidate.json",
            "eligibility_governance_path": "presets/us_short_eligibility_governance_20260624.json",
            "momentum_projection_path": "state/us_short/test_momentum.json",
            "theme_projection_path": "state/us_short/test_theme.json",
            "offering_audit_source_path": "state/us_short/test_offering.json",
            "analyst_grade_actions_path": "state/us_short/test_analyst.json",
            "massive_news_events_path": "state/us_short/test_news.json",
            "catalyst_governance_path": "presets/us_short_catalyst_governance_20260630.json",
        }

        components = assemble_official_context_components_from_resolved_pass2_sources(
            candidate_artifact=_candidate_artifact(("AAPL", "MSFT", "JPM")),
            expected_decision_date=_DECISION_DATE,
            eligibility_governance=_gov(),
            momentum_projection=_constant_projection("momentum_by_ticker", ("AAPL", "MSFT"), "scored"),
            theme_projection=_constant_projection("theme_block_by_ticker", ("AAPL", "MSFT"), "scored_theme_base"),
            offering_audit_source=offering_source,
            analyst_grade_actions=analyst_grade_actions,
            massive_news_events=news_events,
            catalyst_governance=load_catalyst_governance(),
            theme_opportunity_state="strong",
            source_ref_paths=source_ref_paths,
        )

        data_context = components["data_context"]
        per_ticker_analysis = components["per_ticker_analysis"]
        self.assertEqual(set(components), {"data_context", "per_ticker_analysis", "run_provenance"})
        self.assertEqual(set(per_ticker_analysis), set(data_context["selection_inputs"]["per_ticker"]))
        self.assertEqual(per_ticker_analysis["AAPL"]["ticker"], "AAPL")
        self.assertEqual(per_ticker_analysis["AAPL"]["row_source"], "top15_candidate")
        self.assertEqual(
            set(per_ticker_analysis["AAPL"]["score_blocks"]),
            {"momentum", "theme", "catalyst"},
        )
        self.assertEqual(data_context["candidate_pass2_signals"]["JPM"], {"critical_data_missing": True})

        run_provenance = components["run_provenance"]
        families = run_provenance["families"]
        self.assertEqual(families["universe"]["row_count"], len(data_context["universe"]))
        self.assertEqual(families["candidate_pass2_signals"]["row_count"], len(data_context["candidate_pass2_signals"]))
        self.assertEqual(families["selection_inputs"]["row_count"], len(data_context["selection_inputs"]["per_ticker"]))
        self.assertEqual(families["per_ticker_analysis"]["row_count"], len(per_ticker_analysis))
        for family in families.values():
            self.assertTrue(family["source_refs"])
        self.assertIn(
            {"role": "candidate_artifact", "path": source_ref_paths["candidate_artifact_path"]},
            families["universe"]["source_refs"],
        )
        self.assertIn(
            {"role": "offering_audit_source", "path": source_ref_paths["offering_audit_source_path"]},
            families["candidate_pass2_signals"]["source_refs"],
        )

        reconciled = reconcile_run_provenance(
            run_provenance,
            now_et=datetime(2026, 6, 15, 8, 30, 0),
            decision_date=_DECISION_DATE,
            price_basis_date=_PRICE_BASIS_DATE,
            run_date="20260615",
            payloads={
                "universe": data_context["universe"],
                "per_ticker_analysis": per_ticker_analysis,
                "candidate_pass2_signals": data_context["candidate_pass2_signals"],
                "selection_inputs": data_context["selection_inputs"],
            },
        )
        self.assertEqual(reconciled["as_of"], _DECISION_DATE)

    def test_resolved_pass2_sources_wrap_boundary_tz_observed_at_overflow(self):
        source_ref_paths = {
            "candidate_artifact_path": "state/us_short/test_candidate.json",
            "eligibility_governance_path": "presets/us_short_eligibility_governance_20260624.json",
            "momentum_projection_path": "state/us_short/test_momentum.json",
            "theme_projection_path": "state/us_short/test_theme.json",
            "offering_audit_source_path": "state/us_short/test_offering.json",
            "analyst_grade_actions_path": "state/us_short/test_analyst.json",
            "massive_news_events_path": "state/us_short/test_news.json",
            "catalyst_governance_path": "presets/us_short_catalyst_governance_20260630.json",
        }

        for observed_at in ("0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00"):
            with self.subTest(observed_at=observed_at):
                offering_source = _offering_source(
                    checked={"AAPL": {"active_offering": _checked_offering()}},
                )
                offering_source["provenance"] = {
                    "AAPL": {"active_offering": _offering_provenance()},
                }
                offering_source["provenance"]["AAPL"]["active_offering"]["observed_at"] = observed_at
                analyst_grade_actions = resolve_analyst_grade_actions(
                    as_of=_GRADE_AS_OF,
                    grades_by_ticker={"AAPL": _grade_source("AAPL", [])},
                )
                news_events = resolve_news_events(
                    as_of=_NEWS_AS_OF,
                    news_by_ticker={"AAPL": _news_source("AAPL", [])},
                )

                with self.assertRaises(DataContextAssemblyError):
                    assemble_official_context_components_from_resolved_pass2_sources(
                        candidate_artifact=_candidate_artifact(("AAPL",)),
                        expected_decision_date=_DECISION_DATE,
                        eligibility_governance=_gov(),
                        momentum_projection=_constant_projection("momentum_by_ticker", ("AAPL",), "scored"),
                        theme_projection=_constant_projection("theme_block_by_ticker", ("AAPL",), "scored_theme_base"),
                        offering_audit_source=offering_source,
                        analyst_grade_actions=analyst_grade_actions,
                        massive_news_events=news_events,
                        catalyst_governance=load_catalyst_governance(),
                        theme_opportunity_state="strong",
                        source_ref_paths=source_ref_paths,
                    )

    def test_resolved_pass2_sources_wrap_malformed_catalyst_governance(self):
        offering_source = _offering_source(
            checked={
                "AAPL": {"active_offering": _checked_offering()},
            },
        )
        analyst_grade_actions = resolve_analyst_grade_actions(
            as_of=_GRADE_AS_OF,
            grades_by_ticker={"AAPL": _grade_source("AAPL", [])},
        )
        news_events = resolve_news_events(
            as_of=_NEWS_AS_OF,
            news_by_ticker={"AAPL": _news_source("AAPL", [_news_item(id="a", sentiment="positive")])},
        )

        with self.assertRaises(DataContextAssemblyError):
            assemble_data_context_from_resolved_pass2_sources(
                candidate_artifact=_candidate_artifact(("AAPL",)),
                expected_decision_date=_DECISION_DATE,
                eligibility_governance=_gov(),
                momentum_projection=_constant_projection("momentum_by_ticker", ("AAPL",), "scored"),
                theme_projection=_constant_projection("theme_block_by_ticker", ("AAPL",), "scored_theme_base"),
                offering_audit_source=offering_source,
                analyst_grade_actions=analyst_grade_actions,
                massive_news_events=news_events,
                catalyst_governance={"broken": True},
                theme_opportunity_state="strong",
            )

    def test_rejects_forged_candidate_artifact_instead_of_trusting_summary(self):
        artifact = _candidate_artifact()
        artifact["summary"]["eligible_count"] = 99

        with self.assertRaises(DataContextAssemblyError):
            _assemble(artifact)

    def test_rejects_wrong_decision_date_artifact(self):
        artifact = _candidate_artifact()
        artifact["decision_date"] = "20260616"

        with self.assertRaises(DataContextAssemblyError):
            _assemble(artifact)

    def test_pass2_signals_must_exactly_cover_pass1_eligible_candidates(self):
        artifact = _candidate_artifact()

        for bad_pass2 in ({}, {"AAPL": {}, "MSFT": {}}):
            with self.subTest(bad_pass2=bad_pass2):
                with self.assertRaises(DataContextAssemblyError):
                    _assemble(artifact, pass2=bad_pass2)

    def test_score_targets_must_cover_pass2_clean_candidates_not_vetoed_candidates(self):
        artifact = _candidate_artifact(("AAPL", "MSFT"))

        data_context = _assemble(
            artifact,
            score_targets=("AAPL",),
            pass2={"AAPL": {}, "MSFT": {"delisted": True}},
        )
        self.assertEqual(set(data_context["selection_inputs"]["per_ticker"]), {"AAPL"})

        with self.assertRaises(DataContextAssemblyError):
            _assemble(
                artifact,
                score_targets=("AAPL", "MSFT"),
                pass2={"AAPL": {}, "MSFT": {"delisted": True}},
            )

    def test_strips_provider_row_clocks_before_run_provenance_binding(self):
        data_context = _assemble(_candidate_artifact())
        run_provenance = {
            "as_of": _DECISION_DATE,
            "price_basis_date": _PRICE_BASIS_DATE,
            "families": {
                "universe": _family(row_count=len(data_context["universe"]), price_bearing=True),
                "per_ticker_analysis": _family(row_count=0, price_bearing=True),
                "candidate_pass2_signals": _family(
                    row_count=len(data_context["candidate_pass2_signals"]),
                    price_bearing=False,
                ),
                "selection_inputs": _family(
                    row_count=len(data_context["selection_inputs"]["per_ticker"]),
                    price_bearing=False,
                ),
            },
        }

        out = reconcile_run_provenance(
            run_provenance,
            now_et=_NOW_ET,
            decision_date=_DECISION_DATE,
            price_basis_date=_PRICE_BASIS_DATE,
            run_date="20260613",
            payloads={
                "universe": data_context["universe"],
                "per_ticker_analysis": {},
                "candidate_pass2_signals": data_context["candidate_pass2_signals"],
                "selection_inputs": data_context["selection_inputs"],
            },
        )

        self.assertEqual(out["as_of"], _DECISION_DATE)


    def test_overextension_map_strips_chasing_theme_and_threads_tier_onto_analysis_rows(self):
        # AAPL chasing (theme-strip, selection) + MSFT warning (execution-side, keeps theme). JPM is Pass2-excluded,
        # so the producer map covers it but _scope_overextension drops it before compose.
        base = assemble_official_context_components_from_resolved_pass2_sources(**_official_kwargs())
        comps = assemble_official_context_components_from_resolved_pass2_sources(
            **_official_kwargs(), overextension_by_ticker=_overext_map(chasing=["AAPL"], warning=["MSFT"]))

        per = comps["data_context"]["selection_inputs"]["per_ticker"]
        rows = comps["per_ticker_analysis"]
        base_per = base["data_context"]["selection_inputs"]["per_ticker"]

        # AAPL chasing: core_score recomputed under theme_off (strictly LOWER than the un-stripped run since theme was
        # boosting it), theme_momentum zeroed, analysis row carries theme_off + the chasing tier.
        self.assertAlmostEqual(per["AAPL"]["core_score"],
                               core_score(rows["AAPL"]["score_blocks"], "theme_off")["core_score"])
        self.assertLess(per["AAPL"]["core_score"], base_per["AAPL"]["core_score"])
        self.assertEqual(per["AAPL"]["theme_momentum_score"], 0.0)
        self.assertEqual(rows["AAPL"]["scoring_profile"], "theme_off")
        self.assertEqual(rows["AAPL"]["overextension"]["overextension_state"], "chasing_extreme")

        # MSFT warning: does NOT strip — core/theme_momentum/profile unchanged vs base; its analysis row carries the
        # warning tier with the execution flags _analyze_one consumes.
        self.assertAlmostEqual(per["MSFT"]["core_score"], base_per["MSFT"]["core_score"])
        self.assertEqual(per["MSFT"]["theme_momentum_score"], base_per["MSFT"]["theme_momentum_score"])
        self.assertEqual(rows["MSFT"]["scoring_profile"], "balanced")
        self.assertEqual(rows["MSFT"]["overextension"]["overextension_state"], "warning")
        self.assertIs(rows["MSFT"]["overextension"]["execution_flags"]["force_pullback"], True)

    def test_overextension_reconciliation_holds_through_analyze_rows(self):
        # the 承重接缝 end-to-end through the REAL data_context: the chasing analysis row (theme_off) + its selection
        # record (the stripped selection score) run through analyze_rows WITHOUT the 1e-6 same-run-fork raise.
        comps = assemble_official_context_components_from_resolved_pass2_sources(
            **_official_kwargs(), overextension_by_ticker=_overext_map(chasing=["AAPL"]))
        per = comps["data_context"]["selection_inputs"]["per_ticker"]["AAPL"]
        row = {
            **comps["per_ticker_analysis"]["AAPL"],
            "price_input": {"close": 101.0, "bars": []},
            "selection_record": {"selection_rank": 1, "selection_bucket": "core_top", **per},
        }
        analyzed = analyze_rows(
            [row], market_axis_regimes={"vix": "进攻", "market_trend": "进攻", "breadth": "进攻"})["rows"][0]
        self.assertEqual(analyzed["score"]["profile"], "theme_off")
        self.assertAlmostEqual(analyzed["score"]["core_score"], per["core_score"])

    def test_no_overextension_map_leaves_rows_without_overextension_field(self):
        comps = assemble_official_context_components_from_resolved_pass2_sources(**_official_kwargs())
        for ticker in ("AAPL", "MSFT"):
            self.assertNotIn("overextension", comps["per_ticker_analysis"][ticker])
            self.assertEqual(comps["per_ticker_analysis"][ticker]["scoring_profile"], "balanced")

    def test_overextension_map_missing_pass2_target_or_non_dict_fails_closed(self):
        bad = _overext_map(chasing=["AAPL"])
        del bad["MSFT"]   # MSFT is Pass2-clean but missing from the map → wiring bug → fail closed
        with self.assertRaises(DataContextAssemblyError):
            assemble_official_context_components_from_resolved_pass2_sources(
                **_official_kwargs(), overextension_by_ticker=bad)
        with self.assertRaises(DataContextAssemblyError):
            assemble_official_context_components_from_resolved_pass2_sources(
                **_official_kwargs(), overextension_by_ticker=["AAPL"])


if __name__ == "__main__":
    unittest.main()
