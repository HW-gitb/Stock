"""CI anti-forget guard: once the A-short semantic-risk ADVISORY layer code exists, the
production-reconciliation (Slice 3) tracker must NOT be silently dropped from the risk register.

Context (design `docs/a_short_semantic_risk_top15_enrichment_design_20260612.md` §8 + the register
`deferred-open` item): the advisory layer is deliberately isolated from production egs_main; two
debts (DeepSeek POL-RISK-VETO legacy-conflict + cninfo dedup) must be reconciled in a later Slice 3.
The design asked for a build-blocking guard "the moment the advisory layer exists".

Interpretation (deliberate, documented): a LITERAL "fail until Slice 3 is done" would block the very
staged delivery the same design mandates (Slice 3 comes AFTER the advisory layer is built+validated).
So this guard enforces the achievable, sound invariant: **while advisory-layer code exists, the
register MUST still carry the reconciliation tracker** (it can be `deferred-open` now, or `resolved`
once Slice 3 actually lands — but it can never be silently deleted). This is the same spirit as
`tests.test_route_doc_ledger_status_consistency`: a durable cross-LLM doc-consistency tripwire.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADVISORY_RUNNER = ROOT / "runners" / "a_short_semantic_risk_summary.py"
REGISTER = ROOT / "docs" / "system_risk_register.md"

TRACKER_TITLE = "A-short semantic-risk layer ↔ production reconciliation"
TRACKER_MARKER = "DEFERRED, DO NOT CLOSE"
SLICE3_REFS = ("Slice 3", "POL-RISK-VETO", "cninfo")


class Slice3ReconciliationGuard(unittest.TestCase):
    def test_advisory_layer_keeps_slice3_tracker_present(self):
        if not ADVISORY_RUNNER.exists():
            self.skipTest("advisory layer not built yet; guard inactive (would be vacuously green)")
        register = REGISTER.read_text(encoding="utf-8")
        self.assertIn(TRACKER_TITLE, register,
                      "advisory layer exists but the Slice-3 production-reconciliation tracker is "
                      "missing from the risk register — it must not be silently dropped.")
        self.assertIn(TRACKER_MARKER, register,
                      "the reconciliation tracker lost its DO-NOT-CLOSE marker while advisory code "
                      "still exists; Slice 3 (cninfo dedup + DeepSeek POL-RISK-VETO legacy-conflict) "
                      "must be reconciled, not forgotten.")
        # the tracker must still spell out WHAT Slice 3 has to reconcile (anti-vagueness)
        for ref in SLICE3_REFS:
            self.assertIn(ref, register, f"reconciliation tracker no longer references {ref!r}")


if __name__ == "__main__":
    unittest.main()
