from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_short_batch5_full_candidate_live_source_packet as runner  # noqa: E402
from runners import us_short_batch5_full_candidate_pass2_preflight as preflight_runner  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _OFFERING_OBSERVED_AT,
    _candidate_artifact,
    _constant_projection,
)


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_DIR = ROOT / "provider_samples" / "us_short_batch5_full_candidate_live_source_packet_20260706"
PREFLIGHT_SAMPLE_DIR = ROOT / "provider_samples" / "us_short_batch5_full_candidate_pass2_preflight_20260706"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class FullCandidateFakeClient:
    def __init__(self):
        self.urls: list[str] = []

    def get_json(self, url, headers=None, timeout_seconds=30):
        self.urls.append(url)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.netloc == "www.sec.gov" and parsed.path.endswith("/company_tickers.json"):
            return (
                {
                    "0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."},
                    "1": {"ticker": "MSFT", "cik_str": 789019, "title": "Microsoft Corp"},
                    "2": {"ticker": "JPM", "cik_str": 19617, "title": "JPMorgan Chase & Co"},
                },
                200,
                True,
                None,
            )
        if parsed.netloc == "data.sec.gov" and parsed.path.startswith("/submissions/"):
            accession = parsed.path.rsplit("CIK", 1)[-1].split(".", 1)[0]
            return (
                {
                    "filings": {
                        "recent": {
                            "form": ["10-Q"],
                            "filingDate": ["2026-06-01"],
                            "acceptanceDateTime": ["2026-06-01T08:00:00-04:00"],
                            "accessionNumber": [f"{int(accession):010d}-26-000001"],
                        }
                    }
                },
                200,
                True,
                None,
            )
        if parsed.netloc == "financialmodelingprep.com" and parsed.path.endswith("/grades"):
            symbol = query["symbol"][0]
            records = []
            if symbol == "AAPL":
                records = [
                    {
                        "symbol": symbol,
                        "date": "2026-06-10",
                        "gradingCompany": "BankA",
                        "newGrade": "Sell",
                        "previousGrade": "Hold",
                        "action": "downgrade",
                    },
                    {
                        "symbol": symbol,
                        "date": "2026-06-11",
                        "gradingCompany": "BankB",
                        "newGrade": "Sell",
                        "previousGrade": "Hold",
                        "action": "downgrade",
                    },
                ]
            return (records, 200, True, None)
        if parsed.netloc == "api.massive.com" and parsed.path == "/stocks/v1/splits":
            symbol = query["ticker"][0]
            return (
                {
                    "results": [
                        {
                            "ticker": symbol,
                            "execution_date": "2020-08-31",
                            "split_from": 1,
                            "split_to": 4,
                            "adjustment_type": "split",
                            "historical_adjustment_factor": 0.25,
                            "id": f"{symbol}-split-1",
                        }
                    ]
                },
                200,
                True,
                None,
            )
        if parsed.netloc == "api.massive.com" and parsed.path == "/stocks/v1/dividends":
            symbol = query["ticker"][0]
            return (
                {
                    "results": [
                        {
                            "ticker": symbol,
                            "ex_dividend_date": "2026-05-09",
                            "cash_amount": 0.25,
                            "pay_date": "2026-05-16",
                            "record_date": "2026-05-12",
                            "declaration_date": "2026-05-01",
                            "currency": "USD",
                            "frequency": 4,
                            "distribution_type": "CD",
                            "split_adjusted_cash_amount": 0.25,
                            "historical_adjustment_factor": 1.0,
                            "id": f"{symbol}-div-1",
                        }
                    ]
                },
                200,
                True,
                None,
            )
        if parsed.netloc == "api.massive.com" and parsed.path == "/v2/reference/news":
            symbol = query["ticker"][0]
            records = []
            if symbol == "AAPL":
                records = [
                    {
                        "id": "aapl-news-1",
                        "published_utc": "2026-06-12T12:00:00Z",
                        "publisher": {"name": "Publisher"},
                        "title": "Apple catalyst",
                        "article_url": "https://example.test/aapl",
                        "tickers": [symbol],
                        "insights": [
                            {
                                "ticker": symbol,
                                "sentiment": "positive",
                                "sentiment_reasoning": "source sentiment",
                            }
                        ],
                    }
                ]
            return ({"results": records}, 200, True, None)
        raise AssertionError(f"unexpected URL: {url}")


class UsShortBatch5FullCandidateLiveSourcePacketTest(unittest.TestCase):
    def setUp(self):
        self.slug = f"fc_live_{os.getpid()}_{abs(hash(self._testMethodName)) % 100000}"
        self.raw_root = SAMPLE_DIR / self.slug / "raw"
        self.paths = {
            "candidate": STATE_DIR / f"{self.slug}_candidate.json",
            "momentum": STATE_DIR / f"{self.slug}_momentum.json",
            "theme": STATE_DIR / f"{self.slug}_theme.json",
            "preflight": PREFLIGHT_SAMPLE_DIR / self.slug / "preflight.json",
            "summary": SAMPLE_DIR / self.slug / "summary.json",
            "prefix": STATE_DIR / self.slug,
            "output": STATE_DIR / f"{self.slug}_data_context.json",
            "components": STATE_DIR / f"{self.slug}_context_components.json",
        }
        for path in list(self.paths.values()) + [self.raw_root]:
            if path.is_dir():
                for item in sorted(path.rglob("*"), reverse=True):
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        item.rmdir()
                path.rmdir()
            elif path.exists():
                path.unlink()
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "MSFT", "JPM")))
        _write_json(
            self.paths["momentum"],
            _constant_projection("momentum_by_ticker", ("AAPL", "MSFT", "JPM"), "scored", score=50.0),
        )
        _write_json(
            self.paths["theme"],
            _constant_projection("theme_block_by_ticker", ("AAPL", "MSFT", "JPM"), "scored_theme_base", score=50.0),
        )
        preflight_runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["preflight"],
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )

    def tearDown(self):
        cleanup = [
            self.paths["candidate"],
            self.paths["momentum"],
            self.paths["theme"],
            self.paths["preflight"],
            self.paths["summary"],
            self.paths["output"],
            self.paths["components"],
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_candidate_subset.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_offering_audit_source.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_analyst_grade_actions.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_massive_news_events.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_corporate_action_capture.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_momentum_projection.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_theme_projection.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_source_packet.json"),
        ]
        for path in cleanup:
            path.unlink(missing_ok=True)
        root = SAMPLE_DIR / self.slug
        if root.exists():
            for item in sorted(root.rglob("*"), reverse=True):
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    item.rmdir()
            root.rmdir()
        preflight_root = PREFLIGHT_SAMPLE_DIR / self.slug
        if preflight_root.exists():
            for item in sorted(preflight_root.rglob("*"), reverse=True):
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    item.rmdir()
            preflight_root.rmdir()

    def _env(self):
        return mock.patch.dict(
            runner.sample_validation.os.environ,
            {
                "FMP_API_KEY": "UNIT_TEST_FMP_SECRET",
                "SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com",
                "MASSIVE_API_KEY": "UNIT_TEST_MASSIVE_SECRET",
            },
            clear=False,
        )

    def test_authorized_full_candidate_run_builds_packet_components_and_corporate_action_capture(self):
        client = FullCandidateFakeClient()

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=16,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=True,
                generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        self.assertEqual(len(client.urls), 16)
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 16)
        self.assertEqual(summary["endpoint_call_budget"]["max_total_http_attempts"], 16)
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_http_attempts"], 16)
        self.assertEqual(summary["endpoint_call_budget"]["retry_count_used"], 0)
        self.assertEqual(summary["endpoint_call_budget"]["massive_stock_split_calls"], 3)
        self.assertEqual(summary["endpoint_call_budget"]["massive_dividend_calls"], 3)
        self.assertTrue(summary["scope"]["provider_calls_performed"])
        self.assertTrue(summary["scope"]["source_packet_written"])
        self.assertTrue(summary["scope"]["data_context_written"])
        self.assertTrue(summary["scope"]["corporate_action_capture_written"])
        self.assertFalse(summary["scope"]["corporate_action_reconciliation_performed"])
        self.assertEqual(summary["candidate_universe"]["eligible_count"], 3)
        self.assertEqual(summary["source_packet"]["preflight_status"], "offline_preflight_passed")
        self.assertTrue(self.paths["output"].exists())
        self.assertTrue(self.paths["components"].exists())
        capture_path = ROOT / summary["source_artifacts"]["corporate_action_capture_path"]
        self.assertTrue(capture_path.exists())
        capture = json.loads(capture_path.read_text(encoding="utf-8"))
        self.assertEqual(capture["aggregate_counts"]["split_endpoint_call_count"], 3)
        self.assertEqual(capture["aggregate_counts"]["dividend_endpoint_call_count"], 3)
        self.assertFalse(capture["scope"]["corporate_action_reconciliation_performed"])

        text = self.paths["summary"].read_text(encoding="utf-8")
        self.assertNotIn("UNIT_TEST_FMP_SECRET", text)
        self.assertNotIn("UNIT_TEST_MASSIVE_SECRET", text)
        self.assertNotIn("UnitTest/0.1", text)
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn("financialmodelingprep.com", text.lower())
        self.assertNotIn("api.massive.com", text.lower())
        self.assertNotIn("data.sec.gov", text.lower())
        self.assertNotIn('"payload"', text)

    def test_stale_clock_source_projection_binding_is_rejected_before_fetch(self):
        # Reverse control (Required B, expensive-fetch boundary): the live re-derivation validates the
        # momentum source binding against the CANDIDATE clock before any provider call; a stale clock
        # aborts with zero fetches.
        momentum = _constant_projection("momentum_by_ticker", ("AAPL", "MSFT", "JPM"), "scored", score=50.0)
        momentum["source_binding"]["decision_clock"]["expected_decision_date"] = "20260614"
        _write_json(self.paths["momentum"], momentum)
        client = FullCandidateFakeClient()
        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            with self.assertRaisesRegex(runner.FullCandidateLiveSourcePacketError, "source binding"):
                runner.run_full_candidate_live_source_packet(
                    preflight_summary_path=self.paths["preflight"],
                    expected_total_call_budget=16,
                    output_data_context_path=self.paths["output"],
                    context_components_output_path=self.paths["components"],
                    source_artifact_prefix=self.paths["prefix"],
                    summary_path=self.paths["summary"],
                    raw_root=self.raw_root,
                    client=client,
                    confirm_user_authorization=True,
                    run_data_context=True,
                    generated_at="2026-07-06T12:00:00+00:00",
                    observed_at=_OFFERING_OBSERVED_AT,
                    sec_sleep_seconds=0,
                )
        self.assertEqual(client.urls, [])

    def test_live_packet_uses_preflight_pass2_targets_not_neutral_full_candidate_fill(self):
        momentum = _constant_projection(
            "momentum_by_ticker", ("AAPL", "MSFT", "JPM"), "scored", score=50.0
        )
        momentum["momentum_by_ticker"] = {"AAPL": 75.0, "MSFT": 70.0}
        momentum["neutral_fill_tickers"] = ["JPM"]
        momentum["coverage"]["JPM"] = "absent_from_pool"
        momentum["scored_count"] = 2
        _write_json(self.paths["momentum"], momentum)
        theme = _constant_projection(
            "theme_block_by_ticker", ("AAPL", "MSFT", "JPM"), "scored_theme_base", score=50.0
        )
        theme["theme_block_by_ticker"] = {"AAPL": 65.0}
        theme["neutral_fill_tickers"] = ["MSFT", "JPM"]
        theme["coverage"]["MSFT"] = "neutral_missing_theme_and_industry_base"
        theme["coverage"]["JPM"] = "neutral_missing_theme_and_industry_base"
        theme["scored_count"] = 1
        _write_json(self.paths["theme"], theme)
        preflight_runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["preflight"],
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )
        client = FullCandidateFakeClient()

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=11,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=True,
                generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        joined_urls = "\n".join(client.urls)
        self.assertEqual(len(client.urls), 11)
        self.assertNotIn("JPM", joined_urls)
        self.assertEqual(summary["pass2_target_universe"]["target_count"], 2)
        self.assertEqual(summary["pass2_target_universe"]["target_symbols"], ["AAPL", "MSFT"])
        self.assertEqual(summary["candidate_universe"]["eligible_count"], 2)
        self.assertEqual(summary["endpoint_call_budget"]["fmp_grades_calls"], 2)
        self.assertEqual(summary["endpoint_call_budget"]["massive_stock_split_calls"], 2)
        self.assertEqual(summary["endpoint_call_budget"]["massive_dividend_calls"], 2)

    def test_missing_authorization_aborts_before_network_or_writes(self):
        client = FullCandidateFakeClient()

        with self.assertRaisesRegex(runner.FullCandidateLiveSourcePacketError, "authorization"):
            runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=16,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=False,
                run_data_context=True,
                generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["summary"].exists())
        self.assertFalse(self.paths["output"].exists())

    def test_budget_mismatch_aborts_before_network(self):
        client = FullCandidateFakeClient()

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ), self.assertRaisesRegex(runner.FullCandidateLiveSourcePacketError, "call budget"):
            runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=15,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=True,
                generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["summary"].exists())

    def test_malformed_preflight_json_raises_typed_error_before_network(self):
        client = FullCandidateFakeClient()
        bad_preflight = self.paths["preflight"].with_name("bad_preflight.json")
        bad_preflight.write_text("{", encoding="utf-8")

        with self.assertRaisesRegex(runner.FullCandidateLiveSourcePacketError, "read JSON"):
            runner.run_full_candidate_live_source_packet(
                preflight_summary_path=bad_preflight,
                expected_total_call_budget=16,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=True,
                generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["summary"].exists())

    def test_invalid_calendar_decision_date_raises_typed_error_before_network(self):
        client = FullCandidateFakeClient()
        preflight = json.loads(self.paths["preflight"].read_text(encoding="utf-8"))
        preflight["decision_clock"]["expected_decision_date"] = "20261301"
        _write_json(self.paths["preflight"], preflight)

        with self.assertRaisesRegex(runner.FullCandidateLiveSourcePacketError, "real calendar date"):
            runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=16,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=True,
                generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["summary"].exists())

    def test_scope_creep_rejected_by_summary_schema(self):
        client = FullCandidateFakeClient()

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=16,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=False,
                generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        for path, value in (
            (("scope", "full_market_call_performed"), True),
            (("scope", "corporate_action_reconciliation_performed"), True),
            (("prohibited_claims", "ship_gate_evidence_claimed"), True),
            (("endpoint_call_budget", "max_total_endpoint_calls"), 15),
            (("endpoint_call_budget", "actual_total_http_attempts"), 17),
            (("source_packet", "preflight_status"), "not_run"),
        ):
            mutated = json.loads(json.dumps(summary))
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            with self.subTest(path=path):
                with self.assertRaises(runner.FullCandidateLiveSourcePacketError):
                    runner._validate_summary_against_schema(mutated)

    def test_forged_preflight_injecting_neutral_fill_target_is_rejected_before_fetch(self):
        # R-USSHORT-BATCH5-LIVE-RUNNER-TRUSTS-PREFLIGHT-FUNNEL-NOT-REDERIVED: the live runner must RE-DERIVE the
        # funnel target from the momentum projection (scored∩eligible ∪ forced-holdings), not trust the preflight.
        # Momentum scores only AAPL/MSFT; JPM is a neutral-fill eligible ticker. A forged preflight injecting JPM
        # into target_symbols must be rejected before any provider fetch or summary write.
        momentum = _constant_projection(
            "momentum_by_ticker", ("AAPL", "MSFT", "JPM"), "scored", score=50.0
        )
        momentum["momentum_by_ticker"] = {"AAPL": 50.0, "MSFT": 50.0}
        momentum["neutral_fill_tickers"] = ["JPM"]
        momentum["coverage"]["JPM"] = "neutral_fill"
        momentum["scored_count"] = 2
        _write_json(self.paths["momentum"], momentum)
        preflight_runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["preflight"],
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )
        preflight = json.loads(self.paths["preflight"].read_text(encoding="utf-8"))
        budget = preflight["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"]
        preflight["pass2_target_universe"]["target_symbols"] = ["AAPL", "JPM", "MSFT"]
        _write_json(self.paths["preflight"], preflight)

        client = FullCandidateFakeClient()
        with self.assertRaisesRegex(runner.FullCandidateLiveSourcePacketError, "funnel"):
            runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=budget,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=True,
                generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["summary"].exists())

    def test_forged_within_cap_preflight_is_rejected_when_target_exceeds_recomputed_cap(self):
        # The runner must RECOMPUTE within-cap from the re-derived target, not trust the preflight's const-true
        # attestation. With the cap lowered to 2, the canonical 3-target preflight (which self-attests within_cap)
        # must be rejected before any fetch — the small-scale analog of a forged 2404 / 12021-call re-expansion.
        client = FullCandidateFakeClient()
        with mock.patch.object(runner, "FMP_FREE_DAILY_GRADE_CALL_CAP", 2), self.assertRaisesRegex(
            runner.FullCandidateLiveSourcePacketError, "free daily grade-call cap"
        ):
            runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=16,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=True,
                generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["summary"].exists())

    def test_runner_narrows_to_preflight_top_k_and_never_fetches_below_top_k(self):
        # R-USSHORT-BATCH5-MOMENTUM-TOPK-NARROWING-MISSING: the runner reads momentum_top_k from the reviewed
        # preflight and re-derives the SAME top-K funnel via select_pass2_targets, so with 3 scored + top_k=2 it
        # fetches only the top-2 momentum tickers (11 calls) and never JPM (below the top-2).
        momentum = _constant_projection(
            "momentum_by_ticker", ("AAPL", "MSFT", "JPM"), "scored", score=50.0
        )
        momentum["momentum_by_ticker"] = {"AAPL": 90.0, "MSFT": 80.0, "JPM": 10.0}
        _write_json(self.paths["momentum"], momentum)
        preflight_runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["preflight"],
            momentum_top_k=2,
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )

        client = FullCandidateFakeClient()
        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=11,  # 1 SEC mapping + 2 targets * 5
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=False,
                generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        self.assertEqual(summary["pass2_target_universe"]["momentum_top_k"], 2)
        self.assertEqual(summary["pass2_target_universe"]["target_count"], 2)
        self.assertEqual(summary["pass2_target_universe"]["target_symbols"], ["AAPL", "MSFT"])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 11)
        fetched_symbols = {row["symbol"] for row in summary["endpoint_results"] if row["symbol"] is not None}
        self.assertEqual(fetched_symbols, {"AAPL", "MSFT"})
        self.assertNotIn("JPM", fetched_symbols)

    def test_runner_per_target_call_constants_match_preflight_forecast_formula(self):
        # Single-source guard: the runner's mirrored per-target / SEC-mapping call constants must equal the
        # preflight's canonical _forecast_calls, so the re-anchored spend budget can never silently drift from the
        # forecast the operator budget is checked against.
        for n in (1, 2, 3, 15, 200):
            expected = preflight_runner._forecast_calls(n, n)["total_calls_for_pass2_target_cut"]
            actual = runner._SEC_TICKER_MAPPING_CALLS + n * runner._PASS2_ENDPOINT_CALLS_PER_TARGET
            self.assertEqual(actual, expected, f"per-target call-count drift at n={n}")

    def test_forged_wider_top_k_with_honest_forecast_is_rejected_before_any_fetch(self):
        # R-USSHORT-BATCH5-MOMENTUM-TOPK-NARROWING-MISSING (circular-K seam): a forged preflight that widens
        # momentum_top_k + target_symbols to the full scored set but KEEPS the honest narrow forecast/budget (so an
        # operator passing the reviewed budget sails past _load_ready_preflight) must be rejected BEFORE any provider
        # call — the runner re-anchors the spend budget to the re-derived target count, not the attested forecast/K.
        momentum = _constant_projection(
            "momentum_by_ticker", ("AAPL", "MSFT", "JPM"), "scored", score=50.0
        )
        momentum["momentum_by_ticker"] = {"AAPL": 90.0, "MSFT": 80.0, "JPM": 10.0}
        _write_json(self.paths["momentum"], momentum)
        preflight_runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["preflight"],
            momentum_top_k=1,  # honest reviewed run: single richest target AAPL, forecast 6
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )
        forged = json.loads(self.paths["preflight"].read_text(encoding="utf-8"))
        self.assertEqual(forged["pass2_target_universe"]["target_symbols"], ["AAPL"])
        self.assertEqual(forged["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"], 6)
        forged["pass2_target_universe"]["momentum_top_k"] = 3
        forged["pass2_target_universe"]["target_count"] = 3
        forged["pass2_target_universe"]["target_symbols"] = ["AAPL", "JPM", "MSFT"]
        forged["pass2_target_universe"]["target_symbol_sample"] = ["AAPL", "JPM", "MSFT"]
        _write_json(self.paths["preflight"], forged)  # forecast LEFT at the honest 6

        client = FullCandidateFakeClient()
        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            with self.assertRaises(runner.FullCandidateLiveSourcePacketError) as ctx:
                runner.run_full_candidate_live_source_packet(
                    preflight_summary_path=self.paths["preflight"],
                    expected_total_call_budget=6,  # the HONEST reviewed budget
                    output_data_context_path=self.paths["output"],
                    context_components_output_path=self.paths["components"],
                    source_artifact_prefix=self.paths["prefix"],
                    summary_path=self.paths["summary"],
                    raw_root=self.raw_root,
                    client=client,
                    confirm_user_authorization=True,
                    run_data_context=False,
                    generated_at="2026-07-06T12:00:00+00:00",
                    observed_at=_OFFERING_OBSERVED_AT,
                    sec_sleep_seconds=0,
                )
        self.assertIn("re-derived Pass2 target count", str(ctx.exception))
        self.assertEqual(client.urls, [])  # zero provider calls spent
        self.assertFalse(self.paths["summary"].exists())


if __name__ == "__main__":
    unittest.main()
