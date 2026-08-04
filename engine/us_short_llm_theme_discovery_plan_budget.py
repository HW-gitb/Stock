"""Offline, plan-bound dispatch accounting for the US-short discovery lanes.

The ledger is written before a provider callable is entered.  A completion write
that fails after the callable returned is therefore represented as a
``DispatchOutcome`` instead of being allowed to erase the paid response from the
runner's partial packet.  Re-entry never silently changes an in-flight dispatch;
an explicit, audited recovery is required before a stale owner can be replaced.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, Callable, Mapping
import uuid

from engine.us_short_llm_theme_discovery_query_plan import (
    QueryPlanError,
    derive_stage1_provider_envelope,
    derive_stage1_query_records,
    validate_parent_plan,
    validate_parent_plan_against_reviewed_policy,
)
from engine.us_short_schema_formats import FORMAT_CHECKER
from runners import us_short_discovery_publish_policy as publish_policy


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state" / "us_short"
SCHEMA_PATH = ROOT / "schemas" / "us_short_llm_theme_discovery_plan_budget.schema.json"
PLAN_BUDGET_PREFIX = "us_short_llm_theme_discovery_plan"
PLAN_BUDGET_MODE = "parent_plan_envelope"
PLAN_PROVIDERS = ("web", "xai")
PLAN_LANE = "us_short"

OWNER_HEARTBEAT_INTERVAL_SECONDS = 1.0
OWNER_HEARTBEAT_TTL_SECONDS = 30.0
VENDOR_BY_PROVIDER_STAGE = {
    ("web", "stage1"): "tavily",
    ("web", "stage2"): "deepseek",
    ("xai", "stage1"): "xai",
}
VENDOR_NAMES = ("tavily", "deepseek", "xai")

_COUNT_FIELDS = (
    "stage1_dispatch_count",
    "stage2_dispatch_count",
    "retry_dispatch_count",
    "dispatch_count",
    "unknown_dispatch_count",
)
_ENVELOPE_COUNT_FIELDS = (
    "stage1_max_dispatch_count",
    "stage2_max_dispatch_count",
    "retry_max_dispatch_count",
    "max_dispatch_count",
)

# These exceptions are process-control signals, not provider drops.  Keep the tuple in the
# budget layer so the ledger owner and the paid gateway classify the same BaseException set.
CONTROL_EXCEPTIONS = (
    KeyboardInterrupt, SystemExit, GeneratorExit,
    MemoryError, RecursionError, SystemError,
)


class PlanBudgetError(ValueError):
    """A plan envelope or its mutable dispatch ledger is unsafe to consume."""


def is_control_error(exc: BaseException) -> bool:
    """Return whether ``exc`` must be re-raised after dispatch accounting."""
    return isinstance(exc, CONTROL_EXCEPTIONS)


def provider_caps() -> dict[str, int]:
    """Read the provider ceilings from the one shared policy source."""
    from engine.us_short_llm_theme_discovery_provider_policy import PROVIDER_CALL_BUDGET

    source = PROVIDER_CALL_BUDGET
    return {
        "tavily": source[("web", "tavily")],
        "deepseek": source[("web", "deepseek")],
        "xai": source[("x", "xai")],
    }


def derive_hard_provider_call_budget() -> dict[str, dict[str, int]]:
    """Derive outer plan caps from the single shared provider-call policy."""
    caps = provider_caps()
    return {
        "web": {
            "stage1_max_dispatch_count": caps["tavily"],
            "stage2_max_dispatch_count": caps["deepseek"],
            "retry_max_dispatch_count": max(caps["tavily"], caps["deepseek"]),
            "max_dispatch_count": caps["tavily"] + caps["deepseek"],
        },
        "xai": {
            "stage1_max_dispatch_count": caps["xai"],
            "stage2_max_dispatch_count": 0,
            "retry_max_dispatch_count": caps["xai"],
            "max_dispatch_count": caps["xai"],
        },
    }


def _vendor_for(provider: str, stage: str) -> str:
    try:
        return VENDOR_BY_PROVIDER_STAGE[(provider, stage)]
    except KeyError as exc:
        raise PlanBudgetError(f"no provider/stage vendor mapping for {provider}/{stage}") from exc


@dataclass(frozen=True)
class DispatchHandle:
    provider: str
    dispatch_id: int
    query_sha256: str
    stage: str
    vendor: str
    attempt: int
    owner_run_id: str


@dataclass(frozen=True)
class DispatchOutcome:
    """The provider result and any post-payment ledger completion failure."""

    value: Any = None
    call_error: BaseException | None = None
    completion_error: PlanBudgetError | None = None


class PostPaymentDispatchError(PlanBudgetError):
    """Ledger completion failed after the provider callable returned a value."""

    def __init__(self, cause: BaseException, *, value: Any = None):
        super().__init__(f"post-payment dispatch completion failed: {type(cause).__name__}")
        self.cause = cause
        self.value = value


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_stamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _scope_digest(scope: str) -> str:
    if type(scope) is not str or not scope:
        raise PlanBudgetError("dispatch scope must be a non-empty string")
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()


def _path(provider: str, decision_date: str, state_dir: Path) -> Path:
    return state_dir / f"{PLAN_BUDGET_PREFIX}_{provider}_{decision_date}_budget.json"


def _read_schema() -> dict[str, Any]:
    try:
        value = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PlanBudgetError("plan budget schema is unreadable") from exc
    if type(value) is not dict:
        raise PlanBudgetError("plan budget schema must be an object")
    return value


def _validate_schema(payload: Any) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:  # pragma: no cover - project dependency
        raise PlanBudgetError("jsonschema is required for the plan budget contract") from exc
    errors = sorted(
        Draft7Validator(_read_schema(), format_checker=FORMAT_CHECKER).iter_errors(payload),
        key=lambda error: list(error.path),
    )
    if errors:
        raise PlanBudgetError(f"plan budget schema rejected: {errors[0].message}")


def _ledger_path(*, provider: str, decision_date: str, state_dir: Path) -> Path:
    if provider not in PLAN_PROVIDERS:
        raise PlanBudgetError(f"unsupported plan provider: {provider}")
    return _path(provider, decision_date, state_dir)


def default_plan_budget_path(
    provider: str, decision_date: str, *, state_dir: Path = STATE_DIR,
) -> Path:
    """Return the one plan-level budget slot for a provider and decision date."""
    return _ledger_path(
        provider=provider, decision_date=decision_date, state_dir=Path(state_dir),
    )


def _validate_hard_provider_envelope(provider: str, envelope: Mapping[str, Any]) -> None:
    hard = derive_hard_provider_call_budget().get(provider)
    if hard is None or envelope.get("provider") != provider:
        raise PlanBudgetError("provider envelope identity is invalid")
    if any(type(envelope.get(field)) is not int for field in _ENVELOPE_COUNT_FIELDS):
        raise PlanBudgetError(f"{provider} provider envelope counts must be integers")
    if any(envelope[field] < 0 for field in _ENVELOPE_COUNT_FIELDS):
        raise PlanBudgetError(f"{provider} provider envelope counts must be non-negative")
    if provider == "web":
        within_provider_caps = (
            envelope["stage1_max_dispatch_count"] + envelope["retry_max_dispatch_count"]
            <= hard["stage1_max_dispatch_count"]
            and envelope["stage2_max_dispatch_count"] + envelope["retry_max_dispatch_count"]
            <= hard["stage2_max_dispatch_count"]
        )
    else:
        within_provider_caps = (
            envelope["stage2_max_dispatch_count"] == hard["stage2_max_dispatch_count"]
            and envelope["stage1_max_dispatch_count"] + envelope["retry_max_dispatch_count"]
            <= hard["stage1_max_dispatch_count"]
        )
    if not within_provider_caps or envelope["max_dispatch_count"] > hard["max_dispatch_count"]:
        raise PlanBudgetError(f"{provider} provider envelope exceeds the hard provider call budget")


def _provider_envelopes(
    parent_plan: Mapping[str, Any], *, require_reviewed_policy: bool = True,
) -> dict[str, dict[str, Any]]:
    try:
        validate_parent_plan(parent_plan)
        if require_reviewed_policy:
            # The opt-out is the CALLER's to declare, never the plan's.  Keying it on
            # the plan's own `policy_version` would let a forged plan skip the whole
            # authority check simply by claiming a different version.
            validate_parent_plan_against_reviewed_policy(parent_plan)
    except QueryPlanError as exc:
        raise PlanBudgetError(f"parent plan is not valid: {exc}") from exc
    core = parent_plan.get("canonical_plan_core")
    rows = core.get("provider_envelopes") if isinstance(core, dict) else None
    if not isinstance(rows, list):
        raise PlanBudgetError("parent plan has no provider envelopes")
    keyed = {row.get("provider"): dict(row) for row in rows if isinstance(row, dict)}
    missing = [provider for provider in PLAN_PROVIDERS if provider not in keyed]
    if missing:
        raise PlanBudgetError(f"parent plan is missing provider envelopes: {','.join(missing)}")
    result = {provider: keyed[provider] for provider in PLAN_PROVIDERS}
    for provider, envelope in result.items():
        _validate_hard_provider_envelope(provider, envelope)
    return result


def _new_ledger(
    *, lane: str, provider: str, decision_date: str, parent_plan: Mapping[str, Any],
    envelope: Mapping[str, Any],
) -> dict[str, Any]:
    stamp = _stamp()
    return {
        "schema_name": "us_short_llm_theme_discovery_plan_budget",
        "schema_version": "1.0.0",
        "budget_mode": PLAN_BUDGET_MODE,
        "lane": lane,
        "provider": provider,
        "decision_date": decision_date,
        "parent_plan_identity": parent_plan["plan_identity"],
        "provider_envelope": dict(envelope),
        "planned_provider_call_count": envelope["max_dispatch_count"],
        "reservation_attempt_count": 1,
        "first_reserved_at": stamp,
        "last_reserved_at": stamp,
        "query_reservations": [],
        "dispatches": [],
        "dispatch_counts": {
            "stage1_dispatch_count": 0,
            "stage2_dispatch_count": 0,
            "retry_dispatch_count": 0,
            "dispatch_count": 0,
            "unknown_dispatch_count": 0,
        },
        "vendor_dispatch_counts": {vendor: 0 for vendor in VENDOR_NAMES},
        "recovery_events": [],
    }


def _bucket(stage: str, attempt: int) -> tuple[str, str]:
    if stage not in {"stage1", "stage2"}:
        raise PlanBudgetError("dispatch stage must be stage1 or stage2")
    if type(attempt) is not int or attempt < 1:
        raise PlanBudgetError("dispatch attempt must be a positive integer")
    if attempt > 1:
        return "retry", "retry_max_dispatch_count"
    return stage, f"{stage}_max_dispatch_count"


def _enforce_envelope_counts(
    envelope: Mapping[str, Any], dispatch_counts: Mapping[str, int],
    vendor_counts: Mapping[str, int],
) -> None:
    """Load-bearing pre-dispatch and persisted-ledger envelope predicate."""
    for bucket in ("stage1", "stage2", "retry"):
        observed = dispatch_counts[f"{bucket}_dispatch_count"]
        cap = envelope[f"{bucket}_max_dispatch_count"]
        if observed > cap:
            raise PlanBudgetError(f"{bucket} dispatch exceeds the frozen provider envelope")
    if dispatch_counts["dispatch_count"] > envelope["max_dispatch_count"]:
        raise PlanBudgetError("dispatch exceeds the frozen provider envelope")
    caps = provider_caps()
    for vendor in VENDOR_NAMES:
        if vendor_counts[vendor] > caps[vendor]:
            raise PlanBudgetError(f"{vendor} dispatch exceeds the hard provider call budget")


def _validate_semantics(
    payload: Mapping[str, Any], *, lane: str, provider: str,
    decision_date: str, parent_plan_identity: str, envelope: Mapping[str, Any],
) -> None:
    _validate_schema(payload)
    errors: list[str] = []
    _validate_hard_provider_envelope(provider, envelope)
    if payload.get("budget_mode") != PLAN_BUDGET_MODE:
        errors.append("budget mode is not a parent-plan envelope")
    if (payload.get("lane"), payload.get("provider"), payload.get("decision_date")) != (
        lane, provider, decision_date,
    ):
        errors.append("ledger identity does not match its slot")
    if payload.get("parent_plan_identity") != parent_plan_identity:
        errors.append("ledger is bound to a different parent plan")
    if payload.get("provider_envelope") != dict(envelope):
        errors.append("provider envelope changed after reservation")
    if payload.get("planned_provider_call_count") != envelope.get("max_dispatch_count"):
        errors.append("planned count is not the frozen provider envelope")
    reservation_attempt_count = payload.get("reservation_attempt_count")
    if type(reservation_attempt_count) is not int or reservation_attempt_count < 1:
        errors.append("reservation attempt count must be a positive integer")
    first_reserved = _parse_stamp(payload.get("first_reserved_at"))
    last_reserved = _parse_stamp(payload.get("last_reserved_at"))
    if first_reserved is None or last_reserved is None or last_reserved < first_reserved:
        errors.append("reservation timestamps are invalid")

    counts = payload.get("dispatch_counts", {})
    for field in _COUNT_FIELDS:
        value = counts.get(field)
        if type(value) is not int or value < 0:
            errors.append(f"dispatch count field {field} must be an integer")
    vendor_counts = payload.get("vendor_dispatch_counts", {})
    for vendor in VENDOR_NAMES:
        value = vendor_counts.get(vendor)
        if type(value) is not int or value < 0:
            errors.append(f"vendor dispatch count field {vendor} must be an integer")

    reservations = payload.get("query_reservations", [])
    reservation_keys = [
        (row.get("query_sha256"), row.get("stage"), row.get("vendor"))
        for row in reservations
    ]
    if len(set(reservation_keys)) != len(reservation_keys):
        errors.append("query scope is reserved more than once")
    reservation_by_key = {key: row for key, row in zip(reservation_keys, reservations)}

    dispatches = payload.get("dispatches", [])
    dispatch_ids = [row.get("dispatch_id") for row in dispatches]
    if len(set(dispatch_ids)) != len(dispatch_ids):
        errors.append("dispatch id is repeated")
    if dispatch_ids != list(range(1, len(dispatches) + 1)):
        errors.append("dispatch ids must be contiguous history")
    counted_statuses = {"in_flight", "complete", "failure", "unknown"}
    if any(row.get("status") not in counted_statuses for row in dispatches):
        errors.append("dispatch status is unknown")
    if any(row.get("last_status") not in counted_statuses for row in reservations):
        errors.append("reservation status is unknown")

    history: dict[tuple[Any, Any, Any], list[Mapping[str, Any]]] = {}
    for row in dispatches:
        row_key = (row.get("query_sha256"), row.get("stage"), row.get("vendor"))
        history.setdefault(row_key, []).append(row)
        if type(row.get("owner_pid")) is not int or row.get("owner_pid") < 1:
            errors.append("dispatch owner_pid must be a positive integer audit field")
        started_at = _parse_stamp(row.get("started_at"))
        heartbeat_at = _parse_stamp(row.get("owner_heartbeat_at"))
        if started_at is None or heartbeat_at is None:
            errors.append("dispatch owner timestamps are invalid")
        if row.get("status") == "in_flight" and row.get("finished_at") is not None:
            errors.append("in-flight dispatch cannot have finished_at")
        if row.get("status") != "in_flight" and _parse_stamp(row.get("finished_at")) is None:
            errors.append("finished dispatch must have finished_at")
        if row.get("status") == "unknown" and not isinstance(row.get("unknown_reason"), str):
            errors.append("unknown dispatch must have unknown_reason")
        try:
            expected_vendor = _vendor_for(provider, row["stage"])
            if row.get("vendor") != expected_vendor:
                errors.append("dispatch vendor does not match provider/stage")
            bucket, cap_field = _bucket(row["stage"], row["attempt"])
            if row["attempt"] > envelope["retry_max_dispatch_count"] + 1:
                errors.append("dispatch attempt exceeds the frozen retry history bound")
            if row["attempt"] > envelope[cap_field] + 1:
                errors.append(f"{bucket} dispatch attempt exceeds its frozen envelope")
            if row_key not in reservation_by_key:
                errors.append("dispatch scope has no reservation")
        except (KeyError, PlanBudgetError) as exc:
            errors.append(f"dispatch event is malformed: {exc}")

    for key, reservation in reservation_by_key.items():
        try:
            if reservation.get("query_count") != 1 or reservation.get("planned_provider_call_count") != 1:
                errors.append("query reservation counts must remain one")
            expected_vendor = _vendor_for(provider, reservation["stage"])
            if reservation.get("vendor") != expected_vendor:
                errors.append("reservation vendor does not match provider/stage")
            rows = history.get(key, [])
            attempts = [row.get("attempt") for row in rows]
            if attempts != list(range(1, len(rows) + 1)):
                errors.append("dispatch attempt history is not contiguous")
            if reservation.get("attempt_count") != len(rows):
                errors.append("reservation attempt count does not match dispatch history")
            if rows and reservation.get("last_status") != rows[-1].get("status"):
                errors.append("reservation status does not match dispatch history")
            if not rows and reservation.get("last_status") != "in_flight":
                errors.append("empty reservation has an invalid status")
        except (KeyError, PlanBudgetError) as exc:
            errors.append(f"reservation is malformed: {exc}")

    observed = {field: 0 for field in _COUNT_FIELDS}
    observed_vendors = {vendor: 0 for vendor in VENDOR_NAMES}
    for row in dispatches:
        try:
            bucket, cap_field = _bucket(row["stage"], row["attempt"])
            observed[f"{bucket}_dispatch_count"] += 1
            observed["dispatch_count"] += 1
            if row.get("status") == "unknown":
                observed["unknown_dispatch_count"] += 1
            observed_vendors[row["vendor"]] += 1
        except (KeyError, PlanBudgetError) as exc:
            errors.append(f"dispatch event is malformed: {exc}")
    if any(counts.get(field) != observed[field] for field in _COUNT_FIELDS):
        errors.append("dispatch counts do not match dispatch events")
    if any(vendor_counts.get(vendor) != observed_vendors[vendor] for vendor in VENDOR_NAMES):
        errors.append("vendor dispatch counts do not match dispatch events")
    try:
        _enforce_envelope_counts(envelope, observed, observed_vendors)
    except PlanBudgetError as exc:
        errors.append(str(exc))

    recovery_events = payload.get("recovery_events", [])
    recovery_ids = [event.get("recovery_id") for event in recovery_events]
    if len(set(recovery_ids)) != len(recovery_ids):
        errors.append("recovery event id is repeated")
    dispatch_by_id = {row.get("dispatch_id"): row for row in dispatches}
    for event in recovery_events:
        row = dispatch_by_id.get(event.get("dispatch_id"))
        if row is None or row.get("status") != "unknown":
            errors.append("recovery event is not bound to an unknown dispatch")
        if event.get("owner_run_id") != (row or {}).get("owner_run_id"):
            errors.append("recovery event owner identity does not match dispatch")
        if not isinstance(event.get("reason"), str) or not event.get("reason", "").strip():
            errors.append("recovery event reason is required")
        if _parse_stamp(event.get("recovered_at")) is None:
            errors.append("recovery event recovered_at is invalid")
    if errors:
        raise PlanBudgetError("; ".join(errors))


@contextmanager
def _ledger_lock(path: Path):
    try:
        with publish_policy.mutable_ledger_lock(path):
            yield
    except publish_policy.DiscoveryPublishPolicyError as exc:
        raise PlanBudgetError(str(exc)) from exc


def coerce_budget_error(exc: BaseException) -> PlanBudgetError | None:
    """Normalize the shared write-door error without swallowing provider errors."""
    if isinstance(exc, PlanBudgetError):
        return exc
    if isinstance(exc, publish_policy.DiscoveryPublishPolicyError):
        return PlanBudgetError(str(exc))
    return None


def validate_run_decision_date(
    parent_plan: Mapping[str, Any], expected_decision_date: str,
    *, require_reviewed_policy: bool = True,
) -> str:
    try:
        validate_parent_plan(parent_plan)
        if require_reviewed_policy:
            # Same rule as `_provider_envelopes`: the caller declares the opt-out.
            validate_parent_plan_against_reviewed_policy(parent_plan)
    except QueryPlanError as exc:
        raise PlanBudgetError(f"parent plan is not valid: {exc}") from exc
    actual = parent_plan["canonical_plan_core"]["decision_date"]
    if actual != expected_decision_date:
        raise PlanBudgetError("parent plan decision_date does not match the run decision_date")
    return actual


def validate_plan_stage1_query(
    parent_plan: Mapping[str, Any], *, provider: str, query_id: str,
    query_text: str, query_text_sha256: str,
) -> dict[str, Any]:
    """Validate one gateway request against the frozen Stage-1 query and envelope."""
    try:
        records = derive_stage1_query_records(parent_plan)
        envelope = derive_stage1_provider_envelope(parent_plan, provider=provider)
    except QueryPlanError as exc:
        raise PlanBudgetError(f"parent plan Stage-1 binding is invalid: {exc}") from exc
    if type(query_id) is not str or not query_id:
        raise PlanBudgetError("plan-bound Stage-1 request requires query_id")
    if type(query_text) is not str or not query_text:
        raise PlanBudgetError("plan-bound Stage-1 request requires query_text")
    expected = next((row for row in records if row["query_id"] == query_id), None)
    if expected is None:
        raise PlanBudgetError("query_id is outside the parent plan Stage-1 query set")
    if query_text != expected["query_text"]:
        raise PlanBudgetError("query text does not match the parent plan query_id")
    if query_text_sha256 != expected["query_text_sha256"]:
        raise PlanBudgetError("query text hash does not match the parent plan query_id")
    return envelope


def _owner_is_alive(row: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    """Use the persisted run identity and heartbeat, never a recyclable PID."""
    run_id = row.get("owner_run_id")
    started = _parse_stamp(row.get("owner_started_at"))
    heartbeat = _parse_stamp(row.get("owner_heartbeat_at"))
    if not isinstance(run_id, str) or not run_id or started is None or heartbeat is None:
        return False
    if heartbeat < started:
        return False
    current = now or datetime.now(timezone.utc)
    age = (current - heartbeat).total_seconds()
    return age <= OWNER_HEARTBEAT_TTL_SECONDS


def _write(
    payload: dict[str, Any], path: Path, *, root: Path, state_dir: Path,
    gitignored: Callable[[Path], bool] | None,
) -> None:
    try:
        publish_policy.write_mutable_ledger(
            payload, path, root=root, state_dir=state_dir, gitignored=gitignored,
            ledger_kind="provider_budget",
        )
    except publish_policy.DiscoveryPublishPolicyError as exc:
        raise PlanBudgetError(str(exc)) from exc


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PlanBudgetError("plan budget ledger is unreadable") from exc
    if type(payload) is not dict:
        raise PlanBudgetError("plan budget ledger must be an object")
    return payload


def _reservation_for(
    payload: Mapping[str, Any], scope_hash: str, stage: str, vendor: str,
) -> dict[str, Any] | None:
    return next(
        (
            row for row in payload.get("query_reservations", [])
            if isinstance(row, dict)
            and row.get("query_sha256") == scope_hash
            and row.get("stage") == stage
            and row.get("vendor") == vendor
        ),
        None,
    )


class PlanDispatchBudget:
    """A mutex-protected plan/date/provider envelope and dispatch guard."""

    def __init__(
        self, parent_plan: Mapping[str, Any], *, lane: str = PLAN_LANE,
        state_dir: Path = STATE_DIR, root: Path = ROOT,
        gitignored: Callable[[Path], bool] | None = None,
        expected_decision_date: str | None = None,
        providers: tuple[str, ...] = PLAN_PROVIDERS,
        require_reviewed_policy: bool = True,
    ) -> None:
        envelopes = _provider_envelopes(
            parent_plan, require_reviewed_policy=require_reviewed_policy,
        )
        if lane != PLAN_LANE:
            raise PlanBudgetError(f"plan budget lane must be {PLAN_LANE}")
        if expected_decision_date is not None:
            validate_run_decision_date(
                parent_plan, expected_decision_date,
                require_reviewed_policy=require_reviewed_policy,
            )
        self.parent_plan = dict(parent_plan)
        self.lane = lane
        self.state_dir = Path(state_dir)
        self.root = Path(root)
        self.gitignored = gitignored
        self.decision_date = parent_plan["canonical_plan_core"]["decision_date"]
        self.parent_plan_identity = parent_plan["plan_identity"]
        self.envelopes = envelopes
        if not providers or any(provider not in PLAN_PROVIDERS for provider in providers):
            raise PlanBudgetError("plan budget provider reservation scope is invalid")
        self.providers = tuple(dict.fromkeys(providers))
        self.owner_pid = os.getpid()
        self.owner_run_id = uuid.uuid4().hex
        self.owner_started_at = _stamp()
        self._reserved = False

    def _path(self, provider: str) -> Path:
        return _ledger_path(
            provider=provider, decision_date=self.decision_date, state_dir=self.state_dir,
        )

    def _validate_loaded(self, payload: Mapping[str, Any], provider: str) -> None:
        _validate_semantics(
            payload, lane=self.lane, provider=provider,
            decision_date=self.decision_date,
            parent_plan_identity=self.parent_plan_identity,
            envelope=self.envelopes[provider],
        )

    def _reserve_one(self, provider: str) -> None:
        path = self._path(provider)
        envelope = self.envelopes[provider]
        with _ledger_lock(path):
            if path.exists():
                payload = _load(path)
                self._validate_loaded(payload, provider)
                in_flight = [row for row in payload["dispatches"] if row["status"] == "in_flight"]
                active = [row for row in in_flight if _owner_is_alive(row)]
                if active:
                    raise PlanBudgetError(
                        "active peer owns an in-flight dispatch; recovery is refused"
                    )
                if in_flight:
                    raise PlanBudgetError(
                        "stale in-flight dispatch requires explicit recovery; cap is not reset"
                    )
                now = _stamp()
                payload["reservation_attempt_count"] += 1
                payload["last_reserved_at"] = now
            else:
                payload = _new_ledger(
                    lane=self.lane, provider=provider, decision_date=self.decision_date,
                    parent_plan=self.parent_plan, envelope=envelope,
                )
            self._validate_loaded(payload, provider)
            _write(
                payload, path, root=self.root, state_dir=self.state_dir,
                gitignored=self.gitignored,
            )

    def reserve(self) -> None:
        """Reserve every parent-plan provider envelope before any paid dispatch."""
        for provider in self.providers:
            self._reserve_one(provider)
        self._reserved = True

    def _check_next_dispatch_capacity(
        self, payload: Mapping[str, Any], *, provider: str, stage: str, attempt: int,
    ) -> tuple[str, str, str]:
        vendor = _vendor_for(provider, stage)
        bucket, cap_field = _bucket(stage, attempt)
        prospective_counts = dict(payload["dispatch_counts"])
        prospective_counts[f"{bucket}_dispatch_count"] += 1
        prospective_counts["dispatch_count"] += 1
        prospective_vendor_counts = dict(payload["vendor_dispatch_counts"])
        prospective_vendor_counts[vendor] += 1
        _enforce_envelope_counts(
            self.envelopes[provider], prospective_counts, prospective_vendor_counts,
        )
        return bucket, cap_field, vendor

    def _begin_one(self, provider: str, scope: str, stage: str) -> DispatchHandle:
        if provider not in self.providers:
            raise PlanBudgetError(f"provider is outside the reserved provider scope: {provider}")
        if provider not in self.envelopes:
            raise PlanBudgetError(f"provider is not in the parent plan: {provider}")
        scope_hash = _scope_digest(scope)
        vendor = _vendor_for(provider, stage)
        path = self._path(provider)
        envelope = self.envelopes[provider]
        with _ledger_lock(path):
            if not path.exists():
                raise PlanBudgetError("provider envelope was not reserved before dispatch")
            payload = _load(path)
            self._validate_loaded(payload, provider)
            reservation = _reservation_for(payload, scope_hash, stage, vendor)
            history = [
                row for row in payload["dispatches"]
                if row["query_sha256"] == scope_hash
                and row["stage"] == stage
                and row["vendor"] == vendor
            ]
            if reservation is not None and reservation["last_status"] in {
                "in_flight", "unknown", "complete",
            }:
                raise PlanBudgetError("scope cannot be automatically replayed after its prior state")
            if reservation is not None and reservation["attempt_count"] != len(history):
                raise PlanBudgetError("scope attempt history is inconsistent")
            attempt = 1 if reservation is None else len(history) + 1
            bucket, _cap_field, vendor = self._check_next_dispatch_capacity(
                payload, provider=provider, stage=stage, attempt=attempt,
            )
            if reservation is None:
                reservation = {
                    "query_sha256": scope_hash,
                    "stage": stage,
                    "vendor": vendor,
                    "query_count": 1,
                    "planned_provider_call_count": 1,
                    "attempt_count": attempt,
                    "last_status": "in_flight",
                }
                payload["query_reservations"].append(reservation)
            else:
                reservation["attempt_count"] = attempt
                reservation["last_status"] = "in_flight"
            dispatch_id = len(payload["dispatches"]) + 1
            payload["dispatches"].append({
                "dispatch_id": dispatch_id,
                "query_sha256": scope_hash,
                "stage": stage,
                "vendor": vendor,
                "attempt": attempt,
                "status": "in_flight",
                "started_at": _stamp(),
                "owner_pid": self.owner_pid,
                "owner_run_id": self.owner_run_id,
                "owner_started_at": self.owner_started_at,
                "owner_heartbeat_at": _stamp(),
            })
            counts = payload["dispatch_counts"]
            counts[f"{bucket}_dispatch_count"] += 1
            counts["dispatch_count"] += 1
            payload["vendor_dispatch_counts"][vendor] += 1
            self._validate_loaded(payload, provider)
            _write(
                payload, path, root=self.root, state_dir=self.state_dir,
                gitignored=self.gitignored,
            )
        return DispatchHandle(
            provider, dispatch_id, scope_hash, stage, vendor, attempt, self.owner_run_id,
        )

    def begin(self, provider: str, *, scope: str, stage: str) -> DispatchHandle:
        if not self._reserved:
            raise PlanBudgetError("plan budget must be reserved before dispatch")
        return self._begin_one(provider, scope, stage)

    def _heartbeat_once(self, handle: DispatchHandle) -> None:
        path = self._path(handle.provider)
        with _ledger_lock(path):
            payload = _load(path)
            self._validate_loaded(payload, handle.provider)
            dispatch = next(
                (row for row in payload["dispatches"] if row["dispatch_id"] == handle.dispatch_id),
                None,
            )
            if dispatch is None or dispatch["status"] != "in_flight":
                return
            if dispatch.get("owner_run_id") != handle.owner_run_id:
                raise PlanBudgetError("heartbeat owner identity does not match")
            dispatch["owner_heartbeat_at"] = _stamp()
            self._validate_loaded(payload, handle.provider)
            _write(
                payload, path, root=self.root, state_dir=self.state_dir,
                gitignored=self.gitignored,
            )

    def _heartbeat_loop(self, handle: DispatchHandle, stop: threading.Event) -> None:
        while not stop.wait(OWNER_HEARTBEAT_INTERVAL_SECONDS):
            try:
                self._heartbeat_once(handle)
            except BaseException:
                # The completion path remains authoritative.  A failed heartbeat makes a later
                # re-entry fail closed until an explicit recovery is recorded.
                return

    def finish(self, handle: DispatchHandle, *, status: str) -> None:
        if status not in {"complete", "failure", "unknown"}:
            raise PlanBudgetError("dispatch completion status is invalid")
        path = self._path(handle.provider)
        envelope = self.envelopes[handle.provider]
        with _ledger_lock(path):
            payload = _load(path)
            self._validate_loaded(payload, handle.provider)
            dispatch = next(
                (row for row in payload["dispatches"] if row["dispatch_id"] == handle.dispatch_id),
                None,
            )
            if dispatch is None or dispatch["status"] != "in_flight":
                raise PlanBudgetError("dispatch completion does not match an in-flight call")
            if (
                dispatch["query_sha256"] != handle.query_sha256
                or dispatch["stage"] != handle.stage
                or dispatch["vendor"] != handle.vendor
                or dispatch["attempt"] != handle.attempt
                or dispatch["owner_run_id"] != handle.owner_run_id
            ):
                raise PlanBudgetError("dispatch completion identity does not match")
            dispatch["status"] = status
            dispatch["finished_at"] = _stamp()
            dispatch["owner_heartbeat_at"] = dispatch["finished_at"]
            if status == "unknown":
                dispatch["unknown_reason"] = "explicit_unknown_completion"
            payload["dispatch_counts"]["unknown_dispatch_count"] = sum(
                row["status"] == "unknown" for row in payload["dispatches"]
            )
            reservation = _reservation_for(
                payload, handle.query_sha256, handle.stage, handle.vendor,
            )
            if reservation is None:
                raise PlanBudgetError("dispatch completion has no scope reservation")
            reservation["last_status"] = status
            self._validate_loaded(payload, handle.provider)
            _write(
                payload, path, root=self.root, state_dir=self.state_dir,
                gitignored=self.gitignored,
            )

    def dispatch_with_outcome(
        self, provider: str, *, scope: str, stage: str,
        call: Callable[[], Any],
    ) -> DispatchOutcome:
        """Run one paid call while retaining its value if completion persistence fails."""
        handle = self.begin(provider, scope=scope, stage=stage)
        stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_loop, args=(handle, stop),
            name=f"us-short-budget-heartbeat-{handle.dispatch_id}", daemon=True,
        )
        heartbeat.start()
        value: Any = None
        call_error: BaseException | None = None
        control_error: BaseException | None = None
        try:
            try:
                value = call()
            except BaseException as exc:
                if is_control_error(exc):
                    control_error = exc
                else:
                    call_error = exc
        finally:
            stop.set()
            heartbeat.join(timeout=max(1.0, OWNER_HEARTBEAT_INTERVAL_SECONDS * 2))
        completion_error: PlanBudgetError | None = None
        try:
            self.finish(
                handle,
                status="failure" if call_error is not None or control_error is not None else "complete",
            )
        except BaseException as exc:
            if is_control_error(exc):
                # A control signal raised while closing the ledger is never downgraded to a
                # provider drop or a post-payment diagnostic.
                raise
            completion_error = PostPaymentDispatchError(exc, value=value)
        if control_error is not None:
            raise control_error
        return DispatchOutcome(
            value=value, call_error=call_error, completion_error=completion_error,
        )

    def recover_stale_in_flight(
        self, provider: str, *, dispatch_id: int, recovery_reason: str,
    ) -> int:
        """Explicitly mark one stale owner unknown without resetting any cap."""
        if type(dispatch_id) is not int or dispatch_id < 1:
            raise PlanBudgetError("recovery dispatch_id must be a positive integer")
        if type(recovery_reason) is not str or not recovery_reason.strip():
            raise PlanBudgetError("recovery reason is required")
        path = self._path(provider)
        with _ledger_lock(path):
            payload = _load(path)
            self._validate_loaded(payload, provider)
            dispatch = next(
                (row for row in payload["dispatches"] if row["dispatch_id"] == dispatch_id),
                None,
            )
            if dispatch is None or dispatch["status"] != "in_flight":
                raise PlanBudgetError("only an in-flight dispatch can be explicitly recovered")
            if _owner_is_alive(dispatch):
                raise PlanBudgetError("active owner heartbeat is fresh; recovery is refused")
            now = _stamp()
            dispatch["status"] = "unknown"
            dispatch["finished_at"] = now
            dispatch["owner_heartbeat_at"] = now
            dispatch["unknown_reason"] = recovery_reason.strip()
            reservation = _reservation_for(
                payload, dispatch["query_sha256"], dispatch["stage"], dispatch["vendor"],
            )
            if reservation is None:
                raise PlanBudgetError("stale dispatch has no scope reservation")
            reservation["last_status"] = "unknown"
            payload["dispatch_counts"]["unknown_dispatch_count"] += 1
            payload["recovery_events"].append({
                "recovery_id": uuid.uuid4().hex,
                "dispatch_id": dispatch_id,
                "owner_run_id": dispatch["owner_run_id"],
                "recovered_at": now,
                "reason": recovery_reason.strip(),
            })
            self._validate_loaded(payload, provider)
            _write(
                payload, path, root=self.root, state_dir=self.state_dir,
                gitignored=self.gitignored,
            )
        return dispatch_id


def reserve_plan_budget(
    parent_plan: Mapping[str, Any], *, lane: str = PLAN_LANE,
    state_dir: Path = STATE_DIR, root: Path = ROOT,
    gitignored: Callable[[Path], bool] | None = None,
    expected_decision_date: str | None = None,
    providers: tuple[str, ...] = PLAN_PROVIDERS,
    require_reviewed_policy: bool = True,
) -> PlanDispatchBudget:
    """Build and reserve the one-time parent-plan envelope."""
    budget = PlanDispatchBudget(
        parent_plan, lane=lane, state_dir=state_dir, root=root, gitignored=gitignored,
        expected_decision_date=expected_decision_date, providers=providers,
        require_reviewed_policy=require_reviewed_policy,
    )
    budget.reserve()
    return budget


def recover_plan_budget_dispatch(
    parent_plan: Mapping[str, Any], *, provider: str, dispatch_id: int,
    recovery_reason: str, lane: str = PLAN_LANE, state_dir: Path = STATE_DIR,
    root: Path = ROOT, gitignored: Callable[[Path], bool] | None = None,
    expected_decision_date: str | None = None,
) -> int:
    """Recover one stale dispatch through the same guarded mutable ledger door."""
    budget = PlanDispatchBudget(
        parent_plan, lane=lane, state_dir=state_dir, root=root, gitignored=gitignored,
        expected_decision_date=expected_decision_date,
    )
    return budget.recover_stale_in_flight(
        provider, dispatch_id=dispatch_id, recovery_reason=recovery_reason,
    )
