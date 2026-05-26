from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

try:
    from jsonschema import Draft7Validator
except ImportError:  # pragma: no cover - environment guard
    Draft7Validator = None  # type: ignore[assignment]

from runners.backtest_execution import ROOT
from runners.materialize_a_short_variant_tracking import (
    DEFAULT_OUT_DIR,
    DEFAULT_OUT_NAME,
    DEFAULT_TEMPLATE_PATH,
    main,
    materialize_payload,
    output_path,
    write_payload,
)


@unittest.skipIf(Draft7Validator is None, "jsonschema not installed")
class MaterializeAShortVariantTrackingTest(unittest.TestCase):
    def load_example(self) -> dict:
        return json.loads(DEFAULT_TEMPLATE_PATH.read_text(encoding="utf-8"))

    def test_cli_writes_schema_valid_tracking_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "a_short_variant_tracking_plan.json"

            rc = main(
                [
                    "--out-path",
                    str(out_path),
                    "--generated-at",
                    "2026-05-26T12:00:00+00:00",
                ]
            )

            self.assertEqual(rc, 0)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            schema = json.loads(
                (ROOT / "schemas" / "a_short_variant_tracking.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            errors = sorted(
                Draft7Validator(schema).iter_errors(payload),
                key=lambda item: list(item.path),
            )

            self.assertEqual(errors, [])
            self.assertEqual(payload["generated_at"], "2026-05-26T12:00:00+00:00")
            self.assertEqual(payload["scope"]["contract_status"], "tracking_contract_only")
            self.assertEqual(payload["data_boundaries"]["mutates_egs"], False)
            self.assertEqual(payload["data_boundaries"]["implements_burst_lane"], False)
            self.assertEqual(set(payload["variant_families"]), set(schema["$defs"]["variantFamilies"]["required"]))

    def test_output_path_defaults_to_ignored_variant_plan_dir(self) -> None:
        self.assertEqual(
            output_path(None),
            DEFAULT_OUT_DIR / DEFAULT_OUT_NAME,
        )

    def test_materialize_payload_does_not_mutate_template(self) -> None:
        template = self.load_example()
        original = copy.deepcopy(template)

        payload = materialize_payload(template, generated_at="2026-05-26T12:00:00+00:00")

        self.assertEqual(template, original)
        self.assertEqual(payload["generated_at"], "2026-05-26T12:00:00+00:00")

    def test_scope_creep_template_is_rejected_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            invalid = self.load_example()
            invalid["data_boundaries"]["mutates_egs"] = True
            payload = materialize_payload(invalid, generated_at="2026-05-26T12:00:00+00:00")

            with self.assertRaisesRegex(ValueError, "data_boundaries/mutates_egs"):
                write_payload(payload, Path(tmpdir) / "plan.json")


if __name__ == "__main__":
    unittest.main()
