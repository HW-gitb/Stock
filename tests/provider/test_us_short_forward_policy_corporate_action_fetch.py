# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from engine import us_short_forward_policy_corporate_action_evidence as evidence  # noqa: E402
from engine import us_short_forward_policy_source_capture as source  # noqa: E402
from engine.us_short_paper_eval_gate import paper_performance_evaluability_from_offline_evidence  # noqa: E402
from runners import us_short_forward_policy_corporate_action_fetch as fetch  # noqa: E402
import test_us_short_forward_policy_source_capture as source_fixture  # noqa: E402
import test_us_short_forward_policy_order_snapshot as order_fixture  # noqa: E402


def _replace(value, old: str, new: str):
    if isinstance(value, dict):
        return {key: _replace(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace(item, old, new) for item in value]
    return new if value == old else value


def _eligible_source_capture(decision_date: str = "20260720") -> dict:
    capture = _replace(order_fixture._capture(), "20260713", decision_date)
    packet = source_fixture._packet(
        decision_date=decision_date, price_basis_date="20260710",
        tickers=list(order_fixture.COMMON_POOL), start=date(2026, 6, 16), days=25,
    )
    with tempfile.TemporaryDirectory() as temp:
        output = Path(temp) / f"forward_policy_source_capture_{decision_date}.json"
        source.materialize_forward_policy_source_capture(
            capture=capture, ohlcv_packet=packet, ohlcv_packet_sha256="a" * 64,
            source_context_sha256=capture["source_context_sha256"],
            overextension_by_ticker={ticker: None for ticker in order_fixture.COMMON_POOL},
            market_axis_regimes=dict(order_fixture._AGGRESSIVE), prior_regime=None, prior_upgrade_count=0,
            private_output_path=output,
        )
        return json.loads(output.read_text(encoding="utf-8"))


def _maturity_packet(*, days: int = 20) -> dict:
    record = _eligible_source_capture()
    packet = source_fixture._packet(
        decision_date="20260810", price_basis_date="20260807",
        tickers=list(record["capture"]["common_selection_pool"]),
        start=date(2026, 7, 20), days=days,
    )
    packet["series_contract"]["adjustment_mode"] = "split_adjusted"
    for series in packet["series_by_ticker"].values():
        series["adjustment_mode"] = "split_adjusted"
    return packet


class QueueClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls: list[str] = []

    def get_json(self, url, *, headers=None, timeout_seconds=30):
        self.urls.append(url)
        return self.responses.pop(0)


def _ok(payload):
    return payload, 200, True, None


class ForwardPolicyCorporateActionFetchTests(unittest.TestCase):
    def _run(self, responses, *, prewrite=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        private_root = root / "state" / "us_short" / "shadow_compare_private"
        private_root.mkdir(parents=True)
        capture = _eligible_source_capture()
        capture_path = private_root / "forward_policy_source_capture_20260720.json"
        capture_path.write_text(json.dumps(capture), encoding="utf-8")
        maturity_path = root / "maturity.json"
        maturity_path.write_text(json.dumps(_maturity_packet(), sort_keys=True), encoding="utf-8")
        if prewrite is not None:
            prewrite(root, private_root, maturity_path)
        capability = fetch._issue_weekly_capstone_capability(
            decision_date="20260810", generated_at="2026-08-10T08:00:00-04:00",
            sample_root=root, private_root=private_root,
        )
        client = QueueClient(responses)
        with mock.patch.dict(os.environ, {"MASSIVE_API_KEY": "UNIT_TEST_SECRET"}):
            summary = fetch.run_fetch(
                confirm_user_authorization=True, capability=capability,
                decision_date="20260810", generated_at="2026-08-10T08:00:00-04:00",
                maturity_ohlcv_path=maturity_path, sample_root=root, private_root=private_root,
                client=client,
            )
        return root, private_root, maturity_path, summary, client

    def test_two_complete_empty_result_sets_emit_evaluable_sidecar_and_maturity_counts(self):
        root, private_root, maturity_path, summary, client = self._run([
            _ok({"results": []}), _ok({"results": []}),
        ])
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["http_attempt_count"], 2)
        self.assertEqual(len(client.urls), 2)
        self.assertTrue(all("ticker=" not in url.lower() and "limit=5000" in url for url in client.urls))
        sidecar = json.loads((private_root / "forward_policy_adjustment_evidence_20260720.json").read_text())
        self.assertEqual(sidecar["adjustment_mode"]["mode"], "split_adjusted_price_return")
        self.assertEqual(paper_performance_evaluability_from_offline_evidence(sidecar)["status"], "evaluable")
        maturity_bytes = maturity_path.read_bytes()
        result = source.materialize_forward_policy_source_maturity(
            source_capture=_eligible_source_capture(),
            current_ohlcv_packet=json.loads(maturity_bytes),
            current_ohlcv_packet_sha256=__import__("hashlib").sha256(maturity_bytes).hexdigest(),
            maturity_as_of="20260810", source_run_id="test-zero-event",
            adjustment_evidence=sidecar,
            private_outcome_path=private_root / "forward_policy_outcome_20260720.json",
        )
        self.assertTrue(result["counted_week_eligible"])
        serialized = json.dumps(summary, sort_keys=True)
        for forbidden in ("UNIT_TEST_SECRET", "api.massive.com", '"ticker"', '"payload"'):
            self.assertNotIn(forbidden, serialized)
        tracked = (root / fetch.SUMMARY_REL_ROOT / "coverage_summary_20260810.json").read_text()
        self.assertEqual(json.loads(tracked), summary)
        for forbidden in ("UNIT_TEST_SECRET", "api.massive.com", '"ticker"', '"payload"'):
            self.assertNotIn(forbidden, tracked)
        self.assertTrue((root / "provider_samples").exists())

    def test_eventful_window_is_no_count_but_outside_pool_event_is_evaluable(self):
        pool_ticker = _eligible_source_capture()["capture"]["common_selection_pool"][0]
        for family, date_field in (("splits", "execution_date"), ("dividends", "ex_dividend_date")):
            with self.subTest(family=family):
                rows = {"splits": [], "dividends": []}
                rows[family] = [{"id": f"{family}-1", "ticker": pool_ticker, date_field: "2026-07-25"}]
                _, private_root, _, summary, _ = self._run([
                    _ok({"results": rows["splits"]}), _ok({"results": rows["dividends"]}),
                ])
                self.assertEqual(summary["eventful_window_count"], 1)
                sidecar = json.loads((private_root / "forward_policy_adjustment_evidence_20260720.json").read_text())
                self.assertEqual(paper_performance_evaluability_from_offline_evidence(sidecar)["status"], "not_evaluable")
        _, private_root, _, summary, _ = self._run([
            _ok({"results": [{"id": "outside-1", "ticker": "ZZZZ", "execution_date": "2026-07-25"}]}),
            _ok({"results": []}),
        ])
        self.assertEqual(summary["eventful_window_count"], 0)
        sidecar = json.loads((private_root / "forward_policy_adjustment_evidence_20260720.json").read_text())
        self.assertEqual(paper_performance_evaluability_from_offline_evidence(sidecar)["status"], "evaluable")

    def test_malformed_duplicate_http_and_pagination_fail_closed(self):
        cases = {
            "missing": [_ok({"results": [{"ticker": "AAPL", "execution_date": "2026-07-25"}]}), _ok({"results": []})],
            "duplicate": [_ok({"results": [
                {"id": "x", "ticker": "AAPL", "execution_date": "2026-07-25"},
                {"id": "x", "ticker": "AAPL", "execution_date": "2026-07-26"},
            ]}), _ok({"results": []})],
            "http": [({"error": "no"}, 503, False, "http_error"), _ok({"results": []})],
            "hostile": [_ok({"results": [], "next_url": "https://evil.example/stocks/v1/splits?cursor=x"}), _ok({"results": []})],
            "third_page": [
                _ok({"results": [], "next_url": "https://api.massive.com/stocks/v1/splits?cursor=one"}),
                _ok({"results": [], "next_url": "https://api.massive.com/stocks/v1/splits?cursor=two"}),
                _ok({"results": []}),
            ],
        }
        for name, responses in cases.items():
            with self.subTest(name=name):
                _, private_root, _, summary, _ = self._run(responses)
                self.assertEqual(summary["status"], "incomplete_no_count")
                sidecar = json.loads((private_root / "forward_policy_adjustment_evidence_20260720.json").read_text())
                self.assertEqual(paper_performance_evaluability_from_offline_evidence(sidecar)["status"], "not_evaluable")

    def test_two_page_success_and_exact_replay_without_network_or_overwrite(self):
        root, private_root, maturity_path, _, _ = self._run([
            _ok({"results": [], "next_url": (
                "https://api.massive.com/stocks/v1/splits?cursor=one&apiKey=UNIT_TEST_SECRET"
            )}),
            _ok({"results": []}), _ok({"results": []}),
        ])
        sidecar_path = private_root / "forward_policy_adjustment_evidence_20260720.json"
        original = sidecar_path.read_bytes()
        cap = fetch._issue_weekly_capstone_capability(
            decision_date="20260810", generated_at="2026-08-10T08:00:00-04:00",
            sample_root=root, private_root=private_root,
        )
        empty_client = QueueClient([])
        with mock.patch.dict(os.environ, {"MASSIVE_API_KEY": "UNIT_TEST_SECRET"}):
            replay = fetch.run_fetch(
                confirm_user_authorization=True, capability=cap, decision_date="20260810",
                generated_at="2026-08-10T08:00:00-04:00", maturity_ohlcv_path=maturity_path,
                sample_root=root, private_root=private_root, client=empty_client,
            )
        self.assertEqual(replay["http_attempt_count"], 0)
        self.assertEqual(empty_client.urls, [])
        self.assertEqual(sidecar_path.read_bytes(), original)
        raw_path = root / "provider_samples" / "us_short_forward_policy_corporate_action_20260810" / \
            "raw" / "massive" / "splits_page_1.json"
        original_raw = raw_path.read_bytes()
        self.assertNotIn(b"UNIT_TEST_SECRET", original_raw)
        drifted_raw = json.loads(original_raw)
        drifted_raw["http_status"] = 201
        raw_path.write_text(json.dumps(drifted_raw), encoding="utf-8")
        with self.assertRaises(fetch.ForwardPolicyCorporateActionFetchError):
            fetch.run_fetch(
                confirm_user_authorization=True, capability=cap, decision_date="20260810",
                generated_at="2026-08-10T08:00:00-04:00", maturity_ohlcv_path=maturity_path,
                sample_root=root, private_root=private_root, client=empty_client,
            )
        raw_path.write_bytes(original_raw)
        tampered = json.loads(original)
        tampered["adjustment_mode"]["status"] = "ambiguous"
        sidecar_path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaises(fetch.ForwardPolicyCorporateActionFetchError):
            fetch.run_fetch(
                confirm_user_authorization=True, capability=cap, decision_date="20260810",
                generated_at="2026-08-10T08:00:00-04:00", maturity_ohlcv_path=maturity_path,
                sample_root=root, private_root=private_root, client=empty_client,
            )

    def test_prior_certificate_does_not_block_a_newly_mature_later_capture(self):
        root, private_root, maturity_path, _, _ = self._run([_ok({"results": []}), _ok({"results": []})])
        old_sidecar = (private_root / "forward_policy_adjustment_evidence_20260720.json").read_bytes()
        later = _eligible_source_capture("20260727")
        (private_root / "forward_policy_source_capture_20260727.json").write_text(json.dumps(later), encoding="utf-8")
        packet = source_fixture._packet(
            decision_date="20260817", price_basis_date="20260814",
            tickers=list(later["capture"]["common_selection_pool"]), start=date(2026, 7, 20), days=29,
        )
        packet["series_contract"]["adjustment_mode"] = "split_adjusted"
        for series in packet["series_by_ticker"].values():
            series["adjustment_mode"] = "split_adjusted"
        maturity_path.write_text(json.dumps(packet, sort_keys=True), encoding="utf-8")
        cap = fetch._issue_weekly_capstone_capability(
            decision_date="20260817", generated_at="2026-08-17T08:00:00-04:00",
            sample_root=root, private_root=private_root,
        )
        client = QueueClient([_ok({"results": []}), _ok({"results": []})])
        with mock.patch.dict(os.environ, {"MASSIVE_API_KEY": "UNIT_TEST_SECRET"}):
            summary = fetch.run_fetch(
                confirm_user_authorization=True, capability=cap, decision_date="20260817",
                generated_at="2026-08-17T08:00:00-04:00", maturity_ohlcv_path=maturity_path,
                sample_root=root, private_root=private_root, client=client,
            )
        self.assertEqual(summary["eligible_capture_count"], 1)
        self.assertEqual(len(client.urls), 2)
        self.assertTrue((private_root / "forward_policy_adjustment_evidence_20260727.json").exists())
        self.assertEqual((private_root / "forward_policy_adjustment_evidence_20260720.json").read_bytes(), old_sidecar)

    def test_pre_cutoff_incomplete_h20_and_caller_created_context_do_not_fetch(self):
        packet = _maturity_packet()
        raw = json.dumps(packet, sort_keys=True).encode()
        self.assertIsNone(evidence.derive_mature_h20_window(
            source_capture=source_fixture.ForwardPolicySourceCaptureTests()._source_capture(),
            maturity_ohlcv_packet=packet, maturity_ohlcv_sha256=__import__("hashlib").sha256(raw).hexdigest(),
            maturity_as_of="20260810",
        ))
        short = _maturity_packet(days=19)
        self.assertIsNone(evidence.derive_mature_h20_window(
            source_capture=_eligible_source_capture(), maturity_ohlcv_packet=short,
            maturity_ohlcv_sha256="a" * 64, maturity_as_of="20260810",
        ))
        client = QueueClient([])
        with self.assertRaises(fetch.ForwardPolicyCorporateActionFetchError):
            fetch.run_fetch(
                confirm_user_authorization=True, capability=None, decision_date="20260810", generated_at="x",
                maturity_ohlcv_path=Path("missing.json"), sample_root=Path(tempfile.gettempdir()),
                private_root=Path(tempfile.gettempdir()), client=client,
            )
        self.assertEqual(client.urls, [])

    def test_wrong_pool_date_or_source_digest_is_rejected_by_pure_emitter(self):
        packet = _maturity_packet()
        raw = json.dumps(packet, sort_keys=True).encode()
        window = evidence.derive_mature_h20_window(
            source_capture=_eligible_source_capture(), maturity_ohlcv_packet=packet,
            maturity_ohlcv_sha256=__import__("hashlib").sha256(raw).hexdigest(), maturity_as_of="20260810",
        )
        coverage = {
            "schema_name": "us_short_forward_policy_corporate_action_coverage", "schema_version": "1.0.0",
            "authorization_ref": fetch.AUTHORIZATION_REF, "generated_at": "x", "maturity_as_of": "20260810",
            "maturity_ohlcv_sha256": window["maturity_ohlcv_sha256"],
            "query_window": {"from": window["window_start"], "to": window["h20_session_date"]},
            "capture_bindings": [{key: window[key] for key in (
                "decision_date", "common_selection_pool_sha256", "window_start", "h20_session_date"
            )}],
            "families": {
                "splits": {"status": "complete", "date_field": "execution_date", "pages_fetched": 1,
                           "pagination_exhausted": True, "result_count": 0,
                           "result_sha256": evidence.canonical_sha256([]), "raw_page_sha256": ["a" * 64],
                           "events": [], "failure_reason": None},
                "dividends": {"status": "complete", "date_field": "ex_dividend_date", "pages_fetched": 1,
                              "pagination_exhausted": True, "result_count": 0,
                              "result_sha256": evidence.canonical_sha256([]), "raw_page_sha256": ["b" * 64],
                              "events": [], "failure_reason": None},
            },
            "boundary": {"track": "comparison_non_production", "provider_id": "massive",
                         "plan": "stocks_basic_free", "spend_usd": 0, "market_wide_queries_only": True,
                         "event_week_reconciliation_performed": False, "ship_gate_or_production_authorized": False,
                         "broker_or_order_automation_allowed": False},
        }
        for mutation in ("pool", "date", "source"):
            drifted = copy.deepcopy(coverage)
            if mutation == "pool":
                drifted["capture_bindings"][0]["common_selection_pool_sha256"] = "f" * 64
            elif mutation == "date":
                drifted["capture_bindings"][0]["h20_session_date"] = drifted["query_window"]["from"]
            else:
                drifted["maturity_ohlcv_sha256"] = "f" * 64
            with self.subTest(mutation=mutation), self.assertRaises(evidence.ForwardPolicyCorporateActionEvidenceError):
                evidence.build_adjustment_evidence(
                    window=window, coverage_packet=drifted,
                    coverage_packet_sha256=evidence.canonical_sha256(drifted),
                )


if __name__ == "__main__":
    unittest.main()
