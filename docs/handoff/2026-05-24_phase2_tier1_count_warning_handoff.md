# Phase 2 Tier1 Count Warning Handoff

Date: 2026-05-24

## What Changed

Added machine-readable date-level sample health warnings to `backtest_report.json`.

Files changed:

- `runners/backtest_rank.py`
- `schemas/rank_backtest_report.schema.json`
- `AGENTS.md`
- `result/a_short/backtest/backtest_report.json`

The report schema is now `rank_backtest_report` v1.9.0.

New top-level report field:

```json
"date_warnings": [
  {
    "trade_date": "20240930",
    "warning_type": "low_tier1_count",
    "severity": "critical",
    "threshold": 5,
    "sample_count": 15,
    "tier1_count": 0,
    "tier2_count": 15,
    "message": "..."
  }
]
```

`low_tier1_count` is emitted when `tier1_count < 5`.
`tier1_count == 0` is marked `critical`; counts 1-4 are marked `warning`.

## Why

The v7.10 24-period production run showed that `20240930` had 0 Tier1 samples and all 15 selected names were Tier2 filler. This should be visible in the machine-readable report, not only in findings prose, because Tier1-only is the primary reporting subset and low Tier1-count dates can distort strategy interpretation.

## Validation Commands

Syntax check:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; files=['runners/backtest_rank.py']; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in files]; print('syntax ok')"
```

Result: `syntax ok`.

Schema meta-validation:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/rank_backtest_report.schema.json',encoding='utf-8')); Draft7Validator.check_schema(s); print('schema ok')"
```

Result: `schema ok`.

Stats-only regeneration and report validation:

```powershell
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\backtest_rank.py --mode production --stats-only --windows 5,10,20 --split-date 20250101
```

Result: success.

Key output:

```text
[OK] backtest_report.json validated against rank_backtest_report v1.9.0
```

## Validation Result Details

The regenerated report emitted 3 `date_warnings`:

| trade_date | severity | tier1_count | tier2_count |
|---|---:|---:|---:|
| 20240430 | warning | 3 | 12 |
| 20240930 | critical | 0 | 15 |
| 20241231 | warning | 3 | 12 |

No strategy scoring, candidate selection, forward return calculation, or findings conclusion was changed.

## Invalidated Old Conclusions

Old `rank_backtest_report` v1.8.0 outputs remain readable but are no longer the current contract because they do not include `date_warnings`.

The strategy conclusion boundary is unchanged:

- Phase 2 engineering chain: PASS.
- Strategy signoff: NOT PASS.
- Tier1-only remains the primary statistics口径.
- Tier2 filler remains observation only.

## Next Notes

Continue Phase 3 minimal analyzer/state work.

When reading future reports, check `date_warnings` before interpreting Tier1-only headline stats. Dates with `tier1_count < 5` should be called out explicitly in findings and portfolio-level interpretation.
