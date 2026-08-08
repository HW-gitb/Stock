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
