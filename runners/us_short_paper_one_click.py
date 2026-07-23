#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single-command US-short weekly paper-account runner.

This is the operator-facing paper path.  It delegates paper state to the
head-bound model-paper store, lets the capstone derive the exact Pass2 budget
inside the same process, and then runs the complete provider-backed source
pipeline once.  A blank account is never recreated per week: the capstone
derives its account input from the mature paper adapter.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path  # noqa: E402
from runners.us_short_weekly_capstone import (  # noqa: E402
    WeeklyCapstoneError,
    resolve_capstone_context,
    run_weekly_capstone,
)


DEFAULT_PRIVATE_ROOT = ROOT / "state" / "us_short"
DEFAULT_STATE_DIR = ROOT / "state" / "us_short"
TEMPLATE_SOURCE = ROOT / "schemas" / "examples" / "us_short_weekend_batch4_context_packet.empty.example.json"


class PaperOneClickError(RuntimeError):
    """The one-click paper launcher could not prepare or run its private inputs."""


_SECRET_ENV_NAME = re.compile(r"(?:key|token|secret|password)", re.IGNORECASE)
_INLINE_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password)\s*([=:])\s*([^\s,;]+)"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _redact_text(value: str) -> str:
    """Keep diagnostics useful without persisting environment secrets or inline credentials."""
    redacted = value
    for name, secret in os.environ.items():
        if _SECRET_ENV_NAME.search(name) and len(secret) >= 4:
            redacted = redacted.replace(secret, "[REDACTED]")
    return _INLINE_SECRET.sub(r"\1\2[REDACTED]", redacted)


class _SanitizingTee:
    """Mirror one stream to a private log while leaving console behavior unchanged."""

    def __init__(self, console: TextIO, log: TextIO) -> None:
        self._console = console
        self._log = log

    def write(self, value: str) -> int:
        if value:
            self._log.write(_redact_text(value))
            self._log.flush()
        return self._console.write(value)

    def flush(self) -> None:
        self._log.flush()
        self._console.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._console, name)


class _RunDiagnostics:
    """Private, append-first diagnostics for a single one-click invocation.

    ``events.jsonl`` and ``heartbeat.json`` are written before/after every
    capstone stage.  If Python is externally killed, they still identify the
    last durable stage; normal exceptions additionally write ``failure.json``
    with a redacted traceback.
    """

    def __init__(self, *, private_root: Path, diagnostics_dir: Path | None = None) -> None:
        root = diagnostics_dir or (
            private_root / "weekly_private" / "_run_diagnostics"
            / f"paper_one_click_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{os.getpid()}_{uuid4().hex[:8]}"
        )
        self.root = root.resolve()
        try:
            reject_nonprivate_output_path(self.root)
        except PrivatePathError as exc:
            raise PaperOneClickError(f"diagnostics directory rejected: {self.root}") from exc
        self.root.mkdir(parents=True, exist_ok=False)
        self._events_path = self.root / "events.jsonl"
        self._heartbeat_path = self.root / "heartbeat.json"
        self._failure_path = self.root / "failure.json"
        self._stdout = (self.root / "stdout.log").open("w", encoding="utf-8", newline="")
        self._stderr = (self.root / "stderr.log").open("w", encoding="utf-8", newline="")

    def stream_pair(self, stdout: TextIO, stderr: TextIO) -> tuple[TextIO, TextIO]:
        return _SanitizingTee(stdout, self._stdout), _SanitizingTee(stderr, self._stderr)

    def emit(self, event: dict[str, Any]) -> None:
        """Best-effort diagnostics must never alter the outcome of a paper run."""
        try:
            payload = {
                "recorded_at": _utc_now(),
                "process_id": os.getpid(),
                **event,
            }
            line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
            with self._events_path.open("a", encoding="utf-8", newline="") as handle:
                handle.write(_redact_text(line))
                handle.flush()
                os.fsync(handle.fileno())
            _write_json(self._heartbeat_path, payload)
        except (OSError, TypeError, ValueError):
            return

    def fail(self, exc: BaseException) -> None:
        details = {
            "schema_name": "us_short_paper_one_click_failure",
            "schema_version": "1.0.0",
            "recorded_at": _utc_now(),
            "process_id": os.getpid(),
            "error_type": type(exc).__name__,
            "message": _redact_text(str(exc) or type(exc).__name__),
            "traceback": _redact_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__))),
        }
        try:
            _write_json(self._failure_path, details)
        except OSError:
            pass
        self.emit({"event": "runner_failed", "error_type": type(exc).__name__})

    def close(self) -> None:
        self._stdout.close()
        self._stderr.close()


def _emit_diagnostic_event(
    diagnostic_event: Callable[[dict[str, Any]], None] | None,
    event: dict[str, Any],
) -> None:
    """An optional observer is not allowed to change a paper-run outcome."""
    if diagnostic_event is None:
        return
    try:
        diagnostic_event(event)
    except Exception:
        return


def _parse_now_et(raw: str) -> datetime:
    try:
        value = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("now-et must be YYYY-MM-DDTHH:MM:SS in Eastern Time") from exc
    return value


def _current_now_et() -> datetime:
    return datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None)


def _private_root(path: Path) -> Path:
    # The capstone root itself is ``state/us_short`` (the ignored private
    # families are its child directories).  The capstone and the generated
    # input directory perform the actual private-path checks at write time.
    return path.resolve()


def _canonical_source_state_dir(path: Path) -> Path:
    """Keep provider-backed source artifacts in this checkout's canonical state root.

    ``private_root`` is the isolation boundary for the paper account and weekly
    outputs.  It is deliberately *not* the source-artifact root: the universe
    runner binds its candidate artifact to ``state/us_short`` of the active
    checkout before any provider request.  A runtest capsule gets that
    canonical path from its cloned checkout automatically; callers must not
    repoint it at the private capsule directory.
    """
    expected = DEFAULT_STATE_DIR.resolve()
    actual = Path(path).resolve()
    if actual != expected:
        raise PaperOneClickError(
            "state-dir must be this checkout's canonical state/us_short root; "
            "use --private-root to isolate paper outputs in a runtest capsule"
        )
    return expected


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def _prepare_paper_inputs(*, private_root: Path, decision_date: str) -> tuple[Path, Path]:
    if not TEMPLATE_SOURCE.is_file():
        raise PaperOneClickError(f"missing tracked paper template: {TEMPLATE_SOURCE}")
    input_root = private_root / "weekly_private" / "_run_inputs"
    try:
        reject_nonprivate_output_path(input_root)
    except PrivatePathError as exc:
        raise PaperOneClickError(f"paper input directory rejected: {input_root}") from exc

    template_path = input_root / "paper_batch4_template.json"
    account_path = input_root / "paper_account_state.adapter.json"
    template = json.loads(TEMPLATE_SOURCE.read_text(encoding="utf-8"))
    _write_json(template_path, template)

    # This placeholder is never a sizing input.  The first local capstone
    # stage replaces it with the head-bound adapter after it has matured the
    # prior paper decision in memory.  On later runs it preserves the prior
    # adapter until that replacement; it never resets cash or positions.
    if not account_path.exists():
        _write_json(account_path, {"pending_model_paper_adapter": True, "decision_date": decision_date})
    return template_path, account_path


def run_one_click(
    *,
    now_et: datetime,
    private_root: Path = DEFAULT_PRIVATE_ROOT,
    state_dir: Path = DEFAULT_STATE_DIR,
    momentum_top_k: int = 200,
    provider_pace_seconds: float = 1.0,
    diagnostic_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict:
    private_root = _private_root(private_root)
    if type(momentum_top_k) is not int or not 1 <= momentum_top_k <= 250:
        raise PaperOneClickError("momentum-top-k must be an integer from 1 through 250")
    if provider_pace_seconds < 0:
        raise PaperOneClickError("provider-pace-seconds must be nonnegative")
    state_dir = _canonical_source_state_dir(state_dir)

    # Resolve the canonical week before writing any generated input.  This is
    # the same resolver used by the capstone, so the wrapper cannot drift to a
    # different decision date.
    placeholder_template = private_root / "weekly_private" / "_run_inputs" / "paper_batch4_template.json"
    placeholder_account = private_root / "weekly_private" / "_run_inputs" / "paper_account_state_pending.json"
    context = resolve_capstone_context(
        now_et=now_et,
        private_root=private_root,
        batch4_template_path=placeholder_template,
        account_state_path=placeholder_account,
        authorized_momentum_top_k=momentum_top_k,
        calendar_path=ROOT / "presets" / "us_short_market_calendar_2026_2027.json",
        confirm_user_authorization=True,
        state_dir=state_dir,
        sample_root=ROOT,
    )
    _emit_diagnostic_event(diagnostic_event, {
        "event": "capstone_context_resolved",
        "decision_date": context.decision_date,
        "price_basis_date": context.price_basis_date,
    })
    template_path, account_path = _prepare_paper_inputs(
        private_root=private_root, decision_date=context.decision_date)
    _emit_diagnostic_event(diagnostic_event, {"event": "paper_inputs_prepared", "decision_date": context.decision_date})

    print(
        f"[US-SHORT PAPER] decision_date={context.decision_date} price_basis_date={context.price_basis_date}",
        file=sys.stderr,
    )
    print(f"[US-SHORT PAPER] python={sys.executable}", file=sys.stderr)
    _emit_diagnostic_event(diagnostic_event, {"event": "capstone_started", "decision_date": context.decision_date})
    summary = run_weekly_capstone(
        now_et=now_et,
        private_root=private_root,
        batch4_template_path=template_path,
        account_state_path=account_path,
        authorized_momentum_top_k=momentum_top_k,
        authorized_pass2_call_budget=None,
        calendar_path=ROOT / "presets" / "us_short_market_calendar_2026_2027.json",
        confirm_user_authorization=True,
        dry_run=False,
        provider_pace_seconds=provider_pace_seconds,
        state_dir=state_dir,
        sample_root=ROOT,
        auto_authorize_pass2_budget=True,
        model_paper_store_root=private_root / "model_paper_private",
        model_paper_run_account_mode="paper_only",
        diagnostic_event=diagnostic_event,
    )
    _emit_diagnostic_event(diagnostic_event, {"event": "capstone_completed", "decision_date": context.decision_date})
    return {
        **summary,
        "paper_account_mode": "paper_only",
        "manual_account_read": False,
        "automatic_broker_execution": False,
        "ship_gate_eligible": False,
        "paper_account_state_path": str(account_path),
        "model_paper_store_root": str(private_root / "model_paper_private"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="US-short weekly one-click paper-account runner")
    parser.add_argument("--now-et", type=_parse_now_et, default=None)
    parser.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    parser.add_argument(
        "--state-dir", type=Path, default=DEFAULT_STATE_DIR,
        help="must remain this checkout's canonical state/us_short root; use --private-root for isolation",
    )
    parser.add_argument("--momentum-top-k", type=int, default=200)
    parser.add_argument("--provider-pace-seconds", type=float, default=1.0)
    parser.add_argument("--diagnostics-dir", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    diagnostics: _RunDiagnostics | None = None
    original_stdout, original_stderr = sys.stdout, sys.stderr
    try:
        diagnostics = _RunDiagnostics(
            private_root=_private_root(args.private_root), diagnostics_dir=args.diagnostics_dir,
        )
        sys.stdout, sys.stderr = diagnostics.stream_pair(original_stdout, original_stderr)
        diagnostics.emit({"event": "runner_started"})
        print(f"[US-SHORT PAPER] diagnostics={diagnostics.root}", file=sys.stderr)
        summary = run_one_click(
            now_et=args.now_et or _current_now_et(),
            private_root=args.private_root,
            state_dir=args.state_dir,
            momentum_top_k=args.momentum_top_k,
            provider_pace_seconds=args.provider_pace_seconds,
            diagnostic_event=diagnostics.emit,
        )
    except BaseException as exc:  # noqa: BLE001 - diagnostics must preserve every failure class
        if diagnostics is not None:
            diagnostics.fail(exc)
        print(f"ERROR: {type(exc).__name__}: {_redact_text(str(exc) or type(exc).__name__)}", file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else (2 if isinstance(exc, (PaperOneClickError, WeeklyCapstoneError)) else 1)
    else:
        diagnostics.emit({"event": "runner_completed"})
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        sys.stdout, sys.stderr = original_stdout, original_stderr
        if diagnostics is not None:
            diagnostics.close()


if __name__ == "__main__":
    raise SystemExit(main())
