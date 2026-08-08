"""Knife 10b: the weekly act that actually advances the 26-week clock.

Knife 7b hung the diagnostic track off the weekly capstone, but only as a READER:
the stage called ``weekly_diagnostic_step``, which reports what the store already
holds and never adds to it. So a clock could be opened and then sit at week zero
for ever while the weekly one-click ran happily every week.

This module is the missing weekly act. It derives the next week's identity from
the two stores rather than from anything a caller passes, captures that week's
benchmark prices and cash rate, settles the week, and lets the engine publish a
scorecard when a window closes.

Where the dates come from, and why not from the caller
------------------------------------------------------
Nothing here takes a decision date as an argument. The diagnostic store says
which INDEX is next; the model-paper head says which week actually settled and
what date it was valued on. A caller that could name the dates could also name a
week the clock is not expecting, which is exactly the shape Knife 7b removed from
``build_next_weekly_record``.

Week one has no previous diagnostic week to price the benchmarks from, so it
measures from the account's own seeding date. The strategy's first return is
measured from seeding too, so both sides start together — which is the whole
point of an exposure-matched comparison.

What happens when a week is missed
----------------------------------
A week whose benchmark inputs never landed used to jam this clock permanently:
the account went on settling every week, so the head's valuation ran past the
decision date of the week the diagnostic store was still waiting for, and
``settlement <= valuation <= decision`` could never hold again. Every later week
reported ``failed`` and the calendar-week count sat frozen for ever.

Three things together make that self-heal, and all three are needed:

* the week's paper dates come from the paper week it WRAPS, found by walking back
  through the account's own settled weeks — so a stuck week can still be
  described at all;
* the fetch step captures every week that is due, not only the stuck one, so the
  current week's prices land in the same run — capture only the stuck week and
  the clock heals one week per week and never catches the calendar up;
* the settle step writes off a week that ENDED without being recorded as
  ``no_count``, which keeps it in the 26-week denominator instead of pushing the
  boundary out (design section 3, section 12.8 duty 3).

A week is over only once the next week's decision day has arrived, so data that
turns up a few days late is still settled as the ordinary evaluable week it is.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_market_diagnostic_lifecycle import (  # noqa: E402
    DEFAULT_ROOT,
    MarketDiagnosticLifecycleError,
    load_settled_weekly_records,
)
from engine.us_short_market_diagnostic_local_adapter import (  # noqa: E402
    LocalMarketDiagnosticAdapterError,
    load_model_paper_week,
)
from engine.us_short_market_diagnostic_weekly_producer import (  # noqa: E402
    MarketDiagnosticWeeklyProducerError,
    diagnostic_store_state,
    next_week_inputs,
    settle_missed_week,
)
from engine.us_short_decision_exposure import (  # noqa: E402
    DecisionExposureError,
    load_decision_exposure,
)
from engine.us_short_model_paper_portfolio import artifact_sha256  # noqa: E402
from engine.us_short_model_paper_store import ModelPaperStoreError, load_head  # noqa: E402
from runners.us_short_market_diagnostic_benchmark_fetch import (  # noqa: E402
    DEFAULT_INPUTS_ROOT,
    PACKET_FILENAME,
    BenchmarkFetchError,
    capture_week,
    week_directory as benchmark_week_directory,
)
from runners.us_short_market_diagnostic_cash_fetch import (  # noqa: E402
    OBSERVATION_FILENAME,
    CashFetchError,
    capture_cash_week,
    week_directory as cash_week_directory,
)
from runners.us_short_market_diagnostic_weekly import (  # noqa: E402
    DEFAULT_PUBLIC_ROOT,
    MarketDiagnosticWeeklyRunnerError,
    settle_week,
)

# The model-paper store lives beside the diagnostic store under the same private
# parent, and both are supplied by their own modules rather than named here.
DEFAULT_MODEL_PAPER_ROOT = ROOT / "state" / "us_short" / "model_paper_private"

DORMANT_STATES = {"not_started"}
WEEK = timedelta(days=7)


class WeeklyAdvanceError(Exception):
    """The week cannot be advanced."""


class WeeklyAdvanceGap(WeeklyAdvanceError):
    """The ACCOUNT has no week here — an absence, not a fault.

    The distinction is load-bearing and belongs at the raise site rather than in a
    caller reading messages. Only an absence may be turned into a spent calendar
    week: a `no_count` record is immutable, so laundering a fault into one burns a
    week of the 26 and stamps it with a reason that is not true, and repairing the
    fault afterwards cannot give the week back. Everything that is a fault —
    an artifact that will not parse, three dates that contradict each other —
    raises plain ``WeeklyAdvanceError`` and must travel up as one.
    """


class WeeklyAdvanceNotReady(WeeklyAdvanceGap):
    """Nothing is wrong; the account simply has not produced a new week yet.

    Kept separate because the caller turns it into a WAITING line rather than a
    fault. For most of any week this is the ordinary answer, and an operator who
    is shown "failed" every time stops reading the word — the same lesson the
    fresh-versus-broken clock states already cost this track once.
    """


class WeeklyAdvanceNoPaperWeek(WeeklyAdvanceGap):
    """The account settled no week this diagnostic week could ever wrap.

    Also an absence: nothing will ever make the week evaluable, so it is the one
    refusal besides ``WeeklyAdvanceNotReady`` that may become a ``no_count`` week.
    """


def _date8(value: str):
    return datetime.strptime(value, "%Y%m%d").date()


def _week_is_over(decision_date: str, as_of_date: str | None) -> bool:
    """Whether the NEXT week's decision day has arrived, which is when this one is over.

    The whole self-heal hangs off this one comparison, and it is deliberately the
    latest moment that is still honest: inputs that turn up a day or three late
    are still this week's inputs, so nothing may be written off until the week
    after it has begun. With no ``as_of_date`` there is no clock to judge by and
    no week is ever over — a caller that did not say when it is may not spend
    calendar weeks.
    """

    if as_of_date is None:
        return False
    return _date8(as_of_date) >= _date8(decision_date) + WEEK


def _account_has_moved_past(decision_date: str, head: Mapping[str, Any]) -> bool:
    """Whether the ACCOUNT itself has lived through this diagnostic week.

    The second half of the kill rule, and the half that cannot be supplied by a
    caller. ``as_of_date`` only says what day the caller believes it is; this says
    the model-paper account has actually valued a day after this week's decision
    date, which is the only evidence in the system that the week really is behind
    us. Requiring both is what lets a week the account never settled be written
    off at all, and what stops a far-future ``as_of`` from burning weeks that are
    still live — the account cannot have moved past a week that has not happened.
    """

    return head["current_state"]["as_of"] > decision_date


def _head(model_paper_root: str | Path) -> dict[str, Any]:
    try:
        head = load_head(model_paper_root)
    except ModelPaperStoreError as exc:
        raise WeeklyAdvanceError(f"the model-paper store cannot be read: {exc}") from exc
    if head["last_settlement"] is None:
        raise WeeklyAdvanceNotReady("the model-paper account has not settled a week yet")
    return head


def _settled_paper_week_dates(model_paper_root: str | Path, not_after: str) -> list[str]:
    """The account's settled weeks, newest first, bounded by the head's own last one.

    Bounded rather than listed raw: the store is explicit that a crash can leave
    an unreferenced week behind, and those sit AFTER the head. A directory the
    head has not adopted is not a settled week.
    """

    weeks = Path(model_paper_root) / "weeks"
    if not weeks.is_dir():
        return []
    return sorted(
        (
            child.name
            for child in weeks.iterdir()
            if child.is_dir()
            and (child / "settlement.json").is_file()
            and child.name <= not_after
        ),
        reverse=True,
    )


def _paper_week_wrapped_by(
    decision_date: str,
    *,
    model_paper_root: str | Path,
    head: Mapping[str, Any],
    as_of_date: str | None,
) -> tuple[str, str]:
    """The settled paper week this diagnostic week wraps: its decision and valuation dates.

    The head is the fast path and, while the clock keeps up, the only one taken.
    It stops being the answer the moment a diagnostic week is missed: the account
    goes on settling weekly, so the head's valuation runs past the decision date
    of the week the diagnostic store is still waiting for, and
    ``settlement <= valuation <= decision`` can then never hold again — which is
    exactly how one absent price packet used to jam this clock for good. Walking
    back through the account's own settled weeks is what lets the stuck week be
    described instead.
    """

    settlement_decision_date = head["last_settlement"]["decision_date"]
    valuation_date = head["current_state"]["as_of"]
    if valuation_date <= decision_date:
        return settlement_decision_date, valuation_date
    for candidate in _settled_paper_week_dates(model_paper_root, settlement_decision_date):
        try:
            week = load_model_paper_week(model_paper_root, candidate, as_of_date=as_of_date)
        except LocalMarketDiagnosticAdapterError as exc:
            # An unreadable week the head has adopted is a fault, not a gap: it
            # must not be stepped over on the way to an older one that happens to
            # fit, because that would silently place this week against the wrong
            # paper week.
            raise WeeklyAdvanceError(
                f"the settled paper week {candidate} cannot be read: {exc}"
            ) from exc
        if week["valuation_date"] <= decision_date:
            return candidate, week["valuation_date"]
    raise WeeklyAdvanceNoPaperWeek(
        f"the account has no settled week valued on or before {decision_date}, so the "
        f"diagnostic week deciding that day has no paper week to wrap"
    )


def _prior_valuation_date(
    index: int,
    *,
    root: str | Path,
    model_paper_root: str | Path,
    head: Mapping[str, Any],
    as_of_date: str | None,
) -> str:
    if index > 1:
        try:
            records = load_settled_weekly_records(root, as_of_date=as_of_date)
        except MarketDiagnosticLifecycleError as exc:
            raise WeeklyAdvanceError(f"the prior settled week cannot be read: {exc}") from exc
        prior = [record for record in records if record["calendar_week_index"] == index - 1]
        if not prior:
            raise WeeklyAdvanceError(
                f"week {index} needs week {index - 1}'s valuation date, which the store does not hold"
            )
        return prior[0]["valuation_date"]
    # Both sides start on the same day: the account's own seeding date. The head
    # carries the seed only as a path and a digest, so the date comes from the
    # seed state itself rather than from a field that is not there.
    seed = _read_json(
        Path(model_paper_root) / head["seed_state"]["relative_path"], "seed portfolio state"
    )
    seeded = seed.get("as_of")
    if not isinstance(seeded, str):
        raise WeeklyAdvanceError("the seeded account carries no as-of date to start from")
    return seeded


def _identity_for(
    index: int,
    *,
    receipt: Mapping[str, Any],
    diagnostic_epoch: str,
    model_paper_root: str | Path,
    head: Mapping[str, Any],
    prior_valuation_date: str,
    as_of_date: str | None,
) -> dict[str, Any]:
    """One diagnostic week, described from the two stores and the frozen receipt."""

    # The diagnostic week's own decision date, derived rather than accepted: week
    # one is frozen in the receipt and every later week is exactly seven days on,
    # which is the cadence the lifecycle already enforces on every write. It is
    # deliberately NOT the paper week's decision date — that one is the
    # SETTLEMENT this week wraps, and the consumer requires
    # settlement <= valuation <= decision.
    first_decision = _date8(receipt["first_calendar_week"]["decision_date"])
    decision_date = (first_decision + timedelta(days=7 * (index - 1))).strftime("%Y%m%d")
    settlement_decision_date, valuation_date = _paper_week_wrapped_by(
        decision_date, model_paper_root=model_paper_root, head=head, as_of_date=as_of_date
    )
    if not (settlement_decision_date <= valuation_date <= decision_date):
        raise WeeklyAdvanceError(
            f"week {index} does not line up: the paper week decided {settlement_decision_date} and was "
            f"valued {valuation_date}, but this diagnostic week decides {decision_date}"
        )
    if prior_valuation_date >= valuation_date:
        raise WeeklyAdvanceNotReady(
            "the model-paper account has not moved on since the last diagnostic week; "
            "there is no new week to settle"
        )
    return {
        "calendar_week_index": index,
        "diagnostic_epoch": diagnostic_epoch,
        "decision_date": decision_date,
        "settlement_decision_date": settlement_decision_date,
        "valuation_date": valuation_date,
        "prior_valuation_date": prior_valuation_date,
    }


def _unlived_week_identity(
    index: int,
    *,
    receipt: Mapping[str, Any],
    diagnostic_epoch: str,
    model_paper_root: str | Path,
    head: Mapping[str, Any],
    prior_valuation_date: str,
) -> dict[str, Any]:
    """A week the account never valued, described well enough to price the market.

    This is the week nobody ran at all — no capture, and no account settlement
    either, so there is no paper week for it and there never will be one. It still
    occupies its calendar slot (design section 3), and section 5 still wants the
    market shown, so it needs three dates.

    Its valuation date is its OWN decision date, which is the one derived answer
    available: the previous week's valuation is already taken (dates must strictly
    increase) and anything else would be arithmetic invented for the occasion.
    Read it as "the market measured up to this week's decision day" — the record
    carries ``no_count`` and ``strategy_evaluable=false``, so no reader can mistake
    it for an account valuation. The settlement anchor is the newest paper week
    the account had actually decided by then, which keeps the packet's
    ``settlement <= valuation <= decision`` ordering true of real artifacts.
    """

    first_decision = _date8(receipt["first_calendar_week"]["decision_date"])
    decision_date = (first_decision + timedelta(days=7 * (index - 1))).strftime("%Y%m%d")
    settled = [
        candidate
        for candidate in _settled_paper_week_dates(
            model_paper_root, head["last_settlement"]["decision_date"]
        )
        if candidate <= decision_date
    ]
    if not settled:
        raise WeeklyAdvanceError(
            f"the account has no settled week decided on or before {decision_date}, so the "
            f"diagnostic week deciding that day cannot even be written off"
        )
    if prior_valuation_date >= decision_date:
        raise WeeklyAdvanceError(
            f"week {index} cannot be written off: the previous diagnostic week was valued "
            f"{prior_valuation_date}, which is not before this week's decision date {decision_date}"
        )
    return {
        "calendar_week_index": index,
        "diagnostic_epoch": diagnostic_epoch,
        "decision_date": decision_date,
        "settlement_decision_date": settled[0],
        "valuation_date": decision_date,
        "prior_valuation_date": prior_valuation_date,
    }


def plan_week(
    index: int,
    *,
    receipt: Mapping[str, Any],
    diagnostic_epoch: str,
    model_paper_root: str | Path,
    head: Mapping[str, Any],
    prior_valuation_date: str,
    as_of_date: str | None,
) -> dict[str, Any]:
    """What this diagnostic week is, in the one place both weekly steps ask.

    Three answers, and the order between them is the whole repair:

    ``evaluable`` — the account settled a week this one wraps. It is settled
    normally EVEN IF it is already over, because design section 3 reserves
    ``no_count`` for weeks that *cannot* be evaluated and this one can. Writing off
    a week whose inputs are sitting on disk destroys real evidence irreversibly and
    records a reason that is not true.

    ``unlived`` — the week is over, the account has moved past it, and it settled
    no week this one could wrap. That is the common outage: nobody ran the weekly
    act at all. Nothing will ever make it evaluable, so it is written off.

    ``not_ready`` — the ordinary answer for most of any week: the account simply
    has not produced a new week yet. Only reachable while the account has NOT moved
    past this week, so it can no longer be confused with a clock that is stuck.
    """

    try:
        identity = _identity_for(
            index,
            receipt=receipt,
            diagnostic_epoch=diagnostic_epoch,
            model_paper_root=model_paper_root,
            head=head,
            prior_valuation_date=prior_valuation_date,
            as_of_date=as_of_date,
        )
    except WeeklyAdvanceGap as exc:
        # ONLY the two absences, by type rather than by reading the message. A
        # fault — an artifact that will not parse, three dates that contradict
        # each other — is a plain `WeeklyAdvanceError` and is not caught here at
        # all, so it travels up as a fault instead of being spent as a calendar
        # week. It used to be caught by `except WeeklyAdvanceError`, which turned
        # a corrupted-but-repairable account week into an immutable `no_count`
        # record whose stated reason was false.
        ready = isinstance(exc, WeeklyAdvanceNotReady)
        first_decision = _date8(receipt["first_calendar_week"]["decision_date"])
        decision_date = (first_decision + timedelta(days=7 * (index - 1))).strftime("%Y%m%d")
        if not (
            _week_is_over(decision_date, as_of_date)
            and _account_has_moved_past(decision_date, head)
        ):
            if ready:
                return {"kind": "not_ready", "reason": str(exc), "identity": None}
            raise
        return {
            "kind": "unlived",
            "reason": "no_settled_account_week_for_this_calendar_week",
            "identity": _unlived_week_identity(
                index,
                receipt=receipt,
                diagnostic_epoch=diagnostic_epoch,
                model_paper_root=model_paper_root,
                head=head,
                prior_valuation_date=prior_valuation_date,
            ),
        }
    return {"kind": "evaluable", "reason": None, "identity": identity}


def next_week_identity(
    *,
    root: str | Path = DEFAULT_ROOT,
    model_paper_root: str | Path = DEFAULT_MODEL_PAPER_ROOT,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Everything the fetchers need, all of it read out of the two stores."""

    try:
        inputs = next_week_inputs(root, as_of_date=as_of_date)
    except MarketDiagnosticWeeklyProducerError as exc:
        raise WeeklyAdvanceError(str(exc)) from exc
    # `next_week_inputs` above is one of the authorization gates: it refuses a
    # store that is not started or cannot be read, so by here the receipt exists.
    # Re-checking it would be a second door for an input the first already shut.
    receipt = diagnostic_store_state(root, as_of_date=as_of_date)["receipt"]
    head = _head(model_paper_root)
    index = inputs["calendar_week_index"]
    return _identity_for(
        index,
        receipt=receipt,
        diagnostic_epoch=inputs["diagnostic_epoch"],
        model_paper_root=model_paper_root,
        head=head,
        prior_valuation_date=_prior_valuation_date(
            index, root=root, model_paper_root=model_paper_root, head=head, as_of_date=as_of_date
        ),
        as_of_date=as_of_date,
    )


def _weeks_now_due(
    *,
    root: str | Path,
    model_paper_root: str | Path,
    as_of_date: str | None,
) -> list[dict[str, Any]]:
    """Every diagnostic week whose prices are now due, oldest first.

    Ordinarily exactly one — the week the store is waiting for. After a week was
    missed it is that stuck week AND every week since, because the current week's
    prices have to be captured in the SAME run: capture only the stuck week and
    the clock heals one week per week and never catches the calendar up, which
    pushes the 26-week boundary out by exactly the thing section 12.8 duty 3
    forbids pushing it out for.

    The list ends at the current week because a week is only added while the one
    before it is already over. A week the account never lived is included too: its
    benchmarks still have to be captured, or it cannot be written off at all.
    """

    try:
        inputs = next_week_inputs(root, as_of_date=as_of_date)
    except MarketDiagnosticWeeklyProducerError as exc:
        raise WeeklyAdvanceError(str(exc)) from exc
    receipt = diagnostic_store_state(root, as_of_date=as_of_date)["receipt"]
    head = _head(model_paper_root)
    epoch = inputs["diagnostic_epoch"]
    index = inputs["calendar_week_index"]
    shared = {
        "receipt": receipt,
        "diagnostic_epoch": epoch,
        "model_paper_root": model_paper_root,
        "head": head,
        "as_of_date": as_of_date,
    }
    first = plan_week(
        index,
        prior_valuation_date=_prior_valuation_date(
            index, root=root, model_paper_root=model_paper_root, head=head, as_of_date=as_of_date
        ),
        **shared,
    )
    if first["kind"] == "not_ready":
        raise WeeklyAdvanceNotReady(first["reason"])
    due = [first]
    while _week_is_over(due[-1]["identity"]["decision_date"], as_of_date):
        # The store holds no record for the week before this one yet, so its
        # valuation comes from the plan just derived — the same date that week's
        # record will carry.
        following = plan_week(
            due[-1]["identity"]["calendar_week_index"] + 1,
            prior_valuation_date=due[-1]["identity"]["valuation_date"],
            **shared,
        )
        if following["kind"] == "not_ready":
            # The account has not produced that week either, and it is not behind
            # us yet. Capture what is due and stop; nothing is invented for it.
            break
        due.append(following)
    return due


def fetch_next_week(
    *,
    confirm_user_authorization: bool = False,
    root: str | Path = DEFAULT_ROOT,
    model_paper_root: str | Path = DEFAULT_MODEL_PAPER_ROOT,
    inputs_root: Path = DEFAULT_INPUTS_ROOT,
    as_of_date: str | None = None,
    benchmark_module: Any | None = None,
    cash_opener: Any | None = None,
    cash_api_key: str | None = None,
) -> dict[str, Any]:
    """Capture every due week's benchmark prices and cash rate. Dormant means silent.

    Ordinarily that is one week. When the clock is behind it is the weeks it
    missed as well, so the settle step has something to project their benchmarks
    from and the current week can still settle in this same run.
    """

    state = diagnostic_store_state(root, as_of_date=as_of_date)
    if state["state"] in DORMANT_STATES:
        # Not an error and not a degradation: a clock nobody opened must cost
        # nothing at all, including zero network and zero bytes.
        return {"status": "dormant", "report_lines": []}
    if state["state"] == "broken":
        return {"status": "broken", "problem": state["problem"], "report_lines": []}

    try:
        due = _weeks_now_due(
            root=root, model_paper_root=model_paper_root, as_of_date=as_of_date
        )
    except WeeklyAdvanceNotReady as exc:
        return {"status": "waiting_for_paper_week", "reason": str(exc), "report_lines": []}
    # One log across every capture. A failure part-way through must still report
    # the requests that already went out: reporting "no provider call" after real
    # ones is a false statement about a paid boundary, which is why the count is
    # carried rather than inferred from whether this returned normally.
    attempts: list[str] = []
    benchmark: dict[str, Any] = {}
    cash: dict[str, Any] = {}
    for plan in due:
        identity = plan["identity"]
        try:
            benchmark = capture_week(
                confirm_user_authorization=confirm_user_authorization,
                call_log=attempts,
                decision_date=identity["decision_date"],
                valuation_date=identity["valuation_date"],
                prior_valuation_date=identity["prior_valuation_date"],
                settlement_decision_date=identity["settlement_decision_date"],
                calendar_week_index=identity["calendar_week_index"],
                diagnostic_epoch=identity["diagnostic_epoch"],
                as_of_date=as_of_date,
                inputs_root=inputs_root,
                module=benchmark_module,
            )
            cash = capture_cash_week(
                confirm_user_authorization=confirm_user_authorization,
                call_log=attempts,
                decision_date=identity["decision_date"],
                valuation_date=identity["valuation_date"],
                calendar_week_index=identity["calendar_week_index"],
                as_of_date=as_of_date,
                inputs_root=inputs_root,
                opener=cash_opener,
                api_key=cash_api_key,
            )
        except (BenchmarkFetchError, CashFetchError) as exc:
            return {
                "status": "capture_failed",
                "problem": str(exc),
                "calendar_week_index": identity["calendar_week_index"],
                "provider_calls": len(attempts),
                "report_lines": [],
            }
    # The last one is the current week; anything before it ended without being
    # recorded and is about to be settled or written off by the settle step.
    return {
        "status": "captured",
        "calendar_week_index": due[-1]["identity"]["calendar_week_index"],
        "backfilled_week_count": len(due) - 1,
        "unlived_week_count": sum(1 for plan in due if plan["kind"] == "unlived"),
        "benchmark_status": benchmark["status"],
        "evaluable_symbols": benchmark["evaluable_symbols"],
        "cash_status": cash["cash_status"],
        "provider_calls": len(attempts),
        "report_lines": [],
    }


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WeeklyAdvanceError(f"{label} cannot be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise WeeklyAdvanceError(f"{label} is not an object")
    return payload


def _next_week_plan(
    *, root: str | Path, model_paper_root: str | Path, as_of_date: str | None
) -> dict[str, Any]:
    """The store's next week, classified. ``not_ready`` is raised, not returned."""

    try:
        inputs = next_week_inputs(root, as_of_date=as_of_date)
    except MarketDiagnosticWeeklyProducerError as exc:
        raise WeeklyAdvanceError(str(exc)) from exc
    receipt = diagnostic_store_state(root, as_of_date=as_of_date)["receipt"]
    head = _head(model_paper_root)
    index = inputs["calendar_week_index"]
    plan = plan_week(
        index,
        receipt=receipt,
        diagnostic_epoch=inputs["diagnostic_epoch"],
        model_paper_root=model_paper_root,
        head=head,
        prior_valuation_date=_prior_valuation_date(
            index, root=root, model_paper_root=model_paper_root, head=head, as_of_date=as_of_date
        ),
        as_of_date=as_of_date,
    )
    if plan["kind"] == "not_ready":
        raise WeeklyAdvanceNotReady(plan["reason"])
    return plan


def _settle_outcome(
    status: str,
    result: Mapping[str, Any],
    settled_weeks: list[int],
    no_count_weeks: list[int],
    *,
    reason: str | None = None,
    calendar_week_index: int | None = None,
    publication: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One shape for every exit, so a caller never has to guess which keys exist.

    A run that settled at least one week reports that settlement, because that is
    what advanced the clock; the wait that stopped it is the ordinary end of every
    healthy week and is not news.

    ``publication`` is carried in rather than read off the last settlement: a run
    that catches up across a window boundary settles week 26 — which emits the
    scorecard — and then week 27, whose own publication is a `not_ready`. Reading
    the last one would leave the only artifact this track exists to produce
    unannounced in the week it was produced.
    """

    if settled_weeks:
        outcome = {
            "status": result.get("status", "settled"),
            # The clock's position after the run, which is the last week settled.
            "calendar_week_index": settled_weeks[-1],
            "publication": publication,
        }
    else:
        outcome = {"status": status, "calendar_week_index": calendar_week_index}
        if reason is not None:
            outcome["reason"] = reason
    outcome["settled_weeks"] = settled_weeks
    outcome["no_count_weeks"] = no_count_weeks
    outcome["report_lines"] = []
    return outcome


def settle_captured_week(
    *,
    root: str | Path = DEFAULT_ROOT,
    model_paper_root: str | Path = DEFAULT_MODEL_PAPER_ROOT,
    inputs_root: Path = DEFAULT_INPUTS_ROOT,
    output_root: Path = DEFAULT_PUBLIC_ROOT,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Settle every week that is now due, and publish if a window closed.

    Each round settles the store's next week if it CAN be settled and writes it off
    as ``no_count`` only if it never can — the account settled no week it could
    wrap, and never will. A week whose inputs merely arrived late is settled, not
    written off: design section 3 keeps ``no_count`` for weeks that cannot be
    evaluated, and spending a calendar slot on one that can destroys real evidence
    behind an immutable record and a reason that is not true.

    The loop terminates on its own: every round either returns or advances the
    store by one week, and the account has only ever produced finitely many.
    """

    state = diagnostic_store_state(root, as_of_date=as_of_date)
    if state["state"] in DORMANT_STATES:
        return {"status": "dormant", "report_lines": []}
    if state["state"] == "broken":
        return {"status": "broken", "problem": state["problem"], "report_lines": []}

    no_count_weeks: list[int] = []
    settled_weeks: list[int] = []
    result: dict[str, Any] = {}
    # The publication that actually happened, kept across the loop rather than
    # taken from the last settlement (see `_settle_outcome`).
    publication: dict[str, Any] | None = None
    while True:
        try:
            plan = _next_week_plan(
                root=root, model_paper_root=model_paper_root, as_of_date=as_of_date
            )
        except WeeklyAdvanceNotReady as exc:
            # Only reachable while the account has NOT moved past this week, so
            # this is the ordinary steady state and never a stuck clock.
            return _settle_outcome(
                "waiting_for_paper_week", result, settled_weeks, no_count_weeks,
                reason=str(exc), publication=publication,
            )
        identity = plan["identity"]
        index = identity["calendar_week_index"]
        packet_path = (
            benchmark_week_directory(identity["decision_date"], inputs_root=inputs_root)
            / PACKET_FILENAME
        )
        if not packet_path.is_file():
            # No inputs. Saying so beats settling a week from inputs nobody
            # captured — and beats writing off a week whose benchmarks could not be
            # projected, which design section 5 requires a no_count week to carry.
            # Which of the two waits this is matters to a reader: one is a week in
            # progress, the other is a clock that has stopped moving.
            stalled = plan["kind"] == "unlived" or _week_is_over(
                identity["decision_date"], as_of_date
            )
            return _settle_outcome(
                "stalled_on_a_finished_week" if stalled else "waiting_for_inputs",
                result, settled_weeks, no_count_weeks, calendar_week_index=index,
                publication=publication,
            )
        if plan["kind"] == "unlived":
            # Nothing will ever make this week evaluable: the account settled no
            # week it could wrap and never will. Design section 3 — it is written
            # down as no_count, keeps its calendar slot, and the 26-week boundary
            # does not move. Only the benchmarks are projected; the market happened.
            try:
                settle_missed_week(
                    benchmark_packet=_read_json(packet_path, "benchmark price packet"),
                    root=root,
                    reason=plan["reason"],
                    as_of_date=as_of_date,
                )
            except (MarketDiagnosticWeeklyProducerError, MarketDiagnosticLifecycleError) as exc:
                raise WeeklyAdvanceError(str(exc)) from exc
            no_count_weeks.append(index)
            continue
        try:
            # Delegated rather than reimplemented: `settle_week` already owns the
            # boundary-week publish, its idempotence, and the refusal to emit on a
            # non-boundary week. A second copy of that policy here would be a
            # second place for it to drift.
            result = settle_week(
                model_paper_root=Path(model_paper_root),
                benchmark_packet_path=packet_path,
                root=Path(root),
                as_of_date=as_of_date,
                output_root=output_root,
            )
        except (MarketDiagnosticWeeklyRunnerError, MarketDiagnosticWeeklyProducerError,
                MarketDiagnosticLifecycleError) as exc:
            raise WeeklyAdvanceError(str(exc)) from exc
        settled_weeks.append(index)
        emitted = result.get("publication") or {}
        if publication is None or emitted.get("status") in {"published", "idempotent"}:
            publication = emitted
        # Round again rather than return, because after a missed run several weeks
        # are due at once and settling one per run is the calendar lag section 12.8
        # duty 3 forbids. Only when the week just settled is itself already over,
        # though: a further week cannot be due before then, and re-planning to
        # discover that costs two whole-register revalidations every ordinary week.
        if not _week_is_over(identity["decision_date"], as_of_date):
            return _settle_outcome(
                "settled", result, settled_weeks, no_count_weeks, publication=publication
            )


def load_cash_returns(
    *,
    root: str | Path = DEFAULT_ROOT,
    inputs_root: Path = DEFAULT_INPUTS_ROOT,
    as_of_date: str | None = None,
) -> dict[int, dict[str, Any]]:
    """Every captured cash observation, keyed by the week it was captured for.

    Read from the store's own settled weeks rather than by listing a directory:
    a stray folder must not be able to introduce a week the ledger never counted.
    """

    try:
        records = load_settled_weekly_records(root, as_of_date=as_of_date)
    except MarketDiagnosticLifecycleError:
        return {}
    result: dict[int, dict[str, Any]] = {}
    for record in records:
        path = (
            cash_week_directory(record["decision_date"], inputs_root=inputs_root)
            / OBSERVATION_FILENAME
        )
        if not path.is_file():
            continue
        stored = _read_json(path, "cash observation")
        if stored.get("calendar_week_index") != record["calendar_week_index"]:
            # A file whose week disagrees with the ledger is not this week's cash.
            continue
        observation = stored.get("observation")
        if isinstance(observation, dict):
            result[record["calendar_week_index"]] = observation
    return result

DEFAULT_RUNS_PRIVATE_ROOT = ROOT / "state" / "us_short" / "runs_private"


def load_target_exposures(
    *,
    root: str | Path = DEFAULT_ROOT,
    runs_private_root: str | Path = DEFAULT_RUNS_PRIVATE_ROOT,
    as_of_date: str | None = None,
) -> dict[int, dict[str, Any]]:
    """Knife 10a: every week's rule-implied target exposure, keyed by calendar week.

    The five components are not computed here and never could be: section 12.7
    forbids recovering a target position from fills or from a later NAV, so the
    only honest source is the note the decision itself took while it still had
    the numbers. This reads that note and shapes it for the attribution gate,
    which then re-derives ``g*`` and the binding constraints from it — so a
    filled position still cannot pass itself off as the rule-implied one.

    Keyed off the ledger's settled weeks, like the cash leg beside it: a stray
    run directory must not introduce a week nobody counted.
    """

    try:
        records = load_settled_weekly_records(root, as_of_date=as_of_date)
    except MarketDiagnosticLifecycleError:
        return {}
    result: dict[int, dict[str, Any]] = {}
    for record in records:
        decision_date = record["decision_date"]
        try:
            note = load_decision_exposure(decision_date, runs_private_root=runs_private_root)
        except DecisionExposureError:
            # An unreadable note is a missing note. The week degrades; it does not
            # take the packet down, and nothing is filled in for it.
            note = None
        if note is None or note.get("status") != "evaluable":
            continue
        result[record["calendar_week_index"]] = {
            "status": "evaluable",
            # The attribution gate requires this to equal the decision date, which
            # is what binds the observation to the week it describes.
            "as_of_date": decision_date,
            "carried_holdings_exposure": note["carried_holdings_exposure"],
            "new_order_exposure": note["new_order_exposure"],
            "cash_capacity_exposure": note["cash_capacity_exposure"],
            "environment_position_cap": note["environment_position_cap"],
            "long_only_cap": note["long_only_cap"],
            "source_refs": [artifact_sha256(note)],
            "data_quality_reasons": [],
        }
    return result
