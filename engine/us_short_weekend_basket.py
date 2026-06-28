# -*- coding: utf-8 -*-
"""US-short weekend-pipeline build-gate resolution — batch4 slice 4d-ii-e (§8 weekly build-limit + 同主题 cap)
+ slice 4d-ii-f (§8 portfolio_guard / symbol_cooldown 新建阻断) + slice 4d-ii-g (§8 强赛道试探名额 theme_probe
额外席).

Design authority: docs/us_short_system_design.md §8 (line 227 每周新增建仓上限 + 同主题上限; line 228-231
强赛道试探名额 theme_probe + 防御档入场; line 230/238 symbol_cooldown / portfolio_guard new-entry block) / §9
(selection_rank, observe_reason_type) / §18.2 batch4.

The cross-row build-gate stage after 4d-ii-c sizing. For every PROVISIONAL 建仓 row it, in order:

  ① (4d-ii-f) NEW-BUILD BLOCKING: an account-level portfolio_guard cooldown (禁新建, the const-pinned
     `block_new_entry` effect — consumed generically from the frozen effect table, NOT hard-coded to one
     state) OR a per-symbol re-entry cooldown (symbol_cooldown_status ∈ {entering_cooldown, in_cooldown})
     downgrades that 建仓 to 观察(`risk_cooldown`) and removes it BEFORE ranking — a cooled-down symbol must
     never consume a weekly / 同主题 slot.
  ② (4d-ii-e) RANK + BASE CAPACITY: ranks the surviving 建仓 by selection strength (core_score) and applies
     the §8 BASE per-regime weekly new-build limit (进攻3 / 震荡2 / 防御1 / 极度防御0) + the 同主题 weekly cap
     (≤2). A 建仓 pushed out of this week's BASE capacity → 观察(`capacity_or_budget_deferred`) (§9).
  ③ (4d-ii-g) THEME_PROBE EXTRA SEATS: the §8 强赛道试探名额 — an EXTRA build allowance BEYOND the base
     regime limit for a market-confirmed strong theme (§4.3/§7). Among the capacity-deferred builds (in
     rank order) the eligible ones are PROMOTED back to 建仓 up to the §8 #27 seat budget
     `theme_probe_seats(regime, theme_opportunity_state)` (防御≤1 / 进攻+极强≤2 / 极度防御0), still under the
     同主题 cap. Eligibility reuses `theme_probe_decision` (lifecycle allows + high_confidence + coverage
     non-restricted + the hard-zeros, which are already cleared for a survivor). A promoted probe carries the
     §8 `theme_probe_min_size` risk tag + its 防御 entry-mode constraint, and its size is FORCED to the
     minimum executable (`MIN_EXECUTABLE_SHARES`) — the pre-probe 4d-ii-c risk size kept as a
     `pre_probe_risk_shares` trace — so a risk-throttled probe can never go out as a normal-sized build
     (§8 line 230 强制 = 最小可执行仓, 绕过常规风险预算放大; governance `forced_min_executable_size`).

Scope (v1): NOT here — the §8 最小仓成本地板 cost floor (line 232 / `engine/us_short_cost_floor.py`), which
downgrades a probe whose expected profit-to-TP1 ≤ round-trip cost × safety multiple to
观察(`cost_inefficient_min_size`), is slice 4d-ii-h WIRING (it needs the commission / slippage / spread
execution-cost input contract — `apply_cost_floor` is not yet wired into any pipeline stage; the row's
`take_profit_exit_price` is available, the cost components are not). Cash allocation (allocate_cash) + §9
action_rank are also later. The portfolio_guard GRADED modulations (caution → reduce_position_size /
reduce_weekly_new_count, recovery → only_few_high_confidence_new) are a separate portfolio_guard-effects
concern — this slice consumes ONLY the cooldown `block_new_entry` (禁新建) effect. No base-build promotion: a
build ranked beyond the weekly limit is never promoted into a slot freed by a 同主题-capped survivor unless
it earns a theme_probe seat (conservative v1).

`market_risk_regime` is the §7 cap regime (极度防御 already yields no 建仓 from 4d-ii-c position_cap==0, so
its weekly limit 0 + its 0 probe seats are a safety net). All inputs are VALUE-validated fail-closed: every
row's final_action must be frozen action vocab, ticker identity is canonical-unique and EMITTED UPPERCASE (a
non-canonical injected ticker is normalized, never echoed raw), each 建仓 must be a real 4d-ii-c sized build
(sizing.status=="sized"), a 观察 row must carry a frozen observe_reason_type and a non-观察 row must carry
none, per_ticker must canonically cover the 建仓 set, the account `portfolio_guard_status` must be a frozen
guard state, each build's `symbol_cooldown_status` a frozen cooldown status, the account
`theme_opportunity_state` a frozen theme-opportunity state, and each build's `theme_probe` inputs a
closed-world dict (the value semantics are fail-closed by `theme_probe_decision` — a malformed / low-confidence
input simply yields no probe); the 同主题 cap counts on the STRIPPED theme so whitespace variants cannot dodge
it. Pure/offline; no provider/live/network; no A-share crossing.
"""
from __future__ import annotations

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_portfolio_guard import PORTFOLIO_GUARD_STATES, portfolio_guard_effects
from engine.us_short_position_sizing import MIN_EXECUTABLE_SHARES
from engine.us_short_theme_probe import THEME_OPPORTUNITY_STATES, theme_probe_decision, theme_probe_seats
from engine.us_short_weekend_decision import OBSERVE_REASONS, action_reason_error

# §8 line 227 / §13.1 #4 forward-calibration priors (NOT frozen const): BASE per-regime weekly new-build
# count cap + the 同主题 weekly cap. theme_probe (§8 line 229 / §13.1 #27) adds EXTRA seats beyond these.
WEEKLY_BUILD_LIMIT = {"进攻": 3, "震荡": 2, "防御": 1, "极度防御": 0}
SAME_THEME_WEEK_CAP = 2

# §8 line 230 single-symbol re-entry cooldown statuses. Provenance: engine/us_short_symbol_cooldown.py
# symbol_cooldown_status() returns one of these four; the two whose `action` is "downgrade_to_observe"
# (entering_cooldown / in_cooldown) BLOCK a new build. Pinned to the engine by a triangulation test
# (test_us_short_weekend_basket.py) so this mapping cannot silently drift from the engine.
SYMBOL_COOLDOWN_STATUSES = ("none", "entering_cooldown", "in_cooldown", "reentry_allowed")
_SYMBOL_COOLDOWN_BLOCKS_NEW = ("entering_cooldown", "in_cooldown")

# §8 line 230 per-build theme_probe eligibility inputs (the value semantics are fail-closed inside
# theme_probe_decision; this stage only enforces the closed-world SHAPE).
_THEME_PROBE_KEYS = frozenset(
    {"theme_lifecycle_state", "high_confidence", "coverage_status", "no_gap_week", "entry_in_band"})

_BUILD = "建仓"
_OBSERVE = "观察"
_R_CAPACITY = "capacity_or_budget_deferred"   # §9 — pushed out of this week's BASE build capacity / budget
_R_RISK_COOLDOWN = "risk_cooldown"            # §9 — portfolio_guard cooldown (禁新建) / per-symbol cooldown block

# Single-source drift guard: the observe reasons this stage emits must stay in the frozen §9 vocab.
assert {_R_CAPACITY, _R_RISK_COOLDOWN} <= set(OBSERVE_REASONS), "emitted observe_reason_type drifted from §9 vocab"


class WeekendBasketError(Exception):
    """The injected sized_result / basket_context is malformed (fail-closed before resolution)."""


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


def _validate_theme_probe_inputs(tinfo, ct):
    """Closed-world SHAPE gate for a build's `theme_probe` eligibility inputs. The VALUE semantics
    (high_confidence is True, lifecycle allows, coverage non-restricted) are fail-closed inside
    `theme_probe_decision` — a low-confidence / unknown-lifecycle / restricted-coverage build simply yields no
    probe — so this only requires the closed-world key set to be present (a missing input is a malformed
    contract)."""
    tp = tinfo.get("theme_probe")
    if not (isinstance(tp, dict) and set(tp) == _THEME_PROBE_KEYS):
        raise WeekendBasketError(
            f"per_ticker[{ct!r}].theme_probe 须为 closed-world {{{sorted(_THEME_PROBE_KEYS)}}}: {tp!r}")
    return tp


def _promote_theme_probes(capacity_deferred, *, regime, theme_opportunity_state, per_ticker, built_theme_count):
    """§8 line 228-231 强赛道试探名额. Among the capacity-deferred builds (already in core_score rank order)
    promote the theme_probe-eligible ones back to 建仓 up to the §8 #27 seat budget
    `theme_probe_seats(regime, theme_opportunity_state)`, still respecting the 同主题 cap (a probe counts toward
    its theme like a base build). The hard-zeros (极度防御 / symbol cooldown / portfolio_guard cooldown /
    hard_veto) are already cleared for a survivor — a blocked build was removed in stage ① and a hard-vetoed
    candidate never became 建仓 in 4d-ii-b — so they are passed explicit False. Returns {idx: {risk_tag,
    entry_mode_constraint}} for the promoted builds (the caller forces each to min-executable size)."""
    total_seats = theme_probe_seats(regime, theme_opportunity_state)
    promoted = {}
    if total_seats <= 0:
        return promoted
    granted = 0
    for idx, ct, theme in capacity_deferred:
        if granted >= total_seats:
            break
        if built_theme_count.get(theme, 0) >= SAME_THEME_WEEK_CAP:
            continue                                   # 同主题 cap (a probe counts toward its theme)
        tp = per_ticker[ct]["theme_probe"]
        decision = theme_probe_decision(
            regime, theme_opportunity_state,
            theme_lifecycle_state=tp["theme_lifecycle_state"], high_confidence=tp["high_confidence"],
            coverage_status=tp["coverage_status"], in_symbol_cooldown=False,
            in_portfolio_guard_cooldown=False, hard_veto=False,
            no_gap_week=tp["no_gap_week"], entry_in_band=tp["entry_in_band"])
        if decision["probe_allowed"]:
            promoted[idx] = {"risk_tag": decision["risk_tag"],
                             "entry_mode_constraint": decision["entry_mode_constraint"]}
            granted += 1
            built_theme_count[theme] = built_theme_count.get(theme, 0) + 1
    return promoted


def resolve_build_capacity(sized_result, *, basket_context):
    """4d-ii-e/f/g build-gate resolution. ① (4d-ii-f) downgrades a provisional 建仓 hit by an account
    portfolio_guard cooldown (禁新建) or a per-symbol re-entry cooldown to 观察(`risk_cooldown`), removed
    BEFORE ranking. ② (4d-ii-e) ranks the surviving 建仓 by core_score and applies the §8 BASE weekly
    build-limit + 同主题 cap; a 建仓 beyond BASE capacity → 观察(`capacity_or_budget_deferred`). ③ (4d-ii-g)
    promotes the theme_probe-eligible capacity-deferred builds back to 建仓 up to the §8 #27 strong-theme seat
    budget (still under the 同主题 cap), tagged `theme_probe_min_size` + an entry-mode constraint, with size
    FORCED to the minimum executable (`MIN_EXECUTABLE_SHARES`, pre-probe risk size kept as
    `pre_probe_risk_shares`). Non-建仓 rows carry through unchanged (selection_rank None).

    sized_result = the `size_rows` output {regime: {... market_risk_regime ...}, rows: [...]}.
    basket_context = {"per_ticker": {<canonical ticker>: {"theme": <non-blank str>,
                                                          "symbol_cooldown_status": <frozen status>,
                                                          "theme_probe": {"theme_lifecycle_state": str|None,
                                                              "high_confidence": bool, "coverage_status": str,
                                                              "no_gap_week": bool, "entry_in_band": bool}}},  # one per 建仓
                      "portfolio_guard_status": <frozen portfolio_guard state>,                                # account-level
                      "theme_opportunity_state": <frozen theme-opportunity state>}                             # account-level

    Returns {"regime": <carried>, "rows": [{...row, "selection_rank": int|None, ["theme_probe": {...}],
    [final_action/observe_reason_type overridden]}], "weekly_build_limit": int, "build_count": int (建仓
    kept, incl. promoted probes)}. Raises WeekendBasketError on a malformed sized_result / regime /
    basket_context, an unknown final_action, an observe_reason_type inconsistent with final_action, a
    non-canonical / duplicate ticker, a 建仓 that is not a real sized build, an invalid portfolio_guard_status
    / symbol_cooldown_status / theme_opportunity_state, a malformed theme_probe input shape, or a per_ticker
    set that does not exactly (canonically) cover the 建仓 tickers."""
    if not (isinstance(sized_result, dict) and isinstance(sized_result.get("regime"), dict)
            and isinstance(sized_result.get("rows"), list)):
        raise WeekendBasketError("sized_result 须为含 regime(dict) + rows(list) 的 4d-ii-c 输出")
    regime = sized_result["regime"].get("market_risk_regime")
    if regime not in WEEKLY_BUILD_LIMIT:
        raise WeekendBasketError(f"market_risk_regime 非法（须 ∈ {sorted(WEEKLY_BUILD_LIMIT)}）: {regime!r}")
    weekly_limit = WEEKLY_BUILD_LIMIT[regime]
    if not (isinstance(basket_context, dict)
            and set(basket_context) == {"per_ticker", "portfolio_guard_status", "theme_opportunity_state"}
            and isinstance(basket_context["per_ticker"], dict)):
        raise WeekendBasketError(
            "basket_context 顶层键须恰为 {'per_ticker','portfolio_guard_status','theme_opportunity_state'} 且 per_ticker 为 dict（closed-world）")
    per_ticker = basket_context["per_ticker"]
    guard_blocks_new = _guard_blocks_new_entry(basket_context["portfolio_guard_status"])
    theme_opportunity_state = basket_context["theme_opportunity_state"]
    if theme_opportunity_state not in THEME_OPPORTUNITY_STATES:
        raise WeekendBasketError(
            f"theme_opportunity_state 非法（须 ∈ {list(THEME_OPPORTUNITY_STATES)}）: {theme_opportunity_state!r}")

    # Pass 1 — VALUE-validate every row (frozen final_action vocab + canonical-unique ticker identity);
    # collect the 建仓 rows. Each 建仓 must be a real 4d-ii-c sized build with a finite core_score; per_ticker
    # must EXACTLY cover the canonical 建仓 set. A 建仓 blocked by the account portfolio_guard cooldown OR its
    # own per-symbol cooldown is recorded for a risk_cooldown downgrade and is NOT collected into the rankable
    # set (a cooled-down symbol must not consume a weekly / 同主题 slot).
    ct_by_index, seen = {}, set()
    builds, build_tickers, blocked_indices = [], set(), set()
    for i, row in enumerate(sized_result["rows"]):
        if not (isinstance(row, dict) and isinstance(row.get("final_action"), str)):
            raise WeekendBasketError(f"sized row 形状非法（须为 4d-ii-c 输出行）: {row!r}")
        err = action_reason_error(row["final_action"], row.get("observe_reason_type"))   # §9 single-source (词表 + 观察⟺reason)
        if err:
            raise WeekendBasketError(err)
        ct = canonical_us_ticker(row.get("ticker"))
        if ct is None:
            raise WeekendBasketError(f"row ticker 非规范 US ticker（拒 A 股码/坏形）: {row.get('ticker')!r}")
        if ct in seen:
            raise WeekendBasketError(f"sized rows 含规范化后重复 ticker（一股一行）: {ct!r}")
        seen.add(ct)
        ct_by_index[i] = ct
        if row["final_action"] != _BUILD:
            continue
        # rank by the PRESERVED Top15 selection_rank (slice 2a/2b: the canonical selection identity threaded from
        # _select_top15), NOT a re-derived analysis core_score — so build/cash/action priority can never silently
        # reverse the selection (R-USSHORT-BATCH4-SELECTION-TRACE-AND-RECALL-CLOSURE-GAP).
        sel_rec = row.get("selection_record")
        sr = sel_rec.get("selection_rank") if isinstance(sel_rec, dict) else None
        if not (isinstance(sr, int) and not isinstance(sr, bool) and sr >= 1):
            raise WeekendBasketError(
                f"建仓 行须有 selection_record.selection_rank 正 int（preserved Top15 rank，供排序、不再重算 core_score）: {ct!r} → {sr!r}")
        sizing = row.get("sizing")
        dms = sizing.get("desired_model_shares") if isinstance(sizing, dict) else None
        if not (isinstance(sizing, dict) and sizing.get("status") == "sized"
                and isinstance(dms, int) and not isinstance(dms, bool) and dms >= 1):
            raise WeekendBasketError(
                f"建仓 行须为 4d-ii-c 真 sized build（sizing.status=='sized' + desired_model_shares≥1）: {ct!r}")
        tinfo = per_ticker.get(ct)
        if not (isinstance(tinfo, dict) and set(tinfo) == {"theme", "symbol_cooldown_status", "theme_probe"}
                and isinstance(tinfo.get("theme"), str) and tinfo["theme"].strip()):
            raise WeekendBasketError(
                f"basket_context.per_ticker[{ct!r}] 须为 {{'theme': 非空 str, 'symbol_cooldown_status', 'theme_probe'}}: {tinfo!r}")
        scs = tinfo["symbol_cooldown_status"]
        if scs not in SYMBOL_COOLDOWN_STATUSES:
            raise WeekendBasketError(
                f"per_ticker[{ct!r}].symbol_cooldown_status 非法（须 ∈ {list(SYMBOL_COOLDOWN_STATUSES)}）: {scs!r}")
        _validate_theme_probe_inputs(tinfo, ct)
        build_tickers.add(ct)
        if guard_blocks_new or scs in _SYMBOL_COOLDOWN_BLOCKS_NEW:
            blocked_indices.add(i)            # §8 新建阻断 → risk_cooldown, removed before ranking
        else:
            builds.append((i, ct, sr, tinfo["theme"].strip()))   # sr = preserved Top15 rank; STRIPPED theme — whitespace variants can't dodge the cap
    if set(per_ticker) != build_tickers:
        raise WeekendBasketError(
            f"basket_context.per_ticker 须恰覆盖 建仓 ticker 集（无缺/无陈旧、canonical 键）: per_ticker={sorted(per_ticker)} builds={sorted(build_tickers)}")

    # order the NON-blocked builds by their PRESERVED Top15 selection_rank (asc, ticker tiebreak); then apply the
    # §8 BASE weekly-limit + 同主题 cap (stripped theme) over that order. The EMITTED selection_rank is the
    # preserved Top15 rank (多强, may be sparse when a Top15 name was downgraded upstream); the weekly limit uses
    # the SURVIVOR POSITION. built_theme_count tracks the BUILT (non-deferred) builds per theme; the
    # capacity-deferred builds (in preserved-rank order) are the theme_probe promotion candidates for stage ③.
    ordered = sorted(builds, key=lambda b: (b[2], b[1]))
    rank_by_index, capped_by_index = {}, {}
    theme_count, built_theme_count, capacity_deferred = {}, {}, []
    for position, (idx, ct, sr, theme) in enumerate(ordered, start=1):
        rank_by_index[idx] = sr
        over_weekly = position > weekly_limit
        over_theme = False
        if not over_weekly:   # 同主题 cap counts only among the weekly survivors
            theme_count[theme] = theme_count.get(theme, 0) + 1
            over_theme = theme_count[theme] > SAME_THEME_WEEK_CAP
        if over_weekly or over_theme:
            capped_by_index[idx] = True
            capacity_deferred.append((idx, ct, theme))
        else:
            capped_by_index[idx] = False
            built_theme_count[theme] = built_theme_count.get(theme, 0) + 1

    # ③ theme_probe extra seats — promote eligible capacity-deferred strong-theme builds back to 建仓.
    promoted = _promote_theme_probes(
        capacity_deferred, regime=regime, theme_opportunity_state=theme_opportunity_state,
        per_ticker=per_ticker, built_theme_count=built_theme_count)

    # Emit — EVERY output row carries the canonical UPPERCASE ticker (never echoed raw). A blocked build is
    # 观察(risk_cooldown) with no rank; a promoted probe is 建仓 + theme_probe metadata; a still-deferred build
    # is 观察(capacity_or_budget_deferred); both deferred classes keep their rank.
    out_rows, build_count = [], 0
    for i, row in enumerate(sized_result["rows"]):
        ct = ct_by_index[i]
        if row["final_action"] != _BUILD:
            out_rows.append({**row, "ticker": ct, "selection_rank": None})
            continue
        if i in blocked_indices:
            out_rows.append({**row, "ticker": ct, "selection_rank": None,
                             "final_action": _OBSERVE, "observe_reason_type": _R_RISK_COOLDOWN})
        elif i in promoted:
            build_count += 1
            # §8 强赛道试探：FORCE min-executable size (绕过风险预算放大 / forced_min_executable_size); a
            # risk-throttled probe must never go out as a normal-sized build. The 4d-ii-c risk size is kept
            # as a `pre_probe_risk_shares` trace.
            orig_sizing = row["sizing"]
            probe_sizing = {**orig_sizing, "desired_model_shares": MIN_EXECUTABLE_SHARES,
                            "reason": "theme_probe_forced_min",
                            "pre_probe_risk_shares": orig_sizing["desired_model_shares"]}
            out_rows.append({**row, "ticker": ct, "selection_rank": rank_by_index[i],
                             "sizing": probe_sizing, "theme_probe": promoted[i]})
        elif capped_by_index[i]:
            out_rows.append({**row, "ticker": ct, "selection_rank": rank_by_index[i],
                             "final_action": _OBSERVE, "observe_reason_type": _R_CAPACITY})
        else:
            build_count += 1
            out_rows.append({**row, "ticker": ct, "selection_rank": rank_by_index[i]})
    return {"regime": sized_result["regime"], "rows": out_rows,
            "weekly_build_limit": weekly_limit, "build_count": build_count}
