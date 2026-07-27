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
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "schemas" / "a_short_m67_effect_contract.json"
ANALYSIS_INPUT_SCHEMA_PATH = ROOT / "schemas" / "analysis_input.schema.json"
_DECISION_FILES = (
    "A-EGS/egs_main.py",
    "engine/egs_industry_heat.py",
    "engine/a_short_industry_theme.py",
    "runners/a_short_phase5_engine.py",
    "runners/a_short_weekly_pipeline.py",
    "runners/a_short_m67_render.py",
    "engine/a_short_portfolio_risk.py",
    "engine/a_short_effect_contract.py",
)
_CONSTANT_FILES = (
    "A-EGS/egs_main.py",
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
_STATIC_SOURCE_FILES = tuple(sorted(
    set(_DECISION_FILES) | set(_CONSTANT_FILES) | {_RUNTIME_CONFIG_FILE}
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


def _paths_for_prefixes(paths: list[str], prefixes: list[str]) -> list[str]:
    return sorted(path for path in paths if any(_matches_prefix(path, prefix) for prefix in prefixes))


def _canonical_ast(node):
    """Return a stable structural representation without ``ast.dump`` text.

    ``ast.dump`` changed its default rendering of empty fields in Python 3.13.
    The effect contract guards source structure, not a particular CPython
    pretty-printer, so omit empty-list implementation fields and retain the
    remaining node types, field names, and literal values as JSON data.
    """
    if isinstance(node, ast.AST):
        fields = []
        for field, value in ast.iter_fields(node):
            if isinstance(value, list) and not value:
                continue
            fields.append([field, _canonical_ast(value)])
        return {"node": type(node).__name__, "fields": fields}
    if isinstance(node, list):
        return [_canonical_ast(value) for value in node]
    if isinstance(node, bytes):
        return {"literal_type": "bytes", "hex": node.hex()}
    if isinstance(node, complex):
        return {"literal_type": "complex", "real": node.real, "imag": node.imag}
    if node is Ellipsis:
        return {"literal_type": "ellipsis"}
    if node is None or isinstance(node, (str, int, float, bool)):
        return node
    raise TypeError(f"unsupported AST fingerprint value: {type(node).__name__}")


def _predicate_hashes(source: str) -> list[str]:
    tree = ast.parse(source)
    tests = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert)):
            tests.append(_hash(_canonical_ast(node.test)))
    return sorted(tests)


def _constant_inventory(source: str) -> dict[str, str]:
    tree = ast.parse(source)
    values = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                values[target.id] = _hash(_canonical_ast(node.value))
    return dict(sorted(values.items()))


def _governed_python_literal_names(source: str, rel: str) -> list[str]:
    """Find business-threshold copies that would bypass the runtime JSON policy."""
    tree = ast.parse(source)
    policy_names = {
        "runners/a_short_phase5_engine.py": {
            "ATR_MULT", "RR_FLOOR", "BREAKOUT_RR_BONUS", "SINGLE_CAP_PCT", "IV_HALVE_PCT",
            "IV_NOBUILD_PCT", "IV_HV_RATIO_HI", "IV_HV_RATIO_LO", "OVERHEAT_5D",
            "OVERHEAT_20D", "MIN_AVG_AMOUNT_5D", "LOWXI_BAND", "SUPPORT_LOOKBACK",
            "RESISTANCE_LOOKBACK", "SR_SPIKE_ATR", "MIN_SHARES", "MIN_AMOUNT", "IMPACT_COST_FRAC",
        },
        "runners/a_short_weekly_pipeline.py": {
            "MIN_PRICE_OBS", "EX_DIV_WINDOW_DAYS", "FORWARD_EVENT_WINDOW_DAYS",
            "DRAGON_LIST_LOOKBACK_TRADING_DAYS", "BLOCK_TRADE_LOOKBACK_TRADING_DAYS",
        },
        "engine/a_short_portfolio_risk.py": {
            "SAME_SW_L2_THRESHOLD_PCT", "NORTHBOUND_THRESHOLD_PCT", "MARGIN_THRESHOLD_PCT",
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
        return sorted(offenders)
    names = policy_names.get(rel, set())
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id in names for target in targets):
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, (int, float)):
                offenders.extend(target.id for target in targets if isinstance(target, ast.Name) and target.id in names)
    return sorted(set(offenders))


def _runtime_portfolio_policy_literal_violations(portfolio_source: str, weekly_source: str) -> list[str]:
    """Reject literal copies in the two result-shaping portfolio consumers."""
    violations = []
    for label, pattern in (
            ("small_float_label", r"小流通市值\(<\d+(?:\.\d+)?亿元\)"),
            ("high_risk_cap_reduction_label", r"持仓单只上限临时下调\d+(?:\.\d+)?%")):
        if re.search(pattern, portfolio_source):
            violations.append(f"engine/a_short_portfolio_risk.py:{label}")

    tree = ast.parse(weekly_source)
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
    return sorted(violations)


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


def _runtime_policy_inventory(overrides: dict[str, str] | None = None,
                              schema_overrides: dict[str, str] | None = None) -> tuple[dict[str, list[str]], dict[str, str], dict[str, str]]:
    overrides = overrides or {}
    schema_overrides = schema_overrides or {}
    paths, value_hashes = {}, {}
    for rel in _RUNTIME_POLICY_FILES:
        raw = overrides.get(rel, (ROOT / rel).read_text(encoding="utf-8"))
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"runtime policy JSON invalid for effect contract: {rel}") from exc
        paths[rel] = _policy_leaf_paths(rel, payload)
        value_hashes[rel] = _hash(raw)
    schema_hashes = {rel: _hash(schema_overrides.get(rel, (ROOT / rel).read_text(encoding="utf-8")))
                     for rel in _RUNTIME_POLICY_SCHEMA_FILES}
    return paths, value_hashes, schema_hashes


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
    industry_theme = sources["engine/a_short_industry_theme.py"]
    trees = {rel: ast.parse(source) for rel, source in {
        _RUNTIME_CONFIG_FILE: loader,
        "A-EGS/egs_main.py": egs,
        "engine/a_short_industry_theme.py": industry_theme,
        "runners/a_short_phase5_engine.py": phase5,
        "engine/a_short_portfolio_risk.py": portfolio,
        "runners/a_short_weekly_pipeline.py": weekly,
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
                    if (key in declared["phase5"]
                            and _loader_reads_key(trees[_RUNTIME_CONFIG_FILE], "_validate_m67", "phase", key)
                            and _policy_value_reaches_result(trees["runners/a_short_phase5_engine.py"], "_PHASE5_POLICY", key)):
                        refs = [
                            f'{_RUNTIME_CONFIG_FILE}::_validate_m67.phase["{key}"]',
                            f'runners/a_short_phase5_engine.py::_PHASE5_POLICY["{key}"]',
                        ]
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


def _string_assignments(source: str) -> dict[str, str]:
    tree = ast.parse(source)
    out = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        if isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            out[node.targets[0].id] = node.value.value
    return out


def _operation_impact_sources(source: str) -> list[str]:
    tree = ast.parse(source)
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
    return sorted(sources)


def _literal_string_assignment(source: str, name: str) -> list[str]:
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        if not isinstance(node.targets[0], ast.Name) or node.targets[0].id != name:
            continue
        values = node.value.args[0] if isinstance(node.value, ast.Call) and node.value.args else node.value
        if isinstance(values, (ast.Tuple, ast.List, ast.Set)):
            return sorted(item.value for item in values.elts
                          if isinstance(item, ast.Constant) and isinstance(item.value, str))
    return []


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
    portfolio_tree = ast.parse(portfolio)
    factor_node = next(
        node for node in portfolio_tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "_FACTOR_SPECS")
    factor_specs = factor_node.value.elts if isinstance(factor_node.value, (ast.Tuple, ast.List)) else []
    policy_paths, policy_hashes, policy_schema_hashes = _runtime_policy_inventory(
        runtime_policy_overrides, runtime_policy_schema_overrides)
    return {
        "analysis_input_paths": analysis_input_paths(analysis_schema),
        "decision_predicate_sha256": {rel: _hash(_predicate_hashes(sources[rel])) for rel in _DECISION_FILES},
        "runtime_constants_sha256": {rel: _hash(_constant_inventory(sources[rel])) for rel in _CONSTANT_FILES},
        "governed_python_literal_names": {
            rel: _governed_python_literal_names(sources[rel], rel) for rel in _GOVERNED_LITERAL_FILES
        } | {"A-EGS/egs_main.py": _governed_python_literal_names(sources["A-EGS/egs_main.py"], "A-EGS/egs_main.py")},
        "runtime_portfolio_policy_literal_violations": _runtime_portfolio_policy_literal_violations(portfolio, weekly),
        "runtime_policy_paths": policy_paths,
        "runtime_policy_paths_sha256": _hash(policy_paths),
        "runtime_policy_sha256": policy_hashes,
        "runtime_policy_schema_sha256": policy_schema_hashes,
        "runtime_policy_leaf_readers": _runtime_policy_leaf_readers(policy_paths, sources),
        "operation_impact_sources": _operation_impact_sources(phase5) + _operation_impact_sources(weekly),
        "llm_task_types": _llm_task_types(analysis_schema),
        "portfolio_factor_fields": [row.elts[0].value for row in factor_specs
                                    if isinstance(row, (ast.Tuple, ast.List)) and row.elts
                                    and isinstance(row.elts[0], ast.Constant)
                                    and isinstance(row.elts[0].value, str)],
        "output_schema_sha256": {rel: _hash(output_schema_overrides.get(rel, (ROOT / rel).read_text(encoding="utf-8")))
                                 for rel in _OUTPUT_SCHEMA_FILES},
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
                     runtime_policy_overrides: dict[str, str] | None = None) -> dict:
    """Return the static inventory, memoized only for unmodified on-disk inputs."""
    if (source_overrides is None and analysis_schema is None
            and output_schema_overrides is None and runtime_policy_overrides is None):
        # A fresh copy prevents a caller from poisoning the cached contract view.
        return copy.deepcopy(_default_static_inventory_from_snapshot(_read_default_static_snapshot()))
    return _build_static_inventory(
        source_overrides=source_overrides,
        analysis_schema=analysis_schema,
        output_schema_overrides=output_schema_overrides,
        runtime_policy_overrides=runtime_policy_overrides,
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
        if handler in {"lineage_gate", "phase5_decision", "phase5_risk", "market_regime", "account_cash", "portfolio_risk", "llm_tasks"}:
            proof_paths = group.get("proven_consumer_paths")
            if not isinstance(proof_paths, list) or sorted(proof_paths) != group_paths:
                return (f"effect contract {group['id']} direct runtime handler lacks all-leaf "
                        "consumer proof; split unresolved leaves or register every leaf")
            if not str(group.get("consumer_proof_ref") or "").strip():
                return f"effect contract {group['id']} direct runtime handler lacks consumer_proof_ref"
        if policy == "intentionally_independent":
            exception = group.get("intentional_independence")
            if not isinstance(exception, dict) or not all(str(exception.get(key) or "").strip()
                                                         for key in ("reason", "owner", "review_ref")):
                return f"effect contract {group['id']} independent exception lacks reason/owner/review_ref"
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
    if contract.get("analysis_input_all_paths_sha256") != _hash(paths):
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
        for path in matched:
            policy_coverage[(rel, path)] += 1
            if policy == "must_affect_result" and not leaf_readers.get(path):
                return (f"effect contract runtime policy leaf has no actual result reader: "
                        f"{rel}:{path}")
    policy_uncovered = sorted(f"{rel}:{path}" for (rel, path), count in policy_coverage.items() if count == 0)
    policy_duplicate = sorted(f"{rel}:{path}" for (rel, path), count in policy_coverage.items() if count > 1)
    if policy_uncovered or policy_duplicate:
        return f"effect contract runtime policy coverage invalid: uncovered={policy_uncovered[:4]}, duplicate={policy_duplicate[:4]}"
    if contract.get("runtime_policy_paths_sha256") != inventory["runtime_policy_paths_sha256"]:
        return "runtime policy field inventory changed without effect contract update"
    if contract.get("runtime_policy_sha256") != inventory["runtime_policy_sha256"]:
        return "runtime policy value changed without effect contract update"
    if contract.get("runtime_policy_schema_sha256") != inventory["runtime_policy_schema_sha256"]:
        return "runtime policy schema changed without effect contract update"
    if contract.get("runtime_policy_leaf_readers_sha256") != _hash(inventory["runtime_policy_leaf_readers"]):
        return "runtime policy per-leaf reader mapping changed without effect contract update"
    literals = {rel: values for rel, values in inventory["governed_python_literal_names"].items() if values}
    if literals:
        return f"governed business threshold literal returned to Python: {literals}"
    if contract.get("decision_predicate_sha256") != inventory["decision_predicate_sha256"]:
        return "decision predicate changed without effect contract update"
    if contract.get("runtime_constants_sha256") != inventory["runtime_constants_sha256"]:
        return "runtime threshold/constant changed without effect contract update"
    if sorted(contract.get("operation_impact_sources") or []) != sorted(inventory["operation_impact_sources"]):
        return "operation_impact source_field changed without effect contract update"
    if sorted(contract.get("llm_task_types") or []) != inventory["llm_task_types"]:
        return "LLM task type changed without effect contract update"
    if sorted(contract.get("portfolio_factor_fields") or []) != sorted(inventory["portfolio_factor_fields"]):
        return "portfolio factor field changed without effect contract update"
    if contract.get("output_schema_sha256") != inventory["output_schema_sha256"]:
        return "weekly/M6.7 output schema changed without effect contract update"
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
    if handler == "account_cash":
        return ("applied", "账户现金/持仓已联动现金分配或持仓处置") if weekly.get("cash_allocation") is not None else ("not_triggered", "本周未提供账户，未运行现金分配")
    if handler == "portfolio_risk":
        return _portfolio_status(weekly)
    if handler == "llm_tasks":
        return _llm_status(weekly)
    raise ValueError(f"unknown effect-contract runtime_handler: {handler}")


def build_effect_contract_ledger(weekly: dict, contract: dict | None = None) -> dict:
    contract = contract if contract is not None else load_contract()
    validate_static_contract(contract)
    records = []
    for group in contract["groups"]:
        status, reason = _runtime_status(group, weekly)
        if status not in _STATUSES:
            raise ValueError(f"invalid effect-contract runtime status: {status}")
        records.append({
            "id": group["id"], "policy": group["policy"], "status": status,
            "source_prefixes": list(group["source_prefixes"]),
            "source_paths_sha256": group["source_paths_sha256"],
            "terminal_surfaces": list(group["terminal_surfaces"]), "reason": reason,
        })
    for track in contract.get("comparison_tracks") or []:
        records.append({
            "id": track["id"], "policy": track["policy"], "status": "intentionally_independent",
            "source_prefixes": [track["schema_path"]], "source_paths_sha256": track["schema_sha256"],
            "terminal_surfaces": list(track.get("consumer_refs") or []), "reason": track["reason"],
        })
    counts = {status: sum(record["status"] == status for record in records) for status in sorted(_STATUSES)}
    return {
        "schema_name": "a_short_effect_contract_ledger", "schema_version": "1.0.0",
        "as_of": str(weekly.get("as_of") or ""), "contract_fingerprint": contract_fingerprint(contract),
        "records": records, "summary": {"total": len(records), **counts},
    }


def validate_effect_contract_ledger(weekly: dict) -> None:
    actual = weekly.get("effect_contract_ledger")
    if not isinstance(actual, dict):
        raise ValueError("weekly missing effect_contract_ledger")
    expected = build_effect_contract_ledger(weekly)
    if actual != expected:
        raise ValueError("effect_contract_ledger diverges from registered field/rule effects")
