# A-short 持仓恒列入 S3a — 系统计算止损/止盈(被动显示) + account_state schema v1.1

**owner**:让系统自动算持仓的**止损 / 止盈**位(用户不再手填),落实桌面 `持仓恒列入.md §14`"系统算决策、用户只填事实"的核心。S3a = **被动**第一刀(算 + 显示,动作恒「持有」);主动动作(减仓 / 止损触发 / 加仓)+ 跨周持久化 ratchet 留 **S3b**。
**状态**:设计稿(2026-06-16,口径已与用户确认);待 `起草` 实现。S1 见 `docs/a_short_holdings_in_m67_design.md`。

## 0. 用户已定口径(2026-06-16 Q&A,不可猜)
- **止损 = 跟踪止损(ratchet)**:`近 N 日最高 − ATR_MULT[regime] × ATR`;随新高上移,无状态(从 price_series 重算)。
- **主动程度 = 被动**:系统算并显示 止损 / 盈一 / 盈二,**动作恒「持有」**;到价由用户盘中手动;**不**自动减仓 / 加仓,**不动**"禁止自动加仓"硬线。

## 1. 背景(为什么)
S1 让持仓恒进 M6.7,但持仓行 `plan=None`、只回显用户手填的 `stop_loss`,而 4.3 转换器**必填** `stop_loss`(用户实跑被卡、被迫手填 53/55)。引擎其实**已有**完整止损/止盈/仓位计算(`exit_and_size`:`stop=支撑−ATR_MULT×ATR`、`t1=压力位或 close+RR_FLOOR×risk`、`t2=max(t1+ATR_MULT×ATR, close+2×risk)`),但**只对新建仓用**;`validate_m67_consistency` 还**强制非建仓行 入/损/盈/股数 全为空**(L690-693)。S3a = 把计算口径**延伸到持仓** + 放开校验 + schema v1.1 让手填 stop 降为**可选参考**。

## 2. 计算规则(精确;复用引擎常量,不另造口径)
新增**纯函数** `holding_levels(inp, ind, regime) -> (plan_dict, None) | (None, reject_reason)`:
- 复用 `ATR_MULT[regime]`(止损/盈二倍数)、`RR_FLOOR[regime]`(盈亏比下限);`atr = ind["atr14"]`、`res = ind["resistance"]`。
- **跟踪止损**:`recent_high = max(price_series 最近 N=20 根已结算 bar 的 high)`(不足 20 根用全部)。`stop = recent_high − ATR_MULT[regime] × atr`。
  - 缺价 / 缺 ATR / atr≤0 / 无 recent_high → `return None, "缺价/ATR/最高价,无法精算跟踪止损"`(退回显示"未算出",**绝不伪造**)。
- **risk = close − stop**:
  - `risk > 0`(现价在止损上方,正常):`t1 = res if (res and res > close) else close + RR_FLOOR[regime]*risk`;`t2 = max(t1 + ATR_MULT[regime]*atr, close + 2.0*risk)`;`basis="trailing"`,`breached=False`。
  - `risk <= 0`(现价 ≤ 跟踪止损,**已破位**):`t1=t2=None`,`basis="trailing"`,`breached=True`(动作仍「持有」,advice 标"现价已跌破系统跟踪止损 X")。
- **不算股数**(已持仓、非新开仓):`shares=None`、`entry=None`。
- **数值取整(回应 Codex Optional)**:用户面持仓价位 `损/盈一/盈二` round 到 **A股主板最小变动价 0.01**(可执行价、对齐 tick;避免 69.412 这种不可下单价);既有建仓 plan 的 3 位小数**不动**(S3a 边界外、避免改既有可执行价语义,可 S4 统一)。返回 `{"entry":None,"stop":…,"t1":…|None,"t2":…|None,"shares":None,"basis":…,"breached":…,"recent_high":…,"atr":…}`。
- **ratchet 边界(S3a 限制,文档明示)**:用"近 20 日高"的**无状态**实现 → 在 20 日 swing 窗内单调不降、随新高上移;**跨 20 日窗后严格"永不下移"需持久化上轮 stop**,留 **S3b**。S3a 不持久化。

## 3. 接入(引擎;既有建仓/观察/否决分支零改)
- `build_m67_report` 的 `has_position` 分支:`action="持有"` 不变,但 `plan, reject = holding_levels(inp, ind, regime)`;成功 → table `损/盈一/盈二` 取系统值(`入/股数=None`),advice 改系统口径;失败/breach → 见 §6。`machine.entry_exit_size_star.plan` 落 holding plan。
- `build_holding_report`(Tier-3):同样调 `holding_levels`(Tier-3 **有** price_series → 可算止损/止盈);EGS/语义"未核查"诚实标注**不变**。
- **`exit_and_size` / `entry_type` / 建仓·观察·否决 分支 / IV 闸门 / Rule12·Rule13 / compute_star 全部零改**。

## 4. account_state schema v1.1(+ 转换器)—— 向后兼容路径(Codex `审查 FAIL` 修订)
- **现状(已核,纠正起草误判)**:schema `schema_version` = `const "1.0.0"`;`validate_account_state`(`a_short_weekly_pipeline.py:62`)单次 `jsonschema.validate(account, schema)`;schema **确实要求** `stop_loss`(`tests/schema/test_a_short_account_state_schema.py::test_position_requires_manual_stop_loss` 删 `stop_loss` → 期望 `ValidationError`)。故起草稿"`const` 升 1.1.0 还兼容旧文件"**自相矛盾**(const 一升,旧 1.0.0 文件即被拒)——本节修订给出确切路径。
- **采用路径 = `enum` + 版本条件校验(单 schema 双版本,draft-07 `if/then`;不引迁移命令/不引第二个 schema)**:
  - `schema_version`:`const "1.0.0"` → **`enum ["1.0.0","1.1.0"]`**(`validate_account_state` 仍单次 `jsonschema.validate`,零调用方改动)。
  - **`if schema_version == "1.0.0" then` positions.items.`required` 含 `stop_loss`**(旧文件**严格不变**、语义保真);`schema_version == "1.1.0"` 时 `stop_loss`/`take_profit_1`/`take_profit_2` **非必填**(语义降手填参考)。draft-07 顶层 `if/then`,`then` 重申 `positions.items.required`。
  - 净效果:**旧 1.0.0(含 stop)仍通过**、**新 1.1.0(空 stop)通过**、**1.0.0 空 stop 仍被拒**(向后兼容与新版放开互不污染)。
- 转换器 `runners/a_short_account_state_from_manual_tables.py`:`ACCOUNT_SCHEMA_VERSION` → `"1.1.0"`;positions `REQUIRED` 集**移除 `stop_loss`**(L70)、改 `_parse_optional_float`(L288);**空白合法、不再 FATAL**(解用户手填摩擦)。lineage 记 `manual_stop_ref`(填了才有,仅审计/参考)。
- 现有 schema 测试:`test_position_requires_manual_stop_loss` **保留**(其 example 是 1.0.0 → 仍 assert stop 必填);双版本新测见 §10 ⑬′。
- **M6.7 report schema 不改**:`损/盈一/盈二` 已 `number|null`;manual_ref 进 advice 文本,不扩 m67 schema。

## 5. `validate_m67_consistency` 放开(按 action 分支)
当前 L690-693:非建仓 → 入/损/盈/股数全 null。改为:
- **建仓**:同现状(plan 必备、四值正、与 plan 一致)。
- **持有**:`入`/`股数` 必 `None`;`损`/`盈一`/`盈二` **可非空** —— 若非空必须与 `machine plan`(holding_levels)一致;`breached` 时 `损` 非空、`盈一/盈二` 可 None;advice **必含**"止损"+"无条件"/"盘中手动"(诚实护栏延用,缺则 raise)。
- **观察 / 否决**:同现状(交易字段全 null)。

## 6. Render(持有行显示系统位;`runners/a_short_m67_render.py`)
- 一览表:持有行 `损/盈一/盈二` 列填系统值(S1 时为空)。
- 逐票卡 advice:`系统跟踪止损 X(无条件、盘中手动执行);止盈 盈一 Y / 盈二 Z;你的手填参考止损 = <manual_ref 或 无>(仅参考)`。
- **breach**:`⚠️ 现价已跌破系统跟踪止损 X —— 触发后由你盘中手动执行`;`损` 仍显示、`盈一/盈二` 显"—"。
- **无法精算**(holding_levels reject:缺价等):显"系统止损未算出(<原因>)",回退手填参考(若有),不伪造。
- Tier-3 持仓:系统位照显(有价就能算)+ **保留** EGS/语义"未核查" caveat(S1 诚实点不动)。

## 7. 边界(S3a 明确不做)
- 不做主动动作(到价减仓 / 止损触发动作 / 移保本 / 加仓)—— 动作**恒「持有」**(S3b)。
- **不动**"禁止自动加仓"硬线、不动 user-stop 的"无条件盘中手动"语义。
- 不改 egs_main / 选股 / EGS 分 / 建仓·观察·否决逻辑 / IV 闸门 / Rule12·Rule13 / 价格门 / 价格钟 / 隐私护栏。
- 跨周严格 ratchet 持久化留 S3b;非生产 / 不接券商 / 不下单 / 主板 only。

## 8. 切片
- **S3a(本设计)**:`holding_levels`(ratchet 止损 + tp)+ 被动显示 + schema v1.1(stop 可选参考)+ converter 不必填 stop + validator 持有放开 + render。
- **S3b**:主动动作(到价减仓 / 止损触发 / 移保本)+ 加仓 + 跨周持久化 ratchet。
- **S4**:no-dangling guard(每个为持仓算出的因子在 M6.7 有落点或标缺失)+ 全测试矩阵。

## 9. owner 文件(S3a)
- `runners/a_short_phase5_engine.py`:新 `holding_levels`;`has_position` 分支 + `build_holding_report` 接入;`validate_m67_consistency` 持有放开。
- `schemas/a_short_account_state.schema.json`:→ 1.1.0(stop 语义降参考、非必填)。
- `schemas/examples/a_short_account_state*.json`(若有 schema_version 断言)+ `a_short_account_state_lineage` example:同步 1.1.0 / manual_stop_ref。
- `runners/a_short_account_state_from_manual_tables.py`:`stop_loss` 移出 REQUIRED、可选;lineage manual_stop_ref。
- `runners/a_short_m67_render.py`:持有行系统位 + advice + breach + 未算出回退。
- `tests/test_a_short_holdings_in_m67.py` / `test_a_short_phase5_engine.py` / `test_a_short_account_state_from_manual_tables.py`:见 §10。
- docs:本文件 + `a_short_holdings_in_m67_design.md §6`(S3 指针)+ `4.3 doc`(stop 可选)+ README 路由行 + CURRENT/SESSION_LOG/register。

## 10. 测试矩阵(对抗式,第一稿全列)
- `holding_levels`:① 正常(risk>0)→ stop=recent_high−ATR×mult、t1/t2 同 exit_and_size 口径、入/股数=None;② **ratchet**:近 20 日内新高 → stop 上移(断言比旧高时高);③ **breach**(现价≤stop)→ breached=True、t1/t2=None、损非空;④ 缺价/ATR → reject、不伪造;⑤ res 缺失 → t1 走 close+RR×risk。
- 引擎接入:⑥ has_position + 可算 → action 持有、table 损/盈一/盈二=系统值、入/股数 null、过 validator;⑦ Tier-3(build_holding_report)持仓带系统位 + 仍标 EGS/语义未核查;⑧ 建仓/观察/否决回归不变。
- validator:⑨ 持有带 损/盈一/盈二 通过;⑩ 持有但 入/股数 非空 → raise;⑪ 持有 损 与 machine plan 不一致 → raise;⑫ 观察/否决仍要求全 null(回归)。
- schema/converter:⑬ positions **空 stop_loss → 转换成功**(不再 FATAL)、manual_stop_ref=None;**⑬′ 双版本校验(向后兼容核心,Codex Required)**:`1.0.0`-含-stop → 通过、`1.0.0`-空-stop → **仍 ValidationError**(旧语义保真,`test_position_requires_manual_stop_loss` 保留)、`1.1.0`-空-stop → 通过、`1.1.0`-含-stop → 通过(降参考);⑭ 填了 stop → manual_stop_ref 落 lineage;⑮ 旧 `1.0.0`(含 stop)account_state 经 `validate_account_state` 仍 load(不报错);⑯ 转换器写 `schema_version=1.1.0`、schema `enum` 接受两版;⑰ 价位取整到 0.01(tick)。
- render:⑰ 持有行显系统止损/止盈;⑱ breach 显警告 + 盈一/盈二="—";⑲ 未算出回退手填参考;⑳ Tier-3 系统位 + 未核查 caveat 并存。
