#!/usr/bin/env python3
"""Full-pack run ledger — enforce verification tiering rule 4 (one full run per unchanged code diff).

Records a lane's full-pack result keyed by a fingerprint of the current CODE working-tree state
(tracked diff-from-HEAD + untracked files, EXCLUDING docs / *.md, because per rule 4 a
docs/register/SESSION_LOG-only correction does not invalidate a run). ``check`` warns loudly AND
prints the cached count when a re-run would be redundant, so the reviewer cites the cached green
instead of re-running a multi-minute pack for a number they already have.

Usage:
  python .tools/full_pack_ledger.py record <lane> <count>   # right after a REAL green full run
  python .tools/full_pack_ledger.py check  <lane>           # before considering a (re-)run

`check` exit code: 0 = cached green on the current exact code state (do NOT re-run; cite it);
1 = no cached green for the current code state (a full run is warranted only if tiering rule 3
applies). This is advisory: it makes a redundant re-run visible, it does not block.
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


def record(lane: str, count: str, *, state: dict[str, str] | None = None, ledger: Path = DEFAULT_LEDGER) -> str:
    fp = fingerprint(state if state is not None else collect_code_state())
    data = _load(ledger)
    data[lane] = {"fingerprint": fp, "count": count, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return fp


def cached_green(lane: str, *, state: dict[str, str] | None = None, ledger: Path = DEFAULT_LEDGER) -> dict | None:
    """Return the cached record iff the current code state matches a recorded run for the lane."""
    fp = fingerprint(state if state is not None else collect_code_state())
    record_for_lane = _load(ledger).get(lane)
    if record_for_lane and record_for_lane.get("fingerprint") == fp:
        return record_for_lane
    return None


def _check(lane: str) -> int:
    hit = cached_green(lane)
    if hit is not None:
        print(f"[full-pack-ledger] CACHED GREEN — {lane} = {hit['count']} at {hit['recorded_at']} on this EXACT "
              f"code state.\n[full-pack-ledger] Tiering rule 4: do NOT re-run the full pack; cite this cached run.")
        return 0
    print(f"[full-pack-ledger] no cached green for {lane} on the current code state — a full run is "
          f"warranted ONLY if tiering rule 3 applies (else focused pack).")
    return 1


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "record":
        fp = record(argv[2], argv[3] if len(argv) > 3 else "OK")
        print(f"[full-pack-ledger] recorded {argv[2]} @ {fp[:12]}")
        return 0
    if len(argv) >= 3 and argv[1] == "check":
        return _check(argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
