# -*- coding: utf-8 -*-
"""US-short weekend-pipeline build-count resolution — batch4 slice 4d-ii-e (§8 weekly build-limit + 同主题 cap).

Design authority: docs/us_short_system_design.md §8 (line 227 每周新增建仓上限 + 同主题上限) / §9
(selection_rank) / §18.2 batch4.

The cross-row stage after 4d-ii-c sizing. It ranks the surviving provisional 建仓 rows by selection
strength (core_score) and applies the §8 BASE per-regime weekly new-build limit (进攻3 / 震荡2 / 防御1 /
极度防御0) + the 同主题 weekly cap (≤2). A 建仓 pushed out of this week's capacity is downgraded to
观察 with `observe_reason_type = capacity_or_budget_deferred` (§9 — otherwise executable, just no room
this week — kept distinct from a cost/min-size or data/price observe so the §11.2 honesty split is honest).

Scope (v1, base only): the §8 强赛道试探名额 theme_probe EXTRA seats (engine/us_short_theme_probe.py),
which add seats BEYOND this base regime limit for strong/extreme themes (and would promote some
capacity-deferred builds), and the portfolio_guard / symbol_cooldown new-entry hard-zero blocking
(engine/us_short_portfolio_guard.py / us_short_symbol_cooldown.py — those route to 观察(risk_cooldown)),
are slice 4d-ii-f WIRING — NOT here. Cash allocation (allocate_cash) + §9 action_rank are also 4d-ii-f.
No promotion: a build ranked beyond the weekly limit is never promoted into a slot freed by a
同主题-capped survivor (conservative v1).

`market_risk_regime` is the §7 cap regime (极度防御 already yields no 建仓 from 4d-ii-c position_cap==0,
so its weekly limit 0 is a safety net). All inputs are VALUE-validated fail-closed: every row's
final_action must be frozen action vocab, ticker identity is canonical-unique and EMITTED UPPERCASE (a
non-canonical injected ticker is normalized, never echoed raw), each 建仓 must be a real 4d-ii-c sized
build (sizing.status=="sized"), a 观察 row must carry a frozen observe_reason_type and a non-观察 row must
carry none, and per_ticker must canonically cover the 建仓 set; the 同主题 cap counts
on the STRIPPED theme so whitespace variants cannot dodge it. Pure/offline; no provider/live/network;
no A-share crossing.
"""
from __future__ import annotations

import math

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_weekend_decision import FINAL_ACTIONS, OBSERVE_REASONS

# §8 line 227 / §13.1 #4 forward-calibration priors (NOT frozen const): BASE per-regime weekly new-build
# count cap + the 同主题 weekly cap. theme_probe (§8) adds EXTRA seats beyond these in 4d-ii-f.
WEEKLY_BUILD_LIMIT = {"进攻": 3, "震荡": 2, "防御": 1, "极度防御": 0}
SAME_THEME_WEEK_CAP = 2

_BUILD = "建仓"
_OBSERVE = "观察"
_R_CAPACITY = "capacity_or_budget_deferred"   # §9 — pushed out of this week's build capacity / budget


class WeekendBasketError(Exception):
    """The injected sized_result / basket_context is malformed (fail-closed before resolution)."""


def _finite_number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def resolve_build_capacity(sized_result, *, basket_context):
    """4d-ii-e build-count resolution. Ranks the 建仓 rows of the 4d-ii-c `size_rows` result by core_score
    and applies the §8 BASE weekly build-limit + 同主题 cap; a 建仓 beyond capacity → 观察
    (capacity_or_budget_deferred). Non-建仓 rows carry through unchanged (selection_rank None).

    sized_result = the `size_rows` output {regime: {... market_risk_regime ...}, rows: [...]}.
    basket_context = {"per_ticker": {<canonical ticker>: {"theme": <non-blank str>}}}  # one per 建仓 row
        (the 同主题 cap needs each build's theme identity; must EXACTLY cover the 建仓 ticker set).

    Returns {"regime": <carried>, "rows": [{...row, "selection_rank": int|None, [final_action/
    observe_reason_type overridden when capacity-deferred]}], "weekly_build_limit": int,
    "build_count": int (建仓 kept)}. Raises WeekendBasketError on a malformed sized_result / regime /
    basket_context, an unknown final_action, an observe_reason_type inconsistent with final_action (观察
    needs a frozen reason; a non-观察 row must carry none), a non-canonical / duplicate ticker, a 建仓 that
    is not a real sized build (missing finite core_score or sizing.status!="sized"), or a per_ticker set
    that does not exactly (canonically) cover the 建仓 tickers."""
    if not (isinstance(sized_result, dict) and isinstance(sized_result.get("regime"), dict)
            and isinstance(sized_result.get("rows"), list)):
        raise WeekendBasketError("sized_result 须为含 regime(dict) + rows(list) 的 4d-ii-c 输出")
    regime = sized_result["regime"].get("market_risk_regime")
    if regime not in WEEKLY_BUILD_LIMIT:
        raise WeekendBasketError(f"market_risk_regime 非法（须 ∈ {sorted(WEEKLY_BUILD_LIMIT)}）: {regime!r}")
    weekly_limit = WEEKLY_BUILD_LIMIT[regime]
    if not (isinstance(basket_context, dict) and set(basket_context) == {"per_ticker"}
            and isinstance(basket_context["per_ticker"], dict)):
        raise WeekendBasketError("basket_context 顶层键须恰为 {'per_ticker'} 且 per_ticker 为 dict（closed-world）")
    per_ticker = basket_context["per_ticker"]

    # Pass 1 — VALUE-validate every row (frozen final_action vocab + canonical-unique ticker identity);
    # collect the 建仓 rows (index, canonical ticker, core_score, STRIPPED theme). Each 建仓 must be a real
    # 4d-ii-c sized build (sizing.status == "sized" + desired_model_shares ≥ 1) with a finite core_score;
    # per_ticker must EXACTLY cover the canonical 建仓 set (canonical keys, no missing / stale).
    ct_by_index, seen = {}, set()
    builds, build_tickers = [], set()
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
        if not (isinstance(tinfo, dict) and set(tinfo) == {"theme"} and isinstance(tinfo.get("theme"), str)
                and tinfo["theme"].strip()):
            raise WeekendBasketError(
                f"basket_context.per_ticker[{ct!r}] 须为 {{'theme': 非空 str}}（建仓必须有主题）: {tinfo!r}")
        builds.append((i, ct, cs, tinfo["theme"].strip()))   # STRIPPED theme — whitespace variants can't dodge the cap
        build_tickers.add(ct)
    if set(per_ticker) != build_tickers:
        raise WeekendBasketError(
            f"basket_context.per_ticker 须恰覆盖 建仓 ticker 集（无缺/无陈旧、canonical 键）: per_ticker={sorted(per_ticker)} builds={sorted(build_tickers)}")

    # selection_rank by (core_score desc, ticker asc); then §8 weekly-limit + 同主题 cap (stripped theme; no promotion).
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

    # Emit — EVERY output row carries the canonical UPPERCASE ticker (never echoed raw).
    out_rows, build_count = [], 0
    for i, row in enumerate(sized_result["rows"]):
        ct = ct_by_index[i]
        if row["final_action"] != _BUILD:
            out_rows.append({**row, "ticker": ct, "selection_rank": None})
            continue
        if capped_by_index[i]:
            out_rows.append({**row, "ticker": ct, "selection_rank": rank_by_index[i],
                             "final_action": _OBSERVE, "observe_reason_type": _R_CAPACITY})
        else:
            build_count += 1
            out_rows.append({**row, "ticker": ct, "selection_rank": rank_by_index[i]})
    return {"regime": sized_result["regime"], "rows": out_rows,
            "weekly_build_limit": weekly_limit, "build_count": build_count}
