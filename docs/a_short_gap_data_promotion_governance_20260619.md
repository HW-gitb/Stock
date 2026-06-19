# A-short 4.2 Field Promotion Governance

**Owner**: 4.2 缺口数据字段在 weekly 同跑、汇总展示后的转正提醒与审查边界。

**Status**: governance contract only. This file does not auto-enable production scoring, hard vetoes, sizing changes, EGS ranking changes, broker/order behavior, or real-money use.

**Source**: consolidated from desktop `price calc.md` §12 into the repo so the rule no longer lives only in a local draft.

## 1. Core Rule

4.2 字段可以一起同跑、一起汇总展示,但转正提醒和正式接入必须按**字段**或**字段族**分别触发、分别审查、分别批准。

禁止把 4.2 字段整包一次性转正。

## 2. Reminder Unit

Allowed reminder units:

- `field`: 单个独立字段,例如单项公告风险、单项资金事件。
- `field_family`: 同一数据源或同一逻辑的一组字段,例如龙虎榜字段族、大宗交易字段族、财报质量字段族。
- `summary_table`: 可以一次性列出所有字段状态,但每一行必须有独立状态和独立审查建议。

Forbidden wording:

```text
4.2 已整体满足条件,建议全部纳入主程序。
```

## 3. Effective Live Week Gate

Default promotion-reminder gate = **12 effective live weeks**, not 12 calendar weeks.

One effective live week must satisfy all of these:

- The reviewed weekly flow actually ran for that field or field family.
- The field source, schema, missing-data handling, and PIT semantics were valid for that week.
- The field was visible in M6.7 or the weekly summary.
- The week was not made incomparable by provider failure, field absence, schema drift, logic rewrite, or source-definition change.

If data source, field definition, calculation logic, missing-value handling, production/advisory impact path, or schema changes materially, that field or field family's 12-week count resets unless a separate reviewed decision explicitly allows inheritance.

## 4. Reminder Is Not Promotion

At 12 effective live weeks, the system may only raise a review reminder, for example:

```text
field_or_family: 北向资金
status: promotion_candidate
effective_live_weeks: 12/12
promotion_review_required: true
recommended_review_scope: 风险扣分 / sizing
```

Formal promotion still requires a separate review, explicit user approval, and a committed implementation slice.

## 5. Field-Type Boundaries

Structured fields may request promotion into scoring, risk deduction, sizing adjustment, or advisory-only display, depending on their evidence.

LLM / web advisory fields default to display, explanation, and manual review only. Any move into build/position sizing/hard-veto behavior requires a stricter separate review.

No 4.2 field may rescue a production hard veto. Anti-rescue stays mandatory.

## 6. Current 4.2 Disposition

Current feasible 4.2接入 is complete for:

- `exclusion_summary`
- candidate and holding semantic advisory
- S3b holding management advisory fields
- 龙虎榜
- 大宗交易
- 财报质量 / 财报趋势 / 行业基本面

Known non-current-production boundaries:

- 外资单票 is not active because `hk_hold` is unavailable after 2024-08 in the current route.
- Semantic promotion to production hard veto is not part of the current 4.2 completion; it needs a separate PIT-source review.

## 7. Future Implementation Contract

If a future weekly promotion summary is implemented, it must include:

- field or field-family id
- status
- effective live week count
- reset reason, if any
- target effect under review
- whether review is required
- evidence window reference

Tests must reject bundled whole-4.2 promotion, LLM advisory auto-promotion, and any attempt to rescue a hard veto.
