"""Full-market limit-up / limit-down breadth from unadjusted ``daily`` + ``stk_limit``.

Pure logic: takes DataFrames, returns a dict.  No fetch, no file write, no wiring.

**Why this module exists separately.** The per-stock limit-price caliber was already
worked out and validated inside `engine/a_short_regime_features.py`, but that module
is labelled comparison-only and production may not import it.  Copying the rule into
a second place would have produced two calibers that drift.  So the shared rule lives
here, and BOTH the comparison features and the production producer import it -- parity
is by construction rather than by a test that has to keep noticing.

**Caliber.** Every stock is judged against *its own* ``up_limit`` / ``down_limit`` row,
so ±10% main board, ±20% ChiNext/STAR, ST ±5% and the BSE ±30% band are all respected
without a single hard-coded percentage.  A hard-coded band is exactly the bug this
shape prevents.

**Universe.** Full market on purpose (main board + ChiNext + STAR + BSE A-shares), not
the tradable main-board subset: these numbers feed a market-mood read, and v14.2's
thresholds (consecutive height >= 5, limit-downs < 50) are calibrated to full-market
magnitudes.  Counting only the main board would make the same thresholds systematically
loose.  B-shares and codes whose board cannot be identified are excluded.

**Fail-closed.** If any stock that actually traded on the day lacks a usable price or a
usable limit row, the whole day's facts are ``unavailable`` -- never zero.  A zero is a
claim that nothing hit the limit; missing data is not that claim.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


#: `close >= up_limit * LIMIT_TOL` counts as a closing limit-up.  Providers round the
#: limit price to two decimals, so an exact equality test drops real limit-ups.
LIMIT_TOL = 0.999

#: `market` values from `stock_basic` that are A-share boards we count.  Anything else
#: -- B-shares, CDRs, unrecognised strings -- is excluded rather than guessed at.
FULL_MARKET_BOARDS = ("主板", "创业板", "科创板", "北交所")

#: INCLUSION-based A-share code shapes, per exchange.  An exclusion-based test ("not
#: ChiNext, not STAR, so main board") is what lets B-shares 900*.SH / 200*.SZ through --
#: this repository already documents that leak in
#: `engine/data/a_share_board_scope.py`.  Relying on the provider's `market` string
#: alone would leave the same hole one mislabelled row wide, so the code shape is a
#: second, independent gate rather than a restatement of the first.
A_SHARE_CODE_PREFIXES = {
    "SH": ("600", "601", "603", "605", "688", "689"),          # main board + STAR
    "SZ": ("000", "001", "002", "003", "300", "301"),          # main board + ChiNext
    "BJ": ("4", "8", "920"),                                   # BSE
}

#: `list_status` values that mean the name is not part of the market on that day.
#: `D` = delisted.  `P` (paused/suspended) stays in: a halted name is still listed,
#: it just has no bar, which the coverage gap reports rather than hides.
DELISTED_LIST_STATUS = ("D",)

UNIVERSE_NAME = "a_share_full_market"


class MarketBreadthError(ValueError):
    """A breadth input violates the source contract and cannot be interpreted."""


def _num(series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _dates(frame: pd.DataFrame, label: str) -> pd.Series:
    if "trade_date" not in getattr(frame, "columns", []):
        raise MarketBreadthError(f"{label} is missing trade_date")
    text = frame["trade_date"].astype(str).str.strip()
    bad = ~text.str.fullmatch(r"[0-9]{8}")
    if bool(bad.any()):
        raise MarketBreadthError(f"{label} carries a non-canonical trade_date")
    return text


def is_a_share_code(ts_code: object) -> bool:
    """Accept only declared A-share code shapes; reject everything else.

    Inclusion, not exclusion.  B-shares are `900xxx.SH` / `200xxx.SZ`, so a suffix
    test passes them and a "not ChiNext, not STAR" test calls them main board.  A
    malformed symbol is rejected too rather than matched on its first three digits.
    """
    code = "" if ts_code is None else str(ts_code).strip().upper()
    if "." not in code:
        return False
    symbol, exchange = code.split(".", 1)
    prefixes = A_SHARE_CODE_PREFIXES.get(exchange)
    if not prefixes:
        return False
    if len(symbol) != 6 or not symbol.isdigit() or not symbol.isascii():
        return False
    return symbol.startswith(prefixes)


def is_bse_debut_limit_row(ts_code: object, up_limit: object, down_limit: object) -> bool:
    """Recognize the BSE first-day no-limit sentinel returned by the provider."""
    try:
        return (
            is_a_share_code(ts_code)
            and str(ts_code).strip().upper().endswith(".BJ")
            and float(up_limit) == 99999.99
            and float(down_limit) == 0.0
        )
    except (TypeError, ValueError):
        return False


def full_market_universe(stock_basic: pd.DataFrame, as_of: str) -> set[str]:
    """PIT full-market A-share universe as of `as_of`.

    Deliberately NOT `is_a_share_main_board()`: that helper answers "may I trade this",
    which is a different question from "is this part of the market whose mood I am
    measuring".  Listing/delisting are applied point-in-time so a name that had not
    listed yet, or had already delisted, cannot silently join the denominator.
    """
    if stock_basic is None or getattr(stock_basic, "empty", True):
        raise MarketBreadthError("stock_basic is required to bound the full-market universe")
    required = {"ts_code", "market", "list_date", "list_status"}
    missing = required - set(stock_basic.columns)
    if missing:
        raise MarketBreadthError(f"stock_basic is missing {sorted(missing)}")
    as_of = str(as_of)
    codes = stock_basic["ts_code"].astype(str).str.strip()
    market = stock_basic["market"].astype(str).str.strip()
    list_date = stock_basic["list_date"].astype(str).str.strip()
    delist_date = (stock_basic["delist_date"].astype(str).str.strip()
                   if "delist_date" in stock_basic.columns
                   else pd.Series([""] * len(stock_basic), index=stock_basic.index))

    status = stock_basic["list_status"].astype(str).str.strip().str.upper()

    on_a_board = market.isin(FULL_MARKET_BOARDS)
    a_share_code = codes.map(is_a_share_code)
    listed = list_date.str.fullmatch(r"[0-9]{8}") & (list_date <= as_of)
    # Two independent ways to be gone, because each alone has a hole: a delisted row
    # may carry no `delist_date`, and a dated delisting may not have had its status
    # updated.  Requiring BOTH to say "still here" is what closes them.
    delisted_by_date = delist_date.str.fullmatch(r"[0-9]{8}").fillna(False) & (delist_date <= as_of)
    delisted_by_status = status.isin(DELISTED_LIST_STATUS)
    return set(codes[on_a_board & a_share_code & listed
                     & ~delisted_by_date & ~delisted_by_status])


def usable_rows(daily: pd.DataFrame, stk_limit: pd.DataFrame) -> pd.DataFrame:
    """Join daily to its limit row and mark which (date, code) pairs are interpretable.

    A row is usable iff it has a finite positive close and high with `high >= close`
    AND a finite positive up/down limit for the same (date, code).

    The exact BSE first-day no-limit sentinel is an explained absent row and is
    excluded before this check; the coverage result reports that exclusion.
    """
    if daily is None or getattr(daily, "empty", True):
        return pd.DataFrame(columns=["trade_date", "ts_code", "close", "high",
                                     "up_limit", "down_limit", "usable"])
    for column in ("ts_code", "close", "high"):
        if column not in daily.columns:
            raise MarketBreadthError(f"daily is missing {column}")
    left = pd.DataFrame({
        "trade_date": _dates(daily, "daily").to_numpy(),
        "ts_code": daily["ts_code"].astype(str).str.strip().to_numpy(),
        "close": _num(daily["close"]).to_numpy(),
        "high": _num(daily["high"]).to_numpy(),
    })
    if left.duplicated(["trade_date", "ts_code"]).any():
        raise MarketBreadthError("daily has duplicate (trade_date, ts_code) rows")
    if stk_limit is None or getattr(stk_limit, "empty", True):
        merged = left.assign(up_limit=np.nan, down_limit=np.nan)
    else:
        for column in ("ts_code", "up_limit", "down_limit"):
            if column not in stk_limit.columns:
                raise MarketBreadthError(f"stk_limit is missing {column}")
        right = pd.DataFrame({
            "trade_date": _dates(stk_limit, "stk_limit").to_numpy(),
            "ts_code": stk_limit["ts_code"].astype(str).str.strip().to_numpy(),
            "up_limit": _num(stk_limit["up_limit"]).to_numpy(),
            "down_limit": _num(stk_limit["down_limit"]).to_numpy(),
        })
        if right.duplicated(["trade_date", "ts_code"]).any():
            raise MarketBreadthError("stk_limit has duplicate (trade_date, ts_code) rows")
        merged = left.merge(right, on=["trade_date", "ts_code"], how="left")
    debut_sentinel = [
        is_bse_debut_limit_row(code, up_limit, down_limit)
        for code, up_limit, down_limit in zip(
            merged["ts_code"], merged["up_limit"], merged["down_limit"]
        )
    ]
    merged = merged.loc[~np.asarray(debut_sentinel, dtype=bool)].copy()
    price_ok = (merged["close"].gt(0) & merged["high"].gt(0)
                & np.isfinite(merged["close"]) & np.isfinite(merged["high"])
                & merged["high"].ge(merged["close"]))
    limit_ok = (merged["up_limit"].gt(0) & merged["down_limit"].gt(0)
                & np.isfinite(merged["up_limit"]) & np.isfinite(merged["down_limit"]))
    return merged.assign(usable=(price_ok & limit_ok).fillna(False))


def limit_up_codes_by_date(rows: pd.DataFrame) -> dict[str, set]:
    """Every date's set of closing limit-up codes, from each stock's own limit."""
    if rows is None or rows.empty:
        return {}
    hit = rows["usable"] & rows["close"].ge(rows["up_limit"] * LIMIT_TOL)
    by_date: dict[str, set] = {}
    for date, code in zip(rows.loc[hit, "trade_date"], rows.loc[hit, "ts_code"]):
        by_date.setdefault(str(date), set()).add(str(code))
    return by_date


def max_limit_streak(up_by_date: dict[str, set], dates: list[str]) -> int:
    """Longest run of consecutive limit-up sessions ending on the LAST date given.

    `dates` must be the consecutive trading sessions in ascending order; a stock's run
    is unbroken membership walking backwards from the end, so a gap in `dates` -- a
    session the caller could not supply -- ends every run rather than being bridged.
    """
    if not dates:
        return 0
    alive = set(up_by_date.get(dates[-1], set()))
    streak = {code: 0 for code in alive}
    for date in reversed(dates):
        ups = up_by_date.get(date, set())
        still = set()
        for code in alive:
            if code in ups:
                streak[code] += 1
                still.add(code)
        alive = still
        if not alive:
            break
    return int(max(streak.values())) if streak else 0


def _unavailable(reason: str, as_of: str, requested: list[str], observed: list[str],
                 eligible: int, usable: int, universe_size: int = 0) -> dict:
    return {
        "full_market_limit_up_count": None,
        "full_market_limit_down_count": None,
        "full_market_consecutive_limit_up_height": None,
        "coverage": {
            "status": "unavailable",
            "universe_name": UNIVERSE_NAME,
            "requested_trade_dates": list(requested),
            "observed_trade_dates": list(observed),
            "universe_size": int(universe_size),
            "eligible_stock_count": int(eligible),
            "usable_stock_count": int(usable),
            "absent_stock_count": max(0, int(universe_size) - int(eligible)),
            "height_window_saturated": False,
            "unavailable_reason": reason,
        },
    }


def compute_full_market_breadth(*, as_of, daily, stk_limit, stock_basic,
                                trading_days, streak_sessions=10,
                                explained_missing_codes_by_date=None):
    """Full-market limit facts for `as_of`, or an honest `unavailable`.

    `trading_days` is the ascending session list the caller believes in; the streak walks
    back over the last `streak_sessions` of them that are `<= as_of`.
    """
    as_of = str(as_of)
    sessions = [str(d) for d in trading_days if str(d) <= as_of]
    if not sessions or sessions[-1] != as_of:
        raise MarketBreadthError("trading_days must end at as_of")
    window = sessions[-int(streak_sessions):]
    universe = full_market_universe(stock_basic, as_of)
    explained_missing_codes_by_date = explained_missing_codes_by_date or {}
    rows = usable_rows(daily, stk_limit)
    # PIT cap, stated rather than assumed: a caller may hand over a wider panel, and
    # a row dated after as_of must not be able to influence anything measured here.
    rows = rows[rows["ts_code"].isin(universe) & (rows["trade_date"] <= as_of)]
    today = rows[rows["trade_date"] == as_of]
    eligible, usable = int(len(today)), int(today["usable"].sum()) if len(today) else 0
    observed = sorted(set(rows["trade_date"])) if len(rows) else []

    universe_size = len(universe)
    absent = universe_size - eligible
    if eligible == 0:
        return _unavailable("no_traded_rows_for_as_of", as_of, window, observed,
                            0, 0, universe_size)
    if usable != eligible:
        # A stock that really traded but has no usable price or limit row means the
        # day's counts cannot be stated.  Reporting the partial count as if it were
        # the total is the one thing this must never do.
        return _unavailable("incomplete_usable_rows_for_as_of", as_of, window, observed,
                            eligible, usable, universe_size)

    up_by_date = limit_up_codes_by_date(rows)
    today_ok = today[today["usable"]]
    up_count = int((today_ok["close"] >= today_ok["up_limit"] * LIMIT_TOL).sum())
    down_count = int((today_ok["close"] <= today_ok["down_limit"] * (2 - LIMIT_TOL)).sum())

    reasons = []
    # The gap between "what the universe says exists" and "what arrived" was invisible
    # before: `eligible` could only ever count rows that turned up, so a truncated
    # page or a dropped board produced a smaller count and a shorter run and still
    # stamped `complete`.  Both errors point the same way -- an overheated market
    # made to look calm -- so the panel being short can never mean complete again.
    # It is not fatal (a halted name legitimately has no bar), it is reported.
    if absent > 0:
        reasons.append("universe_rows_absent")

    # The height needs the whole walk-back window; a hole understates the run rather
    # than admitting it does not know.
    if [d for d in window if d not in set(observed)]:
        height, height_reason = None, "incomplete_history_window"
    elif [d for d, group in rows.groupby("trade_date")
          if d in set(window) and int(group["usable"].sum()) != int(len(group))]:
        height, height_reason = None, "incomplete_history_window"
    else:
        # Per-stock holes are the subtle case: one candidate for the maximum missing
        # a single mid-window bar leaves every OTHER stock's day complete, so no
        # date-level check fires and the run is silently cut short at the hole.
        # Only the names that can set the maximum matter, so only they are required
        # to be present throughout.
        contenders = up_by_date.get(as_of, set())
        present = {(d, c) for d, c in zip(rows["trade_date"], rows["ts_code"])}
        explained_holes = any(
            (date, code) not in present
            and code in explained_missing_codes_by_date.get(date, set())
            for code in contenders
            for date in window
        )
        holed = sorted(
            code for code in contenders
            for date in window
            if (date, code) not in present
            and code not in explained_missing_codes_by_date.get(date, set())
        )
        if holed:
            height, height_reason = None, "contender_bar_missing_in_window"
        else:
            height = max_limit_streak(up_by_date, window)
            height_reason = (
                "suspension_gap_in_height_window" if explained_holes else None
            )
    if height_reason:
        reasons.append(height_reason)

    return {
        "full_market_limit_up_count": up_count,
        "full_market_limit_down_count": down_count,
        "full_market_consecutive_limit_up_height": height,
        "coverage": {
            "status": "complete" if not reasons else "partial",
            "universe_name": UNIVERSE_NAME,
            "requested_trade_dates": list(window),
            "observed_trade_dates": [d for d in window if d in set(observed)],
            "universe_size": universe_size,
            "eligible_stock_count": eligible,
            "usable_stock_count": usable,
            "absent_stock_count": absent,
            # A run that fills the whole walk-back window is a FLOOR, not a known
            # height -- it may well be longer than the window can see.  Kept as its
            # own flag rather than folded into `status`, because "I cannot see far
            # enough back" and "the panel was short" are different problems and a
            # reader who conflates them learns nothing from either.
            "height_window_saturated": bool(height is not None and height > 0
                                            and height >= len(window)),
            "unavailable_reason": "; ".join(reasons) if reasons else None,
        },
    }
