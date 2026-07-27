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
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
HEALTH_SCHEMA = ROOT / "schemas" / "a_short_weekly_sidecar_health.schema.json"
OUTCOME_SCHEMA = ROOT / "schemas" / "a_short_weekly_sidecar_outcomes.schema.json"
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
    "crash_veto": "forward_evidence",
    "shared_cache_build": "cache_support",
    "regime_daily": "forward_evidence",
    "regime_action": "forward_evidence",
    "candidate_effect": "forward_evidence",
    "iv_feed": "readiness",
    "official_operation_capture": "forward_evidence",
    "official_operation_settlement": "forward_evidence",
    "factor_v2_capture": "forward_evidence",
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
    "crash_veto",
    "shared_cache_build",
    "regime_daily",
    "regime_action",
    "official_operation_capture",
    "official_operation_settlement",
    "factor_v2_capture",
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


def _artifact_matches_schema(name: str, path: Path) -> bool:
    payload = _load_json(path)
    schema_path = REQUIRED_ARTIFACT_SCHEMAS.get(name)
    if payload is None or schema_path is None:
        return False
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(payload, schema)
        if name == "candidate_effect":
            from engine.a_short_regime_action_comparison import validate_candidate_effect_summary
            validate_candidate_effect_summary(payload)
        elif name == "iv_feed":
            from runners.a_short_iv_feed_build import validate_feed_summary_consistency
            validate_feed_summary_consistency(payload)
    except (OSError, ValueError, TypeError, jsonschema.ValidationError, jsonschema.SchemaError):
        return False
    return True


def _authoritative_artifact_path(project_root: Path, name: str, as_of: str) -> Path:
    if name == "candidate_effect":
        return project_root / "research/results/a_short/regime_candidate_effect_summary.json"
    if name == "iv_feed":
        return project_root / f"research/results/a_short/iv_feed_{as_of}/iv_feed.json"
    raise ValueError(f"authoritative sidecar has no artifact path: {name}")


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


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
    if expected and execution == "succeeded" and required_artifact is not None \
            and not _artifact_matches_schema(name, required_artifact):
        execution = "failed"
        progress = "unavailable"
        observed_decision = None
        observed_data = None
        raw = dict(raw)
        raw["error_code"] = f"{name}_artifact_missing_or_invalid"
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
        "skip_reason": raw.get("skip_reason"),
        "blocking": False,
    }
    if item["error_code"] is not None:
        item["error_code"] = str(item["error_code"])
    if item["skip_reason"] is not None:
        item["skip_reason"] = str(item["skip_reason"])
    # A zero exit code is not enough: a successful process that left its
    # expected artifact behind an older clock is still stalled.  Pure cache
    # and settlement helpers have no independent decision clock.
    clockless = {
        "shared_cache_build", "forward_tracker_backfill",
        "official_operation_settlement", "industry_weight_settlement",
        "overlay_adjudication_settlement",
    }
    if item["execution_status"] == "succeeded" and name not in clockless:
        expected_decision = item["expected_decision_as_of"]
        expected_data = item["expected_data_through"]
        if expected_decision:
            if observed_decision is None:
                item["progress_status"] = "unavailable"
            elif observed_decision < expected_decision:
                item["progress_status"] = "stalled"
        if expected_data:
            if observed_data is None:
                item["progress_status"] = "unavailable"
            elif observed_data < expected_data:
                item["progress_status"] = "stalled"
    return item


def build_health(
    *,
    as_of: str,
    launcher_manifest: dict[str, Any] | None = None,
    pipeline_manifest: dict[str, Any] | None = None,
    project_root: Path = ROOT,
    m67_status: str = "not_run",
    run_id: str | None = None,
    candidate_digest: str | None = None,
) -> dict[str, Any]:
    _validate_sidecar_validation_buckets()
    manifests = [manifest for manifest in (launcher_manifest, pipeline_manifest) if manifest]
    expected: list[str] = []
    raw_by_name: dict[str, dict[str, Any]] = {}
    for manifest in manifests:
        expected.extend(str(name) for name in manifest.get("expected_sidecars", []))
        for raw in manifest.get("sidecars", []):
            if isinstance(raw, dict) and raw.get("name"):
                raw_by_name[str(raw["name"])] = raw
        run_id = run_id or manifest.get("run_id")
        candidate_digest = candidate_digest or manifest.get("candidate_digest")
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
    failed = sum(1 for item in entries if item["execution_status"] in {"failed", "missing_outcome"} or
                 (item["expected"] and item["progress_status"] in {"stalled", "unavailable"}))
    stalled = sum(1 for item in entries if item["progress_status"] == "stalled")
    advanced = sum(1 for item in entries if item["progress_status"] in {"advanced", "already_current"})
    partial = sum(1 for item in entries if item["execution_status"] in {"skipped", "not_due", "not_configured"})
    overall = "degraded" if failed else ("partial" if partial else "healthy")
    payload = {
        "schema_name": "a_short_weekly_sidecar_health",
        "schema_version": "1.0.0",
        "as_of": as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": run_id,
        "candidate_digest": candidate_digest,
        "m67_status": m67_status,
        "overall": overall,
        "advanced_count": advanced,
        "stalled_count": stalled,
        "failed_count": failed,
        "partial_count": partial,
        "source_receipt_sha256": None,
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


def write_health_bundle(payload: dict[str, Any], out_dir: Path, receipt_path: Path | None = None) -> tuple[Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    source_sha = _sha256(receipt_path) if receipt_path else None
    if source_sha:
        payload = dict(payload)
        payload["source_receipt_sha256"] = source_sha
        jsonschema.validate(payload, json.loads(HEALTH_SCHEMA.read_text(encoding="utf-8")))
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
    json_bytes = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    receipt["health_sha256"] = hashlib.sha256(json_bytes).hexdigest()
    md = [
        f"# A-short sidecar health · {payload['as_of']}", "",
        f"overall={payload['overall']} · advanced={payload['advanced_count']} · stalled={payload['stalled_count']} · failed={payload['failed_count']} · partial={payload['partial_count']}", "",
        "| sidecar | execution | progress | decision/data through | error |", "|---|---|---|---|---|",
    ]
    for item in payload["sidecars"]:
        date = item.get("observed_decision_as_of") or item.get("observed_data_through") or "-"
        md.append(f"| {item['name']} | {item['execution_status']} | {item['progress_status']} | {date} | {item.get('error_code') or '-'} |")
    md_bytes = ("\n".join(md) + "\n").encode("utf-8")
    receipt_bytes = (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
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
    parser.add_argument("--weekly-receipt")
    parser.add_argument("--m67-status", choices=["complete", "failed", "skipped", "not_run"], default="not_run")
    args = parser.parse_args(argv)
    payload = build_health(
        as_of=args.as_of,
        launcher_manifest=_load_manifest(args.launcher_outcomes),
        pipeline_manifest=_load_manifest(args.pipeline_outcomes),
        project_root=Path(args.project_root).resolve(),
        m67_status=args.m67_status,
    )
    paths = write_health_bundle(payload, Path(args.out_dir).resolve(), Path(args.weekly_receipt).resolve() if args.weekly_receipt else None)
    print(f"[sidecar-health] overall={payload['overall']} failed={payload['failed_count']} stalled={payload['stalled_count']} partial={payload['partial_count']} -> {paths[1].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
