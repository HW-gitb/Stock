"""Knife4b source-bound soft-boost consumption and local ON/OFF attribution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from engine.us_short_provisional_theme_boost import (
    ProvisionalThemeBoostError,
    _schema_validate as _validate_theme_artifact_schema,
    validate_provisional_theme_artifact_identity,
)
from engine.us_short_schema_formats import FORMAT_CHECKER
from runners.us_short_discovery_publish_policy import (
    DiscoveryPublishPolicyError,
    _serialized_sha256,
    publish_immutable_pair,
    validate_exact_decision_slot,
    write_immutable_json,
)


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state" / "us_short"
STAGE_SCHEMA = ROOT / "schemas" / "us_short_provisional_theme_stage_receipt.schema.json"
CONSUMPTION_SCHEMA = ROOT / "schemas" / "us_short_soft_boost_consumption_receipt.schema.json"
SHADOW_SCHEMA = ROOT / "schemas" / "us_short_soft_boost_shadow_receipt.schema.json"
LEDGER_SCHEMA = ROOT / "schemas" / "us_short_soft_boost_comparison_ledger.schema.json"
EPOCH_SCHEMA = ROOT / "schemas" / "us_short_soft_boost_evidence_epoch.schema.json"
EPOCH_PATH = ROOT / "presets" / "us_short_soft_boost_evidence_epoch_20260727.json"
STATISTICAL_PLAN_SCHEMA = ROOT / "schemas" / "us_short_soft_boost_statistical_plan.schema.json"
STATISTICAL_PLAN_PATH = ROOT / "presets" / "us_short_soft_boost_statistical_plan_20260727.json"
EPOCH_ID = "us_short_soft_boost_k4b_20260727"
_DIGEST_KEYS = (
    "discovery_artifact_sha256",
    "candidate_artifact_sha256",
    "classification_packet_sha256",
)


class SoftBoostConsumptionError(ValueError):
    """The K4b consumer contract itself is malformed."""


def _read_schema(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SoftBoostConsumptionError(f"cannot load schema: {path.name}") from exc
    if type(value) is not dict:
        raise SoftBoostConsumptionError(f"schema is not an object: {path.name}")
    return value


def _validate(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise SoftBoostConsumptionError("jsonschema is required for K4b consumption") from exc
    errors = sorted(
        Draft7Validator(_read_schema(schema_path), format_checker=FORMAT_CHECKER).iter_errors(payload),
        key=lambda error: list(error.path),
    )
    if errors:
        raise SoftBoostConsumptionError(f"{label} schema rejected: {errors[0].message}")


def _read_json_bytes(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if type(value) is not dict:
        raise ValueError("JSON root must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def _read_canonical_json(path: Path) -> tuple[dict[str, Any], str]:
    value, _raw_sha256 = _read_json_bytes(path)
    return value, _serialized_sha256(value)


def _repo_rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise SoftBoostConsumptionError("K4b artifact path must stay under the repository root") from exc


def _artifact(path: Path | None, digest: str | None) -> dict[str, Any]:
    return {
        "path": _repo_rel(path) if path is not None else None,
        "sha256": digest,
    }


def _zero(
    *,
    decision_date: str,
    requested: bool,
    status: str,
    reason_code: str,
    stage_path: Path | None,
    stage_sha: str | None,
    validation_path: Path | None,
    validation_sha: str | None,
) -> dict[str, Any]:
    return {
        "decision_date": decision_date,
        "requested_enabled": requested,
        "effective_enabled": False,
        "status": status,
        "reason_code": reason_code,
        "stage_receipt": _artifact(stage_path, stage_sha),
        "validation_artifact": _artifact(validation_path, validation_sha),
        "validation_payload": None,
        "input_digests": None,
    }


def degrade_soft_boost_consumption(
    *,
    decision_date: str,
    reason_code: str = "K4B_OPTIONAL_LIFECYCLE_REJECTED",
) -> dict[str, Any]:
    """Return the typed zero used when any optional K4b lifecycle step fails."""
    return _zero(
        decision_date=decision_date,
        requested=True,
        status="zero_invalid_evidence",
        reason_code=reason_code,
        stage_path=None,
        stage_sha=None,
        validation_path=None,
        validation_sha=None,
    )


def resolve_soft_boost_consumption(
    *,
    expected_decision_date: str,
    theme_soft_boost_enabled: bool,
    current_stage_result: dict[str, Any],
    stage_receipt_path: Path,
    validation_artifact_path: Path,
    candidate_artifact_path: Path,
    classification_packet_path: Path,
    state_dir: Path = STATE_DIR,
) -> dict[str, Any]:
    """Resolve the optional upstream into either a fully bound ON input or a typed zero.

    Evidence failures are deliberately non-fatal because this is an optional discovery
    channel. A malformed caller contract (notably a non-bool switch) still raises.
    """
    if type(theme_soft_boost_enabled) is not bool:
        raise SoftBoostConsumptionError("theme_soft_boost_enabled must be exact bool")
    if (
        type(expected_decision_date) is not str
        or len(expected_decision_date) != 8
        or not expected_decision_date.isascii()
        or not expected_decision_date.isdigit()
    ):
        raise SoftBoostConsumptionError("expected_decision_date must be ASCII YYYYMMDD")
    if not theme_soft_boost_enabled:
        return _zero(
            decision_date=expected_decision_date, requested=False, status="zero_disabled",
            reason_code="SOFT_BOOST_DISABLED", stage_path=None, stage_sha=None,
            validation_path=None, validation_sha=None,
        )

    stage_sha = validation_sha = None
    try:
        _validate(current_stage_result, STAGE_SCHEMA, label="current K4a stage result")
        if current_stage_result["decision_date"] != expected_decision_date:
            raise ValueError("current stage result decision date mismatch")
        current_status = current_stage_result["status"]
        if current_status not in {"valid_nonempty", "valid_empty"}:
            mapped = {
                "disabled": "zero_disabled",
                "upstream_unavailable": "zero_upstream_unavailable",
                "invalid_evidence": "zero_invalid_evidence",
            }[current_status]
            return _zero(
                decision_date=expected_decision_date,
                requested=True,
                status=mapped,
                reason_code=current_stage_result["reason_code"] or {
                    "disabled": "SOFT_DISCOVERY_DISABLED",
                    "upstream_unavailable": "UPSTREAM_UNAVAILABLE",
                    "invalid_evidence": "INVALID_EVIDENCE",
                }[current_status],
                stage_path=None,
                stage_sha=None,
                validation_path=None,
                validation_sha=None,
            )
        expected_stage_path = Path(state_dir) / (
            f"us_short_provisional_theme_stage_receipt_{expected_decision_date}.json"
        )
        expected_validation_path = Path(state_dir) / (
            f"us_short_provisional_theme_validation_{expected_decision_date}.json"
        )
        validate_exact_decision_slot(
            Path(stage_receipt_path), expected_stage_path, root=ROOT, state_dir=Path(state_dir)
        )
        validate_exact_decision_slot(
            Path(validation_artifact_path),
            expected_validation_path,
            root=ROOT,
            state_dir=Path(state_dir),
        )
        stage, stage_sha = _read_json_bytes(Path(stage_receipt_path))
        _validate(stage, STAGE_SCHEMA, label="K4a stage receipt")
        if stage["decision_date"] != expected_decision_date:
            raise ValueError("stage receipt decision date mismatch")
        if stage != current_stage_result:
            raise ValueError("canonical stage receipt is not this run's stage result")
        stage_status = stage["status"]

        expected_validation_rel = _repo_rel(Path(validation_artifact_path))
        if stage["artifacts"]["validation"]["path"] != expected_validation_rel:
            raise ValueError("stage receipt validation path mismatch")
        validation, validation_sha = _read_json_bytes(Path(validation_artifact_path))
        if stage["artifacts"]["validation"]["sha256"] != validation_sha:
            raise ValueError("stage receipt validation digest mismatch")
        _validate_theme_artifact_schema(validation)
        input_digests = {
            key: validation["input_artifacts"][key]
            for key in _DIGEST_KEYS
        }
        ingest_sha = stage["artifacts"]["ingest"]["sha256"]
        actual_candidate_sha = hashlib.sha256(Path(candidate_artifact_path).read_bytes()).hexdigest()
        actual_classification_sha = hashlib.sha256(Path(classification_packet_path).read_bytes()).hexdigest()
        expected_digests = {
            "discovery_artifact_sha256": ingest_sha,
            "candidate_artifact_sha256": actual_candidate_sha,
            "classification_packet_sha256": actual_classification_sha,
        }
        validate_provisional_theme_artifact_identity(
            validation,
            expected_decision_date=expected_decision_date,
            expected_input_digests=expected_digests,
        )
        validated_count = validation["summary"]["validated_theme_count"]
        boostable_count = len({
            member["ticker"]
            for theme in validation["themes"]
            for member in theme["members"]
        })
        if (
            stage["validated_theme_count"] != validated_count
            or stage["boostable_ticker_count"] != boostable_count
        ):
            raise ValueError("stage receipt counts do not match validation artifact")
        if stage_status == "valid_empty":
            if validated_count != 0 or validation["themes"]:
                raise ValueError("valid_empty stage carries non-empty validation evidence")
            return _zero(
                decision_date=expected_decision_date,
                requested=True,
                status="zero_valid_empty",
                reason_code="VALID_EMPTY",
                stage_path=Path(stage_receipt_path),
                stage_sha=stage_sha,
                validation_path=Path(validation_artifact_path),
                validation_sha=validation_sha,
            )
    except (
        OSError, UnicodeDecodeError, ValueError, KeyError, TypeError,
        ProvisionalThemeBoostError, SoftBoostConsumptionError, DiscoveryPublishPolicyError,
    ):
        return _zero(
            decision_date=expected_decision_date, requested=True, status="zero_invalid_evidence",
            reason_code="K4B_EVIDENCE_REJECTED",
            stage_path=Path(stage_receipt_path), stage_sha=stage_sha,
            validation_path=Path(validation_artifact_path), validation_sha=validation_sha,
        )

    return {
        "decision_date": expected_decision_date,
        "requested_enabled": True,
        "effective_enabled": True,
        "status": "consumed_valid_nonempty",
        "reason_code": None,
        "stage_receipt": _artifact(Path(stage_receipt_path), stage_sha),
        "validation_artifact": _artifact(Path(validation_artifact_path), validation_sha),
        "validation_payload": validation,
        "input_digests": input_digests,
    }


def _score_map(value: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for ticker, score in value.items():
        if type(ticker) is not str or type(score) not in (int, float) or isinstance(score, bool):
            raise SoftBoostConsumptionError("selection score map is malformed")
        numeric = float(score)
        if not 0.0 <= numeric <= 100.0:
            raise SoftBoostConsumptionError("selection score is outside [0,100]")
        out[ticker] = numeric
    return out


def build_consumption_receipt(
    *,
    resolved: dict[str, Any],
    generated_at: str,
    on_selection: dict[str, Any],
    off_selection: dict[str, Any],
    boost_records: dict[str, dict[str, Any]],
    on_top15: list[str],
    off_top15: list[str],
) -> dict[str, Any]:
    on = _score_map(on_selection)
    off = _score_map(off_selection)
    if set(on) != set(off) or set(boost_records) != set(on):
        raise SoftBoostConsumptionError("ON/OFF/boost ticker coverage differs")
    rows = []
    for ticker in sorted(on):
        record = boost_records[ticker]
        points = float(record.get("theme_soft_boost", 0.0))
        tier = record.get("evidence_tier")
        if points not in {0.0, 2.0, 5.0} or tier not in {None, "single", "both"}:
            raise SoftBoostConsumptionError("actual boost record violates the fixed tier contract")
        expected_delta = min(100.0, off[ticker] + points) - off[ticker]
        if abs(on[ticker] - off[ticker] - expected_delta) > 1e-9:
            raise SoftBoostConsumptionError("ON/OFF core delta is not explained solely by the soft boost")
        rows.append({
            "ticker": ticker, "evidence_tier": tier, "actual_boost": points,
            "core_score_off": off[ticker], "core_score_on": on[ticker],
        })
    entered = sorted(set(on_top15) - set(off_top15))
    exited = sorted(set(off_top15) - set(on_top15))
    effective = bool(resolved["effective_enabled"])
    payload = {
        "schema_name": "us_short_soft_boost_consumption_receipt",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "decision_date": resolved["decision_date"],
        "requested_enabled": resolved["requested_enabled"],
        "effective_enabled": effective,
        "status": resolved["status"],
        "reason_code": resolved["reason_code"],
        "bindings": {
            "stage_receipt": resolved["stage_receipt"],
            "validation_artifact": resolved["validation_artifact"],
        },
        "per_ticker": rows,
        "top15_impact": {"entered": entered, "exited": exited, "changed": bool(entered or exited)},
        "effects": {
            "core_score_effect_enabled": effective and any(row["actual_boost"] > 0 for row in rows),
            "top15_effect_enabled": effective and bool(entered or exited),
            "operation_advice_effect_claimed": False,
            "dynamic_seats_enabled": False,
            "theme_probe_enabled": False,
            "lifecycle_actions_enabled": False,
            "provider_calls_performed": False,
        },
    }
    _validate(payload, CONSUMPTION_SCHEMA, label="K4b consumption receipt")
    return payload


def write_consumption_receipt(
    payload: dict[str, Any], path: Path, *, state_dir: Path = STATE_DIR,
) -> None:
    _validate(payload, CONSUMPTION_SCHEMA, label="K4b consumption receipt")
    try:
        expected = Path(state_dir) / (
            f"us_short_soft_boost_consumption_receipt_{payload['decision_date']}.json"
        )
        validate_exact_decision_slot(Path(path), expected, root=ROOT, state_dir=Path(state_dir))
        write_immutable_json(
            payload, Path(path), verify=lambda value: _validate(
                value, CONSUMPTION_SCHEMA, label="existing K4b consumption receipt",
            ),
        )
    except DiscoveryPublishPolicyError as exc:
        raise SoftBoostConsumptionError("cannot publish immutable K4b consumption receipt") from exc


def _validated_evidence_contracts() -> tuple[str, str]:
    plan, plan_sha = _read_canonical_json(STATISTICAL_PLAN_PATH)
    _validate(plan, STATISTICAL_PLAN_SCHEMA, label="K4b statistical plan")
    epoch, epoch_sha = _read_canonical_json(EPOCH_PATH)
    _validate(epoch, EPOCH_SCHEMA, label="K4b evidence epoch")
    if epoch["statistical_plan_path"] != _repo_rel(STATISTICAL_PLAN_PATH):
        raise SoftBoostConsumptionError("K4b evidence epoch statistical-plan path mismatch")
    if epoch["statistical_plan_sha256"] != plan_sha:
        raise SoftBoostConsumptionError("K4b evidence epoch statistical-plan digest mismatch")
    return epoch_sha, plan_sha


def build_shadow_receipt(
    *,
    resolved: dict[str, Any],
    generated_at: str,
    on_top15: list[str],
    off_top15: list[str],
    common_input_sha256: str,
) -> dict[str, Any]:
    epoch_sha, plan_sha = _validated_evidence_contracts()
    if (
        type(common_input_sha256) is not str
        or len(common_input_sha256) != 64
        or any(char not in "0123456789abcdef" for char in common_input_sha256)
    ):
        raise SoftBoostConsumptionError("common_input_sha256 must be lowercase SHA-256")
    payload = {
        "schema_name": "us_short_soft_boost_shadow_receipt",
        "schema_version": "1.0.0",
        "epoch_id": EPOCH_ID,
        "evidence_epoch_sha256": epoch_sha,
        "statistical_plan_sha256": plan_sha,
        "generated_at": generated_at,
        "decision_date": resolved["decision_date"],
        "comparison": ["soft_boost_on", "soft_boost_off"],
        "common_input_sha256": common_input_sha256,
        "stage_receipt_sha256": resolved["stage_receipt"]["sha256"],
        "validation_artifact_sha256": resolved["validation_artifact"]["sha256"],
        "on_top15": list(on_top15),
        "off_top15": list(off_top15),
        "divergent": set(on_top15) != set(off_top15),
        "maturity": {
            "captured": True, "matured": False, "eligible": False,
            "non_overlap_h10_block": False,
        },
        "provider_calls_performed": False,
    }
    _validate(payload, SHADOW_SCHEMA, label="K4b shadow receipt")
    return payload


def write_evidence_bundle(
    *,
    consumption_receipt: dict[str, Any],
    consumption_path: Path,
    shadow_receipt: dict[str, Any],
    shadow_path: Path,
    ledger_path: Path,
    state_dir: Path = STATE_DIR,
) -> None:
    """Atomically publish the three K4b evidence siblings or none."""
    _validate(consumption_receipt, CONSUMPTION_SCHEMA, label="K4b consumption receipt")
    _validate(shadow_receipt, SHADOW_SCHEMA, label="K4b shadow receipt")
    decision_date = consumption_receipt["decision_date"]
    state_root = Path(state_dir)
    expected_paths = (
        state_root / f"us_short_soft_boost_consumption_receipt_{decision_date}.json",
        state_root / "shadow_compare_private" / (
            f"us_short_soft_boost_shadow_receipt_{decision_date}.json"
        ),
        state_root / "shadow_compare_private" / (
            f"us_short_soft_boost_comparison_ledger_{decision_date}.json"
        ),
    )
    ledger = {
        "schema_name": "us_short_soft_boost_comparison_ledger",
        "schema_version": "1.0.0",
        "epoch_id": EPOCH_ID,
        "records": [shadow_receipt],
        "captured_week_count": 1,
        "matured_week_count": 0,
        "eligible_divergence_week_count": 0,
        "non_overlap_h10_block_count": 0,
        "record_scope": "single_decision_week_capture",
        "formal_adjudication_performed": False,
        "pending_user_decision_receipt_generated": False,
        "status": "continue_accumulation",
        "automatic_route_change_allowed": False,
    }
    _validate(ledger, LEDGER_SCHEMA, label="K4b weekly comparison ledger")
    try:
        for path, expected in zip((consumption_path, shadow_path, ledger_path), expected_paths):
            validate_exact_decision_slot(Path(path), expected, root=ROOT, state_dir=state_root)
        publish_immutable_pair(
            (
                (consumption_receipt, Path(consumption_path)),
                (shadow_receipt, Path(shadow_path)),
                (ledger, Path(ledger_path)),
            ),
            verifiers=(
                lambda value: _validate(value, CONSUMPTION_SCHEMA, label="existing K4b consumption receipt"),
                lambda value: _validate(value, SHADOW_SCHEMA, label="existing K4b shadow receipt"),
                lambda value: _validate(value, LEDGER_SCHEMA, label="existing K4b weekly comparison ledger"),
            ),
            clock_keys=(),
            recursive=False,
        )
    except DiscoveryPublishPolicyError as exc:
        raise SoftBoostConsumptionError("cannot atomically publish K4b evidence bundle") from exc
