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
        # README no longer teaches the panel landing (the semantic-web rows were consolidated to a single
        # pointer row in the run-path single-source refactor); coverage + skill-prompt still teach + route it.
        for expect in ("a_short_semantic_risk_coverage.md", "semantic_risk_web_llm.md"):
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

    def test_contract_expresses_m67_advisory_distinction_not_absolute_no_hard_veto(self):
        # R-ASHORT-SEMANTIC-CONTRACT-M67-INTEGRATION-DRIFT: after the M6.7 integration, active docs
        # must NOT keep the old absolute whole-layer "no hard veto / panel-only" wording while the
        # engine makes official high → advisory 否决. One authoritative distinction in the contract:
        # production EGS scoring/decision/veto + backtest forbidden; web_llm never hard-veto; but
        # validated official high MAY produce an advisory 否决 inside non-production M6.7.
        contract = _read("docs/a_short_semantic_risk_contract.md")
        coverage = _read("docs/a_short_semantic_risk_coverage.md")
        # old absolute whole-layer no-hard-veto wording must be gone (it contradicts M6.7 evidence-full high→否决)
        self.assertNotIn("语义风险层是 advisory-only:不硬否决", contract,
                         "contract still asserts absolute whole-layer no-hard-veto (contradicts M6.7 integration)")
        self.assertNotIn("**advisory-only**。绝不硬否决、不进 production scoring", coverage,
                         "coverage still asserts absolute whole-layer no-hard-veto")
        # contract must carry the production-vs-M6.7 advisory distinction
        for kw in ("production EGS", "web_llm", "official_structured", "semantic_official", "否决"):
            self.assertIn(kw, contract, f"contract lost the M6.7-distinction anchor: {kw}")
        # web_llm must STILL be pinned as never-hard-veto (only official-high may advisory-否决)
        self.assertIn("绝不硬否决", contract)
        # README routes to the distinction too (not the old panel-only-as-final-invariant)
        readme = _read("docs/README.md")
        self.assertIn("semantic_official", readme)
        # Slice 1b evidence-full rule must be the stated rule (not generic "any high vetoes"):
        # high needs non-empty url_or_pdf to advisory-否决; blank-URL high routes to pending.
        for kw in ("url_or_pdf", "证据齐全", "待核"):
            self.assertIn(kw, contract, f"contract lost the Slice-1b evidence-full anchor: {kw}")
        # R-ASHORT-M67-EVIDENCE-FULL-ROUTEDOC-GUARD-WEAKNESS: the route docs RESTATE the rule, so each
        # must carry ALL load-bearing anchors (not just `url_or_pdf`), else they can drift back to a
        # generic "official high vetoes" row while still containing the word `url_or_pdf`.
        coverage = _read("docs/a_short_semantic_risk_coverage.md")
        for kw in ("url_or_pdf", "待核", "不否决"):
            self.assertIn(kw, coverage, f"coverage evidence-full block lost anchor: {kw}")
        for kw in ("url_or_pdf", "pending", "never veto"):
            self.assertIn(kw, readme, f"README evidence-full row lost anchor: {kw}")

    def test_coverage_doc_rejects_exact_48h_overclaim(self):
        text = _read("docs/a_short_semantic_risk_coverage.md")
        self.assertIn("默认 90 天", text)
        self.assertIn("并非精确\"48h 新鲜度\"窗口", text)
        self.assertIn("未来 recency 字段", text)

    # ---- R-ASHORT-SEMANTIC-WEBLLM-RUNPATH-SINGLE-SOURCE-GUARD-GAP — REAL single-source guard ----
    # The web_llm run-path (current = weekly M6.7 DeepSeek auto / transitional = standalone summary +
    # 2b-ii skill-patch + Stage-4 sidecar) is stated ONCE, in the contract §web_llm 产出路径. Codex round-5:
    # the prior guard let "pointer somewhere on the line" exempt a line that ALSO re-narrated the path, and
    # missed current-path narration (`current auto web path` / `web_llm UNKNOWN here` / `DeepSeek auto-provider`).
    # FIX: a STRICT surface that re-narrates the run-path (any RUNPATH_NARRATION phrase) is an offender
    # REGARDLESS of a co-located pointer — a route surface must POINT only, never re-narrate (current OR
    # transitional). The non-archive DESIGN doc may keep historical wording ONLY if the line carries an
    # inline supersession pointer to the contract section.
    RUNPATH_NARRATION = (
        # current-path narration (must live only in the contract)
        "current auto web path", "current web conclusion", "CURRENT web conclusion", "web_llm UNKNOWN here",
        "DeepSeek auto-provider", "auto-connects", "web 自动判走",
        # producer / transitional narration
        "skill-in-loop", "left unknown here", "skill to fill", "skill fills", "skill 在环",
        "2b-ii skill", "Slice-2b skill", "Slice 2 skill", "Slice-2 web layer", "formal Slice-2 layer",
        "Slice 2 formal advisory layer", "全留 unknown", "web 留 unknown", "未评估(unknown",
        "stays UNKNOWN until", "不能纯自动化", "web_llm 另跑",
    )
    SINGLE_SOURCE_POINTER = "§web_llm 产出路径"     # the one authority section (in the contract)

    @classmethod
    def _strict_surfaces(cls):
        # GLOB-DISCOVERED (not a hand-curated list — Codex round-6/7 kept finding a missed surface, e.g.
        # the Slice-1 probe runner). Every non-archive semantic-risk DOC + the semantic-risk RUNNERS
        # (probe / summary = `runners/a_short_semantic_risk_*.py`) + the weekly orchestration script are
        # checked. The contract (authority) and pure implementation files (adapter / engine / pipeline,
        # which are NOT named a_short_semantic_risk_*) are deliberately excluded.
        import glob
        files = ["docs/a_short_semantic_risk_coverage.md", "docs/README.md", "runners/weekly_screening.ps1"]
        files += sorted(str(Path(p).relative_to(ROOT)).replace("\\", "/")
                        for p in glob.glob(str(ROOT / "runners" / "a_short_semantic_risk_*.py")))
        return files
    DESIGN_SURFACES = ("docs/a_short_semantic_risk_top15_enrichment_design_20260612.md",)
    # The 2b-ii skill prompt is the transitional COMPONENT's own instruction file (every line is about the
    # skill doing the web/LLM judgment — a per-line "point only" rule is nonsensical). It is instead checked
    # at FILE level: it must carry a supersession banner = a transitional marker + the run-path pointer, so a
    # reader sees it is the transitional path and that the current run-path is single-sourced in the contract.
    BANNER_SUPERSEDED_SURFACES = ("skills/a_short_analysis/prompts/semantic_risk_web_llm.md",)
    TRANSITIONAL_MARKERS = ("过渡", "transitional", "SUPERSEDED", "Slice 3")

    @classmethod
    def _separate_run_offenders(cls, text, pointer_exempts=False):
        # shared by the live guard AND the planted test. STRICT (pointer_exempts=False): a line that
        # re-narrates the run-path is an offender even if it also carries the pointer (a route surface
        # must POINT only). DESIGN (pointer_exempts=True): a historical-design line may keep the wording
        # if it carries an inline supersession pointer to the contract section.
        out = []
        for ln in text.splitlines():
            if not any(s in ln for s in cls.RUNPATH_NARRATION):
                continue
            if pointer_exempts and cls.SINGLE_SOURCE_POINTER in ln:
                continue
            out.append(ln.strip()[:200])
        return out

    def test_no_pre_slice2_separate_web_workflow_taught_as_current(self):
        # authority: the contract holds the §web_llm 产出路径 section with the canonical current-vs-transitional
        # statement; no other surface re-states it.
        contract = _read("docs/a_short_semantic_risk_contract.md")
        self.assertIn("## web_llm 产出路径", contract, "contract lost the single-source web run-path section")
        for kw in ("当前结论路", "DeepSeek adapter 自动", "过渡路", "Slice 3"):
            self.assertIn(kw, contract, f"contract run-path section lost anchor: {kw}")
        # STRICT route surfaces (glob-discovered): ZERO run-path narration (point only — a co-located
        # pointer does NOT exempt). Glob ensures a new semantic-risk runner/doc can't silently escape.
        for rel in self._strict_surfaces():
            off = self._separate_run_offenders(_read(rel))
            self.assertEqual(off, [], f"{rel} re-narrates the web run-path (must POINT only to {self.SINGLE_SOURCE_POINTER}, "
                                      f"never re-narrate current/transitional path): {off}")
        # non-archive DESIGN doc: historical wording allowed ONLY with an inline supersession pointer
        for rel in self.DESIGN_SURFACES:
            off = self._separate_run_offenders(_read(rel), pointer_exempts=True)
            self.assertEqual(off, [], f"{rel} teaches the old run-path without an inline supersession pointer "
                                      f"({self.SINGLE_SOURCE_POINTER}): {off}")
        # transitional COMPONENT prompt(s): FILE-LEVEL supersession banner (transitional marker + run-path pointer)
        for rel in self.BANNER_SUPERSEDED_SURFACES:
            t = _read(rel)
            self.assertIn(self.SINGLE_SOURCE_POINTER, t,
                          f"{rel} lost the run-path pointer to the contract single source")
            self.assertTrue(any(mk in t for mk in self.TRANSITIONAL_MARKERS),
                            f"{rel} must carry a transitional/SUPERSEDED component banner")
        # coverage + README must carry the pointer (route to the single source)
        for rel in ("docs/a_short_semantic_risk_coverage.md", "docs/README.md"):
            self.assertIn(self.SINGLE_SOURCE_POINTER, _read(rel),
                          f"{rel} lost the pointer to the contract single source")

    def test_separate_web_workflow_guard_is_real_planted(self):
        # the EXACT Codex round-5 false negatives must now FAIL on a STRICT surface, pointer notwithstanding.
        ptr_plus_renarration = ("This Stage-4 is a transitional standalone sidecar (web_llm UNKNOWN here); "
                                "the current auto web path is the M6.7 weekly pipeline. 产出路径见契约 §web_llm 产出路径")
        self.assertTrue(self._separate_run_offenders(ptr_plus_renarration),
                        "STRICT: pointer + local current-path re-narration must FAIL (the round-5 false negative)")
        skill_renarration = "web_llm (skill-in-loop, left unknown here) for the Slice-2b skill to fill. §web_llm 产出路径"
        self.assertTrue(self._separate_run_offenders(skill_renarration),
                        "STRICT: a header pointer must not mask local skill-in-loop / left-unknown-here run-path wording")
        probe_variant = "完整 web+LLM 判断属 Slice 2 skill 在环,本函数只喂原始 sources。"  # Codex round-7 non-hyphen probe variant
        self.assertTrue(self._separate_run_offenders(probe_variant),
                        "STRICT: the non-hyphen 'Slice 2 skill 在环' probe variant must FAIL")
        pure_pointer = "web_llm run path: see contract §web_llm 产出路径 (transitional sidecar)."
        self.assertEqual(self._separate_run_offenders(pure_pointer), [],
                         "a pure pointer line (no run-path narration) is fine")
        # DESIGN doc: old wording WITH an inline supersession pointer is allowed; WITHOUT it fails.
        design_superseded = "web+LLM 层 = skill 在环(已超越:run-path 单一来源见契约 §web_llm 产出路径)"
        self.assertEqual(self._separate_run_offenders(design_superseded, pointer_exempts=True), [],
                         "DESIGN: a historical line with an inline supersession pointer is allowed")
        self.assertTrue(self._separate_run_offenders("web+LLM 层 = skill 在环", pointer_exempts=True),
                        "DESIGN: a historical run-path line without a supersession pointer must FAIL")
        # BANNER tier (skill prompt): a prompt-style file WITHOUT the supersession banner (no pointer +
        # no transitional marker) must fail the file-level banner check.
        prompt_no_banner = ("Purpose: this is the Slice 2b-ii web/LLM advisory layer (skill-in-loop). "
                            "Do the LIVE web/LLM judgment and emit the patch.")
        self.assertFalse(self.SINGLE_SOURCE_POINTER in prompt_no_banner
                         and any(mk in prompt_no_banner for mk in self.TRANSITIONAL_MARKERS),
                         "BANNER planted: a prompt without the supersession banner must fail the banner check")
        prompt_with_banner = ("过渡组件 / transitional (Slice 3 retires); run-path 见契约 §web_llm 产出路径. "
                              "Purpose: produce the patch (skill-in-loop).")
        self.assertTrue(self.SINGLE_SOURCE_POINTER in prompt_with_banner
                        and any(mk in prompt_with_banner for mk in self.TRANSITIONAL_MARKERS),
                        "BANNER planted: a prompt WITH the supersession banner passes the banner check")


if __name__ == "__main__":
    unittest.main()
