"""The single write door for the offline discovery lane, plus its immutability policy.

Every filesystem write in the lane goes through this module: the knife-1 ingest artifact,
the knife-2 validation artifact, the knife-3 web/X/merge packet+receipt pairs, the raw
provider receipts, and the one deliberately MUTABLE artifact (the live provider
reservation ledger).  Centralizing them is not tidiness — the recurring defect in this
lane was a policy applied at N-1 of N call sites (immutability at one of three writers,
the credential check at three of five sinks, the date-keyed slot at the writers but not
the readers, the format checker at six of seven validators).  With one door there is no
site N+1 to forget, and `tests/test_us_short_discovery_conformance.py` fails if a second
write primitive appears anywhere in the lane.

The one axis writers legitimately differ on is WHICH clock keys a retry may re-stamp, so
that is an explicit parameter instead of a per-writer reimplementation.  Knife-3 may
re-stamp only its top-level `generated_at`: each source's `fetched_at` is frozen evidence
and must survive retries unchanged.
"""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Sequence
from uuid import uuid4

# Retry clocks a re-run may legitimately re-stamp without minting different evidence.
CLOCK_KEYS_ARTIFACT: tuple[str, ...] = ("generated_at",)
CLOCK_KEYS_RECEIPT: tuple[str, ...] = ("generated_at",)
CLOCK_KEYS_NONE: tuple[str, ...] = ()
# The lane has exactly ONE mutable artifact family (the per-decision provider reservation
# counter).  Naming it here means the door - not a call site - decides what may be replaced;
MUTABLE_LEDGER_SUFFIX = "_budget.json"
CONFORMANCE_GUARDS = ("_serialized_payload", "_serialized_sha256")


class DiscoveryPublishPolicyError(ValueError):
    """A discovery writer tried to leave its own immutable decision-date slot."""


def _repo_relative(path: Path, *, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise DiscoveryPublishPolicyError("publish path must stay under the repository root") from exc


def _gitignored(path: Path, *, root: Path) -> bool:
    result = subprocess.run(
        ["git", "-c", "core.excludesFile=", "check-ignore", "-q", "--", _repo_relative(path, root=root)],
        cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    return result.returncode == 0


def validate_exact_decision_slot(
    path: Path | str, expected_path: Path, *, root: Path, state_dir: Path,
    gitignored: Callable[[Path], bool] | None = None,
) -> Path:
    """Accept only this writer's own decision-date slot, resolved against the REPO root.

    Resolving a relative spelling against the repository root rather than the process
    working directory keeps `--output-path state/us_short/<slot>.json` meaning the same
    thing for every writer no matter where the operator stands.  `gitignored` exists only so a
    caller can inject its own already-tested predicate (test seams); the POLICY - containment,
    suffix, ignored, exact slot - stays here in one place.
    """
    raw = Path(path)
    resolved = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        resolved.relative_to(state_dir.resolve())
    except ValueError as exc:
        raise DiscoveryPublishPolicyError("publish path must stay under state/us_short") from exc
    is_ignored = gitignored(resolved) if gitignored is not None else _gitignored(resolved, root=root)
    if resolved.suffix != ".json" or not is_ignored:
        raise DiscoveryPublishPolicyError("publish path must be a gitignored JSON file")
    if resolved != expected_path.resolve():
        raise DiscoveryPublishPolicyError("publish path must use this writer's decision-date artifact slot")
    return resolved


def evidence_bytes(
    payload: Any, *, clock_keys: Sequence[str] = CLOCK_KEYS_ARTIFACT, recursive: bool = False,
) -> bytes:
    """Canonical bytes of a payload's EVIDENCE: everything except the declared retry clocks."""
    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: strip(value) for key, value in node.items() if key not in clock_keys}
        if isinstance(node, list):
            return [strip(item) for item in node]
        return node

    if recursive:
        pruned = strip(payload)
    elif isinstance(payload, dict):
        pruned = {key: value for key, value in payload.items() if key not in clock_keys}
    else:
        pruned = payload
    try:
        return json.dumps(pruned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise DiscoveryPublishPolicyError("immutable artifact evidence is not serializable") from exc


def frozen_artifact_matches(
    payload: Any, path: Path, *, clock_keys: Sequence[str] = CLOCK_KEYS_ARTIFACT, recursive: bool = False,
    verify: Callable[[Any], None] | None = None,
) -> bool:
    """False when the slot is free; True when an evidence-equivalent artifact is frozen there.

    `verify` lets a writer require that the FROZEN bytes still satisfy its own contract: a
    tampered artifact must not be reported as a successful reuse just because the evidence
    bytes match.
    """
    if not path.exists():
        return False
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise DiscoveryPublishPolicyError("refusing to replace an unreadable frozen artifact") from exc
    if (evidence_bytes(existing, clock_keys=clock_keys, recursive=recursive)
            != evidence_bytes(payload, clock_keys=clock_keys, recursive=recursive)):
        raise DiscoveryPublishPolicyError("immutable decision-date artifact already exists with different evidence")
    if verify is not None:
        try:
            verify(existing)
        except DiscoveryPublishPolicyError:
            raise
        except Exception as exc:
            raise DiscoveryPublishPolicyError(
                f"frozen artifact no longer satisfies its own contract: {exc}"
            ) from exc
    return True


def _serialized_payload(payload: Any) -> bytes:
    """Serialize before any filesystem side effect so bad text cannot leave residue."""
    try:
        return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise DiscoveryPublishPolicyError("immutable artifact payload is not serializable") from exc


def _serialized_sha256(payload: Any) -> str:
    """Digest the exact bytes the shared immutable writer will publish."""
    return hashlib.sha256(_serialized_payload(payload)).hexdigest()


def _staged_temp(path: Path, serialized: bytes, *, suffix: str = "tmp") -> Path:
    """Stage the bytes in a hidden, uniquely named sibling created EXCLUSIVELY.

    The temp is discarded here if the staging write itself fails.  Relying on the caller's
    `finally` was wrong: this function raised BEFORE returning the name, so a disk-full or IO
    error left a permanent hidden partial file - at all three writers at once.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.{suffix}")
    try:
        with tmp.open("xb") as handle:
            handle.write(serialized)
    except BaseException:
        _discard([tmp])
        raise
    return tmp


def _discard(paths: Sequence[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def write_immutable_json(
    payload: dict[str, Any], path: Path, *,
    clock_keys: Sequence[str] = CLOCK_KEYS_ARTIFACT, recursive: bool = False,
    verify: Callable[[Any], None] | None = None,
) -> bool:
    """Write once; return True when an evidence-equivalent frozen artifact was reused."""
    serialized = _serialized_payload(payload)
    if frozen_artifact_matches(payload, path, clock_keys=clock_keys, recursive=recursive, verify=verify):
        return True
    tmp: Path | None = None
    try:
        tmp = _staged_temp(path, serialized)
        try:
            # A hard link creates the final name atomically and fails rather than
            # overwriting evidence if another process won the same slot first.
            os.link(tmp, path)
        except FileExistsError:
            # Lost the race: keep the winner only if it holds the same evidence.
            return frozen_artifact_matches(
                payload, path, clock_keys=clock_keys, recursive=recursive, verify=verify,
            )
        return False
    except OSError as exc:
        raise DiscoveryPublishPolicyError("cannot write immutable decision-date artifact") from exc
    finally:
        _discard([tmp] if tmp is not None else [])


def publish_immutable_pair(
    items: Sequence[tuple[dict[str, Any], Path]], *,
    clock_keys: Sequence[str] = CLOCK_KEYS_RECEIPT, recursive: bool,
    verifiers: Sequence[Callable[[Any], None] | None] | None = None,
) -> None:
    """Publish several slots as a unit: stage all, then create final names, rolling back new peers."""
    paths = [path for _payload, path in items]
    if len({path.resolve() for path in paths}) != len(paths):
        raise DiscoveryPublishPolicyError("publish targets must be distinct")
    checks = tuple(verifiers) if verifiers is not None else (None,) * len(items)
    if len(checks) != len(items):
        raise DiscoveryPublishPolicyError("publish verifiers must align with publish items")
    staged: list[tuple[Path, Path, dict[str, Any], Callable[[Any], None] | None]] = []
    committed: list[Path] = []
    try:
        for (payload, path), verify in zip(items, checks):
            serialized = _serialized_payload(payload)
            if frozen_artifact_matches(
                payload, path, clock_keys=clock_keys, recursive=recursive, verify=verify,
            ):
                continue
            staged.append((_staged_temp(path, serialized, suffix="pair.tmp"), path, payload, verify))
        for tmp, path, payload, verify in staged:
            try:
                os.link(tmp, path)
            except FileExistsError:
                # Another writer won this slot: keep it only if it holds the same evidence.
                frozen_artifact_matches(
                    payload, path, clock_keys=clock_keys, recursive=recursive, verify=verify,
                )
                continue
            committed.append(path)
    except DiscoveryPublishPolicyError:
        _discard([tmp for tmp, _path, _payload, _verify in staged] + list(reversed(committed)))
        raise
    except OSError as exc:
        _discard([tmp for tmp, _path, _payload, _verify in staged] + list(reversed(committed)))
        raise DiscoveryPublishPolicyError("cannot publish the decision-date artifact pair") from exc
    finally:
        _discard([tmp for tmp, _path, _payload, _verify in staged])


def write_mutable_ledger(
    payload: dict[str, Any], path: Path, *, root: Path, state_dir: Path,
    gitignored: Callable[[Path], bool] | None = None,
) -> None:
    """The lane's ONE declared mutable write: the live provider reservation counter.

    A reservation ledger must accumulate attempts across retries, so it is deliberately
    replaceable — and it lives here rather than at its call site so that "one write door"
    stays a rule with no exceptions for the conformance pack to carve out.
    """
    # Same containment/suffix/gitignore policy as every other write - only the immutability
    # differs - so a second caller cannot aim this at an immutable slot or a tracked file.
    resolved = validate_exact_decision_slot(path, path, root=root, state_dir=state_dir, gitignored=gitignored)
    if not resolved.name.endswith(MUTABLE_LEDGER_SUFFIX):
        raise DiscoveryPublishPolicyError(
            "the mutable writer may only replace the reservation ledger, never an immutable artifact"
        )
    serialized = _serialized_payload(payload)
    tmp: Path | None = None
    try:
        tmp = _staged_temp(resolved, serialized)
        os.replace(tmp, resolved)
        tmp = None
    except OSError as exc:
        raise DiscoveryPublishPolicyError("cannot update the provider reservation ledger") from exc
    finally:
        _discard([tmp] if tmp is not None else [])
