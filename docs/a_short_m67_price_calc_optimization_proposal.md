# A-short M6.7 价格计算优化提案(entry / stop / take-profit / 现金分配)

**owner**:优化 M6.7 周报输出的各类价格,使其**可执行、数学自洽、组合层不超配**。
**status**:设计已收敛(用户 master + Codex §11 + subagent 审查 + 用户 2026-06-16 directives)。逐 slice 走 `起草→审查→修复→提交`,**尚未实现任何 slice**。
**source / 权威**:用户桌面 master `price calc.md`(含 Codex §11 修正);本 in-repo 文件 = 仓库内**实现依据**,与 master 对齐。关联 `docs/a_short_holdings_s3_system_levels_design.md`(S3a 持仓侧)、引擎 `runners/a_short_phase5_engine.py`。

## 0. 系统级·永久变更声明(用户 2026-06-16)
本提案所有改动落在**引擎 / schema / render 的计算逻辑**,**永久生效、适用于所有未来运行**(任意持仓、任意 topN 候选)。**不是**给当前持仓(601138/603667)或本周 topN 打补丁。每个 slice 都是确定性内核/契约级改动,必有回归测试。

## 0.1 已拍板决定(2026-06-16)
- **D1 = 是**:所有价格取到 **0.01(2 位小数)**,**统一覆盖建仓 + 持仓 plan**(推翻原 S3a §2.22"建仓 plan 不动";已在 S3a 设计同步)。
- **D2 = 是**:入场区间的 **RR 门 + 现金预算一律按区间最不利价 `entry_high`**(非 `entry_ref`)。
- **tick = side-aware**(方向敏感,见 §2),非统一四舍五入。
- **D3 = 是**:本提案 + S3a + 现有引擎按**一条 M6.7 价格 roadmap** 统一排序(见 §10)。

## 1. 背景 + 3 个已验证真问题(对代码逐一核过)
建仓价位由 `exit_and_size` 算(`stop=支撑−ATR_MULT[regime]×atr`、`t1=压力位 或 close+RR_FLOOR×risk`、`t2=max(t1+ATR_MULT×atr, close+2×risk)`、仓位上限)。三个真问题:
1. **不可执行价**:render `_cell`=`str(round(close,3))` → 表里 `69.412` 这类价;A股主板最小变动 0.01,不可下单。
2. **多票超配**:pipeline 每个候选用**同一** `account` dict、各自吃 `available_cash×cap_pct`,**无全局现金预算** → 合计可超配。
3. **突破型 RR 门未区分**:V14.2 §300 规定突破 RR floor 2.0/2.5,引擎 `RR_FLOOR` 是 regime 平值。

## 2. Slice 0(横切)— A股 tick 精度(side-aware,= master §3 + §11.1)【最先】
- 不用 `round(x+1e-9, 2)`(银行家舍入 + 浮点偏置不稳)。用 **`Decimal` + 方向敏感** tick helpers,统一到 **0.01**;入口 `if x is None or not math.isfinite(x): return None`(守"绝不伪造价"):
  - `price_ref`:Decimal half-up(展示参考价)。
  - `stop_trigger`:**向上**取 tick(实际止损不低于系统风险线)。
  - `take_profit`:**向下**取 tick(不高估可实现止盈)。
  - `buy_limit_high`(entry_high):**向下**取 tick(系统建议价不超计算上沿)。
  - `buy_limit_low`(entry_low):向上/half-up,但须保证区间仍合法(`low<=high`)。
- **覆盖建仓 plan(`exit_and_size`)+ 持仓 plan(S3a `holding_levels`)**;**machine plan 与 table 存同一组 tick 后值**(防 `validate_m67_consistency` 的 `1e-9` 比对写盘前 `ValueError` 炸整轮);raw 计算值如保留只作 debug、非用户执行价。
- 操作建议须写"价格已按 A 股 0.01 tick 规整"。
- **§2.1 post-tick 不变式(Codex Required,关键)**:tick 是**最终执行价**——所有建仓决策 / RR 校验 / 持仓位用**取整后**价,不用 raw。side-aware 取整可能收窄风险结构,故取整后**必须重校验**,任一破即转观察 / 走 breached:`risk = entry_for_risk − stop` 有限且 > 0;`stop < entry_for_risk`;`t1 > entry_for_risk`;`t2 >= t1`;`rr_at_entry_high = (t1 − entry_high)/(entry_high − stop) >= rr_floor`(**用取整后价复算**)。建仓任一不满足 → 转「观察」(reject 写"取整后 RR/结构失效")。**S3a 持仓**:取整后 `stop >= close`(跟踪止损越过现价)→ 走 §7 / S3a 的 **breached** 路径(t1/t2=None、标已破位),不当正常止盈。对抗测试:raw 合格、仅取整后失效 → 正确转观察 / breached。

## 3. Slice — 入场区间 + 最不利价 RR 门(= master §4 + §11.2)
- `entry_low` / `entry_high` / `entry_type`(低吸·突破)/ `entry_invalid_reason`;区间无效(`low>high`)退回单点不伪造。**唯一可执行决策价=`entry=entry_high`**；`tick(close)` 只保留为原始参考上下文，不得成为 table/plan/advice/RR 的操作价。
- **低吸(精确公式,Codex Required)**:`entry_ref=close`;`entry_low=max(support, close−0.5×ATR)`(floor:不追到支撑下方);**`entry_high=close`**(cap:低吸不追到现价上方,等回落到 `entry_low–close` 区间吸)→ 区间 `[entry_low, close]` 非退化(只要 `support<=close` 即低吸正常触发态)。**raw 兜底**:`entry_low>entry_high`(即 `support>close`,现价已破支撑)→ 退单点 `entry_ref` + `entry_invalid_reason`。**post-tick 兜底**:取整后(entry_low 向上取、entry_high 向下取)若 `entry_low>entry_high` → 同退单点。突破:`entry_high=close+0.3×ATR`、`chase_invalid_above=close+0.5×ATR`。
- **RR 用 entry_high 重算**:`risk_at_entry_high=entry_high−stop`、`rr_at_entry_high=(t1−entry_high)/risk_at_entry_high`;**`rr_at_entry_high>=rr_floor` 才输出建仓**,否则收窄区间或转观察(master §11.2)。machine plan 存 `entry_for_risk/risk_at_entry_high/rr_at_entry_high`。
- 落点:`table.入=plan.entry=entry_high`;操作建议写 `entry_low–entry_high`+同一 `rr`/`rr_at_entry_high`+突破"超过 chase_invalid_above 不追"+区间失效条件;第一版不扩 schema(render 测试强制文案含 entry_low/high/chase),或可选 `m67.execution_guidance.entry_range`。

## 4. Slice — 组合级现金分配(修真·超配 bug,= master §5 + §11.3/11.4)
- 出全部 action 后、只对 `建仓` 票:逐票出 raw plan → 排序 → 逐票消耗 `remaining_cash`(初值 `available_cash`)。
- **按 entry_high(最不利价)计提现金**:`cash_required=allocated_shares×entry_high`(无区间则 `=entry_ref`)。
- 排序键(确定性):`action_buildable↓ > star↓ > egs_score↓ > rr_at_entry_high↓ > avg_amount_5d↓ > original_topN_rank↑ > ts_code↑`。**只 re-rank 建仓票,不 rescue hard veto、不把观察/否决变建仓、不碰 Rule12/13/L2 暴露**(审查 F7)。
- 字段:`raw_shares/allocated_shares/cash_budget_used/cash_allocation_rank`(+ weekly `available_cash_start/allocated_cash_total/remaining_cash`)。**`allocated_shares==0`(分配后不足一手/最小金额)→ 完整状态转换(Codex Required,防 validator 崩)**:**同时**置 `machine.entry_exit_size_star.action="观察"` 与 `m67.table.操作="观察"`;按 validator 观察规则**清空 `入/损/盈一/盈二/股数`=null**;raw plan(entry/stop/t1/t2/raw_shares)仅留 `machine` 诊断字段(如 `plan.diagnostic_raw`)、**不**作用户执行价;advice 写"组合现金分配后不足一手→转观察(原拟建仓价位见诊断)"。**绝不**出现 `建仓` 行 股数 null/0。测试:归零后 `validate_m67_consistency` 通过、无 `建仓` 行 股数 null/0、action↔table 一致。`allocated<raw`(非 0)时操作建议写明降档原因(审查 F6,no-dangling)。

## 5. Slice — 有效支撑/压力(策略口径,单独切片单独审查,后置)
`min/max(20日)` → 抗单日极值结构位 + 质量标记(strong/weak/fallback_extreme)。
- **#5 support(已做):** `effective_support` 改建仓 stop / RR 门**分母**(risk)/ 谁能建仓,**只动建仓侧**(S3a 持仓止损当时用 raw `recent_high` 不是 support)。
- **#6 resistance/压力 有效化(已做 2026-06-17):** `effective_resistance` 同样去插针(最高 high 比次高 high 高 >1×ATR 判插针取次高),改建仓 `t1`/RR 门**分子**(补全 #5 只护分母的抗插针对称——上插针顶高会让 RR 虚高、marginal 建仓假性过门)**且改持仓跟踪止损口径**(`recent_high` 现为去插针的有效压力,**区别于 #5**;用户已确认接受该持仓行为变更)。交叉引用审查 F8 / C2。

## 6. Slice — V14.2 可结构化细节迁移
突破型更高 RR floor、除权提示、IV/HV 标签、更细结构止损。逐项带"输入字段 + deterministic 函数 + M6.7 落点 + validator + 回归测试",不做一次性大包。
**状态(2026-06-17):** 突破型 RR floor(#6-i `98e6351`)、除权提示(#1 `d60bf07d`)、IV/HV 标签(`39c53e00`)均已完成;**更细结构止损 = 放弃**(用户定:周频 + 手动执行下精度微调 ROI 不足,**不做**)。**§6 收尾**;resistance/压力 有效化(`d22b3e6e`)见 §5。价格层后续若再有结构性需求另开设计,不在 §6 残留待办。

## 7. 与 S3a 的衔接(审查 C1-C4)
- **C1 已解决**:D1 拍板"建仓也取整" → 推翻 S3a §2.22(已同步改 S3a 设计);Slice 0 同时覆盖建仓 + 持仓。
- **S3a 持仓 stop/tp 也用 side-aware tick**:持仓止损 `stop_trigger` 向上取、止盈向下取(与建仓共用 round + 落点规则)。
- C2:止损基准两条线不同且都已确认(建仓=支撑−ATR;持仓=近20日高−ATR ratchet),非冲突;#5 改 support 只影响建仓侧,#6 改 resistance(有效压力)同时影响建仓 `t1`/RR 与**持仓跟踪止损**(两条线都用去插针后的结构位)。
- C3:止盈基准一致(同源 `exit_and_size` 口径)。
- C4:Slice 0 与 S3a 都改 `validate_m67_consistency`——S3a 改"持有"分支放开 损/盈一/盈二、Slice 0 不改逻辑只要求 round 后两边同值;同 PR 视角审、排顺序避免 clobber。

## 8. No-Dangling 规则(= master §8)
任何新价格字段必须**同时**有 machine 落点 + table/文案落点 + validator 检查,否则不许新增。`gap_invalid_below/above` 桌面草案无落点 → **删除**待真有落点再议(审查 F9)。

## 9. 边界
非生产 / A股主板 only / 不接券商 / 不自动下单 / 不自动加仓/减仓(措辞也不得出现)/ 止损=盘中手动。不动 egs_main / 选股 / EGS 分 / IV 闸门 / Rule12·Rule13 / 隐私护栏。Slice 0/现金分配 = 确定性内核 → 必有回归;支撑升级/V14.2 = 策略口径 → 各自单独审查。

## 10. 实施序(合并 roadmap,= master §11.8 + S3a)
1. **Slice 0 — tick + side-aware rounding**(覆盖建仓 + 持仓,同时给两侧解锁,最先)。
2. **S3a — 持仓系统止损/止盈实现**(被动显示;复用 Slice 0 的 round + 落点;= 用户 §14 主诉求)。
3. **入场区间 + 最不利价 RR 门**(建仓侧;cash 依赖它的 entry_high)。
4. **全局现金分配**(按 entry_high 消耗、确定性排序)。
5. **No-dangling guard**(全价格字段落点 + 测试抓漏)。
6. **有效支撑/压力**(单独策略切片)。
7. **V14.2 可结构化迁移**(逐项)。
每 slice 独立 `起草→审查→修复→提交`,不一次性大改。
