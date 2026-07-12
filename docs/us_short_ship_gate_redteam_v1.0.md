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
