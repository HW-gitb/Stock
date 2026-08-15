from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "runners" / "weekly_screening.ps1"


class RegimeSidecarWiringTests(unittest.TestCase):
    def test_regime_runner_receives_current_revision_id_in_sidecar_only(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        stage = text[text.index("# --- Stage 5:"):text.index("$RegimeOutput = @(& $PythonExe @RegimeArgs 2>&1)")]
        self.assertIn("'--sidecar-outcome-run-revision-id', $RunRevisionId", stage)
        self.assertNotIn("'--run-revision-id', $RunRevisionId", stage)


if __name__ == "__main__":
    unittest.main()
