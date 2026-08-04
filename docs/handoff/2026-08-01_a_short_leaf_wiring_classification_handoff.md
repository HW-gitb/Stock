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
- 真实 `--as-of 20260803` 的 provider 跑**已由用户授权单独执行**（只跑写盘门、未跑实盘周报）：写盘成功、`n_days=281`，窗口内 calendar-only 恰为 `['20260803']`、independent-only 为空，根因与修复均由实测确认；详见 register 同条的「真实数据闭合」。仍未做的是带 `-Account` 的完整周报运行。

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

## 2026-08-02 追加：融资融券 Optional (a) 候选级降级修复

### 文档作用与范围

本节是本次 Optional 修复的同阶段 handoff：给独立 reviewer 说明改了什么、为什么这样改、如何验证、哪些结论仍不能下。`docs/system_risk_register.md` 保存完整风险机制与 Required/Optional 账；`docs/SESSION_LOG.md` 只保存本轮最小 cycle facts 与提交门字段；本节保存 reviewer 接手所需的调用链、负向控制和边界。三者不是重复契约，也不授权 provider、实盘、账户或下单。

### 修复内容与作用

- 批次级 `margin_coverage` 仍只有全窗口数值完整、日期/规模满足条件才为 `complete`；因此不完整源不会被伪装成完整全集，也不能证明候选缺席为 `not_applicable`。
- `A-EGS/egs_main.py::_collect_rule6_evaluations()` 对 `incomplete` 且有效参考日滞后不超过一席的参考日出现候选写入 `margin_candidate_eligibility=true`；不在部分参考集、源有坏码或时钟不成立的候选保持 `None`，两项 Rule6 继续 `unknown`。
- `runners/a_short_phase5_engine.py::_margin_source_is_unavailable()` 新增候选级消费路径：只有两项 Rule6 外层均为 `pass/fail`，metrics 仍明确为 `incomplete`、`coverage_complete=false`、reference/effective 日期与批次一致且资格为 `true` 时，才不再打系统级 margin outage banner；任一缺失、unknown、错绑或 partial 下 `not_applicable` 都继续阻断。

### 验证与边界

- 固定解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，`Python 3.13.8`。
- focused producer/consumer/negative lane：`Ran 32 tests in 4.501s ... OK`；effect-contract：`Ran 47 tests in 64.944s ... OK`。
- rule 3 full lane：`Ran 2274 tests in 442.088s ... OK (skipped=3)`；ledger `RESULT status=PASS exit=0 tests=2274 elapsed=444.2s deadline=860s`。
- 未刷新真实缓存、`20260803` data-health 或四个既有未跟踪 provider/run 产物；未执行新的 provider/network/live/account/order；未 commit/push/merge。独立 reviewer pending，Optional (b) 的测试文件未被 `test_a_short*.py` 发现选择器覆盖，仍单独记账。

### 交接动作

Claude Code：按 `R-ASHORT-MARGIN-COVERAGE-NUMERIC-GAP-ZEROES-REFERENCE-UNIVERSE` 复核 producer → metrics → Phase5 gate 的完整 diff、partial 正控与 absence/unknown/clock/not_applicable 负控；独立 PASS 前不得提交或合入。

## 2026-08-03 追加：桌面清单 #01（原 P1-1）forward-event / ratchet 文案契约修复

### 文档作用与范围

本节是 A-short executor/fixer 给 Claude Code reviewer/committer 的同阶段交接：记录本条两腿缺陷的判断、调用链、直接消费者、schema/source-binding/写盘边界、负向控制、固定 Python 命令和最终终态。完整风险定义与 Required/NOT_VERIFIED 单一来源在 docs/system_risk_register.md 的 R-ASHORT-P1-1-FORWARD-EVENT-ADVICE-TEXT-CONTRACT；docs/SESSION_LOG.md 只保留本轮最小 cycle facts。本节不授权 provider/live、账户实盘、下单、commit、push 或 merge。

### 意见判断与根因

- 用户意见正确。腿一是 _attach_forward_event_impacts() 先把 forward_event_* 写入 machine.operation_impact 和 操作建议，_apply_holding_ratchet() 的 breach 分支随后整段覆盖 操作建议；事件结构仍在但中文 marker 消失，报告级 no-dangling 旧 guard 拒绝整批周报。
- 腿二是同一类缺陷的未触发分支：non-breach 路径按 系统跟踪止损 {old_stop} 精确查找，文案措辞、空格或数字格式变化即可 raise。二者共同把人类展示面当成机器跨阶段契约。

### 调用链与直接消费者

main() → _upcoming_events() → _attach_forward_event_impacts() → _attach_holding_disposition() → _apply_holding_ratchet() → validate_weekly_report() / validate_operation_impact_no_dangling() / weekly writer。机器权威是 reports[] 的 machine.operation_impact：source_field=forward_event_{type}、evidence_ref.value=upcoming_events.events[{type}]、evidence_ref.as_of==报告 as_of、source-class analysis-only 与 held/candidate shape/privacy。操作建议是可被 ratchet/处置阶段改写的人类展示面；holdings_manual_review 旁路没有 machine.operation_impact，仍以 reason marker 证明落地。

### 改动与写盘边界

- runners/a_short_phase5_engine.py：删除 forward_event_* 对 操作建议 固定中文 marker 的报告级机器守卫；保留 source-class、blocked-add、weekly calendar evidence 和 fake/mutated impact 的 fail-closed guard。
- runners/a_short_weekly_pipeline.py：新增 _rewrite_holding_ratchet_advice()，只按 stop 语义标签清理 ratchet-owned 展示片段，最终 stop/t1/t2 全由 machine plan 结构化值生成；不查旧数字、不因文案改写抛错，保留既有 forward-event advisory。breach 后将 _apply_holding_disposition() 的最终 structured disposition 同步到 machine.ratchet 与 sidecar row，闭合 clear_review/hold_watch 结构边界。
- schemas/a_short_m67_report.schema.json：只补说明，operation_impact 形状/required 字段未改；forward_event_* 的结构化 source-binding 是机器落地权威。schemas/a_short_m67_effect_contract.json：按固定 Python 实际 inventory 同步 phase5/weekly decision predicate 与 M6.7 output schema 指纹。
- 未改操作、EGS、TopN、选股、股数、production effect、provider/credential、账户/订单路径；测试只写临时目录，未刷新 result/production 或真实私密周报。

### 负向控制与自审

- 结构化 forward_event impact 篡改 production_effect_enabled、veto_class、field_class、new_entry_effect、holding_effect 仍被拒；checked calendar 缺 report impact、fake type/code、impact 缺匹配 calendar evidence 仍被 weekly validator 拒。
- 中文 操作建议 被改写后 direct no-dangling 通过；non-breach 旧 stop 字面不存在时仍按 plan 写最终跨周止损；breach ratchet 后 forward-event impact 保留、marker 展示保留、blocked-add/no-dangling 通过。
- Pre-Codex self-review matrix：advice overwrite / exact old phrase / structured operation_impact / plan.stop-table.损 binding / breach disposition synchronization / M6.7 schema / effect-contract fingerprint / weekly reverse evidence / write boundary。无 provider/live、无下单、无 sub-agent；独立审查和提交仍未发生。

### 验证命令与原始终态

- 唯一解释器：C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe；版本：Python 3.13.8。
- 固定 wrapper：& 'D:\cnhea\Codex\worktrees\29e0\Stock\.tools\run_unittest_with_repo_pythonpath.cmd' --timeout-seconds 1300 tests.test_a_short_weekly_pipeline.ForwardEventRowLandingTests tests.test_a_short_review1_knives_1_5.Cut4StopAndRRTests → Ran 27 tests in 3.674s ... OK；RESULT tier=focused status=PASS exit=0 tests=27。
- 固定 wrapper：& 'D:\cnhea\Codex\worktrees\29e0\Stock\.tools\run_unittest_with_repo_pythonpath.cmd' --timeout-seconds 1300 tests.test_a_short_effect_contract tests.test_a_short_phase5_engine → Ran 195 tests in 95.932s ... OK；RESULT tier=focused status=PASS exit=0 tests=195。
- 固定 wrapper：& 'D:\cnhea\Codex\worktrees\29e0\Stock\.tools\run_unittest_with_repo_pythonpath.cmd' --timeout-seconds 1300 tests.test_a_short_weekly_pipeline tests.test_a_short_review1_knives_1_5 → Ran 539 tests in 108.496s ... OK；RESULT tier=focused status=PASS exit=0 tests=539。
- 官方 full lane：& 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' 'D:\cnhea\Codex\worktrees\29e0\Stock\.tools\full_pack_ledger.py' run a_short 'R-ASHORT-P1-1-FORWARD-EVENT-ADVICE-TEXT-CONTRACT repair' 'focused 27 + effect-contract/phase5 195 + weekly/review1 539 OK; static_contract_error=None' 860 -- discover -s tests -p 'test_a_short*.py' → Ran 2305 tests in 338.683s ... OK (skipped=3)；RESULT status=PASS exit=0 tests=2305 elapsed=341.3s deadline=860s。
- 固定 Python AST/schema/static 自审：AST/schema/static_contract=None；git diff --check exit 0（只有 CRLF 转换提示）。第一次未重封契约的聚焦命令曾得到 RESULT tier=focused status=FAIL exit=1 tests=27，已修正并重跑；不把该中间结果当最终证据。

### NOT_VERIFIED、审查/提交边界与下一步

- NOT_VERIFIED：provider/network/live、--confirm-fetch-authorized、-Account 新实盘、真实 7 只财报事件复跑、生产产物刷新均未执行；未启动 runner、sub-agent 或自动下单。
- Claude Code reviewer/committer 尚未独立审查；本节不是 review PASS，也不是 ship/live PASS。commit/push/merge = NOT_PERFORMED；PASS 前不提交。
- 下一步：Claude Code 独立审查 R-ASHORT-P1-1-FORWARD-EVENT-ADVICE-TEXT-CONTRACT，复核本节列出的调用链、schema/effect-contract 指纹、两条负向控制和文档门。

### 2026-08-03 文档门禁最终复核补充

- 本节追加记录本轮最后的文档治理执行：固定 wrapper `& 'D:\\cnhea\\Codex\\worktrees\\29e0\\Stock\\.tools\\run_unittest_with_repo_pythonpath.cmd' --timeout-seconds 1300 tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency tests.test_readme_route_row_length`；原始终态 `Ran 66 tests in 0.899s ... OK`，`RESULT tier=focused status=PASS exit=0 tests=66 elapsed=1.0s deadline=1300s`。解释器仍为 `C:\\Users\\cnhea\\AppData\\Local\\Programs\\Python\\Python313\\python.exe` / `Python 3.13.8`；`git diff --check` exit 0（仅 CRLF 转换提示）。



### 2026-08-03 Claude Code 独立审查 = FAIL（#01 forward-event/ratchet 文案契约）

- **Verdict**: FAIL，未提交、未合入。原始症状确已消除（marker 在 ratchet 之后仍在、措辞改写不再抛错、止损改用结构化 `plan`），但修复 ③ 的实现比声明宽，把跨周 anti-rescue 打穿。
- **实测（A/B 探针，两棵树同一 fixture：上周 `last_disposition=clear_review`、本周合并出 `hold`）**：主树 HEAD 得 `ratcheted_disposition=clear_review` / `row.last_disposition=clear_review`；本树得两处均为 `hold` —— 降档且已写进私密 sidecar row。连带 `_ratchet_report_error` 弱不变式 ③ 因赋值在检查之前而变成自比较，永不触发。
- **Required（三条，正文在 register 单一来源 `R-ASHORT-P1-1-FORWARD-EVENT-ADVICE-TEXT-CONTRACT`）**：① `a_short_weekly_pipeline.py:3634-3637` 改成 `_severity_max_disposition` 合并而非覆盖；② 补降档方向的反向控制 + 破位升档正控；③ 删掉 engine ⑫ 运行时强制并反转其反向控制后，须给出结构化替代或等价反向控制。
- **按类修的边界（正文见同一 R-ID 的「缺陷类边界」条，本处只留指针）**：Required ①② 属 **类 1「先赋值、后校验」——本刀必须整类修完**：已确认两个实例（③ disposition 为本刀新引入；② stop 因 `plan["stop"] = final_stop` 先于本刀就已退化成 `rs < rs`），须逐条走 `_ratchet_report_error` ①-⑤ 问「它读的量是否在写点被赋成了对照量」，并为 stop / disposition **各**补一条降低方向的反向控制。Required ③ 属 **类 2「中文 marker 当机器契约」——本刀不铺开**：engine 内仍有 5 条同构判据，其中 `blocked_add_required`(:2327) 读的就是 `advice_text` 且 forward_event held 分支正好设它为 true，本刀只是靠新正则保留周边文本躲开；本刀只需补一条覆盖「attach 之后任意阶段整段改写 `操作建议`」的反向控制 + 记 follow-up。
- **不要返工**：`_rewrite_holding_ratchet_advice` 两条腿、effect-contract 双 runner 指纹与 M6.7 schema 指纹重封。
- **Verify**: review-evidence:402172fb353a；full lane 在本树 `[full-pack-ledger] CACHED GREEN - a_short = 2305 OK`（与执行方自跑同一 code state，未重复跑）。provider/live 与 `-Account` 实跑 `NOT_VERIFIED`。

## 2026-08-03 追加：Codex 第二轮修复——R4b 写回 anti-rescue 与类2单条反控

### 文档作用与本轮范围

本节是当前 A-short executor/fixer 给 Claude Code reviewer/committer 的同阶段追加交接，承接上一节 Claude FAIL。附件方案判断正确；本轮按「类1整类收口、类2只做一条」执行。完整风险与 follow-up 单一来源为 `docs/system_risk_register.md` 同一 R-ID；本节不授权 provider/live、账户实盘、下单、commit、push 或 merge。

### 根因、优化与调用链

- 根因不是单一覆盖语句，而是 `_ratchet_report_error()` 的判据在 pipeline 写回前读取了已经被改写的 `plan["stop"]` / `machine_ratchet["ratcheted_disposition"]`，导致 stop 退化为自比较、disposition 退化为自比较；上一轮无条件同步还把跨周 `clear_review` 降成了本周 `hold`。
- 优化后的链路为 `main → _apply_holding_ratchet → _holding_ratchet → _apply_holding_disposition → _ratchet_report_error → state[key] = row`：disposition 用 `_severity_max_disposition` 合并；stop 在写 `plan["stop"]` 前捕获本周有效值；跨周 stop/disposition 在 sidecar 替换前按旧 row 与新 row 做 fail-closed 单向断言。同周重跑仍跳过跨周比较以保持幂等，`entry_date` 继续隔离 re-entry。
- 类2只新增 held + forward_event + `blocked_add_required` 清空 advice 的真实负控并要求 raise；其余 5 条文案 marker 判据登记后续刀，不在本刀扩大。

### 改动、直接消费者、schema/source-binding 与写盘边界

- `runners/a_short_weekly_pipeline.py`：加入 `_severity_max_disposition`/`_is_finite_num` 局部依赖；修复 ratchet disposition 合并；加入写点 stop 自检和 `state[key]` 前跨周 stop/disposition 断言。
- `tests/test_a_short_gap_data_registry.py`：新增 disposition 降档反控、破位升档正控、植入 stop 降低反控、植入 disposition 降档反控，共四条 Required。
- `tests/test_a_short_weekly_pipeline.py`：将类2单条用例改为 held forward-event 清空用户文案后，`blocked_add_required` guard 必须 raise；候选结构化 forward-event advice 可重写的正向覆盖仍由 earnings source guard 测试保留。
- `schemas/a_short_m67_effect_contract.json`：按固定 Python 重算并同步 weekly runner predicate hash；M6.7 schema 形状和 forward-event `operation_impact/source-binding` 未改。
- 机器权威仍是 `machine.ratchet` 与私密 sidecar row；`操作建议` 仅展示面。未改 engine `_ratchet_report_error` 签名、EGS/TopN/生产 effect、provider、账户/订单路径。

### 负向控制与自审

- 上周 `clear_review` + 本周 `hold` 不得降档；上周 `hold` + ratchet 破位必须升到 `clear_review` 且不误拒。
- 植入低于上周的 `ratcheted_stop` 或较低 `last_disposition` 均在 sidecar 写回前 raise；同周 replay 仍幂等。
- held forward-event 清空 `操作建议` 且清空 `风控触发` 后，`blocked_add_required` 仍必须 raise；这条记录了类2后续结构化统一的现有牙口。
- 自审矩阵：`disposition merge / cross-week stop / cross-week disposition / pre-write stop / breach escalation / class2 blocked_add / effect-contract / sidecar write boundary`；未改 `_rewrite_holding_ratchet_advice` 两条已通过路径。

### 固定 Python、测试命令与原始终态

- 固定主 Python：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`。
- focused 命令：`& 'D:\cnhea\Codex\worktrees\29e0\Stock\.tools\run_unittest_with_repo_pythonpath.cmd' --timeout-seconds 1300 tests.test_a_short_gap_data_registry.HoldingRatchetS3bR4bTests tests.test_a_short_weekly_pipeline.ForwardEventRowLandingTests tests.test_a_short_review1_knives_1_5.Cut4StopAndRRTests tests.test_a_short_effect_contract tests.test_a_short_phase5_engine` → `Ran 263 tests in 51.174s ... OK`；`RESULT tier=focused status=PASS exit=0 tests=263 elapsed=52.6s deadline=1300s`。
- 唯一 full lane 命令：`& 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' 'D:\cnhea\Codex\worktrees\29e0\Stock\.tools\full_pack_ledger.py' run a_short 'R-ASHORT-P1-1-FORWARD-EVENT-ADVICE-TEXT-CONTRACT second repair' 'focused 263 OK; disposition merge + cross-week writeback anti-rescue + pre-write stop guard + class2 blocked_add negative control; static_contract_error=None' 860 -- discover -s tests -p 'test_a_short*.py'` → `Ran 2309 tests in 335.740s ... OK (skipped=3)`；`RESULT status=PASS exit=0 tests=2309 elapsed=337.5s deadline=860s`；ledger fingerprint `dd8ced5ed9cb`。
- 固定 Python effect-contract 自审：weekly predicate hash 已同步，`static_contract_error=None`；provider/live/account 未调用。
- 文档治理/路由/README：`Ran 66 tests in 0.936s ... OK`，`RESULT tier=focused status=PASS exit=0 tests=66 elapsed=1.1s deadline=1300s`；固定 Python 与上文相同。

### NOT_VERIFIED、审查/提交边界与下一步

- `NOT_VERIFIED`：provider/network/live、`-Account` 新实盘、真实财报事件复跑、生产产物刷新、sub-agent 均未执行；未自动下单。
- Claude Code 独立复审尚未发生，本节不是 review PASS 或 ship/live PASS；commit/push/merge = `NOT_PERFORMED`。
- 下一步：Claude Code 独立审查 `R-ASHORT-P1-1-FORWARD-EVENT-ADVICE-TEXT-CONTRACT`，重点复核类1写点断言与类2 follow-up 边界。

### 2026-08-03 Claude Code 独立审查第二轮 = PASS（#01 R4b 写回 anti-rescue）

- **Verdict**: PASS，已提交并合入 master。上一轮三条 Required 全部按指定形态收口；类 1 整类修完（含我未点名、执行方自补的「跨周止损丢失」那条腿），类 2 按边界只补一条反控。
- **实测（reviewer 四条探针，本树实跑；A 是上一轮 FAIL 的同一份 fixture）**：降档反控 → `ratcheted_disposition` 与 `row.last_disposition` 均保持 `clear_review`（上一轮同 fixture 得 `hold`）；植入降档 → RAISED `R4b ratchet 跨周降档(...): 'clear_review' -> 'hold'`（守卫有牙）；破位升档正控 → 升到 `clear_review` 且不误拒；同周重放 → 跳过跨周检查、不抛错。
- **计数/指纹**：full lane `CACHED GREEN a_short = 2309 OK`；`2305→2309` 的 `+4` 逐条可解释（gap_data_registry 新增 4 条，weekly_pipeline 那条是改名不新增）；`static_contract_error()=None`。
- **Follow-up（另起一刀）**：`validate_operation_impact_no_dangling` 内仍有 5 条同构「中文 marker 当机器契约」判据待统一为结构化判据；未修 Optional = `_RATCHET_STOP_ADVICE_RE` 逗号续写会被吞。正文见 register 同一 R-ID。
- **Verify**: review-evidence:3d088ed82302。provider/live 与 `-Account` 实跑仍 `NOT_VERIFIED`——本周真实 M6.7 能否 emit 要等下一次 `-Account` 周跑。

### 2026-08-03 a_cc_testrun1 剩余 15 条的执行顺序（#01 闭合后重排；Claude Code 定，含复杂度星级）

**为什么重排**：原顺序把「让修复循环可信」（#02/#03/#04）放在第 2 位，理由是修 #01 期间每次试跑都会失败并复发。#01 已闭合（`1f8d30dd`），周跑不再必然失败，这三条从「每天被咬」降级成「保险」，因此让位给四把快赢。星级 = 改代码 + 验证（含指纹重封、反向控制、全量）的成本，**不含**等用户裁决的时间。

**第 0 步（不是刀，最高优先）**：跑一次带 `-Account` 的真周跑。这一步零代码成本、信息量最大：端到端验证 #01 真的让 M6.7 emit；拿到 register 里挂了很久的观察项「候选级两融降级是否让那两项 Rule6 真正生效」；并直接看出 #02/#03/#04 是否还会被触发。**时点注意**：周一收盘后跑，canonical 会解析到下一交易日；要复现本周决策日须显式 `-AsOf 20260803`（此时 `price_as_of` 会等于 `as_of`，是 #10 的双口径问题，产出可用但基准不是盘前口径）。

| 批 | 序 | 条目 | 刀数 | 复杂度 | 排这里的理由 |
|---|---|---|---|---|---|
| ✅ 1 快赢 | 1 | #05 北向量纲 | 1 | ★★☆☆☆ | 已合入 master |
| ✅ 1 | 2 | #07(a) cninfo fail-loud | 1 | ★★☆☆☆ | 已合入 master |
| ✅ 1 | 3 | #11 ratchet 陈旧 state | 1 | ★☆☆☆☆ | 已合入 master |
| ✅ 1 | 4 | #13 tracker 成熟度日志 | 1 | ★☆☆☆☆ | 已合入 master |
| ✅ 1 | 5 | #12 last_selection 按 as_of 分版本 | 1 | ★★☆☆☆ | 已合入 master |
| ✅ 并行 | — | #07(b) cninfo 换请求形态/换源 | 1 | ★★★★☆ | 已合入 master |
| ✅ 2 韧性 | 6 | #03+#04 launcher 提前 exit | 1 | ★★★★☆ | 已合入 master `a66e7340` |
| 2 | 7 | #02 汇总/账本事务性 | 1 | ★★★★☆ | 第 0 步那次周跑只要挂一次，这条立刻回到最痛位置 |
| ✅裁决 3 | 8 | #10 price_as_of 双口径 + 资金流容差 | 1 | ★★★☆☆ | **2026-08-04 已裁**：价格基准统一成「上一个已收盘交易日」（研究口径另开显式开关）；资金流窗口允许退一日并显式标注实际用日 |
| ✅ 3 | 9 | #16 融资过热（裁决） | — | — | **2026-08-04 用户裁定「接」**；工程项转下方序 19 |
| ✅ 3 | 10 | #06 节前减仓的解环裁决 | 裁决 | — | 已解：写成「豁免需举证」，`unknown` 照常打折，#08-market_regime 落地后豁免自动生效、代码一个字不用改 |
| 4 悬空治理 | 11 | #09 守卫粒度 group→leaf | 1 | ★★★★★ | 必须同刀携带 28 条叶的处置（接线 or 显式标注有意不接），否则改完当场 lane 红 |
| 4 | 12 | #08 northbound 接线 | 1 | ★★☆☆☆ | 数已取到（#05 已闭，量纲已对），现在只进控制台不进契约；**消费点现成**：v14.2 `:224`「北向连续 5 日净流出」是回溯触发升级审查的三选二之一 |
| 4 ⛔ | 13 | #08 liquidity 接线 | 1 | ★★☆☆☆ | **仍未决，禁止开工**：数据现成但无消费点，v14.2 的 regime 触发条件里没有成交额这一项；未定用途前接线必造 `true_dangling` 叶 |
| 4 | 14 | #08 breadth 接线 | 1 | ★★★☆☆ | **口径已定（2026-08-04）：全市场，不限主板**，字段名须写明；连板高度仍是新算法 |
| 4 | 15 | #08 volatility 接线 | 1 | ★★★★☆ | 卡执行次序：EGS 跑在 IV feed 之前，结构上拿不到。**2026-08-04 用户令：先花一刀验证 IV feed 是否依赖 EGS 输出**（见下方序 20），验完再定方案 |
| 4 | 16 | #08 market_regime 接线 | 1 | ★★★★★ | 三个仓位上限 + 最小盈亏比 + triggers，v14.2 核心状态机，碰真钱边界 |
| ✅ 4 | 17 | #06 节前减仓实现 | 1 | ★★★★★ | 已合入 master `a41c005c`；没等 regime，用举证式豁免解了环 |
| 5 新增 | 18 | #14 短史候选无区别对待 | 1 | ★★☆☆☆ | **2026-08-04 由「记账」升为刀 + 口径已定：降级不排除**（可打分、禁进 Tier1/最终）。33/819 只 <61 根，调节表**无任何「历史不足」排除理由**，它们照常参与排名 |
| 5 | 19 | #16 全市场融资过热接线 | 1 | ★★★☆☆ | **2026-08-04 用户裁定「接」+ 消费点已定：压总仓位**（复用 #06 的现金系数杠杆，不走盈亏比门槛）。`A-EGS/egs_main.py:5971` 现为占位字符串 |
| 6 前置 | 20 | IV feed 依赖关系验证刀 | 1 | ★☆☆☆☆ | **2026-08-04 用户令**：查清 IV feed 是否依赖 EGS 输出。序 15 volatility 与序 16 market_regime 的共同前置，不做这两把都开不了工 |

**不许违反的约束**：① 第 4 批的 #09 与 #08 强耦合——#09 单独落地会让 28 条恒空叶暴露成叶级悬空、守卫当场红，必须同刀带处置。② ~~#06 反向依赖 #08-market_regime~~ **已作废（2026-08-04）**：#06 用举证式豁免解环并已落地，不再依赖 regime 先接。③ **新增（2026-08-04，来自 #06 的教训）**：序 12-16、18、19 每一把都必须**生产者与消费者同刀闭合**——只填真值不接消费者会立刻造出一条 `true_dangling` 叶，直接撞「每因子必联动到最终输出」的验收门，并被序 11 的 #09 账本盯上。

**剩余 11 刀**（#02、#10、#09、#08×5、#14、#16、IV-feed 依赖验证；已合入 master 的 8 项见上表 ✅）。其中 **#08 liquidity 仍未决、禁止开工**。原为 17 刀，2026-08-04 后 #14/#16 由「记账 / 待裁决」转为工程项各 +1 刀。第 1 批五把加起来约等于一把 ★★★，却消除两条「看起来正常实则已死」的假象、清掉一处脏状态、并止住每跑一次就毁一次的追踪基线。

**约束 ③（2026-08-03 Claude Code 补，实读 `schemas/a_short_m67_effect_contract.json`）**：序 11 的 #09 **不必发明新 nature 值**。`leaf_nature_by_group` 已有 `true_dangling` 这一档并已在用——29 个 group 的 nature 分布实测为 `main_decision` 6 / `partial_consumption` 9 / `true_dangling` 9 / `comparison_track` 2 / `duplicate_source` 2 / `display_audit` 1，其中 `candidate_capital_flow`、`candidate_quote`、`account_context` 等 9 个组正用 `true_dangling` 诚实表达「整组真悬空」。所以 #09 的实质是给 `market_context` 这种**组内混合**的情形补一个**叶级出口**，把那 28 条恒空叶按既有 `true_dangling` 逐条标注即可，不是设计能力缺失，也不需要新概念。

**附带实证（不要当缺陷去修）**：`candidates[].capital_flow.margin.*` 五个字段（`balance` / `balance_change_5d_pct` / `balance_change_10d_pct` / `balance_to_float_mv_pct` / `extreme_accumulation`）在 2026-08-03 实盘周跑里 15 只候选**全为 null**，生产者 `A-EGS/egs_main.py:791-794` 写死 `None`。但其所属组已诚实标注 `true_dangling`，属 `docs/CURRENT.md` §0 所述「Remaining `true_dangling` leaves are not yet wired」的**既定待接线存量**，**不是新漏洞**，不进 a_cc_testrun1 清单。同一份两融数据在 `event_risk.rule6_checks[].metrics` 里是有值的（本轮 `600236.SH` 因 `margin_growth=0.2399` vs `price_gain=0.0188` 被 `rule6_margin_extreme_accumulation` 判 `fail` → `rule6_gate.disposition=hard_veto` → M6.7 `操作=否决`），判断链完好，空的只是展示字段。

## 2026-08-03 追加：桌面清单 #05（D-2）北向资金量纲与防御阈值

### 文档作用与范围

本节是当前 A-short executor/fixer 给 Claude Code reviewer/committer 的同日追加交接，记录桌面 `a_cc_testrun1.md` #05 的判断、根因、修复、调用链、直接消费者、schema/source-binding、写盘边界、负向控制、自审、固定 Python、原始测试终态、NOT_VERIFIED 和下一步。`docs/handoff/README.md` 将本文件定义为 A-short 叶级接线/效果分类与本周漏洞的当前 phase handoff；完整风险单一来源为 `docs/system_risk_register.md` 的 `R-ASHORT-KNIFE5-NORTHBOUND-MONEYFLOW-UNIT-MISMATCH`，`docs/SESSION_LOG.md` 只保留最小 cycle facts。本节不授权 provider/live、真实周跑、账户实盘、下单、commit、push 或 merge。

### 意见判断、根因与修复

- **意见正确，且 #05 确实是 #01 闭合后的下一刀**：桌面清单第 3 批把它列为 D-2；当前 handoff 的重排表也明确把 #05 排为序 1，#08 northbound 接线依赖本刀。
- `pro.moneyflow_hsgt.north_money` 的接口数值口径是**万元**。旧实现直接求和后把数值当人民币元，显示再 `/1e8`，所以 `281077.72 + 341408.12 + 363460.14 + 354101.65 = 1,340,047.63 万元` 被错误显示成 `0.01 亿`，正确值约为 `134.00 亿`。
- 同一个未归一化数值还被两个防御消费者复用：`north_flow < -50e8` 的大幅流出阈值被错误解释为约 `-50 万亿元` 的原始万元数，实际死掉；CSI300 下跌时的静默条件也读同一错误量。
- 修复采用一次性、显式的 source boundary：新增 `TUSHARE_MONEYFLOW_HSGT_NORTH_MONEY_UNIT_YUAN = 10_000`，将 `north_money` 先归一为 `north_flow_yuan`；显示、`north_flow_yuan < -50e8` 大幅流出、`north_flow_yuan < 0` 静默三处只消费这个人民币元值。`sum(min_count=1)` 加有限值判断保持空/全无效输入不伪装成零流入，继续输出数据不可用。

### 调用链、消费者、schema/source-binding 与写盘边界

- 调用链：`run_egs()` → `market_environment(trade_dates, stats_df)` → `safe_api(pro.moneyflow_hsgt, start_date=trade_dates[4], end_date=trade_dates[0])` → `north_money`（万元）→ `north_flow_yuan`（人民币元）→ 市场环境字符串 → `env_report` 控制台输出。
- 直接消费者只有同一函数内的三个市场环境出口：`近一周净流入` 显示、`北向资金大幅流出` 防御提示、CSI300<-10 且北向为负的 `[静默]`。全仓旧独立符号 `north_flow` 与旧 raw-sum 形态均无残留；`#08 market_context.northbound` 结构化接线仍是后续刀，本刀不扩大范围。
- schema/source-binding：未改变 `analysis_input`、M6.7 或 weekly report 的 schema 形状；`moneyflow_hsgt.north_money` 的万元→人民币元单位绑定落在 EGS producer 代码的显式常量上。因 A-EGS 生产判据/常量改变，按固定 Python inventory 只重封 `schemas/a_short_m67_effect_contract.json` 中 `A-EGS/egs_main.py` 的 `decision_predicate_sha256` 与 `runtime_constants_sha256`；未改 provider endpoint、API 参数、PIT 日期窗口或其他 runtime policy。
- 写盘边界：`env_report` 仍只由 EGS 现有控制台输出路径打印；本刀未刷新 `result/`、正式分析产物、weekly/private artifact、缓存或账户状态。测试对 `safe_api` / CSI300 返回做内存 patch；full lane 只执行离线测试，不调用 provider/live/network/order。

### 负向控制与自审

- 正向单位控制：四个桌面实测形状数值作为万元 fixture，期望输出 `北向资金近一周净流入: 134.00 亿`，旧 `0.01 亿` 不得出现。
- 防御负向/正控：`-600000 万元 = -60 亿` 且 CSI300 `-11` 时，必须同时出现 `-60.00 亿`、`北向资金大幅流出，防御信号` 与 `[静默]`；这条同时证明阈值和静默两个消费者不能只修显示腿。
- 结构自审矩阵：source unit constant → normalized internal value → display → large-outflow threshold → silence predicate → invalid/finite fail-closed → EGS `env_report` write boundary → effect-contract predicate/constant reseal → old-symbol/raw-sum ripple grep → full-lane selection coverage。
- 全仓残留证据：固定 `rg -n -w 'north_flow' A-EGS engine runners tests` 为 0 hits；固定 `rg -n -F 'df_hsgt["north_money"].sum()' .` 为 0 hits；现存 `north_money` 命中均为 API 字段读取、单位常量说明或本刀测试 fixture，未发现第二个市场环境转换消费者。

### 固定 Python、精确测试命令与原始终态

- 唯一解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`；版本原始终态：`Python 3.13.8`。
- 聚焦命令：`Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_egs_market_environment tests.test_a_short_effect_contract` → `Ran 50 tests in 50.453s ... OK`。
- 语法命令：`& 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m py_compile 'D:\cnhea\Codex\worktrees\29e0\Stock\A-EGS\egs_main.py' 'D:\cnhea\Codex\worktrees\29e0\Stock\tests\test_a_short_egs_market_environment.py'` → exit `0`。
- 官方 full lane 命令：`Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' 'D:\cnhea\Codex\worktrees\29e0\Stock\.tools\full_pack_ledger.py' run a_short 'R-ASHORT-KNIFE5-NORTHBOUND-UNIT-CONTRACT' 'focused 50 OK; Tushare north_money 万元 to normalized RMB; display + defensive threshold + silence consumers; static contract and py_compile OK' 860 -- discover -s tests -p 'test_a_short*.py'` → `Ran 2311 tests in 318.407s ... OK (skipped=3)`；`[full-pack-ledger] RESULT status=PASS exit=0 tests=2311 elapsed=320.2s deadline=860s`；ledger fingerprint `f8f172610569`。
- 第一次同一 full lane 的测试主体虽为 `Ran 2311 tests ... OK`，但 ledger 因运行期间 HEAD 从 `030d7ee4` 推进到 docs-only `95baf649` 而输出 `REFUSED - code state changed during the full run`，不采信为 PASS；在稳定 `95baf649` 上重跑才取得上述有效 PASS。未执行任何 commit。
- effect-contract 聚焦已证明 `static_contract_error=None`；文档追加后最终 `git diff --check` exit `0`（仅 CRLF 转换提示），最终文档/路由门禁 `Ran 66 tests in 0.942s ... OK`。

### NOT_VERIFIED、审查/提交边界与下一步

- `NOT_VERIFIED`：真实 `pro.moneyflow_hsgt` provider 行为、网络/live、`--confirm-fetch-authorized`、带 `-Account` 的真实周跑、生产/私密产物刷新、#08 `market_context.northbound` 接线及实际防御周报均未执行；未启动 sub-agent，未自动下单。
- Claude Code reviewer/committer 尚未独立审查；本节不是 review PASS、不是 ship/live PASS。`commit/push/merge = NOT_PERFORMED`；full-pack 的 `RESULT status=PASS` 只证明本次离线测试包，不替代独立审查。
- 下一步：Claude Code：独立审查 `R-ASHORT-KNIFE5-NORTHBOUND-MONEYFLOW-UNIT-MISMATCH`，逐项复核万元→元 source-binding、三个直接消费者、effect-contract 重封、负向控制与 #08 未越界；审查 PASS 后按项目规则提交。

### 2026-08-03 Claude Code 独立审查 = PASS（#05 北向资金量纲）

- **Verdict**: PASS，已提交并合入 master。量纲（万元→元）判定正确，显示与两个防御判据统一读元口径；执行方另修对一条我未点名的洞——`sum(min_count=1)`+finite-check 让全 NaN 不再假装「0.00 亿」。
- **实测（reviewer 九腿探针）**：真实样本 `134.00 亿`（修前 `0.01 亿`）；阈值反控 -40 亿不触发、边界恰好 -50 亿不触发、-60 亿触发；全 NaN / 空表 / 缺列 / inf / None 五种坏输入均「北向资金数据不可用」。九腿全对。
- **Optional（不阻断，正文见 register 同一 R-ID）**：新测试只覆盖其中两腿，阈值反控与新引入的 fail-closed 行为零覆盖；建议补三条。
- **影响面澄清**：`env_report` 只在 `A-EGS/egs_main.py:5885` 被 `print`，不进 `analysis_input`（`northbound` 仍是 #08 的恒空叶）、不改选股/veto/仓位。
- **Verify**: review-evidence:738da66dbd8a；`static_contract_error()=None`；full lane `CACHED GREEN 2311 OK`（同 HEAD `95baf649`）。live `moneyflow_hsgt` 与 `-Account` 实跑 `NOT_VERIFIED`。

## 2026-08-03 追加：#05 Optional 收口与桌面清单 #07(a) CNINFO fail-loud

### 本节文档作用与执行边界

本节继续追加到 `docs/handoff/README.md` 指定的 A-short 叶级接线/效果分类当前 phase handoff；它不是新的路由真相源：风险状态与 Required/Optional 细节以 `docs/system_risk_register.md` 对应 R-ID 为准，`docs/SESSION_LOG.md` 只记录最小 cycle facts。本节记录本次先收口 #05 Optional、再执行桌面 #07(a) 的根因、改动、调用链、直接消费者、schema/source-binding、写盘边界、负向控制、自审、固定 Python、原始测试终态、NOT_VERIFIED、审查/提交边界和下一步。未授权 provider/live、真实周跑、换源、commit、push、merge 或下单。

### #05 Optional：三类回归覆盖补齐

- **问题与判断**：Claude 已独立探针证明 #05 九腿行为正确，但测试只钉住真实样本和 `-60 亿` 触发两腿；阈值反控（-40、严格边界 -50）与全 NaN/空表/缺列/inf/None fail-closed 没有回归。该 Optional 是覆盖缺口，不是重新打开 #05 生产修复。
- **改动与边界**：只扩 `tests/test_a_short_egs_market_environment.py` 的内存 fixture helper，使其可接受原始 `DataFrame`/`None`，并新增三条点名测试；`A-EGS/egs_main.py::market_environment`、三个既有消费者、schema 和生产写盘均未再改。
- **负向控制/自审**：`-40 亿`、恰好 `-50 亿`均不出现大幅流出；五种坏输入均出现 `北向资金数据不可用`且不伪造防御信号。自审核对了九腿覆盖、严格 `<` 边界、旧 positive/trigger 控制和本刀不触碰 #07/#08。
- **固定 Python 与原始终态**：唯一解释器 `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`。精确聚焦命令 `Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_egs_market_environment tests.test_a_short_effect_contract` → `Ran 53 tests in 44.147s ... OK`；对应两文件 `py_compile` exit `0`；随后官方 full lane → `Ran 2314 tests in 319.297s ... OK (skipped=3)`，`RESULT status=PASS exit=0 tests=2314 elapsed=321.2s deadline=860s`，fingerprint `6f6610dbce91`。
- **NOT_VERIFIED/审查边界**：未调用 provider/live、未跑账户实盘、未刷新生产产物、未启动 runner/sub-agent；Optional 尚未独立复审、commit/push/merge 均 `NOT_PERFORMED`。下一步与 #07 一并交 Claude Code review，不把该测试终态称为 review PASS。

### 桌面 #07(a)：CNINFO 监管 advisory 由静默 unknown 改为 fail-loud

- **最终收口门禁**：文档/路由/readme/Slice3 门禁 `Ran 73 tests ... OK`；`git diff --check` exit `0`（仅 CRLF 转换提示）。
- **精确 #07 聚焦命令**：`Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_cninfo_health tests.test_a_short_egs_market_environment tests.test_a_short_effect_contract tests.phase6.test_egs_sw_industry_and_watch_pool_health tests.test_semantic_risk_slice3_guard tests.phase6.test_weekly_screening_guardrails` → `Ran 95 tests in 45.079s ... OK`；五文件 `py_compile` → exit `0`。

- **意见判断与范围**：桌面 #07 的“200 空响应已 100% 失效且完全静默”中，旧的“空响应误报 `通过`”其实已经由 Slice 3 修为 `未检查`；本次仍成立的缺陷是空/失败结果没有进入 `data_health`、没有聚合 warning。本次只执行建议的第一步 #07(a) fail-loud；#07(b) 换请求形态或换源是另一个 provider slice，未执行。
- **根因**：`stage3_ai_clearing::_cninfo_check` 的 `hit is None` 分支覆盖 HTTP 非 200、异常和 HTTP 200 空公告，但循环只保留默认 `cninfo_flag=未检查`，没有保留失败原因或把 source-health 送给 `export_data_health`；15 只候选全走此路时，用户只能看到无原因的“未检查”。
- **改动与不变式**：`_cninfo_check` 对 `http_status`、`invalid_payload`、`empty_announcements`、`invalid_announcements`、`exception` 返回结构化 unknown reason；Stage3 汇总请求数、已知清白、advisory 命中、unknown 数和 reason counts，unknown 时保留 `未检查`、不转 `通过`，并发一条聚合 `log.warning`。已知关键词仍是 `REGULATOR-ADVISORY`，不删候选、不恢复 `REGULATOR-VETO`/硬否决。
- **调用链与直接消费者**：`run_egs()` → `stage3_ai_clearing()` → `_cninfo_check()` → HTTP status/JSON/公告形状 → `cninfo_health` → `_cninfo_health_warning()` → `export_data_health(..., sidecar_warnings=...)` → `data_health.json`/`DATA_HEALTH` 汇总。直接消费者只有候选 `cninfo_flag` advisory 展示和 `data_health.warnings`；候选池、排序、M6.7 操作、账户/订单不消费该 warning。
- **schema/source-binding**：`schemas/data_health.schema.json` 仍为 `1.8.0`，复用既有 issue 的 `check/message` 与允许的附加 metrics，没有新增字段；`schemas/a_short_m67_effect_contract.json` 的 A-EGS `decision_predicate_sha256` 已按固定 Python 重封为 `3b37a4537511f48317581265e08dcb6c5f4adab8c715b791c901daedeeddba77`，`runtime_constants_sha256` 保持 `81ddd1765aef3b079d44c4603d984e3ceb2467aff0f1cac777368e2b3b336d84`。请求参数、PIT 窗口、provider/source 选择未改。
- **写盘边界**：`data_health` warning 复用既有 EGS 官方输出事务和发布路径；测试只 patch `requests.post`，没有刷新 `result/`、正式周报、缓存或账户状态。不会因 unknown warning 自动删除候选或下单。
- **负向控制与自审**：正控为已知清白→`通过`且无 warning、监管命中→`REGULATOR-ADVISORY`且候选仍保留；反控为 200 空、非 200、非 dict payload、坏公告形状、异常→`未检查`+具体 reason+health warning。`build_data_health` schema/`overall_status=warn` 点名测试、Slice 3 “空不等于通过/不恢复硬否决”守卫、stage3 调用点守卫均覆盖；未改变 #05/#08 路径。
- **固定 Python 与原始终态**：唯一解释器仍为 `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe` / `Python 3.13.8`。#07 影响面精确聚焦命令（含 #05 Optional、effect contract、data_health、Slice 3 与调用点守卫）→ `Ran 95 tests in 45.079s ... OK`；相关五文件 `py_compile` exit `0`；官方命令 `Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' 'D:\cnhea\Codex\worktrees\29e0\Stock\.tools\full_pack_ledger.py' run a_short 'R-ASHORT-KNIFE7-CNINFO-EMPTY-RESPONSE-SILENT' 'focused 95 OK; CNINFO unknown outcomes aggregate into data_health warning; advisory hit remains non-deleting; effect contract and py_compile OK' 860 -- discover -s tests -p 'test_a_short*.py'` → `Ran 2318 tests in 296.024s ... OK (skipped=3)`，`RESULT status=PASS exit=0 tests=2318 elapsed=297.9s deadline=860s`，fingerprint `1e8b67194c43`。
- **NOT_VERIFIED/审查、提交边界与下一步**：真实 CNINFO HTTP 200 空响应、真实 provider/live、`-Account` 周跑、生产/私密产物刷新、#07(b) 换请求形态/换源、自动下单和 sub-agent 均未执行。Claude Code 尚未独立审查；`commit/push/merge=NOT_PERFORMED`。下一步：`Claude Code：独立审查 R-ASHORT-KNIFE7-CNINFO-UNKNOWN-RESULT-SILENT-DOWNGRADE，并同时复核 #05 Optional；PASS 后按项目规则提交。`

### 2026-08-03 Claude Code 独立审查 = PASS（#07a cninfo fail-loud）

- **Verdict**: PASS，已提交并合入 master。沉默通道变有声：五类不可用原因分开计数 + warning + 进 `data_health` 抬 `overall_status=warn`；新增类型守比修前更 fail-closed；`cninfo_flag` 语义与候选池未动。
- **reviewer 亲核两处**：① 接缝静态读 `egs_main.py:1888` 并实跑端到端用例双证；② `stage3_ai_clearing` 2-tuple→3-tuple 全仓扫过，真实调用仅 `:5917` 一处已更新，无遗留解包。
- **补了 lane 覆盖不到的一块**：核心接缝用例在 `tests/phase6/`，不匹配 `test_a_short*.py` 选择器；我单独跑得 `Ran 9 tests ... OK / RESULT tier=focused status=PASS exit=0 tests=9`。lane 全量 `CACHED GREEN 2318 OK`，`+7` 逐条可解释。
- **顺带闭合**：#05 留的三条 Optional 已在本刀补齐。
- **Optional（结构性，非本刀引入）**：lane 选择器吃不到 `tests/phase6/`，lane 绿≠该接缝绿；建议改名进选择器或在 ledger focused evidence 固定带上。正文见 register 同一 R-ID。
- **Verify**: review-evidence:943fa9bcc21e。cninfo live 调用与 `-Account` 实周跑 `NOT_VERIFIED`——通道本身仍是死的，那是 #07(b)。
### 2026-08-03 Codex 修复：桌面 #11/#13/#12 一次收口

#### 文档作用与本轮边界

本节是当前 A-short leaf wiring/classification phase handoff 的同日追加，记录桌面 `a_cc_testrun1.md` 的 #11、#13、#12 三项问题各自的作用、根因、调用链、直接消费者、schema/source-binding、写盘边界、负向控制、自审和验证边界。风险详情以 `docs/system_risk_register.md` 的三个 R-ID 为准；`docs/SESSION_LOG.md` 只保留本轮最小 cycle facts。本轮不执行 provider/live/account、真实周跑、runner、sub-agent、commit、push 或 merge。

#### #11：ratchet 不再消费跨周旧 bootstrap 状态

- 根因：`runners/a_short_weekly_pipeline.py::_apply_holding_ratchet()` 原先以 `(ts_code, entry_date)` 查 sidecar 后直接把 `bootstrap=true` 的旧合成行交给 `_holding_ratchet()`；生产 `state/a_short/holding_ratchet/ratchet_state.json` 中的旧 bootstrap stop 因而可能成为当前持仓的跨周止损基线，即使该 stop 来自另一周的 bootstrap 上下文。
- 修复链：`main()` → `_apply_holding_ratchet(weekly, state, as_of)` → future-state PIT guard → 删除 `bootstrap is True and last_as_of != as_of` 的 state 行 → `_holding_ratchet(this_week, None)` 重新以本周结构化 `plan.stop`/breakeven bootstrap → `machine.ratchet`、`m67.table`、advice 与 `state[key]` 写回。相同 `as_of` 的 replay 保留原行，跨周非 bootstrap ratchet 仍走原有 stop/disposition anti-rescue。
- 直接消费者/契约：机器权威是 `machine.ratchet`、`entry_exit_size_star.plan.stop` 与 sidecar row；`schemas/a_short_holding_ratchet.schema.json` 未改，`bootstrap`/`last_as_of` 字段语义保持不变。展示 advice 不是 ratchet 数据源；未改 EGS/TopN/生产决策或账户下单边界。
- 负向控制/自审：旧 bootstrap 的荒谬 stop 不得穿透、无关旧 bootstrap 行被清除、同周 replay 仍幂等、未来 `last_as_of` 仍先于过滤而 fail-closed；保留既有跨周 disposition/stop 降级反控与 breach 升档正控。新增 `test_r4b_pipeline_discards_stale_bootstrap_baseline`，并以既有同周 positive control 对照。

#### #13：tracker 日志明确区分日历够龄与缓存覆盖

- 根因：`runners/forward_tracker.py::backfill()` 的 `_mature_as_ofs()` 以日历年龄挑出 pending cohort，而 `_partition_asof_coverage()` 再按 shared cache 的实际交易日覆盖决定 ready/immature/needs_refresh；旧日志把两者都称作“mature/未到 +N trading days”，同一 cohort 会产生相互矛盾的可观测语义。
- 修复链：只改 `backfill()` 四处日志标签：`calendar-age eligible as_of` 表示日历年龄门已满足；`calendar-age eligible cohort(s) lack +N trading-day cache coverage` 表示缓存覆盖门未满足；no-ready 日志也保留 calendar-age 前缀。`_mature_as_ofs()`、`_partition_asof_coverage()`、cache-only 写回和退出码不变。
- 直接消费者/写盘边界：周 launcher/人工运维只消费 stdout 与 `backfill()` 退出码；tracker CSV、`forward_daily.pkl`、ledger settlement、refresh/provider 调用均未改。该修复是 observability-only，不把日志变更当作 ledger progress 或 PASS。
- 负向控制/自审：有日历够龄但缓存只有 3 个交易日的 fixture 时，必须同时看到 calendar-age eligible、lack cache coverage、no cohort has cache coverage，且不再出现旧的“captured but not yet +20 trading days old”；返回仍为 0，无 provider fetch。

#### #12：候选追踪按 as_of 版本化并严格读取前一期

- 根因：`A-EGS/egs_main.py` 原来把所有候选追踪写入同一个 `Result/egs_last_selection_qfq_v1.json`；同一个 canonical `as_of` 重跑会覆盖 run_date，下一次 tracking 只能看到同日记录，无法建立真实上一周 baseline。
- 修复链：`engine/a_short_run_paths.py` 统一提供 `last_selection_version_path(as_of)`、`previous_last_selection_version_path(as_of)`、文件名日期解析与严格 YYYYMMDD 校验。`run_egs()` 只读 `<result_dir>/egs_last_selection_qfq_v1_<as_of>.json` 之前最近的版本；同日、未来文件和旧 singleton 均不作为 prior。读取 envelope 后校验 `schemas/a_short_last_selection.schema.json`，并要求文件名日期等于 payload `as_of` 且严格早于 decision_as_of；校验失败不写新 tracking，避免空 baseline 覆盖事实。写盘为 schema-bound envelope，仍使用既有 atomic writer；旧 singleton 保留但只记录 ignored warning，不删除、不覆盖、不迁移。
- 直接消费者/契约/边界：唯一直接消费者是 `run_egs()` 的上一候选池周内收益/高低点报告与当前 leaver 保留逻辑；`run_egs(backtest_mode=True)` 不读取 mutable prior。新 schema 对记录字段、`price_basis=qfq_anchored_as_of`、`run_date`、`still_in_pool` 和 additionalProperties 做 fail-closed 约束；文件名与 payload 双 source-binding 防止同日自读/错日读取。
- 负向控制/自审：path helper 只选择严格更早版本，忽略 singleton/current/future；schema 拒绝 extra field 与非 canonical as_of；source test 约束 prior envelope load、versioned atomic write 和 legacy 不被 open；effect-contract 的 `A-EGS/egs_main.py` decision/runtime hashes 用固定 Python 实际 inventory 重封。没有读取/删除桌面文件或现有未版本化 artifact。

#### 固定 Python、验证、NOT_VERIFIED 与审查边界

- 固定解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`。本轮聚焦原始终态：`Ran 58 tests in 0.203s ... OK`（#11/#13）；`Ran 12 tests in 0.012s ... OK`（#12 path/schema）；`Ran 48 tests in 41.619s ... OK`（effect contract）；相关 `py_compile` exit `0`；schema meta check `schema OK`。
- 精确聚焦命令：`& 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_gap_data_registry.HoldingRatchetS3bR4bTests tests.phase6.test_forward_tracker_cache_guard`；`... -m unittest tests.test_a_short_run_paths tests.schema.test_a_short_last_selection_schema`；`... -m unittest tests.test_a_short_effect_contract`。
- A-short full lane 原始终态：`Ran 2325 tests in 298.938s ... OK (skipped=3)`；`[full-pack-ledger] RESULT status=PASS exit=0 tests=2325 elapsed=300.8s deadline=860s`；START fingerprint=`4220c0a2e304`。治理门原始终态 `Ran 73 tests in 0.979s ... OK`，`git diff --check` exit `0`（仅 CRLF 转换 warning）。provider/network/live/account/真实周跑/真实 ratchet artifact 刷新/sub-agent/Claude 独立审查/commit/push/merge 均为 `NOT_VERIFIED` 或 `NOT_PERFORMED`，不称 review PASS、ship PASS 或 production PASS。
- 下一步：Codex 完成文档治理门与当前树 A-short full lane；随后 Claude Code 独立审查 `R-ASHORT-KNIFE11-RATCHET-STALE-BOOTSTRAP-STATE`、`R-ASHORT-KNIFE13-FORWARD-TRACKER-MATURITY-LOG-CONTRADICTION`、`R-ASHORT-KNIFE12-LAST-SELECTION-ASOF-BASELINE-OVERWRITE`，PASS 后按项目规则提交。

### 2026-08-03 Claude Code 独立审查 = FAIL（#11；#12/#13 本身通过）

- **Verdict**: FAIL，未提交、未合入。#11 的 pop 判据 `bootstrap is True and last_as_of != as_of` 命中了合法路径——首周恒写 `bootstrap=True`，第二周必然被丢 → 每周重 bootstrap → 跨周 ratchet 永不成立；且 pop 在 `_prev = state.get(key)` 之前，把 P1-1 第二轮刚加的跨周断言绕成不可达。
- **A/B 实测**（同一持仓连续三周，本周止损 10.0 < 上周 10.5）：主树 `W2 stop=10.5/wc=2/bootstrap=False`；本树 `W2 stop=10.0/wc=1/bootstrap=True`。
- **Required 两条**（正文见 register 同一 R-ID）：① 收窄 pop 判据（按陈旧程度或 key 对不上，而非 `!= as_of`）；② 补连续两周正控 + 跨周断言可达反控——full lane `2325 OK` 没抓到，是因为没有用例跑过同一持仓两周。
- **不要返工**：#13 措辞修正、#12 分版本快照（严格更早 + schema + 文件名↔文档 as_of 绑定 + 拒 `>=` + legacy 只告警）都正确。
- **Optional（#12）**：读失败会跳过本周写盘，损坏会自我传播到下周。
- **Verify**: review-evidence:37325941927c。

### 2026-08-03 Codex 修复：#11 review FAIL 收口（不涉及 #03+#04）

#### 本文档内容、作用与追加位置

本 handoff 是 A-short leaf wiring/classification 阶段的详细交接源：记录本刀的根因、实现、调用链、直接消费者、schema/source-binding、写盘边界、负向控制、自审、固定 Python、精确命令和审查边界；`docs/SESSION_LOG.md` 只保留 cycle 摘要，`docs/system_risk_register.md` 保留风险与 Required 单一来源。本节按同日 reverse-chronological 追加在上一条 Claude #11 FAIL 后；后续执行在本文件继续追加同格式小节，不覆盖历史审查记录。

#### #11 当前判定与根因

- 上轮 FAIL 的判断正确：`bootstrap=True and last_as_of != as_of` 把合法的“同一持仓首周 bootstrap”误判为陈旧。第二周进入前被删除后，`_holding_ratchet()` 收到 `None`，`week_count` 每周回到 1，较高的跨周 stop 丢失，且在 `_prev = state.get(key)` 之前清理会让跨周 anti-rescue 失去可达性。
- 本轮修复范围只针对 `R-ASHORT-KNIFE11-RATCHET-STALE-BOOTSTRAP-STATE`；#12/#13 不返工，#03+#04 不涉及，`runners/weekly_screening.ps1` 未改。

#### 实现、调用链与直接消费者

- `runners/a_short_weekly_pipeline.py::_apply_holding_ratchet()` 保留既有 `last_as_of > as_of` future-state PIT 拒绝；从本周 `reports[]` 中只收集 `m67.table.操作 == 持有` 且存在 `machine.stateful_risk.position.entry_date` 的 `(ts_code, entry_date)` compound key。
- 仅删除 `bootstrap is True` 且不在本周 active holding key 集合中的 orphan sidecar 行；同一持仓上周合法 bootstrap 行保留。保留后链路为：`main()` → `_apply_holding_ratchet()` → `runners/a_short_phase5_engine.py::_holding_ratchet()` → `machine.ratchet` / `entry_exit_size_star.plan.stop` / `m67.table` / disposition-advice → `state[key]` → 既有 `save_holding_ratchet()`。
- 直接机器消费者是 `machine.ratchet`、结构化 `plan.stop` 和 sidecar row；中文操作建议只是展示面，不参与 ratchet 基线或清理判定。既有非 bootstrap 跨周 stop/disposition 只升不降和 breach escalation 保持不变。

#### schema、source-binding 与写盘边界

- `schemas/a_short_holding_ratchet.schema.json` 未修改，`bootstrap` 与 `last_as_of` 的字段契约不变；本次补的是 consumer 侧“bootstrap 行必须与本周 held compound key 绑定”的跨字段/跨运行语义，未把渲染文字当机器契约。
- `schemas/a_short_m67_effect_contract.json` 本轮只把 `decision_predicate_sha256["runners/a_short_weekly_pipeline.py"]` 从旧值重封为固定 Python 实际值 `e6e70d69f105ffae07b18278dfb729aaa95f9b845eb325f7593bee00cd865735`；其他既有 #12 effect-contract 变化保留。
- 生产调用仍只写既有 ratchet sidecar/state 位置并遵守原子写路径；本轮测试没有 provider/live/account、没有刷新真实 `state/a_short/holding_ratchet/ratchet_state.json`，没有改变 EGS/TopN、生产决策、订单或账户写盘边界。

#### 负向控制与自审项目

- `test_r4b_pipeline_discards_stale_bootstrap_baseline`：不匹配本周任何持仓的 orphan bootstrap 行不能污染本周 stop，且会被移除。
- `test_r4b_pipeline_preserves_bootstrap_baseline_across_two_weeks`：W1 bootstrap → W2 `week_count=2`、`bootstrap=False`、`ratcheted_stop` 保留 W1 较高值；证明合法首周基线不会被误删。
- `test_r4b_pipeline_bootstrap_baseline_keeps_cross_week_guard_reachable`：保留 W1 bootstrap 时注入跨周降止损写回，仍命中 `跨周止损下降` guard；证明 `_prev` 与 anti-rescue 没被清理动作绕过。
- 既有 same-week 幂等、future-state fail-closed、disposition/stop anti-rescue、breach escalation 和 effect-contract mutation guards 一并复核；未起 sub-agent。

#### 固定 Python、精确命令与原始终态

- 唯一解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`。
- 语法命令：`Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m py_compile 'D:\cnhea\Codex\worktrees\29e0\Stock\runners\a_short_weekly_pipeline.py' 'D:\cnhea\Codex\worktrees\29e0\Stock\tests\test_a_short_gap_data_registry.py' 'D:\cnhea\Codex\worktrees\29e0\Stock\schemas\a_short_m67_effect_contract.json'` → exit `0`。
- 焦点命令：`Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_effect_contract tests.test_a_short_gap_data_registry.HoldingRatchetS3bR4bTests tests.phase6.test_forward_tracker_cache_guard` → `Ran 108 tests in 44.445s ... OK`。
- full lane 命令：`Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' '.tools\full_pack_ledger.py' run a_short 'R-ASHORT-KNIFE11-RATCHET-BOOTSTRAP-PRESERVATION' 'focused 108 OK; preserve same-key W1 bootstrap across W2; orphan bootstrap cleanup; bootstrap anti-rescue reachability; effect contract resealed' 860 -- discover -s tests -p 'test_a_short*.py'` → `Ran 2327 tests in 347.739s ... OK (skipped=3)`；`[full-pack-ledger] RESULT status=PASS exit=0 tests=2327 elapsed=349.4s deadline=860s`。
- 文档/治理命令：`Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency tests.test_readme_route_row_length tests.test_semantic_risk_slice3_guard` → `Ran 73 tests in 1.906s ... OK`。
- 收口核对：`git diff --name-only -- runners/weekly_screening.ps1` 为空；provider/live/account/真实周报与 sidecar artifact、独立 review、commit/push/merge = `NOT_VERIFIED`/`NOT_PERFORMED`。测试终态是 test-pack evidence，不等于 review PASS、production PASS 或 ship PASS。

### 2026-08-03 Claude Code 第二轮独立审查 = FAIL（#11 最后一条腿）

- **Verdict**: FAIL，未提交、未合入。主回归已修好，剩最后一条同类腿。
- **三腿实测**：① 连续两周 `W2 stop=10.5/wc=2/bootstrap=False` **OK**；② 孤儿陈旧行已清 **OK**；③ **停牌周仍失守**——`holdings_manual_review` 旁路持仓不进 `reports[]`，其 bootstrap 行被当孤儿丢，复牌后 `stop 10.5 → 10.0`、重新 bootstrap。
- **Required 一条**（正文见 register 同一 R-ID）：把 `holdings_manual_review` 的 `ts_code` 也算作活跃；该旁路行没有 `entry_date`，用 ts_code 粒度即可（sidecar 行自带 ts_code）。
- **不要返工**：连续两周延续、孤儿清理、`(ts_code, entry_date)` 复合身份、pop 不再绕过跨周断言——四项实测已通过。#12/#13 维持上一轮结论。
- **Verify**: review-evidence:f807ad117ba8；full lane `CACHED GREEN a_short = 2327 OK`（`+2` 为本轮新增用例）。

### 2026-08-03 Codex 修复：#11 二轮 FAIL 最后一条腿（manual-review 旁路；不涉及 #03+#04）

#### 本 handoff 的内容、作用与追加位置

本 handoff 继续作为 A-short leaf wiring/classification 的详细交接源，记录本轮旁路根因、最小改动、调用链、直接消费者、schema/source-binding、写盘边界、负向控制、固定 Python、精确测试命令、原始终态和审查边界；SESSION_LOG 只记 cycle 摘要，system risk register 记 Required 与风险单一来源。本节按同日 reverse-chronological 追加在二轮 Claude FAIL 后，未覆盖历史记录；后续执行仍在本文件追加同格式小节。

#### 根因与最小改动

- 上轮修复只把 `reports[]` 中 `m67.table.操作 == 持有` 且有 `entry_date` 的 `(ts_code, entry_date)` 作为 active。停牌/无价/陈旧价格持仓按设计进入 `holdings_manual_review`、不进 `reports[]`，所以其上一周合法 bootstrap sidecar 行被误删。
- `runners/a_short_weekly_pipeline.py::_apply_holding_ratchet()` 现在同时收集 `holdings_manual_review[].ts_code`。只有 bootstrap 行既不匹配本周 report compound key、也不匹配本周 manual-review `ts_code` 时才作为 orphan 删除。manual-review 周不伪造机器 ratchet；复牌报告出现后仍按 compound key 消费并继续 ratchet。

#### 调用链、直接消费者、schema/source-binding 与写盘边界

- 调用链：`main()` → `_apply_holding_ratchet(weekly, state, as_of)` → reports compound-key + manual-review ts_code active filter → 复牌时 `runners/a_short_phase5_engine.py::_holding_ratchet()` → `machine.ratchet` / `entry_exit_size_star.plan.stop` / `m67.table` / disposition-advice → `state[key]` → 既有 `save_holding_ratchet()`。
- 直接机器消费者仍是 `machine.ratchet`、结构化 `plan.stop` 和 sidecar row；`holdings_manual_review.reason` 只用于人工旁路展示，不成为 ratchet 基线。复合 key 仍保护 re-entry 不继承旧 entry_date。
- `schemas/a_short_holding_ratchet.schema.json` 未修改；sidecar 的既有 `ts_code` 支持旁路保护，`entry_date` 仍只在复牌 report 中完成 source-binding。effect-contract 指纹未变化，`static_contract_error=None`。没有改 EGS/TopN、生产决策、provider/PIT、订单、账户或真实 state artifact 写盘边界。

#### 负向控制与自审

- 新增 `test_r4b_pipeline_preserves_bootstrap_through_manual_review_week`：W1 bootstrap → W2 只有 `holdings_manual_review` 且无 reports → W3 复牌使用更低 stop；断言 W2 保留 W1 行，W3 `week_count=2`、`bootstrap=False`、`ratcheted_stop` 保持 W1 较高值。
- 上一轮 `test_r4b_pipeline_preserves_bootstrap_baseline_across_two_weeks`、孤儿清理、`test_r4b_pipeline_bootstrap_baseline_keeps_cross_week_guard_reachable` 及 future-state/same-week/disposition/breach controls 继续通过；#12/#13 不返工，#03+#04 未触碰，未起 sub-agent。

#### 固定 Python、精确命令与原始终态

- 唯一解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`。
- 语法/单类命令：`$env:PYTHONPATH='D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m py_compile 'D:\cnhea\Codex\worktrees\29e0\Stock\runners\a_short_weekly_pipeline.py' 'D:\cnhea\Codex\worktrees\29e0\Stock\tests\test_a_short_gap_data_registry.py'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_gap_data_registry.HoldingRatchetS3bR4bTests` → py_compile exit `0`；`Ran 45 tests in 0.146s ... OK`。
- 焦点组合命令：`$env:PYTHONPATH='D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_effect_contract tests.test_a_short_gap_data_registry.HoldingRatchetS3bR4bTests tests.phase6.test_forward_tracker_cache_guard` → `Ran 109 tests in 71.289s ... OK`。
- full lane 命令：`Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' '.tools\full_pack_ledger.py' run a_short 'R-ASHORT-KNIFE11-RATCHET-MANUAL-REVIEW-BOOTSTRAP-PRESERVATION' 'focused 109 OK; preserve same-key W1 bootstrap through holdings_manual_review week; W3 resume ratchet; orphan cleanup; anti-rescue reachability' 860 -- discover -s tests -p 'test_a_short*.py'` → `Ran 2328 tests in 472.934s ... OK (skipped=3)`；`[full-pack-ledger] RESULT status=PASS exit=0 tests=2328 elapsed=475.4s deadline=860s`。
- 收口边界：`static_contract_error=None`；provider/live/account/真实周报与 sidecar artifact、独立 review、commit/push/merge = `NOT_VERIFIED`/`NOT_PERFORMED`；测试终态不等于 review PASS、production PASS 或 ship PASS。#03+#04 的 `runners/weekly_screening.ps1` 未产生 diff。

### 2026-08-03 Claude Code 第三轮独立审查 = PASS（#11/#12/#13）

- **Verdict**: PASS，已提交并合入 master。#11 三轮收口完成；#12/#13 维持前两轮结论。
- **三腿复跑**：连续两周 `wc=2/bootstrap=False`；孤儿清理仍生效；**停牌周已修好**——`W1 10.5 → W2 manual_review 行幸存 → W3 复牌 stop=10.5/wc=2/bootstrap=False`。
- **对抗探针（过度保留反控）**：旧仓 `600000.SH|20250101`（stop=3.05）在 manual-review 周被保留，但新 entry_date 复牌得 `stop=10.5/wc=1/bootstrap=True`——**未继承 3.05**，复合 key 仍是基线唯一判据；旧行随后自动清掉。
- **计数**：full lane `CACHED GREEN a_short = 2328 OK`，`2327→2328` 的 `+1` 为新增 manual-review 用例。
- **仍挂 Optional（#12，不阻断）**：读失败跳过本周写盘，损坏会自我传播到下周。
- **Verify**: review-evidence:63adac82ec8a。provider/live 与 `-Account` 实跑 `NOT_VERIFIED`。

### 2026-08-04 Codex 执行：桌面 #07(b) CNINFO orgId 请求形态（不涉及 #03+#04）

#### 本节内容、作用与追加位置

本 handoff 是 A-short leaf wiring/classification 阶段的详细交接源；本节记录 #07(b) 的判断、根因、最小实现、调用链、直接消费者、schema/source-binding、缓存与写盘边界、负向控制、固定 Python、精确测试命令、原始终态、NOT_VERIFIED 项和审查边界。`docs/SESSION_LOG.md` 只保留本轮 cycle 摘要，`docs/system_risk_register.md` 是 R-ID 与风险/Required 单一来源。本节按同日 reverse-chronological 追加在现有 handoff 尾部，不覆盖 #11/#12/#13 历史审查记录；后续执行继续在本文件追加同格式小节。

#### #07(b) 判断、根因与最小改动

- 桌面意见正确：#07(a) 已把 HTTP 200 空公告正确保留为 `未检查`，但没有修复旧请求的机器身份形态；旧 `stock=code,sh/sz` 会在接口层返回 200 空结果，正确契约是 `stock=code,orgId`。因此本刀必须连同“映射/缓存”和“请求参数”一起收口，不能只调整 warning。
- `A-EGS/egs_main.py` 新增官方 map URL `http://www.cninfo.com.cn/new/data/szse_stock.json`、`cninfo_org_id_map_v1` cache key、`code/orgId` 归一化与缓存验证。只接受六位代码和 `gss[h|z]` 编码中末六位一致的 `orgId`；缓存读坏、源 HTTP 非 200、payload 无合法映射、异常或候选 code 缺失均 fail-closed。
- `stage3_ai_clearing::_cninfo_check()` 先规范化 canonical `ts_code` 并从结构化 map 取 `orgId`，再以 `stock=f"{stock_code},{org_id}"` 发公告查询；没有有效 `orgId` 时不发 POST，返回 unknown reason，`cninfo_flag` 继续为 `未检查`，既有 data-health warning 继续承接。原有公告 response/status/shape guard、监管命中 advisory-only 和候选不删除不变。
- #03+#04 明确排除；没有换源、没有恢复生产监管 hard veto、没有改 `runners/weekly_screening.ps1`、没有真实 provider/live/账户运行。

#### 调用链、直接消费者、schema/source-binding 与写盘边界

- 调用链：`run_egs()` → `stage3_ai_clearing()` → `_load_cninfo_org_id_map()`（既有 `load_cache/save_cache` → 官方 map source）→ `_cninfo_check()`（canonical `ts_code` → source-bound `orgId`）→ `http://www.cninfo.com.cn/new/hisAnnouncement/query` → status/JSON/announcements guard → `cninfo_flag` 与 `cninfo_health` → `_cninfo_health_warning()` / `export_data_health(..., sidecar_warnings=...)` → `data_health.json`/汇总。
- 直接消费者只有候选 `cninfo_flag` advisory 展示与 data-health warning；本刀不让 map/公告结果进入 EGS/TopN 排名、候选删除、生产 hard veto、M6.7 machine decision、订单或账户。
- schema 没有新增业务字段；`schemas/a_short_m67_effect_contract.json` 只按固定 Python 实际 inventory 更新 `A-EGS/egs_main.py` 的 `decision_predicate_sha256` 和 `runtime_constants_sha256` 两项。source binding 由固定官方 URL、code/orgId 编码一致性、canonical `ts_code` 精确映射共同约束；未知映射不会降级成 market 短名或“通过”。
- map 使用既有 `CONF["cache_dir"]` 的 `load_cache/save_cache`，cache write 保持既有临时文件 + `os.replace` 原子边界；坏缓存不删除、不覆盖既有官方产物，源已验证但 cache write 失败时只 warning 并使用本次 map。既有 report/data-health 输出写盘路径和原子写策略未改。

#### 负向控制与自审项目

- `tests/test_a_short_cninfo_health.py` 覆盖：valid map 请求精确为 `600900,gssh0600900` 且缓存写入；valid cache 命中不再 GET；缺 code 不发 POST且 reason=`org_id_missing`；map HTTP 失败不发 POST且 reason=`org_id_map_http_status`；orgId 不匹配 payload 不发 POST且 reason=`org_id_map_invalid_payload`；原有 empty/non-200/invalid JSON/invalid announcements/exception 仍保留 `未检查`。
- 反向边界：旧 `600900,sh` 不再作为请求参数；异常映射不会伪造“通过”；监管关键词命中仍只写 advisory、不删候选；没有把中文展示文案作为 map/query 机器契约。#03+#04 的 `runners/weekly_screening.ps1` diff 为空，未起 sub-agent。
- effect-contract 诊断只发现 `A-EGS/egs_main.py` 两项实际 hash 变化，已按 actual inventory reseal；`static_contract_error()` 在效果契约测试中通过。

#### 固定 Python、精确命令与原始终态

- 唯一允许解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`；本轮所有测试、检查和 full runner 均显式使用该路径。
- 专项命令：`$env:PYTHONPATH='D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_cninfo_health` → `Ran 9 tests in 0.627s ... OK`。
- 语法命令：`$env:PYTHONPATH='D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m py_compile 'D:\cnhea\Codex\worktrees\29e0\Stock\A-EGS\egs_main.py' 'D:\cnhea\Codex\worktrees\29e0\Stock\tests\test_a_short_cninfo_health.py'` → exit `0`。
- 效果契约命令：`$env:PYTHONPATH='D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_effect_contract` → `Ran 48 tests in 69.142s ... OK`。
- 影响面聚焦命令：`$env:PYTHONPATH='D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_cninfo_health tests.test_a_short_egs_market_environment tests.test_a_short_effect_contract tests.phase6.test_egs_sw_industry_and_watch_pool_health tests.test_semantic_risk_slice3_guard tests.phase6.test_weekly_screening_guardrails` → `Ran 100 tests in 72.589s ... OK`。
- 官方 full lane：`$env:PYTHONPATH='D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' 'D:\cnhea\Codex\worktrees\29e0\Stock\.tools\full_pack_ledger.py' run a_short 'R-ASHORT-KNIFE7-CNINFO-ORG-ID-REQUEST-SHAPE' 'focused 100 OK; CNINFO code-to-orgId cache and source-bound request shape; missing or invalid orgId remains unknown; no source replacement; effect contract sealed' 860 -- discover -s tests -p 'test_a_short*.py'` → START fingerprint=`2200e426e083`；`Ran 2333 tests in 468.029s ... OK (skipped=3)`；`[full-pack-ledger] RESULT status=PASS exit=0 tests=2333 elapsed=470.2s deadline=860s`。
- 文档治理命令：`$env:PYTHONPATH='D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency tests.test_readme_route_row_length tests.test_semantic_risk_slice3_guard` → `Ran 73 tests in 1.950s ... OK`。`git diff --check` exit `0`（仅 CRLF warning）；`git diff --name-only -- runners/weekly_screening.ps1` 为空。

#### NOT_VERIFIED、审查/提交边界与下一步

- 未执行真实 CNINFO map/query HTTP、provider/live、账户周跑、真实生产/私密 artifact 刷新或自动下单；因此不把离线测试称为实盘验证、production PASS 或 ship PASS。真实 CNINFO 对 valid orgId 是否返回非空公告仍 `NOT_VERIFIED`。
- Claude Code 独立审查尚未进行；`sub-agent`、`commit`、`push`、`merge` 均 `NOT_PERFORMED`。下一步：`Claude Code：独立审查 R-ASHORT-KNIFE7-CNINFO-ORG-ID-REQUEST-SHAPE；PASS 后按项目规则提交。`

### 2026-08-03 Claude Code 独立审查 = FAIL（#07b cninfo orgId）

- **Verdict**: FAIL，未提交、未合入。方向对，格式假设错。
- **实测（用被审代码自己的规范化函数跑真实 payload）**：6227 行 → 只留 1403 条（丢 77.5%）；orgId 真实前缀分布为纯数字 3481 / `gfbj` 943 / `gssh` 881 / `gssz` 599 / `nssc` 207 / `GD` 37 / `qsgn` 29 / `gshk` 20，正则只认 `gss[hz]`。本周 15 只候选 **8 只**解析不到 → 仍「未检查」；独立实打 `603259.SH`（orgId `9900035584`）得 2 条真公告，证明不是没公告。
- **Required 三条**（正文见 register 同一 R-ID）：① source binding 改用行内 `code` 字段匹配，不解析 orgId 结构（放宽后实测 6227/6227、候选 15/15）；② 市场后缀换确定来源（56% orgId 是纯数字，没有 h/z 字母）；③ 补真实五类前缀形态的覆盖用例 + 覆盖率下限断言。
- **Optional**：as-of 跑的 `cache_ttl` 为 10 年且 miss 不重取，新上市股票会永久「未检查」。
- **不要返工**：失败原因分类接进 #07a health、重复 code 整表拒、`column`/`plate` 保持原样——都正确。
- **Verify**: review-evidence:92f18e931d60；full lane `CACHED GREEN 2333 OK` 全绿未抓到，正是 Required ③ 的理由。

### 2026-08-04 Codex 修复 #07(b) 审查 Required ①–③ + 缓存 Optional（不涉及 #03+#04）

#### 本节内容、作用与追加位置

本 handoff 继续作为 A-short leaf wiring/classification 阶段的详细交接源；本节 supersede 上一节“只接受 `gss[hz]`”的实现描述，完整记录真实形态缺陷、四项修复、调用链、直接消费者、schema/source-binding、cache/写盘边界、负向控制、固定 Python、精确命令、原始终态和审查边界。`docs/SESSION_LOG.md` 只放 cycle 指针，`docs/system_risk_register.md` 保存 R-ID 单一风险详情；本节按 reverse-chronological 追加在 2026-08-03 Claude FAIL 后，不覆盖历史。

#### 上轮 FAIL 判断与全修方案

- 上轮三条 Required 判断全部正确：真实 `szse_stock.json` 中 `orgId` 有纯数字、`gfbj`、`gssh`、`gssz`、`nssc` 等形态，不能解析 orgId 内部结构；市场后缀必须来自确定的 code 来源；测试必须锁住五类形态和覆盖率下限。
- `A-EGS/egs_main.py::_cninfo_org_id_entry()` 现在只校验源行 `code` 为六位数字、`orgId` 非空且不含逗号/空白/控制字符；不再用正则解析 orgId。市场由 code 确定映射：`6/9→.SH`、`0/2/3→.SZ`、`4/8→.BJ`，缓存回读走同一绑定函数。
- `_normalize_cninfo_org_id_map()` 对可识别 rows 施加至少 80% 的规范化覆盖率，不足则整张 map invalid、保持 fail-closed；重复 code 对应不同 orgId 仍整表拒绝。新增离线 fixture 覆盖纯数字 / `gfbj` / `gssh` / `gssz` / `nssc` 五类，断言映射数量和每个 `ts_code`。
- 上轮缓存 Optional 也收口：Stage3 把本批 canonical candidate code 集合传入 `_load_cninfo_org_id_map(required_ts_codes)`；valid cache 缺当前候选会 source refresh 一次。若 refresh HTTP/JSON 失败，保留已验证 cache 给已存在候选使用，缺失候选仍返回结构化 map failure reason；不循环请求，不把缺失转为“通过”。

#### 调用链、直接消费者、schema/source-binding 与写盘边界

- 调用链：`run_egs()` → `stage3_ai_clearing()` → required-code-aware `_load_cninfo_org_id_map()` → cache/source map normalize/validate → `_cninfo_check()` canonical `ts_code` lookup → `hisAnnouncement/query` with `stock=code,orgId` → response guard → `cninfo_flag`/`cninfo_health` → 既有 `_cninfo_health_warning()` / `export_data_health(..., sidecar_warnings=...)`。
- 直接消费者仍只有候选 `cninfo_flag` advisory 展示和 data-health warning；map/公告不进 EGS/TopN 排名、候选删除、生产 hard veto、M6.7 machine decision、订单或账户。
- 无新增业务 schema；`schemas/a_short_m67_effect_contract.json` 只更新 `A-EGS/egs_main.py` 的实际 decision/runtime hash。source binding 是源行 code + code-derived market + orgId delimiter guard + canonical `ts_code`，不是 orgId 前缀猜测。
- cache 继续使用既有 `CONF["cache_dir"]`、`load_cache/save_cache` 和临时文件+`os.replace` 原子边界；本轮不清理/迁移既有 cache 或官方 report/data-health artifact，不改 provider/live 或 #03+#04 写盘边界。

#### 负向控制与自审项目

- 新增五类真实形态/覆盖率测试：纯数字 orgId（含 `603259` 类形态）、`gfbj`、`gssh`、`gssz`、`nssc` 均解析；code 决定 `.SH/.SZ`，不读取 orgId 内部字母。
- 新增 cache partial miss 回归：缓存缺本批 code 时只刷新一次并使用新 map；缓存完整时不 GET；HTTP/非法 payload/异常、低覆盖率、逗号污染、code 缺失均不发公告 POST或保持 `未检查`；既有 empty/non-200/invalid announcements/exception 与 advisory 不删候选继续通过。
- 自审确认：旧 `stock=code,sh/sz` 无残留请求写点；`runners/weekly_screening.ps1` 无 diff；未起 sub-agent；未触碰 #03+#04。

#### 固定 Python、精确命令与原始终态

- 唯一解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`。
- 专项：`$env:PYTHONPATH='D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_cninfo_health` → `Ran 11 tests in 0.437s ... OK`。
- 语法：`$env:PYTHONPATH='D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m py_compile 'D:\cnhea\Codex\worktrees\29e0\Stock\A-EGS\egs_main.py' 'D:\cnhea\Codex\worktrees\29e0\Stock\tests\test_a_short_cninfo_health.py'` → exit `0`。
- 影响面聚焦：`$env:PYTHONPATH='D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_cninfo_health tests.test_a_short_egs_market_environment tests.test_a_short_effect_contract tests.phase6.test_egs_sw_industry_and_watch_pool_health tests.test_semantic_risk_slice3_guard tests.phase6.test_weekly_screening_guardrails` → `Ran 102 tests in 51.832s ... OK`。
- 官方 full lane：`$env:PYTHONPATH='D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' 'D:\cnhea\Codex\worktrees\29e0\Stock\.tools\full_pack_ledger.py' run a_short 'R-ASHORT-KNIFE7-CNINFO-ORG-ID-REQUEST-SHAPE' 'focused 102 OK; bind by source-row code; accept numeric/gfbj/gssh/gssz/nssc orgIds; deterministic market; coverage floor; cache miss refresh; fail-closed unknown' 860 -- discover -s tests -p 'test_a_short*.py'` → START fingerprint=`165357abecef`；`Ran 2335 tests in 323.538s ... OK (skipped=3)`；`[full-pack-ledger] RESULT status=PASS exit=0 tests=2335 elapsed=325.4s deadline=860s`。
- 文档治理/最终门：`$env:PYTHONPATH='D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency tests.test_readme_route_row_length tests.test_semantic_risk_slice3_guard` → `Ran 73 tests in 0.948s ... OK`；`git diff --check` exit `0`（仅 CRLF warning）；`git diff --name-only -- runners/weekly_screening.ps1` 为空。测试证据不等于独立 review PASS、production PASS 或 ship PASS。

#### NOT_VERIFIED、审查/提交边界与下一步

- 本轮未执行真实 CNINFO map/query、provider/live、账户周跑、真实 artifact 刷新或自动下单；真实接口实盘结果仍 `NOT_VERIFIED`。Claude Code 独立审查尚未完成，`sub-agent/commit/push/merge=NOT_PERFORMED`。
- 下一步：`Claude Code：独立审查 R-ASHORT-KNIFE7-CNINFO-ORG-ID-REQUEST-SHAPE 的 Required ①–③ 与缓存 Optional；PASS 后按项目规则提交。`

### 2026-08-03 Claude Code 第二轮独立审查 = PASS（#07b cninfo orgId）

- **Verdict**: PASS，已提交并合入 master。三条 Required + 上轮 Optional 全部收口。
- **对真实源实测**：`6227 → 6227`，覆盖率 **1.0000**、dropped **0**（上轮 1403 / 丢 77.5%）；本周 15 只候选解析失败 **0**（上轮 8 只）；80% 地板余量 1245 行。市场推导抽查含 `688981→.SH`、`900901→.SH`、`430047→.BJ` 全对。
- **五条植入控制全 PASS**：覆盖率地板 70% 整表拒 / 冲突重复整表拒 / 含逗号·空白·控制符的 orgId 一律丢弃（防污染 `code,orgId` 请求）/ 缓存缺必需候选触发重取 / 已覆盖则不重取。
- **Verify**: review-evidence:cb12b83185f2；full lane `CACHED GREEN 2335 OK`（`+2` 新增用例）。
- **仍 NOT_VERIFIED**：真实周跑的逐票命中率——(a) 的 warning 是否噤声要等下次 `-Account` 周跑，那是 (a)+(b) 的天然验收正控。

### 2026-08-04 Codex 执行：桌面 #03+#04 M6.7 failure closeout（OPEN / NOT_VERIFIED）

#### 本节内容、作用与追加位置

本节是 A-short leaf wiring/classification 阶段对桌面 #03+#04 的详细执行交接，记录本轮判断、根因、最小修复、调用链、直接消费者、schema/source-binding/写盘边界、负向控制、固定 Python、原始终态、NOT_VERIFIED 项和审查/提交边界。`docs/SESSION_LOG.md` 顶部只保留本轮 cycle 摘要，`docs/system_risk_register.md` 顶部保存 `R-ASHORT-KNIFE03-04-M67-FAILURE-CLOSEOUT` 的单一风险详情；本节按同日 reverse-chronological 规则追加在现有 handoff 末尾，不覆盖 #07b/#11/#12/#13 历史记录，后续同一刀继续在本文件追加。

#### 意见判断、根因与修复

- 桌面 #03「post-EGS M6.7 失败早退跳过 Stage 5」与 #04「失败 receipt/helper 把 health 变成空表面」判断正确，不能分开修；共同根因是四条 post-EGS failure branch 直接 `exit`，且失败写盘在 final launcher/health closeout 之前发生。
- `runners/weekly_screening.ps1` 现在用显式 `M67InvocationState`、失败原因/码、`FinalExitCode` 和 `IvFeedReady` 表示状态。`analysis_input_missing`、IV failure、account path missing、weekly pipeline failure 全部经 `Set-M67Failure -Directory ...` 汇聚；首个正式失败码不被后续步骤覆盖，post-EGS 分支不再退出。
- `Write-M67FailureReceipt -DeferHealth` 先原子写 failed receipt，health 延后；Stage 5 采用 `complete/failed/skipped/historical` 矩阵。complete 才绑定同一 source/as-of 的 raw regime + M6.7 report；failed、semantic-risk skip、historical 走 daily-safe 或 not-applicable 路径，不能传空/伪造 M6.7 参数。最终只在 closeout 处退出一次。
- final closeout 原子写 launcher manifest，保留成功前置 sidecars，requested live 固定补齐九个 pipeline；health 只调用一次。三件套（launcher/health/pipeline manifest）缺任一或失败 receipt 存在时，当前 health surface 作废并输出 `UNAVAILABLE`，但保留失败 receipt 与 manifest。

#### 调用链、直接消费者、schema/source-binding 与写盘边界

- 调用链：`weekly_screening.ps1` EGS success → IV/M6.7 invocation → `Set-M67Failure` / failed receipt → Stage 5 daily/full regime runner → atomic launcher manifest → health closeout。
- 直接消费者：Stage 5 runner 参数、pipeline outcome manifest、health summary/data-health 与失败 receipt SHA。EGS/TopN、M6.7 decision predicate、position/order/account/provider 不在本刀消费者范围。
- schema：本轮没有新增或改业务 schema，复用现有 M6.7 outcome、health/publish receipt schema。source binding：complete 的 raw regime 与 M6.7 report 必须同一 analysis input/as-of；failed/skipped 只允许 daily-safe as-of/regime 参数；可用 IV feed 才可作为 optional daily input。
- 写盘：post-EGS failure 先失效旧 M6.7/health/pipeline/launcher surface，再用临时文件 + `Move-Item` 原子写 receipt/launcher/health；失败 health 绑定 receipt SHA；缺 pipeline manifest 写 `missing_outcome`，不写成功假象。没有清理或覆盖用户既有无关产物。

#### 负向控制与自审项目

- 新增 `tests/test_a_short_weekly_screening_m67_failure_closeout.py`：四个 failure aggregator call、post-EGS 无 branch exit、唯一末尾 exit、complete/failed 参数隔离、skip/historical、atomic launcher/health、九个 requested pipeline。
- `tests/test_a_short_weekly_sidecar_health.py`：failed receipt 下成功前置 sidecar 保留、九个 `missing_outcome`、failed/degraded、receipt SHA；既有 phase6/review1 测试已从旧 `exit 21/22/23` 迁移为统一 failure aggregator 契约。
- 自审结果：四状态矩阵、failed daily-only 无 raw/M6.7 伪造、首个失败码保留、receipt/manifest/health source binding、stale surface invalidation、incomplete health fail-closed、唯一末尾退出均已静态/功能检查。第一次 full lane 捕获了旧测试断言残留，修正测试后以最新 runner fingerprint 重跑；PowerShell 混合换行解析问题也已修正为 CRLF。

#### 固定 Python、精确命令与原始终态

- 唯一解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`；版本：`Python 3.13.8`。本轮没有调用 PATH `python/python3`、bundled Python 或其他解释器。
- focused：`& 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_weekly_screening_m67_failure_closeout tests.test_a_short_weekly_sidecar_health tests.phase6.test_weekly_screening_guardrails` → `Ran 68 tests in 10.589s ... OK`。
- extended：同命令追加 `tests.test_a_short_review1_knives_6_10` → `Ran 89 tests in 15.460s ... OK`。
- full lane：`.tools/full_pack_ledger.py run a_short 'R-ASHORT-KNIFE03-04-M67-FAILURE-CLOSEOUT' 'post-EGS M6.7 failure closeout, daily-only regime continuation, truthful launcher/health, stale-output negative controls' 860 -- discover -s tests -p 'test_a_short*.py'`（以固定 Python 和绝对工作树路径调用）→ `Ran 2341 tests in 297.848s ... OK (skipped=3)`；`RESULT status=PASS exit=0 tests=2341 elapsed=299.5s deadline=860s`；fingerprint `8cb7e493f12f`。
- 治理/语法：`tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency tests.test_readme_route_row_length tests.test_semantic_risk_slice3_guard` → `Ran 73 tests in 0.904s ... OK`；PowerShell parser=`POWERSHELL_PARSE_OK`；四个测试文件 py_compile exit `0`；`git diff --check` exit `0`。

#### NOT_VERIFIED、审查/提交边界与下一步

- 未执行真实 provider/live/account/`-Account` 周跑、真实 sidecar/artifact 刷新或自动下单；离线 focused/full 证据不等于实盘、生产或 ship PASS。没有验证真实四类 failure 在生产数据上的 artifact 形状，只验证了静态契约与离线负向控制。
- Claude Code 独立审查尚未完成；本轮未启动 sub-agent，未 commit/push/merge。当前工作树改动仍待 reviewer 判断，不能在本 executor 交接中称 review PASS。
- 下一步：`Claude Code：独立审查 R-ASHORT-KNIFE03-04-M67-FAILURE-CLOSEOUT；核对四状态矩阵、失败收据 SHA、成功 sidecar 保留、九个 pipeline outcome 与唯一末尾退出；PASS 后按项目规则提交。`

### 2026-08-03 Claude Code 独立审查 = PASS（#03+#04 M6.7 失败收口）

- **Verdict**: PASS，已提交并合入 master。规格九条实现项全部成立。
- **静态出口枚举**：9 处早退全在 EGS 之前 + `:406 exit $EgsExitCode` + 末尾单点 `:876 exit $FinalExitCode`；M6.7/Stage5/收尾无早退。
- **四处状态赋值实读真实文件核对**（不采信过滤 diff）：`IvFeedReady`(:578) 与 `M67InvocationState='complete'`(:679) 均在成功分支；`account_path_missing` 先置 `$RunM67=$false`(:663)；`:670` 的门防止已失败后仍跑 pipeline。
- **两条植入控制均被抓到**：删 `:670` 的状态门 / 把 `iv_feed_failed` 的 receipt 目录改错 → 各得 `FAILED (failures=5)`；植入后 `cmp` 逐字节还原。
- **Optional**：lane 内新测试全为源码文本断言，post-EGS 失败路径无端到端执行覆盖（`-PythonExe` 只收固定主 Python，无法桩替 pipeline）。正文见 register 同一 R-ID。
- **Verify**: review-evidence:c4d7c7cdeb9b；full lane `RESULT status=PASS exit=0 tests=2341`。

## 2026-08-04 Codex execution: desktop #06 (OPEN / NOT_VERIFIED)
### This document's content, role, append position, and format

This handoff remains the detailed same-phase A-short leaf-wiring/classification handoff. Its role is to preserve the implementation judgment, root cause, call chain, direct consumers, schema/source-binding and write boundaries, negative controls, exact fixed-Python evidence, NOT_VERIFIED boundary, and the next reviewer command. This section is appended at EOF in reverse chronological order; future same-phase A-short execution/review entries append another dated section below it and do not rewrite earlier entries. `docs/SESSION_LOG.md` carries only the short cycle pointer, while `docs/system_risk_register.md` is the single detailed risk record for `R-ASHORT-KNIFE06-PRE-HOLIDAY-CASH-GUARD`.

### Judgment and optimized repair

The desktop #06 plan is correct. I executed it with three review-hardening constraints: the producer binds the forward calendar to `decision_as_of` rather than `price_data_through`; the final weekly run uses one validated official open/closed calendar and selects only a gap of at least five closed days beginning by the next seven-day weekly run; and only raw regime `attack` exempts the conservative `0.8` factor. `unknown`, `shock`, `defense`, and `contraction` are not treated as an exemption. The structured control is normalized in the analysis consumer and revalidated at the `_allocate_cash` entry with the weekly `as_of`, so a direct caller cannot supply an unbound numeric factor.

### Root cause and repair

The old EGS fields were placeholders (`is_pre_holiday_window=False`, `holiday_days_ahead=None`, `next_trade_date=None`) and weekly allocation had no consumer. The repair adds `A-EGS/egs_main.py::get_trade_calendar_context()` and strict `cal_date,is_open` normalization; `run_egs()` passes that context through `export_analysis_input()`; weekly `main()` consumes it through `_pre_holiday_control_from_analysis()` and `_normalise_pre_holiday_control()`; and `_allocate_cash()` scales only `available_cash` and `new_exposure_capacity` before the existing deterministic build allocation. Existing holding rows are outside the allocator's `操作=建仓` set and remain untouched.

### Call chain, consumers, schema/source binding, and write boundary

- Call chain: `run_egs()` → `get_trade_calendar_context(decision_as_of)` → `export_analysis_input()` → `analysis_input.market_context.trade_calendar` → weekly `main()` → `_pre_holiday_control_from_analysis()` → `_normalise_pre_holiday_control()` → `build_weekly_report()` → `_allocate_cash(..., as_of=...)` → `weekly.cash_allocation.pre_holiday_control` plus the new-entry cash/capacity summaries.
- Direct consumers: the weekly cash allocator and its validator are the decision consumers; the analysis-input calendar and weekly cash summary are machine-readable audit surfaces. Human advisory text is not used as a predicate.
- Schema/effect contract: `schemas/a_short_weekly_report.schema.json` requires the structured control when sized cash allocation exists. `schemas/a_short_m67_effect_contract.json` records `is_pre_holiday_window`, `holiday_days_ahead`, and `next_trade_date` with their consumers, terminal surfaces, mutation evidence, and fixed-Python hashes.
- Source binding: `calendar_source=tushare.trade_cal`, official fields `cal_date,is_open`; `decision_as_of` is separate from `price_data_through`; positive windows require a valid source, source date equal to weekly `as_of`, a later next trade date, and at least five closed days. The analysis contract accepts legacy fixtures with no positive window by falling back to its bound `trade_date`, but a positive window without the official source is rejected.
- Write boundary: existing EGS cache/write paths and weekly report/schema validation are reused; cache persistence remains atomic through `save_cache`; no provider/live/account run or production artifact refresh occurred.

### Negative controls and self-review

The new regression file covers the 20260928 positive seven-day closure, 20260921 two-weeks-early negative, four-closed-day negative, malformed calendar fail-closed, unknown `0.8`, attack `1.0`, capacity scaling, invalid/unbound source and clock, and direct allocator calls without `as_of`. Existing weekly and holding consumers remain in the final full lane. The phase6 IV fixtures changed in this section only add fields already required by the current IV schema so the EGS→weekly consumer tests reach the intended #06 path.

### Fixed Python, exact tests, raw terminal state, and review boundary

- Governance: `... -m unittest tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency tests.test_readme_route_row_length tests.test_semantic_risk_slice3_guard` → `Ran 73 tests in 1.459s ... OK`; full-pack `check a_short` → `CACHED GREEN — a_short = 2348 OK`, no rerun required.

- Fixed interpreter: `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`; version: `Python 3.13.8`.
- `... -m unittest tests.test_a_short_pre_holiday_cash_guard` → `Ran 7 tests in 4.157s ... OK`.
- `... -m unittest tests.test_a_short_weekly_pipeline` → `Ran 521 tests in 90.084s ... OK`.
- `... -m unittest tests.test_a_short_pre_holiday_cash_guard tests.test_a_short_effect_contract tests.test_a_short_effect_consumer_probe tests.test_a_short_review1_knives_6_10 tests.phase6.test_egs_analysis_input_contract` → `Ran 102 tests in 79.598s ... OK`.
- `... -m unittest tests.phase6.test_egs_analysis_input_contract` → `Ran 11 tests in 9.190s ... OK`.
- Full lane: `[full-pack-ledger] START lane=a_short deadline=860s fingerprint=e5ed58a41494`; `Ran 2348 tests in 451.433s`; `OK (skipped=3)`; `[full-pack-ledger] RESULT status=PASS exit=0 tests=2348 elapsed=453.6s deadline=860s`.
- Fixed-Python `py_compile` exit `0`; `git diff --check` exit `0` with only normal CRLF warnings. No provider/live/account/real weekly run, sub-agent, independent review, commit, push, or merge was performed; those remain `NOT_VERIFIED` / `NOT_PERFORMED`.
- Next command: `Claude Code：独立审查 R-ASHORT-KNIFE06-PRE-HOLIDAY-CASH-GUARD；通过后按项目规则提交。`

## 2026-08-04 追加：Claude Code 独立审查 #06（节前减仓接线）= PASS

- **结论**：PASS，已提交。桌面 #06 三条已定口径全部按指定形态落地——`attack` 唯一豁免（举证式，#08 落地后自动生效）、
  触发判据是「as_of 后至 as_of+7 之间存在 ≥5 天休市」而非规格字面的节前 2 日、只压新建仓的钱不动已有持仓。
- **三条植入控制均被抓到**：中和 `cash_factor` 折扣 → consumer 红；只摘 `and gap_start <= next_weekly_run` →
  两周前反控 `FAILED (failures=1)`；`PRE_HOLIDAY_MIN_CLOSED_DAYS` 5→4 → 四天反控 `FAILED (failures=1)`。
  三次均 `filecmp` 逐字节还原 True。附带证明 effect-contract 指纹门是活的。
- **独立重算**：伪造 `calendar_source` 被拒；同组 reports 在 1.0 vs 0.8 下 allocated 由 99760.0 压到 80040.0。
- **测试落点**：`+7` 全在 `test_a_short*.py` 选择器内（避开了 #03+#04 的坑）；lane 外的
  `tests.phase6.test_egs_analysis_input_contract` 由我单独跑 `Ran 11 tests ... OK`。
- **Optional 四条**（默认分支不自洽 / `next_trade_date` 叶登记措辞 / validator 够不着权威 / SESSION_LOG 多一个标签）
  正文见 register 同一 R-ID。
- **Verify**: review-evidence:3544906e5d33；full lane `CACHED GREEN a_short = 2348 OK`。

## 2026-08-04 追加：#06 四条 Optional 自修自审 = PASS

- **修了什么**：① `_allocate_cash` 单一归一化路径、`as_of` 必填（删掉会产出 `source_as_of: None` 的默认分支）；
  ② `next_trade_date` 叶改记 `m67_main_decision` + 改正 mutation_evidence；
  ③ `validate_weekly_report` 加 `expected_pre_holiday_control`，`main()` 传入 analysis_input 派生的控制；
  ④ 折掉 SESSION_LOG 超模板的 `Governance` 标签。
- **为什么**：①是死分支与新 schema 不自洽；②叶登记措辞与实际行为不符；③校验腿的权威链终点原来是它自己，
  看不见「窗口被整体写成 false」这种自洽形状；④极简模板精确集合。
- **验证命令与结果**：focused `tests.test_a_short_pre_holiday_cash_guard tests.test_a_short_industry_theme
  tests.phase6.test_egs_margin_coverage tests.phase6.test_egs_analysis_input_contract` → `status=PASS exit=0 tests=62`；
  full lane `RESULT status=PASS exit=0 tests=2350 elapsed=414.3s deadline=860s`（fingerprint `e89706d37ae3`，`2348→2350` 的 `+2` 为本轮新增两条强制腿）。
- **失效旧结论**：上一轮审查记的 Optional ①②③④ 全部作废（已修）；`validate_weekly_report` 不再是纯形状校验器，
  在生产路径上它已绑定 analysis_input 的交易日历。
- **下一步注意**：真实 `trade_cal` 取数与带 `-Account` 的真实周跑仍未验；天然验收正控是 2026-09-28 那次周跑。

## 2026-08-04 追加：两条用户裁决（#14 升为刀 / #16 裁定「接」）+ 队列重排

**改了什么**：上方队列表按本日实际进度刷新——已合入 master 的 8 项打 ✅（#05 / #07a / #07b / #11 / #12 / #13 / #03+#04 `a66e7340` / #06 `a41c005c`），并落两条用户裁决。

**裁决一 · #14 由「记账」升为一把刀（★★☆☆☆）**

- **为什么改**：原判「纯记账、不改代码」建立在「系统已经正确记了 warning」上，但实读 `result/a_short/20260803/rank_universe_reconciliation.csv` 后这个前提不成立：1437 只 L0 的排除理由只有 `l1_industry_leader_elim` 351、`l2_crash_veto` 251、`l2_margin_growth_veto` 8、`l2_espq_valuation_veto` 8，**没有任何一条与历史长度有关**。
- **事实**：候选打分池 `full_count=819`，其中 `short_history_candidate_count=33`（4.0%）可用收盘价不足 61 根，**这 33 只全部照常进入排名**，用不足样本算出的 ATR / 位置分位与满历史票同台竞争。本周 15 只入选票的 `price_observation_count` 全为 64-65 根，即这周没有短史票进观察池——**是没撞上，不是被拦住**。
- **本刀要做什么**：给「历史不足」一个明确处置——要么加一条 L2 级排除理由把 <61 根直接剔出排名，要么标成低置信度、禁止进 Tier1。两条路都必须同刀带正反控制（正控：造一只 40 根的票，断言它拿不到席位；反控：64 根的票不受影响）。
- **不能做什么**：不得只加一个字段/一条 warning 就算完——那正是本条被误判成「记账」的原因。
- **基线缺口**：`short_history_candidate_count` 是本周才加的指标，前 10 周 `data_health.json` 都没有该字段，**无历史基线可判 4.0% 是否偏高**。本刀不负责补基线，但实现后应让该计数进入既有 data_health 趋势。

**裁决二 · #16 全市场融资过热：裁定「接」（★★★☆☆，1 刀）**

- **性质定性（实读证据）**：这是**疏忽不是有意留白**。`A-EGS/EGS v7.4.md:284` 明确把「全市场风险提示（解禁潮、政策突变、**融资过热**等）」写进了设计输出，而 `A-EGS/egs_main.py:5971` 至今只有一行占位 `env.append("融资过热判断：待接入两融余额历史分位")`，紧邻的动量因子有效性判断则是真在算的。全仓无任何「已决定不做」的记录。
- **别混淆的同名物**：v14.2 规格里的融资规则（`:288` 融资余额>流通市值 12% → 盈亏比 2.0:1、`:324` 融资余额占流通市值比因子 >8%）是**逐票**两融，早已在跑（其数据源现状即原 #15）。本条指的是**全市场两融余额的历史分位**，两者不是一回事。
- **本刀要做什么**：① 取全市场两融余额的历史序列并算当前分位；② **同刀定消费点**——过热要压什么（总仓位、新建仓上限、还是风险等级），不定就别开工，否则新增叶立刻悬空、撞 #09 的账本；③ 契约侧照 #06 的做法重封（叶账本 + `leaf_effect_overrides` + 指纹）。
- **可复用 #06 的形状**：#06 刚证明了「生产者 + 消费者 + 举证式门 + 反向控制」这套模板可行，本刀按同一形状走即可，不必另起设计。

**验证命令与结果**：本次为纯文档改动，未跑测试；提交由 `.githooks/pre-commit` 的两道守卫把关（route 14 OK + doc-governance 41 OK）。

**失效旧结论**：① 「#14/#15 纯记账 0 刀」作废——#15 已移除（处理逻辑本就正确、非缺陷），#14 升为刀。② 「#16 做 / 显式记『已决定不做』」二选一作废——已裁定「接」。③ 约束②「#06 反向依赖 #08-market_regime」作废——#06 已用举证式豁免落地。

**下一步注意**：按「先易后难」，下一刀建议 **序 12 #08 northbound 接线**（★★☆☆☆）——它是剩余项里唯一「生产者已经在跑、消费者已经写在 v14.2 规格里」的，两头都现成，是 #06 之后最省的一把；序 13 liquidity 虽同为 ★★☆☆☆ 但缺消费点，须先定用途，别排在前面。

## 2026-08-04 追加：六条用户裁决一次性落定（#10×2 / #14 / #16 / #08-breadth / IV-feed 验证刀）

**改了什么**：上方队列表的序 8、13、14、15、18、19 按本日用户裁决更新，并新增序 20（IV feed 依赖关系验证刀）。桌面清单 `C:\Users\cnhea\Desktop\a_cc_testrun1.md` 同步写入同样的口径。

**为什么改**：这六条此前都卡在「等用户拍板」，实现方若自行解释会各走各的。以下口径**实现不得再自行解释**。

| # | 裁定 | 关键理由（用户采纳的那条） |
|---|---|---|
| 1 · #10 价格基准 | **统一成「上一个已收盘交易日」**，即 canonical 现有行为；显式 `-AsOf` 不再改变价格基准，研究口径另开显式开关（如 `-PriceBasis close`） | 主路径不得存在两种行为；`weekly_screening.ps1:260` vs `:276` 的分歧就此收敛 |
| 2 · #10 资金流容差 | **允许退一日**，取不到参考日即回退前一交易日，并在产物显式标明实际用日 | 节后资金流延迟发布常见，为此废掉整个大单流向因子不划算；但退一日必须可见、不得静默 |
| 3 · #14 短史候选 | **降级不排除**：可进池打分、保留可见性，禁止进 Tier1 与最终建议 | 61 根的含义是「指标算不稳」不是「票不好」；直接排除会系统性错过次新股 |
| 4 · #16 融资过热 | **压总仓位**，复用 #06 的现金系数杠杆；不走「提高最低盈亏比门槛」 | 全市场杠杆冲高是系统性回撤前兆，压仓位最直接；盈亏比那条会与 Rule 10 既有的环境分档互相抵消 |
| 5 · #08 breadth | **全市场口径**（不限主板），字段名须写明 | 这些数喂的是 regime 判定，判的是市场情绪不是可买范围；且 v14.2 `:154` 的阈值（连板≥5、跌停<50）按全市场量级定，只数主板会让阈值系统性偏松 |
| 6 · #08 volatility | **先花一刀验证 IV feed 是否依赖 EGS 输出**（新增序 20），验完再定「调换次序 / EGS 两趟 / 判定挪 pipeline」 | 三条路的成本与风险差别全取决于这个依赖事实；把「判定挪 pipeline」当默认解会让契约叶永远为空，等于用换地方算绕过悬空问题 |

**仍未决（不得开工）**：**#08 liquidity** —— `market_turnover_amount` / `median_amount_20d` 接出来影响什么没有结论。v14.2 的 regime 触发条件里**没有成交额这一项**，硬接等于在规格之外发明判据；未定用途前接线必造 `true_dangling` 叶。本轮用户未答此条。

**顺带定死的非决策事实**：**#08 market_regime 不需要用户裁决** —— v14.2 `:149-154` 已把四态触发条件与参数定死（防御 单只25%/总仓50%、震荡 40%/60%、进攻 50%/80%、收缩期禁止新建仓），`:110` 另定进攻期≥1.5:1 / 防御期≥2.0:1。它缺的是**输入**：触发条件用的跌停家数 / 涨停指数 / 连板高度 / IV分位正是 `breadth` 与 `volatility` 两块。因此 regime 被这两把卡着，不是被裁决卡着。

**验证命令与结果**：本次为纯文档改动，未跑测试；提交由 `.githooks/pre-commit` 两道守卫把关。

**失效旧结论**：① #10 的「待决口径」两问作废（已裁）。② #14「排除 or 降级」二选一作废（选降级）。③ #16「压仓位 or 提盈亏比」二选一作废（选压仓位）。④ #08 breadth「全市场 or 主板」二选一作废（选全市场）。⑤ 上一版把 #08 market_regime 列为「碰真钱边界需裁决」的说法作废——它没有待裁项，只有前置输入。

**下一步注意**：下一刀仍是**序 12 #08 northbound 接线**（★★☆☆☆，两头现成、无待裁项）；序 20 的 IV feed 依赖验证刀可与它并行，因为两者不碰同一处代码。

## 2026-08-04 追加：批 1 执行方案起草（序 20 IV-feed 依赖验证 + 序 12 #08 northbound 接线）

用户令「起草批 1」。两把同批的理由：验证刀纯查证、不改任何行为、与谁都不冲突；northbound 是离线接线。同批可省一次全量、一次契约重封、一次收口。**#14 不并入本批**——它直接改「谁能进 Tier1」，混批后下周选股若变动将无法归因到具体刀。**#16 更不并入**——它要新取全市场两融历史序列（真取数），与离线接线不是一个性质。

---

### 序 20 · IV feed 依赖关系验证刀（★☆☆☆☆，纯查证）

**目标**：用证据回答一个是非题——`runners/a_short_iv_feed_build.py` 是否依赖 `A-EGS/egs_main.py` 的任何产出。据此在三条路里**选定** volatility 的实现方案：(A) 调换次序让 IV feed 先跑 / (B) EGS 跑两趟 / (C) 把 IV 相关判定挪到 pipeline。

**起草时的实读先验（验证方须复核，不得直接采信）**

1. `a_short_iv_feed_build.main` 的 CLI 只有 `--as-of` / `--out` / `--failure-receipt-out` / `--confirm-fetch-authorized`，**没有任何指向 EGS 产物的入参**。
2. 其核心构建函数为 `build_daily_iv(opt_basic, opt_daily, underlier, ...)`，输入是期权链与标的行情，不是候选集。
3. 故**强先验是「不依赖」**。本刀的价值在于把先验变成证据，并把反向可能性排除干净——**先验不是结论，不得以「看起来不依赖」结案**。

**实现范围（纯查证，不改任何行为）**

1. **静态·依赖面**：在 `runners/a_short_iv_feed_build.py` 内全仓 grep `result/a_short`、`analysis_input`、`candidates`、`snapshot`、`data_health`、`egs`，逐条判定是「真读 EGS 产物」还是「同名巧合」。期望 0 条真依赖；**每条都要给出是/否判定，不允许整体性措辞**。
2. **静态·输入面**：列出该模块的全部外部输入（CLI 参数、环境变量、读盘路径、provider API 家族），逐项确认在 EGS 之前即可获得。
3. **动态·无 EGS 跑**：在一棵干净的临时输出根下，**不先跑 EGS**，直接以 canonical as_of 跑一次 `a_short_iv_feed_build`，断言它能产出 feed 且不报缺 EGS 产物。若该路径需要真取数，按现有 `--confirm-fetch-authorized` 门走并先取得用户授权；无授权则用既有离线/fixture 路径跑，并在结论里标明用的是哪条路径。
4. **反向**：若第 3 步失败，逐条记录它究竟缺什么，并明确判定「缺的是 EGS 产物」还是「缺的是别的前置」。失败不等于依赖成立。
5. **产出结论**：三选一必须**明确选定**，附理由与下一刀范围；若证据不足以选定，明写「不足以选定」并列出还缺什么。结论追加进本 handoff。

**验收**

| 场景 | 必须满足 |
|---|---|
| 静态依赖清单 | 每条命中逐条给「是/否 EGS 依赖」判定；不接受「看起来不依赖」这类措辞 |
| 静态输入清单 | 每项输入标明「EGS 之前可得 / 之后才可得」 |
| 动态无 EGS 跑 | 有真实终态（成功产 feed，或明确失败原因 + 缺什么），不接受推测 |
| 结论 | 三选一有选定 + 理由 + 下一刀范围；不足以选定时明写不足与缺口 |

**测试落点**：本刀不新增行为测试（无行为变更）。第 3 步若需一次性脚本，脚本走 scratchpad **不进 tracked**，只把结论写进 handoff。

**边界**：不改 `runners/weekly_screening.ps1` 的编排、不改 `A-EGS/egs_main.py`、不改 IV feed 的任何行为、不接 volatility 叶、不改任何 schema 或 effect contract。**本刀只产结论，不产功能。**

---

### 序 12 · #08 northbound 接线（复杂度上修 ★★☆☆☆ → ★★★☆☆）

**起草时的更正（重要，推翻上一版排期依据）**

上一版把本刀记为「两头现成、零待裁项」，实读后**两点均不成立**：

1. **v14.2 `:224` 的消费点不可直接用**。那是 M2.6 10日回溯的「**三选二**」升级审查触发，需要「大宗折价连续扩大 / 融资余额下降加快 / 北向连续5日净流出」三者中的两个；另两个输入当前不存在，故 northbound 单独到位也点不亮该门。且规格写的是「**连续**5日净流出」（逐日形态），而生产者现算的是 `north_money` 五日**求和**（`A-EGS/egs_main.py:5928`）——两者不是一回事，不得混用。
2. **真正现成的消费点在 `market_environment()` 自己（`A-EGS/egs_main.py:5937-5949`），但今天只输出文本**：
   - `north_flow_yuan < -50e8` → 打印「[!!] 北向资金大幅流出，防御信号。」
   - `csi300_ret < -10` 且 `north_flow_yuan < 0` → 打印「[静默] 市场进入防御/收缩期：建议静默，**禁止开新仓**。」

   后者是一条**真的仓位规则**，条件与阈值都已写死在代码里，但它对最终表零影响。本刀的实质即：把这句打印变成真门。

**已定口径（2026-08-04 用户确认，实现不得再自行解释）**

做哪一条门 —— **只做「静默」那条，且保持其现有双条件与阈值原样不变**（CSI300 窗口跌幅 `< -10` 且北向五日净流出 `< 0` → 本周禁止新建仓）；`-50亿` 那条保持 advisory（其信息已由 `net_flow_5d` 真值字段表达，不需额外后果）。理由：阈值不是新发明的、是代码里已有的，在无回测依据时自造新数字风险更高；这也正是 #05 立意里「让『北向大幅流出→防御』这条死掉的风控复活」。**本刀开口已关（2026-08-04 用户「确认」），可开工。**

**风险披露（必须让用户看到）**：「禁止新建仓」是一把大锤——条件一旦满足，当周所有新仓位都不建。该规则从未真正生效过，**历史触发频率未知**。因此实现范围第 5 条为硬要求：同刀产出回看统计供用户决定是否保留该门。

**实现范围**

1. **生产者**：`market_environment()` 已算出 `north_flow_yuan`（`:5925-5934`）；把它连同派生的 `status` 一并回传，写进 `export_analysis_input` 的 `market_context.northbound.{net_flow_5d, status}`。**单位必须是元**（schema 已注明 `Unit: CNY`），不得写万元——现有代码已用 `TUSHARE_MONEYFLOW_HSGT_NORTH_MONEY_UNIT_YUAN` 做过换算，沿用它。
2. **fail-closed 口径**：`status` 取 `inflow / outflow / flat / unknown` 四值（schema 已固定该 enum）。取不到数据时 `status="unknown"` 且 `net_flow_5d=null`，**不得填 0、不得当作 `flat`**；下游也不得把 `unknown` 当 `flat` 处理。
3. **窗口口径**：五日窗口沿用现有 `trade_dates[4]..trade_dates[0]`，**不得改窗口、不得改成「连续净流出」判据**（那是 v14.2 M2.6 的另一件事，不在本刀）。
4. **消费者**：按上面确认的口径，把「静默」条件做成真门。**生产者与消费者必须同刀闭合**（#06 的教训 + 2026-08-04 约束③）；只填真值不接消费者会立刻造出 `true_dangling` 叶。
5. **回看统计（硬要求）**：产一份 counts-only 的「过去 N 周若该门为真会触发几次」统计，走 comparison / research 路径，**不进生产决策、不改任何本周输出**。用户看过后再决定该门去留。
6. **契约**：`market_context.northbound.net_flow_5d` / `.status` 由恒空叶变真值且开始影响决策 → effect contract 叶账本 + `leaf_effect_overrides` + `decision_predicate_sha256` 重封，照 #06 的做法（两个 fingerprint-governed 文件各一次）。

**验收（正控 + 四条反控 + 一条植入）**

| # | 类型 | 断言 |
|---|---|---|
| ① | 正控 | 注入 CSI300 窗口跌 `-12` + 北向五日净流出为负 → 本周所有建仓降为观察；且 `northbound.status="outflow"`、`net_flow_5d` 为负的**元**值 |
| ② | 反控·单条件 | 只跌不流出 / 只流出不跌 → 现金与仓位结果**逐字段不变** |
| ③ | 反控·数据缺失 | `moneyflow_hsgt` 取不到 → `status="unknown"`、`net_flow_5d=null`、**不封门**（unknown 既不当 outflow 也不当 flat）|
| ④ | 反控·单位 | 用一个已知 `north_money`（万元）值验算，断言写进契约的是 ×10000 后的元值 |
| ⑤ | 植入控制 | 中和消费门（把封门条件改成恒假）→ ① 的正控必须转红 |

**测试落点**：新增用例必须落在 `test_a_short*.py` 选择器内，否则 lane 全量绿不代表本刀绿（同 #03+#04 的坑）。

**边界（不得扩大）**：不改选股 / EGS 打分 / TopN / M6.7 操作判定 / 已有持仓处置 / provider 参数 / PIT 窗口；**不动逐票 `capital_flow.northbound`**（那是 hk_hold 数据，2024-08 后已停发，按既有决策 5「拿不到不做」）；不改五日窗口口径；不发明新阈值；不并入 #14 / #16。

---

**本批共同约定**：两把刀在**同一棵 worktree**内连续起草、各自独立 slice + 自审，**loop 中不 commit**；effect contract 只在两把都落地后**统一重封一次**；最后一次全量、一次收口、一次提交。执行前 worktree 已由 reviewer reset 到 master `fa71f184`（本日六条裁决已在树内）。

### 批 1 交接：给 executor 的命令（2026-08-04 reviewer 写入）

**命令**：执行批 1 —— **序 20（IV feed 依赖关系验证）** 与 **序 12（#08 northbound 接线）**。范围、验收、边界一律以本 handoff 同日「批 1 执行方案起草」节的两份方案为准，不得自行扩大或重新解释口径。

**执行树**：`D:\cnhea\Codex\worktrees\29e0\Stock`，reviewer 已 reset 到 master（本日六条裁决 + 两份方案 + 本命令均在树内）。**命令与口径只认这棵树里的文档**。

**register 条目（executor 建，用这两个 ID 以便跨轮对照）**：
- 序 20 → `R-ASHORT-KNIFE20-IV-FEED-DEPENDENCY-PROBE`
- 序 12 → `R-ASHORT-KNIFE12-NORTHBOUND-MARKET-WIRING`

**顺序与批内约定**：序 20 先做（纯查证，**三选一结论必须写回本 handoff**），序 12 后做。两把在同一棵树内连续起草、各自独立 slice + 自审，**loop 中不 commit**；effect contract 只在序 12 落地后**统一重封一次**；最后一次全量、一次收口。

**开工前必读**：`AGENTS.md`、`docs/CURRENT.md`、`docs/system_risk_register.md` 顶部未关闭条目、`docs/SESSION_LOG.md` 顶 1-3 条、`docs/pre_codex_self_review_checklist.md`（起草/修复必走 A-F，含 A.6 权威链与 C2 植入对照判据；SESSION_LOG 必带 Proof-of-use 行）。

**不得做**：
- **不读桌面文档** —— `C:\Users\cnhea\Desktop\a_cc_testrun1.md` 不是工程输入，只在 merge 后由 reviewer 回写状态位。
- **不 commit / push / merge** —— 提交与合入由 reviewer 在独立审查 PASS 后负责。
- **不并入 #14 / #16** —— 前者会改「谁能进 Tier1」，混批后选股变动无法归因；后者要真取数，性质不同。
- **不碰 #08 liquidity** —— 用途仍未决，用户本轮未答；无消费点接线必造 `true_dangling` 叶。
- 不改选股 / EGS 打分 / TopN / M6.7 操作判定 / 已有持仓处置 / provider 参数 / PIT 窗口；不动逐票 `capital_flow.northbound`（hk_hold 已停发）。

**完成条件（交 reviewer 前逐条自检）**：
1. 序 20 的三选一结论已写回本 handoff，且每条静态命中都有「是/否 EGS 依赖」逐条判定。
2. 序 12 的五条验收全过：正控（封门 + 元值 + status=outflow）、三条反控（单条件 / 数据缺失 unknown 不封门 / 单位 ×10000）、一条植入控制（中和消费门 → 正控转红）。
3. 回看统计已产出（counts-only、不进生产决策）。
4. effect contract 叶账本 + `leaf_effect_overrides` + 指纹已统一重封一次。
5. 两条 register 条目已建；`docs/SESSION_LOG.md` 按极简模板写一条并带 Proof-of-use 行（`matrix=` / `register=` / `handoff=` / `focused=` / `full-lane=` / `door=` 六字段齐全）。
6. 新增用例全部落在 `test_a_short*.py` 选择器内。

## 2026-08-04 追加：批 1 执行结果（序 20 IV feed 依赖验证 + 序 12 #08 northbound 接线）

### 交接文档作用确认

- `docs/handoff/README.md` 是交接目录的路由、文档角色和同日追加格式说明；本轮未改变路由，因此不改该文件。
- 本文件是序 20 / 序 12 的范围、验收、边界和执行证据唯一同日交接载体；本节追加实际终态，供 reviewer 复核。
- `docs/handoff/` 其他文件仍按各自主题保存历史方案/交接，不是本批命令的替代真相源；本批未从其他工作树或桌面文件借用结论。

### 序 20：IV feed 依赖关系验证——已选 A，纯查证完成

**Verdict/Action**：结论为 **A：调换次序让 IV feed 先跑**。验证证明 `runners/a_short_iv_feed_build.py` 不读取 EGS 产物；因此不需要 EGS 跑两趟，也不需要把 IV 判定挪入 weekly pipeline。本序不改编排、不改 IV 行为、不接 volatility 叶。

**静态依赖清单（逐条判定）**：

| 搜索项 | 实际命中 | 是否 EGS 产出依赖 |
|---|---|---|
| `result/a_short` | 0 | 否 |
| `analysis_input` | 0 | 否 |
| `candidates` | 0 | 否 |
| `snapshot` | 0 | 否 |
| `data_health` | 0 | 否 |
| `egs` | 1 条模块边界 docstring（“不动 production / egs_main / V14.2”），不是读盘、导入或数据访问 | 否 |

**静态输入清单**：

| 输入 | 位置/形状 | EGS 之前可得 |
|---|---|---|
| `--as-of` | CLI canonical decision date | 是 |
| `--out` | CLI feed 写盘目标 | 是；只决定本序输出，不读取 EGS |
| `--failure-receipt-out` | CLI sanitized failure receipt 目标 | 是；只决定本序输出 |
| `--confirm-fetch-authorized` | CLI provider-call gate | 是；本轮未开启真实取数 |
| `TUSHARE_TOKEN` | provider 初始化环境变量 | 是；本轮 fake provider 未使用真实 token |
| `trade_cal` / `option_basic` / `opt_daily` / underlier `fund_daily` 家族 | `a_short_iv_feed_probe.fetch_probe_inputs` 的 provider 输入 | 是；与候选集无关 |
| EGS `analysis_input` / `candidates.csv` / `snapshot.json` / `data_health` | 全部无读路径 | 不适用：本序没有该前置 |

**动态无 EGS 证据**：在 fake-provider、临时输出根、未先跑 EGS 的路径直接运行：

`& 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_iv_feed_build.BuildMainRegressionTests.test_enough_dates_writes_nonnull_latest_percentile` → `Ran 1 test in 0.907s ... OK`，临时目录成功写出 feed；同模块完整回归 → `Ran 64 tests in 4.533s ... OK`。该路径没有报缺 EGS 产物；使用 fake provider，不是 provider/live 证据。

**反向判定**：动态路径未失败，因此不存在“缺少 EGS 产物”的失败项；真实 provider、真实 EGS 周跑和生产编排仍未验证。下一刀如需改编排，只需保持 IV feed 的独立输入/写盘边界并让它先于 EGS 消费，不在本批扩展。

## 2026-08-04 Codex 批 1 Required + Optional 修复交接（未提交，待独立 reviewer）

### 交接文档作用与追加位置

- `docs/handoff/README.md`：交接目录路由、角色分工和同日追加格式；本轮只读取并遵循，未改其稳定内容。
- 本文件：序 12 northbound wiring 的同日执行/修复事实、调用链、验收和边界唯一 handoff 载体；本节追加在文件末尾，保留此前历史交接。
- `docs/system_risk_register.md`：三条 material Required 的完整根因、修复状态和风险边界单一来源；本轮新增同日修复登记，仍是 `OPEN-NOT_VERIFIED`。
- `docs/SESSION_LOG.md`：reverse-chrono 的极简 review-cycle 入口；本轮已在顶部追加一条，详细内容不在此重复。

### Verdict / Action

序 12 的三条 Required 与五条 Optional 已完成最小修复；未提交、未 push、未 merge，未启动 provider/live、runner、sub-agent 或任何真实历史取数。序 20 的既有 PASS 结论未改变。下一个动作是 Claude Code 对 parent wiring 与三条 Required 做独立复审。

### Required 修复

1. **P1 窗口覆盖**：`A-EGS/egs_main.py::_northbound_provider_facts()` 现在要求请求侧恰好 5 个唯一 `trade_date`，响应侧恰好 5 行、5 个唯一日期、日期集合完全落在且等于 `trade_dates[4]..trade_dates[0]`；重复、缺失、窗口外、非法日期、非有限 `north_money` 均 fail-closed 为 `unknown + null`，不再部分求和。`requested_session_count`、`observed_session_count`、`coverage_complete` 随 `analysis_input.market_context.northbound` 写盘。
2. **P2 回看空证据**：选择“不扩展历史 provider 授权”的方案 (b)。`NORTHBOUND_MARKET_GATE_PRODUCTION_EFFECT_ENABLED=False`，analysis-input schema const-pin 为 false；weekly 仍计算/记录 `predicate_triggered`，但 `production_effect_enabled=false` 时不改变建仓。`research/results/a_short/northbound_market_silence_lookback_summary.json` 保持 counts-only、`NOT_VERIFIED`、`comparison_only`，不进入生产决策。
3. **P3 held guard**：删除不可达的 `position_state == held` guard；`test_existing_holding_is_not_changed_by_new_entry_gate` 改为比较完整 held 报告/机器记录，直接验证已有持仓不受新建仓门影响。

### Optional 修复

- `validate_weekly_report()` 增加 `expected_northbound_control`，main 传入同一 analysis_input 派生控制，防止周报控制对象只靠自身重算而脱离 source。
- Markdown 增加两种市场级可见性：谓词触发但 production effect disabled 时显示“仅记录未生效”；实际封门但没有建仓候选时显示“没有可被该门降级的新建仓候选”。
- `csi300_window` 结构化发布 start/end/length/length_unit，并写入 analysis/weekly schema 与 effect contract；完整窗口按交易日，短输入 fallback 明确为自然日。
- `_finite_number()` 使用 `numbers.Real`，兼容 numpy 实数且保持 bool/NaN/Inf fail-closed；删除测试中的 unused `control` 赋值。
- 本次新增 8 个 analysis-input 结构化叶后，effect consumer probe 的固定叶节点基线从 380 更新为 388；这是契约实际扩展，不是放宽断言。

### 调用链、消费者、schema、source-binding 与写盘边界

`market_environment()` → `_northbound_provider_facts()` → `export_analysis_input()` → `analysis_input.market_context.northbound` / `breadth.csi300_window` → `_northbound_control_from_analysis()` → `_normalise_northbound_control()` → `validate_weekly_report(expected_northbound_control=...)` → `_apply_northbound_market_gate()` → weekly reports/operation impact/Markdown。生产 effect 由代码常量和 analysis schema 双重关闭；weekly schema 要求覆盖、谓词、effect、理由与 CSI 窗口字段。未完整对账的 provider 数据不能进入求和、source-binding 或生产门；未触发/未生效时仍保留结构化记录和 Markdown 提示。effect contract 已同步 decision/runtime/schema fingerprints，最终 `static_contract_error=None`。

### 负向控制与自审

- 5 日完整正控按真实符号判定；1 行、3 行、窗口外、重复、非法/非有限值全部 `unknown/null` 且不封门。
- 只满足 CSI、只满足北向、缺失北向、缺失 CSI、held 行、production effect disabled、无建仓候选、消费者植入回归均有覆盖。
- 已检查调用链、直接消费者、schema required/const、source_paths/effect contract、写盘和 renderer 边界；未改选股、TopN、Phase5、逐票 `capital_flow.northbound` 或 provider 参数。

### Verify / 原始终态

- 固定解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，`Python 3.13.8`。
- `& 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_egs_market_environment tests.test_a_short_northbound_market_wiring` → `Ran 18 tests in 3.133s` / `OK`。
- `& 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_weekly_pipeline` → `Ran 521 tests in 55.232s` / `OK`。
- `& 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' -m unittest tests.test_a_short_official_operation_evidence tests.test_a_short_effect_contract tests.schema.test_analysis_input_contract` → `Ran 88 tests in 43.815s` / `OK`。
- full lane 首次因 `test_all_analysis_input_leaves_have_explicit_nature` 的旧 `380` 断言失败：`Ran 194 tests in 4.970s` / `FAILED (failures=1)`；更新为 388 后最终同一 full-pack 命令：`Ran 2363 tests in 295.405s` / `OK (skipped=3)`，`[full-pack-ledger] RESULT status=PASS exit=0 tests=2363 elapsed=297.1s deadline=860s`。
- `static_contract_error=None`；`git diff --check` 无 whitespace error，仅有行尾转换提示。

### Pre-Codex self-review / NOT_VERIFIED

`matrix=Required P1/P2/P3 + Optional 1-5`; `register=updated`; `handoff=updated`; `focused=18+521+88 OK`; `full-lane=2363 OK (skipped=3), stale 380 baseline repaired`; `door=route-doc + doc-governance: 66 OK / exit=0`; `review=NOT_VERIFIED`; `commit=NOT_PERFORMED`; `provider/live/account/sub-agent=NOT_USED`。

仍未验证：Claude Code 独立复审、真实 provider/live、真实历史结构化周报与触发频率、review PASS、commit/push/merge。自动化测试绿不等于这些结论；下步只执行独立 review，不自行提交。

### Next

Claude Code：独立审查 `R-ASHORT-KNIFE12-NORTHBOUND-MARKET-WIRING` 及 `R-ASHORT-KNIFE12-NORTHBOUND-WINDOW-COVERAGE-UNVALIDATED`、`R-ASHORT-KNIFE12-LOOKBACK-DELIVERABLE-EMPTY-WHILE-GATE-LIVE`、`R-ASHORT-KNIFE12-HELD-GUARD-TEST-NOT-LOAD-BEARING`；确认后按项目规则决定提交。

### 序 12：#08 northbound 接线——实现完成，待独立审查

**根因**：EGS 已把 `north_money` 五日求和转换为 CNY，并在 `market_environment()` 打印「静默、禁止开新仓」文字，但此前只写渲染文本；weekly 没有结构化 producer/consumer，机器无法把该双条件落实到新建仓结果。

**实现与调用链**：

1. `engine/a_short_northbound.py` 集中保存 `-10.0` CSI300 阈值、`inflow/outflow/flat/unknown` 分类和 `should_block_new_entries()`；未知、非有限值不进入门。
2. `A-EGS/egs_main.py::market_environment()` 保留原五日窗口 `trade_dates[4]..trade_dates[0]` 和原 `north_money × 10000` 元单位，返回结构化 `{northbound: {net_flow_5d, status}, csi300_pct_change_window}`；`run_egs()` 将 facts 传给 `export_analysis_input()`，写入 `analysis_input.market_context`。`-50e8` 仍是 advisory 文本。
3. `runners/a_short_weekly_pipeline.py::_northbound_control_from_analysis()` 只读结构化 `analysis_input`，校验 `decision_as_of`、`source_paths`、flow/status 一致性；`_normalise_northbound_control()` 对缺失数据归一为 `null + unknown`。
4. `build_weekly_report()` 在账户覆盖校验后、portfolio context/cash allocation 前调用 `_apply_northbound_market_gate()`；只对 `操作=建仓` 且非已有 `stateful_risk.position_state=held` 的行复用 canonical observe demotion，已有持仓不动；命中时追加 `machine.operation_impact` 与周报级 `northbound_control`。
5. `schemas/a_short_weekly_report.schema.json` 现在把 `northbound_control` 作为当前周报必需 envelope 字段；旧已审 `1.0.0` legacy migration 在 `runners/a_short_official_operation_evidence.py` 仅对旧契约豁免该新字段，当前 schema/validator 仍 fail-closed。

**结构化边界**：`market_context.northbound.net_flow_5d` 单位为 CNY；`unknown` 必须保持 `net_flow_5d=null`，不得伪造 `0/flat`。消费者的唯一生产门是“CSI300 `< -10` 且北向五日 flow `< 0`”，不使用 v14.2 的“连续五日净流出三选二”门，不触碰逐票 `capital_flow.northbound`。

**回看统计（counts-only）**：已产出 `research/results/a_short/northbound_market_silence_lookback_summary.json`，schema 为 `schemas/a_short_northbound_market_silence_lookback_summary.schema.json`。扫描现有 4 份 tracked weekly artifact（`20260612/20260706/20260720/20260727`）得到 `structured_fact_week_count=0`、`eligible_week_count=0`、`trigger_count=null`、`status=NOT_VERIFIED`；因历史周报没有结构化北向/CSI300 facts，未从历史文案反推触发次数。该 artifact 明确 `comparison_only=true`、`production_effect_enabled=false`，不进入 weekly 决策。

**验收与负向控制**：

- 正控：`test_dual_condition_demotes_every_new_entry_and_lands_structured_impact` 证明双条件下所有新建仓降为观察、flow 为负元值、status=`outflow`、impact/source/evidence 落地。
- 单条件反控：`test_single_condition_does_not_block` 覆盖只跌、只流出、flat 三组，建仓不变。
- 缺失反控：`test_missing_data_is_unknown_or_unavailable_and_does_not_block` 覆盖 `null+unknown` 与 CSI 缺失，均不封门。
- 单位/producer 反控：`tests/test_a_short_egs_market_environment.py` 的 7 条回归覆盖 `万元 ×10000 → 元`、双防御文字边界、结构化 facts 和 export 写盘。
- 持仓边界：`test_existing_holding_is_not_changed_by_new_entry_gate` 证明 held 行不被新建仓门改写。
- 植入控制：`test_disabling_gate_makes_positive_control_red` patch 掉 consumer 后，双条件正控重新保持“建仓”，证明门本身而非 fixture 使正控通过。
- schema/summary 控制：`test_lookback_summary_is_counts_only_and_explicitly_not_verified` 校验回看统计不含逐票/raw 结果且不具生产效力。

**effect contract**：已在两刀落地后统一重封一次；新增 `engine/a_short_northbound.py` decision/runtime constant fingerprints，注册 `northbound_market_silence_gate`，为 `market_context.breadth.csi300_pct_change_window`、`market_context.northbound.net_flow_5d`、`.status` 增加 `m67_main_decision` 叶覆盖，并更新 weekly output schema hash。固定 Python 计算 `static_contract_error=None`。

### 批 1 验证终态与边界

- 固定主 Python：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`；所有测试、检查、ledger 均显式使用该解释器；未使用 PATH/python/python3/bundled Python。
- focused：北向接线 `Ran 7 tests ... OK`；EGS facts/export `Ran 7 tests ... OK`；IV feed `Ran 64 tests ... OK`；effect contract `Ran 48 tests ... OK`；schema required 后核心 combined `Ran 583 tests ... OK`；直接消费者兼容修复后 combined `Ran 598 tests ... OK`。
- final full lane：`& 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' '.tools\full_pack_ledger.py' run a_short 'batch1 final closure after northbound schema required + legacy migration compatibility repair' 'fixed-Python focused: northbound 7 OK; EGS facts/export 7 OK; IV build 64 OK; effect contract 48 OK; weekly 521 OK; post-schema combined 583 OK; direct-consumer combined 598 OK; static_contract_error=None; no-provider fixture' 860 '--' discover -s tests -p 'test_a_short*.py'` → `[full-pack-ledger] RESULT status=PASS exit=0 tests=2359 elapsed=344.9s deadline=860s`，原始 unittest `Ran 2359 tests in 343.263s`、`OK (skipped=3)`。
- 固定 Python `py_compile` exit `0`；序 20 static scan 只有 1 条边界 docstring `egs` 命中，逐项 EGS 依赖判定均为“否”；effect contract static error 为 `None`。
- NOT_VERIFIED：Claude Code 独立审查、真实 provider/live/真实周跑和触发频率（历史结构化 facts 为 0 周）尚未验证；full/focused 绿不等于 review/live/ship-gate PASS。
- 审查/提交边界：当前工作树仍未 commit/push/merge，未启动 sub-agent；下一步由 reviewer 独立审查两条 register，PASS 后按项目规则提交，executor 不提交。

## 2026-08-04 追加：序 18（#14 短史候选降级）与序 21（全市场两融端点形状探针）执行方案起草

用户令「起草 #14」+「起草两融探针」。两把**不同批**：#14 纯离线改准入判据，探针是取数刀，性质与授权边界都不同。序 21 的授权范围由 reviewer 自行拍板（见该节），不再回问用户。

---

### 序 18 · #14 短史候选降级（★★☆☆☆，1 刀）

**已定口径（2026-08-04 用户裁决，实现不得再自行解释）**

走**降级**不走排除：可用收盘价不足门槛的候选**仍进打分池参与排名**（`full_count` 不得因此变化），但**禁止进入 Tier1 与最终建议**。理由：61 根这条线的含义是「技术指标算不稳」而非「这票不好」，直接排除会系统性错过次新股。

**起草时的实读事实（实现方须复核，不得直接采信）**

1. 判据已存在但**只产计数、不产逐票事实**：`A-EGS/egs_main.py:4753 _short_history_candidate_count(df_stocks, stats_df)` 取主板 code ∩ `stats_df.price_observation_count`，用 `observations.between(1, DAILY_STATS_REQUIRED_CLOSES - 1, inclusive="both").sum()` 得一个整数。阈值常量在 `:3131`：`DAILY_STATS_REQUIRED_CLOSES = DAILY_STATS_MAX_LOOKBACK_SESSIONS + 1`。
2. **调节表里没有任何「历史不足」处置**：实读 `result/a_short/20260803/rank_universe_reconciliation.csv`，1437 只 L0 的 reason 只有 `l1_industry_leader_elim` 351、`l2_crash_veto` 251、`l2_margin_growth_veto` 8、`l2_espq_valuation_veto` 8。即这 33 只（占打分池 `full_count=819` 的 4.0%）照常参与排名。
3. 本周 15 只入选票 `price_observation_count` 全为 64-65 根——**是没撞上，不是被拦住**。
4. Tier1 产出点为 `A-EGS/egs_main.py:6377` 的 `tier1_final, cninfo_checked, cninfo_health = stage3_ai_clearing(...)`；观察池选择器为 `:121` 导入的 `select_profile_watch_pool`。

**实现范围**

1. **计数升为逐票事实**：在 `stats_df` 已有的 `price_observation_count` 基础上派生 per-candidate 短史标记。**必须复用 `DAILY_STATS_REQUIRED_CLOSES` 这一个常量**，不得另立阈值；判据须与 `_short_history_candidate_count` 逐字同口径，否则计数与标记会各说各话。
2. **降级点**：禁止短史票进入 Tier1 与最终建议，但**不得**把它们移出打分池。接缝候选为 `stage3_ai_clearing`（`:6377`）与 `select_profile_watch_pool`；**实现方必须在 handoff 写明最终绑到哪一处及为什么**，不得两处都改。
3. **调节表出理由**：`rank_universe_reconciliation.csv` 必须出现可识别的短史处置理由，**不得复用** `l2_crash_veto` 等既有理由，也不得让这些票在表里显示为普通 `ranked`。
4. **0 观测的处置必须显式定义**：现判据是 `between(1, N-1)`，即 `price_observation_count == 0` 的票**不在计数内**。本刀须明确 0 根票走哪条路（大概率应与短史同等或更严），并写进 handoff；不得默认放行。
5. **计数一致性断言**：`data_health.short_history_candidate_count` 与逐票标记数必须相等，加一条断言防止两者漂移。
6. **契约**：若新增 `analysis_input` 叶，必须**同刀接上消费者**并重封指纹（`leaf_effect_overrides` + `decision_predicate_sha256`），照 #06 / 序 12 的做法——只填真值不接消费者会立刻造出 `true_dangling` 叶。

**验收（正控 + 三反控 + 一植入）**

| # | 类型 | 断言 |
|---|---|---|
| ① | 正控 | 造一只 `price_observation_count=40` 的票 → **拿不到 Tier1/最终席位**，但仍出现在打分池（`full_count` 计入）且在调节表里带短史理由 |
| ② | 反控·满历史 | `price_observation_count=65` 的票 → 名次、席位、现金结果**逐字段不变** |
| ③ | 反控·边界 | 恰好 `= DAILY_STATS_REQUIRED_CLOSES` 根 → **正常通过**（不得把边界值误判成短史） |
| ④ | 反控·退化输入 | `price_observation_count` 为 0 / 缺列 / 非数值 → 按第 4 条既定口径处置，且**不得崩** |
| ⑤ | 植入控制 | 摘掉降级腿 → ① 的正控必须转红 |

**测试落点**：新增用例必须落在 `test_a_short*.py` 选择器内。

**边界（不得扩大）**：不排除候选、不改 EGS 打分/权重/TopN 排序、不改 `DAILY_STATS_REQUIRED_CLOSES` 的值、不改主板范围判据（`is_a_share_main_board`）、不动 M6.7 操作判定与已有持仓处置、不碰 provider 参数与 PIT 窗口、不并入 #16 或 #02。

---

### 序 21 · 全市场两融端点形状探针（★☆☆☆☆，1 刀，取数）

**目标**：查清「全市场两融余额」的端点、权限、字段名、单位与历史深度，产一张**真实形状表**。序 19（#16 融资过热接线）与北向回看统计两把都要靠它写代码。**本刀只产形状与结论，不写任何消费代码。**

**为什么必须先探**：`#07(b)` 的教训——实现方假设 cninfo `orgId` 是 `gss[hz]` 格式直接写解析，真实数据里纯数字占 56%，规范化后丢弃 77.5% 的行，赔进一个完整 FAIL 轮。全市场两融是**全新端点**，端点名、权限、字段、历史深度四样全未知，正是同一形状的坑。

**已实读的边界事实**

- `A-EGS/egs_main.py:228` 的 `EGS_API_FAMILIES` 已含 `margin_detail`（**逐票**两融），即该家族已在授权范围内；**市场层总量是另一个端点，权限未知**。
- 逐票两融的既有消费者是 v14.2 `:288`（融资余额>流通市值 12%→盈亏比 2.0:1）与 `:324`（融资余额占流通市值比因子>8%），与本条要的**全市场历史分位**不是一回事。

**授权范围（reviewer 自行拍板，实现方不得扩大）**

- **端点白名单**：`pro.margin`（交易所层两融汇总）为主目标；若其不可用，允许再探一次 `pro.margin_detail` 的**聚合可行性**（只取一个日期看能否按市场求和），不得逐日全量拉取。
- **调用次数上限 12 次**，超出即中止并如实记录。
- **日期点 ≤5**：3 个近期交易日（验字段与单位）+ 2 个远期日期（验历史深度，建议取约 1 年前与约 3 年前各一个）。
- **不得**做全历史序列拉取、不得写分位计算、不得接任何消费者、不得改 EGS/pipeline/schema。

**实现范围（模板复用 `runners/a_short_rule6_tushare_d_tier_probe.py`）**

1. 新建 `runners/a_short_margin_market_shape_probe.py`，沿用该模板的骨架：`RAW_ROOT = provider_samples/a_short_margin_market_shape_probe_<PROBE_DATE>/`（**gitignored**）、`SUMMARY_PATH = docs/a_short_margin_market_shape_probe_summary_<PROBE_DATE>.json`（tracked）、`_shape()` / `_error_category()` / `run_probe(pro_client, raw_root)` / `main(argv)`。
2. **tracked summary 只许含**：端点名、是否需要 `exchange` 参数、HTTP/API 状态、返回列名清单、行数、每列的类型与是否全空、单位线索（字段名或文档措辞）、历史深度判定（远期日期是否有数据）、限频观察。**不得含** token、请求 URL、任何 raw 行值。
3. **失败分类必须可分辨四类**：无权限 / 端点不存在 / 限频 / 空数据。混成一个「失败」等于没探。
4. **单位必须探明并写进结论**：两融余额常见为元或万元；这一条若留空，序 19 会重蹈北向「万元当元」的覆辙。
5. **产出结论写回本 handoff**：字段名→用途映射、单位、可用历史深度（决定分位窗口能开多长）、限频、以及「序 19 与北向回看能否共用同一取数脚手架」的判定。

**验收**

| 场景 | 必须满足 |
|---|---|
| 密钥卫生 | tracked summary 过 secret scan：无 token / 无请求 URL / 无 raw 行；raw 全部落在 gitignored 根 |
| 调用预算 | 实际调用次数 ≤12 并如实记录；超限中止 |
| 失败可分辨 | 四类失败各自有独立 `error_category`，不得合并 |
| 结论完整 | 字段名、单位、历史深度、限频四项齐全；任一探不到须明写「未探明」及原因，不得留空或猜 |

**边界**：不写分位计算、不接消费者、不改 `EGS_API_FAMILIES` 之外的行为、不改任何生产 runner/schema、不做全历史拉取。探针结论出来之前，**序 19 与北向回看统计两把都不得开工**。

---

**批次安排**：序 18 与序 21 **不同批、可并行**——前者纯离线改准入，后者是取数刀，两者不碰同一处代码。序 21 回来后，序 19（#16）与北向回看统计**才**可以合批写代码（共用同一套「历史序列→统计」脚手架）。

## 2026-08-04 追加：序 21 探针结论 + 序 18 落地（reviewer 自执行）

**序 21 结论（解锁序 19 与北向回看）**：`pro.margin` 有权限；每交易日 3 行按 `exchange_id` = `SSE`/`SZSE`/`BSE`；字段 `rzye`/`rzmre`/`rzche`/`rqye`/`rqmcl`/`rzrqye`/`rqyl` + `trade_date`/`exchange_id`，数值列 `float64`；**单位 = 元**（三所 `rzrqye` 合计量级 1e12 ≈ 2.6 万亿元，与公开规模吻合；万元则大四个数量级）；**历史 ≥3 年**（1 年前与 3 年前窗口均非空），故分位窗口可开到 3 年。调用 5/12、零错误、无限频。`margin_detail` 聚合回退未触发。留给序 19 的唯一确认点：`BSE` 是否计入（占比 ≈0.3%；与 breadth「全市场」裁决一致的做法是全计）。

**序 18 落地**：`watch_pool_eligible_frame()` + `_short_history_mask()` 同时喂两处 `select_profile_watch_pool` 调用点；`df_full` 不删行；短史 code 漏进 `watch_df`/`top50` 直接 `RuntimeError`。判据 `< DAILY_STATS_REQUIRED_CLOSES`(=61)，含 0 与非数值，严于既有计数器的 `between(1,60)`。

**对我自己起草方案的两处更正**：① 「计数必须相等」不成立——计数器口径是全体主板 ∩ stats，拦截作用在打分帧，population 不同；② 「调节表出短史理由」放错了表——`rank_universe_reconciliation` 建模 L0→ranked，而短史票本就该被 ranked，拦截在排名之后，加理由等于谎称它们未进排名。正文见 register 同两条 R-ID。

**验证命令与结果**：`tests.test_a_short_short_history_downgrade` 8 OK；写盘守卫 10 OK；full lane `status=PASS tests=2371 elapsed=330.1s`；`static_contract_error=None`。

**失效旧结论**：起草节里「计数一致性断言(必须相等)」与「调节表须出现短史处置理由」两条作废，理由如上。

**下一步注意**：序 19 与北向回看现在可以合批写代码（共用「历史序列→统计」脚手架），但两者仍须各自独立审查；序 18 留了一条观测性 Optional（无 tracked 字段直说本周拦了几只），见 register。
