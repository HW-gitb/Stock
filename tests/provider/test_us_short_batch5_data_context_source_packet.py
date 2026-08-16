from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_catalyst import load_catalyst_governance  # noqa: E402
from engine.us_short_fmp_analyst_grades import resolve_analyst_grade_actions  # noqa: E402
from engine.us_short_massive_news import resolve_news_events  # noqa: E402
from engine.us_short_sec_offering_audit import resolve_offering_audit  # noqa: E402
from engine.us_short_yfinance_analyst_grades import resolve_yfinance_grade_actions  # noqa: E402
from runners import us_short_batch5_data_context_source_packet as source_packet_runner  # noqa: E402
from runners.us_short_batch5_data_context import official_top15_tickers  # noqa: E402
from runners.us_short_batch5_data_context_source_packet import (  # noqa: E402
    SourcePacketError,
    _load_and_validate_packet,
    _soft_boost_common_input_sha256,
    main,
    run_packet,
    run_preflight,
    source_packet_input_manifest,
)
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _GRADE_AS_OF,
    _NEWS_AS_OF,
    _OFFERING_AS_OF,
    _candidate_artifact,
    _checked_offering,
    _constant_projection,
    _grade_record,
    _grade_source,
    _news_item,
    _news_source,
    _offering_record,
    _offering_source,
)
from tests.schema.test_us_short_provisional_theme_validation_schema import _artifact as _theme_artifact  # noqa: E402
from tests.provider.us_short_private_test_root import (  # noqa: E402
    temporary_us_short_directory,
    temporary_us_short_state_directory,
)


STATE_DIR = ROOT / "state" / "us_short"


class ContextComponentsShapeContractTest(unittest.TestCase):
    def _components(self, shape: str) -> dict:
        values = {
            "data_context": {},
            "score_composition": {},
            "overextension_by_ticker": None,
            "per_ticker_analysis": {},
            "run_provenance": {},
            "result_linkage_sources": {},
        }
        return {
            key: values[key]
            for key in reversed(tuple(source_packet_runner.CONTEXT_COMPONENT_SHAPES[shape]))
        }

    def test_exact_shape_contract_accepts_historical_shapes_and_only_current_cut4(self):
        for shape in ("legacy", "a1", "cut4"):
            with self.subTest(shape=shape):
                self.assertEqual(
                    source_packet_runner.validate_context_components_shape(
                        self._components(shape), allowed_shapes=("legacy", "a1", "cut4")
                    ),
                    shape,
                )

        current = self._components("cut4")
        self.assertEqual(source_packet_runner.CURRENT_CONTEXT_COMPONENT_SHAPE, "cut4")
        self.assertEqual(source_packet_runner.validate_current_context_components(current), "cut4")
        with self.assertRaisesRegex(SourcePacketError, "missing_keys=.*result_linkage_sources"):
            source_packet_runner.validate_current_context_components(
                {key: value for key, value in current.items() if key != "result_linkage_sources"}
            )
        with self.assertRaisesRegex(SourcePacketError, "unexpected_keys=.*unknown"):
            source_packet_runner.validate_current_context_components({**current, "unknown": {}})
        with self.assertRaisesRegex(SourcePacketError, "mapping"):
            source_packet_runner.validate_current_context_components([])
        with self.assertRaisesRegex(SourcePacketError, "invalid_value_types=.*data_context"):
            source_packet_runner.validate_current_context_components({**current, "data_context": []})


class K4bPublicTop15ContractTest(unittest.TestCase):
    def test_source_packet_imports_the_public_top15_contract(self):
        self.assertIs(source_packet_runner.official_top15_tickers, official_top15_tickers)
        source = Path(source_packet_runner.__file__).read_text(encoding="utf-8")
        self.assertNotIn("_official_top15_tickers", source)

    def test_k4b_default_state_root_is_allowed_but_every_output_stays_gitignored(self):
        # READ-ONLY/NEGATIVE CONTROL: this class audits the canonical default-root contract and
        # never creates, writes, or removes a file under the real state root.
        self.assertFalse(source_packet_runner._git_ignored(STATE_DIR))
        state_dir = source_packet_runner._validate_soft_boost_state_dir(_rel(STATE_DIR))
        self.assertEqual(state_dir, STATE_DIR)
        for field, relative_path in (
            ("soft_boost_consumption_receipt_path", "us_short_soft_boost_consumption_receipt_20260615.json"),
            ("soft_boost_shadow_receipt_path", "shadow_compare_private/us_short_soft_boost_shadow_receipt_20260615.json"),
            ("soft_boost_comparison_ledger_path", "shadow_compare_private/us_short_soft_boost_comparison_ledger_20260615.json"),
        ):
            with self.subTest(field=field):
                output = STATE_DIR / relative_path
                self.assertTrue(source_packet_runner._git_ignored(output))
                self.assertEqual(
                    source_packet_runner._validate_soft_boost_output_path(
                        _rel(output), field=field, state_dir=state_dir
                    ),
                    output,
                )


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _eligible_digest(tickers) -> str:
    payload = json.dumps(sorted(tickers), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _tier(state: str) -> dict:
    flags = ({"force_pullback": True, "reduce_size": True, "raise_rr_gate": True}
             if state == "warning" else {})
    return {
        "overextension_state": state,
        "strips_theme_score": state == "chasing_extreme",
        "execution_flags": flags,
        "conditions_met": 3 if state == "chasing_extreme" else 0,
        "condition_names": (["vertical_run", "volume_climax", "weak_retrace"]
                            if state == "chasing_extreme" else []),
        "disposition": "scored",
        "pit": {"as_of": "2026-06-12", "session": "RTH",
                "adjustment_mode": "split_adjusted", "n_points": 70},
    }


def _overextension_projection() -> dict:
    tickers = ("AAPL", "MSFT", "JPM")
    return {
        "schema_name": "us_short_full_universe_overextension_projection",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-15T08:30:00-04:00",
        "decision_clock": {
            "expected_decision_date": "20260615",
            "candidate_price_basis_date": "20260612",
            "price_basis_date": "2026-06-12",
            "source_as_of": "2026-06-12",
        },
        "source_contract": {"session": "RTH", "adjustment_mode": "split_adjusted"},
        "candidate_binding": {
            "eligible_count": 3,
            "eligible_tickers_sha256": _eligible_digest(tickers),
        },
        "overextension_by_ticker": {
            "AAPL": _tier("chasing_extreme"),
            "MSFT": _tier("warning"),
            "JPM": _tier("none"),
        },
        "disposition_counts": {"scored": 3, "insufficient_data": 0},
        "scored_count": 3,
        "target_count": 3,
    }


class Batch5DataContextSourcePacketTest(unittest.TestCase):
    def setUp(self):
        self.slug = f"test_source_packet_{os.getpid()}_{self._testMethodName}"
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_dir = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._provider_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / f"data_context_source_packet_{self.slug}"
        )
        self.provider_root = Path(self._provider_root_context.__enter__())
        self.addCleanup(self._provider_root_context.__exit__, None, None, None)
        self.soft_state_dir = self.provider_root / "state" / "us_short"
        self.soft_state_dir.mkdir(parents=True, exist_ok=True)
        original_git_ignored = source_packet_runner._git_ignored
        private_roots = tuple(root.resolve() for root in (self.state_dir, self.soft_state_dir, self.provider_root))

        def _git_ignored_for_private_test(path):
            resolved = Path(path).resolve()
            if any(resolved == root or root in resolved.parents for root in private_roots):
                return True
            return original_git_ignored(path)

        source_packet_runner._git_ignored = _git_ignored_for_private_test
        self.addCleanup(setattr, source_packet_runner, "_git_ignored", original_git_ignored)
        self.paths = {
            "packet": self.state_dir / f"{self.slug}_packet.json",
            "candidate": self.state_dir / f"{self.slug}_candidate.json",
            "momentum": self.state_dir / f"{self.slug}_momentum.json",
            "theme": self.state_dir / f"{self.slug}_theme.json",
            "overextension": self.state_dir / f"{self.slug}_overextension.json",
            "offering": self.state_dir / f"{self.slug}_offering.json",
            "analyst": self.state_dir / f"{self.slug}_analyst.json",
            "yfinance": self.state_dir / f"{self.slug}_yfinance_analyst.json",
            "news": self.state_dir / f"{self.slug}_news.json",
            "theme_contract": self.state_dir / f"{self.slug}_theme_selection_contract.json",
            "output": self.state_dir / f"{self.slug}_data_context.json",
            "components": self.state_dir / f"{self.slug}_context_components.json",
            "classification": self.state_dir / f"{self.slug}_classification.json",
            "soft_ingest": self.soft_state_dir / f"{self.slug}_soft_ingest.json",
            "soft_stage": self.soft_state_dir / f"us_short_provisional_theme_stage_receipt_{_DECISION_DATE}.json",
            "soft_validation": self.soft_state_dir / f"us_short_provisional_theme_validation_{_DECISION_DATE}.json",
            "soft_consumption": self.soft_state_dir / (
                f"us_short_soft_boost_consumption_receipt_{_DECISION_DATE}.json"
            ),
            "soft_shadow": self.soft_state_dir / "shadow_compare_private" / (
                f"us_short_soft_boost_shadow_receipt_{_DECISION_DATE}.json"
            ),
            "soft_ledger": self.soft_state_dir / "shadow_compare_private" / (
                f"us_short_soft_boost_comparison_ledger_{_DECISION_DATE}.json"
            ),
            "raw_payload": self.provider_root / f"{self.slug}_raw_payload.json",
        }
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        self.packet = self._write_sources_and_packet()

    def tearDown(self):
        for path in self.paths.values():
            path.unlink(missing_ok=True)

    def _write_sources_and_packet(self):
        targets = ("AAPL", "MSFT")
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "MSFT", "JPM")))
        _write_json(
            self.paths["momentum"],
            _constant_projection(
                "momentum_by_ticker", targets, "scored", score=50.0,
                candidate_path=self.paths["candidate"], component="momentum",
                producer_id="us_short_batch5_full_candidate_live_source_packet",
                source_roles=("parent_momentum_projection",),
            ),
        )
        _write_json(
            self.paths["theme"],
            _constant_projection(
                "theme_block_by_ticker", targets, "scored_theme_base", score=50.0,
                candidate_path=self.paths["candidate"], component="theme",
                producer_id="us_short_batch5_full_candidate_live_source_packet",
                source_roles=("parent_theme_projection",),
            ),
        )
        _write_json(
            self.paths["offering"],
            resolve_offering_audit(
                as_of=_OFFERING_AS_OF,
                filings_by_ticker={
                    "AAPL": _offering_record([]),
                    "MSFT": _offering_record([]),
                    "JPM": _offering_record([], coverage="partial"),
                },
            ),
        )
        _write_json(
            self.paths["analyst"],
            resolve_analyst_grade_actions(
                as_of=_GRADE_AS_OF,
                grades_by_ticker={
                    "AAPL": _grade_source(
                        "AAPL",
                        [
                            _grade_record("AAPL", date="2026-06-10", company="BankA"),
                            _grade_record("AAPL", date="2026-06-11", company="BankB"),
                        ],
                    ),
                    "MSFT": _grade_source("MSFT", []),
                },
            ),
        )
        _write_json(
            self.paths["news"],
            resolve_news_events(
                as_of=_NEWS_AS_OF,
                news_by_ticker={
                    "AAPL": _news_source("AAPL", [_news_item(id="a", sentiment="positive")]),
                    "MSFT": _news_source("MSFT", []),
                },
            ),
        )
        _write_json(
            self.paths["theme_contract"],
            {
                "as_of": _DECISION_DATE,
                "mode": "industry_heat_v1_cross_industry_disabled",
                "cross_industry_provisional_enabled": False,
                "theme_opportunity_state": "strong",
                "per_ticker": {
                    ticker: {
                        "theme_id": f"industry:{ticker.lower()}", "theme_source": "industry_heat_v1",
                        "theme_lifecycle_state": "confirmed_active", "theme_leader_rs": 0.0,
                        "membership_origin": "automatic_discovery", "market_confirmed": True,
                        "individual_theme_gate_passed": True, "overextension_state": "none",
                        "macro_cluster": "unclassified_conservative",
                    }
                    for ticker in targets
                },
            },
        )
        packet = {
            "schema_name": "us_short_batch5_data_context_source_packet",
            "schema_version": "1.4.0",
            "generated_at": "2026-07-04T00:00:00Z",
            "active_analyst_source": "fmp",
            "scope": {
                "market": "US",
                "lane": "us_short",
                "batch": "batch5_provider_live",
                "packet_status": "resolved_pass2_source_packet_ready_for_local_assembly",
                "network_access_performed": False,
                "provider_calls_performed": False,
                "raw_payload_capture_performed": False,
                "datahub_consumption_allowed": False,
                "production_storage_allowed": False,
                "ship_gate_evidence_claimed": False,
                "broker_or_order_automation_allowed": False,
                "a_share_crossing_allowed": False,
            },
            "decision_clock": {
                "expected_decision_date": _DECISION_DATE,
                "theme_opportunity_state": "strong",
            },
            "source_artifact_sha256": {
                "offering_audit_source_path": hashlib.sha256(self.paths["offering"].read_bytes()).hexdigest(),
                "analyst_grade_actions_path": hashlib.sha256(self.paths["analyst"].read_bytes()).hexdigest(),
                "massive_news_events_path": hashlib.sha256(self.paths["news"].read_bytes()).hexdigest(),
                "theme_selection_contract_path": hashlib.sha256(self.paths["theme_contract"].read_bytes()).hexdigest(),
            },
            "paths": {
                "candidate_artifact_path": _rel(self.paths["candidate"]),
                "eligibility_governance_path": "presets/us_short_eligibility_governance_20260624.json",
                "momentum_projection_path": _rel(self.paths["momentum"]),
                "theme_projection_path": _rel(self.paths["theme"]),
                "offering_audit_source_path": _rel(self.paths["offering"]),
                "analyst_grade_actions_path": _rel(self.paths["analyst"]),
                "massive_news_events_path": _rel(self.paths["news"]),
                "catalyst_governance_path": "presets/us_short_catalyst_governance_20260630.json",
                "theme_selection_contract_path": _rel(self.paths["theme_contract"]),
                "output_data_context_path": _rel(self.paths["output"]),
            },
            "optional_inputs": {
                "holdings": [],
                "catalyst_recall_feed": None,
            },
            "preflight_gates": {
                "local_files_only": True,
                "source_artifacts_must_exist": True,
                "output_must_be_gitignored": True,
                "no_provider_fetch": True,
                "no_datahub_or_production": True,
            },
            "prohibited_claims": {
                "provider_selection_complete": False,
                "live_normalized_evidence": False,
                "ship_gate_evidence": False,
                "production_ready": False,
                "datahub_consumed": False,
            },
        }
        return _write_json(self.paths["packet"], packet)

    def _yfinance_source(self, records, *, ticker="AAPL", coverage="full", parser="ok"):
        return {
            "records": list(records),
            "provenance": {
                "provider_id": "yfinance",
                "endpoint_or_filing_type": "upgrades_downgrades",
                "source_as_of": _GRADE_AS_OF,
                "observed_at": "2026-06-15T08:00:00-04:00",
                "coverage_status": coverage,
                "parser_status": parser,
                "lineage_ref": f"yfinance:upgrades_downgrades:{_GRADE_AS_OF}#{ticker.lower()}",
            },
        }

    def _yfinance_row(
        self,
        *,
        ticker="AAPL",
        date="2026-06-10",
        action="down",
        firm="BankA",
        to_grade="Sell",
        from_grade="Hold",
    ):
        return {
            "symbol": ticker,
            "GradeDate": date,
            "Action": action,
            "Firm": firm,
            "ToGrade": to_grade,
            "FromGrade": from_grade,
        }

    def _packet_payload(self):
        return json.loads(self.paths["packet"].read_text(encoding="utf-8"))

    def test_preflight_validates_local_source_packet_without_writing_output(self):
        result = run_preflight(self.packet, generated_at="2026-07-04T00:00:01Z")

        self.assertFalse(self.paths["output"].exists())
        self.assertEqual(result["scope"]["preflight_status"], "offline_preflight_passed")
        self.assertFalse(result["scope"]["network_access_required"])
        self.assertFalse(result["scope"]["provider_calls_performed"])
        self.assertTrue(result["preflight_checks"]["packet_contract_validated"])
        self.assertTrue(result["preflight_checks"]["output_path_gitignored"])

    def test_run_packet_writes_data_context_from_resolved_sources(self):
        result = run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")

        self.assertEqual(result["scope"]["assembly_status"], "data_context_assembled_from_resolved_sources")
        self.assertFalse(result["scope"]["network_access_required"])
        self.assertFalse(result["scope"]["provider_calls_performed"])
        self.assertEqual(result["data_context"]["output_path"], _rel(self.paths["output"]))
        written = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        self.assertEqual(written["candidate_pass2_signals"]["JPM"], {"critical_data_missing": True})
        self.assertEqual(set(written["selection_inputs"]["per_ticker"]), {"AAPL", "MSFT"})
        self.assertAlmostEqual(written["selection_inputs"]["per_ticker"]["AAPL"]["core_score"], 43.5)
        self.assertAlmostEqual(written["selection_inputs"]["per_ticker"]["MSFT"]["core_score"], 50.0)

    def test_k4b_valid_nonempty_uses_one_source_packet_for_on_and_local_off_shadow(self):
        operator_shadow_dir = self.state_dir / "shadow_compare_private"
        operator_shadow_dir_existed = operator_shadow_dir.exists()
        packet = self._packet_payload()
        packet["paths"]["output_context_components_path"] = _rel(self.paths["components"])
        baseline_packet = copy.deepcopy(packet)
        baseline_packet["optional_inputs"]["theme_soft_boost_enabled"] = False
        _write_json(self.packet, baseline_packet)
        run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")
        baseline = self.paths["output"].read_bytes()

        candidate_sha = hashlib.sha256(self.paths["candidate"].read_bytes()).hexdigest()
        _write_json(self.paths["classification"], {"decision_date": _DECISION_DATE})
        classification_sha = hashlib.sha256(self.paths["classification"].read_bytes()).hexdigest()
        _write_json(self.paths["soft_ingest"], {"decision_date": _DECISION_DATE})
        ingest_sha = hashlib.sha256(self.paths["soft_ingest"].read_bytes()).hexdigest()
        artifact = _theme_artifact()
        artifact["input_artifacts"].update({
            "discovery_artifact_sha256": ingest_sha,
            "candidate_artifact_sha256": candidate_sha,
            "classification_packet_sha256": classification_sha,
        })
        _write_json(self.paths["soft_validation"], artifact)
        validation_sha = hashlib.sha256(self.paths["soft_validation"].read_bytes()).hexdigest()
        stage = {
            "schema_name": "us_short_provisional_theme_stage_receipt",
            "schema_version": "1.0.0",
            "generated_at": "2026-06-15T08:30:00-04:00",
            "decision_date": _DECISION_DATE,
            "status": "valid_nonempty",
            "reason_code": None,
            "artifacts": {
                "merge": {"path": "state/us_short/merge.json", "sha256": "1" * 64},
                "merge_manifest": {"path": "state/us_short/manifest.json", "sha256": "2" * 64},
                "ingest": {"path": _rel(self.paths["soft_ingest"]), "sha256": ingest_sha},
                "validation": {"path": _rel(self.paths["soft_validation"]), "sha256": validation_sha},
            },
            "evidence_anchor": {
                "upstream_pair_anchored": True,
                "document_content_anchored": True,
                "upstream_artifacts": {
                    "web_discovery": {"path": "state/us_short/web.json", "sha256": "3" * 64},
                    "web_receipt": {"path": "state/us_short/web_receipt.json", "sha256": "4" * 64},
                    "x_discovery": {"path": "state/us_short/x.json", "sha256": "5" * 64},
                    "x_receipt": {"path": "state/us_short/x_receipt.json", "sha256": "6" * 64},
                },
            },
            "immutable_conflict": None,
            "validated_theme_count": 1,
            # The semantic fixture has four validated members; MSFT is Web-only
            # (`single`), so its 50.0 base receives 2.0, not the both-tier 5.0.
            "boostable_ticker_count": 4,
            "drop_summary": {"merge_dropped_theme_count": 0, "validation_drop_count": 0},
            "error_summary": None,
            "effects": {
                "network_access_performed": False, "provider_calls_performed": False,
                "scoring_eligible": False, "top15_effect_enabled": False,
                "operation_advice_effect_enabled": False, "dynamic_seats_enabled": False,
                "theme_probe_enabled": False, "lifecycle_actions_enabled": False,
            },
        }
        _write_json(self.paths["soft_stage"], stage)
        packet["optional_inputs"]["theme_soft_boost_enabled"] = True
        packet["optional_inputs"]["soft_discovery_stage_result"] = stage
        packet["paths"].update({
            "soft_boost_state_dir_path": _rel(self.soft_state_dir),
            "provisional_theme_stage_receipt_path": _rel(self.paths["soft_stage"]),
            "provisional_theme_validation_path": _rel(self.paths["soft_validation"]),
            "original_candidate_artifact_path": _rel(self.paths["candidate"]),
            "classification_packet_path": _rel(self.paths["classification"]),
            "soft_boost_consumption_receipt_path": _rel(self.paths["soft_consumption"]),
            "soft_boost_shadow_receipt_path": _rel(self.paths["soft_shadow"]),
            "soft_boost_comparison_ledger_path": _rel(self.paths["soft_ledger"]),
        })
        typed_zero_consumption = self.paths["soft_consumption"]
        typed_zero_shadow = self.paths["soft_shadow"]
        typed_zero_ledger = self.paths["soft_ledger"]
        typed_zero_packet = copy.deepcopy(packet)
        typed_zero_stage = copy.deepcopy(stage)
        typed_zero_stage.update({
            "status": "upstream_unavailable",
            "reason_code": "CANDIDATE_INPUT_UNAVAILABLE",
            "validated_theme_count": 0,
            "boostable_ticker_count": 0,
            "error_summary": {
                "code": "CANDIDATE_INPUT_UNAVAILABLE",
                "error_type": "SoftDiscoveryEvidenceError",
            },
        })
        typed_zero_packet["optional_inputs"]["soft_discovery_stage_result"] = typed_zero_stage
        _write_json(self.packet, typed_zero_packet)
        typed_zero_result = run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")
        self.assertEqual(self.paths["output"].read_bytes(), baseline)
        self.assertEqual(typed_zero_result["soft_boost"]["status"], "zero_upstream_unavailable")
        self.assertFalse(typed_zero_result["soft_boost"]["evidence_bundle_written"])
        self.assertEqual(
            typed_zero_result["soft_boost"]["consumption_receipt_path"],
            _rel(typed_zero_consumption),
        )
        self.assertTrue(typed_zero_consumption.is_file())
        self.assertFalse(typed_zero_shadow.exists())
        self.assertFalse(typed_zero_ledger.exists())

        # A same-date retry may learn a different typed-zero reason.  The frozen
        # receipt remains the honest reportable result; a write rejection must
        # not be swallowed into an unclaimed/invalid K4b result.
        empty_validation = copy.deepcopy(artifact)
        empty_validation["themes"] = []
        empty_validation["summary"]["validated_theme_count"] = 0
        empty_validation["summary"]["validated_member_count"] = 0
        _write_json(self.paths["soft_validation"], empty_validation)
        empty_validation_sha = hashlib.sha256(self.paths["soft_validation"].read_bytes()).hexdigest()
        valid_empty_stage = copy.deepcopy(stage)
        valid_empty_stage.update({
            "status": "valid_empty",
            "reason_code": "VALID_EMPTY",
            "validated_theme_count": 0,
            "boostable_ticker_count": 0,
        })
        valid_empty_stage["artifacts"]["validation"]["sha256"] = empty_validation_sha
        _write_json(self.paths["soft_stage"], valid_empty_stage)
        typed_zero_packet["optional_inputs"]["soft_discovery_stage_result"] = valid_empty_stage
        _write_json(self.packet, typed_zero_packet)
        frozen_zero_retry = run_packet(self.packet, generated_at="2026-07-04T00:00:03Z")
        self.assertEqual(frozen_zero_retry["soft_boost"]["status"], "zero_upstream_unavailable")
        self.assertEqual(frozen_zero_retry["soft_boost"]["reason_code"], "CANDIDATE_INPUT_UNAVAILABLE")
        self.assertEqual(
            frozen_zero_retry["soft_boost"]["consumption_receipt_path"],
            _rel(typed_zero_consumption),
        )
        self.assertEqual(
            json.loads(typed_zero_consumption.read_text(encoding="utf-8"))["status"],
            "zero_upstream_unavailable",
        )
        frozen_zero_bytes = typed_zero_consumption.read_bytes()
        typed_zero_consumption.write_text("{not-json", encoding="utf-8")
        unreadable_zero_retry = run_packet(self.packet, generated_at="2026-07-04T00:00:04Z")
        self.assertEqual(unreadable_zero_retry["soft_boost"]["status"], "zero_invalid_evidence")
        self.assertIsNone(unreadable_zero_retry["soft_boost"]["consumption_receipt_path"])
        typed_zero_consumption.unlink()
        _write_json(self.paths["soft_validation"], artifact)
        _write_json(self.paths["soft_stage"], stage)
        _write_json(self.packet, packet)
        typed_zero_consumption.write_bytes(frozen_zero_bytes)
        missing_components = copy.deepcopy(packet)
        missing_components["paths"].pop("output_context_components_path")
        _write_json(self.packet, missing_components)
        with self.assertRaisesRegex(SourcePacketError, "output_context_components_path"):
            run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")
        _write_json(self.packet, packet)
        loaded_packet, loaded_paths = _load_and_validate_packet(self.packet)
        common_digest = _soft_boost_common_input_sha256(loaded_packet, loaded_paths)
        changed_holdings = copy.deepcopy(loaded_packet)
        changed_holdings["optional_inputs"]["holdings"] = [{"ticker": "AAPL"}]
        self.assertNotEqual(
            common_digest,
            _soft_boost_common_input_sha256(changed_holdings, loaded_paths),
        )
        changed_theme_contract = dict(loaded_paths)
        alternate = self.state_dir / f"{self.slug}_alternate_theme_contract.json"
        _write_json(alternate, {"different": True})
        self.paths["alternate_theme_contract"] = alternate
        changed_theme_contract["theme_selection_contract_path"] = alternate
        self.assertNotEqual(
            common_digest,
            _soft_boost_common_input_sha256(loaded_packet, changed_theme_contract),
        )
        with mock.patch(
            "runners.us_short_batch5_data_context_source_packet.write_evidence_bundle",
            side_effect=__import__(
                "engine.us_short_soft_boost_consumption",
                fromlist=["SoftBoostConsumptionError"],
            ).SoftBoostConsumptionError("planted publication failure"),
        ):
            degraded_from_frozen_zero = run_packet(
                self.packet, generated_at="2026-07-04T00:00:02Z"
            )
        self.assertEqual(self.paths["output"].read_bytes(), baseline)
        self.assertFalse(degraded_from_frozen_zero["soft_boost"]["effective_enabled"])
        self.assertEqual(
            degraded_from_frozen_zero["soft_boost"]["status"],
            "zero_invalid_evidence",
        )
        self.assertFalse(degraded_from_frozen_zero["soft_boost"]["evidence_bundle_written"])
        self.assertIsNone(degraded_from_frozen_zero["soft_boost"]["consumption_receipt_path"])
        self.assertEqual(
            json.loads(typed_zero_consumption.read_text(encoding="utf-8"))["status"],
            "zero_upstream_unavailable",
        )
        from runners import us_short_weekly_capstone as capstone
        from types import SimpleNamespace

        lock = capstone._acquire_decision_lock(SimpleNamespace(
            state_dir=self.soft_state_dir, decision_date=_DECISION_DATE,
        ))
        try:
            # Model the only recoverable zero-to-valid state: the shadow and ledger
            # were published, but the final consumption receipt still contains the
            # earlier typed zero.
            typed_zero_consumption.unlink()
            run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")
            typed_zero_consumption.write_bytes(frozen_zero_bytes)
            result = run_packet(
                self.packet, generated_at="2026-07-04T00:00:02Z", decision_lock=lock,
            )
        finally:
            capstone._release_decision_lock(lock)

        written = json.loads(self.paths["output"].read_text(encoding="utf-8"))
        self.assertAlmostEqual(written["selection_inputs"]["per_ticker"]["AAPL"]["core_score"], 48.5)
        self.assertAlmostEqual(written["selection_inputs"]["per_ticker"]["MSFT"]["core_score"], 52.0)
        components = json.loads(self.paths["components"].read_text(encoding="utf-8"))
        self.assertEqual(
            components["score_composition"]["analysis_by_ticker"]["AAPL"][
                "provisional_theme_boost"
            ]["theme_soft_boost"],
            5.0,
        )
        self.assertNotEqual(self.paths["output"].read_bytes(), baseline)
        self.assertTrue(result["soft_boost"]["effective_enabled"])
        self.assertTrue(result["soft_boost"]["evidence_bundle_written"])
        receipt = json.loads(self.paths["soft_consumption"].read_text(encoding="utf-8"))
        self.assertFalse(receipt["effects"]["operation_advice_effect_claimed"])
        shadow = json.loads(self.paths["soft_shadow"].read_text(encoding="utf-8"))
        self.assertEqual(shadow["comparison"], ["soft_boost_on", "soft_boost_off"])
        self.assertFalse(shadow["provider_calls_performed"])
        self.assertNotIn("theme_off", self.paths["soft_shadow"].read_text(encoding="utf-8"))
        with mock.patch(
            "runners.us_short_batch5_data_context_source_packet.write_evidence_bundle",
            side_effect=__import__(
                "engine.us_short_soft_boost_consumption",
                fromlist=["SoftBoostConsumptionError"],
            ).SoftBoostConsumptionError("planted publication failure"),
        ):
            degraded = run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")
        self.assertEqual(self.paths["output"].read_bytes(), baseline)
        self.assertFalse(degraded["soft_boost"]["effective_enabled"])
        self.assertEqual(degraded["soft_boost"]["status"], "zero_invalid_evidence")
        self.assertFalse(degraded["soft_boost"]["evidence_bundle_written"])
        self.assertIsNone(degraded["soft_boost"]["consumption_receipt_path"])

        import engine.us_short_soft_boost_consumption as soft_consumer

        missing_plan = self.soft_state_dir / "missing_statistical_plan.json"
        with mock.patch.object(soft_consumer, "STATISTICAL_PLAN_PATH", missing_plan):
            missing_plan_result = run_packet(
                self.packet, generated_at="2026-07-04T00:00:02Z"
            )
        self.assertEqual(self.paths["output"].read_bytes(), baseline)
        self.assertFalse(missing_plan_result["soft_boost"]["effective_enabled"])
        self.assertEqual(
            missing_plan_result["soft_boost"]["reason_code"],
            "K4B_OPTIONAL_LIFECYCLE_REJECTED",
        )

        original_assemble = (
            source_packet_runner.assemble_official_context_components_from_resolved_pass2_sources
        )

        def unexplained_on_delta(**kwargs):
            value = original_assemble(**kwargs)
            if kwargs.get("theme_soft_boost_enabled") is True:
                value["data_context"]["selection_inputs"]["per_ticker"]["AAPL"]["core_score"] += 1.0
            return value

        with mock.patch(
            "runners.us_short_batch5_data_context_source_packet."
            "assemble_official_context_components_from_resolved_pass2_sources",
            side_effect=unexplained_on_delta,
        ):
            attribution_result = run_packet(
                self.packet, generated_at="2026-07-04T00:00:02Z"
            )
        self.assertEqual(self.paths["output"].read_bytes(), baseline)
        self.assertFalse(attribution_result["soft_boost"]["effective_enabled"])

        def out_of_range_on_score(**kwargs):
            value = original_assemble(**kwargs)
            if kwargs.get("theme_soft_boost_enabled") is True:
                value["data_context"]["selection_inputs"]["per_ticker"]["AAPL"][
                    "core_score"
                ] = 101.0
            return value

        with mock.patch(
            "runners.us_short_batch5_data_context_source_packet."
            "assemble_official_context_components_from_resolved_pass2_sources",
            side_effect=out_of_range_on_score,
        ):
            score_range_result = run_packet(
                self.packet, generated_at="2026-07-04T00:00:02Z"
            )
        self.assertEqual(self.paths["output"].read_bytes(), baseline)
        self.assertFalse(score_range_result["soft_boost"]["effective_enabled"])

        with mock.patch(
            "runners.us_short_batch5_data_context_source_packet."
            "_soft_boost_common_input_sha256",
            side_effect=OSError("planted unreadable K4b input"),
        ):
            unreadable_result = run_packet(
                self.packet, generated_at="2026-07-04T00:00:02Z"
            )
        self.assertEqual(self.paths["output"].read_bytes(), baseline)
        self.assertFalse(unreadable_result["soft_boost"]["effective_enabled"])
        self.assertEqual(operator_shadow_dir.exists(), operator_shadow_dir_existed)

    def test_provider_envelope_digests_are_required_before_consumption(self):
        packet = self._packet_payload()
        packet.pop("source_artifact_sha256")
        _write_json(self.packet, packet)
        with (
            mock.patch("runners.us_short_batch5_data_context_source_packet._validate_schema"),
            mock.patch(
                "runners.us_short_batch5_data_context_source_packet.assemble_data_context_from_resolved_pass2_sources",
                return_value={"universe": [], "selection_inputs": {"per_ticker": {}}},
            ),
        ):
            with self.assertRaisesRegex(SourcePacketError, "source_artifact_sha256"):
                run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")
        self.assertFalse(self.paths["output"].exists())

    def test_theme_selection_contract_digest_is_required_before_consumption(self):
        # The lifecycle/seat facts are a first-class local source, not a mutable sidecar added after packet review.
        contract = json.loads(self.paths["theme_contract"].read_text(encoding="utf-8"))
        contract["per_ticker"]["AAPL"]["theme_lifecycle_state"] = "decayed"
        _write_json(self.paths["theme_contract"], contract)
        with self.assertRaises(SourcePacketError):
            run_packet(self.packet)
        self.assertFalse(self.paths["output"].exists())

    def test_provider_envelopes_remain_semantically_bound_after_digest_refresh(self):
        cases = {
            "offering_provenance": (
                "offering_audit_source_path",
                self.paths["offering"],
                lambda payload: payload["provenance"]["AAPL"]["active_offering"].__setitem__("provider_id", "fmp"),
            ),
            "analyst_records": (
                "analyst_grade_actions_path",
                self.paths["analyst"],
                lambda payload: payload["records"].__setitem__("AAPL", []),
            ),
            "news_tally": (
                "massive_news_events_path",
                self.paths["news"],
                lambda payload: payload["signals"]["AAPL"]["news_recent"].update({
                    "positive": 0,
                    "neutral": 1,
                    "net_sentiment": 0,
                }),
            ),
            "news_post_observation": (
                "massive_news_events_path",
                self.paths["news"],
                lambda payload: payload["records"]["AAPL"][0].__setitem__(
                    "published_utc", "2026-06-15T08:01:00-04:00"
                ),
            ),
        }
        for label, (field, path, mutate) in cases.items():
            with self.subTest(case=label):
                self._write_sources_and_packet()
                payload = json.loads(path.read_text(encoding="utf-8"))
                mutate(payload)
                _write_json(path, payload)
                packet = self._packet_payload()
                packet["source_artifact_sha256"][field] = hashlib.sha256(path.read_bytes()).hexdigest()
                _write_json(self.packet, packet)
                with (
                    mock.patch("runners.us_short_batch5_data_context_source_packet._validate_schema"),
                    mock.patch(
                        "runners.us_short_batch5_data_context_source_packet.assemble_data_context_from_resolved_pass2_sources",
                        return_value={"universe": [], "selection_inputs": {"per_ticker": {}}},
                    ),
                ):
                    with self.assertRaisesRegex(SourcePacketError, "provider envelope"):
                        run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")
                self.assertFalse(self.paths["output"].exists())

    def test_bound_provider_envelopes_reach_assembly(self):
        with (
            mock.patch("runners.us_short_batch5_data_context_source_packet._validate_schema"),
            mock.patch(
                "runners.us_short_batch5_data_context_source_packet.assemble_data_context_from_resolved_pass2_sources",
                return_value={"universe": [], "selection_inputs": {"per_ticker": {}}},
            ),
        ):
            result = run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")
        self.assertEqual(result["scope"]["assembly_status"], "data_context_assembled_from_resolved_sources")

    def test_provider_envelope_digest_rejects_each_replaced_artifact(self):
        for field, path in (
            ("offering_audit_source_path", self.paths["offering"]),
            ("analyst_grade_actions_path", self.paths["analyst"]),
            ("massive_news_events_path", self.paths["news"]),
        ):
            with self.subTest(field=field):
                self._write_sources_and_packet()
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["replacement_probe"] = field
                _write_json(path, payload)
                with mock.patch("runners.us_short_batch5_data_context_source_packet._validate_schema"):
                    with self.assertRaisesRegex(SourcePacketError, "does not bind"):
                        run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")
                self.assertFalse(self.paths["output"].exists())

    def test_active_yfinance_source_bytes_and_provider_declaration_are_rejected(self):
        for label, mutate, refresh_digest, expected_message in (
            (
                "bytes",
                lambda payload: payload.__setitem__("replacement_probe", "yfinance-bytes"),
                False,
                "does not bind",
            ),
            (
                "provider_declaration",
                lambda payload: payload["provenance"]["AAPL"].__setitem__("provider_id", "fmp"),
                True,
                "provider envelope",
            ),
        ):
            with self.subTest(case=label):
                self._write_sources_and_packet()
                _write_json(
                    self.paths["yfinance"],
                    resolve_yfinance_grade_actions(
                        as_of=_GRADE_AS_OF,
                        grades_by_ticker={
                            "AAPL": self._yfinance_source([self._yfinance_row()]),
                            "MSFT": self._yfinance_source([], ticker="MSFT"),
                        },
                    ),
                )
                packet = self._packet_payload()
                packet["active_analyst_source"] = "yfinance"
                packet["paths"]["analyst_grade_actions_path"] = _rel(self.paths["yfinance"])
                packet["source_artifact_sha256"]["analyst_grade_actions_path"] = hashlib.sha256(
                    self.paths["yfinance"].read_bytes()
                ).hexdigest()
                _write_json(self.packet, packet)

                payload = json.loads(self.paths["yfinance"].read_text(encoding="utf-8"))
                mutate(payload)
                _write_json(self.paths["yfinance"], payload)
                if refresh_digest:
                    packet["source_artifact_sha256"]["analyst_grade_actions_path"] = hashlib.sha256(
                        self.paths["yfinance"].read_bytes()
                    ).hexdigest()
                    _write_json(self.packet, packet)

                with mock.patch("runners.us_short_batch5_data_context_source_packet._validate_schema"):
                    with self.assertRaisesRegex(SourcePacketError, expected_message):
                        run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")
                self.assertFalse(self.paths["output"].exists())

    def test_yfinance_grade_envelope_is_bound_when_selected(self):
        _write_json(
            self.paths["yfinance"],
            resolve_yfinance_grade_actions(
                as_of=_GRADE_AS_OF,
                grades_by_ticker={
                    "AAPL": self._yfinance_source([self._yfinance_row()]),
                    "MSFT": self._yfinance_source([], ticker="MSFT"),
                },
            ),
        )
        packet = self._packet_payload()
        packet["active_analyst_source"] = "yfinance"
        packet["paths"]["analyst_grade_actions_path"] = _rel(self.paths["yfinance"])
        packet["source_artifact_sha256"]["analyst_grade_actions_path"] = hashlib.sha256(
            self.paths["yfinance"].read_bytes()
        ).hexdigest()
        _write_json(self.packet, packet)
        with (
            mock.patch("runners.us_short_batch5_data_context_source_packet._validate_schema"),
            mock.patch(
                "runners.us_short_batch5_data_context_source_packet.assemble_data_context_from_resolved_pass2_sources",
                return_value={"universe": [], "selection_inputs": {"per_ticker": {}}},
            ),
        ):
            result = run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")
        self.assertEqual(result["scope"]["assembly_status"], "data_context_assembled_from_resolved_sources")

    def test_selected_yfinance_source_drives_cut4_analyst_coverage(self):
        # Required red control for R-USSHORT-ANALYST-SOURCE-COVERAGE-HEALTH-DRIFT:
        # scoring and Cut4 linkage must consume the same active analyst source.  The
        # canonical FMP shell is intentionally empty in this fixture.
        _write_json(
            self.paths["analyst"],
            resolve_analyst_grade_actions(
                as_of=_GRADE_AS_OF,
                grades_by_ticker={
                    # The canonical FMP-compatible shell deliberately has no
                    # official target coverage; only yfinance covers AAPL.
                    "JPM": _grade_source("JPM", []),
                },
            ),
        )
        _write_json(
            self.paths["yfinance"],
            resolve_yfinance_grade_actions(
                as_of=_GRADE_AS_OF,
                grades_by_ticker={
                    "AAPL": self._yfinance_source([self._yfinance_row()]),
                    "MSFT": self._yfinance_source([], ticker="MSFT"),
                },
            ),
        )
        packet = self._packet_payload()
        packet["source_artifact_sha256"]["analyst_grade_actions_path"] = hashlib.sha256(
            self.paths["analyst"].read_bytes()
        ).hexdigest()
        packet["active_analyst_source"] = "yfinance"
        packet["paths"]["analyst_grade_actions_path"] = _rel(self.paths["yfinance"])
        packet["source_artifact_sha256"]["analyst_grade_actions_path"] = hashlib.sha256(
            self.paths["yfinance"].read_bytes()
        ).hexdigest()
        packet["paths"]["output_context_components_path"] = _rel(self.paths["components"])
        _write_json(self.packet, packet)

        run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")

        components = json.loads(self.paths["components"].read_text(encoding="utf-8"))
        selection = components["data_context"]["selection_inputs"]["per_ticker"]
        self.assertNotEqual(selection["AAPL"]["core_score"], 50.0)
        self.assertEqual(
            components["result_linkage_sources"]["AAPL"]["coverage"]["data_checks"]["analyst"],
            "ok",
        )

    def test_cli_default_accepts_legacy_projection_inputs_profile(self):
        targets = ("AAPL", "MSFT")
        _write_json(
            self.paths["momentum"],
            _constant_projection(
                "momentum_by_ticker", targets, "scored", score=50.0,
                candidate_path=self.paths["candidate"], component="momentum",
            ),
        )
        _write_json(
            self.paths["theme"],
            _constant_projection(
                "theme_block_by_ticker", targets, "scored_theme_base", score=50.0,
                candidate_path=self.paths["candidate"], component="theme",
            ),
        )
        with mock.patch("builtins.print"):
            self.assertEqual(main(["--packet-path", str(self.packet)]), 0)
        self.assertTrue(self.paths["output"].exists())

    def test_cli_default_rejects_full_candidate_live_profile(self):
        with mock.patch("builtins.print"), self.assertRaisesRegex(SourcePacketError, "producer is not authorized"):
            main(["--packet-path", str(self.packet)])
        self.assertFalse(self.paths["output"].exists())

    def test_stale_clock_source_projection_binding_is_rejected(self):
        # Reverse control (Required B, core-score/official-output consumer): a stale-clock momentum
        # source binding is rejected before any official data-context component is written.
        momentum = _constant_projection(
            "momentum_by_ticker", ("AAPL", "MSFT"), "scored", score=50.0,
            candidate_path=self.paths["candidate"], component="momentum",
            producer_id="us_short_batch5_full_candidate_live_source_packet",
            source_roles=("parent_momentum_projection",),
        )
        momentum["source_binding"]["decision_clock"]["expected_decision_date"] = "20260614"
        _write_json(self.paths["momentum"], momentum)
        with self.assertRaisesRegex(SourcePacketError, "source binding"):
            run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")
        self.assertFalse(self.paths["output"].exists())

    def test_wrong_projection_producer_is_rejected(self):
        momentum = json.loads(self.paths["momentum"].read_text(encoding="utf-8"))
        momentum["source_binding"]["producer_id"] = "unreviewed_projection_producer"
        _write_json(self.paths["momentum"], momentum)
        with self.assertRaisesRegex(SourcePacketError, "producer is not authorized"):
            run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")
        self.assertFalse(self.paths["output"].exists())

    def test_wrong_projection_source_role_is_rejected(self):
        theme = json.loads(self.paths["theme"].read_text(encoding="utf-8"))
        theme["source_binding"]["source_artifacts"][0]["role"] = "unreviewed_theme_source"
        _write_json(self.paths["theme"], theme)
        with self.assertRaisesRegex(SourcePacketError, "source artifact roles"):
            run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")
        self.assertFalse(self.paths["output"].exists())

    def test_run_packet_optionally_writes_official_context_components(self):
        _write_json(
            self.paths["offering"],
            resolve_offering_audit(
                as_of=_OFFERING_AS_OF,
                filings_by_ticker={
                    "AAPL": _offering_record([]),
                    "MSFT": _offering_record([]),
                    "JPM": _offering_record([], coverage="partial"),
                },
            ),
        )
        packet = self._packet_payload()
        packet["paths"]["output_context_components_path"] = _rel(self.paths["components"])
        _write_json(self.paths["packet"], packet)

        result = run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")

        self.assertTrue(result["scope"]["context_components_written"])
        self.assertEqual(result["context_components"]["output_path"], _rel(self.paths["components"]))
        components = json.loads(self.paths["components"].read_text(encoding="utf-8"))
        self.assertEqual(
            set(components),
            {"data_context", "score_composition", "overextension_by_ticker", "per_ticker_analysis", "run_provenance",
             "result_linkage_sources"},
        )
        self.assertEqual(set(components["per_ticker_analysis"]), {"AAPL", "MSFT"})
        self.assertIsNone(components["overextension_by_ticker"])
        self.assertNotIn("overextension", components["per_ticker_analysis"]["AAPL"])
        self.assertEqual(
            components["per_ticker_analysis"]["AAPL"]["row_source"],
            "top15_candidate",
        )
        source_refs = components["run_provenance"]["families"]["candidate_pass2_signals"]["source_refs"]
        self.assertIn(
            {"role": "offering_audit_source", "path": _rel(self.paths["offering"])},
            source_refs,
        )

    def test_run_packet_validates_current_components_before_writing_them(self):
        packet = self._packet_payload()
        packet["paths"]["output_context_components_path"] = _rel(self.paths["components"])
        _write_json(self.packet, packet)
        original = source_packet_runner.validate_current_context_components

        with mock.patch.object(
            source_packet_runner,
            "validate_current_context_components",
            wraps=original,
        ) as validator:
            run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")

        validator.assert_called_once()
        written = json.loads(self.paths["components"].read_text(encoding="utf-8"))
        self.assertEqual(validator.call_args.args[0], written)

    def test_current_components_rejection_happens_before_component_output_write(self):
        packet = self._packet_payload()
        packet["paths"]["output_context_components_path"] = _rel(self.paths["components"])
        _write_json(self.packet, packet)

        with mock.patch.object(
            source_packet_runner,
            "validate_current_context_components",
            side_effect=SourcePacketError("planted current-shape rejection"),
        ):
            with self.assertRaisesRegex(SourcePacketError, "planted current-shape rejection"):
                run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")

        self.assertFalse(self.paths["components"].exists())
        self.assertFalse(self.paths["output"].exists())

    def test_run_packet_context_components_preserve_holdings_union_row_sources(self):
        _write_json(
            self.paths["offering"],
            resolve_offering_audit(
                as_of=_OFFERING_AS_OF,
                filings_by_ticker={
                    "AAPL": _offering_record([]),
                    "MSFT": _offering_record([]),
                    "JPM": _offering_record([], coverage="partial"),
                },
            ),
        )
        packet = self._packet_payload()
        packet["paths"]["output_context_components_path"] = _rel(self.paths["components"])
        packet["optional_inputs"]["holdings"] = [
            {"ticker": "AAPL", "signals": {}},
            {"ticker": "JPM", "signals": {"critical_data_missing": True}},
            {"ticker": "TSLA", "signals": {"critical_data_missing": True}},
        ]
        _write_json(self.paths["packet"], packet)

        result = run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")

        self.assertTrue(result["scope"]["context_components_written"])
        components = json.loads(self.paths["components"].read_text(encoding="utf-8"))
        rows = components["per_ticker_analysis"]
        self.assertEqual(set(rows), {"AAPL", "MSFT", "JPM", "TSLA"})
        self.assertEqual(rows["AAPL"]["row_source"], "holding_in_top15")
        self.assertEqual(rows["MSFT"]["row_source"], "top15_candidate")
        self.assertEqual(rows["JPM"]["row_source"], "holding_pass2_only")
        self.assertEqual(rows["TSLA"]["row_source"], "holding_account_only")
        self.assertEqual(rows["TSLA"]["signals"], {"critical_data_missing": True})
        self.assertEqual(
            components["run_provenance"]["families"]["per_ticker_analysis"]["row_count"],
            4,
        )

    def test_optional_overextension_projection_reaches_selection_analysis_and_source_binding(self):
        _write_json(
            self.paths["offering"],
            resolve_offering_audit(
                as_of=_OFFERING_AS_OF,
                filings_by_ticker={
                    "AAPL": _offering_record([]),
                    "MSFT": _offering_record([]),
                    "JPM": _offering_record([], coverage="partial"),
                },
            ),
        )
        _write_json(self.paths["overextension"], _overextension_projection())
        packet = self._packet_payload()
        packet["paths"]["overextension_projection_path"] = _rel(self.paths["overextension"])
        packet["paths"]["overextension_candidate_artifact_path"] = _rel(self.paths["candidate"])
        packet["paths"]["output_context_components_path"] = _rel(self.paths["components"])
        _write_json(self.paths["packet"], packet)

        result = run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")

        self.assertEqual(result["source_artifacts"]["local_source_artifacts_read"], 11)
        components = json.loads(self.paths["components"].read_text(encoding="utf-8"))
        selection = components["data_context"]["selection_inputs"]["per_ticker"]
        rows = components["per_ticker_analysis"]
        self.assertEqual(selection["AAPL"]["theme_momentum_score"], 0.0)
        self.assertEqual(rows["AAPL"]["scoring_profile"], "balanced")
        self.assertEqual(rows["AAPL"]["overextension"]["overextension_state"], "chasing_extreme")
        self.assertEqual(rows["MSFT"]["overextension"]["overextension_state"], "warning")
        self.assertTrue(rows["MSFT"]["overextension"]["execution_flags"]["raise_rr_gate"])
        source_refs = components["run_provenance"]["families"]["selection_inputs"]["source_refs"]
        self.assertIn(
            {"role": "overextension_projection", "path": _rel(self.paths["overextension"])},
            source_refs,
        )
        self.assertIn(
            {"role": "overextension_candidate_artifact", "path": _rel(self.paths["candidate"])},
            source_refs,
        )
        self.assertEqual(
            components["run_provenance"]["families"]["selection_inputs"]["observed_at"],
            "2026-06-15T08:30:00",
        )
        self.assertIn(
            "overextension_projection_path",
            {field for field, _, _ in source_packet_input_manifest(self.packet)},
        )

    def test_overextension_projection_and_full_candidate_paths_must_be_paired(self):
        _write_json(self.paths["overextension"], _overextension_projection())
        base_packet = self._packet_payload()
        for field in ("overextension_projection_path", "overextension_candidate_artifact_path"):
            with self.subTest(only_path=field):
                packet = json.loads(json.dumps(base_packet))
                packet["paths"][field] = _rel(
                    self.paths["overextension"] if field == "overextension_projection_path" else self.paths["candidate"]
                )
                _write_json(self.paths["packet"], packet)
                with self.assertRaises(SourcePacketError):
                    run_preflight(self.packet)

    def test_overextension_projection_clock_and_candidate_binding_fail_closed(self):
        packet = self._packet_payload()
        packet["paths"]["overextension_projection_path"] = _rel(self.paths["overextension"])
        packet["paths"]["overextension_candidate_artifact_path"] = _rel(self.paths["candidate"])
        _write_json(self.paths["packet"], packet)
        def forge_contract_and_rows(projection):
            projection["source_contract"]["session"] = "EXT"
            for tier in projection["overextension_by_ticker"].values():
                tier["pit"]["session"] = "EXT"

        mutations = {
            "future_price_basis": lambda p: p["decision_clock"].__setitem__("price_basis_date", "2099-01-01"),
            "wrong_decision": lambda p: p["decision_clock"].__setitem__("expected_decision_date", "20260616"),
            "wrong_session": lambda p: p["source_contract"].__setitem__("session", "EXT"),
            "wrong_adjustment": lambda p: p["source_contract"].__setitem__("adjustment_mode", "raw"),
            "self_consistent_but_untrusted_session": forge_contract_and_rows,
            "wrong_candidate_digest": lambda p: p["candidate_binding"].__setitem__(
                "eligible_tickers_sha256", "0" * 64),
            "missing_pit": lambda p: p["overextension_by_ticker"]["AAPL"].pop("pit"),
            "future_row_pit": lambda p: p["overextension_by_ticker"]["AAPL"]["pit"].__setitem__(
                "as_of", "2099-01-01"),
            "chasing_below_min_condition_count": lambda p: p["overextension_by_ticker"]["MSFT"].update({
                "overextension_state": "chasing_extreme",
                "strips_theme_score": True,
                "execution_flags": {},
                "conditions_met": 2,
                "condition_names": ["vertical_run", "volume_climax"],
            }),
            "bool_disposition_count": lambda p: p["disposition_counts"].__setitem__(
                "insufficient_data", False),
        }
        for label, mutate in mutations.items():
            with self.subTest(case=label):
                projection = _overextension_projection()
                mutate(projection)
                _write_json(self.paths["overextension"], projection)
                with self.assertRaises(SourcePacketError):
                    run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")
                self.assertFalse(self.paths["output"].exists())

    def test_optional_yfinance_grade_actions_prefer_yfinance_and_keep_missing_neutral(self):
        _write_json(
            self.paths["offering"],
            resolve_offering_audit(
                as_of=_OFFERING_AS_OF,
                filings_by_ticker={
                    "AAPL": _offering_record([]),
                    "MSFT": _offering_record([]),
                    "JPM": _offering_record([], coverage="partial"),
                },
            ),
        )
        _write_json(
            self.paths["yfinance"],
            resolve_yfinance_grade_actions(
                as_of=_GRADE_AS_OF,
                grades_by_ticker={
                    "AAPL": self._yfinance_source([], coverage="missing", parser="failed"),
                    "MSFT": self._yfinance_source([], ticker="MSFT"),
                },
            ),
        )
        packet = self._packet_payload()
        packet["active_analyst_source"] = "yfinance"
        packet["paths"]["analyst_grade_actions_path"] = _rel(self.paths["yfinance"])
        packet["source_artifact_sha256"]["analyst_grade_actions_path"] = hashlib.sha256(
            self.paths["yfinance"].read_bytes()
        ).hexdigest()
        packet["paths"]["output_context_components_path"] = _rel(self.paths["components"])
        _write_json(self.paths["packet"], packet)

        result = run_packet(self.packet, generated_at="2026-07-04T00:00:02Z")

        self.assertEqual(result["source_artifacts"]["local_source_artifacts_read"], 9)
        components = json.loads(self.paths["components"].read_text(encoding="utf-8"))
        selection = components["data_context"]["selection_inputs"]["per_ticker"]
        self.assertAlmostEqual(selection["AAPL"]["core_score"], 51.5)
        aapl_linkage = components["result_linkage_sources"]["AAPL"]
        self.assertEqual(aapl_linkage["coverage"]["data_checks"]["analyst"], "restricted")
        self.assertEqual(aapl_linkage["coverage"]["coverage_status"], "restricted")
        self.assertIn("analyst:restricted", aapl_linkage["coverage"]["coverage_gap_tags"])
        self.assertNotIn("provider_health", components)
        self.assertNotIn("provider_health_facts", components)
        self.assertNotIn("emit", components)
        self.assertNotIn("ship_gate", components)
        source_refs = components["run_provenance"]["families"]["selection_inputs"]["source_refs"]
        self.assertIn({"role": "analyst_grade_actions", "path": _rel(self.paths["yfinance"])}, source_refs)
        self.assertNotIn({"role": "yfinance_grade_actions", "path": _rel(self.paths["yfinance"])}, source_refs)
        self.assertNotIn(
            "yfinance_grade_actions_path",
            {field for field, _, _ in source_packet_input_manifest(self.packet)},
        )

    def test_output_path_must_be_gitignored_state_file(self):
        packet = self._packet_payload()
        packet["paths"]["output_data_context_path"] = "docs/us_short_leaky_data_context.json"
        _write_json(self.paths["packet"], packet)

        with self.assertRaises(SourcePacketError):
            run_packet(self.packet, generated_at="2026-07-04T00:00:03Z")
        self.assertFalse((ROOT / "docs" / "us_short_leaky_data_context.json").exists())

    def test_scope_creep_flag_is_rejected(self):
        packet = self._packet_payload()
        packet["scope"]["network_access_performed"] = True
        _write_json(self.paths["packet"], packet)

        with self.assertRaises(SourcePacketError):
            run_preflight(self.packet)
        self.assertFalse(self.paths["output"].exists())

    def test_missing_source_artifact_rejected_before_write(self):
        self.paths["news"].unlink()

        with self.assertRaises(SourcePacketError):
            run_packet(self.packet, generated_at="2026-07-04T00:00:04Z")
        self.assertFalse(self.paths["output"].exists())

    def test_source_artifacts_must_not_point_at_provider_samples_raw_payloads(self):
        _write_json(self.paths["raw_payload"], {"raw": True})
        packet = self._packet_payload()
        packet["paths"]["massive_news_events_path"] = _rel(self.paths["raw_payload"])
        _write_json(self.paths["packet"], packet)

        with self.assertRaises(SourcePacketError):
            run_preflight(self.packet, generated_at="2026-07-04T00:00:05Z")
        self.assertFalse(self.paths["output"].exists())

    def test_preflight_rejects_non_gitignored_packet_path_before_write(self):
        leaky_packet = ROOT / "docs" / f"{self.slug}_packet.json"
        self.addCleanup(leaky_packet.unlink, missing_ok=True)
        _write_json(leaky_packet, self._packet_payload())

        with self.assertRaises(SourcePacketError):
            run_preflight(leaky_packet, generated_at="2026-07-04T00:00:05Z")
        self.assertFalse(self.paths["output"].exists())

    def test_malformed_catalyst_governance_is_wrapped_by_packet_runner(self):
        bad_governance = self.state_dir / f"{self.slug}_bad_catalyst_governance.json"
        self.paths["bad_governance"] = bad_governance
        _write_json(bad_governance, {"broken": True})
        packet = self._packet_payload()
        packet["paths"]["catalyst_governance_path"] = _rel(bad_governance)
        _write_json(self.paths["packet"], packet)

        with self.assertRaises(SourcePacketError):
            run_packet(self.packet, generated_at="2026-07-04T00:00:06Z")
        self.assertFalse(self.paths["output"].exists())

    def test_preflight_rejects_wrong_shape_root_packet(self):
        _write_json(self.paths["packet"], ["not", "an", "object"])

        with self.assertRaises(SourcePacketError):
            run_preflight(self.packet)


if __name__ == "__main__":
    unittest.main()
