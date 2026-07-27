#!/usr/bin/env python3
r"""Full-pack run ledger — enforce verification tiering rule 4 (one full run per unchanged code diff).

Records a lane's full-pack result keyed by a fingerprint of the current CODE working-tree state
(tracked diff-from-HEAD + untracked files, EXCLUDING docs / *.md, because per rule 4 a
docs/register/SESSION_LOG-only correction does not invalidate a run). ``check`` warns loudly AND
prints the cached count when a re-run would be redundant, so the reviewer cites the cached green
instead of re-running a multi-minute pack for a number they already have.

Usage:
   .\tools\codex_main_python.ps1 .tools\full_pack_ledger.py prepare <lane> <full-trigger-reason> <focused-evidence>
   .\tools\codex_main_python.ps1 .tools\full_pack_ledger.py record <lane> <count>   # right after a REAL green full run
   .\tools\codex_main_python.ps1 .tools\full_pack_ledger.py check  <lane>           # before considering a (re-)run

`check` exit code: 0 = cached green on the current exact code state (do NOT re-run; cite it);
1 = no cached green for the current code state (a full run is warranted only if tiering rule 3
applies). ``prepare`` attests that the focused repair loop converged and the A-F self-review is
complete before the one final full run. ``record`` refuses to create a new green without the
matching preparation, so a behavior/contract edit after self-review must return to the focused loop.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = ROOT / ".tools" / "state" / "full_pack_ledger.json"
PREPARES_KEY = "_prepares"


def _is_code_path(rel_path: str) -> bool:
    """A docs/register/SESSION_LOG-only edit must NOT invalidate a code full-pack (rule 4)."""
    r = rel_path.replace("\\", "/")
    if r.startswith("docs/") or r.endswith(".md"):
        return False
    return True


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True).stdout


def collect_code_state() -> dict[str, str]:
    """Map every code file that differs from HEAD or is untracked to its content sha (+ HEAD)."""
    changed = [line for line in _git("diff", "HEAD", "--name-only").splitlines() if line]
    untracked = [line for line in _git("ls-files", "--others", "--exclude-standard").splitlines() if line]
    state: dict[str, str] = {}
    for rel in set(changed) | set(untracked):
        if not _is_code_path(rel):
            continue
        path = ROOT / rel
        state[rel] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "ABSENT"
    state["@HEAD"] = _git("rev-parse", "HEAD").strip()
    return state


def fingerprint(state: dict[str, str]) -> str:
    canonical = "\n".join(f"{key}:{state[key]}" for key in sorted(state))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load(ledger: Path) -> dict:
    try:
        return json.loads(ledger.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def prepare(lane: str, trigger_reason: str, focused_evidence: str, *,
            state: dict[str, str] | None = None, ledger: Path = DEFAULT_LEDGER) -> str:
    """Attest that the focused loop and A-F review are complete for this code state."""
    if not str(trigger_reason).strip() or not str(focused_evidence).strip():
        raise ValueError("prepare requires a full-trigger reason and focused-test evidence")
    fp = fingerprint(state if state is not None else collect_code_state())
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


def record(lane: str, count: str, *, state: dict[str, str] | None = None, ledger: Path = DEFAULT_LEDGER) -> str:
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
    }
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return fp


def cached_green(lane: str, *, state: dict[str, str] | None = None, ledger: Path = DEFAULT_LEDGER) -> dict | None:
    """Return the cached record iff the current code state matches a recorded run for the lane."""
    current_state = state if state is not None else collect_code_state()
    fp = fingerprint(current_state)
    record_for_lane = _load(ledger).get(lane)
    matching_prepare = prepared_review(lane, state=current_state, ledger=ledger)
    if (record_for_lane and record_for_lane.get("fingerprint") == fp
            and (matching_prepare is not None
                 or "prepared_fingerprint" not in record_for_lane)):
        return record_for_lane
    return None


def _check(lane: str, *, state: dict[str, str] | None = None,
           ledger: Path = DEFAULT_LEDGER) -> int:
    current_state = state if state is not None else collect_code_state()
    prepared = prepared_review(lane, state=current_state, ledger=ledger)
    hit = cached_green(lane, state=current_state, ledger=ledger)
    if hit is not None:
        if prepared is None:
            print(f"[full-pack-ledger] LEGACY CACHED GREEN — {lane} = {hit['count']} at "
                  f"{hit['recorded_at']} on this exact code state; it predates the prepare gate.\n"
                  "[full-pack-ledger] Do NOT re-run solely to migrate this record; future `record` calls require prepare.")
            return 0
        print(f"[full-pack-ledger] PREPARED A-F — {lane}: {prepared['trigger_reason']} | "
              f"focused={prepared['focused_evidence']}\n[full-pack-ledger] CACHED GREEN — {lane} = "
              f"{hit['count']} at {hit['recorded_at']} on this EXACT code state.\n"
              "[full-pack-ledger] Tiering rule 4: do NOT re-run the full pack; cite this cached run.")
        return 0
    if prepared is not None:
        print(f"[full-pack-ledger] PREPARED A-F — {lane}: {prepared['trigger_reason']} | "
              f"focused={prepared['focused_evidence']}\n[full-pack-ledger] no cached green for this prepared "
              "code state — run one full pack only if tiering rule 3 applies.")
        return 1
    print(f"[full-pack-ledger] no cached green for {lane} on the current code state — a full run is "
          "warranted ONLY if tiering rule 3 applies (else focused pack); "
          "complete the focused loop, A-F, and `prepare` before a required full run.")
    return 1


def main(argv: list[str]) -> int:
    if len(argv) >= 5 and argv[1] == "prepare":
        try:
            fp = prepare(argv[2], argv[3], argv[4])
        except ValueError as exc:
            print(f"[full-pack-ledger] REFUSED — {exc}")
            return 2
        print(f"[full-pack-ledger] prepared {argv[2]} @ {fp[:12]}")
        return 0
    if len(argv) >= 3 and argv[1] == "record":
        try:
            fp = record(argv[2], argv[3] if len(argv) > 3 else "OK")
        except ValueError as exc:
            print(f"[full-pack-ledger] REFUSED — {exc}")
            return 2
        print(f"[full-pack-ledger] recorded {argv[2]} @ {fp[:12]}")
        return 0
    if len(argv) >= 3 and argv[1] == "check":
        return _check(argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
