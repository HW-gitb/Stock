"""Guards for the pre-freeze evidence mode shared by every A-short comparison track.

The bug this locks down: each track's epoch fingerprint hashed whole
implementation files, so an edit unrelated to any comparison contract silently
dropped every accumulated week.  While the design is unfrozen the fingerprints
must be stable constants, and no track may reach a verdict on evidence that
does not count.
"""
from __future__ import annotations

import ast
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import a_short_evidence_epoch_mode as epoch_mode  # noqa: E402
from tests._a_short_epoch_mode_test_utils import (  # noqa: E402
    _resealed_freeze_packet, patched_epoch_modes,
)

P0V2_CONTRACT_LEGS = (
    "decision_delta_contract",
    "immutable_common_pool_contract",
    "outcome_contract",
    "runtime_wiring_contract",
)

# Every direct ``inspect.getsource`` source-identity seam in the seven tracks.
# A new call fails this scan until its persisted root and pre-freeze gate are
# named.  This turns the parking requirement into an opt-out review gate rather
# than another opt-in fingerprint list.
SOURCE_IDENTITY_GETSOURCE_CALLS = {
    # P1/P3/P4a/P5 now derive their source identity through the shared
    # AST helpers in `a_short_evidence_epoch_mode`, so they must hold no direct
    # `inspect.getsource` callsite at all; an empty set is the strong assertion.
    "engine/a_short_regime_action_comparison.py": set(),
    "runners/a_short_regime_comparison_runner.py": set(),
    "runners/a_short_final_action_validation_runner.py": set(),
    "engine/a_short_overlay_adjudication.py": set(),
    "engine/egs_industry_heat.py": set(),
    # P2's dependency-closure walker and its two shared-surface legs now route
    # through the same AST helper, so this file must also hold none.
    "runners/a_short_target_policy_comparison_runner.py": set(),
    # Still a direct callsite by design: the theme track reads a live function
    # object rather than a module, though it AST-normalises the result itself.
    "engine/a_short_theme_forward_comparison.py": {"_semantic_function_digest"},
}

# Each source-derivation seam above must terminate at one of these audited
# pre-freeze roots.  The root must contain the named gate call in its AST.
SOURCE_IDENTITY_GATES = {
    "engine/a_short_factor_comparison_v2.py": {
        "_canonical_contracts": "validated_frozen_packet_identity",
    },
    "engine/a_short_regime_action_comparison.py": {
        "candidate_effect_policy_fingerprint": "fingerprint_or_pre_freeze",
    },
    "runners/a_short_regime_comparison_runner.py": {
        "_candidate_effect_selector_contract": "fingerprint_or_pre_freeze",
    },
    "runners/a_short_target_policy_comparison_runner.py": {
        "_contract_fingerprint": "validated_frozen_packet_identity",
    },
    "runners/a_short_final_action_validation_runner.py": {
        "_contract_fingerprint": "fingerprint_or_pre_freeze",
    },
    "engine/a_short_overlay_adjudication.py": {
        "_epoch_context": "fingerprint_or_pre_freeze",
    },
    "engine/egs_industry_heat.py": {
        "_p5_source_fingerprint": "fingerprint_or_pre_freeze",
    },
    "engine/a_short_industry_weight_comparison.py": {
        "_contract_fingerprint": "fingerprint_or_pre_freeze",
    },
    "engine/a_short_theme_forward_comparison.py": {
        "_epoch_context": "validated_frozen_packet_identity",
    },
}


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
    from engine.egs_industry_heat import _p5_source_fingerprint
    from runners.a_short_final_action_validation_runner import _contract_fingerprint as p3
    from runners.a_short_regime_comparison_runner import _candidate_effect_policy_key
    from runners.a_short_target_policy_comparison_runner import _contract_fingerprint as p2
    from engine.a_short_theme_forward_comparison import (
        TRACK_ID as theme_track, comparison_contract_fingerprint, load_governance as load_theme_governance,
    )
    v2_contracts = _canonical_contracts(load_v2_governance())
    values = {
        "p4a": _epoch_context()["contract_fingerprint"],
        "p3": p3(),
        "p5": p5(load_governance()),
        "p2_target": p2("target_exit"),
        "p2_breakout": p2("breakout_entry"),
        "p1": p1(),
        "p1_selector": _candidate_effect_policy_key(),
        "p5_source": _p5_source_fingerprint(),
        "theme_forward": epoch_mode.fingerprint_or_pre_freeze(
            theme_track,
            lambda: comparison_contract_fingerprint(
                load_theme_governance(),
                ["physical_ai"],
                {
                    "industry_trend_configuration_fingerprint": "a" * 64,
                    "theme_taxonomy_configuration_fingerprint": "b" * 64,
                },
            ),
        ),
    }
    for leg in P0V2_CONTRACT_LEGS:
        values[f"p0v2.{leg}"] = v2_contracts[leg]
    return values


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


class PreFreezeEvidenceModeTests(unittest.TestCase):
    def test_default_mode_is_pre_freeze_and_does_not_count(self):
        for track in epoch_mode.TRACKS:
            self.assertFalse(epoch_mode.enforcement_enabled(track))
            self.assertFalse(epoch_mode.evidence_counts_toward_clock(track))

    def test_every_individually_frozen_track_rearms_the_shared_freeze_packet(self):
        for track in epoch_mode.TRACKS:
            with self.subTest(track=track), \
                    patched_epoch_modes("frozen_enforced", (track,)), \
                    mock.patch.object(
                        epoch_mode, "_validate_fifth_knife_freeze_packet",
                        wraps=epoch_mode._validate_fifth_knife_freeze_packet,
                    ) as validate:
                self.assertTrue(epoch_mode.enforcement_enabled(track))
                validate.assert_called_once_with(require_contract_hashes=True)

    def test_pre_freeze_still_consumes_packet_identity_and_honesty(self):
        with patched_epoch_modes("pre_freeze_audit_only", (epoch_mode.TRACKS[0],)):
            packet_path = epoch_mode.FIFTH_KNIFE_FREEZE_PACKET_PATH
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            packet["boundary"]["effectiveness_claimed"] = True
            packet["record_sha256"] = epoch_mode._canonical_json_sha256({
                key: value for key, value in packet.items() if key != "record_sha256"
            })
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            # The schema is the first guard.  Bypass it only inside this test
            # to prove the independent runtime honesty check is still
            # load-bearing rather than dead code behind schema consts.
            with mock.patch.object(epoch_mode, "_freeze_packet_validator"), \
                    self.assertRaisesRegex(
                        epoch_mode.EvidenceEpochModeError,
                        "dishonest fifth-knife pre-freeze boundary",
                    ):
                epoch_mode.enforcement_enabled(epoch_mode.TRACKS[0])

    def test_freeze_schema_validator_is_cached_but_packet_validation_is_not(self):
        with tempfile.TemporaryDirectory() as temp, \
                patched_epoch_modes("pre_freeze_audit_only"):
            schema_path = Path(temp) / "freeze.schema.json"
            schema_path.write_bytes(
                epoch_mode.FIFTH_KNIFE_FREEZE_SCHEMA_PATH.read_bytes()
            )
            packet_path = epoch_mode.FIFTH_KNIFE_FREEZE_PACKET_PATH
            epoch_mode._compiled_freeze_packet_validator.cache_clear()
            self.addCleanup(
                epoch_mode._compiled_freeze_packet_validator.cache_clear
            )
            with mock.patch.object(
                epoch_mode, "FIFTH_KNIFE_FREEZE_SCHEMA_PATH", schema_path,
            ):
                self.assertFalse(
                    epoch_mode.enforcement_enabled(epoch_mode.TRACKS[0])
                )
                self.assertFalse(
                    epoch_mode.enforcement_enabled(epoch_mode.TRACKS[0])
                )
                self.assertEqual(
                    epoch_mode._compiled_freeze_packet_validator.cache_info().misses,
                    1,
                )

                packet = json.loads(packet_path.read_text(encoding="utf-8"))
                original_ship_gate_status = packet["ship_gate"]["status"]
                packet["ship_gate"]["status"] = "invented_status"
                packet["record_sha256"] = epoch_mode._canonical_json_sha256({
                    key: value for key, value in packet.items()
                    if key != "record_sha256"
                })
                packet_path.write_text(json.dumps(packet), encoding="utf-8")
                with self.assertRaisesRegex(
                    epoch_mode.EvidenceEpochModeError,
                    "invalid fifth-knife freeze packet schema",
                ):
                    epoch_mode.enforcement_enabled(epoch_mode.TRACKS[0])
                self.assertEqual(
                    epoch_mode._compiled_freeze_packet_validator.cache_info().misses,
                    1,
                )

                schema_path.write_bytes(schema_path.read_bytes() + b"\n")
                packet["ship_gate"]["status"] = original_ship_gate_status
                packet["record_sha256"] = epoch_mode._canonical_json_sha256({
                    key: value for key, value in packet.items()
                    if key != "record_sha256"
                })
                packet_path.write_text(json.dumps(packet), encoding="utf-8")
                self.assertFalse(
                    epoch_mode.enforcement_enabled(epoch_mode.TRACKS[0])
                )
                self.assertEqual(
                    epoch_mode._compiled_freeze_packet_validator.cache_info().misses,
                    2,
                )

    def test_pre_freeze_rejects_packet_shape_outside_manual_runtime_checks(self):
        with patched_epoch_modes("pre_freeze_audit_only"):
            packet_path = epoch_mode.FIFTH_KNIFE_FREEZE_PACKET_PATH
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            packet["ship_gate"]["status"] = "invented_status"
            packet["record_sha256"] = epoch_mode._canonical_json_sha256({
                key: value for key, value in packet.items() if key != "record_sha256"
            })
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            with self.assertRaisesRegex(
                epoch_mode.EvidenceEpochModeError,
                "invalid fifth-knife freeze packet schema",
            ):
                epoch_mode.enforcement_enabled(epoch_mode.TRACKS[0])

    def test_any_frozen_track_rejects_drift_in_any_shared_contract(self):
        for track in epoch_mode.TRACKS:
            with self.subTest(track=track), \
                    patched_epoch_modes("frozen_enforced", (track,)):
                packet_path = epoch_mode.FIFTH_KNIFE_FREEZE_PACKET_PATH
                packet = json.loads(packet_path.read_text(encoding="utf-8"))
                packet["frozen_contracts"][-1]["semantic_fingerprint"] = "0" * 64
                packet["record_sha256"] = epoch_mode._canonical_json_sha256({
                    key: value for key, value in packet.items()
                    if key != "record_sha256"
                })
                packet_path.write_text(json.dumps(packet), encoding="utf-8")
                with self.assertRaisesRegex(
                    epoch_mode.EvidenceEpochModeError,
                    "fifth-knife frozen contract semantic drift: weekly_report_schema",
                ):
                    epoch_mode.enforcement_enabled(track)

    def test_a_cosmetic_shared_contract_edit_costs_nothing_but_a_semantic_one_rekeys_all(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            original_packet = epoch_mode.FIFTH_KNIFE_FREEZE_PACKET_PATH.read_bytes()
            packet_path = temp_root / "freeze_packet.json"
            packet_path.write_bytes(original_packet)
            for relative in epoch_mode._FIFTH_KNIFE_FROZEN_CONTRACTS.values():
                source = epoch_mode.ROOT / relative
                target = temp_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            registry_path = temp_root / "registry.json"
            registry_path.write_text(json.dumps({
                "schema_name": "a_short_evidence_epoch_mode_registry",
                "schema_version": "1.0.0",
                "track_modes": {
                    track: "frozen_enforced" for track in epoch_mode.TRACKS
                },
            }), encoding="utf-8")
            with mock.patch.object(epoch_mode, "ROOT", temp_root), \
                    mock.patch.object(
                        epoch_mode, "FIFTH_KNIFE_FREEZE_PACKET_PATH", packet_path,
                    ), \
                    mock.patch.object(
                        epoch_mode, "TRACK_MODE_REGISTRY_PATH", registry_path,
                    ):
                _resealed_freeze_packet(packet_path)
                before = _fingerprints()
                shared_contract = temp_root / (
                    epoch_mode._FIFTH_KNIFE_FROZEN_CONTRACTS[
                        "weekly_report_schema"
                    ]
                )
                # Cosmetic first: reformatting and rewording a shared contract
                # must cost nothing.  This is the whole reason the gate moved
                # off whole-file bytes -- edits like these fired twice in one
                # week and silently discarded every accumulated week.
                document = json.loads(shared_contract.read_text(encoding="utf-8"))
                document["description"] = "reworded during an unfinished design"
                document["$comment"] = "and annotated"
                shared_contract.write_text(
                    json.dumps(document, indent=4) + "\n", encoding="utf-8",
                )
                _resealed_freeze_packet(packet_path)
                after_cosmetic = _fingerprints()

                # Semantic second: a validation keyword genuinely changes which
                # payloads are admissible, so every track must be rekeyed.
                document["properties"]["__epoch_semantic_probe__"] = {"type": "string"}
                shared_contract.write_text(
                    json.dumps(document, indent=4) + "\n", encoding="utf-8",
                )
                _resealed_freeze_packet(packet_path)
                after_semantic = _fingerprints()
            self.assertTrue(before)
            self.assertEqual(set(before), set(after_cosmetic))
            self.assertEqual(before, after_cosmetic,
                             "a cosmetic edit discarded evidence")
            self.assertEqual(set(before), set(after_semantic))
            self.assertTrue(all(before[key] != after_semantic[key] for key in before),
                            "a semantic edit failed to rekey every track")

    def test_bound_identity_rejects_missing_old_version_freeze_id_and_record_hash(self):
        with patched_epoch_modes(
            "frozen_enforced", (epoch_mode.TRACKS[0],)
        ):
            current = epoch_mode.validated_frozen_packet_identity(
                epoch_mode.TRACKS[0]
            )
            self.assertIsNotNone(current)
            mutations = (
                None,
                {**current, "schema_version": "0.9.0"},
                {**current, "freeze_id": "other-freeze"},
                {**current, "record_sha256": "0" * 64},
            )
            for expected in mutations:
                with self.subTest(expected=expected), self.assertRaisesRegex(
                    epoch_mode.EvidenceEpochModeError, "epoch binding mismatch"
                ):
                    epoch_mode.validate_bound_frozen_packet_identity(
                        epoch_mode.TRACKS[0], expected,
                    )

    def test_freeze_packet_inventory_cannot_drop_or_duplicate_a_contract(self):
        for mutation in ("drop", "duplicate"):
            with self.subTest(mutation=mutation), \
                    patched_epoch_modes("pre_freeze_audit_only"):
                packet_path = epoch_mode.FIFTH_KNIFE_FREEZE_PACKET_PATH
                packet = json.loads(packet_path.read_text(encoding="utf-8"))
                if mutation == "drop":
                    packet["frozen_contracts"].pop()
                else:
                    packet["frozen_contracts"].append(
                        dict(packet["frozen_contracts"][0])
                    )
                packet["record_sha256"] = epoch_mode._canonical_json_sha256({
                    key: value for key, value in packet.items()
                    if key != "record_sha256"
                })
                packet_path.write_text(json.dumps(packet), encoding="utf-8")
                with self.assertRaises(epoch_mode.EvidenceEpochModeError):
                    epoch_mode.enforcement_enabled(epoch_mode.TRACKS[0])

    def test_pre_freeze_fingerprint_is_sha256_shaped_and_track_distinct(self):
        seen = {track: epoch_mode.pre_freeze_fingerprint(track) for track in epoch_mode.TRACKS}
        self.assertEqual(len(set(seen.values())), len(epoch_mode.TRACKS))
        for value in seen.values():
            self.assertRegex(value, r"^[0-9a-f]{64}$")

    def test_unregistered_track_is_rejected(self):
        with self.assertRaises(epoch_mode.EvidenceEpochModeError):
            epoch_mode.pre_freeze_fingerprint("not_a_track")
        with patched_epoch_modes("frozen_enforced"):
            with self.assertRaises(epoch_mode.EvidenceEpochModeError):
                epoch_mode.enforcement_enabled("not_a_track")

    def test_no_global_switch_can_arm_all_tracks(self):
        self.assertFalse(hasattr(epoch_mode, "MODE"))

    def test_all_persisted_source_identities_are_lazy_and_stable_pre_freeze(self):
        """A source edit cannot re-key a ledger or block capture before freeze."""
        from engine import a_short_factor_comparison_v2 as p0
        from engine import a_short_industry_weight_comparison as p5
        from engine import egs_industry_heat as heat
        from runners import a_short_regime_comparison_runner as p1_runner

        with patched_epoch_modes("pre_freeze_audit_only"):
            baseline = _fingerprints()
            p0_baseline = p0._canonical_contracts(p0.load_v2_governance())
            p1_key = p1_runner._candidate_effect_policy_key()
            p1_policy = p1_runner._new_candidate_effect_group()["policy"]
            p5_source = p5._source_fingerprint()
            with mock.patch.object(
                epoch_mode, "semantic_module_contract",
                side_effect=AssertionError("pre-freeze P0 semantic supplier executed"),
            ), mock.patch.object(
                p1_runner, "_real_candidate_effect_selector_contract",
                side_effect=AssertionError("pre-freeze P1 selector supplier executed"),
            ), mock.patch.object(
                heat, "_real_p5_source_fingerprint",
                side_effect=AssertionError("pre-freeze P5 source supplier executed"),
            ):
                self.assertEqual(_fingerprints(), baseline)
                self.assertEqual(p0._canonical_contracts(p0.load_v2_governance()), p0_baseline)
                self.assertEqual(p1_runner._candidate_effect_policy_key(), p1_key)
                self.assertEqual(p1_runner._new_candidate_effect_group()["policy"], p1_policy)
                self.assertEqual(p5._source_fingerprint(), p5_source)

    def test_comment_edit_never_rekeys_p1_but_a_code_edit_does_once_frozen(self):
        """The full matrix the original reviewer counterexample only half covered.

        comment edit  -> must move nothing, in either mode (churn immunity)
        code edit     -> must move nothing pre-freeze, and MUST move once frozen
        """
        from runners import a_short_regime_comparison_runner as p1_runner

        real_source = Path(p1_runner.__file__).read_text(encoding="utf-8")
        commented = real_source.replace(
            "def _real_candidate_effect_selector_contract",
            "# simulated comment-only edit\ndef _real_candidate_effect_selector_contract", 1)
        tree = ast.parse(real_source)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "_m67_build_candidates":
                node.body.insert(0, ast.parse("_semantic_mutant = 1").body[0])
                break
        else:  # pragma: no cover - the bound function must exist
            self.fail("_m67_build_candidates is no longer a top-level function")
        recoded = ast.unparse(ast.fix_missing_locations(tree))
        self.assertNotEqual(commented, real_source)
        self.assertNotEqual(recoded, real_source)

        def key_with(source_text, mode):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "p1_runner_variant.py"
                path.write_text(source_text, encoding="utf-8")
                with patched_epoch_modes(mode, ("p1_regime_candidate_effect",)), \
                        mock.patch.object(epoch_mode.inspect, "getsourcefile", return_value=str(path)):
                    return p1_runner._candidate_effect_policy_key()

        for mode in ("pre_freeze_audit_only", "frozen_enforced"):
            baseline = key_with(real_source, mode)
            self.assertEqual(key_with(commented, mode), baseline,
                             f"a comment-only edit moved the P1 bucket in {mode}")
            moved = key_with(recoded, mode) != baseline
            self.assertEqual(moved, mode == "frozen_enforced",
                             f"code-edit drift is wrong for {mode}")

    def test_p2_contract_is_prose_insensitive_and_code_sensitive_on_every_leg(self):
        """P2 was the last raw-source track; all three of its legs must converge.

        The walker was the only leg named in the finding, but `_shared_contract_surface`
        carried two more direct `inspect.getsource` legs, so the class is three legs
        plus a scoping control and a rename control.
        """
        from engine import a_short_managed_exit as managed_exit
        from runners import a_short_target_policy_comparison_runner as p2

        real_getsourcefile = epoch_mode.inspect.getsourcefile
        originals = {
            module.__name__: Path(real_getsourcefile(module)).read_text(encoding="utf-8")
            for module in (managed_exit, p2)
        }

        def variants(module, function_name):
            source = originals[module.__name__]
            tree = ast.parse(source)
            node = next((n for n in tree.body
                         if isinstance(n, ast.FunctionDef) and n.name == function_name), None)
            self.assertIsNotNone(node, f"{function_name} is no longer a top-level function")
            lines = source.splitlines(keepends=True)
            lines.insert(node.body[0].lineno - 1,
                         f"{' ' * node.body[0].col_offset}# simulated comment-only edit\n")
            commented = "".join(lines)
            node.body.insert(0, ast.parse("_semantic_mutant = 1").body[0])
            recoded = ast.unparse(ast.fix_missing_locations(tree))
            self.assertNotEqual(commented, source)
            return commented, recoded

        def fingerprint_with(module, source_text, mode):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "p2_variant.py"
                path.write_text(source_text, encoding="utf-8")
                overrides = {module.__name__: str(path)}

                def resolve(target):
                    return overrides.get(getattr(target, "__name__", ""), real_getsourcefile(target))

                with patched_epoch_modes(mode, ("p2_target_policy",)), \
                        mock.patch.object(epoch_mode.inspect, "getsourcefile", side_effect=resolve):
                    return p2._contract_fingerprint()

        legs = (
            (managed_exit, "evaluate_managed_exit", True),   # walker leg, another module
            (p2, "_settle_existing_records", True),          # settlement dispatch leg
            (p2, "_load_execution_cache", True),             # shared cache loader leg
            (p2, "main", False),                             # scoping control: unbound
        )
        for module, function_name, bound in legs:
            commented, recoded = variants(module, function_name)
            for mode in ("pre_freeze_audit_only", "frozen_enforced"):
                baseline = fingerprint_with(module, originals[module.__name__], mode)
                self.assertEqual(fingerprint_with(module, commented, mode), baseline,
                                 f"a comment-only edit moved P2 via {function_name} in {mode}")
                moved = fingerprint_with(module, recoded, mode) != baseline
                self.assertEqual(moved, bound and mode == "frozen_enforced",
                                 f"code-edit drift is wrong for {function_name} in {mode}")

        renamed = originals[p2.__name__].replace(
            "def _load_execution_cache(", "def _load_execution_cache_renamed(", 1)
        with self.assertRaises(epoch_mode.EvidenceEpochModeError):
            fingerprint_with(p2, renamed, "frozen_enforced")

    def test_every_track_has_a_positive_enforced_drift_control(self):
        """Every parked identity must become genuinely drift-sensitive at freeze."""
        from engine import a_short_factor_comparison_v2 as p0
        from engine import a_short_industry_weight_comparison as p5
        from engine import a_short_overlay_adjudication as p4a
        from engine import a_short_regime_action_comparison as p1
        from engine import a_short_theme_forward_comparison as theme
        from runners import a_short_final_action_validation_runner as p3
        from runners import a_short_regime_comparison_runner as p1_runner
        from runners import a_short_target_policy_comparison_runner as p2

        with patched_epoch_modes("frozen_enforced"):
            p0_before = p0._canonical_contracts(p0.load_v2_governance())
            original_semantic_contract = epoch_mode.semantic_module_contract

            def p0_mutant(module, *, excluded_functions=frozenset()):
                value = original_semantic_contract(module, excluded_functions=excluded_functions)
                if module.__name__ == "engine.a_short_factor_comparison_v2_adjudication":
                    value = {**value, "semantic_ast_sha256": "0" * 64}
                return value

            with mock.patch.object(epoch_mode, "semantic_module_contract", side_effect=p0_mutant):
                p0_after = p0._canonical_contracts(p0.load_v2_governance())
            self.assertEqual(
                {leg for leg in P0V2_CONTRACT_LEGS if p0_before[leg] != p0_after[leg]},
                set(P0V2_CONTRACT_LEGS),
            )

            p1_before = p1.candidate_effect_policy_fingerprint()
            with mock.patch.object(p1, "_runtime_policy_source_fingerprint", return_value="0" * 64):
                self.assertNotEqual(p1.candidate_effect_policy_fingerprint(), p1_before)
            p1_key_before = p1_runner._candidate_effect_policy_key()
            with mock.patch.object(p1_runner, "_real_candidate_effect_selector_contract", return_value="1" * 64):
                self.assertNotEqual(p1_runner._candidate_effect_policy_key(), p1_key_before)

            target_before = p2._contract_fingerprint("target_exit")
            breakout_before = p2._contract_fingerprint("breakout_entry")
            with mock.patch.object(p2, "_target_contract_surface", return_value={"semantic_mutant": True}):
                self.assertNotEqual(p2._contract_fingerprint("target_exit"), target_before)
                self.assertEqual(p2._contract_fingerprint("breakout_entry"), breakout_before)

            p3_before = p3._contract_fingerprint()
            with mock.patch.object(p3, "_real_contract_fingerprint", return_value="2" * 64):
                self.assertNotEqual(p3._contract_fingerprint(), p3_before)

            p4a_before = p4a._contract_fingerprint()
            with mock.patch.object(p4a, "_screening_runtime_recipe_binding",
                                   return_value={"semantic_mutant": True}):
                self.assertNotEqual(p4a._contract_fingerprint(), p4a_before)

            p5_before = p5._contract_fingerprint(p5.load_governance())
            with mock.patch.object(p5, "_runtime_source_fingerprint", return_value="3" * 64):
                self.assertNotEqual(p5._contract_fingerprint(p5.load_governance()), p5_before)

            theme_source = {
                "industry_trend_configuration_fingerprint": "a" * 64,
                "theme_taxonomy_configuration_fingerprint": "b" * 64,
            }
            theme_before = epoch_mode.fingerprint_or_pre_freeze(
                theme.TRACK_ID,
                lambda: theme.comparison_contract_fingerprint(
                    theme.load_governance(), ["physical_ai"], theme_source,
                ),
            )
            with mock.patch.object(theme, "_contract_function_semantics",
                                   return_value={"semantic_mutant": "4" * 64}):
                theme_after = epoch_mode.fingerprint_or_pre_freeze(
                    theme.TRACK_ID,
                    lambda: theme.comparison_contract_fingerprint(
                        theme.load_governance(), ["physical_ai"], theme_source,
                    ),
                )
            self.assertNotEqual(theme_after, theme_before)

    def test_p0v2_semantic_binding_is_complete_and_exclusions_are_exact(self):
        from engine import a_short_factor_comparison_v2 as p0

        for module_name, exclusions in p0.P0V2_SEMANTIC_MODULE_EXCLUSIONS.items():
            module = __import__(module_name, fromlist=["*"])
            contract = epoch_mode.semantic_module_contract(
                module,
                excluded_functions=exclusions,
            )
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            functions = {
                node.name for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            self.assertEqual(set(contract["excluded_functions"]), set(exclusions), module_name)
            self.assertEqual(set(contract["bound_functions"]), functions - set(exclusions), module_name)
            self.assertEqual(functions, set(contract["bound_functions"]) | set(exclusions), module_name)
        self.assertEqual(set().union(*p0.P0V2_SEMANTIC_MODULE_EXCLUSIONS.values()), set())

    def test_semantic_module_contract_ignores_comments_and_docstrings_but_not_code(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "semantic_probe.py"
            module = SimpleNamespace(__name__="semantic_probe")
            with mock.patch.object(epoch_mode.inspect, "getsourcefile", return_value=str(path)):
                path.write_text('def value():\n    """old docs"""\n    return 1\n', encoding="utf-8")
                baseline = epoch_mode.semantic_module_contract(module)
                path.write_text('# comment\ndef value():\n    """new docs"""\n    return 1  # inline\n', encoding="utf-8")
                prose_only = epoch_mode.semantic_module_contract(module)
                path.write_text('def value():\n    return 2\n', encoding="utf-8")
                semantic_change = epoch_mode.semantic_module_contract(module)
        self.assertEqual(baseline, prose_only)
        self.assertNotEqual(baseline["semantic_ast_sha256"], semantic_change["semantic_ast_sha256"])

    def test_semantic_contract_memos_key_on_source_bytes_and_return_fresh_values(self):
        from types import SimpleNamespace

        epoch_mode._semantic_module_contract_from_source.cache_clear()
        epoch_mode._semantic_function_contract_from_source.cache_clear()
        epoch_mode._cached_semantic_source_tree.cache_clear()
        module = SimpleNamespace(__name__="semantic_memo_probe")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "semantic_memo_probe.py"
            with mock.patch.object(epoch_mode.inspect, "getsourcefile", return_value=str(path)):
                path.write_text("LIMIT = 3\n\ndef bound():\n    return LIMIT\n", encoding="utf-8")
                with mock.patch.object(epoch_mode.ast, "parse", wraps=epoch_mode.ast.parse) as parse:
                    first = epoch_mode.semantic_function_contract(module, ("bound",))
                    first["bound_constants"].append("poison")
                    second = epoch_mode.semantic_function_contract(module, ("bound",))
                    path.write_text("LIMIT = 4\n\ndef bound():\n    return LIMIT\n", encoding="utf-8")
                    changed = epoch_mode.semantic_function_contract(module, ("bound",))
                self.assertEqual(parse.call_count, 2)
        self.assertEqual(second["bound_constants"], ["LIMIT"])
        self.assertNotEqual(changed["semantic_ast_sha256"], second["semantic_ast_sha256"])

    def test_semantic_source_parse_cache_is_shared_across_contract_dimensions(self):
        from types import SimpleNamespace

        epoch_mode._semantic_module_contract_from_source.cache_clear()
        epoch_mode._semantic_function_contract_from_source.cache_clear()
        epoch_mode._cached_semantic_source_tree.cache_clear()
        module = SimpleNamespace(__name__="semantic_dimension_probe")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "semantic_dimension_probe.py"
            source = (
                "FIRST = 1\nSECOND = 2\n\n"
                "def first():\n    return FIRST\n\n"
                "def second():\n    return SECOND\n"
            )
            with mock.patch.object(epoch_mode.inspect, "getsourcefile", return_value=str(path)):
                path.write_text(source, encoding="utf-8")
                with mock.patch.object(epoch_mode.ast, "parse", wraps=epoch_mode.ast.parse) as parse:
                    for _ in range(4):
                        epoch_mode.semantic_function_contract(module, ("first",))
                        epoch_mode.semantic_function_contract(module, ("second",))
                        epoch_mode.semantic_function_contract(module, ("first", "second"))
                        epoch_mode.semantic_module_contract(module)
                        epoch_mode.semantic_module_contract(module, excluded_functions={"second"})
                    self.assertEqual(parse.call_count, 1)

                    cached_body, cached_functions, _cached_constants = (
                        epoch_mode._semantic_source_inventory(module.__name__, source)
                    )
                    epoch_mode._semantic_ast_sha256([cached_functions["first"]])
                    self.assertEqual(
                        epoch_mode.semantic_function_contract(module, ("first",))["bound_constants"],
                        ["FIRST"],
                    )
                    self.assertEqual(cached_functions["first"].body[-1].value.id, "FIRST")

                    path.write_text(source.replace("FIRST = 1", "FIRST = 3"), encoding="utf-8")
                    changed = epoch_mode.semantic_function_contract(module, ("first",))
                self.assertEqual(parse.call_count, 2)

        self.assertEqual(changed["bound_constants"], ["FIRST"])
        for cached in (
            epoch_mode._semantic_module_contract_from_source.cache_info(),
            epoch_mode._semantic_function_contract_from_source.cache_info(),
        ):
            self.assertLess(cached.currsize, cached.maxsize)

    def test_real_epoch_binding_sources_fit_the_tree_cache(self):
        """All seven A-short track bindings must fit without tree-cache eviction."""
        epoch_mode._cached_semantic_source_tree.cache_clear()
        epoch_mode._semantic_module_contract_from_source.cache_clear()
        epoch_mode._semantic_function_contract_from_source.cache_clear()
        source_tree_cache = epoch_mode._cached_semantic_source_tree
        with patched_epoch_modes("frozen_enforced"), \
                mock.patch.object(epoch_mode, "_cached_semantic_source_tree", wraps=source_tree_cache) as cached:
            _fingerprints()
        tree_cache = epoch_mode._cached_semantic_source_tree.cache_info()
        self.assertGreater(tree_cache.currsize, 0)
        self.assertLess(tree_cache.currsize, tree_cache.maxsize)
        for call in cached.call_args_list:
            module_name, source = call.args
            self.assertEqual(
                ast.dump(source_tree_cache(module_name, source), include_attributes=True),
                ast.dump(ast.parse(source), include_attributes=True),
                f"cached semantic tree was mutated for {module_name}",
            )

    def test_semantic_contract_cache_failures_keep_their_fail_closed_messages(self):
        from types import SimpleNamespace

        epoch_mode._semantic_module_contract_from_source.cache_clear()
        epoch_mode._semantic_function_contract_from_source.cache_clear()
        epoch_mode._cached_semantic_source_tree.cache_clear()
        module = SimpleNamespace(__name__="semantic_failure_probe")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "semantic_failure_probe.py"
            with mock.patch.object(epoch_mode.inspect, "getsourcefile", return_value=str(path)):
                path.write_text("def broken(:\n", encoding="utf-8")
                with self.assertRaisesRegex(
                    epoch_mode.EvidenceEpochModeError,
                    r"^cannot read semantic source for semantic_failure_probe$",
                ):
                    epoch_mode.semantic_module_contract(module)

                path.write_text("def bound():\n    return 1\n", encoding="utf-8")
                with self.assertRaisesRegex(
                    epoch_mode.EvidenceEpochModeError,
                    r"^missing semantic functions in semantic_failure_probe: \['missing'\]$",
                ):
                    epoch_mode.semantic_function_contract(module, ("missing",))
                with self.assertRaisesRegex(
                    epoch_mode.EvidenceEpochModeError,
                    r"^no semantic functions requested for semantic_failure_probe$",
                ):
                    epoch_mode.semantic_function_contract(module, ())
                with self.assertRaisesRegex(
                    epoch_mode.EvidenceEpochModeError,
                    r"^unknown semantic-function exclusions for semantic_failure_probe: \['missing'\]$",
                ):
                    epoch_mode.semantic_module_contract(module, excluded_functions={"missing"})

    def test_narrow_contract_binds_the_constants_its_functions_read(self):
        """A narrow binding must cover read constants, or a governed threshold escapes.

        P5 is the live case: `select_profile_watch_pool` reads
        `PROFILE_WATCH_POOL_TOP_N`, the fixed watch-pool slot count, so binding
        only the function body let that number change without moving the epoch.
        """
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "const_probe.py"
            module = SimpleNamespace(__name__="const_probe")
            body = ('LIMIT = 3\nOTHER = 7\n\n\ndef bound():\n    return LIMIT\n\n\n'
                    'def unbound():\n    return OTHER\n')
            with mock.patch.object(epoch_mode.inspect, "getsourcefile", return_value=str(path)):
                path.write_text(body, encoding="utf-8")
                baseline = epoch_mode.semantic_function_contract(module, ("bound",))
                self.assertEqual(baseline["bound_constants"], ["LIMIT"])

                path.write_text(body.replace("LIMIT = 3", "LIMIT = 4"), encoding="utf-8")
                self.assertNotEqual(
                    epoch_mode.semantic_function_contract(module, ("bound",))["semantic_ast_sha256"],
                    baseline["semantic_ast_sha256"], "a read constant escaped the narrow contract")

                # A constant only the unbound function reads stays out of scope.
                path.write_text(body.replace("OTHER = 7", "OTHER = 8"), encoding="utf-8")
                self.assertEqual(epoch_mode.semantic_function_contract(module, ("bound",)), baseline)

                # Prose around the constant is still ignored.
                path.write_text(body.replace("LIMIT = 3", "# note\nLIMIT = 3"), encoding="utf-8")
                self.assertEqual(epoch_mode.semantic_function_contract(module, ("bound",)), baseline)

    def test_p5_narrow_contract_now_covers_its_governed_slot_count(self):
        """The real instance behind the previous test, pinned against the live module."""
        from engine import egs_industry_heat as heat

        contract = epoch_mode.semantic_function_contract(
            heat, ("select_profile_watch_pool", "final_score_and_tier", "compute_industry_heat_score"),
        )
        self.assertIn("PROFILE_WATCH_POOL_TOP_N", contract["bound_constants"])
        self.assertIn("UNKNOWN_INDUSTRY", contract["bound_constants"])

    def test_semantic_function_contract_is_narrow_exact_and_prose_insensitive(self):
        """A narrowed binding keeps prose-insensitivity and fails closed on a rename."""
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "narrow_probe.py"
            module = SimpleNamespace(__name__="narrow_probe")
            with mock.patch.object(epoch_mode.inspect, "getsourcefile", return_value=str(path)):
                path.write_text(
                    'def bound():\n    """old"""\n    return 1\n\n\ndef unbound():\n    return 9\n',
                    encoding="utf-8")
                baseline = epoch_mode.semantic_function_contract(module, ("bound",))
                self.assertEqual(baseline["bound_functions"], ["bound"])

                # prose inside the bound function, and any edit to an unbound one,
                # must both leave the contract alone.
                path.write_text(
                    '# header\ndef bound():\n    """new"""\n    return 1  # inline\n\n\n'
                    'def unbound():\n    return 10\n',
                    encoding="utf-8")
                self.assertEqual(epoch_mode.semantic_function_contract(module, ("bound",)), baseline)

                path.write_text(
                    'def bound():\n    return 2\n\n\ndef unbound():\n    return 9\n', encoding="utf-8")
                self.assertNotEqual(
                    epoch_mode.semantic_function_contract(module, ("bound",))["semantic_ast_sha256"],
                    baseline["semantic_ast_sha256"])

                with self.assertRaises(epoch_mode.EvidenceEpochModeError):
                    epoch_mode.semantic_function_contract(module, ("renamed_away",))
                with self.assertRaises(epoch_mode.EvidenceEpochModeError):
                    epoch_mode.semantic_function_contract(module, ())

    def test_p4a_semantic_exclusions_are_exact_and_enumerated(self):
        from engine import a_short_overlay_adjudication as p4a

        contract = epoch_mode.semantic_module_contract(
            p4a, excluded_functions=p4a.P4A_SEMANTIC_MODULE_EXCLUSIONS)
        functions = {
            node.name for node in ast.parse(
                Path(p4a.__file__).read_text(encoding="utf-8")).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertEqual(set(contract["excluded_functions"]), set(p4a.P4A_SEMANTIC_MODULE_EXCLUSIONS))
        self.assertEqual(functions,
                         set(contract["bound_functions"]) | set(p4a.P4A_SEMANTIC_MODULE_EXCLUSIONS))
        # the exclusions are the epoch machinery itself, nothing that shapes a result
        self.assertEqual(set(p4a.P4A_SEMANTIC_MODULE_EXCLUSIONS),
                         {"_today", "_epoch_context", "_contract_fingerprint", "_epoch_id"})

    def test_source_identity_scan_has_no_ungated_new_digest_path(self):
        """New source-digest callsites fail until their gate is explicitly audited."""
        for relative, expected_functions in SOURCE_IDENTITY_GETSOURCE_CALLS.items():
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            actual = set()
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if any(
                    isinstance(item, ast.Call)
                    and isinstance(item.func, ast.Attribute)
                    and isinstance(item.func.value, ast.Name)
                    and item.func.value.id == "inspect"
                    and item.func.attr == "getsource"
                    for item in ast.walk(node)
                ):
                    actual.add(node.name)
                for item in ast.walk(node):
                    if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) and \
                            item.func.attr == "read_bytes":
                        rendered = ast.unparse(item.func.value)
                        self.assertNotIn("__file__", rendered, f"source bytes bypass in {relative}:{node.name}")
                        self.assertNotIn(".py", rendered, f"source bytes bypass in {relative}:{node.name}")
            self.assertEqual(actual, expected_functions, relative)

        for relative, roots in SOURCE_IDENTITY_GATES.items():
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            functions = {
                node.name: node for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for root, required_call in roots.items():
                self.assertIn(root, functions, f"missing persisted source-identity root {relative}:{root}")
                calls = {
                    item.func.attr
                    for item in ast.walk(functions[root])
                    if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
                }
                self.assertIn(required_call, calls, f"ungated source identity {relative}:{root}")

        epoch_tree = ast.parse(
            (ROOT / "engine" / "a_short_evidence_epoch_mode.py").read_text(encoding="utf-8")
        )
        source_readers = set()
        for node in epoch_tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            attributes = {
                item.func.attr
                for item in ast.walk(node)
                if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
            }
            if "getsourcefile" in attributes:
                source_readers.add(node.name)
        self.assertEqual(source_readers, {"_module_source_text"})

    def test_enforcement_is_parked_not_deleted(self):
        """Flipping the mode back on must restore a real, drift-sensitive binding."""
        with patched_epoch_modes("frozen_enforced"):
            enforced = _fingerprints()
        with patched_epoch_modes("pre_freeze_audit_only"):
            parked = _fingerprints()
        self.assertEqual(sorted(enforced), sorted(parked))
        for component in enforced:
            self.assertNotEqual(enforced[component], parked[component], component)

    def test_unknown_mode_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "registry.json"
            modes = {track: "pre_freeze_audit_only" for track in epoch_mode.TRACKS}
            modes[epoch_mode.TRACKS[0]] = "something_else"
            path.write_text(json.dumps({
                "schema_name": "a_short_evidence_epoch_mode_registry",
                "schema_version": "1.0.0",
                "track_modes": modes,
            }), encoding="utf-8")
            with mock.patch.object(epoch_mode, "TRACK_MODE_REGISTRY_PATH", path):
                with self.assertRaises(epoch_mode.EvidenceEpochModeError):
                    epoch_mode.enforcement_enabled(epoch_mode.TRACKS[0])


class PreFreezeVerdictGateTests(unittest.TestCase):
    def test_p4a_threshold_evidence_gates_pre_freeze_then_re_arms(self):
        from engine.a_short_overlay_adjudication import _adjudicate
        rows = [_p4a_promotion_row(index) for index in range(24)]
        with patched_epoch_modes("pre_freeze_audit_only", ("p4a_overlay_adjudication",)):
            parked, parked_metrics = _adjudicate(rows, 24, 0)
        with patched_epoch_modes("frozen_enforced", ("p4a_overlay_adjudication",)):
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
            with patched_epoch_modes("pre_freeze_audit_only", ("p5_industry_weight",)):
                parked = p5._question_progress(Path("."), "balanced_vs_legacy", "20260727")
            with patched_epoch_modes("frozen_enforced", ("p5_industry_weight",)):
                enforced = p5._question_progress(Path("."), "balanced_vs_legacy", "20260727")
        # Same threshold-satisfying evidence both times: 12 eligible weeks, 12 with a real difference.
        self.assertEqual((parked["eligible_policy_weeks"], parked["difference_weeks"]), (12, 12))
        self.assertEqual((parked["p5b_build_due"], parked["p5b_checkpoint_notice"]), (False, "accumulating"))
        self.assertEqual((enforced["p5b_build_due"], enforced["p5b_checkpoint_notice"]),
                         (True, "p5b_implementation_due_at_12"))


class SemanticProjectionTests(unittest.TestCase):
    """The freeze packet gates on what decides, not on file bytes.

    Whole-file hashing meant an edit that could not change any verdict still
    discarded every accumulated week.  With eight remaining knives to land
    before the design settles, that made starting a 12-week clock impossible:
    row 11 rewrites the effect contract's leaf ledger, which decides nothing
    about a comparison verdict, and under byte hashing it would have thrown
    away the whole accumulation.
    """

    def _temp_tree(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for relative in epoch_mode._FIFTH_KNIFE_FROZEN_CONTRACTS.values():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((epoch_mode.ROOT / relative).read_bytes())
        return root

    def _fingerprint_after(self, root, name, mutate):
        relative = epoch_mode._FIFTH_KNIFE_FROZEN_CONTRACTS[name]
        path = root / relative
        with mock.patch.object(epoch_mode, "ROOT", root):
            before = epoch_mode.contract_semantic_fingerprint(name)
            mutate(path)
            after = epoch_mode.contract_semantic_fingerprint(name)
        return before, after

    @staticmethod
    def _rewrite_json(path, edit):
        document = json.loads(path.read_text(encoding="utf-8"))
        edit(document)
        path.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")

    def test_every_frozen_contract_declares_exactly_one_projection(self):
        self.assertEqual(set(epoch_mode._CONTRACT_PROJECTIONS),
                         set(epoch_mode._FIFTH_KNIFE_FROZEN_CONTRACTS))
        for name in epoch_mode._FIFTH_KNIFE_FROZEN_CONTRACTS:
            projection = epoch_mode.contract_semantic_projection(name)
            self.assertEqual(projection["projection"], epoch_mode._CONTRACT_PROJECTIONS[name])
            self.assertRegex(epoch_mode.contract_semantic_fingerprint(name), r"^[0-9a-f]{64}$")

    def test_rewriting_the_effect_contract_leaf_ledger_keeps_the_epoch(self):
        """Row 11 rewrites every one of these keys and decides nothing here."""
        root = self._temp_tree()

        def rewrite_ledger(document):
            document["leaf_effect_overrides"] = {"candidates[].invented": "true_dangling"}
            document["leaf_nature_by_group"] = {"market_context": "true_dangling"}
            document["groups"] = []
            document["analysis_input_paths"] = ["candidates[].invented"]
            document["analysis_input_all_paths_sha256"] = "f" * 64
            document["legacy_migration_sha256"] = "e" * 64

        before, after = self._fingerprint_after(
            root, "m67_effect_contract",
            lambda path: self._rewrite_json(path, rewrite_ledger),
        )
        self.assertEqual(before, after)

    def test_moving_the_effect_contract_decision_surface_breaks_the_epoch(self):
        """The other half of the same file does decide, and must still bite."""
        root = self._temp_tree()
        before, after = self._fingerprint_after(
            root, "m67_effect_contract",
            lambda path: self._rewrite_json(
                path,
                lambda document: document["decision_predicate_sha256"].update(
                    {"A-EGS/egs_main.py": "0" * 64}
                ),
            ),
        )
        self.assertNotEqual(before, after)

    def test_an_unclassified_effect_contract_key_is_bound_rather_than_ignored(self):
        """Over-binding costs one re-arm; under-binding turns stale evidence valid."""
        root = self._temp_tree()
        before, after = self._fingerprint_after(
            root, "m67_effect_contract",
            lambda path: self._rewrite_json(
                path,
                lambda document: document.update({"invented_decision_key": {"cap": 0.5}}),
            ),
        )
        self.assertNotEqual(before, after)

    def test_reformatting_and_annotating_a_schema_keeps_the_epoch(self):
        for name in ("weekly_report_schema", "v14_3_action_comparison_schema"):
            with self.subTest(contract=name):
                root = self._temp_tree()

                def annotate(document):
                    document["description"] = "reworded mid-design"
                    document["$comment"] = "and annotated"
                    document["title"] = "retitled"

                before, after = self._fingerprint_after(
                    root, name, lambda path: self._rewrite_json(path, annotate),
                )
                self.assertEqual(before, after)

    def test_a_validation_keyword_change_breaks_a_schema_epoch(self):
        root = self._temp_tree()
        before, after = self._fingerprint_after(
            root, "weekly_report_schema",
            lambda path: self._rewrite_json(
                path,
                lambda document: document["properties"].update(
                    {"__probe__": {"type": "string"}}
                ),
            ),
        )
        self.assertNotEqual(before, after)

    def test_reformatting_a_governance_preset_keeps_the_epoch(self):
        root = self._temp_tree()
        before, after = self._fingerprint_after(
            root, "a_short_m67_runtime_policy",
            lambda path: self._rewrite_json(
                path, lambda document: document.update({"description": "reworded"}),
            ),
        )
        self.assertEqual(before, after)

    def test_changing_a_governed_threshold_breaks_the_epoch(self):
        """Governance presets are small and every real value in them decides."""
        root = self._temp_tree()
        before, after = self._fingerprint_after(
            root, "a_short_m67_runtime_policy",
            lambda path: self._rewrite_json(
                path,
                lambda document: document["phase5"].update({"__probe_threshold__": 0.99}),
            ),
        )
        self.assertNotEqual(before, after)

    def test_a_comment_in_the_python_contract_keeps_the_epoch_but_code_breaks_it(self):
        root = self._temp_tree()
        relative = epoch_mode._FIFTH_KNIFE_FROZEN_CONTRACTS["p4a_overlay_epoch"]
        path = root / relative
        original = path.read_text(encoding="utf-8")

        with mock.patch.object(epoch_mode, "ROOT", root):
            before = epoch_mode.contract_semantic_fingerprint("p4a_overlay_epoch")
            path.write_text("# a comment added mid-design\n" + original, encoding="utf-8")
            commented = epoch_mode.contract_semantic_fingerprint("p4a_overlay_epoch")
            path.write_text(original + "\n\ndef __epoch_probe__():\n    return 1\n",
                            encoding="utf-8")
            recoded = epoch_mode.contract_semantic_fingerprint("p4a_overlay_epoch")

        self.assertEqual(before, commented, "a comment discarded evidence")
        self.assertNotEqual(before, recoded, "new executable code kept the old epoch")

    def test_the_python_projection_never_imports_or_consults_inspect(self):
        """Packet validation must not answer to a patched ``getsourcefile``.

        The overlay module imports this one, so importing it back would be a
        cycle; routing through ``inspect`` also let any caller's patch decide
        what the packet validates against.
        """
        with mock.patch.object(epoch_mode.inspect, "getsourcefile",
                               side_effect=AssertionError("inspect was consulted")):
            self.assertRegex(
                epoch_mode.contract_semantic_fingerprint("p4a_overlay_epoch"),
                r"^[0-9a-f]{64}$",
            )

    def test_semantic_drift_is_reported_with_the_contract_and_its_projection(self):
        """Losing evidence is sometimes right; losing it silently never is."""
        track = epoch_mode.TRACKS[0]
        with patched_epoch_modes("frozen_enforced", (track,)):
            packet_path = epoch_mode.FIFTH_KNIFE_FREEZE_PACKET_PATH
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            for entry in packet["frozen_contracts"]:
                if entry["name"] == "m67_effect_contract":
                    entry["semantic_fingerprint"] = "0" * 64
            packet["record_sha256"] = epoch_mode._canonical_json_sha256({
                key: value for key, value in packet.items() if key != "record_sha256"
            })
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            with self.assertRaisesRegex(
                epoch_mode.EvidenceEpochModeError,
                r"semantic drift: m67_effect_contract .*projection="
                r"json_effect_contract_decisions",
            ):
                epoch_mode.enforcement_enabled(track)

    def test_a_packet_projection_that_disagrees_with_the_code_is_rejected(self):
        """The packet says how it was sealed; the code is the authority."""
        track = epoch_mode.TRACKS[0]
        with patched_epoch_modes("pre_freeze_audit_only", (track,)):
            packet_path = epoch_mode.FIFTH_KNIFE_FREEZE_PACKET_PATH
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            for entry in packet["frozen_contracts"]:
                if entry["name"] == "weekly_report_schema":
                    entry["projection"] = "json_governance"
            packet["record_sha256"] = epoch_mode._canonical_json_sha256({
                key: value for key, value in packet.items() if key != "record_sha256"
            })
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            with self.assertRaisesRegex(
                epoch_mode.EvidenceEpochModeError,
                "projection mismatch: weekly_report_schema",
            ):
                epoch_mode.enforcement_enabled(track)


if __name__ == "__main__":
    unittest.main()
