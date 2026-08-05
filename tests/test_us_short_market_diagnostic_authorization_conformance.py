"""Encode the two quantifiers this track keeps getting wrong.

Two defect classes have now recurred across knives 1, 2, 3, 5, 6 and 7:

* **A guard exists but only on some of the paths that matter.** The window anchor
  lived on the trigger path but not the compute path; ``as_of_date`` was built in
  one module and forwarded by none; the clock gate covered writes while the
  scorecard — the only thing this track produces — was published ungated.
* **Something named "verify" re-reads a value the artifact itself supplied.** A
  benchmark week asserted it was total-return with nothing bound to a dividend
  digest; the register's own anchor field was fed back into the expected register
  and compared with itself.

Both were re-introduced immediately after being closed, by the same person who
had just read the rule against re-introducing them. So the rule is written here
as a test instead: a new ungated consumer, or a verification that cannot notice
its own source changing, fails this file rather than waiting for a reviewer to
have the right thought on the right day.
"""
from __future__ import annotations

import ast
from pathlib import Path
import tempfile
import unittest

import engine.us_short_market_diagnostic_start_receipt as receipts
from engine.us_short_market_diagnostic_aggregator import (
    MarketDiagnosticAggregationError,
    build_market_diagnostic_report,
    write_market_diagnostic_report,
)
from engine.us_short_market_diagnostic_lifecycle import (
    MarketDiagnosticLifecycleError,
    load_lifecycle_register,
    load_settled_weekly_records,
    persist_settled_weekly_record,
)
from tests.test_us_short_market_diagnostic import _weekly_rows


ROOT = Path(__file__).resolve().parents[1]

# Every module that can reach the private diagnostic store.
# A module is in scope when it can actually reach the private diagnostic store —
# because it names the store, or because it imports one of the modules that owns
# it. Derived rather than hand-listed so a new consumer joins the surface by
# existing, not by somebody remembering to add it; scoped by what a module DOES
# rather than by its filename, so the pure calculators stay out.
_STORE_OWNERS = (
    "us_short_market_diagnostic_lifecycle",
    "us_short_market_diagnostic_start_receipt",
)
# Markers must name THIS store. `lifecycle_register.json` is a filename several
# unrelated us_short stores use, so it selects modules that cannot reach the
# diagnostic private root at all — a surface full of false positives is a surface
# nobody keeps honest.
_STORE_MARKERS = (
    "market_diagnostic_private",
    "diagnostic_start_receipt.json",
) + _STORE_OWNERS


def _surface_modules() -> list[str]:
    """Scoped by what a module DOES, over every engine and runner there is.

    The previous version globbed ``us_short_market_diagnostic*.py`` first and
    applied the marker test inside that glob, so a module could reach the store
    and still never join the surface as long as it was named something else.
    ``engine/us_short_weekly_report_renderer.py`` — which already owns the
    section this track reports into, and is where section 12.8 lands next — is
    exactly such a module. The filename filter is gone; only behaviour selects.
    """

    found = []
    for folder in ("engine", "runners"):
        for path in sorted((ROOT / folder).glob("*.py")):
            source = path.read_text(encoding="utf-8")
            stem = path.stem
            if stem in _STORE_OWNERS or any(marker in source for marker in _STORE_MARKERS):
                found.append(f"{folder}/{path.name}")
    return found


SURFACE = tuple(_surface_modules())
# The producers of the published verdict must not be able to accept the artifact
# and the store as independent arguments: that shape is what let a fabricated
# history be published against an authorized store while a gate call sat in the
# body doing nothing. Judged by SHAPE, because "a gate name appears" is satisfied
# by a call whose result is discarded.
PUBLISH_PATH = {
    "build_market_diagnostic_report",
    "write_market_diagnostic_report",
    "publish_completed_market_diagnostic_window",
}
# An ALLOWLIST, not a blocklist. A blocklist of artifact-sounding names was the
# same syntax-layer mistake one level up: renaming the parameter `settled_weeks`
# walked straight through it. What a verdict producer is allowed to be told is
# where to read from and when — everything else it must fetch itself.
PUBLISH_PATH_ALLOWED_PARAMS = frozenset({"lifecycle_root", "output_root", "as_of_date"})
# There is deliberately no filter here. The previous version decided "does this
# function reach the store?" by looking at whether a parameter happened to be
# named `root` — a convenient handle, not the property. It was blind to eleven of
# the aggregator's twelve functions, including all three that actually produce the
# published verdict. The domain is now every function in the surface, and the only
# way out is a named exemption.
GATES = frozenset(
    {
        "assert_first_week_is_authorized",
        "assert_clock_authorization_still_holds",
        "_require_start_receipt",
        "_require_unchanged_anchor",
        # Delegating to a gated public entry counts: the check still happens.
        "load_lifecycle_register",
        "load_settled_weekly_records",
        "persist_settled_weekly_record",
        "publish_completed_market_diagnostic_window",
        "_authorized_records",
        "build_market_diagnostic_report",
        # Supplier-style, like _authorized_records: it reads the clock and the
        # store and hands back what the next week must be, so a caller cannot
        # choose the index or continue the NAV series from a number it invented.
        "next_week_inputs",
        # The single four-state decider every reader goes through. It calls the
        # gated receipt and register loaders itself and hands back what it found,
        # so a reader cannot reach its own conclusion about a store it never read.
        "diagnostic_store_state",
    }
)

# Exemptions must name a reason. If a function in this surface cannot say why it
# needs no authorization check, it needs one. Pure helpers that never touch the
# store or the verdict are exempt; anything that reads the store or produces the
# published artifact is not.
EXEMPT = {
    "engine/us_short_market_diagnostic_aggregator.py::_load_schema": "loads a schema",
    "engine/us_short_market_diagnostic_aggregator.py::_number": "formats a number",
    "engine/us_short_market_diagnostic_aggregator.py::_publicize_window_summary": "projects a summary in hand",
    "engine/us_short_market_diagnostic_aggregator.py::_report_output_paths": "resolves a public output path; no store read",
    "engine/us_short_market_diagnostic_aggregator.py::_summary_lines": "formats a summary in hand",
    "engine/us_short_market_diagnostic_aggregator.py::_validate_public_summary": "validates a summary in hand",
    "engine/us_short_market_diagnostic_aggregator.py::_validate_report": "validates a report in hand",
    "engine/us_short_market_diagnostic_aggregator.py::_write_bytes": "byte writer for an already-derived report",
    "engine/us_short_market_diagnostic_aggregator.py::render_market_diagnostic_markdown": "renders a report the gated builder produced; writes nothing",
    "engine/us_short_market_diagnostic_lifecycle.py::_as_of": "parses a date",
    "engine/us_short_market_diagnostic_lifecycle.py::_atomic_write": "byte writer for a value the caller already validated",
    "engine/us_short_market_diagnostic_lifecycle.py::_date8": "parses a date",
    "engine/us_short_market_diagnostic_lifecycle.py::_derive_v1_1_attribution": "pure derivation from records in hand",
    "engine/us_short_market_diagnostic_lifecycle.py::_load_records_for_register": "internal to the gated loader",
    "engine/us_short_market_diagnostic_lifecycle.py::_load_schema": "loads a schema",
    "engine/us_short_market_diagnostic_lifecycle.py::_not_future": "compares two dates",
    "engine/us_short_market_diagnostic_lifecycle.py::_private_path": "resolves and privacy-checks a path; no store read",
    "engine/us_short_market_diagnostic_lifecycle.py::_private_root": "resolves and privacy-checks a path; no store read",
    "engine/us_short_market_diagnostic_lifecycle.py::_read_canonical_json": "reads one named file the caller resolved",
    "engine/us_short_market_diagnostic_lifecycle.py::_record_files": "lists filenames for the gated loaders",
    "engine/us_short_market_diagnostic_lifecycle.py::_record_relative_path": "derives a path string from a record in hand",
    "engine/us_short_market_diagnostic_lifecycle.py::_register_from_records": "pure register derivation from records in hand",
    "engine/us_short_market_diagnostic_lifecycle.py::_require_weekly_cadence": "compares two dates",
    "engine/us_short_market_diagnostic_lifecycle.py::_schema_validate": "validates a value in hand",
    "engine/us_short_market_diagnostic_lifecycle.py::_validate_weekly_record_for_store": "validates a record in hand",
    "engine/us_short_market_diagnostic_lifecycle.py::build_v1_1_reminder": "pure reminder from counts in hand",
    "engine/us_short_market_diagnostic_lifecycle.py::build_weekly_report_reminder": "pure reminder from a register in hand",
    "engine/us_short_market_diagnostic_lifecycle.py::render_weekly_report_reminder": "renders a reminder in hand",
    "engine/us_short_market_diagnostic_start_receipt.py::_aware_instant": "parses a timestamp",
    "engine/us_short_market_diagnostic_start_receipt.py::_date8": "parses a date",
    "engine/us_short_market_diagnostic_start_receipt.py::_fail": "raises",
    "engine/us_short_market_diagnostic_start_receipt.py::_mapping": "type guard",
    "engine/us_short_market_diagnostic_start_receipt.py::_path_like": "type guard",
    "engine/us_short_market_diagnostic_start_receipt.py::_private_root": "resolves and privacy-checks a path; no store read",
    "engine/us_short_market_diagnostic_start_receipt.py::_receipt_path": "resolves and privacy-checks a path; no store read",
    "engine/us_short_market_diagnostic_start_receipt.py::_text_digest": "pure digest",
    "engine/us_short_market_diagnostic_start_receipt.py::_validator": "loads a schema",
    "engine/us_short_market_diagnostic_start_receipt.py::assert_clock_authorization_still_holds": "is the gate",
    "engine/us_short_market_diagnostic_start_receipt.py::assert_first_week_is_authorized": "is the gate",
    "engine/us_short_market_diagnostic_start_receipt.py::build_start_receipt": "assembles the authorization before one exists",
    "engine/us_short_market_diagnostic_start_receipt.py::design_authority_sha256": "pure digest of the frozen contract block",
    "engine/us_short_market_diagnostic_start_receipt.py::design_contract_block": "reads the design document, not the store",
    "engine/us_short_market_diagnostic_start_receipt.py::issue_start_receipt": "creates the authorization",
    "engine/us_short_market_diagnostic_start_receipt.py::load_start_receipt": "reads the authorization itself",
    "engine/us_short_market_diagnostic_start_receipt.py::start_receipt_sha256": "pure digest of a receipt already in hand",
    "engine/us_short_market_diagnostic_start_receipt.py::validate_start_receipt": "validates the authorization itself",
    "engine/us_short_market_diagnostic_weekly_producer.py::_load_preset": "reads a named preset file; no store",
    "engine/us_short_market_diagnostic_weekly_producer.py::has_counted_weeks": "existence probe over the weekly records; reads no content and authorizes nothing",
    "engine/us_short_market_diagnostic_weekly_producer.py::model_paper_week_is_settled": "reads the model-paper store, not the diagnostic store",
    "engine/us_short_market_diagnostic_weekly_producer.py::build_no_count_record": "projects a packet in hand; touches no store",
    "engine/us_short_market_diagnostic_weekly_producer.py::_target_week": "picks the packet week the gated inputs allow; reads through the gated loader",
    "engine/us_short_market_diagnostic_weekly_producer.py::diagnostic_policy_sha256": "pure digest of a preset",
    "engine/us_short_market_diagnostic_weekly_producer.py::strategy_ruleset_fingerprint": "pure digest of the declared governed presets",
    "runners/us_short_market_diagnostic_weekly.py::_parse_args": "argument parsing",
    "runners/us_short_market_diagnostic_weekly.py::_read_json": "reads one named file the caller resolved",
    "runners/us_short_market_diagnostic_weekly.py::_read_notification": "reads one named file the caller resolved",
    "runners/us_short_market_diagnostic_weekly.py::main": "dispatches to gated or exempt subcommands",
    "runners/us_short_market_diagnostic_weekly.py::open_clock": "is the operator act of authorizing",
}


def _reachable_calls(node: ast.AST) -> set[str]:
    """Names called on a path that actually runs when this function runs.

    Two things earn no credit, because both are how "a gate name appears in the
    body" gets satisfied without a gate ever running: a call parked inside a
    nested ``def``/``lambda`` that nothing invokes, and a call under a branch
    whose condition is a literal that can never be true.
    """

    found: set[str] = set()
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(child, ast.If):
            test = child.test
            if isinstance(test, ast.Constant) and not test.value:
                for orelse in child.orelse:
                    found |= _reachable_calls(orelse)
                continue
            if isinstance(test, ast.Constant) and test.value:
                found |= _reachable_calls(test)
                for body in child.body:
                    found |= _reachable_calls(body)
                continue
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                found.add(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                found.add(child.func.attr)
        found |= _reachable_calls(child)
    return found


def _declared_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Every name this function can be handed a value under.

    ``args`` and ``kwonlyargs`` alone were not the parameter list: declaring the
    same parameter positional-only (``records=None, /``) or variadic
    (``**records``) was invisible to the shape check, which is one token away
    from silently restoring the API the whole fix removed.
    """

    spec = node.args
    names = {a.arg for a in spec.posonlyargs + spec.args + spec.kwonlyargs}
    for extra in (spec.vararg, spec.kwarg):
        if extra is not None:
            names.add(extra.arg)
    return names


def _surface_functions() -> list[tuple[str, str, set[str], set[str]]]:
    """Every function in the surface, including class methods. No filter, by design."""

    found: list[tuple[str, str, set[str], set[str]]] = []
    for relative in SURFACE:
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            found.append((relative, node.name, _reachable_calls(node), _declared_params(node)))
    return found


class AuthorizationConformanceTest(unittest.TestCase):
    def test_every_store_touching_function_is_gated_or_explicitly_exempt(self) -> None:
        """The quantifier that was wrong twice, written down so it cannot be wrong again."""

        functions = _surface_functions()
        self.assertGreater(len(functions), 10, "the surface scan found suspiciously little")
        ungated = [
            f"{relative}::{name}"
            for relative, name, called, _params in functions
            if not called.intersection(GATES) and f"{relative}::{name}" not in EXEMPT
        ]
        self.assertEqual(
            [],
            ungated,
            "these reach the diagnostic store without checking that the clock is authorized; "
            "gate them, or add an entry to EXEMPT saying why they need no gate",
        )

    def test_the_publish_path_cannot_take_the_artifact_and_the_store_apart(self) -> None:
        """The shape check that a call-presence check cannot make.

        A gate call in the body proves nothing if the thing gated and the thing
        published arrive as separate arguments: that is exactly how a fabricated
        26-week history was published against an authorized store holding one.
        Removing the artifact parameter removes the opportunity.
        """

        offenders = sorted(
            f"{relative}::{name}({sorted(params - PUBLISH_PATH_ALLOWED_PARAMS)})"
            for relative, name, _called, params in _surface_functions()
            if name in PUBLISH_PATH and params - PUBLISH_PATH_ALLOWED_PARAMS
        )
        self.assertEqual(
            [],
            offenders,
            "a verdict producer accepts something other than where to read and when; "
            "have it fetch the weeks through the gated loader instead",
        )

    def test_the_publish_path_cannot_be_exempted_from_the_gate(self) -> None:
        """The hole this file shipped with, closed as a shape rather than a habit.

        Both verdict producers were on EXEMPT — so the one test with power over
        the publish path had none over the two functions the entire effort was
        about. Inlining an ungated read into the builder kept 41 tests green and
        published a 26-week scorecard from a store whose receipt had been
        deleted. An exemption list that may exempt anything is not a list of
        exceptions, it is an off switch.
        """

        exempted = sorted(key for key in EXEMPT if key.rsplit("::", 1)[-1] in PUBLISH_PATH)
        self.assertEqual(
            [],
            exempted,
            "a verdict producer is on EXEMPT; the publish path is the one thing this "
            "file exists to hold, and it may not opt out",
        )

    def test_the_exempt_list_does_not_outlive_its_functions(self) -> None:
        """A stale exemption is a hole waiting for a name collision."""

        live = {f"{relative}::{name}" for relative, name, _c, _p in _surface_functions()}
        self.assertEqual(set(), set(EXEMPT) - live, "EXEMPT names functions that no longer exist")

    def test_the_public_read_and_publish_entries_are_in_the_gated_set(self) -> None:
        """Named explicitly, because these are the ones that produce the verdict."""

        gated = {
            name
            for _, name, called, _p in _surface_functions()
            if called.intersection(GATES)
        }
        for name in ("load_lifecycle_register", "load_settled_weekly_records", "persist_settled_weekly_record"):
            self.assertIn(name, gated)


class SourceDriftTest(unittest.TestCase):
    """A check that cannot notice its source changing is not a check.

    Tampering with the artifact is the easy half and was already covered. This is
    the half that was missing: leave the artifact alone and move what it claims to
    be bound to. An identity comparison passes that; a real verification does not.
    """

    def setUp(self) -> None:
        self.rows = _weekly_rows()
        self.notification = {
            "issued_at": "2025-12-29T00:00:00+00:00",
            "issuer": "codex",
            "notification_text": "US-short 26-week diagnostic design is complete.",
        }

    def _open(self, root):
        return receipts.issue_start_receipt(
            diagnostic_epoch=self.rows[0]["diagnostic_epoch"],
            completion_notification=dict(self.notification),
            first_decision_date=self.rows[0]["decision_date"],
            root=root,
        )

    def test_removing_the_anchor_is_noticed_by_every_public_reader(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            self._open(root)
            for row in self.rows[:3]:
                persist_settled_weekly_record(row, root=root)
            (root / receipts.RECEIPT_FILENAME).unlink()

            for reader in (load_lifecycle_register, load_settled_weekly_records):
                with self.assertRaises(MarketDiagnosticLifecycleError, msg=reader.__name__):
                    reader(root)

    def test_an_unauthorized_store_cannot_publish_anything(self) -> None:
        """The behaviour the shape rule exists to produce, asserted end to end.

        Every other check here is structural — it reads source. This one runs the
        publish path against a store whose receipt is gone and insists nothing
        comes out, so the rule survives a refactor that keeps the shape and loses
        the effect.
        """

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            output_root = Path(td) / "public"
            self._open(root)
            for row in self.rows[:3]:
                persist_settled_weekly_record(row, root=root)
            (root / receipts.RECEIPT_FILENAME).unlink()

            with self.assertRaises(MarketDiagnosticAggregationError):
                build_market_diagnostic_report(lifecycle_root=root)
            with self.assertRaises(MarketDiagnosticAggregationError):
                write_market_diagnostic_report(lifecycle_root=root, output_root=output_root)
            self.assertFalse(output_root.exists(), "an unauthorized store left bytes behind")

    def test_the_anchor_cannot_be_moved_under_a_running_count(self) -> None:
        """Re-anchoring updates the receipt AND the register, so a digest match is not enough.

        The closure criterion of the previous round's P1: what is actually bound
        is the week the clock counted from, not the pointer to the receipt.
        """

        import json

        from engine.us_short_model_paper_portfolio import canonical_json_bytes

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            self._open(root)
            for row in self.rows[:3]:
                persist_settled_weekly_record(row, root=root)

            (root / receipts.RECEIPT_FILENAME).unlink()
            moved = receipts.issue_start_receipt(
                diagnostic_epoch=self.rows[0]["diagnostic_epoch"],
                completion_notification=dict(self.notification),
                first_decision_date="20260109",
                root=root,
            )
            self.assertNotEqual(self.rows[0]["decision_date"], "20260109")

            path = root / "lifecycle_register.json"
            register = json.loads(path.read_bytes().decode("utf-8"))
            register["start_receipt_sha256"] = moved["receipt_sha256"]
            path.write_bytes(canonical_json_bytes(register))

            with self.assertRaises(MarketDiagnosticLifecycleError) as ctx:
                load_lifecycle_register(root)
            self.assertIn("different week 1", str(ctx.exception))

    def test_a_moved_anchor_that_changes_epoch_is_also_refused(self) -> None:
        """The second half of the same branch, which the week-1 case does not reach."""

        import json

        from engine.us_short_model_paper_portfolio import canonical_json_bytes

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            self._open(root)
            persist_settled_weekly_record(self.rows[0], root=root)

            (root / receipts.RECEIPT_FILENAME).unlink()
            moved = receipts.issue_start_receipt(
                diagnostic_epoch="us-short-26w-relabelled",
                completion_notification=dict(self.notification),
                first_decision_date=self.rows[0]["decision_date"],
                root=root,
            )
            path = root / "lifecycle_register.json"
            register = json.loads(path.read_bytes().decode("utf-8"))
            register["start_receipt_sha256"] = moved["receipt_sha256"]
            path.write_bytes(canonical_json_bytes(register))

            with self.assertRaises(MarketDiagnosticLifecycleError) as ctx:
                load_lifecycle_register(root)
            self.assertIn("different diagnostic epoch", str(ctx.exception))

    def test_the_register_anchor_is_derived_from_the_receipt_not_from_itself(self) -> None:
        """Rewriting the register's own claim must not be self-consistent."""

        import json

        from engine.us_short_model_paper_portfolio import canonical_json_bytes

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            self._open(root)
            persist_settled_weekly_record(self.rows[0], root=root)

            path = root / "lifecycle_register.json"
            register = json.loads(path.read_bytes().decode("utf-8"))
            register["start_receipt_sha256"] = "d" * 64
            path.write_bytes(canonical_json_bytes(register))
            with self.assertRaises(MarketDiagnosticLifecycleError):
                load_lifecycle_register(root)

    def _with_design(self, td, body: str):
        """Point the design-authority lookup at a fixture document."""

        drifted = Path(td) / "drifted_repo"
        target = drifted / receipts.DESIGN_AUTHORITY_RELATIVE_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return drifted

    @staticmethod
    def _design_document(*, status_priority_first: str = "unavailable", prose: str = "") -> str:
        return (
            "# design\n"
            f"{prose}"
            "## 12.1 Machine-bound v1 summary and status contract\n\n"
            "```json\n"
            "{\n"
            '  "v1_summary_strategy_metric_fields": ["since_inception_return"],\n'
            '  "v1_summary_benchmark_metric_fields": ["information_ratio"],\n'
            f'  "status_priority": ["{status_priority_first}"]\n'
            "}\n"
            "```\n"
        )

    def test_the_design_digest_notices_the_contract_moving_underneath_it(self) -> None:
        """The receipt is untouched; only the contract it names changes."""

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            original = receipts._DESIGN_AUTHORITY_ROOT
            try:
                receipts._DESIGN_AUTHORITY_ROOT = self._with_design(td, self._design_document())
                self._open(root)
                receipts._DESIGN_AUTHORITY_ROOT = self._with_design(
                    td, self._design_document(status_priority_first="data_degraded")
                )
                with self.assertRaises(receipts.DiagnosticStartReceiptError) as ctx:
                    receipts.load_start_receipt(root)
                self.assertIn("contract on disk", str(ctx.exception))
            finally:
                receipts._DESIGN_AUTHORITY_ROOT = original

    def test_editing_the_prose_around_the_contract_does_not_brick_the_clock(self) -> None:
        """The other half, and the reason the digest is scoped the way it is.

        The design document is still being written and the risk register requires
        some of those edits. Whole-file hashing made every one of them a silent
        kill switch on a running 26-week clock — evidence destroyed by a sentence
        somewhere else in the file.
        """

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            original = receipts._DESIGN_AUTHORITY_ROOT
            try:
                receipts._DESIGN_AUTHORITY_ROOT = self._with_design(td, self._design_document())
                self._open(root)
                persist_settled_weekly_record(self.rows[0], root=root)
                receipts._DESIGN_AUTHORITY_ROOT = self._with_design(
                    td, self._design_document(prose="Knife 7 has now executed.\n\n")
                )
                self.assertIsNotNone(receipts.load_start_receipt(root))
                persist_settled_weekly_record(self.rows[1], root=root)
                self.assertEqual(2, load_lifecycle_register(root)["calendar_week_count"])
            finally:
                receipts._DESIGN_AUTHORITY_ROOT = original

    def test_twenty_six_consecutive_days_are_not_twenty_six_weeks(self) -> None:
        import copy
        import datetime

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "market_diagnostic_private"
            self._open(root)
            persist_settled_weekly_record(self.rows[0], root=root)

            daily = copy.deepcopy(self.rows[1])
            start = datetime.date(2026, 1, 2) + datetime.timedelta(days=1)
            daily["decision_date"] = start.strftime("%Y%m%d")
            daily["valuation_date"] = daily["decision_date"]
            with self.assertRaises(MarketDiagnosticLifecycleError) as ctx:
                persist_settled_weekly_record(daily, root=root)
            self.assertIn("seven days", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
