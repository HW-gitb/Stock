"""Offline Knife4a orchestration for the US-short soft-discovery lane."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from engine.us_short_schema_formats import FORMAT_CHECKER
from runners import us_short_llm_theme_discovery as ingest
from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from runners import us_short_llm_theme_discovery_merge as merge
from runners import us_short_provisional_theme_validate as validate
from runners.us_short_discovery_publish_policy import (
    CLOCK_KEYS_NONE,
    DiscoveryPublishPolicyError,
    frozen_artifact_matches,
    publish_immutable_pair,
    _serialized_sha256,
    validate_exact_decision_slot,
    write_immutable_json,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "us_short_provisional_theme_stage_receipt.schema.json"
CONFORMANCE_GUARDS = (
    "_schema_validate",
    "validate_exact_decision_slot",
    "_relative",
    "_read_json_with_sha",
    "_require_complete_pair",
    "_conflict_receipt_path",
    "_guard_existing_artifact_hashes",
    "_published_sha256",
)


class SoftDiscoveryEvidenceError(ValueError):
    """The optional frozen upstream cannot be consumed without guessing."""

    def __init__(self, message: str, *, reason_code: str = "SOFT_DISCOVERY_EVIDENCE_INVALID"):
        super().__init__(message)
        self.reason_code = reason_code


def default_receipt_path(expected_decision_date: str, *, state_dir: Path | None = None) -> Path:
    ingest.output_filename(expected_decision_date)
    root = Path(state_dir) if state_dir is not None else ingest.STATE_US_SHORT_DIR
    return root / f"us_short_provisional_theme_stage_receipt_{expected_decision_date}.json"


def _conflict_receipt_path(
    expected_decision_date: str, conflict_key: str, *, state_dir: Path,
) -> Path:
    ingest.output_filename(expected_decision_date)
    if len(conflict_key) != 64 or any(char not in "0123456789abcdef" for char in conflict_key):
        raise SoftDiscoveryEvidenceError("soft-discovery conflict key is invalid")
    return Path(state_dir) / (
        f"us_short_provisional_theme_stage_receipt_{expected_decision_date}"
        f"_conflict_{conflict_key}.json"
    )


def rerooted_default_path(
    helper: Callable[[str], Path], expected_decision_date: str, *, state_dir: Path,
) -> Path:
    """Use a Knife1/2/3 helper as filename authority under the capstone's state root."""
    return Path(state_dir) / helper(expected_decision_date).name


def _schema_validate(payload: Any) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise SoftDiscoveryEvidenceError("jsonschema is required; refusing receipt schema bypass") from exc
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SoftDiscoveryEvidenceError("cannot load the soft-discovery receipt schema") from exc
    errors = sorted(
        Draft7Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(payload),
        key=lambda error: list(error.path),
    )
    if errors:
        raise SoftDiscoveryEvidenceError(f"soft-discovery receipt schema rejected: {errors[0].message}")


def _read_json_with_sha(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SoftDiscoveryEvidenceError(
            f"{label} is not readable JSON", reason_code="SOFT_DISCOVERY_JSON_INVALID",
        ) from exc
    if type(payload) is not dict:
        raise SoftDiscoveryEvidenceError(
            f"{label} must be a JSON object", reason_code="SOFT_DISCOVERY_JSON_INVALID",
        )
    return payload, hashlib.sha256(raw).hexdigest()


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise SoftDiscoveryEvidenceError("soft-discovery path must stay under the repository root") from exc


def _relative_or_none(path: Path) -> str | None:
    try:
        return _relative(path)
    except SoftDiscoveryEvidenceError:
        return None


def _artifact(path: Path, sha256: str | None, *, allow_external_unbound: bool = False) -> dict[str, Any]:
    relative = _relative_or_none(path) if allow_external_unbound else _relative(path)
    return {"path": relative, "sha256": sha256}


def _guard_existing_artifact_hashes(paths: dict[str, Path]) -> dict[str, str | None]:
    hashes: dict[str, str | None] = {}
    for key, path in paths.items():
        try:
            raw = path.read_bytes()
        except OSError:
            hashes[key] = None
        else:
            hashes[key] = hashlib.sha256(raw).hexdigest()
    return hashes


def _published_sha256(
    payload: dict[str, Any], path: Path, *, verify: Callable[[Any], None],
) -> str:
    """Digest the bytes that will remain in the immutable slot, including a valid reused representation."""
    if not path.is_file():
        return _serialized_sha256(payload)
    frozen_artifact_matches(
        payload, path, clock_keys=CLOCK_KEYS_NONE, recursive=False, verify=verify,
    )
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise DiscoveryPublishPolicyError("cannot digest the frozen decision-date artifact") from exc


def _require_complete_pair(
    first_exists: bool, second_exists: bool, *, label: str, reason_code: str,
) -> None:
    if first_exists != second_exists:
        raise SoftDiscoveryEvidenceError(f"{label} pair is incomplete", reason_code=reason_code)
    if not first_exists:
        raise SoftDiscoveryEvidenceError(f"{label} pair is unavailable", reason_code=reason_code)


def _paths(ctx) -> dict[str, Path]:
    return {
        "merge": rerooted_default_path(
            merge.default_discovery_path, ctx.decision_date, state_dir=ctx.state_dir,
        ),
        "merge_manifest": rerooted_default_path(
            merge.default_manifest_path, ctx.decision_date, state_dir=ctx.state_dir,
        ),
        "ingest": rerooted_default_path(
            ingest.default_output_path, ctx.decision_date, state_dir=ctx.state_dir,
        ),
        "validation": rerooted_default_path(
            validate.default_output_path, ctx.decision_date, state_dir=ctx.state_dir,
        ),
        "receipt": default_receipt_path(ctx.decision_date, state_dir=ctx.state_dir),
        "web_discovery": rerooted_default_path(
            web.default_discovery_path, ctx.decision_date, state_dir=ctx.state_dir,
        ),
        "web_receipt": rerooted_default_path(
            web.default_receipt_path, ctx.decision_date, state_dir=ctx.state_dir,
        ),
        "x_discovery": rerooted_default_path(
            xfetch.default_discovery_path, ctx.decision_date, state_dir=ctx.state_dir,
        ),
        "x_receipt": rerooted_default_path(
            xfetch.default_receipt_path, ctx.decision_date, state_dir=ctx.state_dir,
        ),
    }


def _receipt(
    ctx,
    paths: dict[str, Path],
    *,
    status: str,
    reason_code: str | None,
    hashes: dict[str, str | None] | None = None,
    validated_theme_count: int = 0,
    boostable_ticker_count: int = 0,
    merge_dropped_theme_count: int = 0,
    validation_drop_count: int = 0,
    error_type: str | None = None,
    generated_at: str | None = None,
    upstream_pair_anchored: bool = False,
    document_content_anchored: bool = False,
    immutable_conflict_hashes: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    hashes = hashes or {}
    payload = {
        "schema_name": "us_short_provisional_theme_stage_receipt",
        "schema_version": "1.0.0",
        "generated_at": generated_at or ctx.generated_at,
        "decision_date": ctx.decision_date,
        "status": status,
        "reason_code": reason_code,
        "artifacts": {
            key: _artifact(
                paths[key], hashes.get(key),
                allow_external_unbound=status not in {"valid_nonempty", "valid_empty"},
            )
            for key in ("merge", "merge_manifest", "ingest", "validation")
        },
        "evidence_anchor": {
            "upstream_pair_anchored": upstream_pair_anchored,
            "document_content_anchored": document_content_anchored,
            "upstream_artifacts": {
                key: _artifact(
                    paths[key], hashes.get(key),
                    allow_external_unbound=status not in {"valid_nonempty", "valid_empty"},
                )
                for key in ("web_discovery", "web_receipt", "x_discovery", "x_receipt")
            },
        },
        "immutable_conflict": None,
        "validated_theme_count": validated_theme_count,
        "boostable_ticker_count": boostable_ticker_count,
        "drop_summary": {
            "merge_dropped_theme_count": merge_dropped_theme_count,
            "validation_drop_count": validation_drop_count,
        },
        "error_summary": (
            {"code": reason_code, "error_type": error_type}
            if reason_code is not None and error_type is not None
            else None
        ),
        "effects": {
            "network_access_performed": False,
            "provider_calls_performed": False,
            "scoring_eligible": False,
            "top15_effect_enabled": False,
            "operation_advice_effect_enabled": False,
            "dynamic_seats_enabled": False,
            "theme_probe_enabled": False,
            "lifecycle_actions_enabled": False,
        },
    }
    if immutable_conflict_hashes is not None:
        frozen = [
            _artifact(paths[key], sha)
            for key, sha in immutable_conflict_hashes.items()
            if key in paths and sha is not None
        ]
        payload["immutable_conflict"] = {
            "canonical_receipt": (
                _artifact(paths["receipt"], immutable_conflict_hashes["receipt"])
                if immutable_conflict_hashes.get("receipt") is not None
                else None
            ),
            "frozen_artifacts": frozen,
        }
    _schema_validate(payload)
    return payload


def _publish_receipt(payload: dict[str, Any], path: Path, *, state_dir: Path) -> dict[str, Any]:
    expected = default_receipt_path(payload["decision_date"], state_dir=state_dir)
    output = validate_exact_decision_slot(path, expected, root=ROOT, state_dir=state_dir)
    write_immutable_json(payload, output, verify=_schema_validate)
    saved, _sha = _read_json_with_sha(output, label="soft-discovery receipt")
    _schema_validate(saved)
    return saved


def _immutable_conflict_receipt(
    ctx, paths: dict[str, Path], _attempted_hashes: dict[str, str | None], *,
    upstream_pair_anchored: bool,
    document_content_anchored: bool,
) -> dict[str, Any]:
    hashes = _guard_existing_artifact_hashes(paths)
    payload = _receipt(
        ctx,
        paths,
        status="invalid_evidence",
        reason_code="SOFT_DISCOVERY_IMMUTABLE_CONFLICT",
        hashes=hashes,
        error_type="DiscoveryPublishPolicyError",
        upstream_pair_anchored=upstream_pair_anchored,
        document_content_anchored=document_content_anchored,
        immutable_conflict_hashes=hashes,
    )
    conflict_key = _serialized_sha256({
        "decision_date": ctx.decision_date,
        "reason_code": payload["reason_code"],
        "hashes": {key: hashes.get(key) for key in sorted(paths)},
    })
    path = _conflict_receipt_path(
        ctx.decision_date, conflict_key, state_dir=ctx.state_dir,
    )
    expected = _conflict_receipt_path(
        ctx.decision_date, conflict_key, state_dir=ctx.state_dir,
    )
    output = validate_exact_decision_slot(
        path, expected, root=ROOT, state_dir=ctx.state_dir,
    )
    write_immutable_json(payload, output, verify=_schema_validate)
    saved, _sha = _read_json_with_sha(output, label="soft-discovery conflict receipt")
    _schema_validate(saved)
    return saved


def _publish_failure_receipt(
    ctx, paths: dict[str, Path], payload: dict[str, Any],
    *, hashes: dict[str, str | None], upstream_pair_anchored: bool,
    document_content_anchored: bool,
) -> dict[str, Any]:
    if _relative_or_none(paths["receipt"]) is None:
        return payload
    try:
        return _publish_receipt(payload, paths["receipt"], state_dir=ctx.state_dir)
    except DiscoveryPublishPolicyError:
        return _immutable_conflict_receipt(
            ctx,
            paths,
            hashes,
            upstream_pair_anchored=upstream_pair_anchored,
            document_content_anchored=document_content_anchored,
        )


def degrade_capstone_boundary_failure(ctx, exc: Exception) -> dict[str, Any]:
    """Return typed zero-effect evidence when the optional stage fails at the capstone boundary."""
    paths = _paths(ctx)
    hashes = _guard_existing_artifact_hashes(paths)
    payload = _receipt(
        ctx,
        paths,
        status="invalid_evidence",
        reason_code="SOFT_DISCOVERY_STAGE_EXCEPTION",
        hashes=hashes,
        error_type=type(exc).__name__,
        upstream_pair_anchored=False,
        document_content_anchored=False,
    )
    try:
        return _publish_failure_receipt(
            ctx,
            paths,
            payload,
            hashes=hashes,
            upstream_pair_anchored=False,
            document_content_anchored=False,
        )
    except Exception:
        # A broken/external state root must not turn this optional channel into a
        # mandatory-capstone failure. The in-memory payload is already schema checked.
        return payload


def run_offline_stage(ctx) -> dict[str, Any]:
    """Consume an existing Knife3 pair, then atomically publish Knife1, Knife2, and the stage receipt."""
    paths = _paths(ctx)
    if getattr(ctx, "soft_discovery_enabled", False) is not True:
        return _receipt(ctx, paths, status="disabled", reason_code="SOFT_DISCOVERY_DISABLED")

    merge_exists = paths["merge"].is_file()
    manifest_exists = paths["merge_manifest"].is_file()
    if not merge_exists and not manifest_exists:
        payload = _receipt(
            ctx,
            paths,
            status="upstream_unavailable",
            reason_code="MERGE_PAIR_UNAVAILABLE",
            error_type="UpstreamUnavailable",
        )
        return _publish_failure_receipt(
            ctx,
            paths,
            payload,
            hashes={},
            upstream_pair_anchored=False,
            document_content_anchored=False,
        )

    hashes: dict[str, str | None] = {}
    upstream_pair_anchored = False
    document_content_anchored = False
    try:
        _require_complete_pair(
            merge_exists, manifest_exists,
            label="Knife3 merge packet/manifest", reason_code="MERGE_PAIR_INCOMPLETE",
        )
        merged, hashes["merge"] = _read_json_with_sha(paths["merge"], label="Knife3 merge artifact")
        manifest, hashes["merge_manifest"] = _read_json_with_sha(
            paths["merge_manifest"], label="Knife3 merge manifest",
        )
        upstream_payloads: dict[str, dict[str, Any]] = {}
        for lane in ("web", "x"):
            artifact_key = f"{lane}_discovery"
            receipt_key = f"{lane}_receipt"
            _require_complete_pair(
                paths[artifact_key].is_file(), paths[receipt_key].is_file(),
                label=f"Knife3 {lane} document anchor",
                reason_code="UPSTREAM_ANCHOR_INCOMPLETE",
            )
            upstream_payloads[artifact_key], hashes[artifact_key] = _read_json_with_sha(
                paths[artifact_key], label=f"Knife3 {lane} discovery artifact",
            )
            upstream_payloads[receipt_key], hashes[receipt_key] = _read_json_with_sha(
                paths[receipt_key], label=f"Knife3 {lane} discovery receipt",
            )
        upstream_pairs = {
            "web": (
                upstream_payloads["web_discovery"], upstream_payloads["web_receipt"],
            ),
            "x": (
                upstream_payloads["x_discovery"], upstream_payloads["x_receipt"],
            ),
        }
        ingest_input = merge.validate_merged_packet(
            merged,
            manifest,
            expected_decision_date=ctx.decision_date,
            upstream_pairs=upstream_pairs,
        )
        upstream_pair_anchored = True
        document_content_anchored = bool(manifest["source_refs"]) and all(
            ref["raw_receipt_ref"] is not None for ref in manifest["source_refs"]
        )
        ingest_artifact = ingest.normalize_discovery_payload(
            ingest_input,
            expected_decision_date=ctx.decision_date,
            generated_at=merged["generated_at"],
        )
        if ingest_artifact.get("schema_version") != ingest.SEMANTIC_DISCOVERY_SCHEMA_VERSION:
            missing_semantic = any(
                isinstance(row, dict) and row.get("reason") == "missing_semantic_assertions"
                for receipt_key in ("web_receipt", "x_receipt")
                for row in upstream_payloads[receipt_key].get("drop_ledger", [])
            )
            if missing_semantic or ingest_artifact.get("themes"):
                raise SoftDiscoveryEvidenceError(
                    "provider omitted semantic assertions"
                    if missing_semantic else "semantic discovery artifact is pre-semantic",
                    reason_code=(
                        "SOFT_DISCOVERY_EVIDENCE_INVALID"
                        if missing_semantic else "CANDIDATE_INPUT_UNAVAILABLE"
                    ),
                )
        ingest_payload_sha256 = _serialized_sha256(ingest_artifact)
        if not ctx.candidate_path.is_file() or not ctx.classification_packet_path.is_file():
            raise SoftDiscoveryEvidenceError(
                "candidate/classification input is unavailable",
                reason_code="CANDIDATE_INPUT_UNAVAILABLE",
            )
        validation_inputs = validate.load_inputs_from_discovery(
            discovery=ingest_artifact,
            discovery_sha256=ingest_payload_sha256,
            candidate_path=ctx.candidate_path,
            classification_path=ctx.classification_packet_path,
            expected_date=ctx.decision_date,
        )
        validation_artifact = validate.build_artifact(
            validation_inputs, generated_at=ingest_artifact["generated_at"],
        )
        try:
            hashes["ingest"] = _published_sha256(
                ingest_artifact, paths["ingest"], verify=ingest._validate_schema,
            )
            hashes["validation"] = _published_sha256(
                validation_artifact,
                paths["validation"],
                verify=lambda existing: validate._schema_validate(
                    existing, validate.SCHEMA_PATH, "existing validation artifact",
                ),
            )
        except DiscoveryPublishPolicyError:
            return _immutable_conflict_receipt(
                ctx,
                paths,
                hashes,
                upstream_pair_anchored=upstream_pair_anchored,
                document_content_anchored=document_content_anchored,
            )
    except (
        SoftDiscoveryEvidenceError,
        merge.ThemeDiscoveryMergeError,
        ingest.LLMThemeDiscoveryError,
        validate.ProvisionalThemeValidationError,
    ) as exc:
        if isinstance(exc, merge.ThemeDiscoveryMergeError):
            reason_code = "MERGE_EVIDENCE_INVALID"
        elif isinstance(exc, ingest.LLMThemeDiscoveryError):
            reason_code = "INGEST_EVIDENCE_INVALID"
        elif isinstance(exc, validate.ProvisionalThemeValidationError):
            reason_code = "VALIDATION_EVIDENCE_INVALID"
        else:
            reason_code = exc.reason_code
        payload = _receipt(
            ctx,
            paths,
            status=(
                "upstream_unavailable"
                if reason_code in {"CANDIDATE_INPUT_UNAVAILABLE"}
                else "invalid_evidence"
            ),
            reason_code=reason_code,
            hashes=hashes,
            error_type=type(exc).__name__,
            upstream_pair_anchored=upstream_pair_anchored,
            document_content_anchored=document_content_anchored,
        )
        return _publish_failure_receipt(
            ctx,
            paths,
            payload,
            hashes=hashes,
            upstream_pair_anchored=upstream_pair_anchored,
            document_content_anchored=document_content_anchored,
        )

    validated_theme_count = validation_artifact["summary"]["validated_theme_count"]
    boostable_tickers = {
        member["ticker"]
        for theme in validation_artifact["themes"]
        for member in theme["members"]
    }
    status = "valid_nonempty" if validated_theme_count else "valid_empty"
    receipt = _receipt(
        ctx,
        paths,
        status=status,
        reason_code=None,
        hashes=hashes,
        validated_theme_count=validated_theme_count,
        boostable_ticker_count=len(boostable_tickers),
        # THEME drops only, matching the manifest's own `dropped_theme_count`.  The ledger also
        # carries member-level rows, which this field's name does not describe.
        merge_dropped_theme_count=manifest["summary"]["dropped_theme_count"],
        validation_drop_count=len(validation_artifact["drop_ledger"]),
        generated_at=merged["generated_at"],
        upstream_pair_anchored=upstream_pair_anchored,
        document_content_anchored=document_content_anchored,
    )
    try:
        for path, helper in (
            (paths["ingest"], ingest.default_output_path),
            (paths["validation"], validate.default_output_path),
        ):
            expected = rerooted_default_path(helper, ctx.decision_date, state_dir=ctx.state_dir)
            validate_exact_decision_slot(path, expected, root=ROOT, state_dir=ctx.state_dir)
        validate_exact_decision_slot(
            paths["receipt"],
            default_receipt_path(ctx.decision_date, state_dir=ctx.state_dir),
            root=ROOT,
            state_dir=ctx.state_dir,
        )
        publish_immutable_pair(
            (
                (ingest_artifact, paths["ingest"]),
                (validation_artifact, paths["validation"]),
                (receipt, paths["receipt"]),
            ),
            verifiers=(
                ingest._validate_schema,
                lambda existing: validate._schema_validate(
                    existing, validate.SCHEMA_PATH, "existing validation artifact",
                ),
                _schema_validate,
            ),
            clock_keys=CLOCK_KEYS_NONE,
            recursive=False,
        )
    except DiscoveryPublishPolicyError:
        return _immutable_conflict_receipt(
            ctx,
            paths,
            hashes,
            upstream_pair_anchored=upstream_pair_anchored,
            document_content_anchored=document_content_anchored,
        )
    saved, _sha = _read_json_with_sha(paths["receipt"], label="soft-discovery receipt")
    _schema_validate(saved)
    return saved
