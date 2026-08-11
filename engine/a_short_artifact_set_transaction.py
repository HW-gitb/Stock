"""Commit a set of files as one unit, or leave every one of them untouched.

A weekly sidecar publishes a *pair* of tracked artifacts (a JSON summary and the
Markdown rendered from it), and those artifacts only mean anything together and
only relative to the private ledger they were derived from.  Writing them one at
a time leaves observable half-states: a JSON ahead of its Markdown, or a public
pair ahead of the ledger that is supposed to justify it.  The second of those
has already been observed once and it turned the whole lane red for reasons
unrelated to whoever was running it.

``_replace_many_with_rollback`` in the weekly pipeline already handles the
in-process half of this, but only that half: it unwinds an exception, not a
process that dies between two ``os.replace`` calls.  This module adds the
missing half by leaving a journal on disk before touching anything, so the next
reader can roll a dead run back before it reads.

**Durability boundary, stated plainly.** The transaction fsyncs the journal and
every backup file it writes, and each individual replacement is atomic because
``os.replace`` is.  It does **not** fsync the containing directory: Windows
cannot open a directory handle, so ``os.fsync`` on a directory is unavailable on
this platform.  A power loss can therefore still lose a directory entry that was
never flushed.  What survives a crash is the guarantee this module actually
claims: either the journal is gone (the set committed) or the journal is present
and names every old byte needed to undo the partial set.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


JOURNAL_NAME = "artifact_set_journal.json"
BACKUP_DIR_NAME = "artifact_set_backup"

#: The whole point of this module is to keep half-written state out of tracked
#: space, so a journal directory inside the published results tree would defeat
#: it: every weekly run would leave journal and backup files exactly where the
#: pair it protects is committed.
_FORBIDDEN_JOURNAL_PARENTS = ("research/results",)


class ArtifactSetTransactionError(RuntimeError):
    """Raised when a set cannot be committed, or a stale journal is unusable."""


def _durable_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _replace_durably(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    _durable_write(temporary, payload)
    os.replace(temporary, target)


def _check_journal_dir(journal_dir: Path) -> None:
    posix = journal_dir.resolve().as_posix()
    for forbidden in _FORBIDDEN_JOURNAL_PARENTS:
        if f"/{forbidden}/" in f"{posix}/":
            raise ArtifactSetTransactionError(
                f"artifact-set journal may not live under {forbidden}: {journal_dir}")


def _journal_paths(journal_dir: Path) -> tuple[Path, Path]:
    return journal_dir / JOURNAL_NAME, journal_dir / BACKUP_DIR_NAME


def _undo(journal_dir: Path, entries: list[dict], *, strict: bool) -> list[str]:
    """Put back everything the journal says was there; report what could not be.

    ``strict`` is the in-flight rollback: the backups were written moments ago by
    this very call, so a failure there is a live fault and must propagate.  A
    *recovery* rollback is not strict -- it runs against whatever a dead process
    happened to leave, and refusing to continue there is what wedges the track.
    """
    _, backup_dir = _journal_paths(journal_dir)
    unrestorable = []
    for entry in entries:
        target = Path(entry["target"])
        backup = entry.get("backup")
        try:
            if backup is None:
                # The target did not exist before this transaction.  Deleting a
                # file the failed run never got to create is a no-op.
                target.unlink(missing_ok=True)
            else:
                _replace_durably(target, (backup_dir / backup).read_bytes())
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.unlink(missing_ok=True)
        except OSError as exc:
            unrestorable.append(f"{target}: {exc}")
    if unrestorable and strict:
        raise ArtifactSetTransactionError(
            "artifact-set rollback could not restore: " + "; ".join(unrestorable))
    return unrestorable


def _clear(journal_dir: Path) -> None:
    """Retire the journal FIRST, then the backups it pointed at.

    Order is the whole point.  An orphan backup is harmless -- the next
    transaction overwrites `NNN.bak` -- while an orphan journal names backups
    that no longer exist, and every later `recover()` would try, fail, and leave
    the journal in place, refusing this track forever.
    """
    journal_path, backup_dir = _journal_paths(journal_dir)
    journal_path.unlink(missing_ok=True)
    if backup_dir.is_dir():
        for child in backup_dir.iterdir():
            child.unlink(missing_ok=True)
        backup_dir.rmdir()


def read_journal(journal_dir: str | Path) -> dict | None:
    """Return the journal a dead run left behind, or ``None`` if there is none."""
    journal_path, _ = _journal_paths(Path(journal_dir))
    if not journal_path.is_file():
        return None
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactSetTransactionError(
            f"artifact-set journal is unreadable: {journal_path}") from exc
    if not isinstance(journal, dict) or not isinstance(journal.get("entries"), list):
        raise ArtifactSetTransactionError(
            f"artifact-set journal is malformed: {journal_path}")
    return journal


def recover(journal_dir: str | Path) -> dict | None:
    """Roll back a set a dead process left half-written, then clear the journal.

    Safe and cheap to call before every read or write of the protected set: with
    no journal it does nothing.  Rolling *back* rather than forward is the
    deliberate choice -- the old bytes are known to be self-consistent, while a
    half-applied new set is exactly the state that has to be impossible.

    **Recovery never refuses.** It is the first thing every commit does, so an
    exception here would stop this track from ever publishing again -- and in
    the weekly pipeline that failure is caught and logged as one more
    `capture_unavailable`, so nobody would find out. Whatever it cannot undo is
    named on stderr and returned in ``unrestorable``, and the journal is retired
    either way so the next commit proceeds.
    """
    journal_dir = Path(journal_dir)
    try:
        journal = read_journal(journal_dir)
        unreadable = False
    except ArtifactSetTransactionError:
        journal, unreadable = None, True
    if journal is None and not unreadable:
        return None
    entries = journal["entries"] if journal else []
    unrestorable = _undo(journal_dir, entries, strict=False)
    _clear(journal_dir)
    report = {
        "recovered": True,
        "targets": [entry["target"] for entry in entries],
        "unrestorable": unrestorable,
        "journal_unreadable": unreadable,
    }
    if unrestorable or unreadable:
        detail = "; ".join(unrestorable) if unrestorable else str(journal_dir)
        print(f"[artifact-set] WARNING recovery could not undo everything "
              f"({'unreadable journal' if unreadable else 'missing backups'}): {detail}. "
              "The journal has been retired so this track keeps publishing; verify "
              "the listed files by hand.", file=sys.stderr)
    return report


def commit_artifact_set(journal_dir: str | Path, files: dict[str | Path, bytes], *,
                        delete_paths: list[str | Path] | tuple[str | Path, ...] = ()) -> None:
    """Write/delete every member, or leave every one of them exactly as it was.

    ``files`` maps each target path to its complete bytes; callers build all of
    them first, so a validation failure happens before anything is touched.
    ``delete_paths`` is used only for a materialized view whose old files are no
    longer part of the selected revision.  Deletions are journaled with the
    same old-byte backup and rollback guarantees as replacements.
    """
    journal_dir = Path(journal_dir)
    if not files:
        return
    _check_journal_dir(journal_dir)
    if any(not isinstance(payload, (bytes, bytearray)) for payload in files.values()):
        raise ArtifactSetTransactionError("artifact-set payloads must be bytes")
    # Never commit on top of somebody else's unresolved journal: that would
    # write new bytes over an old backup set and make the earlier run
    # unrecoverable.
    recover(journal_dir)

    targets = [(Path(target), bytes(payload), "write") for target, payload in files.items()]
    existing_targets = {target for target, _payload, _operation in targets}
    for target in delete_paths:
        target_path = Path(target)
        if target_path in existing_targets:
            raise ArtifactSetTransactionError(
                f"artifact-set target is both written and deleted: {target_path}")
        targets.append((target_path, b"", "delete"))
    targets.sort(key=lambda item: item[0].as_posix())
    _, backup_dir = _journal_paths(journal_dir)
    entries = []
    for index, (target, _payload, _operation) in enumerate(targets):
        if target.is_file():
            backup_name = f"{index:03d}.bak"
            _durable_write(backup_dir / backup_name, target.read_bytes())
        else:
            backup_name = None
        entries.append({"target": str(target), "backup": backup_name})
    journal = {
        "schema_name": "a_short_artifact_set_journal",
        "schema_version": "1.0.0",
        "entries": entries,
    }
    journal_path, _ = _journal_paths(journal_dir)
    # The journal is the one file everything else trusts, so it may not be the
    # one file written in place: a torn or zero-byte journal used to be
    # unreadable, and an unreadable journal used to be unrecoverable.
    _replace_durably(journal_path, json.dumps(journal, ensure_ascii=False, sort_keys=True,
                                              indent=1, allow_nan=False).encode("utf-8"))
    try:
        for target, payload, operation in targets:
            if operation == "delete":
                target.unlink(missing_ok=True)
            else:
                _replace_durably(target, payload)
    except BaseException:
        _undo(journal_dir, entries, strict=True)
        _clear(journal_dir)
        raise
    _clear(journal_dir)
