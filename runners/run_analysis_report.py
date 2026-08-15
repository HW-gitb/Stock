#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 4 deterministic single-stock analysis report runner.

This runner is intentionally pure Python and deterministic. It reads one
candidate from ``analysis_input.json``, replays the Phase 3 analyzer veto,
checks JSON state, validates the report against
``schemas/deterministic_report.schema.json``, then writes JSON + Markdown.
It does not call an LLM.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.analyzer import state_manager
from engine.analyzer.rule6_hard_veto import RULE_VERSIONS, run_veto
from engine.a_short_legacy_llm_tasks import result_content
from engine.data.analysis_input_contract import validate_analysis_input_file
from engine.a_short_run_revision import official_analysis_input_path


SCHEMA_PATH = ROOT / "schemas" / "deterministic_report.schema.json"
ENRICHMENT_SCHEMA_PATH = ROOT / "schemas" / "deterministic_report_enrichment.schema.json"
LIVE_RESULT_ROOT = ROOT / "result" / "a_short"
REPORT_SCHEMA_VERSION = "1.3.0"
PROMPT_REF_ALIASES = {
    "regulatory_check": "regulatory_48h",
}
A_SHARE_STATE_REPLAY_TZ = timezone(timedelta(hours=8))


def load_analysis_input(as_of: str, input_path: Path | None = None) -> dict[str, Any]:
    path = input_path or official_analysis_input_path(ROOT, as_of)
    return validate_analysis_input_file(path, label=f"analysis_input {path}")


def find_candidate(payload: dict[str, Any], ts_code: str) -> dict[str, Any]:
    candidates = payload.get("candidates")
    if not candidates:
        # Distinguish "input has zero candidates" from "ts_code not in candidates"
        # so the user can tell whether to re-run egs_main vs check their ts_code.
        raise ValueError(
            f"analysis_input has no candidates (candidates field is "
            f"{'missing' if candidates is None else 'empty'}); "
            f"re-run egs_main for this as_of?"
        )
    for candidate in candidates:
        if str(candidate.get("ts_code")) == str(ts_code):
            return candidate
    available = [str(c.get("ts_code")) for c in candidates if isinstance(c, dict)]
    raise ValueError(
        f"candidate ts_code {ts_code!r} not in analysis_input "
        f"(available: {', '.join(available[:10])}{'...' if len(available) > 10 else ''})"
    )


def build_report(payload: dict[str, Any], candidate: dict[str, Any],
                 generated_at: str | None = None,
                 state_now: datetime | str | None = None) -> dict[str, Any]:
    generated_at = generated_at or datetime.now().astimezone().isoformat(timespec="seconds")
    as_of = str(payload.get("trade_date") or "")
    state_evaluation_time = _state_evaluation_time(as_of, state_now)
    ts_code = str(candidate.get("ts_code") or "")
    name = str(candidate.get("name") or ts_code)
    veto = run_veto(candidate)
    has_position = state_manager.has_position(ts_code)
    circuit_active = state_manager.is_circuit_breaker_active(state_evaluation_time)
    decision = _build_decision(veto, has_position, circuit_active)

    report = {
        "schema_name": "deterministic_report",
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "preset": str(payload.get("preset") or "a_short"),
        "as_of": as_of,
        "ts_code": ts_code,
        "name": name,
        "decision": decision,
        "veto": veto,
        "entry_plan": {
            "price": None,
            "condition": "unknown",
            "type": "unknown",
            "requires_llm": True,
        },
        "exit_plan": {
            "stop_loss": None,
            "take_profit_1": None,
            "take_profit_2": None,
            "time_stop_days": None,
            "requires_llm": True,
        },
        "position_size": {
            "shares": None,
            "pct_of_capital": None,
            "rationale": "not_implemented_phase4",
            "requires_llm": True,
        },
        "risk_flags": _build_risk_flags(candidate, veto, has_position, circuit_active),
        "evidence": _build_evidence(payload, candidate),
        "unknowns": _build_unknowns(candidate),
        "llm_notes": {
            "enabled": False,
            "sections": _build_llm_sections(candidate),
        },
        "data_lineage": {
            "egs_version": str(_get(payload, "source", "screening_engine_version", default="v0.0")),
            "analyzer_rules": [
                {"code": code, "version": version}
                for code, version in RULE_VERSIONS.items()
            ],
            "state_snapshot_ref": _state_snapshot_ref(),
            "analysis_input_schema_version": str(payload.get("schema_version") or "0.0.0"),
            "l3_mode": _analysis_input_l3_mode(payload),
            **_analysis_input_l3_lineage(payload),
            "enrichment_applied": False,
            "enrichment_source": None,
            "state_evaluation_time": state_evaluation_time,
            "generated_at": generated_at,
        },
        "analyzer_invocations": _build_analyzer_invocations(veto),
    }
    return report


def _build_decision(veto: dict[str, Any], has_position: bool, circuit_active: bool) -> dict[str, str]:
    if veto.get("vetoed"):
        # Comma-separated (RULE_VERSIONS codes never contain commas) instead of
        # pipe — pipes are reserved for downstream Markdown table cells where
        # they would need escaping. Comma is safer for embedding in CSV/MD.
        codes = sorted({str(r.get("code")) for r in (veto.get("reasons") or []) if r.get("code")})
        reason = "analyzer_hard_veto:" + ",".join(codes)
        return {"action": "skip", "reason_code": reason, "confidence": "high"}
    if circuit_active:
        return {"action": "skip", "reason_code": "state_circuit_breaker_active", "confidence": "high"}
    if has_position:
        return {"action": "watch", "reason_code": "state_existing_position", "confidence": "medium"}
    return {"action": "watch", "reason_code": "phase4_v1_no_buy_decision", "confidence": "unknown"}


def _build_risk_flags(candidate: dict[str, Any], veto: dict[str, Any],
                      has_position: bool, circuit_active: bool) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    for reason in veto.get("reasons") or []:
        flags.append({
            "code": str(reason.get("code") or "analyzer_veto"),
            "severity": "critical",
            "source": "analyzer",
            "detail": reason.get("detail") or {},
        })
    for diag in veto.get("diagnostics") or []:
        flags.append({
            "code": f"{diag.get('code')}:{diag.get('status')}",
            "severity": "info",
            "source": "analyzer",
            "detail": diag,
        })
    if circuit_active:
        flags.append({
            "code": "circuit_breaker_active",
            "severity": "critical",
            "source": "state",
            "detail": state_manager.load_circuit_breaker(),
        })
    if has_position:
        flags.append({
            "code": "existing_position",
            "severity": "info",
            "source": "state",
            "detail": {"ts_code": candidate.get("ts_code")},
        })
    tier = _get(candidate, "selection", "tier")
    final_score = _get(candidate, "scores", "final_score")
    if tier is not None or final_score is not None:
        flags.append({
            "code": "egs_selection_context",
            "severity": "info",
            "source": "egs",
            "detail": {"tier": tier, "final_score": final_score},
        })
    return flags


def _build_evidence(payload: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = [
        {"field_path": "analysis_input.schema_version", "value": payload.get("schema_version"), "source": "analysis_input"},
        {"field_path": "source.screening_engine_version", "value": _get(payload, "source", "screening_engine_version"), "source": "analysis_input"},
        {"field_path": "candidate.ts_code", "value": candidate.get("ts_code"), "source": "analysis_input"},
        {"field_path": "selection.rank", "value": _get(candidate, "selection", "rank"), "source": "analysis_input"},
        {"field_path": "selection.tier", "value": _get(candidate, "selection", "tier"), "source": "analysis_input"},
        {"field_path": "selection.entry_flag", "value": _get(candidate, "selection", "entry_flag"), "source": "analysis_input"},
        {"field_path": "quote.close", "value": _get(candidate, "quote", "close"), "source": "analysis_input"},
        {"field_path": "scores.final_score", "value": _get(candidate, "scores", "final_score"), "source": "analysis_input"},
        {"field_path": "scores.esp_score", "value": _get(candidate, "scores", "esp_score"), "source": "analysis_input"},
        {"field_path": "scores.cat_score", "value": _get(candidate, "scores", "cat_score"), "source": "analysis_input"},
        {"field_path": "scores.l4_score", "value": _get(candidate, "scores", "l4_score"), "source": "analysis_input"},
        {"field_path": "technical.support.price", "value": _get(candidate, "technical", "support", "price"), "source": "analysis_input"},
        {"field_path": "technical.resistance.price", "value": _get(candidate, "technical", "resistance", "price"), "source": "analysis_input"},
        {"field_path": "industry.sw_l1_name", "value": _get(candidate, "industry", "sw_l1_name"), "source": "analysis_input"},
        {"field_path": "industry.sw_l2_name", "value": _get(candidate, "industry", "sw_l2_name"), "source": "analysis_input"},
    ]
    return [item for item in evidence if item["value"] is not None]


def _build_unknowns(candidate: dict[str, Any]) -> list[dict[str, str]]:
    unknowns = [
        {
            "field": "entry_plan.price",
            "reason": "not_implemented_phase4",
            "note": "Phase 4 v1 does not compute deterministic entry price.",
        },
        {
            "field": "exit_plan.stop_loss",
            "reason": "not_implemented_phase4",
            "note": "ATR/technical stop-loss engine is out of Phase 4 minimal scope.",
        },
        {
            "field": "exit_plan.take_profit_1",
            "reason": "not_implemented_phase4",
            "note": "Take-profit levels are reserved for later analyzer/execution phases.",
        },
        {
            "field": "position_size.shares",
            "reason": "not_implemented_phase4",
            "note": "M6.3 position sizing is reserved for Phase 5 execution work.",
        },
        {
            "field": "llm_notes.sections",
            "reason": "requires_llm",
            "note": "Industry trend, regulation, policy/news and hidden-risk interpretation require optional LLM enrichment.",
        },
    ]
    for field, path in [
        ("technical.atr.atr_14", ("technical", "atr", "atr_14")),
        ("technical.rsi_14", ("technical", "rsi_14")),
        ("technical.macd", ("technical", "macd", "dif")),
    ]:
        if _get(candidate, *path) is None:
            unknowns.append({
                "field": field,
                "reason": "data_missing",
                "note": "analysis_input does not contain this technical value.",
            })
    return unknowns


def _build_llm_sections(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = candidate.get("llm_tasks")
    if not isinstance(tasks, list):
        return []
    sections = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        prompt_name = str(task.get("prompt") or "").strip()
        task_type = str(task.get("task_type") or prompt_name or "").strip() or None
        task_id = str(task.get("task_id") or "").strip() or None
        modern_task = bool(task.get("task_type"))
        code = str(task.get("id") or task.get("code") or
                   (task_id if modern_task else prompt_name) or prompt_name or "llm_task")
        prompt_ref = task.get("prompt_ref")
        if prompt_ref is None and prompt_name:
            prompt_file = PROMPT_REF_ALIASES.get(prompt_name, prompt_name)
            prompt_ref = f"skills/a_short_analysis/prompts/{prompt_file}.md"
        sections.append({
            "code": code,
            "task_id": task_id,
            "task_type": task_type,
            "title": str(task.get("title") or prompt_name or code),
            "status": "unknown",
            "prompt_ref": None if prompt_ref is None else str(prompt_ref),
            "content": None,
            "confidence": "unknown",
        })
    return sections


def build_legacy_task_enrichment(report: dict[str, Any], task_results: list[dict[str, Any]],
                                 generated_at: str | None = None) -> dict[str, Any]:
    """Build a deterministic Phase 4 patch for one candidate's six task results."""
    expected = {
        (str(section.get("task_id") or section.get("code")),
         str(section.get("task_type") or section.get("title")))
        for section in ((report.get("llm_notes") or {}).get("sections") or [])
    }
    actual = {(str(item.get("task_id")), str(item.get("task_type"))) for item in task_results}
    if not expected or expected != actual or len(actual) != len(task_results):
        raise ValueError("legacy task results do not map one-to-one to report task configuration")
    sections = []
    for item in task_results:
        status = str(item.get("status") or "unknown")
        section_status = "completed" if status == "completed" else "skipped" if status in {
            "delegated", "provider_unavailable", "window_incomplete"
        } else "unknown"
        sections.append({
            "code": str(item["task_id"]),
            "task_id": str(item["task_id"]),
            "task_type": str(item["task_type"]),
            "title": str(item["task_type"]),
            "status": section_status,
            "prompt_ref": "engine/a_short_legacy_llm_tasks.py",
            "content": result_content(item),
            "confidence": "high" if section_status == "completed" else "unknown",
        })
    return {
        "schema_name": "deterministic_report_enrichment",
        "schema_version": "1.3.0",
        "target": {
            "as_of": str(report["as_of"]),
            "ts_code": str(report["ts_code"]),
            "report_schema_version": str(report["schema_version"]),
        },
        "generated_at": generated_at or str(report["generated_at"]),
        "source": {
            "kind": "deterministic", "model": None,
            "prompt_refs": ["engine/a_short_legacy_llm_tasks.py"],
        },
        "llm_notes": {"enabled": True, "sections": sections},
    }


def _build_analyzer_invocations(veto: dict[str, Any]) -> list[dict[str, Any]]:
    reasons_by_code = {str(r.get("code")): r for r in (veto.get("reasons") or []) if r.get("code")}
    diagnostics_by_code: dict[str, list[dict[str, Any]]] = {}
    for diag in veto.get("diagnostics") or []:
        code = str(diag.get("code"))
        diagnostics_by_code.setdefault(code, []).append(diag)

    invocations = []
    for code in veto.get("enabled_rules") or []:
        if code in reasons_by_code:
            status = "fired"
            detail = reasons_by_code[code].get("detail") or {}
        elif code in diagnostics_by_code:
            status = "diagnostic"
            detail = {"diagnostics": diagnostics_by_code[code]}
        else:
            status = "passed"
            detail = {}
        invocations.append({
            "code": code,
            "version": int(RULE_VERSIONS[code]),
            "status": status,
            "detail": detail,
        })
    return invocations


def validate_report(report: dict[str, Any], schema_path: Path = SCHEMA_PATH) -> None:
    _validate_json_object(
        report,
        schema_path,
        error_prefix="deterministic_report schema validation failed",
    )


def load_enrichment(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_enrichment(enrichment: dict[str, Any],
                        schema_path: Path = ENRICHMENT_SCHEMA_PATH) -> None:
    _validate_json_object(
        enrichment,
        schema_path,
        error_prefix="deterministic_report_enrichment schema validation failed",
    )


def apply_enrichment(report: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
    target = enrichment.get("target") or {}
    mismatches = []
    for field in ("as_of", "ts_code"):
        if str(target.get(field)) != str(report.get(field)):
            mismatches.append(field)
    if str(target.get("report_schema_version")) != str(report.get("schema_version")):
        mismatches.append("report_schema_version")
    if mismatches:
        raise ValueError(f"enrichment target mismatch: {', '.join(mismatches)}")
    sections = ((enrichment.get("llm_notes") or {}).get("sections") or [])
    task_pairs = [(section.get("task_id"), section.get("task_type")) for section in sections]
    if len(task_pairs) != len(set(task_pairs)):
        raise ValueError("enrichment contains duplicate task sections")
    configured = {
        (section.get("task_id"), section.get("task_type"))
        for section in ((report.get("llm_notes") or {}).get("sections") or [])
    }
    if any(pair != (None, None) for pair in task_pairs) and set(task_pairs) != configured:
        raise ValueError("enrichment task sections do not match report task configuration")

    # Deep copy so downstream mutations of the returned report can't reach
    # back into the caller's report (e.g. mutating merged["risk_flags"] would
    # otherwise mutate the original list since dict() is a shallow copy).
    merged = copy.deepcopy(report)
    merged["llm_notes"] = copy.deepcopy(enrichment["llm_notes"])
    merged["data_lineage"]["enrichment_applied"] = True
    merged["data_lineage"]["enrichment_source"] = copy.deepcopy(enrichment["source"])
    if (enrichment.get("source") or {}).get("kind") == "deterministic":
        merged["unknowns"] = [
            item for item in merged.get("unknowns") or []
            if item.get("field") != "llm_notes.sections"
        ]
    return merged


def _validate_json_object(obj: dict[str, Any], schema_path: Path, error_prefix: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "jsonschema is required to validate Phase 4 report contracts. "
            "Install with: python -m pip install -r requirements.txt"
        ) from exc

    with Path(schema_path).open("r", encoding="utf-8") as f:
        schema = json.load(f)
    Draft7Validator.check_schema(schema)
    errors = sorted(Draft7Validator(schema).iter_errors(obj), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        path = "$" + "".join(f"[{repr(p)}]" for p in first.path)
        raise ValueError(f"{error_prefix} at {path}: {first.message}")


def render_markdown(report: dict[str, Any]) -> str:
    decision = report["decision"]
    entry = report["entry_plan"]
    exit_plan = report["exit_plan"]
    position = report["position_size"]
    flags = report.get("risk_flags") or []
    unknowns = report.get("unknowns") or []
    veto = report.get("veto") or {}
    llm_notes = report.get("llm_notes") or {}

    price_block = " / ".join([
        _fmt_unknown(entry.get("price")),
        _fmt_unknown(exit_plan.get("take_profit_1")),
        _fmt_unknown(exit_plan.get("take_profit_2")),
        _fmt_unknown(exit_plan.get("stop_loss")),
    ])
    trigger = entry.get("condition")
    if not trigger or trigger == "unknown":
        trigger = decision["reason_code"]

    table = [
        "| target | action | shares | entry/tp1/tp2/stop | type | priority | trigger |",
        "|---|---|---:|---|---|---|---|",
        (
            f"| {report['ts_code']} {report['name']} | {decision['action']} | "
            f"{_fmt_unknown(position.get('shares'))} | {price_block} | "
            f"{entry.get('type') or 'unknown'} | pending_llm_enrich | "
            f"{trigger} |"
        ),
    ]

    lines = [
        f"# M6.7 Deterministic Report - {report['ts_code']} {report['name']}",
        "",
        f"- as_of: `{report['as_of']}`",
        f"- decision: `{decision['action']}` (`{decision['reason_code']}`, confidence={decision['confidence']})",
        f"- analyzer_vetoed: `{veto.get('vetoed')}`",
        "",
        "## M6.7 Table",
        "",
        *table,
        "",
        "## Deterministic Summary",
        "",
        "- current_environment: unknown",
        "- volatility_state: unknown",
        "- current_price_and_cost: see `evidence.quote.close`",
        "- veto_review: " + ("hard veto fired" if veto.get("vetoed") else "passed or diagnostic only"),
        "- sector_fund_event: requires_llm",
        "- risk_control_trigger: not_implemented_phase4",
        "",
        "## Risk Flags",
        "",
    ]
    if flags:
        lines.extend(f"- `{f['code']}` [{f['severity']}/{f['source']}]" for f in flags)
    else:
        lines.append("- none")
    lines.extend(["", "## Unknowns", ""])
    lines.extend(f"- `{u['field']}`: {u['reason']} - {u['note']}" for u in unknowns)
    lines.extend(["", "## LLM Notes", "", f"- enabled: {str(bool(llm_notes.get('enabled'))).lower()}"])
    for section in llm_notes.get("sections") or []:
        lines.append(
            f"- `{section.get('code')}` [{section.get('status')}/"
            f"{section.get('confidence')}]: {_fmt_unknown(section.get('content'))}"
        )
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    validate_report(report)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = str(report["ts_code"])
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    _atomic_write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _atomic_write_text(md_path, render_markdown(report))
    return json_path, md_path


def _atomic_write_text(path: Path, text: str) -> None:
    """Atomically replace one report surface; incomplete files are never published."""
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _get(obj: Any, *keys: str, default=None):
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _fmt_unknown(value: Any) -> str:
    if value is None:
        return "unknown"
    return str(value)


def _analysis_input_l3_mode(payload: dict[str, Any]) -> str:
    l3_mode = str(_get(payload, "source", "l3_mode", default="today") or "today")
    if l3_mode not in {"pit", "today", "neutralize"}:
        raise ValueError(f"unsupported analysis_input.source.l3_mode: {l3_mode!r}")
    return l3_mode


def _analysis_input_l3_lineage(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    coverage = source.get("l3_coverage") if isinstance(source.get("l3_coverage"), dict) else {}
    return {
        "l3_provider": source.get("l3_provider"),
        "l3_snapshot_date": source.get("l3_snapshot_date"),
        "l3_catalog_digest": coverage.get("catalog_digest"),
        "l3_catalog_board_count": coverage.get("catalog_board_count"),
        "l3_scoring_universe": coverage.get("scoring_universe"),
        "l3_coverage_complete": coverage.get("complete"),
    }


def _state_evaluation_time(as_of: str, state_now: datetime | str | None = None) -> str:
    if state_now is not None:
        return _normalize_state_now(state_now)
    try:
        replay_day = datetime.strptime(as_of, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"invalid as_of for state replay: {as_of!r}") from exc
    replay_time = replay_day.replace(hour=15, minute=0, second=0, tzinfo=A_SHARE_STATE_REPLAY_TZ)
    return replay_time.isoformat(timespec="seconds")


def _normalize_state_now(value: datetime | str) -> str:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            raise ValueError("state_now must be a non-empty ISO timestamp")
        parse_text = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            dt = datetime.fromisoformat(parse_text)
        except ValueError as exc:
            raise ValueError(f"invalid state_now timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _state_snapshot_ref() -> str:
    refs = []
    for label, path in [
        ("positions", state_manager.POSITIONS_PATH),
        ("veto_log", state_manager.VETO_LOG_PATH),
        ("circuit_breaker", state_manager.CIRCUIT_BREAKER_PATH),
    ]:
        refs.append(f"{label}:{_file_digest(path)}")
    return ";".join(refs)


def _file_digest(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        return "missing"
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate one deterministic Phase 4 analysis report.")
    parser.add_argument("--as-of", required=True, help="YYYYMMDD result directory date.")
    parser.add_argument("--ts-code", required=True, help="Candidate ts_code, e.g. 600415.SH.")
    parser.add_argument("--input-path", help="Optional explicit analysis_input.json path.")
    parser.add_argument(
        "--state-now",
        help=(
            "Optional ISO timestamp used to evaluate JSON state such as "
            "circuit_breaker.expires_at. Default: as-of A-share close "
            "(15:00 +08:00), not wall-clock now."
        ),
    )
    parser.add_argument(
        "--enrichment-path",
        help="Optional deterministic_report_enrichment JSON path. Only llm_notes are merged.",
    )
    parser.add_argument("--out-dir", help="Output directory. Default: result/a_short/<as-of>/reports")
    args = parser.parse_args(argv)

    input_path = Path(args.input_path) if args.input_path else None
    payload = load_analysis_input(args.as_of, input_path=input_path)
    # Sanity: CLI --as-of must match the file's trade_date when --input-path is
    # explicit. Without this guard, a typo'd --input-path pointing at the wrong
    # day silently produces a report under the wrong as_of directory.
    payload_trade_date = str(payload.get("trade_date") or "")
    if payload_trade_date and payload_trade_date != str(args.as_of):
        raise SystemExit(
            f"[FATAL] --as-of {args.as_of} mismatches analysis_input.trade_date "
            f"{payload_trade_date!r}; check --input-path or rerun egs_main."
        )
    candidate = find_candidate(payload, args.ts_code)
    report = build_report(payload, candidate, state_now=args.state_now)
    if args.enrichment_path:
        enrichment = load_enrichment(Path(args.enrichment_path))
        validate_enrichment(enrichment)
        report = apply_enrichment(report, enrichment)
    out_dir = Path(args.out_dir) if args.out_dir else LIVE_RESULT_ROOT / args.as_of / "reports"
    json_path, md_path = write_report(report, out_dir)
    print(f"[OK] wrote {json_path.relative_to(ROOT) if json_path.is_relative_to(ROOT) else json_path}")
    print(f"[OK] wrote {md_path.relative_to(ROOT) if md_path.is_relative_to(ROOT) else md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
