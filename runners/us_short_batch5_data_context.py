from __future__ import annotations

import math
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo

from engine.us_short_catalyst import CatalystGovernanceError
from engine.us_short_eligibility_gate import (
    canonical_us_ticker,
    inject_catalyst_recall,
    pass2_safety_admit,
)
from engine.us_short_analyst_grade_risk import (
    AnalystGradeRiskError,
    project_analyst_grade_risk_downgrade,
)
from engine.us_short_massive_news_catalyst import (
    MassiveNewsCatalystSeamError,
    project_massive_news_catalyst,
)
from engine.us_short_overextension import validate_overextension_result
from engine.us_short_overextension_producer import eligible_tickers_sha256
from engine.us_short_risk_downgrade import risk_downgrade
from engine.us_short_sec_offering_audit import (
    OfferingAuditError,
    build_offering_audit_from_sec_submissions,
)
from engine.us_short_seam_score import OUTPUT_KEYS, ScoreSeamError, compose_score_inputs
from runners.us_short_universe_fetch import (
    eligible_tickers_from_rows,
    validate_candidate_artifact,
)
from runners.us_short_batch5_full_universe_momentum_fetch import (
    ADJUSTMENT_MODE as OVEREXTENSION_SOURCE_ADJUSTMENT_MODE,
    SESSION_LABEL as OVEREXTENSION_SOURCE_SESSION,
)


DATA_CONTEXT_KEYS = (
    "universe",
    "catalyst_recall_feed",
    "holdings",
    "candidate_pass2_signals",
    "selection_inputs",
)
UNIVERSE_ROW_KEYS = (
    "ticker",
    "exchange",
    "price",
    "adv_usd",
    "market_cap_usd",
    "delisted",
    "halted",
    "bankruptcy",
    "otc",
)
SELECTION_INPUT_KEYS = {"theme_opportunity_state", "per_ticker"}
SELECTION_ROW_KEYS = {"core_score", "theme_momentum_score"}
PASS2_SOURCE_KEYS = {"offering_audit"}
PASS2_SOURCE_DISPOSITIONS = ("signals", "checked", "excluded")
SOURCE_REF_PATH_KEYS = (
    "candidate_artifact_path",
    "eligibility_governance_path",
    "momentum_projection_path",
    "theme_projection_path",
    "offering_audit_source_path",
    "analyst_grade_actions_path",
    "massive_news_events_path",
    "catalyst_governance_path",
)
OPTIONAL_SOURCE_REF_PATH_KEYS = ("overextension_projection_path", "yfinance_grade_actions_path")
_SOURCE_REF_ROLE_BY_PATH_KEY = {
    key: key[:-5] if key.endswith("_path") else key
    for key in (*SOURCE_REF_PATH_KEYS, *OPTIONAL_SOURCE_REF_PATH_KEYS)
}
_FAMILY_SOURCE_REF_ROLES = {
    "universe": ("candidate_artifact", "eligibility_governance"),
    "candidate_pass2_signals": ("offering_audit_source",),
    "selection_inputs": (
        "momentum_projection",
        "theme_projection",
        "offering_audit_source",
        "analyst_grade_actions",
        "massive_news_events",
        "catalyst_governance",
    ),
    "per_ticker_analysis": (
        "candidate_artifact",
        "momentum_projection",
        "theme_projection",
        "analyst_grade_actions",
        "massive_news_events",
        "catalyst_governance",
    ),
}


class DataContextAssemblyError(ValueError):
    """Batch5 provider-side source rows cannot be assembled into Batch4 data_context."""


def _fail(message: str) -> None:
    raise DataContextAssemblyError(message)


def _canonical_ticker(raw: Any, *, where: str) -> str:
    ticker = canonical_us_ticker(raw)
    if ticker is None:
        _fail(f"{where} must be a canonicalizable US ticker: {raw!r}")
    return ticker


def _canonical_ticker_list(value: Any, *, where: str) -> list[str]:
    if type(value) is not list and type(value) is not tuple:
        _fail(f"{where} must be an exact list/tuple")
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        ticker = _canonical_ticker(raw, where=where)
        if ticker in seen:
            _fail(f"{where} contains duplicate canonical ticker: {ticker}")
        seen.add(ticker)
        out.append(ticker)
    return out


def _finite_score(value: Any, *, where: str) -> float:
    if type(value) is not int and type(value) is not float:
        _fail(f"{where} must be exact int/float in [0,100]")
    score = float(value)
    if not math.isfinite(score) or score < 0.0 or score > 100.0:
        _fail(f"{where} must be finite in [0,100]: {value!r}")
    return score


def _validated_source_ref_paths(value: Any) -> dict[str, str]:
    if type(value) is not dict:
        _fail("source_ref_paths must be an exact dict")
    allowed = set(SOURCE_REF_PATH_KEYS) | set(OPTIONAL_SOURCE_REF_PATH_KEYS)
    if not set(SOURCE_REF_PATH_KEYS) <= set(value) or not set(value) <= allowed:
        _fail(
            "source_ref_paths must contain all required keys and only optional supported keys: "
            f"required={sorted(SOURCE_REF_PATH_KEYS)} optional={sorted(OPTIONAL_SOURCE_REF_PATH_KEYS)}"
        )
    out: dict[str, str] = {}
    for path_key in (*SOURCE_REF_PATH_KEYS, *OPTIONAL_SOURCE_REF_PATH_KEYS):
        if path_key not in value:
            continue
        raw = value[path_key]
        if type(raw) is not str or not raw.strip():
            _fail(f"source_ref_paths.{path_key} must be a non-empty repo-relative path")
        if "://" in raw or "\\" in raw or ":" in raw:
            _fail(f"source_ref_paths.{path_key} must be repo-relative, not a URL or absolute path")
        parts = PurePosixPath(raw).parts
        if PurePosixPath(raw).is_absolute() or any(part in ("", ".", "..") for part in parts):
            _fail(f"source_ref_paths.{path_key} must be a clean repo-relative path")
        out[_SOURCE_REF_ROLE_BY_PATH_KEY[path_key]] = raw
    return out


def _source_refs_for_family(source_refs_by_role: dict[str, str], family: str) -> list[dict[str, str]]:
    roles = list(_FAMILY_SOURCE_REF_ROLES[family])
    if family in {"selection_inputs", "per_ticker_analysis"} and "yfinance_grade_actions" in source_refs_by_role:
        roles = [
            "yfinance_grade_actions" if role == "analyst_grade_actions" else role
            for role in roles
        ]
    if family in {"selection_inputs", "per_ticker_analysis"} and "overextension_projection" in source_refs_by_role:
        roles.append("overextension_projection")
    return [
        {"role": role, "path": source_refs_by_role[role]}
        for role in roles
    ]


def _observed_at_to_naive_et(value: Any, *, where: str) -> datetime:
    if type(value) is not str or "T" not in value:
        _fail(f"{where} must be an ISO date-time string")
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise DataContextAssemblyError(f"{where} must be parseable ISO date-time") from exc
    if dt.tzinfo is not None:
        try:
            dt = dt.astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None)
        except (OverflowError, ValueError, OSError) as exc:
            raise DataContextAssemblyError(f"{where} must be timezone-normalizable ISO date-time") from exc
    return dt


def _collect_observed_at_instants(value: Any, *, where: str) -> list[datetime]:
    out: list[datetime] = []

    def walk(node: Any, path: str) -> None:
        if type(node) is dict:
            for key, child in node.items():
                child_path = f"{path}.{key}" if path else str(key)
                if key == "observed_at":
                    out.append(_observed_at_to_naive_et(child, where=child_path))
                else:
                    walk(child, child_path)
        elif type(node) is list:
            for idx, child in enumerate(node):
                walk(child, f"{path}[{idx}]")

    walk(value, where)
    return out


def _max_observed_at(family: str, instants: list[datetime]) -> str:
    if not instants:
        _fail(f"run_provenance.families.{family} has no source observed_at clock")
    return max(instants).isoformat(timespec="seconds")


def _provenance_family(
    *,
    as_of: str,
    observed_at: str,
    price_basis_date: str | None,
    row_count: int,
    source_refs: list[dict[str, str]],
) -> dict[str, Any]:
    price_bearing = price_basis_date is not None
    return {
        "as_of": as_of,
        "observed_at": observed_at,
        "price_basis_date": price_basis_date,
        "session": "RTH" if price_bearing else None,
        "adjustment": "split_div_adjusted" if price_bearing else None,
        "row_count": row_count,
        "source_refs": source_refs,
    }


def _validated_candidate_artifact(
    candidate_artifact: dict[str, Any],
    *,
    expected_decision_date: str,
    eligibility_governance: dict[str, Any],
) -> dict[str, Any]:
    try:
        return validate_candidate_artifact(
            candidate_artifact,
            expected_decision_date=expected_decision_date,
            governance=eligibility_governance,
        )
    except Exception as exc:
        raise DataContextAssemblyError(f"candidate_artifact rejected: {exc}") from exc


def _universe_rows_from_artifact(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, raw in enumerate(artifact["rows"]):
        if type(raw) is not dict:
            _fail(f"candidate_artifact.rows[{idx}] must be an exact dict")
        ticker = _canonical_ticker(raw.get("ticker"), where=f"candidate_artifact.rows[{idx}].ticker")
        if ticker in seen:
            _fail(f"candidate_artifact.rows contains duplicate canonical ticker: {ticker}")
        seen.add(ticker)
        try:
            row = {key: raw[key] for key in UNIVERSE_ROW_KEYS}
        except KeyError as exc:
            _fail(f"candidate_artifact.rows[{idx}] missing Batch4 universe key: {exc.args[0]}")
        row["ticker"] = ticker
        rows.append(row)
    return rows


def _canonical_signal_map(value: Any, *, expected_candidates: list[str]) -> dict[str, dict[str, Any]]:
    if type(value) is not dict:
        _fail("candidate_pass2_signals must be an exact dict")
    out: dict[str, dict[str, Any]] = {}
    for raw_ticker, raw_signals in value.items():
        ticker = _canonical_ticker(raw_ticker, where="candidate_pass2_signals key")
        if ticker in out:
            _fail(f"candidate_pass2_signals contains duplicate canonical ticker: {ticker}")
        if type(raw_signals) is not dict:
            _fail(f"candidate_pass2_signals[{ticker}] must be an exact dict")
        out[ticker] = dict(raw_signals)
    expected = set(expected_candidates)
    actual = set(out)
    if actual != expected:
        _fail(
            "candidate_pass2_signals must exactly cover final candidates "
            f"(missing {sorted(expected - actual)} / stale {sorted(actual - expected)})"
        )
    return out


def _canonical_source_disposition_map(value: Any, *, source_name: str, disposition: str) -> dict[str, dict[str, Any]]:
    if type(value) is not dict:
        _fail(f"pass2_sources.{source_name}.{disposition} must be an exact dict")
    out: dict[str, dict[str, Any]] = {}
    for raw_ticker, raw_row in value.items():
        ticker = _canonical_ticker(raw_ticker, where=f"pass2_sources.{source_name}.{disposition} key")
        if ticker in out:
            _fail(f"pass2_sources.{source_name}.{disposition} contains duplicate canonical ticker: {ticker}")
        if type(raw_row) is not dict:
            _fail(f"pass2_sources.{source_name}.{disposition}[{ticker}] must be an exact dict")
        out[ticker] = dict(raw_row)
    return out


def _source_disposition_maps(source: Any, *, source_name: str) -> dict[str, dict[str, dict[str, Any]]]:
    if type(source) is not dict:
        _fail(f"pass2_sources.{source_name} must be an exact dict")
    maps = {
        disposition: _canonical_source_disposition_map(
            source.get(disposition),
            source_name=source_name,
            disposition=disposition,
        )
        for disposition in PASS2_SOURCE_DISPOSITIONS
    }
    owner: dict[str, str] = {}
    for disposition, rows in maps.items():
        for ticker in rows:
            if ticker in owner:
                _fail(
                    f"pass2_sources.{source_name} has ambiguous disposition for {ticker}: "
                    f"{owner[ticker]} and {disposition}"
                )
            owner[ticker] = disposition
    return maps


def _pass2_signals_from_offering_audit(source: Any, *, expected_candidates: list[str]) -> dict[str, dict[str, Any]]:
    maps = _source_disposition_maps(source, source_name="offering_audit")
    expected = set(expected_candidates)
    actual = set().union(*(set(rows) for rows in maps.values()))
    if actual != expected:
        _fail(
            "pass2_sources.offering_audit must exactly disposition final candidates "
            f"(missing {sorted(expected - actual)} / stale {sorted(actual - expected)})"
        )

    out: dict[str, dict[str, Any]] = {}
    for ticker in expected_candidates:
        if ticker in maps["signals"]:
            active_offering = maps["signals"][ticker].get("active_offering")
            if type(active_offering) is not dict:
                _fail(f"pass2_sources.offering_audit.signals[{ticker}].active_offering must be an exact dict")
            out[ticker] = {"active_offering": dict(active_offering)}
        elif ticker in maps["checked"]:
            checked = maps["checked"][ticker].get("active_offering")
            if type(checked) is not dict:
                _fail(f"pass2_sources.offering_audit.checked[{ticker}].active_offering must be an exact dict")
            out[ticker] = {}
        elif ticker in maps["excluded"]:
            if "active_offering" not in maps["excluded"][ticker]:
                _fail(f"pass2_sources.offering_audit.excluded[{ticker}] missing active_offering disposition")
            out[ticker] = {"critical_data_missing": True}
        else:  # pragma: no cover - covered by the exact-disposition guard above.
            _fail(f"pass2_sources.offering_audit missing disposition for {ticker}")
    return out


def _pass2_signals_from_sources(pass2_sources: Any, *, expected_candidates: list[str]) -> dict[str, dict[str, Any]]:
    if type(pass2_sources) is not dict:
        _fail("pass2_sources must be an exact dict")
    if set(pass2_sources) != PASS2_SOURCE_KEYS:
        _fail(f"pass2_sources must contain exactly {sorted(PASS2_SOURCE_KEYS)}")
    return _pass2_signals_from_offering_audit(
        pass2_sources["offering_audit"],
        expected_candidates=expected_candidates,
    )


def _canonical_holdings(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if type(value) is not list:
        _fail("holdings must be a list when provided")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, raw in enumerate(value):
        if type(raw) is not dict:
            _fail(f"holdings[{idx}] must be an exact dict")
        ticker = _canonical_ticker(raw.get("ticker"), where=f"holdings[{idx}].ticker")
        if ticker in seen:
            _fail(f"holdings contains duplicate canonical ticker: {ticker}")
        seen.add(ticker)
        signals = raw.get("signals")
        if type(signals) is not dict:
            _fail(f"holdings[{idx}].signals must be an exact dict")
        out.append({"ticker": ticker, "signals": dict(signals)})
    return out


def _canonical_recall_feed(value: Any, universe_eligibility: dict[str, bool]) -> list[str] | None:
    if value is None:
        return None
    if type(value) is not list:
        _fail("catalyst_recall_feed must be None or a list")
    out: list[str] = []
    seen: set[str] = set()
    for raw_ticker in value:
        ticker = _canonical_ticker(raw_ticker, where="catalyst_recall_feed item")
        if ticker in seen:
            _fail(f"catalyst_recall_feed contains duplicate canonical ticker: {ticker}")
        seen.add(ticker)
        out.append(ticker)
    try:
        inject_catalyst_recall([], recall_feed=out, universe_eligibility=universe_eligibility)
    except Exception as exc:
        raise DataContextAssemblyError(f"catalyst_recall_feed rejected: {exc}") from exc
    return out


def _validate_score_composition(
    score_composition: Any,
    *,
    expected_pass2_clean: list[str],
) -> dict[str, Any]:
    if type(score_composition) is not dict:
        _fail("score_composition must be an exact dict")
    if set(score_composition) != set(OUTPUT_KEYS):
        _fail(f"score_composition keys drifted from Cut 6-d output contract: {sorted(score_composition)}")

    targets = _canonical_ticker_list(score_composition["target_tickers"], where="score_composition.target_tickers")
    expected_set = set(expected_pass2_clean)
    target_set = set(targets)
    if target_set != expected_set:
        _fail(
            "score_composition.target_tickers must exactly cover Pass2-clean candidates "
            f"(missing {sorted(expected_set - target_set)} / stale {sorted(target_set - expected_set)})"
        )
    expected = set(targets)
    for family in ("analysis_by_ticker", "coverage_by_ticker"):
        value = score_composition[family]
        if type(value) is not dict:
            _fail(f"score_composition.{family} must be an exact dict")
        keys = set()
        for raw_ticker in value:
            ticker = _canonical_ticker(raw_ticker, where=f"score_composition.{family} key")
            if ticker in keys:
                _fail(f"score_composition.{family} contains duplicate canonical ticker: {ticker}")
            keys.add(ticker)
        if keys != expected:
            _fail(f"score_composition.{family} must exactly cover target_tickers")

    return _validated_selection_inputs(score_composition["selection_inputs"], expected_tickers=expected)


def _validated_selection_inputs(value: Any, *, expected_tickers: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != SELECTION_INPUT_KEYS:
        _fail("score_composition.selection_inputs must use the Batch4 closed-world shape")
    state = value["theme_opportunity_state"]
    if type(state) is not str:
        _fail("selection_inputs.theme_opportunity_state must be exact str")
    per = value["per_ticker"]
    if type(per) is not dict:
        _fail("selection_inputs.per_ticker must be an exact dict")
    out_per: dict[str, dict[str, float]] = {}
    for raw_ticker, raw_row in per.items():
        ticker = _canonical_ticker(raw_ticker, where="selection_inputs.per_ticker key")
        if ticker in out_per:
            _fail(f"selection_inputs.per_ticker contains duplicate canonical ticker: {ticker}")
        if type(raw_row) is not dict or set(raw_row) != SELECTION_ROW_KEYS:
            _fail(f"selection_inputs.per_ticker[{ticker}] must contain core_score/theme_momentum_score only")
        out_per[ticker] = {
            "core_score": _finite_score(raw_row["core_score"], where=f"{ticker}.core_score"),
            "theme_momentum_score": _finite_score(
                raw_row["theme_momentum_score"],
                where=f"{ticker}.theme_momentum_score",
            ),
        }
    if set(out_per) != expected_tickers:
        _fail("selection_inputs.per_ticker must exactly cover score target_tickers")
    return {"theme_opportunity_state": state, "per_ticker": out_per}


def _prepare_context_inputs(
    *,
    candidate_artifact: dict[str, Any],
    expected_decision_date: str,
    eligibility_governance: dict[str, Any],
    candidate_pass2_signals: dict[str, Any] | None,
    pass2_sources: dict[str, Any] | None,
    catalyst_recall_feed: list[str] | None,
) -> dict[str, Any]:
    artifact = _validated_candidate_artifact(
        candidate_artifact,
        expected_decision_date=expected_decision_date,
        eligibility_governance=eligibility_governance,
    )
    universe_rows = _universe_rows_from_artifact(artifact)
    eligible_tickers = eligible_tickers_from_rows(artifact["rows"])
    universe_eligibility = {row["ticker"]: row["eligible"] for row in artifact["rows"]}
    recall_feed = _canonical_recall_feed(catalyst_recall_feed, universe_eligibility)
    try:
        recalled = inject_catalyst_recall(
            eligible_tickers,
            recall_feed=recall_feed,
            universe_eligibility=universe_eligibility,
        )
    except Exception as exc:
        raise DataContextAssemblyError(f"catalyst recall candidate set rejected: {exc}") from exc
    candidates = recalled["candidates"]
    if (candidate_pass2_signals is None) == (pass2_sources is None):
        _fail("provide exactly one of candidate_pass2_signals or pass2_sources")
    if pass2_sources is not None:
        candidate_pass2_signals = _pass2_signals_from_sources(
            pass2_sources,
            expected_candidates=candidates,
        )
    pass2_signals = _canonical_signal_map(candidate_pass2_signals, expected_candidates=candidates)
    pass2_clean = [
        ticker
        for ticker in candidates
        if pass2_safety_admit(pass2_signals[ticker], row_context="candidate")["admit_to_topn"]
    ]
    return {
        "universe_rows": universe_rows,
        "recall_feed": recall_feed,
        "pass2_signals": pass2_signals,
        "pass2_clean": pass2_clean,
    }


def _assembled_context_from_prepared(
    prepared: dict[str, Any],
    *,
    selection_inputs: dict[str, Any],
    holdings: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    return {
        "universe": prepared["universe_rows"],
        "catalyst_recall_feed": prepared["recall_feed"],
        "holdings": _canonical_holdings(holdings),
        "candidate_pass2_signals": prepared["pass2_signals"],
        "selection_inputs": selection_inputs,
    }


def assemble_data_context(
    *,
    candidate_artifact: dict[str, Any],
    expected_decision_date: str,
    eligibility_governance: dict[str, Any],
    score_composition: dict[str, Any],
    candidate_pass2_signals: dict[str, Any] | None,
    pass2_sources: dict[str, Any] | None = None,
    holdings: list[dict[str, Any]] | None = None,
    catalyst_recall_feed: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble Batch5 provider-fed local artifacts into the Batch4 data_context seam.

    Pure/offline: no provider calls, no state writes, no DataHub. The provider candidate artifact
    remains the priced/lineage source of record; Batch4 universe rows intentionally strip provider
    clocks and lineage so run_provenance can bind family-level clocks without dirty row overrides.
    `pass2_sources.offering_audit` consumes the resolved SEC offering-audit output shape; callers that hold raw
    injected SEC submissions can use `assemble_data_context_from_sec_offering_submissions` to build that source
    without hand-authoring a Pass2 map. The offering producer currently emits real recent+active offerings with
    materiality=None, so they are admitted as strong_downgrade rather than entry_hard_veto until a later materiality
    parser lands; excluded offering-audit rows become critical_data_missing and fail closed.
    """
    prepared = _prepare_context_inputs(
        candidate_artifact=candidate_artifact,
        expected_decision_date=expected_decision_date,
        eligibility_governance=eligibility_governance,
        candidate_pass2_signals=candidate_pass2_signals,
        pass2_sources=pass2_sources,
        catalyst_recall_feed=catalyst_recall_feed,
    )
    selection_inputs = _validate_score_composition(
        score_composition,
        expected_pass2_clean=prepared["pass2_clean"],
    )
    return _assembled_context_from_prepared(prepared, selection_inputs=selection_inputs, holdings=holdings)


def _scope_overextension(
    overextension_by_ticker: dict[str, Any] | None, pass2_clean: list[str]
) -> dict[str, Any] | None:
    """Scope an injected §4.3 overextension producer map (keyed by ALL eligible) down to the Pass2-clean targets
    EXACTLY, so `compose_score_inputs` receives exact-coverage (its `_validated_theme_strip_targets` requires it).
    None → None (no strip; backward-compatible default). A non-dict map, or a Pass2-clean target missing from the
    map, fails closed — pass2_clean ⊆ eligible ⊆ the producer map keys, so a miss is a wiring bug, not a data gap.
    The per-ticker record's state/effect closed-world shape is validated downstream by the shared §4.3 validator."""
    if overextension_by_ticker is None:
        return None
    if type(overextension_by_ticker) is not dict:
        _fail("overextension_by_ticker must be a dict or None")
    scoped: dict[str, Any] = {}
    for ticker in pass2_clean:
        if ticker not in overextension_by_ticker:
            _fail(f"overextension_by_ticker is missing Pass2-clean target {ticker!r} (must cover every eligible)")
        scoped[ticker] = overextension_by_ticker[ticker]
    return scoped


_OVEREXTENSION_PROJECTION_KEYS = {
    "schema_name", "schema_version", "generated_at", "decision_clock", "source_contract",
    "candidate_binding", "overextension_by_ticker", "disposition_counts", "scored_count", "target_count",
}


def validate_overextension_projection(
    projection: Any,
    *,
    candidate_artifact: dict[str, Any],
    expected_decision_date: str,
    eligibility_governance: dict[str, Any],
) -> dict[str, Any]:
    """Bind a local §4.3 projection to the current candidate clock/universe before any score consumer sees it."""
    if type(projection) is not dict or set(projection) != _OVEREXTENSION_PROJECTION_KEYS:
        _fail("overextension projection must use the exact source-bound envelope")
    if (projection["schema_name"] != "us_short_full_universe_overextension_projection"
            or projection["schema_version"] != "1.0.0"):
        _fail("overextension projection schema identity drifted")
    _observed_at_to_naive_et(projection["generated_at"], where="overextension_projection.generated_at")

    artifact = _validated_candidate_artifact(
        candidate_artifact,
        expected_decision_date=expected_decision_date,
        eligibility_governance=eligibility_governance,
    )
    eligible = eligible_tickers_from_rows(artifact["rows"])
    price_basis_compact = artifact["price_basis_date"]
    try:
        price_basis_iso = datetime.strptime(price_basis_compact, "%Y%m%d").date().isoformat()
    except (TypeError, ValueError) as exc:
        raise DataContextAssemblyError("candidate price_basis_date is not canonical YYYYMMDD") from exc

    expected_clock = {
        "expected_decision_date": expected_decision_date,
        "candidate_price_basis_date": price_basis_compact,
        "price_basis_date": price_basis_iso,
        "source_as_of": price_basis_iso,
    }
    if type(projection["decision_clock"]) is not dict or projection["decision_clock"] != expected_clock:
        _fail("overextension projection decision/price clock mismatches the current candidate artifact")
    source_contract = projection["source_contract"]
    expected_source_contract = {
        "session": OVEREXTENSION_SOURCE_SESSION,
        "adjustment_mode": OVEREXTENSION_SOURCE_ADJUSTMENT_MODE,
    }
    if type(source_contract) is not dict or source_contract != expected_source_contract:
        _fail("overextension projection source_contract drifted from the reviewed grouped-window source")
    binding = projection["candidate_binding"]
    expected_binding = {
        "eligible_count": len(eligible),
        "eligible_tickers_sha256": eligible_tickers_sha256(eligible),
    }
    if (type(binding) is not dict or set(binding) != set(expected_binding)
            or type(binding.get("eligible_count")) is not int or binding["eligible_count"] < 0
            or type(binding.get("eligible_tickers_sha256")) is not str
            or binding != expected_binding):
        _fail("overextension projection candidate-universe binding mismatches the current artifact")

    rows = projection["overextension_by_ticker"]
    if type(rows) is not dict:
        _fail("overextension_by_ticker must be an exact dict")
    canonical_rows: dict[str, dict[str, Any]] = {}
    expected_pit = {
        "as_of": price_basis_iso,
        "session": source_contract["session"],
        "adjustment_mode": source_contract["adjustment_mode"],
    }
    for raw_ticker, record in rows.items():
        ticker = _canonical_ticker(raw_ticker, where="overextension_by_ticker key")
        if ticker in canonical_rows:
            _fail(f"overextension_by_ticker contains duplicate canonical ticker: {ticker}")
        try:
            validate_overextension_result(
                record,
                require_producer_metadata=True,
                expected_pit=expected_pit,
            )
        except ValueError as exc:
            raise DataContextAssemblyError(f"overextension_by_ticker[{ticker}] rejected: {exc}") from exc
        canonical_rows[ticker] = record
    if set(canonical_rows) != set(eligible):
        _fail("overextension projection must exactly cover the current Pass1-eligible universe")

    counts = {"scored": 0, "insufficient_data": 0}
    for record in canonical_rows.values():
        counts[record["disposition"]] += 1
    disposition_counts = projection["disposition_counts"]
    counts_are_exact_ints = (type(disposition_counts) is dict and set(disposition_counts) == set(counts)
                             and all(type(disposition_counts[key]) is int and disposition_counts[key] >= 0
                                     for key in counts))
    if (type(projection["target_count"]) is not int or projection["target_count"] != len(eligible)
            or type(projection["scored_count"]) is not int or projection["scored_count"] != counts["scored"]
            or not counts_are_exact_ints or disposition_counts != counts):
        _fail("overextension projection counts do not reconcile to the bound tier rows")
    return {
        "overextension_by_ticker": canonical_rows,
        "generated_at": projection["generated_at"],
    }


def assemble_data_context_with_analyst_grade_risk(
    *,
    candidate_artifact: dict[str, Any],
    expected_decision_date: str,
    eligibility_governance: dict[str, Any],
    momentum_projection: dict[str, Any],
    theme_projection: dict[str, Any],
    catalyst_projection: dict[str, Any],
    analyst_grade_actions: dict[str, Any],
    theme_opportunity_state: str,
    candidate_pass2_signals: dict[str, Any] | None,
    pass2_sources: dict[str, Any] | None = None,
    holdings: list[dict[str, Any]] | None = None,
    catalyst_recall_feed: list[str] | None = None,
    overextension_by_ticker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble data_context while deriving score risk from resolved FMP analyst-grade facts.

    Pure/offline: this consumes an already-resolved analyst-grade fact layer; it does not fetch FMP grades,
    persist raw data, or create a second scoring formula. The final selection surface still comes from
    `compose_score_inputs`.
    """
    prepared = _prepare_context_inputs(
        candidate_artifact=candidate_artifact,
        expected_decision_date=expected_decision_date,
        eligibility_governance=eligibility_governance,
        candidate_pass2_signals=candidate_pass2_signals,
        pass2_sources=pass2_sources,
        catalyst_recall_feed=catalyst_recall_feed,
    )
    try:
        analyst_projection = project_analyst_grade_risk_downgrade(
            target_tickers=prepared["pass2_clean"],
            analyst_grade_actions=analyst_grade_actions,
        )
        score_composition = compose_score_inputs(
            target_tickers=prepared["pass2_clean"],
            momentum_projection=momentum_projection,
            theme_projection=theme_projection,
            catalyst_projection=catalyst_projection,
            risk_downgrade_by_ticker=analyst_projection["risk_downgrade_by_ticker"],
            theme_opportunity_state=theme_opportunity_state,
            overextension_by_ticker=_scope_overextension(overextension_by_ticker, prepared["pass2_clean"]),
        )
    except (AnalystGradeRiskError, ScoreSeamError) as exc:
        raise DataContextAssemblyError(f"analyst-grade score composition rejected: {exc}") from exc
    selection_inputs = _validate_score_composition(
        score_composition,
        expected_pass2_clean=prepared["pass2_clean"],
    )
    return _assembled_context_from_prepared(prepared, selection_inputs=selection_inputs, holdings=holdings)


def assemble_data_context_with_massive_news_catalyst(
    *,
    candidate_artifact: dict[str, Any],
    expected_decision_date: str,
    eligibility_governance: dict[str, Any],
    momentum_projection: dict[str, Any],
    theme_projection: dict[str, Any],
    massive_news_events: dict[str, Any],
    catalyst_governance: dict[str, Any],
    theme_opportunity_state: str,
    candidate_pass2_signals: dict[str, Any] | None,
    pass2_sources: dict[str, Any] | None = None,
    holdings: list[dict[str, Any]] | None = None,
    catalyst_recall_feed: list[str] | None = None,
    overextension_by_ticker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble data_context while deriving the catalyst block from resolved Massive news facts.

    Pure/offline: this consumes an already-resolved Massive news fact layer; it does not fetch news,
    call an LLM, persist raw data, or create a second scoring formula. The final selection surface
    still comes from `compose_score_inputs`.
    """
    prepared = _prepare_context_inputs(
        candidate_artifact=candidate_artifact,
        expected_decision_date=expected_decision_date,
        eligibility_governance=eligibility_governance,
        candidate_pass2_signals=candidate_pass2_signals,
        pass2_sources=pass2_sources,
        catalyst_recall_feed=catalyst_recall_feed,
    )
    try:
        catalyst_projection = project_massive_news_catalyst(
            news_events=massive_news_events,
            governance=catalyst_governance,
            as_of=expected_decision_date,
            target_tickers=prepared["pass2_clean"],
        )
        score_composition = compose_score_inputs(
            target_tickers=prepared["pass2_clean"],
            momentum_projection=momentum_projection,
            theme_projection=theme_projection,
            catalyst_projection=catalyst_projection,
            risk_downgrade_by_ticker={ticker: risk_downgrade() for ticker in prepared["pass2_clean"]},
            theme_opportunity_state=theme_opportunity_state,
            overextension_by_ticker=_scope_overextension(overextension_by_ticker, prepared["pass2_clean"]),
        )
    except (MassiveNewsCatalystSeamError, ScoreSeamError, CatalystGovernanceError) as exc:
        raise DataContextAssemblyError(f"Massive-news score composition rejected: {exc}") from exc
    selection_inputs = _validate_score_composition(
        score_composition,
        expected_pass2_clean=prepared["pass2_clean"],
    )
    return _assembled_context_from_prepared(prepared, selection_inputs=selection_inputs, holdings=holdings)


def _assemble_resolved_pass2_source_context(
    *,
    candidate_artifact: dict[str, Any],
    expected_decision_date: str,
    eligibility_governance: dict[str, Any],
    momentum_projection: dict[str, Any],
    theme_projection: dict[str, Any],
    offering_audit_source: dict[str, Any],
    analyst_grade_actions: dict[str, Any],
    massive_news_events: dict[str, Any],
    catalyst_governance: dict[str, Any],
    theme_opportunity_state: str,
    holdings: list[dict[str, Any]] | None = None,
    catalyst_recall_feed: list[str] | None = None,
    overextension_by_ticker: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    prepared = _prepare_context_inputs(
        candidate_artifact=candidate_artifact,
        expected_decision_date=expected_decision_date,
        eligibility_governance=eligibility_governance,
        candidate_pass2_signals=None,
        pass2_sources={"offering_audit": offering_audit_source},
        catalyst_recall_feed=catalyst_recall_feed,
    )
    scoped_overextension = _scope_overextension(overextension_by_ticker, prepared["pass2_clean"])
    try:
        analyst_projection = project_analyst_grade_risk_downgrade(
            target_tickers=prepared["pass2_clean"],
            analyst_grade_actions=analyst_grade_actions,
        )
        catalyst_projection = project_massive_news_catalyst(
            news_events=massive_news_events,
            governance=catalyst_governance,
            as_of=expected_decision_date,
            target_tickers=prepared["pass2_clean"],
        )
        score_composition = compose_score_inputs(
            target_tickers=prepared["pass2_clean"],
            momentum_projection=momentum_projection,
            theme_projection=theme_projection,
            catalyst_projection=catalyst_projection,
            risk_downgrade_by_ticker=analyst_projection["risk_downgrade_by_ticker"],
            theme_opportunity_state=theme_opportunity_state,
            overextension_by_ticker=scoped_overextension,
        )
    except (AnalystGradeRiskError, MassiveNewsCatalystSeamError, ScoreSeamError, CatalystGovernanceError) as exc:
        raise DataContextAssemblyError(f"resolved Pass2 source score composition rejected: {exc}") from exc
    selection_inputs = _validate_score_composition(
        score_composition,
        expected_pass2_clean=prepared["pass2_clean"],
    )
    return (
        _assembled_context_from_prepared(prepared, selection_inputs=selection_inputs, holdings=holdings),
        score_composition,
        scoped_overextension,
    )


def assemble_data_context_from_resolved_pass2_sources(
    *,
    candidate_artifact: dict[str, Any],
    expected_decision_date: str,
    eligibility_governance: dict[str, Any],
    momentum_projection: dict[str, Any],
    theme_projection: dict[str, Any],
    offering_audit_source: dict[str, Any],
    analyst_grade_actions: dict[str, Any],
    massive_news_events: dict[str, Any],
    catalyst_governance: dict[str, Any],
    theme_opportunity_state: str,
    holdings: list[dict[str, Any]] | None = None,
    catalyst_recall_feed: list[str] | None = None,
    overextension_by_ticker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble data_context from already-resolved Pass2/provider fact layers.

    Pure/offline: no provider calls, raw persistence, DataHub, or second scoring formula. Offering audit
    owns Pass2 safety signals; analyst grades and Massive news are projected into the canonical score composer.
    """
    data_context, _, _ = _assemble_resolved_pass2_source_context(
        candidate_artifact=candidate_artifact,
        expected_decision_date=expected_decision_date,
        eligibility_governance=eligibility_governance,
        momentum_projection=momentum_projection,
        theme_projection=theme_projection,
        offering_audit_source=offering_audit_source,
        analyst_grade_actions=analyst_grade_actions,
        massive_news_events=massive_news_events,
        catalyst_governance=catalyst_governance,
        theme_opportunity_state=theme_opportunity_state,
        holdings=holdings,
        catalyst_recall_feed=catalyst_recall_feed,
        overextension_by_ticker=overextension_by_ticker,
    )
    return data_context


def _official_per_ticker_analysis(
    score_composition: dict[str, Any], scoped_overextension: dict[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for ticker, row in score_composition["analysis_by_ticker"].items():
        if type(row) is not dict:
            _fail(f"score_composition.analysis_by_ticker[{ticker}] must be an exact dict")
        if set(row) & {"ticker", "row_source", "signals", "overextension"}:
            _fail(f"score_composition.analysis_by_ticker[{ticker}] must not pre-populate official row identity")
        official_row = {
            "ticker": ticker,
            "row_source": "top15_candidate",
            "signals": {},
            **row,
        }
        if scoped_overextension is not None:
            # §4.3 (cut 2c): the per-ticker overextension tier rides onto the analysis row so _analyze_one applies a
            # `warning` force-pullback. A `chasing_extreme` tier is inert HERE (empty execution_flags) — its effect
            # was the SELECTION theme-strip already applied in compose (Slice B). This same validated record makes
            # _analyze_one remove only the theme contribution when it recomputes the selection score.
            official_row["overextension"] = scoped_overextension[ticker]
        out[ticker] = official_row
    return out


def assemble_official_context_components_from_resolved_pass2_sources(
    *,
    candidate_artifact: dict[str, Any],
    expected_decision_date: str,
    eligibility_governance: dict[str, Any],
    momentum_projection: dict[str, Any],
    theme_projection: dict[str, Any],
    offering_audit_source: dict[str, Any],
    analyst_grade_actions: dict[str, Any],
    massive_news_events: dict[str, Any],
    catalyst_governance: dict[str, Any],
    theme_opportunity_state: str,
    source_ref_paths: dict[str, Any],
    holdings: list[dict[str, Any]] | None = None,
    catalyst_recall_feed: list[str] | None = None,
    overextension_by_ticker: dict[str, Any] | None = None,
    overextension_generated_at: str | None = None,
) -> dict[str, Any]:
    """Assemble official Batch4 data/provenance components from resolved local source artifacts.

    This is still pure/offline and intentionally does not fabricate batch4 price bars or provider data. It adds
    the official per-ticker score rows and a source-ref-bound run_provenance manifest beside the existing
    data_context seam; the later batch5->batch4 E2E cut supplies the remaining analysis inputs.
    """
    source_refs_by_role = _validated_source_ref_paths(source_ref_paths)
    has_overextension_ref = "overextension_projection" in source_refs_by_role
    if has_overextension_ref and overextension_by_ticker is None:
        _fail("overextension projection source ref requires a consumed map")
    if has_overextension_ref != (overextension_generated_at is not None):
        _fail("source-bound overextension projection must carry its validated generated_at")
    data_context, score_composition, scoped_overextension = _assemble_resolved_pass2_source_context(
        candidate_artifact=candidate_artifact,
        expected_decision_date=expected_decision_date,
        eligibility_governance=eligibility_governance,
        momentum_projection=momentum_projection,
        theme_projection=theme_projection,
        offering_audit_source=offering_audit_source,
        analyst_grade_actions=analyst_grade_actions,
        massive_news_events=massive_news_events,
        catalyst_governance=catalyst_governance,
        theme_opportunity_state=theme_opportunity_state,
        holdings=holdings,
        catalyst_recall_feed=catalyst_recall_feed,
        overextension_by_ticker=overextension_by_ticker,
    )
    per_ticker_analysis = _official_per_ticker_analysis(score_composition, scoped_overextension)
    if set(per_ticker_analysis) != set(data_context["selection_inputs"]["per_ticker"]):
        _fail("per_ticker_analysis must exactly cover selection_inputs.per_ticker")

    candidate_observed = _observed_at_to_naive_et(candidate_artifact.get("generated_at"), where="candidate_artifact.generated_at")
    offering_observed = _collect_observed_at_instants(offering_audit_source, where="offering_audit_source")
    analyst_observed = _collect_observed_at_instants(analyst_grade_actions, where="analyst_grade_actions")
    news_observed = _collect_observed_at_instants(massive_news_events, where="massive_news_events")
    overextension_observed = (
        [_observed_at_to_naive_et(overextension_generated_at, where="overextension_projection.generated_at")]
        if overextension_generated_at is not None else []
    )
    score_family_observed = [candidate_observed, *offering_observed, *analyst_observed, *news_observed,
                             *overextension_observed]
    price_basis_date = candidate_artifact["price_basis_date"]
    families = {
        "universe": _provenance_family(
            as_of=expected_decision_date,
            observed_at=candidate_observed.isoformat(timespec="seconds"),
            price_basis_date=price_basis_date,
            row_count=len(data_context["universe"]),
            source_refs=_source_refs_for_family(source_refs_by_role, "universe"),
        ),
        "per_ticker_analysis": _provenance_family(
            as_of=expected_decision_date,
            observed_at=_max_observed_at("per_ticker_analysis", score_family_observed),
            price_basis_date=price_basis_date,
            row_count=len(per_ticker_analysis),
            source_refs=_source_refs_for_family(source_refs_by_role, "per_ticker_analysis"),
        ),
        "candidate_pass2_signals": _provenance_family(
            as_of=expected_decision_date,
            observed_at=_max_observed_at("candidate_pass2_signals", offering_observed),
            price_basis_date=None,
            row_count=len(data_context["candidate_pass2_signals"]),
            source_refs=_source_refs_for_family(source_refs_by_role, "candidate_pass2_signals"),
        ),
        "selection_inputs": _provenance_family(
            as_of=expected_decision_date,
            observed_at=_max_observed_at("selection_inputs", score_family_observed),
            price_basis_date=None,
            row_count=len(data_context["selection_inputs"]["per_ticker"]),
            source_refs=_source_refs_for_family(source_refs_by_role, "selection_inputs"),
        ),
    }
    return {
        "data_context": data_context,
        "per_ticker_analysis": per_ticker_analysis,
        "run_provenance": {
            "as_of": expected_decision_date,
            "price_basis_date": price_basis_date,
            "families": families,
        },
    }


def assemble_data_context_from_sec_offering_submissions(
    *,
    candidate_artifact: dict[str, Any],
    expected_decision_date: str,
    eligibility_governance: dict[str, Any],
    score_composition: dict[str, Any],
    offering_as_of: str,
    offering_observed_at: str,
    offering_submissions_by_ticker: Any,
    holdings: list[dict[str, Any]] | None = None,
    catalyst_recall_feed: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble Batch4 data_context directly from injected SEC company-submissions payloads.

    Pure/offline: no SEC fetch, no raw persistence, no DataHub. This is a convenience wiring seam for callers that
    already hold reviewed SEC submissions payloads and should not hand-author a Pass2 signal map.
    """
    try:
        offering_source = build_offering_audit_from_sec_submissions(
            as_of=offering_as_of,
            observed_at=offering_observed_at,
            submissions_by_ticker=offering_submissions_by_ticker,
        )
    except OfferingAuditError as exc:
        raise DataContextAssemblyError(f"offering SEC submissions rejected: {exc}") from exc
    return assemble_data_context(
        candidate_artifact=candidate_artifact,
        expected_decision_date=expected_decision_date,
        eligibility_governance=eligibility_governance,
        score_composition=score_composition,
        candidate_pass2_signals=None,
        pass2_sources={"offering_audit": offering_source},
        holdings=holdings,
        catalyst_recall_feed=catalyst_recall_feed,
    )
