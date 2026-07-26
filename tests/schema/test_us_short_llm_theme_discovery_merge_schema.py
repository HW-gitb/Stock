from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft7Validator

from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from runners import us_short_llm_theme_discovery_merge as merge

X_ROWS = [
    {"url": "https://x.example/post/schema-merge", "title": "Power", "text": "AAPL", "created_at": "2026-07-24T10:00:00Z"},
]


class MergeSchemaTests(unittest.TestCase):
    def test_merge_manifest_schema_and_effect_pins(self):
        source_id = xfetch._source_id(X_ROWS[0]["url"])
        response = json.dumps({"themes": [{"theme_id": "power_demand", "display_name": "Power", "summary": "Power", "observed_at": "2026-07-24T12:00:00Z", "source_ref_ids": [source_id], "members": [{"ticker": "AAPL", "source_ref_ids": [source_id]}]}]})
        xa, xr, _ = xfetch.build_x_fetch_packet(queries=["power"], results=X_ROWS, grok_response=response, expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        # Empty web side is valid for the merge contract; it still proves the manifest shape and pins.
        from runners import us_short_llm_theme_discovery_fetch_web as web
        wa, wr, _ = web.build_web_fetch_packet(queries=["power"], search_results=[], llm_response='{"themes":[]}', expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        _, manifest = merge.merge_web_x_discovery(web_artifact=wa, web_receipt=wr, x_artifact=xa, x_receipt=xr, expected_decision_date="20260725", generated_at="2026-07-25T08:00:00Z")
        schema = json.loads((Path(merge.ROOT) / "schemas/us_short_llm_theme_discovery_merge.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(Draft7Validator(schema).iter_errors(manifest)), [])
        bad = json.loads(json.dumps(manifest))
        bad["merge_contract"]["top15_effect_enabled"] = True
        self.assertTrue(list(Draft7Validator(schema).iter_errors(bad)))


if __name__ == "__main__":
    unittest.main()
