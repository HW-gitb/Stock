from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_short_batch5_full_candidate_live_source_packet as funnel  # noqa: E402
from runners import us_short_batch5_full_candidate_pass2_preflight as preflight_runner  # noqa: E402
from runners import us_short_batch5_to_batch4_weekend_e2e as e2e  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _OFFERING_OBSERVED_AT,
    _candidate_artifact,
    _constant_projection,
)
from tests.provider.test_us_short_batch5_full_candidate_live_source_packet import (  # noqa: E402
    FullCandidateFakeClient,
)
from tests.provider.test_us_short_batch5_to_batch4_e2e import _empty_account, _no_build_template  # noqa: E402


STATE_DIR = ROOT / "state" / "us_short"
SAMPLE_DIR = ROOT / "provider_samples" / "us_short_batch5_full_candidate_live_source_packet_20260706"
PREFLIGHT_SAMPLE_DIR = ROOT / "provider_samples" / "us_short_batch5_full_candidate_pass2_preflight_20260706"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class CapstoneOfflineE2ETest(unittest.TestCase):
    """Capstone offline E2E: the REAL funnel runner (fake client, no network) produces a momentum-narrowed
    Pass2 source packet, which the REAL batch5->batch4 bridge turns into a private PAPER weekly_report.md /
    action_table.csv. Neither the funnel test nor the bridge test ran the other before — this proves the funnel
    output actually composes with the bridge into an honest offline paper report."""

    def setUp(self) -> None:
        self.slug = f"capstone_e2e_{os.getpid()}_{abs(hash(self._testMethodName)) % 100000}"
        self.raw_root = SAMPLE_DIR / self.slug / "raw"
        self.paths = {
            "candidate": STATE_DIR / f"{self.slug}_candidate.json",
            "momentum": STATE_DIR / f"{self.slug}_momentum.json",
            "theme": STATE_DIR / f"{self.slug}_theme.json",
            "preflight": PREFLIGHT_SAMPLE_DIR / self.slug / "preflight.json",
            "summary": SAMPLE_DIR / self.slug / "summary.json",
            "prefix": STATE_DIR / self.slug,
            "output": STATE_DIR / f"{self.slug}_data_context.json",
            "components": STATE_DIR / f"{self.slug}_context_components.json",
        }
        self._cleanup_paths()
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "MSFT", "JPM")))
        _write_json(
            self.paths["momentum"],
            _constant_projection("momentum_by_ticker", ("AAPL", "MSFT", "JPM"), "scored", score=50.0),
        )
        _write_json(
            self.paths["theme"],
            _constant_projection("theme_block_by_ticker", ("AAPL", "MSFT", "JPM"), "scored_theme_base", score=50.0),
        )
        preflight_runner.run_preflight(
            candidate_artifact_path=self.paths["candidate"],
            expected_decision_date=_DECISION_DATE,
            momentum_projection_path=self.paths["momentum"],
            theme_projection_path=self.paths["theme"],
            summary_path=self.paths["preflight"],
            confirm_user_authorization=True,
            generated_at="2026-07-06T12:00:00+00:00",
        )

    def _source_artifact_paths(self) -> list[Path]:
        prefix = self.paths["prefix"]
        return [
            prefix.with_name(prefix.name + suffix)
            for suffix in (
                "_candidate_subset.json",
                "_offering_audit_source.json",
                "_analyst_grade_actions.json",
                "_massive_news_events.json",
                "_corporate_action_capture.json",
                "_momentum_projection.json",
                "_theme_projection.json",
                "_source_packet.json",
            )
        ]

    def _cleanup_paths(self) -> None:
        state_files = [
            self.paths["candidate"],
            self.paths["momentum"],
            self.paths["theme"],
            self.paths["output"],
            self.paths["components"],
        ] + self._source_artifact_paths()
        for path in state_files:
            if path.is_file():
                path.unlink()
        for root in (SAMPLE_DIR / self.slug, PREFLIGHT_SAMPLE_DIR / self.slug):
            if root.exists():
                for item in sorted(root.rglob("*"), reverse=True):
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        item.rmdir()
                root.rmdir()

    def tearDown(self) -> None:
        self._cleanup_paths()

    def _env(self):
        return mock.patch.dict(
            funnel.sample_validation.os.environ,
            {
                "FMP_API_KEY": "UNIT_TEST_FMP_SECRET",
                "SEC_USER_AGENT": "UnitTest/0.1 contact:test@example.com",
                "MASSIVE_API_KEY": "UNIT_TEST_MASSIVE_SECRET",
            },
            clear=False,
        )

    def test_funnel_output_flows_through_bridge_to_private_paper_weekly_report(self) -> None:
        client = FullCandidateFakeClient()
        with self._env(), mock.patch.object(
            funnel.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            funnel_summary = funnel.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=16,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=False,
                generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )

        source_packet_path = ROOT / funnel_summary["source_packet"]["path"]
        self.assertTrue(source_packet_path.exists())
        self.assertEqual(funnel_summary["pass2_target_universe"]["target_count"], 3)

        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", {"fmp": "ok", "sec_edgar": "ok"})
            template = _no_build_template(private_root / "batch4_template.json")

            summary = e2e.run_e2e(
                source_packet_path=source_packet_path,
                batch4_template_path=template,
                account_state_path=account,
                provider_health_path=health,
                private_root=private_root,
                now_et=datetime(2026, 6, 15, 9, 0, 0),
                context_components_path=self.paths["components"],
                bootstrap_lifecycle=True,
                generated_at="2026-06-15T13:01:00Z",
            )

            self.assertEqual(summary["scope"]["status"], "batch5_source_packet_to_batch4_outputs_completed")
            self.assertFalse(summary["scope"]["network_access_required"])
            self.assertFalse(summary["scope"]["provider_calls_performed"])
            self.assertTrue(summary["batch4_run"]["emitted"])
            self.assertEqual(summary["batch4_run"]["decision_date"], _DECISION_DATE)

            report_path = private_root / "weekly_private" / _DECISION_DATE / "weekly_report.md"
            action_path = private_root / "weekly_private" / _DECISION_DATE / "action_table.csv"
            self.assertTrue(report_path.exists())
            self.assertTrue(action_path.exists())
            self.assertTrue((private_root / "runs_private" / _DECISION_DATE / "machine_record.json").exists())

            # Paper / offline honesty: the report carries the offline-run sentinel, never an operational-clean claim.
            report_text = report_path.read_text(encoding="utf-8")
            self.assertIn("离线", report_text)

            # No secret / ticker leak in the returned summary.
            blob = json.dumps(summary, ensure_ascii=False)
            self.assertNotIn("UNIT_TEST_FMP_SECRET", blob)
            self.assertNotIn("UNIT_TEST_MASSIVE_SECRET", blob)
            self.assertNotIn("AAPL", blob)

    def test_research_live_run_emits_real_data_report_not_fixture(self) -> None:
        # option a + R-USSHORT-REVIEWQ-CAT1 Required A: run_mode="research_live" is CAPSTONE-INTERNAL — it emits the
        # honest real-data research report ONLY when handed a source-bound capstone execution receipt. The report carries the research
        # sentinel (研究运行 / 真实 provider 数据), NOT the offline_test fixture lie, and the machine record carries the
        # research run_origin. (The negative sibling below proves the SAME fixture packet WITHOUT the capability
        # cannot get the real-provider banner.)
        from engine.us_short_run_origin import RESEARCH_LIVE_RUN_ORIGIN, _issue_capstone_research_live_receipt
        client = FullCandidateFakeClient()
        with self._env(), mock.patch.object(
            funnel.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            funnel_summary = funnel.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=16,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=False,
                generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )
        source_packet_path = ROOT / funnel_summary["source_packet"]["path"]
        source_digest = hashlib.sha256(source_packet_path.read_bytes()).hexdigest()
        source_manifest = e2e.source_packet_runner.source_packet_input_manifest(source_packet_path)
        evidence_digest = "2" * 64
        provider_summary_digests = tuple(
            (stage, hashlib.sha256(json.dumps({"stage": stage}, sort_keys=True,
                                               separators=(",", ":")).encode("utf-8")).hexdigest())
            for stage in ("universe_fetch", "momentum_fetch", "sic_fetch", "pass2_fetch")
        )
        receipt = _issue_capstone_research_live_receipt(
            run_id=hashlib.sha256(
                f"{_DECISION_DATE}|2026-06-15T13:01:00Z|{source_packet_path.resolve()}|{source_digest}|{evidence_digest}".encode("utf-8")
            ).hexdigest(),
            decision_date=_DECISION_DATE,
            generated_at="2026-06-15T13:01:00Z",
            completed_stages=("universe_fetch", "momentum_fetch", "momentum_producer", "sic_fetch", "theme_producer",
                              "projection_inputs", "pass2_preflight", "pass2_fetch"),
            source_packet_path=source_packet_path.resolve(),
            source_packet_sha256=source_digest,
            source_artifact_manifest=source_manifest,
            provider_call_counts=(("universe_fetch", 1), ("momentum_fetch", 1), ("sic_fetch", 1), ("pass2_fetch", 16)),
            provider_summary_digests=provider_summary_digests,
            provider_health_facts=(("fmp", "ok"), ("sec_edgar", "ok")),
            provider_evidence_sha256=evidence_digest,
        )

        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", {"fmp": "ok", "sec_edgar": "ok"})
            mismatched_health = _write_json(
                private_root / "provider_health_mismatch.json", {"fmp": "down", "sec_edgar": "down"}
            )
            template = _no_build_template(private_root / "batch4_template.json")

            with self.assertRaises(e2e.Batch5ToBatch4E2EError):
                e2e.run_e2e(
                    source_packet_path=source_packet_path,
                    batch4_template_path=template,
                    account_state_path=account,
                    provider_health_path=mismatched_health,
                    private_root=private_root,
                    now_et=datetime(2026, 6, 15, 9, 0, 0),
                    context_components_path=self.paths["components"],
                    run_mode="research_live",
                    _research_live_capability=receipt,
                    bootstrap_lifecycle=True,
                    generated_at="2026-06-15T13:01:00Z",
                )
            self.assertFalse((private_root / "weekly_private").exists())
            self.assertFalse((private_root / "runs_private").exists())

            summary = e2e.run_e2e(
                source_packet_path=source_packet_path,
                batch4_template_path=template,
                account_state_path=account,
                provider_health_path=health,
                private_root=private_root,
                now_et=datetime(2026, 6, 15, 9, 0, 0),
                context_components_path=self.paths["components"],
                run_mode="research_live",
                _research_live_capability=receipt,
                bootstrap_lifecycle=True,
                generated_at="2026-06-15T13:01:00Z",
            )

            self.assertTrue(summary["batch4_run"]["emitted"])   # emits (did NOT crash as run_mode="live" would)
            report_path = private_root / "weekly_private" / _DECISION_DATE / "weekly_report.md"
            self.assertTrue(report_path.exists())
            report_text = report_path.read_text(encoding="utf-8")
            self.assertIn("研究运行", report_text)                 # honest real-data research provenance
            self.assertIn("真实 provider", report_text)
            self.assertNotIn("调用方注入 fixture", report_text)     # NOT the offline_test fixture lie
            machine_record = json.loads(
                (private_root / "runs_private" / _DECISION_DATE / "machine_record.json").read_text(encoding="utf-8"))
            self.assertEqual(machine_record["run_origin"], RESEARCH_LIVE_RUN_ORIGIN)
            blob = json.dumps(summary, ensure_ascii=False)
            self.assertNotIn("UNIT_TEST_FMP_SECRET", blob)
            self.assertNotIn("UNIT_TEST_MASSIVE_SECRET", blob)

    def test_research_live_receipt_rejects_changed_referenced_source_artifact(self) -> None:
        from engine.us_short_run_origin import _issue_capstone_research_live_receipt

        client = FullCandidateFakeClient()
        with self._env(), mock.patch.object(
            funnel.sample_validation, "_read_windows_environment_value", return_value=None
        ):
            funnel_summary = funnel.run_full_candidate_live_source_packet(
                preflight_summary_path=self.paths["preflight"],
                expected_total_call_budget=16,
                output_data_context_path=self.paths["output"],
                context_components_output_path=self.paths["components"],
                source_artifact_prefix=self.paths["prefix"],
                summary_path=self.paths["summary"],
                raw_root=self.raw_root,
                client=client,
                confirm_user_authorization=True,
                run_data_context=False,
                generated_at="2026-07-06T12:00:00+00:00",
                observed_at=_OFFERING_OBSERVED_AT,
                sec_sleep_seconds=0,
            )
        source_packet_path = ROOT / funnel_summary["source_packet"]["path"]
        source_digest = hashlib.sha256(source_packet_path.read_bytes()).hexdigest()
        source_manifest = e2e.source_packet_runner.source_packet_input_manifest(source_packet_path)
        evidence_digest = "2" * 64
        provider_summary_digests = tuple(
            (stage, hashlib.sha256(json.dumps({"stage": stage}, sort_keys=True,
                                               separators=(",", ":")).encode("utf-8")).hexdigest())
            for stage in ("universe_fetch", "momentum_fetch", "sic_fetch", "pass2_fetch")
        )
        receipt = _issue_capstone_research_live_receipt(
            run_id=hashlib.sha256(b"source-artifact-tamper-test").hexdigest(),
            decision_date=_DECISION_DATE,
            generated_at="2026-06-15T13:01:00Z",
            completed_stages=("universe_fetch", "momentum_fetch", "momentum_producer", "sic_fetch", "theme_producer",
                              "projection_inputs", "pass2_preflight", "pass2_fetch"),
            source_packet_path=source_packet_path.resolve(),
            source_packet_sha256=source_digest,
            source_artifact_manifest=source_manifest,
            provider_call_counts=(("universe_fetch", 1), ("momentum_fetch", 1), ("sic_fetch", 1), ("pass2_fetch", 16)),
            provider_summary_digests=provider_summary_digests,
            provider_health_facts=(("fmp", "ok"), ("sec_edgar", "ok")),
            provider_evidence_sha256=evidence_digest,
        )
        packet = json.loads(source_packet_path.read_text(encoding="utf-8"))
        changed_path = ROOT / packet["paths"]["candidate_artifact_path"]
        changed_path.write_text(changed_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", {"fmp": "ok", "sec_edgar": "ok"})
            template = _no_build_template(private_root / "batch4_template.json")
            with self.assertRaises(e2e.Batch5ToBatch4E2EError):
                e2e.run_e2e(
                    source_packet_path=source_packet_path,
                    batch4_template_path=template,
                    account_state_path=account,
                    provider_health_path=health,
                    private_root=private_root,
                    now_et=datetime(2026, 6, 15, 9, 0, 0),
                    context_components_path=self.paths["components"],
                    run_mode="research_live",
                    _research_live_capability=receipt,
                    bootstrap_lifecycle=True,
                    generated_at="2026-06-15T13:01:00Z",
                )
            self.assertFalse((private_root / "weekly_private").exists())
            self.assertFalse((private_root / "runs_private").exists())

    def test_research_live_standalone_fixture_cannot_get_real_provider_banner(self) -> None:
        # R-USSHORT-REVIEWQ-CAT1 Required A (the exact reviewer probe): a generic batch5->batch4 caller feeding a
        # local/fixture source packet must NOT be able to stamp the "真实 provider 数据" research banner. Neither an
        # ABSENT capability, nor a FORGED one (True / a look-alike object), can obtain research_live — run_e2e fails
        # closed BEFORE any report/action/record write. (The capstone receipt is source-bound.)
        from engine.us_short_run_origin import _issue_capstone_research_live_receipt

        with tempfile.TemporaryDirectory() as private_dir:
            private_root = Path(private_dir)
            account = _write_json(private_root / "account_state.json", _empty_account())
            health = _write_json(private_root / "provider_health.json", {"fmp": "ok", "sec_edgar": "ok"})
            template = _no_build_template(private_root / "batch4_template.json")
            fixture_packet = _write_json(private_root / "fixture_source_packet.json", {"note": "local fixture"})

            for forged in (None, True, object(), "yes"):   # absent + forged attestations all fail closed
                kwargs = {} if forged is None else {"_research_live_capability": forged}
                with self.assertRaises(e2e.Batch5ToBatch4E2EError):
                    e2e.run_e2e(
                        source_packet_path=fixture_packet,
                        batch4_template_path=template,
                        account_state_path=account,
                        provider_health_path=health,
                        private_root=private_root,
                        now_et=datetime(2026, 6, 15, 9, 0, 0),
                        run_mode="research_live",   # capstone-internal mode refused without a valid source-bound receipt
                        bootstrap_lifecycle=True,
                        generated_at="2026-06-15T13:01:00Z",
                        **kwargs,
                    )
            fixture_digest = hashlib.sha256(fixture_packet.read_bytes()).hexdigest()
            provider_summary_digests = tuple(
                (stage, hashlib.sha256(json.dumps({"stage": stage}, sort_keys=True,
                                                   separators=(",", ":")).encode("utf-8")).hexdigest())
                for stage in ("universe_fetch", "momentum_fetch", "sic_fetch", "pass2_fetch")
            )
            valid_receipt = _issue_capstone_research_live_receipt(
                run_id=hashlib.sha256(b"missing-generated-at-test").hexdigest(),
                decision_date=_DECISION_DATE,
                generated_at="2026-06-15T13:01:00Z",
                completed_stages=("universe_fetch", "momentum_fetch", "momentum_producer", "sic_fetch",
                                  "theme_producer", "projection_inputs", "pass2_preflight", "pass2_fetch"),
                source_packet_path=fixture_packet.resolve(),
                source_packet_sha256=fixture_digest,
                source_artifact_manifest=(("fixture", str(fixture_packet.resolve()), fixture_digest),),
                provider_call_counts=(("universe_fetch", 1), ("momentum_fetch", 1),
                                      ("sic_fetch", 1), ("pass2_fetch", 1)),
                provider_summary_digests=provider_summary_digests,
                provider_health_facts=(("fmp", "ok"), ("sec_edgar", "ok")),
                provider_evidence_sha256="2" * 64,
            )
            with self.assertRaises(e2e.Batch5ToBatch4E2EError) as cm:
                e2e.run_e2e(
                    source_packet_path=fixture_packet,
                    batch4_template_path=template,
                    account_state_path=account,
                    provider_health_path=health,
                    private_root=private_root,
                    now_et=datetime(2026, 6, 15, 9, 0, 0),
                    run_mode="research_live",
                    _research_live_capability=valid_receipt,
                    bootstrap_lifecycle=True,
                )
            self.assertIn("generated_at", str(cm.exception))
            # fail-closed: the refused runs wrote NO official output (no real-provider banner anywhere).
            self.assertFalse((private_root / "weekly_private").exists())
            self.assertFalse((private_root / "runs_private").exists())


if __name__ == "__main__":
    unittest.main()
