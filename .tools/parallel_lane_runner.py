#!/usr/bin/env python3
"""Run one lane's full pack as concurrent module-level unittest processes.

What the 860s full-pack ceiling actually bounds is wall clock, and the serial
pack spends it on one core of a sixteen-core host.  This driver leaves every
selection and evidence rule alone -- the caller's discovery selector, the fixed
``-b -f --durations 25`` runtime flags, the "only PASS is recorded" ledger
contract -- and changes only how many processes carry the same work.

Two properties are what make the aggregate citable as one full pack:

* the module list and the expected total are derived from the caller's own
  discovery arguments, never from a list maintained in this file; and
* a green is reported only when the case counts the workers actually ran sum to
  that discovered total.  A module the scheduler silently dropped therefore
  produces a FAIL, not a smaller green.

The count equality is a precondition for reporting PASS, not a red/green
criterion of its own: a worker stopped early by ``-f`` legitimately runs fewer
cases than were discovered, and that run is already a FAIL for the ordinary
reason.
"""
from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
import sys
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from bounded_unittest import (
    FULL_PACK_RUNTIME_ARGS,
    INVALID_EVIDENCE_EXIT,
    NESTED_RUN_MARKER,
    Result,
    TIMEOUT_EXIT,
    run_command,
)

ROOT = Path(__file__).resolve().parent.parent
WORKERS = 8
STATE_DIR = ROOT / ".tools" / "state"
DURATIONS_PATH = STATE_DIR / "parallel_module_durations.json"
RUNS_DIR = STATE_DIR / "runs"
# `unittest` builds a placeholder test under this module name when a test file
# cannot be imported.  Treating one as an ordinary module would hand a worker a
# name that is not importable, so discovery refuses instead.
LOADER_FAILURE_MODULE = "unittest.loader"
_DURATION_LINE = re.compile(r"^\s*(\d+\.\d+)s\s+(\S.*?)\s*$", re.MULTILINE)
# A helper that takes one of these holds it against every other process on the
# same tree, so its dependents have to run one at a time.
_CROSS_PROCESS_LOCK = re.compile(r"msvcrt\.locking|fcntl\.(?:flock|lockf)")

_DISCOVERY_SNIPPET = r"""
import json, sys, unittest

start_dir, pattern, top_level = sys.argv[1], sys.argv[2], sys.argv[3] or None
counts = {}


def walk(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            walk(item)
        else:
            name = type(item).__module__
            counts[name] = counts.get(name, 0) + 1


loader = unittest.defaultTestLoader
before = list(sys.path)
walk(loader.discover(start_dir, pattern=pattern, top_level_dir=top_level))
# Discovery names modules relative to the top level directory it resolved, and
# reaches them by putting that directory on sys.path.  A worker given only the
# name cannot import it without the same entries, and adding a prefix instead
# would import a DIFFERENT module object than the serial run does.
json.dump(
    {
        "counts": counts,
        "path_entries": [entry for entry in sys.path if entry not in before],
        "errors": [str(err) for err in (getattr(loader, "errors", None) or [])],
    },
    sys.stdout,
)
"""


@dataclass(frozen=True)
class ModuleOutcome:
    """One worker's verdict on one test module."""

    module: str
    status: str
    exit_code: int
    tests: int | None
    elapsed_seconds: float
    output: str
    log_path: str | None = None


def parse_discovery_args(unittest_args: list[str]) -> tuple[str, str, str]:
    """Read the caller's own discovery selector rather than restating one here.

    Anything beyond the discovery options is refused: this driver has to
    reproduce the caller's selection exactly, and a flag it does not understand
    could narrow or widen that selection without it noticing.
    """
    if not unittest_args or unittest_args[0] != "discover":
        raise ValueError("parallel full-pack requires unittest `discover` arguments")
    start_dir, pattern, top_level = ".", "test*.py", ""
    index = 1
    options = {
        "-s": "start", "--start-directory": "start",
        "-p": "pattern", "--pattern": "pattern",
        "-t": "top", "--top-level-directory": "top",
    }
    while index < len(unittest_args):
        flag = unittest_args[index]
        target = options.get(flag)
        if target is None:
            raise ValueError(f"parallel full-pack cannot reproduce discovery option {flag!r}")
        if index + 1 >= len(unittest_args):
            raise ValueError(f"discovery option {flag!r} is missing its value")
        value = unittest_args[index + 1]
        if target == "start":
            start_dir = value
        elif target == "pattern":
            pattern = value
        else:
            top_level = value
        index += 2
    return start_dir, pattern, top_level


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def discover_modules(unittest_args: list[str], *, timeout_seconds: int = 300,
                     cwd: Path = ROOT) -> tuple[dict[str, int], list[str]]:
    """Return each module's case count plus the sys.path entries discovery needed."""
    start_dir, pattern, top_level = parse_discovery_args(unittest_args)
    result = run_command(
        [sys.executable, "-c", _DISCOVERY_SNIPPET, start_dir, pattern, top_level],
        timeout_seconds,
        cwd=cwd,
        extra_env={NESTED_RUN_MARKER: "1"},
    )
    if result.exit_code != 0 and result.status != "UNKNOWN":
        raise ValueError(f"discovery failed (exit {result.exit_code}): {result.output.strip()[-800:]}")
    try:
        payload = json.loads(result.output)
    except json.JSONDecodeError as exc:
        raise ValueError(f"discovery produced no usable module map: {exc}") from exc
    errors = payload.get("errors") or []
    if errors:
        raise ValueError(f"discovery reported loader errors: {errors[0][:400]}")
    counts = {str(name): int(total) for name, total in (payload.get("counts") or {}).items()}
    if LOADER_FAILURE_MODULE in counts:
        raise ValueError(
            "discovery found unimportable test files; a parallel run cannot dispatch them by name"
        )
    if not counts:
        raise ValueError("discovery found no test modules for the given selector")
    path_entries = [str(entry) for entry in (payload.get("path_entries") or [])]
    return counts, path_entries


def matching_module_files(start_dir: str, pattern: str, cwd: Path = ROOT) -> list[Path]:
    """Count the selector's files independently of the loader that will run them.

    Discovery reports both the modules to dispatch and the total the count gate
    checks against.  An under-reporting discovery therefore shrinks both sides at
    once, and the gate cannot see it -- it is comparing a number with itself.
    The filesystem is the one side that does not come from the loader.

    Descent stops at directories without ``__init__.py`` because that is what
    discovery itself walks; counting files it would never reach would make this
    anchor disagree for a reason that is not a defect.
    """
    root = Path(start_dir)
    if not root.is_absolute():
        root = Path(cwd) / root
    found: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        if not directory.is_dir():
            continue
        for child in sorted(directory.iterdir()):
            if child.is_dir():
                if (child / "__init__.py").is_file():
                    pending.append(child)
            elif fnmatch.fnmatch(child.name, pattern):
                found.append(child)
    return found


def _files_against_discovery(counts, path_entries: list[str], start_dir: str, pattern: str,
                             cwd: Path = ROOT) -> tuple[list[Path], dict[Path, list[str]]]:
    """Check discovery against the filesystem: what it missed, and what it doubled.

    Counting module names against file names would be wrong twice over -- two
    packages may hold the same basename, and one file may legitimately be
    reported under more than one name.  Resolving each name back to its file is
    the comparison that means something.
    """
    resolved: dict[Path, list[str]] = {}
    for name in counts:
        path = _module_path(name, path_entries)
        if path is not None:
            resolved.setdefault(path.resolve(), []).append(name)
    on_disk = matching_module_files(start_dir, pattern, cwd)
    unreported = [path for path in on_disk if path.resolve() not in resolved]
    duplicated = {path: names for path, names in resolved.items() if len(names) > 1}
    return unreported, duplicated


def _module_path(name: str, path_entries: list[str]) -> Path | None:
    """Resolve a discovered module name to its file, the way discovery reached it."""
    relative = Path(*name.split("."))
    for entry in path_entries:
        module = Path(entry) / relative.with_suffix(".py")
        if module.is_file():
            return module
        package = Path(entry) / relative / "__init__.py"
        if package.is_file():
            return package
    return None


def _imported_names(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def serial_tail_modules(modules, path_entries: list[str]) -> set[str]:
    """Modules that reach a cross-process lock, and so must not run concurrently.

    A lock taken on a fixed shared path is invisible for as long as only one
    process ever runs tests: it is acquired and released with nobody to contend
    with.  Put eight processes on the same tree and the same helper starts
    refusing, which reads as a red test rather than as what it is.  The set is
    derived from the sources rather than listed here, because a hand-kept list
    of "these must stay serial" goes stale the first time somebody reuses the
    helper somewhere new.
    """
    verdicts: dict[str, bool] = {}

    def reaches(path: Path | None, stack: set[str]) -> bool:
        if path is None:
            return False  # resolved outside the discovered tree: stdlib or installed
        key = str(path)
        if key in verdicts:
            return verdicts[key]
        if key in stack:
            return False
        stack.add(key)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # Cannot rule it out, so do not run it concurrently.
            stack.discard(key)
            verdicts[key] = True
            return True
        verdict = bool(_CROSS_PROCESS_LOCK.search(source))
        if not verdict:
            verdict = any(
                reaches(_module_path(name, path_entries), stack)
                for name in sorted(_imported_names(source))
            )
        stack.discard(key)
        verdicts[key] = verdict
        return verdict

    return {
        name for name in modules
        if reaches(_module_path(name, path_entries), set())
    }


def _load_durations(lane: str, path: Path = DURATIONS_PATH) -> dict[str, float]:
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    lane_durations = stored.get(lane)
    if not isinstance(lane_durations, dict):
        return {}
    return {
        str(module): float(seconds)
        for module, seconds in lane_durations.items()
        if isinstance(seconds, (int, float))
    }


def _store_durations(lane: str, observed: dict[str, float], path: Path = DURATIONS_PATH) -> None:
    """Let the next run schedule from measurement instead of a hand-kept table."""
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(stored, dict):
            stored = {}
    except (OSError, json.JSONDecodeError):
        stored = {}
    stored[lane] = {module: round(seconds, 3) for module, seconds in sorted(observed.items())}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(stored, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def schedule_order(counts: dict[str, int], durations: dict[str, float]) -> list[str]:
    """Longest first, because the last module dispatched sets the wall clock.

    Measured seconds from the previous run rank a module when they exist; case
    count is the stand-in on the first run, before anything has been measured.
    """
    return sorted(
        counts,
        key=lambda module: (durations.get(module, 0.0), counts[module], module),
        reverse=True,
    )


def worker_environment(path_entries: list[str], *, cwd: Path = ROOT,
                       start_dir: str | None = None) -> dict[str, str]:
    """Give a worker discovery's own import path, and the nested-run marker.

    The marker matters because several tests legitimately spawn the bounded
    launcher; without it, eight concurrent workers would each let their child
    overwrite the single acceptance receipt -- the failure already recorded as
    R-TOOLS-PRECOMMIT-RECEIPT-SELF-CLOBBER, multiplied by the pool size.

    Discovery may resolve a package through a transient ``sys.path`` entry that
    is not present in the parent environment.  Keep the worker independent of
    that transient state by also binding the caller's cwd and start directory
    explicitly, after resolving relative entries against the same cwd.
    """
    env = {NESTED_RUN_MARKER: "1"}
    entries: list[str] = []

    def add_entry(entry: str | Path) -> None:
        path = Path(entry) if str(entry) else cwd
        if not path.is_absolute():
            path = cwd / path
        value = str(path.resolve())
        if value not in entries:
            entries.append(value)

    add_entry(cwd)
    for entry in path_entries:
        add_entry(entry)
    if start_dir:
        add_entry(start_dir)
    inherited = os.environ.get("PYTHONPATH", "")
    if inherited:
        entries.append(inherited)
    if entries:
        env["PYTHONPATH"] = os.pathsep.join(entries)
    return env


def _run_module(module: str, timeout_seconds: int, log_dir: Path | None,
                runtime_args: tuple[str, ...] = FULL_PACK_RUNTIME_ARGS,
                cwd: Path = ROOT,
                worker_env: dict[str, str] | None = None) -> ModuleOutcome:
    result = run_command(
        [sys.executable, "-m", "unittest", *runtime_args, module],
        timeout_seconds,
        cwd=cwd,
        extra_env=worker_env if worker_env is not None else {NESTED_RUN_MARKER: "1"},
    )
    log_path = None
    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            target = log_dir / f"{module}.log"
            target.write_text(result.output, encoding="utf-8", errors="replace")
            log_path = _display_path(target)
        except OSError:
            log_path = None
    return ModuleOutcome(
        module=module,
        status=result.status,
        exit_code=result.exit_code,
        tests=result.tests,
        elapsed_seconds=result.elapsed_seconds,
        output=result.output,
        log_path=log_path,
    )


def _aggregate_durations(outcomes: list[ModuleOutcome], limit: int = 25) -> list[tuple[float, str]]:
    entries: list[tuple[float, str]] = []
    for outcome in outcomes:
        for seconds, test_id in _DURATION_LINE.findall(outcome.output or ""):
            entries.append((float(seconds), test_id))
    entries.sort(reverse=True)
    return entries[:limit]


def _write_sidecar(path: Path, lane: str, outcomes: list[ModuleOutcome],
                   slowest: list[tuple[float, str]]) -> str | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for outcome in outcomes:
                handle.write(json.dumps({
                    "lane": lane,
                    "module": outcome.module,
                    "status": outcome.status,
                    "exit": outcome.exit_code,
                    "ran": outcome.tests,
                    "elapsed_seconds": round(outcome.elapsed_seconds, 3),
                    "log": outcome.log_path,
                }, ensure_ascii=False) + "\n")
            handle.write(json.dumps({
                "lane": lane,
                "record": "slowest_tests",
                "entries": [{"seconds": seconds, "test": test_id} for seconds, test_id in slowest],
            }, ensure_ascii=False) + "\n")
        return _display_path(path)
    except OSError:
        return None


def _report(lane: str, outcomes: list[ModuleOutcome], skipped: list[str], discovered_total: int,
            observed_total: int, sidecar: str | None, slowest: list[tuple[float, str]],
            elapsed: float, workers: int, tail: list[str],
            duplicated: list[list[str]], deadline_seconds: int) -> str:
    lines = [
        f"[parallel-lane] lane={lane} workers={workers} modules={len(outcomes) + len(skipped)} "
        f"discovered_cases={discovered_total} serial_tail={len(tail)}",
    ]
    for module in tail:
        lines.append(f"[parallel-lane] SERIAL_TAIL {module} (reaches a cross-process lock)")
    for names in duplicated:
        lines.append(
            f"[parallel-lane] DOUBLE_IMPORT one file reported under {len(names)} names, so its "
            f"cases are counted and run twice: {', '.join(names)}"
        )
    for outcome in sorted(outcomes, key=lambda item: item.elapsed_seconds, reverse=True):
        ran = outcome.tests if outcome.tests is not None else "UNKNOWN"
        lines.append(
            f"[parallel-lane] {outcome.status:<7} ran={ran:<5} "
            f"{outcome.elapsed_seconds:7.1f}s {outcome.module}"
        )
    for module in skipped:
        lines.append(f"[parallel-lane] SKIPPED ran=-     dispatch halted after a red module {module}")
    for outcome in outcomes:
        if outcome.status != "PASS":
            lines.append(f"[parallel-lane] ---- {outcome.status} output: {outcome.module} ----")
            lines.append((outcome.output or "").rstrip())
    if slowest:
        lines.append("[parallel-lane] slowest tests across all workers")
        for seconds, test_id in slowest:
            lines.append(f"[parallel-lane]   {seconds:.3f}s {test_id}")
    if sidecar:
        lines.append(f"[parallel-lane] sidecar={sidecar}")
    floor = max(outcomes, key=lambda item: item.elapsed_seconds, default=None)
    if floor is not None:
        share = 100.0 * floor.elapsed_seconds / elapsed if elapsed > 0 else 0.0
        lines.append(
            f"[parallel-lane] WALL_CLOCK_FLOOR {floor.elapsed_seconds:.1f}s of {elapsed:.1f}s "
            f"({share:.1f}%) is one module: {floor.module}. More workers cannot go below it; "
            f"only that module getting faster can. Deadline {deadline_seconds}s."
        )
    lines.append(
        f"[parallel-lane] COUNT_GATE discovered={discovered_total} ran={observed_total} "
        f"equal={discovered_total == observed_total}"
    )
    lines.append(f"Ran {observed_total} tests in {elapsed:.3f}s")
    return "\n".join(lines) + "\n"


def run_parallel_pack(
    lane: str,
    unittest_args: list[str],
    timeout_seconds: int,
    *,
    workers: int = WORKERS,
    runtime_args: tuple[str, ...] = FULL_PACK_RUNTIME_ARGS,
    runs_dir: Path = RUNS_DIR,
    durations_path: Path = DURATIONS_PATH,
    cwd: Path = ROOT,
) -> tuple[Result, dict]:
    """Run the lane's discovered modules concurrently and aggregate one verdict."""
    if workers < 1:
        raise ValueError("parallel full-pack needs at least one worker")
    started = time.monotonic()
    deadline = started + timeout_seconds
    counts, path_entries = discover_modules(unittest_args, cwd=cwd)
    start_dir, pattern, _top_level = parse_discovery_args(unittest_args)
    unreported, duplicated = _files_against_discovery(counts, path_entries, start_dir, pattern, cwd)
    if unreported:
        # Refuse before dispatching.  Only under-reporting is dangerous: it is
        # the one direction that can hide coverage, and it is invisible to the
        # count gate, which compares discovery's total against discovery's own
        # dispatch list.  Over-reporting cannot hide anything, so it is said out
        # loud below rather than refused.
        raise ValueError(
            f"discovery reported {len(counts)} modules but did not report "
            f"{len(unreported)} file(s) the selector matches; first: {unreported[0].name}"
        )
    worker_env = worker_environment(path_entries, cwd=cwd, start_dir=start_dir)
    discovered_total = sum(counts.values())
    stamp = time.strftime("%Y%m%dT%H%M%S")
    log_dir = runs_dir / f"{stamp}_{lane}_parallel"
    sidecar_path = runs_dir / f"{stamp}_{lane}_parallel.jsonl"

    tail = serial_tail_modules(counts, path_entries)
    ordered = schedule_order(counts, _load_durations(lane, durations_path))
    pending = deque(module for module in ordered if module not in tail)
    tail_pending = deque(module for module in ordered if module in tail)
    in_flight: dict[Future[ModuleOutcome], str] = {}
    outcomes: list[ModuleOutcome] = []
    halt_dispatch = False
    budget_exhausted = False

    with ThreadPoolExecutor(max_workers=workers) as pool:
        while pending or in_flight:
            while pending and len(in_flight) < workers and not halt_dispatch:
                remaining = int(deadline - time.monotonic())
                if remaining <= 0:
                    budget_exhausted = True
                    halt_dispatch = True
                    break
                module = pending.popleft()
                in_flight[
                    pool.submit(_run_module, module, remaining, log_dir, runtime_args,
                                cwd, worker_env)
                ] = module
            if not in_flight:
                break
            done, _ = wait(set(in_flight), return_when=FIRST_COMPLETED)
            for future in done:
                in_flight.pop(future)
                outcome = future.result()
                outcomes.append(outcome)
                if outcome.status != "PASS":
                    # Module-granularity failfast: stop dispatching, let the
                    # workers already running finish.  That only ever runs more
                    # modules than the serial `-f` would, never fewer.
                    halt_dispatch = True

    # The tail runs after the wave and one at a time: these modules contend on
    # a lock the wave would have held against them.
    while tail_pending and not halt_dispatch:
        remaining = int(deadline - time.monotonic())
        if remaining <= 0:
            budget_exhausted = True
            break
        outcome = _run_module(
            tail_pending.popleft(), remaining, log_dir, runtime_args, cwd, worker_env,
        )
        outcomes.append(outcome)
        if outcome.status != "PASS":
            halt_dispatch = True

    skipped = list(pending) + list(tail_pending)
    observed_total = sum(outcome.tests or 0 for outcome in outcomes)
    slowest = _aggregate_durations(outcomes)
    sidecar = _write_sidecar(sidecar_path, lane, outcomes, slowest)
    elapsed = time.monotonic() - started
    duplicate_groups = sorted(sorted(names) for names in duplicated.values())
    output = _report(lane, outcomes, skipped, discovered_total, observed_total,
                     sidecar, slowest, elapsed, workers, sorted(tail), duplicate_groups,
                     timeout_seconds)

    if all(outcome.status == "PASS" for outcome in outcomes):
        _store_durations(
            lane,
            {outcome.module: outcome.elapsed_seconds for outcome in outcomes},
            durations_path,
        )

    slowest_module = max(outcomes, key=lambda item: item.elapsed_seconds, default=None)
    summary = {
        "mode": "parallel",
        "workers": workers,
        # Wall clock is the entire reason this driver exists, and a reviewer
        # citing the ledger under rule 4 reads the record, not the console.  It
        # travels with the record so the claim can be checked where it is made.
        "elapsed_seconds": round(elapsed, 1),
        "deadline_seconds": timeout_seconds,
        # Dispatch is per module, so the slowest single module is a floor no
        # number of workers can go under.  Recorded because that floor, not the
        # lane total, is what the next ceiling scare will come from.
        "slowest_module": slowest_module.module if slowest_module else None,
        "slowest_module_seconds": round(slowest_module.elapsed_seconds, 1) if slowest_module else None,
        "serial_tail": sorted(tail),
        # One file reported under two names runs twice; harmless for coverage,
        # but it inflates the total a reviewer is about to cite.
        "duplicate_module_imports": duplicate_groups,
        "modules_discovered": len(counts),
        "modules_run": len(outcomes),
        "modules_not_dispatched": len(skipped),
        "discovered_cases": discovered_total,
        "ran_cases": observed_total,
        "count_gate_equal": observed_total == discovered_total,
        "sidecar": sidecar,
    }

    if budget_exhausted or any(outcome.status == "TIMEOUT" for outcome in outcomes):
        return Result("TIMEOUT", TIMEOUT_EXIT, None, elapsed, output), summary
    red = [outcome for outcome in outcomes if outcome.status != "PASS"]
    if red:
        return Result("FAIL", red[0].exit_code or 1, observed_total, elapsed, output), summary
    if skipped:
        return Result("FAIL", 1, observed_total, elapsed, output), summary
    if observed_total != discovered_total:
        # Every module reported OK, so nothing here is a test failure; what is
        # missing is the right to call the aggregate a full pack.
        return Result("UNKNOWN", INVALID_EVIDENCE_EXIT, observed_total, elapsed, output), summary
    return Result("PASS", 0, observed_total, elapsed, output), summary


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--" not in argv or len(argv) < 4:
        print("usage: parallel_lane_runner.py <lane> <timeout-seconds> -- <discovery args>")
        return 2
    split = argv.index("--")
    if split != 2:
        print("usage: parallel_lane_runner.py <lane> <timeout-seconds> -- <discovery args>")
        return 2
    try:
        result, _summary = run_parallel_pack(argv[0], argv[split + 1:], int(argv[1]))
    except (ValueError, OSError) as exc:
        print(f"[parallel-lane] REFUSED - {exc}")
        return 2
    print(result.output, end="" if result.output.endswith("\n") else "\n")
    count = str(result.tests) if result.tests is not None else "UNKNOWN"
    print(
        f"[parallel-lane] RESULT status={result.status} exit={result.exit_code} "
        f"tests={count} elapsed={result.elapsed_seconds:.1f}s deadline={argv[1]}s"
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
