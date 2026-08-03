from __future__ import annotations

import ast
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
import unittest
from unittest import mock

from engine import us_short_llm_theme_discovery_plan_budget as plan_budget
from engine import us_short_llm_theme_discovery_paid_gateway as paid_gateway
from engine import us_short_llm_theme_discovery_provider_policy as provider_policy
from engine import us_short_llm_theme_discovery_query_plan as query_plan
from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from tests.provider.us_short_private_test_root import temporary_us_short_state_directory


ROOT = plan_budget.ROOT
DECISION_DATE = "20260808"
STAMP = "2026-08-02T12:00:00Z"


def _noop_persist(_request, _value):
    """Explicit test sink for orchestration-only tests that do not build raw receipts."""
    return None


def _parent(*, stage1: int = 1, stage2: int = 1, retry: int = 1) -> dict:
    envelopes = [
        {
            "provider": "web",
            "stage1_max_dispatch_count": stage1,
            "stage2_max_dispatch_count": stage2,
            "retry_max_dispatch_count": retry,
            "max_dispatch_count": stage1 + stage2 + retry,
        },
        {
            "provider": "xai",
            "stage1_max_dispatch_count": 1,
            "stage2_max_dispatch_count": 0,
            "retry_max_dispatch_count": 1,
            "max_dispatch_count": 2,
        },
    ]
    return query_plan.build_parent_plan(
        decision_date=DECISION_DATE,
        policy_version="soft_discovery_query_policy_v0.1.0",
        policy_template_content_sha256="a" * 64,
        stage1_queries=[
            {"query_id": "stage1-a", "query_text": "Find demand shifts."},
        ],
        stage2_rule_sha256="b" * 64,
        provider_envelopes=envelopes,
        generated_at=STAMP,
    )


def _function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(
        candidate for candidate in tree.body
        if isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef)) and candidate.name == name
    )
    return "\n".join(source.splitlines()[node.lineno - 1:node.end_lineno])


def _canonical_control_sites(source: str) -> list[tuple[str, str]]:
    """Derive every provider BaseException outlet that consults the canonical control rule."""
    tree = ast.parse(source)
    sites: list[tuple[str, str]] = []

    def visit(body: list[ast.stmt], owner: str = "") -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit(node.body, f"{owner}.{node.name}" if owner else node.name)
                continue
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            has_control_handler = any(
                isinstance(handler, ast.ExceptHandler)
                and isinstance(handler.type, ast.Name)
                and handler.type.id == "BaseException"
                and any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "is_control_error"
                    for call in ast.walk(handler)
                )
                for handler in ast.walk(node)
            )
            if has_control_handler:
                sites.append((owner or "<module>", node.name))

    visit(tree.body)
    return sorted(set(sites))


def _reads_mapping_field(source: str, function_name: str, field: str) -> bool:
    """Read a semantic field through AST, so a string-only check cannot self-certify."""
    tree = ast.parse(source)
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    )
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "get" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and first.value == field:
            return True
    return False


def _plan_reservation_order_offenders(source: str) -> list[str]:
    tree = ast.parse(source)
    calls = [
        (
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id,
            node.lineno,
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
        and (node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id)
        in {"reserve_plan_budget", "execute_live_web_orchestration"}
    ]
    reserve = [line for name, line in calls if name == "reserve_plan_budget"]
    spend = [line for name, line in calls if name == "execute_live_web_orchestration"]
    if not reserve or not spend:
        return ["missing plan reservation or paid orchestration"]
    return [] if min(reserve) < min(spend) else ["plan reservation must precede paid orchestration"]


def _class_a_default_none_offenders(paths: list[Path]) -> list[tuple[str, str, str, int]]:
    offenders: list[tuple[str, str, str, int]] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = list(node.args.args) + list(node.args.kwonlyargs)
            defaults = (
                [None] * (len(node.args.args) - len(node.args.defaults))
                + list(node.args.defaults)
                + list(node.args.kw_defaults)
            )
            for arg, default in zip(args, defaults):
                if (
                    node.name in {"_run_web_fetch", "_run_x_fetch", "runner"}
                    and any(token in arg.arg.lower() for token in ("budget", "plan", "raw_root"))
                    and isinstance(default, ast.Constant)
                    and default.value is None
                ):
                    offenders.append((path.name, node.name, arg.arg, node.lineno))
    return offenders


def _dispatch_outlet_functions(path: Path) -> list[tuple[str, str]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    result: list[tuple[str, str]] = []
    for call in ast.walk(tree):
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "dispatch_with_outcome"
        ):
            continue
        owner = next(
            (node for node in functions if node.lineno <= call.lineno <= node.end_lineno),
            None,
        )
        if owner is not None:
            result.append((owner.name, _function_source(source, owner.name)))
    return result


def _schema_contract_field_names(value: object) -> set[str]:
    fields: set[str] = set()
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            fields.update(key for key in properties if isinstance(key, str))
        required = value.get("required")
        if isinstance(required, list):
            fields.update(item for item in required if isinstance(item, str))
        for child in value.values():
            fields.update(_schema_contract_field_names(child))
    elif isinstance(value, list):
        for child in value:
            fields.update(_schema_contract_field_names(child))
    return fields


def _replace_once(source: str, needle: str, replacement: str) -> str:
    head, separator, tail = source.partition(needle)
    if not separator:
        return source
    return head + replacement + tail


def _replace_all(source: str, needle: str, replacement: str) -> str:
    return replacement.join(source.split(needle))


class PlanBudgetAcceptanceTests(unittest.TestCase):
    def _reserved(self, parent: dict, state: Path) -> plan_budget.PlanDispatchBudget:
        return plan_budget.reserve_plan_budget(
            parent, state_dir=state, root=ROOT, gitignored=lambda _path: True,
        )

    def _ledger(self, state: Path, provider: str = "web") -> dict:
        path = plan_budget._ledger_path(
            provider=provider, decision_date=DECISION_DATE, state_dir=state,
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def test_A4_B1_plan_reservation_precedes_first_paid_call_static_reference(self):
        parent = _parent()
        with temporary_us_short_state_directory(ROOT) as raw:
            state = Path(raw)
            budget = self._reserved(parent, state)
            first = self._ledger(state)
            self.assertEqual(first["planned_provider_call_count"], 3)
            budget.reserve()
            second = self._ledger(state)
            self.assertEqual(second["planned_provider_call_count"], 3)
            self.assertEqual(second["reservation_attempt_count"], 2)

        source = _function_source(inspect.getsource(web), "_run_web_fetch")
        self.assertEqual(_plan_reservation_order_offenders(source), [])
        needle = "plan_budget.reserve_plan_budget"
        head, separator, tail = source.partition(needle)
        self.assertEqual(separator, needle)
        mutated = head + "plan_budget.mutant_missing_reservation" + tail
        self.assertTrue(_plan_reservation_order_offenders(mutated))

    def test_A4_B1_runtime_reservation_control_and_production_mutant(self):
        """The order control executes the live entrypoint and mutates its real reserve call."""
        run_impl = next(
            cell.cell_contents for cell in (web.run_web_fetch.__closure__ or ())
            if getattr(cell.cell_contents, "__name__", "") == "_run_web_fetch"
        )
        parent = _parent()
        fake_budget = object()
        events: list[str] = []

        def fake_reserve(*_args, **_kwargs):
            events.append("reserve")
            return fake_budget

        def fake_execute(**kwargs):
            events.append("execute")
            self.assertIs(kwargs["dispatch_budget"], fake_budget)
            return {
                "results": [], "llm_response": '{"themes": []}',
                "query_drops": [], "fetched_at": web._parse_dt(STAMP, field="fetched_at"),
                "regroup_model_identity": web._regroup_model_identity(),
                "regroup_failed": False, "regroup_attempted": False,
                "regroup_chunk_counts": {"attempted": 0, "successful": 0, "failed": 0, "failed_indexes": []},
                "budget_error": None, "provider_call_count": 0,
            }

        def fake_build(**_kwargs):
            events.append("build")
            return ({"packet": True}, {"receipt": True}, {"summary": True})

        common = {
            "queries": ["q"], "expected_decision_date": DECISION_DATE,
            "generated_at": STAMP, "confirm_user_authorization": True,
            "live": True, "parent_plan": parent,
            "_new_transport": lambda *_providers: object(), "_issue_ticket": lambda: object(),
            "_revoke_ticket": lambda _ticket: None,
        }
        with mock.patch.object(web, "_require_single_tavily_api_key", return_value="tvly-" + "a" * 52), \
             mock.patch.object(web, "_require_single_deepseek_api_key", return_value="sk-" + "a" * 20), \
             mock.patch.object(web.paid_gateway, "create_web_clients", return_value=(object(), object())), \
             mock.patch.object(web.plan_budget, "reserve_plan_budget", side_effect=fake_reserve), \
             mock.patch.object(web, "execute_live_web_orchestration", side_effect=fake_execute), \
             mock.patch.object(web, "build_web_fetch_packet", side_effect=fake_build):
            run_impl(**common)
        self.assertEqual(events, ["reserve", "execute", "build"])

        # Planted mutation removes the production reservation result.  The runtime assertion in
        # fake_execute must then fail, so this test is a real B1 mutant control rather than AST text.
        with mock.patch.object(web.plan_budget, "reserve_plan_budget", return_value=None), \
             mock.patch.object(web, "execute_live_web_orchestration", side_effect=fake_execute), \
             mock.patch.object(web, "build_web_fetch_packet", side_effect=fake_build), \
             mock.patch.object(web, "_require_single_tavily_api_key", return_value="tvly-" + "a" * 52), \
             mock.patch.object(web, "_require_single_deepseek_api_key", return_value="sk-" + "a" * 20), \
             mock.patch.object(web.paid_gateway, "create_web_clients", return_value=(object(), object())):
            with self.assertRaises(AssertionError):
                run_impl(**common)

    def test_A4_B2_same_scope_retry_only_increments_attempt_not_planned(self):
        parent = _parent(stage1=1, stage2=0, retry=1)
        with temporary_us_short_state_directory(ROOT) as raw:
            state = Path(raw)
            budget = self._reserved(parent, state)

            def failed_call():
                raise RuntimeError("provider failure")

            first = budget.dispatch_with_outcome("web", scope="same-scope", stage="stage1", call=failed_call)
            self.assertIsInstance(first.call_error, RuntimeError)
            budget.dispatch_with_outcome("web", scope="same-scope", stage="stage1", call=lambda: "retry-ok")
            ledger = self._ledger(state)
        self.assertEqual(ledger["planned_provider_call_count"], 2)
        self.assertEqual(ledger["reservation_attempt_count"], 1)
        self.assertEqual(ledger["dispatch_counts"]["stage1_dispatch_count"], 1)
        self.assertEqual(ledger["dispatch_counts"]["retry_dispatch_count"], 1)
        self.assertEqual(ledger["query_reservations"][0]["attempt_count"], 2)

    def test_A4_B3_concurrent_reservation_cannot_double_charge(self):
        parent = _parent()
        with temporary_us_short_state_directory(ROOT) as raw:
            state = Path(raw)
            failures: list[BaseException] = []

            def reserve():
                try:
                    self._reserved(parent, state)
                except BaseException as exc:
                    failures.append(exc)

            threads = [threading.Thread(target=reserve) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
            ledger = self._ledger(state)
        self.assertEqual(failures, [])
        self.assertEqual(ledger["planned_provider_call_count"], 3)
        self.assertEqual(ledger["reservation_attempt_count"], 2)

    def test_A4_B4_reentry_marks_orphan_unknown_and_refuses_replay(self):
        parent = _parent()
        with temporary_us_short_state_directory(ROOT) as raw:
            state = Path(raw)
            first = self._reserved(parent, state)
            first.begin("web", scope="crashed-scope", stage="stage1")
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "active peer"):
                self._reserved(parent, state)
            # Re-entry never guesses that the old owner died.  The recovery command must
            # explicitly attest stale heartbeat and write an audit event without resetting caps.
            with mock.patch.object(plan_budget, "_owner_is_alive", return_value=False):
                with self.assertRaisesRegex(plan_budget.PlanBudgetError, "explicit recovery"):
                    self._reserved(parent, state)
                recovered = plan_budget.PlanDispatchBudget(
                    parent, state_dir=state, root=ROOT, gitignored=lambda _path: True,
                )
                recovered.recover_stale_in_flight(
                    "web", dispatch_id=1, recovery_reason="executor heartbeat expired",
                )
                reentered = self._reserved(parent, state)
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "automatically replayed"):
                reentered.begin("web", scope="crashed-scope", stage="stage1")
            ledger = self._ledger(state)
        self.assertEqual(ledger["dispatch_counts"]["unknown_dispatch_count"], 1)
        self.assertEqual(ledger["dispatches"][0]["status"], "unknown")
        self.assertEqual(ledger["query_reservations"][0]["last_status"], "unknown")
        self.assertEqual(len(ledger["recovery_events"]), 1)
        self.assertIn("heartbeat", ledger["recovery_events"][0]["reason"])

    def test_A4_B5_over_envelope_fails_before_paid_callback_and_mutant_is_red(self):
        parent = _parent(stage1=0, stage2=1, retry=0)
        with temporary_us_short_state_directory(ROOT) as raw:
            state = Path(raw)
            budget = self._reserved(parent, state)
            calls: list[str] = []
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "stage1 dispatch exceeds"):
                budget.dispatch_with_outcome(
                    "web", scope="over-envelope", stage="stage1",
                    call=lambda: calls.append("paid"),
                )
            self.assertEqual(calls, [])

            # Planted mutation targets the production envelope predicate, not a test-double
            # begin() method.  If that real guard is removed, this assertion fails before the
            # callback can be mistaken for a passing B5 control.
            with mock.patch.object(plan_budget, "_enforce_envelope_counts", return_value=None):
                budget.dispatch_with_outcome(
                    "web", scope="over-envelope", stage="stage1",
                    call=lambda: calls.append("paid"),
                )
            # Asserted directly, not inside `assertRaises(AssertionError)`: that older shape was
            # satisfied by ANY AssertionError from the dispatch path, so it could go green for a
            # reason unrelated to the planted mutation.
            self.assertEqual(
                calls, ["paid"],
                "removing the real pre-dispatch envelope guard must let the paid callback run; "
                "if it does not, this control no longer proves the guard is load-bearing",
            )

    def test_A4_B6_mutated_ledger_identity_is_rejected(self):
        parent = _parent()
        with temporary_us_short_state_directory(ROOT) as raw:
            state = Path(raw)
            budget = self._reserved(parent, state)
            ledger = self._ledger(state)
            ledger["planned_provider_call_count"] += 1
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "planned count"):
                plan_budget._validate_semantics(
                    ledger, lane=budget.lane, provider="web", decision_date=DECISION_DATE,
                    parent_plan_identity=parent["plan_identity"],
                    envelope=parent["canonical_plan_core"]["provider_envelopes"][0],
                )

    def test_A4_hard_provider_budget_rejects_plan_that_enlarges_the_outer_cap(self):
        parent = _parent(stage1=26, stage2=0, retry=0)
        with temporary_us_short_state_directory(ROOT) as raw:
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "hard provider call budget"):
                self._reserved(parent, Path(raw))
            self.assertEqual(list(Path(raw).glob("*.json")), [])

    def test_A4_live_runner_without_parent_plan_fails_closed_before_credentials(self):
        with self.assertRaisesRegex(web.WebThemeDiscoveryError, "parent plan"):
            web.run_web_fetch(
                queries=["q"], expected_decision_date=DECISION_DATE,
                generated_at=STAMP, confirm_user_authorization=True, live=True,
            )
        with self.assertRaisesRegex(xfetch.XThemeDiscoveryError, "parent plan"):
            xfetch.run_x_fetch(
                queries=["q"], expected_decision_date=DECISION_DATE,
                generated_at=STAMP, confirm_user_authorization=True, live=True,
            )

    def test_A4_run_date_is_bound_before_reservation(self):
        parent = _parent()
        with temporary_us_short_state_directory(ROOT) as raw:
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "decision_date"):
                plan_budget.reserve_plan_budget(
                    parent, expected_decision_date="20260809", state_dir=Path(raw),
                    root=ROOT, gitignored=lambda _path: True,
                )
            self.assertEqual(list(Path(raw).glob("*.json")), [])

    def test_A4_stage_is_part_of_scope_identity(self):
        parent = _parent(stage1=1, stage2=1, retry=0)
        with temporary_us_short_state_directory(ROOT) as raw:
            budget = self._reserved(parent, Path(raw))
            budget.dispatch_with_outcome("web", scope="same-text", stage="stage1", call=lambda: "one")
            budget.dispatch_with_outcome("web", scope="same-text", stage="stage2", call=lambda: "two")
            ledger = self._ledger(Path(raw))
        self.assertEqual(len(ledger["query_reservations"]), 2)
        self.assertEqual({row["stage"] for row in ledger["query_reservations"]}, {"stage1", "stage2"})

    def test_A4_dispatch_counts_are_derived_from_events_and_reject_float(self):
        parent = _parent(stage1=1, stage2=0, retry=0)
        with temporary_us_short_state_directory(ROOT) as raw:
            state = Path(raw)
            budget = self._reserved(parent, state)
            budget.dispatch_with_outcome("web", scope="counted", stage="stage1", call=lambda: "ok")
            ledger = self._ledger(state)
            ledger["dispatch_counts"] = {
                "stage1_dispatch_count": 0, "stage2_dispatch_count": 0,
                "retry_dispatch_count": 0, "dispatch_count": 0,
                "unknown_dispatch_count": 0,
            }
            path = plan_budget._ledger_path(provider="web", decision_date=DECISION_DATE, state_dir=state)
            plan_budget._write(
                ledger, path, root=ROOT, state_dir=state,
                gitignored=lambda _path: True,
            )
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "dispatch counts do not match"):
                budget.begin("web", scope="another", stage="stage1")

            ledger = self._ledger(state)
            ledger["dispatch_counts"]["stage1_dispatch_count"] = 1.0
            plan_budget._write(
                ledger, path, root=ROOT, state_dir=state,
                gitignored=lambda _path: True,
            )
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "must be an integer"):
                budget.begin("web", scope="another", stage="stage1")

    def test_A4_budget_abort_returns_partial_paid_outcome_for_packet_persistence(self):
        class AbortAfterOne:
            def __init__(self):
                self.calls = 0

            def dispatch_with_outcome(self, _provider, *, scope, stage, call):
                self.calls += 1
                if self.calls == 1:
                    return plan_budget.DispatchOutcome(value=call())
                return plan_budget.DispatchOutcome(
                    call_error=plan_budget.PlanBudgetError("budget exhausted"),
                )

        class Tavily:
            def search(self, query):
                return [{
                    "url": f"https://example.com/{query}", "title": query,
                    "content": "AAPL demand evidence", "published_date": "2026-08-07T10:00:00Z",
                }]

        web_outcome = web.execute_live_web_orchestration(
            queries=["q1", "q2"], expected_decision_date=DECISION_DATE,
            tavily=Tavily(), deepseek_client=object(), transport=object(),
            dispatch_budget=AbortAfterOne(), persist_search_response=_noop_persist,
        )
        self.assertIsInstance(web_outcome["budget_error"], plan_budget.PlanBudgetError)
        self.assertEqual(len(web_outcome["results"]), 1)
        self.assertIn("plan_budget_aborted", [row["reason"] for row in web_outcome["query_drops"]])

        class XClient:
            def search(self, query, _expected):
                return {"text": '{"themes":[]}', "results": [], "annotation_urls": []}

        x_outcome = xfetch.execute_live_x_orchestration(
            queries=["q1", "q2"], expected_decision_date=DECISION_DATE,
            client=XClient(), dispatch_budget=AbortAfterOne(), persist_response=_noop_persist,
        )
        self.assertIsInstance(x_outcome["budget_error"], plan_budget.PlanBudgetError)
        self.assertEqual(len(x_outcome["raw_provider_responses"]), 1)
        self.assertIn("plan_budget_aborted", [row["reason"] for row in x_outcome["query_drops"]])

    def test_A4_post_payment_completion_failure_keeps_paid_value_and_requires_recovery(self):
        parent = _parent(stage1=1, stage2=0, retry=0)
        with temporary_us_short_state_directory(ROOT) as raw:
            state = Path(raw)
            budget = self._reserved(parent, state)
            with mock.patch.object(
                budget, "finish", side_effect=plan_budget.PlanBudgetError("ledger write failed"),
            ):
                outcome = budget.dispatch_with_outcome(
                    "web", scope="paid-but-unfinished", stage="stage1",
                    call=lambda: {"paid": True},
                )
            self.assertEqual(outcome.value, {"paid": True})
            self.assertIsNone(outcome.call_error)
            self.assertIsInstance(outcome.completion_error, plan_budget.PostPaymentDispatchError)
            ledger = self._ledger(state)
        self.assertEqual(ledger["dispatches"][0]["status"], "in_flight")

    def test_A4_control_baseexception_is_accounted_then_rethrown(self):
        parent = _parent(stage1=1, stage2=0, retry=0)
        with temporary_us_short_state_directory(ROOT) as raw:
            state = Path(raw)
            budget = self._reserved(parent, state)

            def interrupted():
                raise KeyboardInterrupt()

            with self.assertRaises(KeyboardInterrupt):
                budget.dispatch_with_outcome(
                    "web", scope="ctrl-c", stage="stage1", call=interrupted,
                )
            ledger = self._ledger(state)
        self.assertEqual(ledger["dispatches"][0]["status"], "failure")

    def test_A4_dispatch_cannot_escape_the_reserved_provider_scope(self):
        parent = _parent()
        with temporary_us_short_state_directory(ROOT) as raw:
            budget = plan_budget.reserve_plan_budget(
                parent, state_dir=Path(raw), root=ROOT, gitignored=lambda _path: True,
                providers=("web",),
            )
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "outside the reserved provider scope"):
                budget.begin("xai", scope="wrong-scope", stage="stage1")

    def test_A4_budget_abort_uses_diagnostic_slot_not_formal_decision_slots(self):
        with temporary_us_short_state_directory(ROOT) as raw:
            old_state = web.STATE_DIR
            try:
                web.STATE_DIR = Path(raw)
                with mock.patch.object(web, "_gitignored", return_value=True):
                    path = web.publish_budget_abort_diagnostic(
                        "web", DECISION_DATE,
                        packet={"partial": True}, receipt={"raw": True},
                        summary={"status": "live_authorized_budget_aborted"},
                    )
                self.assertTrue(path.exists())
                diagnostic = json.loads(path.read_text(encoding="utf-8"))
                self.assertTrue(diagnostic["replay_required"])
                self.assertFalse(diagnostic["formal_decision_slots_occupied"])
                self.assertFalse(web.default_discovery_path(DECISION_DATE).exists())
                self.assertFalse(web.default_receipt_path(DECISION_DATE).exists())
            finally:
                web.STATE_DIR = old_state

    def test_A4_empty_budget_abort_retry_cannot_overwrite_paid_diagnostic_evidence(self):
        with temporary_us_short_state_directory(ROOT) as raw:
            old_state = web.STATE_DIR
            try:
                web.STATE_DIR = Path(raw)
                with mock.patch.object(web, "_gitignored", return_value=True):
                    strong_path = web.publish_budget_abort_diagnostic(
                        "web", DECISION_DATE,
                        packet={"paid": "strong"},
                        receipt={
                            "fetch_contract": {
                                "provider_calls_performed": True,
                                "network_access_performed": True,
                            },
                            "source_refs": [{"source_id": "web:paid"}],
                        },
                        summary={"accepted_source_count": 1, "validated_theme_count": 1},
                    )
                    weak_path = web.publish_budget_abort_diagnostic(
                        "web", DECISION_DATE,
                        packet={"paid": "empty"}, receipt={},
                        summary={"status": "live_authorized_budget_aborted"},
                    )
                self.assertEqual(str(strong_path), str(weak_path))
                diagnostic = json.loads(strong_path.read_text(encoding="utf-8"))
                self.assertEqual(diagnostic["packet"], {"paid": "strong"})
            finally:
                web.STATE_DIR = old_state

    def test_A4_P_D_web_and_x_post_payment_grid_keeps_paid_transport_evidence(self):
        class CompletionAfterReturn:
            def __init__(self):
                self.calls = 0

            def dispatch_with_outcome(self, _provider, *, scope, stage, call):
                del scope, stage
                self.calls += 1
                value = call()
                return plan_budget.DispatchOutcome(
                    value=value,
                    completion_error=plan_budget.PostPaymentDispatchError(
                        RuntimeError("completion receipt unavailable"), value=value,
                    ),
                )

        class Tavily:
            def search(self, query):
                return [{
                    "url": f"https://example.com/{query}", "title": query,
                    "content": "AAPL demand evidence", "published_date": "2026-08-07T10:00:00Z",
                }]

        web_outcome = web.execute_live_web_orchestration(
            queries=["q"], expected_decision_date=DECISION_DATE,
            tavily=Tavily(), deepseek_client=object(), transport=object(),
            dispatch_budget=CompletionAfterReturn(), persist_search_response=_noop_persist,
        )
        self.assertIsInstance(web_outcome["budget_error"], plan_budget.PostPaymentDispatchError)
        self.assertEqual(web_outcome["provider_call_count"], 1)
        self.assertEqual(len(web_outcome["results"]), 1)

        class XClient:
            def search(self, query, _expected):
                return {"text": '{"themes": []}', "results": [], "annotation_urls": []}

        x_outcome = xfetch.execute_live_x_orchestration(
            queries=["q"], expected_decision_date=DECISION_DATE,
            client=XClient(), dispatch_budget=CompletionAfterReturn(), persist_response=_noop_persist,
        )
        self.assertIsInstance(x_outcome["budget_error"], plan_budget.PostPaymentDispatchError)
        self.assertEqual(len(x_outcome["raw_provider_responses"]), 1)

    def test_A4_call_and_completion_error_matrix_stops_before_a_sibling_paid_call(self):
        class BothErrors:
            def __init__(self):
                self.calls = 0

            def dispatch_with_outcome(self, _provider, *, scope, stage, call):
                del scope, stage, call
                self.calls += 1
                completion = plan_budget.PostPaymentDispatchError(
                    RuntimeError("completion write failed"), value="paid",
                )
                return plan_budget.DispatchOutcome(
                    value="paid", call_error=RuntimeError("provider failed"),
                    completion_error=completion,
                )

        fake = BothErrors()
        gateway = web.paid_gateway.PaidDispatchGateway(fake)
        first = gateway._request("web", "first", "stage1", lambda: "paid")
        second = gateway._request("web", "second", "stage1", lambda: "must-not-run")
        batch = gateway.dispatch_all([first, second], persist_response=_noop_persist)
        self.assertEqual(fake.calls, 1)
        self.assertEqual(len(batch.items), 1)
        self.assertIsInstance(batch.stop_error, plan_budget.PostPaymentDispatchError)

    def test_A4_stage1_gateway_requires_persistence_sink_before_budget_reservation(self):
        class Budget:
            def __init__(self):
                self.calls = 0

            def dispatch_with_outcome(self, _provider, *, scope, stage, call):
                del scope, stage, call
                self.calls += 1
                return plan_budget.DispatchOutcome(value="paid")

        for sink in (None, False, object()):
            with self.subTest(sink=repr(sink)):
                budget = Budget()
                gateway = paid_gateway.PaidDispatchGateway(budget)
                with self.assertRaises(paid_gateway.PaidProviderError):
                    gateway.dispatch_all(
                        [gateway._request("web", "q", "stage1", lambda: "paid")],
                        persist_response=sink,
                    )
                self.assertEqual(budget.calls, 0)

    def test_A4_paid_evidence_finalizer_failure_is_terminal_before_sibling_call(self):
        class Budget:
            def __init__(self):
                self.calls = 0

            def dispatch_with_outcome(self, _provider, *, scope, stage, call):
                del scope, stage
                self.calls += 1
                return plan_budget.DispatchOutcome(value=call())

        budget = Budget()
        gateway = web.paid_gateway.PaidDispatchGateway(budget)
        requests = [
            gateway._request("web", "first", "stage1", lambda: "paid"),
            gateway._request("web", "second", "stage1", lambda: "must-not-run"),
        ]
        batch = gateway.dispatch_all(
            requests, persist_response=lambda _request, _value: (_ for _ in ()).throw(
                OSError("raw write door failed")
            ),
        )
        self.assertEqual(budget.calls, 1)
        self.assertIsInstance(
            batch.stop_error, web.paid_gateway.PaidEvidenceUnavailableError,
        )
        self.assertIsInstance(batch.items[0].evidence_error, web.paid_gateway.PaidEvidenceUnavailableError)

    def test_A4_web_and_x_rejected_raw_writes_are_terminal_before_a_sibling_call(self):
        class Budget:
            def __init__(self):
                self.calls = 0

            def dispatch_with_outcome(self, _provider, *, scope, stage, call):
                del scope, stage
                self.calls += 1
                return plan_budget.DispatchOutcome(value=call())

        web_row = {
            "url": "https://example.com/paid",
            "title": "paid",
            "content": "AAPL evidence",
            "published_date": "2026-08-07T10:00:00Z",
        }
        cases = [
            (
                "web",
                lambda request, value: web._persist_live_web_search_response(
                    request, value, raw_root=ROOT / "engine", expected_decision_date=DECISION_DATE,
                ),
                [web_row],
            ),
            (
                "xai",
                lambda request, value: xfetch._persist_live_x_response(
                    request, value, raw_root=ROOT / "engine", expected_decision_date=DECISION_DATE,
                ),
                {"record": {"response": {"id": "paid-response"}}},
            ),
        ]
        for provider, persist, value in cases:
            with self.subTest(provider=provider):
                budget = Budget()
                gateway = paid_gateway.PaidDispatchGateway(budget)
                requests = [
                    gateway._request(provider, "q1", "stage1", lambda value=value: value),
                    gateway._request(provider, "q2", "stage1", lambda: "must-not-run"),
                ]
                batch = gateway.dispatch_all(requests, persist_response=persist)
                self.assertEqual(budget.calls, 1)
                self.assertIsInstance(
                    batch.stop_error, paid_gateway.PaidEvidenceUnavailableError,
                )

    def test_A4_gateway_control_signal_is_rethrown_and_live_clients_are_not_offline_fixtures(self):
        class ControlBudget:
            def dispatch_with_outcome(self, _provider, *, scope, stage, call):
                del scope, stage, call
                return plan_budget.DispatchOutcome(call_error=KeyboardInterrupt())

        gateway = web.paid_gateway.PaidDispatchGateway(ControlBudget())
        with self.assertRaises(KeyboardInterrupt):
            gateway.dispatch_all(
                [gateway._request("web", "q", "stage1", lambda: "paid")],
                persist_response=_noop_persist,
            )

        live_client = object.__new__(web.paid_gateway.TavilyClient)
        with self.assertRaises(web.paid_gateway.PaidProviderError):
            web.paid_gateway.offline_web_search(live_client, "q")

    def test_A4_every_provider_baseexception_outlet_uses_the_canonical_control_rule(self):
        gateway_source = (
            ROOT / "engine" / "us_short_llm_theme_discovery_paid_gateway.py"
        ).read_text(encoding="utf-8")
        sites = _canonical_control_sites(gateway_source)
        self.assertNotIn("_must_propagate", gateway_source)

        class TavilySearch:
            def __call__(self):
                client = object.__new__(paid_gateway.TavilyClient)
                client.api_key = "tvly-" + "a" * 52
                client.timeout = 1.0
                client.network_call_count = 0
                with mock.patch("urllib.request.urlopen", side_effect=KeyboardInterrupt()):
                    return client.search("q")

        class CompletionDelegate:
            def create(self, *args, **kwargs):
                del args, kwargs
                raise KeyboardInterrupt()

        class ImportInterrupt:
            def __init__(self, module_name):
                self.module_name = module_name

            def __call__(self, name, *args, **kwargs):
                if name == self.module_name:
                    raise KeyboardInterrupt()
                return self.original(name, *args, **kwargs)

        def deepseek_completion():
            return paid_gateway.DeepSeekClient._Completions(CompletionDelegate()).create()

        def deepseek_init():
            original = __import__
            importer = ImportInterrupt("openai")
            importer.original = original
            with mock.patch("builtins.__import__", side_effect=importer):
                return paid_gateway.DeepSeekClient(
                    "sk-" + "a" * 52,
                    live_transport=paid_gateway.new_transport("deepseek"),
                )

        class BadRawResponse:
            def model_dump(self, *args, **kwargs):
                del args, kwargs
                raise KeyboardInterrupt()

        def raw_response_freeze():
            return paid_gateway._raw_provider_response_payload(BadRawResponse())

        def grok_init():
            original = __import__
            importer = ImportInterrupt("openai")
            importer.original = original
            with mock.patch("builtins.__import__", side_effect=importer):
                return paid_gateway.GrokXSearchClient(
                    "xai-" + "a" * 52,
                    live_transport=paid_gateway.new_transport("xai"),
                )

        def grok_parse():
            class Responses:
                def create(self, **kwargs):
                    del kwargs
                    return type(
                        "Response",
                        (),
                        {
                            "model_dump": lambda self, mode="json": {"id": "response"},
                            "output_text": "text",
                            "results": [],
                            "model": "grok-4.3",
                            "system_fingerprint": "fp",
                        },
                    )()

            client = object.__new__(paid_gateway.GrokXSearchClient)
            client.network_call_count = 0
            client.client = type("Client", (), {"responses": Responses()})()
            with mock.patch.object(
                paid_gateway, "_response_text", side_effect=KeyboardInterrupt()
            ):
                return client.search("q", DECISION_DATE)

        cases = {
            ("TavilyClient", "search"): TavilySearch(),
            ("DeepSeekClient._Completions", "create"): deepseek_completion,
            ("DeepSeekClient", "__init__"): deepseek_init,
            ("<module>", "_raw_provider_response_payload"): raw_response_freeze,
            ("GrokXSearchClient", "__init__"): grok_init,
            ("GrokXSearchClient", "search"): grok_parse,
        }
        self.assertEqual(set(sites), set(cases))
        self.assertEqual(len(sites), 6)
        for site, case in cases.items():
            with self.subTest(site=site):
                with self.assertRaises(KeyboardInterrupt):
                    case()
                with mock.patch.object(plan_budget, "is_control_error", return_value=False):
                    try:
                        case()
                    except KeyboardInterrupt as exc:
                        self.fail(f"control signal was swallowed at {site}: {exc!r}")
                    except BaseException:
                        pass

    def test_A4_live_orchestration_requires_a_persistence_sink_before_dispatch(self):
        web_parameter = inspect.signature(
            web.execute_live_web_orchestration,
        ).parameters["persist_search_response"]
        x_parameter = inspect.signature(
            xfetch.execute_live_x_orchestration,
        ).parameters["persist_response"]
        self.assertIs(web_parameter.default, inspect.Parameter.empty)
        self.assertIs(x_parameter.default, inspect.Parameter.empty)

        class Budget:
            def __init__(self):
                self.calls = 0

            def dispatch_with_outcome(self, _provider, *, scope, stage, call):
                del scope, stage, call
                self.calls += 1
                return plan_budget.DispatchOutcome(value=[])

        web_budget = Budget()
        with self.assertRaisesRegex(plan_budget.PlanBudgetError, "persist_search_response"):
            web.execute_live_web_orchestration(
                queries=["q"], expected_decision_date=DECISION_DATE,
                tavily=object(), deepseek_client=object(), transport=object(),
                dispatch_budget=web_budget, persist_search_response=None,
            )
        self.assertEqual(web_budget.calls, 0)

        x_budget = Budget()
        with self.assertRaisesRegex(plan_budget.PlanBudgetError, "persist_response"):
            xfetch.execute_live_x_orchestration(
                queries=["q"], expected_decision_date=DECISION_DATE,
                client=object(), dispatch_budget=x_budget, persist_response=None,
            )
        self.assertEqual(x_budget.calls, 0)

    def test_A4_live_web_orchestration_never_crosses_the_offline_client_boundary(self):
        class Budget:
            def dispatch_with_outcome(self, _provider, *, scope, stage, call):
                del scope, stage
                return plan_budget.DispatchOutcome(value=call())

        class Tavily:
            def search(self, _query):
                return []

        with mock.patch.object(
            web.paid_gateway, "offline_web_search",
            side_effect=AssertionError("live path called offline helper"),
        ):
            outcome = web.execute_live_web_orchestration(
                queries=["q"], expected_decision_date=DECISION_DATE,
                tavily=Tavily(), deepseek_client=object(), transport=object(),
                dispatch_budget=Budget(), persist_search_response=_noop_persist,
            )
        self.assertEqual(outcome["results"], [])

    def test_A4_raw_flush_precedes_receipt_validation(self):
        web_source = (ROOT / "runners" / "us_short_llm_theme_discovery_fetch_web.py").read_text(encoding="utf-8")
        x_source = (ROOT / "runners" / "us_short_llm_theme_discovery_fetch_x.py").read_text(encoding="utf-8")
        web_builder = _function_source(web_source, "build_web_fetch_packet")
        x_builder = _function_source(x_source, "build_x_fetch_packet")

        def assert_flush_before_validation(source: str, flush_call: str) -> None:
            flush_at = source.index(flush_call)
            validation_at = source.index("_assert_receipt_secret_free", flush_at)
            self.assertLess(flush_at, validation_at)
            validation_call = (
                "web._assert_receipt_secret_free"
                if flush_call.startswith("web.")
                else "_assert_receipt_secret_free"
            )
            mutated = _replace_once(
                source,
                f"{flush_call}\n    {validation_call}",
                f"{validation_call}\n    {flush_call}",
            )
            self.assertGreater(
                mutated.index(flush_call), mutated.index("_assert_receipt_secret_free"),
            )

        assert_flush_before_validation(web_builder, "_flush_raw_writes(pending_raw_writes)")
        assert_flush_before_validation(x_builder, "web._flush_raw_writes(pending_raw_writes)")

    def test_A4_dispatch_budget_none_is_rejected_at_both_live_orchestration_exports(self):
        with self.assertRaisesRegex(plan_budget.PlanBudgetError, "dispatch_budget"):
            web.execute_live_web_orchestration(
                queries=["q"], expected_decision_date=DECISION_DATE,
                tavily=object(), deepseek_client=object(), transport=object(),
                dispatch_budget=None, persist_search_response=_noop_persist,
            )
        with self.assertRaisesRegex(plan_budget.PlanBudgetError, "dispatch_budget"):
            xfetch.execute_live_x_orchestration(
                queries=["q"], expected_decision_date=DECISION_DATE,
                client=object(), dispatch_budget=None, persist_response=_noop_persist,
            )

    def test_A4_hard_budget_is_derived_from_shared_provider_call_budget_and_relabel_is_rejected(self):
        original = dict(provider_policy.PROVIDER_CALL_BUDGET)
        try:
            provider_policy.PROVIDER_CALL_BUDGET[("web", "tavily")] = 7
            provider_policy.PROVIDER_CALL_BUDGET[("web", "deepseek")] = 8
            provider_policy.PROVIDER_CALL_BUDGET[("x", "xai")] = 9
            derived = plan_budget.derive_hard_provider_call_budget()
            self.assertEqual(derived["web"]["stage1_max_dispatch_count"], 7)
            self.assertEqual(derived["web"]["stage2_max_dispatch_count"], 8)
            self.assertEqual(derived["xai"]["max_dispatch_count"], 9)
        finally:
            provider_policy.PROVIDER_CALL_BUDGET.clear()
            provider_policy.PROVIDER_CALL_BUDGET.update(original)

        parent = _parent(stage1=1, stage2=0, retry=0)
        with temporary_us_short_state_directory(ROOT) as raw:
            state = Path(raw)
            budget = self._reserved(parent, state)
            budget.dispatch_with_outcome("web", scope="vendor-bound", stage="stage1", call=lambda: "ok")
            ledger = self._ledger(state)
            ledger["dispatches"][0]["vendor"] = "deepseek"
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "vendor"):
                plan_budget._validate_semantics(
                    ledger, lane="us_short", provider="web", decision_date=DECISION_DATE,
                    parent_plan_identity=parent["plan_identity"],
                    envelope=parent["canonical_plan_core"]["provider_envelopes"][0],
                )

    def test_A4_owner_liveness_uses_run_id_and_heartbeat_not_pid(self):
        now = datetime.now(timezone.utc)
        row = {
            "owner_pid": 1,
            "owner_run_id": "a" * 32,
            "owner_started_at": (now - timedelta(seconds=2)).isoformat(),
            "owner_heartbeat_at": (now - timedelta(seconds=1)).isoformat(),
        }
        self.assertTrue(plan_budget._owner_is_alive(row, now=now))
        row["owner_pid"] = 999999999
        self.assertTrue(plan_budget._owner_is_alive(row, now=now))
        row["owner_heartbeat_at"] = (now - timedelta(seconds=plan_budget.OWNER_HEARTBEAT_TTL_SECONDS + 1)).isoformat()
        self.assertFalse(plan_budget._owner_is_alive(row, now=now))

    def test_A4_class_exit_predicates_P_A_P_D_P_C_and_P_E_are_executable(self):
        gateway_path = ROOT / "engine" / "us_short_llm_theme_discovery_paid_gateway.py"
        budget_path = ROOT / "engine" / "us_short_llm_theme_discovery_plan_budget.py"
        web_path = ROOT / "runners" / "us_short_llm_theme_discovery_fetch_web.py"
        x_path = ROOT / "runners" / "us_short_llm_theme_discovery_fetch_x.py"
        paths = [budget_path, web_path, x_path]
        offenders = _class_a_default_none_offenders(paths)
        # Exact list on purpose: a NEW default-None on the money path must be added here
        # consciously, with its reason, instead of silently joining the allowlist.
        #   parent_plan  — only offline mode may omit it; live rejects None before credentials.
        #   raw_root     — resolved at CALL time (`raw_root or DEFAULT_RAW_ROOT`) and validated in
        #                  both branches.  It must NOT be bound into the signature: an import-time
        #                  default defeats `mock.patch.object(module, "DEFAULT_RAW_ROOT", tmp)`,
        #                  which sent offline test writes into the real gitignored raw root and
        #                  made the pack history-dependent (guarded by
        #                  tests.test_us_short_discovery_class_guards.RawRootIsolationSeamConformance).
        self.assertEqual(
            [(filename, function, argument) for filename, function, argument, _line in offenders],
            [
                ("us_short_llm_theme_discovery_fetch_web.py", "_run_web_fetch", "raw_root"),
                ("us_short_llm_theme_discovery_fetch_web.py", "_run_web_fetch", "parent_plan"),
                ("us_short_llm_theme_discovery_fetch_web.py", "runner", "raw_root"),
                ("us_short_llm_theme_discovery_fetch_web.py", "runner", "parent_plan"),
                ("us_short_llm_theme_discovery_fetch_x.py", "_run_x_fetch", "raw_root"),
                ("us_short_llm_theme_discovery_fetch_x.py", "_run_x_fetch", "parent_plan"),
                ("us_short_llm_theme_discovery_fetch_x.py", "runner", "raw_root"),
                ("us_short_llm_theme_discovery_fetch_x.py", "runner", "parent_plan"),
            ],
        )

        # P-A/P-D: the two runners expose no paid dispatch outlet or provider-client definition;
        # the sole module that constructs/calls those clients is the gateway.
        for path in (web_path, x_path):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("dispatch_with_outcome", source)
            self.assertNotIn("TavilyClient", source)
            self.assertNotIn("DeepSeekClient", source)
            self.assertNotIn("GrokXSearchClient", source)
            self.assertEqual(_dispatch_outlet_functions(path), [])
        gateway_source = gateway_path.read_text(encoding="utf-8")
        for symbol in ("TavilyClient", "DeepSeekClient", "GrokXSearchClient", "dispatch_all", "completion_error"):
            self.assertIn(symbol, gateway_source)

        class CompletionBudget:
            def __init__(self):
                self.calls = 0

            def dispatch_with_outcome(self, _provider, *, scope, stage, call):
                del scope, stage
                self.calls += 1
                value = call()
                return plan_budget.DispatchOutcome(
                    value=value,
                    completion_error=plan_budget.PostPaymentDispatchError(
                        RuntimeError("completion lost"), value=value,
                    ),
                )

        events: list[str] = []
        budget = CompletionBudget()
        gateway = web.paid_gateway.PaidDispatchGateway(budget)
        batch = gateway.dispatch_all(
            [gateway._request("web", "q", "stage1", lambda: "paid")],
            capture_response=lambda _request, value: events.append("capture") or value,
            persist_response=_noop_persist,
            consume_response=lambda _request, value: events.append("consume") or value,
        )
        self.assertEqual(events, ["capture", "consume"])
        self.assertEqual(budget.calls, 1)
        self.assertIsInstance(batch.stop_error, plan_budget.PostPaymentDispatchError)

        # P-C: recovery fields are not writer-only schema decoration; an AST reader must see the
        # actual field access, and a field-renaming mutant must turn this control red.
        semantics_source = _function_source(
            budget_path.read_text(encoding="utf-8"), "_validate_semantics",
        )
        for field in ("reason", "recovered_at"):
            self.assertTrue(_reads_mapping_field(semantics_source, "_validate_semantics", field))
            mutated = _replace_all(
                semantics_source,
                f'event.get("{field}"', f'event.get("removed_{field}"',
            )
            self.assertFalse(_reads_mapping_field(mutated, "_validate_semantics", field))

        # P-E: plant the lower-level envelope predicate while executing the real dispatch path;
        # patching the method under test would only prove the test's own replacement.
        parent = _parent(stage1=0, stage2=1, retry=0)
        with temporary_us_short_state_directory(ROOT) as raw:
            guarded = self._reserved(parent, Path(raw))
            calls: list[str] = []
            with mock.patch.object(
                plan_budget, "_enforce_envelope_counts", return_value=None,
            ):
                guarded.dispatch_with_outcome(
                    "web", scope="stage1-over-envelope", stage="stage1",
                    call=lambda: calls.append("paid"),
                )
            self.assertEqual(calls, ["paid"])

        schema = json.loads((ROOT / "schemas" / "us_short_llm_theme_discovery_plan_budget.schema.json").read_text(encoding="utf-8"))
        engine_source = budget_path.read_text(encoding="utf-8")
        field_names = _schema_contract_field_names(schema)
        self.assertTrue(field_names)
        self.assertTrue(all(field in engine_source for field in field_names))
        self.assertIn("vendor_dispatch_counts", field_names)

        # A forged persisted vendor total must be rejected by the real semantic validator; this
        # replaces the old tautology that only searched a mutated source string.
        parent = _parent(stage1=1, stage2=0, retry=0)
        with temporary_us_short_state_directory(ROOT) as raw:
            state = Path(raw)
            budget = self._reserved(parent, state)
            budget.dispatch_with_outcome("web", scope="vendor-count", stage="stage1", call=lambda: "ok")
            ledger = self._ledger(state)
            ledger["vendor_dispatch_counts"]["tavily"] = 0
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "vendor dispatch counts"):
                plan_budget._validate_semantics(
                    ledger, lane="us_short", provider="web", decision_date=DECISION_DATE,
                    parent_plan_identity=parent["plan_identity"],
                    envelope=parent["canonical_plan_core"]["provider_envelopes"][0],
                )

        test_methods = inspect.getmembers(PlanBudgetAcceptanceTests, predicate=inspect.isfunction)
        for name, method in test_methods:
            if "mutant_is_red" in name or "planted" in name:
                source = inspect.getsource(method)
                self.assertIn("mock.patch.object", source)
                self.assertRegex(source, r"(?:plan_budget|web)\.")


if __name__ == "__main__":
    unittest.main()
