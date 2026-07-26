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

import hashlib
import json
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
