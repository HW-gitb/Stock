# US-short soft-discovery X live response-shape re-review — 2026-07-28

## 2026-07-29 追加：K3-R79 / K3-R83 修复的 Required 清单扩到八条（Claude Code；未实现任何代码）

**先读这一条再动手**：上一轮我给的 FAIL 只有 K3-R86。§6a 独立对抗 agent 随后回来，独立复现了 K3-R86，另外开出七条，我已逐条落 register 并对其中四条做了结构性核实。**这一刀现在要一起修 K3-R86 到 K3-R93 八条**，正文只在 `docs/system_risk_register.md`，此处不复述。

**为什么必须合成一刀**：这八条不是八个孤立 bug，是三个类。
- **「一个坏件弄死整批」类**（K3-R87 / K3-R88）—— 这是本 lane 自己 §五 红线 #4 的原话，也是 K3-R70 / K3-R71 那条反复复发的线。新的 raw 捕获路径把它整个反过来了：一次抓取失败就废掉 N 次已付费调用，而同文件里的 `_normalize_results` 对同一类是「记账后继续」。修的时候按类扫，别只补被点名的那一条腿。
- **「策略选错了那一版」类**（K3-R89 / K3-R92）—— 仓库里同时存在宽松词法策略和 value-shaped 持久化策略，注释白纸黑字写了持久化证据该用后者；新代码两处都挑了错的那版（安全扫描用了宽松词法、drop 新字段绕过了唯一的 sink 侧 sanitizer）。
- **「证据身份 / 可复现性」类**（K3-R86 / K3-R90 / K3-R91 / K3-R93）—— schema 追溯作废历史收据、一条 annotation 放大出无界来源身份、live 重试不再幂等、merge 根本不验新加的 `provider_response_refs`。最后这条尤其要紧：K3-R83 的全部意义就是「让那份 raw 证据真实且可复现」，而现在收据可以声称一份不存在的 raw，消费端照单全收。

**agent 试过但没打穿的（别重复投入）**：48 种 status-id 伪造全被拒（全角/阿拉伯-印度数字、前导零、前后缀、`x.com.evil.io`、punycode 与西里尔同形、userinfo、`/i/web/status/N`、id 只在 query 或 fragment）；60 万条模糊输入下 `_x_status_identity` 零异常；raw 写入路径逃逸在四个目标上全部拦住且未创建任何文件；已冻结产物无法被覆盖；每条中止路径都没留下残片；离线路径除多一个恒空键外逐字节不变。清单在 register 的 §6a 记录条里。

**边界**：本刀仍然**不含任何付费调用**；真实验证是下一刀（只跑 X、一条查询、一次 xAI 调用、非交易决策日）。改动面命中 AGENTS rule 3(c)，全量归属按 rule 4 决定并写进 `full-lane=`；交出前别忘了 `door=`。

## 2026-07-29 追加：交给 Codex 的下一刀命令 —— 修复 K3-R79 + K3-R83（Claude Code 下达；未实现任何代码）

**命令**：`修复 K3-R79 与 K3-R83`，两条同刀做，范围 = `runners/us_short_llm_theme_discovery_fetch_x.py` 的背书比对与 drop 记录、必要时 `runners/us_short_llm_theme_discovery_fetch_web.py` 的共享 raw 落盘腿，加对应测试。**Required 正文、修法约束与 Closure 条件的唯一来源是 `docs/system_risk_register.md` 的 K3-R79 与 K3-R83 两条**，这里不复述——动手前整段读它们，别只照本节的摘要修。

**工作树与基线**：本树已同步到 master tip `5514b02e`，工作区干净。K3-R80 / K3-R81 / K3-R82 已 CLOSED 并合入 master，不要重开。

**为什么合成一刀**：K3-R79 是「怎么修」，K3-R83 是「修完怎么证明」。只修前者，下一次仍然只能靠散文转写的 fixture 验证；只修后者，误杀继续。两条的 Closure 测试互相咬合，分两轮做会重复改同一个 drop 路径。

**必须先读清楚的三条边界**（都出自 register，摘要仅为防止走错方向，冲突时以 register 为准）：
1. **不许动 `_canonical_locator`**。它的 sha256 就是 `_source_id`，改了会波及已冻结证据；把 `/<handle>/status/<id>` 折成 `/i/status/<id>` 虽然身份等价但丢 handle，违反 K3-R35/R36 定下的「只做无损变换」。身份比较只加在**背书比对那一处**。
2. **K3-R83 有两条腿，别只修被点名那条**：(i) 因身份/背书不匹配而丢弃时，drop 条目要同时记下**两边**；(ii) live 调用即使 0 条被接受也要落 raw。今天 raw 是按「被接受的来源」写盘的，所以全被丢掉的那次运行反而什么都没留——那恰恰是最需要 raw 的一次。整类扫：web lane 是否有同样的「0 接受 → 0 raw」形状，一并处理或明确写为不适用。
3. **本刀不含任何付费调用**。不要为了验证去跑 provider；验证用 register K3-R79 里记下的六个 status id 与两种 URL 形式重建 fixture。真实付费验证是**下一刀**，且已定为「只跑 X、一条查询、一次 xAI 调用、非交易日」，Web 不跑。

**交出前必须满足**：`Pre-Codex self-review` 现在是**六**个字段——新增 `door=`，要求交出前跑一次 `.githooks/pre-commit` 的那两个守卫（`tests.test_route_doc_ledger_status_consistency` + `tests.test_doc_governance_guard`）并贴终端结果；写 `TBD` / 留空判红，跑不了写 `door=BLOCKED: <原因>`。规则正文见 `docs/pre_codex_self_review_checklist.md` §0.10/§0.11。另按 AGENTS rule 1，改到 `AGENTS.md` 或治理文档时**必须**把 `tests.test_doc_governance_guard` 放进 focused pack——这正是 K3-R81 的根因。

**验证分级预判**：改动面是 X lane 的 provider 消费与 raw 落盘 → 命中 AGENTS rule 3(c)（provider / raw-payload / live-data），全量由谁跑按 rule 4 决定并在 `full-lane=` 写明。

## 2026-07-29 追加：K3-R81 / K3-R82 独立审查 — PASS（Claude Code，48b5 工作树，已提交并合入 master）

**为什么 PASS**：三条腿都补齐且都被外部挖空证明是承重的。Required 正文与关闭证据只在 `docs/system_risk_register.md`（K3-R81 / K3-R82 CLOSED），此处不复述。

**验证命令 / 结果**：
- 未起全量（用户指令 + rule 4 docs-only 例外）：本轮相对已审 K3-R80 状态的 delta 只有 `AGENTS.md` 1+/1- 与文档，reviewer 自有的 `Ran 5001 tests` / `OK` 仍然有效。
- 验收超集：`.tools\run_unittest_with_repo_pythonpath.cmd tests.test_doc_governance_guard tests.test_review_tiering_enforcement tests.test_route_doc_ledger_status_consistency` → `RESULT tier=focused status=PASS exit=0 tests=72 elapsed=2.8s`。
- 外部挖空 12/12（真文件 + 真守卫 + 按字节还原 + 核 sha256）：删掉单反斜杠 `` `.tools\codex_main_python.ps1` remains the strict host-Python entrypoint `` → 路由断言转红（证明 415/689 行的 `\\` 转义写法不顶用）；删掉 K3-R80 条目里补回的 `Pre-Codex self-review` 行 → closeout 守卫转红；两处还原后复跑皆绿。

**失效的旧结论**：K3-R80-O2 已并入 K3-R81 并随之关闭，不要再当 Optional 追。

**下一步注意事项**：rule 4 里恢复的「不要 `Start-Process` 包裹 / 不要拼成单个 `ArgumentList`」那句**没有任何机器守卫**——我的对照证明删掉它全绿，它上次就是这么无声消失的。下一次碰 `tests/test_doc_governance_guard.py` 时顺手加一行 `assertIn` 把它钉住，不要为它单开一轮。

## 2026-07-29 追加：K3-R81 / K3-R82 executor repair（待 Claude Code 独立审查）

**判断与修复**：两条 Required 成立，且都来自上一刀 O1 的文档改动，不是 K3-R80 残留修复本身。rule 4 保持「带字面 `--` 的 ledger 必须直调固定主 Python」，同时恢复 `.tools\codex_main_python.ps1` 作为不含该 separator 的严格主 Python 入口；明确 rule 5 仍是 focused 测试入口，并恢复「不得 `Start-Process` 包裹或把 argv 拼成一个 `ArgumentList` 字符串」的禁令。上一条 Codex K3-R80/O1 entry 补入带 `matrix=`、`register=`、`handoff=`、`focused=`、`full-lane=` 的 labeled self-review 行。

**证据 / 边界**：固定主 Python 治理超集：`tests.test_doc_governance_guard` + `tests.test_review_tiering_enforcement` = `Ran 58 tests` / `OK`；`git diff --check` 通过。K3-R80 的 reviewer-owned full lane 已为 `5001 OK`，本轮仅治理文档，按 rule 4 不使该全量结果失效、也不重复跑。无 provider/key/network/live 动作，未 push / remote。

**交给 Claude Code**：独立审查 K3-R81 / K3-R82；不要把 `.tools\codex_main_python.ps1` 重新用于含 `--` 的 full ledger argv。

## 2026-07-29 追加：K3-R80 / K3-R80-O1 独立审查 — FAIL（Claude Code，48b5 工作树，未提交）

**改了什么**：六个 `tempfile.mkdtemp(dir=<protected root>)` 点（status source / bankruptcy / retry pacing / replay ×3）改成受管 `TemporaryDirectory`；replay 的 capture summary 移到独立的非-source-raw 临时根；`tests/test_us_short_soft_boost_consumption.py` 每次 `setUp()` 建独立 `TemporaryDirectory` 并 `addCleanup`，根治重复 `setUp()` 只清最后一套的老 `tearDown`；删 61 个 gitignored 旧夹具目录；`AGENTS.md` rule 4 改为固定主 Python 直调账本。

**为什么 FAIL**：K3-R80 的实质修复是对的——守卫一行没动（`tests/test_us_short_discovery_class_guards.py` 与上轮我已审的 diff 逐字节相同），改的是丢垃圾的测试本身，正是 Required 要求的方向，且已被官方全量账本与我自写的独立扫描器双向证实。挡住这一刀的是同刀的 O1 改动：rule 4 重写删掉了 `AGENTS.md` 里唯一能满足文档守卫断言的单反斜杠 `.tools\codex_main_python.ps1`，把 `tests/test_doc_governance_guard.py` 由绿打红；同一次重写还删了 `Start-Process` / `ArgumentList` 那句，并让 rule 4 与 rule 5 / line 689 互相矛盾。另一条是执行方本轮 `修复` 条目缺 `Pre-Codex self-review` 行。Required 正文只在 `docs/system_risk_register.md`（K3-R81 / K3-R82；K3-R80 实质证据同处），此处不复述。

**验证命令 / 结果**：
- 全量（rule 4 官方账本，reviewer 取得 ownership 亲跑；rule 3d：包范围守卫无法被 focused 包界定）：`python .tools\full_pack_ledger.py run us_short "<trigger>" "<evidence>" 1300 -- discover -s tests -p 'test_us_short*.py'` → `Ran 5001 tests in 653.584s` / `OK`；`RESULT status=PASS exit=0 tests=5001 elapsed=654.5s deadline=1300s`，已记账。与上轮 FAIL 同为 5001，说明没增删或跳过用例。
- reviewer 自写独立扫描器 9/9（刻意不复用 `_growth` 与它的 import 基线）：植入嵌套文件可检出且已清除；六个修复模块 `44 OK` 后 `provider_samples` 与 `state/us_short` 零增长零丢失；`tests/test_us_short_soft_boost_consumption` 单跑 `10 OK` 且零残留。
- 整类扫描：lane 内存活的 `mkdtemp(` 全部无 `dir=<protected root>`；`k4b_*` 残留 0、`_unit_tests/run_*` 残留 0、`state/us_short` 文件 0；删目录未触及任何 tracked 文件。

- 文档守卫：`.tools\run_unittest_with_repo_pythonpath.cmd tests.test_doc_governance_guard` → `RESULT tier=focused status=FAIL exit=1 tests=39 elapsed=0.9s`，两条红即 K3-R81 / K3-R82。该模块不匹配 `test_us_short*.py`，全量绿与它无关。回归归属已证：把守卫那条归一化断言分别跑在 `git show HEAD:AGENTS.md` 与当前树上 → True / False。

**失效的旧结论**：executor 记的「post-repair full lane = NOT_VERIFIED」已由本轮官方账本 PASS 取代，不要再当未验证引用；K3-R80 的残留实质不必重验。上一轮记的 K3-R80-O2 已升级并并入 K3-R81，不要再当 Optional 处理。

**下一步注意事项**：改 `AGENTS.md` 必须把 `tests/test_doc_governance_guard` 放进 focused pack——本轮 44 个用例里一个文档守卫都没有，这是两条红的共同根因。另 `tests/test_us_short_soft_boost_consumption` 排在残留守卫之后，全量包结构上看不见它的残留——以后再动这个模块，必须像本轮一样单独跑 + 自己扫，别拿全量绿当它的证据。

## 2026-07-29 追加：K3-R80 / K3-R80-O1 executor repair（待 Claude Code 独立审查）

**方案判断**：保留 `LaneResidueConformance` 的 `provider_samples` 增长腿是正确解；不能按发现顺序或缩小根目录绕开。审查列出的六个 `mkdtemp` 点中四个已有局部清理，但统一迁到 `TemporaryDirectory` 才能防止未来早退或新分支漏清。soft-boost 的根因更深：一个测试内重复调用 `setUp()` 会覆盖旧 `self.paths`，原 `tearDown()` 只能删最后一套夹具；现在每一套都注册独立 cleanup。

**修复**：status-source、bankruptcy、retry pacing、replay 的六个 raw 夹具点均改为受管临时目录；replay capture summary 明确放在独立的非-source-raw 临时根。soft-boost 改为每次 `setUp()` 建立并 `addCleanup` 一个 `TemporaryDirectory`。经路径和 gitignore 核验后，删除 61 个旧 `k4b_*` / status `run_*` 测试夹具；不触碰其他 provider 样本。`AGENTS.md` rule 4 改为直接固定主 Python 调账本，修复 PowerShell launcher 吞 `--` 的 Optional。

**证据 / 边界**：固定主 Python、离线 focused 超集（status source、bankruptcy、retry pacing、replay、soft-boost、residue guard）=`Ran 44 tests` / `OK`；`py_compile` 与 `git diff --check` 通过；六点 `mkdtemp` 静态扫描为零，命名测试残留目录为零，`state/us_short` 文件为零。第一次此超集曾在 replay 红两条：capture summary 被放入 source raw 后被 replay 正确当作非 wrapper 拒绝；已移到独立根并同命令转绿。此前官方全量 `5001` 的单一 guard FAIL 仍为真实历史证据；本轮探针已红，按规则没有启动第二次全量，因此 post-repair full lane = **NOT_VERIFIED**。无 provider/key/network/live 动作，未 push / remote。

**交给 Claude Code**：独立审查 K3-R80 / O1；按 AGENTS tiering 处理是否拥有 final-diff 的唯一 rule-4 全量，不得把当前 `NOT_VERIFIED` 写成 PASS。

## 2026-07-29 追加：K3-R77 两条 residual Optional 修复的独立审查 — FAIL（Claude Code，48b5 工作树）

**改了什么 / 审了什么**：`runners/us_short_llm_theme_discovery_fetch_web.py::_live_receipt_retry_evidence` 加 `execution_mode == "live_authorized"` 门；`tests/test_us_short_discovery_class_guards.py::LaneResidueConformance` 把增长谓词从 `state/us_short` 一处扩到 `state/us_short` + `provider_samples` 两处，并加一条 root 成员固定测试。

**为什么 FAIL**：第二条把 us_short 全量包打红。守卫本身是对的——它抓到的是真残留：`tests/provider/test_us_short_batch5_status_source_probe.py:61` 用 `tempfile.mkdtemp(prefix="run_", dir=…provider_samples/us_short_batch5_status_source_20260630/raw/_unit_tests)` 且从不清理，而 `unittest discover` 按 `sorted(os.listdir("tests"))` 走，`tests/provider`（下标 8）整包在 `tests/test_us_short_discovery_class_guards.py`（下标 137）之前跑完，基线又是 import 时捕获的，所以这些残留正好落在测量窗口里。Required 正文与整类清单只在 `docs/system_risk_register.md`（K3-R80），此处不复述。

**验证命令 / 结果**：
- 全量（rule 4 官方账本，reviewer 亲跑）：`python .tools\full_pack_ledger.py run us_short "<rule 3d trigger>" "<focused evidence>" 1300 -- discover -s tests -p 'test_us_short*.py'` → `Ran 5001 tests in 654.408s` / `FAILED (failures=1)`；`RESULT status=FAIL exit=1 tests=5001 elapsed=655.3s deadline=1300s`。唯一失败即该守卫。
- focused 超集：`.tools\run_unittest_with_repo_pythonpath.cmd tests.provider.test_us_short_llm_theme_discovery_fetch_web tests.test_us_short_discovery_class_guards tests.test_us_short_discovery_conformance` → `RESULT tier=focused status=PASS exit=0 tests=94 elapsed=20.2s`。
- reviewer 自写外部挖空探针 21/21：把 `_live_receipt_retry_evidence` 换成修复前函数体 → 新离线不可变性测试转红，还原转绿；植入 `provider_samples/**` 与 `state/us_short/**` 残留各自令守卫转红，两处清理后复扫为空。

**失效的旧结论**：上一轮 K3-R77 PASS 记录的「两条 residual Optional 不阻断」仍然成立，但「扩到 `provider_samples` 是纯增强」不成立——它继承了 lane 既有的残留债，必须连带修测试才能落地。

**下一步注意事项**：修复方不得为了让包变绿而削弱/收窄/删除该守卫；`tests/provider` 在守卫之前跑这一点是排序事实，不要靠调整顺序绕过。另注意 `codex_main_python.ps1` 会吞掉 `--`（K3-R80-O1），跑账本请直接调 pinned 解释器。

## K3-R76/K3-R77 executor repair — 2026-07-29

## K3-R77 downstream payload repair - 2026-07-29 (pending Claude review)

## K3-R77 residual Optional repair - 2026-07-29 (pending Claude review)

The two residual Optionals are worth repairing, but their narrow repair is preferable to a broad test-harness rewrite. Retry projection now applies only to an exact `live_authorized` receipt: that is the sole mode with transient provider-attempt telemetry worth ignoring on an idempotent retry. Offline receipts retain the entire immutable comparison, and the real pair-write control proves a changed offline drop ledger is rejected; deleting the `execution_mode` gate makes it red. This does not alter the immutable publisher or relax raw/hash binding.

The private-residue predicate now covers both `state/us_short` and `provider_samples` from import-time baselines. Thus a prior authorized live ledger/raw capture is allowed, while a file left by a sequential test or probe is rejected. A nested temporary-root raw receipt proves the growth predicate, and a separate control pins `provider_samples` into the protected-root set so the coverage cannot disappear by omission. A pack-wide root redirection would be stronger only by changing the whole test harness and the many tests that deliberately exercise isolated raw files; it is not justified for these non-blocking residuals.

Required main-Python offline evidence: `tests.test_us_short_discovery_class_guards tests.provider.test_us_short_llm_theme_discovery_fetch_web tests.provider.test_us_short_llm_theme_discovery_fetch_x_merge` = **116 OK**; `tests.test_us_short_discovery_conformance` = **27 OK**. Before running, `state/us_short` and gitignored `provider_samples/` were inspected. No provider command/request, credential read/output, network/live action, scoring change, full-pack retry, push, or remote action occurred. Full lane remains **NOT_VERIFIED**; hand to Claude Code for independent review.

The previous K3-R77 repair is superseded where it implied that deleting module attributes or retaining a one-shot ticket made `live_authorized` unforgeable. It does not: arbitrary Python in this process can inspect `run_web_fetch.__closure__`, instantiate its captured `new_transport`, and add an arbitrary object to the mutable `issued_tickets` set captured by `_consume_ticket`. That ticket mechanism is retained only as normal-path/replay bookkeeping; it is not provider provenance.

The repaired, load-bearing claim is narrower and is tested at the boundary that can affect money. `tests/provider/test_us_short_llm_theme_discovery_fetch_x_merge.py` now uses that exact closure forge with no network activity. A forged live label with no source refs passes merge but is refused by knife-2's non-empty discovery schema, creating no member or boost. A forged live label with one source whose persisted raw bytes are then modified is refused by merge before knife-2 because merge re-reads the raw file and re-derives `content_sha256`. The latter control turns red if `_guard_raw_content_digest` is weakened. This is not a claim that malicious same-process code cannot fabricate both a label and provider-shaped bytes; such external provider provenance remains NOT_VERIFIED.

Required main-Python offline evidence: `tests.test_us_short_discovery_class_guards tests.provider.test_us_short_llm_theme_discovery_fetch_x_merge` = **53 OK**; `tests.test_us_short_discovery_conformance` = **27 OK**; `git diff --check` clean. Before correcting the new test's expected knife-2 refusal, gitignored `provider_samples/` and `state/us_short` were inspected; the only red was that intentional schema rejection, not a production failure. No provider command/request, credential read/output, raw live capture, score-flag change, second decision date, or full-pack retry occurred. Full lane remains **NOT_VERIFIED**; hand to Claude Code for independent review.

The earlier class-guard round was itself rejected: an empty-directory residue assertion would reject a legitimate future budget ledger, and module-public `_new_live_transport` exposed the concrete ticket registry. The repaired residue predicate snapshots `state/us_short` at import and rejects only new files; its planted case is entirely temporary-root-local. Web/X bind concrete factories only while constructing their runner closure and delete their module attributes afterward. Every runner-issued ticket is object-held, consumed once by the verified transport, and revoked in `finally` on both success and error paths.

Evidence under the required main Python: K3-R76/R77 focused controls plus mock-live positive paths 7 OK; Web 61 OK; X 47 OK; discovery conformance 27 OK; final `state/us_short` file scan was empty. Independent read-only self-review PASS. No provider command/request, secret output, raw live capture, scoring change, second decision date, or full-pack retry occurred. The prior sole full invocation remains without terminal evidence or cached green: live execution is still NOT_VERIFIED and must not begin.

## K3-R34 step-5 executor update — 2026-07-29

The user authorized the bounded paid-provider scope. Before any request, the executor repaired the registered offline checklist: retry comparisons exclude only per-attempt transport/drop bookkeeping; response-derived live attestation and raw/hash binding remain mandatory; malformed xAI `.results` / `.citations` are annotation-only; and a per-ledger Windows named mutex protects the budget read-modify-write with a true two-contender test. The only live code change is removal of the K3-R34 early raises; credential single-key checks, pre-reservation, PIT floor, raw freeze, and write-door rules remain fail-closed.

Independent self-review found and then re-reviewed two additional defects before any provider action: a direct builder caller could reach ticket factories through public runner defaults, and `WAIT_ABANDONED` ownership was not released. Ticket factories now live only in the runner closure; a verified transport consumes one ticket before packet construction. The Windows named mutex releases abandoned ownership before failing closed. Web/X forged-transport/arbitrary-ticket/replay controls and mocked-live runner success pass; mutex controls cover two contenders, reservation entry, and abandoned cleanup. Final main-Python focused evidence is Web **61 OK**, X **47 OK**, discovery conformance **27 OK**; the independent read-only self-review is PASS. The sole actual required full-lane invocation likewise recorded A-F preparation but no terminal result; exact-state `full_pack_ledger.py check us_short` has no cached green. No Web/X provider command, paid request, provider key output, raw live capture, `theme_soft_boost_enabled`, 4d action, or second decision date occurred. Do not retry the full lane or begin live execution in this executor turn; hand to Claude Code for independent review/next authorized action.

## Scope and outcome

The initial captured-shape re-review did not close unfreeze step ②: independent review found K3-R68 (missing decision-week floor) and K3-R69 (missing served-model receipt binding). This handoff now records their executor repair, still without a new provider request, credential read, network call, or live run.

The captured shape is: response text in `output_text`; `results` and `citations` absent (`None`); URL attestation only in `output[].content[].annotations[*]` entries of type `url_citation`. The model-produced JSON `sources` are therefore accepted only as `model_transcribed` when their canonical URL is present in that annotation set.

## Code and regression evidence

`GrokXSearchClient` keeps the transcript through `_response_text`, finds no provider text rows through `_provider_result_rows`, and extracts URL attestations through `_provider_annotation_urls`. `build_x_fetch_packet` accepts an annotation-backed model source and rejects the same source when the annotation is absent with `model_source_url_not_provider_annotated`.

The shape is pinned by `tests/provider/test_us_short_llm_theme_discovery_fetch_x_merge.py::XFetchAndMergeTests.test_captured_grok_response_shape_routes_only_annotation_backed_transcript`. The fixture records only the observed structural fields and safe local values; it does not copy provider raw content.

Fixed main Python command and actual result:

```text
.tools\run_unittest_with_repo_pythonpath.cmd tests.provider.test_us_short_llm_theme_discovery_fetch_x_merge
Ran 39 tests in 9.160s
OK
```

## Boundary and remaining gates

`run_x_fetch(live=True)` still fails before any key, client, budget, or network action. This handoff does not authorize a provider call, lift K3-R34, repair K3-R31/K3-R32, enable scoring or `theme_soft_boost_enabled`, or begin 4d.

The next technical work remains K3-R31 and K3-R32. Only after those repairs and their review may the K3-R34 freeze be reconsidered under a separate user command.

## Pre-Codex self-review

`matrix=complete; register=updated; handoff=updated; focused=61 OK; full-lane=not_triggered: AGENTS rule 3; reason=X intake/receipt schema and direct consumers only`.

## K3-R68/K3-R69 repair update

X normalization now reuses `web._decision_week_start` and emits `published_at_outside_decision_week` per stale source. The captured model-transcribed source dated 2026-03-02 is rejected; prior-Friday and Sunday controls remain accepted.

The X receipt schema now requires `fetch_contract.grok_model` with the requested alias, the provider-reported served model, and unique system fingerprints. `GrokXSearchClient` extracts the identity from the response; orchestration carries it to the builder, which rejects a successful live-shaped attempt that lacks a served model. The identity is receipt metadata rather than part of `discovery_artifact_sha256`, which deliberately binds normalized discovery evidence only.

The captured annotation-backed response now runs through orchestration and the builder in one regression test. Fixed main Python direct pack:

```text
tests.provider.test_us_short_llm_theme_discovery_fetch_x_merge
tests.schema.test_us_short_llm_theme_discovery_fetch_x_schema
tests.provider.test_us_short_llm_theme_discovery_offline_invariants
tests.provider.test_us_short_offline_production_entry_guard
Ran 61 tests
OK
```

This is pending independent review. K3-R34 remains frozen, and K3-R31/K3-R32 remain outside this repair.

## 2026-07-28 追加：独立审查两轮（FAIL → PASS），步骤 ② 至此才真正闭合

第一轮判 **FAIL**。钉住捕获形状是对的，但步骤 ② 的命题是「拿真实形状复审 live 半边」——web 侧同一步正是这样挖出 K3-R49～R58。横扫兄弟 lane 后开出两条 Required：**K3-R68**（X 侧无当周下限，五个月前的旧帖仍能撑出 `both`/5.0；这同时是 K3-R66 leg 1 写明却未满足的闭合条件）、**K3-R69**（X 收据不绑 served model，K3-R53 已在 web 关闭的同类）。

第二轮判 **FAIL（K3-R68 闭合，K3-R69 未闭）**。K3-R68 复用 `web._decision_week_start`、落在唯一入口 `_normalize_results`：旧帖掉 `published_at_outside_decision_week`，而上周五 / 上周日 / 决策当日仍各接受 1 条——未重演 K3-R56 的过度收紧。K3-R69 的产物形状也对：无 served 的 live 尝试被拒、全查询失败仍诚实建包、服务端换成 `grok-4.5` 时照建并把差异记进 `fetch_contract.grok_model`。两道守卫各有一个具名测试在我外部挖空后转红。

但 K3-R69 的编排腿把两条未声明的批级 `raise` 放进了 per-query 循环，lane 自己的 §五 red-line #4 守卫（`test_no_undeclared_batch_level_raise_inside_an_item_loop`）因此转红 → **K3-R70**。行为今天没坏（同循环 `except` 把它收成 per-query drop），坏的是声明契约本身。**这一条只有全量包能发现**：4,980 tests 里唯一的红就是它，而直接消费改动符号的 130 个测试全绿——所以本刀交接时那句 `full-lane=NOT_VERIFIED` 正是漏掉它的原因。同轮更正一条历史假设：桌面清单说 `test_strict_pass2_approval_callsite_has_independent_load_bearing_control` 仍红，本次全量里它是绿的。

完整 Required / 复现 / 闭合判据的单一来源仍是 `docs/system_risk_register.md#R-USSHORT-KNIFE3-WEB-X-MERGE-PACKET-BOUNDARY`，本节不复述。**下一步不变**：K3-R31 / K3-R32（解冻链步骤 ④），之后才谈 K3-R34。

The earlier rule-3 invocation had no usable result at the time it was recorded. That statement is superseded by the K3-R70 repair update below; it remains here only as a historical account of why K3-R70 was found by independent review.

## K3-R70 repair update — 2026-07-28

The repair keeps model identity validation per query: a missing provider-served model produces `served_model_missing`, and a later different served model produces `served_model_changed`, both via `web._ProviderItemRejected`. They are recorded as exact `llm` drop-ledger rows; they are not added to the batch-level raise allowlist. Generic client failures still use `provider_response_dropped`.

The regression uses good replies before and after the two rejected replies. It proves the two siblings survive, checks both exact drop rows, and confirms that the retained identity is `grok-4.5` with the two accepted fingerprints. It was run with the fixed main Python together with the named lane per-item conformance probe: **44 OK**. `py_compile` and `git diff --check` passed.

The one required rule-3 command completed on this exact code state. The actual ledger result is **CACHED GREEN — 4981 OK at 2026-07-28T22:41:07**. This fixes K3-R70 pending independent review; it does not lift K3-R34, authorize any provider/key/network/live action, or begin K3-R31/K3-R32.

## 2026-07-28 追加：第三轮独立审查 **PASS** —— 解冻链 ② 至此闭合

K3-R70 按指定方向修好：两处改用 `web._ProviderItemRejected` + 具名 reason，专捕分支放在通用 `except` 之前，`DECLARED_BATCH_RAISES` 未被放宽（该测试文件零改动）。我自己的探针证明兄弟查询真的活着——四查询 good→missing→changed→good，两条好查询的 provider row 与 annotation 全保留，只掉 `served_model_missing:q2` 与 `served_model_changed:q3` 两行，收据留下的身份是 `grok-4.5` 加 `fp1,fp2`，被拒回复的指纹没有混进证据。挖空任一处 raise，具名测试 `test_live_x_model_identity_rejections_drop_only_the_affected_query` 转红（baseline 43 tests / 0 红）；曾经转红的 `LanePerItemConformance` 现在 2 OK；全量按 tiering rule 4 引用账本自身输出 `CACHED GREEN 4981 OK`，不重跑。

**至此 K3-R68 / K3-R69 / K3-R70 全部 CLOSED，X 侧「拿真实形状复审 live 半边」（解冻链 ②）闭合。** 下一步是 K3-R31 / K3-R32（步骤 ④），之后才谈 K3-R34 解冻。一条不阻断的 Optional：本次 K3-R70 修复轮没有对应的 `修复` SESSION_LOG 条目，跨轮记录靠 register 与本 handoff 兜住。

## Pre-Codex self-review

`matrix=complete; register=updated; handoff=updated; focused=44 OK (X orchestration + per-item conformance); full-lane=4981 OK (official ledger); no batch-level allowlist extension; no provider/key/network/live action.`

## 2026-07-28 conformance test-tier split

The K4b executable coverage and mutation-heavy closure matrix now execute from `tests/test_us_short_discovery_conformance_executable.py`. The original `tests/test_us_short_discovery_conformance.py` retains their plain helper bases for the static guard registry, so importing the static module does not collect either slow TestCase. This preserves every inherited test method and assertion without circular imports or double collection.

Collection evidence is `static=27` plus `executable=11`, the original 38 conformance tests. The bounded static package plus the moved K4b class ran `31 OK` in `17.036s`, below the 300-second focused limit. The required final US-short discovery run executed, rather than reusing the old cache: `Ran 4981 tests in 706.708s`, `OK`; the ledger recorded its new code fingerprint at `2026-07-28T23:27:39`.

This is test-structure only: no production code, assertion body, R70 guard, timeout policy, provider/key/network/live path, score effect, or K3-R34 freeze changed. The remaining technical work is still K3-R31/K3-R32 before any separate reconsideration of K3-R34.

## K3-R31/K3-R32 executor repair — 2026-07-28

The K3-R34 early live freeze remains first and unchanged; no provider client, credential, network request, or live run occurred. The future web path now reserves both Tavily and the reviewed maximum DeepSeek regroup capacity before its first paid Tavily request. Its dated budget ledger has per-query-scope reservations, so retrying the exact scope does not add planned calls.

For R32, only receipt-level `generated_at` is a retry clock. Web and X raw source payloads retain `fetched_at`, bind it in `content_sha256`, and a same-evidence retry reuses the source's first frozen fetch instant. A tampered receipt-source `fetched_at` is refused; a genuine retry with a new packet clock remains idempotent. Tests use private gitignored raw roots: an inspected historical default-root fixture (`2026-07-28T13:39:11Z`) lacked `fetched_at`, which correctly conflicts under the repaired contract rather than being silently treated as equivalent.

Fixed main Python focused pack:

```text
tests.provider.test_us_short_llm_theme_discovery_fetch_web
tests.provider.test_us_short_llm_theme_discovery_fetch_x_merge
tests.provider.test_us_short_llm_theme_discovery
tests.provider.test_us_short_llm_theme_discovery_offline_invariants
Ran 128 tests in 15.592s
OK
```

`py_compile` and `git diff --check` passed. One official full-pack-ledger invocation was made, but it returned no terminal test result; follow-up `full_pack_ledger.py check us_short` reported no cached green on this exact code state. Therefore `full-lane=NOT_VERIFIED`; do not rerun it in this executor turn and do not close K3-R31/K3-R32 or lift K3-R34. Independent review is next.

## K3-R71/K3-R72 recurrence repair — 2026-07-29

K3-R71 is repaired without widening `DECLARED_BATCH_RAISES`: reservation-ledger entries are projected in a comprehension, then malformed shape, duplicate scope and aggregate-count failures are rejected once outside the iteration. This keeps untrusted-item loop behavior separate from the system-boundary ledger failure contract and makes `LanePerItemConformance` green again.

K3-R72 is now a static AST ordering guard because K3-R34 correctly prevents execution of the future paid path. The guard requires `_reserve_live_web_provider_budgets` before `execute_live_web_orchestration`; its own test removes the reserve call and reinserts it after orchestration, then asserts an offender. The project rule added to `AGENTS.md` is deliberately predicate-based: a static conformance guard is a direct focused consumer when its AST/registry predicate intersects the changed symbol. It does not impose a filename-based test tax.

The same-class Optional dispositions are: raw frozen `fetched_at` after the current retry clock is now a per-source rejection; `publish_immutable_pair` requires an explicit keyword-only recursion policy; the active clock-stripping docstring now matches the code; and the non-persisted retry tests were renamed to the narrower property they actually prove while the persisted retry test proves a new packet clock preserves the first frozen source clock.

Focused main-Python evidence before the final test-only R72 helper strengthening: `fetch_web`, `fetch_x_merge`, policy/discovery and `LanePerItemConformance` = **120 OK / 12.167s**. The re-run then stopped before the target test body at an external `temporary_provider_directory` lock (`OSError 36`; lock mtime `2026-07-28T13:04:12Z`), so final focused status is **UNKNOWN**, not a code verdict. `py_compile` and `git diff --check` passed. The one scheduled read-only independent self-review returned PASS with no must-fix and ran no tests. A single official full-pack invocation returned no terminal test result and its ledger has no cached green for this code state; `full-lane=NOT_VERIFIED`, with no rerun. K3-R34 remains frozen and no provider/key/network/live action occurred. Next: independent review after the private-root lock is released.

## 2026-07-29 追加：K3-R31/K3-R32 独立审查 **FAIL** —— 解冻链 ④ 未闭合

判 **FAIL**，红点不在设计方向而在实现落点。这一刀的方向是对的：预算在第一笔付费 Tavily 之前一次性预留、同 query scope 的重试只加尝试次数不加计划调用（K3-R31 的闭合语句），`fetched_at` 回到冻结证据里并进 `content_sha256`、只留顶层 `generated_at` 当重试时钟（K3-R32 的闭合语句）。我另外核过三处不容易看出来的正确性：`_chunk_regroup_rows` 在 `len(chunks) > MAX_DEEPSEEK_REGROUP_CALLS` 时直接抛，所以按常量预留永远不会少留；`generated_at` 只出现在制品与 X 收据的**顶层**，去掉 `recursive` 不会误伤嵌套重试时钟；四个生产建包口全部 `persist_raw=True`，冻结路径覆盖了每个真实调用者。

**红的那条只有全量包能发现，焦点包 128 OK 对它是瞎的**——和 K3-R70 完全一样的盲区。`_reserve_provider_budget` 为了校验新的 `query_reservations` 开了一个 `for entry in reservations:` 循环，循环体里两条 `WebThemeDiscoveryError` 是未声明的批级 raise，令 lane 自己的 §五 red-line #4 守卫转红（`batch_raise_offenders`，`tests/test_us_short_discovery_conformance.py:587`）。官方账本在本代码态实跑：`Ran 4983 tests in 622.385s` / `FAILED (failures=1)`，4983 = 原 4981 加本刀两条新回归，所以除这一条外没有别的回归。第二条 Required 是我用植入对照挖出来的：K3-R31 的全部意义就是「先预留再花钱」，而这条路径被 K3-R34 冻着不可执行，静态断言是唯一可能的证明——现在那条断言只钉了「凭据在预留之前」，把预留整行移到 `execute_live_web_orchestration(` 之后它照样绿。

**全量账本边界**（本轮专门核过，因为上一轮交接停在「只有 prepare 没有结果」）：账本只记 PASS，`prepare` 每个 lane 只有一格且被下一次 `run` 覆盖。所以「有 prepare 没结果」不是含糊信号，它证明包跑过且没绿，但它既不区分 FAIL 与 TIMEOUT，也不保存失败内容；而下一次 `run` 会抹掉上一次的 prepare。另外 `run` 参数形状不对时只打印用法、返回 2、**不写 prepare**，等于完全不留痕。

完整 Required / 复现 / 闭合判据的单一来源仍是 `docs/system_risk_register.md#R-USSHORT-KNIFE3-WEB-X-MERGE-PACKET-BOUNDARY`（K3-R71 / K3-R72 及四条 Optional），本节不复述。**下一步**：修 K3-R71 / K3-R72 后再复审，K3-R34 在那之后才谈解冻。

## 2026-07-29 追加：K3-R71/K3-R72 复审 **PASS** —— 解冻链 ④ 至此闭合

判 **PASS**。K3-R71 走的是我给的首选修法：整个 `for entry in reservations:` 消失，改成 comprehension 投影 + 一条聚合条件在迭代外只抛一次；`_reserve_provider_budget` 现在 AST 上有 **0 个 For/While 节点**，守卫的谓词根本匹配不到它，`DECLARED_BATCH_RAISES` 一字未动——没有靠削守卫过关。等价性我自己探针逐条打过：账本缺 `query_reservations` / 非 list → `cannot prove retry scope`；非 dict 条目、非 str `query_sha256`、字符串或负 `call_count`、重复 scope、`sum != planned` → `live budget ledger is malformed`；同 scope 不同 `call_count` → `retry scope conflicts`；新 scope 超帽 → `budget exhausted: 25+1 > 25`。**重写成单条布尔表达式后最容易漏的两种形状**——不可哈希的 `query_sha256`（进 set comprehension）和非 int 的 `call_count`（进 `sum()`）——都收成 `WebThemeDiscoveryError` 而不是裸 TypeError，说明 `or` 的短路顺序摆对了。正面对照：同 scope 重试 ACCEPTED、`reservation_attempt_count=2`、`planned_provider_call_count` 仍是 2，正是 K3-R31 的闭合语句。

K3-R72 换成 AST 版 `_live_preflight_order_offenders`，并且在同一条测试里就地把 reserve 移到 orchestration 之后证明它会红。我按「守卫必须由外部挖空证明会死」另跑一遍：baseline `[]`、移到花钱之后 `['reserve must precede the first paid orchestration call']`、删掉 `['missing reserve-before-spend call']`。**同时核了它的 inline 对照不是假阳性**——锚点行 `fetched_now = outcome["fetched_at"]` 在 `run_web_fetch` 里真实存在，所以那个变异确实是「重排」而不是退化成「删除」。

四条 Optional：α 闭且没有过度收紧——把冻结 raw 篡改成 2099 后 `accepted_source_count=0`、`source_refs=[]`、掉 `immutable_raw_content_conflict`（上一轮是被原样采信），而把它改成**更早**的 06:00 仍被复用，没有重演 K3-R56；β 闭——`recursive` 变成无默认的 keyword-only，四个调用点（web ×2、capstone、policy 测试）全部显式传值；γ 闭；δ 记为覆盖迁移。

**全量由我按 rule 4 接管重跑**（执行方那轮因外部私有根锁 `OSError 36` 停在 UNKNOWN）：`Ran 4984 tests in 476.291s` / `OK` / `status=PASS exit=0 tests=4984`，已记账。4984 = 我 FAIL 轮的 4983 加一条新签名回归，说明曾经红的 `LanePerItemConformance` 已绿且别处没动。`state/us_short` 0 文件，全程无 provider / key / network / live 动作。

**至此 K3-R71 / K3-R72 CLOSED，K3-R31 / K3-R32 CLOSED，解冻链 ④ 闭合。** 剩下的只有步骤 ⑤ 解 K3-R34，需用户单独命令。

## 2026-07-29 追加：K3-R34 步骤⑤ offline repair 独立审查 **FAIL**

判 **FAIL**，三条 Required。方向没问题——重试性 residual、mutex、DeepSeek transport-reporting 适配器、以及把 live 权限从模块态挪进闭包，这些都是对的。问题出在「挪进闭包」并没有真的把门关上。

**K3-R73**：`del _issue_live_ticket` 只删了模块名，而 `run_web_fetch` 本身就是捕获了它的那个闭包。我的探针（零网络）：`run_web_fetch.__code__.co_freevars` = `['issue_ticket','new_transport','run_impl']`，从 `__closure__` 直接取出票据工厂，配上仍然模块公开的 `_new_live_transport()`，`build_web_fetch_packet` 就吐出 `execution_mode=live_authorized`、`transport_response_counts={'tavily':1,'deepseek':0}` 的收据。X lane 两扇门一模一样。**新加的守卫恰好只钉了关着的那两扇**——`hasattr(fetch,"_issue_live_ticket")` 为 False、`__kwdefaults__` 里没有 `_issue_ticket`——从不看 `__closure__`。所以解冻清单里的 Optional (b)「不可证伪的 live_authorized」**没有闭合**，不能记成已闭。影响仍然有界（真正有用的伪造还需要磁盘上能对上 `content_sha256` 的 raw 收据），这不是「钱能被挪走」，而是「那个标签依然可以在进程内伪造」。

**K3-R74**：票据用 `id()` 记进 `set[int]`，且不持有对象引用。任何在 consume 之前抛错的 live 建包都会把 id 永久留在集合里而对象被回收，CPython 随后会把同一地址分配给新对象。探针：发一张票、丢引用、`gc.collect()`、连续分配 `object()` 直到撞回那个地址——撞上了，拿它当 `_live_ticket` 又建出 live 收据。这条连 `__closure__` 都不用碰，是本刀新引入的。

**K3-R75**：真实 `state/us_short` 里留着 `us_short_llm_theme_discovery_x_xai_20260725_budget.json`，`first_reserved_at 2026-07-29T03:06:00Z`，是执行方本轮写的，1 次 xai 预留。它 gitignored，所以 `git status` 看不见——这正是「`state/us_short` 不留文件」必须真去查、不能靠推断的原因。后果有二：红线被破；以及 20260725 那周真正授权的 live X 运行会对着一份没有任何真实运行做过的预留开始，静默吃掉 15 次上限中的 1 次并污染花费审计。X live 路径在建 client 之前就预留，所以它本身不证明发生过付费请求。

四条 Optional（mutex 平台锁定、`_reports_transport` 属性开关、`_live_receipt_retry_evidence` 把五个 live 归属字段移出不可变信封、register 顶部新开了第三个同名 anchor 小节）与完整闭合判据的单一来源仍是 `docs/system_risk_register.md#R-USSHORT-KNIFE3-WEB-X-MERGE-PACKET-BOUNDARY`，本节不复述。

全量：我按 rule 4 亲起官方账本，在结论发出之后返回 `Ran 4993 tests in 492.250s` / `OK` / `status=PASS exit=0 tests=4993`，已记账。**这个绿不触及上面三条 Required**——K3-R73 的守卫钉的是关着的那两扇门，K3-R74 没有任何测试覆盖，K3-R75 是 gitignored 残留、测试根本看不见。按 rule ③ 探针已坐实 FAIL，故先出结论、账本结果后补。全程未执行任何 live/provider/network 路径。

## 2026-07-29 交接：K3-R76 / K3-R77 修复方案（执行者 = Codex）

### 用户目的（这一节比下面的方案更重要）

用户要的不是「把这两条修好」。用户要的是**这一类漏洞以后不要再出现**。所以本刀的交付物是**谓词**，不是补丁；补丁只是让谓词能变绿的附带产物。判据是：一年后有人往这条 lane 里加一个新函数，他不需要读过本文件、不需要记得这些教训，机器也会在他犯同一类错误时当场喊停。

### 背景（为什么会走到这里）

K3-R34 的码级 live 冻结已按用户授权解除，真实付费请求已获授权，所以这条 lane 现在是真钱边界。解冻当轮的独立审查开出三条 Required（K3-R73/R74/R75）。用户令审查者自己修，修完起独立对抗子 agent 复核——**子 agent 判 CONFIRMED-BROKEN，而且指向的是修复者新加的那两道守卫本身**。全量在两次都是绿的（4993 OK、4998 OK），两次都与缺陷无关。

这已经是同一现象在本会话内的第四次：

| 轮次 | 缺陷 | 全量状态 |
|---|---|---|
| K3-R70 | 修复把未声明批级 raise 放进 item 循环 | 全量红（守卫是谓词，抓到了） |
| K3-R71 | 同一个错误换个函数再犯 | 全量红（同一条谓词，又抓到了） |
| K3-R73/74/75 | 能力可达、id 复用、operator state 残留 | **全量绿**（没有谓词） |
| K3-R76/77 | 修复者新加的守卫自身失效 | **全量绿**（谓词写错了） |

规律很清楚：**写成谓词的类会被机器逮住；写成散文（矩阵行）或写成手写断言的类不会。** 矩阵第 XII 行「No test, probe or review may write into operator state」一字不差地存在，K3-R75 照样发生。

完整复现、探针输出与闭合判据的单一来源是 `docs/system_risk_register.md#R-USSHORT-KNIFE3-WEB-X-MERGE-PACKET-BOUNDARY`（K3-R73…K3-R77），本节不复述。

### K3-R76 — 残留谓词定错了范围

**错在哪**：`state/us_short` 是本 lane **合法的**写入地（`_provider_budget_path` 就落在里面，另有约 20 个 us_short runner 也写那儿）。现在的 `LaneResidueConformance` 断言该目录必须为空，因此第一次授权 live 运行之后它会**永久转红**；今天能绿只是因为还没跑过 live。它的植入对照还往它自己管的目录里写文件。**这是一个定时炸弹，不是守卫——在修好之前这棵树不要合并。**

同时更正 K3-R75 的表述：问题从来不是「这里有个文件」，而是「**一次测试或探针替一个真实决策日铸了 live 预留**」。

**方案（必须做）**：谓词改成按**进程生命期**区分，而不是按目录是否为空。模块导入时记下起始时刻，断言真实 `STATE_DIR` 里没有任何文件的 mtime ≥ 该时刻。这样既能精确逮住「本次测试进程写了 operator state」，又不会被此前合法 live 运行留下的账本误伤。植入对照改成往**临时根**植入，不得写进被管辖目录。测试 docstring 必须写明它只能看见排在它之前运行的模块——这是真实限制，要说出来而不是藏起来。

**方案（更强，若可行则一并做）**：让测试包在结构上**看不见**真实 `STATE_DIR` / `DEFAULT_RAW_ROOT`——包级 fixture 在整包期间把它们指向临时根。这与本 lane 已经成功的「一个写门」哲学一致：不是去检测第 N+1 个调用点，而是让它不可能存在。若判断代价过高，明确记录为未做及理由，不要做半截。

### K3-R77 — live 授权票据是装饰性的

**错在哪**：不需要 `run_web_fetch.__closure__`。`_new_live_transport()` 模块公开、且被修复者自己的清单认可为正当的门；拿到任一 transport 实例后 `type(t)._consume_ticket.__closure__` 直接暴露**可变的** `issued_tickets`，塞入伪造对象即得 `execution_mode=live_authorized` 与伪造的 `transport_response_counts`。因此 `del _issue_live_ticket`、「不得再导出」断言、`__kwdefaults__` 断言三样都不保护任何东西。

**先接受一个事实再动手**：进程内的 Python 防不住进程内的 Python。本会话已经两次证明「把能力藏起来」只是把门挪一层（模块属性 → 闭包 cell → transport 类的闭包）。**不要再试第三次。**

**方案（必须做）**：

1. **停止声称不可达。** 删掉或改写所有暗示「外部无法取得」的注释与断言，包括那三条装饰性断言。文档要写明真实边界。
2. **把守卫钉到那条真正成立的性质上**：伪造的 `live_authorized` 标签**买不到可计分的证据**——它仍然必须拿出磁盘上能对上每一个 `content_sha256` 的 raw 收据，而 merge 会重新推导。新增一条载荷性测试：用最省事的路径在进程内伪造一份 live 收据，驱动它过 merge → knife-2，要求被拒或产出零个可计分成员。**这条测试会在有人削弱 raw 收据 / `content_sha256` 重推导时转红**，那才是真正护着钱的那道门。
3. **清单守卫保留，但改成行为判定而非名字判定**，并把它的主张改准确：它能发现**改名与挪位**，它**不能**阻止新门出现。名字过滤（`transport`/`capabilit`/`ticket`）已被证明会漏掉 `_mint_live_authority` 这类命名；改成枚举模块内所有可调用对象、判断其返回值的类型是否定义了 `_consume_ticket` / `_record_completed_response`。
4. **票据泄漏**：发票放进 `try/finally`，前置校验抛错时归还，避免未消费票据无限累积且对任何 transport 长期有效。
5. `_live_receipt_retry_evidence` 补 `execution_mode` 门——它按名字与 docstring 只该作用于 live 收据，现在离线收据也被投影。

### 类级要求（本刀真正的交付物）

以下五条针对本 lane 生效，写进代码/测试，不是写进备忘：

1. **复发计数是触发器，不是严重度。** 同一缺陷类第二次出现时，该轮的交付物是**对整条 lane 生效的可执行谓词**，不是实例修复。
2. **谓词必须是行为判定，不是名字判定。** K3-R77 的清单守卫正是栽在名字匹配上。
3. **植入对照必须忠实。** 变异要把原缺陷**逐字**还原，不能近似——本会话发生过一次：近似的植入没打死守卫，看上去像守卫失效，实际是植入写歪了。
4. **每加一道守卫，必须回答「什么样的合法未来状态会让它变红」，并把答案写进 docstring。** 没人做这一步，于是产生了 K3-R76。这是新规则里最重要的一条。
5. **当修复者与审查者是同一个行为体时，PASS 之前必须有一个独立对抗子 agent。** 本轮正是它逮住了修复者自己的守卫缺陷。

### 边界

不解除任何现存 fail-closed 门；不执行 provider / key / network / live；不动 `theme_soft_boost_enabled`；不开 4d；不第二个 decision_date；`state/us_short` 不留残留；不 push、不 remote add。改完由 Claude Code 独立复审，全量按 rule 4 一次。

## 2026-07-29 追加：K3-R76 / K3-R77 独立审查 —— K3-R76 CLOSED，K3-R77 未闭（FAIL）

**K3-R76 闭了，而且做法比我指定的好。** 我要的是按 mtime 区分，执行方用的是 import-time 基线：`unittest discover` 在任何测试跑起来之前就把所有模块 import 完，所以基线是**全包范围且与执行顺序无关**，比我提的进程时刻更强，同时天然容忍此前合法 live 运行留下的账本。我用外部植入验证（不采信它的 inline 对照）：往真实 `state/us_short` 放一个文件 → 守卫红；清掉 → 绿；对照本身也改成往临时根植入，不再写进它管辖的目录。

**K3-R77 没闭，而且是同一个形状连续第三轮。** 上一份交接写得很直白：进程内的 Python 防不住进程内的 Python，本会话已两次证明「把能力藏起来」只是把门挪一层，**不要再试第三次**。本轮试了第三次——`_make_live_capabilities` / `_new_live_transport` / `_issue_live_ticket` / `_revoke_live_ticket` 全部从模块作用域删掉——伪造路径原封不动：

```
runner freevars              : ['issue_ticket', 'new_transport', 'revoke_ticket', 'run_impl']
transport via runner closure : LiveTransport
cells behind _consume_ticket : ['issued_tickets', 'ticket_lock']
FORGED via registry mutation : live_authorized {'tavily': 1, 'deepseek': 1}
```

而新守卫 `test_factories_are_not_module_public_or_runner_defaults` **第三次**只断言了刚刚关上的那四扇门，一次也没碰开着的那扇。这正是我在类级要求第 4 条里点名的病：加守卫时没问「什么样的状态会让它变红」，于是它只对已经不可能发生的事情敏感。

**上一份交接指定的第 2 项交付物没有建**：一条载荷性测试——用最省事的路径在进程内伪造一份 live 收据，驱动它过 merge → knife-2，要求被拒或产出零个可计分成员。那是**唯一真正护着钱**的性质，也是唯一会在有人削弱 raw 收据 / `content_sha256` 重推导时转红的守卫。本 diff 里没有它。

**闭合条件不变，并且现在是唯一可接受的一条**：不要再挪能力；把所有「外部不可达」的声称改成实话；把守卫钉到下游那条真正成立的性质上。仍开着的 Optional：`_live_receipt_retry_evidence` 还没有 `execution_mode` 门（离线收据也被投影）；增长谓词覆盖了 `state/us_short` 但没覆盖 `provider_samples/`。

完整复现与闭合判据的单一来源仍是 `docs/system_risk_register.md#R-USSHORT-KNIFE3-WEB-X-MERGE-PACKET-BOUNDARY`（K3-R76 / K3-R77），本节不复述。

全量补记：我按 rule 4 亲起的官方账本在结论之后返回 `Ran 4998 tests in 472.563s` / `OK` / `status=PASS exit=0 tests=4998`，已记账。**这个绿与 K3-R77 无关**——伪造路径没有任何测试覆盖，而新守卫只对「模块上又出现一个属性名」敏感。

## 2026-07-29 追加：K3-R77 复审 **PASS** —— 解冻链⑤ 的 offline repair 至此闭合

关掉它的方式是**停止假装**。两 lane 的 `_make_live_capabilities` docstring 现在开头就写「this is not a security boundary」，并明说进程内 Python 能读闭包、能改被捕获的对象，所以工厂和 `live_authorized` 都不证明真的调用过 provider；然后点名真正的边界（merge 重读每份 raw 收据、重新推导 `content_sha256`）并指向钉住它的控制。守卫类改名 `LiveTransportLifecycleConformance`，主张改成「一次性票据保证正常路径的生命期正确性，不是 provenance」，误导性的模块属性清单断言撤掉了——「只断言已经关上的门」没有第四次。

交接指定的第 2 项交付物建成了：一条证明光有标签买不到东西（`themes == []`、knife-2 抛 `ProvisionalThemeValidationError`），一条把 raw 字节在磁盘上换掉后要求 merge 拒绝。**载荷性由我外部挖空验证，不采信它的 docstring**：把 `merge._guard_raw_content_digest` 里的哈希拒绝改成死分支，那条具名控制**转红**；还原后绿。这才是真正护钱的那道门，而且它现在会在被削弱时死掉——此前每一版守卫都只在「模块上又冒出一个属性名」时才死。

伪造路径本身没变、也不该变：我的探针依旧经 `type(transport)._consume_ticket.__closure__` 拿到 `issued_tickets` 并造出 `live_authorized`。区别在于系统不再声称相反。

全量按 rule 4 我亲起：`Ran 4999 tests in 450.019s` / `OK` / `status=PASS exit=0 tests=4999`，已记账；`state/us_short` 0 文件。仍开的两条 Optional（离线收据被 retry 投影、增长谓词未覆盖 `provider_samples/`）见 register，不阻断。

## 2026-07-29 交接：K3-R79 修复方案（执行者 = Codex）

### 从哪棵树开始

**从 master（`D:/cnhea/Stock`）开始，不要从 48b5 的旧状态。** 首次授权的真实付费运行是在 master 上跑的，K3-R78 与 K3-R79 也只记在 master 的 register 里；48b5 落后于 master，动手前先同步。

### 用户目的

让这条软发现通道的 **5.0 档在真实数据上真的能拿到**。现在拿不到，不是因为设计不成立，是因为一条缺失的身份规则把真实的、有平台背书的证据全判成了没背书。

### 背景（一次付费探针把三选一变成一选一）

首次真实付费运行（决策日 `20260731`，刻意非交易日）里 web 健康、X 全空：3 次 xai 调用买到 0 条证据，15 条模型来源全部掉 `model_source_url_not_provider_annotated`。当时无法区分三种可能——annotation 是空的、类型不对、还是仅不匹配——因为零接收意味着没有 raw 落盘。用户授权后花一次调用查清：

```
output[5] type='message' content[0] type='output_text' annotations=17 types=['url_citation']
provider annotation : https://x.com/i/status/1937910118252712411
model source        : https://x.com/Umbisam/status/1937910118252712411
annotations 17 / canonical 17 | model sources 6 | 字符串交集 0 | 按 status ID 交集 6/6
```

provider 用平台自己的 `/i/status/<id>` 规范形式，模型用 `/<handle>/status/<id>`，19 位 ID 完全相同。**六条模型来源，六条都在 annotation 集合里。** 所以那 15 条全是误杀，K3-R65 选项 (c) 的补偿在真实数据上是可满足的。

### 方案（形状很关键，别修宽了）

**不要动 `_canonical_locator`。** 两个理由，都不是风格问题：

1. `_source_id` 是它的 sha256。改它会让所有 X source ID 变掉，波及已冻结的证据与已发布的收据。
2. 把 `/<handle>/status/<id>` 折成 `/i/status/<id>` **会丢掉 handle**——身份上等价，出处上有损。K3-R35/K3-R36 定下的规矩是「只做无损变换」，这一条不满足。

**要做的是**：locator 一个字不动，只在**「annotation 背书」这一处比较**时改成按 **X 帖子身份**比：host 属于 x.com / twitter.com 家族、且路径形如 `/<任意段>/status/<数字>`，才提取那串数字作为身份；其余一切 URL 保持今天的精确 canonical 比较不变。

### 必须配的反向对照

- 上面六对实测 URL 必须绑上；
- 两条**真正不同**的 status id 永不相撞；
- 非 status 的 x.com 链接、以及任何非 X 域名，行为一字不变；
- 挖空这条新身份规则，某条**具名**测试转红。

### 这次为什么 4,999 条离线测试全都没发现

因为每个 fixture 两边都用同一种 URL 写法。这条属于「只有真实 provider 才暴露」的类，和 K3-R49/K3-R50 同一族——离线再密的覆盖也照不到。修复时值得顺手想一句：还有哪些地方是「我们自己造的两端天然一致、真实两端却可能不一致」。

### 边界

不解除任何现存 fail-closed 门；不放宽 K3-R65 的补偿本身（背书要求保留，只修身份比较）；不执行 provider / key / network / live；不动 `theme_soft_boost_enabled`；不开 4d；`state/us_short` 不留测试残留；不 push。改完由 Claude Code 独立复审，全量按 rule 4 一次。

## 2026-07-29 update: K3-R79 + K3-R83 executor repair (pending Claude Code review)

X backing now compares a status ID only at the annotation seam for X/Twitter `/<segment>/status/<digits>` URLs. `_canonical_locator` and `_source_id` stay unchanged, preserving source provenance. Mismatch drops now carry both `model_source_url` and the canonical `provider_annotation_urls` candidate set, required by schema for that reason. Live X snapshots one JSON-safe raw provider response per completed call to a gitignored shared provider-response path and binds its hash/ref in `provider_response_refs`, including zero-accepted packets.

Main-Python focused superset = 97 OK; the six measured pairs, different-id/non-status/non-X cases, identity hollowing, two-sided drop fields, and mocked-live zero-accepted raw replay/hash control are covered. The single rule-3 full ledger run = 5003 OK at 2026-07-29T18:18:34. The historical web run accepted sources, so its zero-accepted shape is N/A. No provider/key/network/live request, scoring change, K3-R34 lift, push, or remote action occurred.

## 2026-07-29 update: K3-R86..K3-R93 executor repair (pending Claude Code review)

All eight review Required items are implemented. Historical frozen X receipts remain schema-valid because the new provider-response and annotation fields are optional at read time; the current builder requires them. Each completed paid response is represented exactly once by a frozen ref or an indexed drop, so one malformed/unsafe/conflicting response cannot erase its siblings. The persisted-text policy is value-shaped, annotation locators must be strict HTTPS X/Twitter status URLs, and one provider annotation owns one persisted source identity. Attempt telemetry is removed from immutable retry comparison. Drop fields are sink-sanitized and the annotation set is stored once.

Merge keeps the legacy no-field read path, but a new-format receipt must carry both evidence fields and prove complete response accounting against `transport_response_counts["xai"]`. Every provider raw ref is bound to the `provider_responses/<decision_date>/xai_<digest>.json` namespace, gitignore status, frozen bytes, digest, and a fetch clock no later than the matching artifact/receipt `generated_at` and before decision open.

The one scheduled read-only adversarial self-review returned FAIL with four residuals: exact non-X annotations, incomplete response accounting, movable raw namespace, and a post-generation/pre-open raw clock. All four were accepted and repaired with reverse controls; no second agent was started. Final fixed-main-Python focused evidence is 105 OK plus the R93/executable mutation pair 2 OK. The official full-pack ledger records 5010 OK on fingerprint `baedefe2e01e` at 2026-07-29T20:26:41. Earlier attempts are historical only: one found the missing guard registration, one was refused after a concurrent master HEAD advance despite 5010 OK, and one hit a resource-isolation flake whose exact nested test passed standalone. No provider/key/network/live request, score/effect change, K3-R34 change, push, or remote action occurred.

## 2026-07-29 update: K3-R94..K3-R96 executor repair (pending Claude Code review)

K3-R94 accepts the known exact X post form `/i/web/status/<digits>` in addition to the existing strict status route; HTTPS, no-port, X/Twitter host, numeric identity, and never-cited refusal are unchanged. K3-R95 separates response-level immutable conflicts from source-level `immutable_raw_content_conflict` and uses one shared provider-response drop-reason set in both builder and merge. A source raw conflict therefore cannot poison provider-response index accounting; the offline merge control and malformed-index control are pinned.

K3-R96 is a documentation correction, not a fictional new storage contract: merge currently verifies `provider_samples/**/provider_responses/<date>/xai_<digest>.json`, and each completed response is either raw-byte verified or represented by an indexed capture-unavailable/unsafe/conflict assertion. It does not guarantee raw bytes for every paid response and does not bind one fixed producer subtree. The five Optional residuals stay in the risk register. Main-Python focused evidence: fetch/merge 59 OK; schema/conformance/class guards 38 OK. The executable matrix produced no terminal test summary in this invocation and is NOT_VERIFIED. Official full lane: 5012 OK / 666.3s, recorded 2026-07-29T23:03:21 for the exact code state. No provider/key/network/live request, score/effect, K3-R34, push, or remote action occurred.

## 2026-07-29 追加：K3-R94 / K3-R95 / K3-R96 + O1..O5 独立审查 —— **FAIL**（执行者 = Codex）

### 审的是哪棵树

**master（`D:/cnhea/Stock`）的未提交工作树。** 用户本轮指定的审查树是 `D:/cnhea/Codex/worktrees/48b5/Stock`，但那棵树停在 `09f6c939` 且完全干净——本轮被审的代码与文档全在 master 的工作树里，register 的 K3-R86..R96 也只存在于 master。把判定写进 48b5 那份落后的 register 会把单一来源劈成两份，所以本次收口（register / SESSION_LOG / 本交接）全部落在 master。48b5 要接着干，先同步到 master tip 再动手。

### 这一轮通过的部分（不必重做）

- **K3-R94 已闭**：`_x_status_identity` 的路径族扩到 `/(<segment>|i/web)/status/<digits>`，host / HTTPS / 无端口 / 纯数字 / 未被引用即拒全部没松。我自己的 11 例身份探针 + 端到端背书探针（`/i/web/status/<id>` 的 annotation 能背书 `/<handle>/status/<id>` 的模型写法，另一条从未被引用的仍掉 `model_source_url_not_provider_annotated`）全绿；`/a/b/status/<id>`、`/i/web/extra/status/<id>`、`http://`、`notx.com`、带 `/photo/1` 尾段一律 None，没有修宽。
- **K3-R95 已闭**：响应级冲突改用自己的 `provider_response_immutable_raw_content_conflict`，选择集中在 `fetch_x.PROVIDER_RESPONSE_DROP_REASONS` 一处、builder 与 merge 同源消费。**植入对照**：把源级 `immutable_raw_content_conflict` 塞回该集合，`_validate_builder_receipt_evidence` 立刻转红——证明这条分离是承重的。
- **K3-R96 的文字确实改真了**：R86..R93 条里"四条 residual 全部接受并关闭"的错话已换成"确认八条闭合，另开 K3-R94/R95 与 K3-R96 边界"，namespace 与 raw 存在性的保证也降到代码真做到的那句。
- **真实付费证据没有被回踩**：拿 `state/us_short` 里 20260731 的四份冻结产物核过——11 条 web locator 与 source_id 在新的 `_canonical_locator`（O1 把百分号八位组规范化提到安全检查之前）下一字未动，两份收据仍过各自 schema，真实 web+x 配对 merge 仍绿（3 个主题）。O1 没有动到已冻结身份。

### 为什么还是 FAIL（正文只在 register，本处不复述）

`docs/system_risk_register.md#R-USSHORT-KNIFE3-WEB-X-MERGE-PACKET-BOUNDARY` 的 **K3-R97 / K3-R98 / K3-R99**。三条的共同点：**没跑全量就并进来的那五条 Optional，把两道仓库自己的静态守卫打红了**；其中 K3-R97 是"一个坏件不许弄死整批"这条红线的第三次复发（K3-R87/R88 → K3-R95 → 现在），这次由修复本身引入，还被它自己的测试钉成了"期望行为"。

### 验证命令与结果

- 全量（rule 4，我亲起并记账）：`.tools\full_pack_ledger.py run us_short … 1300 -- discover -s tests -p test_us_short*.py` → `status=FAIL exit=1 tests=5017 elapsed=422.4s` / `FAILED (failures=3)`。三条红：`LanePerItemConformance.test_no_undeclared_batch_level_raise_inside_an_item_loop`（点名 `line 542`）、`LaneWriteDoorConformance.test_only_the_publish_policy_module_touches_the_filesystem`（点名 `line 638: unlink` / `line 642: rmdir`）、`ExecutableClosureMatrix.test_d_repo_shared_resource_tests_inject_state_and_lock_roots`（`(1, 1) != (1, 0)`）。
- 自写探针三组（身份/背书、K3-R95 植入对照、O1 冻结证据回归）与 K3-R97 复现探针（出厂 orchestrator + 出厂校验器，未打任何补丁）：结果见 SESSION_LOG 本轮 `Verify`。
- §6a 未起独立 agent：该门是 PASS 前的义务，本轮 FAIL 已由自写探针与仓库自身守卫双重坐实。

### 失效的旧结论

- "O1..O5 属 Optional-only，可按 carve-out 免全量" —— **作废**。carve-out 免的是 §6a 的独立 agent，不免 rule 3 的**改动面**触发；O1 改的是两条 lane 与 merge 共用的 `_canonical_locator`，O4 在 live 路径上加了删文件。
- "`tests.provider.test_us_short_llm_theme_discovery_fetch_x_merge` = 64 OK 足以收口" —— **作废**（K3-R80 同一教训再现）：被打红的两道守卫的测量范围是**整个包**，focused 模块绿对它们没有证明力。
- register 里"K3-R96-O1..O5 remain Optional as recorded above"这句已被紧随其后的修复条目推翻，改 tier 行时一并改掉（已记为 K3-R99 内的 Optional）。

### 给 Codex 的命令

`修复` K3-R97 / K3-R98 / K3-R99，范围与 closure 条件以 register 三条为准。三点强制要求：

1. **K3-R97 按类修，不要只把 `raise` 换成 drop**：序号必须来自"真正完成的调用"这个计数器（或在调用点就地记下完成序号），让**没打通的调用不占完成序号**；每条完成但抓不下来的响应仍要留 indexed drop；剩余不匹配只能是 ledger 行，不能是 item 路径上的 raise。同时改写 `test_k3_r96_o5_response_indexes_are_paid_call_ordinals_or_fail_closed`——它现在把缺陷钉成了期望行为。必配对照：**多条查询、其中一条 provider 调用失败，整包仍然发布，且好那条的 raw ref 在收据里**。
2. **K3-R98 走写门**：删除动作要么搬到 publish-policy 那道唯一写门后面，要么直接不删（让收据成为"哪些 raw 算证据"的唯一权威）；没有可读的已发布收据时一律不删；清理失败不得改变一次成功发布的退出码。
3. **K3-R99 = 一次绿的全量**：最终代码态跑一次 `full_pack_ledger run us_short` 并记账；第三条红（`ExecutableClosureMatrix` 的 resource-root 注入）要么单跑复现并修掉、要么明确证明它是 flake，不能只说"上一轮也这样"。

边界照旧：不执行 provider / key / network / live；不动 `theme_soft_boost_enabled`；`state/us_short` 与 `provider_samples` 不留测试残留；不 push、不 remote add。改完由 Claude Code 独立复审。

## 2026-07-29 update: K3-R96-O1..O5 Optional executor repair (pending Claude Code review)

All five recorded Optional residuals are repaired without provider/key/network/live action. Locator security now normalizes percent-encoded unreserved octets before screening, stale provider raw clocks fail the decision-week lower bound, model Grok sources are capped at 500, and unreferenced digest-named X response raws are pruned only after immutable publication identifies the winning receipt. Response indices are request ordinals; a gap or duplicate fails closed instead of being rebased to a successful-response position. The focused X fetch/merge module is 64 OK / 7.702s; compile and diff checks pass. Optional-only tiering means full-lane is intentionally not rerun for this code state. No score/effect, K3-R34, push, or remote action occurred.
