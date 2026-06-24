# -*- coding: utf-8 -*-
"""US-short weekend-pipeline build-gate resolution — batch4 slice 4d-ii-e (§8 weekly build-limit + 同主题 cap)
+ slice 4d-ii-f (§8 portfolio_guard / symbol_cooldown 新建阻断).

Design authority: docs/us_short_system_design.md §8 (line 227 每周新增建仓上限 + 同主题上限; line 230
symbol_cooldown / portfolio_guard new-entry block; line 238 组合级熔断 cooldown→禁新建) / §9 (selection_rank,
observe_reason_type) / §18.2 batch4.

The cross-row build-gate stage after 4d-ii-c sizing. For every PROVISIONAL 建仓 row it, in order:

  ① (4d-ii-f) NEW-BUILD BLOCKING: an account-level portfolio_guard cooldown (禁新建, the const-pinned
     `block_new_entry` effect — consumed generically from the frozen effect table, NOT hard-coded to one
     state) OR a per-symbol re-entry cooldown (symbol_cooldown_status ∈ {entering_cooldown, in_cooldown})
     downgrades that 建仓 to 观察(`risk_cooldown`) and removes it BEFORE ranking — a cooled-down symbol must
     never consume a weekly / 同主题 slot.
  ② (4d-ii-e) RANK + BASE CAPACITY: ranks the surviving 建仓 by selection strength (core_score) and applies
     the §8 BASE per-regime weekly new-build limit (进攻3 / 震荡2 / 防御1 / 极度防御0) + the 同主题 weekly cap
     (≤2). A 建仓 pushed out of this week's BASE capacity → 观察(`capacity_or_budget_deferred`) (§9 — otherwise
     executable, just no room this week — kept distinct from a cost/min-size or data/price observe so the
     §11.2 honesty split is honest).

Scope (v1): NOT here — the §8 强赛道试探名额 theme_probe EXTRA seats (engine/us_short_theme_probe.py), which
add seats BEYOND this base regime limit for strong/extreme themes (and would PROMOTE some
capacity-deferred builds, re-sized to min-executable + cost-floor checked) — that is slice 4d-ii-g WIRING.
Cash allocation (allocate_cash) + §9 action_rank are also later. The portfolio_guard GRADED modulations
(caution → reduce_position_size / reduce_weekly_new_count, recovery → only_few_high_confidence_new) are a
separate portfolio_guard-effects concern — this slice consumes ONLY the cooldown `block_new_entry` (禁新建)
effect, the user-scoped 新建阻断. No promotion: a build ranked beyond the weekly limit is never promoted into
a slot freed by a 同主题-capped survivor (conservative v1).

`market_risk_regime` is the §7 cap regime (极度防御 already yields no 建仓 from 4d-ii-c position_cap==0,
so its weekly limit 0 is a safety net). All inputs are VALUE-validated fail-closed: every row's
final_action must be frozen action vocab, ticker identity is canonical-unique and EMITTED UPPERCASE (a
non-canonical injected ticker is normalized, never echoed raw), each 建仓 must be a real 4d-ii-c sized
build (sizing.status=="sized"), a 观察 row must carry a frozen observe_reason_type and a non-观察 row must
carry none, per_ticker must canonically cover the 建仓 set, the account `portfolio_guard_status` must be a
frozen guard state and each build's `symbol_cooldown_status` a frozen cooldown status; the 同主题 cap counts
on the STRIPPED theme so whitespace variants cannot dodge it. Pure/offline; no provider/live/network;
no A-share crossing.
"""
from __future__ import annotations

import math

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_portfolio_guard import PORTFOLIO_GUARD_STATES, portfolio_guard_effects
from engine.us_short_weekend_decision import FINAL_ACTIONS, OBSERVE_REASONS

# §8 line 227 / §13.1 #4 forward-calibration priors (NOT frozen const): BASE per-regime weekly new-build
# count cap + the 同主题 weekly cap. theme_probe (§8) adds EXTRA seats beyond these in 4d-ii-g.
WEEKLY_BUILD_LIMIT = {"进攻": 3, "震荡": 2, "防御": 1, "极度防御": 0}
SAME_THEME_WEEK_CAP = 2

# §8 line 230 single-symbol re-entry cooldown statuses. Provenance: engine/us_short_symbol_cooldown.py
# symbol_cooldown_status() returns one of these four; the two whose `action` is "downgrade_to_observe"
# (entering_cooldown / in_cooldown) BLOCK a new build. Pinned to the engine by a triangulation test
# (test_us_short_weekend_basket.py) so this mapping cannot silently drift from the engine.
SYMBOL_COOLDOWN_STATUSES = ("none", "entering_cooldown", "in_cooldown", "reentry_allowed")
_SYMBOL_COOLDOWN_BLOCKS_NEW = ("entering_cooldown", "in_cooldown")

_BUILD = "建仓"
_OBSERVE = "观察"
_R_CAPACITY = "capacity_or_budget_deferred"   # §9 — pushed out of this week's BASE build capacity / budget
_R_RISK_COOLDOWN = "risk_cooldown"            # §9 — portfolio_guard cooldown (禁新建) / per-symbol cooldown block

# Single-source drift guard: the observe reasons this stage emits must stay in the frozen §9 vocab.
assert {_R_CAPACITY, _R_RISK_COOLDOWN} <= set(OBSERVE_REASONS), "emitted observe_reason_type drifted from §9 vocab"


class WeekendBasketError(Exception):
    """The injected sized_result / basket_context is malformed (fail-closed before resolution)."""


def _finite_number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _guard_blocks_new_entry(guard_status):
    """Account-level §8 new-build block from the frozen portfolio_guard effect table (line 238 cooldown→禁新建).
    Consumes the `block_new_entry` effect GENERICALLY (not hard-coded to a single state name) so a governance
    recalibration that flips the effect on another state is honored. A guard state outside the frozen vocab,
    or a malformed effect value, fails closed to BLOCK (an untrustworthy account risk state must not silently
    permit a new entry)."""
    if guard_status not in PORTFOLIO_GUARD_STATES:
        raise WeekendBasketError(
            f"portfolio_guard_status 非法（须 ∈ {sorted(PORTFOLIO_GUARD_STATES)}）: {guard_status!r}")
    gb = portfolio_guard_effects(guard_status).get("block_new_entry")
    return gb if isinstance(gb, bool) else True   # malformed governance effect → fail closed to block


def resolve_build_capacity(sized_result, *, basket_context):
    """4d-ii-e/f build-gate resolution. ① (4d-ii-f) downgrades a provisional 建仓 hit by an account
    portfolio_guard cooldown (禁新建) or a per-symbol re-entry cooldown to 观察(`risk_cooldown`), removed
    BEFORE ranking. ② (4d-ii-e) ranks the surviving 建仓 by core_score and applies the §8 BASE weekly
    build-limit + 同主题 cap; a 建仓 beyond BASE capacity → 观察(`capacity_or_budget_deferred`). Non-建仓 rows
    carry through unchanged (selection_rank None).

    sized_result = the `size_rows` output {regime: {... market_risk_regime ...}, rows: [...]}.
    basket_context = {"per_ticker": {<canonical ticker>: {"theme": <non-blank str>,
                                                          "symbol_cooldown_status": <frozen status>}},  # one per 建仓
                      "portfolio_guard_status": <frozen portfolio_guard state>}                          # account-level

    Returns {"regime": <carried>, "rows": [{...row, "selection_rank": int|None, [final_action/
    observe_reason_type overridden when blocked or capacity-deferred]}], "weekly_build_limit": int,
    "build_count": int (建仓 kept)}. Raises WeekendBasketError on a malformed sized_result / regime /
    basket_context, an unknown final_action, an observe_reason_type inconsistent with final_action (观察
    needs a frozen reason; a non-观察 row must carry none), a non-canonical / duplicate ticker, a 建仓 that
    is not a real sized build (missing finite core_score or sizing.status!="sized"), an invalid
    portfolio_guard_status / symbol_cooldown_status, or a per_ticker set that does not exactly (canonically)
    cover the 建仓 tickers."""
    if not (isinstance(sized_result, dict) and isinstance(sized_result.get("regime"), dict)
            and isinstance(sized_result.get("rows"), list)):
        raise WeekendBasketError("sized_result 须为含 regime(dict) + rows(list) 的 4d-ii-c 输出")
    regime = sized_result["regime"].get("market_risk_regime")
    if regime not in WEEKLY_BUILD_LIMIT:
        raise WeekendBasketError(f"market_risk_regime 非法（须 ∈ {sorted(WEEKLY_BUILD_LIMIT)}）: {regime!r}")
    weekly_limit = WEEKLY_BUILD_LIMIT[regime]
    if not (isinstance(basket_context, dict) and set(basket_context) == {"per_ticker", "portfolio_guard_status"}
            and isinstance(basket_context["per_ticker"], dict)):
        raise WeekendBasketError(
            "basket_context 顶层键须恰为 {'per_ticker','portfolio_guard_status'} 且 per_ticker 为 dict（closed-world）")
    per_ticker = basket_context["per_ticker"]
    guard_blocks_new = _guard_blocks_new_entry(basket_context["portfolio_guard_status"])

    # Pass 1 — VALUE-validate every row (frozen final_action vocab + canonical-unique ticker identity);
    # collect the 建仓 rows. Each 建仓 must be a real 4d-ii-c sized build (sizing.status == "sized" +
    # desired_model_shares ≥ 1) with a finite core_score; per_ticker must EXACTLY cover the canonical 建仓
    # set. A 建仓 blocked by the account portfolio_guard cooldown OR its own per-symbol cooldown is recorded
    # for a risk_cooldown downgrade and is NOT collected into the rankable set (a cooled-down symbol must not
    # consume a weekly / 同主题 slot).
    ct_by_index, seen = {}, set()
    builds, build_tickers, blocked_indices = [], set(), set()
    for i, row in enumerate(sized_result["rows"]):
        if not (isinstance(row, dict) and isinstance(row.get("final_action"), str)):
            raise WeekendBasketError(f"sized row 形状非法（须为 4d-ii-c 输出行）: {row!r}")
        if row["final_action"] not in FINAL_ACTIONS:
            raise WeekendBasketError(f"final_action 非法（不在冻结词表）: {row['final_action']!r}")
        orr = row.get("observe_reason_type")   # observe_reason_type ⟺ 观察 (§9 only 观察 carries a reason)
        if row["final_action"] == _OBSERVE:
            if orr not in OBSERVE_REASONS:
                raise WeekendBasketError(f"观察 行 observe_reason_type 须 ∈ 冻结词表: {orr!r}")
        elif orr is not None:
            raise WeekendBasketError(f"非观察行（{row['final_action']}）不得带 observe_reason_type: {orr!r}")
        ct = canonical_us_ticker(row.get("ticker"))
        if ct is None:
            raise WeekendBasketError(f"row ticker 非规范 US ticker（拒 A 股码/坏形）: {row.get('ticker')!r}")
        if ct in seen:
            raise WeekendBasketError(f"sized rows 含规范化后重复 ticker（一股一行）: {ct!r}")
        seen.add(ct)
        ct_by_index[i] = ct
        if row["final_action"] != _BUILD:
            continue
        score = row.get("score")
        cs = _finite_number(score.get("core_score")) if isinstance(score, dict) else None
        if cs is None:
            raise WeekendBasketError(f"建仓 行须有有限 core_score（供 selection_rank）: {ct!r}")
        sizing = row.get("sizing")
        dms = sizing.get("desired_model_shares") if isinstance(sizing, dict) else None
        if not (isinstance(sizing, dict) and sizing.get("status") == "sized"
                and isinstance(dms, int) and not isinstance(dms, bool) and dms >= 1):
            raise WeekendBasketError(
                f"建仓 行须为 4d-ii-c 真 sized build（sizing.status=='sized' + desired_model_shares≥1）: {ct!r}")
        tinfo = per_ticker.get(ct)
        if not (isinstance(tinfo, dict) and set(tinfo) == {"theme", "symbol_cooldown_status"}
                and isinstance(tinfo.get("theme"), str) and tinfo["theme"].strip()):
            raise WeekendBasketError(
                f"basket_context.per_ticker[{ct!r}] 须为 {{'theme': 非空 str, 'symbol_cooldown_status': 冻结状态}}: {tinfo!r}")
        scs = tinfo["symbol_cooldown_status"]
        if scs not in SYMBOL_COOLDOWN_STATUSES:
            raise WeekendBasketError(
                f"per_ticker[{ct!r}].symbol_cooldown_status 非法（须 ∈ {list(SYMBOL_COOLDOWN_STATUSES)}）: {scs!r}")
        build_tickers.add(ct)
        if guard_blocks_new or scs in _SYMBOL_COOLDOWN_BLOCKS_NEW:
            blocked_indices.add(i)            # §8 新建阻断 → risk_cooldown, removed before ranking
        else:
            builds.append((i, ct, cs, tinfo["theme"].strip()))   # STRIPPED theme — whitespace variants can't dodge the cap
    if set(per_ticker) != build_tickers:
        raise WeekendBasketError(
            f"basket_context.per_ticker 须恰覆盖 建仓 ticker 集（无缺/无陈旧、canonical 键）: per_ticker={sorted(per_ticker)} builds={sorted(build_tickers)}")

    # selection_rank by (core_score desc, ticker asc) over the NON-blocked builds; then §8 weekly-limit +
    # 同主题 cap (stripped theme; no promotion).
    ordered = sorted(builds, key=lambda b: (-b[2], b[1]))
    rank_by_index, capped_by_index = {}, {}
    theme_count = {}
    for rank, (idx, ct, cs, theme) in enumerate(ordered, start=1):
        rank_by_index[idx] = rank
        over_weekly = rank > weekly_limit
        over_theme = False
        if not over_weekly:   # 同主题 cap counts only among the weekly survivors
            theme_count[theme] = theme_count.get(theme, 0) + 1
            over_theme = theme_count[theme] > SAME_THEME_WEEK_CAP
        capped_by_index[idx] = over_weekly or over_theme

    # Emit — EVERY output row carries the canonical UPPERCASE ticker (never echoed raw). A blocked build is
    # 观察(risk_cooldown) with no rank (never ranked); a capacity-deferred build keeps its rank.
    out_rows, build_count = [], 0
    for i, row in enumerate(sized_result["rows"]):
        ct = ct_by_index[i]
        if row["final_action"] != _BUILD:
            out_rows.append({**row, "ticker": ct, "selection_rank": None})
            continue
        if i in blocked_indices:
            out_rows.append({**row, "ticker": ct, "selection_rank": None,
                             "final_action": _OBSERVE, "observe_reason_type": _R_RISK_COOLDOWN})
        elif capped_by_index[i]:
            out_rows.append({**row, "ticker": ct, "selection_rank": rank_by_index[i],
                             "final_action": _OBSERVE, "observe_reason_type": _R_CAPACITY})
        else:
            build_count += 1
            out_rows.append({**row, "ticker": ct, "selection_rank": rank_by_index[i]})
    return {"regime": sized_result["regime"], "rows": out_rows,
            "weekly_build_limit": weekly_limit, "build_count": build_count}
