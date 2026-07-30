from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest import mock

from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from runners import us_short_llm_theme_discovery_merge as merge
from runners.us_short_llm_theme_discovery_merge import ThemeDiscoveryMergeError, merge_web_x_discovery
from runners import us_short_llm_theme_discovery_fetch_web as web
from tests.provider.us_short_private_test_root import temporary_provider_directory


X_ROWS = [
    {"url": "https://x.example/post/1", "title": "Power post", "text": "AAPL and CEG power demand", "created_at": "2026-07-24T11:00:00Z"},
    {"url": "https://x.example/post/2", "title": "Utility post", "text": "VST generation buildout", "created_at": "2026-07-23T11:00:00Z"},
]


class _TransportProbe:
    def __init__(self, *providers):
        self._completed = {provider: 0 for provider in providers}

    def _record_completed_response(self, provider):
        self._completed[provider] += 1

    def _snapshot(self):
        return dict(self._completed)


class XFetchAndMergeTests(unittest.TestCase):
    def setUp(self):
        self._raw_tempdir = temporary_provider_directory(web.ROOT)
        self._raw_path = Path(self._raw_tempdir.__enter__())
        self._web_raw_patch = mock.patch.object(web, "DEFAULT_RAW_ROOT", self._raw_path / "web_raw")
        self._x_raw_patch = mock.patch.object(xfetch, "DEFAULT_RAW_ROOT", self._raw_path / "x_raw")
        self._web_raw_patch.start()
        self._x_raw_patch.start()

    def tearDown(self):
        self._x_raw_patch.stop()
        self._web_raw_patch.stop()
        self._raw_tempdir.__exit__(None, None, None)

    def _x_response(self):
        refs = [xfetch._source_id(row["url"]) for row in X_ROWS]
        return json.dumps({"themes": [{"theme_id": "power_demand", "display_name": "Power demand", "summary": "Power demand", "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": refs, "members": [{"ticker": "AAPL", "source_ref_ids": refs}, {"ticker": "CEG", "source_ref_ids": refs}, {"ticker": "VST", "source_ref_ids": refs}]}]})

    @staticmethod
    def _live_raw_response(response_id="resp-test"):
        return {"id": response_id, "object": "response", "output": []}

    @staticmethod
    def _closure_cells(function):
        return dict(zip(function.__code__.co_freevars, (
            cell.cell_contents for cell in function.__closure__ or ()
        )))

    def _forge_web_live_label_by_closure(self):
        """Reproduce the cheapest in-process R77 forge without any provider activity.

        This is intentionally not a proof that a ticket is secure: arbitrary same-process Python can
        reach the runner factory and the captured mutable registry.  The two callers below prove the
        load-bearing downstream alternatives instead: no sources earn zero knife-2 members, and a
        source whose frozen bytes no longer hash is refused by merge before knife-2.
        """
        runner_cells = self._closure_cells(web.run_web_fetch)
        transport = runner_cells["new_transport"]()
        consume_cells = self._closure_cells(type(transport)._consume_ticket)
        forged_ticket = object()
        consume_cells["issued_tickets"].add(forged_ticket)
        transport._record_completed_response("tavily")
        return transport, forged_ticket

    def _forge_x_live_label_by_closure(self, completed=1):
        runner_cells = self._closure_cells(xfetch.run_x_fetch)
        transport = runner_cells["new_transport"]("xai")
        consume_cells = self._closure_cells(type(transport)._consume_ticket)
        forged_ticket = object()
        consume_cells["issued_tickets"].add(forged_ticket)
        for _ in range(completed):
            transport._record_completed_response("xai")
        return transport, forged_ticket

    def test_closure_forged_live_label_without_sources_is_refused_by_knife_2(self):
        """K3-R77: a live label alone cannot buy a theme, member, or soft-boost point."""
        transport, ticket = self._forge_web_live_label_by_closure()
        wa, wr, _ = web.build_web_fetch_packet(
            queries=["power"], search_results=[], llm_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            execution_mode="live_authorized", _live_transport=transport, _live_ticket=ticket,
        )
        xa, xr, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=[], grok_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        merged, _ = merge_web_x_discovery(
            web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr,
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        self.assertEqual(merged["themes"], [])
        from runners.us_short_provisional_theme_validate import ProvisionalThemeValidationError
        with self.assertRaises(ProvisionalThemeValidationError):
            self._chain_points(merged)

    def test_closure_forged_live_label_with_tampered_raw_is_refused_before_knife_2(self):
        """K3-R77: merge re-hashes forged-labelled raw bytes; weakening that re-derivation turns this red."""
        with temporary_provider_directory(web.ROOT) as td:
            transport, ticket = self._forge_web_live_label_by_closure()
            wa, wr, _ = web.build_web_fetch_packet(
                queries=["power"],
                search_results=[{
                    "url": "https://web.example/forged-live", "title": "Power",
                    "content": "AAPL original provider-shaped bytes", "published_date": "2026-07-24T10:00:00Z",
                }],
                llm_response='{"themes":[]}', expected_decision_date="20260725",
                generated_at="2026-07-25T08:00:00Z", raw_root=Path(td) / "web", persist_raw=True,
                execution_mode="live_authorized", _live_transport=transport, _live_ticket=ticket,
            )
            xa, xr, _ = xfetch.build_x_fetch_packet(
                queries=["power"], results=[], grok_response='{"themes":[]}',
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            )
            raw_path = web.ROOT / wr["source_refs"][0]["raw_receipt_ref"]
            raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
            raw_payload["content"] = "AAPL substituted bytes"
            raw_path.write_text(json.dumps(raw_payload), encoding="utf-8")
            with self.assertRaises(ThemeDiscoveryMergeError):
                merge_web_x_discovery(
                    web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr,
                    expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                )

    def test_x_fake_client_is_offline_and_pit_bound(self):
        discovery, receipt, summary = xfetch.build_x_fetch_packet(
            queries=["power"], results=X_ROWS, grok_response=self._x_response(),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        self.assertEqual(receipt["fetch_contract"]["execution_mode"], "offline_fake_client")
        self.assertFalse(receipt["fetch_contract"]["network_access_performed"])
        self.assertEqual(len(discovery["themes"]), 1)
        self.assertEqual(summary["accepted_source_count"], 2)

    def test_x_credential_rejects_whitespace_and_concatenated_markers(self):
        valid = "xai-" + "a" * 32
        for invalid in ("", "xai-a xai-b", valid + valid):
            with self.subTest(invalid=repr(invalid)):
                with self.assertRaises(xfetch.XThemeDiscoveryError):
                    xfetch.GrokXSearchClient(invalid)

    def test_x_credential_policy_is_shared_and_accepts_a_rotated_length(self):
        """Both X call sites go through one helper that reuses the web lane's ambiguity rule."""
        for rotated in ("xai-" + "a" * 20, "xai-" + "b" * 80, "xai-" + "c" * 200):
            with self.subTest(rotated=len(rotated)):
                self.assertEqual(xfetch._require_single_xai_api_key(rotated), rotated)
        for ambiguous in ("", "xai-", "xai-short", "xai-" + "a" * 40 + "xai-" + "b" * 40,
                          "xai-" + "a" * 40 + "\t"):
            with self.subTest(ambiguous=repr(ambiguous[:10])):
                with self.assertRaises(xfetch.XThemeDiscoveryError):
                    xfetch._require_single_xai_api_key(ambiguous)

    def test_x_absent_and_unsupported_created_at_get_distinct_ledger_reasons(self):
        rows = [
            {"url": "https://x.com/u/status/1", "title": "p", "text": "AAPL post"},
            {"url": "https://x.com/u/status/2", "title": "p", "text": "AAPL post", "created_at": "not-a-date"},
            {"url": "https://x.com/u/status/3", "title": "p", "text": "AAPL post",
             "created_at": "2026-07-24T10:00:00+00:00"},
        ]
        refs, drops = xfetch._normalize_results(
            rows, expected_decision_date="20260727",
            fetched_at=web._parse_dt("2026-07-26T12:00:00Z", field="fetched_at"),
            raw_root=None, persist_raw=False,
        )
        self.assertEqual(len(refs), 1)
        self.assertEqual(
            sorted(row["reason"] for row in drops),
            ["missing_created_at", "unsupported_created_at_format"],
        )

    def test_unsafe_x_attestation_is_rejected_per_item_without_aborting_valid_rows(self):
        rows = [
            {"url": "https://x.com/u/status/good", "title": "good", "text": "AAPL post",
             "created_at": "2026-07-24T10:00:00Z", "_evidence_attestation": "provider_attested"},
            {"url": "https://x.com/u/status/bad", "title": "bad", "text": "CEG post",
             "created_at": "2026-07-24T10:00:00Z", "_evidence_attestation": "unverified"},
        ]
        refs, drops = xfetch._normalize_results(
            rows, expected_decision_date="20260727",
            fetched_at=web._parse_dt("2026-07-26T12:00:00Z", field="fetched_at"),
            raw_root=None, persist_raw=False,
        )
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["evidence_attestation"], "provider_attested")
        self.assertEqual(drops, [{
            "stage": "search_result", "reason": "unsafe_x_evidence_attestation",
            "detail": "https://x.com/u/status/bad",
        }])

    def test_live_x_orchestration_is_executable_and_mints_no_live_label(self):
        """Same split as the web lane: the X live body used to be unreachable dead code."""
        class _Client:
            def __init__(self, plan): self.plan, self.queries = list(plan), []
            def search(self, query, expected):
                self.queries.append(query)
                item = self.plan.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item

        good = {"text": self._x_response(), "results": X_ROWS}
        client = _Client([good, RuntimeError("boom")])
        outcome = xfetch.execute_live_x_orchestration(
            queries=["q1", "q2"], expected_decision_date="20260725", client=client,
        )
        self.assertEqual(client.queries, ["q1", "q2"])
        self.assertEqual(len(outcome["results"]), len(X_ROWS), "the good query survives the bad one")
        self.assertTrue(any(row["reason"] == "provider_response_dropped" for row in outcome["query_drops"]))
        self.assertNotIn("receipt", outcome)
        with self.assertRaises(xfetch.XThemeDiscoveryError):
            xfetch.build_x_fetch_packet(
                queries=["q"], results=[], grok_response='{"themes":[]}',
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                execution_mode="live_authorized",
            )

    def test_live_x_model_identity_rejections_drop_only_the_affected_query(self):
        """K3-R70: model identity is untrusted per-query input, never a batch-level failure."""
        class Client:
            def __init__(self):
                self.replies = iter((
                    {"text": self_response, "results": X_ROWS, "model_identity": {"served_model": "grok-4.5", "system_fingerprint": "fp-first"}},
                    {"text": self_response, "results": X_ROWS, "model_identity": {"served_model": None}},
                    {"text": self_response, "results": X_ROWS, "model_identity": {"served_model": "grok-4.3"}},
                    {"text": self_response, "results": X_ROWS, "model_identity": {"served_model": "grok-4.5", "system_fingerprint": "fp-last"}},
                ))

            def search(self, query, expected):
                return next(self.replies)

        self_response = self._x_response()
        outcome = xfetch.execute_live_x_orchestration(
            queries=["good-first", "missing", "changed", "good-last"],
            expected_decision_date="20260725", client=Client(),
        )

        self.assertEqual(len(outcome["results"]), 2 * len(X_ROWS), "sibling queries survive identity drops")
        self.assertEqual(
            [row for row in outcome["query_drops"] if row["reason"] in {"served_model_missing", "served_model_changed"}],
            [
                {"stage": "llm", "reason": "served_model_missing", "detail": "missing"},
                {"stage": "llm", "reason": "served_model_changed", "detail": "changed"},
            ],
        )
        self.assertEqual(outcome["grok_model_identity"], {
            "requested_model": xfetch.GROK_MODEL,
            "served_model": "grok-4.5",
            "system_fingerprints": ["fp-first", "fp-last"],
        })

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
        with temporary_provider_directory(web.ROOT) as td:
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

    def test_x_retry_publish_property_same_source_fetch_clock_new_packet_clock_is_idempotent(self):
        kwargs = dict(queries=["q"], results=X_ROWS[:1], grok_response='{"themes":[]}', expected_decision_date="20260725")
        first, first_receipt, _ = xfetch.build_x_fetch_packet(
            generated_at="2026-07-25T07:00:00Z", fetched_at="2026-07-25T07:00:00Z", **kwargs,
        )
        second, second_receipt, _ = xfetch.build_x_fetch_packet(
            generated_at="2026-07-25T08:00:00Z", fetched_at="2026-07-25T07:00:00Z", **kwargs,
        )
        self.assertEqual(first_receipt["discovery_artifact_sha256"], second_receipt["discovery_artifact_sha256"])
        with temporary_provider_directory(web.ROOT) as td:
            with mock.patch.object(web, "STATE_DIR", Path(td)), mock.patch.object(xfetch, "STATE_DIR", Path(td)):
                output = xfetch.default_discovery_path("20260725")
                receipt_path = xfetch.default_receipt_path("20260725")
                web.publish_decision_pair(first, output, output, first_receipt, receipt_path, receipt_path)
                before = (output.read_bytes(), receipt_path.read_bytes())
                web.publish_decision_pair(second, output, output, second_receipt, receipt_path, receipt_path)
                self.assertEqual((output.read_bytes(), receipt_path.read_bytes()), before)

    def test_retry_reuses_frozen_source_fetch_clock_and_rejects_tampering(self):
        """K3-R32: a retry may restamp its packet clock, never a source fetch instant."""
        for lane in ("web", "x"):
            with self.subTest(lane=lane), temporary_provider_directory(web.ROOT) as td:
                root = Path(td)
                if lane == "web":
                    def build(generated_at, fetched_at):
                        return web.build_web_fetch_packet(
                            queries=["q"],
                            search_results=[{
                                "url": "https://web.example/r32", "title": "R32", "content": "AAPL",
                                "published_date": "2026-07-24T10:00:00Z",
                            }],
                            llm_response='{"themes":[]}', expected_decision_date="20260725",
                            generated_at=generated_at, fetched_at=fetched_at,
                            raw_root=root / lane, persist_raw=True,
                        )
                else:
                    def build(generated_at, fetched_at):
                        return xfetch.build_x_fetch_packet(
                            queries=["q"], results=[X_ROWS[0]], grok_response='{"themes":[]}',
                            expected_decision_date="20260725", generated_at=generated_at,
                            fetched_at=fetched_at, raw_root=root / lane, persist_raw=True,
                        )

                first, first_receipt, _ = build("2026-07-25T07:00:00Z", "2026-07-25T07:00:00Z")
                retry, retry_receipt, _ = build("2026-07-25T08:00:00Z", "2026-07-25T08:00:00Z")
                self.assertEqual(retry_receipt["source_refs"][0]["fetched_at"], "2026-07-25T07:00:00+00:00")
                artifact_path = root / f"{lane}_artifact.json"
                receipt_path = root / f"{lane}_receipt.json"
                web._write_json_pair_atomic(first, artifact_path, first_receipt, receipt_path)
                web._write_json_pair_atomic(retry, artifact_path, retry_receipt, receipt_path)
                raw_path = web.ROOT / first_receipt["source_refs"][0]["raw_receipt_ref"]
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                raw["fetched_at"] = "2099-01-01T00:00:00Z"
                raw_path.write_text(json.dumps(raw), encoding="utf-8")
                _artifact, tampered_raw_receipt, _summary = build(
                    "2026-07-25T09:00:00Z", "2026-07-25T09:00:00Z",
                )
                self.assertEqual(tampered_raw_receipt["summary"]["accepted_source_count"], 0)
                self.assertIn("immutable_raw_content_conflict", [
                    row["reason"] for row in tampered_raw_receipt["drop_ledger"]
                ])
                tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
                tampered["source_refs"][0]["fetched_at"] = "2099-01-01T00:00:00Z"
                receipt_path.write_text(json.dumps(tampered), encoding="utf-8")
                with self.assertRaises(web.WebThemeDiscoveryError):
                    web._write_json_pair_atomic(retry, artifact_path, retry_receipt, receipt_path)

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
        with temporary_provider_directory(web.ROOT) as td:
            wa, wr, _ = web.build_web_fetch_packet(queries=["power"], search_results=web_rows, llm_response=web_text, expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", raw_root=Path(td) / "web", persist_raw=True)
            xa, xr, _ = xfetch.build_x_fetch_packet(queries=["power"], results=X_ROWS, grok_response=self._x_response(), expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", raw_root=Path(td) / "x", persist_raw=True)
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
        w_rows = [{"url": "https://web.example/a", "title": "A", "content": "AAPL power", "published_date": "2026-07-24T20:00:00Z"}]
        x_rows = [{"url": "https://x.example/1", "title": "P", "text": "AAPL power", "created_at": "2026-07-24T18:00:00-04:00"}]
        w_ref = [web._source_id(w_rows[0]["url"])]
        x_ref = [xfetch._source_id(x_rows[0]["url"])]
        def theme(refs, observed):
            return {"theme_id": "power_demand", "display_name": "P", "summary": "S", "observed_at": observed,
                    "source_ref_ids": refs, "members": [{"ticker": "AAPL", "source_ref_ids": refs}]}
        with temporary_provider_directory(web.ROOT) as td:
            wa, wr, _ = web.build_web_fetch_packet(
                queries=["power"], search_results=w_rows,
                llm_response=json.dumps({"themes": [theme(w_ref, "2026-07-24T20:30:00Z")]}),
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", raw_root=Path(td) / "web", persist_raw=True)
            xa, xr, _ = xfetch.build_x_fetch_packet(
                queries=["power"], results=x_rows,
                grok_response=json.dumps({"themes": [theme(x_ref, "2026-07-24T18:30:00-04:00")]}),
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", raw_root=Path(td) / "x", persist_raw=True)
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
            with temporary_provider_directory(web.ROOT) as td:
                wa, wrc, _ = web.build_web_fetch_packet(
                    queries=["q"], search_results=w_rows, llm_response=json.dumps({"themes": [theme(wr)]}),
                    expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", raw_root=Path(td) / "web", persist_raw=True)
                xa, xrc, _ = xfetch.build_x_fetch_packet(
                    queries=["q"], results=x_rows, grok_response=json.dumps({"themes": [theme(xr)]}),
                    expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", raw_root=Path(td) / "x", persist_raw=True)
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
        wr["fetch_contract"].update(
            execution_mode="live_authorized", network_access_performed=True,
            provider_calls_performed=True, network_call_count=1, provider_call_count=1,
        )
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
        with temporary_provider_directory(web.ROOT) as td:
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

        with temporary_provider_directory(web.ROOT) as td:
            wa, wr, _ = web.build_web_fetch_packet(
                queries=["power"], search_results=wrows,
                llm_response=payload({t: [wid[u] for u in us] for t, us in web_members.items()}, [wid[u] for u in web_urls]),
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", raw_root=Path(td) / "web", persist_raw=True)
            xa, xr, _ = xfetch.build_x_fetch_packet(
                queries=["power"], results=xrows,
                grok_response=payload({t: [xid[u] for u in us] for t, us in x_members.items()}, [xid[u] for u in x_urls]),
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", raw_root=Path(td) / "x", persist_raw=True)
            return merge_web_x_discovery(web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr,
                                         expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")

    def test_both_member_without_frozen_x_ticker_evidence_demotes_to_single_through_boost(self):
        """K3-R59: model refs alone cannot buy the 5-point `both` tier."""
        w_rows = [{"url": "https://web.example/power", "title": "Power", "content": "AAPL MSFT JPM power", "published_date": "2026-07-24T10:00:00Z"}]
        x_rows = [{"url": "https://x.example/photo", "title": "Photo", "text": "MSFT JPM power\nhttps://images.example/AAPL\nDisclaimer: AAPL is not evidence", "created_at": "2026-07-24T10:00:00Z"}]
        w_ref, x_ref = web._source_id(w_rows[0]["url"]), xfetch._source_id(x_rows[0]["url"])
        payload = json.dumps({"themes": [{
            "theme_id": "power_demand", "display_name": "Power", "summary": "Power",
            "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": [w_ref, x_ref],
            "members": [{"ticker": ticker, "source_ref_ids": [w_ref, x_ref]} for ticker in ("AAPL", "MSFT", "JPM")],
        }]})
        with temporary_provider_directory(web.ROOT) as td:
            wa, wr, _ = web.build_web_fetch_packet(
                queries=["power"], search_results=w_rows, llm_response=payload,
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=Path(td) / "web", persist_raw=True,
            )
            xa, xr, _ = xfetch.build_x_fetch_packet(
                queries=["power"], results=x_rows, grok_response=payload,
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=Path(td) / "x", persist_raw=True,
            )
            x_raw = json.loads((web.ROOT / xr["source_refs"][0]["raw_receipt_ref"]).read_text(encoding="utf-8"))
            self.assertFalse(merge._raw_payload_mentions_ticker(x_raw, "AAPL"))
            merged, manifest = merge_web_x_discovery(
                web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr,
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            )
            # K3-R102: an ordinary demotion must not make the builder emit a manifest that its own
            # validator refuses forever (the decision slot is immutable, so that zeroes the week).
            merge.validate_merged_packet(
                merged, manifest, expected_decision_date="20260725",
                upstream_pairs={"web": (wa, wr), "x": (xa, xr)},
            )
        rows = {row["ticker"]: row for theme in manifest["themes"] for row in theme["members"]}
        tiers, boosts = self._chain_points(merged)
        self.assertEqual(rows["AAPL"]["evidence_tier"], "single")
        self.assertEqual(tiers["AAPL"], "single")
        self.assertEqual(boosts["AAPL"], 2.0)
        self.assertEqual(rows["MSFT"]["evidence_tier"], "both")
        self.assertEqual(manifest["summary"]["member_evidence_demotion_count"], 1)
        self.assertIn(
            {"stage": "theme", "theme_id": "power_demand", "reason": "member_evidence_demoted_unbound_ticker", "detail": f"AAPL:{x_ref}"},
            manifest["drop_ledger"],
        )

    def test_k3_r105a_only_a_real_trailing_notice_swallows_the_text_behind_it(self):
        """K3-R105 (a): a mid-sentence CTA label may not hide every ticker behind it."""
        def payload(text):
            return {"source_type": "web", "title": "Power demand", "content": text}

        # A call-to-action label is a phrase: what the snippet actually says survives it.
        kept = payload("AAPL leads the trade. Read more: MSFT and JPM follow.")
        for ticker in ("AAPL", "MSFT", "JPM"):
            with self.subTest(kept=ticker):
                self.assertTrue(merge._raw_payload_mentions_ticker(kept, ticker))
        for label in ("Subscribe: MSFT rallies", "Follow us MSFT rallies", "Source: MSFT rallies"):
            with self.subTest(label=label):
                self.assertTrue(merge._raw_payload_mentions_ticker(payload(label), "MSFT"))
        # A label may not eat the HEAD of a longer word and leave a fragment standing: `SOURCES`
        # minus `source` would read as the bare ticker `S`.
        for fragment_text, minted in (
            ("MSFT power demand, SOURCES SAY", "S"),
            ("SUBSCRIBERS FLEE MSFT", "RS"),
            ("FOLLOW USA TODAY MSFT", "A"),
            ("READ MORES MSFT", "S"),
        ):
            with self.subTest(fragment=fragment_text):
                self.assertFalse(merge._raw_payload_mentions_ticker(payload(fragment_text), minted))
                self.assertTrue(merge._raw_payload_mentions_ticker(payload(fragment_text), "MSFT"))
        # A legal notice really does terminate the content, but only when it STARTS a segment.
        for notice in (
            "MSFT rallies. Disclaimer: AAPL is not evidence",
            "MSFT rallies. Copyright 2026 AAPL Inc",
            "MSFT rallies. All rights reserved AAPL",
            "MSFT rallies https://img.example/x Disclaimer: AAPL is not evidence",
        ):
            with self.subTest(notice=notice):
                self.assertFalse(merge._raw_payload_mentions_ticker(payload(notice), "AAPL"))
                self.assertTrue(merge._raw_payload_mentions_ticker(payload(notice), "MSFT"))
        # ... and the same words used as ordinary prose mid-sentence are NOT a trailing notice.
        for prose in (
            "The disclaimer in the 10-K notes AAPL supply risk",
            "A copyright dispute hit AAPL this week",
        ):
            with self.subTest(prose=prose):
                self.assertTrue(merge._raw_payload_mentions_ticker(payload(prose), "AAPL"))

    def test_k3_r105b_a_single_member_also_needs_its_ticker_in_the_frozen_text(self):
        """K3-R105 (b): the 2.0 tier is content-bound too, not only the 5.0 tier."""
        w_rows = [{"url": "https://web.example/power", "title": "Power",
                   "content": "AAPL MSFT JPM power demand", "published_date": "2026-07-24T10:00:00Z"}]
        w_ref = web._source_id(w_rows[0]["url"])
        payload = json.dumps({"themes": [{
            "theme_id": "power_demand", "display_name": "Power", "summary": "Power",
            "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": [w_ref],
            "members": [{"ticker": ticker, "source_ref_ids": [w_ref]}
                        for ticker in ("AAPL", "MSFT", "JPM", "NVDA")],
        }]})
        with temporary_provider_directory(web.ROOT) as td:
            wa, wr, _ = web.build_web_fetch_packet(
                queries=["power"], search_results=w_rows, llm_response=payload,
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=Path(td) / "web", persist_raw=True,
            )
            xa, xr, _ = xfetch.build_x_fetch_packet(
                queries=["power"], results=[], grok_response='{"themes":[]}',
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=Path(td) / "x", persist_raw=True,
            )
            merged, manifest = merge_web_x_discovery(
                web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr,
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            )
            merge.validate_merged_packet(
                merged, manifest, expected_decision_date="20260725",
                upstream_pairs={"web": (wa, wr), "x": (xa, xr)},
            )
        rows = {row["ticker"]: row for theme in manifest["themes"] for row in theme["members"]}
        self.assertEqual(sorted(rows), ["AAPL", "JPM", "MSFT"])       # NVDA is never named
        self.assertEqual({rows[ticker]["evidence_tier"] for ticker in rows}, {"single"})
        self.assertIn("member_evidence_unbound_ticker_dropped",
                      {row["reason"] for row in manifest["drop_ledger"]})
        _, boosts = self._chain_points(merged)
        self.assertEqual(boosts["AAPL"], 2.0)
        self.assertNotIn("NVDA", boosts)

    def test_k3_r103_unverifiable_member_is_dropped_without_taking_its_theme(self):
        """K3-R103: one member whose ticker is never in the frozen text may not void its siblings."""
        w_rows = [{"url": "https://web.example/power", "title": "Power",
                   "content": "AAPL MSFT JPM power demand", "published_date": "2026-07-24T10:00:00Z"}]
        x_rows = [{"url": "https://x.example/power", "title": "Power",
                   "text": "AAPL MSFT JPM power demand", "created_at": "2026-07-24T10:00:00Z"}]
        w_ref, x_ref = web._source_id(w_rows[0]["url"]), xfetch._source_id(x_rows[0]["url"])
        payload = json.dumps({"themes": [{
            "theme_id": "power_demand", "display_name": "Power", "summary": "Power",
            "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": [w_ref, x_ref],
            "members": [{"ticker": ticker, "source_ref_ids": [w_ref, x_ref]}
                        for ticker in ("AAPL", "MSFT", "JPM", "NVDA")],
        }]})
        with temporary_provider_directory(web.ROOT) as td:
            wa, wr, _ = web.build_web_fetch_packet(
                queries=["power"], search_results=w_rows, llm_response=payload,
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=Path(td) / "web", persist_raw=True,
            )
            xa, xr, _ = xfetch.build_x_fetch_packet(
                queries=["power"], results=x_rows, grok_response=payload,
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=Path(td) / "x", persist_raw=True,
            )
            merged, manifest = merge_web_x_discovery(
                web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr,
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            )
            merge.validate_merged_packet(
                merged, manifest, expected_decision_date="20260725",
                upstream_pairs={"web": (wa, wr), "x": (xa, xr)},
            )
        self.assertEqual(manifest["summary"]["merged_theme_count"], 1)
        self.assertEqual(manifest["summary"]["dropped_theme_count"], 0)
        rows = {row["ticker"]: row for theme in manifest["themes"] for row in theme["members"]}
        self.assertEqual(sorted(rows), ["AAPL", "JPM", "MSFT"])
        self.assertEqual({rows[ticker]["evidence_tier"] for ticker in rows}, {"both"})
        self.assertIn("member_evidence_unbound_ticker_dropped",
                      {row["reason"] for row in manifest["drop_ledger"]})
        tiers, boosts = self._chain_points(merged)
        self.assertEqual(boosts["AAPL"], 5.0)
        self.assertNotIn("NVDA", boosts)

    def test_offline_raw_receipts_keep_bound_two_source_members_through_knife_2(self):
        """K3-R64: offline output persists raw bytes before the same ticker gate runs."""
        web_row = {
            "url": "https://web.example/ceg", "title": "CEG generation",
            "content": "AAPL MSFT JPM expand data-center generation.", "published_date": "2026-07-24T10:00:00Z",
        }
        x_row = {
            "url": "https://x.example/ceg", "title": "CEG power demand",
            "text": "AAPL MSFT JPM power demand keeps climbing.", "created_at": "2026-07-24T10:00:00Z",
        }
        web_ref, x_ref = web._source_id(web_row["url"]), xfetch._source_id(x_row["url"])
        payload = json.dumps({"themes": [{
            "theme_id": "power_demand", "display_name": "Power", "summary": "Power",
            "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": [web_ref, x_ref],
            "members": [{"ticker": ticker, "source_ref_ids": [web_ref, x_ref]}
                        for ticker in ("AAPL", "MSFT", "JPM")],
        }]})
        with temporary_provider_directory(web.ROOT) as td:
            web_artifact, web_receipt, _ = web.build_web_fetch_packet(
                queries=["power"], search_results=[web_row], llm_response=payload,
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=Path(td) / "web", persist_raw=True,
            )
            x_artifact, x_receipt, _ = xfetch.build_x_fetch_packet(
                queries=["power"], results=[x_row], grok_response=payload,
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=Path(td) / "x", persist_raw=True,
            )
            self.assertTrue(all(ref["raw_receipt_ref"] is not None for ref in web_receipt["source_refs"] + x_receipt["source_refs"]))
            merged, manifest = merge_web_x_discovery(
                web_artifact=web_artifact, web_receipt=web_receipt,
                x_artifact=x_artifact, x_receipt=x_receipt,
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            )
        self.assertEqual(manifest["summary"]["both_member_count"], 3)
        self.assertEqual(manifest["summary"]["member_evidence_demotion_count"], 0)
        tiers, boosts = self._chain_points(merged)
        self.assertEqual(tiers, {"AAPL": "both", "MSFT": "both", "JPM": "both"})
        self.assertEqual(boosts["AAPL"], 5.0)

    def test_raw_ticker_match_requires_standalone_non_url_non_boilerplate_evidence(self):
        raw = {"source_type": "web", "title": "AAPL mentioned", "content": "$AAPL is explicit"}
        self.assertTrue(merge._raw_payload_mentions_ticker(raw, "aapl"))
        short = {"source_type": "x", "title": "", "text": "analysis https://example.com/A\nDisclaimer: A is not evidence"}
        self.assertFalse(merge._raw_payload_mentions_ticker(short, "A"))
        self.assertTrue(merge._raw_payload_mentions_ticker({**short, "text": "analysis $A"}, "A"))

    def test_model_transcribed_x_source_requires_provider_annotation_url(self):
        """K3-R66: model text is evidence only after provider URL attestation."""
        url = "https://x.com/ceg/status/1937910118252712411"
        grok = json.dumps({"sources": [{"url": url, "title": "CEG", "text": "CEG demand rises", "created_at": "2026-07-24T10:00:00Z"}], "themes": [{"theme_id": "power_demand", "display_name": "Power", "summary": "Power", "observed_at": "2026-07-24T12:00:00Z", "source_urls": [url], "members": [{"ticker": "CEG", "source_urls": [url]}]}]})
        _, rejected, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=[], grok_response=grok,
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            provider_annotation_urls=[],
        )
        self.assertEqual(rejected["source_refs"], [])
        self.assertIn("model_source_url_not_provider_annotated", {row["reason"] for row in rejected["drop_ledger"]})
        _, accepted, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=[], grok_response=grok,
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            provider_annotation_urls=[url],
        )
        self.assertEqual(accepted["source_refs"][0]["evidence_attestation"], "model_transcribed")

    def test_x_status_identity_backs_real_annotation_form_and_records_both_mismatch_sides(self):
        """K3-R79/R83: comparison identity is narrow, while mismatch evidence remains replayable."""
        status_ids = [
            "1937910118252712411", "2080275382704500979", "1976276108007092382",
            "2051270129586209252", "2081856920949014998", "2074770950034227607",
        ]
        model_urls = [f"https://x.com/handle{index}/status/{status_id}" for index, status_id in enumerate(status_ids)]
        annotation_urls = [f"https://x.com/i/status/{status_id}" for status_id in status_ids]
        transcript = json.dumps({
            "sources": [
                {"url": url, "title": "Power", "text": "CEG demand rises", "created_at": "2026-07-24T10:00:00Z"}
                for url in model_urls
            ],
            "themes": [],
        })
        _, accepted, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=[], grok_response=transcript,
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            provider_annotation_urls=annotation_urls,
        )
        self.assertEqual(
            {(ref["canonical_locator"], ref["source_id"]) for ref in accepted["source_refs"]},
            {(url, xfetch._source_id(url)) for url in annotation_urls},
        )

        web_annotation = f"https://x.com/i/web/status/{status_ids[0]}"
        _, web_form, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=[], grok_response=json.dumps({
                "sources": [{"url": web_annotation, "title": "Power", "text": "CEG", "created_at": "2026-07-24T10:00:00Z"}],
                "themes": [],
            }), expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            provider_annotation_urls=[web_annotation],
        )
        self.assertEqual(web_form["source_refs"][0]["canonical_locator"], web_annotation)

        mismatch_annotation_urls = annotation_urls + ["https://x.com/i/status/9999999999999999999"]
        _, rejected, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=[], grok_response=json.dumps({
                "sources": [{"url": "https://x.com/other/status/1111111111111111111", "title": "Power", "text": "CEG", "created_at": "2026-07-24T10:00:00Z"}], "themes": [],
            }), expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            provider_annotation_urls=mismatch_annotation_urls,
        )
        drop = next(row for row in rejected["drop_ledger"] if row["reason"] == "model_source_url_not_provider_annotated")
        self.assertEqual(set(drop), {"stage", "reason", "detail", "model_source_url", "provider_annotation_set_ref"})
        self.assertEqual(drop["model_source_url"], "https://x.com/other/status/1111111111111111111")
        self.assertEqual(drop["provider_annotation_set_ref"], "provider_annotation_urls")
        self.assertEqual(rejected["provider_annotation_urls"], sorted(mismatch_annotation_urls))

        for model_url in ("https://x.com/home", "https://example.com/handle/status/1937910118252712411"):
            with self.subTest(model_url=model_url):
                _, unbacked, _ = xfetch.build_x_fetch_packet(
                    queries=["power"], results=[], grok_response=json.dumps({
                        "sources": [{"url": model_url, "title": "Power", "text": "CEG", "created_at": "2026-07-24T10:00:00Z"}], "themes": [],
                    }), expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                    provider_annotation_urls=annotation_urls,
                )
                self.assertEqual(unbacked["source_refs"], [])

        with mock.patch.object(xfetch, "_x_status_identity", return_value=None):
            _, hollowed, _ = xfetch.build_x_fetch_packet(
                queries=["power"], results=[], grok_response=transcript,
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                provider_annotation_urls=annotation_urls,
            )
        self.assertEqual(hollowed["source_refs"], [])

    def test_k3_r86_legacy_x_receipt_shape_remains_mergeable(self):
        wa, wr, _ = web.build_web_fetch_packet(
            queries=["power"], search_results=[], llm_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        xa, xr, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=[], grok_response=json.dumps({
                "sources": [{"url": "https://x.com/u/status/1", "title": "Power", "text": "CEG", "created_at": "2026-07-24T10:00:00Z"}],
                "themes": [],
            }), expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            provider_annotation_urls=[],
        )
        legacy = json.loads(json.dumps(xr))
        legacy.pop("provider_response_refs", None)
        legacy.pop("provider_annotation_urls", None)
        for row in legacy["drop_ledger"]:
            row.pop("model_source_url", None)
            row.pop("provider_annotation_urls", None)
            row.pop("provider_annotation_set_ref", None)
        xfetch._validate_schema(legacy)
        for missing in ("provider_response_refs", "provider_annotation_urls"):
            new_shape = json.loads(json.dumps(xr))
            new_shape.pop(missing)
            with self.assertRaises(xfetch.XThemeDiscoveryError):
                xfetch._validate_builder_receipt_evidence(new_shape, 0)
        merged, _ = merge_web_x_discovery(
            web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=legacy,
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        self.assertEqual(merged["themes"], [])

    def test_k3_r87_r88_bad_or_conflicting_raw_response_drops_only_that_response(self):
        with temporary_provider_directory(web.ROOT) as td:
            raw_root = Path(td) / "x"
            good = self._live_raw_response("good")
            bad = {"id": "bad", "text": "lone-surrogate-\ud800"}
            transport, ticket = self._forge_x_live_label_by_closure(completed=2)
            _, receipt, _ = xfetch.build_x_fetch_packet(
                queries=["q1", "q2"], results=[], grok_response='{"themes":[]}',
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=raw_root, persist_raw=True, execution_mode="live_authorized",
                _live_transport=transport, _live_ticket=ticket,
                raw_provider_responses=[good, bad],
            )
            self.assertEqual(len(receipt["provider_response_refs"]), 1)
            self.assertIn("provider_response_capture_unavailable", {row["reason"] for row in receipt["drop_ledger"]})

            conflict = self._live_raw_response("conflict")
            conflict_digest = hashlib.sha256(web._canonical_json(conflict)).hexdigest()
            conflict_path = web._raw_provider_response_path(raw_root, "xai", conflict_digest, "20260725")
            conflict_path.parent.mkdir(parents=True, exist_ok=True)
            conflict_path.write_text("{ not json", encoding="utf-8")
            transport, ticket = self._forge_x_live_label_by_closure()
            _, conflicted, _ = xfetch.build_x_fetch_packet(
                queries=["q"], results=[], grok_response='{"themes":[]}',
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=raw_root, persist_raw=True, execution_mode="live_authorized",
                _live_transport=transport, _live_ticket=ticket,
                raw_provider_responses=[conflict],
            )
            self.assertEqual(conflicted["provider_response_refs"], [])
            self.assertIn("provider_response_immutable_raw_content_conflict", {row["reason"] for row in conflicted["drop_ledger"]})

    def test_k3_r95_source_conflict_is_not_a_provider_response_drop(self):
        """K3-R95: source freeze failures must not poison response-index accounting."""
        receipt = {
            "fetch_contract": {"execution_mode": "live_authorized"},
            "provider_response_refs": [{"response_index": 0}],
            "provider_annotation_urls": [],
            "drop_ledger": [{
                "stage": "search_result", "reason": "immutable_raw_content_conflict",
                "detail": "https://x.com/u/status/1",
            }],
        }
        xfetch._validate_builder_receipt_evidence(receipt, 1)
        receipt["drop_ledger"].append({
            "stage": "search_result", "reason": "provider_response_capture_unavailable",
            "detail": "response[1]:missing_response", "provider_response_index": 1,
        })
        with self.assertRaises(xfetch.XThemeDiscoveryError):
            xfetch._validate_builder_receipt_evidence(receipt, 1)

    def test_k3_r95_offline_source_conflict_does_not_break_merge_accounting(self):
        wa, wr, _ = web.build_web_fetch_packet(
            queries=["q"], search_results=[], llm_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        xa, xr, _ = xfetch.build_x_fetch_packet(
            queries=["q"], results=[], grok_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        xr["drop_ledger"].append({
            "stage": "search_result", "reason": "immutable_raw_content_conflict",
            "detail": "https://x.com/u/status/1",
        })
        xr["drop_ledger"].sort(key=lambda row: (row["stage"], row["reason"], row["detail"]))
        xr["discovery_artifact_sha256"] = web._discovery_evidence_hash(xa)
        xfetch._validate_schema(xr)
        merged, _ = merge_web_x_discovery(
            web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr,
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        self.assertEqual(merged["themes"], [])

    def test_k3_r96_o1_percent_encoded_secret_locator_drops_without_schema_abort(self):
        locator = "https://x.com/%73ecret/status/1937910118252712411"
        _, receipt, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=[], grok_response=json.dumps({
                "sources": [{"url": locator, "title": "Power", "text": "CEG", "created_at": "2026-07-24T10:00:00Z"}],
                "themes": [],
            }), expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            provider_annotation_urls=[locator],
        )
        self.assertEqual(receipt["source_refs"], [])
        self.assertEqual(receipt["provider_annotation_urls"], [])
        self.assertNotIn("redacted_untrusted_detail", json.dumps(receipt))

    def test_k3_r96_o2_provider_raw_must_stay_in_decision_week(self):
        with temporary_provider_directory(web.ROOT) as td:
            raw_root = Path(td) / "x"
            transport, ticket = self._forge_x_live_label_by_closure()
            xa, xr, _ = xfetch.build_x_fetch_packet(
                queries=["q"], results=[], grok_response='{"themes":[]}',
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=raw_root, persist_raw=True, execution_mode="live_authorized",
                _live_transport=transport, _live_ticket=ticket,
                raw_provider_responses=[self._live_raw_response("stale-clock")],
            )
            wa, wr, _ = web.build_web_fetch_packet(
                queries=["q"], search_results=[], llm_response='{"themes":[]}',
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            )
            raw_ref = xr["provider_response_refs"][0]
            raw_path = web.ROOT / raw_ref["raw_receipt_ref"]
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            raw["fetched_at"] = "2026-05-01T08:00:00Z"
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            raw_ref["fetched_at"] = raw["fetched_at"]
            with self.assertRaises(ThemeDiscoveryMergeError):
                merge_web_x_discovery(
                    web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr,
                    expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                )

    def test_k3_r96_o3_model_source_list_is_bounded_by_truncation_not_by_a_batch_abort(self):
        """K3-R101: the cap bounds the receipt; it may not void the themes of paid siblings.

        `_parse_grok` also runs on the CONCATENATION of every query's response, so raising here let
        the aggregate of individually-innocent responses erase them all.
        """
        drops: list[dict] = []
        theme = {"theme_id": "power", "display_name": "P", "summary": "S",
                 "observed_at": "2026-07-24T12:00:00Z", "members": []}
        parsed = xfetch._parse_grok(json.dumps({
            "sources": [{"url": f"https://x.example/post/{index}"}
                        for index in range(xfetch.MAX_GROK_SOURCES + 25)],
            "themes": [theme],
        }), drop_ledger=drops)
        self.assertEqual(len(parsed["sources"]), xfetch.MAX_GROK_SOURCES)
        self.assertEqual(parsed["themes"], [theme])
        self.assertIn("model_source_list_truncated", {row["reason"] for row in drops})

        under_cap = json.dumps({
            "sources": [{"url": f"https://x.example/post/{index}"}
                        for index in range(xfetch.MAX_GROK_SOURCES - 100)],
            "themes": [theme],
        })
        combined, _ = xfetch._combine_grok_responses([under_cap, under_cap])
        survived = xfetch._parse_grok(combined, drop_ledger=[])
        self.assertEqual(len(survived["themes"]), 1)

    def test_k3_r100_one_x_post_in_two_spellings_is_not_corroboration(self):
        """K3-R100: two spellings of ONE tweet may not mint the 5-point `both` tier."""
        status_id = "1937910118252712411"

        def ref(kind: str, locator: str) -> dict[str, str]:
            return {
                "source_id": f"{kind}:" + hashlib.sha256(locator.encode("utf-8")).hexdigest(),
                "source_type": kind, "canonical_locator": locator,
            }

        web_sighting = ref("web", f"https://x.com/nvidia/status/{status_id}")
        for spelling in (
            f"https://x.com/i/status/{status_id}",             # the spelling the X lane persists
            f"https://twitter.com/nvidia/status/{status_id}",  # host alias
            f"https://x.com/i/web/status/{status_id}",         # the K3-R94 route
            f"https://www.x.com/nvidia/status/{status_id}",    # www mirror
            f"https://www.twitter.com/nvidia/status/{status_id}",
            f"https://mobile.twitter.com/nvidia/status/{status_id}",
            f"http://x.com/nvidia/status/{status_id}",         # scheme mirror
            f"https://x.com/nvidia/status/{status_id}/photo/1",   # permalink views
            f"https://x.com/nvidia/status/{status_id}/photo/1/large",
            f"https://x.com/nvidia/status/{status_id}/video/2",
            f"https://x.com/nvidia/status/{status_id}/quotes",
            f"https://x.com/nvidia/status/{status_id}/likes",
            f"https://x.com/nvidia/status/{status_id}/retweets",
            f"https://x.com/nvidia/status/{status_id}/analytics",
            f"https://x.com/nvidia/status/{status_id}/history",
            f"https://twitter.com/nvidia/statuses/{status_id}",   # pre-2013 spelling
            f"https://x.com/nvidia/Status/{status_id}",           # path case
            f"https://x.com./nvidia/status/{status_id}",          # RFC 1034 root label
            f"https://www.twitter.com./nvidia/status/{status_id}",
            f"https://x.com//nvidia/status/{status_id}",          # empty path segments
            f"https://x.com/nvidia//status/{status_id}",
            f"https://x.com/nvidia/status//{status_id}",
            f"https://x.com/nvidia/status/{status_id}%2Fphoto%2F1",   # encoded separators
            f"https://x.com/nvidia/status/0{status_id}",          # X resolves the id as an integer
            f"https://x.com:8443/nvidia/status/{status_id}",      # port is ignored on purpose
            f"https://x.com/status/{status_id}",                  # handle-less permalink
            f"https://twitter.com/statuses/{status_id}",
            f"https://x.com//status/{status_id}",                 # empty handle segment
            f"https://x.com/%2Fstatus/{status_id}",
            f"https://x.com/statuses/{status_id}/photo/1",
            f"https://www.twitter.com./statuses/{status_id}",
            f"https://x.com/i/statuses/{status_id}",
        ):
            x_sighting = ref("x", spelling)
            keep, tier, redundant = merge._corroboration([web_sighting, x_sighting])
            with self.subTest(spelling=spelling):
                self.assertEqual((keep, tier), ("web", "single"))
                self.assertEqual(redundant, [x_sighting["source_id"]])
        # Reverse controls: two genuinely different posts still corroborate, and the frozen
        # hash-suffix behaviour for non-X documents is untouched.
        self.assertEqual(merge._corroboration([
            web_sighting, ref("x", f"https://x.com/i/status/{status_id[:-1]}7"),
        ])[1], "both")
        self.assertEqual(merge._corroboration([
            ref("web", "https://a.example/news"), ref("x", "https://b.example/news"),
        ])[1], "both")
        # Over-collapse controls: a non-status X page, a look-alike host and a dot-segment escape
        # must NOT be absorbed into the post identity.
        for unrelated in (
            "https://x.com/nvidia",
            "https://x.com/nvidia/with_replies",
            "https://x.com/i/lists/" + status_id,
            "https://x.com/i/communities/" + status_id,
            "https://api.twitter.com/2/tweets/" + status_id,
            "https://mobile.twitter.com.evil.example/nvidia/status/" + status_id,
        ):
            with self.subTest(unrelated=unrelated):
                self.assertIsNone(xfetch._x_post_document_identity(unrelated))
        # Widening corroboration must not widen ADMISSION: the strict rule still refuses them all.
        for spelling in (
            f"https://x.com./nvidia/status/{status_id}",
            f"https://x.com/nvidia/statuses/{status_id}",
            f"http://x.com/nvidia/status/{status_id}",
            f"https://x.com/nvidia/status/{status_id}/photo/1",
            f"https://www.x.com/nvidia/status/{status_id}",
            f"https://x.com/status/{status_id}",
            f"https://x.com//status/{status_id}",
        ):
            with self.subTest(admission=spelling):
                self.assertIsNone(xfetch._x_status_identity(spelling))
        # A tail may not smuggle a SECOND post id out: the leftmost pair wins.
        self.assertEqual(
            xfetch._x_post_document_identity(f"https://x.com/n/status/{status_id}/status/999"),
            status_id,
        )
        # Planted failure: with the identity collapsed back to the raw hash suffix, the first
        # assertion above must die.
        with mock.patch.object(
            merge, "_document_identity", lambda ref: ref["source_id"].split(":", 1)[1],
        ):
            self.assertEqual(merge._corroboration([
                web_sighting, ref("x", f"https://x.com/i/status/{status_id}"),
            ])[1], "both")
        # A ref that lost its locator must fail CLOSED (collapse to one shared identity), not
        # silently revert to the hash suffix and mint `both` again.
        self.assertEqual(merge._corroboration([
            {k: v for k, v in web_sighting.items() if k != "canonical_locator"},
            {k: v for k, v in ref("x", f"https://x.com/i/status/{status_id}").items()
             if k != "canonical_locator"},
        ])[1], "single")

    def test_k3_r98_the_producer_owns_no_filesystem_deletion_path(self):
        """K3-R98: the receipt is the only authority on which raws count as evidence.

        A producer-side delete sits outside the lane's single write door (enforced AST-side by
        `LaneWriteDoorConformance`) and could destroy the paid bytes of a run whose publish failed,
        so no such helper may exist here at all.
        """
        self.assertFalse(hasattr(xfetch, "_prune_unreferenced_provider_responses"))
        source = (web.ROOT / "runners" / "us_short_llm_theme_discovery_fetch_x.py").read_text(encoding="utf-8")
        for primitive in (".unlink(", ".rmdir(", "os.remove(", "shutil.rmtree("):
            self.assertNotIn(primitive, source)

    def test_k3_r97_one_failed_provider_call_does_not_void_its_paid_siblings(self):
        """K3-R97: a query whose provider call never completed consumes no completed ordinal."""
        with temporary_provider_directory(web.ROOT) as td:
            raw_root = Path(td) / "x"
            transport, ticket = self._forge_x_live_label_by_closure(completed=0)
            reply = {
                "text": '{"themes":[]}', "results": [], "annotation_urls": [],
                "raw_response": self._live_raw_response("paid-sibling"),
                "model_identity": {"served_model": "grok-4.3", "system_fingerprint": "fp"},
            }

            class FirstQueryFails:
                def search(self, query, expected_date):
                    if query == "q0":
                        raise xfetch.XThemeDiscoveryError("Grok X request failed: APIStatusError")
                    transport._record_completed_response("xai")
                    return dict(reply)

            outcome = xfetch.execute_live_x_orchestration(
                queries=["q0", "q1"], expected_decision_date="20260725", client=FirstQueryFails(),
            )
            self.assertEqual(len(outcome["raw_provider_responses"]), 1)
            _, receipt, _ = xfetch.build_x_fetch_packet(
                queries=["q0", "q1"], results=outcome["results"],
                grok_response=outcome["grok_response"],
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                fetched_at="2026-07-25T08:00:00Z",
                raw_root=raw_root, persist_raw=True, execution_mode="live_authorized",
                _live_transport=transport, _live_ticket=ticket,
                extra_drop_ledger=outcome["query_drops"],
                raw_provider_responses=outcome["raw_provider_responses"],
                grok_model_identity=outcome["grok_model_identity"],
                grok_attempted=outcome["grok_attempted"], grok_failed=outcome["grok_failed"],
            )
            self.assertEqual(len(receipt["provider_response_refs"]), 1)
            self.assertEqual(receipt["provider_response_refs"][0]["response_index"], 0)
            self.assertTrue((web.ROOT / receipt["provider_response_refs"][0]["raw_receipt_ref"]).is_file())
            self.assertIn("provider_response_dropped", {row["reason"] for row in receipt["drop_ledger"]})

    def test_k3_r97_unaccountable_response_record_is_ledgered_not_raised(self):
        """K3-R97: an out-of-range or duplicate record becomes a ledger row, never a batch abort."""
        with temporary_provider_directory(web.ROOT) as td:
            drops: list[dict] = []
            refs = xfetch._provider_response_refs(
                [{"response_index": 4, "response": self._live_raw_response("later-call")}],
                raw_root=Path(td) / "x", persist_raw=True, execution_mode="live_authorized",
                completed_response_count=1, expected_decision_date="20260725",
                fetched_at=datetime(2026, 7, 25, 8, tzinfo=timezone.utc),
                pending_raw_writes=[], drops=drops,
            )
            self.assertEqual(refs, [])
            reasons = {row["reason"] for row in drops}
            self.assertIn("provider_response_record_unaccounted", reasons)
            self.assertIn("provider_response_capture_unavailable", reasons)
            self.assertEqual(
                [row.get("provider_response_index") for row in drops
                 if row["reason"] in xfetch.PROVIDER_RESPONSE_DROP_REASONS], [0],
            )

    def test_k3_r89_ordinary_secret_word_is_safe_persisted_evidence(self):
        self.assertTrue(xfetch._provider_response_is_safe({"text": "CEG's secret weapon is its nuclear fleet"}))
        self.assertFalse(xfetch._provider_response_is_safe({"api_key": "value-shaped-credential"}))

    def test_k3_r90_one_annotation_mints_one_annotation_bound_identity(self):
        status_id = "1937910118252712411"
        annotation = f"https://x.com/i/status/{status_id}"
        sources = [
            {"url": f"https://x.com/handle{index}/status/{status_id}?variant={index}", "title": "Power", "text": "CEG demand", "created_at": "2026-07-24T10:00:00Z"}
            for index in range(24)
        ]
        discovery, receipt, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=[], grok_response=json.dumps({
                "sources": sources,
                "themes": [{
                    "theme_id": "power_demand", "display_name": "Power", "summary": "Power",
                    "observed_at": "2026-07-24T12:00:00Z", "source_urls": [sources[0]["url"]],
                    "members": [{"ticker": "CEG", "source_urls": [sources[0]["url"]]}],
                }],
            }),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            provider_annotation_urls=[annotation],
        )
        self.assertEqual(len(receipt["source_refs"]), 1)
        self.assertEqual(receipt["source_refs"][0]["canonical_locator"], annotation)
        self.assertEqual(discovery["themes"][0]["source_ref_ids"], [receipt["source_refs"][0]["source_id"]])
        self.assertEqual(discovery["themes"][0]["members"][0]["source_ref_ids"], [receipt["source_refs"][0]["source_id"]])
        for invalid in (
            f"https://x.com./i/status/{status_id}",
            f"https://x.com:8443/i/status/{status_id}",
            f"https://sub.x.com/i/status/{status_id}",
        ):
            self.assertIsNone(xfetch._x_status_identity(invalid))
        _, non_x_receipt, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=[],
            grok_response=json.dumps({
                "sources": [{
                    "url": "https://example.com/not-an-x-status", "title": "Power",
                    "text": "CEG demand", "created_at": "2026-07-24T10:00:00Z",
                }],
                "themes": [],
            }),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            provider_annotation_urls=["https://example.com/not-an-x-status"],
        )
        self.assertEqual(non_x_receipt["source_refs"], [])
        self.assertIn(
            "model_source_url_not_provider_annotated",
            {row["reason"] for row in non_x_receipt["drop_ledger"]},
        )

    def test_k3_r91_provider_attempt_receipts_are_projected_from_retry_evidence(self):
        _, receipt, _ = xfetch.build_x_fetch_packet(
            queries=["q"], results=[], grok_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        receipt["fetch_contract"].update(
            execution_mode="live_authorized", network_access_performed=True,
            provider_calls_performed=True, network_call_count=1, provider_call_count=1,
            transport_response_counts={"xai": 1},
        )
        receipt["provider_response_refs"] = [{"response_sha256": "a" * 64}]
        receipt["provider_annotation_urls"] = ["https://x.com/i/status/1"]
        projected = web._live_receipt_retry_evidence(receipt)
        self.assertNotIn("provider_response_refs", projected)
        self.assertNotIn("provider_annotation_urls", projected)

    def test_k3_r92_mismatch_urls_are_sanitized_and_annotation_set_is_stored_once(self):
        annotations = [f"https://x.com/i/status/{index}?email=user{index}%40example.com&uid={index}" for index in range(10, 16)]
        sources = [
            {"url": f"https://x.com/u/status/{index}?email=alice%40example.com&uid=99", "title": "Power", "text": "CEG", "created_at": "2026-07-24T10:00:00Z"}
            for index in range(20, 26)
        ]
        _, receipt, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=[], grok_response=json.dumps({"sources": sources, "themes": []}),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            provider_annotation_urls=annotations,
        )
        mismatch = [row for row in receipt["drop_ledger"] if row["reason"] == "model_source_url_not_provider_annotated"]
        self.assertEqual(len(receipt["provider_annotation_urls"]), len(annotations))
        self.assertTrue(all("provider_annotation_urls" not in row for row in mismatch))
        self.assertTrue(all(row["provider_annotation_set_ref"] == "provider_annotation_urls" for row in mismatch))
        serialized = json.dumps(receipt, ensure_ascii=False)
        self.assertNotIn("email=", serialized)
        self.assertNotIn("uid=", serialized)

    def test_k3_r93_merge_rejects_missing_or_redigested_provider_raw_response(self):
        with temporary_provider_directory(web.ROOT) as td:
            raw_root = Path(td) / "x"
            transport, ticket = self._forge_x_live_label_by_closure()
            xa, xr, _ = xfetch.build_x_fetch_packet(
                queries=["q"], results=[], grok_response='{"themes":[]}',
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=raw_root, persist_raw=True, execution_mode="live_authorized",
                _live_transport=transport, _live_ticket=ticket,
                raw_provider_responses=[self._live_raw_response("merge-bound")],
            )
            wa, wr, _ = web.build_web_fetch_packet(
                queries=["q"], search_results=[], llm_response='{"themes":[]}',
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            )
            def merge_packet():
                return merge_web_x_discovery(
                    web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr,
                    expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                )

            merge_packet()
            raw_ref = xr["provider_response_refs"][0]
            raw_path = web.ROOT / raw_ref["raw_receipt_ref"]
            original = raw_path.read_bytes()

            original_refs = xr["provider_response_refs"]
            xr["provider_response_refs"] = []
            with self.assertRaises(ThemeDiscoveryMergeError):
                merge_packet()
            xr["drop_ledger"].append({
                "stage": "search_result", "reason": "provider_response_capture_unavailable",
                "detail": "response[0]:test_control", "provider_response_index": 0,
            })
            merge_packet()
            xr["drop_ledger"].pop()
            xr["provider_response_refs"] = original_refs

            annotations = xr.pop("provider_annotation_urls")
            with self.assertRaises(ThemeDiscoveryMergeError):
                merge_packet()
            xr["provider_annotation_urls"] = annotations

            original_ref = raw_ref["raw_receipt_ref"]
            parts = list(PurePosixPath(original_ref).parts)
            date_index = parts.index("20260725")
            raw_ref["raw_receipt_ref"] = PurePosixPath(
                *parts[:date_index], "lexical_alias", "..", *parts[date_index:]
            ).as_posix()
            with self.assertRaises(ThemeDiscoveryMergeError):
                merge_packet()
            raw_ref["raw_receipt_ref"] = original_ref

            other_namespace = raw_path.parent.parent.parent / "other_namespace" / "20260725" / raw_path.name
            other_namespace.parent.mkdir(parents=True, exist_ok=True)
            other_namespace.write_bytes(original)
            raw_ref["raw_receipt_ref"] = web._repo_relative(other_namespace)
            with self.assertRaises(ThemeDiscoveryMergeError):
                merge_packet()
            raw_ref["raw_receipt_ref"] = original_ref

            generated_later = json.loads(original.decode("utf-8"))
            generated_later["fetched_at"] = "2026-07-25T08:01:00Z"
            raw_path.write_text(json.dumps(generated_later), encoding="utf-8")
            raw_ref["fetched_at"] = generated_later["fetched_at"]
            with self.assertRaises(ThemeDiscoveryMergeError):
                merge_packet()
            raw_ref["fetched_at"] = json.loads(original.decode("utf-8"))["fetched_at"]

            post_open = json.loads(original.decode("utf-8"))
            post_open["fetched_at"] = "2026-07-25T13:30:00Z"
            raw_path.write_text(json.dumps(post_open), encoding="utf-8")
            raw_ref["fetched_at"] = post_open["fetched_at"]
            with self.assertRaises(ThemeDiscoveryMergeError):
                merge_packet()
            raw_ref["fetched_at"] = json.loads(original.decode("utf-8"))["fetched_at"]

            raw_path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ThemeDiscoveryMergeError):
                merge_packet()
            tampered = json.loads(original.decode("utf-8"))
            tampered["response"]["id"] = "redigested"
            raw_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaises(ThemeDiscoveryMergeError):
                merge_packet()
            raw_path.write_bytes(original)
            raw_path.unlink()
            with self.assertRaises(ThemeDiscoveryMergeError):
                merge_packet()

    def test_captured_grok_response_shape_routes_only_annotation_backed_transcript(self):
        """Unfreeze step ②: pin the captured Grok shape, not a guessed result-row API."""
        url = "https://x.com/example/status/1"
        transcript = json.dumps({
            "sources": [{
                "url": url, "title": "Power", "text": "CEG demand rises",
                "created_at": "2026-07-24T10:00:00Z",
            }],
            "themes": [{
                "theme_id": "power_demand", "display_name": "Power", "summary": "Power",
                "observed_at": "2026-07-24T12:00:00Z", "source_urls": [url],
                "members": [{"ticker": "CEG", "source_urls": [url]}],
            }],
        })
        response = SimpleNamespace(
            output_text=transcript,
            results=None,
            citations=None,
            output=[SimpleNamespace(content=[SimpleNamespace(annotations=[
                SimpleNamespace(type="url_citation", url=url, title=url, start_index=0, end_index=1),
            ])])],
        )

        self.assertEqual(xfetch._response_text(response), transcript)
        self.assertEqual(xfetch._provider_result_rows(response), [])
        annotation_urls = xfetch._provider_annotation_urls(response)
        self.assertEqual(annotation_urls, [url])

        discovery, receipt, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=[], grok_response=xfetch._response_text(response),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            provider_annotation_urls=annotation_urls,
        )
        self.assertEqual(receipt["source_refs"][0]["evidence_attestation"], "model_transcribed")
        self.assertEqual(discovery["themes"][0]["members"][0]["ticker"], "CEG")

        _, unbacked_receipt, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=[], grok_response=xfetch._response_text(response),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            provider_annotation_urls=[],
        )
        self.assertEqual(unbacked_receipt["source_refs"], [])
        self.assertIn(
            "model_source_url_not_provider_annotated",
            {row["reason"] for row in unbacked_receipt["drop_ledger"]},
        )

        class OrchestrationClient:
            def search(self, query, expected):
                return {"text": transcript, "results": [], "annotation_urls": [url]}

        outcome = xfetch.execute_live_x_orchestration(
            queries=["power"], expected_decision_date="20260725", client=OrchestrationClient(),
        )
        discovery, receipt, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=outcome["results"], grok_response=outcome["grok_response"],
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            provider_annotation_urls=outcome["annotation_urls"],
        )
        self.assertEqual(receipt["source_refs"][0]["evidence_attestation"], "model_transcribed")
        self.assertEqual(discovery["themes"][0]["members"][0]["ticker"], "CEG")

    def test_x_model_transcript_enforces_decision_week_window(self):
        """K3-R68: annotation-backed transcription still needs the sibling lane's week floor."""
        url = "https://x.com/ceg/status/1937910118252712411"

        def packet(created_at):
            response = json.dumps({
                "sources": [{"url": url, "title": "CEG", "text": "CEG demand rises", "created_at": created_at}],
                "themes": [{"theme_id": "power_demand", "display_name": "Power", "summary": "Power", "observed_at": created_at, "source_urls": [url], "members": [{"ticker": "CEG", "source_urls": [url]}]}],
            })
            return xfetch.build_x_fetch_packet(
                queries=["power"], results=[], grok_response=response,
                expected_decision_date="20260727", generated_at="2026-07-27T12:00:00Z",
                provider_annotation_urls=[url],
            )

        _, stale, _ = packet("2026-03-02T13:22:06Z")
        self.assertEqual(stale["summary"]["accepted_source_count"], 0)
        self.assertIn("published_at_outside_decision_week", {row["reason"] for row in stale["drop_ledger"]})
        for created_at in ("2026-07-24T13:22:06Z", "2026-07-26T12:00:00Z"):
            with self.subTest(created_at=created_at):
                _, accepted, _ = packet(created_at)
                self.assertEqual(accepted["summary"]["accepted_source_count"], 1)

        with mock.patch.object(web, "_decision_week_start", return_value=xfetch._parse_dt("2000-01-01T00:00:00Z", "week_start")):
            _, without_floor, _ = packet("2026-03-02T13:22:06Z")
        self.assertEqual(without_floor["summary"]["accepted_source_count"], 1)

    def test_x_unverified_results_or_citations_shapes_fail_closed_to_annotation_only(self):
        """K3-R34 Optional (c): guessed dict fields cannot become provider-attested rows."""
        url = "https://x.example/annotation-only"
        response = SimpleNamespace(
            output_text='{"themes":[]}', results={"url": url}, citations={"url": url},
            output=[SimpleNamespace(content=[SimpleNamespace(annotations=[
                SimpleNamespace(type="url_citation", url=url),
            ])])],
        )
        self.assertEqual(xfetch._provider_result_rows(response), [])
        self.assertEqual(xfetch._provider_annotation_urls(response), [url])
        with mock.patch.object(response, "results", [{"url": url, "title": "P", "text": "CEG", "created_at": "2026-07-24T12:00:00Z"}]):
            rows = xfetch._provider_result_rows(response)
        self.assertEqual(rows[0]["_evidence_attestation"], "provider_attested")

    def test_x_live_mode_requires_confirmation_then_reserves_before_orchestration(self):
        with mock.patch.object(xfetch.os.environ, "get", side_effect=AssertionError("key lookup reached")) as key_lookup:
            with self.assertRaisesRegex(xfetch.XThemeDiscoveryError, "requires --confirm-user-authorization"):
                xfetch.run_x_fetch(
                    queries=["power"], expected_decision_date="20260725",
                    generated_at="2026-07-25T08:00:00Z", live=True,
                )
        key_lookup.assert_not_called()

        order: list[str] = []
        outcome = {
            "results": [], "grok_response": '{"themes":[]}', "query_drops": [],
            "fetched_at": datetime(2026, 7, 25, 8, tzinfo=timezone.utc), "annotation_urls": [],
            "grok_model_identity": xfetch._grok_model_identity(), "grok_attempted": False, "grok_failed": False,
        }
        with (
            mock.patch.object(xfetch.os.environ, "get", return_value="xai-" + "x" * 40),
            mock.patch.object(xfetch.web, "_reserve_provider_budget", side_effect=lambda *_args, **_kwargs: order.append("reserve")),
            mock.patch.object(xfetch, "GrokXSearchClient"),
            mock.patch.object(xfetch, "execute_live_x_orchestration", side_effect=lambda **_: order.append("orchestrate") or outcome),
            mock.patch.object(xfetch, "build_x_fetch_packet", return_value=({}, {}, {})),
        ):
            xfetch.run_x_fetch(
                queries=["power"], expected_decision_date="20260725",
                generated_at="2026-07-25T08:00:00Z", confirm_user_authorization=True, live=True,
            )
        self.assertEqual(order, ["reserve", "orchestrate"])

    def test_x_live_receipt_binds_grok_requested_and_served_model(self):
        """K3-R69: model aliases are not replayable evidence without provider-served identity."""
        identity = xfetch._grok_model_identity(
            served_model="grok-4.5", system_fingerprints=["fp-b", "fp-a", "fp-a"],
        )
        _, receipt, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=X_ROWS, grok_response=self._x_response(),
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            grok_model_identity=identity, grok_attempted=True,
        )
        self.assertEqual(receipt["fetch_contract"]["grok_model"], {
            "requested_model": xfetch.GROK_MODEL,
            "served_model": "grok-4.5",
            "system_fingerprints": ["fp-a", "fp-b"],
        })

        self.assertIsNone(xfetch._grok_model_identity()["served_model"])

    def test_x_orchestration_carries_provider_model_identity_into_live_receipt(self):
        class Client:
            def search(self, query, expected):
                return {
                    "text": self_response, "results": X_ROWS, "annotation_urls": [],
                    "model_identity": {"served_model": "grok-4.5", "system_fingerprint": "fp-live"},
                }

        self_response = self._x_response()
        outcome = xfetch.execute_live_x_orchestration(
            queries=["power"], expected_decision_date="20260725", client=Client(),
        )
        _, receipt, _ = xfetch.build_x_fetch_packet(
            queries=["power"], results=outcome["results"], grok_response=outcome["grok_response"],
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
            grok_model_identity=outcome["grok_model_identity"],
            grok_attempted=outcome["grok_attempted"], grok_failed=outcome["grok_failed"],
        )
        self.assertEqual(receipt["fetch_contract"]["grok_model"], {
            "requested_model": xfetch.GROK_MODEL,
            "served_model": "grok-4.5",
            "system_fingerprints": ["fp-live"],
        })

    def test_x_direct_builder_rejects_a_minted_completed_live_transport(self):
        transport = _TransportProbe("xai")
        transport._record_completed_response("xai")
        for _ in range(2):
            with self.assertRaisesRegex(xfetch.XThemeDiscoveryError, "response-derived runner transport"):
                xfetch.build_x_fetch_packet(
                    queries=["power"], results=[], grok_response='{"themes":[]}',
                    expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                    execution_mode="live_authorized", _live_transport=transport, _live_ticket=object(),
                )

    def test_x_runner_ticket_is_consumed_and_cannot_replay_a_live_receipt(self):
        self.assertFalse(hasattr(xfetch, "_issue_live_ticket"))
        self.assertNotIn("_issue_ticket", xfetch.run_x_fetch.__kwdefaults__ or {})
        transport = _TransportProbe("xai")
        transport._record_completed_response("xai")
        args = {
            "queries": ["power"], "results": [], "grok_response": '{"themes":[]}',
            "expected_decision_date": "20260725", "generated_at": "2026-07-25T08:00:00Z",
            "execution_mode": "live_authorized", "_live_transport": transport,
            "_live_ticket": object(),
        }
        for _ in range(2):
            with self.assertRaisesRegex(xfetch.XThemeDiscoveryError, "response-derived runner transport"):
                xfetch.build_x_fetch_packet(**args)

    def test_x_live_runner_closure_can_authorize_its_own_completed_transport_once(self):
        class Client:
            def __init__(self, *_args, _live_transport=None, **_kwargs):
                self._live_transport = _live_transport

        def orchestration(*, client, **_kwargs):
            client._live_transport._record_completed_response("xai")
            return {
                "results": [], "grok_response": '{"themes":[]}', "query_drops": [],
                "fetched_at": datetime(2026, 7, 25, 8, tzinfo=timezone.utc), "annotation_urls": [],
                "raw_provider_responses": [self._live_raw_response("resp-zero-accepted")],
                "grok_model_identity": xfetch._grok_model_identity(),
                "grok_attempted": False, "grok_failed": False,
            }

        with (
            mock.patch.object(xfetch, "_require_single_xai_api_key", return_value="xai-" + "a" * 40),
            mock.patch.object(xfetch.web, "_reserve_provider_budget"),
            mock.patch.object(xfetch, "GrokXSearchClient", Client),
            mock.patch.object(xfetch, "execute_live_x_orchestration", side_effect=orchestration),
        ):
            _, receipt, _ = xfetch.run_x_fetch(
                queries=["power"], expected_decision_date="20260725",
                generated_at="2026-07-25T08:00:00Z", confirm_user_authorization=True, live=True,
                raw_root=self._raw_path / "x_live_zero",
            )
        self.assertEqual(receipt["fetch_contract"]["execution_mode"], "live_authorized")
        self.assertEqual(receipt["fetch_contract"]["transport_response_counts"], {"xai": 1})
        self.assertEqual(receipt["source_refs"], [])
        self.assertEqual(len(receipt["provider_response_refs"]), 1)
        raw_ref = receipt["provider_response_refs"][0]
        raw_payload = json.loads((web.ROOT / raw_ref["raw_receipt_ref"]).read_text(encoding="utf-8"))
        self.assertEqual(raw_payload["response"], self._live_raw_response("resp-zero-accepted"))
        self.assertEqual(raw_ref["response_sha256"], hashlib.sha256(web._canonical_json(raw_payload["response"])).hexdigest())
    def test_raw_ticker_match_requires_uppercase_bare_form_or_explicit_cashtag(self):
        prose = {"source_type": "web", "title": "", "content": "The market had a mixed session. It closed on a soft note, so all eyes are on Friday."}
        uppercase = {"source_type": "web", "title": "CEG expands generation", "content": ""}
        lowercase = {"source_type": "web", "title": "ceg expands generation", "content": ""}
        cashtag = {"source_type": "web", "title": "$ceg expands generation", "content": ""}

        def assert_case_rule() -> None:
            for ticker in ("A", "IT", "ON", "SO", "ALL"):
                self.assertFalse(merge._raw_payload_mentions_ticker(prose, ticker))
            self.assertTrue(merge._raw_payload_mentions_ticker(uppercase, "CEG"))
            self.assertFalse(merge._raw_payload_mentions_ticker(lowercase, "CEG"))
            self.assertTrue(merge._raw_payload_mentions_ticker(cashtag, "CEG"))

        assert_case_rule()
        with mock.patch.object(
            merge,
            "_evidence_mentions_canonical_ticker",
            side_effect=lambda evidence, canonical: __import__("re").search(
                rf"(?<![A-Z0-9])(?:\\$)?{canonical}(?![A-Z0-9])", evidence, __import__("re").I,
            ) is not None,
        ):
            with self.assertRaises(AssertionError):
                assert_case_rule()

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
        def raw_pair(td):
            wa, wr, _ = web.build_web_fetch_packet(
                queries=["power"], search_results=[{"url": "https://web.example/live", "title": "A", "content": "AAPL", "published_date": "2026-07-24T10:00:00Z"}],
                llm_response='{"themes":[]}', expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=Path(td) / "web", persist_raw=True)
            xa, xr, _ = xfetch.build_x_fetch_packet(
                queries=["power"], results=[{"url": "https://x.example/live", "title": "P", "text": "AAPL", "created_at": "2026-07-24T10:00:00Z"}],
                grok_response='{"themes":[]}', expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                raw_root=Path(td) / "x", persist_raw=True)
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
                    temporary_provider_directory(web.ROOT) as td:
                wa, wr, xa, xr = raw_pair(td)
                receipt, artifact = (wr, wa) if lane == "web" else (xr, xa)
                merge_pair(wa, wr, xa, xr)      # reverse control: the untouched pair merges
                raw_path = web.ROOT / receipt["source_refs"][0]["raw_receipt_ref"]
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                raw[time_key] = "2026-07-25T15:00:00+00:00"
                rehash(receipt, artifact, raw_path, raw)
                with self.assertRaises(ThemeDiscoveryMergeError):
                    merge_pair(wa, wr, xa, xr)
            with self.subTest(lane=lane, defect="forged source identity"), \
                    temporary_provider_directory(web.ROOT) as td:
                wa, wr, xa, xr = raw_pair(td)
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
                    temporary_provider_directory(web.ROOT) as td:
                wa, wr, xa, xr = raw_pair(td)
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
                        temporary_provider_directory(web.ROOT) as td:
                    wa, wr, xa, xr = raw_pair(td)
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

    def test_merge_rehashes_frozen_raw_receipts(self):
        with temporary_provider_directory(web.ROOT) as td:
            root = Path(td)
            wa, wr, _ = web.build_web_fetch_packet(
                queries=["power"], search_results=[{"url": "https://web.example/live", "title": "A", "content": "AAPL", "published_date": "2026-07-24T10:00:00Z"}], llm_response='{"themes":[]}',
                expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z", raw_root=root / "web", persist_raw=True,
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
