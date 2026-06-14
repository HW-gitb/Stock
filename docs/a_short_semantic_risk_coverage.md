# A-short 语义风险层覆盖说明(coverage map)

**边界(贯穿全层;生产 vs 非生产 M6.7 区分,稳定锚点见 `docs/a_short_semantic_risk_contract.md`)**:**不进 production EGS scoring/`decision`/`veto`、不写 `result/a_short`、不做历史回测证据、`unknown` 绝不伪装 `clear`**(永久)。**web_llm 永久 advisory-only、绝不硬否决**。**但**经校验的 official_structured **high 且证据齐全(`url_or_pdf` 非空)** 才可在**非生产 M6.7** 内产 **advisory `否决`**(`semantic_official` family,绝不救回);**high 缺 URL/PDF → pending 待核、不否决**;详见 §融入 M6.7——这是 M6.7 advisory 否决、非 production hard veto。对应 v14.2 语义项 M2.1-M2.5 / M3.1 中**语义/检索类**那部分;`industry_heat`(生产动量热度)是**另一回事**,不在此层。**迁移期已收口(Slice 3b)**:独立 summary CLI + 面板均退役、weekly_screening 现跑 M6.7;`a_short_semantic_risk_summary` 仅留 M6.7 复用的 builders;最终语义直接进 M6.7。

## 两个置信层(严格分置)

| 层 | 源 | 口径 | 谁产出 | 切片 |
|---|---|---|---|---|
| **official_structured** | 巨潮 cninfo `hisAnnouncement/query`(`stock`="code,orgId") | 按披露日 **PIT**(canonical 且 ≤ as_of);标题→risk_type+severity 粗筛 | **headless**(`a_short_semantic_risk_summary.py`) | 1 / 2a / 2b-i |
| **web_llm** | 新浪/通用 web/用户上下文 | **LIVE-only**(`pit_capable=false`,不可复现、绝不进历史回测);soft flag | 产出路径(当前/过渡)单一来源见契约 §web_llm 产出路径 | 1 / 2 / 2b-ii |

## 覆盖矩阵(v14.2 语义风险项 → 本层)

| v14.2 语义项 | 本层覆盖 | status |
|---|---|---|
| 监管(问询/关注/立案/处罚/警示) | official_structured(cninfo PIT 公告,severity high/medium)+ web_llm 佐证 | 已建(2a 结构化 + 2b-i 分级);精判经 web_llm(产出路径见契约 §web_llm 产出路径)。**注:当前是配置 lookback(默认 90 天)内、披露日 ≤ as_of 的 PIT 官方公告证据,并非精确"48h 新鲜度"窗口**——精确 48h 时效 / 媒体负面的实质精判见契约 §web_llm 产出路径(或未来 recency 字段),headless 不强制 48h |
| 媒体负面 | web_llm advisory(web 文本经判官判断) | web_llm 已建;产出路径见契约 §web_llm 产出路径 |
| 基本面行业景气(≠ industry_heat 动量) | web_llm `status` tailwind/headwind | 同上(产出路径见契约 §web_llm 产出路径) |
| 隐蔽风险线索(资金占用/违规担保/诉讼…) | official_structured 粗筛(宽关键词,最窄抑制只压明确否定式)+ web_llm 实质降级 | headless 粗筛已建;**实质判断靠 web_llm(产出路径见契约 §web_llm 产出路径)**(headless 关键词注定粗,见下) |

## official_structured 关键词粗筛的已知边界(为什么必须有 web_llm)
- 宽关键词(如 `资金占用`)会命中年报季**例行合规件**("…非经营性资金占用…情况专项说明/汇总表",结论通常无占用)。最窄抑制只压**明确无占用否定式**(不存在/未发生/无新增…);**裸例行件仍报 `risk[medium]`**,交 web_llm advisory 降级(见契约 §web_llm 产出路径)。
- 取舍:headless 残余误差**只会是误报(web_llm advisory 降级),绝不漏报**真风险。`high` severity(立案/处罚/ST)永不被抑制。
- 故 official_structured 是**粗筛 + 证据(PIT 公告 title/category/date/url)**,**实质性"是不是真风险"由 web_llm advisory 判**(产出路径见契约 §web_llm 产出路径)。

## web_llm 不变式单一来源
- web_llm 不变式矩阵(unknown 中性三元组 `unknown/unknown/no_action`、任何非-unknown 态须带 `sources`、risk_level 配对、action 枚举等)**= 单一来源 `docs/a_short_semantic_risk_contract.md`,本文件不复述**(B2 contract-anchor,防部分复述漂移)。代码侧由 summary + DeepSeek adapter 共用的 `_web_llm_consistency_error` 强制;skill-patch 路径已在 Slice 3a 退役。

## 语义行内化进 M6.7 周报(Slice 3b:独立面板已退役)
- 语义 advisory 自 **Slice 3b 逐票行内化**进 M6.7 周报 .md(`runners/a_short_m67_render._semantic_line`,从每票 `machine.layer.semantic_risk` 渲染);**独立面板渲染已退役**。advisory 仍只是引擎层 trace 的渲染,**绝不进确定性周报 JSON**、不改任何结论。

## 运行接入(cadence)
- **M6.7 advisory 接入 `runners/weekly_screening.ps1`**(Stage 4,旁路;Slice 3b-2):周报 egs_main 成功后,以当次 `result/a_short/<as_of>/analysis_input.json` 为输入跑 M6.7 pipeline(建市场 IV feed + `a_short_weekly_pipeline`,语义 cninfo official + DeepSeek web 逐票**行内**),落 `research/results/a_short/<as_of>/weekly_m67.json`。**advisory-only 旁路**:真取数失败绝不阻断周报(同 canary/tracker),禁 result/a_short,`-SkipSemanticRisk` 可关。
- **web_llm 产出路径见契约 §web_llm 产出路径(单一来源)**。`weekly_screening.ps1` Stage-4 现跑 M6.7 pipeline(语义行内,3b-2);独立 summary CLI 已退役。
- watch pool = 当次 EGS `analysis_input.candidates`;M6.7 provider 内用 `main_board_top15` 过主板 Top15(纯函数单测)。

## 融入 M6.7 打分(迁移中,目标:不再独立 artifact/面板)
> 方向见桌面设计 `semantic_into_m67_design_20260613.md`(用户+Codex 收敛)。分片落地。
- **Slice 1(已建)**:official_structured 经引擎 **`semantic_official` risk family** 融进 M6.7——official **high**(证据齐全)→否决(复用引擎 hard_veto 机制,绝不救回)、**medium/low**→"待核"(不扣分/不清/不降星)、**clear/unknown/无输入**→中性;消费门 `_validate_semantic_official` fail-closed(完整 PIT 证据契约);trace 进 `machine.layer.semantic_risk`。
- **Slice 1b(已建)**:真 cninfo 自动接入周报——`main` 在真 run(`--confirm-fetch-authorized` 且未 `--skip-semantic`)时,`_build_cninfo_semantic_provider` 批量 cninfo 取数 → 逐票 `build_official_structured` → 喂进 M6.7;**advisory 旁路非阻断**(取数失败→全 unknown 中性,不阻断周报)。**方案 A(空 URL)**:cninfo 偶缺 adjunctUrl → official event url_or_pdf 空 → 引擎把**缺 URL 的 high 事件降为 pending 待核**(不否决、不崩),只有证据齐全(含非空 URL)的 high 才驱动否决。
- **Slice 2(已建)**:DeepSeek web/LLM **判官**接进 M6.7——周报内 `_build_deepseek_web_llm_provider`(一次性批量抓 sina → 逐票 `runners/a_short_deepseek_semantic_adapter.judge_web_llm` 让 DeepSeek 判,**缺 key/SDK/抓取失败/答复不可解析/违反契约 → 全 unknown 中性,非阻断、绝不打印 key**)产 `web_llm`;引擎 `semantic_web_llm` 族:web **risk/risk_candidate/headwind 且有 sources 证据 → downgrade**(**绝不 hard_veto**),tailwind/clear_light 不救回硬风控,unknown/无输入/违反契约 → 中性化(trace 标 `invalid_neutralized`,非静默)。web_llm 跨字段不变式复用 `_web_llm_consistency_error`(单一来源)。两层来源仍在 `machine.layer.semantic_risk` 可追溯。
- **Slice 3b 已收口**:render 行内化 + 废弃独立面板(3b-1)+ 退役独立 summary CLI/Stage-4 + weekly_screening 跑 M6.7(3b-2,M6.7 端到端 `执行` 验证通过)。**待**:deterministic promotion(见下,~4 周真实 advisory 证据门槛)。advisory-only / unknown-not-clear / 不进 production scoring / 不进回测 边界全程保留。

## 不在本层(deferred)
- **Slice 3 — deterministic promotion**:把 cninfo 官方命中升级为**生产硬否决** + 处置既有 DeepSeek `POL-RISK-VETO` legacy-conflict + cninfo 两路径去重。门槛高(动冻结相邻 egs_main stage3),设计上待 advisory 跑出几周真实结果后再决定。追踪:`docs/system_risk_register.md` deferred-open 条目 + `tests/test_semantic_risk_slice3_guard.py`(防忘 CI 守护)。
