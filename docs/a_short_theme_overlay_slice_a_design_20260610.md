# Slice A — EGS 赛道热度 overlay 详细设计(design-only)

**日期**: 2026-06-10
**父设计**: `docs/a_short_theme_overlay_phase5_design_spec_20260610.md`(已 review-passed,commit `f918594`)
**类型**: design-only。**授权:无 runner 代码、无数据抓取、无 EGS production 行为/权重变更、无真钱、无 ship-gate。** 本文把 overlay 的计算契约钉死;runner 子切片(另走 起草→审查→提交→执行)才落代码,并在那时更新 EGS governance + parity 测试。
**处置**: 本切片显式处置父设计审查的 Codex Optional **O1(PIT 覆盖)**与 **O2(冻结阈值 + 升级规则)**。

---

## 1. 范围(v1)

新增**非 production 的 comparison-track overlay**,对 EGS **现有候选池重排序**,产出与 baseline 并行的 `overlay_rank` + 组件分。

- **不改** L0–L5 准入、不改 production `final_score` / `tier` / 推荐口径。
- 仅输出 comparison artifact 供 §6 评估。
- **仪表化**:记录 L0–L5 阶段被丢弃名字及其赛道热度(被踢 vs 留下),为 v2"是否改准入"留证据。

**输入(全部 EGS 已抓,无新数据源)**: `concept` / `concept_detail`(L3:concepts、concept_members、stock_concepts)、`daily`(pct_chg, amount)、`index_daily`(CSI300 / CSI1000 + 全市场聚合)、SW L1/L2 映射、以及每股已算的 `esp_score / l4_score / overheat_flag / chasing_high / cat_flag(CHASE) / pct_5d / pct_20d / drawdown_20d`。

---

## 2. 组件计算契约

| 组件 | 角色 | 计算 | 输出域 |
|---|---|---|---|
| `theme_heat_score` | 加权项(lead) | 每概念算 5d 与 20d 成交额加权 member 涨跌强度 → 各窗口全市场概念百分位;每股取其所属概念的 `0.5×pct_rank_5d + 0.5×pct_rank_20d` 最大值(扩展现有 5d 单窗口 `cat_score`) | 0–100 |
| `industry_heat_score` | 加权项(incremental) | 每 SW L2 算 20d/60d 收益相对 CSI300/CSI1000/全市场中位的强弱 → 跨行业百分位;按个股 L2 映射(L2 未知/过薄 → L1 回退) | 0–100 |
| `theme_breadth_score` | **门槛** | 个股 top 概念内:上涨 member 占比 ∧ 放量 member 占比(amount_5d>amount_20d) | 0–1 |
| `theme_persistence_score` | **乘子(0~1)** | top 概念连续处于强度高分位(top 30%)的天数 / 窗口 → 0~1,乘到 `theme_heat` | 0–1 |
| `candidate_theme_fit_score` | **门槛+乘子** | 代理三选合成:① 个股在 top 概念内的成交额权重;② 个股日收益对 top 概念虚拟指数的滚动相关性;③ 多概念交叉确认数。**三者皆不可算 → `unknown`** | 0–1 / unknown |
| `crowding_risk_family` | **风险族** | 成员 = `overheat_flag ∨ chasing_high ∨ CHASE ∨ 高位缩量`;**不独立扣分**,触发 → 降级或转 burst(每候选一次硬处理),热度加分不得救回 | bool 集 |

**正交化(防共线,父设计 §2 C;R-ASLICEA-INDUSTRY-ORTHO-SCALE)**: 跨候选池把 `industry_heat` 对 `theme_heat` 做横截面回归取残差(theme 领先,industry 只贡献增量);`theme_heat` 不残差化。**残差零中心、尺度任意,不可直接进 0.15 权重**——必须先把残差**横截面百分位归一化回 0–100**:`industry_heat_norm⊥ = pct_rank(residual) × 100`,使其与 `esp / l4 / theme_eff`(均 0–100)同尺度可加权。进权重的是 `industry_heat_norm⊥`,不是原始残差。

**冻结单一权重(v1 comparison-track,不做权重搜索)**:
```
fit_pass    = (fit ≠ unknown) ∧ (fit ≥ fit_floor)        # 单一定义, 全文/输出/测试复用
eligible    = (theme/industry/breadth ≥2 项过 pass) ∧ fit_pass
bonus_gate  = eligible ∧ (¬crowding_hit)                  # 赛道红利唯一门
theme_eff   = theme_heat_score × persistence_mult × fit_mult     （fit_mult = 1 当 fit_pass 否则 0）
overlay_base  = esp_score×0.15 + l4_score×0.45
overlay_score = overlay_base
              + 0.25 × (theme_eff            当 bonus_gate 否则 0)
              + 0.15 × (industry_heat_norm⊥  当 bonus_gate 否则 0)
              （industry_heat_norm⊥ = 残差百分位归一化回 0–100, 见 §2 正交化; 与其余 0–100 项同尺度）
overlay_rank  = overlay_score 降序
注:**crowding 命中 = 一次硬处理 → 剥夺赛道红利**(overlay 退回 esp+l4 base),热度不得救回;
   不再用乘 0.5 的"降级系数"(会被高热度压过,不满足"不得救回")。
```

**赛道红利资格门槛**: `theme_heat / industry_heat / breadth` **≥2 项过 pass 阈值** ∧ `fit_pass`(定义见上,= `fit≠unknown ∧ fit≥fit_floor`,与权重公式 `fit_mult` 用同一条件)。不满足 → 该股 overlay 只吃 `esp+l4` 部分,不获赛道红利。

---

## 3. O1 处置 — PIT 覆盖(概念归属 + SW 映射 双 PIT)

- overlay 回测 **必须 `--l3-mode pit` + `state/l3_snapshots/`** 取 **as-of 概念归属**。
- **新增**:SW L1/L2 行业映射也必须 PIT——用 as-of 日期的 SW 映射快照算历史 `industry_heat`,**严禁用今日 SW 映射**。
- 任一(概念归属 **或** SW 映射)在某时段无 PIT 快照 → 该时段 **forward-only**,排除出 PIT 回测。
- schema/测试要让"用当前映射算历史热度"在结构上不可能(显式 `pit_source` 标记 + 断言;runner 子切片落测试)。

## 4. O2 处置 — 冻结阈值 + 升级规则(进 governance artifact,不留 prose 裁量)

runner 子切片须把以下数值**冻进 governance artifact + parity 测试**:
- `breadth` 门槛(上涨/放量 member 占比下限)
- `theme_heat / industry_heat` 的 pass 百分位阈值(如 ≥ p70)
- `persistence` 高分位定义 + 窗口
- `fit_floor`
- **启用裁决**: 本 Slice A 不再定义独立的 overlay 升级规则；唯一裁决轨为 P4a `overlay_adjudication`。它在正式发布后累积 Stage3 rank-source 对照证据，任何启用仍须独立审查和用户决定。

---

## 5. 输出契约(overlay artifact,runner 子切片建 JSON schema)

每 as-of 一份,per candidate 字段:`ts_code`、6 组件分、`industry_heat_norm⊥`(归一化后实际进权重的值)、`theme_eff`、`overlay_score`、`overlay_rank`、`baseline_rank`、资格 flags(theme/industry/breadth pass、`fit_pass`、`fit_unknown`)、`crowding_risk_family` 命中集、`pit_source`(concept/SW 各自 pit|forward)。另含 run 级 `dropped_at_l0_l5`(被丢弃名字 + 其 theme_heat)仪表化块。**非 production**:不写回 `final_score`/`tier`。

---

## 6. 验证(comparison-track,不混 production)

overlay 与 baseline **同候选池**并行;excess **同时看 CSI1000 ∧ CSI300**;判据:月度 clustered-t / drawdown / 胜率 / 坏票率 / false-negative,不只看均值。**两道门**(父设计 §5):≥12 obs + 稳定胜出 → 升 production 排序;full-size/真钱 另走 12 月 ship gate。没稳定胜出 → 继续 research。

---

## 7. 不变量 → runner 子切片必须落的测试

- **消费完整性**:每个组件都映射到 `overlay_score` / 资格 / 风险族效果;无悬挂 → FAIL。
- **热度不覆盖硬风控**:任一 hard_veto 或 crowding 命中 → 赛道红利失效。
- **fit_pass 门控(单一定义)**:`fit_pass=(fit≠unknown)∧(fit≥fit_floor)`;`fit_pass=false` → theme 与 industry 红利均 0(不许编核心股)。权重公式 `fit_mult`、资格门槛、输出 flag 必须用同一个 `fit_pass`,不得出现"仅 fit≠unknown"与"fit≥floor"两套口径。
- **theme⊥industry + 同尺度**:industry 对 theme 残差化后**百分位归一化回 0–100**(`industry_heat_norm⊥`)再进权重;**禁止直接用零中心残差**加权。
- **PIT 双覆盖**:用当前 concept/SW 映射算历史时段 → FAIL;无快照时段 forward-only。
- **冻结阈值在 governance artifact**(parity 测试)。
- **v1 不动 production**:不改 `final_score`/`tier`/准入。

---

## 8. 治理与边界

- runner 子切片改 EGS 须同切片更新 `presets/a_short_screening_threshold_governance_20260602.json` + parity 测试,保持 additive / non-production / comparison-track。
- 本切片 design-only,授权无代码/无 fetch/无 run/无 production 变更/无真钱。
- 与 IV feed slice、Slice B、pipeline 的关系见父设计 §6 路线。
