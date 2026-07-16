"""Create and govern isolated, disposable full-run capsules.

This module deliberately does not know how to select stocks.  It supplies one
safe execution boundary for the A-short and US-short runtest launchers:
an exact detached clone, fresh runtime roots, a signed local manifest, and a
fail-closed deletion gate.  Production launchers do not call this module.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


MARKET_NAMES = {"a_short", "us_short"}
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
INPUT_LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
MANIFEST_NAME = "runtest_manifest.json"
ACTIVE_MARKER_NAME = ".runtest_active.json"
MANIFEST_SCHEMA = "stock_runtest_capsule"
MANIFEST_VERSION = "1.0.0"
DEFAULT_CAPSULE_ROOT = Path(
    os.environ.get("STOCK_RUNTEST_CAPSULE_ROOT", r"D:\cnhea\Stock_runtest_private")
)


class CapsuleError(RuntimeError):
    """A capsule invariant failed; callers must keep the capsule for inspection."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolved(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _is_strict_child(path: Path | str, parent: Path | str) -> bool:
    child = _resolved(path)
    root = _resolved(parent)
    try:
        return child != root and child.is_relative_to(root)
    except AttributeError:  # pragma: no cover - retained for older local Python
        try:
            child.relative_to(root)
        except ValueError:
            return False
        return child != root


def _require_child(path: Path | str, parent: Path | str, label: str) -> Path:
    candidate = _resolved(path)
    if not _is_strict_child(candidate, parent):
        raise CapsuleError(f"{label} must stay strictly under the configured capsule root")
    return candidate


def _validate_market_run(market: str, run_id: str) -> None:
    if market not in MARKET_NAMES:
        raise CapsuleError(f"unsupported market {market!r}")
    if not RUN_ID_RE.fullmatch(run_id):
        raise CapsuleError("run_id must be 1-64 safe letters, digits, dots, underscores, or hyphens")


def capsule_path(capsule_root: Path | str, market: str, run_id: str) -> Path:
    _validate_market_run(market, run_id)
    root = _resolved(capsule_root)
    return _require_child(root / market / run_id, root, "capsule path")


def _validate_capsule_layout(capsule: Path | str, capsule_root: Path | str) -> tuple[Path, str, str]:
    root = _resolved(capsule_root)
    target = _require_child(capsule, root, "capsule path")
    try:
        relative = target.relative_to(root)
    except ValueError as exc:  # pragma: no cover - _require_child already guards this
        raise CapsuleError("capsule is outside the configured root") from exc
    if len(relative.parts) != 2:
        raise CapsuleError("capsule must be exactly <capsule-root>/<market>/<run-id>")
    market, run_id = relative.parts
    _validate_market_run(market, run_id)
    return target, market, run_id


def _run_git(args: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise CapsuleError(f"git {' '.join(args[:2])} failed: {detail}")
    return completed.stdout.strip()


def _resolve_commit(source_root: Path, commit_ref: str) -> str:
    if not (source_root / ".git").exists():
        raise CapsuleError("source_root is not a standalone Git repository")
    if not commit_ref or commit_ref.startswith("-"):
        raise CapsuleError("commit ref is required and cannot start with '-'")
    return _run_git(["-C", str(source_root), "rev-parse", "--verify", f"{commit_ref}^{{commit}}"])


def _iter_guarded_files(source_root: Path) -> Iterable[tuple[str, int, int]]:
    # These are the fixed production and private-output roots that a full run
    # could otherwise mutate.  The manifest stores only a digest/count/bytes,
    # never a pathname list or file contents.
    guarded = (
        "A-EGS/Result",
        "logs",
        "state",
        "provider_samples",
        "result",
        "research/results",
    )
    # Output files a full run writes directly ABOVE a guarded directory root:
    # EGS emits its tier1 workbook to the A-EGS/ top level (CONF["xlsx_dir"]
    # default SCRIPT_DIR), not A-EGS/Result/, so the directory roots above would
    # otherwise miss a source-side A-EGS/*.xlsx mutation.
    guarded_globs = ("A-EGS/*.xlsx",)
    for relative_root in guarded:
        root = source_root / relative_root
        if not root.exists():
            continue
        if root.is_file():
            stat = root.stat()
            yield relative_root.replace("\\", "/"), stat.st_size, stat.st_mtime_ns
            continue
        for child in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            if child.is_file():
                stat = child.stat()
                yield child.relative_to(source_root).as_posix(), stat.st_size, stat.st_mtime_ns
    for pattern in guarded_globs:
        for match in sorted(source_root.glob(pattern), key=lambda item: item.as_posix()):
            if match.is_file():
                stat = match.stat()
                yield match.relative_to(source_root).as_posix(), stat.st_size, stat.st_mtime_ns


def source_guard_snapshot(source_root: Path | str) -> dict[str, Any]:
    source = _resolved(source_root)
    digest = hashlib.sha256()
    files = 0
    byte_count = 0
    for relative, size, mtime_ns in _iter_guarded_files(source):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(mtime_ns).encode("ascii"))
        digest.update(b"\n")
        files += 1
        byte_count += size
    return {"file_count": files, "byte_count": byte_count, "sha256": digest.hexdigest()}


def _default_key_path() -> Path:
    override = os.environ.get("STOCK_RUNTEST_CAPSULE_KEY_FILE")
    if override:
        return _resolved(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise CapsuleError("LOCALAPPDATA is unavailable; set STOCK_RUNTEST_CAPSULE_KEY_FILE to an external key file")
    return _resolved(Path(local_app_data) / "Stock" / "runtest_capsule_hmac.key")


def _load_or_create_key(key_path: Path | str | None, capsule_root: Path) -> bytes:
    key_file = _resolved(key_path) if key_path else _default_key_path()
    if _is_strict_child(key_file, capsule_root) or key_file == _resolved(capsule_root):
        raise CapsuleError("manifest signing key must remain outside the capsule root")
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if key_file.exists():
        key = key_file.read_bytes()
        if len(key) < 32:
            raise CapsuleError("capsule signing key is too short")
        return key
    key = secrets.token_bytes(32)
    fd, tmp_name = tempfile.mkstemp(prefix=".runtest_key_", dir=str(key_file.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, key_file)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return key


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sign_payload(payload: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, _canonical_payload(payload), hashlib.sha256).hexdigest()


def _write_manifest(repo: Path, manifest: dict[str, Any], key: bytes) -> None:
    payload = dict(manifest)
    payload.pop("signature", None)
    payload["signature"] = {"algorithm": "hmac-sha256", "value": _sign_payload(payload, key)}
    target = repo / MANIFEST_NAME
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, target)


def _read_manifest(capsule: Path, capsule_root: Path, key_path: Path | str | None) -> tuple[dict[str, Any], bytes]:
    target, market, run_id = _validate_capsule_layout(capsule, capsule_root)
    repo = target / "repo"
    manifest_path = repo / MANIFEST_NAME
    if not repo.is_dir() or not manifest_path.is_file():
        raise CapsuleError("capsule has no runnable repo or signed runtest manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapsuleError("capsule manifest is unreadable") from exc
    signature = manifest.pop("signature", None)
    if not isinstance(signature, dict) or signature.get("algorithm") != "hmac-sha256":
        raise CapsuleError("capsule manifest signature is missing or malformed")
    key = _load_or_create_key(key_path, _resolved(capsule_root))
    expected = _sign_payload(manifest, key)
    actual = signature.get("value")
    if not isinstance(actual, str) or not hmac.compare_digest(actual, expected):
        raise CapsuleError("capsule manifest signature does not verify")
    if (
        manifest.get("schema_name") != MANIFEST_SCHEMA
        or manifest.get("schema_version") != MANIFEST_VERSION
        or manifest.get("market") != market
        or manifest.get("run_id") != run_id
        or manifest.get("capsule_path") != str(target)
        or manifest.get("repo_path") != str(repo)
    ):
        raise CapsuleError("capsule manifest identity does not match its path")
    manifest["signature"] = signature
    return manifest, key


def _copy_inputs(capsule: Path, copy_inputs: dict[str, Path | str] | None) -> list[str]:
    copied: list[str] = []
    for label, source_value in (copy_inputs or {}).items():
        if not INPUT_LABEL_RE.fullmatch(label):
            raise CapsuleError(f"invalid private input label {label!r}")
        source = _resolved(source_value)
        if not source.is_file() or source.is_symlink():
            raise CapsuleError(f"private input {label!r} must be an existing regular file")
        destination = capsule / "private_inputs" / label
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(label)
    return sorted(copied)


def create_capsule(
    *,
    source_root: Path | str,
    capsule_root: Path | str = DEFAULT_CAPSULE_ROOT,
    market: str,
    run_id: str,
    commit_ref: str = "HEAD",
    copy_inputs: dict[str, Path | str] | None = None,
    key_path: Path | str | None = None,
) -> dict[str, Any]:
    """Create an exact, detached clone and its signed runtest manifest."""
    source = _resolved(source_root)
    root = _resolved(capsule_root)
    target = capsule_path(root, market, run_id)
    if not source.is_dir():
        raise CapsuleError("source_root does not exist")
    if source == root or _is_strict_child(source, root):
        raise CapsuleError("source_root cannot be the capsule root or one of its children")
    if target.exists():
        raise CapsuleError("capsule already exists; every runtest requires a new run_id")
    commit = _resolve_commit(source, commit_ref)
    key = _load_or_create_key(key_path, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    repo = target / "repo"
    try:
        _run_git(["clone", "--no-local", "--no-hardlinks", str(source), str(repo)])
        _run_git(["-C", str(repo), "checkout", "--detach", commit])
        _run_git(["-C", str(repo), "clean", "-ffdx"])
        copied_input_labels = _copy_inputs(target, copy_inputs)
        manifest: dict[str, Any] = {
            "schema_name": MANIFEST_SCHEMA,
            "schema_version": MANIFEST_VERSION,
            "market": market,
            "run_id": run_id,
            "run_mode": "runtest",
            "production_eligible": False,
            "ship_gate_evidence_allowed": False,
            "source_root": str(source),
            "source_commit": commit,
            "capsule_path": str(target),
            "repo_path": str(repo),
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "status": "prepared",
            "cache_policy": "disabled",
            "forbidden_runtime_reuse": ["cache", "checkpoint", "resume", "provider_raw", "source_packet"],
            "private_input_labels": copied_input_labels,
            "source_guard_before": source_guard_snapshot(source),
        }
        _write_manifest(repo, manifest, key)
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        raise
    return {"capsule": str(target), "repo": str(repo), "manifest": str(repo / MANIFEST_NAME)}


def activate_capsule(
    capsule: Path | str,
    *,
    capsule_root: Path | str = DEFAULT_CAPSULE_ROOT,
    key_path: Path | str | None = None,
) -> dict[str, Any]:
    root = _resolved(capsule_root)
    target, _, _ = _validate_capsule_layout(capsule, root)
    manifest, key = _read_manifest(target, root, key_path)
    marker = target / ACTIVE_MARKER_NAME
    if manifest.get("status") != "prepared" or marker.exists():
        raise CapsuleError("capsule is not in a prepared, inactive state")
    manifest.pop("signature", None)
    manifest["status"] = "active"
    manifest["updated_at"] = _utc_now()
    manifest["source_guard_before"] = source_guard_snapshot(Path(manifest["source_root"]))
    marker.write_text(json.dumps({"activated_at": manifest["updated_at"]}) + "\n", encoding="utf-8")
    _write_manifest(target / "repo", manifest, key)
    return {"capsule": str(target), "status": "active"}


def finish_capsule(
    capsule: Path | str,
    *,
    exit_code: int,
    capsule_root: Path | str = DEFAULT_CAPSULE_ROOT,
    key_path: Path | str | None = None,
) -> dict[str, Any]:
    root = _resolved(capsule_root)
    target, _, _ = _validate_capsule_layout(capsule, root)
    manifest, key = _read_manifest(target, root, key_path)
    marker = target / ACTIVE_MARKER_NAME
    if manifest.get("status") != "active" or not marker.is_file():
        raise CapsuleError("capsule is not active; refusing to finalize an unknown run")
    manifest.pop("signature", None)
    source_after = source_guard_snapshot(Path(manifest["source_root"]))
    unchanged = source_after == manifest.get("source_guard_before")
    manifest["source_guard_after"] = source_after
    manifest["source_guard_unchanged"] = unchanged
    manifest["runner_exit_code"] = int(exit_code)
    manifest["status"] = "completed" if int(exit_code) == 0 and unchanged else "failed"
    manifest["updated_at"] = _utc_now()
    _write_manifest(target / "repo", manifest, key)
    marker.unlink()
    if not unchanged:
        raise CapsuleError("source output guard changed during runtest; capsule retained and marked failed")
    return {"capsule": str(target), "status": manifest["status"], "source_guard_unchanged": True}


def delete_capsule(
    capsule: Path | str,
    *,
    capsule_root: Path | str = DEFAULT_CAPSULE_ROOT,
    key_path: Path | str | None = None,
) -> None:
    """Delete one completed/failed signed capsule, never an arbitrary directory."""
    root = _resolved(capsule_root)
    target, _, _ = _validate_capsule_layout(capsule, root)
    manifest, _ = _read_manifest(target, root, key_path)
    if manifest.get("status") == "active" or (target / ACTIVE_MARKER_NAME).exists():
        raise CapsuleError("refusing to delete an active capsule")
    if manifest.get("status") not in {"completed", "failed", "prepared"}:
        raise CapsuleError("refusing to delete capsule with unknown status")
    # The layout and signed identity have both been checked immediately before
    # this operation.  This is the only recursive deletion in the subsystem.
    # Local Git clones can inherit a read-only pack/index bit on Windows.
    def _clear_readonly_and_retry(function, path, exception) -> None:
        del exception
        os.chmod(path, stat.S_IWRITE)
        function(path)

    shutil.rmtree(target, onexc=_clear_readonly_and_retry)


def _parse_copy_inputs(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        label, separator, source = value.partition("=")
        if not separator or not label or not source or label in parsed:
            raise CapsuleError("--copy-input must be unique LABEL=PATH")
        parsed[label] = source
    return parsed


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or govern a disposable Stock runtest capsule")
    parser.add_argument("--capsule-root", default=str(DEFAULT_CAPSULE_ROOT))
    parser.add_argument("--key-path", default=None, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create")
    create.add_argument("--source-root", required=True)
    create.add_argument("--market", choices=sorted(MARKET_NAMES), required=True)
    create.add_argument("--run-id", required=True)
    create.add_argument("--commit", default="HEAD")
    create.add_argument("--copy-input", action="append", default=[], metavar="LABEL=PATH")

    for name in ("activate", "finish", "delete", "show"):
        command = commands.add_parser(name)
        command.add_argument("--capsule", required=True)
    commands.choices["finish"].add_argument("--exit-code", required=True, type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "create":
            _emit(
                create_capsule(
                    source_root=args.source_root,
                    capsule_root=args.capsule_root,
                    market=args.market,
                    run_id=args.run_id,
                    commit_ref=args.commit,
                    copy_inputs=_parse_copy_inputs(args.copy_input),
                    key_path=args.key_path,
                )
            )
        elif args.command == "activate":
            _emit(activate_capsule(args.capsule, capsule_root=args.capsule_root, key_path=args.key_path))
        elif args.command == "finish":
            _emit(
                finish_capsule(
                    args.capsule,
                    exit_code=args.exit_code,
                    capsule_root=args.capsule_root,
                    key_path=args.key_path,
                )
            )
        elif args.command == "delete":
            delete_capsule(args.capsule, capsule_root=args.capsule_root, key_path=args.key_path)
            _emit({"capsule": str(_resolved(args.capsule)), "deleted": True})
        else:  # show
            manifest, _ = _read_manifest(_resolved(args.capsule), _resolved(args.capsule_root), args.key_path)
            _emit(manifest)
    except CapsuleError as exc:
        print(f"[FATAL] runtest capsule: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
