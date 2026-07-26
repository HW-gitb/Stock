from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from runners import us_short_llm_theme_discovery_merge as merge
from runners.us_short_llm_theme_discovery_merge import ThemeDiscoveryMergeError, merge_web_x_discovery
from runners import us_short_llm_theme_discovery_fetch_web as web


X_ROWS = [
    {"url": "https://x.example/post/1", "title": "Power post", "text": "AAPL and CEG power demand", "created_at": "2026-07-24T11:00:00Z"},
    {"url": "https://x.example/post/2", "title": "Utility post", "text": "VST generation buildout", "created_at": "2026-07-23T11:00:00Z"},
]


class XFetchAndMergeTests(unittest.TestCase):
    def _x_response(self):
        refs = [xfetch._source_id(row["url"]) for row in X_ROWS]
        return json.dumps({"themes": [{"theme_id": "power_demand", "display_name": "Power demand", "summary": "Power demand", "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": refs, "members": [{"ticker": "AAPL", "source_ref_ids": refs}, {"ticker": "CEG", "source_ref_ids": refs}, {"ticker": "VST", "source_ref_ids": refs}]}]})

    def test_x_fake_client_is_offline_and_pit_bound(self):
        discovery, receipt, summary = xfetch.build_x_fetch_packet(
            queries=["power"], results=X_ROWS, grok_response=self._x_response(),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        self.assertEqual(receipt["fetch_contract"]["execution_mode"], "offline_fake_client")
        self.assertFalse(receipt["fetch_contract"]["network_access_performed"])
        self.assertEqual(len(discovery["themes"]), 1)
        self.assertEqual(summary["accepted_source_count"], 2)

    def test_x_live_freeze_blocks_before_client_key_or_reservation(self):
        """K3-R34 covers X separately: no client construction, key read, or spend reservation."""
        with (
            mock.patch.object(xfetch, "GrokXSearchClient") as client,
            mock.patch.object(web, "_reserve_provider_budget") as reserve,
            mock.patch.object(xfetch.os.environ, "get", side_effect=AssertionError("key lookup reached")) as key_lookup,
        ):
            with self.assertRaisesRegex(xfetch.XThemeDiscoveryError, "live execution is frozen"):
                xfetch.run_x_fetch(
                    queries=["power"], expected_decision_date="20260725",
                    generated_at="2026-07-25T08:00:00Z", confirm_user_authorization=True, live=True,
                )
        client.assert_not_called()
        reserve.assert_not_called()
        key_lookup.assert_not_called()

    def test_bad_grok_response_is_dropped_per_query(self):
        good = self._x_response()
        class Fake:
            results = X_ROWS
            def __init__(self): self.calls = 0
            def search(self, query, expected):
                self.calls += 1
                return "not-json" if self.calls == 1 else good
        discovery, receipt, _ = xfetch.run_x_fetch(queries=["q1", "q2"], expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", x_client=Fake())
        self.assertEqual(len(discovery["themes"]), 1)
        self.assertTrue(any(row["reason"] == "invalid_response_dropped" for row in receipt["drop_ledger"]))

    def test_x_guards_and_direct_live_builder_gate(self):
        with self.assertRaises(xfetch.XThemeDiscoveryError):
            xfetch._safe_queries(["secret=api_key"])
        with self.assertRaises(xfetch.XThemeDiscoveryError):
            xfetch._safe_queries(["q"] * (xfetch.MAX_X_QUERIES + 1))
        with self.assertRaises(xfetch.XThemeDiscoveryError):
            xfetch.build_x_fetch_packet(queries=["q"], results=[], grok_response='{"themes":[]}', expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", execution_mode="live_authorized")

    def test_x_whitespace_url_and_raw_conflict_drop_per_item(self):
        bad = {**X_ROWS[0], "url": "https://x.example/a b"}
        _, receipt, _ = xfetch.build_x_fetch_packet(
            queries=["q"], results=[bad, X_ROWS[1]], grok_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        self.assertEqual(receipt["summary"]["accepted_source_count"], 1)
        self.assertIn("invalid_canonical_locator", [row["reason"] for row in receipt["drop_ledger"]])
        with tempfile.TemporaryDirectory(dir=web.ROOT / "provider_samples") as td:
            root = Path(td) / "x"
            kwargs = dict(queries=["q"], grok_response='{"themes":[]}', expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", raw_root=root, persist_raw=True)
            xfetch.build_x_fetch_packet(results=X_ROWS, **kwargs)
            _, retried, _ = xfetch.build_x_fetch_packet(results=[dict(X_ROWS[0], text="changed"), X_ROWS[1]], **kwargs)
        self.assertEqual(retried["summary"]["accepted_source_count"], 1)
        self.assertIn("immutable_raw_content_conflict", [row["reason"] for row in retried["drop_ledger"]])

    def test_x_poisoned_text_drops_one_item_and_keeps_good_sibling(self):
        poisoned = {**X_ROWS[0], "url": "https://x.example/poisoned", "text": "bad\ud800"}
        _, receipt, _ = xfetch.build_x_fetch_packet(
            queries=["q"], results=[X_ROWS[1], poisoned], grok_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        self.assertEqual(receipt["summary"]["accepted_source_count"], 1)
        self.assertIn("missing_post_text", [row["reason"] for row in receipt["drop_ledger"]])
        json.dumps(receipt, ensure_ascii=False).encode("utf-8")

    def test_x_generic_item_exception_boundary_is_load_bearing(self):
        """X uses the same catch-all boundary and needs its own deletion latch."""
        class ExplodingText:
            def __str__(self):
                raise RuntimeError("provider-controlled string conversion failed")
        poisoned = {**X_ROWS[0], "url": "https://x.example/explodes", "title": ExplodingText()}
        _, receipt, _ = xfetch.build_x_fetch_packet(
            queries=["q"], results=[X_ROWS[1], poisoned], grok_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        self.assertEqual(receipt["summary"]["accepted_source_count"], 1)
        self.assertIn("provider_item_exception_dropped", [row["reason"] for row in receipt["drop_ledger"]])

    def test_x_model_shape_property_drops_bad_query_or_theme_without_batch_failure(self):
        good = self._x_response()
        bad_members = json.dumps({
            "sources": [],
            "themes": [
                {"theme_id": "bad", "display_name": "Bad", "summary": "Bad", "observed_at": "2026-07-24T12:00:00Z", "members": 5},
                {"theme_id": "power_demand", "display_name": "Power", "summary": "Power", "observed_at": "2026-07-24T12:00:00Z", "members": []},
            ],
        })
        class Replies:
            results = X_ROWS
            def __init__(self): self.calls = 0
            def search(self, query, expected):
                self.calls += 1
                return '{"sources":5,"themes":[]}' if self.calls == 1 else (bad_members if self.calls == 2 else good)
        discovery, receipt, _ = xfetch.run_x_fetch(
            queries=["q1", "q2", "q3"], expected_decision_date="20260725",
            generated_at="2026-07-25T08:00:00Z", x_client=Replies(),
        )
        self.assertEqual([theme["theme_id"] for theme in discovery["themes"]], ["power_demand"])
        reasons = [row["reason"] for row in receipt["drop_ledger"]]
        self.assertIn("ignored_malformed_top_level_field", reasons)
        self.assertIn("malformed_theme_members", reasons)

    def test_x_model_top_level_superset_keeps_themes_and_ledgers_ignored_keys(self):
        payload = json.loads(self._x_response())
        payload.update({"notes": "benign commentary", "confidence": 0.8})
        class ExtraKeys:
            results = X_ROWS
            def search(self, query, expected):
                return json.dumps(payload)
        discovery, receipt, _ = xfetch.run_x_fetch(
            queries=["q"], expected_decision_date="20260725",
            generated_at="2026-07-25T08:00:00Z", x_client=ExtraKeys(),
        )
        self.assertEqual([theme["theme_id"] for theme in discovery["themes"]], ["power_demand"])
        ignored = [row for row in receipt["drop_ledger"] if row["reason"] == "ignored_top_level_keys"]
        self.assertEqual([row["detail"] for row in ignored], ["confidence,notes"])

    def test_x_model_malformed_auxiliary_sources_never_discards_good_themes(self):
        for malformed_sources in ("see above", {}, 0, False, None):
            with self.subTest(sources_type=type(malformed_sources).__name__):
                payload = json.loads(self._x_response())
                payload["sources"] = malformed_sources
                discovery, receipt, _ = xfetch.build_x_fetch_packet(
                    queries=["q"], results=X_ROWS, grok_response=json.dumps(payload),
                    expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                )
                self.assertEqual([theme["theme_id"] for theme in discovery["themes"]], ["power_demand"])
                self.assertIn(
                    {"stage": "llm", "reason": "ignored_malformed_top_level_field",
                     "detail": f"sources:{type(malformed_sources).__name__}"},
                    receipt["drop_ledger"],
                )

    def test_x_model_top_level_without_theme_list_still_fails_closed(self):
        for payload in ({}, {"notes": "only"}, {"themes": None}, {"themes": {}}, {"themes": "bad"}):
            with self.subTest(payload=payload):
                discovery, receipt, _ = xfetch.build_x_fetch_packet(
                    queries=["q"], results=X_ROWS, grok_response=json.dumps(payload),
                    expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                )
                self.assertEqual(discovery["themes"], [])
                self.assertIn("invalid_or_unusable_response", [row["reason"] for row in receipt["drop_ledger"]])

    def test_x_provider_row_property_a_poisoned_row_never_kills_good_evidence(self):
        poisons = (
            {"url": "https://x.example/extreme", "title": "bad", "text": "bad", "created_at": "0001-01-01T00:00:00+23:00"},
            {"url": "https://x.example/a b", "title": "bad", "text": "bad", "created_at": "2026-07-24T10:00:00Z"},
            {"url": "https://x.example/no-text", "title": "bad", "text": "", "created_at": "2026-07-24T10:00:00Z"},
            7,
        )
        for poison in poisons:
            with self.subTest(poison=type(poison).__name__):
                _, receipt, _ = xfetch.build_x_fetch_packet(
                    queries=["q"], results=[X_ROWS[0], poison], grok_response='{"themes":[]}',
                    expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                )
                self.assertEqual(receipt["summary"]["accepted_source_count"], 1)
                self.assertTrue(receipt["drop_ledger"])

    def test_x_retry_publish_property_same_evidence_different_clocks_is_idempotent(self):
        kwargs = dict(queries=["q"], results=X_ROWS[:1], grok_response='{"themes":[]}', expected_decision_date="20260725")
        first, first_receipt, _ = xfetch.build_x_fetch_packet(
            generated_at="2026-07-25T07:00:00Z", fetched_at="2026-07-25T07:00:00Z", **kwargs,
        )
        second, second_receipt, _ = xfetch.build_x_fetch_packet(
            generated_at="2026-07-25T08:00:00Z", fetched_at="2026-07-25T08:00:00Z", **kwargs,
        )
        self.assertEqual(first_receipt["discovery_artifact_sha256"], second_receipt["discovery_artifact_sha256"])
        with tempfile.TemporaryDirectory(dir=web.ROOT / "provider_samples") as td:
            with mock.patch.object(web, "STATE_DIR", Path(td)), mock.patch.object(xfetch, "STATE_DIR", Path(td)):
                output = xfetch.default_discovery_path("20260725")
                receipt_path = xfetch.default_receipt_path("20260725")
                web.publish_decision_pair(first, output, output, first_receipt, receipt_path, receipt_path)
                before = (output.read_bytes(), receipt_path.read_bytes())
                web.publish_decision_pair(second, output, output, second_receipt, receipt_path, receipt_path)
                self.assertEqual((output.read_bytes(), receipt_path.read_bytes()), before)

    def test_grok_sources_are_receipted_and_url_refs_are_coerced(self):
        response = json.dumps({
            "sources": [{"url": X_ROWS[0]["url"], "title": X_ROWS[0]["title"], "text": X_ROWS[0]["text"], "created_at": X_ROWS[0]["created_at"]}],
            "themes": [{"theme_id": "power_demand", "display_name": "Power demand", "summary": "Power demand", "observed_at": "2026-07-24T12:00:00Z", "source_urls": [X_ROWS[0]["url"]], "members": [{"ticker": "AAPL", "source_urls": [X_ROWS[0]["url"]]}]}],
        })
        discovery, receipt, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=X_ROWS[:1], grok_response=response,
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        self.assertEqual(receipt["summary"]["accepted_source_count"], 1)
        self.assertEqual(discovery["themes"][0]["source_ref_ids"], [xfetch._source_id(X_ROWS[0]["url"])])
        self.assertEqual(discovery["themes"][0]["members"][0]["source_ref_ids"], [xfetch._source_id(X_ROWS[0]["url"])])

    def test_model_claimed_sources_without_provider_rows_are_not_evidence(self):
        response = json.dumps({
            "sources": [{"url": "https://x.example/invented", "title": "Invented", "text": "AAPL", "created_at": "2026-07-24T10:00:00Z"}],
            "themes": [{"theme_id": "invented_theme", "display_name": "Invented", "summary": "Invented", "observed_at": "2026-07-24T12:00:00Z", "source_urls": ["https://x.example/invented"], "members": [{"ticker": "AAPL", "source_urls": ["https://x.example/invented"]}]}],
        })
        discovery, receipt, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=[], grok_response=response,
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        self.assertEqual(discovery["themes"], [])
        self.assertEqual(receipt["summary"]["accepted_source_count"], 0)

    def test_web_x_merge_emits_both_and_single_tiers(self):
        web_rows = [{"url": "https://web.example/a", "title": "A", "content": "AAPL CEG", "published_date": "2026-07-24T10:00:00Z"}, {"url": "https://web.example/b", "title": "B", "content": "CEG", "published_date": "2026-07-23T10:00:00Z"}]
        web_refs = [web._source_id(row["url"]) for row in web_rows]
        web_text = json.dumps({"themes": [{"theme_id": "power_demand", "display_name": "Power", "summary": "Power", "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": web_refs, "members": [{"ticker": "AAPL", "source_ref_ids": web_refs}, {"ticker": "CEG", "source_ref_ids": web_refs}]}]})
        wa, wr, _ = web.build_web_fetch_packet(queries=["power"], search_results=web_rows, llm_response=web_text, expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        xa, xr, _ = xfetch.build_x_fetch_packet(queries=["power"], results=X_ROWS, grok_response=self._x_response(), expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        merged, manifest = merge_web_x_discovery(web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr, expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        rows = {row["ticker"]: row for theme in manifest["themes"] for row in theme["members"]}
        self.assertEqual(rows["AAPL"]["evidence_tier"], "both")
        self.assertEqual(rows["CEG"]["evidence_tier"], "both")
        self.assertEqual(rows["VST"]["evidence_tier"], "single")
        self.assertEqual(manifest["summary"]["both_member_count"], 2)
        self.assertEqual(manifest["summary"]["single_member_count"], 1)
        self.assertEqual(len(merged["themes"]), 1)

    def test_merge_survives_mixed_utc_offsets_and_ledgers_a_rejected_theme(self):
        """A model may legitimately answer in -04:00; a lexical max over mixed offsets used to pick the
        earlier instant and abort the whole week. Also pins that merge drops per theme, not per week."""
        w_rows = [{"url": "https://web.example/a", "title": "A", "content": "power", "published_date": "2026-07-24T20:00:00Z"}]
        x_rows = [{"url": "https://x.example/1", "title": "P", "text": "power", "created_at": "2026-07-24T18:00:00-04:00"}]
        w_ref = [web._source_id(w_rows[0]["url"])]
        x_ref = [xfetch._source_id(x_rows[0]["url"])]
        def theme(refs, observed):
            return {"theme_id": "power_demand", "display_name": "P", "summary": "S", "observed_at": observed,
                    "source_ref_ids": refs, "members": [{"ticker": "AAPL", "source_ref_ids": refs}]}
        wa, wr, _ = web.build_web_fetch_packet(
            queries=["power"], search_results=w_rows,
            llm_response=json.dumps({"themes": [theme(w_ref, "2026-07-24T20:30:00Z")]}),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        xa, xr, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=x_rows,
            grok_response=json.dumps({"themes": [theme(x_ref, "2026-07-24T18:30:00-04:00")]}),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        merged, manifest = merge_web_x_discovery(
            web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr,
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        self.assertEqual(len(merged["themes"]), 1)
        self.assertEqual(manifest["summary"]["dropped_theme_count"], 0)
        self.assertEqual(manifest["drop_ledger"], [])

    def test_both_requires_two_distinct_documents_not_one_seen_twice(self):
        """Grok may cite a news article Tavily also found. Two lanes pointing at the SAME locator is
        one source seen twice, not independent corroboration, so it must not earn the `both` tier."""
        shared = "https://reuters.example/story"
        def packets(x_url):
            w_rows = [{"url": shared, "title": "A", "content": "CEG", "published_date": "2026-07-24T10:00:00Z"}]
            x_rows = [{"url": x_url, "title": "A", "text": "CEG", "created_at": "2026-07-24T10:00:00Z"}]
            wr = [web._source_id(shared)]
            xr = [xfetch._source_id(x_url)]
            def theme(refs):
                return {"theme_id": "power_demand", "display_name": "T", "summary": "S",
                        "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": refs,
                        "members": [{"ticker": "CEG", "source_ref_ids": refs}]}
            wa, wrc, _ = web.build_web_fetch_packet(
                queries=["q"], search_results=w_rows, llm_response=json.dumps({"themes": [theme(wr)]}),
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
            xa, xrc, _ = xfetch.build_x_fetch_packet(
                queries=["q"], results=x_rows, grok_response=json.dumps({"themes": [theme(xr)]}),
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
            _, manifest = merge_web_x_discovery(
                web_artifact=wa, web_receipt=wrc, x_artifact=xa, x_receipt=xrc,
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
            return [row["evidence_tier"] for th in manifest["themes"] for row in th["members"]]

        self.assertEqual(packets(shared), ["single"])
        self.assertEqual(packets("https://x.example/post/9"), ["both"])

    def test_merge_rejects_forged_receipt_digest(self):
        wa, wr, _ = web.build_web_fetch_packet(queries=["power"], search_results=[], llm_response='{"themes":[]}', expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        xa, xr, _ = xfetch.build_x_fetch_packet(queries=["power"], results=[], grok_response='{"themes":[]}', expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        wr["discovery_artifact_sha256"] = "0" * 64
        with self.assertRaises(ThemeDiscoveryMergeError):
            merge_web_x_discovery(web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr, expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")

    def test_merge_rejects_inconsistent_execution_attestation(self):
        wa, wr, _ = web.build_web_fetch_packet(queries=["power"], search_results=[], llm_response='{"themes":[]}', expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        xa, xr, _ = xfetch.build_x_fetch_packet(queries=["power"], results=[], grok_response='{"themes":[]}', expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        wr["fetch_contract"]["execution_mode"] = "live_authorized"
        with self.assertRaises(ThemeDiscoveryMergeError):
            merge_web_x_discovery(web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr, expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")

    def test_merge_cli_rejects_bad_date_and_operator_output_before_reading_inputs(self):
        with mock.patch.object(merge, "merge_web_x_discovery") as run:
            with self.assertRaises(web.WebThemeDiscoveryError):
                merge.main([
                    "--web-discovery", "missing-web.json", "--web-receipt", "missing-web-receipt.json",
                    "--x-discovery", "missing-x.json", "--x-receipt", "missing-x-receipt.json",
                    "--expected-decision-date", "2026-07-25", "--generated-at", "2026-07-25T08:00:00Z",
                ])
            with self.assertRaises(web.WebThemeDiscoveryError):
                merge.main([
                    "--web-discovery", "missing-web.json", "--web-receipt", "missing-web-receipt.json",
                    "--x-discovery", "missing-x.json", "--x-receipt", "missing-x-receipt.json",
                    "--expected-decision-date", "20260725", "--generated-at", "2026-07-25T08:00:00Z",
                    "--discovery-output", str(web.STATE_DIR / "us_short_llm_theme_discovery_web_tavily_20260725_budget.json"),
                ])
            run.assert_not_called()

    def test_merge_retry_publish_property_same_evidence_different_clocks_is_idempotent(self):
        wa, wr, _ = web.build_web_fetch_packet(
            queries=["q"], search_results=[], llm_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T07:00:00Z",
        )
        xa, xr, _ = xfetch.build_x_fetch_packet(
            queries=["q"], results=[], grok_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T07:00:00Z",
        )
        wa_retry, wr_retry, _ = web.build_web_fetch_packet(
            queries=["q"], search_results=[], llm_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        xa_retry, xr_retry, _ = xfetch.build_x_fetch_packet(
            queries=["q"], results=[], grok_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        with tempfile.TemporaryDirectory(dir=web.ROOT / "provider_samples") as td:
            root = Path(td)
            paths = []
            for name, payload in (("web.json", wa), ("web_receipt.json", wr), ("x.json", xa), ("x_receipt.json", xr)):
                path = root / name
                path.write_text(json.dumps(payload), encoding="utf-8")
                paths.append(path)
            retry_paths = []
            for name, payload in (("web_retry.json", wa_retry), ("web_retry_receipt.json", wr_retry), ("x_retry.json", xa_retry), ("x_retry_receipt.json", xr_retry)):
                path = root / name
                path.write_text(json.dumps(payload), encoding="utf-8")
                retry_paths.append(path)
            base = [
                "--web-discovery", str(paths[0]), "--web-receipt", str(paths[1]),
                "--x-discovery", str(paths[2]), "--x-receipt", str(paths[3]),
                "--expected-decision-date", "20260725",
            ]
            with mock.patch.object(web, "STATE_DIR", root):
                self.assertEqual(merge.main(base + ["--generated-at", "2026-07-25T07:00:00Z"]), 0)
                output = merge.default_discovery_path("20260725")
                manifest = merge.default_manifest_path("20260725")
                before = (output.read_bytes(), manifest.read_bytes())
                retry_base = [
                    "--web-discovery", str(retry_paths[0]), "--web-receipt", str(retry_paths[1]),
                    "--x-discovery", str(retry_paths[2]), "--x-receipt", str(retry_paths[3]),
                    "--expected-decision-date", "20260725",
                ]
                self.assertEqual(merge.main(retry_base + ["--generated-at", "2026-07-25T08:00:00Z"]), 0)
                self.assertEqual((output.read_bytes(), manifest.read_bytes()), before)

    def _chain_points(self, merged):
        """merge -> ingest -> knife-2 validate -> boost map, so the tier that scores is the one asserted."""
        from runners import us_short_provisional_theme_validate as validate
        from engine.us_short_provisional_theme_boost import build_provisional_theme_boost_map

        tickers = ["AAPL", "MSFT", "JPM"]
        digests = {"discovery_artifact_sha256": "a" * 64, "candidate_artifact_sha256": "b" * 64,
                   "classification_packet_sha256": "c" * 64}
        artifact = validate.build_artifact({
            "discovery": merged,
            "candidate": {"decision_date": "20260725", "price_basis_date": "20260724", "used_date": "2026-07-24"},
            "classification": {"decision_clock": {"source_as_of": "2026-07-24"}},
            "hashes": {"discovery": "a" * 64, "candidate": "b" * 64, "classification": "c" * 64},
            "eligible": set(tickers), "sectors": {"AAPL": "10", "MSFT": "10", "JPM": "20"},
        }, generated_at="2026-07-25T11:00:00Z")
        boosts = build_provisional_theme_boost_map(
            artifact, target_tickers=tickers, expected_decision_date="20260725",
            expected_input_digests=digests,
        )
        tiers = {member["ticker"]: member["evidence_tier"] for theme in artifact["themes"] for member in theme["members"]}
        return tiers, {ticker: boosts[ticker]["theme_soft_boost"] for ticker in tickers}

    def _merge_lanes(self, web_urls, x_urls, web_members, x_members):
        wrows = [{"url": u, "title": "T", "content": "AAPL MSFT JPM power", "published_date": "2026-07-24T10:00:00Z"} for u in web_urls]
        xrows = [{"url": u, "title": "P", "text": "AAPL power", "created_at": "2026-07-24T10:00:00Z"} for u in x_urls]
        wid = {u: web._source_id(web._canonical_locator(u)) for u in web_urls}
        xid = {u: xfetch._source_id(web._canonical_locator(u)) for u in x_urls}

        def payload(members, refs):
            return json.dumps({"themes": [{
                "theme_id": "power_demand", "display_name": "Power", "summary": "Power demand story",
                "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": refs,
                "members": [{"ticker": t, "source_ref_ids": r} for t, r in members.items()]}]})

        wa, wr, _ = web.build_web_fetch_packet(
            queries=["power"], search_results=wrows,
            llm_response=payload({t: [wid[u] for u in us] for t, us in web_members.items()}, [wid[u] for u in web_urls]),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        xa, xr, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=xrows,
            grok_response=payload({t: [xid[u] for u in us] for t, us in x_members.items()}, [xid[u] for u in x_urls]),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        return merge_web_x_discovery(web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr,
                                     expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")

    def test_redundant_lane_evidence_cannot_be_re_promoted_to_both_downstream(self):
        """The merge's corroboration verdict must reach the SCORE, not just the manifest.

        knife-2 rebuilds `evidence_tier` from ref types alone, so a redundant lane left in the member's
        refs is silently re-promoted to `both` = 5.0 one layer down (exact duplicates did exactly that:
        manifest `single`, boost 5.0). Partial overlap is the same defect: X adding only a document web
        already has is not corroboration. Only genuinely distinct documents may earn 5.0.
        """
        a, b, x_only = "https://web.example/a", "https://web.example/b", "https://x.example/post/9"
        spelled, permuted = "https://web.example/a?p=1&q=2", "https://WEB.Example/a/?q=2&p=1"
        cases = [
            ("exact duplicate", [a], [a], {"AAPL": [a], "MSFT": [a], "JPM": [a]}, {"AAPL": [a]}, "single", 2.0),
            ("partial overlap", [a, b], [a], {"AAPL": [a, b], "MSFT": [a], "JPM": [a]}, {"AAPL": [a]}, "single", 2.0),
            # One document each lane spells differently (host case, trailing slash, parameter order).
            ("one document spelled two ways", [spelled], [permuted],
             {"AAPL": [spelled], "MSFT": [spelled], "JPM": [spelled]}, {"AAPL": [permuted]}, "single", 2.0),
            # Same, with the legacy `;` pair separator: the credential policy treats `;` as a separator,
            # so ordering must too, or one article scores `both` again.
            ("one document, semicolon parameters permuted", ["https://web.example/a?p=1;q=2"], ["https://web.example/a?q=2;p=1"],
             {"AAPL": ["https://web.example/a?p=1;q=2"], "MSFT": ["https://web.example/a?p=1;q=2"], "JPM": ["https://web.example/a?p=1;q=2"]},
             {"AAPL": ["https://web.example/a?q=2;p=1"]}, "single", 2.0),
            ("one document, percent-triplet case", ["https://web.example/a%2Fb"], ["https://web.example/a%2fb"],
             {"AAPL": ["https://web.example/a%2Fb"], "MSFT": ["https://web.example/a%2Fb"], "JPM": ["https://web.example/a%2Fb"]},
             {"AAPL": ["https://web.example/a%2fb"]}, "single", 2.0),
            ("one document, percent-encoded unreserved", ["https://web.example/user%7Ejdoe?u=%41&u=A"], ["https://web.example/user~jdoe?u=A&u=%41"],
             {"AAPL": ["https://web.example/user%7Ejdoe?u=%41&u=A"], "MSFT": ["https://web.example/user%7Ejdoe?u=%41&u=A"], "JPM": ["https://web.example/user%7Ejdoe?u=%41&u=A"]},
             {"AAPL": ["https://web.example/user~jdoe?u=A&u=%41"]}, "single", 2.0),
            ("one document, dot segment", ["https://web.example/sector/./story"], ["https://web.example/sector/story"],
             {"AAPL": ["https://web.example/sector/./story"], "MSFT": ["https://web.example/sector/./story"], "JPM": ["https://web.example/sector/./story"]},
             {"AAPL": ["https://web.example/sector/story"]}, "single", 2.0),
            ("distinct documents", [a], [x_only], {"AAPL": [a], "MSFT": [a], "JPM": [a]}, {"AAPL": [x_only]}, "both", 5.0),
        ]
        for label, web_urls, x_urls, web_members, x_members, tier, points in cases:
            with self.subTest(shape=label):
                merged, manifest = self._merge_lanes(web_urls, x_urls, web_members, x_members)
                row = {r["ticker"]: r for th in manifest["themes"] for r in th["members"]}["AAPL"]
                tiers, boosts = self._chain_points(merged)
                self.assertEqual(row["evidence_tier"], tier)
                self.assertEqual(tiers["AAPL"], tier, "knife-2 must re-derive the merge's own verdict")
                self.assertEqual(boosts["AAPL"], points)
                self.assertEqual(bool(row["redundant_source_ref_ids"]), tier == "single")
                self.assertEqual(manifest["summary"]["redundant_member_count"], 0 if tier == "both" else 1)
                # The theme LABEL follows the same rule (its refs stay whole; only the label changes).
                self.assertEqual(manifest["themes"][0]["discovery_sources"], "both" if tier == "both" else "web")

    def test_merge_binds_raw_observation_time_and_recomputes_source_identity(self):
        """A self-consistent raw/receipt/artifact triad is not provenance, and a re-hashed raw payload is
        not PIT evidence: merge must re-derive the ID from its locator and bind the raw observation time.
        """
        def live_pair(td):
            wa, wr, _ = web.build_web_fetch_packet(
                queries=["power"], search_results=[{"url": "https://web.example/live", "title": "A", "content": "AAPL", "published_date": "2026-07-24T10:00:00Z"}],
                llm_response='{"themes":[]}', expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=Path(td) / "web", persist_raw=True, execution_mode="live_authorized",
                network_call_count=1, provider_call_count=1, _live_attestation=web._LIVE_ATTESTATION)
            xa, xr, _ = xfetch.build_x_fetch_packet(
                queries=["power"], results=[{"url": "https://x.example/live", "title": "P", "text": "AAPL", "created_at": "2026-07-24T10:00:00Z"}],
                grok_response='{"themes":[]}', expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=Path(td) / "x", persist_raw=True, execution_mode="live_authorized",
                network_call_count=1, provider_call_count=1, _live_attestation=web._LIVE_ATTESTATION)
            return wa, wr, xa, xr

        def rehash(receipt, artifact, raw_path, raw):
            raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            receipt["source_refs"][0]["content_sha256"] = hashlib.sha256(web._canonical_json(raw)).hexdigest()
            receipt["discovery_artifact_sha256"] = web._discovery_evidence_hash(artifact)

        def merge_pair(wa, wr, xa, xr):
            return merge_web_x_discovery(web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr,
                                         expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")

        for lane, time_key in (("web", "published_at"), ("x", "created_at")):
            with self.subTest(lane=lane, defect="after-open raw re-hashed"), \
                    tempfile.TemporaryDirectory(dir=web.ROOT / "provider_samples") as td:
                wa, wr, xa, xr = live_pair(td)
                receipt, artifact = (wr, wa) if lane == "web" else (xr, xa)
                merge_pair(wa, wr, xa, xr)      # reverse control: the untouched pair merges
                raw_path = web.ROOT / receipt["source_refs"][0]["raw_receipt_ref"]
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                raw[time_key] = "2026-07-25T15:00:00+00:00"
                rehash(receipt, artifact, raw_path, raw)
                with self.assertRaises(ThemeDiscoveryMergeError):
                    merge_pair(wa, wr, xa, xr)
            with self.subTest(lane=lane, defect="forged source identity"), \
                    tempfile.TemporaryDirectory(dir=web.ROOT / "provider_samples") as td:
                wa, wr, xa, xr = live_pair(td)
                receipt, artifact = (wr, wa) if lane == "web" else (xr, xa)
                forged = f"{lane}:" + "a" * 64
                raw_path = web.ROOT / receipt["source_refs"][0]["raw_receipt_ref"]
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                raw["source_id"] = forged
                receipt["source_refs"][0]["source_id"] = forged
                artifact["source_refs"][0]["source_id"] = forged
                # Rename the raw file to the forged ID too: otherwise the path-binding guard fires and
                # this passes for the WRONG reason instead of pinning the ID recomputation.
                forged_path = raw_path.with_name(f"{forged.split(':', 1)[1]}.json")
                raw_path.rename(forged_path)
                receipt["source_refs"][0]["raw_receipt_ref"] = forged_path.relative_to(web.ROOT).as_posix()
                rehash(receipt, artifact, forged_path, raw)
                with self.assertRaises(ThemeDiscoveryMergeError):
                    merge_pair(wa, wr, xa, xr)
            with self.subTest(lane=lane, defect="raw path not bound to source ID"), \
                    tempfile.TemporaryDirectory(dir=web.ROOT / "provider_samples") as td:
                wa, wr, xa, xr = live_pair(td)
                receipt = wr if lane == "web" else xr
                raw_path = web.ROOT / receipt["source_refs"][0]["raw_receipt_ref"]
                moved = raw_path.with_name("unbound_name.json")
                moved.write_bytes(raw_path.read_bytes())
                receipt["source_refs"][0]["raw_receipt_ref"] = moved.relative_to(web.ROOT).as_posix()
                with self.assertRaises(ThemeDiscoveryMergeError):
                    merge_pair(wa, wr, xa, xr)
            for defect, observed in (("artifact observation drifts from the receipt", "2026-07-23T09:00:00+00:00"),
                                     ("every copy moved past the decision open", "2026-07-25T15:00:00+00:00")):
                with self.subTest(lane=lane, defect=defect), \
                        tempfile.TemporaryDirectory(dir=web.ROOT / "provider_samples") as td:
                    wa, wr, xa, xr = live_pair(td)
                    receipt, artifact = (wr, wa) if lane == "web" else (xr, xa)
                    artifact["source_refs"][0]["observed_at"] = observed
                    raw_path = web.ROOT / receipt["source_refs"][0]["raw_receipt_ref"]
                    raw = json.loads(raw_path.read_text(encoding="utf-8"))
                    if "decision open" in defect:
                        # Move receipt AND raw too, so only the merge-side cutoff can reject it: an
                        # after-open observation that is internally consistent everywhere.
                        receipt["source_refs"][0]["observed_at"] = observed
                        raw[time_key] = observed
                    rehash(receipt, artifact, raw_path, raw)
                    with self.assertRaises(ThemeDiscoveryMergeError):
                        merge_pair(wa, wr, xa, xr)

    def test_merge_refuses_a_receipt_whose_locator_is_not_canonical(self):
        """Re-deriving the ID from the receipt's own locator only proves self-consistency. The dedup reads
        that hash as a DOCUMENT identity, so an uncanonical spelling (which the producers never mint, but
        the merge boundary must not assume) would smuggle in a second identity for one document.
        """
        canonical = "https://web.example/story"
        wrows = [{"url": canonical, "title": "T", "content": "AAPL", "published_date": "2026-07-24T10:00:00Z"}]
        xrows = [{"url": canonical, "title": "P", "text": "AAPL", "created_at": "2026-07-24T10:00:00Z"}]

        def theme(refs):
            return json.dumps({"themes": [{"theme_id": "power_demand", "display_name": "P", "summary": "S",
                                           "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": refs,
                                           "members": [{"ticker": "AAPL", "source_ref_ids": refs}]}]})

        variants = ("https://WEB.Example/story", "https://web.example/story/", "https://web.example:443/story")
        for lane in ("web", "x"):
            for variant in variants:
                with self.subTest(lane=lane, variant=variant):
                    wa, wr, _ = web.build_web_fetch_packet(
                        queries=["q"], search_results=wrows, llm_response=theme([web._source_id(canonical)]),
                        expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
                    xa, xr, _ = xfetch.build_x_fetch_packet(
                        queries=["q"], results=xrows, grok_response=theme([xfetch._source_id(canonical)]),
                        expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
                    artifact, receipt = (wa, wr) if lane == "web" else (xa, xr)
                    old_id = receipt["source_refs"][0]["source_id"]
                    # Re-hash the ID from the variant so the triad stays self-consistent: only the
                    # canonical-locator requirement can reject this, not the ID-recomputation guard.
                    forged = f"{lane}:" + hashlib.sha256(variant.encode("utf-8")).hexdigest()
                    receipt["source_refs"][0].update(source_id=forged, canonical_locator=variant)
                    for ref in artifact["source_refs"]:
                        if ref["source_id"] == old_id:
                            ref["source_id"] = forged
                    for theme_row in artifact["themes"]:
                        theme_row["source_ref_ids"] = [forged if r == old_id else r for r in theme_row["source_ref_ids"]]
                        for member in theme_row["members"]:
                            member["source_ref_ids"] = [forged if r == old_id else r for r in member["source_ref_ids"]]
                    receipt["discovery_artifact_sha256"] = web._discovery_evidence_hash(artifact)
                    with self.assertRaises(ThemeDiscoveryMergeError):
                        merge_web_x_discovery(web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr,
                                              expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")

    def test_x_receipt_never_persists_a_generic_credential_locator(self):
        rows = [{"url": "https://x.example/p?token=REVIEW_FAKE_TOKEN_999", "title": "P", "text": "AAPL", "created_at": "2026-07-24T10:00:00Z"},
                {"url": "https://x.example/good", "title": "P", "text": "AAPL", "created_at": "2026-07-24T10:00:00Z"}]
        _, receipt, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=rows, grok_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        body = json.dumps(receipt)
        self.assertNotIn("REVIEW_FAKE_TOKEN_999", body)
        self.assertEqual(receipt["summary"]["accepted_source_count"], 1)
        self.assertIn("invalid_canonical_locator", [row["reason"] for row in receipt["drop_ledger"]])

    def test_merge_rehashes_live_raw_receipts(self):
        with tempfile.TemporaryDirectory(dir=web.ROOT / "provider_samples") as td:
            root = Path(td)
            wa, wr, _ = web.build_web_fetch_packet(
                queries=["power"], search_results=[{"url": "https://web.example/live", "title": "A", "content": "AAPL", "published_date": "2026-07-24T10:00:00Z"}], llm_response='{"themes":[]}',
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", raw_root=root / "web", persist_raw=True,
                execution_mode="live_authorized", network_call_count=1, provider_call_count=1, _live_attestation=web._LIVE_ATTESTATION,
            )
            xa, xr, _ = xfetch.build_x_fetch_packet(
                queries=["power"], results=[], grok_response='{"themes":[]}',
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            )
            raw_path = web.ROOT / wr["source_refs"][0]["raw_receipt_ref"]
            raw_path.unlink()
            with self.assertRaises(ThemeDiscoveryMergeError):
                merge_web_x_discovery(web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr, expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")


if __name__ == "__main__":
    unittest.main()
