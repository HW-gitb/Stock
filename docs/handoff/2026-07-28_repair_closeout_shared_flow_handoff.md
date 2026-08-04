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
