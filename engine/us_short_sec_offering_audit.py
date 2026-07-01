# -*- coding: utf-8 -*-
"""US-short SEC OFFERING-AUDIT source — batch5 Cut 5, slice 5-a (offline half).

Design authority: docs/us_short_system_design.md §5.1a (SEC 增发/转售 hard veto = 近期+已激活+重大; 挂着的
shelf/陈旧/小额不当硬否决) / §3.1 (每个 runtime 字段记 provider/endpoint-or-filing/as_of/observed_at/
coverage/parser/lineage provenance) / §3.3 (关键 unknown 不当 clean) / §3.5 (event/observed 与 as_of 是不同
PIT 事实; 不用 look-ahead 证据) / §18.2 (跨模块契约先 schema-first 冻结再消费). Frozen contract:
docs/us_short_cut5_sec_offering_audit_binding_20260701.json (+ its schema; module consts below are triangulated
== that binding by a conformance test, so this consumer copy cannot silently drift).

WHAT THIS IS — the OFFLINE half of the (SR-PROVIDER-001-gated) SEC offering-audit data layer. Reachability of the
SEC submissions form-type + filing-date channel was PROVEN 2026-07-01
(docs/us_short_cut5_pass2_feasibility_probe_summary_20260701.json). This layer takes INJECTED per-ticker SEC
submissions-derived offering filings (the gated live half later fetches them), applies the repo's SINGLE US-ticker
identity policy (`canonical_us_ticker`), validates each ticker's machine provenance + PIT chronology +
coverage/parser fitness against the frozen binding, and derives the §5.1a `active_offering` signal
(recency / status / materiality) that `engine/us_short_hard_veto.py::classify_hard_veto` consumes. A scored offering
veto can no longer ride a caller-authored label, a future/look-ahead filing, a missing/failed coverage, or a
free-form "trust-me" lineage.

The offline submissions channel gives form-type + filing dates, so it can determine RECENCY (dates) and a STATUS
proxy (a recent 424B* prospectus supplement = the shelf is being USED = active; a bare recent registration
(domestic S-1/S-11/S-3/S-3ASR or foreign-issuer F-1/F-3/F-3ASR) with no recent takedown = registered_shelf,
挂着的 shelf ≠ 马上增发). It CANNOT determine MATERIALITY (offering SIZE) — that
needs 424B document-text parsing (gated, later) — so materiality is emitted null, and hard_veto maps a recent +
active offering with null materiality to strong_downgrade (没数据≠安全), short of a hard veto.

WHAT THIS IS NOT — no fetch (no network/provider; SR-PROVIDER-001 gates the live half + the runner wiring), does NOT
re-implement `classify_hard_veto`'s SCORING (single-source that in hard_veto — the emitted active_offering object is
what it consumes), does NOT re-source `delisted`/`bankruptcy`/`8-K catalyst` (owned by us_short_status_source /
us_short_catalyst_source), and does NOT cross A-share. S-8 (routine employee shares) and 25-NSE (delisting; status
source's domain) are deliberately NOT offering vetoes. Only the offline contract SHAPE is frozen here.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.us_short_eligibility_gate import canonical_us_ticker  # the repo's single US ticker identity policy

BINDING_PATH = (Path(__file__).resolve().parents[1]
                / "docs" / "us_short_cut5_sec_offering_audit_binding_20260701.json")

PROVIDER_ID = "sec_edgar"
ENDPOINT = "submissions"
# offering form families == binding offering_form_families (a conformance test triangulates module const == binding
# JSON). (family -> (matcher, [form exacts/prefixes], dilution_role)). Covers DOMESTIC registrations (S-1 / S-11
# REIT / S-3 / S-3ASR) AND FOREIGN-issuer analogs (F-1 / F-3 / F-3ASR) — NYSE/NASDAQ-listed ADRs file the F-*
# series for offerings with identical dilution mechanics, so a domestic-only family set would miss a real ADR
# dilution. 424B prospectus supplements (takedowns) are domicile-agnostic. S-8 / 25-NSE are NOT here (module doc).
_OFFERING_FAMILIES = {
    "primary_registration": ("exact_or_amend", ("S-1", "S-11", "F-1"), "registration"),
    "shelf_registration": ("exact_or_amend", ("S-3", "S-3ASR", "F-3", "F-3ASR"), "registration"),
    "prospectus_supplement": ("prefix", ("424B",), "takedown"),
}
_TAKEDOWN_FAMILY = "prospectus_supplement"           # a recent one -> status active
_RECENCY_WINDOW_DAYS = 90                             # §5.1a recency prior (reviewed calibration, not alpha)
_PROVENANCE_FIELDS = frozenset({"provider_id", "endpoint_or_filing_type", "source_as_of",
                                "observed_at", "coverage_status", "parser_status", "lineage_ref"})
_COVERAGE_ALLOWED = frozenset({"full", "partial", "missing"})
_PARSER_ALLOWED = frozenset({"ok", "degraded", "failed"})
_COVERAGE_EMIT = "full"                               # emission fitness: only full+ok is score-ready
_PARSER_EMIT = "ok"
# Each offering filing carries its EVENT instant `acceptance_datetime` (when EDGAR made it public — the probe
# proved SEC submissions supply acceptanceDateTime per filing), so a same-day filing accepted AFTER the 09:30
# decision open is distinguishable from valid premarket evidence (Codex Cut5 finding A: filing_date day-only was
# indistinguishable). filing_date stays for the recency window; acceptance_datetime is the PIT instant.
_FILING_KEYS = frozenset({"form", "filing_date", "acceptance_datetime", "accession"})
_RECORD_KEYS = frozenset({"filings", "provenance"})
_DECISION_TZ_NAME = "America/New_York"
_DECISION_CUTOFF_HHMM = (9, 30)                       # decision-session open (§2.1); observed_at must be strictly before
# Machine-readable PIT / identity / checked-empty / authorization POLICY consts — triangulated == the binding's
# frozen fields (a conformance test asserts equality), so the offline shared contract §18.2 requires cannot drift
# between schema, binding, and engine behavior (Codex Cut5 finding D: the binding must freeze the POLICIES, not just
# the vocabularies). Any drift fails the conformance test.
_CUTOFF_OPERATOR = "strictly_before"                  # observed_at < decision_open (half-open, matches resolve_canonical_asof)
_CUTOFF_REFERENCE = "decision_session_open"           # the 09:30 ET open on as_of
_CHRONOLOGY_ORDER = ("acceptance_datetime", "observed_at", "source_as_of", "as_of")   # each <= the next (non-decreasing)
_LINEAGE_REF_FORMAT = "provider_id:endpoint_or_filing_type:source_as_of#record_id"
_DUPLICATE_IDENTITY = "accession"                     # per-filing source-row identity (SEC accession is globally unique)
_DUPLICATE_POLICY = "reject"                          # an exact/repeated accession fails closed (never silently deduped/double-counted)
_CHECKED_EMPTY_DISPOSITION = "audited_no_active_offering"   # full/ok + zero offering filings -> retained coverage proof, NOT silent drop
# The offline slice performs NO live fetch / network / raw capture / runner wiring / DataHub / production / ship-gate;
# a machine boundary object (all-false) freezes that so a same-shaped binding cannot quietly claim authorization.
_AUTHORIZATION_BOUNDARY = {
    "live_fetch": False, "network": False, "raw_capture": False, "runner_wired": False,
    "datahub": False, "production": False, "ship_gate": False,
}


class OfferingAuditError(ValueError):
    """An injected SEC offering payload is malformed / mis-provenanced / PIT-inconsistent, or a source's ticker
    keys alias to the same canonical US ticker (fail-closed; never fabricates or misattributes an offering veto)."""


def _valid_ymd(s: Any) -> bool:
    """Strict 10-char ASCII real-calendar YYYY-MM-DD (SEC-native). ASCII-guarded so `strptime` cannot accept
    Unicode decimal digits as a date (mirrors us_short_market_calendar / status_source single convention)."""
    if not (type(s) is str and len(s) == 10 and s.isascii()):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _valid_observed_at(s: Any) -> bool:
    """Strict RFC3339-like tz-AWARE date-time ('T' separator + offset/Z). Rejects date-only, space-separated,
    and naive (no-offset) strings (mirrors us_short_status_source._valid_observed_at, single convention)."""
    if not (type(s) is str and "T" in s):
        return False
    try:
        dt = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _et_tz():
    """The canonical decision timezone (America/New_York, DST-aware), or fail-closed (raise) if no tz database — a
    clock that cannot be normalized must never silently pass."""
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError as exc:
        raise OfferingAuditError("无 zoneinfo，无法归一化决策时区，拒绝降级") from exc
    try:
        return ZoneInfo(_DECISION_TZ_NAME)
    except ZoneInfoNotFoundError as exc:
        raise OfferingAuditError(f"无 {_DECISION_TZ_NAME} 时区库(tzdata)，无法归一化决策时区，拒绝降级") from exc


def _observed_at_et(observed_at: str) -> datetime:
    """The instant as an ET-normalized aware datetime (DST-aware), so a caller's arbitrary offset cannot shift the
    PIT instant/date. Fail-closed (raise) on an out-of-range boundary-year timestamp whose tz conversion would leak
    a raw OverflowError. Assumes `observed_at` already passed `_valid_observed_at` (so it is an exact str)."""
    tz = _et_tz()
    inst = datetime.fromisoformat(observed_at[:-1] + "+00:00" if observed_at.endswith("Z") else observed_at)
    try:
        return inst.astimezone(tz)
    except (OverflowError, OSError) as exc:
        raise OfferingAuditError(f"时间戳超出可归一化时区范围（非真实 provider 时钟）: {observed_at!r}") from exc


def _decision_cutoff(as_of: str) -> datetime:
    """The canonical decision cutoff = the decision-session 09:30 ET open on `as_of` (§2.1). `observed_at` must be
    STRICTLY before this instant (half-open window; 09:30 itself is out-of-window, matching resolve_canonical_asof,
    the authority for the half-open boundary). Assumes `as_of` already passed `_valid_ymd` (YYYY-MM-DD)."""
    return datetime(int(as_of[:4]), int(as_of[5:7]), int(as_of[8:10]),
                    _DECISION_CUTOFF_HHMM[0], _DECISION_CUTOFF_HHMM[1], tzinfo=_et_tz())


def _valid_lineage_ref(ref: Any, *, source_as_of: str) -> bool:
    """A STRUCTURED, source-bound, machine-verifiable lineage reference
    `sec_edgar:submissions:<source_as_of>#<record_id>`; record_id a nonempty ASCII token (no ':' '#' whitespace).
    A free-form 'trust-me' string is rejected (§3.1 lineage must be verifiable, mirrors catalyst_source)."""
    if not (type(ref) is str and ref.isascii()):
        return False
    prefix, sep, rid = ref.rpartition("#")
    if sep != "#" or not rid or any(c.isspace() for c in rid) or ":" in rid or "#" in rid:
        return False
    return prefix == f"{PROVIDER_ID}:{ENDPOINT}:{source_as_of}"


def _validate_provenance(prov: Any, *, ticker: str, as_of: str) -> datetime:
    """Fail-closed §3.1/§3.5 provenance + PIT check for ONE ticker's offering pull, against the frozen binding.
    provider_id/endpoint pinned; source_as_of real YYYY-MM-DD; observed_at a tz-aware RFC3339 INSTANT; the observed
    instant STRICTLY before the decision-session 09:30 ET open on as_of (half-open, no at/post-open look-ahead) and
    the chronology `observed_at ET date <= source_as_of <= as_of` (a source snapshot cannot predate its own
    observation; nothing may postdate as_of); coverage/parser ∈ binding sets; lineage_ref structured. Returns the
    ET-normalized observation instant (so the per-filing event chronology can bind acceptance <= observed). Raises
    OfferingAuditError (BEFORE emit)."""
    # exact-str provenance keys BEFORE `set(prov)` — a str-subclass key with a hostile __eq__/__hash__ would
    # otherwise leak a raw exception through the set comparison (mirrors catalyst_source hostile-key hardening).
    if not (isinstance(prov, dict) and all(type(pk) is str for pk in prov) and set(prov) == _PROVENANCE_FIELDS):
        raise OfferingAuditError(
            f"[{ticker}].provenance 键须恰为精确 str 的 {sorted(_PROVENANCE_FIELDS)}（§3.1，fail-closed）")
    if (type(prov["provider_id"]) is not str or type(prov["endpoint_or_filing_type"]) is not str
            or prov["provider_id"] != PROVIDER_ID or prov["endpoint_or_filing_type"] != ENDPOINT):
        raise OfferingAuditError(
            f"[{ticker}].provenance provider/endpoint 与冻结 binding 不符（须 {PROVIDER_ID}/{ENDPOINT}）")
    src_as_of = prov["source_as_of"]
    if not _valid_ymd(src_as_of):
        raise OfferingAuditError(f"[{ticker}].provenance source_as_of 须为真实 YYYY-MM-DD")
    if not _valid_observed_at(prov["observed_at"]):
        raise OfferingAuditError(f"[{ticker}].provenance observed_at 须为 tz-aware RFC3339 时间戳（§3.5 决策截止需瞬时精度，非日期）")
    # A-clock (HALF-OPEN window [prior_close, decision_open), §2.1/§3.5): the observation INSTANT must be STRICTLY
    # before the 09:30 ET decision open on as_of — exactly 09:30 is OUT-OF-WINDOW (matching resolve_canonical_asof),
    # so an at/post-open same-date observation is look-ahead, distinguishable from a valid premarket one.
    obs_dt = _observed_at_et(prov["observed_at"])
    if obs_dt >= _decision_cutoff(as_of):
        raise OfferingAuditError(
            f"[{ticker}].provenance observed_at 不早于决策开盘（{as_of} 09:30 ET 半开边界；09:30 及之后 out-of-window/look-ahead，§2.1/§3.5）")
    obs_date = obs_dt.strftime("%Y-%m-%d")
    if not (obs_date <= src_as_of):
        raise OfferingAuditError(f"[{ticker}].provenance source_as_of 早于观测日期（源快照不能早于它含的证据；§3.5）")
    if not (src_as_of <= as_of):
        raise OfferingAuditError(f"[{ticker}].provenance source_as_of 晚于决策 as_of={as_of}（look-ahead；§3.5）")
    if type(prov["coverage_status"]) is not str or prov["coverage_status"] not in _COVERAGE_ALLOWED:
        raise OfferingAuditError(f"[{ticker}].provenance coverage_status 非法（须 ∈ {sorted(_COVERAGE_ALLOWED)}）")
    if type(prov["parser_status"]) is not str or prov["parser_status"] not in _PARSER_ALLOWED:
        raise OfferingAuditError(f"[{ticker}].provenance parser_status 非法（须 ∈ {sorted(_PARSER_ALLOWED)}）")
    if not _valid_lineage_ref(prov["lineage_ref"], source_as_of=src_as_of):
        raise OfferingAuditError(
            f"[{ticker}].provenance lineage_ref 须为结构化 source-bound 引用 "
            f"'{PROVIDER_ID}:{ENDPOINT}:{src_as_of}#<record_id>'（非自由文本）")
    return obs_dt


def _form_matches(form: Any, matcher: str, patterns: tuple) -> bool:
    if type(form) is not str:               # EXACT str before .startswith/== (a hostile str-subclass form must not leak a raw exception)
        return False
    for pattern in patterns:
        if matcher == "prefix":
            if form.startswith(pattern):
                return True
        else:  # exact_or_amend
            if form == pattern or form.startswith(pattern + "/"):
                return True
    return False


def _family_of(form: Any) -> str | None:
    for family, (matcher, patterns, _role) in _OFFERING_FAMILIES.items():
        if _form_matches(form, matcher, patterns):
            return family
    return None


def _canonical_keyed(filings_by_ticker: Any) -> dict:
    """Re-key the injected {ticker: {filings, provenance}} by canonical US ticker. None -> {}. Invalid /
    non-string / cross-market (A-share) / non-ASCII ticker keys are EXCLUDED (dropped, fail-closed). Two keys
    aliasing to the same canonical US ticker RAISE. Each record must be a dict whose keys are EXACT `str`
    (`type(k) is str` — a str SUBCLASS with a hostile __eq__/__hash__/__repr__ is rejected BEFORE any set/format)
    and are EXACTLY {filings, provenance}; the diagnostic echoes only the safe const set, never the caller's keys
    (mirrors catalyst_source)."""
    if filings_by_ticker is None:
        return {}
    if not isinstance(filings_by_ticker, dict):
        raise OfferingAuditError(f"filings_by_ticker 须为 dict 或 None: {type(filings_by_ticker).__name__}")
    out: dict[str, dict] = {}
    for k, v in filings_by_ticker.items():
        if type(k) is not str:                       # exact-str ticker key only (hostile str-subclass excluded)
            continue
        ck = canonical_us_ticker(k)
        if ck is None:
            continue                                 # invalid / A-share / non-ASCII -> excluded (dropped)
        if not isinstance(v, dict):
            raise OfferingAuditError(f"[{ck}] 记录须为 dict: {type(v).__name__}")
        if not all(type(rk) is str for rk in v):     # exact-str record keys BEFORE any set op (hostile-key class)
            raise OfferingAuditError(f"[{ck}] 记录键须为精确 str（拒 str 子类/非串，fail-closed，不回显敌意键）")
        if set(v) != _RECORD_KEYS:
            raise OfferingAuditError(f"[{ck}] 记录键须恰为 {sorted(_RECORD_KEYS)}（fail-closed，不回显实际键）")
        if ck in out:
            raise OfferingAuditError(f"规范化后重复 ticker {ck!r}（别名歧义，fail-closed；不静默去重）")
        out[ck] = v
    return out


def _parse_offering_filings(filings: Any, *, ticker: str, as_of: str, observed_at_et: datetime) -> list[dict]:
    """Return the PIT-cut offering filings (offering-family form) whose EVENT instant `acceptance_datetime` is at or
    before the observation instant (a filing that only became public AFTER we observed the ticker, or after the
    decision open, is look-ahead and EXCLUDED — §3.5), each a validated {form, filing_date, acceptance_datetime,
    accession, family}. A non-offering form is ignored. A duplicate/blank/non-ASCII accession fails closed (a SEC
    accession is a globally-unique source-row identity, so a repeated one is a fabricated/duplicated row, never
    silently double-counted). Malformed filing shape fails closed (raise)."""
    if not isinstance(filings, list):
        raise OfferingAuditError(f"[{ticker}].filings 须为 list: {type(filings).__name__}")
    obs_date = observed_at_et.strftime("%Y-%m-%d")
    out: list[dict] = []
    seen_accessions: set[str] = set()
    for f in filings:
        if not (isinstance(f, dict) and all(type(k) is str for k in f) and set(f) == _FILING_KEYS):
            raise OfferingAuditError(f"[{ticker}] filing 键须恰为 {sorted(_FILING_KEYS)}（fail-closed）")
        family = _family_of(f["form"])
        if family is None:
            continue                                 # not an offering form (S-8/8-K/10-K/25-NSE/...) -> ignored
        fdate = f["filing_date"]
        if not _valid_ymd(fdate):
            raise OfferingAuditError(f"[{ticker}] offering filing filing_date 须为真实 YYYY-MM-DD（仅类型 {type(fdate).__name__}）")
        acceptance = f["acceptance_datetime"]
        if not _valid_observed_at(acceptance):
            raise OfferingAuditError(f"[{ticker}] offering filing acceptance_datetime 须为 tz-aware RFC3339 时间戳（EDGAR 公开事件瞬时）")
        # PIT cut (event <= observed): a filing whose public instant is after the observation (observed is already
        # STRICTLY before the 09:30 decision open) was not premarket-known evidence -> excluded, not emitted.
        if _observed_at_et(acceptance) > observed_at_et:
            continue
        if fdate > obs_date:                         # coarse consistency: filing day-label cannot postdate observation
            continue
        accession = f["accession"]                   # exact-str BEFORE `in seen_accessions` (hostile-subclass hash/eq guard)
        if not (type(accession) is str and accession and accession.isascii() and not any(c.isspace() for c in accession)):
            raise OfferingAuditError(f"[{ticker}] offering filing accession 须为非空、无空白、ASCII 串（可追溯 source-row 身份）")
        if accession in seen_accessions:
            raise OfferingAuditError(f"[{ticker}] offering filing accession 重复（source-row 身份不唯一，fail-closed；不静默去重/双计）")
        seen_accessions.add(accession)
        out.append({"form": f["form"], "filing_date": fdate, "acceptance_datetime": acceptance,
                    "accession": accession, "family": family})
    return out


def _days_between(later_ymd: str, earlier_ymd: str) -> int:
    return (datetime.strptime(later_ymd, "%Y-%m-%d").date()
            - datetime.strptime(earlier_ymd, "%Y-%m-%d").date()).days


def _derive_active_offering(offering_filings: list[dict], *, as_of: str) -> dict:
    """Derive the §5.1a active_offering signal from the PIT-cut offering filings.
    recency: 'recent' iff the most-recent offering filing is within _RECENCY_WINDOW_DAYS of as_of, else 'stale'.
    status:  'active' iff a RECENT takedown (424B*) filing exists (shelf being used); else 'registered_shelf'.
    materiality: always None (offering SIZE unavailable from submissions — needs 424B doc parse, gated)."""
    most_recent = max(f["filing_date"] for f in offering_filings)
    recency = "recent" if _days_between(as_of, most_recent) <= _RECENCY_WINDOW_DAYS else "stale"
    recent_takedown = any(
        f["family"] == _TAKEDOWN_FAMILY and _days_between(as_of, f["filing_date"]) <= _RECENCY_WINDOW_DAYS
        for f in offering_filings
    )
    status = "active" if recent_takedown else "registered_shelf"
    return {"recency": recency, "status": status, "materiality": None}


def resolve_offering_audit(*, as_of: str, filings_by_ticker: Any) -> dict[str, Any]:
    """Resolve injected SEC submissions offering filings -> the per-ticker §5.1a `active_offering` signal that
    `classify_hard_veto` consumes, keyed by canonical US ticker, with validated §3.1/§3.5 provenance + PIT +
    coverage/parser fitness.

    `as_of` = the reviewed decision clock (real YYYY-MM-DD). Each ticker record = {"filings": [ {form,
    filing_date: 'YYYY-MM-DD', acceptance_datetime: tz-aware RFC3339, accession} ... ], "provenance": {...7 §3.1
    fields...}}. Provenance is validated BEFORE emit (provider/endpoint pinned, real clocks, the observed instant
    STRICTLY before the 09:30 ET decision open, chronology observed<=source<=as_of, coverage/parser enums,
    structured lineage). A ticker's signal is EMITTED only when coverage=='full' AND parser=='ok'; otherwise it is
    EXCLUDED (conservative — the offline slice cannot assert offering status on incomplete data). A full/ok ticker
    with NO in-window offering filing emits an explicit CHECKED coverage record (disposition
    `audited_no_active_offering`) — a safety-audit "we looked and found no active offering", DISTINCT from a ticker
    that was never queried (§3.3: an audited clean must not collapse to unknown). One WITH offering filings emits
    {active_offering: {recency, status, materiality: None}}.

    Returns {signals: {ticker: {active_offering: {...}}}, provenance: {ticker: {active_offering: {...prov,
    contributing_filings: [{form, filing_date, acceptance_datetime, accession}]}}}, excluded: {ticker:
    {active_offering: reason}}, checked: {ticker: {active_offering: {disposition, coverage_status, parser_status}}}}.
    Raises OfferingAuditError on any malformed / PIT-inconsistent input.
    """
    if not _valid_ymd(as_of):
        raise OfferingAuditError(f"as_of 须为真实 YYYY-MM-DD 决策时钟（不回显敌意值，仅类型 {type(as_of).__name__}）")
    canon = _canonical_keyed(filings_by_ticker)
    signals: dict[str, dict] = {}
    provenance: dict[str, dict] = {}
    excluded: dict[str, dict] = {}
    checked: dict[str, dict] = {}
    for ct, rec in canon.items():
        prov = rec["provenance"]
        obs_dt = _validate_provenance(prov, ticker=ct, as_of=as_of)       # fail-closed before any emit; returns ET instant
        if prov["coverage_status"] != _COVERAGE_EMIT or prov["parser_status"] != _PARSER_EMIT:
            excluded[ct] = {"active_offering": f"coverage={prov['coverage_status']}/parser={prov['parser_status']}"}
            continue
        offering_filings = _parse_offering_filings(rec["filings"], ticker=ct, as_of=as_of, observed_at_et=obs_dt)
        base_prov = {k: prov[k] for k in _PROVENANCE_FIELDS}
        if not offering_filings:
            # full/ok + no in-window offering filing: emit a CHECKED coverage proof (audited clean), retaining the
            # provenance so a consumer can tell "audited: no active offering" from "never queried" (§3.3, finding C).
            checked[ct] = {"active_offering": {
                "disposition": _CHECKED_EMPTY_DISPOSITION,
                "coverage_status": prov["coverage_status"], "parser_status": prov["parser_status"],
            }}
            provenance[ct] = {"active_offering": {**base_prov, "contributing_filings": []}}
            continue
        signals[ct] = {"active_offering": _derive_active_offering(offering_filings, as_of=as_of)}
        provenance[ct] = {"active_offering": {
            **base_prov,
            "contributing_filings": [
                {"form": f["form"], "filing_date": f["filing_date"],
                 "acceptance_datetime": f["acceptance_datetime"], "accession": f["accession"]}
                for f in sorted(offering_filings, key=lambda x: (x["filing_date"], x["accession"]))
            ],
        }}
    return {"signals": signals, "provenance": provenance, "excluded": excluded, "checked": checked}


def load_binding() -> dict:
    """Load the frozen binding JSON (for the conformance test that triangulates module consts == binding)."""
    return json.loads(BINDING_PATH.read_text(encoding="utf-8"))
