"""Test-only helpers for the registry-owned A-short evidence modes."""
from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from engine import a_short_evidence_epoch_mode as epoch_mode


@contextmanager
def patched_epoch_modes(mode: str, tracks: tuple[str, ...] | None = None):
    selected = set(tracks or epoch_mode.TRACKS)
    modes = {
        track: mode if track in selected else "pre_freeze_audit_only"
        for track in epoch_mode.TRACKS
    }
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "registry.json"
        path.write_text(json.dumps({
            "schema_name": "a_short_evidence_epoch_mode_registry",
            "schema_version": "1.0.0",
            "track_modes": modes,
        }), encoding="utf-8")
        with mock.patch.object(epoch_mode, "TRACK_MODE_REGISTRY_PATH", path):
            yield path


def enter_patched_epoch_modes(testcase, mode: str, tracks: tuple[str, ...] | None = None) -> None:
    context = patched_epoch_modes(mode, tracks)
    context.__enter__()
    testcase.addCleanup(context.__exit__, None, None, None)
