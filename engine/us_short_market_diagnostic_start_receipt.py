"""US-short 26-week market-diagnostic Knife 7 start receipt.

The 26-week clock has exactly one door, and this module is it. Nothing else may
decide that week 1 has arrived: not the design document's own date, not the day a
component was finished, not the day the model-paper account was seeded, and not
any historical commit. Those are all things that happen to be true on some date;
none of them is a decision that the design is complete.

What this receipt does and does not prove, stated precisely, because a guard that
overstates itself is worse than one that does not exist:

* The design digest is re-computed whenever the receipt is used to AUTHORIZE, so a
  receipt bound to a contract that is not there is caught. It covers the frozen
  machine-bound contract block, not the living prose around it — see
  ``design_contract_block`` for why hashing the whole file was the wrong guard.
* The notification digest is re-computed from the notification text the receipt
  carries. That makes the pair self-consistent — a zeroed digest is caught — but
  it does NOT prove a notification was ever issued, because both halves live
  inside the receipt.
* Nothing here is tamper-PROOF. There is no secret, so anyone who can write the
  private root can hand-author a receipt that validates. What the receipt buys is
  tamper-EVIDENCE against the realistic failure: a clock opened by accident, by a
  stale date, or by someone reasoning that a component being finished must mean
  the design is done.

Authorization also has to survive the moment it is granted. Once the clock is
open the receipt's own digest is recorded in the lifecycle register, and every
later write re-checks that binding, so nobody can delete, corrupt, or swap the
receipt and leave a clock nobody can account for.

The receipt is immutable and idempotent, and it is created exclusively — a second
issuer racing the first loses visibly instead of silently overwriting the anchor.
It lives beside the lifecycle store under the private root, is never published,
and this module never calls a provider, touches the model-paper account, or
changes selection, action, sizing or NAV.

Building this door does not open it. ``issue_start_receipt`` requires a caller to
supply a real notification; there is no default that would let the clock start by
omission.
"""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

import jsonschema

from engine.us_short_market_diagnostic import window_containing_week
from engine.us_short_model_paper_portfolio import artifact_sha256, canonical_json_bytes
from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = ROOT / "state" / "us_short" / "market_diagnostic_private"
RECEIPT_FILENAME = "diagnostic_start_receipt.json"
RECEIPT_SCHEMA_PATH = ROOT / "schemas" / "us_short_market_diagnostic_start_receipt.schema.json"
DESIGN_AUTHORITY_RELATIVE_PATH = "docs/us_short_market_diagnostic_26w_design.md"
DESIGN_CONTRACT_ANCHOR = "12.1 Machine-bound v1 summary and status contract"
_DESIGN_CONTRACT_BLOCK = re.compile(
    r"```json\s*(\{\s*\"v1_summary_strategy_metric_fields\".*?\})\s*```", re.DOTALL
)

RECEIPT_BOUNDARY = {
    "diagnostic_only": True,
    "comparison_only": True,
    "counts_ship_gate": False,
    "changes_selection_or_action": False,
    "automatic_policy_switch": False,
    "broker_or_order_automation": False,
    "provider_fetch": False,
    "account_write": False,
    # A receipt is a recorded decision, never an inference from a timestamp.
    "issued_by_automatic_inference": False,
}

# Tests need to point the design-authority lookup at a fixture tree. That is a
# module-level seam rather than a public parameter, because a caller-chosen
# document root is exactly how a receipt stops being bound to the real design.
_DESIGN_AUTHORITY_ROOT = ROOT

_SCHEMA: dict[str, Any] | None = None
_DATE8 = re.compile(r"^[0-9]{8}\Z")
_SHA256 = re.compile(r"^[0-9a-f]{64}\Z")
# A frozen week must follow the decision and stay within a horizon somebody can act on.
_MAX_DAYS_AHEAD = 366
# This track's decision week is a Monday, and the whole 26-week clock is derived
# from the anchor by adding seven days -- so the anchor's weekday IS the clock's.
# Refusing only Saturday and Sunday let a Wednesday through, which anchors every
# one of the twenty-six weeks on a day this track never decides on.
_CANONICAL_DECISION_WEEKDAY = 0


class DiagnosticStartReceiptError(ValueError):
    """Raised when a start receipt is malformed, unbound, or cannot be written safely."""


def _fail(message: str) -> None:
    raise DiagnosticStartReceiptError(message)


def _validator() -> jsonschema.Draft7Validator:
    global _SCHEMA
    if _SCHEMA is None:
        try:
            _SCHEMA = json.loads(RECEIPT_SCHEMA_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DiagnosticStartReceiptError("start receipt schema is unreadable") from exc
    return jsonschema.Draft7Validator(_SCHEMA)


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{field} must be an object")
    assert isinstance(value, Mapping)
    return value


def _path_like(value: object, field: str) -> Path:
    """Reject a non-path before ``Path()`` can raise something untyped."""

    if isinstance(value, Path):
        return value
    if isinstance(value, str) and value:
        return Path(value)
    if isinstance(value, os.PathLike):
        return Path(value)
    _fail(f"{field} must be a non-empty path")
    raise AssertionError("unreachable")


def _date8(value: object, field: str) -> date:
    if not isinstance(value, str) or _DATE8.fullmatch(value) is None:
        _fail(f"{field} must be an eight-digit date")
    assert isinstance(value, str)
    try:
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    except ValueError as exc:
        raise DiagnosticStartReceiptError(f"{field} is not a real calendar date") from exc


def _aware_instant(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        _fail(f"{field} must be a timezone-aware timestamp string")
    assert isinstance(value, str)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DiagnosticStartReceiptError(f"{field} is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(f"{field} must carry a timezone offset")
    return parsed


def _text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def design_contract_block() -> dict[str, Any]:
    """The frozen machine-bound contract the receipt is actually bound to.

    Deliberately NOT the whole document. The design is a living file: section
    12.8 is unimplemented, section 13 still says Knife 7 has not run, and the
    register requires that sentence to change when it does. Hashing the file
    would mean each of those mandated edits permanently bricked a running clock,
    which is the "change something else and the accumulated evidence dies"
    failure this project has already paid for once. What must not move is the
    contract in 12.1 — the field list and status priority the whole track is
    measured against — so that is what is digested.
    """

    path = _DESIGN_AUTHORITY_ROOT / DESIGN_AUTHORITY_RELATIVE_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DiagnosticStartReceiptError(f"design authority is unreadable: {path}") from exc
    match = _DESIGN_CONTRACT_BLOCK.search(text)
    if match is None:
        _fail(
            f"design authority carries no machine-bound contract block ({DESIGN_CONTRACT_ANCHOR}): {path}"
        )
        raise AssertionError("unreachable")
    try:
        block = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise DiagnosticStartReceiptError(
            f"the machine-bound design contract is not valid JSON: {path}"
        ) from exc
    if not isinstance(block, dict):
        _fail("the machine-bound design contract must be an object")
    return block


def design_authority_sha256() -> str:
    """Digest of the frozen contract block, canonicalized so formatting is not identity."""

    return hashlib.sha256(canonical_json_bytes(design_contract_block())).hexdigest()


def build_start_receipt(
    *,
    diagnostic_epoch: str,
    completion_notification: Mapping[str, Any],
    first_decision_date: str,
    as_of_date: str,
) -> dict[str, Any]:
    """Assemble one receipt. The caller supplies the decision; the digests are earned.

    ``as_of_date`` is required, and required here rather than in
    ``validate_start_receipt``: minting is the moment a decision is claimed to
    have been made, so that is the only moment at which "the notification has not
    happened yet" is answerable. A receipt read back next year is legitimately
    older than the reader's clock, and re-judging it then would refuse every
    receipt that ever worked.
    """

    notification = _mapping(completion_notification, "completion_notification")
    for field in ("issued_at", "issuer", "notification_text"):
        if field not in notification:
            _fail(f"completion_notification.{field} is required")
    issued = _aware_instant(notification["issued_at"], "completion_notification.issued_at")
    text = notification["notification_text"]
    if not isinstance(text, str) or len(text) < 16:
        _fail("completion_notification.notification_text must be the notification itself")
    _date8(first_decision_date, "first_decision_date")
    # A notification dated in the future has not been issued. Every other check
    # here reasons FROM issued_at -- the anchor may not precede it, and may not
    # run away from it -- so a future issued_at moves the whole horizon with it
    # and re-legalizes exactly the back-fill those checks exist to refuse.
    if issued.date() > _date8(as_of_date, "as_of_date"):
        _fail(
            "completion_notification.issued_at is in the future; a decision that has not been "
            "made yet cannot authorize a clock"
        )

    window = window_containing_week(1)
    receipt = {
        "schema_name": "us_short_market_diagnostic_start_receipt",
        "schema_version": "1.0.0",
        "diagnostic_epoch": diagnostic_epoch,
        "design_authority": {
            "document_path": DESIGN_AUTHORITY_RELATIVE_PATH,
            "contract_anchor": DESIGN_CONTRACT_ANCHOR,
            "contract_sha256": design_authority_sha256(),
        },
        "completion_notification": {
            "issued_at": notification["issued_at"],
            "issuer": notification["issuer"],
            "notification_text": text,
            "notification_sha256": _text_digest(text),
        },
        "first_calendar_week": {
            "calendar_week_index": 1,
            "decision_date": first_decision_date,
            "window_id": window["window_id"],
        },
        "boundary": dict(RECEIPT_BOUNDARY),
    }
    validate_start_receipt(receipt)
    return receipt


def validate_start_receipt(
    receipt: Mapping[str, Any], *, verify_design_against_disk: bool = True
) -> dict[str, Any]:
    """Closed-world re-check.

    ``verify_design_against_disk`` is on for the moments that AUTHORIZE — issuing a
    receipt, and admitting week 1 — and off for ordinary reads of a clock that is
    already running. What is re-hashed is the frozen contract block, not the
    living document; see ``design_contract_block``.
    """

    candidate = _mapping(receipt, "start_receipt")
    errors = sorted(_validator().iter_errors(candidate), key=lambda error: list(error.absolute_path))
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path) or "<root>"
        _fail(f"start receipt schema violation at {location}: {errors[0].message}")

    if dict(candidate["boundary"]) != RECEIPT_BOUNDARY:
        _fail("start receipt crosses the diagnostic boundary")

    notification = candidate["completion_notification"]
    _aware_instant(notification["issued_at"], "completion_notification.issued_at")
    if _text_digest(notification["notification_text"]) != notification["notification_sha256"]:
        _fail("completion_notification.notification_sha256 does not match its own notification text")

    if verify_design_against_disk and candidate["design_authority"]["contract_sha256"] != design_authority_sha256():
        _fail(
            "start receipt design_authority.contract_sha256 does not match the machine-bound "
            "contract on disk; the clock was authorized against a different contract"
        )

    first = candidate["first_calendar_week"]
    frozen = _date8(first["decision_date"], "first_calendar_week.decision_date")
    issued = _aware_instant(notification["issued_at"], "completion_notification.issued_at").date()
    # A receipt authorizes a week that follows the decision. Freezing a week that
    # already happened is back-filling; freezing one years out authorizes nothing
    # anybody can act on.
    if frozen < issued:
        _fail(
            "first_calendar_week.decision_date precedes the completion notification; a start "
            "receipt cannot back-fill a week that happened before the decision"
        )
    if (frozen - issued).days > _MAX_DAYS_AHEAD:
        _fail("first_calendar_week.decision_date is too far after the completion notification")
    if frozen.weekday() != _CANONICAL_DECISION_WEEKDAY:
        _fail(
            "first_calendar_week.decision_date is not a canonical decision week for this track; "
            "the anchor sets the weekday of all twenty-six weeks and this track decides on Mondays"
        )
    expected_window = window_containing_week(first["calendar_week_index"])["window_id"]
    if first["window_id"] != expected_window:
        _fail("start receipt window_id does not match the canonical 26-week clock")
    return dict(candidate)


def _private_root(root: str | Path) -> Path:
    path = _path_like(root, "diagnostic private root")
    if not path.is_absolute():
        _fail("diagnostic private root must be absolute")
    path = path.resolve()
    try:
        reject_nonprivate_output_path(path)
    except PrivatePathError as exc:
        raise DiagnosticStartReceiptError(f"diagnostic private root is not private: {path}") from exc
    return path


def _receipt_path(root: Path) -> Path:
    candidate = (root / RECEIPT_FILENAME).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise DiagnosticStartReceiptError("start receipt escapes its private root") from exc
    try:
        reject_nonprivate_output_path(candidate)
    except PrivatePathError as exc:
        raise DiagnosticStartReceiptError(f"start receipt is not private: {candidate}") from exc
    return candidate


def load_start_receipt(
    root: str | Path = DEFAULT_ROOT, *, verify_design_against_disk: bool = True
) -> dict[str, Any] | None:
    """Return the stored receipt, or ``None`` when the clock has never been opened."""

    path = _receipt_path(_private_root(root))
    if not path.exists():
        return None
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise DiagnosticStartReceiptError(f"cannot read the start receipt: {path}") from exc
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiagnosticStartReceiptError("the start receipt is not UTF-8 JSON") from exc
    if not isinstance(value, dict):
        _fail("the start receipt must be an object")
    if canonical_json_bytes(value) != payload:
        _fail("the start receipt is not canonical JSON")
    return validate_start_receipt(value, verify_design_against_disk=verify_design_against_disk)


def start_receipt_sha256(receipt: Mapping[str, Any]) -> str:
    """The digest the lifecycle register records so authorization stays provable."""

    return artifact_sha256(dict(receipt))


def issue_start_receipt(
    *,
    diagnostic_epoch: str,
    completion_notification: Mapping[str, Any],
    first_decision_date: str,
    as_of_date: str,
    root: str | Path = DEFAULT_ROOT,
) -> dict[str, Any]:
    """Open the clock once, on a real notification, and never silently re-anchor it."""

    receipt = build_start_receipt(
        diagnostic_epoch=diagnostic_epoch,
        completion_notification=completion_notification,
        first_decision_date=first_decision_date,
        as_of_date=as_of_date,
    )
    store_root = _private_root(root)
    path = _receipt_path(store_root)

    existing = load_start_receipt(store_root)
    if existing is not None:
        if start_receipt_sha256(existing) == start_receipt_sha256(receipt):
            return {
                "status": "idempotent",
                "receipt": existing,
                "receipt_sha256": start_receipt_sha256(existing),
            }
        _fail("a different start receipt already anchors this diagnostic clock")

    payload = canonical_json_bytes(receipt)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create rather than check-then-replace: two issuers racing must not
    # both be told they won while only one anchor survives.
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        existing = load_start_receipt(store_root)
        if existing is not None and start_receipt_sha256(existing) == start_receipt_sha256(receipt):
            return {
                "status": "idempotent",
                "receipt": existing,
                "receipt_sha256": start_receipt_sha256(existing),
            }
        _fail("a different start receipt already anchors this diagnostic clock")
        raise AssertionError("unreachable")
    except OSError as exc:
        raise DiagnosticStartReceiptError(f"cannot write the start receipt: {path}") from exc
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        try:
            path.unlink()
        except OSError:
            pass
        raise DiagnosticStartReceiptError(f"cannot write the start receipt: {path}") from exc
    return {"status": "issued", "receipt": receipt, "receipt_sha256": start_receipt_sha256(receipt)}


def assert_first_week_is_authorized(
    record: Mapping[str, Any], *, root: str | Path = DEFAULT_ROOT
) -> dict[str, Any]:
    """Gate week 1 on a receipt that actually froze this week.

    A receipt that exists is not enough: it must have frozen *this* decision date,
    *this* epoch and week 1 itself, so an operator cannot open the clock on one
    week and then persist a different one against it.
    """

    receipt = load_start_receipt(root)
    if receipt is None:
        _fail(
            "the 26-week diagnostic clock has no start receipt; week 1 cannot be written "
            "from a date, a component completion, an account seeding, or a commit"
        )
    assert receipt is not None
    incoming = _mapping(record, "weekly_record")
    first = receipt["first_calendar_week"]
    if incoming.get("calendar_week_index") != first["calendar_week_index"]:
        _fail("week 1 does not match the calendar week frozen by the start receipt")
    if incoming.get("decision_date") != first["decision_date"]:
        _fail("week 1 decision date does not match the start receipt")
    if incoming.get("window_id") != first["window_id"]:
        _fail("week 1 window does not match the start receipt")
    if incoming.get("diagnostic_epoch") != receipt["diagnostic_epoch"]:
        _fail("week 1 diagnostic epoch does not match the start receipt")
    return receipt


def assert_clock_authorization_still_holds(
    recorded_sha256: object,
    *,
    root: str | Path = DEFAULT_ROOT,
    first_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Re-check, on every later write, that the anchor is still the one we counted from.

    Week 1's gate proves the clock was opened legitimately. This proves it has not
    been re-opened, deleted, or swapped since — which is the part that makes a
    26-week claim auditable rather than merely well-formed.
    """

    # An ongoing read must not re-hash the living design document; see validate_start_receipt.
    receipt = load_start_receipt(root, verify_design_against_disk=False)
    if receipt is None:
        _fail("the start receipt that opened this diagnostic clock is missing")
    assert receipt is not None
    if not isinstance(recorded_sha256, str) or _SHA256.fullmatch(recorded_sha256) is None:
        _fail("the lifecycle register does not record a start receipt digest")
    if start_receipt_sha256(receipt) != recorded_sha256:
        _fail("the start receipt no longer matches the one this diagnostic clock was opened with")
    if first_record is not None:
        # A digest match alone only proves the register and the receipt were
        # updated together. Re-anchoring updates both, so the identity has to be
        # re-checked against the weeks actually counted, not just the pointer.
        frozen = receipt["first_calendar_week"]
        if first_record.get("decision_date") != frozen["decision_date"]:
            _fail(
                "the start receipt freezes a different week 1 than the one this clock counted; "
                "the anchor was moved underneath a running count"
            )
        if first_record.get("diagnostic_epoch") != receipt["diagnostic_epoch"]:
            _fail("the start receipt names a different diagnostic epoch than the counted weeks")
    return receipt


__all__ = [
    "DEFAULT_ROOT",
    "DESIGN_AUTHORITY_RELATIVE_PATH",
    "DESIGN_CONTRACT_ANCHOR",
    "DiagnosticStartReceiptError",
    "RECEIPT_BOUNDARY",
    "RECEIPT_FILENAME",
    "assert_clock_authorization_still_holds",
    "assert_first_week_is_authorized",
    "build_start_receipt",
    "design_authority_sha256",
    "design_contract_block",
    "issue_start_receipt",
    "load_start_receipt",
    "start_receipt_sha256",
    "validate_start_receipt",
]
