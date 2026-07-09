# -*- coding: utf-8 -*-
"""US-short MASSIVE actual-financials source — batch5 Cut 5, slice 5-b (offline half).

Design authority: docs/us_short_system_design.md §4.2 (财报实际/基础财务) / §3.1 (每个 runtime 字段记
provider/endpoint/as_of/observed_at/coverage/parser/lineage provenance) / §3.5 (公开日 filing_date 与 as_of
是 PIT 事实; 不用 look-ahead 证据) / §18.2 (跨模块契约先 schema-first 冻结再消费). Frozen contract:
docs/us_short_cut5_massive_actual_financials_binding_20260701.json (+ its schema; module consts below are
triangulated == that binding by a conformance test).

WHAT THIS IS — the OFFLINE half of the (SR-PROVIDER-001-gated) Massive actual-financials data layer. Reachability
+ real shape were PROVEN 2026-07-01 (docs/us_short_cut5_pass2_feasibility_probe_summary_20260701.json + captured
gitignored raw): Massive/Polygon `/vX/reference/financials?timeframe=quarterly|annual` returns a REAL filing_date +
acceptance_datetime (the 10-Q/10-K public dates) plus income/balance/cash-flow concepts, each {value, unit, label,
order}. This layer takes INJECTED per-ticker Massive periodic financials (the gated live half fetches them), applies
the repo's SINGLE US-ticker identity policy (`canonical_us_ticker`), validates the pull's §3.1 provenance +
coverage/parser fitness, PIT-anchors each period to its real `filing_date` (<= as_of), and flattens the bound
line-item concepts into a clean per-period 财报实际 record. A scored fundamental can no longer ride a future/
look-ahead period, a null-filing-date (unknowable-PIT) period, a ttm rollup with no single filing, a fabricated
line item, or a free-form "trust-me" lineage.

PIT is load-bearing: `filing_date` (the SEC 10-Q/10-K public date) — NOT `period_end` (the fiscal period end,
which precedes the public date by weeks) — is the knowable-date anchor. The probe found the ttm DEFAULT returns a
NULL filing_date, so `timeframe` is bound to {quarterly, annual} and a period with a null / missing / future
filing_date is EXCLUDED (§3.5).

WHAT THIS IS NOT — no fetch (no network/provider; SR-PROVIDER-001 gates the live half + the runner wiring), does NOT
SCORE (this is the fact layer; the earnings-growth / 财报实际vs预期 surprise wiring — the estimate half stays
un-hooked per the 2026-07-01 user decision, future-paid-gated — is a later seam), and does NOT cross A-share. Only
the offline contract SHAPE is frozen here.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.us_short_eligibility_gate import canonical_us_ticker  # the repo's single US ticker identity policy

BINDING_PATH = (Path(__file__).resolve().parents[1]
                / "docs" / "us_short_cut5_massive_actual_financials_binding_20260701.json")

PROVIDER_ID = "massive"
ENDPOINT = "reference_financials"
_DECISION_TZ_NAME = "America/New_York"
_ALLOWED_TIMEFRAMES = ("quarterly", "annual")           # ttm EXCLUDED (null filing_date, no single 10-Q/10-K PIT)
# bound line-item concepts per statement == binding bound_line_items (a conformance test triangulates). Real
# Massive/Polygon concept keys (confirmed from the 2026-07-01 captured raw).
_BOUND_LINE_ITEMS = {
    "income_statement": ("revenues", "gross_profit", "operating_income_loss", "net_income_loss",
                         "diluted_earnings_per_share", "basic_earnings_per_share"),
    "balance_sheet": ("assets", "liabilities", "equity", "current_assets", "current_liabilities", "long_term_debt"),
    "cash_flow_statement": ("net_cash_flow_from_operating_activities",),
}
_PROVENANCE_FIELDS = frozenset({"provider_id", "endpoint_or_filing_type", "source_as_of",
                                "observed_at", "coverage_status", "parser_status", "lineage_ref"})
_COVERAGE_ALLOWED = frozenset({"full", "partial", "missing"})
_PARSER_ALLOWED = frozenset({"ok", "degraded", "failed"})
_COVERAGE_EMIT = "full"
_PARSER_EMIT = "ok"
_RECORD_KEYS = frozenset({"periods", "provenance"})
# fields this layer reads from an injected Massive period; extra Massive keys (cik/company_name/sic/tickers) are
# tolerated + ignored (the period is an EXTERNAL provider shape, not an internal exact-key contract).
_PERIOD_REQUIRED = ("timeframe", "fiscal_period", "fiscal_year", "start_date", "end_date",
                    "filing_date", "acceptance_datetime", "financials")
_DECISION_CUTOFF_HHMM = (9, 30)                          # decision-session open (§2.1); observed_at must be strictly before
# Machine-readable PIT / identity / checked-empty / authorization POLICY consts — triangulated == the binding's
# frozen fields (a conformance test asserts equality), so the offline shared contract §18.2 requires cannot drift
# between schema, binding, and engine behavior (Codex Cut5 finding D: freeze the POLICIES, not just the vocabularies).
_CUTOFF_OPERATOR = "strictly_before"                     # observed_at < decision_open (half-open, matches resolve_canonical_asof)
_CUTOFF_REFERENCE = "decision_session_open"              # the 09:30 ET open on as_of
_CHRONOLOGY_ORDER = ("acceptance_datetime", "observed_at", "source_as_of", "as_of")   # each <= the next (non-decreasing)
_LINEAGE_REF_FORMAT = "provider_id:endpoint_or_filing_type:source_as_of#record_id"
_DUPLICATE_IDENTITY = ("timeframe", "fiscal_year", "fiscal_period")   # per-period source-row identity (one report per fiscal period)
_DUPLICATE_POLICY = "reject"                             # a repeated (timeframe,fiscal_year,fiscal_period) fails closed (never double-counted)
_CHECKED_EMPTY_DISPOSITION = "checked_no_pit_fit_period"   # full/ok + zero PIT-fit period -> retained coverage proof, NOT silent drop
_AUTHORIZATION_BOUNDARY = {
    "live_fetch": False, "network": False, "raw_capture": False, "runner_wired": False,
    "datahub": False, "production": False, "ship_gate": False,
}


class MassiveFinancialsError(ValueError):
    """An injected Massive financials payload is malformed / mis-provenanced / PIT-inconsistent, or a source's
    ticker keys alias to the same canonical US ticker (fail-closed; never fabricates a fundamental)."""


def _is_finite_number(x: Any) -> bool:
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        return False
    try:
        return math.isfinite(x)   # an over-large raw line-item int → non-finite, not a bare OverflowError
    except OverflowError:
        return False


def _valid_ymd(s: Any) -> bool:
    """Strict 10-char ASCII real-calendar YYYY-MM-DD. ASCII-guarded (mirrors the repo-wide single convention)."""
    if not (type(s) is str and len(s) == 10 and s.isascii()):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _valid_observed_at(s: Any) -> bool:
    """Strict RFC3339-like tz-AWARE date-time ('T' + offset/Z). Rejects date-only / space-sep / naive (mirrors
    us_short_status_source._valid_observed_at). Reused for acceptance_datetime (same RFC3339 contract)."""
    if not (type(s) is str and "T" in s):
        return False
    try:
        dt = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _et_tz():
    """The canonical decision timezone (America/New_York, DST-aware), or fail-closed (raise) if no tz database."""
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError as exc:
        raise MassiveFinancialsError("无 zoneinfo，无法归一化决策时区，拒绝降级") from exc
    try:
        return ZoneInfo(_DECISION_TZ_NAME)
    except ZoneInfoNotFoundError as exc:
        raise MassiveFinancialsError(f"无 {_DECISION_TZ_NAME} 时区库(tzdata)，无法归一化决策时区，拒绝降级") from exc


def _observed_at_et(observed_at: str) -> datetime:
    """The instant as an ET-normalized aware datetime (DST-aware), so a caller's arbitrary offset cannot shift the
    PIT instant/date. Fail-closed (raise) on an out-of-range boundary-year timestamp whose tz conversion would leak
    a raw OverflowError. Assumes `observed_at` already passed `_valid_observed_at` (exact str). Reused for the
    per-period acceptance instant (same RFC3339 contract)."""
    tz = _et_tz()
    inst = datetime.fromisoformat(observed_at[:-1] + "+00:00" if observed_at.endswith("Z") else observed_at)
    try:
        return inst.astimezone(tz)
    except (OverflowError, OSError) as exc:
        raise MassiveFinancialsError(f"时间戳超出可归一化时区范围（非真实 provider 时钟）: {observed_at!r}") from exc


def _decision_cutoff(as_of: str) -> datetime:
    """The canonical decision cutoff = the decision-session 09:30 ET open on `as_of` (§2.1). `observed_at` must be
    STRICTLY before this instant (half-open window; 09:30 itself is out-of-window, matching resolve_canonical_asof).
    Assumes `as_of` already passed `_valid_ymd` (YYYY-MM-DD)."""
    return datetime(int(as_of[:4]), int(as_of[5:7]), int(as_of[8:10]),
                    _DECISION_CUTOFF_HHMM[0], _DECISION_CUTOFF_HHMM[1], tzinfo=_et_tz())


def _valid_lineage_ref(ref: Any, *, source_as_of: str) -> bool:
    """Structured source-bound `massive:reference_financials:<source_as_of>#<record_id>` (record_id a nonempty
    ASCII token, no ':' '#' whitespace). Free-form 'trust-me' rejected (§3.1, mirrors catalyst_source)."""
    if not (type(ref) is str and ref.isascii()):
        return False
    prefix, sep, rid = ref.rpartition("#")
    if sep != "#" or not rid or any(c.isspace() for c in rid) or ":" in rid or "#" in rid:
        return False
    return prefix == f"{PROVIDER_ID}:{ENDPOINT}:{source_as_of}"


def _validate_provenance(prov: Any, *, ticker: str, as_of: str) -> datetime:
    """Fail-closed §3.1/§3.5 provenance check for ONE ticker's financials pull, against the frozen binding.
    provider/endpoint pinned; source_as_of real YYYY-MM-DD; observed_at a tz-aware RFC3339 INSTANT STRICTLY before
    the 09:30 ET decision open on as_of (half-open); chronology `observed_at ET date <= source_as_of <= as_of`;
    coverage/parser ∈ binding sets; lineage_ref structured. Returns the ET-normalized observation instant (so the
    per-period event chronology can bind acceptance <= observed). Raises MassiveFinancialsError (BEFORE emit)."""
    if not (isinstance(prov, dict) and all(type(pk) is str for pk in prov) and set(prov) == _PROVENANCE_FIELDS):
        raise MassiveFinancialsError(
            f"[{ticker}].provenance 键须恰为精确 str 的 {sorted(_PROVENANCE_FIELDS)}（§3.1，fail-closed）")
    if (type(prov["provider_id"]) is not str or type(prov["endpoint_or_filing_type"]) is not str
            or prov["provider_id"] != PROVIDER_ID or prov["endpoint_or_filing_type"] != ENDPOINT):
        raise MassiveFinancialsError(
            f"[{ticker}].provenance provider/endpoint 与冻结 binding 不符（须 {PROVIDER_ID}/{ENDPOINT}）")
    src_as_of = prov["source_as_of"]
    if not _valid_ymd(src_as_of):
        raise MassiveFinancialsError(f"[{ticker}].provenance source_as_of 须为真实 YYYY-MM-DD")
    if not _valid_observed_at(prov["observed_at"]):
        raise MassiveFinancialsError(f"[{ticker}].provenance observed_at 须为 tz-aware RFC3339 时间戳（§3.5 决策截止需瞬时精度，非日期）")
    # A-clock (HALF-OPEN [prior_close, decision_open), §2.1/§3.5): observation INSTANT STRICTLY before the 09:30 ET
    # decision open on as_of — exactly 09:30 is OUT-OF-WINDOW (matching resolve_canonical_asof).
    obs_dt = _observed_at_et(prov["observed_at"])
    if obs_dt >= _decision_cutoff(as_of):
        raise MassiveFinancialsError(
            f"[{ticker}].provenance observed_at 不早于决策开盘（{as_of} 09:30 ET 半开边界；09:30 及之后 out-of-window/look-ahead，§2.1/§3.5）")
    obs_date = obs_dt.strftime("%Y-%m-%d")
    if not (obs_date <= src_as_of):
        raise MassiveFinancialsError(f"[{ticker}].provenance source_as_of 早于观测日期（源快照不能早于它含的证据；§3.5）")
    if not (src_as_of <= as_of):
        raise MassiveFinancialsError(f"[{ticker}].provenance source_as_of 晚于决策 as_of={as_of}（look-ahead；§3.5）")
    if type(prov["coverage_status"]) is not str or prov["coverage_status"] not in _COVERAGE_ALLOWED:
        raise MassiveFinancialsError(f"[{ticker}].provenance coverage_status 非法（须 ∈ {sorted(_COVERAGE_ALLOWED)}）")
    if type(prov["parser_status"]) is not str or prov["parser_status"] not in _PARSER_ALLOWED:
        raise MassiveFinancialsError(f"[{ticker}].provenance parser_status 非法（须 ∈ {sorted(_PARSER_ALLOWED)}）")
    if not _valid_lineage_ref(prov["lineage_ref"], source_as_of=src_as_of):
        raise MassiveFinancialsError(
            f"[{ticker}].provenance lineage_ref 须为结构化 source-bound 引用 "
            f"'{PROVIDER_ID}:{ENDPOINT}:{src_as_of}#<record_id>'（非自由文本）")
    return obs_dt


def _canonical_keyed(financials_by_ticker: Any) -> dict:
    """Re-key the injected {ticker: {periods, provenance}} by canonical US ticker. None -> {}. Invalid /
    non-string / cross-market (A-share) / non-ASCII ticker keys are EXCLUDED (dropped). Two keys aliasing to the
    same canonical US ticker RAISE. Each record must be a dict whose keys are EXACT `str` (`type(k) is str`) and
    are EXACTLY {periods, provenance}; the diagnostic echoes only the safe const set (mirrors catalyst_source /
    offering_audit hostile-key hardening)."""
    if financials_by_ticker is None:
        return {}
    if not isinstance(financials_by_ticker, dict):
        raise MassiveFinancialsError(f"financials_by_ticker 须为 dict 或 None: {type(financials_by_ticker).__name__}")
    out: dict[str, dict] = {}
    for k, v in financials_by_ticker.items():
        if type(k) is not str:
            continue
        ck = canonical_us_ticker(k)
        if ck is None:
            continue
        if not isinstance(v, dict):
            raise MassiveFinancialsError(f"[{ck}] 记录须为 dict: {type(v).__name__}")
        if not all(type(rk) is str for rk in v):
            raise MassiveFinancialsError(f"[{ck}] 记录键须为精确 str（拒 str 子类/非串，fail-closed，不回显敌意键）")
        if set(v) != _RECORD_KEYS:
            raise MassiveFinancialsError(f"[{ck}] 记录键须恰为 {sorted(_RECORD_KEYS)}（fail-closed，不回显实际键）")
        if ck in out:
            raise MassiveFinancialsError(f"规范化后重复 ticker {ck!r}（别名歧义，fail-closed；不静默去重）")
        out[ck] = v
    return out


def _extract_line_items(financials: Any, *, ticker: str, period_label: str) -> tuple[dict, list]:
    """Flatten the bound Massive concepts -> ({concept: finite value}, [missing concept ...]). A bound statement
    that is entirely ABSENT (or a concept absent within it) is recorded MISSING (never fabricated / zero-filled).
    A PRESENT-but-malformed concept (statement non-dict, concept non-dict, non-finite value, or missing/empty
    unit) FAILS CLOSED (raise) — corrupt data must not be silently dropped. `financials` itself must be a dict."""
    if not isinstance(financials, dict):
        raise MassiveFinancialsError(f"[{ticker}] {period_label}.financials 须为 dict: {type(financials).__name__}")
    line_items: dict[str, float] = {}
    missing: list[str] = []
    for statement, concepts in _BOUND_LINE_ITEMS.items():
        stmt = financials.get(statement)
        if stmt is None:
            missing.extend(f"{statement}.{c}" for c in concepts)
            continue
        if not isinstance(stmt, dict):
            raise MassiveFinancialsError(f"[{ticker}] {period_label}.financials.{statement} 须为 dict 或缺失")
        for concept in concepts:
            cell = stmt.get(concept)
            if cell is None:
                missing.append(f"{statement}.{concept}")
                continue
            if not isinstance(cell, dict):
                raise MassiveFinancialsError(f"[{ticker}] {period_label} 概念 {statement}.{concept} 须为 {{value,unit,...}} dict")
            value, unit = cell.get("value"), cell.get("unit")
            if not _is_finite_number(value):
                raise MassiveFinancialsError(
                    f"[{ticker}] {period_label} 概念 {statement}.{concept} value 须为有限数（拒 NaN/Inf/bool/串；仅类型 {type(value).__name__}）")
            if not (isinstance(unit, str) and unit):
                raise MassiveFinancialsError(f"[{ticker}] {period_label} 概念 {statement}.{concept} unit 须为非空字符串")
            line_items[concept] = float(value)
    return line_items, missing


def _parse_period(period: Any, *, ticker: str, as_of: str, observed_at_et: datetime) -> dict | None:
    """Validate + flatten ONE injected Massive period into a PIT-fit actual-financials record, or return None if
    the period is not PIT-fit (ttm / non-allowed timeframe; an explicitly-null or future filing_date; or an
    acceptance instant AFTER the observation instant — event-after-observation, EXCLUDED, §3.5). A structurally
    malformed period FAILS CLOSED (raise): non-dict, a MISSING required key, a bad-SHAPE (non-null, non-YYYY-MM-DD)
    filing_date (NOT silently absent — sibling us_short_sec_offering_audit parity), bad start/end dates, or a non-tz
    acceptance. Extra Massive keys (cik/company_name/sic/tickers) are tolerated."""
    if not isinstance(period, dict):
        raise MassiveFinancialsError(f"[{ticker}] period 须为 dict: {type(period).__name__}")
    for field in _PERIOD_REQUIRED:
        if field not in period:
            raise MassiveFinancialsError(f"[{ticker}] period 缺必需字段 {field!r}（fail-closed）")
    obs_date = observed_at_et.strftime("%Y-%m-%d")
    timeframe = period["timeframe"]
    if type(timeframe) is not str or timeframe not in _ALLOWED_TIMEFRAMES:   # EXACT str before `in` (hostile subclass __eq__)
        return None                                        # ttm / unknown / non-exact-str timeframe -> not PIT-anchorable -> excluded
    # filing_date is the PIT anchor. Split the three dispositions (do NOT collapse bad-shape into null):
    filing_date = period["filing_date"]
    if filing_date is None:
        return None                                        # explicit null (e.g. ttm rollup) -> unknowable PIT -> excluded
    if not _valid_ymd(filing_date):
        raise MassiveFinancialsError(                      # bad-SHAPE filing_date -> fail closed (a corrupted PIT date
            f"[{ticker}] period filing_date 须为真实 YYYY-MM-DD 或 null（坏形状不静默丢，防真实一期财报无声消失；仅类型 {type(filing_date).__name__}）")
    if filing_date > obs_date:
        return None                                        # filing day-label postdates observation -> look-ahead -> excluded (§3.5)
    # EXACT str: fiscal_period/fiscal_year are hashed into the duplicate-identity set + formatted into `label`; a
    # hostile str-subclass __hash__/__eq__/__format__ must fail closed, never leak a raw exception.
    fiscal_period, fiscal_year = period["fiscal_period"], period["fiscal_year"]
    if not (type(fiscal_period) is str and fiscal_period and type(fiscal_year) is str and fiscal_year):
        raise MassiveFinancialsError(f"[{ticker}] period fiscal_period/fiscal_year 须为非空精确字符串")
    start_date, end_date = period["start_date"], period["end_date"]
    if not (_valid_ymd(start_date) and _valid_ymd(end_date) and start_date <= end_date):
        raise MassiveFinancialsError(f"[{ticker}] period start_date/end_date 须为真实 YYYY-MM-DD 且 start<=end")
    acceptance = period["acceptance_datetime"]
    if not _valid_observed_at(acceptance):
        raise MassiveFinancialsError(f"[{ticker}] period acceptance_datetime 须为 tz-aware RFC3339 时间戳")
    # PIT cut (event <= observed): a period whose filing became public AFTER the observation (observed is already
    # STRICTLY before the 09:30 decision open) was not premarket-known -> excluded, not emitted (§3.5).
    if _observed_at_et(acceptance) > observed_at_et:
        return None
    label = f"{fiscal_year}{fiscal_period}"
    line_items, missing = _extract_line_items(period["financials"], ticker=ticker, period_label=label)
    return {
        "timeframe": timeframe, "fiscal_period": fiscal_period, "fiscal_year": fiscal_year,
        "period_start": start_date, "period_end": end_date,
        "filing_date": filing_date, "acceptance_datetime": acceptance,
        "line_items": line_items, "line_items_missing": sorted(missing),
    }


def resolve_actual_financials(*, as_of: str, financials_by_ticker: Any) -> dict[str, Any]:
    """Resolve injected Massive periodic financials -> per-ticker PIT-anchored 财报实际 fact records, keyed by
    canonical US ticker, with validated §3.1/§3.5 provenance + PIT + coverage/parser fitness.

    `as_of` = the reviewed decision clock (YYYY-MM-DD). Each ticker record = {"periods": [ <Massive periodic
    financials dict: timeframe, fiscal_period, fiscal_year, start_date, end_date, filing_date, acceptance_datetime,
    financials:{income_statement,balance_sheet,cash_flow_statement, ...}> ... ], "provenance": {...7 §3.1 fields}}.
    Provenance is validated BEFORE emit (provider/endpoint pinned, real clocks, the observed instant STRICTLY
    before the 09:30 ET decision open, chronology observed<=source<=as_of). A ticker's records are EMITTED only
    when coverage=='full' AND parser=='ok'; otherwise EXCLUDED. Within a fit ticker, each period is PIT-anchored to
    its real filing_date + acceptance instant (acceptance <= observed); a ttm / non-allowed-timeframe /
    null-or-future-filing_date / accepted-after-observation period is skipped (counted in `skipped_period_count`); a
    duplicate (timeframe, fiscal_year, fiscal_period) fails closed. A full/ok ticker with NO PIT-fit period emits an
    explicit CHECKED coverage record (disposition `checked_no_pit_fit_period`) retaining its provenance — DISTINCT
    from a ticker that was never queried (§3.3).

    Returns {records: {ticker: [ {timeframe, fiscal_period, fiscal_year, period_start, period_end, filing_date,
    acceptance_datetime, line_items: {concept: value}, line_items_missing: [...]} ... sorted by filing_date ]},
    provenance: {ticker: {...7 §3.1 fields, skipped_period_count}}, excluded: {ticker: reason}, checked: {ticker:
    {disposition, coverage_status, parser_status, skipped_period_count}}}. Raises MassiveFinancialsError on any
    malformed / PIT-inconsistent input.
    """
    if not _valid_ymd(as_of):
        raise MassiveFinancialsError(f"as_of 须为真实 YYYY-MM-DD 决策时钟（不回显敌意值，仅类型 {type(as_of).__name__}）")
    canon = _canonical_keyed(financials_by_ticker)
    records: dict[str, list] = {}
    provenance: dict[str, dict] = {}
    excluded: dict[str, str] = {}
    checked: dict[str, dict] = {}
    for ct, rec in canon.items():
        prov = rec["provenance"]
        obs_dt = _validate_provenance(prov, ticker=ct, as_of=as_of)       # fail-closed before any emit; returns ET instant
        if prov["coverage_status"] != _COVERAGE_EMIT or prov["parser_status"] != _PARSER_EMIT:
            excluded[ct] = f"coverage={prov['coverage_status']}/parser={prov['parser_status']}"
            continue
        periods = rec["periods"]
        if not isinstance(periods, list):
            raise MassiveFinancialsError(f"[{ct}].periods 须为 list: {type(periods).__name__}")
        fit: list[dict] = []
        seen_identity: set[tuple] = set()
        for p in periods:
            parsed = _parse_period(p, ticker=ct, as_of=as_of, observed_at_et=obs_dt)
            if parsed is None:
                continue
            identity = tuple(parsed[k] for k in _DUPLICATE_IDENTITY)      # (timeframe, fiscal_year, fiscal_period)
            if identity in seen_identity:
                raise MassiveFinancialsError(
                    f"[{ct}] period 身份 {_DUPLICATE_IDENTITY}={identity} 重复（source-row 不唯一，fail-closed；不静默去重/双计）")
            seen_identity.add(identity)
            fit.append(parsed)
        skipped = len(periods) - len(fit)
        base_prov = {k: prov[k] for k in _PROVENANCE_FIELDS}
        if not fit:
            # full/ok + no PIT-fit period: emit a CHECKED coverage proof (checked clean), retaining provenance so a
            # consumer can tell "checked, no PIT-fit financials" from "never queried" (§3.3, finding C).
            checked[ct] = {"disposition": _CHECKED_EMPTY_DISPOSITION,
                           "coverage_status": prov["coverage_status"], "parser_status": prov["parser_status"],
                           "skipped_period_count": skipped}
            provenance[ct] = {**base_prov, "skipped_period_count": skipped}
            continue
        records[ct] = sorted(fit, key=lambda r: (r["filing_date"], r["fiscal_year"], r["fiscal_period"]))
        provenance[ct] = {**base_prov, "skipped_period_count": skipped}
    return {"records": records, "provenance": provenance, "excluded": excluded, "checked": checked}


def load_binding() -> dict:
    """Load the frozen binding JSON (for the conformance test that triangulates module consts == binding)."""
    return json.loads(BINDING_PATH.read_text(encoding="utf-8"))
