# Phase 2 Data Lineage Handoff

Date: 2026-05-24

## What Changed

Closed the Phase 2.6 lineage tail by adding a formal `data_lineage` object to `backtest_report.json`. Report schema bumped to `rank_backtest_report` v1.10.0.

Files changed:

- `schemas/rank_backtest_report.schema.json` (v1.9.0 → v1.10.0; `data_lineage` added to `required` + `properties`)
- `runners/backtest_rank.py` (writes `data_lineage` block; schema_version constant bumped)
- `result/a_short/backtest/backtest_report.json` (regenerated via `--stats-only`)
- `docs/CURRENT.md` (Phase 2.6 status flipped to 完成；§6 next-step list rewritten around Phase 3)
- `AGENTS.md` (handoff chain link)

## Why

Phase 2.6 design doc and AGENTS guardrail were already in place, but report lineage was only partially recorded — provider, API surface, benchmark identifiers, and PIT limitations were scattered across `settings`, `forward_daily`, and the free-text `limitations` array, or absent entirely. The 24p v7.10 review explicitly flagged this as the Phase 2.6 闭环 gap.

A future reader (LLM teammate, audit, or a Phase 7 DataHub refactor) now has one canonical place to identify what fed every number in the report.

## The data_lineage Object

```json
"data_lineage": {
  "data_provider": "tushare",
  "api_families": {
    "candidate_generation": [
      "daily", "daily_basic", "moneyflow", "fina_indicator",
      "stk_limit", "stock_basic", "trade_cal",
      "index_member_all", "index_member", "index_classify",
      "adj_factor", "concept", "concept_detail"
    ],
    "forward_evaluation": [
      "daily", "adj_factor", "stk_limit", "index_daily", "trade_cal"
    ]
  },
  "forward_return_adjustment_mode": "qfq_via_adj_factor",
  "benchmark_sources": {
    "csi300": "tushare:index_daily/000300.SH",
    "csi1000": "tushare:index_daily/000852.SH",
    "eligible": "internal:generated/_intermediate/egs_full_YYYYMMDD.csv Tier1+Tier2 equal-weight"
  },
  "pit_limitations": [
    "Tushare financials are filtered by ann_date<=as_of but returned values reflect latest revisions, not as-originally-disclosed (Tushare API limitation, not fixable here).",
    "L3 concept catalysts have no native as-of parameter; PIT support is via locally accumulated state/l3_snapshots/ snapshots (only effective once coverage is meaningful).",
    "SW industry membership applies in_date/out_date PIT filtering (B3a fix).",
    "Stock universe includes delisted stocks per as_of (B2 fix)."
  ]
}
```

Notes:

- `forward_return_adjustment_mode` is read from `forward_daily.adj` when available; otherwise defaults to `qfq_via_adj_factor`. Schema enum currently `qfq_via_adj_factor | none` matches `forward_daily.adj`.
- `pit_limitations` is a centralized, structured subset; the dynamic `l3_mode`-dependent note still lives in the top-level `limitations` array (it varies per run).
- This is additive metadata only. No production screening, candidate scoring, sample selection, or stats computation changed.

## Validation Commands

Syntax check:

```powershell
python -c "from pathlib import Path; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in ['runners/backtest_rank.py']]; print('syntax ok')"
```

Result: `syntax ok`.

Schema meta-validation:

```powershell
python -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/rank_backtest_report.schema.json',encoding='utf-8')); Draft7Validator.check_schema(s); print('schema meta-validation ok')"
```

Result: `schema meta-validation ok`.

Stats-only regeneration:

```powershell
python runners/backtest_rank.py --mode production --stats-only --windows 5,10,20 --split-date 20250101
```

Result: success, exit code 0.

Independent report-against-schema validation:

```powershell
python -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/rank_backtest_report.schema.json',encoding='utf-8')); r=json.load(open('result/a_short/backtest/backtest_report.json',encoding='utf-8')); errs=list(Draft7Validator(s).iter_errors(r)); print(f'errors: {len(errs)}'); print('schema_version:', r['schema_version'])"
```

Result: `errors: 0`, `schema_version: 1.10.0`.

## Invalidated Old Conclusions

- `rank_backtest_report` v1.9.0 outputs remain readable but no longer match the current contract (missing `data_lineage`).
- `CURRENT.md` claim that Phase 2.6 was "待启动" is invalid; Phase 2.6 is now complete.
- `CURRENT.md` schema-version references to `1.8.0` are invalid; current is `1.10.0`.

No strategy conclusion changes. Phase 2 strategy boundary unchanged: engineering signoff yes, strategy signoff no, Tier1-only is the primary subset.

## Next Notes

- Future schema changes that introduce a new data source (e.g., 美股扩展时引入 polygon/alpaca) must extend `data_provider` enum and add to `api_families`. Treat any new external API endpoint as a `data_lineage` change requiring schema version bump.
- Phase 3 analyzer/state work should be the next handoff. The Phase 2.6 work is now considered fully closed.
