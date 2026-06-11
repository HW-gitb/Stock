# 生产 EGS 行业/赛道权重提升(industry_heat)— 设计 + 实现切片

**日期**: 2026-06-11
**来源**: 用户(approver)指令 + Codex 优化(2026-06-11)。诉求 = **sector beta:热门赛道带动全行业跟涨**,要让行业/赛道在**生产选股打分**(不只分析/overlay 层)里更重。
**类型**: design + code + tests。**动生产冻结物 `A-EGS/egs_main.py` 打分段**——用户已显式授权(覆盖默认"不改 production 评分"排除)。`起草`(Claude)→`审查`(Codex)强制。

## 0. 激活契约 + 安全网(最重要)
**生产 `active_profile=balanced`(esp .20 / cat .25 / l4 .40 / industry_heat .15)= 直接生效。** 用户目的就是靠提高行业/赛道权重改变选股,故 v1 默认即 balanced;**提交本切片 + 下次 EGS 运行 → 选股按新权重改变**(赛道/行业总权重 0.30→0.40)。
**安全网(不是"默认不生效"):**
- `legacy` profile(esp .20 / cat .30 / l4 .50 / industry_heat 0 = 改前原式)**保留**,仅作 **① 一键回滚锚**(若新选股不对,把 `active_profile` 翻回 `legacy` 即可,不改代码)+ **② 回归测试基准**(证明本次重构除了"有意的权重改动"外没改别的——`test_legacy_byte_identical*` / `test_legacy_final_score_formula`)。
- **每次运行自动产出"新 vs legacy 选股 diff"**(`research/results/egs_weight_comparison_<date>.json`):即使权重已生效,你每周仍能看到改了哪些票、过热占比变化——透明,非盲改。
- industry_heat 只加分排序,**绝不救回** hard_veto/停牌/涨停锁/ST/减持/闪崩;`chasing_high·overheat·未知行业 → Tier2` 降级原样保留。

## 1. 锁定的权重 profile(presets/egs_industry_heat_governance_20260611.json)
| profile | esp | cat(概念) | l4(动量) | industry_heat(SW L2) | 用途 |
|---|---|---|---|---|---|
| `balanced` | 0.20 | 0.25 | 0.40 | 0.15 | **生产 active(v1 生效;赛道/行业 0.30→0.40)** |
| `legacy` | 0.20 | 0.30 | 0.50 | 0.00 | 改前原式;保留作回滚锚 + 回归基准 |
| `aggressive` | 0.15 | 0.25 | 0.40 | 0.20 | 仅对照 variant,非 active |
| `theme_double` | 0.15 | 0.35 | 0.35 | 0.15 | 条件触发的后续变体(见 §4) |

**为何是 balanced**:权重从 l4(-0.10)+ cat(-0.05) 让出给新行业项;**esp 0.20 保留**(基本面/业绩预期锚,防纯炒作票被推上来——Codex 对 Claude 初稿压 esp 的纠正)。cat 是**概念/题材**层、industry_heat 是 **SW L2 行业** beta,两者分开加、避免共线双计。

## 2. industry_heat_score 定义(生产钉死;借鉴 overlay 概念,非字面复用)
`engine/egs_industry_heat.compute_industry_heat_score(df)`:每 SW L2 行业的强度 = 成员 `pct_20d_n` 中位数(若有 `pct_60d(_n)` 再等权混入)→ **跨行业百分位 0-100**;映射回个股。未知行业/缺动量 → NaN(加权时按 0,且未知行业本就降 Tier2)。
- **诚实标注(避免过度声称):** 这是**生产钉死**的定义(测试 `test_definition_pinned_values` 钉死具体值),**借鉴** Slice A overlay `compute_industry_heat` 的"跨行业百分位行业热度"**概念**,但**不是字面调用它**——overlay 用的是独立 benchmark 窗口强度序列(egs_main 打分 df 里没有)。**v1 无 SW L1 fallback**(未知 L2 直接 NaN)。
- **与 l4 的双计处理:** l4 已含零星行业 kicker(`ind_mom_cnt≥3 +5`、alpha+行业不跌 +10)。v1 **保留不动**(保 legacy 逐值一致),industry_heat 作为**独立加项** → 轻度正向重叠,接受并标注;`compute_industry_heat_score` **不修改 l4_score**(测试 `test_does_not_mutate_l4` 钉死);v2 可摘 l4 kicker。

## 3. 单一真相源 + 边界
打分尾段(egs_base→mult→deduct→final_score→tier→准入降级)抽到 **`engine/egs_industry_heat.py` 纯模块**,`egs_main` 与产出 diff **共用**(杜绝重实现漂移;egs_main import 期有 set_token 副作用不可被测试 import,故逻辑必须在独立纯模块)。
- **行业热度只加分排序,绝不救回** hard_veto/停牌/涨停锁/ST/减持/闪崩;`chasing_high·overheat·未知行业 → Tier2` 降级**原样保留**(都在 egs_base 之后施加,模块里忠实复制)。测试证"热门行业 + overheat 的票仍非 Tier1"。
- **双计提示(v1 接受 + 量化)**:l4 已含零星行业 kicker(`ind_mom_cnt≥3 +5`、行业不跌 +10,egs_main:2601/2614)。新增 0.15 行业项与之有轻度重叠;v1 **不动 l4**(保 legacy 逐值一致),在文档/审查里标注;v2 可考虑摘除 l4 kicker。
- 非真钱、不接券商、不自动下单。

## 4. 上线不盲改 + 防遗忘(每周自动产出 diff)
`run_egs` 在 score_l5 后(全量打分 df 在手)调 `write_weight_comparison(df_full, research/results/egs_weight_comparison_<date>.json)`(guarded,失败绝不影响生产 run)。每周自动落盘:
- `legacy_vs`:每个非 legacy profile vs legacy 的 **Tier1 名单变动 + 过热票占比**(看权重改动的影响)。
- `variant_top_n`:**每个 profile(legacy/balanced/aggressive/theme_double)各自的 top-N 选股清单**(默认 15),供并排比较。**明确标 `comparison-only / non-production / NOT tradeable`**:这些只是"各公式会选啥"的参考,**生产实际只用 active(balanced)那份,非 active 的清单绝不可照着交易**(`boundary.variant_lists_are_tradeable=false`)。在前向收益记分牌建好前,它是参考信息、非"换着用"的依据。
- `theme_double` 也每周在列,**不依赖任何人记忆**。
- **`theme_double` = 条件触发、非排期**:仅当滚动 ≥12 周里其 Tier1 **前向 1–3 周收益 > balanced** 过噪声门槛、且过热/回撤不更差,才走审查过的 governance 改动提升;否则永不自动转正。
- **本切片只产横截面 diff(无前向收益)**;前向收益记分牌 + 提升 auto-flag = register forward-item 后续件(需累积周度前向数据)。

## 5. 交付物
- `engine/egs_industry_heat.py`(industry_heat + 治理权重 + final_score_and_tier 单一真相源 + selection_diff + write_weight_comparison)+ `tests/test_egs_industry_heat.py`。
- `presets/egs_industry_heat_governance_20260611.json` + `schemas/egs_industry_heat_governance.schema.json`(profile 和=1 由 parity 测试守)。
- `A-EGS/egs_main.py` 接线:算 industry_heat_score、打分尾段改调模块(active=balanced 生效;legacy 逐值一致仅作回滚锚)、输出 `scores.industry_heat_score` + CSV 列 + 每周 diff。
- `schemas/analysis_input.schema.json`:新增可选 `scores.industry_heat_score`(旧 artifact/example 无此字段仍合法)。

## 6. 边界(总)
**生产选股权重 v1 生效(balanced active → 下次运行改变选股,用户目的)**;不真钱、不 ship-gate、不接券商。回滚 = 翻 active_profile→legacy(一行,不改代码)。`theme_double` 后续条件触发。前向收益记分牌/auto-flag 后续(register forward-item)。V14.2 + Phase 5/overlay 不动;industry_heat 只加分排序、不救回任何 veto/降级。
