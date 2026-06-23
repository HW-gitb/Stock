# -*- coding: utf-8 -*-
"""US-short §11.2 price clock consistency — batch-3 (#21): the price-clock fail-closed validator.

Design authority: docs/us_short_system_design.md §11.2 honest banner ④ (price clock 必显: price_data_through=
上周五收盘=canonical 决策日前一已收盘交易日 / news_window_through=运行时刻 / session_scope=RTH / decision_date=
canonical 即将到来的美股交易日) / §3.5 (机器层 as_of / session / timezone) / §2.1 (canonical decision date) /
§18.1 #21. Field-list authority = the FROZEN us_short_weekly_report_contract ``price_clock.fields`` (single source).

The weekly_report renderer (banner ④) already enforces the price clock is ALWAYS shown with all 4 fields
non-blank; THIS is the complement — the fail-closed CONSISTENCY gate (#21): ``session_scope`` must be RTH, the
three date fields must be strict REAL dates, and they must be correctly ORDERED so a reader can never be shown a
stale / forward / mixed price clock — ``price_data_through`` is a PRIOR closed trading day (STRICTLY before
``decision_date`` — a price dated on/after the decision day is a stale / forward leak), and the news window runs
from the price-data day up to (at most) the decision day (``price_data_through <= news_window_through <=
decision_date``). When the §3.5 machine-layer ``as_of`` / ``session`` are supplied, the clock must agree with
them, so the surfaced clock can never disagree with the machine layer it renders from. Pure / offline: validates
a dict; no provider / live / DataHub / network; no A-share crossing.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_CONTRACT_PRESET = ROOT / "presets" / "us_short_weekly_report_contract_20260620.json"

_SESSION_SCOPE = "RTH"  # §11.2 ④ / §21: US-short decisions price off regular-trading-hours only
_DATE_FIELDS = ("price_data_through", "news_window_through", "decision_date")

_CACHE: dict = {}


class PriceClockError(ValueError):
    """Raised when a price clock violates the §11.2 ④ / §21 consistency contract (fields, session, dates, order)."""


def _fields() -> list:
    if "fields" not in _CACHE:
        _CACHE["fields"] = list(json.loads(_CONTRACT_PRESET.read_text(encoding="utf-8"))["price_clock"]["fields"])
    return _CACHE["fields"]


def _strict_yyyymmdd(s) -> bool:
    # mirrors engine.us_short_lifecycle_eval._strict_yyyymmdd (the canonical lifecycle date gate); inlined so this
    # pure validator stays importable on a minimal runtime (no jsonschema pull-in, like us_short_lifecycle_render)
    if not (isinstance(s, str) and len(s) == 8 and s.isascii() and s.isdigit()):  # isascii() rejects Unicode digits (Arabic-Indic / fullwidth) that int() would still coerce
        return False
    try:
        datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return True
    except ValueError:
        return False


def validate_price_clock(price_clock, *, machine_as_of=None, machine_session=None) -> None:
    """Fail-closed §11.2 ④ / §21 price-clock consistency gate.

    Enforces: a dict carrying EXACTLY the frozen price_clock fields; ``session_scope == "RTH"``;
    ``price_data_through`` / ``news_window_through`` / ``decision_date`` strict REAL YYYYMMDD dates; the ordering
    ``price_data_through < decision_date`` (a PRIOR closed trading day — a price dated on/after the decision day is
    a stale / forward leak, refused) and ``price_data_through <= news_window_through <= decision_date`` (the news
    window runs from the price-data day up to the decision day). When ``machine_as_of`` / ``machine_session`` are
    given (§3.5), the clock must agree (``price_data_through == machine_as_of`` ; ``session_scope ==
    machine_session``). Raises ``PriceClockError`` on any violation."""
    if not isinstance(price_clock, dict):
        raise PriceClockError("price_clock must be a dict")
    if set(price_clock) != set(_fields()):
        raise PriceClockError(
            "price_clock must carry EXACTLY the frozen fields %s, got %s" % (_fields(), sorted(map(str, price_clock)))
        )
    if price_clock["session_scope"] != _SESSION_SCOPE:
        raise PriceClockError("session_scope must be %r (§11.2 ④ RTH-only), got %r" % (_SESSION_SCOPE, price_clock["session_scope"]))
    for f in _DATE_FIELDS:
        if not _strict_yyyymmdd(price_clock[f]):
            raise PriceClockError("%s must be a strict real YYYYMMDD, got %r" % (f, price_clock[f]))
    pdt, nwt, dd = price_clock["price_data_through"], price_clock["news_window_through"], price_clock["decision_date"]
    if not pdt < dd:  # strict real YYYYMMDD strings sort chronologically
        raise PriceClockError(
            "price_data_through %s must be STRICTLY before decision_date %s — a PRIOR closed trading day; a price "
            "dated on/after the decision day is a stale / forward leak (§21 混合/陈旧价格 fail-closed)" % (pdt, dd)
        )
    if not pdt <= nwt <= dd:
        raise PriceClockError(
            "news_window_through %s must be within [price_data_through %s, decision_date %s]" % (nwt, pdt, dd)
        )
    if machine_as_of is not None and pdt != machine_as_of:
        raise PriceClockError("price_data_through %s != machine-layer as_of %s (§3.5 must agree)" % (pdt, machine_as_of))
    if machine_session is not None and price_clock["session_scope"] != machine_session:
        raise PriceClockError("session_scope %s != machine-layer session %s (§3.5 must agree)" % (price_clock["session_scope"], machine_session))
