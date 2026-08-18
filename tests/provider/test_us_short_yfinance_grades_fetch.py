from __future__ import annotations

import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_analyst_grade_risk import project_analyst_grade_risk_downgrade  # noqa: E402
from runners import us_short_batch5_full_candidate_pass2_preflight as preflight_runner  # noqa: E402
from runners import us_short_yfinance_grades_fetch as runner  # noqa: E402
from tests.provider.test_us_short_batch5_data_context import (  # noqa: E402
    _DECISION_DATE,
    _candidate_artifact,
    _constant_projection,
)
from tests.provider.us_short_private_test_root import (  # noqa: E402
    temporary_us_short_directory,
    temporary_us_short_state_directory,
)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _grade_row(
    *,
    grade_date: str = "2026-06-10",
    action: str = "down",
    firm: str = "BankA",
    to_grade: str = "Sell",
    from_grade: str = "Hold",
):
    return {
        "GradeDate": grade_date,
        "Action": action,
        "Firm": firm,
        "ToGrade": to_grade,
        "FromGrade": from_grade,
    }


class _FakeTicker:
    def __init__(self, table):
        self._table = table

    @property
    def upgrades_downgrades(self):
        if isinstance(self._table, Exception):
            raise self._table
        return self._table


class _FakeYFinanceClient:
    def __init__(self, tables):
        self._tables = dict(tables)
        self.calls: list[str] = []

    def ticker(self, symbol: str):
        self.calls.append(symbol)
        return _FakeTicker(self._tables.get(symbol, []))


class _NoisyFailingTicker:
    @property
    def upgrades_downgrades(self):
        print('HTTP Error 404: {"quoteSummary":{"error":"No fundamentals data found for symbol: ITIC"}}')
        print('HTTP Error 404: {"quoteSummary":{"error":"No fundamentals data found for symbol: ITIC"}}', file=sys.stderr)
        raise RuntimeError("provider fetch failed")


class _NoisyFailingYFinanceClient:
    def ticker(self, symbol: str):
        return _NoisyFailingTicker()


# What the provider actually prints, matched as the phrases it prints them in.
# `"404"` on its own used to stand in for the third one, and a bare three-digit
# substring is not a provider message: this suite names its artifacts
# `yf_grades_<pid>_<random 5 digits>` and writes those paths into the tracked
# summary, so roughly one run in three hundred drew a number containing 404 and
# turned this red for its own directory name. That is the arbitrary-substring
# trap the very next test in this file exists to warn about.
PROVIDER_NOISE_TOKENS = ("ITIC", "quoteSummary", "HTTP Error 404")


def _leaked_provider_noise(summary_text: str) -> list[str]:
    return [token for token in PROVIDER_NOISE_TOKENS if token in summary_text]


class UsShortYFinanceGradesFetchTest(unittest.TestCase):
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_root = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        self._sample_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_yfinance_grades_fetch" / _DECISION_DATE
        )
        self.sample_root = Path(self._sample_root_context.__enter__())
        self.addCleanup(self._sample_root_context.__exit__, None, None, None)
        self._preflight_root_context = temporary_us_short_directory(
            ROOT, Path("provider_samples") / "us_short_batch5_full_candidate_pass2_preflight" / _DECISION_DATE
        )
        self.preflight_root = Path(self._preflight_root_context.__enter__())
        self.addCleanup(self._preflight_root_context.__exit__, None, None, None)
        for module in (runner, preflight_runner):
            original_git_ignored = module._git_ignored
            private_roots = tuple(root.resolve() for root in (
                self.state_root, self.sample_root, self.preflight_root,
            ))

            def _git_ignored_for_private_test(
                path, *, _original=original_git_ignored, _private_roots=private_roots,
            ):
                resolved = Path(path).resolve()
                if any(resolved == root or root in resolved.parents for root in _private_roots):
                    return True
                return _original(path)

            module._git_ignored = _git_ignored_for_private_test
            self.addCleanup(setattr, module, "_git_ignored", original_git_ignored)
        self.slug = f"yf_grades_{os.getpid()}_{abs(hash(self._testMethodName)) % 100000}"
        self.paths = {
            "candidate": self.state_root / f"{self.slug}_candidate.json",
            "momentum": self.state_root / f"{self.slug}_momentum.json",
            "theme": self.state_root / f"{self.slug}_theme.json",
            "preflight": self.preflight_root / self.slug / "preflight.json",
            "source": self.state_root / f"{self.slug}_source_package.json",
            "resolved": self.state_root / f"{self.slug}_resolved_grade_actions.json",
            "summary": self.sample_root / self.slug / "summary.json",
            "raw_root": self.sample_root / self.slug / "raw",
        }
        for path in self.paths.values():
            self._remove(path)
        _write_json(self.paths["candidate"], _candidate_artifact(("AAPL", "MSFT", "JPM")))
        _write_json(
            self.paths["momentum"],
            _constant_projection(
                "momentum_by_ticker", ("AAPL", "MSFT", "JPM"), "scored", score=50.0,
                candidate_path=self.paths["candidate"], component="momentum",
            ),
        )
        _write_json(
            self.paths["theme"],
            _constant_projection(
                "theme_block_by_ticker", ("AAPL", "MSFT", "JPM"), "scored_theme_base", score=50.0,
                candidate_path=self.paths["candidate"], component="theme",
            ),
        )
        preflight_options = {
            "candidate_artifact_path": self.paths["candidate"],
            "expected_decision_date": _DECISION_DATE,
            "momentum_projection_path": self.paths["momentum"],
            "theme_projection_path": self.paths["theme"],
            "summary_path": self.paths["preflight"],
            "confirm_user_authorization": True,
            "generated_at": "2026-07-10T12:00:00+00:00",
        }
        preview = preflight_runner.run_preflight(**preflight_options)
        preflight_options["authorized_total_call_budget"] = (
            preview["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"]
        )
        preflight_runner.run_preflight(**preflight_options)
        from runners.us_short_weekly_capstone import Pass2BudgetApproval

        preflight = _read_json(self.paths["preflight"])
        self.budget_approval = Pass2BudgetApproval(
            decision_date=preflight["decision_clock"]["expected_decision_date"],
            candidate_price_basis_date=preflight["decision_clock"]["candidate_price_basis_date"],
            candidate_artifact_sha256=preflight["candidate_universe"]["candidate_artifact_sha256"],
            momentum_top_k=preflight["pass2_target_universe"]["momentum_top_k"],
            target_count=preflight["pass2_target_universe"]["target_count"],
            exact_pass2_calls=preflight["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"],
            authorization_mode="manual",
            authorization_ref="manual:test_fixture",
            generated_at=preflight["generated_at"],
        )
        preflight_runner.finalize_preflight_from_existing_derivation(
            preflight_summary_path=self.paths["preflight"],
            approval_binding=self.budget_approval.binding_summary(),
        )

    def tearDown(self):
        for path in self.paths.values():
            self._remove(path)
        self._remove(self.preflight_root / self.slug)
        self._remove(self.sample_root / self.slug)

    def _remove(self, path: Path) -> None:
        if path.is_dir():
            for item in sorted(path.rglob("*"), reverse=True):
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    item.rmdir()
            path.rmdir()
        elif path.exists():
            path.unlink()

    def _run(self, **kwargs):
        options = {
            "preflight_summary_path": self.paths["preflight"],
            "output_source_package_path": self.paths["source"],
            "output_resolved_actions_path": self.paths["resolved"],
            "summary_path": self.paths["summary"],
            "raw_root": self.paths["raw_root"],
            "generated_at": "2026-07-10T12:00:00+00:00",
            "observed_at": "2026-06-15T08:00:00-04:00",
            "pace_seconds": 0,
            "budget_approval": self.budget_approval,
        }
        options.update(kwargs)
        return runner.run_yfinance_grades_fetch(**options)

    def test_missing_authorization_aborts_before_import_client_or_writes(self):
        imports = []
        client = _FakeYFinanceClient({"AAPL": [_grade_row()]})
        with self.assertRaisesRegex(runner.YFinanceGradesFetchError, "explicit user authorization"):
            self._run(
                client=client,
                importer=lambda name: imports.append(name),
                confirm_user_authorization=False,
            )
        self.assertEqual(imports, [])
        self.assertEqual(client.calls, [])
        self.assertFalse(self.paths["summary"].exists())
        self.assertFalse(self.paths["source"].exists())
        self.assertFalse(self.paths["resolved"].exists())

    def test_structural_preflight_schema_failure_remains_fatal_before_provider_or_fallback_writes(self):
        preflight = _read_json(self.paths["preflight"])
        preflight["pass2_target_universe"]["target_symbols"] = []
        _write_json(self.paths["preflight"], preflight)
        client = _FakeYFinanceClient({"AAPL": []})

        with self.assertRaisesRegex(runner.YFinanceGradesFetchError, "target_symbols"):
            self._run(client=client, confirm_user_authorization=True)

        self.assertEqual(client.calls, [])
        self.assertFalse(self.paths["summary"].exists())
        self.assertFalse(self.paths["source"].exists())
        self.assertFalse(self.paths["resolved"].exists())

    def test_default_dry_run_neither_imports_nor_writes(self):
        imports = []
        result = runner.run_default(
            dry_run=True,
            preflight_summary_path=self.paths["preflight"],
            importer=lambda name: imports.append(name),
        )
        self.assertEqual(result["scope"]["status"], "dry_run_only")
        self.assertFalse(result["scope"]["network_access_performed"])
        self.assertEqual(imports, [])
        self.assertFalse(self.paths["summary"].exists())

    def test_default_run_mode_still_requires_explicit_authorization(self):
        imports = []
        with self.assertRaisesRegex(runner.YFinanceGradesFetchError, "explicit user authorization"):
            runner.run_default(
                dry_run=False,
                preflight_summary_path=self.paths["preflight"],
                budget_approval=self.budget_approval,
                importer=lambda name: imports.append(name),
            )
        self.assertEqual(imports, [])
        self.assertFalse(self.paths["summary"].exists())
        self.assertFalse(self.paths["source"].exists())
        self.assertFalse(self.paths["resolved"].exists())

    def test_authorized_fetch_writes_source_resolved_and_hygienic_counts_summary(self):
        client = _FakeYFinanceClient(
            {
                "AAPL": [
                    _grade_row(firm="BankA"),
                    _grade_row(grade_date="2026-06-11", firm="BankB"),
                ],
                "MSFT": [],
                "JPM": [_grade_row(action="up", firm="BankC", to_grade="Buy", from_grade="Hold")],
            }
        )
        summary = self._run(client=client, confirm_user_authorization=True)
        self.assertEqual(summary["scope"]["status"], "completed")
        self.assertEqual(summary["scope"]["provider_status"], "ok")
        self.assertEqual(summary["execution"]["attempted_symbol_count"], 3)
        self.assertEqual(summary["execution"]["successful_symbol_count"], 3)
        self.assertTrue(self.paths["source"].exists())
        self.assertTrue(self.paths["resolved"].exists())
        self.assertEqual(len(list(self.paths["raw_root"].glob("*.json"))), 3)

        summary_text = self.paths["summary"].read_text(encoding="utf-8")
        for forbidden in ("AAPL", "MSFT", "JPM", "BankA", "http", "UNIT_TEST", '"request_url"'):
            self.assertNotIn(forbidden, summary_text)

        resolved = _read_json(self.paths["resolved"])
        projected = project_analyst_grade_risk_downgrade(
            target_tickers=["AAPL", "MSFT", "JPM"],
            analyst_grade_actions=resolved,
        )
        self.assertTrue(projected["analyst_collective_downgrade_by_ticker"]["AAPL"])
        self.assertFalse(projected["analyst_collective_downgrade_by_ticker"]["MSFT"])
        self.assertFalse(projected["analyst_collective_downgrade_by_ticker"]["JPM"])

    def test_provider_console_noise_is_suppressed_and_kept_out_of_summary(self):
        # P3: yfinance can print raw provider errors itself.  The operator sees only the structured outcome;
        # raw message/ticker text is neither echoed nor persisted in the tracked aggregate summary.
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            summary = self._run(client=_NoisyFailingYFinanceClient(), confirm_user_authorization=True)

        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(summary["scope"]["status"], "completed_with_fetch_errors")
        self.assertEqual(summary["execution"]["fetch_error_count"], 3)
        self.assertEqual(list(self.paths["raw_root"].glob("*.json")), [])
        summary_text = self.paths["summary"].read_text(encoding="utf-8")
        self.assertEqual([], _leaked_provider_noise(summary_text))

    def test_the_noise_guard_reads_provider_messages_not_digits_in_a_path(self):
        """The reverse control: it must catch the leak and ignore its own filenames.

        Both halves matter. Without the first the guard could be satisfied by
        matching nothing; without the second it is red whenever this suite happens
        to name a directory `yf_grades_14740_20404`, which is what it did.
        """

        leaked = (
            '{"note": "HTTP Error 404: {\\"quoteSummary\\":{\\"error\\": '
            '\\"No fundamentals data found for symbol: ITIC\\"}}"}'
        )
        self.assertEqual(["ITIC", "quoteSummary", "HTTP Error 404"], _leaked_provider_noise(leaked))
        for slug in ("yf_grades_14740_20404", "yf_grades_404_40404"):
            with self.subTest(slug=slug):
                self.assertEqual(
                    [],
                    _leaked_provider_noise(f'{{"resolved_actions_path": "state/us_short/{slug}.json"}}'),
                )

    def test_summary_guard_matches_ticker_tokens_not_arbitrary_substrings(self):
        summary = self._run(
            client=_FakeYFinanceClient({"AAPL": [], "MSFT": [], "JPM": []}),
            confirm_user_authorization=True,
        )
        # real single-letter tickers M/R/T (Macy's/Ryder/AT&T) + US must NOT false-positive on the fixed
        # `limitations` prose ("Missing"/"Resolver"/"Tracked") or the `scope` identity ("US"/"US-short"); the
        # whole-JSON scan used to abort on them. Only free-form path leaves are ticker-scanned now.
        runner._assert_summary_safe(summary, ["U", "ON", "ALL", "RAW", "M", "R", "T", "US"], [])

        summary["source_artifacts"]["source_package_path"] = "state/us_short/U.json"
        with self.assertRaisesRegex(runner.YFinanceGradesFetchError, "ticker names"):
            runner._assert_summary_safe(summary, ["U"], [])

    def test_post_gate_summary_failure_atomically_replaces_real_outputs_with_full_neutral_set(self):
        client = _FakeYFinanceClient(
            {
                "AAPL": [_grade_row(firm="BankA"), _grade_row(grade_date="2026-06-11", firm="BankB")],
                "MSFT": [],
                "JPM": [_grade_row(action="up", firm="BankC", to_grade="Buy", from_grade="Hold")],
            }
        )
        real_assert = runner._assert_summary_safe

        def reject_primary_summary(summary, target_symbols, sensitive_values):
            if summary["scope"]["status"] != "advisory_stage_neutralized":
                raise runner.YFinanceGradesFetchError("simulated post-gate summary rejection")
            return real_assert(summary, target_symbols, sensitive_values)

        with mock.patch.object(runner, "_assert_summary_safe", side_effect=reject_primary_summary):
            summary = self._run(client=client, confirm_user_authorization=True)

        self.assertEqual(summary["scope"]["status"], "advisory_stage_neutralized")
        self.assertEqual(summary["scope"]["provider_status"], "down")
        self.assertEqual(
            summary["execution"]["advisory_failure"],
            {
                "category": "post_structural_gate_failure",
                "message": "noncritical yfinance stage failed after structural gates; neutralized",
            },
        )
        self.assertEqual(summary["execution"]["attempted_symbol_count"], 3)
        source = _read_json(self.paths["source"])
        self.assertEqual(set(source["grades_by_ticker"]), {"AAPL", "MSFT", "JPM"})
        self.assertTrue(all(not row["records"] for row in source["grades_by_ticker"].values()))
        resolved = _read_json(self.paths["resolved"])
        self.assertEqual(resolved["signals"], {})
        self.assertEqual(set(resolved["excluded"]), {"AAPL", "MSFT", "JPM"})
        self.assertEqual(_read_json(self.paths["summary"]), summary)

    def test_unexpected_post_gate_build_failure_uses_same_neutral_boundary_without_type_sniffing(self):
        client = _FakeYFinanceClient({"AAPL": [_grade_row()], "MSFT": [], "JPM": []})
        with mock.patch.object(
            runner,
            "resolve_yfinance_grade_actions",
            side_effect=RuntimeError("unexpected builder failure with AAPL context"),
        ):
            summary = self._run(client=client, confirm_user_authorization=True)

        self.assertEqual(summary["scope"]["status"], "advisory_stage_neutralized")
        self.assertNotIn("AAPL", self.paths["summary"].read_text(encoding="utf-8"))
        self.assertEqual(set(_read_json(self.paths["resolved"])["excluded"]), {"AAPL", "MSFT", "JPM"})

    def test_dependency_missing_writes_down_neutral_without_raw_payloads(self):
        def _missing(_name):
            raise ModuleNotFoundError("No module named yfinance")

        summary = self._run(importer=_missing, confirm_user_authorization=True)
        self.assertEqual(summary["scope"]["status"], "dependency_missing")
        self.assertEqual(summary["scope"]["provider_status"], "down")
        self.assertFalse(summary["scope"]["network_access_performed"])
        self.assertFalse(summary["scope"]["raw_payload_storage_performed"])
        self.assertFalse(self.paths["raw_root"].exists())
        resolved = _read_json(self.paths["resolved"])
        self.assertEqual(resolved["signals"], {})
        self.assertEqual(set(resolved["excluded"]), {"AAPL", "MSFT", "JPM"})

    def test_broken_yfinance_import_writes_down_neutral_without_raw_payloads(self):
        def _broken(_name):
            raise ImportError("yfinance binary dependency is broken")

        summary = self._run(importer=_broken, confirm_user_authorization=True)
        self.assertEqual(summary["scope"]["status"], "dependency_missing")
        self.assertEqual(summary["scope"]["provider_status"], "down")
        self.assertFalse(self.paths["raw_root"].exists())
        resolved = _read_json(self.paths["resolved"])
        self.assertEqual(resolved["signals"], {})
        self.assertEqual(set(resolved["excluded"]), {"AAPL", "MSFT", "JPM"})

    def test_resolver_rejection_writes_down_neutral_actions_and_hygienic_reason(self):
        summary = self._run(
            client=_FakeYFinanceClient({"AAPL": [_grade_row()], "MSFT": [], "JPM": []}),
            confirm_user_authorization=True,
            observed_at="2026-07-10T12:00:00+00:00",
        )
        self.assertEqual(summary["scope"]["status"], "resolver_rejected_neutralized")
        self.assertEqual(summary["scope"]["provider_status"], "down")
        self.assertEqual(
            summary["execution"]["resolver_rejection"],
            {
                "error_class": "YFinanceGradesError",
                "message": "resolver rejected yfinance package; neutralized",
            },
        )
        self.assertTrue(self.paths["source"].exists())
        self.assertTrue(self.paths["resolved"].exists())
        resolved = _read_json(self.paths["resolved"])
        self.assertEqual(resolved["signals"], {})
        self.assertEqual(set(resolved["excluded"]), {"AAPL", "MSFT", "JPM"})
        projected = project_analyst_grade_risk_downgrade(
            target_tickers=["AAPL", "MSFT", "JPM"],
            analyst_grade_actions=resolved,
        )
        self.assertFalse(any(projected["analyst_collective_downgrade_by_ticker"].values()))
        summary_text = self.paths["summary"].read_text(encoding="utf-8")
        for forbidden in ("AAPL", "MSFT", "JPM", "BankA", "observed_at must be before"):
            self.assertNotIn(forbidden, summary_text)

    def test_duplicate_yfinance_row_is_deduplicated_and_does_not_block_downstream_grade_risk(self):
        row = _grade_row(action="down", firm="  BankA  ")
        client = _FakeYFinanceClient(
            {
                "AAPL": [
                    row,
                    {**row, "Action": " DOWN ", "Firm": "banka"},
                    _grade_row(action="down", firm="BankB"),
                ],
                "MSFT": [],
                "JPM": [],
            }
        )
        summary = self._run(client=client, confirm_user_authorization=True)
        self.assertEqual(summary["scope"]["status"], "completed")
        self.assertTrue(self.paths["source"].exists())
        self.assertTrue(self.paths["resolved"].exists())
        source = _read_json(self.paths["source"])
        self.assertEqual(len(source["grades_by_ticker"]["AAPL"]["records"]), 2)
        resolved = _read_json(self.paths["resolved"])
        projected = project_analyst_grade_risk_downgrade(
            target_tickers=["AAPL", "MSFT", "JPM"],
            analyst_grade_actions=resolved,
        )
        self.assertTrue(projected["analyst_collective_downgrade_by_ticker"]["AAPL"])

    def test_rate_limit_or_crumb_halts_and_writes_neutral_for_every_target(self):
        client = _FakeYFinanceClient({"AAPL": RuntimeError("invalid crumb 429")})
        summary = self._run(client=client, confirm_user_authorization=True)
        self.assertEqual(summary["scope"]["status"], "halted_rate_limit_or_crumb_failure")
        self.assertEqual(summary["scope"]["provider_status"], "down")
        self.assertEqual(summary["execution"]["attempted_symbol_count"], 1)
        self.assertEqual(summary["execution"]["rate_limit_or_crumb_failure_count"], 1)
        resolved = _read_json(self.paths["resolved"])
        self.assertEqual(resolved["signals"], {})
        self.assertEqual(set(resolved["excluded"]), {"AAPL", "MSFT", "JPM"})

    def test_parser_failed_source_is_neutral_for_that_ticker_only(self):
        client = _FakeYFinanceClient(
            {
                "AAPL": [{"GradeDate": "2026-06-10", "Action": "down", "Firm": "BankA", "ToGrade": "Sell"}],
                "MSFT": [_grade_row(action="up", firm="BankB")],
                "JPM": [],
            }
        )
        summary = self._run(client=client, confirm_user_authorization=True)
        self.assertEqual(summary["scope"]["status"], "completed_with_parser_errors")
        self.assertEqual(summary["execution"]["parser_failed_symbol_count"], 1)
        self.assertTrue((self.paths["raw_root"] / "AAPL.json").exists())
        self.assertTrue(summary["scope"]["raw_payload_storage_performed"])
        resolved = _read_json(self.paths["resolved"])
        self.assertNotIn("AAPL", resolved["signals"])
        self.assertIn("AAPL", resolved["excluded"])
        self.assertIn("MSFT", resolved["signals"])
        self.assertIn("JPM", resolved["checked"])

    def test_window_aware_normalization_skips_old_bad_rows_but_keeps_in_window_gap_partial(self):
        rows = [
            _grade_row(firm=f"Bank{index}")
            for index in range(927)
        ]
        rows.append(_grade_row(grade_date="2012-11-27", firm="HistoricalBank"))
        rows.append({
            "GradeDate": "2012-11-28",
            "Action": "main",
            "Firm": "Nomura",
            "ToGrade": "",
            "FromGrade": "",
            "priceTargetAction": "Maintains",
        })

        attempt, raw_rows = runner._fetch_one(
            _FakeYFinanceClient({"MSFT": rows}),
            "MSFT",
            source_as_of="2026-07-10",
        )
        self.assertEqual(len(attempt["records"]), 928)
        self.assertEqual((attempt["coverage"], attempt["parser"]), ("full", "ok"))
        self.assertEqual(len(raw_rows), 929)
        self.assertIn("2012-11-27", {row["GradeDate"] for row in attempt["records"]})

        in_window_gap = {
            **_grade_row(grade_date="2026-07-01", firm="MissingGrade"),
            "ToGrade": "",
            "priceTargetAction": "",
        }
        attempt, _ = runner._fetch_one(
            _FakeYFinanceClient({"MSFT": [_grade_row(firm="ValidBank"), in_window_gap]}),
            "MSFT",
            source_as_of="2026-07-10",
        )
        self.assertEqual(len(attempt["records"]), 1)
        self.assertEqual((attempt["coverage"], attempt["parser"]), ("partial", "ok"))
        resolved = runner.resolve_yfinance_grade_actions(
            as_of="2026-07-10",
            grades_by_ticker={
                "MSFT": {
                    "records": attempt["records"],
                    "provenance": {
                        "provider_id": "yfinance",
                        "endpoint_or_filing_type": "upgrades_downgrades",
                        "source_as_of": "2026-07-10",
                        "observed_at": "2026-07-10T08:00:00-04:00",
                        "coverage_status": attempt["coverage"],
                        "parser_status": attempt["parser"],
                        "lineage_ref": "yfinance:upgrades_downgrades:2026-07-10#msftyfinancegrades",
                    },
                }
            },
        )
        self.assertIn("MSFT", resolved["excluded"])

    def test_normalization_regressions_keep_aapl_shape_empty_table_and_fail_closed_edges(self):
        fields = ["Action", "Firm", "ToGrade", "FromGrade", "GradeDate"]
        aapl_rows = [
            _grade_row(firm=f"Bank{index}")
            for index in range(967)
        ] + [
            _grade_row(firm="Bank0"),
            _grade_row(firm="Bank1"),
        ]
        normalized, coverage, parser = runner._normalized_source_rows(
            "AAPL", fields, aapl_rows, source_as_of="2026-07-10"
        )
        self.assertEqual(len(normalized), 967)
        self.assertEqual((coverage, parser), ("full", "ok"))

        self.assertEqual(
            runner._normalized_source_rows("AAPL", fields, [], source_as_of="2026-07-10"),
            ([], "full", "ok"),
        )
        invalid_date = _grade_row(grade_date="not-a-date")
        self.assertEqual(
            runner._normalized_source_rows("AAPL", fields, [invalid_date], source_as_of="2026-07-10")[1:],
            ("partial", "failed"),
        )
        self.assertEqual(
            runner._normalized_source_rows(
                "AAPL", ["Action", "Firm", "ToGrade", "GradeDate"], [_grade_row()], source_as_of="2026-07-10"
            )[1:],
            ("partial", "failed"),
        )

    def test_summary_schema_rejects_emit_gate_or_scope_drift(self):
        client = _FakeYFinanceClient({"AAPL": [], "MSFT": [], "JPM": []})
        summary = self._run(client=client, confirm_user_authorization=True)
        summary["prohibited_claims"]["emit_gate_source"] = True
        with self.assertRaisesRegex(runner.YFinanceGradesFetchError, "schema validation"):
            runner._validate_json_schema(summary, runner.SUMMARY_SCHEMA_PATH, label="mutated summary")


if __name__ == "__main__":
    unittest.main()
