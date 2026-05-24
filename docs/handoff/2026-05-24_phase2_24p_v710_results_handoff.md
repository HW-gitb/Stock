# Phase 2 24p v7.10 Results Handoff

Date: 2026-05-24

## What Changed In This Handoff

This handoff records the first completed 24-period production run after the v7.10 validation-tooling changes.

No code was changed in this handoff. The material update is the new production output and findings file:

- `result/a_short/backtest/backtest_report.json`
- `result/a_short/backtest/Phase2_rank_backtest_findings_codex_24p_v7.10.md`

## Command Run

```powershell
python runners\backtest_rank.py --mode production --periods 24 --freq monthly --end-date 20260301 --split-date 20250101 --refresh-forward-daily
```

Result: success, exit code 0.

## Validation Results

- Report schema: `rank_backtest_report` v1.8.0, validation passed with 0 errors.
- Selected dates: 24 monthly dates from `20240131` to `20251231`.
- Samples: 360, exactly 15 candidates per selected date.
- Candidate pools used in `selected_dates`: all are `analysis_input.schema_version=1.1.0`, `screening_engine_version=v7.10`, `l3_mode=neutralize`.
- Forward data: `stock_rows=2,681,523`, `stock_codes=5,564`, `limit_rows=3,513,895`.
- T+1 no-entry simulation: 11 / 360 samples marked `pending_no_entry_limit_up`, all from `stk_limit`.
- Old generated dirs `20260515` and `20260522` still exist but were not selected and were not used.

## Main Findings

Primary subset is `tier1_only`.

- 5d Tier1 `t1_net`: +0.63%, monthly_t=0.91.
- 5d Tier1 `excess_csi1000`: +1.04%, monthly_t=2.88. This is the clearest short-window excess signal.
- 20d Tier1 `t1_net`: +2.84%, monthly_t=1.60.
- 20d Tier1 `excess_csi300`: +0.63%, monthly_t=0.57.
- 20d Tier1 `excess_csi1000`: +0.31%, monthly_t=0.17.
- 20d Tier1 `excess_eligible`: +0.94%, monthly_t=0.82.

Interpretation boundary:

- Phase 2 engineering chain: PASS.
- Strategy signoff: NOT PASS. Results do not justify deployment claims.
- The run supports continued development and Phase 3, not real-money confidence.

## Strategy Variant Notes

- `esp_raw > 200` group was weak: 29 samples, 20d `t1_net=-1.66%`, monthly_t=-1.07.
- `esp_raw <= 200` group was better: 276 samples, 20d `t1_net=+3.31%`, monthly_t=1.66.
- This supports keeping v7.10 low-base cap / penalty.
- `esp_cap_200_rerank` did not improve baseline materially.
- `no_chase`, `no_overheat`, and `no_lock` had no effect inside Tier1 because those flags were absent from Tier1 in this run.

## Important Diagnostics

- Rank monotonicity is not proven:
  - Top 1-5: 20d `t1_net=+2.79%`, monthly_t=1.61.
  - Top 11-15: 20d `t1_net=+4.23%`, monthly_t=2.09.
- `20240930` had 0 Tier1 samples; all 15 were Tier2 filler, and 10 of those were T+1 limit-up unbuyable.
- Portfolio Tier1 20d `t1_net`:
  - period_count=23
  - mean period return=+2.36%
  - compounded return=+62.55%
  - max drawdown=-18.75%
  - period win rate=47.8%
  - monthly_t=1.60

## Next Recommended Work

1. Add a date-level Tier1-count warning to the report, especially for `Tier1_count < 5`.
2. Keep Tier1-only as the main statistics口径; treat Tier2 filler as observation only.
3. Accumulate PIT L3 snapshots and later rerun with `--l3-mode pit --l3-pit-strict`.
4. Start Phase 3 minimal analyzer/state interface, but preserve the conclusion boundary: engineering signoff only, no strategy signoff yet.
