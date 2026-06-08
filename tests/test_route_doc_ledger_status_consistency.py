from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "research" / "ledgers"
# Durable route / index docs that must not restate a stale ledger spend-state.
ROUTE_DOCS = [
    ROOT / "research" / "README.md",
    ROOT / "docs" / "README.md",
    ROOT / "docs" / "CURRENT.md",
]

# Extra aliases for spent lines whose route-doc rows often name a runner / schema / packet instead of
# the ledger file. Auto-derived aliases cover most preregistration/result paths; these keep historical
# A-long packet/runner rows from escaping the guard after their singleton ledger is spent.
STATIC_SPENT_ROUTE_ALIASES = {
    "a_long_signal_search_program_test_budget_ledger_20260604.json": [
        "research/preregistrations/a_long_signal_search_preregistration_20260604.json",
        "research/results/a_long_signal_search_20260604/execution_summary.json",
        "runners/a_long_full_main_board_signal_search.py",
        "schemas/a_long_signal_search_execution_summary.schema.json",
        "schemas/a_long_full_main_board_signal_search_execution_packet.schema.json",
        "docs/a_long_full_main_board_signal_search_execution_packet_20260605.json",
    ],
    "a_long_large_cap_pure_quality_program_test_budget_ledger_20260607.json": [
        "research/preregistrations/a_long_large_cap_pure_quality_20260607.json",
        "research/results/a_long_large_cap_pure_quality_20260607/execution_summary.json",
        "runners/a_long_large_cap_pure_quality_signal_search.py",
        "schemas/a_long_large_cap_pure_quality_signal_search_execution_summary.schema.json",
        "schemas/a_long_large_cap_pure_quality_signal_search_execution_packet.schema.json",
        "docs/a_long_large_cap_pure_quality_signal_search_execution_packet_20260607.json",
        "schemas/a_long_large_cap_market_cap_field_probe_packet.schema.json",
        "docs/a_long_large_cap_market_cap_field_probe_packet_20260607.json",
        "runners/a_long_large_cap_market_cap_field_probe.py",
        "schemas/a_long_large_cap_market_cap_materialization_packet.schema.json",
        "docs/a_long_large_cap_market_cap_materialization_packet_20260607.json",
        "runners/a_long_large_cap_market_cap_materialization.py",
        "schemas/a_long_large_cap_market_cap_audit_packet.schema.json",
        "docs/a_long_large_cap_market_cap_audit_packet_20260607.json",
        "runners/a_long_large_cap_market_cap_audit.py",
    ],
    "a_long_large_cap_cash_conversion_program_test_budget_ledger_20260607.json": [
        "research/preregistrations/a_long_large_cap_cash_conversion_20260607.json",
        "research/results/a_long_large_cap_cash_conversion_20260607/execution_summary.json",
        "runners/a_long_large_cap_cash_conversion_signal_search.py",
        "schemas/a_long_large_cap_cash_conversion_signal_search_execution_summary.schema.json",
    ],
    "a_long_large_cap_low_volatility_program_test_budget_ledger_20260608.json": [
        "research/preregistrations/a_long_large_cap_low_volatility_20260608.json",
        "research/results/a_long_large_cap_low_volatility_20260608/execution_summary.json",
        "runners/a_long_large_cap_low_volatility_signal_search.py",
        "schemas/a_long_large_cap_low_volatility_signal_search_execution_summary.schema.json",
    ],
}


# Phrases that assert a singleton ledger is UNSPENT / not-yet-run. They must never appear on a
# route-doc line that references an already-SPENT line by ledger, result, preregistration, runner,
# schema, or packet alias. This is the mechanical guard against recurring route-doc state-transition
# drift: durable index rows kept describing executed/spent A-long lines as "pending / zero spent"
# because each transition only updated the active line and sibling rows silently rotted.
SPENT_CONTRADICTING_PHRASES = [
    "zero spent",
    "one pending test",
    "one pending / zero spent",
    "pending / zero-spent",
    "planned not-reviewed",
    "not-reviewed signal-search test",
    "unspent singleton ledger",
    "unspent large-cap singleton ledger",
    "reverted to unspent",
    "future result path",
    "future execution reads",
    "future execution, only after",
    "will read local raw",
    "a rerun still requires",
    "spends this singleton once",
    "spend the singleton ledger once",
    "spends the singleton ledger exactly once",
    "first reviewed signal-search execution spends",
    "no valid a-long alpha result",
    "no valid signal run is authorized",
]


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _strip_date_suffix(name: str) -> str:
    return re.sub(r"_\d{8}$", "", name)


def _ledger_payloads() -> dict[str, dict]:
    payloads: dict[str, dict] = {}
    for path in sorted(LEDGER_DIR.glob("*program_test_budget_ledger*.json")):
        payloads[path.name] = json.loads(path.read_text(encoding="utf-8"))
    return payloads


def _ledger_spent_map() -> dict[str, bool]:
    return {
        name: int((data.get("budget_policy") or {}).get("tests_spent_count", 0)) > 0
        for name, data in _ledger_payloads().items()
    }


def _aliases_from_ref(ref: str) -> set[str]:
    aliases = {ref, Path(ref).name}
    if ref.endswith("/execution_summary.json"):
        result_dir = Path(ref).parent.name
        stem = _strip_date_suffix(result_dir)
        aliases.update(
            {
                result_dir,
                f"runners/{stem}_signal_search.py",
                f"schemas/{stem}_signal_search_execution_summary.schema.json",
                f"tests/test_{stem}_signal_search.py",
                f"tests/schema/test_{stem}_signal_search_schema.py",
            }
        )
    return aliases


def _spent_route_aliases() -> dict[str, set[str]]:
    aliases_by_ledger: dict[str, set[str]] = {}
    for name, data in _ledger_payloads().items():
        tests_spent = int((data.get("budget_policy") or {}).get("tests_spent_count", 0))
        if tests_spent <= 0:
            continue
        aliases = {name, f"research/ledgers/{name}"}
        family_id = data.get("family_id")
        artifact_id = data.get("artifact_id")
        if isinstance(family_id, str):
            aliases.add(family_id)
        if isinstance(artifact_id, str):
            aliases.add(artifact_id)
        for item in list(data.get("test_spend_log") or []) + list(data.get("planned_tests") or []):
            if not isinstance(item, dict):
                continue
            for key in ("result_ref", "planned_result_ref", "preregistration_ref", "planned_preregistration_ref"):
                ref = item.get(key)
                if isinstance(ref, str):
                    aliases.update(_aliases_from_ref(ref))
        aliases.update(STATIC_SPENT_ROUTE_ALIASES.get(name, []))
        aliases_by_ledger[name] = {alias.lower() for alias in aliases if alias}
    return aliases_by_ledger


def _find_spent_state_violations(doc_lines: dict[str, list[str]]) -> list[str]:
    aliases_by_ledger = _spent_route_aliases()
    violations: list[str] = []
    for doc_name, lines in doc_lines.items():
        for lineno, line in enumerate(lines, start=1):
            lower = line.lower()
            matched_phrases = [phrase for phrase in SPENT_CONTRADICTING_PHRASES if phrase in lower]
            if not matched_phrases:
                continue
            for ledger_name, aliases in aliases_by_ledger.items():
                matched_aliases = sorted(alias for alias in aliases if alias in lower)
                if not matched_aliases:
                    continue
                for phrase in matched_phrases:
                    violations.append(
                        f"{doc_name}:{lineno} references SPENT line {ledger_name} via "
                        f"'{matched_aliases[0]}' but still says '{phrase}'"
                    )
    return violations


# docs/CURRENT.md durable pointer sections. Per AGENTS.md route-doc v3, live current-state restatement
# belongs in §0 + top docs/SESSION_LOG.md + the execution summaries; durable zones like §1 (目标) and §5
# (下一步) must stay stable pointers and must NOT restate per-round result metrics (t-stat, mean excess,
# drawdown, cohort count, concentration). §0 (live restatement) and §3 (standing strategy conclusions,
# which legitimately carry numbers) are intentionally NOT scanned. This guards R-EP-CURRENT-DURABLE-
# METRIC-DUPLICATION so the closeout drift class fails automatically next time.
CURRENT_DOC = ROOT / "docs" / "CURRENT.md"
DURABLE_POINTER_SECTION_PREFIXES = ("## 1.", "## 5.")
DURABLE_METRIC_PATTERNS = [
    re.compile(r"`[+-]?\d+\.\d+`"),            # backtick-wrapped decimal: t-stat / mean excess / drawdown / concentration
    re.compile(r"HAC\s*t", re.IGNORECASE),     # HAC t-stat restatement
    re.compile(r"mean\s*net\s*excess", re.IGNORECASE),
    re.compile(r"\d+\s*cohort", re.IGNORECASE),  # cohort count restatement
]


def _current_durable_pointer_lines() -> list[tuple[int, str]]:
    if not CURRENT_DOC.exists():
        return []
    collected: list[tuple[int, str]] = []
    in_section = False
    for lineno, line in enumerate(CURRENT_DOC.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("## "):
            in_section = stripped.startswith(DURABLE_POINTER_SECTION_PREFIXES)
            continue
        if in_section:
            collected.append((lineno, line))
    return collected


def _find_durable_metric_violations(numbered_lines: list[tuple[int, str]]) -> list[str]:
    violations: list[str] = []
    for lineno, line in numbered_lines:
        for pat in DURABLE_METRIC_PATTERNS:
            if pat.search(line):
                violations.append(
                    f"docs/CURRENT.md:{lineno} durable pointer zone restates a result metric "
                    f"(matched /{pat.pattern}/): {line.strip()[:90]}"
                )
                break
    return violations


# Transient review/commit-cycle wording = LIVE workflow position (who reviews next, pending / awaiting,
# before-commit, routed-to, uncommitted, result-closeout). It must live ONLY in docs/SESSION_LOG.md top,
# and must NOT appear ANYWHERE in docs/CURRENT.md (header, preamble, §0, or any section) because CURRENT
# is durable and any such phrase goes stale at the very next state transition. The earlier guards were
# SECTION-scoped (a ledger filename, then §1/§5), so the same drift kept relocating to the next
# un-guarded spot (research/README -> contract rows -> §1/§5 -> header/§0). This scan is WHOLE-DOCUMENT
# and location-independent — the permanent cure for the recurring route-doc drift class
# (R-EP-CURRENT-TRANSIENT-GATE-WORDING). CURRENT may state SETTLED facts (verdict / metrics-in-§0 /
# spent / closed); it may never state where we are in the review/commit cycle.
# STRICT = unambiguous transient line-state wording. The WHOLE-DOCUMENT scan applies to docs/CURRENT.md
# ONLY (a live snapshot that must stay settled-only). The READMEs describe the review PROCESS in prose,
# so a whole-doc scan there would false-positive ("pending review" / "routed to ... for review"); README
# transient drift is instead caught by the ALIAS-SCOPED regex scan (_readme_alias_scoped_transient_
# violations), which applies these same STRICT + synonym patterns ONLY to README lines that reference a
# SPENT ledger's alias (precise route/artifact-row scope, no prose false-positive).
# `pending`/`awaiting` still require a review/commit object as a second safety.
STRICT_TRANSIENT_GATE_PATTERNS = [
    re.compile(r"待\s*Codex"),
    re.compile(r"待\s*`?(审查|提交|复审|评审|执行)"),
    re.compile(r"(待审查|待提交|待复审|待评审|待执行)"),
    re.compile(r"尚未\s*(提交|审查|入库|复审|执行)"),
    re.compile(r"等待\s*(审查|提交|复审|执行|Codex)"),
    re.compile(r"pending\s+(re-?\s*)?(审查|review|commit|提交|复审)", re.IGNORECASE),
    re.compile(r"awaiting\s+(re-?\s*)?(审查|review|commit|复审)", re.IGNORECASE),
    re.compile(r"routed to Codex", re.IGNORECASE),
    re.compile(r"result-closeout", re.IGNORECASE),
    re.compile(r"before (the )?(next )?(result )?commit", re.IGNORECASE),
    re.compile(r"uncommitted", re.IGNORECASE),
]
# SYNONYM = the SAME gate concept written as a next-command / who-reviews / who-commits / who-executes
# sequence (R-EP-CURRENT-GATE-SYNONYM-GUARD-GAP). Scanned in docs/CURRENT.md ONLY — the READMEs legitimately
# describe the Claude->Codex->Claude review/execute process, so these would false-positive there. NOTE: a
# finite phrase list reduces but cannot fully eliminate the synonym leak; Codex review + the AGENTS.md
# route-doc v3 behavioral rule are the concept-level backstop.
CURRENT_ONLY_SYNONYM_PATTERNS = [
    re.compile(r"下一条命令"),
    re.compile(r"下一步[^。；;\n]{0,16}命令"),
    re.compile(r"谁\s*(审查|审|提交|复审|执行)"),
    re.compile(r"由\s*Codex\s*审"),
    re.compile(r"(随后|然后|接着|再由?)\s*Claude\s*`?(提交|执行)"),
    re.compile(r"Claude\s*`?(提交|执行)"),
]


def _numbered_lines(path: Path) -> list[tuple[int, str]]:
    if not path.exists():
        return []
    return list(enumerate(path.read_text(encoding="utf-8").splitlines(), start=1))


def _find_transient_gate_hits(
    numbered_lines: list[tuple[int, str]], patterns: list[re.Pattern]
) -> list[tuple[int, str, str]]:
    hits: list[tuple[int, str, str]] = []
    for lineno, line in numbered_lines:
        for pat in patterns:
            if pat.search(line):
                hits.append((lineno, pat.pattern, line))
                break
    return hits


def _current_transient_gate_violations() -> list[str]:
    """Whole-document scan of docs/CURRENT.md ONLY (a live snapshot -> settled facts only). README
    transient drift is handled by the alias-scoped README scan (the SAME strict+synonym regex, applied
    only to lines referencing a SPENT line's alias), not here, to avoid false-positives on README
    review-process prose."""
    violations: list[str] = []
    lines = _numbered_lines(CURRENT_DOC)
    for patterns, label in (
        (STRICT_TRANSIENT_GATE_PATTERNS, "review/commit-cycle wording"),
        (CURRENT_ONLY_SYNONYM_PATTERNS, "next-command / who-reviews / who-commits / who-executes synonym"),
    ):
        for lineno, pattern, line in _find_transient_gate_hits(lines, patterns):
            violations.append(
                f"docs/CURRENT.md:{lineno} carries a TRANSIENT {label} (matched /{pattern}/) — "
                f"the live gate belongs only in docs/SESSION_LOG.md top: {line.strip()[:90]}"
            )
    return violations


README_TRANSIENT_SCAN_DOCS = [
    ROOT / "research" / "README.md",
    ROOT / "docs" / "README.md",
]


def _alias_scoped_transient_hits(
    numbered_lines: list[tuple[int, str]], aliases: set, patterns: list[re.Pattern]
) -> list[tuple[int, str, str]]:
    """Hits where a line BOTH references a SPENT line's alias AND matches a transient-gate regex.
    Alias-scoping means README review-process prose (no spent alias) is never flagged, while the full
    strict+synonym regex (incl no-space `待Codex` and who-reviews / who-commits / who-executes synonyms)
    still catches drift on spent-line rows — closing R-ROUTEDOC-README-SYNONYM-GUARD."""
    hits: list[tuple[int, str, str]] = []
    for lineno, line in numbered_lines:
        lower = line.lower()
        if not any(alias in lower for alias in aliases):
            continue
        for pat in patterns:
            if pat.search(line):
                hits.append((lineno, pat.pattern, line))
                break
    return hits


def _readme_alias_scoped_transient_violations() -> list[str]:
    aliases: set = set()
    for alias_set in _spent_route_aliases().values():
        aliases |= alias_set
    patterns = STRICT_TRANSIENT_GATE_PATTERNS + CURRENT_ONLY_SYNONYM_PATTERNS
    violations: list[str] = []
    for path in README_TRANSIENT_SCAN_DOCS:
        if not path.exists():
            continue
        rel = _relative(path)
        for lineno, pattern, line in _alias_scoped_transient_hits(_numbered_lines(path), aliases, patterns):
            violations.append(
                f"{rel}:{lineno} references a SPENT line's alias AND carries transient gate wording "
                f"(matched /{pattern}/) — move the live gate to docs/SESSION_LOG.md top: {line.strip()[:90]}"
            )
    return violations


class RouteDocLedgerStatusConsistencyTest(unittest.TestCase):
    def test_ledgers_are_discoverable(self) -> None:
        spent = _ledger_spent_map()
        self.assertTrue(spent, "expected at least one program-test-budget ledger under research/ledgers/")

    def test_no_route_doc_describes_a_spent_ledger_as_unspent(self) -> None:
        doc_lines = {
            _relative(doc): doc.read_text(encoding="utf-8").splitlines()
            for doc in ROUTE_DOCS
            if doc.exists()
        }
        violations = _find_spent_state_violations(doc_lines)
        self.assertEqual(
            violations,
            [],
            "route-doc ledger-status drift detected (a spent singleton line is described as unspent/"
            "pending/future-spend); fix the row to a stable terminal pointer and delegate live state to "
            "the ledger file + docs/SESSION_LOG.md + the execution summary:\n" + "\n".join(violations),
        )

    def test_guard_catches_contract_style_stale_row_without_ledger_filename(self) -> None:
        stale_contract_row = (
            "- `schemas/a_long_signal_search_execution_summary.schema.json` / "
            "`runners/a_long_full_main_board_signal_search.py` - A-long signal-search contract; "
            "it validates an unspent singleton ledger before future execution reads local raw."
        )
        violations = _find_spent_state_violations({"research/README.md": [stale_contract_row]})
        self.assertTrue(violations, "expected contract-style stale row to be caught without ledger filename")

    def test_current_durable_pointer_sections_do_not_restate_result_metrics(self) -> None:
        violations = _find_durable_metric_violations(_current_durable_pointer_lines())
        self.assertEqual(
            violations,
            [],
            "docs/CURRENT.md durable pointer zones (§1/§5) restate per-round result metrics; move metrics "
            "to §0 / docs/SESSION_LOG.md top / the execution summary and keep §1/§5 as stable pointers:\n"
            + "\n".join(violations),
        )

    def test_durable_metric_guard_catches_planted_metric_line(self) -> None:
        planted = [
            (1, "- `ep_value` `falsified` with HAC t `2.17`, mean net excess `+0.108`, 56 cohorts, concentration `0.378` > `0.35`."),
        ]
        self.assertTrue(
            _find_durable_metric_violations(planted),
            "expected a planted durable-zone result-metric line to be caught",
        )

    def test_current_has_no_transient_gate_wording(self) -> None:
        violations = _current_transient_gate_violations()
        self.assertEqual(
            violations,
            [],
            "docs/CURRENT.md carries transient review/commit-cycle wording (pending review / before commit / "
            "routed to Codex / result-closeout / 待审查 / uncommitted / next-command / who-reviews / who-commits / "
            "who-executes). CURRENT is durable — move ALL live workflow-gate state to docs/SESSION_LOG.md top:\n"
            + "\n".join(violations),
        )

    def test_transient_gate_guard_catches_planted_phrases_and_synonyms(self) -> None:
        # Literal phrases anywhere (header / §0 / §5) AND same-meaning synonyms (incl who-executes) caught.
        planted = [
            (2, "**最后更新**：... result-closeout 待 Codex `审查`；实时状态见 §0"),
            (9, "- 2026-06-08 ... the result-closeout is routed to Codex `审查` before the result commit."),
            (95, "- ep_value runner committed; closeout is uncommitted and pending re-审查."),
            (12, "- 下一条命令是 Claude `提交`。"),
            (13, "- 由 Codex 审,随后 Claude 提交。"),
            (14, "- 当前 gate:谁审 / 谁提交 见此。"),
            (15, "- 下一步 Claude `执行` 这条线。"),
            (16, "- 当前 gate:谁执行 见此。"),
            (17, "- 待复审 后再 `执行`。"),
        ]
        hits = _find_transient_gate_hits(planted, STRICT_TRANSIENT_GATE_PATTERNS + CURRENT_ONLY_SYNONYM_PATTERNS)
        self.assertEqual(
            len(hits),
            len(planted),
            "expected every planted transient-gate line — literal AND synonym, incl 执行 — to be caught",
        )

    def test_strict_transient_patterns_do_not_false_positive_on_readme_process_prose(self) -> None:
        # The READMEs legitimately describe the review process; strict patterns must not fire on prose
        # like "pending Optional disposition" or generic role descriptions.
        benign = [
            (1, "| pending Optional disposition | `docs/SESSION_LOG.md` top 1-3 entries |"),
            (2, "- Claude = Designer + Implementer; Codex = Independent Reviewer; 用户 = Final Approver."),
            (3, "- preregistration goes through independent review before execution."),
        ]
        self.assertEqual(
            _find_transient_gate_hits(benign, STRICT_TRANSIENT_GATE_PATTERNS),
            [],
            "strict transient-gate patterns must not false-positive on README process prose",
        )

    def _a_spent_alias(self) -> str:
        aliases: set = set()
        for alias_set in _spent_route_aliases().values():
            aliases |= alias_set
        self.assertTrue(aliases, "expected at least one spent ledger to derive an alias from")
        return sorted(aliases)[0]

    def test_readme_alias_scoped_transient_is_clean(self) -> None:
        violations = _readme_alias_scoped_transient_violations()
        self.assertEqual(
            violations,
            [],
            "a README row that references a SPENT line's alias also carries transient review/commit-cycle "
            "wording; convert it to a stable terminal pointer and delegate live gate to docs/SESSION_LOG.md "
            "top:\n" + "\n".join(violations),
        )

    def test_alias_scoped_transient_catches_nospace_and_synonyms(self) -> None:
        # The README alias-scoped scan uses the SAME strict+synonym regex as CURRENT, so no-space and
        # synonym variants on a spent-alias row are all caught (R-ROUTEDOC-README-SYNONYM-GUARD).
        alias = self._a_spent_alias()
        patterns = STRICT_TRANSIENT_GATE_PATTERNS + CURRENT_ONLY_SYNONYM_PATTERNS
        planted = [
            (1, f"- `{alias}` 待Codex审查"),  # no space
            (2, f"- `{alias}`: 下一条命令是 Claude `提交`。"),
            (3, f"- `{alias}`: 由 Codex 审,随后 Claude 提交。"),
            (4, f"- `{alias}`: 谁执行 这条线?"),
            (5, f"- `{alias}`: Claude 执行 之。"),
        ]
        hits = _alias_scoped_transient_hits(planted, {alias.lower()}, patterns)
        self.assertEqual(
            len(hits),
            len(planted),
            "every spent-alias row variant (no-space + synonyms incl 执行) must be caught",
        )

    def test_alias_scoped_transient_ignores_prose_without_alias(self) -> None:
        # README review-process prose that does NOT reference a spent alias must not be flagged.
        patterns = STRICT_TRANSIENT_GATE_PATTERNS + CURRENT_ONLY_SYNONYM_PATTERNS
        benign = [
            (1, "- preregistration goes through independent review before execution; items pending review go to SESSION_LOG."),
            (2, "- 流程:Claude 改 → Codex 审 → Claude 提交(描述,不指向具体已花线)。"),
        ]
        self.assertEqual(
            _alias_scoped_transient_hits(benign, {"a_long_large_cap_ep_value_v1"}, patterns),
            [],
            "process prose without a spent-line alias must not be flagged",
        )


if __name__ == "__main__":
    unittest.main()
