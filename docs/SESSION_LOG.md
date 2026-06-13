# Session Log

跨 LLM 认知交接日志。**reverse-chronological，最新 entry 在顶部**。

本文件存在的目的：commit message 和 handoff 记录"改了什么 / 为什么改"，但不记录 "试过什么没成 / 试过的方案为什么被否决 / 当前 LLM 的纠结点 / 下一步该做什么的判断"。这一层认知信息在跨 LLM 协作时最容易丢失。

进项目前每个 LLM 必读：本文顶部 1-3 条最近 entry。完整规则见 `AGENTS.md §Session log discipline`。

---

> 📦 **历史归档**:2026-05-25 … 2026-06-12 的 861 条更早 entry 已逐字移至 `docs/archive/session_log/session_log_archive_2026-05-25_to_2026-06-12.md`(完整历史,不丢)。本次归档时保留了归档前最新 30 条;之后新增 entry 继续累积到本文件,过大时再按 `AGENTS.md §Session log discipline → 归档` 归档。追溯更早请开归档文件。

## 2026-06-13 — Claude `执行` (语义风险 advisory 层首次真实运行 — Slice 3 证据时钟起点)

**What ran**: 语义风险 advisory 层首次端到端真实运行(headless cninfo + skill-in-loop web_llm)。
- watch pool = 最近生产 EGS `result/a_short/20260605/analysis_input.json` 的 15 个主板候选;as_of=20260605。
- headless 真 cninfo 取数:`python runners/a_short_semantic_risk_summary.py --as-of 20260605 --watch-pool <15码> --out research/results/a_short/semantic_risk_20260605/summary.json --confirm-fetch-authorized`。覆盖 15/15(unknown=0/failed=0),官方结构化 9 个 risk(全 `fund_occupation/medium`、0 high)——经标题确认均为 2025 年报季例行《非经营性资金占用及对外担保情况专项说明》(已知假阳性类)。
- 2b-ii web_llm skill(我在环,WebSearch 单轮 LIVE)产 `web_llm_patch.json` → `apply_web_llm_patch` 校验合并 → `render_semantic_risk_panel` 出 `panel.md`。

**Result(merged web_llm)**:4 risk_candidate(601375 国元/601688 华泰 投行罚单·警示函=low;600592 龙溪 福建证监局责令改正+诚信档案 / 601211 国泰海通 子公司高管被港 SFC·ICAC 调查=medium·manual_review)+ 1 headwind(600743 华远 2025 预亏+债务集中到期)+ 3 clear_light 降级例行件 FP(000543 皖能/603790 雅运/603916 苏博特)+ 7 unknown(601377 兴业 无近期实质保留 + 6 个 official-clear 本轮未搜)。**无 high 级真实风险**。

**边界**:LIVE/单轮/不可复现/advisory-only;不硬否决、不改 EGS/Phase5/选股;产物全在 research 非生产 lane(`research/results/a_short/semantic_risk_20260605/` summary+patch+panel),未入库(可复现运行产物)。

**意义/留痕**:这是首份真实 `a_short_semantic_risk_summary` advisory artifact → **Slice 3(deterministic promotion)的 ~4 周证据时钟从 2026-06-13 起算**(目标累积窗口 ~2026-07-11 后再评估;由 `project_slice3_reminder_after_advisory_weeks` memory + `test_semantic_risk_slice3_guard` 追踪)。建议后续每周用当周生产 EGS Top15 同批再跑,累积 forward 证据。

**Next(待用户)**: ① V14.3 bootstrap / 20260612 生产实盘;② 下周用新 Top15 再跑一轮 advisory。

## 2026-06-13 — Codex `审查 PASS` (weekly aux overlay duplicate-candidate bypass)
- **Verdict/Action**: PASS. Duplicate overlay rows are now rejected before dict collapse; weekly aux candidate-lineage closure is verified.
- **Required**: `R-ASHORT-WEEKLY-AUX-ARTIFACT-CANDIDATE-SET-MISMATCH` — full detail in `docs/system_risk_register.md` (single source).
- **Verify**: 152 tests OK; py_compile OK; `git diff --check` clean; custom duplicate-overlay probe rejected with no JSON/MD.
- **Next**: Claude `提交`.

## 2026-06-13 — Claude `修复` (周报 overlay 重复行旁路 — dict 折叠前查重 + 修测试断言)
- **Verdict/Action**: `_load_validated_overlay` 在 `{ts_code: row}` 折叠**之前**对原始 candidate ts_code 列表查重,重复即 SystemExit(堵住 3 行折叠成 2、set 比对看不到重复、星级被悄改);并修正测试 helper:overlay abort 断言改为 json/md **各自独立** 不存在(旧 `not(a and b)` 会放过 partial write)。
- **Required**: `R-ASHORT-WEEKLY-AUX-ARTIFACT-CANDIDATE-SET-MISMATCH` — 完整详情见 `docs/system_risk_register.md`(单一来源,本处不复述)。
- **Verify**: 新增 dup-overlay 测试(已探明该 overlay 过 schema+consistency,真正撞 dup 门)→ abort-no-file;semantic 侧本就按有序 candidates 列表比对、天然防重复;weekly 套件 62 OK;五套合计 152 OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A 把"dict 折叠隐藏重复"作类补(查重置于折叠前);B 改动仅 overlay loader + 测试,未碰 scoring/schema/Phase5;C 反向:正向匹配 overlay 仍双写;**自检并修了 Codex 点出的测试断言漏洞(各自独立 assert)**;F:py_compile OK、diff/BOM 干净。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (weekly aux overlay duplicate-candidate bypass)
- **Verdict/Action**: FAIL. semantic wrong-pool and overlay missing/wrong-set are fixed, but duplicate overlay `ts_code` rows still bypass the lineage gate after dict/set collapse.
- **Required**: `R-ASHORT-WEEKLY-AUX-ARTIFACT-CANDIDATE-SET-MISMATCH` — full update in `docs/system_risk_register.md` (single source).
- **Verify**: semantic/weekly suite 128 OK; doc-governance/route 23 OK; `git diff --check` clean; custom duplicate-overlay probe accepted 3 rows and wrote JSON+MD.
- **Next**: Claude `修复`.

## 2026-06-13 — Claude `修复` (周报 aux artifact 候选池血缘门 — semantic + overlay)
- **Verdict/Action**: `main` 在任何写盘前把两个 aux artifact 绑定到周报 EGS 候选集:semantic summary 的 universe/candidates 必须 == 由 analysis_input 按 `main_board_top15` 推出的预期池(否则 ValueError);overlay 必须恰好覆盖周报候选集(否则 SystemExit,堵住缺行被静默降级)。
- **Required**: `R-ASHORT-WEEKLY-AUX-ARTIFACT-CANDIDATE-SET-MISMATCH` — 完整详情见 `docs/system_risk_register.md`(单一来源,本处不复述)。
- **Verify**: 新增对抗测试:semantic 错池 / overlay 缺候选 / overlay 错集(后两者用内部合规 overlay,确保触发我的血缘门而非 overlay 自身一致性)均 abort-no-file;正向匹配池 semantic + overlay 仍双写;旧 tamper/as_of/缺文件测试改用匹配池基底;weekly 套件 61 OK;五套合计 151 OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A 按 Codex sibling-artifact 矩阵一次覆盖(semantic+overlay 各:错池/缺行/正向);B 改动仅 main 消费校验、未碰 EGS/overlay scoring/schema/Phase5;C 反向:正向匹配池双写、JSON 仍不含 advisory;D 走精确集合相等非启发式;F:py_compile OK、diff/BOM 干净。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (weekly aux artifact candidate-set mismatch)
- **Verdict/Action**: FAIL。上轮 partial-write 已修,但同日错候选池的 semantic summary / overlay 仍会被 weekly pipeline 接受并写出。
- **Required**: `R-ASHORT-WEEKLY-AUX-ARTIFACT-CANDIDATE-SET-MISMATCH` — 完整 Required/风险/边界/closure 见 `docs/system_risk_register.md`(单一来源,本处不复述)。
- **Verify**: 148 tests OK; py_compile OK; `git diff --check` clean; custom probes confirmed same-date semantic summary candidate mismatch and overlay missing-candidate mismatch both still write outputs.
- **Next**: Claude `修复`。

## 2026-06-13 — Claude `修复` (Slice 2b-ii-B 周报面板 — validate-before-write,消除 partial JSON)
- **Verdict/Action**: `main` 把可选 semantic 面板的 load+校验+渲染移到 `write_weekly_report`/`write_weekly_markdown` **之前**;非法 summary 在落盘前 abort,既不留 weekly.json 也不留 .md(与 analysis-input/价格/篡改周报同一 abort-no-file 模式)。
- **Required**: `R-ASHORT-SEMANTIC-PANEL-MAIN-PARTIAL-WRITE-ON-INVALID-SUMMARY` — 完整详情见 `docs/system_risk_register.md`(单一来源,本处不复述)。
- **Verify**: 新增 5 个 main-level 测试:合规路径双写(JSON 形状不变、advisory 绝不进 JSON、md 含 advisory)+ 四个 abort-no-file(schema_version 篡改 / boundary const 篡改 = ValidationError;as_of 错配 = ValueError;summary 文件缺失 = FileNotFoundError)均断言 json 与 md 皆不存在;weekly 套件 58 OK;五套合计 148 OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A 按 Codex 要求的矩阵一次覆盖(schema 篡改 + boundary + 非 schema 的 as_of + 缺文件,各断言无 json 无 md);B 改动仅 main 出口顺序、未碰 schema/scoring/Phase5;C 反向:合规路径仍双写且 JSON 不含 advisory;F:py_compile OK、diff/BOM 干净。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (Slice 2b-ii-B weekly semantic panel partial-write)
- **Verdict/Action**: FAIL。代码/文档守护主体通过,但 `main --semantic-risk-summary` 的无效输入会在失败前留下已写出的 weekly JSON partial artifact。
- **Required**: `R-ASHORT-SEMANTIC-PANEL-MAIN-PARTIAL-WRITE-ON-INVALID-SUMMARY` — 完整 Required/风险/边界/closure 见 `docs/system_risk_register.md`(单一来源,本处不复述)。
- **Verify**: doc-governance+route 23 OK; semantic-risk weekly/contract/summary 120 OK; py_compile OK; custom invalid-summary main probe reproduced `ValidationError` with `weekly.json` existing and md absent; `git diff --check` clean。
- **Next**: Claude `修复`。

## 2026-06-13 — Claude `修复` (协议双写守护 — 子集→精确集合 + 长度上界,一次钉死)
- **Verdict/Action**: 用户指示主动加固:守护从子集 allowlist 升级为**精确标签集**(标签集合须恰好 = base,缺/多/重复均 FAIL)+ **每 bullet ≤500 字符**(防把 register 全文塞进一条 allowed bullet);同时确认用户新增的 Codex 一次过 defect-class 矩阵规则已 pin 入 AGENTS(test 已过)。
- **Required**: `R-DOCGOV-MINIMAL-ENTRY-GUARD-NONSTRUCTURAL-FALSE-NEGATIVE`(及 PASS-header/placeholder 同族)— 完整详情见 `docs/system_risk_register.md`(单一来源,本处不复述)。
- **Verify**: 植入扩到 9 例(+crammed-bullet/missing-label/duplicate-label)均 FAIL,合规极简 PASS;现有 5 条 compliant entry 仍过精确集合;`python -m unittest tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency` = 23 OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A 不再补单形态,改"恰好集合 + 长度 + 重复"覆盖剩余 entry 变体维度;B helper 单一来源 live+planted 共用;C 反向:9 植入 + 1 pass + 现存 5 entry 全验;D 走精确集合非禁词。
- **Next**: `审查`。

## 2026-06-13 — Claude `修复` (协议双写守护 — 覆盖 PASS-only header + 禁 Verify 占位符)
- **Verdict/Action**: review-cycle 触发词补 `PASS`/`Pass`/`FAIL`(纯 `Codex PASS (R-ID)` header 不再被跳过);Verify bullet 禁 placeholder(`N OK`/`<N>`/`TODO`/`TBD`/`XXX` 等);并把上两轮 entry 的占位结果填实为 22 OK。
- **Required**: `R-DOCGOV-MINIMAL-GUARD-PASS-HEADER-GAP` · `R-DOCGOV-SESSIONLOG-VERIFY-PLACEHOLDER` — 完整详情见 `docs/system_risk_register.md`(单一来源,本处不复述)。
- **Verify**: 六植入均 FAIL(同日缺指针 / 中文复述 / Finding-1 段 / 修复缺 proof / PASS-header 带额外段 / Verify-ph),合规极简 PASS;`python -m unittest tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency` = 23 OK;四套合计 87 OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A 整类:把"PASS-only header 漏检"与"verify 占位"并入结构化守护并各加植入;B helper 单一来源 live+planted 共用;C 反向:placeholder 守护当场抓出我自己两条占位结果(已填实);D allowlist 不靠禁词;E 规则进 AGENTS/协议 doc 单态。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (协议双写守护 — PASS header gap + verify placeholder)
- **Verdict/Action**: FAIL。结构化 allowlist 已修好上一轮主体问题,但 PASS-only header 可跳过 guard,且最新修复 entry 的验证结果仍有 `N OK` 占位符。
- **Required**: `R-DOCGOV-MINIMAL-GUARD-PASS-HEADER-GAP`;`R-DOCGOV-SESSIONLOG-VERIFY-PLACEHOLDER` — 完整详情见 `docs/system_risk_register.md`(单一来源,本处不复述)。
- **Verify**: 反向探针确认 `Codex PASS (R-ID)` 带额外问题段会被当前 helper 跳过;现有治理测试 22 OK;语义风险相关测试 120 OK;`git diff --check` clean(LF→CRLF warnings only)。
- **Next**: Claude `修复`。

## 2026-06-13 — Claude `修复` (协议双写守护 — 改结构化 allowlist enforcement)
- **Verdict/Action**: token 黑名单(whack-a-mole,换中文/换标题即绕过)→**结构化 allowlist**:compliant-zone 评审 entry 正文只允许固定标签 bullet(Verdict/Action·Required·Verify·Next·修复加 Pre-Codex self-review),任何自由段落/额外 finding·risk·repair·boundary 段一律 FAIL;`修复` 轮强制带 proof 行。
- **Required**: `R-DOCGOV-MINIMAL-ENTRY-GUARD-NONSTRUCTURAL-FALSE-NEGATIVE` — 完整详情见 `docs/system_risk_register.md`(单一来源,本处不复述)。
- **Verify**: 四植入(同日缺指针 / 中文复述段 / Finding-1 段 / 修复缺 proof)均 FAIL,合规极简 PASS;`python -m unittest tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency` = 23 OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A 改整类结构化(白名单标签+禁自由段+强制 proof),非再补 token;B helper 单一来源 live-guard 与 planted 共用;C 反向四植入+一 pass 已验;D 正解"换措辞绕过"=走 allowlist 不走 blacklist 关键词。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (协议双写守护 — minimal-template guard still non-structural)
- **Verdict/Action**: FAIL。上一轮两个点名漏洞已修到位,但守护仍不是结构化 minimal-template enforcement,换中文/问题段写法仍可双写。
- **Required**: `R-DOCGOV-MINIMAL-ENTRY-GUARD-NONSTRUCTURAL-FALSE-NEGATIVE` — 完整详情见 `docs/system_risk_register.md`(单一来源,本处不复述)。
- **Verify**: 植入样例确认同日缺指针与英文边界样例会被抓;中文复述、英文问题段复述、修复 entry 缺 proof-of-use 仍通过;治理测试 22 OK;语义风险相关测试 120 OK;`git diff --check` clean(LF→CRLF warnings only)。
- **Next**: Claude `修复`。

## 2026-06-13 — Claude `修复` (协议双写守护 — marker-gate + no-double-write + 闭 first-review 漏洞)
- **Verdict/Action**: 守护从 date-gate 改 **marker-gate**(同日即生效,消除 adoption 当天盲区);加 **no-double-write** 结构检查(禁 register 专属段抄入 SESSION_LOG);`AI_REVIEW_PROTOCOL.md` 删除 first-review 例外,首次 FAIL 也走极简模板。
- **Required**: `R-DOCGOV-MINIMAL-ENTRY-GUARD-FALSE-NEGATIVES` · `R-DOCGOV-AI-REVIEW-FIRST-REVIEW-DOUBLEWRITE-LOOPHOLE` — 完整详情见 `docs/system_risk_register.md`(单一来源,本处不复述)。
- **Verify**: 三植入(同日缺指针 / 带指针仍复述 / 合规极简)分别 FAIL·FAIL·PASS;`python -m unittest tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency` = 23 OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A 整类:同日/未来/带指针复述三形态各一植入;B 单一来源:offender 逻辑做成 `_review_cycle_offenders` helper,live guard 与 planted 测试共用(本修复自身不双写);C 反向:三植入已验;D:双写检测走"禁 register 专属段"最窄安全侧;E:规则进 AGENTS + 协议 doc 单态。
- **Next**: `审查`。

<!-- REVIEW-CYCLE-MINIMAL-TEMPLATE-MARKER (adopted 2026-06-13): 新评审循环 entry(审查/修复/PASS)一律 prepend 到本行之上,遵循 AGENTS §Session log discipline → 评审循环 entry 极简模板(最小:Verdict/Action · Required→register 指针 · Verify · Next · 修复加一行 Proof-of-use);完整 finding 详情只进 system_risk_register.md。本行之下为 adoption 前历史,grandfather。勿删勿移。 -->

## 2026-06-13 — Codex `审查 FAIL` (协议修订:交接双写消除 + 单一来源原则落地)

- **Verdict/Action**: FAIL。设计方向正确(保留 register 详情、SESSION_LOG 极简指针),但当前守护和协议文本仍不足以保证"双写不复发"。
- **Required**: `R-DOCGOV-MINIMAL-ENTRY-GUARD-FALSE-NEGATIVES`;`R-DOCGOV-AI-REVIEW-FIRST-REVIEW-DOUBLEWRITE-LOOPHOLE` — 完整 Required/风险/边界/closure 见 `docs/system_risk_register.md`(单一来源,本处不复述)。
- **Verify**: 反向探针确认 same-day missing pointer 与 future duplicate-with-pointer 均被当前 guard 放过; `python -m unittest tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency -v` = 20 OK; `python -m unittest tests.test_a_short_weekly_pipeline tests.test_a_short_semantic_risk_contract_docs tests.test_a_short_semantic_risk_summary -v` = 120 OK; `git diff --check` clean(LF→CRLF warnings only)。
- **Next**: Claude `修复`。

---

## 2026-06-13 — Claude `起草` (协议修订:交接双写消除 + 单一来源原则落地)

**动机**:用户(+Codex)指出反复多轮返工的一个根=交接协议**双写**——同一份修复详情在 `system_risk_register.md` 与 `SESSION_LOG.md` 各写一遍,其一漂移即返工。采纳 Codex 修正:不砍 advisory-only 等**有意**安全复述;只改双写;proof-of-use **压成一行但保留**(砍掉会退回每轮漏面);目标改为"同类必被 guard/单一来源挡住,新类别一次性沉淀成规则/测试,不靠人记"(不说"永不再现")。

**改动(docs/test 协议层,无 runtime)**:
- `AGENTS.md` §System risk register discipline:register = material finding 详情**单一来源**;SESSION_LOG 评审循环 entry 只放最小事实 + 指向 R-ID,不复述。
- `AGENTS.md` §Claude implementer standard item7 **B2 泛化**:从"contract-anchor"升级为通用"一个会变事实=一个权威位置+一个**局部**守护(非整文件)+planted-failure 证局部性";权威位置按性质选(代码→docstring / 契约→anchor / finding→register / live-state→SESSION_LOG 顶)。
- `AGENTS.md` §Session log discipline:新增 **评审循环 entry 极简模板**(verdict/Required-ID 指针/verify/next;修复轮必带一行 proof-of-use),与七节 session 格式分流。
- `docs/AI_REVIEW_PROTOCOL.md` §Review Recording:指向上述模板 + register 单一来源(仍 AGENTS 为准)。
- `tests/test_doc_governance_guard.py`:+2 守护——(a) pin AGENTS 三条新规不被删;(b) **双写守护**:adoption(2026-06-13)之后的 审查/修复 entry 若引用 R-ID 必须含 register 指针(date-gated 不churn 今日历史)。

**Pre-Codex self-review: A-F checked** — A:协议三处(register/implementer/session-log)+ 协议指针 doc 一次覆盖;B:grep 确认 AI_REVIEW_PROTOCOL 仍 defer AGENTS、无第二份角色表;C 反向:已验证双写守护对"未来引用 R-ID 却无 register 指针"FAIL、对合规指针 PASS;D:双写检测走"引用 R-ID 必须指 register"的最窄安全侧,不穷举措辞;E:协议规则进 AGENTS(durable 单态),本 entry 只交接;F:31 tests OK、`git diff --check` clean、BOM/FFFD 见下。**本 entry 本身即按新极简精神写(详情在 AGENTS,不在此复述)。**

**Boundary**:仅协议文档 + 治理测试;无 business runtime/EGS/Phase5/scoring 改动;不动 advisory-only 等有意安全复述;V14.2 frozen。独立 scope,与待审的面板门修复分开 commit。

**Next**: `审查`(复审协议三改 + 双写守护的 date-gating/反向有效性 + 是否与现有 route-doc v3 一致)。

---

## 2026-06-13 — Claude `修复` (Slice 2b-ii-B — 单一来源收敛 + 守护改局部)

**两件事一轮做完**:(1) 回应用户"这么多面描述同一条落地路径有必要吗"——**没必要**;(2) Codex 新 FAIL `R-ASHORT-SEMANTIC-PANEL-GUARD-FILE-LEVEL-FALSE-NEGATIVE` 成立(我上轮"位置无关"守护是**整文件**粒度,Codex 不动工作树就复现:往 README 追加一句 stale,因别处已有 `schema+consistency` 而照过)。

**根本认识**:历轮守护一直**逼每个面重复 `schema+consistency`**——等于把"同一道门"复制成 5 份,正是反复漂的根。

**修复 A(单一来源收敛)**:门步骤只留 1 处 = `_semantic_panel_from_summary` docstring(被 `test_panel_rejects_*` 钉住);CLI help / README 行 / coverage §2b-ii-B / skill-prompt How-it-lands 全收成**纯指针**(点名函数 +「步骤见 docstring」),没有可漂的复述。

**修复 B(守护改局部)**:重建守护按**块**(markdown 表行 / 空行段落)校验,非整文件——块算 consumer 落地当且仅当:含 consumer 符号(`_semantic_panel_from_summary`/`--semantic-risk-summary`),**或**呈现漂移形状(`render_semantic_risk_panel` 与 `validate_summary_consistency` 同块,即 Codex 植入的绕过形)。此类块必须 route 到 `_semantic_panel_from_summary` 且无 stale。新增 `test_panel_gate_guard_is_local_planted_failure` 复刻 Codex 的植入复现并断言**必 FAIL**。

**Pre-Codex self-review: A-F checked** — A:不再补单面,改 single-source + 局部守护治整类;**B 连带——局部守护当场抓到我没想到的真面**:README 2b-i 行的 `render_semantic_risk_panel` 是渲染器名(非 consumer 落地),据此把判定从"含 render_* token"收窄为"consumer 符号 OR render_*+consistency 同块"(checklist D 歧义→走最窄安全侧,不穷举关键词);C 反向:planted 测试证局部有效、全套绿证无误报;F:138 OK、`git diff --check` clean、BOM/FFFD=0。

**Boundary**: 仅 docs/test/docstring/CLI-help;无 runtime/EGS/Phase5/scoring/hard-veto/live-web/分类 prompt 改动;面板仍只进 .md;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审单一来源收敛 + 局部守护的 planted-failure 有效性 + 无误报)。

---

## 2026-06-13 — Codex `审查` FAIL (Slice 2b-ii-B — location-independent guard has file-level false negative)

**Scope**: re-reviewed Claude's repair for `R-ASHORT-SEMANTIC-PANEL-SCHEMA-GATE-PROMPT-SURFACE-DRIFT`, including the prompt landing text and the claimed location-independent anti-recurrence guard. Covered `skills/a_short_analysis/prompts/semantic_risk_web_llm.md`, `tests/test_a_short_semantic_risk_contract_docs.py`, `runners/a_short_weekly_pipeline.py`, `docs/README.md`, `docs/a_short_semantic_risk_coverage.md`, `docs/system_risk_register.md`, and `docs/SESSION_LOG.md`.

**Verdict**: FAIL. The concrete prompt wording is now correct, and the CLI/user-facing help remains correct. The new guard is directionally right because it tries to scan active docs/prompts instead of naming only one file. However it is not actually strong enough to support the "彻底杜绝类似问题再次发生" requirement.

**Finding-1 (P3, required, `R-ASHORT-SEMANTIC-PANEL-GUARD-FILE-LEVEL-FALSE-NEGATIVE`)**: `tests/test_a_short_semantic_risk_contract_docs.py::test_no_active_teaching_surface_drifts_panel_gate` checks the whole file for `schema+consistency` when any landing token appears anywhere in that file. That creates a false negative: if a future stale panel-landing sentence is added to `docs/README.md` or another already-covered file, the test still passes as long as the same file contains `schema+consistency` somewhere else. Independent probe reproduced this exact class without touching the working tree: appending `Future stale panel landing: render_semantic_risk_panel is appended after validate_summary_consistency; no schema gate mentioned here.` to the current `docs/README.md` still passes the guard's logic (`file_level_guard_false_negative_for_planted_stale_readme_line=True`) because README already contains `schema+consistency` elsewhere and the stale sentence avoids the three exact banned strings. Required repair: make the guard local to each active landing mention/region, not whole-file. Acceptable shapes include line/paragraph/window-based checks around each landing token, or extracting route-table cells / prompt sections / argparse help blocks and requiring the schema gate in the same local region. Add a planted-failure assertion for a stale paragraph in a file that already contains a valid `schema+consistency` elsewhere, so this false-negative class is closed. Keep the repair test-only or docs/test-only; do not change runtime behavior, EGS, Phase5, scoring, hard veto, live web execution, or category prompts.

**Clean / verified**:
- Prompt landing wording now routes through `--semantic-risk-summary` -> `_semantic_panel_from_summary` and states the full schema+consistency gate before markdown-only append.
- Actual module help: `python -m runners.a_short_weekly_pipeline --help` shows `schema+consistency` and `JSON Schema 在先`.
- Tests: `python -m unittest tests.test_a_short_weekly_pipeline tests.test_a_short_semantic_risk_contract_docs tests.test_a_short_semantic_risk_summary tests.test_route_doc_ledger_status_consistency -v` = 135 OK.
- `git diff --check` exits 0 (LF->CRLF warnings only).

**Boundary**: strengthen the guard's locality and add the planted false-negative case. Do not broaden into production/runtime behavior.

**Next**: Claude `修复`.

---

## 2026-06-13 — Claude `修复` (Slice 2b-ii-B — panel-gate drift 终结:位置无关守护)

**Finding-1 (P3, `R-ASHORT-SEMANTIC-PANEL-SCHEMA-GATE-PROMPT-SURFACE-DRIFT`)成立**:skill prompt 的「How it lands」仍把落地描述成"apply_web_llm_patch 跑 validate_summary_consistency → panel append",漏 weekly consumer 的 schema+consistency 门。

**老实说为什么又是新面**:上轮我把 skills:48 主观判成"patch-apply 路径无关"**直接 dismiss**——这是**判断错误**(它的 How it lands 继续描述了到 weekly markdown 的落地),不是 grep 盲区。这已是同一类第 4 次以新面现形(P2 bypass→doc-drift→help-drift→prompt-surface)。结论:靠"我每轮穷尽发现所有面"不可靠,必须让守护**不依赖我的面枚举**。

**终结性修复**:(1) prompt「How it lands」改为两步,weekly 落地显式走 `--semantic-risk-summary → _semantic_panel_from_summary` 的 schema+consistency 门再 append。(2) 新增**位置无关**守护 `test_no_active_teaching_surface_drifts_panel_gate`:扫**所有** `docs/*.md` + 所有 `skills/**/*.md` prompt + pipeline 模块,凡提到落地符号(`_semantic_panel_from_summary`/`--semantic-risk-summary`/`render_semantic_risk_panel`)的面**必须**含 schema 半且无旧措辞——**任何未来新文档/prompt 自动纳入,不再靠我逐面发现**。排除 append-only 历史(SESSION_LOG/archive/register findings)与定义 renderer 的实现模块。

**Pre-Codex self-review: A-F checked** — A:不再补单面,改成类级位置无关守护;B 穷尽 grep 落地符号确认活面=coverage/README/prompt/pipeline 四处(summary.py 是 renderer 定义、非落地描述,故排除),全已含 schema 半;C 反向:已验证守护对 regressed 面 FAIL、且 sweep 内置 sanity 断言确实触达四面;**F 自catch 一个真 bug**:守护初版排除逻辑只写在 docstring 没落代码,扫到 SESSION_LOG 历史里 Codex 引用的旧措辞→FAIL,已补 HISTORY 实际排除后 139 OK;`git diff --check` clean、BOM/FFFD=0。

**Boundary**: 仅 prompt 措辞 + 守护;无 runtime/EGS/Phase5/scoring/hard-veto/live-web/分类 prompt 改动;面板仍只进 .md;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审 prompt 落地 + 位置无关守护的穷尽性/反向有效性)。

---

## 2026-06-13 — Codex `审查` FAIL (Slice 2b-ii-B — anti-recurrence guard still misses skill-prompt landing surface)

**Scope**: re-reviewed Claude's repair for `R-ASHORT-SEMANTIC-PANEL-SCHEMA-GATE-HELP-DRIFT` with the explicit user requirement that the fix must prevent the same contract-surface drift from recurring, not only repair the previously named CLI help string. Covered `runners/a_short_weekly_pipeline.py`, `runners/a_short_m67_render.py`, `skills/a_short_analysis/prompts/semantic_risk_web_llm.md`, `docs/README.md`, `docs/a_short_semantic_risk_coverage.md`, `tests/test_a_short_weekly_pipeline.py`, `tests/test_a_short_semantic_risk_contract_docs.py`, `docs/system_risk_register.md`, and `docs/SESSION_LOG.md`.

**Verdict**: FAIL. The specific prior blocker is repaired: `--semantic-risk-summary` help now states the same `schema+consistency` gate as `write_summary`, and the new narrow test covers that help block. However, the anti-recurrence coverage is still not complete for the active Slice 2b-ii-B contract surfaces.

**Finding-1 (P3, required, `R-ASHORT-SEMANTIC-PANEL-SCHEMA-GATE-PROMPT-SURFACE-DRIFT`)**: `skills/a_short_analysis/prompts/semantic_risk_web_llm.md` has an active **How it lands** section that says the patch is applied by `apply_web_llm_patch`, which re-runs `validate_summary_consistency`, and then the merged summary's advisory panel is appended to weekly M6.7 markdown. This is another live contract-facing surface for the same landing path, but it omits the weekly consumer boundary now required after the prior P2/P3 loop: `--semantic-risk-summary` -> `_semantic_panel_from_summary` -> full JSON Schema + consistency gate -> `render_semantic_risk_panel` -> markdown-only append. The current drift guards check README/coverage and CLI help, but not this prompt surface, so a future maintainer/LLM can still learn the old "consistency-only then append" mental model from the skill prompt while every current test stays green. Required repair: update the prompt's **How it lands** wording to route final weekly consumption through `_semantic_panel_from_summary` / `--semantic-risk-summary` and state the full schema+consistency consumer gate before markdown append; extend the doc-drift guard to include this prompt landing block (or a narrow active-surface scan for current `render_semantic_risk_panel` / weekly-panel landing text) so the stale `apply_web_llm_patch` + `validate_summary_consistency`-only landing description cannot reappear. Keep the repair docs/test-only; do not change runtime behavior, EGS, Phase5, scoring, hard veto, live web execution, or the six category prompts.

**Clean / verified**:
- Previous CLI-help blocker is repaired in code and actual module help: `python -m runners.a_short_weekly_pipeline --help` shows `schema+consistency` and `JSON Schema 在先`.
- Tests: `python -m unittest tests.test_a_short_weekly_pipeline tests.test_a_short_semantic_risk_contract_docs tests.test_a_short_semantic_risk_summary tests.test_route_doc_ledger_status_consistency -v` = 134 OK.
- `git diff --check` exits 0 (LF->CRLF warnings only).
- Touched/new files are UTF-8, BOM=false, U+FFFD=false, trailing whitespace=0.

**Boundary**: prompt landing wording + narrow doc-drift guard only. Do not broaden into runtime/production behavior.

**Next**: Claude `修复`.

---

## 2026-06-13 — Claude `修复` (Slice 2b-ii-B — gate doc-drift 残留:CLI help 面)

**Finding-1 (P3, `R-ASHORT-SEMANTIC-PANEL-SCHEMA-GATE-HELP-DRIFT`)成立且公允**:上轮我声称"anchor 整类",但 `--semantic-risk-summary` 的 argparse help 仍写「as_of 须与周报一致且过一致性校验」,少 schema 半;类级守护也只扫 README/coverage,没扫 CLI help。

**为什么又漏一个面(老实说):** 上轮 ripple-grep 用的 token 是符号 `validate_summary_consistency`,而 help 是**中文转述**「过一致性校验」——同一类遗漏正好落在我 grep 的盲区里。教训:连带 grep 必须覆盖**转述/paraphrase**,不能只搜符号名。

**修复:** (1) help 改为 anchor 措辞「过与 write_summary 同款 schema+consistency 门(JSON Schema 在先,再 as_of 与周报一致),详见 docstring」。(2) 新增窄守护 `test_pipeline_cli_help_states_schema_gate_not_consistency_only`:扫 `--semantic-risk-summary` add_argument 区,要求 schema 半、且**同时禁**符号形式与中文转述「as_of 须与周报一致且过一致性校验」(把我漏掉的那个 token 钉死)。

**Pre-Codex self-review: A-F checked** — A:help 面按类补;B 连带:这次 grep **穷尽 token**(中英 + 转述「一致性校验」/「过一致性」),确认门描述面仅 docstring/help/coverage/README,register P2 finding 文本与 SESSION_LOG 是历史记录不改写,skills:48 是 patch-apply 路径无关;C 反向:已验证新守护在 regressed help 下 FAIL、现 help PASS;F:138 tests OK、`git diff --check` clean、BOM/FFFD=0。

**Boundary**: 仅 CLI help + 窄 doc-drift 测试;无 runtime/EGS/Phase5/scoring/hard-veto/live-web/prompt 改动;面板仍只进 .md;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审 help anchor 化 + 窄守护;穷尽性确认)。

---

## 2026-06-13 — Codex `审查` FAIL (Slice 2b-ii-B — schema-gate doc drift residual in CLI help)

**Scope**: re-reviewed Claude's repair for `R-ASHORT-SEMANTIC-PANEL-SCHEMA-GATE-DOC-DRIFT`, including the schema-gate code path, durable route docs, new drift guard, and option help. Covered `runners/a_short_weekly_pipeline.py`, `docs/README.md`, `docs/a_short_semantic_risk_coverage.md`, `tests/test_a_short_semantic_risk_contract_docs.py`, `tests/test_a_short_weekly_pipeline.py`, `docs/system_risk_register.md`, and `docs/SESSION_LOG.md`.

**Verdict**: FAIL. The previous route/coverage/docstring drift is mostly fixed and the schema bypass remains closed, but the repair did not cover one of its own required surfaces: the CLI help for `--semantic-risk-summary`.

**Finding-1 (P3, required, `R-ASHORT-SEMANTIC-PANEL-SCHEMA-GATE-HELP-DRIFT`)**: `runners/a_short_weekly_pipeline.py` still defines the `--semantic-risk-summary` help as `as_of 须与周报一致且过一致性校验`, omitting the JSON Schema half of the consumer gate. The latest register entry for `R-ASHORT-SEMANTIC-PANEL-SCHEMA-GATE-DOC-DRIFT` explicitly required route/docs/docstring/**help** surfaces to say schema+consistency, but the repair updated only docstring/README/coverage/register. The new class-level guard also covers only `docs/a_short_semantic_risk_coverage.md` and `docs/README.md`, so the CLI help can regress back to the exact omission class without a test failure. Required repair: update the `--semantic-risk-summary` help to state the schema+consistency gate (or point to the docstring/`write_summary` same-gate wording), and extend the drift guard to inspect `runners/a_short_weekly_pipeline.py` for this option help so the old consistency-only help text cannot reappear. Keep the guard narrow to this option/help surface.

**Clean / verified**:
- Counterexample replay: `schema_version="0.9.0"`, `boundary.hard_veto=true`, `boundary.production=true`, and top-level `decision="hard_veto"` are all rejected by `jsonschema.ValidationError`.
- Tests: `python -m unittest tests.test_a_short_weekly_pipeline tests.test_a_short_semantic_risk_contract_docs tests.test_a_short_semantic_risk_summary tests.test_route_doc_ledger_status_consistency -v` = 133 OK.
- `git diff --check` exits 0 (LF→CRLF warnings only).
- Touched/new files are UTF-8, BOM=false, U+FFFD=false, trailing whitespace=0.

**Boundary**: CLI help text + doc-drift test only. Do not change runtime behavior, EGS, Phase5 decisions, scoring, hard veto, live web execution, or prompt content.

**Next**: Claude `修复`.

---

## 2026-06-13 — Claude `修复` (Slice 2b-ii-B — gate doc-drift 根治,非再补实例)

**Finding-1 (P3, `R-ASHORT-SEMANTIC-PANEL-SCHEMA-GATE-DOC-DRIFT`)成立**:上轮把 `_semantic_panel_from_summary` 代码门改成 schema+consistency,但 docstring + README 行 + coverage §2b-ii-B 仍写旧门(只 schema_name/as_of/consistency)。

**根因(回答用户"为什么一直漂移、修了好多轮"):** 这一类是**遗漏式漂移**——新增一步不改任何旧符号,checklist B 的"grep 旧符号"抓不住"那句枚举少列了一项";且同一道门被在 docstring/coverage/README **各自独立枚举**(我早把 B2 contract-anchor 用在了 web_llm 矩阵,却漏用在"消费校验门"描述上)。所以历轮"针对性补一句/补一个测试"本身就是病灶(打地鼠)。

**根治(非 per-instance):** 套用已有 anchor 纪律——门只在 `_semantic_panel_from_summary` docstring **唯一权威枚举**(改为 JSON-Schema-first + as_of + consistency);README/coverage/register in_progress 条目都改成"指向 = 与 `write_summary` 同款 schema+consistency 门",不再各自枚举步骤。新增**类级**守护 `test_panel_consumer_gate_docs_state_schema_not_consistency_only`:任何耐久面描述该 consumer 必须含 schema 半、且禁止旧的 consistency-only 枚举。

**Pre-Codex self-review: A-F checked** — A:按"门描述漂移"整类修(docstring+README+coverage+register 四面一次覆盖),非只 Codex 点名的三处;B 连带 grep:`schema_name + as_of + consistency` 全局搜,连 register line 40 旧句一并改(SESSION_LOG 历史 entry 是事实记录、不改写);C 反向失败:已验证守护在 regressed 措辞下会 FAIL、在现文档 PASS(非空操作);F:137 tests OK、`git diff --check` clean、BOM/FFFD=0。

**Boundary**: 仅 docs/test/docstring 同步;不扩 EGS/Phase5/scoring/hard-veto/live-web;面板仍只进 .md;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审 anchor 化 + 类级守护)。

---

## 2026-06-13 — Codex `审查` FAIL (Slice 2b-ii-B — schema fix works but route/docs still teach old gate)

**Scope**: re-reviewed Claude's repair for `R-ASHORT-SEMANTIC-PANEL-SUMMARY-SCHEMA-BYPASS` plus the full Slice 2b-ii-B surface. Covered `runners/a_short_weekly_pipeline.py`, `runners/a_short_m67_render.py`, `tests/test_a_short_weekly_pipeline.py`, `tests/test_a_short_semantic_risk_contract_docs.py`, `skills/a_short_analysis/prompts/semantic_risk_web_llm.md`, `docs/a_short_semantic_risk_coverage.md`, `docs/README.md`, `docs/system_risk_register.md`, and `docs/SESSION_LOG.md`.

**Verdict**: FAIL. The code-level schema bypass is fixed: the previous four counterexamples (`schema_version="0.9.0"`, `boundary.hard_veto=true`, `boundary.production=true`, top-level `decision="hard_veto"`) are now rejected by JSON Schema. However, the durable route/docs and the function docstring still describe the old weaker consumer gate, so the exact contract that was just repaired is not synchronized.

**Finding-1 (P3, required, `R-ASHORT-SEMANTIC-PANEL-SCHEMA-GATE-DOC-DRIFT`)**: `docs/README.md` Slice 2b-ii-B row, `docs/a_short_semantic_risk_coverage.md` §2b-ii-B panel wiring, and `runners/a_short_weekly_pipeline.py::_semantic_panel_from_summary` docstring still say the weekly panel consumer checks `schema_name` / `as_of` / `validate_summary_consistency` (or equivalent). They omit the repaired required gate: **full JSON Schema validation of `a_short_semantic_risk_summary` plus consistency validation**. This is not just wording polish: the immediately preceding FAIL was caused by treating `validate_summary_consistency` as sufficient, while `schema_version`, top-level boundary consts, and `additionalProperties:false` live in the JSON Schema. Leaving the old route text/docstring makes the next maintainer likely to remove or bypass the schema half while believing they are following the documented contract. Required repair: update those route/docs/docstring/help surfaces to say `_semantic_panel_from_summary` enforces schema+consistency (JSON Schema first, then as_of/consistency), and add/extend a doc-drift test so the Slice 2b-ii-B route/coverage text cannot regress to the old "schema_name + as_of + consistency only" wording.

**Clean / verified**:
- Counterexample replay: all four prior mutated summaries are rejected by `jsonschema.ValidationError`.
- Tests: `python -m unittest tests.test_a_short_weekly_pipeline tests.test_a_short_semantic_risk_contract_docs tests.test_a_short_semantic_risk_summary -v` = 118 OK.
- Route-doc guard: `tests.test_route_doc_ledger_status_consistency` = 14 OK.
- `git diff --check` exits 0 (LF→CRLF warnings only).

**Boundary**: docs/test/docstring synchronization only. Do not broaden into EGS, Phase5 decisions, hard veto, scoring, live web execution, or prompt rewrites.

**Next**: Claude `修复`.

---

## 2026-06-13 — Claude `修复` (Slice 2b-ii-B — 面板 consumer 补 JSON Schema 校验)

**Finding-1 (P2) 成立**:`_semantic_panel_from_summary` 只跑 `validate_summary_consistency`,没跑 summary 的 JSON Schema → schema_version 篡改 / boundary.hard_veto=true / production=true / 顶层加 decision 等会漏过(这些靠 schema 的 const + additionalProperties 才拦)。**checklist A 漏格**:consumer 校验门 = schema + consistency 两部分,我只做了 consistency 那半(write_summary 是两部分都做的)。

**Fix(consumer-validation + tests only)**:`_semantic_panel_from_summary` 在 as_of/consistency 前先 `jsonschema.validate(summary, a_short_semantic_risk_summary.schema.json)`(用模块 `SCHEMA_PATH`),与 `write_summary` 同门。回归测试:schema_version 篡改 / boundary hard_veto / boundary production / 顶层多余 decision 字段 → 全 `jsonschema.ValidationError` 拒;正向 + 仅进 .md/不进确定性 JSON 测试仍绿。

**Pre-Codex self-review: A-F checked** — A:把"完整 consumer 校验门 = schema + consistency"作整类补齐,4 个篡改形态各一测;C 反向:加 schema 校验不拒合法 summary(_sem_summary 正向仍过);F:136 tests OK、`git diff --check` clean、BOM/FFFD=0。

**Boundary**: 仅 consumer 校验 + 测试;不扩 EGS/Phase5/scoring/hard-veto/live-web;面板仍只进 .md;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审 consumer schema 校验)。

---

## 2026-06-13 — Codex `审查` FAIL (语义风险 Slice 2b-ii-B — summary consumer lacks schema validation)

**Scope**: reviewed Claude's Slice 2b-ii-B draft for semantic-risk skill prompt + weekly M6.7 markdown panel wiring. Covered `skills/a_short_analysis/prompts/semantic_risk_web_llm.md`, `runners/a_short_weekly_pipeline.py`, `runners/a_short_m67_render.py`, `tests/test_a_short_weekly_pipeline.py`, `tests/test_a_short_semantic_risk_contract_docs.py`, `docs/a_short_semantic_risk_coverage.md`, `docs/README.md`, `docs/system_risk_register.md`, and `docs/SESSION_LOG.md`.

**Verdict**: FAIL. The prompt routing and markdown-only append direction are basically correct, and existing tests pass, but the new `--semantic-risk-summary` consumer does not run the `a_short_semantic_risk_summary` JSON Schema before rendering the advisory panel. That leaves a contract bypass at the exact new boundary being introduced.

**Finding-1 (P2, required, `R-ASHORT-SEMANTIC-PANEL-SUMMARY-SCHEMA-BYPASS`)**: `runners/a_short_weekly_pipeline.py::_semantic_panel_from_summary` checks only `schema_name`, `as_of`, and `validate_summary_consistency(summary)`. It does not validate against `schemas/a_short_semantic_risk_summary.schema.json`. A direct counterexample rendered successfully in the current working tree after mutating a valid summary to `schema_version="0.9.0"`, `boundary.hard_veto=true`, `boundary.production=true`, or adding top-level `decision="hard_veto"`. The schema would reject all of those. This matters because the Slice 2b-ii-B boundary says the semantic layer is advisory-only, never production/hard-veto, and stable-versioned; the weekly consumer must enforce the same schema contract before making the panel visible. Required repair: load and run `jsonschema.validate(summary, a_short_semantic_risk_summary.schema.json)` inside `_semantic_panel_from_summary` before `validate_summary_consistency`, then keep the existing `schema_name/as_of/consistency` checks. Add regression tests proving the panel rejects at least wrong `schema_version`, top-level boundary tamper (`hard_veto` or `production` true), and extra top-level hard-decision fields, while still appending only to `.md` and never to the deterministic weekly JSON.

**Clean / verified**: current tests are green but insufficient: `python -m unittest tests.test_a_short_weekly_pipeline tests.test_a_short_semantic_risk_contract_docs tests.test_a_short_semantic_risk_summary -v` = 115 OK. `git diff --check` exits 0. Touched/new files are UTF-8, BOM=false, U+FFFD=false, trailing whitespace=0.

**Boundary**: fix is consumer-validation + tests only. Do not broaden into production scoring, hard veto, EGS, Phase5 decision changes, or live web execution. Do not rewrite the existing six category prompts.

**Next**: Claude `修复`.

---

## 2026-06-13 — Claude `起草` (语义风险 Slice 2b-ii-B — skill prompt + 周报面板接入)

2b-ii 的 skill-在环 + 可见性半边。语义风险层至此功能完整(Slice 1/2a/2b-i/2b-ii-A/2b-ii-B);剩 Slice 3 deferred(有 tracker+guard)。

**交付物**:
- `skills/a_short_analysis/prompts/semantic_risk_web_llm.md`:编排既有 6 个分类 prompt → 产 `a_short_semantic_risk_web_llm_patch`;路由到稳定契约 + 重申硬规则(advisory-only/绝不硬否决、unknown-not-clear `unknown/unknown/no_action`、非 unknown 须 sources、主板 Top15、LIVE 不可复现)。**复用**6 个现有 prompt,非重写。
- 面板接入:`a_short_weekly_pipeline --semantic-risk-summary` → `_semantic_panel_from_summary`(校验 schema_name + as_of 一致 + `validate_summary_consistency`)→ `render_semantic_risk_panel` **仅追加到周报 .md**(`---` 分隔),**绝不进确定性周报 JSON**;`write_weekly_markdown` 加可选 `semantic_panel`。

**Pre-Codex self-review: A-F checked** — A:面板接入不变式矩阵(valid / as_of-mismatch / schema_name-mismatch / invalid-summary → raise;md startswith 确定性渲染=advisory 纯追加;无 summary 时 md==确定性渲染=不泄漏)+ prompt 漂移锚;B ripple-grep:coverage/README 的"2b-ii-B/面板 deferred"future 措辞已随落地更新(防"已完成却写未来"漂移);C 反向:advisory **绝不进确定性 JSON**(测 md==确定性 when无 panel)、面板渲染前硬校验防伪造;D:web_llm 实质判断本就 skill-在环、不穷举,headless 只做契约+接线;E register/coverage 单态;F:133 tests OK + `git diff --check` clean + BOM/FFFD=0。

**Boundary**: advisory-only;面板只进 .md 不进确定性 JSON;不硬否决/不改 EGS/Phase5/不写 production;V14.2 frozen;egs_main stage3 未碰。weekly pipeline 是 research-lane 非生产。

**Next**: `审查`(审 Slice 2b-ii-B)。

---

## 2026-06-13 — Claude `提交` (文档治理精简 + doc-governance guard → local master)

Codex PASS(entry below)。提交本轮文档治理精简 + 防复发 guard 到本地 master(无 push):
- **SESSION_LOG 归档**:2.68MB/15153 行/891 条 → 60KB/最近 30 条 + 归档指针;861 条逐字移 `docs/archive/session_log/...`(零丢失,assert 过)。
- **handoff 索引合并**:13 条描述搬进 `docs/handoff/README.md`;AGENTS §交接记录 + §文件参考 压成单一指针(去掉第二 mini-index)。
- **AGENTS §Session log discipline → 归档** 新约定 + Entry 格式 pointer-aware 插入规则。
- **`tests/test_doc_governance_guard.py`** 防复发 guard(4 测,#1 section-scoped)。
- register 本轮 5 条 docgov entry(insert-rule / archive-header-count / duplicate-handoff-index / order-drift / pointer-count+EOF / guard-weak / slice)全 flip `resolved`。

**经多轮审查**(全同类 ripple/hygiene):归档零丢失 → pointer/EOF → 反时序 → 3 ripple 残留 → guard 偏弱 → guard section-scoped。**结构性收尾:加了 build-blocking guard,该类漂移以后自动红。**

**Pre-Codex self-review: A-F checked** — register 全 resolved 单态;doc-governance guard 4/4 + route-doc guard 14/14 = 18 OK;`git diff --check` clean;全 changeset BOM/FFFD=0;只提交文档治理 + guard 改动,不 push。

**Next**: 见下方"全项目下一步"。

---

## 2026-06-13 — Codex `审查` PASS (doc-governance guard #1 section-scoped repair)

**Scope**: re-reviewed Claude's repair for `R-DOCGOV-GUARD-ENTRY-FORMAT-SCOPE-WEAK`, plus the previously repaired doc-governance simplification items. Covered `tests/test_doc_governance_guard.py`, `AGENTS.md`, `docs/archive/session_log/session_log_archive_2026-05-25_to_2026-06-12.md`, `docs/handoff/README.md`, `docs/archive/README.md`, `docs/SESSION_LOG.md`, and `docs/system_risk_register.md`.

**Verdict**: PASS. The anti-recurrence guard now tests the actual `AGENTS.md ### Entry 格式` rule region, not the whole file, so it would fail if the entry-format rule loses the archive-pointer insertion exception again.

**Verified**:
- `tests/test_doc_governance_guard.py::test_session_log_entry_rule_teaches_archive_pointer_exception` now extracts `### Entry 格式` with a section regex and asserts, inside that section, `归档指针`, `指针之后`, `无指针`, and absence of the old bare `新 entry 永远 prepend 到文件顶部` rule.
- Prior concrete fixes remain intact: `AGENTS.md §Entry 格式` is pointer-aware; the archive file header uses past-tense non-drifting wording; `AGENTS.md §文件参考` has one pointer to `docs/handoff/README.md` instead of a second handoff mini-index; `docs/handoff/README.md` reaches every `*_handoff.md`.
- Tests: `tests.test_doc_governance_guard` + `tests.test_route_doc_ledger_status_consistency` = 18 OK.
- Hygiene: `git diff --check` OK (LF→CRLF warnings only); touched/new files are UTF-8, BOM=false, U+FFFD=false, trailing whitespace=0.

**Submit note**: during `提交`, flip the doc-governance open Hot Queue entries to `resolved` with this PASS evidence, then commit the reviewed doc/test slice. Do not restore the giant active `SESSION_LOG` and do not delete archive or handoff originals.

**Next**: Claude `提交`.

---

## 2026-06-13 — Claude `修复` (doc-governance guard #1 — 限定到 Entry 格式 section)

**Finding 成立(认同)**:guard #1 v1 在**全文** `assertIn("归档指针")`,但 AGENTS §归档 本就含该词 → 即便 §Entry 格式 规则区丢了"指针之后"插入规则,测试仍绿 = 假防护。

**Fix(只改这一项,保持窄范围)**:`test_session_log_entry_rule_teaches_archive_pointer_exception` 改为先用 `(?ms)^### Entry 格式.*?(?=^#{2,3} |\Z)` 抽取 `### Entry 格式` section,在**该 section 内**断言:(a)`归档指针` (b)`指针之后`(新 entry 在指针后)(c)`无指针`(无指针 fallback)(d)不含旧裸规则 `新 entry 永远 prepend 到文件顶部`。仍不扫 SESSION_LOG 历史正文 / archive entry bodies。

**Pre-Codex self-review: A-F checked** — C(反向):若 §Entry 格式 规则区回退到旧裸规则,section 内会缺 `指针之后`/`无指针` 且含旧规则 → guard 真红(已逻辑核);A:只此一项,未扩成全文 linter;F:doc-governance guard 4/4 + route-doc guard 14/14 = 18 OK、`git diff --check` clean、BOM/FFFD=0。

**Boundary**: 仅改 1 个测试方法;零业务代码/schema/runtime;归档/handoff 原文/大 SESSION_LOG 未动。

**Next**: `审查`(复审 section-scoped guard #1)。

---

## 2026-06-13 — Codex `审查` FAIL (文档治理 guard 复审 — anti-recurrence guard 仍偏弱)

**Scope**: reviewed Claude's doc-governance repair after the full-review FAIL, including the three prior Required fixes and the new anti-recurrence guard. Covered `AGENTS.md`, `docs/archive/session_log/session_log_archive_2026-05-25_to_2026-06-12.md`, `docs/handoff/README.md`, `docs/archive/README.md`, `tests/test_doc_governance_guard.py`, `docs/SESSION_LOG.md`, and `docs/system_risk_register.md`.

**Verdict**: FAIL. The three concrete doc fixes are correct, and the new guard is the right direction, but one guard assertion is too weak to prevent the exact insertion-rule drift from recurring.

**Clean / verified**:
- Prior three findings are fixed in the working tree: `AGENTS.md §Entry 格式` is pointer-aware; the archive file header uses past-tense non-drifting wording; `AGENTS.md §文件参考` now points to `docs/handoff/README.md` instead of maintaining a second handoff mini-index.
- `docs/handoff/README.md` remains the single annotated index and reaches every `*_handoff.md`.
- `tests.test_doc_governance_guard` + `tests.test_route_doc_ledger_status_consistency` = 18 OK.
- `git diff --check` exits 0 (LF→CRLF warnings only). Touched/new files are UTF-8, BOM=false, U+FFFD=false, trailing whitespace=0.

**Finding-1 (P3, guard can pass even if the entry-format rule loses the archive-pointer exception)**: `tests/test_doc_governance_guard.py::test_session_log_entry_rule_teaches_archive_pointer_exception` checks `self.assertIn("归档指针", text)` across the entire `AGENTS.md`, not just `AGENTS.md §Session log discipline → Entry 格式`. Because `AGENTS.md §归档` also contains `归档指针`, the test can still pass if the entry-format rule later loses the pointer-aware insertion instruction, unless it reintroduces the exact old phrase `新 entry 永远 prepend 到文件顶部`. That is too weak for the anti-recurrence purpose: the previous bug was specifically an insertion-rule contract drift. Required repair: make the test extract only the `### Entry 格式` section and assert the section itself contains the archive-pointer exception plus the insertion semantics (`指针之后` / no-pointer fallback or equivalent), and still rejects the old bare H1-prepend rule. Keep the guard narrow; do not scan historical `SESSION_LOG` or archive bodies.

**Register**: recorded as `R-DOCGOV-GUARD-ENTRY-FORMAT-SCOPE-WEAK` in `docs/system_risk_register.md`.

**Boundary**: test/doc-only. Do not undo the archive, do not delete handoff originals, and do not broaden into a full-text style linter.

**Next**: Claude `修复`.

---

## 2026-06-13 — Claude `修复` (文档治理 — 加窄范围 doc-governance guard 防同类复发)

用户转达 Codex 最新审查:3 finding(insert-rule / archive-header-count / duplicate-handoff-index)**上轮已修**(本条之下那条 3-ripple 修复),但要求**"整类防复发"——必须加 guard**,不能只改文案。这正解(同类已反复 5+ 轮,人工审拦不住)。

**新增 `tests/test_doc_governance_guard.py`**(窄范围,只扫当前规则区,**不扫 SESSION_LOG 历史正文 / 归档 entry 正文**,避免误报):
- AGENTS SESSION_LOG entry-format 规则必须含 archive-pointer 插入例外(`归档指针`),且不得保留旧"新 entry 永远 prepend…紧跟 H1"规则;
- `docs/archive/session_log/*.md` 的 **header**(split 到首条 dated entry 前)不得出现漂移活计数("keeps the most recent 30 entries"/"只保留最近 30 条");
- AGENTS 不得有 `^- docs/handoff/…_handoff.md` mini-index 列表项,只留 README 指针;
- (我加的反向项)handoff 索引必须**完整可达**每个 `*_handoff.md`(防单一索引 stale-incomplete)。
4 guard 全过 → 同时**证明 1-3 真修好**。

**Pre-Codex self-review: A-F checked** — A:guard 覆盖三类 finding + 反向完整性,一次到位;B:guard 本身就是 ripple 防线;C:反向项防"索引压缩过头变不全";E register 单态;F:guard 4/4 + route-doc guard 14/14 + `git diff --check` clean + BOM/FFFD=0(含新测试文件)。

**根因结构性解决**:文档治理同类漂移此前靠人工逐轮抓;现有 build-blocking guard,改错当前规则区即红。

**Boundary**: 文档 + 1 个新测试文件,零业务代码/schema/runtime;不还原大 SESSION_LOG、不删归档/handoff 原文。

**Next**: `审查`(复审 guard + 3 修复)。

---

## 2026-06-13 — Claude `修复` (文档治理 — 3 处 consolidation ripple 残留)

三条 P3 都成立,全是 checklist B 的 ripple 漏网(consolidation/archival 没 grep 干净所有同类位置):

- **F1 `R-DOCGOV-SESSIONLOG-INSERT-RULE-CONFLICT`**:AGENTS §Entry 格式 仍教"紧跟 H1 prepend"(正是上轮 order drift 的根因)→ 改为 pointer-aware:归档指针在 H1 后为固定 meta,新 entry 紧跟**指针之后**,无指针则跟 H1。
- **F2 `R-DOCGOV-ARCHIVE-HEADER-COUNT-DRIFT`**:archive 文件 header L3 又写"keeps the most recent 30 entries"漂移计数 → 改过去式创建事实。
- **F3 `R-DOCGOV-AGENTS-DUPLICATE-HANDOFF-INDEX`**:AGENTS §文件参考 还留 12 条 handoff 第二索引(且缺 phase6a)→ 换成单一指针指向 `docs/handoff/README.md`。

**Pre-Codex self-review: A-F checked** — A:consolidation 残留作整类一次清(插入规则 + archive 计数 + 第二索引);**B(本轮重点,补前几轮欠的)**:grep 确认 active docs 无其他漂移 30 计数、AGENTS 无第二 handoff 单列(0)、L407 的"紧跟 H1"是新 pointer-aware 规则非旧文;C:纯措辞/指针,无内容/行为改;E register 单态;F:route-doc guard 14/14 + `git diff --check` clean + BOM/FFFD=0。

**根因反思**:文档治理这几轮反复被点,全是"改了一处契约/索引,没 grep 它在别处的复述/旧教法"——和代码侧 Pattern B 同源。已确认 B(ripple-grep)这次扫全。

**Boundary**: 纯文档措辞/指针,零内容/行为;归档、大 SESSION_LOG、handoff 原文未动。

**Next**: `审查`(复审 3 处 ripple)。

---

## 2026-06-13 — Codex `审查` FAIL (文档治理精简 — 全面复审仍有契约残留)

**Scope**: full adversarial review of the documentation-simplification slice, not limited to the last named repair. Covered `AGENTS.md`, `docs/SESSION_LOG.md`, `docs/archive/session_log/session_log_archive_2026-05-25_to_2026-06-12.md`, `docs/handoff/README.md`, `docs/archive/README.md`, `docs/README.md`, `docs/pre_codex_self_review_checklist.md`, and `docs/system_risk_register.md`.

**Verdict**: FAIL. The archive itself is structurally sound and the previous order/pointer/EOF repairs are materially correct, but three P3 contract/hygiene blockers remain before commit.

**Clean / verified**:
- Archive reachability is intact: old HEAD has 891 dated entries; archive has 861 entries starting from old entry 31; active log has the 30 retained old entries plus 5 new doc-governance entries. The only non-exact old-top30 byte difference is removal of the prior extra EOF blank line, already required by `git diff --check`.
- `docs/handoff/README.md` contains the 13 handoff descriptions moved from `AGENTS.md §交接记录`, and all referenced handoff files exist.
- Encoding/hygiene for touched/new files: UTF-8 decodable, BOM=false, U+FFFD=false, trailing whitespace=0.
- `tests.test_route_doc_ledger_status_consistency` = 14 OK; `git diff --check` exits 0 (LF→CRLF warnings only).

**Finding-1 (P3, archive pointer creates a new insertion rule but `AGENTS.md` still teaches the old rule)**: `AGENTS.md` now says the active log keeps an archive pointer right after the H1 intro, but `AGENTS.md §Session log discipline → Entry 格式` still says new entries are prepended "紧跟 H1 header 之后". That old instruction is exactly what caused the pointer/order drift in the previous round. Required repair: update the entry-format rule to state the stable archive pointer, if present, stays immediately after the H1 intro and new dated entries are inserted immediately after that pointer; if no pointer exists, insert after the H1 intro. Keep entries themselves reverse-chronological.

**Finding-2 (P3, archive file header repeats the exact-count drift in a different place)**: `docs/archive/session_log/session_log_archive_2026-05-25_to_2026-06-12.md` line 3 says the active `docs/SESSION_LOG.md` "keeps the most recent 30 entries". The active file already has 35 entries and will continue accumulating until the next archive. Required repair: rewrite this header in past-tense/non-drifting form: this archive was created after retaining the pre-archive latest 30 active entries, and later active entries accumulate in `docs/SESSION_LOG.md` until the next archive.

**Finding-3 (P3, `AGENTS.md` still contains a second stale handoff mini-index outside `§交接记录`)**: the slice correctly moved the 13 annotated handoff descriptions into `docs/handoff/README.md`, but `AGENTS.md §文件参考` still lists individual `docs/handoff/...` files at lines 578-589. This leaves two handoff indexes in the root entry doc, and the lower one is already incomplete/stale (`2026-05-26_phase6a_kickoff_spec_handoff.md` is missing there while present in `docs/handoff/README.md`). Required repair: replace that lower handoff block with a single pointer to `docs/handoff/README.md` (or otherwise make it clearly non-index and complete). The root doc should not keep a second handoff list after declaring `docs/handoff/README.md` the single annotated index.

**Register**: recorded as `R-DOCGOV-SESSIONLOG-INSERT-RULE-CONFLICT`, `R-DOCGOV-ARCHIVE-HEADER-COUNT-DRIFT`, and `R-DOCGOV-AGENTS-DUPLICATE-HANDOFF-INDEX` in `docs/system_risk_register.md`.

**Boundary**: docs-only. No code/schema/runtime behavior changed in this slice; do not undo the archive, do not restore the giant active log, and do not delete any handoff originals.

**Next**: Claude `修复`.

---

## 2026-06-13 — Claude `修复` (文档治理 — SESSION_LOG entry 反时序 + pointer 归位)

**Finding-1 (P3, 反时序) 成立**:上轮我把 修复 entry 锚在 起草 上,结果落到 Codex FAIL 之下,违反"最新在顶";且两条 Codex review 把 archive pointer 挤到中部。
- Fix:重排活跃顶部为严格反时序——archive pointer 归位到 H1 后(稳定 meta);entry 顺序 = 本修复 → Codex FAIL#2(order)→ 修复(pointer+EOF)→ Codex FAIL#1 → 起草 → 2b-ii-A 提交。**零内容改动(仅块移位)**。

**Pre-Codex self-review: A-F checked** — A:反时序作整类一次修(pointer 归位 + 全部 6/13 文档治理块按时序);C:纯移位无内容改;F:git diff --check clean + route-doc guard 14/14 + BOM/FFFD=0。

**Boundary**: 纯顺序/位置,零内容改动。

**Next**: `审查`(复审反时序)。

---

## 2026-06-13 — Codex `审查` FAIL (文档治理精简 — pointer/EOF fixed, but SESSION_LOG order broken)

**Scope**: re-reviewed Claude's repair for the doc-governance simplification slice, specifically the two prior Required items (`R-DOCGOV-ARCHIVE-POINTER-COUNT-DRIFT`, `R-DOCGOV-SESSIONLOG-BLANK-EOF`) plus the active `SESSION_LOG` handoff order. Covered `docs/SESSION_LOG.md`, `docs/archive/session_log/session_log_archive_2026-05-25_to_2026-06-12.md`, `docs/system_risk_register.md`, `docs/pre_codex_self_review_checklist.md`, `AGENTS.md`, `docs/handoff/README.md`, and `docs/archive/README.md`.

**Verdict**: FAIL. The two named Required items are repaired, but the active `SESSION_LOG` order now violates the repo's reverse-chronological handoff rule.

**Clean / verified**:
- `R-DOCGOV-ARCHIVE-POINTER-COUNT-DRIFT` is fixed: the archive pointer no longer says the file "only keeps latest 30"; it now says this archive retained the pre-archive latest 30 and later entries accumulate until the next archive.
- `R-DOCGOV-SESSIONLOG-BLANK-EOF` is fixed: `git diff --check` exits 0 (CRLF warnings only).
- Zero-loss archive still holds: old HEAD had 891 `SESSION_LOG` entries; the archive has old entries 31..891 exactly; the old top 30 are still present in the active file in exact order; no old entry is missing.
- Handoff index still reaches all 13 handoff files.
- Encoding/hygiene: touched/new files are UTF-8, BOM=false, U+FFFD=false, trailing whitespace=0; route-doc guard = 14 OK.

**Finding-1 (P3, latest repair entry is below the prior FAIL, so top-of-log handoff is stale/misordered)**: `docs/SESSION_LOG.md` entry order is currently:
1. Codex previous FAIL (`文档治理精简 — 归档零丢失通过...`)
2. Claude repair (`归档指针去漂移计数 + EOF 空行`)
3. Claude original draft

This violates the file's own rule: "reverse-chronological，最新 entry 在顶部". It also undermines the startup rule that each LLM reads only the top 1-3 entries, because the first entry still says `FAIL` before the repair it is supposed to precede. Required repair: reorder the active top section so the archive pointer sits in its stable header/pointer location and entries are reverse-chronological. At minimum, the Claude repair entry must be above the prior Codex FAIL; after the next review, top entries should read as latest review verdict -> Claude repair -> prior FAIL -> Claude draft. Do not change the archive content, do not restore the giant log, and do not delete any handoff originals.

**Register**: recorded as `R-DOCGOV-SESSIONLOG-ENTRY-ORDER-DRIFT` in `docs/system_risk_register.md`.

**Boundary**: docs-only ordering/handoff repair. The archive design remains accepted; no code/schema/runtime behavior is involved.

**Next**: Claude `修复`.

---

## 2026-06-13 — Claude `修复` (文档治理 — 归档指针去漂移计数 + EOF 空行)

两条 P3 都成立(Codex 确认归档零丢失、handoff 可达、编码干净):

**Finding-1 (归档指针漂移计数)**:指针写"本文件只保留最近 30 条"——这是会随 entry 累积漂移的活计数(现已 31、加 review 32),正是我自己 route-doc mutable-state 教训。Fix:改为不漂移措辞"本次归档时保留了归档前最新 30 条;之后新增继续累积,过大时再按约定归档"。归档文件名/861 计数是不可变事实,保留。

**Finding-2 (EOF 空行)**:`git diff --check` 报 SESSION_LOG 末尾多一空行。Fix:二进制去尾部多余换行,保留"---"后单个 EOL。**根因:pre-flight 没跑 `git diff --check`**——已把它补进 checklist F。

**Pre-Codex self-review: A-F checked** — A:durable-doc hygiene 整类(漂移计数 + EOF)一并修;并核 register/AGENTS 的"30 条"是过去式动作描述或"~30"近似(非活计数),不漂移;B:`git diff --check` 全 changeset = clean;C:指针改措辞不丢归档引用(文件名+861 保留);F:补 `git diff --check` 进 checklist + BOM/FFFD=0 + route-doc guard 14/14。

**Boundary**: 纯文档 hygiene,零内容/行为;不动归档、不复活大 SESSION_LOG、不删 handoff 原文。

**Next**: `审查`(复审指针措辞 + EOF)。

---

## 2026-06-13 — Codex `审查` FAIL (文档治理精简 — 归档零丢失通过,但提交前文案/EOF hygiene 未过)

**Scope**: reviewed the working-tree doc-governance simplification requested by the user: `docs/SESSION_LOG.md` archival, `docs/archive/session_log/session_log_archive_2026-05-25_to_2026-06-12.md`, `AGENTS.md` handoff/read-path compression, `docs/handoff/README.md` annotated index, `docs/archive/README.md`, and `docs/system_risk_register.md`.

**Verdict**: FAIL. The main design is sound and the history is not lost, but two submit-blocking P3 hygiene/accuracy issues remain.

**Clean / verified**:
- Zero-loss archive check passed at entry-body level: pre-slice HEAD had 891 `SESSION_LOG` entries; current active log has 1 new Claude entry + the old top 30; the archive has the old remaining 861. `current_old30_exact == True`, `archive_rest_exact == True`, and `(current old 30 + archive 861) == old 891` exactly.
- Handoff consolidation preserves reachability: all 13 handoff files exist and are referenced from `docs/handoff/README.md`; `AGENTS.md §交接记录` now points to the annotated index instead of forcing full handoff reading.
- Encoding is clean for touched/new files: UTF-8 decode OK, BOM=false, U+FFFD=false, trailing whitespace=0.
- `tests.test_route_doc_ledger_status_consistency` = 14 OK.

**Finding-1 (P3, active archive pointer uses a precise count that is already false / will drift immediately)**: `docs/SESSION_LOG.md` archive pointer says `本文件只保留最近 30 条`, but the current file already has 31 entries (new Claude draft + old top 30), and after this review entry it will have 32. This does not lose memory, but it violates the user's explicit requirement that the handoff stay accurate while being simplified. Required repair: rewrite the pointer to non-drifting wording such as "活跃文件保留约最近 30 条；本次归档时保留了归档前最新 30 条，之后新增 entry 会继续累积到下次归档". Keep the archive file name/count factual.

**Finding-2 (P3, `git diff --check` fails on SESSION_LOG EOF)**: `git diff --check` reports `docs/SESSION_LOG.md:550: new blank line at EOF.` Required repair: remove the extra final blank line from `docs/SESSION_LOG.md` and rerun `git diff --check`.

**Register**: recorded as `R-DOCGOV-ARCHIVE-POINTER-COUNT-DRIFT` and `R-DOCGOV-SESSIONLOG-BLANK-EOF` in `docs/system_risk_register.md`.

**Boundary**: docs-only. Do not undo the archive, do not restore the giant active `SESSION_LOG`, do not delete handoff originals, and do not change code/schema/runtime behavior.

**Next**: Claude `修复`.

---

## 2026-06-13 — Claude `起草` (文档治理精简 — SESSION_LOG 归档 + handoff 索引合并)

**目标**:降低启动/工作读取负担,**不删任何历史**。按用户修正后的优先级安全顺序执行。

**P1 SESSION_LOG 归档(最大负担:2.68MB/15153 行/891 条)**:保留最近 30 条 + H1 header,更早 861 条(2026-05-25…2026-06-12)逐字移到 `docs/archive/session_log/session_log_archive_2026-05-25_to_2026-06-12.md`,活跃文件现 60KB/533 行 + 归档指针。**零丢失**:迁移脚本写盘前断言 `head+kept+archived==原文`;Python utf-8 写盘(无 BOM)。新归档约定写入 `AGENTS.md §Session log discipline → 归档`。

**P2 handoff 索引合并(先于 P3,防丢信息)**:AGENTS §交接记录 13 条 handoff 的一行描述搬进 `docs/handoff/README.md` Phase Index(单一带注解索引)。

**P3 压缩 AGENTS §交接记录**:"按时间顺序读取以下 handoff"+13 条列表 → "默认不全量读 handoff;按 docs/handoff/README.md 点读",消解与既有"不要全量读"门控的冲突;保留新建 handoff 高门槛规则。`docs/archive/README.md` 记录新 `session_log/` 目录。

**Pre-Codex self-review: A-F checked** — A:归档作整类一次完成(P1/P2/P3 + archive 目录文档 + AGENTS 约定),非只动一处;B ripple-grep:AGENTS 已无编号 handoff 列表(0)、handoff/README 含全部 13 个文件名(0 missing)、guard 不读 SESSION_LOG(已核 14 处引用全在注释);C 反向:归档=移位非删除,断言零丢失,不引入信息损失;E:register 单态;F:6 个 touched 文件 BOM=0/FFFD=0(已含新 checklist F BOM 检查)、route-doc guard 14/14。

**Boundary**: 纯文档治理,零代码/schema/behavior;不删任何 handoff 原文、不丢任何 SESSION_LOG 历史;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审归档零丢失 + handoff 索引 + AGENTS 压缩)。

---

## 2026-06-13 — Claude `提交` (语义风险 Slice 2b-ii-A web_llm enrichment 契约 → local master)

Codex PASS(entry below)。提交 Slice 2b-ii-A(web_llm enrichment 契约的 headless 半)到本地 master(无 push)。一次提交本切片整 pending set(Codex 作为同一集审过):
- 代码:`runners/a_short_semantic_risk_summary.py`(`validate_web_llm_patch` / `apply_web_llm_patch` / 共享 `_web_llm_consistency_error`,evidence 不变式:非 unknown 须 sources、unknown⇒unknown/no_action)+ `schemas/a_short_semantic_risk_web_llm_patch.schema.json` + `tests/test_a_short_semantic_risk_summary.py`。
- 契约/文档:`docs/a_short_semantic_risk_contract.md`(稳定契约锚点)+ `docs/a_short_semantic_risk_coverage.md` + `tests/test_a_short_semantic_risk_contract_docs.py`(B2 drift-guard)+ README 路由 + `AGENTS.md` B2 anchor 规则 + `docs/pre_codex_self_review_checklist.md`(F 补 BOM 检查)。
- register:本切片 5 条 finding(stale-summary / schema-name / clear+tailwind-coverage / 48h / unknown-action(代码+doc)/ enrichment 契约)全 flip `resolved`。

**经多轮审查**:stale summary → schema_name → clear/tailwind 无证据 → unknown 无证据 action → 文档矩阵 de-dup(B2)→ BOM。

**Pre-Codex self-review: A-F checked** — 纯提交;register 全 resolved 单态;route-doc guard 14/14;全 changeset 无 BOM/FFFD=0(已含新 checklist F BOM 检查);advisory-only / V14.2 frozen / egs_main 未碰 / 无 push。

**Next**: 见下方"全项目下一步"。

---

## 2026-06-13 — Codex `审查` PASS (语义风险 Slice 2b-ii-A — BOM repair + contract clean)

**Scope**: re-reviewed the latest Claude BOM repair after the prior Codex FAIL. Covered `docs/SESSION_LOG.md`, `docs/system_risk_register.md`, `docs/pre_codex_self_review_checklist.md`, `AGENTS.md`, `docs/README.md`, `docs/a_short_semantic_risk_contract.md`, `docs/a_short_semantic_risk_coverage.md`, `schemas/a_short_semantic_risk_web_llm_patch.schema.json`, `runners/a_short_semantic_risk_summary.py`, `tests/test_a_short_semantic_risk_summary.py`, and `tests/test_a_short_semantic_risk_contract_docs.py`.

**Verdict**: PASS. The previous BOM blocker is repaired, and no Required findings remain for Slice 2b-ii-A.

**What is clean**:
- Encoding: every changed/new file in this slice decodes as UTF-8, has no UTF-8 BOM prefix, no U+FFFD replacement characters, and no trailing whitespace. `docs/SESSION_LOG.md` and `docs/system_risk_register.md` now both start with `# S`, not `EF BB BF`.
- Process guard: `docs/pre_codex_self_review_checklist.md` now explicitly includes UTF-8-without-BOM checking, so this exact pre-flight blind spot is covered going forward.
- Contract behavior: patch validator rejects `unknown/unknown/downgrade`, `unknown/unknown/manual_review_required`, `unknown/unknown/observe`, empty-source `clear_light`, and empty-source `tailwind`; summary consistency rejects `unknown/unknown/downgrade`; `unknown/unknown/no_action` with empty sources remains accepted.
- Contract anchoring: README / coverage / patch-schema description route web_llm rules to `docs/a_short_semantic_risk_contract.md`; old weak active prose only appears inside `assertNotIn` regression tests.

**Clarification**: Claude's top entry says "零内容/行为改动"; read that as zero business/runtime behavior change. There is one intentional process-doc content change: the checklist now includes the BOM pre-flight check. This is acceptable and not a blocker.

**Verification**: semantic-risk contract/summary/guard/probe suite = 114 OK; route-doc guard = 14 OK; summary/probe/web-patch schema Draft7 meta = 3 OK; `py_compile` OK; `git diff --check` OK (CRLF warnings only); independent web_llm evidence probes all match the contract.

**Register**: no new material risk. Existing semantic-risk Hot Queue items can be flipped to `resolved` as part of `提交` after this PASS is committed.

**Next**: Claude `提交`.

---

## 2026-06-13 — Claude `修复` (Slice 2b-ii-A — 去除 register/SESSION_LOG 的 UTF-8 BOM)

**Finding-1 (P3, BOM churn) 成立**:`docs/system_risk_register.md` 被加了 UTF-8 BOM(`EF BB BF`),durable route/risk 文档不该带 BOM。**根因:我的 pre-flight 只查 U+FFFD、没查 BOM(checklist F 编码盲点);BOM 大概率某次编辑/linter 触碰引入。**

**Fix(修整类不修实例)**:.NET 裸字节读写去 BOM(避免 PowerShell `Out-File -Encoding utf8` 反而写回 BOM),保内容不变。扫**整个 changeset 10 文件**,除 Codex 点的 register 外,**ripple 还抓到 SESSION_LOG.md 也带 BOM**(Codex 没点),一并去除;其余 8 个无 BOM。两文件现以 `# S`(23 20 53)开头。
- **checklist F 补 BOM 检查**(`docs/pre_codex_self_review_checklist.md`):编码项加"UTF-8 无 BOM(查 `EF BB BF` 前缀,不只 U+FFFD)",堵这个 pre-flight 盲点。

**Pre-Codex self-review: A-F checked** — A:BOM 作整类扫全 changeset(非只修 register 一处),多抓 SESSION_LOG;B:扫确认仅这两文件有 BOM;C:裸字节去 3 字节不改内容(78 tests + FFFD=0 验内容完好);F:盲点已补进 checklist。

**Boundary**: 纯编码 hygiene,零内容/行为改动;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审 BOM 去除)。

---

## 2026-06-13 — Codex `审查` FAIL (语义风险 Slice 2b-ii-A — B2 de-duplicate repair, BOM churn)

**Scope**: reviewed the latest Claude B2 de-duplicate repair after the prior Codex PASS. Covered `docs/SESSION_LOG.md` top ordering, `docs/README.md`, `docs/a_short_semantic_risk_contract.md`, `docs/a_short_semantic_risk_coverage.md`, `schemas/a_short_semantic_risk_web_llm_patch.schema.json`, `tests/test_a_short_semantic_risk_contract_docs.py`, `runners/a_short_semantic_risk_summary.py`, `tests/test_a_short_semantic_risk_summary.py`, and `docs/system_risk_register.md`.

**Verdict**: FAIL, but only for a hidden document hygiene blocker. The B2 contract-anchor repair itself is correct: active README / coverage / patch-schema prose now routes to `docs/a_short_semantic_risk_contract.md` instead of restating the old partial web_llm matrix, and regression tests prevent the old weak wording from returning.

**Finding-1 (P3, hidden encoding churn in a route/risk doc)**: `docs/system_risk_register.md` now starts with a UTF-8 BOM (`bytes0 = b'\xef\xbb\xbf#'`), shown in git diff as `+﻿# System Risk Register`. This is unrelated to the semantic-risk logic but should not be committed into a durable route/risk register file. Required repair: rewrite `docs/system_risk_register.md` as UTF-8 without BOM, preserving all current content, then rerun the same checks.

**Clean / verified**:
- Contract behavior probes: patch validator rejects `unknown/unknown/downgrade`, `unknown/unknown/manual_review_required`, `unknown/unknown/observe`, empty-source `clear_light`, and empty-source `tailwind`; summary consistency rejects `unknown/unknown/downgrade`; `unknown/unknown/no_action` with empty sources is accepted.
- Active-doc grep: old weak wording only appears inside `assertNotIn` tests, not in README / coverage / schema description.
- Encoding: new contract/coverage docs are valid UTF-8 without mojibake or U+FFFD; the apparent terminal mojibake was display-layer only.

**Verification**: semantic-risk contract/summary/guard/probe suite = 114 OK; route-doc guard = 14 OK; summary/probe/web-patch schema Draft7 meta = 3 OK; `git diff --check` OK (CRLF warnings only). Text check found FFFD/trailing whitespace = 0 for reviewed files, but BOM = true for `docs/system_risk_register.md`.

**Register**: no new business/system risk registered; this is submit-blocking hygiene on an already-touched durable risk document.

**Next**: Claude `修复` (remove the BOM only, preserve content).

---

## 2026-06-13 — Claude `修复` (Slice 2b-ii-A — 文档矩阵 de-duplicate 到契约锚点,B2)

**Finding-1 (P3, doc drift) 成立**:代码已正确拒 `unknown/unknown/downgrade`,但 active 路由/schema 文档(coverage/README/schema desc)仍复述旧/部分 unknown 不变式、漏 `unknown ⇒ action no_action`,与契约不一致、违反 B2。**根因:我上轮修代码时没做彻底的 checklist B(连带 grep)——改了 helper+测试,却没 grep 所有复述旧 unknown 不变式的文档。**

**Fix(选 B2 强制的 de-duplicate,不是补全措辞)**:
- 契约锚点 `a_short_semantic_risk_contract.md` web_llm 段补全为 `unknown ⇒ risk_level unknown AND action no_action`(原缺 action 半句)。
- coverage §web_llm 矩阵 → 单一来源指针;README Slice-2a 行 + 契约 route 行去掉部分复述 → topic gloss + 指针;patch schema description → 指向契约不列规则。
- drift 测试重写:coverage/README/schema 必须**指向契约且不复述矩阵/旧弱措辞**;保留 `unknown/unknown/no_action` 行为锚 + 契约锚 + 48h。

**Pre-Codex self-review: A-F checked; B2 applied** — A:把"所有复述旧 unknown 不变式的 active 文档"作整类一次清(coverage/README:78/README:76 契约行/schema desc——比 Codex 点的 3 处多抓了 README:76);**B(本轮重点,补上轮欠的)**:`Select-String` 全扫 README/coverage 残留矩阵措辞=0;B2 单一锚点=契约其余指向;C:de-dup 不改行为(代码已锁)无反向;E register 注记单态;F:128 tests OK、patch schema meta OK、FFFD=0、route-doc guard 14/14。

**Boundary**: 纯文档/测试(无 runner 行为改动);advisory-only;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审 B2 de-duplicate)。

---

## 2026-06-13 — Claude `修复` (Slice 2b-ii-A — unknown 态须 action no_action)

**Finding-1 (P2) 成立**:`_web_llm_consistency_error` 的 unknown 分支只校验 risk_level,漏了 action → `unknown/unknown/downgrade`(空 sources)被接受,违反契约(`docs/a_short_semantic_risk_contract.md` line 11-12:无证据时 web 须 `unknown/unknown/no_action`)。同一证据边界类、经 action 字段(我上轮 unknown 分支只覆盖 risk_level 一格、漏 action 格)。
- Fix:helper(summary+patch 共享)unknown 分支加 `action == no_action` 校验。`unknown/unknown/no_action` 空 sources 仍放行。
- 回归(两侧,Codex 要求):patch validator(contract-docs `test_behavior_anchor_unknown_requires_no_action`)+ summary consistency(`test_web_unknown_with_soft_action_raises`)+ 契约 drift-guard 锚定 unknown 三元组。

**Pre-Codex self-review: A-F checked** — A:unknown 态的"完整中性三元组(unknown/unknown/no_action)"两格都覆盖(risk_level+action);**scope 守住**——按 Codex de-scope 未扩到完整 status×action 矩阵(契约只锁 unknown 三元组),non-blocking 的 clear/tailwind/risk-action 观察已承认+deferred,不静默扩。B:helper 单一来源,summary+patch 两侧自动同改;契约文档已述该规则,无新漂移。C 反向:强制 unknown⇒no_action 不引入漏报(无证据→中性,更保守)。D N-A。E register 注记单态。F:127 tests OK、py_compile OK、FFFD=0、route-doc guard 14/14。

**Boundary**: advisory-only;不碰 official/boundary;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审 unknown-action 不变式)。

---

## 2026-06-13 — Codex `审查` PASS (语义风险 Slice 2b-ii-A — evidence-contract + contract-anchor clean)

**Scope**: re-reviewed the working-tree repair after the prior `unknown ⇒ action no_action` doc-drift FAIL. Covered `runners/a_short_semantic_risk_summary.py`, `tests/test_a_short_semantic_risk_summary.py`, `tests/test_a_short_semantic_risk_contract_docs.py`, `docs/a_short_semantic_risk_contract.md`, `docs/a_short_semantic_risk_coverage.md`, `schemas/a_short_semantic_risk_web_llm_patch.schema.json`, `docs/README.md`, `docs/system_risk_register.md`, and the adjacent B2 process rule in `AGENTS.md`.

**Verdict**: PASS. No Required findings remain for Slice 2b-ii-A.

**What is now clean**:
- Behavior: `_web_llm_consistency_error` is the shared summary+patch authority. Empty-source `clear_light` / `tailwind` are rejected; `unknown/unknown/no_action` with empty sources is accepted; `unknown/unknown/downgrade|manual_review_required|observe` is rejected; stale web summary replacement and summary-schema-name matching are enforced.
- Contract anchoring: `docs/a_short_semantic_risk_contract.md` is the single durable web_llm invariant source. README / coverage / patch-schema description no longer restate a partial matrix; they route to the contract anchor instead.
- 48h wording: coverage states official_structured is configured-lookback PIT official-announcement evidence (default 90d), not an exact 48h freshness implementation.
- Boundary: advisory-only; no production/EGS/Phase5 behavior, data fetch, hard veto, historical-backtest claim, or full status/action matrix expansion.

**Independent probes**: patch validator rejects `unknown/unknown/downgrade`, `unknown/unknown/manual_review_required`, and `unknown/unknown/observe`; summary consistency rejects `unknown/unknown/downgrade`; patch validator accepts `unknown/unknown/no_action` with empty sources.

**Verification**: semantic-risk contract/summary/guard/probe suite = 114 OK; route-doc guard = 14 OK; summary/probe/web-patch schema Draft7 meta = 3 OK; `py_compile` OK; `git diff --check` OK (CRLF warnings only); custom text/FFFD/trailing-whitespace check OK. Old weak active prose grep only matches `assertNotIn` regression tests.

**Register**: existing semantic-risk Hot Queue items may flip to `resolved` during `提交` after this PASS is committed; no new material risk was found.

**Next**: Claude `提交`.

---

## 2026-06-13 — Codex `审查` FAIL (语义风险 Slice 2b-ii-A — unknown-action doc drift)

**Scope**: reviewed the working-tree repair for `R-SEMANTIC-WEBPATCH-UNKNOWN-ACTION-WITHOUT-EVIDENCE` across `runners/a_short_semantic_risk_summary.py`, `tests/test_a_short_semantic_risk_summary.py`, `tests/test_a_short_semantic_risk_contract_docs.py`, `docs/a_short_semantic_risk_contract.md`, `docs/a_short_semantic_risk_coverage.md`, `schemas/a_short_semantic_risk_web_llm_patch.schema.json`, `docs/README.md`, and `docs/system_risk_register.md`.

**Verdict**: FAIL. Code behavior is repaired, but active route/schema docs still restate the old weaker invariant and omit `unknown ⇒ action no_action`.

**Finding-1 (P3, route/schema summaries omit the newly fixed `unknown ⇒ action no_action` invariant)**: `_web_llm_consistency_error` now correctly rejects no-evidence actions: independent probes show `unknown/unknown/downgrade`, `unknown/unknown/manual_review_required`, and `unknown/unknown/observe` are rejected in patch validation, `summary` consistency rejects `unknown/unknown/downgrade`, and `unknown/unknown/no_action` with empty sources remains accepted. However the active docs still restate a partial matrix. `docs/a_short_semantic_risk_coverage.md:29` says `unknown ⇒ risk_level unknown` and only says action is one of the enum values; it omits `unknown ⇒ action no_action`. `docs/README.md:78` says unknown may have empty sources and must keep `risk_level unknown`, also omitting `action no_action`. `schemas/a_short_semantic_risk_web_llm_patch.schema.json:4` describes the cross-field authority as unknown may have empty sources plus non-unknown requires sources, again omitting the neutral-action rule. This conflicts with the stable contract at `docs/a_short_semantic_risk_contract.md:11-12` and violates the B2 rule just added to avoid partial repeated contracts. Required repair: update these active summaries to either stop restating the matrix and point only to the stable contract, or explicitly include `unknown ⇒ risk_level unknown AND action no_action`; extend `tests/test_a_short_semantic_risk_contract_docs.py` so coverage/README/schema prose cannot regress to the weaker wording again.

**Already verified clean**: the runner-level blocker is fixed. Probe output: `PATCH_UNKNOWN_downgrade REJECTED`, `PATCH_UNKNOWN_manual_review_required REJECTED`, `PATCH_UNKNOWN_observe REJECTED`, `SUMMARY_UNKNOWN_DOWNGRADE_REJECTED`, `PATCH_UNKNOWN_NO_ACTION_ACCEPTED`. Semantic-risk contract/summary/guard/probe suite = 113 OK; route-doc guard = 14 OK.

**Register**: recorded as `R-SEMANTIC-WEBPATCH-UNKNOWN-ACTION-DOC-DRIFT` in `docs/system_risk_register.md`.

**Boundary**: no production/EGS/Phase5 behavior, data fetch, hard veto, historical-backtest claim, or full status/action matrix expansion is authorized. This is a documentation/contract-drift repair only.

**Next**: Claude `修复`.

---

## 2026-06-13 — Codex `审查` FAIL (语义风险 Slice 2b-ii-A — unknown action evidence-contract gap)

**Scope**: reviewed current working tree for the A-short semantic-risk Slice 2b-ii-A evidence-contract repair after the prior FAILs: `runners/a_short_semantic_risk_summary.py`, `tests/test_a_short_semantic_risk_summary.py`, `schemas/a_short_semantic_risk_web_llm_patch.schema.json`, `docs/a_short_semantic_risk_coverage.md`, `docs/a_short_semantic_risk_contract.md`, `tests/test_a_short_semantic_risk_contract_docs.py`, `docs/README.md`, and the related risk-register note. The extra B2 contract-anchor process-doc change in `AGENTS.md` was treated as adjacent hygiene, not as business logic.

**Verdict**: FAIL. The previously named blockers are largely repaired: empty-source `clear_light` is rejected, empty-source `tailwind` is rejected, empty-source `unknown` is accepted, stale `summary` is replaced, schema-name mismatch is rejected, coverage no longer overclaims exact 48h, and README/coverage now route to the stable contract. One material evidence-contract gap remains.

**Finding-1 (P2, `unknown` can still carry a no-evidence action)**: `runners/a_short_semantic_risk_summary.py:244` returns success for `web_llm.status == "unknown"` once `risk_level == "unknown"`; it does not require `action == "no_action"`. This conflicts with `docs/a_short_semantic_risk_contract.md:11`, which states that 未检索/检索失败/证据缺失时 web must remain `unknown/unknown/no_action`. Independent probe: `validate_web_llm_patch` accepts `web_llm.status=unknown, risk_level=unknown, action=downgrade, sources=[]`. Materiality: a candidate with no search/evidence can still carry a soft downgrade/manual-review action into the advisory/M6.7 layer, which is the same evidence-boundary class as "unknown must not masquerade as clear", just through the action field. Required repair: enforce `unknown ⇒ risk_level unknown AND action no_action` in the shared `_web_llm_consistency_error`, and add regression tests for both patch validation and summary consistency rejecting `unknown/unknown/downgrade` (or `manual_review_required`) while preserving acceptance of `unknown/unknown/no_action` with empty `sources`.

**Non-blocking observation**: probes also show `clear_light/downgrade`, `tailwind/downgrade`, and `risk/no_action` are accepted. I am not making that a Required fix in this round because the current stable contract only explicitly locks the `unknown/unknown/no_action` triple and otherwise merely restricts the action enum to non-hard-veto/non-buy actions. A full status/action matrix can be designed later if desired.

**Register**: recorded as `R-SEMANTIC-WEBPATCH-UNKNOWN-ACTION-WITHOUT-EVIDENCE` in `docs/system_risk_register.md`.

**Verification**: semantic-risk contract/summary/guard/probe suite = 110 OK; route-doc guard = 14 OK; `git diff --check` OK (CRLF warnings only); `py_compile` OK. Independent probe result: `UNKNOWN_DOWNGRADE_ACCEPTED`, which is the blocker above.

**Boundary**: advisory-only; no production/EGS/Phase5 behavior, data fetch, hard veto, or historical-backtest claim is authorized. V14.2 remains frozen. 2b-ii-B skill prompts and weekly-panel wiring are still not part of this PASS gate.

**Next**: Claude `修复`.

---

## 2026-06-13 — Codex user-authorized implementation (semantic-risk contract-doc drift guard)

**Scope**: user approved the lightweight repair for the repeated "code/schema/doc contract drift" pattern. This implementation is process/document/test scope only; no EGS, production scoring, provider call, data fetch, hard veto, historical-backtest, or V14.2 behavior changed.

**Changed**:
- Added `docs/a_short_semantic_risk_contract.md` as the stable A-short semantic-risk contract anchor: advisory-only boundary, official_structured PIT/default-lookback wording, web_llm evidence invariant, patch merge whitelist, and drift-guard owner.
- Updated `docs/a_short_semantic_risk_coverage.md`, `docs/README.md`, and `schemas/a_short_semantic_risk_web_llm_patch.schema.json` to point at the stable contract and stop restating the stale weaker web invariant.
- Added `tests/test_a_short_semantic_risk_contract_docs.py` to bind behavior and docs: empty-source `clear_light`/`tailwind` are rejected, empty-source `unknown` is accepted, README/coverage old wording is rejected, and the 90-day-not-exact-48h caveat is present.
- Added the general B2 contract-anchor drift-guard rule to `AGENTS.md` so future repeated behavior contracts must have one stable anchor plus a focused doc-drift test.
- Updated `docs/system_risk_register.md` Hot Queue note for `R-SEMANTIC-COVERAGE-WEB-INVARIANT-STALE` to describe the working-tree repair; status still resolves only after re-`审查` PASS + `提交`.

**Verification**: semantic-risk contract/doc tests 5 OK; semantic-risk summary/probe/guard suite 105 OK; combined semantic-risk suite 110 OK; route-doc guard 14 OK; summary/probe/web-patch schema meta OK; `py_compile` OK; FFFD=0; `git diff --check` OK (CRLF warnings only).

**Boundary**: this does not complete Slice 2b-ii-B skill prompts or weekly-pipeline panel wiring; it only removes the recurring contract drift gap for the current semantic-risk layer and records the generic guardrail.

**Next**: `审查`.

---

## 2026-06-13 — Codex `审查` FAIL (语义风险 Slice 2b-ii-A — web_llm evidence invariant docs drift)

**Scope**: reviewed current working tree after commit `d47db96`: tracked changes in `docs/README.md`, `docs/SESSION_LOG.md`, `docs/system_risk_register.md`, `runners/a_short_semantic_risk_summary.py`, `tests/test_a_short_semantic_risk_summary.py`; untracked `docs/a_short_semantic_risk_coverage.md`, `schemas/a_short_semantic_risk_web_llm_patch.schema.json`. Re-reviewed the previous Required fixes and the new repair for "non-unknown web status must have evidence".

**Verdict**: FAIL, but the remaining issue is documentation/contract drift, not runner behavior. Code-level repairs are correct: `clear_light` with empty sources is rejected, `tailwind` with empty sources is rejected, `unknown` with empty sources is accepted, stale-summary replacement remains fixed, and schema-name mismatch remains rejected.

**Finding-1 (P3, coverage/route docs still describe the old weaker web evidence invariant)**: `docs/a_short_semantic_risk_coverage.md` still states the web invariant as `风险态(risk_candidate/risk/headwind) ⇒ ... 必有 sources`, then separately lists `clear_light ⇒ risk_level none` and `tailwind ⇒ none/low`. That is the old weaker contract and omits the actual new rule implemented in `_web_llm_consistency_error`: **any non-unknown web status** (`clear_light`, `tailwind`, `risk_candidate`, `risk`, `headwind`) must carry `sources`; only `unknown` may have empty sources. `docs/README.md` also has an older Slice-2a route sentence summarizing `validate_summary_consistency` as `web risk-status ⇒ sources required`, which is no longer the full validator contract. Materiality: this is exactly the class of doc-contract drift that can cause 2b-ii-B or a later maintainer to reintroduce empty-source `clear_light`/`tailwind` while believing the coverage doc allows it. Required fix: update the coverage doc web_llm invariant bullet and the README validator summary to say "non-unknown / evaluated web status requires sources; unknown may have empty sources".

**Already verified clean**: prior P2 behavior blocker fixed. `clear_light_empty_sources=rejected`; `tailwind_empty_sources=rejected`; `unknown_empty_sources=accepted`. Stale-summary probe: `stale_present=False`, `sources_len=1`. Schema-name mismatch probe rejected.

**Register**: recorded as `R-SEMANTIC-COVERAGE-WEB-INVARIANT-STALE` under the existing semantic-risk web_llm Hot Queue item. No new production/EGS/Phase5 behavior, data fetch, hard veto, or historical-backtest claim is authorized.

**Verification**: semantic-risk/probe/guard tests = 105 OK; route-doc guard = 14 OK; summary/probe/web-patch schema Draft7 meta OK; `py_compile` OK; FFFD=0; `git diff --check` only CRLF warnings. `docs/a_short_semantic_risk_coverage.md` exact 48h wording is repaired.

**Boundary**: advisory-only; no EGS/Phase5/production-path write/hard-veto/historical-backtest; V14.2 frozen; `egs_main` untouched.

**Next**: Claude `修复`.

---

## 2026-06-13 — Claude `修复` (Slice 2b-ii-A — 非 unknown 态须有证据 + coverage 48h 收措辞)

两条都成立:

**Finding-1 (P2, clear/tailwind 无证据) ✅**:又是 unknown-not-clear 核心边界——我只对 risk 态要 sources,`clear_light`/`tailwind` 空 sources 也被接受 → 无证据的清白/顺风结论与"没检索"无法区分。
- Fix:`_web_llm_consistency_error`(summary+patch 共享)改为**任何非 `unknown` 态都必须有 sources**;只有 `unknown` 可空。headless summary(web 恒 unknown)不受影响。
- 测试:clear_light 空 sources→拒、tailwind 空 sources→拒、unknown 空 sources→放行;既有 patch 测改为带证据(`_pc` 默认 sources 非空)。

**Finding-2 (P3, 48h 过度声称) ✅**:coverage 文档把"监管48h"说成 official_structured 已建,但实际 90 天 lookback、只 ≤as_of、无 48h 窗口。
- Fix:措辞改为"配置 lookback 内 PIT 官方公告证据,非精确 48h;精确时效/媒体负面属 2b-ii-B skill 或未来 recency 字段"。

**Pre-Codex self-review: A-F checked** — A:把"非 unknown ⇒ 须证据"作为整类一条规则覆盖所有已评估态(clear_light/tailwind/risk*),非只补 clear;B ripple-grep:helper 为单一来源,headless summary web=unknown 不回归(119 tests 确认);C 反向:要求 clear 带证据不会反向漏报(无证据→留 unknown 更保守);D N-A;E register 注记单态;F:py_compile OK、FFFD=0、119 tests OK、route-doc guard 14/14。

**Boundary**: advisory-only;不碰 official/boundary;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审 evidence 不变式 + coverage 措辞)。

---

## 2026-06-13 — Codex `审查` FAIL (语义风险 Slice 2b-ii-A — web_llm patch evidence contract)

**Scope**: reviewed current working tree after commit `d47db96`: tracked changes in `docs/README.md`, `docs/SESSION_LOG.md`, `docs/system_risk_register.md`, `runners/a_short_semantic_risk_summary.py`, `tests/test_a_short_semantic_risk_summary.py`; untracked `docs/a_short_semantic_risk_coverage.md`, `schemas/a_short_semantic_risk_web_llm_patch.schema.json`. Re-reviewed the prior Codex FAIL repairs plus the new web_llm patch schema/merge contract, tests, coverage doc, README route row, and relevant prompt/design assertions.

**Verdict**: FAIL。上轮两个 Required 已实际修复: stale summary 探针现在 `stale_present=False`; schema-name mismatch 探针现在 rejected。新的 blocker 是 web_llm patch 仍允许无检索证据的正向/清白结论,会破坏 "未检索/失败必须 unknown,不能伪装 clear" 的核心边界。

**Finding-1 (P2, clear/tailwind without evidence can masquerade unknown as clear)**: `validate_web_llm_patch` / `_web_llm_consistency_error` currently requires `sources` only for risk statuses (`risk_candidate` / `risk` / `headwind`). Independent probes show both `clear_light/none/no_action` with `sources=[]` and `tailwind/none/observe` with `sources=[]` are accepted. This conflicts with the frozen design text in `docs/a_short_semantic_risk_top15_enrichment_design_20260612.md`: "未检索/失败→unknown,绝不伪装 clear", "无命中但检索成功→clear_light(须带 source coverage / checked_at / scope)", and Slice-2 tests requirement "sources·date·confidence·action 必填". Materiality: a skill or future weekly panel can present a web/LLM `clear_light` or `tailwind` conclusion with no source/coverage evidence, which is indistinguishable from "not actually checked" and can under-warn the user. Required fix: encode a positive evidence/coverage invariant before any non-unknown web status can be written. Recommended narrow repair: require `sources` (or a newly explicit per-candidate `checked_scope`/coverage object) for `clear_light` and `tailwind` as well as risk statuses; if no source/coverage check exists, status must remain `unknown/unknown/no_action`. Add regression tests rejecting `clear_light` with empty coverage and `tailwind` with empty coverage, and update existing tests that currently treat empty-source clear patches as valid.

**Finding-2 (P3, coverage doc overclaims exact 48h regulatory coverage)**: `docs/a_short_semantic_risk_coverage.md` maps "监管 48h" to `official_structured(cninfo PIT 公告...)` and says the structured part is built, but the actual cninfo runner default is `--cninfo-lookback-days 90` and `build_official_structured` only filters `disclosure_date <= as_of`; it does not enforce a 48h recency window. This is not a code contamination bug, but the coverage map should not imply exact 48h implementation. Required doc repair: state that official_structured currently provides broader PIT official-announcement evidence over the configured lookback, while exact 48h freshness / media-negative judgment remains a 2b-ii-B skill/prompt or future recency-field responsibility.

**Register**: material contract/doc gaps recorded in `docs/system_risk_register.md` as `R-SEMANTIC-WEBPATCH-CLEAR-WITHOUT-COVERAGE`, `R-SEMANTIC-WEBPATCH-TAILWIND-WITHOUT-COVERAGE`, and `R-SEMANTIC-COVERAGE-48H-OVERCLAIM`.

**Verification**: targeted semantic-risk/probe/guard tests = 102 OK; route-doc guard 14 OK; summary/probe/web-patch schema Draft7 meta OK; `py_compile` OK; FFFD=0; `git diff --check` produced only CRLF warnings. Independent probes: stale-summary replacement repaired; schema-name mismatch repaired; `clear_light_empty_sources=accepted`; `tailwind_empty_sources=accepted`.

**Boundary**: advisory-only; no EGS/Phase5/production-path write/hard-veto/historical-backtest; V14.2 frozen; `egs_main` untouched.

**Next**: Claude `修复`.

---

## 2026-06-13 — Claude `修复` (Slice 2b-ii-A — patch merge 替换不全 + target schema_name 未校验)

两条都成立(我的 merge 矩阵漏了两格,checklist A 没把"所有可替换字段都真替换"+"所有 target 字段都校验"列全):

**Finding-1 (P2, stale summary) ✅**:`apply_web_llm_patch` 声称替换语义,却只在 patch 带 summary 时覆盖 → risk(带 summary)→ clear(不带 summary)后旧风险 summary 残留,与当前 web 态矛盾。
- Fix:每次 patch 候选**总是**设 `c["summary"]`——带则用,不带则按当前 official+web 态**重生**,绝不留旧文。

**Finding-2 (P3, schema_name 未校验) ✅**:只校验 as_of+version,漏 summary_schema_name。
- Fix:merge 前校验 `target.summary_schema_name == summary.schema_name == SCHEMA_NAME`。

**Pre-Codex self-review: A-F checked** — A:补全"替换字段矩阵"(web_llm/sources/confidence/**summary**)+"target 校验矩阵"(as_of/version/**schema_name**),每格一回归测试;B ripple-grep:summary 重生用现有 official_structured 字段,无新符号,既有 50 patch/summary 测无回归;C 反向:重生 summary 反映当前态(降级后不残留旧风险文)= 正是反向失败的修复,`test_no_stale_summary_after_clear_overwrite` 守;D N-A;E register 注记非流水账;F:py_compile OK,FFFD=0,116 tests OK。

**Boundary**: advisory-only;不碰 official/boundary;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审 summary 替换 + schema_name 校验)。

---

## 2026-06-13 — Codex `审查` FAIL (语义风险 Slice 2b-ii-A — web_llm patch merge contract)

**Scope**: reviewed current working tree after commit `d47db96`: tracked changes in `docs/README.md`, `docs/SESSION_LOG.md`, `docs/system_risk_register.md`, `runners/a_short_semantic_risk_summary.py`, `tests/test_a_short_semantic_risk_summary.py`; untracked `docs/a_short_semantic_risk_coverage.md`, `schemas/a_short_semantic_risk_web_llm_patch.schema.json`.

**Verdict**: FAIL。Slice 2b-ii-A 的方向正确:patch schema + validate/apply 纯函数 + shared web invariant + coverage doc 都符合 advisory-only 边界。但 merge 契约还有两个测试未覆盖的漏洞。

**Finding-1 (P2, stale web summary after replacement)**: `apply_web_llm_patch` 声称 `web_llm/sources/confidence/summary` 是替换语义,但代码只在 patch candidate 携带 `summary` 时才覆盖 `c["summary"]`。独立探针:先对候选打 `risk/high/manual_review_required + summary="old risk summary"`,再用同一候选的 `clear_light/none/no_action` patch(不带 summary)覆盖,结果 `web_llm.status=clear_light`, `sources=[]`,但 `summary` 仍是 `old risk summary`。这会让面板/人工阅读看到与当前 web 状态相反的风险说明。Required fix: 明确定义 optional summary 的替换语义;建议每次候选被 patch 时都设置 `c["summary"] = pc.get("summary", "")` 或其他明确中性值,并加回归测试:风险 patch 带 summary → clear patch 不带 summary 后旧 summary 必须消失。

**Finding-2 (P3, target summary_schema_name not enforced)**: patch schema 有 `target.summary_schema_name`,但 `apply_web_llm_patch` 只校验 `as_of` 和 `summary_schema_version`。独立探针把 summary 的 `schema_name` 改成 `wrong_schema_name`,version 保持 `1.0.0`;patch 仍被接受并返回 `schema_name=wrong_schema_name`。Required fix: merge 前校验 `patch["target"]["summary_schema_name"] == summary["schema_name"] == "a_short_semantic_risk_summary"`(或等价),并加回归测试。

**Register**: material contract gaps recorded in `docs/system_risk_register.md` as `R-SEMANTIC-WEBPATCH-STALE-SUMMARY` and `R-SEMANTIC-WEBPATCH-SCHEMA-NAME-MISMATCH`.

**Verification**: `tests.test_a_short_semantic_risk_summary + tests.test_semantic_risk_slice3_guard + tests.test_a_short_semantic_risk_probe` = 100 tests OK; route-doc guard 14/14 OK; summary/probe/web-patch schema meta OK; `py_compile` OK. These pass because the two adversarial probes above are not yet covered by tests.

**Boundary**: advisory-only; no EGS/Phase5/production-path write/hard-veto/historical-backtest; V14.2 frozen; `egs_main` untouched.

**Next**: Claude `修复`.

---

## 2026-06-13 — Claude `起草` (语义风险 Slice 2b-ii-A — web_llm enrichment 契约 + coverage 文档)

**切片**: 2b-ii 拆 **2b-ii-A(headless 契约+merge+coverage,可测)+ 2b-ii-B(skill prompts + 面板接入 weekly,skill 在环)**。本轮 2b-ii-A。

**交付物**:
- `schemas/a_short_semantic_risk_web_llm_patch.schema.json` — skill 产出的 patch 契约(per-candidate web_llm status/risk_level/action + sources + confidence + 可选 summary;boundary advisory_only/not_deterministic_veto/never_touches_official const)。
- `runners/a_short_semantic_risk_summary.py`:`validate_web_llm_patch`(schema + canonical target.as_of + 无重复 ts_code + web 不变式)、纯 `apply_web_llm_patch`(校验 + target.as_of/schema-version 匹配 + 拒 universe 外代码 + **只**写 web_llm/sources/confidence/summary、**绝不**碰 official_structured/boundary/rank/scan_tier/ts_code/coverage、替换非追加、合并后跑 `validate_summary_consistency` 作 authority)。web 不变式抽成共享 `_web_llm_consistency_error`(summary 与 patch 单一来源,防漂移)。
- `docs/a_short_semantic_risk_coverage.md` — 覆盖 map。

**Pre-Codex self-review: A-F checked** —
- **A 类不修实例**:patch merge 不变式矩阵一次覆盖——target 不匹配 / universe 外代码 / 重复 ts / 改 official·boundary(schema additionalProperties:false + merge 白名单)/ web 不变式(unknown·风险态需 sources·clear_light·tailwind)/ idempotent,每格一测(10 patch tests)。
- **B ripple-grep**:`a_short_semantic_risk_web_llm_patch` 引用命中 README:79 + coverage:10/27 + runner:51/52(契约已路由);抽取 `_web_llm_consistency_error` 后既有 40 summary tests 无回归。
- **C 反向失败**:merge 不得篡改 official/降级官方风险——`test_happy_merge_and_official_untouched` 深比 official_structured/boundary/scan_tier 合并前后相等。
- **D**:N-A(无歧义 NL 分类新增)。
- **E route-doc 单态**:register 新条目最终态;coverage 文档单态。
- **F**:schema Draft7 meta OK;canonical target.as_of 校验;py_compile OK;FFFD=0(6 文件);114 tests OK。

**Boundary**: advisory-only;web action 永不硬否决/买入;LIVE 不可复现/绝不进历史回测;不写 production;V14.2 frozen;egs_main stage3 未碰。

**Next**: `审查`(审 2b-ii-A)→ 提交 → 2b-ii-B(skill prompts + 面板接入 weekly pipeline)。

---

## 2026-06-13 — Claude `提交` (语义风险 Slice 2b-i + pre-Codex self-review checklist → local master)

Codex PASS(entry below,复审 scope 同时含 2b-i pending set + checklist 接线,tests 90/90 OK)。一次提交两 scope(Codex 作为同一 pending set 一并审过,共享 README/register/SESSION_LOG 已交织,不再 hunk 拆分):
- **Slice 2b-i**:`a_short_semantic_risk_summary.py`(severity 分级 + 最窄 routine 抑制 `ROUTINE_OCCUPATION_FORMS`+`NO_OCCUPATION_NEGATIONS` + `render_semantic_risk_panel`)+ schema(event severity)+ tests。register 项 flip resolved。
- **pre-Codex self-review checklist**:`docs/pre_codex_self_review_checklist.md` + `AGENTS.md §Claude implementer standard` item 7(A-F gate + proof-of-use)+ README 路由。register 项 resolved。

**Pre-Codex self-review: A-F checked** — A:两 scope 各自类×出口已在前轮覆盖;B ripple-grep:checklist routing 命中 AGENTS+README,旧 `NEGATIVE_PATTERNS`/`ESCALATION_MARKERS` 仅在 SUPERSEDED 历史;C/D N-A(本轮纯提交);E:register 两条均最终态单态;F:route-doc guard 14/14 + summary/probe 90 tests OK + FFFD=0。

**边界**:advisory-only;V14.2 frozen;egs_main stage3 未碰;无 push。

**Next**: 见下方"全项目下一步"。

---

## 2026-06-13 — Codex `审查` PASS (pre-Codex self-review checklist 接线复审)

**Scope**: reviewed tracked working tree and untracked `docs/pre_codex_self_review_checklist.md`: `AGENTS.md`, `docs/README.md`, `docs/system_risk_register.md`, `docs/SESSION_LOG.md`, semantic-risk Slice 2b-i code/schema/tests already in the same pending change set, and the new checklist file.

**Verdict**: PASS。上一轮三条 Required 均已修复。R-1 adoption: compact A-F gate + proof-of-use is now in `AGENTS.md §Claude implementer standard` item 7, and detailed doc is routed from `docs/README.md`; `docs/AI_REVIEW_PROTOCOL.md` remains a pointer, no duplicate checklist. R-2 route-doc semantics: checklist §E now bans only transient next-actor/next-command gate from `CURRENT`/durable route docs and explicitly allows `system_risk_register` stable open-risk status + closure criteria. R-3 proof-of-use: AGENTS + checklist require each Claude `起草`/`修复` SESSION_LOG entry to include `Pre-Codex self-review: A-F checked / N-A` with grep/test evidence.

**Register**: `Pre-Codex self-review checklist adoption gap` is marked `resolved` in `docs/system_risk_register.md`. No new material risk found.

**Verification**: route-doc guard 14/14 OK; semantic-risk related tests 90/90 OK; summary/probe schema meta OK; `py_compile` OK; FFFD=0 for touched docs/code/schema/tests; `git diff --check` only CRLF warnings. Residual scans show old `NEGATIVE_PATTERNS` / `ESCALATION_MARKERS` only in explicit `SUPERSEDED` history, and old checklist adoption-gap text only in historical SESSION_LOG / resolved register narrative.

**Boundary**: process/docs only for checklist repair; no business-code/schema behavior change beyond the previously reviewed semantic-risk Slice 2b-i pending set; V14.2 frozen; `egs_main` untouched.

**Next**: Claude `提交`.

---

## 2026-06-13 — Claude `修复` (pre-Codex self-review checklist — 采纳缺陷 + 语义过宽 + 留痕)

三条都成立(我那份"防遗忘"的 checklist 自身有易遗忘的采纳缺陷,够讽刺):

**R-1 (P2, 采纳缺陷) 成立**:checklist 是孤立未路由文件,无机制强制未来 Claude 读/执行。
- Fix:把紧凑 A-F gate + proof-of-use 折进 `AGENTS.md §Claude implementer standard` item 7(每次 起草/修复 交付前必走);`docs/README.md` 路由表加指向详细文档的行;`AI_REVIEW_PROTOCOL.md` 保持纯指针(不重复 checklist)。

**R-2 (P2, register ban 过宽) 成立**:checklist §E 说 gate"绝不进 CURRENT/register"——register 部分太宽,`system_risk_register` 是持久 open-risk 队列,合法记 stable status + closure criteria。
- Fix:§E(+ AGENTS gate)收窄为"只禁 transient next-actor/next-command gate 进 CURRENT/durable route docs;register 可记 stable open-risk status + closure criteria"。

**R-3 (P3, 无留痕契约) 成立**:checklist 不要求留证据。
- Fix:checklist + AGENTS 现要求每条 起草/修复 SESSION_LOG entry 带 `Pre-Codex self-review: A-F checked / N-A` + grep/test 证据。

**Pre-Codex self-review: A-F checked** — A: 本修类=checklist 采纳,出口=AGENTS+README+register 三处一次覆盖(非只建文件);B ripple-grep:`Select-String pre_codex_self_review_checklist|Pre-Codex self-review` → AGENTS.md:348/355 + README.md:16 命中(routing 就位),旧过宽措辞仅存在于 checklist §E 已改;C 反向:折进 AGENTS 未与既有 item 1-6/§Codex standard 冲突(已读);D N-A;E:register R-PRECODEX 条目用 repaired 注记非流水账,wording 收窄;F:route-doc guard 14/14 OK,FFFD=0(4 文件)。

**Boundary**: 纯 process/docs;无代码/schema/behavior;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审 AGENTS 折叠 + README 路由 + §E 收窄 + 留痕)。

---

## 2026-06-13 — Codex `审查` FAIL (Claude pre-Codex self-review checklist — 方向正确但不是最优落地)

**Scope**: reviewed tracked working tree plus untracked `docs/pre_codex_self_review_checklist.md`. Relevant existing authorities checked: `AGENTS.md §Claude implementer standard`, `AGENTS.md §Codex adversarial review standard`, `docs/AI_REVIEW_PROTOCOL.md` pointer/duplication rule, `docs/README.md` routing table, and `docs/system_risk_register.md`.

**Verdict**: FAIL / not optimal as-is. The checklist's A-F content is directionally right and directly targets the repeated failure pattern (fixing only the named instance, missing ripple docs, missing reverse-failure tests, route-doc accretion). But it is currently a standalone untracked/unrouted file; no startup route or Claude implementer rule forces future Claude sessions to read it or attest it. A checklist that is easy to forget is not the optimal repair for "Claude keeps forgetting".

**Required-1 (P2, cross-LLM continuity / adoption gap)**: `docs/pre_codex_self_review_checklist.md` is not referenced by `AGENTS.md`, `docs/README.md`, or `docs/AI_REVIEW_PROTOCOL.md` (`rg` only finds the file itself). Required repair: fold a compact A-F pre-Codex gate into `AGENTS.md §Claude implementer standard` and route the detailed doc from `docs/README.md`, or delete the standalone file and keep only AGENTS bullets. `docs/AI_REVIEW_PROTOCOL.md` should remain a compatibility pointer, not a duplicated checklist.

**Required-2 (P2, route-doc semantics over-broad)**: checklist E.39 says review/commit gate must never enter `CURRENT/register`. The `CURRENT` part is right, but the `register` ban is too broad: `system_risk_register` is the durable open-risk queue and can legitimately record stable status / closure criteria. Required repair: narrow the wording to forbid transient next-actor / next-command state in `CURRENT` and durable route docs, while explicitly allowing stable risk closure criteria in `system_risk_register`.

**Required-3 (P3, no proof-of-use contract)**: the checklist does not require Claude to leave evidence that it ran the checklist. Required repair: Claude `起草` / `修复` SESSION_LOG entries should include a short `Pre-Codex self-review: A-F checked / N-A` line with the actual grep/test/schema evidence, especially for B/C/E.

**Register**: recorded as `Pre-Codex self-review checklist adoption gap` in `docs/system_risk_register.md` with Required IDs `R-PRECODEX-CHECKLIST-UNROUTED` and `R-PRECODEX-CHECKLIST-REGISTER-OVERBROAD`.

**Verification**: read the checklist content with UTF-8 (PowerShell display mojibake was terminal encoding, not file corruption); `rg` confirmed no routing pointer; inspected AGENTS Claude implementer standard and AI review protocol duplication warning. No business code/schema behavior reviewed or changed in this checklist review.

**Next**: Claude `修复`.

---

## 2026-06-13 — Codex `修复+审查` PASS (语义风险 Slice 2b-i — register 计数残留修复 + 完整复审)

**Fix**: `docs/system_risk_register.md` Slice 2b-i Hot Queue 验证行已从旧的 `38 summary + 1 guard + 49 probe + 14 route-doc tests pass` 改成不带易漂移数字的 "Targeted summary/guard/probe suites pass; route-doc guard passes; schema meta + py_compile OK"。

**Verdict**: PASS。代码、schema、测试、README/register 当前机制描述一致:裸 routine 专项说明/汇总表无明确无占用否定式 → `risk[medium]`;routine + 明确无占用否定式 → clear;正向/可疑占用与高 severity 事件 → risk。`NEGATIVE_PATTERNS` / `ESCALATION_MARKERS` 只保留在 `SUPERSEDED interim` 历史说明中,不再作为当前机制。

**Checks**: behavior probe OK; 90 related tests OK; 14 route-doc guard tests OK; schema meta OK; `py_compile` OK; FFFD=0 for touched docs/code/schema/tests; `git diff --check` only CRLF warnings。

**Boundary**: advisory-only, no hard-veto/EGS/Phase5/production-path/historical-backtest; V14.2 frozen; `egs_main` stage3 untouched; panel render function only, weekly-pipeline wiring deferred to later slice.

**Next**: Claude `提交`。

---

## 2026-06-13 — Codex `审查` FAIL (语义风险 Slice 2b-i 第七轮复审 — register 验证计数残留)

**Verdict**: FAIL。代码行为、README、register 最终机制描述均已对齐最窄策略:裸 routine 无否定式 → `risk[medium]`;routine + 明确无占用否定式 → clear;正向/可疑风险 → risk。`NEGATIVE_PATTERNS` / `ESCALATION_MARKERS` 只以 `SUPERSEDED interim` 出现,可接受。未发现新的代码/schema 行为阻断。

**Finding-1 (P3, current register verification count stale)**: `docs/system_risk_register.md` 当前 Slice 2b-i Hot Queue 行仍写 `38 summary + 1 guard + 49 probe + 14 route-doc tests pass`。当前实际 targeted run 为 `tests.test_a_short_semantic_risk_summary` + guard + probe = 90 tests OK,其中 summary 已是 40 tests(40 + 1 + 49 = 90),route-doc 14 tests OK。活动 route-doc 不应保留错误验证计数。Required fix: 改成当前真实计数,或更稳妥地改成不带易漂移数字的 "targeted summary/guard/probe + route-doc suites pass; schema meta + py_compile OK"。

**Checks**: behavior probe OK; 90 related tests OK; schema meta OK; route-doc guard OK; FFFD=0 for README/register/SESSION_LOG; `py_compile` OK; `git diff --check` only CRLF warnings。

**Next**: Claude `修复` register verification-count wording 后再交 Codex `审查`。

---

## 2026-06-13 — Claude `修复` (Slice 2b-i — register Hot Queue 压成最终状态,清旧机制)

**Finding 1 (P2) 成立**:register Slice 2b-i 活动行把 round 1-4 repair 流水账全堆在内,前半段仍写旧机制(`ESCALATION_MARKERS`/`no escalation marker → clear`),后半段才是 round-4 最窄策略——同一活动 route-doc 并存冲突的当前机制,后续 LLM 易按前半段旧机制改。这是我 route-doc state-duplication 老毛病([[feedback_route_docs_state_duplication]])。
- Fix:整条 Hot Queue entry 重写——**CURRENT MECHANISM** 段只留最窄策略(`ROUTINE_OCCUPATION_FORMS`+`NO_OCCUPATION_NEGATIONS`,裸 routine→risk),**SUPERSEDED interim** 段把 round 1-3 的 `NEGATIVE_PATTERNS`/`_has_adverse_marker` 压成一句"已删除、勿重引入"。README 已确认无旧机制残留。

**Pre-flight**:README grep 无 ESCALATION_MARKERS/NEGATIVE_PATTERNS 残留;route-doc guard OK;FFFD 待校验。

**Boundary**: 纯 register 文案重排;无代码/schema/behavior 改动;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审 Hot Queue 重写)。

---

## 2026-06-13 — Codex `审查` FAIL (语义风险 Slice 2b-i 第六轮复审 — register Hot Queue 仍混入旧机制)

**Verdict**: FAIL。代码行为、测试、schema 都已通过最窄策略复审:裸 routine 浦发专项说明/情况汇总表 → `risk[medium]`;明确否定式 `不存在/未发生/无新增/不存在被...占用` → clear;正向 `存在/发生` → risk。`docs/README.md` 的旧 "浦发 now clear" 也已修正。剩余问题在 current Hot Queue 文案。

**Finding-1 (P2, current register line 仍含已废弃机制且未明确 superseded)**: `docs/system_risk_register.md` 当前 Slice 2b-i Hot Queue 行仍在前半段写 `suppression is NARROW (_is_routine_occupation_report + ESCALATION_MARKERS)`、`with NO escalation marker is suppressed`、以及 earlier repair 中 `only the no-escalation annual occupation special report → clear`。同一行后半段又说 round-4 已删除 `_has_adverse_marker`/`ESCALATION_MARKERS`,改为 `NO_OCCUPATION_NEGATIONS` 最窄策略。虽然能读出后文覆盖前文,但这是 durable current route-doc 的活动行,不应同时保留互相冲突的当前机制;后续 LLM 很容易按前半段旧机制继续修。Required fix: 把 Hot Queue 当前描述压缩成最终状态,或把旧 round 1-3 机制移出/明确标为 `superseded`;当前机制只保留 `ROUTINE_OCCUPATION_FORMS + NO_OCCUPATION_NEGATIONS`,以及"bare routine without explicit negation surfaces as risk"。

**Checks**: behavior probe OK; `tests.test_a_short_semantic_risk_summary` + guard + probe = 90 tests OK; schema meta OK; route-doc guard OK; `py_compile` OK; `git diff --check` 仅 CRLF warning。

**Next**: Claude `修复` register Hot Queue stale wording 后再交 Codex `审查`。

---

## 2026-06-13 — Claude `修复` (Slice 2b-i — route-doc 残留"浦发→clear"旧结论)

**Finding 1 (P2) 成立**:我转最窄策略时只改了抑制逻辑描述,漏改更早那句顶层结论 *"unit test reproduces the exact 浦发 专项说明 title → now `clear`"*,留在 `docs/README.md` + `docs/system_risk_register.md` Hot Queue,与当前实现/测试(裸 routine 浦发 → risk[medium])相反。
- Fix:两处改为"裸 routine 无否定式 → risk[medium] 交 skill 降级;仅 routine+明确无占用否定式 → clear,两向均有单测"。SESSION_LOG 第 15 行那句是 Codex 审查叙述(历史 append-only),不动。

**Pre-flight**:残留扫描确认 active 行无旧结论;54 tests(summary 40 + route-doc 14)OK;FFFD=0。

**Boundary**: 纯 docs 订正;无代码/schema/behavior 改动;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审 route-doc 订正)。

---

## 2026-06-13 — Codex `审查` FAIL (语义风险 Slice 2b-i 第五轮复审 — route docs 残留旧结论)

**Verdict**: FAIL。代码行为已切到最窄策略且通过对抗探针:裸 routine 浦发专项说明/情况汇总表 → risk[medium] 交 skill 降级;明确否定式 `不存在/未发生/无新增/不存在被...占用` → clear;`存在/发生` 等正向风险 → risk。旧 JSON 产物仍不存在。测试/schema/route guard 也全过。

**Finding-1 (P2, route-doc active line 与实现相反)**: `docs/README.md` Slice 2b-i 行仍写 "A unit test reproduces the exact 浦发 专项说明 title → now `clear` (false positive fixed headlessly)"。`docs/system_risk_register.md` 当前 Hot Queue 同样残留 "Unit test reproduces the exact 浦发 专项说明 title → now `clear`"。这与当前实现和测试相反: `tests/test_a_short_semantic_risk_summary.py::test_bare_routine_without_negation_now_surfaces_as_risk` 明确断言浦发裸 routine 专项说明 `assertIsNotNone`,实测也返回 `risk[medium]`。提交前必须删除/改写这两处旧结论,改成"裸 routine without explicit negation surfaces as risk; only routine+explicit no-occupation negation clears"。

**Checks**: behavior probe OK; `tests.test_a_short_semantic_risk_summary` + guard + probe = 90 tests OK; schema meta OK; route-doc guard OK; `py_compile` OK; `git diff --check` 仅 CRLF warning。

**Next**: Claude `修复` route-doc stale wording 后再交 Codex `审查`。

---

## 2026-06-13 — Claude `修复` (Slice 2b-i — 转最窄抑制策略,终结 routine 关键词 whack-a-mole)

**Finding 1 (P1, 否定式被误判 risk) 成立**:round-3 的 adverse markers 不处理否定语境,`未发生/无新增/不存在被…占用` 被误报 risk。**这是同类第 5 轮**(汇总表 → 存在/发生/被占用 → 未发生/无新增/否定式)。

**按用户授权转最窄策略(终结 whack-a-mole)**:
- 删掉脆弱的 `_has_adverse_marker`/`ESCALATION_MARKERS` 穷举。
- `_is_routine_occupation_report` **只抑制**"例行披露形式(`ROUTINE_OCCUPATION_FORMS` 专项说明/专项审核/汇总表)+ 标题明示无占用否定式(`NO_OCCUPATION_NEGATIONS` 不存在/未发生/无新增/无占用/…)"。
- **其余一切**(裸 routine 无否定式、明示/可疑占用、high)→ 报 risk,交 2b skill 降级。
- **设计后果**:残余误差**只会是误报(skill 可降级),绝不漏报**;漏掉某否定式只是让一份无占用报告多显示 risk,无害。**裸 routine 报告现 surface 为 risk[medium](逆转早前"3 银行归 clear")——这是 headless 粗筛、skill 精判的设计本意。**

**Finding 2 (P3)**:README 旧符号已在 round-3 部分改,本轮再校正为 `ROUTINE_OCCUPATION_FORMS`+`NO_OCCUPATION_NEGATIONS`。

**Pre-flight 复跑**:40 summary + 1 guard + 49 probe + 14 route-doc OK;py_compile OK。测试覆盖否定式(含 不存在被…占用)→ clear;裸 routine / 存在 / 发生 / 被占用 / 整改 / 违规担保 / 问询 → risk。

**教训(已落实)**:对"歧义自然语言分类"别走关键词穷举(必然 whack-a-mole);要么收到最窄安全侧(只抑制明确否定式,其余留 skill),要么直接交 skill。本轮即此修正。

**Boundary**: advisory-only;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审最窄策略)。

---

## 2026-06-13 — Codex `审查` FAIL (语义风险 Slice 2b-i 第四轮复审 — adverse marker 未处理否定式)

**Verdict**: FAIL。上轮的 `存在/发生/被占用` 漏报已修；README 旧 `NEGATIVE_PATTERNS` 符号也已改掉。但 `_has_adverse_marker` 新增后又引入一类系统性假阳性。

**Finding-1 (P1, 明确否定式被误判为 risk)**: `_has_adverse_marker` 只判断 marker 子串，不先处理否定语境。Unicode 探针确认以下标题当前都返回 `('资金占用','fund_occupation','medium')`：`关于公司未发生非经营性资金占用情况的专项说明`、`关于公司未形成非经营性资金占用情况的专项说明`、`关于公司无新增非经营性资金占用情况的专项说明`、`关于公司不存在被控股股东非经营性资金占用情况的专项说明`。这些标题明确是否定/无新增/不存在，占用风险不应由 headless 层报 risk。尤其 `不存在被...占用` 与本轮实现注释的 "`不存在`/`未存在` 不算 adverse" 冲突，因为后面的 `被 + 占用` 特判又把它拉回 risk。

**Required fix**: 在 adverse marker 前先做 explicit-negative guard，至少覆盖 `不存在`/`未存在`/`未发生`/`未形成`/`无新增`/`不存在被...占用` 等否定式；同时保留 `存在`/`发生`/`形成`/`新增`/`被...占用` 明示风险为 risk。补 adversarial tests，不能只测正向 marker。

**Checks**: 91 个相关单测 OK；schema meta OK；route-doc guard OK；`git diff --check` 仅 CRLF warning。测试未覆盖否定式 marker，所以仍 FAIL。

**Next**: Claude `修复` 后再交 Codex `审查`。

---

## 2026-06-13 — Claude `修复` (Slice 2b-i — 补 adverse/existence override 防明示风险漏报 + README 符号)

**Finding 1 (P1, 漏报) 成立**:escalation 不含 `存在/发生/被…占用`,导致"关于公司**存在**非经营性资金占用情况的专项说明"等明示风险标题被压成 clear(比 routine 误报更严重)。
- Fix:加 `_has_adverse_marker`——ESCALATION_MARKERS 扩(发生/形成/新增/未归还/未清偿/尚未归还/余额)+ 特判:`存在`(明示有占用)adverse 但 `不存在`/`未存在` 不算;`被…占用` adverse。routine 抑制改为 `routine form AND not _has_adverse_marker`。
- 测试:存在/发生/被占用 → risk;`不存在…专项说明` routine → 仍 clear。

**Finding 2 (P3, doc) 成立**:README 2b-i 行文件列表仍写已删的 `NEGATIVE_PATTERNS` → 改 `ROUTINE_OCCUPATION_FORMS`+`ESCALATION_MARKERS`。

**Pre-flight 复跑**:41 summary + 1 guard + 49 probe + 14 route-doc OK;py_compile OK。

**反思(同类第 4 轮)**:routine↔adverse 的歧义本质是 skill 的活,headless 关键词层注定有边界 case。我连续被点(汇总表→存在/发生/被占用)说明**穷举关键词形式集这条路本身脆**。本轮已尽量保守(adverse 全覆盖、宁误报不漏报);若 Codex 仍有边界 case,应考虑把 headless 抑制收到最窄(只压"不存在…占用"明确否定式),其余一律留给 web/LLM skill 降级——这才是设计本意(headless 粗筛、skill 精判)。

**Boundary**: advisory-only;V14.2 frozen;egs_main 未碰。

**Next**: `审查`(复审 adverse override + README)。

---

## 2026-06-12 — Codex `审查` FAIL (语义风险 Slice 2b-i 第三轮复审 — routine 抑制仍有真实风险漏报)

**Verdict**: FAIL。上轮指出的 `情况汇总表` 假阳性已经修掉；旧产物也已删除；整改/问询/处罚样例仍能正确浮出。但 routine 抑制仍有新的真实风险漏报。

**Finding-1 (P1, 漏报)**: `_is_routine_occupation_report` 现在用 `资金占用 + 情况 + (专项说明/专项审核/汇总表) + 无 ESCALATION_MARKERS` 判 clear，但 `ESCALATION_MARKERS` 不含 `存在` / `发生` / `被...占用` 这类明确实质风险措辞。Unicode 探针确认以下标题当前全被判 `clear`、events 为空：`关于公司存在非经营性资金占用情况的专项说明`、`关于公司发生非经营性资金占用情况的专项说明`、`关于公司被控股股东非经营性资金占用情况的专项说明`。这比 routine false positive 更严重，因为它会把标题已经明示的资金占用风险压掉。

**Required fix**: 将 adverse/existence markers 补入 escalation override，并加 tests：至少覆盖 `存在`、`发生`、`被控股股东...占用` 仍为 risk；同时保留 routine annual `非经营性资金占用及其他关联资金往来情况的专项说明/情况汇总表` clear。原则仍是宁可把可疑标题留给 web/LLM 降级，也不能把明示风险压成 clear。

**Finding-2 (P3, 文档残留)**: `docs/README.md` Slice 2b-i route row 的交付物列表仍写 `RISK_KEYWORD_MAP/NEGATIVE_PATTERNS/severity`，但代码已删除 `NEGATIVE_PATTERNS`，当前真实入口是 `ROUTINE_OCCUPATION_FORMS` + `ESCALATION_MARKERS`。这不是行为 blocker，但提交前应顺手改掉，避免后续 LLM 按旧符号找实现。

**Checks**: 90 个相关单测 OK；schema meta OK；route-doc guard OK；`py_compile` OK；`git diff --check` 仅 CRLF warning。测试未覆盖 `存在/发生/被占用` 标题，所以仍 FAIL。

**Next**: Claude `修复` 后再交 Codex `审查`。

---
