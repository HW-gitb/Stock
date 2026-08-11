"""Closed-world M6.7 field/rule-to-result contract.

The contract is deliberately static and local: it does not fetch data or infer
meaning from free text.  It makes an addition or modification to a decision
input, threshold, predicate, operation-impact source, task enum, or portfolio
factor fail tests until its terminal weekly surface is explicitly registered.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
import subprocess
from collections import Counter
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "schemas" / "a_short_m67_effect_contract.json"
LEGACY_MIGRATION_PATH = ROOT / "schemas" / "a_short_m67_effect_contract_legacy_migrations.json"
_CONTRACT_RELATIVE_PATH = "schemas/a_short_m67_effect_contract.json"
ANALYSIS_INPUT_SCHEMA_PATH = ROOT / "schemas" / "analysis_input.schema.json"
_DECISION_FILES = (
    "A-EGS/egs_main.py",
    "engine/egs_industry_heat.py",
    "engine/a_short_industry_theme.py",
    "engine/a_short_northbound.py",
    "engine/a_short_margin_overheat.py",
    "runners/a_short_phase5_engine.py",
    "runners/a_short_weekly_pipeline.py",
    "runners/a_short_m67_render.py",
    "engine/a_short_portfolio_risk.py",
    "engine/a_short_effect_contract.py",
)
_CONSTANT_FILES = (
    "A-EGS/egs_main.py",
    "engine/a_short_northbound.py",
    "engine/a_short_margin_overheat.py",
    "runners/a_short_phase5_engine.py",
    "engine/a_short_portfolio_risk.py",
)
_GOVERNED_LITERAL_FILES = _CONSTANT_FILES + ("runners/a_short_weekly_pipeline.py",)
_RUNTIME_CONFIG_FILE = "engine/a_short_runtime_config.py"
_RUNTIME_POLICY_FILES = (
    "presets/a_short_screening_threshold_governance_20260602.json",
    "presets/a_short_m67_runtime_policy_20260715.json",
    "presets/egs_industry_heat_governance_20260611.json",
)
_RUNTIME_POLICY_SCHEMA_FILES = (
    "schemas/a_short_screening_threshold_governance.schema.json",
    "schemas/a_short_m67_runtime_policy.schema.json",
)
_OUTPUT_SCHEMA_FILES = (
    "schemas/a_short_weekly_report.schema.json",
    "schemas/a_short_m67_report.schema.json",
)
_ANALYSIS_INPUT_SCHEMA_FILE = "schemas/analysis_input.schema.json"
_LEGACY_MIGRATION_FILE = "schemas/a_short_m67_effect_contract_legacy_migrations.json"
_STATIC_SOURCE_FILES = tuple(sorted(
    set(_DECISION_FILES) | set(_CONSTANT_FILES) | {_RUNTIME_CONFIG_FILE, _LEGACY_MIGRATION_FILE}
))
_DEFAULT_STATIC_SNAPSHOT_FILES = tuple(sorted(
    set(_STATIC_SOURCE_FILES)
    | {_ANALYSIS_INPUT_SCHEMA_FILE}
    | set(_RUNTIME_POLICY_FILES)
    | set(_RUNTIME_POLICY_SCHEMA_FILES)
    | set(_OUTPUT_SCHEMA_FILES)
))
_STATUSES = frozenset({"applied", "not_triggered", "unavailable_manual_review", "intentionally_independent"})
_POLICIES = frozenset({"must_affect_result", "intentionally_independent"})
_NATURES = frozenset({
    "true_dangling", "partial_consumption", "duplicate_source",
    "display_audit", "comparison_track", "main_decision", "delete",
})
_NATURE_RUNTIME_HANDLERS = {
    "display_audit": frozenset({"intentionally_independent"}),
    "duplicate_source": frozenset({"intentionally_independent"}),
    "delete": frozenset({"intentionally_independent"}),
    "true_dangling": frozenset({"unresolved_input_group"}),
    "partial_consumption": frozenset({"unresolved_input_group", "llm_tasks"}),
    "main_decision": frozenset({
        "lineage_gate", "phase5_decision", "phase5_risk", "market_regime",
        "industry_trend", "account_cash", "portfolio_risk", "llm_tasks",
        "m4_review_gate",
    }),
    "comparison_track": frozenset({"data_quality_shadow", "comparison_track", "technical_volatility_comparison"}),
}
_LEAF_EFFECT_CATEGORIES = frozenset({
    "m67_main_decision",
    "formal_comparison_verdict",
    "upstream_candidate_set_or_rank",
    "duplicate_or_display_audit",
    "intentionally_independent_or_delete",
    "producer_constant_null",
    "true_dangling",
    # Not yet adjudicated.  Distinct from ``true_dangling`` so a published count
    # can never present an un-audited remainder as a finished audit.
    "unclassified_pending_audit",
})


def _hash(value) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _schema_leaf_paths(schema: dict) -> list[str]:
    def deref(node: dict) -> dict:
        if "$ref" not in node:
            return node
        ref = node["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            raise ValueError(f"unsupported schema ref: {ref!r}")
        target = schema
        for part in ref[2:].split("/"):
            target = target[part]
        merged = dict(deref(target))
        merged.update({key: value for key, value in node.items() if key != "$ref"})
        return merged

    def walk(node: dict, prefix: str) -> list[str]:
        node = deref(node)
        props = node.get("properties") or {}
        if props:
            out = []
            for key, child in props.items():
                out.extend(walk(child, f"{prefix}.{key}" if prefix else str(key)))
            return out
        if "items" in node:
            return walk(node["items"], prefix + "[]")
        return [prefix]

    return sorted(walk(schema, ""))


def analysis_input_paths(schema: dict | None = None) -> list[str]:
    if schema is None:
        schema = json.loads(ANALYSIS_INPUT_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _schema_leaf_paths(schema)


def _matches_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "[]")


@lru_cache(maxsize=2048)
def _paths_for_prefixes_cached(paths: tuple[str, ...], prefixes: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(
        path for path in paths
        if any(_matches_prefix(path, prefix) for prefix in prefixes)
    ))


def _paths_for_prefixes(paths: list[str], prefixes: list[str]) -> list[str]:
    """Select the leaves a group owns.

    Memoized on the exact (paths, prefixes) pair.  One weekly report rebuilds
    the effect ledger, and one ledger asks this question ~210 times over the
    same 396-leaf list, so the uncached form spent 2.7M prefix comparisons per
    report -- 93% of the ledger's runtime by profile, and the single largest
    cost in the whole A-short lane.  The full path list is part of the key, so
    any change to the leaf set produces a different entry rather than a stale
    answer.
    """
    return list(_paths_for_prefixes_cached(tuple(paths), tuple(prefixes)))


def _leaf_nature_map(contract: dict, paths: list[str]) -> dict[str, str]:
    """Expand the contract's group-level nature rules to every input leaf."""
    groups = contract.get("groups")
    mapping = contract.get("leaf_nature_by_group")
    if not isinstance(mapping, dict):
        raise ValueError("leaf_nature_by_group missing")
    group_ids = {group.get("id") for group in groups if isinstance(group, dict)}
    if set(mapping) != group_ids:
        raise ValueError("leaf_nature_by_group must name every group exactly once")
    result: dict[str, str] = {}
    for group in groups:
        group_id = group["id"]
        nature = mapping[group_id]
        if nature not in _NATURES:
            raise ValueError(f"unknown nature for {group_id}: {nature!r}")
        for path in _paths_for_prefixes(paths, group.get("source_prefixes") or []):
            if path in result:
                raise ValueError(f"leaf assigned multiple natures: {path}")
            result[path] = nature
    if set(result) != set(paths):
        missing = sorted(set(paths) - set(result))
        extra = sorted(set(result) - set(paths))
        raise ValueError(f"leaf nature coverage mismatch: missing={missing[:4]}, extra={extra[:4]}")
    return result


def leaf_natures(contract: dict | None = None, inventory: dict | None = None) -> dict[str, str]:
    contract = contract if contract is not None else load_contract()
    inventory = inventory if inventory is not None else static_inventory()
    return _leaf_nature_map(contract, inventory["analysis_input_paths"])


def _producer_literal_leaves(egs_source: str) -> dict[str, str]:
    """Reconstruct which analysis-input leaves the producer emits as a literal.

    A leaf whose producing expression is the literal ``None`` can never be a
    consumer-wiring gap: nothing downstream could act on it even if it were
    read.  Deriving this mechanically keeps the ledger honest without a
    hand-written list that silently rots when the producer changes.
    """
    def walk(node, prefix: str, out: dict[str, str]) -> None:
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    walk(value, f"{prefix}.{key.value}" if prefix else key.value, out)
            return
        if isinstance(node, ast.List):
            inner = [element for element in node.elts if isinstance(element, ast.Dict)]
            for element in inner:
                walk(element, prefix + "[]", out)
            if not inner:
                out.setdefault(prefix, "computed")
            return
        if isinstance(node, ast.Constant):
            out[prefix] = "constant_null" if node.value is None else "computed"
            return
        if isinstance(node, ast.IfExp):
            branches: dict[str, str] = {}
            walk(node.body, prefix, branches)
            walk(node.orelse, prefix, branches)
            out[prefix] = branches.get(prefix, "computed")
            return
        out[prefix] = "computed"

    emitted: dict[str, str] = {}
    tree = ast.parse(egs_source)
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef) or function.name != "_candidate_from_row":
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                walk(node.value, "candidates[]", emitted)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) and any(
                    isinstance(target, ast.Name) and target.id == "candidate"
                    for target in node.targets):
                walk(node.value, "candidates[]", emitted)
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Subscript) \
                    and isinstance(node.targets[0].value, ast.Name) \
                    and node.targets[0].value.id == "candidate" \
                    and isinstance(node.targets[0].slice, ast.Constant):
                walk(node.value, f"candidates[].{node.targets[0].slice.value}", emitted)
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = {key.value for key in node.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)}
            if {"universe_summary", "market_context"} & keys:
                walk(node, "", emitted)
    return emitted


def _leaf_effect_map(contract: dict, paths: list[str],
                     producer_constant_null_leaves: tuple[str, ...] = ()) -> dict[str, str]:
    """Classify every analysis-input leaf without widening group-level proof."""
    overrides = contract.get("leaf_effect_overrides")
    if not isinstance(overrides, dict):
        raise ValueError("leaf_effect_overrides missing")
    baseline = contract.get("unclassified_pending_audit_baseline")
    if not isinstance(baseline, list) or any(not isinstance(item, str) for item in baseline):
        raise ValueError("unclassified_pending_audit_baseline missing")
    baseline_pending = set(baseline)
    path_set = set(paths)
    unknown = sorted(set(overrides) - path_set)
    if unknown:
        raise ValueError(f"leaf effect override outside analysis_input: {unknown[:4]}")
    derived_null = set(producer_constant_null_leaves)
    result: dict[str, str] = {}
    for group in contract["groups"]:
        group_paths = _paths_for_prefixes(paths, group.get("source_prefixes") or [])
        proven = set(group.get("proven_consumer_paths") or [])
        producer_constant_null = (group.get("producer_binding") or {}).get("status") == "constant_null"
        for path in group_paths:
            override = overrides.get(path)
            if isinstance(override, dict):
                category = override.get("category")
            else:
                category = override
            if category is None:
                # An explicit adjudication outranks the derived producer fact:
                # "Phase5 recomputes this" is a decision, "the producer emits
                # None" is only an observation about today's producer.
                if group["policy"] == "intentionally_independent":
                    nature = contract["leaf_nature_by_group"][group["id"]]
                    category = ("duplicate_or_display_audit"
                                if nature == "duplicate_source"
                                else "intentionally_independent_or_delete")
                elif producer_constant_null or path in derived_null:
                    category = "producer_constant_null"
                elif path in proven:
                    nature = contract["leaf_nature_by_group"][group["id"]]
                    category = ("formal_comparison_verdict"
                                if nature == "comparison_track" else "m67_main_decision")
                else:
                    # Unproven is not the same as adjudicated-dangling.  Claiming
                    # ``true_dangling`` requires an explicit, evidenced override so
                    # the published count can never pass an un-audited remainder
                    # off as a finished audit.
                    #
                    # This branch is frozen debt, not a default landing zone.  A
                    # leaf reaches it only when nothing mechanical classifies it,
                    # so a leaf arriving here that is not already on the baseline
                    # is exactly the one worth asking about: a new computed leaf,
                    # a producer that stopped emitting a literal ``None``, a
                    # renamed path, or a leaf that fell out of its group's proof.
                    if path not in baseline_pending:
                        raise ValueError(
                            "unclassified analysis_input leaf outside the frozen "
                            f"pending-audit baseline: {path}; register it in "
                            "leaf_effect_overrides with a category, or prove its "
                            "consumer -- the baseline may only shrink")
                    category = "unclassified_pending_audit"
            if category not in _LEAF_EFFECT_CATEGORIES:
                raise ValueError(f"unknown leaf effect category for {path}: {category!r}")
            if path in result:
                raise ValueError(f"leaf assigned multiple effect categories: {path}")
            result[path] = category
    if set(result) != path_set:
        missing = sorted(path_set - set(result))
        raise ValueError(f"leaf effect coverage mismatch: missing={missing[:4]}")
    return result


def leaf_effects(contract: dict | None = None, inventory: dict | None = None) -> dict[str, str]:
    contract = contract if contract is not None else load_contract()
    inventory = inventory if inventory is not None else static_inventory()
    return _leaf_effect_map(contract, inventory["analysis_input_paths"],
                            tuple(inventory["producer_constant_null_leaves"]))


def _default_trend_guard(current_count: int) -> dict:
    return {
        "status": "skipped_no_prior_ledger",
        "previous_as_of": None,
        "previous_unavailable_manual_review": None,
        "current_unavailable_manual_review": int(current_count),
        "reason": (
            "No prior published effect-contract ledger was supplied; this is an explicit bootstrap skip. "
            "The production weekly entrypoint must resolve the latest prior canonical weekly artifact before validation."
        ),
    }


def _validate_trend_guard_record(guard: dict, current_count: int,
                                 previous_ledger: dict | None) -> None:
    if not isinstance(guard, dict):
        raise ValueError("effect-contract trend guard missing")
    status = guard.get("status")
    if status not in {"checked", "skipped_no_prior_ledger"}:
        raise ValueError(f"effect-contract trend guard status invalid: {status!r}")
    if int(guard.get("current_unavailable_manual_review", -1)) != int(current_count):
        raise ValueError("effect-contract trend guard current count diverges")
    reason = str(guard.get("reason") or "").strip()
    if not reason:
        raise ValueError("effect-contract trend guard reason missing")
    if previous_ledger is None:
        if status != "skipped_no_prior_ledger":
            raise ValueError("effect-contract trend guard claims checked without a prior ledger")
        if guard.get("previous_as_of") is not None or guard.get("previous_unavailable_manual_review") is not None:
            raise ValueError("skipped trend guard must not carry prior-ledger facts")
        return
    if status != "checked":
        raise ValueError("effect-contract trend guard did not record the supplied prior ledger")
    previous_summary = (previous_ledger.get("summary") or {}) if isinstance(previous_ledger, dict) else {}
    previous_count = int(previous_summary.get("unavailable_manual_review", -1))
    if int(guard.get("previous_unavailable_manual_review", -1)) != previous_count:
        raise ValueError("effect-contract trend guard previous count diverges")
    previous_as_of = str(previous_ledger.get("as_of") or "") if isinstance(previous_ledger, dict) else ""
    if str(guard.get("previous_as_of") or "") != previous_as_of:
        raise ValueError("effect-contract trend guard previous as_of diverges")
    validate_unavailable_manual_review_trend(previous_ledger, {
        "summary": {"unavailable_manual_review": current_count},
    })


def validate_unavailable_manual_review_trend(previous_ledger: dict, current_ledger: dict) -> None:
    """Reject a weekly ledger whose unresolved count rises against a prior ledger."""
    previous = int(((previous_ledger or {}).get("summary") or {}).get("unavailable_manual_review", 0))
    current = int(((current_ledger or {}).get("summary") or {}).get("unavailable_manual_review", 0))
    if current > previous:
        raise ValueError(
            f"unavailable_manual_review trend regressed: previous={previous}, current={current}"
        )


@lru_cache(maxsize=64)
def _source_tree(source: str) -> ast.AST:
    """Parse source once per exact text; callers must treat the tree as read-only."""
    return ast.parse(source)


@lru_cache(maxsize=128)
def _governed_python_literal_names_for_source(source: str, rel: str) -> tuple[str, ...]:
    """Find business-threshold copies that would bypass the runtime JSON policy."""
    tree = _source_tree(source)
    policy_names = {
        "runners/a_short_phase5_engine.py": {
            "ATR_MULT", "RR_FLOOR", "BREAKOUT_RR_BONUS", "SINGLE_CAP_PCT", "IV_HALVE_PCT",
            "IV_NOBUILD_PCT", "IV_HV_RATIO_HI", "IV_HV_RATIO_LO", "OVERHEAT_5D",
            "OVERHEAT_20D", "MIN_AVG_AMOUNT_5D", "LOWXI_BAND", "SUPPORT_LOOKBACK",
            "RESISTANCE_LOOKBACK", "SR_SPIKE_ATR", "BREAKOUT_SOURCE_DISAGREEMENT_RATE_THRESHOLD_PCT",
            "MIN_SHARES", "MIN_AMOUNT", "IMPACT_COST_FRAC",
        },
        "runners/a_short_weekly_pipeline.py": {
            "MIN_PRICE_OBS", "EX_DIV_WINDOW_DAYS", "FORWARD_EVENT_WINDOW_DAYS",
            "DRAGON_LIST_LOOKBACK_TRADING_DAYS", "BLOCK_TRADE_LOOKBACK_TRADING_DAYS",
        },
        "engine/a_short_portfolio_risk.py": {
            "SAME_SW_L2_THRESHOLD_PCT", "MARGIN_THRESHOLD_PCT",
            "LARGE_INDEX_THRESHOLD_PCT", "SMALL_FLOAT_MV_THRESHOLD_PCT", "SMALL_FLOAT_MV_RMB",
            "HIGH_RISK_HOLDING_CAP_MULTIPLIER",
        },
    }
    offenders = []
    if rel == "A-EGS/egs_main.py":
        screening = {
            "min_avg_amount", "unlock_ratio", "top_n", "watch_n", "final_n", "suspend_lookback",
            "suspend_daily_min_coverage", "daily_stats_min_rows", "momentum_std_threshold",
            "max_concepts_per_stock", "overheat_5d", "overheat_20d", "esp_raw_cap",
        }
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not any(isinstance(t, ast.Name) and t.id == "CONF" for t in node.targets):
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            for key, value in zip(node.value.keys, node.value.values):
                if (isinstance(key, ast.Constant) and key.value in screening
                        and isinstance(value, ast.Constant) and isinstance(value.value, (int, float))):
                    offenders.append(str(key.value))
        return tuple(sorted(offenders))
    names = policy_names.get(rel, set())
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id in names for target in targets):
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)):
                offenders.extend(target.id for target in targets if isinstance(target, ast.Name) and target.id in names)
    return tuple(sorted(set(offenders)))


def _governed_python_literal_names(source: str, rel: str) -> list[str]:
    return list(_governed_python_literal_names_for_source(source, rel))


@lru_cache(maxsize=128)
def _runtime_portfolio_policy_literal_violations_for_sources(
        portfolio_source: str, weekly_source: str) -> tuple[str, ...]:
    """Reject literal copies in the two result-shaping portfolio consumers."""
    violations = []
    for label, pattern in (
            ("small_float_label", r"小流通市值\(<\d+(?:\.\d+)?亿元\)"),
            ("high_risk_cap_reduction_label", r"持仓单只上限临时下调\d+(?:\.\d+)?%")):
        if re.search(pattern, portfolio_source):
            violations.append(f"engine/a_short_portfolio_risk.py:{label}")

    tree = _source_tree(weekly_source)
    checks = (
        ("_holding_adds_portfolio_risk", "circ_mv_rmb", "small_float_mv_rmb"),
        ("_validate_portfolio_risk", "holding_single_position_cap_multiplier", "high_risk_holding_cap_multiplier"),
    )
    for function_name, field, policy_key in checks:
        function = _function_by_name(tree, function_name)
        if function is None:
            violations.append(f"runners/a_short_weekly_pipeline.py:{policy_key}_consumer_missing")
            continue
        for comparison in (node for node in ast.walk(function) if isinstance(node, ast.Compare)):
            operands = [comparison.left, *comparison.comparators]
            reads_field = any(
                isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                and node.slice.value == field
                for operand in operands for node in ast.walk(operand)
            )
            has_numeric_literal = any(
                isinstance(operand, ast.Constant) and isinstance(operand.value, (int, float))
                and not isinstance(operand.value, bool)
                for operand in operands
            )
            if reads_field and has_numeric_literal:
                violations.append(f"runners/a_short_weekly_pipeline.py:{policy_key}")
                break
    return tuple(sorted(violations))


def _runtime_portfolio_policy_literal_violations(portfolio_source: str, weekly_source: str) -> list[str]:
    return list(_runtime_portfolio_policy_literal_violations_for_sources(portfolio_source, weekly_source))


def _policy_leaf_paths(rel: str, payload: dict) -> list[str]:
    if rel.endswith("a_short_screening_threshold_governance_20260602.json"):
        values = payload.get("thresholds") if isinstance(payload, dict) else None
        return sorted(f"thresholds.{key}" for key in values) if isinstance(values, dict) else []
    if rel.endswith("egs_industry_heat_governance_20260611.json"):
        values = payload.get("industry_trend_classifier") if isinstance(payload, dict) else None
        return sorted(f"industry_trend_classifier.{key}" for key in values) if isinstance(values, dict) else []
    paths = []
    for section in ("phase5", "portfolio_risk", "weekly_windows"):
        values = payload.get(section) if isinstance(payload, dict) else None
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            if isinstance(value, dict):
                paths.extend(f"{section}.{key}.{nested}" for nested in value)
            else:
                paths.append(f"{section}.{key}")
    return sorted(paths)


def _schema_paths_from_raw(raw: str, label: str) -> list[str]:
    try:
        schema = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON schema invalid for effect contract: {label}") from exc
    if not isinstance(schema, dict):
        raise ValueError(f"JSON schema must be an object for effect contract: {label}")
    return _schema_leaf_paths(schema)


def _runtime_policy_inventory(overrides: dict[str, str] | None = None,
                              schema_overrides: dict[str, str] | None = None) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    overrides = overrides or {}
    schema_overrides = schema_overrides or {}
    paths, schema_paths = {}, {}
    for rel in _RUNTIME_POLICY_FILES:
        raw = overrides.get(rel, (ROOT / rel).read_text(encoding="utf-8"))
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"runtime policy JSON invalid for effect contract: {rel}") from exc
        paths[rel] = _policy_leaf_paths(rel, payload)
    for rel in _RUNTIME_POLICY_SCHEMA_FILES:
        schema_paths[rel] = _schema_paths_from_raw(
            schema_overrides.get(rel, (ROOT / rel).read_text(encoding="utf-8")), rel
        )
    return paths, schema_paths


def _legacy_migration_entries(raw: str) -> list[dict[str, str | None]]:
    try:
        registry = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("legacy effect-contract migration registry is unreadable") from exc
    migrations = registry.get("migrations") if isinstance(registry, dict) else None
    if not isinstance(migrations, list):
        raise ValueError("legacy effect-contract migration registry entries are malformed")
    keys = ("contract_fingerprint", "source_commit", "ledger_schema_version")
    entries = [{key: entry.get(key) if isinstance(entry, dict) else None for key in keys}
               for entry in migrations]
    return sorted(entries, key=lambda entry: tuple(str(entry[key]) for key in keys))


def _sorted_string_list(value):
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return value
    return sorted(value)


def _sorted_path_map(value):
    if not isinstance(value, dict):
        return value
    normalized = {}
    for key, paths in value.items():
        if (not isinstance(key, str) or not isinstance(paths, list)
                or not all(isinstance(path, str) for path in paths)):
            return value
        normalized[key] = sorted(paths)
    return {key: normalized[key] for key in sorted(normalized)}


def _sorted_migration_entries(value):
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        return value
    keys = ("contract_fingerprint", "source_commit", "ledger_schema_version")
    return sorted(value, key=lambda entry: tuple(str(entry.get(key)) for key in keys))


def _function_by_name(tree: ast.AST, name: str) -> ast.FunctionDef | None:
    return next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name), None)


def _subscript_matches(node: ast.AST, root: str, *, literal_key: str | None = None,
                       dynamic_key: str | None = None) -> bool:
    if not isinstance(node, ast.Subscript) or not isinstance(node.value, ast.Name) or node.value.id != root:
        return False
    slice_node = node.slice
    if literal_key is not None:
        return isinstance(slice_node, ast.Constant) and slice_node.value == literal_key
    return dynamic_key is not None and isinstance(slice_node, ast.Name) and slice_node.id == dynamic_key


def _loader_reads_key(tree: ast.AST, function_name: str, root: str, key: str, *, dynamic: bool = False) -> bool:
    function = _function_by_name(tree, function_name)
    if function is None:
        return False
    return any(_subscript_matches(node, root, literal_key=None if dynamic else key,
                                  dynamic_key="key" if dynamic else None)
               for node in ast.walk(function))


def _assignment_target_names(node: ast.AST) -> set[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
    return {target.id for target in targets if isinstance(target, ast.Name)}


def _top_level_value_loads(node: ast.AST) -> set[str]:
    value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
    return {item.id for item in ast.walk(value) if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)} if value else set()


def _policy_value_reaches_result(tree: ast.AST, policy_var: str, key: str) -> bool:
    """A top-level policy-derived value must reach a non-module function body.

    This blocks the deceptive shape ``UNUSED = _POLICY['new']``: loading a
    JSON value is not enough unless the derived value (possibly through a
    top-level helper tuple/dict) is actually consumed by result code.
    """
    assignments = [node for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))]
    reached = set()
    for node in assignments:
        if node.value is not None and any(
                _subscript_matches(part, policy_var, literal_key=key) for part in ast.walk(node.value)):
            reached.update(_assignment_target_names(node))
    if not reached:
        return False
    changed = True
    while changed:
        changed = False
        for node in assignments:
            targets = _assignment_target_names(node)
            if targets and not targets.issubset(reached) and _top_level_value_loads(node) & reached:
                before = len(reached)
                reached.update(targets)
                changed = changed or len(reached) != before
    function_loads = {
        item.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for item in ast.walk(node)
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
    }
    return bool(reached & function_loads)


def _function_conf_key_reaches_result(tree: ast.AST, key: str) -> bool:
    return any(_subscript_matches(item, "CONF", literal_key=key)
               for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               for item in ast.walk(node))


def _calls_name(tree: ast.AST, name: str) -> bool:
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
               for node in ast.walk(tree))


def _runtime_policy_leaf_readers(policy_paths: dict[str, list[str]], sources: dict[str, str]) -> dict[str, dict[str, list[str]]]:
    """Prove every active JSON leaf reaches one concrete runtime reader.

    A section-level prose reference is intentionally insufficient: a future
    field must be declared by the closed-world loader *and* be read by the
    relevant result-shaping module.  The resulting per-leaf map is hashed in
    the contract, so a new field cannot be waved through by editing a generic
    ``consumer_refs`` string.
    """
    loader = sources[_RUNTIME_CONFIG_FILE]
    egs = sources["A-EGS/egs_main.py"]
    phase5 = sources["runners/a_short_phase5_engine.py"]
    portfolio = sources["engine/a_short_portfolio_risk.py"]
    weekly = sources["runners/a_short_weekly_pipeline.py"]
    render = sources["runners/a_short_m67_render.py"]
    industry_theme = sources["engine/a_short_industry_theme.py"]
    trees = {rel: _source_tree(source) for rel, source in {
        _RUNTIME_CONFIG_FILE: loader,
        "A-EGS/egs_main.py": egs,
        "engine/a_short_industry_theme.py": industry_theme,
        "runners/a_short_phase5_engine.py": phase5,
        "engine/a_short_portfolio_risk.py": portfolio,
        "runners/a_short_weekly_pipeline.py": weekly,
        "runners/a_short_m67_render.py": render,
    }.items()}
    declared = {
        "screening": set(_literal_string_assignment(loader, "_SCREENING_KEYS")),
        "phase5": set(_literal_string_assignment(loader, "_PHASE5_KEYS")),
        "portfolio_risk": set(_literal_string_assignment(loader, "_PORTFOLIO_KEYS")),
        "weekly_windows": set(_literal_string_assignment(loader, "_WEEKLY_WINDOW_KEYS")),
    }
    result: dict[str, dict[str, list[str]]] = {}
    for rel, paths in policy_paths.items():
        by_path: dict[str, list[str]] = {}
        for path in paths:
            parts = path.split(".")
            refs: list[str] = []
            if rel.endswith("egs_industry_heat_governance_20260611.json"):
                key = parts[1] if len(parts) == 2 else ""
                classifier_reads = (
                    _loader_reads_key(trees["engine/a_short_industry_theme.py"], "industry_trend_from_score", "policy", key)
                    if key in {"headwind_max", "tailwind_min"}
                    else _loader_reads_key(trees["engine/a_short_industry_theme.py"], "classify_industry_trend", "policy", key)
                )
                if key == "semantic_boundary":
                    refs = ["intentionally_independent: classifier explanation only"]
                elif (classifier_reads
                      and _calls_name(trees["A-EGS/egs_main.py"], "classify_industry_trend")
                      and _calls_name(trees["runners/a_short_weekly_pipeline.py"], "industry_trend_policy")):
                    refs = [
                        f'engine/a_short_industry_theme.py::industry_trend_classifier["{key}"]',
                        "A-EGS/egs_main.py::classify_industry_trend",
                        "runners/a_short_weekly_pipeline.py::_industry_trend_for_candidate",
                    ]
            elif rel.endswith("a_short_screening_threshold_governance_20260602.json"):
                key = parts[1] if len(parts) == 2 else ""
                if (key in declared["screening"]
                        and _loader_reads_key(trees[_RUNTIME_CONFIG_FILE], "_validate_screening", "raw", key)
                        and _function_conf_key_reaches_result(trees["A-EGS/egs_main.py"], key)):
                    refs = [
                        f'{_RUNTIME_CONFIG_FILE}::_validate_screening.raw["{key}"]',
                        f'A-EGS/egs_main.py::CONF["{key}"]',
                    ]
            elif len(parts) >= 2:
                section, key = parts[0], parts[1]
                if section == "phase5":
                    phase5_reader = _policy_value_reaches_result(
                        trees["runners/a_short_phase5_engine.py"], "_PHASE5_POLICY", key)
                    weekly_reader = _policy_value_reaches_result(
                        trees["runners/a_short_weekly_pipeline.py"], "_PHASE5_POLICY", key)
                    render_reader = _policy_value_reaches_result(
                        trees["runners/a_short_m67_render.py"], "_PHASE5_POLICY", key)
                    if (key in declared["phase5"]
                            and _loader_reads_key(trees[_RUNTIME_CONFIG_FILE], "_validate_m67", "phase", key)
                            and (phase5_reader or weekly_reader or render_reader)):
                        refs = [
                            f'{_RUNTIME_CONFIG_FILE}::_validate_m67.phase["{key}"]',
                        ]
                        if phase5_reader:
                            refs.append(f'runners/a_short_phase5_engine.py::_PHASE5_POLICY["{key}"]')
                        if weekly_reader:
                            refs.append(f'runners/a_short_weekly_pipeline.py::_PHASE5_POLICY["{key}"]')
                        if render_reader:
                            refs.append(f'runners/a_short_m67_render.py::_PHASE5_POLICY["{key}"]')
                elif section == "portfolio_risk":
                    portfolio_reader = _policy_value_reaches_result(
                        trees["engine/a_short_portfolio_risk.py"], "_PORTFOLIO_POLICY", key)
                    weekly_reader = _policy_value_reaches_result(
                        trees["runners/a_short_weekly_pipeline.py"], "_PORTFOLIO_RISK_POLICY", key)
                    weekly_consumer_keys = {
                        "small_float_mv_rmb", "high_risk_holding_cap_multiplier",
                    }
                    if (key in declared["portfolio_risk"]
                            and _loader_reads_key(trees[_RUNTIME_CONFIG_FILE], "_validate_m67", "portfolio", key, dynamic=True)
                            and portfolio_reader
                            and (key not in weekly_consumer_keys or weekly_reader)):
                        refs = [
                            f'{_RUNTIME_CONFIG_FILE}::_PORTFOLIO_KEYS/{key}->portfolio[key]',
                            f'engine/a_short_portfolio_risk.py::_PORTFOLIO_POLICY["{key}"]',
                        ]
                        if key in weekly_consumer_keys:
                            refs.append(f'runners/a_short_weekly_pipeline.py::_PORTFOLIO_RISK_POLICY["{key}"]')
                elif section == "weekly_windows":
                    if (key in declared["weekly_windows"]
                            and _loader_reads_key(trees[_RUNTIME_CONFIG_FILE], "_validate_m67", "windows", key, dynamic=True)
                            and _policy_value_reaches_result(trees["runners/a_short_weekly_pipeline.py"], "_WEEKLY_WINDOWS", key)):
                        refs = [
                            f'{_RUNTIME_CONFIG_FILE}::_WEEKLY_WINDOW_KEYS/{key}->windows[key]',
                            f'runners/a_short_weekly_pipeline.py::_WEEKLY_WINDOWS["{key}"]',
                        ]
            by_path[path] = refs
        result[rel] = by_path
    return result


@lru_cache(maxsize=128)
def _string_assignment_items(source: str) -> tuple[tuple[str, str], ...]:
    tree = _source_tree(source)
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        if isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            out[node.targets[0].id] = node.value.value
    return tuple(sorted(out.items()))


def _string_assignments(source: str) -> dict[str, str]:
    return dict(_string_assignment_items(source))


@lru_cache(maxsize=128)
def _operation_impact_sources_for_source(source: str) -> tuple[str, ...]:
    tree = _source_tree(source)
    strings = _string_assignments(source)
    sources = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or key.value != "source_field":
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                sources.add(value.value)
            elif isinstance(value, ast.Name) and value.id in strings:
                sources.add(strings[value.id])
    return tuple(sorted(sources))


def _operation_impact_sources(source: str) -> list[str]:
    return list(_operation_impact_sources_for_source(source))


@lru_cache(maxsize=128)
def _literal_string_assignment_values(source: str, name: str) -> tuple[str, ...]:
    tree = _source_tree(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        if not isinstance(node.targets[0], ast.Name) or node.targets[0].id != name:
            continue
        values = node.value.args[0] if isinstance(node.value, ast.Call) and node.value.args else node.value
        if isinstance(values, (ast.Tuple, ast.List, ast.Set)):
            return tuple(sorted(item.value for item in values.elts
                                if isinstance(item, ast.Constant) and isinstance(item.value, str)))
    return ()


def _literal_string_assignment(source: str, name: str) -> list[str]:
    return list(_literal_string_assignment_values(source, name))


def _llm_task_types(analysis_schema: dict) -> list[str]:
    """Return the closed enum of configured legacy LLM tasks from the input contract."""
    try:
        values = analysis_schema["$defs"]["llmTask"]["properties"]["prompt"]["enum"]
    except (KeyError, TypeError):
        return []
    return sorted(value for value in values if isinstance(value, str))


def _build_static_inventory(*, source_overrides: dict[str, str] | None = None,
                            analysis_schema: dict | None = None,
                            output_schema_overrides: dict[str, str] | None = None,
                            runtime_policy_overrides: dict[str, str] | None = None,
                            runtime_policy_schema_overrides: dict[str, str] | None = None) -> dict:
    source_overrides = source_overrides or {}
    output_schema_overrides = output_schema_overrides or {}
    analysis_schema = analysis_schema if analysis_schema is not None else json.loads(
        (ROOT / "schemas" / "analysis_input.schema.json").read_text(encoding="utf-8")
    )
    sources = {rel: source_overrides.get(rel, (ROOT / rel).read_text(encoding="utf-8"))
               for rel in _STATIC_SOURCE_FILES}
    phase5 = sources["runners/a_short_phase5_engine.py"]
    portfolio = sources["engine/a_short_portfolio_risk.py"]
    weekly = sources["runners/a_short_weekly_pipeline.py"]
    portfolio_tree = _source_tree(portfolio)
    factor_node = next(
        node for node in portfolio_tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "_FACTOR_SPECS")
    factor_specs = factor_node.value.elts if isinstance(factor_node.value, (ast.Tuple, ast.List)) else []
    analysis_paths = analysis_input_paths(analysis_schema)
    policy_paths, policy_schema_paths = _runtime_policy_inventory(
        runtime_policy_overrides, runtime_policy_schema_overrides)
    return {
        "analysis_input_paths": analysis_paths,
        "producer_constant_null_leaves": sorted(
            path for path, kind in _producer_literal_leaves(sources["A-EGS/egs_main.py"]).items()
            if kind == "constant_null" and path in set(analysis_paths)
        ),
        "governed_python_literal_names": {
            rel: _governed_python_literal_names(sources[rel], rel) for rel in _GOVERNED_LITERAL_FILES
        } | {"A-EGS/egs_main.py": _governed_python_literal_names(sources["A-EGS/egs_main.py"], "A-EGS/egs_main.py")},
        "runtime_portfolio_policy_literal_violations": _runtime_portfolio_policy_literal_violations(portfolio, weekly),
        "runtime_policy_paths": policy_paths,
        "runtime_policy_schema_paths": policy_schema_paths,
        "runtime_policy_leaf_readers": _runtime_policy_leaf_readers(policy_paths, sources),
        "operation_impact_sources": _operation_impact_sources(phase5) + _operation_impact_sources(weekly),
        "llm_task_types": _llm_task_types(analysis_schema),
        "portfolio_factor_fields": [row.elts[0].value for row in factor_specs
                                    if isinstance(row, (ast.Tuple, ast.List)) and row.elts
                                    and isinstance(row.elts[0], ast.Constant)
                                    and isinstance(row.elts[0].value, str)],
        "output_schema_paths": {
            rel: _schema_paths_from_raw(
                output_schema_overrides.get(rel, (ROOT / rel).read_text(encoding="utf-8")), rel
            ) for rel in _OUTPUT_SCHEMA_FILES
        },
        "legacy_migration_entries": _legacy_migration_entries(sources[_LEGACY_MIGRATION_FILE]),
    }


def _read_default_static_snapshot() -> tuple[tuple[str, str], ...]:
    """Read every default static-contract input; content is the cache key."""
    return tuple((rel, (ROOT / rel).read_text(encoding="utf-8"))
                 for rel in _DEFAULT_STATIC_SNAPSHOT_FILES)


@lru_cache(maxsize=4)
def _default_static_inventory_from_snapshot(snapshot: tuple[tuple[str, str], ...]) -> dict:
    raw = dict(snapshot)
    return _build_static_inventory(
        source_overrides={rel: raw[rel] for rel in _STATIC_SOURCE_FILES},
        analysis_schema=json.loads(raw[_ANALYSIS_INPUT_SCHEMA_FILE]),
        output_schema_overrides={rel: raw[rel] for rel in _OUTPUT_SCHEMA_FILES},
        runtime_policy_overrides={rel: raw[rel] for rel in _RUNTIME_POLICY_FILES},
        runtime_policy_schema_overrides={rel: raw[rel] for rel in _RUNTIME_POLICY_SCHEMA_FILES},
    )


def static_inventory(*, source_overrides: dict[str, str] | None = None,
                     analysis_schema: dict | None = None,
                     output_schema_overrides: dict[str, str] | None = None,
                     runtime_policy_overrides: dict[str, str] | None = None,
                     runtime_policy_schema_overrides: dict[str, str] | None = None) -> dict:
    """Return the static inventory, memoized only for unmodified on-disk inputs."""
    if (source_overrides is None and analysis_schema is None
            and output_schema_overrides is None and runtime_policy_overrides is None
            and runtime_policy_schema_overrides is None):
        # A fresh copy prevents a caller from poisoning the cached contract view.
        return copy.deepcopy(_default_static_inventory_from_snapshot(_read_default_static_snapshot()))
    return _build_static_inventory(
        source_overrides=source_overrides,
        analysis_schema=analysis_schema,
        output_schema_overrides=output_schema_overrides,
        runtime_policy_overrides=runtime_policy_overrides,
        runtime_policy_schema_overrides=runtime_policy_schema_overrides,
    )


@lru_cache(maxsize=4)
def _contract_from_source(raw: str) -> dict:
    return json.loads(raw)


def load_contract() -> dict:
    # Re-read the bytes for every call so an in-process source change invalidates
    # the memo; return a copy so callers cannot mutate cached contract state.
    return copy.deepcopy(_contract_from_source(CONTRACT_PATH.read_text(encoding="utf-8")))


def contract_fingerprint(contract: dict | None = None) -> str:
    return _hash(contract if contract is not None else load_contract())


def load_legacy_effect_contract(contract_fp: str) -> dict | None:
    """Return a registered historical contract snapshot, or ``None``.

    This is an explicit compatibility registry for already-published ledgers.
    It never treats an unknown fingerprint as compatible and never substitutes
    the current contract for a historical one.
    """
    if not isinstance(contract_fp, str) or not re.fullmatch(r"[0-9a-f]{64}", contract_fp):
        return None
    try:
        registry_text = LEGACY_MIGRATION_PATH.read_text(encoding="utf-8")
        registry = json.loads(registry_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("legacy effect-contract migration registry is unreadable") from exc
    if load_contract().get("legacy_migration_entries") != _legacy_migration_entries(registry_text):
        raise ValueError("legacy effect-contract migration registry entries are not bound to current contract")
    if (registry.get("schema_name") != "a_short_m67_effect_contract_legacy_migrations"
            or registry.get("schema_version") != "1.0.0"):
        raise ValueError("legacy effect-contract migration registry schema is invalid")
    migrations = registry.get("migrations")
    if not isinstance(migrations, list) or not migrations:
        raise ValueError("legacy effect-contract migration registry is empty")
    seen = set()
    match = None
    for entry in migrations:
        if not isinstance(entry, dict):
            raise ValueError("legacy effect-contract migration entry is not an object")
        fp = entry.get("contract_fingerprint")
        source_commit = entry.get("source_commit")
        if (not isinstance(fp, str) or not re.fullmatch(r"[0-9a-f]{64}", fp)
                or fp in seen
                or not isinstance(source_commit, str)
                or not re.fullmatch(r"[0-9a-f]{40}", source_commit)
                or entry.get("ledger_schema_version") != "1.0.0"):
            raise ValueError("legacy effect-contract migration entry identity is invalid")
        seen.add(fp)
        snapshot = entry.get("contract")
        if not isinstance(snapshot, dict) or contract_fingerprint(snapshot) != fp:
            raise ValueError("legacy effect-contract migration snapshot fingerprint mismatch")
        try:
            commit_check = subprocess.run(
                ["git", "-C", str(ROOT), "cat-file", "-e", f"{source_commit}^{{commit}}"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            historical = subprocess.run(
                ["git", "-C", str(ROOT), "show", f"{source_commit}:{_CONTRACT_RELATIVE_PATH}"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            if commit_check.returncode != 0 or historical.returncode != 0:
                raise ValueError("legacy effect-contract source commit/path is unavailable")
            historical_contract = json.loads(historical.stdout.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("legacy effect-contract source commit snapshot is unreadable") from exc
        if (not isinstance(historical_contract, dict)
                or contract_fingerprint(historical_contract) != fp
                or historical_contract != snapshot):
            raise ValueError("legacy effect-contract registry snapshot is not the recorded git snapshot")
        if fp == contract_fp:
            match = snapshot
    return copy.deepcopy(match) if match is not None else None


def static_contract_error(contract: dict | None = None, *, inventory: dict | None = None) -> str | None:
    contract = contract if contract is not None else load_contract()
    inventory = inventory if inventory is not None else static_inventory()
    if contract.get("schema_name") != "a_short_m67_effect_contract" or contract.get("schema_version") != "1.0.0":
        return "effect contract schema_name/schema_version invalid"
    groups = contract.get("groups")
    if not isinstance(groups, list) or not groups:
        return "effect contract groups missing"
    paths = inventory["analysis_input_paths"]
    group_ids = set()
    coverage = {path: 0 for path in paths}
    for group in groups:
        if not isinstance(group, dict) or not str(group.get("id") or "") or group["id"] in group_ids:
            return "effect contract group id missing or duplicate"
        group_ids.add(group["id"])
        prefixes = group.get("source_prefixes")
        if not isinstance(prefixes, list) or not prefixes:
            return f"effect contract {group['id']} source_prefixes missing"
        group_paths = _paths_for_prefixes(paths, prefixes)
        if not group_paths:
            return f"effect contract {group['id']} covers no analysis_input paths"
        if group.get("source_paths_sha256") != _hash(group_paths):
            return f"effect contract {group['id']} analysis_input paths changed without contract update"
        for path in group_paths:
            coverage[path] += 1
        policy = group.get("policy")
        if policy not in _POLICIES:
            return f"effect contract {group['id']} policy invalid"
        if not isinstance(group.get("terminal_surfaces"), list) or not group["terminal_surfaces"]:
            return f"effect contract {group['id']} terminal_surfaces missing"
        handler = str(group.get("runtime_handler") or "")
        if not handler:
            return f"effect contract {group['id']} runtime_handler missing"
        if handler == "upstream_candidate_set":
            return (f"effect contract {group['id']} may not treat report presence as a field consumer; "
                    "use a proven handler or unresolved_input_group")
        if handler == "unresolved_input_group" and not str(group.get("unresolved_reason") or "").strip():
            return f"effect contract {group['id']} unresolved input group lacks reason"
        if handler in {"lineage_gate", "phase5_decision", "phase5_risk", "market_regime", "account_cash", "portfolio_risk", "llm_tasks", "data_quality_shadow", "comparison_track", "m4_review_gate", "technical_volatility_comparison"}:
            proof_paths = group.get("proven_consumer_paths")
            if not isinstance(proof_paths, list) or sorted(proof_paths) != group_paths:
                return (f"effect contract {group['id']} direct runtime handler lacks all-leaf "
                        "consumer proof; split unresolved leaves or register every leaf")
            if not str(group.get("consumer_proof_ref") or "").strip():
                return f"effect contract {group['id']} direct runtime handler lacks consumer_proof_ref"
        if group.get("id") == "candidate_derived_flags_m4_review":
            expected_binding = {
                "status": "constant_null",
                "source_ref": "A-EGS/egs_main.py::m4_review_required",
                "activation": "not_triggered_until_separately_reviewed_m4_producer",
            }
            if group.get("producer_binding") != expected_binding:
                return ("effect contract candidate_derived_flags_m4_review producer binding "
                        "must disclose the current constant-null producer and deferred activation")
        if group.get("id") == "candidate_volatility":
            expected_binding = {
                "status": "constant_null",
                "source_ref": "A-EGS/egs_main.py::_candidate_from_row.volatility",
                "activation": "display_audit_only_until_separately_reviewed_volatility_producer",
            }
            if group.get("producer_binding") != expected_binding:
                return ("effect contract candidate_volatility producer binding must disclose the "
                        "current constant-null producer and deferred activation")
        if policy == "intentionally_independent":
            exception = group.get("intentional_independence")
            if not isinstance(exception, dict) or not all(str(exception.get(key) or "").strip()
                                                         for key in ("reason", "owner", "review_ref")):
                return f"effect contract {group['id']} independent exception lacks reason/owner/review_ref"
    try:
        nature_by_path = _leaf_nature_map(contract, paths)
    except (TypeError, ValueError, KeyError) as exc:
        return f"effect contract nature classification invalid: {exc}"
    baseline = contract.get("unclassified_pending_audit_baseline")
    if not isinstance(baseline, list) or any(not isinstance(item, str) for item in baseline):
        return "effect contract unclassified_pending_audit_baseline missing or malformed"
    if baseline != sorted(set(baseline)):
        return "effect contract unclassified_pending_audit_baseline must be sorted and duplicate-free"
    try:
        effect_by_path = _leaf_effect_map(
            contract, paths, tuple(inventory["producer_constant_null_leaves"]))
    except (TypeError, ValueError, KeyError) as exc:
        return f"effect contract leaf effect classification invalid: {exc}"
    # Ratchet: the baseline is a debt list, so every entry must still be a real
    # debt.  A leaf that has since been wired, deleted, renamed, or turned
    # constant-null must leave the list; nothing may be parked there.
    stale_baseline = sorted(path for path in baseline
                            if effect_by_path.get(path) != "unclassified_pending_audit")
    if stale_baseline:
        return ("effect contract unclassified_pending_audit_baseline still lists "
                f"{len(stale_baseline)} leaf/leaves that no longer classify as pending "
                f"(e.g. {stale_baseline[0]}); remove them -- the list may only shrink")
    # The other direction.  `_leaf_effect_map`'s gate only guards the fallback
    # branch, and an explicit override outranks it: writing
    # ``{"category": "unclassified_pending_audit"}`` for an unlisted leaf books
    # new debt without ever touching the baseline.  Closing only the fallback
    # would leave that door open in the self-contained validator and rely on a
    # test to notice.
    unlisted_pending = sorted(path for path, category in effect_by_path.items()
                              if category == "unclassified_pending_audit"
                              and path not in set(baseline))
    if unlisted_pending:
        return ("effect contract declares "
                f"{len(unlisted_pending)} leaf/leaves unclassified that the frozen baseline "
                f"does not list (e.g. {unlisted_pending[0]}); adjudicate them with a real "
                "category -- new debt may not be added to the baseline")
    _LIVE_EFFECTS = {"m67_main_decision", "formal_comparison_verdict",
                     "upstream_candidate_set_or_rank"}
    for group in groups:
        group_paths = _paths_for_prefixes(paths, group["source_prefixes"])
        if contract["leaf_nature_by_group"][group["id"]] != "true_dangling":
            continue
        live = sorted(p for p in group_paths if effect_by_path[p] in _LIVE_EFFECTS)
        if live:
            return (f"effect contract {group['id']} is labelled true_dangling but "
                    f"{len(live)} of its leaves already reach a live terminal "
                    f"(e.g. {live[0]}); use partial_consumption")
    for path, override in (contract.get("leaf_effect_overrides") or {}).items():
        category = effect_by_path[path]
        if category not in {"m67_main_decision", "formal_comparison_verdict",
                            "upstream_candidate_set_or_rank"}:
            continue
        # A bare-string override names a category and carries no evidence, so
        # skipping it here would let a live claim in through the one form that
        # cannot hold the proof.  Only a non-live category may stay bare.
        if not isinstance(override, dict):
            return (f"effect contract leaf {path} claims a live effect as a bare string; "
                    "a live claim must carry consumer_ref / terminal_surface / mutation_evidence")
        if not all(str(override.get(key) or "").strip()
                   for key in ("consumer_ref", "terminal_surface", "mutation_evidence")):
            return f"effect contract leaf {path} effect proof incomplete"
    for group in groups:
        nature = contract["leaf_nature_by_group"][group["id"]]
        policy = group["policy"]
        if nature in {"display_audit", "duplicate_source", "delete"} and policy != "intentionally_independent":
            return f"effect contract {group['id']} nature={nature} requires intentionally_independent policy"
        if nature in {"true_dangling", "partial_consumption", "main_decision", "comparison_track"} \
                and policy != "must_affect_result":
            return f"effect contract {group['id']} nature={nature} requires must_affect_result policy"
        allowed_handlers = _NATURE_RUNTIME_HANDLERS[nature]
        if group.get("runtime_handler") not in allowed_handlers:
            return (f"effect contract {group['id']} nature={nature} requires runtime_handler in "
                    f"{sorted(allowed_handlers)!r}; got {group.get('runtime_handler')!r}")
        if nature == "comparison_track":
            comparison_paths = _paths_for_prefixes(paths, group["source_prefixes"])
            binding = group.get("comparison_verdict_binding")
            if not isinstance(binding, dict):
                return f"effect contract {group['id']} comparison verdict binding missing"
            if "::" not in str(binding.get("runtime_ref") or ""):
                return f"effect contract {group['id']} comparison verdict runtime_ref missing"
            verdict_field = str(binding.get("verdict_field") or "")
            if not verdict_field or verdict_field.lower() in {"input_sha256", "comparison_digest", "hash", "digest"}:
                return f"effect contract {group['id']} comparison verdict may not be digest-only"
            proof = binding.get("variation_proof")
            if not isinstance(proof, dict):
                return f"effect contract {group['id']} comparison verdict variation proof missing"
            if proof.get("mutated_leaf") not in comparison_paths:
                return f"effect contract {group['id']} comparison verdict mutation leaf is outside group"
            if (not str(proof.get("baseline_outcome") or "").strip()
                    or not str(proof.get("variant_outcome") or "").strip()
                    or proof["baseline_outcome"] == proof["variant_outcome"]):
                return f"effect contract {group['id']} comparison verdict variation proof must change outcome"
    tracks = contract.get("comparison_tracks")
    if not isinstance(tracks, list) or not tracks:
        return "effect contract comparison_tracks missing"
    for track in tracks:
        if not isinstance(track, dict) or not str(track.get("id") or "").strip():
            return "effect contract comparison track id missing"
        if track.get("policy") != "intentionally_independent":
            return f"comparison track {track.get('id')} policy invalid"
        if not all(str(track.get(key) or "").strip() for key in ("reason", "owner", "review_ref", "schema_path", "schema_sha256")):
            return f"comparison track {track.get('id')} traceability incomplete"
        path = ROOT / str(track["schema_path"])
        if not path.is_file() or track["schema_sha256"] != _hash(path.read_text(encoding="utf-8")):
            return f"comparison track {track.get('id')} schema changed without effect-contract update"
    uncovered = sorted(path for path, count in coverage.items() if count == 0)
    duplicate = sorted(path for path, count in coverage.items() if count > 1)
    if uncovered or duplicate:
        return f"effect contract analysis_input coverage invalid: uncovered={uncovered[:4]}, duplicate={duplicate[:4]}"
    if _sorted_string_list(contract.get("analysis_input_paths")) != paths:
        return "analysis_input schema changed without effect contract update"
    if inventory["runtime_portfolio_policy_literal_violations"]:
        return ("runtime portfolio policy literal returned to result consumers: "
                f"{inventory['runtime_portfolio_policy_literal_violations']}")
    bindings = contract.get("runtime_policy_bindings")
    if not isinstance(bindings, list) or not bindings:
        return "effect contract runtime_policy_bindings missing"
    policy_coverage = {(rel, path): 0 for rel, values in inventory["runtime_policy_paths"].items() for path in values}
    binding_ids = set()
    for binding in bindings:
        if not isinstance(binding, dict) or not str(binding.get("id") or "") or binding["id"] in binding_ids:
            return "effect contract runtime policy binding id missing or duplicate"
        binding_ids.add(binding["id"])
        rel = binding.get("policy_path")
        prefixes = binding.get("source_prefixes")
        if rel not in inventory["runtime_policy_paths"] or not isinstance(prefixes, list) or not prefixes:
            return f"effect contract runtime policy binding {binding['id']} route/prefix invalid"
        matched = _paths_for_prefixes(inventory["runtime_policy_paths"][rel], prefixes)
        if not matched:
            return f"effect contract runtime policy binding {binding['id']} covers no policy fields"
        if binding.get("source_paths_sha256") != _hash(matched):
            return f"effect contract runtime policy binding {binding['id']} fields changed without registration"
        policy = binding.get("policy")
        if policy not in {"must_affect_result", "intentionally_independent"}:
            return f"effect contract runtime policy binding {binding['id']} policy invalid"
        if not isinstance(binding.get("terminal_surfaces"), list) or not binding["terminal_surfaces"]:
            return f"effect contract runtime policy binding {binding['id']} terminal surface missing"
        if policy == "must_affect_result" and (not isinstance(binding.get("consumer_refs"), list) or not binding["consumer_refs"]):
            return f"effect contract runtime policy binding {binding['id']} consumer proof missing"
        if policy == "intentionally_independent":
            exception = binding.get("intentional_independence")
            if not isinstance(exception, dict) or not all(str(exception.get(key) or "").strip()
                                                         for key in ("reason", "owner", "review_ref")):
                return f"effect contract runtime policy binding {binding['id']} independent exception incomplete"
        leaf_readers = inventory["runtime_policy_leaf_readers"].get(rel, {})
        if policy == "must_affect_result":
            actual_readers = [reader for path in matched for reader in leaf_readers.get(path, [])]
            for consumer_ref in binding["consumer_refs"]:
                if (not isinstance(consumer_ref, str) or "::" not in consumer_ref
                        or not any(reader.startswith(consumer_ref) for reader in actual_readers)):
                    return (f"effect contract runtime policy binding {binding['id']} "
                            f"consumer_ref is not an actual reader: {consumer_ref!r}")
        for path in matched:
            policy_coverage[(rel, path)] += 1
            if policy == "must_affect_result" and not leaf_readers.get(path):
                return (f"effect contract runtime policy leaf has no actual result reader: "
                        f"{rel}:{path}")
    policy_uncovered = sorted(f"{rel}:{path}" for (rel, path), count in policy_coverage.items() if count == 0)
    policy_duplicate = sorted(f"{rel}:{path}" for (rel, path), count in policy_coverage.items() if count > 1)
    if policy_uncovered or policy_duplicate:
        return f"effect contract runtime policy coverage invalid: uncovered={policy_uncovered[:4]}, duplicate={policy_duplicate[:4]}"
    if _sorted_path_map(contract.get("runtime_policy_paths")) != _sorted_path_map(inventory["runtime_policy_paths"]):
        return "runtime policy field inventory body changed without effect contract update"
    if (_sorted_path_map(contract.get("runtime_policy_schema_paths"))
            != _sorted_path_map(inventory["runtime_policy_schema_paths"])):
        return "runtime policy schema changed without effect contract update"
    if contract.get("runtime_policy_leaf_readers") != inventory["runtime_policy_leaf_readers"]:
        return "runtime policy per-leaf reader mapping body changed without effect contract update"
    literals = {rel: values for rel, values in inventory["governed_python_literal_names"].items() if values}
    if literals:
        return f"governed business threshold literal returned to Python: {literals}"
    if sorted(contract.get("operation_impact_sources") or []) != sorted(inventory["operation_impact_sources"]):
        return "operation_impact source_field changed without effect contract update"
    if sorted(contract.get("llm_task_types") or []) != inventory["llm_task_types"]:
        return "LLM task type changed without effect contract update"
    if sorted(contract.get("portfolio_factor_fields") or []) != sorted(inventory["portfolio_factor_fields"]):
        return "portfolio factor field changed without effect contract update"
    if _sorted_path_map(contract.get("output_schema_paths")) != _sorted_path_map(inventory["output_schema_paths"]):
        return "weekly/M6.7 output schema changed without effect contract update"
    if (_sorted_migration_entries(contract.get("legacy_migration_entries"))
            != _sorted_migration_entries(inventory["legacy_migration_entries"])):
        return "legacy effect-contract migration registry changed without effect-contract update"
    return None


def validate_static_contract(contract: dict | None = None) -> None:
    error = static_contract_error(contract)
    if error:
        raise ValueError(error)


def _phase5_status(weekly: dict, *, risk_only: bool = False, market_only: bool = False) -> tuple[str, str]:
    reports = weekly.get("reports") or []
    if not reports:
        return "not_triggered", "本周没有候选/持仓行"
    families = []
    for report in reports:
        fam = ((report.get("machine") or {}).get("risk_families") or {})
        if market_only:
            families.append(fam.get("market_regime") or {})
        else:
            families.extend(value for value in fam.values() if isinstance(value, dict))
    if risk_only and not any(item.get("hit") or item.get("action") != "none" for item in families):
        return "not_triggered", "本周没有命中该组风险条件"
    return "applied", "已写入逐票 M6.7 操作/星级/价格或风险说明"


def _m4_review_status(weekly: dict) -> tuple[str, str]:
    """Report the M4 gate honestly while its upstream producer is still null-only."""
    reports = weekly.get("reports") or []
    if not reports:
        return "not_triggered", "M4 producer is constant-null; this week has no candidate/holding report"
    saw_true = False
    for report in reports:
        node = ((report.get("machine") or {}).get("m4_review_gate"))
        if not isinstance(node, dict):
            return "unavailable_manual_review", "m4_review_gate observation is missing"
        if (node.get("input_leaf") != "candidates[].derived_flags.m4_review_required"
                or node.get("producer_status") != "constant_null"
                or node.get("producer_ref") != "A-EGS/egs_main.py::m4_review_required"):
            return "unavailable_manual_review", "m4_review_gate producer binding diverges"
        state = node.get("observed_state")
        if state == "true":
            saw_true = True
        elif state == "malformed_non_null":
            return "unavailable_manual_review", "m4_review_required malformed non-null value was observed"
        elif state != "inactive":
            return "unavailable_manual_review", "m4_review_gate observed state is invalid"
    if saw_true:
        return "applied", "m4_review_required=true reached the Phase5 new-entry gate"
    return "not_triggered", "M4 producer is constant-null; no non-null review flag was observed"


def _portfolio_status(weekly: dict) -> tuple[str, str]:
    risk = weekly.get("portfolio_risk") or {}
    summary = risk.get("summary") or {}
    if risk.get("status") == "manual_review_required":
        return "unavailable_manual_review", "组合事实缺失或无效，已显式人工复核"
    results = risk.get("stock_results") or []
    if any(row.get("action") in {"replace", "observe_required", "blocked_add"} for row in results if isinstance(row, dict)):
        return "applied", "已联动到观察/禁止加仓/人工复核"
    if summary.get("status") == "not_applicable":
        return "not_triggered", "持仓数量不足，规则本周不适用"
    return "not_triggered", "组合集中度和因子均未触发限制"


def _llm_status(weekly: dict) -> tuple[str, str]:
    from engine.a_short_legacy_llm_tasks import TASK_TYPES

    reports = weekly.get("reports") or []
    if not reports:
        return "not_triggered", "本周没有候选/持仓报告，无需生成 legacy task 结果"
    expected = set(TASK_TYPES)
    for report in reports:
        results = (((report.get("machine") or {}).get("layer") or {}).get("llm_task_results"))
        if not isinstance(results, list) or len(results) != len(expected):
            return "unavailable_manual_review", "legacy task 结果缺失或数量不完整"
        types = [row.get("task_type") for row in results if isinstance(row, dict)]
        if len(types) != len(expected) or set(types) != expected or len(set(types)) != len(types):
            return "unavailable_manual_review", "legacy task 类型不完整、重复或损坏"
        if any(str(row.get("ts_code") or "") != str(report.get("ts_code") or "")
               or str(row.get("as_of") or "") != str(weekly.get("as_of") or "")
               for row in results):
            return "unavailable_manual_review", "legacy task 结果与周报候选或日期未绑定"
    return "applied", "六项 legacy task 已生成、写入逐票 M6.7 与确定性 Phase 4 报告"


def _derived_flag_comparison_status(weekly: dict) -> tuple[str, str]:
    """Validate the formal comparison-only derived-flag landing surface."""
    reports = weekly.get("reports") or []
    if not reports:
        return "not_triggered", "本周没有候选或持仓报告"
    for report in reports:
        node = (report.get("machine") or {}).get("derived_flag_comparison")
        if not isinstance(node, dict):
            return "unavailable_manual_review", "derived_flag_comparison missing"
        if (node.get("input_leaf") != "candidates[].derived_flags.vol_confirm"
                or node.get("comparison_only") is not True
                or node.get("production_effect_enabled") is not False
                or node.get("observed_outcome") not in {
                    "vol_confirm_true", "vol_confirm_false", "vol_confirm_unknown"
                }):
            return "unavailable_manual_review", "derived_flag_comparison boundary or outcome invalid"
    return "applied", "vol_confirm 已落到正式 comparison-only 观察项"


def _technical_volatility_comparison_status(weekly: dict, family: str) -> tuple[str, str]:
    """Validate one 12B source-family comparison surface."""
    reports = weekly.get("reports") or []
    if not reports:
        return "not_triggered", "本周没有候选或持仓报告"
    expected_prefix = f"candidates[].{family}"
    expected_status = "constant_null" if family == "volatility" else "snapshot_or_constant_null"
    expected_count = 3 if family == "volatility" else 39
    saw_observed = False
    for report in reports:
        node = ((report.get("machine") or {}).get("technical_volatility_comparison") or {})
        if (node.get("comparison_only") is not True
                or node.get("production_effect_enabled") is not False):
            return "unavailable_manual_review", "technical/volatility comparison boundary diverges"
        observation = node.get(family)
        if not isinstance(observation, dict):
            return "unavailable_manual_review", f"{family} comparison observation missing"
        if (observation.get("input_leaf_prefix") != expected_prefix
                or observation.get("producer_status") != expected_status
                or observation.get("comparison_only") is not True
                or observation.get("production_effect_enabled") is not False
                or observation.get("leaf_count") != expected_count
                or not isinstance(observation.get("input_sha256"), str)
                or len(observation["input_sha256"]) != 64):
            return "unavailable_manual_review", f"{family} comparison binding or digest invalid"
        if observation.get("observed_outcome") == "malformed":
            return "unavailable_manual_review", f"{family} source snapshot is malformed"
        if observation.get("observed_outcome") == "snapshot_observed":
            saw_observed = True
        elif observation.get("observed_outcome") not in {"constant_null"}:
            return "unavailable_manual_review", f"{family} comparison outcome invalid"
    if saw_observed:
        return "applied", f"{family} source snapshot reached the formal comparison-only surface"
    return "not_triggered", f"{family} producer is constant-null; no non-null snapshot was observed"


def _runtime_status(group: dict, weekly: dict) -> tuple[str, str]:
    handler = group["runtime_handler"]
    if handler == "intentionally_independent":
        return "intentionally_independent", group["intentional_independence"]["reason"]
    if handler == "lineage_gate":
        return "applied", "本周产物已通过批次、日期和候选集绑定"
    if handler == "unresolved_input_group":
        return "unavailable_manual_review", str(group["unresolved_reason"])
    if handler == "phase5_decision":
        return _phase5_status(weekly)
    if handler == "phase5_risk":
        return _phase5_status(weekly, risk_only=True)
    if handler == "m4_review_gate":
        return _m4_review_status(weekly)
    if handler == "market_regime":
        return _phase5_status(weekly, risk_only=True, market_only=True)
    if handler == "industry_trend":
        details = [((report.get("machine") or {}).get("industry_trend") or {})
                   for report in (weekly.get("reports") or [])]
        if not details:
            return "not_triggered", "本周没有候选/持仓报告"
        if any(detail.get("effect") == "unavailable_manual_review" for detail in details):
            return "unavailable_manual_review", "存在缺失、损坏、串线或陈旧的行业热度信号，已显式人工复核"
        if any(detail.get("effect") == "star_down" for detail in details):
            return "applied", "有效 headwind 已传入 Phase5，并使对应报告星级 -1"
        return "not_triggered", "行业趋势已核查；neutral/tailwind 未触发负面降星（tailwind 不重复加星）"
    if handler == "data_quality_shadow":
        shadow = weekly.get("data_quality_shadow")
        if not isinstance(shadow, dict):
            return "unavailable_manual_review", "data_quality_shadow missing; comparison consumer is not closed"
        if (shadow.get("as_of") != weekly.get("as_of")
                or shadow.get("comparison_only") is not True
                or shadow.get("production_effect_enabled") is not False):
            return "unavailable_manual_review", "data_quality_shadow date or comparison-only boundary diverges"
        return "applied", "data_quality_shadow is emitted on the weekly comparison surface"
    if handler == "comparison_track":
        return _derived_flag_comparison_status(weekly)
    if handler == "technical_volatility_comparison":
        family = str(group.get("comparison_family") or "")
        if family not in {"technical", "volatility"}:
            return "unavailable_manual_review", "technical/volatility comparison family missing"
        return _technical_volatility_comparison_status(weekly, family)
    if handler == "account_cash":
        return ("applied", "账户现金/持仓已联动现金分配或持仓处置") if weekly.get("cash_allocation") is not None else ("not_triggered", "本周未提供账户，未运行现金分配")
    if handler == "portfolio_risk":
        return _portfolio_status(weekly)
    if handler == "llm_tasks":
        return _llm_status(weekly)
    raise ValueError(f"unknown effect-contract runtime_handler: {handler}")


def build_legacy_effect_contract_ledger(weekly: dict, contract: dict,
                                       *, contract_fp: str) -> dict:
    """Rebuild the exact pre-leaf-classification ledger shape for one registry entry."""
    if (not isinstance(contract, dict)
            or contract.get("schema_name") != "a_short_m67_effect_contract"
            or contract.get("schema_version") != "1.0.0"
            or contract_fingerprint(contract) != contract_fp):
        raise ValueError("legacy effect-contract snapshot is invalid")
    records = []
    for group in contract.get("groups") or []:
        status, reason = _runtime_status(group, weekly)
        if status not in _STATUSES:
            raise ValueError(f"invalid legacy effect-contract runtime status: {status}")
        records.append({
            "id": group["id"], "policy": group["policy"], "status": status,
            "source_prefixes": list(group["source_prefixes"]),
            "source_paths_sha256": group["source_paths_sha256"],
            "terminal_surfaces": list(group["terminal_surfaces"]), "reason": reason,
        })
    for track in contract.get("comparison_tracks") or []:
        records.append({
            "id": track["id"], "policy": track["policy"],
            "status": "intentionally_independent",
            "source_prefixes": [track["schema_path"]],
            "source_paths_sha256": track["schema_sha256"],
            "terminal_surfaces": list(track.get("consumer_refs") or []),
            "reason": track["reason"],
        })
    counts = {status: sum(record["status"] == status for record in records)
              for status in sorted(_STATUSES)}
    return {
        "schema_name": "a_short_effect_contract_ledger", "schema_version": "1.0.0",
        "as_of": str(weekly.get("as_of") or ""), "contract_fingerprint": contract_fp,
        "records": records, "summary": {"total": len(records), **counts},
    }


def build_effect_contract_ledger(weekly: dict, contract: dict | None = None,
                                *, trend_guard: dict | None = None) -> dict:
    contract = contract if contract is not None else load_contract()
    validate_static_contract(contract)
    nature_by_path = leaf_natures(contract)
    effect_by_path = leaf_effects(contract)
    records = []
    for group in contract["groups"]:
        status, reason = _runtime_status(group, weekly)
        if status not in _STATUSES:
            raise ValueError(f"invalid effect-contract runtime status: {status}")
        group_paths = _paths_for_prefixes(list(nature_by_path), group["source_prefixes"])
        records.append({
            "id": group["id"], "policy": group["policy"], "status": status,
            "nature": contract["leaf_nature_by_group"][group["id"]],
            "leaf_natures": {path: nature_by_path[path] for path in group_paths},
            "leaf_effects": {path: effect_by_path[path] for path in group_paths},
            "source_prefixes": list(group["source_prefixes"]),
            "source_paths_sha256": group["source_paths_sha256"],
            "terminal_surfaces": list(group["terminal_surfaces"]), "reason": reason,
        })
    for track in contract.get("comparison_tracks") or []:
        records.append({
            "id": track["id"], "policy": track["policy"], "status": "intentionally_independent",
            "nature": "comparison_track", "leaf_natures": {track["schema_path"]: "comparison_track"},
            "leaf_effects": {track["schema_path"]: "formal_comparison_verdict"},
            "source_prefixes": [track["schema_path"]], "source_paths_sha256": track["schema_sha256"],
            "terminal_surfaces": list(track.get("consumer_refs") or []), "reason": track["reason"],
        })
    counts = {status: sum(record["status"] == status for record in records) for status in sorted(_STATUSES)}
    nature_counts = {nature: sum(value == nature for value in nature_by_path.values())
                     for nature in sorted(_NATURES)}
    effect_counts = {category: sum(value == category for value in effect_by_path.values())
                     for category in sorted(_LEAF_EFFECT_CATEGORIES)}
    guard = copy.deepcopy(trend_guard) if trend_guard is not None else _default_trend_guard(counts["unavailable_manual_review"])
    guard["current_unavailable_manual_review"] = counts["unavailable_manual_review"]
    return {
        "schema_name": "a_short_effect_contract_ledger", "schema_version": "1.0.0",
        "as_of": str(weekly.get("as_of") or ""), "contract_fingerprint": contract_fingerprint(contract),
        "records": records, "summary": {
            "total": len(records), **counts, "nature_counts": nature_counts,
            "effect_counts": effect_counts,
        },
        "trend_guard": guard,
    }


def validate_effect_contract_ledger(weekly: dict, previous_ledger: dict | None = None) -> None:
    actual = weekly.get("effect_contract_ledger")
    if not isinstance(actual, dict):
        raise ValueError("weekly missing effect_contract_ledger")
    actual_fp = actual.get("contract_fingerprint")
    current_fp = contract_fingerprint()
    if actual_fp == current_fp:
        expected = build_effect_contract_ledger(weekly, trend_guard=actual.get("trend_guard"))
        if actual != expected:
            raise ValueError("effect_contract_ledger diverges from registered field/rule effects")
        _validate_trend_guard_record(
            actual["trend_guard"],
            actual["summary"]["unavailable_manual_review"],
            previous_ledger,
        )
        return
    legacy = load_legacy_effect_contract(actual_fp)
    if legacy is None:
        raise ValueError("effect_contract_ledger fingerprint is neither current nor registered historical")
    expected = build_legacy_effect_contract_ledger(
        weekly, legacy, contract_fp=str(actual_fp)
    )
    if actual != expected:
        raise ValueError("historical effect_contract_ledger diverges from its registered contract")
