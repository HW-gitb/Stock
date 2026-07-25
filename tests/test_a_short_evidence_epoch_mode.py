"""Guards for the pre-freeze evidence mode shared by every A-short comparison track.

The bug this locks down: each track's epoch fingerprint hashed whole
implementation files, so an edit unrelated to any comparison contract silently
dropped every accumulated week.  While the design is unfrozen the fingerprints
must be stable constants, and no track may reach a verdict on evidence that
does not count.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import a_short_evidence_epoch_mode as epoch_mode  # noqa: E402

# Files bound by several tracks' real fingerprints and edited by most repair
# slices; touching them must not disturb any epoch while the design is unfrozen.
CHURN_FILES = (
    "runners/a_short_weekly_pipeline.py",
    "runners/a_short_phase5_engine.py",
    "A-EGS/egs_main.py",
)

MODES = ("pre_freeze_audit_only", "frozen_enforced")

# The epoch components whose ENFORCED binding hashes one of CHURN_FILES whole.
# Asserting this exact set both ways keeps the pre-freeze equality honest: if a
# component silently stopped binding those files the probe would prove nothing,
# and if a new component started binding them it has joined the churn class and
# must be a deliberate decision.  When the restore-condition convergence onto
# semantic contracts lands this set shrinks — that is a decision to record, not
# a test to relax.
CHURN_BOUND_COMPONENTS = frozenset({
    "p0v2.decision_delta_contract",
    "p0v2.immutable_common_pool_contract",
    "p1",
    "p3",
    "p4a",
})

# The live modules this probe used to ``importlib.reload``.  Reload keeps the
# module object and its ``__dict__`` identical, so only the symbols inside them
# reveal a re-execution.
TRACK_MODULES = (
    "engine.a_short_overlay_adjudication",
    "runners.a_short_final_action_validation_runner",
    "engine.a_short_industry_weight_comparison",
    "runners.a_short_target_policy_comparison_runner",
    "engine.a_short_regime_action_comparison",
    "engine.a_short_factor_comparison_v2",
)

P0V2_CONTRACT_LEGS = (
    "decision_delta_contract",
    "immutable_common_pool_contract",
    "outcome_contract",
    "runtime_wiring_contract",
)


def _fingerprints() -> dict[str, str]:
    """Every epoch component, not one sample per track.

    P0/v2 owns four contract legs and only two of them bind a churn file, so
    sampling a single leg (the original shape of this helper) left the two
    diseased legs unexercised.
    """
    from engine.a_short_factor_comparison_v2 import _canonical_contracts, load_v2_governance
    from engine.a_short_industry_weight_comparison import _contract_fingerprint as p5, load_governance
    from engine.a_short_overlay_adjudication import _epoch_context
    from engine.a_short_regime_action_comparison import candidate_effect_policy_fingerprint as p1
    from runners.a_short_final_action_validation_runner import _contract_fingerprint as p3
    from runners.a_short_target_policy_comparison_runner import _contract_fingerprint as p2
    v2_contracts = _canonical_contracts(load_v2_governance())
    values = {
        "p4a": _epoch_context()["contract_fingerprint"],
        "p3": p3(),
        "p5": p5(load_governance()),
        "p2_target": p2("target_exit"),
        "p2_breakout": p2("breakout_entry"),
        "p1": p1(),
    }
    for leg in P0V2_CONTRACT_LEGS:
        values[f"p0v2.{leg}"] = v2_contracts[leg]
    return values


def _loaded_track_symbols() -> dict[str, tuple[int, ...]]:
    """Identity of every callable inside each already-loaded track module.

    ``importlib.reload`` reuses the module object and its ``__dict__``, so the
    module id is unchanged by a re-execution; the rebuilt functions and classes
    inside it are not.
    """
    identities: dict[str, tuple[int, ...]] = {}
    for name in TRACK_MODULES:
        module = sys.modules.get(name)
        if module is None:
            continue
        identities[name] = tuple(
            id(getattr(module, attribute)) for attribute in sorted(vars(module))
            if callable(getattr(module, attribute, None))
        )
    return identities


def _p4a_promotion_row(index: int) -> dict:
    """One P4a outcome row shaped to clear every promotion gate when enforced.

    Threshold-satisfying on purpose: an empty-row probe cannot tell a working
    gate from a missing one, because `_adjudicate` returns `continue_accumulating`
    on no evidence either way.
    """
    month = index + 1
    decision = f"202{6 + index // 12}{month % 12 or 12:02d}01"
    arm = {"entry_date": decision[:-2] + "02", "exit_date": decision[:-2] + "11",
           "close_drawdown_pct": 0.0, "cash_drag_pct": 0.0, "unfilled_rate_pct": 0.0,
           "positions": [{"ts_code": f"c{index}", "entry_status": "filled", "net_return_pct": 1.0}]}
    baseline = dict(arm, positions=[{"ts_code": f"b{index}", "entry_status": "filled", "net_return_pct": .5}])
    return {
        "decision_date": decision, "same_list": False,
        "h5": {"status": "settled", "delta_pct": .5}, "h5_complete": True,
        "h10": {"status": "settled", "delta_pct": .5, "baseline": baseline, "candidate": arm,
                "benchmarks": {"csi1000": {"candidate_excess_pct": .5}, "csi300": {"candidate_excess_pct": .5}}},
        "h20": {"status": "settled", "delta_pct": .5}, "h20_complete": True,
    }


def _fingerprints_in_mode(mode: str) -> dict[str, str]:
    original = epoch_mode.MODE
    epoch_mode.MODE = mode
    try:
        return _fingerprints()
    finally:
        epoch_mode.MODE = original


class PreFreezeEvidenceModeTests(unittest.TestCase):
    def test_default_mode_is_pre_freeze_and_does_not_count(self):
        self.assertEqual(epoch_mode.MODE, "pre_freeze_audit_only")
        self.assertFalse(epoch_mode.enforcement_enabled())
        self.assertFalse(epoch_mode.evidence_counts_toward_clock())

    def test_pre_freeze_fingerprint_is_sha256_shaped_and_track_distinct(self):
        seen = {track: epoch_mode.pre_freeze_fingerprint(track) for track in epoch_mode.TRACKS}
        self.assertEqual(len(set(seen.values())), len(epoch_mode.TRACKS))
        for value in seen.values():
            self.assertRegex(value, r"^[0-9a-f]{64}$")

    def test_unregistered_track_is_rejected(self):
        with self.assertRaises(epoch_mode.EvidenceEpochModeError):
            epoch_mode.pre_freeze_fingerprint("not_a_track")

    def test_unrelated_source_edits_do_not_move_any_epoch(self):
        """The churn edit must move nothing pre-freeze while still being able to
        move the enforced bindings; without the second half the equality proves
        nothing at all.

        Deliberately no ``importlib.reload``: every fingerprint reads its inputs
        at call time, and re-executing live modules inside the shared test
        interpreter corrupted unrelated test modules
        (`R-ASHORT-EPOCH-MODE-TEST-RELOAD-POLLUTES-LANE-PACK`).  The mutation is
        owned here so the restore runs even if a fingerprint call raises.
        """
        originals = {path: (ROOT / path).read_bytes() for path in CHURN_FILES}
        symbols_before = _loaded_track_symbols()
        try:
            before = {mode: _fingerprints_in_mode(mode) for mode in MODES}
            for path in CHURN_FILES:
                with (ROOT / path).open("ab") as handle:
                    handle.write(b"\n# evidence-epoch churn probe\n")
            after = {mode: _fingerprints_in_mode(mode) for mode in MODES}
        finally:
            for path, payload in originals.items():
                (ROOT / path).write_bytes(payload)
        self.assertEqual(before["pre_freeze_audit_only"], after["pre_freeze_audit_only"])
        moved = {name for name, value in after["frozen_enforced"].items()
                 if before["frozen_enforced"][name] != value}
        self.assertEqual(moved, set(CHURN_BOUND_COMPONENTS))
        # Regression guard for the pollution this probe once caused: no already
        # loaded track module may be re-executed, no churn file may keep the
        # probe comment, and the shared mode must be back where it started.
        symbols_after = _loaded_track_symbols()
        self.assertEqual([name for name, ids in symbols_before.items()
                          if symbols_after.get(name) != ids], [])
        self.assertEqual({path: (ROOT / path).read_bytes() for path in CHURN_FILES}, originals)
        self.assertEqual(epoch_mode.MODE, "pre_freeze_audit_only")

    def test_enforcement_is_parked_not_deleted(self):
        """Flipping the mode back on must restore a real, drift-sensitive binding."""
        enforced = _fingerprints_in_mode("frozen_enforced")
        parked = _fingerprints_in_mode("pre_freeze_audit_only")
        self.assertEqual(sorted(enforced), sorted(parked))
        for component in enforced:
            self.assertNotEqual(enforced[component], parked[component], component)

    def test_unknown_mode_fails_closed(self):
        original = epoch_mode.MODE
        try:
            epoch_mode.MODE = "something_else"
            with self.assertRaises(epoch_mode.EvidenceEpochModeError):
                epoch_mode.enforcement_enabled()
        finally:
            epoch_mode.MODE = original


class PreFreezeVerdictGateTests(unittest.TestCase):
    def test_p4a_threshold_evidence_gates_pre_freeze_then_re_arms(self):
        from engine.a_short_overlay_adjudication import _adjudicate
        rows = [_p4a_promotion_row(index) for index in range(24)]
        with mock.patch.object(epoch_mode, "MODE", "pre_freeze_audit_only"):
            parked, parked_metrics = _adjudicate(rows, 24, 0)
        with mock.patch.object(epoch_mode, "MODE", "frozen_enforced"):
            enforced, _metrics = _adjudicate(rows, 24, 0)
        self.assertEqual(parked, "continue_accumulating")
        self.assertEqual(enforced, "candidate_for_manual_promotion")
        # The raw audit counters stay visible pre-freeze; only the verdict is withheld.
        self.assertEqual((parked_metrics["eligible"], parked_metrics["difference"]), (24, 24))

    def test_p2_review_status_stays_not_reviewed(self):
        from runners.a_short_target_policy_comparison_runner import _current_review_status
        ledger = {"review_status_by_epoch": {"target_exit": {"e1": "reviewed"}, "breakout_entry": {}}}
        status = _current_review_status(ledger, "target_exit", {"epoch_id": "e1"})
        self.assertEqual(status, "not_reviewed")

    def test_p5_threshold_evidence_gates_pre_freeze_then_re_arms(self):
        from engine import a_short_industry_weight_comparison as p5
        captures = [{"decision_date": f"202607{day:02d}"} for day in range(1, 13)]
        outcome = {"payload": {"questions": [{"question_id": "balanced_vs_legacy", "same_list": False,
                                              "horizons": {"h10": {"status": "settled"}}}]}}
        any_existing_file = ROOT / "engine" / "a_short_evidence_epoch_mode.py"
        with mock.patch.object(p5, "_current_admission_capture_records", lambda root: captures), \
                mock.patch.object(p5, "_weekly_paths", lambda root, date: (any_existing_file, any_existing_file)), \
                mock.patch.object(p5, "_load_json", lambda path: outcome), \
                mock.patch.object(p5, "_validate_private_record", lambda record: None):
            with mock.patch.object(epoch_mode, "MODE", "pre_freeze_audit_only"):
                parked = p5._question_progress(Path("."), "balanced_vs_legacy", "20260727")
            with mock.patch.object(epoch_mode, "MODE", "frozen_enforced"):
                enforced = p5._question_progress(Path("."), "balanced_vs_legacy", "20260727")
        # Same threshold-satisfying evidence both times: 12 eligible weeks, 12 with a real difference.
        self.assertEqual((parked["eligible_policy_weeks"], parked["difference_weeks"]), (12, 12))
        self.assertEqual((parked["p5b_build_due"], parked["p5b_checkpoint_notice"]), (False, "accumulating"))
        self.assertEqual((enforced["p5b_build_due"], enforced["p5b_checkpoint_notice"]),
                         (True, "p5b_implementation_due_at_12"))


if __name__ == "__main__":
    unittest.main()
