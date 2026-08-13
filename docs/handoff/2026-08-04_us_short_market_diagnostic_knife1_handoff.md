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

## 2026-08-07 追加：接缝审计 verdict = 六处接缝全部成立（一条环境耦合测试红另挂 Required）

**审的问题只有一个**：状态从上一刀流到下一刀有没有断——本轨一周内三次自我发现的缺陷全是「每刀单测绿、接起来是死的」这一类。

**逐缝证据**：①receipt→store：`runners/us_short_market_diagnostic_weekly_fetch.py::next_week_identity:132-133` 周次由冻结首周 + 7 天节律推出、`:157` 强制 `settlement<=valuation<=decision`；审查方活体探针（repo 外临时根、`python -B`）证 `not_started→发 receipt→fresh`、重复签发被 `DiagnosticStartReceiptError` 拒。②model-paper→identity：首周 prior 取种子自身 `as_of`（`:146-155`）、账户未推进走 `WeeklyAdvanceNotReady` 等待态而非故障（`:162`）。③captures→settle：包缺→`waiting_for_inputs`（`:289-296`）、结算委托唯一 owner `settle_week`（边界 publish 与幂等单点，`:297-308` 注释明说不复制该策略）。④cash/g\* loaders：以账本已结周做键、游离目录进不来（`load_cash_returns:332-350` 周次交叉核；`load_target_exposures:375-402` `as_of=decision_date` 绑定 + note digest 进 `source_refs`）。⑤记录→step/聚合器：引用刀 10b 审查轮 16 探针与家族测试包。⑥step→capstone：引用今晨 10c 审查轮 7 植入（staging root 名单量词化 + splice 落 §12）。

**根管道事实（写给未来读者）**：capstone 的 `market_diagnostic_root` 只覆盖诊断 store 根；`inputs_root` / `model_paper_root` / `runs_private_root` / `output_root` 各有默认、指真树。实跑全默认=一致；任何 sandbox 用法（含演练刀）五根**必须全部显式传参**。

**唯一发现**：`FRED_API_KEY` 已进操作者环境后，`tests/test_us_short_market_diagnostic_cash_return.py:426` 恒红（测试断言 key 缺失却未隔离环境）——`R-USSHORT-CASH-KEY-TEST-READS-THE-OPERATORS-ENVIRONMENT`（Required，正文只在 register）。另一条非缺陷 wiring 留痕（一键 settle 无 sidecar 绑定参数）已追加进股息条目。

## 2026-08-07 追加：演练刀（rehearsal harness）执行规格 — 待用户 `执行` 后由 Codex 实施

**为什么要这刀**：刀 0–10c 全部建完并接线，但从没有任何一次运行让 26 个连续周走完整条链；本轨一周内三次自我发现的缺陷（报告行无读取方、staging root 未注入、周任务只读不推进）共同点都是「每刀单测全绿、接起来是死的」。开钟不可回滚（第 1 周由 receipt 冻结），在那之前需要一个能反复空跑、产物可读的检查台。**演练产物永远不是诊断证据，不进任何真根，不可被引用。**

**新建文件（零生产代码改动）**：`runners/us_short_market_diagnostic_rehearsal.py` + `tests/test_us_short_market_diagnostic_rehearsal.py`。授权一致性守卫把新函数拉进论域时按机制加豁免并写明理由（参照 `splice_diagnostic_report_lines` 那条的形态）。

**CLI**：`--root`（必填）、`--weeks`（默认 26）、`--first-decision-date`（必填，YYYYMMDD，须为交易周一；receipt schema 拒周末，审查方已实测）、`--no-count-weeks`（可选，逗号分隔周号）、`--with-total-return-sidecar`（可选旗标，见下）。

**唯一的门（fail-closed，~10 行）**：`--root` 必须为绝对路径，且 `resolve()` 后**不在仓库树内**（与 `engine.us_short_private_paths.ROOT` 比较）——这同时排除了所有 engine 默认根（`market_diagnostic_private` / `market_diagnostic_inputs_private` / `model_paper_private` / `runs_private` / `DEFAULT_PUBLIC_ROOT` 全在仓内）。非空根直接拒绝（操作者自己删；不做 `--reset`）。**审查方已探针实证**：repo 外 TemporaryDirectory 被 store 守卫接受（`reject_nonprivate_output_path` 明文放行仓外绝对路径），故此门**不需要动任何守卫或白名单**——原第一拆刀条件解除。

**sandbox 布局**（runner 在 `--root` 下自建）：`diag/`（诊断 store）、`inputs/`（inputs_root）、`model_paper/`、`runs/`（runs_private）、`public/`（成绩单 output_root）、`reports/<decision_date>/weekly_report.md`。

**rehearsal 标记**：`diagnostic_epoch="rehearsal-<YYYYMMDD>-<n>"`（审查方已实测过 schema）；每份周报第 1 节内容带「REHEARSAL — 非诊断证据」横幅（横幅是节内容，不改 renderer 契约）。

**每周链条（全部复用现有公开入口，不绕道）**：①model-paper 周：`initialize_store` 一次播种 + 逐周 `freeze_decision_bundle` → `commit_settlement_and_freeze_next`（`paper_evaluable=true`；seed/bundle/settlement 形状抄 `tests/test_us_short_model_paper_store.py` 的 fixtures；价格路径用确定性序列，零随机）；②基准包：优先复用 fetch 模块「下载」与「组包」的分层（若可分），否则按 schema 直接合成 `benchmark_week_directory(decision_date, inputs_root)/PACKET_FILENAME`，由 settle 的 `validate_local_price_packet` 守门；③现金观测：按 capture schema 1.1.0 合成 `cash_week_directory(...)/OBSERVATION_FILENAME`（顶层带 `calendar_week_index` + `observation`，`available_from` 语义）；④敞口记录：用真 writer `engine/us_short_decision_exposure.py::build_decision_exposure_record` + `write_decision_exposure` 写进 `runs/`；⑤结算：`settle_captured_week(root=diag, model_paper_root=…, inputs_root=…, output_root=public, as_of_date=该周 decision_date)`——与 capstone 一键路径同一入口，边界周自动出成绩单、幂等已由引擎自证；⑥读取：`weekly_diagnostic_step(root=diag, as_of, cash_return_by_week=load_cash_returns(root=diag, inputs_root=…), target_exposure_by_week=load_target_exposures(root=diag, runs_private_root=…))`；⑦周报：用真 renderer 渲染 13 节报告（参照 producer 测试的 `_rendered_weekly_report`），`splice_diagnostic_report_lines` 把该周行拼进 §12。**关键**：五个根全部显式传参——capstone 的 `market_diagnostic_root` 只覆盖 store 根，兄弟根默认指真树，rehearsal 一个都不能省。

**`--no-count-weeks`**：那几周跳过②③（不写 captures）→ 引擎自然走 `waiting_for_inputs` / 该周按引擎规则记 no_count/unavailable；报告可见、26 周分母保留。注意设计 §5.2：启用前的 no-count 会清零 v1.1 连续计数——文档示例用激活后的周号（如 7）。

**`--with-total-return-sidecar`**：默认关。开了则改走 `settle_week(benchmark_packet_path=…, total_return_sidecar_path=…)`（`runners/us_short_market_diagnostic_weekly.py` 的手动路径），VTI sidecar fixture 抄 `tests/test_us_short_market_diagnostic_total_return.py`——这是全仓唯一能**看见** v1.1 完整数字（`raw_excess = exposure + active`）的方式；默认关的原因：一键路径 `settle_captured_week` 没有 sidecar 参数（该 wiring 缺口已记入 register 股息条目 addendum），默认模式如实展示当前一键路径会给出的样子（v1.1 active 但周周 `unavailable`）。若 sidecar fixture 合成过重，此旗标允许拆成后续小刀（第二拆刀条件）。

**零网络**：不 import 任何 provider 模块；测试 poison `socket`/`urlopen` 跑一次最小演练证零请求。

**测试（最小集）**：门三拒（仓内路径 / 省略 `--root` / 非空根）；零网络；N 周跑完产物齐（逐周报告带 §12 行、第 4→5 周 X/4→active 转移可见、边界周成绩单存在、rehearsal 横幅存在）；`--no-count-weeks` 的周在报告可见且分母不变；跑后 `git status` 零变化。

**剩余拆刀条件（撞上即停并报，不硬顶）**：①跨周摘要链（`prior_state_sha256` 类）靠 store 公开 API 拼不出——可能性低，`commit_settlement_and_freeze_next` 存在的理由就是兜它；②sidecar fixture 过重 → 拆 `--with-total-return-sidecar`。

**规模估计**：连测试 ~400–600 行，一刀（半天）。**验证**：焦点 = 新测试模块 + `tests.test_us_short_market_diagnostic_weekly_advance`（同入口消费方）；不触发 rule 3（无生产改动）。

**给 Codex 的命令**：`执行` = 按本节实施 `runners/us_short_market_diagnostic_rehearsal.py` + 测试；先修 register `R-USSHORT-CASH-KEY-TEST-READS-THE-OPERATORS-ENVIRONMENT`（不修它，本机任何含 cash_return 模块的包都是红的，演练刀自己的验证包会被它污染）。

## 2026-08-07 执行：演练刀已实施——26 周第一次真的从头走到尾

**结果**：`runners/us_short_market_diagnostic_rehearsal.py` + `tests/test_us_short_market_diagnostic_rehearsal.py`（零生产代码改动）。26 周实跑 52s 走完全链，第 26 周自动出成绩单（`26w-1-26.json` + `.md`），前 25 周 `not_ready`。**这是本轨第一次有一次运行让 26 个连续周走完整条链**——三次「每刀单测全绿、接起来是死的」正是没有这个台子才发现得那么晚。

**逐周链条按规格全部走公开入口**：store 自己的 `initialize_store`/`freeze_decision_bundle`/`commit_settlement_and_freeze_next` → 真 `capture_week`（注入确定性本地 vendor，走 `module=` 参数）→ 真 `capture_cash_week`（注入 `opener`）→ 真 `build_decision_exposure_record`+`write_decision_exposure` → `settle_captured_week`（与一键路径同一入口）→ `weekly_diagnostic_step`（现金腿/敞口腿都经 `load_*` 传入）→ 真 renderer + `splice_diagnostic_report_lines`。五个根全部显式传参。

**开钟改走 `open_clock` 而不是 `issue_start_receipt`**（与规格的字面不同，理由更强）：①它才是被演练的那个操作员动作，绕过它就是在演练一条没人走的路；②直接 import 起点 receipt 模块会把本模块拉进授权论域，实测需要 **20 条豁免**——而 register 自己写过「豁免多到那个程度就不是例外清单而是开关」。改走 `open_clock` 后本模块自然不在论域内，`SURFACE` 实测为空。receipt schema 把 issuer 钉死在唯一能开真钟的角色上，故演练在通知正文里写明身份，靠 epoch 前缀与沙箱门把两者分开。

**实跑观察到的两件事**：①v1.1 在第 4 个连续真周结算后自动转 `active`，第 5 周报告里出现 `attribution_epoch=`——设计 §5.2 的自动启用在制品上可见，不是只在代码里；②`active` 之后每周仍是 `0/N 周可评估`，因为默认模式不带 VTI 总收益 sidecar——**这正是当前一键路径会给出的样子**，不是演练的缺陷。

**`--with-total-return-sidecar` 已补齐（2026-08-07 同日）**：默认仍关。打开后改走 `settle_week` 手动路径，并**从当周刚捕获的价格包里派生** sidecar（`window_id` / `diagnostic_epoch` / `valuation_date` / 逐只 `prior_price_date`·`price_date` 全部取自包本身）——适配器要把两者对账，自带一套日期的 sidecar 只是在考演练自己的记账。实跑读出 v1.1 的完整身份：`raw_excess=-0.0356 = 仓位效果 -0.0317 + 主动系统效果 -0.0039`，而同样五周在默认模式下是 `0/5 周可评估`。**两种模式都要保留**：默认那条才是当前一键路径真会给出的样子（`settle_captured_week` 没有 sidecar 参数，该 wiring 缺口已在 register 挂账）。开着旗标遇到饿死周时，没有包可对账，自动落回一键入口拿诚实的 `waiting_for_inputs`，不是崩。

**验证**：`tests.test_us_short_market_diagnostic_rehearsal` 12 例（门四拒 / 零网络 / 六周链含一个饿死周 / 26 周成绩单）；焦点包 7 模块 `Ran 123 tests in 79.9s PASS`（含授权论域守卫、IO 清单、类守卫、weekly advance/runner、现金腿）。无生产改动，不触发 rule 3。

**边界**：演练产物永远不是诊断证据——沙箱必须是仓外绝对路径且为空（门实测四拒），epoch 前缀 `rehearsal-`，每份周报第 1 节带「REHEARSAL — 非诊断证据」横幅，且有一条测试在真跑之后核对仓库受保护根零增长。真钟仍未开：没有签发过任何真 receipt。

## 2026-08-08 追加：断供一周后诊断钟不再永久卡死——缺失周写 no_count 并自愈

**改了什么**：`runners/us_short_market_diagnostic_weekly_fetch.py`（周次身份拆出 `_identity_for` + `_paper_week_wrapped_by` 回溯、fetch 侧 `_weeks_now_due` 一次抓齐所有到期周、settle 侧写掉已结束的未记录周再结算当前周、判死规则 `_week_is_over`）、`engine/us_short_market_diagnostic_weekly_producer.py`（新 `settle_missed_week`；顺手修 `build_no_count_record` 的 `source_refs` 只滤股息腿 `None` 的真缺陷，改用 settled 周同一个 `_dedupe_sha256`）、`runners/us_short_weekly_capstone.py`（settle stage 新增一条固定串报告行点名被写掉的周号）、`runners/us_short_market_diagnostic_rehearsal.py`（每周改走 `fetch_next_week` 而非自带日期直调 `capture_week`/`capture_cash_week`；`--with-total-return-sidecar` 只在钟正停在本周时才走手动入口）、三个测试模块与授权论域豁免表。

**为什么改**：`R-USSHORT-26W-DIAG-A-MISSED-WEEK-JAMS-THE-CLOCK-FOREVER-AND-NOTHING-WRITES-NO-COUNT`（与 `...KNIFE7B-NO-COUNT-WEEK-CANNOT-BE-PRODUCED` 是同一缺陷两种说法）。缺一周价格包后，账户仍每周结算，head 的估值日永远越过诊断 store 还在等的那一周，`settlement <= valuation <= decision` 此后恒不成立——周任务每周报 `failed`、日历周数永久冻结，既不是设计允许的 no_count 也不是任何人批准过的行为。用户裁决取 candidate ①（settle 路径自补），判死时点用「下一周的决策日到了，那周才算真的过去」。机制、逐条修法、刻意与裁决文字不同的一处（补抓落在已 gated 的 fetch、写掉仍在 settle）与取舍全文只在 `docs/system_risk_register.md` 该条，本节不复述。

**验证命令**：焦点超集 `.tools\run_unittest_with_repo_pythonpath.cmd tests.test_us_short_market_diagnostic_weekly_advance tests.test_us_short_market_diagnostic_weekly_producer tests.test_us_short_market_diagnostic_rehearsal tests.test_us_short_market_diagnostic_authorization_conformance tests.test_us_short_market_diagnostic_weekly_runner tests.test_us_short_market_diagnostic_local_adapter tests.test_us_short_market_diagnostic_lifecycle tests.test_us_short_market_diagnostic tests.test_us_short_market_diagnostic_aggregator tests.test_us_short_market_diagnostic_cash_return tests.test_us_short_market_diagnostic_benchmark_packet tests.test_us_short_discovery_conformance tests.schema.test_us_short_market_diagnostic_26w_schemas`；全量按 rule 3(a)（改动含生产顶层 runner `runners/us_short_weekly_capstone.py`）走 `.tools\full_pack_ledger.py run us_short`。植入对照脚本走 `python -B` + `PYTHONDONTWRITEBYTECODE=1`，跑完 `git status` 已核零残留。

**验证结果**：焦点超集与全量结果、7 个植入 7 红的逐条清单、以及演练刀「饿中间周 / 饿首周 / 连饿两周」三条整链用例读出的逐周图景，全部记在 register 该条的 `Closure` 与 `docs/SESSION_LOG.md` 顶条。一句话：`weeks=4, no_count=(2,)` 现在跑出 `published / waiting_for_inputs / published / published`，第 2 周以 `no_count` 留在 26 周分母里，`current_window_id` 未变。

**失效的旧结论**：① 上一节写的「演练刀逐周直调 `capture_week` / `capture_cash_week`」已不成立——那样绕开了卡死发生的入口，现在每周走 `fetch_next_week`，饿一周＝那一周不跑 fetch。② 上一节「饿中间周用例断言现状（每周 failed、钟冻在第 1 周）」已被推翻，该用例现断言恢复后的行为；`no_count` 这个 outcome 字段已改名为 `starved`（它标的是「这周被饿了」，而真正的 no_count 记录现在是产物里的东西）。③ register triage 条里「`build_no_count_record` 全仓零调用方」的旧说法此前已更正为「inputs 侧无生产者」，本轮把 inputs 侧也补上了。

**下一步注意事项**：① `KNIFE7-FROZEN-FIRST-WEEK-IS-BARELY-CONSTRAINED` 仍 open，且本轮给了它一个新后果——首周若被设成过去的日期，那些已过去的周会在开钟后第一次运行里被直接写成 `no_count`（以前是卡住）；开真钟前应先补「首周不早于 `issued_at`」的约束。② `as_of_date` 是判死的唯一时钟：capstone 传的是 canonical decision date，直调 runner 的人若传一个远期日期，会让中间所有周被写掉——缺省 `None` 时任何周都不算结束，这是有意的 fail-closed 缺省。③ 供应商长期不可用时，缺失周没有包可投影，钟按设计停在 `waiting_for_inputs` 而不是盲写 no_count；这是数据可得性的限制，不是卡死，恢复后会自己追上。

## 2026-08-08 追加：自愈只覆盖了「被测的那种漏周」——补齐「整周没人跑」，并把「能结算就先结算」放到写掉之前

**改了什么**：`runners/us_short_market_diagnostic_weekly_fetch.py`（新 `plan_week` 三态分类器 = fetch 与 settle 共用的唯一判定处；判死拆成 `_week_is_over` + `_account_has_moved_past` 两半；新 `_unlived_week_identity` 让账户从未结过的周也能被描述和补抓；settle 循环改成「能结算就结算、结算完继续下一周」，只写掉 `unlived` 周；新增 `stalled_on_a_finished_week` 状态）、`runners/us_short_weekly_capstone.py`（停钟专属报告行 + no_count 行改措辞）、`engine/us_short_market_diagnostic_weekly_producer.py`（`build_no_count_record` docstring 按两个调用方分别写清，并明写「账户结过的周绝不能走到这里」）、`runners/us_short_market_diagnostic_benchmark_fetch.py`（补上 `--confirm-user-authorization`，该 CLI 此前必 AttributeError）、`runners/us_short_market_diagnostic_rehearsal.py`（`--no-count-weeks` 拆成 `--starved-weeks` 与 `--skipped-weeks` 两种断供，account 循环学会跳过）、三个测试模块。

**为什么改**：`R-USSHORT-26W-DIAG-SELF-HEAL-ONLY-COVERS-THE-OUTAGE-IT-WAS-TESTED-FOR`（F1 整周没人跑即永久卡死且标签与健康态同形 / F2 漏首周每周硬失败 / F3 把本可评估的周写成 no_count 且理由为假 / F4 未来 as_of 烧活周）+ `...A-MISSED-WEEK-JAMS...` 内的 NAV 窗口条。上一轮只修了「输入断供但账户照常结周」这一种漏法，而现实里最常见的是整周没人跑——那时账户也没结，写掉那条腿永远够不着。机制、逐条修法、为什么 NAV 那条是被 F3 化解而不是单独改，全文只在 `docs/system_risk_register.md`，本节不复述。

**验证命令**：焦点超集 13 模块经 `.tools\run_unittest_with_repo_pythonpath.cmd`；全量按 rule 3(a) 经 `.tools\full_pack_ledger.py run us_short`；植入对照脚本 `python -B` + `PYTHONDONTWRITEBYTECODE=1`，跑完核 `git status` 零残留。

**验证结果**：焦点超集 `Ran 304 in 140.1s PASS receipt:6209b299ab4a94fac444d82f`；全量 `PASS 5604/5604 573.9s`、计数门相等、指纹 `e00fe0735a68`。7 个植入 7 红、控制组先全绿。两种断供的逐周图景与读出的数字在 register 的两条 Closure 里。

**失效的旧结论**：① 上一节写的「饿一周 → 该周以 no_count 出现」**不再成立**——输入断供而账户照常结周的周现在**正常结算**（它能被评估），no_count 只留给账户从未结过的周；`StarvedMiddleWeekTest` 已按此重写。② `--no-count-weeks` 这个旗标已删除，换成 `--starved-weeks` / `--skipped-weeks`；两者不可同时点名同一周。③ 上一节说「no_count 周的 NAV 写 prior 是对的」只在新的唯一调用场景下成立，理由已写进 `build_no_count_record` 的 docstring。

**下一步注意事项**：① 新开一条 `R-USSHORT-26W-DIAG-THE-WEEK-AFTER-AN-UNLIVED-WEEK-COMPARES-TWO-WEEKS-OF-STRATEGY-WITH-DAYS-OF-BENCHMARK`——跳过整周后，恢复周的策略窗口跨两周而基准窗口只有几天，三个候选口径都是设计决策，**须用户裁一个**，开钟前定。② 判死的第二半是「账户自己走过去了」而不是本机时钟，这是有意的：演练台整条日历都在未来，用挂钟做护栏会把演练台一起打死。③ `KNIFE7-FROZEN-FIRST-WEEK-IS-BARELY-CONSTRAINED` 仍 open，开真钟前该补。

## 2026-08-08 追加：那条随机命名导致的假红已闭；跳周后的窗口不对称仍待用户裁

**改了什么**：只改了一个测试文件 `tests/provider/test_us_short_yfinance_grades_fetch.py`——provider 噪声判据由裸子串 `"404"` 换成 provider 真正打印的 `"HTTP Error 404"`，与另两个 token 一起抽成模块级 `PROVIDER_NOISE_TOKENS` + `_leaked_provider_noise()`，并补一条两头都断言的反向用例。无生产代码改动。

**为什么改**：`R-USSHORT-YFINANCE-GRADES-HYGIENE-TEST-FAILS-WHEN-ITS-OWN-RANDOM-SLUG-CONTAINS-404`。该套件把自己的运行 id（`yf_grades_<pid>_<随机5位>`）写进 tracked summary 的路径字段，随机数含 `404` 时那条断言就红——本修复链的一次全量正好抽到 `yf_grades_14740_20404`，赔掉一次 11 分钟的全量。机制、为什么不同时改 slug 的随机派生，只在 `docs/system_risk_register.md` 该条。

**验证命令**：`.tools\run_unittest_with_repo_pythonpath.cmd tests.provider.test_us_short_yfinance_grades_fetch`（本模块）+ 焦点超集 14 模块 + 全量按 rule 3(a) 经 `.tools\full_pack_ledger.py run us_short`（本轮虽只改测试，但未提交树整体仍带前两轮的生产改动，指纹已变，故重绑一次）。

**验证结果**：本模块 `Ran 17 OK`；2 个植入 2 红、控制组先绿（判据退回裸 `"404"` → 目录名那半红；判据恒空 → provider 真消息那半红）。焦点超集与全量结果记在 `docs/SESSION_LOG.md` 顶条。

**失效的旧结论**：上一节里「那条 flake 与本刀无关、只诊断入册不修」已被本轮取代——它已修并配了反向用例。

**下一步注意事项**：`R-USSHORT-26W-DIAG-THE-WEEK-AFTER-AN-UNLIVED-WEEK-COMPARES-TWO-WEEKS-OF-STRATEGY-WITH-DAYS-OF-BENCHMARK` 仍 open 且**本轮刻意没动**：本轮把三个候选口径逐个验过，② 会让基准自己的 26 周累计把同一段市场算两遍、③ 要改 model-paper 记账（越出本轨），只剩 ① 自洽；而 ① 需要周记录里有一个「两边数字都对但窗口不可比」的字段，现有 schema 只有 `strategy_evaluable` / `benchmark_evaluable` 两个开关，硬挑一个置 false 是拿假标签换真问题。所以它需要的是一次 schema 决定，开钟前定。

## 2026-08-08 追加：诊断钟自愈第二轮审查 verdict（FAIL）

**审查对象**：本工作树未提交态中的自愈修复轮，针对 `R-USSHORT-26W-DIAG-SELF-HEAL-ONLY-COVERS-THE-OUTAGE-IT-WAS-TESTED-FOR` 的 F1–F4。改动面：`plan_week` / `_weeks_now_due` / `settle_captured_week` 三段自愈逻辑（`runners/us_short_market_diagnostic_weekly_fetch.py`）、`settle_missed_week`（`engine/us_short_market_diagnostic_weekly_producer.py`）、capstone 的 no_count 报告行与停钟状态、基准 fetch CLI 补 `--confirm-user-authorization`。

**verdict**：`审查 FAIL`。四条 Required 的修法形态逐条实读确认正确——可评估周即使已过去也照常结算（`no_count` 保留给不能评估的周）、判死由「`as_of` 说下一周决策日已到」与「账户估值已越过」两半共同成立、到期周一次抓齐、补抓仍在已 gated 的 fetch、停钟另给 `stalled_on_a_finished_week` 状态与专属报告行。

**拦住的一条**：`plan_week` 的 `except WeeklyAdvanceError` 把 `_identity_for` 抛出的**任何**故障（包括「已被 head 采纳的已结算周读不出」与「三日期不对齐」）在「本周已过 + 账户已越过」时一律洗成 `unlived`，写成一条理由为假、不可撤销的 `no_count` 周。护栏本身存在且有反向测试，但那条测试打在 `next_week_identity` 层，生产周任务走的是 `settle_captured_week → _next_week_plan → plan_week`，护栏在这条路上被自己的 `except` 吃掉。完整机制、探针复现步骤、Required repair 与 Closure tests 见 `docs/system_risk_register.md::R-USSHORT-26W-DIAG-A-FAULT-IN-THE-PAPER-WEEK-IS-LAUNDERED-INTO-A-NO-COUNT-WEEK`（含两条不阻塞 Optional：一轮结算多周时边界周的 `publication` 会被后一周覆盖）。

**验证边界**：验收超集 `Ran 268 in 125.0s PASS receipt:5d99e65ae100c8cfcbffff73`（包全绿而缺陷真实）；全量按 rule 4 不重跑，引用执行方 ledger `5604 OK / 573.9s`、指纹 `e00fe0735a68`（trigger rule 3(a) 成立）；§6a 独立对抗 agent 本轮未起（会话级规则禁用），补偿为审查方自写探针与上一轮同面 agent 覆盖；真实 vendor 行为仍未联网验证。本 verdict 只覆盖诊断轨的五个源文件与三个诊断测试模块，其后新增的 `tests/test_us_short_yfinance_grades_fetch.py` 改动不在本轮验收包内。

**落盘约定变更（2026-08-08 用户定）**：此后所有交接文档（register / SESSION_LOG / handoff）一律写入本工作树 `D:\cnhea\Stock-wt\us-short_r28`；`wt/usshort_r1` 只负责审查、提交与 merge，不再承载审查记录。

## 2026-08-08 追加：故障不再被洗成 no_count 周（gap 与 fault 在抛出点分家）

**改了什么**：`runners/us_short_market_diagnostic_weekly_fetch.py`——新增 `WeeklyAdvanceGap(WeeklyAdvanceError)` 标记「账户这里没有这一周」，`WeeklyAdvanceNotReady` 改继承它，新增 `WeeklyAdvanceNoPaperWeek(WeeklyAdvanceGap)` 用于「没有可包裹的已结算周」那个抛出点；`plan_week` 的 `except` 由 `WeeklyAdvanceError` 收窄为 `WeeklyAdvanceGap`。同轮收口两条 Optional：结算多周时保留真正发生过的那次 `publication`、`calendar_week_index` 取 `settled_weeks[-1]`；并把「结算完一周后是否继续下一轮」加了「该周已过去才继续」的界。测试侧加三条 Closure 用例 + 一条正控 + 一条 O1 单元断言。

**为什么改**：`R-USSHORT-26W-DIAG-A-FAULT-IN-THE-PAPER-WEEK-IS-LAUNDERED-INTO-A-NO-COUNT-WEEK`。上一轮我用 `except WeeklyAdvanceError` 包住整个 `_identity_for`，于是「已结算周读不出」「三日期不对齐」两种**故障**也被归类成 `unlived`，写下一条理由为假且不可撤销的 no_count 周——把一个可修复的损坏件烧成了 26 周分母里的一格。机制、复现步骤与逐条 Closure 只在 `docs/system_risk_register.md`。

**验证命令**：`.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 400 tests.test_us_short_market_diagnostic_weekly_advance tests.test_us_short_market_diagnostic_rehearsal tests.test_us_short_market_diagnostic_authorization_conformance`（该三模块实测 332.7s，超 300s 默认上限，原因见下条）；植入脚本 `python -B` + `PYTHONDONTWRITEBYTECODE=1`。

**验证结果**：三模块 `Ran 78 in 332.7s PASS`；审查方探针在生产路径复现为**抛错且零残留**（无周记录、无 register）；5 植入 5 红、控制组先全绿。**其中两个植入第一次跑成绿**——它们瞄准的用例把 `_identity_for` mock 掉了、走不到被改的抛出点，改瞄「跳过第 1 周」那条真穿过该点的端到端后才转红。

**失效的旧结论**：上一节「判死拆成两半」的描述仍成立，但**不完整**——两半只回答「该不该判死」，不回答「这个拒绝是不是一次故障」。现在 gap 与 fault 由异常类在抛出点分开，新增抛出点必须自己选边，忘了选就默认是 fault（安全侧）。

**下一步注意事项**：新开 `R-USSHORT-26W-DIAG-REHEARSAL-GOT-4-5X-SLOWER-WHEN-IT-STARTED-USING-THE-REAL-FETCH-ENTRY`——演练台改走真 `fetch_next_week` 之后，26 周整链由 52s 变 **231.6s**（每周多出数次全账本校验，随周数是 O(n²)），焦点包因此撞 300s/600s 上限。方向是给读取链一个单次运行内的一致性缓存，不得弱化校验；在它修好之前，这条轨的焦点包要显式带 `--timeout-seconds`。

## 2026-08-08 追加：演练台的 O(n²) 消除（读取链一次调用只读校一遍）

**改了什么**：`engine/us_short_market_diagnostic_lifecycle.py`——`load_lifecycle_register` 与 `load_settled_weekly_records` 合并为同一个 `load_register_and_settled_records`（两个公开读取方成为它的投影），`_register_from_records` 新增 `records_already_validated`，只在「这批记录几行之前刚由验证型装载器产出」时置真。授权论域表同步注册 `load_register_and_settled_records`（它才是真正复核锚点的那个）。加一条「校验没被跳掉」的对照用例。

**为什么改**：`R-USSHORT-26W-DIAG-REHEARSAL-GOT-4-5X-SLOWER-WHEN-IT-STARTED-USING-THE-REAL-FETCH-ENTRY`（用户直接指派）。一次 `load_settled_weekly_records` 原先把全店读校三遍，一次运行里被调多次，随周数是 O(n²)。**不加缓存**是刻意的：跨调用零缓存，每次仍完整读校磁盘，两次调用之间被改坏的记录照样被拒。

**验证命令**：`.tools\run_unittest_with_repo_pythonpath.cmd tests.test_us_short_market_diagnostic_rehearsal`（默认 300s 上限）；焦点包 8 模块同入口；全量 `.tools\full_pack_ledger.py run us_short`。

**验证结果**：演练模块 `Ran 28 in 173.9s PASS`，**跑在默认 300s 上限内**（修前 600s 都跑不完）；焦点包 `Ran 184 in 187.5s PASS receipt:f49349f07a19db76a02f95a9`；篡改一条已存周记录后两个读取方都仍拒。全量仍 TIMEOUT，但地板已定位到别处，见下。

**失效的旧结论**：上一节把「焦点包要显式带 `--timeout-seconds`」写成常态——已不成立，演练模块回到默认上限内。上一节把 lane 超时全部归因于我拖慢的演练模块，也不完整：见下。

**下一步注意事项**：新开 `R-USSHORT-LANE-WALL-CLOCK-FLOOR-IS-ONE-UNRELATED-MODULE-AND-IT-DRIFTED-TO-652s`——runner 这次打印出 `WALL_CLOCK_FLOOR 652.4s of 859.4s (75.9%) is one module: test_us_short_discovery_conformance_executable`，该模块打的是 theme-discovery 与 `weekly_capstone_soft_discovery`、与本轨无关，且同一天在 277s→652s 之间漂（同期全量两次 PASS：573.9s / 742.9s）；已核零残留 worker 进程。**加 worker 无用，只有那个模块自己变快才有用**，那是下一刀。

## 2026-08-08 追加：诊断钟自愈第三轮审查 verdict（未完全验证）

**审查对象**：本工作树未提交态，针对 `R-USSHORT-26W-DIAG-A-FAULT-IN-THE-PAPER-WEEK-IS-LAUNDERED-INTO-A-NO-COUNT-WEEK`（含 O1/O2）的修复轮，外加同期落入审查面的 `engine/us_short_market_diagnostic_lifecycle.py` 读取链去重。

**已闭合并经审查方独立复验**：

- **gap 与 fault 在抛出点分家**。新增 `WeeklyAdvanceGap` 基类，`WeeklyAdvanceNotReady` 与新增 `WeeklyAdvanceNoPaperWeek` 继承它，`plan_week` 的 `except` 由 `WeeklyAdvanceError` 收窄为 `WeeklyAdvanceGap`。形态正确的关键在于**默认方向**：新增抛出点若忘了选边，落在 fault 一侧（不被吞、不消费日历周），而不是落在会写掉一周的一侧。审查方重跑上一轮那条腐坏周探针（损坏已结算周 `20260720` + 本周已过 + 账户已越过），生产路径 `settle_captured_week` 现与控制组 `next_week_identity` 一样拒绝 `cannot be read`，`no_count_weeks` 为空。三日期 `does not line up` 仍是 plain `WeeklyAdvanceError`，按同一收窄自动落在 fault 侧。
- **O1/O2 由机制收口**。`_settle_outcome` 的 `publication` 改为**显式传入**而非读最后一次 `settle_week` 的返回，`calendar_week_index` 取 `settled_weeks[-1]`；跨窗口边界补齐（第 26 周发成绩单后同轮再结第 27 周）不再把成绩单丢掉不报。
- **校验去重是真去重，不是放松**。`load_register_and_settled_records` 把两个公开读取方合成一次读校，`_register_from_records(records_already_validated=True)` 只在同一函数内、`_load_records_for_register` 刚以**同一个 `as_of_date`** 验过这批记录的四行之后传入；全仓仅此一处传 True，另外四个调用点走全校验。审查方植入验证：把周记录 `weekly_return` 改成 schema 合法的数值并**同时修好 register 里的摘要**（使摘要门无法成为拒绝理由），读取方仍拒 `weekly record calculation contract violation: strategy.weekly_return disagrees with NAV construction`；不修摘要的控制组先被摘要门拒，证明植入确实打到了目标层。

**为什么不是 PASS**：与代码无关，是状态问题。①验收超集 `Ran 283 in 88.1s PASS receipt:11cd0d02b0074461527e7fc4` 跑完之后，树上又出现 `tests/test_us_short_discovery_conformance.py`(+45)，scope 已不冻结；②rule 3(a) 早已触发（`runners/us_short_weekly_capstone.py` 是生产顶层入口），而当前指纹**没有任何一次绿的全量**：执行方两轮分别记 TIMEOUT，审查方按 rule 6 升级自跑亦被 ledger 以 `focused acceptance receipt does not match the current code state` 拒绝（正是因为树在动）。lane 墙钟地板已由执行方登记为 `R-USSHORT-LANE-WALL-CLOCK-FLOOR-IS-ONE-UNRELATED-MODULE-AND-IT-DRIFTED-TO-652s`（Required/P2）并正在修。

**下一次交审前需要满足**：树冻结（不再有并发编辑）→ 焦点包重跑出与终稿指纹绑定的 receipt → `full_pack_ledger run us_short` 拿到一次绿并记账。三者齐了这一刀即可直接收 PASS，本轮已复验的三项无需重查。

## 2026-08-08 追加：lane 墙钟地板已量到构成（未压到 570s，未留改动）

**改了什么**：本节**没有代码改动**。唯一尝试过的一处（给 `tests/test_us_short_discovery_conformance.py` 的 `_tree` 加 `lru_cache` 并把 14 处 `ast.parse(_source(...))` 路由过去）实测无收益，已 `git checkout` 撤回。

**为什么**：用户指派把 us_short 全量压回 570s 内。`R-USSHORT-LANE-WALL-CLOCK-FLOOR-IS-ONE-UNRELATED-MODULE-AND-IT-DRIFTED-TO-652s` 的 Required repair 第一项就是「先量清楚」，本轮完成了这一项。

**验证命令**：`.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 800 --durations 25 tests.test_us_short_discovery_conformance_executable`。**注意**：`--durations` 只有全量记账路径会自动加，焦点跑必须显式传——我为此白跑了两次 12 分钟，这是本节最值钱的操作教训。

**验证结果**：`Ran 11 tests in 766.8s`。`test_c_every_repo_derived_guard_callsite_has_a_real_dying_mutation` **445.2s**、`test_d_repo_shared_resource_tests_inject_state_and_lock_roots` **210.2s**、`test_a_matrix_is_independent_derived_and_mutation_load_bearing` 87.6s，其余 8 条合计 <24s。三条猜测已实测排除：非本修复链造成（该模块论域 20 个 theme-discovery 文件，本链改的 6 个文件一个不在内）、非残留 worker（`Get-Process python` 空）、非重复 AST 解析（`_source` 本就 `lru_cache(maxsize=None)`；加 `_tree` 缓存后 747s→767s）。

**失效的旧结论**：上一节推测这个模块「多半是重复编译/解析」——**已被实测否掉**。真实成本是 `test_c` 对每个守卫调用点在 patch 掉守卫后**逐条真跑候选行为测试**直到一条转红才 break（短路已存在，省不出来），成本 = 坐标数 × 命中前跑过的候选真实耗时。

**下一步注意事项**：三条候选方向都不是顺手一行，且**与 26 周诊断轨零耦合**——①候选排序（唯一不改语义的加速，收益取决于候选耗时分布，需再一次约 13 分钟测量才能定值不值）②把 `test_c`/`test_d` 移出 lane 全量单独记账（改变「全量」的含义，属流程决策，需用户定）③深挖 `test_d` 的 210s（内部构成未量）。**应作为独立一刀独立审查，不要再挂在诊断轨的修复链上**。

## 2026-08-08 追加：诊断钟自愈全链审查 verdict（PASS，已合入 master）

**接上一节（未完全验证）**：当时卡住的两件——树未冻结、当前指纹无绿全量——第一件已解除：执行方把没有实测收益的 `_tree` 缓存连同 `tests/test_us_short_discovery_conformance.py` 一并撤回，树回到 **`1ea3200645`**，正是审查方上一节验收包 `receipt:11cd0d02b0074461527e7fc4`（`Ran 283 PASS`）绑定的那个指纹，故该证据逐字节适用，无需重跑。

**本轮补齐的覆盖**：按改动符号（而非改动文件）枚举消费者并全部实跑——`Ran 62 PASS receipt:2004929aa5a09a9a0b3c9093`（`lifecycle_store` / `start_receipt` / capstone 两模块）、`Ran 17 PASS receipt:a09be5c5b5caeb812ea8396b`（yfinance grades 抖动修复，本轮唯一此前未覆盖的模块）。

**为什么在没有绿全量的情况下仍放行**：rule 3(a) 确实触发，但该门当前**结构性不可满足**——单模块 `test_us_short_discovery_conformance_executable` 实测 766.8s，逼近 860s 全量上限，而抬上限须用户明确批准。审查方因此不以「全量绿」放行，改用可枚举 bound：`grep` 出全部消费者后确认只有 `runners/us_short_market_diagnostic_weekly.py` 与 `engine/us_short_market_diagnostic_aggregator.py` 真正 import 诊断 lifecycle；`engine/us_short_weekend_lifecycle_stage.py` 与 `engine/us_short_lifecycle_store.py` 是**同名不同物**（soft-boost 生命周期），**生产选股路径未被触及**。替代 bound、残余风险与「本条修好后须补跑绑定指纹的绿全量」已追记进 `docs/system_risk_register.md::R-USSHORT-LANE-WALL-CLOCK-FLOOR-IS-ONE-UNRELATED-MODULE-AND-IT-DRIFTED-TO-652s`。

**这一刀的最终状态**：刀 8—刀 10 的喂料与推进层加上本轮自愈全链已闭；诊断轨仍 `not_started`、无 receipt、无真实第 1 周，接线完成不等于启动。下一件与本轨无关的独立刀是 lane 墙钟地板。

## 2026-08-08 追加：跳周后的窗口不对称——周记录加字段（schema 1.1.0），恢复周记录但不参与比较

**改了什么**：`schemas/us_short_market_diagnostic_weekly_record.schema.json` 升 `1.0.0 → 1.1.0`，新增两个必填顶层字段 `windows_aligned` / `windows_misaligned_reason`；`engine/us_short_market_diagnostic.py` 钉新版本、校验两字段的双向不变式、并新增「窗口不对齐时任何基准不得 `joint_evaluable`」；`engine/us_short_market_diagnostic_local_adapter.py` 的 `adapt_benchmark_week` 把 `joint_evaluable` 收紧为「两边可评估**且**窗口对齐」，`build_weekly_record_from_local` 接收并落盘该事实；`engine/us_short_market_diagnostic_weekly_producer.py` 的 `_target_week` 连带回报「前一条已存记录是不是 `no_count`」，`build_no_count_record` 补写两字段。夹具与契约测试同步。

**为什么改**：`R-USSHORT-26W-DIAG-THE-WEEK-AFTER-AN-UNLIVED-WEEK-COMPARES-TWO-WEEKS-OF-STRATEGY-WITH-DAYS-OF-BENCHMARK`，用户裁决取①。整周没人跑时账户不结算、挂起决策拖到下一周成熟，那一次结算覆盖两个日历周；于是恢复周的策略收益跨两周、基准只跨几天。三个候选口径的取舍与为什么②③被排除，只在 `docs/system_risk_register.md` 该条。

**验证命令**：`.tools\run_unittest_with_repo_pythonpath.cmd`（10 模块焦点包 + 演练模块各一次）；全量 `.tools\full_pack_ledger.py run us_short`。

**验证结果**：焦点包 `Ran 282 in 194.3s PASS`，演练模块 `Ran 29 in 182.6s PASS`。演练台 `--skipped-weeks` 端到端读出：恢复周 `windows_aligned=false`、四只基准 `benchmark_evaluable=true` 而 `joint_evaluable=false`、`raw_excess=null`，策略侧 `strategy_evaluable=true` 且 `weekly_return` 非空——**两边数字都留着，只是不配对**；再下一周恢复对齐并重新参与比较。5 植入 5 红、控制组先全绿；其中一条第一次跑成绿（被另一道检查先拦下），把 joint 先摘掉后才真正打在那道门上。

**失效的旧结论**：register 里「① 需要一个字段而现有 schema 只有两个开关，所以只能由用户裁」——用户已裁，字段已加，该条已 resolved。另：周记录 `schema_version` 不再是 `1.0.0`，任何硬编码该版本的地方都要跟着走（本轮已扫：两个生产者、契约校验器、三处夹具）。

**下一步注意事项**：①判据是「**前一条已存记录是不是 no_count**」而不是「这一周是不是恢复周」——这是类级的，两个 no_count 生产者都覆盖，连着两个 no_count 就跨三周也自动成立；改动这条判据前先想清楚它要覆盖的是哪一类。②代价是一次整周没人跑会让「可联合评估周数」少两周（26 周分母不变），设计 §5 的 20 周门因此更慢达成——方向是更保守。

## 2026-08-08 追加：窗口对齐门审查 verdict（FAIL）

**审查对象**：本工作树未提交态 11 文件，实施用户对 `R-USSHORT-26W-DIAG-THE-WEEK-AFTER-AN-UNLIVED-WEEK-...` 的裁决①（周记录加字段），周记录 schema 升 `1.0.0 → 1.1.0`，新增必填 `windows_aligned` / `windows_misaligned_reason`，`joint_evaluable` 由「两边可评估」收紧为「两边可评估且窗口对齐」。

**成立的部分（已实读确认）**：判据是**账本派生**而非调用方断言——`_target_week` 顺带回报「前一条已存记录是不是 no_count」，两个 no_count 生产者与连续两个 no_count 的情形都覆盖；`joint_evaluable` 是聚合器实际读的字段，所以 §5 的 20 周门与逐周超额自动排除该周，不必改聚合器；no_count 周自己写 `aligned=true` 的取舍成立（它没有跨度可对齐，出局靠 `strategy_evaluable=false`，一个事实一个字段）；已知代价（一次整周没人跑使可联合评估周少两周、26 周分母仍为 26）与设计 §5「no_count 周保留在窗口分母」一致且已入册。

**拦住的一条**：同一个字段两套强度不一的验证器。逐条记录那侧 `validate_weekly_record` 要求真布尔并强制与 reason 双向一致；窗口那侧 `_validate_rows` 只写 `bool(row.get("windows_aligned", True))`，既不 `_required` 也不查类型，`_validate_benchmark` 与 `adapt_benchmark_week` 的形参默认值同样是 `True`——三处默认都朝放行，而这道门的唯一用途是**排除**。探针在 `validate_window` 公开入口上实测：控制组（`aligned=False` 且 joint 为真）正确拒；删掉字段放行；写成字符串 `"false"` 放行；写成整数 `0` 才拒。今天不致命是因为聚合器喂进来的记录都过了逐条验证器，但 `validate_window` / `summarize_window` 是接受调用方自带 rows 的公开入口，防线不该建立在「调用方恰好来自另一条已校验的路」上。完整机制、Closure tests 与一条 Optional（schema 整文件重排版把两字段的新增淹在约 250 行格式噪声里）见 `docs/system_risk_register.md::R-USSHORT-26W-DIAG-THE-NEW-ALIGNMENT-GATE-DEFAULTS-TO-ALIGNED-WHEN-THE-FIELD-IS-ABSENT-OR-NOT-A-BOOLEAN`。

**验证边界**：验收超集 `Ran 363 in 81.1s PASS receipt:df67c880f3460731658a1fbe`（13 模块）——包全绿而缺陷真实，说明这道门缺的正是「缺字段/错类型」这一类反向用例。全量按用户本轮指示未起，引用执行方 `parallel_lane_runner PASS 5613/5613 1147.1s`（超 860s 系用户单次授权、未进 ledger）。§6a 独立对抗 agent 未起（会话级规则禁用），补偿为审查方自写探针。

## 2026-08-08 追加：全量墙钟 1147s → 837s（地板降 72%），瓶颈转移到串行尾巴

**改了什么**：`tests/test_us_short_discovery_conformance.py`——`test_c` 把「有无冗余兄弟坐标」的判断从扫完全部候选之后**提到扫描之前**，扫描中 `hit` 一到即停；并抽出 `ResourceIsolationMatrix`（`test_d` 原样搬入）。新增 `tests/test_us_short_discovery_conformance_resources.py` 承载它。`docs/us_short_test_io_inventory_20260801.json` 按实重生成（新模块使 `module_count` 305→306）。**两处都没有改动任何断言**。

**为什么改**：`R-USSHORT-LANE-WALL-CLOCK-FLOOR-IS-ONE-UNRELATED-MODULE-AND-IT-DRIFTED-TO-652s`，用户要求全量压回 600s 内。逐坐标的结论是 `hit ∧ (死掉 ∨ 有兄弟)`，兄弟只依赖已在手的数据；`test_d` 的「正序+逆序各跑一遍」里逆序是抓顺序依赖泄漏的，不能删，只能改打包。

**验证命令**：`.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 700 <五模块验收包>`；`.tools\full_pack_ledger.py run us_short`。定位用 `--durations 25`（焦点跑必须显式传，全量记账路径才自动加）。

**验证结果**：`test_c` 445.2s→114.4s；地板模块 675s→**183.8s**（占比 58.8%→22.0%）；验收包 `Ran 67 in 530.8s PASS`；全量 **`PASS 5613/5613`、计数门相等、837.0s**、已记账（此前连续三次 860s TIMEOUT）。**未达 600s。**

**失效的旧结论**：①「这个模块慢多半是重复编译/解析」——实测否掉（加 AST 缓存 747→767s，已撤回）；②「按耗时重排候选能省」——实测否掉（445→450s，因为 break 几乎总在第一条候选就发生，已撤回）；③「地板是全量的瓶颈」——现在不是了，见下。

**下一步注意事项**：瓶颈已转移到**串行尾巴**。所有模块耗时合计 **1306.3s**、墙钟 837s，并行效率仅 **1.56×**；前四名 `conformance_executable 183.8 + conformance_resources 178.4 + market_diagnostic_rehearsal 164.9 + market_diagnostic_aggregator 107.5 = 634.6s` 基本就是那条队。`serial_tail_modules` 把「源码或传递导入命中跨进程锁」的模块排成一队，**加 worker 无用**。方向：让这四个自身更快（其中 rehearsal 与 aggregator 属本诊断轨，是我方可动的面），或证明某些模块并不真的需要那把锁——**后者须极谨慎**，串行尾巴存在的理由正是防止并发把锁竞争读成假红。另注：新模块首次进 lane 时没有历史耗时记录，会被排到最后而撞上限；`.tools/state/parallel_module_durations.json` 记下之后即恢复正常。

## 2026-08-08 追加：窗口对齐门的放行默认已收口（一个字段一份判据，三处默认值删净）

**改了什么**：`engine/us_short_market_diagnostic.py` 新增 `_window_alignment(record)` 作为 `windows_aligned` / `windows_misaligned_reason` 的**唯一**读取器（两字段 `_required`、必须真 `bool`、理由双向一致），`validate_weekly_record` 与 `_validate_rows` 都只经它取值；`_validate_benchmark(windows_aligned)`、`adapt_benchmark_week(windows_aligned)`、`build_weekly_record_from_local(prior_week_was_no_count)` 三处默认值**删除改为必传**；`build_no_count_record` 显式写 `windows_aligned=True` 并注明理由。schema 文件按 HEAD 原文重新落最小增量（恢复紧凑单行风格）。

**为什么改**：`R-USSHORT-26W-DIAG-THE-NEW-ALIGNMENT-GATE-DEFAULTS-TO-ALIGNED-WHEN-THE-FIELD-IS-ABSENT-OR-NOT-A-BOOLEAN`。同一个字段有强弱两套判据：记录侧要求真布尔并双向校验，窗口侧却是 `bool(row.get("windows_aligned", True))`——删掉字段、或写成字符串 `"false"`（`bool("false")` 为真），都能从公开入口 `validate_window` 走过去。这道门存在的唯一目的就是把一周排除出比较，它却在拿不到判据时选择放行。

**验证命令**：`.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 400 <10 模块验收包>`；全量 `.tools\full_pack_ledger.py run us_short`。

**验证结果**：验收包 `Ran 285 in 198.0s PASS receipt:dea5370b152e6c9e0f6abe53`。**5 植入 5 红、控制组先全绿**：窗口侧退回宽松读取 / 共用读取器不再 `_required` 字段 / 不再 `_required` 理由 / 某签名重新长出默认值 / 收紧把原有的「不对齐不得 joint」打歪。schema diff 由 +330/−65 收回到 **+5/−1**。

**失效的旧结论**：上一节说「`joint_evaluable` 收紧后聚合器自动排除该周」仍成立，但那只在字段可信时成立——现在字段本身在两个入口都被强制校验，这句才真的闭合。

**下一步注意事项**：**取「必传关键字」而不是「安全侧默认」是有意的**——安全侧默认仍会静默生效，忘了传的调用点不会有任何声响；删掉默认则当场 `TypeError`（本轮因此逼出 6 个测试调用点显式声明）。另配了结构守卫 `test_no_alignment_knob_carries_a_default_that_means_aligned`（AST 扫那三个签名），因为这类默认值在没人漏传时行为测试抓不到。

## 2026-08-08 追加：窗口对齐门收口审查 verdict（PASS，已合入 master）

**已闭的 Required**：`windows_aligned` 现在只有一个读取器 `engine/us_short_market_diagnostic.py::_window_alignment`——两个字段都走 `_required`、`windows_aligned` 必须是真 `bool`、`windows_misaligned_reason` 与它双向一致，记录入口与窗口入口都只经它。三处朝放行的形参默认值（`_validate_benchmark`、`adapt_benchmark_week`、`build_weekly_record_from_local`）**删除改为必传**，理由比「默认取安全侧」更强：安全默认仍会静默生效，删掉才会在漏传时当场 `TypeError`；另有 AST 守卫钉住这三个签名不得再长出默认值。Optional 也已闭——schema diff 由 +330/−65 收回 +5/−1。

**审查方独立复验**：重跑上一轮的探针，三种坏形状全部转拒（缺字段 `is required`、字符串 `"false"` 与整数 `0` 同报 `must be boolean`——后者不再靠 `bool()` 的真假巧合），正控（合规 26 行窗口）仍 `ACCEPTED`。另补一条**防「严读掩盖」**的探针：更严的读取器现在会先因缺理由报错，可能掩盖 joint 门本身是否还活；给它一个**格式完全合规的不对齐周**并保留 `joint_evaluable=true`，仍被拒 `benchmarks.VTI joint_evaluable over misaligned comparison windows`，摘掉 joint 声明后重新被接受——两道门各自独立可证。

**同轮的 D 轴模块拆分（本审查一并覆盖）**：`ResourceIsolationMatrix` 在 `tests/test_us_short_discovery_conformance.py` 里已是**普通类而非 TestCase**，由新模块 `tests/test_us_short_discovery_conformance_resources.py` 以 `(base, unittest.TestCase)` 承载——正是 `R-USSHORT-A-SHARED-FIXTURE-DRAGGED-ITS-OWNERS-TESTS-INTO-A-SECOND-MODULE` 立下的正确形状。实测发现数：旧模块 0 条 ResourceIsolation、新模块 1 条，**无双跑**；`docs/us_short_test_io_inventory_20260801.json` 只是 module_count 305→306、class0 +1 与路径摘要更新，**allowlist 未新增任何条目**（没有新的真树写入）。`tests/test_us_short_discovery_conformance_executable.py` 在 status 里显示 modified 但内容 diff 为空，属 CRLF churn，未带入内容改动。新模块原为 untracked，已由审查方纳入本次提交——否则 D 轴覆盖只存在于本机。

**证据强度（本链首次达标）**：验收超集 `Ran 316 in 104.9s PASS receipt:1506d4fa0d7ec4c9f52afce3`，其指纹 `b1a940efb317` 与 ledger 全量 `PASS 5616/5616 829.2s` 同指纹——第一次有一次**绑定当前树态的记账绿全量**，故按 rule 4 未重跑。拆分把 lane 从 TIMEOUT/1147.1s 拉回 829.2s、重新落在 860s 上限内，`...LANE-WALL-CLOCK-FLOOR-...` 因此翻 partially resolved（仍未达用户要的 600s，瓶颈已转移到串行尾巴）。

## 2026-08-08 追加：两轮派工与「本轮无可审对象」的记录

本节补两轮的收口——上一轮只落了 register 与 SESSION_LOG，没有回到本 handoff，属漏写，一并补齐。

**① register 状态回写（已派工，尚未执行）**：`R-USSHORT-26W-DIAG-OPEN-LIST-TRIAGE-20260807` 的 Required ① 被定为独立一轮的**全部**范围——8 条强证据条目翻 `resolved` 并写回证据。硬约束写在该条目里：这是账目回写不是修复轮，**不得改任何代码 / schema / 测试**；且**不得照抄 2026-08-05 的核对结论**，那次之后这条轨又落了七八轮改动，每条必须按今天的代码重新定位、亲眼确认后再翻，并把「现在看到的是什么」写进该条目自己；任一条重新确认后仍成立即 STOP、留 `open`、不自行开修。

**本轮审查：无可审对象**。`git status` 为空，`wt/us-short_r28` 与 master 同在 `1e521dd6`，①尚未执行。按 AGENTS item 16c，没有可审实现时不得冒充 code-level PASS，故本轮不产生代码结论，只做派工落盘（`35a05fd8`）。

**② 下一刀（已派工，前置为 ①）**：三部分一轮做完，写在 `R-USSHORT-26W-DIAG-KNIFE7-FROZEN-FIRST-WEEK-IS-BARELY-CONSTRAINED` 之下。**A 首周门**——`first_decision_date` 补「必须是 canonical 决策周」与「不早于 `issued_at`」，判据取该条目 2026-08-05 已定的闭合判据，无需新决策。**B 前视门的放行默认**——`_validate_rows` 的未来日期检查写成 `if as_of is not None`，而 `validate_window` / `summarize_window` / `publish_completed_market_diagnostic_window` 的 `as_of_date` 默认 `None`，不传即整条门不生效；修法照抄本轨刚确立的形状（**删默认改必传** + AST 守卫钉签名），反向用例是「26 周纯未来日期的窗口必须被拒」。**C KNIFE7 家族 5 条定点探针**——因落在 A/B 要改的同一片代码而并入，每条一个可复现探针，已消失则翻 resolved 并附输出，仍成立则保持 open 且本刀不修。

**为什么 ① 必须在 ② 之前**：两轮改的是同一批 register 条目，并行必冲突；且 ① 做完之后这条轨的 open 清单才可信，② 的排期才不会建立在虚高的数字上。

## 2026-08-08 追加：triage Required ① —— 8 条强证据的状态回写（账目轮，零代码改动）

**改了什么**：只改两份 doc。`docs/system_risk_register.md` 里 8 条 header 由 ` — open ` 翻 ` — resolved `，每条正文末尾追加一条 `- **2026-08-08 复核（逐条重新确认）**` 证据行；triage 条 `R-USSHORT-26W-DIAG-OPEN-LIST-TRIAGE-20260807` 追加 Required ① 完成标注。`docs/SESSION_LOG.md` prepend 一条修复 entry。**未动任何代码 / schema / 测试**——这是审查方派工的硬约束，`git diff --name-only` 只有这两份 doc 加本文件。

**为什么改**：triage 条的 Required ① 要求「8 条强证据逐条翻 resolved 并写回证据」，且明令**不得照抄 2026-08-05 的核对结论**——那次是按线索批量核的，这次要求每条重新定位到现行代码、亲眼确认机制确实不存在、把「现在看到的是什么」写进该条目自己的正文。在 ①② 做完前，任何「本轨还剩 N 条」的说法都不可引用；这轮先把 ① 的账做实。

**验证命令**（逐条现证，均在主树 `D:\cnhea\Stock` 执行）：
```
grep -n "def _run_market_diagnostic" -A 30 runners/us_short_weekly_capstone.py     # ①
grep -n "records = \[\]" engine/us_short_market_diagnostic_weekly_producer.py       # ②
grep -n "diagnostic_store_state" engine/us_short_market_diagnostic_weekly_task.py runners/us_short_market_diagnostic_weekly.py   # ③
python -c "import json;print(len(json.load(open('presets/us_short_market_diagnostic_strategy_ruleset_v1.json'))['governed_presets']))"  # ④
sed -n '95,112p;320,330p' tests/test_us_short_market_diagnostic_authorization_conformance.py   # ⑤⑥
sed -n '165,168p;306,312p' engine/us_short_market_diagnostic_aggregator.py          # ⑦
sed -n '1199,1225p' engine/us_short_market_diagnostic_attribution.py                # ⑧
.tools/run_unittest_with_repo_pythonpath.cmd -v tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency
```

**验证结果**：8 条**全部**确认机制已不存在，无一条需按「复核仍成立」留 `open`。
- ① `_run_market_diagnostic` 在 :490，`try:` 在 :511，`from engine.us_short_market_diagnostic_weekly_task import weekly_diagnostic_step` 在 :519 —— lazy import 已在 `try` 内，import 期 schema 装载失败走 stage 失败返回而非抛穿；另有 `test_a_dormant_clock_costs_nothing_at_all`。
- ② `records = []` 零命中 —— 把 lifecycle 异常吞成空列表、进而把任何故障读成「第 1 周」的 `except` 已删。
- ③ `diagnostic_store_state` 四态判定器被 `weekly_task.py:46/:82` 与 `us_short_market_diagnostic_weekly.py:63/:291` 两处真正消费；「没有 store」与「store 坏了」不再共用出口。
- ④ `governed_presets` 由 9 份扩到 **16 份**，含当初点名漏掉的 `us_short_scoring_profile_governance_20260620.json`；由 `test_every_engine_preset_is_classified_as_governed_or_excluded`（`weekly_producer` 测试 :183）守住「非治即排」。
- ⑤ 代理判据已被性质本身取代：:101 就地写着「There is deliberately no filter here」并点名旧代理（按参数是否叫 `root` 判定，曾对 aggregator 十二个函数瞎掉十一个）；域改为 `_surface_functions()`（:283）扫出的全集，唯一出口是具名 `EXEMPT`。
- ⑥ 判据由「函数体内出现 GATES 的名字」改判**形状**：:100 `PUBLISH_PATH_ALLOWED_PARAMS`（允许清单，非屏蔽清单），:324-326 断言发布路径函数不得携带清单外参数 —— 改名绕不过去。
- ⑦ 结构性消失：`build_market_diagnostic_report(*, lifecycle_root, as_of_date=None)`（:165）的 `records` 已删，`write_market_diagnostic_report(*, lifecycle_root, output_root, as_of_date)`（:306）的 `report` 已删；无法再被喂进与受门 store 无关的伪造史，错误组合**不可表达**。
- ⑧ schema 已含 `carried_holdings_exposure` / `new_order_exposure`，`validate_attribution_report`（:1206-1224）真重推：两分量各过 `_finite` 与 `[0,1]`，其和与 `requested_exposure` 差超 `_TOLERANCE` 即 `_fail`。
- 门：`tests.test_doc_governance_guard` + `tests.test_route_doc_ledger_status_consistency` `Ran 55 OK / 1.0s / receipt:ae4a57b00f33180a78c1796e`。回写 diff `+16/−8`（8 header + 8 证据），证明未整文件翻转、未误伤邻条。**未跑全量：零代码改动。**

**失效的旧结论**：
- 「本轨还有 8 条 KNIFE6/7/7B 强证据 open」——作废，8 条均已 `resolved` 并各带现行代码证据。引用「本轨还剩 N 条」时须重新数。
- 「`KNIFE6-REQUESTED-EXPOSURE-IS-ASSERTED-NOT-DERIVED` 是 requested_exposure 完全没被校验」——作废，但**别读成完全关闭**：所述机制（schema 缺分量）已闭，两分量本身仍是 producer 自报、本模块按 design 12.7 不得读成交去核，把 0.9 拆成 0.5+0.4 仍能过。门槛已从「写一个数」抬到「写两个能对上的数」，彻底关闭属尚不存在的 target-exposure producer。该残留已在 `attribution.py:1199-1206` 就地写明，不属本条。

**下一步注意事项**：
- triage 条**不关闭**。Required ②（7 条弱证据的定点探针）与 ③（2 条确认成立的进修复队列）仍 open，由用户裁决是否起刀。
- `KNIFE7-FROZEN-FIRST-WEEK-IS-BARELY-CONSTRAINED` 的首周门已与「前视门 `as_of_date` 默认 `None` 致整条门可选」并为下一刀，别提前动。
- 分叉待处理：`wt/us-short_r28` 工作树的 `docs/system_risk_register.md` 另有 6 行未提交（全量测试提速 option 1 的待做记录），主树这份没有；两棵树同名文件现已不同，合并前先对齐。

## 2026-08-08 追加：triage Required ① 审查 verdict（PASS-with-Required）

**审查对象**：`9381cc49`（已由执行方直接提交在主树），8 条强证据条目的状态回写。

**范围守住了**：只动 4 个文档，零代码 / 零 schema / 零测试，与派工写的「这是账目回写不是修复轮」一致。8 条**确属按今天的代码重新定位**而非照抄 2026-08-05——每条都带 file:line 或符号名加一句现状（lazy import 已进 `try`、吞成空列表的 `except` 已删、四态判定器有两个真消费点、governed presets 由 9 份增至 16 份、conformance 域改为扫描全集、publish 路径改为允许清单形状门、两个 report producer 的伪造史入口参数已删）。审查方抽验两条属实：`records = []` 在 `weekly_producer` 里零命中；两个 report producer 已是关键字签名。

**拦下的一条（P3，doc drift，不影响翻状态本身）**：`KNIFE6-REQUESTED-EXPOSURE-IS-ASSERTED-NOT-DERIVED` 翻 `resolved` 成立，但回写称残留「属尚不存在的 target-exposure producer」**与事实不符**——该 producer 已建成并于 2026-08-07 审过（`runners/us_short_market_diagnostic_weekly_fetch.py:863 load_target_exposures`，两分量取自 `engine/us_short_decision_exposure.py:147-148` 决策当时落下的只读记录，是推导不是自报）。真实残留比回写说的窄，只剩「经其他路径手工递入两分量」那一支。这句话会误导下一个人去建一个已经存在的东西，故必改；更正与 repair 已就地追记在该条目内。

**清单可信度的变化**：Required ① 完成后，这条轨的 open 清单第一次可以按面值读；Required ② ③ 仍 open，triage 条目不关闭。下一刀（首周门 + 前视门默认 + KNIFE7 家族 5 条探针）的前置因此已满足。

## 2026-08-08 追加：刀 5 捕获段回溯审查 verdict（PASS）

**对象**：`d4303f61`（2026-08-05 已并入 master；`D:\cnhea\Codex\worktrees\891a\Stock` 那棵树落后 125 个提交，故按 master 当前态审，该段文件此后未再被改动）。

**结论 PASS，三道真钱/密钥门实读确认**：`confirm_user_authorization` 是函数级门；raw 与 normalized 路径必须**正向**确认落在 `provider_samples/` 之内（`_is_gitignored_provider_path` 用 `relative_to` 判，不是靠字符串前缀），否则直接拒；三份产物任一已存在即拒覆盖，不会静默重写证据；分页预算在**发出请求之前**判，超限不花调用。续页处理是这段里最稳的一处：校验厂商回的 `next_url` 没有改 host / path / symbol / adjusted 模式，剥掉来路 `apiKey` 再补上授权的那把——厂商无法把密钥引到别处去。

**审查方植入 4 条全红、控制组先绿**：把「请求 URL」「裸 `apikey=`」「环境密钥字面量」「`"payload"` 键」分别喂给 `_scan_summary_safe`，均抛 `EtfCaptureError`，干净文本放行。该扫描跑在**序列化之后、落盘之前**，所以摘要里 `tracked_summary_contains_secrets: false` 是派生结论而非自报断言。tracked 摘要实扫：`https?://` 零命中；21 处价格/事件字段命中全是字段名清单，不是数据行；`git check-ignore` 确认 raw 根命中 `.gitignore:113`。

**未覆盖**：§6a 独立对抗 agent 未起（会话级规则禁用），补偿为上述自写植入；未联网复跑真实取数，故摘要所载的 16 次调用与覆盖结论只按其自洽性与落盘证据审，不是重新观测。

## 2026-08-08 追加：首周门 + 前视门放行默认 + KNIFE7 家族五条探针（一刀三部分）

**改了什么**

A（首周门）：`engine/us_short_market_diagnostic_start_receipt.py` 把 `frozen.weekday() >= 5` 改判 `!= _CANONICAL_DECISION_WEEKDAY`（新常量=0，周一），并给 `build_start_receipt` / `issue_start_receipt` 加**必传** `as_of_date`，`issued.date() > as_of` 即拒；`runners/us_short_market_diagnostic_weekly.py::open_clock` 解析今天并显式下传。

B（前视门）：`as_of_date` 的 `= None` 默认从**六**个函数上删除改必传——`us_short_market_diagnostic.py` 的 `_validate_rows` / `validate_window` / `summarize_window` / `summarize_since_inception`，`_aggregator.py::publish_completed_market_diagnostic_window`，`_lifecycle.py::_register_from_records`。后两个是按整类扫出来的，派工没点名。

C（探针）：零代码改动，只在 register 各条目里落探针记录。

连带：fixture 锚点 `date(2026, 1, 2)`（周五）→ `date(2026, 1, 5)`（周一），因为旧 fixture 自己就是 A 要挡的非 canonical 锚点；随之更正四处随锚点走的字面量。测试侧共 ~30 处调用点显式声明 `as_of_date`。

**为什么改**

A：只挡周末从来不够。锚点决定全部 26 周的星期几（钟靠 +7 天推进），放一个周三进来，二十六周就全落在本轨从不决策的那天。`issued_at` 那道更要紧——这道门的**其余检查全部以 `issued_at` 为原点**（锚点不得早于它、不得远离它），所以一个 2099 的 `issued_at` 会把整条地平线一起搬走，重新合法化它们本要禁的回填；而这是本轨唯一不可逆的写。放在铸造时刻而非 `validate_start_receipt`：一份明年读回的 receipt 本就该比读者的钟旧，那时再判会把每一份能用的 receipt 都拒掉。

B：下游写的是 `if as_of is not None`，所以 `= None` 默认**不是安全默认，是把门关掉**——对每一个没想到要传的调用方静默关掉，26 周纯未来日期就是这么发布出去的。改必传之后，真没有 as-of 的调用方必须把 `as_of_date=None` 说出口，读者和 grep 都看得见。

**验证命令**

```
.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 700 discover -s tests -p "test_us_short_market_diagnostic*.py"
python .tools\full_pack_ledger.py run us_short "<trigger>" "receipt:cc1779ba7f3d53507f8481f9" 860 -- discover -s tests -p "test_us_short*.py"
python -B <scratchpad>\plant.py     # A1/A2/B1 三条植入对照，跑完逐字节还原
python -B <scratchpad>\probe_c.py   # C 的四条实跑探针（第五条是静态）
```

**验证结果**

- 验收包 `Ran 415 tests in 390.0s` / `OK` / `receipt:cc1779ba7f3d53507f8481f9`。焦点截止时间由 300s 提到 700s，理由是实测：同包改动前两次为 199.9s / 213.5s，本刀加了约 10 条测试且并发跑别的活，300s 处 `TIMEOUT`。
- 植入三条各**精确**转红、还原逐字节一致：A1 首周门退回 `>= 5` → 首周门测试红；A2 短路 `issued_at` 前视门 → 通知测试红；B1 让 `validate_window` 的 `= None` 长回来 → AST 守卫与必传测试**双双**红。
- C 五条探针全部「已消失」，各带基线对照（例：删 receipt 前 `calendar_week_count=10` 正常返回，删后三个入口全部拒绝，故拒绝来自门不是来自 store 坏了）。
- 全量 ledger 一次（rule 3(a)：B 动了生产 runner 的调用点）——结果见 SESSION_LOG 同日 entry。

**失效的旧结论**

- 「`first_decision_date` 无 canonical 决策周校验、无 as_of、与 `issued_at` 无先后关系」——**部分早已失效**：不早于 `issued_at`（:281）与一年上限（:286）本刀开工前就在，本刀补的是 canonical 周与 `issued_at` 自身在未来两道。引用原文时别照抄「三道全无」。
- 「26 连续日可发布为 26w-1-26」——已失效，`_require_weekly_cadence`（`lifecycle.py:376`）早已在，`gap != 7` 即拒。但它的反向用例**曾硬编码旧锚点**，fixture 一移就悄悄退化成「日期须递增」测试，本刀已改为从 fixture 推导。
- 「KNIFE7 家族那 5 条还 open」——已失效，全部 resolved 并各带探针。
- 「`build_start_receipt(diagnostic_epoch=..., completion_notification=..., first_decision_date=...)` 三参数即可」——已失效，第四个 `as_of_date` 必传。

**下一步注意事项**

- **`load_lifecycle_register` / `persist_settled_weekly_record` 的同名 `as_of_date=None` 默认本刀故意未动**：它们是公开读写口、runner 已各自解析今天下传，改必传要波及约 50 处测试调用点。这是权衡后划在范围外的，不是漏掉；真要收口须单独一刀。
- **探针1 的闭合判据还剩可见性半条未做**：公开 report schema 无 `start_receipt_sha256` 与首/末决策日，拿到成绩单的审计者无从独立复核锚点。已在其条目内如实记着，等用户决定是否另起。
- triage 条**仍不关闭**：Required ② 还剩 2 条未探（`KNIFE7B-CAPSTONE-ROOT-HAS-NO-PRODUCER`、`KNIFE6-CASH-LEG-NEVER-BOUND-TO-ITS-OWN-WEEK`），按派工不在本刀。
- 新增测试后本包墙钟约 390s，已逼近 300s 默认门；下次跑这包记得带 `--timeout-seconds`。
- 钟仍 `not_started`：本刀不开钟、不签发任何 receipt，A 的两道门在真开钟那天才第一次挡真东西。

## 2026-08-08 追加：首周门 + 前视门默认 + KNIFE7 家族探针 审查 verdict（PASS）

**对象**：`0d44a774`（19 文件），即本 handoff 上一节派工的 A/B/C 三段，一轮做完。

**A 首周门**：周末检查换成 canonical 决策周（`_CANONICAL_DECISION_WEEKDAY = 0`）。这比派工写的更到位——原判据只挡周六日，而时钟是「锚点 + 7×N」推出来的，一个周三锚点会让二十六周**全部**落在这条轨从不决策的那一天。另一半是 `issued_at`：`build_start_receipt` 现在必收 `as_of_date` 并拒绝尚未发生的通知。**把这道判在铸造而不是校验，是对的**：一份明年读回的 receipt 本就比读者的钟老，放在校验侧会把每一份曾经合法的 receipt 都判死。审查方探针：周一接受（控制组）、周二/三/五/六全拒且报 canonical 周那句、周一但早于通知拒「precedes the completion notification」、`issued_at=2099` 铸造时拒。

**B 前视门**：六处 `as_of_date=None` 默认**删除**而非改成安全值，调用方须显式写 `as_of_date=None`——安全默认仍会静默生效，删掉才逼出显式声明；配 AST 守卫钉住不得再长回来。审查方实读 aggregator 的 `publish_completed_market_diagnostic_window` 确认是删默认，并探到 `validate_window()` 漏传即 `TypeError`。顺带修的 fixture 值得记：它原来的锚点是周五，**夹具自己就是 A 要拒的那种非规范锚点**；另有一条既有反向测试硬编码了旧锚点，不改它会从「二十六天不是二十六周」悄悄降级成「日期必须递增」。

**C KNIFE7 家族五条**：全部给出可复现探针并翻 resolved，且没有一条借探针之名顺手改代码。其中 `HOLLOW-NOTIFICATION-TEST` 那条尤其有意思——原测试三个子例都传 `diagnostic_epoch="e1"`，而 schema 最短 3 字符，所以三例其实全死在 epoch 上、根本没测到通知；**审查方自己第一轮探针也踩了同一个坑**（用 `'e1'` 导致四个锚点用例全报 schema 错），可算独立复现了该 finding 的机制。

**验证边界**：验收超集 `Ran 297 in 83.3s PASS receipt:4ec902273372b1f4f96a5660`。§6a 独立对抗 agent 未起（会话级规则禁用），补偿为上述自写探针；C 的五条只读其条目内的探针记录、未逐条复跑。首轮包跑到一半别窗把 master 从 `0d44a774` 推到 `f8ec16fe`，收据被 runner 以「code state changed during focused run」拒绝（测试本身 297 全绿），故在自己树同步后重跑一次取得绑定收据。

## 2026-08-08 追加：演练台 O(n²) 的真正位置——不在读取链内部，在它的调用方

**改了什么**：三腿，同一缺陷类一次扫净，**不加任何缓存**。
1. `engine/us_short_market_diagnostic_weekly_producer.py::diagnostic_store_state` 由「先 `load_lifecycle_register` 再 `load_settled_weekly_records`」改为一次 `load_register_and_settled_records`。
2. 同文件 `next_week_inputs` 把它已经验过的 `receipt` 与 `settled_records` 一并交回；`_target_week` 改用 `inputs["settled_records"]`，不再为查一个前周 NAV 重读整店。
3. `runners/us_short_market_diagnostic_weekly_fetch.py` 三处 `receipt = diagnostic_store_state(...)["receipt"]` 改取 `inputs["receipt"]`；`_prior_valuation_date` 由 `root` 参数改为必传 `settled_records`（三个调用点各自显式下传）。

**为什么改**：上一刀把两个公开读者合并成 `load_register_and_settled_records`，**却没改最热的调用方**。`load_lifecycle_register` 与 `load_settled_weekly_records` 现在是同一个 tuple 的两半，`diagnostic_store_state` 一次调用因此把整店读校两遍——而它占全部整店读校的 63%。其余两腿同理：调用方刚把整店读校完，紧接着又为一个 receipt、一个前周 NAV 各重读一遍。

**先量后改**（这是本刀最该被复用的做法）：用计数探针裹住 `load_register_and_settled_records`，按 `traceback` 归因到调用链，跑 8 周演练台。没有这一步我会照代码直觉只看到「每周 3 次」，实际是 **22.8 次**。

**验证命令**
```
python -B <scratchpad>\count_reads.py 8      # 每周整店读校次数 + 累计记录校验条数
.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 600 -v tests.test_us_short_market_diagnostic_rehearsal --durations 3
.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 600 discover -s tests -p "test_us_short_market_diagnostic*.py"
python .tools\full_pack_ledger.py run us_short "<trigger>" "receipt:<token>" 860 -- discover -s tests -p "test_us_short*.py"
```

**验证结果**
- 每周整店读校 **22.8 → 11.2 次**（182→90，−51%）；累计记录校验 **756 → 384 条**（−49%）。
- 模块墙钟 **176.0s → 109.4s**（−38%）；`test_twenty_six_weeks_reach_the_scorecard` **121.9s → 71.0s**（−42%）；29 测全绿。对照：建成时手记 52s，退化峰值 231.6s。
- 「校验没被跳过」对照：新增 `StoreStateTest::test_reusing_the_validated_records_did_not_stop_them_being_validated`——干净跑一轮后盘上篡改第 2 周 NAV，`diagnostic_store_state` 必须报 `broken` **且 `records` 为空**、`next_week_inputs` 必须抛。两条植入各精确转红、还原逐字节一致（P1 坏店仍 `running`+records → 4 测红；P2' `settled_records` 装未校验的盘上记录 → 12 测红）。
- 全量 ledger 一次（改动落在 shared engine + 生产 runner）——结果见 SESSION_LOG 同日 entry。

**失效的旧结论**
- 「真正的成本在 `load_settled_weekly_records` 每次重跑 `_load_records_for_register`」——**已失效**。那一层上一刀就修完了；剩下的成本全在**调用方重复调用**，不在读取链内部。照旧结论继续往读取链里找会白费一轮。
- 「方向是给这条读取链一个单次运行内的一致性缓存」——**没有采纳，也不需要**。三腿都是「把手里已经验过的东西传下去」，跨调用零缓存，因此不承担缓存的失效风险，也不需要证明命中率。
- 「lane 剩余墙钟由 `test_us_short_discovery_conformance_executable`（652s）主导」——已失效。并行 runner 落地后地板换成了本模块（主树实测 `WALL_CLOCK_FLOOR 179.5s of 815.3s`），本刀正是打这个地板。

**下一步注意事项**
- `next_week_inputs` 的返回**多了两个键**（`receipt`、`settled_records`）。它不进任何制品、无键集合断言，但写新消费者时别假设它只有原来四个键。
- `_prior_valuation_date` 的 `root` 参数**没了**，改必传 `settled_records`；新调用点必须自己拿到已验记录再传，别退回自己去 load。
- 首版植入对照 P2 打歪（`list(... or [])` 语义等价 → 全绿）。**对照全绿要当成「打歪了」而不是「覆盖充分」**，这是本会话第四次踩同一个坑。

## 2026-08-08 追加：诊断轨读取链去重的审查结论（`adab3216`，PASS）

**审查对象**：`adab3216`，工作树 `D:\cnhea\Stock-wt\us-short_r28`（当时领先 master 一个提交，工作区干净、无 untracked）。改动面 = `engine/us_short_market_diagnostic_weekly_producer.py`、`runners/us_short_market_diagnostic_weekly_fetch.py` 两个生产模块 + 两个测试文件（纯新增）+ 四份文档。

**成立的部分**：① `diagnostic_store_state` 由两次读店改一次，是取值等价——`load_lifecycle_register` / `load_settled_weekly_records` 本就是 `load_register_and_settled_records` 的两半（`lifecycle.py:591-604`）；② `next_week_inputs` 交回它已验的 `receipt` / `settled_records`，`_target_week` 与 `weekly_fetch` 三处改用之，实测三项取值与旧读法逐项相等；③「跨调用零缓存」属实，读取链无记忆化，下一次调用仍整店读盘重校；④ runner 层仍 fail-closed（reviewer 自写探针，控制组先绿）：盘上篡改第 2 周 NAV 后 `next_week_identity` 死在门上而非拿旧数据继续；⑤ `_prior_valuation_date` 的 EXEMPT 理由属实——私有、三个调用点都在本模块、都传门刚返回的东西、不在发布路径。

**拦下的一条**：无。两条 Optional 记在 `docs/system_risk_register.md`（本刀造出的两个孤儿 import；`_target_week` 的 EXEMPT 理由「reads through the gated loader」已随本刀失真）。

**验证命令与结果**：焦点超集包 `.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 700` 跑 `tests.test_us_short_market_diagnostic_` 的 `weekly_producer` / `authorization_conformance` / `weekly_advance` / `weekly_runner` / `rehearsal` / `lifecycle` 六模块 → `Ran 179 in 46.780s OK`、`receipt:7a76f3fd80e257e086218b22`（覆盖被改函数的全部生产调用点；47s 本身也旁证了去重生效）。全量按 AGENTS rule 4 不由 reviewer 重跑，引执行方 ledger 记录（`.tools/state/full_pack_ledger.json` 实含 `tests=5623 / 835.6s / receipt:b65e753874f6f96f4e9d2ca9`）。

**验证边界**：未起 §6a 独立对抗 agent——rule 8 低危档（dormant comparison-only 诊断轨，不触及选股 / core_score / veto / sizing / PIT-进选股 / 真钱 / secret / live provider）；未联网、未真跑取数；性能数字（22.8→11.2、176.0→109.4s）为执行方实测，reviewer 未复跑计数探针，只独立确认了「等价 + 不省检查」这两件决定正确性的事。

**失效旧结论**：`R-USSHORT-26W-DIAG-REHEARSAL-GOT-4-5X-SLOWER-WHEN-IT-STARTED-USING-THE-REAL-FETCH-ENTRY` 原「方向是给读取链一个单次运行内的一致性缓存」已被推翻——真正的 O(n²) 在调用方重复提问，不在读取链内部，最终修法未引入任何缓存。

## 2026-08-08 追加：打 `test_us_short_discovery_conformance_resources`（199.5s 地板）——量完了，没有不付代价的加速

**改了什么**：只有三处可证等价的折叠（`fetch_web.py:946/948`、`fetch_x.py:186/188`、`fetch_x.py:594/615`：同一路径连问两遍 `_gitignored`，第二次只可能返回 True）。**没有别的代码改动**——因为再往下走每条路都要付代价，那是用户的决定不是我的。

**为什么没有更多**：见 register 该条目 ①–⑦。四个关键实测：
1. 该模块**在串行尾巴里**（`serial_tail_modules` 实算命中；尾巴在波次后逐个跑），所以它的 199.5s 1:1 加进墙钟，**而且拆成两个模块是死路**——两半都会排队。
2. 成本 = 2 × 78.9s（223 条真测试正逆序各一遍）+ 约 42s 自身开销；**62% 集中在 `test_us_short_weekly_capstone_soft_discovery` 一个模块**。
3. 那个模块的热点是 `_gitignored` 每次 spawn `git check-ignore`（17.6ms × 130 次/测），重复率 62%。
4. **缓存它不安全**：该模块 `setUp:102` 用 `temporary_provider_directory(ROOT)` 在仓库内真造 `.gitignore`，同一路径的 ignored 性在进程内确实会变；而它是防 provider 原始数据落进 tracked 位置的 fail-closed 隐私门。

**验证命令**
```
cd .tools && python -c "import parallel_lane_runner as m; print(m.serial_tail_modules([...], [<repo>]))"   # ① 尾巴归属
python -B <scratchpad>\probe_d.py                                    # ② selected 条数 + 单遍耗时 + 按模块归因
python -B -c "<cProfile 单测>"                                        # ③ subprocess 次数与 _gitignored 占比
.tools\run_unittest_with_repo_pythonpath.cmd tests.provider.test_us_short_llm_theme_discovery_fetch_web tests.provider.test_us_short_llm_theme_discovery_fetch_x_merge tests.provider.test_us_short_llm_theme_discovery tests.provider.test_us_short_weekly_capstone_soft_discovery
```

**验证结果**：折叠后 `Ran 217 tests / 74.0s / OK`。**收益在噪声内**（最慢那条 13.4s → 13.7s）——如实记，别人别再重量一遍。另外两条猜测也已实测排除：`snapshot()` 不是成本（`state/us_short` 现有 0 个文件）；逐条跑不会重复付 `setUpClass`（该模块只有 `setUp`）。

**失效的旧结论**
- 「照上一刀的办法把它拆成独立模块就能并行」——**已失效**。上一刀那次有效是因为拆出来的两半分别落在波次里；这次两半都在串行尾巴里，排队总时间不变。
- 「地板只是最长模块，加 worker 无用但结构上可并行」——**已失效**，它是尾巴成员，本来就不参与波次。

**下一步注意事项**
- 四条路的代价写在 register ⑦，等用户裁决。执行方推荐 **(D) 另起一刀专打 `test_us_short_weekly_capstone_soft_discovery`**：它在 lane 跑一遍、在 D 轴再跑两遍，**任何提速都是 3 倍杠杆**，且不碰任何 fail-closed 门。
- **(B)（砍掉 D 轴正序那遍）是真实降强度**，别当成纯提速：会丢掉「正序跑完一遍后仓库根是干净的」这个断言。

## 2026-08-08 追加：triage Required ② 补完最后两条 + 上一轮两条 Optional 收口

**改了什么**：① `engine/us_short_market_diagnostic_weekly_producer.py` 删掉读取链去重那一刀留下的两行孤儿 import（`load_lifecycle_register` / `load_settled_weekly_records`），只留 `load_register_and_settled_records`；② `tests/test_us_short_market_diagnostic_authorization_conformance.py` 把 `_target_week` 的豁免理由从「reads through the gated loader」改写成它现在真正在做的事（读那同一份 gated inputs 携带的已结周记录、自己不碰店），并写明理由本身为什么必须跟着改。两条 triage 探针**只探不改**，未动任何代码。

**为什么改**：豁免理由是这道授权门唯一的审计线索——写错会让下一个人以为 `_target_week` 仍自己经门查授权；孤儿 import 是上一刀的连带残留。两者都非材料性，故上一轮记 Optional 而非 Required。

**验证命令**：焦点超集包 `.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 700` 跑 `weekly_producer` / `authorization_conformance` / `weekly_advance` / `weekly_runner` / `rehearsal` / `lifecycle` 六模块；探针与植入脚本均 `python -B` + `PYTHONDONTWRITEBYTECODE=1`，跑完 `git status` 无残留。

**验证结果**：见 `docs/SESSION_LOG.md` 同日 `修复` 条的 `Verify`（单一来源，此处不复述数字）。植入对照：删掉 `_target_week` 的豁免整条 → 授权一致性守卫精确转红并点名该函数，还原后 sha256 逐字节一致。

**两条探针的结论（正文与实测输出在 register 各自条目）**：`KNIFE7B-CAPSTONE-ROOT-HAS-NO-PRODUCER` 与 `KNIFE6-CASH-LEG-NEVER-BOUND-TO-ITS-OWN-WEEK` 描述的机制**都已不存在**，各自翻 `resolved`。前者的字面闭合判据（把默认根写进 `resolve_capstone_context`）被有意否决且理由成立——在该模块点名私有根会把它约 90 个函数拖进诊断授权论域；改为在 stage adapter 惰性解析默认，功能等价而不扩大授权面。

**失效旧结论**：`R-USSHORT-26W-DIAG-OPEN-LIST-TRIAGE-20260807` 的「本轨还剩 N 条待办」自此不再适用——①8 条、②7 条、③2 条全部有终态，该 triage 条目已关闭。此后再引用剩余条数，须按当时 register 现状重新核，不得沿用 2026-08-07 的清单。

**下一步注意**：本轨近端唯一的实质待建件是刀 5 后半段（ETF 股息 sidecar 生产器 + 挂进 capstone 已 gated 的 fetch 阶段 + 给 `settle_captured_week` 补 sidecar 绑定参数），三件必须同刀落，否则每周一键照跑而 VTI 永远升不到 `total_return_evaluable`。

## 2026-08-08 追加：打 `test_us_short_weekly_capstone_soft_discovery`（用户选 (D)，3 倍杠杆兑现）

**改了什么**：一处，测试侧。把这个类**自己早就写好、却只在一个方法里用**的 seam `_owned_private_root_git_check` 从 `with` 提到 `setUp`（用 `self.enterContext`），并把原来那处 `with` 去掉（已被 setUp 覆盖，同轮把块 dedent 回去）。另加一条钉住 seam 契约的对照测试。

**为什么改**：整模块 cProfile（59.3s）按仓库函数归因，第一名是 `us_short_llm_theme_discovery_fetch_web.py:548 _gitignored`——**635 次调用、14.23s、占整模块 24%**，每次都 spawn 一个 `git check-ignore`（单次 17.6ms）。

**为什么这样改是安全的（关键，别读成「为了快而放宽」）**：seam 在入口用**真 git** 证明 `self.temp_root` 确实被忽略，之后只为**该已证明根内部**的路径回答；根外一律委派回真实实现。**git 语义下被排除目录的整棵子树都被排除**，所以已证明被忽略的根内不可能存在「未被忽略」的路径——对根内答 True 是**真答案**。生产侧的 containment / 后缀 / 精确 slot 检查一条没动。真 git 探针由 635 次降到每测 1 次。

**验证命令**
```
.tools\run_unittest_with_repo_pythonpath.cmd -v tests.provider.test_us_short_weekly_capstone_soft_discovery --durations 3
.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 600 -v tests.test_us_short_discovery_conformance_resources
python .tools\full_pack_ledger.py run us_short "<trigger>" "receipt:<token>" 860 -- discover -s tests -p "test_us_short*.py"
```

**验证结果**
- 模块 **62.7s → 25.0s（−60%）**，且是在多了一条对照测试（51→52 测）之后；最慢一条 **16.0s → 2.9s**。
- 地板模块 `test_us_short_discovery_conformance_resources` **199.5s → 130.0s（−35%）**——杠杆如预期（D 轴跑两遍 + lane 跑一遍）。
- 对照：新增 `test_the_owned_root_seam_answers_only_for_the_root_it_proved`，自己重做真 git 证明、断言 owned root 内答 True 而**根外 `docs/`、`runners/` 仍答 False**。两条植入各转红、还原逐字节一致：P1 让 seam 对任何路径答 True → 该对照红；P2' 把 owned root 指向 tracked 的 `docs/` → **52 条全红**（证明那道真 git 证明承重）。
- 全量 ledger 一次——结果见 SESSION_LOG 同日 entry。

**失效的旧结论**
- 「`_gitignored` 只占约 4%、免费折叠后收益在噪声内」——**已失效**。那是从**单条测试**的 cProfile 估的；整模块归因是 **24%**。教训：单测 profile 不能外推到模块，模块级归因才是决策依据。
- 「这条只能在 fail-closed 门上做取舍」——**已失效**。取舍是假的：类里本来就有一个既安全又快的 seam，只是没被用起来。**先找这个类自己有没有现成答案，再去动共享代码**。

**下一步注意事项**
- 这个 seam 现在对**整个类**生效。往这个类里加测试时，若要断言「某路径不被忽略」，**路径必须在 `self.temp_root` 之外**（根内 seam 会答 True，且那是真答案）。
- `test_the_owned_root_seam_answers_only_for_the_root_it_proved` 是这条边界的守卫，别删。
- 首版 P2 植入又打歪一次（放宽一个本来就成立的断言 → 全绿）。**对照全绿=打歪，不是覆盖充分**——本会话第五次。

## 2026-08-09 追加：Knife5 后半段收口（OPEN-NOT_VERIFIED）

### 改了什么

- 新增 `D:\cnhea\Codex\worktrees\cb59\Stock\engine\us_short_market_diagnostic_etf_sidecar.py`：纯 builder，固定 VTI/IWB/SPY/QQQ 与 `dividends`、`splits`、`daily_adjusted`、`daily_unadjusted` 四类 source binding；按 ETF 局部输出 coverage/reason，不把缺失伪装成 total return。
- 新增 `D:\cnhea\Codex\worktrees\cb59\Stock\runners\us_short_market_diagnostic_etf_sidecar_fetch.py`：复用现有 Massive capture helper、现有 per-execution 授权语义；标准化 sidecar 路径、请求前 logical/physical budget、raw gitignored、落盘前安全扫描、O_EXCL 幂等。
- `D:\cnhea\Codex\worktrees\cb59\Stock\runners\us_short_market_diagnostic_weekly_fetch.py` 在既有 fetch 后生产同周 sidecar，并给 `settle_captured_week(total_return_sidecar_path=...)` 自动绑定同周路径；`D:\cnhea\Codex\worktrees\cb59\Stock\runners\us_short_weekly_capstone.py` 仍只使用 gated `market_diagnostic_fetch`。
- `D:\cnhea\Codex\worktrees\cb59\Stock\engine\us_short_market_diagnostic_total_return.py` / `us_short_market_diagnostic_local_adapter.py` 保留 misaligned/no-sidecar 的 price-only 语义；测试与 inventory 快照同步。

### 为什么改

- `D:\cnhea\Codex\worktrees\cb59\Stock\docs\system_risk_register.md` 的 2026-08-08 裁决选 B：先升基准侧 ETF total return，不做 C（模型持仓股息）。若只造 sidecar 不接 weekly fetch/settle，用户每周一键仍不会得到 `total_return_evaluable`，所以三件必须同刀落。
- 实现遵守六条硬约束：只挂既有 gated stage；预算发请求前判；not_started 零网络零字节；缺 key/厂商失败/分页或对账问题只局部降级；异常只留类名、raw 仅 gitignored `provider_samples/`；同周重跑不重抓不覆盖。

### 验证命令

```text
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m py_compile engine/us_short_market_diagnostic_benchmark_packet.py engine/us_short_market_diagnostic_etf_sidecar.py engine/us_short_market_diagnostic_local_adapter.py engine/us_short_market_diagnostic_total_return.py runners/us_short_market_diagnostic_etf_sidecar_fetch.py runners/us_short_market_diagnostic_rehearsal.py runners/us_short_market_diagnostic_weekly.py runners/us_short_market_diagnostic_weekly_fetch.py runners/us_short_weekly_capstone.py tests/test_us_short_market_diagnostic_etf_sidecar.py tests/test_us_short_market_diagnostic_local_adapter.py tests/test_us_short_market_diagnostic_rehearsal.py tests/test_us_short_market_diagnostic_weekly_advance.py
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.test_us_short_market_diagnostic_etf_sidecar tests.test_us_short_market_diagnostic tests.test_us_short_market_diagnostic_benchmark_packet tests.test_us_short_market_diagnostic_total_return tests.test_us_short_market_diagnostic_local_adapter tests.test_us_short_market_diagnostic_rehearsal tests.test_us_short_market_diagnostic_weekly_runner tests.test_us_short_market_diagnostic_weekly_advance tests.test_us_short_model_paper_capstone_wiring tests.test_us_short_market_diagnostic_authorization_conformance tests.test_us_short_capstone_checkpoint tests.schema.test_us_short_market_diagnostic_26w_schemas tests.provider.test_us_short_market_diagnostic_etf_capture tests.provider.test_us_short_weekly_capstone tests.test_us_short_test_io_inventory
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe .tools\full_pack_ledger.py run us_short "Knife5 ETF sidecar producer + gated fetch + settle binding" "receipt:659666f25a0aad1ff58cd333" 860 -- discover -s tests -p "test_us_short*.py"
```

### 验证结果

- 固定主 Python 编译通过；最终 focused `303/303 OK`，receipt `receipt:659666f25a0aad1ff58cd333`；最终 full lane `PASS 5630/5630`，`COUNT_GATE discovered=5630 ran=5630`，442.3s/860s；ledger static `diff_check=PASS`、`py_compile=13`。
- A–F 自审完成。反向红测三项均按预期转红并还原：预算门挖空→首请求测试红；窗口对齐门挖空→4 个 ETF joint-evaluable 断言红；settle 绑定挖空→sidecar path 断言红。inventory `22/22 OK`，新增测试 raw 已隔离到临时 gitignored provider root，未增 allowlist 项。
- 首轮 full 曾因新增测试模块使 inventory `306→307` 而 fail-fast；已用仓库生成器同步 `D:\cnhea\Codex\worktrees\cb59\Stock\docs\us_short_test_io_inventory_20260801.json`，并重打最终 full。未执行真实 Massive provider、真实 model-paper、开钟、账户写入或 Ship gate。

### 失效的旧结论

- 「总回报 sidecar 全仓无 producer」：对本刀前的历史基线成立，已被上述 producer 改写；「每周一键没有 sidecar 绑定参数」也已由 `settle_captured_week` 参数与同周自动路径改写。
- 「桌面 §9.1 的状态行仍是捕获段建成之前」：仍只作索引，未作为本轮审查对象，也未修改 `C:\Users\cnhea\Desktop\usshort-compare.md`；本轮验收以 register 2026-08-08 裁决和桌面 §3.5 五项清单为准。
- 「只升基准必须等真实周」：用户 2026-08-08 已裁决现在做 B；真实周仍是后续测 X 的证据，不是本刀实现前置。

### 下一步注意事项

- 当前 Required `R-USSHORT-26W-DIAG-BOTH-SIDES-IGNORE-DIVIDENDS-AND-THAT-IS-NOT-NEUTRAL` 仍为 `OPEN-NOT_VERIFIED`，交给 Claude Code 独立复审；本工作树不 commit。独立审查 PASS 后由 reviewer/committer 按项目规则处理提交。
- 以后每周只跑 capstone 一键：sidecar 复用既有 `market_diagnostic_fetch` 授权；缺 key/失败只落 degraded sidecar、周任务继续，不能新增确认或手工补参数。sidecar 合格后才可让消费器给出 `total_return_evaluable`，不合格仍是 price-only。
- 本刀不启动 26 周计时、不产生真实成绩、不升级 C、不改变选股/操作建议/NAV/账户/Ship gate；开钟仍是独立的 `设计完成` 通知 + `diagnostic_start_receipt` 一次性动作。

## 2026-08-09 追加：Knife5 后半段 ETF 股息 sidecar 的审查结论（FAIL）

**审查对象**：`D:\cnhea\Codex\worktrees\cb59\Stock` 的未提交工作（17 改 + 3 新增；新增 = `engine/us_short_market_diagnostic_etf_sidecar.py` 507 行、`runners/us_short_market_diagnostic_etf_sidecar_fetch.py` 420 行、其测试 170 行）。该树当时落后 master 2 个提交且不干净，故未同步、按现状审。

**成立的部分**：不碰选股/操作建议/仓位/NAV/Ship gate；密钥与 raw 卫生（两个写入根都 gitignored，写前正向确认，异常只留类名，落盘前派生扫描）；不新增授权门；dormant 零网络；预算在发请求之前判；总回报是从 source-bound 事件真复算而非照抄厂商数；`unavailable` 不导出 dividend sidecar SHA；窗口/epoch/周号/估值日四道独立绑定；sidecar JSON 幂等。`windows_aligned` 那处修复方向正确且其测试有牙（植入对照四 ETF 全红）。

**拦下的**：四条 Required（两 P1 两 P2）+ 四条 Optional，正文全部在 `docs/system_risk_register.md` 同日节内。两条 P1 一句话：**读不到股息被当成没有股息，还升级成总回报**；**一次中断让那周永久取不回，且把现金腿一起卡死**。

**验证命令与结果**：焦点超集 `discover -s tests -p "test_us_short_market_diagnostic*.py"`（`--timeout-seconds 900`）→ `Ran 422 in 342.779s OK`、`receipt:0fb32a4a99b6598dd1b44716`。全量按 AGENTS rule 4 不由 reviewer 重跑，引执行方 ledger 记录（`tests=5630 / 442.3s`）。reviewer 自写探针与植入对照见 SESSION_LOG 同日条的 `Verify`。

**验证边界**：§6a 独立对抗 agent 已跑（read-only、离线、未改仓库）；其结论我不照单全收——F1/F3/F2 逐条回源码复核后才写进 register，其余按其自陈的覆盖缺口处理。未联网、未真跑 provider。`fetch_next_week` / `settle_captured_week` 未在真实 lifecycle + model-paper store 上端到端跑过（私有店夹具与并发测试抢跨进程锁），多周 `due` 循环、`no_count` 路径与 O3 的实际表现是源码推理而非实跑——这是本轮**明确未覆盖**的维度。

**失效旧结论**：register `R-...-BOTH-SIDES-IGNORE-DIVIDENDS-AND-THAT-IS-NOT-NEUTRAL` 里 2026-08-09 那条「缺失局部降级、写一次幂等均由代码钉住」**不成立**，已被上述两条 P1 推翻；该条继续 `OPEN-NOT_VERIFIED`，不得据此翻 resolved。

## 2026-08-09 追加：Knife5 后半段审查 Required + Optional 收口（OPEN-NOT_VERIFIED）

### 改了什么

- `D:\cnhea\Codex\worktrees\cb59\Stock\engine\us_short_market_diagnostic_etf_sidecar.py` 将不可读/空股息拒绝为 price-only、把 Decimal 行异常局部降级、并把局部价格区间收敛为不升级的 sidecar；`D:\cnhea\Codex\worktrees\cb59\Stock\engine\us_short_market_diagnostic_total_return.py` 令 `windows_aligned` 必传且只接受真 `bool`。
- `D:\cnhea\Codex\worktrees\cb59\Stock\runners\us_short_market_diagnostic_etf_capture.py` 用 canonical raw 身份去除 run-scoped `observed_at`；`D:\cnhea\Codex\worktrees\cb59\Stock\runners\us_short_market_diagnostic_etf_sidecar_fetch.py` 预拒绝 stale `as_of_date`、隔离 raw 冲突；`D:\cnhea\Codex\worktrees\cb59\Stock\runners\us_short_market_diagnostic_weekly_fetch.py` 只在匹配周绑定成功后消耗显式 sidecar。
- 在既有测试模块增补四条 Required、O1–O4 和 interval 回归；官方 inventory 生成器同步 `D:\cnhea\Codex\worktrees\cb59\Stock\docs\us_short_test_io_inventory_20260801.json`，没有扩张 allowlist。

### 为什么改

- Claude 审查指出：不可读股息会被伪装为零、一次中断会毒化该周 raw、裸 `DecimalException` 会中止四 ETF，公开 builder 还保留默认放行。四项都会违背每周一键只局部降级、不得虚报 `total_return_evaluable` 的约束；详细 Required 正文和状态只在 `D:\cnhea\Codex\worktrees\cb59\Stock\docs\system_risk_register.md`。

### 验证命令

```text
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.test_us_short_market_diagnostic_etf_sidecar tests.test_us_short_market_diagnostic tests.test_us_short_market_diagnostic_benchmark_packet tests.test_us_short_market_diagnostic_total_return tests.test_us_short_market_diagnostic_local_adapter tests.test_us_short_market_diagnostic_rehearsal tests.test_us_short_market_diagnostic_weekly_runner tests.test_us_short_market_diagnostic_weekly_advance tests.test_us_short_model_paper_capstone_wiring tests.test_us_short_market_diagnostic_authorization_conformance tests.test_us_short_capstone_checkpoint tests.schema.test_us_short_market_diagnostic_26w_schemas tests.provider.test_us_short_market_diagnostic_etf_capture tests.provider.test_us_short_weekly_capstone tests.test_us_short_test_io_inventory
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe .tools\full_pack_ledger.py run us_short knife5_post_review_sidecar_required_repair receipt:035dccced54a511e77f9d55a 860 -- discover -s tests -p test_us_short*.py
```

### 验证结果

- fixed Python 反向验证四项均按预期转红后逐字还原；focused `312/312 OK`（`receipt:035dccced54a511e77f9d55a`）。
- full lane `5639/5639 PASS`、373.2s/860s，`COUNT_GATE discovered=5639 ran=5639`，ledger static diff/py_compile PASS。未执行真实 provider、真实 lifecycle/model-paper store、开钟、账户写入或 Ship gate。

### 失效的旧结论

- 「`empty` dividend family 足以代表零股息并可升格」与「raw 页带 run-scoped `observed_at` 仍能天然幂等」均失效；前者会虚报 total return，后者会使中断周无法重跑。
- 「`windows_aligned` 留默认不会造成后续调用点放行」也失效；公开入口的放行门必须强制调用方显式作决定。

### 下一步注意事项

- 四条 Required 和既有 `R-USSHORT-26W-DIAG-BOTH-SIDES-IGNORE-DIVIDENDS-AND-THAT-IS-NOT-NEUTRAL` 均为 `OPEN-NOT_VERIFIED`，交 Claude Code 独立审查；本工作树不 commit。
- 后续不得用实际 provider/lifecycle 结果替代上述审查，也不得新增确认入口、回填零股息或绕开同周/epoch/window/valuation-date 绑定；桌面 `C:\Users\cnhea\Desktop\usshort-compare.md` 仍只作索引，未修改。

## 2026-08-09 追加：Knife5 后半段修复轮的复审结论（FAIL，同类兄弟腿）

**审查对象**：`D:\cnhea\Codex\worktrees\cb59\Stock` 的未提交修复轮（19 改 + 3 新增）。

**成立的部分**：上一轮四条 Required 全部按类修完且**没有过度修正**——dividends 收紧到必须 `covered`，而 splits 真正为空时仍然评估通过（这是我上一轮点名的陷阱，没踩）；敌意 Decimal 只降所属 ETF；raw 包裹层去掉 run-scoped 时间戳后同页二次写入不再冲突，冲突也改成局部降级；对齐门改必传并加类型硬拒。O1–O4 一并实现，新测试模块 4→11 条。

**拦下的**：四条新 Required，**三条是已修类的兄弟腿**——修了被点名那条，相邻那条没动。正文在 `docs/system_risk_register.md` 同日节。

**整类修法（写在这里是因为它决定下一轮怎么做）**：`capture._result_rows` 返回 `(key, rows)`，真空返回 `key='results'`、读不懂返回 `key=None`；`_page_result:332` 用 `_, page_rows = ...` 把这个判据丢了。捡回来即可**一次盖住四个 family**，既不放过 splits 也不误伤正常无拆股周——不需要给每个 family 各写特例。

**验证命令与结果**：焦点超集 `discover -s tests -p "test_us_short_market_diagnostic*.py"`（`--timeout-seconds 900`）→ `Ran 431 in 359.211s OK`。全量按 rule 4 引执行方 ledger（`tests=5639 / 373.2s`）。探针与植入对照见 SESSION_LOG 同日 `Verify`。

**验证边界**：§6a 独立对抗 agent 已跑（read-only、离线）。其「真实 provider body 自带 per-request id、故 payload 漂移仍会永久冻住降级态」的主张，本树无 `provider_samples/` 可查证，记 **NOT_VERIFIED**；要定它只需一份真实 raw 页。其「sidecar 排在 cash 之前故失败连坐现金腿」「`mkdir` 在 try 之外故 OSError 逃逸」两条我读源码认可但未自跑复现，留执行方复核。`settle_captured_week` / capstone 端到端仍未在真实 lifecycle + model-paper store 上跑过。

**给下一轮的教训（本轮最值钱的一条）**：上一轮我给出的类边界是「按 family 分档」，方向对但**不够彻底**——它默许了「一个 family 一套特例」，于是修复方只改了被点名的 dividends。正确的类边界是「读不懂 ≠ 没有」这个**判据本身**，而那个判据仓库里早就算好了、只是被丢掉。**下次给类边界时，先找现成的判别器，再谈分档。**

## 2026-08-09 追加：Knife5 兄弟腿 Required 收口（OPEN-NOT_VERIFIED）

### 改了什么

- `D:\cnhea\Codex\worktrees\cb59\Stock\runners\us_short_market_diagnostic_etf_capture.py` 保留 `_result_rows` 的 key，把真实空结果与 `unreadable_body` 分开；四个 family 的不可读 body 均 fail-closed，`splits` 真空正向控制仍放行。
- `D:\cnhea\Codex\worktrees\cb59\Stock\engine\us_short_market_diagnostic_etf_sidecar.py` 对精确重复股息去重、同日冲突标 invalid；split ratio 加 Decimal finite + float representable 双门；无拆股窗口实际比较 adjusted/unadjusted close。schema、capture/sidecar 测试同步。

### 为什么改

- Claude Code 新一轮指出四个兄弟腿仍可把不可读当真空、重复股息重复计数、Decimal 在 float 出口变成 `inf/0.0`、以及只比日期不比价格。四项都会让 sidecar 错贴 `total_return_evaluable` 或污染总回报，违反本 register 的 08-08 裁决与六条硬约束。

### 验证命令

```text
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m py_compile engine/us_short_market_diagnostic_etf_sidecar.py runners/us_short_market_diagnostic_etf_capture.py tests/test_us_short_market_diagnostic_etf_sidecar.py tests/provider/test_us_short_market_diagnostic_etf_capture.py
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.test_us_short_market_diagnostic_etf_sidecar tests.provider.test_us_short_market_diagnostic_etf_capture
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.test_us_short_market_diagnostic_etf_sidecar tests.test_us_short_market_diagnostic tests.test_us_short_market_diagnostic_benchmark_packet tests.test_us_short_market_diagnostic_total_return tests.test_us_short_market_diagnostic_local_adapter tests.test_us_short_market_diagnostic_rehearsal tests.test_us_short_market_diagnostic_weekly_runner tests.test_us_short_market_diagnostic_weekly_advance tests.test_us_short_model_paper_capstone_wiring tests.test_us_short_market_diagnostic_authorization_conformance tests.test_us_short_capstone_checkpoint tests.schema.test_us_short_market_diagnostic_26w_schemas tests.provider.test_us_short_market_diagnostic_etf_capture tests.provider.test_us_short_weekly_capstone tests.test_us_short_test_io_inventory
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe .tools\full_pack_ledger.py run us_short "Knife5 ETF sidecar sibling-leg Required closure" "receipt:f07a38a14cc7f1b1ca72af8b" 860 -- discover -s tests -p "test_us_short*.py"
```

### 验证结果

- 固定主 Python 编译通过；四个 mutation controls 均按预期转红后还原。最新 focused `318/318 OK`，receipt=`receipt:ecfba8fbba10da8ff3a29e0b`。
- full lane 两次均在并行矩阵的 `tests.test_us_short_discovery_conformance_resources` 失败，`discovered=5645`、`ran=4469`；该模块单跑 `1/1 OK`。因此本轮 full-lane 是 `NOT_VERIFIED`，没有把单跑绿灯写成全量 PASS；失败与本刀改动无代码交集。
- 未执行真实 Massive/provider、真实 lifecycle/model-paper、开钟、账户写入或 Ship gate；无 commit。inventory 已用官方生成器同步，文档门待最终重跑后记录。

### 失效的旧结论

- 「四个 family 的无 rows 都可按 `empty` 处理」失效：现在必须区分真实真空与不可读 body。
- 「事件逐行 append 不会污染总回报」失效：精确重复必须去重，同日冲突必须 invalid；「Decimal finite 就足够安全」也失效，float 出口仍需 representable 门。
- 「日期集合相同即可标记 `adjusted_unadjusted_reconciled`」失效：无拆股窗口还必须比较 close 数值。旧 handoff 中 prior receipt 的 full PASS 只属于旧代码状态，不是本轮 full-lane 证据。

### 下一步注意事项

- 四条新 Required（`R-USSHORT-26W-DIAG-KNIFE5-THE-SPLITS-LEG-STILL-LAUNDERS-AN-UNREADABLE-BODY`、`R-USSHORT-26W-DIAG-KNIFE5-A-DUPLICATED-DIVIDEND-IS-COUNTED-TWICE`、`R-USSHORT-26W-DIAG-KNIFE5-A-NON-FINITE-SPLIT-RATIO-IS-EMITTED-WITH-NO-REASON`、`R-USSHORT-26W-DIAG-KNIFE5-THE-RECONCILED-FLAG-NEVER-COMPARES-ANY-PRICE`）仍为 `OPEN-NOT_VERIFIED`，交 Claude Code 独立审查；本工作树不 commit。
- 后续保持既有 gated 授权、同周/epoch/window/valuation-date 绑定和局部降级；不得用真实 provider/lifecycle 结果替代本轮审查，不得修改桌面 `C:\Users\cnhea\Desktop\usshort-compare.md`。

## 2026-08-09 追加：Knife5 兄弟腿四条 Required 的复审结论（PASS，用户指定起全量）

**审查对象**：`D:\cnhea\Codex\worktrees\cb59\Stock` 的未提交修复轮（21 改 + 3 新增）。

**成立的部分**：四条兄弟腿 Required 全闭，且这一轮的类修**落在共享层而不是四条腿上各打补丁**——`capture._page_result` 捡回 `_result_rows` 早就返回却被 `_, page_rows = ...` 丢掉的 key，把「读不懂」升格成独立 status `unreadable_body` 并排在 `empty` 之前；`_family_complete` 因此一行未改就对四个 family 同时生效，而 `empty` 从此只表示「真的没有」。另三条：`_daily_prices_reconciled` 用 Decimal 真比价（拆股周正确跳过）、分红事件去重、非有限比值不落地。

**拦下的**：无。

**验证命令与结果**：全量由 reviewer 自起（用户本轮指定）`full_pack_ledger run us_short ... -- discover -s tests -p "test_us_short*.py"` → `PASS 5645 / 628.9s / deadline=860s`、`COUNT_GATE discovered=ran=5645`；焦点 `43 OK`。探针、控制组与植入对照见 SESSION_LOG 同日 `Verify` 与 register。

**这一轮解决的一个证据缺口**：执行方本轮把 full-lane 记为 `NOT_VERIFIED`（`discovered=5645 / ran=4469`，并行资源测试失败）。同一代码态由我重跑，计数门相等、零失败，故该 flake 未复现——本刀现在有一份计数门相等的全量证据。

**验证边界**：未起第三个独立对抗 agent（rule 8：delta 约 110 行、方向全是收紧；前两轮已各跑过一个 agent，第三个会重走同一片代码）。收紧类改动的真实风险是误伤，已由每条的控制组覆盖（真空 splits 仍通过、无拆股周价格相等不得误伤）。payload-drift 残留（真实 provider body 若带 per-request id）本树无 `provider_samples/` 可查证，继续 NOT_VERIFIED。

**给下一轮的教训（承接上一条追加）**：上一轮我把类边界说成「按 family 分档」，方向对但默许了一个 family 一套特例，于是第一次修复只动了被点名的 dividends。这一轮改成「先找现成的判别器」，判别器一捡回来，四条腿一次全好、且不需要为每个 family 写例外。**下次给类边界时，先问「这个区分是不是已经在代码里算过了」，再谈分档。**

## 2026-08-09 追加：Knife7 tests-only 18 项回归清账（resolved）

### 改了什么

- 仅修改 `D:\cnhea\Codex\worktrees\cb59\Stock\tests\test_us_short_market_diagnostic_start_receipt.py` 与 `D:\cnhea\Codex\worktrees\cb59\Stock\tests\test_us_short_market_diagnostic_aggregator.py`：拆开 backfill/horizon、first-week 4/4，新增 malformed digest 精确分支与 `O_EXCL` race，并收紧 orphan、digest swap、report conflict 的因果断言。18 项完整矩阵见 `D:\cnhea\Codex\worktrees\cb59\Stock\docs\system_risk_register.md` 对应 R-ID。

### 为什么改

- 原 finding 记录 18 个产品回归只抓 9 个；当前多数守卫后来已补，但 digest-format 仍会被后续 mismatch 异常冒充，`O_EXCL` 仍无竞态测试，组合测试也无法逐项清账。tests-only 修法把每个安全属性钉到可单独植入的行为结果，不改授权或写盘逻辑。

### 验证命令

```text
.tools\run_unittest_with_repo_pythonpath.cmd tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_reissuing_the_same_receipt_is_idempotent_but_re_anchoring_is_refused tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_the_frozen_week_must_be_a_week_this_track_actually_decides_on tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_the_frozen_week_cannot_back_fill_before_the_notification tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_orphan_recovery_cannot_open_the_clock_either tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_the_frozen_week_cannot_escape_the_notification_horizon tests.test_us_short_market_diagnostic_authorization_conformance.SourceDriftTest.test_a_moved_anchor_that_changes_epoch_is_also_refused tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_ongoing_gate_rejects_a_malformed_digest_before_comparison tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_exclusive_create_rechecks_the_race_winner tests.test_us_short_market_diagnostic_aggregator.UsShortMarketDiagnosticAggregatorTest.test_public_pair_is_immutable_and_identical_rerun_is_idempotent tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_first_week_gate_binds_calendar_week_index tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_first_week_gate_binds_decision_date tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_first_week_gate_binds_window_id tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_first_week_gate_binds_diagnostic_epoch tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_deleting_the_receipt_stops_the_clock_it_opened tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_swapping_the_receipt_stops_the_clock_it_opened tests.test_us_short_market_diagnostic_authorization_conformance.SourceDriftTest.test_the_anchor_cannot_be_moved_under_a_running_count tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_a_receipt_whose_design_digest_is_invented_opens_nothing tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_a_notification_digest_must_match_its_own_text
.tools\run_unittest_with_repo_pythonpath.cmd tests.test_us_short_market_diagnostic_start_receipt tests.test_us_short_market_diagnostic_authorization_conformance tests.test_us_short_market_diagnostic_aggregator
.tools\verify_doc_process.cmd
```

### 验证结果

- 干净态 18/18 OK；同批中和 18 个对应产品约束后 `Ran 18 / FAILED (failures=23)`，即 18 个 test case 全红。三份产品文件随后按 mutation 前 SHA-256 逐字节恢复；同步最新 master 后最终三模块 `47/47 OK`，receipt `24f08fac528a8122414df9e7`。用户已豁免独立审查，本 R-ID 已 resolved；未联网、未用 provider、未开钟、未写账户。

### 失效的旧结论

- 「当前全套仍只能发现 18 项中的 9 项」对本工作树测试态已失效；但 executor 证据不等于独立审查，本 R-ID 在 register 仍为 `OPEN-NOT_VERIFIED`。`RECEIPT-DIGESTS` 的真实通知来源绑定仍 open，未被本轮 M18 覆盖。

### 下一步注意事项

- 用户已明确本条不需要独立审查；后续若处理 `RECEIPT-DIGESTS`，仍须另立 R-ID 范围，不得把真实通知来源绑定混入本条。本轮已提交并合并，工作树不再有未提交改动。

## 2026-08-09 追加：Knife7 RECEIPT-DIGESTS 通知半收口（OPEN-NOT_VERIFIED）

### 改了什么

- 在 `D:\cnhea\Codex\worktrees\cb59\Stock\schemas\us_short_market_diagnostic_completion_notification.schema.json` 增加 closed-world canonical 通知源契约；`schemas\us_short_market_diagnostic_start_receipt.schema.json` 升至 `1.1.0`，固定私有源名 `design_completion_notification.json`，保留唯一一枚对完整 canonical 源计算的 `notification_sha256`。
- `D:\cnhea\Codex\worktrees\cb59\Stock\engine\us_short_market_diagnostic_start_receipt.py` 的 build/issue API 改为只收绝对 `notification_path`；签发用两次 `O_EXCL` 固化源与 receipt，所有 receipt 消费都回读源复核。source-only 中断态报 broken，同源可恢复、异源拒绝；源写失败清理部分文件。
- `D:\cnhea\Codex\worktrees\cb59\Stock\runners\us_short_market_diagnostic_weekly.py` 删除独立 `--issued-at`，时间/issuer/正文全由 JSON 源提供；`runners\us_short_market_diagnostic_rehearsal.py` 同步生成明确标注的 sandbox canonical 源。schema、CLI、reader/writer/publish/recovery/rehearsal 与 inventory 测试同步。

### 为什么改

- 旧实现拿 receipt 内的通知正文与同一 receipt 内的摘要互比，是循环自证；即使二者一致，也不能证明存在外部通知来源。修法让摘要真正绑定一份独立磁盘制品，并让每个授权消费点都重新核它。
- SHA 只保留一枚，用作 canonical 外部源的紧凑稳定身份；没有叠加第二哈希、签名、证书或确认入口。全字段比较负责语义一致，SHA 不被夸成无密钥防伪。

### 验证命令

```text
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_notification_digest_is_verified_against_the_independent_source
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.test_us_short_market_diagnostic_start_receipt tests.test_us_short_market_diagnostic_weekly_runner tests.test_us_short_market_diagnostic_authorization_conformance tests.test_us_short_market_diagnostic_lifecycle tests.test_us_short_market_diagnostic_aggregator tests.test_us_short_market_diagnostic_benchmark_packet tests.test_us_short_market_diagnostic_weekly_producer tests.test_us_short_market_diagnostic_weekly_advance tests.schema.test_us_short_market_diagnostic_26w_schemas tests.test_us_short_market_diagnostic_rehearsal tests.test_us_short_test_io_inventory
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe .tools\full_pack_ledger.py run us_short rule3:c_notification_source+schema+open-clock+rehearsal_entrypoints receipt:7e83f706097323c0dc3731fd 860 -- discover -s tests -p "test_us_short*.py"
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd tests.test_route_doc_ledger_status_consistency tests.test_doc_governance_guard
```

### 验证结果

- 临时中和 source comparison 后，源漂移用例精确转红；还原后产品文件 SHA-256 回到 `0ef0039764cd2f5fc50dfe3743d8ed304c81aaf58a006f441ea7575348db7283`。首轮 full lane 又抓到 rehearsal 仍传旧 `issued_at`；修正后 rehearsal `30/30 OK`，说明全量红灯补到了真实组装遗漏而非被旧绿覆盖。
- 开工后 master 前进 10 个提交，按规则 fast-forward/autostash 同步到 `d7d7e8a3` 的已审 inventory 收口；没有手工改 snapshot/allowlist，只把本轮通用 `source` 改成路径语义名。inventory 定点及 full-lane 组合均 `18/18 OK`。
- 最终 focused `277/277 OK`，receipt=`7e83f706097323c0dc3731fd`；当前 fingerprint full lane `5665/5665 PASS`、307/307 modules、`COUNT_GATE discovered=ran=5665`、365.9s/860s。未联网、未调用真实 provider、未生成真实完成通知/receipt、未开钟、未写 model-paper/account、未改变选股/操作/NAV/Ship gate；未 commit。

### 失效的旧结论

- 「M18 证明通知来源绑定」仍是错的；M18 只证明旧 receipt 内部自洽。本轮新增的磁盘源回读与 source-drift 反向用例才覆盖来源绑定。
- 「通知摘要全仓没有消费点」对本工作树已失效；`validate_start_receipt(receipt, root=...)` 已是统一消费点，所有后续授权路径经它回读固定源。
- 「rehearsal 已天然兼容新版 open-clock」与「开工时 inventory 状态仍是当前 master」也失效；前者被首轮 full lane 转红，后者由用户提醒后查出 master 已前进并已审收口，均已按真实组合态修正/同步。

### 下一步注意事项

- Required `R-USSHORT-26W-DIAG-KNIFE7-RECEIPT-DIGESTS-ARE-NEVER-RE-VERIFIED` 实现完成但保持 `OPEN-NOT_VERIFIED`；交 Claude Code 独立审查 source drift、source-only recovery、reader/writer/publish 全消费点和无真实开钟边界。本工作树不 commit。
- 不要把单枚 SHA 扩成签名/证书体系，也不要恢复 caller-built mapping 或独立 `--issued-at`；真实 `设计完成` 通知、receipt 签发与 26 周开钟仍是未来独立动作，不由本轮实现自动触发。

## 2026-08-09 追加：开钟门通知源绑定的审查结论（FAIL）

**审查对象**：`D:\cnhea\Codex\worktrees\cb59\Stock` 的未提交工作（19 改 + 1 新增 schema），闭 `RECEIPT-DIGESTS` 的通知半。

**成立的部分**：这条 finding 的立项目的**确实达成了**——通知不再是「拿收据里的哈希比收据里的原文」，而是一份独立的 canonical JSON 源制品，`O_EXCL` 复制进私有 store，其后每次读/写/发布都回读磁盘制品重算。四类伪造（摘要归零、自洽无源、源删除、**盘上源被换**）在每个消费点 fail-closed，我与独立 agent 各自复现。API 只收路径、幂等、设计文档同步更新。

**拦下的三条**：①一份 20 个空格的通知能开钟，而 dry-run 预览恰在同一输入上抛 `IndexError`——**不可逆的写成功、防手误的预览崩掉**；②非有限数让 `ModelPaperPortfolioError` 穿透本轨错误契约，坏掉的钟报不出 `broken`；③全仓没有任何工具能产出被接受的 canonical 通知字节（编辑器默认的末尾换行即被拒），这道门一生只被真人用一次，而那一次注定先失败几轮。正文在 `docs/system_risk_register.md` 同日节。

**验证命令与结果**：焦点超集 `Ran 452 in 337.9s OK`；按用户指定本轮不起全量。探针、控制组与植入对照见 SESSION_LOG 同日 `Verify`。

**验证边界与一条过程缺陷**：§6a 独立对抗 agent 已跑（read-only、离线）。**我在它审同一文件期间跑了植入对照，导致它三轮探针失效**；它自行快照、只还原那一行、在快照上重跑，并事后核对 live 文件 sha256 与快照一致，故结论未受污染——但这是我的调度失误：`rule 7(c)` 讲的是不要并发跑重包，同一条原则也适用于「agent 在读某文件时不要去改它」。下次起 agent 后，植入类操作要等它回报。未覆盖：真实并发下的 `O_EXCL` 竞争、符号链接/ACL 面、`verify_design_against_disk=False` 的长期风险量化。

## 2026-08-09 追加：开钟门通知源三条审查 Required 收口（OPEN-NOT_VERIFIED）

### 改了什么

- `schemas/us_short_market_diagnostic_completion_notification.schema.json` 要求 `notification_text` 至少含一个非空白字符；weekly dry-run 不再对可能为空的 `splitlines()` 结果无守卫取 `[0]`。
- `engine/us_short_market_diagnostic_start_receipt.py` 新增统一 `_canonical_payload` typed-error 边界与 `write_completion_notification_template`；weekly CLI 新增 `emit-notification-template --output-path --issued-at --notification-text`，只写 canonical source，不确认设计、不签 receipt、不打开时钟，已有文件以 `O_EXCL` 拒绝覆盖。
- `aggregator` 报告写出与 `lifecycle._atomic_write` 补齐本轨 typed-error 转换；authorization conformance 为两个纯内存 helper 和只写 operator-named source 的 producer 增加理由化豁免，未改 tracked I/O inventory snapshot/allowlist。

### 为什么改

- reviewer 证明原实现允许 20 个空格通过不可逆开钟，而 dry-run 在同一输入上抛 `IndexError`；修复后预览与真开钟同向拒绝且未写 store。
- `canonical_json_bytes` 对 `NaN`/`Infinity` 抛外部 `ModelPaperPortfolioError`；14 个调用点中，`start_receipt` 七处现统一转换，`aggregator` 与 lifecycle writer 补齐，lifecycle reader/attribution/local adapter/total return 原已收口，weekly producer 的 payload 仅含已检查字符串与 SHA，非有限数不可达。
- 人工编辑器默认末尾换行会让正确内容变成 non-canonical；新 producer 直接写出引擎接受的 exact bytes，消除“只能读源码手工拼字节”的操作死角，但不增加开钟授权。

### 验证命令

```text
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 60 tests.test_us_short_market_diagnostic_weekly_runner.DryRunTest.test_blank_notification_is_rejected_before_both_preview_and_real_open
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 60 tests.test_us_short_market_diagnostic_weekly_runner.ClockStatusTest.test_non_finite_notification_source_stays_inside_the_track_error_contract
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 60 tests.test_us_short_market_diagnostic_weekly_runner.NotificationTemplateTest.test_cli_emits_exact_canonical_bytes_that_preview_and_real_open_accept
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 600 tests.test_us_short_market_diagnostic_start_receipt tests.test_us_short_market_diagnostic_weekly_runner tests.test_us_short_market_diagnostic_authorization_conformance tests.test_us_short_market_diagnostic_lifecycle tests.test_us_short_market_diagnostic_aggregator tests.test_us_short_market_diagnostic_benchmark_packet tests.test_us_short_market_diagnostic_weekly_producer tests.test_us_short_market_diagnostic_weekly_advance tests.schema.test_us_short_market_diagnostic_26w_schemas tests.test_us_short_market_diagnostic_rehearsal tests.test_us_short_market_diagnostic_attribution tests.test_us_short_market_diagnostic_local_adapter tests.test_us_short_market_diagnostic_total_return tests.test_us_short_test_io_inventory
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe .tools\full_pack_ledger.py run us_short "rule3:c receipt notification schema+producer+typed-error closure" "receipt:209cdc1e26aa6651a82e740e" 860 -- discover -s tests -p "test_us_short*.py"
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd tests.test_route_doc_ledger_status_consistency tests.test_doc_governance_guard
```

### 验证结果

- 三条点名植入分别把 schema pattern 放宽为 `.*`、把 serializer wrapper 改为只 catch `KeyError`、给模板输出追加末尾换行；对应测试均精确转红，随后逐项恢复。最终 affected `389/389 OK`、receipt `209cdc1e26aa6651a82e740e`；canonical 调用点模块与 tracked I/O inventory 包 `214/214 OK`。
- affected 首轮由 authorization conformance 精确抓到三个新 helper 未声明边界；理由化豁免后单项与全包转绿。该红灯证明组合守卫承重，不是靠改 inventory snapshot 追绿。
- 本代码态唯一 full-lane 为 `FAIL 1886/5676`：同步 master 后新加入的 0815 soft-discovery 冻结守卫期望 0809 runbook SHA `301ed0a5…`，但当前 HEAD blob 为 `b9637395…`、CRLF checkout 为 `145a5d90…`，且该文件 git-clean、本刀未触碰。按范围边界不改冻结付费证据、不重跑，故 full-lane=`NOT_VERIFIED`。未联网、未用 provider、未生成真实通知/receipt、未开钟或写账户。

### 失效的旧结论

- “`minLength: 16` 足以证明通知有内容”失效；纯空白必须在 schema 门拒绝。
- “canonical serializer 的外来错误自然会被本轨入口接住”失效；只有明确转换或证明不可达才成立。
- “仓库已有 source reader，所以操作员能自然产出 canonical source”失效；现在由专用 producer 写 exact bytes。
- “同步后的 master full-lane 可直接作为本刀绿色底座”失效；0815 新冻结守卫与其 HEAD 制品不一致，必须另刀处理。

### 下一步注意事项

- 三条 Knife7 Required 保持 `OPEN-NOT_VERIFIED`，交 Claude Code 独立审查；O1/O2 仍为 Optional，未纳入本修复轮。
- `R-USSHORT-SOFT-DISCOVERY-20260809-FROZEN-RUNBOOK-HASH-DOES-NOT-MATCH-HEAD` 属 soft-discovery 外部 blocker；不得在本刀改 expected hash、改冻结 runbook 或重复跑 full 追绿。
- 工作树绝对路径为 `D:\cnhea\Codex\worktrees\cb59\Stock`；不 commit，不触碰 `D:\cnhea\Stock` 工作区内容或桌面文档。

## 2026-08-09 追加：开钟门三条 Required 的复审结论（PASS）

**审查对象**：`D:\cnhea\Codex\worktrees\cb59\Stock` 的未提交修复轮（21 改 + 1 新增 schema）。注：记忆里当轮审查树写的是 `000e`，但该树干净、其刀已提交合入，未提交对象在 cb59。

**成立的部分**：三条 Required 全闭，且都按类边界修的——空白门只加在 schema 一处（未双重设门）；`[0]` 那条只改了真正会崩的 `weekly.py`，其余 6 处按 reviewer 枚举保持不动；非有限数的类扫伸到了我点名之外的 `aggregator` 与 `lifecycle`。最值得记的一条是我额外追出来的：`clock_status` 从「抛外来异常」变成「返回 `broken` 并给出原因」，而不是被洗成 `not_started`——空 store 对照仍报 `not_started`，说明没有把一切判成坏。

**拦下的**：无。

**验证命令与结果**：焦点超集 `Ran 456 in 344.0s OK`；按用户指定不起全量。三条的原始条件复现、控制组与植入对照见 SESSION_LOG 同日 `Verify` 与 register。

**验证边界**：未起第三个独立对抗 agent（rule 8：同一道门、收紧类小 delta，上一轮已由 agent 全面攻过；误伤面由正常文本/空 store/正常 dry-run 三处控制组覆盖）。未覆盖：真实并发下的 `O_EXCL` 竞争、符号链接与 ACL 面、`verify_design_against_disk=False` 的长期风险量化——这三条与上一轮相同，仍未量化。

## 2026-08-09 追加：Knife7 两条 Optional 收口（OPEN-NOT_VERIFIED）

### 改了什么

- `engine/us_short_market_diagnostic_start_receipt.py` 新增非授权的 `diagnostic_start_receipt.pending.json`：先于通知源和最终 receipt 以 `O_EXCL` 冻结完整候选 receipt；只有全参数相同的中断重试可继续，source-only 旧中断态不可恢复。
- `schemas/us_short_market_diagnostic_start_receipt.schema.json` 升至 `1.2.0` 并删除 `completion_notification.notification_sha256`；builder、source validator、模板返回值及测试同步更新，不增加替代摘要或确认入口。

### 为什么改

- 旧恢复只比较通知源字节，同一通知在最终 receipt 尚未落盘的窗口可换 `first_decision_date` / `diagnostic_epoch` 重锚；pending intent 把“恢复”收紧为完成同一次签发。
- 通知 schema 闭世界，receipt 已逐字段比较所有可变通知字段；再存一枚由同字段计算的 SHA 没有独立验证力，保留只会让来源绑定看起来比实际多一层。

### 验证命令

```text
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 120 tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_interrupted_issuance_recovers_only_with_the_complete_pending_receipt tests.test_us_short_market_diagnostic_start_receipt.StartReceiptTest.test_notification_fields_are_verified_against_the_independent_source
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 300 tests.test_us_short_market_diagnostic_start_receipt tests.test_us_short_market_diagnostic_weekly_runner tests.test_us_short_market_diagnostic_authorization_conformance tests.test_us_short_market_diagnostic_lifecycle tests.test_us_short_market_diagnostic_aggregator tests.test_us_short_market_diagnostic_benchmark_packet tests.test_us_short_market_diagnostic_weekly_producer tests.test_us_short_market_diagnostic_weekly_advance tests.schema.test_us_short_market_diagnostic_26w_schemas tests.test_us_short_market_diagnostic_rehearsal tests.test_us_short_test_io_inventory
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 120 tests.schema.test_us_short_soft_discovery_query_quality_probe_packet_20260809_schema.UsShortSoftDiscoveryQueryQualityProbePacket20260815SchemaTest.test_executed_20260809_artifacts_remain_byte_immutable
cmd /c .tools\run_unittest_with_repo_pythonpath.cmd tests.test_route_doc_ledger_status_consistency tests.test_doc_governance_guard
```

### 验证结果

- 中断绑定 mutation 同时中和“既有 pending 必须逐字一致”和“pending 必须匹配请求”后，点名测试精确红在错误参数已写出最终 receipt；恢复后转绿。SHA mutation 把字段完整加回 schema、builder、validator 后，点名测试精确红在字段复活；恢复后两项 clean control `2/2 OK`，receipt `838a6dbf382a364cb0b33202`。
- affected 11 模块 `282/282 OK`，receipt `03a7335cb113af0ec914c2e5`；tracked I/O inventory 同包通过，未改 snapshot/allowlist。full 前置点名仍红在既有 soft-discovery frozen runbook hash（expected `301ed0a5…`、checkout `145a5d90…`），故未启动必败全量，也未跨部件追绿。
- 未联网、未调用 provider、未生成真实通知/pending/receipt、未开钟、未写 lifecycle/model-paper/account；工作树 `D:\cnhea\Codex\worktrees\cb59\Stock` 未提交。

### 失效的旧结论

- “source-only 中断可凭相同通知字节安全恢复”失效；没有预先绑定完整候选 receipt 的 source-only 状态无法证明原签发参数，只能保持 broken。
- “`notification_sha256` 是外部通知源的必要身份层”失效；它完全由已逐字段比较的同一自由字段派生，删除后来源核验强度不变。
- “O1/O2 仍挂着未动”只属于上一轮审查快照；本轮实现已落地，但在 Claude Code 独立复审前仍为 `OPEN-NOT_VERIFIED`。

### 下一步注意事项

- Claude Code 在 `D:\cnhea\Codex\worktrees\cb59\Stock` 独立审查两条 R-ID，重点确认 pending intent 不授权开钟、差异重试在最终 receipt 写入前拒绝、legacy source-only 不能重锚，以及 schema 1.2.0 没有残留 `notification_sha256` 消费者。
- soft-discovery 冻结 runbook hash 是本刀外部 full-lane blocker；不要在本工作树顺手改 expected hash 或冻结制品。真实通知、receipt 签发与开钟仍须未来独立授权动作。

## 2026-08-09 追加：开钟门两条 Optional 的审查结论（PASS）

**审查对象**：`D:\cnhea\Codex\worktrees\cb59\Stock` 的未提交 Optional 修复轮（10 文件）。

**成立的部分**：O1 把签发改成「先写 pending intent → 通知 → O_EXCL 写 receipt → 成功后丢弃 intent」，恢复时比对整份候选 receipt；忠实复现中断后，原参数恢复仍成功、三种重锚全拒、成功路径不留残留。O2 把验证力为零的 `notification_sha256` 从 schema 整个删掉（1.1.0→1.2.0），剩余四字段仍闭世界，塞回该字段即被拒，生产侧无悬空消费者。

**拦下的**：无。

**验证命令与结果**：按 §6a Optional-only 快档——一次 scope grep + 最小覆盖目标一次 `Ran 71 in 26.8s OK`；未起 agent、未跑全量。探针与控制组见 SESSION_LOG 同日 `Verify`。

**一条自我更正**：我第一版探针把「中断」模拟成「删掉 receipt」，忘了真实中断会先留下 pending intent，于是控制组红了。代码报的 `without a pending receipt intent` 正好点破——那条路径（有人手工摆一份通知）本就该拒。按控制组不绿即判探针无效的规矩重做后结论才成立。教训：**模拟失败态之前先读清楚成功路径的写入顺序**。

## 2026-08-10 追加：桌面 us_testrun1 问题1 —— canonical transaction lock 私密路径修复（OPEN-NOT_VERIFIED）

### 改了什么

- 根 `.gitignore` 新增精确规则 `state/*/_transaction_locks/`，覆盖一键入口真实生成的 `state/us_short/_transaction_locks/<decision_date>.lock`。
- `tests/test_us_short_paper_one_click.py` 新增 canonical 接线测试：使用 `DEFAULT_STATE_DIR`、真实 `resolve_capstone_context()` 和 `_decision_lock_path()`，再由真实 `reject_nonprivate_output_path()` 消费；同时保留 `state/us_short/anything/deep/x.json` 的负向控制。
- 生产代码仍只有 `runners/us_short_weekly_capstone.py::_decision_lock_path()` 一个锁目录生产点；conformance 测试中的 `provider_samples/.../_transaction_locks` 是故意植入坐标，未改。

### 为什么改

问题1的实际死点发生在任何 stage 之前：canonical transaction lock 被私密守卫拒绝。原有锁测试只注入仓外/临时 state root，无法证明一键真实坐标可用；本刀同时验证 tracked `.gitignore` 来源，避免本机 `.git/info/exclude` 造成假绿。

### 验证命令

```text
固定解释器：C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe（3.13.8）
.tools\run_unittest_with_repo_pythonpath.cmd tests.test_us_short_paper_one_click.USShortPaperOneClickTest.test_canonical_decision_lock_is_ignored_by_tracked_gitignore
.tools\run_unittest_with_repo_pythonpath.cmd tests.test_us_short_paper_one_click tests.test_us_short_private_paths tests.provider.test_us_short_weekly_capstone.CapstoneFakeChainTest.test_decision_lock_is_bound_to_the_injected_state_root_and_reacquirable
.tools\run_unittest_with_repo_pythonpath.cmd tests.test_route_doc_ledger_status_consistency tests.test_doc_governance_guard
```

### 验证结果

- 修复前点名测试 `Ran 1 / FAILED`，失败来源为本机 `D:/cnhea/Stock/.git/info/exclude:7`，不是 tracked `.gitignore`；修复后点名测试 `Ran 1 / OK`，receipt=`receipt:3f736ec63694dc9b3abf1f80`。
- 聚焦包 `Ran 21 / OK`，receipt=`receipt:e068e3e4e61b77a35749ae9b`；canonical `git check-ignore -v` 命中 `.gitignore:47`，深层未登记路径返回未忽略且守卫拒绝。
- 两道 door `Ran 55 / OK`，receipt=`receipt:619d73c2ec80fa334fac94d6`；`py_compile` 与 `git diff --check` 通过（仅既有 LF/CRLF 警告）。
- 未运行 provider、网络、真实一键周跑或 full US-short lane；本轮不打开诊断时钟，不触及问题2。

### 失效的旧结论

- “现有临时 state-root 锁测试足以覆盖一键锁路径”已失效；真实 canonical `state/us_short` 坐标此前没有接线覆盖。
- “`git check-ignore` 返回 0 即证明 tracked 私密规则已生效”已失效；本轮红灯证明本机 `.git/info/exclude` 可以制造假绿，必须核对命中来源。

### 下一步注意事项

- 当前 R-ID `R-USSHORT-CANONICAL-TRANSACTION-LOCK-NOT-GITIGNORED` 保持 `OPEN-NOT_VERIFIED`，等待 Claude Code 独立审查后再决定关闭/提交。
- 问题2 `private_root` / `official_output_root` 默认根冲突仍未处理；不得把本刀的 tracked ignore 修复解释为一键全流程已通过。

## 2026-08-10 追加：问题1 独立审查 PASS（Claude Code reviewer/committer）

### 改了什么

- 只做审查与收口，未改上一节交付的任何代码或测试；本节新增的只有 verdict 与独立证据落位：`R-USSHORT-CANONICAL-TRANSACTION-LOCK-NOT-GITIGNORED` 翻 `resolved`，并新记一条 Optional `R-USSHORT-NEW-PRIVATE-STATE-SUBDIR-HAS-NO-RECURRENCE-GUARD`。

### 为什么改

- 上一节的 verdict 位停在 `OPEN-NOT_VERIFIED`，等的就是独立复算；复算全部成立，故按 reviewer/committer 流程关闭并提交。同时把「一个实例已关、产生它的机制仍无守卫」这条残留从桌面权威件搬进仓库状态，避免它只活在桌面文档里。

### 验证命令

```text
固定解释器：C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe（3.13.8）
.tools\run_unittest_with_repo_pythonpath.cmd tests.test_us_short_paper_one_click tests.test_doc_governance_guard
（植入探针）按字节删除 .gitignore 第 47 行 → 跑 tests.test_us_short_paper_one_click.USShortPaperOneClickTest.test_canonical_decision_lock_is_ignored_by_tracked_gitignore → 按字节还原并核对 sha256
git check-ignore -v --no-index -- <9 条私密坐标 + state/us_short/anything/deep/x.json>
```

### 验证结果

- rule-1 焦点超集（reviewer 亲跑）：`Ran 51 in 4.4s OK`，`receipt:8b2c35c706519566f86e4d90`。
- 承重腿植入：点名测试精确转红，失败正文正是 `D:/cnhea/Stock/.git/info/exclude:7`；还原后 `.gitignore` sha256 前后同为 `de129b6ed07e3bdbfb1f4cbf331093cd9242cd617af147e47f5544ad50808758`。同一植入态下 `reject_nonprivate_output_path(lock_path)` 仍 ACCEPT —— 生产守卫本身测不出这个缺口，所以那条「来源必须是 tracked `.gitignore`」的断言是承重的，不是装饰。
- 同类扫描独立重跑：私密家族 9 条坐标全部命中 tracked `.gitignore`；`state/us_short/anything/deep/x.json` 仍 NOT-IGNORED，忽略面未扩大。
- 掩盖源穷举：repo `.git/info/exclude` 只有 `state/*/_transaction_locks/` 一条真实模式，`core.excludesFile` 未配置（rc=1），故本仓没有第二处「靠未跟踪 exclude 撑起私密证明」的同类实例。
- 分级：无 live provider、无 secret 落盘、无 fail-closed 引擎改动，按 §6a 不起独立 agent；rule 3 五个触发条件均不成立，`full-lane=not_triggered`。

### 失效的旧结论

- 上一节「等待 Claude Code 独立审查后再决定关闭/提交」已失效——审查已完成，R-ID 已关闭并提交。

### 下一步注意事项

- 机制级复发仍未上守卫（Optional R-ID 已登记）。若将来采纳，只允许一条窄的静态一致性测试 + planted-failure；桌面权威件 §问题1 修复方案 §0 已把注册表 / schema / 指纹 / 运行时目录扫描器 / 新抽象层列入不纳入，不得借此扩建。
- 问题2 `private_root` / `official_output_root` 默认根冲突仍未处理；本刀 PASS 只代表锁这一步不再拦路，不代表一键全流程可跑通。

## 2026-08-10 追加：问题1 Optional recurrence guard + 桌面问题2 carrier-root / model-paper 首周 seed 修复（OPEN-NOT_VERIFIED）

### 改了什么

- 问题1 Optional：`tests/test_us_short_paper_one_click.py` 静态枚举生产 `ctx.state_dir / "<literal>"` 私密子目录，逐项要求真实 `git check-ignore -v --no-index` 命中 tracked `.gitignore`，并加入未登记子目录 planted-failure；未引入注册表、schema、指纹、运行时扫描器或宽泛 ignore。
- 问题2 A：`runners/us_short_batch5_to_batch4_weekend_e2e.py` 把 `private_root` / `official_output_root` 只解析为 carrier root；account/context 及下游 lifecycle/weekly/runs 实际叶子守卫保留。
- 问题2 B：`runners/us_short_weekly_capstone.py` 在 authorization/context 基础校验后、settlement/checkpoint/transaction/provider 前，对 account、context packet、lifecycle、三份 official 叶子和 model-paper `head_manifest.json` 做真实 preflight；dry-run 语义不变。
- 问题2 C：`engine/us_short_model_paper_store.py::_store_root()` 改守卫首个真实制品 `head_manifest.json`，不提前 mkdir；首次缺失 store 继续走既有 `not initialized → seed_required`，终端 owner 仍负责初始化。
- 只在既有三个测试文件补三条承重回归，并更新既有 IO inventory 测试分类与快照；未改 schema、CLI、业务字段、`.gitignore`、provider/live。

### 为什么改

问题2的两个默认入口把 namespace/carrier root 当成私密叶子，导致 canonical `state/us_short` 在任何 stage 前被拒；model-paper 首次运行又在真实 head 制品创建前守卫尚不存在的裸根，阻断 first-week seed。桌面方案要求把隐私证明落在真实叶子，不放宽全局 private-path guard，也不忽略整根。

### 验证命令

```text
固定解释器：C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe（3.13.8）
.tools\run_unittest_with_repo_pythonpath.cmd tests.provider.test_us_short_batch5_to_batch4_e2e tests.provider.test_us_short_weekly_capstone tests.test_us_short_paper_one_click tests.test_us_short_model_paper_store tests.test_us_short_model_paper_weekly tests.test_us_short_model_paper_capstone_wiring tests.test_us_short_private_paths tests.test_us_short_capstone_checkpoint
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -m py_compile runners/us_short_batch5_to_batch4_weekend_e2e.py runners/us_short_weekly_capstone.py engine/us_short_model_paper_store.py tests/provider/test_us_short_batch5_to_batch4_e2e.py tests/provider/test_us_short_weekly_capstone.py tests/test_us_short_model_paper_capstone_wiring.py
.tools\run_unittest_with_repo_pythonpath.cmd tests.test_us_short_test_io_inventory
.tools\run_unittest_with_repo_pythonpath.cmd tests.test_route_doc_ledger_status_consistency tests.test_doc_governance_guard
```

### 验证结果与边界

- 三条新回归先取得区分性红灯，修复后 `3/3 PASS`，receipt=`receipt:6ee0485a5f5e70b6691ab3c7`；最终 focused 超集 `146/146 PASS`，receipt=`receipt:beb25a11ea3b1625b55af028`；IO inventory 修正后 `18/18 PASS`，receipt=`receipt:d7ee5d51a1a2c9807ee0d682`。
- full-lane 按 rule 3(a)/(b) 只执行一次：ledger `FAIL`，`discovered=5735`、`ran=5274`，因旧 IO inventory 快照未覆盖本刀新增夹具 allowlist/count；未显示生产行为测试失败。按桌面方案不重跑 full lane，不能宣称 full-lane PASS。
- `py_compile`、`git diff --check` 和两道 door 均通过；door `55/55 PASS` receipt=`receipt:971fdcf25e64d9d407333f05`。本轮无 provider/network/live/account/diagnostic clock/ship-gate，未产生真实运行产物，Codex 未提交。当前 Required 与 Optional 均保持 `OPEN-NOT_VERIFIED`，待 Claude Code 独立审查。

### 失效的旧结论

- “问题1只有 `_transaction_locks/` 实例、没有机制级 recurrence guard”已失效：静态枚举 + tracked-ignore + planted-failure 已落地，但仍待独立审查闭合。
- “canonical `private_root` / `official_output_root` 仍在首阶段被根守卫阻断”已失效；“首次不存在的 model-paper root 必须先手工 mkdir 才能 seed”也已失效。
- “当前问题2 full lane 已通过”不成立：唯一 full-lane 记录是 `5735 discovered / 5274 ran / FAIL`，inventory 基线随后已修正，但按方案未重跑全量。

### 下一步注意事项

- Claude Code：独立审查问题1 Optional 与 `R-USSHORT-CARRIER-ROOT-LEAF-PREFLIGHT-AND-MODEL-PAPER-FIRST-SEED`；重点核对 carrier root 与实际叶子边界、preflight 位置、model-paper 首件证明、negative controls、full-lane FAIL 边界，然后决定 Pass 或 Required/重跑授权。
- 不要把 `state/us_short` 整根加入 `.gitignore`，不要恢复裸根 guard，不要用手工 mkdir/新 schema/SHA/运行时机制掩盖问题；本工作树仍为 `D:\cnhea\Codex\worktrees\238a\Stock`，不提交、不触碰主树或其他工作树。

## 2026-08-10 追加：问题2 独立审查 FAIL（Claude Code reviewer）

### 改了什么

- 只做审查，未改本刀交付的任何代码或测试。新增 verdict 与证据落位：blocking `R-USSHORT-NEW-CAPSTONE-TEST-WRITES-INTO-THE-REAL-REPO-PRIVATE-ROOT` + 5 条 Optional，正文全在 `docs/system_risk_register.md`。

### 为什么改

- 生产三处改动本身站得住（见下），但新增回归测试把真实 checkout 的 `state/us_short` 当成自己的沙盒跑真实事务，撞红既有资源隔离守卫，full lane 因此无法通过——而执行方自己写的 closure criteria 就要求一次 `discovered == ran` 的 full lane PASS。

### 验证命令

```text
固定解释器：C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe（3.13.8）
.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.test_us_short_paper_one_click tests.test_us_short_model_paper_capstone_wiring tests.test_us_short_test_io_inventory tests.provider.test_us_short_weekly_capstone tests.provider.test_us_short_batch5_to_batch4_e2e tests.test_us_short_discovery_conformance tests.test_doc_governance_guard
python .tools\full_pack_ledger.py run us_short "<rule-6 escalation reason>" "receipt:9cf2d8d1d47637bb4878e4e9" 860 -- discover -s tests -p "test_us_short*.py"
（放松腿反向控制）_store_root / _week_paths 对 state/us_short_probe_tmp 与 canonical 对照；git check-ignore -v --no-index 逐条坐标
```

### 验证结果

- 焦点超集：`Ran 197 in 43.5s OK`，`receipt:9cf2d8d1d47637bb4878e4e9`。
- reviewer 自起 full lane（rule 6）：`discovered=5735 ran=5734 equal=False FAIL`，唯一红为 `tests/test_us_short_discovery_conformance.py:2325`，断言原文 `a resource test changed repository state/us_short`。跑完真实目录里多出 `runs_private/20260709/machine_record.json`、`weekly_private/20260709/{weekly_report.md,action_table.csv}` 与 `_superseded/20260709__2026-07-09T08-00-00-04-00[_x…]` 链，全部 gitignored 所以 `git status` 恒净。
- 放松腿反向控制：`_store_root` 现接受 `state/us_short_probe_tmp`（该根本身 NOT-IGNORED）——放松是真的；但 `_week_paths` 在同一根下仍 REJECT，canonical 对照两者皆 ACCEPT，故**叶子级 fail-closed 仍成立、无数据外泄**。`.json.tmp` 兄弟实测 IGNORED，我读代码时怀疑的临时文件泄漏不成立。
- §6a 独立对抗 agent（起 1 个）：在不知道我那条全量红的前提下独立收敛到同一条，并演示 `_superseded` 目录对数 9→10 的无界增长；其余 6 条为 P2/P3，均未演示出数据外泄，已按 Optional 记录。

### 失效的旧结论

- 「full-lane 唯一失败是旧 IO inventory 快照、未显示生产行为测试失败」已失效：那次 fail-fast 停在 inventory 模块，**从未跑到**资源隔离守卫；本轮跑到了，红的是本刀新增测试引起的真实状态污染。

### 下一步注意事项

- 修复须整类闭：同类还有 `tests/test_us_short_model_paper_capstone_wiring.py` 断言 `state/us_short/model_paper_private` 不存在（跑过产品的 checkout 必红）。
- 修完请一并清掉本次已落盘的 `state/us_short/{runs_private,weekly_private}/20260709*` 与 `_superseded` 残链，并由执行方跑出一次 `discovered == ran` 的 full lane PASS 再交复审。

## 2026-08-10 追加：Required 测试真实私密根污染修复（OPEN-NOT_VERIFIED）

### 改了什么

- `test_unregistered_in_repo_root_fails_before_first_stage` 的正向控制改用既有 `temporary_us_short_state_directory(ROOT)` 注入式 gitignored 临时根；仍跑 `dry_run=False` 的完整 fake bridge 事务并断言 weekly/action/machine 三份输出，canonical carrier-root 语义未改成放宽真实守卫。
- `test_absent_in_repo_model_paper_root_reaches_first_week_seed_preview` 同样使用临时 state 根，验证缺失 store 可到达 `seed_required` 且 adapter preview 不创建 store；不再断言真实 checkout 的 `state/us_short/model_paper_private` 永远不存在。
- 用既有 inventory 生成器同步 `docs/us_short_test_io_inventory_20260801.json`，只删除已经不再出现的 `model_paper_store_root` unresolved key；五条 Optional 未处理。

### 残留清理

- 当前工作树中已删除并复核为空：
  `state/us_short/runs_private/20260709`、
  `state/us_short/runs_private/_superseded`、
  `state/us_short/weekly_private/20260709`、
  `state/us_short/weekly_private/_superseded`、
  `state/us_short/model_paper_private`。
- 被删除的是 gitignored 运行时假产物/归档链，不在 Git 历史中，不能由 Git 恢复；未触碰主树或其他工作树。

### 验证命令与结果

```text
固定解释器：C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe（3.13.8）
.tools\run_unittest_with_repo_pythonpath.cmd tests.test_us_short_discovery_conformance_resources.ResourceIsolationMatrix.test_d_repo_shared_resource_tests_inject_state_and_lock_roots
.tools\run_unittest_with_repo_pythonpath.cmd tests.provider.test_us_short_batch5_to_batch4_e2e tests.provider.test_us_short_weekly_capstone tests.test_us_short_paper_one_click tests.test_us_short_model_paper_store tests.test_us_short_model_paper_weekly tests.test_us_short_model_paper_capstone_wiring tests.test_us_short_private_paths tests.test_us_short_capstone_checkpoint
.tools\run_unittest_with_repo_pythonpath.cmd tests.test_us_short_test_io_inventory
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe .tools\full_pack_ledger.py check us_short
```

- 资源隔离点名 `Ran 1 / 82.119s / OK`，receipt=`receipt:27466ca9e5aeeddac40d8b51`；affected focused `Ran 146 / 17.994s / OK`，receipt=`receipt:e7a0edc450540a89f16cd5e3`；inventory `Ran 18 / 10.219s / OK`，receipt=`receipt:7e34a2a9cf7656c50dbe5f6d`。
- full lane 已按 ledger 唯一执行并通过：`modules=316, discovered=5735, ran=5735, equal=True`，`Ran 5735 in 592.724s`，`RESULT status=PASS exit=0 tests=5735`；`.tools/state/full_pack_ledger.json` 已记录该 exact code fingerprint `430062b2a96e490bccef5b29d97b52e1ce38d8be3bb814f8de0114aac0a1c4ca` 的 `5735 OK`。full-pack static 为 `diff_check=PASS, py_compile=8`；最终文档/路由门 `Ran 55 / 2.024s / OK`，receipt=`receipt:545765f5d3b817c60a23a610`，`git diff --check=PASS`。
- 盘面扫描确认 `20260709`、`_superseded`、`model_paper_private` 均无匹配残留；无 provider/network/live/account/order/诊断时钟/ship-gate。

### 失效的旧结论

- 「full lane 唯一失败是旧 inventory、未跑到生产行为守卫」已失效：当前 exact code state 的唯一有效 full lane 已完整跑到资源隔离模块并以 `5735/5735 PASS` 收口。
- 「测试会把真实 `state/us_short` 当作自己的沙盒并持续增长 `_superseded`」已失效：两处正向/缺失根测试都绑定临时根，真实盘面扫描为空。

### 下一步

- Claude Code：独立审查本 R-ID 的两处测试隔离、inventory 变更、清理范围和 `5735/5735` ledger 证据；通过后由 reviewer/committer 提交。五条 Optional 继续留在 register，未作为本次 Required 的闭合条件。

## 2026-08-10 追加：问题2 复审 PASS（Claude Code reviewer/committer）

### 改了什么

- 只做复审与收口，未改本刀交付的任何代码或测试。`R-USSHORT-NEW-CAPSTONE-TEST-WRITES-INTO-THE-REAL-REPO-PRIVATE-ROOT` 与 `R-USSHORT-CARRIER-ROOT-LEAF-PREFLIGHT-AND-MODEL-PAPER-FIRST-SEED` 双双翻 `resolved`，独立复算写进 register 顶部；上轮 5 条 Optional 保持 open。

### 为什么改

- 上轮判死的是测试隔离，不是设计。两条同类腿改用 lane 既有的 `temporary_us_short_state_directory` 之后，canonical 载体根语义仍被完整证明（正向控制照跑完整事务，并新增三份 official 产物落位断言），而真实 checkout 不再被写。

### 验证命令

```text
固定解释器：C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe（3.13.8）
.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.provider.test_us_short_weekly_capstone tests.test_us_short_model_paper_capstone_wiring tests.test_us_short_paper_one_click tests.test_us_short_test_io_inventory tests.provider.test_us_short_batch5_to_batch4_e2e tests.test_us_short_discovery_conformance_resources tests.test_doc_governance_guard
（植入探针）把 _preflight_private_output_paths 按字节中和成 no-op → 跑点名测试 → 按字节还原并核 sha256
python -c "verification_receipt.collect_code_state / fingerprint" 独立重算指纹，与 .tools/state/full_pack_ledger.json 记录比对
```

### 验证结果

- 焦点超集（含上轮转红的 `tests.test_us_short_discovery_conformance_resources`）：`Ran 169 / 142.1s / OK`，`receipt:a1634177c8bfc727d82dfa94`；真实 `state/us_short` 下 `20260709`、`_superseded`、`model_paper_private` 残留实测为空。
- 植入探针：中和 preflight 后点名测试精确转红（`FAILED (errors=1)`），还原后 `runners/us_short_weekly_capstone.py` sha256 前后同为 `2e01b679…`。**顺带一个比预期更强的结论**：中和后拦住未登记仓内根的，是更深处 writer 抛出的原生 `PrivatePathError`（`weekly_private/_transaction_state/20260709.json`）——preflight 是「把失败提前」，不是唯一防线。
- full lane 按 rule 4 引用执行方账本、reviewer 不重跑：`fingerprint` 与 `prepared_fingerprint` 均等于我独立重算的 `430062b2a96e49…`，`discovered=ran=5735`、`count_gate_equal=True`、`modules 316/316`、592.7s。
- 一次自我更正：`check us_short` 报 no cached green，一度像是与账本冲突；读 `cached_green()` 后确认它还要求 prepared 记录的 focused receipt 与当前 receipt 文件一致，而覆盖该文件的正是我自己的 focused 重跑——属受体绑定假阴性，不是代码态变化，故未按 rule 6 重跑全量。
- 另一次自我更正：第一版植入探针写成 PowerShell 内联字符串，转义被解析吃掉，文件从未被改（sha 未变）而命令却返回 OK，并在仓库根留下一个空文件 `assert`。已删除该文件并改用脚本文件重做，结论以重做那次为准。教训：**带引号/反斜杠的字节级补丁一律走脚本文件，别塞进内联字符串**。

### 失效的旧结论

- 「本刀不能过，因为 full lane 过不去」已失效：账本已有 `5735/5735 equal PASS` 且指纹匹配当前代码态。

### 下一步注意事项

- 五条 Optional（preflight 只证 head 叶子 / serenity 结算块写入不在名单 / capstone 私密 writer 无自守卫 / state_dir AST 守卫实测只覆盖 1 个 child / 相对 private-root 行为变更）仍 open，别当作已解决。
- 桌面 `us_testrun1.md` 的问题 3 及之后各项尚未处理；本刀 PASS 只代表一键跑到 `weekly_bridge` 之前的路径不再自堵。

## 2026-08-11 追加：问题3 覆盖标签规范序 —— 独立审查 PASS（Claude Code reviewer/committer）

### 改了什么

- 只做审查与收口，未改本刀交付的代码或测试。新建并关闭 `R-USSHORT-COVERAGE-GAP-TAGS-ORDER-DEPENDS-ON-CALLER-MAPPING-ORDER`，另记流程 Optional `R-USSHORT-EXECUTOR-LANDED-A-SLICE-WITH-NO-SESSION-LOG-OR-REGISTER-ENTRY`；正文都在 register。

### 为什么改

- 执行方本轮只留了 5 个改动文件，SESSION_LOG / register / handoff 三处都没有条目，也没有 full-lane 记账。verdict 与证据必须有 durable 落点，否则下一个接手的人只能从 diff 猜。

### 验证命令

```text
固定解释器：C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe（3.13.8）
.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.test_us_short_coverage_honesty tests.test_us_short_result_source_linkage tests.provider.test_us_short_batch5_to_batch4_e2e tests.test_us_short_test_io_inventory tests.test_doc_governance_guard
python .tools\full_pack_ledger.py run us_short "<rule-6 escalation reason>" "receipt:cff9f819a009340f5f9c1df4" 860 -- discover -s tests -p "test_us_short*.py"
（探针）两种调用方顺序的 build_row_coverage 输出比对 + 漏项/多项/不支持类别三种坏输入 + 把循环还原成 caller 顺序的植入
```

### 验证结果

- 焦点超集：`Ran 105 / 32.1s / OK`，`receipt:cff9f819a009340f5f9c1df4`。
- 结构闭合性（静态）：`_GATING_CATEGORIES = frozenset(_SUPPORTED_COVERAGE_CATEGORIES)`，两者同集合且入参已校验 required ⊆ 该集合，所以「按规范序遍历 + 跳过非 required」恰好访问全部 required 项——不存在漏检某个已校验类别、把 worst-of 算轻的路径。这是本刀唯一值得担心的方向，已排除。
- 探针：两种调用方顺序输出逐字段相同（`gap_tags=['analyst:missing','event:blocked']`、`coverage_status='blocked'`）；Cut4 子集 `price`+`momentum` 得 `restricted`；漏项 / 多项 / 不支持类别三种坏输入全部仍被拒（闭世界没被顺带放宽）。
- 植入：循环还原成 `for category in required_categories` → 精确转红 4 条，含 `test_sorted_json_round_trip_preserves_multigap_source_fact`（ERROR，本 finding 的复现形态）与 `test_required_category_order_does_not_change_3_4_7_category_outputs` 的三种形状；还原后引擎 sha256 前后同为 `a5f54465…`。
- reviewer 自起 full lane（rule 6）：`discovered=5738 ran=5738 equal=True PASS`，735.8s，fingerprint `4dd172cfe749`，已记账。

### 失效的旧结论

- 上一节「问题 3 及之后各项尚未处理」中的问题 3 部分已失效：问题 3 已修复并通过独立审查。

### 下一步注意事项

- 实现方下一刀交审前请补 SESSION_LOG entry（含 Proof-of-use）并在 rule 3 触发时自行跑全量记账；本轮因两者都缺，reviewer 只能自补一次 736s 全量，墙钟被拉长。
- 桌面 `us_testrun1.md` 问题 4（checkpoint 能力）及之后各项仍未处理；问题2 遗留的 5 条 Optional 也仍 open。

## 2026-08-11 追加：桌面 us_testrun0810 问题1 Optional + 问题2 OHLCV source-packet→价格链修复（OPEN-NOT_VERIFIED）

### 改动

- 当前权威执行方案是桌面 `us_testrun0810.md`；`us_testrun1.md` 已不再作为本轮方案。
- 问题1 Optional recurrence guard 已按既有窄静态方案复核：点名 planted-failure 测试 `1 OK`，receipt=`receipt:8996ec08ef757a4374473b9c`；状态仍为 `repaired / OPEN-NOT_VERIFIED`，不得宣读为覆盖所有私密子目录。
- 问题2 的断点是 Pass2 丢失已有 `ctx.ohlcv_series_packet_path`。修复只做 A/B/C：weekly capstone Pass2 inputs 加 OHLCV 并升 contract `2.0.0→2.1.0`；stage 透传；source-packet runner/CLI 接收同一路径，复用既有路径校验，把 packet 相对路径和真实字节 SHA 写入 source packet，随后让 result linkage / Batch4 使用同一 OHLCV bars。没有新 schema、sidecar、manifest、digest identity 或 yfinance 行为改动。

### 证据

- 固定解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`（3.13.8）。问题2核心 `weekly=86 OK`、`source-packet=23 OK`、`batch5→batch4 e2e=11 OK`；inventory `18 OK`，receipt=`receipt:35fb887d8914d2c4feee52ef`。
- 反向植入：移除 adapter 的 OHLCV 透传后点名测试精确 `KeyError`/FAIL；恢复后 2 条相关测试 `OK`，receipt=`receipt:96452500059b2ef9adbb1043`。
- 精确桌面 focused package `130` 仍有唯一测试文件红：`test_tracked_artifact_digest_canonicalization` 的 8 个既有 A-short raw-digest 坐标；新增 OHLCV 坐标已用精确例外处理。未修改无关 A-short。
- full lane 在最终行为代码态只执行一次，`discovered=5740 ran=5740 equal=True PASS`，`360.5s/860s`；静态 `py_compile=7`、`git diff --check=PASS`。未调用 provider/network/live/account，未跑真实周任务。

### 交接边界与下一步

- 本轮不是“exact focused 全绿”或实盘/ship-gate 结论；`R-USSHORT-CAPSTONE-OHLCV-PRICE-LINKAGE-GAP` 为 `repaired / OPEN-NOT_VERIFIED`。
- Claude Code：独立审查问题1 Optional、问题2 A/B/C、精确 digest 例外、既有 A-short focused baseline 与 `5740/5740` full-lane 证据；若接受基线边界，再决定 Pass 或另开 A-short 修复。

## 2026-08-11 追加：问题2 OHLCV 价格链接线 —— 独立审查 PASS 并收口

### 改了什么

- 无生产代码改动（审查方不写业务代码）。本节记录对执行方 A/B/C 的独立复核结论与证据，并把 `R-USSHORT-CAPSTONE-OHLCV-PRICE-LINKAGE-GAP` 从 `repaired / OPEN-NOT_VERIFIED` 收到 `resolved`。

### 为什么

- 桌面权威件 `us_testrun0810.md` §问题2 要求的不是"source packet 多一个字段"，而是 bars 真到价格引擎。故本轮审查把重点放在消费侧整读与植入证伪，而不是复述执行方的红绿计数。

### 验证命令与结果

- 焦点超集（reviewer 亲跑）：`.tools\run_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.provider.test_us_short_weekly_capstone tests.provider.test_us_short_batch5_full_candidate_live_source_packet tests.provider.test_us_short_batch5_to_batch4_e2e tests.test_tracked_artifact_digest_canonicalization` → `Ran 130 / 77.4s / FAILED(failures=1)`，唯一红为既有 A-short digest 坐标（已归因、已单立 R-ID）。
- 植入探针（reviewer 自写）：抹掉 `_build_local_source_packet` 写 `packet_paths["ohlcv_series_packet_path"]` 的那一条 → 点名测试转红，红点落在生产门 `_validated_provider_envelope_digests`；还原后该文件 sha256 前后同为 `7dbc9e55…`。
- full lane：按 AGENTS rule 4 不重跑，引用执行方账本 `5740/5740 equal=True PASS 360.5s/860s`；reviewer 用 `full_pack_ledger.collect_code_state()` / `fingerprint()` 独立重算得 `0153257565f7a0e8…`，与账本记录逐字相同，证明该全量绑定当前 diff。

### 失效旧结论

- 上一节末尾"桌面 `us_testrun1.md` 问题 4 …"的表述失效：**自 2026-08-11 起 `us_testrun1.md` 已退役**，唯一权威清单是桌面 `us_testrun0810.md`（按严重度重排，编号与旧文不同：原问题1→#4、原问题2→#5、原问题3→#1）。
- "问题2 遗留的 5 条 Optional 仍 open"指的是 0810 的 **#5（原问题2，private_root 载体根）**，与本节的 0810 **#2（原问题11，OHLCV 价格链）** 不是同一条，别按编号串起来。

### 下一步注意事项

- 0810 清单里已写出完整「修复执行方案」而尚未动工的是 **#3（原问题7，analyst 覆盖源）、#6（原问题6，provider_health 八键）、#8（原问题5，Massive 429）、#9（原问题12，context_components 形状权威）、#12（原问题4，checkpoint 与操作员参数）**。
- **#3 是 #2 的必要配套**：本刀只解开 OHLCV 一条腿，`coverage_status` 仍会被 analyst 空壳压成 `restricted`，`final_action` 仍被强制转"观察"。**不得据本刀宣称"操作表会出现建仓"。**
- A-short 那条 digest guard 红由 A-short owner 处理，US-short 侧不要顺手改别人 lane 的 allowlist。

## 2026-08-11 追加：问题8 ETF total-return sidecar 429 恢复（1302，待 Claude 独立审查）

### 改动与边界

- ETF sidecar 的 Massive 请求按同一逻辑 page 重试，固定等待 `65s`、最多 `2` 次；记录 logical/physical/retry 计数并严格限制总物理尝试不超过 `40`（本方案的 `32` 个逻辑调用）。
- 持久 429 只使受影响 ETF family 降级，其他 family 继续完成；不把失败 family 伪装成 total-return 可用，不跨全局 cap，也不改变既有 26-week clock、settlement、cash return 或 ship-gate 语义。
- 入口仍是既有 `market_diagnostic_fetch`/sidecar 路径；没有新增 health 链。问题8共用的 one-click/Pass2/forward 预算边界、问题6 `massive_events` receipt/report 消费和 checkpoint retry-identity 反向测试记录在 `R-USSHORT-MASSIVE-429-RECOVERY-WIRING-GAP`。

### 验证与交接

- 固定主 Python：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`；ETF retry/持久降级/预算测试通过，问题8与既有问题6消费者 focused 超集 `249 OK`，最终 full lane `discovered=5773 ran=5773 equal=True PASS`，`392.8s/860s`。
- 验证为 fake client、临时根和离线 full lane；未调用 provider/network/live，未打开诊断时钟，未写真实市场诊断私有根。状态仍 `OPEN-NOT_VERIFIED`，下一步为 Claude Code 独立审查后按流程提交。

## 2026-08-11 追加：问题8 ETF Optional 修复（1302，待 Claude 独立复审）

### 判定与变更

- `O-P8-1`、`O-P8-2`、`O-P8-4` 均合理：此前 ETF physical pool 没有为剩余 logical request 保留初始槽位，整周全 429 仍写 captured sidecar，且窗口常量有重复来源。本轮增加 `_consume_physical_attempt` 预留逻辑，强制 `physical=logical+retry` 且不超过40；整周全 family 持久 429 且无成功页改为 `incomplete_no_count`/无 canonical sidecar，同日成功 rerun 可恢复；capacity、wait、max2 复用 `universe_fetch` canonical constants。
- ETF raw 的持久429路径使用新的 attempt leaf，恢复后不同字节可写入；非429成功页仍保留既有 write-once/digest 行为。混合 family 继续局部降级，不把失败 family 伪装成可用 total-return。

### 验证与边界

- ETF 模块 `18 OK`；问题8与既有问题6消费者 focused 超集 `415 OK`，receipt=`receipt:5328794d756e3be6929c54f6`；full lane `5779/5779 equal=True PASS`、`317/317`、`388.4s/860s`。
- 固定主 Python、fake client、临时根和离线测试；无 provider/network/live，未改变 26-week clock、settlement、cash return 或 ship-gate 语义。状态 `OPEN-NOT_VERIFIED`，待 Claude Code 独立复审。

## 2026-08-13 追加：问题12正式一键入口透传五个既有运行控制（1302，待 Claude 独立审查）

### 方案与责任边界

- 桌面 `us_testrun0810.md` 问题12的五个真实缺口是 `--max-retries-per-call`、`--retry-backoff-seconds`、`--max-total-http-attempts`、`--disable-soft-discovery`、`--disable-theme-soft-boost`。底层责任已经分别在 Problem8 的 retry normalizer/`HttpAttemptBudget` 与 Problem10 的 K4a/K4b/三态分类器中存在，本刀只补正式 paper one-click 的入口透传。
- 单一链为 `.cmd`（仅 `%*`）→ `us_short_paper_one_click.ps1` → `us_short_paper_one_click.py` argparse → `run_one_click()` → `run_weekly_capstone()` → 既有 retry/soft-channel owners。PowerShell 的 nullable 数字和 switch 只在显式给出时追加 argv；Python 省略值原样交给 capstone 的唯一归一化责任点。
- `auto_authorize_pass2_budget + resume_from` 的拒绝、手工 Pass2 budget/`--resume`/`--catalyst-recall-ticker` 不暴露、stage 顺序、checkpoint/receipt/schema/产物生命周期均保持原状；五个参数不持久化。

### 实施与验证

- 改动文件仅为 `runners/us_short_paper_one_click.py`、`runners/us_short_paper_one_click.ps1`、`tests/test_us_short_paper_one_click.py`；capstone、Problem8、Problem10 生产 owner 和 `.cmd` 未改。Python 测试覆盖显式五值到达 capstone、全部省略保持 `None/True/True`；PowerShell 同一临时仓两次调用覆盖 argv 无继承、数值/开关顺序和退出码透传。
- 旧实现红测：Python 显式参数为未知关键字、省略仍硬编码 `2/65`、PowerShell 显式参数为 `NamedParameterNotFound`；修复后固定主 Python 焦点超集 `248 OK`，receipt=`receipt:1f1d28ece8ab0a9553855354`。其中包含 `tests.test_us_short_discovery_conformance`、Problem8 retry、Problem10 K4a/K4b/分类器和现有 capstone 消费测试。
- 因修改生产顶层 one-click runner，按 rule 3(a) 执行官方 full lane。首跑在 `test_us_short_discovery_conformance_executable` 暴露 one-click 日期解析调用缺显式 `theme_soft_boost_enabled`；补上同一开关透传后以最终 receipt 完成 `5832/5832 equal=True PASS`，`318/318`，`416.3s/860s`，fingerprint=`917623ebe194d708f1e59cf2cde4ed490e0bac07d82eaa3872dcfadd569383b8`。
- `py_compile=2`、`git diff --check`、BOM/FFFD/冲突标记扫描通过；仅使用固定主 Python、fake PowerShell runner、临时根和离线 full lane。未调用 provider/network/live/paper，未写真实 `state/us_short`，未修改主树或桌面 guideline。

### 交接状态

- 风险条目为 `R-USSHORT-PAPER-ONECLICK-OMITS-EXISTING-RUNTIME-CONTROLS`，当前 `repaired / OPEN-NOT_VERIFIED`；需 Claude Code 独立审查后再决定 `resolved` 与提交。Codex 不提交、不 merge；后续若审查通过，下一刀才可按用户命令处理其他问题。
## 2026-08-13 追加：问题12 一键入口五项控制贯通——审查 PASS，已合入 master

**改了什么**：本节只记审查侧结论。范围三个代码/测试文件：`runners/us_short_paper_one_click.py`（argparse 三个 retry 值 + 两个 disable flag，`run_one_click` 原值转发）、`runners/us_short_paper_one_click.ps1`（两个 `[Nullable[...]]`、一个 `[Nullable[int]]`、两个 `[switch]`，只在显式给值时追加 argv）、`tests/test_us_short_paper_one_click.py`。`.cmd` 未改，仍 `%*`。

**为什么**：底层早有重试与关闭可选通道的按钮，最上层操作员入口按不到；桌面 §问题12 只要求贯通这五项，`--resume` / `--pass2-call-budget` / `--catalyst-recall-ticker` 明确不开。

**验证命令**：
- `.tools
un_unittest_with_repo_pythonpath.cmd --timeout-seconds 600 tests.test_us_short_paper_one_click tests.provider.test_us_short_weekly_capstone tests.provider.test_us_short_batch5_full_candidate_live_source_packet tests.test_us_short_soft_boost_consumption tests.test_us_short_discovery_conformance`
- reviewer 直跑真函数 `_normalize_capstone_retry_policy` 的九格转移表
- reviewer 三次源码级植入：逐条删掉 `run_weekly_capstone(...)` 的转发再跑 one-click 测试，`finally` 按字节还原并核 sha256 + `git diff --numstat`

**验证结果**：焦点超集 `PASS tests=180 elapsed=109.3s`、`receipt:86c660cbdb5fd9d4d28a9d04`。转移表：省略 + `auto_authorize_pass2_budget=True`（正式一键）→ `(2, 65.0)`，与被删掉的硬编码 `max_retries_per_call=2` / `MASSIVE_RATE_LIMIT_RETRY_SECONDS` 逐字等价；非 auto 仍 `(0, 0.0)`；`2+30`、`3`、`True`、`0+65` 全部在 provider 调用前被拒。三次植入（删 `theme_soft_boost_enabled` / `max_total_http_attempts` / `soft_discovery_enabled` 转发）每次都让 `tests.test_us_short_paper_one_click` 转红，还原后 sha256 与植入前相同、numstat 回 `32 3`。full lane 引执行方账本 `5832/5832`、`318/318`、`count_gate_equal=True`，独立重算指纹 `917623ebe194` 与记录及 `prepared_fingerprint` 一致。

**失效旧结论**：`R-USSHORT-PAPER-ONECLICK-OMITS-EXISTING-RUNTIME-CONTROLS` 转 `resolved`；「一键入口无法启用 429 重试」的旧描述不再成立（默认仍是 2 次 / 65 秒，且现在可显式覆盖）。

**下一步注意事项**：
- 问题8 仍是 retry/物理预算的唯一 owner（`_normalize_capstone_retry_policy` 出自 `8fb7f2d4`，本刀一行未改），问题10 仍是 soft-boost 三态唯一 owner；后续别在一键层再加第二套校验或默认值。
- `runners/us_short_weekly_capstone.py:2189` 的 `include_soft_discovery=ctx.soft_discovery_enabled` 耦合**必须继续保留**：靠它，`--disable-soft-discovery` 才是把 K4a stage 整个移出 pipeline（问题10 判为正常 `NOT_REQUESTED`），而不是让 stage 发出 `disabled` 回执再被 degrade 成 `zero_invalid_evidence`。
- 按 0810 去重后的顺序，下一刀是**问题11 + 问题13 同一刀（先 11 后 13）**。

## 2026-08-13 追加：问题11→问题13统一 stage outcome（1302，repaired / OPEN-NOT_VERIFIED）

### 实现边界

- 按桌面 us_testrun0810.md 先处理问题11，再处理问题13；两者共用 weekly capstone 的唯一 outcome owner。问题11没有新增 Web/X、Serenity 或 maturity producer，只消费本轮既有 typed status/reason/count。
- runners/us_short_weekly_capstone.py 增加单一 normalizer 与 terminal recorder：stage_outcomes 与原 stages 同序、同 execution_mode；四项 stage_outcome_counts 从列表现场派生。十个特殊 stage 的 completed/no-work/waiting/failed 映射只定义一次，未知 typed result 统一 fail-closed。
- input unreadable、stage exception、fresh output missing 三类既有 nonblocking 出口均记录失败行并发 stage_failed；同轮多失败不覆盖，后续合法 stage 继续。删去旧 shadow_capture_failure / shadow_capture_failed 单数生产投影，不新增第二失败列表。
- runners/us_short_paper_one_click.py 只读取 capstone summary：stderr 输出四类短表和全部非 completed 行，stdout 仍是一份合法 JSON；capstone_completed 不复制 counts，runner_completed 只带一次 counts。emit/no-emit、退出码、官方发布和诊断不阻断边界未改。

### 验证与自审

- 固定主 Python C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe。桌面焦点超集通过：297 tests，receipt=receipt:d3c118348035d8b8e1860d47；唯一 full lane 终态为 discovered=5838、ran=5838、equal=True、PASS，388.2s/860s，fingerprint=db1b9e1ee4a1；文档门 55 OK，receipt=receipt:a70c10eae9dce137bfccecbf。
- 四个实际代码/测试文件 py_compile=4、git diff --check=PASS、BOM/FFFD/冲突标记扫描 PASS。测试覆盖十 stage mapping、valid-empty/no-work/waiting、问题10 artifact-invalid 对照、三类同轮失败与 missing-output terminal event、executed/reused/refreshed/no-emit、one-click stdout/stderr proof。
- 自审确认无新 schema/sidecar/registry/hash/fingerprint/runtime receipt/checkpoint 字段；无 provider/live/paper/真实 state 写入；问题6 health、问题9 shape、问题10三态、问题14成败计数和问题11 producer 边界未被复制或改写。

### 交接状态

- 风险登记：R-USSHORT-CAPSTONE-STAGE-OUTCOME-TRUTHFULNESS-GAP，状态 repaired / OPEN-NOT_VERIFIED。两道文档门需在本轮落盘后执行；独立审查尚未发生，不能宣称问题11/13已最终关闭。
- Claude Code：请独立核对十项 mapping、多失败保全、fresh-output terminal event、两个 summary 返回路径以及 one-click 同一 counts 消费；PASS 后由 Claude 按项目规则提交，本 Codex 不提交。

### 后续执行项：纯文档门不得覆盖仍有效的代码 focused receipt

- **执行责任与时点**：本项由 Codex 在问题11/13独立审查并合入后的后续独立小刀执行；本轮只记录方案，不改验证工具。目标是消除“先跑较大代码焦点包，最后两道文档门覆盖 singleton receipt，提交前被迫原样重跑焦点包”的重复耗时。
- **最小方案**：只调整 `.tools/bounded_unittest.py` 的 receipt 写入判定。若本次 invocation 仅运行项目既定的纯文档门，并且盘上 focused receipt 对当前非文档代码 fingerprint 仍校验有效，则文档门照常执行和报告 PASS/FAIL，但不得覆盖该 receipt。代码态变化、原 receipt 无效/缺失或普通代码焦点测试运行时，仍沿现有逻辑生成新 receipt。
- **窄作用域**：纯文档门只按现有明确测试入口识别（当前为 `tests.test_route_doc_ledger_status_consistency` 与 `tests.test_doc_governance_guard`），不按 `bundles=[]`、测试数量、名称模糊匹配或“看起来像文档测试”猜测；因为正常代码焦点包也可能是 `bundles=[]`。不新增第二个 receipt、sidecar、schema、hash、CLI flag 或并行验证系统。
- **必须保留的安全门**：`.githooks/pre-commit` 对 staged 非文档代码的 hard gate 不删除、不降级；receipt 继续绑定固定主 Python、当前代码 fingerprint、真实 PASS/正测试数和完整性 ID；`full_pack_ledger.py` 继续只接受与当前代码态和 token 一致的 focused evidence。文档门失败仍必须返回失败，不能因保留旧 receipt 而被吞掉。
- **回归闭合判据**：①先生成有效代码 focused receipt，再跑两道文档门，测试正常通过且 receipt 文件字节/ID不变；②代码改一字后旧 receipt 必须失效，文档门不得把它“续命”；③无 receipt 时跑文档门不得伪造代码 receipt；④再跑普通代码焦点包必须生成新 receipt；⑤pre-commit、verification_receipt、bounded_unittest 与 full_pack_ledger 相关既有测试保持绿。
- **完成边界**：这项只优化验证证据生命周期，不能据此少跑方案要求的首次焦点包、条件触发的唯一 full lane 或两道文档门；省掉的仅是文档门之后为恢复 singleton receipt 而重复执行的同一焦点包。实现后按正常流程落风险/SESSION_LOG/本 handoff，并交 Claude Code 独立审查；Codex 不提交。
## 2026-08-13 追加：刀11+13 stage outcome 真实性——审查 FAIL（两格分类把真相说反了）

**改了什么**：本节只记审查侧结论。被审范围 `runners/us_short_weekly_capstone.py`（+248/−61，新增四类 outcome normalizer 与单一 terminal recorder）、`runners/us_short_paper_one_click.py`（+28/−1，stderr 短表）及两份测试。

**为什么 FAIL**：骨架成立，但十格映射表里两格与产出端/方案不符——
1. `market_diagnostic_settle` 只认 `settle_status == "settled"`，而真实链路给的是 `published` / `idempotent` / `recovered`（`engine/us_short_market_diagnostic_lifecycle.py:682/704/772` → `_settle_outcome`（`runners/us_short_market_diagnostic_weekly_fetch.py:752`）只在上游缺 `status` 时才退化成 `"settled"`）。**结算真正成功的那一周被判成 `failed_nonblocking / OUTCOME_CONTRACT_UNRECOGNIZED`。**新表测试钉的 `"settled"` 来自把 `settle_week` mock 掉的夹具，所以全绿也照不出来；仓库自己的 e2e 在三处断言 `{settled, published, recorded}`。
2. `weekly_bridge` 的 no-emit 一律 `no_work_expected`，但 `no_emit_reason` 有两种语义（`engine/us_short_weekend_orchestrator.py:391` 的 `out_of_window` vs `:401` 的 `provider_health_*`）。provider 被挡那周，一键短表会打出 `waiting_dependency=0 failed_nonblocking=0`。同时与桌面 §问题13 两处明写的 `completed_work` 相悖，且 register/SESSION_LOG 无偏离说明。

**验证命令**：
- `.tools
un_unittest_with_repo_pythonpath.cmd --timeout-seconds 900 tests.provider.test_us_short_weekly_capstone tests.test_us_short_paper_one_click tests.provider.test_us_short_weekly_capstone_soft_discovery tests.test_us_short_serenity_quality_forward tests.test_us_short_market_diagnostic_weekly_advance tests.test_us_short_market_diagnostic_weekly_producer tests.test_us_short_capstone_checkpoint`
- reviewer 三次源码级植入（failure 整类 / 问题10 ARTIFACT_INVALID / 非 dict 兜底），`finally` 按字节还原
- 独立对抗 agent（只读、探针在 scratchpad）

**验证结果**：焦点超集 `PASS tests=297 elapsed=103.7s`、`receipt:54a33b35cf07f386c923e167`；full lane 引账本 `5838/5838`、`318/318`、gate True，独立重算指纹 `db1b9e1ee4a1` 与账本及 prepared 一致。植入：前两次精确转红（`failures=7` / `failures=1`），第三次**仍绿**（非 dict 兜底无人钉，记 `O-K13-6`）；三次均按字节还原、numstat 回 `248 61`。十格表其余九格与方案逐条一致。

**失效旧结论**：register 里「emitted=true / honest emitted=false / dry-run 三条返回路径都带同一 outcome 投影」不准确——`_run_pass2_budget_preview` 是第四条且不带（`O-K13-5`）。

**下一步注意事项**：
- 修 `market_diagnostic_settle` 时不要在 normalizer 里另造别名，按产出端真实词表对；并把测试夹具从 mock 出来的 `"settled"` 换成真实产出值，否则同一个洞下次照旧照不出来。
- 另外九个 stage 的成功值与产出端的逐条对照是 agent 做的、不是我做的，修复轮需给出逐条对照结果。
- `weekly_bridge` 若认为方案的 `completed_work` 不对，可以改，但必须在 register 写明理由——静默偏离方案是这次被记 Required 的一半原因。
- 1302 当前落后 master 2 个提交（实测零 us_short 重叠），修复轮开工前先 ff-only 同步，避免 receipt 与账本作废两次。

## 2026-08-13 追加：纯文档 focused receipt 保留修复（1302，repaired / OPEN-NOT_VERIFIED）

### 十格双向差集（改代码前）

| 维度 | D-C | C-D |
|---|---|---|
| 入口参数 | 两道文档门模块只在文档集合 | 两道 effect-contract 模块只在代码集合 |
| 路径边界 | `docs/*.md` 与根 `.md` 不进 code scope | `runners/*.py`、`engine/*.py` 进 code scope |
| fingerprint | 文档改动保持代码 fingerprint | 代码内容改动改变 fingerprint |
| bundle | 文档门 `()` | effect-contract 组合为 `a_short_effect_contract` |
| receipt side effect | 修前文档门会写/覆盖（唯一差集） | 修前代码焦点写入（正确行为） |

### 实现与闭合

- `.tools/bounded_unittest.py` 只识别精确的两模块文档门集合；顺序可交换，额外参数、重复参数和普通代码焦点不匹配。匹配时不采集 code state、不调用 receipt writer；PASS 输出固定 `DOC_ONLY - acceptance receipt left untouched`。失败仍返回原失败状态。
- `tests/test_bounded_unittest.py` 新增十格入口反控、已有 receipt 保留、无 receipt 不伪造、普通代码焦点仍写入四类承重测试。未修改 `.tools/verification_receipt.py`、`.githooks/pre-commit` 或 `.tools/full_pack_ledger.py`。
- 固定主 Python 焦点：`tests.test_bounded_unittest tests.test_verification_receipt`，`32 tests OK`，receipt=`receipt:14660bdd054cd4b7806bbe46`。随后两道文档门 `55 tests OK`，输出 DOC_ONLY，receipt 前后 ID 与字节均未变化；py_compile=2、git diff --check、BOM/FFFD/冲突扫描和 verification receipt PASS。
- 本刀是验证工具面，full-lane=`not_triggered`；未调用 provider/network/live/paper，未写真实 `state/us_short`，未改主树或桌面文档。状态保持 `repaired / OPEN-NOT_VERIFIED`，待 Claude Code 独立审查。
## 2026-08-13 追加：文档门不再覆盖代码 receipt——审查 PASS，已合入 master

**改了什么**：本节只记审查侧结论。范围两个文件：`.tools/bounded_unittest.py`（+22/−2，新增 `_is_document_only_focused_run` 与两处 `not document_only` 短路）、`tests/test_bounded_unittest.py`（+70，三条直接测试）。

**为什么**：此前任何 focused 运行都写 receipt，于是「跑焦点包 → 跑两道文档门 → 提交」这个正常顺序会让文档门那次把代码 receipt 覆盖掉，pre-commit 报 `focused acceptance receipt does not match the current code state`。本会话我为此多跑过两次焦点包。

**验证命令**：
- `.toolsun_unittest_with_repo_pythonpath.cmd --timeout-seconds 600 tests.test_bounded_unittest tests.test_verification_receipt tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency`
- reviewer 直跑真 `_is_document_only_focused_run` 的七格识别表
- reviewer 两次源码级植入（放宽成超集 / 删去重守卫），`finally` 按字节还原并核 sha256 + `git diff --numstat`

**验证结果**：焦点超集 `PASS tests=87 elapsed=29.7s`、`receipt:fb613d3ba8b7c6ca6455c5b5`——这一跑本身就是反证，参数含那两个文档模块但共 4 个，识别器没当成文档门，receipt 照常写出。七格表：恰好两模块与顺序颠倒为 True，其余五格（重复、单个、两文档+一代码、一文档+一代码、空）全为 False。植入放宽成超集 → `failures=1` 精确转红；植入删去重守卫 → 仍绿，随即证明该条件冗余（`[a,a]` 在 `len==2 and set==DOC_SET` 下本就 False），记 `O-DOCGATE-1`。

**失效旧结论**：此前几轮交接里「跑完文档门要重跑一次焦点包才能提交」的操作提醒不再需要——但仅限恰好那两个文档模块单独跑的情况；混进任何第三个参数仍会正常写 receipt。

**下一步注意事项**：
- 该改动只能**不写** receipt、不能**伪造**；pre-commit 侧仍按当前代码指纹校验，旧 receipt 不会因此变得可用。
- 刀11+13 本轮零改动，`runners/us_short_weekly_capstone.py` sha 仍是上轮 FAIL 时的 `86e50ba3d9d9d5ee`；`R-USSHORT-MARKET-DIAGNOSTIC-SETTLE-SUCCESS-VALUE-IS-NOT-IN-THE-OUTCOME-TABLE` 与 `R-USSHORT-WEEKLY-BRIDGE-NO-EMIT-COLLAPSES-TWO-DIFFERENT-REASONS` 两条 Required 及 6 条 Optional 全部原样 open，是下一刀的内容。
- 1302 当前落后 master 4 个提交，刀11+13 修复轮开工前先 ff-only 同步。
