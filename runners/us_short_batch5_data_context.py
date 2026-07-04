from __future__ import annotations

import math
from typing import Any

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
        )
    except (MassiveNewsCatalystSeamError, ScoreSeamError, CatalystGovernanceError) as exc:
        raise DataContextAssemblyError(f"Massive-news score composition rejected: {exc}") from exc
    selection_inputs = _validate_score_composition(
        score_composition,
        expected_pass2_clean=prepared["pass2_clean"],
    )
    return _assembled_context_from_prepared(prepared, selection_inputs=selection_inputs, holdings=holdings)


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
