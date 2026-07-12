# US-short Ship-Gate Protocol v1.0 (PROPOSED — not active)

> **Status**: `proposed`. **NOT active. The 12-month evidence clock has NOT started.** This is a pre-registration
> draft for review. It becomes binding only after the activation preconditions (§0) are met and it is explicitly
> frozen (hash + timestamp recorded, `status: active`). Until then it moves no money and gates nothing.
>
> **Scope**: US-short (short-holding-period, long-only / buy-side; never short-selling). Instantiates the cross-lane
> `docs/evidence_capital_policy.md` and design `docs/us_short_system_design.md` §12/§13 with concrete US-short numbers.
> Machine-readable twin: `presets/us_short_ship_gate_protocol_v1.0.json`.
>
> **Freeze discipline**: once active, this file is append-only. Any change to a threshold or rule = a new version
> (`v1.1`, …) + the evidence clock restarts. The bar is never moved on already-observed data.

Purpose: define — **before the first real trade** — how the US-short strategy earns the right to scale from
paper/minimal-size to full real-money size, in a way whose false-graduation rate is calibrated and which cannot be
gamed after seeing results. "Correct" here means *error-controlled, economically meaningful, and non-manipulable* —
never "guaranteed to make money" (unprovable before real data).

---

## §0. Activation preconditions (clock starts only when ALL are true)

1. **User approval** of this protocol, including the ⟨USER⟩ risk fields in §2.
2. **Strategy version locked**: the `balanced` selection engine + 40/35/25 weights are frozen — i.e. 0c94 (theme
   lifecycle → Top15) is merged-or-explicitly-excluded and the A1 forward-policy decisions are settled. You cannot
   start the clock on a moving selection target.
3. **All four pre-freeze validations (§11) PASS** — especially the zero-alpha calibration (≤5% false graduation).
4. **Freeze recorded**: `frozen_at` (UTC timestamp) + `frozen_sha256` of the machine-readable twin are written and
   `status` set to `active`.

Freeze the *methodology* now (everything below is fixed); start the *clock* only when 0–4 hold.

---

## §1. What is frozen now vs computed later

**Frozen now** (this document + the JSON twin): strategy version identity; target-capital definition; benchmarks;
NAV / cost / alpha / Sharpe / drawdown formulas; skip / re-price / early-exit / unfilled handling (ITT, §9);
minimum sample and effective-independence rules; formal-check dates + multiple-testing correction; capacity /
liquidity / stress-exit formulas; version-reset list; PASS / FAIL / insufficient-evidence actions; the research
trial log (every `balanced` config ever compared, incl. failed ones).

**Computed later, but whose METHOD + upper bound is frozen now** (never a fabricated pre-answer): realized
slippage/spread distributions; full-size market-impact estimate; effective independent sample count `n_eff`;
realized alpha/Sharpe/drawdown; whether an adverse market regime occurred; final capacity ceiling; each gate's
PASS/FAIL/insufficient verdict.

---

## §2. Target capital and risk budget ⟨USER — must be set before activation⟩

- `target_capital C*` = the specific dollar amount that "full size" means for the US-short bucket. **⟨USER_TO_SET⟩**
  — a concrete number (e.g. "≤ $X in this bucket"), written to a **gitignored/local** file, never into this tracked
  doc or the JSON twin (account/fund figures must not be committed).
- `max_drawdown_tolerance` = the real drawdown you can accept on `C*`. **= 15% (user-confirmed 2026-07-12).** Must
  correspond to a dollar loss you accept today (`C* × 15%`).
- `min_economic_alpha` = minimum net annualized alpha to justify complexity vs passive. **= 5% net annualized
  (user-set 2026-07-12, raised from the 3% default).**

These are risk-preference decisions, frozen a-priori, never revised because results look close.

---

## §3. Evidence framework (maps to `evidence_capital_policy.md`)

- `evidence_level ∈ {paper, live_normalized}`. **`paper` can NEVER graduate full size** (design §12; policy §2/§4).
- Only `live_normalized` (real minimal-size forward fills + reconciliation, normalized to `C*` basis) counts.
- **Two ledgers (intention-to-treat)**:
  - **Strategy-measurement ledger** — only protocol-compliant minimal-size fills; the sole graduation evidence.
    A skipped recommendation stays in the denominator as cash; it cannot disappear. A non-compliant week is marked
    non-compliant and lowers coverage — a paper/counterfactual fill may NOT substitute for it.
  - **Operator ledger** — discretionary skips / re-prices / early exits / extra non-recommended buys. Evaluates the
    *operator*, never improves the *strategy's* graduation record.
- `scaling_mode ∈ {linear, capped, not_valid, not_assessed}` per policy §3; `not_assessed` is never a pass.

---

## §4. Graduation = statistical bar × capital ramp (stringency rises with money at risk)

Statistical proof of full-size alpha is often infeasible in a few years (see §10 power note). So evidence is
**graduated**: a weak-but-positive bar authorizes a small ramp step; the full bar is reserved for full size. The
end-to-end false-graduation rate (reaching 100% `C*`) is calibrated to ≤5% (§11.2).

| Rung | Trigger (accumulated `live_normalized`) | Alpha / statistics (weekly HAC, one-sided) | Risk / environment / capacity |
|---|---|---|---|
| Minimal measurement | day 1 | none (accumulate) | coverage ≥ 98%, monthly compliance ≥ 95% (ITT) |
| **25% `C*`** | ≥ 12 months **and** `n_eff` ≥ 52 | net economic alpha point est. > 0; `t ≥ 1.0`; **factor-adjusted alpha ≥ 0** | lifetime max DD ≤ tolerance; realized cost within frozen model; `scaling_mode ≠ not_valid` |
| **50% `C*`** | + ≥ 8 weeks | net alpha ≥ ~2.5%; `t ≥ 1.5` | **a *sustained* adverse regime must have occurred (benchmark ≥ 10% peak-to-trough that stayed below the prior peak ≥ 20 trading days / did not recover within 4 weeks — a flash dip-and-recover does NOT count) — else capped here until it does** |
| **75% `C*`** | + ≥ 8 weeks | net alpha ≥ ~3.75%; `t ≥ 2.0` | capacity **stress-exit** test passes (§8) |
| **100% (full)** | + ≥ 8 weeks; typically 24–36 months total | net economic alpha ≥ **`min_economic_alpha`**; `t ≥ 2.0`; **Deflated Sharpe P(true>0.5) ≥ 95%**; both-halves alpha > 0; cumulative net > VTI + cash | full-size capacity validated; adverse regime confirmed; independent recompute matches |

Any rung's cost / capacity / risk-limit / compliance breach → drop one rung + accrue ≥ 8 more weeks. **The
graduation lines are never edited to fix a failure.**

---

## §5. The five gates (all `live_normalized`, `C*` basis, net of cost)

1. **Economic alpha** — primary benchmark = target-exposure-matched VTI total return + 3M T-bill on the cash sleeve
   (§6). Full size requires **net alpha ≥ `min_economic_alpha` AND factor-adjusted alpha ≥ 0** (so a positive-vs-VTI,
   negative-vs-momentum result is only "momentum exposure", not selection alpha).
2. **Statistical** — weekly HAC/Newey–West one-sided + weekly-block bootstrap (block = `max(4, H)`, `H` = max holding
   weeks). Full size: `t ≥ 2.0`, `p ≤ 0.025`; two formal checks → Bonferroni `/2` (§7).
3. **Sharpe** — annualized net **≥ 1.0 AND Deflated Sharpe P(true Sharpe > 0.5) ≥ 95%**, with the deflation trial
   count = every `balanced` config compared in research (§7).
4. **Drawdown + environment** — lifetime (from first observation, non-resettable) max DD ≤ `max_drawdown_tolerance`.
   **(v1.0 red-team patch, hole G) DD is measured on the `C*`-normalized strategy return % (as-if-full-size), NOT on
   the currently-deployed ramp dollars — so a 15% strategy drawdown counts as 15% even at the 25% rung, and the
   ramp cannot hide risk.** **The window must contain ≥ 1 *sustained* benchmark ≥ 10% drawdown (per §4 — a flash
   dip-and-recover does not count)** (else capped at 50%, §4); any single-name / sector / portfolio risk-limit
   breach ⇒ no graduation.
5. **Capacity** — `C* ≤ 0.8 · C_cap`; per trade in/out ≤ 2% · `MDV20`; whole position exitable in 2 sessions at
   ≤ 5%/day of the 60-day 10th-percentile stress volume; full-size cost = `max(observed implementation shortfall,
   95% upper bound of a √-impact model)`; target participation > 4× the largest validated participation ⇒ `not_valid`.

---

## §6. Benchmarks (frozen a-priori)

- **Primary (economic)**: `R_B,t = g*_t · R_VTI-total,t + (1 − g*_t) · R_3M-Tbill,t`, where `g*_t` = the strategy's
  *rule-implied* target equity exposure that day (NOT the operator's actual post-skip exposure — so discretionary
  cash is not flattered by a zero benchmark; cash drag stays inside the portfolio return). **(v1.0 red-team patch,
  hole H) `g*_t` is pinned as the sum of that day's rule-implied target position weights, capped at 1.0 — no
  discretion.** If the eligible universe is in fact predominantly small-cap, replace VTI with a fixed investable
  small-cap total-return benchmark **now**, not after seeing results.
- **Auxiliary (attribution, does not replace primary)**: market/size/value/profitability/investment/**momentum**
  factor regression + a fixed investable momentum ETF + a sector/size-matched portfolio. Positive vs VTI but clearly
  negative vs momentum ⇒ conclusion is "captured momentum exposure", not independent selection alpha. **(v1.0
  red-team patch, hole C) The EXACT factor set (Fama–French 5 + momentum), data source (Kenneth French Data Library),
  frequency, and construction are pinned in the JSON twin before freeze — no post-hoc factor-set selection to make
  the adjusted alpha look non-negative.**

---

## §7. Sample, effective independence, multiple testing

- Minimums (all required): ≥ 24 calendar months to full size; ≥ 96 valid weekly batches; ≥ 300 closed position
  cycles (for fill/cost/exit coverage — **not** 300 independent alpha samples); `n_eff ≥ 52` week-equivalents.
- Effective independent count: `n_eff = n / (1 + 2·Σ_{k=1..H} ρ_k)`, `H` = frozen max holding weeks; significance via
  weekly-block bootstrap, block length `max(4, H)`. (Sharpe/t are distorted by autocorrelation + time-aggregation —
  no naive √-annualization.)
- **Formal checks**: exactly two, at month 24 and month 36 → Bonferroni `/2` (each ≤ 2.5% one-sided). Daily viewing
  is allowed; graduation may only be *declared* on a formal-check date.
- **Deflated-Sharpe trial count** = number of distinct `balanced` configs actually compared on any data during
  research (log in §11 trial list). Our design sets weights as an a-priori prior (no statistical factor-mining), so
  this count should be *small* — an advantage — but every compared config must be logged honestly. **(v1.0 red-team
  patch, hole F) The trial log is honor-system / self-reported — it must be append-only + timestamped from research
  start, and its completeness (no quietly-dropped failed configs) is itself an explicit independent-red-team target
  (§11.4); a low trial count is only trustworthy if the log is verifiably complete.**
- **(v1.0 red-team patch, hole D) The ramp rungs (25/50/75%) are themselves alpha-gated looks, not just the two
  formal full-size checks.** The Bonferroni `/2` covers only the two full-size (100%) checks; the end-to-end
  false-graduation control across ALL rungs + both formal checks is the §11.2 zero-alpha calibration (≤ 5% to full),
  which must be run over the complete ladder. Each rung's bar is pre-committed here and never re-chosen after seeing
  results.
- Cross-version multiplicity is handled by the version-clock (§10): each version has its own independent clock;
  shadow variants (`theme_plus/aggressive/off`, `catalyst_off`, `overextension_selection_off`) NEVER count toward the
  gate (design §12.2).

---

## §8. Capacity and scaling detail

`C_cap = min_{i,t} ( 0.02 · MDV20_{i,t} / w_{i,t} )`, `MDV20` = PIT-visible 20-day median daily dollar volume,
`w_{i,t}` = target weight. Require `C* ≤ 0.8 · C_cap`. Stress-exit: at the 60-day 10th-percentile volume, the whole
position must clear within 2 sessions at ≤ 5%/day. Full-size cost is the **higher** of (a) observed micro-fill
implementation shortfall + fixed spread/fees, and (b) the 95% upper bound of a square-root impact model at the
target order/ADV ratio — micro-fill slippage is never linearly extrapolated. `scaling_mode`:
`linear` only if target ≤ 0.10% MDV20 and ≤ the largest validated real order and same window/order-type; `capped` if
≤ 0.50% MDV20 and ≤ 5% window volume and ≤ 2× validated max; `not_valid` beyond, or if the √-impact cost erodes net
alpha; `not_assessed` if volume/spread/timing/real-size test missing (never a pass).

---

## §9. Manual-execution compliance (ITT)

Every rule-compliant recommendation is executed in the minimal-size validation account at uniform size. Subjective
skip → cash for that planned allocation (not deleted). Re-price → real fill price + real cost. Early exit → real
result. Unfilled → the frozen cancel/chase rule. No non-recommended names in the validation account. Required:
notional coverage ≥ **98%**, weekly compliance (dollar AND count) ≥ **95%** monthly and cumulatively at each formal
check. Allowed exceptions are only pre-listed objective events (halt, no valid quote, regulatory restriction) — never
"felt wrong". **(v1.0 red-team patch, hole A) Every claimed exception needs an objective evidence stamp captured at
the time (halt record / quote snapshot / regulatory notice); an unstamped exception counts as a discretionary skip
(cash), so you cannot quietly re-label a losing pick as "no quote".** **(v1.0 red-team patch, hole E) A non-compliant
week stays IN the strategy return series at what actually happened (or benchmark/cash per the frozen rule); it is
NEVER dropped from the alpha computation — non-compliance lowers coverage, but must never become a lever to excise
bad weeks.** Below threshold ⇒ the actual portfolio evaluates system+operator, but does NOT prove the scoring engine;
counterfactual paper fills are diagnostic only.

---

## §10. Version binding and clock reset

New strategy ID + **clock restart** on any change to: 40/35/25 weights; data fields / PIT semantics / sources;
universe / ranking / entry / exit / stop / target; sizing or risk rules; manual-exception rules; or any fix that
alters *any* historical week's recommendation, price, or position. Evidence may be inherited only for: UI / wording /
report format; a fix proven by per-period replay to be bit-for-bit output-identical across all history; storage /
performance changes with identical output. Emergency risk-tightening may take effect immediately, but the new
version does not graduate on the old version's record — safety over clock preservation.

*Power note (why the ladder, not a single 24-month bar):* with `t ≈ IR·√T`, a genuine but modest strategy
(`IR ≈ 0.6`, e.g. 6% alpha / 10% TE) needs ~11 years to reach `t ≥ 2`. A single full-size `t ≥ 2` gate is therefore
nearly unpassable for modest-but-real strategies; the graduated ladder (weak bar → small size, strong bar → full
size) plus the economic-alpha / Deflated-Sharpe / adverse-environment gates carry the load a bare t-stat cannot.

---

## §11. Pre-freeze validation (MUST pass before activation — this is "how we know it's correct")

1. **Computability audit** — on throwaway synthetic data (never counts as evidence): dividends/splits/halts/unfilled,
   skips, early exits, deposits/withdrawals, missing prices, duplicate orders, version changes, and `not_valid`
   capacity all resolve to a **deterministic** verdict (same inputs → same PASS/FAIL/insufficient).
2. **Zero-alpha calibration** — ≥ 10,000 synthetic runs with zero true alpha but realistic market/sector/momentum
   exposure, serial correlation, fat tails/negative skew, high same-week correlation, and operator gaps; each run
   through the full ladder + both formal checks + trial count. **Require: P(reaching 100% `C*`) ≤ 5%.** Else tighten
   thresholds / reduce looks / lengthen sample — never "should be fine in practice".
3. **Power analysis** — simulate true net alpha 3% / 6% / 9% (× tracking-error / impact scenarios); report
   graduation probability + time-to-full at each. Surfaces how many good strategies get rejected and how long you
   wait; likely confirms 24–36 months is short for modest alpha ⇒ accept graduated ramp, do not lower the bar.
4. **Red-team + independent recompute** — someone who has NOT seen returns tries to game the frozen protocol
   (swap benchmark, delete skipped losers, pass correlated names as independent, re-version-lottery, micro-slippage
   as full-size cost, early graduate in a calm bull). Separately, a second implementation recomputes every metric
   from the frozen protocol + raw records; must match within a pre-set tolerance. Any hole found ⇒ not frozen yet.

---

## §12. Outcomes

Each formal check yields exactly one of: **PASS** (rung's full bar met → authorize that rung's size, manual),
**FAIL** (a hard gate breached, e.g. lifetime DD or a risk-limit → no graduation; a tightened version restarts the
clock), **INSUFFICIENT_EVIDENCE** (`not_assessed` / `not_evaluable` / sample or `n_eff` short, or an adverse regime
not yet observed → hold at current rung, keep accruing). "Insufficient" is never a pass. A 12-/24-month non-pass does
NOT mean the strategy is invalid — only that evidence is not yet enough to risk a full-size error (an accepted
false-negative).

---

## §13. Amendment

Append-only. Any threshold/rule change ⇒ new version file + retained old protocol + restarted evidence clock. If a
frozen method is later found wrong, fix it *prospectively* under a new version; never overwrite this file or move a
bar on data already observed.

---

*This v1.0 is a proposal. `frozen_at: null`, `frozen_sha256: null`, `status: proposed`. See the machine twin
`presets/us_short_ship_gate_protocol_v1.0.json`. Next steps after landing: `docs/SESSION_LOG.md` top entry.*
