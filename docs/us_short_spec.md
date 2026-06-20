# US Short Spec — ARCHIVED POINTER (superseded)

> **状态：已降级为归档指针（2026-06-20，docs-only landing）。本文不再是 US-short 设计权威。**
>
> **单一权威 = [`docs/us_short_system_design.md`](us_short_system_design.md)**（US Short System — Design，in-repo authority）。任何 US-short 设计 / 实现讨论一律以该稿为准；本文仅作历史指针，避免两个权威并存（写 repo 第一刀 gate ①）。
>
> 旧内容（Phase 6d「把 `skills/us_short_analysis/reference/` 资料规范成 production-facing docs-only baseline」+ Phase 7a-4 evidence-feasibility routing）已被新权威稿整体吸收并细化；其设计决策、lane 边界、screening/analysis contract、hard veto、benchmark、ship-gate 边界均在新稿 §0–§19 重写。需要历史 baseline 措辞请查本文件的 git 历史（截至 commit 前的版本）。

## 不变的引用

- **源资料归档**：`skills/us_short_analysis/reference/us_short_screening_spec.md` / `us_short_analysis_spec.md` 仍是美股短线**框架参考源**（非权威、非运行时提示词），新权威稿 §16 说明如何借用。`skills/us_short_analysis/SKILL.md` 在 Phase 7 / Phase 8 实现前仍 reserved。
- **provider / 数据**：US EGS provider evidence、SR-PROVIDER-001 边界、FMP / SEC 授权状态见 `docs/provider_evidence_drift_monitor.md` + `AGENTS.md` 固化决策 #14/#22/#26 + `docs/system_risk_register.md`。新权威稿 §3 / §18.0 把 provider 授权门固化为 P0 硬规则。
- **lane / 架构路由**：`docs/strategy_design_synthesis.md`（总体架构）、`docs/burst_lane_spec.md`（独立 US burst lane，与本 steady 线分开）。
- **ship-gate / 证据级**：`docs/evidence_capital_policy.md`（paper vs live_normalized）；满仓线仍是月度 alpha t≥2.0 / Sharpe≥1.0 / 回撤≤15% / ≥12 个月 forward-live，docs 不放松。

## 边界

本文降级为指针不引入任何 schema / runner / provider / DataHub / Skill / prompt / 下单实现；US-short 实现仍 gated（须用户单独授权 + schema-first + tests + Codex 审查 + 多 LLM 串行 + 不交叉 A 股），P0 硬门见新权威稿 §18.0 与 `docs/system_risk_register.md`（`R-USSHORT-V1-P0-IMPLEMENTATION-GATES`）。
