# A-short 语义风险层覆盖说明(coverage map)

**边界(贯穿全层;生产 vs 非生产 M6.7 区分,稳定锚点见 `docs/a_short_semantic_risk_contract.md`)**:**不进 production EGS scoring/`decision`/`veto`、不写 `result/a_short`、不做历史回测证据、`unknown` 绝不伪装 `clear`**(永久)。**web_llm 永久 advisory-only、绝不硬否决**。**但**经校验的 official_structured **high** 可在**非生产 M6.7** 内产 **advisory `否决`**(`semantic_official` family,绝不救回;详见 §融入 M6.7)——这是 M6.7 advisory 否决、非 production hard veto。对应 v14.2 语义项 M2.1-M2.5 / M3.1 中**语义/检索类**那部分;`industry_heat`(生产动量热度)是**另一回事**,不在此层。**迁移期**:独立 `a_short_semantic_risk_summary` artifact + 周报面板是过渡形态(非最终不变式),最终语义直接进 M6.7。

## 两个置信层(严格分置)

| 层 | 源 | 口径 | 谁产出 | 切片 |
|---|---|---|---|---|
| **official_structured** | 巨潮 cninfo `hisAnnouncement/query`(`stock`="code,orgId") | 按披露日 **PIT**(canonical 且 ≤ as_of);标题→risk_type+severity 粗筛 | **headless**(`a_short_semantic_risk_summary.py`) | 1 / 2a / 2b-i |
| **web_llm** | 新浪/通用 web/用户上下文 | **LIVE-only**(`pit_capable=false`,不可复现、绝不进历史回测);soft flag | **skill 在环**(LLM 产 `a_short_semantic_risk_web_llm_patch`,headless 校验+合并) | 2b-ii |

## 覆盖矩阵(v14.2 语义风险项 → 本层)

| v14.2 语义项 | 本层覆盖 | status |
|---|---|---|
| 监管(问询/关注/立案/处罚/警示) | official_structured(cninfo PIT 公告,severity high/medium)+ web_llm 佐证 | 已建(2a 结构化 + 2b-i 分级);精判待 2b-ii skill。**注:当前是配置 lookback(默认 90 天)内、披露日 ≤ as_of 的 PIT 官方公告证据,并非精确"48h 新鲜度"窗口**——精确 48h 时效 / 媒体负面判断属 2b-ii-B skill/prompt 或未来 recency 字段责任,headless 不强制 48h |
| 媒体负面 | web_llm advisory(skill web 搜索 + 判断) | 契约+合并已建(2b-ii-A);skill prompt 已建(2b-ii-B),运行时 skill 在环产 patch + apply 合并 |
| 基本面行业景气(≠ industry_heat 动量) | web_llm `status` tailwind/headwind | 同上(2b-ii skill) |
| 隐蔽风险线索(资金占用/违规担保/诉讼…) | official_structured 粗筛(宽关键词,最窄抑制只压明确否定式)+ web_llm 实质降级 | headless 粗筛已建;**实质判断必须靠 2b-ii skill**(headless 关键词注定粗,见下) |

## official_structured 关键词粗筛的已知边界(为什么必须有 web_llm)
- 宽关键词(如 `资金占用`)会命中年报季**例行合规件**("…非经营性资金占用…情况专项说明/汇总表",结论通常无占用)。最窄抑制只压**明确无占用否定式**(不存在/未发生/无新增…);**裸例行件仍报 `risk[medium]`**,交 web_llm/skill 降级。
- 取舍:headless 残余误差**只会是误报(skill 降级),绝不漏报**真风险。`high` severity(立案/处罚/ST)永不被抑制。
- 故 official_structured 是**粗筛 + 证据(PIT 公告 title/category/date/url)**,**实质性"是不是真风险"由 web_llm advisory(2b-ii skill)判**。

## web_llm enrichment 契约(2b-ii-A)
- skill 产出 `a_short_semantic_risk_web_llm_patch`(schema:`schemas/a_short_semantic_risk_web_llm_patch.schema.json`)。
- `apply_web_llm_patch(summary, patch)`(headless,纯函数):校验 patch(schema + 跨字段不变式 + 无重复 ts_code)→ **只**写 `web_llm`/`sources`/`confidence`/`summary` 到匹配候选 → **绝不**碰 `official_structured`/`boundary`/`rank`/`scan_tier`/`ts_code`/`coverage` → 合并后整体过 `validate_summary_consistency`。patch 不能引入 universe 外代码;覆盖语义=替换(非追加)。
- web_llm 不变式矩阵(unknown 中性三元组 `unknown/unknown/no_action`、任何非-unknown 态须带 `sources`、risk_level 配对、action 枚举等)**= 单一来源 `docs/a_short_semantic_risk_contract.md`,本文件不复述**(B2 contract-anchor,防部分复述漂移)。代码侧由 summary + patch 共用的 `_web_llm_consistency_error` 强制。

## web/LLM skill 层 + 面板接入(2b-ii-B,已建)
- **skill prompt** `skills/a_short_analysis/prompts/semantic_risk_web_llm.md`:编排既有 6 个分类 prompt(regulatory_48h/policy_news/industry_trend/hidden_risk/earnings_no_good_repair/cross_market_linkage)→ 产 `a_short_semantic_risk_web_llm_patch`;运行时 skill 在环、`apply_web_llm_patch` 校验合并。
- **面板接入 weekly pipeline**:`a_short_weekly_pipeline --semantic-risk-summary <summary.json>` → `_semantic_panel_from_summary`(渲染前过其消费门)→ `render_semantic_risk_panel` **仅追加到周报 .md**(`---` 分隔),**绝不进确定性周报 JSON**。消费门的校验步骤**单一来源** = `_semantic_panel_from_summary` docstring,本处只指向、不复述(防漂移)。

## 运行接入(cadence)
- **Step 1(headless official_structured)接入 `runners/weekly_screening.ps1`**(Stage 4,旁路):周报 run egs_main 成功后,以当次 `result/a_short/<as_of>/analysis_input.json` 候选为 watch pool(`--analysis-input`,runner 内再过主板 Top15),真 cninfo 取数产 `research/results/a_short/semantic_risk_<as_of>/summary.json`。**advisory-only 旁路**:cninfo 失败/反爬绝不阻断周报(同 canary/tracker),落 research 非生产 lane(禁 result/a_short),`-SkipSemanticRisk` 可关。
- **Step 2(web_llm)仍需 2b-ii skill(LLM 在环)另跑**——脚本只产官方结构化层(web_llm 全留 unknown),不能纯自动化。
- watch pool 抽取 = `a_short_semantic_risk_summary._watch_pool_from_analysis_input`(纯函数,单测)。

## 融入 M6.7 打分(迁移中,目标:不再独立 artifact/面板)
> 方向见桌面设计 `semantic_into_m67_design_20260613.md`(用户+Codex 收敛)。分片落地。
- **Slice 1(已建)**:official_structured 经引擎 **`semantic_official` risk family** 融进 M6.7——official **high**→否决(复用引擎 hard_veto 机制,绝不救回)、**medium/low**→"待核"(不扣分/不清/不降星)、**clear/unknown/无输入**→中性;trace 进 `machine.layer.semantic_risk`。`normalize_candidate(semantic=)` + `main(semantic_provider=)` 透传;真 cninfo provider 接入 = Slice 1b。
- **待后续片**:真 cninfo 自动接入(1b)、DeepSeek web_llm adapter(2)、render 行内化 + 废弃独立面板/Stage4、weekly_screening 一键串联(3)。advisory-only / unknown-not-clear / 不进 production scoring / 不进回测 边界全程保留。

## 不在本层(deferred)
- **Slice 3 — deterministic promotion**:把 cninfo 官方命中升级为**生产硬否决** + 处置既有 DeepSeek `POL-RISK-VETO` legacy-conflict + cninfo 两路径去重。门槛高(动冻结相邻 egs_main stage3),设计上待 advisory 跑出几周真实结果后再决定。追踪:`docs/system_risk_register.md` deferred-open 条目 + `tests/test_semantic_risk_slice3_guard.py`(防忘 CI 守护)。
