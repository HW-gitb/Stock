from __future__ import annotations

import ast
from contextlib import ExitStack, contextmanager
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import sys
import types
import unittest
from unittest import mock

from engine import us_short_llm_theme_discovery_plan_budget as plan_budget
from engine import us_short_llm_theme_discovery_paid_gateway as paid_gateway
from engine import us_short_llm_theme_discovery_provider_policy as provider_policy
from engine import us_short_llm_theme_discovery_query_plan as query_plan
from runners import us_short_llm_theme_discovery_fetch_web as web
from runners import us_short_llm_theme_discovery_fetch_x as xfetch
from runners import us_short_llm_theme_discovery_web_regroup_smoke as smoke
from tests.provider.us_short_private_test_root_light import temporary_us_short_state_directory


ROOT = plan_budget.ROOT
DECISION_DATE = "20260815"
# A decision date that is deliberately NOT the plan's, used to prove the run-date binding
# is checked before reservation.  Derived rather than written down: it was a literal, and
# moving the probe slot onto that literal silently turned the assertion into a no-op.
OTHER_DECISION_DATE = (
    datetime.strptime(DECISION_DATE, "%Y%m%d") + timedelta(days=1)
).strftime("%Y%m%d")
DECISION_DAY_UTC = datetime.strptime(DECISION_DATE, "%Y%m%d").replace(tzinfo=timezone.utc)
# Keep every live-shape fixture inside the current packet's accepted week.  A future reslot may
# legally move DECISION_DATE; it must turn red if any source clock is left on the retired slot.
STAMP = (DECISION_DAY_UTC - timedelta(days=1) + timedelta(hours=12)).isoformat().replace(
    "+00:00", "Z"
)
CURRENT_WEEK_PUBLISHED_AT = (
    DECISION_DAY_UTC - timedelta(days=1) + timedelta(hours=10)
).isoformat().replace("+00:00", "Z")


def _reviewed_parent_plan() -> dict:
    """The plan the shipped builder publishes, i.e. the one production actually accepts.

    Wrapped like `_parent()` so the artifact binding the runner needs is present; only the
    policy-bound fields differ from the synthetic fixture.
    """
    from runners import us_short_llm_theme_discovery_build_parent_plan as _builder
    payload = _builder.build_parent_plan_from_reviewed_policy(
        decision_date=DECISION_DATE, generated_at=STAMP,
    )
    return query_plan.ParentPlanDocument(
        payload, artifact_sha256="c" * 64,
        artifact_path="state/us_short/test-parent-plan.json",
    )


def _noop_persist(_request, _value):
    """Explicit test sink for orchestration-only tests that do not build raw receipts."""
    return None


def _k5_response(*, content: str = '{"themes": []}', model: str = "deepseek-v4-pro",
                 usage: dict | None = None, finish_reason: str = "stop") -> dict:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
        "model": model,
        "usage": usage if usage is not None else {
            "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
        },
        "system_fingerprint": "fp_test",
    }


class _K5FakeDeepSeek:
    def __init__(self, response: object, error: BaseException | None = None):
        self.requests: list[dict] = []
        self._response = response
        self._error = error
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.requests.append(kwargs)
                if outer._error is not None:
                    raise outer._error
                return outer._response

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


class _K5FakeBudget:
    def __init__(
        self, *, parent_plan: dict, state_dir: Path,
        completion_error: BaseException | None = None,
    ):
        self.parent_plan = parent_plan
        self.state_dir = state_dir
        self.completion_error = completion_error
        self.calls: list[tuple[str, str, str]] = []
        self.ledger_path = plan_budget.default_plan_budget_path(
            "web", DECISION_DATE, state_dir=state_dir,
        )

    def _write_ledger(self, status: str) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_path.write_text(json.dumps({
            "reservation_attempt_count": 1,
            "query_reservations": [{"last_status": status}],
            "dispatch_counts": {
                "stage1_dispatch_count": 0,
                "stage2_dispatch_count": 1,
                "retry_dispatch_count": 0,
                "dispatch_count": 1,
                "unknown_dispatch_count": 0,
            },
            "vendor_dispatch_counts": {"tavily": 0, "deepseek": 1, "xai": 0},
            "recovery_events": [],
        }), encoding="utf-8")

    def dispatch_with_outcome(self, provider, *, scope, stage, call):
        self.calls.append((provider, scope, stage))
        self._write_ledger("in_flight")
        try:
            value = call()
        except BaseException as exc:
            if plan_budget.is_control_error(exc):
                raise
            self._write_ledger("failure")
            return plan_budget.DispatchOutcome(call_error=exc)
        self._write_ledger("complete")
        return plan_budget.DispatchOutcome(value=value, completion_error=self.completion_error)


@contextmanager
def _k5_smoke_fixture(
    *, response: object | None = None, client_error: BaseException | None = None,
    completion_error: BaseException | None = None, persist_error: BaseException | None = None,
    publish_error: BaseException | None = None, packet_version: int = 2,
):
    version = str(packet_version)
    packet = json.loads(
        (ROOT / f"docs/us_short_web_regroup_engineering_smoke_packet_20260815_v{version}.json").read_text(
            encoding="utf-8"
        )
    )
    with tempfile.TemporaryDirectory(prefix="us_short_k5_") as raw:
        root = Path(raw)
        state_dir = root / "state" / "us_short"
        private_root = state_dir / "runs_private" / f"soft_discovery_engineering_smoke_v{version}"
        provider_root = root / "provider_samples" / f"us_short_llm_theme_discovery_engineering_smoke_v{version}"
        parent_plan = {"plan_identity": "p" * 64}
        fake_client = _K5FakeDeepSeek(
            response if response is not None else _k5_response(), error=client_error,
        )
        fake_budget = _K5FakeBudget(
            parent_plan=parent_plan, state_dir=private_root, completion_error=completion_error,
        )
        target_rows = [{
            "source_id": "web:" + "a" * 64,
            "title": "Evidence title",
            "content": "AAPL demand evidence",
        }]
        packet_path = root / "packet.json"
        schema_path = root / "packet.schema.json"
        summary_path = private_root / "us_short_web_regroup_engineering_smoke_20260815_chunk1_summary.json"
        patches = [
            mock.patch.object(smoke, "ROOT", root),
            mock.patch.object(smoke, "LIVE_ROOT", root),
            mock.patch.object(smoke, "PACKET_PATH", packet_path),
            mock.patch.object(smoke, "SCHEMA_PATH", schema_path),
            mock.patch.object(smoke, "PRIVATE_ROOT", private_root),
            mock.patch.object(
                smoke,
                "PARENT_PLAN_PATH",
                private_root / "us_short_web_regroup_engineering_smoke_20260815_chunk1_parent_plan.json",
            ),
            mock.patch.object(smoke, "RAW_ROOT", provider_root),
            mock.patch.object(smoke, "SUMMARY_PATH", summary_path),
            mock.patch.object(web, "ROOT", root),
            mock.patch.object(web, "STATE_DIR", state_dir),
            mock.patch.object(web, "_gitignored", return_value=True),
            mock.patch.object(smoke, "_validate_packet", return_value=packet),
            mock.patch.object(smoke, "_frozen_target_rows", return_value=target_rows),
            mock.patch.object(smoke, "_validate_rendered_prompt", return_value="prompt"),
            mock.patch.object(smoke, "_build_diagnostic_parent_plan", return_value=parent_plan),
            mock.patch.object(smoke, "_private_gitignored", return_value=True),
            mock.patch.object(web, "_require_single_deepseek_api_key", return_value="sk-" + "a" * 16),
        ]
        if persist_error is not None:
            patches.append(mock.patch.object(web, "_persist_live_web_regroup_response", side_effect=persist_error))
        if publish_error is not None:
            patches.append(mock.patch.object(web, "publish_engineering_smoke_diagnostic", side_effect=publish_error))
        with ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            reserve_mock = stack.enter_context(
                mock.patch.object(plan_budget, "reserve_plan_budget", return_value=fake_budget)
            )
            client_constructor = stack.enter_context(
                mock.patch.object(paid_gateway, "DeepSeekClient", return_value=fake_client)
            )
            yield {
                "packet": packet,
                "root": root,
                "private_root": private_root,
                "provider_root": provider_root,
                "summary_path": summary_path,
                "client": fake_client,
                "budget": fake_budget,
                "reserve_mock": reserve_mock,
                "client_constructor": client_constructor,
            }


def _live_transport(*providers: str) -> paid_gateway.LiveTransport:
    return paid_gateway.new_transport(*providers)


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
    return query_plan.ParentPlanDocument(query_plan.build_parent_plan(
        decision_date=DECISION_DATE,
        policy_version="soft_discovery_query_policy_v0.1.0",
        policy_template_content_sha256="a" * 64,
        stage1_queries=[
            {"query_id": "stage1-a", "query_text": "Find demand shifts."},
        ],
        stage2_rule_sha256="b" * 64,
        provider_envelopes=envelopes,
        generated_at=STAMP,
    ), artifact_sha256="c" * 64, artifact_path="state/us_short/test-parent-plan.json")


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


def _live_orchestration_optional_keyword_offenders(path: Path) -> list[tuple[str, str, int]]:
    """Derive every optional keyword at the paid orchestration boundary from its AST."""
    return _live_orchestration_optional_keyword_offenders_from_source(
        path.read_text(encoding="utf-8")
    )


def _live_orchestration_optional_keyword_offenders_from_source(
    source: str,
) -> list[tuple[str, str, int]]:
    tree = ast.parse(source)
    offenders: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not (node.name.startswith("execute_live_") and node.name.endswith("_orchestration")):
            continue
        for argument, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            if default is not None:
                offenders.append((node.name, argument.arg, node.lineno))
        # Same rule on the two axes the keyword-only walk is blind to: a money-path argument
        # declared positionally with a default, or swallowed by **kwargs, is just as omittable.
        positional = node.args.posonlyargs + node.args.args
        for argument, default in zip(positional[len(positional) - len(node.args.defaults):],
                                     node.args.defaults):
            if default is not None:
                offenders.append((node.name, argument.arg, node.lineno))
        if node.args.kwarg is not None:
            offenders.append((node.name, f"**{node.args.kwarg.arg}", node.lineno))
    return sorted(offenders)


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
    def test_K5_sdk_clients_disable_transport_retries_for_both_openai_compatible_paths(self):
        captured: list[dict] = []

        class FakeOpenAI:
            def __init__(self, **kwargs):
                captured.append(kwargs)
                self.chat = types.SimpleNamespace(completions=object())
                self.responses = types.SimpleNamespace()

        with mock.patch.dict(sys.modules, {"openai": types.SimpleNamespace(OpenAI=FakeOpenAI)}):
            paid_gateway.DeepSeekClient(
                "sk-" + "a" * 16, live_transport=_live_transport("deepseek"),
            )
            paid_gateway.GrokXSearchClient(
                "xai-" + "b" * 16, live_transport=_live_transport("xai"),
            )
        self.assertEqual([row["max_retries"] for row in captured], [0, 0])
        # the 2026-08-19 shot hung up at 45.3s with nothing back; the timeout the SDK actually
        # receives must be the module constant sized for Pro, not a literal left behind by Flash
        self.assertEqual(captured[0]["timeout"], paid_gateway.DEEPSEEK_REQUEST_TIMEOUT_SECONDS)

    def test_K5_a_timed_out_call_records_a_routable_cause_without_leaking_its_message(self):
        leaky = "read timed out; https://api.deepseek.com/v1 key sk-" + "z" * 16
        try:
            try:
                raise TimeoutError(leaky)
            except TimeoutError as cause:
                raise paid_gateway.PaidProviderError("DeepSeek request failed: TimeoutError") from cause
        except paid_gateway.PaidProviderError as err:
            client_error = err

        with _k5_smoke_fixture(client_error=client_error) as fixture:
            summary = smoke.run_one_shot(
                fixture["packet"], confirm_user_authorization=fixture["packet"]["packet_id"],
            )
        self.assertEqual(summary["transport_verdict"], "FAIL")
        self.assertEqual(summary["terminal_error_reason"], "provider_call_failed")
        # enough to route the failure...
        self.assertEqual(summary["terminal_error_detail"], "TimeoutError")
        # ...and nothing more: no message, no URL, no key anywhere in the artifact
        self.assertNotIn("sk-", json.dumps(summary))
        self.assertNotIn("api.deepseek.com", json.dumps(summary))

    def _reserved(self, parent: dict, state: Path) -> plan_budget.PlanDispatchBudget:
        return plan_budget.reserve_plan_budget(
            parent, state_dir=state, root=ROOT, gitignored=lambda _path: True,
            # synthetic plan fixture: the CALLER declares the opt-out, never the plan itself.
            require_reviewed_policy=False,
        )

    def _ledger(self, state: Path, provider: str = "web") -> dict:
        path = plan_budget._ledger_path(
            provider=provider, decision_date=DECISION_DATE, state_dir=state,
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def test_P5_gateway_uses_plan_query_id_and_rejects_plan_external_query_before_budget(self):
        parent = _parent()

        class Budget:
            def __init__(self):
                self.parent_plan = parent
                self.calls = []

            def dispatch_with_outcome(self, provider, *, scope, stage, call):
                self.calls.append((provider, scope, stage))
                return plan_budget.DispatchOutcome(value=call())

        class Client:
            @staticmethod
            def search(query):
                return [{"query": query}]

        budget = Budget()
        gateway = paid_gateway.PaidDispatchGateway(budget, parent_plan=parent)
        record = query_plan.derive_stage1_query_records(parent)[0]
        batch = gateway.dispatch_web_search_all(
            Client(), [record], persist_response=_noop_persist,
        )
        self.assertEqual(len(batch.items), 1)
        request = batch.items[0].request
        self.assertEqual(request.query_id, "stage1-a")
        self.assertEqual(request.scope, "stage1-a")
        self.assertEqual(request.query_text, record["query_text"])
        self.assertEqual(len(budget.calls), 1)

        forged = dict(record)
        forged["query_id"] = "stage1-foreign"
        with self.assertRaisesRegex(paid_gateway.PaidProviderError, "outside the parent plan"):
            gateway.dispatch_web_search_all(
                Client(), [forged], persist_response=_noop_persist,
            )
        self.assertEqual(len(budget.calls), 1)

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
        # This control drives the real _run_web_fetch, which validates the plan against the
        # reviewed policy before it reserves.  A synthetic plan would only prove that the
        # authority check can be dodged, so use the plan the builder actually publishes.
        parent = _reviewed_parent_plan()
        reviewed_queries = [row["query_text"] for row in parent["canonical_plan_core"]["stage1_queries"]]
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
                "stage1_dispatch_count": 1, "stage1_queries": list(reviewed_queries),
            }

        def fake_build(**_kwargs):
            events.append("build")
            return ({"packet": True}, {"summary": {"query_count": 1}}, {"summary": True})

        common = {
            "queries": reviewed_queries, "expected_decision_date": DECISION_DATE,
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
                    # synthetic plan fixture: the CALLER declares the opt-out, never the plan itself.
                    require_reviewed_policy=False,
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
                    parent, expected_decision_date=OTHER_DECISION_DATE, state_dir=Path(raw),
                    root=ROOT, gitignored=lambda _path: True,
                    # synthetic plan fixture: the CALLER declares the opt-out, never the plan itself.
                    require_reviewed_policy=False,
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
                    "content": "AAPL demand evidence", "published_date": CURRENT_WEEK_PUBLISHED_AT,
                }]

        web_outcome = web.execute_live_web_orchestration(
            queries=["q1", "q2"], expected_decision_date=DECISION_DATE,
            tavily=Tavily(), deepseek_client=object(), transport=_live_transport("tavily", "deepseek"),
            dispatch_budget=AbortAfterOne(), persist_search_response=_noop_persist,
            persist_regroup_response=_noop_persist,
            query_records=["q1", "q2"], parent_plan=None,
        )
        self.assertIsInstance(web_outcome["budget_error"], plan_budget.PlanBudgetError)
        self.assertEqual(len(web_outcome["results"]), 1)
        self.assertIn("plan_budget_aborted", [row["reason"] for row in web_outcome["query_drops"]])

        class XClient:
            def search(self, query, _expected):
                return {"text": '{"themes":[]}', "results": [], "annotation_urls": []}

        x_outcome = xfetch.execute_live_x_orchestration(
            queries=["q1", "q2"], expected_decision_date=DECISION_DATE,
            client=XClient(), dispatch_budget=AbortAfterOne(), transport=_live_transport("xai"),
            persist_response=_noop_persist, query_records=["q1", "q2"], parent_plan=None,
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
                # synthetic plan fixture: the CALLER declares the opt-out, never the plan itself.
                require_reviewed_policy=False,
            )
            with self.assertRaisesRegex(plan_budget.PlanBudgetError, "outside the reserved provider scope"):
                budget.begin("xai", scope="wrong-scope", stage="stage1")

    def test_A4_budget_abort_uses_diagnostic_slot_not_formal_decision_slots(self):
        self.assertTrue(web.is_diagnostic_only_execution_status("live_authorized_budget_aborted"))
        self.assertFalse(web.is_diagnostic_only_execution_status("live_authorized_paid_evidence_unavailable"))
        self.assertFalse(web.is_diagnostic_only_execution_status("live_authorized_completed"))
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

    def test_K5_packet_schema_and_diagnostic_parent_plan_freeze_one_web_stage2_call(self):
        packet = json.loads(
            (ROOT / "docs/us_short_web_regroup_engineering_smoke_packet_20260815_v2.json").read_text(
                encoding="utf-8"
            )
        )
        schema = json.loads(
            (ROOT / "schemas/us_short_web_regroup_engineering_smoke_packet_v2.schema.json").read_text(
                encoding="utf-8"
            )
        )
        from jsonschema import Draft7Validator
        errors = list(Draft7Validator(schema).iter_errors(packet))
        self.assertEqual(errors, [])
        self.assertEqual(packet["paid_boundary"]["call_counts"], {
            "tavily": 0, "deepseek": 1, "xai": 0, "retry": 0,
            "recovery": 0, "unknown_sibling": 0,
        })
        parent = smoke._build_diagnostic_parent_plan(packet)
        envelopes = {
            row["provider"]: row
            for row in parent["canonical_plan_core"]["provider_envelopes"]
        }
        self.assertEqual(envelopes["web"]["stage1_max_dispatch_count"], 0)
        self.assertEqual(envelopes["web"]["stage2_max_dispatch_count"], 1)
        self.assertEqual(envelopes["web"]["retry_max_dispatch_count"], 0)
        self.assertEqual(envelopes["web"]["max_dispatch_count"], 1)
        self.assertEqual(envelopes["xai"]["max_dispatch_count"], 0)

    def test_K5_consumed_v3_packet_cannot_reuse_the_v4_runtime(self):
        packet = json.loads(
            (ROOT / "docs/us_short_web_regroup_engineering_smoke_packet_20260815_v3.json").read_text(
                encoding="utf-8"
            )
        )
        with self.assertRaisesRegex(smoke.EngineeringSmokeError, "runtime output paths"):
            smoke._assert_packet_contract(packet)

    def test_K5_v4_packet_identity_branch_accepts_tracked_packet(self):
        packet = json.loads(
            (ROOT / "docs/us_short_web_regroup_engineering_smoke_packet_20260815_v4.json").read_text(
                encoding="utf-8"
            )
        )
        smoke._assert_packet_contract(packet)

    def test_K5_v3_packet_mutation_stops_before_budget_or_client(self):
        with _k5_smoke_fixture(packet_version=3) as fixture:
            forged = json.loads(json.dumps(fixture["packet"]))
            forged["input"]["target_chunk_index"] = 2
            with mock.patch.object(smoke, "_validate_packet", return_value=forged):
                with self.assertRaisesRegex(smoke.EngineeringSmokeError, "target or prompt binding"):
                    smoke.run_one_shot(
                        forged, confirm_user_authorization=forged["packet_id"],
                    )
            fixture["reserve_mock"].assert_not_called()
            fixture["client_constructor"].assert_not_called()

    def test_K5_requires_exact_packet_confirmation_before_fixed_main_tree_gate(self):
        packet = json.loads(
            (ROOT / "docs/us_short_web_regroup_engineering_smoke_packet_20260815_v2.json").read_text(
                encoding="utf-8"
            )
        )
        with mock.patch.object(smoke, "_validate_packet", return_value=packet):
            with self.assertRaisesRegex(smoke.EngineeringSmokeError, "exact packet authorization"):
                smoke.run_one_shot(packet, confirm_user_authorization="--live")

    def test_K5_smoke_statuses_use_private_publisher_and_normal_status_is_rejected(self):
        self.assertTrue(web.is_diagnostic_only_execution_status(
            "live_authorized_engineering_smoke_response_captured"
        ))
        self.assertTrue(web.is_diagnostic_only_execution_status(
            "live_authorized_engineering_smoke_call_failed"
        ))
        self.assertFalse(web.is_diagnostic_only_execution_status("live_authorized_completed"))
        with temporary_us_short_state_directory(ROOT) as raw:
            old_state = web.STATE_DIR
            try:
                web.STATE_DIR = Path(raw)
                summary = {
                    "status": "live_authorized_engineering_smoke_call_failed",
                    "packet_id": "us_short_web_regroup_engineering_smoke_20260815_chunk1_v2",
                    "summary_ref": "state/us_short/runs_private/soft_discovery_engineering_smoke_v2/us_short_web_regroup_engineering_smoke_20260815_chunk1_summary.json",
                    "formal_decision_slots_occupied": False,
                }
                with mock.patch.object(web, "_gitignored", return_value=True):
                    path = web.publish_engineering_smoke_diagnostic(summary)
                self.assertTrue(path.exists())
                self.assertEqual(
                    json.loads(path.read_text(encoding="utf-8"))["status"],
                    summary["status"],
                )
                v4_summary_ref = "state/us_short/runs_private/soft_discovery_engineering_smoke_v4/us_short_web_regroup_engineering_smoke_20260815_chunk1_summary.json"
                v4_path = web.publish_engineering_smoke_diagnostic({
                    **summary,
                    "packet_id": "us_short_web_regroup_engineering_smoke_20260815_chunk1_v4",
                    "summary_ref": v4_summary_ref,
                })
                self.assertEqual(
                    v4_path,
                    Path(raw) / Path(v4_summary_ref).relative_to("state/us_short"),
                )
                with self.assertRaises(TypeError):
                    web.publish_engineering_smoke_diagnostic(
                        summary, path=Path(raw) / "caller_selected.json",
                    )
                with self.assertRaisesRegex(web.WebThemeDiscoveryError, "diagnostic-only"):
                    web.publish_engineering_smoke_diagnostic({
                        "status": "live_authorized_completed",
                        "formal_decision_slots_occupied": False,
                    })
                with self.assertRaisesRegex(web.WebThemeDiscoveryError, "diagnostic-only"):
                    web.publish_engineering_smoke_diagnostic({
                        "status": "live_authorized_budget_aborted",
                        "formal_decision_slots_occupied": False,
                    })
            finally:
                web.STATE_DIR = old_state

    def test_K5_rendered_prompt_gate_calls_the_production_builder(self):
        rows = [{
            "source_id": "web:" + "a" * 64,
            "url": "https://example.com/evidence",
            "title": "Evidence title",
            "content": "AAPL demand evidence",
            "published_date": "2026-08-14T12:00:00+00:00",
        }]
        prompt = web._build_deepseek_prompt("20260815", rows)
        packet = {
            "source_decision_date": "20260815",
            "input": {"rendered_prompt_sha256": web._sha256_bytes(prompt.encode("utf-8"))},
        }
        self.assertEqual(smoke._validate_rendered_prompt(packet, rows), prompt)
        packet["input"]["rendered_prompt_sha256"] = "0" * 64
        with self.assertRaisesRegex(smoke.EngineeringSmokeError, "prompt digest"):
            smoke._validate_rendered_prompt(packet, rows)

    def test_K5_unparsed_theme_status_keeps_semantic_not_evaluated(self):
        self.assertEqual(
            smoke._post_check_status(None, failure_reason="max_themes_exceeded"),
            ("failed", "not_evaluated"),
        )

    def test_K5_runner_does_not_reference_formal_decision_publisher_or_slots(self):
        source = Path(smoke.__file__).read_text(encoding="utf-8")
        self.assertNotIn("publish_decision_pair", source)
        self.assertNotIn("default_discovery_path", source)
        self.assertNotIn("default_receipt_path", source)

    def test_K5_required_2_run_one_shot_revalidates_tampered_packet_before_budget_or_client(self):
        packet = json.loads(
            (ROOT / "docs/us_short_web_regroup_engineering_smoke_packet_20260815_v2.json").read_text(
                encoding="utf-8"
            )
        )
        forged = json.loads(json.dumps(packet))
        forged["input"]["target_chunk_index"] = 2
        with mock.patch.object(smoke, "_validate_packet", return_value=packet) as validate, \
                mock.patch.object(plan_budget, "reserve_plan_budget", side_effect=AssertionError("budget constructed")) as reserve, \
                mock.patch.object(paid_gateway, "DeepSeekClient", side_effect=AssertionError("client constructed")) as client:
            with self.assertRaisesRegex(smoke.EngineeringSmokeError, "does not match"):
                smoke.run_one_shot(
                    forged, confirm_user_authorization=packet["packet_id"],
                )
        validate.assert_called_once_with(smoke.PACKET_PATH)
        reserve.assert_not_called()
        client.assert_not_called()

    def test_K5_new_summary_marks_identity_rejection_content_checks_not_evaluated(self):
        with _k5_smoke_fixture(response=_k5_response(model=None)) as fixture:
            summary = smoke.run_one_shot(
                fixture["packet"], confirm_user_authorization=fixture["packet"]["packet_id"],
            )
        self.assertEqual(summary["transport_verdict"], "FAIL")
        self.assertEqual(summary["strict_parse_error_reason"], "served_model_missing")
        self.assertEqual(summary["strict_parse_error_detail"], "chunk[1]:served_model")
        self.assertEqual(summary["max_four_themes_status"], "not_evaluated")
        self.assertEqual(summary["semantic_fields_status"], "not_evaluated")
        self.assertEqual(summary["requested_model"], "deepseek-v4-pro")
        self.assertIsNone(summary["served_model"])
        self.assertFalse(summary["model_identity_complete"])
        self.assertFalse(summary["model_identity_match"])
        self.assertEqual(summary["system_fingerprint"], "fp_test")
        self.assertEqual(summary["budget_ledger_ref"], fixture["packet"]["output_boundary"]["budget_ledger_ref"])
        self.assertEqual(summary["deepseek_call_count"], 1)

    def test_K5_served_model_gate_rejects_aliases_before_content_parse(self):
        for label, model in {
            "flash": "deepseek-v4-flash",
            "old_alias": "deepseek-chat",
            "other_model": "deepseek-other",
        }.items():
            with self.subTest(model=label), _k5_smoke_fixture(response=_k5_response(model=model)) as fixture:
                with mock.patch.object(web, "_parse_llm_json", side_effect=AssertionError("parser reached")) as parser:
                    summary = smoke.run_one_shot(
                        fixture["packet"], confirm_user_authorization=fixture["packet"]["packet_id"],
                    )
                parser.assert_not_called()
                self.assertEqual(summary["transport_verdict"], "FAIL")
                self.assertEqual(summary["strict_parse_error_reason"], "served_model_mismatch")
                self.assertTrue(summary["model_identity_complete"])
                self.assertFalse(summary["model_identity_match"])
                self.assertEqual(len(fixture["budget"].calls), 1)
                self.assertEqual(len(fixture["client"].requests), 1)

    def test_K5_expected_served_model_mutation_stops_before_budget_or_client(self):
        with _k5_smoke_fixture() as fixture:
            forged = json.loads(json.dumps(fixture["packet"]))
            forged["paid_boundary"]["request"]["expected_served_model"] = "deepseek-v4-flash"
            with mock.patch.object(smoke, "_validate_packet", return_value=forged):
                with self.assertRaisesRegex(smoke.EngineeringSmokeError, "paid boundary"):
                    smoke.run_one_shot(
                        forged, confirm_user_authorization=forged["packet_id"],
                    )
            fixture["reserve_mock"].assert_not_called()
            fixture["client_constructor"].assert_not_called()

    def test_K5_new_summary_reads_counts_from_the_budget_ledger(self):
        with _k5_smoke_fixture() as fixture:
            real_write = fixture["budget"]._write_ledger

            def undercount(status):
                real_write(status)
                ledger = json.loads(fixture["budget"].ledger_path.read_text(encoding="utf-8"))
                ledger["vendor_dispatch_counts"]["deepseek"] = 0
                fixture["budget"].ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

            with mock.patch.object(fixture["budget"], "_write_ledger", side_effect=undercount):
                summary = smoke.run_one_shot(
                    fixture["packet"],
                    confirm_user_authorization=fixture["packet"]["packet_id"],
                )
        self.assertEqual(summary["deepseek_call_count"], 0)
        self.assertEqual(summary["transport_verdict"], "FAIL")

    def test_K5_packet_prompt_and_runtime_output_mutations_stop_before_budget_or_client(self):
        with _k5_smoke_fixture() as fixture:
            fixture["packet"]["input"]["rendered_prompt_sha256"] = "0" * 64
            with self.assertRaisesRegex(smoke.EngineeringSmokeError, "target or prompt binding"):
                smoke.run_one_shot(
                    fixture["packet"],
                    confirm_user_authorization=fixture["packet"]["packet_id"],
                )
            fixture["reserve_mock"].assert_not_called()
            fixture["client_constructor"].assert_not_called()

        with _k5_smoke_fixture() as fixture:
            formal_path = fixture["root"] / "state" / "us_short" / "formal.json"
            with mock.patch.object(smoke, "SUMMARY_PATH", formal_path):
                with self.assertRaisesRegex(smoke.EngineeringSmokeError, "runtime output paths"):
                    smoke.run_one_shot(
                        fixture["packet"],
                        confirm_user_authorization=fixture["packet"]["packet_id"],
                    )
            fixture["reserve_mock"].assert_not_called()
            fixture["client_constructor"].assert_not_called()

    def test_K5_13_1_target_chunk_is_derived_from_production_order_not_receipt_storage_order(self):
        fetched_at = datetime(2026, 8, 15, tzinfo=timezone.utc)
        raw_rows = [{
            "url": f"https://example.com/source-{index:02d}",
            "title": f"Title {index:02d}",
            "content": f"AAPL demand evidence {index:02d}",
            "published_date": "2026-08-14T00:00:00+00:00",
        } for index in range(34)]
        refs, prompt_rows, drops = web._normalize_search_results(
            raw_rows, expected_decision_date=DECISION_DATE, fetched_at=fetched_at,
            raw_root=None, persist_raw=False,
        )
        self.assertEqual(drops, [])
        chunks = web._chunk_regroup_rows(prompt_rows)
        self.assertEqual([len(chunk) for chunk in chunks], [10, 10, 10, 4])
        with tempfile.TemporaryDirectory(prefix="us_short_k5_order_") as raw:
            root = Path(raw)
            raw_dir = root / "provider_samples" / "us_short_llm_theme_discovery_fetch_web" / "raw" / DECISION_DATE
            raw_dir.mkdir(parents=True)
            raw_by_url = {row["url"]: row for row in raw_rows}
            receipt_refs = []
            for ref in refs:
                source_id = ref["source_id"]
                source_path = raw_dir / f"{source_id.split(':', 1)[1]}.json"
                source_row = raw_by_url[ref["canonical_locator"]]
                source_path.write_text(json.dumps({
                    "source_id": source_id,
                    "source_type": "web",
                    "canonical_locator": ref["canonical_locator"],
                    "title": source_row["title"],
                    "content": source_row["content"],
                    "published_at": ref["observed_at"],
                }), encoding="utf-8")
                receipt_refs.append({
                    **ref,
                    "raw_receipt_ref": (
                        f"provider_samples/us_short_llm_theme_discovery_fetch_web/raw/"
                        f"{DECISION_DATE}/{source_path.name}"
                    ),
                    "raw_receipt_gitignored": True,
                })
            stored_refs = list(reversed(receipt_refs))
            receipt_path = root / "state" / "us_short" / "receipt.json"
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps({
                "decision_clock": {"expected_decision_date": DECISION_DATE},
                "source_refs": stored_refs,
            }), encoding="utf-8")
            by_id = {ref["source_id"]: ref for ref in stored_refs}
            target = chunks[1]
            packet = {
                "input": {
                    "receipt_ref": "state/us_short/receipt.json",
                    "receipt_sha256": "unused-in-direct-preflight",
                    "accepted_source_count": 34,
                    "target_chunk_index": 1,
                    "target_source_ids": [row["source_id"] for row in target],
                    "target_source_refs": [by_id[row["source_id"]] for row in target],
                },
            }
            with mock.patch.object(smoke, "ROOT", root):
                target_rows = smoke._frozen_target_rows(packet)
            self.assertEqual(
                [row["source_id"] for row in target_rows], packet["input"]["target_source_ids"],
            )
            self.assertNotEqual(
                [ref["source_id"] for ref in stored_refs[10:20]],
                packet["input"]["target_source_ids"],
                "direct receipt slicing must be a live negative control",
            )
            flattened = [row["source_id"] for chunk in chunks for row in chunk]
            self.assertEqual(len(flattened), len(set(flattened)))
            self.assertEqual(set(flattened), {ref["source_id"] for ref in stored_refs})

    def test_K5_13_1_cli_has_no_free_model_or_output_shape_arguments(self):
        with self.assertRaises(SystemExit):
            smoke.main([
                "--confirm-user-authorization", "packet-id", "--model", "other-model",
            ])

    def test_K5_13_2_one_shot_uses_one_gateway_attempt_and_private_budget(self):
        with _k5_smoke_fixture() as fixture:
            summary = smoke.run_one_shot(
                fixture["packet"], confirm_user_authorization=fixture["packet"]["packet_id"],
            )
            self.assertEqual(summary["transport_verdict"], "PASS")
            self.assertEqual(len(fixture["budget"].calls), 1)
            self.assertEqual(len(fixture["client"].requests), 1)
            self.assertTrue(fixture["private_root"].exists())
            self.assertNotIn("formal_decision", str(fixture["private_root"]))
            self.assertIn("require_reviewed_policy=True", Path(smoke.__file__).read_text(encoding="utf-8"))

    def test_K5_13_2_second_gateway_chunk_is_stopped_by_the_real_budget(self):
        parent = _parent(stage1=0, stage2=1, retry=0)
        client = _K5FakeDeepSeek(_k5_response())
        rows = [{"source_id": "web:" + "b" * 64, "title": "t", "content": "c"}]
        with temporary_us_short_state_directory(ROOT) as raw:
            budget = plan_budget.reserve_plan_budget(
                parent, state_dir=Path(raw), root=ROOT, gitignored=lambda _path: True,
                providers=("web",), require_reviewed_policy=False,
            )
            batch = paid_gateway.PaidDispatchGateway(
                budget, parent_plan=parent,
            ).dispatch_web_regroup_all(
                client, expected_decision_date=DECISION_DATE,
                chunks=[(1, rows), (2, rows)], prompt_builder=lambda _date, _rows: "prompt",
                persist_response=_noop_persist,
            )
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(len(batch.items), 1)
        self.assertIsInstance(batch.stop_error, plan_budget.PlanBudgetError)

    def test_K5_13_3_raw_exists_before_parser_and_bad_json_remains_replayable(self):
        with _k5_smoke_fixture(response=_k5_response(content="not json")) as fixture:
            raw_seen_by_parser: list[bool] = []
            real_consumer = web._consume_regroup_response

            def consume(response, *, expected_served_model, chunk_index):
                raw_seen_by_parser.append(any(fixture["provider_root"].rglob("*.json")))
                return real_consumer(
                    response, expected_served_model=expected_served_model, chunk_index=chunk_index,
                )

            with mock.patch.object(web, "_consume_regroup_response", side_effect=consume):
                summary = smoke.run_one_shot(
                    fixture["packet"], confirm_user_authorization=fixture["packet"]["packet_id"],
                )
            self.assertEqual(raw_seen_by_parser, [True])
            self.assertEqual(summary["transport_verdict"], "FAIL")
            self.assertEqual(summary["strict_parse_status"], "failed")
            self.assertTrue(any(fixture["provider_root"].rglob("*.json")))
            self.assertEqual(len(fixture["budget"].calls), 1)

    def test_K5_13_3_raw_write_failure_and_unsafe_response_skip_parser(self):
        for label, kwargs in (
            ("writer", {"persist_error": web.WebThemeDiscoveryError("raw writer failed")}),
            ("unsafe", {"response": object()}),
        ):
            with self.subTest(case=label), _k5_smoke_fixture(**kwargs) as fixture:
                with mock.patch.object(web, "_consume_regroup_response") as consume:
                    with self.assertRaises(smoke.EngineeringSmokeError):
                        smoke.run_one_shot(
                            fixture["packet"],
                            confirm_user_authorization=fixture["packet"]["packet_id"],
                        )
                consume.assert_not_called()
                self.assertEqual(len(fixture["budget"].calls), 1)
                self.assertFalse(fixture["summary_path"].exists())

    def test_K5_13_4_request_and_response_metadata_are_pinned(self):
        response = _k5_response()
        with _k5_smoke_fixture(response=response) as fixture:
            summary = smoke.run_one_shot(
                fixture["packet"], confirm_user_authorization=fixture["packet"]["packet_id"],
            )
            request = fixture["client"].requests[0]
            self.assertEqual(request["model"], paid_gateway.DEEPSEEK_MODEL)
            self.assertEqual(request["temperature"], 0)
            self.assertEqual(request["max_tokens"], paid_gateway.DEEPSEEK_REGROUP_MAX_TOKENS)
            self.assertEqual(request["response_format"], {"type": "json_object"})
            self.assertEqual(summary["served_model"], "deepseek-v4-pro")
            self.assertEqual(summary["expected_served_model"], "deepseek-v4-pro")
            self.assertTrue(summary["model_identity_complete"])
            self.assertTrue(summary["model_identity_match"])
            self.assertEqual(summary["usage"], response["usage"])
            self.assertEqual(summary["finish_reason"], "stop")
            self.assertEqual(summary["original_chunk_index"], 1)
            self.assertEqual(summary["parsed_theme_count"], 0)
            persisted_summary = json.loads(fixture["summary_path"].read_text(encoding="utf-8"))
            self.assertNotIn("response", persisted_summary)
            self.assertNotIn("sk-", json.dumps(persisted_summary))

    def test_K5_13_4_bad_provider_metadata_is_failure_without_refill(self):
        usage_missing = _k5_response()
        usage_missing["usage"] = None
        variants = {
            "served_model_missing": _k5_response(model=None),
            "served_model_empty": _k5_response(model=""),
            "usage_missing": usage_missing,
            "finish_length": _k5_response(finish_reason="length"),
            "five_themes": _k5_response(content=json.dumps({"themes": [{}, {}, {}, {}, {}]})),
        }
        for label, response in variants.items():
            with self.subTest(case=label), _k5_smoke_fixture(response=response) as fixture:
                summary = smoke.run_one_shot(
                    fixture["packet"], confirm_user_authorization=fixture["packet"]["packet_id"],
                )
                self.assertEqual(summary["transport_verdict"], "FAIL")
                self.assertEqual(len(fixture["budget"].calls), 1)
                self.assertEqual(len(fixture["client"].requests), 1)

    def test_K5_13_5_formal_slots_and_publisher_are_unreachable(self):
        with _k5_smoke_fixture() as fixture:
            formal_paths = (
                web.default_discovery_path(DECISION_DATE),
                web.default_receipt_path(DECISION_DATE),
            )
            frozen = []
            for path in formal_paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"frozen-formal-slot")
                frozen.append(path.read_bytes())
            with mock.patch.object(
                web, "publish_decision_pair", side_effect=AssertionError("formal publisher reached"),
            ):
                summary = smoke.run_one_shot(
                    fixture["packet"], confirm_user_authorization=fixture["packet"]["packet_id"],
                )
            self.assertEqual(summary["transport_verdict"], "PASS")
            self.assertEqual([path.read_bytes() for path in formal_paths], frozen)
            self.assertFalse(summary["formal_decision_slots_occupied"])

    def test_K5_13_6_each_failure_shape_spends_once_and_replay_is_refused_before_provider(self):
        completion = plan_budget.PostPaymentDispatchError(RuntimeError("ledger completion failed"))
        cases = (
            ("response_captured", {}, "PASS"),
            ("call_failed", {"client_error": paid_gateway.PaidProviderError("provider failed")}, "FAIL"),
            ("completion_ledger_error", {"completion_error": completion}, "FAIL"),
            ("raw_persistence_error", {"persist_error": web.WebThemeDiscoveryError("raw failed")}, None),
            ("summary_write_error", {"publish_error": RuntimeError("summary failed")}, None),
        )
        for label, kwargs, expected_verdict in cases:
            with self.subTest(case=label), _k5_smoke_fixture(**kwargs) as fixture:
                first_error = None
                try:
                    first = smoke.run_one_shot(
                        fixture["packet"],
                        confirm_user_authorization=fixture["packet"]["packet_id"],
                    )
                except BaseException as exc:
                    first_error = exc
                if expected_verdict is not None:
                    self.assertIsNone(first_error)
                    self.assertEqual(first["transport_verdict"], expected_verdict)
                else:
                    self.assertIsNotNone(first_error)
                self.assertEqual(len(fixture["budget"].calls), 1)
                with self.assertRaisesRegex(smoke.EngineeringSmokeError, "replay is forbidden"):
                    smoke.run_one_shot(
                        fixture["packet"],
                        confirm_user_authorization=fixture["packet"]["packet_id"],
                    )
                self.assertEqual(len(fixture["budget"].calls), 1)
                self.assertEqual(fixture["reserve_mock"].call_count, 1)
                self.assertEqual(fixture["client_constructor"].call_count, 1)

    def test_K5_13_7_raw_before_parse_mutation_control_is_load_bearing(self):
        with _k5_smoke_fixture() as fixture:
            raw_seen_by_parser: list[bool] = []
            real_consumer = web._consume_regroup_response

            def consume(response, *, expected_served_model, chunk_index):
                raw_seen_by_parser.append(any(fixture["provider_root"].rglob("*.json")))
                return real_consumer(
                    response, expected_served_model=expected_served_model, chunk_index=chunk_index,
                )

            with mock.patch.object(web, "_consume_regroup_response", side_effect=consume):
                summary = smoke.run_one_shot(
                    fixture["packet"], confirm_user_authorization=fixture["packet"]["packet_id"],
                )
            self.assertEqual(summary["transport_verdict"], "PASS")
            self.assertEqual(raw_seen_by_parser, [True])

    def test_K5_13_7_formal_publisher_mutation_control_is_runtime_not_grep_only(self):
        with _k5_smoke_fixture() as fixture:
            with mock.patch.object(
                web, "publish_decision_pair", side_effect=AssertionError("formal publisher reached"),
            ):
                summary = smoke.run_one_shot(
                    fixture["packet"], confirm_user_authorization=fixture["packet"]["packet_id"],
                )
            self.assertEqual(summary["transport_verdict"], "PASS")

    def test_K5_13_7_status_consumer_disconnect_is_rejected(self):
        with _k5_smoke_fixture() as fixture:
            with mock.patch.object(web, "ENGINEERING_SMOKE_EXECUTION_STATUSES", frozenset()):
                with self.assertRaisesRegex(web.WebThemeDiscoveryError, "diagnostic-only"):
                    smoke.run_one_shot(
                        fixture["packet"],
                        confirm_user_authorization=fixture["packet"]["packet_id"],
                    )
            self.assertEqual(len(fixture["budget"].calls), 1)

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
                    "content": "AAPL demand evidence", "published_date": CURRENT_WEEK_PUBLISHED_AT,
                }]

        web_outcome = web.execute_live_web_orchestration(
            queries=["q"], expected_decision_date=DECISION_DATE,
            tavily=Tavily(), deepseek_client=object(), transport=_live_transport("tavily", "deepseek"),
            dispatch_budget=CompletionAfterReturn(), persist_search_response=_noop_persist,
            persist_regroup_response=_noop_persist,
            query_records=["q"], parent_plan=None,
        )
        self.assertIsInstance(web_outcome["budget_error"], plan_budget.PostPaymentDispatchError)
        self.assertEqual(web_outcome["provider_call_count"], 1)
        self.assertEqual(len(web_outcome["results"]), 1)

        class XClient:
            def search(self, query, _expected):
                return {"text": '{"themes": []}', "results": [], "annotation_urls": []}

        x_outcome = xfetch.execute_live_x_orchestration(
            queries=["q"], expected_decision_date=DECISION_DATE,
            client=XClient(), dispatch_budget=CompletionAfterReturn(), transport=_live_transport("xai"),
            persist_response=_noop_persist, query_records=["q"], parent_plan=None,
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
            "published_date": CURRENT_WEEK_PUBLISHED_AT,
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
                tavily=object(), deepseek_client=object(), transport=_live_transport("tavily", "deepseek"),
                dispatch_budget=web_budget, persist_search_response=None,
                persist_regroup_response=None,
                query_records=["q"], parent_plan=None,
            )
        self.assertEqual(web_budget.calls, 0)

        x_budget = Budget()
        with self.assertRaisesRegex(plan_budget.PlanBudgetError, "persist_response"):
            xfetch.execute_live_x_orchestration(
                queries=["q"], expected_decision_date=DECISION_DATE,
                client=object(), dispatch_budget=x_budget, transport=_live_transport("xai"),
                persist_response=None, query_records=["q"], parent_plan=None,
            )
        self.assertEqual(x_budget.calls, 0)

    def test_P5_paid_orchestration_keywords_are_required_by_derived_ast_predicate(self):
        paths = [
            ROOT / "runners" / "us_short_llm_theme_discovery_fetch_web.py",
            ROOT / "runners" / "us_short_llm_theme_discovery_fetch_x.py",
        ]
        for source_path in paths:
            with self.subTest(module_name=source_path.name):
                self.assertEqual(_live_orchestration_optional_keyword_offenders(source_path), [])
                source = source_path.read_text(encoding="utf-8")
                needle = "query_records: list[str] | list[dict[str, str]],"
                offset = source.index(needle)
                replacement = "query_records: list[str] | list[dict[str, str]] = None,"
                mutated = "".join((source[:offset], replacement, source[offset + len(needle):]))
                self.assertTrue(
                    _live_orchestration_optional_keyword_offenders_from_source(mutated),
                    "a newly optional paid keyword must turn the derived predicate red",
                )
        # The keyword-only walk alone was blind to two other escape routes; both must be caught.
        for label, escape in (
            ("positional-with-default", "def execute_live_web_orchestration(queries, plan=None):\n    pass\n"),
            ("**kwargs", "def execute_live_web_orchestration(*, queries, **paid):\n    pass\n"),
        ):
            with self.subTest(escape=label):
                self.assertTrue(
                    _live_orchestration_optional_keyword_offenders_from_source(escape),
                    f"a {label} money-path escape must turn the derived predicate red",
                )
        self.assertEqual(
            _live_orchestration_optional_keyword_offenders_from_source(
                "def execute_live_web_orchestration(*, queries, plan):\n    pass\n"
            ),
            [], "an all-required signature must stay green (false-positive control)",
        )

    def test_P5_parent_plan_rejects_bare_query_records_before_any_budget_call(self):
        class Budget:
            def __init__(self):
                self.calls = 0

            def dispatch_with_outcome(self, _provider, *, scope, stage, call):
                del scope, stage, call
                self.calls += 1
                return plan_budget.DispatchOutcome(value=[])

        class Tavily:
            def __init__(self):
                self.calls = []

            def search(self, query):
                self.calls.append(query)
                return []

        class XClient:
            def __init__(self):
                self.calls = []

            def search(self, query, _expected):
                self.calls.append(query)
                return {"text": '{"themes":[]}', "results": [], "annotation_urls": []}

        parent = _parent(stage1=1, stage2=0, retry=0)
        web_budget = Budget()
        web_client = Tavily()
        with self.assertRaisesRegex(paid_gateway.PaidProviderError, "plan query record"):
            web.execute_live_web_orchestration(
                queries=["off-plan"], expected_decision_date=DECISION_DATE,
                tavily=web_client, deepseek_client=object(),
                transport=_live_transport("tavily", "deepseek"), dispatch_budget=web_budget,
                persist_search_response=_noop_persist, persist_regroup_response=_noop_persist,
                query_records=None, parent_plan=parent,
            )
        self.assertEqual(web_budget.calls, 0)
        self.assertEqual(web_client.calls, [])

        x_budget = Budget()
        x_client = XClient()
        with self.assertRaisesRegex(paid_gateway.PaidProviderError, "plan query record"):
            xfetch.execute_live_x_orchestration(
                queries=["off-plan"], expected_decision_date=DECISION_DATE,
                client=x_client, dispatch_budget=x_budget,
                transport=_live_transport("xai"), persist_response=_noop_persist,
                query_records=None, parent_plan=parent,
            )
        self.assertEqual(x_budget.calls, 0)
        self.assertEqual(x_client.calls, [])

    def test_P5_live_orchestration_requires_a_concrete_transport_before_dispatch(self):
        class Budget:
            def __init__(self):
                self.calls = 0

            def dispatch_with_outcome(self, _provider, *, scope, stage, call):
                del scope, stage, call
                self.calls += 1
                return plan_budget.DispatchOutcome(value=[])

        web_budget = Budget()
        with self.assertRaisesRegex(plan_budget.PlanBudgetError, "transport"):
            web.execute_live_web_orchestration(
                queries=["q"], expected_decision_date=DECISION_DATE,
                tavily=object(), deepseek_client=object(), transport=None,
                dispatch_budget=web_budget, persist_search_response=_noop_persist,
                persist_regroup_response=_noop_persist,
                query_records=["q"], parent_plan=None,
            )
        self.assertEqual(web_budget.calls, 0)

        x_budget = Budget()
        with self.assertRaisesRegex(plan_budget.PlanBudgetError, "transport"):
            xfetch.execute_live_x_orchestration(
                queries=["q"], expected_decision_date=DECISION_DATE,
                client=object(), dispatch_budget=x_budget, transport=None,
                persist_response=_noop_persist, query_records=["q"], parent_plan=None,
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
                tavily=Tavily(), deepseek_client=object(), transport=_live_transport("tavily", "deepseek"),
                dispatch_budget=Budget(), persist_search_response=_noop_persist,
                persist_regroup_response=_noop_persist,
                query_records=["q"], parent_plan=None,
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
                tavily=object(), deepseek_client=object(), transport=_live_transport("tavily", "deepseek"),
                dispatch_budget=None, persist_search_response=_noop_persist,
                persist_regroup_response=_noop_persist,
                query_records=["q"], parent_plan=None,
            )
        with self.assertRaisesRegex(plan_budget.PlanBudgetError, "dispatch_budget"):
            xfetch.execute_live_x_orchestration(
                queries=["q"], expected_decision_date=DECISION_DATE,
                client=object(), dispatch_budget=None, transport=_live_transport("xai"),
                persist_response=_noop_persist, query_records=["q"], parent_plan=None,
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


class _RecordingBudget:
    """Records the stage of every charge so a test can prove a denial cost nothing."""

    def __init__(self):
        self.stages = []

    def dispatch_with_outcome(self, _provider, *, scope, stage, call):
        del scope
        self.stages.append(stage)
        return plan_budget.DispatchOutcome(value=call())


class _RecordingTavily:
    def __init__(self):
        self.paid = []

    def search(self, query):
        self.paid.append(query)
        return [{"url": f"https://example.com/{len(self.paid)}", "title": query,
                 "content": "AAPL demand evidence", "published_date": CURRENT_WEEK_PUBLISHED_AT}]


class _RecordingDeepSeek:
    """A WORKING regroup double: if Stage-2 is reached at all, it answers."""

    def __init__(self):
        self.paid = []
        outer = self

        class _Completions:
            @staticmethod
            def create(**kwargs):
                outer.paid.append(kwargs.get("model"))
                return {"choices": [{"message": {"content": '{"themes": []}'}}],
                        "model": "deepseek-v4-pro", "system_fingerprint": "fp_test"}

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


class PlanGateDecisionTableTests(unittest.TestCase):
    """The plan-bound money gate is a decision TABLE; these cases are generated from it.

    Three consecutive rounds each bolted one more `if` onto `_validate_plan_bound_request`, and
    each time a neighbouring cell was left wrong: a bare string under a plan was paid for, and
    then the legitimate Stage-2 regroup was refused AFTER Stage-1 had already been paid.
    Generating the cases from the same table the guard reads makes a forgotten combination show
    up as a missing row here instead of as a paid-path defect one round later.
    """

    # Hand-authored expectation, deliberately NOT derived from the module under test. Comparing
    # the engine table against itself only proves the code matches the table — self-review showed
    # a WRONG cell (membership check flipped to allow) survived every other case in this class.
    GOLDEN_DECISIONS = {
        ("stage1", "absent", "bare"): "allow",
        ("stage1", "absent", "record"): "deny_missing_plan",
        ("stage1", "valid", "bare"): "deny_missing_record",
        ("stage1", "valid", "record"): "verify_membership",
        ("stage1", "malformed", "bare"): "deny_malformed_plan",
        ("stage1", "malformed", "record"): "deny_malformed_plan",
        ("stage2", "absent", "bare"): "allow",
        ("stage2", "absent", "record"): "deny_stage1_only",
        ("stage2", "valid", "bare"): "allow",
        ("stage2", "valid", "record"): "deny_stage1_only",
        ("stage2", "malformed", "bare"): "deny_malformed_plan",
        ("stage2", "malformed", "record"): "deny_malformed_plan",
    }

    def test_P5_plan_gate_table_matches_the_hand_authored_expectation(self):
        self.assertEqual(paid_gateway.PLAN_GATE_DECISIONS, self.GOLDEN_DECISIONS)

    def test_P5_plan_gate_table_is_total_over_its_axes(self):
        expected = {
            (stage, plan, identity)
            for stage in paid_gateway.PLAN_GATE_STAGES
            for plan in paid_gateway.PLAN_GATE_PLAN_STATES
            for identity in paid_gateway.PLAN_GATE_IDENTITIES
        }
        self.assertEqual(set(paid_gateway.PLAN_GATE_DECISIONS), expected)
        known = {paid_gateway.PLAN_GATE_ALLOW, paid_gateway.PLAN_GATE_VERIFY_MEMBERSHIP}
        known |= set(paid_gateway.PLAN_GATE_DENIAL_MESSAGES)
        self.assertEqual(set(paid_gateway.PLAN_GATE_DECISIONS.values()) - known, set())

    def test_P5_an_unknown_or_drifted_stage_label_is_denied_not_waved_through(self):
        """A stage string outside the table must fail closed, not fall into a permissive bucket."""
        parent = _parent()
        for stage in ("stage2 ", "STAGE1", "stage1 ", "", "banana", "retry", "stage3"):
            with self.subTest(stage=stage):
                budget, client = _RecordingBudget(), _RecordingTavily()
                gateway = paid_gateway.PaidDispatchGateway(budget, parent_plan=parent)
                request = gateway._request("web", "scope", stage, lambda: client.search("x"))
                with self.assertRaisesRegex(paid_gateway.PaidProviderError, "not a known plan-gate stage"):
                    gateway._validate_plan_bound_request(request)
                self.assertEqual(budget.stages, [])
                self.assertEqual(client.paid, [])

    def test_P5_identity_check_catches_an_in_flight_plan_mutation(self):
        """The only thing the identity comparison can catch — so pin exactly that."""
        parent = _parent()
        record = query_plan.derive_stage1_query_records(parent)[0]
        budget = _RecordingBudget()
        gateway = paid_gateway.PaidDispatchGateway(budget, parent_plan=parent)
        request = gateway._request(
            "web", "scope", "stage1", lambda: None, query_id=record["query_id"],
            query_text=record["query_text"], query_text_sha256=record["query_text_sha256"],
        )
        gateway._validate_plan_bound_request(request)          # unmutated: accepted
        gateway._parent_plan = dict(parent, plan_identity="f" * 64)
        with self.assertRaisesRegex(paid_gateway.PaidProviderError, "does not match the parent plan"):
            gateway._validate_plan_bound_request(request)
        self.assertEqual(budget.stages, [])

    def test_P5_every_table_row_is_enforced_by_the_real_guard_before_any_charge(self):
        parent = _parent()
        record = query_plan.derive_stage1_query_records(parent)[0]
        plans = {"absent": None, "valid": parent, "malformed": object()}
        for (stage_axis, plan_axis, identity_axis), decision in sorted(
            paid_gateway.PLAN_GATE_DECISIONS.items()
        ):
            with self.subTest(stage=stage_axis, plan=plan_axis, identity=identity_axis):
                budget, client = _RecordingBudget(), _RecordingTavily()
                gateway = paid_gateway.PaidDispatchGateway(budget, parent_plan=plans[plan_axis])
                identity_kwargs = (
                    {"query_id": record["query_id"], "query_text": record["query_text"],
                     "query_text_sha256": record["query_text_sha256"]}
                    if identity_axis == "record" else {}
                )
                request = gateway._request(
                    "web", "scope", stage_axis, lambda: client.search("probe"), **identity_kwargs,
                )
                if decision in paid_gateway.PLAN_GATE_DENIAL_MESSAGES:
                    with self.assertRaises(paid_gateway.PaidProviderError) as caught:
                        gateway._validate_plan_bound_request(request)
                    self.assertEqual(str(caught.exception),
                                     paid_gateway.PLAN_GATE_DENIAL_MESSAGES[decision])
                    self.assertEqual(budget.stages, [], "a denied cell must cost nothing")
                    self.assertEqual(client.paid, [], "a denied cell must not reach the provider")
                else:
                    gateway._validate_plan_bound_request(request)

    def test_P5_plan_gate_policy_lives_only_in_the_decision_table(self):
        """The allow/deny decision must come from the table, not from a stage literal in the body.

        SCOPE, stated honestly: this catches the two forms the guard historically regressed into —
        a comparison against a stage string literal, and an early return before the table lookup.
        It does NOT catch every conceivable re-accretion (`in PLAN_GATE_STAGES`, `startswith`,
        `match/case`, a bare `return`); adversarial review confirmed each of those is caught by the
        BEHAVIOURAL cases in this class instead. Do not read this as a complete creep barrier.
        """
        source = Path(paid_gateway.__file__).read_text(encoding="utf-8")
        node = next(                                  # a METHOD, so walk (not just tree.body)
            candidate for candidate in ast.walk(ast.parse(source))
            if isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef))
            and candidate.name == "_validate_plan_bound_request"
        )
        body = ast.get_source_segment(source, node) or ""
        self.assertIn("plan_gate_decision(", body)

        def stage_literal_creep(candidate: str) -> list[str]:
            return [token for token in ('"stage1"', "'stage1'", '"stage2"', "'stage2'")
                    if token in candidate]

        self.assertEqual(stage_literal_creep(body), [],
                         "a stage literal crept back into the guard body")
        # PLANTED CONTROL: the detector must fire on a body that really did re-accrete the check.
        # (A first cut asserted a literal against a string it had just concatenated that literal
        # into — true for every input, i.e. a tautology. Feed the DETECTOR a crept body instead.)
        for crept in ('    if request.stage == "stage2":\n        return\n',
                      "    if request.stage != 'stage1':\n        return\n"):
            self.assertTrue(stage_literal_creep(crept),
                            "the detector cannot observe a reintroduced stage comparison")
        self.assertEqual(stage_literal_creep("    return None\n"), [],
                         "false-positive control: an unrelated body must stay clean")

    def test_P5_live_plan_run_reaches_stage2_regroup_after_stage1_is_paid(self):
        """FORCED-LEG POSITIVE CONTROL: tightening the gate must not brick the legitimate path.

        Every other case in this class asserts a denial. Without this one, refusing the Stage-2
        regroup (which carries no plan query id BY DESIGN) kept the whole lane pack green while a
        real live run paid for every Tavily call and then died before regrouping.
        """
        parent = _parent()
        records = query_plan.derive_stage1_query_records(parent)
        budget, tavily, deepseek = _RecordingBudget(), _RecordingTavily(), _RecordingDeepSeek()
        outcome = web.execute_live_web_orchestration(
            queries=[row["query_text"] for row in records], expected_decision_date=DECISION_DATE,
            tavily=tavily, deepseek_client=deepseek,
            transport=_live_transport("tavily", "deepseek"), dispatch_budget=budget,
             persist_search_response=_noop_persist, persist_regroup_response=_noop_persist,
             query_records=records, parent_plan=parent,
        )
        self.assertEqual(budget.stages, ["stage1"] * len(records) + ["stage2"])
        self.assertEqual(len(tavily.paid), len(records))
        self.assertEqual(len(deepseek.paid), 1, "the Stage-2 regroup must actually run")
        self.assertTrue(outcome["regroup_attempted"])

    def test_P5_live_orchestration_refuses_a_missing_or_foreign_transport(self):
        """Named control for the transport guard, which shipped with no test at all."""
        parent = _parent()
        records = query_plan.derive_stage1_query_records(parent)
        for label, transport in (("none", None), ("duck", object())):
            with self.subTest(lane="web", transport=label):
                budget = _RecordingBudget()
                with self.assertRaisesRegex(plan_budget.PlanBudgetError, "transport is required"):
                    web.execute_live_web_orchestration(
                        queries=[records[0]["query_text"]], expected_decision_date=DECISION_DATE,
                        tavily=_RecordingTavily(), deepseek_client=_RecordingDeepSeek(),
                        transport=transport, dispatch_budget=budget,
                        persist_search_response=_noop_persist, persist_regroup_response=_noop_persist,
                        query_records=records, parent_plan=parent,
                    )
                self.assertEqual(budget.stages, [])
            with self.subTest(lane="x", transport=label):
                budget = _RecordingBudget()
                with self.assertRaisesRegex(plan_budget.PlanBudgetError, "transport is required"):
                    xfetch.execute_live_x_orchestration(
                        queries=[records[0]["query_text"]], expected_decision_date=DECISION_DATE,
                        client=object(), dispatch_budget=budget, transport=transport,
                        persist_response=_noop_persist,
                        query_records=records, parent_plan=parent,
                    )
                self.assertEqual(budget.stages, [])

    def test_P5_the_off_plan_denial_cell_is_load_bearing(self):
        """Flipping ONLY that cell to `allow` must let the paid call through.

        The previous round closed this hole with a line no test covered: restoring the old
        permissive behaviour left every lane test green.
        """
        parent = _parent()
        cell = ("stage1", "valid", "bare")
        self.assertEqual(paid_gateway.PLAN_GATE_DECISIONS[cell], "deny_missing_record")
        budget, client = _RecordingBudget(), _RecordingTavily()
        gateway = paid_gateway.PaidDispatchGateway(budget, parent_plan=parent)
        with self.assertRaises(paid_gateway.PaidProviderError):
            gateway.dispatch_web_search_all(
                client, ["off-plan text"], persist_response=_noop_persist,
            )
        self.assertEqual(client.paid, [])
        flipped = dict(paid_gateway.PLAN_GATE_DECISIONS)
        flipped[cell] = paid_gateway.PLAN_GATE_ALLOW
        with mock.patch.object(paid_gateway, "PLAN_GATE_DECISIONS", flipped):
            gateway.dispatch_web_search_all(
                client, ["off-plan text"], persist_response=_noop_persist,
            )
        self.assertEqual(client.paid, ["off-plan text"],
                         "that cell must be what stops the payment")


if __name__ == "__main__":
    unittest.main()
