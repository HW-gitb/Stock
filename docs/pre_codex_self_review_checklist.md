# 交 Codex 前 self-review checklist(Claude 起草/修复 必走)

**存在目的**:减少同类问题反复被 Codex 点名(本项目反复出现"修了被点名的实例、没修整类"+"修复不追连带影响"两类失败,典型如 Slice-1 PIT 4 轮、Slice-2b-i 关键词 6 轮)。**测试集通过 ≠ 设计闭环通过**;每次把代码/文档交给 Codex `审查` 前,逐项过下面 6 关,自跑对抗,确认后再交。

适用:每次 `起草` 和每次 `修复`。重点是 **`修复` 时**——一条 finding 修完后,先别急着交,由主线程跑 B/C/E；不要把每次小修都变成新的独立审查窗口。

---

## 0. 执行速度纪律(speed discipline)

本节是执行/修复时的默认节奏,用于避免把时间耗在环境探测、重复验证和卡住的独立自审上;不改变 A-F 设计闭环要求。

1. **先固定测试 Python,再跑测试**:进入执行/修复后只用固定主 Python `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`；测试通过 `.tools/run_unittest_with_repo_pythonpath.cmd`，其他项目命令通过 `.tools\codex_main_python.ps1`。不要试裸 `python`/`py`，不要设置 `STOCK_TEST_PYTHON`，也不得回退到 Codex bundled/PATH runtime。
2. **红绿节奏保持窄**:先写能复现 Required 的 focused 红测,最小修复到 focused 绿;所有 docs/register/SESSION_LOG 写完后再跑一次对应固定包。固定包层级、full-lane 触发条件及 reviewer 的独立复跑义务只以 `AGENTS.md §Verification tiering and one-full-run rule` 为准。除非后续代码/契约又变了,不要因为只补交接文字反复跑同一大包。
3. **stable-slice single-window contract**:主线程完成实现、same-class closure、focused 验证且 diff 稳定后，才安排 **exactly one scheduled independent review**；迭代红绿、同类排查和固定包均由主线程完成，不在中途起/唤醒 agent。
4. **独立自审默认轻量**:该唯一窗口只给当前稳定 diff、当前 requirement、same-class closure 和必要文件清单;默认 `fork_context=false`,不 fork 完整历史,不让它 repo-wide 发散。
5. **self-review anti-hang contract**:独立自审 prompt 必须硬限制为 `current-diff-only`(只审当前 diff + 当前 requirement + same-class closure),输出只允许 `PASS / FAIL` 或 `FAIL: <must-fix list>`;明确 `do not run big packs`,固定包测试证据由主线程负责。prompt 里要列明本 slice 文件清单,并写清 `unrelated dirty files` 不属于当前审查范围,避免子 agent 因混批犹豫。
6. **main-thread class-closure after FAIL**:唯一窗口给出 Required 后，由主线程一次按类完成修复、B/C/E 和受影响验证；**no content-driven re-review**，不得因逐条修复而反复唤醒同一 agent。之后直接进入项目规定的 Claude Code 独立审查/提交门。
7. **独立自审限时**:轻量自审 `2-3 minutes`(2-3 分钟)无结果即 `close and restart once`；该 restart 仅限同一已排程窗口的超时/传输故障，不得作为内容性复审。`second timeout` 仍无结果时 `do not keep waiting`,停止等待并在 SESSION_LOG 说明 timeout。此时走 `main-thread checklist fallback`:主线程按 A-F/B2 自查 + 已跑固定验证包作测试证据,不得无限等 agent。子 agent 只有通过上述固定主 Python launcher 且获批准的 host-process execution 时才跑测试;否则只做逻辑/契约审查。
8. **documented material-new-risk exception**:只有修复引入新的、独立的安全/资金/生产边界疑点时，才可额外开一个独立审查窗口；SESSION_LOG 必须写明新风险类别和为何原窗口不能覆盖。不得以“更放心”或未完成主线程排查为由加开。
9. **Proof-of-use 必写速度证据**:SESSION_LOG 的 `Pre-Codex self-review` 行要写明是否使用轻量自审、是否发生 timeout/重启、是否触发 main-thread checklist fallback、固定包是否集中一次跑完；若开例外窗口，写明 material-new-risk 理由。这样未来审查能看见是否又退回慢路径。

## A. 类不修实例(class-not-instance)
改 classifier / validator / enum / 形式集 / 布尔门 / 不变式 时:
1. 先写下**完整矩阵**:`缺陷类 × 所有出口`。出口至少含:per-row → per-candidate → **聚合/batch** → validator → schema → render/panel → 下游消费者。
2. **每个 cell 一次覆盖、一条测试**。不要只覆盖被点名的那个输入/那个出口。
3. 问自己:"被点名的 finding 属于哪个**一般类**?这个类还会从哪些输入/出口冒出来?"
4. **可枚举命名集 → 全员一次覆盖**(本会话反复栽在此处):若 finding 点名的是**某个可枚举集合里的一/几个成员**(4 档 profile 里的 2 档、9 个 enum 值里的 1 个、K 个字段里的 1 个、N 个出口里的 1 个),**先列全该集合的所有成员**,对**每一个**施加并验证同一修复——`const-pin` / 严格化 / 拒未知 / 改 enum / 加不变式 这类**结构性**修复尤其要**全员一次到位**,别只动被点名的成员。**Proof-of-use 的 A 行必须写出枚举的完整集合 + 确认全覆盖**(如「profile 4 档全 const」「§9 动作 9 值全钉」),**不许只写「A checked」糊弄**——让"修没修整类"对用户/Codex 可检。
5. **const-pin 必须落在 schema(自足校验器)本身、不止测试**(治理/契约 schema 连撞两次):被治理的**身份/常量**(权重 / 枚举 / 列集 / 节集 / 不变式 / banner 身份…)要 **const-pin 进 schema**——schema 是可复用校验器、是上面矩阵里的一个**出口**;只在测试里断言「当前这份 preset 对」、而 schema 仍接受 **same-shape drift**(同形改值 / 改名 / 乱序),= 漏了 schema 这个出口(任何只拿 schema 校验的消费者会放行)。测试留给 **draft-07 表达不了的跨字段不变式 + 单一来源/三角守护**(如 `schema-const == preset == design` 三角)。**非 ASCII / Chinese 内容别因「怕硬编码」退回只靠测试守**——从权威源字节生成 preset + 三角测试兜转写即可,不是把 const 踢出 schema 的理由。
- 反例(本项目真实):PIT 在 future 出口修了,漏了 bad-shape/unparseable/status;feasibility 在 per-candidate 修了,漏了 batch;**(本会话)scoring-profile `const-pin` 钉了 4 档里的 balanced+theme_off 两档就交,漏了 theme_plus/aggressive → Codex 同类 re-FAIL**。
- 反例(schema 欠钉,本会话**连撞两次**):scoring-profile 权重起初只 shape-only;weekly_report 节集 / banner-tag / lifecycle 规则只靠测试守、schema 仍接受 same-shape drift → Codex `审查` 各 FAIL 一轮。根治 = 治理身份**全 const 进 schema**、测试只做三角 + 跨字段不变式(= 上面 point 5)。

## B. 连带 grep(ripple grep,机械步,**改完必做;一次全仓 + 贴零残留证据**)
任何**行为 / 符号名 / 机制 / 规则措辞**改动后,做**一次全仓 grep 旧形态**(`rg` 跨 `*.py` + `*.md` + 测试),逐一更新或确认,并把**零残留证据**(实际命令 + `0 hits`,排除档案/历史/无关同名)贴进 proof-of-use 行——"我 grep 了"不算,要"0 残留":
1. **旧符号名**(重命名/删除的常量、函数、字段)→ 期望 0 stale 引用。
2. **所有断言旧行为的文字(不止 .md)**:README route 行、`system_risk_register.md` 活动条目、design 文档、**runner docstring/注释**、**`test_*` 的 docstring 与注释(测试也是教学面!)**、**emit 到输出的字符串字面量**(如 `machine.consumption.*`、log/print、面板/用户可见文案——它们会跑到产物里,不是注释)、SESSION_LOG 顶部活动 gate(历史 append-only 不改)。
3. **下游消费者**:改的函数/字段/schema 谁在用 → 确认仍成立(含跨 runner import、weekly pipeline、面板)。
4. **已跨轮复发的规则 → 加一条全仓 guard 测试禁旧形态**(把 B2 单一来源/守护用到整棵树),让 partial fix 直接测试红,不靠记忆逐面发现。
- 反例 1:换最窄策略改了行为,却把 README/register 里旧的"浦发→clear"结论留着 → 又一轮。
- 反例 2(本会话):evidence-full 规则只扫 runner+.md,漏了 **`machine.consumption.semantic` emit 字符串**与 **`SemanticIntoM67` 测试 docstring** → Codex 同 R-ID re-FAIL 3 轮。根治=第 2 点显式含这两面 + 第 1 句的"一次全仓 + 零残留证据"。

## B2. 单一来源 + drift guard(generalized)
**Materiality gate (2026-06-14)**: ripple grep is evidence gathering, not an automatic "zero every stale word" mandate. Treat drift as blocking only when it affects a current authority contract, required route/startup doc, run entry / CLI help, schema description used by consumers, test assertion / guard explanation that defines expected behavior, live-state gate, or another surface that can mislead execution or review. Clearly historical / archived / superseded text and low-impact comments may be left alone or listed as Optional; do not create Required work for doc drift that has no system-quality or review-quality impact.

**活跃设计文档 current-state gate (2026-06-14)**: 如果某个设计文档仍在 `docs/README.md` / `CURRENT` / 当前切片中作为活跃入口,它的"仍未来 / 未来工作 / 未接线 / stub"列表必须只包含真实未完成项。凡代码、schema、route doc 已证明完成的事实(如已接线、已消费、已 schema 化),不得继续出现在未来项里;要么改成已完成事实 + 指针,要么把整篇文档降级为 historical / superseded 并移出活跃入口。已跨轮复发的 completed-vs-future 类错误必须加 registry/guard,不能只改一个句子。

**一个会变的事实**(行为契约 / 校验门 / finding 详情 / 状态)**= 一个权威位置 + 一个机器守护禁止他处复述**;所有其他位置只许"点名 + 指过去",不复述步骤/矩阵。
1. **权威位置按事实性质选**:代码行为→紧贴代码的 docstring(被拒绝测试钉住);跨文档契约→单一 contract 锚点;material finding→`system_risk_register.md`;live-state→`SESSION_LOG` 顶部。
2. **守护必须按局部块**(表行/段落)校验、**不是整文件**——整文件粒度会被"同文件别处有正确句"骗过(见 `R-ASHORT-SEMANTIC-PANEL-GUARD-FILE-LEVEL-FALSE-NEGATIVE`),并配一个 **planted-failure** 测试证明其局部性。
3. **目标不是"靠警惕永不再犯"**:同类漂移必须被守护或单一来源机制挡住;**出现新类别时一次性沉淀成规则/测试,绝不退回靠人记**。
- 反例(本会话):同一规则同时写在 `AGENTS.md` item 7 与本 checklist,靠 guard 钉两处——后来收敛为 item 7 只点名、本 checklist 做唯一正文(单一来源)。

## C. 反向失败自检(reverse-failure)
交付前问:**这个修复有没有制造相反方向的错?**
- 误报 ↔ 漏报、over-suppress ↔ under-suppress、too-strict ↔ too-lax、修了 look-ahead 却把合法当日数据也挡了。
- 给反方向补一条测试。
- 反例:为压 routine 误报加一刀切负向模式 → 把真风险整改件压成 clear(漏报,比原问题更严重)。

## D. 歧义自然语言分类:别穷举关键词
对"标题/文本是不是某类风险"这种**歧义自然语言**判断:
- **不要**靠枚举关键词/形式集去精判(必然 whack-a-mole,被点一个补一个)。
- 走**最窄安全侧**:只在能确定的最小集合上动作,让残余误差落在**无害方向**(如 advisory 层宁误报、交 LLM 层降级,绝不漏报)。或直接**交 LLM 层**精判。
- 反例:routine↔adverse 关键词走了 6 轮才转最窄。

## E. route-doc 单态(no accretion)
durable route docs(`CURRENT`、READMEs)+ register 活动条目**只陈述当前最终机制 + settled 事实**:
- 修复流水账(round 1/2/3…)**不要**逐条堆进活动条目正文,造成新旧机制并存冲突。
- 历史压成一句 **"SUPERSEDED interim: <旧机制> 已删除/已被替代,勿重引入"**。
- **transient next-actor / next-command gate**(待审查 / before commit / 谁审谁提交 / routed-to / 下一条命令是谁的 X)只进 SESSION_LOG 顶部,**绝不进 CURRENT 或 durable route docs**。
- **例外**:`system_risk_register` 是持久 open-risk 队列,**可**记 stable open-risk status + closure criteria(如 "closure on Codex PASS + 提交");这不算 transient gate。(详见 `AGENTS.md` route-doc 约定)

## F. 既有 pre-flight sweep(仍适用)
非有限值(NaN/Inf)/ canonical 日期严格性 / 跨字段不变式 / API footgun(generator 双消费、静默去重、旁路)/ 设计自查(新约束是否误拒合法正常态)/ **doc↔behavior 一致**(refactor 后 re-grep 旧函数名)/ **编码:UTF-8 无 BOM**(查文件前缀 `EF BB BF`,**不只查 U+FFFD**——Windows PowerShell `Out-File -Encoding utf8` 会写回 BOM;改文件后用 .NET 裸字节读写避免)+ 无 mojibake / **`git diff --check`**(末尾空行 / 行尾空白 / 冲突标记——Codex 会跑,pre-flight 先跑)。

---

## Proof-of-use(留痕,硬契约)
每次 `起草`/`修复` 的 SESSION_LOG entry **必须**带一行 `Pre-Codex self-review: A-F checked / N-A`,并附实际证据(尤其 **B/C/E**):跑的 grep 命令 + 命中数、加的反向测试名、route-doc 单态确认。无此行 = 没过门。让"做没做"对用户和 Codex 可检查。

**收尾自问(一句话门)**:"我这次是修了**整类 + 追了连带 + 查了反向**,还是只让这一条 finding 消失了?" 后者就别交。
