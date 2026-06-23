# -*- coding: utf-8 -*-
"""US-short §11.5 持仓覆盖诚实度 — batch-3: per-row coverage classifier + fail-closed honesty gate.

Design authority: docs/us_short_system_design.md §11.5 (row_source + coverage_status + coverage_gap_tags;
即使强制进 Pass 2，缺分析师/SEC parse/事件数据 → 明示 partial/未核查、不写 clean) / §11.3 (action_table 的
coverage_status / coverage_gap_tags / row_source 列) / §18.1 #10. Enum authority = the FROZEN
presets/us_short_action_table_contract_20260620.json ``design_locked_enums`` (batch-1, design-locked): the 4
``row_source`` values and the 4 ``coverage_status`` values are read from it (single source, no hardcoded copy),
and the ``coverage_status`` list order IS the severity order (full < partial < restricted < blocked).

The §11.5 honesty rule is the heart of this slice: a row is labelled ``full`` ONLY when every gating coverage
category checked out — missing / restricted / blocked analyst, SEC-parse, or event data downgrades the row and
records a ``coverage_gap_tag`` so the report never claims a clean cover it does not have. ``build_row_coverage``
DERIVES ``coverage_status`` as the WORST-of the per-category checks (mirrors the provider-health worst-of) and
``validate_row_coverage`` is the fail-closed gate that enforces the bidirectional invariant
``coverage_status == "full" ⇔ no gap_tags`` — so a hand-built / upstream coverage record can never claim ``full``
with an open gap, nor downgrade without naming the gap. Pure / offline: reads the frozen enum contract, maps
dicts; no provider / live / DataHub / network; no A-share crossing.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_CONTRACT_PRESET = ROOT / "presets" / "us_short_action_table_contract_20260620.json"

# The §11.5 gating coverage categories (design prose — not a frozen enum). A row must report ALL of them, so it
# can never be scored ``full`` without having actually checked analyst + SEC-parse + event data.
_REQUIRED_COVERAGE_CATEGORIES = ("analyst", "sec_parse", "event")
# Per-category availability vocabulary → the coverage_status label it contributes (ok = fully covered).
_CATEGORY_STATUS_TO_COVERAGE = {"ok": "full", "missing": "partial", "restricted": "restricted", "blocked": "blocked"}

_CACHE: dict = {}


class CoverageHonestyError(ValueError):
    """Raised when a row's coverage input / record violates the §11.5 honesty contract (enum, category set, or the
    full ⇔ no-gap invariant)."""


def _enums() -> dict:
    if "enums" not in _CACHE:
        _CACHE["enums"] = json.loads(_CONTRACT_PRESET.read_text(encoding="utf-8"))["design_locked_enums"]
    return _CACHE["enums"]


def _row_sources() -> list:
    return list(_enums()["row_source"])


def _coverage_statuses() -> list:
    return list(_enums()["coverage_status"])  # frozen order == severity order (full < partial < restricted < blocked)


def _nonblank_str(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


_GATING_CATEGORIES = frozenset(_REQUIRED_COVERAGE_CATEGORIES)  # {analyst, sec_parse, event}
_GAP_STATUSES = ("missing", "restricted", "blocked")          # the non-ok category statuses that constitute a gap


def _coverage_rank(category_status) -> int:
    """Severity rank of a per-category status = its index in the FROZEN coverage_status order (single source — the
    one place that maps a category status to a coverage severity, used by both the deriver and the validator)."""
    return _coverage_statuses().index(_CATEGORY_STATUS_TO_COVERAGE[category_status])


def build_row_coverage(row_source, data_checks) -> dict:
    """Classify one row's §11.5 coverage honesty → ``{"row_source", "coverage_status", "coverage_gap_tags"}``.

    ``row_source`` must be one of the frozen ``design_locked_enums`` row_source values. ``data_checks`` must be a
    dict reporting EXACTLY the gating categories (``analyst`` / ``sec_parse`` / ``event``), each a status in
    {ok, missing, restricted, blocked} — a missing / extra category is refused (closed-world + complete: a row
    can't be scored without checking all three). ``coverage_status`` is the WORST-of the per-category checks
    (severity = the frozen coverage_status order), and ``coverage_gap_tags`` lists every non-ok category as
    ``"<category>:<status>"``. So ``full`` is emitted only when all three are ``ok`` (the §11.5 不写 clean rule),
    and the result is self-validated. Raises ``CoverageHonestyError`` on bad input."""
    if row_source not in set(_row_sources()):
        raise CoverageHonestyError(
            "row_source %r not in the frozen design_locked_enums row_source set %s" % (row_source, _row_sources())
        )
    if not isinstance(data_checks, dict):
        raise CoverageHonestyError("data_checks must be a dict, got %r" % (type(data_checks).__name__,))
    if set(data_checks) != set(_REQUIRED_COVERAGE_CATEGORIES):
        raise CoverageHonestyError(
            "data_checks must report EXACTLY the gating categories %s, got %s"
            % (sorted(_REQUIRED_COVERAGE_CATEGORIES), sorted(map(str, data_checks)))
        )

    statuses = _coverage_statuses()
    worst_rank = 0
    gap_tags = []
    for category in _REQUIRED_COVERAGE_CATEGORIES:  # frozen category order (stable, deterministic gap_tags)
        status = data_checks[category]
        if status not in _CATEGORY_STATUS_TO_COVERAGE:
            raise CoverageHonestyError(
                "data_checks[%r] = %r is not a valid category status %s"
                % (category, status, sorted(_CATEGORY_STATUS_TO_COVERAGE))
            )
        worst_rank = max(worst_rank, _coverage_rank(status))
        if status != "ok":
            gap_tags.append("%s:%s" % (category, status))

    coverage = {
        "row_source": row_source,
        "coverage_status": statuses[worst_rank],
        "coverage_gap_tags": gap_tags,
    }
    validate_row_coverage(coverage)
    return coverage


def validate_row_coverage(coverage) -> None:
    """Fail-closed §11.5 honesty gate for a per-row coverage record. Enforces: a dict; ``row_source`` /
    ``coverage_status`` in the frozen enums; ``coverage_gap_tags`` a list of NON-BLANK strings; and the
    bidirectional invariant ``coverage_status == "full" ⇔ coverage_gap_tags is empty`` — a row can NEVER claim a
    clean ``full`` cover while carrying an open gap (§11.5 不写 clean), nor be downgraded below ``full`` without
    naming the gap. Raises ``CoverageHonestyError`` on any violation; a record from ``build_row_coverage`` always
    passes."""
    if not isinstance(coverage, dict):
        raise CoverageHonestyError("coverage record must be a dict")
    if coverage.get("row_source") not in set(_row_sources()):
        raise CoverageHonestyError("coverage row_source %r not in the frozen enum set" % (coverage.get("row_source"),))
    status = coverage.get("coverage_status")
    if status not in set(_coverage_statuses()):
        raise CoverageHonestyError("coverage_status %r not in the frozen enum set" % (status,))
    gap_tags = coverage.get("coverage_gap_tags")
    if not isinstance(gap_tags, list) or not all(_nonblank_str(t) for t in gap_tags):
        raise CoverageHonestyError("coverage_gap_tags must be a list of non-blank strings, got %r" % (gap_tags,))
    if (status == "full") != (len(gap_tags) == 0):
        raise CoverageHonestyError(
            "§11.5 honesty invariant violated: coverage_status=%r with %d gap_tag(s) — 'full' requires ZERO gaps "
            "and any non-full status must name at least one gap (不写 clean)" % (status, len(gap_tags))
        )
    # each gap_tag must be a CONTRACT '<gating-category>:<non-ok-status>' (unique category), and coverage_status
    # must EXACTLY equal the worst-of those tag severities (frozen order) — so a hand-built / upstream record can
    # neither carry an arbitrary / `ok` / unknown tag nor UNDERSTATE a blocked / restricted gap as partial (the
    # §11.5 honesty hole: a weak gate would let a severe evidence gap be reported as a milder coverage state).
    seen = set()
    ranks = []
    for tag in gap_tags:
        parts = tag.split(":")
        if len(parts) != 2 or parts[0] not in _GATING_CATEGORIES or parts[1] not in _GAP_STATUSES:
            raise CoverageHonestyError(
                "gap_tag %r must be '<gating-category>:<non-ok-status>' (category in %s, status in %s)"
                % (tag, sorted(_GATING_CATEGORIES), list(_GAP_STATUSES))
            )
        if parts[0] in seen:
            raise CoverageHonestyError("gap_tag category %r duplicated" % (parts[0],))
        seen.add(parts[0])
        ranks.append(_coverage_rank(parts[1]))
    if ranks:  # status is already guaranteed non-full here (the full ⇔ no-gap check above)
        expected = _coverage_statuses()[max(ranks)]
        if status != expected:
            raise CoverageHonestyError(
                "§11.5 severity mismatch: coverage_status=%r but the gap_tags imply %r (worst-of) — a non-full "
                "status must EXACTLY match its worst gap severity (no understatement / overstatement)" % (status, expected)
            )
