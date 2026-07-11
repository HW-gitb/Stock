"""Immutable clock/source binding for US-short score projections."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_NAME = "us_short_score_projection_binding"
SCHEMA_VERSION = "2.0.0"
_COMPONENTS = frozenset({"momentum", "theme"})
_VALUE_KEYS = {"momentum": "momentum_by_ticker", "theme": "theme_block_by_ticker"}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def projection_payload_sha256(projection: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in projection.items() if key != "source_binding"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
    producer_id: str,
    generated_at: str,
    expected_decision_date: str,
    candidate_price_basis_date: str,
    source_as_of: str,
    target_tickers: list[str] | tuple[str, ...] | set[str],
    projection: Mapping[str, Any],
    source_artifact_paths: Mapping[str, Path],
    session: str = "RTH",
    adjustment_mode: str = "massive_grouped_daily",
) -> dict[str, Any]:
    if component not in _COMPONENTS:
        raise ValueError("projection binding component must be momentum or theme")
    if type(producer_id) is not str or not producer_id:
        raise ValueError("projection binding producer_id must be a non-empty exact string")
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
        "producer_id": producer_id,
        "generated_at": generated_at,
        "decision_clock": {
            "expected_decision_date": expected_decision_date,
            "candidate_price_basis_date": candidate_price_basis_date,
            "source_as_of": source_as_of,
        },
        "source_contract": {"session": session, "adjustment_mode": adjustment_mode},
        "target_tickers_sha256": ticker_partition_sha256(target_tickers),
        "projection_sha256": projection_payload_sha256(projection),
        "source_artifacts": artifacts,
    }
    _validate_shape(binding)
    _validate_clock_order(binding)
    return binding


def _validate_clock_order(binding: Mapping[str, Any]) -> None:
    generated = datetime.fromisoformat(str(binding["generated_at"]).replace("Z", "+00:00"))
    clock = binding["decision_clock"]
    source_date = datetime.strptime(clock["source_as_of"], "%Y-%m-%d").date()
    decision_open = datetime.strptime(clock["expected_decision_date"], "%Y%m%d").replace(
        hour=9, minute=30, tzinfo=ZoneInfo("America/New_York")
    )
    generated_et = generated.astimezone(ZoneInfo("America/New_York"))
    if generated_et.date() < source_date:
        raise ValueError("projection source_binding generated_at precedes source_as_of")
    if generated_et >= decision_open:
        raise ValueError("projection source_binding must be generated before decision-session open")


def _validate_shape(binding: Any) -> None:
    if type(binding) is not dict or set(binding) != {
        "schema_name", "schema_version", "component", "producer_id", "generated_at", "decision_clock",
        "source_contract", "target_tickers_sha256", "projection_sha256", "source_artifacts",
    }:
        raise ValueError("projection source_binding shape drifted")
    if binding["schema_name"] != SCHEMA_NAME or binding["schema_version"] != SCHEMA_VERSION:
        raise ValueError("projection source_binding schema identity drifted")
    if binding["component"] not in _COMPONENTS:
        raise ValueError("projection source_binding component is invalid")
    if type(binding["producer_id"]) is not str or not binding["producer_id"]:
        raise ValueError("projection source_binding producer_id is invalid")
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
    source_contract = binding["source_contract"]
    if type(source_contract) is not dict or set(source_contract) != {"session", "adjustment_mode"}:
        raise ValueError("projection source_binding source contract shape drifted")
    if not all(type(source_contract[key]) is str and source_contract[key] for key in source_contract):
        raise ValueError("projection source_binding source contract values are invalid")
    for field in ("target_tickers_sha256", "projection_sha256"):
        if type(binding[field]) is not str or len(binding[field]) != 64:
            raise ValueError(f"projection source_binding {field} must be sha256 hex")
        try:
            int(binding[field], 16)
        except ValueError as exc:
            raise ValueError(f"projection source_binding {field} must be sha256 hex") from exc
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
    expected_producer_id: str | None = None,
    expected_source_roles: tuple[str, ...] | None = None,
    expected_session: str = "RTH",
    expected_adjustment_mode: str = "massive_grouped_daily",
    allowed_dispositions: set[str] | frozenset[str] | None = None,
    scored_dispositions: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    if type(projection) is not dict:
        raise ValueError("projection must be an exact dict")
    binding = projection.get("source_binding")
    _validate_shape(binding)
    if binding["component"] != component:
        raise ValueError("projection source_binding component does not match the projection")
    if expected_producer_id is not None and binding["producer_id"] != expected_producer_id:
        raise ValueError("projection source_binding producer is not authorized for this stage")
    expected_clock = {
        "expected_decision_date": expected_decision_date,
        "candidate_price_basis_date": candidate_price_basis_date,
        "source_as_of": source_as_of,
    }
    if binding["decision_clock"] != expected_clock:
        raise ValueError("projection source_binding decision clock does not match the candidate artifact")
    _validate_clock_order(binding)
    if binding["source_contract"] != {
        "session": expected_session,
        "adjustment_mode": expected_adjustment_mode,
    }:
        raise ValueError("projection source_binding session/adjustment contract is not authorized")
    partition = target_tickers if target_tickers is not None else projection_partition_tickers(
        projection, component=component
    )
    if binding["target_tickers_sha256"] != ticker_partition_sha256(partition):
        raise ValueError("projection source_binding target partition hash does not match the projection")
    value_key = _VALUE_KEYS[component]
    if set(projection) != {
        value_key, "neutral_fill_tickers", "coverage", "target_count", "scored_count", "source_binding"
    }:
        raise ValueError("projection keys drifted from the exact bound contract")
    values = projection[value_key]
    neutral = projection["neutral_fill_tickers"]
    coverage = projection["coverage"]
    if type(values) is not dict or type(neutral) is not list or type(coverage) is not dict:
        raise ValueError("projection bound payload containers are invalid")
    if any(type(ticker) is not str for ticker in neutral) or len(neutral) != len(set(neutral)):
        raise ValueError("projection neutral_fill_tickers must be unique exact strings")
    if any(type(ticker) is not str for ticker in coverage):
        raise ValueError("projection coverage keys must be exact strings")
    if any(type(value) is not str or not value for value in coverage.values()):
        raise ValueError("projection coverage dispositions must be non-empty exact strings")
    if any(
        type(ticker) is not str
        or isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or not 0.0 <= float(score) <= 100.0
        for ticker, score in values.items()
    ):
        raise ValueError("projection bound scores must be finite numbers in [0,100]")
    if type(projection["target_count"]) is not int or isinstance(projection["target_count"], bool):
        raise ValueError("projection target_count must be an exact int")
    if type(projection["scored_count"]) is not int or isinstance(projection["scored_count"], bool):
        raise ValueError("projection scored_count must be an exact int")
    if set(coverage) != set(values) | set(neutral) or set(values) & set(neutral):
        raise ValueError("projection score/neutral/coverage partition is inconsistent")
    if projection["target_count"] != len(coverage) or projection["scored_count"] != len(values):
        raise ValueError("projection target/scored counts are inconsistent")
    if allowed_dispositions is not None and any(value not in allowed_dispositions for value in coverage.values()):
        raise ValueError("projection coverage disposition is not authorized")
    if scored_dispositions is not None:
        if any(coverage[ticker] not in scored_dispositions for ticker in values):
            raise ValueError("projection scored row has a non-scored disposition")
        if any(coverage[ticker] in scored_dispositions for ticker in neutral):
            raise ValueError("projection neutral row has a scored disposition")
    if binding["projection_sha256"] != projection_payload_sha256(projection):
        raise ValueError("projection source_binding payload digest does not match the projection")
    roles = tuple(artifact["role"] for artifact in binding["source_artifacts"])
    if expected_source_roles is not None and roles != expected_source_roles:
        raise ValueError("projection source artifact roles are not authorized for this stage")
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
