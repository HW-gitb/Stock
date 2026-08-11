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
import sys
from pathlib import Path
from typing import Any, Callable

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


def _status(value: Any, *, revision: str) -> dict[str, Any]:
    result = {"status": "unavailable", "official_revision_id": revision}
    if isinstance(value, dict):
        result["status"] = str(value.get("status") or "unavailable")
        observed = value.get("official_revision_id")
        if observed not in (None, ""):
            result["official_revision_id"] = str(observed)
    return result


def _optional_call(label: str, revision: str, callback: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"track": label, **_status(callback(), revision=revision)}
    except ImportError:
        return {"track": label, "status": "unavailable", "official_revision_id": revision,
                "error_code": "module_unavailable"}
    except Exception as exc:  # comparison-only sidecar: M6.7 remains authoritative
        return {"track": label, "status": "unavailable", "official_revision_id": revision,
                "error_code": "settlement_unavailable",
                "error_type": type(exc).__name__}


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
        return settle_and_summarize_v2_weekly(
            root=factor_root, daily_cache_path=cache, as_of=date,
            run_revision_id=revision, official_project_root=root,
        )

    def margin() -> Any:
        from engine.a_short_margin_overheat_cash_control import settle_and_summarize_margin_overheat_weekly
        return settle_and_summarize_margin_overheat_weekly(
            root=margin_root, daily_cache_path=cache, as_of=date, strict=True,
            run_revision_id=revision, official_project_root=root,
        )

    def industry() -> Any:
        from engine.a_short_industry_weight_comparison import settle_and_summarize_weekly
        return settle_and_summarize_weekly(
            root=industry_root, daily_cache_path=cache, as_of=date,
            public_json_path=public_root / "industry_weight_comparison_summary.json",
            public_markdown_path=public_root / "industry_weight_comparison_summary.md",
            write_public=True, strict=True, run_revision_id=revision,
            official_project_root=root,
        )

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
        return settle_and_summarize_weekly(
            root=overlay_root, daily_cache_path=cache, as_of=date,
            public_json_path=public_root / "overlay_adjudication_summary.json",
            public_markdown_path=public_root / "overlay_adjudication_summary.md",
            write_public=True, strict=True, run_revision_id=revision,
            official_project_root=root,
        )

    for label, callback in (
        ("factor_v2_settlement", factor),
        ("margin_overheat_settlement", margin),
        ("industry_weight_settlement", industry),
        ("target_policy_settlement", target),
        ("final_action_settlement", final_action),
        ("official_operation_settlement", operation),
        ("overlay_settlement", overlay),
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

        tracks.append(_optional_call("forward_backfill", revision, forward_backfill))

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

        tracks.append(_optional_call("theme_forward_settlement", revision, theme))

        def crash() -> Any:
            from runners.a_short_crash_veto_tracker import settle_existing
            return settle_existing(
                as_of=date,
                state_path=root / "logs" / "a_short_crash_veto_tracker.json",
                summary_path=root / "logs" / "a_short_crash_veto_summary.json",
                price_path=root / "logs" / "a_short_crash_veto_prices.pkl",
                run_revision_id=revision, official_project_root=root,
            )

        tracks.append(_optional_call("crash_veto_settlement", revision, crash))

    return {
        "status": "settled",
        "decision_as_of": date,
        "official_revision_id": revision,
        "formal_count": 1,
        "tracks": tracks,
        "official_root": str(official_public_revision_root(root, date, revision)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A-short post-selector official settlement")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--run-revision-id")
    parser.add_argument("--skip-forward", action="store_true")
    args = parser.parse_args(argv)
    result = settle_official_revision(
        project_root=args.project_root, as_of=args.as_of,
        run_revision_id=args.run_revision_id, include_forward=not args.skip_forward,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
