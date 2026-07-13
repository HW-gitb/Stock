"""Source-bound checkpoint bundles for the resumable US-short weekly capstone."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
from typing import Any

from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "us_short_weekly_capstone_checkpoint_manifest.schema.json"


class CapstoneCheckpointError(ValueError):
    pass


def _guard_private(path: Path) -> None:
    try:
        reject_nonprivate_output_path(path)
    except PrivatePathError as exc:
        raise CapstoneCheckpointError("checkpoint destination is not provably private") from exc


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate(manifest: Any) -> dict[str, Any]:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise CapstoneCheckpointError("jsonschema is required for capstone checkpoint validation") from exc
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CapstoneCheckpointError("cannot read capstone checkpoint schema") from exc
    errors = sorted(Draft7Validator(schema).iter_errors(manifest), key=lambda error: list(error.path))
    if errors:
        raise CapstoneCheckpointError(
            "capstone checkpoint failed schema validation: " + "; ".join(error.message for error in errors[:5])
        )
    names = [row["name"] for row in manifest["pipeline_contract"]]
    stage_names = [row["name"] for row in manifest["stages"]]
    if len(set(names)) != len(names) or len(set(stage_names)) != len(stage_names):
        raise CapstoneCheckpointError("capstone checkpoint stage names must be unique")
    if any(name not in names for name in stage_names):
        raise CapstoneCheckpointError("capstone checkpoint contains a stage outside its pipeline contract")
    return manifest


def pipeline_contract(stages) -> list[dict[str, str]]:
    return [
        {
            "name": stage.name,
            "contract_version": stage.contract_version,
            "reuse_policy": stage.reuse_policy,
        }
        for stage in stages
    ]


def _prune_superseded_decision_checkpoints(private_root: Path, current_decision_date: str) -> None:
    """Retention: a checkpoint bundle is only resumable for its own decision week (`validate_resume_header` binds the
    decision date — you cannot resume a past week), so bundle trees under an OLDER `capstone_checkpoints_private/
    <YYYYMMDD>/` directory are dead weight. Remove them on each new run so the private checkpoint store does not grow
    unboundedly across weeks. Bounded + private + fail-soft: only 8-digit-date directories strictly older than the
    current one, under the same fail-closed private root, are removed, and any prune error is swallowed (retention
    must never abort a run)."""
    base = (Path(private_root) / "capstone_checkpoints_private").resolve()
    if not base.is_dir():
        return
    for child in list(base.iterdir()):
        try:
            if not (child.is_dir() and len(child.name) == 8 and child.name.isdigit()
                    and child.name < current_decision_date):
                continue
            _guard_private(child)
            shutil.rmtree(child)
        except (OSError, CapstoneCheckpointError):
            continue


def create_manifest(
    *, private_root: Path, decision_date: str, price_basis_date: str, generated_at: str, run_contract: dict[str, Any],
    stages,
) -> tuple[Path, dict[str, Any]]:
    checkpoint_id = hashlib.sha256(
        f"{decision_date}|{generated_at}|{uuid.uuid4().hex}".encode("utf-8")
    ).hexdigest()
    manifest_path = (
        Path(private_root) / "capstone_checkpoints_private" / decision_date / checkpoint_id / "checkpoint_manifest.json"
    ).resolve()
    manifest = {
        "schema_name": "us_short_weekly_capstone_checkpoint_manifest",
        "schema_version": "1.0.0",
        "checkpoint_id": checkpoint_id,
        "decision_date": decision_date,
        "price_basis_date": price_basis_date,
        "created_at": generated_at,
        "updated_at": generated_at,
        "run_contract": deepcopy(run_contract),
        "pipeline_contract": pipeline_contract(stages),
        "stages": [],
    }
    _write_manifest(manifest_path, manifest)
    _prune_superseded_decision_checkpoints(Path(private_root), decision_date)
    return manifest_path, manifest


def load_manifest(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CapstoneCheckpointError("cannot read resume checkpoint manifest") from exc
    _validate(manifest)
    expected_parent = path.parent
    if expected_parent.name != manifest["checkpoint_id"]:
        raise CapstoneCheckpointError("checkpoint path does not match checkpoint_id")
    return manifest


def validate_resume_header(
    manifest: dict[str, Any], *, decision_date: str, price_basis_date: str, run_contract: dict[str, Any], stages,
) -> None:
    _validate(manifest)
    if manifest["decision_date"] != decision_date or manifest["price_basis_date"] != price_basis_date:
        raise CapstoneCheckpointError("resume checkpoint decision/price clock differs from this run")
    if manifest["run_contract"] != run_contract:
        raise CapstoneCheckpointError("resume checkpoint non-file run contract differs from this run")
    current_contract = pipeline_contract(stages)
    if manifest["pipeline_contract"] != current_contract:
        raise CapstoneCheckpointError("resume checkpoint pipeline contract differs from this runner")


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    _validate(manifest)
    _guard_private(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    _guard_private(tmp)
    tmp.write_bytes(_json_bytes(manifest) + b"\n")
    os.replace(tmp, path)


def _logical_manifest(paths: list[Path], logical_paths: list[str]) -> list[dict[str, str]]:
    if len(paths) != len(logical_paths):
        raise CapstoneCheckpointError("checkpoint path/logical-path counts differ")
    rows = []
    for path, logical in zip(paths, logical_paths):
        if not Path(path).is_file():
            raise CapstoneCheckpointError(f"checkpoint artifact is missing: {logical}")
        rows.append({"logical_path": logical, "sha256": _sha256_file(Path(path))})
    return rows


def record_stage(
    *, manifest_path: Path, manifest: dict[str, Any], stage, execution_mode: str,
    generated_at: str, observed_at: str | None, input_paths: list[Path], input_logical_paths: list[str],
    output_paths: list[Path], output_logical_paths: list[str], result: dict[str, Any],
) -> dict[str, Any]:
    if execution_mode not in {"executed", "reused", "refreshed_equivalent"}:
        raise CapstoneCheckpointError("checkpoint execution_mode is invalid")
    input_manifest = _logical_manifest(input_paths, input_logical_paths)
    if len(output_paths) != len(output_logical_paths):
        raise CapstoneCheckpointError("checkpoint output/logical-path counts differ")
    bundle_root = Path(manifest_path).resolve().parent
    output_manifest = []
    for index, (source, logical) in enumerate(zip(output_paths, output_logical_paths), start=1):
        source = Path(source)
        if not source.is_file():
            raise CapstoneCheckpointError(f"cannot checkpoint missing stage output: {logical}")
        safe_name = source.name.replace("..", "_")
        relative = Path("artifacts") / stage.name / f"{index:02d}_{safe_name}"
        destination = bundle_root / relative
        _guard_private(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = destination.with_suffix(destination.suffix + ".tmp")
        _guard_private(tmp)
        shutil.copyfile(source, tmp)
        os.replace(tmp, destination)
        digest = _sha256_file(source)
        if _sha256_file(destination) != digest:
            raise CapstoneCheckpointError("checkpoint bundle copy digest mismatch")
        output_manifest.append({
            "logical_path": logical,
            "bundle_path": relative.as_posix(),
            "sha256": digest,
        })
    row = {
        "name": stage.name,
        "contract_version": stage.contract_version,
        "reuse_policy": stage.reuse_policy,
        "execution_mode": execution_mode,
        "generated_at": generated_at,
        "observed_at": observed_at,
        "input_manifest": input_manifest,
        "output_manifest": output_manifest,
        "result": deepcopy(result),
        "result_sha256": hashlib.sha256(_json_bytes(result)).hexdigest(),
    }
    updated = deepcopy(manifest)
    updated["stages"] = [existing for existing in updated["stages"] if existing["name"] != stage.name]
    updated["stages"].append(row)
    order = {contract["name"]: index for index, contract in enumerate(updated["pipeline_contract"])}
    updated["stages"].sort(key=lambda item: order[item["name"]])
    updated["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_manifest(Path(manifest_path), updated)
    return updated


def _without_observation_clocks(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_observation_clocks(item)
            for key, item in value.items()
            if key not in {"generated_at", "observed_at"}
        }
    if isinstance(value, list):
        return [_without_observation_clocks(item) for item in value]
    return value


def refresh_output_from_equivalent_checkpoint(
    *, source_manifest_path: Path, source_manifest: dict[str, Any], stage,
    output_paths: list[Path], output_logical_paths: list[str],
) -> bool:
    """After a volatile refresh, reuse the old bound artifact only when all non-clock facts are identical."""
    if stage.reuse_policy != "refresh_then_reuse_if_equivalent":
        return False
    if len(output_paths) != len(output_logical_paths):
        raise CapstoneCheckpointError("checkpoint output/logical-path counts differ")
    row = next((item for item in source_manifest["stages"] if item["name"] == stage.name), None)
    if row is None or row["contract_version"] != stage.contract_version \
            or row["reuse_policy"] != stage.reuse_policy:
        return False
    if [item["logical_path"] for item in row["output_manifest"]] != output_logical_paths:
        return False
    bundle_root = Path(source_manifest_path).resolve().parent
    pairs: list[tuple[Path, Path, str]] = []
    for stored, current in zip(row["output_manifest"], output_paths):
        bundled = (bundle_root / stored["bundle_path"]).resolve()
        if bundle_root not in bundled.parents or not bundled.is_file():
            raise CapstoneCheckpointError(f"checkpoint bundle artifact missing for stage {stage.name}")
        if _sha256_file(bundled) != stored["sha256"]:
            raise CapstoneCheckpointError(f"checkpoint bundle artifact digest mismatch for stage {stage.name}")
        try:
            old_value = json.loads(bundled.read_text(encoding="utf-8"))
            new_value = json.loads(Path(current).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if _without_observation_clocks(old_value) != _without_observation_clocks(new_value):
            return False
        pairs.append((bundled, Path(current), stored["sha256"]))
    for bundled, destination, digest in pairs:
        tmp = destination.with_suffix(destination.suffix + ".resume.tmp")
        shutil.copyfile(bundled, tmp)
        os.replace(tmp, destination)
        if _sha256_file(destination) != digest:
            raise CapstoneCheckpointError(f"refreshed-equivalent artifact digest mismatch for stage {stage.name}")
    return True


def restore_stage(
    *, source_manifest_path: Path, source_manifest: dict[str, Any], stage,
    input_paths: list[Path], input_logical_paths: list[str], output_paths: list[Path], output_logical_paths: list[str],
) -> tuple[dict[str, Any], str, str | None] | None:
    if stage.reuse_policy != "frozen_inputs":
        return None
    if len(output_paths) != len(output_logical_paths):
        raise CapstoneCheckpointError("checkpoint output/logical-path counts differ")
    row = next((item for item in source_manifest["stages"] if item["name"] == stage.name), None)
    if row is None:
        return None
    if row["contract_version"] != stage.contract_version or row["reuse_policy"] != stage.reuse_policy:
        return None
    current_inputs = _logical_manifest(input_paths, input_logical_paths)
    if current_inputs != row["input_manifest"]:
        return None
    if [item["logical_path"] for item in row["output_manifest"]] != output_logical_paths:
        return None
    if hashlib.sha256(_json_bytes(row["result"])).hexdigest() != row["result_sha256"]:
        raise CapstoneCheckpointError(f"checkpoint result digest mismatch for stage {stage.name}")
    bundle_root = Path(source_manifest_path).resolve().parent
    for stored, destination in zip(row["output_manifest"], output_paths):
        bundled = (bundle_root / stored["bundle_path"]).resolve()
        if bundle_root not in bundled.parents or not bundled.is_file():
            raise CapstoneCheckpointError(f"checkpoint bundle artifact missing for stage {stage.name}")
        if _sha256_file(bundled) != stored["sha256"]:
            raise CapstoneCheckpointError(f"checkpoint bundle artifact digest mismatch for stage {stage.name}")
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = destination.with_suffix(destination.suffix + ".resume.tmp")
        shutil.copyfile(bundled, tmp)
        os.replace(tmp, destination)
        if _sha256_file(destination) != stored["sha256"]:
            raise CapstoneCheckpointError(f"restored artifact digest mismatch for stage {stage.name}")
    return deepcopy(row["result"]), row["generated_at"], row["observed_at"]
