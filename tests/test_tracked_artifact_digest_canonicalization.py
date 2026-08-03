"""Derived guard for canonical digests of tracked JSON contracts.

Tracked contracts are edited under different checkout EOL policies.  A digest
that binds one of them therefore has to be the canonical JSON digest, never a
hash of the checkout bytes.  The guard keeps statically named tracked paths,
function-local path assignments, direct ``hashlib.sha256(path.read_bytes())``
calls, and one-hop helper argument propagation visible.  Runtime evidence/state
digests may hash bytes as received only when their exact coordinate has a
reviewed exception below.
"""
from __future__ import annotations

import ast
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (ROOT / "engine", ROOT / "runners")
TRACKED_PREFIXES = ("docs", "presets", "schemas")

# A coordinate may be excepted only when the raw bytes are deliberately part
# of runtime evidence or input binding rather than a tracked JSON contract.
# Keep every exception exact and explain it here; a stale coordinate is an
# error, so this cannot become a silent allow-list.
RUNTIME_COMPOSED_PATH_LABEL = "<runtime-composed-path>"
RAW_DIGEST_EXCEPTIONS: dict[str, str] = {
    "runners/a_long_data_integrity_audit.py:file_sha256:<runtime-composed-path>:path": (
        "A-long integrity audit fingerprints its runtime input file for evidence, not tracked contract identity."
    ),
    "engine/a_short_industry_weight_comparison.py:_verify_egs_published_sources:helper=_file_digest:<runtime-composed-path>:analysis_input_path": (
        "P5 verifies caller-supplied analysis_input bytes for runtime evidence lineage, not a tracked contract."
    ),
    "engine/a_short_industry_weight_comparison.py:_verify_egs_published_sources:helper=_file_digest:<runtime-composed-path>:weight_comparison_path": (
        "P5 verifies caller-supplied comparison bytes for runtime evidence lineage, not a tracked contract."
    ),
    "engine/a_short_overlay_adjudication.py:_verify_egs_publish_marker:helper=_file_sha256:<runtime-composed-path>:path": (
        "P4a verifies caller-supplied published bundle bytes for receipt binding, not a tracked contract digest."
    ),
    "engine/us_short_soft_boost_consumption.py:resolve_soft_boost_consumption:<runtime-composed-path>:Path(candidate_artifact_path)": (
        "K4b consumption binds the candidate artifact bytes as received before validation; it is runtime evidence input."
    ),
    "engine/us_short_soft_boost_consumption.py:resolve_soft_boost_consumption:<runtime-composed-path>:Path(classification_packet_path)": (
        "K4b consumption binds the classification packet bytes as received before validation; it is runtime evidence input."
    ),
    "runners/a_short_account_state_from_manual_tables.py:main:helper=_sha256:<runtime-composed-path>:path": (
        "Manual-account runner fingerprints the caller-supplied state table for provenance, not a tracked contract."
    ),
    "runners/a_short_crash_veto_tracker.py:_official_inputs:helper=_sha256:<runtime-composed-path>:full_path": (
        "Crash-veto tracking binds the runtime full-universe artifact bytes for audit identity, not a tracked contract."
    ),
    "runners/a_short_crash_veto_tracker.py:_official_inputs:helper=_sha256:<runtime-composed-path>:recon_path": (
        "Crash-veto tracking binds the runtime reconciliation artifact bytes for audit identity, not a tracked contract."
    ),
    "runners/a_short_d4_policy_ablation.py:build_summary:helper=_sha256:<runtime-composed-path>:PREREG_PATH": (
        "D4 ablation binds the runtime preregistration artifact bytes for reproducibility, not a tracked contract."
    ),
    "runners/a_short_d4_policy_ablation.py:build_summary:helper=_sha256:<runtime-composed-path>:samples_path": (
        "D4 ablation binds caller-supplied runtime sample bytes for reproducibility, not a tracked contract."
    ),
    "runners/a_short_entry_funnel_calibration.py:build_report:helper=sha256:<runtime-composed-path>:PREREG_PATH": (
        "Entry-funnel calibration fingerprints its runtime preregistration artifact for reproducibility."
    ),
    "runners/a_short_entry_funnel_calibration.py:verified_sources:helper=sha256:<runtime-composed-path>:path": (
        "Entry-funnel calibration fingerprints caller-supplied runtime sample bytes for reproducibility."
    ),
    "runners/a_short_rule6_report_rc_coverage_audit.py:main:<runtime-composed-path>:args.analysis_input": (
        "Rule6 audit records the caller-supplied analysis-input bytes used by the report, not a tracked contract."
    ),
    "runners/a_short_steady_alpha_reaudit.py:build_evidence_report:helper=file_sha256:<runtime-composed-path>:preregistration_path": (
        "Steady-alpha re-audit fingerprints runtime preregistration bytes for evidence reproducibility."
    ),
    "runners/a_short_theme_forward_comparison.py:_load_formal_decision_receipt:<runtime-composed-path>:archive_path": (
        "Forward comparison verifies runtime archive bytes against its formal decision receipt."
    ),
    "runners/a_short_theme_forward_comparison.py:_record_formal_decision_if_due:<runtime-composed-path>:archive_path": (
        "Forward comparison records runtime archive bytes in its formal decision receipt."
    ),
    "runners/a_short_weekly_pipeline.py:_validate_official_publish_marker:<runtime-composed-path>:path": (
        "Weekly pipeline verifies the consumed analysis_input bytes bound by the published runtime marker, not a tracked contract digest."
    ),
    "runners/a_short_official_operation_evidence.py:_file_digest:<runtime-composed-path>:path": (
        "Official-operation evidence binds runtime evidence input bytes, not tracked contract identity."
    ),
    "runners/us_short_account_state_from_manual_tables.py:main:helper=_sha256:<runtime-composed-path>:path": (
        "Manual-account runner fingerprints the caller-supplied state table for provenance, not a tracked contract."
    ),
    "runners/us_short_batch5_data_context_source_packet.py:_soft_boost_common_input_sha256:<runtime-composed-path>:paths[field]": (
        "Batch5 soft-boost inputs are runtime packet artifacts whose exact bytes bind consumption provenance."
    ),
    "runners/us_short_batch5_data_context_source_packet.py:_validated_provider_envelope_digests:<runtime-composed-path>:paths[field]": (
        "Batch5 provider envelopes are runtime source artifacts checked against packet-declared byte digests."
    ),
    "runners/us_short_batch5_data_context_source_packet.py:run_packet:<runtime-composed-path>:path": (
        "Batch5 per-ticker records bind selected runtime source bytes to the emitted evidence."
    ),
    "runners/us_short_batch5_data_context_source_packet.py:source_packet_input_manifest:<runtime-composed-path>:path": (
        "Batch5 source manifest records exact runtime source bytes for packet reproducibility."
    ),
    "runners/us_short_batch5_full_candidate_live_source_packet.py:_build_local_source_packet:<runtime-composed-path>:path": (
        "Full-candidate packet binds selected runtime source artifact bytes, not tracked contract identity."
    ),
    "runners/us_short_batch5_full_candidate_live_source_packet.py:_build_local_source_packet:<runtime-composed-path>:yfinance_grade_actions_path": (
        "Optional yfinance-grade action input is a runtime provider-evidence artifact with intentional raw-byte binding."
    ),
    "runners/us_short_batch5_full_candidate_live_source_packet.py:_raw_capture_manifest:<runtime-composed-path>:raw_path": (
        "Captured provider payloads are raw evidence whose exact bytes are recorded in the capture manifest."
    ),
    "runners/us_short_batch5_live_source_packet.py:_build_local_source_packet:<runtime-composed-path>:paths[artifact]": (
        "Live source packet binds selected runtime source artifact bytes, not tracked contract identity."
    ),
    "runners/us_short_batch5_replay_pass2_source_packet_from_raw.py:ReplayClient.__init__:helper=_sha256_file:<runtime-composed-path>:wrapper_path": (
        "Pass2 replay fingerprints the runtime wrapper input bytes for reproducibility, not a tracked contract."
    ),
    "runners/us_short_batch5_replay_pass2_source_packet_from_raw.py:_load_bound_source_capture:helper=_sha256_file:<runtime-composed-path>:raw_path": (
        "Pass2 replay fingerprints raw runtime source bytes for reproducibility, not a tracked contract."
    ),
    "runners/us_short_batch5_replay_pass2_source_packet_from_raw.py:_load_bound_source_capture:helper=_sha256_file:<runtime-composed-path>:summary_path": (
        "Pass2 replay fingerprints the runtime summary input bytes for reproducibility, not a tracked contract."
    ),
    "runners/us_short_batch5_to_batch4_weekend_e2e.py:run_e2e:<runtime-composed-path>:source_packet": (
        "Weekend E2E binds the runtime source-packet bytes before receipt validation."
    ),
    "runners/us_short_batch5_to_batch4_weekend_e2e.py:run_e2e:<runtime-composed-path>:template_path": (
        "Weekend E2E records the caller-selected action-template bytes for replay binding."
    ),
    "runners/us_short_forward_lifecycle_capture.py:_sha256_file:<runtime-composed-path>:path": (
        "Forward-lifecycle capture fingerprints runtime input bytes for evidence reproducibility."
    ),
    "runners/us_short_massive_corporate_action_normalize.py:_load_capture_binding:<runtime-composed-path>:packet_path": (
        "Corporate-action normalization binds the captured packet's exact runtime bytes for evidence lineage."
    ),
    "runners/us_short_weekly_capstone_soft_discovery.py:_published_sha256:<runtime-composed-path>:path": (
        "Weekly capstone fingerprints the runtime published artifact for output provenance."
    ),
}


def _path_parts(node: ast.AST, constants: dict[str, tuple[str, ...]]) -> tuple[str, ...] | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _path_parts(node.left, constants)
        right = _path_parts(node.right, constants)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path" and node.args:
        return _path_parts(node.args[0], constants)
    return () if isinstance(node, ast.Name) and node.id in {"ROOT", "REPO_ROOT", "PROJECT_ROOT"} else None


def _module_constants(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    constants: dict[str, tuple[str, ...]] = {
        "ROOT": (), "REPO_ROOT": (), "PROJECT_ROOT": (), "_ROOT": (),
    }
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if value is None:
            continue
        parts = _path_parts(value, constants)
        if parts is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = parts
    return constants


def _is_gitignored(relative_path: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "--quiet", "--", relative_path],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    return {
        id(child): node
        for node in ast.walk(tree)
        for child in ast.iter_child_nodes(node)
    }


def _nearest_scope(node: ast.AST, parents: dict[int, ast.AST]) -> ast.AST | None:
    current = node
    while id(current) in parents:
        current = parents[id(current)]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return current
    return None


def _scope_name(node: ast.AST, parents: dict[int, ast.AST]) -> str:
    names: list[str] = []
    current = node
    if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names.append(current.name)
    while id(current) in parents:
        current = parents[id(current)]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(current.name)
    return ".".join(reversed(names)) or "<module>"


def _binding_targets(node: ast.AST) -> list[ast.Name]:
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    elif isinstance(node, ast.NamedExpr):
        targets = [node.target]
    else:
        return []
    return [target for target in targets if isinstance(target, ast.Name)]


def _scoped_path_constants(
    tree: ast.Module,
) -> tuple[dict[str, tuple[str, ...]], dict[int, ast.AST], dict[int, dict[str, tuple[str, ...]]]]:
    """Resolve module and function-local static path bindings without executing code."""
    parents = _parent_map(tree)
    module_constants = _module_constants(tree)
    scope_constants: dict[int, dict[str, tuple[str, ...]]] = {}
    functions = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for function in functions:
        constants = dict(module_constants)
        assignments = [
            node for node in ast.walk(function)
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr))
            and _nearest_scope(node, parents) is function
        ]
        assignments.sort(key=lambda node: (getattr(node, "lineno", 0), getattr(node, "col_offset", 0)))
        for assignment in assignments:
            value = assignment.value
            parts = _path_parts(value, constants)
            if parts is None:
                continue
            for target in _binding_targets(assignment):
                constants[target.id] = parts
        scope_constants[id(function)] = constants
    return module_constants, parents, scope_constants


def _constants_for(
    node: ast.AST,
    module_constants: dict[str, tuple[str, ...]],
    parents: dict[int, ast.AST],
    scope_constants: dict[int, dict[str, tuple[str, ...]]],
) -> dict[str, tuple[str, ...]]:
    scope = _nearest_scope(node, parents)
    return module_constants if scope is None else scope_constants.get(id(scope), module_constants)


def _tracked_path_label(node: ast.AST, constants: dict[str, tuple[str, ...]]) -> str | None:
    parts = _path_parts(node, constants)
    if not parts or parts[0] not in TRACKED_PREFIXES:
        return None
    relative_path = Path(*parts).as_posix()
    if _is_gitignored(relative_path):
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path" and node.args:
        if isinstance(node.args[0], ast.Name):
            return node.args[0].id
    return relative_path


def _runtime_path_label(node: ast.AST) -> str:
    try:
        expression = ast.unparse(node)
    except Exception:
        expression = type(node).__name__
    expression = " ".join(expression.split())
    return f"{RUNTIME_COMPOSED_PATH_LABEL}:{expression}"


def _path_label(node: ast.AST | None, constants: dict[str, tuple[str, ...]]) -> str:
    if node is None:
        return f"{RUNTIME_COMPOSED_PATH_LABEL}:<missing>"
    return _tracked_path_label(node, constants) or _runtime_path_label(node)


def _site_coordinate(relative_path: Path, node: ast.AST, label: str, parents: dict[int, ast.AST]) -> str:
    return f"{relative_path.as_posix()}:{_scope_name(node, parents)}:{label}"


def _raw_reader_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Name):
        return None
    normalized = node.id.lower()
    return node.id if "read" in normalized and "bytes" in normalized else None


def _sha256_read_bytes_path(node: ast.Call) -> ast.AST | None:
    hash_function = node.func
    is_hash_call = (
        isinstance(hash_function, ast.Attribute)
        and isinstance(hash_function.value, ast.Name)
        and hash_function.value.id == "hashlib"
        and hash_function.attr.lower().startswith(("sha", "blake"))
    ) or (
        isinstance(hash_function, ast.Name)
        and hash_function.id.lower().startswith(("sha", "blake"))
    )
    if not (is_hash_call and node.args):
        return None
    argument = node.args[0]
    if (
        isinstance(argument, ast.Call)
        and isinstance(argument.func, ast.Attribute)
        and argument.func.attr == "read_bytes"
        and not argument.args
    ):
        return argument.func.value
    return None


def _function_argument_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [
        argument.arg
        for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    ]


def _helper_parameter_indexes(tree: ast.Module) -> dict[str, tuple[int, ...]]:
    """Find one-hop helpers whose single return hashes a parameter's raw bytes."""
    helpers: dict[str, tuple[int, ...]] = {}
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) or len(function.body) != 1:
            continue
        if not isinstance(function.body[0], ast.Return):
            continue
        if function.body[0].value is None:
            continue
        arguments = _function_argument_names(function)
        indexes: set[int] = set()
        for call in ast.walk(function.body[0].value):
            if not isinstance(call, ast.Call):
                continue
            path_node = _sha256_read_bytes_path(call)
            if isinstance(path_node, ast.Name) and path_node.id in arguments:
                indexes.add(arguments.index(path_node.id))
            elif (
                isinstance(path_node, ast.Call)
                and isinstance(path_node.func, ast.Name)
                and path_node.func.id == "Path"
                and path_node.args
                and isinstance(path_node.args[0], ast.Name)
                and path_node.args[0].id in arguments
            ):
                indexes.add(arguments.index(path_node.args[0].id))
        if indexes:
            helpers[function.name] = tuple(sorted(indexes))
    return helpers


def _raw_digest_coordinates(relative_path: Path, source: str) -> set[str]:
    tree = ast.parse(source, filename=str(relative_path))
    module_constants, parents, scope_constants = _scoped_path_constants(tree)
    helpers = _helper_parameter_indexes(tree)
    helper_functions = {
        function.name: function
        for function in ast.walk(tree)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        and function.name in helpers
    }
    helper_calls_seen: set[str] = set()
    coordinates: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        constants = _constants_for(node, module_constants, parents, scope_constants)
        constant_name: str | None = None
        if isinstance(node.func, ast.Attribute) and node.func.attr == "read_bytes":
            constant_name = _tracked_path_label(node.func.value, constants)
        elif _raw_reader_name(node.func) and node.args:
            constant_name = _tracked_path_label(node.args[0], constants)
        if constant_name:
            coordinates.add(_site_coordinate(relative_path, node, constant_name, parents))

        path_node = _sha256_read_bytes_path(node)
        if path_node is not None:
            scope = _nearest_scope(node, parents)
            if scope is None or scope.name not in helpers:
                coordinates.add(_site_coordinate(relative_path, node, _path_label(path_node, constants), parents))

        if isinstance(node.func, ast.Name) and node.func.id in helpers:
            helper_calls_seen.add(node.func.id)
            helper_arguments = _function_argument_names(helper_functions[node.func.id])
            for argument_index in helpers[node.func.id]:
                actual = node.args[argument_index] if len(node.args) > argument_index else None
                if actual is None and argument_index < len(helper_arguments):
                    actual = next(
                        (keyword.value for keyword in node.keywords if keyword.arg == helper_arguments[argument_index]),
                        None,
                    )
                label = _path_label(actual, constants)
                coordinates.add(_site_coordinate(
                    relative_path, node, f"helper={node.func.id}:{label}", parents,
                ))
    for helper_name, argument_indexes in helpers.items():
        if helper_name in helper_calls_seen:
            continue
        function = helper_functions[helper_name]
        arguments = _function_argument_names(function)
        for argument_index in argument_indexes:
            coordinates.add(_site_coordinate(
                relative_path, function,
                f"{RUNTIME_COMPOSED_PATH_LABEL}:{arguments[argument_index]}", parents,
            ))
    return coordinates


def _derived_raw_digest_coordinates(sources: dict[Path, str] | None = None) -> set[str]:
    if sources is None:
        sources = {
            path.relative_to(ROOT): path.read_text(encoding="utf-8")
            for source_root in SOURCE_ROOTS
            for path in source_root.rglob("*.py")
        }
    return {
        coordinate
        for relative_path, source in sources.items()
        for coordinate in _raw_digest_coordinates(relative_path, source)
    }


class TrackedArtifactDigestCanonicalizationTests(unittest.TestCase):
    def test_every_derived_tracked_raw_digest_has_an_explicit_exception(self) -> None:
        """The class is derived from engine/runners, not a hand-written registry."""
        derived = _derived_raw_digest_coordinates()
        unexplained = sorted(derived - RAW_DIGEST_EXCEPTIONS.keys())
        self.assertEqual(unexplained, [], "tracked JSON must use _serialized_sha256: " + ", ".join(unexplained))
        stale = sorted(set(RAW_DIGEST_EXCEPTIONS) - derived)
        self.assertEqual(stale, [], "exception no longer names a derived raw-digest coordinate: " + ", ".join(stale))
        self.assertTrue(all(reason.strip() for reason in RAW_DIGEST_EXCEPTIONS.values()))

    def test_original_epoch_raw_reader_is_a_red_control(self) -> None:
        relative_path = Path("engine/us_short_soft_boost_consumption.py")
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        mutant = source.replace(
            "epoch, epoch_sha = _read_canonical_json(EPOCH_PATH)",
            "epoch, epoch_sha = _read_json_bytes(EPOCH_PATH)",
            1,
        )
        self.assertNotEqual(mutant, source, "epoch canonical call moved; update this red control")
        coordinates = _derived_raw_digest_coordinates({relative_path: mutant})
        self.assertTrue(
            any(coordinate.endswith(":EPOCH_PATH") for coordinate in coordinates),
            f"original epoch raw-reader mutation escaped the derived guard: {coordinates}",
        )

    def test_future_third_tracked_raw_hash_is_a_red_control(self) -> None:
        relative_path = Path("runners/future_digest_leg.py")
        source = '''\
from pathlib import Path
import hashlib
ROOT = Path(__file__).resolve().parents[1]
FUTURE_SCHEMA = ROOT / "schemas" / "future.json"
def bad() -> str:
    return hashlib.sha256(FUTURE_SCHEMA.read_bytes()).hexdigest()
'''
        coordinates = _derived_raw_digest_coordinates({relative_path: source})
        self.assertEqual(coordinates, {"runners/future_digest_leg.py:bad:FUTURE_SCHEMA"})

    def test_function_local_tracked_path_is_a_red_control(self) -> None:
        relative_path = Path("engine/function_local_digest_leg.py")
        source = '''\
from pathlib import Path
import hashlib
ROOT = Path(__file__).resolve().parents[1]
def bad() -> str:
    local_schema = ROOT / "schemas" / "future.json"
    return hashlib.sha256(local_schema.read_bytes()).hexdigest()
'''
        coordinates = _derived_raw_digest_coordinates({relative_path: source})
        self.assertEqual(
            coordinates,
            {"engine/function_local_digest_leg.py:bad:local_schema"},
        )

    def test_one_hop_helper_tracked_argument_is_a_red_control(self) -> None:
        relative_path = Path("engine/helper_indirect_digest_leg.py")
        source = '''\
from pathlib import Path
import hashlib
ROOT = Path(__file__).resolve().parents[1]
TRACKED_SCHEMA = ROOT / "schemas" / "future.json"
def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
def bad() -> str:
    return digest(TRACKED_SCHEMA)
'''
        coordinates = _derived_raw_digest_coordinates({relative_path: source})
        self.assertEqual(
            coordinates,
            {"engine/helper_indirect_digest_leg.py:bad:helper=digest:TRACKED_SCHEMA"},
        )

    def test_one_hop_helper_imported_hash_keyword_argument_is_a_red_control(self) -> None:
        relative_path = Path("engine/helper_keyword_digest_leg.py")
        source = '''\
from pathlib import Path
from hashlib import sha256
ROOT = Path(__file__).resolve().parents[1]
TRACKED_SCHEMA = ROOT / "schemas" / "future.json"
def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()
def bad() -> str:
    return digest(path=TRACKED_SCHEMA)
'''
        coordinates = _derived_raw_digest_coordinates({relative_path: source})
        self.assertEqual(
            coordinates,
            {"engine/helper_keyword_digest_leg.py:bad:helper=digest:TRACKED_SCHEMA"},
        )

    def test_unreferenced_helper_still_has_a_reviewable_runtime_coordinate(self) -> None:
        relative_path = Path("engine/unreferenced_helper_digest_leg.py")
        source = '''\
import hashlib
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
'''
        coordinates = _derived_raw_digest_coordinates({relative_path: source})
        self.assertEqual(
            coordinates,
            {"engine/unreferenced_helper_digest_leg.py:digest:<runtime-composed-path>:path"},
        )

    def test_runtime_composed_tracked_raw_hash_is_a_red_control(self) -> None:
        relative_path = Path("engine/runtime_composed_digest_leg.py")
        source = '''\
from pathlib import Path
import hashlib
def bad(root: str, policy: dict[str, object]) -> str:
    packet = Path(root) / policy["source_packet"]["path"]
    return hashlib.sha256(packet.read_bytes()).hexdigest()
'''
        coordinates = _derived_raw_digest_coordinates({relative_path: source})
        self.assertEqual(
            coordinates,
            {"engine/runtime_composed_digest_leg.py:bad:<runtime-composed-path>:packet"},
        )

    def test_symbol_coordinates_survive_line_relocation(self) -> None:
        relative_path = Path("engine/relocated_digest_leg.py")
        source = '''\
from pathlib import Path
import hashlib
ROOT = Path(__file__).resolve().parents[1]
TRACKED_SCHEMA = ROOT / "schemas" / "future.json"
def bad() -> str:
    return hashlib.sha256(TRACKED_SCHEMA.read_bytes()).hexdigest()
'''
        original = _derived_raw_digest_coordinates({relative_path: source})
        shifted = _derived_raw_digest_coordinates({relative_path: "\n\n" + source})
        self.assertEqual(original, shifted)

    def test_runtime_state_raw_bytes_are_not_in_the_tracked_contract_class(self) -> None:
        relative_path = Path("engine/runtime_receipt.py")
        source = '''\
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
STATE_RECEIPT = ROOT / "state" / "us_short" / "receipt.json"
def read() -> object:
    return _read_json_bytes(STATE_RECEIPT)
'''
        self.assertEqual(_derived_raw_digest_coordinates({relative_path: source}), set())


if __name__ == "__main__":
    unittest.main()
