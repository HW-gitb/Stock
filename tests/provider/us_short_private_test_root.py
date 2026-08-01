from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_OWNERSHIP_MARKER = ".us_short_test_private_root_owned"
_TEMP_ROOT_MARKER = ".us_short_test_temp_root_owned"
_LOCKS_GUARD = threading.Lock()
_ROOT_LOCKS: dict[Path, threading.RLock] = {}
_THREAD_STATE = threading.local()


def _root_lock(root: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        return _ROOT_LOCKS.setdefault(root, threading.RLock())


def _acquire_process_lock(root: Path):
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:20]
    path = Path(tempfile.gettempdir()) / f"us_short_private_test_root_{digest}.lock"
    handle = path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _release_process_lock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()


@contextmanager
def temporary_provider_directory(
    repo_root: Path,
    relative_parent: Path = Path("provider_samples"),
) -> Iterator[str]:
    """Create an isolated in-repo private root without assuming ignored parents exist."""
    root = repo_root.resolve()
    lock = _root_lock(root)
    with lock:
        depths = getattr(_THREAD_STATE, "depths", {})
        handles = getattr(_THREAD_STATE, "handles", {})
        if depths.get(root, 0) == 0:
            handles[root] = _acquire_process_lock(root)
        depths[root] = depths.get(root, 0) + 1
        _THREAD_STATE.depths = depths
        _THREAD_STATE.handles = handles
        try:
            parent = (root / relative_parent).resolve()
            parent.relative_to(root)
            missing_parents: list[Path] = []
            cursor = parent
            while cursor != root and not cursor.exists():
                missing_parents.append(cursor)
                cursor = cursor.parent
            parent.mkdir(parents=True, exist_ok=True)
            for created in missing_parents:
                (created / _OWNERSHIP_MARKER).touch(exist_ok=True)
            try:
                with tempfile.TemporaryDirectory(dir=parent) as tempdir:
                    # Keep every in-repo private test root fail-closed for subprocesses that
                    # perform a real ``git check-ignore``.  The state wrapper used to add this
                    # boundary itself, leaving provider roots dependent on the repository's
                    # parent ignore rules and leaking evidence on a clean checkout.
                    Path(tempdir, ".gitignore").write_text("*\n", encoding="utf-8")
                    Path(tempdir, _TEMP_ROOT_MARKER).touch()
                    yield tempdir
            finally:
                cursor = parent
                while cursor != root:
                    marker = cursor / _OWNERSHIP_MARKER
                    if not marker.is_file():
                        cursor = cursor.parent
                        continue
                    if any(path != marker for path in cursor.iterdir()):
                        cursor = cursor.parent
                        continue
                    marker.unlink()
                    cursor.rmdir()
                    cursor = cursor.parent
        finally:
            depths[root] -= 1
            if depths[root] == 0:
                del depths[root]
                _release_process_lock(handles.pop(root))


@contextmanager
def temporary_us_short_directory(
    repo_root: Path,
    relative_parent: Path,
) -> Iterator[str]:
    """Create an isolated US-short private directory below the requested lane root.

    This is the shared seam for tests that need either ``provider_samples`` or
    ``state/us_short``.  The existing provider helper remains the implementation owner so
    the process lock, owned-parent markers, and cleanup rules cannot drift between roots.
    """
    with temporary_provider_directory(repo_root, relative_parent) as tempdir:
        yield tempdir


@contextmanager
def temporary_us_short_state_directory(repo_root: Path) -> Iterator[str]:
    """Create an isolated temporary directory below the US-short state root."""
    with temporary_us_short_directory(repo_root, Path("state") / "us_short") as tempdir:
        yield tempdir
