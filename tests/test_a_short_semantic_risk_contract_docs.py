from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_semantic_risk_summary import validate_web_llm_patch  # noqa: E402


AS_OF = "20260630"
TS_CODE = "600000.SH"
SRC = {
    "title": "checked source",
    "url": "https://example.invalid/news",
    "published_at": "2026-06-10",
    "fetched_at": None,
    "source_type": "web",
}


def _patch(status: str, risk_level: str, action: str, sources: list[dict] | None = None) -> dict:
    return {
        "schema_name": "a_short_semantic_risk_web_llm_patch",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-30T13:00:00+08:00",
        "target": {
            "as_of": AS_OF,
            "summary_schema_name": "a_short_semantic_risk_summary",
            "summary_schema_version": "1.0.0",
        },
        "source": {"kind": "skill_web_llm", "prompt_refs": ["skills/a_short_analysis/prompts/x.md"]},
        "candidates": [
            {
                "ts_code": TS_CODE,
                "web_llm": {"status": status, "risk_level": risk_level, "action": action},
                "sources": [] if sources is None else sources,
                "confidence": 0.7,
            }
        ],
        "boundary": {
            "advisory_only": True,
            "not_deterministic_veto": True,
            "never_touches_official": True,
        },
    }


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


class SemanticRiskContractDocs(unittest.TestCase):
    def test_behavior_anchor_non_unknown_requires_sources(self):
        with self.assertRaises(ValueError):
            validate_web_llm_patch(_patch("clear_light", "none", "no_action"))
        with self.assertRaises(ValueError):
            validate_web_llm_patch(_patch("tailwind", "low", "observe"))
        validate_web_llm_patch(_patch("unknown", "unknown", "no_action"))
        validate_web_llm_patch(_patch("clear_light", "none", "no_action", [SRC]))

    def test_behavior_anchor_unknown_requires_no_action(self):
        # contract: 无证据 ⇒ unknown/unknown/no_action; a no-evidence candidate cannot carry a soft action
        with self.assertRaises(ValueError):
            validate_web_llm_patch(_patch("unknown", "unknown", "downgrade"))
        with self.assertRaises(ValueError):
            validate_web_llm_patch(_patch("unknown", "unknown", "manual_review_required"))
        validate_web_llm_patch(_patch("unknown", "unknown", "no_action"))   # the only neutral triple

    def test_stable_contract_locks_unknown_neutral_triple(self):
        text = _read("docs/a_short_semantic_risk_contract.md")
        self.assertIn("unknown/unknown/no_action", text)

    def test_stable_contract_contains_current_web_evidence_rule(self):
        text = _read("docs/a_short_semantic_risk_contract.md")
        self.assertIn("任何非 `unknown` 的 web 状态都必须带 `sources` 证据", text)
        self.assertIn("`web_llm.status == \"unknown\"`", text)
        self.assertIn("可以空 `sources`", text)

    def test_coverage_doc_points_to_contract_not_matrix(self):
        # B2 contract-anchor: coverage routes to the contract, does NOT re-describe the rule matrix.
        text = _read("docs/a_short_semantic_risk_coverage.md")
        self.assertIn("docs/a_short_semantic_risk_contract.md", text)             # routes to anchor
        self.assertNotIn("clear_light ⇒ risk_level none", text)                   # no per-status matrix
        self.assertNotIn("tailwind ⇒ none/low", text)
        self.assertIsNone(                                                        # no old weak rule
            re.search(r"风险态\(risk_candidate/risk/headwind\).*必有 sources", text),
            "coverage doc must not restate the matrix / only-risk-needs-sources rule",
        )

    def test_readme_routes_to_contract_not_matrix(self):
        # B2: README routes to the contract and must NOT restate the web invariant (full or partial).
        text = _read("docs/README.md")
        self.assertIn("docs/a_short_semantic_risk_contract.md", text)             # routes to anchor
        self.assertNotIn("any non-unknown/evaluated web status requires sources", text)
        self.assertNotIn("web risk-status ⇒ sources required", text)
        self.assertNotIn("clear_light ⇒ risk_level none", text)

    def test_schema_description_points_to_contract_not_matrix(self):
        text = _read("schemas/a_short_semantic_risk_web_llm_patch.schema.json")
        self.assertIn("a_short_semantic_risk_contract.md", text)
        self.assertNotIn("any non-unknown/evaluated web status requires sources", text)

    def test_coverage_doc_rejects_exact_48h_overclaim(self):
        text = _read("docs/a_short_semantic_risk_coverage.md")
        self.assertIn("默认 90 天", text)
        self.assertIn("并非精确\"48h 新鲜度\"窗口", text)
        self.assertIn("未来 recency 字段", text)


if __name__ == "__main__":
    unittest.main()
