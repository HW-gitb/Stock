from __future__ import annotations

import json
import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from tests.provider.us_short_private_test_root_light import temporary_provider_directory


WEB_GOOD = {
    "url": "https://offline.example/good-web", "title": "Power demand",
    "content": "AAPL MSFT JPM power demand", "published_date": "2026-07-24T10:00:00Z",
}
X_GOOD = {
    "url": "https://offline.example/good-x", "title": "Power post",
    "text": "AAPL MSFT JPM power demand", "created_at": "2026-07-24T10:00:00Z",
}


class _ExplodingText:
    def __str__(self) -> str:
        raise RuntimeError("provider-controlled string conversion failed")


def _poisoned_rows(
    base: dict[str, object], *, text_field: str, time_field: str, title_required: bool,
):
    """Deterministic malformed-value corpus shared by both offline producer lanes."""
    yield None
    yield 7
    yield []
    for url in (
        None, "not-a-url", "https://offline.example/a b", "https://offline.example/\ud800",
        "http://offline.example:99999/a", "https://offline.example/cb?token=FAKE_TOKEN",
    ):
        yield {**base, "url": url}
    for value in (None, "", "\ud800", _ExplodingText()):
        if title_required:
            yield {**base, "title": value}
        yield {**base, text_field: value}
    for value in (None, 7, {}, "not-a-date", "0001-01-01T00:00:00+23:00", "2026-07-25T14:00:00Z"):
        yield {**base, time_field: value}


def _theme_payload(refs: list[str], *, theme_id: str = "good_theme") -> dict[str, object]:
    return {
        "theme_id": theme_id, "display_name": "Power demand", "summary": "Cross-industry power demand",
        "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": refs,
        "members": [
            {"ticker": "AAPL", "source_ref_ids": refs},
            {"ticker": "MSFT", "source_ref_ids": refs},
            {"ticker": "JPM", "source_ref_ids": refs},
        ],
        "semantic_assertions": [{
            "basis": "shared_commercial_driver",
            "basis_explanation": "Power demand reaches the linked issuers.",
            "common_driver": {
                "driver_statement": "Power demand is increasing.",
                "transmission_mechanism": "Load growth drives infrastructure spending.",
                "source_ref_ids": refs,
            },
            "member_links": [{
                "ticker": ticker, "role": "beneficiary",
                "link_statement": "The issuer is linked to the common demand.",
                "source_ref_ids": refs,
            } for ticker in ("AAPL", "MSFT", "JPM")],
        }],
    }


def _poisoned_themes(refs: list[str]):
    base = _theme_payload(refs, theme_id="bad_theme")
    yield None
    yield 7
    for field, values in (
        ("theme_id", (None, "", "BAD THEME", "x" * 80)),
        ("display_name", (None, "", "\ud800")),
        ("summary", (None, "", "\ud800")),
        ("observed_at", (None, "bad", "0001-01-01T00:00:00+23:00")),
        ("source_ref_ids", (None, 7, {}, ["unbound:ref"])),
        ("members", (None, 7, {}, [None], [{"ticker": "AAPL", "source_ref_ids": 7}])),
    ):
        for value in values:
            yield {**base, field: value}


class OfflineDiscoveryInvariantTests(unittest.TestCase):
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

    """Offline-only convergence harness; live/provider execution is intentionally out of scope."""

    def test_every_poisoned_web_row_keeps_the_good_sibling_and_ledgers_a_drop(self):
        for index, poisoned in enumerate(_poisoned_rows(
            {**WEB_GOOD, "url": "https://offline.example/poison-web"},
            text_field="content", time_field="published_date", title_required=True,
        )):
            with self.subTest(index=index, shape=type(poisoned).__name__):
                _, receipt, _ = web.build_web_fetch_packet(
                    queries=["q"], search_results=[WEB_GOOD, poisoned], llm_response='{"themes":[]}',
                    expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                )
                self.assertEqual(receipt["summary"]["accepted_source_count"], 1)
                self.assertGreaterEqual(receipt["summary"]["dropped_result_count"], 1)

    def test_every_poisoned_x_row_keeps_the_good_sibling_and_ledgers_a_drop(self):
        for index, poisoned in enumerate(_poisoned_rows(
            {**X_GOOD, "url": "https://offline.example/poison-x"},
            text_field="text", time_field="created_at", title_required=False,
        )):
            with self.subTest(index=index, shape=type(poisoned).__name__):
                _, receipt, _ = xfetch.build_x_fetch_packet(
                    queries=["q"], results=[X_GOOD, poisoned], grok_response='{"themes":[]}',
                    expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                )
                self.assertEqual(receipt["summary"]["accepted_source_count"], 1)
                self.assertGreaterEqual(receipt["summary"]["dropped_result_count"], 1)

    def test_every_poisoned_theme_keeps_the_good_theme_on_both_lanes(self):
        lane_inputs = (
            ("web", web._source_id(web._canonical_locator(WEB_GOOD["url"]))),
            ("x", xfetch._source_id(web._canonical_locator(X_GOOD["url"]))),
        )
        for lane, ref in lane_inputs:
            good = _theme_payload([ref])
            for index, poisoned in enumerate(_poisoned_themes([ref])):
                with self.subTest(lane=lane, index=index, shape=type(poisoned).__name__):
                    response = json.dumps({"themes": [good, poisoned]}, ensure_ascii=True, default=str)
                    if lane == "web":
                        artifact, receipt, _ = web.build_web_fetch_packet(
                            queries=["q"], search_results=[WEB_GOOD], llm_response=response,
                            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                        )
                    else:
                        artifact, receipt, _ = xfetch.build_x_fetch_packet(
                            queries=["q"], results=[X_GOOD], grok_response=response,
                            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                        )
                    self.assertIn("good_theme", [theme["theme_id"] for theme in artifact["themes"]])
                    model_clock_poisoned = isinstance(poisoned, dict) and poisoned.get("observed_at") in (
                        None, "bad", "0001-01-01T00:00:00+23:00",
                    )
                    if model_clock_poisoned:
                        self.assertIn("bad_theme", [theme["theme_id"] for theme in artifact["themes"]])
                        self.assertEqual(receipt["drop_ledger"], [])
                    else:
                        self.assertTrue(receipt["drop_ledger"])

    def test_every_bad_member_is_dropped_without_erasing_its_good_theme_on_both_lanes(self):
        """K3-R41/R42: raw identity and malformed member fields are per-member boundaries."""
        lane_inputs = (
            ("web", web._source_id(web._canonical_locator(WEB_GOOD["url"]))),
            ("x", xfetch._source_id(web._canonical_locator(X_GOOD["url"]))),
        )
        poisoned_members = (
            None,
            7,
            {"ticker": "AAPL", "source_ref_ids": 7},
            {"ticker": "ıBM", "source_ref_ids": []},
            {"ticker": "ＡAPL", "source_ref_ids": []},
            {"ticker": "AAPL\u00a0", "source_ref_ids": []},
            {"ticker": "AAPL", "source_ref_ids": []},
        )
        for lane, ref in lane_inputs:
            for poisoned in poisoned_members:
                with self.subTest(lane=lane, poisoned=repr(poisoned)):
                    theme = _theme_payload([ref])
                    theme["members"].append(poisoned)
                    response = json.dumps({"themes": [theme]}, ensure_ascii=False)
                    if lane == "web":
                        artifact, receipt, _ = web.build_web_fetch_packet(
                            queries=["q"], search_results=[WEB_GOOD], llm_response=response,
                            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                        )
                    else:
                        artifact, receipt, _ = xfetch.build_x_fetch_packet(
                            queries=["q"], results=[X_GOOD], grok_response=response,
                            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                        )
                    self.assertEqual([row["theme_id"] for row in artifact["themes"]], ["good_theme"])
                    self.assertEqual(
                        [row["ticker"] for row in artifact["themes"][0]["members"]], ["AAPL", "JPM", "MSFT"],
                    )
                    self.assertTrue(any(row["stage"] == "llm" for row in receipt["drop_ledger"]))

    def test_offline_cli_object_fixture_publishes_a_nonempty_lane_on_both_producers(self):
        """K3-R40: ordinary JSON-object fixtures use the same parser boundary as live text."""
        with temporary_provider_directory(web.ROOT) as td:
            state_dir = Path(td) / "state" / "us_short"
            fake_results = Path(td) / "results.json"
            fake_response = Path(td) / "response.json"
            fixtures = (
                (
                    "web", web.main, [WEB_GOOD],
                    {"themes": [_theme_payload([web._source_id(web._canonical_locator(WEB_GOOD["url"]))])]},
                    "--fake-results-path", "--fake-llm-response-path",
                    web.default_discovery_path, web.default_receipt_path,
                ),
                (
                    "x", xfetch.main, [X_GOOD],
                    {"themes": [_theme_payload([xfetch._source_id(web._canonical_locator(X_GOOD["url"]))])]},
                    "--fake-results-path", "--fake-response-path",
                    xfetch.default_discovery_path, xfetch.default_receipt_path,
                ),
            )
            for lane, main, results, response, result_flag, response_flag, discovery_path, receipt_path in fixtures:
                with self.subTest(lane=lane):
                    fake_results.write_text(json.dumps(results), encoding="utf-8")
                    fake_response.write_text(json.dumps(response), encoding="utf-8")
                    with (
                        mock.patch.object(web, "STATE_DIR", state_dir),
                        mock.patch.object(xfetch, "STATE_DIR", state_dir),
                    ):
                        self.assertEqual(main([
                            "--query", "q", "--expected-decision-date", "20260725",
                            "--generated-at", "2026-07-25T08:00:00Z",
                            result_flag, str(fake_results), response_flag, str(fake_response),
                        ]), 0)
                        artifact = json.loads(discovery_path("20260725").read_text(encoding="utf-8"))
                        self.assertEqual([theme["theme_id"] for theme in artifact["themes"]], ["good_theme"])
                        self.assertTrue(receipt_path("20260725").is_file())

    def test_offline_cli_malformed_top_level_fixture_fails_before_any_publication(self):
        with temporary_provider_directory(web.ROOT) as td:
            state_dir = Path(td) / "state" / "us_short"
            fake_response = Path(td) / "response.json"
            fake_results = Path(td) / "results.json"
            fake_response.write_text(json.dumps({"notes": "missing themes"}), encoding="utf-8")
            fixtures = (
                ("web", web.main, [WEB_GOOD], "--fake-llm-response-path", web.WebThemeDiscoveryError,
                 web.default_discovery_path, web.default_receipt_path),
                ("x", xfetch.main, [X_GOOD], "--fake-response-path", xfetch.XThemeDiscoveryError,
                 xfetch.default_discovery_path, xfetch.default_receipt_path),
            )
            for lane, main, results, response_flag, error, discovery_path, receipt_path in fixtures:
                with self.subTest(lane=lane):
                    fake_results.write_text(json.dumps(results), encoding="utf-8")
                    with (
                        mock.patch.object(web, "STATE_DIR", state_dir),
                        mock.patch.object(xfetch, "STATE_DIR", state_dir),
                    ):
                        with self.assertRaises(error):
                            main([
                                "--query", "q", "--expected-decision-date", "20260725",
                                "--generated-at", "2026-07-25T08:00:00Z",
                                "--fake-results-path", str(fake_results), response_flag, str(fake_response),
                            ])
                        self.assertFalse(discovery_path("20260725").exists())
                        self.assertFalse(receipt_path("20260725").exists())

    def test_top_level_supersets_are_tolerated_but_missing_theme_lists_fail_closed(self):
        web_drops: list[dict[str, str]] = []
        parsed_web = web._parse_llm_json(
            '{"themes":[],"notes":"ok","confidence":0.8}', drop_ledger=web_drops,
        )
        self.assertEqual(parsed_web, {"themes": []})
        self.assertEqual(web_drops, [{"stage": "llm", "reason": "ignored_top_level_keys", "detail": "confidence,notes"}])

        x_drops: list[dict[str, str]] = []
        parsed_x = xfetch._parse_grok(
            '{"themes":[],"sources":[],"notes":"ok","confidence":0.8}', drop_ledger=x_drops,
        )
        self.assertEqual(parsed_x, {"sources": [], "themes": []})
        self.assertEqual(x_drops, [{"stage": "llm", "reason": "ignored_top_level_keys", "detail": "confidence,notes"}])

        for malformed_sources in ("see above", {}, 0, False, None):
            with self.subTest(sources_type=type(malformed_sources).__name__):
                drops: list[dict[str, str]] = []
                parsed = xfetch._parse_grok(json.dumps({"themes": [], "sources": malformed_sources}), drop_ledger=drops)
                self.assertEqual(parsed, {"themes": []})
                self.assertEqual(drops, [{
                    "stage": "llm", "reason": "ignored_malformed_top_level_field",
                    "detail": f"sources:{type(malformed_sources).__name__}",
                }])

        for malformed in ('{}', '{"notes":"only"}', '{"themes":null}', '{"themes":{}}'):
            with self.subTest(malformed=malformed):
                with self.assertRaises(web.WebThemeDiscoveryError):
                    web._parse_llm_json(malformed)
                with self.assertRaises(xfetch.XThemeDiscoveryError):
                    xfetch._parse_grok(malformed)

    def test_schema_date_time_formats_are_enforced_at_every_discovery_boundary(self):
        """Optional-u: each of the seven Draft7 date-time boundaries is load-bearing."""
        from engine import us_short_provisional_theme_boost as boost
        from runners import us_short_llm_theme_discovery as discovery
        from runners import us_short_llm_theme_discovery_merge as merge
        from runners import us_short_provisional_theme_validate as validate

        source_payload = {
            "source_refs": [{"source_id": "web:fixture", "source_type": "web", "observed_at": "2026-07-24T10:00:00Z"}],
            "themes": [{
                "theme_id": "fixture", "display_name": "Fixture", "summary": "Fixture",
                "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": ["web:fixture"],
                "members": [{"ticker": "AAPL", "source_ref_ids": ["web:fixture"]}],
            }],
        }
        artifact = discovery.normalize_discovery_payload(
            source_payload, expected_decision_date="20260725", generated_at="2026-07-24T12:30:00Z",
        )
        bad_artifact = copy.deepcopy(artifact)
        bad_artifact["generated_at"] = "not-a-timestamp"
        with self.assertRaises(discovery.LLMThemeDiscoveryError):
            discovery._validate_schema(bad_artifact)

        web_artifact, web_receipt, _ = web.build_web_fetch_packet(
            queries=["q"], search_results=[WEB_GOOD], llm_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        bad_web = copy.deepcopy(web_receipt)
        bad_web["generated_at"] = "not-a-timestamp"
        with self.assertRaises(web.WebThemeDiscoveryError):
            web._validate_schema(bad_web)

        x_artifact, x_receipt, _ = xfetch.build_x_fetch_packet(
            queries=["q"], results=[X_GOOD], grok_response='{"themes":[]}',
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        bad_x = copy.deepcopy(x_receipt)
        bad_x["generated_at"] = "not-a-timestamp"
        with self.assertRaises(xfetch.XThemeDiscoveryError):
            xfetch._validate_schema(bad_x)

        _, manifest = merge.merge_web_x_discovery(
            web_artifact=web_artifact, web_receipt=web_receipt,
            x_artifact=x_artifact, x_receipt=x_receipt,
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        bad_manifest = copy.deepcopy(manifest)
        bad_manifest["generated_at"] = "not-a-timestamp"
        with self.assertRaises(merge.ThemeDiscoveryMergeError):
            merge._schema_validate(merge.SCHEMA_PATH, bad_manifest)

        bad_merged_discovery = copy.deepcopy(artifact)
        bad_merged_discovery["generated_at"] = "not-a-timestamp"
        with self.assertRaises(merge.ThemeDiscoveryMergeError):
            merge._validate_discovery(bad_merged_discovery)

        digests = {
            "discovery_artifact_sha256": "a" * 64,
            "candidate_artifact_sha256": "b" * 64,
            "classification_packet_sha256": "c" * 64,
        }
        validation_artifact = {
            "schema_name": "us_short_provisional_theme_validation",
            "schema_version": "1.0.0",
            "generated_at": "2026-07-25T08:00:00Z",
            "decision_clock": {
                "expected_decision_date": "20260725",
                "candidate_price_basis_date": "20260724",
                "universe_used_date": "2026-07-24",
                "classification_source_as_of": "2026-07-24",
                "cutoff_policy": "before_decision_open_et",
                "pit_enforced": True,
            },
            "validation_contract": {
                "producer_kind": "provisional_theme_validate",
                "input_mode": "offline_local_artifacts",
                "membership_status": "provisional_validated",
                "market_confirmation_status": "not_run",
                "scoring_eligible": False,
                "top15_effect_enabled": False,
                "operation_advice_effect_enabled": False,
                "dynamic_seats_enabled": False,
                "theme_probe_enabled": False,
                "lifecycle_actions_enabled": False,
            },
            "input_artifacts": {**digests, "eligible_ticker_count": 1, "classification_ticker_count": 1},
            "source_ref_types": {"web:fixture": "web"},
            "themes": [],
            "drop_ledger": [],
            "summary": {
                "discovered_theme_count": 0,
                "validated_theme_count": 0,
                "validated_member_count": 0,
                "rejected_theme_count": 0,
                "dropped_member_count": 0,
                "truncated_theme_count": 0,
            },
        }
        validate._schema_validate(validation_artifact, validate.SCHEMA_PATH, "validation artifact")
        self.assertEqual(
            set(boost.build_provisional_theme_boost_map(
                validation_artifact,
                target_tickers=["AAPL"],
                expected_decision_date="20260725",
                expected_input_digests=digests,
            )),
            {"AAPL"},
        )
        for malformed_generated_at in (
            "2026-07-25 08:00:00+00:00",
            "2026-07-25T08:00:00\x00+00:00",
            "2026-07-25T08:00:00+0000",
            "banana",
        ):
            with self.subTest(malformed_generated_at=repr(malformed_generated_at)):
                bad_validation = copy.deepcopy(validation_artifact)
                bad_validation["generated_at"] = malformed_generated_at
                with self.assertRaises(validate.ProvisionalThemeValidationError):
                    validate._schema_validate(
                        bad_validation, validate.SCHEMA_PATH, "validation artifact",
                    )
                with self.assertRaises(boost.ProvisionalThemeBoostError):
                    boost.build_provisional_theme_boost_map(
                        bad_validation,
                        target_tickers=["AAPL"],
                        expected_decision_date="20260725",
                        expected_input_digests=digests,
                    )

        bad_validation = copy.deepcopy(validation_artifact)
        bad_validation["generated_at"] = "banana"

        def assert_discovery_rejects_bad_date_time() -> None:
            with self.assertRaises(discovery.LLMThemeDiscoveryError):
                discovery._validate_schema(bad_artifact)

        def assert_web_rejects_bad_date_time() -> None:
            with self.assertRaises(web.WebThemeDiscoveryError):
                web._validate_schema(bad_web)

        def assert_x_rejects_bad_date_time() -> None:
            with self.assertRaises(xfetch.XThemeDiscoveryError):
                xfetch._validate_schema(bad_x)

        def assert_merge_manifest_rejects_bad_date_time() -> None:
            with self.assertRaises(merge.ThemeDiscoveryMergeError):
                merge._schema_validate(merge.SCHEMA_PATH, bad_manifest)

        def assert_merge_discovery_rejects_bad_date_time() -> None:
            with self.assertRaises(merge.ThemeDiscoveryMergeError):
                merge._validate_discovery(bad_merged_discovery)

        def assert_validate_rejects_bad_date_time() -> None:
            with self.assertRaises(validate.ProvisionalThemeValidationError):
                validate._schema_validate(bad_validation, validate.SCHEMA_PATH, "validation artifact")

        def assert_boost_rejects_bad_date_time() -> None:
            with self.assertRaises(boost.ProvisionalThemeBoostError):
                boost.build_provisional_theme_boost_map(
                    bad_validation,
                    target_tickers=["AAPL"],
                    expected_decision_date="20260725",
                    expected_input_digests=digests,
                )

        for boundary, module, assertion in (
            ("knife_1_discovery", discovery, assert_discovery_rejects_bad_date_time),
            ("web_fetch", web, assert_web_rejects_bad_date_time),
            ("x_fetch", xfetch, assert_x_rejects_bad_date_time),
            ("merge_manifest", merge, assert_merge_manifest_rejects_bad_date_time),
            ("merge_discovery", merge, assert_merge_discovery_rejects_bad_date_time),
            ("knife_2_validate", validate, assert_validate_rejects_bad_date_time),
            ("boost_consumer", boost, assert_boost_rejects_bad_date_time),
        ):
            with self.subTest(boundary=boundary):
                assertion()
                with mock.patch.object(module, "FORMAT_CHECKER", None):
                    with self.assertRaises(AssertionError):
                        assertion()

    def test_lossless_url_equivalence_is_collapsing_and_idempotent(self):
        pairs = (
            ("https://offline.example/a%2fb", "https://offline.example/a%2Fb"),
            ("https://offline.example/a/./story", "https://offline.example/a/story"),
            ("https://offline.example/a/b/../story", "https://offline.example/a/story"),
            ("https://offline.example/s?q=a%2fb", "https://offline.example/s?q=a%2Fb"),
            ("https://offline.example/user%7Ejdoe?q=%41", "https://offline.example/user~jdoe?q=A"),
            ("https://offline.example/a/%2E%2E/story", "https://offline.example/story"),
        )
        for first, second in pairs:
            with self.subTest(first=first, second=second):
                canonical = web._canonical_locator(first)
                self.assertIsNotNone(canonical)
                self.assertEqual(canonical, web._canonical_locator(second))
                self.assertEqual(web._canonical_locator(canonical), canonical)

        authorities = (
            ("https", "OFFLINE.Example", ":443", "offline.example"),
            ("http", "OFFLINE.Example", ":80", "offline.example"),
            ("https", "[2001:DB8::1]", ":443", "[2001:db8::1]"),
        )
        dot_paths = (
            "/root/./doc{token}/", "/root/branch/../doc{token}",
            "/./root/doc{token}", "/root/branch/../../root/doc{token}",
        )
        percent_pairs = (("%2f", "%2F"), ("%3a", "%3A"), ("%aa", "%AA"), ("%ff", "%FF"))
        for scheme, host, port, canonical_host in authorities:
            for path_shape in dot_paths:
                for lower, upper in percent_pairs:
                    variant = f"{scheme.upper()}://{host}{port}{path_shape.format(token=lower)}?z={lower}&a=1"
                    expected = f"{scheme}://{canonical_host}/root/doc{upper}?a=1&z={upper}"
                    with self.subTest(variant=variant):
                        canonical = web._canonical_locator(variant)
                        self.assertEqual(canonical, expected)
                        self.assertEqual(web._canonical_locator(canonical), canonical)

        for encoded, literal in (("%41", "A"), ("%7e", "~"), ("%2d", "-"), ("%2e", "."), ("%5f", "_")):
            variant = f"https://OFFLINE.example:443/root/{encoded}story?z={encoded}&a=1"
            expected = f"https://offline.example/root/{literal}story?a=1&z={literal}"
            with self.subTest(variant=variant):
                canonical = web._canonical_locator(variant)
                self.assertEqual(canonical, expected)
                self.assertEqual(web._canonical_locator(canonical), canonical)

    def test_new_guards_have_reverse_mutation_controls(self):
        """Hollow each new guard and prove its invariant assertion turns red."""
        def assert_percent_case() -> None:
            self.assertEqual(
                web._canonical_locator("https://offline.example/user%7Ejdoe?q=%41"),
                web._canonical_locator("https://offline.example/user~jdoe?q=A"),
            )

        def assert_dot_segments() -> None:
            self.assertEqual(
                web._canonical_locator("https://offline.example/a/./story"),
                web._canonical_locator("https://offline.example/a/story"),
            )

        def assert_web_extra_key_ledger() -> None:
            drops: list[dict[str, str]] = []
            web._parse_llm_json('{"themes":[],"notes":"ok"}', drop_ledger=drops)
            self.assertEqual([row["reason"] for row in drops], ["ignored_top_level_keys"])

        def assert_x_extra_key_ledger() -> None:
            drops: list[dict[str, str]] = []
            xfetch._parse_grok('{"themes":[],"notes":"ok"}', drop_ledger=drops)
            self.assertEqual([row["reason"] for row in drops], ["ignored_top_level_keys"])

        for assertion in (assert_percent_case, assert_dot_segments, assert_web_extra_key_ledger, assert_x_extra_key_ledger):
            assertion()

        with mock.patch.object(web, "_uppercase_percent_octets", side_effect=lambda value: value):
            with self.assertRaises(AssertionError):
                assert_percent_case()
        with mock.patch.object(web, "_remove_dot_segments", side_effect=lambda value: value):
            with self.assertRaises(AssertionError):
                assert_dot_segments()
        with mock.patch.object(web, "_parse_llm_json", side_effect=lambda value, **_kwargs: json.loads(value)):
            with self.assertRaises(AssertionError):
                assert_web_extra_key_ledger()
        with mock.patch.object(xfetch, "_parse_grok", side_effect=lambda value, **_kwargs: json.loads(value)):
            with self.assertRaises(AssertionError):
                assert_x_extra_key_ledger()

    def test_invalid_query_corpus_fails_closed_without_any_fake_client_call(self):
        class SpyWeb:
            calls = 0
            def search(self, query):
                self.calls += 1
                return []

        class SpyX:
            calls = 0
            results: list[object] = []
            def search(self, query, expected):
                self.calls += 1
                return '{"themes":[]}'

        invalid_web = ([], [""], ["\ud800"], ["api_key=FAKE"], ["q"] * (web.MAX_TAVILY_QUERIES + 1))
        invalid_x = ([], [""], ["\ud800"], ["api_key=FAKE"], ["q"] * (xfetch.MAX_X_QUERIES + 1))
        web_spy, x_spy = SpyWeb(), SpyX()
        for queries in invalid_web:
            with self.subTest(lane="web", query_count=len(queries)):
                with self.assertRaises(web.WebThemeDiscoveryError):
                    web.run_web_fetch(
                        queries=queries, expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                        search_client=web_spy, deepseek_client=object(),
                    )
        for queries in invalid_x:
            with self.subTest(lane="x", query_count=len(queries)):
                with self.assertRaises(xfetch.XThemeDiscoveryError):
                    xfetch.run_x_fetch(
                        queries=queries, expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
                        x_client=x_spy,
                    )
        self.assertEqual(web_spy.calls, 0)
        self.assertEqual(x_spy.calls, 0)


if __name__ == "__main__":
    unittest.main()
