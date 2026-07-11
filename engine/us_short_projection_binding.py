"""Immutable clock/source binding for US-short score projections."""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_NAME = "us_short_score_projection_binding"
SCHEMA_VERSION = "1.0.0"
_COMPONENTS = frozenset({"momentum", "theme"})
_VALUE_KEYS = {"momentum": "momentum_by_ticker", "theme": "theme_block_by_ticker"}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ticker_partition_sha256(tickers: list[str] | tuple[str, ...] | set[str]) -> str:
    canonical = sorted(tickers)
    if any(type(ticker) is not str or not ticker for ticker in canonical) or len(canonical) != len(set(canonical)):
        raise ValueError("projection binding tickers must be unique non-empty exact strings")
    return hashlib.sha256(("\n".join(canonical) + "\n").encode("utf-8")).hexdigest()


def _repo_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("projection binding source artifact must stay inside the repository") from exc


def build_projection_binding(
    *,
    component: str,
    generated_at: str,
    expected_decision_date: str,
    candidate_price_basis_date: str,
    source_as_of: str,
    target_tickers: list[str] | tuple[str, ...] | set[str],
    source_artifact_paths: Mapping[str, Path],
) -> dict[str, Any]:
    if component not in _COMPONENTS:
        raise ValueError("projection binding component must be momentum or theme")
    artifacts = []
    for role, path in sorted(source_artifact_paths.items()):
        resolved = Path(path).resolve()
        if type(role) is not str or not role or not resolved.is_file():
            raise ValueError("projection binding source artifacts must be named existing files")
        artifacts.append({"role": role, "path": _repo_rel(resolved), "sha256": file_sha256(resolved)})
    if not artifacts:
        raise ValueError("projection binding requires at least one source artifact")
    binding = {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "component": component,
        "generated_at": generated_at,
        "decision_clock": {
            "expected_decision_date": expected_decision_date,
            "candidate_price_basis_date": candidate_price_basis_date,
            "source_as_of": source_as_of,
        },
        "target_tickers_sha256": ticker_partition_sha256(target_tickers),
        "source_artifacts": artifacts,
    }
    _validate_shape(binding)
    return binding


def _validate_shape(binding: Any) -> None:
    if type(binding) is not dict or set(binding) != {
        "schema_name", "schema_version", "component", "generated_at", "decision_clock",
        "target_tickers_sha256", "source_artifacts",
    }:
        raise ValueError("projection source_binding shape drifted")
    if binding["schema_name"] != SCHEMA_NAME or binding["schema_version"] != SCHEMA_VERSION:
        raise ValueError("projection source_binding schema identity drifted")
    if binding["component"] not in _COMPONENTS:
        raise ValueError("projection source_binding component is invalid")
    try:
        observed = datetime.fromisoformat(
            binding["generated_at"][:-1] + "+00:00"
            if binding["generated_at"].endswith("Z") else binding["generated_at"]
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("projection source_binding generated_at must be RFC3339") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("projection source_binding generated_at must be timezone-aware")
    clock = binding["decision_clock"]
    if type(clock) is not dict or set(clock) != {
        "expected_decision_date", "candidate_price_basis_date", "source_as_of"
    }:
        raise ValueError("projection source_binding decision_clock shape drifted")
    if not (type(clock["expected_decision_date"]) is str and len(clock["expected_decision_date"]) == 8
            and clock["expected_decision_date"].isascii() and clock["expected_decision_date"].isdigit()):
        raise ValueError("projection source_binding expected_decision_date must be YYYYMMDD")
    if not (type(clock["candidate_price_basis_date"]) is str and len(clock["candidate_price_basis_date"]) == 8
            and clock["candidate_price_basis_date"].isascii() and clock["candidate_price_basis_date"].isdigit()):
        raise ValueError("projection source_binding candidate_price_basis_date must be YYYYMMDD")
    try:
        datetime.strptime(clock["source_as_of"], "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError("projection source_binding source_as_of must be YYYY-MM-DD") from exc
    if type(binding["target_tickers_sha256"]) is not str or len(binding["target_tickers_sha256"]) != 64:
        raise ValueError("projection source_binding target_tickers_sha256 must be sha256 hex")
    try:
        int(binding["target_tickers_sha256"], 16)
    except ValueError as exc:
        raise ValueError("projection source_binding target_tickers_sha256 must be sha256 hex") from exc
    artifacts = binding["source_artifacts"]
    if type(artifacts) is not list or not artifacts:
        raise ValueError("projection source_binding requires source_artifacts")
    roles: set[str] = set()
    for artifact in artifacts:
        if type(artifact) is not dict or set(artifact) != {"role", "path", "sha256"}:
            raise ValueError("projection source artifact shape drifted")
        role, path, digest = artifact["role"], artifact["path"], artifact["sha256"]
        if type(role) is not str or not role or role in roles or type(path) is not str or not path:
            raise ValueError("projection source artifact role/path is invalid")
        roles.add(role)
        if type(digest) is not str or len(digest) != 64:
            raise ValueError("projection source artifact sha256 is invalid")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ValueError("projection source artifact sha256 is invalid") from exc


def projection_partition_tickers(projection: Any, *, component: str) -> list[str]:
    if type(projection) is not dict or component not in _VALUE_KEYS:
        raise ValueError("projection binding cannot derive the component partition")
    values = projection.get(_VALUE_KEYS[component])
    neutral = projection.get("neutral_fill_tickers")
    if type(values) is not dict or type(neutral) is not list:
        raise ValueError("projection binding cannot derive the component partition")
    tickers = list(values) + list(neutral)
    if any(type(ticker) is not str for ticker in tickers) or len(tickers) != len(set(tickers)):
        raise ValueError("projection component partition contains invalid or duplicate tickers")
    return tickers


def validate_projection_binding(
    projection: Any,
    *,
    component: str,
    expected_decision_date: str,
    candidate_price_basis_date: str,
    source_as_of: str,
    target_tickers: list[str] | tuple[str, ...] | set[str] | None = None,
    verify_source_artifacts: bool = True,
) -> dict[str, Any]:
    if type(projection) is not dict:
        raise ValueError("projection must be an exact dict")
    binding = projection.get("source_binding")
    _validate_shape(binding)
    if binding["component"] != component:
        raise ValueError("projection source_binding component does not match the projection")
    expected_clock = {
        "expected_decision_date": expected_decision_date,
        "candidate_price_basis_date": candidate_price_basis_date,
        "source_as_of": source_as_of,
    }
    if binding["decision_clock"] != expected_clock:
        raise ValueError("projection source_binding decision clock does not match the candidate artifact")
    partition = target_tickers if target_tickers is not None else projection_partition_tickers(
        projection, component=component
    )
    if binding["target_tickers_sha256"] != ticker_partition_sha256(partition):
        raise ValueError("projection source_binding target partition hash does not match the projection")
    if verify_source_artifacts:
        for artifact in binding["source_artifacts"]:
            resolved = (ROOT / artifact["path"]).resolve()
            try:
                resolved.relative_to(ROOT.resolve())
            except ValueError as exc:
                raise ValueError("projection source artifact path escapes the repository") from exc
            if not resolved.is_file() or file_sha256(resolved) != artifact["sha256"]:
                raise ValueError(f"projection source artifact hash mismatch: {artifact['role']}")
    return binding
