from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_eligibility_gate import load_eligibility_governance, pass2_safety_admit  # noqa: E402
from engine.us_short_risk_downgrade import risk_downgrade  # noqa: E402
from engine.us_short_run_provenance import reconcile_run_provenance  # noqa: E402
from engine.us_short_sec_offering_audit import (  # noqa: E402
    build_offering_audit_from_sec_submissions,
    resolve_offering_audit,
)
from engine.us_short_seam_score import compose_score_inputs  # noqa: E402
from engine.us_short_weekend_pipeline import run_selection  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402
from runners.us_short_batch5_data_context import (  # noqa: E402
    DataContextAssemblyError,
    assemble_data_context,
    assemble_data_context_from_sec_offering_submissions,
)


_GOV_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
_DECISION_DATE = "20260615"
_PRICE_BASIS_DATE = "20260612"
_USED_DATE = "2026-06-12"
_GENERATED_AT = "2026-06-13T10:00:00+00:00"
_OFFERING_AS_OF = "2026-06-15"
_OFFERING_OBSERVED_AT = "2026-06-15T08:00:00-04:00"
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
    }


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


if __name__ == "__main__":
    unittest.main()
