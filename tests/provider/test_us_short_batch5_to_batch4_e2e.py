from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_fmp_analyst_grades import resolve_analyst_grade_actions  # noqa: E402
from engine.us_short_massive_news import resolve_news_events  # noqa: E402
from engine.us_short_provider_health import REQUIRED_HEALTH_KEYS  # noqa: E402
from engine.us_short_projection_binding import build_projection_binding  # noqa: E402
from engine.us_short_result_source_linkage import validate_result_source_fact  # noqa: E402
from engine.us_short_sec_offering_audit import resolve_offering_audit  # noqa: E402
from runners import us_short_batch5_to_batch4_weekend_e2e as e2e  # noqa: E402
from runners import us_short_weekly_capstone_stages as capstone_stages  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _GRADE_AS_OF,
    _NEWS_AS_OF,
    _OFFERING_AS_OF,
    _candidate_artifact,
    _constant_projection,
    _grade_source,
    _news_source,
    _offering_record,
)
from tests.provider.us_short_private_test_root import temporary_us_short_state_directory  # noqa: E402


TEMPLATE = ROOT / "schemas" / "examples" / "us_short_weekend_batch4_context_packet.nonempty.example.json"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _empty_account() -> dict:
    return {
        "schema_name": "us_short_account_state",
        "schema_version": "1.0.0",
        "as_of": _DECISION_DATE,
        "us_market_equity": 30000.0,
        "us_short_bucket_capital": 10000.0,
        "us_short_available_cash": 4000.0,
        "positions": [],
        "holding_action_reconciliation": {
            "schema_name": "us_short_holding_action_reconciliation", "schema_version": "1.0.0",
            "as_of": _DECISION_DATE, "positions": []},
        "symbol_cooldown_reconciliation": {
            "schema_name": "us_short_symbol_cooldown_reconciliation", "schema_version": "1.0.0",
            "as_of": _DECISION_DATE, "events": []},
        "manual_order_only": True,
        "broker_connection_allowed": False,
    }


def _provider_health(**overrides) -> dict[str, str]:
    values = {key: "ok" for key in REQUIRED_HEALTH_KEYS}
    values.update(overrides)
    return values


def _no_build_template(path: Path) -> Path:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    payload["sizing_per_ticker"] = {}
    payload["basket_context"]["per_ticker"] = {}
    return _write_json(path, payload)


def _overextension_for_current_aapl() -> dict:
    ticker = "AAPL"
    digest = hashlib.sha256(json.dumps([ticker], separators=(",", ":")).encode("ascii")).hexdigest()
    return {
        "schema_name": "us_short_full_universe_overextension_projection",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-15T08:30:00-04:00",
        "decision_clock": {
            "expected_decision_date": _DECISION_DATE,
            "candidate_price_basis_date": "20260612",
            "price_basis_date": "2026-06-12",
            "source_as_of": "2026-06-12",
        },
        "source_contract": {"session": "RTH", "adjustment_mode": "split_adjusted"},
        "candidate_binding": {"eligible_count": 1, "eligible_tickers_sha256": digest},
        "overextension_by_ticker": {
            ticker: {
                "overextension_state": "none",
                "strips_theme_score": False,
                "execution_flags": {},
                "conditions_met": 0,
                "condition_names": [],
                "disposition": "scored",
                "pit": {
                    "as_of": "2026-06-12",
                    "session": "RTH",
                    "adjustment_mode": "split_adjusted",
                    "n_points": 70,
                },
            },
        },
        "disposition_counts": {"scored": 1, "insufficient_data": 0},
        "scored_count": 1,
        "target_count": 1,
    }


def _forward_ohlcv_packet(*, decision_date: str, price_basis_date: str, start_date: str, points: int) -> dict:
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    rows = []
    for offset in range(points):
        current = start.fromordinal(start.toordinal() + offset)
        rows.append({
            "date": current.isoformat(), "open": 100.0, "high": 101.0,
            "low": 99.0, "close": 100.0, "volume": 1000.0,
        })
    price_basis_iso = f"{price_basis_date[:4]}-{price_basis_date[4:6]}-{price_basis_date[6:]}"
    return {
        "schema_name": "us_short_batch5_full_universe_ohlcv_series_packet",
        "schema_version": "1.0.0",
        "generated_at": "2026-06-15T13:00:00Z",
        "scope": {
            "market": "US", "lane": "us_short", "batch": "batch5_provider_live",
            "packet_status": "full_universe_per_ticker_ohlcv_series_ready_for_local_overextension_projection",
            "full_market_reconstruction": True, "network_access_performed_by_packet_producer": False,
            "provider_calls_performed_by_packet_producer": False, "raw_payload_refs_gitignored": True,
            "datahub_consumption_allowed": False, "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False, "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {
            "expected_decision_date": decision_date,
            "candidate_price_basis_date": price_basis_date,
            "price_basis_date": price_basis_iso,
            "source_as_of": price_basis_iso,
        },
        "series_contract": {
            "session": "regular", "adjustment_mode": "split_dividend_adjusted",
            "as_of": price_basis_iso, "grouped_session_count": points,
        },
        "provenance": {
            "provider_id": "massive", "endpoint_or_family": "grouped_daily",
            "source_as_of": price_basis_iso, "observed_at": "2026-06-15T13:00:00Z",
            "coverage_status": "full", "parser_status": "ok",
        },
        "series_by_ticker": {
            "AAPL": {
                "as_of": price_basis_iso, "session": "regular",
                "adjustment_mode": "split_dividend_adjusted", "points": rows,
            },
        },
    }


class Batch5ToBatch4E2ETest(unittest.TestCase):
    def setUp(self) -> None:
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_dir = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self.slug = f"test_batch5_to_batch4_e2e_{os.getpid()}_{self._testMethodName}"
        self.paths = {
            "packet": self.state_dir / f"{self.slug}_packet.json",
            "candidate": self.state_dir / f"{self.slug}_candidate.json",
            "momentum": self.state_dir / f"{self.slug}_momentum.json",
            "theme": self.state_dir / f"{self.slug}_theme.json",
            "offering": self.state_dir / f"{self.slug}_offering.json",
            "analyst": self.state_dir / f"{self.slug}_analyst.json",
            "news": self.state_dir / f"{self.slug}_news.json",
            "theme_contract": self.state_dir / f"{self.slug}_theme_selection_contract.json",
            "ohlcv": self.state_dir / f"{self.slug}_ohlcv.json",
            "overextension": self.state_dir / f"{self.slug}_overextension.json",
            "data_context": self.state_dir / f"{self.slug}_data_context.json",
            "components": self.state_dir / f"{self.slug}_context_components.json",
        }
        for path in self.paths.values():
            path.unlink(missing_ok=True)
        self._write_source_packet()

    def tearDown(self) -> None:
        for path in self.paths.values():
            path.unlink(missing_ok=True)

    def _write_source_packet(self) -> None:
        targets = ("AAPL",)
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "LOWADV")))
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
        _write_json(
            self.paths["offering"],
            resolve_offering_audit(as_of=_OFFERING_AS_OF, filings_by_ticker={"AAPL": _offering_record([])}),
        )
        _write_json(
            self.paths["analyst"],
            resolve_analyst_grade_actions(as_of=_GRADE_AS_OF, grades_by_ticker={"AAPL": _grade_source("AAPL", [])}),
        )
        _write_json(
            self.paths["news"],
            resolve_news_events(as_of=_NEWS_AS_OF, news_by_ticker={"AAPL": _news_source("AAPL", [])}),
        )
        _write_json(
            self.paths["theme_contract"],
            {"as_of": _DECISION_DATE, "mode": "industry_heat_v1_cross_industry_disabled",
             "cross_industry_provisional_enabled": False, "theme_opportunity_state": "no_strong_theme",
             "per_ticker": {"AAPL": {"theme_id": "industry:aapl", "theme_source": "industry_heat_v1",
                                       "theme_lifecycle_state": "confirmed_active", "theme_leader_rs": 0.0,
                                       "membership_origin": "automatic_discovery", "market_confirmed": True,
                                       "individual_theme_gate_passed": True, "overextension_state": "none",
                                       "macro_cluster": "unclassified_conservative"}}},
        )
        _write_json(
            self.paths["packet"],
            {
                "schema_name": "us_short_batch5_data_context_source_packet",
                "schema_version": "1.3.0",
                "generated_at": "2026-06-15T08:05:00-04:00",
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
                    "theme_opportunity_state": "no_strong_theme",
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
                    "output_data_context_path": _rel(self.paths["data_context"]),
                },
                "optional_inputs": {"holdings": [], "catalyst_recall_feed": None},
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
            },
        )

    def test_vix_regime_override_changes_only_vix_axis(self) -> None:
        template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        original_axes = dict(template["market_axis_regimes"])
        components = {
            "data_context": {"selection_inputs": {"theme_opportunity_state": "no_strong_theme"}},
            "per_ticker_analysis": {},
            "run_provenance": {"as_of": _DECISION_DATE, "price_basis_date": "20260612"},
        }
        packet = e2e._assemble_batch4_packet(
            components=components,
            template=template,
            provider_health=_provider_health(),
            account_state_path=Path("account.json"),
            calendar_path=Path("calendar.json"),
            governance_path=Path("governance.json"),
            private_root=Path("private"),
            official_output_root=None,
            now_et=datetime(2026, 6, 15, 9, 0, 0),
            vix_regime="防御",
        )
        self.assertEqual(packet["market_axis_regimes"]["vix"], "防御")
        self.assertEqual(packet["market_axis_regimes"]["market_trend"], original_axes["market_trend"])
        self.assertEqual(packet["market_axis_regimes"]["breadth"], original_axes["breadth"])

    def test_explicit_model_paper_track_replaces_template_and_omission_preserves_fixture_path(self) -> None:
        template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        components = {
            "data_context": {"selection_inputs": {"theme_opportunity_state": "no_strong_theme"}},
            "per_ticker_analysis": {},
            "run_provenance": {"as_of": _DECISION_DATE, "price_basis_date": "20260612"},
        }
        track = {
            "paper_evaluable": True,
            "consecutive_stops": 0,
            "paper_drawdown_frac": 0.0,
            "evidence_ref": {"kind": "source_id", "value": "model_paper_nav:e2e-test", "as_of": _DECISION_DATE},
        }
        kwargs = {
            "components": components,
            "template": template,
            "provider_health": _provider_health(),
            "account_state_path": Path("account.json"),
            "calendar_path": Path("calendar.json"),
            "governance_path": Path("governance.json"),
            "private_root": Path("private"),
            "official_output_root": None,
            "now_et": datetime(2026, 6, 15, 9, 0, 0),
        }
        supplied = e2e._assemble_batch4_packet(**kwargs, model_paper_track=track)
        self.assertEqual(supplied["paper_track"], track)
        self.assertIsNot(supplied["paper_track"], track)
        template_path = e2e._assemble_batch4_packet(**kwargs)
        self.assertEqual(
            template_path["paper_track"]["evidence_ref"]["value"],
            "synthetic_fixture:paper_track_not_evaluable",
        )

    def test_provider_bridge_rejects_research_live_when_it_consumes_action_template(self) -> None:
        """This bridge always consumes a caller template, so it cannot emit the fully-provider-derived label."""
        with self.assertRaisesRegex(e2e.Batch5ToBatch4E2EError, "must use mixed_source"):
            e2e.run_e2e(
                source_packet_path=Path("missing-source.json"),
                batch4_template_path=Path("missing-template.json"),
                account_state_path=Path("missing-account.json"),
                provider_health_path=Path("missing-health.json"),
                private_root=Path("missing-private"),
                now_et=datetime(2026, 6, 15, 9, 0, 0),
                run_mode="research_live",
            )

    def test_template_bytes_must_match_receipt_digest_at_parse(self) -> None:
        """A post-receipt replacement must fail before its action inputs can be consumed."""
        with tempfile.TemporaryDirectory() as directory:
            template = Path(directory) / "batch4_template.json"
            template.write_bytes(TEMPLATE.read_bytes())
            expected = hashlib.sha256(template.read_bytes()).hexdigest()
            template.write_text('{"replaced": true}', encoding="utf-8")
            with self.assertRaises(e2e.Batch5ToBatch4E2EError):
                e2e._load_template(template, expected_sha256=expected)

    def test_local_source_packet_to_private_weekly_report_and_action_table(self) -> None:
        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", _provider_health())
            template = _no_build_template(private_root / "batch4_template.json")
            context_out = private_root / "context_packet.json"

            summary = e2e.run_e2e(
                source_packet_path=self.paths["packet"],
                batch4_template_path=template,
                account_state_path=account,
                provider_health_path=health,
                private_root=private_root,
                now_et=datetime(2026, 6, 15, 9, 0, 0),
                context_components_path=self.paths["components"],
                context_packet_path=context_out,
                bootstrap_lifecycle=True,
                generated_at="2026-06-15T13:01:00Z",
            )

            self.assertEqual(summary["scope"]["status"], "batch5_source_packet_to_batch4_outputs_completed")
            self.assertFalse(summary["scope"]["network_access_required"])
            self.assertFalse(summary["scope"]["provider_calls_performed"])
            self.assertFalse(summary["scope"]["datahub_consumption_allowed"])
            self.assertFalse(summary["scope"]["ship_gate_evidence_claimed"])
            self.assertTrue(summary["batch4_run"]["emitted"])
            self.assertEqual(summary["batch4_run"]["decision_date"], _DECISION_DATE)
            self.assertEqual(summary["batch4_run"]["row_count"], 1)
            self.assertTrue((private_root / "weekly_private" / _DECISION_DATE / "weekly_report.md").exists())
            self.assertTrue((private_root / "weekly_private" / _DECISION_DATE / "action_table.csv").exists())
            self.assertTrue((private_root / "runs_private" / _DECISION_DATE / "machine_record.json").exists())
            self.assertTrue(self.paths["components"].exists())
            context_packet = json.loads(context_out.read_text(encoding="utf-8"))
            # Cut4 preserves the receipt-bound close in provenance, but never lets close-only data enter the
            # price engine.  It therefore cannot create synthetic ATR/support geometry or a new build.
            row = context_packet["per_ticker_analysis"]["AAPL"]
            self.assertEqual(row["price_input"], {})
            self.assertEqual(row["source_result_facts"]["price"]["status"], "close_only")
            self.assertEqual(row["source_result_facts"]["price"]["input"], {"close": 200.0})
            self.assertEqual(row["coverage_status"], "partial")
            machine = json.loads(
                (private_root / "runs_private" / _DECISION_DATE / "machine_record.json").read_text(encoding="utf-8")
            )["rows"][0]
            self.assertEqual(machine["coverage_status"], "partial")
            self.assertEqual(machine["data_quality_tags"], row["data_quality_tags"])
            self.assertEqual(machine["final_action"], "\u89c2\u5bdf")
            self.assertEqual(machine["observe_reason_type"], "price_not_executable")
            action_csv = (private_root / "weekly_private" / _DECISION_DATE / "action_table.csv").read_text(encoding="utf-8")
            self.assertIn("coverage_status", action_csv.splitlines()[0])
            self.assertIn("partial", action_csv.splitlines()[1])

    def test_same_date_rerun_reuses_one_earlier_prior_and_publishes_four_states(self) -> None:
        """The bridge/orchestrator/writer path must not treat the first same-date slot as a new prior week."""
        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            prior_dir = private_root / "runs_private" / "20260612"
            _write_json(prior_dir / "machine_record.json", {})
            _write_json(prior_dir / "market_regime_state.json", {
                "schema_name": "us_short_market_regime_state", "schema_version": "1.0.0",
                "as_of": "20260612", "market_risk_regime": "防御", "upgrade_count": 1,
            })
            _write_json(prior_dir / "holding_action_state.json", {
                "schema_name": "us_short_holding_action_state", "schema_version": "1.0.0",
                "as_of": "20260612", "positions": [],
            })
            _write_json(prior_dir / "portfolio_guard_state.json", {
                "schema_name": "us_short_portfolio_guard_state", "schema_version": "1.0.0",
                "as_of": "20260612", "state": "normal",
            })
            _write_json(prior_dir / "symbol_cooldown_state.json", {
                "schema_name": "us_short_symbol_cooldown_state", "schema_version": "1.0.0",
                "as_of": "20260612", "records": [],
            })
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", _provider_health())
            template_payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
            template_payload["prior_regime"] = "进攻"
            template_payload["prior_upgrade_count"] = 99
            template = _write_json(private_root / "batch4_template.json", template_payload)

            kwargs = dict(
                source_packet_path=self.paths["packet"], batch4_template_path=template,
                account_state_path=account, provider_health_path=health, private_root=private_root,
                now_et=datetime(2026, 6, 15, 9, 0, 0), context_components_path=self.paths["components"],
                bootstrap_lifecycle=True, generated_at="2026-06-15T13:01:00Z",
            )
            first = e2e.run_e2e(**kwargs)
            first_context = json.loads(Path(first["context_packet"]["path"]).read_text(encoding="utf-8"))
            second = e2e.run_e2e(**kwargs)

            context = json.loads(Path(second["context_packet"]["path"]).read_text(encoding="utf-8"))
            self.assertEqual(context["prior_regime"], "防御")
            self.assertEqual(context["prior_upgrade_count"], 1)
            self.assertEqual(Path(context["prior_run_dir"]).resolve(), prior_dir.resolve())
            self.assertEqual(first_context["prior_run_dir"], context["prior_run_dir"])
            current_dir = private_root / "runs_private" / _DECISION_DATE
            self.assertTrue(current_dir.is_dir())
            self.assertTrue({
                "machine_record.json", "market_regime_state.json", "holding_action_state.json",
                "portfolio_guard_state.json", "symbol_cooldown_state.json",
            }.issubset({path.name for path in current_dir.iterdir()}))
            self.assertFalse((private_root / "runs_private" / "market_regime_state.json").exists())

    def test_one_current_producer_carrier_feeds_bridge_then_shadow_then_maturity(self) -> None:
        """The same six-key producer artifact feeds both runtime consumers and the existing H20 reader."""
        _write_json(self.paths["overextension"], _overextension_for_current_aapl())
        packet = json.loads(self.paths["packet"].read_text(encoding="utf-8"))
        packet["paths"].update({
            "overextension_projection_path": _rel(self.paths["overextension"]),
            "overextension_candidate_artifact_path": _rel(self.paths["candidate"]),
        })
        _write_json(self.paths["packet"], packet)

        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", _provider_health())
            template = _no_build_template(private_root / "batch4_template.json")
            context_out = private_root / "context_packet.json"
            bridge = e2e.run_e2e(
                source_packet_path=self.paths["packet"],
                batch4_template_path=template,
                account_state_path=account,
                provider_health_path=health,
                private_root=private_root,
                now_et=datetime(2026, 6, 15, 9, 0, 0),
                context_components_path=self.paths["components"],
                context_packet_path=context_out,
                bootstrap_lifecycle=True,
                generated_at="2026-06-15T13:01:00Z",
            )
            components = json.loads(self.paths["components"].read_text(encoding="utf-8"))
            self.assertEqual(
                set(components),
                set(e2e.source_packet_runner.CONTEXT_COMPONENT_SHAPES["cut4"]),
            )
            self.assertTrue(bridge["batch4_run"]["emitted"])

            ohlcv_path = private_root / "ohlcv_20260615.json"
            _write_json(
                ohlcv_path,
                _forward_ohlcv_packet(
                    decision_date=_DECISION_DATE,
                    price_basis_date="20260612",
                    start_date="2026-06-08",
                    points=5,
                ),
            )
            vix_path = _write_json(private_root / "vix_20260615.json", {
                "vix_regime": "进攻", "vix_regime_is_unknown": False,
            })
            shadow_root = private_root / "shadow_compare_private"
            shadow_root.mkdir()
            ctx = SimpleNamespace(
                now_et=datetime(2026, 6, 15, 9, 0, 0),
                data_context_path=self.paths["data_context"],
                context_components_path=self.paths["components"],
                decision_date=_DECISION_DATE,
                price_basis_date="20260612",
                generated_at="2026-06-15T13:01:00Z",
                forward_shadow_selection_private_path=shadow_root / "forward_policy_selection_20260615.json",
                forward_policy_summary_path=shadow_root / "forward_policy_summary_20260615.json",
                forward_policy_source_capture_private_path=(
                    shadow_root / "forward_policy_source_capture_20260615.json"
                ),
                ohlcv_series_packet_path=ohlcv_path,
                batch4_template_path=template,
                vix_regime_summary_path=vix_path,
            )
            shadow = capstone_stages.run_forward_policy_shadow(ctx)
            self.assertEqual(shadow["summary"]["selected_counts"]["balanced"], 1)
            self.assertTrue(ctx.forward_policy_source_capture_private_path.is_file())

            maturity_ohlcv = _write_json(
                private_root / "ohlcv_20260713.json",
                _forward_ohlcv_packet(
                    decision_date="20260713",
                    price_basis_date="20260710",
                    start_date="2026-06-15",
                    points=26,
                ),
            )
            maturity_ctx = SimpleNamespace(
                forward_policy_comparison_ledger_path=shadow_root / "forward_policy_comparison_ledger.json",
                ohlcv_series_packet_path=maturity_ohlcv,
                decision_date="20260713",
            )
            maturity = capstone_stages.run_forward_policy_maturity(maturity_ctx)
            self.assertEqual(maturity["source_captures_processed"], 1)
            self.assertEqual(maturity["whole_week_no_count"], 1)
            self.assertTrue((shadow_root / "forward_policy_outcome_20260615.json").is_file())

    def test_bridge_keeps_exact_legacy_a1_and_cut4_carriers_readable(self) -> None:
        base = {
            "data_context": {
                "universe": [],
                "selection_inputs": {"theme_opportunity_state": "no_strong_theme"},
            },
            "per_ticker_analysis": {},
            "run_provenance": {"as_of": _DECISION_DATE, "price_basis_date": "20260612"},
        }
        variants = {
            "legacy": base,
            "a1": {**base, "score_composition": {}, "overextension_by_ticker": None},
            "cut4": {**base, "score_composition": {}, "overextension_by_ticker": None, "result_linkage_sources": {}},
        }
        source_summary = {
            "packet_ref": "historical-fixture",
            "data_context": {"selection_input_count": 0},
            "scope": {"context_components_written": True},
        }
        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", _provider_health())
            template = _no_build_template(private_root / "batch4_template.json")
            for shape, components in variants.items():
                with self.subTest(shape=shape):
                    _write_json(self.paths["components"], components)
                    with mock.patch.object(e2e, "_safe_source_packet_run", return_value=source_summary), mock.patch.object(
                        e2e, "_safe_batch4_run", return_value={"emitted": False, "decision_date": _DECISION_DATE, "row_count": 0}
                    ):
                        result = e2e.run_e2e(
                            source_packet_path=self.paths["packet"],
                            batch4_template_path=template,
                            account_state_path=account,
                            provider_health_path=health,
                            private_root=private_root,
                            now_et=datetime(2026, 6, 15, 9, 0, 0),
                            context_components_path=self.paths["components"],
                            context_packet_path=private_root / f"{shape}_context_packet.json",
                            generated_at="2026-06-15T13:01:00Z",
                        )
                    self.assertEqual(result["scope"]["status"], "batch5_source_packet_to_batch4_outputs_completed")

    def test_multigap_source_facts_survive_sorted_context_packet_and_emit(self) -> None:
        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            # Keep this a producer-backed source packet, but use the existing theme
            # projection seam's explicit missing-source disposition so the real Cut4
            # path emits at least two order-sensitive gaps (theme + price).
            theme_projection = _constant_projection(
                "theme_block_by_ticker",
                ("AAPL",),
                "neutral_missing_theme_and_industry_base",
                score=50.0,
                candidate_path=self.paths["candidate"],
                component="theme",
            )
            theme_projection["theme_block_by_ticker"] = {}
            theme_projection["neutral_fill_tickers"] = ["AAPL"]
            theme_projection["scored_count"] = 0
            theme_projection["source_binding"] = build_projection_binding(
                component="theme",
                producer_id="us_short_batch5_full_candidate_projection_inputs",
                generated_at="2026-06-13T10:00:00+00:00",
                expected_decision_date=_DECISION_DATE,
                candidate_price_basis_date="20260612",
                source_as_of="2026-06-12",
                target_tickers=["AAPL"],
                projection=theme_projection,
                source_artifact_paths={
                    "candidate_artifact": self.paths["candidate"],
                    "source_theme_projection": self.paths["candidate"],
                },
            )
            _write_json(self.paths["theme"], theme_projection)
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", _provider_health())
            template = _no_build_template(private_root / "batch4_template.json")
            context_out = private_root / "context_packet.json"

            summary = e2e.run_e2e(
                source_packet_path=self.paths["packet"],
                batch4_template_path=template,
                account_state_path=account,
                provider_health_path=health,
                private_root=private_root,
                now_et=datetime(2026, 6, 15, 9, 0, 0),
                context_components_path=self.paths["components"],
                context_packet_path=context_out,
                bootstrap_lifecycle=True,
                generated_at="2026-06-15T13:01:00Z",
            )

            self.assertEqual(summary["scope"]["status"], "batch5_source_packet_to_batch4_outputs_completed")
            self.assertTrue(summary["batch4_run"]["emitted"])
            self.assertTrue(context_out.is_file())
            raw_context = context_out.read_text(encoding="utf-8")
            context_packet = json.loads(raw_context)
            self.assertEqual(
                raw_context,
                json.dumps(context_packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
            row = context_packet["per_ticker_analysis"]["AAPL"]
            validate_result_source_fact(
                row["source_result_facts"],
                ticker="AAPL",
                row_source=row["row_source"],
                as_of=_DECISION_DATE,
                price_basis_date=row["source_result_facts"]["price_basis_date"],
            )
            coverage = row["source_result_facts"]["coverage"]
            checks = coverage["data_checks"]
            expected_gaps = [
                f"{category}:{checks[category]}"
                for category in ("analyst", "sec_parse", "event", "momentum", "theme", "catalyst", "price")
                if checks[category] != "ok"
            ]
            self.assertGreaterEqual(len(expected_gaps), 2)
            self.assertEqual(row["coverage_gap_tags"], expected_gaps)

            weekly_report = private_root / "weekly_private" / _DECISION_DATE / "weekly_report.md"
            action_table = private_root / "weekly_private" / _DECISION_DATE / "action_table.csv"
            machine_path = private_root / "runs_private" / _DECISION_DATE / "machine_record.json"
            self.assertTrue(weekly_report.is_file())
            self.assertTrue(action_table.is_file())
            self.assertTrue(machine_path.is_file())
            machine_row = json.loads(machine_path.read_text(encoding="utf-8"))["rows"][0]
            for key in ("coverage_status", "coverage_gap_tags", "data_quality_tags"):
                self.assertEqual(machine_row[key], row[key], key)

    def test_canonical_private_and_official_roots_are_carriers_not_leaf_outputs(self) -> None:
        """The canonical state root is a namespace; only its private child leaves need the guard."""
        canonical_root = e2e.STATE_US_SHORT_DIR.resolve()
        with tempfile.TemporaryDirectory() as input_dir:
            inputs = Path(input_dir)
            account = _write_json(inputs / "account_state.json", _empty_account())
            health = _write_json(inputs / "provider_health.json", _provider_health())
            template = _no_build_template(inputs / "batch4_template.json")
            context_out = self.state_dir / f"{self.slug}_carrier_context_packet.json"
            final_writer_calls: list[Path] = []

            def stub_final_batch4(packet_path: Path, **_kwargs):
                final_writer_calls.append(packet_path)
                return {"emitted": True, "decision_date": _DECISION_DATE, "row_count": 1}

            with mock.patch.object(e2e, "_safe_batch4_run", side_effect=stub_final_batch4):
                summary = e2e.run_e2e(
                    source_packet_path=self.paths["packet"],
                    batch4_template_path=template,
                    account_state_path=account,
                    provider_health_path=health,
                    private_root=canonical_root,
                    official_output_root=canonical_root,
                    now_et=datetime(2026, 6, 15, 9, 0, 0),
                    context_components_path=self.paths["components"],
                    context_packet_path=context_out,
                    bootstrap_lifecycle=True,
                    generated_at="2026-06-15T13:01:00Z",
                )

        self.assertEqual(summary["scope"]["status"], "batch5_source_packet_to_batch4_outputs_completed")
        self.assertEqual(summary["batch4_run"]["emitted"], True)
        self.assertEqual(final_writer_calls, [context_out.resolve()])

    def test_local_ohlcv_packet_is_the_only_executable_price_input(self) -> None:
        points = [
            {"date": f"2026-05-{idx:02d}", "high": 101.0 + idx, "low": 99.0 + idx, "close": 100.0 + idx}
            for idx in range(1, 15)
        ] + [{"date": "2026-06-12", "high": 116.0, "low": 114.0, "close": 115.0}]
        _write_json(self.paths["ohlcv"], {
            "schema_name": "us_short_batch5_full_universe_ohlcv_series_packet", "schema_version": "1.0.0",
            "generated_at": "2026-06-15T13:00:00Z",
            "scope": {
                "market": "US", "lane": "us_short", "batch": "batch5_provider_live",
                "packet_status": "full_universe_per_ticker_ohlcv_series_ready_for_local_overextension_projection",
                "full_market_reconstruction": True, "network_access_performed_by_packet_producer": False,
                "provider_calls_performed_by_packet_producer": False, "raw_payload_refs_gitignored": True,
                "datahub_consumption_allowed": False, "production_storage_allowed": False,
                "ship_gate_evidence_claimed": False, "broker_or_order_automation_allowed": False,
                "a_share_crossing_allowed": False,
            },
            "decision_clock": {
                "expected_decision_date": _DECISION_DATE, "candidate_price_basis_date": "20260612",
                "price_basis_date": "2026-06-12", "source_as_of": "2026-06-12",
            },
            "series_contract": {"session": "RTH", "adjustment_mode": "adjusted", "as_of": "2026-06-12",
                                "grouped_session_count": 15},
            "provenance": {"provider_id": "fmp", "endpoint_or_family": "historical_price_full",
                           "source_as_of": "2026-06-12", "observed_at": "2026-06-15T13:00:00Z",
                           "coverage_status": "full", "parser_status": "ok"},
            "series_by_ticker": {"AAPL": {"as_of": "2026-06-12", "session": "RTH",
                                             "adjustment_mode": "adjusted", "points": points}},
        })
        packet = json.loads(self.paths["packet"].read_text(encoding="utf-8"))
        packet["paths"]["ohlcv_series_packet_path"] = _rel(self.paths["ohlcv"])
        packet["source_artifact_sha256"]["ohlcv_series_packet_path"] = hashlib.sha256(
            self.paths["ohlcv"].read_bytes()
        ).hexdigest()
        _write_json(self.paths["packet"], packet)
        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", _provider_health())
            template = _no_build_template(private_root / "batch4_template.json")
            context_out = private_root / "context_packet.json"
            e2e.run_e2e(
                source_packet_path=self.paths["packet"], batch4_template_path=template,
                account_state_path=account, provider_health_path=health, private_root=private_root,
                now_et=datetime(2026, 6, 15, 9, 0, 0), context_components_path=self.paths["components"],
                context_packet_path=context_out, bootstrap_lifecycle=True, generated_at="2026-06-15T13:01:00Z",
            )
            row = json.loads(context_out.read_text(encoding="utf-8"))["per_ticker_analysis"]["AAPL"]
            price_source = row["source_result_facts"]["price"]
            self.assertEqual(price_source["status"], "ohlcv_ready")
            self.assertEqual(price_source["observed_at"], "2026-06-15T13:00:00Z")
            self.assertEqual(price_source["session"], "RTH")
            self.assertEqual(price_source["adjustment_mode"], "adjusted")
            self.assertEqual(len(row["price_input"]["bars"]), 15)
            expected_bars = [
                {"high": point["high"], "low": point["low"], "close": point["close"]}
                for point in points
            ]
            self.assertEqual(price_source["input"]["bars"], expected_bars)
            self.assertEqual(row["price_input"], price_source["input"])

    def test_default_legacy_e2e_rejects_full_candidate_profile_without_explicit_contract(self) -> None:
        targets = ("AAPL",)
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
        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", _provider_health())
            template = _no_build_template(private_root / "batch4_template.json")
            with self.assertRaisesRegex(e2e.Batch5ToBatch4E2EError, "source packet runner failed"):
                e2e.run_e2e(
                    source_packet_path=self.paths["packet"],
                    batch4_template_path=template,
                    account_state_path=account,
                    provider_health_path=health,
                    private_root=private_root,
                    now_et=datetime(2026, 6, 15, 9, 0, 0),
                    context_components_path=self.paths["components"],
                    bootstrap_lifecycle=True,
                )
            self.assertFalse((private_root / "weekly_private").exists())
            self.assertFalse((private_root / "runs_private").exists())

    def test_provider_health_is_required_before_any_batch4_output(self) -> None:
        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())

            with self.assertRaises(e2e.Batch5ToBatch4E2EError):
                e2e.run_e2e(
                    source_packet_path=self.paths["packet"],
                    batch4_template_path=TEMPLATE,
                    account_state_path=account,
                    provider_health_path=private_root / "missing_provider_health.json",
                    private_root=private_root,
                    now_et=datetime(2026, 6, 15, 9, 0, 0),
                    context_components_path=self.paths["components"],
                    bootstrap_lifecycle=True,
                )

            self.assertFalse((private_root / "weekly_private").exists())
            self.assertFalse((private_root / "runs_private").exists())
            self.assertFalse(self.paths["components"].exists())

    def test_cli_subprocess_writes_private_outputs_without_stdout_ticker_leak(self) -> None:
        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", _provider_health())
            template = _no_build_template(private_root / "batch4_template.json")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "runners" / "us_short_batch5_to_batch4_weekend_e2e.py"),
                    "--source-packet",
                    str(self.paths["packet"]),
                    "--batch4-template",
                    str(template),
                    "--account",
                    str(account),
                    "--provider-health",
                    str(health),
                    "--private-root",
                    str(private_root),
                    "--now-et",
                    "2026-06-15T09:00:00",
                    "--context-components-out",
                    str(self.paths["components"]),
                    "--bootstrap-lifecycle",
                    "--generated-at",
                    "2026-06-15T13:01:00Z",
                ],
                cwd=ROOT,
                text=True,
                encoding="utf-8",          # GOV-R6: both ends pinned, never the ambient locale
                errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["scope"]["status"], "batch5_source_packet_to_batch4_outputs_completed")
            self.assertTrue((private_root / "weekly_private" / _DECISION_DATE / "weekly_report.md").exists())
            self.assertTrue((private_root / "weekly_private" / _DECISION_DATE / "action_table.csv").exists())
            self.assertTrue(self.paths["components"].exists())
            emitted_text = result.stdout + result.stderr
            self.assertNotIn("AAPL", emitted_text)
            self.assertNotIn("https://", emitted_text)
            self.assertNotIn("api_key", emitted_text.lower())

    def test_cli_batch4_failure_leaves_no_generated_residue_or_ticker_leak(self) -> None:
        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", _provider_health())
            bad_template_payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
            bad_template_payload["market_axis_regimes"] = "bad"
            bad_template = _write_json(private_root / "bad_template.json", bad_template_payload)
            context_out = private_root / "context_packet.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "runners" / "us_short_batch5_to_batch4_weekend_e2e.py"),
                    "--source-packet",
                    str(self.paths["packet"]),
                    "--batch4-template",
                    str(bad_template),
                    "--account",
                    str(account),
                    "--provider-health",
                    str(health),
                    "--private-root",
                    str(private_root),
                    "--now-et",
                    "2026-06-15T09:00:00",
                    "--context-components-out",
                    str(self.paths["components"]),
                    "--context-out",
                    str(context_out),
                    "--bootstrap-lifecycle",
                    "--generated-at",
                    "2026-06-15T13:01:00Z",
                ],
                cwd=ROOT,
                text=True,
                encoding="utf-8",          # GOV-R6: both ends pinned, never the ambient locale
                errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            emitted_text = result.stdout + result.stderr
            self.assertNotIn("AAPL", emitted_text)
            self.assertNotIn("https://", emitted_text)
            self.assertNotIn("api_key", emitted_text.lower())
            self.assertFalse(self.paths["data_context"].exists())
            self.assertFalse(self.paths["components"].exists())
            self.assertFalse(context_out.exists())
            self.assertFalse(context_out.with_suffix(context_out.suffix + ".tmp").exists())
            self.assertFalse((private_root / "weekly_private").exists())
            self.assertFalse((private_root / "runs_private").exists())
            self.assertFalse((private_root / "lifecycle").exists())


if __name__ == "__main__":
    unittest.main()
