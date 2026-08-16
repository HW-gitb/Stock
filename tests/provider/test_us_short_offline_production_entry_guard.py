"""Permanent offline regression guard for the real US-short producer entrances.

This intentionally calls only ``run_web_fetch`` and ``run_x_fetch``.  It exists
to prevent the K3-R62/R64/R67 class from being hidden by builder-only fixtures.
"""
from __future__ import annotations

import json
import uuid
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from runners import us_short_llm_theme_discovery_merge as merge
from runners import us_short_provisional_theme_validate as knife2
from tests.provider.us_short_private_test_root import temporary_provider_directory


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

    def _packets(self, *, cat_aapl=False):
        token = uuid.uuid4().hex
        packet_tickers = TICKERS + ("NVDA",) if cat_aapl else TICKERS
        web_url = f"https://web.example/k3-permanent-{token}"
        x_urls = [f"https://x.example/k3-permanent-{token}-{ticker.lower()}" for ticker in packet_tickers]
        web_rows = [{
            "url": web_url, "title": "Power demand", "content": "AAPL MSFT JPM power demand",
            "published_date": "2026-07-24T10:00:00Z",
        }]
        x_rows = [{
            "url": x_urls[index], "title": ("X post" if cat_aapl and index == 0 else ticker), "text": (
                "totally unrelated cat photo" if cat_aapl and index == 0
                else f"{ticker} power demand"
            ), "created_at": "2026-07-24T10:00:00Z",
        } for index, ticker in enumerate(packet_tickers)]
        web_payload = _theme_payload(source_urls=[web_url], source_type="web")
        x_payload = _theme_payload(source_urls=x_urls, source_type="x", tickers=packet_tickers)
        web_artifact, web_receipt, web_summary = web.run_web_fetch(
            queries=["power"], expected_decision_date=DATE, generated_at=GENERATED,
            search_client=_FakeSearch(web_rows), deepseek_client=_FakeDeepSeek(web_payload),
            raw_root=self._raw_root / "web",
        )
        x_artifact, x_receipt, x_summary = xfetch.run_x_fetch(
            queries=list(packet_tickers), expected_decision_date=DATE, generated_at=GENERATED,
            x_client=_FakeX(x_rows, x_payload), raw_root=self._raw_root / "x",
        )
        return (web_artifact, web_receipt, web_summary,
                x_artifact, x_receipt, x_summary)

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

    # Three separately named controls, one per gate.  They deliberately assert the OBSERVABLE
    # outcome of hollowing a gate rather than wrapping their own assertions in `assertRaises`:
    # a control that asserts its own inline assertions fail cannot show that the real test above
    # would die, and it passes just as happily when something unrelated raises.

    def test_production_default_entry_turns_red_when_persistence_gate_is_removed(self):
        """Without the frozen raw receipts the merge cannot verify evidence and must refuse."""
        packets = self._packets()
        for receipt in (packets[1], packets[4]):
            for ref in receipt["source_refs"]:
                (web.ROOT / ref["raw_receipt_ref"]).unlink()
        with self.assertRaises(merge.ThemeDiscoveryMergeError):
            self._merge_and_knife2(packets)

    def test_production_default_entry_turns_red_when_raw_digest_gate_is_removed(self):
        """A frozen raw receipt edited after the fact must not pass its content digest."""
        packets = self._packets()
        web_receipt = packets[1]
        raw_ref = next(ref["raw_receipt_ref"] for ref in web_receipt["source_refs"])
        raw_path = web.ROOT / raw_ref
        tampered = json.loads(raw_path.read_text(encoding="utf-8"))
        tampered["title"] = "tampered title"
        raw_path.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaises(merge.ThemeDiscoveryMergeError):
            self._merge_and_knife2(packets)

    def test_production_default_entry_turns_red_when_ticker_binding_gate_is_removed(self):
        """Hollowing the ticker check must flip the cat-photo control's own outcome."""
        cat = self._packets(cat_aapl=True)
        armed_manifest, armed_validated, _ = self._merge_and_knife2(cat)
        armed = {member["ticker"]: member for theme in armed_validated for member in theme["members"]}
        self.assertNotEqual(armed["AAPL"]["evidence_tier"], "both")
        self.assertGreater(armed_manifest["summary"]["member_evidence_demotion_count"], 0)

        hollowed = self._packets(cat_aapl=True)
        with mock.patch.object(merge, "_raw_payload_mentions_ticker", return_value=True):
            manifest, validated, _ = self._merge_and_knife2(hollowed)
        members = {member["ticker"]: member for theme in validated for member in theme["members"]}
        self.assertEqual(members["AAPL"]["evidence_tier"], "both",
                         "with the gate hollowed the unrelated X post must corroborate again")
        self.assertEqual(manifest["summary"]["member_evidence_demotion_count"], 0)


if __name__ == "__main__":
    unittest.main()
