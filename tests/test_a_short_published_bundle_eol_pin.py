"""Guard: frozen published weekly bundles must be byte-identical on every checkout.

Once the relevant A-short evidence track is explicitly frozen, the comparison
ledgers bind evidence by the RAW sha256 of these files
(`m67_provenance.source_sha256`, and the official-operation capture's source
identity).  This repository runs with `core.autocrlf=true`, so without a
`-text` pin a fresh clone or `git worktree add` smudges the bundles to CRLF,
their sha stops matching the recorded one, and every source-binding assertion
fails for a reason that has nothing to do with the code under review.  Before
the user authorizes design completion, those records are audit-only and are
not required to be members of the frozen bundle set.

That false red has already consumed a full review round, with the reviewer and
the implementer measuring opposite results on two different trees.  This guard
turns the manual `git check-attr` spot-check into a machine check, and it fails
loudly on a smudged worktree instead of letting the operator chase a phantom
evidence drift.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path

from engine import a_short_evidence_epoch_mode as epoch_mode

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATTERN = "research/results/a_short/*/weekly_m67.*"
RECORDS = ROOT / "research" / "results" / "a_short" / "regime_action_comparison_records.json"
REGIME_TRACK = "p1_regime_candidate_effect"
EOL_ROW = re.compile(r"^i/(?P<index>\S*)\s+w/(?P<worktree>\S*)\s+attr/(?P<attr>\S*)\s*\t(?P<path>.+)$")


def _git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True)
    return result.stdout


def _tracked_bundles() -> list[dict]:
    rows = []
    for line in _git("ls-files", "--eol", BUNDLE_PATTERN).splitlines():
        match = EOL_ROW.match(line.strip())
        if match:
            rows.append(match.groupdict())
    return rows


class PublishedBundleEolPinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundles = _tracked_bundles()
        self.assertTrue(self.bundles, "no published weekly bundle is tracked; the guard would be vacuous")

    def test_every_published_bundle_is_pinned_and_checked_out_as_lf(self) -> None:
        """Covers the whole class: every tracked bundle, every file type."""
        unpinned = [row["path"] for row in self.bundles if row["attr"] != "-text"]
        self.assertEqual(unpinned, [], "`.gitattributes` does not pin these bundles with -text; "
                                       "a fresh checkout will smudge them to CRLF and break their recorded sha")
        smudged = [row["path"] for row in self.bundles if row["worktree"] not in ("lf", "")]
        self.assertEqual(smudged, [], "this worktree holds CRLF copies of sha-pinned bundles; re-check them out "
                                      "(delete the paths and `git checkout -- <paths>`) before trusting any "
                                      "source-binding failure")

    def test_no_published_bundle_contains_crlf_on_disk(self) -> None:
        """Independent of git plumbing: the bytes the hashes are taken over."""
        with_crlf = [row["path"] for row in self.bundles if b"\r\n" in (ROOT / row["path"]).read_bytes()]
        self.assertEqual(with_crlf, [])

    def test_recorded_source_sha_still_matches_a_tracked_bundle(self) -> None:
        """Check source binding only after this track is explicitly frozen."""
        payload = json.loads(RECORDS.read_text(encoding="utf-8"))
        records = payload if isinstance(payload, list) else payload.get("records", [])
        recorded = [str((row.get("m67_provenance") or {}).get("source_sha256") or "")
                    for row in records if (row.get("m67_provenance") or {}).get("source_sha256")]
        if not epoch_mode.durable_evidence_writes_enabled(REGIME_TRACK):
            # Pre-freeze rows remain available for audit, but they must not turn
            # an untracked audit artifact into a failed frozen-bundle assertion.
            return
        self.assertTrue(recorded, "no recorded provenance sha; this guard would be vacuous")
        available = {hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest() for row in self.bundles}
        self.assertEqual([sha for sha in recorded if sha not in available], [])


    def test_the_only_writer_of_these_bundles_normalises_to_lf(self) -> None:
        """Root cause, not just today's offender.

        `ConvertTo-Json` emits CRLF on Windows and the callers append a bare
        LF terminator, so the launcher used to write mixed-ending receipts and
        manifests; the next failed weekly run would re-offend the moment its
        receipt was tracked.  All three callers go through one write door, so
        the normalisation belongs there and this assertion pins it.
        """
        launcher = (ROOT / "runners" / "weekly_screening.ps1").read_text(encoding="utf-8")
        door = launcher[launcher.index("function Write-M67Utf8NoBom"):]
        door = door[:door.index("\nfunction ")]
        self.assertIn("-replace", door)
        self.assertIn("WriteAllText($LiteralPath, $Normalised", door)
        self.assertNotIn("WriteAllText($LiteralPath, $Text", door)


if __name__ == "__main__":
    unittest.main()
