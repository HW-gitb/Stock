from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from engine import us_short_llm_theme_discovery_query_plan as query_plan
from runners import us_short_llm_theme_discovery as ingest
from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from runners import us_short_llm_theme_discovery_merge as merge
from runners import us_short_provisional_theme_validate as validate
from tests.provider.test_us_short_batch5_full_universe_momentum_producer import (
    _ALL_ELIGIBLE,
    _DECISION_DATE,
    _candidate_artifact,
)
from tests.provider.test_us_short_batch5_full_universe_theme_producer import _classification_packet
from tests.provider.us_short_private_test_root import temporary_provider_directory


DECISION_DATE = _DECISION_DATE
GENERATED_AT = "2026-06-13T13:00:00Z"
OBSERVED_AT = "2026-06-13T12:00:00Z"
WEB_URL = "https://offline.example/plan-bound-web"
X_URL = "https://offline.example/plan-bound-x"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _themes(*, source_refs: list[str] | None = None, source_urls: list[str] | None = None) -> list[dict[str, object]]:
    member_sets = {
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
    """Exercise the shipped CLI mains through merge, ingest, and provisional validation."""

    def test_same_main_path_reaches_both_provisional_gates_without_provider_calls(self):
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
        x_response = {"themes": _themes(source_urls=[X_URL])}
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
                _write_json(candidate_path, _candidate_artifact(_ALL_ELIGIBLE))
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


if __name__ == "__main__":
    unittest.main()
