#!/usr/bin/env python3
r"""Full-pack run ledger — enforce verification tiering rule 4 (one full run per unchanged code diff).

Records a lane's full-pack result keyed by a fingerprint of the current CODE working-tree state
(tracked diff-from-HEAD + untracked files, EXCLUDING docs / *.md, because per rule 4 a
docs/register/SESSION_LOG-only correction does not invalidate a run). ``check`` warns loudly AND
prints the cached count when a prepare-bound re-run would be redundant, so the reviewer cites that
cached green instead of re-running a multi-minute pack for a number they already have. Legacy
records written before the preparation gate are historical evidence only and are never reusable.

Usage:
   C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe .tools\full_pack_ledger.py run <lane> <full-trigger-reason> receipt:<receipt-id> <timeout-seconds> -- <unittest args>
   .\tools\codex_main_python.ps1 .tools\full_pack_ledger.py check <lane>

`run` accepts only the lane's fixed full-discovery selector: `a_short` = `discover -s tests -p test_a_short*.py`; `us_short` = `discover -s tests -p test_us_short*.py`.  The fixed `-b -f --durations 25` runtime flags are applied to every worker; they quiet passing output, stop on the first red, and retain timing evidence without narrowing discovery.

The pack is carried by concurrent module-level workers (`parallel_lane_runner`) under the same single total deadline.  The module list and the expected case total come from that same selector, and a green is recorded only when the cases the workers actually ran sum to the discovered total -- a dropped module is a FAIL, never a smaller green.

`check` exit code: 0 = cached green on the current exact code state (do NOT re-run; cite it);
1 = no cached green for the current code state (a full run is warranted only if tiering rule 3
applies). ``run`` is the only public write path: it checks the cache, binds the A-F preparation,
runs one bounded unittest process, verifies its exit code and test count, and records only PASS.
"""
from __future__ import annotations

import json
import py_compile
import shutil
import subprocess
import sys
import time
from pathlib import Path

from bounded_unittest import (
    DEPENDENCY_EXIT,
    FULL_MAX_SECONDS,
    FULL_PACK_RUNTIME_ARGS,
    external_test_dependency_error,
)
import parallel_lane_runner
import verification_receipt as receipts

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = ROOT / ".tools" / "state" / "full_pack_ledger.json"
FOCUSED_RECEIPT_PATH = receipts.RECEIPT_PATH
PREPARES_KEY = "_prepares"
FULL_PACK_DISCOVERY_ARGS = {
    "a_short": ("discover", "-s", "tests", "-p", "test_a_short*.py"),
    "us_short": ("discover", "-s", "tests", "-p", "test_us_short*.py"),
}
PRIVATE_TEST_ROOTS = (ROOT / "provider_samples", ROOT / "state" / "us_short")
PRIVATE_TEST_ROOT_MARKER = ".us_short_test_temp_root_owned"


def cleanup_orphaned_private_test_roots(
    roots: tuple[Path, ...] = PRIVATE_TEST_ROOTS,
) -> tuple[Path, ...]:
    """Remove only helper-marked temporary roots left by an interrupted test process.

    The marker is created by ``temporary_provider_directory``.  We require both that marker
    and an exact child of one of the two protected lane roots before deleting anything; a
    user-created or pre-existing private artifact is never a cleanup target.
    """
    removed: list[Path] = []
    for parent in roots:
        parent = parent.resolve()
        if not parent.is_dir():
            continue
        for candidate in tuple(parent.iterdir()):
            if not candidate.is_dir() or not (candidate / PRIVATE_TEST_ROOT_MARKER).is_file():
                continue
            candidate = candidate.resolve()
            try:
                candidate.relative_to(parent)
            except ValueError:
                continue
            try:
                shutil.rmtree(candidate)
            except OSError:
                continue
            removed.append(candidate)
    return tuple(removed)


def snapshot_private_test_dirs(
    roots: tuple[Path, ...] = PRIVATE_TEST_ROOTS,
) -> frozenset[Path]:
    """Capture existing directories so full-pack cleanup never targets prior evidence."""
    snapshot: set[Path] = set()
    for parent in roots:
        parent = parent.resolve()
        if parent.is_dir():
            snapshot.update(
                path.resolve() for path in parent.rglob("*") if path.is_dir()
            )
    return frozenset(snapshot)


def cleanup_new_private_test_roots(
    before: frozenset[Path],
    roots: tuple[Path, ...] = PRIVATE_TEST_ROOTS,
) -> tuple[Path, ...]:
    """Remove only new tempfile-style directories below the protected lane roots."""
    removed: list[Path] = []
    candidates: set[Path] = set()
    for parent in roots:
        parent = parent.resolve()
        if parent.is_dir():
            candidates.update(
                path.resolve()
                for path in parent.rglob("tmp*")
                if path.is_dir() and path.resolve() not in before
            )
    for candidate in sorted(candidates, key=lambda path: len(path.parts), reverse=True):
        if any(candidate == prior or prior in candidate.parents for prior in removed):
            continue
        try:
            shutil.rmtree(candidate)
        except OSError:
            continue
        removed.append(candidate)
    return tuple(removed)


def _is_code_path(rel_path: str) -> bool:
    """A docs/register/SESSION_LOG-only edit must NOT invalidate a code full-pack (rule 4)."""
    return receipts.is_code_path(rel_path)


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True).stdout


def collect_code_state() -> dict[str, str]:
    """Map every code file that differs from HEAD or is untracked to its content sha (+ HEAD)."""
    return receipts.collect_code_state()


def fingerprint(state: dict[str, str]) -> str:
    return receipts.fingerprint(state)


def _load(ledger: Path) -> dict:
    try:
        return json.loads(ledger.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def prepare(
    lane: str,
    trigger_reason: str,
    focused_evidence: str,
    *,
    state: dict[str, str] | None = None,
    ledger: Path = DEFAULT_LEDGER,
    focused_receipt_path: Path = FOCUSED_RECEIPT_PATH,
) -> str:
    """Attest that the focused loop and A-F review are complete for this code state."""
    if not str(trigger_reason).strip():
        raise ValueError("prepare requires a full-trigger reason and focused-test evidence")
    if not str(focused_evidence).strip():
        raise ValueError("prepare requires a full-trigger reason and focused-test evidence")
    if not isinstance(focused_evidence, str) or not focused_evidence.startswith("receipt:"):
        raise ValueError("prepare requires the machine focused receipt token `receipt:<receipt_id>`")
    current_state = state if state is not None else collect_code_state()
    receipt, receipt_reason = _receipt_matches_current_state(
        focused_evidence,
        state=current_state,
        path=focused_receipt_path,
    )
    if receipt is None:
        raise ValueError(f"prepare requires a current focused receipt: {receipt_reason}")
    fp = fingerprint(current_state)
    data = _load(ledger)
    prepares = data.setdefault(PREPARES_KEY, {})
    prepares[lane] = {
        "fingerprint": fp,
        "self_review": "A-F complete after focused loop converged",
        "trigger_reason": str(trigger_reason),
        "focused_evidence": str(focused_evidence),
        "prepared_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return fp


def prepared_review(lane: str, *, state: dict[str, str] | None = None,
                    ledger: Path = DEFAULT_LEDGER) -> dict | None:
    """Return the preparation iff it binds the exact current code state."""
    fp = fingerprint(state if state is not None else collect_code_state())
    prepared = _load(ledger).get(PREPARES_KEY, {}).get(lane)
    if isinstance(prepared, dict) and prepared.get("fingerprint") == fp:
        return prepared
    return None


def record(lane: str, count: str, *, state: dict[str, str] | None = None,
           ledger: Path = DEFAULT_LEDGER, run_detail: dict | None = None) -> str:
    current_state = state if state is not None else collect_code_state()
    fp = fingerprint(current_state)
    if prepared_review(lane, state=current_state, ledger=ledger) is None:
        raise ValueError("cannot record full-pack green without matching prepare")
    data = _load(ledger)
    data[lane] = {
        "fingerprint": fp,
        "prepared_fingerprint": fp,
        "count": count,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        # How the count was obtained is part of what a reviewer is citing, so
        # the per-module detail travels with the record rather than living only
        # in a console scrollback.
        "run_detail": dict(run_detail) if run_detail else None,
    }
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return fp


def _pre_full_static_checks(state: dict[str, str]) -> bool:
    """Run the cheap, deterministic gates immediately before the one full process."""
    diff_check = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    if diff_check.returncode != 0:
        detail = (diff_check.stdout + diff_check.stderr).strip()
        print(f"[full-pack-ledger] REFUSED - git diff --check failed\n{detail}")
        return False
    compiled = 0
    try:
        for rel in sorted(state):
            if rel.startswith("@") or not rel.endswith(".py"):
                continue
            path = ROOT / rel
            if path.is_file():
                py_compile.compile(str(path), doraise=True)
                compiled += 1
    except (OSError, py_compile.PyCompileError) as exc:
        print(f"[full-pack-ledger] REFUSED - py_compile failed: {exc}")
        return False
    print(f"[full-pack-ledger] STATIC status=PASS diff_check=PASS py_compile={compiled}")
    return True


def _receipt_matches_current_state(
    focused_evidence: str,
    *,
    state: dict[str, str],
    path: Path = FOCUSED_RECEIPT_PATH,
) -> tuple[dict | None, str]:
    return receipts.validate_focused_evidence(
        focused_evidence,
        state=state,
        path=path,
    )


def _execute_full_pack(
    lane: str, unittest_args: list[str], timeout_seconds: int
) -> tuple[object, dict]:
    """Carry the lane's one full pack, concurrently, under the same total deadline.

    Only the process count changes here.  The module list and the expected case
    total are derived from ``unittest_args`` -- the same selector a serial run
    would hand to ``unittest`` -- and the runtime flags are applied per worker,
    so what is being verified is unchanged and only the wall clock moves.
    """
    return parallel_lane_runner.run_parallel_pack(
        lane,
        unittest_args,
        timeout_seconds,
        runtime_args=FULL_PACK_RUNTIME_ARGS,
    )


def run_full_pack(
    lane: str,
    trigger_reason: str,
    focused_evidence: str,
    timeout_seconds: int,
    unittest_args: list[str],
    *,
    state: dict[str, str] | None = None,
    ledger: Path = DEFAULT_LEDGER,
    focused_receipt_path: Path = FOCUSED_RECEIPT_PATH,
) -> int:
    """Run the simplified check/prepare/test/record chain."""
    if timeout_seconds <= 0 or timeout_seconds > FULL_MAX_SECONDS:
        raise ValueError(f"full timeout must be 1..{FULL_MAX_SECONDS} seconds")
    if not unittest_args:
        raise ValueError("run requires unittest arguments after --")
    required_args = FULL_PACK_DISCOVERY_ARGS.get(lane)
    if required_args is None:
        raise ValueError(f"unknown lane for full-pack ledger: {lane}")
    if tuple(unittest_args) != required_args:
        raise ValueError(
            f"{lane} full-pack must exactly use unittest args {list(required_args)!r}"
        )
    dependency_error = external_test_dependency_error(lane)
    if dependency_error:
        print(f"[full-pack-ledger] RESULT status=FAIL exit={DEPENDENCY_EXIT} tests=UNKNOWN "
              f"elapsed=0.0s deadline={timeout_seconds}s\n[full-pack-ledger] {dependency_error}")
        return DEPENDENCY_EXIT
    current_state = state if state is not None else collect_code_state()
    receipt, receipt_reason = _receipt_matches_current_state(
        focused_evidence,
        state=current_state,
        path=focused_receipt_path,
    )
    if receipt is None:
        print(f"[full-pack-ledger] REFUSED - {receipt_reason}")
        return 2
    print(
        f"[full-pack-ledger] FOCUSED_RECEIPT status=PASS tests={receipt['tests']} "
        f"bundles={','.join(receipt['bundles']) or 'none'}"
    )
    hit = cached_green(
        lane,
        state=current_state,
        ledger=ledger,
        focused_receipt_path=focused_receipt_path,
    )
    if hit is not None:
        print(f"[full-pack-ledger] CACHED GREEN - {lane} = {hit['count']}; full run skipped.")
        return 0
    if not _pre_full_static_checks(current_state):
        return 2
    prepared_fingerprint = prepare(
        lane,
        trigger_reason,
        focused_evidence,
        state=current_state,
        ledger=ledger,
        focused_receipt_path=focused_receipt_path,
    )
    print(
        f"[full-pack-ledger] START lane={lane} deadline={timeout_seconds}s "
        f"fingerprint={prepared_fingerprint[:12]}",
        flush=True,
    )
    private_dirs_before = snapshot_private_test_dirs()
    try:
        result, run_detail = _execute_full_pack(lane, unittest_args, timeout_seconds)
    finally:
        orphaned = cleanup_orphaned_private_test_roots()
        new_tmp_dirs = cleanup_new_private_test_roots(private_dirs_before)
        cleaned = orphaned + new_tmp_dirs
        if cleaned:
            print(
                f"[full-pack-ledger] CLEANUP removed={len(cleaned)} "
                "new/helper-marked private roots",
                flush=True,
            )
    if result.output:
        print(result.output, end="" if result.output.endswith("\n") else "\n")
    count = str(result.tests) if result.tests is not None else "UNKNOWN"
    print(
        f"[full-pack-ledger] RESULT status={result.status} exit={result.exit_code} "
        f"tests={count} elapsed={result.elapsed_seconds:.1f}s deadline={timeout_seconds}s "
        f"mode={run_detail.get('mode', 'unknown')}"
    )
    if result.status != "PASS":
        return result.exit_code
    final_state = state if state is not None else collect_code_state()
    if fingerprint(final_state) != fingerprint(current_state):
        print("[full-pack-ledger] REFUSED - code state changed during the full run")
        return 2
    record(lane, f"{result.tests} OK", state=final_state, ledger=ledger, run_detail=run_detail)
    return 0


def cached_green(
    lane: str,
    *,
    state: dict[str, str] | None = None,
    ledger: Path = DEFAULT_LEDGER,
    focused_receipt_path: Path = FOCUSED_RECEIPT_PATH,
) -> dict | None:
    """Return the cached record iff the current code state matches a recorded run for the lane."""
    current_state = state if state is not None else collect_code_state()
    fp = fingerprint(current_state)
    record_for_lane = _load(ledger).get(lane)
    matching_prepare = prepared_review(lane, state=current_state, ledger=ledger)
    if matching_prepare is not None:
        receipt, _ = _receipt_matches_current_state(
            str(matching_prepare.get("focused_evidence", "")),
            state=current_state,
            path=focused_receipt_path,
        )
        if receipt is None:
            return None
    if (record_for_lane and record_for_lane.get("fingerprint") == fp
            and record_for_lane.get("prepared_fingerprint") == fp
            and matching_prepare is not None):
        return record_for_lane
    return None


def _check(lane: str, *, state: dict[str, str] | None = None,
           ledger: Path = DEFAULT_LEDGER) -> int:
    dependency_error = external_test_dependency_error(lane)
    if dependency_error:
        print(f"[full-pack-ledger] environment incomplete — cached green unavailable: {dependency_error}")
        return 1
    current_state = state if state is not None else collect_code_state()
    prepared = prepared_review(lane, state=current_state, ledger=ledger)
    record_for_lane = _load(ledger).get(lane)
    hit = cached_green(lane, state=current_state, ledger=ledger)
    if hit is not None:
        print(f"[full-pack-ledger] PREPARED A-F — {lane}: {prepared['trigger_reason']} | "
              f"focused={prepared['focused_evidence']}\n[full-pack-ledger] CACHED GREEN — {lane} = "
              f"{hit['count']} at {hit['recorded_at']} on this EXACT code state.\n"
              "[full-pack-ledger] Tiering rule 4: do NOT re-run the full pack; cite this cached run.")
        return 0
    if (isinstance(record_for_lane, dict)
            and record_for_lane.get("fingerprint") == fingerprint(current_state)
            and "prepared_fingerprint" not in record_for_lane):
        print(f"[full-pack-ledger] STALE LEGACY GREEN — {lane} = {record_for_lane.get('count', 'UNKNOWN')} "
              f"at {record_for_lane.get('recorded_at', 'UNKNOWN')}; it predates the A-F prepare binding "
              "and is not reusable closeout evidence.")
        return 1
    if prepared is not None:
        print(f"[full-pack-ledger] PREPARED A-F — {lane}: {prepared['trigger_reason']} | "
              f"focused={prepared['focused_evidence']}\n[full-pack-ledger] no cached green for this prepared "
              "code state — use the single `run` command only if tiering rule 3 applies.")
        return 1
    print(f"[full-pack-ledger] no cached green for {lane} on the current code state — a full run is "
          "warranted ONLY if tiering rule 3 applies (else focused pack); "
          "complete the focused loop and A-F, then use the single `run` command.")
    return 1


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    pin_error = receipts.pinned_python_error()
    if pin_error:
        print(f"[full-pack-ledger] REFUSED - {pin_error}")
        return 2
    if len(argv) >= 2 and argv[1] == "run":
        if "--" not in argv:
            print("[full-pack-ledger] REFUSED - invalid run arguments; missing `--` before unittest args")
            return 2
        split = argv.index("--")
        if split != 6:
            print("[full-pack-ledger] REFUSED - invalid run arguments; expected "
                  "`run <lane> <trigger> <focused evidence> <timeout> -- <unittest args>`")
            return 2
        try:
            return run_full_pack(
                argv[2],
                argv[3],
                argv[4],
                int(argv[5]),
                argv[split + 1:],
            )
        except (ValueError, OSError) as exc:
            print(f"[full-pack-ledger] REFUSED - {exc}")
            return 2
    if len(argv) >= 3 and argv[1] in {"prepare", "record"}:
        print("[full-pack-ledger] REFUSED - use the single `run` command; manual prepare/record is retired")
        return 2
    if len(argv) >= 3 and argv[1] == "check":
        return _check(argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
