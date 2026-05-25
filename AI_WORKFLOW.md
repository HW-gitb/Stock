# AI Workflow

本文件是 AI 协作者的轻量工作流入口；不可替代 `AGENTS.md`。所有硬规则仍以 `AGENTS.md` 为准。

## Read Order

1. `AGENTS.md`
2. `docs/CURRENT.md`
3. `docs/SESSION_LOG.md` 顶部 1-3 条
4. 当前 phase 对应 handoff
5. 任务相关代码 / schema / runner

## Work Rules

- 先确认当前 phase 边界，再改代码。
- 跨模块数据先 schema-first。
- 重要修改后同步 handoff；有 non-trivial commit 时同步 `docs/SESSION_LOG.md`。
- 不 push，不 add remote。
- 不重写用户或其他 LLM 的未提交改动。
- Phase 5 起继续保持 contract-first：先定义 execution 输入/输出，再写 runner。

## Validation

常规验证优先：

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

schema-validating 命令使用装有 `jsonschema` 的项目/本机 Python；Codex bundled Python 可用于 compile 和大部分 unit tests。

## Commit Discipline

- 小而稳定的里程碑自动 commit。
- commit 前只 stage 本轮相关文件。
- 若配额或权限阻断 commit，立即记录当前状态和下一步，不绕过。
