from __future__ import annotations

from collections import Counter
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from engine.us_short_fmp_analyst_grades import resolve_analyst_grade_actions
from engine import us_short_llm_theme_discovery_query_plan as query_plan
from engine.us_short_risk_downgrade import risk_downgrade
from engine.us_short_seam_score import compose_score_inputs
from engine.us_short_weekend_pipeline import _select_top15
from runners import us_short_llm_theme_discovery as ingest
from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from runners import us_short_llm_theme_discovery_merge as merge
from runners import us_short_provisional_theme_validate as validate
from runners.us_short_batch5_data_context import (
    DataContextAssemblyError,
    assemble_data_context_with_analyst_grade_risk,
)
from tests.provider.test_us_short_batch5_data_context import (
    _candidate_artifact as _context_candidate_artifact,
    _constant_projection,
    _gov,
    _grade_source,
    _theme_selection_contract,
)
from tests.provider.test_us_short_batch5_full_universe_momentum_producer import _DECISION_DATE
from tests.provider.test_us_short_batch5_full_universe_theme_producer import _classification_packet
from tests.provider.us_short_private_test_root import temporary_provider_directory


DECISION_DATE = _DECISION_DATE
GENERATED_AT = "2026-06-13T13:00:00Z"
OBSERVED_AT = "2026-06-13T12:00:00Z"
WEB_URL = "https://offline.example/plan-bound-web"
X_URL = "https://offline.example/plan-bound-x"
SCORE_TICKERS = ("AAPL", "MSFT", "JPM", "GOOG", "AMZN")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _themes(
    *, source_refs: list[str] | None = None, source_urls: list[str] | None = None,
    member_sets: dict[str, list[str]] | None = None,
) -> list[dict[str, object]]:
    member_sets = member_sets or {
        "power_demand": ["AAPL", "MSFT", "JPM", "GOOG"],
        "single_industry": ["AAPL", "MSFT", "GOOG"],
        "small_theme": ["AAPL", "MSFT"],
    }
    output: list[dict[str, object]] = []
    for theme_id, tickers in member_sets.items():
        theme: dict[str, object] = {
            "theme_id": theme_id,
            "display_name": theme_id.replace("_", " ").title(),
            "summary": "Offline plan-bound cross-industry evidence.",
            "observed_at": OBSERVED_AT,
            "members": [{"ticker": ticker} for ticker in tickers],
        }
        if source_refs is not None:
            theme["source_ref_ids"] = list(source_refs)
            theme["members"] = [
                {"ticker": ticker, "source_ref_ids": list(source_refs)}
                for ticker in tickers
            ]
        if source_urls is not None:
            theme["source_urls"] = list(source_urls)
            theme["members"] = [
                {"ticker": ticker, "source_urls": list(source_urls)}
                for ticker in tickers
            ]
        output.append(theme)
    return output


class PlanBoundOfflineClosureTests(unittest.TestCase):
    """Exercise discovery through validation, score composition, and the offline data-context seam."""

    def test_same_main_path_reaches_validation_score_assemble_without_provider_calls(self):
        web_source_id = web._source_id(web._canonical_locator(WEB_URL))
        web_results = [{
            "url": WEB_URL,
            "title": "Plan-bound power evidence",
            "content": "AAPL MSFT JPM GOOG cross-industry power demand.",
            "published_date": OBSERVED_AT,
        }]
        x_results = [{
            "url": X_URL,
            "title": "Plan-bound X evidence",
            "text": "AAPL MSFT JPM GOOG cross-industry power demand.",
            "created_at": OBSERVED_AT,
        }]
        web_response = {"themes": _themes(source_refs=[web_source_id])}
        x_response = {"themes": _themes(
            source_urls=[X_URL],
            member_sets={
                "power_demand": ["AAPL", "MSFT", "JPM"],
                "single_industry": ["AAPL", "MSFT"],
                "small_theme": ["AAPL", "MSFT"],
            },
        )}
        plan = query_plan.build_parent_plan(
            decision_date=DECISION_DATE,
            policy_version="soft_discovery_query_policy_v0.1.0",
            policy_template_content_sha256="a" * 64,
            stage1_queries=[
                {"query_id": "stage1-a", "query_text": "Find power demand shifts."},
                {"query_id": "stage1-b", "query_text": "Find capacity commitments."},
            ],
            stage2_rule_sha256="b" * 64,
            provider_envelopes=[
                {"provider": "web", "stage1_max_dispatch_count": 2, "stage2_max_dispatch_count": 0, "retry_max_dispatch_count": 0, "max_dispatch_count": 2},
                {"provider": "xai", "stage1_max_dispatch_count": 2, "stage2_max_dispatch_count": 0, "retry_max_dispatch_count": 0, "max_dispatch_count": 2},
            ],
            generated_at="2026-07-06T11:00:00Z",
        )

        with temporary_provider_directory(web.ROOT) as private_root:
            private_root = Path(private_root)
            state_dir = private_root / "state" / "us_short"
            raw_web = private_root / "raw" / "web"
            raw_x = private_root / "raw" / "x"
            fixtures = private_root / "fixtures"
            plan_path = state_dir / (
                f"us_short_llm_theme_discovery_query_plan_parent_{DECISION_DATE}_{plan['plan_identity']}.json"
            )
            query_plan.write_parent_plan(
                plan, plan_path, state_dir=state_dir, root=web.ROOT, gitignored=lambda _path: True,
            )
            web_results_path = fixtures / "web_results.json"
            web_response_path = fixtures / "web_response.json"
            x_results_path = fixtures / "x_results.json"
            x_response_path = fixtures / "x_response.json"
            _write_json(web_results_path, web_results)
            _write_json(web_response_path, web_response)
            _write_json(x_results_path, x_results)
            _write_json(x_response_path, x_response)

            with (
                mock.patch.object(web, "STATE_DIR", state_dir),
                mock.patch.object(xfetch, "STATE_DIR", state_dir),
                mock.patch.object(web, "DEFAULT_RAW_ROOT", raw_web),
                mock.patch.object(xfetch, "DEFAULT_RAW_ROOT", raw_x),
                mock.patch.object(ingest, "STATE_US_SHORT_DIR", state_dir),
                mock.patch.object(validate, "STATE_DIR", state_dir),
            ):
                self.assertEqual(web.main([
                    "--parent-plan", str(plan_path),
                    "--expected-decision-date", DECISION_DATE,
                    "--generated-at", GENERATED_AT,
                    "--raw-root", str(raw_web),
                    "--fake-results-path", str(web_results_path),
                    "--fake-llm-response-path", str(web_response_path),
                ]), 0)
                self.assertEqual(xfetch.main([
                    "--parent-plan", str(plan_path),
                    "--expected-decision-date", DECISION_DATE,
                    "--generated-at", GENERATED_AT,
                    "--raw-root", str(raw_x),
                    "--fake-results-path", str(x_results_path),
                    "--fake-response-path", str(x_response_path),
                ]), 0)

                web_discovery = web.default_discovery_path(DECISION_DATE)
                web_receipt = web.default_receipt_path(DECISION_DATE)
                x_discovery = xfetch.default_discovery_path(DECISION_DATE)
                x_receipt = xfetch.default_receipt_path(DECISION_DATE)
                web_receipt_payload = json.loads(web_receipt.read_text(encoding="utf-8"))
                self.assertEqual(
                    web_receipt_payload["plan_binding"]["parent_plan_artifact"]["path"],
                    plan_path.resolve().relative_to(web.ROOT.resolve()).as_posix(),
                )
                self.assertEqual(
                    web_receipt_payload["summary"]["query_count"],
                    len(query_plan.derive_stage1_query_records(plan)),
                )
                self.assertEqual(merge.main([
                    "--web-discovery", str(web_discovery),
                    "--web-receipt", str(web_receipt),
                    "--x-discovery", str(x_discovery),
                    "--x-receipt", str(x_receipt),
                    "--expected-decision-date", DECISION_DATE,
                    "--generated-at", GENERATED_AT,
                ]), 0)

                merged_path = merge.default_discovery_path(DECISION_DATE)
                manifest_path = merge.default_manifest_path(DECISION_DATE)
                merged = json.loads(merged_path.read_text(encoding="utf-8"))
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                ingest_input = merge.validate_merged_packet(
                    merged,
                    manifest,
                    expected_decision_date=DECISION_DATE,
                    upstream_pairs={
                        "web": (
                            json.loads(web_discovery.read_text(encoding="utf-8")),
                            json.loads(web_receipt.read_text(encoding="utf-8")),
                        ),
                        "x": (
                            json.loads(x_discovery.read_text(encoding="utf-8")),
                            json.loads(x_receipt.read_text(encoding="utf-8")),
                        ),
                    },
                )
                ingest_input_path = state_dir / f"us_short_llm_theme_discovery_ingest_input_{DECISION_DATE}.json"
                _write_json(ingest_input_path, ingest_input)
                self.assertEqual(ingest.main([
                    "--input-path", str(ingest_input_path),
                    "--output-path", str(ingest.default_output_path(DECISION_DATE)),
                    "--expected-decision-date", DECISION_DATE,
                    "--generated-at", GENERATED_AT,
                ]), 0)

                candidate_path = state_dir / f"candidate_{DECISION_DATE}.json"
                classification_path = state_dir / f"classification_{DECISION_DATE}.json"
                candidate_artifact = _context_candidate_artifact(SCORE_TICKERS)
                _write_json(candidate_path, candidate_artifact)
                _write_json(classification_path, _classification_packet({
                    "AAPL": "10", "MSFT": "10", "GOOG": "10", "JPM": "20", "AMZN": "20",
                }))
                self.assertEqual(validate.main([
                    "--discovery-path", str(ingest.default_output_path(DECISION_DATE)),
                    "--candidate-path", str(candidate_path),
                    "--classification-path", str(classification_path),
                    "--output-path", str(validate.default_output_path(DECISION_DATE)),
                    "--expected-decision-date", DECISION_DATE,
                    "--generated-at", GENERATED_AT,
                ]), 0)

                validation = json.loads(
                    validate.default_output_path(DECISION_DATE).read_text(encoding="utf-8")
                )

        score_tickers = list(SCORE_TICKERS)
        momentum_projection = _constant_projection("momentum_by_ticker", score_tickers, "scored", score=50.0)
        theme_projection = _constant_projection("theme_block_by_ticker", score_tickers, "scored_theme_base", score=50.0)
        catalyst_projection = _constant_projection(
            "catalyst_block_by_ticker", score_tickers, "scored_realized_catalyst", score=50.0,
        )
        risk_map = {ticker: risk_downgrade() for ticker in score_tickers}
        input_digests = {
            key: validation["input_artifacts"][key]
            for key in ("discovery_artifact_sha256", "candidate_artifact_sha256", "classification_packet_sha256")
        }

        def compose(*, enabled: bool, target_tickers: list[str], projections=None):
            projections = projections or (
                momentum_projection, theme_projection, catalyst_projection,
            )
            return compose_score_inputs(
                target_tickers=target_tickers,
                momentum_projection=projections[0],
                theme_projection=projections[1],
                catalyst_projection=projections[2],
                risk_downgrade_by_ticker={ticker: risk_map.get(ticker, risk_downgrade()) for ticker in target_tickers},
                theme_opportunity_state="strong",
                provisional_theme_validation=validation if enabled else None,
                theme_soft_boost_enabled=enabled,
                provisional_theme_expected_decision_date=DECISION_DATE if enabled else None,
                provisional_theme_input_digests=input_digests if enabled else None,
            )

        baseline = compose(enabled=False, target_tickers=score_tickers)
        boosted = compose(enabled=True, target_tickers=score_tickers)
        boost_by_ticker = {
            ticker: boosted["analysis_by_ticker"][ticker]["provisional_theme_boost"]
            for ticker in score_tickers
        }
        self.assertEqual(boost_by_ticker["AAPL"]["theme_soft_boost"], 5.0)
        self.assertEqual(boost_by_ticker["GOOG"]["theme_soft_boost"], 2.0)
        self.assertLessEqual(max(row["theme_soft_boost"] for row in boost_by_ticker.values()), 5.0)
        self.assertAlmostEqual(
            boosted["selection_inputs"]["per_ticker"]["AAPL"]["core_score"]
            - baseline["selection_inputs"]["per_ticker"]["AAPL"]["core_score"],
            5.0,
        )
        self.assertAlmostEqual(
            boosted["selection_inputs"]["per_ticker"]["GOOG"]["core_score"]
            - baseline["selection_inputs"]["per_ticker"]["GOOG"]["core_score"],
            2.0,
        )

        analyst_grade_actions = resolve_analyst_grade_actions(
            as_of="2026-06-15",
            grades_by_ticker={ticker: _grade_source(ticker, []) for ticker in score_tickers},
        )
        theme_selection_contract = _theme_selection_contract(score_tickers)
        assemble_kwargs = {
            "candidate_artifact": candidate_artifact,
            "expected_decision_date": DECISION_DATE,
            "eligibility_governance": _gov(),
            "momentum_projection": momentum_projection,
            "theme_projection": theme_projection,
            "catalyst_projection": catalyst_projection,
            "analyst_grade_actions": analyst_grade_actions,
            "theme_opportunity_state": "strong",
            "candidate_pass2_signals": {ticker: {} for ticker in score_tickers},
            "theme_selection_contract": theme_selection_contract,
            "provisional_theme_validation": validation,
            "theme_soft_boost_enabled": True,
            "provisional_theme_input_digests": input_digests,
        }
        assembled = assemble_data_context_with_analyst_grade_risk(**assemble_kwargs)
        self.assertEqual(set(assembled["selection_inputs"]["per_ticker"]), set(score_tickers))
        self.assertEqual(
            assembled["selection_inputs"]["per_ticker"],
            boosted["selection_inputs"]["per_ticker"],
        )

        boundary_tickers = [
            "AAPL", "MSFT", "JPM", "GOOG", "AMZN", "META", "NVDA", "TSLA",
            "NFLX", "ORCL", "ADBE", "CRM", "INTC", "AMD", "BAC", "WFC",
        ]
        boundary_momentum = _constant_projection(
            "momentum_by_ticker", boundary_tickers, "scored", score=50.0,
        )
        boundary_theme = _constant_projection(
            "theme_block_by_ticker", boundary_tickers, "scored_theme_base", score=50.0,
        )
        boundary_catalyst = _constant_projection(
            "catalyst_block_by_ticker", boundary_tickers, "scored_realized_catalyst", score=50.0,
        )
        boundary_momentum["momentum_by_ticker"]["AAPL"] = 49.0
        boundary_theme["theme_block_by_ticker"]["AAPL"] = 49.0
        boundary_catalyst["catalyst_block_by_ticker"]["AAPL"] = 49.0
        boundary_projections = (boundary_momentum, boundary_theme, boundary_catalyst)
        boundary_base = compose(enabled=False, target_tickers=boundary_tickers, projections=boundary_projections)
        boundary_boosted = compose(enabled=True, target_tickers=boundary_tickers, projections=boundary_projections)
        boundary_base_top15 = _select_top15(
            boundary_tickers,
            {
                "theme_opportunity_state": "strong",
                "theme_selection_contract": _theme_selection_contract(boundary_tickers),
                "per_ticker": boundary_base["selection_inputs"]["per_ticker"],
            },
            decision_date=DECISION_DATE,
        )["admitted"]
        boundary_boosted_top15 = _select_top15(
            boundary_tickers,
            {
                "theme_opportunity_state": "strong",
                "theme_selection_contract": _theme_selection_contract(boundary_tickers),
                "per_ticker": boundary_boosted["selection_inputs"]["per_ticker"],
            },
            decision_date=DECISION_DATE,
        )["admitted"]
        self.assertNotIn("AAPL", boundary_base_top15)
        self.assertIn("AAPL", boundary_boosted_top15)
        self.assertNotEqual(boundary_base_top15, boundary_boosted_top15)

        with self.assertRaises(DataContextAssemblyError):
            bad_date = copy.deepcopy(validation)
            bad_date["decision_clock"]["expected_decision_date"] = "20260616"
            assemble_data_context_with_analyst_grade_risk(
                **{**assemble_kwargs, "provisional_theme_validation": bad_date},
            )
        with self.assertRaises(DataContextAssemblyError):
            assemble_data_context_with_analyst_grade_risk(
                **{**assemble_kwargs, "provisional_theme_input_digests": None},
            )
        with self.assertRaises(DataContextAssemblyError):
            bad_digests = dict(input_digests)
            bad_digests["candidate_artifact_sha256"] = "d" * 64
            assemble_data_context_with_analyst_grade_risk(
                **{**assemble_kwargs, "provisional_theme_input_digests": bad_digests},
            )
        with self.assertRaises(DataContextAssemblyError):
            incomplete_overextension = {
                ticker: {"overextension_state": "none", "strips_theme_score": False, "execution_flags": {}}
                for ticker in score_tickers[:-1]
            }
            assemble_data_context_with_analyst_grade_risk(
                **{**assemble_kwargs, "overextension_by_ticker": incomplete_overextension},
            )

        input_themes = {theme["theme_id"] for theme in ingest_input["themes"]}
        accepted = {
            theme["theme_id"]: theme["validation"]
            for theme in validation["themes"]
        }
        denominator = len(input_themes)
        drop_reasons = Counter(row["reason"] for row in validation["drop_ledger"])
        member_fail_themes = {
            row["theme_id"]
            for row in validation["drop_ledger"]
            if row["reason"] == "fewer_than_3_qualified_members"
        }
        industry_fail_themes = member_fail_themes | {
            row["theme_id"]
            for row in validation["drop_ledger"]
            if row["reason"] == "fewer_than_2_sec_sic_industries"
        }
        member_gate_pass = denominator - len(member_fail_themes)
        industry_gate_pass = denominator - len(industry_fail_themes)
        stats = {
            "theme_denominator": denominator,
            "member_gate": {"pass": member_gate_pass, "fail": denominator - member_gate_pass, "rate": member_gate_pass / denominator},
            "industry_gate": {"pass": industry_gate_pass, "fail": denominator - industry_gate_pass, "rate": industry_gate_pass / denominator},
            "drop_reasons": dict(sorted(drop_reasons.items())),
            "scored_ticker_count": len(assembled["selection_inputs"]["per_ticker"]),
            "scoring_or_top15_effect": True,
            "network_access_performed": False,
            "provider_calls_performed": False,
        }
        print("OFFLINE_PLAN_BOUND_CLOSURE_STATS " + json.dumps(stats, sort_keys=True))
        self.assertEqual(stats["theme_denominator"], 3)
        self.assertEqual(stats["member_gate"], {"pass": 2, "fail": 1, "rate": 2 / 3})
        self.assertEqual(stats["industry_gate"], {"pass": 1, "fail": 2, "rate": 1 / 3})
        self.assertEqual(
            stats["drop_reasons"],
            {"fewer_than_2_sec_sic_industries": 1, "fewer_than_3_qualified_members": 1},
        )
        self.assertEqual(stats["scored_ticker_count"], len(score_tickers))
        self.assertTrue(stats["scoring_or_top15_effect"])


if __name__ == "__main__":
    unittest.main()
