from __future__ import annotations

import copy
import json
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

from runners import us_short_llm_theme_discovery_fetch_web as fetch
from tests.provider.us_short_private_test_root import temporary_provider_directory


class _Search:
    def __init__(self, rows): self.rows, self.calls = rows, []
    def search(self, query): self.calls.append(query); return copy.deepcopy(self.rows)


class _DeepSeek:
    def __init__(self, text): self.text, self.calls = text, []
    class _Completions:
        def __init__(self, owner): self.owner = owner
        def create(self, **kwargs): self.owner.calls.append(kwargs); return type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": self.owner.text})()})()]})()
    def __init_subclass__(cls): return super().__init_subclass__()
    @property
    def chat(self): return type("Chat", (), {"completions": self._completions})()
    _completions = None
    def __post_init__(self): pass


def _deepseek(text):
    obj = _DeepSeek(text)
    obj._completions = _DeepSeek._Completions(obj)
    return obj


ROWS = [
    {"url": "https://example.com/a", "title": "Power demand theme", "content": "AAPL and CEG discuss data-center power.", "published_date": "2026-07-24T10:00:00Z"},
    {"url": "https://example.com/b", "title": "Utility buildout", "content": "VST and CEG expand generation.", "published_date": "2026-07-23T10:00:00Z"},
    {"url": "https://example.com/b", "title": "Duplicate", "content": "duplicate", "published_date": "2026-07-23T10:00:00Z"},
    {"url": "https://example.com/future", "title": "Future", "content": "future", "published_date": "2026-07-25T14:00:00Z"},
    {"url": "not-a-url", "title": "Bad", "content": "bad", "published_date": "2026-07-23T10:00:00Z"},
]


class WebFetchTests(unittest.TestCase):
    def setUp(self):
        self._state_tempdir = temporary_provider_directory(fetch.ROOT)
        self._state_path = Path(self._state_tempdir.__enter__())
        self._state_patch = mock.patch.object(fetch, "STATE_DIR", self._state_path)
        self._state_patch.start()

    def tearDown(self):
        self._state_patch.stop()
        self._state_tempdir.__exit__(None, None, None)

    def _llm(self):
        refs = [fetch._source_id("https://example.com/a"), fetch._source_id("https://example.com/b")]
        return json.dumps({"themes": [{"theme_id": "power_demand", "display_name": "Power demand", "summary": "Cross-industry power demand.", "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": refs, "members": [{"ticker": "AAPL", "source_ref_ids": refs}, {"ticker": "CEG", "source_ref_ids": refs}]}]})

    def test_offline_fake_clients_keep_good_drop_bad_and_never_network(self):
        search = _Search(ROWS)
        ds = _deepseek(self._llm())
        discovery, receipt, summary = fetch.run_web_fetch(
            queries=["cross-industry power demand"], expected_decision_date="20260725",
            generated_at="2026-07-25T08:00:00Z", search_client=search, deepseek_client=ds,
        )
        self.assertEqual(search.calls, ["cross-industry power demand"])
        self.assertEqual(len(discovery["themes"]), 1)
        self.assertEqual(receipt["fetch_contract"]["execution_mode"], "offline_fake_client")
        self.assertFalse(receipt["fetch_contract"]["network_access_performed"])
        self.assertEqual(receipt["summary"]["accepted_source_count"], 2)
        self.assertEqual(summary["dropped_result_count"], 3)
        self.assertTrue(any(row["reason"] == "published_at_after_decision_open" for row in receipt["drop_ledger"]))

    def test_live_freeze_blocks_before_clients_keys_or_reservation(self):
        """K3-R34: live=True must stop before any provider-side effect begins."""
        with (
            mock.patch.object(fetch, "TavilyClient") as tavily_client,
            mock.patch.object(fetch, "_reserve_provider_budget") as reserve,
            mock.patch.object(fetch.os.environ, "get", side_effect=AssertionError("key lookup reached")) as key_lookup,
        ):
            with self.assertRaisesRegex(fetch.WebThemeDiscoveryError, "live execution is frozen"):
                fetch.run_web_fetch(
                    queries=["x"], expected_decision_date="20260725",
                    generated_at="2026-07-25T08:00:00Z", confirm_user_authorization=True, live=True,
                )
        tavily_client.assert_not_called()
        reserve.assert_not_called()
        key_lookup.assert_not_called()

    def test_invalid_llm_is_empty_but_packet_is_still_valid(self):
        packet, receipt, _ = fetch.build_web_fetch_packet(
            queries=["x"], search_results=ROWS[:2], llm_response="not json",
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        self.assertEqual(packet["themes"], [])
        self.assertEqual(receipt["summary"]["validated_theme_count"], 0)
        self.assertEqual(receipt["drop_ledger"][-1]["stage"], "llm")

    def test_model_top_level_superset_keeps_themes_and_ledgers_ignored_keys(self):
        payload = json.loads(self._llm())
        payload.update({"notes": "benign commentary", "confidence": 0.8})
        packet, receipt, _ = fetch.build_web_fetch_packet(
            queries=["x"], search_results=ROWS[:2], llm_response=json.dumps(payload),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        self.assertEqual([theme["theme_id"] for theme in packet["themes"]], ["power_demand"])
        ignored = [row for row in receipt["drop_ledger"] if row["reason"] == "ignored_top_level_keys"]
        self.assertEqual([row["detail"] for row in ignored], ["confidence,notes"])

    def test_model_top_level_without_theme_list_still_fails_closed(self):
        for payload in ({}, {"notes": "only"}, {"themes": None}, {"themes": {}}, {"themes": "bad"}):
            with self.subTest(payload=payload):
                packet, receipt, _ = fetch.build_web_fetch_packet(
                    queries=["x"], search_results=ROWS[:2], llm_response=json.dumps(payload),
                    expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                )
                self.assertEqual(packet["themes"], [])
                self.assertIn("invalid_or_unusable_response", [row["reason"] for row in receipt["drop_ledger"]])

    def test_one_bad_llm_theme_is_dropped_without_killing_good_theme(self):
        refs = [fetch._source_id("https://example.com/a"), fetch._source_id("https://example.com/b")]
        llm = {"themes": [
            {"theme_id": "good_theme", "display_name": "Good", "summary": "good", "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": refs, "members": [{"ticker": "AAPL", "source_ref_ids": refs}]},
            {"theme_id": "bad_theme", "display_name": "Bad", "summary": "bad", "observed_at": "2026-07-26T12:00:00Z", "source_ref_ids": refs, "members": [{"ticker": "CEG", "source_ref_ids": refs}]},
        ]}
        packet, receipt, _ = fetch.build_web_fetch_packet(
            queries=["x"], search_results=ROWS[:2], llm_response=json.dumps(llm),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        self.assertEqual([theme["theme_id"] for theme in packet["themes"]], ["good_theme"])
        self.assertIn("invalid_theme_dropped", [row["reason"] for row in receipt["drop_ledger"]])

    def test_raw_receipt_is_content_hashed_and_never_contains_key(self):
        with temporary_provider_directory(fetch.ROOT) as td:
            root = Path(td) / "web"
            _, receipt, _ = fetch.build_web_fetch_packet(
                queries=["x"], search_results=ROWS[:2], llm_response=self._llm(),
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=root, persist_raw=True,
            )
            ref = receipt["source_refs"][0]
            raw = fetch._raw_receipt_path(root, ref["source_id"], "20260725").read_text(encoding="utf-8")
            self.assertEqual(fetch._sha256_bytes(fetch._canonical_json(json.loads(raw))), ref["content_sha256"])
            self.assertNotIn("api_key", raw.lower())

    def test_malformed_provider_and_llm_fields_are_dropped_not_raised(self):
        good_url = "https://example.com/good"
        good_ref = fetch._source_id(good_url)
        rows = [
            {"url": "http://e.com:99999/x", "title": "bad", "content": "bad", "published_date": "2026-07-24T10:00:00Z"},
            {"url": good_url, "title": "good", "content": "AAPL", "published_date": "2026-07-24T10:00:00Z"},
        ]
        llm = {"themes": [
            {"theme_id": "bad_refs", "display_name": "Bad", "summary": "Bad", "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": 7, "members": []},
            {"theme_id": "good_theme", "display_name": "Good", "summary": "Good", "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": [good_ref], "members": [{"ticker": "AAPL", "source_ref_ids": 9}]},
        ]}
        artifact, receipt, _ = fetch.build_web_fetch_packet(
            queries=["q"], search_results=rows, llm_response=json.dumps(llm),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        self.assertEqual(artifact["themes"], [])
        self.assertTrue(any(row["reason"] == "malformed_theme_source_refs" for row in receipt["drop_ledger"]))
        self.assertTrue(any(row["reason"] == "malformed_member_source_refs" for row in receipt["drop_ledger"]))

    def test_poisoned_provider_text_drops_one_item_and_keeps_good_sibling(self):
        """A lone UTF-8 surrogate is provider data, never a whole-batch publication error."""
        poisoned = {
            "url": "https://example.com/poisoned", "title": "bad\ud800",
            "content": "AAPL", "published_date": "2026-07-24T10:00:00Z",
        }
        _, receipt, _ = fetch.build_web_fetch_packet(
            queries=["q"], search_results=[ROWS[0], poisoned], llm_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        self.assertEqual(receipt["summary"]["accepted_source_count"], 1)
        self.assertIn("missing_title_or_content", [row["reason"] for row in receipt["drop_ledger"]])
        json.dumps(receipt, ensure_ascii=False).encode("utf-8")

    def test_generic_item_exception_boundary_is_load_bearing(self):
        """Removing `_ingest_provider_item`'s catch-all turns one bad provider row into a batch failure."""
        class ExplodingText:
            def __str__(self):
                raise RuntimeError("provider-controlled string conversion failed")
        poisoned = {
            "url": "https://example.com/explodes", "title": ExplodingText(),
            "content": "AAPL", "published_date": "2026-07-24T10:00:00Z",
        }
        _, receipt, _ = fetch.build_web_fetch_packet(
            queries=["q"], search_results=[ROWS[0], poisoned], llm_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        self.assertEqual(receipt["summary"]["accepted_source_count"], 1)
        self.assertIn("provider_item_exception_dropped", [row["reason"] for row in receipt["drop_ledger"]])

    def test_path_query_schema_and_fetch_clock_guards_are_live(self):
        with self.assertRaises(fetch.WebThemeDiscoveryError):
            fetch._validate_output_path(fetch.ROOT / "runners" / "bad.json")
        with self.assertRaises(fetch.WebThemeDiscoveryError):
            fetch._validate_raw_root(fetch.ROOT / "runners", require_gitignored=True)
        with self.assertRaises(fetch.WebThemeDiscoveryError):
            fetch._safe_queries(["api_key=secret"])
        with self.assertRaises(fetch.WebThemeDiscoveryError):
            fetch._safe_queries(["q"] * (fetch.MAX_TAVILY_QUERIES + 1))
        with self.assertRaises(fetch.WebThemeDiscoveryError):
            fetch.build_web_fetch_packet(queries=["q"], search_results=[], llm_response='{"themes":[]}', expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", fetched_at="2099-01-01T00:00:00Z")

    def test_raw_receipt_conflict_drops_only_changed_source_and_keeps_sibling(self):
        with temporary_provider_directory(fetch.ROOT) as td:
            root = Path(td) / "retry"
            kwargs = dict(queries=["q"], expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", raw_root=root, persist_raw=True)
            fetch.build_web_fetch_packet(search_results=ROWS[:2], llm_response='{"themes":[]}', **kwargs)
            _, receipt, _ = fetch.build_web_fetch_packet(
                search_results=[dict(ROWS[0], content="changed"), ROWS[1]], llm_response='{"themes":[]}', **kwargs)
            self.assertEqual(receipt["summary"]["accepted_source_count"], 1)
            self.assertIn("immutable_raw_content_conflict", [row["reason"] for row in receipt["drop_ledger"]])

    def test_bad_decision_date_and_publish_target_fail_before_live_work(self):
        with temporary_provider_directory(fetch.ROOT) as td:
            with mock.patch.object(fetch, "STATE_DIR", Path(td)):
                for malformed in ("2026-08-10", "20260810x", "not-a-date"):
                    with self.subTest(date=malformed), self.assertRaises(fetch.WebThemeDiscoveryError):
                        fetch._reserve_provider_budget("web", "tavily", malformed, call_count=1, query_scope=["q"])
                budget = Path(td) / "us_short_llm_theme_discovery_web_tavily_20260810_budget.json"
                with self.assertRaises(fetch.WebThemeDiscoveryError):
                    fetch._validate_publish_path(budget, fetch.default_discovery_path("20260810"))
        with mock.patch.object(fetch, "run_web_fetch") as run:
            with self.assertRaises(fetch.WebThemeDiscoveryError):
                fetch.main(["--query", "q", "--expected-decision-date", "20260810", "--generated-at", "2026-08-10T08:00:00Z", "--output-path", str(fetch.ROOT / "docs" / "bad.json")])
            run.assert_not_called()

    def test_packet_order_and_drop_ledger_are_deterministic(self):
        kwargs = dict(queries=["q"], llm_response=self._llm(), expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        first, first_receipt, _ = fetch.build_web_fetch_packet(search_results=ROWS, **kwargs)
        second, second_receipt, _ = fetch.build_web_fetch_packet(search_results=list(reversed(ROWS)), **kwargs)
        self.assertEqual(first, second)
        self.assertEqual(first_receipt["source_refs"], second_receipt["source_refs"])
        self.assertEqual(first_receipt["drop_ledger"], second_receipt["drop_ledger"])

    def test_raw_batch_failure_removes_its_partial_new_evidence(self):
        with temporary_provider_directory(fetch.ROOT) as td:
            root = Path(td) / "batch"
            pending = [(root / "raw" / "a.json", {"a": 1}), (root / "raw" / "b.json", {"b": 2})]
            real_write = fetch._write_json_atomic
            # The batch now publishes through the lane's single write door, so the failure is
            # injected at that door: the second final-name creation fails after both are staged.
            from runners import us_short_discovery_publish_policy as policy
            calls = 0
            real_link = policy.os.link

            def fail_second_link(source, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("forced second link failure")
                real_link(source, target)

            with mock.patch.object(policy.os, "link", side_effect=fail_second_link):
                with self.assertRaises(fetch.WebThemeDiscoveryError):
                    fetch._flush_raw_writes(pending)
            self.assertFalse((root / "raw" / "a.json").exists())
            self.assertFalse((root / "raw" / "b.json").exists())

    def test_public_packet_pair_rolls_back_if_second_publish_fails(self):
        with tempfile.TemporaryDirectory(dir=fetch.STATE_DIR) as td:
            first = Path(td) / "discovery.json"
            second = Path(td) / "receipt.json"
            real_link = fetch.os.link
            calls = 0
            def fail_second_link(path, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("forced second publish failure")
                return real_link(path, target)
            with mock.patch.object(fetch.os, "link", new=fail_second_link):
                with self.assertRaises(fetch.WebThemeDiscoveryError):
                    fetch._write_json_pair_atomic({"artifact": 1}, first, {"receipt": 1}, second)
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())

    def test_identical_later_refetch_is_idempotent_and_budget_is_per_decision_date(self):
        with temporary_provider_directory(fetch.ROOT) as td:
            root = Path(td) / "retry"
            base = dict(queries=["q"], search_results=[ROWS[0]], llm_response='{"themes":[]}', expected_decision_date="20260725", raw_root=root, persist_raw=True)
            _, first, _ = fetch.build_web_fetch_packet(generated_at="2026-07-25T07:00:00Z", fetched_at="2026-07-25T07:00:00Z", **base)
            _, second, _ = fetch.build_web_fetch_packet(generated_at="2026-07-25T08:00:00Z", fetched_at="2026-07-25T08:00:00Z", **base)
            self.assertNotEqual(first["source_refs"][0]["fetched_at"], second["source_refs"][0]["fetched_at"])
            self.assertEqual(first["source_refs"][0]["content_sha256"], second["source_refs"][0]["content_sha256"])
        with tempfile.TemporaryDirectory(dir=fetch.STATE_DIR) as td:
            original_state = fetch.STATE_DIR
            try:
                fetch.STATE_DIR = Path(td)
                self.assertTrue(fetch._gitignored(original_state / "us_short_llm_theme_discovery_web_tavily_20260725_budget.json"))
                with mock.patch.object(fetch, "_gitignored", return_value=True):
                    fetch._reserve_provider_budget("web", "tavily", "20260725", call_count=1, query_scope=["q"])
                    fetch._reserve_provider_budget("web", "tavily", "20260726", call_count=1, query_scope=["q"])
                self.assertTrue((Path(td) / "us_short_llm_theme_discovery_web_tavily_20260725_budget.json").exists())
                self.assertTrue((Path(td) / "us_short_llm_theme_discovery_web_tavily_20260726_budget.json").exists())
            finally:
                fetch.STATE_DIR = original_state

    def test_raw_receipt_is_not_written_before_receipt_schema_passes(self):
        with temporary_provider_directory(fetch.ROOT) as td:
            root = Path(td) / "schema_gate"
            with mock.patch.object(fetch, "_validate_schema", side_effect=fetch.WebThemeDiscoveryError("forced schema failure")):
                with self.assertRaises(fetch.WebThemeDiscoveryError):
                    fetch.build_web_fetch_packet(
                        queries=["q"], search_results=ROWS[:1], llm_response='{"themes":[]}',
                        expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", raw_root=root, persist_raw=True,
                    )
            self.assertFalse(root.exists())

    def test_gitignore_gate_cannot_be_bypassed(self):
        with temporary_provider_directory(fetch.ROOT) as td:
            with mock.patch.object(fetch, "_gitignored", return_value=False):
                with self.assertRaises(fetch.WebThemeDiscoveryError):
                    fetch.build_web_fetch_packet(
                        queries=["q"], search_results=ROWS[:1], llm_response='{"themes":[]}',
                        expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                        raw_root=Path(td) / "blocked", persist_raw=True,
                    )

    def test_secret_like_locator_is_never_echoed_into_the_receipt(self):
        leaky = {**ROWS[0], "url": "https://evil.example/cb?api_key=sk-live-TESTFAKE123456"}
        _, receipt, _ = fetch.build_web_fetch_packet(
            queries=["power"], search_results=[ROWS[0], leaky], llm_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        blob = json.dumps(receipt, ensure_ascii=False)
        self.assertNotIn("sk-live-TESTFAKE123456", blob)
        self.assertNotIn("api_key", blob)
        self.assertTrue(any(row["reason"] == "invalid_canonical_locator" for row in receipt["drop_ledger"]))

    def test_receipt_schema_gate_is_load_bearing(self):
        """`_validate_schema` is the only thing enforcing the receipt's own invariants (query cap,
        const-false effect flags, raw-ref shape), so it needs a test that dies with it."""
        receipt = {
            "schema_name": "us_short_llm_theme_discovery_fetch_web", "schema_version": "1.0.0",
            "generated_at": "2026-07-25T08:00:00Z",
            "decision_clock": {"expected_decision_date": "20260725", "cutoff_policy": "before_decision_open_et", "pit_enforced": True},
            "fetch_contract": {
                "producer_kind": "tavily_deepseek_web_fetch", "execution_mode": "offline_fake_client",
                "network_access_performed": False, "provider_calls_performed": False,
                "network_call_count": 0, "provider_call_count": 0,
                "scoring_eligible": True,      # must be const false
                "top15_effect_enabled": False, "operation_advice_effect_enabled": False,
                "dynamic_seats_enabled": False, "theme_probe_enabled": False, "lifecycle_actions_enabled": False,
            },
            "queries": ["q"], "source_refs": [], "discovery_artifact_sha256": "a" * 64,
            "drop_ledger": [], "raw_receipts_written": False,
            "summary": {"query_count": 1, "accepted_source_count": 0, "validated_theme_count": 0,
                        "validated_member_count": 0, "dropped_result_count": 0, "prompt_source_count": 0},
        }
        with self.assertRaises(fetch.WebThemeDiscoveryError):
            fetch._validate_schema(receipt)

    def test_gitignored_answers_the_repository_not_a_constant(self):
        """The whole private-evidence guarantee rests on `_gitignored`. Pin its own behaviour: a
        constant-True stub (or a `provider_samples/` that stopped being ignored) must fail here."""
        self.assertTrue(fetch._gitignored(fetch.DEFAULT_RAW_ROOT / "raw" / "probe.json"))
        self.assertTrue(fetch._gitignored(fetch.STATE_DIR / "probe.json"))
        self.assertFalse(fetch._gitignored(fetch.ROOT / "docs" / "probe_not_ignored.json"))
        self.assertFalse(fetch._gitignored(fetch.ROOT / "runners" / "probe_not_ignored.json"))

    def test_atomic_writer_loses_a_race_without_overwriting_or_temp_residue(self):
        with temporary_provider_directory(fetch.ROOT) as td:
            path = Path(td) / "state" / "us_short" / "race.json"
            payload = {"evidence": "frozen"}
            fetch._write_json_atomic(payload, path)
            frozen = path.read_bytes()
            with self.assertRaises(fetch.WebThemeDiscoveryError):
                fetch._write_json_atomic({"evidence": "changed"}, path)
            self.assertEqual(path.read_bytes(), frozen)
            race_path = Path(td) / "state" / "us_short" / "lost-race.json"
            with (
                mock.patch.object(fetch, "_existing_packet_matches", side_effect=(False, True)),
                mock.patch.object(fetch.os, "link", side_effect=FileExistsError),
            ):
                fetch._write_json_atomic(payload, race_path)
            self.assertFalse(race_path.exists())
            self.assertEqual(list(race_path.parent.glob("*.tmp")), [])

    def test_receipt_secret_backstop_fires_when_sanitizing_is_bypassed(self):
        leaky = {**ROWS[0], "url": "https://evil.example/cb?api_key=sk-live-TESTFAKE123456"}
        with mock.patch.object(fetch, "_sanitized_drop_ledger", side_effect=lambda rows: list(rows)):
            with self.assertRaises(fetch.WebThemeDiscoveryError):
                fetch.build_web_fetch_packet(
                    queries=["power"], search_results=[ROWS[0], leaky], llm_response='{"themes":[]}',
                    expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                )

    def test_live_budget_is_capped_and_lets_a_second_query_set_spend_the_rest(self):
        # A test must never reserve against the operator's real state/us_short.
        with temporary_provider_directory(fetch.ROOT) as td:
            with mock.patch.object(fetch, "STATE_DIR", Path(td)):
                fetch._reserve_provider_budget("web", "tavily", "20260726", call_count=20, query_scope=[f"a{i}" for i in range(20)])
                fetch._reserve_provider_budget("web", "tavily", "20260726", call_count=5, query_scope=[f"b{i}" for i in range(5)])
                with self.assertRaises(fetch.WebThemeDiscoveryError):
                    fetch._reserve_provider_budget("web", "tavily", "20260726", call_count=1, query_scope=["c"])

    def test_provider_budgets_are_separate(self):
        """The frozen runner cannot spend; direct ledger checks retain the provider-cap invariant."""
        with temporary_provider_directory(fetch.ROOT) as td:
            root = Path(td)
            with mock.patch.object(fetch, "STATE_DIR", root):
                fetch._reserve_provider_budget("web", "tavily", "20260726", call_count=2, query_scope=["q1", "q2"])
                ledger = json.loads((root / "us_short_llm_theme_discovery_web_tavily_20260726_budget.json").read_text(encoding="utf-8"))
                self.assertEqual(ledger["planned_provider_call_count"], 2)
                self.assertFalse((root / "us_short_llm_theme_discovery_web_deepseek_20260726_budget.json").exists())
                fetch._reserve_provider_budget("web", "deepseek", "20260726", call_count=1, query_scope=["q1", "q2"])
                deepseek = json.loads((root / "us_short_llm_theme_discovery_web_deepseek_20260726_budget.json").read_text(encoding="utf-8"))
                self.assertEqual(deepseek["planned_provider_call_count"], 1)

    def test_secret_like_path_is_sanitized_without_poisoning_receipt_backstop(self):
        bad_path = {**ROWS[0], "url": "https://evil.example/password/reset"}
        _, receipt, _ = fetch.build_web_fetch_packet(
            queries=["power"], search_results=[ROWS[0], bad_path], llm_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        blob = json.dumps(receipt, ensure_ascii=False)
        self.assertEqual(receipt["summary"]["accepted_source_count"], 1)
        self.assertNotIn("password", blob.lower())
        self.assertIn("redacted_untrusted_detail", [row["detail"] for row in receipt["drop_ledger"]])

    def test_cli_publishes_one_slot_per_decision_date(self):
        with temporary_provider_directory(fetch.ROOT) as state:
            with tempfile.TemporaryDirectory() as td:
                results = Path(td) / "results.json"
                llm = Path(td) / "llm.json"
                results.write_text(json.dumps(ROWS[:1]), encoding="utf-8")
                llm.write_text(json.dumps(json.dumps({"themes": []})), encoding="utf-8")
                published = []
                with mock.patch.object(fetch, "STATE_DIR", Path(state)):
                    for date_ in ("20260726", "20260727"):
                        self.assertEqual(fetch.main([
                            "--query", "power", "--expected-decision-date", date_,
                            "--generated-at", "2026-07-25T08:00:00Z",
                            "--fake-results-path", str(results), "--fake-llm-response-path", str(llm),
                        ]), 0)
                        out = fetch.default_discovery_path(date_)
                        receipt = fetch.default_receipt_path(date_)
                        published.extend([out, receipt])
                        self.assertTrue(out.is_file() and receipt.is_file())
                self.assertEqual(len({p.name for p in published}), 4)

    def test_canonical_locator_collapses_equivalent_spellings(self):
        """Two spellings of ONE document must mint ONE source ID: the merge treats `sha256(locator)` as a
        document identity, so a host-case / trailing-slash / default-port / permuted-parameter variant
        would otherwise read as independent corroboration and earn the 5-point `both` tier.
        """
        canonical = "https://web.example/story"
        for variant in ("https://WEB.Example/story/", "https://web.example/story/",
                        "https://web.example:443/story", "HTTPS://web.example/story"):
            with self.subTest(variant=variant):
                self.assertEqual(fetch._canonical_locator(variant), canonical)
        self.assertEqual(fetch._canonical_locator("https://web.example/s?b=2&a=1"),
                         fetch._canonical_locator("https://web.example/s?a=1&b=2"))
        # `;` is a legacy pair separator and the credential policy already treats it as one, so order
        # must be normalized under BOTH separators or one article still mints two identities.
        self.assertEqual(fetch._canonical_locator("https://web.example/s?b=2;a=1"),
                         fetch._canonical_locator("https://web.example/s?a=1;b=2"))
        self.assertEqual(fetch._canonical_locator("https://web.example/s?c=3&b=2;a=1"),
                         "https://web.example/s?a=1;b=2&c=3")
        for first, second, expected in (
            ("https://web.example/a%2fb", "https://web.example/a%2Fb", "https://web.example/a%2Fb"),
            ("https://web.example/a/./story", "https://web.example/a/story", "https://web.example/a/story"),
            ("https://web.example/a/b/../story", "https://web.example/a/story", "https://web.example/a/story"),
            ("https://web.example/s?q=a%2fb", "https://web.example/s?q=a%2Fb", "https://web.example/s?q=a%2Fb"),
        ):
            with self.subTest(first=first, second=second):
                self.assertEqual(fetch._canonical_locator(first), expected)
                self.assertEqual(fetch._canonical_locator(second), expected)
                self.assertEqual(fetch._source_id(fetch._canonical_locator(first)),
                                 fetch._source_id(fetch._canonical_locator(second)))
        # A `;` that is an ordinary VALUE character must stay byte-identical: no separator rewrite.
        for literal in ("https://web.example/s?filter=a;b", "https://web.example/s?tag=x;y;z"):
            with self.subTest(literal=literal):
                self.assertEqual(fetch._canonical_locator(literal), literal)
        # Merge requires idempotence to trust the receipt's locator, so pin it here too.
        self.assertEqual(fetch._canonical_locator(canonical), canonical)
        for stable in ("https://web.example/s?a=1&b=2", "https://web.example/s?a=1;b=2&c=3"):
            with self.subTest(stable=stable):
                self.assertEqual(fetch._canonical_locator(stable), stable)
        self.assertIsNone(fetch._canonical_locator("https://web.example/a b"))
        self.assertIsNone(fetch._canonical_locator("https://web.example/a\u00a0b"))

    def test_locator_property_is_idempotent_across_generated_url_shapes(self):
        """Every accepted provider locator remains canonical when normalized again."""
        for base in (
            "https://WEB.example:443/story/", "http://WEB.example:80/story/",
            "https://[2001:DB8::1]:443/story/", "http://[2001:DB8::2]:80/story/",
        ):
            for query in ("", "?b=2&a=1", "?b=2;a=1", "?filter=a;b"):
                with self.subTest(locator=base + query):
                    canonical = fetch._canonical_locator(base + query)
                    self.assertIsNotNone(canonical)
                    self.assertEqual(fetch._canonical_locator(canonical), canonical)

    def test_provider_row_property_a_poisoned_row_never_kills_good_web_evidence(self):
        poisons = (
            {"url": "https://web.example/extreme", "title": "bad", "content": "bad", "published_date": "0001-01-01T00:00:00+23:00"},
            {"url": "https://web.example/a b", "title": "bad", "content": "bad", "published_date": "2026-07-24T10:00:00Z"},
            {"url": "https://web.example/missing", "title": "", "content": "bad", "published_date": "2026-07-24T10:00:00Z"},
            7,
        )
        for poison in poisons:
            with self.subTest(poison=type(poison).__name__):
                _, receipt, _ = fetch.build_web_fetch_packet(
                    queries=["q"], search_results=[ROWS[0], poison], llm_response='{"themes":[]}',
                    expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                )
                self.assertEqual(receipt["summary"]["accepted_source_count"], 1)
                self.assertTrue(receipt["drop_ledger"])

    def test_retry_publish_property_same_evidence_different_clocks_is_idempotent(self):
        kwargs = dict(queries=["q"], search_results=ROWS[:1], llm_response='{"themes":[]}', expected_decision_date="20260725")
        first, first_receipt, _ = fetch.build_web_fetch_packet(
            generated_at="2026-07-25T07:00:00Z", fetched_at="2026-07-25T07:00:00Z", **kwargs,
        )
        second, second_receipt, _ = fetch.build_web_fetch_packet(
            generated_at="2026-07-25T08:00:00Z", fetched_at="2026-07-25T08:00:00Z", **kwargs,
        )
        self.assertEqual(first_receipt["discovery_artifact_sha256"], second_receipt["discovery_artifact_sha256"])
        with temporary_provider_directory(fetch.ROOT) as td:
            with mock.patch.object(fetch, "STATE_DIR", Path(td)):
                output = fetch.default_discovery_path("20260725")
                receipt_path = fetch.default_receipt_path("20260725")
                fetch.publish_decision_pair(first, output, output, first_receipt, receipt_path, receipt_path)
                bytes_before = (output.read_bytes(), receipt_path.read_bytes())
                fetch.publish_decision_pair(second, output, output, second_receipt, receipt_path, receipt_path)
                self.assertEqual((output.read_bytes(), receipt_path.read_bytes()), bytes_before)

    def test_generic_credential_query_locators_are_rejected_structurally(self):
        """`SECRET_RE` only knows `api_key`-shaped words, so a provider-supplied signed URL using a
        GENERIC parameter (`?token=`, `?sig=`, `?auth=`) was canonicalized and persisted verbatim. The
        policy is on the parsed query KEY, so a benign query (`?author=`, `?page=`) must still survive.
        """
        for query in ("token=REVIEW_FAKE_TOKEN_123", "sig=REVIEW_FAKE_SIG", "auth=REVIEW_FAKE_AUTH",
                      "Session_Id=REVIEW_FAKE_SESSION", "apikey=REVIEW_FAKE_KEY", "page=2;token=REVIEW_FAKE_TOKEN"):
            with self.subTest(query=query):
                self.assertIsNone(fetch._canonical_locator(f"https://evil.example/cb?{query}"))
        self.assertEqual(
            fetch._canonical_locator("https://news.example/story?author=jane&page=2"),
            "https://news.example/story?author=jane&page=2",
        )
        leaky = {**ROWS[0], "url": "https://evil.example/cb?token=REVIEW_FAKE_TOKEN_123"}
        _, receipt, _ = fetch.build_web_fetch_packet(
            queries=["power"], search_results=[ROWS[0], leaky], llm_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        blob = json.dumps(receipt, ensure_ascii=False)
        self.assertNotIn("REVIEW_FAKE_TOKEN_123", blob)
        self.assertNotIn("token=", blob)
        self.assertEqual(receipt["summary"]["accepted_source_count"], 1)
        self.assertTrue(any(row["reason"] == "invalid_canonical_locator" for row in receipt["drop_ledger"]))
        # Backstop must be independent of the locator gate: hand-inject and it still refuses to persist.
        with self.assertRaises(fetch.WebThemeDiscoveryError):
            fetch._assert_receipt_secret_free({"note": "https://evil.example/cb?token=REVIEW_FAKE_TOKEN_123"})
        # Ledger sink: scheme-less locator text never reached the query-stripping branch.
        self.assertNotIn("REVIEW_FAKE_TOKEN_123", fetch._ledger_safe_detail("evil.example/cb?token=REVIEW_FAKE_TOKEN_123"))

    def test_future_dated_fetch_clock_is_rejected_on_its_own_branch(self):
        """The existing clock test trips the `fetched > generated` branch first, so the future-dating
        branch was never reached. Here both are in the future and only that branch can fire."""
        future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        with self.assertRaises(fetch.WebThemeDiscoveryError):
            fetch._validate_fetch_clock(future, future)


if __name__ == "__main__":
    unittest.main()
