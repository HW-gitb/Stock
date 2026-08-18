"""A-short V14.3 comparison-record forward-return backfill + panel render (slice 2b-impl ②a, pure).

Two pure, comparison-only helpers on the weekly comparison records produced by
``engine.a_short_regime_classifier.build_comparison_record``:

- :func:`backfill_forward_returns` — fill the elapsed h1/h3/h5/h10 forward returns on the const-pinned
  basis (CSI1000 ``000852.SH`` raw forward close-to-close simple return, percent), NEVER look-ahead
  (only a horizon whose target trading day's close already exists is filled). An existing non-null
  value is NOT blindly kept — it is AUDITED against the deterministic CSI1000 return and RAISES on
  mismatch or if its target has not elapsed under ``as_of_now`` (only an audited matching value is
  preserved). Each updated record is re-validated through ``validate_comparison_record``.
- :func:`render_regime_comparison_block` — render a clearly-labelled comparison-only markdown block
  (V14.2 production vs V14.3 raw regime, divergence, evidence n/gate weeks, forward returns/pending,
  data-quality flags). It never mixes with overlay stars / M6.7 build actions.

Boundary (hard): pure logic, comparison-only, non-production. No data fetch, no EGS wiring, no file
write, no Phase 5 / veto / sizing. V14.2 stays the frozen production baseline.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from engine.a_short_regime_classifier import (
    validate_comparison_record, FORWARD_RETURN_BASIS, GOVERNANCE_PATH,
)
from engine.a_short_regime_ledger import is_canonical_date

# horizon → trading-day offset, single-sourced from the const-pinned basis.
_HORIZON_DAYS = dict(FORWARD_RETURN_BASIS["horizons_trading_days"])   # {"h1":1,"h3":3,"h5":5,"h10":10}


def _switch_gate_weeks() -> int:
    """forward-live weeks the switch-candidate gate requires (single source: governance)."""
    gov = json.loads(Path(GOVERNANCE_PATH).read_text(encoding="utf-8"))
    return int(gov["switch_candidate_gate"]["forward_live_weeks_min"])


def _index_close_map(csi1000: pd.DataFrame, as_of_now: str | None) -> tuple[list, dict]:
    """(ordered trade_dates, {date: finite close}) for CSI1000 rows <= as_of_now; raise on bad dates/dups."""
    if csi1000 is None or csi1000.empty or "trade_date" not in csi1000.columns or "close" not in csi1000.columns:
        return [], {}
    df = csi1000.copy()
    bad = sorted({str(d) for d in df["trade_date"] if not is_canonical_date(str(d))})
    if bad:
        raise ValueError(f"backfill_forward_returns: csi1000 has non-canonical trade_date {bad[:3]}")
    if as_of_now is not None:
        if not is_canonical_date(as_of_now):
            raise ValueError(f"backfill_forward_returns: as_of_now {as_of_now!r} is not a real YYYYMMDD date")
        df = df[df["trade_date"].astype(str) <= str(as_of_now)]
    keys = df["trade_date"].astype(str)
    if keys.duplicated().any():
        raise ValueError("backfill_forward_returns: csi1000 has duplicate trade_date rows")
    df = df.assign(_d=keys, _c=pd.to_numeric(df["close"], errors="coerce")).sort_values("_d")
    dates = list(df["_d"])
    # a valid index close is finite AND positive; NaN/Inf/zero/negative → unavailable (None), so a
    # bogus 0/-1 target can't fabricate a −100%/−101% forward return.
    close = {d: (float(c) if (np.isfinite(c) and c > 0) else None) for d, c in zip(df["_d"], df["_c"])}
    return dates, close


def _backfill_forward_return_values(forward_returns: dict, anchor: str,
                                    dates: list, close: dict) -> dict:
    fr = dict(forward_returns or {})
    a_pos = {d: i for i, d in enumerate(dates)}.get(str(anchor))
    a_close = close.get(str(anchor))
    anchor_ok = a_pos is not None and a_close is not None
    for h, ndays in _HORIZON_DAYS.items():
        existing = fr.get(h)
        t_close = None
        if anchor_ok:
            t_pos = a_pos + ndays
            if t_pos < len(dates):
                t_close = close.get(dates[t_pos])
        available = anchor_ok and t_close is not None
        if existing is not None:
            if not available:
                raise ValueError(
                    f"backfill_forward_returns: existing forward_returns.{h}={existing} on {anchor} "
                    "cannot be verified — target horizon not available ≤ as_of_now (not elapsed / "
                    "out of series); refusing to count an unverifiable look-ahead value"
                )
            recomputed = round((t_close / a_close - 1.0) * 100.0, 6)
            if abs(float(existing) - recomputed) > 1e-6:
                raise ValueError(
                    f"backfill_forward_returns: existing forward_returns.{h}={existing} on {anchor} "
                    f"!= deterministic CSI1000 return {recomputed}; corrupt prefilled value"
                )
        elif available:
            fr[h] = round((t_close / a_close - 1.0) * 100.0, 6)
    return {h: fr.get(h, None) for h in _HORIZON_DAYS}


def backfill_forward_return_values(forward_returns: dict, anchor: str,
                                   csi1000: pd.DataFrame,
                                   as_of_now: str | None = None) -> dict:
    """Shared pure CSI1000 raw close-to-close backfill used by comparison consumers."""
    dates, close = _index_close_map(csi1000, as_of_now)
    return _backfill_forward_return_values(forward_returns, str(anchor), dates, close)


def backfill_forward_returns(records: Iterable[dict], csi1000: pd.DataFrame,
                             as_of_now: str | None = None) -> list[dict]:
    """Fill elapsed forward returns on each record from the CSI1000 series; return updated copies.

    A null horizon ``h`` is filled only if the record's ``as_of`` and the ``h``-th trading day after it
    both exist in the (``as_of_now``-capped) CSI1000 series with a finite positive close — otherwise it
    stays null (no look-ahead, no fabrication). An EXISTING non-null horizon is audited, not blindly
    kept: if its target is not available under ``as_of_now`` (not elapsed / out of series) it RAISES;
    if available, the stored value must equal the deterministic CSI1000 return within ``1e-6`` else it
    RAISES; only a matching value is preserved. Each updated record is re-validated; invalid → raises.
    """
    dates, close = _index_close_map(csi1000, as_of_now)
    out = []
    for rec in records:
        r = json.loads(json.dumps(rec))   # deep copy (records are plain JSON)
        anchor = str(r.get("as_of"))
        r["forward_returns"] = _backfill_forward_return_values(
            r.get("forward_returns") or {}, anchor, dates, close
        )
        r["forward_returns_pending"] = [h for h in _HORIZON_DAYS if r["forward_returns"][h] is None]
        r["backfill_complete"] = not r["forward_returns_pending"]
        validate_comparison_record(r)              # self-check the updated record
        out.append(r)
    return out


def summarize_comparison_records(records: Iterable[dict], csi1000: pd.DataFrame,
                                 as_of_now: str) -> dict:
    """Audited evidence counts for the switch-candidate clock; raise on any invalid input.

    ``csi1000`` + ``as_of_now`` are MANDATORY (no default) — there is no unaudited or uncapped evidence
    count. ``as_of_now`` must be a real canonical YYYYMMDD date so the PIT cap is real (an uncapped
    pass over a CSI1000 frame containing future rows would count look-ahead horizons as evidence).
    This runs :func:`backfill_forward_returns` (which caps the index at ``as_of_now``, audits every
    existing forward-return value against the deterministic CSI1000 return, and
    ``validate_comparison_record``s each record — raising on fabrication / look-ahead) BEFORE counting,
    and rejects duplicate ``as_of``."""
    audited = _audited_history(records, csi1000, as_of_now)
    return {
        "total_weeks": len(audited),
        "divergence_weeks": sum(1 for r in audited if r.get("divergence")),
        "backfill_complete_weeks": sum(1 for r in audited if r.get("backfill_complete")),
    }


def _audited_history(records: Iterable[dict], csi1000: pd.DataFrame, as_of_now: str) -> list[dict]:
    """Audit a comparison-record history for the evidence clock; raise on any disqualifier.

    ``as_of_now`` mandatory canonical. Each record is backfilled+validated (audits existing forward
    values vs the deterministic CSI1000 return, raising on fabrication/look-ahead); a record dated
    AFTER ``as_of_now`` (a future/look-ahead week) is rejected; duplicate ``as_of`` is rejected."""
    if as_of_now is None or not is_canonical_date(as_of_now):
        raise ValueError(f"audited history: as_of_now must be a real YYYYMMDD date "
                         f"(the PIT cap is mandatory for evidence counting), got {as_of_now!r}")
    audited = backfill_forward_returns(records, csi1000, as_of_now)
    seen = set()
    for r in audited:
        a = str(r.get("as_of"))
        if a > str(as_of_now):
            raise ValueError(f"audited history: record as_of {a} is after as_of_now {as_of_now} "
                             f"(future/look-ahead week cannot count as evidence)")
        if a in seen:
            raise ValueError(f"audited history: duplicate as_of {a} (cannot count twice)")
        seen.add(a)
    return audited


def _fmt(v) -> str:
    return "pending" if v is None else f"{v:+.2f}"


def render_regime_comparison_block(record: dict, csi1000: pd.DataFrame, as_of_now: str,
                                   records: Iterable[dict] | None = None,
                                   switch_gate_weeks: int | None = None) -> str:
    """Render the comparison-only regime block for the weekly panel (pure markdown string).

    ``record`` = this run's comparison record; ``records`` (optional) = accumulated history for the
    evidence counter. ``csi1000`` + ``as_of_now`` are MANDATORY (no default; ``as_of_now`` must be a
    real canonical YYYYMMDD date) so the panel can only display AUDITED, PIT-capped forward returns /
    evidence: the current record and any history go through :func:`backfill_forward_returns` (capped at
    ``as_of_now``, raising on fabricated / look-ahead values) before display. The block is explicitly
    non-production and must never be merged with overlay stars or M6.7 actions.
    """
    if as_of_now is None or not is_canonical_date(as_of_now):
        raise ValueError(f"render_regime_comparison_block: as_of_now must be a real YYYYMMDD date "
                         f"(mandatory PIT cap), got {as_of_now!r}")
    record = backfill_forward_returns([record], csi1000, as_of_now)[0]   # audit + PIT-cap before display
    if str(record.get("as_of")) > str(as_of_now):
        raise ValueError(f"render_regime_comparison_block: current record as_of {record.get('as_of')} "
                         f"is after as_of_now {as_of_now} (future week cannot be the current panel)")
    gate = switch_gate_weeks if switch_gate_weeks is not None else _switch_gate_weeks()
    summ = None
    if records is not None:
        audited = _audited_history(records, csi1000, as_of_now)   # future/dup/audit-checked history
        # the displayed current week must be present exactly once in the evidence history and identical
        # to the audited current record — otherwise the panel's "current" and its evidence counts are
        # inconsistent (the shown week would be excluded from / disagree with the counts).
        match = [r for r in audited if str(r.get("as_of")) == str(record.get("as_of"))]
        if len(match) != 1:
            raise ValueError(f"render_regime_comparison_block: current record as_of {record.get('as_of')} "
                             f"must appear exactly once in records (found {len(match)})")
        if match[0] != record:
            raise ValueError(f"render_regime_comparison_block: current record for {record.get('as_of')} "
                             f"does not match the same-as_of record in history (payload mismatch)")
        summ = {
            "total_weeks": len(audited),
            "divergence_weeks": sum(1 for r in audited if r.get("divergence")),
            "backfill_complete_weeks": sum(1 for r in audited if r.get("backfill_complete")),
        }
    fr = record.get("forward_returns") or {}
    flags = record.get("data_quality_flags") or []
    lines = [
        "### 市场环境对比 (V14.3 comparison-only — 非生产 / 不构成交易信号)",
        f"- as_of: {record.get('as_of')}",
        f"- 生产基线 V14.2: **{record.get('v14_2_regime')}**",
        f"- 候选 V14.3 (raw): **{record.get('v14_3_raw_regime')}**  (rule: {record.get('v14_3_fired_rule')})",
        f"- 是否分歧: {'是' if record.get('divergence') else '否'}",
    ]
    if summ is not None:
        lines.append(f"- 证据进度: {summ['total_weeks']}/{gate} 周 (分歧 {summ['divergence_weeks']} 周; "
                     f"切换门槛未达前绝不切换)")
    else:
        lines.append(f"- 证据进度: 切换门槛 {gate} 周 forward-live (未达前绝不切换)")
    lines.append("- 后续表现 (CSI1000 000852.SH raw fwd close-to-close, %): "
                 f"h1 {_fmt(fr.get('h1'))} | h3 {_fmt(fr.get('h3'))} | "
                 f"h5 {_fmt(fr.get('h5'))} | h10 {_fmt(fr.get('h10'))}")
    if record.get("v14_3_insufficient_window"):
        lines.append(f"- ⚠ V14.3 分位窗不足 (window_n={record.get('v14_3_window_n')})")
    lines.append(f"- 数据质量: {', '.join(flags) if flags else '无'}")
    lines.append("> 仅用于对比验证与证据积累;绝不与 overlay 星级 / M6.7 建仓动作 / 仓位结论混写。")
    return "\n".join(lines)
