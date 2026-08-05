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
producer does not exist yet anywhere in the repo and its design-named upstream
(the grouped market window) is unimplemented; inventing prices here would be the
one thing this whole track exists to prevent.

Nothing here calls a provider, writes the model-paper account, or changes
selection, action, sizing or NAV. Everything written goes through the Knife 7
authorization gate under the private, git-ignored diagnostic root.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from engine.us_short_market_diagnostic_local_adapter import (
    LocalMarketDiagnosticAdapterError,
    build_weekly_record_from_local,
)
from engine.us_short_market_diagnostic_lifecycle import (
    DEFAULT_ROOT,
    REGISTER_FILENAME,
    MarketDiagnosticLifecycleError,
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

    Over the DECLARED list, canonicalized, with each preset's own digest inside —
    so editing any governed rule moves the fingerprint, editing the declaration
    moves it, and re-formatting a preset does not.
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
        path = ROOT / relative
        if not path.is_file():
            raise MarketDiagnosticWeeklyProducerError(
                f"declared governed preset is missing, so the ruleset in force cannot be "
                f"fingerprinted: {relative}"
            )
        digests[relative] = artifact_sha256(_load_preset(path, f"governed preset {relative}"))
    payload = {
        "ruleset_id": declaration.get("ruleset_id"),
        "governed_preset_sha256": digests,
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def register_exists(root: str | Path = DEFAULT_ROOT) -> bool:
    """Whether this store has ever counted a week.

    Used to tell "never opened" apart from "opened, counted, and then lost its
    receipt". Those two look identical from the receipt alone and mean opposite
    things: one is a clean slate, the other is destroyed evidence.
    """

    try:
        return (Path(root) / REGISTER_FILENAME).is_file()
    except (OSError, TypeError, ValueError):
        return False


def next_week_inputs(
    root: str | Path = DEFAULT_ROOT, *, as_of_date: str | None = None
) -> dict[str, Any]:
    """What the store says the next week must be. Nothing here is caller-supplied.

    Returns the index to produce, the prior settled NAV to continue from, and the
    v1.1 reminder derived from the counts already on disk. Week 1 carries a
    ``None`` prior NAV because the normalized capital is the base; a later week
    that lost its predecessor is a store problem, not something to paper over.
    """

    try:
        receipt = load_start_receipt(root, verify_design_against_disk=False)
    except DiagnosticStartReceiptError as exc:
        raise MarketDiagnosticWeeklyProducerError(
            f"the diagnostic clock cannot be read: {exc}"
        ) from exc
    if receipt is None:
        if register_exists(root):
            raise MarketDiagnosticWeeklyProducerError(
                "weeks have been counted but the start receipt that authorized them is gone; "
                "this is a broken clock, not one that was never opened"
            )
        raise MarketDiagnosticWeeklyProducerError(
            "the 26-week diagnostic clock has not been opened; run open-clock first"
        )

    try:
        records = load_settled_weekly_records(root, as_of_date=as_of_date)
    except MarketDiagnosticLifecycleError:
        records = []
    if not records:
        return {
            "calendar_week_index": 1,
            "prior_nav": None,
            "v1_1_reminder": build_v1_1_reminder(0, consecutive_paper_evaluable_week_count=0),
            "diagnostic_epoch": receipt["diagnostic_epoch"],
        }

    try:
        register = load_lifecycle_register(root, as_of_date=as_of_date)
    except MarketDiagnosticLifecycleError as exc:
        raise MarketDiagnosticWeeklyProducerError(
            f"the diagnostic store cannot be read, so the next week is unknown: {exc}"
        ) from exc
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
) -> tuple[int, str | None]:
    """Which week this packet is for, and the NAV it must continue from.

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
        return target, None
    try:
        records = load_settled_weekly_records(root, as_of_date=as_of_date)
    except MarketDiagnosticLifecycleError as exc:
        raise MarketDiagnosticWeeklyProducerError(
            f"the prior settled week cannot be read, so week {target} has no NAV to continue: {exc}"
        ) from exc
    for record in records:
        if record["calendar_week_index"] == target - 1:
            return target, record["strategy"]["nav"]
    raise MarketDiagnosticWeeklyProducerError(
        f"week {target} needs the settled NAV of week {target - 1}, which the store does not hold"
    )


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
    target, prior_nav = _target_week(benchmark_packet, inputs, root, as_of_date=as_of_date)
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
            as_of_date=as_of_date,
        )
    except LocalMarketDiagnosticAdapterError as exc:
        raise MarketDiagnosticWeeklyProducerError(
            f"local inputs cannot produce calendar week {target}: {exc}"
        ) from exc


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
    "diagnostic_policy_sha256",
    "next_week_inputs",
    "settle_next_week",
    "strategy_ruleset_fingerprint",
]
