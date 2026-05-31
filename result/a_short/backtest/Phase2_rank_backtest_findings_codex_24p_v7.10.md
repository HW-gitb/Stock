# Phase 2 Rank Backtest Findings - Codex 24p v7.10

> **Measurement caveat (2026-05-31)**: All benchmark excess fields in this findings document (`excess_csi1000`, `excess_csi300`, and `excess_eligible`, across all horizons) are now treated as measurement-contaminated / uncorrected until same-anchor benchmark excess is re-run. The known issue is stock T+1 open entry semantics mixed with benchmark close-basis returns. Keep `t1_net` diagnostics, but do not use any excess line here as validated alpha, research-continuation evidence, or promotion evidence before corrected-basis revalidation.

Run time: 2026-05-24 11:26 CST

Command:

```powershell
python runners\backtest_rank.py --mode production --periods 24 --freq monthly --end-date 20260301 --split-date 20250101 --refresh-forward-daily
```

## 1. Engineering Validation

Conclusion: PASS for Phase 2 engineering validation.

- Report schema: `rank_backtest_report` v1.8.0, JSON Schema validation passed with 0 errors.
- Selected dates: 24 monthly as-of dates from `20240131` to `20251231`.
- Samples: 360 rows, exactly 15 candidates per selected date.
- Candidate pool versions: all selected pools are `analysis_input.schema_version=1.1.0`, `screening_engine_version=v7.10`, `l3_mode=neutralize`.
- Forward data: `stock_rows=2,681,523`, `stock_codes=5,564`, `limit_rows=3,513,895`.
- New outputs were written: `eligible_benchmark.csv`, `strategy_variant_stats.csv`, `strategy_variant_monthly.csv`, `portfolio_period_returns.csv`, `portfolio_stats.csv`.
- T+1 no-entry simulation is active: 11 / 360 samples were marked `pending_no_entry_limit_up`, all from `stk_limit`.

Note: old generated folders `20260515` and `20260522` still exist under `result/a_short/backtest/generated/`, but they are not in `selected_dates` and were not used.

## 2. Primary Result

Primary subset remains `tier1_only`, because Tier2 filler still dilutes results.

Tier1-only summary:

| Window | Variant | Mean | Median | Win Rate | Monthly t |
|---|---:|---:|---:|---:|---:|
| 5d | t1_net | +0.63% | +0.35% | 51.8% | 0.91 |
| 5d | excess_csi300 | +0.73% | -0.22% | 47.9% | 1.39 |
| 5d | excess_csi1000 | +1.04% | +0.63% | 55.4% | 2.88 |
| 10d | t1_net | +0.98% | +0.67% | 54.1% | 1.04 |
| 20d | t1_net | +2.84% | +0.32% | 51.1% | 1.60 |
| 20d | excess_csi300 | +0.63% | -1.12% | 43.6% | 0.57 |
| 20d | excess_csi1000 | +0.31% | -1.14% | 43.0% | 0.17 |
| 20d | excess_eligible | +0.94% | -0.96% | 46.2% | 0.82 |

Interpretation:

- The absolute 20d return is positive, but benchmark excess is weak.
- The clearest alpha-like signal in this run is 5d versus CSI1000, not 20d.
- Phase 2 supports engineering signoff, not strategy signoff.

## 3. Time Split

20d Tier1-only:

| Period | t1_net | excess_csi300 | excess_csi1000 | excess_eligible |
|---|---:|---:|---:|---:|
| Discovery, 2024 | +2.49%, t=0.71 | -0.90%, t=-0.43 | -0.43%, t=-0.25 | +1.21%, t=0.61 |
| Validation, 2025 | +3.10%, t=1.77 | +1.78%, t=1.55 | +0.87%, t=0.80 | +0.73%, t=0.52 |

This does not show obvious in-sample-only overfit. Validation is better than discovery on absolute and CSI300 excess. But the t-stat is still not high enough to claim robust strategy alpha.

## 4. Strategy Variant Findings

20d Tier1-only `t1_net`:

| Variant | Samples | Mean | Win Rate | Monthly t |
|---|---:|---:|---:|---:|
| no_low_base | 259 | +3.02% | 49.8% | 1.54 |
| combined_p0 | 259 | +3.02% | 49.8% | 1.54 |
| baseline | 305 | +2.84% | 51.1% | 1.60 |
| esp_cap_200_rerank | 302 | +2.81% | 50.7% | 1.57 |

Related factor slice:

- `esp_raw > 200`: 29 samples, 20d `t1_net=-1.66%`, monthly t=-1.07.
- `esp_raw <= 200`: 276 samples, 20d `t1_net=+3.31%`, monthly t=1.66.

Decision:

- Low-base growth filtering / penalty is supported directionally.
- The current `esp_raw` cap is reasonable.
- Reranking only by ESP cap did not improve results; the stronger effect is exclusion/penalty of extreme low-base names, not simple reranking.
- `no_chase`, `no_overheat`, and `no_lock` had no effect inside Tier1 in this v7.10 neutralized run because those flags were absent from Tier1. Do not treat them as validated.

## 5. Cross-Sectional Diagnosis

Rank bucket, 20d Tier1-only `t1_net`:

| Bucket | Samples | Mean | Win Rate | Monthly t |
|---|---:|---:|---:|---:|
| Top 1-5 | 111 | +2.79% | 48.6% | 1.61 |
| Top 6-10 | 102 | +1.64% | 47.1% | 0.94 |
| Top 11-15 | 92 | +4.23% | 58.7% | 2.09 |

Rank monotonicity is not proven. Top 11-15 outperformed Top 1-5 in this run. Top 5 can remain the human-analysis workload subset, but the score ranking itself needs more evidence before it is treated as a strong ordering signal.

Entry flag:

- `可直接观察`: 301 samples, 20d `t1_net=+2.91%`, monthly t=1.68.
- `资金流背离`: 4 samples, 20d `t1_net=-2.65%`, too few samples but directionally negative.

## 6. Time Stability And Portfolio View

Worst / best Tier1-only monthly 20d periods:

- Worst: `20240731` -8.25%, `20251031` -5.66%, `20240430` -4.44%.
- Best: `20240830` +22.31%, `20250731` +9.96%, `20241031` +9.09%.

Portfolio-level Tier1-only 20d `t1_net`:

- Period count: 23, because `20240930` had 0 Tier1 samples.
- Mean period return: +2.36%.
- Compounded return over the sampled path: +62.55%.
- Max drawdown: -18.75%.
- Period win rate: 47.8%.
- Monthly t: 1.60.

Interpretation:

- The path is positive but volatile.
- One very strong month contributes materially.
- This is still not enough for deployment-level confidence.

## 7. Limitations

- L3 was neutralized. This avoids look-ahead bias but removes the concept/catalyst layer from the test.
- Stage3 cninfo/news/DeepSeek checks are skipped in backtest mode.
- This is still rank backtest only. Execution backtest has not yet modeled stop-loss, time stop, circuit breaker, position limits, or cooldown.
- Tushare financial data is filtered by `ann_date <= as_of`, but revised historical financial rows may still reflect latest revisions.

## 8. Next Actions

1. Keep v7.10 engineering path as the current Phase 2 baseline.
2. Keep low-base growth penalty/cap; do not promote a stronger rule until it survives more periods or PIT-L3 reruns.
3. Treat Tier1-only as the main statistical口径; Tier2 filler remains observation / liquidity-of-output support, not strategy evidence.
4. Add a report warning for dates with very low Tier1 count, especially `Tier1_count < 5`.
5. Accumulate real PIT L3 snapshots and rerun a PIT-mode backtest once coverage is meaningful.
6. Move to Phase 3 minimal analyzer/state interface only after documenting that Phase 2 is engineering-signoff, not strategy-signoff.
