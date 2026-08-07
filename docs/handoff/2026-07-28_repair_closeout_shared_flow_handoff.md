# Repair-closeout shared flow / lane-specific verification handoff

## 2026-07-29 append: K3-R85 repair — Markdown-wrapped `BLOCKED` reasons

K3-R84's parser repair correctly split `BLOCKED: <reason>`, but checked the reason before removing outer Markdown emphasis. A real parser probe showed that bold and italic forms of an otherwise rejected fixed reason passed. The repair is deliberately narrow: after the existing backtick and punctuation normalization, strip only outer `*` / `_`, then re-trim punctuation before the existing placeholder comparison. It does not change the `door=` contract, introduce a general quality heuristic, or change any lane behavior. The planted controls include bold and italic fixed reasons, English and Chinese forms, a punctuation-inside-emphasis form, and a meaningful emphasized blocker that must stay accepted. The initial final-door run also showed that the inner split overwrote the outer entry iterator: a valid blocked repair entry before another repair entry raised `IndexError`. That variable is isolated as `blocked_parts` and a two-entry green control now pins the iteration contract. Focused document-governance = 41 OK before the final two-guard handoff run; no full lane or external action is warranted.

## 2026-07-29 append: K3-R84 review FAIL — blocked door must name its reason

The new `door=` handoff rule is correctly unconditional and does not need a changed-surface mapping table, but its initial parser treats a whole `BLOCKED: <reason>` string as opaque. A fixed-main-Python probe against the shipped guard showed both `door=BLOCKED:` and `door=BLOCKED: TBD` return no offender, although the contract says the reason must make the blocker visible and empty / `TBD` are red. K3-R84 is therefore Required: parse the `BLOCKED:` form, reject a missing or placeholder suffix (and bare `BLOCKED`), retain a real nonempty reason, and pin all cases with named controls. The pre-commit two-guard focused superset was 55 OK; this is a guard false-negative, not a lane/runtime/provider issue. No full lane or external action is warranted.

## Scope and decision

The repair-closeout matrix is one shared execution/repair process for A-short and US-short. `matrix=`, `register=`, and `handoff=` record the common closure responsibility; the same `SESSION_LOG` adoption marker and doc-governance guard enforce future repair entries.

`focused=` and `full-lane=` remain lane-specific evidence. They must name the system actually touched, its test package, and its data boundary. A-short preflight, Python, provider, or full-lane commands are not defaults for US-short, and the reverse is also prohibited.

## Full-lane disposition

`full-lane=` is mandatory evidence of the decision, not an unconditional full-regression tax. When AGENTS rule 3 triggers, record the one matching lane run and its result. When it does not trigger, record `not_triggered: AGENTS rule 3; reason=<specific change surface>`.

## Boundary and verification

This clarification changes only process documentation and guard anchors. It changes no A-short/US-short business rule, provider authorization, live weekly operation, account/order path, or ship gate.

## 2026-07-28 append: full-pack external dependency preflight (lane-scoped repair)

The first global preflight was rejected: it made A-share-only provider absence block US-short focused work. The repaired `external_test_dependency_error(lane)` selects `REQUIRED_TEST_MODULES_BY_LANE`; `akshare` and `tushare` are a_short-only, while shared modules such as `jsonschema` remain in both sets. The check now exists only in `full_pack_ledger` `run`/`check`, before cache reuse, prepare, or unittest spawn; `bounded_unittest.run_unittest` remains a generic focused runner.

The closure pack has named controls for: A-share provider absence blocks a_short full but not us_short full/focused; shared `jsonschema` absence blocks both full lanes; and hollowing lane routing makes the named a-share/us-short isolation test red. This is tooling only; no provider call, market-system behavior, or full lane run is triggered.

## 2026-07-28 追加：全量测试入口的可观测性与调用纪律（full_pack_ledger + AGENTS rule 1/4）

### 改了什么

- `.tools/full_pack_ledger.py::run_full_pack`：`prepare()` 的返回值接住为 `prepared_fingerprint`，并在**真正 spawn unittest 之前**打印一行 `START lane=<lane> deadline=<N>s fingerprint=<前12位>`（`flush=True`）。它排在依赖检查与 cached-green 早返回之后，所以只有确实要起进程时才出现。
- `.tools/full_pack_ledger.py::main`：`run` 分支的准入从 `len(argv) >= 8 and "--" in argv` 放宽为 `argv[1] == "run"`，随后**显式**拒绝两类错参——缺 `--`、`--` 不在第 6 位——各以一行 `REFUSED` + exit 2 收场，不再退化成打印 `__doc__`。
- `AGENTS.md` 分级规则两句：rule 1 追加「focused pack 必须显式点名每个被触及的 schema 与 effect-contract 守卫，不得由 lane 名自动推断」；rule 4 追加「直接调用该参数向量，不要用 `Start-Process` 包一层、也不要把它拼成单个 `ArgumentList` 字符串」。

### 为什么改

全量入口此前在 spawn 前完全沉默，等待期无法区分「正在跑」与「卡住/没起来」，而 AGENTS rule 5 又明令不许靠扫描 PID/CPU 猜进度——于是只剩干等。错参走 `__doc__` 也让调用错误看起来像用法提示而非拒绝。rule 1 那句来自本会话实证：6B 首轮的 focused pack 差点漏掉 `test_a_short_effect_contract`（谓词哈希守卫），靠 lane 名推断不出来。

### 验证命令与结果

- 审查方亲跑 focused 超集 `.toolsun_unittest_with_repo_pythonpath.cmd tests.test_full_pack_ledger tests.test_bounded_unittest tests.test_doc_governance_guard tests.test_review_tiering_enforcement tests.test_route_doc_ledger_status_consistency` = `104 OK / 5.9s / exit 0`。
- 审查方自写 CLI 反向探针（固定主 Python 直调，六种错参形态）：`run`、`run <4 args>` → `REFUSED missing --`；`run … 30 --`（`--` 在第 6 位但其后为空）→ `REFUSED run requires unittest arguments after --`；`--` 错位 → `REFUSED expected run <lane> …`；把 discovery 收窄成 `test_bogus*.py` → `REFUSED must exactly use unittest args [...]`；`timeout=99999` → `REFUSED full timeout must be 1..1300`。六种全部 exit 2 且无进程起飞。
- 静态核：`prepare()` 确实 `return fp`，故 `prepared_fingerprint[:12]` 不会炸；`record()` 仍只在 `status == "PASS"` 且前后 fingerprint 相等时写；旧 `len(argv) >= 8` 分支全仓零残留。

### 失效的旧结论

「`run` 的错参会打印用法文档」已失效：现在一律是单行 `REFUSED` + exit 2。分支放宽不等于放松——`run_full_pack` 自身的空参、未知 lane、discovery 参数必须逐字相等、timeout 上界四道门都在放宽后的路径上仍然生效，实测已逐条坐实。

### 下一步注意事项

- `START` 只是「进程要起了」的诚实信号，**不是**进度或 PASS 证据；AGENTS rule 5 的判据仍是真实测试输出 + 终态退出码。
- 本刀不改依赖门、不改指纹口径、不改 PASS-only 记账，故未触发 rule 3 全量。

## 2026-07-30 追加：full-lane 硬上限降至 800 秒

### 改了什么 / 为什么

- 用户明确把 full-lane 全量测试硬上限从 1300 秒降至 800 秒。单一执行常量 `bounded_unittest.FULL_MAX_SECONDS` 已改为 `800`，`full_pack_ledger.run_full_pack` 继续直接消费该常量，因此 `801` 起拒绝且不会启动测试。
- focused 默认仍为 300 秒，已批准的显式慢 focused 包上限仍为 1300 秒；两者不再错误共用 full-lane 常量。审查提示、AGENTS active contract、risk-register active contract 与机器守卫已同步为 full=800。
- 历史 `deadline=1300s` 运行记录保留为当时事实，不回写伪造历史。

### 验证命令 / 结果

- 固定主 Python 经 bounded launcher 最终跑 `tests.test_bounded_unittest tests.test_full_pack_ledger tests.test_review_tiering_enforcement tests.test_doc_governance_guard tests.test_route_doc_ledger_status_consistency`：`108 OK / 5.3s`。
- 交接门 `tests.test_route_doc_ledger_status_consistency tests.test_doc_governance_guard`：`55 OK / 1.1s`；三个相关工具模块 `py_compile` 通过。
- 反向控制明确钉住 `FULL_MAX_SECONDS == 800`、`FOCUSED_MAX_SECONDS == 1300`，并验证 full timeout `801` 得到 `full timeout must be 1..800 seconds`。

### 失效旧结论 / 下一步注意事项

- 旧的“当前 full-lane 上限 1300 秒”已失效；仅历史命令与历史结果中的 1300 仍有效。
- 本刀只收紧测试基础设施的运行时预算，不改 discovery selector、测试覆盖、业务代码、provider 边界或 PASS-only 记账。它不触发 lane full regression；下一次 rule-3 full run 必须在 800 秒内完成，否则诚实返回 `TIMEOUT`，不得抬上限或把 UNKNOWN 当 PASS。
- 唯一 scheduled 独立自审曾指出审查入口仍写 focused“最多 300 秒”；主线程已按类改成“默认 300 / 显式慢包最高 1300”，并在 review-tiering 守卫中同时钉住 300、1300、800。该窗口随后按 checklist 关闭，不做内容驱动复审。
## 2026-08-04 追加：focused/full 证据机器化门禁

### 改了什么

- 新增 `.tools/verification_receipt.py`；bounded launcher 在真实 focused PASS 后写入本地 receipt，绑定精确 unittest args、`Ran N tests`、固定 Python、当前非文档代码指纹和派生 bundle。
- `full_pack_ledger.run_full_pack` 现在对所有调用拒绝自由文本、缺失/过期/篡改 receipt；effect producer/consumer/schema surface 强制同一 focused pack 同时包含 `tests.test_a_short_effect_contract` 与 `tests.test_a_short_effect_consumer_probe`。
- full process 启动前自动执行 `git diff --check` 与 changed-Python `py_compile`；launcher 清除 PATH/PYTHONPATH 污染，仅保留 pinned Python、固定 Git 和 Windows 工具；pre-commit 对 staged 非文档改动硬阻断无当前 receipt。

### 为什么改

旧流程把 focused 证据当自由文本，无法机器识别“实际跑了什么”，也无法阻止 effect consumer 漏包；这会让 full lane 的执行门依赖人工记忆。此次只补证据和门禁，不改变业务规则或 full-lane 条件。

### 验证命令 / 验证结果

- 固定主 Python：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`。
- `.tools\run_unittest_with_repo_pythonpath.cmd tests.test_verification_receipt tests.test_bounded_unittest tests.test_full_pack_ledger tests.test_a_short_preflight tests.test_doc_governance_guard`：`Ran 102 tests in 8.533s` / `OK`；receipt `receipt:b4af4edcf4a0e314c39595f6`；`.tools\verification_receipt.py` 自校验 `PASS - OK`。
- `git diff --check` 与 changed-tool/test `py_compile` 均 exit 0；full lane `not_triggered`，因为本刀仅为流程工具/门禁改动。

### 失效旧结论

旧的 `focused=<文字>` 不再是 full-pack 合法证据；full command 必须传 `receipt:<receipt-id>`。focused green 仍不等于独立 review、provider/live、production 或 ship-gate PASS。

### 下一步注意事项

Claude Code 独立审查本轮工具、bundle surface 映射、receipt integrity 和 pre-commit 行为；review PASS 后由 reviewer/committer 按项目规则提交。`OPEN/NOT_VERIFIED`、provider/network/live/account/sub-agent 均保持边界。
## 2026-08-04 Addendum: final focused evidence correction

The prior `102 tests` / `receipt:b4af4edcf4a0e314c39595f6` line was an intermediate run. The final combined focused pack, including route-doc governance, returned `Ran 116 tests in 11.561s` / `OK` under `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe` (`Python 3.13.8`) and wrote `receipt:ac0a3b275409bb88adaf36f9`. The receipt self-check returned `PASS - OK`; `git diff --check` and changed-tool/test `py_compile` returned exit 0. Full lane remains `not_triggered` under AGENTS rule 3 for this process-tool-only repair. Independent review and submission remain `NOT_VERIFIED` / `NOT_PERFORMED`.

## 2026-08-04 Addendum: internal prepare receipt hardening

The remaining process bypass was in the internal `full_pack_ledger.prepare()` API: the retired CLI and normal `run_full_pack()` path were guarded, but a direct caller could still pass free-text focused evidence and write ledger state. `prepare()` now requires and validates the current `receipt:<receipt_id>` against the current code state and pinned Python before writing; `run_full_pack()` passes the same receipt path through. The new negative test proves free text is rejected before ledger creation. Fixed-Python focused evidence: `Ran 117 tests in 9.256s` / `OK`, receipt `receipt:2032d1904f546c7cbeafe54c`; receipt self-check `PASS - OK`; `git diff --check` and changed-tool/test `py_compile` returned exit 0; full lane remains `not_triggered` under AGENTS rule 3. Independent review and submission remain `NOT_VERIFIED` / `NOT_PERFORMED`.

## 2026-08-06 追加：全量 lane 并行 runner 方案（设计已定，未开工）

### 为什么打这一刀

a_short 全量最近一次记账是 `PASS 2498 tests / 826.4s`，硬上限 860s——**贴着天花板**，一次机器争用就翻成 TIMEOUT（2026-08-05 已实际发生过一次 `exit=124 tests=UNKNOWN`）。内容键缓存那一批（`R-ASHORT-LANE-SPEED-REGRESSION-CONTENT-KEYED-CACHES`）已经把单点重算削掉，剩下的是**结构性浪费：16 核机器只用 1 核串行跑**。

本刀不改任何一条测试断言，只把「一个进程串行跑全 lane」换成「按测试模块分给 N 个进程并行跑」。墙钟下界 = 最长单模块（提速刀前实测 theme ≈224s、weekly ≈200s），预期 826s → **250~300s**，860 上限由贴地变宽裕。

### 开工前必须知道的四条（起草复审时核出，不照抄原始方案）

1. **收据自毁已有现成机制，别再发明。** 每个 worker 都是 bounded 子进程 → 每个都会写 `.tools/state/focused_acceptance_receipt.json` 互相覆盖。这正是 2026-08-05 修过的 `R-TOOLS-PRECOMMIT-RECEIPT-SELF-CLOBBER`，修法是 `STOCK_BOUNDED_UNITTEST_ACTIVE` 嵌套标记（覆盖 launcher→launcher 任意深度）。driver 给 worker 带上该标记，收据由 driver 一份收口。**这是实现时第一个会撞上的东西。**
2. **计数相等门只能挂在绿路径上。** worker 内保留账本固定旗标 `-b -f --durations 25`，红模块会提前停，其 `Ran N` 必然小于发现数。精确语义：**`Σ Ran_i == 串行发现总数` 是「记 PASS 的前置条件」**；红路径本来就是 FAIL、账本本来就只记 PASS，计数门不适用。不写清这句，实现方会让两个门互相打架。
3. **串行尾巴 / 豁免清单不许手写。** 隔离扫描扫出的「临时改真仓库文件」类测试若不全部密闭化、留一部分串行跑，那份清单**必须由扫描器派生并机器校验**。手写枚举无守卫 = `R-ASHORT-ADMISSION-REGISTRY-CACHE-AUTHORITY-TUPLE-IS-UNGUARDED` 同一个类，别在同一周再造一个。
4. **顺序**：本刀动 `.tools/`（跨 lane 共享面，us_short 全量同走这套）并要改若干测试的 fixture 管道。**等 ashort_r1 当前序 19 修复轮独立审查 PASS 并合入 master 之后再开工**；2026-08-05 已经发生过三方同树写同一文件的争用。验证矩阵须在 a_short 与 us_short 两个 lane 各跑一遍对照。

### 刀 T1｜隔离扫描器 + 分类处置（纯离线，先行）

这刀才是真正的工程量所在——并行安全要求测试之间不共享可变状态。

1. 新增 `.tools/test_isolation_scan.py`：AST/文本扫 `tests/**` 的真实仓库写盘模式——`write_text` / `write_bytes` / `open(..., 'w')` / `os.replace` / `shutil.*` / `os.utime` / `json.dump` 落到 ROOT 相对路径、`mock.patch` 之后又写盘等。输出「模块 → 写盘证据」清单。
2. 逐命中分类：**A** = 已密闭（`tempfile`），排除；**B** = 写共享 gitignored 固定路径（`state/`、`provider_samples/`、`result/`）；**C** = 临时改真仓库文件再还原。已知 C 类至少一条：准入注册表 snapshot 腿（临时改 preset 字节）；us_short 那条「测试读操作员状态」的长期假红（`R-USSHORT-SOFT-DISCOVERY-LIVE-CLI-TEST-READS-OPERATOR-STATE`）是同类根因。
3. 处置：C 类逐个改密闭（临时树 / 注入路径，**只动 fixture 管道、断言零改**，每个改动点在 handoff 列名）；B 类能改则改，难改的进串行尾巴。
4. 守卫：串行尾巴清单 **== 扫描器当前命中集**（派生而非手写），配植入对照——给临时样本模块加一条仓库写，扫描器必命中。理想终态是空集。

### 刀 T2｜并行 driver（只在 `.tools/`，CLI 契约不变）

1. `full_pack_ledger run` 的执行层内加并行模式（或 `bounded_unittest --shard-parallel N`）：**selector 用 `--` 之后的原样参数做 discovery**，得模块清单 + 每模块 case 数 + 总数 T，**绝不自己发明 discovery 模式**（含 `tests/schema/`、`tests/phase6/` 子包）。
2. 调度：worker = 8（常量，烧机后可调 6-10），**最长优先**——耗时表取上一次 ledger PASS 记录的 `--durations` 输出，缺省按 case 数排。theme / weekly 两个重包必须最先派，否则它们决定尾部。
3. 每 worker = 现有 pinned Python + bounded 子进程，旗标 `-b -f --durations 25` 原样不变，环境带 `STOCK_BOUNDED_UNITTEST_ACTIVE`，输出各落各文件。**worker 输出缺终态 `Ran N` 行 = UNKNOWN = 总 FAIL**（rule 5 语义原样下沉，不得冒充绿）。
4. 聚合：绿路径过计数门才打总 `Ran T tests ... OK`；红路径 **failfast 语义变为模块粒度**（首个红模块后不再派新模块，在跑的跑完）——只会多跑不会少跑，写明即可。逐模块明细进 sidecar（`runs/<ts>_parallel.jsonl`：模块 / Ran / 时长 / 终态 / 输出路径 + durations 聚合 top25）供审查。
5. 超时：单模块挂死杀本进程树并如实记 TIMEOUT；**总 deadline 860 不动**。
6. 串行尾巴（若 T1 留了）：并行波结束后单 worker 依次跑，计入同一聚合与同一计数门。
7. 账本：PASS 记录加 `mode=parallel` + 计数门结果 + sidecar 指针；指纹绑定、只记 PASS、reviewer 按 rule 4 引用的方式**全部不变**。

### 验收矩阵

| # | 场景 | 必须满足 |
|---|---|---|
| ① | 绿路径 | `Σ Ran_i == 串行发现总数`，成立才出总 OK |
| ② | 植入必红模块 | 总 FAIL，红归属到模块 + 用例名 |
| ③ | 植入挂死模块 | 单模块 TIMEOUT 被杀，总 FAIL，860 内返回 |
| ④ | 同一树态 串行 vs 并行 | 红绿集合逐模块相等，**a_short 与 us_short 各做一次** |
| ⑤ | 并行连烧 3 遍 | 零 flaky，抓隔离性漏网 |
| ⑥ | 植入缺终态 worker（模拟 kill） | UNKNOWN → 总 FAIL，不冒充绿 |
| ⑦ | 计数门植入 | 让 driver 少派一个模块 → 即使全绿也必 FAIL |
| ⑧ | 收据 / 账本 | 并行 run 后收据只有 driver 一份；账本记录含 `mode` 与计数门结果 |

### 边界

不动任何测试断言（C 类密闭化只动 fixture 管道）；不动 860 上限；不动 discovery selector；**focused 路径默认仍串行**（并行只挂 full-lane）；不改「账本只记 PASS」；不改 reviewer 按 rule 4 引用执行方记账、不重跑全量的约定。

### 预期收益与状态

全量 826s（争用）/ ~550s（独占）→ 预期 250~300s。T1 的隔离扫描器同时根治两个 lane 的共享状态假红，是通用件。**当前状态：设计已定，未开工**；前置条件见上文第 4 条。

## 2026-08-06 执行：并行 runner 刀 T1+T2 已实现，a_short 全量 826s→338.7s 并入账（未提交，待审查）

执行方 Claude Code，工作树 `D:\cnhea\Stock-wt\ashort_r1`（分支 `wt/ashort_r1`）。用户批准整刀。方案第 4 条的前置（等序 19 独立审查）已由 `R-ASHORT-SEQ19-RATIO-KNIFE-REVIEW`（Pass-with-Required，代码侧全绿）满足，故开工。

### 结果一句话

`RESULT status=PASS exit=0 tests=2510 elapsed=338.7s deadline=860s mode=parallel`，已入账本。860 上限一个字没动——不是把墙挪开，是让包装得下（占用 96% → 39%）。

### 方案里被实测推翻 / 补正的三条

1. **T1 的清单来源从静态扫描改成运行时观测。** 静态 AST 扫描精度撑不住：`test_a_short_weekly_sidecar_health` 静态报 51 处可疑而运行时零仓库改动。改为跑前跑后快照 `git status` + 六个受保护目录的 mtime/size，逐模块跑 103 个。静态扫描器仍建成（`.tools/test_isolation_scan.py`，fail-closed：解析不出记 `unresolved` 而非「临时安全」），降级为长期守卫。
2. **worker 必须继承 discovery 自己的 import path。** `discover -s tests` 把 top-level 定在 `tests/`，模块名是裸名（`test_a_short_weekly_pipeline`、`schema.test_...`），从仓库根 `-m unittest` 导不到。**加 `tests.` 前缀会导入另一个模块对象**，不是同一次运行。改为让 discovery 报出它实际插入的 `sys.path` 条目原样传给 worker（PYTHONPATH 前置不覆盖）。这是实现时第一个真正会咬人的地方，比方案预判的收据自毁更隐蔽。
3. **串行尾巴不是「若 T1 留了」的可选项，是必需项**——原因见下。

### 本刀最有价值的产出：一条串行世界原理上看不见的缺陷

`tests/provider/us_short_private_test_root.py` 用 `msvcrt.locking` 对固定私有根加**跨进程锁**。只要世界是串行的，这把锁永远没有对手；八个进程一上去，5 个 us_short 模块当场 `OSError: [Errno 36] Resource deadlock avoided`（各卡 9.5s 后放弃）——**读起来像测试红了，其实是并发假红**。

T1 的运行时观测**原理上抓不到它**（它写了又删，串行留不下痕迹），我在 T1 的 register 条目里预先写下了这条盲区，T2 把它变成了实例。

处置按方案 §T2-6，且**判据派生不手写**：模块的 import 闭包能否到达取跨进程锁的源码（`msvcrt.locking` / `fcntl.flock|lockf`）。a_short 尾巴 = **空集**（这就是它能整包并行的原因）；us_short 尾巴 = **59 个**，尾巴串行后锁错误全部消失。植入对照走**中间 helper 间接 import**，不是直接 import。

### 验收矩阵实跑结果

| # | 场景 | 结果 |
|---|---|---|
| ① | 绿路径计数门 | `2510 == 2510`，成立才出总 OK |
| ② | 植入必红模块 | 总 FAIL，归属到模块 + 用例名 |
| ③ | 植入挂死模块 | 单模块被杀、总 TIMEOUT、deadline 内返回 |
| ④ | 串行 vs 并行 | **真 lane 上取不到**，见下节；合成树上逐模块相等 |
| ⑤ | 并行连烧 3 遍 | `2510 / 2510 / 2510` 全 PASS，237.8s / 241.3s / 341.1s，零 flaky |
| ⑥ | 植入 `os._exit(0)`（模拟 kill） | 缺终态 `Ran` 行 = UNKNOWN = 总 FAIL，不冒充绿 |
| ⑦ | 让 driver 少派一个模块 | 全绿仍 FAIL（exit 125） |
| ⑧ | 收据 / 账本 | 103 并发 worker 后收据完好（`tests=180` + bundle 在）；记录含 mode/workers/计数门/sidecar |

### 两条必须写明的削弱

- **验收 ④ 在真 lane 上做不成。** 两个 lane 的串行都跑不完：a_short 串行在 2510 例 TIMEOUT@860（正是本刀要解的事），us_short 串行本轮实测 `TIMEOUT exit=124 elapsed=860.2s`（无红，纯粹装不下）。串行那一侧取不到，替代证据是合成树等价 + 每次运行强制的计数门。
- **按模块分进程比串行更隔离。** 串行全量里「A 模块的模块级副作用让 B 模块通过」这类耦合，并行下不再被覆盖——并行绿在这一个方向上是比串行绿**更弱**的声称。目前无证据表明存在这种耦合，但它不再被测到。

### us_short 侧：并行把墙钟压到 240s，但撞上一条与并发无关的既有红

`test_us_short_test_io_inventory` 的 `module_count` 与 `docs/us_short_test_io_inventory_20260801.json` 基线比对失败（`296 != 286`）。**该模块单独串行跑一次同样红**，证明与并发无关：是 2026-08-01 后全仓新增 10 个测试文件造成的基线漂移。已立 `R-USSHORT-TEST-IO-INVENTORY-BASELINE-REDS-ON-ANY-LANE-ADDING-A-TEST`，**未修**——那是 us_short lane 的基线产物，本工作树是 a_short 执行方，不越界改别窗在动的东西。故 us_short 仍无绿记录，其天花板条目仍 open。

### 改动清单

- 新增 `.tools/parallel_lane_runner.py`、`.tools/test_isolation_scan.py`、`tests/test_parallel_lane_runner.py`（14 条）
- `.tools/bounded_unittest.py`：`run_command`/`run_unittest` 加 `extra_env`；`FULL_PACK_RUNTIME_ARGS` 移来此处单点定义
- `.tools/full_pack_ledger.py`：执行层 `run_unittest` → `_execute_full_pack`（走并行 driver）；`record` 带 `run_detail`
- `tests/test_full_pack_ledger.py` / `tests/test_bounded_unittest.py`：接缝改名与新 kwarg 的对应更新（断言语义不变，其中一条从「拼接后的 argv」升级为「selector 原样下传 + flags 作为 flags 下传」，是更强的断言）
- `tests/test_a_short_experiment_admission_registry.py`：T1 唯一真阳性的密闭化（只动 fixture 管道，断言零改）

### 下一步（给审查方）

审查面 = 上列改动 + `R-ASHORT-PARALLEL-LANE-T1-ISOLATION` / `R-ASHORT-PARALLEL-LANE-T2-DRIVER` 两条 register。序 19 那一批仍在同一工作树未提交，两批一起看。

## 2026-08-07 追加：并发全量偶发假红的根因是一次真树写入，不是 carrier

**症状**：`full_pack_ledger run us_short`（现走并行 driver）偶发红在 `test_us_short_discovery_class_guards.LaneResidueConformance`：`state/us_short` 新增 `lifecycle/lifecycle_register.json`。

**根因**：`tests/test_us_short_weekend_lifecycle_stage.py::DefaultRegisterPath` 为证明默认路径，真往那个规范私有路径 `mkdir`+`write_text`、跑完 `unlink`。串行包里守卫与它同进程且排在前面，生灭都看不见；模块各占一进程的并发包里，那个瞬时文件落进另一个进程「拍完基线、还没断言」的窗口。**偶发**：安静环境下并发全量 `PASS 5559/5559 640.6s`，撞上时才红。完整机制、两处更正与被否掉的两个原方案见 `docs/system_risk_register.md` 的 `R-USSHORT-A-TEST-WRITES-THE-REAL-LIFECYCLE-REGISTER-AND-A-CONCURRENT-GUARD-SEES-IT`（单一来源）。

**修法**：去掉那次写。「默认被消费」改为 patch 掉 `stage.LIFECYCLE_REGISTER_PATH` 后跑一次；「默认是规范私有位置」改为常量恒等式 + `reject_nonprivate_output_path` 断言。两条都比原来强——原来那条 `skipIf(LIFECYCLE_REGISTER_PATH.exists())` 在真有账本的机器上直接跳过。

**防复发**：`LaneResidueConformance` 新增类扫描 `test_no_test_writes_a_canonical_real_path_an_engine_declares`（AST 扫全部 `tests/**/test_us_short*.py`，禁止把写方法作用在从 `engine`/`runners` 导入的路径常量上）。这一类残留守卫抓不住（瞬时）、静态 I/O 清单也只当成 `class4_unresolved_write` 放行（常量解析不下去）。

**没做的事（明说边界）**：并发包里「残留守卫只看得见自己那一小段窗口」的结构性弱点仍在——整包级残留检查只有 harness 做得了，本轮不动 `.tools/parallel_lane_runner.py`。要搬进 harness 是另一刀。`serial_tail_modules` 也未改：把守卫塞进串行尾巴会让它的 import 时基线包含整波残留，等于把假红换成假绿。

**验证**：焦点包 `Ran 87 tests in 23.5s PASS`（lifecycle stage + class guards + IO inventory + lifecycle store + discovery conformance）；4 植入 4 红；`docs/us_short_test_io_inventory_20260801.json` 随之减少一条 `class4_unresolved_write` 键（3 增 5 删的最小 diff，未重排整文件）。
