from __future__ import annotations

import copy
import hashlib
import inspect
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest import mock

from runners import us_short_llm_theme_discovery as ingest
from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from runners import us_short_llm_theme_discovery_merge as merge
from runners import us_short_provisional_theme_validate as validate
from runners import us_short_universe_fetch as universe
from runners import us_short_weekly_capstone as capstone
from runners import us_short_weekly_capstone_stages as stages
from runners import us_short_weekly_capstone_soft_discovery as soft
from runners.us_short_discovery_publish_policy import DiscoveryPublishPolicyError
from tests.provider.test_us_short_batch5_full_universe_momentum_producer import (
    _ALL_ELIGIBLE,
    _candidate_artifact,
)
from tests.provider.test_us_short_batch5_full_universe_theme_producer import _classification_packet
from tests.provider.us_short_private_test_root import temporary_provider_directory


ROOT = Path(__file__).resolve().parents[2]
DECISION_DATE = "20260615"
GENERATED_AT = "2026-06-15T11:00:00Z"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _source_packets(
    *, empty: bool = False, variant: str = "power", include_merge_drop: bool = False,
) -> tuple[dict, dict, dict, dict]:
    web_row = {
        "url": f"https://web.example/{variant}",
        "title": "Power",
        "content": "AAPL MSFT JPM GOOG",
        "published_date": "2026-06-12T11:00:00Z",
    }
    x_row = {
        "url": f"https://x.example/{variant}",
        "title": "Power",
        "text": "AAPL MSFT JPM GOOG",
        "created_at": "2026-06-12T11:05:00Z",
    }
    members = ["AAPL", "MSFT", "JPM", "GOOG"]
    web_ref = web._source_id(web_row["url"])
    x_ref = xfetch._source_id(x_row["url"])

    def response(ref: str) -> str:
        themes = [] if empty else [{
            "theme_id": "power_demand",
            "display_name": "Power demand",
            "summary": "Cross-industry power demand.",
            "observed_at": "2026-06-12T12:00:00Z",
            "source_ref_ids": [ref],
            "members": [{"ticker": ticker, "source_ref_ids": [ref]} for ticker in members],
        }]
        return json.dumps({"themes": themes})

    web_artifact, web_receipt, _ = web.build_web_fetch_packet(
        queries=["power"],
        search_results=[web_row],
        llm_response=response(web_ref),
        expected_decision_date=DECISION_DATE,
        generated_at=GENERATED_AT,
    )
    x_artifact, x_receipt, _ = xfetch.build_x_fetch_packet(
        queries=["power"],
        results=[x_row],
        grok_response=response(x_ref),
        expected_decision_date=DECISION_DATE,
        generated_at=GENERATED_AT,
    )
    if include_merge_drop:
        web_artifact["themes"][0]["theme_id"] = "stale_power"
        web_artifact["themes"][0]["observed_at"] = "2026-06-12T10:00:00Z"
        web_receipt["discovery_artifact_sha256"] = web._discovery_evidence_hash(web_artifact)
    return web_artifact, web_receipt, x_artifact, x_receipt


class WeeklyCapstoneSoftDiscoveryStageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = temporary_provider_directory(ROOT)
        self.temp_root = Path(self.tempdir.__enter__())
        self.state_dir = self.temp_root / "state" / "us_short"
        self.state_dir.mkdir(parents=True)
        self.patches = [
            mock.patch.object(web, "STATE_DIR", self.state_dir),
            mock.patch.object(xfetch, "STATE_DIR", self.state_dir),
            mock.patch.object(ingest, "STATE_US_SHORT_DIR", self.state_dir),
            mock.patch.object(validate, "STATE_DIR", self.state_dir),
            mock.patch.object(universe, "CANDIDATE_LIST_DIR", self.state_dir),
            mock.patch.object(
                capstone,
                "_decision_lock_path",
                side_effect=lambda ctx: (
                    Path(ctx.state_dir) / "_transaction_locks" / f"{ctx.decision_date}.lock"
                ).resolve(),
            ),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        self.tempdir.__exit__(None, None, None)

    def _ctx(self, *, enabled: bool):
        ctx = capstone.resolve_capstone_context(
            now_et=datetime(2026, 6, 15, 7, 0, 0),
            private_root=self.state_dir,
            batch4_template_path=self.state_dir / "template.json",
            account_state_path=self.state_dir / "account.json",
            state_dir=self.state_dir,
            sample_root=ROOT,
        )
        return replace(ctx, soft_discovery_enabled=enabled)

    def _bridge_stage(self) -> capstone.Stage:
        def outputs(run_ctx):
            output_root = run_ctx.official_output_root or run_ctx.private_root
            return [
                output_root / "weekly_private" / run_ctx.decision_date / "weekly_report.md",
                output_root / "weekly_private" / run_ctx.decision_date / "action_table.csv",
                output_root / "runs_private" / run_ctx.decision_date / "machine_record.json",
            ]

        def run(run_ctx):
            paths = outputs(run_ctx)
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("terminal", encoding="utf-8")
            return {
                "batch4_run": {
                    "emitted": True,
                    "output_paths": {
                        "weekly_report_path": str(paths[0]),
                        "action_table_path": str(paths[1]),
                        "machine_record_path": str(paths[2]),
                    },
                },
            }

        return capstone.Stage("weekly_bridge", False, lambda _ctx: [], outputs, run)

    def _run_terminal_pipeline(self, soft_run, *, soft_inputs=None, soft_outputs=None, now_et=None) -> dict:
        return capstone.run_weekly_capstone(
            now_et=now_et or datetime(2026, 6, 15, 7, 0, 0),
            private_root=self.state_dir / "private",
            batch4_template_path=self.state_dir / "template.json",
            account_state_path=self.state_dir / "account.json",
            dry_run=False,
            confirm_user_authorization=True,
            stages=[
                capstone.Stage(
                    "soft_discovery", False,
                    soft_inputs or (lambda _ctx: []),
                    soft_outputs or (lambda run_ctx: [run_ctx.soft_discovery_receipt_path]),
                    soft_run,
                    failure_policy="zero_effect", output_policy="optional",
                    checkpoint_policy="optional_result_only",
                    failure_handler=capstone._degrade_soft_discovery_boundary,
                ),
                self._bridge_stage(),
            ],
            state_dir=self.state_dir,
            sample_root=ROOT,
            soft_discovery_enabled=True,
        )

    def _write_supporting_inputs(self, ctx) -> None:
        _write_json(ctx.candidate_path, _candidate_artifact(_ALL_ELIGIBLE))
        _write_json(
            ctx.classification_packet_path,
            _classification_packet({
                "AAPL": "10", "MSFT": "10", "GOOG": "10", "JPM": "20", "AMZN": "20",
            }),
        )

    def _write_merge_pair(
        self, ctx, *, empty: bool = False, variant: str = "power", replace_existing: bool = False,
        include_merge_drop: bool = False,
    ) -> tuple[dict, dict]:
        web_artifact, web_receipt, x_artifact, x_receipt = _source_packets(
            empty=empty, variant=variant, include_merge_drop=include_merge_drop,
        )
        merged, manifest = merge.merge_web_x_discovery(
            web_artifact=web_artifact,
            web_receipt=web_receipt,
            x_artifact=x_artifact,
            x_receipt=x_receipt,
            expected_decision_date=ctx.decision_date,
            generated_at=ctx.generated_at,
        )
        pairs = (
            (
                web_artifact,
                soft.rerooted_default_path(
                    web.default_discovery_path, ctx.decision_date, state_dir=ctx.state_dir,
                ),
                web.default_discovery_path(ctx.decision_date),
                web_receipt,
                soft.rerooted_default_path(
                    web.default_receipt_path, ctx.decision_date, state_dir=ctx.state_dir,
                ),
                web.default_receipt_path(ctx.decision_date),
            ),
            (
                x_artifact,
                soft.rerooted_default_path(
                    xfetch.default_discovery_path, ctx.decision_date, state_dir=ctx.state_dir,
                ),
                xfetch.default_discovery_path(ctx.decision_date),
                x_receipt,
                soft.rerooted_default_path(
                    xfetch.default_receipt_path, ctx.decision_date, state_dir=ctx.state_dir,
                ),
                xfetch.default_receipt_path(ctx.decision_date),
            ),
            (
                merged,
                ctx.soft_discovery_merge_path,
                merge.default_discovery_path(ctx.decision_date),
                manifest,
                ctx.soft_discovery_merge_manifest_path,
                merge.default_manifest_path(ctx.decision_date),
            ),
        )
        for first, first_path, first_expected, second, second_path, second_expected in pairs:
            if replace_existing:
                _write_json(first_path, first)
                _write_json(second_path, second)
            else:
                web.publish_decision_pair(
                    first, first_path, first_expected, second, second_path, second_expected,
                )
        return merged, manifest

    def test_disabled_is_inert_and_default_one_click_pipeline_includes_soft_discovery(self):
        ctx = self._ctx(enabled=False)
        before = sorted(path.relative_to(self.state_dir) for path in self.state_dir.rglob("*") if path.is_file())
        result = stages.run_soft_discovery(ctx)
        after = sorted(path.relative_to(self.state_dir) for path in self.state_dir.rglob("*") if path.is_file())
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(after, before)
        names = [stage.name for stage in capstone.default_pipeline()]
        self.assertEqual(names[names.index("sic_fetch") + 1], "soft_discovery")
        self.assertFalse(capstone.default_pipeline()[names.index("soft_discovery")].gated)
        self.assertNotIn(
            "soft_discovery",
            [stage.name for stage in capstone.default_pipeline(include_soft_discovery=False)],
        )
        self.assertIs(
            inspect.signature(capstone.default_pipeline).parameters[
                "include_soft_discovery"
            ].default,
            True,
        )
        self.assertIs(
            inspect.signature(capstone.resolve_capstone_context).parameters[
                "soft_discovery_enabled"
            ].default,
            True,
        )
        self.assertIs(
            inspect.signature(capstone.run_weekly_capstone).parameters[
                "soft_discovery_enabled"
            ].default,
            True,
        )

    def test_cli_one_click_defaults_soft_discovery_on_without_enable_flag(self):
        argv = [
            "--now-et", "2026-06-15T07:00:00",
            "--batch4-template-path", str(self.state_dir / "template.json"),
            "--account-state-path", str(self.state_dir / "account.json"),
        ]
        with mock.patch.object(capstone, "run_weekly_capstone", return_value={}) as run:
            self.assertEqual(capstone.main(argv), 0)
        self.assertIs(run.call_args.kwargs["soft_discovery_enabled"], True)
        self.assertIs(run.call_args.kwargs["theme_soft_boost_enabled"], True)
        with mock.patch.object(capstone, "run_weekly_capstone", return_value={}) as run:
            self.assertEqual(capstone.main([*argv, "--disable-soft-discovery"]), 0)
        self.assertIs(run.call_args.kwargs["soft_discovery_enabled"], False)
        with mock.patch.object(capstone, "run_weekly_capstone", return_value={}) as run:
            self.assertEqual(capstone.main([*argv, "--disable-theme-soft-boost"]), 0)
        self.assertIs(run.call_args.kwargs["theme_soft_boost_enabled"], False)

    def test_public_pipeline_switch_rejects_non_boolean_values(self):
        for value in (0, 1, "false", "true", None):
            with self.subTest(surface="default_pipeline", value=value):
                with self.assertRaisesRegex(capstone.WeeklyCapstoneError, "exact bool"):
                    capstone.default_pipeline(include_soft_discovery=value)
            with self.subTest(surface="resolve_capstone_context", value=value):
                with self.assertRaisesRegex(capstone.WeeklyCapstoneError, "exact bool"):
                    capstone.resolve_capstone_context(
                        now_et=datetime(2026, 6, 15, 7, 0, 0),
                        private_root=self.state_dir / "private",
                        batch4_template_path=self.state_dir / "template.json",
                        account_state_path=self.state_dir / "account.json",
                        soft_discovery_enabled=value,
                        state_dir=self.state_dir,
                    )
            with self.subTest(surface="resolve_capstone_context.boost", value=value):
                with self.assertRaisesRegex(capstone.WeeklyCapstoneError, "exact bool"):
                    capstone.resolve_capstone_context(
                        now_et=datetime(2026, 6, 15, 7, 0, 0),
                        private_root=self.state_dir / "private",
                        batch4_template_path=self.state_dir / "template.json",
                        account_state_path=self.state_dir / "account.json",
                        theme_soft_boost_enabled=value,
                        state_dir=self.state_dir,
                    )

    def test_all_five_states_are_distinct_and_invalid_is_not_valid_empty(self):
        disabled = stages.run_soft_discovery(self._ctx(enabled=False))
        self.assertEqual(disabled["status"], "disabled")

        unavailable_ctx = self._ctx(enabled=True)
        unavailable = stages.run_soft_discovery(unavailable_ctx)
        self.assertEqual(unavailable["status"], "upstream_unavailable")

        for empty, expected in ((False, "valid_nonempty"), (True, "valid_empty")):
            with self.subTest(expected=expected), temporary_provider_directory(ROOT) as td:
                state_dir = Path(td) / "state" / "us_short"
                state_dir.mkdir(parents=True)
                with (
                    mock.patch.object(web, "STATE_DIR", state_dir),
                    mock.patch.object(xfetch, "STATE_DIR", state_dir),
                    mock.patch.object(ingest, "STATE_US_SHORT_DIR", state_dir),
                    mock.patch.object(validate, "STATE_DIR", state_dir),
                    mock.patch.object(universe, "CANDIDATE_LIST_DIR", state_dir),
                ):
                    ctx = replace(self._ctx(enabled=True), state_dir=state_dir)
                    self._write_supporting_inputs(ctx)
                    self._write_merge_pair(ctx, empty=empty)
                    result = stages.run_soft_discovery(ctx)
                    self.assertEqual(result["status"], expected)
                    self.assertEqual(result["validated_theme_count"] > 0, not empty)

        with temporary_provider_directory(ROOT) as td:
            state_dir = Path(td) / "state" / "us_short"
            state_dir.mkdir(parents=True)
            with (
                mock.patch.object(web, "STATE_DIR", state_dir),
                mock.patch.object(xfetch, "STATE_DIR", state_dir),
                mock.patch.object(ingest, "STATE_US_SHORT_DIR", state_dir),
                mock.patch.object(validate, "STATE_DIR", state_dir),
                mock.patch.object(universe, "CANDIDATE_LIST_DIR", state_dir),
            ):
                invalid_ctx = replace(self._ctx(enabled=True), state_dir=state_dir)
                self._write_supporting_inputs(invalid_ctx)
                _write_json(invalid_ctx.soft_discovery_merge_path, {"bad": "packet"})
                _write_json(invalid_ctx.soft_discovery_merge_manifest_path, {"bad": "manifest"})
                invalid = stages.run_soft_discovery(invalid_ctx)
                self.assertEqual(invalid["status"], "invalid_evidence")
                self.assertNotEqual(invalid["status"], "valid_empty")

    def test_valid_retry_is_byte_equivalent_and_receipt_binds_all_artifacts(self):
        ctx = self._ctx(enabled=True)
        self._write_supporting_inputs(ctx)
        self._write_merge_pair(ctx)
        first = stages.run_soft_discovery(ctx)
        paths = (
            ctx.soft_discovery_ingest_path,
            ctx.soft_discovery_validation_path,
            ctx.soft_discovery_receipt_path,
        )
        before = tuple(path.read_bytes() for path in paths)
        retry = stages.run_soft_discovery(replace(ctx, generated_at="2026-06-15T11:05:00+00:00"))
        self.assertEqual(tuple(path.read_bytes() for path in paths), before)
        self.assertEqual(retry, first)
        for key in ("merge", "merge_manifest", "ingest", "validation"):
            self.assertRegex(first["artifacts"][key]["sha256"], r"^[0-9a-f]{64}$")

    def test_date_digest_and_manifest_binding_tamper_are_rejected_without_partial_publish(self):
        mutations = ("date", "digest", "manifest_binding", "raw_path")
        for mutation in mutations:
            with self.subTest(mutation=mutation), temporary_provider_directory(ROOT) as td:
                state_dir = Path(td) / "state" / "us_short"
                state_dir.mkdir(parents=True)
                with (
                    mock.patch.object(web, "STATE_DIR", state_dir),
                    mock.patch.object(xfetch, "STATE_DIR", state_dir),
                    mock.patch.object(ingest, "STATE_US_SHORT_DIR", state_dir),
                    mock.patch.object(validate, "STATE_DIR", state_dir),
                    mock.patch.object(universe, "CANDIDATE_LIST_DIR", state_dir),
                ):
                    ctx = replace(self._ctx(enabled=True), state_dir=state_dir)
                    self._write_supporting_inputs(ctx)
                    merged, manifest = self._write_merge_pair(ctx)
                    if mutation == "date":
                        merged["decision_clock"]["expected_decision_date"] = "20260616"
                    elif mutation == "digest":
                        merged["input_sha256"] = "f" * 64
                    elif mutation == "manifest_binding":
                        manifest["themes"][0]["members"][0]["source_ref_ids"] = []
                    else:
                        ref = manifest["source_refs"][0]
                        time_key = "published_at" if ref["source_type"] == "web" else "created_at"
                        raw_payload = {
                            "source_id": ref["source_id"],
                            "source_type": ref["source_type"],
                            "canonical_locator": ref["canonical_locator"],
                            time_key: ref["observed_at"],
                        }
                        wrong_raw = Path(td) / "wrong_decision_date" / "wrong_source.json"
                        _write_json(wrong_raw, raw_payload)
                        ref["raw_receipt_ref"] = wrong_raw.resolve().relative_to(ROOT.resolve()).as_posix()
                        ref["raw_receipt_gitignored"] = True
                        ref["content_sha256"] = merge._sha(raw_payload)
                    _write_json(ctx.soft_discovery_merge_path, merged)
                    _write_json(ctx.soft_discovery_merge_manifest_path, manifest)

                    result = stages.run_soft_discovery(ctx)
                    self.assertEqual(result["status"], "invalid_evidence")
                    self.assertFalse(ctx.soft_discovery_ingest_path.exists())
                    self.assertFalse(ctx.soft_discovery_validation_path.exists())
                    self.assertTrue(ctx.soft_discovery_receipt_path.is_file())
                    self.assertEqual(
                        list(state_dir.glob(f".{ctx.soft_discovery_receipt_path.name}.*")), [],
                    )

    def test_existing_clock_drift_cannot_create_receipt_to_actual_artifact_digest_split(self):
        ctx = self._ctx(enabled=True)
        self._write_supporting_inputs(ctx)
        merged, manifest = self._write_merge_pair(ctx)
        web_artifact, web_receipt, x_artifact, x_receipt = _source_packets()
        ingest_input = merge.validate_merged_packet(
            merged,
            manifest,
            expected_decision_date=ctx.decision_date,
            upstream_pairs={
                "web": (web_artifact, web_receipt),
                "x": (x_artifact, x_receipt),
            },
        )
        mismatched_clock_artifact = ingest.normalize_discovery_payload(
            ingest_input,
            expected_decision_date=ctx.decision_date,
            generated_at="2026-06-15T11:01:00Z",
        )
        _write_json(ctx.soft_discovery_ingest_path, mismatched_clock_artifact)
        frozen = ctx.soft_discovery_ingest_path.read_bytes()
        result = stages.run_soft_discovery(ctx)
        self.assertEqual(result["status"], "invalid_evidence")
        self.assertEqual(result["reason_code"], "SOFT_DISCOVERY_IMMUTABLE_CONFLICT")
        self.assertEqual(ctx.soft_discovery_ingest_path.read_bytes(), frozen)
        self.assertFalse(ctx.soft_discovery_validation_path.exists())
        self.assertFalse(ctx.soft_discovery_receipt_path.exists())

    def test_reused_artifact_digest_records_actual_frozen_file_bytes(self):
        ctx = self._ctx(enabled=True)
        self._write_supporting_inputs(ctx)
        self._write_merge_pair(ctx)
        first = stages.run_soft_discovery(ctx)
        self.assertEqual(first["status"], "valid_nonempty")
        ctx.soft_discovery_receipt_path.unlink()
        ingest_payload = json.loads(ctx.soft_discovery_ingest_path.read_text(encoding="utf-8"))
        ctx.soft_discovery_ingest_path.write_text(
            json.dumps(ingest_payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        frozen_sha = hashlib.sha256(ctx.soft_discovery_ingest_path.read_bytes()).hexdigest()

        result = stages.run_soft_discovery(ctx)

        self.assertEqual(result["status"], "valid_nonempty")
        self.assertEqual(result["artifacts"]["ingest"]["sha256"], frozen_sha)

    def _assert_conflict_transition(self, initial: str, final: str):
        ctx = self._ctx(enabled=True)
        self._write_supporting_inputs(ctx)
        if initial == "unavailable":
            first = stages.run_soft_discovery(ctx)
        elif initial == "invalid":
            _write_json(ctx.soft_discovery_merge_path, {"bad": "packet"})
            _write_json(ctx.soft_discovery_merge_manifest_path, {"bad": "manifest"})
            first = stages.run_soft_discovery(ctx)
        else:
            self._write_merge_pair(ctx)
            first = stages.run_soft_discovery(ctx)
        self.assertIn(first["status"], {"upstream_unavailable", "invalid_evidence", "valid_nonempty"})
        frozen = {
            path: path.read_bytes()
            for path in (
                ctx.soft_discovery_receipt_path,
                ctx.soft_discovery_ingest_path,
                ctx.soft_discovery_validation_path,
            )
            if path.is_file()
        }

        if initial == "invalid":
            ctx.soft_discovery_merge_path.unlink()
            ctx.soft_discovery_merge_manifest_path.unlink()
        if final == "valid":
            self._write_merge_pair(ctx, replace_existing=initial == "valid")
        elif final == "invalid":
            _write_json(ctx.soft_discovery_merge_path, {"bad": "packet"})
            _write_json(ctx.soft_discovery_merge_manifest_path, {"bad": "manifest"})
        elif final == "unavailable":
            ctx.soft_discovery_merge_path.unlink(missing_ok=True)
            ctx.soft_discovery_merge_manifest_path.unlink(missing_ok=True)
        elif final == "replaced_valid":
            self._write_merge_pair(ctx, variant="nuclear", replace_existing=True)
        else:
            self.fail(f"unknown transition target: {final}")

        result = stages.run_soft_discovery(ctx)
        self.assertEqual(result["status"], "invalid_evidence")
        self.assertEqual(result["reason_code"], "SOFT_DISCOVERY_IMMUTABLE_CONFLICT")
        self.assertEqual(result["validated_theme_count"], 0)
        self.assertEqual(result["boostable_ticker_count"], 0)
        conflict_receipts = list(self.state_dir.glob(
            f"us_short_provisional_theme_stage_receipt_{ctx.decision_date}_conflict_*.json"
        ))
        self.assertEqual(len(conflict_receipts), 1)
        self.assertEqual(json.loads(conflict_receipts[0].read_text(encoding="utf-8")), result)
        for group in ("artifacts",):
            for row in result[group].values():
                path = ROOT / row["path"] if row["path"] is not None else None
                if row["sha256"] is None:
                    self.assertTrue(path is None or not path.is_file())
                else:
                    self.assertTrue(path.is_file())
                    self.assertEqual(
                        row["sha256"],
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
        for path, content in frozen.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(
            [path for path in self.state_dir.rglob("*") if path.is_file() and path.name.startswith(".")],
            [],
        )
        return ctx

    def test_all_same_day_status_transitions_reach_terminal_with_bound_conflict_receipts(self):
        transitions = (
            ("unavailable", "valid"),
            ("invalid", "valid"),
            ("unavailable", "invalid"),
            ("valid", "unavailable"),
            ("valid", "replaced_valid"),
        )
        for index, (initial, final) in enumerate(transitions):
            with self.subTest(initial=initial, final=final):
                if index:
                    self.tearDown()
                    self.setUp()
                ctx = self._assert_conflict_transition(initial, final)

                def bridge_outputs(run_ctx):
                    output_root = run_ctx.official_output_root or run_ctx.private_root
                    return [
                        output_root / "weekly_private" / run_ctx.decision_date / "weekly_report.md",
                        output_root / "weekly_private" / run_ctx.decision_date / "action_table.csv",
                        output_root / "runs_private" / run_ctx.decision_date / "machine_record.json",
                    ]

                def run_bridge(run_ctx):
                    outputs = bridge_outputs(run_ctx)
                    for output in outputs:
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_text("terminal", encoding="utf-8")
                    return {
                        "batch4_run": {
                            "emitted": True,
                            "output_paths": {
                                "weekly_report_path": str(outputs[0]),
                                "action_table_path": str(outputs[1]),
                                "machine_record_path": str(outputs[2]),
                            },
                        },
                    }

                pipeline = [
                    capstone.Stage(
                        "soft_discovery", False, lambda _ctx: [],
                        lambda run_ctx: [run_ctx.soft_discovery_receipt_path],
                        stages.run_soft_discovery,
                        failure_policy="zero_effect", output_policy="optional",
                        checkpoint_policy="optional_result_only",
                        failure_handler=capstone._degrade_soft_discovery_boundary,
                    ),
                    capstone.Stage(
                        "weekly_bridge", False, lambda _ctx: [], bridge_outputs, run_bridge,
                    ),
                ]
                summary = capstone.run_weekly_capstone(
                    now_et=datetime(2026, 6, 15, 7, 0, 0),
                    private_root=self.state_dir / "private",
                    batch4_template_path=self.state_dir / "template.json",
                    account_state_path=self.state_dir / "account.json",
                    dry_run=False,
                    confirm_user_authorization=True,
                    stages=pipeline,
                    state_dir=self.state_dir,
                    sample_root=ROOT,
                    soft_discovery_enabled=True,
                )
                self.assertTrue(summary["emitted"])
                result = next(
                    row["result"] for row in summary["stages"]
                    if row["name"] == "soft_discovery"
                )
                self.assertEqual(result["reason_code"], "SOFT_DISCOVERY_IMMUTABLE_CONFLICT")
                self.assertEqual(result["boostable_ticker_count"], 0)

    def test_budget_preview_accepts_bound_immutable_conflict_receipt(self):
        ctx = self._assert_conflict_transition("unavailable", "valid")
        preflight_path = self.state_dir / "preflight.json"

        def run_preflight(_ctx):
            _write_json(preflight_path, {"fresh": True})
            return {
                "scope": {"status": "blocked_execution_constraints"},
                "endpoint_call_forecast": {"total_calls_for_pass2_target_cut": 6},
                "pass2_target_universe": {"target_count": 1},
                "execution_gate": {
                    "ready_to_run_full_candidate_live_packet": False,
                    "block_reasons": ["pass2_call_budget_not_yet_authorized"],
                },
            }

        preview = capstone._run_pass2_budget_preview(ctx, [
            capstone.Stage(
                "soft_discovery", False, lambda _ctx: [],
                lambda run_ctx: [run_ctx.soft_discovery_receipt_path],
                stages.run_soft_discovery,
                failure_policy="zero_effect", output_policy="optional",
                checkpoint_policy="optional_result_only",
                failure_handler=capstone._degrade_soft_discovery_boundary,
            ),
            capstone.Stage(
                "pass2_preflight", False, lambda _ctx: [],
                lambda _ctx: [preflight_path], run_preflight,
            ),
        ])
        self.assertEqual(preview["mode"], "pass2_budget_preview")
        self.assertEqual(preview["pass2_call_budget"], 6)
        self.assertEqual(preview["pass2_target_count"], 1)

    def test_merge_and_manifest_generated_clocks_are_pit_bounded_and_equal(self):
        web._guard_generated_before_open(
            web._parse_dt("2026-06-15T13:29:59.999999Z", field="generated_at"),
            DECISION_DATE,
        )
        with self.assertRaisesRegex(web.WebThemeDiscoveryError, "before the decision open"):
            web._guard_generated_before_open(
                web._parse_dt("2026-06-15T13:30:00Z", field="generated_at"),
                DECISION_DATE,
            )
        web_artifact, web_receipt, x_artifact, x_receipt = _source_packets()
        accepted, manifest = merge.merge_web_x_discovery(
            web_artifact=web_artifact,
            web_receipt=web_receipt,
            x_artifact=x_artifact,
            x_receipt=x_receipt,
            expected_decision_date=DECISION_DATE,
            generated_at="2026-06-15T13:29:59.999999Z",
        )
        self.assertEqual(accepted["generated_at"], manifest["generated_at"])
        with self.assertRaisesRegex(merge.ThemeDiscoveryMergeError, "before the decision open"):
            merge.merge_web_x_discovery(
                web_artifact=web_artifact,
                web_receipt=web_receipt,
                x_artifact=x_artifact,
                x_receipt=x_receipt,
                expected_decision_date=DECISION_DATE,
                generated_at="2026-06-15T13:30:00Z",
            )

        ctx = self._ctx(enabled=True)
        self._write_supporting_inputs(ctx)
        merged, manifest = self._write_merge_pair(ctx)
        manifest["generated_at"] = "2026-06-15T11:00:01+00:00"
        _write_json(ctx.soft_discovery_merge_manifest_path, manifest)
        result = stages.run_soft_discovery(ctx)
        self.assertEqual(result["reason_code"], "MERGE_EVIDENCE_INVALID")
        self.assertFalse(ctx.soft_discovery_ingest_path.exists())

    def test_merge_producer_rejects_after_open_fetched_at_for_web_and_x(self):
        for source_type in ("web", "x"):
            with self.subTest(source_type=source_type):
                web_artifact, web_receipt, x_artifact, x_receipt = _source_packets()
                receipt = web_receipt if source_type == "web" else x_receipt
                receipt["source_refs"][0]["fetched_at"] = "2026-06-15T13:30:00Z"
                with self.assertRaisesRegex(merge.ThemeDiscoveryMergeError, "PIT-safe"):
                    merge.merge_web_x_discovery(
                        web_artifact=web_artifact,
                        web_receipt=web_receipt,
                        x_artifact=x_artifact,
                        x_receipt=x_receipt,
                        expected_decision_date=DECISION_DATE,
                        generated_at=GENERATED_AT,
                    )

    def test_merge_consumer_rejects_after_open_fetched_at_for_web_and_x(self):
        for source_type in ("web", "x"):
            with self.subTest(source_type=source_type):
                web_artifact, web_receipt, x_artifact, x_receipt = _source_packets()
                merged, manifest = merge.merge_web_x_discovery(
                    web_artifact=web_artifact,
                    web_receipt=web_receipt,
                    x_artifact=x_artifact,
                    x_receipt=x_receipt,
                    expected_decision_date=DECISION_DATE,
                    generated_at=GENERATED_AT,
                )
                row = next(ref for ref in manifest["source_refs"] if ref["source_type"] == source_type)
                row["fetched_at"] = "2026-06-15T13:30:00Z"
                with self.assertRaisesRegex(merge.ThemeDiscoveryMergeError, "PIT-safe"):
                    merge.validate_merged_packet(
                        merged,
                        manifest,
                        expected_decision_date=DECISION_DATE,
                        upstream_pairs={
                            "web": (web_artifact, web_receipt),
                            "x": (x_artifact, x_receipt),
                        },
                    )

    def test_web_and_x_producer_generated_at_guards_have_direct_controls(self):
        web_row = {
            "url": "https://web.example/clock", "title": "Clock", "content": "AAPL",
            "published_date": "2026-06-12T11:00:00Z",
        }
        x_row = {
            "url": "https://x.example/clock", "title": "Clock", "text": "AAPL",
            "created_at": "2026-06-12T11:00:00Z",
        }
        with self.assertRaisesRegex(web.WebThemeDiscoveryError, "decision open"):
            web.build_web_fetch_packet(
                queries=["clock"], search_results=[web_row], llm_response='{"themes":[]}',
                expected_decision_date=DECISION_DATE, generated_at="2026-06-15T13:30:00Z",
            )
        with self.assertRaisesRegex(xfetch.XThemeDiscoveryError, "decision open"):
            xfetch.build_x_fetch_packet(
                queries=["clock"], results=[x_row], grok_response='{"themes":[]}',
                expected_decision_date=DECISION_DATE, generated_at="2026-06-15T13:30:00Z",
            )

    def test_input_artifact_digest_anchor_guard_has_a_direct_reverse_control(self):
        with self.assertRaisesRegex(merge.ThemeDiscoveryMergeError, "document anchors"):
            merge._guard_input_artifact_hashes(
                {"web": "0" * 64, "x": "1" * 64},
                {"web": "2" * 64, "x": "1" * 64},
            )

    def test_merge_consumer_clock_guard_has_a_direct_reverse_control(self):
        with self.assertRaisesRegex(merge.ThemeDiscoveryMergeError, "do not match"):
            merge._guard_merge_consumer_clock(
                "2026-06-15T11:00:00Z",
                "2026-06-15T11:00:01Z",
                cutoff=web._cutoff(DECISION_DATE),
            )

    def test_merge_consumer_guards_are_load_bearing_at_the_public_entry(self):
        web_artifact, web_receipt, x_artifact, x_receipt = _source_packets()
        merged, manifest = merge.merge_web_x_discovery(
            web_artifact=web_artifact,
            web_receipt=web_receipt,
            x_artifact=x_artifact,
            x_receipt=x_receipt,
            expected_decision_date=DECISION_DATE,
            generated_at=GENERATED_AT,
        )
        upstream = {
            "web": (web_artifact, web_receipt),
            "x": (x_artifact, x_receipt),
        }

        def rejected(mutator):
            artifact_case = copy.deepcopy(merged)
            manifest_case = copy.deepcopy(manifest)
            mutator(artifact_case, manifest_case)
            with self.assertRaises(merge.ThemeDiscoveryMergeError):
                merge.validate_merged_packet(
                    artifact_case,
                    manifest_case,
                    expected_decision_date=DECISION_DATE,
                    upstream_pairs=upstream,
                )

        cases = {
            "manifest_clock": lambda _artifact, packet: packet.update(
                generated_at="2026-06-15T11:00:01Z"
            ),
            "member_tier": lambda _artifact, packet: (
                packet["themes"][0]["members"][0].update(evidence_tier="single")
            ),
            "summary_count": lambda _artifact, packet: packet["summary"].update(
                merged_theme_count=packet["summary"]["merged_theme_count"] + 1
            ),
            "input_digest": lambda _artifact, packet: packet[
                "input_artifact_sha256"
            ].update(web="f" * 64),
        }
        for label, mutator in cases.items():
            with self.subTest(guard=label):
                rejected(mutator)

        def bad_identity(artifact_case, manifest_case):
            old = manifest_case["source_refs"][0]["source_id"]
            forged = "web:" + "f" * 64
            for packet in (artifact_case, manifest_case):
                for ref in packet["source_refs"]:
                    if ref["source_id"] == old:
                        ref["source_id"] = forged
                for theme in packet["themes"]:
                    if "source_ref_ids" in theme:
                        theme["source_ref_ids"] = [
                            forged if ref == old else ref for ref in theme["source_ref_ids"]
                        ]
                    for member in theme["members"]:
                        member["source_ref_ids"] = [
                            forged if ref == old else ref for ref in member["source_ref_ids"]
                        ]

        with self.subTest(guard="source_identity"):
            rejected(bad_identity)

        source_ref = manifest["source_refs"][0]
        raw_payload = {
            "source_id": source_ref["source_id"],
            "source_type": source_ref["source_type"],
            "canonical_locator": source_ref["canonical_locator"],
            "published_at": source_ref["observed_at"],
        }
        raw_path = (
            self.temp_root
            / "raw"
            / DECISION_DATE
            / f"{source_ref['source_id'].split(':', 1)[1]}.json"
        )
        _write_json(raw_path, raw_payload)
        raw_ref = raw_path.relative_to(ROOT).as_posix()

        def with_raw(manifest_case):
            row = manifest_case["source_refs"][0]
            row["raw_receipt_ref"] = raw_ref
            row["raw_receipt_gitignored"] = True
            row["content_sha256"] = merge._sha(raw_payload)

        with self.subTest(guard="raw_digest"):
            rejected(lambda _artifact, packet: (
                with_raw(packet),
                packet["source_refs"][0].update(content_sha256="f" * 64),
            ))
        with self.subTest(guard="raw_observation_clock"):
            later = dict(raw_payload, published_at="2026-06-12T12:01:00Z")
            _write_json(raw_path, later)
            rejected(lambda _artifact, packet: (
                with_raw(packet),
                packet["source_refs"][0].update(content_sha256=merge._sha(later)),
            ))

    def test_merge_consumer_redundant_guards_fall_through_to_replay_gate(self):
        web_artifact, web_receipt, x_artifact, x_receipt = _source_packets()
        merged, manifest = merge.merge_web_x_discovery(
            web_artifact=web_artifact,
            web_receipt=web_receipt,
            x_artifact=x_artifact,
            x_receipt=x_receipt,
            expected_decision_date=DECISION_DATE,
            generated_at=GENERATED_AT,
        )
        upstream = {"web": (web_artifact, web_receipt), "x": (x_artifact, x_receipt)}

        def bad_identity(artifact_case, manifest_case):
            old = manifest_case["source_refs"][0]["source_id"]
            forged = "web:" + "f" * 64
            for packet in (artifact_case, manifest_case):
                for ref in packet["source_refs"]:
                    if ref["source_id"] == old:
                        ref["source_id"] = forged
                for theme in packet["themes"]:
                    if "source_ref_ids" in theme:
                        theme["source_ref_ids"] = [
                            forged if ref == old else ref for ref in theme["source_ref_ids"]
                        ]
                    for member in theme["members"]:
                        member["source_ref_ids"] = [
                            forged if ref == old else ref for ref in member["source_ref_ids"]
                        ]

        cases = {
            "_guard_merge_consumer_clock": (
                lambda _artifact, packet: packet.update(
                    generated_at="2026-06-15T11:00:01Z"
                ),
                "deterministic projection",
            ),
            "_guard_member_evidence_tier": (
                lambda _artifact, packet: (
                    packet["themes"][0]["members"][0].update(evidence_tier="single")
                ),
                "summary does not match",
            ),
            "_guard_summary_counts": (
                lambda _artifact, packet: packet["summary"].update(
                    merged_theme_count=packet["summary"]["merged_theme_count"] + 1
                ),
                "deterministic projection",
            ),
            "_guard_input_artifact_hashes": (
                lambda _artifact, packet: packet[
                    "input_artifact_sha256"
                ].update(web="f" * 64),
                "deterministic projection",
            ),
            "_guard_source_identity": (
                bad_identity,
                "identity/digest",
            ),
        }
        permissive = lambda *_args, **_kwargs: None
        for guard, (mutator, remaining_gate) in cases.items():
            with self.subTest(guard=guard):
                artifact_case = copy.deepcopy(merged)
                manifest_case = copy.deepcopy(manifest)
                mutator(artifact_case, manifest_case)
                with mock.patch.object(merge, guard, permissive):
                    with self.assertRaisesRegex(
                        merge.ThemeDiscoveryMergeError,
                        remaining_gate,
                    ):
                        merge.validate_merged_packet(
                            artifact_case,
                            manifest_case,
                            expected_decision_date=DECISION_DATE,
                            upstream_pairs=upstream,
                        )

        source_ref = manifest["source_refs"][0]
        raw_payload = {
            "source_id": source_ref["source_id"],
            "source_type": source_ref["source_type"],
            "canonical_locator": source_ref["canonical_locator"],
            "published_at": source_ref["observed_at"],
        }
        raw_path = (
            self.temp_root
            / "raw-redundancy"
            / DECISION_DATE
            / f"{source_ref['source_id'].split(':', 1)[1]}.json"
        )
        _write_json(raw_path, raw_payload)
        manifest_case = copy.deepcopy(manifest)
        row = manifest_case["source_refs"][0]
        row["raw_receipt_ref"] = raw_path.relative_to(ROOT).as_posix()
        row["raw_receipt_gitignored"] = True
        row["content_sha256"] = "f" * 64
        with self.subTest(guard="_guard_raw_content_digest"):
            with mock.patch.object(merge, "_guard_raw_content_digest", permissive):
                with self.assertRaisesRegex(
                    merge.ThemeDiscoveryMergeError,
                    "deterministic projection",
                ):
                    merge.validate_merged_packet(
                        copy.deepcopy(merged),
                        manifest_case,
                        expected_decision_date=DECISION_DATE,
                        upstream_pairs=upstream,
                    )

    def test_merge_entry_points_reject_post_open_upstream_generated_clocks(self):
        web_artifact, web_receipt, x_artifact, x_receipt = _source_packets()
        merged, manifest = merge.merge_web_x_discovery(
            web_artifact=web_artifact,
            web_receipt=web_receipt,
            x_artifact=x_artifact,
            x_receipt=x_receipt,
            expected_decision_date=DECISION_DATE,
            generated_at=GENERATED_AT,
        )
        web_artifact["generated_at"] = "2026-06-15T13:30:00Z"
        web_receipt["generated_at"] = "2026-06-15T13:30:00Z"
        for entry_point in ("producer", "consumer"):
            with self.subTest(entry_point=entry_point):
                with self.assertRaisesRegex(merge.ThemeDiscoveryMergeError, "decision open"):
                    if entry_point == "producer":
                        merge.merge_web_x_discovery(
                            web_artifact=web_artifact,
                            web_receipt=web_receipt,
                            x_artifact=x_artifact,
                            x_receipt=x_receipt,
                            expected_decision_date=DECISION_DATE,
                            generated_at=GENERATED_AT,
                        )
                    else:
                        merge.validate_merged_packet(
                            merged,
                            manifest,
                            expected_decision_date=DECISION_DATE,
                            upstream_pairs={
                                "web": (web_artifact, web_receipt),
                                "x": (x_artifact, x_receipt),
                            },
                        )

    def test_upstream_pairs_are_required_replayed_and_honestly_labelled(self):
        ctx = self._ctx(enabled=True)
        self._write_supporting_inputs(ctx)
        merged, manifest = self._write_merge_pair(ctx)
        result = stages.run_soft_discovery(ctx)
        self.assertTrue(result["evidence_anchor"]["upstream_pair_anchored"])
        self.assertFalse(result["evidence_anchor"]["document_content_anchored"])
        for row in result["evidence_anchor"]["upstream_artifacts"].values():
            self.assertRegex(row["sha256"], r"^[0-9a-f]{64}$")
        with self.assertRaises(TypeError):
            merge.validate_merged_packet(
                merged, manifest, expected_decision_date=ctx.decision_date,
            )

        ctx.soft_discovery_receipt_path.unlink()
        ctx.soft_discovery_ingest_path.unlink()
        ctx.soft_discovery_validation_path.unlink()
        web_path = soft.rerooted_default_path(
            web.default_discovery_path, ctx.decision_date, state_dir=ctx.state_dir,
        )
        forged = json.loads(web_path.read_text(encoding="utf-8"))
        forged["themes"] = []
        _write_json(web_path, forged)
        invalid = stages.run_soft_discovery(ctx)
        self.assertEqual(invalid["status"], "invalid_evidence")
        self.assertEqual(invalid["reason_code"], "MERGE_EVIDENCE_INVALID")
        self.assertFalse(invalid["evidence_anchor"]["upstream_pair_anchored"])
        self.assertFalse(invalid["evidence_anchor"]["document_content_anchored"])

    def test_manifest_shadow_rows_members_and_drop_ledger_are_rejected(self):
        mutations = ("theme", "member", "fabricated_drop", "omitted_drop")
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=mutation):
                if index:
                    self.tearDown()
                    self.setUp()
                ctx = self._ctx(enabled=True)
                self._write_supporting_inputs(ctx)
                merged, manifest = self._write_merge_pair(
                    ctx, include_merge_drop=mutation == "omitted_drop",
                )
                if mutation == "theme":
                    shadow = copy.deepcopy(manifest["themes"][0])
                    shadow["discovery_sources"] = "none"
                    manifest["themes"].insert(0, shadow)
                elif mutation == "member":
                    shadow = copy.deepcopy(manifest["themes"][0]["members"][0])
                    shadow["source_ref_ids"] = []
                    manifest["themes"][0]["members"].insert(0, shadow)
                elif mutation == "fabricated_drop":
                    manifest["drop_ledger"].append({
                        "stage": "theme", "theme_id": "invented",
                        "reason": "invented", "detail": "invented",
                    })
                    manifest["summary"]["dropped_theme_count"] += 1
                else:
                    self.assertEqual(len(manifest["drop_ledger"]), 1)
                    manifest["drop_ledger"] = []
                    manifest["summary"]["dropped_theme_count"] = 0
                _write_json(ctx.soft_discovery_merge_manifest_path, manifest)
                result = stages.run_soft_discovery(ctx)
                self.assertEqual(result["status"], "invalid_evidence")
                self.assertEqual(result["reason_code"], "MERGE_EVIDENCE_INVALID")

    def test_in_memory_discovery_digest_must_hash_the_payload(self):
        ctx = self._ctx(enabled=True)
        self._write_supporting_inputs(ctx)
        merged, manifest = self._write_merge_pair(ctx)
        web_artifact, web_receipt, x_artifact, x_receipt = _source_packets()
        discovery = merge.validate_merged_packet(
            merged,
            manifest,
            expected_decision_date=ctx.decision_date,
            upstream_pairs={
                "web": (web_artifact, web_receipt),
                "x": (x_artifact, x_receipt),
            },
        )
        artifact = ingest.normalize_discovery_payload(
            discovery,
            expected_decision_date=ctx.decision_date,
            generated_at=merged["generated_at"],
        )
        canonical_digest = hashlib.sha256(
            (json.dumps(artifact, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        ).hexdigest()
        valid = validate.load_inputs_from_discovery(
            discovery=artifact,
            discovery_sha256=canonical_digest,
            candidate_path=ctx.candidate_path,
            classification_path=ctx.classification_packet_path,
            expected_date=ctx.decision_date,
        )
        self.assertEqual(valid["hashes"]["discovery"], canonical_digest)
        with self.assertRaisesRegex(validate.ProvisionalThemeValidationError, "does not bind"):
            validate.load_inputs_from_discovery(
                discovery=artifact,
                discovery_sha256="f" * 64,
                candidate_path=ctx.candidate_path,
                classification_path=ctx.classification_packet_path,
                expected_date=ctx.decision_date,
            )

    def test_disabled_is_inert_with_an_external_state_root(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = replace(self._ctx(enabled=False), state_dir=Path(td))
            result = stages.run_soft_discovery(ctx)
            self.assertEqual(result["status"], "disabled")
            self.assertFalse(any(Path(td).rglob("*")))

    def test_unavailable_and_invalid_evidence_are_inert_with_an_external_state_root(self):
        with tempfile.TemporaryDirectory() as td:
            external = Path(td)
            unavailable_ctx = replace(self._ctx(enabled=True), state_dir=external)
            unavailable = stages.run_soft_discovery(unavailable_ctx)
            self.assertEqual(unavailable["status"], "upstream_unavailable")
            self.assertTrue(all(value is False for value in unavailable["effects"].values()))

        with tempfile.TemporaryDirectory() as td:
            external = Path(td)
            invalid_ctx = replace(self._ctx(enabled=True), state_dir=external)
            _write_json(invalid_ctx.soft_discovery_merge_path, {"bad": "artifact"})
            _write_json(invalid_ctx.soft_discovery_merge_manifest_path, {"bad": "manifest"})
            invalid = stages.run_soft_discovery(invalid_ctx)
            self.assertEqual(invalid["status"], "invalid_evidence")
            self.assertTrue(all(value is False for value in invalid["effects"].values()))

    def test_receipt_publisher_writes_and_reloads_a_schema_valid_payload(self):
        ctx = self._ctx(enabled=False)
        payload = stages.run_soft_discovery(ctx)
        saved = soft._publish_receipt(
            payload,
            ctx.soft_discovery_receipt_path,
            state_dir=ctx.state_dir,
        )
        self.assertEqual(saved, payload)
        self.assertEqual(
            json.loads(ctx.soft_discovery_receipt_path.read_text(encoding="utf-8")),
            payload,
        )

    def test_capstone_boundary_failure_binds_existing_artifact_hashes(self):
        ctx = self._ctx(enabled=True)
        self._write_supporting_inputs(ctx)
        self._write_merge_pair(ctx)
        frozen = stages.run_soft_discovery(ctx)
        self.assertEqual(frozen["status"], "valid_nonempty")
        ctx.soft_discovery_receipt_path.unlink()

        result = soft.degrade_capstone_boundary_failure(
            ctx,
            RuntimeError("injected-capstone-boundary-failure"),
        )

        self.assertEqual(result["reason_code"], "SOFT_DISCOVERY_STAGE_EXCEPTION")
        for key, artifact in result["artifacts"].items():
            path = ROOT / artifact["path"] if artifact["path"] is not None else None
            self.assertIsNotNone(path, key)
            self.assertEqual(
                artifact["sha256"], hashlib.sha256(path.read_bytes()).hexdigest(),
            )

    def test_missing_candidate_or_classification_is_typed_upstream_unavailable(self):
        for missing in ("candidate", "classification"):
            with self.subTest(missing=missing):
                ctx = self._ctx(enabled=True)
                self._write_supporting_inputs(ctx)
                self._write_merge_pair(ctx)
                target = (
                    ctx.candidate_path
                    if missing == "candidate"
                    else ctx.classification_packet_path
                )
                target.unlink()
                result = stages.run_soft_discovery(ctx)
                self.assertEqual(result["status"], "upstream_unavailable")
                self.assertEqual(result["reason_code"], "CANDIDATE_INPUT_UNAVAILABLE")
                self.assertTrue(all(value is False for value in result["effects"].values()))
                self.tearDown()
                self.setUp()

    def test_receipt_schema_rejects_cross_field_and_unknown_reason_drift(self):
        receipt = stages.run_soft_discovery(self._ctx(enabled=False))
        invalid = copy.deepcopy(receipt)
        invalid["status"] = "invalid_evidence"
        with self.assertRaises(soft.SoftDiscoveryEvidenceError):
            soft._schema_validate(invalid)
        unknown = copy.deepcopy(receipt)
        unknown["reason_code"] = "UNKNOWN_REASON"
        with self.assertRaises(soft.SoftDiscoveryEvidenceError):
            soft._schema_validate(unknown)
        mismatched = copy.deepcopy(receipt)
        mismatched["status"] = "invalid_evidence"
        mismatched["reason_code"] = "MERGE_PAIR_INCOMPLETE"
        mismatched["error_summary"] = {
            "code": "MERGE_EVIDENCE_INVALID",
            "error_type": "SoftDiscoveryEvidenceError",
        }
        with self.assertRaises(soft.SoftDiscoveryEvidenceError):
            soft._schema_validate(mismatched)
        ctx = self._ctx(enabled=True)
        self._write_supporting_inputs(ctx)
        self._write_merge_pair(ctx, empty=True)
        empty = stages.run_soft_discovery(ctx)
        self.assertEqual(empty["status"], "valid_empty")
        for field in ("validated_theme_count", "boostable_ticker_count"):
            drift = copy.deepcopy(empty)
            drift[field] = 1
            with self.assertRaises(soft.SoftDiscoveryEvidenceError):
                soft._schema_validate(drift)
        nonempty_with_zero_counts = copy.deepcopy(empty)
        nonempty_with_zero_counts["status"] = "valid_nonempty"
        with self.assertRaises(soft.SoftDiscoveryEvidenceError):
            soft._schema_validate(nonempty_with_zero_counts)

    def test_raw_receipt_traversal_is_rejected_before_filesystem_lookup(self):
        web_artifact, web_receipt, x_artifact, x_receipt = _source_packets()
        merged, manifest = merge.merge_web_x_discovery(
            web_artifact=web_artifact,
            web_receipt=web_receipt,
            x_artifact=x_artifact,
            x_receipt=x_receipt,
            expected_decision_date=DECISION_DATE,
            generated_at=GENERATED_AT,
        )
        manifest["source_refs"][0]["raw_receipt_ref"] = (
            "provider_samples/outside_allowed_root/leaked.json"
        )
        manifest["source_refs"][0]["raw_receipt_gitignored"] = True
        with mock.patch.object(
            merge,
            "PROVIDER_SAMPLES_ROOT",
            ROOT / "provider_samples" / "allowed_only",
        ):
            with self.assertRaisesRegex(
                merge.ThemeDiscoveryMergeError,
                "must stay under provider_samples",
            ):
                merge.validate_merged_packet(
                    merged,
                    manifest,
                    expected_decision_date=DECISION_DATE,
                    upstream_pairs={
                        "web": (web_artifact, web_receipt),
                        "x": (x_artifact, x_receipt),
                    },
                )

    def test_merge_discovery_shape_guard_is_load_bearing_at_the_public_producer(self):
        web_artifact, web_receipt, x_artifact, x_receipt = _source_packets()
        web_artifact["unexpected"] = "schema drift"
        web_receipt["discovery_artifact_sha256"] = web._discovery_evidence_hash(web_artifact)
        with self.assertRaises(merge.ThemeDiscoveryMergeError):
            merge.merge_web_x_discovery(
                web_artifact=web_artifact,
                web_receipt=web_receipt,
                x_artifact=x_artifact,
                x_receipt=x_receipt,
                expected_decision_date=DECISION_DATE,
                generated_at=GENERATED_AT,
            )

    def test_merge_manifest_schema_guard_is_load_bearing_at_the_public_producer(self):
        web_artifact, web_receipt, x_artifact, x_receipt = _source_packets()
        with mock.patch.object(
            merge,
            "_corroboration",
            return_value=("not-a-schema-enum", None, []),
        ):
            with self.assertRaises(merge.ThemeDiscoveryMergeError):
                merge.merge_web_x_discovery(
                    web_artifact=web_artifact,
                    web_receipt=web_receipt,
                    x_artifact=x_artifact,
                    x_receipt=x_receipt,
                    expected_decision_date=DECISION_DATE,
                    generated_at=GENERATED_AT,
                )

    def test_stage_fail_closed_terms_have_direct_dying_controls(self):
        with self.assertRaises(soft.SoftDiscoveryEvidenceError):
            soft._relative(Path(tempfile.gettempdir()) / "outside.json")
        bad_json = self.state_dir / "array.json"
        bad_json.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(soft.SoftDiscoveryEvidenceError, "JSON object"):
            soft._read_json_with_sha(bad_json, label="probe")
        with self.assertRaisesRegex(soft.SoftDiscoveryEvidenceError, "incomplete"):
            soft._require_complete_pair(
                True, False, label="probe", reason_code="MERGE_PAIR_INCOMPLETE",
            )
        with self.assertRaisesRegex(soft.SoftDiscoveryEvidenceError, "conflict key"):
            soft._conflict_receipt_path(
                DECISION_DATE, "../bad", state_dir=self.state_dir,
            )
        wrong = self.state_dir / "wrong.json"
        with self.assertRaises(DiscoveryPublishPolicyError):
            soft.validate_exact_decision_slot(
                wrong,
                soft.default_receipt_path(DECISION_DATE, state_dir=self.state_dir),
                root=ROOT,
                state_dir=self.state_dir,
            )

    def test_merge_fail_closed_terms_have_direct_dying_controls(self):
        cutoff = web._cutoff(DECISION_DATE)
        with self.assertRaises(merge.ThemeDiscoveryMergeError):
            merge._guard_generated_clock(
                "2026-06-15T13:30:00Z", cutoff=cutoff, field="probe",
            )
        with self.assertRaises(merge.ThemeDiscoveryMergeError):
            merge._guard_source_identity(
                source_id="web:" + "0" * 64,
                source_type="web",
                locator="https://example.invalid/source",
            )
        with self.assertRaises(merge.ThemeDiscoveryMergeError):
            merge._guard_source_pit(observed=cutoff, fetched=cutoff, cutoff=cutoff)
        with self.assertRaises(merge.ThemeDiscoveryMergeError):
            merge._guard_raw_content_digest(raw_payload={}, expected_sha256="0" * 64)
        with self.assertRaises(merge.ThemeDiscoveryMergeError):
            merge._guard_member_evidence_tier(
                residual=[], actual_sources="both", expected_sources="single",
                actual_tier="both", expected_tier="single",
            )
        with self.assertRaises(merge.ThemeDiscoveryMergeError):
            merge._guard_summary_counts(summary={"count": 1}, expected_counts={"count": 2})
        with self.assertRaises(merge.ThemeDiscoveryMergeError):
            merge._guard_unique_manifest_rows(
                [{"theme_id": "same"}, {"theme_id": "same"}],
                key="theme_id", label="theme identity",
            )

    def test_unexpected_programming_error_is_not_hidden_as_a_normal_status(self):
        ctx = self._ctx(enabled=True)
        self._write_supporting_inputs(ctx)
        self._write_merge_pair(ctx)
        with mock.patch.object(merge, "validate_merged_packet", side_effect=RuntimeError("bug")):
            with self.assertRaisesRegex(RuntimeError, "bug"):
                stages.run_soft_discovery(ctx)
        self.assertFalse(ctx.soft_discovery_receipt_path.exists())

    def test_capstone_full_entry_degrades_any_soft_stage_exception_and_reaches_terminal(self):
        summary = self._run_terminal_pipeline(
            mock.Mock(side_effect=RuntimeError("injected-stage-failure")),
        )
        self.assertTrue(summary["emitted"])
        result = summary["stages"][0]["result"]
        self.assertEqual(result["status"], "invalid_evidence")
        self.assertEqual(result["reason_code"], "SOFT_DISCOVERY_STAGE_EXCEPTION")
        self.assertEqual(result["error_summary"]["error_type"], "RuntimeError")
        self.assertTrue(all(value is False for value in result["effects"].values()))

    def test_capstone_boundary_degrades_optional_input_output_and_freshness_failures(self):
        cases = {
            "input_enumeration": {"soft_inputs": mock.Mock(side_effect=RuntimeError("input enumeration"))},
            "unreadable_input": {"soft_inputs": lambda _ctx: [self.state_dir / "missing-input.json"]},
            "output_enumeration": {"soft_outputs": mock.Mock(side_effect=RuntimeError("output enumeration"))},
            "non_object_result": {"soft_run": lambda _ctx: []},
            "freshness": {"soft_run": lambda _ctx: {"status": "valid_empty", "effects": {
                "scoring_eligible": False, "top15_effect_enabled": False,
                "operation_advice_effect_enabled": False, "dynamic_seats_enabled": False,
                "theme_probe_enabled": False, "lifecycle_actions_enabled": False,
            }}},
        }
        for index, (name, kwargs) in enumerate(cases.items()):
            with self.subTest(failure=name):
                summary = self._run_terminal_pipeline(
                    kwargs.pop("soft_run", mock.Mock(side_effect=RuntimeError("unused"))),
                    now_et=datetime(2026, 6, 15 + index, 7, 0, 0), **kwargs,
                )
                self.assertTrue(summary["emitted"])
                result = summary["stages"][0]["result"]
                self.assertEqual(result["status"], "invalid_evidence")
                self.assertTrue(all(value is False for value in result["effects"].values()))

    def test_capstone_boundary_contains_the_real_soft_stage_public_entry(self):
        with mock.patch.object(
            soft,
            "run_offline_stage",
            side_effect=RuntimeError("injected-public-entry-failure"),
        ):
            summary = self._run_terminal_pipeline(stages.run_soft_discovery)
        self.assertTrue(summary["emitted"])
        result = summary["stages"][0]["result"]
        self.assertEqual(result["status"], "invalid_evidence")
        self.assertEqual(result["reason_code"], "SOFT_DISCOVERY_STAGE_EXCEPTION")
        self.assertTrue(all(value is False for value in result["effects"].values()))

    def test_capstone_full_entry_survives_failure_of_the_soft_failure_writer(self):
        with mock.patch.object(
            soft,
            "degrade_capstone_boundary_failure",
            side_effect=soft.SoftDiscoveryEvidenceError("injected fallback failure"),
        ):
            summary = self._run_terminal_pipeline(
                mock.Mock(side_effect=RuntimeError("injected-stage-failure")),
            )
        self.assertTrue(summary["emitted"])
        result = summary["stages"][0]["result"]
        self.assertEqual(result["reason_code"], "SOFT_DISCOVERY_STAGE_EXCEPTION")
        self.assertTrue(all(value is False for value in result["effects"].values()))
        soft._schema_validate(result)

    def test_production_checkpoint_records_artifactless_optional_failure_and_terminal_emits(self):
        """K4A-R10: a canonical receipt slot occupied by a directory cannot kill the weekly run."""
        ctx = self._ctx(enabled=True)
        ctx.soft_discovery_receipt_path.mkdir(parents=True, exist_ok=True)
        _write_json(ctx.account_state_path, {"positions": []})
        _write_json(ctx.batch4_template_path, {"template": True})
        degraded = soft.run_offline_stage(ctx)
        self.assertEqual(degraded["reason_code"], "SOFT_DISCOVERY_IMMUTABLE_CONFLICT")

        def bridge_outputs(run_ctx):
            root = run_ctx.official_output_root or run_ctx.private_root
            return [
                root / "weekly_private" / run_ctx.decision_date / "weekly_report.md",
                root / "weekly_private" / run_ctx.decision_date / "action_table.csv",
                root / "runs_private" / run_ctx.decision_date / "machine_record.json",
            ]

        def bridge(run_ctx):
            outputs = bridge_outputs(run_ctx)
            for output in outputs:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("terminal", encoding="utf-8")
            return {"batch4_run": {"emitted": True, "output_paths": {
                "weekly_report_path": str(outputs[0]),
                "action_table_path": str(outputs[1]),
                "machine_record_path": str(outputs[2]),
            }}}

        pipeline = [
            capstone.Stage(
                "soft_discovery", False, lambda _ctx: [],
                lambda run_ctx: [run_ctx.soft_discovery_receipt_path],
                lambda _ctx: copy.deepcopy(degraded),
                failure_policy="zero_effect", output_policy="optional",
                checkpoint_policy="optional_result_only",
                failure_handler=capstone._degrade_soft_discovery_boundary,
            ),
            capstone.Stage("weekly_bridge", False, lambda _ctx: [], bridge_outputs, bridge),
        ]
        with mock.patch.object(capstone, "default_pipeline", return_value=pipeline), \
                mock.patch.object(capstone, "_provider_execution_receipt", return_value=object()), \
                mock.patch("runners.us_short_account_state_from_manual_tables.validate_account_state"):
            summary = capstone.run_weekly_capstone(
                now_et=datetime(2026, 6, 15, 7, 0, 0),
                private_root=self.state_dir / "private",
                batch4_template_path=self.state_dir / "template.json",
                account_state_path=self.state_dir / "account.json",
                authorized_pass2_call_budget=10,
                dry_run=False,
                confirm_user_authorization=True,
                state_dir=self.state_dir,
                sample_root=ROOT,
            )
        self.assertTrue(summary["emitted"])
        manifest = capstone.checkpoint_store.load_manifest(Path(summary["checkpoint_manifest"]))
        row = next(item for item in manifest["stages"] if item["name"] == "soft_discovery")
        self.assertEqual(row["output_availability"], "unavailable")
        self.assertEqual(row["output_manifest"], [])
        self.assertEqual(row["checkpoint_policy"], "optional_result_only")

    def test_optional_checkpoint_oserror_is_fail_soft_and_leaves_no_optional_row(self):
        ctx = self._ctx(enabled=True)
        ctx.soft_discovery_receipt_path.mkdir(parents=True, exist_ok=True)
        _write_json(ctx.account_state_path, {"positions": []})
        _write_json(ctx.batch4_template_path, {"template": True})
        degraded = soft.run_offline_stage(ctx)
        pipeline = [
            capstone.Stage(
                "soft_discovery", False, lambda _ctx: [],
                lambda run_ctx: [run_ctx.soft_discovery_receipt_path],
                lambda _ctx: copy.deepcopy(degraded),
                failure_policy="zero_effect", output_policy="optional",
                checkpoint_policy="optional_result_only",
                failure_handler=capstone._degrade_soft_discovery_boundary,
            ),
            self._bridge_stage(),
        ]
        events = []
        original_record_stage = capstone.checkpoint_store.record_stage

        def record_stage_with_optional_oserror(**kwargs):
            if kwargs["stage"].name == "soft_discovery":
                raise OSError("injected optional checkpoint write failure")
            return original_record_stage(**kwargs)

        with mock.patch.object(capstone, "default_pipeline", return_value=pipeline), \
                mock.patch.object(capstone, "_provider_execution_receipt", return_value=object()), \
                mock.patch.object(
                    capstone.checkpoint_store, "record_stage", side_effect=record_stage_with_optional_oserror,
                ), \
                mock.patch("runners.us_short_account_state_from_manual_tables.validate_account_state"):
            summary = capstone.run_weekly_capstone(
                now_et=datetime(2026, 6, 15, 7, 0, 0),
                private_root=self.state_dir / "private",
                batch4_template_path=self.state_dir / "template.json",
                account_state_path=self.state_dir / "account.json",
                authorized_pass2_call_budget=10, dry_run=False,
                confirm_user_authorization=True, state_dir=self.state_dir,
                sample_root=ROOT, diagnostic_event=events.append,
            )
        self.assertTrue(summary["emitted"])
        self.assertIn(
            {"event": "stage_checkpoint_unavailable", "stage": "soft_discovery", "error_type": "OSError"},
            events,
        )
        manifest = capstone.checkpoint_store.load_manifest(Path(summary["checkpoint_manifest"]))
        self.assertNotIn("soft_discovery", {row["name"] for row in manifest["stages"]})

    def test_budget_preview_entry_degrades_any_soft_stage_exception_and_continues(self):
        ctx = self._ctx(enabled=True)
        preflight_path = self.state_dir / "preflight_exception.json"

        def run_preflight(_ctx):
            _write_json(preflight_path, {"fresh": True})
            return {
                "endpoint_call_forecast": {"total_calls_for_pass2_target_cut": 6},
                "pass2_target_universe": {"target_count": 1},
                "execution_gate": {
                    "ready_to_run_full_candidate_live_packet": False,
                    "block_reasons": ["pass2_call_budget_not_yet_authorized"],
                },
            }

        cases = {
            "input_enumeration": capstone.Stage(
                "soft_discovery", False,
                mock.Mock(side_effect=RuntimeError("injected-input-enumeration")),
                lambda run_ctx: [run_ctx.soft_discovery_receipt_path],
                mock.Mock(side_effect=RuntimeError("unused-run")),
            ),
            "unreadable_input": capstone.Stage(
                "soft_discovery", False,
                lambda _ctx: [self.state_dir / "missing-preview-input.json"],
                lambda run_ctx: [run_ctx.soft_discovery_receipt_path],
                mock.Mock(side_effect=RuntimeError("unused-run")),
            ),
            "output_enumeration": capstone.Stage(
                "soft_discovery", False, lambda _ctx: [],
                mock.Mock(side_effect=RuntimeError("injected-output-enumeration")),
                mock.Mock(side_effect=RuntimeError("unused-run")),
            ),
            "stage_run": capstone.Stage(
                "soft_discovery", False, lambda _ctx: [],
                lambda run_ctx: [run_ctx.soft_discovery_receipt_path],
                mock.Mock(side_effect=RuntimeError("injected-stage-failure")),
            ),
            "non_object_result": capstone.Stage(
                "soft_discovery", False, lambda _ctx: [],
                lambda run_ctx: [run_ctx.soft_discovery_receipt_path],
                lambda _ctx: [],
            ),
            "freshness": capstone.Stage(
                "soft_discovery", False, lambda _ctx: [],
                lambda run_ctx: [run_ctx.soft_discovery_receipt_path],
                lambda _ctx: {"status": "invalid_evidence", "effects": {}},
            ),
        }
        for name, soft_stage in cases.items():
            with self.subTest(failure=name):
                soft_stage.failure_policy = "zero_effect"
                soft_stage.output_policy = "optional"
                soft_stage.checkpoint_policy = "optional_result_only"
                soft_stage.failure_handler = capstone._degrade_soft_discovery_boundary
                preview = capstone._run_pass2_budget_preview(ctx, [
                    soft_stage,
                    capstone.Stage(
                        "pass2_preflight", False, lambda _ctx: [],
                        lambda _ctx: [preflight_path], run_preflight,
                    ),
                ])
                self.assertEqual(preview["pass2_call_budget"], 6)
                result = preview["stages"][0]["result"]
                self.assertEqual(result["status"], "invalid_evidence")
                self.assertTrue(all(value is False for value in result["effects"].values()))

    def test_capstone_accepts_an_exact_immutable_receipt_retry(self):
        receipt_path = self.state_dir / "fake_soft_discovery_receipt.json"
        receipt = {"status": "upstream_unavailable", "decision_date": DECISION_DATE}
        _write_json(receipt_path, receipt)
        stage = capstone.Stage(
            "soft_discovery",
            False,
            lambda _ctx: [],
            lambda _ctx: [receipt_path],
            lambda _ctx: copy.deepcopy(receipt),
            failure_policy="zero_effect", output_policy="optional",
            checkpoint_policy="optional_result_only",
            failure_handler=capstone._degrade_soft_discovery_boundary,
        )
        self.assertTrue(capstone._unchanged_soft_discovery_receipt_matches(
            stage, copy.deepcopy(receipt), [receipt_path],
        ))
        self.assertFalse(capstone._unchanged_soft_discovery_receipt_matches(
            stage, {**receipt, "status": "invalid_evidence"}, [receipt_path],
        ))

    def test_capstone_accepts_every_bound_unusable_canonical_receipt_as_zero_effect(self):
        corruptions = {
            "truncated": b"{",
            "non_json": b"not-json",
            "non_object": b"[]",
            "schema_invalid": b'{"schema_name":"wrong"}',
            "future_schema": json.dumps({
                "schema_name": "us_short_provisional_theme_stage_receipt",
                "schema_version": "999.0.0",
            }).encode("utf-8"),
        }
        for index, (cause, frozen_bytes) in enumerate(corruptions.items()):
            with self.subTest(cause=cause):
                if index:
                    self.tearDown()
                    self.setUp()
                ctx = self._ctx(enabled=True)
                self._write_supporting_inputs(ctx)
                self._write_merge_pair(ctx)
                first = stages.run_soft_discovery(ctx)
                self.assertEqual(first["status"], "valid_nonempty")
                ctx.soft_discovery_receipt_path.write_bytes(frozen_bytes)

                result = stages.run_soft_discovery(ctx)
                self.assertEqual(result["status"], "invalid_evidence")
                self.assertEqual(result["reason_code"], "SOFT_DISCOVERY_IMMUTABLE_CONFLICT")
                self.assertEqual(result["validated_theme_count"], 0)
                self.assertEqual(result["boostable_ticker_count"], 0)
                binding = result["immutable_conflict"]["canonical_receipt"]
                self.assertEqual(
                    binding["sha256"], hashlib.sha256(frozen_bytes).hexdigest(),
                )
                self.assertEqual(ctx.soft_discovery_receipt_path.read_bytes(), frozen_bytes)
                self.assertTrue(capstone._unchanged_soft_discovery_receipt_matches(
                    capstone.Stage(
                        "soft_discovery", False, lambda _ctx: [],
                        lambda run_ctx: [run_ctx.soft_discovery_receipt_path],
                        stages.run_soft_discovery,
                        failure_policy="zero_effect", output_policy="optional",
                        checkpoint_policy="optional_result_only",
                        failure_handler=capstone._degrade_soft_discovery_boundary,
                    ),
                    result,
                    [ctx.soft_discovery_receipt_path],
                ))
                summary = self._run_terminal_pipeline(lambda _ctx: copy.deepcopy(result))
                self.assertTrue(summary["emitted"])
                self.assertEqual(
                    summary["stages"][0]["result"]["boostable_ticker_count"], 0,
                )
                self.assertFalse([
                    path for path in self.state_dir.rglob("*")
                    if path.is_file() and path.name.startswith(".")
                ])


if __name__ == "__main__":
    unittest.main()
