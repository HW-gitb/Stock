"""A-short post-run sidecar health companion.

This module only observes the already-run weekly stages.  It never changes the
selection result, M6.7 bundle, or the non-blocking exit-code contract.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
# The weekly PowerShell launcher invokes this file directly.  Keep the same
# project-root bootstrap as the other runner entry points so ``runners.*``
# imports do not depend on the caller's ``PYTHONPATH`` or working directory.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_observability import safe_exception_summary  # noqa: E402

HEALTH_SCHEMA = ROOT / "schemas" / "a_short_weekly_sidecar_health.schema.json"
OUTCOME_SCHEMA = ROOT / "schemas" / "a_short_weekly_sidecar_outcomes.schema.json"
WEEKLY_RECEIPT_SCHEMA = ROOT / "schemas" / "a_short_weekly_publish_receipt.schema.json"
REQUIRED_ARTIFACT_SCHEMAS = {
    "candidate_effect": ROOT / "schemas" / "a_short_regime_candidate_effect_summary.schema.json",
    "iv_feed": ROOT / "schemas" / "a_short_iv_feed.schema.json",
}

# Deliberately small and explicit.  A new sidecar must be registered here and
# must also be named in the launcher/pipeline expected-outcome manifest.
SIDECAR_SPECS: dict[str, str] = {
    "data_canary": "advisory",
    "forward_tracker_capture": "forward_evidence",
    "forward_tracker_backfill": "forward_evidence",
    "theme_forward_comparison": "forward_evidence",
    "crash_veto": "forward_evidence",
    "shared_cache_build": "cache_support",
    "regime_daily": "forward_evidence",
    "regime_action": "forward_evidence",
    "candidate_effect": "forward_evidence",
    "iv_feed": "readiness",
    "official_operation_capture": "forward_evidence",
    "official_operation_settlement": "forward_evidence",
    "factor_v2_capture": "forward_evidence",
    "margin_overheat_cash_control_capture": "advisory",
    "margin_overheat_cash_control_settlement": "advisory",
    "industry_weight_capture": "forward_evidence",
    "industry_weight_settlement": "forward_evidence",
    "target_policy_capture": "forward_evidence",
    "final_action_capture": "forward_evidence",
    "overlay_adjudication_capture": "forward_evidence",
    "overlay_adjudication_settlement": "forward_evidence",
}
AUTHORITATIVE_ARTIFACT_SIDECARS = frozenset(REQUIRED_ARTIFACT_SCHEMAS)
BEST_EFFORT_SELF_REPORT_SIDECARS = frozenset({
    "data_canary",
    "forward_tracker_capture",
    "forward_tracker_backfill",
    # Landed on master in parallel with the fourth knife.  Best-effort: it has a probe path
    # and its own adjudication-mode check below, but no schema-validated authoritative receipt.
    "theme_forward_comparison",
    "crash_veto",
    "shared_cache_build",
    "regime_daily",
    "regime_action",
    "official_operation_capture",
    "official_operation_settlement",
    "factor_v2_capture",
    "margin_overheat_cash_control_capture",
    "margin_overheat_cash_control_settlement",
    "industry_weight_capture",
    "industry_weight_settlement",
    "target_policy_capture",
    "final_action_capture",
    "overlay_adjudication_capture",
    "overlay_adjudication_settlement",
})


def _validate_sidecar_validation_buckets() -> None:
    """Keep every registered sidecar explicit about whether its artifact is authoritative.

    Authoritative artifacts fail closed on missing/invalid data. Best-effort sidecars retain the
    established launcher-report fallback because they have no schema-bound public receipt yet.
    """
    registered = set(SIDECAR_SPECS)
    authoritative = set(AUTHORITATIVE_ARTIFACT_SIDECARS)
    best_effort = set(BEST_EFFORT_SELF_REPORT_SIDECARS)
    if authoritative & best_effort:
        raise ValueError("sidecar validation buckets overlap")
    if authoritative | best_effort != registered:
        raise ValueError("every sidecar must have one validation bucket")
    if not authoritative <= set(REQUIRED_ARTIFACT_SCHEMAS):
        raise ValueError("authoritative sidecar lacks an artifact schema")


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


def _authoritative_artifact_path(project_root: Path, name: str, as_of: str) -> Path:
    if name == "candidate_effect":
        return project_root / "research/results/a_short/regime_candidate_effect_summary.json"
    if name == "iv_feed":
        return project_root / f"research/results/a_short/iv_feed_{as_of}/iv_feed.json"
    raise ValueError(f"authoritative sidecar has no artifact path: {name}")


def _failed_m67_receipt_evidence(receipt_path: Path, as_of: str) -> dict[str, Any] | None:
    """Validate a failure-only receipt without claiming any output binding."""
    try:
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes.decode("utf-8"))
        schema = json.loads(WEEKLY_RECEIPT_SCHEMA.read_text(encoding="utf-8"))
        jsonschema.validate(receipt, schema)
        if str(receipt.get("as_of")) != str(as_of) or receipt.get("stage_status") != "failed":
            return None
        return {
            "status": "failed",
            "run_id": None,
            "candidate_digest": None,
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
            from runners.a_short_weekly_pipeline import validate_published_weekly_bundle

            bundle = validate_published_weekly_bundle(weekly_path)
            if str(bundle.weekly.get("as_of")) != str(as_of):
                raise ValueError("weekly bundle as_of mismatch")
            lineage = bundle.weekly.get("run_lineage") or {}
            return {
                "status": "complete",
                "run_id": str(lineage.get("run_id") or "") or None,
                "candidate_digest": str(lineage.get("candidate_digest") or "") or None,
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
            "source_receipt_sha256": None,
        }
    if any(present):
        return {
            "status": "unavailable",
            "run_id": None,
            "candidate_digest": None,
            "source_receipt_sha256": None,
        }
    return {
        "status": "unavailable",
        "run_id": None,
        "candidate_digest": None,
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
    return text if len(text) == 8 and text.isdigit() else None


def _max_csv_as_of(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = csv.DictReader(handle)
            dates = [_safe_date(row.get("as_of")) for row in rows]
    except (OSError, csv.Error):
        return None
    valid = [value for value in dates if value]
    return max(valid) if valid else None


def _max_json_as_of(path: Path, *, row_key: str | None = None) -> str | None:
    value = _load_json(path)
    if value is None:
        return None
    if row_key:
        rows = value.get(row_key)
        if isinstance(rows, list):
            dates = [_safe_date(row.get("as_of")) for row in rows if isinstance(row, dict)]
            valid = [date for date in dates if date]
            return max(valid) if valid else None
    return _safe_date(value.get("as_of")) or _safe_date(value.get("latest_evidence_as_of"))


def _probe(project_root: Path, name: str, as_of: str) -> tuple[str | None, str | None]:
    """Return observed decision/data dates from de-identified artifacts."""
    paths: dict[str, tuple[Path, str | None]] = {
        "regime_daily": (project_root / "research/results/a_short/regime_daily_ledger.json", "rows"),
        "regime_action": (project_root / "research/results/a_short/regime_action_comparison_records.json", None),
        "candidate_effect": (project_root / "research/results/a_short/regime_candidate_effect_summary.json", None),
        "crash_veto": (project_root / "logs/a_short_crash_veto_summary.json", None),
        "forward_tracker_capture": (project_root / "logs/forward_tracker.csv", None),
        "theme_forward_comparison": (
            project_root / "research/results/a_short_theme_forward_comparison.json", None
        ),
        "industry_weight_capture": (project_root / "research/results/a_short/industry_weight_comparison_summary.json", None),
        "industry_weight_settlement": (project_root / "research/results/a_short/industry_weight_comparison_summary.json", None),
        "target_policy_capture": (project_root / "research/results/a_short/target_policy_comparison_summary.json", None),
        "final_action_capture": (project_root / "research/results/a_short/final_action_validation_summary.json", None),
        "official_operation_settlement": (project_root / "research/results/a_short/official_operation_evidence_summary.json", None),
        "overlay_adjudication_settlement": (project_root / "research/results/a_short/overlay_adjudication_summary.json", None),
    }
    if name == "factor_v2_capture":
        path = project_root / "state/a_short/factor_comparison_private/v2/weeks" / as_of
        return (as_of if path.is_dir() else None, None)
    if name == "iv_feed":
        observed = _max_json_as_of(
            project_root / f"research/results/a_short/iv_feed_{as_of}/iv_feed.json"
        )
        return observed, None
    path_info = paths.get(name)
    if path_info is None:
        return None, None
    path, row_key = path_info
    if path.suffix.lower() == ".csv":
        observed = _max_csv_as_of(path)
    elif path.name.endswith("records.json") and name == "regime_action":
        try:
            rows = json.loads(path.read_text(encoding="utf-8-sig"))
            observed = max((_safe_date(row.get("as_of")) for row in rows if isinstance(row, dict)), default=None)
        except (OSError, ValueError, TypeError):
            observed = None
    else:
        observed = _max_json_as_of(path, row_key=row_key)
    if name == "regime_daily":
        return None, observed
    return observed, None


def _normalise_outcome(raw: dict[str, Any], *, as_of: str, project_root: Path) -> dict[str, Any]:
    name = str(raw.get("name") or "")
    expected = bool(raw.get("expected"))
    attempted = bool(raw.get("attempted"))
    execution = str(raw.get("execution_status") or "missing_outcome")
    progress = str(raw.get("progress_status") or "unavailable")
    observed_decision = _safe_date(raw.get("observed_decision_as_of"))
    observed_data = _safe_date(raw.get("observed_data_through"))
    required_artifact = (
        _authoritative_artifact_path(project_root, name, as_of)
        if name in AUTHORITATIVE_ARTIFACT_SIDECARS else None
    )
    artifact_valid = None
    artifact_code = None
    artifact_detail = None
    if required_artifact is not None:
        artifact_valid, artifact_code, artifact_detail = _artifact_validation(name, required_artifact)
        if expected and execution == "succeeded" and not artifact_valid:
            execution = "failed"
            progress = "unavailable"
            observed_decision = None
            observed_data = None
            raw = dict(raw)
            raw["error_code"] = raw.get("error_code") or artifact_code
            raw["error_detail"] = raw.get("error_detail") or artifact_detail
    probed_decision, probed_data = _probe(project_root, name, as_of)
    if name in AUTHORITATIVE_ARTIFACT_SIDECARS or probed_decision is not None:
        observed_decision = probed_decision
    if name in AUTHORITATIVE_ARTIFACT_SIDECARS or probed_data is not None:
        observed_data = probed_data
    if execution == "succeeded" and progress == "not_applicable":
        if observed_decision == as_of or (observed_data and observed_data <= as_of):
            progress = "advanced"
    if execution == "failed":
        progress = "stalled" if (observed_decision and observed_decision < as_of) else "unavailable"
    item = {
        "name": name,
        "evidence_role": SIDECAR_SPECS[name],
        "expected": expected,
        "attempted": attempted,
        "execution_status": execution,
        "progress_status": progress,
        "expected_decision_as_of": _safe_date(raw.get("expected_decision_as_of")) or (as_of if name not in {"regime_daily"} else None),
        "expected_data_through": _safe_date(raw.get("expected_data_through")),
        "observed_decision_as_of": observed_decision,
        "observed_data_through": observed_data,
        "error_code": raw.get("error_code"),
        "error_detail": raw.get("error_detail"),
        "skip_reason": raw.get("skip_reason"),
        "blocking": False,
    }
    if "attempted_before_egs" in raw:
        item["attempted_before_egs"] = bool(raw["attempted_before_egs"])
    if raw.get("iv_feed_status") is not None:
        item["iv_feed_status"] = str(raw["iv_feed_status"])
    if raw.get("feed_ref") is not None:
        item["feed_ref"] = str(raw["feed_ref"])
    if raw.get("feed_sha256") is not None:
        item["feed_sha256"] = str(raw["feed_sha256"])
    if item["error_code"] is not None:
        item["error_code"] = str(item["error_code"])
    if item["error_detail"] is not None:
        item["error_detail"] = str(item["error_detail"])
    if item["skip_reason"] is not None:
        item["skip_reason"] = str(item["skip_reason"])
    # A zero exit code is not enough: a successful process that left its
    # expected artifact behind an older clock is still stalled.  Pure cache
    # and settlement helpers have no independent decision clock.
    clockless = {
        "shared_cache_build", "forward_tracker_backfill",
        "official_operation_settlement", "industry_weight_settlement",
        "overlay_adjudication_settlement", "margin_overheat_cash_control_capture",
        "margin_overheat_cash_control_settlement",
    }
    if item["execution_status"] == "succeeded" and name not in clockless:
        expected_decision = item["expected_decision_as_of"]
        expected_data = item["expected_data_through"]
        if expected_decision:
            if observed_decision is None:
                item["progress_status"] = "unavailable"
                item["error_code"] = item["error_code"] or (
                    "candidate_effect_no_observed_evidence"
                    if name == "candidate_effect" else f"{name}_observed_evidence_missing"
                )
                item["error_detail"] = item["error_detail"] or (
                    "authoritative_summary_observed_as_of=missing"
                    if name == "candidate_effect" else "observed_decision_as_of=missing"
                )
            elif observed_decision < expected_decision:
                item["progress_status"] = "stalled"
                item["error_code"] = item["error_code"] or f"{name}_evidence_stale"
                item["error_detail"] = item["error_detail"] or "observed_decision_as_of=stale"
        if expected_data:
            if observed_data is None:
                item["progress_status"] = "unavailable"
                item["error_code"] = item["error_code"] or f"{name}_observed_data_missing"
                item["error_detail"] = item["error_detail"] or "observed_data_through=missing"
            elif observed_data < expected_data:
                item["progress_status"] = "stalled"
                item["error_code"] = item["error_code"] or f"{name}_data_stale"
                item["error_detail"] = item["error_detail"] or "observed_data_through=stale"
    if name == "theme_forward_comparison" and item["execution_status"] == "succeeded":
        packet = _load_json(
            project_root / "research/results/a_short_theme_forward_comparison.json"
        )
        rejected = (packet or {}).get("rejected_atomic_cohorts") if isinstance(packet, dict) else None
        if isinstance(rejected, dict) and rejected.get(str(as_of)):
            item["progress_status"] = "unavailable"
            item["error_code"] = item["error_code"] or "theme_cohort_rejected"
            item["error_detail"] = item["error_detail"] or safe_exception_summary(
                ValueError(str(rejected[str(as_of)])), limit=480
            )
        mode = str((packet or {}).get("adjudication_mode") or "")
        if mode.startswith("epoch_"):
            item["progress_status"] = "stalled"
            item["error_code"] = item["error_code"] or f"evidence_clock_blocked_{mode}"
    if name == "candidate_effect" and expected and item["execution_status"] == "succeeded" \
            and item["observed_decision_as_of"] is None and artifact_valid is not False:
        item["progress_status"] = "unavailable"
        item["error_code"] = item["error_code"] or "candidate_effect_no_observed_evidence"
        item["error_detail"] = item["error_detail"] or "authoritative_summary_observed_as_of=missing"
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
) -> dict[str, Any]:
    _validate_sidecar_validation_buckets()
    if m67_invocation is None:
        m67_invocation = "requested" if m67_out_dir is not None else "not_run"
    if m67_invocation not in {"requested", "skipped", "not_run"}:
        raise ValueError("m67_invocation must be requested, skipped, or not_run")
    manifests = [manifest for manifest in (launcher_manifest,) if manifest]
    if m67_invocation == "requested" and pipeline_manifest:
        manifests.append(pipeline_manifest)
    expected: list[str] = []
    raw_by_name: dict[str, dict[str, Any]] = {}
    manifest_run_ids: set[str] = set()
    manifest_candidate_digests: set[str] = set()
    for manifest in manifests:
        expected.extend(str(name) for name in manifest.get("expected_sidecars", []))
        for raw in manifest.get("sidecars", []):
            if isinstance(raw, dict) and raw.get("name"):
                raw_by_name[str(raw["name"])] = raw
        if manifest.get("run_id"):
            manifest_run_ids.add(str(manifest["run_id"]))
        if manifest.get("candidate_digest"):
            manifest_candidate_digests.add(str(manifest["candidate_digest"]))
    evidence = (
        {
            "status": m67_invocation,
            "run_id": None,
            "candidate_digest": None,
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
            "source_receipt_sha256": None,
        }
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
        entries.append(_normalise_outcome(raw, as_of=as_of, project_root=project_root))
    _validate_health_reason_contract(entries)
    failed = sum(1 for item in entries if item["execution_status"] in {"failed", "missing_outcome"} or
                 (item["expected"] and item["progress_status"] in {"stalled", "unavailable"}))
    stalled = sum(1 for item in entries if item["progress_status"] == "stalled")
    advanced = sum(1 for item in entries if item["progress_status"] in {"advanced", "already_current"})
    partial = sum(1 for item in entries if item["execution_status"] in {"skipped", "not_due", "not_configured"})
    m67_status = str(evidence.get("status") or "unavailable")
    overall = (
        "degraded"
        if failed or m67_status in {"failed", "unavailable"}
        else (
            "partial"
            if partial or m67_status == "skipped"
            else "healthy"
        )
    )
    payload = {
        "schema_name": "a_short_weekly_sidecar_health",
        "schema_version": "1.0.0",
        "as_of": as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": evidence.get("run_id"),
        "candidate_digest": evidence.get("candidate_digest"),
        "m67_status": m67_status,
        "overall": overall,
        "advanced_count": advanced,
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
        "schema_version": "1.0.0",
        "as_of": payload["as_of"],
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
        # `m67_status` is half of the `overall` formula, so it is printed next to
        # the verdict: an all-zero sidecar tally beside `degraded` reads as a
        # contradiction until the M6.7 leg that actually caused it is visible.
        f"overall={payload['overall']} · m67={payload['m67_status']} · advanced={payload['advanced_count']} · stalled={payload['stalled_count']} · failed={payload['failed_count']} · partial={payload['partial_count']}", "",
        "| sidecar | execution | progress | decision/data through | error |", "|---|---|---|---|---|",
    ]
    for item in payload["sidecars"]:
        date = item.get("observed_decision_as_of") or item.get("observed_data_through") or "-"
        md.append(f"| {item['name']} | {item['execution_status']} | {item['progress_status']} | {date} | {item.get('error_code') or '-'} |")
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
    )
    paths = write_health_bundle(payload, out_dir)
    print(f"[sidecar-health] overall={payload['overall']} m67={payload['m67_status']} failed={payload['failed_count']} stalled={payload['stalled_count']} partial={payload['partial_count']} -> {paths[1].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
