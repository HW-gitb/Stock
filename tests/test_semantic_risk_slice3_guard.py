"""CI regression guard for the Slice-3 reconciliation (LANDED 2026-06-20).

History: the A-short semantic-risk advisory layer was deliberately isolated from production `egs_main`,
leaving two debts tracked in the register as `DEFERRED, DO NOT CLOSE`:
  (1) DeepSeek `POL-RISK-VETO` — an LLM(DeepSeek)+web → industry production hard-veto, contradicting the
      "web/LLM advisory-only, never auto hard-veto" principle (and basically inert after the sina source died);
  (2) cninfo regulatory check — deleted production candidates on keyword hit AND false-cleared (cninfo_flag
      "通过") on HTTP-200-but-empty responses (a suspect `stock=code,market` request form).

Slice 3 landed (2026-06-20, user-directed): `POL-RISK-VETO` + its prompt-injection helpers REMOVED;
cninfo downgraded to advisory-only (no production candidate deletion) + the 200-empty false-clear fixed
(empty → `未核查`, not `通过`). Making cninfo a real production regulatory veto is a SEPARATE opt-in slice.

This guard therefore flips from a "tracker-present anti-forget" check to a "stays-resolved regression"
check: the register must still RECORD the reconciliation (not silently drop it), and `egs_main` must NOT
reintroduce the production `POL-RISK-VETO` / cninfo `REGULATOR-VETO` deletion.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EGS_MAIN = ROOT / "A-EGS" / "egs_main.py"
REGISTER = ROOT / "docs" / "system_risk_register.md"

TRACKER_TITLE = "A-short semantic-risk layer ↔ production reconciliation"
RESOLVED_MARKER = "Slice 3 reconciliation"
# Code symbols that exist ONLY if the removed POL-RISK production hard-veto is reintroduced (the historical
# explanatory comments deliberately still say "POL-RISK-VETO" / "DeepSeek", so we ban code symbols, not prose).
POL_RISK_CODE_SYMBOLS = ("_build_policy_risk_prompt", "_fetch_eastmoney_news", "pol_risk_inds", "mask_pol")
# Active route/design docs must reflect the Slice-3 resolution (POL-RISK removed / cninfo advisory),
# not describe the pre-Slice-3 production hard-veto as current/pending (R-ASHORT-SLICE3-SEMANTIC-ROUTE-DOC-DRIFT).
ACTIVE_SLICE3_DOCS = (
    ROOT / "docs" / "CURRENT.md",
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "a_short_semantic_risk_coverage.md",
    ROOT / "docs" / "a_short_semantic_risk_top15_enrichment_design_20260612.md",
    ROOT / "docs" / "a_short_theme_overlay_phase5_design_spec_20260610.md",
)
SLICE3_DOC_RESOLUTION_MARKER = "Slice 3 已 land"

# Negative drift guard (R-ASHORT-SLICE3-SEMANTIC-ROUTE-DOC-DRIFT, re-审查 round): the positive marker
# above proves resolution is *recorded*, but a doc could keep the marker AND still carry pre-Slice-3
# prose elsewhere. These phrases assert the OLD production hard-veto / deferred-Slice-3 state as
# current or pending. An occurrence is a VIOLATION unless it is qualified as historical (a line-level
# marker) or the whole doc carries a doc-level SUPERSEDED banner (an archival design spec).
STALE_CURRENT_PATTERNS = (
    "待决 Slice 3",
    "Slice 3 待决",
    "不碰 production stage3",
    "production stage3 隔离",
    "production stage3 不动",
    "production stage3 untouched",
    "不改 DeepSeek POL-RISK-VETO",
)
HISTORICAL_QUALIFIER_TOKENS = (
    "历史设计态", "已移除", "已降", "降为 advisory", "已拆", "已处置",
    "superseded", "SUPERSEDED", "Slice 3 已 land", "已由 Slice 3 reconciliation", "已 superseded",
)


def _has_doc_level_historical_banner(text: str) -> bool:
    # a prominent top banner declaring downstream prose historical (e.g. the Top15 design spec)
    # exempts that doc's archival body from the line-level negative scan.
    for ln in text.splitlines():
        if "SUPERSEDED-IN-PART" in ln:
            return True
        if "下文" in ln and "历史设计态" in ln:
            return True
    return False


def _unqualified_stale_slice3_claims(text: str):
    banner = _has_doc_level_historical_banner(text)
    out = []
    for lineno, ln in enumerate(text.splitlines(), 1):
        for pat in STALE_CURRENT_PATTERNS:
            if pat in ln:
                line_qualified = any(q in ln for q in HISTORICAL_QUALIFIER_TOKENS)
                if not line_qualified and not banner:
                    out.append((lineno, pat))
    return out


def _egs_main_is_post_slice3() -> bool:
    egs = EGS_MAIN.read_text(encoding="utf-8")
    return "REGULATOR-ADVISORY" in egs and not any(sym in egs for sym in POL_RISK_CODE_SYMBOLS)


class Slice3ReconciliationGuard(unittest.TestCase):
    def test_register_records_slice3_resolution_not_silently_dropped(self):
        register = REGISTER.read_text(encoding="utf-8")
        self.assertIn(TRACKER_TITLE, register,
                      "the Slice-3 reconciliation record must not be silently dropped from the register")
        self.assertIn(RESOLVED_MARKER, register,
                      "register must record the Slice-3 reconciliation (POL-RISK removed / cninfo downgraded)")

    def test_egs_main_has_no_production_pol_risk_veto(self):
        egs = EGS_MAIN.read_text(encoding="utf-8")
        for sym in POL_RISK_CODE_SYMBOLS:
            self.assertNotIn(sym, egs,
                             f"Slice-3-removed POL-RISK production hard-veto code symbol reappeared: {sym!r}")

    def test_egs_main_cninfo_is_advisory_not_production_veto(self):
        egs = EGS_MAIN.read_text(encoding="utf-8")
        # cninfo downgraded: the production-deletion marker is gone; the advisory marker is present.
        self.assertNotIn("REGULATOR-VETO", egs,
                         "cninfo REGULATOR-VETO production deletion must stay downgraded to advisory")
        self.assertIn("REGULATOR-ADVISORY", egs,
                      "cninfo advisory marker missing (downgrade should keep an advisory cninfo_flag)")
        # the false-clear fix: 200-empty announcements must NOT fall through to a clear verdict.
        self.assertIn("修假清白", egs,
                      "cninfo 200-empty false-clear fix marker missing (empty must map to 未核查, not 通过)")

    def test_active_route_docs_reflect_slice3_resolution(self):
        # R-ASHORT-SLICE3-SEMANTIC-ROUTE-DOC-DRIFT: active route/design docs must carry the Slice-3
        # resolution marker (POL-RISK removed / cninfo advisory). Reverting a doc to the pre-Slice-3
        # production hard-veto description drops the marker → FAIL (cross-LLM mis-routing tripwire).
        missing = [p.name for p in ACTIVE_SLICE3_DOCS
                   if SLICE3_DOC_RESOLUTION_MARKER not in p.read_text(encoding="utf-8")]
        self.assertEqual(missing, [], f"active Slice-3 route/design docs missing resolution marker "
                         f"{SLICE3_DOC_RESOLUTION_MARKER!r} (pre-Slice-3 production hard-veto drift): {missing}")

    def test_active_route_docs_have_no_unqualified_stale_slice3_claims(self):
        # R-ASHORT-SLICE3-SEMANTIC-ROUTE-DOC-DRIFT (re-审查 round, negative direction): once egs_main is
        # in the post-Slice-3 state, active route docs may NOT present the old production hard-veto /
        # deferred-Slice-3 tracker as current/pending without a historical qualifier or doc-level
        # SUPERSEDED banner. (Conditional on egs_main: if code is reverted pre-Slice-3, the egs_main
        # code guards above fire instead, so this doc guard would be premature.)
        if not _egs_main_is_post_slice3():
            self.skipTest("egs_main not in post-Slice-3 state; the egs_main code guards fire instead")
        offenders = {p.name: _unqualified_stale_slice3_claims(p.read_text(encoding="utf-8"))
                     for p in ACTIVE_SLICE3_DOCS}
        offenders = {k: v for k, v in offenders.items() if v}
        self.assertEqual(offenders, {}, f"active route docs carry UNQUALIFIED pre-Slice-3 claims "
                         f"(current/pending hard-veto without historical marker): {offenders}")

    def test_stale_slice3_claim_checker_flags_planted_failure(self):
        # planted-failure control: a living route doc reverted to the deferred/old-veto wording (no
        # historical qualifier, no banner) MUST be flagged — the checker is not vacuously green.
        planted = "剩余:语义→生产硬否决升级(待决 Slice 3,见下条)、cninfo 命中→生产硬否决。\n"
        self.assertTrue(_unqualified_stale_slice3_claims(planted),
                        "checker must flag an unqualified pre-Slice-3 claim")

    def test_stale_slice3_claim_checker_allows_historical_prose(self):
        # false-positive controls (Codex-required): historical prose that carries a line-level
        # qualifier OR sits under a doc-level SUPERSEDED banner must NOT fail.
        line_qualified = "原『与 production stage3 隔离 / 不改 DeepSeek POL-RISK-VETO』为历史设计态。\n"
        self.assertEqual(_unqualified_stale_slice3_claims(line_qualified), [],
                         "line-level historical qualifier must exempt the archival phrase")
        under_banner = ("> SUPERSEDED-IN-PART(Slice 3 已 land):下文一切「不碰 production stage3」均为历史设计态。\n"
                        "本切片不碰 production stage3;不改 DeepSeek POL-RISK-VETO;Slice 3 待决。\n")
        self.assertEqual(_unqualified_stale_slice3_claims(under_banner), [],
                         "doc-level SUPERSEDED banner must exempt the archival design body")


if __name__ == "__main__":
    unittest.main()
