"""A-short post-run sidecar health companion.

This module only observes the already-run weekly stages.  It never changes the
selection result, M6.7 bundle, or the non-blocking exit-code contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
# The weekly PowerShell launcher invokes this file directly.  Keep the same
# project-root bootstrap as the other runner entry points so ``runners.*``
# imports do not depend on the caller's ``PYTHONPATH`` or working directory.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_run_revision import validate_run_revision_id  # noqa: E402

HEALTH_SCHEMA = ROOT / "schemas" / "a_short_weekly_sidecar_health.schema.json"
OUTCOME_SCHEMA = ROOT / "schemas" / "a_short_weekly_sidecar_outcomes.schema.json"
WEEKLY_RECEIPT_SCHEMA = ROOT / "schemas" / "a_short_weekly_publish_receipt.schema.json"
REQUIRED_ARTIFACT_SCHEMAS = {
    "candidate_effect": ROOT / "schemas" / "a_short_regime_candidate_effect_summary.schema.json",
    "iv_feed": ROOT / "schemas" / "a_short_iv_feed.schema.json",
}
HEALTH_SCHEMA_VERSION = "1.2.0"

# Deliberately small and explicit.  A new sidecar must be registered here and
# must also be named in the launcher/pipeline expected-outcome manifest.  The
# three properties are the only health policy: no runtime path probing is
# allowed to infer a fourth one.
class _SidecarSpec(dict[str, str]):
    """Mapping value with a small compatibility equality for old callers."""

    def __eq__(self, other: object) -> bool:  # pragma: no cover - compatibility only
        if isinstance(other, str):
            return self.get("evidence_role") == other
        return dict.__eq__(self, other)


def _spec(evidence_role: str, progress_clock: str, evidence_policy: str) -> _SidecarSpec:
    return _SidecarSpec(
        evidence_role=evidence_role,
        progress_clock=progress_clock,
        evidence_policy=evidence_policy,
    )


SIDECAR_SPECS: dict[str, _SidecarSpec] = {
    "data_canary": _spec("advisory", "decision", "manifest_only"),
    "forward_tracker_capture": _spec("forward_evidence", "decision", "manifest_only"),
    "forward_tracker_backfill": _spec("forward_evidence", "clockless", "manifest_only"),
    "theme_forward_comparison": _spec("forward_evidence", "decision", "validated_current_packet"),
    "crash_veto": _spec("forward_evidence", "decision", "manifest_only"),
    "shared_cache_build": _spec("cache_support", "clockless", "manifest_only"),
    "regime_daily": _spec("forward_evidence", "data", "manifest_only"),
    "regime_action": _spec("forward_evidence", "decision", "manifest_only"),
    "candidate_effect": _spec("forward_evidence", "decision", "authoritative_artifact"),
    "iv_feed": _spec("readiness", "decision", "authoritative_artifact"),
    "official_operation_capture": _spec("forward_evidence", "decision", "manifest_only"),
    "official_operation_settlement": _spec("forward_evidence", "clockless", "manifest_only"),
    "factor_v2_capture": _spec("forward_evidence", "decision", "manifest_only"),
    "margin_overheat_cash_control_capture": _spec("advisory", "clockless", "manifest_only"),
    "margin_overheat_cash_control_settlement": _spec("advisory", "clockless", "manifest_only"),
    "industry_weight_capture": _spec("forward_evidence", "decision", "manifest_only"),
    "industry_weight_settlement": _spec("forward_evidence", "clockless", "manifest_only"),
    "target_policy_capture": _spec("forward_evidence", "decision", "manifest_only"),
    "final_action_capture": _spec("forward_evidence", "decision", "manifest_only"),
    "final_action_settlement": _spec("forward_evidence", "clockless", "manifest_only"),
    "overlay_adjudication_capture": _spec("forward_evidence", "decision", "manifest_only"),
    "overlay_adjudication_settlement": _spec("forward_evidence", "clockless", "manifest_only"),
}
AUTHORITATIVE_ARTIFACT_SIDECARS = frozenset(
    name for name, spec in SIDECAR_SPECS.items()
    if spec["evidence_policy"] == "authoritative_artifact"
)
BEST_EFFORT_SELF_REPORT_SIDECARS = frozenset(
    set(SIDECAR_SPECS) - set(AUTHORITATIVE_ARTIFACT_SIDECARS)
)
_ALLOWED_CLOCKS = frozenset({"decision", "data", "clockless"})
_ALLOWED_POLICIES = frozenset({
    "manifest_only", "authoritative_artifact", "validated_current_packet",
})


def _validate_sidecar_validation_buckets() -> None:
    """Require one explicit clock and one evidence policy for every sidecar."""
    registered = set(SIDECAR_SPECS)
    clock_registered: set[str] = set()
    policy_registered: set[str] = set()
    for name, spec in SIDECAR_SPECS.items():
        if not isinstance(spec, dict):
            raise ValueError("every sidecar must have one validation bucket")
        if set(spec) != {"evidence_role", "progress_clock", "evidence_policy"}:
            raise ValueError("every sidecar must have one validation bucket")
        if spec.get("progress_clock") not in _ALLOWED_CLOCKS:
            raise ValueError("every sidecar must have one progress clock")
        if spec.get("evidence_policy") not in _ALLOWED_POLICIES:
            raise ValueError("every sidecar must have one evidence policy")
        clock_registered.add(name)
        policy_registered.add(name)
    if registered != clock_registered or registered != policy_registered:
        raise ValueError("every sidecar must have one validation bucket")
    if set(AUTHORITATIVE_ARTIFACT_SIDECARS) != {
        name for name, spec in SIDECAR_SPECS.items()
        if spec.get("evidence_policy") == "authoritative_artifact"
    }:
        raise ValueError("authoritative sidecar policy mismatch")
    if not set(AUTHORITATIVE_ARTIFACT_SIDECARS) <= set(REQUIRED_ARTIFACT_SCHEMAS):
        raise ValueError("authoritative sidecar lacks an artifact schema")
    if any(
        spec.get("evidence_policy") == "authoritative_artifact"
        and spec.get("progress_clock") != "decision"
        for spec in SIDECAR_SPECS.values()
    ):
        raise ValueError("authoritative artifact must use decision clock")
    if SIDECAR_SPECS.get("theme_forward_comparison", {}).get("evidence_policy") != "validated_current_packet":
        raise ValueError("theme sidecar must use current packet policy")


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _artifact_validation(name: str, path: Path) -> tuple[bool, str | None, str | None]:
    """Validate one authoritative artifact and return ``(ok, code, detail)``.

    The detail is deliberately a short, de-identified classification.  It
    never contains the path or raw JSON, so health can safely persist it.
    """
    if not path.is_file():
        return False, f"{name}_artifact_missing", "artifact=missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        return False, f"{name}_artifact_invalid_json", "artifact=invalid_json"
    if not isinstance(payload, dict):
        return False, f"{name}_artifact_schema_invalid", "artifact=not_object"
    schema_path = REQUIRED_ARTIFACT_SCHEMAS.get(name)
    if schema_path is None:
        return False, f"{name}_artifact_schema_invalid", "artifact=schema_unregistered"
    try:
        if name == "iv_feed":
            from runners.a_short_iv_feed_build import validate_feed_artifact

            validate_feed_artifact(payload)
        else:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            jsonschema.validate(payload, schema)
            if name == "candidate_effect":
                from engine.a_short_regime_action_comparison import validate_candidate_effect_summary

                validate_candidate_effect_summary(payload)
    except jsonschema.ValidationError:
        return False, f"{name}_artifact_schema_invalid", "artifact=schema_invalid"
    except jsonschema.SchemaError:
        return False, f"{name}_artifact_schema_invalid", "artifact=schema_unreadable"
    except (OSError, ValueError, TypeError):
        return False, f"{name}_artifact_identity_mismatch", "artifact=identity_or_content_mismatch"
    return True, None, None


def _artifact_matches_schema(name: str, path: Path) -> bool:
    """Boolean compatibility wrapper for existing callers and tests."""
    return _artifact_validation(name, path)[0]


def _authoritative_artifact_path(project_root: Path, name: str, as_of: str,
                                 iv_feed_path: Path | None = None) -> Path:
    if name == "candidate_effect":
        return project_root / "research/results/a_short/regime_candidate_effect_summary.json"
    if name == "iv_feed":
        if iv_feed_path is not None:
            return iv_feed_path
        return project_root / f"research/results/a_short/iv_feed_{as_of}/iv_feed.json"
    raise ValueError(f"authoritative sidecar has no artifact path: {name}")


def _failed_m67_receipt_evidence(receipt_path: Path, as_of: str) -> dict[str, Any] | None:
    """Validate a failure-only receipt while preserving only paired identities."""
    try:
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes.decode("utf-8"))
        schema = json.loads(WEEKLY_RECEIPT_SCHEMA.read_text(encoding="utf-8"))
        jsonschema.validate(receipt, schema)
        if str(receipt.get("as_of")) != str(as_of) or receipt.get("stage_status") != "failed":
            return None
        receipt_run_id = str(receipt.get("run_id") or "") or None
        receipt_candidate_digest = str(receipt.get("candidate_digest") or "") or None
        if not (receipt_run_id and receipt_candidate_digest):
            receipt_run_id = None
            receipt_candidate_digest = None
        return {
            "status": "failed",
            "run_id": receipt_run_id,
            "candidate_digest": receipt_candidate_digest,
            "run_revision_id": str(receipt.get("run_revision_id") or "") or None,
            "source_receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        }
    except (
        OSError,
        UnicodeDecodeError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        jsonschema.ValidationError,
        jsonschema.SchemaError,
    ):
        return None


def _m67_evidence(
    out_dir: Path,
    as_of: str,
) -> dict[str, Any]:
    """Derive requested M6.7 health identity from the canonical published bundle only."""
    weekly_path = out_dir / "weekly_m67.json"
    markdown_path = out_dir / "weekly_m67.md"
    receipt_path = out_dir / "weekly_m67.receipt.json"
    present = (weekly_path.is_file(), markdown_path.is_file(), receipt_path.is_file())
    if all(present):
        try:
            from runners.a_short_weekly_pipeline import validate_published_weekly_operation_bundle

            bundle = validate_published_weekly_operation_bundle(weekly_path)
            if str(bundle.weekly.get("as_of")) != str(as_of):
                raise ValueError("weekly bundle as_of mismatch")
            lineage = bundle.weekly.get("run_lineage") or {}
            return {
                "status": str(bundle.receipt.get("stage_status") or ""),
                "run_id": str(lineage.get("run_id") or "") or None,
                "candidate_digest": str(lineage.get("candidate_digest") or "") or None,
                "run_revision_id": str(lineage.get("run_revision_id") or "") or None,
                "source_receipt_sha256": bundle.receipt_sha256,
            }
        except Exception:
            failed = _failed_m67_receipt_evidence(receipt_path, as_of)
            if failed is not None:
                return failed
            return {
                "status": "unavailable",
                "run_id": None,
                "candidate_digest": None,
                "run_revision_id": None,
                "source_receipt_sha256": None,
            }
    if receipt_path.is_file() and not weekly_path.exists() and not markdown_path.exists():
        failed = _failed_m67_receipt_evidence(receipt_path, as_of)
        if failed is not None:
            return failed
        return {
            "status": "unavailable",
            "run_id": None,
            "candidate_digest": None,
            "run_revision_id": None,
            "source_receipt_sha256": None,
        }
    if any(present):
        return {
            "status": "unavailable",
            "run_id": None,
            "candidate_digest": None,
            "run_revision_id": None,
            "source_receipt_sha256": None,
        }
    return {
        "status": "unavailable",
        "run_id": None,
        "candidate_digest": None,
        "run_revision_id": None,
        "source_receipt_sha256": None,
    }


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _safe_date(value: Any) -> str | None:
    text = str(value or "")
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None
    return text


def _normalise_date_field(
    value: Any,
    *,
    as_of: str,
    field: str,
    clock: str,
) -> tuple[str | None, str | None]:
    """Parse one manifest date without accepting future or impossible dates."""
    if value in (None, ""):
        return None, None
    parsed = _safe_date(value)
    if parsed is None or parsed > as_of:
        return None, "health_contract_invalid_date"
    if clock == "decision" and field == "observed_data_through":
        return None, "health_contract_clock_mismatch"
    if clock == "data" and field == "observed_decision_as_of":
        return None, "health_contract_clock_mismatch"
    return parsed, None


def _artifact_observed_date(name: str, path: Path, *, as_of: str) -> tuple[str | None, str | None]:
    """Read only the date owned by an already validated authoritative artifact."""
    payload = _load_json(path)
    if payload is None:
        return None, "health_contract_invalid_date"
    value = payload.get("as_of") if name == "iv_feed" else (
        payload.get("latest_evidence_as_of")
        or payload.get("observed_as_of")
        or payload.get("as_of")
    )
    if value in (None, ""):
        return None, None
    parsed = _safe_date(value)
    if parsed is None or parsed > as_of:
        return None, "health_contract_invalid_date"
    return parsed, None


def _set_contract_failure(item: dict[str, Any], code: str | None, detail: str | None) -> None:
    item["progress_status"] = "unavailable"
    if code and not item.get("error_code"):
        item["error_code"] = code
    if detail and not item.get("error_detail"):
        item["error_detail"] = detail


def _theme_packet_progress(
    item: dict[str, Any],
    *,
    as_of: str,
    project_root: Path,
) -> None:
    """Apply the one named theme packet rule; never inspect stale packets."""
    if not (item["expected"] and item["attempted"] and item["execution_status"] == "succeeded"):
        return
    packet_path = project_root / "research/results/a_short_theme_forward_comparison.json"
    packet = _load_json(packet_path)
    if packet is None:
        _set_contract_failure(item, None, None)
        return
    try:
        from engine.a_short_theme_forward_comparison import validate_comparison_packet

        validate_comparison_packet(packet)
    except Exception:
        _set_contract_failure(item, None, None)
        return
    latest, date_error = _normalise_date_field(
        packet.get("latest_evidence_as_of"),
        as_of=as_of,
        field="observed_decision_as_of",
        clock="decision",
    )
    if date_error:
        _set_contract_failure(item, date_error, "theme_packet_latest_evidence_as_of=invalid")
        return
    if latest is not None:
        item["observed_decision_as_of"] = latest
    rejected = packet.get("rejected_atomic_cohorts")
    if isinstance(rejected, dict) and rejected.get(as_of):
        # V3-A owns this reason.  The health consumer only chooses the state.
        item["progress_status"] = "unavailable"
        return
    mode = str(packet.get("adjudication_mode") or "")
    if mode.startswith("epoch_"):
        item["progress_status"] = "stalled"
        return
    # The producer/launcher outcome is the progress authority.  A packet date
    # is an observed clock only; it must not upgrade a producer no-op into
    # ``advanced``.


def _normalise_outcome(raw: dict[str, Any], *, as_of: str, project_root: Path,
                       iv_feed_path: Path | None = None) -> dict[str, Any]:
    name = str(raw.get("name") or "")
    spec = SIDECAR_SPECS[name]
    clock = spec["progress_clock"]
    policy = spec["evidence_policy"]
    expected = bool(raw.get("expected"))
    attempted = bool(raw.get("attempted"))
    execution = str(raw.get("execution_status") or "missing_outcome")
    progress = str(raw.get("progress_status") or "unavailable")
    observed_decision, decision_error = _normalise_date_field(
        raw.get("observed_decision_as_of"), as_of=as_of,
        field="observed_decision_as_of", clock=clock,
    )
    observed_data, data_error = _normalise_date_field(
        raw.get("observed_data_through"), as_of=as_of,
        field="observed_data_through", clock=clock,
    )
    expected_data, expected_data_error = _normalise_date_field(
        raw.get("expected_data_through"), as_of=as_of,
        field="expected_data_through", clock="data" if clock == "data" else "clockless",
    )
    expected_decision_raw = raw.get("expected_decision_as_of")
    expected_decision = None
    expected_decision_error = None
    if clock == "decision":
        if expected_decision_raw not in (None, ""):
            expected_decision, expected_decision_error = _normalise_date_field(
                expected_decision_raw, as_of=as_of,
                field="expected_decision_as_of", clock="decision",
            )
        else:
            expected_decision = as_of
    elif expected_decision_raw not in (None, ""):
        expected_decision_error = "health_contract_clock_mismatch"
    if clock != "data" and expected_data is not None:
        expected_data_error = "health_contract_clock_mismatch"

    item = {
        "name": name,
        "evidence_role": spec["evidence_role"],
        "expected": expected,
        "attempted": attempted,
        "execution_status": execution,
        "progress_status": progress,
        "expected_decision_as_of": expected_decision,
        "expected_data_through": expected_data if clock == "data" else None,
        "observed_decision_as_of": observed_decision,
        "observed_data_through": observed_data,
        "error_code": raw.get("error_code"),
        "error_detail": raw.get("error_detail"),
        "skip_reason": raw.get("skip_reason"),
        "blocking": False,
    }
    for key in ("error_code", "error_detail", "skip_reason"):
        if item[key] is not None:
            item[key] = str(item[key])
    if "attempted_before_egs" in raw:
        item["attempted_before_egs"] = bool(raw["attempted_before_egs"])
    if raw.get("iv_feed_status") is not None:
        item["iv_feed_status"] = str(raw["iv_feed_status"])
    if raw.get("feed_ref") is not None:
        item["feed_ref"] = str(raw["feed_ref"])
    if raw.get("feed_sha256") is not None:
        item["feed_sha256"] = str(raw["feed_sha256"])

    date_error = next(
        (error for error in (decision_error, data_error, expected_data_error, expected_decision_error) if error),
        None,
    )

    # The only artifact reads are the two named authoritative validators, and
    # only for a current, expected, attempted successful run.
    artifact_valid: bool | None = None
    if policy == "authoritative_artifact" and expected and attempted and execution == "succeeded":
        artifact_path = _authoritative_artifact_path(project_root, name, as_of, iv_feed_path)
        artifact_valid, _artifact_code, _artifact_detail = _artifact_validation(name, artifact_path)
        if artifact_valid:
            artifact_date, artifact_date_error = _artifact_observed_date(name, artifact_path, as_of=as_of)
            if artifact_date_error:
                date_error = date_error or artifact_date_error
                item["observed_decision_as_of"] = None
            else:
                item["observed_decision_as_of"] = artifact_date
                if name == "candidate_effect" and artifact_date is None:
                    # V3-A owns the stable explanation for a valid current
                    # summary that has no observed evidence clock.  V4 may
                    # downgrade progress, but must not replace this reason
                    # with its generic missing-clock classification.
                    item["error_code"] = item["error_code"] or "candidate_effect_no_observed_evidence"
                    item["error_detail"] = item["error_detail"] or \
                        "authoritative_summary_observed_as_of=missing"
            item["observed_data_through"] = None
        else:
            item["observed_decision_as_of"] = None
            item["observed_data_through"] = None
            _set_contract_failure(item, None, None)

    if policy == "validated_current_packet":
        _theme_packet_progress(item, as_of=as_of, project_root=project_root)

    if date_error:
        _set_contract_failure(item, date_error, f"{date_error}=manifest_clock")

    # Upstream execution/progress is authoritative.  Only the explicitly
    # allowed decision/data checks may change a claimed advanced state.
    if execution == "failed" and progress not in {"stalled", "unavailable"}:
        item["progress_status"] = "unavailable"
        item["error_code"] = item["error_code"] or "health_contract_conflict"
        item["error_detail"] = item["error_detail"] or "failed_progress_conflict"
    elif execution in {"skipped", "not_due", "not_configured"} and progress != "not_applicable":
        item["progress_status"] = "unavailable"
        item["error_code"] = item["error_code"] or "health_contract_conflict"
        item["error_detail"] = item["error_detail"] or "non_execution_progress_conflict"

    if execution == "succeeded" and item["progress_status"] in {"advanced", "already_current"}:
        if clock == "decision":
            if item["observed_decision_as_of"] is None:
                _set_contract_failure(item, "health_contract_missing_clock", "observed_decision_as_of=missing")
            elif expected_decision and item["observed_decision_as_of"] < expected_decision:
                item["progress_status"] = "stalled"
                if not item.get("error_code"):
                    item["error_code"] = f"{name}_evidence_stale"
                if not item.get("error_detail"):
                    item["error_detail"] = "observed_decision_as_of=stale"
        elif clock == "data":
            if item["observed_data_through"] is None:
                _set_contract_failure(item, "health_contract_missing_clock", "observed_data_through=missing")
            elif expected_data and item["observed_data_through"] < expected_data:
                item["progress_status"] = "stalled"
                if not item.get("error_code"):
                    item["error_code"] = f"{name}_data_stale"
                if not item.get("error_detail"):
                    item["error_detail"] = "observed_data_through=stale"
    return item


def _validate_health_reason_contract(entries: list[dict[str, Any]]) -> None:
    """Keep health durable even when an upstream sidecar violates its reason contract.

    Health is the diagnostic boundary.  A malformed upstream outcome must be
    visible as a bounded synthetic reason, not allowed to erase the JSON,
    Markdown, and receipt bundle that explains the failure.
    """
    for item in entries:
        if item["execution_status"] in {"failed", "missing_outcome"} or \
                item["progress_status"] in {"stalled", "unavailable"}:
            code = item.get("error_code")
            issues: list[str] = []
            if not isinstance(code, str) or not code or not code.replace("_", "").isalnum():
                issues.append("missing_or_invalid_error_code")
            detail = item.get("error_detail")
            if detail is not None and (
                    not isinstance(detail, str)
                    or "\n" in detail
                    or "\r" in detail
                    or len(detail) > 512
            ):
                issues.append("error_detail_unbounded")
            if issues:
                # Preserve a valid upstream code when only detail is malformed;
                # otherwise diagnostics lose the producer's actionable reason.
                if "missing_or_invalid_error_code" in issues:
                    item["error_code"] = "reason_contract_violation"
                item["error_detail"] = "health_reason_contract=" + ";".join(issues)


def build_health(
    *,
    as_of: str,
    launcher_manifest: dict[str, Any] | None = None,
    pipeline_manifest: dict[str, Any] | None = None,
    project_root: Path = ROOT,
    m67_out_dir: Path | None = None,
    m67_invocation: str | None = None,
    iv_feed_path: Path | None = None,
    run_revision_id: str | None = None,
) -> dict[str, Any]:
    _validate_sidecar_validation_buckets()
    as_of = _safe_date(as_of)
    if as_of is None:
        raise ValueError("health_contract_invalid_date")
    if m67_invocation is None:
        m67_invocation = "requested" if m67_out_dir is not None else "not_run"
    if m67_invocation not in {"requested", "skipped", "not_run"}:
        raise ValueError("m67_invocation must be requested, skipped, or not_run")
    if run_revision_id not in (None, ""):
        run_revision_id = validate_run_revision_id(run_revision_id)
    manifests = [manifest for manifest in (launcher_manifest,) if manifest]
    if m67_invocation == "requested" and pipeline_manifest:
        manifests.append(pipeline_manifest)
    expected: list[str] = []
    raw_by_name: dict[str, dict[str, Any]] = {}
    sidecar_owners: dict[str, int] = {}
    manifest_run_ids: set[str] = set()
    manifest_candidate_digests: set[str] = set()
    manifest_revisions: set[str] = set()
    for manifest_index, manifest in enumerate(manifests):
        if manifest.get("as_of") not in (None, "", as_of):
            raise ValueError("health_contract_clock_mismatch")
        expected.extend(str(name) for name in manifest.get("expected_sidecars", []))
        for raw in manifest.get("sidecars", []):
            if isinstance(raw, dict) and raw.get("name"):
                name = str(raw["name"])
                if name in sidecar_owners:
                    raise ValueError("duplicate_sidecar_outcome")
                sidecar_owners[name] = manifest_index
                raw_by_name[name] = raw
        if manifest.get("run_id"):
            manifest_run_ids.add(str(manifest["run_id"]))
        if manifest.get("candidate_digest"):
            manifest_candidate_digests.add(str(manifest["candidate_digest"]))
        if manifest.get("run_revision_id") not in (None, ""):
            manifest_revisions.add(validate_run_revision_id(manifest["run_revision_id"]))
    if len(manifest_revisions) > 1:
        raise ValueError("launcher/pipeline manifests use different run_revision_id values")
    if run_revision_id is not None and manifest_revisions and manifest_revisions != {run_revision_id}:
        raise ValueError("manifest run_revision_id does not match requested run revision")
    evidence = (
        {
            "status": m67_invocation,
            "run_id": None,
            "candidate_digest": None,
            "run_revision_id": None,
            "source_receipt_sha256": None,
        }
        if m67_invocation != "requested"
        else (
            _m67_evidence(Path(m67_out_dir), as_of)
            if m67_out_dir is not None
            else {
                "status": "unavailable",
                "run_id": None,
                "candidate_digest": None,
                "run_revision_id": None,
                "source_receipt_sha256": None,
            }
        )
    )
    if evidence.get("status") == "complete" and (
        (manifest_run_ids and manifest_run_ids != {evidence.get("run_id")})
        or (
            manifest_candidate_digests
            and manifest_candidate_digests != {evidence.get("candidate_digest")}
        )
    ):
        evidence = {
            "status": "unavailable",
            "run_id": None,
            "candidate_digest": None,
            "run_revision_id": None,
            "source_receipt_sha256": None,
        }
    evidence_revision = evidence.get("run_revision_id")
    if evidence_revision not in (None, ""):
        evidence_revision = validate_run_revision_id(evidence_revision)
    if manifest_revisions and evidence_revision not in (None, next(iter(manifest_revisions))):
        raise ValueError("M6.7 bundle run_revision_id does not match sidecar manifests")
    if run_revision_id is not None and evidence_revision not in (None, run_revision_id):
        raise ValueError("M6.7 bundle run_revision_id does not match requested run revision")
    resolved_revision = run_revision_id or (next(iter(manifest_revisions)) if manifest_revisions else evidence_revision)
    expected = list(dict.fromkeys(expected))
    for name in expected:
        if name not in SIDECAR_SPECS:
            raise ValueError(f"unregistered sidecar: {name}")
    entries: list[dict[str, Any]] = []
    for name in expected:
        raw = dict(raw_by_name.get(name) or {})
        if not raw:
            raw = {
                "name": name, "expected": True, "attempted": False,
                "execution_status": "missing_outcome", "progress_status": "unavailable",
                "error_code": "missing_outcome",
            }
        entries.append(_normalise_outcome(
            raw, as_of=as_of, project_root=project_root,
            iv_feed_path=iv_feed_path,
        ))
    _validate_health_reason_contract(entries)
    failed = sum(1 for item in entries if item["execution_status"] in {"failed", "missing_outcome"})
    stalled = sum(1 for item in entries if item["progress_status"] == "stalled")
    advanced = sum(1 for item in entries if item["progress_status"] == "advanced")
    already_current = sum(1 for item in entries if item["progress_status"] == "already_current")
    partial = sum(1 for item in entries if item["execution_status"] in {"skipped", "not_due", "not_configured"})
    sidecar_degraded = any(
        item["expected"] and item["progress_status"] in {"stalled", "unavailable"}
        for item in entries
    )
    m67_status = str(evidence.get("status") or "unavailable")
    overall = (
        "failed"
        if m67_status == "failed"
        else "degraded"
        if failed or sidecar_degraded or m67_status in {
            "unavailable", "degraded_no_new_entries",
        }
        else (
            "partial"
            if partial or m67_status in {"skipped", "partial_holdings_only"}
            else "healthy"
        )
    )
    payload = {
        "schema_name": "a_short_weekly_sidecar_health",
        "schema_version": HEALTH_SCHEMA_VERSION,
        "as_of": as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_revision_id": resolved_revision,
        "run_id": evidence.get("run_id"),
        "candidate_digest": evidence.get("candidate_digest"),
        "m67_status": m67_status,
        "overall": overall,
        "advanced_count": advanced,
        "already_current_count": already_current,
        "stalled_count": stalled,
        "failed_count": failed,
        "partial_count": partial,
        "source_receipt_sha256": evidence.get("source_receipt_sha256"),
        "sidecars": entries,
    }
    jsonschema.validate(payload, json.loads(HEALTH_SCHEMA.read_text(encoding="utf-8")))
    return payload


def _load_manifest(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    if not Path(path).is_file():
        return None
    payload = _load_json(Path(path))
    if payload is None:
        raise ValueError("sidecar outcome manifest is not valid JSON")
    jsonschema.validate(payload, json.loads(OUTCOME_SCHEMA.read_text(encoding="utf-8")))
    return payload


def write_health_bundle(payload: dict[str, Any], out_dir: Path) -> tuple[Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "sidecar_health.json"
    md_path = out_dir / "sidecar_health.md"
    receipt = {
        "schema_name": "a_short_weekly_sidecar_health_receipt",
        "schema_version": HEALTH_SCHEMA_VERSION,
        "as_of": payload["as_of"],
        "run_revision_id": payload.get("run_revision_id"),
        "run_id": payload.get("run_id"),
        "candidate_digest": payload.get("candidate_digest"),
        "health_sha256": None,
        "source_receipt_sha256": payload.get("source_receipt_sha256"),
        "overall": payload["overall"],
        "outputs": [json_path.name, md_path.name],
    }
    json_bytes = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    receipt["health_sha256"] = hashlib.sha256(json_bytes).hexdigest()
    md = [
        f"# A-short sidecar health · {payload['as_of']}", "",
        f"already_current={payload['already_current_count']}", "",
        # `m67_status` is half of the `overall` formula, so it is printed next to
        # the verdict: an all-zero sidecar tally beside a non-failed main state reads as a
        # contradiction until the M6.7 leg that actually caused it is visible.
        f"overall={payload['overall']} · m67={payload['m67_status']} · advanced={payload['advanced_count']} · stalled={payload['stalled_count']} · sidecar_failed={payload['failed_count']} · partial={payload['partial_count']}", "",
        "| sidecar | execution | progress | expected decision | observed decision | expected data through | observed data through | error |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in payload["sidecars"]:
        md.append(
            f"| {item['name']} | {item['execution_status']} | {item['progress_status']} | "
            f"{item.get('expected_decision_as_of') or '-'} | "
            f"{item.get('observed_decision_as_of') or '-'} | "
            f"{item.get('expected_data_through') or '-'} | "
            f"{item.get('observed_data_through') or '-'} | "
            f"{item.get('error_code') or '-'} |"
        )
    md_bytes = ("\n".join(md) + "\n").encode("utf-8")
    receipt_bytes = (json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    _atomic_write(json_path, json_bytes)
    _atomic_write(md_path, md_bytes)
    _atomic_write(out_dir / "sidecar_health.receipt.json", receipt_bytes)
    return json_path, md_path, out_dir / "sidecar_health.receipt.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A-short weekly sidecar health companion")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--project-root", default=str(ROOT))
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--launcher-outcomes")
    parser.add_argument("--pipeline-outcomes")
    parser.add_argument("--iv-feed", help="revision-scoped IV feed for authoritative health validation")
    parser.add_argument("--run-revision-id", help="expected V5 revision shared by M6.7 and both manifests")
    parser.add_argument(
        "--m67-invocation",
        choices=["requested", "skipped", "not_run"],
        default="requested",
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir).resolve()
    payload = build_health(
        as_of=args.as_of,
        launcher_manifest=_load_manifest(args.launcher_outcomes),
        pipeline_manifest=_load_manifest(args.pipeline_outcomes),
        project_root=Path(args.project_root).resolve(),
        m67_out_dir=out_dir,
        m67_invocation=args.m67_invocation,
        iv_feed_path=Path(args.iv_feed).resolve() if args.iv_feed else None,
        run_revision_id=args.run_revision_id,
    )
    paths = write_health_bundle(payload, out_dir)
    print(f"[sidecar-health] overall={payload['overall']} m67={payload['m67_status']} sidecar_failed={payload['failed_count']} stalled={payload['stalled_count']} partial={payload['partial_count']} -> {paths[1].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
