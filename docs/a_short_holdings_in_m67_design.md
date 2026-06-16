# A-short 持仓恒列入 M6.7 — in-repo 设计 + 切片

**owner**：让账户持仓无论是否进本周 EGS top-N，都恒出现在周报 M6.7 并诚实标明覆盖度。完整设计推演见用户桌面 `持仓恒列入.md`(§1–§19);本文件是 in-repo 权威摘要 + 切片边界,供 Codex `审查` 仓库改动。
**状态**：S1 drafted。S2/S3/S4 后续。

## 1. 背景与目的

4.3(手工持仓 CSV → `account_state.json` → 周报 M6.7 `--account`)已上线,但 M6.7 是**候选股为中心**(`a_short_weekly_pipeline.py::main` 只遍历 `analysis_input.candidates` = EGS top-N)。持仓只在"恰好进 top-N"时才显示。实测用户真实持仓 `601138.SH`/`603667.SH` 都不在本周 top15 → M6.7 完全看不到它们。

**目的**:账户每只持仓都恒进 M6.7,诚实标明 EGS 覆盖度;最终(S3)由系统算止盈/止损/加仓/动作,用户只填事实。**EGS top-N admission 完全不变**(持仓是额外行,不进选股、不占名额)。

## 2. 三档 Tier 路由（已核产物决定）

EGS 实跑只落盘 top-N 到 `analysis_input.candidates`(15),但 **`A-EGS/Result/egs_full_YYYYMMDD.csv` 落盘本轮全量评分**(粗筛后 ~859 行,扁平 CSV,含 `final_score/esp_score/l4_score/is_lock/has_crash_veto/overheat_flag/...`)。真实持仓常**连 egs_full 都不在**(粗筛阶段就排除)。故分三档:

- **Tier 1 — 持仓在 top-N**:复用 `analysis_input.candidates` 完整数据 + 持仓状态。`row_source=egs_candidate_with_position`,`coverage_status=full`。
- **Tier 2 — 不在 top-N、在 egs_full**:读 `egs_full`(**不改 egs_main**),adapter 把扁平 CSV 行映射成 engine 输入(**只映射真实存在列,缺列标 unknown,绝不 default-False 伪造安全**)。`row_source=account_position_egs_full`,**`coverage_status=partial`**(S1 注入持仓语义/新闻层未跑→不标 full)。**现价取本次 price provider 最新已结算 bar(价格钟),egs_full 仅作 EGS 分/风险 lineage、不作现价权威**(否则与 `price_data_through` 漂移,见 `R-...-CLOSE-PRICE-CLOCK-DRIFT`)。
- **Tier 3 — 不在 top-N、也不在 egs_full(真实持仓常态)**:本周 EGS 粗筛未覆盖。**不伪造、不补算 EGS 分**。价格/技术/账户状态仍分析;EGS/语义标"未覆盖"。`row_source=account_position_only`,`coverage_status=partial`。
- **S1 覆盖诚实(关键)**:**所有注入持仓(Tier-2 + Tier-3)`coverage_status` 一律 partial**——S1 不对持仓跑语义/新闻层,故没有"full 已核查"的注入持仓。Tier-2 vs Tier-3 的区别只在 `row_source`(EGS 复用 vs 粗筛未覆盖)。render:**对每只持仓都显式标「语义/新闻未核查(S1)」**(Tier-2 也标——它 EGS 复用了但语义没跑);EGS 派生字段的「未核查」覆盖**只对 Tier-3(`row_source=account_position_only`)**生效(Tier-2 的 EGS 字段是真实评分、原样显示)。Tier-1(top-N 候选)走候选全链(含语义)→ `coverage_status=full`,不受此限。

## 3. S1 架构（引擎不动；coverage 在 pipeline 标、"未核查" 在 render 诚实展示）

**关键实现决策**:S1 **不改 `a_short_phase5_engine.py` 内核**(它是共享/敏感引擎),改动集中在 pipeline 组装 + render:

- **注入(pipeline)**:`main()` 在 top-N `cands` 之外,把"持仓∖候选"按 Tier 造合成候选,抓价,**现价一律取 price provider 最新 bar**(非 egs_full 快照,见价格钟修正)。**Tier-2** 经 `normalize_candidate` + `build_m67_report`(复用 egs_full 的真实 EGS 分/风险;action 走 `has_position`→`持有`);**Tier-3** 经 `build_holding_report`(**不跑 `classify_risk_families`**,避免在缺失数据上伪造 veto/clean;经 `build_weekly_report` 按 `n["egs_coverage"]=="uncovered"` 路由)。pipeline 给每个 report 打 `row_source` + `coverage_status`(**注入持仓一律 partial**:S1 不跑持仓语义/新闻)。
- **"未核查" 在 render(诚实)**:① EGS 派生字段(否决审查触发/板块资金事件)的"未核查"覆盖**只对 Tier-3(`row_source=account_position_only`)**生效——Tier-2 的真实 egs_full EGS 字段原样显示;② **对每只注入持仓(Tier-2 + Tier-3)都显式加「语义/新闻未核查(S1)」行**——S1 没对持仓跑语义,绝不让缺失语义被读成"无/已核查";③ Tier-3 另加"EGS 未覆盖"行。绝不让缺失数据被误读成安全。
- **不得悬挂(S1 范围)**:`coverage_status`/`row_source` 是表内可见字段;Tier-3 的"EGS 未覆盖"+ 所有持仓的"语义/新闻未核查"在表与卡片都显式;4.3-D `consistency_warnings` 渲染到对应持仓行。

## 4. S1 边界（明确不做）

- 不改 `egs_main` / EGS top-N 选股 / `analysis_input.candidates` 契约(Tier-2 只**读** egs_full)。
- 不扩语义/DeepSeek 到持仓(注入的持仓**显式排除**出语义层;持仓语义标 unknown)——是 S2。
- 不实现系统主动止盈/止损/加仓价/主动卖出动作——是 S3。
- 不改 user `stop_loss` 的过渡期决策含义、不改 account_state schema(v1.0 持仓 `stop_loss` 必填保留作过渡期安全字段)——S3 同刀做 v1.1。
- 非生产、不接券商、手动下单、主板 only。

## 5. 价格门(沿用 §11.3 旁路,务必)

现有两道**对全候选硬中止**的价格门(`MIN_PRICE_OBS` 不足 abort、候选间最新 bar 不一致 abort)是 **candidate 门**。持仓**单独判价**:价格不足/停牌/无价的持仓 → 产「停牌/无价,人工管理」行并**旁路这两道 abort 门**(绝不让一只问题持仓中止整轮、绝不参与候选一致性判定、绝不静默当"持有")。有正常价的持仓才并入价格时钟(最新 bar 须 == `price_data_through`)。

## 6. 切片

- **S1(本切片)**:持仓可见 + Tier 路由 + egs_full adapter + coverage/row_source(加性 schema)+ render 分区 + 价格门旁路 + 4.3-D warning 渲染。引擎/选股/语义/user-stop 不动。
- **S2**:语义/新闻扩到持仓(持仓 symbol 入语义 watch 池;独立联网/DeepSeek 成本)。
- **S3**(设计稿见 `docs/a_short_holdings_s3_system_levels_design.md`,口径已与用户确认 2026-06-16):系统阈值 + ratchet 止损 + schema/converter v1.1(user stop/tp 降为 `manual_*_ref`)+ 放开 `validate_m67_consistency`(现要求非建仓行 `入/损/盈一/盈二` 为空,持仓显示系统位时放开)。**拆 S3a/S3b**:**S3a**=跟踪止损(ratchet)+ 止盈**被动显示**(动作恒「持有」、不动"禁止加仓")+ schema v1.1 + validator 持有放开 + render;**S3b**=主动动作(到价减仓/止损触发/移保本)+ 加仓 + 跨周持久化 ratchet。
- **S4**:不得悬挂 guard(每个为持仓算出的因子在 M6.7 有落点或标缺失)+ 全测试矩阵。

## 7. owner 文件(S1)

- `runners/a_short_weekly_pipeline.py`(注入 + Tier 路由 + 价格门旁路 + 语义排除 + 打 row_source/coverage)。
- `engine/a_short_egs_full_adapter.py`(新;读 egs_full + Tier-2 列映射 adapter + 表头校验 + 不 default-False)。
- `runners/a_short_m67_render.py`(分区 + coverage-aware "未核查" 展示 + row_source/coverage 列 + 持仓行 4.3-D warning)。
- `schemas/a_short_m67_report.schema.json`(加性 optional `row_source`/`coverage_status`)。
- `tests/test_a_short_holdings_in_m67.py`(矩阵:无 account 不变 / 持仓不在 top-N 也进 / Tier1/2/3 / 去重 / 无价停牌→人工管理不炸轮 / Tier-3 不伪造 EGS 分(render 显未核查)/ 语义未扩 / 4.3-D warning 渲染 / **隐私护栏**见 §8)。

## 8. 账户周报隐私输出路由(固化,2026-06-16)

带 `--account` 的周报含**真实持仓**(代码/成本/止损)。本节起因:S1 验证跑时手动把 `--out` 落到非标准目录,暴露出"带账户的周报输出可能进 **git 追踪** 的 research lane → 一次 `git add` 就泄漏持仓"的面。固化方案:

- **路由**:带 `--account` → 输出落 gitignored `state/<系统类型>/weekly_private/<as_of>/`(scheme 覆盖 a_short / a_long / us_short / us_long);observation-only(无 `--account`、无持仓)→ 仍落标准 `research/results/a_short/<as_of>/`(可留作证据)。`weekly_screening.ps1` 按 `-Account` 选目录。
- **gitignore**:`state/*/weekly_private/`(所有系统类型的私密周报目录全部不入库)。
- **pipeline 硬护栏**:`_reject_nonprivate_account_output_path(out, has_account, allow_override)` —— 带 `--account` 且 `--out` 落**仓库内、且 git 未忽略它** → fail-fast `SystemExit`(早于任何取数/落盘)。**直接调用 pipeline 绕过 ps1 也拦得住**。
- **判据 = `git check-ignore` 真值,不是路径名启发式**(Codex 审查 FAIL 的根治):护栏问 `git check-ignore -q -- <out>`——git 确实忽略 → 放行,git 不忽略 → 拒。故仓库内**假** `weekly_private`(如 `research/.../weekly_private/`,只有 `state/*/weekly_private/` 被忽略)、未被单层 `state/*/weekly_private/` 覆盖的**嵌套**层级、**大小写变体**都按 git 实际行为正确处理(早期"路径含 weekly_private 即放行"的子串启发式会被这三类绕过)。仓库外路径(临时目录/外部盘)git 提交不到 → 放行(故单测 `TemporaryDirectory` 不受影响);git 不可用/出错 → 当未忽略(fail-closed,宁拒勿漏);`--allow-nonprivate-account-out` 显式放行(慎用)。
- **不动**:observation-only 路径与既有 production-root 护栏(`_reject_production_output_path`)不变。
