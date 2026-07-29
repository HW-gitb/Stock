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

## 2026-07-28 conformance test-tier split

The K4b executable coverage and mutation-heavy closure matrix now execute from `tests/test_us_short_discovery_conformance_executable.py`. The original `tests/test_us_short_discovery_conformance.py` retains their plain helper bases for the static guard registry, so importing the static module does not collect either slow TestCase. This preserves every inherited test method and assertion without circular imports or double collection.

Collection evidence is `static=27` plus `executable=11`, the original 38 conformance tests. The bounded static package plus the moved K4b class ran `31 OK` in `17.036s`, below the 300-second focused limit. The required final US-short discovery run executed, rather than reusing the old cache: `Ran 4981 tests in 706.708s`, `OK`; the ledger recorded its new code fingerprint at `2026-07-28T23:27:39`.

This is test-structure only: no production code, assertion body, R70 guard, timeout policy, provider/key/network/live path, score effect, or K3-R34 freeze changed. The remaining technical work is still K3-R31/K3-R32 before any separate reconsideration of K3-R34.

## K3-R31/K3-R32 executor repair — 2026-07-28

The K3-R34 early live freeze remains first and unchanged; no provider client, credential, network request, or live run occurred. The future web path now reserves both Tavily and the reviewed maximum DeepSeek regroup capacity before its first paid Tavily request. Its dated budget ledger has per-query-scope reservations, so retrying the exact scope does not add planned calls.

For R32, only receipt-level `generated_at` is a retry clock. Web and X raw source payloads retain `fetched_at`, bind it in `content_sha256`, and a same-evidence retry reuses the source's first frozen fetch instant. A tampered receipt-source `fetched_at` is refused; a genuine retry with a new packet clock remains idempotent. Tests use private gitignored raw roots: an inspected historical default-root fixture (`2026-07-28T13:39:11Z`) lacked `fetched_at`, which correctly conflicts under the repaired contract rather than being silently treated as equivalent.

Fixed main Python focused pack:

```text
tests.provider.test_us_short_llm_theme_discovery_fetch_web
tests.provider.test_us_short_llm_theme_discovery_fetch_x_merge
tests.provider.test_us_short_llm_theme_discovery
tests.provider.test_us_short_llm_theme_discovery_offline_invariants
Ran 128 tests in 15.592s
OK
```

`py_compile` and `git diff --check` passed. One official full-pack-ledger invocation was made, but it returned no terminal test result; follow-up `full_pack_ledger.py check us_short` reported no cached green on this exact code state. Therefore `full-lane=NOT_VERIFIED`; do not rerun it in this executor turn and do not close K3-R31/K3-R32 or lift K3-R34. Independent review is next.

## K3-R71/K3-R72 recurrence repair — 2026-07-29

K3-R71 is repaired without widening `DECLARED_BATCH_RAISES`: reservation-ledger entries are projected in a comprehension, then malformed shape, duplicate scope and aggregate-count failures are rejected once outside the iteration. This keeps untrusted-item loop behavior separate from the system-boundary ledger failure contract and makes `LanePerItemConformance` green again.

K3-R72 is now a static AST ordering guard because K3-R34 correctly prevents execution of the future paid path. The guard requires `_reserve_live_web_provider_budgets` before `execute_live_web_orchestration`; its own test removes the reserve call and reinserts it after orchestration, then asserts an offender. The project rule added to `AGENTS.md` is deliberately predicate-based: a static conformance guard is a direct focused consumer when its AST/registry predicate intersects the changed symbol. It does not impose a filename-based test tax.

The same-class Optional dispositions are: raw frozen `fetched_at` after the current retry clock is now a per-source rejection; `publish_immutable_pair` requires an explicit keyword-only recursion policy; the active clock-stripping docstring now matches the code; and the non-persisted retry tests were renamed to the narrower property they actually prove while the persisted retry test proves a new packet clock preserves the first frozen source clock.

Focused main-Python evidence before the final test-only R72 helper strengthening: `fetch_web`, `fetch_x_merge`, policy/discovery and `LanePerItemConformance` = **120 OK / 12.167s**. The re-run then stopped before the target test body at an external `temporary_provider_directory` lock (`OSError 36`; lock mtime `2026-07-28T13:04:12Z`), so final focused status is **UNKNOWN**, not a code verdict. `py_compile` and `git diff --check` passed. The one scheduled read-only independent self-review returned PASS with no must-fix and ran no tests. A single official full-pack invocation returned no terminal test result and its ledger has no cached green for this code state; `full-lane=NOT_VERIFIED`, with no rerun. K3-R34 remains frozen and no provider/key/network/live action occurred. Next: independent review after the private-root lock is released.

## 2026-07-29 追加：K3-R31/K3-R32 独立审查 **FAIL** —— 解冻链 ④ 未闭合

判 **FAIL**，红点不在设计方向而在实现落点。这一刀的方向是对的：预算在第一笔付费 Tavily 之前一次性预留、同 query scope 的重试只加尝试次数不加计划调用（K3-R31 的闭合语句），`fetched_at` 回到冻结证据里并进 `content_sha256`、只留顶层 `generated_at` 当重试时钟（K3-R32 的闭合语句）。我另外核过三处不容易看出来的正确性：`_chunk_regroup_rows` 在 `len(chunks) > MAX_DEEPSEEK_REGROUP_CALLS` 时直接抛，所以按常量预留永远不会少留；`generated_at` 只出现在制品与 X 收据的**顶层**，去掉 `recursive` 不会误伤嵌套重试时钟；四个生产建包口全部 `persist_raw=True`，冻结路径覆盖了每个真实调用者。

**红的那条只有全量包能发现，焦点包 128 OK 对它是瞎的**——和 K3-R70 完全一样的盲区。`_reserve_provider_budget` 为了校验新的 `query_reservations` 开了一个 `for entry in reservations:` 循环，循环体里两条 `WebThemeDiscoveryError` 是未声明的批级 raise，令 lane 自己的 §五 red-line #4 守卫转红（`batch_raise_offenders`，`tests/test_us_short_discovery_conformance.py:587`）。官方账本在本代码态实跑：`Ran 4983 tests in 622.385s` / `FAILED (failures=1)`，4983 = 原 4981 加本刀两条新回归，所以除这一条外没有别的回归。第二条 Required 是我用植入对照挖出来的：K3-R31 的全部意义就是「先预留再花钱」，而这条路径被 K3-R34 冻着不可执行，静态断言是唯一可能的证明——现在那条断言只钉了「凭据在预留之前」，把预留整行移到 `execute_live_web_orchestration(` 之后它照样绿。

**全量账本边界**（本轮专门核过，因为上一轮交接停在「只有 prepare 没有结果」）：账本只记 PASS，`prepare` 每个 lane 只有一格且被下一次 `run` 覆盖。所以「有 prepare 没结果」不是含糊信号，它证明包跑过且没绿，但它既不区分 FAIL 与 TIMEOUT，也不保存失败内容；而下一次 `run` 会抹掉上一次的 prepare。另外 `run` 参数形状不对时只打印用法、返回 2、**不写 prepare**，等于完全不留痕。

完整 Required / 复现 / 闭合判据的单一来源仍是 `docs/system_risk_register.md#R-USSHORT-KNIFE3-WEB-X-MERGE-PACKET-BOUNDARY`（K3-R71 / K3-R72 及四条 Optional），本节不复述。**下一步**：修 K3-R71 / K3-R72 后再复审，K3-R34 在那之后才谈解冻。

## 2026-07-29 追加：K3-R71/K3-R72 复审 **PASS** —— 解冻链 ④ 至此闭合

判 **PASS**。K3-R71 走的是我给的首选修法：整个 `for entry in reservations:` 消失，改成 comprehension 投影 + 一条聚合条件在迭代外只抛一次；`_reserve_provider_budget` 现在 AST 上有 **0 个 For/While 节点**，守卫的谓词根本匹配不到它，`DECLARED_BATCH_RAISES` 一字未动——没有靠削守卫过关。等价性我自己探针逐条打过：账本缺 `query_reservations` / 非 list → `cannot prove retry scope`；非 dict 条目、非 str `query_sha256`、字符串或负 `call_count`、重复 scope、`sum != planned` → `live budget ledger is malformed`；同 scope 不同 `call_count` → `retry scope conflicts`；新 scope 超帽 → `budget exhausted: 25+1 > 25`。**重写成单条布尔表达式后最容易漏的两种形状**——不可哈希的 `query_sha256`（进 set comprehension）和非 int 的 `call_count`（进 `sum()`）——都收成 `WebThemeDiscoveryError` 而不是裸 TypeError，说明 `or` 的短路顺序摆对了。正面对照：同 scope 重试 ACCEPTED、`reservation_attempt_count=2`、`planned_provider_call_count` 仍是 2，正是 K3-R31 的闭合语句。

K3-R72 换成 AST 版 `_live_preflight_order_offenders`，并且在同一条测试里就地把 reserve 移到 orchestration 之后证明它会红。我按「守卫必须由外部挖空证明会死」另跑一遍：baseline `[]`、移到花钱之后 `['reserve must precede the first paid orchestration call']`、删掉 `['missing reserve-before-spend call']`。**同时核了它的 inline 对照不是假阳性**——锚点行 `fetched_now = outcome["fetched_at"]` 在 `run_web_fetch` 里真实存在，所以那个变异确实是「重排」而不是退化成「删除」。

四条 Optional：α 闭且没有过度收紧——把冻结 raw 篡改成 2099 后 `accepted_source_count=0`、`source_refs=[]`、掉 `immutable_raw_content_conflict`（上一轮是被原样采信），而把它改成**更早**的 06:00 仍被复用，没有重演 K3-R56；β 闭——`recursive` 变成无默认的 keyword-only，四个调用点（web ×2、capstone、policy 测试）全部显式传值；γ 闭；δ 记为覆盖迁移。

**全量由我按 rule 4 接管重跑**（执行方那轮因外部私有根锁 `OSError 36` 停在 UNKNOWN）：`Ran 4984 tests in 476.291s` / `OK` / `status=PASS exit=0 tests=4984`，已记账。4984 = 我 FAIL 轮的 4983 加一条新签名回归，说明曾经红的 `LanePerItemConformance` 已绿且别处没动。`state/us_short` 0 文件，全程无 provider / key / network / live 动作。

**至此 K3-R71 / K3-R72 CLOSED，K3-R31 / K3-R32 CLOSED，解冻链 ④ 闭合。** 剩下的只有步骤 ⑤ 解 K3-R34，需用户单独命令。
