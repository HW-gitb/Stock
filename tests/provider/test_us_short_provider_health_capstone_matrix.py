from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_provider_health import (  # noqa: E402
    AUTHORIZED_SOURCES,
    CRITICAL_SOURCES,
    EMIT_ALLOWED_RUN_STATES,
    REQUIRED_HEALTH_KEYS,
    classify_provider_health,
    parse_provider_health_detail_line,
    provider_health_detail_line,
    validate_provider_health_facts,
)
from runners import us_short_weekly_capstone_stages as stages  # noqa: E402


TARGETS = ("AAPL", "MSFT")


def _status_outcome(*, blocked: bool = False, critical_failed: list[str] | None = None) -> dict:
    critical_failed = list(critical_failed or [])
    return {
        "per_source": {
            "ticker_reference": "ok" if not critical_failed or "ticker_reference" not in critical_failed else "down",
            "exchange_halt_feed": "ok" if "exchange_halt_feed" not in critical_failed else "down",
            "sec_8k_item_103": "missing",
        },
        "failed_sources": sorted(set(critical_failed + ["sec_8k_item_103"])),
        "failed_count": len(set(critical_failed + ["sec_8k_item_103"])),
        "total_sources": 3,
        "critical_failed": sorted(set(critical_failed)),
        "critical_all_failed": blocked,
        "block_or_no_emit": blocked,
    }


def _yfinance_summary(*, successful: int = 2, parser_failed: int = 0, provider_status: str = "ok",
                      status: str = "completed", dependency_missing: bool = False) -> dict:
    attempted = successful + parser_failed
    return {
        "schema_name": "us_short_yfinance_grades_fetch_summary",
        "schema_version": "1.1.0",
        "scope": {
            "provider_status": provider_status,
            "status": status,
            "network_access_performed": attempted > 0,
            "provider_calls_performed": attempted > 0,
        },
        "decision_clock": {
            "expected_decision_date": "20260706",
            "source_as_of": "2026-07-06",
        },
        "preflight_gate": {
            "preflight_summary_path": "docs/us_short_batch5_full_candidate_pass2_preflight_summary_20260706.json",
            "target_count": len(TARGETS),
            "target_symbols_in_summary": False,
        },
        "execution": {
            "attempted_symbol_count": attempted,
            "successful_symbol_count": successful,
            "parser_failed_symbol_count": parser_failed,
            "fetch_error_count": 0,
            "rate_limit_or_crumb_failure_count": 0,
            "dependency_missing": dependency_missing,
            "resolver_rejection": None,
            "advisory_failure": None,
        },
    }


def _pass2(*, analyst_source: str = "yfinance") -> dict:
    rows = []
    for symbol in TARGETS:
        if analyst_source == "fmp":
            rows.append({"provider_id": "financial_modeling_prep", "endpoint_family": "grades",
                         "symbol": symbol, "status": "success"})
        rows.append({"provider_id": "sec_edgar", "endpoint_family": "submissions",
                     "symbol": symbol, "status": "success"})
        for family in ("reference_news", "stock_splits", "dividends"):
            rows.append({"provider_id": "massive", "endpoint_family": family,
                         "symbol": symbol, "status": "success"})
    return {
        "scope": {"yfinance_consumption_performed": analyst_source == "yfinance"},
        "decision_clock": {
            "expected_decision_date": "20260706", "source_as_of": "2026-07-06",
        },
        "preflight_gate": {
            "preflight_summary_path": "docs/us_short_batch5_full_candidate_pass2_preflight_summary_20260706.json",
        },
        "pass2_target_universe": {"target_count": len(TARGETS), "target_symbols": list(TARGETS)},
        "source_artifacts": {
            "analyst_grade_actions_consumed_from": (
                "yfinance_grade_actions" if analyst_source == "yfinance" else "fmp_analyst_grade_actions"
            ),
        },
        "endpoint_call_budget": {"fmp_grades_calls": len(TARGETS) if analyst_source == "fmp" else 0},
        "endpoint_results": rows,
    }


def _stage_results() -> dict:
    return {
        "universe_fetch": {
            "scope": {"status": "universe_fetch_and_pass1_completed"},
            "schema_version": "1.3.0",
            "pass1_result": {"needs_market_cap": []},
            "status_screening": {"status_source_outcome": _status_outcome()},
            "provider_health": {
                "overall_run_state": "usable_with_fallback",
                "status_sources": {"state": "clean", "outcome": _status_outcome()},
                "opportunistic_fallbacks": {
                    "yfinance_market_cap": {"needed_count": 0, "unresolved_count": 0}
                },
            },
        },
        "momentum_fetch": {
            "fetch_stats": {"sessions_with_data": 5, "min_sessions_required": 3},
            "coverage": {"eligible_count": len(TARGETS), "series_ticker_count": len(TARGETS),
                         "benchmarks_present": True},
        },
        "sic_fetch": {
            "classification": {"eligible_count": len(TARGETS), "sic_resolved_count": len(TARGETS),
                                "sic_missing_count": 0},
        },
        "pass2_fetch": _pass2(),
        "yfinance_grades_fetch": _yfinance_summary(),
        "vix_regime": {"http_status": 200, "vix_value": 18.0,
                        "vix_regime": stages.REGIMES[0], "vix_regime_is_unknown": False},
    }


def _projected() -> dict[str, str]:
    return stages.derive_capstone_provider_health(_stage_results())


class CapstoneProviderHealthMatrix(unittest.TestCase):
    def _with_completion(self, *, needs, completion):
        stages = _stage_results()
        stages["universe_fetch"]["pass1_result"]["needs_market_cap"] = list(needs)
        stages["universe_fetch"]["market_cap_completion"] = dict(completion)
        return stages

    def test_market_cap_completion_zero_and_43_rescued_are_ok(self):
        zero = self._with_completion(
            needs=[],
            completion={
                "needed_count": 0, "sec_companyfacts_target_count": 0, "sec_companyfacts_request_count": 0,
                "sec_companyfacts_rescued_count": 0, "yfinance_attempted_count": 0, "yfinance_rescued_count": 0,
                "massive_overview_attempted_count": 0, "massive_overview_rescued_count": 0,
                "final_unresolved_count": 0,
            },
        )
        self.assertEqual(stages._universe_market_cap_health(zero["universe_fetch"]),
                         ("universe_market_cap", "ok"))

        names = [f"P{idx:02d}X" for idx in range(43)]
        complete = self._with_completion(
            needs=[],
            completion={
                "needed_count": 43, "sec_companyfacts_target_count": 0, "sec_companyfacts_request_count": 0,
                "sec_companyfacts_rescued_count": 0, "yfinance_attempted_count": 43, "yfinance_rescued_count": 40,
                "massive_overview_attempted_count": 3, "massive_overview_rescued_count": 3,
                "final_unresolved_count": 0,
            },
        )
        self.assertEqual(stages._universe_market_cap_health(complete["universe_fetch"]),
                         ("universe_market_cap", "ok"))
        self.assertEqual(
            stages.derive_capstone_provider_health(complete)["universe_market_cap"], "ok",
        )

    def test_market_cap_completion_unresolved_is_degraded(self):
        summary = self._with_completion(
            needs=["UNRESOLVED"],
            completion={
                "needed_count": 1, "sec_companyfacts_target_count": 1, "sec_companyfacts_request_count": 1,
                "sec_companyfacts_rescued_count": 0, "yfinance_attempted_count": 1, "yfinance_rescued_count": 0,
                "massive_overview_attempted_count": 1, "massive_overview_rescued_count": 0,
                "final_unresolved_count": 1,
            },
        )
        self.assertEqual(stages._universe_market_cap_health(summary["universe_fetch"]),
                         ("universe_market_cap", "degraded"))

    def test_market_cap_completion_malformed_or_nonconserved_is_down(self):
        malformed = self._with_completion(
            needs=["A"],
            completion={"needed_count": 1},
        )
        self.assertEqual(stages._universe_market_cap_health(malformed["universe_fetch"]),
                         ("universe_market_cap", "down"))

        nonconserved = self._with_completion(
            needs=["A"],
            completion={
                "needed_count": 1, "sec_companyfacts_target_count": 0, "sec_companyfacts_request_count": 0,
                "sec_companyfacts_rescued_count": 1, "yfinance_attempted_count": 0, "yfinance_rescued_count": 1,
                "massive_overview_attempted_count": 0, "massive_overview_rescued_count": 0,
                "final_unresolved_count": 0,
            },
        )
        self.assertEqual(stages._universe_market_cap_health(nonconserved["universe_fetch"]),
                         ("universe_market_cap", "down"))

        rescue_exceeds_attempts = self._with_completion(
            needs=[],
            completion={
                "needed_count": 2, "sec_companyfacts_target_count": 0, "sec_companyfacts_request_count": 0,
                "sec_companyfacts_rescued_count": 0, "yfinance_attempted_count": 1, "yfinance_rescued_count": 2,
                "massive_overview_attempted_count": 0, "massive_overview_rescued_count": 0,
                "final_unresolved_count": 0,
            },
        )
        self.assertEqual(stages._universe_market_cap_health(rescue_exceeds_attempts["universe_fetch"]),
                         ("universe_market_cap", "down"))

    def test_committed_real_universe_summary_keeps_market_cap_fallback_noncritical(self):
        path = ROOT / "docs" / "us_short_universe_fetch_summary_20260730.json"
        summary = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(stages._universe_health(summary), ("universe_status", "ok"))
        self.assertEqual(stages._universe_market_cap_health(summary), ("universe_market_cap", "degraded"))

    def test_legacy_fmp_completion_shape_is_not_current_contract(self):
        summary = self._with_completion(
            needs=["A"],
            completion={
                "needed_count": 1, "sec_companyfacts_target_count": 1, "sec_companyfacts_request_count": 1,
                "sec_companyfacts_rescued_count": 0, "fmp_attempted_count": 1, "fmp_rescued_count": 1,
                "massive_overview_attempted_count": 0, "massive_overview_rescued_count": 0,
                "final_unresolved_count": 0,
            },
        )
        self.assertEqual(stages._universe_market_cap_health(summary["universe_fetch"]),
                         ("universe_market_cap", "down"))

    def test_universe_status_does_not_read_overall_run_state(self):
        summary = _stage_results()["universe_fetch"]
        summary["provider_health"]["overall_run_state"] = "blocked"
        self.assertEqual(stages._universe_health(summary), ("universe_status", "ok"))

    def test_missing_or_conflicting_universe_health_block_fails_closed(self):
        missing = _stage_results()["universe_fetch"]
        missing.pop("provider_health")
        self.assertEqual(stages._universe_health(missing), ("universe_status", "missing"))
        conflict = _stage_results()["universe_fetch"]
        conflict["provider_health"]["status_sources"]["outcome"]["failed_count"] = 99
        self.assertEqual(stages._universe_health(conflict), ("universe_status", "missing"))

    def test_projector_emits_exact_eight_raw_families(self):
        facts = _projected()
        self.assertEqual(tuple(facts), REQUIRED_HEALTH_KEYS)
        self.assertEqual(set(facts), set(AUTHORIZED_SOURCES))
        self.assertEqual(set(facts.values()), {"ok"})
        self.assertEqual(classify_provider_health(facts)["overall_run_state"], "clean")

    def test_each_producer_mutation_changes_only_its_family(self):
        base = _projected()
        mutations = {}

        universe = _stage_results()
        blocked = _status_outcome(blocked=True, critical_failed=["ticker_reference", "exchange_halt_feed"])
        universe["universe_fetch"]["status_screening"] = {"status_source_outcome": blocked}
        universe["universe_fetch"]["provider_health"]["status_sources"] = {
            "state": "blocked", "outcome": blocked,
        }
        mutations["universe_status"] = universe

        market_cap = _stage_results()
        market_cap["universe_fetch"]["pass1_result"]["needs_market_cap"] = ["AAPL"]
        market_cap["universe_fetch"]["provider_health"]["opportunistic_fallbacks"] = {
            "yfinance_market_cap": {"needed_count": 1, "unresolved_count": 1}
        }
        mutations["universe_market_cap"] = market_cap

        momentum = _stage_results()
        momentum["momentum_fetch"]["coverage"]["series_ticker_count"] = 1
        mutations["massive_momentum"] = momentum

        sic = _stage_results()
        sic["sic_fetch"]["classification"].update({"sic_resolved_count": 1, "sic_missing_count": 1})
        mutations["sec_sic"] = sic

        grades = _stage_results()
        grades["yfinance_grades_fetch"]["scope"]["status"] = "completed_with_fetch_errors"
        grades["yfinance_grades_fetch"]["execution"]["successful_symbol_count"] = 1
        grades["yfinance_grades_fetch"]["execution"]["parser_failed_symbol_count"] = 1
        mutations["analyst_grades"] = grades

        offering = _stage_results()
        offering["pass2_fetch"]["endpoint_results"] = [
            row for row in offering["pass2_fetch"]["endpoint_results"]
            if not (row["provider_id"] == "sec_edgar" and row["symbol"] == "MSFT")
        ]
        mutations["sec_offering_audit"] = offering

        events = _stage_results()
        for row in events["pass2_fetch"]["endpoint_results"]:
            if row["provider_id"] == "massive" and row["endpoint_family"] == "dividends" and row["symbol"] == "MSFT":
                row["status"] = "error"
        mutations["massive_events"] = events

        vix = _stage_results()
        vix["vix_regime"].update({"vix_regime": stages.UNKNOWN, "vix_regime_is_unknown": True})
        mutations["fmp_vix"] = vix

        for changed_key, fixture in mutations.items():
            with self.subTest(changed_key=changed_key):
                actual = stages.derive_capstone_provider_health(fixture)
                self.assertNotEqual(actual[changed_key], base[changed_key])
                self.assertEqual(
                    [key for key in REQUIRED_HEALTH_KEYS if actual[key] != base[key]], [changed_key]
                )

    def test_criticality_and_emit_gate_are_functional_not_vendor_wide(self):
        for key in REQUIRED_HEALTH_KEYS:
            raw = dict(_projected())
            raw[key] = "down"
            result = classify_provider_health(raw)
            with self.subTest(key=key):
                if key in CRITICAL_SOURCES:
                    self.assertEqual(result["overall_run_state"], "blocked")
                    self.assertNotIn(result["overall_run_state"], EMIT_ALLOWED_RUN_STATES)
                else:
                    self.assertEqual(result["overall_run_state"], "usable_with_fallback")
                    self.assertIn(result["overall_run_state"], EMIT_ALLOWED_RUN_STATES)

    def test_yfinance_health_changes_without_becoming_emit_critical(self):
        base = _stage_results()
        clean = stages.derive_capstone_provider_health(base)
        poisoned = copy.deepcopy(base)
        poisoned["yfinance_grades_fetch"] = _yfinance_summary(
            successful=0, provider_status="down", status="dependency_missing", dependency_missing=True,
        )
        poisoned["yfinance_grades_fetch"]["execution"]["attempted_symbol_count"] = 0
        poisoned_health = stages.derive_capstone_provider_health(poisoned)
        self.assertEqual(clean["analyst_grades"], "ok")
        self.assertEqual(poisoned_health["analyst_grades"], "down")
        self.assertNotEqual(poisoned_health, clean)
        self.assertEqual(classify_provider_health(clean)["overall_run_state"], "clean")
        self.assertEqual(classify_provider_health(poisoned_health)["overall_run_state"], "usable_with_fallback")

    def test_receipt_facts_and_report_detail_are_exact_closed_world(self):
        facts = tuple(_projected().items())
        self.assertTrue(validate_provider_health_facts(facts))
        self.assertFalse(validate_provider_health_facts(facts[:-1]))
        self.assertFalse(validate_provider_health_facts(facts + (("yfinance", "ok"),)))
        self.assertFalse(validate_provider_health_facts((("fmp", "ok"), ("sec_edgar", "ok"))))

        result = classify_provider_health(dict(facts))
        detail = provider_health_detail_line(result)
        self.assertEqual(parse_provider_health_detail_line(detail), result["sources"])
        self.assertIsNone(parse_provider_health_detail_line(detail.replace("analyst_grades=clean", "analyst_grades=blocked")))
        self.assertIsNone(parse_provider_health_detail_line(detail + "; yfinance=clean"))


if __name__ == "__main__":
    unittest.main()


class HostileInputFailsClosedInsteadOfCrashing(unittest.TestCase):
    """Every family projector must DEGRADE on hostile input; a raise out of these is the defect (O-P6R-2/3/4).

    The three inputs below each used to escape as TypeError / OverflowError from a function whose entire contract
    is to hand back a state word, so a single malformed row could abort the health write rather than fail closed.
    """

    def test_unhashable_target_symbol_degrades_every_pass2_family(self):
        summary = {
            "endpoint_results": [],
            "pass2_target_universe": {"target_count": 2, "target_symbols": [{"a": 1}, {"b": 2}]},
        }
        self.assertEqual(stages._sec_offering_health(summary), ("sec_offering_audit", "down"))
        self.assertEqual(stages._massive_events_health(summary), ("massive_events", "missing"))
        self.assertEqual(stages._fmp_analyst_grades_health(summary), ("analyst_grades", "missing"))

    def test_unhashable_row_symbol_degrades_massive_events(self):
        summary = {
            "endpoint_results": [
                {"provider_id": "massive", "endpoint_family": "dividends", "symbol": {"x": 1}, "status": "success"},
            ],
            "pass2_target_universe": {"target_count": 1, "target_symbols": ["AAPL"]},
        }
        self.assertEqual(stages._massive_events_health(summary), ("massive_events", "down"))

    def test_huge_vix_integer_degrades_instead_of_overflowing(self):
        summary = {
            "http_status": 200, "vix_value": 10 ** 400,
            "vix_regime": "进攻", "vix_regime_is_unknown": False,
        }
        self.assertEqual(stages._vix_health(summary), ("fmp_vix", "down"))
        # a finite value on the same shape still reads healthy, so the guard is not blanket-rejecting
        self.assertEqual(stages._vix_health({**summary, "vix_value": 18.0}), ("fmp_vix", "ok"))


class UniverseStatusRefusesVacuousEvidence(unittest.TestCase):
    """universe_status is emit-critical, so absent or self-contradictory status evidence must not read ok (O-P6R-6)."""

    @staticmethod
    def _summary(outcome: dict) -> dict:
        return {
            "scope": {"status": "ok"},
            "pass1_result": {},
            "provider_health": {"status_sources": {"state": "clean", "outcome": outcome}},
        }

    def test_zero_declared_status_sources_is_not_healthy(self):
        outcome = {
            "per_source": {}, "failed_sources": [], "critical_failed": [], "failed_count": 0,
            "total_sources": 0, "critical_all_failed": False, "block_or_no_emit": False,
        }
        self.assertEqual(stages._universe_health(self._summary(outcome)), ("universe_status", "missing"))

    def test_every_source_down_while_nothing_is_declared_failed_is_not_healthy(self):
        outcome = {
            "per_source": {"ticker_reference": "down", "exchange_halt_feed": "down", "sec_8k_item_103": "down"},
            "failed_sources": [], "critical_failed": [], "failed_count": 0,
            "total_sources": 3, "critical_all_failed": False, "block_or_no_emit": False,
        }
        self.assertEqual(stages._universe_health(self._summary(outcome)), ("universe_status", "missing"))

    def test_the_real_committed_summaries_still_read_ok(self):
        """Positive control: the tightening must not reject the artifacts the producer really writes."""
        seen = 0
        for path in sorted((ROOT / "docs").glob("us_short_universe_fetch_summary_*.json")):
            summary = json.loads(path.read_text(encoding="utf-8"))
            outcome = ((summary.get("provider_health") or {}).get("status_sources") or {}).get("outcome")
            if not isinstance(outcome, dict):
                continue          # pre-1.2.0 shape carries no status block at all; it is covered as `missing` above
            seen += 1
            self.assertEqual(stages._universe_health(summary), ("universe_status", "ok"), path.name)
        self.assertGreaterEqual(seen, 3)
