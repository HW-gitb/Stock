"""A-short weekly revision identity and official-selection boundary.

V5-A deliberately keeps this module small.  It owns only the opaque revision
identity, the three sanctioned revision roots, the final immutable manifest,
and the de-identified official pointer/selection receipt.  Business payloads
remain in their existing producers; this module never parses or rewrites them.
"""
from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Mapping

import jsonschema

from engine.a_short_artifact_set_transaction import commit_artifact_set


ROOT = Path(__file__).resolve().parents[1]
REVISION_MANIFEST_SCHEMA = ROOT / "schemas" / "a_short_run_revision_manifest.schema.json"
OFFICIAL_REVISION_SCHEMA = ROOT / "schemas" / "a_short_official_revision.schema.json"
PHASE4_REPORTS_SCHEMA = ROOT / "schemas" / "a_short_phase4_reports_manifest.schema.json"
_DATE8_RE = re.compile(r"^[0-9]{8}$")
_REVISION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RevisionError(ValueError):
    """A malformed or conflicting revision boundary."""


class RevisionIdentityConflict(RevisionError):
    """The same revision id was reused with different bytes or identity."""


class RevisionSelectionBlocked(RevisionError):
    """An official switch is forbidden after a formal clock or cutoff."""


def new_run_revision_id() -> str:
    """Generate the only accepted physical-run primary key."""
    return uuid.uuid4().hex


def validate_run_revision_id(value: str) -> str:
    value = str(value or "")
    if not _REVISION_ID_RE.fullmatch(value):
        raise RevisionError("run_revision_id must be exactly 32 lowercase hexadecimal characters")
    return value


def validate_decision_as_of(value: str) -> str:
    value = str(value or "")
    if not _DATE8_RE.fullmatch(value):
        raise RevisionError("decision_as_of must be YYYYMMDD")
    try:
        _datetime.datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise RevisionError("decision_as_of is not a calendar date") from exc
    return value


def resolve_revision_root(root: str | Path, decision_as_of: str, run_revision_id: str) -> Path:
    """Resolve ``<root>/<decision_as_of>/revisions/<run_revision_id>``."""
    base = Path(root).resolve()
    date = validate_decision_as_of(decision_as_of)
    revision = validate_run_revision_id(run_revision_id)
    return base / date / "revisions" / revision


def public_revision_root(project_root: str | Path, decision_as_of: str, run_revision_id: str) -> Path:
    return resolve_revision_root(Path(project_root) / "result" / "a_short", decision_as_of, run_revision_id)


def research_revision_root(project_root: str | Path, decision_as_of: str, run_revision_id: str) -> Path:
    return resolve_revision_root(Path(project_root) / "research" / "results" / "a_short", decision_as_of, run_revision_id)


def private_revision_root(private_root: str | Path, decision_as_of: str, run_revision_id: str) -> Path:
    """Resolve the private weekly root without exposing account contents."""
    base = Path(private_root).resolve()
    date = validate_decision_as_of(decision_as_of)
    revision = validate_run_revision_id(run_revision_id)
    return base / "weeks" / date / "revisions" / revision


def private_week_root(
    private_root: str | Path,
    decision_as_of: str,
    run_revision_id: str | None = None,
) -> Path:
    """Resolve one private weekly evidence directory.

    A new writer must pass ``run_revision_id`` and therefore lands below the
    immutable ``weeks/<decision>/revisions/<id>`` boundary.  Omitting the id is
    retained only for legacy readers/fixtures; it never guesses a revision.
    """
    if run_revision_id is None:
        base = Path(private_root).resolve()
        return base / "weeks" / validate_decision_as_of(decision_as_of)
    return private_revision_root(private_root, decision_as_of, run_revision_id)


def iter_private_week_roots(
    private_root: str | Path,
) -> list[tuple[str, str | None, Path]]:
    """List legacy and revision-scoped private weeks in deterministic order.

    The returned tuple is ``(decision_as_of, run_revision_id, path)``.  This is
    an explicit reader boundary: it never uses directory mtime or "latest"
    selection, and callers can apply the official resolver before counting.
    """
    root = Path(private_root).resolve() / "weeks"
    if not root.exists():
        return []
    result: list[tuple[str, str | None, Path]] = []
    for day in sorted((p for p in root.iterdir() if p.is_dir() and _DATE8_RE.fullmatch(p.name)), key=lambda p: p.name):
        legacy = day / "capture.json"
        if legacy.exists() or not (day / "revisions").exists():
            result.append((day.name, None, day))
        revisions = day / "revisions"
        if revisions.is_dir():
            for revision in sorted((p for p in revisions.iterdir() if p.is_dir()), key=lambda p: p.name):
                validate_run_revision_id(revision.name)
                result.append((day.name, revision.name, revision))
    return result


def canonical_json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def phase4_reports_manifest_path(
    project_root: str | Path, decision_as_of: str, run_revision_id: str,
) -> Path:
    """Return the registered index for reports inside one public revision.

    The report bytes stay below ``result/.../revisions/<id>/reports``.  The
    index is the only selector-managed date-root convenience artifact; it
    gives legacy readers a deterministic pointer without allowing the selector
    to scan or overwrite old date-only report files.
    """
    return public_revision_root(project_root, decision_as_of, run_revision_id) / "phase4_reports_manifest.json"


def _phase4_reports_content_digest(payload: Mapping[str, object]) -> str:
    basis = {
        "decision_as_of": payload.get("decision_as_of"),
        "run_revision_id": payload.get("run_revision_id"),
        "reports_root": payload.get("reports_root"),
        "files": payload.get("files"),
    }
    return sha256_bytes(canonical_json_bytes(basis))


def build_phase4_reports_manifest(
    *, project_root: str | Path, decision_as_of: str, run_revision_id: str,
) -> dict:
    """Index deterministic Phase-4 files without reading date-root legacy data."""
    date = validate_decision_as_of(decision_as_of)
    revision = validate_run_revision_id(run_revision_id)
    revision_root = public_revision_root(project_root, date, revision)
    reports_root = revision_root / "reports"
    files: list[dict[str, object]] = []
    if reports_root.exists():
        if not reports_root.is_dir():
            raise RevisionError("phase4 reports path is not a directory")
        for path in sorted(reports_root.rglob("*"), key=lambda item: item.as_posix()):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(revision_root).as_posix()
            files.append({
                "relative_path": relative,
                "sha256": sha256_file(path),
                "byte_length": path.stat().st_size,
            })
    payload = {
        "schema_name": "a_short_phase4_reports_manifest",
        "schema_version": "1.0.0",
        "decision_as_of": date,
        "run_revision_id": revision,
        "reports_root": "reports",
        "file_count": len(files),
        "files": files,
    }
    payload["content_digest"] = _phase4_reports_content_digest(payload)
    _validate_schema(payload, PHASE4_REPORTS_SCHEMA)
    return payload


def write_phase4_reports_manifest(
    project_root: str | Path, decision_as_of: str, run_revision_id: str,
) -> str:
    """Write the report index idempotently, failing on same-id drift."""
    date = validate_decision_as_of(decision_as_of)
    revision = validate_run_revision_id(run_revision_id)
    target = phase4_reports_manifest_path(project_root, decision_as_of, run_revision_id)
    payload = build_phase4_reports_manifest(
        project_root=project_root, decision_as_of=decision_as_of,
        run_revision_id=run_revision_id,
    )
    resolved_target = target.resolve()
    if (
        resolved_target.name != "phase4_reports_manifest.json"
        or resolved_target.parent.name != revision
        or resolved_target.parent.parent.name != "revisions"
        or resolved_target.parent.parent.parent.name != date
    ):
        raise RevisionError("phase4 reports manifest is outside its date/revision directory")
    encoded = canonical_json_bytes(payload)
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RevisionIdentityConflict("existing phase4 reports manifest is unreadable") from exc
        _validate_schema(existing, PHASE4_REPORTS_SCHEMA)
        if existing != payload:
            raise RevisionIdentityConflict("same run_revision_id was reused with changed Phase-4 reports")
        return "already_current"
    _atomic_write(target, encoded)
    return "written"


def _validate_schema(payload: dict, schema_path: Path) -> None:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(payload, schema)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError,
            jsonschema.ValidationError, jsonschema.SchemaError) as exc:
        raise RevisionError(f"revision contract validation failed: {type(exc).__name__}") from exc


def _role_reference(role: str, path: Path, project_root: Path) -> str:
    """Return a public relative identifier without exposing private roots."""
    try:
        relative = path.resolve().relative_to(project_root.resolve())
    except ValueError:
        # A configured private root may intentionally live outside the repo.
        # The manifest carries its digest but never copies that absolute path.
        return f"private://{role}/{path.name}"
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise RevisionError("revision manifest role path is not a safe relative path")
    if relative.parts and (relative.parts[0] == "state" or "private" in relative.parts):
        return f"private://{role}/{path.name}"
    return relative.as_posix()


def _validate_manifest_location(path: Path, manifest: Mapping[str, object]) -> None:
    """Keep the final manifest inside its immutable date/revision directory."""
    revision = str(manifest.get("run_revision_id") or "")
    decision = str(manifest.get("decision_as_of") or "")
    if (
        path.name != "revision_manifest.json"
        or path.parent.name != revision
        or path.parent.parent.name != "revisions"
        or path.parent.parent.parent.name != decision
    ):
        raise RevisionError("revision manifest is outside its date/revision directory")


def build_revision_manifest(
    *,
    project_root: str | Path,
    manifest_path: str | Path,
    decision_as_of: str,
    run_date: str | None,
    price_data_through: str,
    run_revision_id: str,
    run_id: str,
    candidate_digest: str,
    roles: Mapping[str, str | Path],
    expected_roles: list[str] | tuple[str, ...] | None = None,
) -> dict:
    """Build a de-identified manifest from already-validated role files."""
    date = validate_decision_as_of(decision_as_of)
    revision = validate_run_revision_id(run_revision_id)
    price = validate_decision_as_of(price_data_through)
    if price > date:
        raise RevisionError("price_data_through is after decision_as_of")
    if run_date not in (None, ""):
        validate_decision_as_of(str(run_date))
    if not isinstance(run_id, str) or not run_id.strip():
        raise RevisionError("run_id is required")
    if not isinstance(candidate_digest, str) or not _SHA256_RE.fullmatch(candidate_digest):
        raise RevisionError("candidate_digest must be a lowercase SHA-256 digest")
    if not isinstance(roles, Mapping) or not roles:
        raise RevisionError("revision manifest requires at least one role file")
    normalised_roles = {str(name): Path(path) for name, path in roles.items()}
    if any(not re.fullmatch(r"[a-z0-9_]+", name) for name in normalised_roles):
        raise RevisionError("revision role names must be lowercase snake_case")
    expected = sorted(set(expected_roles or normalised_roles))
    if sorted(normalised_roles) != expected:
        raise RevisionError("revision manifest role set is incomplete or contains unexpected roles")
    root = Path(project_root).resolve()
    role_payload = {}
    for name in expected:
        path = normalised_roles[name]
        if not path.is_file():
            raise RevisionError(f"revision role file missing: {name}")
        role_payload[name] = {
            "relative_path": _role_reference(name, path, root),
            "sha256": sha256_file(path),
            "byte_length": path.stat().st_size,
        }
    manifest = {
        "schema_name": "a_short_run_revision_manifest",
        "schema_version": "1.0.0",
        "decision_as_of": date,
        "run_date": run_date if run_date not in (None, "") else None,
        "price_data_through": price,
        "run_revision_id": revision,
        "run_id": run_id,
        "candidate_digest": candidate_digest,
        "stage_status": "complete",
        "structural_completeness": {
            "expected_role_count": len(expected),
            "observed_role_count": len(role_payload),
            "all_expected_roles_present": True,
        },
        "roles": role_payload,
    }
    manifest["content_digest"] = _manifest_content_digest(manifest)
    _validate_schema(manifest, REVISION_MANIFEST_SCHEMA)
    _validate_manifest_location(Path(manifest_path).resolve(), manifest)
    return manifest


def _manifest_content_digest(manifest: dict) -> str:
    """Digest payload identity while ignoring revision-specific paths/ids."""
    roles = {
        name: {"sha256": value["sha256"], "byte_length": value["byte_length"]}
        for name, value in sorted((manifest.get("roles") or {}).items())
    }
    basis = {
        "decision_as_of": manifest.get("decision_as_of"),
        "run_date": manifest.get("run_date"),
        "price_data_through": manifest.get("price_data_through"),
        "run_id": manifest.get("run_id"),
        "candidate_digest": manifest.get("candidate_digest"),
        "stage_status": manifest.get("stage_status"),
        "roles": roles,
    }
    return sha256_bytes(canonical_json_bytes(basis))


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def write_revision_manifest(path: str | Path, manifest: dict) -> str:
    """Write the final manifest last; identical replays never rewrite bytes."""
    target = Path(path)
    _validate_schema(manifest, REVISION_MANIFEST_SCHEMA)
    _validate_manifest_location(target.resolve(), manifest)
    payload = (json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RevisionIdentityConflict("existing revision manifest is unreadable") from exc
        _validate_schema(existing, REVISION_MANIFEST_SCHEMA)
        if existing != manifest:
            raise RevisionIdentityConflict("same run_revision_id was reused with changed manifest identity")
        return "already_current"
    _atomic_write(target, payload)
    return "written"


def read_revision_manifest(path: str | Path, *, verify_roles: bool = True) -> dict:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RevisionError("revision manifest is unreadable") from exc
    _validate_schema(payload, REVISION_MANIFEST_SCHEMA)
    _validate_manifest_location(target.resolve(), payload)
    if verify_roles:
        root = None
        for ancestor in target.parents:
            if ancestor.name in {"research", "result"}:
                root = ancestor.parent
                break
        # A revision manifest normally lives under the repository's research or
        # public result root.  If a caller stores it elsewhere, identity reads
        # remain valid but role-byte verification is intentionally unavailable.
        if root is not None:
            for role in payload["roles"].values():
                if str(role["relative_path"]).startswith("private://"):
                    continue
                role_path = root / Path(role["relative_path"])
                if not role_path.is_file() or sha256_file(role_path) != role["sha256"]:
                    raise RevisionError("revision manifest role bytes no longer match")
    return payload


def _load_official(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RevisionError("official revision pointer is unreadable") from exc
    _validate_schema(payload, OFFICIAL_REVISION_SCHEMA)
    return payload


def read_official_revision(path: str | Path) -> dict | None:
    return _load_official(Path(path))


def official_revision_pointer_path(project_root: str | Path, decision_as_of: str) -> Path:
    """Return the sole date-root official pointer for one decision date."""
    root = Path(project_root).resolve()
    date = validate_decision_as_of(decision_as_of)
    return root / "research" / "results" / "a_short" / date / "official_revision.json"


def official_current_view_root(project_root: str | Path, decision_as_of: str) -> Path:
    """Return the date-root public compatibility view for one decision date.

    New readers must resolve :func:`official_revision_pointer_path` first.  The
    date-root view is only a materialized convenience for existing report
    readers and is never itself an authority.
    """
    root = Path(project_root).resolve()
    return root / "result" / "a_short" / validate_decision_as_of(decision_as_of)


def _project_root_from_manifest(manifest_path: Path) -> Path | None:
    """Infer a repository root without relying on cwd or directory ordering."""
    for ancestor in manifest_path.resolve().parents:
        if ancestor.name == "research":
            return ancestor.parent
    return None


def _official_current_view_payloads(
    project_root: Path, decision_as_of: str, run_revision_id: str,
    manifest: Mapping[str, object],
) -> dict[Path, bytes]:
    """Build public date-root files from the selected revision only.

    Private/research roles are deliberately skipped.  The function validates
    that every copied role is physically below the selected public revision
    root, so a manifest cannot smuggle a private or unrelated file into the
    public compatibility view.
    """
    selected_root = public_revision_root(project_root, decision_as_of, run_revision_id).resolve()
    current_root = official_current_view_root(project_root, decision_as_of)
    payloads: dict[Path, bytes] = {}
    for role in (manifest.get("roles") or {}).values():
        if not isinstance(role, Mapping):
            continue
        relative = str(role.get("relative_path") or "")
        if not relative or relative.startswith("private://"):
            continue
        source = (project_root / Path(relative)).resolve()
        try:
            destination_relative = source.relative_to(selected_root)
        except ValueError:
            # Research roles and other public-but-not-date-view artifacts are
            # still bound by the manifest, but are not copied to legacy view.
            continue
        if not source.is_file():
            raise RevisionError("selected revision public role is missing")
        destination = (current_root / destination_relative).resolve()
        try:
            destination.relative_to(current_root.resolve())
        except ValueError as exc:
            raise RevisionError("official current view escaped its date root") from exc
        payloads[destination] = source.read_bytes()
    return payloads


def _revision_manifest_path(project_root: Path, decision_as_of: str,
                            run_revision_id: str) -> Path:
    """Resolve a selected revision manifest without scanning or guessing.

    The launcher writes the manifest in the research revision root.  The
    public candidate fixture is accepted as a compatibility location for
    hermetic callers, but directory ordering and mtime are never consulted.
    """
    candidates = (
        research_revision_root(project_root, decision_as_of, run_revision_id) / "revision_manifest.json",
        public_revision_root(project_root, decision_as_of, run_revision_id) / "revision_manifest.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RevisionError("selected official revision manifest is missing")


def _official_current_view_payloads_for_revision(
    project_root: Path, decision_as_of: str, run_revision_id: str,
) -> dict[Path, bytes]:
    """Return only the files that selector previously materialised for a revision."""
    manifest_path = _revision_manifest_path(project_root, decision_as_of, run_revision_id)
    manifest = read_revision_manifest(manifest_path, verify_roles=False)
    if (manifest.get("decision_as_of") != decision_as_of or
            manifest.get("run_revision_id") != run_revision_id):
        raise RevisionError("selected official revision manifest identity does not match pointer")
    return _official_current_view_payloads(project_root, decision_as_of, run_revision_id, manifest)


def _official_current_view_deletions(
    current_root: Path, payloads: Mapping[Path, bytes],
    managed_paths: Mapping[Path, bytes] | set[Path] | tuple[Path, ...] = (),
) -> list[Path]:
    """Return stale files from the selector-managed compatibility view only.

    Legacy date-root files are read-only compatibility artifacts.  They are
    not discoverable by scanning the directory, so a first official selection
    must never delete them.  On a switch, ``managed_paths`` is the exact set
    materialised by the previous official manifest; only those paths may be
    removed when the new selected payload no longer contains them.
    """
    if not current_root.is_dir():
        return []
    selected = {Path(path).resolve() for path in payloads}
    previous = managed_paths.keys() if isinstance(managed_paths, Mapping) else managed_paths
    stale: list[Path] = []
    current_root_resolved = current_root.resolve()
    for raw_path in previous:
        path = Path(raw_path).resolve()
        try:
            path.relative_to(current_root_resolved)
        except ValueError as exc:
            raise RevisionError("managed official current-view path escaped its date root") from exc
        if path in selected or not path.is_file():
            continue
        if isinstance(managed_paths, Mapping):
            try:
                if path.read_bytes() != managed_paths[raw_path]:
                    # A date-root compatibility user changed this file after
                    # the prior official materialisation; it is legacy now.
                    continue
            except (OSError, KeyError):
                continue
        stale.append(path)
    return stale


def _official_current_view_writes(
    current_root: Path, payloads: Mapping[Path, bytes],
    managed_paths: Mapping[Path, bytes] | set[Path] | tuple[Path, ...] = (),
) -> dict[Path, bytes]:
    """Avoid overwriting an unmanaged legacy date-root file on first selection."""
    if not current_root.is_dir():
        return dict(payloads)
    managed = managed_paths if isinstance(managed_paths, Mapping) else {}
    writes: dict[Path, bytes] = {}
    for raw_path, payload in payloads.items():
        path = Path(raw_path).resolve()
        if not path.is_file():
            writes[path] = payload
            continue
        if path in managed:
            try:
                if path.read_bytes() == managed[path]:
                    writes[path] = payload
            except OSError:
                pass
        # Existing files absent from the previous official materialisation are
        # legacy compatibility artifacts and remain byte-for-byte untouched.
    return writes


def resolve_official_revision(
    project_root: str | Path,
    decision_as_of: str,
    *,
    expected_revision_id: str | None = None,
    require: bool = False,
) -> dict | None:
    """Resolve the selected revision without directory-order or mtime guessing.

    A missing pointer is retained as a legacy/read-only compatibility result
    unless ``require`` is true.  When a pointer exists, an expected revision
    must match it exactly; a validation-only or stale revision therefore
    cannot enter a formal consumer by merely passing its own id.
    """
    date = validate_decision_as_of(decision_as_of)
    expected = validate_run_revision_id(expected_revision_id) if expected_revision_id is not None else None
    pointer_path = official_revision_pointer_path(project_root, date)
    selected = read_official_revision(pointer_path)
    if selected is None:
        if require:
            raise RevisionSelectionBlocked("official revision pointer is missing")
        return None
    if selected.get("decision_as_of") != date:
        raise RevisionError("official revision pointer date does not match requested decision_as_of")
    selected_id = validate_run_revision_id(str(selected.get("selected_revision_id") or ""))
    if expected is not None and selected_id != expected:
        raise RevisionSelectionBlocked("requested revision is not the selected official revision")
    return selected


def require_official_revision(
    project_root: str | Path,
    decision_as_of: str,
    expected_revision_id: str,
) -> str:
    """Return the selected id or fail closed before formal counting."""
    selected = resolve_official_revision(
        project_root, decision_as_of,
        expected_revision_id=expected_revision_id, require=True,
    )
    assert selected is not None  # ``require=True`` above makes this invariant.
    return str(selected["selected_revision_id"])


def official_public_revision_root(
    project_root: str | Path,
    decision_as_of: str,
    run_revision_id: str | None = None,
) -> Path:
    """Resolve the public EGS root through an id or the official pointer.

    A missing pointer is the only case that may fall back to the legacy
    date-root reader. Once a pointer exists, consumers use its validated
    revision id rather than guessing by mtime or directory order.
    """
    root = Path(project_root).resolve()
    date = validate_decision_as_of(decision_as_of)
    if run_revision_id is not None:
        return public_revision_root(root, date, run_revision_id)
    pointer = official_revision_pointer_path(root, date)
    selected = read_official_revision(pointer)
    if selected is None:
        return root / "result" / "a_short" / date
    if selected.get("decision_as_of") != date:
        raise RevisionError("official revision pointer date does not match requested decision_as_of")
    return public_revision_root(root, date, selected["selected_revision_id"])


def official_analysis_input_path(
    project_root: str | Path,
    decision_as_of: str,
    run_revision_id: str | None = None,
) -> Path:
    """Return analysis_input through the official resolver, with legacy read-only fallback."""
    return official_public_revision_root(project_root, decision_as_of, run_revision_id) / "analysis_input.json"


def _selection_payload(*, schema_name: str, decision_as_of: str, revision: str,
                       manifest_digest: str, content_digest: str, supersedes: str | None, reason: str,
                       status: str) -> dict:
    payload = {
        "schema_name": schema_name,
        "schema_version": "1.0.0",
        "decision_as_of": decision_as_of,
        "selected_revision_id": revision,
        "selected_manifest_sha256": manifest_digest,
        "selected_content_digest": content_digest,
        "selection_status": status,
        "reason": reason,
        "supersedes_revision_id": supersedes,
    }
    _validate_schema(payload, OFFICIAL_REVISION_SCHEMA)
    return payload


def select_official_revision(
    *,
    pointer_path: str | Path,
    selection_receipt_path: str | Path,
    manifest_path: str | Path,
    transaction_dir: str | Path,
    run_revision_id: str,
    decision_as_of: str,
    reason: str = "normal_weekly",
    formal_state_committed: bool = False,
    cutoff_passed: bool = False,
    project_root: str | Path | None = None,
) -> dict:
    """Select one complete revision through the existing rollback boundary."""
    revision = validate_run_revision_id(run_revision_id)
    date = validate_decision_as_of(decision_as_of)
    manifest = read_revision_manifest(manifest_path, verify_roles=False)
    if manifest["run_revision_id"] != revision or manifest["decision_as_of"] != date:
        raise RevisionError("revision selection identity does not match manifest")
    manifest_digest = sha256_file(manifest_path)
    content_digest = manifest["content_digest"]
    pointer = Path(pointer_path)
    receipt = Path(selection_receipt_path)
    inferred_root = Path(project_root).resolve() if project_root is not None else _project_root_from_manifest(Path(manifest_path))
    current = _load_official(pointer)
    previous_view: dict[Path, bytes] = {}
    if current is not None:
        current_revision = current["selected_revision_id"]
        current_digest = current["selected_manifest_sha256"]
        if current_revision == revision:
            if current_digest != manifest_digest or current.get("selected_content_digest") != content_digest:
                raise RevisionIdentityConflict("selected revision manifest digest changed")
            # A prior process may have committed the pointer before a crash
            # interrupted legacy-view materialisation.  Rebuild only from the
            # already-selected manifest; never select a different revision.
            if inferred_root is not None:
                view = _official_current_view_payloads(inferred_root, date, revision, manifest)
                current_root = official_current_view_root(inferred_root, date)
                stale = _official_current_view_deletions(current_root, view, view)
                writes = _official_current_view_writes(current_root, view, view)
                if writes or stale:
                    commit_artifact_set(transaction_dir, writes, delete_paths=stale)
            return {"status": "already_current", "selected_revision_id": revision}
        if current.get("selected_content_digest") == content_digest:
            return {"status": "equivalent_replay", "selected_revision_id": current_revision}
        if formal_state_committed:
            raise RevisionSelectionBlocked("official revision switch is forbidden after formal settlement/ratchet state")
        if cutoff_passed:
            raise RevisionSelectionBlocked("official revision switch is forbidden after the weekly cutoff")
        supersedes = current_revision
        if inferred_root is not None:
            # Only paths previously materialised by the selected official are
            # eligible for cleanup.  Arbitrary date-root legacy artifacts are
            # intentionally not scanned or deleted.
            previous_view = _official_current_view_payloads_for_revision(
                inferred_root, date, current_revision
            )
    else:
        if formal_state_committed:
            raise RevisionSelectionBlocked("official revision selection is forbidden after formal settlement/ratchet state")
        if cutoff_passed:
            raise RevisionSelectionBlocked("official revision selection is forbidden after the weekly cutoff")
        supersedes = None
    pointer_payload = _selection_payload(
        schema_name="a_short_official_revision", decision_as_of=date, revision=revision,
        manifest_digest=manifest_digest, content_digest=content_digest,
        supersedes=supersedes, reason=reason,
        status="selected",
    )
    receipt_payload = _selection_payload(
        schema_name="a_short_official_selection_receipt", decision_as_of=date, revision=revision,
        manifest_digest=manifest_digest, content_digest=content_digest,
        supersedes=supersedes, reason=reason,
        status="selected",
    )
    current_view = (
        _official_current_view_payloads(inferred_root, date, revision, manifest)
        if inferred_root is not None else {}
    )
    current_view_root = official_current_view_root(inferred_root, date) if inferred_root is not None else None
    current_view_deletions = (
        _official_current_view_deletions(current_view_root, current_view, previous_view)
        if current_view_root is not None else []
    )
    current_view_writes = (
        _official_current_view_writes(current_view_root, current_view, previous_view)
        if current_view_root is not None else current_view
    )
    commit_files = {
        pointer: (json.dumps(pointer_payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"),
        receipt: (json.dumps(receipt_payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"),
    }
    commit_files.update(current_view_writes)
    commit_artifact_set(
        transaction_dir,
        commit_files,
        delete_paths=current_view_deletions,
    )
    return {"status": "selected", "selected_revision_id": revision, "supersedes_revision_id": supersedes}


def _parse_roles(values: list[str]) -> dict[str, str]:
    roles = {}
    for value in values:
        name, separator, path = value.partition("=")
        if not separator or not name or not path:
            raise RevisionError("--role must be ROLE=PATH")
        if name in roles:
            raise RevisionError(f"duplicate revision role: {name}")
        roles[name] = path
    return roles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A-short V5-A revision boundary")
    sub = parser.add_subparsers(dest="command", required=True)
    writer = sub.add_parser("write-manifest")
    writer.add_argument("--project-root", required=True)
    writer.add_argument("--manifest", required=True)
    writer.add_argument("--decision-as-of", required=True)
    writer.add_argument("--run-date")
    writer.add_argument("--price-data-through", required=True)
    writer.add_argument("--run-revision-id", required=True)
    writer.add_argument("--run-id", required=True)
    writer.add_argument("--candidate-digest", required=True)
    writer.add_argument("--role", action="append", required=True)
    selector = sub.add_parser("select-official")
    selector.add_argument("--pointer", required=True)
    selector.add_argument("--selection-receipt", required=True)
    selector.add_argument("--manifest", required=True)
    selector.add_argument("--transaction-dir", required=True)
    selector.add_argument("--run-revision-id", required=True)
    selector.add_argument("--decision-as-of", required=True)
    selector.add_argument("--reason", default="normal_weekly")
    selector.add_argument("--formal-state-committed", action="store_true")
    selector.add_argument("--cutoff-passed", action="store_true")
    reports = sub.add_parser("write-reports-index")
    reports.add_argument("--project-root", required=True)
    reports.add_argument("--decision-as-of", required=True)
    reports.add_argument("--run-revision-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "write-manifest":
        roles = _parse_roles(args.role)
        manifest = build_revision_manifest(
            project_root=args.project_root, manifest_path=args.manifest,
            decision_as_of=args.decision_as_of, run_date=args.run_date,
            price_data_through=args.price_data_through, run_revision_id=args.run_revision_id,
            run_id=args.run_id, candidate_digest=args.candidate_digest, roles=roles,
        )
        status = write_revision_manifest(args.manifest, manifest)
    elif args.command == "select-official":
        status = select_official_revision(
            pointer_path=args.pointer, selection_receipt_path=args.selection_receipt,
            manifest_path=args.manifest, transaction_dir=args.transaction_dir,
            run_revision_id=args.run_revision_id, decision_as_of=args.decision_as_of,
            reason=args.reason, formal_state_committed=args.formal_state_committed,
            cutoff_passed=args.cutoff_passed,
        )["status"]
    else:
        status = write_phase4_reports_manifest(
            args.project_root, args.decision_as_of, args.run_revision_id,
        )
    print(json.dumps({"status": status}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
