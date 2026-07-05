from __future__ import annotations

import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jsonschema import Draft7Validator  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _GENERATED_AT,
    _PRICE_BASIS_DATE,
    _USED_DATE,
    _gov,
)


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_ROOT = ROOT / "provider_samples" / "us_short_batch5_bankruptcy_8k_candidate_scan_20260705"
MODULE = "runners.us_short_batch5_bankruptcy_8k_candidate_scan"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sec_submissions(*, form="8-K", filing_date="2026-06-10", accession="0000000000-26-000001", items="9.01"):
    return {
        "filings": {
            "recent": {
                "form": [form],
                "filingDate": [filing_date],
                "accessionNumber": [accession],
                "items": [items],
            }
        }
    }


def _candidate_artifact_many(symbols: tuple[str, ...]):
    sec_tickers = {}
    sec_shares = {}
    market_data = {}
    for idx, symbol in enumerate(symbols):
        cik = 100000 + idx
        sec_tickers[symbol] = {"cik": cik, "exchange": "NASDAQ" if idx % 2 else "NYSE"}
        sec_shares[cik] = {"shares": 1_000_000_000 + idx, "end": "2026-03-31"}
        market_data[symbol] = {
            "close": 50.0 + idx,
            "volume": 1_000_000 + idx,
            "adv_usd": 60_000_000.0 + idx,
            "adv_days_observed": 20,
            "price_as_of": _USED_DATE,
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


class FakeSecClient:
    def __init__(self, symbols: tuple[str, ...], *, error_symbol: str | None = None):
        self.symbols = symbols
        self.error_symbol = error_symbol
        self.urls: list[str] = []
        self.cik_by_symbol = {symbol: 100000 + idx for idx, symbol in enumerate(symbols)}
        self.symbol_by_cik = {cik: symbol for symbol, cik in self.cik_by_symbol.items()}

    def get_json(self, url: str, *, headers=None, timeout_seconds=30):
        del headers, timeout_seconds
        self.urls.append(url)
        if url.endswith("/files/company_tickers_exchange.json"):
            return (
                {
                    "fields": ["ticker", "exchange", "cik"],
                    "data": [
                        [symbol, "Nasdaq" if idx % 2 else "NYSE", self.cik_by_symbol[symbol]]
                        for idx, symbol in enumerate(self.symbols)
                    ],
                },
                200,
                True,
                None,
            )
        match = re.search(r"CIK([0-9]{10})\.json$", url)
        if not match:
            return {"unexpected": url}, 404, False, "unexpected_url"
        cik = int(match.group(1))
        symbol = self.symbol_by_cik[cik]
        if symbol == self.error_symbol:
            return {"error": "unit test"}, 503, False, "http_error"
        item = "1.03,9.01" if symbol == "AAB" else "9.01"
        return (
            _sec_submissions(accession=f"{cik:010d}-26-000001", items=item),
            200,
            True,
            None,
        )


class Bankruptcy8kCandidateScanTest(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_b8kshard_{os.getpid()}_{self._testMethodName[:22]}"
        self.symbols = ("AAA", "AAB", "AAC", "AAD", "AAE", "AAF", "AAG")
        self.paths = {
            "candidate": STATE_DIR / f"{self.slug}_candidate.json",
            "source_packet": STATE_DIR / f"{self.slug}_packet.json",
            "screen": STATE_DIR / f"{self.slug}_screen.json",
            "producer_summary": ROOT / "docs" / f"{self.slug}_summary.json",
            "consumer_summary": ROOT / "docs" / f"{self.slug}_consumer_summary.json",
        }
        self.raw_root = SAMPLE_ROOT / self.slug / "raw"
        for path in self.paths.values():
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".tmp").unlink(missing_ok=True)
        _write_json(self.paths["candidate"], _candidate_artifact_many(self.symbols))

    def tearDown(self):
        for path in self.paths.values():
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".tmp").unlink(missing_ok=True)
        root = SAMPLE_ROOT / self.slug
        if root.exists():
            for item in sorted(root.rglob("*"), reverse=True):
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    item.rmdir()
            root.rmdir()

    def _env(self, producer):
        return mock.patch.dict(
            producer.sample_validation.os.environ,
            {"SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com"},
            clear=False,
        )

    def _run_happy(self, *, client=None, shard_start=0, shard_size=5, exclude_symbols=None):
        import importlib

        producer = importlib.import_module(MODULE)
        client = client or FakeSecClient(self.symbols)
        with self._env(producer), mock.patch.object(
            producer.sample_validation, "_read_windows_environment_value", return_value=None
        ), mock.patch.object(producer.time, "sleep"):
            summary = producer.run_candidate_shard_scan(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                shard_start=shard_start,
                shard_size=shard_size,
                exclude_symbols=exclude_symbols or [],
                output_source_packet_path=self.paths["source_packet"],
                output_screen_path=self.paths["screen"],
                summary_path=self.paths["producer_summary"],
                consumer_summary_path=self.paths["consumer_summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                generated_at="2026-07-05T12:00:00+00:00",
                observed_at="2026-06-15T12:00:00+00:00",
                sec_sleep_seconds=0,
            )
        return summary, client

    def test_authorized_candidate_shard_scan_fetches_more_than_three_and_writes_screen(self):
        summary, client = self._run_happy(exclude_symbols=["AAA"], shard_size=5)

        self.assertEqual(summary["candidate_scope"]["symbols"], ["AAB", "AAC", "AAD", "AAE", "AAF"])
        self.assertEqual(len(client.urls), 6)  # SEC ticker map + 5 company-submissions calls
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 6)
        self.assertEqual(summary["candidate_scope"]["shard_size"], 5)
        self.assertEqual(summary["candidate_scope"]["excluded_symbols"], ["AAA"])
        self.assertTrue(summary["scope"]["provider_calls_performed"])
        self.assertFalse(summary["scope"]["full_market_scan_performed"])
        self.assertFalse(summary["scope"]["full_candidate_universe_scan_completed"])
        self.assertFalse(summary["scope"]["run_fetch_invoked"])
        self.assertFalse(summary["scope"]["status_records_written"])
        self.assertFalse(summary["scope"]["candidate_artifact_written"])
        self.assertFalse(summary["scope"]["datahub_consumption_performed"])
        self.assertFalse(summary["scope"]["ship_gate_or_live_normalized_evidence_claimed"])

        packet = _read_json(self.paths["source_packet"])
        self.assertEqual(set(packet["sec_submissions_by_ticker"]), {"AAB", "AAC", "AAD", "AAE", "AAF"})
        screen = _read_json(self.paths["screen"])
        self.assertEqual(screen["by_ticker"]["AAB"]["screen_status"], "bankrupt_8k_found")
        self.assertEqual(summary["consumer_screen"]["bankruptcy_8k_positive_count"], 1)
        self.assertEqual(len(list(self.raw_root.rglob("*.json"))), 6)

        text = self.paths["producer_summary"].read_text(encoding="utf-8")
        self.assertNotIn("UnitTest/0.1 contact:test@example.com", text)
        self.assertNotIn("https://", text.lower())
        self.assertNotIn("data.sec.gov", text.lower())
        self.assertNotIn("www.sec.gov", text.lower())
        self.assertNotIn('"filings"', text)
        self.assertNotIn('"accessionNumber"', text)

    def test_preflight_reports_shard_budget_and_writes_nothing(self):
        import importlib

        producer = importlib.import_module(MODULE)
        result = producer.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            shard_start=0,
            shard_size=4,
            exclude_symbols=["AAA"],
            output_source_packet_path=self.paths["source_packet"],
            output_screen_path=self.paths["screen"],
            summary_path=self.paths["producer_summary"],
            consumer_summary_path=self.paths["consumer_summary"],
            raw_root=self.raw_root,
            generated_at="2026-07-05T12:00:00+00:00",
        )

        self.assertEqual(result["candidate_scope"]["symbols"], ["AAB", "AAC", "AAD", "AAE"])
        self.assertEqual(result["endpoint_call_budget"]["planned_total_endpoint_calls"], 5)
        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["producer_summary"].exists())
        self.assertFalse(self.paths["screen"].exists())

    def test_requires_authorization_before_fetch_or_write(self):
        import importlib

        producer = importlib.import_module(MODULE)
        client = FakeSecClient(self.symbols)
        with self.assertRaises(producer.Bankruptcy8kCandidateScanError):
            producer.run_candidate_shard_scan(
                candidate_artifact_path=self.paths["candidate"],
                expected_decision_date=_DECISION_DATE,
                shard_start=0,
                shard_size=5,
                output_source_packet_path=self.paths["source_packet"],
                output_screen_path=self.paths["screen"],
                summary_path=self.paths["producer_summary"],
                consumer_summary_path=self.paths["consumer_summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=False,
            )

        self.assertEqual(client.urls, [])
        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["producer_summary"].exists())
        self.assertFalse(self.paths["screen"].exists())

    def test_endpoint_error_fails_closed_before_packet_summary_or_screen_write(self):
        import importlib

        producer = importlib.import_module(MODULE)
        client = FakeSecClient(self.symbols, error_symbol="AAC")
        with self._env(producer), mock.patch.object(
            producer.sample_validation, "_read_windows_environment_value", return_value=None
        ), mock.patch.object(producer.time, "sleep"):
            with self.assertRaises(producer.Bankruptcy8kCandidateScanError):
                producer.run_candidate_shard_scan(
                    candidate_artifact_path=self.paths["candidate"],
                    expected_decision_date=_DECISION_DATE,
                    shard_start=0,
                    shard_size=5,
                    output_source_packet_path=self.paths["source_packet"],
                    output_screen_path=self.paths["screen"],
                    summary_path=self.paths["producer_summary"],
                    consumer_summary_path=self.paths["consumer_summary"],
                    raw_root=self.raw_root,
                    client=client,
                    confirm_user_authorization=True,
                    generated_at="2026-07-05T12:00:00+00:00",
                    observed_at="2026-06-15T12:00:00+00:00",
                    sec_sleep_seconds=0,
                )

        self.assertFalse(self.paths["source_packet"].exists())
        self.assertFalse(self.paths["producer_summary"].exists())
        self.assertFalse(self.paths["screen"].exists())
        self.assertFalse(self.paths["consumer_summary"].exists())

    def test_summary_schema_rejects_scope_creep_claims(self):
        import importlib

        producer = importlib.import_module(MODULE)
        summary, _ = self._run_happy(shard_size=5)
        schema = _read_json(producer.SUMMARY_SCHEMA_PATH)
        validator = Draft7Validator(schema)

        for path, value in (
            (("scope", "full_market_scan_performed"), True),
            (("scope", "full_candidate_universe_scan_completed"), True),
            (("scope", "status_records_written"), True),
            (("scope", "run_fetch_invoked"), True),
            (("scope", "datahub_consumption_performed"), True),
            (("scope", "ship_gate_or_live_normalized_evidence_claimed"), True),
            (("prohibited_claims", "full_candidate_universe_complete"), True),
        ):
            mutated = json.loads(json.dumps(summary))
            cursor = mutated
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            self.assertGreater(len(list(validator.iter_errors(mutated))), 0, path)


if __name__ == "__main__":
    unittest.main()
