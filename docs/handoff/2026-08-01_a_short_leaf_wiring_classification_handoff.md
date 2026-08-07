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
| 4 悬空治理 | 11 | #09 守卫粒度 group→leaf | 1 | ★★★★★ | **口径已更正（2026-08-05）**：不是 28 条叶，是**当时 schema 全部 leaves 逐条处置**（数量动态取自 schema）+ **取消 `leaf_nature_by_group` 的放行权**；见文末更正节 |
| 4 | 12 | #08 northbound 接线 | 1 | ★★☆☆☆ | 数已取到（#05 已闭，量纲已对），现在只进控制台不进契约；**消费点现成**：v14.2 `:224`「北向连续 5 日净流出」是回溯触发升级审查的三选二之一 |
| 4 ✅已裁 | 13 | #08 liquidity 接线 | 1 | ★★☆☆☆ | **2026-08-05 用户裁决：删**。从 schema 删掉整个市场级 `liquidity` 对象，不保留占位/alias；理由见文末更正节。**可开工** |
| 4 | 14 | #08 breadth 接线 | 1 | ★★★☆☆ | **口径已定（2026-08-04）：全市场，不限主板**，字段名须写明；连板高度仍是新算法 |
| 4 ✅前置已解 | 15 | #08 volatility 接线 | 1 | ★★★★☆ | 卡执行次序：EGS 跑在 IV feed 之前，结构上拿不到。**（2026-08-05 刷新）序 20 已验完并合入：IV feed 不依赖 EGS 输出，三选一已选 A（调换次序让 IV feed 先跑）**，方案已定、可开工 |
| 4 | 16 | #08 market_regime 接线 | 1 | ★★★★★ | 三个仓位上限 + 最小盈亏比 + triggers，v14.2 核心状态机，碰真钱边界 |
| ✅ 4 | 17 | #06 节前减仓实现 | 1 | ★★★★★ | 已合入 master `a41c005c`；没等 regime，用举证式豁免解了环 |
| ✅ 5 新增 | 18 | #14 短史候选无区别对待 | 1 | ★★☆☆☆ | **已合入 master**。 **2026-08-04 由「记账」升为刀 + 口径已定：降级不排除**（可打分、禁进 Tier1/最终）。33/819 只 <61 根，调节表**无任何「历史不足」排除理由**，它们照常参与排名 |
| 5 | 19 | #16 全市场融资过热接线 | 1 | ★★★☆☆ | **2026-08-04 用户裁定「接」+ 消费点已定：压总仓位**（复用 #06 的现金系数杠杆，不走盈亏比门槛）。`A-EGS/egs_main.py:5971` 现为占位字符串 |
| ✅ 6 前置 | 20 | IV feed 依赖关系验证刀 | 1 | ★☆☆☆☆ | **已合入 master（已选 A）**。 **2026-08-04 用户令**：查清 IV feed 是否依赖 EGS 输出。序 15 volatility 与序 16 market_regime 的共同前置，不做这两把都开不了工 |
| ✅ 7 | 21 | 全市场两融端点形状探针 | 1 | ☆☆☆☆☆ | **已合入 master**。`pro.margin` 有权限、9 字段、每日 3 行、单位=元、历史 ≥3 年；为序 19 拆除形状未知 |
| ✅ 7 | 22a | 共享历史取数层 | 1 | ★★☆☆☆ | **已合入 master**。`engine/a_short_market_history.py` exact-date 对账；序 19 与 22b 的共同前置 |
| ✅ 7 | 22b | 北向回看统计 | 1 | ★★☆☆☆ | **已审查 PASS 并合入 `f93e2125`**。123/155 周可用、触发 5 次=4.1%；comparison-only |
| ✅ 8 | 23 | 北向静默门通电 | 1 | ★☆☆☆☆ | **已审查 PASS 并合入 `b217f09a`**。真钱门已生效；阈值与判据未动 |

**不许违反的约束**：① 第 4 批的 #09 与 #08 强耦合——#09 单独落地会让恒空叶暴露成叶级悬空、守卫当场红，必须同刀带处置。**（2026-08-05 更正：原文写「28 条」，实际范围是全部 schema leaves，见文末更正节。）**② ~~#06 反向依赖 #08-market_regime~~ **已作废（2026-08-04）**：#06 用举证式豁免解环并已落地，不再依赖 regime 先接。③ **新增（2026-08-04，来自 #06 的教训）**：序 12-16、18、19 每一把都必须**生产者与消费者同刀闭合**——只填真值不接消费者会立刻造出一条 `true_dangling` 叶，直接撞「每因子必联动到最终输出」的验收门，并被序 11 的 #09 账本盯上。

~~**剩余 11 刀**（#02、#10、#09、#08×5、#14、#16、IV-feed 依赖验证）~~ → **剩余 8 刀（2026-08-05 重算）**：序 7 (#02)、序 8 (#10)、序 11 (#09)、序 13/14/15/16 (#08×4)、序 19 (#16 两融过热)。已销的三刀：#14=序 18、IV-feed 验证=序 20、#08 northbound=序 12。其中 **#08 liquidity 仍未决、禁止开工**。原为 17 刀，2026-08-04 后 #14/#16 由「记账 / 待裁决」转为工程项各 +1 刀。第 1 批五把加起来约等于一把 ★★★，却消除两条「看起来正常实则已死」的假象、清掉一处脏状态、并止住每跑一次就毁一次的追踪基线。

**约束 ③（2026-08-03 Claude Code 补，实读 `schemas/a_short_m67_effect_contract.json`）**：序 11 的 #09 **不必发明新 nature 值**。`leaf_nature_by_group` 已有 `true_dangling` 这一档并已在用——29 个 group 的 nature 分布实测为 `main_decision` 6 / `partial_consumption` 9 / `true_dangling` 9 / `comparison_track` 2 / `duplicate_source` 2 / `display_audit` 1，其中 `candidate_capital_flow`、`candidate_quote`、`account_context` 等 9 个组正用 `true_dangling` 诚实表达「整组真悬空」。所以 #09 的实质是给 `market_context` 这种**组内混合**的情形补一个**叶级出口**，把那 28 条恒空叶按既有 `true_dangling` 逐条标注即可，不是设计能力缺失，也不需要新概念。

> **本段结论已作废（2026-08-05 更正）**：「标注那 28 条即可」**不成立**。当前系统已有逐叶 `leaf_effect_overrides` 与机械派生的 `producer_constant_null`，测试按 schema 全量 leaves 对账。真缺陷是**两层账并存**（group nature 与逐叶 effect），再加一层 `leaf_nature_by_path` 会形成第三张重复账。正确范围见文末更正节。

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
| 1 · #10 价格基准 | **统一成「上一个已收盘交易日」**，即 canonical 现有行为；显式 `-AsOf` 不再改变价格基准，研究口径另开显式开关（如 `-PriceBasis close`） | 主路径不得存在两种行为；`weekly_screening.ps1` 两条分支的分歧就此收敛（**2026-08-05 实测更正：现在 `:280` `$PriceAsOf = [string]$Resolved.last_settled` vs `:296` `$PriceAsOf = $AsOf`；原写 `:260`/`:276` 已漂移**） |
| 2 · #10 资金流容差 | **允许退一日**，取不到参考日即回退前一交易日，并在产物显式标明实际用日 | 节后资金流延迟发布常见，为此废掉整个大单流向因子不划算；但退一日必须可见、不得静默 |
| 3 · #14 短史候选 | **降级不排除**：可进池打分、保留可见性，禁止进 Tier1 与最终建议 | 61 根的含义是「指标算不稳」不是「票不好」；直接排除会系统性错过次新股 |
| 4 · #16 融资过热 | **压总仓位**，复用 #06 的现金系数杠杆；不走「提高最低盈亏比门槛」 | 全市场杠杆冲高是系统性回撤前兆，压仓位最直接；盈亏比那条会与 Rule 10 既有的环境分档互相抵消 |
| 5 · #08 breadth | **全市场口径**（不限主板），字段名须写明 | 这些数喂的是 regime 判定，判的是市场情绪不是可买范围；且 v14.2 `:154` 的阈值（连板≥5、跌停<50）按全市场量级定，只数主板会让阈值系统性偏松 |
| 6 · #08 volatility | **先花一刀验证 IV feed 是否依赖 EGS 输出**（新增序 20），验完再定「调换次序 / EGS 两趟 / 判定挪 pipeline」 | 三条路的成本与风险差别全取决于这个依赖事实；把「判定挪 pipeline」当默认解会让契约叶永远为空，等于用换地方算绕过悬空问题 |

**仍未决（不得开工）**：**#08 liquidity** —— `market_turnover_amount` / `median_amount_20d` 接出来影响什么没有结论。v14.2 的 regime 触发条件里**没有成交额这一项**，硬接等于在规格之外发明判据；未定用途前接线必造 `true_dangling` 叶。本轮用户未答此条。

**顺带定死的非决策事实**：**#08 market_regime 不需要用户裁决** —— v14.2 `:149-154` 已把四态触发条件与参数定死（防御 单只25%/总仓50%、震荡 40%/60%、进攻 50%/80%、收缩期禁止新建仓），`:110` 另定进攻期≥1.5:1 / 防御期≥2.0:1。它缺的是**输入**：触发条件用的跌停家数 / 涨停指数 / 连板高度 / IV分位正是 `breadth` 与 `volatility` 两块。因此 regime 被这两把卡着，不是被裁决卡着。

**验证命令与结果**：本次为纯文档改动，未跑测试；提交由 `.githooks/pre-commit` 两道守卫把关。

**失效旧结论**：① #10 的「待决口径」两问作废（已裁）。② #14「排除 or 降级」二选一作废（选降级）。③ #16「压仓位 or 提盈亏比」二选一作废（选压仓位）。④ #08 breadth「全市场 or 主板」二选一作废（选全市场）。⑤ 上一版把 #08 market_regime 列为「碰真钱边界需裁决」的说法作废——它没有待裁项，只有前置输入。**（2026-08-05 再更正：「没有待裁项」已不成立——序 14 起草时实读发现 v14.2 的「涨停指数」在仓库内没有权威数据源也没有精确定义，这是序 16 的实质待裁项，见文末更正节。）**

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

## 2026-08-04 追加：批 3 执行方案起草（共享历史取数层 + 序 19 融资过热 + 序 22 北向回看统计）

用户令「起草批 3」。这两把**该合批**，因为它们要的是同一件东西：**一条覆盖率经过校验的历史序列**。序 21 探针已把数据前提全部落实（`pro.margin` 有权限、9 字段、每日 3 行按 `SSE`/`SZSE`/`BSE`、**单位 = 元**、历史 ≥3 年），所以本批不再有形状未知。

**批内三件，按序做**：22a 共享取数层 → **22b 北向回看** → **序 19 融资过热**。22a 是另两件的共同前置。

> **顺序更正（2026-08-05，reviewer 令；起草时写的是 22a → 19 → 22b）**：22b 提前到 19 之前。理由：① 两者**互不依赖**——22b 产的是北向回看，不是序 19 分位所需的两融回看，序 19 的阈值证据由它自己那刀产出；② 22b **不碰仓位路径**，纯产证据；而序 19 压着一个起草时漏报的前置——`_allocate_cash` 只有单一 `cash_factor`（`runners/a_short_weekly_pipeline.py:1152-1159` 单点相乘），接第二道门必须先把它改造成可容纳多控制的形态，工作量与风险都远大于 22b；③ 22b 的产出直接解锁序 12 北向门那个仍为 `False` 的 `production_effect_enabled`，先做先有用。
> **22a 已完成**：`engine/a_short_market_history.py` + `tests/test_a_short_market_history.py` 已实现、自审（抓到并闭了一条 numpy 标量同类回归）、提交（`c9053abd` / `47b042ba`）。

> **命名警告（2026-08-04，已造成一次实际误执行）**：本文件的「批 N」是**队列批次**，与桌面清单 `a_cc_testrun1.md` 的「第 N 批」**不是同一套编号**——桌面「第 3 批」是 #06 节前减仓。执行方曾据「批 3」去做桌面第 3 批并只跑了一次验证。**下命令一律用序号**（如「执行序 22a」），或写全「队列批 3」，不要只说「批 3」。

---

### 22a · 共享历史取数层（★★☆☆☆）

**为什么先建它**：序 12 刚证明「把 provider 返回的行直接求和」是个真钱级缺陷——1 场当 5 场会双向翻转决策门。历史序列比周度窗口更容易缺日：三年里任何一天缺失、重复或越界，都会静默污染分位与回看计数。**同一个坑不许在历史层重挖一遍。**

**实现范围**

1. 新增 `engine/a_short_market_history.py`，提供一个纯函数 `reconcile_dated_series(rows, *, requested_dates, date_key, value_key)`：
   - 行数、去重后行数、日期集合三者必须与 `requested_dates` **完全相等**，任一不满足即返回 `coverage_complete=False` 且**不产出数值**；
   - 非有限值（NaN/Inf）出现即整段判不完整，不做插值、不做前值填充；
   - 返回 `{"series": ..., "requested_count": n, "observed_count": m, "coverage_complete": bool}`。
2. 判据必须与序 12 的 `_northbound_provider_facts` **同形**（行数 = 去重数 = 请求数 + 集合相等）。**不得**另立一套宽松口径。
3. 本层**纯离线纯函数**：不发请求、不读环境变量、不落盘。取数由各刀的 runner 负责，喂进来的是已经拿到的行。

**验收**：完整序列 → 出值；缺 1 日 / 多 1 行 / 重复行 / 越界日 / 含 NaN 五类 → 一律 `coverage_complete=False` 且无数值；空输入与空请求集不崩。植入：摘掉集合相等判据 → 「越界日」那条反控必须转红。

---

### 序 19 · #16 全市场融资过热接线（★★★☆☆）

**已定口径（2026-08-04 用户裁决 + reviewer 依探针结论细化，实现不得再自行解释）**

1. **消费点 = 压总仓位**（用户裁决），复用 #06 的现金系数杠杆，**不走**提高最低盈亏比那条。
2. **取哪个字段 = `rzye`（融资余额）**，不是 `rzrqye`。理由：「融资过热」度量的是**多头杠杆**，而 `rzrqye` 含融券侧；A 股融券占比极小（探针实测 SSE `rqye` 约 1.4e10 对 `rzye` 约 1.3e12，≈1%），混进来只会稀释语义而不改变量级。**同刀必须把 `A-EGS/egs_main.py` 那句占位文案「待接入两融余额历史分位」改成与实际口径一致的措辞**，否则留下 doc↔behavior 漂移。
3. **口径 = 三所全计**（`SSE` + `SZSE` + `BSE`）。与用户对 breadth 的「全市场」裁决一致；BSE 占比 ≈0.3%，计不计不改结论，但口径统一比省这 0.3% 值钱。
4. **分位窗口 = 滚动 3 年**（探针已证 3 年可达）。窗口内任一交易日缺失即走 22a 的 fail-closed，不得用残缺窗口算分位。
5. **多门相遇取最狠、不相乘**：本门与 #06 节前减仓、以及将来任何现金系数门同时命中时，**取最小的那个系数**，不做连乘。理由是连乘会把两个各自合理的门叠成一个没人论证过的深度折扣（0.8 × 0.8 = 0.64 这个数没有任何依据）。
   - **更正（2026-08-04 起草复审）**：起草时曾引 v14.2 `:164`「参数分歧处置：取更保守值」作依据，**该引用不成立**——原文限定于「若**环境切换**导致**仓位上限/盈亏比门槛**出现两种可能取值」，讲的是单一参数在 regime 过渡期的取值歧义，**不是两道独立风控门的叠加**。本条依据仅为上述自身论证，实现方不得据 v14.2 声称已获授权。
   - **结构前置（起草时漏报，会改变工作量）**：全仓**没有**现金系数栈。`runners/a_short_weekly_pipeline.py::_allocate_cash` 只有唯一一个 `cash_factor`，来源写死为 `pre_holiday_control.cash_factor`（`:1152-1159` 单点相乘）。接第二道门**必须先把它改造成可容纳多控制的形态**（合并控制对象或控制列表 + 取最小），否则最省事的写法就是再乘一次——正好是本条禁止的连乘。本刀因此实际不止 ★★★☆☆，须把该改造计入范围。
6. **首刀 `production_effect_enabled = False`**，与序 12 北向门同处置：先只记录分位与是否越线，不改本周决策；等 22b 的回看统计给出历史触发频率，用户看过再决定翻真。**这一条不是保守，是因为阈值本身还没有证据**（见下条）。
   > **更正（2026-08-05）**：「等 **22b** 的回看统计」**是错的**——22b 产的是**北向**回看，与两融分位无关（本节开头的顺序更正已指出这点，本条当时漏改）。序 19 的频率证据**由它自己那刀产出**：同刀发布 p80/p85/p90/p95 四档的触发周数、最长连续周与年度分布，供用户一次性裁定阈值与现金系数。按原文等 22b 会等到一份永远不会来的证据。
7. **阈值留给证据定，本刀不发明数字**：分位阈值（如 ≥90% 算过热）在 22b 的回看跑出频率之前**不写死进生产常量**；本刀只发布分位值本身与一个 governance 常量占位，翻真时同刀确定。

**实现范围**

1. 新增 gated runner 取 3 年 `pro.margin` 历史 → 经 22a 校验 → 算当前 `rzye` 三所合计在滚动 3 年内的分位。
2. 生产者写进 `analysis_input.market_context`：分位值、窗口起止、覆盖计数、`production_effect_enabled`。**新增叶必须同刀接消费者**（#06/序 12 的教训），否则立刻造 `true_dangling`。
3. 消费者按第 5 条接进现金系数栈（取最狠不相乘）；`production_effect_enabled=False` 时**只记录不改数**，且该开关必须像序 12 那样**经实测承重**，不是摆设。
4. 契约：叶账本 + `leaf_effect_overrides` + `decision_predicate_sha256` 重封。

**验收（正控 + 四反控 + 一植入）**

| # | 类型 | 断言 |
|---|---|---|
| ① | 正控 | 注入高分位 + `effect=True` → 可用现金按系数下降，且分位/窗口/覆盖计数落进产物 |
| ② | 反控·开关 | 同一组高分位事实 + `effect=False` → 现金与操作**逐字段不变**，但分位仍如实记录 |
| ③ | 反控·覆盖不全 | 3 年窗口缺任一交易日 → fail-closed，不出分位、不压仓 |
| ④ | 反控·取最狠 | 同时命中 #06 节前减仓 → 最终系数 = 两者最小值，**不等于**乘积 |
| ⑤ | 反控·单位 | 用已知 `rzye` 值验算，断言进契约的是元（探针已定单位，此条防回归） |
| ⑥ | 植入 | 中和消费门 → ① 转红 |

**边界**：不改选股/EGS 打分/TopN/M6.7 操作判定/已有持仓处置/PIT 窗口；不动逐票两融（v14.2 `:288`/`:324` 那两条是另一回事）；不发明分位阈值；不并入序 22b 的回看逻辑（共用 22a，但各自独立 slice）。

---

### 序 22b · 北向回看统计（★★☆☆☆）

**为什么需要**：序 12 的北向门当前 `production_effect_enabled = False`，因为「历史触发频率无证据」。本刀就是产那份证据，产完用户才能决定给那道门通电。

**已定口径**

1. **必须复用 live 门的同一谓词** `engine/a_short_northbound.py::should_block_new_entries`，**不得**另写一套回看判据——那正是上轮审查点名的 `I9` 风险（回看与实盘各算各的，结论无法互证）。
2. 输入两条历史序列：北向五日净流（`pro.moneyflow_hsgt` 的 `north_money`，元）与 CSI300 窗口涨跌（与 `get_csi300_return` **同窗口口径**）。两条都过 22a 校验，任一周覆盖不全即该周记 `unavailable`，**不猜、不插值**。
3. 产出 counts-only：`weeks_considered` / `eligible_week_count` / `trigger_count` / `unavailable_week_count` + 每周的判定。**不进生产决策**，走 comparison/research 路径。
4. 覆盖不到的周必须**显式计入 `unavailable`**，不得从分母里悄悄消失——否则触发率会被系统性高估。

**验收**：正控（构造必触发周 → `trigger_count` 递增）；反控（单条件周不计入）；反控（覆盖不全周计 `unavailable` 且不进分母的 eligible）；一致性（同一组输入，回看判定与直接调 `should_block_new_entries` 逐周相等——这是「同一谓词」的机器证明）；植入（把回看改成自写判据 → 一致性断言转红）。

**边界**：不改门的行为、不动 `production_effect_enabled`（翻真是另一次用户裁决）、不写进任何生产决策路径。

---

**授权范围（reviewer 自定，实现方不得扩大）**：本批历史取数**总预算 12 次调用**——序 19 的 `pro.margin` 三年窗口 ≤6 次，序 22b 的 `moneyflow_hsgt` + `index_daily` 合计 ≤6 次。raw 一律落 gitignored `provider_samples/`，tracked summary 只记计数/覆盖/分位，**不得含 raw 行、请求 URL、密钥**。超预算即中止并如实记录。

**批内约定**：**22a（已完成）→ 22b → 序 19** 顺序做（2026-08-05 更正，理由见本节开头的顺序更正块），同一棵树内连续起草、各自独立 slice + 自审，**loop 中不 commit**；effect contract 只在序 19 落地后统一重封一次（22b 不动契约叶，纯 comparison/research 产物）；最后一次全量、一次收口。

## 2026-08-05 — Codex executor/fixer 同日追加：执行序 22b（review pending）

### 本次问题、根因与改动

- 原 `research/results/a_short/northbound_market_silence_lookback_summary.json` 是空占位产物，只有测试读取，没有 producer；无法重算序 12 北向门的历史触发频率。
- 新增 `engine/a_short_northbound_lookback.py` 纯统计核心、`runners/a_short_northbound_market_silence_lookback.py` bounded provider runner、`schemas/a_short_northbound_market_silence_lookback_summary.schema.json` 2.0.0、tracked summary 与两组 lookback/runner 测试。
- runner 的 provider boundary 将有限 numeric string 规范化后才进入 22a `reconcile_dated_series`；覆盖缺失、重复、越界、错误 benchmark、非法/非有限值均 fail-closed 为 `unavailable`，不插值、不移动窗口、不把不可用周放进分母。
- 最终 full lane 发现新增 `_write_json` 未注册公共 writer registry；已作最小登记修复，未改变 payload、路径或生产链。

### 调用链、消费者、schema、source-binding 与写盘边界

`moneyflow_hsgt.north_money`（provider 万元值 × 10,000 = CNY）+ `index_daily(000300.SH)`（calendar trade dates）→ raw `provider_samples/a_short_northbound_lookback_20260804/` → numeric-string boundary → 22a exact-date reconciliation → `engine/a_short_northbound.py::should_block_new_entries` → counts-only `research/results/a_short/northbound_market_silence_lookback_summary.json`。

- 北向窗口固定 5 sessions；CSI300 窗口固定复用 `get_csi300_return` 的 20-session 口径。
- 直接消费者只有 comparison/research artifact；不导入 weekly/EGS，不写 `analysis_input`，不进入任何 production decision path；`production_effect_enabled` 保持 `false`。
- schema 固定 endpoint、`000300.SH`、单位、5/20 sessions、共享 live predicate、`comparison_only=true`、`production_effect_enabled=false`。
- raw 只写 gitignored `provider_samples/`；tracked summary 只写周数/覆盖数/判定，不写 raw rows、request URL、token/secret。

### 实际结果与原始终态

- as-of `20260804`，lookback start `20230804`；`weeks_considered=155`、`eligible_week_count=57`、`unavailable_week_count=98`、`trigger_count=0`，57 周为 `eligible_not_triggered`，summary `status=PARTIAL`，`NOT_VERIFIED` 明确写出 98 周覆盖不足。
- provider 实际调用 `2/6`：`moneyflow_hsgt`、`index_daily` 各一次且成功；随后 `replay_raw` 复用同一 raw，未新增调用。raw 观测形状为 flow 300 rows（最早 `20250429`）和 CSI300 726 rows（最早 `20230804`），未把行值写入 tracked 文档/产物。
- 固定主 Python：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `3.13.8`。
- focused 精确命令：

  `Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & '.tools\run_unittest_with_repo_pythonpath.cmd' 'tests.test_a_short_northbound_lookback' 'tests.test_a_short_northbound_lookback_runner' 'tests.test_a_short_northbound_market_wiring' 'tests.test_a_short_market_history' 'tests.test_a_short_egs_market_environment' 'tests.test_a_short_effect_consumer_probe' 'tests.test_a_short_effect_contract' 'tests.test_a_short_public_json_writer_nonfinite_guard'`

  原始终态：`Ran 118 tests in 79.241s` / `OK`；receipt `receipt:d836041f06598d5ef608b0de`。
- 静态/编译/JSON：`py_compile=0 json=0 static_residue_scan=0`；`git diff --check` exit 0。
- full 精确命令：

  `Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' '.tools\full_pack_ledger.py' run a_short 'R-ASHORT-SEQ22B-NORTHBOUND-LOOKBACK-PROVIDER-RAW-BOUNDARY' 'receipt:d836041f06598d5ef608b0de' 860 -- discover -s tests -p 'test_a_short*.py'`

  原始终态：`Ran 2398 tests in 459.278s` / `OK (skipped=3)`；`[full-pack-ledger] RESULT status=PASS exit=0 tests=2398`。
- 首次 full 的真实失败也保留：`Ran 1174 tests in 208.981s` / `FAILED (failures=1)`，根因是新增 `_write_json` 未登记；登记后按同一触发器修复重跑并通过。

### 负向控制、自审、审查与提交边界

- 已覆盖/复核：正控触发、单条件不触发、缺最新 flow 日不后移、错误 `ts_code`、非有限/非法 provider 行、替换回看谓词的一致性断言、raw root/production output guard、summary 无 raw/url/secret、生产门未启用。
- `NOT_VERIFIED`：独立 Claude Code review、用户翻转生产门、完整 live/weekly 消费、commit/push/merge；未起 sub-agent，未跑 provider/live 以外的 live 行为。
- 本次只改 22b 及其必要 writer registry；不处理序 19，不 commit。当前下一步：`Claude Code：审查`。

## 2026-08-05 追加：序 22b 两条 P1 修复（待 Claude Code 独立复审）

### 修复目标、判断与边界

本轮按 Claude Code 同日 FAIL 修复两条 P1：

1. `R-ASHORT-SEQ22B-CSI300-WINDOW-MISMATCH`：实盘 `get_csi300_return(trade_dates)` 的 `>=20` 只是最小长度守卫；当前生产传入的 `trade_dates` 为 65 个交易日，实际 return 跨完整 65-session span。回看不再使用独立 20-session 常量。
2. `R-ASHORT-SEQ22B-FETCH-TRUNCATED-AT-PROVIDER-ROW-CAP`：`moneyflow_hsgt` 的单次 300-row 上限不能当成完整三年证据；runner 改为先取得 CSI300 日历，再分段取 flow，并记录截断和覆盖分类。

> **历史纠正**：本文件前一节执行记录中的「CSI300 20-session 口径」及 schema「5/20 sessions」表述已由本节 supersede；20 只表示生产函数的最小长度守卫，当前 live span 与本回看契约均为 65 sessions。

本轮仍只处理序 22b comparison/research slice：不改 `A-EGS/egs_main.py` 生产运行代码、不改 weekly/EGS/TopN/M6.7/仓位、不打开 `production_effect_enabled`，不处理序 19。Claude review 的两个 P2 Optional 留作 deferred，不在本轮冒充已修。

### 调用链、消费者、schema/source-binding 与写盘边界

`index_daily(000300.SH)` 交易日历 → `moneyflow_hsgt` 按最多 250 sessions 的日期段读取（单次 provider cap = 300 rows）→ raw `provider_samples/a_short_northbound_lookback_20260804/`（含分段 payload 与 counts-only fetch manifest，均 gitignored）→ numeric-string boundary → 22a `reconcile_dated_series` exact-date reconciliation → `engine/a_short_northbound.py::should_block_new_entries` → counts-only `research/results/a_short/northbound_market_silence_lookback_summary.json`。

- `engine/a_short_csi300_window.py` 是回看窗口契约源：`CSI300_LIVE_WINDOW_SESSIONS=65`；`tests/phase6/test_egs_main_daily_stats_guard.py` 把它与生产 `A-EGS/egs_main.py::DAILY_ALL_QFQ_WINDOW_TRADING_DAYS=65` 断言绑定。生产 EGS 文件本轮保持不变，避免 comparison-only 修复无故改变 effect-contract fingerprint。
- 北向仍为 5-session `north_money × 10000 = CNY`；CSI300 回看使用 65-session live span；两者都经过 22a exact reconciliation，不补值、不滑窗。
- 每周 `unavailable_reason` 只允许 `warm_up`、`fetch_truncated`、`source_gap` 或 eligible 周的 `null`；summary 增加 `unavailable_breakdown`，runner 增加 `northbound_fetch`（row cap、分段上限、分段数、请求/观测数、截断数、状态）。schema 对 65-session、字段枚举和安全边界做 const/closed-world 约束。
- 直接消费者仍只有 comparison/research artifact；`comparison_only=true`、`production_effect_enabled=false`；tracked summary 不写 raw rows、request URL、token/secret。

### 负向控制与实际 provider 重算

- 65-session vs 20-session 分歧控制：构造 65-session 跌破 −10% 而最近 20-session 未跌破的序列，修复后触发，旧回看口径不会误绿。
- 分段控制：726 个 CSI300 交易日必须生成 3 个 flow segments；300-row fake response 必须写 `truncated=true` 并将受影响周归入 `fetch_truncated`；删最新 flow 日且无 row-cap 标记归入 `source_gap`；前 65-session 不足归入 `warm_up`。
- 固定主 Python 下已实际重算：`as_of=20260804`、`calls=4/6`（CSI300 1 + flow 3）、`segment_count=3`、`truncated_segment_count=0`、请求 726、观测 702；`weeks=155`、`eligible=123`、`unavailable=32`、`breakdown={warm_up:13, fetch_truncated:0, source_gap:19}`、`trigger_count=5`、`status=PARTIAL`。`PARTIAL` 保持诚实，不宣称三年 COMPLETE 或 production PASS。

### 验证命令与原始终态

- Python identity：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe` / `Python 3.13.8`。
- focused bounded command：

  `Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & '.tools\run_unittest_with_repo_pythonpath.cmd' 'tests.test_a_short_northbound_lookback' 'tests.test_a_short_northbound_lookback_runner' 'tests.test_a_short_northbound_market_wiring' 'tests.test_a_short_egs_market_environment' 'tests.phase6.test_egs_main_daily_stats_guard' 'tests.test_a_short_market_history' 'tests.test_a_short_effect_consumer_probe' 'tests.test_a_short_effect_contract' 'tests.test_a_short_public_json_writer_nonfinite_guard'`

  原始终态：`Ran 132 tests in 82.568s` / `OK`；receipt `receipt:ca0c033c553615ccfa934ecc`。
- provider command：

  `Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' 'runners/a_short_northbound_market_silence_lookback.py' '--as-of' '20260804' '--raw-root' 'provider_samples/a_short_northbound_lookback_20260804' '--out' 'research/results/a_short/northbound_market_silence_lookback_summary.json'`

  原始终态：`completed calls=4/6 weeks=155 eligible=123 triggers=5`；summary schema 校验通过。provider raw 未进入 tracked 文件。
- static command：固定 Python 对 6 个 changed Python `py_compile=0`；summary `jsonschema=0`；`git diff --check` exit 0。
- final full lane：

  `Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & 'C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe' '.tools\full_pack_ledger.py' run a_short 'R-ASHORT-SEQ22B-P1-WINDOW-MATCH-AND-PROVIDER-ROW-CAP-REPAIR' 'receipt:ca0c033c553615ccfa934ecc' 860 -- discover -s tests -p 'test_a_short*.py'`

  原始终态：`Ran 2402 tests in 476.578s` / `OK (skipped=3)`；`[full-pack-ledger] RESULT status=PASS exit=0 tests=2402`。
- 交接门：固定 Python bounded command `tests.test_route_doc_ledger_status_consistency` + `tests.test_doc_governance_guard`，最终文档落盘后复跑 `Ran 55 tests in 1.732s` / `OK`；receipt `receipt:fa397a6712f19cd5c229ddbe`。

### NOT_VERIFIED、审查/提交边界与下一步

- `NOT_VERIFIED`：Claude Code 对当前修复 diff 的独立复审、用户翻转生产 effect、完整 live/weekly 消费、commit/push/merge；本轮未起 sub-agent，未改变生产 effect contract。
- 两条 P1 只有经 Claude Code 独立复审确认后才能关闭并按项目规则提交；full lane `PASS` 只代表自动化回归通过，不代表独立审查 PASS，也不代表历史频率已经 COMPLETE。
- 下一步：`Claude Code：审查序22b P1修复`。

## 2026-08-05 追加：序 23 · 北向静默门通电（★☆☆☆☆，1 刀，真钱门激活）

**性质**：这不是修缺陷，是**把一道已建好、已审过、已用真实历史验过的风控从「只记录」翻成「真生效」**。改动极小，但落点是真钱边界，故按满标准走。

### 证据基础（序 22b 产出，已独立审查 PASS 并合入 `f93e2125`）

- 三年 155 周中 **123 周可用**，门会触发 **5 次 = 4.1%**。
- 5 次全部落在 **2023-11-10 / 12-08 / 12-15 / 12-22 / 2024-01-12**，即 2023 年底至 2024 年初那一波持续下跌；**此后两年半（2024-01 → 2026-08）一次未触发**。形态是「事件型」而非「闪烁型」——真跌时响，平时安静。
- 未覆盖的 32 周中 13 周 warm-up 落在 **2023-08~11**，与上述触发段同属一波下跌。**故 4.1% 是下限不是上限**；补齐覆盖只会抬高触发率，不会翻转结论。
- **行为后果（必须让用户在授权前知道）**：开启后按历史节奏约**每年 1–2 次、每次连续数周不建新仓**。这是真实的行为改变，不是纸面标记。已有持仓不受影响（门只降级 `操作=建仓` 行）。

### 已定口径（实现不得再自行解释）

1. **只翻一个常量**：`engine/a_short_northbound.py:12` 的 `NORTHBOUND_MARKET_GATE_PRODUCTION_EFFECT_ENABLED` 由 `False` 改 `True`。
2. **不动阈值、不动判据**：`NORTHBOUND_CSI300_SILENCE_THRESHOLD_PCT = -10.0` 与 `should_block_new_entries` 的双条件逻辑**一个字不改**。本刀只改「生不生效」，不改「什么时候该响」。
3. **不动降级机制**：`_apply_northbound_market_gate` 仍只降 `操作=建仓` 且不碰已有持仓；不改成压现金系数（那是节前减仓与序 19 的机制，与本门不同）。

### 不得碰的三处同名字段（起草时实读确认，防误改）

实现方会 grep 到 `production_effect_enabled` 的多个命中，**其中三处与本门无关**：

- `runners/a_short_weekly_pipeline.py:607` —— 主题 **overlay** 的字段。
- `runners/a_short_weekly_pipeline.py:758` —— `earnings_bad_reaction` 的 **operation_impact** 条目。
- `engine/a_short_northbound_lookback.py:405` + schema `{"const": false}` —— 语义是「**回看产物自身**无生产效力（comparison-only）」，**不是门的状态镜像**。翻门时**必须保持 false**，否则 `tests/test_a_short_northbound_market_wiring.py:210` 的 `assertFalse` 会红，而那条断言是对的。

> **顺带记一条可读性陷阱（Optional，本刀可不修）**：同一个字段名 `production_effect_enabled` 在 `analysis_input.market_context.northbound`（= 门的状态）与回看产物（= 产物属性）里含义不同。日后读者可能据回看产物的 `false` 误判门是关的。建议某刀把回看侧改名为 `artifact_production_effect` 或补 schema `description`。

### 实现范围

1. 翻常量（第 1 条）。
2. **契约重封**：`engine/a_short_northbound.py` 同时在 `_DECISION_FILES` 与 `_CONSTANT_FILES` 内，故 `runtime_constants_sha256`（及可能的 `decision_predicate_sha256`）必变，须用 `_build_static_inventory()` 重算重封，收工后 `static_contract_error()` 必须为 `None`。
3. **测试从「钉 OFF 态」改为「钉一致性」**：起草时实读确认**没有任何测试直接断言该常量为 `False`**（grep 命中 0），故翻转不会引起意外红。但现有 `tests/test_a_short_northbound_market_wiring.py` 用显式参数 `production_effect_enabled=True/False` 双向覆盖，本刀须**新增一条断言把生产默认值钉住**——即「不显式传参时，`_northbound_control_from_analysis` 得到的 `production_effect_enabled` 等于 `engine.a_short_northbound` 的常量」，防止将来两侧再分叉。
4. **产物可见性**：确认 `analysis_input.market_context.northbound.production_effect_enabled` 与 `weekly.northbound_control.production_effect_enabled` 均随之变 `true`，且 `m67_render` 的横幅从「仅记录未生效」切到「已触发」分支（该分支已在序 12 建好）。

### 验收（正控 + 三反控 + 一植入）

| # | 类型 | 断言 |
|---|---|---|
| ① | 正控 | 注入 `status=outflow` + `net_flow_5d<0` + `csi300 < -10` → 本周所有 `建仓` 降为 `观察`，`new_entry_blocked=true`、`reason="dual_condition"`，`allocated_cash_total` 归 0 |
| ② | 反控·单条件 | 只跌不流出 / 只流出不跌 → 现金与操作**逐字段不变** |
| ③ | 反控·数据缺失 | `status="unknown"` 或覆盖不全 → **不封门**，`reason` 为 `northbound_unknown` / `csi300_unavailable` |
| ④ | 反控·持仓不受影响 | 同一封门周内，已有持仓行的 `m67` 与 `machine` **逐字节不变** |
| ⑤ | 植入控制 | 把常量改回 `False` → ① 的正控**必须转红**（这是本刀唯一真正新增的行为，必须证明它承重）|

**测试落点**：新增/改动用例必须落在 `test_a_short*.py` 选择器内。

### 边界（不得扩大）

不改阈值 `-10.0`、不改双条件判据、不改降级机制、不改选股/EGS 打分/TopN/M6.7 操作判定/已有持仓处置/provider 参数/PIT 窗口；不动上面点名的三处同名字段；不并入序 19；不改回看产物的 `comparison_only` 与 `production_effect_enabled`。

### 已知边界：约 12% 的周结构性失明（港股假期，非缺陷、不可靠多取数改善）

**起草后补入（2026-08-05，reviewer 实读 gitignored raw 得出）**

- 取数本身没问题：`provider_samples/a_short_northbound_lookback_20260804/northbound_moneyflow_hsgt.json` 实测 **702 行、`20230804..20260804` 完整三年**（分 3 段 243+242+217 取回）。同期 `csi300_index_daily.json` 为 **726 行**。
- 两者差 **24 个交易日**，逐年分布（2023 缺 5 / 2024 缺 9 / 2025 缺 6 / 2026 缺 4），不是断崖。缺的日期为：
  `20230901 20230908 20231023 20231225 20231226 20240329 20240401 20240515 20240701 20240906 20240918 20241011 20241225 20241226 20250418 20250421 20250701 20251029 20251225 20251226 20260403 20260407 20260525 20260701`
- **规律明显**：`1225`/`1226` 连续三年出现、`0701` 连续三年出现，另有 `0329`/`0401`/`0418`/`0421` 等复活节前后日期，以及 `20230901`/`20230908`/`20240906`/`20240918` 等疑似台风/黑雨停市日。**推断这些是「港股休市、A 股开市」的日子**——北向走沪深港通，港股不开门则当日无北向交易，故无数据。**这是真实市场事实，不是 provider 缺陷。**
- **诚实边界**：上述归因由日期形态**推断**得出，起草时**未**比对权威港股交易日历（未消耗额外 provider 预算）。实现方若采纳下述建议，须以真实港股日历确认后再落分类，不得照抄本推断。

**对本刀的后果（用户授权前须知）**

- 覆盖判据要求北向 5 日与 A 股交易日**逐日严格对齐**，故**只要一周含一个港股独有假期，该周就永久判 `unavailable`**。回看里的 19 周 `source_gap` 正是这类。
- 即约 **12%（19/155）的周门是结构性失明的**——它既不拦你，也不会主动说明「本周未判定」。**这个比例不会因为多取数而改善**，港股假期每年都有。
- 这不构成拒绝通电的理由（失明周门的行为是 fail-closed 的「不拦」，与门关闭时一致），但用户应在授权前知道：**开门不等于每周都有判定**。

**建议（Optional，可并入本刀也可另起）**

把 `unavailable_reason` 的 `source_gap` 再细分出 `hk_holiday` 一档，判据为「缺失日在 A 股交易日历内但不在港股交易日历内」。这样通电之后，产物能一眼说明「本周未判定是因为香港休市」，而不是笼统的「有缺口」。同一分类也应出现在 live 侧的 `weekly.northbound_control.reason`，否则周报读者仍看不出原因。

### 前置：用户明确授权

本刀是**真钱门激活**，`AGENTS.md` 的执行边界要求这类改动由用户明示。用户已于 2026-08-05 在对话中要求起草本刀；**开工前仍需一句明确的执行授权**（起草 ≠ 授权激活）。执行方不得自行开工。

## 2026-08-05 追加：Codex 执行序23（北向静默门通电；待序19后统一最终全量）

### 本次问题、根因与改动

- 不是谓词缺陷，而是序22b已审查通过的真钱门仍处于 governance OFF：`NORTHBOUND_MARKET_GATE_PRODUCTION_EFFECT_ENABLED=False` 只记录、不改变新建仓。
- 用户本轮明确授权后，将 `engine/a_short_northbound.py` 的共享开关改为 `True`；`-10.0` 阈值、`should_block_new_entries` 双条件、`_apply_northbound_market_gate` 新建仓-only/持仓不变逻辑均未改。
- `schemas/analysis_input.schema.json` 北向开关同步为 `const=true`；effect contract 的事实说明同步并重封 `runtime_constants_sha256`。
- `runners/a_short_weekly_pipeline.py::_northbound_control_from_analysis` 的缺省开关改为读取同一共享常量，新增默认 source-binding 测试，防止 producer/consumer 分叉。
- 生产者测试同步 active；北向回看 artifact 的 comparison-only `production_effect_enabled=false` 反控保持原样。

### 调用链、直接消费者、schema/source-binding、写盘边界

`engine.a_short_northbound` shared switch → `A-EGS/egs_main.py::market_environment/_northbound_provider_facts` → `analysis_input.market_context.northbound.production_effect_enabled` → `_northbound_control_from_analysis` / `_normalise_northbound_control` → shared `should_block_new_entries` → `_apply_northbound_market_gate` → `weekly.northbound_control` + M6.7 new-entry action + `reports[].machine.operation_impact` + Markdown banner。

- schema 边界是 `analysis_input.schema.json` 的北向 `const=true`；effect contract 的 `runtime_constants_sha256` 已更新，`static_contract_error()` 为 `None`。
- 同名字段边界已保留：`runners/a_short_weekly_pipeline.py` 主题 overlay/earnings impact 和 `engine/a_short_northbound_lookback.py` comparison-only 产物仍不变；回看产物不进入生产决策。
- 本轮没有 provider/live/account/order/正式周跑、没有刷新 raw/summary 运行产物；只改 tracked code/schema/contract/tests。

### 验收、负向控制与自审

- 正控：outflow + 5/5 complete + CSI300 `< -10%` + active → new-entry builds 全降为观察、`new_entry_blocked=true`、`reason=dual_condition`、结构化 impact 落地。
- 反控：只满足一个条件、unknown/partial coverage、已有持仓、显式 `effect=False` 均不错误封门；中和 `_apply_northbound_market_gate` 后正控转红；comparison-only summary 仍为 false。
- 固定主 Python：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `3.13.8`。
- 精确 focused 命令：
  `Set-Location -LiteralPath 'D:\cnhea\Codex\worktrees\29e0\Stock'; & '.tools\run_unittest_with_repo_pythonpath.cmd' 'tests.test_a_short_northbound_market_wiring' 'tests.test_a_short_egs_market_environment' 'tests.test_a_short_effect_contract' 'tests.test_a_short_effect_consumer_probe' 'tests.test_a_short_weekly_pipeline' 'tests.test_a_short_public_json_writer_nonfinite_guard'`
  原始终态：`Ran 613 tests in 120.190s` / `OK`；`receipt:69cfa1f3b213189f4541a954`。
- static contract `None`、changed Python `py_compile=0`、`git diff --check=0`；A-F self-review complete。`sub-agent=NOT_USED`。

### NOT_VERIFIED、审查/提交边界与下一步

- `NOT_VERIFIED`：与序19合并后的最终 full lane、Claude Code 独立复审、用户后续 live/账户影响、commit/push/merge；本轮不称 PASS。
- 序23单独 full lane 按连续序19执行后的“一次最终 full lane”规则暂不启动；序19结束后最终行为/契约状态只跑一次 full lane，之后只做 docs-only 追加。
- 当前审查/提交边界：executor/fixer 不 commit；独立 reviewer PASS 后按项目流程提交。下一步：`Codex：执行序19`。

## 2026-08-05 追加：队列表按实际进度刷新 + 五条过期口径更正（文末更正节）

### 本节作用

本文件多处口径停在 2026-08-03/04，而后续几刀的实读结论已推翻它们。本节把五条已知过期的说法就地更正（上方相应位置已加更正块并指向本节），并把队列表刷到当前进度。**不改任何代码、不改任何业务判据**，纯文档口径收敛。

### 五条更正

- **① 序 11（#09）的范围：28 条叶 → 全部 schema leaves**。原文（队列表第 11 行、约束①、约束③）说「携带 28 条叶的处置」「按既有 `true_dangling` 逐条标注即可」。实读当前代码：系统已有逐叶 `leaf_effect_overrides` 与机械派生的 `producer_constant_null`，测试按 schema 全量 leaves 对账。真缺陷是 **group nature 与逐叶 effect 两层账并存**，且大量未举证叶落 `unclassified_pending_audit`。
- **① 的正确范围**：把 `leaf_effect_overrides` 升为**覆盖全部 leaves 的唯一闸门**（keys 与 `analysis_input_paths(schema)` 精确相等，数量动态取自 schema、不硬编码 28/388）；**删除 `leaf_nature_by_group` 的放行权**，group nature 降为逐叶机械派生的摘要；收口后不允许 `unclassified_pending_audit` 留在正式 contract。**不新增 nature 概念**（这一点原约束③说对了），也**不得**再加 `leaf_nature_by_path`——那会是第三张重复账。
- **② 序 16 仍有实质待裁项**。2026-08-04 六条裁决的⑤ 写「它没有待裁项，只有前置输入」，**已不成立**。序 14 起草时实读发现：v14.2 的「涨停指数」在仓库内**没有权威数据源也没有精确定义**（现有 V14.3 comparison 正是用晋级率/炸板率替代它）。不得用 CSI300、涨停家数或自造等权篮子冒充。**在用户批准该指数 source-binding 前，序 14 只能是 partial、序 16 不得开工。**
- **③ 序 19 的阈值证据由它自己那刀产**。序 19 口径第 6 条写「等 22b 的回看统计」，**是错的**——22b 产的是北向回看，与两融分位无关。同一节开头的「顺序更正」已指出这点，第 6 条当时漏改。序 19 同刀发布 p80/p85/p90/p95 四档的触发周数、最长连续周与年度分布，用户据此一次性裁定阈值与现金系数。
- **④ 序 15 的前置已解**。队列表第 15 行停在「验完再定方案」，但序 20 早已验完并合入：**IV feed 不依赖 EGS 输出，三选一已选 A（调换次序让 IV feed 先跑）**，不需要 EGS 跑两趟。本文件下方序 20 的结论节本就写对了，只是队列表那一行没跟着改。
- **⑤ 队列表的 ✅ 账已刷新**。序 18 / 序 20 补上 ✅；新增序 21 / 22a / 22b / 23 四行（原本表里根本没有）；「剩余 11 刀」重算为 **8 刀**（已销 #14=序18、IV-feed 验证=序20、#08 northbound=序12）。

### 剩余 8 刀的当前真实状态

| 序 | 条目 | 复杂度 | 可否开工 |
|---|---|---|---|
| 19 | #16 全市场融资过热接线 | ★★★☆☆**不止**（含 `_allocate_cash` 现金系数栈改造） | ✅ 可，下一刀 |
| 7 | #02 汇总/账本事务性 | ★★★★☆ | ✅ 可 |
| 8 | #10 `price_as_of` 双口径 + 资金流容差 | ★★★☆☆ | ✅ 可（口径 2026-08-04 已裁） |
| 13 | #08 liquidity 接线 | ★★☆☆☆ | ⛔ 待用户确认「删除式不接」 |
| 14 | #08 breadth 接线 | ★★★☆☆ | ⚠ 部分：涨跌停家数/连板高度可做；「涨停指数」待 source-binding 裁决 |
| 15 | #08 volatility 接线 | ★★★★☆ | ✅ 可（序 20 已解前置，方案 A） |
| 16 | #08 market_regime 接线 | ★★★★★ | ⛔ 被序 14 的指数源与序 15 同时卡住 |
| 11 | #09 反悬空守卫粒度 | ★★★★★ | ✅ 可但**必须放最后**（序 13-16 每接一把，本刀包袱少一分） |

### 序 23 审查收口（补登）

- 序 23 北向静默门通电已经 Claude Code 独立审查 = **PASS**，已提交并合入 master `b217f09a`。上一节 Codex 执行记录里的 `NOT_VERIFIED`（独立复审 / commit / merge）已被本条 supersede；「下一步：Codex：执行序19」仍有效。
- finding 正文单一来源仍在 `docs/system_risk_register.md`（序 23 审查节 + 一条 P1 收口 + 一条 Optional），本处不复述。
- 序 23 不再等「与序 19 合并后的最终 full lane」：合入时已单独跑过全量 `RESULT status=PASS exit=0 tests=2404`。序 19 落地后仍按其自身规则跑一次最终全量。

### 本节未做 / 仍存的矛盾

- ~~**序 13 liquidity 的处置方向仍未定**：删除 vs 保留标注互斥。~~ **已裁（2026-08-05 用户定）：删**。详见下方「序 13 裁决」节。
- ~~**序 19 在桌面汇总视图里只有一条「☆纯裁决」**。~~ **已补（2026-08-05）**：桌面已加入序 19 工程刀的汇总表行与完整方案（含 `_allocate_cash` 改造与八项验收），与本节同源。

### 序 13 裁决（2026-08-05 用户定）：删除式不接

- **裁决**：从当前 schema 的 `market_context` 删掉整个市场级 `liquidity` 对象（`market_turnover_amount` / `median_amount_20d`），不保留运行时 alias、不新增任何成交额阈值。逐票 `candidates[].liquidity` **完全不动**。三条备选（A 接进 regime 判据 / B 做个股流动性相对基准 / C 保留并标「有意不接」）全部否决。
- **工程理由**：v14.2 的 regime 触发条件里没有成交额这一项，系统也没有任何市场级成交额消费者。保留两个永远为 null 的公开字段只会制造「以后也许有用」的假契约，且序 11 还得为它们各写一条交代。
- **交易理由**：① 成交额是「因」，v14.2 盯的连板高度/涨跌停家数是「果」，果比因准（缩量不一定杀情绪，连板掉了就是真掉）；② 成交额对后市的映射**非单调**——缩量既可能是顶部退潮也可能是地量地价，同一阈值在 2023-08 与 2024-01 含义相反，做不了阈值门。
- **交易理由（续）**：③ M6.7 是逐票操作表，大盘成交额落不到任何一行的买点或止损位上，唯一合理落点是仓位总闸——而那是 regime 的杠杆，绕回冻结规格；④ 短线真正的流动性风险在**个股出不去**，那道防线已由逐票绝对额门槛承担；⑤ 日成交额是落定的历史事实、随时可从 provider 回取，**没有 PIT 脆弱性**，所以「先留着攒历史」这个理由不成立。
- **将来重新接的触发条件**：forward 账本显示「缩量区间里胜率/盈亏比系统性变差」。那时按北向门的同一条治理路走（带真实消费者的刀 → 先只记录 → 回看统计 → 用户看过证据拍板 → 通电），并同刀定义清楚口径（两市还是含北交所、绝对额还是相对 20 日中位的量比）。
- **对序 11 的影响**：这两条叶将不再存在，序 11 的全叶账本不必为它们举证；effect contract 只按新 schema 动态 inventory 结算，不得为了「保留 388」留假叶，也不得把删除写成 `main_decision`。

## 2026-08-05 追加：序 14 前置查证刀 —— v14.2「涨停指数」数据源探针（reviewer 自执行）

### 为什么打这一刀

序 16 被序 14 的「涨停指数 source-binding」卡住，而这个 source 到底存不存在**从来没有人查过**——V14.3 设计文档只是绕过它。在用户面前摆 A/B 选项之前，得先知道 A 是不是根本不可行。

### 结论：当前权限下取不到

- 枚举 `index_basic` 全部 7 个发布方分区共 **10,506 条指数**，按 `涨停/跌停/打板/连板/首板/涨跌停` 匹配名称 → **0 条命中**；每个分区均由不足页证明已穷尽。
- `ths_index`（同花顺概念板块）→ `permission_or_entitlement`，**账号无此权限**。这是唯一没能看到的地方，属 `NOT_VERIFIED`，不得写成「已确认不存在」。
- 故**选项 A（绑定真实「涨停指数」）在当前权限下不可行**；要走 A 须先买同花顺权限，且那仍是厂商自造指数、构造法不可验证，**证明不了它就是 v14.2 所指**。

### 首轮差点报错结论（同类复发，已闭）

首轮在 `index_basic(market='CSI')` 返回**恰好 8000 行**时就报了「不存在」——实测 `offset=8000` 还有 863 行，即只搜了 92.5%。**与序 22b 的 `FETCH-TRUNCATED-AT-PROVIDER-ROW-CAP` 同类**。已改为按页取到不足页为止，并让未穷尽分区把 verdict 降级为 `negative_but_universe_coverage_incomplete`。register 单一来源两条：`R-ASHORT-V142-LIMIT-UP-INDEX-HAS-NO-REACHABLE-PUBLISHED-SOURCE`、`R-ASHORT-LIMIT-UP-INDEX-PROBE-FIRST-PASS-TRUNCATED-AT-PROVIDER-ROW-CAP`。

### 边界与产物

- 新增 `runners/a_short_limit_up_index_source_probe.py`（bounded、只读、注入式 client）与 `tests/test_a_short_limit_up_index_source_probe.py`（8 条，含防截断植入对照）。writer 已登记进 `PUBLIC_WRITER_FUNCTIONS`（序 22b 的教训）。
- raw 落 gitignored `provider_samples/a_short_limit_up_index_source_probe_20260805/`；tracked summary `docs/a_short_limit_up_index_source_probe_summary_20260805.json` 只含形状/计数/命中项的代码与名称，无 raw 行、无请求 URL、无密钥（已 grep 验证）。
- **未改任何生产行为**：不碰 EGS/weekly/TopN/M6.7/仓位/冻结规格；不做 regime 分类；不接消费者。
- provider 调用 `9/20`，全部只读参考端点。

### 下一步（用户裁决项）

- **A**：买同花顺板块权限再查一次（代价：花钱 + 即便查到也证明不了口径一致）
- **B**：采用 V14.3 的晋级率/炸板率替代（数据侧已有 281 天逐日历史；代价：动冻结规格 + 切换门要 ≥12 周前向证据，当前 `total_forward_weeks=0`）
- 序 14 的涨跌停家数/连板高度**不依赖本指数**，可先做，完成后状态为 partial；序 16 在裁定前不得开工。

### 2026-08-05 同轮补查：项目自有同花顺通道也取不到（用户指出后）

首版结论把「同花顺」记成**唯一没看到的地方**并标 `NOT_VERIFIED`——**这是漏查**。用户指出我们之前就在用同花顺金融数据 API，实读确认：`HITHINK_FINANCE_API_KEY` 是 L3 概念图谱的**生产凭证**（`engine/a_short_hithink_l3.py`，`https://fuyao.aicubes.cn`）。

- **补搜结果**：其板块目录 `cn_concept` 共 **390 个板块，0 个**带涨停类字样；`cn_industry`/`cn_region`/`cn_style`/`cn_special`/`cn_tech` 五个 tag 该账号均不可达；空 tag 等同 `cn_concept`。
- **更致命的一层（结构性）**：该 API **只有目录与成分两个端点，没有任何行情端点**。即便存在「昨日涨停」板块，拿到的也只是**成分股名单**，拿不到**指数点位或涨跌幅**——而 v14.2 判据「涨停指数跌>3%」是对**指数日涨跌幅**的陈述。**这一层买权限也解决不了。**
- **探针已补齐该腿**：`probe_hithink_catalog()` 逐 tag 搜索并记录可达性；HiThink 腿未真正搜成时，总 verdict 降级为 `negative_but_universe_coverage_incomplete`，不允许读成干净的「不存在」。新增 6 条测试（含「无凭证不等于不存在」与「该面无法发布指数点位」两条）。
- **教训**：查数据源时「我们有没有这个厂商的通道」必须先扫**自有凭证与已接线模块**，再去问转发方。只查 Tushare 转发就把自有直连当成不可达，是这一轮差点犯的第二个完整性错误。

## 2026-08-05 追加：epoch 语义投影刀（reviewer 自执行，用户授权）

### 为什么打这一刀

用户问「起 12 周时钟」，核出一个死锁：时钟要攒 12 周不被作废 → 序 11 不能落地；序 16 要接 V14.3 必须排在时钟之后；而序 11 必须放最后。转不动。

根因**不是「设计没定」，是「指纹哈希整文件」**——一个跟判定毫无关系的字段改动也能作废三个月证据。这是机器的毛病。

### 改了什么

冻结包 8 份契约由**整文件字节哈希**改为**按契约声明的语义投影**（`_CONTRACT_PROJECTIONS`）：治理 preset 去注解规范化、JSON Schema 只留校验关键字、P4a Python 契约按路径读取的 AST（不导入、不经 `inspect`）、效果契约只绑决策面而排除叶账本六键。冻结包与 schema 去掉恒会腐烂的 `sha256`，改由 `projection` + `semantic_fingerprint` 把关；漂移报错点名契约与投影，不再静默。

### 死锁解开了

- 序 7 / 8 / 13 / 14 / 15 不碰对比判定 → **不作废**
- **序 11 重写叶账本 → 不作废**（本刀的头号目标，有专门测试钉住）
- 序 16 本就排在时钟之后 → 不冲突
- 真改了判定（阈值、校验关键字、可执行代码）→ **仍然作废**，且会说是哪份契约哪种投影

### 边界

不改任何选股/EGS/仓位/真钱行为；**没有**翻任何轨的 `pre_freeze_audit_only`（起不起时钟是用户决策）；不改 12/24/36 周门槛本身。

### 验证

focused `Ran 117 tests ... OK`（`receipt:728b842b330d5995304d1fb9`）；a_short 全量 `RESULT status=PASS exit=0 tests=2430 elapsed=550.9s`——账本拒绝记录，因为跑的 550 秒里另一窗口在改 us_short，绿是真的但没绑上稳定指纹。植入对照两次均转红后还原。register 单一来源：`R-ASHORT-EPOCH-WHOLE-FILE-HASH-DISCARDS-EVIDENCE-ON-UNRELATED-EDITS`。

### 下一步

用户决定起不起 12 周时钟（翻 `regime` 相关轨的注册表条目）。翻之前不必再等其它刀。

## 2026-08-05 追加：用户裁决 —— 设计定稿前不起 12 周时钟

### 裁决

**不起时钟。** epoch 维持现状（七条轨全 `pre_freeze_audit_only`），既不废除也不激活。剩余 8 刀照常做，epoch 不会拦。序 16 随之推后。

### 为什么（这个矛盾工程上消不掉）

12 周证据的意义在于「同一套不变的契约」。**关着哈希起时钟 → 攒出的 12 周没意义**（可能第 6 周改了判据）；**开着哈希起时钟 → 设计还在动，反复归零**。两者互斥。同日做的语义投影刀只能减少冤枉的归零，消不掉矛盾。

### 现状确认（实读，非推断）

`pre_freeze_audit_only` 下：轨指纹是固定常量、8 份契约哈希校验根本不跑、`evidence_counts_toward_clock()` 恒 False。**当前改任何代码都不作废任何东西**——2026-07-25 的规矩一直在执行，不需要另外"废掉哈希"。

### 本会话两条自纠（重要）

- 「起时钟成本近乎零、建议起」**框架错误**。成本不在翻开关，在于设计未定时攒的证据不算数。
- 「序 7/8/13/14/15 不碰对比判定故不作废」**是错的**。`decision_predicate_sha256` 哈希 9 个生产文件的全部 `if`/`while`/`assert` 条件，**剩余每一把刀都会改到其中至少一个**。

### 将来起时钟的三步（缺一不可，按序）

1. **按轨分绑**——取消七轨共绑 9 文件的一刀切，每条轨只绑它真正消费的生产文件，并加守卫。
2. 翻对应轨注册表条目为 `frozen_enforced`。
3. **从翻的那天起**数 12 周 + ≥8 个分歧样本。

### 边界

**AI 协作者不得自行提议起时钟。** 单一来源：`docs/system_risk_register.md` 的 `R-ASHORT-TWELVE-WEEK-CLOCK-DEFERRED-UNTIL-DESIGN-FREEZE`。

## 2026-08-05 追加：执行序 19（#16 全市场融资过热接线，含现金系数栈改造）

> 执行方 = Claude Code（本工作树 `wt/ashort_r1`）；未 commit / 未 merge / 未 push，等独立审查。finding 正文单一来源 = `docs/system_risk_register.md` 的 `R-ASHORT-SEQ19-MARGIN-OVERHEAT-WIRING`，本节不复述。

### 改了什么

1. **新引擎 `engine/a_short_margin_overheat.py`**（纯离线）：三所 `rzye` 逐所过 22a `reconcile_dated_series` 后求和 → 滚动 3 年分位；`should_reduce_new_exposure` fail-closed 谓词；`fetch_segments` 按 vendor 行上限分段；`resolve_published_window` 处理发布延迟；`threshold_trigger_evidence` 产四档触发统计。两条治理常量（分位阈值、现金系数）**留空 `None`**，`MARGIN_OVERHEAT_PRODUCTION_EFFECT_ENABLED = False`。
2. **`runners/a_short_weekly_pipeline.py::_allocate_cash` 现金系数栈改造**：单一 `pre_holiday_control.cash_factor` → `_resolve_cash_factor_stack` 取各控制**最小值**；新增 `_normalise_margin_overheat_control` / `_margin_overheat_control_from_analysis`；`build_weekly_report` 与 `validate_weekly_report` 各加一个参数把控制绑回 analysis_input；`cash_allocation` 新增 `margin_overheat_control` 与 `cash_factor_stack` 两个审计对象。
3. **`A-EGS/egs_main.py` 生产者接线**：`market_environment` 里取 3 年 `trade_cal` + 分段 `pro.margin`（各自截断即 fail-closed），写进 `analysis_input.market_context.margin_overheat` 八条叶；`EGS_API_FAMILIES` 加 `margin`；**占位文案「待接入两融余额历史分位」换成与实际口径一致的句子**（口径 2 要求）。
4. **schema**：`analysis_input.schema.json` 新增 `market_context.margin_overheat`（`production_effect_enabled` const-pin 为 `false`，与引擎常量三角断言）；`a_short_weekly_report.schema.json` 的 `cash_allocation` 新增两个对象；新建 `schemas/a_short_margin_overheat_percentile_evidence.schema.json`。
5. **契约重封**：`engine/a_short_effect_contract.py` 的 `_DECISION_FILES` / `_CONSTANT_FILES` 收编新引擎；`schemas/a_short_m67_effect_contract.json` 补 8 条 `leaf_effect_overrides` 并重算 `analysis_input_all_paths_sha256` / `market_context` 组指纹 / `decision_predicate_sha256` / `runtime_constants_sha256` / `output_schema_sha256`。
6. **取数刀 `runners/a_short_margin_overheat_percentile.py`** + tracked 产物 `research/results/a_short/margin_overheat_percentile_threshold_evidence.json`；writer 已登记进 `PUBLIC_WRITER_FUNCTIONS`（序 22b 的教训）。

### 为什么改

序 19 的三条硬约束决定了形状：① 新增叶必须**同刀接消费者**，否则立刻造 `true_dangling` 撞序 11 的账本；② 多门相遇**取最小不相乘**，而全仓原本没有现金系数栈，最省事的写法正好是被禁止的连乘，所以栈改造是前置而不是附带；③ 阈值不许发明，所以同刀必须产出用户裁决所需的四档触发频率。

### 验证命令

- focused：`.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.test_a_short_margin_overheat_wiring tests.test_a_short_margin_overheat_percentile_runner tests.test_a_short_market_history tests.test_a_short_egs_market_environment tests.test_a_short_northbound_market_wiring tests.test_a_short_pre_holiday_cash_guard tests.test_a_short_weekly_pipeline tests.test_a_short_effect_contract tests.test_a_short_effect_consumer_probe tests.test_a_short_public_json_writer_nonfinite_guard tests.test_a_short_evidence_epoch_mode tests.schema.test_analysis_input_contract tests.schema.test_a_short_fifth_knife_forward_evidence_freeze_schema`
- 取数：`python runners/a_short_margin_overheat_percentile.py`（真跑，4/6 调用）；`--replay-raw`（零调用重算）
- 静态：`py_compile`、`git diff --check`、`static_contract_error`、JSON/schema 校验、BOM/U+FFFD 扫描
- full lane：`.tools\full_pack_ledger.py run a_short "<trigger>" "receipt:<focused>" 860 -- discover -s tests -p "test_a_short*.py"`（按 AGENTS rule 3(a)：改了 `runners/a_short_weekly_pipeline.py` 与 `A-EGS/egs_main.py` 两个生产顶层入口）

### 验证结果

见 SESSION_LOG 顶条与 register 的 Closure tests 节（单一来源，本处不复述计数）。**真实取数结论**：窗口 `20230807..20260804`、725/725 交易日三所全齐、当前分位 `0.8276`、三所合计约 `2.59e12` 元；四档触发统计 p80/p85/p90/p95 = 53/51/50/45 周（可评 53 周），**最长连续 53/51/50/32 周**。

**⚠️ full lane 未跑完**：`RESULT status=TIMEOUT exit=124 tests=UNKNOWN elapsed=860.3s`。已打印的约 780 条无一失败（仅 3 skip），但按 AGENTS rule 5 超时即 UNKNOWN，不得记为通过；860 秒上限未经用户批准不得上调。本机当前吞吐异常低（今天 756 条聚焦用例跑了 754 秒，历史同 lane 是 2430 条 / 551 秒），与另一窗口并发占用一致。审查方若要完整全量属 rule 6 escalation。

### 失效的旧结论

- **「序 19 只有 ★★★☆☆」失效**：`_allocate_cash` 改造属实是本刀最大的一块，星级实际不止（队列表与桌面已提前更正过，这里确认属实）。
- **「窗口右端 = 决策日」失效**：`pro.margin` 有一个交易日的发布延迟（2026-08-05 实测当天无行、最新到 08-04）。窗口右端改为「最新一个三所齐全的已发布交易日」，滞后超过 1 个交易日即 fail-closed。
- **「等 22b 的回看统计给出触发频率」早已被 2026-08-05 更正块判错**：本刀确实自己产出了这份频率，那条更正属实。
- **`A-EGS/egs_main.py:5971` 的占位行**不复存在；本文件上方约第 1030 行对它的引用是历史记录，按 doc-drift materiality gate 属非实质，未回改。

### 下一步注意事项

1. **这道门现在压不了任何仓**：分位阈值与现金系数两个治理常量都是 `None`，`production_effect_enabled=False`。要通电需要**同时**定这三样，缺一道都不生效——这是有意的双门。
2. **⚠️ 别照搬 p90**：实测三年里融资余额持续上行，「当前值处于近 3 年 90% 分位」几乎恒成立（可评 53 周里触发 50 周、最长连续 50 周）。照搬会变成无差别常态压仓。可选方向：改用变化率/斜率、更高分位配更短窗口、或判定该门在当前市场结构下不成立。这是**用户裁决项**，实现方不得代拍。
3. **证据口径与实盘门不同**：本刀发布的是 `expanding_trailing_window_min_480_sessions`（每周只用它之前的历史），实盘门比的是完整滚动 3 年；要按周复现实盘同口径需要 6 年历史，超出本批 ≤6 次的授权预算，故 101 个早期周如实记 `warm_up`。将来若要补齐，须另行授权更宽的取数。
4. **EGS 每周会多 4 次 provider 调用**（1 次 `trade_cal` + 3 次分段 `margin`），任一失败或截断都只让本门 unavailable，不影响其余周跑。
5. **真实 EGS 周跑内的这条腿未跑过**（本刀只用注入式 client 覆盖），属 `NOT_VERIFIED`。
6. 本刀未动 epoch 七条轨、未动逐票两融、未动选股/TopN/M6.7/持仓/PIT 窗口。

## 2026-08-05 追加：序 19 独立审查 —— FAIL（一条 P2 + 九条 Optional）

### 判定

**FAIL，未提交。** 七条已定口径逐条落地属实、验收八格覆盖到位、权威链闭合、卫生干净、已发布产物非伪造——这些我都独立复算过。拦住它的是一条 P2：**600 交易日下限只保护了 `current_percentile`，没保护整张四档阈值证据表。**

### 那条 P2 是什么

`runners/a_short_margin_overheat_percentile.py:143-187` 把同一份 rows 归约了两次：`margin_overheat_facts()` 里有 600 交易日下限，`market_margin_totals()` 里没有——它只做逐所 exact-date 对账，不认识「窗口该多长」。而 `:162` 的分支和 `:178` 的证据计算都吃后者。于是一个 500 交易日的窗口会写出 `coverage_complete: false` / `observed_session_count: 0` / `current_percentile: null`，**同时**写出一张 101 周、四档齐全的触发表，并通过 schema（该 schema 无任何跨字段约束）。

最要命的是 `status`：截断运行是 `PARTIAL`，而 2026-08-05 那次诚实的 725/725 满覆盖运行**也是** `PARTIAL`（因为有 warm_up 周）。**读者无法靠状态区分「窗口短了」和「早期周训练不足」**，而这两件事对那张表的可信度是天壤之别。

判它是缺陷而不是过度防御，理由是同一条规则的**兄弟实现已经挡了**：`A-EGS/egs_main.py::_margin_overheat_provider_facts` 明写 `if len(sessions) < MARGIN_OVERHEAT_MIN_WINDOW_SESSIONS: return unavailable`。生产腿有下限、证据腿没有，是同一不变式两处实现不一致。这也是本项目**同类第三次复发**（序 22b 行上限截断、涨停指数探针 8000 行截断）。

改法与三条 closure tests 见 `docs/system_risk_register.md` 的 `R-ASHORT-SEQ19-EVIDENCE-LEG-SKIPS-THE-MIN-WINDOW-FLOOR`（单一来源，本处不复述）。

### 我实际验了什么

- **验收超集亲跑**：`Ran 741 tests in 102.078s / OK`、`receipt:ebdd2262d4fef2d9c3c44291`（margin wiring + percentile runner + effect contract + consumer probe + epoch + weekly pipeline + market history + phase6 analysis_input/margin coverage + freeze schema）。
- **自写探针（不复用执行方的测试）**：取最小非连乘 `(0.8,0.7)→0.7`、`(0.6,0.9)→0.6`、并列时两个控制都记进 `binding_controls`，`0.56` 从未出现；注入 synthetic 阈值 0.9 / 系数 0.7 后 `on=0.7` / `off=1.0`，证明开关在未来真的承重；把 `production_effect_enabled: true` 伪造进 analysis_input → 被 schema `const: false` 拒；599 交易日声称 complete → 被消费端拒；不完整覆盖带 percentile → 被拒。
- **独立对抗 agent**（只读、隔离在取数腿）：20 条探针。覆盖 fail-closed、调用预算、惰性、secret / raw 卫生、字段与单位、产物是否伪造——**六类全部 HELD**；它独立从 raw 重算出的 `current_balance_yuan=2592313734952.0` 与 `current_percentile=0.8275862068965517` 与已发布值**逐位相同**，四档触发数、最长连续、年度分布也都能从产物自身的 `weeks[]` 复现。
- **两处性能缓存实测命中**（按「提速刀必验真命中」）：`_paths_for_prefixes` `hits=205 / misses=65 / currsize=65 < 2048`；epoch fingerprint `hits=16 / misses=8 / currsize=8`（恰 8 份契约）。键分别含完整叶路径元组与每次现读的文件正文，改叶集 / 改契约必换键，正确。

### full lane 的处置

执行方记 `TIMEOUT exit=124 tests=UNKNOWN elapsed=860.3s`，即 AGENTS rule 3 的义务**未完成**。按 rule 6 我本可 escalate 自己跑（记录不可得就是 escalation 条件），但按 rule 8 我**不代跑**：本刀要回修，任何现在跑出来的全量都会被后续改动作废，那是纯浪费。**须由执行方在修复后重跑一次。**

顺带一个新事实：执行方超时时归因于「本机每条用例慢约 4 倍，与另一窗口并发一致」。我今天跑 741 条只花 102 秒，即那次超时确实是并发争用的产物，不是代码变慢——修复后重跑很可能能在 860 秒内跑完，不需要申请上调上限。

### 未覆盖维度（诚实边界）

- **真实 provider 行为**：我与 agent 都没有联网。`trade_cal` 真实返回短窗口 / 改格式的概率是 `NOT_VERIFIED`，故上面那条 P2 判的是「门缺失」，不是「已发生的错误产物」——2026-08-05 那份已发布产物经双向独立重算为真，**没有**被这个缺陷污染。
- **真实 EGS 周跑内的这条腿**：只有注入式 client 覆盖，未跑真实周跑。
- **阈值本身**：四档触发频率没有区分度（p80 触发 53/53、p95 触发 45/53，53 个可评周里 percentile 最小 0.8216、中位 0.9861），根因是证据用扩张窗口、实盘门用定长滚动三年，两个估计量不同。执行方已在 register 里如实点破并给了三个方向。**这是用户裁决项，不是我判它 FAIL 的理由。**

## 2026-08-05 追加：序 19 修复轮 —— 给执行窗口的指令（Codex 额度不足，改由另一个 Claude 窗口执行）

### 先读这三条硬约束

1. **必须在 `D:\cnhea\Stock-wt\ashort_r1` 这棵树里做。** 序 19 的整份成果是**未提交**的工作树改动，别的树看不见它；在别处「修复序 19」只会凭空重写一遍。
2. **这棵树里有并发的无关脏改动，绝不 sweep。** `engine/a_short_experiment_admission_registry.py` 与 `engine/a_short_theme_forward_comparison.py` 是另一个窗口的**提速刀**，与序 19 无关，**不在本轮审查范围、不得改、不得暂存、不得提交**。本轮只碰下面「本刀文件清单」里的文件。
3. **本轮触发 `codex-fix-gate`**（输入含「修复」）。按 `.claude/skills/codex-fix-gate/SKILL.md` 走：从 register 的 `Required repair` + `Closure tests` **全文**枚举出整个缺陷类成 checklist，复现审查方的确切探针，SESSION_LOG 评审循环条目每 bullet ≤450 字一次过 doc-governance guard。

### 本刀文件清单（本轮唯一可动范围）

已跟踪改动：`A-EGS/egs_main.py`、`engine/a_short_effect_contract.py`、`engine/a_short_evidence_epoch_mode.py`、`runners/a_short_weekly_pipeline.py`、`schemas/analysis_input.schema.json`、`schemas/a_short_weekly_report.schema.json`、`schemas/a_short_m67_effect_contract.json`、`tests/test_a_short_effect_consumer_probe.py`、`tests/test_a_short_public_json_writer_nonfinite_guard.py`。
未跟踪新增：`engine/a_short_margin_overheat.py`、`runners/a_short_margin_overheat_percentile.py`、`schemas/a_short_margin_overheat_percentile_evidence.schema.json`、`tests/test_a_short_margin_overheat_wiring.py`、`tests/test_a_short_margin_overheat_percentile_runner.py`、`research/results/a_short/margin_overheat_percentile_threshold_evidence.json`。
文档：`docs/SESSION_LOG.md`、`docs/system_risk_register.md`、本 handoff、`docs/handoff/README.md`。

---

### 刀 A（**零授权、现在就做**）：闭掉 FAIL

**A-1 Required（唯一阻塞项）**：`R-ASHORT-SEQ19-EVIDENCE-LEG-SKIPS-THE-MIN-WINDOW-FLOOR`。按 register 该条的 `Required repair` 做最窄改法，并把三条 `Closure tests` 全部落地（含**植入对照**：改回读 `reconciled["coverage_complete"]` 必须让反控转红）。**不要**用抬高 `MARGIN_OVERHEAT_EVIDENCE_MIN_TRAILING_SESSIONS` 冒充修复——那改的是逐周训练期门槛，不是整窗下限。

**A-2 同轮必做（产物诚实性，与 A-1 改同一处 `not_verified` 列表）**：现在产物的 `not_verified[0]` 只说「早期周记 warm_up」，读者会以为局限只在覆盖度。必须明说：**已发布的四档触发频率来自「锚定起点的扩张窗口」估计量，与实盘门的「定长滚动三年」不是同一个口径，因此这些频率不能当作实盘门的预期触发频率**。理由：这份产物会随本刀合入并作为用户裁定阈值的存档材料。

**A-3 Optional（按项目规矩「修复轮 Optional 合理就一并修」）**：`R-ASHORT-SEQ19-REVIEW-OPTIONAL-BATCH` 九条。审查方建议**一并修** O-1（replay 无 provenance）、O-2（截断探测器不可达却报 complete）、O-3（非有限 `rzye` 崩溃且不落 raw）、O-4（中止报错原因不对）、O-5（连续周跨零交易周桥接 + ISO 年/自然年混用）——这五条都在同两个文件里、成本低。**建议延后**：O-6、O-7（消费端已挡，仅两侧不对称）、O-8（留给通电刀）。**O-9 不改代码**，只需在本轮 SESSION_LOG 与 handoff 里**显式声明**：本刀附带了 `_paths_for_prefixes` 与 `contract_semantic_fingerprint` 两处性能缓存，属超出实现范围五步的夹带，审查方已实测命中率与键正确性。

**A-4 验证**：focused 超集须覆盖 changed producer + 直接消费者 + schema/effect + 写盘 + 负向控制（审查方本轮跑的那套 741 条可直接沿用）。**rule 3 触发且上一轮 full lane 是 `TIMEOUT/UNKNOWN`，本轮必须由执行方跑完一次真正的 full lane**；860 秒上限未经用户批准不得上调。参考事实：审查方今天跑 741 条只花 102 秒，上次超时是并发争用不是代码变慢，本轮大概率能跑完。

**A-5 边界**：刀 A **完全离线**，不发任何 provider 请求，不重算证据表数值（只改它的诚实文案与产出条件）。不动 epoch 七轨、不动逐票两融、不动选股/EGS 打分/TopN/M6.7/持仓/PIT 窗口。不 commit（审查方 PASS 后提交）。

---

### 刀 B（**需要用户两个授权，未授权前不得开工**）：换掉被排序的那个量

**为什么要换**：融资余额的**绝对元数**长年随市场规模上行，拿它跟自己的历史比，量到的是「时间」不是「温度」。实测后果：53 个可评周里 percentile 最小 0.8216、中位 0.9861，p80 触发 100%、p95 触发 85%——四档之间没有区分度，照搬任何一档都等于全年永久压仓。一个能一眼看懂的佐证：当前三所合计融资余额约 **2.59 万亿元**，已高于 2015 年泡沫顶部的约 2.27 万亿（该历史数字为审查方引用，**须核**），而今天显然不是 2015 式泡沫——因为分母（流通市值）翻了一倍多。

**要换成什么（按优先级，探针结果回来后由审查方定口径）**：
1. **融资余额 ÷ 全市场流通市值**（首选，经济含义正确、跨年可比、真会均值回归）。取数最便宜的路子是 Tushare `index_dailybasic` 的指数 `float_mv`（一次调用拿一条指数的全历史），用沪深 300 或上证综指当规模代理；**该端点在本权限档能否取到未验证，必须先打形状探针**。
2. **融资余额 ÷ 自身 250 日均线的偏离度**（退路，只用已抓到的数据、零新授权，能去掉趋势漂移但经济含义弱一些）。
3. **纯 20 日变化率**：不推荐单独用（噪音大、会让现金仓位每周抖），只可作第二确认条件。

**用户须做的两个决定（缺任一即不得开工）**：
- **决定 1**：是否授权 1–2 次 `index_dailybasic` 形状探针（沿用序 21 探针模板：bounded、只读、注入式 client、raw 落 gitignored、tracked 摘要无 secret/URL/raw 行）。
- **决定 2**：是否把 `pro.margin` 历史由 3 年补到 6 年（约 +6–8 次调用）。补了才能让证据表用与实盘门**完全相同**的「定长滚动三年」口径逐周回看，A-2 那条诚实边界也随之消失；不补则证据表继续是扩张窗口近似。

**阈值定法（换量之后，写死进本轮方案，防止「看完结果再挑数字」）**：不要再问「p80 还是 p90」，先定**目标触发频率**，再从平稳化后的历史里反读出对应分位。审查方建议目标 **5–10% 的周（一年 2–5 周）**，与北向门实测的 3–4% 同量级。现金系数须与触发率配着定：一年响 3 周可到 0.5–0.6，一年响 15 周只能 0.85–0.9。

---

### 刀 C（等刀 B 的证据表过审后）

用户一次性裁定两个数（overheat percentile threshold + cash factor）→ 通电刀只落这两个数、把 `production_effect_enabled` 翻真、重封 schema/effect contract，验收沿用既有五格 + 取最小不相乘 + 已有持仓不受阻。

### 顺序建议

**A → 审查 → PASS 合入 → B（若已授权）→ 审查 → C。** 刀 A 不依赖任何授权，先把已验证正确的接线、现金系数栈与 fail-closed 银行进去；把 B 压在 A 后面，避免 P2 的闭合被 provider 授权卡住。

## 2026-08-06 追加：B0 分母源探针（reviewer 自执行，用户 `B0 授权`）

### 为什么打这一刀

序 19 的四档阈值表没有区分度（p80 触发 100%、p95 触发 85%），根因是被排序的量——融资余额的绝对元数——长年随市场规模上行。要换成比率，就得先知道分母拿不拿得到。这三件事此前全是假设：`index_dailybasic` 可达吗、`float_mv` 什么单位、两边历史各有多深。

### 三个假设变成事实

1. **分母可达，单位是元**。12 列，含 `float_mv`/`total_mv`/`float_share`/`free_share`。沪深300 于 `20260804` 的 `float_mv` = `5.1766e13`，量级 1e13 即元。单位是从观测量级读出来的，不是假设的。
2. **没有单一的全市场指数**。`000985.CSI`（中证全指）三窗口全 0 行且无报错——本权限档不发布。可达的是沪深300 与上证综指，两者六年前均有数据。
3. **`pro.margin` 六年前只有两所**。`20200803`–`20200807` 每日只有 `SSE`+`SZSE`（10 行），`20260729`–`20260804` 才三所齐全（15 行）。北交所 2021-11 才开市。

### 换量方向被数据证实了

只比 `SSE+SZSE`（口径可比），`20200807 → 20260804`：

| 量 | 2020-08-07 | 2026-08-04 | 六年漂移 |
|---|---|---|---|
| 融资余额（两所） | 1.404 万亿 | 2.584 万亿 | **+84.1%** |
| 沪深300 流通市值 | 33.4 万亿 | 51.8 万亿 | +55.1% |
| 上证综指 流通市值 | 34.2 万亿 | 58.9 万亿 | +72.4% |
| **比率 ÷ 上证综指** | 4.1075% | 4.3855% | **+6.8%** |
| 比率 ÷ 沪深300 | 4.2048% | 4.9920% | +18.7% |

一个六年漂 84% 的量撑不起分位阈值；漂 6.8% 的可以。**上证综指去趋势明显优于沪深300**——它覆盖全部沪市个股，而沪深300 只有 300 只大盘股、其占全市场流通市值的比重本身在变。

**水平不可跨口径比**：上面 4.1–4.4% 的绝对值不能与「全市场两融占流通市值常态 2.0–2.5%、2015 顶 4.7%」直接对照，因为分子是三所全市场余额而分母只是沪市。对分位而言重要的是平稳性，不是水平。

### 决定 2 变形了：不再是预算问题

「补到六年」与已定口径 3「三所全计」直接冲突——`market_margin_totals` 要求每所都覆盖整窗，任何一个北交所不存在的交易日都会让整窗 fail-closed。三选一：**(a)** 交易所必需集随时间生效（北交所自其首个有数据的交易日起才必需）；**(b)** 接受三年窗口（北交所全程存在，无冲突）；**(c)** 从口径去掉北交所（约 0.3%，但与用户已定口径冲突，须明确改口径）。**审查方倾向 (a)**：保住「三所全计」的原意，代价是一条按日期生效的必需集规则加它的反控测试。

### 还能用 2-3 次调用问掉的一件事

分子是三所，分母目前只有沪市。若 `399106.SZ`（深证综指）与 `899050.BJ`（北证50）同样可达，分母就能与分子**同口径**相加。本轮预算 11/12 用尽，未探；这是一次独立的小额授权决定，不阻塞任何东西。

### 边界与产物

- 新增 `runners/a_short_margin_ratio_source_probe.py`（bounded、只读、注入式 client、`--confirm-fetch-authorized` 必填）与 `tests/test_a_short_margin_ratio_source_probe.py`（17 条，含植入对照与一条明写「整档偏差被设计吸收且这是正确的」的负向测试）。writer 已登记进 `PUBLIC_WRITER_FUNCTIONS`。
- raw 落 gitignored `provider_samples/a_short_margin_ratio_source_probe_20260805/`；tracked 摘要 `docs/a_short_margin_ratio_source_probe_summary_20260805.json` 无 token/URL/raw 行。
- **未改任何生产行为**：不碰 EGS/weekly/TopN/M6.7/仓位/序 19 的任何文件；不接消费者；不提议阈值。
- **一处自审纠错**：首版把「分母恰好差 1e4」当成比率交叉校验能抓的情形，实测被 `infer_unit` 的分档设计吸收，那条测试因此不承重。已改用非整档扰动（窄 100 倍）作判据，并补一条负向测试明写该边界是设计使然、不是漏洞。

### 并发事实（不属本轮范围，但下一个动这棵树的人必须知道）

`runners/a_short_weekly_pipeline.py` 在审查方 21:21 的验收包**之后**被另一窗口改过（diff 由 +223 变 +266，新增 schema 编译 `lru_cache` 与 `_validate_against_schema_file`），`tests.test_a_short_public_json_writer_nonfinite_guard` 的 `test_reviewer_named_weekly_and_ledger_writers_reject_nonfinite_without_publishing` 现为 ERROR（`Additional properties are not allowed ('value' was unexpected)`）。该改动不在序 19 审查范围内，B0 未动它。**序 19 的 FAIL verdict 是对 21:21 那个树态下的判断。**

## 2026-08-06 追加：序 19 审查 FAIL 修复（P2 下限门 + 九条 Optional 处置）与 lane 提速刀

> 执行方 = Claude Code；未 commit。finding 正文单一来源 = register 的 `R-ASHORT-SEQ19-EVIDENCE-LEG-SKIPS-THE-MIN-WINDOW-FLOOR`（已 working-tree repaired）、`R-ASHORT-SEQ19-REVIEW-OPTIONAL-BATCH`（六修/二延/一声明闭合）、`R-ASHORT-LANE-SPEED-REGRESSION-CONTENT-KEYED-CACHES`（六处内容键缓存全声明）。本节只记交接事实。

### 改了什么 / 为什么

1. **P2 修复**：`build_evidence` 的分支由 `reconciled["coverage_complete"]` 改判 `facts["coverage_complete"]`（register 点名的第一种最窄改法），窗口短于 600 时点名会话数、空表、`NOT_VERIFIED`；未动 480 训练期门槛。
2. **Optional 六修**：O-1 replay 恒带标记不再抄旧 summary；O-3 raw 捕获路径 `_nonfinite_safe` 后落盘（tracked 仍严格拒）；O-4 预算中止保留日历+专用归因句；O-5 最长连续改 ISO 日历相邻断段、归年改 ISO 年；O-6 输入 schema 补 percentile 0..1 / balance>0；O-7 回声校验兄弟对齐（None=未供给，非数值=ValueError）。O-2/O-8 延后（schema 词表/通电刀），O-9 以 register 单独条目声明闭合。
3. **上一节「并发事实」点名的守卫 ERROR 已修**：schema 校验移进缓存校验器后，守卫测试的中和缝隙跟着从 `jsonschema.validate` 换到 `_validate_against_schema_file`，被测策略（写盘器拒 NaN 且零残留）不变，模块 10 OK。
4. **lane 提速刀（用户令「修复全量测试」）**：六处重复重算改内容键缓存 + 两处循环外提升，明细与植入对照全在 register 速度条目；测试零删减、860 上限未动。

### 验证命令与结果

- 两 margin 模块（含 P2 closure ①② 与 Optional 各测）`Ran 51 tests / OK`；植入对照③实跑转红后逐字节还原。
- 守卫模块 `Ran 10 tests / OK`；12 模块验收 `Ran 848 tests / OK / 469s`；重铸 bundle 收据 `Ran 109 tests / OK`（`receipt:9589391b595cc9642deaaeef`）。
- 产物按修后代码 `--replay-raw` 重生成：分位 `0.8276` 与余额逐位不变；**四档最长连续 53/51/50/32 → 全部 29**（春节周不再被桥接），ISO 年重归 2025:22/2026:31；replay 标记诚实（calls=0）。
- full lane 最新态见 SESSION_LOG 顶条（多次背景运行被会话回收，PASS 记录以 ledger 为准）。

### 失效旧结论

- 「最长连续 53 周」作废——那是跨零交易周的假连续；修正后四档在同一个 **29 连续周**段封顶，对阈值裁决更有区分度（触发计数 53/51/50/45 不变）。
- 「replay 产物与实抓不可区分」不再成立。

### 下一步注意

- B0 比率探针结论已在 register 顶部（分母可达/单位元/六年史与北交所冲突的三选一），阈值与换判据仍是**用户裁决项**；本轮修复不代拍。
- O-2 / O-8 留给通电刀（schema 词表与跨字段校验一起动）。

## 2026-08-06 追加：序 19 P2 收口 + 提速刀批 独立审查 —— FAIL（一条 P2）

### 判定

**FAIL，未提交。** 上一轮那条 P2 修得干净利落；拦住本轮的是**这一批提速刀里的新问题**。

### 序 19 的 P2：已闭合，且我证明了它承重

`build_evidence` 现在判 `facts["coverage_complete"]`（内含 600 交易日下限）而不是 `reconciled["coverage_complete"]`（只有逐所对账、不认识窗口长度），并把两种不可用原因分开点名——短窗口那条会写出实际交易日数与下限值。截断运行的 `status` 也由 `PARTIAL` 改成 `NOT_VERIFIED`，与诚实满覆盖运行（仍是 `PARTIAL`）**终于可区分**。

**我自己的植入对照（决定性）**：把 `MARGIN_OVERHEAT_MIN_WINDOW_SESSIONS` 挖成 0 等于拆掉这道门 —— 同一个 500 交易日窗口立刻由 `NOT_VERIFIED / 0 档 / pct=None` 变回 `PARTIAL / 4 档 / pct=1.0`，**精确复现修复前的缺陷**；还原后与基线逐字段一致。这道门是承重的，不是恰好没触发。

closure ①（500 与 599 双边界）与 ②（725 满窗仍出表）都已落地且断言精确。我上一轮列的 Optional 里，O-1（replay 标记）、O-3（非有限值仍落 raw）、O-4（预算中止报对原因）也都有对应测试名。

### 拦住本轮的：一道被声称存在、实际不存在的守卫

提速刀给 `admissions()` 加了 `_cached_registry`，键是四份 preset 的原始字节；缓存体内 `del authority_key` 后再实读一次那些文件——**「键完整」是唯一让它不返回陈旧注册表的东西**。而模块注释白纸黑字写着「which is why the guard test pins the `_load(ROOT / ...)` call sites to this list」，**那道守卫全仓不存在**（`grep -rn` 除引擎自身零命中）。

今天没有错误产物：我用 AST 取出四个 `_load(ROOT / ...)` 调用点，与声明元组**完全相等**。缺的是防它日后漂掉的门，以及那句会误导下一个实现者的假声称。修法与可直接抄的 AST 谓词见 register 的 `R-ASHORT-ADMISSION-REGISTRY-CACHE-AUTHORITY-TUPLE-IS-UNGUARDED`。

### 七处新缓存：实测都真在省，键也都是完整权威

按「提速刀必验真命中」的规矩实跑 `cache_info()`：`_paths_for_prefixes_cached` 147/65（currsize 65 << 2048）、epoch fingerprint 16/8（currsize 恰 8 份契约）、`_cached_registry` 3/1、`_compiled_schema_validator` 4/2。没有刀 6 那种「maxsize 装不下键导致颠簸」。键分别含完整叶路径元组 / 现读文件正文 / schema 文本 / preset 字节，改源即换键。

`_compiled_schema_validator` 与 `jsonschema.validate` 的等价性我双路验过：类选择与 `check_schema` 逐条对应，同一必拒实例两边同判 `ValidationError`；唯一差异是 `best_match` 与首错的**文案**差别，`test_..._nonfinite_guard` 已相应改 patch 新接缝。

**两处未覆盖**：`_structurally_validated_packet` 与 `_track_modes_from_source` 在我的探针路径上 hits=0/misses=0，即未被触达，命中率 `NOT_VERIFIED`。

**theme_forward 是纯提升不是缓存**，但有一处语义差值得执行方自己确认：`iterrows()` 会把混合 dtype 行向上转型（int 可能变 float），`to_dict(orient="records")` 保留各列 dtype。方向上后者更忠实，但这是行为变化而非纯提速，建议补一条混合 dtype 的等价性断言。

### 验收包的诚实边界

**结论后回写的更正**：15 模块验收超集最终返回 `Ran 869 tests in 677.9s / OK`（`receipt:823fd1e46b61f61117592229`，deadline 900 秒内完成）。我发结论时它还没落盘（bounded runner 缓冲输出，文件当时 0 字节），当时按 rule 6 记了 `UNKNOWN`——**那条记载是错的，已作废**。本轮 FAIL 按 rule 3 由已坐实的探针得出、不依赖该包，包返回后与结论一致。full lane 按 rule 4 引用执行方记账 `PASS 2498/826.4s`，未重跑。教训：678 秒的超集不要在结论前当成「饿死」，`0 字节` 只说明缓冲未刷，不说明进程没进展。

## 2026-08-06 追加：复审 FAIL 的 P2 修复（准入注册表缓存权威守卫落地，并抓到第五个漏网读点）

> 执行方 = Claude Code；未 commit。正文单一来源 = register 的 `R-ASHORT-ADMISSION-REGISTRY-CACHE-AUTHORITY-TUPLE-IS-UNGUARDED`（working-tree repaired）。

### 改了什么 / 为什么

1. 把引擎注释承诺却不存在的守卫真落地：`AdmissionSourcePresetGuardTests` 以 AST 走查 `_load(ROOT / ...)` 调用点，断言相对路径集合恰好等于 `_ADMISSION_SOURCE_PRESETS`；不可解析的 `_load` 形态产生 loud 标记（不隐形）。
2. **守卫首跑抓到第五个真实读点**（审查方内联枚举漏掉的）：`_p4_admission` 经变量间接读 `egs_industry_heat_governance_20260611.json`——修复前改这份 preset 不会让注册表缓存失效。调用点改直连形态，清单补第五份，并做同款权威植入（改字节必 miss、还原命中）。
3. 按缺陷类清单把 `admission_snapshot_sha256`（`:466`）腿也断言到；顺手补上审查方留档条目里的 dtype 语义差 Optional（混合 dtype 行在 dict/Series 两形态下消费者判定一致 + `.0` 后缀由时钟比较吸收，两条测试钉住）。

### 验证命令与结果

- 注册表模块 `Ran 17 tests / OK`（守卫 4 条 + snapshot 腿 1 条全在内）；注册表+治理+dtype 类 `Ran 29 tests / OK`。
- 消费者验收包（注册表+治理+factor_v2+regime_action+industry_weight+final_action+target_policy+theme）结果见 SESSION_LOG 顶条。
- full lane 未重触发：本轮改动 = 测试新增 + 引擎一处注释与一处调用点等价改写 + 清单补一份；生产顶层 runner 未动，既有 `PASS 2498/826.4s` 记录对生产面仍有效。

### 失效旧结论

- 「四个 `_load` 调用点与声明清单完全相等」失效——真实是五个，第五个藏在变量间接后面；这正是守卫要求「不可读形态必须 loud」的原因。

### 下一步注意

- 给注册表加新 `_load` 时必须同步扩清单，守卫会拦；写法必须用直连 `_load(ROOT / ...)` 形态，间接形态会被 loud 标记拦下。

## 2026-08-06 追加：序 19 判据换比率刀（用户裁决 ①换比率 ②选 a）+ 首份实盘同口径阈值证据

> 执行方 = Claude Code；未 commit。正文单一来源 = register 的 `R-ASHORT-SEQ19-RATIO-CRITERION-KNIFE`。同轮处置：③上轮复审 Required 已在前一节修毕；④effect memo 缓存实测为净亏损已回滚（memo 测试本意就测冷构建，缓存帮不到反加键构造税，模块 77s→102s，还原后 63 条绿）。

### 改了什么

1. **引擎**：过热量改为比率（required-exchange `rzye` 合计 ÷ `000001.SH float_mv`）；交易所集按日期生效（BSE 自数据自证的首日 `20230213` 起必需，反作弊三腿）；证据函数升实盘同口径（每周完整滚动 3 年窗、与实盘门同一 600 下限）；新增 `margin_ratio_series` / `required_exchanges` / `_bse_effective_from`。
2. **对账缝修复**：分母当日发布 vs margin 滞后一日 → 两腿对账前按请求集筛行（窗内缺/重/NaN 仍拒），否则实盘每天必 fail-closed。
3. **生产者**：EGS 加分母腿取数（每周 +3 次 `index_dailybasic`），emit `ratio` + `denominator_float_mv_yuan` 两新叶。
4. **消费者**：weekly 控制回声新增比率恒等式（`ratio×denominator==balance`，容差 1e-6 相对），万元滑移当场拒。
5. **schema**：analysis_input 两新叶带界；weekly 控制块两新字段；证据 schema 升 2.0.0（比率/分母/BSE 生效日/预算 12/绑定规则）。
6. **契约**：重封（两新叶 `m67_main_decision` 带三件套 override）。
7. **真实取数**：11/12 调用，6 年窗 1454/1454 全齐，产出比率基准阈值证据。

### 验证结果

margin 两模块 56 绿；验收包 682 绿（`receipt:c1de5807ed0db575bfec092e`）；full lane 见 SESSION_LOG 顶条。**关键数字**：当前比率 4.357%、比率分位 0.912、BSE 生效日 20230213；181 个实盘同口径可评周——p80 54(30%)/连25、p85 52/25、p90 48(27%)/24、p95 40(22%)/18。

### 失效旧结论

- 「水平分位无区分度（p90 恒触发 94%）」的裁决困境**已解**：比率判据触发率 22-30%、最长段约半年，表可用了。
- 上一份水平基准证据产物（p80-95=53/51/50/45、longest 29）被比率基准 2.0.0 产物整体取代。
- 「六年史与三所全计冲突」已由日期生效集消解；BSE 数据起点是 20230213 而非开市日。

### 下一步注意

- 阈值+现金系数+通电三件仍等用户按新表一次裁定；O-2/O-8 仍留通电刀。
- 顶层两个 session 计数口径差（全窗 1454 vs 实盘窗 726）已在 register 声明，复审可裁改名。

## 2026-08-06 追加：比率刀 + 准入守卫 + 提速刀批 独立审查 —— Pass-with-Required

### 判定

**Pass-with-Required，未提交。** 代码侧我认可，全部独立验过；唯一挡住 clean PASS 的是全量在 860 秒硬上限处越线——**基础设施天花板，不是本刀的缺陷**，但按 closeout gate 无全量绿记录不能给干净 PASS。

### 比率刀：三条核心声称我逐条独立验证，全部属实

1. **`20230213` 全仓未写死**（`grep` engine/runners/A-EGS/schemas 零命中）。北交所首个有 margin 数据的交易日确实由取数自证——它比北交所开市日晚一年余，写死开市日常量就会错。
2. **`BSE_MARGIN_EXPECTED_BY="20260101"` 是冻结常量**（`:88` 定义、`:244` 消费）做反截断，权威链终点合格。
3. **证据窗已改用与实盘门同一个 600 常量**，旧的 480 已不存在。我最早提的「证据用扩张窗口、实盘门用定长滚动三年，两个估计量不同」这条**根治了**。

### 我自己的植入对照 9/9

比率恒等式承重：万元分母（1e4 偏小）被当场拒、`ratio×2` 的自相矛盾同拒。日期生效必需集三腿：首日前两所窗口正常对账（1400/1400）、首日后缺一天 fail-closed、整窗零 BSE 且触及冻结日判截断。证据口径两腿：默认常量 == 实盘常量、退役常量确已移除。

### 产物独立复算：自洽，且换量确实奏效

恒等式 `|ratio×denominator − balance| / balance = 0.0` 精确；实盘窗 `20230807..20260805` `726/726 complete` 与证据窗 `20200806..20260805` 1454 会话**已分开报**——执行方自查出的那个「六年跨度配 726/1454 还写 complete」的自相矛盾确实修好了；`181+127=308` 对得上。

**决定性对比**：周分位**中位数 0.4966**（最小 0.0014、最大 1.0000）。旧的水平分位是最小 0.8216、中位 0.9861、p80 触发 100%。一个跨 [0,1] 铺开的分布，正是平稳量该有的样子。

### 给用户裁阈值时要知道的一条（不是缺陷）

四档触发率 p80 29.8% / p85 28.7% / p90 26.5% / p95 22.1%，**彼此只差 7.7 个百分点**；触发周几乎全落在 2025-2026（p90 `{2025:18, 2026:30}`），最长连续 24 周约半年。即：换比率之后判据**有了真实区分度**（相对旧口径的 94%），但它是个**区间指标不是事件触发器**——四档之间仍不太分得开。若目标是「一年响 2-5 周」，这四档都到不了，得往 p98 以上找。刀本身不该发明阈值，这条只是把裁决所需的事实摆清楚。

### 上一轮 Required 的闭合情况：比我要求的更严

`AdmissionSourcePresetGuardTests` 四条——AST 谓词、我点名的植入对照、**不可读 `_load` 形态 loud 报错**（我没要求的硬化）、以及我特别强调的 `admission_snapshot_sha256` `:466` 腿。假声称的注释改成点名具体测试类。**声明清单由 4 份补到 5 份**：证实我审查时那份手写枚举确实已经漏了一个读点，不是理论风险。dtype Optional 也补了 `MixedDtypeRowEquivalenceTests`，其中一条主动断言差异真实存在再证消费面剥后缀，比我要的更诚实。

### 唯一未闭：全量天花板

`R-ASHORT-FULL-PACK-NOW-EXCEEDS-ITS-OWN-CEILING`。rule 3 已触发（生产顶层 runner + 共享 engine + provider），rule 4 要一次全量，而它在 860 秒处 TIMEOUT。两条路都要你裁：**(a)** 批准上调上限（如 1000s）后执行方重跑取绿；**(b)** 批准并行 runner 刀（方案见 `docs/handoff/2026-07-28_repair_closeout_shared_flow_handoff.md`）。裁完取得全量绿，我复核后提交并合入 master。

### 本轮验证

验收超集 `Ran 875 tests in 685.1s / OK`、`receipt:dd83d6ae0844b864e2e6b65a`。**本轮无 review-gate token**（命令未触发 hook），证据全部为工具实跑回显，已在 SESSION_LOG 如实写 `review-evidence:not_available`。

## 2026-08-06 追加：下一步两把小刀 —— 触发周成绩对账（①）+ 变化率族并列发布（②）

> **状态：待做，用户 2026-08-06 指定为下一个事项。** 前置：序 19 当前批（比率刀 + 准入守卫 + 提速刀）取得全量绿并合入 master 之后再开工——两把都要读比率刀的产物，不要跟未提交的树抢。

### 为什么现在要打这两把

审查复算出的事实：四档触发率 p80 29.8% / p85 28.7% / p90 26.5% / p95 22.1%，**彼此只差 7.7 个百分点**；触发周几乎全落 2025-2026（p90 `{2025:18, 2026:30}`，2023/2024 **一次未触发**），最长连续 24 周约半年。

两个后果：

1. **四档之间分不开，裁阈值缺依据。** 触发周不是散布在 80-95 之间，而是扎堆挤在最顶上，所以画哪条线都是「约四分之一的周」。更要命的是——**我们只知道门会在哪些周亮，完全不知道那些周是不是真的更差。** 频率有了，结果证据一个字都没有。
2. **信号性质与消费点错配。** 这道门接 `_allocate_cash`、压的是**每周新建仓现金**，而系统持股 5-15 天，这是个**战术**杠杆；而「水平分位连亮 24 周」是个**战略/区间**信号。照现有四档通电，等于在 2025-2026 的上行段里连续半年把新建仓砍到七折——代价确定、收益未验证。

### 刀 ①：触发周 × 实际表现对账（★★☆☆☆，纯离线，无新取数）

**目标**：回答「门亮的那些周，是不是真的更该少建仓」。产出一份对账表，让用户拿证据裁阈值，而不是拍脑袋。

**第 0 步必须先做（不做完不要写计算代码）**：确认**哪份产物能提供逐周实际表现，且覆盖够不够到 2025-2026**。已知风险：`forward_daily` 缓存长期不刷（曾停在 `20260227`，见 memory 提醒），comparison-only 轨的账本也不随实盘推进。**若覆盖够不到触发密集的 2025-2026，本刀的结论就是「现有证据无法评估该门」——那本身就是给用户的有效答案，如实产出即可，不得用残缺样本硬算。**

**口径（关键，别用错）**：
- 被评的对象是**该周新建仓的那批票的前向表现**（这道门只压新建仓、从不动已有持仓），**不是**组合整体的周 NAV 变化——后者混进了门根本碰不到的存量持仓，会把结论稀释成噪音。
- 触发标记直接取自 `research/results/a_short/margin_overheat_percentile_threshold_evidence.json` 的 `threshold_evidence.weeks[]`（每周带 `week_end` / `percentile` / `verdict`），四档各自的触发集由该周 percentile 与候选阈值比较得出，**不要重算分位**。
- 至少给出：触发周 vs 未触发周的**胜率、平均/中位前向收益、最大回撤、样本数**；四档各算一遍；并按 ISO 年切一刀（因为触发全在 2025-2026，全样本平均会被区间效应主导）。

**防 p-hacking（本项目自己的规矩，务必遵守）**：四档 × 多个结果指标 × 多种切法 = 多重检验。**开工前先在 register 写死「哪一个比较决定结论」**（建议：p90、新建仓周前向收益中位数、按年分层），其余全部标为探索性。**绝不允许看完结果再改口径或改阈值**（AGENTS item 13）。样本量小（181 周里触发 40-54 周，且集中在一年半内）时必须如实标注统计功效不足，不得用「看起来更差」下结论。

**边界**：不新取数、不接消费者、不提议阈值、不动开关；产物落 `research/results/a_short/`，comparison-only。

### 刀 ②：变化率族并列发布（★☆☆☆☆，同一条序列换统计量）

**目标**：给用户第二张表做对照——**事件型**信号长什么样。

**做什么**：复用比率刀已抓好的 6 年比率序列（`20200806..20260805`，1454 会话，已在 gitignored raw 与产物里），**不发任何新请求**，只多算几个统计量并列发布：
- 比率的 **4 周变化**（战术尺度）
- 比率的 **13 周变化**（季度尺度）
- 比率相对**自身 52 周均值的偏离度**

对每一族照样出「候选分位 × 触发周数 / 最长连续 / 年度分布」，与现有水平分位那张表**并排放同一份产物**，字段上标清是哪一族。预期形态与水平分位截然不同：短促、一年响几次、最长连续短——那才对得上短线战术消费点。

**必须沿用的既有纪律**（不要另起一套）：逐所 exact-date 对账、日期生效必需集、≥600 会话下限与实盘门同常量、比率恒等式。任何一族算不出来时该族 `unavailable`，不得补零。

**边界**：不新取数、不接消费者、**不提议任何阈值**、不动开关与治理常量；schema 版本按加字段升 minor。

### 两把刀的关系与顺序

**② 先做也行、并行也行**（它便宜且不依赖 ①），但 **① 是裁阈值的必要条件**。理想顺序：② 产出第二张表 → ① 对两族分别做同一套对账 → 用户拿着「两族 × 各自触发集 × 实际表现」一次裁定用哪一族、哪个阈值、什么系数。

**在 ① 出结果之前，不得给融资过热门通电**——否则就是用确定的成本换未验证的保护。

## 2026-08-07 追加：执行序 11 —— #09 反悬空守卫粒度 group→leaf（增量棘轮版）

**改了什么**

1. 契约 `schemas/a_short_m67_effect_contract.json` 新增顶层键 `unclassified_pending_audit_baseline`：执行时树上 225 条 pending 路径的排序快照（纯机械、零举证）。
2. `engine/a_short_effect_contract.py::_leaf_effect_map` 的兜底分支不再开放——判 pending 的叶不在基线内即 `raise` 并点名叶路径，要求登记 `leaf_effect_overrides`（沿用既有四键，未建 9 字段证据分类学）。
3. `static_contract_error()` 加两条基线卫生：棘轮腿（基线每条必须当前仍真判 pending，接线/删除/翻 constant_null 后留在名单里即报 `may only shrink`）+ 排序去重检查（让「只减」在 diff 里可审）。防换血腿在 `tests/test_a_short_effect_contract.py::_PENDING_AUDIT_LANDING_SNAPSHOT`，断言活基线 ⊆ 落地日冻结快照。
4. `engine/a_short_evidence_epoch_mode.py::_EFFECT_CONTRACT_LEAF_LEDGER_KEYS` 六键 → 七键，新键入排除清单并同步其证明测试。
5. `docs/a_short_m67_effect_contract.md` 新增「未判定余量」一节并把「以后改字段/规则时」的步骤 1 补上新叶闸；顺带把该文档写死的旧叶数改成「由 schema 动态计算」（序 19 加叶后它已过期）。

**为什么改**

组级 nature 会把单个判断批量扩到整组，而逐叶 `leaf_effect_overrides` 虽已存在却不是闸门；于是新增或改造一个字段不会被强制问「悬不悬空」，只会让 pending 计数静默 +1。那个计数是后面每一把接线刀的工作清单与验收分母，能被无声加长就等于没有分母。2026-08-05 用户裁定不做全量补审：存量冻结、只减不增，新债在引入当场被问一次。

**验证命令与结果**

- focused 验收包（6 模块一次合并）：`.toolsun_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.test_a_short_effect_contract tests.test_a_short_effect_consumer_probe tests.test_a_short_evidence_epoch_mode tests.test_a_short_weekly_pipeline tests.test_a_short_regime_action_comparison tests.test_a_short_final_action_validation` → `Ran 677 tests in 457.6s ... OK`，`receipt:9daf87eb2e0c10a6ad85d19c`，`bundles=a_short_effect_contract`。300s 默认不够（实测跑到约 380 条被截断），按 AGENTS rule 5 抬到 900s。
- full lane（rule 3(b)：共享 effect 引擎 + 契约 JSON 喂生产周报管道，只跑一次）：`RESULT status=PASS exit=0 tests=2521 elapsed=235.6s deadline=860s mode=parallel`，`COUNT_GATE discovered=2521 ran=2521 equal=True`。2510 + 本刀 11 条新测试 = 2521。
- 行为不变逐字节正控：同一进程内用 `git show HEAD:` 的引擎源码对同一份磁盘输入重算，`leaf_effects()` 与 `leaf_natures()` 均与改造后逐字节相同；各类计数不变，合计 398。
- 三个植入对照（中和的都是门本身，非判据来源）：挖掉新叶闸的 `raise` → 两条新叶测试转红；棘轮腿恒空 → 三条 `..._may_not_stay_on_the_baseline` 全红；往活基线追加一条新债 → 防换血腿转红。探针改真文件、跑合规入口、事后按字节还原。
- 静态门：`py_compile` 4 文件通过，`git diff --check` 干净，契约 JSON 解析通过、无 BOM、无 mojibake，`static_contract_error()` 返回 `None`（`decision_predicate_sha256` 只有 `engine/a_short_effect_contract.py` 一键变动并已重封）。

**失效旧结论**

- **本文件 §「① 序 11（#09）的范围」两段（约 1714-1715 行）已 SUPERSEDED，勿再照它执行**。那版方案要求「把 `leaf_effect_overrides` 升为覆盖全部 leaves 的唯一闸门、删除 `leaf_nature_by_group` 的放行权、收口后不允许 `unclassified_pending_audit` 留在正式 contract」——那是全量补审版。2026-08-05 用户裁定改走增量棘轮版：`leaf_nature_by_group` **原样保留**（新叶闸生效后它对新叶已无放行力，对存量只是描述），`unclassified_pending_audit` **允许**继续留在契约里、以冻结基线的形式存在，**无清零期限**。
- 桌面 `a_testrun.md` 顺位 3 那节的执行方案已实现完毕，状态位待 merge 后回写。

**下一步注意事项**

- 本刀**不判定**存量 225 条里谁是真悬空。收缩只会由序 13（删叶）、序 14/15（接线）自然发生；每次收缩必须同时从基线数组删除对应条目，否则棘轮腿报红。
- `market_regime` 那几条叶是机械 `producer_constant_null` 或已在基线名单里，序 16 推后**不需要**为它们做任何登记。
- 解冻那一刀必须注意：`engine/a_short_regime_action_comparison.py:93` 与 `runners/a_short_final_action_validation_runner.py:119` 把**整份契约 JSON**摊进各自的对比轨指纹，叶账本（含本刀新键）都在里面。今天两条轨都 `pre_freeze_audit_only`、指纹走常量，不作废任何证据；解冻前必须把叶账本键从这两处也排除，否则每次基线收缩都会白白作废对比轨证据。详见 register `R-ASHORT-ANTI-DANGLING-GUARD-IS-GROUP-GRAINED-SO-A-NEW-FIELD-IS-NEVER-ASKED`。

## 2026-08-07 追加：序 11 独立审查 —— PASS（新叶闸 + 冻结基线棘轮）

### 判定

**PASS，已提交并合入 master。** 这刀干的事很小也很对：把 `_leaf_effect_map` 那个「谁都没接住就静默落 pending」的开放兜底，关成一张 225 条的闭合名单。不判定存量谁是真悬空、不建 9 字段分类学、不动 `leaf_nature_by_group`——都与 2026-08-05 用户裁定一致。

### 我实际验了什么（不是转述）

- **行为不变**：现算 398 叶的七类计数与执行方所报逐项相同；冻结基线 **225 == 今日 pending 225**，双向差集皆空；`static_contract_error()` 返回 `None`，这同时证明 `decision_predicate_sha256` 的重封与现算 inventory 精确相等（引擎比的是整份预判据字典，不是文件字节——我一开始拿文件 sha256 去对，那是错的尺子）。
- **防换血锚**：`_PENDING_AUDIT_LANDING_SNAPSHOT` 实测 225 条、去重后仍 225，与活基线双向差集皆空，且在另一份文件里——契约编辑不会带着它一起漂。
- **epoch**：整读 `contract_semantic_projection` 的 `_PROJECTION_EFFECT_CONTRACT` 分支，新键确在 `_EFFECT_CONTRACT_LEAF_LEDGER_KEYS` 排除集内，基线收缩不动语义指纹。

### 植入对照（2/2，中和的都是门本身）

① 从源码副本中挖掉兜底分支的 `raise` → 同一条新叶由 raise 变成静默 `unclassified_pending_audit`；② 挖掉 `static_contract_error` 的 `stale_baseline` 整段 → 「已判 `true_dangling` 却仍留名单」的 `may only shrink` 报错消失。两处都等价于「删掉这道门」，不是 patch 判据来源。

### 一条 Optional（不阻塞）

棘轮只做了 `baseline ⊆ pending` 一个方向。给一条**不在基线**的叶显式登记 `{"category": "unclassified_pending_audit"}` 就能绕开新叶闸（override 优先级最高、不走兜底分支）：实测 `universe_summary.after_l0_count` 如此登记后 pending 226 / 基线 225，`static_contract_error()` 仍返回 `None`。测试层的双向相等断言会红，所以今天没有损害；但按 checklist §A.5，自足校验器本身该钉住。加固是一行。正文见 register 同一条目。

### 未覆盖维度与诚实边界

执行方焦点包 6 模块 677 条，我按 rule ⑤ 只重跑覆盖改动符号的 3 模块 118 条，另 3 个消费者模块未由我复跑；全量按 rule 4 引用执行方记账（指纹已核为当前代码态 `d570ae90…`）未重跑；register 里那条「两条对比轨把整份契约摊进指纹」的既有观察我未独立复验。

### 下一步

序 11 收口。队列上仍未开工的是序 7（#02 汇总/账本事务性）、序 8（#10 `price_as_of` 双口径）、序 13/14/15，以及本文件文末那两把小刀（①触发周成绩对账 ②变化率族）——后者是用户 2026-08-06 指定的下一个事项，前置（序 19 批合入 master）已满足。
