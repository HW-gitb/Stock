# Session Log

跨 LLM 认知交接日志。**reverse-chronological，最新 entry 在顶部**。

本文件存在的目的：commit message 和 handoff 记录"改了什么 / 为什么改"，但不记录 "试过什么没成 / 试过的方案为什么被否决 / 当前 LLM 的纠结点 / 下一步该做什么的判断"。这一层认知信息在跨 LLM 协作时最容易丢失。

进项目前每个 LLM 必读：本文顶部 1-3 条最近 entry。完整规则见 `AGENTS.md §Session log discipline`。

---

> 📦 **历史归档**:2026-05-25 … 2026-06-12 的 861 条更早 entry 已逐字移至 `docs/archive/session_log/session_log_archive_2026-05-25_to_2026-06-12.md`(完整历史,不丢)。本次归档时保留了归档前最新 30 条;之后新增 entry 继续累积到本文件,过大时再按 `AGENTS.md §Session log discipline → 归档` 归档。追溯更早请开归档文件。

## 2026-06-14 — Codex `审查 PASS` (R-ASHORT-WEBLLM-EM-SOURCE-CONTRACT-DRIFT-R2)
- **Verdict/Action**: PASS. R2 三个残留面已清:weekly wrapper 真取数清单改 em,probe CLI 标 legacy opt-in,README 设计行标历史并指向 EM contract;guard 覆盖 R1/R2 残留形态。
- **Required**: `R-ASHORT-WEBLLM-EM-SOURCE-CONTRACT-DRIFT-R2` addressed;`R-ASHORT-WEBLLM-EM-SOURCE-CONTRACT-DRIFT` 也随本切片闭合。提交时按 register 翻 resolved。
- **Verify**: targeted 245 OK;py_compile OK;diff-check clean;PS ParseFile OK;BOM/FFFD OK;full discover 1821 only 6 known `C:\Users\cnhea\tk.csv` PermissionError。
- **Next**: Claude `提交`。

## 2026-06-14 — Claude `修复` (R-ASHORT-WEBLLM-EM-SOURCE-CONTRACT-DRIFT-R2)
- **Verdict/Action**: R2 残留 sina-as-current 全清(详情见 register):ps1 Stage4 真取数清单 sina→em(×2)、probe CLI help/fatal/`--include-sina` help 标 legacy+非当前源(×3)、probe docstring 行标 legacy、README design 行标「历史设计·当前已切 em」。drift guard 强化:加 `weekly_screening.ps1` 入扫描集 + per-line scan(R1+R2 全形态:`cninfo+sina`/`cninfo/sina`/`可选 sina`/`新浪/web`/`抓 sina`/`web_llm=sina`)+ per-line legacy/canary 豁免 + planted 五形态。零 runtime 语义改动。
- **Required**: `R-ASHORT-WEBLLM-EM-SOURCE-CONTRACT-DRIFT-R2`;详情见 register。
- **Verify**: 全量 1842 OK;contract-docs 14 OK;强化 guard 的残留扫描全活跃面 = clean(自抓到 probe docstring 一处漏标、已修);ps1 ParseFile 0 errors 无 BOM;py_compile OK;diff-check 干净;_diag/_em_slice.patch 已删(R1)、仅 m67_validation byproduct untracked。
- **Next**: 审查。
- **Pre-Codex self-review**: A(整类一次扫全:不带 legacy 排除的全 sina/新浪 grep 逐行分 current-vs-legacy);B(连带:guard 同步覆盖 ps1 + 全形态,自跑 guard 抓出并修了 docstring 残留);C(反向:planted 五形态证 guard 真抓 + legacy/canary 豁免不误杀,canary 行非 web 源不动)。边界=docs/comments/CLI-help/guard。Tests passing ≠ design closure.

## 2026-06-14 — Codex `审查` FAIL (R-ASHORT-WEBLLM-EM-SOURCE-CONTRACT-DRIFT-R2)
- **Verdict/Action**: FAIL. CC 修复了 Python 主路径和多数契约面,但当前一键入口/CLI help/README 路由仍残留 Sina-as-current 口径,且新增 guard 未覆盖这些形态;详情见 register。
- **Required**: `R-ASHORT-WEBLLM-EM-SOURCE-CONTRACT-DRIFT-R2`;详情见 `docs/system_risk_register.md`。
- **Verify**: semantic/weekly/doc targeted 245 OK;py_compile OK;diff-check clean;active grep still hits `weekly_screening.ps1` true-fetch list, probe CLI help/fatal, README design row。
- **Next**: Claude `修复`。

## 2026-06-14 — Claude `修复` (R-ASHORT-WEBLLM-EM-SOURCE-CONTRACT-DRIFT)
- **Verdict/Action**: 三部分全办(详情见 register):① 全活跃当前路面 sina→em + sina 标 legacy(coverage / 两 schema desc / README probe 行 / probe+summary docstring);② drift guard 加 em-source 扫描(含 schema 描述 + route docs)+ planted;③ option-b:契约 §web_llm 定 EM tracked owner(`fetch_em_news` + `FetchEmNews` 测试)、probe 标 Slice-1 legacy 不建模 em、删 `_diag_web_sources.py` + `_em_slice.patch`(不作 ad-hoc 提交)。
- **Required**: `R-ASHORT-WEBLLM-EM-SOURCE-CONTRACT-DRIFT`;详情见 register。零 runtime 语义改动(不碰 DeepSeek/M6.7/生产 EGS/V14.2)。
- **Verify**: 全量 1842 OK(+2 守护);contract-docs 14 OK;py_compile OK;残留 active sina-as-current grep=0;`git diff --check` 干净;`_diag`/`_em_slice.patch` 已删、仅 `m67_validation_20260605` byproduct untracked。
- **Next**: 审查。
- **Pre-Codex self-review**: A(sina-as-current 整类:全活跃面 grep 改全、含 schema 描述)/ B(连带:drift guard 同步加 em-source 扫描含 schema+route docs;契约权威面定 owner)/ C(反向:legacy-marked sina 不误判 + planted 证 guard 真抓)。边界=源契约/docs/schema 描述/probe wiring/tests。Tests passing ≠ design closure.

## 2026-06-14 — Claude (session handoff:下一步序列 + /clear 启动须读)
**已提交(durable)**:Slice 3a/3b/3b-2(weekly_screening M6.7 一键串联 + standalone 退役 + run_lineage)、regime_fallback(`6046cfc`)、cadence 重命名(`659b677`)、account-state Rule12/13+持有(`3ef40497`)。
**未提交(working tree)**:em 主源接入 slice(probe `fetch_em_news` + summary `_em_sources` + schema source_type=em + pipeline provider 切 em + 测试 + 文档)——Codex 已审 **FAIL**,待 Claude `修复`。`_em_slice.patch` / `_diag_web_sources.py` / `research/results/a_short/m67_validation_20260605/` 为 untracked,勿误提交。
**下一步序列**:
1. **em `修复`** `R-ASHORT-WEBLLM-EM-SOURCE-CONTRACT-DRIFT`(全文见 register Hot Queue):① 所有活跃当前路面 sina→em(coverage / 两个 schema 的 description / README / probe+summary 顶 docstring + CLI help),sina 标 deprecated/legacy opt-in、无任何活跃行说 weekly provider "抓 sina";② 强化 `tests/test_a_short_semantic_risk_contract_docs.py` drift guard(含 schema 描述 + route docs + planted stale-Sina offender);③ 闭 EM 审计缺口(二选一:EM 加成 first-class tracked probe/feasibility 路径,或把 contract/README 降级标 probe=legacy-Sina-only + weekly EM 另立 tracked owner/test;**别把 `_diag_web_sources.py` 当 ad-hoc root helper 提交**)。边界:源契约/docs/schema 描述/probe wiring/tests;不改 DeepSeek/M6.7 语义、生产 EGS/V14.2/下单。修复前必走 `docs/pre_codex_self_review_checklist.md`。
2. em 修复 → Codex `审查` → PASS 后 `提交`(em-only;勿 add patch/diag/byproduct)。
3. em 提交后:删 `_em_slice.patch`(已用尽)+ 按 ①③ 决定处置 `_diag_web_sources.py`。
4. register 卫生:account-state 已提交 → 将 `R-ASHORT-ACCOUNT-STATE-RULE12-13-FINALIZE` 标 resolved。
5. 暂不触发(gated):cls 第二源(需签名);Slice 3 确定性升级(等 ~4 周 advisory 证据,见 memory `project_slice3_reminder_after_advisory_weeks`);A-long 2 clue forward-live。
**/clear 启动须读**:CLAUDE.md(自动加载,路由)→ `AGENTS.md` → `docs/CURRENT.md` → `docs/SESSION_LOG.md` 顶部(本条 + em FAIL/起草 + account-state)→ `docs/system_risk_register.md` Hot Queue(尤其 `R-ASHORT-WEBLLM-EM-SOURCE-CONTRACT-DRIFT` 全文)→ `git status`。`MEMORY.md` 自动加载 = 记忆索引(含本会话固化的 persist-findings-to-register / propose-codex-command 等规则)。

## 2026-06-14 — Codex `审查` FAIL (R-ASHORT-WEBLLM-EM-SOURCE-CONTRACT-DRIFT)
- **Verdict/Action**: FAIL. 运行代码方向基本正确(weekly provider 已切 EM、Top15 gate、fail-closed、targeted tests 绿),但活跃契约/coverage/schema/README/docstring 仍多处把 Sina 教成当前 web_llm 源,且 EM 主源可审计 probe/evidence 未进入正式 artifact 路径。
- **Required**: `R-ASHORT-WEBLLM-EM-SOURCE-CONTRACT-DRIFT` 已登记到 register。范围:源契约/route/schema 描述/probe wiring/guard;不改 DeepSeek/M6.7 语义、不改生产 EGS/V14.2/下单。
- **Verify**: targeted semantic/weekly/doc tests 243 OK; `py_compile` touched runners OK; `git diff --check` OK(仅 LF/CRLF warning); active scan confirmed stale Sina current-source wording in coverage/schema/README/probe/summary surfaces。
- **Next**: Claude `修复`。

## 2026-06-14 — Claude `起草` (web_llm em 主源接入 / sina 退役 / cls 暂缓)
- 背景:`执行` 实测 sina roll 端点失效(对任意 k 返回 `code=11 列表未注册`、`data` 恒空)→ web_llm 层一直暗着;诊断 `_diag_web_sources.py` 确认 em search-api/cmsArticleWeb 可用、cls 需签名(errno 50101)。
- 改动:probe 加 `fetch_em_news`(JSONP 剥壳 → `result.cmsArticleWeb` → normalize → PIT 近 N 天窗 + 倒序 cap;fail-closed)+ EM 常量;`fetch_sina`/`SINA_NEWS_URL_TEMPLATE` 标 DEPRECATED(仅留 legacy probe `--include-sina`)。summary `_sina_sources` 泛化为 `_news_sources` + 加 `_em_sources`(source_type=em);summary-schema source_type enum 加 `em`。pipeline `_build_deepseek_web_llm_provider` 切 em(`fetch_em_news`+`_em_sources`,签名加 `as_of`/`lookback_days`)+ `--web-news-lookback-days`(默认 30)+ main 接线。
- 测试:`FetchEmNews`(JSONP/recency 窗/cap/no-name/non-200/bad-as-of)+ `_em_sources` + `DeepSeekWebProviderWiring` 切 em(断言 source_type=em)。文档:契约 §web_llm 产出路径(权威)+ §来源 + coverage 表格 cell 同步(em 主源 / sina 弃用 / cls 暂缓)。
- Verify:全量 1840 OK;契约漂移 + 治理守护 OK;diff-check 干净;web_llm 仍 advisory-only / 绝不 hard_veto / unknown 不伪 clear / fail-closed,不碰确定性 base。account-state 已先提交(`3ef40497`),em 为独立 diff(em-only 3 文件 + pipeline/test 的 web 段)。
- Pre-Codex self-review:A(`fetch_em_news` 全出口覆盖)/ B(sina 消费点核全:provider 已切、probe main + build_candidate 保留 sina=dev/None、source_type enum 加 em、契约权威面更新)/ C(fail-closed 不伪 clear、PIT 拒未来文)。
- Next:审查(交 Codex 复审 em slice)。

## 2026-06-14 — Claude `审查 PASS` (account-state Rule12/13 + 持有 切片收尾)
- **Verdict/Action**: PASS。Codex 按 register 全数收尾:① `test_markdown_structure` 断言改「持有」计数;② **held+hard_veto→否决 安全边界测试**已加且真钉(构造 held+ST/退市 → 断言 操作==否决 + 「不得加仓/手动执行」,非 持有);③ `持有` m67_render 测试已加(持仓明细 / 类型=已有持仓 / 禁加仓);④ Optional-5 schema 安全旗标入 required(example/fixture 同步)。运行时逻辑未变(前轮已验无 bug)。
- **Required**: `R-ASHORT-ACCOUNT-STATE-RULE12-13-FINALIZE` 全部 Addressed;无新增。详情见 register。
- **Verify**: 全量 1834 OK;git diff --check 干净;tracked diff em 标记=0(em 仍 parked 在 `_em_slice.patch`、未混入);schema required 含两安全旗标 + example 携带。
- **Next**: Codex 提交(账户状态文件;勿 add `_em_slice.patch` / `_diag_web_sources.py` / `m67_validation_20260605`)。

## 2026-06-14 — Codex `修复` (account-state Rule12/13 final test closure)
- **Verdict/Action**: 按 `R-ASHORT-ACCOUNT-STATE-RULE12-13-FINALIZE` 修复提交前阻断:① 更新 `test_markdown_structure` 的 action tally 断言为 `建仓/持有/观察/否决`;② 新增 held+hard_veto→`否决` 安全边界测试,钉住 ST/退市等硬风控优先于 `持有`;③ 新增 `持有` markdown render 测试,覆盖持仓股数/均价/手动止损、`类型=已有持仓`、禁止自动加仓建议。另将账户 schema 的 `manual_order_only` / `broker_connection_allowed` 纳入 required(执行 Optional-5,不改运行行为)。
- **Required**: `R-ASHORT-ACCOUNT-STATE-RULE12-13-FINALIZE` working-tree repaired;等待复审。未触碰 `_em_slice.patch` / `_diag_web_sources.py` / `research/results/a_short/m67_validation_20260605/`。
- **Verify**: targeted 148 OK;py_compile OK;full discover 1813 only 6 known `C:\Users\cnhea\tk.csv` PermissionError(setUpClass imports `A-EGS/egs_main.py`);`git diff --check` 待最终复跑。
- **Pre-Codex self-review**: A/B2/C/E/F checked — 只补 register 指定测试缺口 + schema safety required;无 runtime 逻辑改动,不碰 em parked patch/production EGS/V14.2/broker/order。
- **Next**: 审查。

## 2026-06-14 — Claude `审查` (account-state Rule12/13 + 持有 切片:逻辑 PASS,补测试后可提交)
- **Verdict/Action**: 运行时逻辑正确、无 correctness bug(held/veto 优先级、Rule12/13 flat-block via `hard` 聚合含 stateful_risk、size_multiplier clamp (0,1]、account schema 严格、validate_m67 认 `持有`、account_ref 入默认 lineage)。但未 commit-ready。em 已拆出(`_em_slice.patch`),工作树现为纯账户状态。
- **Required**: `R-ASHORT-ACCOUNT-STATE-RULE12-13-FINALIZE`(详情见 register):①(RED)`test_markdown_structure` 断言补「持有」计数;② **held+hard_veto→否决 安全边界零测试**须补(变 ST/退市的持仓票必 否决 不是 持有);③ `持有` m67_render 路径须补测试。Optional:ts_code 限主板、安全旗标进 required。
- **Verify**: 全量 1832,唯一失败 = `test_markdown_structure`(账户状态自身,非 em);两共享文件 em 标记=0(已拆净);held/veto 优先级、`hard` 聚合含 stateful_risk、size_multiplier clamp 均读码验过。
- **Next**: Codex `修复`(按 register 逐条;**勿 add** `_em_slice.patch` / `_diag_web_sources.py` / `m67_validation_20260605`)。

## 2026-06-14 — Claude `审查` (Codex regime_fallback 文案 cleanup:PASS,提交阻塞未解)
- **Verdict/Action**: PASS。v14_3 §7 切换提醒文案逗号已改全角 `，`(U+FF0C,符用户「中文逗号」要求);纯 doc、engine/pipeline/tests 未动、无 runtime 改动。但此 cleanup **未解决提交阻塞**:scope 仍混装(regime_fallback / cadence 重命名 / v14_3 doc)、cadence 重命名仍待决——与 Codex 本条自述「提交前仍需分拆 scope」一致。
- **Required**: 无新增 Required;register 无新条目;提交前仍须拆 scope + 决定 cadence 重命名(见下方上一条 PASS verdict)。
- **Verify**: governance guard 16 OK;全角逗号 U+FF0C 已核;doc-only(`git diff --stat` 确认 runners/tests/schemas 无本轮新增改动);`?` 仍 ASCII(用户只要求逗号,非阻断)。
- **Next**: 拆 scope 后单独提交 regime_fallback;cadence 重命名 revert 或同步 register。

## 2026-06-14 — Codex `修复` (regime_fallback submit-readiness cleanup)
- **Verdict/Action**: 统一 V14.3 切换提醒文案为用户要求的中文逗号版本;未改 runtime。提交前仍需按上一条 PASS 提醒分拆 scope/staging。
- **Required**: 无新增 Required;关联上一条 PASS 的 submit-readiness cleanup,register 无新条目。
- **Verify**: targeted 236 OK;py_compile OK;route-doc guard 14 OK;old cadence active-surface scan clean;diff-check clean except LF/CRLF warnings。
- **Pre-Codex self-review**: A/B2/E/F checked — 只改活跃 V14.3 提醒文案一致性,不新增 durable gate/状态复述,历史日志/register 旧词不作为本轮 Required。
- **Next**: 审查。

## 2026-06-14 — Claude `审查` (regime_fallback 切片:实质 PASS;混装 cadence-rename/v14_3 doc 待拆)
- **Verdict/Action**: PASS(实质)。regime_fallback = 真安全修复:EGS `unknown`/missing 不再被账户配置抬成进攻期,统一 震荡期 + downgrade + 保守减半 + M6.7 caveat + observe 标记(`resolve_market_regime` + engine classify/build_m67/compute_star 一致)。`compute_star` 的 `hit`→`action=="downgrade"` 经核 overheat/portfolio 命中只设 downgrade = 等价零回归。
- **Required**: 无新增 Required(PASS);register 无 regime_fallback 条目。但**别按现状一把提交**——这批未提交混了 3 个无关 scope(regime_fallback / `out_of_scope_by_weekly_cadence`→`_by_cadence` 重命名 / v14_3 切换提醒文案 doc)。
- **Verify**: 全量 1812 OK(+5 regime 测试);diff-check 干净;关键测试均过(classify→downgrade、build_m67 halve 股数<base+caveat+schema、账户不能覆盖 unknown、resolve 单测);cadence 重命名无 .py/test 引用(不破测试)但 `system_risk_register.md` 4 条历史条目仍用旧词 = 用词不一致。
- **Next**: 提交前拆 scope(regime_fallback 单独 commit)+ 决定 cadence 重命名(revert 或同步 register)+ 归位 v14_3 doc;Optional:`compute_star` 改用 `inp.regime_fallback.active`、补 star 值/缺 market_context 测试。

## 2026-06-14 — Codex `审查 PASS` (Slice 3b-2 R4 + optional hardening)
- **Verdict/Action**: PASS. 覆盖 weekly pipeline / ps1 Stage4 / schema / render / standalone summary CLI 退役 / route docs / doc-governance anti-drift guard / Claude 后续 #1/#2 Optional hardening;未发现新的阻断问题。
- **Required**: `R-ASHORT-WEEKLYSCREENING-M67-BUNDLE-CONTRACT-DRIFT` R4 已 Addressed;无新增 Required。详情见 `docs/system_risk_register.md`。
- **Verify**: targeted 186 tests passed;py_compile passed;schema parse passed;PowerShell ParseFile passed;full discover 1786 only 6 known `C:\Users\cnhea\tk.csv` permission errors;diff-check 仅 LF/CRLF warning;BOM/FFFD `BAD=[]`。
- **Next**: 提交。

## 2026-06-14 — Claude `审查` (Slice 3b-2 self-review:PASS,补 #1/#2 Optional hardening)
- **Verdict/Action**: 完整通读 changeset(pipeline 全文 / ps1 Stage4 / schema / render / 退役 dangling 扫描 / 测试覆盖 + Codex anti-drift governance guard)→ PASS、无阻断。补两处自审 Optional:#1 `validate_weekly_report` 的 run_lineage 一致性收紧为严格双态 `{(provided,sized),(absent,observation_only_no_account)}`(原只查两向、漏矛盾对 (provided,observation_only))+ 加错配测试;#2 对齐 `a_short_weekly_pipeline.py` regime 注释(「待建件」→「尚未生产接线、slice 2a/2b 在建」)与设计文档一致。
- **Required**: 关联 `R-ASHORT-WEEKLYSCREENING-M67-BUNDLE-CONTRACT-DRIFT`(R4 已 Addressed + Codex anti-drift hardened,详情见 register);#1/#2 为自审 Optional、非新 Required。
- **Verify**: 全量 1807 OK(+1 错配测试;稳定 x2、0 fail/0 error);B-ripple grep 无其他 regime「待建」残留;C 反向:收紧不误拒合法对(_weekly 默认 (absent,obs)、main 产 (provided,sized) 均过);git diff --check 干净。
- **Next**: 审查(新代码 #1/#2 交 Codex 复审)。

## 2026-06-14 — Codex `修复` (R4 anti-drift:active design completed-vs-future guard)
- **Verdict/Action**: 补机制防线,不是再补一个措辞:`tests/test_doc_governance_guard.py` 新增 current-fact registry、代码/route anchor 校验、活跃设计文档 future-work 扫描和 planted failure;`docs/pre_codex_self_review_checklist.md` 新增活跃设计文档 current-state gate。零 runtime 改动。
- **Required**: `R-ASHORT-WEEKLYSCREENING-M67-BUNDLE-CONTRACT-DRIFT` R4 anti-recurrence extension;详情见 `docs/system_risk_register.md`。
- **Verify**: targeted 185 tests OK;`git diff --check` 只有 LF/CRLF warning;PowerShell ParseFile OK;新增文件 BOM/FFFD `BAD=[]`;`research/results/a_short/m67_validation_20260605/` 仍 untracked。
- **Pre-Codex self-review**: A/B2/C/E/F checked — 把 completed-vs-future 漂移类沉淀成 registry+guard;guard 正向钉 anchors、负向钉未来项、不误杀真实 pending regime;历史/低影响文本不纳入 Required。
- **Next**: 审查。

## 2026-06-14 — Claude `修复` (Slice 3b-2 R4:weekly-design remaining-work drift)
- **Verdict/Action**: weekly pipeline 设计 §5 把已接线的 Slice A overlay 数据装载(M6.7 赛道红利星级)从「仍未来」改为「已接线」(probe 证实:egs_main:3318 `build_overlay_summary_from_panels`→overlay.json、ps1:218 传 `--overlay`、pipeline:331 `_load_validated_overlay` 消费),仍未来仅留真未决的 EGS regime 分类器;并修 §4 line 44 内部矛盾(首次端到端执行已发生、artifact 在 m67_validation_20260605)→ 仍未来 scope 到每周常态 cadence + ≥12周/12月 ship-gate 前向验证。零 runtime 改动。
- **Required**: `R-ASHORT-WEEKLYSCREENING-M67-BUNDLE-CONTRACT-DRIFT` R4;详情见 register。
- **Verify**: 全量 1803 OK(+1=overlay-done 回归守护);active grep overlay-as-future 全仓=0(假阳:拒未来日期 / 绝不混写);git diff --check 干净;m67_validation byproduct 仍 untracked;ps1 未改、ParseFile 维持 0。
- **Next**: 审查。
- **Pre-Codex self-review**: 这次先跑 reviewer 探针——读全份设计文档逐条 future-claim 对现实核(非只改被点名句),probe 代码确认 overlay 真接线、看 artifact 确认首跑真发生;B 连带 grep 全活跃文档无其他 overlay-future;C 反向(守护正向断言 `--overlay` 在场 + 负向钉「仍未来」无 overlay,不假过);boundary=docs+1 测试、零 runtime。

## 2026-06-14 — Codex `审查 FAIL` (Slice 3b-2 R4:weekly-design remaining-work drift)
- **Verdict/Action**: FAIL. R3 的 run_lineage/account/path 文档修复通过,但同一个活跃 weekly pipeline 设计文档 §5 仍把已完成的 Slice A overlay 数据装载/M6.7 赛道红利接线列为未来工作,会误导下一步判断。
- **Required**: `R-ASHORT-WEEKLYSCREENING-M67-BUNDLE-CONTRACT-DRIFT` R4 remains open; details in `docs/system_risk_register.md`.
- **Verify**: targeted 181 tests OK; full discover only hits known `C:\Users\cnhea\tk.csv` permission boundary (6 errors); PS ParseFile OK; diff-check clean except LF/CRLF warnings; validation artifacts remain untracked.
- **Next**: Claude `修复`。

## 2026-06-14 — Claude `修复` (Slice 3b-2 R3:active path+weekly-design contract sync)
- **Verdict/Action**: blanket「同桶/M6.7 同桶」scope 到选股+EGS comparison(run_paths docstring + convention §动因/§1);周报 M6.7 落点改述「按流分」(分析流同桶 / 生产 hybrid 靠 run_lineage);weekly pipeline 设计 §3 加 required `run_lineage`(5 子字段)+ §3 不变量 + §5 account 语义重写(valid→sized / 坏路径→跳 M6.7 / 缺省→observation-only artifact+banner / 非法 available_cash→FATAL);零 runtime 改动。
- **Required**: `R-ASHORT-WEEKLYSCREENING-M67-BUNDLE-CONTRACT-DRIFT` R3;详情见 register。
- **Verify**: 全量 1802 OK(+1=doc↔schema 守护 `test_weekly_design_doc_documents_schema_required_run_lineage`);残留 blanket-同桶/旧 available_cash 全仓 grep=0;PS ParseFile 0 errors 无 BOM;git diff --check 干净;m67_validation byproduct 仍 untracked 未 staged。
- **Next**: 审查。
- **Pre-Codex self-review**: A 一次覆盖全类(blanket-同桶=run_paths+convention;旧 schema/account=weekly_design §3+§5);B 连带 grep(iv_feed_ref/a_short_weekly_report→README route 行只指 schema 不复述、不动;industry_heat 11/36=comparison 真同桶、不动;收紧 dangling §-ref);C 反向(守护断言 5 子字段在场非缺席、不假过);boundary=docs+1 测试、零 runtime。

## 2026-06-14 — Codex `审查 FAIL` (Slice 3b-2 R3:active path+weekly-design contract sync)
- **Verdict/Action**: FAIL. Runtime/account/run_lineage 修复本身通过 targeted 行为测试,但活跃契约面仍不同步:run-bundle/path 总述仍保留 blanket same-bucket/M6.7 同桶说法,weekly pipeline 设计文档仍列旧 schema 且未记录当前 account_status/sizing_mode 语义。
- **Required**: `R-ASHORT-WEEKLYSCREENING-M67-BUNDLE-CONTRACT-DRIFT` R3 remains open; details in `docs/system_risk_register.md`.
- **Verify**: targeted 180 tests OK; active doc scan found stale claims in `engine/a_short_run_paths.py`, `docs/a_short_run_bundle_convention_20260611.md`, and `docs/a_short_weekly_pipeline_design_20260610.md`; no runtime change made.
- **Next**: Claude `修复`。

## 2026-06-14 — Claude `修复` (Slice 3b-2 R2:account artifact 标 + run_lineage 闭合)
- **Verdict/Action**: ① ps1 三态(有效 -Account→真 sizing / 坏路径→跳过 M6.7 不静默 / 缺省→observation-only);pipeline 把 durable `run_lineage.sizing_mode`+`account_status` 写进 weekly_m67.json + .md no-sizing banner(读 artifact 即知 sizing 假象),并拒非法 available_cash。② schema 化 `run_lineage`(analysis_input/selection_bucket/iv_feed/account_status/sizing_mode)绑 selection↔M6.7 + validate 校验 + convention 匹配实际字段。③ 删温件、validation artifacts 明确不追踪。详情见 register。
- **Required**: `R-ASHORT-WEEKLYSCREENING-M67-MISSING-ACCOUNT` + `R-ASHORT-WEEKLYSCREENING-M67-BUNDLE-CONTRACT-DRIFT` — R2 Addressed 见 `docs/system_risk_register.md`。
- **Verify**: 全量 1801 tests OK(行为 account 测试:有账户 sized+建仓 / 无账户 observation+观察+.md banner / 坏 cash SystemExit;render banner;guardrails 坏路径);PS 5.1 ParseFile 0;BOM/FFFD=0;diff-check 净;无 root 温件。
- **Pre-Codex self-review**: A-F checked — A 两 Required×全出口(ps1/pipeline/schema/render/convention/3 测试)一次覆盖,**行为测试非仅静态串**;B grep 无旧 lineage 假声明/温件残留;C 反向自检 坏路径跳过(非静默)、默认 run_lineage 保旧 builder/测试 valid、render 无 lineage 优雅;F ps1 parse/编码/diff/git-status 净。
- **Next**: `审查`。

## 2026-06-14 — Codex `审查 FAIL` (Slice 3b-2 R2:account artifact + lineage closure gap)
- **Verdict/Action**: FAIL. `-Account` 只在路径存在时传给 M6.7;坏路径会落入无账户分支继续跑,且无账户 warning 只在终端,`weekly_m67.json/.md` 本身没有 no-sizing 标记,仍会把可建仓票渲染成 `观察`。bundle 侧文档声称 `weekly_m67.json` 记录 analysis_input/iv-feed lineage,但实际 schema/report 只有 basename `iv_feed_ref`,没有 analysis_input/account/selection-bucket lineage。另有 root 临时 `_fix_bundle_docs.py` 未清。
- **Required**: `R-ASHORT-WEEKLYSCREENING-M67-MISSING-ACCOUNT` + `R-ASHORT-WEEKLYSCREENING-M67-BUNDLE-CONTRACT-DRIFT` remain open; see Codex re-review correction in `docs/system_risk_register.md`.
- **Verify**: targeted 169 tests OK; no-network probe confirmed no-account artifact `has_no_sizing_text=false` while action changes from `建仓` to `观察`; `git diff --check` clean except LF/CRLF warnings; git status still has untracked `_fix_bundle_docs.py` + validation artifacts.
- **Next**: Claude `修复`.

## 2026-06-14 — Claude `修复` (Slice 3b-2 P1:M6.7 缺账户 sizing + bundle 契约漂移)
- **Verdict/Action**: ① `weekly_screening.ps1` 加 `-Account`(给则传 `--account`、不给则**响亮标** no-sizing observation-only,不再静默把 建仓 误显成 观察)+ guardrails 测试钉死;② bundle 契约定为**有意 hybrid**(egs_main 选股→`result/a_short`、M6.7 advisory→research lane、weekly_m67 记 lineage),改 run_paths.py/convention/runners-README 删"生产流本就不跑 pipeline"假命题;ps1 IV feed 移到 convention 的市场级 `iv_feed_<as_of>/`。详情见 register。
- **Required**: `R-ASHORT-WEEKLYSCREENING-M67-MISSING-ACCOUNT` + `R-ASHORT-WEEKLYSCREENING-M67-BUNDLE-CONTRACT-DRIFT` — Addressed 见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: 全量 1795 tests OK(含 guardrails 账户 guard);PS 5.1 ParseFile 0 errors;BOM/FFFD=0;diff-check 净。
- **Pre-Codex self-review**: A-F checked — A 两 Required×出口(ps1/run_paths/convention/README/test)一次覆盖;B grep 无残留"生产流不跑 pipeline"/旧 Stage-4 调用;C 反向自检 -Account 缺失不再静默(响亮标)、egs_main/生产桶/护栏未动、ps1 CRLF+parse 0;E 路由文档单态(hybrid 已 documented);F 编码/diff/parse 净。
- **Next**: `审查`。

## 2026-06-14 — Codex `审查 FAIL` (Slice 3b-2:weekly_screening M6.7 一键串联)
- **Verdict/Action**: FAIL. Slice 3b-2 方向正确,但当前一键周报路径有两个提交前阻断: M6.7 没传账户 sizing 输入; 路径/文档仍按旧边界写,导致 selection 与 M6.7 artifacts 分散且契约自相矛盾.
- **Required**: `R-ASHORT-WEEKLYSCREENING-M67-MISSING-ACCOUNT` + `R-ASHORT-WEEKLYSCREENING-M67-BUNDLE-CONTRACT-DRIFT`; details in `docs/system_risk_register.md`.
- **Verify**: targeted 168 tests OK(说明现有 guard 漏检); PS ParseFile OK; `git diff --check` clean; no-network repro showed same candidate with account = `建仓`, without account = `观察` / `可建股数/金额不足(放弃)`.
- **Next**: Claude `修复`.

## 2026-06-14 — Claude `起草` (Slice 3b-2:退役独立 summary CLI/Stage-4 + weekly_screening 一键串联)
- **动机**: 3b-1 行内化 + `执行`(M6.7 端到端验证通过)后,3b-2 前置已满足;本轮收口最后的过渡组件。
- **改动(本地,未提交)**:
  - `weekly_screening.ps1` Stage-4(原跑独立 summary)→ **M6.7 一键串联**:egs_main 成功后建市场 IV feed(`a_short_iv_feed_build`)+ 跑 `a_short_weekly_pipeline`(真 price+cninfo+sina+DeepSeek,语义逐票行内),落 research lane;advisory 旁路非阻断(同 canary/tracker),`-SkipSemanticRisk` 可关;**CRLF 保留、PS 5.1 ParseFile 0 errors**。
  - `a_short_semantic_risk_summary.py` 退役 standalone CLI(`main` + `write_summary` + `_watch_pool_from_analysis_input` + 随之 unused 的 argparse/datetime/jsonschema/SCHEMA_PATH/4 个 probe import)+ docstring 去 CLI 口径;**保留** M6.7 复用的 builders(`build_summary_from_fetches`/`build_official_structured`/`_sina_sources`/`_web_llm_consistency_error` 等)。
  - 测试:删 summary 的 `WritePath` + `AnalysisInputWatchPoolWiring`(CLI 测试)+ 加 `test_standalone_summary_cli_retired`;contract-docs 加 `test_weekly_screening_runs_m67_not_standalone_summary`(钉 ps1 跑 M6.7、不再调 standalone)。
  - docs:contract/coverage/README 标 standalone CLI + Stage-4 退役、weekly_screening 跑 M6.7(过渡路全退役);coverage 修 watch-pool 引用(`_watch_pool_from_analysis_input` 已删)。
- **保留(反向自检)**:egs_main / 生产 screening 输出(`result/a_short`)不动;M6.7 advisory 仍落 research lane、非阻断;独立 summary 的 builders 留(M6.7 cninfo provider 复用)。
- **Verify**: 全量 1794 tests OK;ps1 PS 5.1 ParseFile 0 errors + CRLF + 无 BOM/FFFD;全仓 grep 无 standalone-CLI 符号 stale 引用(coverage 35 已修);diff-check 净。
- **Pre-Codex self-review A-F**: A 退役类×全出口(summary.py / ps1 / tests / docs / guard)一次覆盖;B ripple grep 0 stale(`_watch_pool`/`write_summary`/standalone call);C 反向自检——egs_main/生产输出/builders 复用未动、ps1 advisory 非阻断保留、ps1 调的是 `执行` 已验证的命令;E 路由文档单态(3b-2 done、无 pending);F ps1 CRLF+parse / 编码 / diff 净。
- **Next**: `审查`。

## 2026-06-14 — Claude `执行` (M6.7 端到端真跑验证:cninfo + DeepSeek 融入)
- 真跑(research lane 非生产;as_of 20260605 复用既有 EGS analysis_input;artifacts 在 `research/results/a_short/m67_validation_20260605/`,**未提交**——一次性 plumbing 验证、可复跑):现建 PIT IV feed(`a_short_iv_feed_build`,n_days=282,latest_iv_pct=65.5)→ `a_short_weekly_pipeline --confirm-fetch-authorized`(真 Tushare 价 + cninfo + sina + DeepSeek),n=15 全观察。
- **验证结论(多票横截面)**:
  - ✅ **cninfo official_structured**:真 PIT 取数+分类+融入引擎——15 票 = 6 clear / 9 risk(全 impact=pending 待核;无证据齐全 high → 不否决,故全 15 观察,符合 advisory 不硬杀)。
  - ✅ **DeepSeek 判官**:直测确认本体工作(`deepseek_layer_status` 全 True;对合成"立案调查"新闻判出 `risk/high/downgrade` + 中文 summary,契约合规)。
  - ✅ **M6.7 端到端 + 3b-1 行内渲染**:price+IV+engine+render 无中止;weekly.md 15 行语义明细格式正确(官方/web 行内)。
  - ⚠️ **管线内 web 层全 unknown**:**sina 连通正常(ok=True、无 error)但这 15 票 items=0**(确无近期 sina 新闻命中)→ web 层正确 fail-closed 成中性、非阻断(设计行为)。即 DeepSeek 判官已单验,但管线内本次未喂到真 sina 文本。**待查(非阻断)**:sina 对全 15 票均 0 命中是真空还是 parse/endpoint 低产,值得后续看一眼。
- **意义**:Slice 3b-2 的前置(M6.7 端到端真跑)已过 —— cninfo+DeepSeek 融入工作、fail-closed 正确。
- **Next**: 可 `起草 Slice 3b-2`(独立 summary/Stage-4 退役 + weekly_screening 一键串联);Slice-3 promotion 仍按 ~4 周真实 advisory 证据门槛(本次为 plumbing 验证、web 空,非 forward 证据第一笔)。

## 2026-06-14 — Claude `提交` (Slice 3b-1:语义面板行内化进 M6.7)
- 提交(本地 master,无 push):语义 advisory 逐票**行内化**进 M6.7 周报 .md(`a_short_m67_render._semantic_line` 从 `machine.layer.semantic_risk` 渲染);退役独立面板渲染路径(`render_semantic_risk_panel` + 仅其用 helper / `_semantic_panel_from_summary` / `--semantic-risk-summary` / `write_weekly_markdown` semantic_panel 参数)。测试:+3 行内测试;退役 panel-gate 单一来源 guard → panel-retired guard;docs coverage/contract/README 改 panel 退役·行内化。
- Codex `审查 PASS`(Required none)。全量 1799 tests OK;活跃 runners/schemas 零面板引用;编码/diff 净。
- 保留(= **Slice 3b-2**,待 `执行` 验证 M6.7 后):独立 summary + weekly_screening Stage-4 退役 + 一键串联(需 IV feed + 真抓价,M6.7 端到端未验证,盲接投机)。
- **Next**: `执行` 验证 M6.7(cninfo+DeepSeek+IV+价格 端到端)→ 再 `起草 Slice 3b-2`。

## 2026-06-14 — Codex `审查 PASS` (Slice 3b-1:语义面板行内化进 M6.7)
- **Verdict/Action**: PASS. 语义 advisory 已从独立 weekly 面板改为逐票行内渲染到 M6.7 markdown;旧 `_semantic_panel_from_summary` / `--semantic-risk-summary` / `render_semantic_risk_panel` 生产入口已退役,活跃面未见旧面板入口残留。
- **Required**: none.
- **Verify**: 152 semantic/weekly/DeepSeek/doc tests OK; doc-governance/route tests 27 OK; full unittest discover 1799 OK(非沙箱复跑;沙箱内仅命中已知 `C:\Users\cnhea\tk.csv` 权限边界); py_compile OK; semantic schemas parse OK; active old-panel scan clean except retired-symbol absence assertions; `git diff --check` clean except LF/CRLF warnings; BOM/FFFD=0.
- **Next**: Claude `提交`.

## 2026-06-14 — Claude `起草` (Slice 3b-1:语义面板行内化进 M6.7 + 退役独立面板渲染)
- **动机/切分**: 读码发现 3b 的"一键串联"需 `a_short_weekly_pipeline.main` 端到端跑(要 `--iv-feed` 独立产物 + 真 Tushare 抓价 + account——weekly_screening 都没有),而 M6.7 端到端从没在真数据上跑过。盲接重管线进周五生产入口=投机必生轮次。故 3b 拆:**3b-1(本轮,安全解耦)= 面板行内化 + 删独立面板渲染**(纯渲染、不碰 IV/价格/ps1);**3b-2(待一次 `执行` 验证 M6.7 后)= 独立 summary/Stage-4 退役 + weekly_screening 一键串联**。
- **改动(本地,未提交)**: `a_short_m67_render` 加 `_semantic_line`——逐票从 `machine.layer.semantic_risk` 行内渲染语义 advisory(官方 status/severity/事件/impact + web status/level/action/源/impact/已中性化),`write_weekly_markdown` 去 `semantic_panel` 参数;`a_short_weekly_pipeline` 删 `_semantic_panel_from_summary` + `--semantic-risk-summary` + main 面板接线;`a_short_semantic_risk_summary` 删 `render_semantic_risk_panel` + 仅其用的 `_needs_manual_review`/`_max_severity`/`_SEVERITY_RANK`。测试:m67_render 加 3 行内测试(有 machine→渲染、invalid_neutralized 显示、无 machine→不渲染不崩);删 summary `Panel` 类 + weekly 的 panel/`--semantic-risk-summary` 测试;contract-docs **退役 panel-gate 单一来源 guard**(面板没了即 obsolete)→ 换 `test_semantic_panel_retired_inline_in_m67`(断言面板符号/flag 已删 + 渲染器带 `_semantic_line`)。docs coverage/contract/README 改 panel 退役·行内化、标 独立 summary/Stage-4 = 3b-2。
- **保留(反向自检)**: 独立 `a_short_semantic_risk_summary` + weekly_screening Stage-4 **不动**(= 3b-2,删了会让周五无语义);M6.7 fold-in(Slice 1/1b/2)+ `_web_llm_consistency_error` + engine 全不动(纯渲染层改)。语义结论(否决/降级)本就 inline(否决审查触发/风控触发),本轮加的是**明细**行。
- **Verify**: 全量 1799 tests OK(面板测试 -15、行内测试 +3);全仓 grep:活跃 runners/schemas 零面板引用,仅剩 panel-retired guard 断言其不存在;BOM/FFFD=0;diff-check 净(仅 LF/CRLF 警告)。
- **Pre-Codex self-review A-F**: A 缺陷类(面板渲染路径)×全出口(renderer/consumer/param/tests/docs)一次覆盖 + 行内替代加测;B ripple grep 0 活跃残留;C 反向自检——语义可见性不丢(行内化加明细)、独立 summary/Stage-4 保留不致周五无语义、无-machine 老报告优雅不崩;E coverage/contract/README 单态(panel 退役);F 编码/diff/ast 净。
- **Next**: `审查`。

## 2026-06-14 — Claude `提交` (Slice 3a 退役 skill-patch + doc-drift 收敛)
- 提交(本地 master,无 push):Slice 3a 退役 2b-ii web_llm skill-patch 路径(删 patch schema + skill-prompt + validate/apply_web_llm_patch;schemas/coverage/contract/README/adapter/summary 去 skill/patch 措辞;web_llm 不变式重锚到共用 `_web_llm_consistency_error`);drift guard 从短语黑名单重构为退役词根 vocabulary(SPECIFIC + GENERIC web_llm 语境 + 标记豁免、域限定 glob);doc-drift materiality gate(AGENTS 15a + closeout + checklist B2)。
- closes `R-ASHORT-SEMANTIC-SLICE3A-RETIRED-SKILLPATH-ACTIVE-SURFACE-DRIFT`(register round-1/2/4 三条翻 resolved;over-broad round-4 留 superseded)。4 轮收敛轨迹:全删 → 词根重构 → materiality 收窄到 1 个 material route-doc 声明。
- 保留(非本 scope):独立 summary / 面板 / Stage-4 = Slice 3b(单独切片,M6.7 验证后);6 个分类 prompt(`egs_main` 生产在用)。
- **Next**: Slice 3b 退役收口(面板行内化 + 独立 summary/Stage-4 退役 + weekly_screening 一键串联)= 真正消除剩余过渡面,待用户 `起草`;建议先 `执行` 验证 M6.7+DeepSeek。

## 2026-06-14 — Codex `审查 PASS` (Slice 3a round-4:materiality-corrected)
- **Verdict/Action**: PASS. Required README live-contract drift is fixed; materiality gate is documented; non-impact stale prose is non-blocking/Optional under the new rule.
- **Required**: `R-ASHORT-SEMANTIC-SLICE3A-RETIRED-SKILLPATH-ACTIVE-SURFACE-DRIFT` addressed; see `docs/system_risk_register.md`.
- **Verify**: 1814 tests OK; targeted semantic/weekly/doc tests OK; py_compile OK; schemas parsed; active patch-merge route-doc no hits; diff-check clean except LF/CRLF warnings.
- **Next**: Claude `提交`.

## 2026-06-14 — Claude `修复` (Slice 3a round-4:README patch-merge-whitelist 活契约声明)
- **Verdict/Action**: 按 materiality 收窄,只修 Required = `docs/README.md` 契约锚点行删 `patch merge whitelist`(§Patch Merge 已 Slice 3a 退役,patch schema/prompt/函数均删);guard SPECIFIC 加 `patch merge`/`merge whitelist` 补 route-doc gap + planted;Optional 顺手清 summary 测试 stale docstring。详情见 register。
- **Required**: `R-ASHORT-SEMANTIC-SLICE3A-RETIRED-SKILLPATH-ACTIVE-SURFACE-DRIFT` — round-4 Addressed 见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: 全量 1814 tests OK;guard 12 OK(含 patch-merge planted);active route-doc 扫描无未标记 patch-merge 声明;BOM/FFFD=0;diff-check clean。
- **Pre-Codex self-review**: A-F checked — A README + guard 一次覆盖该类;B 全仓扫 patch merge/whitelist 0 未标记残留;C 反向自检 `patch merge` 为特定短语、不误伤 Codex-patch / merge_rows;E README 路由行单态;F 编码/diff 净。
- **Next**: `审查`。

## 2026-06-14 — Codex `审查 FAIL` (Slice 3a round-4:materiality-corrected)
- **Verdict/Action**: FAIL, but narrowed by user materiality direction. Non-impact doc drift is non-blocking; stale test prose is Optional/non-blocking. Required is only the active `docs/README.md` route-doc `patch merge whitelist` live-contract claim.
- **Required**: `R-ASHORT-SEMANTIC-SLICE3A-RETIRED-SKILLPATH-ACTIVE-SURFACE-DRIFT` materiality-corrected Round-4 entry in `docs/system_risk_register.md`.
- **Verify**: active scan still hits `docs/README.md:76`; `tests.test_a_short_semantic_risk_contract_docs` 12 OK shows the route-doc guard gap; `git diff --check` clean except LF/CRLF warnings.
- **Next**: Claude `修复`.

## 2026-06-14 — Claude `修复` (Slice 3a round-3:散文收口 + guard 词根 vocabulary 重构)
- **Verdict/Action**: summary.py 6 处 + coverage 2 处旧 skill/patch 散文 → web_llm advisory / 指针(full-file grep:summary.py 净、coverage 仅退役标记行);guard 按 Codex-agreed 优化思路重构为退役词根 vocabulary(SPECIFIC 无需语境 + GENERIC 仅 web_llm 语境;bare skill/patch 不用——避 us_short/Codex-patch/checklist 误伤)+ glob 域限定(a_short_semantic_risk_* + README + weekly + 语义 runners);checklist stale 示例去 skill 耦合。详情见 register。
- **Required**: `R-ASHORT-SEMANTIC-SLICE3A-RETIRED-SKILLPATH-ACTIVE-SURFACE-DRIFT` — 完整 Addressed(round-3)见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: 全量 1814 tests OK;guard 12 OK(含 round-3 变体 planted + 跨域非误伤 planted);广域闭环扫描活跃面零未标记退役引用(余 4 命中均带 退役/SUPERSEDED 标记或权威/design tier);BOM/FFFD=0;diff-check clean。
- **Pre-Codex self-review**: A-F checked — A 缺陷类(retired 散文)×全出口(summary.py/coverage 全实例 grep 清,非只修点名);B 广扫旧词根+变体 0 未标记残留;C 反向自检 bare 词撤回避误伤、域限定避跨域、活不变式+48h-token 保留;F JSON/编码/diff 净。
- **Next**: `审查`。

## 2026-06-14 — Codex `审查 FAIL` (Slice 3a 5 面修复复审:summary/coverage 活跃残留)
- **Verdict/Action**: FAIL. 5 个被点名面本身修对了(schema descriptions、coverage 16/17、contract 48h、adapter 注释、schema guard),但 closure 不成立:活跃 `summary.py` 与 coverage 仍有旧 skill/patch 口径,且 guard 没覆盖这些变体。
- **Required**: `R-ASHORT-SEMANTIC-SLICE3A-RETIRED-SKILLPATH-ACTIVE-SURFACE-DRIFT` — 复审修复要求已追加到 `docs/system_risk_register.md`(单一来源)。
- **Verify**: semantic contract/summary/probe/slice3 tests 111 OK; weekly/DeepSeek adapter tests 104 OK; doc-governance/route tests 27 OK; py_compile OK; two schema JSON parse OK; `git diff --check` clean. Broader active scan still hit `runners/a_short_semantic_risk_summary.py` lines 56/84-86/237/366 and `docs/a_short_semantic_risk_coverage.md` lines 22-23.
- **Proof-of-use**: Re-review used current worktree diff, targeted tests, schema JSON parse, `git diff --check`, and broad active-surface `rg`; full repair detail is stored only in the register.
- **Next**: Claude `修复`.

## 2026-06-14 — Claude `修复` (Slice 3a 退役 skill-patch:活跃 schema/docs 残留收口)
- **Verdict/Action**: Codex 点的 5 活跃面残留全收(2 schema description + coverage 16/17 + contract 48h + adapter 注释 → 指针 / 当前 web_llm advisory 措辞),guard 加扫 `schemas/a_short_semantic_risk_*.schema.json` + 补 4 变体 + schema-desc planted。详情见 register。
- **Required**: `R-ASHORT-SEMANTIC-SLICE3A-RETIRED-SKILLPATH-ACTIVE-SURFACE-DRIFT` — 完整 Addressed 详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: 全量 1814 tests OK;guard 12 OK(schema 扫描 + schema-desc planted + 48h-overclaim);两 schema JSON valid;BOM/FFFD=0;diff-check clean;闭环扫描活跃面净(唯一 design-doc DESIGN-tier inline-superseded,合规)。
- **Pre-Codex self-review**: A-F checked — A 缺陷类×全出口(schema/coverage/contract/注释/guard)一次覆盖;B 闭环 grep 0 残留;C 48h-token/schema-JSON/活不变式保留;F JSON/编码/diff 净。
- **Next**: `审查`。

## 2026-06-14 — Codex `审查 FAIL` (Slice 3a 退役 skill-patch 路径:活跃 schema/docs 残留)
- **Verdict/Action**: FAIL. 方向正确:patch schema / skill prompt 已删除,`validate_web_llm_patch`/`apply_web_llm_patch` 已移除,DeepSeek/M6.7 目标测试仍过。但活跃 schema/docs/comment 仍残留旧 `skill-in-loop` / `Slice-2b skill to fill` / `2b-ii-B skill prompt` 口径,且当前 guard 没扫 schema descriptions、也没覆盖这些变体。
- **Required**: `R-ASHORT-SEMANTIC-SLICE3A-RETIRED-SKILLPATH-ACTIVE-SURFACE-DRIFT` — 完整修复要求见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: semantic contract/summary/probe/slice3 tests 111 OK; weekly/DeepSeek adapter tests 104 OK; doc-governance/route tests 27 OK; py_compile OK; `git diff --check` clean. Residual scan excluding SESSION_LOG/register/archive hit active `schemas/a_short_semantic_risk_summary.schema.json`, `schemas/a_short_semantic_risk_probe_summary.schema.json`, `docs/a_short_semantic_risk_coverage.md`, `docs/a_short_semantic_risk_contract.md`, and `runners/a_short_deepseek_semantic_adapter.py`.
- **Next**: Claude `修复`.

## 2026-06-14 — Claude `起草` (Slice 3a 退役 skill-patch 路径)
- **动机**: 用户定向"退役过渡组件"。读码发现退役分两半:**3a(本轮,解耦)= 退役 2b-ii skill-patch 路径**(被 Slice 2 DeepSeek adapter 取代,M6.7 从不用 patch);**3b(后续,耦合+生产相邻)= 面板行内化 + 独立 summary/Stage-4 退役 + weekly_screening 一键串联**(需读 engine 报告 schema、改生产 ps1,最好待 M6.7 真跑验证后)。面板/独立 summary 非纯冗余(显语义明细),故不在 3a 删。
- **改动(8 文件,本地,无 push)**: 删 `schemas/a_short_semantic_risk_web_llm_patch.schema.json` + `skills/a_short_analysis/prompts/semantic_risk_web_llm.md`;`summary.py` 去 `validate_web_llm_patch`/`apply_web_llm_patch` + PATCH_SCHEMA 常量 + `import copy` + docstring 收指针;summary 测试删 `WebLlmPatch` 类 + 其 helper,加退役防回归测试;guard 行为锚从死 `validate_web_llm_patch` **重指到活 `_web_llm_consistency_error`**(DeepSeek adapter/engine 在用)、删读已删文件的两测试、BANNER tier 置空、panel-gate expect 去 skill-prompt;契约 §web_llm 产出路径 transitional 去 skill-patch + 删已死的 §Patch Merge;coverage 2b-ii-A patch 节 → 不变式单一来源指针 + 删 skill 层 bullet(panel bullet 留 3b);README 路由行去两删文件 + lineage 去 patch-contract。
- **保留(反向自检)**: `_web_llm_consistency_error`、`render_semantic_risk_panel`/`_semantic_panel_from_summary`/`--semantic-risk-summary`(3b)、`build_official_structured` 等复用件、6 个分类 prompt(生产 `egs_main` 在用)、slice3-guard 的 production-reconciliation tracker(gated promotion,不动)。
- **Verify**: 全量 **1814 tests OK**;退役防回归测试断言 patch 符号/文件已 gone + 不变式仍由 `_web_llm_consistency_error` 强制;契约外 grep 残留全为预期(契约退役命名 / 防回归测试 / register 历史 / research 旧 artifact);6 编辑文件 BOM/FFFD=0;git status 8 项净(4M+2D+2M)。
- **Pre-Codex self-review A-F**: A 缺陷类×全出口一次覆盖(code/schema/prompt/tests/docs/guard);B 连带 grep 旧符号+文件名全仓清,category prompts 确认生产仍用故保留;C 反向自检活不变式/面板 3b/slice3-guard 未误删,re-anchor 保不变式覆盖不漏报;E 单一来源:契约仍权威、退役只减面不增叙述;F .py 编译 / .md 编码 / diff 净。
- **未删(说明)**: `research/results/a_short/semantic_risk_20260605/{panel.md,summary.json,web_llm_patch.json}` = 过去运行的历史研究数据(非生产 lane、非代码依赖),退役只动代码/文档故保留。
- **Next**: `审查`。

## 2026-06-14 — Claude `提交` (语义 doc 单一来源 refactor)
- 提交单一来源 refactor(本地 master,无 push):契约 §web_llm 产出路径 = web run-path 唯一来源;coverage/README/weekly_screening/summary/probe 收成纯指针(README 5 切片行并 1 行);design doc 行内 + skill-prompt 文件级 supersession;guard 三 tier(STRICT glob route/runner per-line、DESIGN 设计行内、BANNER 组件 prompt 文件级)。
- closes `R-ASHORT-SEMANTIC-WEBLLM-RUNPATH-SINGLE-SOURCE-GUARD-GAP`(register 三条翻 resolved)。
- 残留 stale-open(**非本提交 scope**):`R-ASHORT-M67-DEEPSEEK-WEBLLM-SEPARATE-RUN-DOC-DRIFT` 旧 corrections(其 producer-class guard 已被本 refactor superseded)+ 2 条 deferred roadmap——留下一轮 register 卫生。
- **Next**: 用户已定方向——真正消除剩余多面叙述靠 **Slice 3 退役过渡组件**(删独立 summary/skill/面板/Stage-4),非继续守 N 面;doc-drift 守护标准已够(主路由+行为+过渡打标)。

## 2026-06-14 — Codex `审查 PASS` (语义单一来源 R8:prompt banner + 三层 guard)
- **Verdict/Action**: PASS. R8 的 active prompt 漏扫已补:prompt 顶部有过渡/Slice-3 退役 banner + `§web_llm 产出路径` 指针,Purpose 行也明确 NOT current run-path;guard 现在覆盖 STRICT route/runner、DESIGN inline-superseded、BANNER component-prompt 三类 surface。
- **Required**: `R-ASHORT-SEMANTIC-WEBLLM-RUNPATH-SINGLE-SOURCE-GUARD-GAP` — 可随本次提交关闭;完整详情见 `docs/system_risk_register.md`。
- **Verify**: semantic contract/summary/probe/slice3 tests 125 OK; weekly/adapter tests 104 OK; doc-governance/route tests 27 OK; `git diff --check` clean; `weekly_screening.ps1` parse OK;py_compile OK;STRICT/DESIGN offenders=0;BANNER prompt has pointer+transitional marker;active scan only leaves allowed superseded design + banner prompt + test fixtures。
- **Next**: Claude `提交`。

## 2026-06-14 — Claude `修复` (语义单一来源 R8:skill-prompt banner + guard 加 BANNER tier)
- **Verdict/Action**: 又一面 = skill prompt(.md,不在 runners glob)仍写 skill-in-loop/do LIVE judgment、未标过渡未指 run-path。它是组件自身指令(全篇讲 skill),不能 per-line STRICT。本轮:prompt 顶加**文件级 supersession banner**(过渡/transitional/Slice 3 + §web_llm 产出路径 指针)+ Purpose 行加行内过渡边界 + 指针;guard 加 **BANNER tier**(`BANNER_SUPERSEDED_SURFACES` 文件须含指针 + 过渡标记)+ planted(无 banner 红 / 有 banner 绿)。
- **Required**: `R-ASHORT-SEMANTIC-WEBLLM-RUNPATH-SINGLE-SOURCE-GUARD-GAP` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: STRICT/DESIGN offenders=0;banner ptr+transitional ✓;active 扫描残留 skill-in-loop 仅 design(inline-superseded)+ prompt(banner-superseded);272 tests OK;diff-check clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A:三类 surface tier 齐(STRICT route per-line glob / DESIGN inline-pointer / BANNER 组件文件级)覆盖 doc/runner/prompt 全类;B:active 全仓扫,残留只在两个带 supersession 的历史/组件文件;C:BANNER 文件级不误伤(prompt 全篇是 skill 内容)、planted 双向;F:diff/BOM 净。**注**:该 finding 第 8 轮——面类(doc/runner/prompt)现三 tier 全覆盖。
- **Next**: `审查`。

## 2026-06-14 — Codex `审查 FAIL` (语义单一来源 R8:skill prompt 漏扫)
- **Verdict/Action**: FAIL. probe/README 漏面已修,guard glob 也覆盖了 semantic-risk runners;但 active prompt `skills/a_short_analysis/prompts/semantic_risk_web_llm.md` 仍本地写 `skill-in-loop` / "do LIVE web/LLM judgment",没有标为过渡组件并把 run-path 指回契约。
- **Required**: `R-ASHORT-SEMANTIC-WEBLLM-RUNPATH-SINGLE-SOURCE-GUARD-GAP` — 完整修复要求见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: semantic contract/summary/probe/slice3 tests 125 OK; weekly/adapter tests 104 OK; doc-governance/route tests 27 OK; `git diff --check` clean; `_strict_surfaces()` offenders=0;`rg` 排除 history 后仅剩 active prompt 的 `skill-in-loop` 命中(测试自体命中除外)。
- **Next**: Claude `修复`。

## 2026-06-14 — Claude `修复` (语义单一来源 R7:probe surface 收口 + guard 改 glob 自动发现)
- **Verdict/Action**: 漏面 = probe.py(4 个 `skill 在环` note,curated 列表没含它)+ README row 77(probe→Slice-2 web layer 复述)。本轮:probe.py 5 处 note + README row 77 三处 Slice-2-layer 收成契约指针;**guard STRICT 面改 glob 自动发现**(`_strict_surfaces()` = coverage+README+weekly+`runners/a_short_semantic_risk_*.py`,自动含 probe/summary/未来 runner,排除 impl adapter/engine/pipeline);RUNPATH_NARRATION 补 `Slice 2 skill`/`Slice-2 web layer`/`formal Slice-2 layer`/`Slice 2 formal advisory layer`;planted 加非连字符 `Slice 2 skill 在环`。
- **Required**: `R-ASHORT-SEMANTIC-WEBLLM-RUNPATH-SINGLE-SOURCE-GUARD-GAP` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: glob 集 STRICT offenders=0、DESIGN offenders=0;272 tests OK;py_compile OK;.ps1 CRLF+parse OK;diff-check clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — **根治漏面**:STRICT 面由 curated→glob,新 semantic-risk runner 自动纳入、不再靠手列(前几轮"又漏一面"的根因);A:probe 5 处一次清;B:dogfood glob 集 offenders=0、全仓 grep 契约外无残留;C:glob 只含 `a_short_semantic_risk_*`(probe/summary)不误纳 impl、design pointer-exempt 不误伤历史设计;F:.ps1/parse/BOM/diff 净。
- **Next**: `审查`。

## 2026-06-14 — Codex `审查 FAIL` (语义 doc 单一来源 refactor:Slice-1 probe 漏扫)
- **Verdict/Action**: FAIL. 当前修复把 coverage/README/weekly/summary/design 这一组收口了,但 active Slice-1 probe surface 仍在本地复述旧 web_llm 路径,且 guard 没覆盖该 runner/README 旧行。
- **Required**: `R-ASHORT-SEMANTIC-WEBLLM-RUNPATH-SINGLE-SOURCE-GUARD-GAP` — 完整修复要求见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: semantic contract/docs + doc-governance/route tests 41 OK; weekly/adapter tests 104 OK; `git diff --check` clean; `weekly_screening.ps1` parse OK;自定义盲区探针显示 STRICT/DESIGN=0,但 `runners/a_short_semantic_risk_probe.py` 有 4 个 run-path offender,且 `docs/README.md` row 77 仍复述 probe→Slice-2 web layer 路径。
- **Next**: Claude `修复`。

## 2026-06-14 — Claude `修复` (语义 doc 单一来源真落住:run-path 复述全收 + guard 严格化)
- **Verdict/Action**: 上轮单一来源是名义的(guard"有指针即放行"放过 pointer+本地复述;只收 producer、漏 current-path 复述)。本轮真落住:契约 §web_llm 产出路径 = 唯一陈述;weekly_screening(头/Stage-4/console)+ summary 字符串 + coverage tier/matrix/skill-bullet 全收成纯指针;README 5 条切片叙述**合并为 1 条无叙述路由行**;design doc line 54 加行内 SUPERSEDED 指针。guard 改严格:STRICT 面任何 run-path 复述(current/transitional)都是 offender(**指针不豁免**),design 面 pointer-exempt;planted 覆盖 Codex 点名 false negatives。
- **Required**: `R-ASHORT-SEMANTIC-WEBLLM-RUNPATH-SINGLE-SOURCE-GUARD-GAP` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: STRICT/DESIGN offenders=0;223 tests OK;契约外全仓 grep 无第二份 run-path 叙述;weekly_screening.ps1 CRLF+PS parse OK;diff-check clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A:dogfood-driven 穷尽收全 offender(coverage/README/weekly/summary/design 一次清);B:全文件 grep run-path 短语 0 残留(契约权威节除外);**B2/D(根治)**:guard 改"指针不豁免"消除 pointer+复述 false negative,README 5→1 结构性消除多面叙述;C:design pointer-exempt 不误伤历史设计、panel-gate guard expect 同步去 README(连带);F:.ps1/parse/BOM/diff 净。
- **Next**: `审查`。

## 2026-06-14 — Codex `审查 FAIL` (语义 doc 单一来源 refactor:web 产出路径收口)
- **Verdict/Action**: FAIL. 方向正确,但单一来源没有真正落住:活跃 surface 仍有本地 run-path 复述,且新 guard 有 false negative。
- **Required**: `R-ASHORT-SEMANTIC-WEBLLM-RUNPATH-SINGLE-SOURCE-GUARD-GAP` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: semantic contract/docs + doc-governance/route tests 41 OK; weekly/adapter tests 104 OK; `git diff --check` clean;自定义探针证明 `web_llm UNKNOWN here/current auto web path` 与 pointer+本地复述可逃过 `_separate_run_offenders`。
- **Next**: Claude `修复`。

## 2026-06-14 — Claude `起草` (语义 doc 单一来源 refactor:web 产出路径收口)

**动机**(用户精简提案 + 同一 doc-drift finding 4 轮均一行残留):症状级逐面调和 + 关键词守护会一直生轮次;根治 = 单一来源(一处权威 + 其余指针 + 结构化守护)。

**改动**:
- 契约 `docs/a_short_semantic_risk_contract.md` 新增 `## web_llm 产出路径(单一来源)`:**唯一**陈述"当前 = 周报 M6.7 DeepSeek 自动(Top15、失败中性)/ 过渡(Slice 3 退役)= standalone summary + 2b-ii skill + Stage-4"。
- coverage(tier/matrix/skill-bullet/cadence)、README(切片行 77-81)、weekly_screening(文件头+Stage-4)、summary(docstring/candidate/panel/print)**全部把路径复述收成统一指针** `(产出路径见契约 §web_llm 产出路径)`,删重复解释、留各自独有内容。
- 守护改单一来源版:producer 行**必须含指针** `§web_llm 产出路径` 才放行——过渡标签 / co-mention DeepSeek 都不够;契约权威节须含 canonical 锚点(当前结论路/DeepSeek adapter 自动/过渡路/Slice 3);planted(无指针必红、含指针放行、纯过渡标签必红)。

**Pre-Codex self-review: A-F checked** — A:全 ~13 面 producer 行一次收口(非部分);**B**:dogfood 4 面 offenders=0 + 全仓 grep 契约外无路径复述残留;**B2/D(根治)**:单一来源 + 结构化指针守护(不再枚举同义词、治本——这是前 4 轮症状的根治);C:契约权威节不在被检面(不自误报)、§融入 impl-log 保留(是 build 记录非路径声明)、跨物理行 producer+指针已合并同行(panel append 修一处);F:py_compile OK、.ps1 CRLF/parse OK、BOM/FFFD=0、diff clean、223 tests OK。

**Boundary**:仅 doc 措辞 + 守护;无 runtime/scoring/business 改动。supersedes Slice 2(`cf4bc49`)的 producer-class drift guard(同防漂目标、更彻底)。独立 scope,单独 commit。

**Next**: `审查`。

## 2026-06-14 — Claude `提交` (语义融入 M6.7 Slice 2:DeepSeek web/LLM 判官)
- 提交 Slice 2(本地 master,无 push):新 `a_short_deepseek_semantic_adapter.py`(DeepSeek 判官 + 全失败 fail-closed unknown、不打印 key)+ 引擎 `semantic_web_llm` 族(有 sources 证据 risk/headwind→downgrade、**绝不 hard_veto/救回**、非法 web 中性化)+ 周报 provider(**主板 Top15** 边界、批量 sina + 逐票判、非阻断)+ 契约/coverage/README/weekly_screening/summary 调和为"M6.7 DeepSeek 自动=当前路、旧 standalone/skill/Stage-4=过渡"+ 漂移守护(producer 信号、过渡标签放行)+ adapter/engine/provider 测试。
- closes `R-ASHORT-M67-DEEPSEEK-WEBLLM-TOP15-SCOPE-BYPASS` · `R-ASHORT-M67-DEEPSEEK-WEBLLM-SEPARATE-RUN-DOC-DRIFT`(register 翻 resolved)。
- **Next**: 起草单一来源 refactor(语义 doc 收口:一处权威 + 其余指针 + 单一来源守护)。

## 2026-06-14 — Codex `审查 PASS` (语义 Slice 2 R4:guard helper 注释收尾复审)
- **Verdict/Action**: PASS. 当前工作树已修复 R4 guard helper 注释漂移;DeepSeek co-mention 不再作为 skill-producer 行的放行条件,旧 standalone/skill 路径均已显式标为过渡/sidecar,当前 web 结论路清晰指向周报 M6.7 DeepSeek adapter。
- **Required**: `R-ASHORT-M67-DEEPSEEK-WEBLLM-SEPARATE-RUN-DOC-DRIFT` — 完整详情见 `docs/system_risk_register.md`(单一来源);此 Required 可随本次提交关闭。
- **Verify**: 118 targeted semantic/weekly/adapter tests OK; doc-governance+route 27 OK; `git diff --check` clean; provider Top15 probe = `15 15 True False True True`;关键实现与 coverage 抽查通过。
- **Next**: Claude `提交`。

## 2026-06-14 — Claude `修复` (语义 Slice 2:guard helper 注释 stale 收尾)
- **Verdict/Action**: R3 去掉 DeepSeek 放行后,漏改 `_separate_run_offenders` helper 注释(还写 "NOR the DeepSeek auto path",与新规矛盾)。改为 "NO explicit transitional label(DeepSeek co-mention 不放行)"。纯注释,行为/测试/offenders 不变。
- **Required**: `R-ASHORT-M67-DEEPSEEK-WEBLLM-SEPARATE-RUN-DOC-DRIFT` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: 27 tests OK;offenders=0;全文件 `rg DeepSeek` 当前规则 stale=0(其余均当前路描述/正向锚/R3 正确规则/Round-2 历史);diff-check clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — B:不只改 Codex 点名的 line 279,全文件 grep `DeepSeek` 逐条核;C:注释改不动行为(测试不变验证);F:diff/BOM 净。**注**:同一 finding 第 4 轮均一行残留——根治是单一来源 refactor(你提的精简,Slice 2 提交后)。
- **Next**: `审查`。

## 2026-06-14 — Codex `审查 FAIL` (语义 Slice 2 R3:guard comment drift)
- **Verdict/Action**: FAIL. Runtime behavior and tests pass, but the active guard helper comment still says a stale producer line is reconciled by the DeepSeek auto path, contradicting the R3 rule that only explicit transitional labels reconcile skill-producer mentions.
- **Required**: `R-ASHORT-M67-DEEPSEEK-WEBLLM-SEPARATE-RUN-DOC-DRIFT` — full detail in `docs/system_risk_register.md`.
- **Verify**: 118 targeted semantic/weekly/adapter tests OK; doc-governance+route 27 OK; `git diff --check` clean; residual is `tests/test_a_short_semantic_risk_contract_docs.py` helper comment line 279.
- **Next**: Claude `修复`.

## 2026-06-14 — Claude `修复` (语义 Slice 2 R3:守护"DeepSeek co-mention"放行过松)
- **Verdict/Action**: 上轮把"同行含 `DeepSeek`"当放行,于是 `DeepSeek 自动 / 或 2b-ii skill`(coverage 行 16 + 我的 `ds_only` planted)蒙混过关——仍把 skill 当当前并列选项。本轮:从 `RECONCILED_MARKERS` **去掉 `DeepSeek`**,skill/producer 提及**只能靠显式过渡标签**放行;coverage 行 16 `/ 或 2b-ii skill` → `2b-ii skill 为过渡旁路`;planted 翻转。
- **Required**: `R-ASHORT-M67-DEEPSEEK-WEBLLM-SEPARATE-RUN-DOC-DRIFT` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: 223 tests OK;**去 DeepSeek 后 4 面 offenders 仍=0**(每个 skill 提及都靠显式过渡标签放行);planted `ds_or_skill`→红、`skill_transitional`→绿;diff-check clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A:不只改 row 16,dogfood 去 DeepSeek 后重扫全 4 面确认无第二处靠 co-mention 蒙混;C 反向:去 DeepSeek 不误伤纯 DeepSeek 当前路行(无 producer 短语的行根本不被检,Slice-2 行不受影响);**D**:放行只认显式过渡标签(结构),不靠"提了 DeepSeek 就算";F:diff/BOM 净。**注**:这仍是症状级收口;根治是单一来源 refactor(你提的精简,排在 Slice 2 提交后)。
- **Next**: `审查`。

## 2026-06-14 — Codex `审查 FAIL` (语义 Slice 2 R2:DeepSeek-or-skill guard gap)
- **Verdict/Action**: FAIL. Most stale skill-only wording is now marked transitional, but the guard treats any line containing DeepSeek as reconciled, so `DeepSeek ... / 或 2b-ii skill` can still pass as a current-path alternative.
- **Required**: `R-ASHORT-M67-DEEPSEEK-WEBLLM-SEPARATE-RUN-DOC-DRIFT` — full detail in `docs/system_risk_register.md`.
- **Verify**: 118 targeted semantic/weekly/adapter tests OK; doc-governance+route 27 OK; `git diff --check` clean; residual issue is coverage row 16 plus planted `ds_only` false negative.
- **Next**: Claude `修复`.

## 2026-06-14 — Claude `修复` (语义 Slice 2 R2:separate-run 漂移同义词穷尽 + 守护升级)
- **Verdict/Action**: 上轮 STALE 清单只匹配精确短语,producer 同义词(`skill 在环`/`skill-in-loop`/`2b-ii skill`/`Slice-2b skill`/`left unknown here`)逃过调和与守护。本轮:穷尽 `rg` 出全部 13 命中行逐行调和(coverage tier/matrix/skill-prompt、weekly_screening 文件头+Stage-4 头、README 切片行 77-81)为"DeepSeek 自动=当前路 / 或标过渡";守护信号改为 **producer/separate-run 类**,同行有过渡标签或提 `DeepSeek` 即放行;丢弃歧义 `未评估`(误匹配 unknown→中性规则注释)。
- **Required**: `R-ASHORT-M67-DEEPSEEK-WEBLLM-SEPARATE-RUN-DOC-DRIFT` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: 223 tests OK;**4 面 offenders=0**(含 producer 同义词);planted 覆盖 producer-only(红)+ DeepSeek-only(绿);weekly_screening.ps1 CRLF-uniform + PS parse OK;diff-check clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A:不只补 Codex 点名 3 处,**穷尽 rg 13 行一次清**;B:`_separate_run_offenders` 扫 4 面=0 残留;**D(根因)**:不再枚举无穷同义词(whack-a-mole),改钉 producer 信号 + DeepSeek/过渡正向放行(最窄安全侧);C:放行含 DeepSeek 不误掩盖(正向锚另验 coverage/README 有 M6.7 auto)、丢 `未评估` 防误报规则注释;F:CRLF/parse/BOM/diff 净。
- **Next**: `审查`。

## 2026-06-14 — Codex `审查 FAIL` (语义 Slice 2 修复复审:separate-run 文档漂移)
- **Verdict/Action**: FAIL. Top15 provider scope is repaired, but separate-run doc drift remains; active surfaces still teach skill-only/separate web wording and the guard misses those synonyms.
- **Required**: `R-ASHORT-M67-DEEPSEEK-WEBLLM-SEPARATE-RUN-DOC-DRIFT` — full detail in `docs/system_risk_register.md`.
- **Verify**: 118 targeted tests OK; doc-governance+route 27 OK; provider probe `15 15 True False True True`; residual scan still hits weekly_screening header, README rows 78/81, coverage rows 17-19.
- **Proof-of-use**: Review used current worktree, targeted tests, provider probe, and residual `rg`; full finding text is stored only in the register.
- **Next**: Claude `修复`.

## 2026-06-14 — Claude `修复` (语义 Slice 2:web provider Top15 边界 + separate-run 文档漂移)
- **Verdict/Action**: 两条都修。(1) `_build_deepseek_web_llm_provider` 抓 sina/判 DeepSeek **前先过 `main_board_top15`**(同 cninfo provider 已审门),只抓过滤后主板 Top15,主板外候选→`None`;加回归测试。(2) 穷尽调和 separate-run/web-unknown 面(coverage/README/weekly_screening/summary)为"M6.7 自动判 web=当前路、standalone/Stage-4/skill=过渡 sidecar",加 per-line 漂移守护(stale 无过渡标记必红)+ planted + 正向锚。
- **Required**: `R-ASHORT-M67-DEEPSEEK-WEBLLM-TOP15-SCOPE-BYPASS` · `R-ASHORT-M67-DEEPSEEK-WEBLLM-SEPARATE-RUN-DOC-DRIFT` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: 223 tests OK(含 provider Top15 过滤测试 + 漂移守护 + planted);**B 全仓扫 4 面 offenders=0**(每条 stale-web 行均带过渡标签);weekly_screening.ps1 CRLF 保持 + PS parse OK;diff-check clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A:Top15 绕过类一次覆盖(provider 过滤 + 主板外→None)+ 文档漂移**穷尽 4 面**(非只 Codex 点名);B:`_separate_run_offenders` 扫 4 面 = 0 残留(非"我改了"是"0 offender");C:过滤不误伤主板内(测主板内正常判)、过渡标签不掩盖当前路(正向锚验 M6.7 auto 已写);F:CRLF/parse/BOM/diff 净。
- **Next**: `审查`。

## 2026-06-14 — Codex `审查 FAIL` (语义融入 M6.7 Slice 2:DeepSeek web/LLM 判官接线)
- **Verdict/Action**: FAIL. DeepSeek adapter and M6.7 downgrade behavior are directionally correct and targeted tests pass, but the weekly web_llm provider currently bypasses the semantic-risk main-board Top15 boundary, and active docs/scripts still teach the old separate-run / web_llm-unknown workflow.
- **Required**: `R-ASHORT-M67-DEEPSEEK-WEBLLM-TOP15-SCOPE-BYPASS`; `R-ASHORT-M67-DEEPSEEK-WEBLLM-SEPARATE-RUN-DOC-DRIFT` — full detail in `docs/system_risk_register.md`.
- **Verify**: 234 targeted tests OK; py_compile OK; independent provider probe showed a 23-code list including `300750.SZ` is passed straight to the fake Sina fetcher; active scan still finds separate-run/unknown wording in coverage, README, weekly_screening, and standalone summary surfaces.
- **Next**: Claude `修复`.

## 2026-06-13 — Claude `起草` (语义融入 M6.7 Slice 2:DeepSeek web/LLM 判官接进 M6.7)

**目标**(用户 #1:"DeepSeek web_llm adapter 接进 M6.7"):补语义的 web/LLM 半边。DeepSeek 当**判官**(判已抓取文本,非搜索器),advisory-only,绝不硬否决/救回/伪装 clear。设计=桌面 doc §8 + 契约,已收敛。

**改动**:
- 新 `runners/a_short_deepseek_semantic_adapter.py`:`deepseek_layer_status`(只报 present/ready 布尔,不泄 key)、`build_deepseek_client`(缺 key/SDK→None,不抛/不打印 key)、`judge_web_llm(...)`——DeepSeek 判 sina 标题 → 契约 web_llm + sources;**全失败路径 fail-closed 到 unknown/unknown/no_action**(无条目/无客户端/API 异常/不可解析/违反契约/无 sources);复用 `_web_llm_consistency_error`(单一来源);prompt-injection 卫生(折叠换行/去反引号/截断/限量)。
- 引擎 `a_short_phase5_engine.py`:`RISK_FAMILIES += semantic_web_llm`;`build_m67_report` 消费 `inp["semantic_web_llm"]={web_llm,sources}`——risk/risk_candidate/headwind 且有 sources→`downgrade`(**绝不 hard_veto**),tailwind/clear_light 不降级不救回,unknown/无输入 中性;**非法 web 中性化 + trace `invalid_neutralized`(advisory 非阻断,不 raise——区别 official 的 fail-closed abort)**;trace web_llm 用真实判断填充;消费映射加 web_llm 行。
- 周报 `a_short_weekly_pipeline.py`:`_build_deepseek_web_llm_provider`(批量抓 sina 一次 → 逐票判,缺 key/SDK/抓取失败/单票异常→None 中性,非阻断);`normalize_candidate` 加 `semantic_web_llm` 参数;`main` 加 `web_llm_provider` 参数 + 真 run(`--confirm` 且未 `--skip-semantic`)自动接入(注入优先)。
- 契约/coverage:web_llm M6.7 集成(Slice 2)= advisory downgrade、绝不 hard_veto、unknown-not-clear、来源可追溯;coverage Slice 2 标已建,待后续片收窄为 Slice 3。

**Pre-Codex self-review: A-F checked**(完整规则见 checklist 单一来源)— A:web 消费按 per-status×outcome 矩阵一次全覆盖(6 态 + 6 非法形 + None)+ adapter 6 条降级路径;**B 全仓 grep**:`rg "未接|web_llm adapter\(2\)" -g"*.py" -g"*.md"`(排除 history)= **0 相关残留**,引擎旧 "Slice2 未接" note 已删(`rg "Slice2|未接" engine` = 0),standalone summary 的"待 Slice-2b skill"是旧路(Slice 3 退役)非本片故不动;B2:`_web_llm_consistency_error` 单一来源,adapter+引擎复用(lazy import 防循环);C 反向:web 绝不 hard_veto(测)、tailwind 绝不救回 official/base 硬否决(测)、非法 web 不静默旁路(`invalid_neutralized` 可见)、unknown 不当 clear;D:NL 判断委托 DeepSeek、不枚举关键词,模糊一律 fail-closed unknown;E:coverage/契约单态(Slice 2 已建 / 待后续片=Slice 3),无修复流水账;F:py_compile OK、无循环依赖、缺 key/SDK 优雅降级、绝不打印 key、220 tests OK、diff-check clean、BOM/FFFD=0。

**Boundary**:仅非生产 M6.7 advisory;web 绝不进 production EGS scoring/decision/veto、不进回测、不写 result/a_short、不自动下单;V14.2 frozen;egs_main stage3(legacy DeepSeek)不碰。真 DeepSeek/sina 调用是之后的 `执行`(本片注入 mock 测)。不含 Slice 3(render 行内化/废面板/weekly_screening 串联)。

**Next**: `审查`。

## 2026-06-13 — Codex `审查 PASS` (pre-Codex gate single-source refactor)
- **Verdict/Action**: PASS. The refactor correctly collapses the pre-Codex gate rule body into `docs/pre_codex_self_review_checklist.md`; `AGENTS.md` item 7 is now a mandatory pointer and no longer restates A-F/B2 bodies.
- **Required**: no new Required. `R-DOCGOV-B-RIPPLE-GREP-PROOF-AND-CHECKLIST-GUARD-GAP` remains resolved in `docs/system_risk_register.md`; this refactor supersedes its pin-both mechanism without reopening the risk.
- **Verify**: doc-governance+route 27 OK; py_compile OK; old pin-both guard names 0 hits in `*.py`; planted probes catch checklist deletion and AGENTS restatement; diff-check/BOM/FFFD clean.
- **Next**: Claude `提交`.

## 2026-06-13 — Claude `起草` (协议精简:pre-Codex gate 收为单一来源,AGENTS item7 只点名)

**动机**(用户+Codex:"协议规则仍在 AGENTS + checklist 双写,是最大冗余"):上一轮 pin-both guard 只是把双写"守起来";而 A/B/B2/C/D/E/F + Proof-of-use **整组**都在 AGENTS item7 与 checklist 各写一遍——只收 B 是"修实例不修类"(规则 A 本身)。按 B2「一个会变事实=一个权威位置」收敛。

**改动**:
- `AGENTS.md §item7`:删 A–F+B2+Proof-of-use 正文,收成**框架句 + 强制指针**(全文见 checklist、起草/修复前必读必走、本文只点名不复述);保留 Proof-of-use 行要求(格式→checklist);§Session log discipline 的 item-7 cross-ref 仍成立。
- `docs/pre_codex_self_review_checklist.md`:新增 `## B2. 单一来源 + drift guard` 段(从 AGENTS 迁入:权威位置选则 / 局部块守护 / planted-failure / 靠人记)→ checklist 成 A–F+B2 **唯一正文**。
- `docs/README.md`:gate 行去 A–F 罗列,指向 checklist 为唯一正文。
- `tests/test_doc_governance_guard.py`:pin-both 两测试 + `_b_sections`/`B_ANCHORS` 替换为单一来源版——`test_pre_codex_checklist_is_sole_rule_authority`(checklist 持 7 段 + B/B2 锚点)+ `test_agents_item7_points_to_checklist_and_does_not_restate`(item7 有指针/必读必走/Proof-of-use,且**不得复述** body 锚点 零残留/defect-class/靠人记/planted-failure)+ `test_pre_codex_gate_single_source_guard_is_real_planted`(双向植入:删 checklist 段/锚点必红、向 AGENTS 注 body 必被抓);`test_agents_pins_register_single_source_and_minimal_template` 移除"B2 须在 AGENTS"子检查。

**Pre-Codex self-review: A-F checked** — A:不只收 B,**整组 A–F+B2+Proof-of-use** 一次收敛(避免"修实例不修类");**B 全仓 grep**:旧 pin-both guard 名在 `*.py` **0 残留**(`rg -n "test_b_ripple_grep_anchors_pinned_in_agents_and_checklist|..._anchor_guard_is_real_planted|_b_sections|B_ANCHORS" -g "*.py"` exit=1),`零残留/靠人记/planted-failure` 已不在 AGENTS(line 323 `defect-class` 属 Codex 标准 item16、在 item-7 区外),history 旧名为 append-only 记录不动;B2:本 refactor 即 B2 应用(单一来源+局部守护+双向 planted);C 反向:no-restatement 守护只钉 body 锚点、不钉规则名(指针含"A class-not-instance / B ripple-grep"不误报),authority 守护按段头+锚点(gut body 会丢锚点→被抓);E:本条即收单态,pin-both 机制在 register 标 superseded;F:25 tests OK、py_compile OK、diff-check clean、BOM/FFFD=0。

**Boundary**:仅协议文档(AGENTS/checklist/README)+ doc-governance 守护;无 runtime/scoring/business 改动。supersedes `c76e4b5` 的 pin-both guard 机制(同一防漂移目标、更彻底);`R-DOCGOV-B-RIPPLE-GREP-PROOF-AND-CHECKLIST-GUARD-GAP` 仍 resolved(漂移风险不回归——已无第二份可漂)。

**Next**: `审查`。

## 2026-06-13 — Claude `提交` (Slice 1b + 协议 B-strengthening,两 scope 分提交)
- **`d4beb9b`**(Slice 1b:真 cninfo provider + evidence-full M6.7):closes `R-ASHORT-M67-CNINFO-PROVIDER-BYPASSES-SEMANTIC-SUMMARY-GATES` · `R-ASHORT-M67-SLICE1B-EVIDENCE-FULL-CONTRACT-DRIFT` · `R-ASHORT-M67-PREVIOUS-REQUIRED-STATUS-DRIFT-AFTER-COMMIT` · `R-ASHORT-M67-EVIDENCE-FULL-RUNTIME-EXPLANATION-DRIFT` · `R-ASHORT-M67-EVIDENCE-FULL-ROUTEDOC-GUARD-WEAKNESS` · `R-ASHORT-M67-RISK-REGISTER-REFAIL-CORRECTION-STALE`。
- **`c76e4b5`**(协议 B ripple-grep 强化 + guard):closes `R-DOCGOV-B-RIPPLE-GREP-PROOF-AND-CHECKLIST-GUARD-GAP` · `R-RISK-REGISTER-STALE-OPEN-REPAIRED-HOTQUEUE-SWEEP-GAP`。
- register 上述 8 条 `open`→`resolved`(本 commit C);本地 master,无 push。
- 未跟踪保留:`research/results/a_short/semantic_risk_20260605/`(首次语义真跑产物,research lane,待定是否单独留痕)。
- **Next**: 起草 pre-Codex gate 单一来源 refactor(AGENTS item7 收成指针、checklist 做唯一正文)。

## 2026-06-13 — Codex `审查 PASS` (B ripple-grep proof command)
- **Verdict/Action**: PASS. `R-DOCGOV-B-RIPPLE-GREP-PROOF-AND-CHECKLIST-GUARD-GAP` is repaired in working tree: proof command is reproducible as shown, and B ripple-grep anchors are pinned in both `AGENTS.md` and the checklist.
- **Required**: no new Required. Existing repaired Required closes on Claude `提交` with commit evidence in `docs/system_risk_register.md`.
- **Verify**: 207 tests OK; py_compile OK; exact `rg -n "test_agents_b_ripple_grep_covers_emit_strings_and_test_surfaces" -g "*.py"` returns 0 hits; diff-check/BOM/FFFD clean; weak-anchor deletion simulation fails.
- **Next**: Claude `提交`.

## 2026-06-13 — Claude `修复` (B ripple-grep dogfood 改为可复现命令)
- **Verdict/Action**: 修复 Codex FAIL — 旧 proof 把排除写在命令外、且搜的是一个杜撰占位短语(从来不是真实产物),字面命令会命中 → 不可复现。换成 scope 写进命令、直出为零的真实重命名扫描:`rg -n "test_agents_b_ripple_grep_covers_emit_strings_and_test_surfaces" -g "*.py"` = 0 hits(本次把 doc-governance guard 从该旧名重命名为 `test_b_ripple_grep_anchors_pinned_in_agents_and_checklist`;旧名在 live code 零残留,只存于 append-only SESSION_LOG/register 历史即 `.md`,在 *.py scope 外,故命令复制即得 0)。杜撰占位短语已从所有 Claude proof 行清除(不再逐字复述以免自命中)。
- **Required**: `R-DOCGOV-B-RIPPLE-GREP-PROOF-AND-CHECKLIST-GUARD-GAP` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: `rg -n "test_agents_b_ripple_grep_covers_emit_strings_and_test_surfaces" -g "*.py"` 字面输出 = 0 hits;doc-governance 12 OK、相关四套 181 OK;`git diff --check` 仅 CRLF;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A:三处我方 proof(register 主条 / 起草 / 上轮修复 Verify)一次全换为该可复现命令;B:dogfood 命令把 scope 写在命令内、字面直出 0,不靠外部 prose 排除;C:不再"声称 0 实则命中"——这次是命令本身的字面输出即 0,且不再逐字复述杜撰短语;F:见 Verify。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (B ripple-grep proof command)
- **Verdict/Action**: FAIL. Checklist guard widening is repaired, but the dogfood proof command is still not reproducible: the displayed `rg -n "repo-grep the old symbol names, every doc sentence" .` returns hits unless extra exclusions are implied outside the command.
- **Required**: `R-DOCGOV-B-RIPPLE-GREP-PROOF-AND-CHECKLIST-GUARD-GAP` — full detail in `docs/system_risk_register.md`.
- **Verify**: 207 tests OK; py_compile OK; `git diff --check` only CRLF warnings; BOM/FFFD clean; exact displayed `rg` command returns current `SESSION_LOG`/register hits.
- **Next**: Claude `修复`.

## 2026-06-13 — Claude `修复` (B ripple-grep dogfood + guard 钉两处 + planted)
- **Verdict/Action**: 修复 Codex FAIL — (1) dogfood:`起草` proof 行补真实 `rg` + 0-hit(旧窄 B 形态已清);(2) guard 由只钉 `AGENTS.md` 扩到 **AGENTS B + checklist B 两处**锚点(零残留/字符串字面量/test_/全仓 guard)+ planted(删任一锚点必红);旧单文件 guard 重命名为 `test_b_ripple_grep_anchors_pinned_in_agents_and_checklist`。
- **Required**: `R-DOCGOV-B-RIPPLE-GREP-PROOF-AND-CHECKLIST-GUARD-GAP` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: doc-governance 12 OK(新 2 测试 + planted)、相关四套 181 OK;dogfood(scope 写进命令、直出为零)`rg -n "test_agents_b_ripple_grep_covers_emit_strings_and_test_surfaces" -g "*.py"` = 0 hits;`git diff --check` 仅 CRLF;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A:guard 一次覆盖 AGENTS+checklist 两面;B:dogfood rg=0、planted 证 guard 非空转;C:planted 全删锚点(非删 1)防漏报;F:见 Verify。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (B ripple-grep protocol strengthening)
- **Verdict/Action**: FAIL. Direction is correct, but the new B rule is not dogfooded and not fully guarded: proof lacks actual `rg` command + `0 hits`, and the guard pins only `AGENTS.md`, not the detailed checklist implementers are routed to.
- **Required**: `R-DOCGOV-B-RIPPLE-GREP-PROOF-AND-CHECKLIST-GUARD-GAP` — full detail in `docs/system_risk_register.md`.
- **Verify**: 206 tests OK; py_compile OK; `git diff --check` only CRLF warnings; BOM/FFFD clean. Diff inspection confirms `test_agents_b_ripple_grep_covers_emit_strings_and_test_surfaces` reads only `AGENTS.md`.
- **Next**: Claude `修复`.

## 2026-06-13 — Claude `起草` (协议强化:B ripple-grep → 全仓+零残留证据+emit/测试面+复发全仓 guard)

**动机**(用户问"为何同一问题多轮修复 / 一次修复不完整如何避免"):根因=我把 B 执行窄了——只扫 runner+.md,漏了 **emit 字符串字面量**(machine.consumption)与 **test docstring/注释**,致同一 evidence-full R-ID 被 Codex re-FAIL 3 轮。标准在(AGENTS item7 + checklist),是我**欠执行 + B 清单缺这两面**。

**改动**:
- `AGENTS.md §item7 B`:强化为"改规则/符号/机制/**措辞**后做**一次全仓 grep 旧形态**(代码+测试[含 docstring/注释]+docs+**emit 字符串字面量** machine.consumption/log/面板/用户文案),贴**零残留证据**(rg+0 hits);**已复发规则→加全仓 guard 禁旧形态**"。
- `docs/pre_codex_self_review_checklist.md §B`:同步;显式列两漏面 + 零残留证据要求 + 复发→全仓 guard;附本会话反例。
- `tests/test_doc_governance_guard.py`:新 guard `test_agents_b_ripple_grep_covers_emit_strings_and_test_surfaces` 钉 B 的强化锚点(零残留/字符串字面量/test_/全仓 guard)不被删。

**Pre-Codex self-review: A-F checked** — A:AGENTS B + checklist B + 守护一次覆盖;**B dogfood(scope 写进命令、直出为零)**:`rg -n "test_agents_b_ripple_grep_covers_emit_strings_and_test_surfaces" -g "*.py"` = **0 hits**(本次重命名的旧 guard 名在 live code 零残留;只存于 append-only SESSION_LOG/register 历史,在 *.py scope 外);guard 现钉 **AGENTS B + checklist B 两处**锚点(零残留/字符串字面量/test_/全仓 guard)+ planted(删任一锚点必红);F:25→26 tests(governance+route)OK、五套 OK、`git diff --check` clean、BOM/FFFD=0。

**Boundary**:仅协议文档(AGENTS/checklist)+ 守护;无 runtime/scoring/business 改动。独立 scope,与 Slice 1b 分开 commit。

**Next**: `审查`。

## 2026-06-13 — Claude `修复` (register 卫生 — stale Codex correction 段标 SUPERSEDED)
- **Verdict/Action**: register line 38 那段 Codex correction 仍称 docstring 修复未完成,与主条 Round 2(已修+零残留)矛盾;标 **SUPERSEDED(Round 2)** 使其历史化,主条 Round 2 注记为 live 真相;两条均 open 至本轮 PASS+提交再闭。
- **Required**: `R-ASHORT-M67-RISK-REGISTER-REFAIL-CORRECTION-STALE` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: register 内部矛盾消除(correction 段标 SUPERSEDED);doc-governance+route 25 OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A:register 矛盾段一次标历史;B:无代码改动、仅 register 措辞,grep 确认无第二处重复该 outstanding 声明;C:RUNTIME-DRIFT 仍 open(未提交)未误闭;F:见 Verify。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (Slice 1b runtime explanation drift — register correction stale)
- **Verdict/Action**: FAIL. Runtime behavior, emitted consumption text, runner comments, and test docstring are now aligned, but the authoritative risk register still contains the prior Codex correction paragraph saying the docstring repair is outstanding.
- **Required**: `R-ASHORT-M67-RISK-REGISTER-REFAIL-CORRECTION-STALE` — full detail in `docs/system_risk_register.md`.
- **Verify**: 205 tests OK; py_compile OK; runtime probe OK; residual scan of active runners/tests/docs found no generic high→veto wording without evidence-full anchors; `git diff --check` and BOM/FFFD clean.
- **Next**: Claude `修复`.

## 2026-06-13 — Claude `修复` (Slice 1b — 测试教学面 evidence-full 收尾 + 穷尽扫零残留)
- **Verdict/Action**: 同 R-ID 第 2 轮(上轮漏了测试面)。改 `SemanticIntoM67` class docstring 为 evidence-full(high 含非空 url_or_pdf→否决;空 URL→待核);并把 test 内泛化措辞的内联/meta 注释也加限定。**穷尽 `rg`** runners+tests+docs 确认零残留泛化 `high→否决/veto`(排除 chasing_high_veto 因子名 + 档案/历史)。
- **Required**: `R-ASHORT-M67-EVIDENCE-FULL-RUNTIME-EXPLANATION-DRIFT` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: 穷尽 rg 零残留;174 tests OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — **A 这次真穷尽**:不只 Codex 点名的 class docstring,全仓 rg 扫所有面(runner/test docstring/test 注释/meta 引述)一次清;**B 反省(连续两轮同 R-ID)**:教训=evidence-full 这类规则改动的 ripple 必须含**测试文件的 docstring/注释**,我前两轮只扫了 runner+.md 漏了 test 教学面——已写进 register lesson;C 反向:证据齐全 high 仍否决(既有测);F:rg 全扫 + diff/BOM 净。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (Slice 1b runtime explanation drift — tests surface still stale)
- **Verdict/Action**: FAIL. Runtime output and runner comments are fixed, but `tests/test_a_short_weekly_pipeline.py::SemanticIntoM67` docstring still teaches generic `high->veto` without the evidence-full / non-empty URL condition.
- **Required**: `R-ASHORT-M67-EVIDENCE-FULL-RUNTIME-EXPLANATION-DRIFT` — full detail in `docs/system_risk_register.md`.
- **Verify**: 205 tests OK and runtime probe OK, but UTF-8 line read confirms `tests/test_a_short_weekly_pipeline.py` still has `high->veto` wording in an active test teaching surface.
- **Next**: Claude `修复`.

## 2026-06-13 — Claude `修复` (Slice 1b — 运行时解释面去泛化漂移 evidence-full)
- **Verdict/Action**: 上轮漏修的 runtime-explanation-drift。把所有运行时/教学面更新到 evidence-full:`machine.consumption.semantic`(实际 emit 的 M6.7 trace)从"official high→否决"改为"official high 且证据齐全(非空 url_or_pdf)→否决;缺 URL high→待核";Phase5 语义块注释 + `normalize_candidate` provider 注释同步。
- **Required**: `R-ASHORT-M67-EVIDENCE-FULL-RUNTIME-EXPLANATION-DRIFT` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: 新增 regression 守护 `test_consumption_map_states_evidence_full_rule_not_generic`(emit 的 consumption.semantic 须含 url_or_pdf+证据齐全+待核);`rg` 确认两 runner 无残留泛化 `high→否决`;174 tests OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A:运行时输出(consumption map)+ 两处代码注释 + 守护一次覆盖(不只 Codex 点名的 consumption map);**B 连带反省**:这是上轮我只改契约/route-doc、漏了**代码内运行时解释面**——B ripple 应含"emit 到 machine 的字符串"与代码注释,不只 .md;C 反向:证据齐全 high 仍否决(既有测);D:无;F:rg 全扫无残留、diff/BOM 净。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (Slice 1b runtime explanation drift still open)
- **Verdict/Action**: FAIL. No newer Claude repair entry is present, and the same runtime explanation drift remains: behavior is pending for blank-URL high, but active output/teaching text still says generic `official high -> veto`.
- **Required**: `R-ASHORT-M67-EVIDENCE-FULL-RUNTIME-EXPLANATION-DRIFT` — full detail already in `docs/system_risk_register.md`.
- **Verify**: `rg` still finds stale `official high->veto` / `high->veto` wording in `runners/a_short_phase5_engine.py` and `runners/a_short_weekly_pipeline.py`; the Required entry remains `status open`.
- **Next**: Claude `修复`.

## 2026-06-13 — Codex `审查 FAIL` (Slice 1b runtime explanation drift)
- **Verdict/Action**: FAIL. Core behavior stays correct, but runtime explanation / active code teaching surfaces still describe the old generic `official high -> veto` rule while blank-URL high now correctly routes to pending.
- **Required**: `R-ASHORT-M67-EVIDENCE-FULL-RUNTIME-EXPLANATION-DRIFT` — full detail in `docs/system_risk_register.md`.
- **Verify**: 203-test suite was green before this added finding; custom probe shows blank `url_or_pdf` high gives `impact=pending` and `evidence_incomplete_high=1`, while `machine.consumption.semantic` still says `official high->veto`.
- **Next**: Claude `修复`.

## 2026-06-13 — Claude `修复` (Slice 1b 复审 — Hot Queue 全量扫翻 + evidence-full 守护强化)
- **Verdict/Action**: 两条都修。(1) **全量 Hot Queue 闭合扫**:14 条已提交 review-passed 却仍 stale `open` 的条目翻 `resolved` 带 commit 证据(92a32c0 / 6709055 / 9918d84);本轮 Slice 1b 仍 open;加 regression 守护钉死已提交 R-ID 必 resolved(不误伤 in-flight)。(2) evidence-full 路由守护强化:coverage 须 `url_or_pdf`+`待核`+`不否决`、README 须 `url_or_pdf`+`pending`+`never veto`,不再只查 `url_or_pdf`(防保留词却漂回泛化)。
- **Required**: `R-RISK-REGISTER-STALE-OPEN-REPAIRED-HOTQUEUE-SWEEP-GAP` · `R-ASHORT-M67-EVIDENCE-FULL-ROUTEDOC-GUARD-WEAKNESS` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: 扫翻 14 条(R-ID↔commit 脚本校验输出核对)、regression 守护过、evidence-full 守护加强后过;112 tests OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A:不只补 Codex 点名的 92a32c0/6709055,**全队列**按 commit 映射一次扫全(含 9918d84 DOCGOV);B 连带:扫翻用 R-ID↔commit 映射脚本(打印核对)、register Python 写盘保 CRLF/无 BOM;C 反向:in-flight findings(40/42/44 + 本轮 36/38)故意不在已提交集合 → 守护不误伤;D:无;F:diff/BOM 净、register 仍可解析(112 OK)。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (Slice 1b 复审 — Hot Queue closure + evidence-full guard)
- **Verdict/Action**: FAIL. Slice 1b 代码路径和核心行为探针通过,但全量复审发现 Hot Queue 仍有已提交旧修复保持 `status open`,且 evidence-full route-doc 守护弱于当前重复文字。
- **Required**: `R-RISK-REGISTER-STALE-OPEN-REPAIRED-HOTQUEUE-SWEEP-GAP`; `R-ASHORT-M67-EVIDENCE-FULL-ROUTEDOC-GUARD-WEAKNESS` — full detail in `docs/system_risk_register.md`.
- **Verify**: 203 tests OK; py_compile OK; diff-check clean; custom probes confirmed provider Top15/batch-empty/missing-code/bad-lookback and blank-vs-full URL high behavior; git log confirmed `92a32c0`/`6709055` are review-passed commits.
- **Next**: Claude `修复`.

## 2026-06-13 — Claude `修复` (Slice 1b — provider 复用已审门 + 契约 evidence-full + register 翻转)
- **Verdict/Action**: 三条都修。(1) `_build_cninfo_semantic_provider` 改为**复用 `build_summary_from_fetches`**(main_board_top15 + 缺码→unknown + 批量空门),不再绕过;lookback 非正整数→不取数;malformed 行丢弃不建 "None" 键。(2) 契约/coverage顶/README 同步 **evidence-full**(high 含非空 url_or_pdf 才否决;空 URL→待核)+ 守护扩锚点。(3) 前 4 个 Slice-1 Required 翻 `resolved`(closure→`908f95f`),Slice 1b 仍 open。
- **Required**: `R-ASHORT-M67-CNINFO-PROVIDER-BYPASSES-SEMANTIC-SUMMARY-GATES` · `R-ASHORT-M67-SLICE1B-EVIDENCE-FULL-CONTRACT-DRIFT` · `R-ASHORT-M67-PREVIOUS-REQUIRED-STATUS-DRIFT-AFTER-COMMIT` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: provider 门对抗(批量空→unknown/缺码→unknown/非主板不取不喂/坏lookback不取/malformed无None/risk正常)+ 契约 evidence-full 守护 + 既有 --confirm 测试加 --skip-semantic 保网络无关;172 tests OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A:provider 绕过类一次复用已审门覆盖全(top15/缺码/批量空/lookback/malformed)+ 契约漂移三面(contract/coverage/README)+ register 4 条;**B 连带**:复用 summary 而非另写薄版(单一来源)、契约改与代码 evidence-full 一致、注明更广 register stale 超本 finding 范围未盲翻;C 反向:证据齐全 high 仍否决(full+blank 混合测)、批量健康仍 clear;D:url 空走 strip 非关键词;F:py_compile OK、validate_m67_consistency 每出口过、diff/BOM 净。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (语义融入 M6.7 Slice 1b — cninfo provider + empty URL evidence contract)
- **Verdict/Action**: FAIL. 行为测试和 py_compile 通过,但自动 cninfo provider 绕过已审过的 Top15/批量空结果质量门,且 stable contract 未同步 evidence-full high 才能 advisory `否决` 的规则。
- **Required**: `R-ASHORT-M67-CNINFO-PROVIDER-BYPASSES-SEMANTIC-SUMMARY-GATES`; `R-ASHORT-M67-SLICE1B-EVIDENCE-FULL-CONTRACT-DRIFT`; `R-ASHORT-M67-PREVIOUS-REQUIRED-STATUS-DRIFT-AFTER-COMMIT` — full detail in `docs/system_risk_register.md`.
- **Verify**: 201 tests OK; py_compile OK; diff-check clean; probes covered mass-empty clear bypass, non-Top15 fetch, negative lookback, malformed row mapping, and doc/contract anchor drift.
- **Next**: Claude `修复`.

## 2026-06-13 — Claude `起草` (语义融入 M6.7 Slice 1b — 真 cninfo provider 接入 + 空 URL 方案 A)

**目标**:把真 cninfo 自动接进周报 provider(用户:Slice 1b),并按用户确认的**方案 A** 处理空 URL(不伪造 URL、不崩、证据不全→待核)。

**改动**:
- `a_short_phase5_engine.py`:`_validate_semantic_official` 放宽 `url_or_pdf` 为 present+string **可空**(其余 6 字段仍非空;非字符串仍 ValueError);`build_m67_report` 把 high 拆 `high_full`(含非空 URL→驱动否决)vs `high_incomplete`(缺 URL→降 pending 待核);trace 加 `evidence_incomplete_high`,severity_max 取全事件(含 incomplete high,诚实)。
- `a_short_weekly_pipeline.py`:`_build_cninfo_semantic_provider`(批量 cninfo→逐票 build_official_structured;**任何失败→None 全 unknown,非阻断**);`main` 在 `--confirm-fetch-authorized` 且未 `--skip-semantic` 时自动接入(注入优先);加 `--cninfo-lookback-days`/`--skip-semantic`。
- 测试:空/空白 URL high→待核(非否决非崩)、full+blank 混合 high→否决、provider builder 映射 + 非阻断、`--skip-semantic` 中性、既有 `--confirm` 测试加 `--skip-semantic` 保网络无关。

**Pre-Codex self-review: A-F checked** — A:空 URL × {空/空白/与 full 混合} + provider × {映射/非阻断} + skip 全覆盖;**B 连带 + 测试卫生**:发现并修了"`--confirm` 测试会触发真 cninfo 网络"的隐患(加 `--skip-semantic`),producer(build_official_structured)未改、summary 测试不受影响;C 反向:证据齐全 high 仍否决(full+blank 混合测)、never-rescue 不变;D:url 空判定走 `.strip()` 非关键词;F:py_compile OK、170 tests OK、validate_m67_consistency 每出口过、diff/BOM 净。

**Boundary**:仅 M6.7 advisory(非生产/不进回测);cninfo 取数非阻断旁路、不写 result/a_short;不接 DeepSeek/不改 render/面板/Stage4;V14.2 frozen。真 cninfo 跑一次属之后的 `执行`。

**Next**: `审查`。

## 2026-06-13 — Codex `审查 PASS` (语义融入 M6.7 Slice 1 — official evidence contract)
- **Verdict/Action**: PASS. 上一轮 `R-ASHORT-M67-SEMANTIC-OFFICIAL-EVIDENCE-NONEMPTY-GAP` 已修:所有 official event 必填字段现在必须是 trim 后非空字符串;blank / whitespace `title`、`category`、`url_or_pdf` 不再能触发 M6.7 advisory `否决`。
- **Required**: no new Required. 既有 4 个语义 M6.7 Required 均已在 working tree 修复,详见 `docs/system_risk_register.md`;状态待 `提交` 后按协议翻 resolved。Slice 1b carry-forward:empty-url official event 必须保证 URL/PDF 或路由 non-veto pending/unknown。
- **Verify**: 196 tests OK; py_compile OK; `git diff --check` clean; custom evidence probe confirmed valid high/medium/low/clear/unknown/None pass and missing/blank/whitespace/non-string required fields, non-cninfo source, bad/future date, bad severity, hpa=false all fail-closed; BOM/FFFD=0。
- **Next**: `提交`。

## 2026-06-13 — Claude `修复` (语义融入 M6.7 Slice 1 — official 证据字段非空门)
- **Verdict/Action**: `_validate_semantic_official` 事件字段从"present"升级为"**trim 后非空字符串**"(present-but-empty / 纯空白 也拒);high 事件若 title/category/url_or_pdf 空,不再能变成 M6.7 否决。source/severity/PIT-date/had_pit 门保留。
- **Required**: `R-ASHORT-M67-SEMANTIC-OFFICIAL-EVIDENCE-NONEMPTY-GAP` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: 对抗测试 +blank title/category/url_or_pdf/whitespace-only 全 ValueError;有效 PIT cninfo 全绿;165 tests OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A:把"非空"作整类(所有必填字段一次,非逐个)+ whitespace 也覆盖;**B 连带 + 已知边界显式上交**:核实 build_official_structured 当 adjunctUrl 缺会 emit url_or_pdf="",本消费门按 Codex minimum 要非空,已在 register/代码注释把"Slice 1b 必须保证 URL 或路由空-URL 到 pending"上交(避免合法空-URL 崩周报的漏报);C 反向:有效 PIT 证据仍正常否决/待核;F:py_compile OK、diff/BOM 净。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (语义融入 M6.7 Slice 1 — official evidence non-empty gate residual)
- **Verdict/Action**: FAIL. 最新修复已堵住缺字段、非 cninfo、未来日、坏日期、blank risk_type、had_pit 矛盾,但 present-but-empty `title` / `category` / `url_or_pdf` 仍能触发 M6.7 advisory `否决`。
- **Required**: `R-ASHORT-M67-SEMANTIC-OFFICIAL-EVIDENCE-NONEMPTY-GAP` — full detail in `docs/system_risk_register.md` (single source).
- **Verify**: 196 tests OK; py_compile OK; `git diff --check` clean before this FAIL note; custom probes confirmed blank `title` / `category` / `url_or_pdf` are accepted as `否决` / `impact=veto`.
- **Next**: Claude `修复`.

## 2026-06-13 — Claude `修复` (语义融入 M6.7 Slice 1 — official 证据契约 + PIT fail-closed)
- **Verdict/Action**: `_validate_semantic_official` 升级为完整 official_structured PIT 证据契约(取 as_of):每 event 必备 source/title/category/disclosure_date/url_or_pdf/risk_type/severity、`source=="cninfo"`、risk_type 非空、severity 枚举、disclosure_date canonical 且 ≤ as_of(PIT)、`had_pit_announcements` 为 bool 且 risk 时为 True。残缺/伪造/未来日/手工源/非 PIT → ValueError 写盘前 abort,绝不让其触发 M6.7 否决。
- **Required**: `R-ASHORT-M67-SEMANTIC-OFFICIAL-EVIDENCE-SHAPE-GAP` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: 对抗测试扩到证据契约全维(severity-only/缺任一字段/blank risk_type/非cninfo源/未来日/坏日期/had_pit false 或缺)全 ValueError;有效 PIT cninfo high/medium/clear/unknown/None 全绿;165 tests OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A:把 Codex 列的整套证据契约(字段齐备+source+risk_type+PIT 日+had_pit)一次补齐(非逐条),对抗例覆盖每个出口;B 连带:校验仍单一来源(family/impact/trace 同源)、validator 取 as_of 与 build_official_structured/summary 的 PIT 口径一致;C 反向:有效 PIT 证据仍正常 否决/待核;F:py_compile OK、validate_m67_consistency 每出口过、diff/BOM 净。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (语义融入 M6.7 Slice 1 — official_structured evidence gate)
- **Verdict/Action**: FAIL. 先前两条 Required 主体已修,但 `_validate_semantic_official` 只校验 status/events/severity,未校验 official_structured 的 PIT 证据字段;缺 source/risk_type/date 或未来披露日也能触发 M6.7 advisory `否决`.
- **Required**: `R-ASHORT-M67-SEMANTIC-OFFICIAL-EVIDENCE-SHAPE-GAP` — full detail in `docs/system_risk_register.md` (single source).
- **Verify**: 196 tests OK; py_compile OK; `git diff --check` clean; custom probes confirmed severity-only / future-date / manual-source official events are accepted and hard-vetoed.
- **Next**: Claude `修复`.

## 2026-06-13 — Claude `修复` (语义融入 M6.7 Slice 1 — 输入 fail-closed 校验 + 契约去漂移)
- **Verdict/Action**: 两条都修。(1) 加 `_validate_semantic_official`(fail-closed),family/impact/severity_max/trace 全部从同一已校验对象派生(消除"clear/unknown+high event→impact=veto 但 action=建仓"矛盾 + 非 dict event 的 AttributeError);非法 provider 输出 → ValueError 写盘前 abort。(2) 契约/coverage/README 改为 production-vs-M6.7 区分(生产 EGS/回测 永禁;web_llm 永不硬否决;official high 可在非生产 M6.7 产 advisory 否决),面板/独立 artifact 标过渡。
- **Required**: `R-ASHORT-M67-SEMANTIC-OFFICIAL-INPUT-CONSISTENCY-GAP` · `R-ASHORT-SEMANTIC-CONTRACT-M67-INTEGRATION-DRIFT` — 完整详情见 `docs/system_risk_register.md`(单一来源)。
- **Verify**: 新增对抗测试(clear/unknown-with-high、missing-status、risk-empty、invalid-severity、non-list/non-dict event、non-dict sem)全 ValueError fail-closed;新增契约去漂移守护(禁旧绝对无硬否决 + 必含 production/web/official 区分锚点);有效形态全绿;165 tests(weekly+contract+summary+governance+route)OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A:输入契约 × 所有非法/矛盾形态一次覆盖(8 例)+ 文档漂移类(契约/coverage/README)一次同步;B 连带:校验集中单一来源(family/impact/trace 同源)、契约锚点单一权威 + README/coverage 指向;C 反向:有效形态仍正确、guard 在旧措辞下会 FAIL;D:severity 枚举非关键词;F:py_compile OK、validate_m67_consistency 每出口过、diff/BOM 净。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (语义融入 M6.7 — official_structured → M6.7 引擎集成)
- **Verdict/Action**: FAIL. 方向正确,但 semantic official 输入边界未校验会产生 action/trace 矛盾,且稳定契约仍写着绝不硬否决/面板-only,与本轮 M6.7 advisory 否决迁移冲突。
- **Required**: `R-ASHORT-M67-SEMANTIC-OFFICIAL-INPUT-CONSISTENCY-GAP`; `R-ASHORT-SEMANTIC-CONTRACT-M67-INTEGRATION-DRIFT` — full detail in `docs/system_risk_register.md` (single source).
- **Verify**: 194 tests OK; py_compile OK; `git diff --check` clean; custom semantic probes reproduced clear/unknown/missing-status high-event -> `impact=veto` with action `建仓`, plus malformed events raising uncontrolled `AttributeError`.
- **Next**: Claude `修复`.

## 2026-06-13 — Claude `起草` (语义融入 M6.7 — Slice 1:official_structured → M6.7 引擎集成)

**目标**(用户+Codex 收敛设计,桌面 `semantic_into_m67_design_20260613.md` §8):把语义层融进 M6.7 打分,不再独立 artifact/面板。本片=最小、最安全单元:**只做 cninfo official → M6.7**,不接 DeepSeek、不改 render/不拆面板/不改 Stage4(留 Slice 1b/2/3)。

**集成法(关键)**:语义做成引擎**新 risk family `semantic_official`**,复用既有 family→action→table→validate 机制,**绝不在外硬改 操作**(否则 violate `validate_m67_consistency`)。

**规则(确定性)**:official **high**(立案/处罚/ST/退市)→ family hard_veto → **否决**(引擎自动 null trade、machine action 一致);**medium/low** → 仅 observe 待核 + 精简结论区"否决审查触发"挂「语义待核(未扣分)」,**不扣分/不清/不降星**;**clear/unknown/无输入** → 中性(向后兼容,无 semantic 行为不变)。trace 全进 `machine.layer.semantic_risk`(machine 开放,**无需改 schema**)。**never-rescue**:语义只 ADD hard_veto、不进 compute_star,构造上不可能救回 base 否决。

**改动**:`a_short_phase5_engine.py`(RISK_FAMILIES +semantic_official、classify high→hard_veto、build_m67_report medium 待核+trace+consumption 映射);`a_short_weekly_pipeline.py`(normalize_candidate `semantic=` 参数、main `semantic_provider` 注入 thread);测试 6 个(high→否决+null、medium 待核不扣分、clear/unknown/None 中性、never-rescue、normalize 参数透传、main 端到端 semantic_provider)。真 cninfo provider 接入 = Slice 1b。

**Pre-Codex self-review: A-F checked** — A:defect-class×出口矩阵一次覆盖(high/medium/low/clear/unknown/None + never-rescue + 管线透传 + 端到端);B 连带:RISK_FAMILIES 加族 → grep 确认无硬编码 family 数/render 无严格 layer key 假设;新消费输入 `semantic` 已进引擎 consumption 映射(§4 完整性);163 tests OK 无向后兼容断裂;C 反向:medium 不当 clear 也不扣分、unknown 不当 clear、never-rescue 各有测;D:用 severity 枚举非关键词猜;F:py_compile OK、`git diff --check` clean、BOM/FFFD=0、`validate_m67_consistency` 每个语义出口都过。

**Boundary**:仅 M6.7(非生产/不进回测/advisory);不碰 EGS 生产打分、不进 production scoring/decision、不硬否决(`否决` 是 advisory 建议非生产 veto);不接 DeepSeek/不改 render/面板/Stage4;V14.2 frozen。

**Next**: `审查`。

## 2026-06-13 — Codex `审查 PASS` (semantic-risk Step1 analysis_input consumer validation)
- **Verdict/Action**: PASS; 未发现新的 material Required。`--analysis-input` 已走 analysis_input 契约校验并强制 `trade_date == --as-of`; weekly Stage 4 仍是 advisory-only 旁路。
- **Required**: `R-ASHORT-SEMANTIC-SUMMARY-ANALYSIS-INPUT-CONSUMER-VALIDATION-GAP` — 修复详情与 working-tree repaired 注记见 `docs/system_risk_register.md`(单一来源); no new Required.
- **Verify**: stale/future/schema-invalid no-write probes OK; semantic-risk+weekly+contract+governance+route suites = 158 OK; PowerShell ParseFile OK; py_compile OK; `git diff --check` clean; touched files have no BOM-at-start/FFFD; SESSION_LOG has one pre-existing internal FEFF in historical text.
- **Next**: `提交`.

## 2026-06-13 — Claude `修复` (语义 Step1 — --analysis-input 走契约校验 + trade_date 门)
- **Verdict/Action**: `--analysis-input` 分支改为 `validate_analysis_input_file`(schema+PIT 契约)+ 强制 `trade_date == --as-of`,均在取数/写盘前 abort;堵住旧/未来/坏批次候选池被贴当前 as_of。与 weekly pipeline 同门;`--watch-pool` 与 exactly-one 守护不变。
- **Required**: `R-ASHORT-SEMANTIC-SUMMARY-ANALYSIS-INPUT-CONSUMER-VALIDATION-GAP` — 完整详情见 `docs/system_risk_register.md`(单一来源,本处不复述)。
- **Verify**: 新增对抗测试:stale trade_date / schema-invalid 均 abort-no-write;正向用 schema-valid analysis_input(trade_date==as_of,300750 创业板被 drop);summary 套件 61 OK、加 weekly+governance 共 132 OK;`git diff --check` clean;BOM/FFFD=0。
- **Pre-Codex self-review**: A-F — A 按消费校验全维(schema-invalid + stale/future trade_date + 正向)一次覆盖;B 复用仓库既有契约函数(同 weekly pipeline)、未碰 cninfo/exit-code/Step2/lane;C 反向:正向匹配批次仍正常产出且 abort 不留文件;F:py_compile OK、diff/BOM 干净。
- **Next**: `审查`。

## 2026-06-13 — Codex `审查 FAIL` (semantic-risk Step1 analysis_input consumer validation)
- **Verdict/Action**: FAIL. `--analysis-input` wiring is directionally right, but the runner accepts stale/schema-invalid analysis_input and can label an old candidate pool as a new `as_of`.
- **Required**: `R-ASHORT-SEMANTIC-SUMMARY-ANALYSIS-INPUT-CONSUMER-VALIDATION-GAP` — full detail in `docs/system_risk_register.md` (single source).
- **Verify**: 83 tests OK; PowerShell ParseFile OK; `git diff --check` clean; custom stale-analysis_input probe wrote `as_of=20260612` from `trade_date=20260605`.
- **Next**: Claude `修复`.

## 2026-06-13 — Claude `起草` (语义风险 Step1 接入 weekly_screening — 旁路 Stage 4)

**目标**:把语义层 Step1(headless cninfo official_structured)接进生产周报脚本,每周自动产出官方结构化层;Step2(web_llm)仍需 LLM 在环另跑(不能纯自动化)。

**改动**:
- `runners/a_short_semantic_risk_summary.py`:加纯函数 `_watch_pool_from_analysis_input(ai)`(从 EGS analysis_input.candidates 抽 ts_code,按序去空)+ CLI `--analysis-input`(与 `--watch-pool` **二选一**,exactly-one 校验);供周报脚本直接喂生产 analysis_input。
- `runners/weekly_screening.ps1`:新增 **Stage 4 semantic-risk 旁路**(同 canary/tracker 模式):egs_main 成功后,以 `result/a_short/<as_of>/analysis_input.json` 为 watch pool,产 `research/results/a_short/semantic_risk_<as_of>/summary.json`。**advisory-only 旁路**:cninfo 失败/反爬不影响 exit code、不阻断周报;落 research 非生产 lane;`-SkipSemanticRisk` 可关。整体 exit code 仍取 egs_main。
- `docs/a_short_semantic_risk_coverage.md`:加"运行接入(cadence)"节。
- 测试:`_watch_pool_from_analysis_input` 顺序/去空/非 dict 容错;`main(--analysis-input)` 注入 cninfo_fetcher 无网产 summary(主板过滤:300750 创业板被 drop);exactly-one 源校验(neither/both → SystemExit)。

**Pre-Codex self-review: A-F checked** — A:watch-pool 双源(--watch-pool/--analysis-input)exactly-one 全覆盖 + 主板 drop 验证;B:grep 确认 egs_main/weekly_screening 原无 semantic 接入,新增不动主流程;旁路失败语义与 canary/tracker 一致(exit code 不受影响);C 反向:300750 创业板确被 drop、合法主板保留;D:无歧义 NL;**F 自catch**:python round-trip .ps1 把 CRLF→LF 致 PS5.1 ParseFile 在中文注释行报错,已转回 CRLF 并 `ParseFile` OK;204 tests OK、`git diff --check` clean、BOM/FFFD=0(.ps1 no-BOM CRLF)。

**Boundary**:仅 runner CLI 选项 + 周报脚本旁路 + 测试 + coverage 说明;advisory-only 不阻断周报、不进 result/a_short、不进 production scoring/decision;Step2 仍人工;V14.2 frozen;egs_main 主流程未碰。

**Next**: `审查`(复审旁路非阻断性 / lane 隔离 / exactly-one 源 / .ps1 CRLF)。

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
