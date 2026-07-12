# US-short Ship-Gate Protocol v1.0 — Red-team Record (first pass)

> Pre-freeze validation record for `docs/us_short_ship_gate_protocol_v1.0.md` §11.4.
> **This is a FIRST-PASS, self-red-team by the protocol's author (Claude).** It de-risks early and produces the
> fixes below, but it does NOT complete the §11.4 validation: because the same party wrote the protocol, blind spots
> remain. An **independent** red-team (a different LLM / person who did not write it) is still required before freeze
> — see the capstone-gate lesson (a solo self-review that read "clean" still missed a shadow-interaction hole that an
> independent pass caught). `pre_freeze_validations.red_team` therefore stays `pending`.
>
> Method: adversary hat — "if I wanted a bad strategy to graduate, or to fool myself, where do the rules leak?" —
> walked gate by gate. Date: 2026-07-12 (author pass).

## Findings — 8 real holes, all patched into the protocol

| # | Hole (attack / self-deception path) | Was it blocked? | Fix (patched) |
|---|---|---|---|
| **A** | Re-label a losing pick as an objective exception ("no quote"/"halt") to drop it from the measurement ledger. | Partially — exceptions were limited to objective events, but the claim was unverifiable. | §9: every claimed exception needs an objective evidence stamp captured at the time; unstamped ⇒ counts as a discretionary skip (cash). |
| **B** | "Adverse regime experienced" satisfied by a flash 10% dip that recovers in 2 days — proves nothing about real downside for a long-only book. | No — a blip counted. | §4/§5·4: require a *sustained* ≥10% benchmark drawdown (below prior peak ≥20 trading days / not recovered within 4 weeks); a flash dip-and-recover does not count. |
| **C** | Choose, after seeing results, the factor set that makes factor-adjusted alpha look non-negative ("e.g. Kenneth French Mom" was not pinned). | No — "e.g." left discretion. | §6: pin the EXACT factor set (FF5 + momentum), data source (Kenneth French), frequency, construction in the JSON twin before freeze. |
| **D** | Treat the ramp rungs (25/50/75%) as free looks; the Bonferroni `/2` only counted the two 100% checks, so extra alpha-gated looks inflate false-positives. | Partially — the /2 understated the number of looks. | §7: rung bars are pre-committed; the end-to-end ≤5% false-graduation control is the §11.2 calibration run over the FULL ladder (all rungs + both formal checks), not the analytical /2 alone. |
| **E** | Dump bad weeks into "non-compliant" and drop them from the alpha series while keeping coverage just above 98%. | No — §9 didn't say whether non-compliant weeks leave the return series. | §9: a non-compliant week stays IN the return series at what actually happened (or benchmark/cash); it is never dropped — non-compliance only lowers coverage. |
| **F** | Quietly omit failed `balanced` configs from the trial log, deflating the Deflated-Sharpe deflation. | No — trial count was self-reported, unverified. | §7: trial log must be append-only + timestamped from research start; its completeness is an explicit independent-red-team target; a low count is trustworthy only if the log is verifiably complete. |
| **G** | During the ramp, measure drawdown on the small deployed dollars, so a real 15% strategy drop reads as ~3.75% at the 25% rung. | Ambiguous — "C* basis" implied it but wasn't explicit. | §5·4: DD is measured on the `C*`-normalized strategy return % (as-if-full-size), not deployed ramp dollars. |
| **H** | Fuzz the benchmark's `g*_t` (rule-implied exposure) to flatter the benchmark. | Ambiguous — `g*_t` was not precisely defined. | §6: `g*_t` pinned = sum of that day's rule-implied target position weights, capped at 1.0; no discretion. |

## Noted (minor / low-risk — flagged, not patched into prose)

- **I. Zero-pick weeks**: how a week with 0 recommended names counts (thin universe) is undefined. Should count as a
  valid observation (cash/benchmark), not skipped. **Pin in the JSON before freeze.**
- **Residual limitation (by design, not a fixable hole)**: the protocol reduces but cannot mathematically eliminate a
  solo operator's self-deception via dishonest data entry — same philosophy as the design's guards ("焊死正常路径 +
  抓常见绕过 + 审查兜底, 非数学上不可绕"). The independent recompute + red-team (§11.4) and honest logging are the
  mitigations; there is no way to make it bypass-proof for a determined self-deceiver.

## Net

First-pass self-red-team closed 8 real holes (all patched) + flagged 1 minor pin (I) + 1 residual limitation. The
protocol is materially tighter. **Still required before freeze**: an independent red-team (different LLM/person) +
the §11.2 zero-alpha calibration + §11 items 1 & 3.

---

## Second red-team — external, independent (2026-07-12) — triage of 24 findings

An independent LLM red-teamed the patched protocol. **It found the one genuinely-killer logical hole both prior
passes missed (N1 = E-core): my ITT patch kept bad weeks in the series but did NOT stop a discretionary deviation
(skip / re-price / early exit) from *improving* the strategy-measurement ledger** — skipping a pick the rule would
have lost recorded cash, not the rule's loss. That alone justified the exercise. The rest is high-quality but written
to an **institutional / adversarial** standard; triaged below for a **solo, manual, small-account** operator (the
"not ready to freeze / 8 blocking" verdict is correct for an institutional bar — for a solo operator who *wants*
honest results, group A is what matters). This is the freeze-checklist; the eventual freeze applies A + B.

**Group A — real conceptual holes, cheap, fit solo scale (PATCH / apply):**
- **N1 (PATCHED §9)** — deviations scored at the deterministic frozen-RULE counterfactual; a deviation can only leave
  the strategy record unchanged or worse, never better. Compliant fills stay at real fills (executability).
- **N7 (PATCHED §9)** — validation uses the frozen target weights scaled by one `k_t`, not equal-dollar.
- **N9 (PATCHED §6)** — `g*_t` from the FULL target portfolio; long-only >100% target = construction error to fix,
  not something the 1.0 cap hides.
- **To apply at freeze (conceptual, one-liners):** N10 activate on the next scheduled run day (no timed start);
  N14 adverse regime must occur *while actually deployed* (min exposure/orders during the stress); N15 drawdown on
  DAILY (not weekly) marks; N16 implementation shortfall from arrival price over ALL intended orders incl. unfilled;
  N19 count "scheduled weeks" not "valid weeks" — a system-failure week never auto-counts as favorable cash;
  N21 any code change touching a potentially-triggerable branch restarts the clock even if historical replay is
  identical; N22 FAIL vs INSUFFICIENT decision matrix (missing the bar at a fixed check = FAIL, not endless wait;
  lifetime-DD breach = permanent fail); N23 full-size authorization has periodic maintenance checks + expiry (alpha/
  capacity/risk decay → downgrade); N24 `C*`/ramp/capacity limits apply across ALL accounts of the same operator
  running this strategy; N6 each rung validated by REAL deployment at that size (not micro-size extrapolation);
  I zero-pick weeks — rule-zero = cash, but data-failure/late-run ≠ favorable cash, and existing holdings stay valued.

**Group B — pin exact values/rules at freeze (specify, don't "build"):** N5 fixed check calendar for every rung;
N8 numeric "predominantly small-cap" threshold + require both exposure-matched-VTI AND size/sector-matched benchmark
(if claiming selection alpha, the 5% floor applies vs the matched benchmark); N11 clamp `1 ≤ n_eff ≤ n` + a
non-negative long-run-variance estimator; N12 pin exact stat defs (annualization / HAC lag / bootstrap type+seeds /
DSR version / rounding / both-halves split); N13 when the (small) calibration runs — freeze DGP+params+seeds BEFORE
seeing results, require a one-sided 95% binomial upper bound ≤ 5% (not the raw pass rate), drop no seeds.

**Group C — institutional-grade, DECLINED for a solo manual operator** (honor-system; mitigations = the operator
*wants* honest results, + independent review, + the design's a-priori-weight / no-factor-mining discipline):
- **N2** salted commitment-hash of `C*` held by an independent custodian → overkill. Mitigation: write `C*` down +
  dated at freeze (local file); any change restarts the clock.
- **N3** external timestamp authority / transparency log for weekly manifests → overkill. Mitigation: commit the
  weekly decision packet to local git at decision time (PIT), before the outcome is known.
- **N4** global family-wise error budget + holdout lock-box → overkill. Mitigation: weights are set a-priori (no
  statistical factor-mining), which structurally keeps the version family small; log every compared config honestly.
- **N18** modeled portfolio-level crowded-exit stress → note as a capacity CAVEAT at solo small size, not a modeled
  gate (the per-name 2%/MDV + stress-exit already bounds it).
- **N20** normative manifest binding all files with external signed timestamps → overkill. Mitigation: declare the
  JSON twin the single authoritative spec (MD is the human companion), and the freeze records the git commit + hashes.

**Net**: 1 killer + 2 conceptual fixes patched now; ~11 conceptual one-liners + 5 pin-items recorded for the freeze;
5 institutional controls declined-with-reason. The protocol is a proposal and freezes only at go-live, so group A/B
are applied AT freeze (with numbers pinned then) — recorded here so nothing is lost, without bloating the proposal.
