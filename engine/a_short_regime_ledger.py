"""A-short V14.3 regime daily-feature ledger — cadence design (slice 2b-cadence, pure logic).

Settles HOW the 252-trading-day percentile window is maintained without recomputing 252 days of
``daily`` + ``stk_limit`` every weekly EGS run: a persisted, append-only, contiguous ledger of
per-trade-day regime feature rows (each matching ``schemas/a_short_market_regime_daily.schema.json``)
under the a_short lane. One-time backfill of the last 252 trading days, then each weekly run appends
the trading days since the last ledger date (~5/week, self-healing across missed runs).

This module is **pure cadence logic only** — it plans which trade dates to append, merges rows
append-only, and validates ledger integrity. It does **not** fetch data, compute features, touch the
EGS run, or write files (that is the remaining slice-2b implementation, drafted after this cadence
design passes review). Boundary (hard): comparison-only, non-production, V14.2 stays frozen, never
drives Phase 5 / veto / sizing, never written under ``result/a_short`` (guard-safe lane only).
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Iterable

from engine.a_short_run_revision import validate_run_revision_id

ROOT = Path(__file__).resolve().parents[1]
DAILY_SCHEMA_PATH = ROOT / "schemas" / "a_short_market_regime_daily.schema.json"

PERCENTILE_WINDOW = 252
BACKFILL_MIN_TRADING_DAYS = 252
# guard-safe lane root; the pipeline's _reject_production_output_path only rejects /result/a_short/.
LEDGER_LANE_ROOT = "research/results/a_short"
LEDGER_FILENAME = "regime_daily_ledger.json"

# const-pinned cadence policy (mirrors the ledger schema `policy` const block; parity-tested).
LEDGER_POLICY = {
    "percentile_window": PERCENTILE_WINDOW,
    "backfill_min_trading_days": BACKFILL_MIN_TRADING_DAYS,
    "row_contract": "a_short_market_regime_daily",
    "append_rule": ("contiguous trading days in (last_ledger_date, as_of]; bootstrap = the last "
                    "backfill_min trading days <= as_of; existing dates immutable; never > as_of"),
    "cadence": "weekly_egs_append_plus_one_time_backfill",
}


# daily-feature numeric (float) fields that must be finite-or-null (jsonschema accepts NaN/Inf).
_DAILY_FLOAT_FIELDS = ("promotion_rate", "failed_limit_rate", "iv_percentile_252d",
                       "csi300_ret_1d", "csi1000_ret_1d", "pct_above_ma20")


def _row_revision(row: dict) -> str | None:
    value = row.get("run_revision_id")
    if value in (None, ""):
        return None
    return validate_run_revision_id(str(value))


def _row_observation_date(row: dict) -> str:
    observed = row.get("observed_data_through")
    if observed not in (None, ""):
        if not _is_canonical_date(str(observed)):
            raise ValueError(f"row observed_data_through {observed!r} is not a real YYYYMMDD date")
        if row.get("as_of") not in (None, "") and str(row.get("as_of")) != str(observed):
            raise ValueError("row observed_data_through must equal as_of for a daily snapshot")
        return str(observed)
    return str(row.get("as_of"))


def _row_key(row: dict) -> tuple[str, str]:
    return (_row_observation_date(row), _row_revision(row) or "legacy_revision_0")


def is_canonical_date(s) -> bool:
    """True iff ``s`` is a real calendar date in canonical YYYYMMDD form.

    Strict: must be a str of exactly 8 ASCII digits AND round-trip
    ``strptime(s).strftime("%Y%m%d") == s``. ``strptime`` alone is too lenient — it parses
    ``"2024011"`` and ``"202401 1"`` as 2024-01-01 — which would make lexicographic PIT/freshness
    ordering unsound; the length + ASCII-digit + round-trip guards reject those. Public so sibling
    V14.3 producers (e.g. the feature computation) share one canonical-date definition.
    """
    if not isinstance(s, str) or len(s) != 8 or not all(c in "0123456789" for c in s):
        return False
    try:
        return datetime.strptime(s, "%Y%m%d").strftime("%Y%m%d") == s
    except ValueError:
        return False


_is_canonical_date = is_canonical_date   # internal back-compat alias (single source)


def daily_row_semantic_errors(row: dict) -> list[str]:
    """Return semantic errors JSON Schema cannot express for a daily-feature row.

    Checks: ``as_of`` is a real YYYYMMDD date; the float fields are finite or null (not NaN/Inf);
    and ``net_limit == limit_up_count - limit_down_count`` (net_limit is derived and feeds the
    defense/attack logic, so an inconsistent value can flip the regime).
    """
    errs = []
    try:
        d = _row_observation_date(row)
        _row_revision(row)
    except ValueError as exc:
        return [str(exc)]
    if not _is_canonical_date(d):
        errs.append(f"row as_of {d!r} is not a real YYYYMMDD date")
    for f in _DAILY_FLOAT_FIELDS:
        v = row.get(f)
        if v is not None and isinstance(v, (int, float)) and not math.isfinite(float(v)):
            errs.append(f"row {d} field {f} is non-finite ({v!r})")
    up, down, net = row.get("limit_up_count"), row.get("limit_down_count"), row.get("net_limit")
    if all(isinstance(x, int) for x in (up, down, net)) and net != up - down:
        errs.append(f"row {d} net_limit {net} != limit_up_count-limit_down_count ({up - down})")
    return errs


def _sorted_dates(rows_or_dates: Iterable) -> list[str]:
    out = []
    for r in rows_or_dates:
        out.append(str(r.get("as_of")) if isinstance(r, dict) else str(r))
    return sorted(out)


def plan_append(existing_dates: Iterable, as_of: str, trade_calendar: Iterable[str], *,
                backfill_min: int = BACKFILL_MIN_TRADING_DAYS) -> list[str]:
    """Return the ascending trade dates to compute & append for a run dated ``as_of``.

    - PIT: never returns a date > ``as_of`` (no look-ahead).
    - Empty ledger → bootstrap: the last ``backfill_min`` trading days <= ``as_of``.
    - Non-empty ledger → all trading days in ``(max(existing), as_of]`` (steady state ~5/week, but
      self-heals gaps from missed runs *after* ``max(existing)``); empty if already current.

    Note: this plans forward from ``max(existing)`` only — it does not repair an internal gap before
    ``max(existing)``. That is safe because the caller MUST run :func:`validate_ledger_for_append` on
    the existing ledger BEFORE planning (it rejects a gappy/future existing ledger, fail-closed).
    Do NOT use :func:`validate_ledger` as the pre-append gate — it adds freshness and would reject the
    normal prior-run ledger; reserve it for the merged final ledger and read use.
    """
    if backfill_min <= 0:
        raise ValueError(f"plan_append: backfill_min must be positive, got {backfill_min}")
    if not _is_canonical_date(as_of):
        raise ValueError(f"plan_append: as_of {as_of!r} is not a real YYYYMMDD date")
    cal_entries = [str(d) for d in trade_calendar]       # materialize ONCE (may be a generator)
    bad_cal = [d for d in cal_entries if not _is_canonical_date(d)]
    if bad_cal:
        raise ValueError(f"plan_append: trade_calendar has non-date entries: {sorted(bad_cal)[:3]}")
    cal = sorted(set(cal_entries))
    existing_list = [str(d.get("as_of")) if isinstance(d, dict) else str(d) for d in existing_dates]
    dup = sorted({d for d in existing_list if existing_list.count(d) > 1})
    if dup:
        raise ValueError(f"plan_append: existing dates contain duplicates {dup[:3]} (corrupt ledger; "
                         f"run validate_ledger_for_append first)")
    existing = set(existing_list)
    bad_ex = [d for d in existing if not _is_canonical_date(d)]
    if bad_ex:
        raise ValueError(f"plan_append: existing ledger has non-date entries: {sorted(bad_ex)[:3]}")
    elig = [d for d in cal if d <= str(as_of)]            # PIT cap
    if existing and max(existing) > str(as_of):
        # never plan against a look-ahead-contaminated ledger (else a future date silently makes
        # the ledger look "already current" and the run appends nothing).
        raise ValueError(f"plan_append: existing ledger contains a date > as_of {as_of} "
                         f"(max={max(existing)}); ledger is future-contaminated")
    if not elig:
        return []
    if not existing:
        return elig[-backfill_min:]                        # bootstrap backfill
    last = max(existing)
    return [d for d in elig if d > last]                   # gap self-heal + steady state


def merge_rows(existing_rows: Iterable[dict], new_rows: Iterable[dict], as_of: str) -> list[dict]:
    """Append ``new_rows`` to ``existing_rows`` append-only, returning the sorted merged list.

    Rejects (``ValueError``): non-canonical dates; a new row dated > ``as_of`` (look-ahead); a new row
    whose date already exists with a DIFFERENT payload (existing dates are immutable — a data revision
    must be handled explicitly, never silently overwritten); and duplicate dates within
    ``existing_rows`` (corrupt ledger). An identical re-append of an existing date is a no-op.

    Scope: this is **merge-only** — it does NOT validate daily-row semantics (finite floats,
    net_limit, schema). The caller MUST run :func:`validate_ledger_for_append` on ``existing_rows``
    before, and :func:`validate_ledger` on the merged result before any write/read (the sanctioned
    gates own row-contract validity).
    """
    if not _is_canonical_date(as_of):
        raise ValueError(f"merge_rows: as_of {as_of!r} is not a real YYYYMMDD date")
    existing_rows = list(existing_rows)
    existing_key_list = [_row_key(r) for r in existing_rows]
    dup = sorted({key for key in existing_key_list if existing_key_list.count(key) > 1})
    if dup:
        # append-only immutable ledger must never carry duplicate dates; the dict-build below would
        # silently collapse them and hide the corruption, so reject before conversion.
        raise ValueError(f"merge_rows: existing_rows contain duplicate observation keys {dup[:3]} (corrupt ledger)")
    existing = {_row_key(r): r for r in existing_rows}
    errs = []
    for d, _revision in existing:                           # existing rows must already be PIT
        if not _is_canonical_date(d):
            errs.append(f"existing row {d!r} is not a real YYYYMMDD date")
        elif d > str(as_of):
            errs.append(f"existing row {d} is after as_of {as_of} (look-ahead-contaminated ledger)")
    for row in new_rows:
        try:
            d = _row_observation_date(row)
            key = _row_key(row)
        except ValueError as exc:
            errs.append(str(exc))
            continue
        if not _is_canonical_date(d):
            errs.append(f"new row {d!r} is not a real YYYYMMDD date")
            continue
        if d > str(as_of):
            errs.append(f"row {d} is after as_of {as_of} (look-ahead)")
            continue
        if key in existing and existing[key] != row:
            errs.append(f"row {d} already exists with a different payload (immutable; revision must be explicit)")
            continue
        existing[key] = row
    if errs:
        raise ValueError("merge_rows rejected: " + "; ".join(errs))
    return [existing[key] for key in sorted(existing)]


def build_ledger(rows: Iterable[dict], generated_at: str | None = None,
                 run_revision_id: str | None = None) -> dict:
    """Assemble the ledger envelope (metadata + const policy + boundary) around sorted rows."""
    if run_revision_id is not None:
        run_revision_id = validate_run_revision_id(run_revision_id)
    rows = [dict(row) for row in rows]
    for row in rows:
        date = _row_observation_date(row)
        row.setdefault("as_of", date)
        if run_revision_id is not None:
            current = _row_revision(row)
            if current not in (None, run_revision_id):
                raise ValueError("build_ledger: row revision does not match ledger revision")
            row["run_revision_id"] = run_revision_id
            row.setdefault("observed_data_through", date)
    rows = sorted(rows, key=_row_key)
    dates = [_row_observation_date(r) for r in rows]
    payload = {
        "schema_name": "a_short_regime_daily_ledger",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "coverage": {
            "start": dates[0] if dates else None,
            "end": dates[-1] if dates else None,
            "n": len(dates),
        },
        "policy": dict(LEDGER_POLICY),
        "rows": rows,
        "boundary": {"production": False, "comparison_only": True,
                     "drives_phase5_risk_posture": False, "lane_root": LEDGER_LANE_ROOT},
    }
    if run_revision_id is not None:
        payload["run_revision_id"] = run_revision_id
    return payload


def validate_ledger_envelope(ledger: dict, *, validate_rows: bool = True) -> bool:
    """Context-free envelope validity (NO PIT / NO contiguity); raise ``ValueError`` on any.

    Checks: ledger schema; rows sorted ascending with no duplicate dates; ``coverage`` matches rows;
    ``policy`` equals the const-pinned policy; boundary is comparison-only / non-production / lane
    not under ``result/a_short``; (with ``validate_rows``) each row valid against the daily schema.
    This is NOT the sanctioned write/use gate — call :func:`validate_ledger` for that, which also
    enforces PIT (``as_of``) and trading-day contiguity, both of which need run context.
    """
    import jsonschema  # runtime validation dep; local import keeps planning logic dep-free

    errs = []
    schema_path = ROOT / "schemas" / "a_short_regime_daily_ledger.schema.json"
    try:
        jsonschema.validate(ledger, json.loads(schema_path.read_text(encoding="utf-8")))
    except jsonschema.ValidationError as exc:
        errs.append(f"schema: {exc.message}")

    rows = ledger.get("rows") or []
    dates = []
    row_revisions = []
    for row in rows:
        try:
            dates.append(_row_observation_date(row))
            row_revisions.append(_row_revision(row))
        except ValueError as exc:
            errs.append(str(exc))
            dates.append(str(row.get("as_of")))
            row_revisions.append(None)
    if dates != sorted(dates):
        errs.append("rows are not sorted ascending by observed_data_through")
    if len(dates) != len(set(dates)):
        errs.append("rows contain duplicate observed_data_through dates")

    ledger_revision = ledger.get("run_revision_id")
    if ledger_revision not in (None, ""):
        try:
            ledger_revision = validate_run_revision_id(str(ledger_revision))
            if any(revision != ledger_revision for revision in row_revisions):
                errs.append("ledger rows do not all match run_revision_id")
        except ValueError as exc:
            errs.append(str(exc))
    elif any(revision is not None for revision in row_revisions):
        errs.append("revision-scoped rows require ledger run_revision_id")

    cov = ledger.get("coverage") or {}
    exp_start = dates[0] if dates else None
    exp_end = dates[-1] if dates else None
    if cov.get("start") != exp_start or cov.get("end") != exp_end or cov.get("n") != len(dates):
        errs.append(f"coverage {cov} does not match rows (start={exp_start}, end={exp_end}, n={len(dates)})")

    if ledger.get("policy") != LEDGER_POLICY:
        errs.append("policy does not match the const-pinned LEDGER_POLICY")

    b = ledger.get("boundary") or {}
    if not (b.get("production") is False and b.get("comparison_only") is True
            and b.get("drives_phase5_risk_posture") is False):
        errs.append("boundary is not comparison-only / non-production")
    if str(b.get("lane_root", "")).replace("\\", "/").startswith("result/a_short"):
        errs.append("lane_root must be the guard-safe research lane, never result/a_short")

    if validate_rows and rows:
        daily_schema = json.loads(DAILY_SCHEMA_PATH.read_text(encoding="utf-8"))
        for r in rows:
            row_errs = []
            try:
                jsonschema.validate(r, daily_schema)
            except jsonschema.ValidationError as exc:
                row_errs.append(f"row {r.get('as_of')} invalid: {exc.message}")
            row_errs.extend(daily_row_semantic_errors(r))   # finite / net_limit / real-date
            if row_errs:
                errs.extend(row_errs)
                break

    if errs:
        raise ValueError("invalid ledger envelope: " + "; ".join(errs))
    return True


def _validate_ledger_core(ledger: dict, *, as_of: str, trade_calendar: Iterable[str],
                          require_fresh: bool) -> bool:
    """Shared ledger gate body; raise ``ValueError`` on any violation. ``require_fresh`` toggles the
    freshness check (the only difference between the append pre-gate and the current/read gate)."""
    errs = []
    if not _is_canonical_date(as_of):
        errs.append(f"as_of {as_of!r} is not a real YYYYMMDD date")
    cal_entries = [str(d) for d in trade_calendar]   # materialize ONCE (calendar may be a generator)
    bad_cal = [d for d in cal_entries if not _is_canonical_date(d)]
    if bad_cal:
        errs.append(f"trade_calendar has non-date entries: {sorted(bad_cal)[:3]}")
    try:
        validate_ledger_envelope(ledger)   # rows always validated — no bypass on the sanctioned gates
    except ValueError as exc:
        errs.append(str(exc))

    rows = ledger.get("rows") or []
    dates = [str(r.get("as_of")) for r in rows]

    future = [d for d in dates if d > str(as_of)]
    if future:
        errs.append(f"rows dated after as_of {as_of} (look-ahead): {future[:3]}")

    cal = sorted(set(cal_entries))
    if dates:
        if not set(dates).issubset(set(cal)):
            errs.append("ledger contains dates not on the trade calendar")
        else:
            span = [d for d in cal if dates[0] <= d <= dates[-1]]
            if span != dates:
                errs.append("ledger is not a contiguous run of trading days (gap within coverage)")
        if require_fresh:
            # A contiguous PIT ledger can still be STALE (last row earlier than the latest trading
            # day <= as_of). Reading the 252d window for this as_of off a stale ledger would classify
            # an old row against a newer run date — a feature-date/run-date mismatch that poisons the
            # evidence clock. (Empty ledger = pre-bootstrap, allowed; readers require non-empty.)
            elig = [d for d in cal if d <= str(as_of)]
            latest = elig[-1] if elig else None
            if latest is not None and dates[-1] != latest:
                errs.append(f"stale ledger: last row {dates[-1]} != latest trading day <= as_of ({latest})")

    if errs:
        raise ValueError("invalid ledger: " + "; ".join(errs))
    return True


def validate_ledger_for_append(ledger: dict, *, as_of: str, trade_calendar: Iterable[str]) -> bool:
    """Pre-append historical-integrity gate (everything EXCEPT freshness); raise ``ValueError``.

    Call on the EXISTING ledger BEFORE :func:`plan_append` / :func:`merge_rows`. It enforces schema +
    row semantics + canonical dates + sorted/coverage/policy/boundary + no duplicates + calendar
    subset + contiguity within existing coverage + no row ``> as_of`` — but **NOT freshness**, because
    the normal weekly pre-append ledger legitimately ends at the *previous* run date (not yet current
    through ``as_of``). This is the safe-and-usable historical gate `plan_append` relies on (it plans
    only forward from ``max(existing)`` and does not repair internal gaps, so the caller must reject a
    gappy existing ledger here first — fail-closed).
    """
    return _validate_ledger_core(ledger, as_of=as_of, trade_calendar=trade_calendar, require_fresh=False)


def validate_ledger(ledger: dict, *, as_of: str, trade_calendar: Iterable[str]) -> bool:
    """The SANCTIONED current / read-write final gate; raise ``ValueError`` on any violation.

    ``as_of`` + ``trade_calendar`` REQUIRED; row-contract validation always on (no bypass flag).
    Everything :func:`validate_ledger_for_append` checks PLUS **freshness** — when rows are present,
    the last row equals the latest trading day ``<= as_of`` — so the ledger is current through the run
    date. Call on the MERGED ledger before writing it, and before reading it for the percentile window
    (readers must also require a non-empty ledger). An empty ledger (pre-bootstrap) passes.
    """
    return _validate_ledger_core(ledger, as_of=as_of, trade_calendar=trade_calendar, require_fresh=True)
