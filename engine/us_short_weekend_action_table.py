# -*- coding: utf-8 -*-
"""US-short weekend-pipeline §11.3 action_table projection — batch4 slice 4d-ii-m1 (machine layer → flat columns).

Design authority: docs/us_short_system_design.md §11.1 (机器层 = 全字段; 周报/csv 从机器层渲染) / §11.3
(action_table.csv 完整列) / §18.2 batch4 slice 4d.

The post-pass after 4d-ii-k (`assemble_machine_record`). The §10 machine record K produces carries the RICH
machine layer (the nested `price` engine result, the `sizing` dict, `veto`, `score`, …) + per-row
`field_records`, but it does NOT carry the FLAT §11.3 action_table columns — so the content-agnostic
`us_short_action_table_renderer` (which reads each column by name, `row.get(col)`) would render mostly-empty
cells. This slice projects the rich machine layer onto the flat §11.3 columns so the action_table.csv (and the
§11.2 one-glance table, slice 4d-ii-m2) render POPULATED:

  * the price engine's `price.action_fields` is a dict whose KEYS are already §11.3 column names (entry_plan /
    valid_entry_high / order_type / stop_clear_price / take_profit_* / risk_reward_ratio / price_engine_used /
    price_sub_mode / …) — each key that is a frozen §11.3 column is lifted onto the row;
  * `sizing.desired_model_shares` (a real sized build) → `model_position_size_shares`.
  Columns with NO v1 pipeline source (macro_cluster / overextension_state / coverage_status /
  live_permission_status / model_position_size_amount / …) are deliberately left EMPTY — honest, not fabricated
  (they land in batch5 / the §11.2 assembly / later forward calibration).

Because the projection makes price.action_fields the OFFICIAL §11.3 cells, the lift boundary VALUE-validates the
§6 price-engine contract (`_validate_price_projection`) BEFORE lifting: any present price/ratio column must be
finite, and an EXECUTABLE row must carry the required executable price fields for its row class (a 建仓 /
executable holding can never render a blank or nonnumeric entry·stop·RR while still showing an action + size);
a non-executable observe/reject row keeps honest partial output (§6). The flattened record then stays §10-clean:
`flatten_machine_record` re-runs `validate_official_machine_record` and fails closed if the projection ever broke the §10
contract (a lifted design-locked enum value is re-checked too). Single-source consumer-validation at the
boundary (§9 action/reason via `action_reason_error`, canonical-unique ticker, the §6 price contract via the
engine's `PRICE_ENGINES` / `PRICE_SUB_MODES` + the column subsets triangulated ⊆ the engine column sets), the
same boundary every weekend stage enforces; the column SET is the frozen contract via `action_table_columns()`.
Pure/offline; no provider/live/network; no broker/auto-order; no A-share crossing.
"""
from __future__ import annotations

import math
import json
from pathlib import Path

from engine.us_short_action_table_renderer import action_table_columns, render_action_table
from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_hard_veto import row_source_to_context
from engine.us_short_no_dangling_validator import validate_official_machine_record
from engine.us_short_price_engine import PRICE_ENGINES, PRICE_SUB_MODES
from engine.us_short_ship_gate_sizing import ship_gate_sizing
from engine.us_short_weekend_decision import action_price_error, action_reason_error

# the frozen §11.3 column set (single source) — only keys that ARE a real column are lifted from the rich layer.
_ACTION_TABLE_COLUMNS = frozenset(action_table_columns())
_ROOT = Path(__file__).resolve().parent.parent
_ACTION_TABLE_PRESET = _ROOT / "presets" / "us_short_action_table_contract_20260620.json"
_ENUM_CACHE = {}

# §6 price-engine contract enforced at the OFFICIAL §11.3 lift boundary (so an executable row can never render a
# blank / nonnumeric entry·stop·RR while still showing an action + size). Single-source: PRICE_ENGINES /
# PRICE_SUB_MODES from the engine; the required / numeric column subsets are triangulated ⊆ NEW_ENTRY_COLUMNS /
# HOLDING_COLUMNS by a test. Any PRESENT price/ratio column must be finite (a nonnumeric string lifted into an
# official cell is rejected, regardless of executability); a NON-executable (observe/reject) row legitimately
# carries honest partial output (§6 — values default None, filled progressively) so only the numeric check applies.
_NUMERIC_PRICE_COLUMNS = frozenset({
    "pullback_entry_price", "breakout_entry_price", "limit_order_price", "valid_entry_low", "valid_entry_high",
    "effective_support", "effective_resistance", "stop_clear_price", "take_profit_reduce_price",
    "take_profit_exit_price", "event_clear_reference_price", "risk_reward_ratio",
})
# executable support_atr_engine ALWAYS sets these on its executable path (price_engine.py l306-314 + l218-231).
_BUILD_REQUIRED = (
    "entry_plan", "order_type", "order_expiry", "gap_policy", "valid_entry_low", "valid_entry_high",
    "limit_order_price", "stop_clear_price", "take_profit_reduce_price", "take_profit_exit_price",
    "risk_reward_ratio", "min_rr_gate_status", "post_round_rr_status", "price_engine_used", "price_sub_mode",
)
# executable holding_exit_engine ALWAYS sets stop/status before any executable return; take_profit / RR are
# legitimately None only when post_round_rr_status explains a breached / no-target holding.
_HOLDING_REQUIRED = ("stop_clear_price", "post_round_rr_status", "price_engine_used")
_CANDIDATE_ENGINE = "support_atr_engine"
_HOLDING_ENGINE = "holding_exit_engine"
_CANDIDATE_GAP_POLICY = "limit_band_first_session_no_chase"
_CANDIDATE_MIN_RR_STATUS = "pass"
_CANDIDATE_POST_ROUND_STATUS = "ok"
_HOLDING_POST_ROUND_STATUSES = frozenset({"ok", "tp_not_computable"})
_HOLDING_TARGET_FIELDS = ("take_profit_reduce_price", "take_profit_exit_price", "risk_reward_ratio")


def _design_enums():
    if not _ENUM_CACHE:
        _ENUM_CACHE.update(json.loads(_ACTION_TABLE_PRESET.read_text(encoding="utf-8"))["design_locked_enums"])
    return _ENUM_CACHE


class WeekendActionTableError(Exception):
    """The injected machine record is malformed, or the flattened projection is not §10-clean (fail-closed)."""


# the only legal §4.5 selection buckets the producer `_select_top15` emits (single source for the consumer-side
# value validation) + the row_sources that carry a selection record (the Top15-admitted names).
_SELECTION_BUCKETS = frozenset({"core_top", "theme_momentum", "overlap", "core_backfill"})
_SELECTED_ROW_SOURCES = frozenset({"top15_candidate", "holding_in_top15"})
_SELECTION_RECORD_KEYS = frozenset({"selection_rank", "selection_bucket", "core_score", "theme_momentum_score"})


def _flatten_row(row, ct):
    """Project one §10 machine-record row's rich layer onto the flat §11.3 columns (keeping the rich layer +
    field_records). Only frozen §11.3 column keys are lifted; an unsourced column is left untouched (empty)."""
    flat = dict(row)
    price = row.get("price")
    if isinstance(price, dict):
        af = price.get("action_fields")
        if isinstance(af, dict):
            for col, val in af.items():
                if col in _ACTION_TABLE_COLUMNS:   # lift only real §11.3 columns (price engine keys == column names)
                    flat[col] = val
    sizing = row.get("sizing")
    if isinstance(sizing, dict) and sizing.get("status") == "sized":
        flat["model_position_size_shares"] = sizing.get("desired_model_shares")
    # Batch4 has paper evidence only and live mode is hard-gated. Re-derive the official ship-gate cells from
    # the frozen engine on every projection, overwriting any caller-planted flat values. A live-normalized grant
    # belongs to the separately reviewed batch5 evidence path, never to this offline boundary.
    shares = sizing.get("desired_model_shares") if isinstance(sizing, dict) and sizing.get("status") == "sized" else None
    af = row.get("price", {}).get("action_fields", {}) if isinstance(row.get("price"), dict) else {}
    entry = af.get("valid_entry_high") if isinstance(af, dict) else None
    has_model_size = (isinstance(shares, int) and not isinstance(shares, bool) and shares >= 0
                      and _finite(entry) and entry > 0.0)
    amount = float(shares) * float(entry) if has_model_size else 0.0
    veto_tier = row.get("veto", {}).get("veto_tier") if isinstance(row.get("veto"), dict) else None
    gate = ship_gate_sizing(amount, shares if has_model_size else 0,
                            hard_veto=veto_tier in {"entry_hard_veto", "position_hard_veto"},
                            evidence_level="paper", graduated_full_size=False)
    flat["model_position_size_amount"] = gate["model_position_size_amount"] if has_model_size else None
    flat["live_permission_status"] = gate["live_permission_status"]
    flat["live_size_warning"] = gate["live_size_warning"]
    # the PRESERVED Top15 selection_bucket lands on its §11.3 column ONLY from a VALIDATED selection_record
    # (R-USSHORT-BATCH4-SELECTION-TRACE-AND-RECALL-CLOSURE-GAP): a SELECTED row (top15_candidate / holding_in_top15)
    # must carry a well-formed record (exact keys, positive-int rank, legal bucket, finite 0-100 scores); a
    # non-selected holding row must carry NO record. A forged / malformed record fails closed; any caller-planted
    # flat value is cleared first so the cell is set ONLY from the validated bucket.
    flat.pop("selection_bucket", None)
    sel_rec = row.get("selection_record")
    if row.get("row_source") in _SELECTED_ROW_SOURCES:
        if not (isinstance(sel_rec, dict) and set(sel_rec) == _SELECTION_RECORD_KEYS):
            raise WeekendActionTableError(
                f"{ct}: Top15 选择行 selection_record 形状非法（须键 {sorted(_SELECTION_RECORD_KEYS)}）: {sel_rec!r}")
        sr = sel_rec["selection_rank"]
        if not (isinstance(sr, int) and not isinstance(sr, bool) and sr >= 1):
            raise WeekendActionTableError(f"{ct}: selection_record.selection_rank 须正 int: {sr!r}")
        if sel_rec["selection_bucket"] not in _SELECTION_BUCKETS:
            raise WeekendActionTableError(
                f"{ct}: selection_record.selection_bucket 非法（须 ∈ {sorted(_SELECTION_BUCKETS)}）: {sel_rec['selection_bucket']!r}")
        for k in ("core_score", "theme_momentum_score"):
            if not (_finite(sel_rec[k]) and 0.0 <= sel_rec[k] <= 100.0):
                raise WeekendActionTableError(f"{ct}: selection_record.{k} 须为 0-100 有限数: {sel_rec[k]!r}")
        # reconcile the record against THIS row's sibling machine fields (no same-row fork): the landed top-level
        # selection_rank (set by the basket for builds) must equal the record rank; the machine score.core_score
        # (when present) must equal the record core (Codex re-review 5: score/rank conflict).
        landed = row.get("selection_rank")
        if landed is not None and landed != sr:
            raise WeekendActionTableError(f"{ct}: 行 selection_rank {landed!r} != selection_record.selection_rank {sr!r}（同行分叉）")
        score = row.get("score")
        if isinstance(score, dict) and "core_score" in score and score["core_score"] != sel_rec["core_score"]:
            raise WeekendActionTableError(
                f"{ct}: 行 score.core_score {score['core_score']!r} != selection_record.core_score {sel_rec['core_score']!r}（同行分叉）")
        flat["selection_bucket"] = sel_rec["selection_bucket"]
    elif sel_rec is not None:
        raise WeekendActionTableError(f"{ct}: 非 Top15 持仓行不得带 selection_record（伪造拒）: {sel_rec!r}")
    return flat


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _validate_price_projection(row, ct):
    """Fail-closed §6 price-engine contract gate at the OFFICIAL §11.3 lift boundary (before price.action_fields
    is projected into the user-facing CSV columns). Any PRESENT price/ratio column must be finite (a nonnumeric
    value lifted into an official cell is rejected); an EXECUTABLE row must additionally carry the required
    executable fields for its row class — a 建仓 / executable holding with empty / partial action_fields can
    never render a blank entry/stop/RR while still showing an action + size. A non-executable (observe/reject)
    row legitimately carries honest partial output (§6), so only the numeric check applies to it."""
    price = row.get("price")
    if not isinstance(price, dict):
        raise WeekendActionTableError(f"{ct}: price 须为 dict（机器记录契约）: {price!r}")
    af = price.get("action_fields")
    if not isinstance(af, dict):
        raise WeekendActionTableError(f"{ct}: price.action_fields 须为 dict: {af!r}")
    # §9 action↔price 一一对应 (R-USSHORT-BATCH4-ACTION-PRICE-MAPPING-GAP): independent of executable / row class,
    # an OFFICIAL action that names a price must carry it BEFORE it is projected onto the §11.3 columns (runs
    # BEFORE the executable early-return below). Single source: action_price_error (decision §9).
    price_err = action_price_error(row.get("final_action"), af)
    if price_err:
        raise WeekendActionTableError(f"{ct}: {price_err}")
    for col in _NUMERIC_PRICE_COLUMNS:                       # any present price/ratio cell must be finite-or-None
        v = af.get(col)
        if v is not None and not _finite(v):
            raise WeekendActionTableError(f"{ct}: price.action_fields[{col}] 须为有限数或缺省: {v!r}")
    if price.get("executable") is not True:
        return                                              # observe/reject: honest partial output (§6), no required gate
    try:
        ctx = row_source_to_context(row.get("row_source"))   # single-source candidate/holding (raises on unknown)
    except ValueError as e:
        raise WeekendActionTableError(f"{ct}: {e}")
    engine = af.get("price_engine_used")
    if ctx == "candidate":
        missing = [c for c in _BUILD_REQUIRED if af.get(c) is None]
        if missing:
            raise WeekendActionTableError(f"{ct}: executable candidate missing required price fields {missing}")
        if engine not in PRICE_ENGINES or engine != _CANDIDATE_ENGINE:
            raise WeekendActionTableError(f"{ct}: candidate 须 price_engine_used==support_atr_engine: {engine!r}")
        if af.get("price_sub_mode") not in PRICE_SUB_MODES:
            raise WeekendActionTableError(f"{ct}: candidate price_sub_mode 须 ∈ {list(PRICE_SUB_MODES)}: {af.get('price_sub_mode')!r}")
        if af.get("order_type") not in set(_design_enums()["order_type"]):
            raise WeekendActionTableError(f"{ct}: candidate order_type is outside the frozen enum: {af.get('order_type')!r}")
        if af.get("order_expiry") not in set(_design_enums()["order_expiry"]):
            raise WeekendActionTableError(f"{ct}: candidate order_expiry is outside the frozen v1 enum: {af.get('order_expiry')!r}")
        if af.get("gap_policy") != _CANDIDATE_GAP_POLICY:
            raise WeekendActionTableError(f"{ct}: candidate gap_policy must be {_CANDIDATE_GAP_POLICY!r}: {af.get('gap_policy')!r}")
        if af.get("min_rr_gate_status") != _CANDIDATE_MIN_RR_STATUS:
            raise WeekendActionTableError(
                f"{ct}: candidate min_rr_gate_status must be {_CANDIDATE_MIN_RR_STATUS!r}: "
                f"{af.get('min_rr_gate_status')!r}"
            )
        if af.get("post_round_rr_status") != _CANDIDATE_POST_ROUND_STATUS:
            raise WeekendActionTableError(
                f"{ct}: candidate post_round_rr_status must be {_CANDIDATE_POST_ROUND_STATUS!r}: "
                f"{af.get('post_round_rr_status')!r}"
            )
    else:  # holding
        if engine not in PRICE_ENGINES or engine != _HOLDING_ENGINE:
            raise WeekendActionTableError(f"{ct}: holding 须 price_engine_used==holding_exit_engine: {engine!r}")
        if af.get("price_sub_mode") is not None:
            raise WeekendActionTableError(f"{ct}: holding price_sub_mode 须 None（非 pullback/breakout）: {af.get('price_sub_mode')!r}")
        missing = [c for c in _HOLDING_REQUIRED if af.get(c) is None]
        if missing:
            raise WeekendActionTableError(f"{ct}: executable holding 缺必填价格字段 {missing}")
        status = af.get("post_round_rr_status")
        if status not in _HOLDING_POST_ROUND_STATUSES:
            raise WeekendActionTableError(f"{ct}: holding post_round_rr_status is invalid: {status!r}")
        trace = price.get("trace")
        if not isinstance(trace, dict) or not isinstance(trace.get("breached"), bool):
            raise WeekendActionTableError(f"{ct}: executable holding price.trace.breached must be bool: {trace!r}")
        breached = trace["breached"]
        missing_targets = [c for c in _HOLDING_TARGET_FIELDS if af.get(c) is None]
        if status == "ok" and not breached and missing_targets:
            raise WeekendActionTableError(
                f"{ct}: non-breached holding with post_round_rr_status='ok' missing TP/RR fields {missing_targets}"
            )
        if status == "tp_not_computable" and not missing_targets:
            raise WeekendActionTableError(
                f"{ct}: holding post_round_rr_status='tp_not_computable' but TP/RR fields are populated"
            )


def flatten_machine_record(machine_record):
    """Project the rich §10 machine record onto the flat §11.3 action_table columns; returns a NEW machine
    record with each row's rich layer + field_records preserved AND the flat columns populated.

    machine_record = the 4d-ii-k `assemble_machine_record` output {schema_name, schema_version, as_of, run_origin, rows}
        (top-level keys are preserved through the projection, so run_origin rides onto the written machine artifact).

    Every row is consumer-validated fail-closed (§9 action/reason single-source + canonical-unique ticker),
    then the rich layer is projected onto the flat §11.3 columns. The flattened record is re-checked §10-clean
    (`render_action_table` runs `validate_official_machine_record`), so a projection that ever broke the §10 contract —
    e.g. a lifted design-locked enum with an illegal value — fails closed. Raises WeekendActionTableError on a
    malformed record / row, a bad §9 pair, a non-canonical / duplicate ticker, or a not-§10-clean projection."""
    if not (isinstance(machine_record, dict) and isinstance(machine_record.get("rows"), list)):
        raise WeekendActionTableError("machine_record 须为含 rows(list) 的 4d-ii-k 机器记录")

    # OFFICIAL consumer gate (R-USSHORT-BATCH4-MACHINE-REGISTRY-COMPLETENESS-GAP): reject a record whose §10
    # registry was STRIPPED after assembly before it is projected into official §11.3 output. The manifest floor
    # (hard_veto / price / market_risk_regime) is UNCONDITIONAL, so deleting raw evidence + field_records cannot
    # forge an empty/partial registry past this boundary (the bare generic validator stays field_id-agnostic).
    _off = validate_official_machine_record(machine_record)
    if not _off["clean"]:
        raise WeekendActionTableError(
            f"machine record 非 official §10-clean（manifest 反查失败）: {_off['violations'][:5]!r}")

    out_rows, seen = [], set()
    for row in machine_record["rows"]:
        if not (isinstance(row, dict) and isinstance(row.get("final_action"), str)):
            raise WeekendActionTableError(f"row 形状非法（须为 4d-ii-k 机器记录行）: {row!r}")
        err = action_reason_error(row["final_action"], row.get("observe_reason_type"))   # §9 single-source
        if err:
            raise WeekendActionTableError(err)
        ct = canonical_us_ticker(row.get("ticker"))
        if ct is None:
            raise WeekendActionTableError(f"row ticker 非规范 US ticker（拒 A 股码/坏形）: {row.get('ticker')!r}")
        if ct in seen:
            raise WeekendActionTableError(f"rows 含规范化后重复 ticker（一股一行）: {ct!r}")
        seen.add(ct)
        _validate_price_projection(row, ct)   # §6 price contract before lifting into the official §11.3 columns
        out_rows.append({**_flatten_row(row, ct), "ticker": ct})

    # cross-row §4.5 selection-rank integrity: the SELECTED rows (top15_candidate / holding_in_top15) ARE the Top15
    # admitted set, so their preserved selection_rank must be EXACTLY 1..N (unique + dense + in-range) — a duplicate
    # / gapped / out-of-range rank fails closed (Codex re-review 5: duplicate selection_rank across selected rows).
    selected_ranks = sorted(r["selection_record"]["selection_rank"]
                            for r in out_rows if r.get("row_source") in _SELECTED_ROW_SOURCES)
    if selected_ranks != list(range(1, len(selected_ranks) + 1)):
        raise WeekendActionTableError(f"selected 行 selection_rank 须恰为 1..N（唯一+连续+在界）: {selected_ranks}")

    flat_record = {**machine_record, "rows": out_rows}
    # re-assert §10-cleanliness of the projection (the renderer's validator is the single §10 gate) — a flatten
    # that ever lifted an illegal design-locked enum value must fail closed before it is treated as output.
    try:
        render_action_table(flat_record)
    except Exception as e:   # NotCleanMachineRecordError (or any validator-surfaced shape error)
        raise WeekendActionTableError(f"flattened machine record 非 §10-clean（投影破坏契约）: {e}")
    return flat_record


def build_action_table(machine_record):
    """Flatten the §10 machine record onto the §11.3 columns and render the populated action_table.

    Returns `{"columns": [...51...], "rows": [[cell, ...], ...]}` (via `render_action_table` on the flattened
    record), so the action_table.csv carries the real entry / stop / take-profit / size / order-type values
    (not the empty cells a non-flattened machine record would render). Raises WeekendActionTableError on a
    malformed / not-§10-clean record."""
    return render_action_table(flatten_machine_record(machine_record))
