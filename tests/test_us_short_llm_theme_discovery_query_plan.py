"""Offline acceptance tests for the A1 query-plan contract."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from engine import us_short_llm_theme_discovery_query_plan as query_plan


DECISION_DATE = "20260808"
STAMP = "2026-08-02T12:00:00Z"


def _parent_queries() -> list[dict[str, str]]:
    return [
        {"query_id": "stage1-a", "query_text": "Find newly emerging demand shifts."},
        {"query_id": "stage1-b", "query_text": "Find new capacity commitments."},
    ]


def _envelopes() -> list[dict[str, int | str]]:
    return [
        {
            "provider": "web",
            "stage1_max_dispatch_count": 2,
            "stage2_max_dispatch_count": 2,
            "retry_max_dispatch_count": 1,
            "max_dispatch_count": 5,
        },
        {
            "provider": "xai",
            "stage1_max_dispatch_count": 1,
            "stage2_max_dispatch_count": 2,
            "retry_max_dispatch_count": 1,
            "max_dispatch_count": 4,
        },
    ]


def _stage1() -> dict:
    return {
        "schema_name": "us_short_llm_theme_discovery",
        "schema_version": "1.0.0",
        "generated_at": STAMP,
        "decision_clock": {
            "expected_decision_date": DECISION_DATE,
            "cutoff_policy": "before_decision_open_et",
            "pit_enforced": True,
        },
        "discovery_contract": {
            "producer_kind": "llm_theme_discovery",
            "input_mode": "offline_local_input",
            "membership_status": "provisional_unvalidated",
            "market_confirmation_status": "not_run",
            "scoring_eligible": False,
            "top15_effect_enabled": False,
            "operation_advice_effect_enabled": False,
            "dynamic_seats_enabled": False,
            "theme_probe_enabled": False,
            "lifecycle_actions_enabled": False,
        },
        "source_refs": [{
            "source_id": "web:source-1",
            "source_type": "web",
            "observed_at": STAMP,
        }],
        "themes": [{
            "theme_id": "new-demand",
            "display_name": "New demand",
            "summary": "A source-bound development.",
            "status": "provisional_discovered",
            "observed_at": STAMP,
            "source_ref_ids": ["web:source-1"],
            "members": [{
                "ticker": "AAPL",
                "membership_status": "provisional_unvalidated",
                "source_ref_ids": ["web:source-1"],
            }],
            "cross_industry_validation_status": "not_run",
            "market_confirmation_status": "not_run",
        }],
    }


class QueryPlanContractTests(unittest.TestCase):
    def _build_parent(self) -> dict:
        return query_plan.build_parent_plan(
            decision_date=DECISION_DATE,
            policy_version="soft_discovery_query_policy_v0.1.0",
            policy_template_content_sha256="a" * 64,
            stage1_queries=_parent_queries(),
            stage2_rule_sha256="b" * 64,
            provider_envelopes=_envelopes(),
            generated_at=STAMP,
        )

    def test_parent_identity_is_clock_free_and_envelope_sum_is_load_bearing(self):
        first = self._build_parent()
        second = query_plan.build_parent_plan(
            decision_date=DECISION_DATE,
            policy_version="soft_discovery_query_policy_v0.1.0",
            policy_template_content_sha256="a" * 64,
            stage1_queries=_parent_queries(),
            stage2_rule_sha256="b" * 64,
            provider_envelopes=_envelopes(),
            generated_at="2026-08-02T12:01:00Z",
        )
        self.assertEqual(first["plan_identity"], second["plan_identity"])
        self.assertEqual(first["canonical_plan_core"], second["canonical_plan_core"])
        broken = json.loads(json.dumps(first))
        broken["canonical_plan_core"]["provider_envelopes"][0]["max_dispatch_count"] += 1
        with self.assertRaises(query_plan.QueryPlanError):
            query_plan.validate_parent_plan(broken)

    def test_artifact_symlink_guard_runs_before_resolution(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            artifact = root / "fixture.json"
            artifact.write_text("{}", encoding="utf-8")
            with (
                mock.patch.object(Path, "is_symlink", return_value=True),
                mock.patch.object(Path, "resolve", side_effect=AssertionError("resolve must not run")),
            ):
                with self.assertRaisesRegex(query_plan.QueryPlanError, "may not be a symlink"):
                    query_plan._read_artifact(artifact, root=root)

    def test_stage2_binds_source_refs_and_does_not_rewrite_stage1(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state" / "us_short"
            state.mkdir(parents=True)
            parent = self._build_parent()
            parent_path = state / (
                f"us_short_llm_theme_discovery_query_plan_parent_{DECISION_DATE}_{parent['plan_identity']}.json"
            )
            query_plan.write_parent_plan(
                parent, parent_path, state_dir=state, root=root, gitignored=lambda _path: True,
            )
            stage1_path = root / "fixture" / "stage1.json"
            stage1_path.parent.mkdir()
            stage1_path.write_text(json.dumps(_stage1(), indent=2) + "\n", encoding="utf-8")
            before = stage1_path.read_bytes()
            stage2 = query_plan.build_stage2_plan(
                parent_plan=parent,
                parent_plan_path=parent_path,
                stage1_artifact_path=stage1_path,
                focus_terms=[{
                    "term": "AAPL", "term_type": "ticker", "source_ref_ids": ["web:source-1"],
                }],
                stage2_queries=[{
                    "query_id": "stage2-aapl",
                    "query_text": "Find the source-bound development for AAPL.",
                    "focus_term": "AAPL",
                    "focus_term_type": "ticker",
                    "source_ref_ids": ["web:source-1"],
                }],
                generated_at=STAMP,
                root=root,
            )
            stage2_path = state / (
                f"us_short_llm_theme_discovery_query_plan_stage2_{DECISION_DATE}_{stage2['plan_identity']}.json"
            )
            query_plan.write_stage2_plan(
                stage2, stage2_path, state_dir=state, root=root, gitignored=lambda _path: True,
            )

            def dispatch(stage: str, query_id: str, attempt: int = 1) -> dict[str, object]:
                return {
                    "sequence": 1, "event_id": f"{stage}-{query_id}-{attempt}", "stage": stage,
                    "provider": "web", "query_id": query_id, "event_type": "dispatch",
                    "attempt": attempt, "occurred_at": STAMP,
                }

            for events, expected in (
                ([dispatch("stage1", "stage1-a"), dispatch("stage1", "stage1-b"), dispatch("stage1", "stage1-c")],
                 "stage1_dispatch_count"),
                ([dispatch("stage2", "stage2-a"), dispatch("stage2", "stage2-b"), dispatch("stage2", "stage2-c")],
                 "stage2_dispatch_count"),
                ([dispatch("stage1", "stage1-a", 1), dispatch("stage1", "stage1-a", 2), dispatch("stage1", "stage1-a", 3)],
                 "retry_dispatch_count"),
            ):
                events = [dict(event, sequence=index + 1) for index, event in enumerate(events)]
                with self.assertRaisesRegex(query_plan.QueryPlanError, expected):
                    query_plan.build_consumption_ledger(
                        parent_plan=parent, parent_plan_path=parent_path,
                        stage2_plan=stage2, stage2_plan_path=stage2_path,
                        events=events, generated_at=STAMP, root=root,
                    )

            self.assertEqual(stage1_path.read_bytes(), before)
            self.assertTrue(stage2_path.is_file())
            bad = json.loads(json.dumps(stage2))
            bad["canonical_stage2_core"]["stage2_queries"][0]["source_ref_ids"] = ["web:foreign"]
            with self.assertRaises(query_plan.QueryPlanError):
                query_plan.validate_stage2_plan(bad)

            ghost_stage1 = _stage1()
            ghost_stage1["themes"][0]["source_ref_ids"] = ["web:ghost"]
            ghost_stage1["themes"][0]["members"][0]["source_ref_ids"] = ["web:ghost"]
            ghost_path = root / "fixture" / "stage1_ghost.json"
            ghost_path.write_text(json.dumps(ghost_stage1, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(query_plan.QueryPlanError, "present in Stage-1"):
                query_plan.build_stage2_plan(
                    parent_plan=parent,
                    parent_plan_path=parent_path,
                    stage1_artifact_path=ghost_path,
                    focus_terms=[{
                        "term": "AAPL", "term_type": "ticker", "source_ref_ids": ["web:ghost"],
                    }],
                    stage2_queries=[{
                        "query_id": "stage2-ghost",
                        "query_text": "Find the source-bound development for AAPL.",
                        "focus_term": "AAPL",
                        "focus_term_type": "ticker",
                        "source_ref_ids": ["web:ghost"],
                    }],
                    generated_at=STAMP,
                    root=root,
                )

    def test_consumption_ledger_and_receipt_bind_unknown_as_consumed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state" / "us_short"
            state.mkdir(parents=True)
            parent = self._build_parent()
            parent_path = state / (
                f"us_short_llm_theme_discovery_query_plan_parent_{DECISION_DATE}_{parent['plan_identity']}.json"
            )
            query_plan.write_parent_plan(
                parent, parent_path, state_dir=state, root=root, gitignored=lambda _path: True,
            )
            ledger = query_plan.build_consumption_ledger(
                parent_plan=parent,
                parent_plan_path=parent_path,
                events=[
                    {
                        "sequence": 1, "event_id": "event-1", "stage": "stage1", "provider": "web",
                        "query_id": "stage1-a", "event_type": "dispatch", "attempt": 1, "occurred_at": STAMP,
                    },
                    {
                        "sequence": 2, "event_id": "event-2", "stage": "stage1", "provider": "web",
                        "query_id": "stage1-a", "event_type": "unknown", "attempt": 1, "occurred_at": STAMP,
                    },
                ],
                generated_at=STAMP,
                status="inconclusive",
                root=root,
            )
            ledger_path = state / (
                f"us_short_llm_theme_discovery_query_plan_{DECISION_DATE}_{parent['plan_identity']}_consumption.json"
            )
            with mock.patch.object(query_plan, "mutable_ledger_lock") as lock:
                query_plan.write_consumption_ledger(
                    ledger, ledger_path, state_dir=state, root=root, gitignored=lambda _path: True,
                )
            lock.assert_called_once_with(ledger_path)
            receipt = query_plan.build_execution_receipt(
                ledger=ledger, ledger_path=ledger_path, status="inconclusive",
                provider_calls_performed=False, generated_at=STAMP, root=root,
            )
            receipt_path = state / (
                f"us_short_llm_theme_discovery_query_plan_{DECISION_DATE}_{parent['plan_identity']}_execution_receipt.json"
            )
            query_plan.write_execution_receipt(
                receipt, receipt_path, state_dir=state, root=root, gitignored=lambda _path: True,
            )
            self.assertEqual(receipt["unknown_dispatch_count"], 1)
            self.assertEqual(receipt["replay_policy"], "unknown_dispatches_are_consumed_no_auto_replay")
            self.assertTrue(receipt_path.is_file())
            self.assertEqual(
                json.loads(ledger_path.read_text(encoding="utf-8"))["mutable"], True,
            )
            bad_totals = json.loads(json.dumps(ledger))
            bad_totals["provider_totals"][0]["unknown_count"] = 0
            with self.assertRaises(query_plan.QueryPlanError):
                query_plan.validate_consumption_ledger(bad_totals)
            bad_receipt = json.loads(json.dumps(receipt))
            bad_receipt["provider_calls_performed"] = True
            with self.assertRaises(query_plan.QueryPlanError):
                query_plan.validate_execution_receipt(bad_receipt)

    def test_stage2_requires_a_frozen_parent_and_foreign_terminal_event_is_rejected(self):
        parent = self._build_parent()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state" / "us_short"
            state.mkdir(parents=True)
            parent_path = state / (
                f"us_short_llm_theme_discovery_query_plan_parent_{DECISION_DATE}_{parent['plan_identity']}.json"
            )
            with self.assertRaises(query_plan.QueryPlanError):
                query_plan.build_consumption_ledger(
                    parent_plan=parent, parent_plan_path=parent_path,
                    events=[{
                        "sequence": 1, "event_id": "event-1", "stage": "stage1", "provider": "web",
                        "query_id": "stage1-a", "event_type": "completion", "attempt": 1, "occurred_at": STAMP,
                    }], generated_at=STAMP, root=root,
                )


if __name__ == "__main__":
    unittest.main()
