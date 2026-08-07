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
from engine.us_short_market_diagnostic_weekly_producer import (  # noqa: E402
    MarketDiagnosticWeeklyProducerError,
    diagnostic_store_state,
    next_week_inputs,
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


class WeeklyAdvanceError(Exception):
    """The week cannot be advanced."""


class WeeklyAdvanceNotReady(WeeklyAdvanceError):
    """Nothing is wrong; the account simply has not produced a new week yet.

    Kept separate because the caller turns it into a WAITING line rather than a
    fault. For most of any week this is the ordinary answer, and an operator who
    is shown "failed" every time stops reading the word — the same lesson the
    fresh-versus-broken clock states already cost this track once.
    """


def _date8(value: str):
    return datetime.strptime(value, "%Y%m%d").date()


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
    try:
        head = load_head(model_paper_root)
    except ModelPaperStoreError as exc:
        raise WeeklyAdvanceError(f"the model-paper store cannot be read: {exc}") from exc
    settlement = head["last_settlement"]
    if settlement is None:
        raise WeeklyAdvanceNotReady("the model-paper account has not settled a week yet")

    settlement_decision_date = settlement["decision_date"]
    valuation_date = head["current_state"]["as_of"]
    index = inputs["calendar_week_index"]
    # The diagnostic week's own decision date, derived rather than accepted: week
    # one is frozen in the receipt and every later week is exactly seven days on,
    # which is the cadence the lifecycle already enforces on every write. It is
    # deliberately NOT the paper week's decision date — that one is the
    # SETTLEMENT this week wraps, and the consumer requires
    # settlement <= valuation <= decision.
    first_decision = _date8(receipt["first_calendar_week"]["decision_date"])
    decision_date = (first_decision + timedelta(days=7 * (index - 1))).strftime("%Y%m%d")

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
        prior_valuation_date = prior[0]["valuation_date"]
    else:
        # Both sides start on the same day: the account's own seeding date. The
        # head carries the seed only as a path and a digest, so the date comes
        # from the seed state itself rather than from a field that is not there.
        seed = _read_json(
            Path(model_paper_root) / head["seed_state"]["relative_path"], "seed portfolio state"
        )
        prior_valuation_date = seed.get("as_of")
        if not isinstance(prior_valuation_date, str):
            raise WeeklyAdvanceError("the seeded account carries no as-of date to start from")

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
        "diagnostic_epoch": inputs["diagnostic_epoch"],
        "decision_date": decision_date,
        "settlement_decision_date": settlement_decision_date,
        "valuation_date": valuation_date,
        "prior_valuation_date": prior_valuation_date,
    }


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
    """Capture this week's benchmark prices and cash rate. Dormant means silent."""

    state = diagnostic_store_state(root, as_of_date=as_of_date)
    if state["state"] in DORMANT_STATES:
        # Not an error and not a degradation: a clock nobody opened must cost
        # nothing at all, including zero network and zero bytes.
        return {"status": "dormant", "report_lines": []}
    if state["state"] == "broken":
        return {"status": "broken", "problem": state["problem"], "report_lines": []}

    try:
        identity = next_week_identity(
            root=root, model_paper_root=model_paper_root, as_of_date=as_of_date
        )
    except WeeklyAdvanceNotReady as exc:
        return {"status": "waiting_for_paper_week", "reason": str(exc), "report_lines": []}
    # One log across both captures. A failure part-way through must still report
    # the requests that already went out: reporting "no provider call" after real
    # ones is a false statement about a paid boundary, which is why the count is
    # carried rather than inferred from whether this returned normally.
    attempts: list[str] = []
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
    return {
        "status": "captured",
        "calendar_week_index": identity["calendar_week_index"],
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


def settle_captured_week(
    *,
    root: str | Path = DEFAULT_ROOT,
    model_paper_root: str | Path = DEFAULT_MODEL_PAPER_ROOT,
    inputs_root: Path = DEFAULT_INPUTS_ROOT,
    output_root: Path = DEFAULT_PUBLIC_ROOT,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Settle the week whose inputs are already captured, and publish if a window closed."""

    state = diagnostic_store_state(root, as_of_date=as_of_date)
    if state["state"] in DORMANT_STATES:
        return {"status": "dormant", "report_lines": []}
    if state["state"] == "broken":
        return {"status": "broken", "problem": state["problem"], "report_lines": []}

    try:
        identity = next_week_identity(
            root=root, model_paper_root=model_paper_root, as_of_date=as_of_date
        )
    except WeeklyAdvanceNotReady as exc:
        return {"status": "waiting_for_paper_week", "reason": str(exc), "report_lines": []}
    packet_path = (
        benchmark_week_directory(identity["decision_date"], inputs_root=inputs_root)
        / PACKET_FILENAME
    )
    if not packet_path.is_file():
        # The fetch step has not run, or ran and could not write. Saying so is
        # better than settling a week from inputs nobody captured.
        return {
            "status": "waiting_for_inputs",
            "calendar_week_index": identity["calendar_week_index"],
            "report_lines": [],
        }
    try:
        # Delegated rather than reimplemented: `settle_week` already owns the
        # boundary-week publish, its idempotence, and the refusal to emit on a
        # non-boundary week. A second copy of that policy here would be a second
        # place for it to drift.
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
    return {
        "status": result.get("status", "settled"),
        "calendar_week_index": result.get("calendar_week_index"),
        "publication": result.get("publication"),
        "report_lines": [],
    }


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
