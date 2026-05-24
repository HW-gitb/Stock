# Claude Code 入口路由

本文件存在的唯一目的：**Claude Code 默认加载 CLAUDE.md 而非 AGENTS.md**，所以这里写一个最小路由，把你转到项目真正的 AI 协作根入口。

## 必读顺序

1. **`AGENTS.md`** — 项目不变约定 + handoff 链 + 协作守则。所有 AI 协作者必读（不管是 Claude / Codex / ChatGPT / Cursor / Cline）
2. **`docs/CURRENT.md`** — 跨会话动态状态表。当前 phase / 已完成事项 / 有效结论 / 已失效结论 / 下一步优先级
3. **handoff 链**（按 `AGENTS.md §交接记录` 顺序读，不要全量展开）

## 不可碰（在你做任何改动前必须知道）

- **不可 `git push`，不可 `git remote add`** — 私密本地仓库
- **不可改 `skills/a_short_analysis/reference/v14.2_spec.md`** 等规格文档（设计已固化）
- **不可写到 `result/a_short/<YYYYMMDD>/`** — 回测必须用 `result/a_short/backtest/generated/<YYYYMMDD>/`
- **不可绕过** `production` 模式对 `--reuse-l3-cache` / `--include-immature` 的拒绝
- **handoff 写作门槛**：默认追加到 phase 主 handoff，新建独立 handoff 是高门槛操作（详见 `AGENTS.md §交接记录`）

## 沟通风格（直接复用 AGENTS.md）

直接给判断，不堆选项让用户选。有理据时主动指出用户方案的问题。AI 协作者是建造者，不是顾问；除非用户明确问意见，默认动手。
