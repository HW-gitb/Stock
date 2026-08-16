"""Focused tests for the post-selector official settlement outcome boundary."""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import jsonschema

from engine.a_short_run_revision import RevisionError
from runners.a_short_official_settlement import (
    OFFICIAL_SETTLEMENT_SIDECARS,
    OUTCOME_SCHEMA,
    _official_outcome_row,
    settle_official_revision,
)


DATE = "20260816"
REVISION = "a" * 32


def _callback_values(*, failing: str | None = None) -> dict[str, object]:
    return {
        "operation": RuntimeError("settlement failed") if failing == "operation" else {
            "status": "settled_from_existing_shared_cache",
            "outcomes_updated": 0,
        },
        "factor": RuntimeError("settlement failed") if failing == "factor" else {
            "status": "evidence_unavailable_or_inconclusive",
            "_official_settlement_class": "no_official_captures",
            "outcomes_updated": 0,
        },
        "margin": RuntimeError("settlement failed") if failing == "margin" else {
            "status": "evidence_unavailable_or_inconclusive",
            "_official_settlement_class": "no_official_captures",
            "outcomes_updated": 0,
        },
        "industry": RuntimeError("settlement failed") if failing == "industry" else {
            "status": "accumulating", "outcomes_updated": 0,
        },
        "target": RuntimeError("settlement failed") if failing == "target" else {
            "status": "review_pass_pending_confirmation", "outcomes_updated": 0,
        },
        "final": RuntimeError("settlement failed") if failing == "final" else {
            "status": "review_due", "outcomes_updated": 0,
        },
        "overlay": RuntimeError("settlement failed") if failing == "overlay" else {
            "status": "manual_promotion_candidate", "outcomes_updated": 0,
        },
        "crash": RuntimeError("settlement failed") if failing == "crash" else {
            "status": "settled", "progress_status": "already_current",
        },
    }


def _patched_callbacks(stack: ExitStack, *, failing: str | None = None) -> None:
    values = _callback_values(failing=failing)
    for target, key in (
        ("runners.a_short_official_operation_evidence.settle_and_summarize", "operation"),
        ("engine.a_short_factor_comparison_v2_weekly.settle_and_summarize_v2_weekly", "factor"),
        ("engine.a_short_margin_overheat_cash_control.settle_and_summarize_margin_overheat_weekly", "margin"),
        ("engine.a_short_industry_weight_comparison.settle_and_summarize_weekly", "industry"),
        ("runners.a_short_target_policy_comparison_runner.settle_and_summarize", "target"),
        ("runners.a_short_final_action_validation_runner.settle_and_summarize", "final"),
        ("engine.a_short_overlay_adjudication.settle_and_summarize_weekly", "overlay"),
        ("runners.a_short_crash_veto_tracker.settle_existing", "crash"),
    ):
        value = values[key]
        def callback(*args, _value=value, _key=key, **kwargs):
            if isinstance(_value, BaseException):
                raise _value
            if _key in {"factor", "margin", "industry", "overlay"}:
                carrier = kwargs.get("sidecar_result")
                if carrier is not None and _value.get("_official_settlement_class") == "no_official_captures":
                    carrier["official_settlement_status"] = "no_official_captures"
            return _value
        stack.enter_context(patch(target, side_effect=callback))
    def forward_callback(*args, **kwargs):
        kwargs["sidecar_result"]["outcomes_updated"] = 0
        return 0

    def theme_callback(*args, **kwargs):
        kwargs["sidecar_result"]["progress_status"] = "already_current"
        return 0

    stack.enter_context(patch("runners.forward_tracker.backfill", side_effect=forward_callback))
    stack.enter_context(patch("runners.a_short_theme_forward_comparison.main", side_effect=theme_callback))


class OfficialSettlementOutcomeTests(unittest.TestCase):
    def _run(self, *, failing: str | None = None, outcomes_path: Path) -> dict:
        with ExitStack() as stack:
            _patched_callbacks(stack, failing=failing)
            stack.enter_context(patch(
                "runners.a_short_official_settlement.require_official_revision",
                return_value=None,
            ))
            return settle_official_revision(
                project_root=outcomes_path.parent,
                as_of=DATE,
                run_revision_id=REVISION,
                outcomes_path=outcomes_path,
            )

    def test_successful_callbacks_write_exact_ten_settled_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "official_settlement_outcomes.json"
            result = self._run(outcomes_path=path)
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "settled")
        self.assertEqual([row["name"] for row in payload["sidecars"]], list(OFFICIAL_SETTLEMENT_SIDECARS))
        self.assertEqual(len({row["name"] for row in payload["sidecars"]}), 10)
        jsonschema.validate(payload, json.loads(OUTCOME_SCHEMA.read_text(encoding="utf-8")))
        self.assertTrue(all(row["execution_status"] == "succeeded" for row in payload["sidecars"]))

    def test_terminal_status_allowlist_and_no_evidence_marker_are_narrow(self):
        for status in (
            "manual_promotion_candidate", "do_not_promote", "retired_for_epoch",
            "preliminary_review", "review_pass_pending_confirmation",
        ):
            row = _official_outcome_row({"track": "x", "status": status, "outcomes_updated": 0})
            self.assertEqual(row["execution_status"], "succeeded")
        marked = _official_outcome_row({
            "track": "x", "status": "evidence_unavailable_or_inconclusive",
            "official_settlement_class": "no_official_captures",
        })
        self.assertEqual(marked["execution_status"], "succeeded")
        self.assertEqual(marked["progress_status"], "not_applicable")
        unmarked = _official_outcome_row({
            "track": "x", "status": "evidence_unavailable_or_inconclusive",
        })
        self.assertEqual(unmarked["execution_status"], "failed")
        self.assertEqual(unmarked["error_code"], "settlement_unavailable")

    def test_structured_update_delta_controls_official_progress(self):
        self.assertEqual(
            _official_outcome_row({
                "track": "x", "status": "settled", "outcomes_updated": 0,
            })["progress_status"],
            "already_current",
        )
        self.assertEqual(
            _official_outcome_row({
                "track": "x", "status": "settled", "outcomes_updated": 2,
            })["progress_status"],
            "advanced",
        )
        missing = _official_outcome_row({"track": "x", "status": "settled"})
        self.assertEqual(missing["execution_status"], "failed")
        self.assertEqual(missing["progress_status"], "unavailable")
        negative = _official_outcome_row({
            "track": "x", "status": "settled", "outcomes_updated": -1,
        })
        self.assertEqual(negative["execution_status"], "failed")
        self.assertEqual(negative["progress_status"], "unavailable")
        conflict = _official_outcome_row({
            "track": "x", "status": "settled", "outcomes_updated": 0,
            "progress_status": "advanced",
        })
        self.assertEqual(conflict["execution_status"], "failed")
        self.assertEqual(conflict["progress_status"], "unavailable")

    def test_one_callback_failure_is_degraded_but_keeps_the_other_nine_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "official_settlement_outcomes.json"
            result = self._run(failing="factor", outcomes_path=path)
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "degraded")
        failed = next(row for row in payload["sidecars"] if row["name"] == "factor_v2_settlement")
        self.assertEqual(failed["execution_status"], "failed")
        self.assertEqual(failed["progress_status"], "unavailable")
        self.assertEqual(failed["error_code"], "settlement_unavailable")
        self.assertEqual(sum(row["execution_status"] == "failed" for row in payload["sidecars"]), 1)

    def test_resolver_failure_is_hard_and_does_not_leave_an_outcome_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "official_settlement_outcomes.json"
            with patch(
                "runners.a_short_official_settlement.require_official_revision",
                side_effect=RevisionError("official revision mismatch"),
            ), self.assertRaises(RevisionError):
                settle_official_revision(
                    project_root=Path(tmp), as_of=DATE,
                    run_revision_id=REVISION, outcomes_path=path,
                )
            self.assertFalse(path.exists())

    def test_consumer_revision_mismatch_is_hard_and_does_not_write_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "official_settlement_outcomes.json"
            with ExitStack() as stack:
                _patched_callbacks(stack)
                stack.enter_context(patch(
                    "runners.a_short_official_settlement.require_official_revision",
                    return_value=None,
                ))
                stack.enter_context(patch(
                    "runners.a_short_official_operation_evidence.settle_and_summarize",
                    return_value={"status": "settled", "official_revision_id": "b" * 32},
                ))
                with self.assertRaises(RevisionError):
                    settle_official_revision(
                        project_root=Path(tmp), as_of=DATE,
                        run_revision_id=REVISION, outcomes_path=path,
                    )
            self.assertFalse(path.exists())

    def test_schema_or_write_failure_is_hard_and_does_not_leave_a_half_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "official_settlement_outcomes.json"
            with ExitStack() as stack:
                _patched_callbacks(stack)
                stack.enter_context(patch(
                    "runners.a_short_official_settlement.require_official_revision",
                    return_value=None,
                ))
                stack.enter_context(patch(
                    "runners.a_short_official_settlement._official_outcomes_payload",
                    side_effect=ValueError("schema rejected"),
                ))
                with self.assertRaises(ValueError):
                    settle_official_revision(
                        project_root=Path(tmp), as_of=DATE,
                        run_revision_id=REVISION, outcomes_path=path,
                    )
            self.assertFalse(path.exists())

            with ExitStack() as stack:
                _patched_callbacks(stack)
                stack.enter_context(patch(
                    "runners.a_short_official_settlement.require_official_revision",
                    return_value=None,
                ))
                stack.enter_context(patch(
                    "runners.a_short_official_settlement._write_official_outcomes",
                    side_effect=OSError("write rejected"),
                ))
                with self.assertRaises(OSError):
                    settle_official_revision(
                        project_root=Path(tmp), as_of=DATE,
                        run_revision_id=REVISION, outcomes_path=path,
                    )
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
