"""Derived guard for canonical digests of tracked JSON contracts.

Tracked contracts are edited under different checkout EOL policies.  A digest
that binds one of them therefore has to be the canonical JSON digest, never a
hash of the checkout bytes.  Runtime state remains outside this rule: its raw
bytes are evidence and may legitimately be hashed as received.
"""
from __future__ import annotations

import ast
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (ROOT / "engine", ROOT / "runners")
TRACKED_PREFIXES = ("docs", "presets", "schemas")

# A coordinate may be excepted only when the raw bytes are deliberately part
# of the contract.  Keep this map empty unless such a case is reviewed.
RAW_DIGEST_EXCEPTIONS: dict[str, str] = {}


def _path_parts(node: ast.AST, constants: dict[str, tuple[str, ...]]) -> tuple[str, ...] | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _path_parts(node.left, constants)
        right = _path_parts(node.right, constants)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path" and node.args:
        return _path_parts(node.args[0], constants)
    return () if isinstance(node, ast.Name) and node.id in {"ROOT", "REPO_ROOT", "PROJECT_ROOT"} else None


def _module_constants(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    constants: dict[str, tuple[str, ...]] = {
        "ROOT": (), "REPO_ROOT": (), "PROJECT_ROOT": (), "_ROOT": (),
    }
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if value is None:
            continue
        parts = _path_parts(value, constants)
        if parts is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = parts
    return constants


def _is_gitignored(relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "--quiet", "--", relative_path],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _tracked_constant_name(node: ast.AST, constants: dict[str, tuple[str, ...]]) -> str | None:
    candidate_node = node
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Path"
        and node.args
    ):
        candidate_node = node.args[0]
    candidate = candidate_node.id if isinstance(candidate_node, ast.Name) else None
    parts = _path_parts(node, constants)
    if candidate is None or not parts or parts[0] not in TRACKED_PREFIXES:
        return None
    relative_path = Path(*parts).as_posix()
    return None if _is_gitignored(relative_path) else candidate


def _raw_reader_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Name):
        return None
    normalized = node.id.lower()
    return node.id if "read" in normalized and "bytes" in normalized else None


def _raw_digest_coordinates(relative_path: Path, source: str) -> set[str]:
    tree = ast.parse(source, filename=str(relative_path))
    constants = _module_constants(tree)
    coordinates: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        constant_name: str | None = None
        if isinstance(node.func, ast.Attribute) and node.func.attr == "read_bytes":
            constant_name = _tracked_constant_name(node.func.value, constants)
        elif _raw_reader_name(node.func) and node.args:
            constant_name = _tracked_constant_name(node.args[0], constants)
        if constant_name:
            coordinates.add(f"{relative_path.as_posix()}:{node.lineno}:{constant_name}")
    return coordinates


def _derived_raw_digest_coordinates(sources: dict[Path, str] | None = None) -> set[str]:
    if sources is None:
        sources = {
            path.relative_to(ROOT): path.read_text(encoding="utf-8")
            for source_root in SOURCE_ROOTS
            for path in source_root.rglob("*.py")
        }
    return {
        coordinate
        for relative_path, source in sources.items()
        for coordinate in _raw_digest_coordinates(relative_path, source)
    }


class TrackedArtifactDigestCanonicalizationTests(unittest.TestCase):
    def test_every_derived_tracked_raw_digest_has_an_explicit_exception(self) -> None:
        """The class is derived from engine/runners, not a hand-written registry."""
        derived = _derived_raw_digest_coordinates()
        unexplained = sorted(derived - RAW_DIGEST_EXCEPTIONS.keys())
        self.assertEqual(unexplained, [], "tracked JSON must use _serialized_sha256: " + ", ".join(unexplained))
        stale = sorted(set(RAW_DIGEST_EXCEPTIONS) - derived)
        self.assertEqual(stale, [], "exception no longer names a derived raw-digest coordinate: " + ", ".join(stale))
        self.assertTrue(all(reason.strip() for reason in RAW_DIGEST_EXCEPTIONS.values()))

    def test_original_epoch_raw_reader_is_a_red_control(self) -> None:
        relative_path = Path("engine/us_short_soft_boost_consumption.py")
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        mutant = source.replace(
            "epoch, epoch_sha = _read_canonical_json(EPOCH_PATH)",
            "epoch, epoch_sha = _read_json_bytes(EPOCH_PATH)",
            1,
        )
        self.assertNotEqual(mutant, source, "epoch canonical call moved; update this red control")
        coordinates = _derived_raw_digest_coordinates({relative_path: mutant})
        self.assertTrue(
            any(coordinate.endswith(":EPOCH_PATH") for coordinate in coordinates),
            f"original epoch raw-reader mutation escaped the derived guard: {coordinates}",
        )

    def test_future_third_tracked_raw_hash_is_a_red_control(self) -> None:
        relative_path = Path("runners/future_digest_leg.py")
        source = '''\
from pathlib import Path
import hashlib
ROOT = Path(__file__).resolve().parents[1]
FUTURE_SCHEMA = ROOT / "schemas" / "future.json"
def bad() -> str:
    return hashlib.sha256(FUTURE_SCHEMA.read_bytes()).hexdigest()
'''
        coordinates = _derived_raw_digest_coordinates({relative_path: source})
        self.assertEqual(coordinates, {"runners/future_digest_leg.py:6:FUTURE_SCHEMA"})

    def test_runtime_state_raw_bytes_are_not_in_the_tracked_contract_class(self) -> None:
        relative_path = Path("engine/runtime_receipt.py")
        source = '''\
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
STATE_RECEIPT = ROOT / "state" / "us_short" / "receipt.json"
def read() -> object:
    return _read_json_bytes(STATE_RECEIPT)
'''
        self.assertEqual(_derived_raw_digest_coordinates({relative_path: source}), set())


if __name__ == "__main__":
    unittest.main()
