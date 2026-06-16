# A-short M6.7 价格计算优化提案(entry / stop / take-profit / 现金分配)

**owner**:优化 M6.7 周报输出的各类价格,使其**可执行、数学自洽、组合层不超配**。本文件是 in-repo **权威提案**(已过对抗式审查),源自用户桌面草案 `未price calc.md` + subagent 审查(2026-06-16,verdict = adopt-with-changes)。
**状态**:提案 / 待用户拍 §8 的 D1-D3,然后逐 slice 走 `起草→审查→修复→提交`。**本文件只是设计,未实现任何 slice。** 关联:`docs/a_short_holdings_s3_system_levels_design.md`(S3a 持仓侧)、`docs/a_short_holdings_in_m67_design.md`(S1)、引擎 `runners/a_short_phase5_engine.py`。

## 1. 背景 + 3 个已验证的真问题(对代码逐一核过)
M6.7 的建仓价位(`入/损/盈一/盈二`)由 `a_short_phase5_engine.py::exit_and_size` 算(`stop=支撑−ATR_MULT[regime]×atr`、`t1=压力位 或 close+RR_FLOOR×risk`、`t2=max(t1+ATR_MULT×atr, close+2×risk)`、仓位上限)。审查确认 3 个真问题:
1. **不可执行价**:render `_cell` 直接 `str(round(close,3))` → 表里出现 `69.412` 这类价;A股主板最小变动 = **0.01**,这种价不可下单。
2. **多票超配**:`a_short_weekly_pipeline.py`(约 L741-747)每个候选用**同一** `account` dict,`exit_and_size`(L312-314)各自吃 `available_cash × cap_pct`,**无全局现金预算** → 多只"建仓"合计可超过可用现金。
3. **突破型 RR 门未区分**:V14.2 §300 规定突破型更高 RR floor(2.0/2.5),但引擎 `RR_FLOOR` 是按 regime 平值、未区分突破/低吸。

## 2. 横切 Slice 0 — tick 取整(可执行价)【最高优先,先做】
- 新增纯函数 `round_a_share_price(x)`:**`Decimal(str(x)).quantize(Decimal("0.01"), ROUND_HALF_UP)`**;入口 `if x is None or not math.isfinite(x): return None`(守住引擎"绝不伪造价"护栏)。**不用** `round(x+1e-9, 2)`(banker's rounding + 浮点偏置不稳,见审查 F2)。
- **同时覆盖建仓 plan(`exit_and_size`)与持仓 plan(S3a `holding_levels`)**:`entry/stop/t1/t2` 落 plan 前统一过 `round_a_share_price`;**machine plan 与 table 存同一组 tick 后值**。
- **必须连 machine plan 一起取整**(审查 F1):`validate_m67_consistency` 用 `abs(table − plan) > 1e-9` 校验一致;若只 round table、plan 留 3 位 → 差 0.002 ≫ 1e-9 → 写盘前 `ValueError` **炸整轮**。两边同源 round 后差为 0,1e-9 容差保留。
- **与 S3a 的冲突 C1**:S3a §2.22 写了"建仓 plan 3 位小数不动";本 slice **推翻它**(tick 统一覆盖建仓+持仓)。采纳前需 D1 拍板(§8)。
- 测试:建仓/持仓 plan 均 tick 后 == table、过 1e-9;`None/NaN/Inf → None`;tie(x.xx5)向上;既有建仓回归。

## 3. Slice A — 组合级现金分配(修真·超配 bug)【高优先,Slice 0 后】
- 在 `build_weekly_report` 出全部 action 后、**只对 `action=="建仓"` 的票**按优先级排序,统一消耗 `remaining_cash`(初值=`available_cash`);单票 sizing 后扣减预算,不足整手 → 置 0 转「观察」(不做半吊子降档,避免改已 gate 过的 RR/仓位语义)。
- 优先级键:`硬条件通过 > 星级 > EGS分 > RR > 流动性`,**末位 tie-breaker = `ts_code` 升序**(审查 F5:否则并列时分配非确定性,破坏确定性决策核)。
- **现金预算 + cap 按区间最不利价保守计提**(审查 F6;若 Slice B 上线用 `entry_high`,否则用 `entry`)。
- 新字段:`raw_shares / allocated_shares / cash_budget_used / cash_allocation_rank`(每个都要 machine + table/文案落点 + validator,见 §9 No-Dangling)。
- **不碰** Rule12/Rule13/同 L2 暴露等既有组合风控(审查 F7):分配只在所有单票硬/降处理之后、只 re-rank 建仓票,不改任何 veto/downgrade/star。

## 4. Slice B — 入场区间(`入` 单点 → 区间)【推迟:先修 3 个公式缺陷】
方向(`entry_ref/entry_low/entry_high/entry_type/entry_invalid_reason`)可取,但**起草前必须先定死**:
- **F3(P1)RR 自洽**:突破型挂单价抬到 `close+0.3ATR`,但 RR 门用 `close` → 真实成交价更高、真实 RR 更低、可能跌破已通过的 rr_floor("系统说能建、按上沿成交其实不够 RR")。**定:建仓 RR 门用区间最不利价重算**(突破型用 `entry_high`),或明确 `entry_ref=close` 仅作决策锚且文案标"按上沿 RR 降至 X"。见 D2(§8)。
- **F4(P2)低吸区间退化**:`entry_high=min(close, support*(1+band))` 在贴支撑常态下塌成单点甚至 `low>high`(已有兜底不崩,但功能形同虚设)。**定:低吸上沿取 `max` 或独立定义**,并核 band 与 0.5ATR 量纲。
- **F6(P2)预算偏差**:现金预算/ cap 用区间上沿(最不利价)计提,不用 `entry_ref`。
- 第一版不扩 m67 schema(区间进 `操作建议` 文案 + machine plan)。

## 5. Slice C — 有效支撑/压力(策略口径变化,单独切片单独审查)
`min/max(20日)` → 抗单日极值的结构位 + 质量标记。**注意**:改 `support` → 直接改建仓 `stop=support−ATR×atr` 与 RR 门 → 改谁能建仓(审查 F8)。**只影响建仓侧**;S3a 持仓止损用 `recent_high` 不是 support,故 Slice C **不改善持仓止损**(C2,需在 Slice C 设计里显式标影响面)。

## 6. Slice D — V14.2 细节迁移
突破型更高 RR floor(2.0/2.5)、除权提示、IV/HV 标签、更细结构止损 —— 逐项带"输入字段 + deterministic 函数 + M6.7 落点 + validator + 回归测试"。

## 7. 与 S3a 的衔接(审查 C1-C4)
- **C1【D1 待拍】**:tick 取整对建仓 plan 的处理与 S3a §2.22 相反 → 见 §2 + §8 D1。
- **C2**:止损基准两条线本就不同且都已确认(建仓=支撑−ATR;持仓=近20日高−ATR ratchet),非冲突;Slice C 改 support 只影响建仓侧 → 文档互相交叉引用。
- **C3**:止盈基准一致(压力位 / `close+RR×risk` / `t1+ATR`),同源 `exit_and_size` 口径。
- **C4【流程】**:Slice 0 与 S3a 都改 `validate_m67_consistency`——S3a 改"持有"分支、Slice 0 不改逻辑只要求 round 后两边同值;同一 PR 视角审、排顺序避免 clobber。

## 8. 待用户决定(D1-D3)
- **D1(C1,直接改 S3a §2.22)**:tick 取整是否**现在就统一覆盖建仓 plan**?(提案 + 审查均建议:是)
- **D2(F3)**:入场区间上线后,建仓 RR 门用 `close` 还是区间**最不利价**重算?(建议:最不利价)
- **D3(流程)**:是否把本提案 + S3a + 现有引擎当**一条 M6.7 价格体系 roadmap** 统一排序,避免同一函数两份相反指令?(建议:是)

## 9. No-Dangling 规则 + 边界
- **No-Dangling**(沿用桌面草案 §8):任何新价格字段必须**同时**有 machine 落点 + table/文案落点 + validator 检查,否则不许新增。桌面草案里 `gap_invalid_below/above` 全篇无定义(审查 F9)→ 本提案**删除**该字段,待真有落点再议。
- **边界**:非生产 / A股主板 only / 不接券商 / 不自动下单 / 止损=盘中手动;不动 egs_main / 选股 / EGS 分 / IV 闸门 / Rule12·Rule13 / 隐私护栏。Slice 0/A 是确定性内核改动 → 必有回归;Slice C/D 是策略口径 → 各自单独审查。

## 10. 实施序(建议)
**Slice 0(tick)→ Slice A(现金分配)→ Slice D(V14.2,可并)→ Slice B(入场区间,待 F3/F4/F6 定死)→ Slice C(支撑升级)。** Slice 0 同时给 S3a 与建仓侧解锁,应最先;Slice A 修的是已验证真 bug,优先于 B。每 slice 独立 `起草→审查→修复→提交`,不一次性大改。
