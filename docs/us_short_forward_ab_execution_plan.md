# US-short forward A/B comparison — execution plan (Codex-facing, in-repo)

> **Purpose**: this is the in-repo, Codex-facing execution roadmap for the US-short forward A/B
> shadow-comparison work-stream. On a `执行` / `执行下一步` command for this work, **read this file,
> check current progress against the register + code, then do the first undone cut** — you do not need
> a per-cut command spelled out each time.
>
> **Design AUTHORITY (spec details, do not restate here)**: `docs/us_short_system_design.md` §12.2
> (赛道权重比较轨 + 错过成绩单, shadow-only) + §4.1/§4.3 (A1 shadow heads, chasing strip) + §13.1 #28/#36
> (governance calibration items). The frozen grid `presets/us_short_forward_policy_grid_20260711.json`
> + `schemas/us_short_forward_policy_grid.schema.json`. Register `R-USSHORT-A1-FORWARD-POLICY-MANIFEST-MATERIALIZATION`
> (resolved) + `R-USSHORT-A1-HEADS-CHASING-STRIP-REALLOC-DRIFT` (resolved).
>
> **Off-repo**: the full final-design + total-review acceptance spec is Claude's review standard
> (`us_short_forward_ab_plan.md`, not in repo). Codex only follows repo + this file.

## 1. Design 思路 (settled = Path A)

Run several cheap, deterministic **policy heads** on the SAME PIT-frozen weekly snapshot (shadow-only),
and compare their forward selection/outcome against the real `balanced` track, to learn which scoring
components / overextension effects add alpha — **with NO delayed materialization and NO §2.1/§12.2
exception** (Path A; the delayed-materialization Path B was rejected).

- The heads **re-score the frozen composition LIVE at decision time** — cheap, deterministic, **zero new
  provider calls** (they reuse the one weekly snapshot the pipeline already fetched). The outcome
  evaluators are already built (§3).
- **Never ship-gate**: only `balanced`'s real live-normalized evidence counts toward the ship-gate; every
  shadow head is comparison/calibration only. The comparator engines already enforce this isolation — any
  wiring MUST preserve it.
- **Hard gates never shadow-off**: data / PIT / halt / completeness gates are never disabled for a head;
  only economic-judgment vetoes may be ablated.
- **1 week = 1 independent statistical block** (not 15 tickers = 15 samples); **12 effective-difference
  weeks are preliminary review only; 24 plus the registered coverage gates are required before a formal
  recommendation**. The v2 statistical plan is pre-registered before outcomes (code may lag, the plan may not).
- Past-week reconstruction is research/backtest only — never forward evidence (§2.1/§12.2 ordinary rule).

## 2. The grid (const-pinned; built)

Authority = `presets/us_short_forward_policy_grid_20260711.json` (+ schema). Do not drift from it.

- **6 immediate selection heads** (materialize live at decision time): `balanced` (primary / A-B control),
  `theme_plus`, `theme_aggressive`, `theme_off`, `catalyst_off`, `overextension_selection_off`.
- **1 second-wave-live slot** (deferred, NOT built): `overextension_execution_off` — starts only once a
  later shadow-branch ledger exists; it never replays frozen weeks.
- **Deliberately NOT in the v1 grid**: `sizing_neutral`, `entry_neutral`, `rr_neutral` (considered in the
  discussion draft, dropped/deferred for v1 — the schema rejects sneaking `sizing_neutral` in).
- **Chasing strip semantics** (`R-USSHORT-A1-HEADS-CHASING-STRIP-REALLOC-DRIFT`, resolved): a chasing
  ticker's theme is stripped for the retain-strip heads via `core_score(strip_theme_score=True)` — NO
  reallocation, matching the real `balanced` selection track. `theme_off`'s reallocation is reserved for
  the dedicated `theme_off` shadow-attribution head only.

## 3. Already-built pieces (do NOT rebuild)

- Grid + schema + tests — committed.
- `engine/us_short_forward_policy_heads.py` — the 6 immediate heads (`build_selection_policy_heads` /
  `build_selection_policy_decisions`, delegating to the authoritative `run_selection`) + tests — committed
  (master), with the strip_theme_score fix. The Cut-A capstone stage consumes it for same-decision capture;
  Cut B consumes that capture through the six-policy comparison APIs below.
- Outcome evaluators (pre-built, offline, ship-gate-isolated): `engine/us_short_shadow_compare.py`,
  `engine/us_short_paper_scorecard_comparison.py` (single-week 4-lane), `engine/us_short_paper_multiweek_comparison.py`
  (≥12-week), `engine/us_short_paper_ledger.py`.
- Private de-identified shadow summary: `engine/us_short_shadow_compare_summary.py` + schema.

## 4. Cut plan — do the FIRST undone cut on `执行`

Status below is the intended order; **verify actual done-state against the register (which R-IDs are
resolved) + the code (which files/stages exist)** before picking — the marks are guidance, the
register + code are the source of truth.

- **[DONE]** grid frozen; 6 selection heads built + strip_theme_score fix; evaluators pre-built.
- **[BUILT] Cut A — wire + privately CAPTURE the 6 heads' live selections (NO comparison yet).**
  Add an additive stage in `runners/us_short_weekly_capstone.py::default_pipeline()` (after the composition/
  overext stages) that at decision time: (i) obtains the frozen `score_composition` + `overextension` map the
  heads consume — **the capstone must persist/pass these from the existing stages** (it does not today);
  (ii) runs `build_selection_policy_decisions` → the 6 heads' selection decisions; (iii) writes them to a
  **private, gitignored** path (§11.6 `shadow_compare_private`); (iv) emits a **de-identified tracked summary**
  (counts only; no ticker / no $). **Do NOT feed the comparators or `lifecycle_eval` yet** — that is Cut B:
  the built `us_short_shadow_compare` / `us_short_paper_scorecard_comparison` accept only the 4 frozen
  `scoring_profile`s, whereas `catalyst_off` + `overextension_selection_off` are ablations (not profiles), so
  the 6-head comparison is a contract change that gets its own reviewed cut. **Additive**; must not break the
  canonical anchor / gated boundaries; **ZERO new provider at decision time**; never ship-gate. Offline-buildable
  + testable; the actual live capture run stays gated (per-execution auth).
- **[BUILT] Cut B — extend the comparators + lifecycle to the 6-head policy namespace + compute the comparison.**
  Extend `us_short_shadow_compare` / `us_short_paper_scorecard_comparison` (single-week) /
  `us_short_paper_multiweek_comparison` (≥12-week) + `lifecycle_eval` from the 4-`scoring_profile` namespace
  to the 6-policy-head namespace, consume Cut A's captured selections, compute the comparison, and **preserve
  the ship-gate isolation** the comparators already enforce. The built contract preserves legacy four-profile APIs;
  the six-policy path binds Cut A's capture/source digests, exact fixed-TopN coverage, de-identified full-caliber scorecards,
  and the grid-governed >=12-week aligned window with embedded validated weekly comparisons and re-derived lineage. Lifecycle contributes only item #28;
  item #36 remains untouched because its governed unit is source-bound overextension triggers, absent from Cut A.
  Its own reviewed cut (a contract change to already-reviewed engines).
- **[BUILT] Cut C** — per-ticker **decision-diff log**: consumes the reviewed Cut-A capture and emits a private
  ticker-bearing balanced-vs-policy diff plus a schema-pinned de-identified counts summary. It re-derives
  non-selection gate stability, rank delta, selection bucket delta, and Top15 membership changes for the five
  shadow policies. Action / size diffs are explicitly marked `not_available_in_cut_a_capture` because Cut A
  does not run downstream analysis/sizing per policy; fabricating those claims is rejected.
- **[SUPERSEDED BEFORE ANY OUTCOME] Cut D v1** — immutable weekly **manifest** + **pre-registered statistical plan** (primary metric
  `net_benchmark_excess`; divergence definition; minimum weeks; comparison margin; placebo seed + match
  frequency; paired basis; elimination rule). The plan must be pre-registered day-1; the analysis code may lag.
  **All four open parameters are FROZEN below (user-ratified 2026-07-12). Build the schema/preset/manifest + tests to
  these EXACT values — do not re-open or invent. Do NOT touch Cut E; do NOT commit until Claude review.**

  **Historical v1 pre-registration record** (superseded before any outcome by the v2 contract below; retain only
  for provenance, never use it to judge a factor):
  - **Primary metric**: `net_benchmark_excess`, paired same-week vs `balanced` (already in grid `evaluation_plan`).
  - **Independence unit**: `decision_week` (1 week = 1 block; frozen). **≥12 DIVERGENCE weeks** (not calendar weeks)
    before any promotion review (`minimum_forward_weeks_before_promotion_review=12`).
  - **Divergence definition** (settled): a week counts as a divergence/effect week **iff the head's Top15 membership
    symmetric difference vs `balanced` ≥ 1 ticker**. Rank + `selection_bucket` differences under IDENTICAL membership
    are SECONDARY diagnostics only and do NOT count toward the primary divergence tally — the Cut-A capture excludes
    sizing/action (Cut C marks `size_change`/`action_change` `not_available_in_cut_a_capture`), so a bucket→outcome
    claim is unsupported. Revisit only if a future capture carries sizing.
  - **comparison_win_margin** (user-ratified): promotion-eligibility requires ALL of —
    (a) mean paired `net_benchmark_excess` advantage vs `balanced` **≥ +0.10%/week** over the ≥12 divergence weeks;
    (b) paired-win consistency **≥ 2/3** of divergence weeks (head ≥ balanced that week);
    (c) the advantage **exceeds the 95th percentile of the head's placebo null** (below). Costs are already inside the
    paired metrics — no separate cost gate.
  - **Placebo** (§12.2 mechanical-vs-real check): `placebo_replicates = 1000`, `placebo_seeds = 0..999` (deterministic,
    pre-registered — NOT drawn at analysis time). Each replicate perturbs `balanced`'s Top15 by the SAME number of
    names the head diverged that week (random in/out swaps from the same eligible candidate pool), forming the null
    for gate (c). Match frequency is thus DATA-BOUND to each head's realized weekly divergence count, not a constant.
  - **early_action = `futility_or_harm_only`** (grid), **口径 = OUTCOME-BLIND** (user-ratified — returns are examined
    ONLY at ≥12 weeks; no early outcome peeking, preserving pre-registration integrity):
    - **futility** (structural): **< 2 divergence weeks in the first 8 decision-weeks** → futility flag (cannot accrue
      ≥12 divergence samples in a reasonable horizon).
    - **harm** (structural): mean weekly Top15 turnover **> 2× `balanced`** sustained ≥2 weeks (harmonized w/ fill), OR Top15 fill **< 50%
      of `balanced`'s seat count** sustained → harm flag.
    - A flag SURFACES the head for human review — never a silent auto-drop. (The 2-in-8 / 2× / 50% concrete cutoffs are
      Claude's concretization of the ratified outcome-blind basis; adjustable on review, frozen for v1.)
  - **Paired basis**: head vs `balanced` on the identical PIT snapshot, same week, same benchmark + cost model.
  - **Elimination rule**: a futility/harm flag → surface for review; an un-flagged head runs to ≥12 divergence weeks,
    then faces the (a)+(b)+(c) gate. No promotion before the minimum (`promotion_before_minimum_allowed=false`).
  - **Boundary**: comparison/calibration only — `shadow_counts_ship_gate=false`, `changes_primary_selection=false`,
    zero new provider, no §2.1/§12.2 exception, private ticker artifacts gitignored, tracked manifest de-identified.
    The manifest METHOD must land before the first authorized LIVE capture run.
- **[SUPERSEDED COMPATIBILITY DIAGNOSTIC] Cut D-analysis — the offline legacy three-gate diagnostic.** The detailed
  v1 bullets below are historical only; current code may expose only `diagnostic_*` statuses and cannot issue a v2
  formal recommendation. The historical implementation was pure/offline/deterministic and consumed the then-defined contracts
  (Cut A captures + Cut B ≥12-week outcome scorecards + the Cut C decision-diff) and applies the const-pinned Cut-D
  manifest to emit, per shadow head, a divergence-week count + a promotion-eligibility verdict + outcome-blind
  futility/harm flags. NEW code = the placebo engine + the (a)(b)(c) gates + the futility/harm detector + per-head verdict.
  - **Computes (EVERY threshold read from the manifest via `load_forward_policy_statistical_plan()` — single source,
    NEVER re-hardcode a number in the analysis code):** divergence-week = head's Top15 membership symmetric-diff vs
    balanced ≥1 (reuse Cut C; rank/bucket NOT counted); promotion needs ALL of (a) mean paired `net_benchmark_excess`
    advantage ≥ `comparison_win_margin` over ≥12 divergence weeks, (b) paired-win consistency ≥ `paired_win_consistency_fraction`
    (2/3), (c) advantage > the 95th pct (`placebo_percentile_exclusive_gt`) of the head's placebo null; placebo null =
    `replicates`(1000) deterministic seeds `seed_start..seed_end_inclusive`(0..999), each perturbing balanced's Top15 by
    the head's realized THAT-week divergence count (random in/out from the same eligible pool) per manifest `method`;
    futility = `< futility.minimum_divergence_weeks`(2) divergence weeks within the first `within_first_decision_weeks`(8);
    harm = mean weekly Top15 turnover > `2.0×` OR fill < `0.5` sustained ≥ `sustained_decision_weeks`(2); per-head verdict
    ∈ {accumulating, futility_flag, harm_flag, promotion_eligible, not_eligible}; a flag only SURFACES for review, never auto-drops.
  - **Required guardrails (review focus):** (1) PURE / real-weeks-only — below the min divergence weeks → `accumulating`,
    NO promotion verdict (`promotion_before_minimum_allowed=false`); it MUST NOT produce / backfill / replay / fabricate any
    forward evidence; zero provider; writes no outcome data. (2) Manifest = the ONLY threshold authority (avoid the
    §4-vs-manifest drift class). (3) Bind to real weeks — reject stale / out-of-order / duplicate weeks + look-ahead
    (outcome week ≤ as_of), mirroring the upgrade-gate §12.2 ③/①. (4) Never ship-gate; `changes_primary_selection=false`;
    ticker-bearing → private/gitignored, tracked summary de-identified (counts / verdicts only — no ticker / no $).
    (5) Deterministic placebo; fail-closed on malformed input.
  - **Does NOT**: fetch forward prices or PRODUCE outcomes (that forward-outcome production is provider-gated + needs real
    weeks — a separate later piece; this engine consumes the outcome CONTRACT + fixtures); wire a live auto-writer into the
    weekly run (read-only over accumulated private data); touch Cut E. Offline-buildable + fixture-testable NOW.
  - **Tests (fixtures)**: <12 → `accumulating` (no fabricated numbers); ≥12 passing all gates → `promotion_eligible`; each
    of (a)/(b)/(c) failing alone → `not_eligible`; futility / harm each → flag; placebo determinism (same seed → identical
    null); manifest-as-single-source (mutate a manifest threshold → the verdict follows, proving no hardcode); fail-closed
    on bad shapes; a zero-real-week input yields NO forward evidence.
  - **Delivered implementation**: `engine/us_short_forward_policy_statistical_evaluation.py` and
    `schemas/us_short_forward_policy_statistical_evaluation_summary.schema.json` consume caller-supplied,
    capture-bound future-week inputs only and return a de-identified in-memory summary. They create no input/output
    writer, do not read a historical result directory, and leave the official selection, lifecycle ledger, and Cut E
    untouched. The detailed material boundary is `R-USSHORT-A1-CUT-D-ANALYSIS-VERDICT-ENGINE`.
- **[BUILT — first repair blade] Comparison v2 evidence contract + capture binding.**
  `presets/us_short_forward_policy_statistical_plan_20260716.json` supersedes v1 before any real outcome. It freezes
  the four isolated factor questions (theme weight, catalyst selection, overextension selection, with execution
  ablation explicitly second-wave), a **Pass2-clean common pool** for every head, H10 after-cost direct return,
  H5/H20 diagnostics, 12-week preliminary / 24-week formal / 36-week retirement clocks, non-overlap and market-risk
  coverage, Holm-Bonferroni correction, risk guardrails, explicit recommendation statuses, a decision receipt, and
  a no-auto-switch boundary. Cut-A private capture and its tracked de-identified summary now bind the v2 contract
  digest and the derived common-pool digest; a Pass2-vetoed name cannot enter placebo or outcome inputs. The existing
  Cut-D-analysis consumer is deliberately only a compatibility diagnostic aligned to common-pool/H10/24; it must not
  emit a v2 formal recommendation. No outcome writer, weekly orchestration, lifecycle/banner wiring, provider call,
  primary-rule change, or second-wave ledger is included in this blade.
- **[BUILT — second repair blade, pure/offline only] Outcome production core.**
  `engine/us_short_forward_policy_outcome.py` now consumes a validated v2 Cut-A capture plus one caller-supplied
  **common-pool** model-paper order per Pass2-clean ticker, exactly 20 caller-supplied daily bars, one frozen cost prior,
  and existing corporate-action evidence. It produces private H5/H10/H20 after-cost candidate returns: same-day/multi-day
  exits reuse the paper engines; a still-open name is an `evaluation_mark_only` at the horizon and never changes the
  model-paper ledger. An incomplete series or non-evaluable adjustment gate produces a whole-week
  `data_degraded_whole_week_no_count` packet with no candidate values. This is the provider-free calculation core, not a
  fetcher, writer, scheduler, or formal judge.
  **Now wired, still fail-closed**: the capstone source stage captures the Pass2-clean all-candidate controls from
  its already-fetched full-universe OHLCV packet, then a later weekly stage matures only the newly captured private
  records and feeds a ready receipt into the existing accumulator/advisor. It adds no provider call. Until an
  independently verified corporate-action/adjustment evidence sidecar exists, maturity writes an explicit whole-week
  no-count record, so no factor recommendation can accumulate from an unverified packet.
- **[BUILT — third repair blade, pure/offline only] All-candidate common order snapshot.**
  `engine/us_short_forward_policy_order_snapshot.py` consumes the validated Cut-A capture plus an exact
  Pass2-clean candidate-price input map at the capture's `price_basis_date`. It invokes the existing candidate
  price-analysis path exactly once under one shared market regime, then emits one canonical model-paper order per
  common-pool ticker with input/order digests. It never accepts a policy key, selected-only input, or a partial
  order map. If any pool member lacks an executable plan, or the common regime does not permit a new entry, it emits
  `data_degraded_whole_week_no_count` with no order map instead of inventing an order or silently dropping a name.
  The original producer remains in-memory; the later source stage now binds its generated order digest through a
  private source capture, without changing primary selection or authorizing a provider call.
- **[BUILT — fourth repair blade, offline/private writer only] Bound forward-week persistence.**
  `engine/us_short_forward_policy_private_week.py` takes one validated Cut-A capture, the third-blade common-order
  snapshot, and caller-injected 20-session bars/cost/adjustment evidence. Before one atomic private write it
  revalidates the capture/order binding, invokes the existing outcome core, and records exact capture, order-packet,
  forward-input, and outcome-packet digests in
  `state/us_short/shadow_compare_private/forward_policy_outcome_<decision_date>.json`. An order-snapshot no-count is
  persisted with no fabricated forward input/outcome; incomplete/adjustment-blocked H20 inputs are persisted as an
  explicit no-count record. It does not fetch a source, scan/accumulate weeks, wire the weekly runner, issue a
  recommendation, or change the model-paper ledger. The next blade is the smallest private accumulator/evaluator
  consumer; actual source acquisition and any provider call stay separately gated.
- **[BUILT — fifth repair blade, pure/offline projection only] Common-pool H10 weekly evidence.**
  `engine/us_short_forward_policy_weekly_evidence.py` revalidates one fourth-blade private record (including its
  stored-input outcome recomputation), retains and revalidates that complete private source week plus its frozen
  Cut-A capture, then reads the same common-pool H10 after-cost candidate value for every policy's exact captured
  selection. It emits six full-Top15 H10 basket means and five paired policy-minus-balanced
  deltas, preserves the three registered factor-question arm groups, and labels the H10 date separately from the later
  H20 availability date. An upstream whole-week no-count remains a value-free no-count projection (retaining an
  already-valid order digest only when the later price/adjustment gate, rather than order creation, degraded). This is neither a
  source-provenance assertion nor a directory reader/accumulator: `produces_forward_evidence:false`, no private write,
  no evaluator/receipt/banner, no recommendation, no model-paper-ledger change, and no conversion of an H10 evaluation mark into a production exit.
  The next blade is the smallest private accumulator with an explicit same-run provenance gate; source acquisition and
  provider calls remain separately gated.
- **[DEFERRED] Cut E** — shadow-branch ledger that activates `overextension_execution_off` (second-wave-live).
  Path-dependent; a separate cut once the ledger exists; never backfills pre-ledger weeks.

> **Pre-registration timing**: Cut A captures raw selections — clean as long as the comparison METHOD is fixed
> before the data is analyzed. So the Cut D statistical-plan manifest (metric / margin / min-weeks / placebo)
> must land **before the first authorized LIVE capture run** ("代码可缓、计划不能缓"); Cut B then applies that
> pre-registered method to Cut A's captures.

## 4.1 Functional blade 3 — source-bound accumulation / formal advice (end-to-end local wiring)

`engine/us_short_forward_policy_comparison_ledger.py` and its two schemas add the private consumer half of the
third functional blade. A ready fourth/fifth-blade private week can enter the ledger only with a distinct same-run
source receipt that binds the exact capture, source context, retained 20-session price window, frozen costs,
corporate-action evidence, common-price snapshot and an opaque source-packet digest. No-count, replay/backfill,
source-digest drift and conflicting decision dates fail closed.

The evaluator is advisory-only. It uses H10 after-cost return plus equal-weight Top15 daily marked NAV (unfilled names
stay cash), drawdown, bad-pick rate, worst-20% tail loss, fill/turnover, fixed seeds 0..999 for a one-sided paired
block bootstrap/placebo, and within-question Holm correction. It returns only `continue_accumulation`,
`recommend_adopt_arm`, `recommend_retain_balanced`, `recommend_discard_arm`, or `inconclusive`; creates a pending
explicit user receipt; and renders a persistent de-identified reminder stating that `balanced` is never auto-switched.

`forward_policy_shadow` now immediately freezes a private `forward_policy_source_capture_<decision_date>.json` from
the same capstone's already-fetched full-universe OHLCV packet: every Pass2-clean common-pool ticker receives the
same pullback-only model-paper geometry, frozen cost prior, shared axes, and source digests. The later
`forward_policy_maturity` stage scans **only** those post-deployment source captures, uses the current already-fetched
OHLCV packet for the first H20 sessions, writes the canonical private outcome, and appends only a ready receipt to
the existing ledger. It never reconstructs old selections or backfills prior weeks.

The capstone bridge injects the de-identified A1 reminder as weekly-report banner ⑥; missing/invalid private ledger
is visible as `inconclusive` but never blocks the official report or changes `balanced`. **The remaining hard gate is
intentional:** this implementation has no corporate-action/adjustment reconciliation producer. In its absence every
matured capture is written as `data_degraded_whole_week_no_count`; it cannot advance any 12/24/36-week clock. A later
authorized, independently reviewed evidence producer may place only a validated
`forward_policy_adjustment_evidence_<decision_date>.json` sidecar in the private directory; the already-wired
maturity stage will then count the ready packet. No manual receipt is accepted as real weekly evidence.

## 5. Per-cut discipline (every cut)

- Own register R-ID + SESSION_LOG block; **offline**; **zero new provider** at decision time (heads reuse the
  frozen snapshot; forward prices reuse the already-fetched grouped-daily path); ticker-bearing shadow
  selection/outcome → private/gitignored; tracked summaries → de-identified (counts only); **never ship-gate**;
  do NOT touch the §2.1/§12.2 contract or the frozen grid.
- **Review focus** (Claude, on `审查`): (1) wiring is purely **additive** — the canonical staged pipeline /
  canonical anchor / gated boundaries are intact; (2) shadow heads are **never** counted toward ship-gate
  (the comparators enforce this — the wiring must not leak a shadow head into the ship-gate path); (3) **zero
  new provider calls** at decision time; (4) ticker-bearing shadow artifacts stay private/gitignored, tracked
  summaries de-identified; (5) design-intent conformance to §12.2 + this plan.

## 6. On `执行`: how to pick the next step

1. Read this file (§4 cut plan) + the design authority (§1 pointers).
2. Check the register for the forward-A/B R-IDs' status + grep the code for which stages/files already exist.
3. Do the **first undone cut**, as its own slice (register + SESSION_LOG block).
4. If a cut needs a genuine design decision, or the next step is ambiguous → **STOP and surface to the user**;
   do not guess a contract or grid change.

## 7. Corporate-action evidence PRODUCER — unblocks real-week counting (user-authorized 2026-07-18)

**Goal**: make the A1 comparison track actually count real weeks. Cut-2 already built the maturity gate + the
sidecar VALIDATOR (`source_capture.py::_validate_maturity_adjustment_evidence`) + the maturity runner that reads a
`forward_policy_adjustment_evidence_<decision_date>.json` sidecar and no-counts when it is absent/`not_evaluable`.
The ONE missing piece is the PRODUCER that WRITES that sidecar. Register `R-USSHORT-A1-CORPORATE-ACTION-EVIDENCE-PRODUCER`
(open P1) has the frozen boundary — obey it exactly (no OHLCV-label trust, no backfill, no `balanced`/ship-gate, no ticker in tracked artifacts).

**User authorization (2026-07-18)**: build it using **Massive's FREE splits/dividends feed** (`/stocks/v1/splits` +
`/dividends`, already shape-probed + normalized — reuse `runners/us_short_batch5_massive_corporate_action_shape_probe.py`
+ `engine/us_short_massive_corporate_action_normalize.py`), **$0 free tier**, schema-first, minimum cuts. NOT authorized:
paid tiers, a new provider, `yfinance`, any source beyond Massive-free splits/dividends, backfill, `balanced`/ship-gate.

**Why 2 cuts (not 1)** — the offline/gated boundary is a safety requirement, not padding (same reason the track itself
split): the reconciliation LOGIC is offline-provable and must land fully-reviewed BEFORE any real fetch; the live Massive
fetch cannot be built/tested offline; merging them would fold provider-fetch risk into the logic review and make failures
un-isolable. This IS the merged minimum (the offline logic is already one cut; the gated fetch is the only other).

- **Cut 1 (OFFLINE, no fetch) — reconciliation producer + sidecar emitter.** New `engine/us_short_corporate_action_reconciliation.py`
  (schema-first): consume the maturity OHLCV packet + NORMALIZED split/dividend events (injected, in the existing normalizer's
  output shape), reconcile the four gates the validator requires (`adjustment_mode` / `split_handling` / `dividend_handling`
  / `ex_date_price_consistency`), bind every gate + event to the exact `maturity_ohlcv_packet` digest + frozen decision date +
  common pool + `ex_date ≤ maturity_as_of`, and emit the sidecar in the EXACT shape `_validate_maturity_adjustment_evidence`
  + `paper_performance_evaluability_from_offline_evidence` accept. Fail-closed: any missing / ambiguous / unconfirmed event ⇒
  `not_evaluable` (NEVER fabricate a confirmation). Tests: a fully-confirmed set ⇒ evaluable sidecar the cut-2 validator accepts
  and the week counts; split-only / dividend-only / ticker-change / missing-event / out-of-window ⇒ `not_evaluable` no-count;
  private-path + no-backfill guards; zero ticker/$/secret in tracked artifacts. No provider call.
- **Cut 2 (GATED, per-execution provider auth) — bounded Massive fetch + weekly wiring.** Add a bounded Massive
  `/stocks/v1/splits` + `/dividends` fetch for the Pass2-clean common-pool tickers over the H20 window (reuse the probe +
  normalizer), feed Cut-1's producer to write the real sidecar into the private root BEFORE `run_forward_policy_maturity`, so a
  fully-confirmed week finally counts. Massive FREE tier ($0); raw only under gitignored `provider_samples/`; tracked summary
  de-identified (counts only — no secret/URL/ticker/$). Wire it inside the weekly one-click so it runs under this standing
  authorization (NO per-week approval) — this is the ONE recurring automatic external call. Still shadow-only, never `balanced`,
  never ship-gate, no backfill; per-execution auth + no-secret summary reviewed like every other gated slice.

**After both cuts**: the weekly one-click auto-fetches split/div (free), certifies adjustment, and counts a real week — no
per-week human step. The clock then needs ~24-36 divergence weeks (~1yr+) before a first verdict, and any verdict is
advisory (user accepts/rejects the receipt; production is never auto-switched).
