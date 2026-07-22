# -*- coding: utf-8 -*-
"""Private transactional store for the US-short model-paper portfolio.

The store is intentionally independent from the weekly capstone. It freezes a
decision, permits a digest-linked same-day supersession only while that decision
is pending, and publishes settlement/state/NAV before atomically advancing
``head_manifest.json``. A crash can leave an unreferenced complete or partial
week, but can never make the head point at missing/mixed artifacts; an identical
retry completes the publish.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import uuid

from jsonschema import Draft7Validator

from engine.us_short_model_paper_portfolio import (
    ModelPaperPortfolioError,
    artifact_sha256,
    build_nav_snapshot,
    canonical_json_bytes,
    validate_decision_bundle,
    validate_nav_snapshot,
    validate_portfolio_state,
    validate_settlement,
)
from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path


ROOT = Path(__file__).resolve().parent.parent
HEAD_SCHEMA_PATH = ROOT / "schemas" / "us_short_model_paper_head_manifest.schema.json"
_HEAD_SCHEMA = json.loads(HEAD_SCHEMA_PATH.read_text(encoding="utf-8"))
Draft7Validator.check_schema(_HEAD_SCHEMA)
_HEAD_VALIDATOR = Draft7Validator(_HEAD_SCHEMA)

STORE_BOUNDARY = {
    "private_store_only": True,
    "manual_account_isolated": True,
    "automatic_broker_execution": False,
    "provider_fetch": False,
    "ship_gate_eligible": False,
}


class ModelPaperStoreError(RuntimeError):
    """Raised when privacy, lineage, immutability, or transactional checks fail."""


def _wrap_portfolio_error(label: str, func, value: dict) -> None:
    try:
        func(value)
    except ModelPaperPortfolioError as exc:
        raise ModelPaperStoreError(f"{label} invalid: {exc}") from exc


def _guard(path: Path) -> None:
    try:
        reject_nonprivate_output_path(path)
    except PrivatePathError as exc:
        raise ModelPaperStoreError(f"private path guard rejected {path}: {exc}") from exc


def _store_root(root: str | Path) -> Path:
    path = Path(root)
    if not path.is_absolute():
        raise ModelPaperStoreError("model-paper store root must be absolute")
    path = path.resolve()
    _guard(path)
    if path.exists():
        for candidate in path.rglob(".*.tmp-*"):
            resolved = candidate.resolve()
            try:
                resolved.relative_to(path)
            except ValueError as exc:
                raise ModelPaperStoreError("temporary artifact escapes the private store root") from exc
            _guard(resolved)
            if resolved.is_dir():
                raise ModelPaperStoreError(f"unexpected temporary directory in private store: {resolved}")
            try:
                resolved.unlink()
            except OSError as exc:
                raise ModelPaperStoreError(f"cannot clean stale private-store temporary artifact: {resolved}") from exc
    return path


def _validate_head(head: dict) -> None:
    errors = sorted(_HEAD_VALIDATOR.iter_errors(head), key=lambda item: list(item.absolute_path))
    if errors:
        error = errors[0]
        path = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise ModelPaperStoreError(f"head manifest schema violation at {path}: {error.message}")


def _resolve_relative(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ModelPaperStoreError("manifest relative path escapes the private store root") from exc
    _guard(candidate)
    return candidate


def _replace_path(source: Path, destination: Path) -> None:
    """Single monkeypatch seam used by crash-recovery tests."""
    os.replace(source, destination)


def _atomic_write(path: Path, value: dict) -> None:
    _guard(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    _guard(temp)
    payload = canonical_json_bytes(value)
    try:
        with temp.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_path(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _read_json_bytes(path: Path) -> tuple[dict, bytes]:
    _guard(path)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ModelPaperStoreError(f"cannot read private store artifact {path}: {exc}") from exc
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelPaperStoreError(f"private store artifact is not canonical UTF-8 JSON: {path}") from exc
    try:
        canonical = canonical_json_bytes(value)
    except ModelPaperPortfolioError as exc:
        raise ModelPaperStoreError(f"private store artifact is not canonical JSON: {path}") from exc
    if canonical != payload:
        raise ModelPaperStoreError(f"private store artifact is not byte-canonical: {path}")
    return value, payload


def _read_digest(path: Path) -> tuple[dict, str]:
    value, payload = _read_json_bytes(path)
    return value, hashlib.sha256(payload).hexdigest()


def _publish_immutable(path: Path, value: dict) -> None:
    digest = artifact_sha256(value)
    if path.exists():
        _existing, existing_digest = _read_digest(path)
        if existing_digest != digest:
            raise ModelPaperStoreError(f"immutable artifact conflict at {path}")
        return
    _atomic_write(path, value)


def _head_path(root: Path) -> Path:
    return root / "head_manifest.json"


def _ref(relative_path: str, value: dict) -> dict:
    return {"relative_path": relative_path, "sha256": artifact_sha256(value)}


def _state_ref(relative_path: str, state: dict) -> dict:
    result = _ref(relative_path, state)
    result["as_of"] = state["as_of"]
    result["last_settled_decision_date"] = state["last_settled_decision_date"]
    return result


def _load_ref(root: Path, reference: dict) -> dict:
    path = _resolve_relative(root, reference["relative_path"])
    value, digest = _read_digest(path)
    if digest != reference["sha256"]:
        raise ModelPaperStoreError(f"digest mismatch for {reference['relative_path']}")
    return value


def load_head(root: str | Path) -> dict:
    store_root = _store_root(root)
    path = _head_path(store_root)
    if not path.is_file():
        raise ModelPaperStoreError("model-paper store is not initialized")
    head, _digest = _read_digest(path)
    _validate_head(head)
    seed_state = _load_ref(store_root, head["seed_state"])
    current_state = _load_ref(store_root, head["current_state"])
    current_nav = _load_ref(store_root, head["current_nav"])
    _wrap_portfolio_error("seed state", validate_portfolio_state, seed_state)
    _wrap_portfolio_error("current state", validate_portfolio_state, current_state)
    _wrap_portfolio_error("current NAV", validate_nav_snapshot, current_nav)
    if current_nav["state_sha256"] != head["current_state"]["sha256"]:
        raise ModelPaperStoreError("head current NAV does not bind current state")
    try:
        expected_nav = build_nav_snapshot(
            current_state,
            {
                "paper_evaluable": current_nav["paper_evaluable"],
                "status": "evaluable" if current_nav["paper_evaluable"] else "not_evaluable",
                "degradation_reasons": current_nav["degradation_reasons"],
                "source_sha256": current_nav["evaluation_source_sha256"],
            },
        )
    except ModelPaperPortfolioError as exc:
        raise ModelPaperStoreError("head current NAV cannot be derived from current state") from exc
    if expected_nav != current_nav:
        raise ModelPaperStoreError("head current NAV is not derivable from current state")
    if current_state["as_of"] != head["current_state"]["as_of"] or current_state["last_settled_decision_date"] != head["current_state"]["last_settled_decision_date"]:
        raise ModelPaperStoreError("head current state metadata is inconsistent")
    last = head["last_settlement"]
    if last is None:
        if head["current_state"]["sha256"] != head["seed_state"]["sha256"]:
            raise ModelPaperStoreError("unsettled head must still point at seed state")
    else:
        if head["current_state"]["sha256"] != last["state_sha256"] or head["current_nav"]["sha256"] != last["nav_sha256"]:
            raise ModelPaperStoreError("last settlement does not bind current state/NAV")
        paths = _week_paths(store_root, last["decision_date"])
        decision, decision_digest = _read_digest(paths["decision"])
        settlement, settlement_digest = _read_digest(paths["settlement"])
        if decision_digest != last["decision_sha256"] or settlement_digest != last["settlement_sha256"]:
            raise ModelPaperStoreError("last settlement decision/settlement digest mismatch")
        _wrap_portfolio_error("last decision", validate_decision_bundle, decision)
        _wrap_portfolio_error("last settlement", validate_settlement, settlement)
        if settlement["price_packet_sha256"] != last["price_packet_sha256"]:
            raise ModelPaperStoreError("last settlement price packet digest mismatch")
        if settlement["decision_bundle_sha256"] != last["decision_sha256"] or settlement["post_state_sha256"] != last["state_sha256"] or settlement["nav_snapshot_sha256"] != last["nav_sha256"]:
            raise ModelPaperStoreError("last settlement cross-artifact binding mismatch")
    return head


def load_current_state(root: str | Path) -> dict:
    store_root = _store_root(root)
    head = load_head(store_root)
    state = _load_ref(store_root, head["current_state"])
    _wrap_portfolio_error("current portfolio state", validate_portfolio_state, state)
    reference = head["current_state"]
    if state["as_of"] != reference["as_of"] or state["last_settled_decision_date"] != reference["last_settled_decision_date"]:
        raise ModelPaperStoreError("current state metadata contradicts head manifest")
    return state


def load_current_nav(root: str | Path) -> dict:
    """Load the head-bound diagnostic NAV without exposing store internals to callers."""
    store_root = _store_root(root)
    head = load_head(store_root)
    nav = _load_ref(store_root, head["current_nav"])
    _wrap_portfolio_error("current NAV", validate_nav_snapshot, nav)
    if nav["state_sha256"] != head["current_state"]["sha256"]:
        raise ModelPaperStoreError("current NAV does not bind current state")
    return nav


def load_pending_decision(root: str | Path) -> dict | None:
    """Load the one immutable pending decision, if any, with its head digest rechecked."""
    store_root = _store_root(root)
    head = load_head(store_root)
    pending = head["pending_decision"]
    if pending is None:
        return None
    decision, digest = _read_digest(_resolve_relative(store_root, pending["relative_path"]))
    if digest != pending["sha256"]:
        raise ModelPaperStoreError("pending decision digest mismatch")
    _wrap_portfolio_error("pending decision", validate_decision_bundle, decision)
    return decision


def initialize_store(root: str | Path, seed_state: dict, seed_nav: dict) -> str:
    store_root = _store_root(root)
    _wrap_portfolio_error("seed state", validate_portfolio_state, seed_state)
    _wrap_portfolio_error("seed NAV", validate_nav_snapshot, seed_nav)
    if seed_state["last_settled_decision_date"] is not None or seed_state["positions"]:
        raise ModelPaperStoreError("initial seed must have no settled decision and no positions")
    if seed_nav["state_sha256"] != artifact_sha256(seed_state):
        raise ModelPaperStoreError("seed NAV does not bind seed state")

    seed_state_rel = "seed/portfolio_state.json"
    seed_nav_rel = "seed/nav_snapshot.json"
    seed_state_path = _resolve_relative(store_root, seed_state_rel)
    seed_nav_path = _resolve_relative(store_root, seed_nav_rel)
    head_path = _head_path(store_root)
    _guard(head_path)
    if head_path.exists():
        head = load_head(store_root)
        if head["seed_state"]["sha256"] != artifact_sha256(seed_state):
            raise ModelPaperStoreError("store already initialized with a different seed")
        _load_ref(store_root, head["seed_state"])
        return "idempotent"

    try:
        _publish_immutable(seed_state_path, seed_state)
        _publish_immutable(seed_nav_path, seed_nav)
        head = {
            "schema_name": "us_short_model_paper_head_manifest",
            "schema_version": "1.0.0",
            "seed_state": _ref(seed_state_rel, seed_state),
            "current_state": _state_ref(seed_state_rel, seed_state),
            "current_nav": _ref(seed_nav_rel, seed_nav),
            "pending_decision": None,
            "last_settlement": None,
            "boundary": copy.deepcopy(STORE_BOUNDARY),
        }
        _validate_head(head)
        _atomic_write(head_path, head)
    except (OSError, ModelPaperPortfolioError, ModelPaperStoreError) as exc:
        if isinstance(exc, ModelPaperStoreError):
            raise
        raise ModelPaperStoreError(f"store initialization failed: {exc}") from exc
    return "initialized"


def _week_paths(root: Path, decision_date: str) -> dict[str, Path]:
    base = _resolve_relative(root, f"weeks/{decision_date}/decision_bundle.json").parent
    result = {
        "decision": base / "decision_bundle.json",
        "settlement": base / "settlement.json",
        "state": base / "portfolio_state.json",
        "nav": base / "nav_snapshot.json",
    }
    for path in result.values():
        _guard(path)
    return result


def _pending_ref(decision: dict) -> dict:
    return {
        "decision_date": decision["decision_date"],
        "relative_path": f"weeks/{decision['decision_date']}/decision_bundle.json",
        "sha256": artifact_sha256(decision),
        "supersedes_sha256": decision["supersedes_sha256"],
    }


def _head_with_pending(head: dict, decision: dict) -> dict:
    updated = copy.deepcopy(head)
    updated["pending_decision"] = _pending_ref(decision)
    _validate_head(updated)
    return updated


def freeze_decision_bundle(root: str | Path, decision_bundle: dict) -> str:
    store_root = _store_root(root)
    _wrap_portfolio_error("decision bundle", validate_decision_bundle, decision_bundle)
    head = load_head(store_root)
    date = decision_bundle["decision_date"]
    paths = _week_paths(store_root, date)
    digest = artifact_sha256(decision_bundle)
    last = head["last_settlement"]
    if last is not None and last["decision_date"] == date:
        if paths["decision"].is_file():
            _stored, stored_digest = _read_digest(paths["decision"])
            if stored_digest == digest:
                return "idempotent"
        raise ModelPaperStoreError("matured decision is immutable")

    current_state = _load_ref(store_root, head["current_state"])
    _wrap_portfolio_error("current state", validate_portfolio_state, current_state)
    if decision_bundle["prior_state_sha256"] != head["current_state"]["sha256"]:
        raise ModelPaperStoreError("decision prior_state_sha256 does not match store head")
    if decision_bundle["price_basis_date"] != current_state["as_of"]:
        raise ModelPaperStoreError("decision price_basis_date does not match current state")

    pending = head["pending_decision"]
    if pending is not None and pending["decision_date"] != date:
        raise ModelPaperStoreError("another decision is pending and must settle first")

    if pending is None:
        if decision_bundle["supersedes_sha256"] is not None:
            raise ModelPaperStoreError("first frozen decision cannot claim supersession")
        if paths["decision"].exists():
            _stored, stored_digest = _read_digest(paths["decision"])
            if stored_digest != digest:
                raise ModelPaperStoreError("orphan decision conflicts with requested freeze")
            status = "recovered"
        else:
            _atomic_write(paths["decision"], decision_bundle)
            status = "frozen"
        _atomic_write(_head_path(store_root), _head_with_pending(head, decision_bundle))
        return status

    if not paths["decision"].is_file():
        raise ModelPaperStoreError("head references a missing pending decision")
    _stored, disk_digest = _read_digest(paths["decision"])
    if disk_digest != pending["sha256"]:
        if digest == disk_digest and decision_bundle["supersedes_sha256"] == pending["sha256"]:
            if any(paths[key].exists() for key in ("settlement", "state", "nav")):
                raise ModelPaperStoreError("cannot recover supersession after settlement publish began")
            _atomic_write(_head_path(store_root), _head_with_pending(head, decision_bundle))
            return "recovered"
        raise ModelPaperStoreError("pending decision digest contradicts head manifest")
    if digest == pending["sha256"]:
        return "idempotent"
    if decision_bundle["supersedes_sha256"] != pending["sha256"]:
        raise ModelPaperStoreError("same-day replacement must bind supersedes_sha256 to pending digest")
    if any(paths[key].exists() for key in ("settlement", "state", "nav")):
        raise ModelPaperStoreError("cannot supersede after settlement publish began")
    _atomic_write(paths["decision"], decision_bundle)
    _atomic_write(_head_path(store_root), _head_with_pending(head, decision_bundle))
    return "superseded"


def _validate_commit_bundle(decision: dict, settlement: dict, state: dict, nav: dict) -> None:
    _wrap_portfolio_error("decision bundle", validate_decision_bundle, decision)
    _wrap_portfolio_error("settlement", validate_settlement, settlement)
    _wrap_portfolio_error("portfolio state", validate_portfolio_state, state)
    _wrap_portfolio_error("NAV snapshot", validate_nav_snapshot, nav)
    if settlement["decision_bundle_sha256"] != artifact_sha256(decision):
        raise ModelPaperStoreError("settlement does not bind decision bundle")
    if settlement["post_state_sha256"] != artifact_sha256(state):
        raise ModelPaperStoreError("settlement does not bind post state")
    if settlement["nav_snapshot_sha256"] != artifact_sha256(nav):
        raise ModelPaperStoreError("settlement does not bind NAV snapshot")
    if nav["state_sha256"] != artifact_sha256(state):
        raise ModelPaperStoreError("NAV snapshot does not bind post state")
    if state["last_settled_decision_date"] != decision["decision_date"] or settlement["decision_date"] != decision["decision_date"]:
        raise ModelPaperStoreError("decision date linkage is inconsistent")
    if state["as_of"] != nav["as_of"] or state["as_of"] != settlement["maturity_as_of"]:
        raise ModelPaperStoreError("maturity/as_of linkage is inconsistent")
    expected_orders = [(row["ticker"], row["final_action"]) for row in decision["orders"]]
    actual_outcomes = [(row["ticker"], row["final_action"]) for row in settlement["order_outcomes"]]
    if actual_outcomes != expected_orders:
        raise ModelPaperStoreError("settlement outcomes do not exactly cover decision orders")


def _verify_committed_files(root: Path, date: str, settlement: dict, state: dict, nav: dict) -> None:
    paths = _week_paths(root, date)
    for key, expected in (("settlement", settlement), ("state", state), ("nav", nav)):
        if not paths[key].is_file():
            raise ModelPaperStoreError(f"committed head references missing {key}")
        _stored, digest = _read_digest(paths[key])
        if digest != artifact_sha256(expected):
            raise ModelPaperStoreError(f"committed {key} digest mismatch")


def commit_settlement(root: str | Path, decision_bundle: dict, settlement: dict, state: dict, nav: dict) -> str:
    store_root = _store_root(root)
    _validate_commit_bundle(decision_bundle, settlement, state, nav)
    head = load_head(store_root)
    date = decision_bundle["decision_date"]
    paths = _week_paths(store_root, date)
    digests = {
        "settlement": artifact_sha256(settlement),
        "state": artifact_sha256(state),
        "nav": artifact_sha256(nav),
    }
    last = head["last_settlement"]
    if last is not None and last["decision_date"] == date:
        expected_last = {
            "decision_date": date,
            "decision_sha256": artifact_sha256(decision_bundle),
            "price_packet_sha256": settlement["price_packet_sha256"],
            "settlement_sha256": digests["settlement"],
            "state_sha256": digests["state"],
            "nav_sha256": digests["nav"],
        }
        if last != expected_last:
            raise ModelPaperStoreError("matured settlement is immutable")
        _verify_committed_files(store_root, date, settlement, state, nav)
        return "idempotent"

    pending = head["pending_decision"]
    if pending is None or pending["decision_date"] != date or pending["sha256"] != artifact_sha256(decision_bundle):
        raise ModelPaperStoreError("settlement requires the exact pending frozen decision")
    if settlement["prior_state_sha256"] != head["current_state"]["sha256"]:
        raise ModelPaperStoreError("settlement prior state does not match store head")
    stored_decision, stored_digest = _read_digest(paths["decision"])
    if stored_digest != pending["sha256"] or stored_decision != decision_bundle:
        raise ModelPaperStoreError("pending decision file does not match head")

    try:
        _publish_immutable(paths["settlement"], settlement)
        _publish_immutable(paths["state"], state)
        _publish_immutable(paths["nav"], nav)
    except (OSError, ModelPaperPortfolioError, ModelPaperStoreError) as exc:
        raise ModelPaperStoreError(f"transaction publish failed: {exc}") from exc

    updated = copy.deepcopy(head)
    updated["current_state"] = _state_ref(f"weeks/{date}/portfolio_state.json", state)
    updated["current_nav"] = _ref(f"weeks/{date}/nav_snapshot.json", nav)
    updated["pending_decision"] = None
    updated["last_settlement"] = {
        "decision_date": date,
        "decision_sha256": artifact_sha256(decision_bundle),
        "price_packet_sha256": settlement["price_packet_sha256"],
        "settlement_sha256": digests["settlement"],
        "state_sha256": digests["state"],
        "nav_sha256": digests["nav"],
    }
    _validate_head(updated)
    try:
        _atomic_write(_head_path(store_root), updated)
    except (OSError, ModelPaperPortfolioError, ModelPaperStoreError) as exc:
        raise ModelPaperStoreError(
            f"head publish failed after immutable artifacts; identical retry will recover: {exc}"
        ) from exc
    return "committed"


def commit_settlement_and_freeze_next(
    root: str | Path,
    decision_bundle: dict,
    settlement: dict,
    state: dict,
    nav: dict,
    next_decision_bundle: dict,
) -> str:
    """Atomically advance a matured week and publish the next pending decision in one head update.

    The immutable artifacts may be written before the head.  Until the final head write they are unreachable,
    so a capstone failure cannot expose a settled old week without its already-derived current decision.
    An identical retry after a failed head write is safe because all artifact paths are digest-immutable.
    """
    store_root = _store_root(root)
    _validate_commit_bundle(decision_bundle, settlement, state, nav)
    _wrap_portfolio_error("next decision bundle", validate_decision_bundle, next_decision_bundle)
    if next_decision_bundle["prior_state_sha256"] != artifact_sha256(state):
        raise ModelPaperStoreError("next decision prior_state_sha256 does not bind matured state")
    if next_decision_bundle["price_basis_date"] != state["as_of"]:
        raise ModelPaperStoreError("next decision price_basis_date does not bind matured state")
    if next_decision_bundle["decision_date"] <= decision_bundle["decision_date"]:
        raise ModelPaperStoreError("next decision date must follow the matured decision")

    head = load_head(store_root)
    pending = head["pending_decision"]
    if pending is None or pending["decision_date"] != decision_bundle["decision_date"] \
            or pending["sha256"] != artifact_sha256(decision_bundle):
        raise ModelPaperStoreError("combined commit requires the exact pending matured decision")
    if settlement["prior_state_sha256"] != head["current_state"]["sha256"]:
        raise ModelPaperStoreError("combined commit prior state does not match store head")

    settled_paths = _week_paths(store_root, decision_bundle["decision_date"])
    next_paths = _week_paths(store_root, next_decision_bundle["decision_date"])
    stored_decision, stored_digest = _read_digest(settled_paths["decision"])
    if stored_digest != pending["sha256"] or stored_decision != decision_bundle:
        raise ModelPaperStoreError("pending decision file does not match head")

    try:
        _publish_immutable(settled_paths["settlement"], settlement)
        _publish_immutable(settled_paths["state"], state)
        _publish_immutable(settled_paths["nav"], nav)
        _publish_immutable(next_paths["decision"], next_decision_bundle)
    except (OSError, ModelPaperPortfolioError, ModelPaperStoreError) as exc:
        raise ModelPaperStoreError(f"combined transaction artifact publish failed: {exc}") from exc

    digests = {
        "settlement": artifact_sha256(settlement),
        "state": artifact_sha256(state),
        "nav": artifact_sha256(nav),
    }
    updated = copy.deepcopy(head)
    updated["current_state"] = _state_ref(
        f"weeks/{decision_bundle['decision_date']}/portfolio_state.json", state)
    updated["current_nav"] = _ref(f"weeks/{decision_bundle['decision_date']}/nav_snapshot.json", nav)
    updated["pending_decision"] = _pending_ref(next_decision_bundle)
    updated["last_settlement"] = {
        "decision_date": decision_bundle["decision_date"],
        "decision_sha256": artifact_sha256(decision_bundle),
        "price_packet_sha256": settlement["price_packet_sha256"],
        "settlement_sha256": digests["settlement"],
        "state_sha256": digests["state"],
        "nav_sha256": digests["nav"],
    }
    _validate_head(updated)
    try:
        _atomic_write(_head_path(store_root), updated)
    except (OSError, ModelPaperPortfolioError, ModelPaperStoreError) as exc:
        raise ModelPaperStoreError(
            f"combined head publish failed after immutable artifacts; identical retry will recover: {exc}") from exc
    return "settled_and_frozen"


__all__ = [
    "ModelPaperStoreError",
    "commit_settlement",
    "freeze_decision_bundle",
    "initialize_store",
    "load_current_nav",
    "load_pending_decision",
    "load_current_state",
    "load_head",
    "commit_settlement_and_freeze_next",
]
