# A-short Knife 11 handoff — crash-veto official rolling verdict

## Scope

Implemented the desktop roadmap Knife 11 / item 6 only. The crash-veto tracker now builds an `official_rolling` node from `official_all_crash_veto` cohorts using equal weighting by mature week. Member rows are never pooled across weeks.

`OFFICIAL_ROLLING_MIN_WEEKS = 3`. A week is mature only when both 5-day and 10-day horizons are ready and each has at least `DECISION_MIN_PAIRS`. Existing decision thresholds are reused; rolling horizon `paired_count`/`member_count` count mature weekly observations rather than inventing a stock-level count, while the per-week pair gate remains enforced before aggregation. The top-level decision set is legacy latest + incremental latest + official rolling, with existing insufficiency/change/keep precedence. Official rolling cohort IDs are included in `final_decision.basis_cohort_ids`.

Crash-veto rolling has no registered shared comparison track yet, so its gate is explicitly hard-wired to `pre_freeze_audit_only`; it never proxies another track's registry bit. A future freeze must be a reviewed unified switchover that registers and switches crash-veto itself. Pre-freeze output keeps both the rolling and top-level verdict at `insufficient_keep`; no EGS, M6.7, preset, sizing, or production rule changes occur. The un-gated synthetic verdict is retained as `unfrozen_decision` for audit evidence only.

## Consumer and schema

`schemas/a_short_crash_veto_tracking.schema.json` accepts the `official_rolling` node and its equal-weight horizon metrics. `build_summary` puts the official rolling text and basis into the existing `final_decision.plain_text`, so the unchanged weekly Markdown renderer carries the official rolling verdict and basis. The existing weekly consumer validates the updated schema and top-level `as_of`; no weekly decision-predicate/effect-contract file was changed.

## Focused proof

Fixed interpreter: `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe` (Python 3.13.8).

`python -m unittest tests.test_a_short_crash_veto_tracker -v` → `Ran 18 tests ... OK`.

The focused tests cover: one 340-member positive week plus two 20-member opposite weeks (weekly equal weighting; basis reaches weekly report/Markdown), weekly observation counts without synthetic stock-pair counts, one mature week blocked by the three-week gate, pre-freeze fail-closed insufficiency, schema validation, weekly consumer wiring, and unchanged comparison-only flags.

## Boundary

No provider call, data fetch, production rule change, commit, push, merge, or full-pack claim was made. Independent Claude Code review remains required before any integration action.

## 2026-08-01 Append: Knife 12 tightened three-cut implementation (Codex executor)

### Scope

- **12A′ shadow-only data quality**: `analysis_input.candidates[].data_quality` is preserved through `normalize_candidate` and consumed by a formal weekly `data_quality_shadow` comparison. The block/degrade/warn policy is observable only; `comparison_only=true` and `production_effect_enabled=false` are schema-bound, and no Phase5 action, star, shares, cash allocation, veto, or production threshold is changed. Malformed/duplicate weekly fixtures do not get pre-empted by the shadow; the existing weekly validator remains the owner of identity errors.
- **12B′ nature classification**: `schemas/a_short_m67_effect_contract.json` now classifies every one of the 371 `analysis_input` leaves through `leaf_nature_by_group`. The ledger exposes per-record `nature`/`leaf_natures` and a seven-value `nature_counts` summary. Nature/policy consistency rejects bulk relabeling of business leaves as display-only; `intentionally_independent` remains an explicit exception. `validate_effect_contract_ledger(..., previous_ledger=...)` provides the non-increasing `unavailable_manual_review` trend guard.
- **12C′ feasibility probe**: `engine/a_short_effect_consumer_probe.py` and its schema prove only three selected local AST chains: `has_crash_veto → negative_event`, `industry_trend → star`, and `data_quality.completeness_score → shadow verdict`. The probe records source hashes and is explicitly not a generic 371-leaf data-flow proof.

### Verification

Fixed interpreter only: `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe` (Python 3.13.8).

- Core 12A′/12B′/12C′/renderer pack: `Ran 65 tests ... OK`.
- Shared weekly pipeline regression: `Ran 515 tests ... OK`.
- Freeze/schema/analysis-input gates: `Ran 45 tests ... OK`; compatibility consumers: `Ran 36 tests ... OK`.
- `py_compile`, JSON Schema meta-check, and `git diff --check` passed.
- The freeze packet was not edited or resealed; no provider/network/full-pack execution occurred.

### Boundary and handoff

The 12B inventory still honestly labels unresolved business groups as `true_dangling`/`partial_consumption`; 12C proves feasibility for three chains only. Full A-short pack and independent reviewer PASS are `NOT_VERIFIED`. No commit, push, merge, freeze transition, or production activation was performed. Next owner: independent Claude Code review of the complete three-cut diff; after PASS, project flow decides submission.

## 2026-08-01 Append: Knife 12 anti-dangling machinery Required repair (Codex executor)
- The independent repair opinion did not include the later 291-leaf `true_dangling` wiring knife; this slice only makes the anti-dangling machinery load-bearing.
- Nature/runtime is bidirectional. `candidate_data_quality` now has a four-leaf `data_quality_shadow` comparison handler. `portfolio_concentration_factor_resonance` remains `partial_consumption` until split-and-wire.
- The weekly production path resolves the prior canonical ledger and records either a checked trend guard or an explicit `skipped_no_prior_ledger` bootstrap; rising unavailable counts fail closed.
- The weekly schema requires `data_quality_shadow`, and its validator rejects `None`; the shadow remains comparison-only and production-disabled.
- Fixed Python evidence: Required-focused `Ran 43 tests ... OK`; weekly pipeline `Ran 515 tests ... OK`; static/compile/schema/diff checks passed. No true-dangling wiring, freeze reseal, provider/network work, activation, commit, push, or merge.
- Next owner: independent Claude Code re-review; only after PASS may the user authorize a separate `true_dangling` wiring knife.

## 2026-08-01 追加：第十一刀独立审查（Claude Code，Pass-with-Required，未提交）

### 改了什么 / 为什么

- 本轮我不改代码，只审查。被审工作树 `D:\cnhea\Codex\worktrees\19d3\Stock`，改动函数只有三个新增符号 `_official_rolling_epoch_mode` / `_rolling_horizon` / `_build_official_rolling`，加上 `build_summary` 的 `decision_set` / `basis` / `final_plain` 段与 schema 的 `official_rolling` 节点。
- `runners/a_short_weekly_pipeline.py`、`runners/a_short_m67_render.py`、`tests/test_a_short_evidence_epoch_mode.py` 在 `git status` 里显示 modified 但 `git diff --numstat HEAD` 为空 —— 只是 CRLF churn，内容零改动。提交前应按字节归一成 LF，别把这三个文件的假 diff 带进 commit。

### 验证命令 / 验证结果

- `.tools\run_unittest_with_repo_pythonpath.cmd tests.test_a_short_crash_veto_tracker` → `Ran 18 tests in 4.8s / OK`，bounded `tier=focused status=PASS exit=0`。与执行方自报一致，为 reviewer 亲跑。按门禁 FAIL 坐实后未跑全量。
- reviewer 自写探针（scratchpad，不入库）补了 checked-in 测试缺的严格形态：legacy(245)+incremental(30) 同时在场且逐字段不变、只翻三个 official 周 outcome → 滚动裁决 `change_candidate`↔`keep`、顶层 `final_decision.status` 同步变、`basis_cohort_ids` 同时含三个 official 周 id 与两个 bootstrap id。桌面方案「只更新 variants 顶层不响应=FAIL」的条件不成立。
- 反向探针坐实 Required：临时 registry 里**只**把 `p0_factor_comparison_v2` 翻成 `frozen_enforced`、crash-veto 侧零决定 → `_official_rolling_epoch_mode()` 返回 `frozen_enforced`。

### 失效旧结论

- register 里「pending independent review」已被本轮 Pass-with-Required 取代；Codex SESSION_LOG 的「Knife 11 implementation complete」在冻结门这一项上不成立。
- 桌面方案点 4 说要「同步 `_validate_crash_veto_tracking_summary`」，实际不需要改码 —— 该函数是纯 schema 驱动，schema 加节点即生效。此项不算漏做。

### 下一步注意事项

- 只需修 `R-ASHORT-KNIFE11-ROLLING-FREEZE-GATE-PROXIES-UNRELATED-P0-TRACK` 一条 Required，Optional（滚动节点复用个股级 horizon schema、合成 `paired_count`）按惯例一并修合理，但不要为它改 `DECISION_MIN_PAIRS` 或上游 `mature` 过滤的语义。
- 选方案①（注册自己的轨）会动 `TRACKS` 与 `docs/a_short_evidence_epoch_mode_registry_20260725.json`，那是 7→8 轨的注册面变化，会牵动 epoch-mode 的既有测试；选方案②（硬钉 pre-freeze + 写明统一解冻入口）改动最小，也更贴桌面第 0 节。自己判，别两条都做。
- 现有正控不许退化：预冻结强证据仍 `insufficient_keep`、`unfrozen_decision` 仍是 audit-only、`comparison_only=true` / `affects_selection=false` / `production_rule_changed=false` 三个常量不许动。

## 2026-08-01 追加：第十一刀 Required + Optional 收口复审（Claude Code，PASS，已提交）

### 改了什么 / 为什么

- 本轮我不改代码，只复审并提交。Codex 采纳方案②：`_official_rolling_epoch_mode()` 直接返回 `pre_freeze_audit_only`，`OFFICIAL_ROLLING_MODE_TRACK` 与对 `engine.a_short_evidence_epoch_mode` 的 import 一并删除，函数注释写明「不属共享七轨、绝不代理别人的 registry bit、将来冻结须显式注册并切换本组件」。
- 顺带 Optional 也改了：`_rolling_horizon` 的 `paired_count`/`member_count` 改成真实成熟周数，形参更名 `official_week_count`；`decide_design` 加 keyword-only `minimum_pairs=DECISION_MIN_PAIRS`，滚动节点显式传 `0`，并在调用处注释说明「配对单位是周，别为了复用阈值伪造个股级配对数」。

### 验证命令 / 验证结果

- `.tools\run_unittest_with_repo_pythonpath.cmd tests.test_a_short_crash_veto_tracker` → `Ran 19 tests in 4.5s / OK`，bounded `tier=focused status=PASS exit=0`（上轮 18，本轮 +1 周观测计数用例）。reviewer 亲跑。
- reviewer 探针 16 项全过。堵死上轮那个洞：临时 registry 把**全部七轨**都翻 `frozen_enforced`，`_official_rolling_epoch_mode()` 仍返回 `pre_freeze_audit_only`；tracker 源码已无 `a_short_evidence_epoch_mode` 字样；完全不打桩的生产路径下三周强证据仍 `insufficient_keep`，而 `unfrozen_decision` 如实记 `change_candidate`。
- 放松类反向控制（`decide_design` 新增 `minimum_pairs`）：默认路径 19 对拒、20 对过；全模块只有滚动那一处传 `minimum_pairs`；把某周 `paired_count` 植成 19 → 该周被剔出 `basis_cohort_ids`、成熟周降到 2、裁决回落 `insufficient_keep`；三个 20 对周确实能出 `change_candidate`。反悬空链路（顶层 status 随 official 周翻转、basis 不挤掉 bootstrap）未回归，三种 summary 形态均过 schema。

### 失效旧结论

- 上一轮的 Pass-with-Required 与「冻结门借 P0」机制描述已作废，两条 R-ID 均 closed。
- 我上轮写的「提交前把三个 CRLF-churn 文件按字节归一成 LF」不必单独做：`git diff --numstat HEAD` 对它们为空，`git add -A` 不会把假 diff 带进 commit（本次提交实际只含 6 个真改动文件 + 本 handoff）。

### 下一步注意事项

- 本刀无待办。将来真要给 crash-veto 起时钟，唯一合法路径是统一 switchover：先在 `TRACKS` 与 `docs/a_short_evidence_epoch_mode_registry_20260725.json` 注册它自己的轨，再改 `_official_rolling_epoch_mode()` 去读自己的 mode；不许再回到读别人 mode 的写法。
- `decide_design(..., minimum_pairs=0)` 只对周级聚合合法。任何新调用点若想传非默认值，必须同时说明「配对单位是什么」并补一条 19/20 边界反向控制，否则就是把个股级样本门悄悄关掉。

## 2026-08-01 追加：第十二刀 12A′/12B′/12C′ 独立审查（Claude Code，FAIL，未提交）

### 改了什么 / 为什么

- 本轮我不改代码，只审查。被审改动：`engine/a_short_effect_contract.py`（新增 `_leaf_nature_map` / `leaf_natures` / `validate_unavailable_manual_review_trend`，改 `static_contract_error` / `build_effect_contract_ledger` / `validate_effect_contract_ledger`）、`runners/a_short_weekly_pipeline.py`（`normalize_candidate` 透传 `data_quality`、`build_weekly_report` 产 shadow、`validate_weekly_report` 校验 shadow）、`runners/a_short_m67_render.py`（新增 `_render_data_quality_shadow`、台账加 `nature_counts` 行）、两个 schema，加四个新文件（shadow 引擎+schema、consumer probe 引擎+schema）与两个新测试模块。
- 判 FAIL 的理由不是核心功能不对，而是**本刀新建的三样防悬空件自己没接到承重位**。这刀的全部价值就是把"登记为应影响结果、实际没接线"变成一份可信清单；清单能靠改标签变短、警报器没通电、新轨能无声消失，价值就不成立。

### 验证命令 / 验证结果

- `.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.test_a_short_weekly_pipeline tests.test_a_short_effect_contract tests.test_a_short_m67_render tests.test_a_short_data_quality_shadow tests.test_a_short_effect_consumer_probe` → `Ran 580 tests in 272.508s / OK`，bounded `tier=focused status=PASS exit=0 deadline=900s`。既有测试全绿——三条缺口正落在测试未覆盖处。申请 900s 上限的实测理由：该超集含 weekly pipeline 全模块，实测 272.5s，超 300s 默认档不安全。
- reviewer 自写探针（scratchpad，不入库）15 项。**通过的**：只改一只候选的 `data_quality`（block / degrade / warn / 非 dict 四种形态各一次），整份周报除 `data_quality_shadow` 外**逐字节相同**，且 shadow 节点确实变（探针非空洞）——checked-in 测试只比了 `操作`/`股数` 两个字段，这是桌面方案要求的严格形态；`leaf_natures()` 实测 371 叶且与 `analysis_input_paths()` 完全相等。**转红的**三条见 register。
- 静态核实：`runners/a_short_phase5_engine.py` 对 `data_quality` 零引用；`A-EGS/egs_main.py:1450` 那处读取是上游既有、本轮未改（该文件不在改动清单）。

### 失效旧结论

- Codex SESSION_LOG 的「12B′ Nature/policy consistency rejects bulk relabeling of business leaves」只对**改成展示类**成立；改成 `main_decision` 这一侧完全不设防，实测 `static_contract_error()` 返回 `None`。
- Codex handoff 的「`validate_effect_contract_ledger(..., previous_ledger=...)` provides the non-increasing trend guard」在生产路径上不成立——生产唯一调用点不传该参数。

### 下一步注意事项

- 三条 Required 是**同一类**，请一起修，别只修被点名的那一处：nature 必须和运行时接线状态交叉校验（不只和 policy）、趋势守护必须在生产周报里真跑、shadow 节点必须进 `required` 且 `None` 不再静默放行。
- 修 ① 时注意反向也要成立：`nature=true_dangling` 的组必须 `runtime_handler == unresolved_input_group`，否则接完线忘了改标签同样是假账。
- 修 ② 若拿不到上一份 ledger（首次发布、历史缺失），必须是显式且有理由的跳过并留痕，不能退回"默认 None 就不查"。
- **不要**为本刀重封冻结包。本轮改了 `weekly_report_schema` 与 `m67_effect_contract` 两个受钉契约，但预冻结期哈希门不比对（当前 8 项已有 6 项漂移而冻结 schema 测试仍绿）；提前重封会把这 6 项漂移一次性洗成新基线，跳过第 2 刀第 5 点要求的逐条 epoch 归属判断。Codex 本轮没重封是对的，保持。
- 用户已说明：本刀 PASS 后才授权执行剩余 `true_dangling` 接线刀。当前实测工作清单是 `true_dangling 291 叶 / partial_consumption 35 叶`（另 `main_decision 35 / display_audit 6 / comparison_track 4`，合计 371）。这个 291 就是后续每一刀的验收基准，所以①必须先堵死，否则基准可伪造。

## 2026-08-01 追加：第十二刀三条 Required 收口复审（Claude Code，PASS，已提交）

### 改了什么 / 为什么

- 本轮我不改代码，只复审并提交。三条 Required 都按类修，不是只堵被点名那一处：
  ① 新增 `_NATURE_RUNTIME_HANDLERS`，`static_contract_error()` 把 nature 与 `runtime_handler` **双向**绑死（不只绑 policy）；`candidate_data_quality` 拿到真 handler `data_quality_shadow`。
  ② 新增 `_load_previous_effect_contract_ledger()` / `_bind_effect_contract_trend_guard()` / `_validate_trend_guard_record()`，趋势结果作为 `trend_guard` 记录进 ledger 本体，绑定点 `write_weekly_report` / `publish_weekly_bundle` / `main()`，`validate_published_weekly_bundle` 再独立重解析一次。
  ③ `data_quality_shadow` 进 weekly schema `required`，`validate_data_quality_shadow(None)` 改为报错。

### 验证命令 / 验证结果

- `.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.test_a_short_weekly_pipeline tests.test_a_short_effect_contract tests.test_a_short_m67_render tests.test_a_short_data_quality_shadow tests.test_a_short_effect_consumer_probe` → `Ran 585 tests in 295.382s / OK`，bounded `tier=focused status=PASS exit=0 deadline=900s`。900s 上限的实测理由：该超集含 weekly pipeline 全模块，实测 295s，300s 默认档不安全。
- reviewer 探针 15 项全过，关键是**穷举而非抽样**：18 个未接线 `true_dangling` 组逐个改标 `main_decision` 全部被拒、零漏网；反向 4 个已接线组逐个改标 `true_dangling` 也全部被拒。趋势守护在临时 canonical 树里实测能真找到上一周（`checked` / `previous_as_of` 正确 / 22:22），且伪造 `checked`、上一份存在却谎报 `skipped`、真实计数上升（21→22）三种都被拒——第二种正是"退化成永远跳过"那条最可能的假修。缺 shadow 的周报被 schema 与 validator 双拒。comparison-only 隔离未回归。
- 另核实修复没有制造假进度：`true_dangling` 仍是 291 叶。6 个 `portfolio_concentration_factor_resonance` 叶由 `main_decision` 如实下调为 `partial_consumption`（新双向门下它没有真 handler），`main_decision` 35→29、`partial_consumption` 35→41，总数仍 371。

### 失效旧结论

- 上一轮 FAIL 的三条机制描述全部作废，两条 R-ID 均 closed。
- 我上一轮记的分布 `partial_consumption 35 / main_decision 35` 已过期，终态见上。

### 下一步注意事项

- 291 叶 `true_dangling` + 41 叶 `partial_consumption` 是后续接线刀的工作清单，且现在这个数字**改标签改不动**——nature 必须与 `runtime_handler` 对得上，接完线必须同时改标签、没接线就不许标成 `main_decision`。
- 接线刀每接一组，必须同时：给该组换上真 `runtime_handler`、在 `_NATURE_RUNTIME_HANDLERS[main_decision]` 里登记该 handler、把 nature 从 `true_dangling` 改成 `main_decision`、补 `proven_consumer_paths` 覆盖全部叶、补一条"只改该叶 → 主决策必须变"的正向变异测试。少任何一步都会被现有守护挡住或留下假账。
- `unavailable_manual_review` 现在只许降不许升，且首次发布的 `skipped_no_prior_ledger` 必须带理由。接线刀若拆组导致组数变化，注意该计数可能先升——那要么拆法有问题，要么需要用户显式批准一次基线重置，不许悄悄放宽守护。
- 仍**不要**为接线刀重封冻结包，理由同上一节。

## 2026-08-01 Append: candidate_derived_flags 接线刀（Codex executor）

- 用户已授权执行下一步；本轮按桌面路线先处理 `candidate_derived_flags`，不是一次性批量处理全部剩余叶。
- 8 个叶已接入：`chasing_high`、`hard_veto`、`has_crash_veto`、`is_lock`、`overheat_flag` → Phase5 风险族；`is_breakout` → entry 类型；`m4_review_required` → 新建仓观察/禁止门；`vol_confirm` → comparison-only 节点（不改变 Phase5 breakout）。
- `schemas/a_short_m67_effect_contract.json` 已拆成四组，均有真实 handler、完整 `proven_consumer_paths`、source hash；`static_contract_error() = None`。
- 固定 Python 3.13.8 验证：`Ran 27 tests ... OK`（effect contract）、`Ran 654 tests ... OK`（Phase5/weekly）、`Ran 22 tests ... OK`（consumer/data-quality/EGS）；full-pack=`NOT_VERIFIED`。
- 最新 nature 分布：`true_dangling 283 / partial_consumption 41 / main_decision 36 / comparison_track 5 / display_audit 6`，合计 371；较上一基线只减少本刀实际接入的 8 叶。
- 边界：未重封冻结包、未启用生产 block/degrade、未做 provider/network/DataHub、未 commit/push/merge。下一 owner：Claude Code 独立复审本刀完整 diff；PASS 后再授权下一组 `true_dangling` 接线。

## 2026-08-01 追加：candidate_derived_flags 接线刀独立审查（Claude Code，Pass-with-Required，未提交）

### 改了什么 / 为什么

- 本轮我不改代码，只审查。这是第 12 刀系列**第一把真改生产决策**的刀，按最高档验：改动符号为 `runners/a_short_phase5_engine.py` 的 `_m4_review_required` / `_derived_flag_comparison`（新增）+ `model_build_eligible` / `build_m67_report` / `build_holding_report`（改），`runners/a_short_weekly_pipeline.py::normalize_candidate` 的 `derived` 构造，加 effect contract 的四组拆分。
- 判 Pass-with-Required 不是因为接线错，而是因为台账对其中一叶的宣称超出事实。

### 验证命令 / 验证结果

- `.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 1100 tests.test_a_short_phase5_engine tests.test_a_short_weekly_pipeline tests.test_a_short_effect_contract tests.test_a_short_m67_render tests.test_a_short_data_quality_shadow tests.test_a_short_effect_consumer_probe` → `Ran 725 tests in 280.7s / OK`，bounded `tier=focused status=PASS exit=0 deadline=1100s`。
- reviewer 探针 11 项，三类都做了：**正向变异**只翻 `m4_review_required=true` → `建仓 → 观察`、触发条件含 `M4 升级审查未完成，禁止新建仓`、`observe_only` 含 `m4_review_required:升级审查`；**旧件字节等价**——缺键 / `null` / `false` 三者报告逐字节相同（该叶刻意不走 `fail_closed_risk_bool`，否则 `None` 会拦掉所有历史候选，这个取舍是对的且被证明没有副作用）；**fail-closed**——`0 / 1 / "" / "false" / "true" / [] / {} / 0.0` 八种畸形非空值全部拦成 `观察`；**comparison-only 反向控制**——翻 `vol_confirm` 只改 `machine.derived_flag_comparison`，整份报告其余逐字节不变，`vol_confirm` 没有偷偷回到 Phase5 突破门（#6-ii 设计意图保住）。
- 唯一转红的 M5：对 `A-EGS/egs_main.py` 做 AST 全量扫描，`m4_review_required` 的赋值点**只有一处且是 `Constant(value=None)`**，无任何可产出非空值的路径。

### 失效旧结论

- register 里「open P1，待 Claude Code 独立复审」已被本轮 Pass-with-Required 取代。
- handoff 与 SESSION_LOG 的「`m4_review_required` → 新建仓观察/禁止门」在字面上成立、在事实上误导：消费端建好了，生产端恒发 `None`，门永远打不着火。

### 下一步注意事项

- 只需修一条 Required，且**不要求现在去建 M4 生产者**——只要求台账别宣称它已生效：给该组补生产者现状披露，并让它的 ledger 状态不再走 `phase5_decision` 的通用 `_phase5_status`（那个只要 Phase5 跑过就报 `applied`）。本周无候选带非空 m4 标志时应为 `not_triggered` 加理由。
- 修的时候顺手把 Optional 一并做也合理：`machine.derived_flag_comparison` 补进 `schemas/a_short_m67_report.schema.json` 并 const-pin `comparison_only` / `production_effect_enabled`（现在 `machine` 没设 `additionalProperties`，靠默认放行，不受约束）。
- **这一类要形成惯例**：以后每接一叶，除了"变异测试能改主决策"，还要问一句"上游真的会发出这个值吗"。消费端先建、生产端未建是合法的，但必须在契约组里显式披露，否则 `true_dangling` 计数就会靠"接了打不着火的线"往下掉。
- 现有正控不许退化：缺键/null/false 三者字节等价、畸形非空值 fail-closed、`vol_confirm` 不进 Phase5 突破门。

## 2026-08-01 Append: M4 review gate producer disclosure/status repair（Codex executor）

- 修复 `R-ASHORT-KNIFE12-M4-REVIEW-GATE-WIRED-TO-A-CONSTANT-NULL-PRODUCER`，不创建 M4 生产者，不重封冻结包。
- `candidate_derived_flags_m4_review` 改用专用 `m4_review_gate` handler；contract 明确记录 `A-EGS/egs_main.py::m4_review_required` 当前恒发 `None`。真实 null-only 周报 ledger 为 `not_triggered`；测试/未来审查后的 `true` 才为 `applied`；畸形非空值为 `unavailable_manual_review`。
- report machine 新增只读 `m4_review_gate` 节点；M67 schema const-pin 其输入叶、producer status/ref，并 const-pin `derived_flag_comparison` 的 comparison-only 边界。AST 守卫钉住 EGS 唯一赋值仍为 `None`。
- 固定 Python 3.13.8：effect contract `Ran 31 tests ... OK`；Phase5/weekly/consumer/schema 回归 `Ran 676 tests in 48.897s ... OK`；静态契约、编译、Schema meta、diff check 通过；full-pack `NOT_VERIFIED`。
- 边界：未改 M4 生产逻辑、未启用生产 block/degrade、未做 provider/network/DataHub、未 commit/push/merge。下一 owner：Claude Code 独立复审本 Required/Optional 修复。

## 2026-08-01 追加：M4 生产者披露 Required + schema 绑定 Optional 收口复审（Claude Code，PASS，已提交）

### 改了什么 / 为什么

- 本轮我不改代码，只复审并提交。Required 按我的意思修的是**诚实**而不是去建 M4 生产者：该组从通用 `phase5_decision` 状态改走专属 `m4_review_gate` handler（`engine/a_short_effect_contract.py::_m4_review_status()`）；Phase5 每份报告新增 `machine.m4_review_gate` 观察节点；契约组新增 `producer_binding`，由 `static_contract_error()` 逐字段钉死。
- Optional 也一并做了：`derived_flag_comparison` 与 `m4_review_gate` 都写进 `schemas/a_short_m67_report.schema.json`，`additionalProperties=false` 且 const-pin `comparison_only` / `production_effect_enabled` / `producer_status` / `producer_ref`。

### 验证命令 / 验证结果

- `.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 1100 tests.test_a_short_phase5_engine tests.test_a_short_weekly_pipeline tests.test_a_short_effect_contract tests.test_a_short_m67_render tests.test_a_short_data_quality_shadow tests.test_a_short_effect_consumer_probe` → `Ran 729 tests in 298.7s / OK`，bounded `tier=focused status=PASS exit=0 deadline=1100s`。
- reviewer 探针 13 项全过。核心那条：**真实（恒 null）生产者下，该组 ledger 状态是 `not_triggered`、理由点名 constant-null，不再是 `applied`**；喂进一个真 `true` 才变 `applied`；`0 / 1 / "" / "true" / [] / {}` 六种畸形值全部 `unavailable_manual_review`。`producer_binding` 的四种攻击（改 status / 改 source_ref / 改 activation / 整个删掉）全被静态拒绝、零漏网。前提自失效守卫是真的：`tests/test_a_short_effect_contract.py::test_m4_producer_binding_is_explicit_and_currently_constant_null` 直接 AST 扫 `egs_main.py` 断言唯一赋值点是 `Constant(None)`，我独立复算同一事实（`sites=1`）；将来生产者一变该测试即红，强制重审披露。schema 侧我把 `production_effect_enabled` 篡改成 `true`，实测被 schema 拒。
- 上一轮三类正控未回归：门仍把 `建仓` 打成 `观察`、`null`/`false`/缺键三者逐字节相同、翻 `vol_confirm` 除比较节点外整份报告不变。

### 失效旧结论

- 上一轮 Pass-with-Required 的机制描述已作废，两条 R-ID 均 closed。
- 我上一轮写的「台账每周报 `applied`」只对修复前成立；现在恒 null 下是 `not_triggered`。

### 下一步注意事项

- **这个模式是后续接线刀的模板**：消费端先建、生产端未建是合法的，但必须做到三件事——① 给该组配自己的状态判据（不要蹭通用 `_phase5_status`，那个只要 Phase5 跑过就报 applied）；② 在契约里写 `producer_binding` 并由 `static_contract_error()` 钉死；③ 补一条 AST 守卫钉住「生产者现状」这个前提，前提一变就红。三件缺一，`true_dangling` 计数就会靠"接了打不着火的线"往下掉。
- `_m4_review_status()` 要求**每份报告**都带 `machine.m4_review_gate`，缺一个就整组 `unavailable_manual_review`。以后新增任何报告构造路径（候选/持仓之外的第三种）必须同步产出这两个观察节点，否则会被 `unavailable_manual_review 只降不升` 的趋势守护挡住发布。
- 仍未改 M4 生产逻辑、未重封冻结包、未启用生产 block/degrade。
