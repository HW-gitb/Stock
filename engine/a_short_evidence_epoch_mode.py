"""Pre-freeze evidence mode shared by every A-short comparison track.

Why this exists (2026-07-25, user-directed)
-------------------------------------------
The seven A-short comparison tracks (P0/v2, P1, P2, P3, P4a, P5, and
theme_forward_comparison) each bind an
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
track's design is settled.  There is deliberately no all-track switch.  Before
freezing a track, converge its real fingerprint onto semantic contracts (governance
JSON / preset / schema / admission snapshot plus ``inspect.getsource`` of the
evidence-producing functions) rather than whole-file bytes, and make any
retained file-level hash LF-canonical -- otherwise the original churn returns
at exactly the moment it starts costing real evidence.

The fifth-knife freeze packet is also pre-freeze while this mode is active. At
the same switchover, rehash all eight frozen contracts LF-canonically,
recompute P4a's semantic fingerprint and the packet self-hash, then record an
explicit epoch judgment in ``docs/SESSION_LOG.md`` for each changed contract.
In particular, a hash-only effect-contract change may remain in the epoch;
the P4a pre-freeze adjudication gate is behavioural but is conservative and
has zero countable forward evidence, so it too requires an explicit judgment
rather than an implicit reseal.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
from functools import lru_cache
from pathlib import Path

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
)

ROOT = Path(__file__).resolve().parents[1]
TRACK_MODE_REGISTRY_PATH = ROOT / "docs" / "a_short_evidence_epoch_mode_registry_20260725.json"


class EvidenceEpochModeError(ValueError):
    """Raised when the evidence mode or a track identifier is not recognised."""


def _mode(track: str) -> str:
    """Return one registered track's mode; the registry is the sole authority."""
    track = _require_track(track)
    try:
        registry = json.loads(TRACK_MODE_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvidenceEpochModeError(f"cannot read evidence epoch mode registry: {exc}") from exc
    if registry.get("schema_name") != "a_short_evidence_epoch_mode_registry" or \
            registry.get("schema_version") != "1.0.0":
        raise EvidenceEpochModeError("invalid evidence epoch mode registry identity")
    modes = registry.get("track_modes")
    if not isinstance(modes, dict) or set(modes) != set(TRACKS):
        raise EvidenceEpochModeError("evidence epoch mode registry must name every registered track exactly once")
    mode = modes.get(track)
    if mode not in _VALID_MODES:
        raise EvidenceEpochModeError(f"unknown evidence epoch mode for track: {track}")
    return mode


def enforcement_enabled(track: str) -> bool:
    """Whether a real contract fingerprint governs epoch membership."""
    return _mode(track) == _FROZEN


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
    return compute() if enforcement_enabled(track) else pre_freeze_fingerprint(track)


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


def _module_function_nodes(module) -> tuple[str, str]:
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


def _semantic_ast_sha256(nodes) -> str:
    normalized = ast.dump(
        _StripDocstrings().visit(ast.Module(body=list(nodes), type_ignores=[])),
        include_attributes=False,
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@lru_cache(maxsize=64)
def _semantic_module_contract_from_source(
        module_name: str, source: str, exclusions: tuple[str, ...]) -> tuple[str, tuple[str, ...], tuple[str, ...], str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise EvidenceEpochModeError(f"cannot read semantic source for {module_name}") from exc
    function_nodes = _top_level_function_nodes(tree)
    unknown = set(exclusions) - set(function_nodes)
    if unknown:
        raise EvidenceEpochModeError(
            f"unknown semantic-function exclusions for {module_name}: {sorted(unknown)}"
        )
    selected = [
        node for node in tree.body
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
    module_name, source = _module_function_nodes(module)
    exclusions = frozenset(str(name) for name in excluded_functions)
    cached = _semantic_module_contract_from_source(module_name, source, tuple(sorted(exclusions)))
    return {
        "module": cached[0],
        "bound_functions": list(cached[1]),
        "excluded_functions": list(cached[2]),
        "semantic_ast_sha256": cached[3],
    }


@lru_cache(maxsize=64)
def _semantic_function_contract_from_source(
        module_name: str, source: str, requested: tuple[str, ...]) -> tuple[str, tuple[str, ...], tuple[str, ...], str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise EvidenceEpochModeError(f"cannot read semantic source for {module_name}") from exc
    function_nodes = _top_level_function_nodes(tree)
    missing = [name for name in requested if name not in function_nodes]
    if missing:
        raise EvidenceEpochModeError(
            f"missing semantic functions in {module_name}: {missing}"
        )
    constant_nodes = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                constant_nodes[target.id] = node
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
    module_name, source = _module_function_nodes(module)
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
