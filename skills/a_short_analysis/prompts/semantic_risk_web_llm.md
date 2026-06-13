# Semantic-Risk web/LLM Advisory — produce `a_short_semantic_risk_web_llm_patch`

Purpose: this is the **Slice 2b-ii web/LLM advisory layer** (skill-in-loop). For the main-board Top15
watch pool, do the LIVE web/LLM judgment that the headless `a_short_semantic_risk_summary` cannot, and
emit a single `a_short_semantic_risk_web_llm_patch` that the headless merger
(`runners/a_short_semantic_risk_summary.py::apply_web_llm_patch`) validates and merges into `web_llm`.

**Stable contract — read first, do not restate the matrix here**: `docs/a_short_semantic_risk_contract.md`
(single source). Coverage map: `docs/a_short_semantic_risk_coverage.md`.

## Inputs
- A built `a_short_semantic_risk_summary` (`as_of`, `universe.main_board_top15`, per-candidate
  `official_structured` events). Only judge the codes in `universe.main_board_top15`.
- Your LIVE web search + the per-category prompts in this folder, applied per candidate:
  `regulatory_48h.md`, `policy_news.md`, `industry_trend.md`, `hidden_risk.md`,
  `earnings_no_good_repair.md`, `cross_market_linkage.md`.

## What to produce
One JSON object validating against `schemas/a_short_semantic_risk_web_llm_patch.schema.json`:
`target` (as_of = the summary's; `summary_schema_name`/`summary_schema_version` matching), `source`
(`kind`, `prompt_refs` = the category prompts you used), and `candidates[]` — one entry per code you
actually judged (a partial patch is fine; unjudged codes keep `web_llm=unknown`).

Per candidate set `web_llm.{status, risk_level, action}` + `sources[]` (+ optional `confidence`,
`summary`). Map the category-prompt findings → `web_llm`:
- 媒体负面 / 监管 / 隐蔽风险 found → `status` `risk_candidate`/`risk` (or `headwind` for industry), with
  `risk_level` `low|medium|high` and `action` `observe`/`downgrade`/`manual_review_required`.
- 基本面行业景气向好 → `tailwind` (`risk_level` `none|low`).
- Checked, nothing material → `clear_light` (`risk_level none`).
- **Not searched / search failed / no evidence → `unknown` / `unknown` / `no_action`.**

## Hard rules (enforced by the merger; violating them makes the patch rejected)
- **Advisory only.** Never a hard veto or buy. `action` ∈ {no_action, observe, downgrade,
  manual_review_required}. The patch only writes `web_llm`/`sources`/`confidence`/`summary`; it can
  NEVER change `official_structured` / `boundary` / `rank` / `scan_tier` / `decision` / `veto` / scoring.
- **Unknown-not-clear.** No search / no evidence ⇒ `unknown/unknown/no_action`. Never present an
  unsearched candidate as `clear_light` or `tailwind`.
- **Evidence required for any non-`unknown` status.** `clear_light`, `risk_candidate`, `risk`,
  `tailwind`, `headwind` all MUST carry ≥1 `sources` entry (title/url/source_type; published_at/
  fetched_at if known). Only `unknown` may have empty `sources`.
- **LIVE-only, non-reproducible.** Web evidence is point-in-time; never claim it as historical-backtest
  evidence and never feed it into a backtest.
- **Main-board Top15 only.** Do not introduce codes outside `universe.main_board_top15`.
- **Semantic industry trend ≠ production `industry_heat`** (momentum). Keep them separate; never write
  back to production scoring.

## How it lands
1. **Merge (headless)**: `apply_web_llm_patch` validates the patch (schema + cross-field invariants +
   no-dup ts_code), writes ONLY `web_llm`/`sources`/`confidence`/`summary` into matched candidates, then
   re-runs `validate_summary_consistency` on the merged summary.
2. **Weekly visibility (headless)**: the built/merged `a_short_semantic_risk_summary` is consumed by
   `a_short_weekly_pipeline --semantic-risk-summary <summary.json>` → `_semantic_panel_from_summary`
   (the panel consumer gate) → `render_semantic_risk_panel` appended to the weekly M6.7 **markdown only**
   (never the deterministic weekly JSON). The consumer-gate steps are single-sourced in the
   `_semantic_panel_from_summary` docstring — not restated here.
