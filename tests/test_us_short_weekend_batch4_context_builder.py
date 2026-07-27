# -*- coding: utf-8 -*-
"""Supported-entrypoint end-to-end test for the US-short batch4 context builder + runner.

Closes the runner half of R-USSHORT-BATCH4-ONE-CLICK-EXECUTION-ENTRYPOINT-GAP: it proves a user can
assemble and run a complete batch4 weekend pipeline from SUPPORTED commands and committed artifacts —
NOT by reverse-engineering test internals. Deliberately does NOT import the private packet helpers
(`tests.test_us_short_weekend_batch4_runner._packet` / `tests.test_us_short_weekend_orchestrator.
_pipeline_context`) and does NOT shape-transform the input: the positive paths feed the committed
example templates to `--analysis-fixture` DIRECTLY (the builder ignores their path keys); the
calendar/governance come from committed presets.

Also pins the round-2 reverse-path fixes: schema↔runtime type for `catalyst_recall_feed`, true 1:1
holdings cardinality (duplicate rows rejected), and the no-secret error contract (no ticker / account
value / schema value echoed to stderr on any failure class). Everything is OFFLINE: synthetic account,
dry-run outputs to a private temp root, live hard-blocked.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import us_short_weekend_batch4 as runner  # module under test (NOT a private test helper)
from engine.us_short_run_origin import OFFLINE_DISCLOSURE_SENTINEL, OFFLINE_TEST_RUN_ORIGIN

SCHEMA_PATH = ROOT / "schemas" / "us_short_weekend_batch4_context_packet.schema.json"
EX_DIR = ROOT / "schemas" / "examples"
EMPTY_EXAMPLE = EX_DIR / "us_short_weekend_batch4_context_packet.empty.example.json"
NONEMPTY_EXAMPLE = EX_DIR / "us_short_weekend_batch4_context_packet.nonempty.example.json"
CALENDAR = ROOT / "presets" / "us_short_market_calendar_2026_2027.json"
GOVERNANCE = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
BUILDER = ROOT / "runners" / "us_short_weekend_batch4_context_builder.py"
RUNNER = ROOT / "runners" / "us_short_weekend_batch4.py"
NOW_ET = "2026-06-13T10:00:00"   # Sat 10:00 ET -> Mon 20260615 decision (matches the committed calendar)


def _account(positions) -> dict:
    positions = list(positions)
    return {"schema_name": "us_short_account_state", "schema_version": "1.0.0", "as_of": "20260615",
            "us_market_equity": 30000.0, "us_short_bucket_capital": 10000.0,
            "us_short_available_cash": 4000.0, "positions": positions,
            "holding_action_reconciliation": {
                "schema_name": "us_short_holding_action_reconciliation", "schema_version": "1.0.0",
                "as_of": "20260615",
                "positions": [{"ticker": p["ticker"], "entry_date": p["entry_date"], "remaining_shares": p["shares"],
                               "tp1_completed": False, "tp1_completed_at": None,
                               "source_reconciliation_ref": "test-account:" + p["ticker"]} for p in positions]},
            "symbol_cooldown_reconciliation": {
                "schema_name": "us_short_symbol_cooldown_reconciliation", "schema_version": "1.0.0",
                "as_of": "20260615", "events": []},
            "manual_order_only": True, "broker_connection_allowed": False}


def _run(cmd):
    existing_pythonpath = os.environ.get("PYTHONPATH")
    pythonpath_parts = [str(ROOT)]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    # GOV-R6: pin BOTH ends of the pipe. The child's stdio encoding follows whatever
    # PYTHONIOENCODING it inherits and the parent's `text=True` would otherwise decode with the
    # machine/shell locale (cp936 here), so an ambient `PYTHONIOENCODING=utf-8` used to turn every
    # redaction assertion below into `UnicodeDecodeError -> stderr is None -> TypeError`.
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(pythonpath_parts), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, *cmd], cwd=str(ROOT), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def _build_cmd(base: Path, *, account, fixture, out):
    return [str(BUILDER), "--account", str(account), "--analysis-fixture", str(fixture),
            "--calendar", str(CALENDAR), "--governance", str(GOVERNANCE),
            "--lifecycle-register", str(base / "lifecycle" / "reg.json"),
            "--runs-private-root", str(base / "runs_private"),
            "--weekly-private-root", str(base / "weekly_private"), "--out", str(out)]


def _build(base: Path, *, fixture: Path, positions):
    """Write a synthetic account, run the builder CLI with the given fixture path. Returns (result, out_path)."""
    account = base / "account_state.json"
    account.write_text(json.dumps(_account(positions)), encoding="utf-8")
    out = base / "packet.json"
    return _run(_build_cmd(base, account=account, fixture=fixture, out=out)), out, account


class ExamplesAndSchema(unittest.TestCase):
    def test_committed_examples_validate_against_schema(self):
        import jsonschema
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        for ex in (EMPTY_EXAMPLE, NONEMPTY_EXAMPLE):
            jsonschema.validate(json.loads(ex.read_text(encoding="utf-8")), schema)

    def test_catalyst_recall_feed_schema_matches_runtime_list_type(self):
        import jsonschema
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        base = json.loads(EMPTY_EXAMPLE.read_text(encoding="utf-8"))
        ok = copy.deepcopy(base)
        ok["data_context"]["catalyst_recall_feed"] = ["AAPL", "MSFT"]   # runtime type = list|null
        jsonschema.validate(ok, schema)                                  # accepted
        bad = copy.deepcopy(base)
        bad["data_context"]["catalyst_recall_feed"] = {}                 # object: runtime rejects it
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)

    def test_runner_validates_nested_packet_shape_before_orchestration(self):
        packet = json.loads(EMPTY_EXAMPLE.read_text(encoding="utf-8"))
        runner._validate_packet_schema(packet)                           # the committed example passes
        bad = copy.deepcopy(packet)
        bad["prior_upgrade_count"] = "not-an-int"
        with self.assertRaises(runner.Batch4RunnerError):
            runner._validate_packet_schema(bad)


class BuilderRunnerEndToEnd(unittest.TestCase):
    def test_empty_run_consumes_committed_example_directly(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            built, packet, _ = _build(base, fixture=EMPTY_EXAMPLE, positions=[])   # committed example, no transform
            self.assertEqual(built.returncode, 0, built.stderr)
            self.assertEqual(built.stderr, "")
            ran = _run([str(RUNNER), "--context", str(packet), "--now-et", NOW_ET,
                        "--bootstrap-lifecycle", "--dry-run"])
            self.assertEqual(ran.returncode, 0, ran.stderr)
            summary = json.loads(ran.stdout)
            self.assertTrue(summary["emitted"] and summary["dry_run"])
            self.assertEqual(summary["row_count"], 0)

    def test_nonempty_run_consumes_committed_example_directly_and_emits_one_row(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            built, packet, _ = _build(base, fixture=NONEMPTY_EXAMPLE, positions=[])  # committed example, no transform
            self.assertEqual(built.returncode, 0, built.stderr)
            self.assertNotIn("AAPL", built.stderr)                       # success path leaks no ticker
            ran = _run([str(RUNNER), "--context", str(packet), "--now-et", NOW_ET,
                        "--bootstrap-lifecycle", "--dry-run"])
            self.assertEqual(ran.returncode, 0, ran.stderr)
            summary = json.loads(ran.stdout)
            self.assertTrue(summary["emitted"])
            self.assertEqual(summary["row_count"], 1)
            self.assertNotIn("AAPL", ran.stdout + ran.stderr)            # runner summary carries no ticker


class OfflineProvenanceArtifacts(unittest.TestCase):
    """R-USSHORT-BATCH4-OFFLINE-ARTIFACT-MODE-PROVENANCE-GAP: a real (non-dry-run) supported-runner write must
    stamp the immutable offline/data-origin fact on BOTH the machine artifact and the rendered report, and the
    report must NOT present the fixture provider health as operationally authoritative-clean."""

    def _assert_offline_artifacts(self, example):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            built, packet, _ = _build(base, fixture=example, positions=[])
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = _run([str(RUNNER), "--context", str(packet), "--now-et", NOW_ET,
                        "--bootstrap-lifecycle"])                                   # NOT dry-run → real private write
            self.assertEqual(ran.returncode, 0, ran.stderr)
            dd = "20260615"   # Mon decision for the Sat 2026-06-13 run
            machine = json.loads((base / "runs_private" / dd / "machine_record.json").read_text(encoding="utf-8"))
            report = (base / "weekly_private" / dd / "weekly_report.md").read_text(encoding="utf-8")
            self.assertEqual(machine["run_origin"], OFFLINE_TEST_RUN_ORIGIN)        # machine artifact stamped
            self.assertIn(OFFLINE_DISCLOSURE_SENTINEL, report)                      # report always-visible banner
            # provider health must NOT be rendered as operationally authoritative-clean (Codex's exact combo);
            # the offline disclaimer replaces it, and §13 can never say there is no unclean item
            self.assertNotIn("provider_health=clean（结构化、权威", report)
            self.assertIn("offline_test 不认定运营级权威 clean", report)
            self.assertNotIn("本周无不 clean 项", report)                            # offline limitation always listed

    def test_empty_and_nonempty_artifacts_carry_matching_offline_provenance(self):
        for example in (EMPTY_EXAMPLE, NONEMPTY_EXAMPLE):
            self._assert_offline_artifacts(example)


class FailClosedAndRedaction(unittest.TestCase):
    def _fixture_from(self, base: Path, mutate) -> Path:
        payload = json.loads(EMPTY_EXAMPLE.read_text(encoding="utf-8"))
        mutate(payload)
        path = base / "fixture.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_malformed_fixture_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            fixture = self._fixture_from(base, lambda p: p.pop("run_provenance"))
            built, out, _ = _build(base, fixture=fixture, positions=[])
            self.assertNotEqual(built.returncode, 0)
            self.assertFalse(out.exists())

    def test_holdings_account_mismatch_rejected_and_redacted(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            built, out, _ = _build(base, fixture=EMPTY_EXAMPLE,   # holdings [] vs account holding AAPL
                                   positions=[{"ticker": "AAPL", "direction": "long", "shares": 1,
                                               "avg_cost_usd": 100.0, "entry_date": "20260601"}])
            self.assertNotEqual(built.returncode, 0)
            self.assertFalse(out.exists())
            self.assertNotIn("AAPL", built.stderr)

    def test_duplicate_holdings_rejected_and_redacted(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            def dup(p):
                p["data_context"]["holdings"] = [{"ticker": "AAPL", "signals": {}},
                                                 {"ticker": "AAPL", "signals": {}}]
            fixture = self._fixture_from(base, dup)
            built, out, _ = _build(base, fixture=fixture,
                                   positions=[{"ticker": "AAPL", "direction": "long", "shares": 1,
                                               "avg_cost_usd": 100.0, "entry_date": "20260601"}])
            self.assertNotEqual(built.returncode, 0)
            self.assertFalse(out.exists())
            self.assertNotIn("AAPL", built.stderr)                       # cardinality breach not leaked

    def test_account_value_not_leaked_on_invalid_account(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            account = base / "account_state.json"
            bad = _account([])
            bad["us_short_available_cash"] = 987654.0                    # > bucket -> ACCOUNT_INVALID
            account.write_text(json.dumps(bad), encoding="utf-8")
            out = base / "packet.json"
            built = _run(_build_cmd(base, account=account, fixture=EMPTY_EXAMPLE, out=out))
            self.assertNotEqual(built.returncode, 0)
            self.assertNotIn("987654", built.stderr)                     # account value redacted

    def test_schema_invalid_value_not_leaked(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            fixture = self._fixture_from(base, lambda p: p.update(prior_upgrade_count="LEAKSENTINEL123"))
            built, out, _ = _build(base, fixture=fixture, positions=[])
            self.assertNotEqual(built.returncode, 0)
            self.assertFalse(out.exists())
            self.assertNotIn("LEAKSENTINEL123", built.stderr)            # schema ValidationError value redacted

    def test_schema_dynamic_ticker_path_not_leaked(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            def bad_dynamic_row(p):
                p["data_context"]["universe"] = []
                p["data_context"]["candidate_pass2_signals"] = {}
                p["data_context"]["selection_inputs"]["per_ticker"] = {}
                p["data_context"]["selection_inputs"]["theme_selection_contract"]["per_ticker"] = {}
                p["per_ticker_analysis"] = {"LEAKTICKER": "not-an-object"}
            fixture = self._fixture_from(base, bad_dynamic_row)
            built, out, _ = _build(base, fixture=fixture, positions=[])
            self.assertNotEqual(built.returncode, 0)
            self.assertFalse(out.exists())
            self.assertNotIn("LEAKTICKER", built.stderr)

    def test_case_variant_duplicate_holdings_rejected(self):
        # 'AAPL' and 'aapl' canonicalize to one identity -> cardinality breach before set equality
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            def dup(p):
                p["data_context"]["holdings"] = [{"ticker": "AAPL", "signals": {}},
                                                 {"ticker": "aapl", "signals": {}}]
            fixture = self._fixture_from(base, dup)
            built, out, _ = _build(base, fixture=fixture,
                                   positions=[{"ticker": "AAPL", "direction": "long", "shares": 1,
                                               "avg_cost_usd": 100.0, "entry_date": "20260601"}])
            self.assertNotEqual(built.returncode, 0)
            self.assertFalse(out.exists())
            self.assertNotIn("AAPL", built.stderr)
            self.assertNotIn("aapl", built.stderr)

    def test_runner_duplicate_holdings_rejected_and_redacted(self):
        # the builder blocks dup holdings, so hand-edit a built packet to prove the runner ALSO enforces cardinality
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            built, packet, account = _build(base, fixture=EMPTY_EXAMPLE, positions=[])
            self.assertEqual(built.returncode, 0, built.stderr)
            pkt = json.loads(packet.read_text(encoding="utf-8"))
            pkt["data_context"]["holdings"] = [{"ticker": "AAPL", "signals": {}},
                                               {"ticker": "AAPL", "signals": {}}]
            packet.write_text(json.dumps(pkt), encoding="utf-8")
            account.write_text(json.dumps(_account(
                [{"ticker": "AAPL", "direction": "long", "shares": 1,
                  "avg_cost_usd": 100.0, "entry_date": "20260601"}])), encoding="utf-8")
            ran = _run([str(RUNNER), "--context", str(packet), "--now-et", NOW_ET, "--dry-run"])
            self.assertNotEqual(ran.returncode, 0)
            self.assertNotIn("AAPL", ran.stderr)

    def test_runner_holdings_mismatch_redacted(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            built, packet, account = _build(base, fixture=EMPTY_EXAMPLE, positions=[])
            self.assertEqual(built.returncode, 0, built.stderr)
            # tamper the account AFTER build: now positions={AAPL} but the packet's holdings is [] -> runner mismatch
            account.write_text(json.dumps(_account(
                [{"ticker": "AAPL", "direction": "long", "shares": 1,
                  "avg_cost_usd": 100.0, "entry_date": "20260601"}])), encoding="utf-8")
            ran = _run([str(RUNNER), "--context", str(packet), "--now-et", NOW_ET, "--dry-run"])
            self.assertNotEqual(ran.returncode, 0)
            self.assertNotIn("AAPL", ran.stderr)                         # runner mismatch carries no ticker

    def test_propagated_engine_error_is_redacted(self):
        # a divergent selection-vs-analysis core_score makes the ORCHESTRATOR raise; the runner main() must
        # surface only the error class, never the propagated message (which can echo scores)
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            def diverge(p):
                p["data_context"]["selection_inputs"]["per_ticker"]["AAPL"]["core_score"] = 7777.0
            payload = json.loads(NONEMPTY_EXAMPLE.read_text(encoding="utf-8"))
            diverge(payload)
            fixture = base / "fixture.json"
            fixture.write_text(json.dumps(payload), encoding="utf-8")
            built, packet, _ = _build(base, fixture=fixture, positions=[])
            self.assertEqual(built.returncode, 0, built.stderr)
            ran = _run([str(RUNNER), "--context", str(packet), "--now-et", NOW_ET,
                        "--bootstrap-lifecycle", "--dry-run"])
            self.assertNotEqual(ran.returncode, 0)
            self.assertNotIn("7777", ran.stderr)                         # propagated score not leaked

    def test_runner_top_level_scalar_not_leaked(self):
        with tempfile.TemporaryDirectory() as d:
            packet = Path(d) / "packet.json"
            packet.write_text(json.dumps("LEAKSENTINEL_TOPLEVEL"), encoding="utf-8")
            ran = _run([str(RUNNER), "--context", str(packet), "--now-et", NOW_ET, "--dry-run"])
            self.assertNotEqual(ran.returncode, 0)
            self.assertNotIn("LEAKSENTINEL_TOPLEVEL", ran.stderr)

    def test_runner_unknown_top_level_key_not_leaked(self):
        with tempfile.TemporaryDirectory() as d:
            packet = Path(d) / "packet.json"
            packet.write_text(json.dumps({"LEAKSECRETKEY": 1}), encoding="utf-8")
            ran = _run([str(RUNNER), "--context", str(packet), "--now-et", NOW_ET, "--dry-run"])
            self.assertNotEqual(ran.returncode, 0)
            self.assertNotIn("LEAKSECRETKEY", ran.stderr)


class PublishedCommandShape(unittest.TestCase):
    def test_builder_docstring_uses_powershell_syntax_and_pinned_codex_python(self):
        source = BUILDER.read_text(encoding="utf-8")
        self.assertNotIn("$PythonExe", source)
        self.assertIn(r"& .\tools\codex_main_python.ps1", source)
        self.assertNotIn(r"C:\Path\To\python.exe", source)
        self.assertNotIn(" \\\n", source)

    def test_builder_help_advertises_direct_full_template_input(self):
        result = _run([str(BUILDER), "--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("full 19-key packet/example", result.stdout)


if __name__ == "__main__":
    unittest.main()
