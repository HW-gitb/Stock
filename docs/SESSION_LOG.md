# Session Log

跨 LLM 认知交接日志。**reverse-chronological，最新 entry 在顶部**。

本文件存在的目的：commit message 和 handoff 记录"改了什么 / 为什么改"，但不记录 "试过什么没成 / 试过的方案为什么被否决 / 当前 LLM 的纠结点 / 下一步该做什么的判断"。这一层认知信息在跨 LLM 协作时最容易丢失。

进项目前每个 LLM 必读：本文顶部 1-3 条最近 entry。完整规则见 `AGENTS.md §Session log discipline`。

---

> 📦 **历史归档**:2026-05-25 … 2026-06-12 的 861 条更早 entry 已逐字移至 `docs/archive/session_log/session_log_archive_2026-05-25_to_2026-06-12.md`(完整历史,不丢)。本次归档时保留了归档前最新 30 条;之后新增 entry 继续累积到本文件,过大时再按 `AGENTS.md §Session log discipline → 归档` 归档。追溯更早请开归档文件。

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
