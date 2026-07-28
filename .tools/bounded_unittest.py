#!/usr/bin/env python3
"""Run one unittest command with a hard deadline and machine-verifiable evidence."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FULL_MAX_SECONDS = 1300
FOCUSED_DEFAULT_SECONDS = 300
# A focused command normally gets the short default. A known slow, still-focused
# pack may opt in through the launcher, but never exceed the full-run ceiling.
FOCUSED_MAX_SECONDS = FULL_MAX_SECONDS
TIMEOUT_EXIT = 124
INVALID_EVIDENCE_EXIT = 125
_RAN_TESTS = re.compile(r"\bRan\s+(\d+)\s+tests?\s+in\b")


@dataclass(frozen=True)
class Result:
    status: str
    exit_code: int
    tests: int | None
    elapsed_seconds: float
    output: str


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


def run_command(command: list[str], timeout_seconds: int, *, cwd: Path = ROOT) -> Result:
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    child_env = os.environ.copy()
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


def run_unittest(args: list[str], timeout_seconds: int, *, cwd: Path = ROOT) -> Result:
    return run_command([sys.executable, "-m", "unittest", *args], timeout_seconds, cwd=cwd)


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


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        tier, timeout, unittest_args = _parse(argv)
        result = run_unittest(unittest_args, timeout)
    except (ValueError, OSError) as exc:
        print(f"[bounded-unittest] REFUSED: {exc}")
        return 2
    if result.output:
        print(result.output, end="" if result.output.endswith("\n") else "\n")
    count = str(result.tests) if result.tests is not None else "UNKNOWN"
    print(
        f"[bounded-unittest] RESULT tier={tier} status={result.status} "
        f"exit={result.exit_code} tests={count} elapsed={result.elapsed_seconds:.1f}s "
        f"deadline={timeout}s"
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
