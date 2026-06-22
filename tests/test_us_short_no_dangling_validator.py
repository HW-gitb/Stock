# -*- coding: utf-8 -*-
"""Tests for the US-short §10 no-dangling / evidence-traceback / field-registry validator
(engine/us_short_no_dangling_validator.py).

Adversarial focus (front-loaded completeness so review converges in one round): ONE failing fixture per
§10 invariant, each starting from a known-clean record and breaking exactly one thing — forward landing,
non-tag-must-land-on-column, core-field-must-hit-an-impact-target (with the shadow_record/dropped escape
as a positive control), risk-downgrade-soft-only, hard_veto-covers-final_action, reverse evidence
traceback (missing / bad-kind / empty-value / wrong-PIT-as_of / declaration-mismatch / unknown-claim),
registry completeness, operation_impact membership, and selection-vs-action_rank explanation. Plus a
malformed-input fail-closed sweep (never raises) and a triangulation proving the validator reads the
FROZEN governance presets (not a hardcoded copy).
"""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_no_dangling_validator as ndv  # noqa: E402

FR_PRESET = json.loads((ROOT / "presets" / "us_short_field_registry_governance_20260620.json").read_text(encoding="utf-8"))
AT_PRESET = json.loads((ROOT / "presets" / "us_short_action_table_contract_20260620.json").read_text(encoding="utf-8"))


def _field(**over):
    base = {
        "field_id": "f", "owner_module": "engine.us_short_x", "data_source": "FMP",
        "pit_basis": "prior_friday_close", "privacy_class": "public_universe",
        "current_landing_surface": "weekly_report.section", "terminal_surface_target": "risk_tags",
        "operation_impact": "仅标签", "evidence_ref_kind": None, "lifecycle_item_id": 7,
        "field_class": "structured_tag", "disposition": "landed",
        "impact_target": None, "claim_type": None, "evidence_ref": None,
    }
    base.update(over)
    return base


def _valid():
    """A fully §10-clean 2-row machine record exercising every load-bearing path."""
    aso = "20260622"
    veto = _field(field_id="sec_s3", field_class="hard veto", operation_impact="硬否决",
                  current_landing_surface="weekly_report.veto", terminal_surface_target="final_action",
                  disposition="landed", impact_target="final_action",
                  evidence_ref_kind="SEC filing", claim_type="S-3", lifecycle_item_id=17,
                  evidence_ref={"kind": "SEC filing", "value": "0000320193-S3", "as_of": aso})
    rdown = _field(field_id="rd", field_class="risk downgrade", operation_impact="降仓",
                   current_landing_surface="weekly_report.risk", terminal_surface_target="model_position_size_shares",
                   disposition="landed", impact_target="position_size", lifecycle_item_id=39)
    theme = _field(field_id="theme", field_class="theme_opportunity_state", operation_impact="调信心",
                   current_landing_surface="weekly_report.theme", terminal_surface_target="action_confidence",
                   disposition="landed", impact_target="action_confidence",
                   evidence_ref_kind="source_id", claim_type="赛道热度", lifecycle_item_id=8,
                   evidence_ref={"kind": "source_id", "value": "theme:ai_complex", "as_of": aso})
    demoted = _field(field_id="sel", field_class="selection", operation_impact="仅标签",
                     current_landing_surface="weekly_report.shadow", terminal_surface_target="shadow_record",
                     disposition="shadow_record", impact_target=None, lifecycle_item_id=1)
    plain = _field(field_id="tag", field_class="structured_tag", operation_impact="仅标签",
                   terminal_surface_target="risk_tags", lifecycle_item_id=None)
    return {
        "schema_name": "us_short_machine_record_contract", "schema_version": "1.0.0", "as_of": aso,
        "rows": [
            {"ticker": "BADCO", "row_source": "top15_candidate", "final_action": "否决/避开",
             "action_rank": 9, "selection_rank": 3, "decision_trace": "S-3 hard veto → 否决",
             "field_records": [veto]},
            {"ticker": "AAPL", "row_source": "holding_account_only", "final_action": "持有",
             "action_rank": 4, "selection_rank": None, "decision_trace": "theme strong; hold",
             "field_records": [rdown, theme, demoted, plain]},
        ],
    }


def _mut(fn):
    rec = _valid()
    fn(rec)
    return rec


# convenience accessors into _valid()'s structure
def _veto_fr(rec):
    return rec["rows"][0]["field_records"][0]


def _theme_fr(rec):
    return rec["rows"][1]["field_records"][1]


def _rdown_fr(rec):
    return rec["rows"][1]["field_records"][0]


class ValidBaseline(unittest.TestCase):
    def test_clean_record_passes_all_checks(self):
        out = ndv.validate_machine_record(_valid())
        self.assertTrue(out["clean"], out["violations"])
        self.assertTrue(all(out["checks"].values()), out["checks"])
        self.assertEqual(set(out["checks"]), set(ndv.PRE_GENERATION_CHECKS))


class ForwardNoDangling(unittest.TestCase):
    def test_empty_landing_is_dangling(self):
        out = ndv.validate_machine_record(_mut(lambda r: _veto_fr(r).__setitem__("current_landing_surface", "")))
        self.assertFalse(out["clean"])
        self.assertFalse(out["checks"]["every_field_has_landing"])
        self.assertFalse(out["checks"]["no_dangling"])

    def test_whitespace_landing_is_dangling(self):
        out = ndv.validate_machine_record(_mut(lambda r: _veto_fr(r).__setitem__("current_landing_surface", "   ")))
        self.assertFalse(out["checks"]["every_field_has_landing"])

    def test_non_tag_impact_must_land_on_a_column(self):
        # 降仓 (non-tag) pointing at a non-column terminal must fail no_dangling
        out = ndv.validate_machine_record(_mut(lambda r: _rdown_fr(r).__setitem__("terminal_surface_target", "some_made_up_label")))
        self.assertFalse(out["checks"]["no_dangling"])

    def test_empty_terminal_is_dangling(self):
        out = ndv.validate_machine_record(_mut(lambda r: _veto_fr(r).__setitem__("terminal_surface_target", "")))
        self.assertFalse(out["checks"]["no_dangling"])

    def test_tag_may_land_on_advisory_label(self):  # positive control
        out = ndv.validate_machine_record(
            _mut(lambda r: r["rows"][1]["field_records"][3].__setitem__("terminal_surface_target", "advisory_label")))
        self.assertTrue(out["clean"], out["violations"])

    def test_tag_on_garbage_terminal_is_dangling(self):
        out = ndv.validate_machine_record(
            _mut(lambda r: r["rows"][1]["field_records"][3].__setitem__("terminal_surface_target", "garbage")))
        self.assertFalse(out["checks"]["no_dangling"])


class CoreFieldImpact(unittest.TestCase):
    def test_core_field_landed_without_impact_target_dangles(self):
        out = ndv.validate_machine_record(_mut(lambda r: _theme_fr(r).__setitem__("impact_target", None)))
        self.assertFalse(out["checks"]["no_dangling"])

    def test_core_field_impact_target_must_be_in_the_frozen_set(self):
        out = ndv.validate_machine_record(_mut(lambda r: _theme_fr(r).__setitem__("impact_target", "made_up_target")))
        self.assertFalse(out["checks"]["no_dangling"])

    def test_core_field_shadow_record_escape_is_clean(self):  # positive control: the §10 escape hatch
        def demote(r):
            fr = _theme_fr(r)
            fr["disposition"] = "shadow_record"
            fr["impact_target"] = None
            fr["operation_impact"] = "仅标签"
            fr["terminal_surface_target"] = "shadow_record"
        out = ndv.validate_machine_record(_mut(demote))
        self.assertTrue(out["clean"], out["violations"])

    def test_core_field_bad_disposition_dangles(self):
        out = ndv.validate_machine_record(_mut(lambda r: _theme_fr(r).__setitem__("disposition", "maybe")))
        self.assertFalse(out["checks"]["no_dangling"])


class RiskDowngradeSoftOnly(unittest.TestCase):
    def test_risk_downgrade_cannot_be_hard_veto(self):
        out = ndv.validate_machine_record(_mut(lambda r: _rdown_fr(r).__setitem__("operation_impact", "硬否决")))
        self.assertFalse(out["checks"]["risk_downgrade_affects_size_confidence_or_tag"])

    def test_risk_downgrade_target_must_be_size_confidence_or_tag(self):
        out = ndv.validate_machine_record(_mut(lambda r: _rdown_fr(r).__setitem__("impact_target", "final_action")))
        self.assertFalse(out["checks"]["risk_downgrade_affects_size_confidence_or_tag"])

    def test_risk_downgrade_onto_action_confidence_is_clean(self):  # positive control
        def to_conf(r):
            fr = _rdown_fr(r)
            fr["impact_target"] = "action_confidence"
            fr["operation_impact"] = "调信心"
            fr["terminal_surface_target"] = "action_confidence"
        out = ndv.validate_machine_record(_mut(to_conf))
        self.assertTrue(out["clean"], out["violations"])


class HardVetoCoversFinalAction(unittest.TestCase):
    def test_hard_veto_must_reach_a_kill_or_exit_action(self):
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][0].__setitem__("final_action", "持有")))
        self.assertFalse(out["checks"]["hard_veto_covers_final_action"])

    def test_hard_veto_with_clear_action_is_clean(self):  # positive control (holding forced exit)
        def hold_veto(r):
            r["rows"][0]["row_source"] = "holding_account_only"
            r["rows"][0]["final_action"] = "清仓-事件"
        out = ndv.validate_machine_record(_mut(hold_veto))
        self.assertTrue(out["clean"], out["violations"])

    def test_no_hard_veto_hold_is_clean(self):  # reverse control: check only fires when a hard veto exists
        out = ndv.validate_machine_record(_valid())  # row[1] is 持有 with no hard veto
        self.assertTrue(out["checks"]["hard_veto_covers_final_action"])


class EvidenceTraceback(unittest.TestCase):
    def test_claim_without_evidence_ref_is_unevidenced(self):
        out = ndv.validate_machine_record(_mut(lambda r: _theme_fr(r).__setitem__("evidence_ref", None)))
        self.assertFalse(out["checks"]["every_claim_traceable"])
        self.assertFalse(out["checks"]["no_unevidenced_claim"])

    def test_claim_with_bad_ref_kind(self):
        out = ndv.validate_machine_record(
            _mut(lambda r: _theme_fr(r)["evidence_ref"].__setitem__("kind", "rumor")))
        self.assertFalse(out["checks"]["every_claim_traceable"])

    def test_claim_with_empty_ref_value(self):
        out = ndv.validate_machine_record(
            _mut(lambda r: _theme_fr(r)["evidence_ref"].__setitem__("value", "")))
        self.assertFalse(out["checks"]["no_unevidenced_claim"])

    def test_claim_evidence_as_of_must_match_record_pit(self):
        out = ndv.validate_machine_record(
            _mut(lambda r: _theme_fr(r)["evidence_ref"].__setitem__("as_of", "20260101")))
        self.assertFalse(out["checks"]["every_claim_traceable"])

    def test_claim_evidence_as_of_must_be_strict_yyyymmdd(self):
        out = ndv.validate_machine_record(
            _mut(lambda r: _theme_fr(r)["evidence_ref"].__setitem__("as_of", "20260231")))  # impossible date
        self.assertFalse(out["checks"]["every_claim_traceable"])

    def test_unknown_claim_type(self):
        out = ndv.validate_machine_record(_mut(lambda r: _theme_fr(r).__setitem__("claim_type", "传闻")))
        self.assertFalse(out["checks"]["every_claim_traceable"])
        self.assertFalse(out["checks"]["no_unevidenced_claim"])

    def test_declared_ref_kind_must_match_actual(self):
        out = ndv.validate_machine_record(_mut(lambda r: _theme_fr(r).__setitem__("evidence_ref_kind", "provider row")))
        self.assertFalse(out["checks"]["every_claim_traceable"])

    def test_non_claim_field_needs_no_evidence(self):  # positive control
        out = ndv.validate_machine_record(_valid())  # rdown / demoted / plain carry no claim_type
        self.assertTrue(out["checks"]["no_unevidenced_claim"])


class RegistryCompletenessAndMembership(unittest.TestCase):
    def test_missing_registry_key_dangles(self):
        out = ndv.validate_machine_record(_mut(lambda r: _veto_fr(r).pop("owner_module")))
        self.assertFalse(out["checks"]["no_dangling"])

    def test_operation_impact_must_be_a_frozen_level(self):
        out = ndv.validate_machine_record(_mut(lambda r: _veto_fr(r).__setitem__("operation_impact", "自动清仓")))
        self.assertFalse(out["checks"]["no_dangling"])


class SelectionVsActionRank(unittest.TestCase):
    def test_missing_decision_trace_is_unexplained(self):
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1].__setitem__("decision_trace", "")))
        self.assertFalse(out["checks"]["selection_vs_action_rank_explained"])

    def test_decision_trace_present_is_explained(self):  # positive control
        out = ndv.validate_machine_record(_valid())
        self.assertTrue(out["checks"]["selection_vs_action_rank_explained"])


class MalformedInputFailsClosed(unittest.TestCase):
    """REVERSE-FAILURE: malformed public-API input must fail closed (clean False) and NEVER raise."""

    def test_non_dict_record(self):
        for bad in (None, "x", 5, ["rows"]):
            out = ndv.validate_machine_record(bad)
            self.assertFalse(out["clean"], repr(bad))

    def test_rows_not_a_list(self):
        out = ndv.validate_machine_record({"as_of": "20260622", "rows": {"a": 1}})
        self.assertFalse(out["clean"])

    def test_row_not_a_dict(self):
        out = ndv.validate_machine_record({"as_of": "20260622", "rows": ["notarow", 7, None]})
        self.assertFalse(out["clean"])

    def test_field_records_not_a_list(self):
        rec = _valid()
        rec["rows"][0]["field_records"] = "nope"
        self.assertFalse(ndv.validate_machine_record(rec)["clean"])

    def test_field_record_not_a_dict(self):
        rec = _valid()
        rec["rows"][0]["field_records"] = ["bad", 1, None]
        self.assertFalse(ndv.validate_machine_record(rec)["clean"])

    def test_claim_evidence_ref_not_a_dict(self):
        out = ndv.validate_machine_record(_mut(lambda r: _theme_fr(r).__setitem__("evidence_ref", "0000-S3")))
        self.assertFalse(out["checks"]["every_claim_traceable"])

    def test_missing_as_of_with_claim_does_not_crash(self):
        rec = _valid()
        rec.pop("as_of")
        out = ndv.validate_machine_record(rec)  # must not raise; PIT-equality check just skipped
        self.assertIn("clean", out)


class ActionTableVocab(unittest.TestCase):
    """R-USSHORT-BATCH3-ACTION-TABLE-VOCAB-BYPASS: any present row field with a frozen action_table enum
    must be a member; required row_source/final_action especially. Optional empty categoricals stay OK."""

    def test_invalid_final_action_without_hard_veto_fails(self):
        # Codex's exact probe: the non-hard-veto holding row with a garbage final_action
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1].__setitem__("final_action", "invalid_action")))
        self.assertFalse(out["clean"])
        self.assertFalse(out["checks"]["no_dangling"])

    def test_invalid_row_source_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1].__setitem__("row_source", "made_up_source")))
        self.assertFalse(out["clean"])

    def test_invalid_optional_enum_field_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1].__setitem__("coverage_status", "totally_covered")))
        self.assertFalse(out["clean"])

    def test_valid_optional_enum_field_is_clean(self):  # positive control
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1].__setitem__("coverage_status", "full")))
        self.assertTrue(out["clean"], out["violations"])

    def test_empty_optional_enum_is_not_false_failed(self):  # reverse control: legit not-applicable empty
        self.assertTrue(ndv.validate_machine_record(_mut(lambda r: r["rows"][1].__setitem__("observe_reason_type", None)))["clean"])
        self.assertTrue(ndv.validate_machine_record(_mut(lambda r: r["rows"][1].__setitem__("observe_reason_type", "")))["clean"])

    def test_empty_required_action_field_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1].__setitem__("final_action", "")))
        self.assertFalse(out["clean"])

    def test_baseline_vocab_is_valid(self):  # positive control
        self.assertTrue(ndv.validate_machine_record(_valid())["clean"])


class RunLevelPitAndClaimDeclaration(unittest.TestCase):
    """R-USSHORT-BATCH3-PIT-EVIDENCE-TRACEBACK-GAP: the run-level as_of PIT anchor must be a strict real
    date even with NO claims, and a claim must carry a registry-declared evidence_ref_kind."""

    def _strip_claims(self, r):
        for row in r["rows"]:
            for fr in row["field_records"]:
                fr["claim_type"] = None
                fr["evidence_ref"] = None
                fr["evidence_ref_kind"] = None

    def test_impossible_run_as_of_with_no_claims_fails(self):
        def f(r):
            self._strip_claims(r)      # isolate: the bad run-level as_of is the ONLY issue
            r["as_of"] = "20260231"    # 8 digits (schema-valid) but an impossible calendar date
        out = ndv.validate_machine_record(_mut(f))
        self.assertFalse(out["clean"])
        self.assertFalse(out["checks"]["no_dangling"])

    def test_missing_run_as_of_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r.pop("as_of")))
        self.assertFalse(out["clean"])
        self.assertFalse(out["checks"]["no_dangling"])

    def test_valid_run_as_of_is_clean(self):  # positive control
        self.assertTrue(ndv.validate_machine_record(_valid())["clean"])

    def test_claim_without_declared_evidence_ref_kind_fails(self):
        # Codex's probe: a claim whose registry declaration evidence_ref_kind is None (runtime kind valid)
        out = ndv.validate_machine_record(_mut(lambda r: _theme_fr(r).__setitem__("evidence_ref_kind", None)))
        self.assertFalse(out["clean"])
        self.assertFalse(out["checks"]["every_claim_traceable"])

    def test_claim_declared_kind_not_a_frozen_kind_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: _theme_fr(r).__setitem__("evidence_ref_kind", "hearsay")))
        self.assertFalse(out["checks"]["every_claim_traceable"])

    def test_non_claim_field_may_have_null_declaration(self):  # positive control: nullable kept for non-claims
        # rdown / demoted / plain are non-claims carrying evidence_ref_kind=None — must stay clean
        self.assertTrue(ndv.validate_machine_record(_valid())["clean"])


class MissingRequiredFields(unittest.TestCase):
    """R-USSHORT-BATCH3-MACHINE-RECORD-REQUIRED-FIELD-BYPASS: a record missing a schema-required row key or
    field-record key must fail closed (clean=False) — the clean gate does NOT rely on the schema."""

    def test_missing_ticker_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1].pop("ticker")))
        self.assertFalse(out["clean"])
        self.assertFalse(out["checks"]["no_dangling"])

    def test_missing_row_source_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1].pop("row_source")))
        self.assertFalse(out["clean"])

    def test_missing_final_action_fails(self):
        # Codex's probe: a row with NO final_action at all (the vocab loop used to skip absent keys → clean=True)
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1].pop("final_action")))
        self.assertFalse(out["clean"])
        self.assertFalse(out["checks"]["no_dangling"])

    def test_missing_field_class_on_plain_record_fails(self):
        # the plain (non-core, non-claim) field record — no class-specific branch would otherwise fire
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1]["field_records"][3].pop("field_class")))
        self.assertFalse(out["clean"])
        self.assertFalse(out["checks"]["no_dangling"])

    def test_missing_disposition_on_plain_record_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1]["field_records"][3].pop("disposition")))
        self.assertFalse(out["clean"])

    def test_blank_field_class_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1]["field_records"][3].__setitem__("field_class", "")))
        self.assertFalse(out["clean"])

    def test_missing_nullable_registry_key_still_required_present(self):
        # evidence_ref_kind may be null but the KEY must be present
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1]["field_records"][3].pop("evidence_ref_kind")))
        self.assertFalse(out["clean"])

    def test_baseline_has_all_required_fields(self):  # positive control
        self.assertTrue(ndv.validate_machine_record(_valid())["clean"])


class StructuralGate(unittest.TestCase):
    """The validator runs the machine_record schema as a structural gate, so wrong types /
    additionalProperties / const / enum violations fail closed — not only the hand-rolled semantic checks."""

    def test_wrong_type_action_rank_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1].__setitem__("action_rank", "five")))
        self.assertFalse(out["clean"])

    def test_wrong_type_risk_tags_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1].__setitem__("risk_tags", "notalist")))
        self.assertFalse(out["clean"])

    def test_field_record_stray_key_fails(self):
        # field_record additionalProperties=false — a stray key would otherwise pass the semantic checks
        out = ndv.validate_machine_record(_mut(lambda r: _theme_fr(r).__setitem__("surprise", 1)))
        self.assertFalse(out["clean"])

    def test_top_level_stray_key_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r.__setitem__("surprise", 1)))
        self.assertFalse(out["clean"])

    def test_wrong_schema_name_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r.__setitem__("schema_name", "wrong")))
        self.assertFalse(out["clean"])

    def test_missing_schema_name_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r.pop("schema_name")))
        self.assertFalse(out["clean"])

    def test_missing_schema_version_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r.pop("schema_version")))
        self.assertFalse(out["clean"])

    def test_invalid_schema_version_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r.__setitem__("schema_version", "v1")))
        self.assertFalse(out["clean"])

    def test_non_claim_evidence_ref_wrong_type_fails(self):
        # Codex probe: a NON-claim field with evidence_ref as a string — the semantic claim block never
        # inspects it (not a claim), so only the structural gate catches it.
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1]["field_records"][3].__setitem__("evidence_ref", "0000-S3")))
        self.assertFalse(out["clean"])

    def test_non_claim_evidence_ref_missing_keys_fails(self):
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1]["field_records"][3].__setitem__("evidence_ref", {})))
        self.assertFalse(out["clean"])

    def test_disposition_enum_on_plain_non_core_field_fails(self):
        # the plain non-core field: the semantic core-branch never checks its disposition; the gate does
        out = ndv.validate_machine_record(_mut(lambda r: r["rows"][1]["field_records"][3].__setitem__("disposition", "weird")))
        self.assertFalse(out["clean"])

    def test_structurally_valid_record_passes(self):  # positive control
        self.assertTrue(ndv.validate_machine_record(_valid())["clean"])


class LifecycleLinkAndAnyHardVeto(unittest.TestCase):
    """§10 registry-link integrity + any-硬否决 reaches final_action (holes beyond the named Codex findings)."""

    def test_lifecycle_item_id_must_resolve_to_13_1(self):
        out = ndv.validate_machine_record(_mut(lambda r: _theme_fr(r).__setitem__("lifecycle_item_id", 99)))
        self.assertFalse(out["clean"])
        self.assertFalse(out["checks"]["no_dangling"])

    def test_lifecycle_item_id_null_is_ok(self):  # positive control (no calibration link)
        out = ndv.validate_machine_record(_mut(lambda r: _theme_fr(r).__setitem__("lifecycle_item_id", None)))
        self.assertTrue(out["clean"], out["violations"])

    def test_any_hard_veto_impact_must_reach_final_action(self):
        # a NON-hard-veto field_class (theme_opportunity_state) emitting 硬否决 must still force a kill/exit
        # final_action; row[1] is a 持有 holding, so this must fail hard_veto_covers (it did NOT before).
        out = ndv.validate_machine_record(_mut(lambda r: _theme_fr(r).__setitem__("operation_impact", "硬否决")))
        self.assertFalse(out["clean"])
        self.assertFalse(out["checks"]["hard_veto_covers_final_action"])

    def test_hard_veto_impact_with_exit_action_is_clean(self):  # positive control
        def f(r):
            _theme_fr(r)["operation_impact"] = "硬否决"
            r["rows"][1]["final_action"] = "清仓-事件"
        out = ndv.validate_machine_record(_mut(f))
        self.assertTrue(out["clean"], out["violations"])


class FrozenPresetIsSingleSource(unittest.TestCase):
    """The validator must READ the frozen vocab from the presets, not hardcode it."""

    def test_native_subsets_triangulate_to_frozen_sets(self):
        self.assertIn(ndv.TAG_LEVEL, FR_PRESET["operation_impact_levels"])
        self.assertTrue(set(ndv.RISK_DOWNGRADE_TARGETS) <= set(FR_PRESET["impact_targets"]))
        self.assertTrue(set(ndv.KILL_OR_EXIT_ACTIONS) <= set(AT_PRESET["design_locked_enums"]["final_action"]))

    def test_validator_uses_injected_registry_not_a_hardcoded_copy(self):
        # same record: clean under the real presets, but if we inject a registry whose levels omit 降仓/硬否决/调信心,
        # those operation_impacts are suddenly unknown -> not clean. Proves membership comes from the loaded set.
        self.assertTrue(ndv.validate_machine_record(_valid())["clean"])
        narrow = copy.deepcopy(FR_PRESET)
        narrow["operation_impact_levels"] = ["仅标签"]
        out = ndv.validate_machine_record(_valid(), field_registry=narrow)
        self.assertFalse(out["clean"])


if __name__ == "__main__":
    unittest.main()
