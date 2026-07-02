"""Offline tests for the US-short Cut 5 Pass-2 audit-gate + catalyst data-layer feasibility probe.

No network: a FakeClient returns canned payloads. Covers the whole class the probe must get right:
dry-run env boundary, full success + endpoint-error branches, SEC form-family extraction (incl the
Form-4 vs 424B disambiguation and prefix families), gitignored raw scoping, the pre-write secret scan +
schema validation (both with planted failures), budget honesty, and the confirm-authorization gate.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_short_cut5_pass2_feasibility_probe as probe  # noqa: E402
from runners import us_egs_sample_validation as sample_validation  # noqa: E402


CIK_MAPPING = {
    "0": {"cik_str": 320193, "ticker": "AAPL"},
    "1": {"cik_str": 789019, "ticker": "MSFT"},
    "2": {"cik_str": 1045810, "ticker": "NVDA"},
}

SUBMISSIONS_PAYLOAD = {
    "cik": "0000320193",
    "filings": {
        "recent": {
            "form": ["8-K", "10-Q", "S-3ASR", "424B5", "4", "424B2", "SC 13G/A", "40-F"],
            "filingDate": ["2026-05-01", "2026-04-30", "2026-03-01", "2026-03-02",
                           "2026-02-01", "2026-02-15", "2026-01-10", "2026-01-05"],
            "acceptanceDateTime": ["2026-05-01T16:05:00.000Z", "2026-04-30T16:05:00.000Z",
                                   "2026-03-01T09:00:00.000Z", "2026-03-02T09:00:00.000Z",
                                   "2026-02-01T18:00:00.000Z", "2026-02-15T18:00:00.000Z",
                                   "2026-01-10T12:00:00.000Z", "2026-01-05T12:00:00.000Z"],
            "accessionNumber": ["a", "b", "c", "d", "e", "f", "g", "h"],
        }
    },
}


def _fmp_payload(family: str, symbol: str) -> list:
    if family == "earnings-surprises":
        return [{"date": "2026-05-01", "symbol": symbol, "actualEarningResult": 1.52, "estimatedEarning": 1.41}]
    if family == "analyst-estimates":
        return [{"date": "2026-06-30", "symbol": symbol, "estimatedRevenueAvg": 1.0e11, "estimatedEpsAvg": 1.6}]
    if family == "grades":
        return [{"symbol": symbol, "date": "2026-05-02", "gradingCompany": "BankX",
                 "newGrade": "Buy", "previousGrade": "Hold"}]
    return []


class FakeClient:
    """URL-dispatched canned responses. fmp_status lets a test simulate a paid-wall (e.g. 403)."""

    def __init__(self, *, fmp_status: int = 200, benzinga_status: int = 404):
        self.fmp_status = fmp_status
        self.benzinga_status = benzinga_status
        self.calls: list[str] = []

    def get_json(self, url, *, headers=None, timeout_seconds=30):
        self.calls.append(url)
        if "company_tickers.json" in url:
            return CIK_MAPPING, 200, True, None
        if "/submissions/CIK" in url:
            return SUBMISSIONS_PAYLOAD, 200, True, None
        if "api.massive.com" in url:
            if "/reference/financials" in url:
                return {"results": [{"cik": 320193, "fiscal_period": "Q2", "fiscal_year": "2026",
                                     "start_date": "2026-01-01", "end_date": "2026-03-31",
                                     "filing_date": "2026-05-01", "financials": {}}]}, 200, True, None
            if "/reference/news" in url:
                return {"results": [{"id": "n1", "publisher": {"name": "Src"}, "title": "AAPL update",
                                     "published_utc": "2026-05-02T10:00:00Z",
                                     "article_url": "https://news.example/x", "tickers": ["AAPL"]}]}, 200, True, None
            if "/benzinga/" in url:   # Massive/Polygon estimate/earnings extension — 404 unless a test opts in
                if self.benzinga_status != 200:
                    return {"status": "NOT_FOUND"}, self.benzinga_status, False, "http_error"
                return {"results": [{"date": "2026-05-01", "ticker": "AAPL", "eps": 1.5,
                                     "eps_est": 1.4, "eps_surprise": 0.1}]}, 200, True, None
            return {"results": [{"t": 1717200000000, "o": 190.0, "h": 192.0, "l": 189.0,
                                 "c": 191.0, "v": 5_000_000}], "resultsCount": 1}, 200, True, None
        if "financialmodelingprep.com/stable/" in url:
            symbol = ""
            for part in url.split("?", 1)[-1].split("&"):
                if part.startswith("symbol="):
                    symbol = part.split("=", 1)[1]
            family = url.split("/stable/", 1)[1].split("?", 1)[0]
            if self.fmp_status != 200:
                return {"error": "forbidden"}, self.fmp_status, False, "http_error"
            return _fmp_payload(family, symbol), 200, True, None
        raise AssertionError(f"unexpected URL in test: {url}")


class Cut5ProbeTestBase(unittest.TestCase):
    def setUp(self):
        self._env_backup = {}
        for name in ("FMP_API_KEY", "SEC_USER_AGENT", "MASSIVE_API_KEY"):
            self._env_backup[name] = os.environ.get(name)
            os.environ[name] = f"DUMMY_{name}_VALUE"
        self._tmp_raw = ROOT / probe.RAW_SAMPLE_REL_ROOT / "raw_test"
        self._tmp_summary = ROOT / probe.RAW_SAMPLE_REL_ROOT / "test_summary.json"
        self._cleanup()

    def tearDown(self):
        self._cleanup()
        for name, value in self._env_backup.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def _cleanup(self):
        if self._tmp_raw.exists():
            shutil.rmtree(self._tmp_raw)
        if self._tmp_summary.exists():
            self._tmp_summary.unlink()

    def _run(self, *, client, confirm=True):
        return probe.run_probe(
            summary_path=self._tmp_summary,
            raw_root=self._tmp_raw,
            generated_at="2026-07-01T00:00:00+00:00",
            client=client,
            confirm_user_authorization=confirm,
            dry_run_env=False,
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )


class DryRunTests(Cut5ProbeTestBase):
    def test_dry_run_env_no_network_no_write(self):
        client = FakeClient()
        summary = probe.run_probe(
            summary_path=self._tmp_summary,
            raw_root=self._tmp_raw,
            generated_at="2026-07-01T00:00:00+00:00",
            client=client,
            confirm_user_authorization=False,
            dry_run_env=True,
        )
        self.assertEqual(client.calls, [])
        self.assertFalse(self._tmp_summary.exists())
        self.assertEqual(summary["scope"]["status"], "dry_run_env_only")
        self.assertFalse(summary["scope"]["provider_live_probe_performed"])
        self.assertTrue(summary["environment"]["massive_api_key_present"])
        self.assertTrue(summary["validation_decision"]["sr_provider_001_remains_open"])


class FullRunTests(Cut5ProbeTestBase):
    def test_full_success_shape_and_budget(self):
        client = FakeClient()
        summary = self._run(client=client)
        # 1 mapping + 3x3 FMP + 3 submissions + 1 Massive aggs + 3x2 Massive reference + 1 earnings probe = 21
        self.assertEqual(summary["endpoint_call_budget"]["actual_total_endpoint_calls"], 21)
        self.assertTrue(summary["endpoint_call_budget"]["within_budget"])
        # the benzinga earnings probe 404s → completed_with_endpoint_errors is the honest status
        self.assertEqual(summary["scope"]["status"], "feasibility_probe_completed_with_endpoint_errors")
        self.assertTrue(self._tmp_summary.exists())

    def test_sec_form_families_extracted(self):
        summary = self._run(client=FakeClient())
        aapl = next(s for s in summary["symbol_results"] if s["symbol"] == "AAPL")
        fams = aapl["sec_form_families"]
        self.assertEqual(fams["8-K"]["count"], 1)
        self.assertEqual(fams["8-K"]["most_recent_filing_date"], "2026-05-01")
        self.assertEqual(fams["S-3"]["count"], 1)           # S-3ASR matched by the S-3 family
        self.assertEqual(fams["424B"]["count"], 2)          # 424B5 + 424B2
        self.assertEqual(fams["form_4"]["count"], 1)        # exactly "4", NOT 424B*/40-F
        self.assertEqual(fams["SC_13G"]["count"], 1)        # "SC 13G/A" matched by prefix
        self.assertEqual(fams["10-K"]["count"], 0)

    def test_feasibility_findings_reachable(self):
        summary = self._run(client=FakeClient())
        ff = summary["feasibility_findings"]
        self.assertEqual(ff["sec_filing_channel"]["reachable_symbol_count"], 3)
        self.assertTrue(ff["fmp_earnings_surprises"]["reachable"])
        self.assertEqual(ff["fmp_earnings_surprises"]["shape_ok_symbol_count"], 3)
        self.assertTrue(ff["fmp_grades"]["reachable"])
        self.assertTrue(ff["massive_per_ticker"]["reachable"])
        self.assertEqual(ff["massive_per_ticker"]["bar_count"], 1)
        self.assertTrue(all(ff["massive_per_ticker"]["ohlcv_fields_present"].values()))
        self.assertFalse(ff["sec_semantic_5_1b"]["reachable_via_this_probe"])
        # Massive/Polygon reference retry (user request): financials + news reachable, estimate/earnings probe not
        self.assertTrue(ff["massive_financials"]["reachable"])
        self.assertEqual(ff["massive_financials"]["shape_ok_symbol_count"], 3)
        self.assertTrue(ff["massive_news"]["reachable"])
        self.assertFalse(ff["massive_earnings_analyst_probe"]["reachable"])
        self.assertIn(404, ff["massive_earnings_analyst_probe"]["observed_http_statuses"])

    def test_all_success_when_benzinga_reachable(self):
        summary = self._run(client=FakeClient(benzinga_status=200))
        self.assertEqual(summary["scope"]["status"], "feasibility_probe_completed")
        ff = summary["feasibility_findings"]
        self.assertTrue(ff["massive_earnings_analyst_probe"]["reachable"])
        self.assertEqual(ff["massive_earnings_analyst_probe"]["shape_ok_symbol_count"], 1)

    def test_written_summary_has_no_secret_or_domain(self):
        self._run(client=FakeClient())
        text = self._tmp_summary.read_text(encoding="utf-8").lower()
        self.assertNotIn("dummy_fmp_api_key_value", text)
        self.assertNotIn("apikey=", text)
        self.assertNotIn("financialmodelingprep.com", text)
        self.assertNotIn("api.massive.com", text)
        self.assertNotIn("data.sec.gov", text)

    def test_fmp_paid_wall_reports_errors_not_crash(self):
        summary = self._run(client=FakeClient(fmp_status=403))
        self.assertEqual(summary["scope"]["status"], "feasibility_probe_completed_with_endpoint_errors")
        self.assertFalse(summary["feasibility_findings"]["fmp_earnings_surprises"]["reachable"])
        self.assertIn(403, summary["feasibility_findings"]["fmp_earnings_surprises"]["observed_http_statuses"])
        # SEC + Massive still succeed → the probe still completes and writes a valid summary
        self.assertTrue(summary["feasibility_findings"]["sec_filing_channel"]["pit_dates_available"])
        self.assertTrue(self._tmp_summary.exists())


class GateTests(Cut5ProbeTestBase):
    def test_confirm_authorization_required_for_live(self):
        with self.assertRaises(RuntimeError):
            self._run(client=FakeClient(), confirm=False)

    def test_raw_root_outside_provider_samples_rejected(self):
        with self.assertRaises(ValueError):
            probe.run_probe(
                summary_path=self._tmp_summary,
                raw_root=ROOT / "state" / "leak_here",
                client=FakeClient(),
                confirm_user_authorization=True,
                now=datetime(2026, 7, 1, tzinfo=timezone.utc),
            )


class FormFamilyUnitTests(unittest.TestCase):
    def test_non_dict_payload_is_failclosed_empty(self):
        for bad in (None, [], "x", 3, {"filings": None}, {"filings": {"recent": None}}):
            fams = probe.extract_sec_form_families(bad)
            self.assertTrue(all(info["count"] == 0 for info in fams.values()))

    def test_form_4_not_swallowed_by_424b_or_40f(self):
        payload = {"filings": {"recent": {
            "form": ["424B5", "40-F", "4/A", "4"],
            "filingDate": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
            "acceptanceDateTime": ["", "", "", ""],
        }}}
        fams = probe.extract_sec_form_families(payload)
        self.assertEqual(fams["form_4"]["count"], 2)   # "4" and "4/A" only
        self.assertEqual(fams["424B"]["count"], 1)

    def test_most_recent_by_filing_date(self):
        payload = {"filings": {"recent": {
            "form": ["8-K", "8-K", "8-K"],
            "filingDate": ["2026-03-01", "2026-05-09", "2026-01-01"],
            "acceptanceDateTime": ["x", "y", "z"],
        }}}
        fams = probe.extract_sec_form_families(payload)
        self.assertEqual(fams["8-K"]["count"], 3)
        self.assertEqual(fams["8-K"]["most_recent_filing_date"], "2026-05-09")
        self.assertEqual(fams["8-K"]["most_recent_acceptance_datetime"], "y")


class SecretScanTests(unittest.TestCase):
    def test_apikey_fragment_rejected(self):
        with self.assertRaises(RuntimeError):
            probe._assert_text_safe('{"x":"...apikey=SECRET..."}', [])

    def test_provider_domain_rejected(self):
        for frag in ("financialmodelingprep.com", "api.massive.com", "data.sec.gov"):
            with self.assertRaises(RuntimeError):
                probe._assert_text_safe(json.dumps({"note": f"see {frag}"}), [])

    def test_sensitive_env_value_rejected(self):
        with self.assertRaises(RuntimeError):
            probe._assert_text_safe('{"ok":true,"blob":"MYKEY123"}', ["MYKEY123"])

    def test_clean_text_passes(self):
        probe._assert_text_safe(json.dumps({"provider": "SEC EDGAR", "note": "Massive per-ticker"}), ["UNUSED"])


class SchemaValidationTests(Cut5ProbeTestBase):
    def _valid_summary(self):
        return self._run(client=FakeClient())

    def test_valid_summary_passes_schema(self):
        probe._validate_summary_against_schema(self._valid_summary())  # no raise

    def test_flipped_safety_flag_rejected(self):
        summary = self._valid_summary()
        summary["scope"]["datahub_consumption_performed"] = True
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(summary)

    def test_sr_provider_flip_rejected(self):
        summary = self._valid_summary()
        summary["validation_decision"]["sr_provider_001_remains_open"] = False
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(summary)

    def test_over_budget_rejected_by_schema(self):
        summary = self._valid_summary()
        summary["endpoint_call_budget"]["actual_total_endpoint_calls"] = 99
        summary["endpoint_call_budget"]["within_budget"] = False
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(summary)


class EndpointManifestTests(Cut5ProbeTestBase):
    def test_full_run_manifest_matches_frozen(self):
        summary = self._run(client=FakeClient())
        m = summary["endpoint_manifest"]
        self.assertEqual(m["actual_total"], 21)
        self.assertTrue(m["matches_expected"])
        self.assertEqual(m["expected_total"], 21)
        self.assertEqual(m["per_family"], m["expected_manifest"])

    def test_compute_manifest_counts_per_family(self):
        rows = [{"provider": "SEC", "endpoint_family": "submissions"},
                {"provider": "SEC", "endpoint_family": "submissions"},
                {"provider": "FMP", "endpoint_family": "grades"}]
        m = probe.compute_endpoint_manifest(rows)
        self.assertEqual(m["per_family"], {"FMP:grades": 1, "SEC:submissions": 2})
        self.assertEqual(m["actual_total"], 3)
        self.assertFalse(m["matches_expected"])   # not the full 21-call plan

    def test_truthful_storage_paths(self):
        summary = self._run(client=FakeClient())
        # the emitted storage paths equal the ACTUAL resolved destinations (no hardcoded canonical lie)
        self.assertEqual(summary["storage"]["tracked_summary_path"], probe._repo_relative(self._tmp_summary))
        self.assertEqual(summary["storage"]["raw_payload_root"], probe._repo_relative(self._tmp_raw))


class PathAndTimeGuardTests(Cut5ProbeTestBase):
    def test_summary_path_outside_approved_rejected(self):
        with self.assertRaises(ValueError):
            probe.run_probe(summary_path=ROOT / "state" / "leak_summary.json", raw_root=self._tmp_raw,
                            client=FakeClient(), confirm_user_authorization=True,
                            now=datetime(2026, 7, 1, tzinfo=timezone.utc))

    def test_bad_generated_at_rejected_by_producer(self):
        with self.assertRaises(RuntimeError):
            probe.run_probe(summary_path=self._tmp_summary, raw_root=self._tmp_raw, generated_at="not-a-time",
                            client=FakeClient(), confirm_user_authorization=True,
                            now=datetime(2026, 7, 1, tzinfo=timezone.utc))

    def test_valid_generated_at_helper(self):
        self.assertTrue(probe._valid_generated_at("2026-07-01T10:31:44+00:00"))
        self.assertTrue(probe._valid_generated_at("2026-07-01T10:31:44Z"))
        for bad in ("not-a-time", "2026-07-01", "2026-07-01 10:31:44", "2026-07-01T10:31:44",
                    "2026-07-01T10:31:44T+00:00", 123):   # incl the double-'T' case
            self.assertFalse(probe._valid_generated_at(bad))


def _write_followup_raw(raw_root, symbol="AAPL"):
    for primary_symbol in probe.EXPECTED_PRIMARY_FINANCIAL_SYMBOLS:
        d = raw_root / "massive" / primary_symbol
        d.mkdir(parents=True, exist_ok=True)
        (d / "massive_financials.json").write_text(json.dumps({
            "provider_id": "massive", "endpoint_family": "massive_financials", "symbol": primary_symbol,
            "http_status": 200, "ok": True, "payload": {"results": []}}), encoding="utf-8")
    rows_by_timeframe = {
        "quarterly": [
            {"filing_date": "2026-05-01", "acceptance_datetime": "2026-05-01T10:01:00Z"},
            {"filing_date": "2026-02-01", "acceptance_datetime": "2026-02-01T10:01:00Z"},
            {"filing_date": None, "acceptance_datetime": None},
            {"filing_date": "2025-11-01", "acceptance_datetime": "2025-11-01T10:01:00Z"},
        ],
        "annual": [
            {"filing_date": "2025-10-31", "acceptance_datetime": "2025-10-31T10:01:26Z"},
            {"filing_date": "2024-11-01", "acceptance_datetime": "2024-11-01T10:01:26Z"},
            {"filing_date": "2023-11-01", "acceptance_datetime": "2023-11-01T10:01:26Z"},
            {"filing_date": "2022-11-01", "acceptance_datetime": None},
        ],
    }
    for timeframe, rows in rows_by_timeframe.items():
        d = raw_root / "massive" / symbol
        d.mkdir(parents=True, exist_ok=True)
        (d / f"massive_financials_{timeframe}.json").write_text(json.dumps({
            "http": 200, "timeframe": timeframe, "ticker": symbol,
            "payload": {"results": rows}}), encoding="utf-8")


def _write_ff_file(raw_root, symbol, timeframe, *, http=200, ticker=None, tf=None, results="_default"):
    d = raw_root / "massive" / symbol
    d.mkdir(parents=True, exist_ok=True)
    if results == "_default":
        results = [{"filing_date": "2026-05-01", "acceptance_datetime": "2026-05-01T10:01:00Z"}]
    (d / f"massive_financials_{timeframe}.json").write_text(json.dumps({
        "http": http, "timeframe": tf if tf is not None else timeframe,
        "ticker": ticker if ticker is not None else symbol,
        "payload": {"results": results}}), encoding="utf-8")


class FollowUpFailClosedTests(Cut5ProbeTestBase):
    """The follow-up block builder must be an EXACT fail-closed 2-call manifest (Codex re-review residual): a
    missing / extra / duplicate / wrong-symbol / failed / empty / envelope-mismatched follow-up must RAISE before
    it can ever become the artifact cited as periodic-PIT proof."""

    def test_empty_raw_dir_raises(self):
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)   # no massive dir -> not the exact 2-call set

    def test_missing_one_call_raises(self):
        _write_ff_file(self._tmp_raw, "AAPL", "quarterly")        # annual missing
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_extra_symbol_call_raises(self):
        _write_followup_raw(self._tmp_raw)                        # AAPL q+a
        _write_ff_file(self._tmp_raw, "MSFT", "quarterly")       # unauthorized extra
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_http_failure_raises(self):
        _write_followup_raw(self._tmp_raw)
        _write_ff_file(self._tmp_raw, "AAPL", "quarterly", http=403)
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_empty_results_raises(self):
        _write_followup_raw(self._tmp_raw)
        _write_ff_file(self._tmp_raw, "AAPL", "quarterly", results=[])
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_absent_filing_date_raises(self):
        _write_followup_raw(self._tmp_raw)
        _write_ff_file(self._tmp_raw, "AAPL", "quarterly",
                       results=[{"acceptance_datetime": "2026-05-01T10:01:00Z"}])   # no filing_date
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_envelope_mismatch_raises(self):
        _write_followup_raw(self._tmp_raw)
        _write_ff_file(self._tmp_raw, "AAPL", "quarterly", ticker="MSFT")   # envelope ticker disagrees
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_valid_two_call_set_builds(self):
        _write_followup_raw(self._tmp_raw)
        block = probe.build_followup_execution_block(self._tmp_raw)
        self.assertEqual(block["call_count"], 2)
        self.assertEqual((block["total_result_count"], block["valid_pit_row_count"]), (8, 6))
        self.assertFalse(block["all_filing_dates_valid"])
        self.assertFalse(block["all_acceptance_datetimes_valid"])


class FollowUpExhaustiveNamespaceTests(Cut5ProbeTestBase):
    """Codex round-2 residual A: the follow-up inventory must EXHAUSTIVELY enumerate massive_financials* and reject
    any extra / renamed / wrong-extension / nested periodic artifact — not just check two hardcoded filenames (which
    let an extra massive_financials_monthly.json ride invisibly while still returning call_count=2)."""

    def _extra(self, name, *, symbol="AAPL", body=None):
        d = self._tmp_raw / "massive" / symbol
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body if body is not None else json.dumps({
            "http": 200, "timeframe": "quarterly", "ticker": symbol,
            "payload": {"results": [{"filing_date": "2026-05-01", "acceptance_datetime": "2026-05-01T10:01:00Z"}]}}),
            encoding="utf-8")

    def test_extra_timeframe_file_raises(self):
        # Codex's EXACT round-2 probe: a valid pair + massive_financials_monthly.json must RAISE (was call_count=2)
        _write_followup_raw(self._tmp_raw)
        self._extra("massive_financials_monthly.json")
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_renamed_copy_file_raises(self):
        _write_followup_raw(self._tmp_raw)
        self._extra("massive_financials_qtr.json")            # a renamed/copied periodic artifact
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_wrong_extension_file_raises(self):
        _write_followup_raw(self._tmp_raw)
        self._extra("massive_financials_quarterly.txt")       # right stem, wrong extension
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_nested_symbol_file_raises(self):
        _write_followup_raw(self._tmp_raw)
        nested = self._tmp_raw / "massive" / "AAPL" / "sub"   # deeper than massive/<symbol>/<file>
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "massive_financials_quarterly.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_extra_symbol_periodic_raises(self):
        _write_followup_raw(self._tmp_raw)
        self._extra("massive_financials_quarterly.json", symbol="MSFT")   # unauthorized symbol -> set mismatch
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_primary_ttm_not_misclassified(self):
        # the DEFAULT-ttm massive_financials.json (primary artifact) must NOT be treated as a follow-up NOR rejected
        # as an unauthorized extra: a valid pair + a primary massive_financials.json still builds exactly 2 calls
        _write_followup_raw(self._tmp_raw)
        (self._tmp_raw / "massive" / "AAPL" / "massive_financials.json").write_text(
            json.dumps({"provider_id": "massive", "endpoint_family": "massive_financials", "symbol": "AAPL",
                        "http_status": 200, "ok": True, "payload": {"results": []}}), encoding="utf-8")
        block = probe.build_followup_execution_block(self._tmp_raw)
        self.assertEqual(block["call_count"], 2)

    def test_extra_primary_unknown_symbol_raises(self):
        _write_followup_raw(self._tmp_raw)
        self._extra("massive_financials.json", symbol="TSLA")
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_primary_http_failure_raises(self):
        _write_followup_raw(self._tmp_raw)
        p = self._tmp_raw / "massive" / "AAPL" / "massive_financials.json"
        p.write_text(json.dumps({"provider_id": "massive", "endpoint_family": "massive_financials",
                                 "symbol": "AAPL", "http_status": 403, "ok": False, "payload": {}}), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_primary_envelope_symbol_mismatch_raises(self):
        _write_followup_raw(self._tmp_raw)
        p = self._tmp_raw / "massive" / "AAPL" / "massive_financials.json"
        p.write_text(json.dumps({"provider_id": "massive", "endpoint_family": "massive_financials",
                                 "symbol": "MSFT", "http_status": 200, "ok": True, "payload": {}}), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_prefixed_directory_artifact_raises(self):
        _write_followup_raw(self._tmp_raw)
        hidden = self._tmp_raw / "massive" / "AAPL" / "massive_financials_monthly"
        hidden.mkdir(parents=True, exist_ok=True)
        (hidden / "call.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_misplaced_same_family_artifact_raises(self):
        _write_followup_raw(self._tmp_raw)
        misplaced = self._tmp_raw / "other" / "AAPL"
        misplaced.mkdir(parents=True, exist_ok=True)
        (misplaced / "massive_financials_monthly.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_non_utf8_raw_fails_closed(self):
        # §3.5 finding 2: a non-UTF-8 follow-up raw must yield a clean domain RuntimeError, never a raw UnicodeDecodeError
        _write_followup_raw(self._tmp_raw)
        (self._tmp_raw / "massive" / "AAPL" / "massive_financials_quarterly.json").write_bytes(b"\xff\xfe\x00{")
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_symlinked_subdir_rejected(self):
        # §3.5 finding 3: a symlinked subtree (which rglob does not follow) can hide a rogue artifact -> fail closed
        import tempfile
        _write_followup_raw(self._tmp_raw)
        ext = Path(tempfile.mkdtemp())
        (ext / "massive_financials_monthly.json").write_text("{}", encoding="utf-8")
        link = self._tmp_raw / "massive" / "AAPL" / "hidden"
        try:
            link.symlink_to(ext, target_is_directory=True)
        except (OSError, NotImplementedError):
            shutil.rmtree(ext, ignore_errors=True)
            self.skipTest("symlink creation not permitted in this environment")
        try:
            with self.assertRaises(RuntimeError):
                probe.build_followup_execution_block(self._tmp_raw)
        finally:
            shutil.rmtree(ext, ignore_errors=True)


class FollowUpValueValidityTests(Cut5ProbeTestBase):
    """Codex round-2 residual B: filing_date / acceptance_datetime must be VALIDATED VALUES (real YYYY-MM-DD /
    tz-aware RFC3339, semantics compatible with the Cut 5-b consumer) — not merely non-blank strings, so the probe
    cannot certify PIT evidence its intended parser would reject."""

    def _one_bad(self, *, filing_date, acceptance):
        _write_followup_raw(self._tmp_raw)                    # valid pair first (so the set matches)...
        _write_ff_file(self._tmp_raw, "AAPL", "quarterly",   # ...then corrupt one VALUE
                       results=[{"filing_date": filing_date, "acceptance_datetime": acceptance}])
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_nondate_filing_date_raises(self):
        # Codex's EXACT round-2 probe: filing_date="not-a-date" must RAISE (was accepted as present=true)
        self._one_bad(filing_date="not-a-date", acceptance="2026-05-01T10:01:00Z")

    def test_impossible_calendar_filing_date_raises(self):
        self._one_bad(filing_date="2026-13-40", acceptance="2026-05-01T10:01:00Z")

    def test_nontime_acceptance_raises(self):
        # Codex's EXACT round-2 probe: acceptance_datetime="not-a-time" must RAISE
        self._one_bad(filing_date="2026-05-01", acceptance="not-a-time")

    def test_naive_acceptance_raises(self):
        self._one_bad(filing_date="2026-05-01", acceptance="2026-05-01T10:01:00")   # no tz -> not PIT-lawful

    def test_boundary_year_acceptance_rejected(self):
        # §3.5 finding 1: an instant the consumer's ET astimezone would OverflowError must NOT be certified
        self._one_bad(filing_date="2026-05-01", acceptance="0001-01-01T00:00:00Z")

    def test_acceptance_validator_matches_consumer_on_boundary(self):
        # the probe must accept an acceptance_datetime IFF the Cut 5-b consumer can ET-normalize it (no over-certify)
        from engine import us_short_massive_financials as consumer
        for v in ("2026-05-01T10:01:00Z", "0001-01-01T00:00:00Z"):
            try:
                consumer._observed_at_et(v)
                consumer_ok = True
            except consumer.MassiveFinancialsError:
                consumer_ok = False
            self.assertEqual(probe._valid_acceptance_instant(v), consumer_ok, v)

    def test_valid_ymd_helper(self):
        self.assertTrue(probe._valid_ymd("2026-05-01"))
        for bad in ("not-a-date", "2026-13-40", "2026-5-1", "2026/05/01", "", "2026-05-01T00:00:00Z", 20260501, None):
            self.assertFalse(probe._valid_ymd(bad))

    def test_valid_acceptance_instant_helper(self):
        for good in ("2026-05-01T10:01:00Z", "2026-05-01T10:01:00+00:00", "2026-05-01T06:01:00-04:00"):
            self.assertTrue(probe._valid_acceptance_instant(good))     # UTC-Z + numeric-offset positive controls
        for bad in ("not-a-time", "2026-05-01", "2026-05-01 10:01:00", "2026-05-01T10:01:00", "", None, 123):
            self.assertFalse(probe._valid_acceptance_instant(bad))

    def test_later_invalid_row_cannot_report_all_present(self):
        _write_followup_raw(self._tmp_raw)
        _write_ff_file(self._tmp_raw, "AAPL", "quarterly", results=[
            {"filing_date": "2026-05-01", "acceptance_datetime": "2026-05-01T10:01:00Z"},
            {"filing_date": "not-a-date", "acceptance_datetime": "not-a-time"},
        ])
        block = probe.build_followup_execution_block(self._tmp_raw)
        self.assertFalse(block["all_filing_dates_valid"])
        self.assertFalse(block["all_acceptance_datetimes_valid"])


class FollowUpAndReconcileTests(Cut5ProbeTestBase):
    def test_followup_block_from_raw(self):
        _write_followup_raw(self._tmp_raw)
        block = probe.build_followup_execution_block(self._tmp_raw)
        self.assertEqual(block["call_count"], 2)
        self.assertEqual(block["primary_raw_symbols"], ["AAPL", "MSFT", "NVDA"])
        self.assertEqual((block["total_result_count"], block["valid_pit_row_count"]), (8, 6))
        self.assertFalse(block["all_filing_dates_valid"])
        self.assertFalse(block["all_acceptance_datetimes_valid"])
        self.assertEqual(block["authorization_ref"], "user_chat_20260701_cut5_massive_financials_periodic_reprobe")
        self.assertEqual({c["timeframe"] for c in block["calls"]}, {"quarterly", "annual"})

    def test_reconcile_adds_followup_and_manifest_and_passes_schema(self):
        self._run(client=FakeClient())                 # writes a valid primary summary to the tmp path
        _write_followup_raw(self._tmp_raw)
        reconciled = probe.reconcile_summary(summary_path=self._tmp_summary, raw_root=self._tmp_raw)
        self.assertEqual(reconciled["follow_up_execution"]["call_count"], 2)
        self.assertEqual(reconciled["endpoint_manifest"]["actual_total"], 21)
        self.assertFalse(reconciled["feasibility_findings"]["massive_financials"]["filing_date_present_in_default_ttm"])
        probe._validate_summary_against_schema(reconciled)   # no raise

    def test_reconcile_summary_path_outside_approved_rejected(self):
        with self.assertRaises(ValueError):
            probe.reconcile_summary(summary_path=ROOT / "state" / "x.json", raw_root=self._tmp_raw)

    def test_reconcile_raw_root_outside_probe_rejected(self):
        # reconcile must only read from THIS probe's own gitignored raw (symmetry with run_probe)
        with self.assertRaises(ValueError):
            probe.reconcile_summary(summary_path=self._tmp_summary, raw_root=ROOT / "state" / "leak_raw")


class TrackedSummaryTests(unittest.TestCase):
    """Guards on the REAL committed tracked artifact (not a tmp fixture)."""

    def setUp(self):
        self.summary = json.loads(probe.SUMMARY_PATH.read_text(encoding="utf-8"))

    def test_tracked_summary_passes_schema(self):
        probe._validate_summary_against_schema(self.summary)

    def test_tracked_summary_inventories_followup(self):
        # follow-up-call OMISSION guard: the tracked artifact MUST inventory the quarterly/annual re-probe it relies on
        fu = self.summary["follow_up_execution"]
        self.assertEqual(fu["call_count"], 2)
        self.assertEqual(fu["primary_raw_symbols"], ["AAPL", "MSFT", "NVDA"])
        self.assertEqual((fu["total_result_count"], fu["valid_pit_row_count"]), (8, 6))
        self.assertFalse(fu["all_filing_dates_valid"])
        self.assertFalse(fu["all_acceptance_datetimes_valid"])
        self.assertEqual({c["timeframe"] for c in fu["calls"]}, {"quarterly", "annual"})

    def test_tracked_summary_manifest_frozen(self):
        m = self.summary["endpoint_manifest"]
        self.assertEqual(m["actual_total"], 21)
        self.assertTrue(m["matches_expected"])

    def test_tracked_summary_ttm_not_periodic(self):
        mf = self.summary["feasibility_findings"]["massive_financials"]
        self.assertFalse(mf["filing_date_present_in_default_ttm"])
        self.assertEqual(mf["default_timeframe_probed"], "ttm")


class PlantedSchemaMutationTests(Cut5ProbeTestBase):
    """The six planted mutations Codex requires must each be rejected by the schema (finding B)."""

    def _reconciled(self):
        self._run(client=FakeClient())
        _write_followup_raw(self._tmp_raw)
        return probe.reconcile_summary(summary_path=self._tmp_summary, raw_root=self._tmp_raw)

    def test_wrong_total_count_rejected(self):
        s = self._reconciled()
        s["endpoint_manifest"]["actual_total"] = 99
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)

    def test_wrong_per_family_via_matches_flag_rejected(self):
        s = self._reconciled()
        s["endpoint_manifest"]["matches_expected"] = False   # a completed run must have matches_expected == true
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)

    def test_default_ttm_vs_periodic_contradiction_rejected(self):
        s = self._reconciled()
        s["feasibility_findings"]["massive_financials"]["filing_date_present_in_default_ttm"] = True
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)

    def test_live_without_authorization_rejected(self):
        s = self._reconciled()
        s["scope"]["provider_live_probe_performed"] = True
        s["pre_execution_checks"]["user_authorization_confirmed"] = False
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)

    def test_bad_generated_at_rejected_by_schema(self):
        s = self._reconciled()
        s["generated_at"] = "not-a-time"
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)

    def test_path_mismatch_rejected(self):
        s = self._reconciled()
        s["storage"]["tracked_summary_path"] = "state/leak.json"
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)

    def test_followup_authorization_drift_rejected(self):
        s = self._reconciled()
        s["follow_up_execution"]["authorization_ref"] = "user_chat_something_else"
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)

    def test_completed_run_per_family_drift_rejected(self):
        # a completed run's per_family is frozen at the 21-call plan; a hand-forged per_family must fail (finding B, A-i)
        s = self._reconciled()
        s["endpoint_manifest"]["per_family"] = {"SEC:submissions": 21}
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)

    def test_malformed_followup_raw_fails_closed(self):
        # a truncated/invalid-JSON follow-up raw must fail closed as a domain RuntimeError, never leak JSONDecodeError
        _write_followup_raw(self._tmp_raw)                     # valid pair first (so the set matches)...
        d = self._tmp_raw / "massive" / "AAPL"
        (d / "massive_financials_quarterly.json").write_text("{not valid json", encoding="utf-8")   # ...then corrupt one
        with self.assertRaises(RuntimeError):
            probe.build_followup_execution_block(self._tmp_raw)

    def test_empty_followup_calls_rejected(self):
        # Codex's exact mutant: calls=[] + call_count=0 + both flags false must FAIL (was 0 schema error before)
        s = self._reconciled()
        s["follow_up_execution"].update({"calls": [], "call_count": 0,
                                         "total_result_count": 0, "valid_pit_row_count": 0})
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)

    def test_followup_wrong_symbol_rejected(self):
        s = self._reconciled()
        s["follow_up_execution"]["calls"][0]["symbol"] = "MSFT"
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)

    def test_followup_http_failure_rejected(self):
        s = self._reconciled()
        s["follow_up_execution"]["calls"][0]["http_status"] = 403
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)

    def test_followup_count_lie_rejected(self):
        s = self._reconciled()
        s["follow_up_execution"]["call_count"] = 3
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)

    def test_followup_aggregate_flag_lie_rejected(self):
        s = self._reconciled()
        s["follow_up_execution"]["all_filing_dates_valid"] = True
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)

    def test_extra_top_level_authorization_claim_rejected(self):
        # Codex's exact mutant: an injected top-level authorization claim must fail (additionalProperties:false)
        s = self._reconciled()
        s["provider_calls_authorized_now"] = True
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)

    def test_periodic_evidence_without_followup_block_rejected(self):
        # claiming periodic evidence in follow_up_execution but omitting the block must fail (cross-field)
        s = self._reconciled()
        del s["follow_up_execution"]
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)

    def test_extra_massive_financials_key_rejected(self):
        # a hand-injected misleading key in the massive_financials finding must fail (additionalProperties:false)
        s = self._reconciled()
        s["feasibility_findings"]["massive_financials"]["periodic_filing_date_proven"] = True
        with self.assertRaises(RuntimeError):
            probe._validate_summary_against_schema(s)


if __name__ == "__main__":
    unittest.main()
