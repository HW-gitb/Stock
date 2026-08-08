"""Knife 7b-i — the missing producer: turn already-local inputs into one settled week.

Until this module existed the diagnostic track could validate a weekly record,
store it, gate it, and aggregate it, but nothing anywhere computed one. The
operator entry could only carry a record somebody had produced by hand, and the
Knife 2 adapter — the thing that knows how to join the model-paper account to the
benchmark prices — had zero callers. A clock with no way to produce week 1 is a
clock that fails on the first day it is opened.

What this module supplies, and where each piece honestly comes from:

* the calendar week index, prior NAV and v1.1 reminder — read out of the
  authorized lifecycle store, never guessed and never supplied by the caller, so
  a week cannot be inserted at an index the store does not expect;
* ``diagnostic_policy_sha256`` — the canonical digest of the frozen diagnostic
  policy preset;
* ``strategy_ruleset_fingerprint`` — a digest over the governance presets named
  in ``presets/us_short_market_diagnostic_strategy_ruleset_v1.json``. Design
  section 6 wants a value that is stable week to week and moves when the rules
  move, so a 26-week report can segment by rule version; the digest of the weekly
  decision artifact would change every week and make ``mixed_ruleset_window``
  permanently true, which is the opposite of useful.

The benchmark price packet is an INPUT, not something this module builds. Its
producer is knife 8 (`runners/us_short_market_diagnostic_benchmark_fetch.py` ->
`engine/us_short_market_diagnostic_benchmark_packet.py`), not the design-named
upstream (the grouped market window), which is still unimplemented; inventing
prices here would be the one thing this whole track exists to prevent.

Nothing here calls a provider, writes the model-paper account, or changes
selection, action, sizing or NAV. Everything written goes through the Knife 7
authorization gate under the private, git-ignored diagnostic root.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

from engine.us_short_market_diagnostic import BOUNDARY
from engine.us_short_market_diagnostic_local_adapter import (
    LocalMarketDiagnosticAdapterError,
    _dedupe_sha256,
    adapt_benchmark_week,
    build_weekly_record_from_local,
    load_model_paper_week,
    validate_local_price_packet,
)
from engine.us_short_market_diagnostic_lifecycle import (
    DEFAULT_ROOT,
    MarketDiagnosticLifecycleError,
    _record_files,
    build_v1_1_reminder,
    load_lifecycle_register,
    load_settled_weekly_records,
    persist_settled_weekly_record,
)
from engine.us_short_market_diagnostic_start_receipt import (
    DiagnosticStartReceiptError,
    load_start_receipt,
)
from engine.us_short_model_paper_portfolio import artifact_sha256, canonical_json_bytes


ROOT = Path(__file__).resolve().parent.parent
POLICY_PRESET_PATH = ROOT / "presets" / "us_short_market_diagnostic_26w_policy_v1.json"
RULESET_PRESET_PATH = ROOT / "presets" / "us_short_market_diagnostic_strategy_ruleset_v1.json"
# The frozen normalized paper capital every diagnostic NAV series starts from.
NORMALIZED_CAPITAL = "100000.000000"


class MarketDiagnosticWeeklyProducerError(RuntimeError):
    """Raised when a settled diagnostic week cannot be produced from local inputs."""


def _load_preset(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketDiagnosticWeeklyProducerError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise MarketDiagnosticWeeklyProducerError(f"{label} must be a JSON object: {path}")
    return value


def diagnostic_policy_sha256() -> str:
    """Digest of the frozen diagnostic policy preset, canonicalized first."""

    return artifact_sha256(_load_preset(POLICY_PRESET_PATH, "diagnostic policy preset"))


def strategy_ruleset_fingerprint() -> str:
    """Digest over the declared governance presets in force.

    Over the DECLARED list, canonicalized, with each preset's own digest inside.
    Precisely: editing any governed rule moves the fingerprint; adding or removing
    an entry moves it; re-formatting a preset does not; and neither does
    reordering or duplicating entries in the declaration, because the payload is a
    sorted map keyed by path rather than a list.
    """

    declaration = _load_preset(RULESET_PRESET_PATH, "strategy ruleset preset")
    governed = declaration.get("governed_presets")
    if not isinstance(governed, list) or not governed:
        raise MarketDiagnosticWeeklyProducerError(
            "strategy ruleset preset declares no governed presets"
        )
    digests: dict[str, str] = {}
    for relative in sorted(governed):
        if not isinstance(relative, str) or not relative:
            raise MarketDiagnosticWeeklyProducerError(
                "strategy ruleset preset lists a governed preset that is not a path"
            )
        # The whole argument for a declared list is that its own change shows up in
        # a diff. An absolute path silently discards ROOT, and `..` walks out of
        # the repo, so either one fingerprints something no reviewer will see.
        # Checked in both path flavours: on Windows ``Path("/etc/passwd")`` is not
        # "absolute" (it has no drive), so a POSIX-rooted entry would slip through
        # a naive check on one platform and not the other.
        candidate = Path(relative)
        posix = PurePosixPath(relative)
        if (
            candidate.is_absolute()
            or posix.is_absolute()
            or PureWindowsPath(relative).is_absolute()
            or ".." in candidate.parts
            or ".." in posix.parts
        ):
            raise MarketDiagnosticWeeklyProducerError(
                f"governed preset must be a repo-relative path inside the tree: {relative}"
            )
        path = ROOT / relative
        if not path.is_file():
            raise MarketDiagnosticWeeklyProducerError(
                f"declared governed preset is missing, so the ruleset in force cannot be "
                f"fingerprinted: {relative}"
            )
        digests[relative] = artifact_sha256(_load_preset(path, f"governed preset {relative}"))
    ruleset_id = declaration.get("ruleset_id")
    if not isinstance(ruleset_id, str) or not ruleset_id:
        raise MarketDiagnosticWeeklyProducerError(
            "strategy ruleset preset has no ruleset_id, so the fingerprint would not say which ruleset it is"
        )
    payload = {"ruleset_id": ruleset_id, "governed_preset_sha256": digests}
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def has_counted_weeks(root: str | Path = DEFAULT_ROOT) -> bool:
    """Whether this store holds any weekly record at all.

    The evidence of counted weeks is the immutable weekly records, NOT the
    mutable register beside them. An earlier version probed
    ``lifecycle_register.json``, which meant a store whose two top-level JSONs had
    both been deleted — a partial restore, or an operator "resetting the clock" —
    reported ten weeks of destroyed evidence as a clean slate. The guard was on
    every path; its argument was the wrong artifact.
    """

    try:
        return bool(_record_files(Path(root)))
    except (MarketDiagnosticLifecycleError, OSError, TypeError, ValueError):
        # An unreadable weeks/ tree is not an empty one.
        return True


def diagnostic_store_state(
    root: str | Path = DEFAULT_ROOT, *, as_of_date: str | None = None
) -> dict[str, Any]:
    """The one place that decides which of four things this store is.

    ``not_started`` — no receipt and no records: a clean slate, and the normal
    state of this track today.
    ``fresh`` — a receipt, no weeks yet: the clock was opened this week and the
    first ``settle-week`` has not run. NOT broken; reporting it as broken is how
    an operator learns to ignore the word.
    ``running`` — a receipt and a readable register.
    ``broken`` — anything else: records with no receipt, an unreadable receipt,
    an unreadable register, a register that does not derive from its records.

    Three readers used to answer this question three slightly different ways, and
    all three got a different case wrong.
    """

    counted = has_counted_weeks(root)
    try:
        receipt = load_start_receipt(root, verify_design_against_disk=False)
    except DiagnosticStartReceiptError as exc:
        return {"state": "broken", "problem": str(exc), "receipt": None, "register": None, "records": []}
    if receipt is None:
        if counted:
            return {
                "state": "broken",
                "problem": (
                    "weeks have been counted but the start receipt that authorized them is gone"
                ),
                "receipt": None,
                "register": None,
                "records": [],
            }
        return {"state": "not_started", "problem": None, "receipt": None, "register": None, "records": []}
    if not counted:
        return {"state": "fresh", "problem": None, "receipt": receipt, "register": None, "records": []}
    try:
        register = load_lifecycle_register(root, as_of_date=as_of_date)
        records = load_settled_weekly_records(root, as_of_date=as_of_date)
    except MarketDiagnosticLifecycleError as exc:
        # Deliberately not swallowed into "no records yet". Any store fault used
        # to become "week 1, prior NAV None", and the public builder would then
        # hand back a week-1 record restarting the NAV series from the normalized
        # capital — a lie the store had to catch on the caller's behalf.
        return {"state": "broken", "problem": str(exc), "receipt": receipt, "register": None, "records": []}
    return {"state": "running", "problem": None, "receipt": receipt, "register": register, "records": records}


def next_week_inputs(
    root: str | Path = DEFAULT_ROOT, *, as_of_date: str | None = None
) -> dict[str, Any]:
    """What the store says the next week must be. Nothing here is caller-supplied.

    Returns the index to produce, the prior settled NAV to continue from, and the
    v1.1 reminder derived from the counts already on disk. Week 1 carries a
    ``None`` prior NAV because the normalized capital is the base; a later week
    that lost its predecessor is a store problem, not something to paper over.
    """

    state = diagnostic_store_state(root, as_of_date=as_of_date)
    if state["state"] == "not_started":
        raise MarketDiagnosticWeeklyProducerError(
            "the 26-week diagnostic clock has not been opened; run open-clock first"
        )
    if state["state"] == "broken":
        raise MarketDiagnosticWeeklyProducerError(
            f"the diagnostic store cannot be read, so the next week is unknown: {state['problem']}"
        )
    receipt = state["receipt"]
    if state["state"] == "fresh":
        return {
            "calendar_week_index": 1,
            "prior_nav": None,
            "v1_1_reminder": build_v1_1_reminder(0, consecutive_paper_evaluable_week_count=0),
            "diagnostic_epoch": receipt["diagnostic_epoch"],
        }

    register = state["register"]
    records = state["records"]
    attribution = register["v1_1_attribution"]
    return {
        "calendar_week_index": register["last_calendar_week_index"] + 1,
        "prior_nav": records[-1]["strategy"]["nav"],
        "v1_1_reminder": build_v1_1_reminder(
            register["evaluable_week_count"],
            consecutive_paper_evaluable_week_count=register[
                "consecutive_paper_evaluable_week_count"
            ],
            active=attribution["status"] == "active",
            attribution_epoch=attribution["attribution_epoch"],
        ),
        "diagnostic_epoch": register["diagnostic_epoch"],
    }


def _target_week(
    benchmark_packet: Mapping[str, Any],
    inputs: Mapping[str, Any],
    root: str | Path,
    *,
    as_of_date: str | None,
) -> tuple[int, str | None, bool]:
    """Which week this packet is for, the NAV it continues from, and whether the
    week before it was a ``no_count``.

    That last fact belongs here because it is a property of the LEDGER, not of the
    packet or of anything a caller could supply: a no_count week is one the account
    never settled, so its NAV was carried forward and this week's move spans both
    calendar weeks. The record has to say so, or the 26-week comparison silently
    pairs a two-week strategy return with a one-week benchmark return.

    Design section 2.2 requires a repeated run to be idempotent. Always producing
    "the next expected week" is not: running the weekly command twice would ask
    for a week the packet does not describe and fail with a confusing message
    instead of quietly agreeing. So the target is the packet's own latest week
    that the store is ready for, and the store's own immutability decides whether
    that is a fresh week or a replay.
    """

    weeks = benchmark_packet.get("weeks") if isinstance(benchmark_packet, Mapping) else None
    if not isinstance(weeks, list) or not weeks:
        raise MarketDiagnosticWeeklyProducerError("the benchmark price packet describes no weeks")
    indexes = sorted(
        week["calendar_week_index"]
        for week in weeks
        if isinstance(week, Mapping) and isinstance(week.get("calendar_week_index"), int)
    )
    expected = inputs["calendar_week_index"]
    candidates = [index for index in indexes if index <= expected]
    if not candidates:
        raise MarketDiagnosticWeeklyProducerError(
            f"the benchmark price packet describes weeks {indexes}, but this clock is ready for "
            f"week {expected}; a gap cannot be skipped over"
        )
    target = candidates[-1]
    if target == 1:
        return target, None, False
    try:
        records = load_settled_weekly_records(root, as_of_date=as_of_date)
    except MarketDiagnosticLifecycleError as exc:
        raise MarketDiagnosticWeeklyProducerError(
            f"the prior settled week cannot be read, so week {target} has no NAV to continue: {exc}"
        ) from exc
    for record in records:
        if record["calendar_week_index"] == target - 1:
            return target, record["strategy"]["nav"], bool(record["strategy"]["no_count"])
    raise MarketDiagnosticWeeklyProducerError(
        f"week {target} needs the settled NAV of week {target - 1}, which the store does not hold"
    )


def model_paper_week_is_settled(
    model_paper_root: str | Path,
    benchmark_packet: Mapping[str, Any],
    calendar_week_index: int,
    *,
    as_of_date: str | None = None,
) -> bool:
    """Whether the model-paper account actually settled the week this packet names.

    Asked before projecting, so an unsettled week becomes a recorded ``no_count``
    rather than an exception. Only the "not settled yet" refusal answers False; a
    tampered or digest-mismatched artifact must still raise, because that is a
    fault and not an honest gap.
    """

    for week in benchmark_packet.get("weeks", []):
        if isinstance(week, Mapping) and week.get("calendar_week_index") == calendar_week_index:
            settlement_date = week.get("settlement_decision_date")
            break
    else:
        raise MarketDiagnosticWeeklyProducerError(
            f"the benchmark price packet has no calendar week {calendar_week_index}"
        )
    try:
        load_model_paper_week(model_paper_root, settlement_date, as_of_date=as_of_date)
    except LocalMarketDiagnosticAdapterError as exc:
        if "requires a settled model-paper week" in str(exc):
            return False
        raise MarketDiagnosticWeeklyProducerError(
            f"the model-paper week {settlement_date} cannot be read: {exc}"
        ) from exc
    return True


def build_no_count_record(
    *,
    benchmark_packet: Mapping[str, Any],
    calendar_week_index: int,
    prior_nav: str | None,
    v1_1_reminder: Mapping[str, Any],
    reason: str,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """One calendar week the strategy could not be evaluated for, recorded honestly.

    The benchmarks are still projected — the market did happen, and section 5 wants
    those weeks visible — while the strategy block carries nulls, ``no_count`` and
    an explicit reason. The strategy digest is the benchmark packet's, since the
    packet is the only evidence this week existed at all.

    NAV is the prior settled NAV, and that is only honest because BOTH callers hand
    over a week the account never settled: ``build_next_weekly_record`` when the
    paper week is absent, and ``settle_missed_week`` when the account never ran
    that week at all. An unsettled week did not move the account, so its NAV is the
    one before it and the next evaluable week still measures a single week. A week
    the account DID settle must never come here — carrying the prior NAV would
    silently erase that week's real gain or loss and hand the next week a two-week
    return to compare against a one-week benchmark. For week 1 the prior NAV is the
    frozen normalized capital.
    """

    if not isinstance(reason, str) or not reason:
        raise MarketDiagnosticWeeklyProducerError("a no_count week must say why")
    try:
        packet = validate_local_price_packet(benchmark_packet, as_of_date=as_of_date)
        week = next(
            item for item in packet["weeks"] if item["calendar_week_index"] == calendar_week_index
        )
        benchmarks = adapt_benchmark_week(
            packet,
            calendar_week_index,
            strategy_evaluable=False,
            strategy_weekly_return=None,
            # No strategy return, so there is no span to line up; this week leaves
            # the comparison through `strategy_evaluable`, not through this flag.
            windows_aligned=True,
            as_of_date=as_of_date,
        )
    except (LocalMarketDiagnosticAdapterError, StopIteration) as exc:
        raise MarketDiagnosticWeeklyProducerError(
            f"a no_count week {calendar_week_index} cannot be projected: {exc}"
        ) from exc

    nav = prior_nav if prior_nav is not None else NORMALIZED_CAPITAL
    packet_digest = artifact_sha256(dict(packet))
    # Same binding rule as a settled week: every benchmark's own price and dividend
    # digests must appear in source_refs, so a no_count week is as source-bound as
    # any other. It is a week with no strategy result, not a week with no evidence.
    # Through the settled week's own helper, because a benchmark can be
    # `unavailable` on EITHER leg and carry a null digest there — a second, local
    # copy of the rule filtered nulls out of the dividend leg only, and the first
    # unavailable benchmark then put a `None` into `source_refs` and failed the
    # schema. One rule, one implementation.
    source_refs = _dedupe_sha256(
        [
            packet_digest,
            *packet["source_refs"],
            *(benchmark["price_packet_sha256"] for benchmark in benchmarks.values()),
            *(benchmark["dividend_sidecar_sha256"] for benchmark in benchmarks.values()),
        ]
    )
    return {
        "schema_name": "us_short_market_diagnostic_weekly_record",
        "schema_version": "1.1.0",
        "decision_date": week["decision_date"],
        # A week with no strategy return has no span to line up against the
        # benchmarks, so nothing is misaligned here. This week is already out of
        # the comparison through `strategy_evaluable`; one fact, one field.
        "windows_aligned": True,
        "windows_misaligned_reason": None,
        "valuation_date": week["valuation_date"],
        "calendar_week_index": calendar_week_index,
        "window_id": packet["window_id"],
        "diagnostic_epoch": packet["diagnostic_epoch"],
        "diagnostic_policy_sha256": diagnostic_policy_sha256(),
        "strategy_ruleset_fingerprint": strategy_ruleset_fingerprint(),
        "strategy": {
            "paper_evaluable": False,
            # Section 12.1's strategy vocabulary is exactly three values; a week the
            # account never settled is `not_evaluable`, and `no_count_reason`
            # carries why. "unavailable" belongs to the benchmark vocabulary.
            "performance_status": "not_evaluable",
            "strategy_evaluable": False,
            "initial_capital": NORMALIZED_CAPITAL,
            "prior_nav": prior_nav,
            "nav": nav,
            "weekly_return": None,
            "cumulative_return": None,
            "cash": None,
            "market_value": None,
            "cumulative_cost_paid": None,
            "turnover": None,
            "unfilled_order_count": None,
            "no_count": True,
            "no_count_reason": reason,
            "source_sha256": packet_digest,
            "degradation_reasons": [reason],
        },
        "benchmarks": benchmarks,
        "v1_1_reminder": dict(v1_1_reminder),
        "source_refs": source_refs,
        "boundary": dict(BOUNDARY),
    }


def build_next_weekly_record(
    *,
    model_paper_root: str | Path,
    benchmark_packet: Mapping[str, Any],
    root: str | Path = DEFAULT_ROOT,
    total_return_sidecar: Mapping[str, Any] | None = None,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Compute the next week from local inputs, without storing it.

    Deliberately no ``calendar_week_index``, ``prior_nav`` or ``v1_1_reminder``
    parameter: those come out of the authorized store, so a caller cannot ask for
    a week the clock is not expecting or continue a NAV series from a number it
    made up.
    """

    inputs = next_week_inputs(root, as_of_date=as_of_date)
    packet_epoch = benchmark_packet.get("diagnostic_epoch") if isinstance(benchmark_packet, Mapping) else None
    if packet_epoch != inputs["diagnostic_epoch"]:
        raise MarketDiagnosticWeeklyProducerError(
            "the benchmark price packet belongs to a different diagnostic epoch than this clock"
        )
    target, prior_nav, prior_week_was_no_count = _target_week(
        benchmark_packet, inputs, root, as_of_date=as_of_date
    )
    if not model_paper_week_is_settled(model_paper_root, benchmark_packet, target, as_of_date=as_of_date):
        # Design sections 3 and 5: a week the account could not settle is recorded
        # as no_count and STILL occupies its calendar slot. Without this the whole
        # weekly act stalled on one unevaluable week — the next week refused with
        # "must append 3, got 4" and the only way forward was hand-authoring a
        # record, which is the manual step this slice exists to remove. The 26-week
        # window is never extended to wait for a week that did not happen.
        return build_no_count_record(
            benchmark_packet=benchmark_packet,
            calendar_week_index=target,
            prior_nav=prior_nav,
            v1_1_reminder=inputs["v1_1_reminder"],
            reason="model_paper_week_not_settled",
            as_of_date=as_of_date,
        )
    try:
        return build_weekly_record_from_local(
            model_paper_root=model_paper_root,
            benchmark_packet=benchmark_packet,
            calendar_week_index=target,
            diagnostic_policy_sha256=diagnostic_policy_sha256(),
            strategy_ruleset_fingerprint=strategy_ruleset_fingerprint(),
            v1_1_reminder=inputs["v1_1_reminder"],
            prior_nav=prior_nav,
            total_return_sidecar=total_return_sidecar,
            prior_week_was_no_count=prior_week_was_no_count,
            as_of_date=as_of_date,
        )
    except LocalMarketDiagnosticAdapterError as exc:
        raise MarketDiagnosticWeeklyProducerError(
            f"local inputs cannot produce calendar week {target}: {exc}"
        ) from exc


def settle_missed_week(
    *,
    benchmark_packet: Mapping[str, Any],
    root: str | Path = DEFAULT_ROOT,
    reason: str,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Record the week the store is still waiting for as ``no_count`` and move on.

    Design sections 3 and 12.8 duty 3: a week that could not be evaluated still
    occupies its calendar slot and the 26-week boundary is never pushed out to
    wait for it. Until this existed ``build_no_count_record`` had exactly one
    caller — the branch where the model-paper account had not settled — so the
    far more likely outage, the week whose benchmark inputs never arrived, had no
    producer at all and the clock stopped for good on the first one.

    Which week is written off is NOT a parameter: it is whatever the authorized
    store says is next, so a caller cannot write off a week the clock is not
    waiting for. The packet must be that same week's, which
    ``build_no_count_record`` enforces by having to find that index inside it.
    """

    inputs = next_week_inputs(root, as_of_date=as_of_date)
    packet_epoch = (
        benchmark_packet.get("diagnostic_epoch") if isinstance(benchmark_packet, Mapping) else None
    )
    if packet_epoch != inputs["diagnostic_epoch"]:
        raise MarketDiagnosticWeeklyProducerError(
            "the benchmark price packet belongs to a different diagnostic epoch than this clock"
        )
    record = build_no_count_record(
        benchmark_packet=benchmark_packet,
        calendar_week_index=inputs["calendar_week_index"],
        prior_nav=inputs["prior_nav"],
        v1_1_reminder=inputs["v1_1_reminder"],
        reason=reason,
        as_of_date=as_of_date,
    )
    try:
        return persist_settled_weekly_record(record, root=root, as_of_date=as_of_date)
    except MarketDiagnosticLifecycleError as exc:
        raise MarketDiagnosticWeeklyProducerError(str(exc)) from exc


def settle_next_week(
    *,
    model_paper_root: str | Path,
    benchmark_packet: Mapping[str, Any],
    root: str | Path = DEFAULT_ROOT,
    total_return_sidecar: Mapping[str, Any] | None = None,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Produce the next week and carry it through the authorization gate."""

    record = build_next_weekly_record(
        model_paper_root=model_paper_root,
        benchmark_packet=benchmark_packet,
        root=root,
        total_return_sidecar=total_return_sidecar,
        as_of_date=as_of_date,
    )
    try:
        return persist_settled_weekly_record(record, root=root, as_of_date=as_of_date)
    except MarketDiagnosticLifecycleError as exc:
        raise MarketDiagnosticWeeklyProducerError(str(exc)) from exc


__all__ = [
    "MarketDiagnosticWeeklyProducerError",
    "POLICY_PRESET_PATH",
    "RULESET_PRESET_PATH",
    "build_next_weekly_record",
    "build_no_count_record",
    "diagnostic_policy_sha256",
    "diagnostic_store_state",
    "has_counted_weeks",
    "model_paper_week_is_settled",
    "next_week_inputs",
    "settle_missed_week",
    "settle_next_week",
    "strategy_ruleset_fingerprint",
]
