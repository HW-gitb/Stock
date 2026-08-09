# -*- coding: utf-8 -*-
"""Drive the whole 26-week diagnostic chain in a sandbox, so it can be read before the clock opens.

Knives 0 through 10c are all built and wired, and no run has ever taken a single
week end to end through them. Three defects found in one week — the report lines
with no consumer, the staging root that was never injected, the weekly task that
read the clock without advancing it — share one shape: every knife's own tests
were green and the assembly was dead. Opening the real clock is not reversible,
because the receipt freezes week one; this is the bench that can be run and
re-run before that happens.

**A rehearsal artifact is never diagnostic evidence.** It carries a rehearsal
epoch, its weekly reports carry a rehearsal banner, and nothing it writes may be
cited. The one gate below keeps it out of the repository entirely, which is the
same thing said in a way a reader cannot forget to honour.

Every step goes through the public entry the real weekly path uses — the store's
own freeze/commit, the real exposure writer, `fetch_next_week`,
`settle_captured_week`, `weekly_diagnostic_step`, the real report renderer and
the real splice. Nothing is reimplemented here; the point is to exercise the
seams, and a private copy of a seam proves nothing about it. No provider module
is imported: the vendor is a deterministic local fake handed in through the
parameter the fetchers already accept for it, so a rehearsal performs zero
network calls.

Two ways a week can go missing, and they are NOT the same shape — the harness
models both because a fix for one is silent about the other:

* `--starved-weeks` — the weekly act ran and the account settled, but the inputs
  never landed. The next run back-captures that week and settles it late, so it
  ends up an ordinary evaluable week and the clock catches the calendar up.
* `--skipped-weeks` — nobody ran the weekly act at all (holiday, machine off), so
  the ACCOUNT has no week for it either and nothing ever can make it evaluable.
  That is the week that becomes `no_count`, and it is the common outage in
  practice. The harness could not produce it at all until the account loop learned
  to skip too.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_decision_exposure import (  # noqa: E402
    build_decision_exposure_record,
    write_decision_exposure,
)
from engine.us_short_market_diagnostic_weekly_task import (  # noqa: E402
    splice_diagnostic_report_lines,
    weekly_diagnostic_step,
)
from engine.us_short_model_paper_portfolio import (  # noqa: E402
    DECISION_BOUNDARY,
    artifact_sha256,
    build_nav_snapshot,
    seed_portfolio_state,
    settle_decision_bundle,
)
from engine.us_short_model_paper_store import (  # noqa: E402
    commit_settlement_and_freeze_next,
    freeze_decision_bundle,
    initialize_store,
)
from engine.us_short_private_paths import ROOT as REPO_ROOT  # noqa: E402
from engine.us_short_weekly_report_renderer import render_weekly_report  # noqa: E402
from engine.us_short_market_diagnostic_weekly_producer import next_week_inputs  # noqa: E402
from runners.us_short_market_diagnostic_benchmark_fetch import (  # noqa: E402
    PACKET_FILENAME,
    week_directory as benchmark_week_directory,
)
from runners.us_short_market_diagnostic_weekly import open_clock, settle_week  # noqa: E402
from runners.us_short_market_diagnostic_weekly_fetch import (  # noqa: E402
    fetch_next_week,
    load_cash_returns,
    load_target_exposures,
    settle_captured_week,
)

REPORT_CONTRACT = ROOT / "presets" / "us_short_weekly_report_contract_20260620.json"
REHEARSAL_BANNER = "REHEARSAL — 非诊断证据"
BENCHMARKS = ("VTI", "IWB", "SPY", "QQQ")
# Enough to open a position in week one and mark it every week after, which is
# what makes the strategy's weekly return move at all.
TICKER = "ABC"
SHARES = 100


class RehearsalError(Exception):
    """The rehearsal cannot run in the place, or on the dates, it was given."""


# ---------------------------------------------------------------------------
# The one gate
# ---------------------------------------------------------------------------

def rehearsal_root(root: str | Path) -> Path:
    """The sandbox must be an absolute path outside the repository, and empty.

    Every default root this chain would otherwise reach — the diagnostic store,
    the weekly inputs root, the model-paper store, ``runs_private`` and the
    public scorecard root — lives inside the repository, so "outside the repo"
    excludes all of them at once rather than listing five things to keep in sync.
    A non-empty root is refused instead of cleared: deleting an operator's
    directory to make room for a rehearsal is not this tool's decision.
    """

    path = Path(root)
    if not path.is_absolute():
        raise RehearsalError("--root must be an absolute path")
    resolved = path.resolve()
    repo = Path(REPO_ROOT).resolve()
    if resolved == repo or repo in resolved.parents:
        raise RehearsalError(
            "--root is inside the repository; a rehearsal must not be able to reach a real root"
        )
    if resolved.exists() and any(resolved.iterdir()):
        raise RehearsalError("--root is not empty; point at a fresh directory or clear it yourself")
    return resolved


# ---------------------------------------------------------------------------
# Deterministic local vendors (no provider module is imported anywhere here)
# ---------------------------------------------------------------------------

class _Row(dict):
    """Just enough of a pandas row for the fetcher's two accesses."""


class _Frame:
    def __init__(self, rows: list[tuple[date, _Row]]) -> None:
        self._rows = rows
        self.empty = not rows

    def iterrows(self):
        return iter(self._rows)


class _Ticker:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    def history(self, *, start: str, end: str, auto_adjust: bool, actions: bool, repair: bool):
        if auto_adjust:
            # The real fetcher pins this to False on purpose; a rehearsal that
            # accepted True would be rehearsing a different price basis.
            raise RehearsalError("the rehearsal vendor is only valid with auto_adjust=False")
        first = datetime.strptime(start, "%Y-%m-%d").date()
        last = datetime.strptime(end, "%Y-%m-%d").date()
        rows: list[tuple[date, _Row]] = []
        day = first
        while day < last:
            if day.weekday() < 5:
                rows.append((day, _Row(Close=_benchmark_close(self.symbol, day),
                                       Dividends=0.0, **{"Stock Splits": 0.0}, **{"Capital Gains": 0.0})))
            day += timedelta(days=1)
        return _Frame(rows)


class _Vendor:
    """The shape `fetch_symbol_bars` asks of yfinance, and nothing else."""

    @staticmethod
    def Ticker(symbol: str) -> _Ticker:  # noqa: N802 - the vendor's own name
        return _Ticker(symbol)


def _benchmark_close(symbol: str, day: date) -> float:
    """A closed-form price: same inputs, same number, on every machine and run."""

    base = 100.0 + 10.0 * BENCHMARKS.index(symbol) if symbol in BENCHMARKS else 100.0
    drift = (day.toordinal() % 23) - 11
    return round(base + drift * 0.25, 6)


def _cash_opener(call_log: list[str]):
    def opener(url: str) -> bytes:
        call_log.append(url)
        start = url.split("observation_start=")[1].split("&")[0]
        end = url.split("observation_end=")[1].split("&")[0]
        first = datetime.strptime(start, "%Y-%m-%d").date()
        last = datetime.strptime(end, "%Y-%m-%d").date()
        rows = []
        day = first
        while day <= last:
            if day.weekday() < 5:
                rows.append({
                    "realtime_start": (day + timedelta(days=1)).strftime("%Y-%m-%d"),
                    "realtime_end": "9999-12-31",
                    "date": day.strftime("%Y-%m-%d"),
                    "value": "3.87",
                })
            day += timedelta(days=1)
        return json.dumps({"observations": rows}).encode("utf-8")

    return opener


# ---------------------------------------------------------------------------
# Model-paper weeks
# ---------------------------------------------------------------------------

def _order(action: str) -> dict:
    opening = action == "建仓"
    return {
        "ticker": TICKER,
        "final_action": action,
        "recommended_action_shares": SHARES if opening else None,
        "order_type": "pullback_limit" if opening else None,
        "order_expiry": "first_regular_session_only" if opening else None,
        "valid_entry_low": 9.8 if opening else None,
        "valid_entry_high": 10.2 if opening else None,
        "limit_order_price": 10.0 if opening else None,
        "breakout_entry_price": None,
        "stop_clear_price": 9.0,
        "take_profit_reduce_price": 11.0,
        "take_profit_exit_price": 12.0,
        "event_clear_reference_price": None,
        "event_source_ref_sha256": None,
    }


def _decision_bundle(prior_state: dict, decision_date: str, orders: list[dict]) -> dict:
    return {
        "schema_name": "us_short_model_paper_decision_bundle",
        "schema_version": "1.0.0",
        "decision_date": decision_date,
        "price_basis_date": prior_state["as_of"],
        "created_at": f"{_iso(decision_date)}T08:00:00Z",
        "prior_state_sha256": artifact_sha256(prior_state),
        "supersedes_sha256": None,
        "source_binding": {
            "source_kind": "us_short_weekly_decision_artifact",
            "source_as_of": decision_date,
            "decision_source_sha256": "d" * 64,
        },
        "cost_prior": {"commission_fee": 0.001, "slippage_bps": 0.0, "spread_cost": 0.0},
        "orders": orders,
        "boundary": dict(DECISION_BOUNDARY),
    }


def _price_packet(decision_date: str, valuation_date: str, close: float) -> dict:
    # The intraday range has to actually reach the pullback limit, or week one's
    # 建仓 never fills and every later 持有 row refers to a position that is not there.
    bar = {"date": decision_date, "open": close, "high": round(close + 0.5, 6),
           "low": round(close - 0.5, 6), "close": close}
    last = {"date": valuation_date, "open": close, "high": round(close + 0.5, 6),
            "low": round(close - 0.5, 6), "close": close}
    return {
        "as_of": valuation_date,
        "session_scope": "RTH",
        "adjustment_mode": "split_dividend_adjusted",
        "observed_at": f"{_iso(valuation_date)}T22:00:00Z",
        "source_sha256": "b" * 64,
        "paper_evaluation": {
            "paper_evaluable": True,
            "status": "evaluable",
            "degradation_reasons": [],
            "source_sha256": "c" * 64,
        },
        "bars_by_ticker": {TICKER: [bar, last]},
    }


def _digest(label: str) -> str:
    """A stable 64-hex digest per label, so two rehearsals of the same week agree."""

    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _total_return_sidecar(packet: dict, calendar_week_index: int) -> dict:
    """A Knife 5 sidecar for the week the packet just captured.

    Built FROM the packet rather than beside it: the adapter reconciles the two,
    and a sidecar carrying its own idea of the dates would be testing the
    rehearsal's bookkeeping instead of the seam. Every ETF gets one dividend
    event, which is what makes the week `total_return_evaluable` and therefore
    the only way anything in this repository can print v1.1's full identity.
    """

    week = next(row for row in packet["weeks"] if row["calendar_week_index"] == calendar_week_index)
    refs = {_digest("sidecar-root")}
    rows: dict[str, Any] = {}
    for symbol in BENCHMARKS:
        observation = week["benchmarks"][symbol]
        binding = {
            "adjusted_price_sha256": _digest(f"adjusted-{symbol}-{calendar_week_index}"),
            "unadjusted_price_sha256": _digest(f"unadjusted-{symbol}-{calendar_week_index}"),
            "dividend_sha256": _digest(f"dividend-{symbol}-{calendar_week_index}"),
            "split_sha256": _digest(f"split-{symbol}-{calendar_week_index}"),
            "raw_capture_sha256": _digest(f"raw-{symbol}-{calendar_week_index}"),
            "source_date": observation["price_date"],
            "observed_at": f"{_iso(observation['price_date'])}T23:00:00Z",
        }
        events = [{
            "ex_date": observation["price_date"],
            "cash_amount": "0.100000",
            "split_adjustment_factor": 1.0,
            "split_adjusted_cash_amount": "0.100000",
            "source_sha256": _digest(f"event-{symbol}-{calendar_week_index}"),
        }]
        refs.update(value for value in binding.values() if isinstance(value, str) and len(value) == 64)
        refs.update(event["source_sha256"] for event in events)
        rows[symbol] = {
            "prior_price_date": observation["prior_price_date"],
            "price_date": observation["price_date"],
            "dividend_events": events,
            "split_events": [],
            "coverage": {
                "pagination_complete": True,
                "dividend_complete": True,
                "split_complete": True,
                "adjusted_unadjusted_reconciled": True,
            },
            "source_binding": binding,
            "data_quality_reasons": [],
        }
    return {
        "schema_name": "us_short_market_diagnostic_etf_total_return_sidecar",
        "schema_version": "1.0.0",
        "window_id": packet["window_id"],
        "diagnostic_epoch": packet["diagnostic_epoch"],
        "price_basis": packet["price_basis"],
        "benchmark_symbols": list(BENCHMARKS),
        "weeks": [{
            "calendar_week_index": calendar_week_index,
            "valuation_date": week["valuation_date"],
            "benchmarks": rows,
        }],
        "source_refs": sorted(refs),
        "boundary": {
            "sidecar_only": True,
            "provider_selection_performed": False,
            "provider_call_performed_by_reconciler": False,
            "account_write_performed": False,
            "paper_gate_upgrade_performed": False,
            "ship_gate_or_production_authorized": False,
        },
    }


def _strategy_close(week: int) -> float:
    """Deterministic and two-sided, so the strategy is not a flat line."""

    return round(10.0 + 0.05 * (((week * 5) % 9) - 4), 6)


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def _date8(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def _shift(value: str, days: int) -> str:
    return (_date8(value) + timedelta(days=days)).strftime("%Y%m%d")


def _weekly_dates(first_decision_date: str, weeks: int) -> list[dict[str, str]]:
    """The three dates each week needs, in the order the consumer requires them.

    ``settlement <= valuation <= decision`` is the diagnostic's own rule, so the
    paper week a diagnostic week wraps is the previous Monday and it is valued on
    the Friday before this Monday.
    """

    if _date8(first_decision_date).weekday() != 0:
        raise RehearsalError("--first-decision-date must be a Monday; the receipt refuses a weekend")
    return [
        {
            "decision_date": _shift(first_decision_date, 7 * index),
            "paper_decision_date": _shift(first_decision_date, 7 * index - 7),
            "valuation_date": _shift(first_decision_date, 7 * index - 3),
        }
        for index in range(weeks)
    ]


# ---------------------------------------------------------------------------
# The report the operator reads
# ---------------------------------------------------------------------------

def _report_data(decision_date: str, price_basis_date: str) -> dict:
    sections = json.loads(REPORT_CONTRACT.read_text(encoding="utf-8"))["sections"]
    body = {str(index): [f"(rehearsal {index})"] for index in range(1, len(sections) + 1)}
    # The banner is section CONTENT, not a new banner element: the renderer's
    # frozen contract is not something a rehearsal gets to extend.
    body["1"] = [REHEARSAL_BANNER, f"(rehearsal run for {decision_date})"]
    return {
        "banner": {
            "price_clock": {
                "price_data_through": price_basis_date,
                "news_window_through": price_basis_date,
                "session_scope": "RTH",
                "decision_date": decision_date,
            }
        },
        "lifecycle_reminder_count": {"section_1": 0, "section_12": 0},
        "sections": body,
    }


# ---------------------------------------------------------------------------
# The rehearsal itself
# ---------------------------------------------------------------------------

def _settle_one_week(
    *,
    index: int,
    week: dict[str, str],
    diag: Path,
    paper: Path,
    inputs: Path,
    public: Path,
    packet_path: Path,
    with_total_return_sidecar: bool,
) -> dict[str, Any]:
    """Settle this week through whichever entry the flag selects."""

    if (
        with_total_return_sidecar
        and packet_path.is_file()
        and next_week_inputs(diag, as_of_date=week["decision_date"])["calendar_week_index"] == index
    ):
        # The manual entry selects a complete synthetic sidecar; the one-click
        # entry now auto-binds the producer's same-week sidecar; default-off
        # keeps its missing-key, price-only result visible. A starved week has no
        # packet to reconcile against, so it falls through to the one-click entry
        # and gets that entry's honest waiting status instead. So does a run where
        # the clock is behind: only the one-click entry writes off the weeks that
        # ended without inputs, and the manual entry would refuse the gap.
        sidecar_path = packet_path.parent / "total_return_sidecar.json"
        if not sidecar_path.exists():
            sidecar_path.write_text(
                json.dumps(
                    _total_return_sidecar(
                        json.loads(packet_path.read_text(encoding="utf-8")), index
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        return settle_week(
            model_paper_root=paper,
            benchmark_packet_path=packet_path,
            root=diag,
            total_return_sidecar_path=sidecar_path,
            output_root=public,
            as_of_date=week["decision_date"],
        )
    return settle_captured_week(
        root=diag,
        model_paper_root=paper,
        inputs_root=inputs,
        output_root=public,
        as_of_date=week["decision_date"],
    )


def run_rehearsal(
    *,
    root: str | Path,
    first_decision_date: str,
    weeks: int = 26,
    starved_weeks: tuple[int, ...] = (),
    skipped_weeks: tuple[int, ...] = (),
    with_total_return_sidecar: bool = False,
    epoch_suffix: int = 1,
) -> dict[str, Any]:
    """Take ``weeks`` consecutive weeks through the whole chain and report what happened."""

    if not isinstance(weeks, int) or isinstance(weeks, bool) or weeks < 1:
        raise RehearsalError("--weeks must be a positive integer")
    sandbox = rehearsal_root(root)
    calendar = _weekly_dates(first_decision_date, weeks)
    starved = set(starved_weeks)
    skipped = set(skipped_weeks)
    inside = set(range(1, weeks + 1))
    if (starved | skipped) - inside:
        raise RehearsalError("--starved-weeks/--skipped-weeks names a week outside the run")
    if starved & skipped:
        raise RehearsalError("a week cannot be both starved and skipped; they are different outages")

    diag = sandbox / "diag"
    inputs = sandbox / "inputs"
    paper = sandbox / "model_paper"
    runs = sandbox / "runs"
    public = sandbox / "public"
    reports = sandbox / "reports"
    for directory in (diag, inputs, paper, runs, public, reports):
        directory.mkdir(parents=True, exist_ok=True)

    epoch = f"rehearsal-{first_decision_date}-{epoch_suffix}"
    # Through the operator entry, not around it. `open_clock` is the act being
    # rehearsed, so reaching past it to the receipt writer would rehearse a path
    # nobody uses — and would put this module inside the diagnostic store's
    # authorization surface, where twenty exemptions would say less than the gate
    # above already says. The receipt schema pins the issuer to the one role that
    # may open a real clock, so the rehearsal says what it is in the text and
    # relies on the epoch and the sandbox gate to keep the two apart.
    notification = sandbox / "rehearsal_notification.txt"
    notification.write_text(
        "REHEARSAL sandbox clock; this is not a design-completion notice.", encoding="utf-8"
    )
    open_clock(
        confirm_design_complete=True,
        notification_path=notification,
        issued_at=f"{_iso(_shift(first_decision_date, -3))}T00:00:00+00:00",
        diagnostic_epoch=epoch,
        first_decision_date=first_decision_date,
        root=diag,
    )

    seed_as_of = _shift(first_decision_date, -10)
    state = seed_portfolio_state(seed_as_of)
    nav = build_nav_snapshot(
        state,
        {"paper_evaluable": False, "status": "not_evaluable",
         "degradation_reasons": ["seed_state"], "source_sha256": None},
    )
    initialize_store(paper, state, nav)
    bundle = _decision_bundle(state, calendar[0]["paper_decision_date"], [_order("建仓")])
    freeze_decision_bundle(paper, bundle)

    provider_calls: list[str] = []
    provider_call_count = 0
    outcomes: list[dict[str, Any]] = []
    for index, week in enumerate(calendar, start=1):
        if index in skipped:
            # Nobody ran the weekly act at all. The account does not settle either,
            # nothing is captured, and no weekly report is produced — the frozen
            # decision simply stays pending and matures a week later, which is what
            # a skipped week really does. Settling the account here anyway is why
            # this harness could not show the outage at all before.
            outcomes.append({
                "calendar_week_index": index,
                "decision_date": week["decision_date"],
                "fetch_status": "not_run",
                "settle_status": "not_run",
                "clock_status": None,
                "v1_1_status": None,
                "publication": None,
                "problem": None,
                "report_path": None,
                "report_lines_delivered": False,
                "starved": False,
                "skipped": True,
                "no_count_weeks": [],
            })
            continue
        # Off the PENDING bundle, not off this week's calendar slot: after a skipped
        # week the decision that is still pending is the older one, and it matures
        # now. The store requires the packet's first bar to be that bundle's own
        # decision date, which is also what makes the account visibly one decision
        # staler after an outage — exactly what a skipped week does in reality.
        packet = _price_packet(bundle["decision_date"], week["valuation_date"], _strategy_close(index))
        settlement, next_state, next_nav = settle_decision_bundle(
            state, bundle, packet, week["valuation_date"]
        )
        # The next decision belongs to the NEXT calendar slot, not to the stale
        # bundle plus seven days: a skipped week's decision day simply never
        # happened, and the store refuses a decision dated before its own price
        # basis anyway.
        following = _decision_bundle(
            next_state,
            _shift(week["paper_decision_date"], 7),
            [_order("持有")],
        )
        commit_settlement_and_freeze_next(paper, bundle, settlement, next_state, next_nav, following)
        state, bundle = next_state, following

        fetched: dict[str, Any] = {"status": "starved"}
        if index not in starved:
            # Through `fetch_next_week`, not around it: the one-click path derives
            # every date from the two stores, and it is the step that back-captures
            # a week whose prices never landed. Starving a week here is simply not
            # running that step, while the account carries on as usual.
            fetched = fetch_next_week(
                confirm_user_authorization=True,
                root=diag,
                model_paper_root=paper,
                inputs_root=inputs,
                as_of_date=week["decision_date"],
                benchmark_module=_Vendor(),
                cash_opener=_cash_opener(provider_calls),
                cash_api_key="rehearsal-not-a-real-key",
            )
            provider_call_count += int(fetched.get("provider_calls") or 0)

        write_decision_exposure(
            build_decision_exposure_record(
                decision_date=week["decision_date"],
                account_state={
                    "us_short_bucket_capital": 100000.0,
                    "us_short_available_cash": float(state["cash"]),
                },
                regime={"market_risk_regime": "neutral", "position_cap": 0.8},
                rows=[],
                portfolio_capacity={
                    "existing_positions": [
                        {"shares": int(position["shares"]),
                         "mark_price": float(position["mark_price"])}
                        for position in state["positions"]
                    ]
                },
            ),
            runs_private_root=runs,
        )

        packet_path = benchmark_week_directory(week["decision_date"], inputs_root=inputs) / PACKET_FILENAME
        problem: str | None = None
        settled: dict[str, Any] = {"status": "failed"}
        try:
            settled = _settle_one_week(
                index=index,
                week=week,
                diag=diag,
                paper=paper,
                inputs=inputs,
                public=public,
                packet_path=packet_path,
                with_total_return_sidecar=with_total_return_sidecar,
            )
        except Exception as exc:  # noqa: BLE001 — mirrors the capstone stage's total adapter
            # The real weekly path wraps exactly this call in a total adapter, so a
            # rehearsal that dies here would be showing a failure mode the operator
            # will never see. It reports the same thing the capstone reports — a
            # failed week with a reason — and carries on to the next one, which is
            # how `A-MISSED-WEEK-JAMS-THE-CLOCK-FOREVER` becomes visible as the
            # every-week-failed, clock-frozen picture it actually is.
            problem = f"{type(exc).__name__}: {exc}"
        step = weekly_diagnostic_step(
            root=diag,
            as_of_date=week["decision_date"],
            cash_return_by_week=load_cash_returns(root=diag, inputs_root=inputs,
                                                  as_of_date=week["decision_date"]),
            target_exposure_by_week=load_target_exposures(root=diag, runs_private_root=runs,
                                                          as_of_date=week["decision_date"]),
        )
        report_path = reports / week["decision_date"] / "weekly_report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            render_weekly_report(_report_data(week["decision_date"], week["valuation_date"])),
            encoding="utf-8",
        )
        delivered = splice_diagnostic_report_lines(report_path, step["report_lines"])
        outcomes.append({
            "calendar_week_index": index,
            "decision_date": week["decision_date"],
            "fetch_status": fetched["status"],
            "settle_status": settled["status"],
            "clock_status": step["status"],
            "v1_1_status": step.get("v1_1_status"),
            "publication": settled.get("publication"),
            "problem": problem,
            "report_path": str(report_path),
            "report_lines_delivered": delivered,
            "starved": index in starved,
            "skipped": False,
            "settled_weeks": settled.get("settled_weeks") or [],
            # Which earlier weeks this run wrote off because they ended without
            # their inputs. Empty in every week of a healthy run.
            "no_count_weeks": settled.get("no_count_weeks") or [],
        })

    return {
        "root": str(sandbox),
        "diagnostic_epoch": epoch,
        "weeks": outcomes,
        "provider_calls": provider_call_count,
        "boundary": {
            "rehearsal_only": True,
            "counts_ship_gate": False,
            "diagnostic_evidence": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="absolute sandbox path OUTSIDE the repository")
    parser.add_argument("--first-decision-date", required=True, help="YYYYMMDD, a Monday")
    parser.add_argument("--weeks", type=int, default=26)
    parser.add_argument("--starved-weeks", default="",
                        help="comma-separated weeks whose INPUTS never landed (account still settles)")
    parser.add_argument("--skipped-weeks", default="",
                        help="comma-separated weeks nobody ran at all (account does not settle either)")
    parser.add_argument("--with-total-return-sidecar", action="store_true",
                        help="settle through the manual entry with a synthesized Knife 5 sidecar, so v1.1 "
                             "prints raw_excess = exposure_effect + active_system_effect")
    args = parser.parse_args(argv)

    def _weeks(text: str) -> tuple[int, ...]:
        return tuple(int(part) for part in text.split(",") if part.strip())

    try:
        summary = run_rehearsal(
            root=args.root,
            first_decision_date=args.first_decision_date,
            weeks=args.weeks,
            starved_weeks=_weeks(args.starved_weeks),
            skipped_weeks=_weeks(args.skipped_weeks),
            with_total_return_sidecar=args.with_total_return_sidecar,
        )
    except RehearsalError as exc:
        print(f"[rehearsal] refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


__all__ = ["RehearsalError", "rehearsal_root", "run_rehearsal"]


if __name__ == "__main__":
    raise SystemExit(main())
