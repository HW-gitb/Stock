# -*- coding: utf-8 -*-
"""US-short core_score CATALYST-SOURCE offline layer (§4.2 catalyst 25% data layer — batch5 Cut 4, offline half).

Design authority: docs/us_short_system_design.md §4.2 (catalyst = realized earnings surprise / analyst revisions
/ 8-K / semantic advisory) + §3.1 (every runtime field records provider / endpoint-or-filing / as_of /
observed_at / coverage / parser / lineage provenance) + §3.5 (event date and observed-at are DISTINCT PIT facts;
no future/look-ahead evidence) + §18.2 (cross-module shared contracts frozen schema-first before consumption).

WHAT THIS IS — the OFFLINE half of the (SR-PROVIDER-001-gated) catalyst data layer. It takes INJECTED per-source
catalyst payloads (the gated live half later fetches FMP earnings/analyst + free SEC 8-K + the advisory LLM),
applies the repo's SINGLE US-ticker identity policy (`canonical_us_ticker`), validates EACH signal's machine
provenance + PIT chronology + coverage/parser fitness against the FROZEN schema-first binding
(docs/us_short_catalyst_source_binding_20260701.json + schemas/us_short_catalyst_source_binding.schema.json;
module consts below are triangulated == that binding by a conformance test), MERGES the fit per-source records
into the flat signal contract `engine/us_short_catalyst.py::catalyst_block` consumes, and emits per-signal
provenance for lineage/audit. A scored catalyst can no longer ride a caller-authored label, a future/impossible
observation clock, a missing/failed coverage, or a free-form "trust-me" lineage.

Identity + hostile keys: each source's ticker keys are canonicalized BEFORE merge (invalid / non-string /
cross-market (A-share) / non-ASCII EXCLUDED; per-source alias collision RAISES). A record's keys must be EXACT
`str` (`type(k) is str`, so a `str` SUBCLASS whose `__eq__`/`__hash__`/`__repr__` is hostile is rejected BEFORE
any set/format touches it), and the diagnostic never echoes the record's own keys.

PIT + provenance (§3.1/§3.5): `resolve_catalyst_signals` requires an explicit decision `as_of` (YYYYMMDD). Every
record MUST carry, besides its value + event-date field, a `provenance` = {provider_id, endpoint_or_filing_type,
source_as_of, observed_at, coverage_status, parser_status, lineage_ref}; validated BEFORE emit — provider/endpoint
== the frozen source; source_as_of + event_date real YYYYMMDD dates, and observed_at a tz-aware RFC3339 INSTANT
normalized to ET (NOT a YYYYMMDD date, so a same-date post-open observation is distinguishable from a premarket
one). The chronology `event_date <= observed_at(date) <= source_as_of <= as_of` (a source snapshot cannot predate
the evidence it contains) AND the observation instant <= the decision-session 09:30 ET cutoff on as_of (a post-open
same-date observation is look-ahead) — the §3.5 sub-date guard. coverage/parser are exact-str ∈ the binding enums
(a list/dict/str-subclass value fails closed as CatalystSourceError, never a raw TypeError); lineage_ref a
STRUCTURED source-bound reference `provider_id:endpoint_or_filing_type:source_as_of#record_id` (not a free-form
string). EMISSION FITNESS: a signal
is emitted to `catalyst_block` ONLY when coverage_status=='full' AND parser_status=='ok'; missing/failed/partial/
degraded are conservatively EXCLUDED (recorded in `excluded`, never a score-ready signal) — the offline slice has
no data-quality downgrade channel to the engine, so it fails closed rather than score partial evidence as clean.

WHAT THIS IS NOT — no fetch (no network/provider; SR-PROVIDER-001 gates the live half + runner wiring), does NOT
re-implement `catalyst_block`'s value/PIT SCORING (single-source that in the engine — the emitted flat `signals`
carry value+date verbatim and the engine decides realized/future/unverified/neutral), and does NOT cross A-share.
The live provider/endpoint SPECIFICS stay gated; only the offline contract SHAPE is frozen here.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from engine.us_short_eligibility_gate import canonical_us_ticker  # the repo's single US ticker identity policy

BINDING_PATH = (Path(__file__).resolve().parents[1]
                / "docs" / "us_short_catalyst_source_binding_20260701.json")

# Frozen catalyst-source contract (== the binding artifact; a conformance test triangulates module const ==
# binding JSON so this consumer copy cannot silently drift — mirrors engine/us_short_catalyst.py governance).
# Each source -> (value_key, date_key, provider_id, endpoint_or_filing_type). value/date use catalyst_block's OWN
# flat key names (no rename). provider/endpoint are the frozen source family; the LIVE endpoint string + real
# values are supplied by the gated live half.
_SOURCES = {
    "earnings": ("earnings_surprise_pct", "earnings_report_date", "fmp", "earnings_surprises"),
    "analyst": ("analyst_revision_net", "analyst_revision_date", "fmp", "analyst_estimate_revisions"),
    "event_8k": ("event_8k_class", "event_8k_date", "sec_edgar", "form_8k"),
    "semantic": ("semantic_advisory_score", "semantic_advisory_date", "llm_advisory", "semantic_advisory"),
}
_PROVENANCE_FIELDS = frozenset({"provider_id", "endpoint_or_filing_type", "source_as_of",
                                "observed_at", "coverage_status", "parser_status", "lineage_ref"})
_COVERAGE_ALLOWED = frozenset({"full", "partial", "missing"})
_PARSER_ALLOWED = frozenset({"ok", "degraded", "failed"})
# EMISSION fitness: only a clean-coverage clean-parse signal is score-ready; everything else is excluded.
_COVERAGE_EMIT = "full"
_PARSER_EMIT = "ok"
# Decision clock (§2.1/§3.5): the catalyst decision is made in the [prior close, decision-session 09:30 ET open)
# window, so an observation must be at or before the 09:30 ET open on `as_of`. `as_of`/`event_date`/`source_as_of`
# are DATE facts (YYYYMMDD); `observed_at` is a tz-aware INSTANT so a post-open same-date observation (look-ahead)
# is distinguishable from a valid premarket one — the sub-date PIT precision §3.5 requires (Codex residual-2 A).
_DECISION_TZ_NAME = "America/New_York"
_DECISION_CUTOFF_HHMM = (9, 30)
# Machine-readable PIT / emission / lineage POLICY consts — triangulated == the binding's frozen fields so the
# offline shared contract §18.2 requires cannot drift between the schema and the engine behavior (Codex residual-3
# B: the binding must freeze the policies, not just the vocabularies). Any drift fails TestBindingConformance.
_CUTOFF_OPERATOR = "strictly_before"      # observed_at < decision_open (half-open, matches resolve_canonical_asof)
_CHRONOLOGY_ORDER = ("event_date", "observed_at", "source_as_of", "as_of")   # each <= the next (non-decreasing)
_LINEAGE_REF_FORMAT = "provider_id:endpoint_or_filing_type:source_as_of#record_id"


class CatalystSourceError(ValueError):
    """An injected catalyst payload is malformed / mis-provenanced / PIT-inconsistent, or a source's ticker keys
    alias to the same canonical US ticker (fail-closed; never fabricates or misattributes a catalyst signal)."""


def _valid_yyyymmdd(s: Any) -> bool:
    """Strict 8-ASCII-digit real-calendar YYYYMMDD. EXACT str (`type(s) is str`) — a str SUBCLASS is rejected so a
    hostile `__le__`/`__eq__` value can never reach the chronology comparisons as a raw exception (residual-2 B
    whole class; real payloads are plain json.load strings)."""
    if not (type(s) is str and len(s) == 8 and s.isascii() and s.isdigit()):
        return False
    try:
        datetime.strptime(s, "%Y%m%d")
        return True
    except ValueError:
        return False


def _et_tz():
    """The canonical decision timezone (America/New_York), or fail-closed (raise) if no tz database — a clock that
    cannot be normalized must never silently pass."""
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError as exc:
        raise CatalystSourceError("无 zoneinfo，无法归一化决策时区，拒绝降级") from exc
    try:
        return ZoneInfo(_DECISION_TZ_NAME)
    except ZoneInfoNotFoundError as exc:
        raise CatalystSourceError(f"无 {_DECISION_TZ_NAME} 时区库(tzdata)，无法归一化决策时区，拒绝降级") from exc


def _valid_observed_at(s: Any) -> bool:
    """Strict RFC3339-like tz-AWARE date-time ('T' separator + offset/Z). Rejects date-only ('20260630' /
    '2026-06-30'), space-separated, and naive (no-offset) strings — a date-only observed clock cannot express the
    §3.5 sub-date decision cutoff (mirrors us_short_status_source._valid_observed_at)."""
    if not (type(s) is str and "T" in s):          # EXACT str: a str-subclass whose slicing/.endswith is hostile
        return False                               # never reaches _observed_at_et's parsing (residual-2 B whole class)
    try:
        dt = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _observed_at_et(observed_at: str) -> datetime:
    """The observation as an ET-normalized aware datetime (DST-aware), so a caller's arbitrary offset cannot shift
    the PIT instant/date. Fail-closed (raise) on an out-of-range boundary-year timestamp whose tz conversion would
    otherwise leak a raw OverflowError. Assumes `observed_at` already passed `_valid_observed_at`."""
    tz = _et_tz()
    inst = datetime.fromisoformat(observed_at[:-1] + "+00:00" if observed_at.endswith("Z") else observed_at)
    try:
        return inst.astimezone(tz)
    except (OverflowError, OSError) as exc:
        raise CatalystSourceError(f"observed_at 超出可归一化时区范围（非真实 provider 时钟）: {observed_at!r}") from exc


def _decision_cutoff(as_of: str) -> datetime:
    """The canonical decision cutoff = the decision-session 09:30 ET open on `as_of` (§2.1). `observed_at` must be
    STRICTLY before this instant (half-open window; 09:30 itself is out-of-window, matching resolve_canonical_asof).
    Assumes `as_of` already passed `_valid_yyyymmdd`."""
    return datetime(int(as_of[:4]), int(as_of[4:6]), int(as_of[6:8]),
                    _DECISION_CUTOFF_HHMM[0], _DECISION_CUTOFF_HHMM[1], tzinfo=_et_tz())


def _valid_lineage_ref(ref: Any, *, provider_id: str, endpoint: str, source_as_of: str) -> bool:
    """A STRUCTURED, source-bound, machine-verifiable lineage reference:
    `provider_id:endpoint_or_filing_type:source_as_of#record_id`, where the prefix EQUALS this signal's
    provider/endpoint/source_as_of and record_id is a nonempty ASCII token (no ':' '#' or whitespace). A free-form
    'trust-me' / 'x' string is rejected (§3.1 lineage must be verifiable, not caller-asserted)."""
    if not (type(ref) is str and ref.isascii()):   # EXACT str: a str-subclass whose .rpartition/__eq__ is hostile
        return False                               # never reaches the prefix compare (residual-2 B whole class)
    prefix, sep, rid = ref.rpartition("#")
    if sep != "#" or not rid or any(c.isspace() for c in rid) or ":" in rid or "#" in rid:
        return False
    return prefix == f"{provider_id}:{endpoint}:{source_as_of}"


def _validate_provenance(prov: Any, *, source_name: str, ticker: str, event_date: Any, as_of: str) -> None:
    """Fail-closed §3.1/§3.5 provenance + PIT check for ONE signal, against the frozen binding for `source_name`.
    provider_id + endpoint == the binding; source_as_of + event_date real YYYYMMDD; observed_at a tz-aware RFC3339
    INSTANT; the chronology `event_date <= observed_at(ET date) <= source_as_of <= as_of` AND the observed instant
    <= the decision-session 09:30 ET cutoff on as_of (no observe-before-event, no source snapshot predating its
    evidence, no observation after the decision cutoff); coverage/parser exact-str ∈ the binding sets (a
    list/dict/str-subclass value fails closed, never a raw TypeError); lineage_ref a structured source-bound
    reference. Raises CatalystSourceError otherwise (BEFORE emit)."""
    _, _, provider_id, endpoint = _SOURCES[source_name]
    # exact-str provenance keys BEFORE `set(prov)` — a str-subclass provenance key with a hostile __eq__/__hash__
    # would otherwise leak a raw exception through the set comparison (same hostile-key class as the record keys).
    if not (isinstance(prov, dict) and all(type(pk) is str for pk in prov) and set(prov) == _PROVENANCE_FIELDS):
        raise CatalystSourceError(
            f"{source_name}[{ticker}].provenance 键须恰为精确 str 的 {sorted(_PROVENANCE_FIELDS)}（§3.1，fail-closed）")
    # EXACT-str provider/endpoint BEFORE `!=` — a str-subclass value whose `__ne__`/`__eq__` is hostile would
    # otherwise leak a raw exception through the comparison (residual-2 B whole class, same as coverage/parser).
    if (type(prov["provider_id"]) is not str or type(prov["endpoint_or_filing_type"]) is not str
            or prov["provider_id"] != provider_id or prov["endpoint_or_filing_type"] != endpoint):
        raise CatalystSourceError(
            f"{source_name}[{ticker}].provenance provider_id/endpoint 须为精确 str 且 == 冻结 binding（{provider_id}/{endpoint}）")
    src_as_of, obs = prov["source_as_of"], prov["observed_at"]
    # source_as_of + event_date are DATE facts (YYYYMMDD); observed_at is a tz-aware INSTANT (§3.5 sub-date cutoff).
    if not _valid_yyyymmdd(src_as_of):
        raise CatalystSourceError(f"{source_name}[{ticker}].provenance source_as_of 须为真实 YYYYMMDD")
    if not _valid_observed_at(obs):
        raise CatalystSourceError(
            f"{source_name}[{ticker}].provenance observed_at 须为 tz-aware RFC3339 时间戳（§3.5 决策截止需瞬时精度，非 YYYYMMDD）")
    if not _valid_yyyymmdd(event_date):
        raise CatalystSourceError(f"{source_name}[{ticker}] 事件日期须为真实 YYYYMMDD（provenance 关系前置；不回显敌意值，仅类型 {type(event_date).__name__}）")
    # A-clock (HALF-OPEN window [prior_close, decision_open), §2.1/§3.5): the observation INSTANT must be STRICTLY
    # before the decision-session 09:30 ET open on as_of — exactly 09:30 is OUT-OF-WINDOW (matching
    # resolve_canonical_asof, the authority for the half-open boundary), so an at-or-post-open same-date
    # observation is look-ahead, distinguishable from a valid premarket one (Codex residual-3 A).
    obs_dt = _observed_at_et(obs)
    if obs_dt >= _decision_cutoff(as_of):
        raise CatalystSourceError(
            f"{source_name}[{ticker}] observed_at 不早于决策开盘（{as_of} 09:30 ET 半开边界；09:30 及之后 out-of-window/look-ahead，§2.1/§3.5）")
    # A-chronology (dates, zero-padded YYYYMMDD -> lexical == date order): event_date <= observed date <=
    # source_as_of <= as_of. A source snapshot cannot predate the evidence it contains; nothing may postdate as_of.
    obs_date = obs_dt.strftime("%Y%m%d")
    if not (event_date <= obs_date):
        raise CatalystSourceError(f"{source_name}[{ticker}] observed_at 早于事件日期（不能在事件发生前观测到；§3.5）")
    if not (obs_date <= src_as_of):
        raise CatalystSourceError(f"{source_name}[{ticker}] source_as_of 早于观测日期（源快照不能早于它含的证据；§3.5）")
    if not (src_as_of <= as_of):
        raise CatalystSourceError(f"{source_name}[{ticker}] source_as_of 晚于决策 as_of={as_of}（look-ahead 证据；§3.5）")
    # B (Codex residual-2 B): type-check the enum VALUE before membership — a list/dict (unhashable) or a hostile
    # str-subclass coverage/parser value must raise CatalystSourceError, never a raw TypeError / hash bomb.
    if type(prov["coverage_status"]) is not str or prov["coverage_status"] not in _COVERAGE_ALLOWED:
        raise CatalystSourceError(
            f"{source_name}[{ticker}].provenance coverage_status 须为精确 str 且 ∈ {sorted(_COVERAGE_ALLOWED)}（fail-closed）")
    if type(prov["parser_status"]) is not str or prov["parser_status"] not in _PARSER_ALLOWED:
        raise CatalystSourceError(
            f"{source_name}[{ticker}].provenance parser_status 须为精确 str 且 ∈ {sorted(_PARSER_ALLOWED)}（fail-closed）")
    if not _valid_lineage_ref(prov["lineage_ref"], provider_id=provider_id, endpoint=endpoint, source_as_of=src_as_of):
        raise CatalystSourceError(
            f"{source_name}[{ticker}].provenance lineage_ref 须为结构化 source-bound 引用 "
            f"'{provider_id}:{endpoint}:{src_as_of}#<record_id>'（非自由文本）")


def _canonical_keyed(source: Any, *, source_name: str, record_keys: frozenset) -> dict:
    """Re-key ONE source's {ticker: record} by canonical US ticker. None -> {}. Invalid / non-string /
    cross-market (A-share) / non-ASCII ticker keys are EXCLUDED (dropped, fail-closed). Two keys aliasing to the
    same canonical US ticker RAISE. Each record must be a dict whose keys are EXACT `str` (`type(k) is str` — a
    `str` SUBCLASS with a hostile `__eq__`/`__hash__`/`__repr__` is rejected BEFORE any set/format), and are
    EXACTLY `record_keys` (value_key + date_key + 'provenance'); the diagnostic echoes only the safe const set,
    never the record's own keys."""
    if source is None:
        return {}
    if not isinstance(source, dict):
        raise CatalystSourceError(f"{source_name} 载荷须为 dict 或 None: {type(source).__name__}")
    out: dict[str, dict] = {}
    for k, v in source.items():
        if type(k) is not str:                # EXACT-str ticker key only: a non-str OR str-SUBCLASS (whose hostile
            continue                          # .strip()/.isascii()/.upper() would leak a raw exception out of
            # canonical_us_ticker) is EXCLUDED here, before the identity policy touches it (whole-key-class hardening)
        ck = canonical_us_ticker(k)
        if ck is None:
            continue                          # invalid / A-share / non-ASCII -> excluded (dropped)
        if not isinstance(v, dict):
            raise CatalystSourceError(f"{source_name}[{ck}] 记录须为 dict: {type(v).__name__}")
        # EXACT-str keys BEFORE any set op: type()+identity invoke NO key dunder, so a str-subclass whose
        # __eq__/__hash__/__repr__ raises is fail-closed here instead of leaking a raw exception via set()/repr().
        if not all(type(rk) is str for rk in v):
            raise CatalystSourceError(f"{source_name}[{ck}] 记录键须为精确 str（拒 str 子类/非串，fail-closed，不回显敌意键）")
        if set(v) != record_keys:             # safe: every key is exactly a plain str
            raise CatalystSourceError(f"{source_name}[{ck}] 记录键须恰为 {sorted(record_keys)}（fail-closed，不回显实际键）")
        if ck in out:
            raise CatalystSourceError(f"{source_name} 规范化后重复 ticker {ck!r}（别名歧义，fail-closed；不静默去重）")
        out[ck] = v
    return out


def resolve_catalyst_signals(*, as_of: str, earnings: Any = None, analyst: Any = None,
                             event_8k: Any = None, semantic: Any = None) -> dict[str, Any]:
    """Merge injected per-source catalyst payloads → the flat per-ticker signal contract `catalyst_block` consumes,
    keyed by canonical US ticker, with validated §3.1/§3.5 provenance + PIT chronology + coverage/parser fitness.

    `as_of` = the reviewed decision clock (real YYYYMMDD); provenance clocks are gated against it. Each source (or
    None) = {ticker: {<value_key>, <date_key>: "YYYYMMDD", "provenance": {...7 §3.1 fields...}}} using
    `catalyst_block`'s own flat value/date key names (earnings/analyst=fmp, event_8k=sec_edgar, semantic=llm).

    Every record MUST carry all three (value + event date + provenance); a partial/foreign-keyed/hostile-keyed
    record fails closed. `observed_at` is a tz-aware RFC3339 INSTANT (source_as_of/event date stay YYYYMMDD).
    Provenance is validated BEFORE emit (provider/endpoint pinned, real clocks, PIT chronology
    event<=observed(ET date)<=source_as_of<=as_of AND observed instant <= the 09:30 ET decision cutoff on as_of,
    exact-str coverage/parser enums, structured lineage). A signal is
    EMITTED only when coverage=='full' AND parser=='ok'; missing/failed/partial/degraded go to `excluded`
    (conservative fail-closed — never score-ready). Emitted `signals` feed `catalyst_block`, which OWNS value/PIT
    scoring. Returns {signals: {ticker: {value_key, date_key}}, provenance: {ticker: {value_key: {…}}},
    excluded: {ticker: {value_key: reason}}}. Raises CatalystSourceError on any malformed/PIT-inconsistent input.
    """
    if not _valid_yyyymmdd(as_of):
        raise CatalystSourceError(f"as_of 须为真实 YYYYMMDD 决策时钟（不回显敌意值，仅类型 {type(as_of).__name__}）")
    canon = {}
    for name, (value_key, date_key, _p, _e) in _SOURCES.items():
        src = {"earnings": earnings, "analyst": analyst, "event_8k": event_8k, "semantic": semantic}[name]
        canon[name] = _canonical_keyed(src, source_name=name,
                                       record_keys=frozenset({value_key, date_key, "provenance"}))
    signals: dict[str, dict] = {}
    provenance: dict[str, dict] = {}
    excluded: dict[str, dict] = {}
    for name, (value_key, date_key, _p, _e) in _SOURCES.items():
        for ct, rec in canon[name].items():
            _validate_provenance(rec["provenance"], source_name=name, ticker=ct,
                                 event_date=rec[date_key], as_of=as_of)          # fail-closed before emit
            prov = rec["provenance"]
            if prov["coverage_status"] != _COVERAGE_EMIT or prov["parser_status"] != _PARSER_EMIT:
                excluded.setdefault(ct, {})[value_key] = (
                    f"coverage={prov['coverage_status']}/parser={prov['parser_status']}")   # not score-ready
                continue
            sig = signals.setdefault(ct, {})
            sig[value_key] = rec[value_key]        # verbatim; catalyst_block owns value/PIT validation + scoring
            sig[date_key] = rec[date_key]
            provenance.setdefault(ct, {})[value_key] = dict(prov)   # validated §3.1 lineage (defensive copy)
    return {"signals": signals, "provenance": provenance, "excluded": excluded}
