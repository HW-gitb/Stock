# AI Review Protocol

本文件定义本项目的多 LLM 审查流程。`AGENTS.md` 仍是最高级协作规则。

## Roles

- **Codex = Designer + Implementer**
  - 设计方案、实现代码/文档、运行验证、更新 handoff / CURRENT / SESSION_LOG。
  - 对 Claude 的建议做技术判断，但不得在用户确认前直接执行 Claude 的建议。

- **Claude = Independent Reviewer**
  - 独立审查 Codex 的设计、代码、schema、测试和交接文档。
  - 输出 findings、风险、缺失测试、是否建议通过。
  - 不直接写代码，不直接改文件。

- **User = Final Approver**
  - 决定是否接受 Claude 的审查意见。
  - 决定 Codex 是否进入修复、继续下一步或暂停。

## Workflow

1. Codex 读取 `AGENTS.md`、`docs/CURRENT.md`、`docs/SESSION_LOG.md` 顶部 entry 和相关 handoff。
2. Codex 设计并实现当前任务，完成验证和文档交接。
3. Codex 提交稳定里程碑。
4. Claude 独立审查该里程碑。
5. 用户根据 Claude 审查结果做最终确认。
6. Codex 仅在用户确认后执行修复或进入下一阶段。

## Review Outcomes

- **通过**：用户确认后，Codex 继续下一最小任务。
- **需修复**：用户确认修复范围后，Codex 按范围修复、验证、提交，并更新交接。
- **失败 / 阻断**：Codex 暂停推进业务实现，先解决阻断项或等待用户裁决。

## Boundaries

- Claude 的输出是审查意见，不是执行指令。
- Codex 不得把 Claude 建议自动当成已批准需求。
- 用户确认前，不因审查意见修改业务代码、schema 或 phase 边界。
- 若审查涉及跨 phase、schema contract 或策略结论变化，必须更新对应 handoff。
