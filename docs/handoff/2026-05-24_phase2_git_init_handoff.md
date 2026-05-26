# Phase 2 Git 初始化 Handoff

生成时间：2026-05-24
作者：cc (claude-opus-4-7)
前置 handoff：
1. [`2026-05-24_phase2_v7.9_handoff.md`](./2026-05-24_phase2_v7.9_handoff.md)
2. [`2026-05-24_phase2_tier1only_subset_handoff.md`](./2026-05-24_phase2_tier1only_subset_handoff.md)

## 读取说明

本 handoff 在前两份之后。**项目首次进入 git 管理**，所有 LLM 接手时必须知道当前 git 状态和约束。

## 本轮改动

### 工程基础设施

| 项 | 操作 |
|---|---|
| `git init` | 在 `D:\cnhea\Stock\` 初始化本地仓库 |
| git identity | local-only：`cnhea <cnheatherwong@hotmail.com>`（仅本仓库，未污染全局 `git config --global`） |
| `.gitignore` | 新建，排除大缓存 / 敏感文件 / 日志 / 临时文件 |
| 首次 commit | hash `dca8367`，305 文件，包含全部源代码 + schemas + docs + handoffs + findings + skills + presets + 历史候选池 |
| remote | **零** —— `git remote -v` 无输出 |

### `.gitignore` 排除清单（重要：接手者必须知道）

```text
# Python
__pycache__/, *.pyc, *.pyo, *.pyd

# Sensitive
.env, .env.*, *.token, credentials*, *.key, *.pem, secrets*

# Large API caches (regenerable)
A-EGS/Result/egs_cache/           # ~861 MB Tushare 缓存
result/*/backtest/cache/          # ~121 MB forward_daily 缓存

# L3 PIT snapshots (regenerable but ONLY forward-going)
state/*/l3_snapshots/, state/l3_snapshots/

# Logs / temp / OS / editor noise
*.log, *.tmp, *.bak, *~, backup_*.zip
.DS_Store, Thumbs.db, .vscode/, .idea/, *.swp

# Claude Code local state
.claude/

# Intermediate scratch
result/*/backtest/generated/_intermediate/
```

## 私密性约束（**严格遵守，不可绕过**）

> 2026-05-26 更新：本节记录 2026-05-24 git init 时的初始 local-only 规则；remote 相关绝对禁令已由本文末尾“2026-05-26 追加：private remote allowed under constraints”覆盖。secrets / caches / logs / 未脱敏数据禁止上传的约束仍然有效。

### 必须做的

- ✅ 本地 commit 即可（默认私有）
- ✅ 改完代码 + verify 通过后 commit，保留版本历史
- ✅ 阶段性改动 commit 前先 `git status` + `git diff --cached` 检查

### 绝对不要做的

- ❌ **`git remote add origin <任何 url>`** —— 加 remote 是发布的第一步
- ❌ **`git push`** —— 没 remote 会失败但仍提醒
- ❌ **创建任何 GitHub / GitLab / Gitee 等远程仓库** 并指向本目录
- ❌ **`git config --global ...`** —— 污染用户其他项目
- ❌ commit `egs_cache/`、`forward_daily.pkl`、`*.log` 等被 .gitignore 排除的文件（除非你确认必要）
- ❌ commit 任何含 `TUSHARE_TOKEN` 实际值的文件（token 永远只在 env var）

### 如果用户将来要推到 GitHub private repo

用户必须**手动**：
1. 在 GitHub 创建 private 仓库
2. `git remote add origin <url>`
3. `git push -u origin master`

**LLM 不可主动发起这三步**，必须等用户明确指令。

## handoff 写入规则补充（git 角度）

之前的 handoff 规则："涉及版本升级、回测重跑、schema 改动、策略结论变化、数据口径变化时必须写 handoff"。

**追加规则**：

- 涉及 git 基础设施改动（add remote / 修改 .gitignore / 修改 hook / 修改 user.email）必须写 handoff
- 重大 commit（如版本升级 + 数据重跑）应在 handoff 末尾引用 commit hash 便于回溯
- 日常 commit 不需要写 handoff（git log 本身就是记录）

## 已 commit 内容（hash `dca8367`）

代码 / schema / docs / findings 全部 305 文件。摘要见 commit message：

```bash
git -C D:\cnhea\Stock show --stat dca8367 | head -10
git -C D:\cnhea\Stock log -1 --format=full dca8367
```

主要包含：
- EGS v7.9 全套代码（含 SW 修复 / L3 PIT / source metadata）
- backtest_rank.py v1.6.0 schema + Tier1-only 切片
- 3 份 findings（cc 12p 已 INVALIDATED / cc 24p / codex 24p）
- 两份前置 handoff
- AGENTS.md + schemas + skills + presets + 历史候选池

## 下次 LLM 接手应该做的

1. **第一件事 read 本 handoff**（按 AGENTS.md 链按时间顺序读 3 份 handoff）
2. **第二件事检查 git 状态**：`git status` / `git log --oneline -10`
3. **改代码前 `git diff` 验证现状**，不基于记忆假设
4. **改完后**：(a) verify (b) commit (c) **如属重大改动则写 handoff**

## 文件状态提醒（git 角度）

- 仓库根：`D:\cnhea\Stock\`
- HEAD: `dca8367 Phase 2 v7.9 baseline: ...`
- branch: `master`
- remote: **none**（私密保证）
- identity: local-only `cnhea <cnheatherwong@hotmail.com>`

## 一个未决项

本 handoff 本身（`2026-05-24_phase2_git_init_handoff.md`）以及对 `AGENTS.md` 的 handoff 链更新，**尚未 commit**。建议下个动作：

```powershell
cd D:\cnhea\Stock
git add docs/handoff/2026-05-24_phase2_git_init_handoff.md AGENTS.md
git commit -m "Add git init handoff; link in AGENTS.md"
```

## 2026-05-26 追加：private remote allowed under constraints

### 改了什么

- 原“不可 `git remote add` / 不可 `git push` / 不创建远程仓库”的绝对禁令，调整为：允许用户本人控制的 **private** Git remote，但必须满足 AGENTS.md 的 `Git remote privacy policy`。
- `AGENTS.md` 新增 remote 隐私策略：默认仍本地处理；只有用户明确要求时才可添加 remote 或 push；remote 必须 private；禁止 public remote、未授权 collaborator、secrets、日志、缓存、未脱敏实盘状态和 `.gitignore` 已排除产物进入远端。
- `docs/CURRENT.md` 同步把“不碰 remote”的雷区改为“不可无约束 remote；private remote allowed under constraints”。

### 为什么改

用户明确希望可以把项目上传到 GitHub private repo 用于私密备份 / 个人版本管理。完全禁止 remote 会阻断这个合理用途；但本项目含交易系统设计、数据缓存、日志和潜在 token 风险，因此不能放开成任意 push。新规则保留安全边界，同时允许受控 private remote。

### 验证命令

```powershell
rg -n "push|remote|private|GitHub|私密|不可 `git push`|不可 `git remote add`" AGENTS.md docs\CURRENT.md docs\handoff\2026-05-24_phase2_git_init_handoff.md
git diff --check
```

### 验证结果

- 相关文档均已出现 private remote constrained policy。
- 旧 handoff 历史段落保留原始 git init 事实；新增追加段明确覆盖后续规则。
- `git diff --check` 通过。

### 失效旧结论

- “LLM 永远不可添加 remote / push”已失效；现在只有在用户明确指令、目标为用户本人控制的 private remote、且通过隐私审计时，才允许执行。
- “remote 必须永远为 none 才能保证私密”已失效；private remote 可作为受控备份手段，但 public remote 和未授权 collaborator 仍禁止。

### 下一步注意事项

1. 真正执行 `git remote add` 或 `git push` 前，必须重新审计 `.gitignore`、`git status --short`、`git remote -v`、staged/tracked 文件中的 secret / token / credentials / logs / caches / live-state data。
2. 若用户只说“上传 GitHub”但未说明 private，必须先确认 private；不得默认创建 public repo。
3. 不要把本轮规则变更理解为可以上传 `.gitignore` 已排除文件或任何未脱敏数据。
## 2026-05-26 追加：ordinary GitHub backup cleanup

### 改了什么

- `.gitignore` 明确扩大 private backup 边界：排除 `A-EGS/Result/`、`A-EGS/*.xlsx`、`result/*/YYYYMMDD/`、backtest CSV/JSON/XLSX、`generated/`、`snapshot_seed/`、`_intermediate/`、以及 `state/*/*.json` / `state/*/*.csv`。
- 用 `git rm --cached` 将上述已跟踪生成产物和本地 live state 从 Git 索引移除；本地磁盘文件保留。
- 保留人写的 backtest findings markdown 与 `result/a_short/backtest/README.md` 在 Git 跟踪中。

### 为什么改

用户已经完成 GitHub private backup，但首次 push 前未做完整敏感信息检查。本轮本地审计未发现真实 token / API key 泄露，因此不做历史重写；改用普通 cleanup 收窄未来备份范围，避免后续继续上传可再生结果、大 CSV/XLSX、中间产物或实盘状态。

### 验证命令

```powershell
git grep -I -n -E "(TUSHARE_TOKEN|api[_-]?key|secret|password|Bearer|ghp_|github_pat_|access[_-]?token|credential)" HEAD
git grep -I -n -E "(TUSHARE_TOKEN[[:space:]]*=|DEEPSEEK_API_KEY[[:space:]]*=|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|Bearer[[:space:]]+[A-Za-z0-9._=-]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})" $(git rev-list --all)
git ls-files result A-EGS/Result A-EGS/egs_tier1.xlsx A-EGS/egs_tier1_20260515.xlsx A-EGS/egs_tier1_20260522.xlsx state/a_short
Test-Path result\a_short\backtest\rank_samples.csv
Test-Path A-EGS\Result\egs_full_20260522.csv
Test-Path state\a_short\positions.json
```

### 验证结果

- 当前 HEAD 与完整历史的 secret-pattern 扫描未发现真实 token；命中项为环境变量读取、文档安全说明、`your_token` 占位示例和第三方测试样例。
- cleanup 后 `git ls-files` 在高风险路径下只保留 human-written findings markdown 与 backtest README。
- `Test-Path` 确认被取消跟踪的本地结果和 state 文件仍在磁盘上。

### 失效旧结论

- “历史候选池 / backtest generated JSON 默认随仓库备份”不再作为推荐边界；之后默认本地保留、Git 不跟踪。
- “空 state 模板可以一直 tracked”不再推荐；未来需要 starter state 时应新增 `.example.json` / `.example.csv`，不要跟踪 live state 路径。

### 下一步注意事项

1. cleanup commit 推送前仍需用户确认 GitHub 仓库是 Private。
2. 本轮不是 history rewrite；旧 commit 中的生成产物仍存在于远端历史，但当前证据不支持为此承担 force push 风险。
3. 若未来发现真实 token/API key 进入历史，再按 incident 处理：吊销 token、重写历史、force push、重新审计。
