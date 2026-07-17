from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path  # noqa: E402
from engine.us_short_provider_health import ProviderHealthError, classify_provider_health  # noqa: E402
from engine.us_short_eligibility_gate import canonical_us_ticker, load_eligibility_governance  # noqa: E402
from engine.us_short_market_calendar import sessions_for_window, validate_market_calendar  # noqa: E402
from engine.us_short_run_origin import (  # noqa: E402
    RunOriginError,
    is_capstone_research_live_capability,
    require_research_live_provider_health,
    require_research_live_receipt_binding,
)
from engine.us_short_weekend_analysis import analyze_rows  # noqa: E402
from engine.us_short_weekend_basket import resolve_build_capacity  # noqa: E402
from engine.us_short_weekend_cost_floor import apply_probe_cost_floor  # noqa: E402
from engine.us_short_weekend_decision import decide_actions  # noqa: E402
from engine.us_short_weekend_orchestrator import _build_analysis_rows  # noqa: E402
from engine.us_short_weekend_pipeline import run_selection  # noqa: E402
from engine.us_short_weekend_sizing import _BUILD as _BUILD_ACTION, size_rows  # noqa: E402
from runners import us_short_batch5_data_context_source_packet as source_packet_runner  # noqa: E402
from runners import us_short_weekend_batch4 as batch4_runner  # noqa: E402


STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
DEFAULT_CALENDAR_PATH = ROOT / "presets" / "us_short_market_calendar_2026_2027.json"
DEFAULT_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
FULL_CANDIDATE_LIVE_PROJECTION_BINDING = source_packet_runner.FULL_CANDIDATE_LIVE_PROJECTION_BINDING
PROJECTION_INPUTS_BINDING = source_packet_runner.PROJECTION_INPUTS_BINDING
_PROVIDER_RECEIPT_RUN_MODES = frozenset({"research_live", "mixed_source"})
_LEGACY_CONTEXT_COMPONENT_KEYS = frozenset({"data_context", "per_ticker_analysis", "run_provenance"})
_A1_CONTEXT_COMPONENT_KEYS = _LEGACY_CONTEXT_COMPONENT_KEYS | frozenset(
    {"score_composition", "overextension_by_ticker"}
)

_TEMPLATE_KEYS = frozenset(
    {
        "market_axis_regimes",
        "prior_regime",
        "prior_upgrade_count",
        "sizing_per_ticker",
        "basket_context",
        "cost_inputs",
        "report_context",
    }
)


class Batch5ToBatch4E2EError(ValueError):
    """The local Batch5 source packet cannot be bridged into a Batch4 weekend run safely."""


_PROBE_COST_KEYS = ("commission_round_trip", "slippage_dollars", "spread_dollars")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise Batch5ToBatch4E2EError(f"{label} could not be read as UTF-8 JSON") from exc


def _repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _resolve_existing_path(path: Path | str, *, label: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise Batch5ToBatch4E2EError(f"{label} must be an existing file")
    return resolved


def _default_components_path(source_packet_path: Path) -> Path:
    return source_packet_path.with_name(source_packet_path.stem + "_context_components.json")


def _state_json_path(path: Path | str, *, label: str) -> Path:
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise Batch5ToBatch4E2EError(f"{label} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise Batch5ToBatch4E2EError(f"{label} must be a .json file")
    return resolved


def _private_path(path: Path | str, *, label: str) -> Path:
    resolved = Path(path).resolve()
    try:
        reject_nonprivate_output_path(resolved)
    except PrivatePathError as exc:
        raise Batch5ToBatch4E2EError(f"{label} must be a provably private path") from exc
    return resolved


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    _private_path(path, label="context_packet_path")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _best_effort_source_data_context_path(source_packet_path: Path) -> Path | None:
    try:
        packet = _read_json(source_packet_path, "source packet")
        value = packet.get("paths", {}).get("output_data_context_path")
        if type(value) is not str:
            return None
        candidate = (ROOT / Path(value)).resolve()
        candidate.relative_to(STATE_US_SHORT_DIR.resolve())
        if candidate.suffix != ".json":
            return None
        return candidate
    except Exception:
        return None


def _tmp_sidecar(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".tmp")


def _cleanup_created_paths(paths: list[Path], roots: list[Path], existed_before: dict[Path, bool]) -> None:
    for path in paths:
        resolved = path.resolve()
        if not existed_before.get(resolved, True):
            try:
                resolved.unlink(missing_ok=True)
            except IsADirectoryError:
                pass
        tmp = _tmp_sidecar(resolved)
        if not existed_before.get(tmp, True):
            tmp.unlink(missing_ok=True)
    for root in roots:
        resolved = root.resolve()
        if existed_before.get(resolved, True) or not resolved.exists():
            continue
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink(missing_ok=True)


def _remember_path(path: Path | None, *, cleanup_paths: list[Path], existed_before: dict[Path, bool]) -> None:
    if path is None:
        return
    resolved = path.resolve()
    if resolved in existed_before:
        return
    existed_before[resolved] = resolved.exists()
    tmp = _tmp_sidecar(resolved)
    existed_before[tmp] = tmp.exists()
    cleanup_paths.append(resolved)


def _remember_root(path: Path, *, cleanup_roots: list[Path], existed_before: dict[Path, bool]) -> None:
    resolved = path.resolve()
    if resolved in existed_before:
        return
    existed_before[resolved] = resolved.exists()
    cleanup_roots.append(resolved)


def _load_template(path: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Batch5ToBatch4E2EError("batch4 template could not be read") from exc
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise Batch5ToBatch4E2EError("batch4 template changed after receipt binding")
    try:
        template = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise Batch5ToBatch4E2EError("batch4 template could not be read as UTF-8 JSON") from exc
    if not isinstance(template, dict):
        raise Batch5ToBatch4E2EError("batch4 template must be a JSON object")
    missing = _TEMPLATE_KEYS - set(template)
    if missing:
        raise Batch5ToBatch4E2EError(f"batch4 template missing required key(s): {sorted(missing)}")
    return {key: copy.deepcopy(template[key]) for key in _TEMPLATE_KEYS}


def _load_provider_health(path: Path) -> dict[str, str]:
    health = _read_json(path, "provider health")
    try:
        classify_provider_health(health)
    except ProviderHealthError as exc:
        raise Batch5ToBatch4E2EError("provider health must be an authorized-source status map") from exc
    return health


def _patched_report_context(
    template_report_context: dict[str, Any], *, run_provenance: dict[str, Any], now_et: datetime,
    forward_policy_comparison_reminder: str | None = None,
):
    report_context = copy.deepcopy(template_report_context)
    if not isinstance(report_context, dict) or not isinstance(report_context.get("price_clock"), dict):
        raise Batch5ToBatch4E2EError("batch4 template report_context.price_clock must be an object")
    report_context["price_clock"] = {
        **report_context["price_clock"],
        "price_data_through": run_provenance["price_basis_date"],
        "news_window_through": now_et.strftime("%Y%m%d"),
        "session_scope": "RTH",
        "decision_date": run_provenance["as_of"],
    }
    if forward_policy_comparison_reminder is not None:
        if not isinstance(forward_policy_comparison_reminder, str) or not forward_policy_comparison_reminder.strip():
            raise Batch5ToBatch4E2EError("forward_policy_comparison_reminder must be a non-blank string or absent")
        report_context["forward_policy_comparison_reminder"] = forward_policy_comparison_reminder.strip()
    return report_context


def _finite_positive(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0.0 else None


def _universe_by_ticker(data_context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in data_context.get("universe") or []:
        if not isinstance(row, dict):
            continue
        ticker = canonical_us_ticker(row.get("ticker"))
        if ticker is None:
            raise Batch5ToBatch4E2EError("data_context universe contains a non-canonical US ticker")
        if ticker in out:
            raise Batch5ToBatch4E2EError("data_context universe contains duplicate canonical tickers")
        out[ticker] = row
    return out


def _analysis_rows_without_synthetic_price_inputs(
    per_ticker_analysis: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Preserve only source-bound price input already present on official components.

    Batch5 universe rows currently provide close/ADV, not the OHLCV/ATR structure required
    by the Batch4 price engine. A close-only bridge must therefore remain non-executable
    instead of fabricating support, resistance, or ATR geometry.
    """
    out: dict[str, dict[str, Any]] = {}
    for key, row in per_ticker_analysis.items():
        ticker = canonical_us_ticker(key)
        if ticker is None or not isinstance(row, dict):
            raise Batch5ToBatch4E2EError("per_ticker_analysis contains a non-canonical ticker or non-object row")
        out[ticker] = copy.deepcopy(row)
    return out


def _short_bucket_dollars(account_state_path: Path, *, required: bool) -> float:
    if not account_state_path.is_file():
        if required:
            raise Batch5ToBatch4E2EError("account_state_path is required to derive dynamic sizing inputs")
        return 1.0
    account = _read_json(account_state_path, "account state")
    bucket = _finite_positive(account.get("us_short_bucket_capital")) if isinstance(account, dict) else None
    if bucket is None:
        raise Batch5ToBatch4E2EError("account_state.us_short_bucket_capital must be a positive finite number")
    return bucket


def _sizing_input_for_ticker(ticker: str, universe_by_ticker: dict[str, dict[str, Any]]) -> dict[str, Any]:
    row = universe_by_ticker.get(ticker) or {}
    price = _finite_positive(row.get("price"))
    adv_usd = _finite_positive(row.get("adv_usd"))
    liquidity_cap = 0
    if price is not None and adv_usd is not None:
        liquidity_cap = max(0, int(math.floor((adv_usd / price) * 0.01)))
    return {"discount_mults": [], "liquidity_cap_shares": liquidity_cap}


def _basket_input_for_ticker() -> dict[str, Any]:
    return {
        "theme": "unclassified",
        "symbol_cooldown_status": "none",
        "theme_probe": {
            "theme_lifecycle_state": None,
            "high_confidence": False,
            "coverage_status": "restricted",
            "no_gap_week": False,
            "entry_in_band": False,
        },
    }


def _cost_inputs_for_promoted_probes(basket_result: dict[str, Any]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in basket_result.get("rows") or []:
        if not isinstance(row, dict) or row.get("final_action") != _BUILD_ACTION or "theme_probe" not in row:
            continue
        ticker = canonical_us_ticker(row.get("ticker"))
        if ticker is None:
            raise Batch5ToBatch4E2EError("promoted probe row has a non-canonical ticker")
        out[ticker] = {key: 0.0 for key in _PROBE_COST_KEYS}
    return out


def _derive_current_action_inputs(
    *,
    components: dict[str, Any],
    template: dict[str, Any],
    account_state_path: Path,
    calendar_path: Path,
    governance_path: Path,
    now_et: datetime,
    market_axis_regimes: dict[str, Any],
    basket_context: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any], dict[str, dict[str, float]]]:
    data_context = components["data_context"]
    universe = _universe_by_ticker(data_context)
    per_ticker_analysis = _analysis_rows_without_synthetic_price_inputs(components["per_ticker_analysis"])
    if not per_ticker_analysis:
        basket_empty = copy.deepcopy(basket_context)
        basket_empty["per_ticker"] = {}
        return per_ticker_analysis, {}, basket_empty, {}
    calendar = validate_market_calendar(_read_json(calendar_path, "market calendar"))
    selection = run_selection(
        now_et,
        sessions_for_window(now_et.strftime("%Y%m%d"), calendar=calendar),
        data_context,
        eligibility_governance=load_eligibility_governance(governance_path),
    )
    if selection["out_of_window"]:
        basket_empty = copy.deepcopy(basket_context)
        basket_empty["per_ticker"] = {}
        return per_ticker_analysis, {}, basket_empty, {}
    rows = _build_analysis_rows(selection, per_ticker_analysis)

    analysis = analyze_rows(
        rows,
        market_axis_regimes=market_axis_regimes,
        prior_regime=template["prior_regime"],
        prior_upgrade_count=template["prior_upgrade_count"],
    )
    decided = decide_actions(analysis)
    build_tickers = {
        row["ticker"] for row in decided["rows"]
        if isinstance(row, dict) and row.get("final_action") == _BUILD_ACTION
    }
    sizing_per_ticker = {
        ticker: _sizing_input_for_ticker(ticker, universe)
        for ticker in sorted(build_tickers)
    }
    if not sizing_per_ticker:
        basket_empty = copy.deepcopy(basket_context)
        basket_empty["per_ticker"] = {}
        return per_ticker_analysis, {}, basket_empty, {}

    sized = size_rows(
        decided,
        sizing_context={
            "short_bucket_dollars": _short_bucket_dollars(account_state_path, required=True),
            "per_ticker": sizing_per_ticker,
        },
    )
    sized_build_tickers = {
        row["ticker"] for row in sized["rows"]
        if isinstance(row, dict) and row.get("final_action") == _BUILD_ACTION
    }
    dynamic_basket = copy.deepcopy(basket_context)
    dynamic_basket["per_ticker"] = {
        ticker: _basket_input_for_ticker()
        for ticker in sorted(sized_build_tickers)
    }
    basket = resolve_build_capacity(sized, basket_context=dynamic_basket)
    cost_inputs = _cost_inputs_for_promoted_probes(basket)
    apply_probe_cost_floor(basket, cost_inputs=cost_inputs)
    return per_ticker_analysis, sizing_per_ticker, dynamic_basket, cost_inputs


def _assemble_batch4_packet(
    *,
    components: dict[str, Any],
    template: dict[str, Any],
    provider_health: dict[str, str],
    account_state_path: Path,
    calendar_path: Path,
    governance_path: Path,
    private_root: Path,
    official_output_root: Path | None,
    now_et: datetime,
    vix_regime: str | None = None,
    forward_policy_comparison_reminder: str | None = None,
) -> dict[str, Any]:
    data_context = components["data_context"]
    run_provenance = components["run_provenance"]
    theme_state = data_context["selection_inputs"]["theme_opportunity_state"]
    basket_context = copy.deepcopy(template["basket_context"])
    if not isinstance(basket_context, dict):
        raise Batch5ToBatch4E2EError("batch4 template basket_context must be an object")
    basket_context["theme_opportunity_state"] = theme_state
    market_axis_regimes = copy.deepcopy(template["market_axis_regimes"])
    if not isinstance(market_axis_regimes, dict):
        raise Batch5ToBatch4E2EError("batch4 template market_axis_regimes must be an object")
    if vix_regime is not None:
        market_axis_regimes["vix"] = vix_regime
    per_ticker_analysis, sizing_per_ticker, basket_context, cost_inputs = _derive_current_action_inputs(
        components=components,
        template=template,
        account_state_path=account_state_path,
        calendar_path=calendar_path,
        governance_path=governance_path,
        now_et=now_et,
        market_axis_regimes=market_axis_regimes,
        basket_context=basket_context,
    )
    return {
        "data_context": data_context,
        "per_ticker_analysis": per_ticker_analysis,
        "run_provenance": run_provenance,
        "provider_health": provider_health,
        "market_axis_regimes": market_axis_regimes,
        "prior_regime": template["prior_regime"],
        "prior_upgrade_count": template["prior_upgrade_count"],
        "sizing_per_ticker": sizing_per_ticker,
        "basket_context": basket_context,
        "cost_inputs": cost_inputs,
        "report_context": _patched_report_context(
            template["report_context"],
            run_provenance=run_provenance,
            now_et=now_et,
            forward_policy_comparison_reminder=forward_policy_comparison_reminder,
        ),
        "eligibility_governance_path": str(governance_path.resolve()),
        "calendar_path": str(calendar_path.resolve()),
        "account_state_path": str(account_state_path.resolve()),
        "lifecycle_register_path": str((private_root / "lifecycle" / "lifecycle_register.json").resolve()),
        "lifecycle_readiness_out_path": None,
        "runs_private_root": str(((official_output_root or private_root) / "runs_private").resolve()),
        "weekly_private_root": str(((official_output_root or private_root) / "weekly_private").resolve()),
    }


def _safe_batch4_run(packet_path: Path, *, now_et: datetime, run_mode: str, research_live_capability,
                     bootstrap_lifecycle: bool, dry_run: bool):
    try:
        return batch4_runner.run_packet(
            packet_path,
            now_et=now_et,
            run_mode=run_mode,
            _research_live_capability=research_live_capability,
            bootstrap_lifecycle=bootstrap_lifecycle,
            dry_run=dry_run,
        )
    except batch4_runner.Batch4RunnerError:
        raise
    except Exception as exc:
        raise Batch5ToBatch4E2EError(f"batch4 runner failed with {type(exc).__name__}") from exc


def _safe_source_packet_run(
    source_packet: Path,
    *,
    generated_at: str | None,
    context_components_path: Path,
    projection_binding_expectations: source_packet_runner.ProjectionBindingExpectations,
) -> dict[str, Any]:
    try:
        return source_packet_runner.run_packet(
            source_packet,
            generated_at=generated_at,
            context_components_output_path=_repo_rel(context_components_path),
            projection_binding_expectations=projection_binding_expectations,
        )
    except source_packet_runner.SourcePacketError as exc:
        raise Batch5ToBatch4E2EError("source packet runner failed") from exc
    except Exception as exc:
        raise Batch5ToBatch4E2EError(f"source packet runner failed with {type(exc).__name__}") from exc


def run_e2e(
    *,
    source_packet_path: Path | str,
    batch4_template_path: Path | str,
    account_state_path: Path | str,
    provider_health_path: Path | str,
    private_root: Path | str,
    official_output_root: Path | str | None = None,
    now_et: datetime,
    context_components_path: Path | str | None = None,
    context_packet_path: Path | str | None = None,
    calendar_path: Path | str = DEFAULT_CALENDAR_PATH,
    governance_path: Path | str = DEFAULT_GOVERNANCE_PATH,
    run_mode: str = "offline_test",
    _research_live_capability=None,
    bootstrap_lifecycle: bool = False,
    dry_run: bool = False,
    generated_at: str | None = None,
    vix_regime: str | None = None,
    forward_policy_comparison_reminder: str | None = None,
    projection_binding_expectations: source_packet_runner.ProjectionBindingExpectations = PROJECTION_INPUTS_BINDING,
) -> dict[str, Any]:
    if not isinstance(now_et, datetime) or now_et.tzinfo is not None:
        raise Batch5ToBatch4E2EError("now_et must be a naive ET datetime")
    # This bridge always consumes a caller-provided Batch4 action template.  A fully provider-derived research_live
    # label is therefore impossible here; a future no-template bridge must be a separately implemented path.
    if run_mode == "research_live":
        raise Batch5ToBatch4E2EError(
            "batch5-to-batch4 bridge consumes caller action inputs and must use mixed_source, never research_live"
        )
    # Provider-backed report modes are CAPSTONE-INTERNAL: minted ONLY when the caller holds the
    # run-specific capstone receipt (bound to source path/digest + provider evidence, NOT a caller-settable boolean).
    # A generic batch5->batch4 caller feeding an arbitrary/fixture
    # source packet cannot obtain it, so the report can never falsely banner "真实 provider 数据". Only the capstone's
    # run_weekly_bridge passes it, after its per-execution SR-PROVIDER-001 authorization + gated live fetch; the CLI
    # cannot select either provider-backed mode.
    if run_mode in _PROVIDER_RECEIPT_RUN_MODES and not is_capstone_research_live_capability(_research_live_capability):
        raise Batch5ToBatch4E2EError(
            "provider-backed run_mode 为 capstone 内部 run_origin（须持 source-bound execution receipt，源自授权的一键 capstone live 取数"
            "执行）；通用 batch5->batch4 调用方不可对任意/fixture source packet 选择——请走 weekly capstone")

    source_packet = _resolve_existing_path(source_packet_path, label="source_packet_path")
    if run_mode in _PROVIDER_RECEIPT_RUN_MODES:
        if not isinstance(generated_at, str) or not generated_at:
            raise Batch5ToBatch4E2EError("provider-backed run_mode requires the receipt-bound generated_at")
        source_digest = hashlib.sha256(source_packet.read_bytes()).hexdigest()
        try:
            source_manifest = source_packet_runner.source_packet_input_manifest(source_packet)
            require_research_live_receipt_binding(
                _research_live_capability,
                generated_at=generated_at,
                source_packet_path=source_packet,
                source_packet_sha256=source_digest,
                source_artifact_manifest=source_manifest,
            )
        except (RunOriginError, source_packet_runner.SourcePacketError, OSError) as exc:
            raise Batch5ToBatch4E2EError(
                "provider-backed receipt does not bind the consumed source packet and source artifacts"
            ) from exc
    template_path = _resolve_existing_path(batch4_template_path, label="batch4_template_path")
    action_input_manifest = ((
        "batch4_action_template", str(template_path), hashlib.sha256(template_path.read_bytes()).hexdigest(),
    ),)
    if run_mode == "mixed_source":
        try:
            require_research_live_receipt_binding(
                _research_live_capability,
                action_input_manifest=action_input_manifest,
            )
        except (RunOriginError, OSError) as exc:
            raise Batch5ToBatch4E2EError(
                "mixed_source receipt does not bind the consumed Batch4 action template"
            ) from exc
    account_path = _private_path(account_state_path, label="account_state_path")
    if not account_path.is_file():
        raise Batch5ToBatch4E2EError("account_state_path must be an existing private file")
    provider_health = _load_provider_health(
        _resolve_existing_path(provider_health_path, label="provider_health_path")
    )
    if run_mode in _PROVIDER_RECEIPT_RUN_MODES:
        try:
            require_research_live_provider_health(_research_live_capability, provider_health)
        except RunOriginError as exc:
            raise Batch5ToBatch4E2EError(
                "provider-backed provider health does not match the receipt-bound provider outcome"
            ) from exc
    private_root_path = _private_path(private_root, label="private_root")
    official_output_root_path = (
        _private_path(official_output_root, label="official_output_root")
        if official_output_root is not None else private_root_path
    )
    calendar = _resolve_existing_path(calendar_path, label="calendar_path")
    governance = _resolve_existing_path(governance_path, label="governance_path")
    components_path = _state_json_path(
        context_components_path or _default_components_path(source_packet),
        label="context_components_path",
    )
    context_path = _private_path(
        context_packet_path or (private_root_path / "batch5_to_batch4_context_packet.json"),
        label="context_packet_path",
    )

    cleanup_paths: list[Path] = []
    cleanup_roots: list[Path] = []
    existed_before: dict[Path, bool] = {}
    _remember_path(
        _best_effort_source_data_context_path(source_packet),
        cleanup_paths=cleanup_paths,
        existed_before=existed_before,
    )
    _remember_path(components_path, cleanup_paths=cleanup_paths, existed_before=existed_before)
    _remember_path(context_path, cleanup_paths=cleanup_paths, existed_before=existed_before)
    for private_output_root in (
        private_root_path / "lifecycle",
        official_output_root_path / "runs_private",
        official_output_root_path / "weekly_private",
    ):
        _remember_root(private_output_root, cleanup_roots=cleanup_roots, existed_before=existed_before)

    try:
        source_summary = _safe_source_packet_run(
            source_packet,
            generated_at=generated_at,
            context_components_path=components_path,
            projection_binding_expectations=projection_binding_expectations,
        )
        if run_mode in _PROVIDER_RECEIPT_RUN_MODES:
            try:
                require_research_live_receipt_binding(
                    _research_live_capability,
                    generated_at=generated_at,
                    source_packet_path=source_packet,
                    source_packet_sha256=hashlib.sha256(source_packet.read_bytes()).hexdigest(),
                    source_artifact_manifest=source_packet_runner.source_packet_input_manifest(source_packet),
                )
            except (RunOriginError, source_packet_runner.SourcePacketError, OSError) as exc:
                raise Batch5ToBatch4E2EError(
                    "provider-backed source packet or source artifacts changed during consumption"
                ) from exc
        components = _read_json(components_path, "context components")
        if not isinstance(components, dict) or frozenset(components) not in {
            _LEGACY_CONTEXT_COMPONENT_KEYS, _A1_CONTEXT_COMPONENT_KEYS,
        }:
            raise Batch5ToBatch4E2EError(
                "context components must use the legacy or A1 source-bound closed-world shape"
            )
        if run_mode in _PROVIDER_RECEIPT_RUN_MODES:
            try:
                require_research_live_receipt_binding(
                    _research_live_capability,
                    decision_date=components["run_provenance"].get("as_of"),
                    generated_at=generated_at,
                )
            except (AttributeError, RunOriginError) as exc:
                raise Batch5ToBatch4E2EError(
                    "provider-backed receipt does not bind the assembled run identity"
                ) from exc

        packet = _assemble_batch4_packet(
            components=components,
            template=_load_template(template_path, expected_sha256=action_input_manifest[0][2]),
            provider_health=provider_health,
            account_state_path=account_path,
            calendar_path=calendar,
            governance_path=governance,
            private_root=private_root_path,
            official_output_root=official_output_root_path,
            now_et=now_et,
            vix_regime=vix_regime,
            forward_policy_comparison_reminder=forward_policy_comparison_reminder,
        )
        _write_private_json(context_path, packet)
        batch4_summary = _safe_batch4_run(
            context_path,
            now_et=now_et,
            run_mode=run_mode,
            research_live_capability=_research_live_capability,
            bootstrap_lifecycle=bootstrap_lifecycle,
            dry_run=dry_run,
        )
    except Exception:
        _cleanup_created_paths(cleanup_paths, cleanup_roots, existed_before)
        raise

    return {
        "schema_name": "us_short_batch5_to_batch4_weekend_e2e_summary",
        "schema_version": "1.0.0",
        "generated_at": generated_at or iso_now(),
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_to_batch4_weekend_e2e",
            "status": "batch5_source_packet_to_batch4_outputs_completed",
            "execution_mode": "live_provider_fetch" if run_mode == "mixed_source" else "offline_local_assembly",
            "report_mode": run_mode,
            "operational_use": "not_authorized",
            "network_access_required": False,
            "provider_calls_performed": False,
            "raw_payloads_read": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "source_packet": {
            "packet_ref": source_summary["packet_ref"],
            "context_components_path": _repo_rel(components_path),
            "selection_input_count": source_summary["data_context"]["selection_input_count"],
            "context_components_written": source_summary["scope"]["context_components_written"],
        },
        "context_packet": {
            "path": str(context_path),
            "template_path": str(template_path),
        },
        "batch4_run": batch4_summary,
    }


def _parse_now_et(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be ET wall clock YYYY-MM-DDTHH:MM:SS") from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run local US-short Batch5 source-packet components through the supported Batch4 weekend runner. "
            "Offline only: no provider fetch, DataHub, production storage, ship-gate claim, broker, or A-share path."
        )
    )
    parser.add_argument("--source-packet", required=True, type=Path)
    parser.add_argument("--batch4-template", required=True, type=Path)
    parser.add_argument("--account", required=True, type=Path)
    parser.add_argument("--provider-health", required=True, type=Path)
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--now-et", required=True, type=_parse_now_et)
    parser.add_argument("--context-components-out", type=Path, default=None)
    parser.add_argument("--context-out", type=Path, default=None)
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR_PATH)
    parser.add_argument("--governance", type=Path, default=DEFAULT_GOVERNANCE_PATH)
    # research_live is capstone-INTERNAL (source-bound to the authorized one-click capstone live fetch), NOT
    # operator-selectable here — R-USSHORT-REVIEWQ-CAT1 Required A; a generic bridge caller only gets offline_test/live.
    parser.add_argument("--run-mode", choices=("offline_test", "live"), default="offline_test")
    parser.add_argument("--bootstrap-lifecycle", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--generated-at", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run_e2e(
            source_packet_path=args.source_packet,
            batch4_template_path=args.batch4_template,
            account_state_path=args.account,
            provider_health_path=args.provider_health,
            private_root=args.private_root,
            now_et=args.now_et,
            context_components_path=args.context_components_out,
            context_packet_path=args.context_out,
            calendar_path=args.calendar,
            governance_path=args.governance,
            run_mode=args.run_mode,
            bootstrap_lifecycle=args.bootstrap_lifecycle,
            dry_run=args.dry_run,
            generated_at=args.generated_at,
        )
    except (Batch5ToBatch4E2EError, batch4_runner.Batch4RunnerError) as exc:
        print(f"US-short batch5->batch4 E2E failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
