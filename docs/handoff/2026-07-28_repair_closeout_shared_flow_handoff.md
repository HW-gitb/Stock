# Repair-closeout shared flow / lane-specific verification handoff

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
