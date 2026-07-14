from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_short_batch5_live_source_packet as runner  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _OFFERING_OBSERVED_AT,
    _candidate_artifact,
    _constant_projection,
)


STATE_DIR = ROOT / "state" / "us_short"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


class FakePass2Client:
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


class ScalarPayloadPass2Client(FakePass2Client):
    def get_json(self, url, headers=None, timeout_seconds=30):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.netloc == "www.sec.gov" and parsed.path.endswith("/company_tickers.json"):
            return super().get_json(url, headers=headers, timeout_seconds=timeout_seconds)
        if parsed.netloc == "financialmodelingprep.com" and parsed.path.endswith("/grades"):
            symbol = query["symbol"][0]
            return (True if symbol == "AAPL" else 4.5, 200, True, None)
        if parsed.netloc == "data.sec.gov" and parsed.path.startswith("/submissions/"):
            return (123, 200, True, None)
        if parsed.netloc == "api.massive.com" and parsed.path == "/v2/reference/news":
            return ("unexpected scalar news payload", 200, True, None)
        raise AssertionError(f"unexpected URL: {url}")


class UsShortBatch5LiveSourcePacketTest(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_live_packet_{os.getpid()}_{self._testMethodName[:24]}"
        self.raw_root = (
            ROOT / "provider_samples" / "us_short_batch5_live_source_packet_20260704" / self.slug / "raw"
        )
        self.paths = {
            "candidate": STATE_DIR / f"{self.slug}_candidate_input.json",
            "momentum": STATE_DIR / f"{self.slug}_momentum.json",
            "theme": STATE_DIR / f"{self.slug}_theme.json",
            "summary": ROOT / "provider_samples" / "us_short_batch5_live_source_packet_20260704" / self.slug / "summary.json",
            "prefix": STATE_DIR / self.slug,
            "output": STATE_DIR / f"{self.slug}_data_context.json",
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
            _constant_projection(
                "momentum_by_ticker", ("AAPL", "MSFT"), "scored", score=50.0,
                candidate_path=self.paths["candidate"], component="momentum",
            ),
        )
        _write_json(
            self.paths["theme"],
            _constant_projection(
                "theme_block_by_ticker", ("AAPL", "MSFT"), "scored_theme_base", score=50.0,
                candidate_path=self.paths["candidate"], component="theme",
            ),
        )
        _write_json(
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_theme_selection_contract.json"),
            {
                "as_of": _DECISION_DATE,
                "mode": "industry_heat_v1_cross_industry_disabled",
                "cross_industry_provisional_enabled": False,
                "theme_opportunity_state": "no_strong_theme",
                "per_ticker": {
                    ticker: {
                        "theme_id": f"industry:{ticker.lower()}", "theme_source": "industry_heat_v1",
                        "theme_lifecycle_state": "confirmed_active", "theme_leader_rs": 0.0,
                        "membership_origin": "automatic_discovery", "market_confirmed": True,
                        "individual_theme_gate_passed": True, "overextension_state": "none",
                    }
                    for ticker in ("AAPL", "MSFT")
                },
            },
        )

    def tearDown(self):
        cleanup = [
            self.paths["candidate"],
            self.paths["momentum"],
            self.paths["theme"],
            self.paths["output"],
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_candidate_subset.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_offering_audit_source.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_analyst_grade_actions.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_massive_news_events.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_theme_selection_contract.json"),
            self.paths["prefix"].with_name(self.paths["prefix"].name + "_source_packet.json"),
            self.paths["summary"],
        ]
        for path in cleanup:
            path.unlink(missing_ok=True)
        root = ROOT / "provider_samples" / "us_short_batch5_live_source_packet_20260704" / self.slug
        if root.exists():
            for item in sorted(root.rglob("*"), reverse=True):
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    item.rmdir()
            root.rmdir()

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

    def test_authorized_probe_builds_source_packet_and_runs_existing_data_context_runner(self):
        client = FakePass2Client()

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = runner.run_live_source_packet(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL", "MSFT"],
                momentum_projection_path=self.paths["momentum"],
                theme_projection_path=self.paths["theme"],
                output_data_context_path=self.paths["output"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=True,
                generated_at="2026-06-15T08:00:00-04:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        self.assertEqual(len(client.urls), 7)
        self.assertTrue(summary["endpoint_call_budget"]["within_budget"])
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 7)
        self.assertTrue(summary["scope"]["provider_calls_performed"])
        self.assertTrue(summary["scope"]["source_packet_written"])
        self.assertTrue(summary["scope"]["data_context_written"])
        self.assertEqual(summary["source_packet"]["preflight_status"], "offline_preflight_passed")
        self.assertTrue(self.paths["output"].exists())
        written = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        self.assertEqual(set(written["selection_inputs"]["per_ticker"]), {"AAPL", "MSFT"})
        self.assertAlmostEqual(written["selection_inputs"]["per_ticker"]["AAPL"]["core_score"], 43.5)
        self.assertAlmostEqual(written["selection_inputs"]["per_ticker"]["MSFT"]["core_score"], 50.0)
        self.assertEqual(len(list(self.raw_root.rglob("*.json"))), 7)

        packet_path = ROOT / summary["source_packet"]["path"]
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        self.assertEqual(packet["schema_name"], "us_short_batch5_data_context_source_packet")
        self.assertEqual(packet["schema_version"], "1.3.0")
        self.assertEqual(packet["paths"]["candidate_artifact_path"], summary["source_artifacts"]["candidate_subset_path"])

        text = self.paths["summary"].read_text(encoding="utf-8")
        self.assertNotIn("UNIT_TEST_FMP_SECRET", text)
        self.assertNotIn("UNIT_TEST_MASSIVE_SECRET", text)
        self.assertNotIn("UnitTest/0.1", text)
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn("financialmodelingprep.com", text.lower())
        self.assertNotIn("api.massive.com", text.lower())
        self.assertNotIn("data.sec.gov", text.lower())
        self.assertNotIn('"payload"', text)

    def test_scalar_payloads_are_recorded_in_summary_without_schema_drift(self):
        client = ScalarPayloadPass2Client()

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            summary = runner.run_live_source_packet(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL", "MSFT"],
                momentum_projection_path=self.paths["momentum"],
                theme_projection_path=self.paths["theme"],
                output_data_context_path=self.paths["output"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=False,
                generated_at="2026-06-15T08:00:00-04:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        self.assertTrue(self.paths["summary"].exists())
        self.assertFalse(self.paths["output"].exists())
        scalar_shapes = [
            endpoint["payload_shape"]
            for endpoint in summary["endpoint_results"]
            if endpoint["endpoint_family"] != "company_tickers_mapping"
        ]
        self.assertEqual({shape["kind"] for shape in scalar_shapes}, {"scalar"})
        self.assertEqual({shape["row_count"] for shape in scalar_shapes}, {None})
        text = self.paths["summary"].read_text(encoding="utf-8")
        self.assertNotIn("unexpected scalar news payload", text)
        self.assertNotIn("UNIT_TEST_FMP_SECRET", text)
        self.assertNotIn("apikey=", text.lower())
        self.assertNotIn('"payload"', text)

    def test_payload_shape_kinds_are_subset_of_summary_schema_enum(self):
        schema = json.loads(runner.SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))
        kind_enum = set(
            schema["properties"]["endpoint_results"]["items"]["properties"]["payload_shape"]["properties"]["kind"][
                "enum"
            ]
        )
        payloads = [
            [],
            {"results": []},
            {"filings": {"recent": {"form": ["10-Q"]}}},
            {"other": "object"},
            None,
            True,
            123,
            4.5,
            "x",
        ]
        kinds = {
            runner._payload_shape(
                runner.sample_validation.FetchRecord(
                    provider_id="massive",
                    endpoint_family="reference_news",
                    symbol="AAPL",
                    raw_sample_ref="provider_samples/us_short_batch5_live_source_packet_20260704/unit/raw.json",
                    ok=True,
                    http_status=200,
                    error_type=None,
                    payload=payload,
                )
            )["kind"]
            for payload in payloads
        }

        self.assertLessEqual(kinds, kind_enum)

    def test_missing_authorization_aborts_before_network_or_writes(self):
        client = FakePass2Client()

        with self.assertRaisesRegex(runner.LiveSourcePacketError, "authorization"):
            runner.run_live_source_packet(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL"],
                momentum_projection_path=self.paths["momentum"],
                theme_projection_path=self.paths["theme"],
                output_data_context_path=self.paths["output"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=False,
                run_data_context=True,
                generated_at="2026-06-15T08:00:00-04:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["summary"].exists())
        self.assertFalse(self.paths["output"].exists())

    def test_caller_selected_strong_theme_state_is_rejected_before_authorization_or_network(self):
        client = FakePass2Client()

        with self.assertRaisesRegex(runner.LiveSourcePacketError, "must remain no_strong_theme"):
            runner.run_live_source_packet(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL", "MSFT"],
                momentum_projection_path=self.paths["momentum"],
                theme_projection_path=self.paths["theme"],
                output_data_context_path=self.paths["output"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                theme_opportunity_state="strong",
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["summary"].exists())
        self.assertFalse(self.paths["output"].exists())

    def test_missing_score_projection_rejected_before_network(self):
        client = FakePass2Client()

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ), self.assertRaises(runner.LiveSourcePacketError):
            runner.run_live_source_packet(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL"],
                momentum_projection_path=STATE_DIR / f"{self.slug}_missing_momentum.json",
                theme_projection_path=self.paths["theme"],
                output_data_context_path=self.paths["output"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=True,
                generated_at="2026-06-15T08:00:00-04:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["summary"].exists())

    def test_raw_root_must_stay_under_authorized_provider_samples_folder(self):
        outside_raw = ROOT / "provider_samples" / "other_live_source_packet" / self.slug / "raw"

        with self._env(), mock.patch.object(
            runner.sample_validation, "_read_windows_environment_value", return_value=None
        ), self.assertRaises(runner.LiveSourcePacketError):
            runner.run_live_source_packet(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                selected_symbols=["AAPL"],
                momentum_projection_path=self.paths["momentum"],
                theme_projection_path=self.paths["theme"],
                output_data_context_path=self.paths["output"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=outside_raw,
                client=FakePass2Client(),
                confirm_user_authorization=True,
                run_data_context=True,
                generated_at="2026-06-15T08:00:00-04:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )


if __name__ == "__main__":
    unittest.main()
