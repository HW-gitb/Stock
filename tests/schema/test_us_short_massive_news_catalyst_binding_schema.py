import copy
import json
import unittest

from jsonschema import Draft202012Validator

from engine.us_short_massive_news_catalyst import load_binding


SCHEMA_PATH = "schemas/us_short_massive_news_catalyst_binding.schema.json"


def _load_schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


class MassiveNewsCatalystBindingSchemaTest(unittest.TestCase):
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

    def test_us_short_massive_news_catalyst_binding_schema_accepts_artifact(self):
        Draft202012Validator.check_schema(self._schema)
        self.assertEqual(self._errors(self._artifact), [])

    def test_us_short_massive_news_catalyst_binding_schema_rejects_missing_required_fields(self):
        for field in (
            "artifact_id",
            "producer_refs",
            "scoring_transform",
            "output_contract",
            "authorization_boundary",
        ):
            with self.subTest(field=field):
                mutated = copy.deepcopy(self._artifact)
                mutated.pop(field)
                self.assertTrue(self._errors(mutated))

    def test_us_short_massive_news_catalyst_binding_schema_rejects_scope_expansion(self):
        for field in ("provider_call", "live_data", "llm_call", "datahub_write", "production_runner"):
            with self.subTest(field=field):
                mutated = copy.deepcopy(self._artifact)
                mutated["authorization_boundary"][field] = True
                self.assertTrue(self._errors(mutated))

    def test_us_short_massive_news_catalyst_binding_schema_rejects_load_bearing_const_drift(self):
        mutants = [
            (["producer_refs"], ["engine/other.py::fn"]),
            (["projection_policy"], "free_text_sentiment_score"),
            (["input_contract", "source_result_required_keys"], ["signals"]),
            (["input_contract", "summary_key"], "other"),
            (["input_contract", "summary_fields"], ["news_count"]),
            (["scoring_transform", "score_formula"], "net_sentiment"),
            (["scoring_transform", "input_bounds"], [0.0, 1.0]),
            (["scoring_transform", "catalyst_signal_key"], "news_sentiment_score"),
            (["output_contract", "required_keys"], ["catalyst_block_by_ticker"]),
            (["output_contract", "coverage_dispositions"], ["scored"]),
        ]
        for path, value in mutants:
            with self.subTest(path=".".join(path)):
                self.assertTrue(self._errors(self._mutated(path, value)))

    def test_us_short_massive_news_catalyst_binding_schema_rejects_extra_keys(self):
        mutated = copy.deepcopy(self._artifact)
        mutated["extra"] = True
        self.assertTrue(self._errors(mutated))

        mutated = copy.deepcopy(self._artifact)
        mutated["scoring_transform"]["extra"] = True
        self.assertTrue(self._errors(mutated))


if __name__ == "__main__":
    unittest.main()
