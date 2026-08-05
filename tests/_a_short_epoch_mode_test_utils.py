"""Test-only helpers for the registry-owned A-short evidence modes."""
from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from engine import a_short_evidence_epoch_mode as epoch_mode


def _resealed_freeze_packet(path: Path) -> None:
    packet = json.loads(
        epoch_mode.FIFTH_KNIFE_FREEZE_PACKET_PATH.read_text(encoding="utf-8")
    )
    for contract in packet["frozen_contracts"]:
        # Seal what decides, not the file bytes: a comment or a reordered key
        # must not be able to discard accumulated evidence.
        contract.pop("sha256", None)
        contract["projection"] = epoch_mode._CONTRACT_PROJECTIONS[contract["name"]]
        contract["semantic_fingerprint"] = epoch_mode.contract_semantic_fingerprint(
            contract["name"]
        )
    packet["record_sha256"] = epoch_mode._canonical_json_sha256({
        key: value for key, value in packet.items() if key != "record_sha256"
    })
    path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")


@contextmanager
def patched_epoch_modes(mode: str, tracks: tuple[str, ...] | None = None):
    selected = set(tracks or epoch_mode.TRACKS)
    modes = {
        track: mode if track in selected else "pre_freeze_audit_only"
        for track in epoch_mode.TRACKS
    }
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "registry.json"
        packet_path = Path(temp) / "freeze_packet.json"
        path.write_text(json.dumps({
            "schema_name": "a_short_evidence_epoch_mode_registry",
            "schema_version": "1.0.0",
            "track_modes": modes,
        }), encoding="utf-8")
        _resealed_freeze_packet(packet_path)
        with mock.patch.object(epoch_mode, "TRACK_MODE_REGISTRY_PATH", path), \
                mock.patch.object(
                    epoch_mode, "FIFTH_KNIFE_FREEZE_PACKET_PATH", packet_path,
                ):
            yield path


def enter_patched_epoch_modes(testcase, mode: str, tracks: tuple[str, ...] | None = None) -> None:
    context = patched_epoch_modes(mode, tracks)
    context.__enter__()
    testcase.addCleanup(context.__exit__, None, None, None)
