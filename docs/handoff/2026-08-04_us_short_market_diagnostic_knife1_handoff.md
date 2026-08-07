# US-short 26 周市场诊断轨 Knife1/Knife2 handoff

## 范围

Knife1 是不读账户、不联网、不调用 provider 的纯计算层。Knife2 在其上增加本地只读适配：校验既有 model-paper store 和本地四基准价格包，再投影为 schema-shaped 逐周记录；两刀都不改变选股、操作建议、sizing、model-paper NAV 或 Ship gate。

本轮已继续落地 Knife3 生命周期读取之后的 Knife4 聚合器：它只在第 26、52、78 等 canonical 边界生成当前 26 周固定区块 + since-inception 双视图，输出确定性的去标识化 JSON/Markdown；当前真实 model-paper 私有根尚未启动，所以没有真实成绩单或真实 10 万美元账户状态被创建。

## 已固化的计算契约

- 策略周收益由 prior NAV/NAV 构造；首周使用 `100000.000000`，`no_count` 周不补零。
- 复利、相对财富、raw excess、最大回撤、Information Ratio 和 Newey-West HAC t 已实现；HAC 的描述性 lag 为 `min(4, n - 1)`。
- 四个基准固定为 VTI/IWB/SPY/QQQ；少于 20 个 joint 周不能给 ahead/behind，price-only 或不可用数据保持降级状态。
- 26 周区块互不重叠；窗口触发是纯函数且按 `window_id` 幂等；epoch 不得静默混入，ruleset 按连续段输出。
- 计算摘要入口与触发入口共用 `window_for_week(end_week)` 的 canonical 锚点；第 5—30 周这类非边界窗口在计算路径也 fail-closed。
- 窗口身份、起止周和 `calendar_weeks` 统一由 `window_containing_week()` 产生；`window_for_week`、单周校验和 lifecycle register 不得各自重写窗口算术。
- 缺失换手率或未成交数输出 `null`；不以 0 代替缺失数据。
- 刀2 读取 `head_manifest.json`、指定结算周的 `settlement.json`、`portfolio_state.json`、`nav_snapshot.json`，并重新核对 settlement/state/NAV digest 绑定；不写 store、不推进 head。
- 刀2 的本地价格包固定 VTI/IWB/SPY/QQQ；SPY/QQQ 可来自 `grouped_market_window`，IWB/VTI 来自 `local_etf_price_packet`；每周保留 price date/source/SHA。
- 刀2 只输出 `price_return_diagnostic`；股息 sidecar 不在本刀消费，缺价格或缺前值输出 `unavailable`，不填零、不换基准。

## 代码和验证入口

- 计算器：`engine/us_short_market_diagnostic.py`
- 本地适配器：`engine/us_short_market_diagnostic_local_adapter.py`
- 合成 fixture / 反向测试 / schema 校验：`tests/test_us_short_market_diagnostic.py`
- 刀2 adapter / 私有 store digest / 本地价格包测试：`tests/test_us_short_market_diagnostic_local_adapter.py`
- 记录 schema：`schemas/us_short_market_diagnostic_weekly_record.schema.json`
- 摘要 schema：`schemas/us_short_market_diagnostic_summary.schema.json`
- 刀2 输入 schema：`schemas/us_short_market_diagnostic_local_price_packet.schema.json`
- 刀3 lifecycle persister：`engine/us_short_market_diagnostic_lifecycle.py`
- 刀3 lifecycle register schema：`schemas/us_short_market_diagnostic_lifecycle_register.schema.json`
- 刀3 计数、幂等、提醒和私有路径反向测试：`tests/test_us_short_market_diagnostic_lifecycle.py`
- 刀4 26 周聚合与发布：`engine/us_short_market_diagnostic_aggregator.py`
- 刀4 报告 schema：`schemas/us_short_market_diagnostic_report.schema.json`
- 刀4 聚合、幂等、半成品保护和 lifecycle 发布测试：`tests/test_us_short_market_diagnostic_aggregator.py`
- 设计入口：`docs/us_short_market_diagnostic_26w_design.md`

## 后续边界

刀3 已接周记录、26 周计数器和 v1.1 reminder 生命周期；Knife4 已在其上增加只读聚合与公开报告发布。聚合器只接受 lifecycle 已校验的 settled 记录；同一 `window_id` 重跑字节级幂等，JSON/Markdown 缺一不可，冲突或半成品拒绝覆盖。Knife5 已补上四 ETF total-return sidecar 的离线 schema、纯复算器和本地适配接线；Knife6 已补上 v1.1 归因的离线契约与纯计算器，真实 provider 获取和真实归因数据仍需单独授权；当前真实 model-paper 根尚未启动，因此不会出现真实 26 周成绩单。

## Knife5 新增实现入口

- sidecar schema：`schemas/us_short_market_diagnostic_etf_total_return_sidecar.schema.json`
- sidecar 纯校验/复算：`engine/us_short_market_diagnostic_total_return.py`
- 本地周记录接线：`engine/us_short_market_diagnostic_local_adapter.py`
- sidecar 回归：`tests/test_us_short_market_diagnostic_total_return.py`
- adapter 接线回归：`tests/test_us_short_market_diagnostic_local_adapter.py`

Knife5 只消费已捕获的 source-bound sidecar：完整覆盖周升级为 `total_return_evaluable`，缺失或错配只降级对应 ETF 周为 `price_return_diagnostic`，不补零、不改变策略收益、NAV、选股或操作建议。当前实现没有 provider/network/raw/account 写入。

补充状态：`_overall_status` 的全 `flat_diagnostic` 分支已经随当前 Knife5 提交落地；它保持 overall 六值契约，使用 `mixed_across_benchmarks` 加明确的 `all_four_benchmarks_show_flat_diagnostic_excess` 理由。风险登记中更早的“未修”文字属于历史记录，不是当前代码状态。

## Knife6 新增实现入口

- attribution input schema：`schemas/us_short_market_diagnostic_attribution_input.schema.json`
- attribution report schema：`schemas/us_short_market_diagnostic_attribution_report.schema.json`
- 纯校验/归因计算器：`engine/us_short_market_diagnostic_attribution.py`
- 刀6回归：`tests/test_us_short_market_diagnostic_attribution.py`
- schema 闭世界入口：`tests/schema/test_us_short_market_diagnostic_26w_schemas.py`

Knife6 是独立的 v1.1 解释层：它消费已绑定的 weekly record、Knife5 VTI total-return 观测、PIT 3M T-bill 观测和规则隐含目标暴露，计算 `g*`、匹配基准、`raw_excess`、`exposure_effect` 与 `active_system_effect`。当前修复让报告携带四个目标暴露约束并由 validator 重算 `g*` / binding constraints；input、report 与 builder 全接 `as_of_date`；巨整数、缺 PIT 日期、错误 map 和兄弟异常统一为 `AttributionError`。任一周缺少必要输入时，报告保持 `unavailable`，不补零、不用固定现金利率、不做不可复现历史回填。当前实现没有 provider/network/raw/account 写入，也不修改 v1 weekly/report、选股、操作建议、NAV 或 Ship gate；真实 model-paper、ETF sidecar 与 PIT 现金数据尚未启动。

Knife3 lifecycle 同步改为机器自动激活 v1.1：启用前按连续 `paper_evaluable=true` 周计数，false/no_count/missing 清零；第 4 个连续真周结算后生成确定的 `attribution_epoch` 并标记 active，从下一周生效；激活后状态保持 active。正式 weekly task 自动调用 Knife6、以及 Codex 完成通知 + `diagnostic_start_receipt` 的首周硬门留给 Knife7；当前设计工作基线不构成完成通知，26 周时钟未由本轮启动。

## 2026-08-07 追加：刀 10c —— 诊断轨的报告行接进周报已注册的 §12 生命周期提醒区块

**改了什么**：`engine/us_short_market_diagnostic_weekly_task.py` 新增 `splice_diagnostic_report_lines(report_path, lines)` 与 `WeeklyReportSpliceError`；`runners/us_short_weekly_capstone.py` 的三个 `market_diagnostic*` stage 改单出口、统一经新的 `_deliver_diagnostic_report_lines` 交付报告行，并补齐两个推进 stage 此前一律静默的 5 个失败/停滞态各一行固定串。

**为什么改**：`weekly_diagnostic_step` 四态都算出 `report_lines`，而全仓读取方为零（三个 stage 排在 `weekly_bridge` 之后，报告已渲染完，此后无人再碰）。结果是钟一旦开起来，设计 §5.2 要求的「v1.1 归因：等待自动启用；当前连续 paper_evaluable=true 周=X/4」与 §13 要求的「经已注册 reminder 区块暴露累计状态」都只到内存为止。完整机制与缺陷类枚举见 `docs/system_risk_register.md` 的 `R-USSHORT-26W-DIAG-REPORT-LINES-HAVE-NO-CONSUMER`（单一来源）。

**落点为什么是 §12 而不是新开一节**：设计 §1.3 明令只有「已注册到 §13 生命周期提醒路径中的诊断 reminder 区块」可以变，禁止新增未注册的自由文本 banner。`build_weekly_report_reminder` 自身发布 `registry_key=us_short_market_diagnostic_v1_1` 与 `section_number=12`，落点由注册给出；splicer 读的就是 `REPORT_REMINDER_SECTION`，找不到或找到多个该节标题即 fail-closed，不换地方写。

**两条硬约束怎么保证的**：①钟 `not_started` 时全链无行可交，交付器与 splicer 各有一道「无行即返回」的门，**根本不打开 `weekly_report.md`**，字节一致由「不碰」保证而非「重写成一样」；②诊断侧任何异常（报告缺失、节标题损坏、splice 失败）只记 `report_lines_delivered=False` + `report_lines_problem`，绝不 raise 进周任务。

**刻意不做的事**：`broken` 与 fetch 侧的 `waiting_*` 不各自发行——`broken` 由永远最后运行的读取 stage 带原因报出，fetch 与 settle 从同两个 store 推导同一周（抓取在等就是结算在等），重复三遍只会训练读者跳读。新增行**全部是固定串**：`problem` 带绝对路径、现金腿的 HTTPError 消息可能回显含 `FRED_API_KEY` 的 URL，理由留在运行摘要与 checkpoint。stage 仍 `outputs=[]`：它标注 bridge 已产出的报告、不产出自己的制品，声明为 output 会要求「本周必须变更」，那恰好会打死休眠周。

**自审在离线全绿之后抓到的第三条腿**：`run_weekly_capstone` 只给 `weekly_bridge` 与 `model_paper_weekly` 注入 `official_output_root=transaction.staging_root`，三个诊断 stage 拿到的仍是 `None` → 落到已发布位置，而实跑时 `weekly_private/<decision_date>/` 在终局 publish 之前必须是空的，于是每周都会 `report_lines_delivered=False`——而所有离线测试（没有 transaction）照样全绿。已抽成模块常量 `_OFFICIAL_ARTIFACT_STAGES` 并纳入三个诊断 stage，守卫按 `default_pipeline()` 量词化（所有 `market_diagnostic*` 必须在该集合内）。

**验证命令与结果**：`.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.test_us_short_market_diagnostic_weekly_producer tests.test_us_short_market_diagnostic_authorization_conformance tests.test_us_short_market_diagnostic_weekly_advance tests.provider.test_us_short_weekly_capstone tests.provider.test_us_short_weekly_capstone_soft_discovery tests.test_us_short_capstone_checkpoint tests.test_us_short_model_paper_capstone_wiring tests.test_us_short_discovery_conformance tests.test_us_short_test_io_inventory tests.test_us_short_weekly_report_renderer tests.test_us_short_weekend_private_write tests.test_us_short_weekend_report` → `Ran 412 tests in 77.5s PASS`（13 模块，含 capstone 离线 e2e）；自打 18 个植入 18 红（控制组先全绿）；全量按 rule 3a 触发（改动含生产顶层 runner），**实际载体是 `parallel_lane_runner us_short workers=1`** → `RESULT status=PASS tests=5559 elapsed=766.8s`、计数门 `discovered=5559 ran=5559 equal=True`（终稿 diff 另有并发全量 `PASS 5561/5561 803.9s`）。**没有走 `full_pack_ledger run`**：当时它的并发载体撞上残留守卫竞态（根因见 register `R-USSHORT-A-TEST-WRITES-THE-REAL-LIFECYCLE-REGISTER-AND-A-CONCURRENT-GUARD-SEES-IT`，已修），所以 `.tools/state/full_pack_ledger.json` 对该代码态只有 `_prepares`、没有 PASS 记录——别照旧措辞去查 ledger。

**失效的旧结论**：register 在刀 7b 那轮记的两处 docstring 漂移（「休眠时不贡献报告行」暗示运行时会贡献、「host 可无条件拼接」而无拼接方）自本刀起不再是漂移——拼接方已存在，且休眠周确实一行不贡献。

**新增实现入口**：
- 报告行拼接器：`engine/us_short_market_diagnostic_weekly_task.py::splice_diagnostic_report_lines`
- capstone 交付点：`runners/us_short_weekly_capstone.py::_deliver_diagnostic_report_lines`
- 回归与植入对照：`tests/test_us_short_market_diagnostic_weekly_producer.py::WeeklyHostStageTest` / `::DiagnosticReportSpliceTest`
- 授权论域豁免：`tests/test_us_short_market_diagnostic_authorization_conformance.py::EXEMPT`

**下一步注意**：本刀只接线，不开钟。当前仍无 receipt、无真实第 1 周，`weekly_report.md` 与今天字节一致。

## 2026-08-07 追加：Knife10c 独立审查 verdict = PASS

**审了什么**：`engine/us_short_market_diagnostic_weekly_task.py::splice_diagnostic_report_lines`、`runners/us_short_weekly_capstone.py::_deliver_diagnostic_report_lines` 与三个 `market_diagnostic*` stage 的完整函数体（非只读 diff），外加 `_official_output_paths`、`Stage` 策略默认与 `_publish_current_output_transaction` 事务语义；并对照设计逐条核 §1.3（只动已注册区块、无自由文本 banner、诊断异常不得 abort 周任务）、§5.2（X/4 提醒逐周露出）、§13（经注册区块暴露累计状态）。

**为什么判过**：承重假设独立成立——`engine/us_short_weekly_report_renderer.py` 对 13 个冻结节缺一即拒渲染，所以 `## 12. ` 在真实周报上恒存在，拼接不是只对夹具成立。两处「放松」判为正确而非疏忽：stage 保持 `outputs=[]`（声明为 output 会要求本周必变，正好打死休眠周）；`splice_diagnostic_report_lines` 进授权豁免仅一函数、与既有 `_read_json` 同类同形且写明理由，不是关开关。

**验证命令与结果**：审查方自跑焦点超集 `.tools\run_unittest_with_repo_pythonpath.cmd` 12 模块 → `Ran 253 in 106.0s PASS receipt:d57ba0bd7c83bfc3b10d778d`；capstone 消费方 2 模块 → `Ran 89 in 23.5s PASS receipt:fe404aabd63ffaf6a784bab2`。审查方自写 7 个植入 **7 红**、控制组先全绿、还原后 `git status` 零残留（`python -B` + `PYTHONDONTWRITEBYTECODE=1`）：staging-root 名单漏一个 stage、休眠态打开文件、交付失败 raise 进周任务、两个 §12 标题被接受、贴着下一标题插入、`capture_failed` 不发行、新类守卫被绕过。全量按 rule 4 引用执行方记录，未重跑。

**失效的旧结论**：无。

**留给下一轮的一条 Optional**：本文件上一节称全量「经 `full_pack_ledger.py run` 记账」，而 ledger 对该代码状态只有 `_prepares`、无 PASS 记录，真实载体是 `parallel_lane_runner`；详情与两种修法只在 `docs/system_risk_register.md` 的 `R-USSHORT-26W-DIAG-REPORT-LINES-HAVE-NO-CONSUMER` 条目内。

**该 Optional 已闭（2026-08-07 执行方）**：取审查方给的第一种修法——把上一节那句改成实际载体，并写明为什么没走 ledger；没取第二种（补跑一次 `full_pack_ledger run`）的理由记在 register 同一条内。

**该收尾轮审查 verdict = PASS（2026-08-07 审查方）**：整读三处文档改动全文，纯文档故按 rule 8 快档（不起 agent、不跑全量）。改法与不取第二种修法的理由均认可；执行方多做的一步——补上 register `Closure` 里此前缺的全量证据——正是单一来源该有的样子。验收 `tests.test_doc_governance_guard` + `tests.test_route_doc_ledger_status_consistency` → `Ran 55 in 1.7s PASS receipt:bddd2d84688b3fbf02b43b5c`；类声明独立复核：全仓 durable doc 里声称承载本刀全量证据的确实只有被改那一句。本轮另记一条与本刀无关的 Optional（评审循环守卫按 header 动词分类，收尾式 header 会整条跳过），正文只在 `docs/system_risk_register.md::R-DOCGOV-A-REPAIR-ROUND-ESCAPES-THE-TEMPLATE-GUARD-BY-NOT-SAYING-修复`。
