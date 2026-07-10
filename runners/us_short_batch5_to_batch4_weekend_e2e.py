from __future__ import annotations

import argparse
import copy
import hashlib
import json
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
from engine.us_short_run_origin import (  # noqa: E402
    RunOriginError,
    is_capstone_research_live_capability,
    require_research_live_provider_health,
    require_research_live_receipt_binding,
)
from runners import us_short_batch5_data_context_source_packet as source_packet_runner  # noqa: E402
from runners import us_short_weekend_batch4 as batch4_runner  # noqa: E402


STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
DEFAULT_CALENDAR_PATH = ROOT / "presets" / "us_short_market_calendar_2026_2027.json"
DEFAULT_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"

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


def _load_template(path: Path) -> dict[str, Any]:
    template = _read_json(path, "batch4 template")
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


def _patched_report_context(template_report_context: dict[str, Any], *, run_provenance: dict[str, Any], now_et: datetime):
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
    return report_context


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
) -> dict[str, Any]:
    data_context = components["data_context"]
    run_provenance = components["run_provenance"]
    theme_state = data_context["selection_inputs"]["theme_opportunity_state"]
    basket_context = copy.deepcopy(template["basket_context"])
    if not isinstance(basket_context, dict):
        raise Batch5ToBatch4E2EError("batch4 template basket_context must be an object")
    basket_context["theme_opportunity_state"] = theme_state
    return {
        "data_context": data_context,
        "per_ticker_analysis": components["per_ticker_analysis"],
        "run_provenance": run_provenance,
        "provider_health": provider_health,
        "market_axis_regimes": template["market_axis_regimes"],
        "prior_regime": template["prior_regime"],
        "prior_upgrade_count": template["prior_upgrade_count"],
        "sizing_per_ticker": template["sizing_per_ticker"],
        "basket_context": basket_context,
        "cost_inputs": template["cost_inputs"],
        "report_context": _patched_report_context(
            template["report_context"],
            run_provenance=run_provenance,
            now_et=now_et,
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
) -> dict[str, Any]:
    try:
        return source_packet_runner.run_packet(
            source_packet,
            generated_at=generated_at,
            context_components_output_path=_repo_rel(context_components_path),
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
) -> dict[str, Any]:
    if not isinstance(now_et, datetime) or now_et.tzinfo is not None:
        raise Batch5ToBatch4E2EError("now_et must be a naive ET datetime")
    # R-USSHORT-REVIEWQ-CAT1 Required A — research_live is CAPSTONE-INTERNAL: minted ONLY when the caller holds the
    # run-specific capstone receipt (bound to source path/digest + provider evidence, NOT a caller-settable boolean).
    # A generic batch5->batch4 caller feeding an arbitrary/fixture
    # source packet cannot obtain it, so the report can never falsely banner "真实 provider 数据". Only the capstone's
    # run_weekly_bridge passes it, after its per-execution SR-PROVIDER-001 authorization + gated live fetch; the CLI
    # cannot (research_live is not an argparse choice).
    if run_mode == "research_live" and not is_capstone_research_live_capability(_research_live_capability):
        raise Batch5ToBatch4E2EError(
            "research_live 为 capstone 内部 run_origin（须持 source-bound execution receipt，源自授权的一键 capstone live 取数"
            "执行）；通用 batch5->batch4 调用方不可对任意/fixture source packet 选择——请走 weekly capstone")

    source_packet = _resolve_existing_path(source_packet_path, label="source_packet_path")
    if run_mode == "research_live":
        if not isinstance(generated_at, str) or not generated_at:
            raise Batch5ToBatch4E2EError("research_live requires the receipt-bound generated_at")
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
                "research_live receipt does not bind the consumed source packet and source artifacts"
            ) from exc
    template_path = _resolve_existing_path(batch4_template_path, label="batch4_template_path")
    account_path = _private_path(account_state_path, label="account_state_path")
    if not account_path.is_file():
        raise Batch5ToBatch4E2EError("account_state_path must be an existing private file")
    provider_health = _load_provider_health(
        _resolve_existing_path(provider_health_path, label="provider_health_path")
    )
    if run_mode == "research_live":
        try:
            require_research_live_provider_health(_research_live_capability, provider_health)
        except RunOriginError as exc:
            raise Batch5ToBatch4E2EError(
                "research_live provider health does not match the receipt-bound provider outcome"
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
        )
        if run_mode == "research_live":
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
                    "research_live source packet or source artifacts changed during consumption"
                ) from exc
        components = _read_json(components_path, "context components")
        if not (
            isinstance(components, dict)
            and set(components) == {"data_context", "per_ticker_analysis", "run_provenance"}
        ):
            raise Batch5ToBatch4E2EError(
                "context components must contain data_context/per_ticker_analysis/run_provenance"
            )
        if run_mode == "research_live":
            try:
                require_research_live_receipt_binding(
                    _research_live_capability,
                    decision_date=components["run_provenance"].get("as_of"),
                    generated_at=generated_at,
                )
            except (AttributeError, RunOriginError) as exc:
                raise Batch5ToBatch4E2EError(
                    "research_live receipt does not bind the assembled run identity"
                ) from exc

        packet = _assemble_batch4_packet(
            components=components,
            template=_load_template(template_path),
            provider_health=provider_health,
            account_state_path=account_path,
            calendar_path=calendar,
            governance_path=governance,
            private_root=private_root_path,
            official_output_root=official_output_root_path,
            now_et=now_et,
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
