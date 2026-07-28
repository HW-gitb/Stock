# US-short soft-discovery X live response-shape re-review — 2026-07-28

## Scope and outcome

The initial captured-shape re-review did not close unfreeze step ②: independent review found K3-R68 (missing decision-week floor) and K3-R69 (missing served-model receipt binding). This handoff now records their executor repair, still without a new provider request, credential read, network call, or live run.

The captured shape is: response text in `output_text`; `results` and `citations` absent (`None`); URL attestation only in `output[].content[].annotations[*]` entries of type `url_citation`. The model-produced JSON `sources` are therefore accepted only as `model_transcribed` when their canonical URL is present in that annotation set.

## Code and regression evidence

`GrokXSearchClient` keeps the transcript through `_response_text`, finds no provider text rows through `_provider_result_rows`, and extracts URL attestations through `_provider_annotation_urls`. `build_x_fetch_packet` accepts an annotation-backed model source and rejects the same source when the annotation is absent with `model_source_url_not_provider_annotated`.

The shape is pinned by `tests/provider/test_us_short_llm_theme_discovery_fetch_x_merge.py::XFetchAndMergeTests.test_captured_grok_response_shape_routes_only_annotation_backed_transcript`. The fixture records only the observed structural fields and safe local values; it does not copy provider raw content.

Fixed main Python command and actual result:

```text
.tools\run_unittest_with_repo_pythonpath.cmd tests.provider.test_us_short_llm_theme_discovery_fetch_x_merge
Ran 39 tests in 9.160s
OK
```

## Boundary and remaining gates

`run_x_fetch(live=True)` still fails before any key, client, budget, or network action. This handoff does not authorize a provider call, lift K3-R34, repair K3-R31/K3-R32, enable scoring or `theme_soft_boost_enabled`, or begin 4d.

The next technical work remains K3-R31 and K3-R32. Only after those repairs and their review may the K3-R34 freeze be reconsidered under a separate user command.

## Pre-Codex self-review

`matrix=complete; register=updated; handoff=updated; focused=61 OK; full-lane=not_triggered: AGENTS rule 3; reason=X intake/receipt schema and direct consumers only`.

## K3-R68/K3-R69 repair update

X normalization now reuses `web._decision_week_start` and emits `published_at_outside_decision_week` per stale source. The captured model-transcribed source dated 2026-03-02 is rejected; prior-Friday and Sunday controls remain accepted.

The X receipt schema now requires `fetch_contract.grok_model` with the requested alias, the provider-reported served model, and unique system fingerprints. `GrokXSearchClient` extracts the identity from the response; orchestration carries it to the builder, which rejects a successful live-shaped attempt that lacks a served model. The identity is receipt metadata rather than part of `discovery_artifact_sha256`, which deliberately binds normalized discovery evidence only.

The captured annotation-backed response now runs through orchestration and the builder in one regression test. Fixed main Python direct pack:

```text
tests.provider.test_us_short_llm_theme_discovery_fetch_x_merge
tests.schema.test_us_short_llm_theme_discovery_fetch_x_schema
tests.provider.test_us_short_llm_theme_discovery_offline_invariants
tests.provider.test_us_short_offline_production_entry_guard
Ran 61 tests
OK
```

This is pending independent review. K3-R34 remains frozen, and K3-R31/K3-R32 remain outside this repair.

## 2026-07-28 追加：独立审查两轮（FAIL → PASS），步骤 ② 至此才真正闭合

第一轮判 **FAIL**。钉住捕获形状是对的，但步骤 ② 的命题是「拿真实形状复审 live 半边」——web 侧同一步正是这样挖出 K3-R49～R58。横扫兄弟 lane 后开出两条 Required：**K3-R68**（X 侧无当周下限，五个月前的旧帖仍能撑出 `both`/5.0；这同时是 K3-R66 leg 1 写明却未满足的闭合条件）、**K3-R69**（X 收据不绑 served model，K3-R53 已在 web 关闭的同类）。

第二轮判 **FAIL（K3-R68 闭合，K3-R69 未闭）**。K3-R68 复用 `web._decision_week_start`、落在唯一入口 `_normalize_results`：旧帖掉 `published_at_outside_decision_week`，而上周五 / 上周日 / 决策当日仍各接受 1 条——未重演 K3-R56 的过度收紧。K3-R69 的产物形状也对：无 served 的 live 尝试被拒、全查询失败仍诚实建包、服务端换成 `grok-4.5` 时照建并把差异记进 `fetch_contract.grok_model`。两道守卫各有一个具名测试在我外部挖空后转红。

但 K3-R69 的编排腿把两条未声明的批级 `raise` 放进了 per-query 循环，lane 自己的 §五 red-line #4 守卫（`test_no_undeclared_batch_level_raise_inside_an_item_loop`）因此转红 → **K3-R70**。行为今天没坏（同循环 `except` 把它收成 per-query drop），坏的是声明契约本身。**这一条只有全量包能发现**：4,980 tests 里唯一的红就是它，而直接消费改动符号的 130 个测试全绿——所以本刀交接时那句 `full-lane=NOT_VERIFIED` 正是漏掉它的原因。同轮更正一条历史假设：桌面清单说 `test_strict_pass2_approval_callsite_has_independent_load_bearing_control` 仍红，本次全量里它是绿的。

完整 Required / 复现 / 闭合判据的单一来源仍是 `docs/system_risk_register.md#R-USSHORT-KNIFE3-WEB-X-MERGE-PACKET-BOUNDARY`，本节不复述。**下一步不变**：K3-R31 / K3-R32（解冻链步骤 ④），之后才谈 K3-R34。

The earlier rule-3 invocation had no usable result at the time it was recorded. That statement is superseded by the K3-R70 repair update below; it remains here only as a historical account of why K3-R70 was found by independent review.

## K3-R70 repair update — 2026-07-28

The repair keeps model identity validation per query: a missing provider-served model produces `served_model_missing`, and a later different served model produces `served_model_changed`, both via `web._ProviderItemRejected`. They are recorded as exact `llm` drop-ledger rows; they are not added to the batch-level raise allowlist. Generic client failures still use `provider_response_dropped`.

The regression uses good replies before and after the two rejected replies. It proves the two siblings survive, checks both exact drop rows, and confirms that the retained identity is `grok-4.5` with the two accepted fingerprints. It was run with the fixed main Python together with the named lane per-item conformance probe: **44 OK**. `py_compile` and `git diff --check` passed.

The one required rule-3 command completed on this exact code state. The actual ledger result is **CACHED GREEN — 4981 OK at 2026-07-28T22:41:07**. This fixes K3-R70 pending independent review; it does not lift K3-R34, authorize any provider/key/network/live action, or begin K3-R31/K3-R32.

## 2026-07-28 追加：第三轮独立审查 **PASS** —— 解冻链 ② 至此闭合

K3-R70 按指定方向修好：两处改用 `web._ProviderItemRejected` + 具名 reason，专捕分支放在通用 `except` 之前，`DECLARED_BATCH_RAISES` 未被放宽（该测试文件零改动）。我自己的探针证明兄弟查询真的活着——四查询 good→missing→changed→good，两条好查询的 provider row 与 annotation 全保留，只掉 `served_model_missing:q2` 与 `served_model_changed:q3` 两行，收据留下的身份是 `grok-4.5` 加 `fp1,fp2`，被拒回复的指纹没有混进证据。挖空任一处 raise，具名测试 `test_live_x_model_identity_rejections_drop_only_the_affected_query` 转红（baseline 43 tests / 0 红）；曾经转红的 `LanePerItemConformance` 现在 2 OK；全量按 tiering rule 4 引用账本自身输出 `CACHED GREEN 4981 OK`，不重跑。

**至此 K3-R68 / K3-R69 / K3-R70 全部 CLOSED，X 侧「拿真实形状复审 live 半边」（解冻链 ②）闭合。** 下一步是 K3-R31 / K3-R32（步骤 ④），之后才谈 K3-R34 解冻。一条不阻断的 Optional：本次 K3-R70 修复轮没有对应的 `修复` SESSION_LOG 条目，跨轮记录靠 register 与本 handoff 兜住。

## Pre-Codex self-review

`matrix=complete; register=updated; handoff=updated; focused=44 OK (X orchestration + per-item conformance); full-lane=4981 OK (official ledger); no batch-level allowlist extension; no provider/key/network/live action.`
