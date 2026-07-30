"""P5a industry-weight forward evidence: private capture, cache-only settlement and public progress.

This module deliberately does not adjudicate a winner.  It freezes the four complete
EGS profile pools only after a published weekly bundle, settles only from the existing
shared P0 daily cache, and emits a de-identified progress/reminder surface.  It never
reads an account, calls a provider, changes an EGS/M6.7 decision, or backfills history.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import math
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema

from engine import a_short_evidence_epoch_mode as _epoch_mode
from engine.a_short_experiment_admission_registry import admission_snapshot
from engine.a_short_nullable_bool import require_known_risk_bool


ROOT = Path(__file__).resolve().parents[1]
PROGRAM_ID = "a_short_industry_weight_comparison_v1"
PRIVATE_SCHEMA = ROOT / "schemas" / "a_short_industry_weight_comparison_private_record.schema.json"
LEDGER_SCHEMA = ROOT / "schemas" / "a_short_industry_weight_comparison_ledger.schema.json"
PROGRAM_SCHEMA = ROOT / "schemas" / "a_short_industry_weight_comparison_program.schema.json"
PUBLIC_SCHEMA = ROOT / "schemas" / "a_short_industry_weight_comparison_progress_summary.schema.json"
GOVERNANCE_PATH = ROOT / "presets" / "a_short_industry_weight_comparison_governance_20260722.json"
PROFILE_GOVERNANCE_PATH = ROOT / "presets" / "egs_industry_heat_governance_20260611.json"
DEFAULT_PRIVATE_ROOT = ROOT / "state" / "a_short" / "industry_weight_comparison_private" / "v1"
DEFAULT_PUBLIC_JSON = ROOT / "research" / "results" / "a_short" / "industry_weight_comparison_summary.json"
DEFAULT_PUBLIC_MD = ROOT / "research" / "results" / "a_short" / "industry_weight_comparison_summary.md"
HORIZONS = (5, 10, 20)
PROFILE_IDS = ("legacy", "balanced", "aggressive", "theme_double")
QUESTION_IDS = ("balanced_vs_legacy", "aggressive_vs_balanced", "theme_double_vs_balanced")
ADMISSION_IDS = tuple(f"p5_{question_id}" for question_id in QUESTION_IDS)
CACHE_NAME = "daily_cache.json"


class IndustryWeightComparisonError(ValueError):
    """A P5 evidence invariant is not provable from the frozen artifacts."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _date(value: object, label: str = "date") -> str:
    text = str(value or "")
    if len(text) != 8 or not text.isascii() or not text.isdigit():
        raise IndustryWeightComparisonError(f"P5 {label} must be YYYYMMDD")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise IndustryWeightComparisonError(f"P5 {label} is not a calendar date") from exc
    return text


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _boundary() -> dict:
    return {
        "comparison_only": True,
        "automatic_policy_switch": False,
        "reads_account_or_holdings": False,
    }


def _boundary_is_compatible(value: object) -> bool:
    """Accept the immutable P5a boundary shape while emitting the P5b shape."""
    return value in (_boundary(), {**_boundary(), "p5b_implemented": False})


def _private_root(root: str | Path) -> Path:
    path = Path(root).resolve()
    suffix = ("state", "a_short", "industry_weight_comparison_private", "v1")
    if tuple(part.lower() for part in path.parts[-4:]) != suffix:
        raise IndustryWeightComparisonError("P5 private root must end state/a_short/industry_weight_comparison_private/v1")
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return path
    try:
        result = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--", str(relative)],
                                capture_output=True, text=True, check=False)
    except OSError as exc:
        raise IndustryWeightComparisonError("cannot prove P5 private root is gitignored") from exc
    if result.returncode != 0:
        raise IndustryWeightComparisonError("P5 private root is not a provably gitignored path")
    return path


def load_governance(path: str | Path = GOVERNANCE_PATH) -> dict:
    try:
        governance = _load_json(Path(path))
        jsonschema.validate(governance, _load_json(PROGRAM_SCHEMA))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise IndustryWeightComparisonError("P5 governance violates its frozen schema") from exc
    if tuple(governance["profiles"]) != PROFILE_IDS:
        raise IndustryWeightComparisonError("P5 profile order/identity drifted")
    if tuple(row.get("question_id") for row in governance["questions"]) != QUESTION_IDS:
        raise IndustryWeightComparisonError("P5 question order/identity drifted")
    if governance["outcome_contract"].get("horizons_trading_days") != list(HORIZONS) or \
            governance["outcome_contract"].get("fixed_slots") != 15 or \
            governance["outcome_contract"].get("round_trip_cost_pct") != 0.16 or \
            governance["outcome_contract"].get("primary_horizon") != 10 or \
            governance["outcome_contract"].get("close_based_drawdown") is not True:
        raise IndustryWeightComparisonError("P5 outcome contract drifted")
    if governance["clock_contract"].get("checkpoints") != [12, 24, 36] or \
            governance["clock_contract"].get("difference_minimums") != [6, 12, 18] or \
            governance["clock_contract"].get("nonoverlap_block_minimums") != {"12": 6, "24": 12, "36": 12} or \
            governance["clock_contract"].get("same_list_effect") != "eligible_with_zero_whole_policy_effect" or \
            governance["clock_contract"].get("no_count_denominator") != "h10_mature_opportunities" or \
            governance["clock_contract"].get("non_overlap") != "decision_date_strictly_after_prior_h10_exit":
        raise IndustryWeightComparisonError("P5 clock contract drifted")
    statistics = governance["risk_and_statistics_contract"]
    if statistics.get("multiplicity_family") != "three_questions" or statistics.get("holm_bonferroni") is not True or \
            statistics.get("aggregate_verdict_priority") != ["manual_rollback_review_only", "do_not_promote",
                                                               "retain_balanced_only", "next_reviewed_candidate_only"]:
        raise IndustryWeightComparisonError("P5 statistical contract drifted")
    try:
        profile_governance = _load_json(PROFILE_GOVERNANCE_PATH)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IndustryWeightComparisonError("P5 cannot read production profile governance") from exc
    if governance["profiles"] != profile_governance.get("profiles"):
        raise IndustryWeightComparisonError("P5 profile weights diverge from production governance")
    return governance


def _source_fingerprint() -> str:
    from engine import egs_industry_heat
    return egs_industry_heat._p5_source_fingerprint()


def _runtime_source_fingerprint() -> str:
    """Pin semantic P5 capture/settlement dependencies, not whole source files."""
    from engine import a_short_industry_weight_adjudication as adjudication
    from engine import a_short_overlay_adjudication as overlay
    from engine import egs_industry_heat as heat
    from runners import a_short_factor_comparison_v2_cache_build as cache_build

    payload = {
        "module_sources": {
            "p5": _epoch_mode.semantic_module_contract(__import__(__name__, fromlist=["*"])),
            "adjudication": _epoch_mode.semantic_module_contract(adjudication),
            "signflip": _epoch_mode.semantic_module_contract(overlay),
            "industry_heat": _epoch_mode.semantic_module_contract(heat),
            "cache_builder": _epoch_mode.semantic_module_contract(cache_build),
        },
        "json_contracts": {"private": _load_json(PRIVATE_SCHEMA), "ledger": _load_json(LEDGER_SCHEMA),
                           "program": _load_json(PROGRAM_SCHEMA),
                           "profile_governance": _load_json(PROFILE_GOVERNANCE_PATH)},
    }
    return _digest(payload)


def _contract_fingerprint(governance: dict) -> str:
    """Pre-freeze returns a stable constant; see ``engine/a_short_evidence_epoch_mode``."""
    return _epoch_mode.fingerprint_or_pre_freeze(
        "p5_industry_weight", lambda: _real_contract_fingerprint(governance))


def _real_contract_fingerprint(governance: dict) -> str:
    return _digest({
        "governance": governance,
        "profile_governance": _load_json(PROFILE_GOVERNANCE_PATH),
        "source_fingerprint": _source_fingerprint(),
        "runtime_source_fingerprint": _runtime_source_fingerprint(),
        "admission_bindings": admission_snapshot(*ADMISSION_IDS),
    })


def _epoch_id(contract_fingerprint: str) -> str:
    return _digest({"program_id": PROGRAM_ID, "contract_fingerprint": contract_fingerprint})


def _validate_private_record(record: dict) -> None:
    try:
        jsonschema.validate(record, _load_json(PRIVATE_SCHEMA))
    except jsonschema.ValidationError as exc:
        raise IndustryWeightComparisonError("P5 private record violates its schema") from exc
    if record.get("program_id") != PROGRAM_ID or not _boundary_is_compatible(record.get("boundary")):
        raise IndustryWeightComparisonError("P5 private record crossed its comparison-only boundary")
    if record.get("record_type") == "capture" and \
            record.get("contract_fingerprint") == _contract_fingerprint(load_governance()) and \
            record.get("payload", {}).get("admission_bindings") != admission_snapshot(*ADMISSION_IDS):
        raise IndustryWeightComparisonError("P5 current-epoch admission binding drifted")
    if record.get("record_type") == "capture":
        payload = record.get("payload") or {}
        expected_epoch = _epoch_id(str(record.get("contract_fingerprint") or ""))
        if payload.get("contract_fingerprint") != record.get("contract_fingerprint") or \
                record.get("epoch_id") != expected_epoch:
            raise IndustryWeightComparisonError("P5 capture epoch binding drifted")
        payload_sha256 = payload.get("capture_payload_sha256")
        expected_payload_sha256 = _digest({key: value for key, value in payload.items()
                                           if key != "capture_payload_sha256"})
        if payload_sha256 != expected_payload_sha256:
            raise IndustryWeightComparisonError("P5 capture payload integrity drifted")


def _weekly_paths(root: Path, decision_date: str) -> tuple[Path, Path]:
    directory = root / "weeks" / decision_date
    return directory / "capture.json", directory / "outcome.json"


def _verify_published_weekly_bundle(*, out_path: str | Path, receipt_path: str | Path,
                                    decision_date: str, source_identity: dict) -> dict:
    output, receipt_file = Path(out_path), Path(receipt_path)
    markdown = output.with_suffix(".md")
    try:
        weekly, receipt = _load_json(output), _load_json(receipt_file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IndustryWeightComparisonError("P5 published weekly bundle is unreadable") from exc
    lineage = weekly.get("run_lineage") if isinstance(weekly, dict) else None
    if not isinstance(lineage, dict) or str(weekly.get("as_of")) != decision_date or \
            lineage.get("run_id") != source_identity.get("run_id") or \
            receipt.get("stage_status") != "complete" or receipt.get("as_of") != decision_date or \
            receipt.get("run_id") != lineage.get("run_id") or \
            receipt.get("candidate_digest") != lineage.get("candidate_digest") or \
            receipt.get("candidate_digest") != source_identity.get("candidate_digest") or \
            set(receipt.get("outputs") or []) != {output.name, markdown.name} or not markdown.is_file():
        raise IndustryWeightComparisonError("P5 published weekly receipt does not bind the official bundle")
    return weekly


def _profile_rows(weight_comparison: dict) -> dict[str, list[dict]]:
    pools = weight_comparison.get("profile_watch_pool_top15") or {}
    if pools.get("top_n") != 15 or not isinstance(pools.get("profiles"), dict):
        raise IndustryWeightComparisonError("P5 requires the governed profile_watch_pool_top15 source")
    profiles = pools["profiles"]
    if tuple(profiles) != PROFILE_IDS:
        raise IndustryWeightComparisonError("P5 profile pool source has wrong profile identity/order")
    clean: dict[str, list[dict]] = {}
    for profile in PROFILE_IDS:
        rows = profiles[profile]
        if not isinstance(rows, list) or len(rows) > 15:
            raise IndustryWeightComparisonError("P5 profile pool is malformed or exceeds fixed slots")
        seen, copied = set(), []
        for raw in rows:
            if not isinstance(raw, dict) or str(raw.get("tier")) != "Tier1":
                raise IndustryWeightComparisonError("P5 profile pool contains a non-Tier1 row")
            code = str(raw.get("ts_code") or "")
            if not code or code in seen:
                raise IndustryWeightComparisonError("P5 profile pool contains an empty/duplicate symbol")
            required = ("final_score", "l4_score", "pct_20d_n", "l1_name", "l2_name", "industry_heat_score",
                        "overheat_flag", "chasing_high")
            if not all(key in raw for key in required):
                raise IndustryWeightComparisonError("P5 profile pool is missing frozen selection fields")
            if not all(_finite(raw[key]) for key in ("final_score", "l4_score", "pct_20d_n")):
                raise IndustryWeightComparisonError("P5 profile pool has non-finite selection scores")
            copied.append({
                "ts_code": code, "tier": "Tier1", "final_score": float(raw["final_score"]),
                "l4_score": float(raw["l4_score"]), "pct_20d_n": float(raw["pct_20d_n"]),
                "industry_heat_score": (None if raw["industry_heat_score"] is None else float(raw["industry_heat_score"])),
                "l1_name": str(raw["l1_name"]), "l2_name": str(raw["l2_name"]),
                "overheat_flag": require_known_risk_bool(
                    raw["overheat_flag"], "P5 profile overheat_flag", IndustryWeightComparisonError
                ),
                "chasing_high": require_known_risk_bool(
                    raw["chasing_high"], "P5 profile chasing_high", IndustryWeightComparisonError
                ),
            })
            seen.add(code)
        clean[profile] = copied
    return clean


def _verify_egs_published_sources(*, analysis_input_path: Path, weight_comparison_path: Path,
                                  analysis_input: dict, weight_comparison: dict, weekly: dict) -> None:
    """Require the final EGS manifest to bind both P5 source bytes to one official run."""
    marker_path = analysis_input_path.parent / "official_publish.json"
    try:
        marker = _load_json(marker_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IndustryWeightComparisonError("P5 capture requires the official EGS publish marker") from exc
    run_identity = (analysis_input.get("source") or {}).get("run_identity") or {}
    weekly_lineage = weekly.get("run_lineage") or {}
    files = marker.get("files") or {}
    analysis_ref, comparison_ref = files.get("analysis_input") or {}, files.get("egs_weight_comparison") or {}
    if marker.get("stage_status") != "complete" or marker.get("trade_date") != analysis_input.get("trade_date") or \
            marker.get("run_id") != run_identity.get("run_id") or \
            marker.get("candidate_digest") != run_identity.get("candidate_digest") or \
            weekly_lineage.get("run_id") != run_identity.get("run_id") or \
            weekly_lineage.get("candidate_digest") != run_identity.get("candidate_digest") or \
            analysis_ref.get("path") != analysis_input_path.name or \
            analysis_ref.get("sha256") != _file_digest(analysis_input_path) or \
            comparison_ref.get("path") != weight_comparison_path.name or \
            comparison_ref.get("sha256") != _file_digest(weight_comparison_path):
        raise IndustryWeightComparisonError("P5 EGS marker does not bind the consumed full-universe sources")


def _capture_payload(*, decision_date: str, run_date: str, weekly: dict, analysis_input: dict,
                     weight_comparison: dict, governance: dict, contract_fingerprint: str,
                     analysis_input_path: Path, weight_comparison_path: Path,
                     weekly_out_path: Path, weekly_receipt_path: Path) -> dict:
    source = analysis_input.get("source") or {}
    run_identity = source.get("run_identity") or {}
    if str(analysis_input.get("trade_date")) != decision_date or not run_identity:
        raise IndustryWeightComparisonError("P5 analysis_input is not a source-bound official decision")
    _verify_egs_published_sources(analysis_input_path=analysis_input_path,
                                  weight_comparison_path=weight_comparison_path,
                                  analysis_input=analysis_input, weight_comparison=weight_comparison, weekly=weekly)
    if str(weight_comparison.get("as_of")) != decision_date or not weight_comparison.get("universe_digest"):
        raise IndustryWeightComparisonError("P5 refuses an old/unbound egs_weight_comparison source")
    def _is_sha256(value) -> bool:
        return isinstance(value, str) and len(value) == 64 and \
            all(char in "0123456789abcdef" for char in value)

    from engine import egs_industry_heat as heat
    # Both legs are content digests, not file bytes, so reformatting the preset
    # cannot invalidate a published bundle; and while the track is parked only
    # well-formedness is required, so parking can never strand an old bundle.
    source_fingerprint = weight_comparison.get("source_fingerprint")
    governance_fingerprint = weight_comparison.get("governance_sha256")
    enforced = _epoch_mode.enforcement_enabled("p5_industry_weight")
    if not _is_sha256(source_fingerprint) or not _is_sha256(governance_fingerprint) or (
        enforced and (
            source_fingerprint != _source_fingerprint()
            or governance_fingerprint != heat._p5_governance_digest(PROFILE_GOVERNANCE_PATH)
        )
    ):
        raise IndustryWeightComparisonError("P5 EGS comparison source does not bind current scoring/selector contract")
    profiles = _profile_rows(weight_comparison)
    balanced_codes = [row["ts_code"] for row in profiles["balanced"]]
    official_codes = [str(row.get("ts_code") or "") for row in (analysis_input.get("candidates") or [])]
    if balanced_codes != official_codes:
        raise IndustryWeightComparisonError("P5 balanced formal pool diverges from official analysis_input watch_df")
    questions = []
    for question in governance["questions"]:
        baseline, challenger = question["baseline"], question["challenger"]
        base_codes = [row["ts_code"] for row in profiles[baseline]]
        challenger_codes = [row["ts_code"] for row in profiles[challenger]]
        questions.append({
            "question_id": question["question_id"], "baseline": baseline, "challenger": challenger,
            "same_list": base_codes == challenger_codes,
            "overlap_count": len(set(base_codes) & set(challenger_codes)),
            "added_symbols": sorted(set(challenger_codes) - set(base_codes)),
            "removed_symbols": sorted(set(base_codes) - set(challenger_codes)),
        })
    price_freshness = (weekly.get("run_lineage") or {}).get("price_freshness") or {}
    price_data_through = _date(price_freshness.get("price_data_through"), "price_data_through")
    payload = {
        "run_date": run_date,
        "run_id": str(run_identity.get("run_id")),
        "input_pit_identity": copy.deepcopy(run_identity),
        "analysis_input_sha256": _digest(analysis_input),
        "official_weekly_m67_sha256": _file_digest(weekly_out_path),
        "official_weekly_receipt_sha256": _file_digest(weekly_receipt_path),
        "full_universe_digest": str(weight_comparison["universe_digest"]),
        "egs_weight_comparison_sha256": _digest(weight_comparison),
        "profile_governance_sha256": _file_digest(PROFILE_GOVERNANCE_PATH),
        "source_fingerprint": _source_fingerprint(),
        "contract_fingerprint": contract_fingerprint,
        "admission_bindings": admission_snapshot(*ADMISSION_IDS),
        "price_request": {"consumer_id": "p5_industry_weight", "price_data_through": price_data_through,
                          "horizons_trading_days": list(HORIZONS), "cache_status": "pending"},
        "profiles": {name: {"profile_weights": copy.deepcopy(governance["profiles"][name]),
                             "slots": 15, "selected": rows,
                             "selected_symbols_digest": _digest([row["ts_code"] for row in rows])}
                     for name, rows in profiles.items()},
        "questions": questions,
        "forward_eligible": True,
        "eligible_policy_week": "pending_h10",
        "difference_week": "pending_h10",
        "no_count_reason": None,
    }
    payload["capture_payload_sha256"] = _digest(payload)
    return payload


def capture_after_published_weekly(*, root: str | Path, decision_date: str, run_date: str,
                                   analysis_input_path: str | Path, weight_comparison_path: str | Path,
                                   source_identity: dict, out_path: str | Path, receipt_path: str | Path,
                                   forward_eligible: bool) -> dict:
    """Freeze one live canonical P5 observation after the matching M6.7 receipt exists."""
    private_root = _private_root(root)
    decision_date, run_date = _date(decision_date, "decision_date"), _date(run_date, "run_date")
    if not forward_eligible or run_date != _today() or decision_date < run_date:
        return {"status": "not_live_canonical_no_capture", "production_unchanged": True}
    weekly = _verify_published_weekly_bundle(out_path=out_path, receipt_path=receipt_path,
                                             decision_date=decision_date, source_identity=source_identity)
    try:
        analysis_input = _load_json(Path(analysis_input_path))
        comparison = _load_json(Path(weight_comparison_path))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IndustryWeightComparisonError("P5 capture sources are unreadable") from exc
    governance = load_governance()
    fingerprint = _contract_fingerprint(governance)
    record = {
        "schema_name": "a_short_industry_weight_comparison_private_record", "schema_version": "1.0.0",
        "record_type": "capture", "program_id": PROGRAM_ID, "decision_date": decision_date,
        "epoch_id": _epoch_id(fingerprint), "contract_fingerprint": fingerprint,
        "payload": _capture_payload(decision_date=decision_date, run_date=run_date, weekly=weekly,
                                    analysis_input=analysis_input, weight_comparison=comparison,
                                    governance=governance, contract_fingerprint=fingerprint,
                                    analysis_input_path=Path(analysis_input_path).resolve(),
                                    weight_comparison_path=Path(weight_comparison_path).resolve(),
                                    weekly_out_path=Path(out_path).resolve(),
                                    weekly_receipt_path=Path(receipt_path).resolve()),
        "boundary": _boundary(),
    }
    _validate_private_record(record)
    capture_path, _ = _weekly_paths(private_root, decision_date)
    if capture_path.exists():
        existing = _load_json(capture_path)
        if existing == record:
            return {"status": "idempotent_existing_capture", "production_unchanged": True}
        conflict = {
            "schema_name": "a_short_industry_weight_comparison_private_record", "schema_version": "1.0.0",
            "record_type": "conflict", "program_id": PROGRAM_ID, "decision_date": decision_date,
            "epoch_id": existing.get("epoch_id", _epoch_id(fingerprint)),
            "contract_fingerprint": existing.get("contract_fingerprint", fingerprint),
            "payload": {"reason": "same_as_of_identity_or_content_drift", "existing_sha256": _digest(existing),
                        "replay_sha256": _digest(record)}, "boundary": _boundary(),
        }
        _atomic_write(private_root / "conflicts" / f"{decision_date}.json", conflict)
        return {"status": "conflict_recorded_no_count", "production_unchanged": True}
    _atomic_write(capture_path, record)
    _refresh_private_ledger(private_root)
    return {"status": "captured_live_canonical", "production_unchanged": True}


def _capture_records(root: Path) -> list[dict]:
    records = []
    weeks = root / "weeks"
    if not weeks.exists():
        return records
    for directory in sorted(path for path in weeks.iterdir() if path.is_dir() and path.name.isdigit()):
        capture_path = directory / "capture.json"
        if not capture_path.exists():
            continue
        record = _load_json(capture_path)
        _validate_private_record(record)
        if record.get("record_type") != "capture" or record.get("decision_date") != directory.name:
            raise IndustryWeightComparisonError("P5 capture directory identity drifted")
        records.append(record)
    return records


def _current_admission_capture_records(root: Path) -> list[dict]:
    """Return only the active governed epoch; older P5a captures stay read-only diagnostic."""
    fingerprint = _contract_fingerprint(load_governance())
    binding = admission_snapshot(*ADMISSION_IDS)
    return [record for record in _capture_records(root)
            if record.get("contract_fingerprint") == fingerprint and
            record.get("payload", {}).get("admission_bindings") == binding]


def cache_consumer_windows(*, root: str | Path, run_date: str) -> list[dict]:
    """Expose P5's frozen cache requests to the shared P0 builder; no provider is touched."""
    private_root = _private_root(root)
    run_date = _date(run_date, "run_date")
    windows = []
    for capture in _current_admission_capture_records(private_root):
        payload = capture["payload"]
        if not payload.get("forward_eligible") or capture["decision_date"] > run_date:
            continue
        symbols = sorted({row["ts_code"] for profile in payload["profiles"].values()
                          for row in profile["selected"]})
        if symbols:
            windows.append({"consumer_id": "p5_industry_weight", "decision_date": capture["decision_date"],
                            "price_data_through": payload["price_request"]["price_data_through"],
                            "symbols": symbols})
    return windows


def _cache_frames(daily_payload: dict) -> tuple[dict[tuple[str, str], dict], dict[tuple[str, str], dict], list[str]]:
    if not isinstance(daily_payload, dict) or not isinstance(daily_payload.get("stocks"), list) or \
            not isinstance(daily_payload.get("limits"), list):
        raise IndustryWeightComparisonError("P5 shared daily cache is malformed")
    stocks, limits = {}, {}
    for raw in daily_payload["stocks"]:
        if not isinstance(raw, dict):
            raise IndustryWeightComparisonError("P5 cache stock row is malformed")
        key = (str(raw.get("ts_code") or ""), _date(raw.get("trade_date"), "cache trade_date"))
        if not key[0] or (key in stocks and stocks[key] != raw):
            raise IndustryWeightComparisonError("P5 cache has a conflicting stock row")
        stocks[key] = raw
    for raw in daily_payload["limits"]:
        if not isinstance(raw, dict):
            raise IndustryWeightComparisonError("P5 cache limit row is malformed")
        key = (str(raw.get("ts_code") or ""), _date(raw.get("trade_date"), "cache trade_date"))
        if not key[0] or (key in limits and limits[key] != raw):
            raise IndustryWeightComparisonError("P5 cache has a conflicting limit row")
        limits[key] = raw
    return stocks, limits, sorted({date for _, date in stocks})


def _qfq(row: dict, field: str) -> float | None:
    if row.get("adj_factor_observed") is not True or row.get("adj_factor_source") != "provider_observed" or \
            not _finite(row.get("adj_factor")) or float(row["adj_factor"]) <= 0 or not _finite(row.get(field)):
        return None
    return float(row[field]) * float(row["adj_factor"])


def _arm_horizon(*, selected: list[dict], decision_date: str, horizon: int, dates: list[str], date_pos: dict[str, int],
                 stocks: dict[tuple[str, str], dict], limits: dict[tuple[str, str], dict], cost_pct: float) -> dict:
    if decision_date not in date_pos or date_pos[decision_date] + horizon >= len(dates):
        return {"status": "pending", "portfolio_net_return_pct": None, "positions": []}
    entry_date, exit_date = dates[date_pos[decision_date] + 1], dates[date_pos[decision_date] + horizon]
    positions, cash_slots = [], 15 - len(selected)
    for member in selected:
        code = member["ts_code"]
        entry, exit_row = stocks.get((code, entry_date)), stocks.get((code, exit_date))
        limit = limits.get((code, entry_date))
        if entry is None or exit_row is None or limit is None:
            return {"status": "no_count", "reason": "missing_required_cache_row", "portfolio_net_return_pct": None, "positions": []}
        entry_qfq, exit_qfq = _qfq(entry, "open"), _qfq(exit_row, "close")
        if entry_qfq is None or exit_qfq is None or not _finite(limit.get("up_limit")):
            return {"status": "no_count", "reason": "qfq_or_limit_unverified", "portfolio_net_return_pct": None, "positions": []}
        if float(entry["open"]) >= float(limit["up_limit"]) * 0.999:
            cash_slots += 1
            positions.append({"entry_status": "unfilled_limit_up", "net_return_pct": 0.0})
        else:
            net = (exit_qfq / entry_qfq - 1.0) * 100.0 - cost_pct
            if not _finite(net):
                return {"status": "no_count", "reason": "nonfinite_qfq_return", "portfolio_net_return_pct": None, "positions": []}
            positions.append({"entry_status": "filled", "net_return_pct": net})
    navs = []
    for day in dates[date_pos[entry_date]:date_pos[exit_date] + 1]:
        values = []
        for member, position in zip(selected, positions):
            if position["entry_status"] != "filled":
                values.append(0.0)
                continue
            close_row = stocks.get((member["ts_code"], day))
            close_qfq = _qfq(close_row, "close") if close_row else None
            if close_qfq is None:
                return {"status": "no_count", "reason": "qfq_close_unverified", "portfolio_net_return_pct": None, "positions": []}
            entry_row = stocks[(member["ts_code"], entry_date)]
            entry_qfq = _qfq(entry_row, "open")
            value = (close_qfq / entry_qfq - 1.0) * 100.0 if entry_qfq is not None else None
            if not _finite(value):
                return {"status": "no_count", "reason": "nonfinite_qfq_close_return", "portfolio_net_return_pct": None, "positions": []}
            values.append(value)
        nav = sum(values) / 15.0
        if not _finite(nav):
            return {"status": "no_count", "reason": "nonfinite_close_drawdown", "portfolio_net_return_pct": None, "positions": []}
        navs.append(nav)
    peak, drawdown = 0.0, 0.0
    for nav in navs:
        peak = max(peak, nav)
        drawdown = max(drawdown, peak - nav)
    portfolio_net_return_pct = sum(row["net_return_pct"] for row in positions) / 15.0
    if not _finite(portfolio_net_return_pct) or not _finite(drawdown):
        return {"status": "no_count", "reason": "nonfinite_portfolio_metric", "portfolio_net_return_pct": None, "positions": []}
    return {"status": "settled", "entry_date": entry_date, "exit_date": exit_date,
            "portfolio_net_return_pct": portfolio_net_return_pct,
            "cash_drag_pct": cash_slots / 15.0 * 100.0, "close_drawdown_pct": drawdown, "positions": positions}


def _question_outcome(question: dict, profiles: dict, decision_date: str, dates: list[str], date_pos: dict[str, int],
                      stocks: dict, limits: dict, cost_pct: float) -> dict:
    arms = {}
    for profile in (question["baseline"], question["challenger"]):
        arms[profile] = {f"h{h}": _arm_horizon(selected=profiles[profile]["selected"], decision_date=decision_date,
                                                  horizon=h, dates=dates, date_pos=date_pos, stocks=stocks,
                                                  limits=limits, cost_pct=cost_pct) for h in HORIZONS}
    horizons = {}
    for horizon in HORIZONS:
        key, base, challenger = f"h{horizon}", arms[question["baseline"]][f"h{horizon}"], arms[question["challenger"]][f"h{horizon}"]
        if base["status"] == "pending" or challenger["status"] == "pending":
            horizons[key] = {"status": "pending", "whole_policy_effect_pct": None}
        elif base["status"] != "settled" or challenger["status"] != "settled":
            horizons[key] = {"status": "no_count", "reason": base.get("reason") or challenger.get("reason"),
                             "whole_policy_effect_pct": None}
        else:
            effect = 0.0 if question["same_list"] else challenger["portfolio_net_return_pct"] - base["portfolio_net_return_pct"]
            if not _finite(effect):
                horizons[key] = {"status": "no_count", "reason": "nonfinite_whole_policy_effect",
                                 "whole_policy_effect_pct": None}
            else:
                horizons[key] = {"status": "settled", "whole_policy_effect_pct": effect,
                                 "same_list_zero_effect": bool(question["same_list"])}
    return {"question_id": question["question_id"], "same_list": question["same_list"], "arms": arms, "horizons": horizons}


def settle_from_daily_payload(*, root: str | Path, daily_payload: dict, as_of: str) -> dict:
    """Settle only current frozen P5 captures using a pre-existing shared cache."""
    private_root, as_of = _private_root(root), _date(as_of, "as_of")
    governance, stocks, limits, all_dates = load_governance(), *_cache_frames(daily_payload)
    dates = [day for day in all_dates if day <= as_of]
    date_pos = {day: index for index, day in enumerate(dates)}
    changed = 0
    for capture in _current_admission_capture_records(private_root):
        decision_date = capture["decision_date"]
        if decision_date > as_of:
            continue
        conflict_path = private_root / "conflicts" / f"{decision_date}.json"
        questions = []
        for question in capture["payload"]["questions"]:
            if conflict_path.exists():
                questions.append({"question_id": question["question_id"], "same_list": question["same_list"],
                                  "horizons": {f"h{h}": {"status": "no_count", "reason": "immutable_capture_conflict",
                                                            "whole_policy_effect_pct": None} for h in HORIZONS}})
            else:
                questions.append(_question_outcome(question, capture["payload"]["profiles"], decision_date,
                                                    dates, date_pos, stocks, limits,
                                                    float(governance["outcome_contract"]["round_trip_cost_pct"])))
        outcome = {
            "schema_name": "a_short_industry_weight_comparison_private_record", "schema_version": "1.0.0",
            "record_type": "outcome", "program_id": PROGRAM_ID, "decision_date": decision_date,
            "epoch_id": capture["epoch_id"], "contract_fingerprint": capture["contract_fingerprint"],
            "payload": {"capture_sha256": _digest(capture), "settled_through": as_of,
                        "cache_sha256": _digest(daily_payload), "questions": questions}, "boundary": _boundary(),
        }
        _validate_private_record(outcome)
        _, outcome_path = _weekly_paths(private_root, decision_date)
        if not outcome_path.exists() or _load_json(outcome_path) != outcome:
            _atomic_write(outcome_path, outcome)
            changed += 1
    _refresh_private_ledger(private_root)
    return {"status": "settled_from_existing_cache", "outcomes_updated": changed, "production_unchanged": True}


def _question_progress(root: Path, question_id: str, as_of: str) -> dict:
    eligible = difference = mature = no_count = 0
    for capture in _current_admission_capture_records(root):
        if capture["decision_date"] > as_of:
            continue
        _, outcome_path = _weekly_paths(root, capture["decision_date"])
        if not outcome_path.exists():
            continue
        outcome = _load_json(outcome_path)
        _validate_private_record(outcome)
        row = next((item for item in outcome["payload"].get("questions", []) if item.get("question_id") == question_id), None)
        if not isinstance(row, dict):
            continue
        h10 = (row.get("horizons") or {}).get("h10") or {}
        if h10.get("status") == "settled":
            mature += 1
            eligible += 1
            if row.get("same_list") is False:
                difference += 1
        elif h10.get("status") == "no_count":
            mature += 1
            no_count += 1
    # Pre-freeze evidence is audit-only: it must not trigger the P5b build reminder.
    counts = _epoch_mode.evidence_counts_toward_clock("p5_industry_weight")
    notice = ("accumulating" if not counts else
              "p5b_terminal_checkpoint_36_not_implemented" if eligible >= 36 else
              "p5b_formal_checkpoint_24_not_implemented" if eligible >= 24 else
              "p5b_implementation_due_at_12" if eligible >= 12 and difference >= 6 else "accumulating")
    return {"question_id": question_id, "eligible_policy_weeks": eligible, "difference_weeks": difference,
            "mature_opportunities": mature, "no_count_weeks": no_count,
            "p5b_build_due": counts and eligible >= 12 and difference >= 6,
            "remaining_eligible_to_p5b": max(0, 12 - eligible), "remaining_difference_to_p5b": max(0, 6 - difference),
            "p5b_checkpoint_notice": notice}


def _p_value_function(method_path: object):
    """Resolve the frozen declared P5 method rather than keeping a second hidden source."""
    method_path = str(method_path or "")
    module_name, separator, attribute = method_path.rpartition(".")
    if not module_name or not separator or not attribute:
        raise IndustryWeightComparisonError("P5 p-value method declaration is invalid")
    try:
        method = getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise IndustryWeightComparisonError("P5 p-value method declaration is unavailable") from exc
    if not callable(method):
        raise IndustryWeightComparisonError("P5 p-value method declaration is not callable")
    return method


def _aggregate_terminal_verdict(terminal: list[dict], governance: dict) -> str:
    """Select the most conservative terminal result from the sealed governance order."""
    priority = governance["risk_and_statistics_contract"]["aggregate_verdict_priority"]
    if not isinstance(priority, list) or len(priority) != len(set(priority)):
        raise IndustryWeightComparisonError("P5 aggregate verdict priority is invalid")
    ranks = {verdict: index for index, verdict in enumerate(priority)}
    try:
        return min((row["verdict"] for row in terminal), key=ranks.__getitem__)
    except KeyError as exc:
        raise IndustryWeightComparisonError("P5 terminal verdict is absent from governance priority") from exc


def build_public_progress(*, root: str | Path | None, as_of: str) -> dict:
    as_of = _date(as_of, "as_of")
    from engine.a_short_industry_weight_adjudication import P5B_IMPLEMENTED, adjudicate_question, holm_bonferroni
    governance = load_governance()
    records = {question_id: [] for question_id in QUESTION_IDS}
    mature = {question_id: 0 for question_id in QUESTION_IDS}
    no_count = {question_id: 0 for question_id in QUESTION_IDS}
    source_rows = []
    if root is not None:
        private_root = _private_root(root)
        for capture in _current_admission_capture_records(private_root) if private_root.exists() else []:
            if capture["decision_date"] > as_of:
                continue
            _, outcome_path = _weekly_paths(private_root, capture["decision_date"])
            if not outcome_path.exists():
                continue
            outcome = _load_json(outcome_path); _validate_private_record(outcome)
            if str(outcome.get("payload", {}).get("settled_through") or "") > as_of:
                continue
            if outcome.get("epoch_id") != capture["epoch_id"] or outcome.get("contract_fingerprint") != capture["contract_fingerprint"] or \
                    outcome.get("payload", {}).get("capture_sha256") not in (None, _digest(capture)):
                raise IndustryWeightComparisonError("P5 outcome/capture source binding drifted")
            source_rows.append({"capture": _digest(capture), "outcome": _digest(outcome)})
            for outcome_question in outcome.get("payload", {}).get("questions", []):
                question_id = outcome_question.get("question_id")
                if question_id not in records:
                    continue
                h10 = (outcome_question.get("horizons") or {}).get("h10") or {}
                if h10.get("status") == "no_count":
                    mature[question_id] += 1; no_count[question_id] += 1
                    continue
                if h10.get("status") != "settled":
                    continue
                mature[question_id] += 1
                if not _finite(h10.get("whole_policy_effect_pct")):
                    no_count[question_id] += 1
                    continue
                baseline = outcome_question.get("arms", {}).get(next(q["baseline"] for q in governance["questions"] if q["question_id"] == question_id), {}).get("h10", {})
                challenger = outcome_question.get("arms", {}).get(next(q["challenger"] for q in governance["questions"] if q["question_id"] == question_id), {}).get("h10", {})
                exit_date = challenger.get("exit_date") or baseline.get("exit_date")
                if not isinstance(exit_date, str) or exit_date > as_of:
                    continue
                tickets = [float(row["net_return_pct"]) for row in challenger.get("positions", []) if _finite(row.get("net_return_pct"))]
                records[question_id].append({"decision_date": capture["decision_date"], "same_list": outcome_question.get("same_list") is True,
                    "effect_pct": float(h10["whole_policy_effect_pct"]), "exit_date": exit_date,
                    "challenger_ticket_returns": tickets,
                    "challenger_close_drawdown_pct": challenger.get("close_drawdown_pct"),
                    "relative_close_drawdown_worsening_pct": (
                        float(challenger["close_drawdown_pct"]) - float(baseline["close_drawdown_pct"])
                        if _finite(challenger.get("close_drawdown_pct")) and _finite(baseline.get("close_drawdown_pct")) else None)})
    from engine.a_short_experiment_admission_registry import get_admission
    question_defs = {item["question_id"]: {**item, "evidence_counts": _epoch_mode.evidence_counts_toward_clock("p5_industry_weight"),
                       "p5b_adjudication_governance": get_admission(f"p5_{item['question_id']}")["statistical_contract"]["definition"]["p5b_adjudication_governance"]}
                     for item in governance["questions"]}
    p_value_methods = {definition["p5b_adjudication_governance"].get("p_value_method")
                       for definition in question_defs.values()}
    if len(p_value_methods) != 1:
        raise IndustryWeightComparisonError("P5 questions disagree about the p-value method")
    p_value_function = _p_value_function(p_value_methods.pop())
    from engine.a_short_industry_weight_adjudication import _blocks
    p_values = {key: p_value_function([row["effect_pct"] for row in _blocks(value)]) for key, value in records.items()}
    rejected = holm_bonferroni(p_values, float(governance["risk_and_statistics_contract"]["formal_alpha_two_sided"]))
    questions = [adjudicate_question(records[key], mature=mature[key], no_count=no_count[key], governance=governance,
                                     question=question_defs[key], holm_rejected=rejected,
                                     p_value_function=p_value_function) for key in QUESTION_IDS]
    terminal = [row for row in questions if row["checkpoint_stage"] == "terminal" and row["verdict"] != "continue_accumulating"]
    aggregate = _aggregate_terminal_verdict(terminal, governance) if terminal else "continue_accumulating"
    stage = "terminal" if terminal else next((row["checkpoint_stage"] for row in questions if row["verdict"] != "continue_accumulating"), "accumulating")
    summary = {"schema_name": "a_short_industry_weight_comparison_progress_summary", "schema_version": "1.0.0",
               "summary_id": "a_short_industry_weight_comparison", "as_of": as_of,
               "status": "not_configured" if root is None else "review_due" if aggregate != "continue_accumulating" else "accumulating",
               "questions": questions, "verdict": aggregate, "adjudication_stage": stage,
               "progress": {"questions": {row["question_id"]: row["progress"] for row in questions}},
               "fingerprint": _contract_fingerprint(governance), "source_hash": _digest(source_rows),
               "p5b_implemented": P5B_IMPLEMENTED, "admission_binding": _digest(admission_snapshot(*ADMISSION_IDS)),
               "message": "P5 行业权重对比：P5b 裁判已运行；仅供人工比较决策，不自动修改生产权重。",
               "production_unchanged": True}
    validate_public_progress(summary)
    return summary


def unavailable_public_progress(as_of: str) -> dict:
    """Fresh no-stale-reminder surface for an unavailable P5 sidecar."""
    from engine.a_short_industry_weight_adjudication import P5B_IMPLEMENTED
    summary = {"schema_name": "a_short_industry_weight_comparison_progress_summary", "schema_version": "1.0.0",
               "summary_id": "a_short_industry_weight_comparison", "as_of": _date(as_of, "as_of"),
               "status": "evidence_unavailable_or_inconclusive",
               "questions": [{"question_id": question_id, "verdict": "continue_accumulating", "reason": "evidence_unavailable",
                              "checkpoint_stage": "not_reached", "progress": {}, "metrics": {}, "comparison_only": True} for question_id in QUESTION_IDS],
               "verdict": "not_adjudicated", "adjudication_stage": "not_adjudicated", "progress": {}, "fingerprint": _contract_fingerprint(load_governance()), "source_hash": _digest([]), "p5b_implemented": P5B_IMPLEMENTED, "admission_binding": _digest(admission_snapshot(*ADMISSION_IDS)),
               "message": "P5 行业权重对比：证据不可用或不完整；不显示旧提醒，生产结论不变。",
               "production_unchanged": True}
    validate_public_progress(summary)
    return summary


def _question_progress_placeholder(question_id: str) -> dict:
    return {"question_id": question_id, "eligible_policy_weeks": 0, "difference_weeks": 0,
            "mature_opportunities": 0, "no_count_weeks": 0, "p5b_build_due": False,
            "remaining_eligible_to_p5b": 12, "remaining_difference_to_p5b": 6,
            "p5b_checkpoint_notice": "accumulating"}


def validate_public_progress(summary: dict) -> None:
    try:
        jsonschema.validate(summary, _load_json(PUBLIC_SCHEMA))
    except jsonschema.ValidationError as exc:
        raise IndustryWeightComparisonError("P5 public progress summary violates its schema") from exc
    if tuple(row["question_id"] for row in summary["questions"]) != QUESTION_IDS:
        raise IndustryWeightComparisonError("P5 public progress is internally inconsistent")
    if summary.get("admission_binding") != _digest(admission_snapshot(*ADMISSION_IDS)):
        raise IndustryWeightComparisonError("P5 public progress admission binding drifted")
    encoded = _canonical(summary).lower()
    for prohibited in ("ts_code", "selected", "price", "account", "holding", "private", "return_pct", "sha256"):
        if prohibited in encoded:
            raise IndustryWeightComparisonError("P5 public progress leaks a private evidence field")


def write_public_progress(summary: dict, *, json_path: str | Path = DEFAULT_PUBLIC_JSON,
                          markdown_path: str | Path = DEFAULT_PUBLIC_MD) -> None:
    validate_public_progress(summary)
    _atomic_write(Path(json_path), summary)
    lines = ["# A-short P5 行业权重比较进度", "", summary["message"], "",
             "| 问题 | 裁决 | 原因 | 检查点 |",
             "|---|---|---|---|"]
    for row in summary["questions"]:
        lines.append("| {question_id} | {verdict} | {reason} | {checkpoint_stage} |".format(**row))
    lines += ["", "P5b 为 comparison-only 裁判；不会自动修改 active_profile、EGS、M6.7 或仓位。"]
    path = Path(markdown_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _refresh_private_ledger(root: Path) -> None:
    epochs: dict[str, dict] = {}
    for capture in _capture_records(root):
        row = epochs.setdefault(capture["epoch_id"], {"epoch_id": capture["epoch_id"],
                                                        "contract_fingerprint": capture["contract_fingerprint"],
                                                        "capture_count": 0, "decision_dates": []})
        row["capture_count"] += 1
        row["decision_dates"].append(capture["decision_date"])
    ledger = {"schema_name": "a_short_industry_weight_comparison_ledger", "schema_version": "1.0.0",
              "program_id": PROGRAM_ID, "epochs": [epochs[key] for key in sorted(epochs)], "boundary": _boundary()}
    try:
        jsonschema.validate(ledger, _load_json(LEDGER_SCHEMA))
    except jsonschema.ValidationError as exc:
        raise IndustryWeightComparisonError("P5 private ledger violates its schema") from exc
    _atomic_write(root / "ledger.json", ledger)


def settle_and_summarize_weekly(*, root: str | Path | None, daily_cache_path: str | Path | None,
                                as_of: str, public_json_path: str | Path = DEFAULT_PUBLIC_JSON,
                                public_markdown_path: str | Path = DEFAULT_PUBLIC_MD) -> dict:
    """Non-blocking weekly seam: cache-only settlement then a fresh de-identified summary."""
    try:
        if root is None:
            summary = build_public_progress(root=None, as_of=as_of)
        else:
            private_root = _private_root(root)
            cache_path = Path(daily_cache_path) if daily_cache_path else private_root / CACHE_NAME
            if not private_root.exists() or not cache_path.is_file():
                summary = build_public_progress(root=private_root, as_of=as_of)
            else:
                settle_from_daily_payload(root=private_root, daily_payload=_load_json(cache_path), as_of=as_of)
                summary = build_public_progress(root=private_root, as_of=as_of)
        write_public_progress(summary, json_path=public_json_path, markdown_path=public_markdown_path)
        return summary
    except Exception:
        summary = unavailable_public_progress(as_of)
        try:
            write_public_progress(summary, json_path=public_json_path, markdown_path=public_markdown_path)
        except Exception:
            pass
        return summary
