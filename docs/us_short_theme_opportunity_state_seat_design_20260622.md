# US-short `theme_opportunity_state` 词表 + 席位矩阵 + `theme_probe` 设计提案 (2026-06-22)

**状态**: DESIGN SOURCE — **已批准(用户 2026-06-22)**。其 const-pin **已落地**为 `schemas/us_short_theme_probe_governance.schema.json` + `presets/us_short_theme_probe_governance_20260622.json` + 对应 schema-test(本 governance 即该 const-pin 的落地面)。`engine/us_short_theme_probe.py`(theme_probe 引擎)+ `engine/us_short_theme_opportunity.py`(`theme_opportunity_state` determination)亦**已落地**。**§4.5 席位拆分应用亦已落地**(`engine/us_short_dynamic_seats.py`:state→12+3/10+5/8+7 拆分 + 强赛道周 Top6-15 龙头升级)—— 批2 纯决策引擎全部收口。折进冻结主设计 `docs/us_short_system_design.md` 为**可选的后续 design-doc cleanup**(非引擎前置)。本文档是设计来源,不授权 provider/live/抓数/真钱/A 股交叉。(逐轮审查 verdict 在 `docs/SESSION_LOG.md` 顶部,不写在此。)

设计权威(本提案据此推导,不替代): `docs/us_short_system_design.md` §4.5(line 163 动态席位)、§7(line 210 两轴)、§8(line 220-224 强赛道试探名额 + line 223 防御档入场)、§13.1 #27(`theme_probe` 席位数/封顶)、#29(§4.5 动态席位比例触发)、§9 测试 #25(line 435 防御档入场单测)。

---

## 1. 为什么需要它(blocker)

批2 纯引擎 14 刀已建完,**仅剩 `theme_probe` 名额 + 防御档入场**两块未建。两块都消费 `theme_opportunity_state`,但:
- `theme_opportunity_state` 的**取值词表 design-deferred**(未进 `us_short_action_table_contract` 冻结 enum;主设计只点名了 `extreme` 一个值,line 223/435)。
- `theme_probe` **席位矩阵**:主设计只给了 3 个默认(`防御 ≤1` / `进攻+极强 ≤2` / `极度防御 = 0`,§13#27),其余 regime×强度组合(震荡、进攻-非极强)**未指定**。

该词表**同时服务** §4.5 动态选股席位(§13#29)与 §8 `theme_probe`(§13#27),故值得一次定准、避免两处各自为政。

## 2. 提案:`theme_opportunity_state` 词表(4 态,单调强度)

| state | 中文 | 含义 | 强度序 |
|---|---|---|---|
| `no_strong_theme` | 无强赛道 | 本周无任何市场确认的强主题;赛道机会最低 | 0(最低) |
| `normal` | 常 | 基线:有零散主题活动、无突出主线 | 1 |
| `strong` | 强赛道 | 1 个市场确认的强主题(§4.3/§7 确认门过) | 2 |
| `extreme` | 极强 | 主线级强主题(AI 存储/半导体/核电 那类,line 211) | 3(最高) |

约束:
- **单调**:`no_strong_theme < normal < strong < extreme`(强度可比较,便于"≥ strong 才给 probe 名额"这类门)。
- `extreme` 是 `strong` 的顶档(都属 §4.5「强赛道周」),但 §8 对二者**席位上限不同**(见 §4)。
- v1 **不进 `us_short_action_table_contract` 冻结 enum**,先在本 governance preset 里 const-pin;跑够数据、§4.5 接线后再考虑入主 contract(避免过早冻结)。
- **determination(谁产这个值)= 上游 §4.3/§7 市场确认逻辑**,本提案只定词表 + 消费规则,**不**定 determination 算法(那是另一刀/已有 §4.3 确认门的产物)。

## 3. 提案:§4.5 动态选股席位映射(§13#29,总数恒 15)

| `theme_opportunity_state` | core_top + theme_momentum | 主设计依据 |
|---|---|---|
| `no_strong_theme` | **12 + 3** | line 163 无强赛道周 |
| `normal` | **10 + 5** | line 163 常 |
| `strong` | **8 + 7** | line 163 强赛道周 |
| `extreme` | **8 + 7** | 同属强赛道周(line 163 未再细分;v1 与 strong 同配比) |

(§4.5 接线本身不在 `theme_probe` 刀范围;此表是词表对 §4.5 的映射、供一致性,接线是后续独立刀。)

## 4. 提案:§8 `theme_probe` 席位矩阵(§13#27,extra 名额 = 超出常规周建仓上限)

行=`market_risk_regime`,列=`theme_opportunity_state`;值 = 该格允许的 `theme_probe` 名额上限。**粗体 = 主设计明确给定;其余 = v1 保守默认(§13#27 prior,待校准)**。

| regime \ state | no_strong_theme | normal | strong | extreme |
|---|---|---|---|---|
| 进攻 aggressive | 0 | 0 | 1 | **2** |
| 震荡 choppy | 0 | 0 | 1 | 1 |
| 防御 defensive | 0 | 0 | **1** | **1** |
| 极度防御 extreme-def | **0** | **0** | **0** | **0** |

推导/默认依据:
- **`极度防御` 整行 = 0**(line 222「极度防御 = 0、不放行」,硬)。
- **`防御` + (strong/extreme) = 1**(line 221「防御 ≤1」)。
- **`进攻` + extreme = 2**(line 221「进攻+极强 ≤2」)。
- `theme_probe` 只在**有市场确认强赛道**时存在(line 220「市场确认的强赛道额外允许」)→ `no_strong_theme`/`normal` 整列 = 0(无强赛道不给试探名额)。
- **未指定格的 v1 保守默认**(交审重点):`震荡`+strong/extreme = 1(取防御档同值、不放大);`进攻`+strong = 1(强但非极强,不享 ≤2,留给 extreme)。理由:`theme_probe` 是"弱市强赛道仍能试探"的反保守抓手(line 211),进攻档本就有常规建仓量,extreme 才值得 +2;其余从严。**这些是 prior、可被你/校准上调**。

## 5. 提案:`theme_probe` 不变量(line 222-224,大多已在主设计明确)

被批准建的引擎刀须守:
1. **强制最小可执行仓**(`= 最小可执行仓`,绕常规风险预算放大)+ **仅高置信**(`coverage 非 restricted`);`risk_tags` 带 `theme_probe_min_size`(line 222)。
2. **仍受全部 §8 约束**:单票/总仓/同主题/可用现金/`hard_veto`/`symbol_cooldown`/`portfolio_guard` 全部叠加(line 222)。任何一个拦 → 不放行。
3. **硬零(4 条)**:`极度防御` regime / `symbol_cooldown` 期内(单票冷静期)/ `portfolio_guard` cooldown(组合熔断,禁新建/加仓,line 230)/ `hard_veto` → **0、不放行**(line 222/230),先于席位矩阵。theme_probe 是新建仓,故组合熔断 cooldown 也拦它,不只单票冷静期。
4. **成本地板**:复用已建 `engine/us_short_cost_floor.py`(§8 line 224)——试探仓小到 round-trip 成本吃掉期望 → `observe`(`cost_inefficient_min_size`),真拦单。
5. **防御档入场**(line 223 / §9 测试 #25 line 435):`regime=防御` 时新建仓(含 `theme_probe`)**默认只 `pullback_mode`**、关突破追高;**唯一例外** = `theme_opportunity_state == extreme` **且** 当周不跳空 **且** 入场在 `valid_entry_band` 内 → 放行 **1 个**最小仓 `breakout_mode` probe(仍占该格名额、仍受全约束;`极度防御`/`veto`/`cooldown` = 0 仍拦死)。

## 6. 不变量 → 测试钩子(建刀时落)

- 极度防御整行 0;防御 strong/extreme 仅 1;进攻 extreme 2;`no_strong_theme`/`normal` 列 0。
- 硬零(4 条)先于矩阵(极度防御 / 单票cooldown / 组合熔断cooldown / veto 即便 extreme 也 0)。
- 强制最小仓 + coverage restricted → 不放行;全 §8 约束任一拦 → 0。
- 防御档:非 extreme → pullback-only;extreme+不跳空+带内 → 恰 1 个 breakout;extreme+跳空 → 不放行 breakout。
- 词表 strict:未知 `theme_opportunity_state` → fail-closed 到最保守(`no_strong_theme` 等价,不给名额);`extreme` 须精确值。
- 单调强度可比较(≥ strong 的门正确)。

## 7. 开放点(用户决定)

**已批准(用户 2026-06-22)**:Q1 = 保留 4 态(不合并 no_strong/normal);Q2 = 接受未指定格 v1 默认(震荡=1、进攻+strong=1);Q3 = 暂不入 action_table 冻结 enum、仅 preset const-pin;Q4 = determination 留 §4.3/§7、不进 theme_probe 刀。下方四点为原始记录。

1. **词表 4 态**(`no_strong_theme/normal/strong/extreme`)命名 + 是否够用(还是要合并 no_strong_theme 与 normal,或加档)?
2. **§4 矩阵未指定格的 v1 默认**(震荡=1、进攻+strong=1)接受否?要不要进攻+strong 也给 2、或震荡更紧到 0?
3. 词表 v1 **暂不入** `action_table` 冻结 enum、只 preset const-pin —— 同意否?
4. determination(谁/怎么产 `theme_opportunity_state`)**不在本提案/本刀**,留作 §4.3 确认门的产物 —— 同意否?

## 8. 落地路线(批准后)

- **② governance const-pin = 已落地**:`presets/us_short_theme_probe_governance_20260622.json` + `schemas/us_short_theme_probe_governance.schema.json` + 对应 schema-test(batch-1 风格 const-pin 词表/矩阵/不变量/硬零/防御档);本 governance 即该 const-pin 的落地面。
- **③ `engine/us_short_theme_probe.py` + `engine/us_short_theme_opportunity.py`(determination)= 已落地**:theme_probe consume 本 preset + 不变量 + 复用 `cost_floor`、消费 `theme_lifecycle_state`;determination 从 §4.3 主题池判 `theme_opportunity_state`;纯/离线。**§4.5 席位拆分应用 = 已落地**(`engine/us_short_dynamic_seats.py`:state→12+3/10+5/8+7 + 强赛道周 Top6-15 龙头升级)—— 批2 纯决策引擎全部收口。
- **① 折进冻结主设计 `docs/us_short_system_design.md` §4.5/§8 + §13#27/#29 = 可选的后续 design-doc cleanup**(非引擎前置;主设计 §8 已述 theme_probe + 引 §13#27 prior,具体值由本 governance preset const-pin)。
