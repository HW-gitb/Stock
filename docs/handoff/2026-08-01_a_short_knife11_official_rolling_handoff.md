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
