# A-short M6.7 字段/规则联动契约

`schemas/a_short_m67_effect_contract.json` 是 A-short 正式周报的防漏接清单。它不调用外部数据，也不自己做交易判断；它只负责让“新增或改动的字段/规则没有被登记、没有最终落点”变成测试失败，而不是悄悄留在代码里。

## 当前覆盖

- `analysis_input.schema.json` 的全部 371 个叶子字段，按业务组逐一覆盖且不允许重叠；新增字段、删除字段或移动字段都会使组指纹不匹配。
- A-short 实际决策文件（EGS、Phase 5、weekly pipeline、M6.7 renderer、组合风险模块和本契约模块）的判断分支；新增或改变判断条件必须更新契约并说明落点。
- 两份运行时 JSON policy 的全部字段：screening 的 13 项，以及 M6.7 的 Phase 5、组合风险、weekly 时间窗；`operation_impact.source_field`、LLM 六类任务枚举、组合因子枚举，以及 weekly/M6.7 输出 schema。
- `candidate_derived_flags.m4_review_required` 的生产者绑定当前明确为 `A-EGS/egs_main.py::m4_review_required` 恒发 `None`；因此真实周报的该组 ledger 状态是 `not_triggered`，只有未来经独立审查的 M4 生产者或测试夹具提供 `true` 才会记 `applied`。

12B technical/volatility 批次的 39+3 叶已按实际性质改判为 `duplicate_source` / `intentionally_independent`；`machine.technical_volatility_comparison` 只保留 source snapshot digest / observed outcome 的 display audit，不声称正式 comparison，也不改变 Phase5 主决策。Phase5 权威值来自 PIT-bounded `price_series` 与 IV feed；volatility 当前生产端 `A-EGS/egs_main.py::_candidate_from_row.volatility` 恒为 `None`，契约仍保留 `producer_binding` 和 AST 前提守卫，且本批次不创建生产者、不重封冻结包。

每一组都必须声明：输入来源、`must_affect_result` 或 `intentionally_independent`、最终结果表面和运行时处理器。刻意独立项必须带原因、owner、review_ref；不能用“默认独立”或空理由躲过检查。

运行时政策不是镜像：`engine/a_short_runtime_config.py` 只接受 `presets/a_short.yaml` 所路由的两份 JSON，并在 EGS、Phase 5 和 weekly 导入时严格校验。effect contract 对每个政策叶字段同时核验“loader 的精确读取点 + 结果模块的精确读取点 + 派生值进入非模块函数结果计算”，并把整张逐字段读取图做指纹；大类的笼统说明或“只赋给未使用常量”都不能代替实际 reader。政策新增字段、删除登记、或把数值重新写回 Python 都会让测试失败。正式 `analysis_input`、`weekly_m67.json` 和 Markdown 均携带同一个配置 fingerprint，因此候选筛选与周报不能混用不同政策版本。

**禁止用“本周有候选”或“写了部分 lineage”当作字段已接通的证据。** 一组字段只要还没有逐叶证明 consumer，就必须使用 `unresolved_input_group`，在周报中显示 `unavailable_manual_review` 和具体原因；不能显示 `applied`。当前批次身份、技术面、催化剂、波动率、分析师、数据质量等整组，以及市场、账户、报价、行业、分数、事件、流动性、组合事实、derived flags 中已接/未接混合的组，都按此规则诚实提示。后续接线时必须先拆成已证明消费者和仍未接通两组，再允许前者显示已联动；直接挂 lineage/Phase5/组合处理器时，契约还要求逐叶 `proven_consumer_paths` 和代码审查依据，防止重新把大组误报为已联动。

## 周报里的提示

每次正式 `weekly_m67.json` 都有 `effect_contract_ledger`，Markdown 有“字段/规则联动台账”。状态只有四种：

- `applied`：本周已经实际影响了周报结果。
- `not_triggered`：这条规则已接通，但本周条件没有触发。
- `unavailable_manual_review`：数据缺失、结果无效或生产者到消费者尚未闭合；必须显式人工复核，绝不能当作无影响。
- `intentionally_independent`：只作审计/血缘留痕，已书面说明为何不参与交易结果。

Master 的确定性行业趋势 `industry_trend` 已正式接入：它只消费 master 的 `engine/a_short_industry_theme.py::classify_industry_trend` 与 `presets/egs_industry_heat_governance_20260611.json`，对日期/股票/分数不一致 fail-closed 为 `unknown`。本周 neutral 会显示 `not_triggered`；只有合格 `headwind` 才使 M6.7 展示星级 -1。它不改变 EGS 排名、现金分配、股数、操作或硬否决。不要把旧 d15e 的 runtime-config 行业趋势实现重新搬回。

旧 Phase 3/4 的 `llm_tasks` 六类任务枚举已被契约登记，因此新增或修改任务类型会被测试拦住；但本次 master 对账没有声称平行的 `run_analysis_report.py` 报告链已桥接到正式周报。该组会诚实显示 `unavailable_manual_review`，直至单独的 LLM bridge 切片落地。

## 以后改字段/规则时

1. 先在 effect contract 增加或更新对应组：来源、政策、最终表面、运行时处理器；若刻意独立，补齐三项例外说明。新增 JSON 字段时，还必须登记 runtime policy binding。
2. 同步更新契约指纹，并新增一个能改变最终结果或明确进入人工复核的行为测试；不得只改 Python 常量或只改 JSON 而不验证实际结果。
3. 运行 `tests/test_a_short_effect_contract.py` 和相关 weekly/M6.7 测试。任何一项未登记或不一致都会失败。

组合集中度/因子共振的唯一正式权威为 `engine/a_short_portfolio_risk.py`：它在现金分配后的真实试算中决定替换、观察、禁止加仓或人工复核。Phase 5 旧的 `portfolio.same_l2_exposure_over_cap` / `factor_resonance` 降星分支已退役，不得恢复。
