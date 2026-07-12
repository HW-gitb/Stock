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
- **1 week = 1 independent statistical block** (not 15 tickers = 15 samples); **≥12 forward weeks** before
  any promotion review; the statistical plan is **pre-registered day-1** (code may lag, the plan may not).
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
  no comparator or lifecycle consumer exists until Cut B.
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
- **[ ] Cut B — extend the comparators + lifecycle to the 6-head policy namespace + compute the comparison.**
  Extend `us_short_shadow_compare` / `us_short_paper_scorecard_comparison` (single-week) /
  `us_short_paper_multiweek_comparison` (≥12-week) + `lifecycle_eval` from the 4-`scoring_profile` namespace
  to the 6-policy-head namespace, consume Cut A's captured selections, compute the comparison, and **preserve
  the ship-gate isolation** the comparators already enforce. Its own reviewed cut (a contract change to
  already-reviewed engines).
- **[ ] Cut C** — per-ticker **decision-diff log**: turning a head off, does it change gate-pass / rank /
  Top15 membership / action / size — a deterministic counterfactual diff (not post-hoc correlation),
  private + de-identified.
- **[ ] Cut D** — immutable weekly **manifest** + **pre-registered statistical plan** (primary metric
  `net_benchmark_excess`; divergence definition; minimum weeks; comparison margin; placebo seed + match
  frequency; paired basis; elimination rule). The plan must be pre-registered day-1; the analysis code may lag.
- **[DEFERRED] Cut E** — shadow-branch ledger that activates `overextension_execution_off` (second-wave-live).
  Path-dependent; a separate cut once the ledger exists; never backfills pre-ledger weeks.

> **Pre-registration timing**: Cut A captures raw selections — clean as long as the comparison METHOD is fixed
> before the data is analyzed. So the Cut D statistical-plan manifest (metric / margin / min-weeks / placebo)
> must land **before the first authorized LIVE capture run** ("代码可缓、计划不能缓"); Cut B then applies that
> pre-registered method to Cut A's captures.

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
