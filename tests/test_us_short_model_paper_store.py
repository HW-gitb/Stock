from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from engine.us_short_model_paper_portfolio import (
    artifact_sha256,
    build_nav_snapshot,
    canonical_json_bytes,
    seed_portfolio_state,
    settle_decision_bundle,
)
from engine.us_short_model_paper_store import (
    ModelPaperStoreError,
    commit_settlement,
    freeze_decision_bundle,
    initialize_store,
    load_current_state,
    load_head,
)
from tests.test_us_short_model_paper_portfolio import _bar, _decision, _order, _packet


class ModelPaperStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "model_paper_private"
        self.seed = seed_portfolio_state("20260717")
        self.seed_nav = build_nav_snapshot(
            self.seed,
            {"paper_evaluable": False, "status": "not_evaluable", "degradation_reasons": ["seed_state"], "source_sha256": None},
        )
        initialize_store(self.root, self.seed, self.seed_nav)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _mature(self, decision: dict | None = None) -> tuple[dict, dict, dict, dict]:
        chosen = decision or _decision(self.seed, [_order()])
        packet = _packet({"ABC": [_bar("20260720", 10.1, 10.2, 9.8, 10.1)]}, "20260720")
        settlement, state, nav = settle_decision_bundle(self.seed, chosen, packet, "20260720")
        return chosen, settlement, state, nav

    def test_initialize_freeze_commit_and_idempotent_reread(self) -> None:
        decision, settlement, state, nav = self._mature()
        self.assertEqual("frozen", freeze_decision_bundle(self.root, decision))
        self.assertEqual("idempotent", freeze_decision_bundle(self.root, decision))
        self.assertEqual("committed", commit_settlement(self.root, decision, settlement, state, nav))
        self.assertEqual("idempotent", commit_settlement(self.root, decision, settlement, state, nav))
        self.assertEqual(state, load_current_state(self.root))
        head = load_head(self.root)
        self.assertIsNone(head["pending_decision"])
        self.assertEqual(artifact_sha256(state), head["current_state"]["sha256"])

    def test_pending_same_day_decision_can_be_superseded_but_matured_decision_is_immutable(self) -> None:
        first = _decision(self.seed, [_order()])
        freeze_decision_bundle(self.root, first)
        second = copy.deepcopy(first)
        second["orders"][0]["limit_order_price"] = 10.1
        second["supersedes_sha256"] = artifact_sha256(first)
        self.assertEqual("superseded", freeze_decision_bundle(self.root, second))
        chosen, settlement, state, nav = self._mature(second)
        commit_settlement(self.root, chosen, settlement, state, nav)
        third = copy.deepcopy(second)
        third["orders"][0]["limit_order_price"] = 10.0
        third["supersedes_sha256"] = artifact_sha256(second)
        with self.assertRaisesRegex(ModelPaperStoreError, "matured decision is immutable"):
            freeze_decision_bundle(self.root, third)

    def test_partial_publish_recovers_without_mixed_head(self) -> None:
        decision, settlement, state, nav = self._mature()
        freeze_decision_bundle(self.root, decision)
        from engine import us_short_model_paper_store as store

        real_replace = store._replace_path
        calls = 0

        def fail_second_result(source: Path, destination: Path) -> None:
            nonlocal calls
            if destination.name in {"settlement.json", "portfolio_state.json", "nav_snapshot.json"}:
                calls += 1
                if calls == 2:
                    raise OSError("injected crash")
            real_replace(source, destination)

        with mock.patch.object(store, "_replace_path", side_effect=fail_second_result):
            with self.assertRaisesRegex(ModelPaperStoreError, "transaction publish failed"):
                commit_settlement(self.root, decision, settlement, state, nav)
        head = load_head(self.root)
        self.assertIsNotNone(head["pending_decision"])
        self.assertEqual("committed", commit_settlement(self.root, decision, settlement, state, nav))
        self.assertEqual(state, load_current_state(self.root))

    def test_existing_artifact_tamper_is_rejected(self) -> None:
        decision, settlement, state, nav = self._mature()
        freeze_decision_bundle(self.root, decision)
        commit_settlement(self.root, decision, settlement, state, nav)
        state_path = self.root / "weeks" / decision["decision_date"] / "portfolio_state.json"
        data = json.loads(state_path.read_text(encoding="utf-8"))
        data["cash"] = "1.000000"
        state_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ModelPaperStoreError, "digest mismatch|not byte-canonical"):
            load_current_state(self.root)

    def test_wrong_prior_state_binding_is_rejected_before_write(self) -> None:
        decision = _decision(self.seed, [_order()])
        decision["prior_state_sha256"] = "f" * 64
        with self.assertRaisesRegex(ModelPaperStoreError, "prior_state_sha256"):
            freeze_decision_bundle(self.root, decision)

    def test_store_rejects_settlement_that_does_not_cover_decision_actions(self) -> None:
        decision, settlement, state, nav = self._mature()
        freeze_decision_bundle(self.root, decision)
        forged = copy.deepcopy(settlement)
        forged["order_outcomes"][0]["final_action"] = "观察"
        with self.assertRaisesRegex(ModelPaperStoreError, "do not exactly cover decision orders"):
            commit_settlement(self.root, decision, forged, state, nav)

    def test_head_binds_matured_decision_and_price_packet_digests(self) -> None:
        decision, settlement, state, nav = self._mature()
        freeze_decision_bundle(self.root, decision)
        commit_settlement(self.root, decision, settlement, state, nav)
        head_path = self.root / "head_manifest.json"
        head = json.loads(head_path.read_text(encoding="utf-8"))
        head["last_settlement"]["decision_sha256"] = "f" * 64
        head_path.write_bytes(canonical_json_bytes(head))
        with self.assertRaisesRegex(ModelPaperStoreError, "decision/settlement digest mismatch"):
            load_head(self.root)

    def test_unignored_repo_destination_is_rejected(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        unignored = repo_root / "model_paper_should_not_write"
        with self.assertRaisesRegex(Exception, "private"):
            initialize_store(unignored, self.seed, self.seed_nav)
        self.assertFalse(unignored.exists())


if __name__ == "__main__":
    unittest.main()
