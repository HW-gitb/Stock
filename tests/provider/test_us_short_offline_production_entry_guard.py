"""Permanent offline regression guard for the real US-short producer entrances.

This intentionally calls only ``run_web_fetch`` and ``run_x_fetch``.  It exists
to prevent the K3-R62/R64/R67 class from being hidden by builder-only fixtures.
"""
from __future__ import annotations

import copy
import json
import tempfile
import uuid
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from engine import us_short_provisional_theme_boost as boost
from engine import us_short_llm_theme_discovery_paid_gateway as paid_gateway
from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from runners import us_short_llm_theme_discovery as discovery_writer
from runners import us_short_llm_theme_discovery_merge as merge
from runners import us_short_provisional_theme_validate as knife2
from runners import us_short_batch5_full_universe_sec_sic_classification_fetch as sic_fetch
from runners import us_short_llm_theme_discovery_web_regroup_replay as replay
from tests.provider.us_short_private_test_root_light import temporary_provider_directory


DATE = "20260725"
GENERATED = "2026-07-25T08:00:00Z"
TICKERS = ("AAPL", "MSFT", "JPM")


class _FakeSearch:
    def __init__(self, rows):
        self.rows = rows

    def search(self, _query):
        return list(self.rows)


class _FakeDeepSeek:
    def __init__(self, text):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_kwargs: self._response(text)
            )
        )

    @staticmethod
    def _response(text):
        payload = {
            "model": "deepseek-test",
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": None,
            "system_fingerprint": None,
        }
        return SimpleNamespace(
            model=payload["model"],
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=text), finish_reason="stop",
            )],
            usage=None,
            system_fingerprint=None,
            model_dump=lambda mode="json": payload,
        )


class _FakeX:
    def __init__(self, rows, text):
        self.rows = rows
        self.text = text

    def search(self, query, _expected_date):
        index = {"aapl": 0, "msft": 1, "jpm": 2, "nvda": 3}[query.lower()]
        return {"text": self.text, "results": [self.rows[index]]}


def _theme_payload(*, source_urls, source_type, tickers=TICKERS):
    source_ids = [
        web._source_id(url) if source_type == "web" else xfetch._source_id(url)
        for url in source_urls
    ]
    ref_key = "source_ref_ids" if source_type == "web" else "source_urls"
    return json.dumps({
        "themes": [{
            "theme_id": "power_demand", "display_name": "Power demand",
            "summary": "Power demand", "observed_at": "2026-07-24T12:00:00Z",
            "source_urls": list(source_urls),
            "source_ref_ids": source_ids,
            "members": [
                {"ticker": ticker, ref_key: list(source_ids if source_type == "web" else [source_urls[index]])}
                for index, ticker in enumerate(tickers)
            ],
            "semantic_assertions": [{
                "basis": "shared_commercial_driver",
                "basis_explanation": "Power demand reaches all three linked issuers.",
                "common_driver": {"driver_statement": "Power demand is increasing.", "transmission_mechanism": "Load growth drives infrastructure spending.", ref_key: list(source_ids if source_type == "web" else source_urls)},
                "member_links": [{"ticker": ticker, "role": "beneficiary", "link_statement": "The issuer is linked to the common demand.", ref_key: list(source_ids if source_type == "web" else [source_urls[index]])} for index, ticker in enumerate(tickers)],
            }],
        }]
    })


class OfflineProductionEntryGuardTests(unittest.TestCase):
    def setUp(self):
        # Frozen raw receipts are immutable by design, so a shared root makes any re-use of a
        # source URL collide across runs as `immutable_raw_content_conflict` and silently drop
        # every source.  A per-test root makes that structurally impossible instead of relying
        # on each author remembering to mint unique URLs.
        self._raw_tempdir = temporary_provider_directory(web.ROOT)
        self._raw_root = Path(self._raw_tempdir.__enter__())

    def tearDown(self):
        self._raw_tempdir.__exit__(None, None, None)

    def _packets(self, *, cat_aapl=False, x_tickers=None, web_source_count=1,
                 unknown_member_ref=False):
        token = uuid.uuid4().hex
        packet_tickers = tuple(x_tickers or (TICKERS + ("NVDA",) if cat_aapl else TICKERS))
        web_url = f"https://web.example/k3-permanent-{token}"
        web_urls = [
            web_url if index == 0 else f"https://web.example/k3-permanent-{token}-extra-{index}"
            for index in range(web_source_count)
        ]
        x_urls = [f"https://x.example/k3-permanent-{token}-{ticker.lower()}" for ticker in packet_tickers]
        web_rows = [{
            "url": url, "title": "Power demand", "content": "AAPL MSFT JPM power demand",
            "published_date": "2026-07-24T10:00:00Z",
        } for url in web_urls]
        x_rows = [{
            "url": x_urls[index], "title": ("X post" if cat_aapl and index == 0 else ticker), "text": (
                "totally unrelated cat photo" if cat_aapl and index == 0
                else f"{ticker} power demand"
            ), "created_at": "2026-07-24T10:00:00Z",
        } for index, ticker in enumerate(packet_tickers)]
        web_payload = json.loads(_theme_payload(source_urls=web_urls, source_type="web"))
        if unknown_member_ref:
            web_payload["themes"][0]["members"][0]["source_ref_ids"].append(
                "web:" + "f" * 64
            )
        x_payload = _theme_payload(source_urls=x_urls, source_type="x", tickers=packet_tickers)
        web_artifact, web_receipt, web_summary = web.run_web_fetch(
            queries=["power"], expected_decision_date=DATE, generated_at=GENERATED,
            search_client=_FakeSearch(web_rows), deepseek_client=_FakeDeepSeek(json.dumps(web_payload)),
            raw_root=self._raw_root / "web",
        )
        x_artifact, x_receipt, x_summary = xfetch.run_x_fetch(
            queries=list(packet_tickers), expected_decision_date=DATE, generated_at=GENERATED,
            x_client=_FakeX(x_rows, x_payload), raw_root=self._raw_root / "x",
        )
        return (web_artifact, web_receipt, web_summary,
                x_artifact, x_receipt, x_summary)

    def _validation_and_boost(self, packets, *, discovery_mutator=None):
        web_artifact, web_receipt, _, x_artifact, x_receipt, _ = packets
        merged, manifest = merge.merge_web_x_discovery(
            web_artifact=web_artifact, web_receipt=web_receipt,
            x_artifact=x_artifact, x_receipt=x_receipt,
            expected_decision_date=DATE, generated_at=GENERATED,
        )
        discovery = merge._ingest_input(merged)
        if discovery_mutator is not None:
            discovery_mutator(discovery)
        eligible = {
            member["ticker"]
            for theme in x_artifact["themes"]
            for member in theme["members"]
        }
        sectors = {
            "AAPL": "10", "MSFT": "20", "JPM": "30", "NVDA": "10",
        }
        artifact = knife2.build_artifact(
            {
                "discovery": discovery,
                "eligible": eligible,
                "universe": eligible,
                "sectors": sectors,
                "candidate": {
                    "decision_date": DATE,
                    "price_basis_date": "20260724",
                    "used_date": "2026-07-24",
                },
                "classification": {"decision_clock": {"source_as_of": "2026-07-24"}},
                "hashes": {
                    "discovery": "a" * 64,
                    "candidate": "b" * 64,
                    "classification": "c" * 64,
                },
            },
            generated_at=GENERATED,
        )
        digests = {
            "discovery_artifact_sha256": artifact["input_artifacts"]["discovery_artifact_sha256"],
            "candidate_artifact_sha256": artifact["input_artifacts"]["candidate_artifact_sha256"],
            "classification_packet_sha256": artifact["input_artifacts"]["classification_packet_sha256"],
        }
        boost_map = boost.build_provisional_theme_boost_map(
            artifact,
            target_tickers=sorted(eligible),
            expected_decision_date=DATE,
            expected_input_digests=digests,
        )
        return merged, manifest, artifact, boost_map

    @staticmethod
    def _event_basis(discovery):
        for theme in discovery["themes"]:
            for assertion in theme.get("semantic_assertions", []):
                assertion["basis"] = "shared_event_bucket"

    @staticmethod
    def _three_one_member_assertions(discovery):
        for theme in discovery["themes"]:
            assertions = theme.get("semantic_assertions", [])
            if not assertions:
                continue
            template = copy.deepcopy(assertions[0])
            members_by_ticker = {
                member["ticker"]: member for member in theme["members"]
            }
            theme["semantic_assertions"] = []
            for ticker in TICKERS:
                assertion = copy.deepcopy(template)
                assertion["member_links"] = [{
                    "ticker": ticker,
                    "role": "beneficiary",
                    "link_statement": "The issuer is linked to the common demand.",
                    "source_ref_ids": list(members_by_ticker[ticker]["source_ref_ids"]),
                }]
                theme["semantic_assertions"].append(assertion)
            return

    @staticmethod
    def _member_link_borrows_source(discovery):
        theme = discovery["themes"][0]
        web_refs = [ref for ref in theme["source_ref_ids"] if ref.startswith("web:")]
        if len(web_refs) < 2:
            raise AssertionError("the cross-source fixture must contain two Web refs")
        aapl = next(member for member in theme["members"] if member["ticker"] == "AAPL")
        aapl["source_ref_ids"] = [web_refs[0]]
        for assertion in theme.get("semantic_assertions", []):
            for link in assertion.get("member_links", []):
                if link.get("ticker") == "AAPL":
                    link["source_ref_ids"] = [web_refs[1]]

    def _merge_and_knife2(self, packets):
        web_artifact, web_receipt, _, x_artifact, x_receipt, _ = packets
        merged, manifest = merge.merge_web_x_discovery(
            web_artifact=web_artifact, web_receipt=web_receipt,
            x_artifact=x_artifact, x_receipt=x_receipt,
            expected_decision_date=DATE, generated_at=GENERATED,
        )
        validated, drops = knife2.validate_provisional_themes(
            merge._ingest_input(merged),
            eligible_tickers={
                member["ticker"] for theme in x_artifact["themes"] for member in theme["members"]
            },
            sectors_by_ticker={"AAPL": "10", "MSFT": "20", "JPM": "30", "NVDA": "10"},
        )
        return manifest, validated, drops

    def test_production_offline_entries_are_load_bearing_for_genuine_and_cat_control(self):
        genuine = self._packets()
        self.assertGreater(genuine[2]["accepted_source_count"], 0)
        self.assertGreater(genuine[5]["accepted_source_count"], 0)
        manifest, validated, _ = self._merge_and_knife2(genuine)
        members = [member for theme in validated for member in theme["members"]]
        self.assertTrue(members)
        self.assertEqual({member["ticker"] for member in members}, set(TICKERS))
        self.assertTrue(all(member["evidence_tier"] == "both" for member in members))
        self.assertEqual(manifest["summary"]["both_member_count"], 3)

        cat = self._packets(cat_aapl=True)
        cat_manifest, cat_validated, _ = self._merge_and_knife2(cat)
        cat_members = {member["ticker"]: member for theme in cat_validated for member in theme["members"]}
        self.assertNotEqual(cat_members["AAPL"]["evidence_tier"], "both")
        # The X assertion has four members; pruning AAPL's bad link still leaves three
        # qualified links, so the two innocent original siblings keep their `both` tier.
        self.assertEqual(cat_members["MSFT"]["evidence_tier"], "both")
        self.assertEqual(cat_members["JPM"]["evidence_tier"], "both")
        self.assertGreater(cat_manifest["summary"]["member_evidence_demotion_count"], 0)

    def test_k4_01_real_entries_reach_semantic_validation_and_boost(self):
        _merged, _manifest, artifact, boost_map = self._validation_and_boost(self._packets())
        self.assertEqual(artifact["schema_version"], "1.2.0")
        self.assertEqual(len(artifact["themes"]), 1)
        self.assertEqual(
            {ticker: boost_map[ticker]["theme_soft_boost"] for ticker in TICKERS},
            {ticker: 5.0 for ticker in TICKERS},
        )
        single_artifact = self._validation_and_boost(self._packets(cat_aapl=True))[2:]
        single_map = single_artifact[1]
        self.assertEqual(single_map["AAPL"]["theme_soft_boost"], 2.0)
        self.assertEqual(max(row["theme_soft_boost"] for row in single_map.values()), 5.0)

    def test_k4_04_unknown_member_source_cannot_be_recovered_by_other_lane(self):
        packets = self._packets(unknown_member_ref=True)
        web_receipt = packets[1]
        unknown_row = next(
            row for row in web_receipt["member_binding_ledger"]
            if row["canonical_ticker"] == "AAPL"
        )
        self.assertEqual(unknown_row["binding_status"], "rejected")
        self.assertEqual(unknown_row["binding_reason"], "member_source_ref_not_in_chunk_sources")
        _merged, _manifest, artifact, boost_map = self._validation_and_boost(packets)
        self.assertEqual(len(artifact["themes"]), 1)
        self.assertEqual(boost_map["AAPL"]["theme_soft_boost"], 2.0)
        self.assertNotEqual(boost_map["AAPL"]["evidence_tier"], "both")

    def test_k4_05_cross_chunk_member_cannot_reach_merged_validation_or_boost(self):
        """A globally known source is still invalid when it belongs to another Web chunk."""
        x_packet = self._packets()[3:]
        clock = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)

        def build_web_packet(*, borrowed: bool):
            token = uuid.uuid4().hex
            search_results = [{
                "url": f"https://web.example/k4-cross-chunk-{token}-{index}",
                "title": "Power demand",
                "content": "AAPL MSFT JPM power demand",
                "published_date": "2026-07-24T10:00:00Z",
            } for index in range(20)]
            _refs, prompt_rows, _drops = web._normalize_search_results(
                search_results, expected_decision_date=DATE, fetched_at=clock,
                raw_root=None, persist_raw=False,
            )
            chunks = web._chunk_regroup_rows(prompt_rows)
            self.assertEqual(len(chunks), 2)
            chunk_source_ids = [
                [row["source_id"] for row in chunk] for chunk in chunks
            ]
            first_ids, second_ids = chunk_source_ids
            member_refs = {
                "AAPL": [second_ids[0] if borrowed else first_ids[0]],
                "MSFT": [first_ids[1]],
                "JPM": [first_ids[2]],
            }
            member_links = [{
                "ticker": ticker,
                "role": "beneficiary",
                "link_statement": "The issuer is linked to the common demand.",
                "source_ref_ids": refs,
            } for ticker, refs in member_refs.items() if not borrowed or ticker != "AAPL"]
            theme = {
                "theme_id": "power_demand",
                "display_name": "Power demand",
                "summary": "Power demand",
                "observed_at": "2026-07-24T10:00:00Z",
                "source_ref_ids": first_ids,
                "members": [
                    {"ticker": ticker, "source_ref_ids": refs}
                    for ticker, refs in member_refs.items()
                ],
                "semantic_assertions": [{
                    "basis": "shared_commercial_driver",
                    "basis_explanation": "Power demand reaches the linked issuers.",
                    "common_driver": {
                        "driver_statement": "Power demand is increasing.",
                        "transmission_mechanism": "Load growth drives infrastructure spending.",
                        "source_ref_ids": first_ids,
                    },
                    "member_links": member_links,
                }],
            }
            response = _FakeDeepSeek._response(json.dumps({"themes": [theme]}))
            raw_root = self._raw_root / ("k4-cross-chunk-borrowed" if borrowed else "k4-cross-chunk-valid")
            transport = paid_gateway.new_transport("tavily", "deepseek")
            transport._record_completed_response("tavily")
            transport._record_completed_response("deepseek")
            transport._record_completed_response("deepseek")
            provider_response_refs = [
                web._persist_deepseek_response(
                    response, raw_root=raw_root, expected_decision_date=DATE,
                    chunk_index=index, fetched_at=clock,
                )
                for index in range(2)
            ]
            ticket = paid_gateway.issue_ticket()
            try:
                packet = web.build_web_fetch_packet(
                    queries=["power"], search_results=search_results,
                    llm_response=json.dumps({"themes": []}),
                    expected_decision_date=DATE, generated_at=clock.isoformat(),
                    fetched_at=clock.isoformat(), raw_root=raw_root, persist_raw=True,
                    execution_mode="live_authorized", network_access_performed=True,
                    provider_calls_performed=True, _live_transport=transport,
                    _live_ticket=ticket,
                    regroup_model_identity=web._regroup_model_identity(
                        served_model="deepseek-test",
                    ),
                    regroup_attempted=True, regroup_chunk_counts={
                        "attempted": 2, "successful": 2, "failed": 0,
                        "failed_indexes": [],
                    },
                    provider_response_refs=provider_response_refs,
                    regroup_chunks=[
                        {
                            "chunk_index": 0, "themes": [theme],
                            "input_source_ids": chunk_source_ids[0],
                        },
                        {
                            "chunk_index": 1, "themes": [],
                            "input_source_ids": chunk_source_ids[1],
                        },
                    ],
                )
            finally:
                paid_gateway.revoke_ticket(ticket)
            return packet

        valid = build_web_packet(borrowed=False)
        _merged, _manifest, _artifact, valid_boost = self._validation_and_boost(
            (*valid, *x_packet),
        )
        self.assertEqual(valid_boost["AAPL"]["theme_soft_boost"], 5.0)

        borrowed = build_web_packet(borrowed=True)
        aapl_row = next(
            row for row in borrowed[1]["member_binding_ledger"]
            if row["canonical_ticker"] == "AAPL"
        )
        self.assertEqual(aapl_row["binding_status"], "rejected")
        self.assertEqual(
            aapl_row["binding_reason"], "member_source_ref_not_in_chunk_sources",
        )
        _merged, _manifest, _artifact, borrowed_boost = self._validation_and_boost(
            (*borrowed, *x_packet),
        )
        self.assertNotEqual(borrowed_boost["AAPL"]["evidence_tier"], "both")
        self.assertLess(borrowed_boost["AAPL"]["theme_soft_boost"], 5.0)

    def test_k4_02_partial_web_regroup_cannot_reach_active_boost(self):
        """A successful Web sibling is still incomplete when another chunk is truncated."""
        clock = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
        with temporary_provider_directory(web.ROOT) as private_root:
            private_root = Path(private_root)
            raw_root = private_root / "partial_web_raw"
            search_results = [{
                "url": f"https://web.example/k4-partial-{index}",
                "title": "Power demand",
                "content": "AAPL MSFT JPM power demand",
                "published_date": "2026-07-24T10:00:00Z",
            } for index in range(20)]
            _refs, prompt_rows, _drops = web._normalize_search_results(
                search_results, expected_decision_date=DATE, fetched_at=clock,
                raw_root=None, persist_raw=False,
            )
            chunks = web._chunk_regroup_rows(prompt_rows)
            first_chunk_refs = [row["source_id"] for row in chunks[0]]
            theme = {
                "theme_id": "power_demand",
                "display_name": "Partial power demand",
                "summary": "Power demand",
                "observed_at": "2026-07-24T10:00:00Z",
                "source_ref_ids": first_chunk_refs,
                "members": [
                    {"ticker": ticker, "source_ref_ids": [first_chunk_refs[0]]}
                    for ticker in TICKERS
                ],
                "semantic_assertions": [{
                    "basis": "shared_commercial_driver",
                    "basis_explanation": "Power demand reaches the linked issuers.",
                    "common_driver": {
                        "driver_statement": "Power demand is increasing.",
                        "transmission_mechanism": "Load growth drives infrastructure spending.",
                        "source_ref_ids": first_chunk_refs,
                    },
                    "member_links": [
                        {
                            "ticker": ticker,
                            "role": "beneficiary",
                            "link_statement": "The issuer is linked to the common demand.",
                            "source_ref_ids": [first_chunk_refs[0]],
                        }
                        for ticker in TICKERS
                    ],
                }],
            }
            response = _FakeDeepSeek._response(json.dumps({"themes": [theme]}))
            transport = paid_gateway.new_transport("tavily", "deepseek")
            transport._record_completed_response("tavily")
            transport._record_completed_response("deepseek")
            provider_ref = web._persist_deepseek_response(
                response, raw_root=raw_root, expected_decision_date=DATE,
                chunk_index=0, fetched_at=clock,
            )
            web_artifact, web_receipt, _ = web.build_web_fetch_packet(
                queries=["power"], search_results=search_results,
                llm_response=json.dumps({"themes": [theme]}),
                expected_decision_date=DATE, generated_at=clock.isoformat(),
                fetched_at=clock.isoformat(), raw_root=raw_root, persist_raw=True,
                execution_mode="live_authorized", network_access_performed=True,
                provider_calls_performed=True, _live_transport=transport,
                _live_ticket=paid_gateway.issue_ticket(),
                regroup_model_identity=web._regroup_model_identity(
                    served_model="deepseek-test",
                ),
                regroup_failed=True, regroup_attempted=True,
                regroup_chunk_counts={
                    "attempted": 2, "successful": 1, "failed": 1,
                    "failed_indexes": [1],
                },
                provider_response_refs=[provider_ref],
                regroup_chunks=[{
                    "chunk_index": 0, "themes": [theme],
                    "input_source_ids": first_chunk_refs,
                }],
                extra_drop_ledger=[
                    {
                        "stage": "llm", "reason": "provider_item_exception_dropped",
                        "detail": "chunk[1]:typed_rejection",
                    },
                    {
                        "stage": "llm", "reason": "regroup_chunk_dropped",
                        "detail": "chunk[1]:_ProviderItemRejected",
                    },
                ],
            )
            x_urls = [
                f"https://x.example/k4-partial-{ticker.lower()}" for ticker in TICKERS
            ]
            x_rows = [{
                "url": url, "title": ticker,
                "text": f"{ticker} power demand",
                "created_at": "2026-07-24T10:00:00Z",
            } for ticker, url in zip(TICKERS, x_urls)]
            x_artifact, x_receipt, _ = xfetch.build_x_fetch_packet(
                queries=list(TICKERS), results=x_rows,
                grok_response=_theme_payload(source_urls=x_urls, source_type="x"),
                expected_decision_date=DATE, generated_at=clock.isoformat(),
                raw_root=raw_root / "x", persist_raw=True,
            )
            with self.assertRaises(merge.ThemeDiscoveryMergeError):
                merge.merge_web_x_discovery(
                    web_artifact=web_artifact,
                    web_receipt=web_receipt,
                    x_artifact=x_artifact,
                    x_receipt=x_receipt,
                    expected_decision_date=DATE,
                    generated_at=GENERATED,
                )
        self.assertEqual(web_receipt["fetch_contract"]["regroup_chunk_counts"]["failed"], 1)

    def test_k4_06_semantic_member_link_cannot_borrow_another_bound_source(self):
        _merged, _manifest, artifact, boost_map = self._validation_and_boost(
            self._packets(web_source_count=2),
            discovery_mutator=self._member_link_borrows_source,
        )
        self.assertEqual(artifact["themes"], [])
        self.assertTrue(all(row["theme_soft_boost"] == 0.0 for row in boost_map.values()))

    def test_k4_07_merge_pruned_member_invalidates_the_only_x_assertion(self):
        _merged, manifest, artifact, boost_map = self._validation_and_boost(
            self._packets(cat_aapl=True, x_tickers=TICKERS),
        )
        self.assertEqual(len(artifact["themes"]), 1)
        self.assertTrue(all(row["theme_soft_boost"] == 2.0 for row in boost_map.values()))
        self.assertEqual(manifest["summary"]["both_member_count"], 2)

    def test_k4_08_three_one_member_assertions_cannot_be_aggregated_to_three(self):
        _merged, _manifest, artifact, boost_map = self._validation_and_boost(
            self._packets(), discovery_mutator=self._three_one_member_assertions,
        )
        self.assertEqual(artifact["themes"], [])
        self.assertTrue(all(row["theme_soft_boost"] == 0.0 for row in boost_map.values()))

    def test_k4_09_event_bucket_is_valid_empty_not_a_boostable_theme(self):
        _merged, _manifest, artifact, boost_map = self._validation_and_boost(
            self._packets(), discovery_mutator=self._event_basis,
        )
        self.assertEqual(artifact["themes"], [])
        self.assertTrue(any(
            row["reason"] == "semantic_basis_not_shared_commercial_driver"
            for row in artifact["drop_ledger"]
        ))
        self.assertTrue(all(row["theme_soft_boost"] == 0.0 for row in boost_map.values()))

    def test_k4_10_web_passing_and_x_semantic_failure_is_single_not_both(self):
        _merged, _manifest, _artifact, boost_map = self._validation_and_boost(
            self._packets(cat_aapl=True),
        )
        self.assertEqual(boost_map["AAPL"]["evidence_tier"], "single")
        self.assertEqual(boost_map["AAPL"]["theme_soft_boost"], 2.0)
        self.assertEqual(boost_map["MSFT"]["evidence_tier"], "both")
        self.assertEqual(boost_map["MSFT"]["theme_soft_boost"], 5.0)

    def test_k4_11_legacy_or_missing_semantic_artifact_cannot_activate_boost(self):
        _merged, _manifest, artifact, _boost_map = self._validation_and_boost(self._packets())
        legacy = copy.deepcopy(artifact)
        legacy["schema_version"] = "1.1.0"
        for theme in legacy["themes"]:
            theme.pop("semantic_validation", None)
        legacy_map = boost.build_provisional_theme_boost_map(
            legacy, target_tickers=list(TICKERS), expected_decision_date=DATE,
            expected_input_digests={
                "discovery_artifact_sha256": "a" * 64,
                "candidate_artifact_sha256": "b" * 64,
                "classification_packet_sha256": "c" * 64,
            },
        )
        self.assertTrue(all(row["theme_soft_boost"] == 0.0 for row in legacy_map.values()))

        missing = copy.deepcopy(artifact)
        missing["themes"][0].pop("semantic_validation", None)
        with self.assertRaises(boost.ProvisionalThemeBoostError):
            boost.build_provisional_theme_boost_map(
                missing, target_tickers=list(TICKERS), expected_decision_date=DATE,
                expected_input_digests={
                    "discovery_artifact_sha256": "a" * 64,
                    "candidate_artifact_sha256": "b" * 64,
                    "classification_packet_sha256": "c" * 64,
                },
            )

    def test_k4_12_unused_accepted_source_does_not_change_validation_or_boost(self):
        _merged, _manifest, artifact, baseline = self._validation_and_boost(self._packets())
        with_unused = copy.deepcopy(artifact)
        unused = "web:" + "e" * 64
        with_unused["source_ref_types"][unused] = "web"
        with_unused["themes"][0]["source_ref_ids"].append(unused)
        actual = boost.build_provisional_theme_boost_map(
            with_unused, target_tickers=list(TICKERS), expected_decision_date=DATE,
            expected_input_digests={
                "discovery_artifact_sha256": "a" * 64,
                "candidate_artifact_sha256": "b" * 64,
                "classification_packet_sha256": "c" * 64,
            },
        )
        self.assertEqual(actual, baseline)

    def test_k4_13_bare_pass_with_inconsistent_member_set_is_rejected_by_boost_consumer(self):
        _merged, _manifest, artifact, _boost_map = self._validation_and_boost(self._packets())
        forged = copy.deepcopy(artifact)
        forged["themes"][0]["semantic_validation"]["final_member_tickers"] = ["JPM", "MSFT"]
        with self.assertRaises(boost.ProvisionalThemeBoostError):
            boost.build_provisional_theme_boost_map(
                forged, target_tickers=list(TICKERS), expected_decision_date=DATE,
                expected_input_digests={
                    "discovery_artifact_sha256": "a" * 64,
                    "candidate_artifact_sha256": "b" * 64,
                    "classification_packet_sha256": "c" * 64,
                },
            )

    # Three separately named controls, one per gate.  They deliberately assert the OBSERVABLE
    # outcome of hollowing a gate rather than wrapping their own assertions in `assertRaises`:
    # a control that asserts its own inline assertions fail cannot show that the real test above
    # would die, and it passes just as happily when something unrelated raises.

    def test_production_default_entry_turns_red_when_persistence_gate_is_removed(self):
        """K4-03: without frozen raw receipts the merge cannot verify evidence and must refuse."""
        packets = self._packets()
        for receipt in (packets[1], packets[4]):
            for ref in receipt["source_refs"]:
                (web.ROOT / ref["raw_receipt_ref"]).unlink()
        with self.assertRaises(merge.ThemeDiscoveryMergeError):
            self._merge_and_knife2(packets)

    def test_production_default_entry_turns_red_when_raw_digest_gate_is_removed(self):
        """K4-03: a frozen raw receipt edited after the fact must not pass its content digest."""
        packets = self._packets()
        web_receipt = packets[1]
        raw_ref = next(ref["raw_receipt_ref"] for ref in web_receipt["source_refs"])
        raw_path = web.ROOT / raw_ref
        tampered = json.loads(raw_path.read_text(encoding="utf-8"))
        tampered["title"] = "tampered title"
        raw_path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaises(merge.ThemeDiscoveryMergeError):
            self._merge_and_knife2(packets)

    def test_k4_control_B_hollowed_ticker_gate_exposes_forbidden_member_and_boost(self):
        """Control B is red only when the final member/boost becomes wrong."""
        cat = self._packets(cat_aapl=True)
        armed_manifest, armed_validated, _ = self._merge_and_knife2(cat)
        armed = {member["ticker"]: member for theme in armed_validated for member in theme["members"]}
        self.assertNotEqual(armed["AAPL"]["evidence_tier"], "both")
        self.assertGreater(armed_manifest["summary"]["member_evidence_demotion_count"], 0)
        _merged, _manifest, _artifact, armed_boost = self._validation_and_boost(cat)
        self.assertEqual(armed_boost["AAPL"]["theme_soft_boost"], 2.0)

        hollowed = self._packets(cat_aapl=True)
        with mock.patch.object(merge, "_raw_payload_mentions_ticker", return_value=True):
            manifest, validated, _ = self._merge_and_knife2(hollowed)
            members = {member["ticker"]: member for theme in validated for member in theme["members"]}
            self.assertEqual(members["AAPL"]["evidence_tier"], "both",
                             "with the gate hollowed the unrelated X post must corroborate again")
            self.assertEqual(manifest["summary"]["member_evidence_demotion_count"], 0)
            _merged, _manifest, _artifact, hollowed_boost = self._validation_and_boost(hollowed)
        self.assertEqual(hollowed_boost["AAPL"]["theme_soft_boost"], 5.0)

    def test_k4_control_A_hollowed_raw_gate_allows_unfrozen_evidence_to_boost(self):
        packets = self._packets()
        for ref in packets[1]["source_refs"]:
            (web.ROOT / ref["raw_receipt_ref"]).unlink()
        with self.assertRaises(merge.ThemeDiscoveryMergeError):
            self._validation_and_boost(packets)

        original_verify = merge._verify_receipt

        def hollowed_verify(artifact, receipt, source_type, expected_decision_date):
            if source_type != "web":
                return original_verify(artifact, receipt, source_type, expected_decision_date)
            actual_types = {
                ref["source_id"]: source_type for ref in receipt["source_refs"]
            }
            raw_payloads = {
                ref["source_id"]: {
                    "source_id": ref["source_id"], "source_type": "web",
                    "canonical_locator": ref["canonical_locator"],
                    "published_at": ref["observed_at"],
                    "title": "Power demand",
                    "content": "AAPL MSFT JPM power demand",
                }
                for ref in receipt["source_refs"]
            }
            return actual_types, raw_payloads

        with mock.patch.object(merge, "_verify_receipt", side_effect=hollowed_verify):
            _merged, _manifest, _artifact, hollowed_boost = self._validation_and_boost(packets)
        self.assertEqual(hollowed_boost["AAPL"]["theme_soft_boost"], 5.0)

    def test_k4_control_C_hollowed_basis_gate_lets_event_evidence_boost(self):
        original = knife2.validate_provisional_themes

        def permissive_validator(discovery, *args, **kwargs):
            mutated = copy.deepcopy(discovery)
            for theme in mutated["themes"]:
                for assertion in theme.get("semantic_assertions", []):
                    if assertion.get("basis") == "shared_event_bucket":
                        assertion["basis"] = "shared_commercial_driver"
            return original(mutated, *args, **kwargs)

        with mock.patch.object(knife2, "validate_provisional_themes", side_effect=permissive_validator):
            _merged, _manifest, artifact, boost_map = self._validation_and_boost(
                self._packets(), discovery_mutator=self._event_basis,
            )
        self.assertEqual(artifact["schema_version"], "1.2.0")
        self.assertEqual(boost_map["AAPL"]["theme_soft_boost"], 5.0)

    def test_k4_control_D_hollowed_tier_effect_guard_turns_single_into_five(self):
        packets = self._packets(cat_aapl=True)
        _merged, _manifest, _artifact, normal = self._validation_and_boost(packets)
        self.assertEqual(normal["AAPL"]["theme_soft_boost"], 2.0)
        with (
            mock.patch.object(boost, "TIER_POINTS", {"both": 5.0, "single": 5.0}),
            mock.patch.object(boost, "validate_provisional_theme_boost_record", return_value=None),
        ):
            _merged, _manifest, _artifact, hollowed = self._validation_and_boost(
                self._packets(cat_aapl=True),
            )
        self.assertEqual(hollowed["AAPL"]["theme_soft_boost"], 5.0)


class WebRegroupReplayTests(unittest.TestCase):
    @staticmethod
    def _fixture(
        *, include_positive=True, include_negative=True, binding_dead=False,
        duplicate_theme=False, served_model="deepseek-chat",
    ):
        source_ids = ["web:" + format(index, "064x") for index in range(10)]
        refs = [{
            "source_id": source_id, "source_type": "web",
            "observed_at": "2026-08-10T10:00:00+00:00",
        } for source_id in source_ids]
        rows = [{
            "source_id": source_id, "title": "Evidence title",
            "content": f"{ticker} evidence for the frozen source",
        } for source_id, ticker in zip(source_ids, ("AAPL", "MSFT", "JPM") * 3 + ("AAPL",))]
        tickers = ("AAPL", "MSFT", "JPM")

        def theme(theme_id, basis):
            theme_refs = source_ids[:3]
            members = [
                {"ticker": ticker, "source_ref_ids": [theme_refs[index]]}
                for index, ticker in enumerate(tickers)
            ]
            if basis == "shared_commercial_driver":
                assertion = {
                    "basis": basis,
                    "basis_explanation": "The same demand mechanism reaches all linked issuers.",
                    "common_driver": {
                        "driver_statement": "A common demand is increasing.",
                        "transmission_mechanism": "Demand growth reaches each issuer.",
                        "source_ref_ids": theme_refs,
                    },
                    "member_links": [
                        {
                            "ticker": ticker, "role": "beneficiary",
                            "link_statement": "The issuer is linked to the common demand.",
                            "source_ref_ids": [theme_refs[index]],
                        }
                        for index, ticker in enumerate(tickers)
                    ],
                }
            else:
                assertion = {
                    "basis": basis,
                    "basis_explanation": "The claims describe a shared event collection, not a driver.",
                    "common_driver": None,
                    "member_links": [],
                }
            return {
                "theme_id": theme_id, "display_name": theme_id,
                "summary": "Frozen replay fixture", "observed_at": "2026-08-10T12:00:00+00:00",
                "source_ref_ids": theme_refs, "members": members,
                "semantic_assertions": [assertion],
            }

        themes = []
        if include_positive:
            themes.append(theme("positive_demand", "shared_commercial_driver"))
        if include_negative:
            themes.append(theme("event_collection", "shared_event_bucket"))
        if binding_dead:
            for raw_theme in themes:
                for member in raw_theme["members"]:
                    member["source_ref_ids"] = ["web:" + "f" * 64]
        if duplicate_theme and len(themes) > 1:
            themes[1]["theme_id"] = themes[0]["theme_id"]
        packet = {
            "packet_id": "us_short_web_regroup_engineering_smoke_20260815_chunk1_v1",
            "source_decision_date": "20260815",
            "input": {
                "target_chunk_index": 1,
                "target_source_ids": source_ids,
                "target_source_refs": refs,
            },
        }
        response = {
            "model": served_model,
            "choices": [{
                "message": {"content": json.dumps({"themes": themes})},
                "finish_reason": "stop",
            }],
        }
        transport_summary = {
            "packet_id": packet["packet_id"], "source_decision_date": "20260815",
            "transport_verdict": "PASS",
            "status": "live_authorized_engineering_smoke_response_captured",
            "provider_call_count": 1, "deepseek_call_count": 1,
            "tavily_call_count": 0, "xai_call_count": 0, "retry_count": 0,
            "raw_persisted_before_parse": True, "raw_hash_reread": True,
            "strict_parse_status": "passed", "formal_decision_slots_occupied": False,
            "raw_provider_response_ref": "provider_samples/us_short_llm_theme_discovery_engineering_smoke/raw.json",
            "raw_provider_response_sha256": "a" * 64,
            "requested_model": "deepseek-chat", "served_model": served_model,
        }
        snapshot = {"source_as_of": "2026-08-10", "snapshot_id": "d" * 64}
        sectors = {"AAPL": "10", "MSFT": "20", "JPM": "30"}
        return packet, rows, refs, response, transport_summary, snapshot, sectors

    def _run_fixture(self, **fixture_kwargs):
        packet, rows, refs, response, transport_summary, snapshot, sectors = self._fixture(**fixture_kwargs)
        with tempfile.TemporaryDirectory(prefix="us_short_5b_replay_") as temp_root:
            test_root = Path(temp_root)
            summary_path = test_root / "state" / "us_short" / "runs_private" / "replay.json"
            patches = (
                mock.patch.object(replay, "ROOT", test_root),
                mock.patch.object(replay, "SIC_SNAPSHOT_PATH", test_root / "frozen_sic_snapshot.json"),
                mock.patch.object(replay, "_replay_summary_path", return_value=summary_path),
                mock.patch.object(replay, "_validate_packet", return_value=packet),
                mock.patch.object(replay, "_validate_transport_summary", return_value=transport_summary),
                mock.patch.object(replay, "_load_target_inputs", return_value=(rows, refs, datetime(2026, 8, 15, tzinfo=timezone.utc))),
                mock.patch.object(replay, "_load_transport_response", return_value=(response, datetime(2026, 8, 15, tzinfo=timezone.utc))),
                mock.patch.object(replay, "_load_frozen_sic", return_value=(snapshot, sectors)),
                mock.patch.object(web, "_gitignored", return_value=True),
                mock.patch.object(web, "publish_decision_pair", side_effect=AssertionError("formal publisher reached")),
            )
            with mock.patch.object(replay, "EXPECTED_SIC_SNAPSHOT_ID", "d" * 64):
                with mock.patch.object(replay, "EXPECTED_SIC_SOURCE_AS_OF", "2026-08-10"):
                    with (
                        patches[0], patches[1], patches[2], patches[3], patches[4],
                        patches[5], patches[6], patches[7], patches[8], patches[9],
                    ):
                        result = replay.run_replay()
            saved = json.loads(summary_path.read_text(encoding="utf-8"))
        return result, saved

    def test_5b_transport_summary_and_raw_follow_the_current_packet_boundary(self):
        packet = json.loads(
            (replay.ROOT / "docs/us_short_web_regroup_engineering_smoke_packet_20260815_v3.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            replay._transport_summary_path(packet),
            replay.ROOT / packet["output_boundary"]["summary_ref"],
        )
        self.assertEqual(
            replay._transport_raw_root(packet),
            replay.ROOT / packet["output_boundary"]["raw_root"].rstrip("/"),
        )
        self.assertNotIn("engineering_smoke_v2", str(replay._transport_summary_path(packet)))
        self.assertNotIn("engineering_smoke_v2", str(replay._transport_raw_root(packet)))

    def test_5b_finalize_transport_verdict_is_derived_from_raw(self):
        packet = json.loads(
            (replay.ROOT / "docs/us_short_web_regroup_engineering_smoke_packet_20260815_v3.json").read_text(
                encoding="utf-8"
            )
        )
        response = {
            "model": "deepseek-v4-pro",
            "system_fingerprint": "fp_finalize",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            "choices": [{
                "message": {"content": json.dumps({"themes": [{"semantic_assertions": []}]} )},
                "finish_reason": "stop",
            }],
        }
        raw = {"provider": "deepseek", "response": response, "fetched_at": "2026-08-19T08:32:42.977104+00:00"}
        ledger = {
            "dispatch_counts": {
                "stage1_dispatch_count": 0,
                "stage2_dispatch_count": 1,
                "retry_dispatch_count": 0,
                "dispatch_count": 1,
                "unknown_dispatch_count": 0,
            },
            "vendor_dispatch_counts": {"tavily": 0, "deepseek": 1, "xai": 0},
            "reservation_attempt_count": 1,
            "query_reservations": [{"attempt_count": 1, "last_status": "complete"}],
            "recovery_events": [],
        }
        raw_path = replay.ROOT / "provider_samples/us_short_llm_theme_discovery_engineering_smoke_v3/provider_responses/20260815/deepseek_test.json"
        response_sha256 = web._sha256_bytes(web._canonical_json(response))
        summary = replay._build_transport_summary_from_raw(
            packet, replay.ROOT / packet["output_boundary"]["budget_ledger_ref"], ledger,
            raw_path, raw, datetime(2026, 8, 19, 8, 32, 42, 977104, tzinfo=timezone.utc), response_sha256,
        )
        self.assertEqual(summary["transport_verdict"], "PASS")
        self.assertEqual(summary["raw_provider_response_ref"], raw_path.relative_to(replay.ROOT).as_posix())
        mutated = copy.deepcopy(response)
        mutated["choices"][0]["finish_reason"] = "length"
        mutated_raw = {**raw, "response": mutated}
        mutated_summary = replay._build_transport_summary_from_raw(
            packet, replay.ROOT / packet["output_boundary"]["budget_ledger_ref"], ledger,
            raw_path, mutated_raw, datetime(2026, 8, 19, 8, 32, 42, 977104, tzinfo=timezone.utc),
            web._sha256_bytes(web._canonical_json(mutated)),
        )
        self.assertEqual(mutated_summary["transport_verdict"], "FAIL")
        self.assertEqual(mutated_summary["strict_parse_error_reason"], "finish_reason_not_stop")

    def test_5b_replay_uses_real_parser_binding_normalizer_validator_and_keeps_zero_effects(self):
        result, saved = self._run_fixture()
        by_theme = {row["theme_id"]: row for row in result["semantic_results"]}
        self.assertEqual(result["status"], "offline_replay_completed")
        self.assertEqual(result["parsed_theme_count"], 2)
        self.assertEqual(result["member_ledger_summary"]["member_claim_count"], 6)
        self.assertEqual(result["member_ledger_summary"]["accepted_binding_count"], 6)
        self.assertEqual(len(result["member_binding_ledger"]), 6)
        self.assertEqual(by_theme["positive_demand"]["machine_result"], "accepted")
        self.assertEqual(by_theme["event_collection"]["machine_result"], "rejected")
        self.assertIn("semantic_basis_not_shared_commercial_driver", by_theme["event_collection"]["drop_reasons"])
        self.assertEqual(result["provider_call_count"], 0)
        self.assertTrue(result["sic_snapshot"]["calibration_only"])
        self.assertIsNone(result["readiness"])
        self.assertFalse(result["formal_decision_slots_occupied"])
        self.assertFalse(result["merge_published"])
        self.assertFalse(result["validation_published"])
        self.assertFalse(result["boost_published"])
        self.assertFalse(result["score_effect"])
        self.assertEqual(saved, result)

    def test_5b_duplicate_theme_rejects_its_member_rows(self):
        result, _saved = self._run_fixture(duplicate_theme=True)
        duplicate_rows = [
            row for row in result["member_binding_ledger"]
            if row["theme_index_in_chunk"] == 1
        ]
        self.assertEqual(len(duplicate_rows), 3)
        self.assertTrue(all(row["parent_theme_status"] == "rejected" for row in duplicate_rows))
        self.assertTrue(all(
            row["parent_theme_reason"] == "duplicate_theme_dropped"
            for row in duplicate_rows
        ))
        self.assertEqual(
            result["member_ledger_summary"]["rejected_parent_theme_member_count"], 3,
        )

    def test_5b_whole_normalization_failure_falls_back_to_empty_discovery(self):
        calls = []

        def normalize(payload, **_kwargs):
            calls.append(payload)
            if payload["themes"]:
                if len(calls) <= 2:
                    return {"themes": payload["themes"]}
                raise ValueError("whole normalization failed")
            return {"source_refs": [], "themes": []}

        with mock.patch.object(discovery_writer, "normalize_discovery_payload", side_effect=normalize):
            result, _saved = self._run_fixture()
        self.assertEqual(result["normalization_drop_reason_counts"], {
            "discovery_normalization_rejected": 1,
        })
        self.assertTrue(all(
            row["machine_result"] == "not_reached_semantic_gate"
            for row in result["semantic_results"]
        ))

    def test_5b_accepts_observed_served_alias_but_rejects_missing_model(self):
        result, _saved = self._run_fixture(served_model="deepseek-v4-flash")
        self.assertEqual(result["served_model"], "deepseek-v4-flash")
        with self.assertRaisesRegex(ValueError, "regroup_model_identity_missing"):
            self._run_fixture(served_model=None)

    def test_5b_partial_semantic_coverage_does_not_issue_readiness(self):
        positive, _saved = self._run_fixture(include_negative=False)
        negative, _saved = self._run_fixture(include_positive=False)
        self.assertEqual(positive["parsed_theme_count"], 1)
        self.assertEqual(negative["parsed_theme_count"], 1)
        self.assertIsNone(positive["readiness"])
        self.assertIsNone(negative["readiness"])

    def test_5b_binding_dead_themes_remain_in_the_machine_case_list(self):
        result, _saved = self._run_fixture(binding_dead=True)
        self.assertEqual(len(result["semantic_results"]), 2)
        self.assertTrue(all(
            row["machine_result"] == "not_reached_semantic_gate"
            for row in result["semantic_results"]
        ))
        self.assertTrue(all(
            "member_source_ref_not_in_chunk_sources" in row["drop_reasons"]
            for row in result["semantic_results"]
        ))

    def test_5b_fixed_sic_identity_is_checked_before_use(self):
        snapshot = {
            "schema_name": "us_short_batch5_sec_sic_classification_snapshot",
            "schema_version": "1.0.0",
            "classification_source": "sec_sic_major_group",
            "parser_version": "1.0.0",
            "observed_at": "2026-08-10T12:00:00+00:00",
            "source_as_of": "2026-08-10",
            "entries": {
                "1": {"cik": 1, "tickers": ["AAPL"], "sector": "10"},
            },
        }
        snapshot["snapshot_id"] = sic_fetch._snapshot_digest(snapshot)
        with (
            mock.patch.object(replay, "_read_json", return_value=snapshot),
            mock.patch.object(replay, "_schema_validate"),
            mock.patch.object(replay, "SIC_SNAPSHOT_PATH", Path("frozen.json")),
            mock.patch.object(replay, "EXPECTED_SIC_SNAPSHOT_ID", snapshot["snapshot_id"]),
        ):
            loaded, sectors = replay._load_frozen_sic()
        self.assertEqual(loaded["snapshot_id"], snapshot["snapshot_id"])
        self.assertEqual(sectors, {"AAPL": "10"})

    def test_5b_target_chunk_comes_from_production_order_not_receipt_storage_order(self):
        with temporary_provider_directory(replay.ROOT) as private_root:
            root = Path(private_root)
            raw_dir = root / "provider_samples" / "us_short_llm_theme_discovery_fetch_web" / "raw" / "20260815"
            raw_dir.mkdir(parents=True, exist_ok=True)
            rows = []
            raw_by_id = {}
            for index in range(34):
                url = f"https://example.test/5b-source-{index:02d}"
                source_id = web._source_id(url)
                row = {
                    "url": url, "title": f"Title {index}", "content": f"Content {index}",
                    "published_date": "2026-08-10T10:00:00Z",
                }
                rows.append(row)
                raw_by_id[source_id] = {
                    "source_id": source_id, "canonical_locator": url,
                    "title": row["title"], "content": row["content"],
                    "published_at": row["published_date"],
                }
            fetched_at = datetime(2026, 8, 15, 4, 30, tzinfo=timezone.utc)
            normalized_refs, prompt_rows, drops = web._normalize_search_results(
                rows, expected_decision_date="20260815", fetched_at=fetched_at,
                raw_root=None, persist_raw=False,
            )
            self.assertFalse(drops)
            chunks = web._chunk_regroup_rows(prompt_rows)
            self.assertEqual([len(chunk) for chunk in chunks], [10, 10, 10, 4])
            ref_by_id = {}
            for ref in normalized_refs:
                raw = raw_by_id[ref["source_id"]]
                raw_path = raw_dir / f"{ref['source_id'].split(':', 1)[1]}.json"
                raw_path.write_text(json.dumps(raw), encoding="utf-8")
                ref_by_id[ref["source_id"]] = {
                    **ref,
                    "fetched_at": fetched_at.isoformat(),
                    "raw_receipt_ref": raw_path.relative_to(root).as_posix(),
                    "raw_receipt_gitignored": True,
                }
            receipt_refs = list(reversed([ref_by_id[ref["source_id"]] for ref in normalized_refs]))
            receipt_path = root / "state" / "us_short" / "us_short_llm_theme_discovery_web_20260815_receipt.json"
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps({
                "decision_clock": {"expected_decision_date": "20260815"},
                "source_refs": receipt_refs,
            }), encoding="utf-8")
            target = chunks[1]
            packet = {
                "input": {
                    "receipt_ref": receipt_path.relative_to(root).as_posix(),
                    "accepted_source_count": 34,
                    "target_chunk_index": 1,
                    "target_source_ids": [row["source_id"] for row in target],
                    "target_source_refs": [ref_by_id[row["source_id"]] for row in target],
                },
            }
            with mock.patch.object(replay, "ROOT", root):
                actual_rows, actual_refs, _actual_fetched_at = replay._load_target_inputs(packet)
            self.assertEqual([row["source_id"] for row in actual_rows], packet["input"]["target_source_ids"])
            self.assertEqual(actual_refs, packet["input"]["target_source_refs"])

    def test_5b_source_digest_keeps_each_frozen_fetched_at(self):
        with temporary_provider_directory(replay.ROOT) as private_root:
            root = Path(private_root)
            raw_dir = root / "provider_samples" / "us_short_llm_theme_discovery_fetch_web" / "raw" / "20260815"
            raw_dir.mkdir(parents=True, exist_ok=True)
            rows = []
            fetched_at_by_url = {}
            for index in range(34):
                url = f"https://example.test/5b-clock-source-{index:02d}"
                row = {
                    "url": url, "title": f"Title {index}", "content": f"Content {index}",
                    "published_date": "2026-08-10T10:00:00Z",
                }
                rows.append(row)
                fetched_at_by_url[url] = datetime(
                    2026, 8, 15, 4, 30, tzinfo=timezone.utc,
                ) + timedelta(minutes=index)
            normalized_refs = []
            prompt_rows = []
            for row in rows:
                refs, prompts, drops = web._normalize_search_results(
                    [row], expected_decision_date="20260815",
                    fetched_at=fetched_at_by_url[row["url"]], raw_root=None,
                    persist_raw=False,
                )
                self.assertFalse(drops)
                normalized_refs.extend(refs)
                prompt_rows.extend(prompts)
            normalized_refs.sort(key=lambda ref: ref["source_id"])
            prompt_rows.sort(key=lambda row: row["source_id"])
            chunks = web._chunk_regroup_rows(prompt_rows)
            ref_by_id = {}
            for ref in normalized_refs:
                row = next(row for row in rows if web._source_id(row["url"]) == ref["source_id"])
                raw = {
                    "source_id": ref["source_id"], "canonical_locator": row["url"],
                    "title": row["title"], "content": row["content"],
                    "published_at": row["published_date"],
                }
                raw_path = raw_dir / f"{ref['source_id'].split(':', 1)[1]}.json"
                raw_path.write_text(json.dumps(raw), encoding="utf-8")
                ref_by_id[ref["source_id"]] = {
                    **ref,
                    "fetched_at": fetched_at_by_url[row["url"]].isoformat(),
                    "raw_receipt_ref": raw_path.relative_to(root).as_posix(),
                    "raw_receipt_gitignored": True,
                }
            receipt_path = root / "state" / "us_short" / "us_short_llm_theme_discovery_web_20260815_receipt.json"
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps({
                "decision_clock": {"expected_decision_date": "20260815"},
                "source_refs": list(reversed([ref_by_id[ref["source_id"]] for ref in normalized_refs])),
            }), encoding="utf-8")
            target = chunks[1]
            packet = {
                "input": {
                    "receipt_ref": receipt_path.relative_to(root).as_posix(),
                    "accepted_source_count": 34,
                    "target_chunk_index": 1,
                    "target_source_ids": [row["source_id"] for row in target],
                    "target_source_refs": [ref_by_id[row["source_id"]] for row in target],
                },
            }
            with mock.patch.object(replay, "ROOT", root):
                actual_rows, actual_refs, actual_fetched_at = replay._load_target_inputs(packet)
            self.assertEqual([row["source_id"] for row in actual_rows], packet["input"]["target_source_ids"])
            self.assertEqual(actual_refs, packet["input"]["target_source_refs"])
            self.assertEqual(actual_fetched_at, max(fetched_at_by_url.values()))

    def test_5b_has_no_free_input_or_paid_entrypoint(self):
        source = Path(replay.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "PaidDispatchGateway", "DeepSeekClient", "reserve_plan_budget",
            "run_web_fetch", "run_x_fetch", "publish_decision_pair",
        ):
            self.assertNotIn(forbidden, source)
        with mock.patch.object(replay, "run_replay", side_effect=AssertionError("runner reached")) as run:
            with mock.patch.object(replay.sys, "argv", ["replay.py", "--raw", "free.json"]):
                self.assertEqual(replay.main(), 2)
        run.assert_not_called()

    def test_5b_validator_call_is_load_bearing(self):
        with mock.patch.object(
            replay.provisional_validate, "validate_provisional_themes",
            side_effect=AssertionError("validator bypassed"),
        ):
            with self.assertRaisesRegex(AssertionError, "validator bypassed"):
                self._run_fixture()


if __name__ == "__main__":
    unittest.main()
