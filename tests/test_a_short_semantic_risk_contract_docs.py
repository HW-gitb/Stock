from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_semantic_risk_summary import _web_llm_consistency_error  # noqa: E402


SRC = {
    "title": "checked source",
    "url": "https://example.invalid/news",
    "published_at": "2026-06-10",
    "fetched_at": None,
    "source_type": "web",
}


def _web(status: str, risk_level: str, action: str, sources: list[dict] | None = None):
    # Slice 3a: the web_llm cross-field invariant is enforced by the shared _web_llm_consistency_error
    # (DeepSeek adapter + engine). The retired skill-patch validator delegated to the same fn, so these
    # behavior anchors still pin the LIVE invariant. Returns an error string, or None if the triple is valid.
    return _web_llm_consistency_error(
        {"status": status, "risk_level": risk_level, "action": action},
        [] if sources is None else sources)


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


class SemanticRiskContractDocs(unittest.TestCase):
    def test_behavior_anchor_non_unknown_requires_sources(self):
        self.assertIsNotNone(_web("clear_light", "none", "no_action"))      # no evidence -> rejected
        self.assertIsNotNone(_web("tailwind", "low", "observe"))
        self.assertIsNone(_web("unknown", "unknown", "no_action"))          # neutral triple ok
        self.assertIsNone(_web("clear_light", "none", "no_action", [SRC]))  # with evidence ok

    def test_behavior_anchor_unknown_requires_no_action(self):
        # contract: 无证据 ⇒ unknown/unknown/no_action; a no-evidence candidate cannot carry a soft action
        self.assertIsNotNone(_web("unknown", "unknown", "downgrade"))
        self.assertIsNotNone(_web("unknown", "unknown", "manual_review_required"))
        self.assertIsNone(_web("unknown", "unknown", "no_action"))          # the only neutral triple

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

    def test_semantic_panel_retired_inline_in_m67(self):
        # Slice 3b: the standalone semantic panel is retired — semantic is rendered INLINE in the
        # M6.7 markdown (per-票 from machine.layer.semantic_risk). The panel renderer / consumer / CLI
        # flag stay gone; the renderer carries the inline helper instead.
        self.assertNotIn("def render_semantic_risk_panel", _read("runners/a_short_semantic_risk_summary.py"))
        pipe = _read("runners/a_short_weekly_pipeline.py")
        self.assertNotIn("_semantic_panel_from_summary", pipe)
        self.assertNotIn("--semantic-risk-summary", pipe)
        render = _read("runners/a_short_m67_render.py")
        self.assertIn("def _semantic_line", render)        # semantic now inline in the M6.7 card
        self.assertNotIn("semantic_panel", render)          # no separate-panel param

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
    # Stage-4 sidecar; the 2b-ii skill-patch path was retired in Slice 3a) is stated ONCE, in the contract
    # §web_llm 产出路径. Codex round-5:
    # the prior guard let "pointer somewhere on the line" exempt a line that ALSO re-narrated the path, and
    # missed current-path narration (`current auto web path` / `web_llm UNKNOWN here` / `DeepSeek auto-provider`).
    # Slice 3a convergence (Codex 2026-06-14): the recurring drift class was a never-ending PHRASE
    # blacklist over an under-covered surface set. Replaced by (a) a CLOSED retired-workflow ROOT
    # vocabulary checked in web/semantic context and only when NOT carrying a retired/historical marker
    # (so new phrasings — combinations of the same roots — can't escape, and a correctly-labelled
    # "retired in Slice 3a" mention is allowed), plus (b) a small CURRENT-narration phrase set that a
    # route surface must never restate even with a pointer (round-5 fix). Bare over-broad words
    # ("skill" / "patch" / "2b-ii") are deliberately NOT roots — every root is specific.
    CURRENT_NARRATION = (
        "current auto web path", "current web conclusion", "CURRENT web conclusion", "web_llm UNKNOWN here",
        "DeepSeek auto-provider", "auto-connects", "web 自动判走", "left unknown here", "全留 unknown",
        "web 留 unknown", "stays UNKNOWN until", "不能纯自动化", "web_llm 另跑",
        "Slice-2 web layer", "formal Slice-2", "Slice 2 formal advisory layer",
    )
    # SPECIFIC roots: strings inherently part of the retired a_short skill-patch web workflow — they do
    # not occur legitimately elsewhere, so each is an offender on its own (no context needed).
    SPECIFIC_ROOTS = (
        "skill-in-loop", "skill 在环", "skill-patch", "skill to fill", "skill fills",
        "skill 降级", "skill 精判", "待 skill", "skill 评估", "2b skill", "web/llm skill", "web_llm skill",
        "2b-ii skill", "2b-ii-a", "2b-ii-b skill", "slice-2b skill", "slice 2 skill",
        "apply_web_llm_patch", "validate_web_llm_patch", "web_llm_patch", "web_llm patch", "semantic_risk_web_llm",
        "patch merge", "merge whitelist",   # round-4: the retired §Patch Merge / patch-merge-whitelist claim
    )
    # GENERIC roots: short phrases that CAN appear in unrelated docs, caught ONLY in a_short web_llm context.
    # Bare "skill"/"patch" are deliberately NOT roots (Codex: too broad — "Codex patch" / analysis "skill"
    # are legitimate); the retired Chinese/compound variants (2b skill / skill 降级 / web_llm patch / …) are
    # enumerated in SPECIFIC_ROOTS above instead, so coverage stays high without bare-word false positives.
    GENERIC_ROOTS = ("skill prompt", "skill/prompt")
    WEB_CONTEXT = ("web_llm", "web/llm", "web+llm")
    RETIRED_MARKERS = ("退役", "retired", "superseded", "已超越", "历史", "过渡", "transitional",
                       "slice 3", "取代", "replaced", "已删", "deleted", "不再", "旧", "old")
    SINGLE_SOURCE_POINTER = "§web_llm 产出路径"     # the one authority section (in the contract)

    @classmethod
    def _strict_surfaces(cls):
        # GLOB-DISCOVERED across the active surface CLASSES, SCOPED to the a_short semantic-risk DOMAIN
        # (Codex 2026-06-14 "glob all active classes", scoped by `a_short_semantic_risk_*` prefix + the
        # cross-cutting route README + the weekly entry/pipeline + semantic runners). Domain-scoping is the
        # same anti-false-positive principle Codex applied to bare words: scanning EVERY docs/*.md tripped
        # cross-domain (`us_short_spec.md`) and meta (`pre_codex_self_review_checklist.md`) files that merely
        # mention "skill" as an example. Excluded: history (SESSION_LOG / register / archive / handoff),
        # research data, frozen skill `reference/` specs, the DESIGN doc (scanned separately), the contract
        # (authority). A new semantic-risk doc/schema/runner is still auto-covered by the prefix glob.
        import glob
        rel = lambda q: str(Path(q).relative_to(ROOT)).replace("\\", "/")
        skip = {"docs/a_short_semantic_risk_contract.md"} | set(cls.DESIGN_SURFACES)
        files = ["runners/weekly_screening.ps1", "runners/a_short_weekly_pipeline.py", "docs/README.md"]
        files += [rel(q) for q in glob.glob(str(ROOT / "docs" / "a_short_semantic_risk_*.md")) if rel(q) not in skip]
        files += [rel(q) for q in glob.glob(str(ROOT / "schemas" / "a_short_semantic_risk_*.schema.json"))]
        files += [rel(q) for q in glob.glob(str(ROOT / "runners" / "a_short_*semantic*.py"))]
        return sorted(set(files))
    DESIGN_SURFACES = ("docs/a_short_semantic_risk_top15_enrichment_design_20260612.md",)
    # BANNER tier: a transitional COMPONENT's own instruction file (every line is about the component, so a
    # per-line "point only" rule is nonsensical) is checked at FILE level — it must carry a supersession
    # banner (transitional marker + run-path pointer). Slice 3a retired the only such file (the 2b-ii skill
    # prompt), so BANNER_SUPERSEDED_SURFACES is empty; the mechanism + planted test stay for future prompts.
    BANNER_SUPERSEDED_SURFACES = ()   # Slice 3a retired the 2b-ii skill-patch prompt; none remain
    TRANSITIONAL_MARKERS = ("过渡", "transitional", "SUPERSEDED", "Slice 3")

    @classmethod
    def _separate_run_offenders(cls, text, pointer_exempts=False):
        # Shared by the live guard AND the planted tests. Two complementary per-line rules:
        #  (1) CURRENT_NARRATION: a route surface restating the current/transitional path is an offender
        #      even WITH a pointer (round-5 fix); pointer_exempts=True (DESIGN doc only) relaxes this.
        #  (2) retired-workflow roots: a SPECIFIC root (alone) OR a GENERIC root in a_short web_llm context,
        #      WITHOUT a retired/historical marker on the line = offender (teaches a deleted path as live).
        #      A correctly-labelled retired/superseded line (marker present) is allowed on any surface.
        out = []
        for ln in text.splitlines():
            low = ln.lower()
            if any(ph.lower() in low for ph in cls.CURRENT_NARRATION):
                if not (pointer_exempts and cls.SINGLE_SOURCE_POINTER in ln):
                    out.append(ln.strip()[:200])
                    continue
            hit = any(r in low for r in cls.SPECIFIC_ROOTS) or (
                any(r in low for r in cls.GENERIC_ROOTS) and any(c in low for c in cls.WEB_CONTEXT))
            if hit and not any(m in low for m in cls.RETIRED_MARKERS):
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
        # Slice 3a: schema descriptions must stay in the scanned strict set (anti-regression on the glob)
        self.assertIn("schemas/a_short_semantic_risk_summary.schema.json", self._strict_surfaces(),
                      "schema descriptions dropped from the strict drift-scan set")
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
        schema_desc_offender = ('"description": "web_llm = Sina/web advisory (skill-in-loop); the headless '
                                'builder leaves it for the 2b-ii-B skill prompt to fill"')  # Slice 3a schema-desc variant
        self.assertTrue(self._separate_run_offenders(schema_desc_offender),
                        "STRICT: a schema description re-narrating the retired skill-patch path must FAIL")
        # Slice 3a round-3 variants (Codex broad-scan residuals) must all FAIL — incl. lines with NO
        # same-line web context (caught by SPECIFIC compounds) and the space-form `web_llm patch`.
        for v in ("实质精判仍交 2b skill(web_llm)。",
                  "残余误差只会是误报(可被 skill 降级),绝不漏报",
                  "跨字段不变式(summary 与 web_llm patch 共用)",
                  "web/LLM 待 skill 评估。",
                  "stable contract anchors the boundary, evidence invariant, patch merge whitelist, and guard"):
            self.assertTrue(self._separate_run_offenders(v), f"STRICT: retired variant must FAIL: {v}")
        # cross-domain / code-review uses of generic skill/patch (no a_short web_llm context) are NOT offenders
        for ok in ("Semantic news can later become Skill prompt fragments.",       # another product's prompt
                   "Top15 enrichment DESIGN-only (Codex patch + revision notes).",  # a git patch, not web_llm_patch
                   "the analysis skill enriches llm_notes for regulatory checks"):  # general analysis skill
            self.assertEqual(self._separate_run_offenders(ok), [],
                             f"cross-domain generic skill/patch must NOT be flagged: {ok}")
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
