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

    def test_web_llm_skill_prompt_routes_to_contract_and_states_core_rules(self):
        # Slice 2b-ii-B skill prompt must route to the contract and restate the load-bearing
        # advisory rules (so a future edit can't quietly drop them); it must not become a hard veto.
        text = _read("skills/a_short_analysis/prompts/semantic_risk_web_llm.md")
        self.assertIn("docs/a_short_semantic_risk_contract.md", text)        # routes to the anchor
        self.assertIn("a_short_semantic_risk_web_llm_patch", text)           # produces the patch
        self.assertIn("unknown/unknown/no_action", text)                    # unknown-not-clear neutral triple
        for kw in ("Advisory only", "hard veto", "Main-board Top15", "Evidence required"):
            self.assertIn(kw, text, f"web_llm skill prompt lost rule anchor: {kw}")

    # ---- single-source + LOCAL panel-gate drift guard (helpers shared with the planted test) ----
    # CONSUMER symbols denote the weekly consumer landing (the function + its CLI flag). The
    # renderer name `render_semantic_risk_panel` ALONE is a building block (e.g. the Slice-2b-i
    # render-only README row legitimately names it with wiring still deferred), so it is NOT by
    # itself a consumer-landing claim. The drift SHAPE Codex planted is the renderer gated
    # directly by consistency — render_* co-occurring with validate_summary_consistency — which
    # bypasses the gatekeeper; that combination IS treated as a landing block.
    CONSUMER_TOKENS = ("_semantic_panel_from_summary", "--semantic-risk-summary")
    STALE_GATE_WORDING = (
        "校验 schema_name + as_of 一致 + `validate_summary_consistency`",
        "un-validated-or-forged summary via `validate_summary_consistency`",
        "as_of 须与周报一致且过一致性校验",
    )

    @classmethod
    def _is_landing_block(cls, b):
        if any(t in b for t in cls.CONSUMER_TOKENS):
            return True
        return "render_semantic_risk_panel" in b and "validate_summary_consistency" in b

    @classmethod
    def _landing_blocks(cls, text):
        # LOCAL unit: paragraphs split on blank lines; a paragraph that is a markdown table is
        # further split per row, so one table row = one block (README is a one-row-per-line table).
        # Returns only the blocks that actually teach the consumer landing.
        import re
        blocks = []
        for para in re.split(r"\n\s*\n", text):
            lines = para.split("\n")
            if any(ln.lstrip().startswith("|") for ln in lines):
                blocks.extend(lines)
            else:
                blocks.append(para)
        return [b for b in blocks if cls._is_landing_block(b)]

    def _assert_landing_block_ok(self, name, block):
        # single-source rule, checked LOCALLY: a block that teaches the landing must ROUTE to the
        # gatekeeper function (point at the one authoritative source) and carry no stale wording.
        self.assertIn("_semantic_panel_from_summary", block,
                      f"{name}: a landing block doesn't route to the single-source gatekeeper:\n{block[:240]}")
        for s in self.STALE_GATE_WORDING:
            self.assertNotIn(s, block, f"{name}: a landing block carries stale gate wording:\n{block[:240]}")

    def test_panel_gate_is_single_sourced_not_duplicated(self):
        # SINGLE-SOURCE + LOCAL guard. Two root fixes combined:
        #  (a) single-source (user-directed): gate steps live in EXACTLY ONE place — the
        #      `_semantic_panel_from_summary` docstring (code-adjacent + pinned by the
        #      `test_panel_rejects_*` rejection tests). Every other surface only POINTS (names the
        #      function), so there is nothing to drift. The prior guards FORCED every surface to
        #      repeat "schema+consistency" — institutionalizing the very duplication that drifted.
        #  (b) LOCALITY (R-ASHORT-SEMANTIC-PANEL-GUARD-FILE-LEVEL-FALSE-NEGATIVE): the routing
        #      check is per landing BLOCK (table row / paragraph), NOT whole-file — a stale landing
        #      block can no longer hide in a file that has correct text elsewhere. The companion
        #      test_panel_gate_guard_is_local_planted_failure proves the locality.
        import glob
        # (1) the ONE authoritative source: the docstring enumerates the full gate.
        pipe = _read("runners/a_short_weekly_pipeline.py")
        anchor = pipe.find("def _semantic_panel_from_summary")
        self.assertNotEqual(anchor, -1, "lost the single-source gatekeeper function")
        self.assertIn("schema+consistency", pipe[anchor: anchor + 1400],
                      "authoritative docstring must enumerate the schema+consistency gate")
        # (2) the CLI help points to the gatekeeper (does not re-enumerate steps).
        h = pipe.find("--semantic-risk-summary")
        self.assertIn("_semantic_panel_from_summary", pipe[h:h + 600],
                      "--semantic-risk-summary help must point to the single-source gatekeeper")
        # (3) every active teaching surface: each landing BLOCK is checked locally.
        HISTORY = {"SESSION_LOG.md", "system_risk_register.md"}
        surfaces = (glob.glob(str(ROOT / "docs" / "*.md"))         # non-recursive: skips archive/handoff
                    + glob.glob(str(ROOT / "skills" / "**" / "*.md"), recursive=True))
        reached = []
        for path in surfaces:
            name = Path(path).name
            if name in HISTORY:
                continue
            blocks = self._landing_blocks(Path(path).read_text(encoding="utf-8"))
            if blocks:
                reached.append(name)
            for b in blocks:
                self._assert_landing_block_ok(name, b)
        for expect in ("README.md", "a_short_semantic_risk_coverage.md", "semantic_risk_web_llm.md"):
            self.assertIn(expect, reached, f"single-source sweep failed to reach {expect}")

    def test_panel_gate_guard_is_local_planted_failure(self):
        # Proves the guard is LOCAL, not whole-file (Codex's exact reproduction of
        # R-ASHORT-SEMANTIC-PANEL-GUARD-FILE-LEVEL-FALSE-NEGATIVE): append a stale landing
        # paragraph to README — which already contains correct content elsewhere — and require the
        # per-block check to FAIL on the planted paragraph.
        planted = _read("docs/README.md") + (
            "\n\nFuture stale panel landing: render_semantic_risk_panel is appended after "
            "validate_summary_consistency; no schema gate mentioned here.\n")
        with self.assertRaises(AssertionError):
            for b in self._landing_blocks(planted):
                self._assert_landing_block_ok("README.md(planted)", b)

    def test_coverage_doc_rejects_exact_48h_overclaim(self):
        text = _read("docs/a_short_semantic_risk_coverage.md")
        self.assertIn("默认 90 天", text)
        self.assertIn("并非精确\"48h 新鲜度\"窗口", text)
        self.assertIn("未来 recency 字段", text)


if __name__ == "__main__":
    unittest.main()
