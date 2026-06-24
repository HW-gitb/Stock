# -*- coding: utf-8 -*-
"""Schema-conformance test: the frozen market-calendar preset matches its JSON schema — batch4 slice 4b.

This pins the ARTIFACT shape (us_short_market_calendar.schema.json) against the committed preset.
It does NOT (and cannot, offline) assert holiday-date accuracy — that is gated on authoritative
cross-check via data_provenance.verification_status (SR-PROVIDER-001). Date-accuracy stays a
reviewed/authoritative concern; this test only enforces the structural contract.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import jsonschema  # noqa: E402

_SCHEMA = ROOT / "schemas" / "us_short_market_calendar.schema.json"
_PRESET = ROOT / "presets" / "us_short_market_calendar_2026_2027.json"


class MarketCalendarSchemaTests(unittest.TestCase):
    def test_preset_conforms_to_schema(self):
        schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
        preset = json.loads(_PRESET.read_text(encoding="utf-8"))
        jsonschema.validate(instance=preset, schema=schema)

    def test_schema_rejects_non_rth_close(self):
        schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
        bad = json.loads(_PRESET.read_text(encoding="utf-8"))
        bad["regular_close"] = "15:00"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)

    def test_schema_rejects_unknown_verification_status(self):
        schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
        bad = json.loads(_PRESET.read_text(encoding="utf-8"))
        bad["data_provenance"]["verification_status"] = "trust_me"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)

    def test_schema_rejects_non_1300_half_day_close(self):
        schema = json.loads(_SCHEMA.read_text(encoding="utf-8"))
        bad = json.loads(_PRESET.read_text(encoding="utf-8"))
        bad["half_days"]["20261127"] = "14:00"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(instance=bad, schema=schema)


if __name__ == "__main__":
    unittest.main()
