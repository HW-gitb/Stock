# -*- coding: utf-8 -*-
"""US-short FMP ANALYST-GRADES source — batch5 Cut 5, slice 5-c (offline half).

Design authority: docs/us_short_system_design.md §4.2 (分析师修正) / §5.2 (分析师集体下调 candidate veto) /
§3.1 (provenance) / §3.5 (评级动作日与 as_of 是不同 PIT 事实; 不用 look-ahead) / §18.2 (跨模块契约先
schema-first 冻结再消费). Frozen contract: docs/us_short_cut5_fmp_analyst_grades_binding_20260701.json (+ its
schema; module consts below are triangulated == that binding by a conformance test).

WHAT THIS IS — the OFFLINE half of the (SR-PROVIDER-001-gated) FMP analyst rating-change data layer. Reachability
+ real shape were PROVEN 2026-07-01 (docs/us_short_cut5_pass2_feasibility_probe_summary_20260701.json + captured
gitignored raw): FMP stable /grades returns a LIST of {symbol, date, gradingCompany, newGrade, previousGrade,
action} rating-change records; FMP CLASSIFIES the `action` (upgrade / downgrade / maintain / ...) itself. This
layer takes INJECTED per-ticker FMP grades (the gated live half fetches them), applies the repo's SINGLE US-ticker
identity policy (`canonical_us_ticker`), validates the pull's §3.1 provenance + coverage/parser fitness, PIT-cuts
each record to its `date` (<= as_of) within a recency window, derives a DIRECTION from FMP's own `action`
(upgrade->up, downgrade->down, anything else->neutral — NO fragile grade-string ranking), and summarizes the
recent-window actions into the §4.2 analyst-revision-direction signal + the §5.2 collective-downgrade basis.

This is the FREE proxy for the (paywalled, user-deferred 2026-07-01) numeric analyst-estimate revisions: FMP
earnings-surprises / analyst-estimates were 404/400, and the estimate half stays un-hooked; the rating-change
DIRECTION (grades) is the reachable free sentiment signal.

WHAT THIS IS NOT — no fetch (no network/provider; SR-PROVIDER-001 gates the live half + the runner wiring), does
NOT SCORE (this is the fact+summary layer; the wiring into the catalyst analyst component / a §5.2 candidate-veto
accumulator is a later seam), does NOT rank analyst grade strings (scales differ across firms; only FMP's `action`
drives direction), and does NOT cross A-share. Only the offline contract SHAPE is frozen here.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.us_short_eligibility_gate import canonical_us_ticker  # the repo's single US ticker identity policy

BINDING_PATH = (Path(__file__).resolve().parents[1]
                / "docs" / "us_short_cut5_fmp_analyst_grades_binding_20260701.json")

PROVIDER_ID = "fmp"
ENDPOINT = "grades"
_DECISION_TZ_NAME = "America/New_York"
_RECENCY_WINDOW_DAYS = 90                                # §4.2/§5.2 recent-analyst-sentiment prior (reviewed, not alpha)
# action -> direction. FMP's own `action` drives it; any action not in this map -> the default (neutral), so a
# maintain / initiate / reiterate / unknown action never fabricates an up/down. == binding direction_map
# (triangulated: the two non-default entries + the default).
_DIRECTION_MAP = {"upgrade": "up", "downgrade": "down"}
_DIRECTION_DEFAULT = "neutral"
_RECORD_REQUIRED = ("date", "action", "gradingCompany", "newGrade", "previousGrade")
_PROVENANCE_FIELDS = frozenset({"provider_id", "endpoint_or_filing_type", "source_as_of",
                                "observed_at", "coverage_status", "parser_status", "lineage_ref"})
_COVERAGE_ALLOWED = frozenset({"full", "partial", "missing"})
_PARSER_ALLOWED = frozenset({"ok", "degraded", "failed"})
_COVERAGE_EMIT = "full"
_PARSER_EMIT = "ok"
_RECORD_KEYS = frozenset({"records", "provenance"})
_DECISION_CUTOFF_HHMM = (9, 30)                          # decision-session open (§2.1); observed_at must be strictly before
# Machine-readable PIT / identity / firm-normalization / checked-empty / authorization POLICY consts — triangulated
# == the binding's frozen fields (a conformance test asserts equality), so the offline shared contract §18.2 requires
# cannot drift (Codex Cut5 finding D: freeze the POLICIES, not just the vocabularies).
_CUTOFF_OPERATOR = "strictly_before"                     # observed_at < decision_open (half-open, matches resolve_canonical_asof)
_CUTOFF_REFERENCE = "decision_session_open"              # the 09:30 ET open on as_of
_CHRONOLOGY_ORDER = ("record_date", "observed_at", "source_as_of", "as_of")   # each <= the next (non-decreasing)
_LINEAGE_REF_FORMAT = "provider_id:endpoint_or_filing_type:source_as_of#record_id"
# a grade action's source-row identity; grading_company is normalized (strip + casefold) so ` bankx `/`BankX`/`BANKX`
# are ONE firm, and an exact/canonical duplicate action fails closed (never inflating net / distinct_firms).
_DUPLICATE_IDENTITY = ("record_date", "grading_company", "action", "new_grade", "previous_grade")
_FIRM_NORMALIZATION = "strip_and_casefold"
_DUPLICATE_POLICY = "reject"
_CHECKED_EMPTY_DISPOSITION = "checked_no_recent_activity"   # full/ok + zero in-window grade -> retained coverage proof
_AUTHORIZATION_BOUNDARY = {
    "live_fetch": False, "network": False, "raw_capture": False, "runner_wired": False,
    "datahub": False, "production": False, "ship_gate": False,
}


class FmpGradesError(ValueError):
    """An injected FMP grades payload is malformed / mis-provenanced / PIT-inconsistent, or a source's ticker keys
    alias to the same canonical US ticker (fail-closed; never fabricates an analyst direction)."""


def _valid_ymd(s: Any) -> bool:
    if not (type(s) is str and len(s) == 10 and s.isascii()):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _valid_observed_at(s: Any) -> bool:
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
        raise FmpGradesError("无 zoneinfo，无法归一化决策时区，拒绝降级") from exc
    try:
        return ZoneInfo(_DECISION_TZ_NAME)
    except ZoneInfoNotFoundError as exc:
        raise FmpGradesError(f"无 {_DECISION_TZ_NAME} 时区库(tzdata)，无法归一化决策时区，拒绝降级") from exc


def _observed_at_et(observed_at: str) -> datetime:
    """The observation as an ET-normalized aware datetime (DST-aware), so a caller's offset cannot shift the PIT
    instant/date. Fail-closed (raise) on an out-of-range boundary-year timestamp whose tz conversion would leak a
    raw OverflowError. Assumes `observed_at` already passed `_valid_observed_at` (exact str)."""
    tz = _et_tz()
    inst = datetime.fromisoformat(observed_at[:-1] + "+00:00" if observed_at.endswith("Z") else observed_at)
    try:
        return inst.astimezone(tz)
    except (OverflowError, OSError) as exc:            # absurd boundary-year clock -> FmpGradesError, not raw OverflowError
        raise FmpGradesError(f"observed_at 超出可归一化时区范围（非真实 provider 时钟）: {observed_at!r}") from exc


def _decision_cutoff(as_of: str) -> datetime:
    """The canonical decision cutoff = the decision-session 09:30 ET open on `as_of` (§2.1). `observed_at` must be
    STRICTLY before this instant (half-open window; 09:30 itself is out-of-window, matching resolve_canonical_asof).
    Assumes `as_of` already passed `_valid_ymd` (YYYY-MM-DD)."""
    return datetime(int(as_of[:4]), int(as_of[5:7]), int(as_of[8:10]),
                    _DECISION_CUTOFF_HHMM[0], _DECISION_CUTOFF_HHMM[1], tzinfo=_et_tz())


def _norm_firm(company: str) -> str:
    """The frozen firm-identity normalization (strip + casefold), so ` bankx `, `BankX`, and `BANKX` are ONE firm
    for the duplicate-action identity and the distinct_firms count (whitespace/case-only variants do not inflate)."""
    return " ".join(company.split()).casefold()


def _valid_lineage_ref(ref: Any, *, source_as_of: str) -> bool:
    if not (type(ref) is str and ref.isascii()):
        return False
    prefix, sep, rid = ref.rpartition("#")
    if sep != "#" or not rid or any(c.isspace() for c in rid) or ":" in rid or "#" in rid:
        return False
    return prefix == f"{PROVIDER_ID}:{ENDPOINT}:{source_as_of}"


def _validate_provenance(prov: Any, *, ticker: str, as_of: str) -> datetime:
    """Fail-closed §3.1/§3.5 provenance check for ONE ticker's grades pull (mirrors the sibling sources). The
    observed_at is a tz-aware INSTANT STRICTLY before the 09:30 ET decision open on as_of (half-open); chronology
    `observed_at ET date <= source_as_of <= as_of`. Returns the ET-normalized observation instant (so a date-only
    grade record can be bound to the observed date)."""
    if not (isinstance(prov, dict) and all(type(pk) is str for pk in prov) and set(prov) == _PROVENANCE_FIELDS):
        raise FmpGradesError(f"[{ticker}].provenance 键须恰为精确 str 的 {sorted(_PROVENANCE_FIELDS)}（§3.1，fail-closed）")
    if (type(prov["provider_id"]) is not str or type(prov["endpoint_or_filing_type"]) is not str
            or prov["provider_id"] != PROVIDER_ID or prov["endpoint_or_filing_type"] != ENDPOINT):
        raise FmpGradesError(f"[{ticker}].provenance provider/endpoint 与冻结 binding 不符（须 {PROVIDER_ID}/{ENDPOINT}）")
    src_as_of = prov["source_as_of"]
    if not _valid_ymd(src_as_of):
        raise FmpGradesError(f"[{ticker}].provenance source_as_of 须为真实 YYYY-MM-DD")
    if not _valid_observed_at(prov["observed_at"]):
        raise FmpGradesError(f"[{ticker}].provenance observed_at 须为 tz-aware RFC3339 时间戳（§3.5 决策截止需瞬时精度，非日期）")
    # A-clock (HALF-OPEN [prior_close, decision_open), §2.1/§3.5): observation INSTANT STRICTLY before the 09:30 ET
    # decision open on as_of — exactly 09:30 is OUT-OF-WINDOW (matching resolve_canonical_asof).
    obs_dt = _observed_at_et(prov["observed_at"])
    if obs_dt >= _decision_cutoff(as_of):
        raise FmpGradesError(
            f"[{ticker}].provenance observed_at 不早于决策开盘（{as_of} 09:30 ET 半开边界；09:30 及之后 out-of-window/look-ahead，§2.1/§3.5）")
    obs_date = obs_dt.strftime("%Y-%m-%d")
    if not (obs_date <= src_as_of):
        raise FmpGradesError(f"[{ticker}].provenance source_as_of 早于观测日期（源快照不能早于它含的证据；§3.5）")
    if not (src_as_of <= as_of):
        raise FmpGradesError(f"[{ticker}].provenance source_as_of 晚于决策 as_of={as_of}（look-ahead；§3.5）")
    if type(prov["coverage_status"]) is not str or prov["coverage_status"] not in _COVERAGE_ALLOWED:
        raise FmpGradesError(f"[{ticker}].provenance coverage_status 非法（须 ∈ {sorted(_COVERAGE_ALLOWED)}）")
    if type(prov["parser_status"]) is not str or prov["parser_status"] not in _PARSER_ALLOWED:
        raise FmpGradesError(f"[{ticker}].provenance parser_status 非法（须 ∈ {sorted(_PARSER_ALLOWED)}）")
    if not _valid_lineage_ref(prov["lineage_ref"], source_as_of=src_as_of):
        raise FmpGradesError(
            f"[{ticker}].provenance lineage_ref 须为结构化 source-bound 引用 "
            f"'{PROVIDER_ID}:{ENDPOINT}:{src_as_of}#<record_id>'（非自由文本）")
    return obs_dt


def _canonical_keyed(grades_by_ticker: Any) -> dict:
    """Re-key {ticker: {records, provenance}} by canonical US ticker (mirrors the sibling sources' hostile-key
    hardening). None -> {}; invalid/non-string/cross-market/non-ASCII keys dropped; alias collision RAISES;
    record keys must be EXACT str and EXACTLY {records, provenance}; never echoes the caller's keys."""
    if grades_by_ticker is None:
        return {}
    if not isinstance(grades_by_ticker, dict):
        raise FmpGradesError(f"grades_by_ticker 须为 dict 或 None: {type(grades_by_ticker).__name__}")
    out: dict[str, dict] = {}
    for k, v in grades_by_ticker.items():
        if type(k) is not str:
            continue
        ck = canonical_us_ticker(k)
        if ck is None:
            continue
        if not isinstance(v, dict):
            raise FmpGradesError(f"[{ck}] 记录须为 dict: {type(v).__name__}")
        if not all(type(rk) is str for rk in v):
            raise FmpGradesError(f"[{ck}] 记录键须为精确 str（拒 str 子类/非串，fail-closed，不回显敌意键）")
        if set(v) != _RECORD_KEYS:
            raise FmpGradesError(f"[{ck}] 记录键须恰为 {sorted(_RECORD_KEYS)}（fail-closed，不回显实际键）")
        if ck in out:
            raise FmpGradesError(f"规范化后重复 ticker {ck!r}（别名歧义，fail-closed；不静默去重）")
        out[ck] = v
    return out


def _direction(action: str) -> str:
    return _DIRECTION_MAP.get(action, _DIRECTION_DEFAULT)


def _days_between(later_ymd: str, earlier_ymd: str) -> int:
    return (datetime.strptime(later_ymd, "%Y-%m-%d").date()
            - datetime.strptime(earlier_ymd, "%Y-%m-%d").date()).days


def _classify_grade_record(record: Any, *, ticker: str, as_of: str, obs_date: str,
                           window: int) -> tuple[str, dict | None]:
    """Validate ONE injected FMP grade record -> ("fit", record) | ("future", None) | ("stale", None). A
    structurally malformed record (non-dict, missing a required key, bad-SHAPE date, non-str/empty-or-whitespace
    action/company/new_grade, non-str previous_grade, or a symbol that disagrees with the ticker key) FAILS CLOSED
    (raise). A record dated AFTER the observation date (`> obs_date`) is excluded — a day-only grade action is only
    in-window if it is provably at-or-before the moment we observed it pre-open (§3.5, no same-day post-open
    look-ahead); a date older than `window` (measured from as_of) is out-of-window. The grading firm is normalized
    (whitespace-collapsed, case preserved) so identity/counting can casefold. Extra FMP keys (symbol etc.) are
    tolerated (symbol, if present, is cross-checked)."""
    if not isinstance(record, dict):
        raise FmpGradesError(f"[{ticker}] grade record 须为 dict: {type(record).__name__}")
    for field in _RECORD_REQUIRED:
        if field not in record:
            raise FmpGradesError(f"[{ticker}] grade record 缺必需字段 {field!r}（fail-closed）")
    date = record["date"]
    if not _valid_ymd(date):
        raise FmpGradesError(f"[{ticker}] grade record date 须为真实 YYYY-MM-DD（坏形状不静默丢；仅类型 {type(date).__name__}）")
    # EXACT str (`type() is str`) for every value that feeds _direction (_DIRECTION_MAP.get -> hash), .split(), or the
    # duplicate-identity tuple (hashed into seen_identity): a hostile str-subclass __hash__/__eq__/method must fail
    # closed as FmpGradesError, never a raw exception (whole-class value hardening, mirrors the key/symbol guards).
    action = record["action"]
    if not (type(action) is str and action):
        raise FmpGradesError(f"[{ticker}] grade record action 须为非空字符串")
    company = record["gradingCompany"]
    if not (type(company) is str and company.strip()):   # reject empty AND whitespace-only firm (traceable identity)
        raise FmpGradesError(f"[{ticker}] grade record gradingCompany 须为非空、非纯空白字符串")
    company = " ".join(company.split())                    # collapse interior/edge whitespace (case preserved)
    new_grade = record["newGrade"]
    if not (type(new_grade) is str and new_grade):
        raise FmpGradesError(f"[{ticker}] grade record newGrade 须为非空字符串")
    prev_grade = record["previousGrade"]
    if type(prev_grade) is not str:                       # may be "" (an initiate has no prior grade), but must be exact str
        raise FmpGradesError(f"[{ticker}] grade record previousGrade 须为字符串（可空串）")
    sym = record.get("symbol")
    if sym is not None:                                    # cross-check FMP's own symbol against the ticker key
        if type(sym) is not str or canonical_us_ticker(sym) != ticker:   # exact-str: a subclass can't reach canonical/repr
            raise FmpGradesError(f"[{ticker}] grade record symbol 与 ticker 键不一致或非精确 str（防误 attribution；仅类型 {type(sym).__name__}）")
    if date > obs_date:
        return ("future", None)                            # dated after the observation -> look-ahead -> excluded (§3.5)
    if _days_between(as_of, date) > window:
        return ("stale", None)                             # older than the recency window -> out-of-window
    return ("fit", {"date": date, "grading_company": company, "new_grade": new_grade,
                    "previous_grade": prev_grade, "action": action, "direction": _direction(action)})


def resolve_analyst_grade_actions(*, as_of: str, grades_by_ticker: Any) -> dict[str, Any]:
    """Resolve injected FMP analyst grades -> per-ticker recent-window rating-change facts + a direction summary,
    keyed by canonical US ticker, with validated §3.1/§3.5 provenance + PIT + coverage/parser fitness.

    `as_of` = the reviewed decision clock (YYYY-MM-DD). Each ticker record = {"records": [ {symbol, date,
    gradingCompany, newGrade, previousGrade, action} ... ], "provenance": {...7 §3.1 fields}}. Provenance is
    validated BEFORE emit (the observed instant STRICTLY before the 09:30 ET decision open); a ticker is EMITTED
    only when coverage=='full' AND parser=='ok', else EXCLUDED. Each record is PIT-cut to its `date` bound to the
    observation date (a record dated after the observation is look-ahead and excluded — a same-day grade is in-window
    only if provably observed pre-open); an out-of-window (old, > window from as_of) date is counted but not in the
    summary. Direction comes from FMP's own `action` (upgrade->up, downgrade->down, else->neutral). A duplicate
    (date, normalized-firm, action, new_grade, previous_grade) fails closed (no inflated net/distinct_firms). A
    full/ok ticker with ZERO in-window records emits an explicit CHECKED coverage record (disposition
    `checked_no_recent_activity`) retaining its provenance — DISTINCT from a never-queried ticker (§3.3).

    Returns {signals: {ticker: {analyst_actions_recent: {upgrades, downgrades, neutrals, net, distinct_firms,
    window_days}}}, records: {ticker: [ {date, grading_company, new_grade, previous_grade, action, direction} ...
    sorted by date ]}, provenance: {ticker: {...7 §3.1 fields, total_record_count, out_of_window_count,
    future_excluded_count}}, excluded: {ticker: reason}, checked: {ticker: {disposition, coverage_status,
    parser_status, total_record_count, out_of_window_count, future_excluded_count}}}. Raises FmpGradesError on any
    malformed / PIT-inconsistent input.
    """
    if not _valid_ymd(as_of):
        raise FmpGradesError(f"as_of 须为真实 YYYY-MM-DD 决策时钟（不回显敌意值，仅类型 {type(as_of).__name__}）")
    canon = _canonical_keyed(grades_by_ticker)
    signals: dict[str, dict] = {}
    records: dict[str, list] = {}
    provenance: dict[str, dict] = {}
    excluded: dict[str, str] = {}
    checked: dict[str, dict] = {}
    for ct, rec in canon.items():
        prov = rec["provenance"]
        obs_dt = _validate_provenance(prov, ticker=ct, as_of=as_of)      # fail-closed before any emit; returns ET instant
        if prov["coverage_status"] != _COVERAGE_EMIT or prov["parser_status"] != _PARSER_EMIT:
            excluded[ct] = f"coverage={prov['coverage_status']}/parser={prov['parser_status']}"
            continue
        obs_date = obs_dt.strftime("%Y-%m-%d")
        raw_records = rec["records"]
        if not isinstance(raw_records, list):
            raise FmpGradesError(f"[{ct}].records 须为 list: {type(raw_records).__name__}")
        fit: list[dict] = []
        seen_identity: set[tuple] = set()
        future_n = stale_n = 0
        for r in raw_records:
            disposition, parsed = _classify_grade_record(
                r, ticker=ct, as_of=as_of, obs_date=obs_date, window=_RECENCY_WINDOW_DAYS)
            if disposition == "fit":
                identity = (parsed["date"], _norm_firm(parsed["grading_company"]), parsed["action"],
                            parsed["new_grade"], parsed["previous_grade"])
                if identity in seen_identity:
                    raise FmpGradesError(
                        f"[{ct}] grade record 身份 {_DUPLICATE_IDENTITY}={identity} 重复（source-row 不唯一，fail-closed；不静默去重/双计）")
                seen_identity.add(identity)
                fit.append(parsed)
            elif disposition == "future":
                future_n += 1
            else:
                stale_n += 1
        base_prov = {k: prov[k] for k in _PROVENANCE_FIELDS}
        counts = {"total_record_count": len(raw_records), "out_of_window_count": stale_n,
                  "future_excluded_count": future_n}
        if not fit:
            # full/ok + no in-window grade: emit a CHECKED coverage proof, retaining provenance so a consumer can
            # tell "checked, no recent analyst activity" from "never queried" (§3.3, finding C).
            checked[ct] = {"disposition": _CHECKED_EMPTY_DISPOSITION, "coverage_status": prov["coverage_status"],
                           "parser_status": prov["parser_status"], **counts}
            provenance[ct] = {**base_prov, **counts}
            continue
        fit.sort(key=lambda r: (r["date"], _norm_firm(r["grading_company"])))
        upgrades = sum(1 for r in fit if r["direction"] == "up")
        downgrades = sum(1 for r in fit if r["direction"] == "down")
        neutrals = len(fit) - upgrades - downgrades
        distinct_firms = len({_norm_firm(r["grading_company"]) for r in fit})
        signals[ct] = {"analyst_actions_recent": {
            "upgrades": upgrades, "downgrades": downgrades, "neutrals": neutrals,
            "net": upgrades - downgrades, "distinct_firms": distinct_firms, "window_days": _RECENCY_WINDOW_DAYS}}
        records[ct] = fit
        provenance[ct] = {**base_prov, **counts}
    return {"signals": signals, "records": records, "provenance": provenance, "excluded": excluded, "checked": checked}


def load_binding() -> dict:
    """Load the frozen binding JSON (for the conformance test that triangulates module consts == binding)."""
    return json.loads(BINDING_PATH.read_text(encoding="utf-8"))
