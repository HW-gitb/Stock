from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_short_batch5_full_candidate_live_source_packet as runner  # noqa: E402
from runners import us_short_market_diagnostic_etf_sidecar_fetch as etf_sidecar  # noqa: E402
from tests.provider.us_short_private_test_root import temporary_us_short_directory  # noqa: E402


class ScriptedClient:
    """Returns a queued sequence of (payload, http_status, ok, error_type) per get_json call; once the queue is
    drained it keeps returning the last-scripted response (so an over-retry can't IndexError)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._last = responses[-1]
        self.calls = 0

    def get_json(self, url, headers=None, timeout_seconds=30):
        self.calls += 1
        return self._responses.pop(0) if self._responses else self._last


class Pass2FetchRetryPacingTest(unittest.TestCase):
    """The Massive-only 429 retry: fixed 65-second waits, a 402 paywall is returned as-is, and retries never
    inflate the LOGICAL record count. Tests patch the sleeper so no wall-clock wait occurs."""

    def setUp(self):
        # fetch_and_store writes raw under a repo-relative path (as_repo_relative -> relative_to(ROOT)), so the
        # raw_root MUST live inside the repo; provider_samples/ is gitignored.
        root_context = temporary_us_short_directory(ROOT, Path("provider_samples"))
        provider_samples = Path(root_context.__enter__())
        self.addCleanup(root_context.__exit__, None, None, None)
        self._raw_root_dir = tempfile.TemporaryDirectory(
            prefix="test_retry_",
            dir=str(provider_samples),
        )
        self.raw_root = Path(self._raw_root_dir.name)

    def tearDown(self):
        self._raw_root_dir.cleanup()

    def _fetch(self, client, *, max_retries, provider_id="massive"):
        stats = {"used": 0}
        budget = runner.HttpAttemptBudget(max_total_http_attempts=1 + max_retries)
        sleeps = []
        with mock.patch.object(runner.time, "sleep", side_effect=sleeps.append):
            record = runner._fetch_with_retry(
                client,
                url="https://api.massive.com/v2/reference/news?ticker=AAPL&apiKey=K",
                provider_id=provider_id,
                endpoint_family="reference_news",
                symbol="AAPL",
                raw_root=self.raw_root,
                headers={},
                pace_seconds=0.0,
                max_retries=max_retries,
                retry_backoff_seconds=65.0 if max_retries else 0.0,
                retry_stats=stats,
                attempt_budget=budget,
                reserved_required_attempts=0,
            )
        return record, stats, sleeps

    def test_429_then_success_retries_and_recovers(self):
        client = ScriptedClient([({}, 429, False, "http_error"), ({"results": [{"id": "n1"}]}, 200, True, None)])
        record, stats, sleeps = self._fetch(client, max_retries=2)
        self.assertTrue(record.ok)
        self.assertEqual(stats["used"], 1)
        self.assertEqual(client.calls, 2)
        self.assertEqual(sleeps, [65.0])

    def test_sleep_func_injection_receives_canonical_wait(self):
        client = ScriptedClient([({}, 429, False, "http_error"), ({"results": []}, 200, True, None)])
        stats = {"used": 0}
        sleeps = []
        record = runner._fetch_with_retry(
            client,
            url="https://api.massive.com/v2/reference/news?ticker=AAPL&apiKey=K",
            provider_id="massive",
            endpoint_family="reference_news",
            symbol="AAPL",
            raw_root=self.raw_root,
            headers={},
            pace_seconds=0.0,
            max_retries=2,
            retry_backoff_seconds=65.0,
            retry_stats=stats,
            attempt_budget=runner.HttpAttemptBudget(max_total_http_attempts=2),
            reserved_required_attempts=0,
            sleep_func=sleeps.append,
        )
        self.assertTrue(record.ok)
        self.assertEqual(sleeps, [65.0])

    def test_402_paywall_is_not_retried(self):
        # second scripted response would succeed IF retried — it must never be reached.
        client = ScriptedClient([(None, 402, False, "http_error"), ({"results": []}, 200, True, None)])
        record, stats, sleeps = self._fetch(client, max_retries=2)
        self.assertFalse(record.ok)
        self.assertEqual(record.http_status, 402)
        self.assertEqual(stats["used"], 0)
        self.assertEqual(client.calls, 1)
        self.assertEqual(sleeps, [])

    def test_persistent_429_exhausts_bounded_retries(self):
        client = ScriptedClient([(None, 429, False, "http_error")])
        record, stats, sleeps = self._fetch(client, max_retries=2)
        self.assertFalse(record.ok)
        self.assertEqual(record.http_status, 429)
        self.assertEqual(stats["used"], 2)       # exactly max_retries retries
        self.assertEqual(client.calls, 3)        # 1 initial + 2 retries
        self.assertEqual(sleeps, [65.0, 65.0])

    def test_success_first_try_no_retry(self):
        client = ScriptedClient([({"results": []}, 200, True, None)])
        record, stats, sleeps = self._fetch(client, max_retries=2)
        self.assertTrue(record.ok)
        self.assertEqual(stats["used"], 0)
        self.assertEqual(client.calls, 1)
        self.assertEqual(sleeps, [])

    def test_zero_retries_disables_retry(self):
        client = ScriptedClient([(None, 429, False, "http_error"), ({"results": []}, 200, True, None)])
        record, stats, sleeps = self._fetch(client, max_retries=0)
        self.assertFalse(record.ok)
        self.assertEqual(stats["used"], 0)
        self.assertEqual(client.calls, 1)
        self.assertEqual(sleeps, [])

    def test_fmp_429_is_not_retried(self):
        client = ScriptedClient([(None, 429, False, "http_error"), ({"results": []}, 200, True, None)])
        record, stats, sleeps = self._fetch(client, max_retries=2, provider_id="financial_modeling_prep")
        self.assertFalse(record.ok)
        self.assertEqual(record.http_status, 429)
        self.assertEqual(stats["used"], 0)
        self.assertEqual(client.calls, 1)
        self.assertEqual(sleeps, [])

    def test_429_without_explicit_physical_slack_is_not_retried(self):
        client = ScriptedClient([(None, 429, False, "http_error"), ({"results": []}, 200, True, None)])
        stats = {"used": 0}
        record = runner._fetch_with_retry(
            client,
            url="https://api.massive.com/v2/reference/news?ticker=AAPL&apiKey=K",
            provider_id="massive",
            endpoint_family="reference_news",
            symbol="AAPL",
            raw_root=self.raw_root,
            headers={},
            pace_seconds=0.0,
            max_retries=2,
            retry_backoff_seconds=65.0,
            retry_stats=stats,
            attempt_budget=runner.HttpAttemptBudget(max_total_http_attempts=1),
            reserved_required_attempts=0,
        )
        self.assertFalse(record.ok)
        self.assertEqual(record.http_status, 429)
        self.assertEqual(stats["used"], 0)
        self.assertEqual(client.calls, 1)


class PhysicalAttemptBudgetTests(unittest.TestCase):
    def test_retry_cannot_steal_a_reserved_logical_attempt(self):
        budget = runner.HttpAttemptBudget(max_total_http_attempts=3)
        budget.consume_required_attempt()
        self.assertFalse(budget.consume_retry_if_available(reserved_required_attempts=2))
        self.assertEqual(budget.used, 1)

    def test_explicit_extra_physical_budget_allows_one_retry(self):
        budget = runner.HttpAttemptBudget(max_total_http_attempts=4)
        budget.consume_required_attempt()
        self.assertTrue(budget.consume_retry_if_available(reserved_required_attempts=2))
        self.assertEqual(budget.used, 2)


class Pass2RetryParamValidationTest(unittest.TestCase):
    # Budget 7 deliberately CANNOT match a ready on-disk preflight forecast, so even if the param validation were
    # ever reordered after preflight loading, these tests still fail-closed BEFORE any live provider call.
    _NO_MATCH_BUDGET = 7

    def test_massive_retry_constants_share_the_universe_source(self):
        self.assertEqual(
            runner.MASSIVE_429_RETRY_WAIT_SECONDS,
            runner.universe_fetch.MASSIVE_RATE_LIMIT_RETRY_SECONDS,
        )
        self.assertEqual(
            runner.MASSIVE_429_RETRY_MAX,
            runner.universe_fetch.MASSIVE_RATE_LIMIT_MAX_RETRIES,
        )
        self.assertEqual(
            runner.MASSIVE_RATE_LIMIT_WINDOW_CAPACITY,
            runner.universe_fetch.MASSIVE_RATE_LIMIT_WINDOW_CAPACITY,
        )
        self.assertEqual(
            etf_sidecar.MASSIVE_429_RETRY_WAIT_SECONDS,
            runner.universe_fetch.MASSIVE_RATE_LIMIT_RETRY_SECONDS,
        )
        self.assertEqual(
            etf_sidecar.MAX_RETRIES_PER_PAGE,
            runner.universe_fetch.MASSIVE_RATE_LIMIT_MAX_RETRIES,
        )

    def test_max_retries_over_cap_rejected_before_any_fetch(self):
        with self.assertRaises(runner.FullCandidateLiveSourcePacketError):
            runner.run_full_candidate_live_source_packet(
                expected_total_call_budget=self._NO_MATCH_BUDGET, confirm_user_authorization=True,
                max_retries_per_call=runner._MAX_RETRIES_PER_CALL_CAP + 1)

    def test_negative_pace_rejected(self):
        with self.assertRaises(runner.FullCandidateLiveSourcePacketError):
            runner.run_full_candidate_live_source_packet(
                expected_total_call_budget=self._NO_MATCH_BUDGET, confirm_user_authorization=True,
                provider_pace_seconds=-1.0)

    def test_non_finite_pace_or_backoff_rejected(self):
        # inf passes a naive `>= 0` guard and then time.sleep(inf) hangs/crashes — must be rejected up front.
        for bad in (float("inf"), float("nan")):
            with self.assertRaises(runner.FullCandidateLiveSourcePacketError):
                runner.run_full_candidate_live_source_packet(
                    expected_total_call_budget=self._NO_MATCH_BUDGET, confirm_user_authorization=True,
                    retry_backoff_seconds=bad)
            with self.assertRaises(runner.FullCandidateLiveSourcePacketError):
                runner.run_full_candidate_live_source_packet(
                    expected_total_call_budget=self._NO_MATCH_BUDGET, confirm_user_authorization=True,
                    provider_pace_seconds=bad)

    def test_zero_backoff_is_rejected_when_retries_are_enabled(self):
        with self.assertRaises(runner.FullCandidateLiveSourcePacketError):
            runner.run_full_candidate_live_source_packet(
                expected_total_call_budget=self._NO_MATCH_BUDGET,
                confirm_user_authorization=True,
                max_retries_per_call=1,
                retry_backoff_seconds=0.0,
            )


if __name__ == "__main__":
    unittest.main()
