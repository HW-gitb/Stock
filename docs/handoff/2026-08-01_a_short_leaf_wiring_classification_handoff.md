# A-short 371 叶重新分层交接

## Scope

本轮只依据当前工作树代码重新核对 Claude 的最新分层，范围是 A-short analysis_input 叶的“必须修复 / 应退役 / 需用户拍板 / 已有承重或非缺口”路由。未执行代码修复、未接线、未建生产者、未重封冻结包、未提交。

## Verdict / Action

- **必须修复**：M0.5 波动率觉醒链一组。生产端和消费端必须同时实现，不能把 `unknown`/`None` 常量接入决策。
- **应退役**：`candidates[].selection.cninfo_flag` 不进入 M6.7 决策；正式 CNINFO 权威为 `official_structured`，旧字段最多暂留审计。
- **需用户拍板**：`selection.entry_flag` 是否作为 M6.7 advisory；`cninfo_flag` 暂留审计还是连同 schema/producer 清理；是否新增节前窗口、regime explanation、`still_in_pool` 规格。
- **已承重/非缺口**：rank/tier 上游选择，board/exchange 身份范围，latest_trade_date PIT/价格契约，market_regime.status fallback，source/quote/account 的既有权威与血缘边界。

## Required

若授权执行，先完成 M0.5 觉醒链的 producer → state → Phase5/M6.7 consumer → 周报打印 → 正反变异闭环；不得将当前常量 `unknown`/`None` 伪装成已接线。`cninfo_flag` 不得与 `official_structured` 形成双权威。不得扩展到其他系统、provider、network、DataHub 或冻结包。

## Verify

- 固定解释器要求：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`。
- 本轮只读代码核对；没有运行测试，因此验证终态为 `NOT_VERIFIED`。
- 当前工作树在本轮之前已有 7 个未提交修改文件；本轮新增本 handoff 和 `SESSION_LOG` 记录后仍不得直接称可提交。

## Proof-of-use

- 当前 IV feed 产出 IV/HV/252 日分位，但没有 M0.5 觉醒状态、现金回收或觉醒联动消费。
- 当前 weekly/Phase5 没有读取 `selection.cninfo_flag` 或 `selection.entry_flag` 形成正式 M6.7 主决策；官方语义对象由 Phase5 的 `official_structured` 消费。

## Pre-Codex self-review

`classification=code-read`; `must_fix=M0.5 volatility awakening`; `retire=cninfo_flag`; `user_decisions=entry_flag/cninfo retention/new optional spec`; `full 371-leaf terminal proof=NOT_VERIFIED`; `tests=NOT_RUN`; `commit=NOT_PERFORMED`。

## Next

用户先拍板 `entry_flag` 的 advisory 处置以及 `cninfo_flag` 的审计保留/清理方式；随后另开独立接线工作树执行 M0.5 波动率觉醒链。

## 2026-08-02 M0.5 执行者交接（本工作树，未提交）

### Verdict / Action

- 已实现 M0.5 producer → state → weekly/Phase5 consumer → M6.7/现金分配/周报打印链；权威生产者是 schema `1.2.0` 的 IV feed，未另建 EGS/第二 IV 源。
- producer 判据：5 个此前连续 `<10` IV 分位日 + 下一日绝对 IV 上升 `>5` 个百分点触发；回到触发前基准 `±1` 个百分点的首个交易日解除；Rule3 显式输出 `normal/reduce_new_position_50pct/no_trade/unknown`。
- active 觉醒按 20% 收回可用现金与新增敞口上限；因当前账户契约没有同日卖出流水权威，flat candidate 在 active 状态 fail-closed 阻止重建，held 行只做管理提示。Phase5/M6.7 读取同一状态，不从占位值重算。

### Required

- 独立 reviewer 必须复核 M0.5 producer/consumer/source-binding、正反变异及 effect-contract 指纹后再决定 PASS；PASS 前不得 commit/merge。
- 不得把 EGS `market_context.volatility` 的 `None/unknown` 当作已接线；其非占位值若出现必须与 1.2.0 IV feed 完全一致，否则拒跑。第十四/十五刀及历史诊断、IV/价格修复仍未授权。

### Verify

- 固定 Python：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`。
- `tests.test_a_short_iv_feed_build` + `tests.test_a_short_phase5_engine` + `tests.test_a_short_effect_contract` + `tests.test_a_short_effect_consumer_probe`：`Ran 240 tests in 67.735s ... OK`。
- M0.5 weekly wiring/负向控制：`Ran 3 tests in 2.954s ... OK`；完整 `tests.test_a_short_weekly_pipeline`：`Ran 518 tests in 86.890s ... OK`；sidecar health：`Ran 39 tests in 9.112s ... OK`。371 叶全量终端双向变异和独立 reviewer PASS 仍 `NOT_VERIFIED`。

### Proof-of-use

- M0.5 状态被写入 `machine.iv_gate`，影响 Rule3 否决/减半；`awakening=active` 改变 `cash_allocation.available_cash_start` / `new_exposure_capacity_start`，并改变 flat candidate 的 M6.7 操作为否决；M6.7 波动率文案打印 Rule3、觉醒、现金回收。
- feed 写盘前会重算 series 状态并核验顶层 awakening；weekly 强制 IV 最新 trade_date 与价格 settled clock 对齐；analysis_input 非占位 M0.5 值与 feed 不一致会 fail-closed。

### Pre-Codex self-review

`scope=M0.5 only`; `producer=iv_feed_schema_1.2.0`; `consumer=weekly+phase5+m67+cash`; `second_authority=blocked`; `negative_controls=state_tamper/conflict/stale_input/invalid_active_cash`; `effect_contract=weekly hash updated`; `full_weekly=NOT_VERIFIED`; `371_leaf_terminal_proof=NOT_VERIFIED`; `independent-review=pending`; `commit=NOT_PERFORMED`。

### Next

Codex：继续固定 Python 跑完整 weekly 模块回归与 `git diff --check`，然后交 Claude Code 独立 reviewer；不要执行第十四/十五刀。

## 2026-08-02 M0.5 三项 Required 修复交接（未提交，待独立 reviewer）

### Verdict / Action

- 三项 M0.5 Required 已按类修复并闭合 producer → state → weekly/Phase5 → M6.7/现金分配/周报链；未扩展第十四/十五刀或 371 叶接线，未重封冻结包。
- 历史 effect-contract 采用登记 fingerprint 的 legacy-only 精确迁移；当前契约保持严格校验，未知/篡改 ledger 仍拒绝。觉醒状态机改为连续、互异交易日判据；active 采用显式 `conservative_degradation`，真实可分配现金为 0 并保留 20% 回收审计。

### Required

- Claude Code 必须独立复核三项 Required 的 source-binding、producer/consumer、写盘/消费链和负向控制；独立 PASS 前不得提交或合并。
- 不得把 `None`/`unknown` 常量伪装为已接线，不得切换 Option (b)，不得执行第十四/十五刀、历史诊断或 IV/价格修复。

### Verify

- 固定解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，`Python 3.13.8`。
- M0.5 producer/Phase5/weekly wiring：`Ran 192 tests in 9.451s ... OK`；effect-contract：`Ran 45 tests in 46.511s ... OK`；7 个下游消费者：`Ran 166 tests in 89.431s ... OK`。
- weekly 最新回归：`Ran 519 tests in 58.075s ... OK`；docs/route gates：`Ran 55 tests in 0.935s ... OK`；`py_compile OK 12`；`git diff --check` OK。
- 唯一完整 pack：`.tools/full_pack_ledger.py run a_short ... 900` → `RESULT status=PASS exit=0 tests=2244 elapsed=319.5s deadline=900s`。独立 reviewer 尚未完成，故本交接不称 PASS。

### Proof-of-use

- 旧 20260720/20260727 published bundle 在登记 fingerprint + 临时 current receipt 下可通过正式校验，未知/篡改仍拒；缺交易日/重复日期不产生单日 jump/awakening。
- active awakening 的 allocator 实际 start/remaining 为 0，M6.7/Markdown 明示「本周不新建仓」，并保留 pre/reclaimed/post 现金回收审计；Rule3 阈值从 reviewed runtime policy 单一读取。

### Pre-Codex self-review

`matrix=complete: M0.5 three Required`; `register=updated`; `handoff=updated`; `focused=192+45+166 OK`; `full-lane=RESULT status=PASS exit=0 tests=2244 elapsed=319.5s deadline=900s`; `door=doc-governance + route-ledger: Ran 55 tests in 0.926s ... OK`; `freeze-packet=untouched`; `independent-review=pending`; `commit=NOT_PERFORMED`。

### Next

Claude Code：独立 reviewer 复核本轮 M0.5 三项 Required；PASS 后再按项目流程提交/合并。

## 2026-08-02 M0.5 第二轮 Required 修复交接（未提交，待独立 reviewer）

### Verdict / Action

- 已修复休市日交易日历代理与 legacy fingerprint 旁路过宽两项新 Required；范围仍只在 M0.5，不执行第十四/十五刀、371 叶接线、历史诊断或 IV/价格修复，不重封冻结包。
- IV producer 现在从同一次 `trade_cal` probe 接收 `trade_calendar`；单日 delta 与五日窗口共用交易日索引相邻判据。休市日可跨越，真实开市日缺 IV 不触发，日历不可得写明 `calendar_unavailable`。
- legacy 兼容要求 weekly schema `1.0.0` + 已登记 fingerprint；旧形状只跳过不存在的 M0.5 键，现代语义与安全检查永远执行。登记表已纳入静态哈希，并逐条核对本地 Git 历史快照。

### Required

- 独立 reviewer 必须复核本轮 source-binding、calendar unavailable、legacy 版本绑定、历史快照校验与反向控制；独立 PASS 前不得提交或合并。
- `schemas/a_short_m67_effect_contract_legacy_migrations.json` 当前为新增未跟踪文件，必须由 reviewer/committer 在通过后纳入提交；本轮不自行 stage/commit。

### Verify

- 固定解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`。
- `test_a_short_iv_feed_build` `Ran 46 tests ... OK`；Phase5 `Ran 146 tests ... OK`；effect-contract `Ran 47 tests ... OK`；weekly pipeline `Ran 519 tests ... OK`；official-operation `Ran 15 tests ... OK`；IV probe/probe-execution `Ran 55 tests ... OK`。
- `static_contract_error=None`、`py_compile`、`git diff --check` 已通过；`.tools/full_pack_ledger.py run a_short` `RESULT status=PASS exit=0 tests=2251 elapsed=317.0s deadline=900s`；文档/路由 `Ran 55 tests ... OK`；独立 reviewer 仍 `NOT_VERIFIED`。

### Proof-of-use

- 休市窗口与真实开市缺 IV 的同构序列得到 active/no-trigger 分离；calendar 缺失在 feed 顶层可见且不触发。
- 现代 active M0.5 报告在 `allow_legacy_m05=True` 与 `False` 都拒绝安全语义篡改；旧 20260720/20260727 bundle 仍通过正式 publish/operation 校验。

### Pre-Codex self-review

`scope=M0.5 second-round Required`; `calendar=trade_cal bound`; `legacy=version+fingerprint+git snapshot`; `schema=m05 enum/conditional guard`; `register=updated`; `handoff=updated`; `focused=46+146+47+519+15+55 OK`; `full-lane=PASS 2251/317.0s`; `docs-route=55 OK`; `freeze-packet=untouched`; `independent-review=pending`; `commit=NOT_PERFORMED`。

### Next

Codex：收口文档门并跑固定 Python 全包；随后交 Claude Code 独立 reviewer，不要提交或合并。

## 2026-08-02 M0.5 第三轮日历绑定 Required 修复交接（未提交，待独立 reviewer）

### Verdict / Action

- 已修复交易日历不受校验、1.2.0 重算从被验 summary 自取日历、weekly 读侧未跑 IV schema 三项缺口；不返工前两轮已闭 Required，不执行第十四/十五刀、371 叶接线、历史诊断或 IV/价格修复，不重封冻结包。
- producer 现在记录逐日探测清单；feed calendar envelope 绑定 source、coverage、count、日期哈希及 probe 哈希。重算使用外部 `trade_calendar` 或 probe binding，不直接使用被验 `calendar.trade_dates`；source 枚举与 as_of 上界一并收紧。
- weekly `validate_weekly_report` 和 CLI `--iv-feed` 入口统一走 `validate_feed_artifact`（schema + binding consistency）。

### Required

- 独立 reviewer 必须复核 calendar source-binding、删除/插入/未来日期反向控制、schema 读门和生产写盘边界；独立 PASS 前不得提交或合并。

### Verify

- 固定解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`。
- 当前 focused 超集：`Ran 917 tests in 143.744s ... OK`；IV feed `Ran 52 tests ... OK`；weekly `Ran 520 tests ... OK`；probe/probe-execution `Ran 55 tests ... OK`；其他直接 IV 消费回归包含在超集中。
- `.tools/full_pack_ledger.py run a_short` `RESULT status=PASS exit=0 tests=2258 elapsed=312.7s deadline=900s`；`static_contract_error=None`、`py_compile`、`git diff --check` 已通过；文档/路由 `Ran 55 tests ... OK`；独立 reviewer 仍 `NOT_VERIFIED`。

### Proof-of-use

- 日历删真实开市日、插入非交易日、外部窗口不一致、未来日期、哈希/条数/边界不一致及 7 位日期均拒绝；真实休市跨越、真实开市缺 IV、无日历 fail-closed 正控保留。

### Pre-Codex self-review

`scope=R-ASHORT-M05-CALENDAR-IS-AN-UNVERIFIED-INPUT-INSIDE-THE-RECOMPUTE-BOUNDARY`; `producer=trade_cal + probe-date binding`; `consumer=write_feed + weekly validate + --iv-feed`; `schema=calendar metadata/hash/source + strict dates`; `register=updated`; `handoff=updated`; `focused=917 OK`; `full-lane=PASS 2258/312.7s`; `door=docs+route 55 OK`; `freeze-packet=untouched`; `independent-review=pending`; `commit=NOT_PERFORMED`。

### Next

Codex：固定 Python 收口 full-pack 与 docs/route 门；随后交 Claude Code 独立 reviewer，不要提交或合并。

## 2026-08-02 M0.5 第五轮 schema-version 内容绑定 Required 修复（未提交，待独立 reviewer）

### Verdict / Action

- 已修复 `R-ASHORT-M05-SELF-DECLARED-SCHEMA-VERSION-SKIPS-THE-WHOLE-M05-RECOMPUTE`：IV feed validator、schema、`latest_m05_state` 消费端均按实际内容判定；1.2.0 形状不可把版本自改成 1.1.0 来跳过重算。
- 只处理本条 M0.5 Required；不返工前三轮已闭项，不执行第十四/十五刀、371 叶接线、历史诊断或 IV/价格修复，不重封冻结包。日历/probe 同源 Optional 仍单独记为 P2，未建新 provider/生产者。

### Required

- 只要 feed 携带 `calendar`、`awakening` 或任一逐行 M0.5 字段，1.1.0/缺失版本均 fail-closed；真正 legacy 1.1.0 必须无这些字段。
- `validated_m05_series()` 先跑 schema + binding；`latest_m05_state()` 对合法 legacy 只返回全 `None`，对伪造/未验证 artifact 不返回可用 M0.5 状态。
- 独立 reviewer 必须复核版本降级、schema 直接读门、legacy 正控与 weekly 消费链；PASS 前不得提交/合并。

### Verify

- 固定解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，`Python 3.13.8`。
- IV feed + M0.5 reverse controls：`Ran 60 tests in 6.704s ... OK`；完整 weekly pipeline：`Ran 521 tests in 53.444s ... OK`。
- `static_contract_error=None`，weekly decision predicate fingerprint 未漂移；`py_compile`、`git diff --check` OK；focused 超集 `Ran 921 tests in 122.264s ... OK`；`.tools/full_pack_ledger.py run a_short` → `RESULT status=PASS exit=0 tests=2262 elapsed=283.9s deadline=900s`；docs-route `Ran 55 tests in 0.788s ... OK`；独立 reviewer `NOT_VERIFIED`。

### Proof-of-use

- 同一 1.2.0 形状仅改 `schema_version` 为 1.1.0，保留/篡改 active 或 inactive、calendar/awakening，consistency 与 schema 读门均拒绝。
- 真 legacy 1.1.0（移除 calendar、awakening、逐行 M0.5 字段）仍可被读取，但 `latest_m05_state()` 不提供可用状态，weekly 既有兼容回归保持绿。

### Pre-Codex self-review

`scope=M0.5 schema-version content gate`; `producer=unchanged`; `validator=content+schema`; `consumer=validated_m05_series→latest_m05_state`; `reverse=60 OK`; `weekly=521 OK`; `matrix=complete`; `register=updated`; `handoff=updated`; `focused=921 OK`; `full-lane=2262 OK`; `door=docs-route 55 OK + static/compile/diff OK`; `effect_contract=static_contract_error None`; `reviewer=pending`; `commit=NOT_PERFORMED`。

### Next

Claude Code：独立 reviewer 复核本轮 M0.5 Required；PASS 前不得提交/合并。

## 2026-08-02 M0.5 第六轮日历独立日期对账全修交接（未提交，待独立 reviewer）

### Verdict / Action

- 已完成 `R-ASHORT-M05-CALENDAR-IS-AN-UNVERIFIED-INPUT-INSIDE-THE-RECOMPUTE-BOUNDARY` 的代码级全修：现有 `fund_daily` PIT 日期作为独立 producer fact 写入 IV feed，生产 source 为 `tushare.trade_cal+fund_daily`；validator/schema/写盘门均做独立日期、窗口、哈希和外部输入对账，M0.5 重算使用独立日期窗口。
- 不新增 provider/生产者，不重封冻结包；不执行第十四/十五刀、371 叶接线、历史诊断或 IV/价格修复。

### Required

- 独立 reviewer 必须复核 combined source 的 schema 条件、fund_daily 日期驱动重算、删除/插入/未来/哈希/外部错配反向控制与生产写盘边界；独立 PASS 前不得提交或合并。
- provider 现实完整性仍是 `NOT_VERIFIED` 数据源审计边界，不把同一 Tushare provider 的独立 endpoint 夸大为交易所签名证明。

### Verify

- 固定解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`。
- IV/probe `Ran 84 tests ... OK`；focused 超集 `Ran 926 tests ... OK`；`.tools/full_pack_ledger.py run a_short` → `RESULT status=PASS exit=0 tests=2267 elapsed=306.3s deadline=900s`（fingerprint `557e5bd9550a`）；`py_compile`、schema JSON、`static_contract_error=None`、`git diff --check` 已通过；docs-route `Ran 55 tests in 0.923s ... OK`；独立 reviewer `NOT_VERIFIED`。

### Proof-of-use

- `fund_daily` 日期缺口、非交易日插入、独立窗口/哈希/外部独立日期错配与 combined source 缺绑定均 fail-closed；重算不再把 `calendar.trade_dates` 当唯一真值；旧 `tushare.trade_cal` 合成 fixture 继续可读但不冒充新生产 source。

### Pre-Codex self-review

`scope=R-ASHORT-M05-CALENDAR... full code-level repair`; `producer=trade_cal + fund_daily`; `consumer=write_feed + weekly validate + --iv-feed`; `schema=combined-source independent binding`; `register=updated`; `handoff=updated`; `focused=926 OK`; `full-lane=2267 OK`; `door=py_compile+schema+static_contract+diff OK + docs-route=55 OK (0.923s)`; `freeze-packet=untouched`; `independent-review=pending`; `commit=NOT_PERFORMED`。

### Next

Claude Code：独立 reviewer 复核本轮 M0.5 日历全修；PASS 前不得提交/合并。

## 2026-08-02 M0.5 adjacency predicate 性能修复交接（未提交，待独立 reviewer）

### 改了什么

- 修复 `R-ASHORT-M05-ADJACENCY-PREDICATE-IS-QUADRATIC-AND-BLEW-UP-THE-WHOLE-LANE`：`build_m05_state()` 在进入热循环前从已规范化的交易日历建立一次 session-position index，并把同一 index 传给单日 IV delta 与五观察 awakening window 的共享 `_feed_dates_are_adjacent()`。
- 直接调用且未提供私有预计算 index 的旧路径仍自行规范化；缺日历、非法日期、倒序和真实开市缺 IV 的 fail-closed 语义不变。没有改阈值、schema、source binding、M6.7/现金语义、provider 或冻结包。

### 为什么

旧谓词每次调用都重做列表化/日期扫描/排序和位置字典；`build_m05_state()` 对每行及窗口重复调用，典型日历长度与 IV 行数接近时是平方级成本，可能拖垮 weekly lane。该修复只消除重复索引构建，不改变相邻判据。

### 验证命令与结果

- 固定 `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`（`Python 3.13.8`）；A-short preflight `status=pass`。
- 新增回归 `M05StateTests.test_state_machine_builds_calendar_lookup_once`：修复前 `0 != 1`，修复后 `Ran 1 test ... OK`；IV/M0.5 模块 `Ran 61 tests in 4.394s ... OK`，并通过 fallback/precomputed 一致性反控。
- 直接受影响的 weekly consumer `Ran 521 tests in 62.383s ... OK`（bounded 600s）；docs/route guards `Ran 55 tests ... OK`；`py_compile` 与 `git diff --check` OK。
- AGENTS rule 3 full-lane 未触发（无 top-level runner/shared engine/schema/provider/auth surface，聚焦包可界定影响），因此 full-lane `NOT_VERIFIED / not run`；独立 reviewer 尚未完成，不能称 PASS。

### 失效旧结论

「每次 adjacency 调用都需要重新规范化并建立位置字典」已失效；现在同一 M0.5 state build 只建立一次 canonical index。日期语义和历史兼容 fallback 没有改变。

### 下一步注意事项

- Claude Code 只需复核本条 diff、反向日期控制和 60+521 focused 证据；PASS 前不得提交或合并。
- 不要把本条性能修复扩大为第十四/十五刀、371 叶接线、历史诊断或 IV/价格修复；full-pack 继续保持 `NOT_VERIFIED`。

## 2026-08-02 追加：IV feed realized-window 判据修复 + 三处读点归一（Claude Code 审查 PASS，已提交并合入 master）

### 改了什么

- `runners/a_short_iv_feed_build.py`：combined source 分支不再要求 `trade_cal` 与 `fund_daily` 在整个日历窗口逐项相等。改为以 `realized_end = independent[-1]` 切窗——`realized_calendar`（日历中 ≤ realized_end 的日期）必须逐项等于 `realized_independent`（independent 中落在 `[calendar[0], realized_end]` 的日期），空集与 `realized_end > calendar[-1]` 均拒；`(realized_end, as_of]` 的未实现尾巴不参与等值、也不进 M0.5 重算（`trusted_calendar` 只取 `realized_calendar`）。新增两条 series 腿：任一 `trade_date > realized_end` 拒、非空 series 末根必须等于 `realized_end`。删除 `:717-718` 外部日历与 fund_daily 窗口的同类跨源等值。新增 `_realized_window_mismatch_message()` 输出脱敏可诊断事实（两侧计数、对称差前后各 3 个、`realized_end`、`as_of`）。
- `tests/test_a_short_iv_feed_build.py`：`_independent_bound_summary()` 由「三参同一份列表」改为真实不等两源（日历含未实现尾巴、independent 与 series 止于前一根），`assertEqual` 反转为 `assertNotEqual`，并加尾巴不影响 M0.5、series 越界拒、series 末根不匹配拒三条。
- `runners/a_short_regime_comparison_runner.py` / `runners/a_short_weekly_sidecar_health.py`：两处读点由「自取 schema + `validate_feed_summary_consistency`」归一到中央入口 `validate_feed_artifact`，删除 `IV_FEED_SCHEMA_PATH`；各配一条 patch 中央入口的路由测试。

### 为什么改

`trade_cal(is_open=1, end_date=as_of)` 是**前瞻发布**的交易所日历，canonical `as_of` 恒为尚未开盘的下周一；`fund_daily` 是**已实现**观测，末根只能到上一交易日。原判据要求两者逐项相等，数学上不可满足，导致 `write_feed` 每次 canonical 周跑必然抛 `trade_cal 与 fund_daily 交易日窗口不一致` → M6.7 不跑 → 整周无周报、持仓止损/减仓提醒一并消失（桌面实盘记录 `a_cc_testrun1.md` 第 1 条，`exit 22`）。

### 验证命令

- `.tools\full_pack_ledger.py run a_short "<trigger>" "<focused>" 860 -- discover -s tests -p test_a_short*.py`（固定主 Python 3.13.8）。
- reviewer 自写探针两份（scratchpad，未入库）：生产形态复现 + 七条反向控制。

### 验证结果

- 最终代码态全量 `RESULT status=PASS exit=0 tests=2274 elapsed=333.6s deadline=860s`；`2269→2274` 的 `+5` 恰等于本刀五个新用例。首轮 `PASS 2272 / 350.7s` 因执行方在其末段又落三处读点共 4 个文件，被 ledger 判 `code state changed` 不予记账，故按最终态重跑一次。
- reviewer 探针 13 条全绿：生产形态（未实现尾巴）经 schema + consistency 两道门放行；realized 窗内删真实开市日、插幻影日、`realized_end` 越出覆盖、realized 列表冒充外部前瞻日历、截断 independent 并重算 sha 五路仍全拒；诚实外部前瞻日历放行；含幻影尾巴与无尾巴两份产物的 M0.5 七字段逐字段相同。

### 失效旧结论

- 「`trade_cal` 与 `fund_daily` 必须在日历窗口内逐项相等」已失效，且其测试断言（`independent_trade_dates == trade_dates`）本身就是该门恒真、真实数据一撞即死的漏检根因。
- 「四个 IV 读点各自拼 schema + consistency」已失效：现统一走 `validate_feed_artifact`；`IV_FEED_SCHEMA_PATH` 零残留。

### 下一步注意事项

- 未实现尾巴只是**不参与等值**，它仍受 `≤ as_of` 与哈希/条数约束，且被排除在 `trusted_calendar` 之外；任何人不得把尾巴喂进 M0.5 邻接。
- 新增的 `series[-1] == realized_end` 与 builder 的可用日定义不同源（`_observed_trade_dates` 不看 close，`build_daily_iv` 要求 close 为正且当日有可用期权行），fund_daily 有行而当日 IV 不可解时会再次整体挡死写盘——记为 register 的不阻断 Optional，不要当已闭。
- 真实 `--as-of 20260803` 的 provider 跑仍未执行（需用户授权），本次闭合只到离线证据层。

## 2026-08-02 追加：Codex executor 当前工作树交接（代码已提交并合并；本节交接文档未提交）

### 作用与范围

本节记录当前 `D:\cnhea\Codex\worktrees\0d46\Stock` 工作树的真实执行状态，作为下一位 reviewer 的接手边界；不改写上方历史条目。第一、二刀代码已在当前 `master` 提交并合并，本节只记录本轮执行证据和新增的交接文档状态。

### 改了什么

- 保留 producer 侧 combined-source realized-window 修复：`trade_cal` 的前瞻尾巴不参与 realized 等值或 M0.5 邻接，`series` 不得越过 `fund_daily` 的 realized end，诊断信息保留脱敏窗口事实。
- 将 `runners/a_short_regime_comparison_runner.py` 与 `runners/a_short_weekly_sidecar_health.py` 的 IV 读点统一接入 `validate_feed_artifact`；weekly pipeline 已有中央入口，未重复改动。
- 新增两个消费者中央入口委托测试；第一刀的 realized-window 正反控制继续保留。

### 为什么

避免不同 IV 消费者各自复制 schema/consistency 组合，从而在 producer 修复后继续保留旧的跨源等值假设；同时保留 fail-closed、source binding、hash、未来日期和 provider failure 负向门。

### 验证命令与结果

- 固定解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，`Python 3.13.8`。
- `test_a_short_iv_feed_build.py`：`Ran 64 tests in 4.593s ... OK`。
- `test_a_short_regime_comparison_runner.py`：`Ran 43 tests in 27.630s ... OK`。
- `test_a_short_weekly_sidecar_health.py`：`Ran 40 tests in 9.188s ... OK`。
- `git diff --check` 退出码 0；仅有既有 Git ignore 权限和 LF/CRLF 提示。
- 本次 session 未重跑 provider/live fetch 或 full-lane；既有合并前 review/full-lane 证据保留在前述交接与当前 `HEAD`。本次未新增 code commit、push 或 merge；代码合并已由既有提交完成。

### 失效旧结论

- 第一、二刀代码的“已审查/已合并”状态已由当前 `HEAD` 与用户确认；当前未提交的只有本节交接及 `SESSION_LOG.md` 的新增记录。
- “第三刀”没有额外独立代码范围：原方案的 producer/source-binding 与消费者中央入口已覆盖；剩余是 review/真实运行验收，不是重复代码刀。

### 下一步注意事项

- reviewer/committer 只需按正常流程审查并处理本节交接与 `SESSION_LOG.md` 的新增落盘；不得为此重复打开已合并的代码刀，也不得覆盖无关改动。
- 真实 `--as-of 20260803` provider 验证仍需单独明确授权；没有该授权继续保持 offline `NOT_VERIFIED`。
- `fund_daily` 有行但 builder 当日 IV 不可解时的 realized-end 语义 Optional 仍未关闭，不得在本轮交接中写成已解决。

## 2026-08-02 追加：第二个漏洞修复后的真实两源窗口验证

### 文档作用与范围

本节是同阶段 handoff 的真实运行收口：把“等值门未经真实两源窗口验证即合入”从离线证据边界推进到一个可复核的真实 `--as-of 20260803` 运行证据，并把未执行的 comparison-only 旁路明确留为 `NOT_VERIFIED`。它不改变已合并代码、不替代独立 reviewer，也不把本轮 observation-only 周报写成 ship-gate 或实盘下单许可。

### 实际执行

- 当前工作树：`D:\cnhea\Codex\worktrees\0d46\Stock`；HEAD `aad87681`；使用唯一授权解释器 `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`（`Python 3.13.8`）。
- IV feed：`a_short_iv_feed_build.py --as-of 20260803 --out research/results/a_short/iv_feed_20260803/iv_feed.json --failure-receipt-out research/results/a_short/20260803/iv_feed_failure_codex_validation.json --confirm-fetch-authorized`。
- 为使当前工作树拥有同一周的 M6.7 输入，执行 EGS：`egs_main.py --as-of 20260803 --price-as-of 20260731 --l3-mode today --cache-policy enabled`。
- M6.7：使用当前工作树的 `result/a_short/20260803/analysis_input.json`、`research/results/a_short/iv_feed_20260803/iv_feed.json` 和同一 as-of overlay，`run-date=20260802`、`price-as-of=20260731`、`price-freshness-mode=intraday_prior_settled`、`--confirm-fetch-authorized`、无账户且 `--skip-ratchet`。
- 未执行整个 `weekly_screening.ps1`，也未执行 canary、forward tracker、crash-veto、regime comparison bootstrap 或自动交易；这些不是本次 producer/write-door 验证的必要范围。

### 真实证据

- IV builder 真实终端：`fetch rows(basic/daily/underlier)=12000/181232/336`；`trade_dates_probed=282/282`；`retry_recovered=0`；`opt_daily_fail_fast=False`；`had_provider_error=False`；`n_days=281`；`latest_iv_pct=74.2063`；exit code `0`，并成功写盘。
- 写入的 feed 是 schema `a_short_iv_feed/1.2.0`、`as_of=20260803`。`calendar.source=tushare.trade_cal+fund_daily`；前瞻 `calendar.trade_dates` 共 282 天，`20250609..20260803`；`probed_trade_dates` 同源 282 天且同 digest；独立 `fund_daily` 窗口共 336 天，`20250317..20260731`，digest 与前瞻日历不同；`series` 共 281 行，`20250609..20260731`。这是真实不相等两源窗口，且 `20260803` 尾巴没有被伪装成已实现观测。
- EGS 真实终端 exit code `0`，生成当前工作树的 `analysis_input.json`、`snapshot.json`、`candidates.csv`、overlay 和官方 marker。
- M6.7 真实终端 exit code `0`：`n=15`、`iv_pct=74.2063`；receipt 为 `stage_status=complete`，`as_of=20260803`、`run_date=20260802`、`price_data_through=20260731`；lineage 绑定 `research/results/a_short/iv_feed_20260803/iv_feed.json`，`iv_freshness={iv_data_through: 20260731, price_data_through: 20260731, status: aligned}`；M6.7 与 receipt 的 `run_id` / `candidate_digest` 一致。
- 产物 digest：IV feed `fb42f6ad1319bb6542e46e607f5b1a55fcae16366bf80c12b81bb402fadbcab4`；`weekly_m67.json` `133d6b1fb478f3e78335755bc27c47eb1a656b584bb337d399c5f3f01d0971de`。

### 结论边界

- 第二个漏洞的缺口——“没有用真实、不相等的 `trade_cal` / `fund_daily` 窗口验证新门”——本轮已有真实运行证据补齐；不能再把该缺口写成“未跑过”。
- 这不是 ship-gate PASS，也不是实盘下单测试：M6.7 产物明确 `production=false`、`real_money=false`、`satisfies_ship_gate=false`，本轮没有账户、持仓或订单。
- comparison-only regime 的独立真实 CLI 仍为 `NOT_VERIFIED`：当前工作树没有既有 regime ledger，首跑需要另行授权的 252 日 bootstrap；sidecar health 的真实 launcher manifest 也未生成。已有当前代码 focused evidence `test_a_short_iv_feed_build.py` `Ran 64 tests ... OK`、regime consumer `Ran 43 tests ... OK`、sidecar health `Ran 40 tests ... OK` 保留为离线证据。
- `fund_daily` 有行但 builder 当日 IV 不可解时的 realized-end 语义 Optional 仍未关闭；本轮真实成功不覆盖该 Optional。

### 交接事项

- 本节交给下一位 reviewer/committer 复核真实产物与文档绑定；不要从另一工作树采纳 Claude 的失败产物作为成功证据。
- 本轮新生成的 `research/results/a_short/20260803/weekly_m67.json`、`weekly_m67.md`、`weekly_m67.receipt.json` 和 `research/results/a_short/iv_feed_20260803/iv_feed.json` 当前保持未跟踪；本轮未提交、未 push、未 merge。

## 2026-08-02 追加：桌面第 3 条融资融券覆盖空基数修复

### 文档作用与范围

本节把桌面清单第 3 条 `margin_coverage` 的代码修复、真实本地缓存重算和未刷新产物边界交给下一位 reviewer。它只覆盖 A-short EGS 融资融券覆盖判定；不覆盖桌面第 4-8 条，也不把真实缓存重算当成重新跑 provider 或刷新正式 `data_health.json`。

### 改了什么

- `A-EGS/egs_main.py::_margin_observation()` 将 `rzye/rqye` 数值检查改为逐行有限值掩码：保留坏值在 frame 中，参考日只统计可用 canonical 代码；只要批次存在数值缺失，状态就是 `incomplete`，不允许 `coverage_complete=true`。
- 结构性坏形态（缺列、非法日期、非法代码、没有任何可用数值参考行）仍然 `invalid`；空 frame 仍然 `unavailable`。
- `schemas/a_short_m67_effect_contract.json` 仅同步 `A-EGS/egs_main.py` 的 predicate hash，满足静态契约门；没有改 data-health/analysis-input schema、Rule6 阈值、排序、账户或订单路径。

### 为什么

当前真实缓存有 50561 行，只有 16 条历史 `rqye=NaN`，但修复前的全局门把整批标成 `invalid` 并把 `universe_size` 清成 0。这样健康检查无法显示真实参考规模，也容易让后续维护者误把源故障看成“没有两融全集”。修复后同一缓存只读重算为 `reference_date=20260731`、`effective_ref_date=20260731`、`universe_size=1993`、`coverage_complete=false`、`status=incomplete`；安全语义仍是阻断/unknown，不是放行。

### 验证命令与结果

- 固定解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`。
- 改变面控制：`python -m unittest tests.phase6.test_egs_margin_coverage.MarginCoverageTests.test_empty_incomplete_and_malformed_sources_never_claim_complete ...`（4 个明确控制）→ `Ran 4 tests in 0.364s ... OK`。
- Effect-contract：`python -m unittest tests.test_a_short_effect_contract` → `Ran 47 tests in 64.252s ... OK`。
- A-short full-lane：`.tools\full_pack_ledger.py run a_short ... 860 -- discover -s tests -p test_a_short*.py` → `Ran 2274 tests in 468.919s ... OK (skipped=3)`，ledger `RESULT status=PASS exit=0 tests=2274 elapsed=471.1s deadline=860s`。
- 真实缓存只读 probe：`margin_20260731_rule6_v4.pkl` 50561 行 → 上述 `incomplete/universe_size=1993`；没有 provider/network 调用，也没有写回 `result/a_short/20260803/data_health.json`。
- 随后发现并修正该模块中一个旧 IV feed 最小 fixture 缺 envelope 字段的问题；固定主 Python 重跑全模块得到 `Ran 17 tests in 4.485s ... OK`。这是测试契约同步，不改变 margin producer 或消费语义。

### 失效旧结论

- “任意 `rzye/rqye` 缺失都应让 `margin_coverage` 变成 `invalid` 且 `universe_size=0`”已失效。
- “现有 `result/a_short/20260803/data_health.json` 已被本刀刷新”不成立；该文件本轮未重写，当前旧 JSON 仍可能保留修复前值。
- “`status=incomplete` 可以被当成非两融全集并清除 Rule6”不成立；只有 `status=complete` 且满足 floor/时钟/字段完整条件才建立 eligibility。

### 下一步注意事项

- 独立 reviewer 需复核对应 R-ID 的完整细节、fixture 同步、4 条控制、effect-contract hash、full-lane ledger 和缓存重算；PASS 前不得提交或合入。
- 若要让桌面批次文件反映新状态，另行授权后用当前代码刷新 `20260803` EGS/data-health 产物；刷新前不能把桌面 JSON 的旧值当成已修复。
- 上一轮四个未跟踪真实 IV/M6.7 产物保持原样；不清理、不覆盖、不纳入本刀默认范围。

## 2026-08-02 追加：桌面第 3 条 Phase6 fixture 契约同步

### 文档作用与范围

本节记录上一轮验证中发现的测试层阻断及其最小修复；它只恢复 `tests.phase6.test_egs_margin_coverage` 对现行 IV feed schema 的合法 fixture，不扩大融资融券 producer 修复，也不刷新 `20260803` data-health 产物。

### 改动与作用

- `test_margin_clock_binds_to_price_data_through_not_decision_date` 改用现有 `_feed()` canonical envelope，再覆盖本测试所需的 `as_of`、`n_days`、`series`；补齐 `schema_name/schema_version/params/boundary/hv_value` 等读门要求。
- 生产代码、schema、effect-contract hash 和真实缓存均未因该 fixture 修复而改变；Rule6 仍对不完整 margin source fail-closed。

### 验证与边界

- 固定主 Python：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`。
- `tests.phase6.test_egs_margin_coverage`：`Ran 17 tests in 4.485s ... OK`；无 provider/network/live/account/order 操作。
- 旧 `result/a_short/20260803/data_health.json` 未覆盖，仍需单独授权刷新；独立 reviewer 仍需复核整刀，当前未提交、未合入。

### 下一步

- Claude Code：复核 margin producer、fixture 同步、真实缓存只读重算及负向门；通过后再决定是否授权刷新旧 data-health 产物。


