from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_TEMP_ROOT_MARKER = ".us_short_test_temp_root_owned"


@contextmanager
def temporary_provider_directory(
    repo_root: Path,
    relative_parent: Path = Path("provider_samples"),
) -> Iterator[str]:
    """Create a private child; keep the shared parent so overlap cannot remove it."""
    root = repo_root.resolve()
    parent = (root / relative_parent).resolve()
    parent.relative_to(root)
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as tempdir:
        Path(tempdir, ".gitignore").write_text("*\n", encoding="utf-8")
        Path(tempdir, _TEMP_ROOT_MARKER).touch()
        yield tempdir


@contextmanager
def temporary_us_short_directory(
    repo_root: Path,
    relative_parent: Path,
) -> Iterator[str]:
    """Create an isolated US-short private directory below the requested lane root."""
    with temporary_provider_directory(repo_root, relative_parent) as tempdir:
        yield tempdir


@contextmanager
def temporary_us_short_state_directory(repo_root: Path) -> Iterator[str]:
    """Create an isolated temporary directory below the US-short state root."""
    with temporary_us_short_directory(repo_root, Path("state") / "us_short") as tempdir:
        yield tempdir
