# A-short 周末 pipeline(批②)— 设计 + 实现切片

**日期**: 2026-06-10
**父设计**: `docs/a_short_theme_overlay_phase5_design_spec_20260610.md`(§0 定位契约 + §3 四层 + §9 周频边界)。roadmap 步骤:把已审过的各块串成一次周末跑。
**类型**: design + code + tests(打包,一次 `审查`)。**授权:无 production 变更、无真钱、无 ship-gate、不接券商/不自动下单;真实前复权价抓取是用户授权 `执行`。**

## 1. 这一批做什么(把"零件"装成"流水线")
批① 已落:Slice A overlay runner、50ETF IV feed build、Phase 5 引擎(逐票 M6.7)。它们是**纯零件**,各自单测,但**没有一条线把它们串起来产出一周的报告**。批② = 这条线:

```
EGS top-N(analysis_input.json)
        │  normalize_candidate(逐票字段映射 → 引擎输入)
        ├── Slice A overlay artifact(eligible / crowding_hit)
        ├── IV feed(252d 分位,市场级:最新 trade_date 必须等于 price_data_through)
        ├── 前复权价序列(执行期抓,PIT ≤ as_of)
        └── 账户状态(available_cash / positions / Rule12 / Rule13;手工维护,不接券商)
        ▼
   Phase 5 引擎 build_m67_report(逐票)
        ▼
   一份周报 a_short_weekly_report(top-N 张 M6.7)←—— 用户只读这个
```

## 2. 关键设计决定
- **IV 是市场级,且必须与价格同钟。** 50ETF IV 252d 分位对当周所有候选取同一个最新值；`validate_iv_feed_freshness` 强制 IV 最新 `trade_date == price_data_through`，空/陈旧/错钟直接拒绝生成周报。IV-HV 标签仍是 advisory，Rule3 分位闸门不变。
- **normalize 是唯一映射点,且必须用 EGS *真实* 契约键。** `normalize_candidate(...)` 把 EGS analysis_input 候选翻成引擎归一化输入。**硬风险字段按真实契约**(对齐 `A-EGS/egs_main.py` 产出):`derived_flags.is_lock`→引擎 `limit_locked`、`event_risk.suspension.is_suspended`→`suspended`、`derived_flags.hard_veto`→引擎独立硬否决输入(即使分解原因未单独命中也硬杀)、`derived_flags.{overheat_flag,chasing_high,is_breakout,has_crash_veto}` / `event_risk.{holder_reduction.active_plan, delisting.st_flag/delisting_warning}` 照映。字段缺失 → 引擎保守/observe,不抛。**突破入场(#6-ii,v14.2 spec)**:`derived_flags.is_breakout` 现为 EGS 按 v14.2 spec §M3.2 算的突破信号(站稳 MA10 + 当日量>5日均量×1.2);引擎突破入场 = `is_breakout ∧ 引擎本地复查 close≥MA10`。**`derived_flags.vol_confirm` 不再门控突破**(它是 EGS 旧量能旁证 up>dn,仅进 EGS l4_score 评分);旧「is_breakout∧站稳MA10∧vol_confirm」门已废。
- **四道消费方/边界护栏(写入校验,不只声明):**
  - *IV feed PIT + 新鲜度*：先过 feed 一致性，再强制最新 IV 日与实际价格特征截止日完全一致；未来、陈旧、空 feed 均拒写。
  - *价格覆盖 + PIT/新鲜度不 fail-open*:`_fetch_price_series` 用 A 股 `asset="E"`,**provider 异常 → `SystemExit` 中止**(不吞成 `[]`);**每个 `trade_date` 校历法、拒任何 `> as_of` 的未来 bar、最新 bar 必须 == `as_of`(否则数据陈旧)→ 违反即中止不写**。`main` 的 `MIN_PRICE_OBS=20` 门默认仍整批中止；仅两种已证实的单票异常可先写入 `candidate_exclusions` 并不进入 reports/现金分配：(a) 当轮 `known_hit` 且 `observed_at==as_of` 的已证停牌；(b) 最新 bar 与全体非已证停牌候选的单一价格时钟一致、但可用历史不足。无最新 bar、陈旧/混合时钟、来源未知或 provider 异常仍整批拒跑，绝不静默退化成“观察”。默认 strict 模式中，provider 对陈旧的非空序列会在隔离前拒跑；该情形不会被停牌例外放宽。
  - *输出路径边界*:`write_weekly_report` 经 `_reject_production_output_path`——**输出路径由调用方指定(约定 `research/results/`),但路径含 `result/a_short/` 即硬拒写**(诚实窄契约:不声称"只写 research/results",只保证绝不落 production 根)。
  - *overlay 消费校验*:`--overlay` 经 `_load_validated_overlay` = overlay JSON schema + `validate_overlay_summary_consistency` + `as_of == weekly.as_of`(拒未来/陈旧)。
  - 逐票 `validate_m67_consistency`(§4 不变量);`write_weekly_report` 还对每张 report 单独跑 m67 schema。P2 公共摘要在 `main` 组装前由其专属校验器检查；若 schema 或消息漂移，则替换为当周的“证据不可用”摘要（再无法校验则只省略 P2 banner），不得阻断正式 M6.7 发布。
- **价格抓取在执行期。** 纯核(normalize / build / validate / write)合成 fixture 全可测;`main` 薄层读 artifacts + 抓前复权价(`--confirm-fetch-authorized`,可注入 `price_provider` 供测试),不在引擎/纯核里碰网络。正式 M6.7 候选与持仓固定使用 `as_of-120` 日窗口；只有启用 P2 且正式 JSON/Markdown/receipt 已成功发布后，P2 才独立请求 `as_of-450` 日影子序列。该影子请求失败只形成 P2 单票 no-count，绝不改变正式价格序列、持仓止损/归属或候选中止语义。

## 3. 输出契约(周报)

**运行时配置血缘**：`run_lineage.runtime_configuration` 是正式周报 schema 的必填字段，记录已加载 JSON policy 的总指纹及每份 policy 的 id、schema、路径和 SHA-256。它必须与 `analysis_input.source.runtime_configuration` 同源；不匹配时 weekly 在调用 provider 或写入前停止。它不是新的交易规则，也不会改变操作、星级、股数、否决或优先级。
`schemas/a_short_weekly_report.schema.json` 的 `run_lineage` 以 `run_id`、`candidate_digest`、`stage_status=complete`、`analysis_input`、`selection_bucket`、`iv_feed`、`account_ref`、`account_status`、`sizing_mode`、`account_snapshot`、`price_freshness` 绑定同一批候选、账户 bundle 快照与价格时钟，并附 `iv_freshness` / `market_regime`。`run_id` / `candidate_digest` 必须来自通过完整契约校验且已发布 `official_publish.json` 的 EGS `analysis_input`，不得把目录日期或路径相似当成同一次运行。账户摘要只暴露 snapshot id/digest、facts/decision 日期、持仓数与 integrity 状态；`market_regime` 同时记录 raw source 与 production effective 状态；unknown/missing 必须 effective=`shock`/震荡期。

不变量(`validate_weekly_report`):`n_stocks==len(reports)`;`boundary` 全 false;每张 `report.as_of==weekly.as_of`;`ts_code` 不重复;逐票 §4 不变量;读入的 feed 过 `validate_feed_summary_consistency`;`run_lineage` 一致(account_status=absent ⇒ sizing_mode=observation_only_no_account、sized ⇒ provided)。最终发布以 `weekly_m67.json`、对应 Markdown、`weekly_m67.receipt.json` 与可选 holding-ratchet 为同一事务：先全部生成并校验，再原子替换；任一替换失败即回滚，禁止只留下部分新文件。成功 receipt 必须标 `complete`，绑定同一 `run_id` / digest，并以 `outputs_digest` 固定 JSON 与确定性 Markdown 的 SHA-256 和字节长度；正式消费者只能复用共享严格验证器同一次读取形成的内容/摘要快照，不得关闭 canonical/Markdown 校验或验后重读。post-run sidecar-health 也是正式消费者：PowerShell 显式传本轮 `requested/skipped/not_run` 意图；该意图优先于目录旧态，`skipped/not_run` 时不得读取旧三件套或旧 pipeline manifest。只有本轮 requested 时，Python 才验证 canonical 三件套并从 snapshot 派生 `complete`、run identity 与 receipt digest；failed receipt、缺件或篡改分别记录诚实的 failed/unavailable，caller 自报不得覆盖。请求 M6.7 后的前置或 pipeline 失败由 wrapper 写 `failed` receipt 并以非零退出码结束。M6.7 是唯一正式运维周报，旧 analysis 报告仅作 research 输入。

## 4. 边界
- 非 production、不真钱、不 ship-gate、不接券商/不自动下单;A-short 仍 `risk_filter_only`,M6.7 为辅助建议、**edge 未验证**。
- 不动 `egs_main` / V14.2 / final_score / tier / admission(冻结)。
- **新建仓资格**：仅 `analysis_input.candidates[].analysis_role=final` 可进入 Phase5 新建仓和现金分配；`watch` 复用观察路径显示“非 final，仅观察”，不得递补。已有持仓仍按持仓管理输出。
- **账户策略配置**：手工账户转换器只读取 `presets/a_short.yaml::position_management` 的三个必需值；文件、区块、键、重复键、数值类型或范围任一异常均拒跑，实际三值写入 `lineage.config`。
- 真实前复权价抓取(`pro_bar adj=qfq`)= 用户授权 `执行`;输出路径调用方指定(约定 `research/results/`),**绝不写 production 根 `result/a_short/<date>`**(写入路径硬校验)。
- 本切片 = 设计 + pipeline 纯核(normalize / build_weekly_report / validate_weekly_report / write_weekly_report)+ 周报 schema + `main` 执行接线 + 测试。
- **仍未来:** 常态化每周授权 `执行` 的正式周报产出;comparison-track ≥12 周与 12 个月 ship-gate 的前向验证(纯执行,等数据)。(首次端到端授权 `执行` 已跑通并据此修复 §5 首跑缺口。)

## 5. 首跑缺口修复(2026-06-11 follow-up,首次端到端 `执行` 后)
首跑(as-of 20260609)暴露并修复:
- **突破入场口径(历史 → #6-ii)**:`vol_confirm`(up/down 量能,egs_main)早已导出到 `derived_flags.vol_confirm`。**#6-ii(2026-06-16)起**:`is_breakout` 由 EGS 按 v14.2 spec §M3.2 算(站稳 MA10 + 当日量>5日均量×1.2),引擎突破 = `is_breakout ∧ 本地 close≥MA10`;**`vol_confirm` 已从突破门移除**(仅留作 EGS l4_score 评分输入)。旧「is_breakout∧站稳MA10∧vol_confirm」三门口径**已废**。
- **market_regime raw/effective 分离**：analysis_input 的 raw status 保留审计；unknown/missing 的 production effective 固定为 `shock`/震荡期并降级减半。`weekly_screening.ps1` 把同一个 effective V14.2 状态显式传给 comparison runner，V14.3 仍 comparison-only，不得拿 literal unknown 当生产基线。
- **账户状态契约**：`--account` 只接受 account+lineage 原子 bundle；真实 facts 日期不再重标为决策日。Rule12 缺失、bundle digest 错配、total_equity/current_gross_exposure 缺失均拒跑。0 现金仍管理已有持仓；对账阻断只禁止新开仓。
- **额度、原因与价位**：新仓股数取现金、A-short bucket 剩余额度、单票上限和流动性上限的最小值；hard veto / downgrade / observe / sizing block 分层记录。持仓止损从 entry stop 起，只消费 entry_date 后高点并与跨周最终 ratchet 同值；低吸/突破 fallback 目标与 RR 都用同一 entry_high 基准。
- **控制台中文乱码**:非代码缺陷,是 Windows 控制台 GBK 显示;产物已是干净 UTF-8。运行 egs_main 时设 `PYTHONIOENCODING=utf-8`(或 chcp 65001)即可避免日志乱码。
- **Slice A overlay 数据装载接线(M6.7 赛道红利星级)已接线**:`build_overlay_summary_from_panels` 在 EGS run 内(pit-mode)写 `result/a_short/<as_of>/overlay.json`,`weekly_screening.ps1` 存在即传 `--overlay`,pipeline 经 `_load_validated_overlay` 消费(见 §2 overlay 消费校验 + `docs/README.md`)。
- **仍未来(不在本修复)**:EGS regime 分类器(生产 egs_main 仍可能输出 `unknown`;V14.3 分类器在 slice 2a/2b 在建,尚未生产接线)。
