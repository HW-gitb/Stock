# US-short 26 周市场表现诊断轨 — 刀0设计契约

> 状态：Knife 0 contract baseline  
> 性质：诊断轨；不改变 US-short 选股、操作建议、paper 账户或 Ship gate。  
> 本文件是仓库内执行契约；桌面另有一份执行总方案（`usshort-compare.md`，不在仓库内，路径见会话记录）。

## 1. 目的

验证完整 US-short model-paper 账户相对固定美国市场基准的表现：

最终选股 → 最终操作建议 → 仓位与现金 → 跨周持仓 → 成本后 NAV

不使用 Top 15 等权收益代替完整账户收益。

本轨只能回答过去固定窗口的事实，不能预测未来，不能证明永久 alpha。

## 2. 固定边界

每个周记录和摘要都必须满足：

- diagnostic_only = true
- comparison_only = true
- counts_ship_gate = false
- changes_selection_or_action = false
- automatic_policy_switch = false
- broker_or_order_automation = false

诊断失败只能生成 unavailable 或数据降级状态，不得阻断正式 weekly report、选股、操作建议或 paper 结算。

诊断开关打开或关闭时，最终选股、action table、sizing、model-paper 状态和 NAV 必须相同；唯一允许变化的是已注册的 lifecycle reminder 区块。

## 3. 账户启动和本地输入

US-short 当前仍是工作基线，设计尚未完成。现在必须保持：

- `diagnostic_start = null`；
- `diagnostic_epoch = unset`；
- `clock_status = not_started`；
- 不产生第 1 周，不做历史回填。

26 周时钟的唯一启动门是：未来由 Codex 完成设计审计后明确发出独立的 `设计完成` 通知，并在同一操作生成 source-bound、不可变、幂等的 `diagnostic_start_receipt`。通知、receipt、冻结的首个 canonical decision week 三者缺一，生命周期写入必须 fail-closed。`2026-06-20`、本文件日期、部件完成日期、账户播种日期和任何历史提交都不是起点。

10 万美元是一次性播种的归一化 model-paper 本金，不是真实账户资金。刀0不播种账户、不创建 head_manifest、不生成启动 receipt、不启动26周时钟。

正式 model-paper 路径启动后，必须先产生：

- 私有 head_manifest；
- 当前 portfolio state；
- 首份真实已结算 settlement；
- 首份 nav_snapshot。

启动 receipt 冻结的首个 canonical decision week 才是第 1 个 calendar week；起点由未来的完成通知确定，不由某个部件何时建完决定。首份真实已结算 `nav_snapshot` 只决定该周是否可评估，不得推迟或重置时钟。若启动后某周因部件或数据缺失不能评估，必须记为 `no_count` / `unavailable`，仍占一个日历周；禁止 fixture、历史回填、事后重建和未来数据。

策略侧每周从私有 model-paper store 读取：

- head_manifest.json；
- weeks/<decision_date>/settlement.json；
- weeks/<decision_date>/portfolio_state.json；
- weeks/<decision_date>/nav_snapshot.json。

这些文件提供现金、持仓市值、NAV、累计盈亏、累计成本、订单结果、paper_evaluable、降级原因和来源摘要。诊断轨不读真实手工账户。

## 4. 价格收益先积累

账户正式启动后，v1允许先保存价格型诊断收益：

- 策略侧保存 diagnostic_nav 和价格型周收益；
- 基准股息不完整时保存 price_return_diagnostic；
- 策略侧 paper_evaluable = false 时，该周只能保存观察数字；
- strategy paper_evaluable = false 的周不计入 joint_evaluable_weeks，不得显示 ahead 或 behind；
- 策略侧 paper_evaluable = true 后，基准若只有价格收益，结果仍标记 data_degraded；
- 任何可评估基准都必须带 price packet 日期、来源和 SHA；`total_return_evaluable` 还必须带已绑定的 dividend sidecar SHA，`unavailable` 不得导出 dividend sidecar SHA；周记录的 `source_refs` 必须逐项包含这些证据 SHA；
- 缺失股息不得填零、不得静默换基准、不得使用固定年化股息率。

## 5. 时间和窗口

使用固定、互不重叠的26个 canonical decision weeks：

- 第1—26周；
- 第27—52周；
- 第53—78周；
- 以后依次类推。

同时保存 since-inception 累计结果，但不能替代固定区块结果。

每周保存：

- calendar_week_index；
- window_id；
- decision_date；
- valuation_date；
- 每个基准的 price_date、price_source、price_packet_sha256 和数据质量；
- strategy_evaluable；
- joint_evaluable；
- total_return_evaluable；
- price_only；
- no_count。

第25周不生成26周摘要，第26周生成一次。重复运行必须幂等。no_count 周保留在窗口分母，不补收益、不延长窗口。

单个基准至少有20个 joint_evaluable_weeks 才允许 ahead_diagnostic 或 behind_diagnostic。

本轨26周时钟与 A1 24/36 divergence weeks、Ship gate 24/36个月检查完全分离。

## 6. 固定基准

四个基准在第一个计数周之前冻结：

- VTI：Ship gate 经济基准连续性；
- IWB：Russell 1000 可交易 ETF 代理；
- SPY：美国大盘和大型股敏感性；
- QQQ：科技成长风格敏感性。

IWB 是 ETF 代理，不是 Russell 1000 指数本身。禁止结果出来后挑选最有利基准。

## 7. 数据质量

严格总回报：

拆股调整价格 + 对应股息现金流

每个基准每周标记：

- total_return_evaluable；
- price_return_diagnostic；
- unavailable。

现有 Massive 公司行动探针只作为接口形状和受限样本证据复用。刀0不重复创建通用探针。

刀5另行完成四个 ETF 专用 coverage/reconciliation sidecar，至少核对：

- SPY、QQQ、IWB、VTI 股息历史；
- 分页；
- ex_dividend_date、cash_amount、split_adjusted_cash_amount；
- adjusted/unadjusted 价格一致性；
- 每周 total return 可重复计算。

刀5真实 provider 调用必须单独授权；raw 只进 gitignored 私有目录；tracked 摘要不得包含 secret、request URL、原始价格或原始事件行。

## 8. v1 指标

对策略和每个基准计算：

- 周收益；
- 26周累计收益；
- since-inception累计收益；
- 每周算术超额收益；
- 复利相对财富；
- 最大回撤；
- 超额收益 Information Ratio；
- HAC/Newey-West t 值；
- 平均现金比例和股票比例；
- 累计交易成本；
- 换手率；
- 未成交数量；
- no_count 数量；
- 数据覆盖率；
- ruleset fingerprint 分段。

HAC t 值只作描述，不作自动通过、失败或策略切换。

## 9. v1.1 提醒和时机

v1只回答总成绩；v1.1解释总成绩来自仓位、现金，还是主动系统效果。

v1.1 代码可以提前存在，但运行态必须按以下机器规则自动启用，不依赖人工记忆：

- 启用前只统计连续、真实、`paper_evaluable = true` 的周；
- 任一 `false` / `no_count` / `missing` 周把连续计数清零；
- 第 4 个连续真周结算后，状态自动变为 `active`，下一周开始实际归因；
- 激活时生成确定、不可变的 `attribution_epoch`；重复运行不得重复激活；
- 激活后保持 active，后续缺数据只让该周归因为 `unavailable`，不自动停用；
- v1.1不重置v1的26周时钟；
- v1.1不回填激活前无法按原时点重现的历史归因。

从第1个 calendar week 起，weekly report 的 lifecycle reminder 必须显示：

未激活时显示：`v1.1 归因：等待自动启用；当前连续 paper_evaluable=true 周=X/4。作用：解释领先或落后主要来自仓位和现金，还是来自主动系统能力。`

激活后显示：`v1.1 归因：已自动启用；缺少 VTI 总收益、PIT 现金收益或 g* 时只报 unavailable，不补零、不停用。`

## 10. 状态

允许的整体状态：

- ahead_diagnostic；
- behind_diagnostic；
- mixed_across_benchmarks；
- data_insufficient；
- data_degraded；
- unavailable。

少于20个 joint_evaluable_weeks 时只能 data_insufficient。缺失或价格-only 数据必须保留降级原因。

v1.1 reminder 状态：

- pending；
- active。

## 11. 规则版本

每周保存 strategy_ruleset_fingerprint。26周窗口不因主规则升级自动重置，但报告必须展示窗口内版本和分段周数。

诊断 preset、基准集合、收益计算方法、窗口计数规则或数据质量口径改变时，开启新的 diagnostic_epoch。

## 12. 存储

私有逐周记录：

    state/us_short/market_diagnostic_private/

去标识化摘要：

    research/results/us_short/market_diagnostic_26w/

## 12.1 Machine-bound v1 summary and status contract

The v1 summary schema must carry the metrics promised in section 8. The following block is the canonical field list used by the schema test; values are null when the metric is not calculable, never silently replaced with zero.

```json
{
  "v1_summary_strategy_metric_fields": [
    "since_inception_return",
    "cash_ratio",
    "equity_ratio",
    "turnover",
    "unfilled_order_count",
    "data_coverage"
  ],
  "v1_summary_benchmark_metric_fields": [
    "information_ratio",
    "hac_t",
    "data_coverage"
  ],
  "status_priority": [
    "unavailable",
    "data_insufficient",
    "data_degraded",
    "mixed_across_benchmarks",
    "ahead_diagnostic",
    "behind_diagnostic"
  ]
}
```

The weekly strategy status and the summary strategy status use the same three values: `evaluable`, `diagnostic_data_degraded`, and `not_evaluable`. The summary `overall_status` uses the six-value priority list above. `mixed_ruleset_window` is true when more than one strategy ruleset fingerprint appears in the 26-week window and no single fingerprint has at least 20 strategy-evaluable weeks; it blocks a single-ruleset performance claim.

Each benchmark summary may additionally use `flat_diagnostic` when its own joint compounded excess is exactly zero. `mixed_across_benchmarks` remains an overall cross-benchmark status and is never used to label one benchmark's individual tie. A flat benchmark does not make the overall result ahead or behind; the overall six-value status contract stays unchanged.
When all four benchmark statuses are `flat_diagnostic`, the overall status remains the non-directional `mixed_across_benchmarks` bucket, but the reason must be `all_four_benchmarks_show_flat_diagnostic_excess`; it must not claim that benchmark directions are non-uniform.

## 12.2 Knife 1 calculation contract

刀1的计算器是纯函数：调用方传入已经准备好的周记录，计算器不读取账户文件、不联网、不调用 provider，也不改变选股、操作建议、仓位或 NAV。

- 策略周收益优先由 `prior_nav` 和 `nav` 构造；首周使用冻结的 `100000.000000` 归一化本金。记录中若同时有 `weekly_return`，必须与构造结果一致；`no_count` 周不补零；
- 复利财富从 1 开始，累计收益不年化；`raw_excess` 是 joint 周内策略复利财富减基准复利财富，`relative_wealth` 是 `(1 + 策略累计收益) / (1 + 基准累计收益) - 1`；
- Information Ratio 使用周算术超额收益的样本标准差，不年化；HAC 使用 Newey-West、`lag = min(4, n - 1)`，只作描述；
- 任一基准少于 20 个 `joint_evaluable` 周时不得给 `ahead_diagnostic` 或 `behind_diagnostic`；price-only 或缺失数据保留 `data_degraded` / `unavailable`，不把缺失改成零，也不替换基准；
- 26 周始终是分母；窗口为 `1—26`、`27—52`、`53—78` 等互不重叠区块。重复触发同一个 `window_id` 返回幂等的“不再触发”；
- 每周记录可带 `turnover` 和 `unfilled_order_count`。缺失时摘要输出 `null`，而不是伪造 0；
- epoch 混入同一摘要窗口会 fail-closed；ruleset 按连续区段输出，并在单一 ruleset 不足 20 个可评估周时设置 `mixed_ruleset_window`。

私有路径必须受 gitignore 和 fail-closed 路径保护。公开摘要不得包含 ticker、逐笔交易、持仓明细、真实账户余额、原始价格或可还原个人账户的信息。

**归一化模拟金额裁决（2026-08-05 用户定，刀0 冻结口径成立）**：公开摘要**允许**携带 model-paper 归一化模拟盘的金额字段（`final_nav`、`cumulative_cost_paid` 等，见 `schemas/us_short_market_diagnostic_summary.schema.json`）。它们由固定的 $100,000 归一化本金推出，**不是用户真实账户余额、也不可反推真实资金规模**，故不属上句「账户余额」之禁。上句的禁止对象是**真实**账户余额与真实持仓。本裁决是对刀0 已冻结 schema 与本节措辞之间歧义的收口，不得据此把任何真实账户数字放进公开件。

## 12.3 Knife 2 local adapter contract

Knife 2 的本地适配器是 `engine/us_short_market_diagnostic_local_adapter.py`，输入契约是 `schemas/us_short_market_diagnostic_local_price_packet.schema.json`。它只读，不写入 model-paper store，也不推进 `head_manifest`。

- 策略侧先通过既有 model-paper store 的 `head_manifest` 校验，再读取指定结算周的 `settlement.json`、`portfolio_state.json` 和 `nav_snapshot.json`；三份文件必须互相绑定，最近结算还必须与 head 指针一致。
- 价格包固定包含 VTI/IWB/SPY/QQQ。`grouped_market_window` 可继续提供 SPY/QQQ，`local_etf_price_packet` 提供 IWB/VTI；适配器不根据结果替换或挑选基准。
- 价格包的 `settlement_decision_date` 是被读取的 `weeks/<decision_date>/` 目录日期；输出记录的 `decision_date` 是结算完成后可观察该周的报告决策日期，`valuation_date` 必须与 NAV 和价格日期一致且不晚于输出决策日期。
- 价格包每个基准同时保存 `prior_price_date` 和 `price_date`；只用拆股调整收盘价构造价格型周收益。可选的股息 sidecar 已接入本地适配器：完整且与价格包区间逐周一致时升级为 `total_return_evaluable`，否则保留 `price_return_diagnostic` 和明确原因；缺价格或缺前值则输出 `unavailable`，绝不填零，且不导出 dividend sidecar SHA。
- 适配器、sidecar 校验器和生命周期写入都接受可选 `as_of_date`；决策日、估值日、价格区间和 sidecar 事件/观察时间晚于该日期时 fail-closed。
- 每周输出保留价格日期、来源、价格包 SHA 和源 digest，随后由刀3负责不可变周记录、26 周计数器和 reminder 接线。适配器不调用 provider、不创建 10 万美元账户、不读取真实手工账户、不改变选股、操作建议、仓位、NAV 或 Ship gate。

## 12.4 Knife 3：不可变逐周记录、26 周计数器和 v1.1 reminder

刀3的实现入口是 `engine/us_short_market_diagnostic_lifecycle.py`，窗口身份、起止周和 `calendar_weeks` 统一由计算引擎的 `window_containing_week()` 生成；私有输出根是：

    state/us_short/market_diagnostic_private/

每次只能接收已经由刀2从 settled model-paper 周构造好的 weekly record。第一条必须是 `calendar_week_index = 1`；之后只能按 `+1` 追加，不能跳周、回填或把不同 `diagnostic_epoch` 静默混在一起。重复提交完全相同的周返回幂等结果；修改同一周的任何内容则 fail-closed。

逐周文件写入 `weeks/<decision_date>/weekly_record.json`，首次写入后不可变；`lifecycle_register.json` 只保存每周文件的相对路径、SHA、周号、日期和 `strategy_evaluable` 标记，以及由这些文件重新计算出的累计数。寄存器不保存 ticker、持仓、订单或账户金额。寄存器缺失、周文件孤儿、SHA 不一致或累计数不是由逐周文件推导出来时拒绝继续。

v1.1 的触发口径是 weekly record 中 `strategy.paper_evaluable = true` 的**连续周**，不是累计 `strategy_evaluable` 周数。启用前遇到 `paper_evaluable = false`、`no_count = true` 或 missing 周，连续计数归零；第 4 个连续真周结算后自动激活并生成确定的 `attribution_epoch`，从下一周生效。激活后状态保持 `active`。每周生成的 `us_short_market_diagnostic_v1_1` reminder block 注册到周报第12节，显示日历周数、累计可评估周数、连续可评估周数、当前状态和大白话作用说明。Knife3 负责自动激活状态，Knife6 负责归因计算；Knife7 负责把两者接入正式周任务。

刀3的写入只写诊断轨私有目录；`provider_fetch=false`、`account_write=false`、`changes_selection_or_action=false`、`automatic_policy_switch=false`、`counts_ship_gate=false`。当前真实 model-paper 私有根尚未启动时，不创建 head、不生成虚假的第1周；刀3只通过临时夹具验证该接线。

## 12.5 Knife 4：26 周聚合器与公开报告

Knife 4 的实现入口是 `engine/us_short_market_diagnostic_aggregator.py`，输入只来自 Knife 3 已校验的私有 settled weekly records；它不读取 provider、真实账户、持仓明细或订单，也不创建 10 万美元 model-paper 账户。

- 只有当最后一条记录正好落在 `26`、`52`、`78` 等 canonical 边界时才生成报告；不足 26 周、缺周、断档或窗口不完整时返回“尚未到期”或 fail-closed，不凑数、不补零；
- 报告同时保留当前 26 周固定区块和从第 1 周到当前的 since-inception 视图。固定区块继续复用 Knife 1 的四基准、状态、数据质量、成本后 NAV、回撤、现金/权益比例、turnover、joint 周数、IR 和 HAC 等既有字段；本刀不改 Knife 0 已冻结 schema，也不新增“周收益波动”字段；
- 四个基准始终是 `VTI`、`IWB`、`SPY`、`QQQ`，不按结果替换。没有合格 ETF 股息 sidecar 的周仍明确标成 `price_return_diagnostic` / `data_degraded`，不能冒充 total return；
- `ruleset_segments` 同时记录固定区块和 since-inception 的 epoch/ruleset 连续分段，防止跨规则版本把成绩混成一个结论；
- 公开 JSON/Markdown 只允许机器化 `status_reason`、安全的 epoch 标识和固定的 v1.1 reminder 文案；内部周记录中的自由文本不得直接进入公开报告；
- 去标识化报告输出到 `research/results/us_short/market_diagnostic_26w/`，每个窗口一对 `<window_id>.json` 和 `<window_id>.md`。JSON 是机器接口，Markdown 是人读摘要；不写逐周原始记录、持仓、交易、原始价格或可还原个人账户的信息；
- 写入采用确定性字节序列：同一窗口重复运行返回幂等；只存在 JSON 或 Markdown 的半成品、或内容冲突时拒绝覆盖，避免产生两份不同成绩单；
- 报告只是比较诊断，不改变选股、最终操作建议、仓位、NAV 或 Ship gate。当前真实 model-paper 私有根尚未启动时，不会生成实际第 26 周成绩单，测试只用临时夹具验证逻辑。

## 12.6 Knife 5：四 ETF total-return sidecar

Knife 5 的离线实现入口是 `engine/us_short_market_diagnostic_total_return.py`，输入契约是 `schemas/us_short_market_diagnostic_etf_total_return_sidecar.schema.json`，由 `engine/us_short_market_diagnostic_local_adapter.py` 作为可选输入接到每周记录。它只消费已经捕获并绑定来源的 sidecar，不在复算器内选择 provider、发请求或写入 raw 数据。

- sidecar 固定覆盖 `VTI`、`IWB`、`SPY`、`QQQ`，按 `window_id`、`diagnostic_epoch`、`calendar_week_index` 和 `valuation_date` 与本地价格包逐周对齐；
- 每个 ETF 周必须记录分页、股息、拆分、adjusted/unadjusted 对账状态，以及 adjusted price、unadjusted price、股息、拆分、raw capture 的 SHA、来源日期和带时区的 `observed_at`；所有事件日期必须落在 sidecar 自己的 prior price date（不含）到 price date（含）的区间内，并由本地价格包再次提供该区间作外部绑定；
- 完整周按已拆分调整的价格基础计算 `(split_adjusted_close + split_adjusted_cash_dividends) / prior_close - 1`，并升级为 `total_return_evaluable`；周记录用 `dividend_sidecar_sha256` 绑定该 ETF 的 sidecar 观测，sidecar 自己保留完整 `source_refs`；
- 单个 ETF 的 sidecar 观测缺数据、分页未完成、股息/拆分未完成、日期不匹配或 adjusted/unadjusted 未对账时，只把该 ETF 周保留为 `price_return_diagnostic` 并附原因；已有价格收益积累继续，不补股息、不补零、不替换基准。若整个 sidecar 结构或来源绑定不合规，则整包 fail-closed，不生成伪造的升级结果；
- 价格不可用时 sidecar 摘要不进入该周公开基准记录；任何巨整数、非有限数和未来日期均转换为本模块的 typed error，不把底层 `OverflowError` 等异常泄露给调用方；
- sidecar 不改变策略收益、model-paper NAV、选股、操作建议、仓位、v1.1 reminder 或 Ship gate。它只改善比较轨的基准收益口径；
- 真实 provider 获取仍是单独授权的后续执行。raw 只能进入 gitignored 私有目录，tracked 摘要不得包含 secret、request URL、原始价格或原始事件行。本刀的 schema、纯复算器和本地接线测试不代表已经取得真实 ETF 股息数据。

## 12.7 Knife 6：v1.1 仓位归因（诊断扩展）

Knife 6 只解释“为什么和 VTI 的差距会这样”，不重新选股、不重算操作建议、不改 v1 周记录、NAV 或账户。实现入口是 `engine/us_short_market_diagnostic_attribution.py`，输入和输出分别是 `schemas/us_short_market_diagnostic_attribution_input.schema.json` 与 `schemas/us_short_market_diagnostic_attribution_report.schema.json`。

- 输入必须逐周绑定四类来源：v1 的 paper 周收益、Knife5 已确认的 VTI total-return sidecar、决策时点可用的 PIT 3M T-bill 周收益，以及规则隐含的目标股票暴露 `g*`；目标暴露由“已持仓暴露 + 新订单暴露”再经过现金容量、环境仓位上限和 long-only 上限取最小值，不能从实际成交或事后 NAV 倒推；
- 匹配基准为 `g* × VTI total return + (1 − g*) × PIT 3M T-bill return`。每周输出 `raw_excess`、`exposure_effect` 和 `active_system_effect`，其中后者是“策略实际收益 − 匹配基准收益”，因此保留选股、操作建议、仓位、执行限制和成本的综合影响，不冒充单独的选股效果；
- 每周和窗口摘要都必须满足 `raw_excess = exposure_effect + active_system_effect`，允许的浮点残差只作机器精度归零；
- 只要任一周缺少可复现的决策时点、VTI total return、PIT 现金收益或规则目标暴露，整份归因报告为 `unavailable`，相关指标保持 `null`，不补零、不使用固定现金利率、不用未来数据；
- `attribution_epoch` 独立于 v1 的 `diagnostic_epoch`，用于标识归因规则版本。Knife 6 不回填无法按原时点重现的历史归因，也不修改既有 weekly/report schema；当前实现只提供离线契约和纯计算器，真实 model-paper、PIT T-bill 与 ETF 数据仍需各自获得授权后才能形成真实可评估结果；
- 报告必须携带 `requested_exposure` 和四个约束值，由 validator 重新计算 `g* = min(requested, cash_capacity, environment_cap, long_only_cap)` 及 binding constraints；不得把实际成交仓位洗成规则目标仓位；
- input、report 和 builder 全部接受 `as_of_date`，未来 `decision_date` / `valuation_date` / `available_at` 必须 fail-closed；公开入口统一抛 `AttributionError`；
- 输入与报告边界固定为 `diagnostic_only=true`、`comparison_only=true`、`counts_ship_gate=false`、不改变选股/操作建议、不自动调仓、不调用 provider、不写账户。测试入口是 `tests/test_us_short_market_diagnostic_attribution.py`，schema 闭世界检查沿用 `tests/schema/test_us_short_market_diagnostic_26w_schemas.py`。

## 12.8 Knife 7：完成通知门、诊断起点与正式周任务接线

Knife7 是最后一刀，共负责四件事：

1. 增加 `diagnostic_start_receipt` schema 和不可变私有落盘；receipt 只能由未来 Codex 的独立 `设计完成` 通知触发，且必须绑定设计权威摘要、通知摘要、通知时间、首个 canonical decision week 与 `diagnostic_epoch`；
2. lifecycle 没有合格 receipt 时拒绝写第 1 周；不得从 `2026-06-20`、文件日期、部件日期或账户日期推断起点；
3. 启动后按日历周推进；部件或数据缺失周写 `no_count` / `unavailable`，不延后 26 周边界；
4. 正式 weekly task 每周自动读取 lifecycle 的 `v1_1_attribution`：pending 时只提醒；active 时自动调用 Knife6。缺 VTI total return、PIT 现金收益或 `g*` 时产出 `unavailable`，不要求用户手动操作。

Knife7 的启动门已实现（`engine/us_short_market_diagnostic_start_receipt.py` + `runners/us_short_market_diagnostic_weekly.py`）；门建成不等于门打开。本文件写下的仍是冻结设计，不是启动通知：至今没有签发过 receipt，也仍无真实第 1 周、真实 10 万美元 model-paper 账户、真实 ETF sidecar 或 PIT 现金归因结果。上文第 4 条（正式 weekly task 自动读取 `v1_1_attribution`）**已接线**（2026-08-09 复核）：`engine/us_short_market_diagnostic_weekly_task.py` 读 `register["v1_1_attribution"]` 并在 active 时调用刀 6 的 `build_attribution_input` / `build_attribution_report`。接线不等于有结果——缺 VTI total return、PIT 现金收益或 `g*` 时仍产出 `unavailable`。

## 13. Knife 0 验收

刀0完成必须证明：

1. policy preset、weekly record schema、summary schema 均为合法 Draft 7；
2. schema 根对象和嵌套对象均 closed-world；
3. 四个基准、26周、20周阈值和状态词被固定；
4. 10万美元账户启动条件被固定，但刀0未播种账户；
5. 策略 paper_evaluable 与基准 return quality 被分开；
6. 价格收益降级不伪装成 total return；
7. no_count、幂等、未来日期和错误时钟边界进入 schema/测试契约；
8. v1.1 的连续4周自动激活、sticky active、每周提醒和 attribution_epoch 规则被固定；
9. 刀0不联网、不调用 provider、不写 state 运行态、不改变正式选股或操作建议。

## 14. Knife 4 验收

Knife 4 完成必须证明：

1. 第 26 周之前不发布报告，第 26、52、78 周边界可按同一规则生成固定区块；
2. 固定 26 周与 since-inception 两套视图分别通过 schema，四个基准和 ruleset 分段完整；
3. 公开 JSON/Markdown 不包含逐周记录，且不改变诊断边界；
4. 同一窗口重复运行字节级幂等，半成品或冲突内容 fail-closed；
5. 从 Knife 3 私有 lifecycle 读取时只消费已 settled 记录；没有真实私有根时不创建真实输出；
6. 固定 Python 下聚合器、诊断引擎、lifecycle、schema 和文档治理测试通过。

## 15. Knife 5 验收

Knife 5 完成必须证明：

1. 四 ETF sidecar schema 为合法 Draft 7、根与嵌套对象 closed-world，来源 digest 能回溯到 root `source_refs`；
2. 完整 sidecar 周可按同一输入复算 total return，并能升级为 `total_return_evaluable`；
3. sidecar 不完整、日期错配或对账失败时只降级对应 ETF 周，仍保留价格收益和明确原因；
4. sidecar 与本地价格包的窗口、epoch、周号和估值日不一致时 fail-closed；
5. 周记录与 model-paper 私有 store 仍只读，任何 sidecar 输入不触发 provider、账户写入、选股/操作建议或 Ship gate 变化；
6. 固定 Python 下 sidecar schema、纯复算器、本地适配器和 flat overall status 回归测试通过。

## 16. Knife 6 验收

Knife 6 完成必须证明：

1. attribution input/report schema 为合法 Draft 7，根和所有对象均 closed-world，source refs 能逐层回溯；
2. `g*` 由规则目标暴露和现金/环境/long-only 约束计算，不读实际成交、不从事后 NAV 倒推；
3. VTI 只有在 Knife5 `total_return_evaluable` 且 sidecar digest 齐全时进入归因；PIT 3M T-bill 必须同时满足有效期、as-of 和 decision-time 顺序；
4. 每周和窗口摘要都输出 `raw_excess`、`exposure_effect`、`active_system_effect`，并通过恒等式回归；
5. 缺少任一必要输入、发生 look-ahead、历史回填或边界篡改时 fail-closed，报告为 `unavailable` 且不把缺失值写成 0；
6. 刀6不修改 v1 weekly/report schema，不改变选股、操作建议、NAV、账户或 Ship gate；
7. 固定 Python 下 attribution 聚焦测试、旧诊断引擎回归和 schema/doc governance 测试通过。
