# A-short Rule6 severity 分类纠错交接

## Scope

本轮只纠正 `candidates[].event_risk.rule6_checks[].severity` 的效果分类，并补一条 Phase5 反向控制测试；不改生产者、不建 M6.7 消费者、不重封冻结包、不扩展到其他系统。

## Verdict / Action

- `severity` 在已生成的 `analysis_input` 中不是 M6.7 决策输入；Rule6 主决策由 `status` 驱动。
- `schemas/a_short_m67_effect_contract.json` 已将该叶从 `m67_main_decision` 改为 `duplicate_or_display_audit`。
- 新增测试证明：只改 `severity` 不改变 M6.7；改 `status` 会改变 Rule6 终态。

## Required

独立 reviewer 必须复核该分类和反向测试；独立 PASS 前不得提交或 merge。`severity` schema/生产字段本身本轮保留。

## Verify

- 固定解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，Python 3.13.8。
- 定向回归：`Ran 19 tests in 2.351s ... OK`。
- `git diff --check`：OK。
- full-pack ledger：NOT_VERIFIED。

## Proof-of-use

`engine/a_short_rule6_contract.py::assess_rule6_checks` 读取 `status` 并生成 `hard_veto_check_ids` / `manual_review_check_ids`；Phase5 使用这些结果决定动作。反向测试覆盖 severity-only 与 status mutation 两条路径。

## Pre-Codex self-review

`scope=classification+negative-control`; `producer=unchanged`; `consumer=unchanged`; `focused=19 OK`; `diff-check=OK`; `full-pack=NOT_VERIFIED`; `independent-review=pending`; `commit=not performed`; `merge=not performed`。

## Next

Claude Code：独立复核本轮 Rule6 severity 分类纠错；PASS 后按项目流程提交并 merge。
