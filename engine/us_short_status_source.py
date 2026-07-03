# -*- coding: utf-8 -*-
"""US-short Pass1 status-source OFFLINE layer — batch5 Cut 1, slice 1a
(R-USSHORT-BATCH5-PASS1-CRITICAL-STATUS-HEALTH-FAILOPEN remainder (a), the OFFLINE half).

Design authority: docs/us_short_system_design.md §3.3 (critical status unknown must NOT be assumed clean) /
§4.0–4.1 (Pass1 安全闸) / §3.7 (provider health) / §18.0 P0 (SR-PROVIDER-001). Frozen per-flag contract:
docs/us_short_batch5_status_source_binding_20260629.json (+ schemas/us_short_batch5_status_source_binding.schema.json).

WHAT THIS IS — the OFFLINE half of the R1 remainder. It (1) parses INJECTED status-source payloads (the caller
supplies them: fixtures in tests, the gated live fetch in 1b) into ONE per-ticker status record with per-flag
provenance; (2) maps that record into the cheap_eligible row contract so an UNKNOWN conservative-reject flag
stays unknown (OMITTED -> cheap_eligible's existing conservative reject; NEVER clean-by-omission, §3.3); and
(3) classifies per-source fetch outcomes into a provider-health/block signal that is never swallowed (a
critical-all-fail run must block / no-emit, not report "completed", per the binding's
provider_failure_health_policy).

WHAT THIS IS NOT - live 1b (SR-PROVIDER-001): NO network/provider call (it consumes payloads, never fetches).
The universe runner may inject already-resolved offline status records into apply_pass1 for tests/fixtures and
schema validation, but the live producer / run_fetch provider wiring remains separately gated. Pure / offline;
no A-share crossing.

Per-flag gate policy (== the frozen binding's unknown_policy, triangulated by a test):
  * delisted / halted / otc  -> conservative_reject: a True/False value needs a real observation; UNKNOWN
    (source not observed / field absent / partial-coverage absence) is OMITTED from the row, so
    cheap_eligible rejects it (status_<flag>_unknown_or_invalid). Never clean-by-omission.
  * bankruptcy -> positive_detection_only (binding bankruptcy_screen_type + mark_unscreened_not_clean): the
    gate flag is True ONLY when an SEC 8-K Item 1.03 is positively found; screened_no_filing AND unscreened
    both map to gate False. "mark_unscreened_not_clean" means the provenance records screen_status=unscreened
    (NO proof of clean) — but an unscreened universe is NOT rejected at Pass1 (bankruptcy is a best-effort
    positive screen; the hard solvency path is Pass2 / hard_veto). This is what stops "don't screen
    bankruptcy" from collapsing the whole universe to ineligible.
"""
from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from engine.us_short_eligibility_gate import canonical_us_ticker, _V1_EXCHANGE_WHITELIST
from engine.us_short_market_calendar import load_market_calendar, sessions_for_window

ACCESS_PACKET_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "us_short_batch5_status_source_access_packet.schema.json"
)
MARKET_CALENDAR_PATH = (
    Path(__file__).resolve().parents[1]
    / "presets"
    / "us_short_market_calendar_2026_2027.json"
)

# == engine/us_short_eligibility_gate._V1_DISQUALIFYING_STATUS_FLAGS and the frozen status-source binding's
# four status_flag_bindings; a test triangulates all three so the disqualifier set cannot drift.
DISQUALIFYING_FLAGS = ("delisted", "halted", "bankruptcy", "otc")

# flag -> authorized source id (== the frozen binding status_flag_bindings; triangulated by a test).
FLAG_SOURCE = {
    "delisted": "ticker_reference",
    "otc": "ticker_reference",
    "halted": "exchange_halt_feed",
    "bankruptcy": "sec_8k_item_103",
}
# flag -> gate policy for a non-observed / unknown status (the binding unknown_policy mapped to its gate effect;
# triangulated by a test against the binding doc).
FLAG_GATE_POLICY = {
    "delisted": "conservative_reject",
    "halted": "conservative_reject",
    "otc": "conservative_reject",
    "bankruptcy": "positive_detection_only",
}

STATUS_SOURCES = ("ticker_reference", "exchange_halt_feed", "sec_8k_item_103")
# Sources whose failure leaves a conservative_reject flag unscreenable: a run with EVERY critical source failed
# must block / no-emit (binding critical_source_all_fail_must_block_or_no_emit). sec_8k is best-effort
# (positive_detection_only; an unscreened bankruptcy universe is a legal state), so it is NOT critical.
CRITICAL_STATUS_SOURCES = ("ticker_reference", "exchange_halt_feed")

_SOURCE_OK = frozenset({"ok", "degraded"})
_SOURCE_FAIL = frozenset({"down", "missing"})
_SOURCE_STATES = _SOURCE_OK | _SOURCE_FAIL

BANKRUPTCY_SCREEN_STATES = frozenset({"bankrupt_8k_found", "screened_no_filing", "unscreened"})

# Single source: otc uses the SAME §3.1 exchange whitelist as the cheap-eligibility gate (the binding's otc
# semantics bind otc to "the §3.1 exchange whitelist"), so importing it makes drift impossible (a test
# triangulates this == eligibility_gate._V1_EXCHANGE_WHITELIST).
_DEFAULT_EXCHANGE_WHITELIST = _V1_EXCHANGE_WHITELIST


class StatusSourceError(ValueError):
    """An injected status payload is malformed (fail-closed; this layer never fabricates a clean status)."""


def _valid_as_of(s) -> bool:
    """Strict YYYY-MM-DD `as_of` (a parseable PIT date), else False. This layer's purpose is per-flag PIT
    provenance, so a non-date clock must never pass (R-USSHORT-BATCH5-STATUS-SOURCE-CLOCK-AND-ACCESS-PACKET-PIN-GAP).
    ASCII-only: `datetime.strptime` would otherwise accept Unicode decimal digits (fullwidth '２０２６', Arabic-Indic)
    as a "date" — a non-ASCII clock would leak into a persisted authorization-relevant field. Mirrors the
    project-wide `us_short_market_calendar._real_yyyymmdd` `.isascii()` guard (single convention)."""
    if not (isinstance(s, str) and len(s) == 10 and s.isascii()):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _valid_observed_at(s) -> bool:
    """Strict RFC3339-like `observed_at`: a 'T'-separated, TIMEZONE-AWARE date-time (e.g.
    '2026-06-30T00:00:00+08:00' or '...Z'). Rejects date-only ('2026-06-30'), space-separated
    ('2026-06-30 12:00:00'), and NO-timezone ('2026-06-30T12:00:00') strings — a date-only / tz-free observed
    clock is ambiguous PIT evidence at the boundary that later removes hardwired False flags
    (R-USSHORT-BATCH5-STATUS-SOURCE-CLOCK-AND-ACCESS-PACKET-PIN-GAP residual). Also reused to semantically
    validate the access-packet `generated_at` (same RFC3339 contract, single source)."""
    if not (isinstance(s, str) and "T" in s):     # require the 'T' separator (rejects date-only + space-sep)
        return False
    try:
        dt = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return False
    return dt.tzinfo is not None                   # require timezone-aware (rejects naive / no-offset)


# Canonical decision timezone for status PIT evidence == the frozen NYSE/NASDAQ market calendar's `timezone`
# (engine/us_short_market_calendar.py pins "America/New_York"); DST-aware via zoneinfo. The observed instant is
# normalized to ET BEFORE its PIT date is taken, so a caller-supplied UTC offset cannot shift the decision date
# (R-USSHORT-BATCH5-STATUS-SOURCE-CLOCK-AND-ACCESS-PACKET-PIN-GAP residual A1).
_DECISION_TZ_NAME = "America/New_York"
def _observed_at_et_date(observed_at):
    """The observation's calendar date in the canonical US decision timezone (ET, DST-aware). The tz-aware
    instant is converted to ET BEFORE the date is taken, so a caller's arbitrary offset cannot shift the PIT
    date (residual A1: `...T23:59:59-12:00` is next-day ET; `...T00:30:00Z` is same-day ET). Fail-closed (raise)
    if no tz database is available — a clock that cannot be normalized must never silently pass. Assumes
    `observed_at` already passed `_valid_observed_at` (tz-aware)."""
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError as exc:                       # no zoneinfo at all -> cannot normalize -> fail closed
        raise StatusSourceError("无 zoneinfo，无法归一化决策时区，拒绝降级") from exc
    try:
        tz = ZoneInfo(_DECISION_TZ_NAME)
    except ZoneInfoNotFoundError as exc:             # no tz database (tzdata) -> cannot normalize -> fail closed
        raise StatusSourceError(f"无 {_DECISION_TZ_NAME} 时区库(tzdata)，无法归一化决策时区，拒绝降级") from exc
    inst = datetime.fromisoformat(observed_at[:-1] + "+00:00" if observed_at.endswith("Z") else observed_at)
    return inst.astimezone(tz).date()


def _parse_observed_at(observed_at):
    return datetime.fromisoformat(
        observed_at[:-1] + "+00:00" if observed_at.endswith("Z") else observed_at)


@lru_cache(maxsize=1)
def _status_calendar():
    return load_market_calendar(MARKET_CALENDAR_PATH)


@lru_cache(maxsize=64)
def _decision_window_bounds(as_of):
    """Return [prior settled close, decision-session open) in ET for a canonical decision date."""
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        tz = ZoneInfo(_DECISION_TZ_NAME)
    except (ImportError, ZoneInfoNotFoundError) as exc:
        raise StatusSourceError(f"无 {_DECISION_TZ_NAME} 时区库，无法校验 status 决策窗口") from exc
    try:
        compact = as_of.replace("-", "")
        sessions = sessions_for_window(compact, calendar=_status_calendar(), back_days=15, fwd_days=0)
    except (OSError, ValueError) as exc:
        raise StatusSourceError(f"无法从冻结市场日历解析 status 决策窗口: {as_of!r}") from exc
    if len(sessions) < 2 or sessions[-1]["date"] != compact:
        raise StatusSourceError(f"as_of 不是冻结 NYSE/NASDAQ 日历中的 canonical 决策 session: {as_of!r}")
    prior, decision = sessions[-2], sessions[-1]
    prior_close = datetime.strptime(
        f"{prior['date']}T{prior['close']}", "%Y%m%dT%H:%M").replace(tzinfo=tz)
    decision_open = datetime.strptime(
        f"{decision['date']}T{decision['open']}", "%Y%m%dT%H:%M").replace(tzinfo=tz)
    return prior_close, decision_open


def _observed_at_in_decision_window(observed_at, as_of) -> bool:
    """True only from the prior settled session close up to (not including) decision-session RTH open."""
    prior_close, decision_open = _decision_window_bounds(as_of)
    instant_et = _parse_observed_at(observed_at).astimezone(prior_close.tzinfo)
    return prior_close <= instant_et < decision_open


def _source_observation(payload, source_id, *, as_of, record_observed_at, require_current):
    """Return (usable, source_observed_at, coverage) for one independently-clocked source payload."""
    if not _observed(payload, source_id):
        return False, None, "observed_failed" if isinstance(payload, dict) else "not_consulted"
    source_observed_at = payload.get("observed_at")
    if not _valid_observed_at(source_observed_at):
        raise StatusSourceError(f"{source_id}.observed_at 须为可解析 tz-aware ISO-8601 时间戳")
    if _parse_observed_at(source_observed_at) > _parse_observed_at(record_observed_at):
        raise StatusSourceError(f"{source_id}.observed_at 不得晚于 status record observed_at")
    if require_current and not _observed_at_in_decision_window(source_observed_at, as_of):
        return False, source_observed_at, "stale"
    return True, source_observed_at, "observed"


def _observed(payload, source_id):
    """A source payload is either None (source not consulted -> its flags unknown) or a dict with an explicit
    boolean `observed`. A non-None / non-dict payload, or a non-bool `observed`, is fail-closed (raise) — a
    malformed payload is NEVER silently treated as a clean observation."""
    if payload is None:
        return False
    if not isinstance(payload, dict):
        raise StatusSourceError(f"{source_id} payload 须为 dict 或 None: {type(payload).__name__}")
    obs = payload.get("observed")
    if obs is not True and obs is not False:
        raise StatusSourceError(f"{source_id} payload.observed 须为 bool（严格）")
    return obs is True


def _canonical_keyed(mapping, *, source_id):
    """Re-key a {ticker: record} source mapping by CANONICAL US ticker so a non-canonical-but-valid key
    ('aapl' -> 'AAPL') still matches the canonical lookup — else a missed SEC 8-K bankruptcy would be a
    fail-OPEN and a missed active listing an over-reject. A key that is NOT a valid US symbol RAISES
    (fail-closed): silently dropping it could discard a positive-detection `bankrupt_8k_found` record keyed by
    a malformed string, re-opening the bankruptcy fail-open — a keyed RECORD dict must never lose a record
    silently (UNLIKE `_resolve_halted`'s MEMBERSHIP set, where a non-canonical entry is just a non-universe
    symbol safe to drop). Two keys canonicalizing to the SAME ticker are ambiguous -> raise."""
    out = {}
    for k, v in mapping.items():
        ck = canonical_us_ticker(k)
        if ck is None:
            raise StatusSourceError(
                f"{source_id} 含非规范 ticker 键 {k!r}（不静默丢弃——丢弃可能漏掉 positive-detection 的 "
                "bankrupt_8k_found 记录=fail-open；fail-closed，数据层须供规范键）")
        if ck in out:
            raise StatusSourceError(f"{source_id} 规范化后重复 ticker 键 {ck!r}（歧义记录，fail-closed）")
        out[ck] = v
    return out


def _resolve_delisted_and_otc(ref, ticker, *, exchange_whitelist, as_of, record_observed_at):
    """ticker_reference observation -> (delisted_value, delisted_prov, otc_value, otc_prov). value is
    True (disqualified) / False (screened clean) / None (unknown). Absence from a FULL-coverage active-listing
    reference => delisted True (binding); absence from a PARTIAL (sample) reference => unknown (a sample must
    NOT mass-mark non-sampled names delisted)."""
    usable, source_clock, cov = _source_observation(
        ref, "ticker_reference", as_of=as_of, record_observed_at=record_observed_at, require_current=True)
    base = {"source_id": "ticker_reference", "as_of": as_of, "observed_at": source_clock}
    if not usable:
        return (None, {**base, "reference_active_value": None, "coverage": cov},
                None, {**base, "primary_exchange_value": None, "coverage": cov})

    coverage = ref.get("coverage")
    if coverage not in ("full", "partial"):
        raise StatusSourceError("ticker_reference.coverage 须 ∈ {full, partial}")
    raw_listings = ref.get("active_listings")
    if not isinstance(raw_listings, dict):
        raise StatusSourceError("ticker_reference.active_listings 须为 dict")
    listings = _canonical_keyed(raw_listings, source_id="ticker_reference.active_listings")
    rec = listings.get(ticker)

    if rec is None:
        # absent: delisted only under FULL coverage; a partial/sample reference cannot prove delisting.
        delisted_v = True if coverage == "full" else None
        return (delisted_v, {**base, "reference_active_value": None,
                             "coverage": "absent_full" if coverage == "full" else "absent_partial"},
                None, {**base, "primary_exchange_value": None,
                       "coverage": "absent_full" if coverage == "full" else "absent_partial"})

    if not isinstance(rec, dict):
        raise StatusSourceError(f"ticker_reference.active_listings[{ticker}] 须为 dict")
    active_val = rec.get("active")
    prim = rec.get("primary_exchange")
    # delisted: present + active is True -> clean False; present + active not-True -> delisted True.
    delisted_v = False if active_val is True else True
    delisted_prov = {**base, "reference_active_value": active_val if isinstance(active_val, bool) else None,
                     "coverage": "observed"}
    # otc: a real primary-exchange value in the whitelist -> clean False; any other real venue -> otc True;
    # missing / non-string venue -> unknown (None).
    if isinstance(prim, str) and prim:
        otc_v = False if prim in exchange_whitelist else True
        otc_prim = prim
    else:
        otc_v = None
        otc_prim = None
    otc_prov = {**base, "primary_exchange_value": otc_prim, "coverage": "observed"}
    return delisted_v, delisted_prov, otc_v, otc_prov


def _resolve_halted(feed, ticker, *, as_of, record_observed_at):
    """exchange_halt_feed observation -> (halted_value, prov). The feed is the complete list of CURRENT halts:
    observed + in feed -> True; observed + absent -> False (absence from an observed halt feed IS evidence of
    not-halted, unlike the listing reference); feed not observed -> unknown."""
    usable, source_clock, cov = _source_observation(
        feed, "exchange_halt_feed", as_of=as_of, record_observed_at=record_observed_at, require_current=True)
    base = {"source_id": "exchange_halt_feed", "as_of": as_of, "observed_at": source_clock}
    if not usable:
        return None, {**base, "halt_feed_observed": cov == "stale", "coverage": cov}
    halted = feed.get("halted_symbols")
    if not isinstance(halted, list):
        raise StatusSourceError("exchange_halt_feed.halted_symbols 须为 list")
    halted_set = {canonical_us_ticker(s) for s in halted}
    halted_set.discard(None)
    return (ticker in halted_set), {**base, "halt_feed_observed": True, "coverage": "observed"}


def _resolve_bankruptcy(screen, ticker, *, as_of, record_observed_at):
    """sec_8k_item_103 observation -> (gate_value, prov). positive_detection_only: gate True iff a bankruptcy
    8-K was positively found; screened_no_filing AND unscreened both -> gate False (the provenance records the
    real screen_status; unscreened is NOT a Pass1 rejection — best-effort, binding mark_unscreened_not_clean)."""
    usable, source_clock, cov = _source_observation(
        screen, "sec_8k_item_103", as_of=as_of, record_observed_at=record_observed_at, require_current=True)
    base = {"source_id": "sec_8k_item_103", "as_of": as_of, "observed_at": source_clock}
    lookback = None
    if isinstance(screen, dict):
        lookback = screen.get("lookback_window") if isinstance(screen.get("lookback_window"), str) else None
    if isinstance(screen, dict) and screen.get("observed") is True:
        if not (isinstance(lookback, str) and lookback.strip()):
            raise StatusSourceError("sec_8k_item_103.lookback_window 须为非空字符串（不得伪造 screened coverage）")
    if not usable:
        if cov == "stale":
            raw_by_ticker = screen.get("by_ticker")
            if isinstance(raw_by_ticker, dict):
                by_ticker = _canonical_keyed(raw_by_ticker, source_id="sec_8k_item_103.by_ticker")
                rec = by_ticker.get(ticker)
                if isinstance(rec, dict) and rec.get("screen_status") == "bankrupt_8k_found":
                    accession = rec.get("filing_accession")
                    if not (isinstance(accession, str) and accession):
                        raise StatusSourceError("stale bankrupt_8k_found 须带 filing_accession（正向证据不可失真）")
                    return True, {
                        **base, "lookback_window": lookback, "filing_accession_if_found": accession,
                        "screen_status": "bankrupt_8k_found", "coverage": "stale_positive"}
        return False, {**base, "lookback_window": lookback, "filing_accession_if_found": None,
                       "screen_status": "unscreened",
                       "coverage": cov}
    raw_by_ticker = screen.get("by_ticker")
    if not isinstance(raw_by_ticker, dict):
        raise StatusSourceError("sec_8k_item_103.by_ticker 须为 dict")
    by_ticker = _canonical_keyed(raw_by_ticker, source_id="sec_8k_item_103.by_ticker")
    rec = by_ticker.get(ticker)
    if rec is None:
        return False, {**base, "lookback_window": lookback, "filing_accession_if_found": None,
                       "screen_status": "unscreened", "coverage": "not_in_screen_set"}
    if not isinstance(rec, dict):
        raise StatusSourceError(f"sec_8k_item_103.by_ticker[{ticker}] 须为 dict")
    screen_status = rec.get("screen_status")
    if not isinstance(screen_status, str) or screen_status not in BANKRUPTCY_SCREEN_STATES:
        raise StatusSourceError(f"sec_8k_item_103 screen_status 非法: {screen_status!r}")
    accession = rec.get("filing_accession") if isinstance(rec.get("filing_accession"), str) and rec.get("filing_accession") else None
    found = screen_status == "bankrupt_8k_found"
    if found and not accession:
        raise StatusSourceError("bankrupt_8k_found 须带 filing_accession（正向检出必须可追溯）")
    return found, {
        **base, "lookback_window": lookback,
        "filing_accession_if_found": accession if found else None,   # only a positively-found 8-K carries an accession
        "screen_status": screen_status, "coverage": "observed"}


def resolve_status_record(ticker, *, ticker_reference=None, halt_feed=None, bankruptcy_screen=None,
                          as_of, observed_at, exchange_whitelist=_DEFAULT_EXCHANGE_WHITELIST):
    """Resolve ONE ticker's four disqualifying status flags from injected source payloads, with provenance.

    Each source payload is None (not consulted -> its flags unknown) or a dict {observed: bool, ...}. Returns a
    status record: {ticker, as_of, observed_at, status_flags_sourced: True, flags: {flag: {value, provenance...}}}.
    value: True (disqualified) / False (screened clean) / None (unknown). bankruptcy.value is always bool
    (positive_detection_only). status_flags_sourced is True because real sources were consulted (vs the runner's
    hardwired-False round-1 rows); the per-flag coverage records WHAT was actually observed.
    """
    ct = canonical_us_ticker(ticker)
    if ct is None:
        raise StatusSourceError(f"非规范 US ticker: {ticker!r}")
    if not (_valid_as_of(as_of) and _valid_observed_at(observed_at)):
        raise StatusSourceError("as_of 须为 YYYY-MM-DD、observed_at 须为可解析 tz-aware ISO-8601 日期时间（PIT 时钟须可解析，不接受自由文本）")
    if not _observed_at_in_decision_window(observed_at, as_of):
        raise StatusSourceError(
            "status record observed_at 须在冻结市场日历的 [上一 session 收盘, 决策 session 开盘) 窗口内")
    if isinstance(exchange_whitelist, str) or not all(isinstance(x, str) and x for x in exchange_whitelist):
        raise StatusSourceError("exchange_whitelist 须为非空字符串的集合（非裸字符串；防 tuple('NYSE') footgun）")
    wl = tuple(exchange_whitelist)

    delisted_v, delisted_prov, otc_v, otc_prov = _resolve_delisted_and_otc(
        ticker_reference, ct, exchange_whitelist=wl, as_of=as_of, record_observed_at=observed_at)
    halted_v, halted_prov = _resolve_halted(
        halt_feed, ct, as_of=as_of, record_observed_at=observed_at)
    bankruptcy_v, bankruptcy_prov = _resolve_bankruptcy(
        bankruptcy_screen, ct, as_of=as_of, record_observed_at=observed_at)

    return {
        "ticker": ct,
        "as_of": as_of,
        "observed_at": observed_at,
        "status_flags_sourced": True,
        "flags": {
            "delisted": {"value": delisted_v, **delisted_prov},
            "halted": {"value": halted_v, **halted_prov},
            "otc": {"value": otc_v, **otc_prov},
            "bankruptcy": {"value": bankruptcy_v, **bankruptcy_prov},
        },
    }


def status_flags_for_row(record, *, row_ticker):
    """Map a status record -> (row_flags, provenance) for the cheap_eligible row contract, BOUND to `row_ticker`.

    BEFORE any flag is emitted this requires (a) validate_status_record(record) and (b)
    record["ticker"] == canonical_us_ticker(row_ticker), so a caller can NEVER apply one ticker's status record
    to a different ticker's row (R-USSHORT-BATCH5-STATUS-RECORD-ROW-BINDING-GAP — a detached clean record would
    re-introduce the R1 fail-open for the wrong symbol). A fabricated record, a noncanonical row_ticker, or a
    record/row ticker mismatch all raise StatusSourceError (fail-closed).

    A conservative_reject flag (delisted/halted/otc) with a KNOWN bool value is set on the row; an UNKNOWN
    (None) value is OMITTED, so cheap_eligible's existing conservative reject fires (status_<flag>_unknown_or_invalid)
    — unknown stays unknown, never clean-by-omission. bankruptcy (positive_detection_only) is ALWAYS set
    (True only when an 8-K was found). `provenance` is the record's per-flag provenance, ready for the 1b
    per-row lineage. The returned row_flags are merged into the universe row BEFORE calling cheap_eligible.
    """
    if not validate_status_record(record):
        raise StatusSourceError("status record 结构非法（validate_status_record=False）")
    rt = canonical_us_ticker(row_ticker)
    if rt is None or record["ticker"] != rt:
        raise StatusSourceError(
            f"status record ticker={record['ticker']!r} 与 row_ticker={row_ticker!r}（canonical={rt!r}）不绑定；"
            "绝不把一票的状态套到另一票的行（R-USSHORT-BATCH5-STATUS-RECORD-ROW-BINDING-GAP）")
    row_flags = {}
    for flag in DISQUALIFYING_FLAGS:
        value = record["flags"][flag]["value"]
        if FLAG_GATE_POLICY[flag] == "positive_detection_only":
            row_flags[flag] = value is True          # always a bool; True only on positive detection
        elif value is True or value is False:
            row_flags[flag] = value                  # known conservative_reject observation
        # value is None -> OMIT so cheap_eligible conservative-rejects (unknown stays unknown)
    provenance = {flag: dict(record["flags"][flag]) for flag in DISQUALIFYING_FLAGS}
    return row_flags, provenance


def classify_status_source_outcomes(outcomes):
    """Classify per-source fetch OUTCOMES into a provider-health / block signal (NEVER swallowed).

    `outcomes` maps a status source id -> one of {ok, degraded, down, missing}. A source absent from the map is
    treated as `missing` (a source we did not account for is fail-closed, not assumed ok). Passing an unknown
    source id, or an invalid state, raises (the classifier cannot consider a non-status source). Per the binding
    provider_failure_health_policy, every failure is classified + counted, and if EVERY critical source
    (ticker_reference + exchange_halt_feed) failed, the run MUST block / no-emit (it cannot emit a "completed"
    all-rejected universe). Returns {per_source, failed_sources, failed_count, total_sources, critical_failed,
    critical_all_failed, block_or_no_emit}.
    """
    if not isinstance(outcomes, dict):
        raise StatusSourceError("outcomes 须为 dict {status_source: state}")
    per_source = {}
    for src, state in outcomes.items():
        if src not in STATUS_SOURCES:
            raise StatusSourceError(
                f"classify 不得考虑非 status 源 {src!r}（仅 {list(STATUS_SOURCES)}）")
        if state not in _SOURCE_STATES:
            raise StatusSourceError(f"源 {src!r} 状态非法 {state!r}（须 ∈ {sorted(_SOURCE_STATES)}）")
        per_source[src] = state
    for src in STATUS_SOURCES:
        per_source.setdefault(src, "missing")        # unaccounted source -> missing -> failed (fail-closed)

    failed_sources = sorted(s for s in STATUS_SOURCES if per_source[s] in _SOURCE_FAIL)
    critical_failed = sorted(s for s in CRITICAL_STATUS_SOURCES if per_source[s] in _SOURCE_FAIL)
    critical_all_failed = set(critical_failed) == set(CRITICAL_STATUS_SOURCES)
    return {
        "per_source": per_source,
        "failed_sources": failed_sources,
        "failed_count": len(failed_sources),
        "total_sources": len(STATUS_SOURCES),
        "critical_failed": critical_failed,
        "critical_all_failed": critical_all_failed,
        "block_or_no_emit": critical_all_failed,
    }


_FLAG_PROV_FIELDS = {
    "delisted": {"source_id", "as_of", "observed_at", "reference_active_value", "coverage", "value"},
    "halted": {"source_id", "as_of", "observed_at", "halt_feed_observed", "coverage", "value"},
    "otc": {"source_id", "as_of", "observed_at", "primary_exchange_value", "coverage", "value"},
    "bankruptcy": {"source_id", "as_of", "observed_at", "lookback_window", "filing_accession_if_found",
                   "coverage", "screen_status", "value"},
}

# The (value, coverage) [+ screen_status for bankruptcy] combinations resolve_status_record can ACTUALLY emit,
# per flag — validate_status_record accepts ONLY these (closed-world "according to the resolver's emitted
# states", R-USSHORT-BATCH5-STATUS-RECORD-ROW-BINDING-GAP). Derived directly from resolve_status_record; the
# positive-control tests run real resolver outputs through validate to prove no over-constraint. This single
# table is the closed-world coverage-enum + value-domain + value↔coverage cross-field check in one.
_VALID_DELISTED = frozenset({
    (False, "observed"), (True, "observed"), (True, "absent_full"),
    (None, "absent_partial"), (None, "observed_failed"), (None, "not_consulted"), (None, "stale")})
_VALID_OTC = frozenset({
    (False, "observed"), (True, "observed"), (None, "observed"),
    (None, "absent_full"), (None, "absent_partial"), (None, "observed_failed"), (None, "not_consulted"),
    (None, "stale")})
_VALID_HALTED = frozenset({
    (True, "observed"), (False, "observed"), (None, "observed_failed"), (None, "not_consulted"),
    (None, "stale")})
_VALID_BANKRUPTCY = frozenset({   # (value, coverage, screen_status)
    (True, "observed", "bankrupt_8k_found"),
    (True, "stale_positive", "bankrupt_8k_found"),
    (False, "observed", "screened_no_filing"),
    (False, "not_in_screen_set", "unscreened"),
    (False, "observed_failed", "unscreened"),
    (False, "not_consulted", "unscreened"),
    (False, "stale", "unscreened")})


def _bool_or_none(x):
    return x is True or x is False or x is None


def _nonempty_str_or_none(x):
    return x is None or (isinstance(x, str) and bool(x))


def validate_status_record(record):
    """True iff `record` is a status record `resolve_status_record` could ACTUALLY have emitted — the
    anti-fabrication validator (mirrors provider_health.validate_provider_health_result). Closed-world on every
    field (R-USSHORT-BATCH5-STATUS-RECORD-ROW-BINDING-GAP):

      * exact {ticker, as_of, observed_at, status_flags_sourced, flags} shape; `ticker` is a CANONICAL US symbol
        (noncanonical / A-share code -> reject); status_flags_sourced is True;
      * `flags` covers EXACTLY the four disqualifiers, each with its binding-required provenance fields + the
        correct source_id;
      * each flag's `as_of` equals the record decision date, while its source-owned `observed_at` is independently
        validated, not later than the record clock, and either inside the exact decision window or marked stale;
      * the (value, coverage) [+ screen_status for bankruptcy] tuple is one the resolver can emit (the _VALID_*
        tables) — closed-world coverage-enum + value-domain + value↔coverage cross-field in one;
      * source-specific provenance value TYPES match the resolver: reference_active_value bool|None,
        primary_exchange_value nonempty-str|None, halt_feed_observed strict bool == (coverage=='observed'),
        lookback_window str|None, filing_accession_if_found nonempty-str IFF a bankruptcy 8-K was found (else None).
    """
    if not (isinstance(record, dict)
            and set(record) == {"ticker", "as_of", "observed_at", "status_flags_sourced", "flags"}):
        return False
    ticker, as_of, observed_at = record["ticker"], record["as_of"], record["observed_at"]
    if not (isinstance(ticker, str) and canonical_us_ticker(ticker) == ticker      # canonical top ticker
            and _valid_as_of(as_of)                                                # parseable PIT date
            and _valid_observed_at(observed_at)                                    # parseable tz-aware timestamp
            and _observed_at_in_decision_window(observed_at, as_of)                # exact prior-close -> decision-open window
            and record["status_flags_sourced"] is True):
        return False
    flags = record["flags"]
    if not (isinstance(flags, dict) and set(flags) == set(DISQUALIFYING_FLAGS)):
        return False
    for flag in DISQUALIFYING_FLAGS:
        prov = flags[flag]
        if not (isinstance(prov, dict) and set(prov) == _FLAG_PROV_FIELDS[flag]):
            return False
        if prov["source_id"] != FLAG_SOURCE[flag]:
            return False
        if prov["as_of"] != as_of:
            return False
        source_clock, coverage = prov["observed_at"], prov["coverage"]
        if not isinstance(coverage, str):
            return False
        no_observation = coverage in {"not_consulted", "observed_failed"}
        if no_observation:
            if source_clock is not None:
                return False
        else:
            if not _valid_observed_at(source_clock):
                return False
            if _parse_observed_at(source_clock) > _parse_observed_at(observed_at):
                return False
            in_window = _observed_at_in_decision_window(source_clock, as_of)
            if (coverage in {"stale", "stale_positive"}) == in_window:
                return False
        value, coverage = prov["value"], prov["coverage"]
        if flag == "bankruptcy":
            if value is not True and value is not False:
                return False
            if not isinstance(prov["screen_status"], str):
                return False
        elif not _bool_or_none(value):
            return False
        if flag == "delisted":
            if (value, coverage) not in _VALID_DELISTED or not _bool_or_none(prov["reference_active_value"]):
                return False
        elif flag == "otc":
            if (value, coverage) not in _VALID_OTC or not _nonempty_str_or_none(prov["primary_exchange_value"]):
                return False
        elif flag == "halted":
            hfo = prov["halt_feed_observed"]
            if (value, coverage) not in _VALID_HALTED or (hfo is not True and hfo is not False):
                return False
            if hfo != (coverage in {"observed", "stale"}):
                return False
        else:  # bankruptcy
            if (value, coverage, prov["screen_status"]) not in _VALID_BANKRUPTCY:
                return False
            lookback = prov["lookback_window"]
            if coverage in {"observed", "not_in_screen_set", "stale", "stale_positive"}:
                if not (isinstance(lookback, str) and lookback.strip()):
                    return False
            elif lookback is not None and not isinstance(lookback, str):
                return False
            acc, found = prov["filing_accession_if_found"], (prov["screen_status"] == "bankrupt_8k_found")
            if found and not (isinstance(acc, str) and acc):   # found ⟹ traceable accession
                return False
            if not found and acc is not None:                  # only a found 8-K carries an accession
                return False
    return flags["delisted"]["observed_at"] == flags["otc"]["observed_at"]


def validate_access_packet_errors(packet):
    """THE access-packet validation path: JSON-Schema (shape + const-pins) PLUS a SEMANTIC `generated_at` check.

    For this FIXED dated packet `generated_at` is const-pinned in the schema to the exact reviewed instant, so a
    future / non-exact / calendar-impossible generation time is rejected by the const itself
    (R-USSHORT-BATCH5-STATUS-SOURCE-CLOCK-AND-ACCESS-PACKET-PIN-GAP residual A3). The semantic
    `_valid_observed_at(generated_at)` check is kept as a defence-in-depth gate bound to the validation boundary
    (residual 2: not an adjacent unit test a caller can bypass) and as the generic guard if this helper ever
    validates a non-const-pinned packet. Tests AND any future gated 1b preflight caller validate THROUGH this
    helper, so schema and semantic checks can never drift apart.

    The CANONICAL repo schema (`ACCESS_PACKET_SCHEMA_PATH`) is ALWAYS used — there is NO caller-supplied schema
    parameter. A validation boundary must own its rules: a caller passing `{}` or a permissive schema could
    otherwise validate an authorization mutant against const-pins that were never applied
    (R-USSHORT-BATCH5-STATUS-SOURCE-CLOCK-AND-ACCESS-PACKET-PIN-GAP residual B).

    Returns a list of human-readable error strings (empty == valid). Fail-closed: if jsonschema is unavailable
    the packet cannot be validated, so we RAISE (a non-validatable authorization packet must never be treated as
    valid). No network / provider / live call — pure offline validation of an injected packet dict.
    """
    try:
        import jsonschema
    except ImportError as exc:   # cannot validate -> fail closed (never pass an unvalidatable packet)
        raise RuntimeError("jsonschema 未安装；无法校验 access packet，拒绝降级（fail-closed）") from exc
    schema = json.loads(ACCESS_PACKET_SCHEMA_PATH.read_text(encoding="utf-8"))   # canonical only (residual B)
    errors = [str(e.message) for e in jsonschema.Draft7Validator(schema).iter_errors(packet)]
    gen = packet.get("generated_at") if isinstance(packet, dict) else None
    if not _valid_observed_at(gen):   # semantic RFC3339 (single source); regex-passing impossible dates rejected here
        errors.append(f"generated_at 非语义有效 RFC3339 时间戳（过 regex 但日历不可能/无时区）: {gen!r}")
    return errors
