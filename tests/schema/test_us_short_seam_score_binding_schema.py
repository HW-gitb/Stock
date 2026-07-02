import copy
import json
import unittest

from jsonschema import Draft202012Validator

from engine.us_short_seam_score import load_binding


SCHEMA_PATH = "schemas/us_short_seam_score_binding.schema.json"


def _load_schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


class SeamScoreBindingSchemaTest(unittest.TestCase):
    def setUp(self):
        self._schema = _load_schema()
        self._artifact = load_binding()
        self._validator = Draft202012Validator(self._schema)

    def _errors(self, artifact):
        return list(self._validator.iter_errors(artifact))

    def _mutated(self, path, value):
        artifact = copy.deepcopy(self._artifact)
        node = artifact
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        return artifact

    def test_us_short_seam_score_binding_schema_accepts_artifact(self):
        Draft202012Validator.check_schema(self._schema)
        self.assertEqual(self._errors(self._artifact), [])

    def test_us_short_seam_score_binding_schema_rejects_missing_required_fields(self):
        for field in (
            "artifact_id",
            "owner",
            "input_contract",
            "output_contract",
            "authorization_boundary",
        ):
            with self.subTest(field=field):
                mutated = copy.deepcopy(self._artifact)
                mutated.pop(field)
                self.assertTrue(self._errors(mutated))

    def test_us_short_seam_score_binding_schema_rejects_scope_expansion(self):
        mutated = copy.deepcopy(self._artifact)
        mutated["authorization_boundary"]["provider_call"] = True

        self.assertTrue(self._errors(mutated))

    def test_us_short_seam_score_binding_schema_rejects_load_bearing_const_drift(self):
        mutants = [
            (["composer_ref"], "engine/other.py::compose"),
            (["selection_inputs_consumer_ref"], "other"),
            (["analysis_consumer_ref"], "other"),
            (["component_keys"], ["momentum"]),
            (["score_block_keys"], ["momentum"]),
            (["theme_momentum_policy"], "neutral_50_for_missing_theme"),
            (["theme_momentum_neutral_score"], 50.0),
            (["input_contract", "projection_required_keys"], ["coverage"]),
            (["input_contract", "risk_downgrade_policy"], "missing_defaults_zero"),
            (["output_contract", "required_keys"], ["selection_inputs"]),
            (["output_contract", "selection_row_keys"], ["core_score"]),
            (["output_contract", "analysis_row_keys"], ["score_blocks"]),
        ]
        for path, value in mutants:
            with self.subTest(path=".".join(path)):
                self.assertTrue(self._errors(self._mutated(path, value)))

    def test_us_short_seam_score_binding_schema_rejects_extra_keys(self):
        mutated = copy.deepcopy(self._artifact)
        mutated["extra"] = True
        self.assertTrue(self._errors(mutated))

        mutated = copy.deepcopy(self._artifact)
        mutated["input_contract"]["extra"] = True
        self.assertTrue(self._errors(mutated))


if __name__ == "__main__":
    unittest.main()
