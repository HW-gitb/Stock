# A-long Large-cap Batch Multi-factor Search — Design DRAFT (2026-06-08)

> **STATUS: DRAFT / non-authoritative archive.** This file records an agreed *design direction* discussed
> in chat so it survives `/clear`. It is **NOT a preregistration** and authorizes **nothing** — no data
> fetch, no signal-search run, no ledger spend, no production / ship-gate / full-size claim. The actual
> batch still requires a formal `起草` of a prereg + bespoke schema + a new singleton/batch ledger →
> Codex `审查` → Claude `提交` → a separate user `执行`. Before `起草`, run the field-verification
> checklist in §6. Live state of the program is in `docs/SESSION_LOG.md` top + `docs/CURRENT.md` §0.

## 1. Why a batch now

Five A-long large-cap **single-factor** lines are executed and closed (full-main-board `no_alpha`;
large-cap pure-quality `falsified`; `cash_conversion` statistical-alpha-clue but NOT tradeable;
`low_volatility` `falsified`; `ep_value` `falsified`). Sequential singletons control *within-factor*
p-hacking but do **not** correct *across-factor* family-wise error, and they burn one review/execute
round each. A single pre-registered **batch with Benjamini-Hochberg FDR** is the honest way to test a
diverse set of remaining hypotheses in one round.

**This is intended as the LAST structured batch / candidate-generation round** (see the stopping rule, §7).

## 2. What a batch does NOT do

It is not "more nets to catch more fish." Under BH-FDR, **more hypotheses raise the bar for every one**
(the k-th smallest p must be ≤ (k/m)·q). The batch's value is (a) one reviewed round instead of N
singletons, and (b) honest multiple-testing control — not higher yield.

## 3. Decision rule

- **FDR across the m PRIMARY cells only** (one pre-committed primary cell per factor). Diagnostics
  (252d, CSI1000, cap-weight, single-factor views) are reporting-only and **cannot rescue** a primary.
- **q = 0.10** as the *research-clue* gate (candidate generation), **and report q = 0.05** as a stricter
  diagnostic. Either threshold is pre-committed before the run.
- Anything that passes is **research-only → routes to forward-live**, never production / ship-gate /
  full-size. The unchanged ship gate still needs ≥ 12 months of forward-live evidence.

## 4. Factor count

**8–10 primary factors + 1 composite** (the composite counts as the m+1-th hypothesis). Not 12–15 —
that just dilutes the FDR threshold and adds redundancy on a small sample. Pick diverse, low-redundancy
representatives (1–3 per family).

## 5. Frozen primary list (9 primary + 1 composite)

All denominators are **circ_mv (free-float market cap)** — name factors `*_to_circ_mv` and do NOT
mislabel them as canonical book-to-market / EV / total-market-cap ratios.

| # | factor id | family | definition (as applied) |
|---|---|---|---|
| 1 | `book_to_circ_mv` | value | PIT book equity (`total_hldr_eqy_exc_min_int`) / circ_mv |
| 2 | `cash_flow_to_circ_mv` | value | TTM operating cash flow (`n_cashflow_act`) / circ_mv |
| 3 | `sales_to_circ_mv` | value | TTM revenue / circ_mv — **needs field check (see §6)** |
| 4 | `low_accruals` | earnings quality | −(TTM net income − TTM CFO) / average total assets (Sloan) |
| 5 | `low_asset_growth` | investment | −YoY growth in total assets (FF5 CMA direction) |
| 6 | `roa_ttm` | profitability **proxy** | TTM net income / total assets — **explicitly a ROA proxy, NOT Novy-Marx gross or FF5 operating profitability** (those fields aren't materialized); **lowest-novelty slot** (overlaps the already-falsified ROE-quality line) — kept only because no purer profitability measure is computable |
| 7 | `low_beta` | low-risk | −market beta vs CSI300 from daily returns (BAB direction); distinct from the falsified total-vol `low_volatility` but correlated with it |
| 8 | `low_MAX` | low-risk / lottery | −max daily return over the trailing month (Bali MAX); China lottery effect is mostly small-cap, so expect weak in large-cap |
| 9 | `momentum_12_1` | momentum | cumulative return t−12..t−1; **China large-cap momentum is documented weak / reversal-prone — expected to falsify, included to put the question to rest** |
| 10 | `family_balanced_composite` | composite (m+1) | equal-weight-by-FAMILY z-score blend (value / quality / investment / risk / momentum each as one family bucket, so the 3 value variants don't dominate); **weights frozen in the prereg, no weight search** |

### Dropped from the earlier (looser) proposal — data not available "no new fetch"
- **EBIT/EV** — no EBIT / enterprise-value lineage in the materialized panel.
- **gross profitability (Novy-Marx) / operating profitability (FF5)** — no gross-profit / COGS /
  operating-profit fields materialized. Use `roa_ttm` as the honest proxy instead (do not硬write the
  literature definitions).
- **dividend yield (DP)** — exclude until dividend + share-count PIT lineage is proven computable.

## 6. Fields-to-verify BEFORE freezing the prereg

Do not repeat the EBIT/EV mistake (listing a factor whose inputs aren't materialized). Confirm each
input exists in the already-materialized full-main-board PIT panel before the factor enters the frozen
list.

- **Confirmed used by `base.compute_signal_values` (present):** `income.n_income_attr_p`,
  `cashflow.n_cashflow_act`, `balancesheet.total_hldr_eqy_exc_min_int`, `balancesheet.total_assets`,
  `balancesheet.total_liab`, `income.profit_dedt`, `fina_indicator.roe`; daily `close` + `adj_factor`;
  index closes (CSI300 / CSI1000). → covers factors 1, 2, 4, 5, 6, 7, 8, 9.
- **MUST verify before freeze:** `income` revenue field (`revenue` / `total_revenue`) for
  `sales_to_circ_mv` — base does not currently read it, so confirm it was materialized.
- **Do NOT include until lineage proven:** EBIT/EV, gross/operating profit, dividends.

## 7. Frozen design reuse (same as the 5 prior lines)

Top-500 PIT circ_mv main-board universe; reviewed `000043.SZ` / `20191129` exclusion + circ_mv
backfill; marginal 0.5 industry + 0.5 size neutralization (SW L2 → L1 fallback; circ_mv quintiles, min
50/bucket); 504d / CSI300 primary + 252d / CSI1000 diagnostics; next-trading-day-close entry;
Newey-West HAC-t on overlapping monthly cohorts; `round_trip_cost = 0.0026`; median sub-period split;
non-positive-denominator / insufficient-history exclusion with reported counts; rolling-overlapping
relative-NAV drawdown ≥ −15% as the *tradeable-candidate* gate (does not gate the statistical clue).

## 8. Multiple-testing caveats (must stay in the prereg)

- Batch FDR controls within-batch family-wise error but **cannot uncount the 5 already-spent
  singletons**; any survivor is, program-level, the (5+k)-th test.
- In-sample (solo or batch) is **candidate generation only**; the 12-month forward-live ship gate is the
  real test.
- Honest power expectation: at m ≈ 10, q = 0.10 BH needs the best p ≤ ~0.01 (t ≳ 2.6); the prior
  marginal factors were t ≈ 2.2 (p ≈ 0.03) and would **not** survive. So the most likely outcome is a
  rigorous "**no robust clue**" — which is itself the decision point below, not a failure of the method.

## 9. Stopping rule (the point of making this the last structured batch)

If this batch yields **no robust clue** (no factor surviving FDR with stable sub-periods + concentration
guards), then **downgrade A-share large-cap long in-sample alpha**: pivot to forward-live validation or a
different market / data path — **do NOT continue rescuing with new factor definitions**. Continuing to
hunt definitions after a properly-powered diverse batch comes up dry is exactly the p-hacking this whole
discipline exists to prevent.

## 10. Next steps (when ready)

1. Run the §6 field-verification (esp. `revenue`).
2. `起草` the batch prereg + bespoke all-`const` schema + a new singleton/batch ledger (frozen factor
   list, FDR rule, q, stopping rule, caveats above).
3. Codex `审查` → Claude `提交` → separate user `执行` (spends the batch ledger once).
