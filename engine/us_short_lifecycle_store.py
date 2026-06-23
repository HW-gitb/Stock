# -*- coding: utf-8 -*-
"""US-short §13 lifecycle register persistence — slice 2b: gitignored write + stale-aware load.

Design authority: docs/us_short_system_design.md §13 (落点分离) / §11.6 (输出路径护栏 + lifecycle 隐私) /
§2.1 (桶名 ≠ decision_date → fail-closed 弃) / §18.0 P0 (私密路径 guard) / §18.1 #20 (陈旧 artifact fail-closed).

The lifecycle_register is the running per-§13.1-item live-forward accumulator (engine/us_short_lifecycle_eval).
It carries per-item counts (and later ticker / performance detail), so it MUST live only on a gitignored private
path (state/us_short/lifecycle/, §11.6). This slice is the FIRST lifecycle PERSISTER:

  * write_lifecycle_register wires the §18.0 P0 fail-closed private-path guard (reject_nonprivate_output_path)
    BEFORE any validate / write, and refuses to persist a register the §13 validator does not mark clean — a
    producer never persists a not-clean accumulator;
  * load_lifecycle_register applies the SAME §18.0 private-path guard to the SOURCE path first (symmetric — a
    private artifact is read only from a provably-private location, never a tracked in-repo path), then
    re-validates the loaded artifact and fails closed on a stale / misaligned / bad bucket — an unreadable /
    corrupt-JSON artifact, a not-clean persisted register, or (when given the run's decision_date) a persisted
    as_of NEWER than that decision_date (§2.1 桶名 ≠ decision_date → 弃 / §18.1 #20 陈旧 artifact). Re-running
    the SAME decision_date (idempotent) and normal forward progress are both fine.

Structure-over-IO: reads/writes a private JSON only; no provider / live / DataHub / network; no A-share
crossing. The honest banner + readiness artifact are slice 2c (engine/us_short_lifecycle_render / us_short_lifecycle_readiness); the weekly reconcile pairs with the weekly_report renderer.
"""
from __future__ import annotations

import json
from pathlib import Path

from engine.us_short_lifecycle_eval import (
    LifecycleRegisterError,
    _strict_yyyymmdd,  # canonical lifecycle date gate (single source — no second date parser to drift)
    validate_lifecycle_register,
)
from engine.us_short_private_paths import reject_nonprivate_output_path

ROOT = Path(__file__).resolve().parent.parent
LIFECYCLE_DIR = ROOT / "state" / "us_short" / "lifecycle"
LIFECYCLE_REGISTER_PATH = LIFECYCLE_DIR / "lifecycle_register.json"  # canonical private location (§13 / §11.6)


class StaleLifecycleArtifactError(LifecycleRegisterError):
    """Raised when a persisted lifecycle_register cannot be trusted for the current run — unreadable / corrupt
    JSON, or a stale / misaligned bucket whose as_of is NEWER than the run's decision_date (§2.1 / §18.1 #20)."""


def write_lifecycle_register(register, out_path, *, calibration=None, authority=None):
    """Persist a §13-clean lifecycle_register to a gitignored private path. Returns the written ``Path``.

    FIRST lifecycle persister: the §18.0 P0 fail-closed private-path guard runs BEFORE any validate / write, so
    a relative / non-gitignored in-repo destination is refused (the register carries per-item counts / later
    tickers). Refuses to persist a register the §13 validator does not mark clean (``LifecycleRegisterError``,
    raised before any file side effect) — a producer never persists a not-clean accumulator. Pass
    ``LIFECYCLE_REGISTER_PATH`` for the canonical location, or an external absolute path.
    """
    reject_nonprivate_output_path(out_path)  # §18.0 P0 guard — before validate / write / any side effect
    result = validate_lifecycle_register(register, calibration=calibration, authority=authority)
    if not result["clean"]:
        raise LifecycleRegisterError(
            "refusing to persist a not-clean lifecycle_register; first violations: %s" % (result["violations"][:5],)
        )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)  # the gitignored lifecycle dir may not exist yet
    out_path.write_text(json.dumps(register, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


def load_lifecycle_register(in_path, *, expected_as_of=None, calibration=None, authority=None) -> dict:
    """Load + re-validate a persisted lifecycle_register; fail closed on a stale / misaligned / bad artifact.

    The §18.0 P0 private-path guard runs FIRST on ``in_path`` — SYMMETRIC with the persister: a private
    lifecycle artifact must be READ only from a provably-private source (gitignored in-repo or outside-repo),
    so a relative / non-gitignored in-repo source is refused (``PrivatePathError``) before any read
    (R-USSHORT-BATCH3-R2-LIFECYCLE-LOAD-PRIVATE-PATH-GUARD-GAP — a tracked-path register, planted or
    accidentally committed, must never enter the pipeline). Returns the loaded register dict. Raises
    ``StaleLifecycleArtifactError`` if the file is missing / unreadable / not valid JSON, or — when
    ``expected_as_of`` is the run's decision_date — the persisted as_of is NEWER than ``expected_as_of``
    (§2.1 桶名 ≠ decision_date → fail-closed 弃 / §18.1 #20 陈旧 artifact). Raises ``LifecycleRegisterError``
    if the persisted CONTENT is not §13-clean (never consume an un-validated accumulator). Re-running the SAME
    decision_date (as_of == expected_as_of, idempotent) and normal forward progress (as_of < expected_as_of)
    are both fine.
    """
    reject_nonprivate_output_path(in_path)  # §18.0 P0 guard — symmetric: read a private artifact ONLY from a provably-private source
    in_path = Path(in_path)
    try:
        raw = in_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as e:
        raise StaleLifecycleArtifactError("lifecycle_register artifact unreadable at %s: %s" % (in_path, e))
    try:
        register = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise StaleLifecycleArtifactError("lifecycle_register artifact at %s is not valid JSON: %s" % (in_path, e))

    result = validate_lifecycle_register(register, calibration=calibration, authority=authority)
    if not result["clean"]:
        raise LifecycleRegisterError(
            "refusing to load a not-clean lifecycle_register from %s; first violations: %s"
            % (in_path, result["violations"][:5])
        )

    if expected_as_of is not None:
        if not _strict_yyyymmdd(expected_as_of):
            raise StaleLifecycleArtifactError("expected_as_of %r is not a strict real YYYYMMDD" % (expected_as_of,))
        as_of = register.get("as_of")  # a §13-clean register guarantees as_of is a strict YYYYMMDD (string compare OK)
        if isinstance(as_of, str) and as_of > expected_as_of:
            raise StaleLifecycleArtifactError(
                "stale / misaligned lifecycle bucket: persisted as_of %s is NEWER than the run decision_date %s "
                "(an older decision_date run against an ahead register, §2.1 / §18.1 #20) — fail closed"
                % (as_of, expected_as_of)
            )
    return register
