#!/usr/bin/env python3
"""Run one unittest command with a hard deadline and machine-verifiable evidence."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from importlib.util import find_spec
from dataclasses import dataclass
from pathlib import Path

import verification_receipt as receipts

ROOT = Path(__file__).resolve().parent.parent
FULL_MAX_SECONDS = 860
FOCUSED_DEFAULT_SECONDS = 300
# A focused command normally gets the short default. A known slow, still-focused
# pack may opt in through the launcher under its separately approved ceiling.
FOCUSED_MAX_SECONDS = 1300
TIMEOUT_EXIT = 124
INVALID_EVIDENCE_EXIT = 125
DEPENDENCY_EXIT = 126
# These flags do not select or skip tests.  They make the one official full
# process quieter on green, stop immediately on the first real red, and retain
# timing evidence for the next test-only optimization pass.  They live here
# rather than in the ledger because the parallel driver applies them per worker
# and the ledger owns the run: one definition, no pair to keep in agreement.
FULL_PACK_RUNTIME_ARGS = ("-b", "-f", "--durations", "25")
REQUIRED_TEST_MODULES_BY_LANE = {
    "a_short": (
        "akshare", "jsonschema", "numpy", "openpyxl", "pandas", "requests", "tqdm", "tushare",
    ),
    "us_short": (
        "jsonschema", "numpy", "openpyxl", "pandas", "requests", "tqdm",
    ),
}
_RAN_TESTS = re.compile(r"\bRan\s+(\d+)\s+tests?\s+in\b")


@dataclass(frozen=True)
class Result:
    status: str
    exit_code: int
    tests: int | None
    elapsed_seconds: float
    output: str


def external_test_dependency_error(lane: str) -> str | None:
    """Return missing dependencies required by one lane's full-pack entry."""
    try:
        required_modules = REQUIRED_TEST_MODULES_BY_LANE[lane]
    except KeyError as exc:
        raise ValueError(f"unknown lane for external test dependencies: {lane}") from exc
    missing = [name for name in required_modules if find_spec(name) is None]
    if not missing:
        return None
    return "required external test modules unavailable: " + ", ".join(missing)


def _stop_owned_tree(process: subprocess.Popen[str]) -> None:
    """Stop only the process tree created by this runner."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    else:  # pragma: no cover - Windows is the project host
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_command(
    command: list[str],
    timeout_seconds: int,
    *,
    cwd: Path = ROOT,
    extra_env: dict[str, str] | None = None,
) -> Result:
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    child_env = os.environ.copy()
    if extra_env:
        child_env.update(extra_env)
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        start_new_session=os.name != "nt",
        env=child_env,
    )
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as initial_timeout:
        timed_out = True
        partial_output = initial_timeout.output or ""
        try:
            _stop_owned_tree(process)
        except (subprocess.TimeoutExpired, OSError):
            pass
        try:
            output, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired as cleanup_timeout:
            process.kill()
            try:
                output, _ = process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                output = cleanup_timeout.output or partial_output
    elapsed = time.monotonic() - started
    matches = _RAN_TESTS.findall(output or "")
    tests = int(matches[-1]) if matches else None
    if timed_out:
        return Result("TIMEOUT", TIMEOUT_EXIT, tests, elapsed, output or "")
    if process.returncode != 0:
        return Result("FAIL", int(process.returncode), tests, elapsed, output or "")
    if tests is None or tests <= 0:
        return Result("UNKNOWN", INVALID_EVIDENCE_EXIT, None, elapsed, output or "")
    return Result("PASS", 0, tests, elapsed, output or "")


def run_unittest(
    args: list[str],
    timeout_seconds: int,
    *,
    cwd: Path = ROOT,
    extra_env: dict[str, str] | None = None,
) -> Result:
    return run_command(
        [sys.executable, "-m", "unittest", *args],
        timeout_seconds,
        cwd=cwd,
        extra_env=extra_env,
    )


def _parse(argv: list[str]) -> tuple[str, int, list[str]]:
    if "--" not in argv:
        raise ValueError("usage: bounded_unittest.py <focused|full> <timeout-seconds> -- <unittest args>")
    split = argv.index("--")
    head, unittest_args = argv[:split], argv[split + 1:]
    if len(head) != 2 or not unittest_args:
        raise ValueError("usage: bounded_unittest.py <focused|full> <timeout-seconds> -- <unittest args>")
    tier, raw_timeout = head
    if tier not in {"focused", "full"}:
        raise ValueError("tier must be focused or full")
    timeout = int(raw_timeout)
    maximum = FOCUSED_MAX_SECONDS if tier == "focused" else FULL_MAX_SECONDS
    if timeout <= 0 or timeout > maximum:
        raise ValueError(f"{tier} timeout must be 1..{maximum} seconds")
    return tier, timeout, unittest_args


NESTED_RUN_MARKER = "STOCK_BOUNDED_UNITTEST_ACTIVE"
DOCUMENT_ONLY_FOCUSED_ARGS = frozenset({
    "tests.test_a_short_preflight.PinnedStockPythonSmoke",
    "tests.test_readme_route_row_length",
    "tests.test_route_doc_ledger_status_consistency",
    "tests.test_doc_governance_guard",
})


def _is_document_only_focused_run(unittest_args: list[str]) -> bool:
    """Recognise only the project's exact document-process verification command."""
    return (
        len(unittest_args) == len(DOCUMENT_ONLY_FOCUSED_ARGS)
        and set(unittest_args) == DOCUMENT_ONLY_FOCUSED_ARGS
    )


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # A run launched from inside another bounded run must never overwrite the
    # acceptance receipt.  Several tests legitimately spawn this launcher
    # (the jsonschema self-check, the preflight guard, this tool's own tests);
    # each of those wrote a bundle-less receipt over the real one, which made
    # `.githooks/pre-commit` destroy the very evidence it then demanded and
    # left every bundle-requiring commit permanently blocked.  The marker is
    # set before the child is spawned, so nesting at any depth is covered
    # without touching a single call site.
    nested = os.environ.get(NESTED_RUN_MARKER) == "1"
    os.environ[NESTED_RUN_MARKER] = "1"
    try:
        pin_error = receipts.pinned_python_error()
        if pin_error:
            raise ValueError(pin_error)
        tier, timeout, unittest_args = _parse(argv)
        document_only = tier == "focused" and _is_document_only_focused_run(unittest_args)
        state_before = (
            receipts.collect_code_state()
            if tier == "focused" and not nested and not document_only
            else None
        )
        result = run_unittest(unittest_args, timeout)
    except (ValueError, OSError) as exc:
        print(f"[bounded-unittest] REFUSED: {exc}")
        return 2
    if result.output:
        print(result.output, end="" if result.output.endswith("\n") else "\n")
    receipt = None
    receipt_error = None
    if tier == "focused" and result.status == "PASS" and not nested and not document_only:
        try:
            state_after = receipts.collect_code_state()
            if receipts.fingerprint(state_before or {}) != receipts.fingerprint(state_after):
                receipt_error = "code state changed during focused run"
            else:
                receipt = receipts.write_focused_receipt(
                    result_status=result.status,
                    result_exit_code=result.exit_code,
                    tests=result.tests,
                    elapsed_seconds=result.elapsed_seconds,
                    timeout_seconds=timeout,
                    unittest_args=unittest_args,
                    state=state_after,
                    path=receipts.RECEIPT_PATH,
                )
                if receipt is None:
                    receipt_error = "focused result did not contain positive terminal test evidence"
        except OSError as exc:
            receipt_error = f"could not write focused acceptance receipt: {exc}"
    reported_status = "FAIL" if receipt_error else result.status
    reported_exit = 2 if receipt_error else result.exit_code
    count = str(result.tests) if result.tests is not None else "UNKNOWN"
    print(
        f"[bounded-unittest] RESULT tier={tier} status={reported_status} "
        f"exit={reported_exit} tests={count} elapsed={result.elapsed_seconds:.1f}s "
        f"deadline={timeout}s"
    )
    if nested and tier == "focused" and result.status == "PASS":
        # Say so rather than skip silently: an unexplained missing receipt is
        # its own trap for whoever is trying to satisfy the pre-commit gate.
        print("[bounded-unittest] NESTED - acceptance receipt left untouched")
    elif document_only and result.status == "PASS" and not nested:
        print("[bounded-unittest] DOC_ONLY - acceptance receipt left untouched")
    if receipt_error:
        print(f"[bounded-unittest] REFUSED - {receipt_error}")
    elif receipt is not None:
        bundles = ",".join(receipt["bundles"]) or "none"
        print(
            f"[bounded-unittest] FOCUSED_RECEIPT token={receipts.receipt_token(receipt)} "
            f"tests={receipt['tests']} bundles={bundles} "
            f"python={receipt['python_executable']}"
        )
    return reported_exit


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
