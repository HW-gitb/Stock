# -*- coding: utf-8 -*-
"""US-short §10 no-dangling + evidence-traceback + field-registry validator (batch-3 cut 1).

Design authority: docs/us_short_system_design.md §10 (不悬空 + 证据反查 + 字段 registry, 机器强制) and
§11.1 (machine layer = operation_impact + 全字段 + 原始分数 + decision_trace + registry → runs_private).

What it enforces on a machine record (the cross-field §10 invariants draft-07 cannot express):

  * 正向 no-dangling — every computed field declares a non-empty landing; a non-tag operation_impact
    must land on a real action_table column; an advisory/shadow explanatory label is a valid landing
    ONLY for the soft 仅标签 level (no_dangling_policy).
  * 核心字段命中 — a field whose field_class is one of the §10 core classes must, when landed, hit one
    of the 6 impact targets; otherwise it must be demoted to shadow_record or dropped (else it dangles).
  * 反向证据反查 — every claim (临近财报 / S-3 / FDA / 做空报告 / 赛道热度 / 新闻催化) must trace to a
    provider row / SEC filing / source_id with a non-empty value at the record's PIT as_of; an
    untraceable claim must NOT be emitted as an operation impact (evidence_traceback_policy).
  * registry 完整 — each field_record carries the 10 const-pinned registry keys, and every non-null
    lifecycle_item_id resolves against the §13.1 calibration registry (1..39); null = no calibration link.
  * structural contract gate — the whole machine record is validated against its draft-07 schema, so
    wrong types, missing/extra (additionalProperties) keys, the disposition enum, schema_name, and the
    evidence_ref / as_of shape all fail closed; the hand-rolled semantic checks ADD the cross-field §10
    logic the schema cannot express.
  * 报告生成前必检 — the 7 pre_generation_checks; failure ⟹ report not clean.

Single source of truth: the FROZEN governance presets — this module READS the vocab
(operation_impact levels, core_field_classes, impact_targets, evidence_claim_types, evidence_ref_kinds,
registry_record_fields, action_table columns) from us_short_field_registry_governance +
us_short_action_table_contract. It does NOT hardcode a copy of those sets (no third drift surface). The
few validator-native subsets (TAG_LEVEL / the kill-or-exit final_action subset / the risk-downgrade
soft targets) are triangulated against the frozen sets in the tests.

Pure / offline: this module performs NO I/O beyond reading the two tracked governance presets and does
NOT persist anything. The §18.0 P0 fail-closed private-path guard (engine/us_short_private_paths.py) is
wired by the first batch-3 cut that actually writes a private artifact (machine-record writer / renderer),
not here. Malformed input fails closed (report not clean) and never raises.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
_FIELD_REGISTRY_PRESET = ROOT / "presets" / "us_short_field_registry_governance_20260620.json"
_ACTION_TABLE_PRESET = ROOT / "presets" / "us_short_action_table_contract_20260620.json"
_LIFECYCLE_PRESET = ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json"
_MACHINE_RECORD_SCHEMA = ROOT / "schemas" / "us_short_machine_record_contract.schema.json"

# Validator-native semantic groupings (triangulated ⊆ the frozen sets in the tests, so a rename of the
# frozen vocab fails the test rather than silently diverging here).
TAG_LEVEL = "仅标签"  # the one operation_impact level for which an advisory/shadow label is a valid landing
RISK_DOWNGRADE_TARGETS = frozenset({"action_rank", "position_size", "action_confidence", "risk_tags"})  # §4.2 selection-score / §5.2 soft-only
KILL_OR_EXIT_ACTIONS = frozenset({"否决/避开", "清仓-止损", "清仓-止盈", "清仓-事件", "减仓"})  # a hard veto must reach one of these
ADVISORY_LANDINGS = frozenset({"advisory_label", "shadow_record", "report_banner"})  # recognized non-column soft landings
NULLABLE_REGISTRY_KEYS = frozenset({"evidence_ref_kind", "lifecycle_item_id"})  # required-present but may be null

PRE_GENERATION_CHECKS = (
    "every_field_has_landing",
    "every_claim_traceable",
    "hard_veto_covers_final_action",
    "risk_downgrade_affects_size_confidence_or_tag",
    "selection_vs_action_rank_explained",
    "no_dangling",
    "no_unevidenced_claim",
)

_CACHE: dict = {}


def _load_preset(path, key):
    if key not in _CACHE:
        _CACHE[key] = json.loads(Path(path).read_text(encoding="utf-8"))
    return _CACHE[key]


def _strict_yyyymmdd(s) -> bool:
    """Exact 8 ASCII digits + a real calendar date (strptime alone parses 2024011 leniently)."""
    if not isinstance(s, str) or len(s) != 8 or not s.isascii() or not s.isdigit():
        return False
    try:
        datetime.strptime(s, "%Y%m%d")
        return True
    except ValueError:
        return False


def _nonempty_str(x) -> bool:
    return isinstance(x, str) and bool(x.strip())


def _result(violations):
    checks = {c: True for c in PRE_GENERATION_CHECKS}
    for v in violations:
        checks[v["check"]] = False
    return {"clean": not violations, "checks": checks, "violations": violations}


# §10 per-row field-registry MANIFEST (R-USSHORT-BATCH4-MACHINE-REGISTRY-COMPLETENESS-GAP) — the assembler's
# _SPECS field_ids. Used ONLY by the OFFICIAL gate `validate_official_machine_record` (producer + every official
# consumer), NEVER by the bare generic `validate_machine_record`, which stays field_id-agnostic by design (its
# docstring forbids a hardcoded producer-vocab copy; its _valid() fixtures use arbitrary ids deliberately).
MANIFEST_FIELD_IDS = frozenset({
    "hard_veto", "price", "market_risk_regime", "core_score", "risk_downgrade", "sizing",
    "theme_lifecycle_state", "theme_opportunity_state", "forward_event", "event_data_gap",
    "portfolio_guard", "symbol_cooldown",
})
_BUILD_ACTIONS = frozenset({"建仓", "加仓"})  # a build is by contract a scored + sized candidate (§8 / machine-record)


def official_expected_field_ids(row):
    """The §10 manifest an OFFICIAL machine-record decision row MUST carry — used by the official gate, NOT the
    generic validator. UNCONDITIONAL floor: hard_veto / price / market_risk_regime are evaluated for EVERY
    decision row, so they are required regardless of row content and CANNOT be stripped to forge an empty /
    partial registry (this is what closes the evidence-strip bypass; an earlier evidence-gated manifest could be
    defeated by deleting the gating field). A 建仓/加仓 additionally requires core_score + sizing — a build is by
    contract a scored, sized candidate and `final_action` is a required non-blank identity key, so this is robust
    too. The remaining fields are required when the row carries that evidence (a holding has no selection score;
    an unsized row no sizing): this catches a record dropped while its evidence still rides along."""
    if not isinstance(row, dict):
        return set()
    expected = {"hard_veto", "price", "market_risk_regime"}
    if row.get("final_action") in _BUILD_ACTIONS:
        expected.update(("core_score", "risk_downgrade", "sizing"))   # a build is a scored candidate (§4.2 penalty)
    if isinstance(row.get("score"), dict):
        expected.update(("core_score", "risk_downgrade"))             # every scored candidate carries the §4.2 penalty
    sizing = row.get("sizing")
    if isinstance(sizing, dict) and sizing.get("status") == "sized":
        expected.add("sizing")
    if isinstance(row.get("theme_probe"), dict):
        expected.update(("theme_lifecycle_state", "theme_opportunity_state"))
    if isinstance(row.get("forward_event"), dict):
        expected.add("forward_event")
    if isinstance(row.get("event_data_gap"), dict):
        expected.add("event_data_gap")
    if "result_effects" in row:
        expected.update(("portfolio_guard", "symbol_cooldown"))
    return expected


def validate_machine_record(record, *, field_registry=None, action_table=None) -> dict:
    """Validate a US-short machine record against the §10 contract.

    Returns {"clean": bool, "checks": {<7 pre_generation_checks>: bool}, "violations": [ ... ]}.
    clean is True only when there are zero violations. Malformed input fails closed (clean False),
    never raises. Pass field_registry / action_table dicts to inject governance (tests); by default the
    frozen presets are read from the repo.
    """
    fr = field_registry if field_registry is not None else _load_preset(_FIELD_REGISTRY_PRESET, "fr")
    at = action_table if action_table is not None else _load_preset(_ACTION_TABLE_PRESET, "at")

    levels = set(fr.get("operation_impact_levels", []))
    core_classes = set(fr.get("core_field_classes", []))
    targets = set(fr.get("impact_targets", []))
    claim_types = set(fr.get("evidence_claim_types", []))
    ref_kinds = set(fr.get("evidence_ref_kinds", []))
    registry_fields = list(fr.get("registry_record_fields", []))
    at_columns = set(at.get("core_columns", []))
    design_enums = {c: set(v) for c, v in at.get("design_locked_enums", {}).items() if isinstance(v, list)}
    valid_lifecycle_ids = {it.get("number") for it in
                           _load_preset(_LIFECYCLE_PRESET, "lifecycle").get("calibration_items", [])
                           if isinstance(it, dict)}
    non_tag_levels = levels - {TAG_LEVEL}

    violations: list = []

    def add(check, where, reason):
        violations.append({"check": check, "where": where, "reason": reason})

    if not isinstance(record, dict):
        add("no_dangling", "record", "machine record is not a dict")
        return _result(violations)

    # structural contract gate: validate the whole record against the machine_record draft-07 schema, so
    # wrong types, missing/extra (additionalProperties) keys, the disposition enum, schema_name const, and
    # the evidence_ref / as_of shape all fail closed. The semantic §10 checks below still run (defensive) to
    # ADD the cross-field logic the schema cannot express; both layers report into `violations`.
    machine_schema = _load_preset(_MACHINE_RECORD_SCHEMA, "machine_schema")
    for err in jsonschema.Draft7Validator(machine_schema).iter_errors(record):
        loc = "/".join(str(p) for p in err.absolute_path) or "record"
        add("no_dangling", loc, "machine-record schema violation: %s" % err.message)

    rec_as_of = record.get("as_of")
    if not _strict_yyyymmdd(rec_as_of):
        # the run-level as_of is the record's PIT anchor — a missing / malformed / impossible date
        # (the schema regex only checks 8 digits, so 20260231 passes IT) makes the record not clean,
        # INDEPENDENT of whether any row carries a claim.
        add("no_dangling", "record.as_of",
            "run-level as_of %r is not a strict real YYYYMMDD PIT anchor" % (rec_as_of,))
    rows = record.get("rows")
    if not isinstance(rows, list):
        add("no_dangling", "record.rows", "rows is not a list")
        return _result(violations)

    for ri, row in enumerate(rows):
        rwhere = "rows[%d]" % ri
        if not isinstance(row, dict):
            add("no_dangling", rwhere, "row is not a dict")
            continue
        ticker = row.get("ticker")
        rid = ticker if _nonempty_str(ticker) else rwhere
        final_action = row.get("final_action")

        # schema-required row keys must be present + non-blank — the clean gate fails closed ITSELF, it does
        # NOT rely on the schema (R-USSHORT-BATCH3-MACHINE-RECORD-REQUIRED-FIELD-BYPASS): ticker / row_source /
        # final_action missing OR blank → not clean (field_records is checked as a list just below).
        for k in ("ticker", "row_source", "final_action"):
            if not _nonempty_str(row.get(k)):
                add("no_dangling", rid, "row required field %s is missing or blank" % k)

        # action-table frozen vocab: any PRESENT, non-empty row field that has a design-locked enum MUST be a
        # member. Missing/blank for the required keys is handled above; an empty OPTIONAL categorical
        # (observe_reason_type / coverage_status / …) is a legitimate NA — skipped, NOT false-failed.
        for col, allowed in design_enums.items():
            cv = row.get(col)
            if cv is None or cv == "":
                continue
            if cv not in allowed:
                add("no_dangling", rid, "%s=%r outside the frozen action_table vocab" % (col, cv))

        # selection_vs_action_rank_explained: every decision row must carry a non-empty decision_trace —
        # that is where the deliberate selection_rank (多强) vs action_rank (先干哪个) divergence is explained
        # (§9: a holding forced-exit can outrank a stronger new buy). No trace ⟹ the divergence is unexplained.
        if not _nonempty_str(row.get("decision_trace")):
            add("selection_vs_action_rank_explained", rid, "row has no non-empty decision_trace")

        field_records = row.get("field_records")
        if not isinstance(field_records, list):
            add("no_dangling", rid, "field_records is not a list")
            continue

        # 反向完整性 — duplicate registry record (R-USSHORT-BATCH4-MACHINE-REGISTRY-COMPLETENESS-GAP): a
        # field_id must appear AT MOST once per row (the assembler's set-based expected/emitted reconciliation
        # cannot see a duplicate; this generic list-based check does, on every validation path). The field_id
        # presence/blank gate runs per-record below; here we only flag a repeated non-blank id.
        _seen_fids: dict = {}
        for frec in field_records:
            if isinstance(frec, dict) and _nonempty_str(frec.get("field_id")):
                _fidk = frec["field_id"]
                _seen_fids[_fidk] = _seen_fids.get(_fidk, 0) + 1
        for _fidk, _cnt in _seen_fids.items():
            if _cnt > 1:
                add("no_dangling", rid, "field_record field_id %r appears %d times (duplicate registry record)" % (_fidk, _cnt))

        row_has_hard_veto = False
        for fi, frec in enumerate(field_records):
            fwhere = "%s.field_records[%d]" % (rid, fi)
            if not isinstance(frec, dict):
                add("no_dangling", fwhere, "field_record is not a dict")
                continue
            fid = frec.get("field_id")
            wid = fid if _nonempty_str(fid) else fwhere

            # registry 完整 + structural completeness: every schema-required field-record key must be present,
            # and the non-nullable string keys non-blank — INCL field_class / disposition (the class-specific
            # branches below would otherwise skip them on a plain / non-core record), so a structurally
            # incomplete field record can never pass the clean gate (R-USSHORT-BATCH3-MACHINE-RECORD-REQUIRED-FIELD-BYPASS).
            for k in registry_fields:
                if k in NULLABLE_REGISTRY_KEYS:
                    if k not in frec:
                        add("no_dangling", wid, "field_record missing required key %s" % k)
                elif not _nonempty_str(frec.get(k)):
                    add("no_dangling", wid, "field_record required key %s is missing or blank" % k)
            for k in ("field_class", "disposition"):
                if not _nonempty_str(frec.get(k)):
                    add("no_dangling", wid, "field_record required key %s is missing or blank" % k)

            # §10 registry link: a non-null lifecycle_item_id must resolve against the §13.1 calibration
            # registry (1..39); null = no calibration link (allowed). A non-resolving id is a dangling link.
            lc = frec.get("lifecycle_item_id")
            if lc is not None and lc not in valid_lifecycle_ids:
                add("no_dangling", wid, "lifecycle_item_id %r does not resolve against the §13.1 registry (1..39)" % (lc,))

            op = frec.get("operation_impact")
            if op not in levels:
                add("no_dangling", wid, "operation_impact %r not in %s" % (op, sorted(levels)))

            # 正向 no-dangling: forward landing
            if not _nonempty_str(frec.get("current_landing_surface")):
                add("every_field_has_landing", wid, "current_landing_surface empty (computed without landing)")
                add("no_dangling", wid, "current_landing_surface empty")
            term = frec.get("terminal_surface_target")
            if not _nonempty_str(term):
                add("no_dangling", wid, "terminal_surface_target empty")
            elif op in non_tag_levels:
                # a non-tag impact (硬否决/降仓/调信心) must land on a real action_table column
                if term not in at_columns:
                    add("no_dangling", wid,
                        "non-tag operation_impact %r must land on an action_table column, got %r" % (op, term))
            elif op == TAG_LEVEL:
                # a soft tag may land on a column OR an advisory/shadow explanatory label
                if term not in at_columns and term not in ADVISORY_LANDINGS:
                    add("no_dangling", wid, "tag terminal %r is neither a column nor an advisory landing" % term)

            # 核心字段命中: a core field must hit an impact target when landed, else be shadow_record/dropped
            fclass = frec.get("field_class")
            disp = frec.get("disposition")
            impact_target = frec.get("impact_target")
            if fclass in core_classes:
                if disp == "landed":
                    if impact_target not in targets:
                        add("no_dangling", wid,
                            "core field_class %r landed but impact_target %r not in %s"
                            % (fclass, impact_target, sorted(targets)))
                elif disp not in ("shadow_record", "dropped"):
                    add("no_dangling", wid,
                        "core field_class %r disposition %r must be landed|shadow_record|dropped"
                        % (fclass, disp))

            # risk downgrade is soft-only (§5.2 / risk_downgrade engine hard_veto always False)
            if fclass == "risk downgrade":
                if op == "硬否决":
                    add("risk_downgrade_affects_size_confidence_or_tag", wid,
                        "risk downgrade must be soft, not 硬否决")
                if disp == "landed" and impact_target not in RISK_DOWNGRADE_TARGETS:
                    add("risk_downgrade_affects_size_confidence_or_tag", wid,
                        "risk downgrade landed impact_target %r not in %s"
                        % (impact_target, sorted(RISK_DOWNGRADE_TARGETS)))

            # ANY 硬否决 operation_impact (not only the hard-veto field_class) must reach final_action — a
            # 硬否决 from data-quality / any class is still a hard veto that forces a kill/exit final_action.
            if op == "硬否决":
                row_has_hard_veto = True

            # 反向证据反查: a claim must trace to a provider row / SEC filing / source_id at PIT as_of
            claim = frec.get("claim_type")
            if claim is not None:
                if claim not in claim_types:
                    add("every_claim_traceable", wid, "claim_type %r not in %s" % (claim, sorted(claim_types)))
                    add("no_unevidenced_claim", wid, "unknown claim_type %r" % claim)
                # registry 完整: a claim MUST carry a registry-declared evidence_ref_kind ∈ the frozen kinds
                # (a null declaration is valid ONLY for non-claim field records) — else traceback is not auditable.
                decl_kind = frec.get("evidence_ref_kind")
                if decl_kind is None or decl_kind not in ref_kinds:
                    add("every_claim_traceable", wid,
                        "claim must declare evidence_ref_kind ∈ %s, got %r" % (sorted(ref_kinds), decl_kind))
                    add("no_unevidenced_claim", wid, "claim has no valid registry-declared evidence_ref_kind")
                ev = frec.get("evidence_ref")
                if not isinstance(ev, dict):
                    add("every_claim_traceable", wid, "claim has no evidence_ref dict")
                    add("no_unevidenced_claim", wid, "claim not traceable (no evidence_ref)")
                else:
                    kind = ev.get("kind")
                    value = ev.get("value")
                    as_of = ev.get("as_of")
                    if kind not in ref_kinds:
                        add("every_claim_traceable", wid, "evidence_ref.kind %r not in %s" % (kind, sorted(ref_kinds)))
                        add("no_unevidenced_claim", wid, "evidence_ref.kind %r invalid" % kind)
                    if not _nonempty_str(value):
                        add("every_claim_traceable", wid, "evidence_ref.value empty")
                        add("no_unevidenced_claim", wid, "evidence_ref.value empty (untraceable)")
                    if not _strict_yyyymmdd(as_of):
                        add("every_claim_traceable", wid, "evidence_ref.as_of %r not strict YYYYMMDD" % as_of)
                    elif _strict_yyyymmdd(rec_as_of) and as_of != rec_as_of:
                        add("every_claim_traceable", wid,
                            "evidence_ref.as_of %r != record as_of %r (PIT)" % (as_of, rec_as_of))
                    # declared (registry) kind must equal the actual evidence kind when both are present+valid
                    if decl_kind is not None and kind is not None and decl_kind != kind:
                        add("every_claim_traceable", wid,
                            "declared evidence_ref_kind %r != evidence_ref.kind %r" % (decl_kind, kind))

        # 报告生成前必检: a hard veto must reach final_action (kill / avoid / forced exit)
        if row_has_hard_veto and final_action not in KILL_OR_EXIT_ACTIONS:
            add("hard_veto_covers_final_action", rid,
                "a 硬否决 operation_impact is present but final_action %r is not a kill/exit action %s"
                % (final_action, sorted(KILL_OR_EXIT_ACTIONS)))

    return _result(violations)


def validate_official_machine_record(record, *, field_registry=None, action_table=None) -> dict:
    """The OFFICIAL machine-record §10 gate = the generic `validate_machine_record` PLUS the reverse-completeness
    MANIFEST mandate (R-USSHORT-BATCH4-MACHINE-REGISTRY-COMPLETENESS-GAP). EVERY official producer/consumer
    (assemble_machine_record / flatten_machine_record / the private write via flatten) uses THIS, never the bare
    generic validator, so an official row CANNOT be reduced to an empty / partial registry by stripping its raw
    evidence — the manifest FLOOR (hard_veto / price / market_risk_regime) is unconditional. Per row: a manifest
    field_record that is MISSING (vs `official_expected_field_ids`) or EXTRA/fabricated ⟹ not clean; duplicate
    manifest ids are already caught by the generic validator. The generic validator stays field_id-agnostic by
    design; the manifest mandate lives ONLY here. Same result shape; malformed input fails closed, never raises."""
    result = validate_machine_record(record, field_registry=field_registry, action_table=action_table)
    violations = list(result["violations"])
    rows = record.get("rows") if isinstance(record, dict) else None
    if isinstance(rows, list):
        for ri, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            rid = row.get("ticker") if _nonempty_str(row.get("ticker")) else ("rows[%d]" % ri)
            frs = row.get("field_records")
            present = ({frec.get("field_id") for frec in frs
                        if isinstance(frec, dict) and frec.get("field_id") in MANIFEST_FIELD_IDS}
                       if isinstance(frs, list) else set())
            expected = official_expected_field_ids(row)
            for missing in sorted(expected - present):
                violations.append({"check": "no_dangling", "where": rid,
                                   "reason": "official row missing required §10 field_record %r (reverse-completeness)" % missing})
            for extra in sorted(present - expected):
                violations.append({"check": "no_dangling", "where": rid,
                                   "reason": "official row carries §10 field_record %r the row did not compute (unexpected/fabricated)" % extra})
    return _result(violations)
