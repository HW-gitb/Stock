"""Schema tests for the manual A-short account/position state input."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_PATH = ROOT / "schemas" / "a_short_account_state.schema.json"
EXAMPLE_PATH = ROOT / "schemas" / "examples" / "a_short_account_state.example.json"


class AShortAccountStateSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

    def test_example_validates(self):
        jsonschema.validate(self.example, self.schema)

    def test_broker_connection_is_forbidden(self):
        bad = copy.deepcopy(self.example)
        bad["broker_connection_allowed"] = True
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_manual_order_only_is_required(self):
        bad = copy.deepcopy(self.example)
        bad["manual_order_only"] = False
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_position_requires_manual_stop_loss(self):
        # 向后兼容:1.0.0(example 即 1.0.0)仍**严格要求** stop_loss(draft-07 if/then)。
        bad = copy.deepcopy(self.example)
        del bad["positions"][0]["stop_loss"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)

    def test_v110_position_stop_loss_optional(self):
        # S3a:schema_version 1.1.0 → positions.stop_loss 可缺(系统算止损,手填降参考);1.0.0 仍严格(上一测)。
        good = copy.deepcopy(self.example)
        good["schema_version"] = "1.1.0"
        del good["positions"][0]["stop_loss"]
        jsonschema.validate(good, self.schema)      # 不抛 = 1.1.0 放开

    def test_unknown_top_level_field_rejected(self):
        bad = copy.deepcopy(self.example)
        bad["market_regime"] = "进攻期"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, self.schema)


if __name__ == "__main__":
    unittest.main()
