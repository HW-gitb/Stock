# -*- coding: utf-8 -*-
"""US-short fail-closed private-path guard (reusable engine helper).

Design authority: ``docs/us_short_system_design.md`` §11.6 / §18.0 P0 / §18.1 #1.

US-short private outputs — machine layer (``runs_private``), paper track
(``model_paper_private``), lifecycle counts (``lifecycle``), comparison-track shadow
(``shadow_compare_private``), weekly_private — contain ticker names, holdings, cost and
fills. They MUST land only on gitignored (private) paths. This helper is the fail-closed
floor every US-short persister calls *before* writing: any in-repo output path that git
does not provably ignore is refused, and a git-check failure (git missing / unexpected
return code) is ALSO refused, because we cannot then prove the path is private.

Mirrors ``runners/us_short_account_state_from_manual_tables.py``
``_reject_nonprivate_account_output_path`` (the no-in-repo-override version, per
``R-USSHORT-ACCTSTATE-PRIVATE-OUTPUT-OVERRIDE-BYPASS``): the ONLY sanctioned
non-gitignored destination is OUTSIDE the repo (the user's own external private
location). There is deliberately NO in-repo override — real holdings/fills must never
land on a tracked path, even on explicit request.

Batch-2 scope note: the batch-2 price engine itself writes nothing. This guard lands now
(§18.1 #1 / ``R-USSHORT-PRIVATE-PATH-FAILCLOSED-GUARD-TEST``) as a single tested helper so
every later US-short persister (cooldown sidecar, machine layer, paper track) calls one
fail-closed gate rather than re-implementing the check. Pure/offline; no A-share crossing.
"""
import subprocess
from pathlib import Path

# engine/us_short_private_paths.py -> engine/ -> repo root
ROOT = Path(__file__).resolve().parent.parent


class PrivatePathError(RuntimeError):
    """Raised when a US-short private output path cannot be proven gitignored (fail-closed)."""


def reject_nonprivate_output_path(out_path) -> None:
    """Refuse to write US-short private data unless the path is provably private.

    Decision (fail-closed):
      * outside the repo                      -> OK   (user's own external private location)
      * in-repo AND gitignored                -> OK   (private)
      * in-repo AND not gitignored            -> raise (would risk committing tickers/holdings/fills)
      * git unavailable / unexpected rc       -> raise (cannot prove the path is private)

    Uses the real ``git check-ignore`` value, not a path-name heuristic, so a fake
    ``runs_private`` directory, a nesting level not covered by ``state/*/<private>/``, or a
    case variant are all judged by git's actual ignore behaviour. There is no in-repo
    override argument by design.
    """
    p = Path(out_path).resolve()
    try:
        p.relative_to(ROOT)
    except ValueError:
        return  # outside the repo -> user's own external private location
    try:
        r = subprocess.run(
            ["git", "check-ignore", "-q", "--", str(p)],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError) as e:
        raise PrivatePathError(
            f"cannot verify {p} is gitignored (git check-ignore unavailable: {e}); "
            "fail-closed, refusing to write US-short private data"
        )
    if r.returncode == 0:
        return  # ignored -> private -> OK
    if r.returncode == 1:
        raise PrivatePathError(
            f"refusing to write US-short private data to non-gitignored in-repo path {p} "
            "(would risk committing tickers/holdings/fills). Put it under a gitignored private dir, "
            "e.g. state/us_short/{runs_private,model_paper_private,lifecycle,shadow_compare_private}/, "
            "or write it OUTSIDE the repo. There is no in-repo override."
        )
    raise PrivatePathError(
        f"git check-ignore failed for {p} (rc={r.returncode}); fail-closed, "
        "refusing to write US-short private data"
    )
