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
from engine.us_short_overextension_producer import eligible_tickers_sha256  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _OFFERING_OBSERVED_AT,
    _candidate_artifact,
    _constant_projection,
)
from tests.provider.us_short_projection_binding_test_helpers import bound_projection  # noqa: E402
from tests.provider.us_short_private_test_root import (  # noqa: E402
    temporary_us_short_directory,
    temporary_us_short_state_directory,
)


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_DIR = ROOT / "provider_samples" / "us_short_batch5_full_candidate_live_source_packet_20260706"
PREFLIGHT_SAMPLE_DIR = ROOT / "provider_samples" / "us_short_batch5_full_candidate_pass2_preflight_20260706"


def _write_json(path: Path, payload) -> Path:
    binding = payload.get("source_binding") if type(payload) is dict else None
    if type(payload) is dict and (
        type(binding) is not dict or binding.get("producer_id") == "us_short_test_fixture"
    ):
        component = "momentum" if "momentum_by_ticker" in payload else "theme" if "theme_block_by_ticker" in payload else None
        candidate_path = path.with_name(path.stem.rsplit("_", 1)[0] + "_candidate.json")
        if component is not None and candidate_path.is_file():
            payload = bound_projection(candidate_path=candidate_path, component=component, projection=payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _full_overextension_projection() -> dict:
    """A full Pass1-eligible projection whose consumer must bind before top-K narrowing."""
    tickers = ("AAPL", "MSFT", "JPM")
    return {
        "schema_name": "us_short_full_universe_overextension_projection",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-15T08:30:00-04:00",
        "decision_clock": {
            "expected_decision_date": _DECISION_DATE,
            "candidate_price_basis_date": "20260612",
            "price_basis_date": "2026-06-12",
            "source_as_of": "2026-06-12",
        },
        "source_contract": {"session": "RTH", "adjustment_mode": "split_adjusted"},
        "candidate_binding": {
            "eligible_count": len(tickers),
            "eligible_tickers_sha256": eligible_tickers_sha256(tickers),
        },
        "overextension_by_ticker": {
            ticker: {
                "overextension_state": "none",
                "strips_theme_score": False,
                "execution_flags": {},
                "conditions_met": 0,
                "condition_names": [],
                "disposition": "scored",
                "pit": {
                    "as_of": "2026-06-12",
                    "session": "RTH",
                    "adjustment_mode": "split_adjusted",
                    "n_points": 70,
                },
            }
            for ticker in tickers
        },
        "disposition_counts": {"scored": len(tickers), "insufficient_data": 0},
        "scored_count": len(tickers),
        "target_count": len(tickers),
    }


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
    def _finalize_manual_approval(self, preflight_path: Path):
        from runners.us_short_weekly_capstone import Pass2BudgetApproval

        summary = json.loads(preflight_path.read_text(encoding="utf-8"))
        approval = Pass2BudgetApproval(
            decision_date=summary["decision_clock"]["expected_decision_date"],
            candidate_price_basis_date=summary["decision_clock"]["candidate_price_basis_date"],
            candidate_artifact_sha256=summary["candidate_universe"]["candidate_artifact_sha256"],
            momentum_top_k=summary["pass2_target_universe"]["momentum_top_k"],
            target_count=summary["pass2_target_universe"]["target_count"],
            exact_pass2_calls=summary["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"],
            authorization_mode="manual",
            authorization_ref="manual:test_fixture",
            generated_at=summary["generated_at"],
        )
        preflight_runner.finalize_preflight_from_existing_derivation(
            preflight_summary_path=preflight_path,
            approval_binding=approval.binding_summary(),
        )
        return approval

    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_root = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._sample_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_full_candidate_live_source_packet_20260706"
        )
        self.sample_root = Path(self._sample_root_context.__enter__())
        self.addCleanup(self._sample_root_context.__exit__, None, None, None)
        self._preflight_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_full_candidate_pass2_preflight_20260706"
        )
        self.preflight_root = Path(self._preflight_root_context.__enter__())
        self.addCleanup(self._preflight_root_context.__exit__, None, None, None)
        self.slug = f"fc_live_{os.getpid()}_{abs(hash(self._testMethodName)) % 100000}"
        self.raw_root = self.sample_root / "full_candidate_live_source_packet_20260706" / self.slug / "raw"
        self.paths = {
            "candidate": self.state_root / f"{self.slug}_candidate.json",
            "momentum": self.state_root / f"{self.slug}_momentum.json",
            "theme": self.state_root / f"{self.slug}_theme.json",
            "preflight": self.preflight_root / self.slug / "preflight.json",
            "summary": self.sample_root / "full_candidate_live_source_packet_20260706" / self.slug / "summary.json",
            "prefix": self.state_root / self.slug,
            "output": self.state_root / f"{self.slug}_data_context.json",
            "components": self.state_root / f"{self.slug}_context_components.json",
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
            authorized_total_call_budget=16,
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )
        self.fixture_approval = self._finalize_manual_approval(self.paths["preflight"])
        original_live_run = runner.run_full_candidate_live_source_packet

        def run_with_fixture_approval(*args, **kwargs):
            if kwargs.get("budget_approval") is None:
                preflight_path = kwargs["preflight_summary_path"]
                if preflight_path != self.paths["preflight"] or self._testMethodName == (
                    "test_invalid_calendar_decision_date_raises_typed_error_before_network"
                ):
                    kwargs["budget_approval"] = self.fixture_approval
                else:
                    try:
                        kwargs["budget_approval"] = self._finalize_manual_approval(preflight_path)
                    except preflight_runner.FullCandidatePass2PreflightError:
                        # Some hostile fixtures deliberately violate a preflight
                        # readiness invariant to exercise a later independent
                        # pre-network guard. Bind their explicit test approval
                        # without claiming that the production finalizer accepts
                        # that invalid derivation.
                        summary = json.loads(preflight_path.read_text(encoding="utf-8"))
                        from runners.us_short_weekly_capstone import Pass2BudgetApproval

                        approval = Pass2BudgetApproval(
                            decision_date=summary["decision_clock"]["expected_decision_date"],
                            candidate_price_basis_date=summary["decision_clock"]["candidate_price_basis_date"],
                            candidate_artifact_sha256=summary["candidate_universe"]["candidate_artifact_sha256"],
                            momentum_top_k=summary["pass2_target_universe"]["momentum_top_k"],
                            target_count=summary["pass2_target_universe"]["target_count"],
                            exact_pass2_calls=summary["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"],
                            authorization_mode="manual",
                            authorization_ref="manual:test_fixture_hostile",
                            generated_at=summary["generated_at"],
                        )
                        summary["execution_gate"]["approval_binding"] = approval.binding_summary()
                        _write_json(preflight_path, summary)
                        kwargs["budget_approval"] = approval
            return original_live_run(*args, **kwargs)

        runner.run_full_candidate_live_source_packet = run_with_fixture_approval
        self.addCleanup(
            setattr, runner, "run_full_candidate_live_source_packet", original_live_run
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
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_full_overextension.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_candidate_subset.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_offering_audit_source.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_analyst_grade_actions.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_massive_news_events.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_corporate_action_capture.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_momentum_projection.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_theme_projection.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_theme_selection_contract.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_source_packet.json"),
        ]
        for path in cleanup:
            path.unlink(missing_ok=True)

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
        contract_path = self.paths["prefix"].with_name(
            self.paths["prefix"].name + "_theme_selection_contract.json"
        )
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        self.assertEqual(contract["as_of"], _DECISION_DATE)
        self.assertEqual(set(contract["per_ticker"]), {"AAPL", "MSFT", "JPM"})
        self.assertEqual(
            {row["theme_id"] for row in contract["per_ticker"].values()},
            {"industry:unclassified:aapl", "industry:unclassified:msft", "industry:unclassified:jpm"},
        )
        self.assertEqual(contract["hot_excluded_audit"]["heat_threshold"], 80.0)
        self.assertEqual(set(contract["hot_excluded_audit"]["per_ticker"]), {"AAPL", "MSFT", "JPM"})
        written_context = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        self.assertEqual(
            written_context["selection_inputs"]["theme_selection_contract"]["hot_excluded_audit"],
            contract["hot_excluded_audit"],
        )

        text = self.paths["summary"].read_text(encoding="utf-8")
        self.assertNotIn("UNIT_TEST_FMP_SECRET", text)
        self.assertNotIn("UNIT_TEST_MASSIVE_SECRET", text)
        self.assertNotIn("UnitTest/0.1", text)
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn("financialmodelingprep.com", text.lower())
        self.assertNotIn("api.massive.com", text.lower())
        self.assertNotIn("data.sec.gov", text.lower())
        self.assertNotIn('"payload"', text)

    def test_full_overextension_binds_eligible_universe_before_top_k_subset_assembly(self):
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
            authorized_total_call_budget=11,
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )
        overextension_path = self.paths["prefix"].with_name(
            self.paths["prefix"].name + "_full_overextension.json"
        )
        _write_json(overextension_path, _full_overextension_projection())

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=11,
                authorized_momentum_top_k=2,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                overextension_projection_path=overextension_path,
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=FullCandidateFakeClient(),
                confirm_user_authorization=True,
                run_data_context=True,
                generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        self.assertEqual(summary["candidate_universe"]["eligible_count"], 2)
        self.assertEqual(summary["pass2_target_universe"]["target_count"], 2)
        source_packet_path = self.paths["prefix"].with_name(
            self.paths["prefix"].name + "_source_packet.json"
        )
        packet = json.loads(source_packet_path.read_text(encoding="utf-8"))
        self.assertEqual(packet["schema_version"], "1.3.0")
        self.assertEqual(packet["paths"]["candidate_artifact_path"], str(
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_candidate_subset.json").relative_to(ROOT)
        ).replace("\\", "/"))
        self.assertEqual(packet["paths"]["overextension_candidate_artifact_path"], str(
            self.paths["candidate"].relative_to(ROOT)
        ).replace("\\", "/"))
        full_candidate = json.loads(self.paths["candidate"].read_text(encoding="utf-8"))
        self.assertEqual(full_candidate["eligible_tickers"], ["AAPL", "MSFT", "JPM"])
        context = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        self.assertEqual({row["ticker"] for row in context["universe"]}, {"AAPL", "MSFT"})

    def test_invalid_full_overextension_aborts_before_top_k_subset_or_provider_fetch(self):
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
            authorized_total_call_budget=11,
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )
        overextension_path = self.paths["prefix"].with_name(
            self.paths["prefix"].name + "_full_overextension.json"
        )
        projection = _full_overextension_projection()
        projection["candidate_binding"]["eligible_tickers_sha256"] = "0" * 64
        _write_json(overextension_path, projection)
        client = FullCandidateFakeClient()

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ), self.assertRaisesRegex(runner.FullCandidateLiveSourcePacketError, "overextension source"):
            runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=11,
                authorized_momentum_top_k=2,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                overextension_projection_path=overextension_path,
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
        for key in ("summary", "output", "components"):
            self.assertFalse(self.paths[key].exists())
        for suffix in ("_candidate_subset.json", "_source_packet.json"):
            self.assertFalse(self.paths["prefix"].with_name(self.paths["prefix"].name + suffix).exists())

    def test_sector_classification_packet_yields_real_industry_theme_ids(self):
        # The capstone passes the run's own SIC packet directly (the projection-inputs theme binding drops that
        # role), so same-real-industry names share an `industry:<sector>` theme_id instead of per-ticker
        # singletons — this is what lets the §4.5 same-theme seat cap group by real industry.
        classification_path = self.paths["prefix"].with_name(
            self.paths["prefix"].name + "_classification.json")
        _write_json(classification_path, {"sector_by_ticker": {
            "AAPL": "Technology", "MSFT": "Technology", "JPM": "Financials"}})
        self.addCleanup(lambda: classification_path.unlink(missing_ok=True))
        client = FullCandidateFakeClient()

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=16,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"],
                sector_classification_packet_path=classification_path,
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=True,
                generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        contract_path = self.paths["prefix"].with_name(
            self.paths["prefix"].name + "_theme_selection_contract.json")
        per = json.loads(contract_path.read_text(encoding="utf-8"))["per_ticker"]
        self.assertEqual(set(per), {"AAPL", "MSFT", "JPM"})
        self.assertEqual(per["AAPL"]["theme_id"], "industry:technology")
        self.assertEqual(per["MSFT"]["theme_id"], "industry:technology")   # same real industry -> shared id
        self.assertEqual(per["JPM"]["theme_id"], "industry:financials")

    def test_stale_clock_source_projection_binding_is_rejected_before_fetch(self):
        # Reverse control (Required B, expensive-fetch boundary): the live re-derivation validates the
        # momentum source binding against the CANDIDATE clock before any provider call; a stale clock
        # aborts with zero fetches.
        momentum = _constant_projection(
            "momentum_by_ticker", ("AAPL", "MSFT", "JPM"), "scored", score=50.0,
            candidate_path=self.paths["candidate"], component="momentum",
        )
        momentum["source_binding"]["decision_clock"]["expected_decision_date"] = "20260614"
        _write_json(self.paths["momentum"], momentum)
        client = FullCandidateFakeClient()
        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            with self.assertRaisesRegex(runner.FullCandidateLiveSourcePacketError, "changed after reviewed preflight"):
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
            authorized_total_call_budget=11,
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
        contract_path = self.paths["prefix"].with_name(
            self.paths["prefix"].name + "_theme_selection_contract.json"
        )
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        self.assertEqual(set(contract["per_ticker"]), {"AAPL", "MSFT"})
        self.assertNotIn("JPM", contract["per_ticker"])

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

    def test_enabled_k4b_missing_current_stage_result_aborts_before_network(self):
        client = FullCandidateFakeClient()
        with self.assertRaisesRegex(
            runner.FullCandidateLiveSourcePacketError, "this run's stage result"
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
                theme_soft_boost_enabled=True,
            )
        self.assertEqual(client.urls, [])

    def test_stale_operator_theme_selection_contract_is_ignored_and_rebuilt_from_live_pass2_sources(self):
        contract_path = self.paths["prefix"].with_name(self.paths["prefix"].name + "_theme_selection_contract.json")
        _write_json(contract_path, {"stale_operator_input": True})
        client = FullCandidateFakeClient()
        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"], expected_total_call_budget=16,
                output_data_context_path=self.paths["output"], context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"], summary_path=self.paths["summary"], raw_root=self.raw_root,
                client=client, confirm_user_authorization=True, run_data_context=True,
                generated_at="2026-07-06T12:00:00+00:00", observed_at=_OFFERING_OBSERVED_AT, sec_sleep_seconds=0,
            )
        self.assertEqual(len(client.urls), 16)
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        self.assertEqual(set(contract["per_ticker"]), {"AAPL", "MSFT", "JPM"})
        self.assertNotIn("stale_operator_input", contract)

    def test_caller_selected_strong_theme_state_is_rejected_before_authorization_or_network(self):
        client = FullCandidateFakeClient()

        with self.assertRaisesRegex(runner.FullCandidateLiveSourcePacketError, "must remain no_strong_theme"):
            runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=16,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                theme_opportunity_state="strong",
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
            "momentum_by_ticker", ("AAPL", "MSFT", "JPM"), "scored", score=50.0,
            candidate_path=self.paths["candidate"], component="momentum",
        )
        momentum["momentum_by_ticker"] = {"AAPL": 50.0, "MSFT": 50.0}
        momentum["neutral_fill_tickers"] = ["JPM"]
        momentum["coverage"]["JPM"] = "absent_from_pool"
        momentum["scored_count"] = 2
        momentum = bound_projection(
            candidate_path=self.paths["candidate"], component="momentum", projection=momentum,
        )
        _write_json(self.paths["momentum"], momentum)
        theme = _constant_projection(
            "theme_block_by_ticker", ("AAPL", "MSFT", "JPM"), "scored_theme_base", score=50.0,
            candidate_path=self.paths["candidate"], component="theme",
        )
        theme["theme_block_by_ticker"] = {"AAPL": 50.0, "MSFT": 50.0}
        theme["neutral_fill_tickers"] = ["JPM"]
        theme["coverage"]["JPM"] = "neutral_missing_theme_and_industry_base"
        theme["scored_count"] = 2
        theme = bound_projection(
            candidate_path=self.paths["candidate"], component="theme", projection=theme,
        )
        _write_json(self.paths["theme"], theme)
        preflight_runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["preflight"],
            authorized_total_call_budget=11,
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
            authorized_total_call_budget=11,
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
                authorized_momentum_top_k=2,
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

    def test_holding_outside_pass1_is_fetched_and_forwarded_as_mandatory_holding_lane(self):
        preflight_runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"], expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"], theme_projection_path=self.paths["theme"],
            summary_path=self.paths["preflight"], forced_holding_tickers=["HOLD"],
            authorized_total_call_budget=21, confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )
        client = FullCandidateFakeClient()
        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"], expected_total_call_budget=21,
                forced_holding_tickers=["HOLD"], output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"], source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"], raw_root=self.raw_root, client=client,
                confirm_user_authorization=True, run_data_context=True,
                generated_at="2026-07-06T12:00:00+00:00", observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )
        self.assertIn("HOLD", summary["pass2_target_universe"]["target_symbols"])
        source_packet = json.loads(
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_source_packet.json").read_text(encoding="utf-8")
        )
        self.assertEqual(source_packet["optional_inputs"]["holdings"], [{"ticker": "HOLD", "signals": {"critical_data_missing": True}}])
        self.assertTrue(any("HOLD" in url for url in client.urls))

    def test_projection_artifact_changed_after_preflight_is_rejected_before_fetch(self):
        envelope = json.loads(self.paths["momentum"].read_text(encoding="utf-8"))
        envelope["generated_at"] = "2026-06-15T12:01:00+00:00"
        self.paths["momentum"].write_text(json.dumps(envelope), encoding="utf-8")
        client = FullCandidateFakeClient()
        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ), self.assertRaisesRegex(runner.FullCandidateLiveSourcePacketError, "changed after reviewed preflight"):
            runner.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"], expected_total_call_budget=16,
                output_data_context_path=self.paths["output"], context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"], summary_path=self.paths["summary"], raw_root=self.raw_root,
                client=client, confirm_user_authorization=True, generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT, sec_sleep_seconds=0,
            )
        self.assertEqual(client.urls, [])

    def test_overlapping_holding_and_recall_lane_cannot_be_dropped_from_union_target(self):
        preflight_runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"], expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"], theme_projection_path=self.paths["theme"],
            summary_path=self.paths["preflight"], forced_holding_tickers=["AAPL"],
            catalyst_recall_tickers=["MSFT"], authorized_total_call_budget=16,
            confirm_user_authorization=True, generated_at="2026-07-06T12:00:00+00:00",
        )
        for holdings, recall, message in (
            ([], ["MSFT"], "holding lane changed"),
            (["AAPL"], [], "recall lane changed"),
        ):
            client = FullCandidateFakeClient()
            with self._env(), mock.patch.object(
                runner.sample_validation, "_read_windows_environment_value", return_value=None
            ), self.assertRaisesRegex(runner.FullCandidateLiveSourcePacketError, message):
                runner.run_full_candidate_live_source_packet(
                    preflight_summary_path=self.paths["preflight"], expected_total_call_budget=16,
                    forced_holding_tickers=holdings, catalyst_recall_tickers=recall,
                    output_data_context_path=self.paths["output"], context_components_output_path=self.paths["components"],
                    source_artifact_prefix=self.paths["prefix"], summary_path=self.paths["summary"], raw_root=self.raw_root,
                    client=client, confirm_user_authorization=True, generated_at="2026-07-06T12:00:00+00:00",
                    observed_at=_OFFERING_OBSERVED_AT, sec_sleep_seconds=0,
                )
            self.assertEqual(client.urls, [])

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
            authorized_total_call_budget=6,
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
        self.assertIn("independently authorized K", str(ctx.exception))
        self.assertEqual(client.urls, [])  # zero provider calls spent
        self.assertFalse(self.paths["summary"].exists())


if __name__ == "__main__":
    unittest.main()
