"""Pre-freeze evidence mode shared by every A-short comparison track.

Why this exists (2026-07-25, user-directed)
-------------------------------------------
The eight A-short comparison tracks (P0/v2, P1, P2, P3, P4a, P5,
theme_forward_comparison, and the margin-overheat cash-control track) each bind an
"epoch fingerprint" that hashes whole implementation files -- among them
``runners/a_short_weekly_pipeline.py``, ``runners/a_short_phase5_engine.py``,
``A-EGS/egs_main.py``, weekly schemas and runtime presets.  The intent was
sound: evidence produced under one comparison contract must not be silently
mixed with evidence produced under a different one.

While the system design is still moving, that binding produced **churn without
protection**.  An edit with no relation to any comparison contract silently
dropped every accumulated week (``_current_records()`` returning 0, or the
active epoch simply not matching) with no warning at all.  It fired twice in a
single week and was found by review, not by the system.  Meanwhile the tracks
hold 0-1 weeks of evidence each against 12/24/36-week checkpoints, so the
mechanism was protecting almost nothing while invalidating everything.

What this module does
---------------------
While a track is ``pre_freeze_audit_only`` in the per-track registry, its epoch
fingerprint is a **stable constant** instead of a hash over moving files:

* captures still record a fingerprint, so provenance is still written down;
* nothing is ever silently dropped, so progress counters stop lying;
* unrelated edits cost nothing, so the design can keep moving.

A pre-freeze constant can never equal a real post-freeze fingerprint, so
freezing one registry entry naturally leaves every pre-freeze week outside the
new epoch.  That is the intended semantics: the 12/24/36-week clocks start
**at the freeze**, not before.

Pre-freeze evidence is audit-only.  ``evidence_counts_toward_clock(track)`` is
False, and every track must refuse to emit a promote / retire / ready verdict
while it is False -- concluding from evidence that does not count would be the
same class of dishonesty this module exists to remove.

Restoring enforcement
---------------------
Freeze only the intended entry in ``TRACK_MODE_REGISTRY_PATH`` once that
track's design is settled.  There is deliberately no all-track switch.

The shared prerequisite is done (2026-08-05).  The fifth-knife freeze packet
used to gate on whole-file bytes, which would have returned the original churn
at exactly the moment it started costing real evidence: eight knives are still
to land before the design settles, and row 11 alone rewrites the effect
contract's entire leaf ledger while changing no comparison verdict.  Each of
the eight contracts now declares a **projection** in ``_CONTRACT_PROJECTIONS``
and is sealed on the substance that can actually move a verdict:

* governance presets -- canonical JSON, annotations dropped, so reformatting
  and rewording are free while every real value still decides;
* JSON Schemas -- validation keywords only, so a reworded ``description``
  cannot discard a week;
* the P4a Python contract -- executable AST with docstrings stripped, read
  from the checked-in file rather than imported, so neither an import cycle
  nor a patched ``inspect`` can decide what the packet validates against;
* the effect contract -- the decision surface only.  Its leaf ledger
  (``_EFFECT_CONTRACT_LEAF_LEDGER_KEYS``) is excluded; every other key is
  bound, **including keys added later**, because over-binding costs one re-arm
  while under-binding silently turns stale evidence into apparent evidence.

Drift is still fatal to an epoch and is now always named: the error says which
contract moved and under which projection.  Losing evidence is sometimes
correct; losing it without being told which change did it is what this
replaces.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
from functools import lru_cache
from pathlib import Path

import jsonschema

_PRE_FREEZE = "pre_freeze_audit_only"
_FROZEN = "frozen_enforced"
_VALID_MODES = (_PRE_FREEZE, _FROZEN)

#: Every track that owns an epoch fingerprint.  A new comparison track MUST be
#: registered here and route its fingerprint through this module, so the next
#: unfinished-design component cannot recreate the same silent-invalidation bug.
TRACKS = (
    "p0_factor_comparison_v2",
    "p1_regime_candidate_effect",
    "p2_target_policy",
    "p3_final_action_validation",
    "p4a_overlay_adjudication",
    "p5_industry_weight",
    "theme_forward_comparison",
    "a_short_margin_overheat_cash_control",
)

ROOT = Path(__file__).resolve().parents[1]
TRACK_MODE_REGISTRY_PATH = ROOT / "docs" / "a_short_evidence_epoch_mode_registry_20260725.json"
FIFTH_KNIFE_FREEZE_PACKET_PATH = (
    ROOT / "docs" / "a_short_fifth_knife_forward_evidence_freeze_20260724.json"
)
FIFTH_KNIFE_FREEZE_SCHEMA_PATH = (
    ROOT / "schemas" / "a_short_fifth_knife_forward_evidence_freeze.schema.json"
)
_FIFTH_KNIFE_FROZEN_CONTRACTS = {
    "a_short_screening_runtime_policy": "presets/a_short_screening_threshold_governance_20260602.json",
    "a_short_m67_runtime_policy": "presets/a_short_m67_runtime_policy_20260715.json",
    "v14_3_action_comparison_governance": "presets/a_short_regime_action_comparison_governance_20260714.json",
    "v14_3_action_comparison_schema": "schemas/a_short_regime_action_comparison_governance.schema.json",
    "v14_3_weekly_capture_schema": "schemas/a_short_regime_action_comparison_weekly.schema.json",
    "p4a_overlay_epoch": "engine/a_short_overlay_adjudication.py",
    "m67_effect_contract": "schemas/a_short_m67_effect_contract.json",
    "weekly_report_schema": "schemas/a_short_weekly_report.schema.json",
}


#: How each frozen contract is reduced to the substance that can actually change
#: a comparison verdict.  Whole-file bytes were the original gate, and they made
#: a comment, a reordered key or a new leaf-ledger entry cost every accumulated
#: week -- churn with no protection, which is the exact failure this module was
#: written to remove.  A projection binds what decides and ignores what does not.
_PROJECTION_JSON_GOVERNANCE = "json_governance"
_PROJECTION_JSON_SCHEMA = "json_schema_validation"
_PROJECTION_PYTHON_MODULE = "python_semantic_module"
_PROJECTION_EFFECT_CONTRACT = "json_effect_contract_decisions"

_CONTRACT_PROJECTIONS = {
    # Small governed presets: every key is a decision, but formatting and key
    # order are not.  Canonical JSON, annotations dropped.
    "a_short_screening_runtime_policy": _PROJECTION_JSON_GOVERNANCE,
    "a_short_m67_runtime_policy": _PROJECTION_JSON_GOVERNANCE,
    "v14_3_action_comparison_governance": _PROJECTION_JSON_GOVERNANCE,
    # JSON Schemas decide only through their validation keywords.  A reworded
    # description cannot change whether a payload is accepted.
    "v14_3_action_comparison_schema": _PROJECTION_JSON_SCHEMA,
    "v14_3_weekly_capture_schema": _PROJECTION_JSON_SCHEMA,
    "weekly_report_schema": _PROJECTION_JSON_SCHEMA,
    # Python: executable AST, docstrings stripped, bound the same way the P4a
    # track itself binds this module so the two cannot disagree.
    "p4a_overlay_epoch": _PROJECTION_PYTHON_MODULE,
    # The effect contract is two documents in one file: a leaf ledger and a set
    # of hashes over the production decision surface.  Only the latter can move
    # a comparison verdict.
    "m67_effect_contract": _PROJECTION_EFFECT_CONTRACT,
}

#: Annotation-only JSON Schema keywords.  Dropping these cannot change which
#: payloads validate; keeping them made every wording fix an epoch break.
_ANNOTATION_ONLY_SCHEMA_KEYWORDS = frozenset({
    "title", "description", "$comment", "examples", "deprecated", "readOnly", "writeOnly",
})

#: Effect-contract keys that are leaf bookkeeping, not decision surface.  Row 11
#: rewrites every one of them while changing no comparison judgment.  Everything
#: else in the document is bound, including keys added later: an unclassified key
#: is bound by default, because over-binding costs one re-arm while under-binding
#: silently turns stale evidence into apparently valid evidence.
_EFFECT_CONTRACT_LEAF_LEDGER_KEYS = frozenset({
    "groups",
    "leaf_effect_overrides",
    "leaf_nature_by_group",
    "analysis_input_paths",
    "analysis_input_all_paths_sha256",
    "legacy_migration_sha256",
    # The frozen list of leaves still awaiting an effect adjudication.  It is
    # bookkeeping of the same kind: wiring or deleting a leaf shrinks it, and
    # that shrink decides no comparison.  Left bound, every such shrink would
    # invalidate accumulated evidence for a change it did not cause.
    "unclassified_pending_audit_baseline",
})


class EvidenceEpochModeError(ValueError):
    """Raised when the evidence mode or a track identifier is not recognised."""


def _canonical_json_sha256(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _strip_schema_annotations(value):
    """Drop annotation-only keywords everywhere, keeping every validation keyword.

    Recurses through objects and arrays.  A key whose own name is an annotation
    keyword is dropped; its value is never inspected, so a property legitimately
    *named* ``description`` inside ``properties`` survives -- that is a schema
    subtree, reached through ``properties``, not an annotation.
    """
    if isinstance(value, dict):
        return {
            key: _strip_schema_annotations(item)
            for key, item in value.items()
            if key not in _ANNOTATION_ONLY_SCHEMA_KEYWORDS
        }
    if isinstance(value, list):
        return [_strip_schema_annotations(item) for item in value]
    return value


def _load_contract_json(name: str, path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise EvidenceEpochModeError(f"cannot read frozen contract: {name}") from exc


def _frozen_contract_path(name: str) -> tuple[str, Path]:
    """Resolve one registered frozen contract to its projection and file."""
    try:
        relative = _FIFTH_KNIFE_FROZEN_CONTRACTS[name]
        projection = _CONTRACT_PROJECTIONS[name]
    except KeyError as exc:
        raise EvidenceEpochModeError(f"unregistered frozen contract: {name}") from exc
    path = (ROOT / relative).resolve()
    if ROOT.resolve() not in path.parents or not path.is_file():
        raise EvidenceEpochModeError(f"missing fifth-knife frozen contract: {name}")
    return projection, path


def contract_semantic_projection(name: str) -> dict:
    """Return the decision-bearing substance of one frozen contract.

    Everything outside the projection is free to move while the design is still
    being built, which is the whole point: an edit that cannot change a verdict
    must not be able to discard evidence.
    """
    projection, path = _frozen_contract_path(name)

    if projection == _PROJECTION_PYTHON_MODULE:
        # Read the file, never import it.  Importing would create a cycle (the
        # overlay module imports this one) and would route through
        # ``inspect.getsourcefile``, making packet validation answer to whatever
        # a caller has patched.  The checked-in bytes are the authority.
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise EvidenceEpochModeError(f"cannot read frozen contract: {name}") from exc
        tree = _cached_semantic_source_tree(str(path), source)
        return {"projection": projection, "substance": {
            # No exclusions here.  A track excludes the functions that compute
            # its own fingerprint to avoid self-reference; this projection is
            # computed from outside, so binding everything is both simpler and
            # more conservative.
            "bound_functions": sorted(_top_level_function_nodes(tree)),
            "semantic_ast_sha256": _semantic_ast_sha256(list(tree.body)),
        }}

    document = _load_contract_json(name, path)
    if projection == _PROJECTION_JSON_GOVERNANCE:
        substance = _strip_schema_annotations(document)
    elif projection == _PROJECTION_JSON_SCHEMA:
        substance = _strip_schema_annotations(document)
    elif projection == _PROJECTION_EFFECT_CONTRACT:
        if not isinstance(document, dict):
            raise EvidenceEpochModeError(f"malformed frozen contract: {name}")
        substance = {
            key: value for key, value in document.items()
            if key not in _EFFECT_CONTRACT_LEAF_LEDGER_KEYS
        }
    else:  # pragma: no cover - _CONTRACT_PROJECTIONS is closed and tested
        raise EvidenceEpochModeError(f"unknown projection for frozen contract: {name}")
    return {"projection": projection, "substance": substance}


@lru_cache(maxsize=64)
def _contract_semantic_fingerprint_from_source(name: str, source: str) -> str:
    return _canonical_json_sha256(contract_semantic_projection(name))


def contract_semantic_fingerprint(name: str) -> str:
    """The 64-hex fingerprint of one contract's decision-bearing substance.

    Memoized on the contract's exact bytes.  Every freeze-packet validation asks
    for all eight fingerprints, and the Python projection deep-copies and
    ``ast.dump``s a whole module to answer -- by profile the single most
    expensive operation in the A-short lane.  The file content is the cache key,
    so an edited contract always produces a new fingerprint rather than a stale
    one; that is the same authority the uncached form had.
    """
    _projection, path = _frozen_contract_path(name)
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvidenceEpochModeError(f"cannot read frozen contract: {name}") from exc
    return _contract_semantic_fingerprint_from_source(name, source)


def _freeze_schema_cache_key(path: Path) -> tuple[str, int, int]:
    """Return the path-and-metadata key for one compiled freeze schema."""
    try:
        stat = path.stat()
        return str(path.resolve()), stat.st_mtime_ns, stat.st_size
    except OSError as exc:
        raise EvidenceEpochModeError("cannot read fifth-knife freeze packet schema") from exc


@lru_cache(maxsize=8)
def _compiled_freeze_packet_validator(
    schema_path: str, mtime_ns: int, size: int,
):
    """Compile a schema once per path/content-metadata version.

    Packet bytes are deliberately never cached: every mode query must still
    observe a changed, malformed, or dishonest packet immediately.  The small
    cache only avoids repeatedly compiling the fixed local JSON Schema.
    """
    del mtime_ns, size  # cache-key inputs; the file is read only on a cache miss.
    try:
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        validator_type = jsonschema.validators.validator_for(schema)
        validator_type.check_schema(schema)
        return validator_type(schema)
    except (OSError, UnicodeDecodeError, ValueError, jsonschema.SchemaError) as exc:
        raise EvidenceEpochModeError("invalid fifth-knife freeze packet schema") from exc


def _freeze_packet_validator():
    """Return the current-schema validator without retaining packet contents."""
    return _compiled_freeze_packet_validator(
        *_freeze_schema_cache_key(FIFTH_KNIFE_FREEZE_SCHEMA_PATH)
    )


def _validate_fifth_knife_freeze_packet(*, require_contract_hashes: bool) -> dict:
    """Validate the shared freeze packet before any comparison mode is used.

    The packet is deliberately allowed to carry stale contract hashes while
    every track is parked in pre-freeze audit-only mode.  Its identity,
    inventory, self-hash and no-evidence/no-promotion claims are still runtime
    requirements.  The first individually frozen track re-arms all eight
    contract hashes before that track can compute or count evidence.

    Structural validation is memoized on the packet's exact text plus the
    schema's identity: comparison tracks call this once per record, and the
    uncached schema-validate + self-hash cost was a top lane sink by profile.
    An edited packet is a different key and revalidates in full.  The eight
    fingerprint comparisons stay outside the memo -- each fingerprint is
    already keyed on its own contract's bytes, so an edited contract still
    fails here even when the packet text is unchanged.
    """
    try:
        packet_source = FIFTH_KNIFE_FREEZE_PACKET_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvidenceEpochModeError("cannot read fifth-knife freeze packet") from exc
    packet = copy.deepcopy(_structurally_validated_packet(
        packet_source, _freeze_schema_cache_key(FIFTH_KNIFE_FREEZE_SCHEMA_PATH)
    ))
    if require_contract_hashes:
        by_name = {contract["name"]: contract for contract in packet["frozen_contracts"]}
        for name in _FIFTH_KNIFE_FROZEN_CONTRACTS:
            recorded = by_name[name]["semantic_fingerprint"]
            if contract_semantic_fingerprint(name) != recorded:
                # Named, never silent.  Losing evidence is sometimes correct; losing
                # it without being told which contract moved is what this replaces.
                raise EvidenceEpochModeError(
                    f"fifth-knife frozen contract semantic drift: {name} "
                    f"(projection={_CONTRACT_PROJECTIONS[name]}); the decision-bearing "
                    "substance changed, so evidence accumulated under the old epoch "
                    "no longer applies"
                )
    return packet


@lru_cache(maxsize=8)
def _structurally_validated_packet(packet_source: str, schema_key: tuple) -> dict:
    """Validate everything about the packet that is a pure function of its text."""
    del schema_key  # binds the cache key; the validator below is cached on the same key
    try:
        packet = json.loads(packet_source)
    except ValueError as exc:
        raise EvidenceEpochModeError("cannot read fifth-knife freeze packet") from exc
    if not isinstance(packet, dict) or \
            packet.get("schema_name") != "a_short_fifth_knife_forward_evidence_freeze" or \
            packet.get("schema_version") != "1.0.0":
        raise EvidenceEpochModeError("invalid fifth-knife freeze packet identity")
    try:
        _freeze_packet_validator().validate(packet)
    except (jsonschema.ValidationError, jsonschema.SchemaError) as exc:
        raise EvidenceEpochModeError("invalid fifth-knife freeze packet schema") from exc

    recorded = packet.get("record_sha256")
    unsigned = {key: value for key, value in packet.items() if key != "record_sha256"}
    if not isinstance(recorded, str) or recorded != _canonical_json_sha256(unsigned):
        raise EvidenceEpochModeError("invalid fifth-knife freeze packet self-hash")

    ship_gate = packet.get("ship_gate")
    boundary = packet.get("boundary")
    capture = packet.get("capture_contract")
    if packet.get("status") != "frozen_not_started" or \
            not isinstance(ship_gate, dict) or \
            ship_gate.get("observed_forward_live_months") != 0 or \
            not isinstance(boundary, dict) or \
            boundary.get("effectiveness_claimed") is not False or \
            boundary.get("production_promotion_allowed") is not False or \
            boundary.get("automatic_orders_allowed") is not False or \
            not isinstance(capture, dict) or \
            capture.get("historical_replay_counts_as_forward") is not False:
        raise EvidenceEpochModeError("dishonest fifth-knife pre-freeze boundary")

    contracts = packet.get("frozen_contracts")
    if not isinstance(contracts, list):
        raise EvidenceEpochModeError("invalid fifth-knife frozen-contract inventory")
    by_name = {}
    for contract in contracts:
        if not isinstance(contract, dict):
            raise EvidenceEpochModeError("invalid fifth-knife frozen-contract entry")
        name = contract.get("name")
        if name in by_name:
            raise EvidenceEpochModeError("duplicate fifth-knife frozen-contract name")
        by_name[name] = contract
    if set(by_name) != set(_FIFTH_KNIFE_FROZEN_CONTRACTS):
        raise EvidenceEpochModeError("incomplete fifth-knife frozen-contract inventory")

    for name, relative in _FIFTH_KNIFE_FROZEN_CONTRACTS.items():
        contract = by_name[name]
        if contract.get("path") != relative:
            raise EvidenceEpochModeError(
                f"fifth-knife frozen-contract path mismatch: {name}"
            )
        recorded = contract.get("semantic_fingerprint")
        if not isinstance(recorded, str) or len(recorded) != 64 or \
                any(char not in "0123456789abcdef" for char in recorded):
            raise EvidenceEpochModeError(
                f"invalid fifth-knife frozen-contract semantic fingerprint: {name}"
            )
        if contract.get("projection") != _CONTRACT_PROJECTIONS[name]:
            raise EvidenceEpochModeError(
                f"fifth-knife frozen-contract projection mismatch: {name}"
            )
    return packet


def _freeze_packet_identity(packet: dict) -> dict[str, str]:
    """Return the immutable identity that every frozen epoch must persist."""
    identity = {
        "freeze_id": packet.get("freeze_id"),
        "schema_version": packet.get("schema_version"),
        "record_sha256": packet.get("record_sha256"),
    }
    if not isinstance(identity["freeze_id"], str) or not identity["freeze_id"] or \
            identity["schema_version"] != "1.0.0" or \
            not isinstance(identity["record_sha256"], str) or \
            len(identity["record_sha256"]) != 64:
        raise EvidenceEpochModeError("invalid fifth-knife freeze packet identity binding")
    return identity


def validated_frozen_packet_identity(track: str) -> dict[str, str] | None:
    """Return the current validated identity, or ``None`` while pre-freeze."""
    mode = _mode(track)
    packet = _validate_fifth_knife_freeze_packet(
        require_contract_hashes=(mode == _FROZEN),
    )
    return _freeze_packet_identity(packet) if mode == _FROZEN else None


@lru_cache(maxsize=4)
def _track_modes_from_source(source: str) -> tuple[tuple[str, str], ...]:
    """Parse and validate the mode registry once per exact registry text."""
    try:
        registry = json.loads(source)
    except ValueError as exc:
        raise EvidenceEpochModeError(f"cannot read evidence epoch mode registry: {exc}") from exc
    if registry.get("schema_name") != "a_short_evidence_epoch_mode_registry" or \
            registry.get("schema_version") != "1.0.0":
        raise EvidenceEpochModeError("invalid evidence epoch mode registry identity")
    modes = registry.get("track_modes")
    if not isinstance(modes, dict) or set(modes) != set(TRACKS):
        raise EvidenceEpochModeError("evidence epoch mode registry must name every registered track exactly once")
    for track, mode in modes.items():
        if mode not in _VALID_MODES:
            raise EvidenceEpochModeError(f"unknown evidence epoch mode for track: {track}")
    return tuple(sorted(modes.items()))


def _mode(track: str) -> str:
    """Return one registered track's mode; the registry is the sole authority.

    The registry file is read on every call -- the text is the cache key, so a
    flipped registry takes effect immediately; only re-parsing identical text
    is skipped.
    """
    track = _require_track(track)
    try:
        source = TRACK_MODE_REGISTRY_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvidenceEpochModeError(f"cannot read evidence epoch mode registry: {exc}") from exc
    return dict(_track_modes_from_source(source))[track]


def enforcement_enabled(track: str) -> bool:
    """Whether a real, freeze-packet-bound fingerprint governs membership."""
    return validated_frozen_packet_identity(track) is not None


def validate_frozen_transition(track: str) -> dict[str, str]:
    """Authorize a durable pre-freeze -> frozen transition.

    This gate deliberately ignores the registry's current polarity.  A writer
    must pass the full eight-contract freeze check *before* it publishes any
    admission receipt, archive, active epoch, or frozen registry state.
    """
    _require_track(track)
    packet = _validate_fifth_knife_freeze_packet(require_contract_hashes=True)
    return _freeze_packet_identity(packet)


def validate_bound_frozen_packet_identity(
    track: str, expected: dict[str, str],
) -> dict[str, str]:
    """Fail closed if a frozen epoch is not bound to the current packet."""
    current = validated_frozen_packet_identity(track)
    if current is None or current != expected:
        raise EvidenceEpochModeError("fifth-knife frozen packet epoch binding mismatch")
    return current


def bind_frozen_fingerprint(
    track: str, fingerprint: str, packet_identity: dict[str, str],
) -> str:
    """Bind one real track fingerprint to the shared freeze-packet identity."""
    _require_track(track)
    if not isinstance(fingerprint, str) or len(fingerprint) != 64 or \
            any(char not in "0123456789abcdef" for char in fingerprint):
        raise EvidenceEpochModeError("invalid real comparison fingerprint")
    validate_bound_frozen_packet_identity(track, packet_identity)
    return _canonical_json_sha256({
        "track": track,
        "component_fingerprint": fingerprint,
        "fifth_knife_freeze_packet_identity": packet_identity,
    })


def evidence_counts_toward_clock(track: str) -> bool:
    """Whether accumulated weeks may advance a 12/24/36-week checkpoint."""
    return enforcement_enabled(track)


def _require_track(track: str) -> str:
    track = str(track)
    if track not in TRACKS:
        raise EvidenceEpochModeError(f"unregistered comparison track: {track}")
    return track


def pre_freeze_fingerprint(track: str) -> str:
    """Stable 64-hex stand-in fingerprint for one track during pre-freeze.

    Distinct per track so two tracks can never share an epoch, and shaped like a
    sha256 digest so it still satisfies every track's ``^[0-9a-f]{64}$`` schema.
    """
    payload = {"evidence_mode": _PRE_FREEZE, "track": _require_track(track)}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def fingerprint_or_pre_freeze(track: str, compute) -> str:
    """Return the track's real fingerprint only while enforcement is enabled."""
    _require_track(track)
    packet_identity = validated_frozen_packet_identity(track)
    if packet_identity is None:
        return pre_freeze_fingerprint(track)
    return bind_frozen_fingerprint(track, compute(), packet_identity)


class _StripDocstrings(ast.NodeTransformer):
    """Drop docstrings so prose edits cannot open a new epoch."""

    def _strip(self, node):
        self.generic_visit(node)
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and \
                isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body.pop(0)
        return node

    visit_Module = _strip
    visit_FunctionDef = _strip
    visit_AsyncFunctionDef = _strip
    visit_ClassDef = _strip


def _module_source_text(module) -> tuple[str, str]:
    """Read the checked-in source of one module for semantic-contract caching.

    The file, not the live module dictionary, is the authority: a runtime
    monkeypatch must not be able to forge or move a contract.
    """
    source_path = inspect.getsourcefile(module)
    if not source_path:
        raise EvidenceEpochModeError(f"cannot locate semantic source for {module.__name__}")
    try:
        source = Path(source_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvidenceEpochModeError(f"cannot read semantic source for {module.__name__}") from exc
    return module.__name__, source


def _top_level_function_nodes(tree: ast.AST) -> dict[str, ast.AST]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _top_level_constant_nodes(tree: ast.AST) -> dict[str, ast.AST]:
    """Return the last top-level all-caps assignment for each constant name."""
    constant_nodes = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                constant_nodes[target.id] = node
    return constant_nodes


@lru_cache(maxsize=64)
def _cached_semantic_source_tree(module_name: str, source: str) -> ast.AST:
    """Parse one exact source text once; only private helpers may read the tree."""
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        raise EvidenceEpochModeError(f"cannot read semantic source for {module_name}") from exc


def _semantic_source_inventory(
        module_name: str, source: str,
) -> tuple[tuple[ast.AST, ...], dict[str, ast.AST], dict[str, ast.AST]]:
    """Return read-only semantic indexes over one source-keyed parse tree.

    The indexes never leave this module.  ``_semantic_ast_sha256`` owns the
    only mutation-prone operation and copies only its selected nodes before
    stripping docstrings; cloning the whole source tree here made every narrow
    function contract pay for unrelated module bodies.
    """
    tree = _cached_semantic_source_tree(module_name, source)
    return tuple(tree.body), _top_level_function_nodes(tree), _top_level_constant_nodes(tree)


def _semantic_ast_sha256(nodes) -> str:
    # The transformer mutates its input.  This is deliberately the sole copy:
    # callers select only contract-relevant nodes from the private cached tree.
    normalized_nodes = copy.deepcopy(list(nodes))
    normalized = ast.dump(
        _StripDocstrings().visit(ast.Module(body=normalized_nodes, type_ignores=[])),
        include_attributes=False,
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@lru_cache(maxsize=128)
def _semantic_module_contract_from_source(
        module_name: str, source: str, exclusions: tuple[str, ...]) -> tuple[str, tuple[str, ...], tuple[str, ...], str]:
    top_level_nodes, function_nodes, _constant_nodes = _semantic_source_inventory(module_name, source)
    unknown = set(exclusions) - set(function_nodes)
    if unknown:
        raise EvidenceEpochModeError(
            f"unknown semantic-function exclusions for {module_name}: {sorted(unknown)}"
        )
    selected = [
        node for node in top_level_nodes
        if not (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in exclusions
        )
    ]
    return (
        module_name,
        tuple(sorted(set(function_nodes) - set(exclusions))),
        exclusions,
        _semantic_ast_sha256(selected),
    )


def semantic_module_contract(module, *, excluded_functions=frozenset()) -> dict:
    """Return a comment/docstring-insensitive contract for one Python module.

    The contract binds the module's complete executable AST and names every
    top-level function explicitly.  Exclusions are fail-closed: a stale or
    misspelled exclusion is an error instead of silently weakening coverage.
    """
    module_name, source = _module_source_text(module)
    exclusions = frozenset(str(name) for name in excluded_functions)
    cached = _semantic_module_contract_from_source(module_name, source, tuple(sorted(exclusions)))
    return {
        "module": cached[0],
        "bound_functions": list(cached[1]),
        "excluded_functions": list(cached[2]),
        "semantic_ast_sha256": cached[3],
    }


@lru_cache(maxsize=256)
def _semantic_function_contract_from_source(
        module_name: str, source: str, requested: tuple[str, ...]) -> tuple[str, tuple[str, ...], tuple[str, ...], str]:
    _top_level_nodes, function_nodes, constant_nodes = _semantic_source_inventory(module_name, source)
    missing = [name for name in requested if name not in function_nodes]
    if missing:
        raise EvidenceEpochModeError(
            f"missing semantic functions in {module_name}: {missing}"
        )
    referenced = tuple(sorted({
        item.id
        for name in requested
        for item in ast.walk(function_nodes[name])
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load) and item.id in constant_nodes
    }))
    selected = [function_nodes[name] for name in requested]
    selected += [constant_nodes[name] for name in referenced]
    return module_name, requested, referenced, _semantic_ast_sha256(selected)


def semantic_function_contract(module, function_names) -> dict:
    """The same contract for a deliberately narrow subset of one module.

    Some tracks bind only a few result-shaping functions rather than a whole
    module.  Narrowing the scope must not cost the comment/docstring
    insensitivity, so this shares the module reader and AST normalisation
    instead of falling back to raw ``inspect.getsource``.  A missing name is an
    error, so a rename cannot silently shrink the bound surface.
    """
    requested = sorted({str(name) for name in function_names})
    if not requested:
        raise EvidenceEpochModeError(f"no semantic functions requested for {module.__name__}")
    module_name, source = _module_source_text(module)
    # A narrow binding still has to cover the constants those functions read.
    # Binding only the function bodies let a governed threshold (P5's fixed
    # watch-pool slot count, for one) change behaviour without moving the
    # epoch, which is the same polarity gap the whole-file helper already
    # closes by collecting referenced constants.  The walk stays inside the
    # requested functions: narrowing the surface is deliberate, so callees are
    # still out of scope.
    cached = _semantic_function_contract_from_source(module_name, source, tuple(requested))
    return {
        "module": cached[0],
        "bound_functions": list(cached[1]),
        "bound_constants": list(cached[2]),
        "semantic_ast_sha256": cached[3],
    }
