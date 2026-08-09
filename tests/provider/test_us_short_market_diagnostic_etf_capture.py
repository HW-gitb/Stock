from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from runners import us_egs_sample_validation as sample_validation
from runners import us_short_market_diagnostic_etf_capture as capture


_FAKE_KEY = "FAKE-MASSIVE-KEY-capture-test"


class _FakeClient:
    def __init__(self, *, continuation: bool = True, wrong_continuation: bool = False,
                 unbounded: bool = False, unreadable_family: str | None = None,
                 price_mismatch: bool = False):
        self.urls: list[str] = []
        self.continuation = continuation
        self.wrong_continuation = wrong_continuation
        # unbounded=True models a real symbol whose history does not fit the page cap:
        # every page keeps offering another one, so the cap is what stops the walk.
        self.unbounded = unbounded
        self.unreadable_family = unreadable_family
        self.price_mismatch = price_mismatch

    def get_json(self, url, headers=None, timeout_seconds=30):
        self.urls.append(url)
        self.assert_key(url)
        parsed = __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(url)
        query = dict(__import__("urllib.parse", fromlist=["parse_qsl"]).parse_qsl(parsed.query))
        page = int(query.get("cursor", "page1").removeprefix("page"))
        symbol = query.get("ticker", "SPY")
        if "/dividends" in parsed.path:
            payload = {
                "status": "OK",
                "results": [
                    {
                        "ticker": query.get("ticker", "SPY"),
                        "ex_dividend_date": "2020-03-20",
                        "cash_amount": 1.0,
                        "split_adjusted_cash_amount": 1.0,
                    }
                ],
            }
        elif "/splits" in parsed.path:
            payload = {
                "status": "OK",
                "results": [
                    {
                        "ticker": query.get("ticker", "SPY"),
                        "execution_date": "2020-08-31",
                        "split_from": 1,
                        "split_to": 4,
                    }
                ],
            }
        else:
            symbol = parsed.path.split("/")[4]
            payload = {
                "status": "OK",
                "ticker": symbol,
                "adjusted": query.get("adjusted") == "true",
                "results": [{"t": 1577836800000 + page, "c": 100.0 + page}],
            }
            if self.price_mismatch and symbol == "VTI" and not query.get("adjusted") == "true":
                payload["results"][0]["c"] = 55.0
        family = "dividends" if "/dividends" in parsed.path else (
            "splits" if "/splits" in parsed.path else (
                "daily_adjusted" if query.get("adjusted") == "true" else "daily_unadjusted"
            )
        )
        if self.unreadable_family == family and symbol == "VTI":
            payload = {}
        if self.continuation and (self.unbounded or page == 1):
            if self.wrong_continuation:
                payload["next_url"] = "https://example.invalid/not-authorized"
            else:
                if "/dividends" in parsed.path or "/splits" in parsed.path:
                    event_symbol = query.get("ticker", "SPY")
                    payload["next_url"] = parsed._replace(query=f"ticker={event_symbol}&cursor=page{page + 1}").geturl()
                else:
                    payload["next_url"] = parsed._replace(query=f"cursor=page{page + 1}").geturl()
        return payload, 200, True, None

    def assert_key(self, url):
        # The fake is a plain object, not a TestCase, so it cannot borrow unittest
        # assertions. A bare assert keeps the check where it belongs: the key must
        # travel in every request URL, which is what makes the tracked-summary
        # secret scan below a meaningful assertion rather than a tautology.
        assert "apiKey=" + _FAKE_KEY in url, f"api key missing from request url: {url}"


class EtfCaptureRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raw = self.root / "raw"
        self.normalized = self.root / "normalized.json"
        self.summary = self.root / "summary.json"
        self.original_env = sample_validation.read_required_env
        self.original_ignored = capture._is_gitignored_provider_path
        self.original_path = capture._repo_relative_path
        sample_validation.read_required_env = lambda name: sample_validation.EnvValue(_FAKE_KEY, "test")
        capture._is_gitignored_provider_path = lambda path: True

        def temp_path(value, *, field):
            return {"raw_payload_root": self.raw, "normalized_capture_path": self.normalized, "tracked_summary_path": self.summary}[field]

        capture._repo_relative_path = temp_path

    def tearDown(self):
        sample_validation.read_required_env = self.original_env
        capture._is_gitignored_provider_path = self.original_ignored
        capture._repo_relative_path = self.original_path
        self.tmp.cleanup()

    def test_missing_confirmation_aborts_before_fetch(self):
        client = _FakeClient()
        with self.assertRaises(capture.EtfCaptureError):
            capture.run_capture(confirm_user_authorization=False, client=client, sleep_func=lambda _: None)
        self.assertEqual(client.urls, [])

    def test_authorized_capture_walks_the_exact_matrix_and_stays_secret_clean(self):
        client = _FakeClient(continuation=True)
        summary = capture.run_capture(
            confirm_user_authorization=True,
            client=client,
            sleep_func=lambda _: None,
            now_func=lambda: "2026-08-05T00:00:00+00:00",
        )
        self.assertEqual(summary["scope"]["actual_logical_requests"], 32)
        self.assertEqual(summary["scope"]["actual_http_attempts"], 32)
        self.assertEqual(len(client.urls), 32)
        self.assertEqual(len(summary["family_results"]), 16)
        self.assertTrue(all(item["pages_captured"] == 2 for item in summary["family_results"]))
        self.assertTrue(all(item["pagination_complete"] for item in summary["family_results"]))
        self.assertEqual({item["status"] for item in summary["family_results"]}, {"covered"})
        self.assertEqual({item["status"] for item in summary["daily_reconciliation"]}, {"session_coverage_match"})
        text = self.summary.read_text(encoding="utf-8")
        self.assertNotIn(_FAKE_KEY, text)
        self.assertNotIn("api.massive.com", text.lower())
        self.assertNotIn('"payload"', text)
        self.assertNotIn("100.0", text)
        self.assertTrue(self.normalized.exists())
        self.assertEqual(len(list(self.raw.rglob("*.json"))), 32)

    def test_unsafe_continuation_is_honest_incomplete_and_never_followed(self):
        client = _FakeClient(continuation=True, wrong_continuation=True)
        summary = capture.run_capture(
            confirm_user_authorization=True,
            client=client,
            sleep_func=lambda _: None,
            now_func=lambda: "2026-08-05T00:00:00+00:00",
        )
        first = summary["family_results"][0]
        self.assertEqual(first["status"], "pagination_incomplete")
        self.assertFalse(first["pagination_complete"])
        self.assertEqual(len(client.urls), 16)
        self.assertTrue(all("example.invalid" not in url for url in client.urls))

    def test_unreadable_body_is_not_reported_as_true_empty(self):
        client = _FakeClient(unreadable_family="splits")
        summary = capture.run_capture(
            confirm_user_authorization=True,
            client=client,
            sleep_func=lambda _: None,
            now_func=lambda: "2026-08-05T00:00:00+00:00",
        )
        vti_split = next(
            item for item in summary["family_results"]
            if item["symbol"] == "VTI" and item["endpoint_family"] == "splits"
        )
        self.assertEqual("unreadable_body", vti_split["status"])
        self.assertEqual(
            "covered",
            next(
                item for item in summary["family_results"]
                if item["symbol"] == "SPY" and item["endpoint_family"] == "splits"
            )["status"],
        )

    def test_numeric_price_mismatch_is_not_session_coverage_match(self):
        client = _FakeClient(price_mismatch=True)
        summary = capture.run_capture(
            confirm_user_authorization=True,
            client=client,
            sleep_func=lambda _: None,
            now_func=lambda: "2026-08-05T00:00:00+00:00",
        )
        self.assertEqual(
            "session_coverage_mismatch",
            next(item for item in summary["daily_reconciliation"] if item["symbol"] == "VTI")["status"],
        )
        self.assertEqual(
            "session_coverage_match",
            next(item for item in summary["daily_reconciliation"] if item["symbol"] == "SPY")["status"],
        )

    def test_page_cap_truncation_is_reported_as_incomplete_not_covered(self):
        """A symbol whose history outruns the page cap must degrade honestly.

        The sibling test above cannot see this: its fake stops offering pages after
        the first one, so the cap is never the thing that ends the walk and the run
        looks complete no matter what the cap is set to. Here every page offers
        another, so the cap is load-bearing -- and the run must say so rather than
        claim full coverage it does not have.
        """
        client = _FakeClient(continuation=True, unbounded=True)
        summary = capture.run_capture(
            confirm_user_authorization=True,
            client=client,
            sleep_func=lambda _: None,
            now_func=lambda: "2026-08-05T00:00:00+00:00",
        )
        cap = capture.load_packet()["execution"]["max_pages_per_symbol_family"]
        self.assertTrue(all(item["pages_captured"] == cap for item in summary["family_results"]))
        self.assertFalse(any(item["pagination_complete"] for item in summary["family_results"]))
        self.assertEqual({item["status"] for item in summary["family_results"]}, {"pagination_incomplete"})
        # the budget still holds: the cap bounds the walk, it does not run away
        self.assertEqual(len(client.urls), 16 * cap)
        self.assertEqual(summary["scope"]["actual_http_attempts"], 16 * cap)

    def test_packet_changes_are_rejected_before_provider_access(self):
        packet = capture.load_packet()
        broken = copy.deepcopy(packet)
        broken["scope"]["symbols"][0] = "AAPL"
        path = self.root / "bad_packet.json"
        path.write_text(json.dumps(broken), encoding="utf-8")
        client = _FakeClient()
        with self.assertRaises(capture.EtfCaptureError):
            capture.run_capture(confirm_user_authorization=True, packet_path=path, client=client, sleep_func=lambda _: None)
        self.assertEqual(client.urls, [])


if __name__ == "__main__":
    unittest.main()
