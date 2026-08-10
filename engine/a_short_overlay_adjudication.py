"""P4a official Stage3 Top5 rank-source evidence, settlement and advisory adjudication.

This is intentionally a private, comparison-only sidecar.  It never calls a
provider, never changes the published EGS/M6.7 result, and never writes an
activation plan.  The only data it consumes are a just-published official
bundle, its matching Stage3 snapshot/overlay scorer receipt, and the existing
single shared daily cache.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import subprocess
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

import jsonschema

from engine import a_short_evidence_epoch_mode as _epoch_mode
from engine.a_short_artifact_set_transaction import commit_artifact_set
from engine import egs_industry_heat as _heat

from engine.a_short_experiment_admission_registry import admission_snapshot, get_admission
from engine.a_short_nullable_bool import require_known_risk_bool
from engine.a_short_runtime_config import runtime_configuration_lineage


ROOT = Path(__file__).resolve().parents[1]
PROGRAM_ID = "a_short_overlay_adjudication_p4a"
ADMISSION_ID = "p4_stage3_rank_source"
PRIVATE_SCHEMA = ROOT / "schemas" / "a_short_overlay_adjudication_private_record.schema.json"
PUBLIC_SCHEMA = ROOT / "schemas" / "a_short_overlay_adjudication_summary.schema.json"
DAILY_CACHE_SCHEMA = ROOT / "schemas" / "a_short_factor_comparison_v2_daily_cache.schema.json"
DEFAULT_PRIVATE_ROOT = ROOT / "state" / "a_short" / "overlay_adjudication_private" / "v1"
DEFAULT_PUBLIC_JSON = ROOT / "research" / "results" / "a_short" / "overlay_adjudication_summary.json"
DEFAULT_PUBLIC_MD = ROOT / "research" / "results" / "a_short" / "overlay_adjudication_summary.md"
#: Gitignored (`state/*/artifact_set_journal/`); rollback journal + old-byte backups only.
DEFAULT_ARTIFACT_SET_JOURNAL_DIR = ROOT / "state" / "a_short" / "artifact_set_journal" / "overlay_adjudication"
HORIZONS = (5, 10, 20)
BENCHMARKS = ("csi1000", "csi300")
BENCHMARK_CODES = {"csi1000": "000852.SH", "csi300": "000300.SH"}
TOP_K, ROUND_TRIP_COST_PCT = 5, 0.16
# The epoch machinery itself cannot be part of the contract it computes; every
# other top-level function in this module is bound.  Enumerated here (not inline)
# so `tests/test_a_short_evidence_epoch_mode.py` can assert the set is exact.
P4A_SEMANTIC_MODULE_EXCLUSIONS = frozenset({
    "_today", "_epoch_context", "_contract_fingerprint", "_epoch_id",
})


class OverlayAdjudicationError(ValueError):
    """A P4a proof, cache, identity, or statistical contract is malformed."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _record_digest(record: dict) -> str:
    """Seal every identity-bearing private-record field, not payload alone."""
    return _digest({key: value for key, value in record.items() if key != "record_sha256"})


def _seal_record(record: dict) -> dict:
    record["record_sha256"] = _record_digest(record)
    return record


def _load(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _public_json_bytes(value: Any) -> bytes:
    """The exact bytes `_write` would have written, without writing them."""
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _write(path: str | Path, value: Any) -> None:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_public_json_bytes(value))
    os.replace(temporary, path)


def _date(value: object, label: str = "date") -> str:
    text = str(value or "")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise OverlayAdjudicationError(f"P4a {label} must be YYYYMMDD") from exc
    return text


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _root(root: str | Path) -> Path:
    value = Path(root).resolve()
    suffix = ("state", "a_short", "overlay_adjudication_private", "v1")
    if tuple(part.lower() for part in value.parts[-4:]) != suffix:
        raise OverlayAdjudicationError("P4a private root must end state/a_short/overlay_adjudication_private/v1")
    try:
        relative = value.relative_to(ROOT)
    except ValueError:
        return value
    try:
        result = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--", str(relative)],
                                capture_output=True, text=True, check=False)
    except OSError as exc:
        raise OverlayAdjudicationError("cannot prove P4a private root is gitignored") from exc
    if result.returncode != 0:
        raise OverlayAdjudicationError("P4a private root is not a provably gitignored path")
    return value


def _boundary() -> dict:
    return {"comparison_only": True, "automatic_policy_switch": False,
            "reads_account_or_holdings": False, "p4b_implemented": False}


def _source_files() -> list[Path]:
    return [Path(__file__).resolve(), ROOT / "A-EGS" / "egs_main.py",
            ROOT / "engine" / "egs_industry_heat.py", ROOT / "engine" / "a_short_industry_theme.py",
            ROOT / "engine" / "a_short_runtime_config.py", ROOT / "presets" / "a_short.yaml",
            ROOT / "presets" / "a_short_screening_threshold_governance_20260602.json",
            ROOT / "runners" / "a_short_theme_overlay_comparison.py",
            ROOT / "runners" / "a_short_factor_comparison_v2_cache_build.py",
            ROOT / "runners" / "a_short_weekly_pipeline.py",
            ROOT / "schemas" / "a_short_theme_overlay_comparison.schema.json",
            ROOT / "presets" / "egs_industry_heat_governance_20260611.json",
            PRIVATE_SCHEMA, PUBLIC_SCHEMA]


def _active_profile_binding() -> dict:
    """Bind the exact profile and weights that formed the official Stage3 run."""
    governance_path = ROOT / "presets" / "egs_industry_heat_governance_20260611.json"
    try:
        governance = _load(governance_path)
        profile = str(governance["active_profile"])
        weights = governance["profiles"][profile]
    except (KeyError, TypeError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OverlayAdjudicationError("P4a active industry profile is malformed") from exc
    if not isinstance(weights, dict) or not weights:
        raise OverlayAdjudicationError("P4a active industry profile weights are malformed")
    return {"active_profile": profile, "weights": weights,
            "governance_sha256": _heat.canonical_governance_digest(governance_path)}


def _screening_runtime_recipe_binding() -> dict:
    """Freeze the runtime authority that actually formed the EGS Stage3 pool."""
    try:
        lineage = runtime_configuration_lineage()
        policies = lineage["policies"]
        screening = [policy for policy in policies if policy.get("schema_name") == "a_short_screening_runtime_policy"]
        if len(screening) != 1:
            raise ValueError("screening policy lineage is not singular")
        policy = screening[0]
        if not all(isinstance(policy.get(key), str) and policy[key] for key in ("policy_id", "schema_version", "path", "sha256")):
            raise ValueError("screening policy lineage is incomplete")
    except Exception as exc:
        raise OverlayAdjudicationError("P4a active EGS screening runtime recipe is malformed") from exc
    return {"policy_id": policy["policy_id"], "schema_version": policy["schema_version"],
            "path": policy["path"], "sha256": policy["sha256"]}


def _epoch_context() -> dict:
    """Read every epoch-bearing dependency once and reuse that coherent snapshot.

    While the design is unfrozen the fingerprint is a stable pre-freeze constant
    (see ``engine/a_short_evidence_epoch_mode``): the whole-file hashes below
    invalidated every accumulated week on edits unrelated to this comparison.
    """
    admission = admission_snapshot(ADMISSION_ID)
    profile = _active_profile_binding()
    recipe = _screening_runtime_recipe_binding()
    def semantic_surface() -> dict[str, Any]:
        from engine import egs_industry_heat
        from engine import a_short_runtime_config
        return {
            "overlay_sources": _epoch_mode.semantic_module_contract(
                __import__(__name__, fromlist=["*"]),
                excluded_functions=P4A_SEMANTIC_MODULE_EXCLUSIONS,
            ),
            "industry_heat_sources": _epoch_mode.semantic_module_contract(egs_industry_heat),
            "runtime_configuration_source": _epoch_mode.semantic_function_contract(
                a_short_runtime_config, ("runtime_configuration_lineage",),
            ),
            "active_profile": _load(ROOT / "presets" / "egs_industry_heat_governance_20260611.json"),
            "screening_governance": _load(ROOT / "presets" / "a_short_screening_threshold_governance_20260602.json"),
            "schemas": {"private": _load(PRIVATE_SCHEMA), "public": _load(PUBLIC_SCHEMA),
                        "daily_cache": _load(DAILY_CACHE_SCHEMA)},
        }

    fingerprint = _epoch_mode.fingerprint_or_pre_freeze(
        "p4a_overlay_adjudication",
        lambda: _digest({"admission": admission, "active_profile_binding": profile,
                    "screening_runtime_recipe": recipe,
                    "semantic_surface": semantic_surface(),
                    "selection": {"top_k": TOP_K, "l1_max": 0.4, "l2_max": 0.3,
                                  "baseline": "final_score", "candidate": "overlay_score"},
                    "outcome": {"horizons": HORIZONS, "entry": "t_plus_1_open",
                                "qfq_provider_observed_only": True, "cost_pct": ROUND_TRIP_COST_PCT,
                                "cash_not_reallocated": True, "benchmarks": BENCHMARKS}}))
    return {"admission_binding": admission, "active_profile_binding": profile,
            "screening_runtime_recipe": recipe, "contract_fingerprint": fingerprint,
            "epoch_id": _epoch_id(fingerprint)}


def _contract_fingerprint() -> str:
    return _epoch_context()["contract_fingerprint"]


def _epoch_id(fingerprint: str) -> str:
    return _digest({"program_id": PROGRAM_ID, "contract_fingerprint": fingerprint})


def _week_paths(root: Path, decision_date: str) -> tuple[Path, Path]:
    directory = root / "weeks" / decision_date
    return directory / "capture.json", directory / "outcome.json"


def _records(root: Path) -> list[dict]:
    weeks = root / "weeks"
    if not weeks.exists():
        return []
    result = []
    for directory in sorted(path for path in weeks.iterdir() if path.is_dir()):
        capture = directory / "capture.json"
        if capture.exists():
            item = _load(capture)
            _validate_record(item)
            if item["decision_date"] != directory.name or item["record_type"] != "capture":
                raise OverlayAdjudicationError("P4a capture directory identity drifted")
            result.append(item)
    return result


def _current_records(root: Path, epoch_context: dict | None = None) -> list[dict]:
    context = epoch_context or _epoch_context()
    return [item for item in _records(root)
            if item["contract_fingerprint"] == context["contract_fingerprint"] and
            item["epoch_id"] == context["epoch_id"] and
            item.get("payload", {}).get("admission_binding") == context["admission_binding"] and
            item.get("payload", {}).get("active_industry_weight_profile") == context["active_profile_binding"] and
            item.get("payload", {}).get("screening_runtime_recipe") == context["screening_runtime_recipe"]]


def _validate_record(record: dict) -> None:
    try:
        jsonschema.validate(record, _load(PRIVATE_SCHEMA))
    except jsonschema.ValidationError as exc:
        raise OverlayAdjudicationError("P4a private record violates schema") from exc
    if record["boundary"] != _boundary():
        raise OverlayAdjudicationError("P4a private boundary drifted")
    if record["record_sha256"] != _record_digest(record):
        raise OverlayAdjudicationError("P4a private record integrity drifted")
    if record["epoch_id"] != _epoch_id(record["contract_fingerprint"]):
        raise OverlayAdjudicationError("P4a private record epoch/header binding drifted")
    if record["record_type"] == "capture":
        payload = record["payload"]
        if payload.get("captured_contract_fingerprint") != record["contract_fingerprint"] or \
                payload.get("captured_epoch_id") != record["epoch_id"]:
            raise OverlayAdjudicationError("P4a capture header/payload binding drifted")
        if not isinstance(payload.get("admission_binding"), dict) or \
                not isinstance(payload.get("active_industry_weight_profile"), dict) or \
                not isinstance(payload.get("screening_runtime_recipe"), dict):
            raise OverlayAdjudicationError("P4a capture epoch dependencies are malformed")
        frozen = {key: value for key, value in payload.items() if key != "capture_payload_sha256"}
        if payload.get("capture_payload_sha256") != _digest(frozen):
            raise OverlayAdjudicationError("P4a capture payload integrity drifted")
    elif record["record_type"] == "outcome":
        payload = record["payload"]
        if not isinstance(payload.get("capture_sha256"), str) or len(payload["capture_sha256"]) != 64:
            raise OverlayAdjudicationError("P4a outcome is missing its immutable capture binding")
        if not isinstance(payload.get("horizons"), dict):
            raise OverlayAdjudicationError("P4a outcome horizons are malformed")


def _require_member(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise OverlayAdjudicationError(f"P4a {label} member is malformed")
    required = ("ts_code", "final_score", "l1_name", "l2_name", "tier", "overheat_flag", "chasing_high")
    if any(key not in value for key in required) or not str(value.get("ts_code") or "") or not _finite(value.get("final_score")):
        raise OverlayAdjudicationError(f"P4a {label} lacks frozen Stage3 fields")
    result = {
        "ts_code": str(value["ts_code"]),
        "final_score": float(value["final_score"]),
        "l1_name": str(value["l1_name"]),
        "l2_name": str(value["l2_name"]),
        "tier": str(value["tier"]),
        "overheat_flag": require_known_risk_bool(
            value["overheat_flag"], f"P4a {label} overheat_flag", OverlayAdjudicationError
        ),
        "chasing_high": require_known_risk_bool(
            value["chasing_high"], f"P4a {label} chasing_high", OverlayAdjudicationError
        ),
    }
    if "overlay_score" in value:
        result["overlay_score"] = value["overlay_score"]
    return result


def _unique_members(rows: object, label: str) -> list[dict]:
    if not isinstance(rows, list):
        raise OverlayAdjudicationError(f"P4a {label} must be a list")
    values = [_require_member(row, label) for row in rows]
    if len({row["ts_code"] for row in values}) != len(values):
        raise OverlayAdjudicationError(f"P4a {label} has duplicate symbols")
    return values


def select_stage3_top5(eligible_pool: list[dict], rank_source: str) -> list[dict]:
    """Pure Stage3 Top5 selector: same pool, ordering source, concentration and truncation.

    The stable input order is retained as the production tie-break.  This is
    why a baseline result can be compared byte-for-byte with ``tier1_final``.
    """
    if rank_source not in {"final_score", "overlay_score"}:
        raise OverlayAdjudicationError("P4a rank source is not admitted")
    rows = _unique_members(eligible_pool, "eligible pool")
    normalised = []
    for index, row in enumerate(rows):
        copy = dict(row)
        if rank_source == "overlay_score":
            if not _finite(row.get("overlay_score")):
                raise OverlayAdjudicationError("P4a overlay score is missing or non-finite")
            copy["overlay_score"] = float(row["overlay_score"])
        normalised.append(copy)
    order = {row["ts_code"]: index for index, row in enumerate(rows)}
    normalised.sort(key=lambda row: (-float(row[rank_source]), order[row["ts_code"]]))
    selected: list[dict] = []; l1_counts: dict[str, int] = {}; l2_counts: dict[str, int] = {}
    for row in normalised:
        l1 = row["l1_name"]; l2 = row["l2_name"]; l1_key = l2 if l1 in {"未知", "unknown", ""} else l1
        denominator = max(len(selected), 1)
        if l1_counts.get(l1_key, 0) / denominator > 0.4 or l2_counts.get(l2, 0) / denominator > 0.3:
            continue
        selected.append(row); l1_counts[l1_key] = l1_counts.get(l1_key, 0) + 1; l2_counts[l2] = l2_counts.get(l2, 0) + 1
        if len(selected) == TOP_K:
            break
    return selected


def _verify_weekly_receipt(out_path: str | Path, receipt_path: str | Path, decision_date: str,
                           run_date: str, source_identity: dict):
    out, receipt_file = Path(out_path).resolve(), Path(receipt_path).resolve()
    expected_receipt = out.with_suffix("").with_suffix(".receipt.json")
    if out.name != "weekly_m67.json" or receipt_file != expected_receipt:
        raise OverlayAdjudicationError("P4a requires the canonical complete weekly_m67 JSON/Markdown/receipt bundle")
    try:
        from runners.a_short_weekly_pipeline import validate_published_weekly_bundle
        bundle = validate_published_weekly_bundle(out, receipt_file)
    except (OSError, ValueError) as exc:
        raise OverlayAdjudicationError(
            "P4a requires the canonical complete weekly_m67 JSON/Markdown/receipt bundle"
        ) from exc
    weekly, receipt = bundle.weekly, bundle.receipt
    lineage = weekly.get("run_lineage") or {}
    if weekly.get("as_of") != decision_date:
        raise OverlayAdjudicationError("P4a requires a complete same-date M6.7 publish receipt")
    if not _published_on_run_date(receipt.get("published_at"), run_date, "M6.7 receipt"):
        raise OverlayAdjudicationError("P4a M6.7 receipt is not published on the live run date")
    for field in ("run_id", "candidate_digest"):
        if not source_identity.get(field) or lineage.get(field) != source_identity.get(field) or \
                receipt.get(field) != source_identity.get(field):
            raise OverlayAdjudicationError(f"P4a M6.7 receipt {field} identity drifted")
    freshness = lineage.get("price_freshness") or {}
    if freshness.get("run_date") != run_date or freshness.get("mode") not in {"strict_as_of", "intraday_prior_settled"} or \
            str(freshness.get("price_data_through") or "") > decision_date:
        raise OverlayAdjudicationError("P4a M6.7 live price/PIT lineage drifted")
    if freshness.get("mode") == "strict_as_of" and freshness.get("price_data_through") != decision_date:
        raise OverlayAdjudicationError("P4a strict-as-of M6.7 lineage is not same-date")
    return bundle


def _file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _published_on_run_date(value: object, run_date: str, label: str) -> bool:
    try:
        return datetime.fromisoformat(str(value)).strftime("%Y%m%d") == run_date
    except ValueError:
        raise OverlayAdjudicationError(f"P4a {label} published_at is malformed") from None


def _verify_egs_publish_marker(marker_path: str | Path, stage3_snapshot_path: str | Path,
                               overlay_path: str | Path, decision_date: str,
                               source_identity: dict, weekly: dict, run_date: str) -> dict:
    """Require the official EGS marker to bind the exact P4 sidecar bytes."""
    marker_file = Path(marker_path).resolve()
    stage3_file, overlay_file = Path(stage3_snapshot_path).resolve(), Path(overlay_path).resolve()
    if marker_file.name != "official_publish.json" or stage3_file.parent != marker_file.parent or \
            overlay_file.parent != marker_file.parent:
        raise OverlayAdjudicationError("P4a official marker and sidecars must be one canonical EGS bundle")
    marker = _load(marker_file)
    if not isinstance(marker, dict) or marker.get("schema_name") != "a_short_egs_official_publish" or \
            marker.get("stage_status") != "complete" or marker.get("trade_date") != decision_date:
        raise OverlayAdjudicationError("P4a requires a complete same-date official EGS publish marker")
    if not _published_on_run_date(marker.get("published_at"), run_date, "official EGS marker"):
        raise OverlayAdjudicationError("P4a official EGS marker is not published on the live run date")
    if marker.get("run_id") != source_identity.get("run_id") or marker.get("candidate_digest") != source_identity.get("candidate_digest"):
        raise OverlayAdjudicationError("P4a official EGS marker run identity drifted")
    weekly_candidate = (weekly.get("run_lineage") or {}).get("candidate_digest")
    if not weekly_candidate or marker.get("candidate_digest") != weekly_candidate:
        raise OverlayAdjudicationError("P4a EGS/M6.7 candidate identity drifted")
    files = marker.get("files")
    if not isinstance(files, dict):
        raise OverlayAdjudicationError("P4a official EGS marker lacks file receipts")
    for role, path, expected_name in (("p4_stage3_selection_snapshot", stage3_file, "stage3_selection_snapshot.json"),
                                      ("p4_stage3_overlay_score", overlay_file, "stage3_overlay_score.json")):
        receipt = files.get(role)
        if not isinstance(receipt, dict) or receipt.get("path") != expected_name or path.name != expected_name or \
                receipt.get("sha256") != _file_sha256(path):
            raise OverlayAdjudicationError(f"P4a official EGS marker does not bind {role}")
    return marker


def _stage3_payload(stage3_snapshot: dict, overlay: dict, decision_date: str, source_identity: dict,
                    active_profile_binding: dict, screening_runtime_recipe: dict) -> tuple[list[dict], list[dict], list[dict], dict]:
    if not isinstance(stage3_snapshot, dict) or stage3_snapshot.get("as_of") != decision_date:
        raise OverlayAdjudicationError("P4a Stage3 snapshot must bind the canonical decision date")
    if not isinstance(source_identity, dict) or not source_identity.get("run_id") or \
            stage3_snapshot.get("run_id") != source_identity.get("run_id") or \
            stage3_snapshot.get("candidate_digest") != source_identity.get("candidate_digest"):
        raise OverlayAdjudicationError("P4a Stage3 snapshot run identity mismatch")
    stored_profile_binding = stage3_snapshot.get("active_industry_weight_profile")
    if not isinstance(stored_profile_binding, dict) or not isinstance(active_profile_binding, dict) or \
            set(stored_profile_binding) != set(active_profile_binding) or \
            any(stored_profile_binding.get(key) != active_profile_binding.get(key)
                for key in ("active_profile", "weights")):
        raise OverlayAdjudicationError("P4a Stage3 snapshot active-profile binding drifted")
    stored_digest = stored_profile_binding.get("governance_sha256")
    expected_digest = active_profile_binding.get("governance_sha256")
    if not _is_sha256(stored_digest) or not _is_sha256(expected_digest) or \
            (_epoch_mode.enforcement_enabled("p4a_overlay_adjudication") and stored_digest != expected_digest):
        raise OverlayAdjudicationError("P4a Stage3 snapshot active-profile binding drifted")
    if stage3_snapshot.get("screening_runtime_recipe") != screening_runtime_recipe:
        raise OverlayAdjudicationError("P4a Stage3 snapshot screening-runtime recipe binding drifted")
    top50 = _unique_members(stage3_snapshot.get("top50"), "official top50")
    eligible = _unique_members(stage3_snapshot.get("stage3_eligible_pool"), "Stage3 eligible pool")
    if not {row["ts_code"] for row in eligible}.issubset({row["ts_code"] for row in top50}):
        raise OverlayAdjudicationError("P4a eligible pool is not a subset of the official top50")
    official = _unique_members(stage3_snapshot.get("official_tier1_final"), "official tier1_final")
    baseline = select_stage3_top5(eligible, "final_score")
    if [row["ts_code"] for row in baseline] != [row["ts_code"] for row in official]:
        raise OverlayAdjudicationError("P4a baseline does not exactly reproduce official tier1_final member/order/shortness")
    if not isinstance(overlay, dict) or overlay.get("as_of") != decision_date or overlay.get("track") != "comparison_non_production":
        raise OverlayAdjudicationError("P4a overlay source is not a same-run comparison-only artifact")
    boundary = overlay.get("boundary") or {}
    if boundary.get("production") is not False or boundary.get("automatic_promotion") is not False:
        raise OverlayAdjudicationError("P4a overlay source claims a production effect")
    score_by_code = {str(row.get("ts_code") or ""): row.get("overlay_score") for row in overlay.get("candidates") or []}
    if not all(code in score_by_code and _finite(score_by_code[code]) for code in (row["ts_code"] for row in eligible)):
        raise OverlayAdjudicationError("P4a overlay cannot rescue excluded rows or omit an eligible row")
    candidate_pool = [dict(row, overlay_score=float(score_by_code[row["ts_code"]])) for row in eligible]
    candidate = select_stage3_top5(candidate_pool, "overlay_score")
    return top50, eligible, baseline, {"candidate": candidate, "overlay_digest": _digest(overlay),
                                       "stage3_snapshot_digest": _digest(stage3_snapshot)}


def capture_after_published_weekly(*, root: str | Path, decision_date: str, run_date: str,
                                   stage3_snapshot_path: str | Path, overlay_path: str | Path,
                                   out_path: str | Path, receipt_path: str | Path,
                                   egs_publish_marker_path: str | Path,
                                   source_identity: dict, forward_eligible: bool) -> dict:
    """Freeze one post-publication P4a observation; historical inputs never start its clock."""
    decision_date, run_date = _date(decision_date, "decision_date"), _date(run_date, "run_date")
    if not forward_eligible or run_date != _today() or decision_date < run_date:
        return {"status": "not_live_canonical_no_capture", "production_unchanged": True}
    if not isinstance(source_identity, dict) or not source_identity.get("run_id") or not source_identity.get("candidate_digest"):
        raise OverlayAdjudicationError("P4a source identity must bind run_id and candidate_digest")
    private_root = _root(root)
    # The profile in the published Stage3 snapshot and the epoch header must
    # be judged against this one immutable configuration read.
    epoch_context = _epoch_context()
    weekly_bundle = _verify_weekly_receipt(
        out_path, receipt_path, decision_date, run_date, source_identity
    )
    weekly = weekly_bundle.weekly
    price_data_through = str(((weekly.get("run_lineage") or {}).get("price_freshness") or {}).get("price_data_through") or "")
    if not price_data_through:
        raise OverlayAdjudicationError("P4a M6.7 bundle lacks the canonical price_data_through clock")
    marker = _verify_egs_publish_marker(egs_publish_marker_path, stage3_snapshot_path, overlay_path,
                                        decision_date, source_identity, weekly, run_date)
    top50, eligible, baseline, candidate_data = _stage3_payload(
        _load(stage3_snapshot_path), _load(overlay_path), decision_date, source_identity,
        epoch_context["active_profile_binding"], epoch_context["screening_runtime_recipe"])
    fingerprint, epoch = epoch_context["contract_fingerprint"], epoch_context["epoch_id"]
    payload = {"admission_binding": epoch_context["admission_binding"], "run_date": run_date,
                "run_id": source_identity["run_id"],
                "weekly_bundle_sha256": weekly_bundle.weekly_sha256,
                "weekly_receipt_digest": _digest(weekly_bundle.receipt),
               "egs_publish_marker_digest": _digest(marker),
               "weekly_candidate_digest": (weekly.get("run_lineage") or {}).get("candidate_digest"),
               "top50_digest": _digest(top50), "eligible_pool_digest": _digest(eligible),
               "stage3_snapshot_digest": candidate_data["stage3_snapshot_digest"], "overlay_digest": candidate_data["overlay_digest"],
               "baseline_selected": baseline, "candidate_selected": candidate_data["candidate"],
                "same_list": {row["ts_code"] for row in baseline} == {row["ts_code"] for row in candidate_data["candidate"]} and
                             len(baseline) == len(candidate_data["candidate"]),
                "forward_eligible": True,
                "active_industry_weight_profile": epoch_context["active_profile_binding"],
               "screening_runtime_recipe": epoch_context["screening_runtime_recipe"],
               "captured_contract_fingerprint": fingerprint, "captured_epoch_id": epoch,
               "price_request": {"price_data_through": price_data_through, "qfq_provider_observed_only": True,
                                 "benchmarks": list(BENCHMARKS)},
               "capture_payload_sha256": ""}
    payload["capture_payload_sha256"] = _digest({key: value for key, value in payload.items() if key != "capture_payload_sha256"})
    record = _seal_record({"schema_name": "a_short_overlay_adjudication_private_record", "schema_version": "1.0.0",
              "record_type": "capture", "program_id": PROGRAM_ID, "decision_date": decision_date,
              "epoch_id": epoch, "contract_fingerprint": fingerprint, "payload": payload, "boundary": _boundary()})
    _validate_record(record); capture_path, _ = _week_paths(private_root, decision_date)
    if capture_path.exists():
        existing = _load(capture_path)
        _validate_record(existing)
        if existing == record:
            return {"status": "idempotent_existing_capture", "production_unchanged": True}
        conflict = _seal_record({"schema_name": "a_short_overlay_adjudication_private_record", "schema_version": "1.0.0",
                    "record_type": "conflict", "program_id": PROGRAM_ID, "decision_date": decision_date,
                    "epoch_id": existing.get("epoch_id", epoch), "contract_fingerprint": existing.get("contract_fingerprint", fingerprint),
                    "payload": {"reason": "same_canonical_week_content_drift_no_overwrite"}, "boundary": _boundary()})
        _write(private_root / "conflicts" / f"{decision_date}.json", conflict)
        return {"status": "conflict_recorded_no_count", "reason_code": "immutable_capture_conflict",
                "production_unchanged": True}
    _write(capture_path, record); _refresh_ledger(private_root)
    return {"status": "captured_live_canonical", "production_unchanged": True}


def cache_consumer_windows(*, root: str | Path, run_date: str) -> list[dict]:
    private_root, run_date = _root(root), _date(run_date, "run_date")
    windows = []
    epoch_context = _epoch_context()
    for capture in _current_records(private_root, epoch_context):
        if capture["decision_date"] > run_date:
            continue
        selected = capture["payload"]["baseline_selected"] + capture["payload"]["candidate_selected"]
        windows.append({"consumer_id": "p4_overlay_adjudication", "decision_date": capture["decision_date"],
                        "price_data_through": capture["payload"]["price_request"]["price_data_through"],
                        "window_mode": "managed_exit", "pre_history_days": 0, "horizon_days": 20,
                        "symbols": sorted({row["ts_code"] for row in selected}), "benchmarks": list(BENCHMARK_CODES.values())})
    return windows


def _validate_shared_daily_cache(payload: dict, as_of: str) -> None:
    """Reject replay/future/hand-built evidence before it can settle a P4 week."""
    try:
        jsonschema.validate(payload, _load(DAILY_CACHE_SCHEMA))
    except jsonschema.ValidationError as exc:
        raise OverlayAdjudicationError("P4a shared daily cache violates its frozen schema") from exc
    meta = payload.get("meta") or {}
    if payload.get("schema_version") != "1.1.0" or meta.get("cache_kind") != "a_short_shared_incremental" or \
            meta.get("writer") != "runners/a_short_factor_comparison_v2_cache_build.py" or \
            meta.get("last_run_date") != as_of or "p4_overlay_adjudication" not in (meta.get("consumers") or []) or \
            not isinstance(meta.get("provider_call_ceiling"), int) or meta["provider_call_ceiling"] > 91:
        raise OverlayAdjudicationError("P4a requires the current bounded single-writer shared daily cache")
    if as_of != _today():
        raise OverlayAdjudicationError("P4a settlement accepts only the real current canonical date")
    for group in ("stocks", "limits", "benchmarks", "rows"):
        for row in payload.get(group) or []:
            if _date(row.get("trade_date"), f"{group} trade_date") > as_of:
                raise OverlayAdjudicationError("P4a shared cache contains future-dated evidence")


def _cache_frames(payload: dict) -> tuple[dict, dict, dict, list[str]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("stocks"), list) or not isinstance(payload.get("limits"), list):
        raise OverlayAdjudicationError("P4a shared daily cache is malformed")
    def index(rows: object, required: tuple[str, ...], label: str) -> dict:
        if not isinstance(rows, list):
            raise OverlayAdjudicationError(f"P4a cache {label} is absent")
        out = {}
        for row in rows:
            if not isinstance(row, dict) or any(key not in row for key in required):
                raise OverlayAdjudicationError(f"P4a cache {label} row is malformed")
            key = (str(row["ts_code"]), _date(row["trade_date"], "cache trade_date"))
            if key in out and out[key] != row:
                raise OverlayAdjudicationError(f"P4a cache {label} has conflicting row")
            out[key] = row
        return out
    stocks = index(payload["stocks"], ("ts_code", "trade_date"), "stocks")
    limits = index(payload["limits"], ("ts_code", "trade_date"), "limits")
    benchmarks = index(payload.get("benchmarks", []), ("ts_code", "trade_date"), "benchmarks")
    return stocks, limits, benchmarks, sorted({date for _, date in stocks})


def _qfq(row: dict, field: str) -> float | None:
    if row.get("adj_factor_observed") is not True or row.get("adj_factor_source") != "provider_observed" or not _finite(row.get("adj_factor")) or float(row["adj_factor"]) <= 0 or not _finite(row.get(field)):
        return None
    return float(row[field]) * float(row["adj_factor"])


def _arm_return(selected: list[dict], decision_date: str, horizon: int, dates: list[str], date_pos: dict[str, int], stocks: dict, limits: dict) -> dict:
    if decision_date not in date_pos or date_pos[decision_date] + horizon >= len(dates):
        return {"status": "pending"}
    entry_date, exit_date = dates[date_pos[decision_date] + 1], dates[date_pos[decision_date] + horizon]
    positions, daily_nav, slot_returns = [], [], []
    for member in selected:
        code = member["ts_code"]; entry = stocks.get((code, entry_date)); exit_row = stocks.get((code, exit_date)); limit = limits.get((code, entry_date))
        if entry is None or exit_row is None or limit is None:
            return {"status": "no_count", "reason": "missing_required_cache_row"}
        entry_qfq, exit_qfq = _qfq(entry, "open"), _qfq(exit_row, "close")
        if entry_qfq is None or exit_qfq is None or not _finite(limit.get("up_limit")):
            return {"status": "no_count", "reason": "qfq_adjustment_or_limit_unverified"}
        unfilled = bool(entry.get("suspended")) or float(entry["open"]) >= float(limit["up_limit"]) * 0.999
        net = 0.0 if unfilled else (exit_qfq / entry_qfq - 1.0) * 100.0 - ROUND_TRIP_COST_PCT
        positions.append({"ts_code": code, "entry_status": "cash" if unfilled else "filled", "net_return_pct": net})
        slot_returns.append(net)
    cash_slots = TOP_K - len(selected) + sum(1 for row in positions if row["entry_status"] == "cash")
    portfolio = sum(slot_returns) / TOP_K
    # Daily close NAV is retained only privately and uses the same fixed slots.
    for date in dates[date_pos[decision_date] + 1:date_pos[decision_date] + horizon + 1]:
        value = 0.0
        for member, position in zip(selected, positions):
            if position["entry_status"] == "cash":
                continue
            row = stocks.get((member["ts_code"], date)); close = _qfq(row, "close") if row else None
            entry = _qfq(stocks[(member["ts_code"], entry_date)], "open")
            if close is None or entry is None:
                return {"status": "no_count", "reason": "missing_daily_nav_price"}
            value += (close / entry - 1.0) * 100.0 / TOP_K
        daily_nav.append(value)
    peak = 0.0; drawdown = 0.0
    for nav in daily_nav:
        peak = max(peak, nav); drawdown = min(drawdown, nav - peak)
    return {"status": "settled", "entry_date": entry_date, "exit_date": exit_date, "portfolio_net_return_pct": portfolio,
            "cash_drag_pct": cash_slots / TOP_K * 100.0, "unfilled_rate_pct": sum(row["entry_status"] == "cash" for row in positions) / TOP_K * 100.0,
            "close_drawdown_pct": drawdown, "positions": positions, "daily_close_nav_pct": daily_nav}


def _benchmark_return(code: str, decision_date: str, horizon: int, dates: list[str], date_pos: dict[str, int], benchmarks: dict) -> dict:
    if decision_date not in date_pos or date_pos[decision_date] + horizon >= len(dates):
        return {"status": "pending"}
    entry_date, exit_date = dates[date_pos[decision_date] + 1], dates[date_pos[decision_date] + horizon]
    entry, exit_row = benchmarks.get((code, entry_date)), benchmarks.get((code, exit_date))
    if entry is None or exit_row is None or entry.get("provider_observed") is not True or exit_row.get("provider_observed") is not True or not _finite(entry.get("open")) or not _finite(exit_row.get("close")) or float(entry["open"]) <= 0:
        return {"status": "no_count", "reason": "benchmark_provider_observed_price_missing"}
    return {"status": "settled", "net_return_pct": (float(exit_row["close"]) / float(entry["open"]) - 1.0) * 100.0}


def _terminal_status(item: object) -> bool:
    return isinstance(item, dict) and item.get("status") in {"settled", "no_count"}


def _terminal_equivalent(old: dict, new: dict) -> bool:
    """The first terminal return remains the evidence; later cache growth cannot rewrite it."""
    return {key: value for key, value in old.items() if key != "source_cache_sha256"} == \
        {key: value for key, value in new.items() if key != "source_cache_sha256"}


def _write_immutable_conflict(root: Path, capture: dict, reason: str) -> None:
    path = root / "conflicts" / f"{capture['decision_date']}.json"
    if path.exists():
        return
    _write(path, _seal_record({"schema_name": "a_short_overlay_adjudication_private_record", "schema_version": "1.0.0",
                  "record_type": "conflict", "program_id": PROGRAM_ID, "decision_date": capture["decision_date"],
                  "epoch_id": capture["epoch_id"], "contract_fingerprint": capture["contract_fingerprint"],
                  "payload": {"reason": reason}, "boundary": _boundary()}))


def settle_from_daily_payload(*, root: str | Path, daily_payload: dict, as_of: str,
                              cache_path: str | Path | None = None, epoch_context: dict | None = None) -> dict:
    private_root, as_of = _root(root), _date(as_of, "as_of")
    if cache_path is not None and Path(cache_path).resolve().name != "daily_cache.json":
        raise OverlayAdjudicationError("P4a settlement cache must be the canonical daily_cache.json artifact")
    _validate_shared_daily_cache(daily_payload, as_of)
    stocks, limits, benchmarks, available_dates = _cache_frames(daily_payload)
    dates = [day for day in available_dates if day <= as_of]; date_pos = {day: index for index, day in enumerate(dates)}; changed = 0
    cache_sha256 = _digest(daily_payload); context = epoch_context or _epoch_context()
    for capture in _current_records(private_root, context):
        if capture["decision_date"] > as_of:
            continue
        conflict = private_root / "conflicts" / f"{capture['decision_date']}.json"; horizons = {}
        for horizon in HORIZONS:
            if conflict.exists():
                horizons[f"h{horizon}"] = {"status": "no_count", "reason": "immutable_capture_conflict"}; continue
            baseline = _arm_return(capture["payload"]["baseline_selected"], capture["decision_date"], horizon, dates, date_pos, stocks, limits)
            candidate = _arm_return(capture["payload"]["candidate_selected"], capture["decision_date"], horizon, dates, date_pos, stocks, limits)
            bench = {name: _benchmark_return(code, capture["decision_date"], horizon, dates, date_pos, benchmarks) for name, code in BENCHMARK_CODES.items()}
            if baseline["status"] == "pending" or candidate["status"] == "pending" or any(row["status"] == "pending" for row in bench.values()):
                horizons[f"h{horizon}"] = {"status": "pending"}; continue
            if baseline["status"] != "settled" or candidate["status"] != "settled" or any(row["status"] != "settled" for row in bench.values()):
                reason = baseline.get("reason") or candidate.get("reason") or next((row.get("reason") for row in bench.values() if row.get("reason")), "missing_price")
                horizons[f"h{horizon}"] = {"status": "no_count", "reason": reason}; continue
            delta = 0.0 if capture["payload"]["same_list"] else candidate["portfolio_net_return_pct"] - baseline["portfolio_net_return_pct"]
            horizons[f"h{horizon}"] = {"status": "settled", "delta_pct": delta, "same_list_zero_effect": bool(capture["payload"]["same_list"]),
                                         "baseline": baseline, "candidate": candidate, "source_cache_sha256": cache_sha256,
                                         "benchmarks": {name: {"baseline_excess_pct": baseline["portfolio_net_return_pct"] - row["net_return_pct"], "candidate_excess_pct": candidate["portfolio_net_return_pct"] - row["net_return_pct"]} for name, row in bench.items()}}
            
        _, path = _week_paths(private_root, capture["decision_date"])
        existing = _load(path) if path.exists() else None
        if existing is not None:
            _validate_record(existing)
            if existing["decision_date"] != capture["decision_date"] or \
                    existing["epoch_id"] != capture["epoch_id"] or \
                    existing["contract_fingerprint"] != capture["contract_fingerprint"] or \
                    existing.get("payload", {}).get("capture_sha256") != _digest(capture):
                _write_immutable_conflict(private_root, capture, "outcome_capture_identity_drift_no_overwrite")
                continue
            old_horizons = existing.get("payload", {}).get("horizons") or {}
            terminal_drift = any(_terminal_status(old_horizons.get(key)) and
                                 not _terminal_equivalent(old_horizons[key], value)
                                 for key, value in horizons.items())
            if terminal_drift:
                _write_immutable_conflict(private_root, capture, "mature_horizon_content_drift_no_overwrite")
                continue
            horizons = {key: old_horizons[key] if _terminal_status(old_horizons.get(key)) else value
                        for key, value in horizons.items()}
        outcome = _seal_record({"schema_name": "a_short_overlay_adjudication_private_record", "schema_version": "1.0.0", "record_type": "outcome", "program_id": PROGRAM_ID,
                   "decision_date": capture["decision_date"], "epoch_id": capture["epoch_id"], "contract_fingerprint": capture["contract_fingerprint"],
                    "payload": {"capture_sha256": _digest(capture), "cache_sha256": cache_sha256,
                                "settled_through": max(as_of, str((existing or {}).get("payload", {}).get("settled_through") or "")),
                                "horizons": horizons}, "boundary": _boundary()})
        _validate_record(outcome)
        if not path.exists() or _load(path) != outcome:
            _write(path, outcome); changed += 1
    _refresh_ledger(private_root)
    return {"status": "settled_from_existing_cache", "outcomes_updated": changed, "production_unchanged": True}


def _block_rows(rows: list[dict]) -> list[dict]:
    blocks = []; last_exit = ""
    for row in rows:
        item = row["h10"]
        if item["baseline"]["entry_date"] > last_exit:
            blocks.append(row); last_exit = item["baseline"]["exit_date"]
    return blocks


def _bootstrap_bounds(values: list[float]) -> tuple[float | None, float | None]:
    if not values: return None, None
    rng = random.Random(0); samples = sorted(mean([rng.choice(values) for _ in values]) for _ in range(2000))
    return samples[int(0.025 * (len(samples) - 1))], samples[int(0.975 * (len(samples) - 1))]


def _signflip_p(values: list[float]) -> float | None:
    if not values: return None
    observed = abs(sum(values)); rng = random.Random(1); trials = 32768 if len(values) > 15 else 1 << len(values); hits = 0
    for index in range(trials):
        signs = ((1 if (index >> position) & 1 else -1) for position in range(len(values))) if len(values) <= 15 else (rng.choice((-1, 1)) for _ in values)
        if abs(sum(value * sign for value, sign in zip(values, signs))) >= observed - 1e-12: hits += 1
    return hits / trials


def _monthly_cluster_t(rows: list[dict]) -> tuple[float | None, int]:
    """Intercept-only weekly paired-difference t, one-way clustered by YYYYMM."""
    groups: dict[str, list[float]] = {}
    for row in rows: groups.setdefault(row["decision_date"][:6], []).append(row["h10"]["delta_pct"])
    values = [float(value) for group in groups.values() for value in group]
    cluster_count, sample_count = len(groups), len(values)
    if cluster_count < 2 or sample_count < 2:
        return None, cluster_count
    intercept = mean(values)
    cluster_scores = [sum(value - intercept for value in group) for group in groups.values()]
    # CR1 small-sample correction for an intercept-only one-way cluster model.
    variance = (cluster_count / (cluster_count - 1)) * sum(score ** 2 for score in cluster_scores) / (sample_count ** 2)
    if variance <= 0:
        return (float("inf") if intercept > 0 else float("-inf") if intercept < 0 else 0.0), cluster_count
    return intercept / math.sqrt(variance), cluster_count


def _risk_metrics(rows: list[dict]) -> dict:
    """Compute P4a's frozen portfolio-level risk gates from private outcomes."""
    if not rows:
        return {"complete": False, "risk_ok": False}
    baseline, candidate = [], []
    for row in rows:
        h10 = row["h10"]
        baseline.extend(value for value in h10["baseline"]["positions"] if value.get("entry_status") == "filled")
        candidate.extend(value for value in h10["candidate"]["positions"] if value.get("entry_status") == "filled")
    if not baseline or not candidate:
        return {"complete": False, "risk_ok": False, "reason": "actual_filled_stock_evidence_unavailable"}
    def rate(values: list[dict], predicate) -> float:
        return 100.0 * sum(bool(predicate(value)) for value in values) / max(len(values), 1)
    def tail(values: list[dict]) -> float:
        numbers = sorted(float(value["net_return_pct"]) for value in values)
        return mean(numbers[:max(1, math.ceil(len(numbers) * .20))]) if numbers else float("-inf")
    baseline_dd = min(row["h10"]["baseline"]["close_drawdown_pct"] for row in rows)
    candidate_dd = min(row["h10"]["candidate"]["close_drawdown_pct"] for row in rows)
    base_bad, candidate_bad = rate(baseline, lambda value: value["net_return_pct"] <= -5.0), rate(candidate, lambda value: value["net_return_pct"] <= -5.0)
    base_tail, candidate_tail = tail(baseline), tail(candidate)
    base_false, candidate_false = [], []
    for row in rows:
        bmap = {value["ts_code"]: value for value in row["h10"]["baseline"]["positions"] if value.get("entry_status") == "filled"}
        cmap = {value["ts_code"]: value for value in row["h10"]["candidate"]["positions"] if value.get("entry_status") == "filled"}
        base_false.extend(value for code, value in cmap.items() if code not in bmap)
        candidate_false.extend(value for code, value in bmap.items() if code not in cmap)
    base_fn = rate(base_false, lambda value: value["net_return_pct"] > 0.0)
    candidate_fn = rate(candidate_false, lambda value: value["net_return_pct"] > 0.0)
    candidate_excess_ok = all(mean(row["h10"]["benchmarks"][name]["candidate_excess_pct"] for row in rows) >= 0.0 for name in BENCHMARKS)
    h5_coverage_ok = all(row.get("h5_complete") is True for row in rows)
    h5 = [row["h5"]["delta_pct"] for row in rows if row.get("h5_complete") is True]
    h20 = [row["h20"]["delta_pct"] for row in rows if row["h20"].get("status") == "settled"]
    h5_h20_not_both_adverse = not (h5 and h20 and mean(h5) <= -.25 and mean(h20) <= -.25)
    candidate_cash = mean(row["h10"]["candidate"]["cash_drag_pct"] for row in rows)
    candidate_unfilled = mean(row["h10"]["candidate"]["unfilled_rate_pct"] for row in rows)
    metrics = {
        "complete": True, "candidate_excess_ok": candidate_excess_ok,
        "candidate_drawdown_pct": candidate_dd, "baseline_drawdown_pct": baseline_dd,
        "drawdown_ok": candidate_dd >= -15.0 and candidate_dd - baseline_dd >= -2.0,
        "candidate_bad_ticket_rate_pct": candidate_bad, "baseline_bad_ticket_rate_pct": base_bad,
        "bad_ticket_ok": candidate_bad <= 35.0 and candidate_bad - base_bad <= 5.0,
        "candidate_tail_pct": candidate_tail, "baseline_tail_pct": base_tail,
        "tail_ok": candidate_tail >= -10.0 and candidate_tail - base_tail >= -2.0,
        "candidate_false_negative_rate_pct": candidate_fn, "baseline_false_negative_rate_pct": base_fn,
        "false_negative_ok": candidate_fn - base_fn <= 5.0,
        "candidate_cash_drag_pct": candidate_cash, "candidate_unfilled_rate_pct": candidate_unfilled,
        "cash_ok": candidate_cash <= 50.0 and candidate_unfilled <= 50.0,
        "h5_coverage_ok": h5_coverage_ok,
        "h5_h20_not_both_adverse": h5_h20_not_both_adverse,
    }
    metrics["risk_ok"] = all(metrics[key] for key in (
        "candidate_excess_ok", "drawdown_ok", "bad_ticket_ok", "tail_ok", "false_negative_ok", "cash_ok", "h5_h20_not_both_adverse",
    ))
    return metrics


def _statistical_contract() -> dict:
    """Read P4a's complete statistical policy from its sealed admission only."""
    try:
        statistical = get_admission(ADMISSION_ID)["statistical_contract"]["definition"]
        preliminary = statistical["preliminary"]
        promotion = statistical["promotion"]
        negative_at_36 = statistical["negative_at_36"]
    except (KeyError, TypeError, ValueError) as exc:
        raise OverlayAdjudicationError("P4a statistical contract is malformed") from exc
    required_numbers = (
        (preliminary, "mean_delta_pp_min", 0.0), (preliminary, "block_win_rate_min", 0.0),
        (preliminary, "negative_mean_delta_pp_max", None),
        (promotion, "mean_delta_pp_min", 0.0), (promotion, "bootstrap_lower_pp_min", 0.0),
        (promotion, "signflip_p_max", 0.0), (promotion, "monthly_cluster_t_min", 0.0),
        (promotion, "no_count_rate_pct_max", 0.0),
        (negative_at_36, "mean_delta_pp_max", None), (negative_at_36, "bootstrap_upper_pp_max", None),
    )
    if (not isinstance(statistical, dict) or any(not isinstance(section, dict) or type(section.get(key)) not in (int, float)
                                                   or not math.isfinite(float(section[key]))
                                                   or (minimum is not None and float(section[key]) <= minimum)
                                                   for section, key, minimum in required_numbers)
            or preliminary["negative_mean_delta_pp_max"] >= 0
            or negative_at_36["mean_delta_pp_max"] >= 0
            or negative_at_36["bootstrap_upper_pp_max"] > 0
            or promotion["signflip_p_max"] > 1
            or type(promotion.get("minimum_months")) is not int or promotion["minimum_months"] <= 0):
        raise OverlayAdjudicationError("P4a statistical contract is malformed")
    return statistical


def _checkpoint_contract(statistical: dict | None = None) -> tuple[tuple[int, int, int], ...]:
    """Read P4a's complete checkpoint gates from its sealed admission only."""
    statistical = _statistical_contract() if statistical is None else statistical
    try:
        checkpoints = statistical["eligible_checkpoints"]
        difference_minimums = statistical["difference_minimums"]
        block_minimums = statistical["nonoverlap_block_minimums"]
    except (KeyError, TypeError, ValueError) as exc:
        raise OverlayAdjudicationError("P4a checkpoint contract is malformed") from exc
    if (not isinstance(checkpoints, list) or len(checkpoints) != 3
            or any(type(value) is not int or value <= 0 for value in checkpoints)
            or checkpoints != sorted(checkpoints)):
        raise OverlayAdjudicationError("P4a checkpoint contract is malformed")
    keys = {str(value) for value in checkpoints}
    if (not isinstance(difference_minimums, dict) or not isinstance(block_minimums, dict)
            or set(difference_minimums) != keys or set(block_minimums) != keys
            or any(type(value) is not int or value <= 0 for value in difference_minimums.values())
            or any(type(value) is not int or value <= 0 for value in block_minimums.values())):
        raise OverlayAdjudicationError("P4a checkpoint contract is malformed")
    return tuple((checkpoint, difference_minimums[str(checkpoint)], block_minimums[str(checkpoint)])
                 for checkpoint in checkpoints)


def _adjudicate(rows: list[dict], mature: int, no_count: int) -> tuple[str, dict]:
    eligible, difference, blocks = len(rows), sum(not row["same_list"] for row in rows), _block_rows(rows)
    statistical = _statistical_contract()
    preliminary, formal, terminal = _checkpoint_contract(statistical)
    preliminary_weeks, preliminary_difference, preliminary_blocks = preliminary
    formal_weeks, formal_difference, formal_blocks = formal
    terminal_weeks, terminal_difference, terminal_blocks = terminal
    preliminary_policy = statistical["preliminary"]; promotion_policy = statistical["promotion"]; negative_policy = statistical["negative_at_36"]
    values = [row["h10"]["delta_pct"] for row in rows]; block_values = [row["h10"]["delta_pct"] for row in blocks]
    metrics = {"eligible": eligible, "difference": difference, "blocks": len(blocks), "mean_delta": mean(values) if values else None,
               "block_win_rate": (sum(value > 0 for value in block_values) / len(block_values) if block_values else None),
               "bootstrap_lower": _bootstrap_bounds(block_values)[0], "bootstrap_upper": _bootstrap_bounds(block_values)[1],
               "signflip_p": _signflip_p(block_values)}
    metrics["monthly_cluster_t"], metrics["months"] = _monthly_cluster_t(rows)
    metrics.update(_risk_metrics(rows))
    metrics["h20_coverage_ok"] = all(row.get("h20_complete") is True for row in rows)
    # Pre-freeze evidence is audit-only: never promote, retire or judge on it.
    if not _epoch_mode.evidence_counts_toward_clock("p4a_overlay_adjudication"): return "continue_accumulating", metrics
    if eligible < preliminary_weeks: return "continue_accumulating", metrics
    if not metrics["h5_coverage_ok"]: return "pending_h5_coverage", metrics
    if difference < preliminary_difference: return "insufficient_policy_separation", metrics
    if len(blocks) < preliminary_blocks: return "continue_accumulating", metrics
    preliminary_positive = metrics["mean_delta"] >= preliminary_policy["mean_delta_pp_min"] and metrics["block_win_rate"] >= preliminary_policy["block_win_rate_min"] and metrics["risk_ok"]
    preliminary_negative = metrics["mean_delta"] <= preliminary_policy["negative_mean_delta_pp_max"] or not metrics["risk_ok"]
    if eligible < formal_weeks: return ("preliminary_positive" if preliminary_positive else "preliminary_negative" if preliminary_negative else "continue_accumulating"), metrics
    h20_complete = metrics["h20_coverage_ok"]
    if not h20_complete: return "pending_h20_coverage", metrics
    if difference < formal_difference or len(blocks) < formal_blocks or mature <= 0 or no_count / mature > promotion_policy["no_count_rate_pct_max"] / 100.0: return "continue_accumulating", metrics
    positive = preliminary_positive and metrics["mean_delta"] >= promotion_policy["mean_delta_pp_min"] and metrics["bootstrap_lower"] is not None and metrics["bootstrap_lower"] >= promotion_policy["bootstrap_lower_pp_min"] and metrics["signflip_p"] is not None and metrics["signflip_p"] <= promotion_policy["signflip_p_max"] and metrics["months"] >= promotion_policy["minimum_months"] and metrics["monthly_cluster_t"] is not None and metrics["monthly_cluster_t"] >= promotion_policy["monthly_cluster_t_min"]
    if eligible < terminal_weeks: return ("candidate_for_manual_promotion" if positive else "continue_accumulating"), metrics
    if difference < terminal_difference: return "continue_accumulating", metrics
    if len(blocks) < terminal_blocks: return "continue_accumulating", metrics
    if positive: return "candidate_for_manual_promotion", metrics
    if (metrics["mean_delta"] <= negative_policy["mean_delta_pp_max"] and metrics["bootstrap_upper"] is not None and metrics["bootstrap_upper"] < negative_policy["bootstrap_upper_pp_max"]) or not metrics["risk_ok"]:
        return "do_not_promote", metrics
    return "inconclusive_retired_for_epoch", metrics


def build_public_summary(*, root: str | Path | None, as_of: str, epoch_context: dict | None = None) -> dict:
    as_of = _date(as_of, "as_of")
    context = epoch_context or _epoch_context()
    if root is None:
        return _summary(as_of, "not_configured", 0, 0, 0, 0, 0, "not_due", "not_due", "continue_accumulating",
                        epoch_context=context)
    private_root = _root(root); rows = []; mature = no_count = 0; h5_complete = h20_complete = True
    for capture in _current_records(private_root, context):
        if capture["decision_date"] > as_of: continue
        _, outcome_path = _week_paths(private_root, capture["decision_date"])
        if not outcome_path.exists(): continue
        outcome = _load(outcome_path); _validate_record(outcome)
        if outcome["decision_date"] != capture["decision_date"] or outcome["epoch_id"] != capture["epoch_id"] or \
                outcome["contract_fingerprint"] != capture["contract_fingerprint"] or \
                outcome["payload"].get("capture_sha256") != _digest(capture):
            raise OverlayAdjudicationError("P4a outcome/capture immutable source binding drifted")
        h10 = outcome["payload"].get("horizons", {}).get("h10", {})
        if (private_root / "conflicts" / f"{capture['decision_date']}.json").exists():
            if h10.get("status") in {"settled", "no_count"}:
                mature += 1; no_count += 1
            continue
        if h10.get("status") == "settled":
            mature += 1; h5 = outcome["payload"].get("horizons", {}).get("h5", {}); h5_is_complete = h5.get("status") == "settled"; h5_complete &= h5_is_complete
            h20 = outcome["payload"].get("horizons", {}).get("h20", {}); complete = h20.get("status") == "settled"; h20_complete &= complete
            rows.append({"decision_date": capture["decision_date"], "same_list": capture["payload"]["same_list"],
                         "h5": h5, "h5_complete": h5_is_complete, "h10": h10,
                         "h20": h20, "h20_complete": complete})
        elif h10.get("status") == "no_count": mature += 1; no_count += 1
    verdict, metrics = _adjudicate(rows, mature, no_count); eligible, difference, blocks = len(rows), sum(not row["same_list"] for row in rows), len(_block_rows(rows))
    preliminary, formal, _ = _checkpoint_contract()
    h5_status = "not_due" if eligible < preliminary[0] else "complete" if h5_complete else "pending_h5_coverage"
    h20_status = "not_due" if eligible < formal[0] else "complete" if h20_complete else "pending_h20_coverage"
    status = "manual_promotion_candidate" if verdict == "candidate_for_manual_promotion" else "do_not_promote" if verdict == "do_not_promote" else "retired_for_epoch" if verdict == "inconclusive_retired_for_epoch" else "preliminary_review" if verdict.startswith("preliminary_") else "accumulating"
    return _summary(as_of, status, eligible, difference, blocks, mature, no_count, h5_status, h20_status, verdict,
                    metrics, context)


def _public_failed_gates(metrics: dict | None, *, eligible: int, blocks: int, mature: int, no_count: int) -> list[str]:
    if not metrics:
        return []
    statistical = _statistical_contract(); preliminary_policy = statistical["preliminary"]; promotion_policy = statistical["promotion"]
    failed = []
    checks = (("candidate_excess_ok", "candidate_excess_vs_benchmarks"), ("drawdown_ok", "close_drawdown"),
              ("bad_ticket_ok", "bad_ticket_rate"), ("tail_ok", "tail_h10"),
              ("false_negative_ok", "false_negative_rate"), ("cash_ok", "cash_or_unfilled"),
              ("h5_coverage_ok", "h5_coverage"),
              ("h5_h20_not_both_adverse", "h5_h20_adverse"))
    preliminary, formal, _ = _checkpoint_contract(statistical)
    preliminary_weeks, _, preliminary_blocks = preliminary
    formal_weeks, _, _ = formal
    failed.extend(name for key, name in checks if metrics.get(key) is False)
    if eligible >= preliminary_weeks and metrics.get("mean_delta") is not None and metrics["mean_delta"] < preliminary_policy["mean_delta_pp_min"]:
        failed.append("mean_delta")
    if blocks >= preliminary_blocks and metrics.get("block_win_rate") is not None and metrics["block_win_rate"] < preliminary_policy["block_win_rate_min"]:
        failed.append("nonoverlap_block_win_rate")
    if eligible >= formal_weeks:
        if metrics.get("h20_coverage_ok") is False: failed.append("h20_coverage")
        if metrics.get("bootstrap_lower") is not None and metrics["bootstrap_lower"] < promotion_policy["bootstrap_lower_pp_min"]: failed.append("block_bootstrap_lower")
        if metrics.get("signflip_p") is not None and metrics["signflip_p"] > promotion_policy["signflip_p_max"]: failed.append("block_signflip")
        if metrics.get("months", 0) < promotion_policy["minimum_months"]: failed.append("monthly_cluster_coverage")
        if metrics.get("monthly_cluster_t") is not None and metrics["monthly_cluster_t"] < promotion_policy["monthly_cluster_t_min"]: failed.append("monthly_cluster_t")
        if mature and no_count / mature > promotion_policy["no_count_rate_pct_max"] / 100.0: failed.append("no_count_rate")
    return sorted(set(failed))


def _summary(as_of: str, status: str, eligible: int, difference: int, blocks: int, mature: int, no_count: int,
             h5: str, h20: str, verdict: str, metrics: dict | None = None,
             epoch_context: dict | None = None) -> dict:
    context = epoch_context or _epoch_context()
    checkpoints = _checkpoint_contract()
    result = {"schema_name": "a_short_overlay_adjudication_summary", "schema_version": "1.0.0", "summary_id": "a_short_p4_stage3_rank_source", "as_of": as_of, "status": status,
               "eligible_policy_weeks": eligible, "difference_weeks": difference, "nonoverlap_blocks": blocks, "mature_opportunities": mature, "no_count_weeks": no_count,
               "h5_coverage_status": h5, "h20_coverage_status": h20,
               "epoch_id": context["epoch_id"],
               "checkpoints": {str(checkpoint): "available" if eligible >= checkpoint else "deficient"
                               for checkpoint, _, _ in checkpoints},
               "checkpoint_progress": {str(checkpoint): {"remaining_eligible_weeks": max(0, checkpoint - eligible),
                                       "remaining_difference_weeks": max(0, target_difference - difference),
                                       "remaining_nonoverlap_blocks": max(0, target_blocks - blocks)}
                                       for checkpoint, target_difference, target_blocks in checkpoints},
               "failing_risk_or_statistical_gates": _public_failed_gates(metrics, eligible=eligible, blocks=blocks, mature=mature, no_count=no_count),
               "adjudication": {"verdict": verdict, "advisory_only": True, "user_decision_required": verdict == "candidate_for_manual_promotion", "automatic_policy_switch": False, "automatic_production_config_write": False},
              "message": "P4a Stage3 排名源比较仅积累旁路证据；不改变正式 Top5、EGS、M6.7、仓位或退出。", "production_unchanged": True}
    try: jsonschema.validate(result, _load(PUBLIC_SCHEMA))
    except jsonschema.ValidationError as exc: raise OverlayAdjudicationError("P4a public summary violates schema") from exc
    return result


def validate_public_summary(summary: dict) -> None:
    try: jsonschema.validate(summary, _load(PUBLIC_SCHEMA))
    except jsonschema.ValidationError as exc: raise OverlayAdjudicationError("P4a public summary violates schema") from exc
    lowered = _canonical(summary).lower()
    if any(word in lowered for word in ("ts_code", "price", "account", "holding", "private", "selected")):
        raise OverlayAdjudicationError("P4a public summary leaks private evidence")


def _assert_public_summary_as_of_monotonic(summary: dict, json_path: Path) -> None:
    """Never replace a tracked public summary with an older point-in-time view."""
    if not json_path.is_file():
        return
    try:
        existing = _load(json_path)
        validate_public_summary(existing)
        existing_as_of = _date(existing.get("as_of"), "existing summary as_of")
        new_as_of = _date(summary.get("as_of"), "summary as_of")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise OverlayAdjudicationError("existing_public_summary_unreadable") from exc
    if existing_as_of > new_as_of:
        raise OverlayAdjudicationError("public_summary_as_of_regressed")


def prepare_public_artifact_set(summary: dict, *, json_path: str | Path = DEFAULT_PUBLIC_JSON,
                                markdown_path: str | Path = DEFAULT_PUBLIC_MD) -> dict[Path, bytes]:
    """Validate and render the whole public pair, writing nothing."""
    validate_public_summary(summary)
    target_path = Path(json_path)
    _assert_public_summary_as_of_monotonic(summary, target_path)
    return {
        target_path: _public_json_bytes(summary),
        Path(markdown_path): _public_markdown_text(summary).encode("utf-8"),
    }


def commit_public_artifact_set(files: dict[Path, bytes], *,
                               journal_dir: str | Path | None = None) -> None:
    """The one write entry point for the public pair: both files or neither."""
    commit_artifact_set(journal_dir or DEFAULT_ARTIFACT_SET_JOURNAL_DIR, files)


def write_public_summary(summary: dict, *, json_path: str | Path = DEFAULT_PUBLIC_JSON,
                         markdown_path: str | Path = DEFAULT_PUBLIC_MD,
                         journal_dir: str | Path | None = None) -> None:
    """Compatibility facade for the standalone runner: prepare then commit."""
    commit_public_artifact_set(
        prepare_public_artifact_set(summary, json_path=json_path, markdown_path=markdown_path),
        journal_dir=journal_dir)


def _public_markdown_text(summary: dict) -> str:
    rows = ["# A-short P4a Stage3 排名源比较", "", summary["message"], "", "| 项目 | 数值 |", "|---|---:|"]
    for key in ("epoch_id", "eligible_policy_weeks", "difference_weeks", "nonoverlap_blocks", "mature_opportunities", "no_count_weeks", "h5_coverage_status", "h20_coverage_status"):
        rows.append(f"| {key} | {summary[key]} |")
    checkpoints = "; ".join(f"{key}:{value}" for key, value in sorted(summary["checkpoints"].items()))
    failed = ", ".join(summary["failing_risk_or_statistical_gates"]) or "none"
    rows.append(f"| checkpoints | {checkpoints} |")
    progress = "; ".join(f"{key}:eligible={value['remaining_eligible_weeks']},difference={value['remaining_difference_weeks']},blocks={value['remaining_nonoverlap_blocks']}" for key, value in sorted(summary["checkpoint_progress"].items()))
    rows.append(f"| checkpoint_progress | {progress} |")
    rows.append(f"| failing_risk_or_statistical_gates | {failed} |")
    rows += ["", f"裁决状态：{summary['adjudication']['verdict']}（仅建议，需用户未来生效周回执；不自动写配置）。"]
    return "\n".join(rows) + "\n"


def unavailable_public_summary(as_of: str, *, epoch_context: dict | None = None) -> dict:
    return _summary(_date(as_of, "as_of"), "evidence_unavailable_or_inconclusive", 0, 0, 0, 0, 0,
                    "not_due", "not_due", "evidence_unavailable", epoch_context=epoch_context)


def settle_and_summarize_weekly(*, root: str | Path | None, daily_cache_path: str | Path | None, as_of: str,
                                public_json_path: str | Path = DEFAULT_PUBLIC_JSON, public_markdown_path: str | Path = DEFAULT_PUBLIC_MD,
                                write_public: bool = True, strict: bool = False,
                                sidecar_result: dict | None = None) -> dict:
    """``write_public=False`` is the weekly-pipeline path: the pair may only move
    after the official bundle publishes and the private capture lands."""
    epoch_context = None
    try:
        epoch_context = _epoch_context()
        if root is None: summary = build_public_summary(root=None, as_of=as_of, epoch_context=epoch_context)
        else:
            private_root = _root(root); cache = Path(daily_cache_path) if daily_cache_path else None
            if cache and cache.is_file():
                settle_from_daily_payload(root=private_root, daily_payload=_load(cache), as_of=as_of, cache_path=cache,
                                          epoch_context=epoch_context)
            summary = build_public_summary(root=private_root, as_of=as_of, epoch_context=epoch_context)
        if write_public:
            write_public_summary(summary, json_path=public_json_path, markdown_path=public_markdown_path)
        if sidecar_result is not None:
            sidecar_result["reason_codes"] = _settlement_reason_codes(
                root=root, as_of=as_of, epoch_context=epoch_context)
        return summary
    except Exception:
        # An outage must not overwrite last week's checked pair with a fresh
        # "unavailable" one; the caller records it in the sidecar outcomes.
        if strict:
            raise
        return unavailable_public_summary(as_of, epoch_context=epoch_context)


def _refresh_ledger(root: Path) -> None:
    groups: dict[str, int] = {}
    for capture in _records(root): groups[capture["epoch_id"]] = groups.get(capture["epoch_id"], 0) + 1
    _write(root / "ledger.json", {"schema_name": "a_short_overlay_adjudication_ledger", "schema_version": "1.0.0", "program_id": PROGRAM_ID,
                                    "epochs": [{"epoch_id": key, "capture_count": groups[key]} for key in sorted(groups)], "boundary": _boundary()})


def _settlement_reason_codes(*, root: str | Path | None, as_of: str,
                             epoch_context: dict | None = None) -> list[str]:
    """Return only stable, de-identified reasons from the current settlement."""
    if root is None:
        return []
    private_root = _root(root)
    if not private_root.exists():
        return []
    cutoff = _date(as_of, "as_of")
    context = epoch_context or _epoch_context()
    codes: set[str] = set()
    for capture in _current_records(private_root, context):
        decision_date = capture["decision_date"]
        if decision_date != cutoff:
            continue
        if (private_root / "conflicts" / f"{decision_date}.json").exists():
            codes.add("immutable_capture_conflict")
        _, outcome_path = _week_paths(private_root, decision_date)
        if not outcome_path.exists():
            continue
        outcome = _load(outcome_path)
        _validate_record(outcome)
        for horizon in (outcome["payload"].get("horizons") or {}).values():
            if isinstance(horizon, dict) and horizon.get("status") == "no_count":
                reason = str(horizon.get("reason") or "no_count")
                codes.add("immutable_capture_conflict" if reason == "immutable_capture_conflict" else "no_count")
    return sorted(codes)
