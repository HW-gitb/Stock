from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator

from runners import us_short_llm_theme_discovery_fetch_web as fetch

from tests.provider.test_us_short_llm_theme_discovery_fetch_web import ROWS


class WebFetchSchemaTests(unittest.TestCase):
    def _receipt(self):
        refs = [fetch._source_id("https://example.com/a"), fetch._source_id("https://example.com/b")]
        ds = json.dumps({"themes": [{"theme_id": "power_demand", "display_name": "Power demand", "summary": "Cross-industry power demand.", "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": refs, "members": [{"ticker": "AAPL", "source_ref_ids": refs}]}]})
        _, receipt, _ = fetch.build_web_fetch_packet(
            queries=["x"], search_results=ROWS[:2], llm_response=ds,
            expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z",
        )
        return receipt

    def test_receipt_schema_is_valid(self):
        schema = json.loads((Path(fetch.ROOT) / "schemas/us_short_llm_theme_discovery_fetch_web.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft7Validator(schema).iter_errors(self._receipt())), [])

    def test_frozen_1_0_receipt_without_provider_refs_remains_readable(self):
        schema = json.loads((Path(fetch.ROOT) / "schemas/us_short_llm_theme_discovery_fetch_web.schema.json").read_text(encoding="utf-8"))
        legacy = self._receipt()
        legacy["schema_version"] = "1.0.0"
        legacy.pop("provider_response_refs", None)
        legacy.pop("member_binding_ledger", None)
        legacy.pop("member_binding_summary", None)
        self.assertEqual(list(Draft7Validator(schema).iter_errors(legacy)), [])

    def test_effect_flags_and_live_proof_are_const_pinned(self):
        schema = json.loads((Path(fetch.ROOT) / "schemas/us_short_llm_theme_discovery_fetch_web.schema.json").read_text(encoding="utf-8"))
        bad = self._receipt()
        bad["fetch_contract"]["top15_effect_enabled"] = True
        self.assertTrue(list(Draft7Validator(schema).iter_errors(bad)))
        bad = self._receipt()
        bad["fetch_contract"]["execution_mode"] = "live_authorized"
        self.assertTrue(list(Draft7Validator(schema).iter_errors(bad)))


if __name__ == "__main__":
    unittest.main()
