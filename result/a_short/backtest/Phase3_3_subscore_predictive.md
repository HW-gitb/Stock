# Phase 3.3 Sub-Score Predictive Analysis (BACKTEST scope)

- Source: `D:/cnhea/Stock/result/a_short/backtest/rank_samples.csv` (Tier1 only)
- Split date: `20250101` (discovery < split, validation >=)
- Bins respect 24p sub-score clumping: esp_score 58% at default 50, l4_score 75% at 100.
- Question: in BACKTEST mode (`--l3-mode neutralize`), does any sub-score predict forward 5d / 10d / 20d returns better than final_score?

**SCOPE WARNING — cat_score is excluded for a data-path reason, not a model reason.**

Backtest production runs default to `--l3-mode neutralize`, which hard-codes
`cat_score = 50.0` for all candidates (egs_main.py:2202). Live weekly runs
default to `--l3-mode today` where Tushare L3 API gives real cat_score in
12-100. So:
- This analysis reflects `final_score ≈ 0.20*esp + 0.50*l4 + 15` (backtest);
  live `final_score = 0.20*esp + 0.30*cat + 0.50*l4` may behave differently.
- cat_score's predictive power can only be tested once L3 PIT snapshots
  accumulate enough history (target ~2026-12); re-run with `--l3-mode pit` then.
- esp_score and l4_score findings here are valid for backtest mode; live
  behavior may diverge if cat_score modulates the effect.

## Monotonicity (Spearman bin-rank vs mean return; positive = higher score → higher return)

| score | window | all | discovery | validation |
| --- | --- | --- | --- | --- |
| final_score | 5 | 0.5000 | 0.6000 | 0.5000 |
| final_score | 10 | 0.5000 | -0.1000 | 0.7000 |
| final_score | 20 | 0.4000 | -0.3000 | 0.7000 |
| esp_score | 5 | -1.0000 | -1.0000 | -1.0000 |
| esp_score | 10 | 0.5000 | 0.5000 | -1.0000 |
| esp_score | 20 | -0.5000 | -0.5000 | -1.0000 |
| l4_score | 5 | 0.5000 | -1.0000 | 1.0000 |
| l4_score | 10 | 0.5000 | -0.5000 | 1.0000 |
| l4_score | 20 | 0.5000 | 0.5000 | 0.5000 |

Interpretation guide:
- |rho| > 0.7 and same sign across discovery + validation: real monotonic predictor.
- rho flips sign between splits: regime-dependent, not stable.
- |rho| < 0.3 in both splits: no usable signal.

## Per-bin detail

| score | group | period_split | sample_count_5d | mean_return_pct_5d | monthly_t_5d | win_rate_pct_5d | sample_count_10d | mean_return_pct_10d | monthly_t_10d | win_rate_pct_10d | sample_count_20d | mean_return_pct_20d | monthly_t_20d | win_rate_pct_20d |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| final_score | lt_60 | all | 70 | -0.8571 | -0.3209 | 35.7143 | 70 | 0.0440 | 0.1288 | 40.0000 | 70 | -1.4410 | 0.0918 | 35.7143 |
| final_score | lt_60 | discovery | 45 | -0.6557 | -0.0641 | 37.7778 | 45 | 1.8193 | 0.6604 | 48.8889 | 45 | 0.2970 | 0.6001 | 37.7778 |
| final_score | lt_60 | validation | 25 | -1.2196 | -1.1223 | 32.0000 | 25 | -3.1516 | -1.2358 | 24.0000 | 25 | -4.5693 | -3.8186 | 32.0000 |
| final_score | 60_70 | all | 41 | 0.8259 | 0.2963 | 51.2195 | 41 | 1.9752 | 0.3083 | 53.6585 | 41 | 6.5080 | 1.0125 | 63.4146 |
| final_score | 60_70 | discovery | 15 | -0.8047 | 0.1978 | 33.3333 | 15 | -1.5281 | -0.3151 | 33.3333 | 15 | 5.8844 | 0.6141 | 53.3333 |
| final_score | 60_70 | validation | 26 | 1.7666 | 0.2181 | 61.5385 | 26 | 3.9964 | 0.6448 | 65.3846 | 26 | 6.8677 | 0.7673 | 69.2308 |
| final_score | 70_75 | all | 28 | 2.3044 | 1.1320 | 64.2857 | 28 | -2.4043 | -1.6189 | 46.4286 | 28 | 1.2078 | -0.3308 | 50.0000 |
| final_score | 70_75 | discovery | 12 | 1.0993 | 0.4039 | 58.3333 | 12 | -6.5410 | -1.5844 | 33.3333 | 12 | 0.9979 | 0.1170 | 50.0000 |
| final_score | 70_75 | validation | 16 | 3.2083 | 1.0330 | 68.7500 | 16 | 0.6983 | -0.7067 | 56.2500 | 16 | 1.3651 | -0.6070 | 50.0000 |
| final_score | 75_80 | all | 133 | 0.6121 | 0.3922 | 53.3835 | 133 | 1.2936 | 0.3432 | 60.1504 | 133 | 3.7441 | 1.0854 | 53.3835 |
| final_score | 75_80 | discovery | 52 | -0.5233 | 0.3451 | 48.0769 | 52 | 0.0842 | 0.0491 | 55.7692 | 52 | 4.4465 | 0.5943 | 51.9231 |
| final_score | 75_80 | validation | 81 | 1.3409 | 0.2003 | 56.7901 | 81 | 2.0701 | 0.4863 | 62.9630 | 81 | 3.2931 | 0.9210 | 54.3210 |
| final_score | ge_80 | all | 33 | 2.1806 | 1.2465 | 69.6970 | 33 | 3.3363 | 1.2942 | 66.6667 | 33 | 5.0910 | 1.4382 | 60.6061 |
| final_score | ge_80 | discovery | 7 | 0.7049 | 0.8029 | 57.1429 | 7 | 0.7585 | 0.7251 | 71.4286 | 7 | -2.7052 | -1.6383 | 28.5714 |
| final_score | ge_80 | validation | 26 | 2.5779 | 0.9871 | 73.0769 | 26 | 4.0303 | 1.1096 | 65.3846 | 26 | 7.1899 | 1.9726 | 69.2308 |
| esp_score | low_lt_50 | all | 55 | 1.2157 | 1.5300 | 54.5455 | 55 | -0.0926 | 0.2956 | 54.5455 | 55 | 2.9122 | 1.4114 | 52.7273 |
| esp_score | low_lt_50 | discovery | 29 | 0.2484 | 0.5178 | 41.3793 | 29 | -2.5556 | -0.2592 | 44.8276 | 29 | 1.9020 | 0.8405 | 48.2759 |
| esp_score | low_lt_50 | validation | 26 | 2.2948 | 2.1703 | 69.2308 | 26 | 2.6547 | 0.8629 | 65.3846 | 26 | 4.0389 | 1.0849 | 57.6923 |
| esp_score | neutral_50 | all | 177 | 0.9890 | 0.5945 | 52.5424 | 177 | 1.4880 | 0.8371 | 56.4972 | 177 | 3.5494 | 2.1231 | 51.9774 |
| esp_score | neutral_50 | discovery | 75 | -0.0504 | 0.0656 | 46.6667 | 75 | 0.7032 | -0.0900 | 53.3333 | 75 | 3.0027 | 0.7103 | 48.0000 |
| esp_score | neutral_50 | validation | 102 | 1.7534 | 0.7066 | 56.8627 | 102 | 2.0651 | 1.5228 | 58.8235 | 102 | 3.9514 | 3.1556 | 54.9020 |
| esp_score | high_gt_50 | all | 73 | -0.6873 | -0.3176 | 47.9452 | 73 | 0.5563 | 0.3043 | 47.9452 | 73 | 1.0592 | 0.1271 | 47.9452 |
| esp_score | high_gt_50 | discovery | 27 | -2.0030 | -2.0452 | 40.7407 | 27 | 0.4267 | 0.2231 | 44.4444 | 27 | 1.6861 | 0.0307 | 37.0370 |
| esp_score | high_gt_50 | validation | 46 | 0.0850 | 0.2437 | 52.1739 | 46 | 0.6325 | 0.1926 | 50.0000 | 46 | 0.6913 | 0.1464 | 54.3478 |
| l4_score | lt_70 | all | 43 | 0.1907 | -0.4335 | 44.1860 | 43 | -0.3759 | -0.4258 | 39.5349 | 43 | -1.6365 | -0.1136 | 32.5581 |
| l4_score | lt_70 | discovery | 22 | 2.3975 | -0.0752 | 50.0000 | 22 | 2.6934 | -0.0214 | 54.5455 | 22 | 1.3218 | 0.2279 | 31.8182 |
| l4_score | lt_70 | validation | 21 | -2.1212 | -1.3633 | 38.0952 | 21 | -3.5914 | -0.7597 | 23.8095 | 21 | -4.7357 | -1.3898 | 33.3333 |
| l4_score | 70_99 | all | 33 | -1.0000 | -1.0420 | 48.4848 | 33 | 1.5237 | 0.5527 | 54.5455 | 33 | 4.5760 | 0.9237 | 60.6061 |
| l4_score | 70_99 | discovery | 11 | -0.7575 | -1.1371 | 45.4545 | 11 | 3.0736 | 0.3282 | 63.6364 | 11 | 4.6743 | 0.0721 | 63.6364 |
| l4_score | 70_99 | validation | 22 | -1.1213 | -0.5745 | 50.0000 | 22 | 0.7488 | 0.5032 | 50.0000 | 22 | 4.5268 | 1.4841 | 59.0909 |
| l4_score | eq_100 | all | 229 | 0.9457 | 1.3244 | 53.7118 | 229 | 1.1562 | 1.1556 | 56.7686 | 229 | 3.4284 | 1.7888 | 53.2751 |
| l4_score | eq_100 | discovery | 98 | -0.9701 | 0.3530 | 42.8571 | 98 | -1.0502 | 0.2323 | 46.9388 | 98 | 2.5040 | 0.6742 | 46.9388 |
| l4_score | eq_100 | validation | 131 | 2.3788 | 1.6150 | 61.8321 | 131 | 2.8068 | 1.7471 | 64.1221 | 131 | 4.1199 | 2.0477 | 58.0153 |

## Interpretation Boundary

- This is exploratory on Tier1 only (N=305, 24p, BACKTEST mode under l3_mode=neutralize). Sub-scores that look strong here may still be regime artifacts.
- Do not promote a sub-score to a strategy variant unless monotonicity holds in both discovery + validation and at least 3 bins have N>=20.
- cat_score is excluded because backtest runs hard-code it to 50 (l3_mode=neutralize). This is NOT evidence that the EGS catalyst signal lacks power — it cannot be tested here.
- Live `--l3-mode today` cat_score behavior is unobserved in this analysis; do not assume final_score under neutralize behaves the same as live.