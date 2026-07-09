# -*- coding: utf-8 -*-
"""US-short weekend-pipeline per-row sizing — batch4 slice 4d-ii-c (§8 风险定仓 + 削减叠法).

Design authority: docs/us_short_system_design.md §8 (按风险定仓 + 削减叠法) / §9 (observe_reason_type)
/ §18.2 batch4.

The fourth batch-4 stage: consumes the 4d-ii-b decision result ({regime, rows}) and sizes each
PROVISIONAL 建仓 via the §8 削减叠法 (reusing the `us_short_position_sizing` engine — no new sizing
math here):

    ① base = risk_based_base_shares(short_bucket, valid_entry_high, stop_clear_price)
    ② × regime multiplier (= the §7 position_cap carried in decision_result.regime)
    ③ × harshest single risk discount (the injected per-row discount_mults — §8 取最狠的一个、不连乘)
    ④ min(single-ticker cap = ⌊bucket × SINGLE_TICKER_CAP_FRAC ÷ entry⌋, injected liquidity cap)
    ⑤ < min executable → 降观察 (建仓 → 观察; 极度防御 position_cap==0 → capacity_or_budget_deferred, else cost_inefficient_min_size)

This is the PER-ROW sizing only. The CROSS-ROW §8 steps — the weekly new-build limit (进攻3/震荡2/
防御1/极度防御0) + 同主题 cap + theme_probe slots + the theme_probe min-size cost floor (§8 line 232)
+ the global cash allocation — are slice 4d-ii-d (they need the whole basket). Non-建仓 rows (观察 /
持有 / 清仓-* / 否决) carry through unchanged with `sizing=None` (holdings keep their account_state size;
this stage sizes only NEW builds). 加仓 is not produced (§6 dual-engine deferred, see 4d-ii-b).

The injected decision-result + sizing_context are VALUE-validated fail-closed (not just shape): a row's
`final_action` must be frozen action vocab, a 建仓 must be a candidate-context + `executable is True` row
with valid levels, ticker identity is canonical-unique across rows AND every output row EMITS the
canonical UPPERCASE ticker (never echoed raw — so one stock can't bypass the single-ticker cap by
appearing twice or in two spellings), `per_ticker` must EXACTLY cover the 建仓 set (no missing / stale
key), and a malformed bucket / discount / cap must not silently zero or inflate a position. Pure/offline;
no provider/live/network; no A-share crossing.
"""
from __future__ import annotations

import math

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_overextension import OVEREXTENSION_STATES
from engine.us_short_position_sizing import MIN_EXECUTABLE_SHARES, reduction_stack, risk_based_base_shares
from engine.us_short_weekend_decision import action_reason_error

# §8 line 226 / §13.1 #4 forward-calibration prior (NOT a frozen const): 单票上限 10% of the short bucket.
SINGLE_TICKER_CAP_FRAC = 0.10
# §13.1 #4/#36 forward prior (NOT frozen const): §4.3 overextension `warning` → reduce size — a discount that folds
# into the §8 削减叠法 step ③ (harshest single discount), NOT a new penalty stage.
WARNING_REDUCE_MULT = 0.5

_BUILD = "建仓"
_OBSERVE = "观察"
_R_COST_INEFFICIENT = "cost_inefficient_min_size"      # §8 line 232 / §9 — genuine under-min / cost-floor observe
_R_CAPACITY_DEFERRED = "capacity_or_budget_deferred"   # §9 — pushed out by a capacity/budget cap (here 极度防御 position_cap==0)


class WeekendSizingError(Exception):
    """The injected sizing_context / decision_result is malformed (fail-closed before sizing)."""


def _finite_number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _nonneg_int(x):
    return x if (isinstance(x, int) and not isinstance(x, bool) and x >= 0) else None


def _validate_sizing_context(sizing_context):
    """Fail-closed shape + value gate for the injected sizing_context (closed-world top-level)."""
    if not isinstance(sizing_context, dict) or set(sizing_context) != {"short_bucket_dollars", "per_ticker"}:
        raise WeekendSizingError(
            "sizing_context 顶层键须恰为 {'short_bucket_dollars','per_ticker'}（closed-world）")
    bucket = _finite_number(sizing_context["short_bucket_dollars"])
    if bucket is None or bucket <= 0.0:
        raise WeekendSizingError(f"short_bucket_dollars 须为正有限数: {sizing_context['short_bucket_dollars']!r}")
    if not isinstance(sizing_context["per_ticker"], dict):
        raise WeekendSizingError("sizing_context.per_ticker 须为 dict")
    return bucket


def _ticker_sizing_inputs(per_ticker, ticker):
    """The validated (discount_mults, liquidity_cap_shares) for a 建仓 ticker — fail-closed on a missing
    entry / malformed discount list / malformed liquidity cap (a build must NOT default to un-discounted
    or uncapped sizing)."""
    inp = per_ticker.get(ticker)
    if not isinstance(inp, dict) or set(inp) != {"discount_mults", "liquidity_cap_shares"}:
        raise WeekendSizingError(
            f"per_ticker[{ticker!r}] 须为 {{'discount_mults','liquidity_cap_shares'}}（建仓必须有 sizing 输入）: {inp!r}")
    dm = inp["discount_mults"]
    if not isinstance(dm, list) or any(_finite_number(m) is None or not (0.0 <= float(m) <= 1.0) for m in dm):
        raise WeekendSizingError(f"per_ticker[{ticker!r}].discount_mults 须为 [0,1] 有限数 list: {dm!r}")
    liq = _nonneg_int(inp["liquidity_cap_shares"])
    if liq is None:
        raise WeekendSizingError(
            f"per_ticker[{ticker!r}].liquidity_cap_shares 须为非负 int: {inp['liquidity_cap_shares']!r}")
    return [float(m) for m in dm], liq


def _size_build(row, *, bucket, position_cap, ticker, per_ticker):
    """§8 削减叠法 for one VALIDATED PROVISIONAL 建仓 row (canonical `ticker`). Returns (final_action,
    observe_reason_type, sizing) — a sized build keeps 建仓; a below-min result downgrades to 观察, with
    reason capacity_or_budget_deferred when a regime/position cap zeroed it (极度防御 position_cap==0)
    else cost_inefficient_min_size (a genuine under-min / cost-floor case)."""
    af = row["price"]["action_fields"]
    entry = _finite_number(af.get("valid_entry_high"))
    stop = _finite_number(af.get("stop_clear_price"))
    if entry is None or stop is None or not (entry > stop > 0.0):
        raise WeekendSizingError(
            f"建仓 行价位非法（须 valid_entry_high>stop_clear_price>0）: {ticker!r} entry={af.get('valid_entry_high')!r} stop={af.get('stop_clear_price')!r}")
    discount_mults, liquidity_cap = _ticker_sizing_inputs(per_ticker, ticker)
    # §4.3 overextension `warning` → reduce size: fold WARNING_REDUCE_MULT into the §8 削减叠法 step ③ (`harshest`
    # single discount — it weighs the injected discounts too, so co-occurring risks are not double-multiplied). The
    # tier rode onto the row via analysis (cut 2c); a PRESENT-but-malformed overextension fails closed (缺数据≠安全,
    # mirrors machine_record); a chasing tier carries NO reduce_size flag (its effect is the SELECTION strip, not sizing).
    ox = row.get("overextension")
    if ox is not None and not (isinstance(ox, dict) and ox.get("overextension_state") in OVEREXTENSION_STATES
                               and isinstance(ox.get("execution_flags"), dict)):
        raise WeekendSizingError(
            f"overextension 非法（须含合法 overextension_state ∈ {list(OVEREXTENSION_STATES)} + dict execution_flags 或缺省）: {ox!r}")
    if isinstance(ox, dict) and ox["execution_flags"].get("reduce_size") is True:
        discount_mults = discount_mults + [WARNING_REDUCE_MULT]

    base = risk_based_base_shares(bucket, entry, stop)
    single_ticker_cap = int(math.floor(bucket * SINGLE_TICKER_CAP_FRAC / entry))
    sized = reduction_stack(base, position_cap, discount_mults, [single_ticker_cap, liquidity_cap],
                            min_executable=MIN_EXECUTABLE_SHARES)
    sizing = {
        "base_shares": base, "regime_multiplier": position_cap,
        "single_ticker_cap_shares": single_ticker_cap, "liquidity_cap_shares": liquidity_cap,
        "desired_model_shares": sized["shares"], "status": sized["status"], "reason": sized["reason"],
    }
    if sized["status"] == "sized":
        return _BUILD, None, sizing
    # §8 ⑤ < 最小可执行 → 降观察. A regime/position-cap zero (极度防御仓位上限) is a CAPACITY/BUDGET deferral
    # (§9 capacity_or_budget_deferred — "good enough, no room this week"), kept distinct from a genuine
    # under-min / cost-floor case (cost_inefficient_min_size) so the §11.2 honesty split is not polluted.
    if position_cap == 0.0:
        return _OBSERVE, _R_CAPACITY_DEFERRED, sizing
    return _OBSERVE, _R_COST_INEFFICIENT, sizing


def size_rows(decision_result, *, sizing_context):
    """4d-ii-c sizing stage. Sizes every PROVISIONAL 建仓 row in the 4d-ii-b decision result via the §8
    削减叠法 (per-row only: regime multiplier + harshest injected discount + single-ticker / liquidity
    caps; below-min → 观察). Non-建仓 rows carry through unchanged with `sizing=None`.

    decision_result = the `decide_actions` output {regime: {... position_cap ...}, rows: [...]}.
    sizing_context = {"short_bucket_dollars": float>0,
                      "per_ticker": {<canonical ticker>: {"discount_mults": [0..1, ...],
                                                          "liquidity_cap_shares": int>=0}}}  # one per 建仓

    Returns {"regime": <carried>, "rows": [{...row, "sizing": {...}|None, "final_action", "observe_reason_type"}]}.
    Raises WeekendSizingError on a malformed decision_result / sizing_context, an unknown final_action, a
    non-candidate / non-executable / bad-level 建仓, a duplicate canonical ticker, or a per_ticker set that
    does not exactly cover the 建仓 tickers. The cross-row build-limit / 同主题 cap / theme_probe cost floor
    / cash allocation + §9 action_rank are slice 4d-ii-d (NOT here)."""
    if not (isinstance(decision_result, dict) and isinstance(decision_result.get("regime"), dict)
            and isinstance(decision_result.get("rows"), list)):
        raise WeekendSizingError("decision_result 须为含 regime(dict) + rows(list) 的 4d-ii-b 输出")
    position_cap = _finite_number(decision_result["regime"].get("position_cap"))
    if position_cap is None or not (0.0 <= position_cap <= 1.0):
        raise WeekendSizingError(f"regime.position_cap 须为 [0,1] 有限数: {decision_result['regime'].get('position_cap')!r}")
    bucket = _validate_sizing_context(sizing_context)
    per_ticker = sizing_context["per_ticker"]

    # Pass 1 — validate the 4d-ii-b decision-row VALUE contract (not just shape) + canonical unique
    # identity; collect the 建仓 ticker set. A bad action vocab, a non-candidate / non-executable 建仓,
    # a non-canonical ticker, or a duplicate identity (which would let one stock bypass the per-ticker
    # cap by appearing twice) fails closed before any sizing.
    seen = set()
    build_tickers = set()
    for row in decision_result["rows"]:
        if not (isinstance(row, dict) and isinstance(row.get("final_action"), str)
                and isinstance(row.get("price"), dict) and isinstance(row["price"].get("action_fields"), dict)):
            raise WeekendSizingError(f"decision row 形状非法（须为 4d-ii-b 输出行）: {row!r}")
        err = action_reason_error(row["final_action"], row.get("observe_reason_type"))   # §9 single-source value-validation (含 final_action 词表 + 观察⟺reason 一致)
        if err:
            raise WeekendSizingError(err)
        ct = canonical_us_ticker(row.get("ticker"))
        if ct is None:
            raise WeekendSizingError(f"row ticker 非规范 US ticker（拒 A 股码/坏形）: {row.get('ticker')!r}")
        if ct in seen:
            raise WeekendSizingError(f"decision rows 含规范化后重复 ticker（一股一行、防绕过单票 cap）: {ct!r}")
        seen.add(ct)
        if row["final_action"] == _BUILD:
            if row.get("row_context") != "candidate":
                raise WeekendSizingError(f"建仓 行 row_context 须为 candidate: {ct!r} → {row.get('row_context')!r}")
            if row["price"].get("executable") is not True:
                raise WeekendSizingError(f"建仓 行 price.executable 须为 True（不可执行不得定仓）: {ct!r}")
            build_tickers.add(ct)
    if set(per_ticker) != build_tickers:
        raise WeekendSizingError(
            f"sizing_context.per_ticker 须恰覆盖 建仓 ticker 集（无缺/无陈旧）: per_ticker={sorted(per_ticker)} builds={sorted(build_tickers)}")

    # Pass 2 — size each 建仓 (per-row); non-建仓 rows carry through unsized. EVERY output row EMITS the
    # canonical UPPERCASE ticker (one identity on every surface — a non-canonical injected ticker like
    # "aapl" / " AAPL " is normalized to "AAPL", never echoed raw; §3 / 4c / 4d identity policy).
    sized_rows = []
    for row in decision_result["rows"]:
        ct = canonical_us_ticker(row["ticker"])   # already validated non-None + unique in pass 1
        if row["final_action"] != _BUILD:
            sized_rows.append({**row, "ticker": ct, "sizing": None})
            continue
        final_action, observe_reason, sizing = _size_build(
            row, bucket=bucket, position_cap=position_cap, ticker=ct, per_ticker=per_ticker)
        sized_rows.append({**row, "ticker": ct, "final_action": final_action,
                           "observe_reason_type": observe_reason, "sizing": sizing})
    return {"regime": decision_result["regime"], "rows": sized_rows}
