"""A-short V14.3 regime weekly orchestration (slice 2b-impl ②b-1, pure, comparison-only).

Composes the already-reviewed pure pieces (ledger gates, the raw classifier + comparison record, the
forward-return backfill / audited evidence path) into the deterministic weekly workflow, with the
data side INJECTED so it stays fully unit-testable without any Tushare fetch or file write:

- :func:`extend_ledger` — the fail-closed cadence workflow: validate the existing ledger for append →
  plan the trading days to add → ask ``feature_provider(date)`` for each day's daily-feature row →
  append (immutably) → re-validate the merged ledger through the sanctioned current/read gate. The
  SAME function does the one-time bootstrap (empty ledger → ``plan_append`` returns the last 252
  trading days) and the weekly increment (~5 days) — only the number of provider calls differs.
- :func:`weekly_regime_step` — one weekly run: extend the ledger, build this week's V14.2-vs-V14.3
  comparison record, then run the audited evidence path (backfill / summarize / render) over the full
  comparison-record history.

Boundary (hard): pure logic, comparison-only, non-production. It performs NO Tushare fetch, NO EGS
wiring, NO file write — the real ``feature_provider`` (in-EGS fetch + ``compute_regime_daily_features``),
the ``csi1000`` frame, file persistence, the bootstrap-runner CLI, and the panel-into-weekly-report
wiring are slice 2b-impl ②b-2 (and the bootstrap RUN is a user-authorized ``执行`` + TUSHARE_TOKEN).
V14.2 stays the frozen production baseline.
"""
from __future__ import annotations

from typing import Callable, Iterable

import pandas as pd

from engine.a_short_regime_ledger import (
    validate_ledger_for_append, plan_append, merge_rows, build_ledger, validate_ledger,
)
from engine.a_short_regime_classifier import build_comparison_record
from engine.a_short_regime_comparison import (
    backfill_forward_returns, summarize_comparison_records, render_regime_comparison_block,
)


def extend_ledger(existing_ledger: dict, as_of: str, trade_calendar: Iterable[str],
                  feature_provider: Callable[[str], dict]) -> dict:
    """Extend the daily-feature ledger up to ``as_of`` via the fail-closed cadence workflow.

    ``feature_provider(date)`` must return the ``a_short_market_regime_daily`` row for ``date`` (in
    ②b-2 this fetches stk_limit + indices + IV and calls ``compute_regime_daily_features``). The
    existing ledger is checked with :func:`validate_ledger_for_append` BEFORE planning (so a gappy /
    future-contaminated history is rejected, not silently appended-onto); :func:`plan_append` yields
    the trading days to add (bootstrap = last 252 ≤ as_of when empty, else the days since the last);
    provider output is required to be dated exactly ``date``; the merged ledger is re-validated through
    the sanctioned current/read gate (:func:`validate_ledger`, incl. freshness through ``as_of``).
    Returns the new ledger dict (does NOT write it — persistence is ②b-2)."""
    cal = list(trade_calendar)   # materialize ONCE — passed to 3 helpers; a generator would empty out
    existing_rows = list(existing_ledger.get("rows") or [])
    validate_ledger_for_append(existing_ledger, as_of=as_of, trade_calendar=cal)
    todo = plan_append([str(r["as_of"]) for r in existing_rows], as_of, cal)
    new_rows = []
    for d in todo:
        row = feature_provider(d)
        if not isinstance(row, dict) or str(row.get("as_of")) != str(d):
            raise ValueError(f"extend_ledger: feature_provider({d!r}) must return a daily-feature row "
                             f"dict with as_of=={d!r}, got {row!r}")
        new_rows.append(row)
    merged = merge_rows(existing_rows, new_rows, as_of)
    if not existing_rows and not merged:
        # bootstrapping from an empty ledger but no eligible trading day <= as_of was produced — a
        # bad/empty calendar (or all-future range). Refuse to persist a fabricated "successful" empty
        # ledger (an empty pre-bootstrap envelope is fine for validate_ledger, NOT for this driver).
        raise ValueError(f"extend_ledger: bootstrap from empty ledger produced no rows — no eligible "
                         f"trading day <= as_of {as_of} in the calendar (bad/empty calendar)")
    new_ledger = build_ledger(merged)
    validate_ledger(new_ledger, as_of=as_of, trade_calendar=cal)
    return new_ledger


def weekly_regime_step(existing_ledger: dict, as_of: str, trade_calendar: Iterable[str],
                       v14_2_regime: str, csi1000: pd.DataFrame,
                       feature_provider: Callable[[str], dict],
                       prior_comparison_records: Iterable[dict] = (),
                       generated_at: str | None = None) -> dict:
    """Run one weekly V14.3 comparison step (pure). Returns the new ledger, this week's audited
    comparison record, the audited comparison-record history, the evidence summary, and the
    comparison-only panel markdown.

    The forward-return / evidence path is PIT-capped at ``as_of`` (the run date) and audited, so this
    week's not-yet-elapsed horizons stay pending and no look-ahead can advance the evidence clock.
    Comparison-only: this drives nothing; V14.2 stays the frozen production baseline.
    """
    cal = list(trade_calendar)   # materialize once (reused by extend_ledger)
    new_ledger = extend_ledger(existing_ledger, as_of, cal, feature_provider)
    record = build_comparison_record(new_ledger["rows"], v14_2_regime, as_of=as_of,
                                     generated_at=generated_at)
    # same-week rerun semantics: if the loaded history already has this as_of, an IDENTICAL
    # classification is a legitimate rerun (replace the row — forward returns are re-derived by the
    # audit anyway); a DIFFERENT classification for the same week is an immutable-history conflict.
    prior = list(prior_comparison_records)
    cur_as_of = str(record["as_of"])
    same = [r for r in prior if str(r.get("as_of")) == cur_as_of]
    if same:
        if len(same) > 1:
            raise ValueError(f"weekly_regime_step: prior_comparison_records already has duplicate "
                             f"as_of {cur_as_of}")
        if not _same_classification(same[0], record):
            raise ValueError(f"weekly_regime_step: same-week rerun for {cur_as_of} differs from history "
                             f"in immutable classification fields (immutable-history conflict)")
        all_records = [r for r in prior if str(r.get("as_of")) != cur_as_of] + [record]
    else:
        all_records = prior + [record]
    audited = backfill_forward_returns(all_records, csi1000, as_of)
    evidence = summarize_comparison_records(all_records, csi1000, as_of)
    panel = render_regime_comparison_block(record, csi1000, as_of, records=all_records)
    current = next(r for r in audited if str(r.get("as_of")) == cur_as_of)
    return {
        "ledger": new_ledger,
        "comparison_record": current,
        "comparison_records": sorted(audited, key=lambda r: str(r.get("as_of"))),   # stable persist order
        "evidence": evidence,
        "panel_markdown": panel,
        "boundary": {"production": False, "comparison_only": True,
                     "drives_phase5_risk_posture": False},
    }


# immutable comparison-record classification fields (forward_returns/pending/backfill_complete are
# mutable — they get backfilled over time, so they are excluded from same-week rerun equality).
_CLASSIFICATION_KEYS = ("schema_name", "schema_version", "as_of", "v14_2_regime", "v14_3_raw_regime",
                        "divergence", "v14_3_fired_rule", "v14_3_window_n", "v14_3_insufficient_window",
                        "data_quality_flags", "forward_return_basis", "boundary")


def _same_classification(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in _CLASSIFICATION_KEYS)
