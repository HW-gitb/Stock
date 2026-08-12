#!/usr/bin/env python3
"""Machine evidence shared by the bounded focused runner and full-pack ledger.

The receipt is local state under ``.tools/state``.  It is deliberately bound to
the exact tracked non-document code tree, any uncommitted non-document files,
and the pinned project interpreter, so a human sentence such as
``focused=12 OK`` cannot authorize a full-pack run.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
PINNED_PYTHON = Path(r"C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe")
RECEIPT_PATH = ROOT / ".tools" / "state" / "focused_acceptance_receipt.json"
RECEIPT_SCHEMA_VERSION = "1.0"

# This is the one canonical effect-contract acceptance bundle.  Both sides of
# the producer/consumer contract must travel in the same bounded focused run.
FOCUSED_BUNDLES: dict[str, frozenset[str]] = {
    "a_short_effect_contract": frozenset(
        {
            "tests.test_a_short_effect_contract",
            "tests.test_a_short_effect_consumer_probe",
        }
    ),
}

# These are the A-short producer/consumer/schema surfaces whose focused proof
# must include the effect bundle.  The mapping is intentionally explicit: a
# future new surface must be added here together with its acceptance test.
EFFECT_CONTRACT_SURFACES = frozenset(
    {
        "A-EGS/egs_main.py",
        "engine/a_short_effect_contract.py",
        "runners/a_short_m67_render.py",
        "runners/a_short_official_operation_evidence.py",
        "runners/a_short_weekly_pipeline.py",
        "schemas/a_short_m67_effect_contract.json",
        "schemas/a_short_weekly_report.schema.json",
        "schemas/analysis_input.schema.json",
        "tests/test_a_short_effect_contract.py",
        "tests/test_a_short_effect_consumer_probe.py",
    }
)


def _normalise(rel_path: str) -> str:
    return rel_path.replace("\\", "/")


def is_code_path(rel_path: str) -> bool:
    """Match the full-pack ledger boundary: docs-only edits do not invalidate code."""
    rel = _normalise(rel_path)
    return not (rel.startswith("docs/") or rel.endswith(".md"))


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), "-c", "core.quotePath=false", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    ).stdout


def _git_stdin(*args: str, stdin: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), "-c", "core.quotePath=false", *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    ).stdout


def code_paths_now() -> set[str]:
    """Every code path that exists for this working tree, tracked or not."""
    paths: set[str] = set()
    for args in (("ls-files",), ("ls-files", "--others", "--exclude-standard")):
        for line in _git(*args).splitlines():
            rel = _normalise(line)
            if rel and is_code_path(rel):
                paths.add(rel)
    return paths


def _effective_code_content_sha256() -> str:
    """Hash what the code files actually contain right now.

    Deliberately blind to whether that content is staged or committed.  A
    focused run tests bytes, not git status, so `git add` and `git commit` of
    the very bytes it just tested must leave its receipt valid -- otherwise the
    gate forces a rerun that can only confirm what was already confirmed.
    Editing, adding, or deleting a code file does change this value.

    Every path is hashed the same way, from disk.  Mixing git blob ids (cheap
    for clean files) with content hashes (needed for dirty ones) would move a
    file between hash spaces the moment it was staged, which is the very flip
    this function exists to remove.
    """
    content: dict[str, str] = {}
    modes: dict[str, str] = {}
    from_disk: set[str] = set()
    for line in _git("ls-files", "-s").splitlines():
        if "\t" not in line:
            continue
        meta, rel = line.split("\t", 1)
        rel = _normalise(rel)
        if not is_code_path(rel):
            continue
        fields = meta.split()
        if len(fields) < 3:
            continue
        mode, blob, stage = fields[0], fields[1], fields[2]
        modes[rel] = mode
        if stage == "0":
            # Mode carries the entry TYPE: 100644/100755 blob, 120000 symlink,
            # 160000 gitlink.  Re-typing a path to a symlink keeps the id while
            # changing what a POSIX checkout executes, so the id alone is not
            # the file.  The retired tree hash covered this by hashing whole
            # `ls-tree` lines; dropping it here would have been a quiet loss.
            content[rel] = f"{mode} {blob}"
        else:  # unmerged: the working copy, not any one side, is the truth
            from_disk.add(rel)
    for args in (("diff-files", "--name-only"), ("ls-files", "--others", "--exclude-standard")):
        for line in _git(*args).splitlines():
            rel = _normalise(line)
            if rel and is_code_path(rel):
                from_disk.add(rel)
    present = sorted(rel for rel in from_disk if (ROOT / rel).is_file())
    for rel in from_disk:
        content[rel] = "ABSENT"
    if present:
        # `hash-object` applies the same per-path clean filters git used for the
        # index entries above, so both halves stay in one id space.
        hashed = _git_stdin("hash-object", "--stdin-paths", stdin="\n".join(present) + "\n").split()
        if len(hashed) != len(present):  # never seal a half-read tree
            raise RuntimeError("git hash-object did not return one id per code path")
        for rel, disk_id in zip(present, hashed):
            content[rel] = f"{modes.get(rel, 'untracked')} {disk_id}"
    canonical = "\n".join(f"{rel}:{content[rel]}" for rel in sorted(content))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def changed_code_paths() -> set[str]:
    """Code paths this working tree changes relative to HEAD.

    Only drives which acceptance bundles a commit must show; it is not part of
    the seal, because "which files moved" is a different question from "what do
    the files contain".
    """
    changed = [line for line in _git("diff", "HEAD", "--name-only").splitlines() if line]
    untracked = [
        line
        for line in _git("ls-files", "--others", "--exclude-standard").splitlines()
        if line
    ]
    return {_normalise(rel) for rel in set(changed) | set(untracked) if is_code_path(rel)}


def collect_code_state() -> dict[str, str]:
    """The content seal, plus the changed paths that decide bundle demands."""
    state: dict[str, str] = {}
    for rel in changed_code_paths():
        path = ROOT / rel
        state[rel] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "ABSENT"
        )
    state["@CODE_CONTENT"] = _effective_code_content_sha256()
    return state


def fingerprint(state: dict[str, str]) -> str:
    """Seal only the ``@`` keys: they already cover every code path's content.

    The per-path entries alongside them record which files a commit touches,
    and that set legitimately empties out on commit while the content stays
    identical.  Sealing it too is what made a commit look like a code change.
    """
    sealed = sorted(key for key in state if key.startswith("@"))
    canonical = "\n".join(f"{key}:{state[key]}" for key in sealed)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bundles_for_paths(paths: Iterable[str]) -> tuple[str, ...]:
    if set(paths) & EFFECT_CONTRACT_SURFACES:
        return ("a_short_effect_contract",)
    return ()


def required_bundles_for_state(state: dict[str, str]) -> tuple[str, ...]:
    return _bundles_for_paths(
        _normalise(path) for path in state if not path.startswith("@")
    )


def merge_in_progress() -> bool:
    return bool(_git("rev-parse", "-q", "--verify", "MERGE_HEAD").strip())


def merge_side_paths() -> frozenset[str]:
    """Code paths either side of a merge changed since their common base.

    ``collect_code_state`` sees a merge from one side only: HEAD is the first
    parent, so everything already on our side reads as unchanged and only the
    incoming half shapes the evidence being demanded.  A merge is the moment a
    combination first exists, so what it has to show should be derived from
    both of the things being combined.  Empty when no merge is in progress.
    """
    if not merge_in_progress():
        return frozenset()
    base = _git("merge-base", "HEAD", "MERGE_HEAD").strip()
    if not base:
        return frozenset()
    paths: set[str] = set()
    for side in ("HEAD", "MERGE_HEAD"):
        paths.update(
            line for line in _git("diff", "--name-only", f"{base}..{side}").splitlines() if line
        )
    return frozenset(_normalise(path) for path in paths if is_code_path(path))


def required_bundles_now(state: dict[str, str]) -> tuple[str, ...]:
    """What this commit must show, widened across both sides when merging."""
    changed = {
        _normalise(path) for path in state if not path.startswith("@")
    }
    return _bundles_for_paths(changed | set(merge_side_paths()))


def bundle_for_args(unittest_args: Iterable[str]) -> tuple[str, ...]:
    args = set(unittest_args)
    return tuple(
        name for name, required in FOCUSED_BUNDLES.items() if required.issubset(args)
    )


def _canonical_path(path: Path) -> str:
    return str(path.resolve()).replace("/", "\\").casefold()


def pinned_python_error() -> str | None:
    if not PINNED_PYTHON.is_file():
        return f"pinned Stock Python was not found: {PINNED_PYTHON}"
    if _canonical_path(Path(sys.executable)) != _canonical_path(PINNED_PYTHON):
        return (
            "the command must run with the pinned Stock Python; "
            f"actual={Path(sys.executable).resolve()} expected={PINNED_PYTHON}"
        )
    return None


def receipt_token(receipt: dict) -> str:
    return f"receipt:{receipt['receipt_id']}"


def _receipt_id(body: dict) -> str:
    """Hash the WHOLE receipt body, so no recorded field sits outside the seal.

    An earlier form hashed only ``code_fingerprint`` + ``unittest_args``, which
    left ``tests`` -- the very number quoted as evidence -- editable without
    breaking the integrity check.  Everything except ``receipt_id`` itself is
    covered now; adding a future field seals it automatically.
    """
    raw = json.dumps(
        {key: value for key, value in body.items() if key != "receipt_id"},
        sort_keys=True,
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def write_focused_receipt(
    *,
    result_status: str,
    result_exit_code: int,
    tests: int | None,
    elapsed_seconds: float,
    timeout_seconds: int,
    unittest_args: list[str],
    state: dict[str, str] | None = None,
    path: Path = RECEIPT_PATH,
) -> dict | None:
    """Write only a successful, positive-count focused receipt."""
    if result_status != "PASS" or result_exit_code != 0 or tests is None or tests <= 0:
        return None
    current_state = state if state is not None else collect_code_state()
    code_fp = fingerprint(current_state)
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "PASS",
        "tier": "focused",
        "exit_code": 0,
        "tests": int(tests),
        "elapsed_seconds": round(float(elapsed_seconds), 3),
        "timeout_seconds": int(timeout_seconds),
        "unittest_args": list(unittest_args),
        "bundles": list(bundle_for_args(unittest_args)),
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": platform.python_version(),
        "code_fingerprint": code_fp,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    receipt["receipt_id"] = _receipt_id(receipt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=1, ensure_ascii=False), encoding="utf-8")
    return receipt


def load_receipt(path: Path = RECEIPT_PATH) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def validate_receipt(
    receipt: dict | None,
    *,
    state: dict[str, str] | None = None,
    required_bundles: tuple[str, ...] | None = None,
) -> tuple[bool, str]:
    if not isinstance(receipt, dict):
        return False, "focused acceptance receipt is missing or unreadable"
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        return False, "focused acceptance receipt schema is unsupported"
    if receipt.get("status") != "PASS" or receipt.get("tier") != "focused":
        return False, "focused acceptance receipt is not a PASS focused result"
    if receipt.get("exit_code") != 0 or not isinstance(receipt.get("tests"), int) or receipt["tests"] <= 0:
        return False, "focused acceptance receipt has invalid terminal test evidence"
    unittest_args = receipt.get("unittest_args")
    if not isinstance(unittest_args, list) or not unittest_args or not all(
        isinstance(arg, str) and arg for arg in unittest_args
    ):
        return False, "focused acceptance receipt has invalid unittest arguments"
    code_fingerprint = receipt.get("code_fingerprint")
    if not isinstance(code_fingerprint, str) or receipt.get("receipt_id") != _receipt_id(receipt):
        return False, "focused acceptance receipt integrity check failed"
    recorded_bundles = receipt.get("bundles")
    if not isinstance(recorded_bundles, list) or any(not isinstance(item, str) for item in recorded_bundles):
        return False, "focused acceptance receipt has invalid bundle evidence"
    if sorted(recorded_bundles) != sorted(bundle_for_args(unittest_args)):
        return False, "focused acceptance receipt bundle evidence does not match its unittest args"
    if _canonical_path(Path(str(receipt.get("python_executable", "")))) != _canonical_path(PINNED_PYTHON):
        return False, "focused acceptance receipt was not produced by the pinned Stock Python"
    if receipt.get("python_version") != platform.python_version():
        return False, "focused acceptance receipt Python version does not match the current pinned runtime"
    current_state = state if state is not None else collect_code_state()
    if receipt.get("code_fingerprint") != fingerprint(current_state):
        return False, "focused acceptance receipt does not match the current code state"
    required = required_bundles if required_bundles is not None else required_bundles_now(current_state)
    recorded_bundle_set = set(recorded_bundles)
    missing = [name for name in required if name not in recorded_bundle_set]
    if missing:
        return False, "focused acceptance receipt is missing bundle(s): " + ", ".join(missing)
    return True, "OK"


def validate_focused_evidence(
    evidence: str,
    *,
    state: dict[str, str] | None = None,
    path: Path = RECEIPT_PATH,
) -> tuple[dict | None, str]:
    """Validate the exact ``receipt:<id>`` token passed to the full-pack command."""
    if not isinstance(evidence, str) or not evidence.startswith("receipt:"):
        return None, "focused evidence must be the machine token `receipt:<receipt_id>`"
    receipt = load_receipt(path)
    ok, reason = validate_receipt(receipt, state=state)
    if not ok:
        return None, reason
    if receipt_token(receipt) != evidence:
        return None, "focused evidence token does not match the current receipt"
    return receipt, "OK"


def explain(
    *,
    state: dict[str, str] | None = None,
    path: Path = RECEIPT_PATH,
) -> tuple[int, list[str]]:
    """Say what the gate is comparing, so a FAIL does not need source reading.

    The one-line FAIL cannot distinguish "no receipt", "wrong Python", "code
    moved" and "missing bundle", and the required-bundle set was only reachable
    by importing the module by hand.

    Returns the gate's OWN exit code alongside the explanation, so this is a
    strict superset of the plain check rather than a softer alternative to it.
    An explain that always succeeded would be a trap: the whole reason to reach
    for it is an opaque FAIL, so the first person to wire it into
    ``.githooks/pre-commit`` for legibility would silently disarm the gate.
    """
    current_state = state if state is not None else collect_code_state()
    receipt = load_receipt(path)
    ok, reason = validate_receipt(receipt, state=current_state)
    current_fp = fingerprint(current_state)
    receipt_fp = receipt.get("code_fingerprint") if isinstance(receipt, dict) else None
    changed = sorted(key for key in current_state if not key.startswith("@"))
    merge_paths = merge_side_paths()
    lines = [
        f"pinned python      : {pinned_python_error() or 'OK'}",
        f"receipt file       : {path}",
        f"receipt            : {'present' if isinstance(receipt, dict) else 'missing/unreadable'}",
    ]
    if isinstance(receipt, dict):
        lines += [
            f"  id               : {receipt.get('receipt_id')}",
            f"  tests            : {receipt.get('tests')}",
            f"  recorded_at      : {receipt.get('recorded_at')}",
            f"  unittest_args    : {receipt.get('unittest_args')}",
            f"  bundles          : {receipt.get('bundles')}",
        ]
    lines += [
        f"code fingerprint   : now={current_fp} receipt={receipt_fp}",
        f"fingerprints match : {'yes' if receipt_fp == current_fp else 'NO'}",
        f"changed code paths : {len(changed)}",
    ]
    lines += [f"  - {rel}" for rel in changed[:12]]
    if len(changed) > 12:
        lines.append(f"  ... and {len(changed) - 12} more")
    lines += [
        f"merge in progress  : {'yes' if merge_in_progress() else 'no'}"
        + (f" (+{len(merge_paths)} merge-side code paths)" if merge_paths else ""),
        f"required bundles   : {required_bundles_now(current_state)}",
        f"verdict            : {'PASS' if ok else 'FAIL'} - {reason}",
    ]
    return (0 if ok and not pinned_python_error() else 1), lines


def explain_lines(
    *,
    state: dict[str, str] | None = None,
    path: Path = RECEIPT_PATH,
) -> list[str]:
    return explain(state=state, path=path)[1]


if __name__ == "__main__":
    if "--explain" in sys.argv[1:]:
        exit_code, lines = explain()
        print("[verification-receipt] EXPLAIN")
        for line in lines:
            print(f"  {line}")
        raise SystemExit(exit_code)
    if pinned_python_error():
        print(f"[verification-receipt] REFUSED - {pinned_python_error()}")
        raise SystemExit(2)
    receipt = load_receipt()
    ok, reason = validate_receipt(receipt)
    print(f"[verification-receipt] {'PASS' if ok else 'FAIL'} - {reason}")
    raise SystemExit(0 if ok else 1)
