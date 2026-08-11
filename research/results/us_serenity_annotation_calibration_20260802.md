# Serenity `structural_theme_annotation` — Blade 1 contrast calibration

- **Run date**: `20260809`
- **Frozen evidence set**: existing local artifacts for decision dates `20260731` Web, `20260801` X and `20260802` X; no new provider call and no network access
- **Lane**: research-only, advisory-only, zero-cost
- **Prerequisite**: Blade 0 reviewer PASS; the two non-blocking Blade 0 rubric gaps are repaired here
- **Decision**: `GO_FOR_CALIBRATION_ONLY`
- **Blade handoff**: `upstream_smoke_artifact=research/results/us_serenity_annotation_smoke_20260809.md`; `rubric_candidate_version=serenity_structural_theme_annotation_rubric_blade1_candidate_20260809`; `calibration_verdict=Go`
- **Contrast handoff**: `contrast_class_by_theme={physical_infrastructure_bottlenecks:strong_physical_constraint, mega_data_center_investment:weak_narrative_low_evidence, ai_data_center_power_demand:long_term_short_horizon_misaligned}`; `source_artifact_locators=§1`; `negative_perturbation_result=PASS (§5)`
- **Scope boundary**: this artifact tests whether the rubric distinguishes three deliberately different evidence classes. It does not prove rubric effectiveness outside this frozen set, market confirmation, alpha, trading relevance, scoring, Top15 selection, sizing, lifecycle, operation advice, schema readiness or ship-gate evidence.
- **Execution boundary**: no provider call, no network call, no installation, no production-code/schema/consumer change, no account/state write, no broker/order action.

## 0. Effect and eligibility guard

```yaml
mode: shadow_only
common_constraint_id: structural_constraint_cluster_shadow:blade1_calibration_only
scoring_eligible: false
top15_effect_enabled: false
operation_advice_effect_enabled: false
dynamic_seats_enabled: false
theme_probe_enabled: false
lifecycle_actions_enabled: false
```

This calibration is a research annotation only. It cannot populate active `macro_cluster`, score, Top15, seat, lifecycle, operation or any other production effect path.

## 1. Fixed inputs and provenance repair

The calibration reuses existing frozen artifacts and their already stored raw evidence. Member tables and source mappings are copied from those artifacts; no member was added by hand.

| Class | Frozen artifact | Theme used | Raw source root |
|---|---|---|---|
| Strong physical constraint | `D:\cnhea\Stock\state\us_short\us_short_llm_theme_discovery_x_20260802.json` | `physical_infrastructure_bottlenecks` | `D:\cnhea\Stock\provider_samples\us_short_llm_theme_discovery_fetch_x\raw\20260802\` |
| Weak narrative / low evidence | `D:\cnhea\Stock\state\us_short\us_short_llm_theme_discovery_web_20260731.json` | `mega_data_center_investment` | `D:\cnhea\Stock\provider_samples\us_short_llm_theme_discovery_fetch_web\raw\20260731\` |
| Long-term / short-horizon-misaligned | `D:\cnhea\Stock\state\us_short\us_short_llm_theme_discovery_x_20260801.json` | `ai_data_center_power_demand` | `D:\cnhea\Stock\provider_samples\us_short_llm_theme_discovery_fetch_x\raw\20260801\` |

### 1.1 Provenance axis added by this Blade 1 repair

`source_authority` and `claim_support` remain separate axes. Blade 1 adds `provenance_mode` so a source cannot look platform-observed merely because a model transcribed it.

| `provenance_mode` | Meaning | Does not imply |
|---|---|---|
| `provider_observed_web_content` | A frozen web payload contains retrieved content and publication metadata. | It is a primary source or independently verified truth. |
| `model_transcribed` | The frozen raw payload explicitly carries `evidence_attestation=model_transcribed`. | The model's transcription is a platform-native record or primary evidence. |
| `issuer_or_regulatory_primary` | A future reviewed issuer filing or regulator record. | The disclosed fact itself proves the structural bottleneck. |
| `unknown` | The frozen record does not establish how the text was obtained. | Any upgrade in source authority or claim support. |

For the selected inputs, the single web source is `provider_observed_web_content` with `source_authority=credible_secondary`; the selected X sources are `model_transcribed` with `source_authority=lead`. All claim support remains separately recorded as `direct`, `corroborating`, or `context`.

### 1.2 Selected source ledger

| Source ref | Evidence set | Observed/published time | `source_authority` | `provenance_mode` | `evidence_attestation` | What it can support |
|---|---|---:|---|---|---|---|
| `x:425d4652d9871e5242a39ece3447293fa0da669f33fc2452330724191f35661c` | `20260802` X | `2026-07-31T02:55:44+00:00` | `lead` | `model_transcribed` | `model_transcribed` | concrete power-equipment, fiber and memory lead-time/allocation framing; not independently audited |
| `x:c60d758c57676b9ac6aa8400c16e6ecc924b4083dbb8534b4e545914327e7aac` | `20260802` X | `2026-07-30T08:31:31+00:00` | `lead` | `model_transcribed` | `model_transcribed` | physical-infrastructure build-speed framing plus GD/VRT/BE mentions; no direct member-level scarcity proof for every name |
| `web:d131ee37dc7ce858ce134638e660a734a00386db407c8fdcf32c1027393a8e73` | `20260731` Web | `2026-07-27T00:00:00+00:00` | `credible_secondary` | `provider_observed_web_content` | `not_present_in_raw_record` | Forbes-reported proposed data-center project and its planned power scale; one source only |
| `x:00b0f4a0672a4b8cdbf3cb874ffa2917f03f34075353979fc03a6ea5bc3e9768` | `20260801` X | `2026-07-26T12:00:34+00:00` | `lead` | `model_transcribed` | `model_transcribed` | 2035 power-demand framing and named company roles |
| `x:4bed663825cd390af8731081fa1fa96ea9a50f50920759c8a93cd25c21ff2760` | `20260801` X | `2026-07-29T01:13:15+00:00` | `lead` | `model_transcribed` | `model_transcribed` | named transmission, substation, electrification, distribution, cooling and generation roles |
| `x:6568562e8eec0437eb4397f6918115d4727fc023739833dbd99a72e55b4e6393` | `20260801` X | `2026-07-25T23:38:19+00:00` | `lead` | `model_transcribed` | `model_transcribed` | repeated 194 GW/2035 framing and named generation/equipment/utility groups |
| `x:99528c938398bfb2c8120fd1f7b5d29f798a355876e79c193433e88c3f69661f` | `20260801` X | `2026-07-26T05:25:50+00:00` | `lead` | `model_transcribed` | `model_transcribed` | repeated 194 GW/2035 framing and NEE/VST/CEG names |
| `x:bffc712daa6ee59859a12194a3fb04739390f1a6fd6824919bcda0eeea6b8646` | `20260801` X | `2026-07-27T21:39:03+00:00` | `lead` | `model_transcribed` | `model_transcribed` | repeated 253%/194 GW/2035 framing |

## 2. Repaired five-category role rubric

The category is determined by two separate questions: **what layer does the source bind the member to?** and **does a source-bound scarcity/pricing mechanism exist?** A name-only mention never earns `供应卡点`.

| Category | Required evidence | Explicit non-qualification |
|---|---|---|
| `控制卡点` | Direct layer match + direct scarcity mechanism + direct evidence the issuer controls/owns the constrained asset, capacity, access, or contractual position. | A source calling a company a leader or beneficiary is insufficient. Model-transcribed-only evidence cannot be `evidence_backed`. |
| `供应卡点` | Direct layer match + direct/corroborating scarcity mechanism tied to the member: lead time, allocation, capacity utilization, backlog, price or equivalent. | A source naming a product/layer without a member-specific mechanism remains `普通受益` or `只有故事`. |
| `普通受益` | The member is source-bound to the theme or exposed to demand, but the layer or scarcity mechanism gate is incomplete. | It is not a negative judgment; it is the honest default when mechanism evidence is absent. |
| `弱定价权` | Direct evidence the member supplies the layer but is a price-taker, has weak pass-through, or is exposed to commoditized economics. | Unknown pricing power is not silently converted to weak pricing power. |
| `只有故事` | Only an unbound thematic mention, or member evidence disappears after the source perturbation. | No member-specific source-bound role may be inferred from the theme headline alone. |

`qualification` is reported separately as `qualified_candidate`, `candidate_unverified`, `not_qualified`, or `unbound`. `source_authority=lead` and `provenance_mode=model_transcribed` can support a research candidate, but cannot produce `evidence_backed` or any effect.

## 3. Independent per-theme annotations

### 3.1 Class A — strong physical constraint: `physical_infrastructure_bottlenecks`

- **`system_change`**: AI/data-center expansion is meeting physical infrastructure limits in power equipment, optical fiber and memory, with long delivery cycles and allocation/capacity pressure.
- **`value_chain_layers`**: demand → data-center/energy systems → power equipment/fiber/memory modules → transformers, fiber and DRAM devices → factory commissioning/allocation → equipment/material production → project infrastructure.
- **`scarce_layer`**: `long_lead_physical_infrastructure_components`.
- **`constraint_mechanism`**: direct lead-time, allocation, factory-capacity and price-pressure evidence is present in `x:425d…5661c`; `x:c60d…7aac` corroborates that delivery speed, not demand alone, is the limiting mechanism.
- **`common_constraint_id`**: `structural_constraint_cluster_shadow:long_lead_physical_infrastructure_components`
- **`system_change_id`**: `system_change:physical_infrastructure_bottlenecks@20260802`
- **`structural_status`**: `plausible` as a research hypothesis; all source authority is still `lead` and no primary verification is claimed.
- **`horizon_alignment`**: `3-12月 + 长期`; 52–144 week lead-time statements create a near-term order/backlog path and a longer construction path.
- **`near_term_observable`**: member-level order/backlog, allocation, factory utilization, delivered lead time, price pass-through and project-delay disclosures over the next 1–4 quarters.
- **`horizon_basis_source_ref_ids`**: `x:425d4652d9871e5242a39ece3447293fa0da669f33fc2452330724191f35661c`, `x:c60d758c57676b9ac6aa8400c16e6ecc924b4083dbb8534b4e545914327e7aac`

| Ticker | Role category | Qualification | Source-bound reason | `source_ref_ids` | Support boundary |
|---|---|---|---|---|---|
| `AMZN` | `普通受益` | `not_qualified` | capex/demand exposure; no supply-layer mechanism | `x:425d…5661c` | `direct` for exposure, not for control/supply choke |
| `BE` | `普通受益` | `not_qualified` | speed-to-power mention without member-specific scarcity metric | `x:c60d…7aac` | `context` for physical build-speed |
| `GD` | `普通受益` | `not_qualified` | backlog mention does not bind the company to the named power/fiber/memory choke | `x:c60d…7aac` | `direct` for backlog mention, not for this scarce layer |
| `GLW` | `供应卡点` | `candidate_unverified` | optical-fiber lead time, full factories and commissioning time bind the member to a named scarce layer | `x:425d…5661c` | `direct` mechanism, `lead` authority; not evidence-backed |
| `META` | `普通受益` | `not_qualified` | capex/demand exposure; no supplier mechanism | `x:425d…5661c` | `direct` for exposure, not for control/supply choke |
| `MU` | `供应卡点` | `candidate_unverified` | DRAM allocation and long lead time bind the member to a named scarce layer | `x:425d…5661c` | `direct` mechanism, `lead` authority; not evidence-backed |
| `VRT` | `普通受益` | `not_qualified` | guidance/speed-to-power mention without a direct lead-time or allocation fact for VRT | `x:c60d…7aac` | `context` for build-speed |

No `控制卡点` or `弱定价权` is assigned: the frozen set contains no member-specific control or pass-through evidence. The two `供应卡点` entries are candidates because they pass the layer-plus-mechanism rule, not because the source merely names them.

#### Class A falsifiers

| Type | Statement | Observable metric | Expected window | Status | `source_ref_ids` |
|---|---|---|---|---|---|
| `mechanism_failure` | Lead times/allocation normalize without project delay or price pressure. | Delivered lead time, allocation status, factory utilization, project-delay rate. | 3–12 months. | `open` | `x:425d…5661c`, `x:c60d…7aac` |
| `member_role_failure` | GLW/MU do not show the cited fiber/memory exposure in filings or operating data. | Product mix, backlog, allocation, pricing and customer disclosures. | Next reported quarter or annual filing. | `open` | `x:425d…5661c` |
| `horizon_failure` | No order/backlog or project-delivery path appears within 3–12 months. | Orders, backlog, delivery dates, capex and project milestones. | 3–12 months. | `open` | `x:425d…5661c`, `x:c60d…7aac` |

### 3.2 Class B — weak narrative / low evidence: `mega_data_center_investment`

- **`system_change`**: a reported mega data-center project is used as an AI-capex/power narrative.
- **`value_chain_layers`**: demand and proposed infrastructure are mentioned; equipment, supplier and scarcity layers are not source-bound for the three members.
- **`scarce_layer`**: `unknown`.
- **`constraint_mechanism`**: `not_established`; the one web article supports project scale, not a member-specific bottleneck.
- **`common_constraint_id`**: `structural_constraint_cluster_shadow:unresolved_mega_project_power_access`
- **`system_change_id`**: `system_change:mega_data_center_investment@20260731`
- **`structural_status`**: `unverified_lead`.
- **`horizon_alignment`**: `3-12月候选`; the article mentions a later project phase, but no near-term member-level revaluation path is frozen.
- **`near_term_observable`**: permits, power-access decisions, phase completion, capex commitment and member-specific contracts; none is independently bound in this calibration input.
- **`horizon_basis_source_ref_ids`**: `web:d131ee37dc7ce858ce134638e660a734a00386db407c8fdcf32c1027393a8e73`

| Ticker | Role category | Qualification | Source-bound reason | `source_ref_ids` | Support boundary |
|---|---|---|---|---|---|
| `GOOGL` | `普通受益` | `not_qualified` | project/AI demand exposure only | `web:d131…e73` | `direct` for article membership, not for scarcity |
| `MSFT` | `普通受益` | `not_qualified` | project/AI demand exposure only | `web:d131…e73` | `direct` for article membership, not for scarcity |
| `NVDA` | `普通受益` | `not_qualified` | chip/project exposure only | `web:d131…e73` | `direct` for article membership, not for scarcity |

No `供应卡点` is assigned: the one source does not bind any member to a constrained supply layer or pricing mechanism. The single-source web record is stronger provenance than a model-transcribed X post, but its claim support is still too narrow for a bottleneck conclusion.

#### Class B falsifiers

| Type | Statement | Observable metric | Expected window | Status | `source_ref_ids` |
|---|---|---|---|---|---|
| `project_not_realized` | The proposed project, power access or phase schedule is cancelled, delayed or materially reduced. | Permit, financing, power-access and construction milestones. | 3–12 months. | `open` | `web:d131…e73` |
| `member_role_failure` | GOOGL/MSFT/NVDA have no contract, capex or project exposure beyond the article mention. | Issuer disclosures and project documents. | Next reported quarter or annual filing. | `open` | `web:d131…e73` |
| `evidence_quality_failure` | No second independent source corroborates the project or its power scale. | Independent source count and primary disclosure presence. | Before any promotion decision. | `open` | `web:d131…e73` |

### 3.3 Class C — long-term / short-horizon-misaligned: `ai_data_center_power_demand`

- **`system_change`**: AI data-center electricity demand is framed as a multi-year generation/grid/equipment expansion.
- **`value_chain_layers`**: demand → reliable power system → generation/transmission/distribution/cooling modules → equipment and infrastructure; no direct short-term project mechanism is frozen.
- **`scarce_layer`**: `reliable_power_delivery_and_interconnection_capacity` candidate only.
- **`constraint_mechanism`**: repeated 2035 demand framing and named roles, but no direct lead-time, allocation, backlog or project-delivery measurement in this input.
- **`common_constraint_id`**: `structural_constraint_cluster_shadow:reliable_power_delivery_and_interconnection_capacity`
- **`system_change_id`**: `system_change:ai_data_center_power_demand@20260801`
- **`structural_status`**: `unverified_lead`, matching Blade 0 §2.9 for the same frozen theme and five source refs. The horizon is long, but no new independent mechanism evidence was added in this calibration, so the status cannot upgrade.
- **`horizon_alignment`**: `长期`.
- **`near_term_observable`**: orders/backlog, contracted capacity, interconnection milestones, energization, utility contracts and reported power/cooling demand; **not observed in the frozen artifact**.
- **`horizon_basis_source_ref_ids`**: `x:00b0f4a0672a4b8cdbf3cb874ffa2917f03f34075353979fc03a6ea5bc3e9768`, `x:6568562e8eec0437eb4397f6918115d4727fc023739833dbd99a72e55b4e6393`, `x:99528c938398bfb2c8120fd1f7b5d29f798a355876e79c193433e88c3f69661f`, `x:bffc712daa6ee59859a12194a3fb04739390f1a6fd6824919bcda0eeea6b8646`

| Ticker | Role category | Qualification | Source-bound reason | `source_ref_ids` | Support boundary |
|---|---|---|---|---|---|
| `CEG` | `普通受益` | `not_qualified` | generation is named but no member-specific scarcity/control mechanism | `x:00b0…e9768`, `x:4bed…2760`, `x:6568…39`, `x:9952…661f` | `direct` for role name, `context` for bottleneck |
| `VST` | `普通受益` | `not_qualified` | generation/utility is named but no direct scarcity mechanism | `x:00b0…e9768`, `x:6568…39`, `x:9952…661f` | `direct` for role name, `context` for bottleneck |
| `NEE` | `普通受益` | `not_qualified` | utility is named but no member-specific capacity or contract evidence | `x:6568…39`, `x:9952…661f` | `direct` for membership/name, `context` for thesis |
| `ETN` | `普通受益` | `not_qualified` | distribution equipment is named but no lead-time/backlog/allocation evidence | `x:00b0…e9768`, `x:4bed…2760`, `x:6568…39` | `direct` for role name, `context` for bottleneck |
| `GEV` | `普通受益` | `not_qualified` | turbines/electrification are named but no member-specific mechanism | `x:00b0…e9768`, `x:4bed…2760`, `x:6568…39` | `direct` for role name, `context` for bottleneck |
| `PWR` | `普通受益` | `not_qualified` | transmission/substations are named but no project/queue evidence | `x:00b0…e9768`, `x:4bed…2760`, `x:6568…39` | `direct` for role name, `context` for bottleneck |
| `VRT` | `普通受益` | `not_qualified` | power/cooling is named but no direct scarcity mechanism | `x:00b0…e9768`, `x:4bed…2760` | `direct` for role name, `context` for bottleneck |

No member qualifies as `供应卡点` under the repaired rule: every source-bound role is a name-level association without the direct mechanism evidence present in Class A.

#### Class C falsifiers

| Type | Statement | Observable metric | Expected window | Status | `source_ref_ids` |
|---|---|---|---|---|---|
| `demand_path` | The 194 GW/2035 or comparable demand path is revised down materially. | Independent load forecasts, utility load additions and realized load. | Quarterly through 2035; first recheck in 3–12 months. | `open` | `x:6568…39`, `x:9952…661f`, `x:bffc…8646` |
| `mechanism_absent` | Named companies do not show a delivery/interconnection, order, backlog or capacity path. | Filings, orders/backlog, contracted capacity and project milestones. | 3–12 months. | `open` | All five `20260801` X refs |
| `horizon_mismatch` | The theme remains a 2035 story with no short-horizon repricing or delivery evidence. | Next-quarter operational evidence and project milestones. | 3–12 months. | `open` | All five `20260801` X refs |

## 4. Contrast result

| Class | `structural_status` | Horizon | Qualified/candidate supply roles | Evidence signature | Calibration distinction |
|---|---|---|---|---|---|
| Strong physical constraint | `plausible` | `3-12月 + 长期` | `GLW`, `MU` as `candidate_unverified` | direct lead-time/allocation/capacity mechanism | mechanism evidence unlocks a supply-role candidate |
| Weak narrative / low evidence | `unverified_lead` | `3-12月候选` | none | one web source; project scale but no member-specific choke | source authority alone does not unlock a supply role |
| Long-term / short-horizon-misaligned | `unverified_lead` | `长期` | none | repeated forecast/role names; no short-term mechanism | same status floor as the weak class; horizon plus absent mechanism distinguishes it, not an unsupported status upgrade |

The three classes are not assigned a numerical score. Class A differs by mechanism evidence and candidate qualification; Classes B and C intentionally share the `unverified_lead` status because neither received new independent evidence. B and C are distinguished by horizon alignment and the absence of a short-term mechanism, not by an unsupported status upgrade. The strong class is not promoted to `evidence_backed` because its mechanism sources are model-transcribed leads.

## 5. Negative perturbation: remove key source and re-run the same rubric

Each perturbation removes source references from the frozen annotation only; it does not add replacement evidence, change the member universe or re-run discovery.

| Class | Perturbation | Before | After | Required degradation |
|---|---|---|---|---|
| Strong physical constraint | Remove `x:425d4652d9871e5242a39ece3447293fa0da669f33fc2452330724191f35661c` (the only cited source for AMZN/GLW/META/MU). | `GLW`/`MU` = `供应卡点 / candidate_unverified`; status=`plausible`; direct mechanism claims present. | AMZN/GLW/META/MU lose member-bound evidence; `GLW`/`MU` become `只有故事 / unbound`; status=`unverified_lead`; mechanism claim support becomes unbound. | **Pass**: role and status both degrade. |
| Weak narrative / low evidence | Remove the sole `web:d131ee37dc7ce858ce134638e660a734a00386db407c8fdcf32c1027393a8e73` source. | Three members = `普通受益 / not_qualified`; project claim support=`direct`; status=`unverified_lead`. | All three members become `只有故事 / unbound`; project claim support becomes unbound; status stays at the already-low `unverified_lead` floor. | **Pass**: member claim support and roles degrade; status cannot go below the honest floor without inventing a new state. |
| Long-term / short-horizon-misaligned | Remove forecast-basis refs `x:00b0f4a0672a4b8cdbf3cb874ffa2917f03f34075353979fc03a6ea5bc3e9768`, `x:6568562e8eec0437eb4397f6918115d4727fc023739833dbd99a72e55b4e6393`, `x:99528c938398bfb2c8120fd1f7b5d29f798a355876e79c193433e88c3f69661f`, and `x:bffc712daa6ee59859a12194a3fb04739390f1a6fd6824919bcda0eeea6b8646`. | status=`unverified_lead`; horizon basis has four refs; long-horizon claim support=`direct`. | status remains `unverified_lead` at the honest floor; horizon basis is empty; VST/NEE lose member evidence and become `只有故事`; remaining x:4bed role names are context only. | **Pass**: horizon basis and member support degrade; status does not invent an upgrade or a lower-than-floor state. |

The perturbation result closes the free-label Optional: a role does not survive merely because a theme once mentioned the company; it needs a surviving source-bound layer and mechanism pair.

## 6. Blade 1 Go/Stop result

### Go

`GO_FOR_CALIBRATION_ONLY`:

- three contrast classes were filled independently from existing frozen Web/X artifacts;
- `provenance_mode=model_transcribed` is explicit and cannot masquerade as platform-observed evidence;
- the five role categories have written qualification criteria rather than name-based labels;
- the strong class has mechanism-specific supply candidates, while the weak and long-horizon classes do not;
- the negative perturbation makes roles, claim support and/or structural status degrade under the same rubric;
- all important claims remain source-bound and all active/effect paths remain disabled.

### Stop boundary

This calibration must not be generalized to effectiveness or production. Do not start Blade 2, schema work, wiring, provider execution, effect mapping, forward testing or any scoring/Top15/action path from this artifact. A future failure to distinguish a new three-class set, or a negative perturbation that leaves a role/status unchanged without an explicit floor explanation, requires rubric revision before any engineering step.
