"""One-shot D4 A-short policy ablation with a post-hoc recorded input hash.

This is deliberately descriptive.  It recomputes the named Rule6 combinations
from the frozen rank-sample columns and reports every preregistered head.  It
cannot choose a winner, delete a rule, alter EGS/M6.7, or turn the 4d/5d crash
comparison into a historical backtest; that last question remains a separately
captured forward matched-cohort result.  The spent 2026-07-14 run did not
pre-bind its input hash: its hash is only a reviewer-trust-only provenance
record.  A future D4 run must use a new preregistration that pins and verifies
the input path and expected SHA-256 before it can run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from jsonschema import Draft7Validator
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.analyzer.rule6_hard_veto import DEFAULT_RULES
from engine.a_short_nullable_bool import fail_closed_risk_bool
from runners.backtest_rank import apply_analyzer_veto


PREREG_PATH = ROOT / "research/preregistrations/a_short_d4_policy_ablation_20260714.json"
PREREG_SCHEMA = ROOT / "schemas/a_short_d4_policy_ablation_preregistration.schema.json"
LEDGER_PATH = ROOT / "research/ledgers/a_short_d4_policy_ablation_program_test_budget_ledger_20260714.json"
LEDGER_SCHEMA = ROOT / "schemas/program_test_budget_ledger.schema.json"
SUMMARY_SCHEMA = ROOT / "schemas/a_short_d4_policy_ablation_execution_summary.schema.json"
OUT_PATH = ROOT / "research/results/a_short_d4_policy_ablation_20260714/execution_summary.json"
TEST_ID = "a_short_d4_policy_ablation_20260714"


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _validate(value: dict, schema_path: Path, label: str) -> None:
    errors = sorted(Draft7Validator(_load(schema_path)).iter_errors(value), key=lambda err: list(err.path))
    if errors:
        first = errors[0]
        location = "/".join(map(str, first.path)) or "<root>"
        raise ValueError(f"{label} schema invalid at {location}: {first.message}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bool(series: pd.Series) -> pd.Series:
    text_true = series.fillna(False).astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y"})
    numeric_true = pd.to_numeric(series, errors="coerce").eq(1)
    return text_true | numeric_true


def _atomic_write_json(path: Path, value: dict) -> None:
    """Atomically replace one JSON artifact without leaving a partial official file."""
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _commit_spent_result(*, summary: dict, ledger: dict, out_path: Path, ledger_path: Path) -> None:
    """Spend first, then publish: a late failure is fail-closed, never an unspent result."""
    _atomic_write_json(ledger_path, ledger)
    _atomic_write_json(out_path, summary)


def _finite(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").replace([math.inf, -math.inf], float("nan"))


def _monthly_t(returns: pd.Series, dates: pd.Series) -> float | None:
    monthly = pd.DataFrame({"month": dates.astype(str).str[:6], "ret": returns}).groupby("month")["ret"].mean()
    if len(monthly) < 2:
        return None
    sd = float(monthly.std(ddof=1))
    if not math.isfinite(sd) or sd == 0:
        return None
    return round(float(monthly.mean()) / (sd / math.sqrt(len(monthly))), 8)


def _max_drawdown(returns: pd.Series, dates: pd.Series) -> float | None:
    if returns.empty:
        return None
    daily = pd.DataFrame({"date": dates.astype(str), "ret": returns}).groupby("date")["ret"].mean().sort_index()
    wealth = (1 + daily / 100.0).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    return round(float(drawdown.min()) * 100.0, 8)


def metric(identifier: str, frame: pd.DataFrame) -> dict:
    eligible = frame.loc[frame["ret_5d_status"].eq("ok")].copy()
    returns = _finite(eligible["ret_5d_t1_net"])
    eligible = eligible.loc[returns.notna()].copy()
    returns = returns.loc[returns.notna()]
    if eligible.empty:
        return {"id": identifier, "sample_count": 0, "trade_date_count": 0, "mean_net_return_pct": None,
                "monthly_t": None, "max_drawdown_pct": None, "win_rate_pct": None}
    return {
        "id": identifier,
        "sample_count": int(len(eligible)),
        "trade_date_count": int(eligible["trade_date"].astype(str).nunique()),
        "mean_net_return_pct": round(float(returns.mean()), 8),
        "monthly_t": _monthly_t(returns, eligible["trade_date"]),
        "max_drawdown_pct": _max_drawdown(returns, eligible["trade_date"]),
        "win_rate_pct": round(float((returns > 0).mean()) * 100.0, 8),
    }


def _parent_population(samples: pd.DataFrame) -> pd.DataFrame:
    hard_veto = (
        samples["hard_veto"].map(fail_closed_risk_bool)
        if "hard_veto" in samples
        else pd.Series(False, index=samples.index)
    )
    return samples.loc[~hard_veto].copy()


def _tier1_with_rules(samples: pd.DataFrame, rules: tuple[str, ...] | list[str]) -> pd.DataFrame:
    replayed = apply_analyzer_veto(samples, list(rules))
    tier1 = replayed["tier"].astype(str).eq("Tier1")
    return replayed.loc[tier1 & ~replayed["analyzer_vetoed"].fillna(False).astype(bool)].copy()


def _crash_window_status(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {"status": "not_available", "legacy_confirmed_days": 4, "candidate_confirmed_days": 5,
                "reason": "no crash-veto forward cohort summary was supplied"}
    payload = _load(path)
    variants = payload.get("variants") or []
    by_scope = {str(row.get("scope")): row for row in variants if isinstance(row, dict)}
    legacy = by_scope.get("legacy_official_4d")
    fifth = by_scope.get("active_5d_incremental_rank_impact")
    if not legacy or not fifth:
        raise ValueError("crash-veto summary lacks the frozen 4d and incremental-5d cohorts")
    return {"status": "forward_pending", "legacy_confirmed_days": 4, "candidate_confirmed_days": 5,
            "reason": "separate matched cohorts are frozen; do not use this historical Rule6 ablation as a 4d/5d result"}


def build_summary(*, samples_path: Path, prereg: dict, generated_at: str,
                  crash_summary_path: Path | None = None) -> dict:
    _validate(prereg, PREREG_SCHEMA, "D4 preregistration")
    samples = pd.read_csv(samples_path, low_memory=False)
    required = prereg["source_contract"]["rank_samples_required_columns"]
    missing = sorted(set(required) - set(samples.columns))
    if missing:
        raise ValueError(f"rank samples missing frozen columns: {missing}")
    parent = _parent_population(samples)
    rules = tuple(prereg["frozen_tests"]["rule6_ablation"]["rules"])
    if rules != tuple(DEFAULT_RULES):
        raise ValueError("runtime Rule6 namespace drifted from frozen D4 preregistration")
    current = _tier1_with_rules(parent, rules)
    legacy = _tier1_with_rules(parent, ())
    population = [
        metric("all_pre_veto", parent),
        metric("tier1_pre_veto", parent.loc[parent["tier"].astype(str).eq("Tier1")]),
        metric("tier2_pre_veto", parent.loc[parent["tier"].astype(str).eq("Tier2")]),
        metric("tier1_current_rule6_passed", current),
    ]
    policy = [metric("tier1_current_all_rule6", current), metric("tier1_legacy_no_rule6", legacy)]
    ablations = []
    for rule in rules:
        ablations.append(metric(f"leave_one_out_{rule}", _tier1_with_rules(parent, [r for r in rules if r != rule])))
    for rule in rules:
        ablations.append(metric(f"only_one_on_{rule}", _tier1_with_rules(parent, [rule])))
    return {
        "schema_name": "a_short_d4_policy_ablation_execution_summary",
        "schema_version": "1.1.0",
        "generated_at": generated_at,
        "preregistration_ref": {"path": "research/preregistrations/a_short_d4_policy_ablation_20260714.json", "sha256": _sha256(PREREG_PATH)},
        "input_integrity": {"rank_samples_sha256": _sha256(samples_path),
                            "binding_status": "posthoc_recorded_unverified",
                            "row_count": int(len(samples)), "provider_calls": 0, "egs_rerun": False},
        "population_views": population,
        "policy_comparison": policy,
        "rule6_ablation": ablations,
        "crash_window_comparison": _crash_window_status(crash_summary_path),
        "decision": {"status": "descriptive_research_only", "rule_deletion_allowed": False, "production_switch_allowed": False,
                     "next_action": "independent_Claude_review_then_wait_for_separate_forward_crash_window_outcome"},
        "boundary": {"production": False, "buy_advice": False, "ship_gate_evidence": False},
    }


def execute(*, samples_path: Path, generated_at: str, out_path: Path = OUT_PATH,
            prereg_path: Path = PREREG_PATH, ledger_path: Path = LEDGER_PATH,
            crash_summary_path: Path | None = None) -> dict:
    if prereg_path.resolve() != PREREG_PATH.resolve() or ledger_path.resolve() != LEDGER_PATH.resolve():
        raise ValueError("D4 only accepts its frozen preregistration and singleton ledger")
    prereg = _load(prereg_path)
    ledger = _load(ledger_path)
    _validate(prereg, PREREG_SCHEMA, "D4 preregistration")
    _validate(ledger, LEDGER_SCHEMA, "D4 ledger")
    if ledger["budget_policy"]["tests_spent_count"] != 0 or ledger["test_spend_log"]:
        raise ValueError("D4 singleton test is already spent; no rerun or rescue is allowed")
    if len(ledger["planned_tests"]) != 1 or ledger["planned_tests"][0]["test_id"] != TEST_ID:
        raise ValueError("D4 ledger planned test is not the frozen singleton")
    summary = build_summary(samples_path=samples_path, prereg=prereg, generated_at=generated_at,
                            crash_summary_path=crash_summary_path)
    _validate(summary, SUMMARY_SCHEMA, "D4 execution summary")
    result_ref = out_path.relative_to(ROOT).as_posix()
    ledger["ledger_status"] = "active_no_new_test_authorized"
    ledger["budget_policy"]["tests_spent_count"] = 1
    ledger["budget_policy"]["tests_available_without_new_review"] = 0
    ledger["test_spend_log"] = [{"test_id": TEST_ID, "preregistration_ref": "research/preregistrations/a_short_d4_policy_ablation_20260714.json", "result_ref": result_ref,
        "status": "spent_passed_research_continue_only", "tests_spent": 1, "promotion_relevant": True,
        "result_summary": "Executed exactly once from a local rank-samples file whose SHA-256 is recorded post-hoc only; provenance is reviewer-trust-only. All named populations and Rule6 ablations were emitted, while 4d/5d remains a separate forward-pending cohort comparison.",
        "allowed_followup": "Independent Claude review may interpret only the descriptive report. No rule deletion, production change, rerun, or crash-window decision is authorized."}]
    ledger["planned_tests"] = []
    ledger["next_required_actions"] = ["Independent Claude review of the D4 preregistration, source hash, all fixed heads, and no-rule-deletion boundary.", "Wait for the separate 4d/5d matched-cohort forward result; do not infer it from historical Rule6 ablations.", "Any new outcome test requires a new reviewed preregistration and user approval."]
    _validate(ledger, LEDGER_SCHEMA, "spent D4 ledger")
    _commit_spent_result(summary=summary, ledger=ledger, out_path=out_path, ledger_path=ledger_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the one-shot, non-production A-short D4 policy ablation.")
    parser.add_argument("--samples", type=Path, required=True, help="existing local rank_samples.csv; never fetched or regenerated")
    parser.add_argument("--crash-summary", type=Path, default=None, help="optional existing 4d/5d forward-cohort summary")
    parser.add_argument("--generated-at", default="2026-07-14T18:30:00+08:00")
    args = parser.parse_args(argv)
    summary = execute(samples_path=args.samples, crash_summary_path=args.crash_summary, generated_at=args.generated_at)
    print(f"[OK] D4 spent once: rows={summary['input_integrity']['row_count']} output={OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
