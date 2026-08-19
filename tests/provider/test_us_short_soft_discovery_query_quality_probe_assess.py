from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from engine import us_short_llm_theme_discovery_plan_budget as plan_budget
from engine import us_short_llm_theme_discovery_query_plan as query_plan
from engine import us_short_soft_discovery_query_quality_probe_paths as probe_paths
from runners import us_short_llm_theme_discovery_build_parent_plan as parent_plan_builder
from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from runners import us_short_soft_discovery_query_quality_probe_assess as assess


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PACKET = REPO_ROOT / "docs" / "us_short_soft_discovery_query_quality_probe_packet_20260730.json"
NEW_SOURCE_PACKET = REPO_ROOT / "docs" / "us_short_soft_discovery_query_quality_probe_packet_20260815.json"
GENERATED_AT = "2026-08-01T20:00:00+00:00"

# These are producer contracts, not a subset check.  A legitimate producer-side top-level
# addition must make the seam red until the assessor either reads it or records an intentional
# ignore decision; silently accepting a third unread evidence field would recreate this risk.
PRODUCTION_DISCOVERY_KEYS = frozenset({
    "schema_name", "schema_version", "generated_at", "input_sha256", "decision_clock",
    "discovery_contract", "source_refs", "themes",
})
PRODUCTION_WEB_RECEIPT_KEYS = frozenset({
    "schema_name", "schema_version", "generated_at", "decision_clock", "fetch_contract",
    "queries", "plan_binding", "source_refs", "provider_response_refs", "discovery_artifact_sha256", "drop_ledger",
    "summary", "member_binding_ledger", "member_binding_summary",
})
PRODUCTION_X_RECEIPT_KEYS = frozenset({
    "schema_name", "schema_version", "generated_at", "decision_clock", "fetch_contract",
    "queries", "plan_binding", "source_refs", "provider_response_refs", "provider_annotation_urls",
    "discovery_artifact_sha256", "drop_ledger", "summary",
})
PRODUCTION_LEDGER_KEYS = frozenset({
    "schema_name", "schema_version", "budget_mode", "lane", "provider", "decision_date",
    "parent_plan_identity", "provider_envelope", "planned_provider_call_count",
    "reservation_attempt_count", "first_reserved_at", "last_reserved_at", "query_reservations",
    "dispatches", "dispatch_counts", "vendor_dispatch_counts", "recovery_events",
})
OFFLINE_INCONCLUSIVE_REASONS = frozenset({
    "execution_mode_not_live_authorized", "provider_calls_not_proven",
    "tavily_query_call_count_not_proven", "xai_query_call_count_not_proven",
})


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _discovery(lane: str) -> dict:
    prefix = "web" if lane == "web" else "x"
    source_ids = [f"{prefix}:{str(index) * 64}" for index in (1, 2, 3)]
    return {
        "schema_name": "us_short_llm_theme_discovery",
        "schema_version": "1.0.0",
        "generated_at": "2026-08-01T12:00:00+00:00",
        "decision_clock": {
            "expected_decision_date": "20260802",
            "cutoff_policy": "before_decision_open_et",
            "pit_enforced": True,
        },
        "discovery_contract": {
            "producer_kind": "llm_theme_discovery",
            "input_mode": "offline_local_input",
            "membership_status": "provisional_unvalidated",
            "market_confirmation_status": "not_run",
            "scoring_eligible": False,
            "top15_effect_enabled": False,
            "operation_advice_effect_enabled": False,
            "dynamic_seats_enabled": False,
            "theme_probe_enabled": False,
            "lifecycle_actions_enabled": False,
        },
        "source_refs": [
            {
                "source_id": source_id,
                "source_type": lane,
                "observed_at": f"2026-08-01T1{index}:00:00+00:00",
            }
            for index, source_id in enumerate(source_ids)
        ],
        "themes": [{
            "theme_id": f"{lane}_new_demand",
            "display_name": f"{lane} new demand",
            "summary": "A source-bound cross-industry pattern.",
            "status": "provisional_discovered",
            "observed_at": "2026-08-01T12:00:00+00:00",
            "source_ref_ids": source_ids,
            "members": [
                {
                    "ticker": ticker,
                    "membership_status": "provisional_unvalidated",
                    "source_ref_ids": [source_id],
                }
                for ticker, source_id in zip(("AAPL", "CEG", "VST"), source_ids)
            ],
            "cross_industry_validation_status": "not_run",
            "market_confirmation_status": "not_run",
        }],
    }


def _receipt(lane: str, discovery: dict, queries: list[str]) -> dict:
    source_rows = []
    for index, source in enumerate(discovery["source_refs"]):
        row = {
            "source_id": source["source_id"],
            "source_type": lane,
            "canonical_locator": f"https://example.com/{lane}/{index}",
            "observed_at": source["observed_at"],
            "fetched_at": "2026-08-01T12:00:00+00:00",
            "content_sha256": hashlib.sha256(f"{lane}-{index}".encode()).hexdigest(),
            "raw_receipt_ref": f"provider_samples/{lane}/{index}.json",
            "raw_receipt_gitignored": True,
        }
        if lane == "x":
            row["evidence_attestation"] = "provider_attested"
        source_rows.append(row)
    if lane == "web":
        contract = {
            "producer_kind": "tavily_deepseek_web_fetch",
            "execution_mode": "live_authorized",
            "network_access_performed": True,
            "provider_calls_performed": True,
            "network_call_count": 8,
            "provider_call_count": 8,
            "transport_response_counts": {"tavily": 4, "deepseek": 4},
            "regroup_chunk_counts": {
                "attempted": 4,
                "successful": 4,
                "failed": 0,
                "failed_indexes": [],
            },
            "scoring_eligible": False,
            "top15_effect_enabled": False,
            "operation_advice_effect_enabled": False,
            "dynamic_seats_enabled": False,
            "theme_probe_enabled": False,
            "lifecycle_actions_enabled": False,
            "regroup_model": {
                "requested_model": "deepseek-chat",
                "served_model": "deepseek-v4-flash",
                "system_fingerprints": [],
            },
        }
        summary = {
            "query_count": 4,
            "accepted_source_count": 3,
            "validated_theme_count": 1,
            "validated_member_count": 3,
            "dropped_result_count": 0,
            "prompt_source_count": 3,
        }
    else:
        contract = {
            "producer_kind": "grok_native_x_fetch",
            "execution_mode": "live_authorized",
            "network_access_performed": True,
            "provider_calls_performed": True,
            "network_call_count": 4,
            "provider_call_count": 4,
            "transport_response_counts": {"xai": 4},
            "scoring_eligible": False,
            "top15_effect_enabled": False,
            "operation_advice_effect_enabled": False,
            "dynamic_seats_enabled": False,
            "theme_probe_enabled": False,
            "lifecycle_actions_enabled": False,
            "grok_model": {
                "requested_model": "grok-4.3",
                "served_model": "grok-4.3",
                "system_fingerprints": [],
            },
        }
        summary = {
            "query_count": 4,
            "accepted_source_count": 3,
            "validated_theme_count": 1,
            "validated_member_count": 3,
            "dropped_result_count": 0,
        }
    return {
        "schema_name": f"us_short_llm_theme_discovery_fetch_{lane}",
        "schema_version": "1.0.0",
        "generated_at": "2026-08-01T13:00:00+00:00",
        "decision_clock": {
            "expected_decision_date": "20260802",
            "cutoff_policy": "before_decision_open_et",
            "pit_enforced": True,
        },
        "fetch_contract": contract,
        "queries": queries,
        "source_refs": source_rows,
        **({
            "provider_response_refs": [
                {
                    "provider": "xai",
                    "response_index": index,
                    "response_sha256": hashlib.sha256(
                        f"x-provider-response-{index}".encode("utf-8")
                    ).hexdigest(),
                    "fetched_at": f"2026-08-01T12:{30 + index * 5:02d}:00+00:00",
                    "raw_receipt_ref": f"provider_samples/x/provider_response_{index}.json",
                    "raw_receipt_gitignored": True,
                }
                for index in range(4)
            ],
            "provider_annotation_urls": [],
        } if lane == "x" else {}),
        "discovery_artifact_sha256": web._discovery_evidence_hash(discovery),
        "drop_ledger": [],
        "summary": summary,
    }


def _ledger(provider: str, query_ids: list[str], call_count: int) -> dict:
    if provider == "web":
        envelope = {
            "provider": "web",
            "stage1_max_dispatch_count": 4,
            "stage2_max_dispatch_count": 4,
            "retry_max_dispatch_count": 0,
            "max_dispatch_count": 8,
        }
        scopes = [
            (query_id, "stage1", "tavily") for query_id in query_ids
        ] + [
            (f"chunk:{index}", "stage2", "deepseek")
            for index in range(len(query_ids))
        ]
    else:
        envelope = {
            "provider": "xai",
            "stage1_max_dispatch_count": 4,
            "stage2_max_dispatch_count": 0,
            "retry_max_dispatch_count": 0,
            "max_dispatch_count": 4,
        }
        scopes = [(query_id, "stage1", "xai") for query_id in query_ids]
    reservations = [
        {
            "query_sha256": hashlib.sha256(scope.encode("utf-8")).hexdigest(),
            "stage": stage,
            "vendor": vendor,
            "query_count": 1,
            "planned_provider_call_count": 1,
            "attempt_count": 1,
            "last_status": "complete",
        }
        for scope, stage, vendor in scopes
    ]
    dispatches = [
        {
            "dispatch_id": index,
            "query_sha256": row["query_sha256"],
            "stage": row["stage"],
            "vendor": row["vendor"],
            "attempt": 1,
            "status": "complete",
            "started_at": "2026-08-01T11:01:00+00:00",
            "owner_pid": 1,
            "owner_run_id": "b" * 32,
            "owner_started_at": "2026-08-01T11:00:00+00:00",
            "owner_heartbeat_at": "2026-08-01T11:02:00+00:00",
            "finished_at": "2026-08-01T11:02:00+00:00",
        }
        for index, row in enumerate(reservations, start=1)
    ]
    stage1_count = len(query_ids)
    stage2_count = len(query_ids) if provider == "web" else 0
    return {
        "schema_name": "us_short_llm_theme_discovery_plan_budget",
        "schema_version": "1.0.0",
        "budget_mode": "parent_plan_envelope",
        "lane": "us_short",
        "provider": provider,
        "decision_date": "20260802",
        "parent_plan_identity": "a" * 64,
        "provider_envelope": envelope,
        "planned_provider_call_count": call_count,
        "reservation_attempt_count": 1,
        "first_reserved_at": "2026-08-01T11:00:00+00:00",
        "last_reserved_at": "2026-08-01T11:00:00+00:00",
        "query_reservations": reservations,
        "dispatches": dispatches,
        "dispatch_counts": {
            "stage1_dispatch_count": stage1_count,
            "stage2_dispatch_count": stage2_count,
            "retry_dispatch_count": 0,
            "dispatch_count": len(dispatches),
            "unknown_dispatch_count": 0,
        },
        "vendor_dispatch_counts": {
            "tavily": stage1_count if provider == "web" else 0,
            "deepseek": stage2_count,
            "xai": stage1_count if provider == "xai" else 0,
        },
        "recovery_events": [],
    }


class QueryQualityProbeAssessmentTest(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="us_short_query_quality_assess_")
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name).resolve()
        self.docs = self.root / "docs"
        self.state = self.root / "state" / "us_short"
        self.packet_path = self.docs / SOURCE_PACKET.name
        self.assessment_path = self.docs / "us_short_soft_discovery_query_quality_probe_assessment_20260802.json"
        packet = json.loads(SOURCE_PACKET.read_text(encoding="utf-8"))
        _write_json(self.packet_path, packet)
        self.queries = [row["text"] for row in packet["query_templates"]]
        # The paid gateway dispatches under `query_id or query_text`, so a plan-bound
        # ledger keys its rows on the id.  Fixtures must speak the producer's dialect.
        self.query_ids = [row["query_id"] for row in packet["query_templates"]]

        self.patches = [
            mock.patch.object(assess, "ROOT", self.root),
            mock.patch.object(assess, "DEFAULT_PACKET_PATH", self.packet_path),
            mock.patch.object(probe_paths, "ROOT", self.root),
            mock.patch.object(probe_paths, "DOCS_DIR", self.docs),
            mock.patch.object(web, "ROOT", self.root),
            mock.patch.object(web, "STATE_DIR", self.state),
            mock.patch.object(
                web,
                "DEFAULT_RAW_ROOT",
                self.root / "provider_samples" / "us_short_llm_theme_discovery_fetch_web",
            ),
            mock.patch.object(web, "_gitignored", return_value=True),
            mock.patch.object(xfetch, "ROOT", self.root),
            mock.patch.object(xfetch, "STATE_DIR", self.state),
            mock.patch.object(
                xfetch,
                "DEFAULT_RAW_ROOT",
                self.root / "provider_samples" / "us_short_llm_theme_discovery_fetch_x",
            ),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self._write_inputs()

    def _write_inputs(self):
        web_discovery = _discovery("web")
        x_discovery = _discovery("x")
        payloads = {
            web.default_discovery_path("20260802"): web_discovery,
            web.default_receipt_path("20260802"): _receipt("web", web_discovery, self.queries),
            xfetch.default_discovery_path("20260802"): x_discovery,
            xfetch.default_receipt_path("20260802"): _receipt("x", x_discovery, self.queries),
            self._plan_budget_path("web"):
                _ledger("web", self.query_ids, 8),
            self._plan_budget_path("xai"):
                _ledger("xai", self.query_ids, 4),
        }
        for path, payload in payloads.items():
            _write_json(path, payload)

    def test_historical_web_receipt_model_identity_remains_schema_valid(self):
        schema = json.loads(web.SCHEMA_PATH.read_text(encoding="utf-8"))
        model_rule = schema["properties"]["fetch_contract"]["properties"]["regroup_model"]["properties"]["requested_model"]
        self.assertEqual(set(model_rule["enum"]), {"deepseek-v4-pro", "deepseek-chat"})
        discovery = _discovery("web")
        web._validate_schema(_receipt("web", discovery, self.queries))

    def _packet_and_input_slot_paths(self) -> dict[str, Path]:
        return {
            "packet": self.packet_path,
            "web_discovery": web.default_discovery_path("20260802"),
            "web_receipt": web.default_receipt_path("20260802"),
            "x_discovery": xfetch.default_discovery_path("20260802"),
            "x_receipt": xfetch.default_receipt_path("20260802"),
            "web": self._plan_budget_path("web"),
            "xai": self._plan_budget_path("xai"),
        }

    def _plan_budget_path(self, provider: str) -> Path:
        return plan_budget.default_plan_budget_path(
            provider, "20260802", state_dir=self.state,
        )

    def _set_lane_execution_clocks(
        self,
        lane: str,
        *,
        reserved_at: str,
        fetched_at: str,
        discovery_generated_at: str,
        receipt_generated_at: str,
    ) -> None:
        if lane == "web":
            discovery_path = web.default_discovery_path("20260802")
            receipt_path = web.default_receipt_path("20260802")
            ledger_paths = (self._plan_budget_path("web"),)
        else:
            discovery_path = xfetch.default_discovery_path("20260802")
            receipt_path = xfetch.default_receipt_path("20260802")
            ledger_paths = (self._plan_budget_path("xai"),)
        discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        discovery["generated_at"] = discovery_generated_at
        for theme in discovery["themes"]:
            theme["observed_at"] = fetched_at
        receipt["generated_at"] = receipt_generated_at
        for row in receipt["source_refs"]:
            row["fetched_at"] = fetched_at
        for row in receipt.get("provider_response_refs", []):
            row["fetched_at"] = fetched_at
        receipt["discovery_artifact_sha256"] = web._discovery_evidence_hash(discovery)
        _write_json(discovery_path, discovery)
        _write_json(receipt_path, receipt)
        for path in ledger_paths:
            ledger = json.loads(path.read_text(encoding="utf-8"))
            ledger["first_reserved_at"] = reserved_at
            ledger["last_reserved_at"] = reserved_at
            _write_json(path, ledger)

    def _remove_lane_immutable_refs(self, lane: str) -> None:
        discovery_path = (
            web.default_discovery_path("20260802")
            if lane == "web"
            else xfetch.default_discovery_path("20260802")
        )
        receipt_path = (
            web.default_receipt_path("20260802")
            if lane == "web"
            else xfetch.default_receipt_path("20260802")
        )
        discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        discovery["source_refs"] = []
        discovery["themes"] = []
        receipt["source_refs"] = []
        if lane == "x":
            receipt["provider_response_refs"] = []
            receipt["drop_ledger"] = [
                {
                    "stage": "search_result",
                    "reason": "provider_response_capture_unavailable",
                    "detail": f"response_index={index}",
                    "provider_response_index": index,
                }
                for index in range(
                    receipt["fetch_contract"]["transport_response_counts"]["xai"]
                )
            ]
        else:
            receipt["drop_ledger"] = []
            receipt["summary"]["prompt_source_count"] = 0
        receipt["summary"]["accepted_source_count"] = 0
        receipt["summary"]["validated_theme_count"] = 0
        receipt["summary"]["validated_member_count"] = 0
        receipt["summary"]["dropped_result_count"] = len(receipt["drop_ledger"])
        receipt["discovery_artifact_sha256"] = web._discovery_evidence_hash(discovery)
        _write_json(discovery_path, discovery)
        _write_json(receipt_path, receipt)

    def test_theme_clock_is_the_publication_clock_not_the_fetch_clock(self):
        """A real run publishes themes EARLIER than the fetch that collected them.

        The producer derives the theme instant as max(bound source observed_at), and every
        source is fetched after it was published, so on a genuine artifact the theme instant
        is strictly before the fetch.  The default fixture happens to set fetched_at equal to
        the theme instant, which is the one arrangement under which a fetch-clock comparison
        also passes -- that coincidence hid a door that refused every real run.  This pins the
        realistic shape: adjudication must survive it.
        """
        for lane in ("web", "x"):
            self._set_lane_execution_clocks(
                lane,
                reserved_at="2026-08-01T11:00:00+00:00",
                fetched_at="2026-08-01T12:20:00+00:00",
                discovery_generated_at="2026-08-01T12:30:00+00:00",
                receipt_generated_at="2026-08-01T13:00:00+00:00",
            )
            discovery_path = (
                web.default_discovery_path("20260802")
                if lane == "web"
                else xfetch.default_discovery_path("20260802")
            )
            receipt_path = (
                web.default_receipt_path("20260802")
                if lane == "web"
                else xfetch.default_receipt_path("20260802")
            )
            discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            # Put the theme back on the publication clock the producer actually uses.
            for theme in discovery["themes"]:
                theme["observed_at"] = max(
                    row["observed_at"]
                    for row in receipt["source_refs"]
                    if row["source_id"] in theme["source_ref_ids"]
                )
            receipt["discovery_artifact_sha256"] = web._discovery_evidence_hash(discovery)
            _write_json(discovery_path, discovery)
            _write_json(receipt_path, receipt)
        summary = assess.run_assessment(
            packet_path=self.packet_path,
            generated_at=GENERATED_AT,
            preflight_only=True,
        )
        self.assertEqual(summary["status"], "preflight_passed_no_write")

    def test_preflight_consumes_every_registered_input_without_writing(self):
        summary = assess.run_assessment(
            packet_path=self.packet_path,
            generated_at=GENERATED_AT,
            preflight_only=True,
        )
        self.assertEqual(summary["status"], "preflight_passed_no_write")
        self.assertFalse(self.assessment_path.exists())

    def test_generation_writes_schema_valid_counts_and_digest_only_assessment(self):
        summary = assess.run_assessment(
            packet_path=self.packet_path,
            generated_at=GENERATED_AT,
        )
        self.assertEqual(summary["assessment_path"], self.assessment_path.relative_to(self.root).as_posix())
        payload = json.loads(self.assessment_path.read_text(encoding="utf-8"))
        assess._validate_schema(payload, assess.ASSESSMENT_SCHEMA_PATH, label="test assessment")
        self.assertEqual(payload["verdict"], "pass_to_query_planner_implementation")
        self.assertEqual(set(payload["input_bindings"]), {
            "web_discovery", "web_receipt", "x_discovery", "x_receipt",
            "web", "xai",
        })
        self.assertFalse(any(payload["prohibited_effects"].values()))
        self.assertEqual(payload["schema_version"], "1.4.0")
        self.assertEqual(
            payload["execution_evidence"]["budget_reservation_attempt_counts"],
            {"web": 1, "xai": 1},
        )
        self.assertEqual(payload["causal_floor"]["instant"], "2026-08-01T13:00:00Z")
        self.assertIn(
            "x_receipt.provider_response_refs[0].fetched_at",
            {row["component"] for row in payload["causal_floor"]["components"]},
        )
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("https://example.com", serialized)
        self.assertNotIn("AAPL", serialized)

    def test_alternate_tracked_output_fails_before_any_partial_write(self):
        # The inventory currently resolves aliases file-wide, so this path-specific name keeps
        # the proven TemporaryDirectory lineage separate from non-path ``alternate`` locals in
        # other tests.  A future scope-aware alias table would make the naming constraint
        # unnecessary; until then, reusing the generic name must turn the inventory guard red.
        alternate_assessment_path = self.docs / "alternate_assessment.json"
        with self.assertRaisesRegex(
            assess.QueryQualityProbeAssessmentError,
            "exact decision-date slot",
        ):
            assess.run_assessment(
                packet_path=self.packet_path,
                assessment_path=alternate_assessment_path,
                generated_at=GENERATED_AT,
            )
        self.assertFalse(alternate_assessment_path.exists())
        self.assertFalse(self.assessment_path.exists())

    def test_exact_relative_assessment_path_is_accepted(self):
        relative = self.assessment_path.relative_to(self.root)
        summary = assess.run_assessment(
            packet_path=self.packet_path,
            assessment_path=relative,
            generated_at=GENERATED_AT,
            preflight_only=True,
        )
        self.assertEqual(summary["status"], "preflight_passed_no_write")
        self.assertFalse(self.assessment_path.exists())

    def test_relative_packet_from_other_cwd_binds_the_validated_repo_packet(self):
        outside = self.root / "outside_cwd"
        fake_packet = outside / "docs" / self.packet_path.name
        fake_payload = json.loads(self.packet_path.read_text(encoding="utf-8"))
        fake_payload["query_templates"][0]["text"] = "different unreviewed query"
        _write_json(fake_packet, fake_payload)
        previous_cwd = Path.cwd()
        try:
            os.chdir(outside)
            built, _ = assess.build_assessment(
                packet_path=Path("docs") / self.packet_path.name,
                generated_at=GENERATED_AT,
            )
        finally:
            os.chdir(previous_cwd)
        self.assertEqual(
            built["probe_identity"]["packet_sha256"],
            hashlib.sha256(self.packet_path.read_bytes()).hexdigest(),
        )
        self.assertNotEqual(
            built["probe_identity"]["packet_sha256"],
            hashlib.sha256(fake_packet.read_bytes()).hexdigest(),
        )

    def test_normalized_relative_alias_is_rejected(self):
        alias = Path("docs") / ".." / "docs" / self.assessment_path.name
        with self.assertRaisesRegex(
            assess.QueryQualityProbeAssessmentError,
            "exact decision-date slot",
        ):
            assess.run_assessment(
                packet_path=self.packet_path,
                assessment_path=alias,
                generated_at=GENERATED_AT,
                preflight_only=True,
            )
        self.assertFalse(self.assessment_path.exists())

    def test_symlinked_default_slot_is_rejected_before_target_write(self):
        outside_target = self.root / "outside_assessment.json"
        outside_target.write_text("unchanged", encoding="utf-8")
        original_is_symlink = Path.is_symlink

        def identify_default(path):
            return Path(path) == self.assessment_path or original_is_symlink(path)

        with mock.patch.object(Path, "is_symlink", autospec=True, side_effect=identify_default):
            with self.assertRaisesRegex(
                assess.QueryQualityProbeAssessmentError,
                "must not be a symlink",
            ):
                assess.run_assessment(
                    packet_path=self.packet_path,
                    assessment_path=self.assessment_path,
                    generated_at=GENERATED_AT,
                )
        self.assertEqual(outside_target.read_text(encoding="utf-8"), "unchanged")
        self.assertFalse(self.assessment_path.exists())

    def test_each_packet_output_and_ledger_input_symlink_is_rejected_without_write(self):
        targets = [
            self.packet_path,
            web.default_discovery_path("20260802"),
            web.default_receipt_path("20260802"),
            xfetch.default_discovery_path("20260802"),
            xfetch.default_receipt_path("20260802"),
            self._plan_budget_path("web"),
            self._plan_budget_path("xai"),
        ]
        original_is_symlink = Path.is_symlink
        for target in targets:
            with self.subTest(target=target.name):
                self._write_inputs()

                def identify_target(path, *, selected=target):
                    return Path(path) == selected or original_is_symlink(path)

                with mock.patch.object(
                    Path,
                    "is_symlink",
                    autospec=True,
                    side_effect=identify_target,
                ):
                    with self.assertRaisesRegex(
                        assess.QueryQualityProbeAssessmentError,
                        "must not be a symlink",
                    ):
                        assess.run_assessment(
                            packet_path=self.packet_path,
                            generated_at=GENERATED_AT,
                        )
                self.assertFalse(self.assessment_path.exists())

    def test_symlinked_input_parent_is_rejected_without_write(self):
        original_is_symlink = Path.is_symlink

        def identify_state_parent(path):
            return Path(path) == self.state or original_is_symlink(path)

        with mock.patch.object(
            Path,
            "is_symlink",
            autospec=True,
            side_effect=identify_state_parent,
        ):
            with self.assertRaisesRegex(
                assess.QueryQualityProbeAssessmentError,
                "must not be a symlink",
            ):
                assess.run_assessment(
                    packet_path=self.packet_path,
                    generated_at=GENERATED_AT,
                )
        self.assertFalse(self.assessment_path.exists())

    def test_write_boundary_revalidates_the_assessment_path(self):
        calls = []
        original = probe_paths.validate_assessment_path

        def observed(path, decision_date):
            calls.append(Path(path))
            return original(path, decision_date)

        with mock.patch.object(probe_paths, "validate_assessment_path", side_effect=observed):
            assess.run_assessment(packet_path=self.packet_path, generated_at=GENERATED_AT)
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(self.assessment_path.exists())

    def test_discovery_tamper_is_rejected_before_assessment_write(self):
        path = web.default_discovery_path("20260802")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["themes"][0]["display_name"] = "tampered"
        _write_json(path, payload)
        with self.assertRaisesRegex(assess.QueryQualityProbeAssessmentError, "does not bind"):
            assess.run_assessment(packet_path=self.packet_path, generated_at=GENERATED_AT)
        self.assertFalse(self.assessment_path.exists())

    def test_legal_same_scope_retry_writes_inconclusive_assessment(self):
        for key in ("web", "xai"):
            with self.subTest(ledger=key):
                self._write_inputs()
                self.assessment_path.unlink(missing_ok=True)
                path = self._packet_and_input_slot_paths()[key]
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["reservation_attempt_count"] = 2
                _write_json(path, payload)
                summary = assess.run_assessment(
                    packet_path=self.packet_path,
                    generated_at=GENERATED_AT,
                )
                self.assertEqual(
                    summary["verdict"],
                    "provider_or_execution_inconclusive_do_not_grade_templates",
                )
                written = json.loads(self.assessment_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    written["execution_evidence"]["budget_reservation_attempt_counts"][key],
                    2,
                )
                self.assertIn(
                    "actual_call_count_or_scope_cannot_be_proven",
                    written["execution_evidence"]["inconclusive_reasons"],
                )

    def test_invalid_reservation_attempt_count_fails_before_assessment_write(self):
        cases = (
            ("zero", lambda payload: payload.__setitem__("reservation_attempt_count", 0)),
            ("negative", lambda payload: payload.__setitem__("reservation_attempt_count", -1)),
            ("bool", lambda payload: payload.__setitem__("reservation_attempt_count", True)),
            ("non_int", lambda payload: payload.__setitem__("reservation_attempt_count", "1")),
            ("missing", lambda payload: payload.pop("reservation_attempt_count")),
        )
        for key in ("web", "xai"):
            for label, mutate in cases:
                with self.subTest(ledger=key, mutation=label):
                    self._write_inputs()
                    self.assessment_path.unlink(missing_ok=True)
                    path = self._packet_and_input_slot_paths()[key]
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    mutate(payload)
                    _write_json(path, payload)
                    with self.assertRaisesRegex(
                        assess.QueryQualityProbeAssessmentError,
                        "reservation_attempt_count",
                    ):
                        assess.run_assessment(
                            packet_path=self.packet_path,
                            generated_at=GENERATED_AT,
                        )
                    self.assertFalse(self.assessment_path.exists())

    def test_budget_ledger_tampering_still_fails_before_assessment_write(self):
        cases = (
            (
                "query_sha256",
                lambda payload: payload["query_reservations"][0].__setitem__(
                    "query_sha256", "0" * 64
                ),
                "query scope is not exact",
            ),
            (
                "query_count",
                lambda payload: payload["query_reservations"][0].__setitem__(
                    "query_count", 3
                ),
                "query scope is not exact",
            ),
            (
                "planned_provider_call_count",
                lambda payload: payload.__setitem__("planned_provider_call_count", 5),
                "mismatch at planned_provider_call_count",
            ),
            (
                "duplicate_query_reservation",
                lambda payload: payload["query_reservations"].append(
                    dict(payload["query_reservations"][0])
                ),
                "scope is not exact",
            ),
            (
                # The exact shape that made this door unopenable on the first real
                # plan-bound run: a ledger keyed on the query TEXT, which is what the
                # bare, plan-less dispatch path records.  A plan-bound ledger keys on
                # the query id, so the text dialect must be refused, not tolerated.
                "pre_plan_query_text_scope_dialect",
                lambda payload, s=self: payload["query_reservations"][0].__setitem__(
                    "query_sha256",
                    hashlib.sha256(s.queries[0].encode("utf-8")).hexdigest(),
                ),
                "query scope is not exact",
            ),
            (
                "conflicting_query_reservation",
                lambda payload: payload["query_reservations"][0].__setitem__(
                    "query_sha256", "1" * 64
                ),
                "scope is not exact",
            ),
            (
                "reservation_clock_order",
                lambda payload: payload.update(
                    first_reserved_at="2026-08-01T12:00:01Z",
                    last_reserved_at="2026-08-01T12:00:00Z",
                ),
                "cannot follow",
            ),
        )
        for key in ("web", "xai"):
            for label, mutate, error in cases:
                with self.subTest(ledger=key, mutation=label):
                    self._write_inputs()
                    self.assessment_path.unlink(missing_ok=True)
                    path = self._packet_and_input_slot_paths()[key]
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    mutate(payload)
                    _write_json(path, payload)
                    with self.assertRaisesRegex(
                        assess.QueryQualityProbeAssessmentError,
                        error,
                    ):
                        assess.run_assessment(
                            packet_path=self.packet_path,
                            generated_at=GENERATED_AT,
                        )
                    self.assertFalse(self.assessment_path.exists())

    def test_provider_identity_gap_yields_preregistered_inconclusive_verdict(self):
        path = xfetch.default_receipt_path("20260802")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["fetch_contract"]["grok_model"]["served_model"] = None
        _write_json(path, payload)
        built, _ = assess.build_assessment(packet_path=self.packet_path, generated_at=GENERATED_AT)
        self.assertEqual(
            built["verdict"],
            "provider_or_execution_inconclusive_do_not_grade_templates",
        )
        self.assertIn("served_model_identity_missing", built["execution_evidence"]["inconclusive_reasons"])

    def test_generated_at_before_causal_floor_fails_without_partial_write(self):
        with self.assertRaisesRegex(
            assess.QueryQualityProbeAssessmentError,
            "causal evidence floor",
        ):
            assess.run_assessment(
                packet_path=self.packet_path,
                generated_at="2000-01-01T00:00:00Z",
            )
        self.assertFalse(self.assessment_path.exists())

    def test_generated_at_equal_to_causal_floor_is_accepted(self):
        built, _ = assess.build_assessment(
            packet_path=self.packet_path,
            generated_at="2026-08-01T13:00:00Z",
        )
        self.assertEqual(built["generated_at"], "2026-08-01T13:00:00+00:00")
        self.assertEqual(built["causal_floor"]["instant"], "2026-08-01T13:00:00Z")

    def test_frozen_time_travel_assessment_cannot_be_reused(self):
        built, _ = assess.build_assessment(
            packet_path=self.packet_path,
            generated_at=GENERATED_AT,
        )
        built["generated_at"] = "2000-01-01T00:00:00Z"
        _write_json(self.assessment_path, built)
        with self.assertRaisesRegex(
            assess.QueryQualityProbeAssessmentError,
            "causal evidence floor",
        ):
            assess.run_assessment(
                packet_path=self.packet_path,
                generated_at=GENERATED_AT,
            )

    def test_advancing_any_input_clock_invalidates_the_old_assessment_clock(self):
        mutations = [
            ("packet", self.packet_path, ("generated_at",)),
            ("web discovery", web.default_discovery_path("20260802"), ("generated_at",)),
            ("web receipt", web.default_receipt_path("20260802"), ("generated_at",)),
            ("x discovery", xfetch.default_discovery_path("20260802"), ("generated_at",)),
            ("x receipt", xfetch.default_receipt_path("20260802"), ("generated_at",)),
        ]
        for lane, discovery_path, receipt_path in (
            (
                "web",
                web.default_discovery_path("20260802"),
                web.default_receipt_path("20260802"),
            ),
            (
                "x",
                xfetch.default_discovery_path("20260802"),
                xfetch.default_receipt_path("20260802"),
            ),
        ):
            discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            mutations.extend(
                (
                    f"{lane} discovery source {index}",
                    discovery_path,
                    ("source_refs", index, "observed_at"),
                )
                for index in range(len(discovery["source_refs"]))
            )
            mutations.extend(
                (
                    f"{lane} receipt source observed {index}",
                    receipt_path,
                    ("source_refs", index, "observed_at"),
                )
                for index in range(len(receipt["source_refs"]))
            )
            mutations.extend(
                (
                    f"{lane} receipt source fetched {index}",
                    receipt_path,
                    ("source_refs", index, "fetched_at"),
                )
                for index in range(len(receipt["source_refs"]))
            )
            mutations.extend(
                (
                    f"{lane} theme {index}",
                    discovery_path,
                    ("themes", index, "observed_at"),
                )
                for index in range(len(discovery["themes"]))
            )
        x_receipt_path = xfetch.default_receipt_path("20260802")
        x_receipt = json.loads(x_receipt_path.read_text(encoding="utf-8"))
        mutations.extend(
            (
                f"x provider response {index}",
                x_receipt_path,
                ("provider_response_refs", index, "fetched_at"),
            )
            for index in range(len(x_receipt["provider_response_refs"]))
        )
        for ledger_name, ledger_path in (
            ("web", self._plan_budget_path("web")),
            ("xai", self._plan_budget_path("xai")),
        ):
            for field in ("first_reserved_at", "last_reserved_at"):
                mutations.append((f"{ledger_name} ledger {field}", ledger_path, (field,)))
        for label, path, key_path in mutations:
            with self.subTest(component=label):
                self._write_inputs()
                payload = json.loads(path.read_text(encoding="utf-8"))
                target = payload
                for key in key_path[:-1]:
                    target = target[key]
                target[key_path[-1]] = "2026-08-01T21:00:00Z"
                if path in {
                    web.default_discovery_path("20260802"),
                    xfetch.default_discovery_path("20260802"),
                }:
                    receipt_path = (
                        web.default_receipt_path("20260802")
                        if path == web.default_discovery_path("20260802")
                        else xfetch.default_receipt_path("20260802")
                    )
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                    if key_path[:1] == ("source_refs",):
                        receipt["source_refs"][key_path[1]]["observed_at"] = (
                            "2026-08-01T21:00:00Z"
                        )
                    receipt["discovery_artifact_sha256"] = web._discovery_evidence_hash(payload)
                    _write_json(receipt_path, receipt)
                _write_json(path, payload)
                with self.assertRaises(assess.QueryQualityProbeAssessmentError):
                    assess.run_assessment(
                        packet_path=self.packet_path,
                        generated_at=GENERATED_AT,
                    )
                self.assertFalse(self.assessment_path.exists())

    def test_causal_clock_manifest_enumerates_every_required_clock(self):
        built, _ = assess.build_assessment(
            packet_path=self.packet_path,
            generated_at=GENERATED_AT,
        )
        actual = {
            row["component"] for row in built["causal_floor"]["components"]
        }
        expected = {
            "packet.generated_at",
            "web_discovery.generated_at",
            "web_receipt.generated_at",
            "x_discovery.generated_at",
            "x_receipt.generated_at",
        }
        for lane in ("web", "x"):
            expected.update(
                f"{lane}_discovery.source_refs[{index}].observed_at"
                for index in range(3)
            )
            expected.update(
                f"{lane}_receipt.source_refs[{index}].observed_at"
                for index in range(3)
            )
            expected.update(
                f"{lane}_receipt.source_refs[{index}].fetched_at"
                for index in range(3)
            )
            expected.add(f"{lane}_discovery.themes[0].observed_at")
        expected.update(
            f"x_receipt.provider_response_refs[{index}].fetched_at"
            for index in range(4)
        )
        for ledger in ("web", "xai"):
            expected.add(f"{ledger}_ledger.first_reserved_at")
            expected.add(f"{ledger}_ledger.last_reserved_at")
        self.assertEqual(actual, expected)

    def test_reordered_receipt_sources_keep_clock_labels_bound_to_real_indexes(self):
        path = web.default_receipt_path("20260802")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["source_refs"].reverse()
        _write_json(path, payload)
        built, _ = assess.build_assessment(
            packet_path=self.packet_path,
            generated_at=GENERATED_AT,
        )
        components = {
            row["component"]: row["instant"]
            for row in built["causal_floor"]["components"]
        }
        self.assertEqual(
            components["web_receipt.source_refs[0].observed_at"],
            "2026-08-01T12:00:00Z",
        )
        self.assertEqual(
            components["web_receipt.source_refs[2].observed_at"],
            "2026-08-01T10:00:00Z",
        )

    def test_invalid_clock_orders_fail_closed_without_partial_output(self):
        cases = [
            (
                "ledger first after last",
                self._plan_budget_path("web"),
                ("first_reserved_at",),
                "2026-08-01T12:00:00Z",
            ),
            (
                "receipt observed mismatch",
                web.default_receipt_path("20260802"),
                ("source_refs", 0, "observed_at"),
                "2026-08-01T10:30:00Z",
            ),
            (
                "source observed after fetched",
                web.default_receipt_path("20260802"),
                ("source_refs", 0, "fetched_at"),
                "2026-08-01T09:00:00Z",
            ),
            (
                "provider response after receipt",
                xfetch.default_receipt_path("20260802"),
                ("provider_response_refs", 0, "fetched_at"),
                "2026-08-01T14:00:00Z",
            ),
        ]
        for label, path, key_path, value in cases:
            with self.subTest(case=label):
                self._write_inputs()
                payload = json.loads(path.read_text(encoding="utf-8"))
                target = payload
                for key in key_path[:-1]:
                    target = target[key]
                target[key_path[-1]] = value
                _write_json(path, payload)
                with self.assertRaises(assess.QueryQualityProbeAssessmentError):
                    assess.run_assessment(
                        packet_path=self.packet_path,
                        generated_at=GENERATED_AT,
                    )
                self.assertFalse(self.assessment_path.exists())

    def test_every_cross_stage_causal_edge_has_a_dying_control(self):
        cases = (
            (
                "packet after reservation",
                self.packet_path,
                ("generated_at",),
                "2026-08-01T11:00:01Z",
                None,
            ),
            (
                "reservation after evidence fetch",
                self._plan_budget_path("web"),
                ("last_reserved_at",),
                "2026-08-01T12:00:01Z",
                None,
            ),
            (
                "source fetch after discovery",
                web.default_receipt_path("20260802"),
                ("source_refs", 0, "fetched_at"),
                "2026-08-01T12:00:01Z",
                None,
            ),
            (
                "theme before a bound source",
                web.default_discovery_path("20260802"),
                ("themes", 0, "observed_at"),
                "2026-08-01T11:59:59Z",
                web.default_receipt_path("20260802"),
            ),
        )
        for label, path, key_path, value, receipt_to_rebind in cases:
            with self.subTest(edge=label):
                self._write_inputs()
                payload = json.loads(path.read_text(encoding="utf-8"))
                target = payload
                for key in key_path[:-1]:
                    target = target[key]
                target[key_path[-1]] = value
                _write_json(path, payload)
                if receipt_to_rebind is not None:
                    receipt = json.loads(receipt_to_rebind.read_text(encoding="utf-8"))
                    receipt["discovery_artifact_sha256"] = web._discovery_evidence_hash(payload)
                    _write_json(receipt_to_rebind, receipt)
                with self.assertRaises(assess.QueryQualityProbeAssessmentError):
                    assess.run_assessment(
                        packet_path=self.packet_path,
                        generated_at=GENERATED_AT,
                    )
                self.assertFalse(self.assessment_path.exists())

    def test_lane_local_causal_edges_allow_both_serial_execution_orders(self):
        orders = (
            (
                "web_then_x",
                (
                    ("web", "2026-08-01T11:00:00Z", "2026-08-01T12:00:00Z",
                     "2026-08-01T12:05:00Z", "2026-08-01T12:10:00Z"),
                    ("x", "2026-08-01T12:15:00Z", "2026-08-01T12:30:00Z",
                     "2026-08-01T12:35:00Z", "2026-08-01T12:40:00Z"),
                ),
            ),
            (
                "x_then_web",
                (
                    ("x", "2026-08-01T11:00:00Z", "2026-08-01T12:00:00Z",
                     "2026-08-01T12:05:00Z", "2026-08-01T12:10:00Z"),
                    ("web", "2026-08-01T12:15:00Z", "2026-08-01T12:30:00Z",
                     "2026-08-01T12:35:00Z", "2026-08-01T12:40:00Z"),
                ),
            ),
        )
        for label, lanes in orders:
            with self.subTest(order=label):
                self._write_inputs()
                for lane, reserved, fetched, discovery_generated, receipt_generated in lanes:
                    self._set_lane_execution_clocks(
                        lane,
                        reserved_at=reserved,
                        fetched_at=fetched,
                        discovery_generated_at=discovery_generated,
                        receipt_generated_at=receipt_generated,
                    )
                built, _ = assess.build_assessment(
                    packet_path=self.packet_path,
                    generated_at=GENERATED_AT,
                )
                self.assertEqual(
                    built["verdict"], "pass_to_query_planner_implementation"
                )

    def test_each_ledger_is_bounded_only_by_its_own_lane_execution(self):
        cases = (
            ("web", self._plan_budget_path("web")),
            ("xai", self._plan_budget_path("xai")),
        )
        for label, path in cases:
            with self.subTest(ledger=label):
                self._write_inputs()
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["first_reserved_at"] = "2026-08-01T12:00:01Z"
                payload["last_reserved_at"] = "2026-08-01T12:00:01Z"
                _write_json(path, payload)
                with self.assertRaisesRegex(
                    assess.QueryQualityProbeAssessmentError,
                    "last_reserved_at cannot be later than",
                ):
                    assess.run_assessment(
                        packet_path=self.packet_path,
                        generated_at=GENERATED_AT,
                    )
                self.assertFalse(self.assessment_path.exists())

    def test_zero_ref_lanes_emit_preregistered_inconclusive_with_receipt_clock(self):
        for zero_lanes in (("web",), ("x",), ("web", "x")):
            with self.subTest(zero_lanes=zero_lanes):
                self._write_inputs()
                for lane in zero_lanes:
                    self._remove_lane_immutable_refs(lane)
                built, _ = assess.build_assessment(
                    packet_path=self.packet_path,
                    generated_at=GENERATED_AT,
                )
                self.assertEqual(
                    built["verdict"],
                    "provider_or_execution_inconclusive_do_not_grade_templates",
                )
                reasons = built["execution_evidence"]["inconclusive_reasons"]
                for lane in zero_lanes:
                    self.assertIn(
                        f"{lane}_immutable_execution_evidence_missing", reasons
                    )

    def test_zero_ref_fallback_rejects_incomplete_execution_accounting(self):
        self._remove_lane_immutable_refs("web")
        receipt_path = web.default_receipt_path("20260802")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["fetch_contract"]["network_call_count"] -= 1
        _write_json(receipt_path, receipt)
        with self.assertRaisesRegex(
            assess.QueryQualityProbeAssessmentError,
            "zero-ref execution accounting is incomplete",
        ):
            assess.run_assessment(
                packet_path=self.packet_path,
                generated_at=GENERATED_AT,
            )
        self.assertFalse(self.assessment_path.exists())

        self._write_inputs()
        self._remove_lane_immutable_refs("x")
        receipt_path = xfetch.default_receipt_path("20260802")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["drop_ledger"].pop()
        receipt["summary"]["dropped_result_count"] -= 1
        _write_json(receipt_path, receipt)
        with self.assertRaisesRegex(
            assess.QueryQualityProbeAssessmentError,
            "provider response evidence is incomplete",
        ):
            assess.run_assessment(
                packet_path=self.packet_path,
                generated_at=GENERATED_AT,
            )
        self.assertFalse(self.assessment_path.exists())

    def test_decision_cutoff_before_equal_and_after_boundaries(self):
        cutoff_cases = (
            ("2026-08-02T13:29:59Z", True),
            ("2026-08-02T13:30:00Z", False),
            ("2026-08-02T13:30:01Z", False),
        )
        receipt_path = xfetch.default_receipt_path("20260802")
        for value, accepted in cutoff_cases:
            with self.subTest(receipt_generated_at=value):
                self._write_inputs()
                payload = json.loads(receipt_path.read_text(encoding="utf-8"))
                payload["generated_at"] = value
                _write_json(receipt_path, payload)
                if accepted:
                    built, _ = assess.build_assessment(
                        packet_path=self.packet_path,
                        generated_at=value,
                    )
                    self.assertEqual(built["causal_floor"]["instant"], value)
                else:
                    with self.assertRaisesRegex(
                        assess.QueryQualityProbeAssessmentError,
                        "strictly earlier than the decision cutoff",
                    ):
                        assess.run_assessment(
                            packet_path=self.packet_path,
                            generated_at="2026-08-02T13:31:00Z",
                        )
                    self.assertFalse(self.assessment_path.exists())

    def test_web_and_x_source_raw_publish_failures_are_inconclusive(self):
        self.assertIs(
            xfetch.SOURCE_RAW_PUBLISH_FAILURE_REASONS,
            web.SOURCE_RAW_PUBLISH_FAILURE_REASONS,
        )
        for lane, path in (
            ("web", web.default_receipt_path("20260802")),
            ("x", xfetch.default_receipt_path("20260802")),
        ):
            for reason in sorted(web.SOURCE_RAW_PUBLISH_FAILURE_REASONS):
                with self.subTest(lane=lane, reason=reason):
                    self._write_inputs()
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    payload["drop_ledger"] = [{
                        "stage": "search_result",
                        "reason": reason,
                        "detail": "https://example.com/raw-conflict",
                    }]
                    payload["summary"]["dropped_result_count"] = 1
                    _write_json(path, payload)
                    built, _ = assess.build_assessment(
                        packet_path=self.packet_path,
                        generated_at=GENERATED_AT,
                    )
                    self.assertEqual(
                        built["verdict"],
                        "provider_or_execution_inconclusive_do_not_grade_templates",
                    )
                    self.assertIn(
                        f"{lane}_source_raw_publish_failure:{reason}",
                        built["execution_evidence"]["inconclusive_reasons"],
                    )

    def test_packet_and_seven_inputs_use_one_read_for_parse_validate_and_hash(self):
        original = assess._read_json_snapshot
        for label, target_path in self._packet_and_input_slot_paths().items():
            with self.subTest(slot=label):
                self._write_inputs()
                if self.packet_path != target_path:
                    _write_json(
                        self.packet_path,
                        json.loads(SOURCE_PACKET.read_text(encoding="utf-8")),
                    )
                target = target_path.resolve()

                def read_then_mutate(path, *, label, _target=target):
                    snapshot = original(path, label=label)
                    if path.resolve() == _target:
                        path.write_bytes(snapshot.raw_bytes + b"\n")
                    return snapshot

                with mock.patch.object(
                    assess,
                    "_read_json_snapshot",
                    side_effect=read_then_mutate,
                ):
                    with self.assertRaisesRegex(
                        assess.QueryQualityProbeAssessmentError,
                        "changed after its validated read",
                    ):
                        assess.run_assessment(
                            packet_path=self.packet_path,
                            generated_at=GENERATED_AT,
                            preflight_only=True,
                        )
                self.assertFalse(self.assessment_path.exists())

    def test_packet_and_seven_inputs_are_rechecked_immediately_before_write(self):
        original = probe_paths.validate_assessment_path
        for label, target_path in self._packet_and_input_slot_paths().items():
            with self.subTest(slot=label):
                self._write_inputs()
                _write_json(
                    self.packet_path,
                    json.loads(SOURCE_PACKET.read_text(encoding="utf-8")),
                )
                calls = 0

                def mutate_after_build(path, decision_date, _target=target_path):
                    nonlocal calls
                    result = original(path, decision_date)
                    calls += 1
                    if calls == 2:
                        _target.write_bytes(_target.read_bytes() + b"\n")
                    return result

                with mock.patch.object(
                    probe_paths,
                    "validate_assessment_path",
                    side_effect=mutate_after_build,
                ):
                    with self.assertRaisesRegex(
                        assess.QueryQualityProbeAssessmentError,
                        "changed after its validated read",
                    ):
                        assess.run_assessment(
                            packet_path=self.packet_path,
                            generated_at=GENERATED_AT,
                        )
                self.assertEqual(calls, 2)
                self.assertFalse(self.assessment_path.exists())

    def test_x_provider_response_evidence_mutations_fail_closed_without_partial_output(self):
        receipt_path = xfetch.default_receipt_path("20260802")
        mutations = {
            "whole group deleted": lambda payload: payload.pop("provider_response_refs"),
            "one response row deleted": lambda payload: payload["provider_response_refs"].pop(1),
            "completed response index missing": lambda payload: payload[
                "provider_response_refs"
            ][1].update({"response_index": 4}),
        }
        for label, mutate in mutations.items():
            with self.subTest(mutation=label):
                self._write_inputs()
                payload = json.loads(receipt_path.read_text(encoding="utf-8"))
                mutate(payload)
                _write_json(receipt_path, payload)
                with self.assertRaisesRegex(
                    assess.QueryQualityProbeAssessmentError,
                    "provider response evidence is incomplete",
                ):
                    assess.run_assessment(
                        packet_path=self.packet_path,
                        generated_at=GENERATED_AT,
                    )
                self.assertFalse(self.assessment_path.exists())

    def test_each_x_provider_response_drop_reason_is_preregistered_inconclusive(self):
        path = xfetch.default_receipt_path("20260802")
        for reason in sorted(xfetch.PROVIDER_RESPONSE_DROP_REASONS):
            with self.subTest(reason=reason):
                self._write_inputs()
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["provider_response_refs"].pop(1)
                payload["drop_ledger"] = [{
                    "stage": "search_result",
                    "reason": reason,
                    "detail": "response_index=1",
                    "provider_response_index": 1,
                }]
                payload["summary"]["dropped_result_count"] = 1
                _write_json(path, payload)
                built, _ = assess.build_assessment(
                    packet_path=self.packet_path,
                    generated_at=GENERATED_AT,
                )
                self.assertEqual(
                    built["verdict"],
                    "provider_or_execution_inconclusive_do_not_grade_templates",
                )
                self.assertIn(
                    f"x_provider_response_failure:{reason}",
                    built["execution_evidence"]["inconclusive_reasons"],
                )

    def test_web_clean_regroup_counts_remain_eligible_for_pass(self):
        built, _ = assess.build_assessment(
            packet_path=self.packet_path,
            generated_at=GENERATED_AT,
        )
        self.assertEqual(built["verdict"], "pass_to_query_planner_implementation")
        self.assertEqual(
            built["execution_evidence"]["web_regroup_chunk_counts"],
            {"attempted": 4, "successful": 4, "failed": 0, "failed_indexes": []},
        )

    def test_missing_web_member_binding_ledger_is_typed_inconclusive(self):
        discovery, receipt, _ = web.build_web_fetch_packet(
            queries=["q"], search_results=[], llm_response='{"themes":[]}',
            expected_decision_date="20260802", generated_at="2026-08-01T08:00:00Z",
        )
        receipt.pop("member_binding_ledger")
        reasons = assess._validate_discovery_and_receipt(
            lane="web", discovery=discovery, receipt=receipt,
            decision_date="20260802", queries=["q"],
        )
        self.assertIn("web_member_binding_ledger_invalid", reasons)

    def test_web_single_multiple_and_all_chunk_drops_are_inconclusive(self):
        path = web.default_receipt_path("20260802")
        for failed_indexes in ([1], [0, 2], [0, 1, 2, 3]):
            with self.subTest(failed_indexes=failed_indexes):
                self._write_inputs()
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["fetch_contract"]["regroup_chunk_counts"] = {
                    "attempted": 4,
                    "successful": 4 - len(failed_indexes),
                    "failed": len(failed_indexes),
                    "failed_indexes": list(failed_indexes),
                }
                payload["drop_ledger"] = [
                    {
                        "stage": "llm",
                        "reason": "regroup_chunk_dropped",
                        "detail": f"chunk[{index}]:RuntimeError",
                    }
                    for index in failed_indexes
                ]
                payload["drop_ledger"].extend(
                    {
                        "stage": "llm",
                        "reason": "provider_item_exception_dropped",
                        "detail": f"chunk[{index}]:RuntimeError",
                    }
                    for index in failed_indexes
                )
                if len(failed_indexes) == 4:
                    payload["drop_ledger"].append({
                        "stage": "llm",
                        "reason": "regroup_response_invalid",
                        "detail": "no_chunk_survived",
                    })
                payload["summary"]["dropped_result_count"] = len(payload["drop_ledger"])
                _write_json(path, payload)
                built, _ = assess.build_assessment(
                    packet_path=self.packet_path,
                    generated_at=GENERATED_AT,
                )
                self.assertEqual(
                    built["verdict"],
                    "provider_or_execution_inconclusive_do_not_grade_templates",
                )
                self.assertIn(
                    "web_regroup_failed",
                    built["execution_evidence"]["inconclusive_reasons"],
                )

    def test_web_auth_or_transport_drop_is_inconclusive(self):
        path = web.default_receipt_path("20260802")
        for reason in sorted(web.INCONCLUSIVE_SEARCH_RESULT_REASONS):
            with self.subTest(reason=reason):
                self._write_inputs()
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["drop_ledger"] = [{
                    "stage": "search_result",
                    "reason": reason,
                    "detail": "RuntimeError",
                }]
                payload["summary"]["dropped_result_count"] = 1
                _write_json(path, payload)
                built, _ = assess.build_assessment(
                    packet_path=self.packet_path,
                    generated_at=GENERATED_AT,
                )
                self.assertEqual(
                    built["verdict"],
                    "provider_or_execution_inconclusive_do_not_grade_templates",
                )
                self.assertIn(
                    "web_provider_or_transport_failed",
                    built["execution_evidence"]["inconclusive_reasons"],
                )

    def test_web_regroup_count_or_index_mismatch_fails_before_partial_write(self):
        path = web.default_receipt_path("20260802")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["fetch_contract"]["regroup_chunk_counts"] = {
            "attempted": 4,
            "successful": 3,
            "failed": 1,
            "failed_indexes": [2],
        }
        payload["drop_ledger"] = [
            {
                "stage": "llm",
                "reason": "regroup_chunk_dropped",
                "detail": "chunk[1]:RuntimeError",
            },
            {
                "stage": "llm",
                "reason": "provider_item_exception_dropped",
                "detail": "chunk[1]:RuntimeError",
            },
        ]
        payload["summary"]["dropped_result_count"] = 2
        _write_json(path, payload)
        with self.assertRaisesRegex(
            assess.QueryQualityProbeAssessmentError,
            "do not match audited counts",
        ):
            assess.run_assessment(
                packet_path=self.packet_path,
                generated_at=GENERATED_AT,
            )
        self.assertFalse(self.assessment_path.exists())

    def test_unpaired_web_provider_item_chunk_drop_cannot_forge_clean_counts(self):
        path = web.default_receipt_path("20260802")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["drop_ledger"] = [{
            "stage": "llm",
            "reason": "provider_item_exception_dropped",
            "detail": "chunk[1]:RuntimeError",
        }]
        payload["summary"]["dropped_result_count"] = 1
        _write_json(path, payload)
        with self.assertRaisesRegex(
            assess.QueryQualityProbeAssessmentError,
            "lack paired provider-item evidence",
        ):
            assess.run_assessment(
                packet_path=self.packet_path,
                generated_at=GENERATED_AT,
            )
        self.assertFalse(self.assessment_path.exists())

    def test_every_malformed_web_chunk_drop_shape_fails_without_partial_write(self):
        path = web.default_receipt_path("20260802")
        malformed_rows = [
            {"stage": "llm", "reason": "regroup_chunk_dropped"},
            {"stage": "llm", "reason": "regroup_chunk_dropped", "detail": None},
            {
                "stage": "llm",
                "reason": "regroup_chunk_dropped",
                "detail": "not-a-chunk",
            },
            {
                "stage": "llm",
                "reason": "regroup_chunk_dropped",
                "detail": "chunk[1:RuntimeError",
            },
            {
                "stage": "llm",
                "reason": "regroup_chunk_dropped",
                "detail": "chunk[-1]:RuntimeError",
            },
            {
                "stage": "llm",
                "reason": "regroup_chunk_dropped",
                "detail": "chunk[1]:RuntimeError trailing",
            },
            {
                "stage": "search_result",
                "reason": "regroup_chunk_dropped",
                "detail": "chunk[1]:RuntimeError",
            },
        ]
        for row in malformed_rows:
            with self.subTest(row=row):
                self._write_inputs()
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["drop_ledger"] = [row]
                payload["summary"]["dropped_result_count"] = 1
                _write_json(path, payload)
                with self.assertRaises(assess.QueryQualityProbeAssessmentError):
                    assess.run_assessment(
                        packet_path=self.packet_path,
                        generated_at=GENERATED_AT,
                    )
                self.assertFalse(self.assessment_path.exists())

    def test_every_generated_file_is_outside_the_repository(self):
        assess.run_assessment(packet_path=self.packet_path, generated_at=GENERATED_AT)
        files = [path.resolve() for path in self.root.rglob("*") if path.is_file()]
        self.assertTrue(files)
        self.assertTrue(all(path.is_relative_to(self.root) for path in files))
        self.assertTrue(all(not path.is_relative_to(REPO_ROOT.resolve()) for path in files))

    def test_direct_script_help_bootstraps_outside_repository(self):
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        script = REPO_ROOT / "runners" / "us_short_soft_discovery_query_quality_probe_assess.py"
        with tempfile.TemporaryDirectory() as cwd:
            completed = subprocess.run(
                [sys.executable, "-I", str(script), "--help"],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


class ProductionQueryQualityProbeSeamTest(unittest.TestCase):
    """Exercise the assessor with producer-shaped, plan-bound offline artifacts.

    This seam intentionally locks contract relationships, not incidental values: a legitimate
    future change to a registered packet/slot, its date-derived runbook filename, the complete
    runbook state-slot names, reviewed query bytes, producer top-level shape, plan-binding
    evidence, drop normalization, clock semantics, or the offline evidence contract should turn
    it red and force an explicit review.  Do not weaken these checks by hand-editing producer
    output; update the contract and its independent consumer decision first.
    """

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory(prefix="us_short_query_quality_producer_seam_")
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name).resolve()
        self.docs = self.root / "docs"
        self.state = self.root / "state" / "us_short"
        self.raw_web = self.root / "provider_samples" / "us_short_llm_theme_discovery_fetch_web"
        self.raw_x = self.root / "provider_samples" / "us_short_llm_theme_discovery_fetch_x"
        self.packet_path = self.docs / NEW_SOURCE_PACKET.name
        packet_payload = json.loads(NEW_SOURCE_PACKET.read_text(encoding="utf-8"))
        decision_date = packet_payload["probe_boundary"]["expected_decision_date"]
        self.assessment_path = self.docs / (
            f"us_short_soft_discovery_query_quality_probe_assessment_{decision_date}.json"
        )
        _write_json(
            self.packet_path,
            packet_payload,
        )
        self.packet = json.loads(self.packet_path.read_text(encoding="utf-8"))
        self.decision_date = self.packet["probe_boundary"]["expected_decision_date"]
        self.patches = [
            mock.patch.object(assess, "ROOT", self.root),
            # Both registry constants are patched so the new-slot registration remains explicit;
            # NEW_PACKET_PATH is the load-bearing branch for the current 20260815 schema.
            mock.patch.object(assess, "DEFAULT_PACKET_PATH", self.packet_path),
            mock.patch.object(assess, "NEW_PACKET_PATH", self.packet_path),
            mock.patch.object(probe_paths, "ROOT", self.root),
            mock.patch.object(probe_paths, "DOCS_DIR", self.docs),
            mock.patch.object(web, "ROOT", self.root),
            mock.patch.object(web, "STATE_DIR", self.state),
            mock.patch.object(web, "DEFAULT_RAW_ROOT", self.raw_web),
            mock.patch.object(web, "_gitignored", return_value=True),
            mock.patch.object(xfetch, "ROOT", self.root),
            mock.patch.object(xfetch, "STATE_DIR", self.state),
            mock.patch.object(xfetch, "DEFAULT_RAW_ROOT", self.raw_x),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def _instant(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

    def _derived_clocks(self) -> dict[str, datetime]:
        t0 = self._instant(self.packet["generated_at"])
        # No absolute fixture timestamps: every producer input and assertion derives from T0.
        delta_reserved = timedelta(minutes=1)
        delta_observed = timedelta(minutes=2)
        delta_fetched = timedelta(minutes=3)
        delta_assessment = timedelta(minutes=4)
        clocks = {
            "packet": t0,
            "plan": t0,
            "reserved": t0 + delta_reserved,
            "observed": t0 + delta_observed,
            "fetched": t0 + delta_fetched,
            "assessment": t0 + delta_fetched + delta_assessment,
        }
        self.assertLess(clocks["packet"], clocks["reserved"])
        self.assertLess(clocks["reserved"], clocks["observed"])
        self.assertLess(clocks["observed"], clocks["fetched"])
        self.assertLess(clocks["fetched"], web._cutoff(self.decision_date))
        self.assertLess(clocks["assessment"], web._cutoff(self.decision_date))
        return clocks

    @staticmethod
    def _web_rows(observed_at: datetime) -> list[dict[str, str]]:
        stamp = observed_at.isoformat()
        return [
            {
                "url": "https://seam.example/web/one",
                "title": "Power demand one",
                "content": "AAPL CEG VST power demand evidence.",
                "published_date": stamp,
            },
            {
                "url": "https://seam.example/web/two",
                "title": "Power demand two",
                "content": "Utility and data-center buildout evidence.",
                "published_date": stamp,
            },
            {
                "url": "https://seam.example/web/three",
                "title": "Power demand three",
                "content": "Grid equipment demand evidence.",
                "published_date": stamp,
            },
            {
                "url": "not-a-url",
                "title": "Producer drop",
                "content": "This row must be dropped by web normalization.",
                "published_date": stamp,
            },
        ]

    @staticmethod
    def _x_rows(observed_at: datetime) -> list[dict[str, str]]:
        stamp = observed_at.isoformat()
        return [
            {
                "url": "https://x.example/status/1",
                "title": "Power post one",
                "text": "AAPL CEG power demand.",
                "created_at": stamp,
                "_evidence_attestation": "provider_attested",
            },
            {
                "url": "https://x.example/status/2",
                "title": "Power post two",
                "text": "Utility buildout evidence.",
                "created_at": stamp,
                "_evidence_attestation": "provider_attested",
            },
            {
                "url": "https://x.example/status/3",
                "title": "Power post three",
                "text": "Grid equipment evidence.",
                "created_at": stamp,
                "_evidence_attestation": "provider_attested",
            },
            {
                "url": "https://x.example/status/4",
                "title": "Producer drop",
                "text": "An untrusted row must be dropped by X normalization.",
                "created_at": stamp,
                "_evidence_attestation": "unverified",
            },
        ]

    class _SearchClient:
        def __init__(self, rows):
            self.rows = rows
            self.calls: list[str] = []

        def search(self, query):
            self.calls.append(query)
            return copy.deepcopy(self.rows)

    class _DeepSeekClient:
        def __init__(self, text):
            self.text = text
            self.calls: list[dict[str, object]] = []

        def _create(self, **kwargs):
            self.calls.append(kwargs)
            response_payload = {
                "model": "deepseek-v4-flash",
                "choices": [{"message": {"content": self.text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                "system_fingerprint": "fp_fixture",
            }
            return SimpleNamespace(
                model=response_payload["model"],
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=self.text), finish_reason="stop",
                )],
                usage=response_payload["usage"],
                system_fingerprint=response_payload["system_fingerprint"],
                model_dump=lambda mode="json": copy.deepcopy(response_payload),
            )

        @property
        def chat(self):
            return SimpleNamespace(completions=SimpleNamespace(create=self._create))

    class _XClient:
        def __init__(self, rows, response):
            self.results = copy.deepcopy(rows)
            self.response = response
            self.calls: list[tuple[str, str]] = []

        def search(self, query, expected_decision_date):
            self.calls.append((query, expected_decision_date))
            return self.response

    @staticmethod
    def _noop_persist(_request, _value):
        return None

    def _web_llm_response(self, observed_at: datetime) -> str:
        source_id = web._source_id("https://seam.example/web/one")
        stamp = observed_at.isoformat()
        return json.dumps({
            "themes": [{
                "theme_id": "seam_web_single_source",
                "display_name": "Power demand",
                "summary": "Three members deliberately share one source.",
                "observed_at": stamp,
                "source_ref_ids": [source_id],
                "members": [
                    {"ticker": "AAPL", "source_ref_ids": [source_id]},
                    {"ticker": "CEG", "source_ref_ids": [source_id]},
                    {"ticker": "VST", "source_ref_ids": [source_id]},
                ],
                "semantic_assertions": [{
                    "basis": "shared_commercial_driver",
                    "basis_explanation": "Power demand reaches all three linked issuers.",
                    "common_driver": {
                        "driver_statement": "Power demand is increasing.",
                        "transmission_mechanism": "Load growth drives generation and infrastructure spending.",
                        "source_ref_ids": [source_id],
                    },
                    "member_links": [{
                        "ticker": ticker,
                        "role": "beneficiary",
                        "link_statement": "The issuer is linked to the common power-demand transmission.",
                        "source_ref_ids": [source_id],
                    } for ticker in ("AAPL", "CEG", "VST")],
                }],
            }],
        })

    def _x_response(self, observed_at: datetime) -> str:
        source_url = "https://x.example/status/1"
        stamp = observed_at.isoformat()
        return json.dumps({
            "themes": [{
                "theme_id": "seam_x_single_source",
                "display_name": "Power demand",
                "summary": "Three members deliberately share one source.",
                "observed_at": stamp,
                "source_urls": [source_url],
                "members": [
                    {"ticker": "AAPL", "source_urls": [source_url]},
                    {"ticker": "CEG", "source_urls": [source_url]},
                    {"ticker": "VST", "source_urls": [source_url]},
                ],
                "semantic_assertions": [{
                    "basis": "shared_commercial_driver",
                    "basis_explanation": "Power demand reaches all three linked issuers.",
                    "common_driver": {
                        "driver_statement": "Power demand is increasing.",
                        "transmission_mechanism": "Load growth drives generation and infrastructure spending.",
                        "source_urls": [source_url],
                    },
                    "member_links": [{
                        "ticker": ticker,
                        "role": "beneficiary",
                        "link_statement": "The issuer is linked to the common power-demand transmission.",
                        "source_urls": [source_url],
                    } for ticker in ("AAPL", "CEG", "VST")],
                }],
            }],
        })

    def _assert_producer_shape(self, lane, discovery, receipt, plan_document):
        self.assertEqual(set(discovery), PRODUCTION_DISCOVERY_KEYS)
        expected_receipt_keys = (
            PRODUCTION_WEB_RECEIPT_KEYS if lane == "web" else PRODUCTION_X_RECEIPT_KEYS
        )
        self.assertEqual(set(receipt), expected_receipt_keys)
        self.assertRegex(discovery["input_sha256"], r"^[0-9a-f]{64}$")
        provider = "web" if lane == "web" else "xai"
        expected_binding = query_plan.build_stage1_plan_binding(
            plan_document, provider=provider,
        )
        self.assertEqual(receipt["plan_binding"], expected_binding)
        self.assertTrue(receipt["drop_ledger"])
        self.assertTrue(discovery["themes"])
        for theme in discovery["themes"]:
            self.assertEqual(len(theme["source_ref_ids"]), 1)
            self.assertEqual(
                len({source_id for member in theme["members"] for source_id in member["source_ref_ids"]}),
                1,
            )
        self.assertEqual(receipt["summary"]["dropped_result_count"], len(receipt["drop_ledger"]))

    def test_real_parent_plan_budget_fetch_publish_and_assessment_chain(self):
        clocks = self._derived_clocks()
        plan_payload = parent_plan_builder.build_parent_plan_from_reviewed_policy(
            decision_date=self.decision_date,
            generated_at=clocks["plan"].isoformat(),
        )
        plan_path = query_plan.default_parent_plan_path(
            self.decision_date, plan_payload["plan_identity"], state_dir=self.state,
        )
        query_plan.write_parent_plan(
            plan_payload,
            plan_path,
            state_dir=self.state,
            root=self.root,
            gitignored=lambda _path: True,
        )
        plan_document, plan_sha256, plan_relative_path = query_plan.read_parent_plan(
            plan_path,
            root=self.root,
            state_dir=self.state,
            require_reviewed_policy=True,
        )
        self.assertIsInstance(plan_document, query_plan.ParentPlanDocument)
        self.assertEqual(plan_document.artifact_sha256, plan_sha256)
        self.assertEqual(plan_document.artifact_path, plan_relative_path)
        self.assertEqual(plan_document["generated_at"], clocks["plan"].isoformat())

        web_queries, web_records, _web_binding = query_plan.resolve_stage1_plan_binding(
            plan_document, provider="web",
        )
        x_queries, x_records, _x_binding = query_plan.resolve_stage1_plan_binding(
            plan_document, provider="xai",
        )
        self.assertEqual(web_queries, x_queries)
        self.assertEqual(web_records, x_records)

        web_rows = self._web_rows(clocks["observed"])
        x_rows = self._x_rows(clocks["observed"])
        gateway_web_search = self._SearchClient(web_rows)
        gateway_web_regroup = self._DeepSeekClient(
            self._web_llm_response(clocks["observed"]),
        )
        gateway_x = self._XClient(x_rows, self._x_response(clocks["observed"]))
        stage2_chunks = [(index, [{"chunk": index}]) for index in range(4)]
        with (
            mock.patch.object(plan_budget, "_stamp", return_value=clocks["reserved"].isoformat()),
            # O2: a synchronous seam should leave no in-flight row.  If a legitimate future
            # lifecycle starts consulting owner liveness here, this red test requires an explicit
            # injected clock/contract decision; it must not silently accept stale frozen heartbeats.
            mock.patch.object(
                plan_budget, "_owner_is_alive", wraps=plan_budget._owner_is_alive,
            ) as owner_alive,
        ):
            web_budget = plan_budget.reserve_plan_budget(
                plan_document,
                state_dir=self.state,
                root=self.root,
                gitignored=lambda _path: True,
                expected_decision_date=self.decision_date,
                providers=("web",),
            )
            x_budget = plan_budget.reserve_plan_budget(
                plan_document,
                state_dir=self.state,
                root=self.root,
                gitignored=lambda _path: True,
                expected_decision_date=self.decision_date,
                providers=("xai",),
            )
            web_gateway = web.paid_gateway.PaidDispatchGateway(
                web_budget, parent_plan=plan_document,
            )
            x_gateway = xfetch.paid_gateway.PaidDispatchGateway(
                x_budget, parent_plan=plan_document,
            )
            web_stage1 = web_gateway.dispatch_web_search_all(
                gateway_web_search,
                web_records,
                persist_response=self._noop_persist,
            )
            web_stage2 = web_gateway.dispatch_web_regroup_all(
                gateway_web_regroup,
                expected_decision_date=self.decision_date,
                chunks=stage2_chunks,
                prompt_builder=lambda _date, _rows: "offline seam regroup",
                persist_response=self._noop_persist,
            )
            x_stage1 = x_gateway.dispatch_x_search_all(
                gateway_x,
                x_records,
                expected_decision_date=self.decision_date,
                persist_response=self._noop_persist,
            )
        self.assertIsNone(web_stage1.stop_error)
        self.assertIsNone(web_stage2.stop_error)
        self.assertIsNone(x_stage1.stop_error)
        self.assertEqual(len(web_stage1.items), 4)
        self.assertEqual(len(web_stage2.items), 4)
        self.assertEqual(len(x_stage1.items), 4)
        # With all gateway calls completing synchronously, the stale-owner branch is not part of
        # this chain.  This is the explicit O2 confirmation, not an assumption about the code.
        self.assertEqual(owner_alive.call_count, 0)

        web_discovery, web_receipt, _web_summary = web.run_web_fetch(
            queries=None,
            parent_plan=plan_document,
            expected_decision_date=self.decision_date,
            generated_at=clocks["fetched"].isoformat(),
            search_client=self._SearchClient(web_rows),
            deepseek_client=self._DeepSeekClient(self._web_llm_response(clocks["observed"])),
            raw_root=self.raw_web,
        )
        x_discovery, x_receipt, _x_summary = xfetch.run_x_fetch(
            queries=None,
            parent_plan=plan_document,
            expected_decision_date=self.decision_date,
            generated_at=clocks["fetched"].isoformat(),
            x_client=self._XClient(x_rows, self._x_response(clocks["observed"])),
            raw_root=self.raw_x,
        )
        self._assert_producer_shape("web", web_discovery, web_receipt, plan_document)
        self._assert_producer_shape("x", x_discovery, x_receipt, plan_document)
        for receipt, discovery in ((web_receipt, web_discovery), (x_receipt, x_discovery)):
            source_times = {
                row["source_id"]: self._instant(row["observed_at"])
                for row in receipt["source_refs"]
            }
            fetched_times = [self._instant(row["fetched_at"]) for row in receipt["source_refs"]]
            self.assertTrue(fetched_times)
            self.assertTrue(any(observed < fetched_times[0] for observed in source_times.values()))
            for theme in discovery["themes"]:
                bound = [source_times[source_id] for source_id in theme["source_ref_ids"]]
                self.assertEqual(self._instant(theme["observed_at"]), max(bound))
                self.assertTrue(all(
                    source_times[source_id] <= fetched_times[0]
                    for source_id in theme["source_ref_ids"]
                ))

        web.publish_decision_pair(
            web_discovery,
            web.default_discovery_path(self.decision_date),
            web.default_discovery_path(self.decision_date),
            web_receipt,
            web.default_receipt_path(self.decision_date),
            web.default_receipt_path(self.decision_date),
        )
        web.publish_decision_pair(
            x_discovery,
            xfetch.default_discovery_path(self.decision_date),
            xfetch.default_discovery_path(self.decision_date),
            x_receipt,
            xfetch.default_receipt_path(self.decision_date),
            xfetch.default_receipt_path(self.decision_date),
        )

        summary = assess.run_assessment(
            packet_path=self.packet_path,
            assessment_path=self.assessment_path,
            generated_at=clocks["assessment"].isoformat(),
        )
        self.assertEqual(summary["status"], "assessment_written_or_reused")
        assessment = json.loads(self.assessment_path.read_text(encoding="utf-8"))
        self.assertEqual(
            assessment["verdict"],
            self.packet["preregistered_evaluation"]["inconclusive_verdict"],
        )
        # O4 is an intentional coverage boundary: the offline contract necessarily makes this
        # verdict inconclusive, so pass/revise mapping is not claimed by this seam.
        self.assertEqual(
            set(assessment["execution_evidence"]["inconclusive_reasons"]),
            OFFLINE_INCONCLUSIVE_REASONS,
        )
        self.assertEqual(
            set(assessment["input_bindings"]),
            {"web_discovery", "web_receipt", "x_discovery", "x_receipt", "web", "xai"},
        )
        threshold = self.packet["preregistered_evaluation"]["per_lane_quality_thresholds"][
            "minimum_member_bound_source_ratio"
        ]
        for lane in ("web", "x"):
            metrics = assessment["lane_assessments"][lane]
            self.assertLess(metrics["member_bound_source_ratio"], threshold)
            self.assertIn("member_bound_source_ratio_below_threshold", metrics["quality_failure_reasons"])

        for provider, receipt, discovery in (
            ("web", web_receipt, web_discovery),
            ("xai", x_receipt, x_discovery),
        ):
            ledger_path = plan_budget.default_plan_budget_path(
                provider, self.decision_date, state_dir=self.state,
            )
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(set(ledger), PRODUCTION_LEDGER_KEYS)
            self.assertTrue(all(row["status"] == "complete" for row in ledger["dispatches"]))
            self.assertFalse(ledger["recovery_events"])
            reserved = self._instant(ledger["first_reserved_at"])
            self.assertLessEqual(clocks["packet"], reserved)
            for source in receipt["source_refs"]:
                fetched = self._instant(source["fetched_at"])
                self.assertLessEqual(reserved, fetched)
                self.assertLessEqual(self._instant(source["observed_at"]), fetched)
                self.assertLessEqual(fetched, self._instant(discovery["generated_at"]))
            self.assertLess(self._instant(receipt["generated_at"]), web._cutoff(self.decision_date))
        self.assertLess(self._instant(assessment["generated_at"]), web._cutoff(self.decision_date))

    def test_runbook_state_filenames_are_derived_from_producer_slots(self):
        """O3: every producer state slot must appear in the runbook under its full name."""
        runbook_path = self._runbook_path()
        self.assertTrue(runbook_path.is_file(), f"registered runbook is missing: {runbook_path}")
        runbook = runbook_path.read_text(encoding="utf-8").replace("\\", "/")
        expected_names = {
            web.default_discovery_path(self.decision_date).name,
            web.default_receipt_path(self.decision_date).name,
            xfetch.default_discovery_path(self.decision_date).name,
            xfetch.default_receipt_path(self.decision_date).name,
            plan_budget.default_plan_budget_path(
                "web", self.decision_date, state_dir=self.state,
            ).name,
            plan_budget.default_plan_budget_path(
                "xai", self.decision_date, state_dir=self.state,
            ).name,
        }
        state_names = {
            raw.rstrip(".,`)")
            for raw in re.findall(r"state/us_short/([^\s`|)]+\.json)", runbook)
        }
        parent_prefix = f"us_short_llm_theme_discovery_query_plan_parent_{self.decision_date}_"
        for name in state_names:
            if name.startswith(parent_prefix):
                self.assertRegex(name, rf"^{re.escape(parent_prefix)}<[^>]+>\.json$")
            else:
                self.assertIn(name, expected_names)
        self.assertTrue(state_names, "runbook must contain at least one explicit state filename")
        # Required R1: this is deliberately bidirectional.  A runbook that only mentions a web
        # slot, or abbreviates an X/plan slot with `...`, must fail instead of silently leaving a
        # producer output undocumented.  The full-name requirement also makes a wrong-vendor
        # mutation red without teaching the parser to guess what an ellipsis meant.
        self.assertTrue(
            expected_names <= state_names,
            f"runbook must list every producer slot by full filename; missing={sorted(expected_names - state_names)}",
        )
        self.assertNotRegex(
            runbook,
            rf"us_short_llm_theme_discovery_(?:tavily|deepseek|xai)_{re.escape(self.decision_date)}_budget\.json",
        )

    def _runbook_path(self, decision_date=None):
        """Keep the runbook leg on the same decision-date slot as the packet under test."""
        slot = self.decision_date if decision_date is None else decision_date
        return REPO_ROOT / "docs" / f"us_short_soft_discovery_probe_{slot}_runbook.md"

    def test_runbook_path_tracks_packet_decision_date(self):
        """Optional O1: a future packet slot must not keep reading the 20260815 runbook."""
        current = datetime.strptime(self.decision_date, "%Y%m%d").date()
        alternate = (current + timedelta(days=1)).strftime("%Y%m%d")
        self.assertEqual(
            self._runbook_path(alternate).name,
            f"us_short_soft_discovery_probe_{alternate}_runbook.md",
        )


if __name__ == "__main__":
    unittest.main()
