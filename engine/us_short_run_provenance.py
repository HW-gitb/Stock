# -*- coding: utf-8 -*-
"""US-short weekend-pipeline run/input provenance reconciliation — batch4 round-2 slice 1a (PIT 安全闸).

Design authority: docs/us_short_system_design.md §2.1 (canonical decision_date / price_basis_date = 前一已收盘
session / 新闻·语义窗口 = 运行时刻、observed_at<=运行时刻 / live 判据 decision_date>=run_date) / §3.7 (跑前健康检查)
/ §18.0 P0.

Closes the PROVENANCE half of R-USSHORT-BATCH4-PIPELINE-PIT-HEALTH-CALENDAR-GATE-GAP: the orchestrator threads
ONE canonical decision_date to K/L/report/N, but the CONSUMED input families (universe / candidate_pass2_signals
/ selection_inputs / per_ticker_analysis) carried NO reconciled as_of / observed_at / price-basis / session /
adjustment lineage, so a family produced for another run (as_of=20990101) or observed in the future could flow
into the official chain while the visible report still showed a plausible canonical price clock.

§2.1 三钟模型 = a run has EXACTLY ONE (decision_date, price_basis_date, run wall-clock). Every consumed input
family must declare a provenance that reconciles against it, fail-closed BEFORE analysis (no clean build):

  * as_of == decision_date                          — cross-run guard (no last-week / 2099 family);
  * observed_at <= now_et (real ET timestamp)       — future guard (物理抓不到未来; 运行时刻是时刻不是日期);
  * price-bearing family price_basis_date == canonical price_basis_date  — stale / future price guard;
  * exactly one session + one adjustment across all price-bearing families  — mixed-session / mixed-adjustment guard;
  * non-price family declares price_basis_date / session / adjustment = None  — no fabricated price lineage.

OFFLINE only: this reconciles an INJECTED closed-world provenance manifest (batch4 fixture; batch5 fills it from
the real provider behind the same seam). It performs NO provider/live/network/DataHub. The authoritative-calendar
requirement for live/forward mode is a SEPARATE slice (the mode gate, 1c); this slice is the PIT reconciliation
core. No A-share crossing.
"""
from __future__ import annotations

from datetime import datetime

# the consumed input families (closed-world) and which of them are price-bearing (§2.1 price clock applies).
# universe = Pass1 price/ADV/market-cap rows; per_ticker_analysis = §6 price-engine inputs → both price-bearing.
# candidate_pass2_signals = §5 audit/filing signals; selection_inputs = §4.5 derived scores → observed-at only.
PRICE_BEARING_FAMILIES = frozenset({"universe", "per_ticker_analysis"})
NON_PRICE_FAMILIES = frozenset({"candidate_pass2_signals", "selection_inputs"})
EXPECTED_FAMILIES = PRICE_BEARING_FAMILIES | NON_PRICE_FAMILIES

# §2.1 fixes the official price clock to RTH. Current Massive `adjusted=true` evidence confirms split adjustment
# only; dividend reconciliation remains separately unconfirmed, so `split_div_adjusted` must never be fabricated.
# A price family declaring an equal-but-illegal session/adjustment is rejected, not accepted just because both
# price families agree (R-USSHORT-BATCH4-PIPELINE-...: approved-vocab guard).
APPROVED_SESSIONS = frozenset({"RTH"})
APPROVED_ADJUSTMENTS = frozenset({"split_adjusted"})

_FAMILY_COMMON_KEYS = frozenset({"as_of", "observed_at", "price_basis_date", "session", "adjustment", "row_count", "source_refs"})
_PRICE_FAMILY_KEYS = _FAMILY_COMMON_KEYS
_NON_PRICE_FAMILY_KEYS = _FAMILY_COMMON_KEYS
_MANIFEST_KEYS = frozenset({"as_of", "price_basis_date", "families"})
_SOURCE_REF_KEYS = frozenset({"role", "path"})


class RunProvenanceError(Exception):
    """The injected run_provenance manifest does not reconcile against the canonical §2.1 clock (fail-closed)."""


def _strict_yyyymmdd(value) -> bool:
    """Exact 8 ASCII digits + a real calendar date (strptime alone parses 2024011 leniently)."""
    if not (isinstance(value, str) and len(value) == 8 and value.isascii() and value.isdigit()):
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
        return True
    except ValueError:
        return False


def _parse_observed_at(value, where):
    """An input family's PIT observation instant. §2.1 新闻·语义窗口 = 运行时刻（时刻，不是日期）→ a real ET
    timestamp, naive (same convention as the resolver's now_et). Fail-closed on a non-ISO / non-timestamp value."""
    if not isinstance(value, str) or not value.strip():
        raise RunProvenanceError(f"{where}.observed_at 须为 ISO ET 时间戳字符串: {value!r}")
    # §2.1 运行时刻 = 时刻（不是日期）— require an ISO date-TIME ('T' separator), not a date-only string
    # (Python fromisoformat would silently parse '20260613' as midnight, defeating the intraday future-guard).
    if "T" not in value:
        raise RunProvenanceError(
            f"{where}.observed_at 须为含时刻的 ISO 时间戳（'T' 分隔、非纯日期；§2.1 运行时刻是时刻不是日期）: {value!r}")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise RunProvenanceError(f"{where}.observed_at 非法 ISO 时间戳（须含日期+时刻、naive ET）: {value!r}")
    if dt.tzinfo is not None:
        raise RunProvenanceError(f"{where}.observed_at 须为 naive ET 时间戳（与 resolver now_et 同口径）: {value!r}")
    return dt


def _validate_source_refs(value, where):
    if not isinstance(value, list) or not value:
        raise RunProvenanceError(f"{where}.source_refs must be a non-empty list")
    seen = set()
    for idx, ref in enumerate(value):
        if not (isinstance(ref, dict) and set(ref) == _SOURCE_REF_KEYS):
            raise RunProvenanceError(f"{where}.source_refs[{idx}] keys must be {sorted(_SOURCE_REF_KEYS)}")
        role = ref["role"]
        path = ref["path"]
        if not (type(role) is str and role.strip()):
            raise RunProvenanceError(f"{where}.source_refs[{idx}].role must be a non-empty str")
        if not (type(path) is str and path.strip()):
            raise RunProvenanceError(f"{where}.source_refs[{idx}].path must be a non-empty str")
        if "://" in path or "\\" in path or ":" in path or path.startswith("/") or "/../" in f"/{path}/":
            raise RunProvenanceError(f"{where}.source_refs[{idx}].path must be a clean repo-relative path")
        identity = (role, path)
        if identity in seen:
            raise RunProvenanceError(f"{where}.source_refs contains duplicate role/path")
        seen.add(identity)


def _family_entries(name, payload):
    """Normalize a consumed family's ACTUAL payload to (row_count, [dict rows]) so the manifest can be BOUND to it:
    universe = a list of rows; candidate_pass2_signals / per_ticker_analysis = a {ticker: row} map; selection_inputs
    = its `per_ticker` map. A wrong-shaped payload yields 0 rows so a nonzero manifest row_count fails closed."""
    if name == "universe":
        rows = payload if isinstance(payload, list) else []
    elif name == "selection_inputs":
        pt = payload.get("per_ticker") if isinstance(payload, dict) else None
        rows = list(pt.values()) if isinstance(pt, dict) else []
    else:  # candidate_pass2_signals / per_ticker_analysis: {ticker: row}
        rows = list(payload.values()) if isinstance(payload, dict) else []
    return len(rows), [r for r in rows if isinstance(r, dict)]


def reconcile_run_provenance(run_provenance, *, now_et, decision_date, price_basis_date, run_date, payloads) -> dict:
    """Reconcile the injected run_provenance manifest against the resolved §2.1 canonical clock.

    run_provenance = {
        "as_of": <YYYYMMDD>,                 # the run's canonical decision anchor (== decision_date)
        "price_basis_date": <YYYYMMDD>,      # the run's price clock (== resolved prior closed session)
        "families": {                        # closed-world: EXACTLY the consumed input families
            "universe":                {"as_of","observed_at","price_basis_date","session","adjustment"},
            "per_ticker_analysis":     {... price-bearing: price_basis_date/session/adjustment non-null ...},
            "candidate_pass2_signals": {... non-price: price_basis_date/session/adjustment = None ...},
            "selection_inputs":        {... non-price ...},
        }}
    now_et / decision_date / price_basis_date / run_date = the resolver outputs for THIS run (§2.1).

    Returns a normalized provenance summary {as_of, price_basis_date, run_date, session, adjustment,
    families:{name: observed_at_iso}} on success. Raises RunProvenanceError on any future / stale / cross-run /
    mixed-session / mixed-adjustment / malformed input — BEFORE analysis, so a contaminated input can never reach
    the official chain. Pure/offline; no provider/live/network.
    """
    # the resolver clocks must themselves be the strict §2.1 triple in legal order (defensive — never trust shape).
    for name, v in (("decision_date", decision_date), ("price_basis_date", price_basis_date), ("run_date", run_date)):
        if not _strict_yyyymmdd(v):
            raise RunProvenanceError(f"resolver {name} 须为真实 YYYYMMDD: {v!r}")
    if not (price_basis_date <= run_date <= decision_date):
        raise RunProvenanceError(
            "resolver 三钟顺序非法（须 price_basis_date <= run_date <= decision_date，§2.1）: "
            f"{price_basis_date!r}/{run_date!r}/{decision_date!r}")
    if not isinstance(now_et, datetime) or now_et.tzinfo is not None:
        raise RunProvenanceError("now_et 须为 naive ET datetime（与 resolver 同口径）")

    if not (isinstance(run_provenance, dict) and set(run_provenance) == _MANIFEST_KEYS):
        raise RunProvenanceError(
            f"run_provenance 顶层键须恰为 {sorted(_MANIFEST_KEYS)}（closed-world）: "
            f"{sorted(run_provenance) if isinstance(run_provenance, dict) else run_provenance!r}")
    if not _strict_yyyymmdd(run_provenance["as_of"]) or run_provenance["as_of"] != decision_date:
        raise RunProvenanceError(
            f"run_provenance.as_of 须 == 本 run decision_date={decision_date!r}（cross-run 守卫）: {run_provenance['as_of']!r}")
    if not _strict_yyyymmdd(run_provenance["price_basis_date"]) or run_provenance["price_basis_date"] != price_basis_date:
        raise RunProvenanceError(
            f"run_provenance.price_basis_date 须 == 本 run price_basis_date={price_basis_date!r}（陈旧/未来价守卫）: "
            f"{run_provenance['price_basis_date']!r}")

    families = run_provenance["families"]
    if not (isinstance(families, dict) and set(families) == EXPECTED_FAMILIES):
        raise RunProvenanceError(
            f"run_provenance.families 须恰覆盖消费输入族 {sorted(EXPECTED_FAMILIES)}（closed-world）: "
            f"{sorted(families) if isinstance(families, dict) else families!r}")
    # the manifest must be BOUND to the ACTUAL consumed payload, not a separable self-report (①a): payloads must
    # cover exactly the same families, so per-family row_count + per-row provenance can be reconciled below.
    if not (isinstance(payloads, dict) and set(payloads) == EXPECTED_FAMILIES):
        raise RunProvenanceError(
            f"payloads 须恰覆盖消费输入族 {sorted(EXPECTED_FAMILIES)}（manifest 须绑 payload，不可脱钩）: "
            f"{sorted(payloads) if isinstance(payloads, dict) else payloads!r}")

    sessions_seen, adjustments_seen = set(), set()
    families_observed = {}
    for name in sorted(EXPECTED_FAMILIES):
        fam = families[name]
        price_bearing = name in PRICE_BEARING_FAMILIES
        expected_keys = _PRICE_FAMILY_KEYS if price_bearing else _NON_PRICE_FAMILY_KEYS
        if not (isinstance(fam, dict) and set(fam) == expected_keys):
            raise RunProvenanceError(
                f"families[{name!r}] 键须恰为 {sorted(expected_keys)}: "
                f"{sorted(fam) if isinstance(fam, dict) else fam!r}")
        # as_of == decision_date (cross-run); a family produced for another run never flows in.
        if not _strict_yyyymmdd(fam["as_of"]) or fam["as_of"] != decision_date:
            raise RunProvenanceError(
                f"families[{name!r}].as_of 须 == decision_date={decision_date!r}（cross-run 守卫）: {fam['as_of']!r}")
        # observed_at <= now_et (future guard at TIMESTAMP granularity — 运行时刻是时刻; 物理抓不到未来观测).
        observed = _parse_observed_at(fam["observed_at"], f"families[{name!r}]")
        if observed > now_et:
            raise RunProvenanceError(
                f"families[{name!r}].observed_at {fam['observed_at']!r} 晚于运行时刻 now_et={now_et.isoformat()!r}"
                "（未来观测守卫，§2.1 observed_at<=运行时刻）")
        families_observed[name] = fam["observed_at"]
        _validate_source_refs(fam["source_refs"], f"families[{name!r}]")
        # ①a bind manifest entry to the ACTUAL payload: row_count must match, and NO payload row may carry its OWN
        # as_of/observed_at that contradicts the manifest (clean-manifest/dirty-payload guard — a row tagged
        # as_of=2099 behind a clean manifest now fails closed HERE, not silently dropped by downstream projection).
        actual_count, fam_rows = _family_entries(name, payloads[name])
        if fam["row_count"] != actual_count:
            raise RunProvenanceError(
                f"families[{name!r}].row_count {fam['row_count']!r} != 实际 payload 行数 {actual_count}（manifest 须绑 payload）")
        for r in fam_rows:
            if r.get("as_of") not in (None, fam["as_of"]):
                raise RunProvenanceError(
                    f"families[{name!r}] payload 某行 as_of {r.get('as_of')!r} 与 manifest as_of {fam['as_of']!r} "
                    "矛盾（clean-manifest/dirty-payload 守卫）")
            if r.get("observed_at") not in (None, fam["observed_at"]):
                raise RunProvenanceError(
                    f"families[{name!r}] payload 某行 observed_at {r.get('observed_at')!r} 与 manifest observed_at "
                    f"{fam['observed_at']!r} 矛盾（clean-manifest/dirty-payload 守卫）")
        if price_bearing:
            # price-bearing: price_basis_date == canonical (stale/future price), session/adjustment present + single-valued.
            if not _strict_yyyymmdd(fam["price_basis_date"]) or fam["price_basis_date"] != price_basis_date:
                raise RunProvenanceError(
                    f"families[{name!r}].price_basis_date 须 == 本 run price_basis_date={price_basis_date!r}"
                    f"（陈旧/未来价守卫）: {fam['price_basis_date']!r}")
            if fam["session"] not in APPROVED_SESSIONS:
                raise RunProvenanceError(
                    f"families[{name!r}].session 非法（须 ∈ {sorted(APPROVED_SESSIONS)}，§2.1 官方价格钟 = RTH；equal-but-illegal 也拒）: {fam['session']!r}")
            if fam["adjustment"] not in APPROVED_ADJUSTMENTS:
                raise RunProvenanceError(
                    f"families[{name!r}].adjustment 非法（须 ∈ {sorted(APPROVED_ADJUSTMENTS)}，确认复权语义、拒 raw/unknown）: {fam['adjustment']!r}")
            sessions_seen.add(fam["session"])
            adjustments_seen.add(fam["adjustment"])
        else:
            # non-price: no fabricated price lineage (price_basis_date / session / adjustment must be None).
            for k in ("price_basis_date", "session", "adjustment"):
                if fam[k] is not None:
                    raise RunProvenanceError(
                        f"families[{name!r}] 为非价格族、{k} 须为 None（不得伪造价格血缘）: {fam[k]!r}")

    # exactly one session + one adjustment across ALL price-bearing families (mixed-session/adjustment guard).
    if len(sessions_seen) != 1:
        raise RunProvenanceError(f"价格族 session 不唯一（mixed-session 守卫）: {sorted(sessions_seen)}")
    if len(adjustments_seen) != 1:
        raise RunProvenanceError(f"价格族 adjustment 不唯一（mixed-adjustment 守卫）: {sorted(adjustments_seen)}")

    return {
        "as_of": decision_date,
        "price_basis_date": price_basis_date,
        "run_date": run_date,
        "session": next(iter(sessions_seen)),
        "adjustment": next(iter(adjustments_seen)),
        "families": families_observed,
    }
