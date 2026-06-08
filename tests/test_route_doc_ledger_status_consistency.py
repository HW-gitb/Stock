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


if __name__ == "__main__":
    unittest.main()
