"""Post-selector, cache-only settlement for the A-short official revision.

The weekly pipeline captures comparison evidence before the official pointer
exists.  This runner is the only production caller that settles public
comparison summaries: it is invoked after ``select-official`` has returned
``selected``/``already_current`` and therefore passes the selected revision
through every formal consumer.  A missing pointer is an audit-only legacy
state, not an error that can stop a historical week.

No provider, token, or new fetch seam is used here.  Optional comparison
modules degrade to an unavailable status; an official resolver mismatch is
the sole hard failure because it would otherwise permit cross-revision
counting.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.a_short_run_revision import (
    RevisionError,
    official_public_revision_root,
    require_official_revision,
    resolve_official_revision,
    validate_decision_as_of,
    validate_run_revision_id,
)

OUTCOME_SCHEMA = ROOT / "schemas" / "a_short_weekly_sidecar_outcomes.schema.json"
OFFICIAL_SETTLEMENT_SIDECARS = (
    "official_operation_settlement",
    "factor_v2_settlement",
    "margin_overheat_cash_control_settlement",
    "industry_weight_settlement",
    "target_policy_settlement",
    "final_action_settlement",
    "overlay_adjudication_settlement",
    "forward_tracker_official_settlement",
    "theme_forward_official_settlement",
    "crash_veto_official_settlement",
)
_OFFICIAL_SUCCESS_STATUSES = frozenset({
    "advanced", "complete", "settled", "settled_from_existing_cache",
    "settled_from_existing_shared_cache", "updated", "written",
    "manual_promotion_candidate", "do_not_promote", "retired_for_epoch",
    "preliminary_review", "review_pass_pending_confirmation",
})
_OFFICIAL_ALREADY_CURRENT_STATUSES = frozenset({
    "already_current", "already_frozen", "accumulating", "evidence_current",
    "idempotent", "idempotent_existing_capture", "review_due",
})
_OFFICIAL_NOT_APPLICABLE_STATUSES = frozenset({
    "pending", "no_count",
})
_OFFICIAL_NO_EVIDENCE_CLASS = "no_official_captures"


def _status(value: Any, *, revision: str) -> dict[str, Any]:
    result = {"status": "unavailable", "official_revision_id": revision}
    if isinstance(value, dict):
        result["status"] = str(value.get("status") or "unavailable")
        if value.get("_official_settlement_class") not in (None, ""):
            result["official_settlement_class"] = str(value["_official_settlement_class"])
        observed = value.get("official_revision_id")
        if observed not in (None, ""):
            observed = str(observed)
            if observed != revision:
                raise RevisionError("official settlement consumer returned a different revision")
            result["official_revision_id"] = observed
    return result


def _mark_official_no_evidence(value: Any, carrier: dict[str, Any]) -> Any:
    """Carry only a real inner no-capture result into the private status map."""
    if carrier.get("official_settlement_status") != _OFFICIAL_NO_EVIDENCE_CLASS:
        return value
    if not isinstance(value, dict):
        return value
    marked = dict(value)
    marked["_official_settlement_class"] = _OFFICIAL_NO_EVIDENCE_CLASS
    return marked


def _optional_call(label: str, revision: str, callback: Callable[[], Any]) -> dict[str, Any]:
    try:
        value = callback()
    except ImportError:
        return {"track": label, "status": "unavailable", "official_revision_id": revision,
                "error_code": "module_unavailable"}
    except RevisionError:
        raise
    except Exception as exc:  # comparison-only sidecar: M6.7 remains authoritative
        return {"track": label, "status": "unavailable", "official_revision_id": revision,
                "error_code": "settlement_unavailable",
                "error_type": type(exc).__name__}
    return {"track": label, **_status(value, revision=revision)}


def _official_outcome_row(track: dict[str, Any], *, attempted: bool = True) -> dict[str, Any]:
    """Project one optional callback into the existing closed outcome schema."""
    name = str(track.get("track") or "")
    status = str(track.get("status") or "")
    error_code = track.get("error_code")
    error_detail = None
    if track.get("error_type"):
        error_detail = f"error_type={track['error_type']}"
    if status == "not_configured":
        execution_status, progress_status = "not_configured", "not_applicable"
    elif status == "not_due":
        execution_status, progress_status = "not_due", "not_applicable"
    elif (track.get("official_settlement_class") == _OFFICIAL_NO_EVIDENCE_CLASS and
          status == "evidence_unavailable_or_inconclusive"):
        execution_status, progress_status = "succeeded", "not_applicable"
    elif status in _OFFICIAL_NOT_APPLICABLE_STATUSES:
        execution_status, progress_status = "succeeded", "not_applicable"
    elif status in _OFFICIAL_ALREADY_CURRENT_STATUSES:
        execution_status, progress_status = "succeeded", "already_current"
    elif status in _OFFICIAL_SUCCESS_STATUSES:
        execution_status, progress_status = "succeeded", "advanced"
    else:
        execution_status, progress_status = "failed", "unavailable"
        error_code = str(error_code or (
            "settlement_unavailable" if status in {
                "", "unavailable", "evidence_unavailable_or_inconclusive",
            } else "unexpected_settlement_status"
        ))
        error_detail = error_detail or f"status={status or 'missing'}"
    row = {
        "name": name,
        "expected": True,
        "attempted": bool(attempted),
        "execution_status": execution_status,
        "progress_status": progress_status,
    }
    if error_code not in (None, ""):
        row["error_code"] = str(error_code)
    if error_detail not in (None, ""):
        row["error_detail"] = str(error_detail)[:512]
    return row


def _official_outcomes_payload(*, as_of: str, revision: str,
                               tracks: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [_official_outcome_row(track, attempted=track.get("attempted", True)) for track in tracks]
    payload = {
        "schema_name": "a_short_weekly_sidecar_outcomes",
        "schema_version": "1.0.0",
        "as_of": as_of,
        "run_revision_id": revision,
        "run_id": None,
        "candidate_digest": None,
        "expected_sidecars": list(OFFICIAL_SETTLEMENT_SIDECARS),
        "sidecars": rows,
    }
    jsonschema.validate(payload, json.loads(OUTCOME_SCHEMA.read_text(encoding="utf-8")))
    if [row["name"] for row in rows] != list(OFFICIAL_SETTLEMENT_SIDECARS):
        raise RevisionError("official settlement outcomes have an unexpected track set")
    return payload


def _write_official_outcomes(payload: dict[str, Any], path: str | Path) -> Path:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, target)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return target


def _legacy_result(project_root: Path, as_of: str, revision: str | None) -> dict[str, Any]:
    """Return the explicit no-pointer legacy boundary without hard failing."""
    if revision is not None:
        raise RevisionError("official settlement requires a selected revision")
    selected = resolve_official_revision(project_root, as_of, require=False)
    if selected is not None:
        raise RevisionError("official settlement revision is required when a pointer exists")
    return {
        "status": "legacy_audit_only",
        "decision_as_of": as_of,
        "official_revision_id": None,
        "formal_count": 0,
        "message": "No official pointer; legacy evidence is retained for audit and excluded from formal counts.",
        "tracks": [],
    }


def settle_official_revision(
    *, project_root: str | Path,
    as_of: str,
    run_revision_id: str | None,
    include_forward: bool = True,
    outcomes_path: str | Path | None = None,
) -> dict[str, Any]:
    """Settle all available official consumers for one selected revision."""
    root = Path(project_root).resolve()
    date = validate_decision_as_of(as_of)
    revision = validate_run_revision_id(run_revision_id) if run_revision_id is not None else None
    if revision is None:
        return _legacy_result(root, date, None)
    # This is intentionally the hard gate.  It is called only after selector
    # success by the launcher; a stale/equivalent/validation revision cannot
    # enter a formal consumer by merely supplying its own id.
    require_official_revision(root, date, revision)

    cache = root / "state" / "a_short" / "factor_comparison_private" / "v2" / "daily_cache.json"
    tracks: list[dict[str, Any]] = []
    factor_root = root / "state" / "a_short" / "factor_comparison_private" / "v2"
    margin_root = root / "state" / "a_short" / "margin_overheat_cash_control_private" / "v1"
    industry_root = root / "state" / "a_short" / "industry_weight_comparison_private" / "v1"
    overlay_root = root / "state" / "a_short" / "overlay_adjudication_private" / "v1"
    operation_root = root / "state" / "a_short" / "operation_evidence_private" / "v1"
    target_root = root / "logs" / "a_short_target_policy_comparison.json"
    final_root = root / "logs" / "a_short_final_action_validation.json"
    public_root = root / "research" / "results" / "a_short"

    def factor() -> Any:
        from engine.a_short_factor_comparison_v2_weekly import settle_and_summarize_v2_weekly
        carrier: dict[str, Any] = {}
        value = settle_and_summarize_v2_weekly(
            root=factor_root, daily_cache_path=cache, as_of=date,
            run_revision_id=revision, official_project_root=root,
            sidecar_result=carrier,
        )
        return _mark_official_no_evidence(value, carrier)

    def margin() -> Any:
        from engine.a_short_margin_overheat_cash_control import settle_and_summarize_margin_overheat_weekly
        carrier: dict[str, Any] = {}
        value = settle_and_summarize_margin_overheat_weekly(
            root=margin_root, daily_cache_path=cache, as_of=date, strict=True,
            run_revision_id=revision, official_project_root=root,
            sidecar_result=carrier,
        )
        return _mark_official_no_evidence(value, carrier)

    def industry() -> Any:
        from engine.a_short_industry_weight_comparison import settle_and_summarize_weekly
        carrier: dict[str, Any] = {}
        value = settle_and_summarize_weekly(
            root=industry_root, daily_cache_path=cache, as_of=date,
            public_json_path=public_root / "industry_weight_comparison_summary.json",
            public_markdown_path=public_root / "industry_weight_comparison_summary.md",
            write_public=True, strict=True, run_revision_id=revision,
            official_project_root=root, sidecar_result=carrier,
        )
        return _mark_official_no_evidence(value, carrier)

    def target() -> Any:
        from runners.a_short_target_policy_comparison_runner import settle_and_summarize
        return settle_and_summarize(
            root=target_root, as_of=date, daily_cache_path=cache,
            summary_path=public_root / "target_policy_comparison_summary.json",
            markdown_path=public_root / "target_policy_comparison_summary.md",
            write_public=True, run_revision_id=revision, official_project_root=root,
        )

    def final_action() -> Any:
        from runners.a_short_final_action_validation_runner import settle_and_summarize
        return settle_and_summarize(
            root=final_root, as_of=date,
            tracker_path=root / "logs" / "forward_tracker.csv", daily_cache_path=cache,
            summary_path=public_root / "final_action_validation_summary.json",
            markdown_path=public_root / "final_action_validation_summary.md",
            write_public=True, run_revision_id=revision, official_project_root=root,
        )

    def operation() -> Any:
        from runners.a_short_official_operation_evidence import settle_and_summarize
        return settle_and_summarize(
            root=operation_root, as_of=date, daily_cache_path=cache,
            public_json_path=public_root / "official_operation_evidence_summary.json",
            public_markdown_path=public_root / "official_operation_evidence_summary.md",
            run_revision_id=revision, official_project_root=root,
        )

    def overlay() -> Any:
        from engine.a_short_overlay_adjudication import settle_and_summarize_weekly
        carrier: dict[str, Any] = {}
        value = settle_and_summarize_weekly(
            root=overlay_root, daily_cache_path=cache, as_of=date,
            public_json_path=public_root / "overlay_adjudication_summary.json",
            public_markdown_path=public_root / "overlay_adjudication_summary.md",
            write_public=True, strict=True, run_revision_id=revision,
            official_project_root=root, sidecar_result=carrier,
        )
        return _mark_official_no_evidence(value, carrier)

    for label, callback in (
        ("official_operation_settlement", operation),
        ("factor_v2_settlement", factor),
        ("margin_overheat_cash_control_settlement", margin),
        ("industry_weight_settlement", industry),
        ("target_policy_settlement", target),
        ("final_action_settlement", final_action),
        ("overlay_adjudication_settlement", overlay),
    ):
        tracks.append(_optional_call(label, revision, callback))

    if include_forward:
        def forward_backfill() -> Any:
            from runners.forward_tracker import backfill
            exit_code = backfill(
                [5, 10, 20], run_revision_id=revision, official_project_root=root,
            )
            if exit_code != 0:
                raise RuntimeError(f"forward_backfill_exit_{exit_code}")
            return {"status": "settled"}

        tracks.append(_optional_call("forward_tracker_official_settlement", revision, forward_backfill))

        def theme() -> Any:
            from runners.a_short_theme_forward_comparison import main as theme_main
            output = root / "research" / "results" / "a_short_theme_forward_comparison.json"
            private = root / "state" / "a_short" / "theme_forward_comparison_private" / "v1"
            exit_code = theme_main([
                "--tracker", str(root / "logs" / "forward_tracker.csv"),
                "--out", str(output), "--private-root", str(private),
                "--run-revision-id", revision, "--official-project-root", str(root),
            ])
            if exit_code not in (None, 0):
                raise RuntimeError(f"theme_exit_{exit_code}")
            return {"status": "settled"}

        tracks.append(_optional_call("theme_forward_official_settlement", revision, theme))

        def crash() -> Any:
            from runners.a_short_crash_veto_tracker import settle_existing
            return settle_existing(
                as_of=date,
                state_path=root / "logs" / "a_short_crash_veto_tracker.json",
                summary_path=root / "logs" / "a_short_crash_veto_summary.json",
                price_path=root / "logs" / "a_short_crash_veto_prices.pkl",
                run_revision_id=revision, official_project_root=root,
            )

        tracks.append(_optional_call("crash_veto_official_settlement", revision, crash))
    else:
        for label in OFFICIAL_SETTLEMENT_SIDECARS[7:]:
            tracks.append({
                "track": label, "status": "not_due", "attempted": False,
                "official_revision_id": revision,
            })

    outcomes = _official_outcomes_payload(as_of=date, revision=revision, tracks=tracks)
    if outcomes_path is not None:
        _write_official_outcomes(outcomes, outcomes_path)
    overall_status = "degraded" if any(
        row["execution_status"] == "failed" for row in outcomes["sidecars"]
    ) else "settled"

    return {
        "status": overall_status,
        "decision_as_of": date,
        "official_revision_id": revision,
        "formal_count": 1,
        "tracks": tracks,
        "outcomes_path": str(Path(outcomes_path).resolve()) if outcomes_path is not None else None,
        "official_root": str(official_public_revision_root(root, date, revision)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A-short post-selector official settlement")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--run-revision-id")
    parser.add_argument("--skip-forward", action="store_true")
    parser.add_argument("--outcomes", required=True)
    args = parser.parse_args(argv)
    result = settle_official_revision(
        project_root=args.project_root, as_of=args.as_of,
        run_revision_id=args.run_revision_id, include_forward=not args.skip_forward,
        outcomes_path=args.outcomes,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
