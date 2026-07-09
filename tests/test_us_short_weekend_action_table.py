# -*- coding: utf-8 -*-
"""Tests for US-short weekend §11.3 action_table projection (batch4 slice 4d-ii-m1).

Covers: the rich machine layer (price.action_fields / sizing) is projected onto the flat §11.3 columns so the
action_table.csv renders POPULATED (the columns that a non-flattened machine record left empty); columns with
no v1 source stay empty (honest, not fabricated); the rich layer + field_records are preserved and the
projection stays §10-clean; and fail-closed on a malformed record, a bad §9 pair, a non-canonical / duplicate
ticker, and a projection that would lift an illegal design-locked enum. Pure/offline; no provider/live; no
A-share crossing.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_weekend_action_table as at  # noqa: E402
import engine.us_short_weekend_machine_record as mr  # noqa: E402
from engine.us_short_action_rank import action_group as _ag  # noqa: E402
from engine.us_short_no_dangling_validator import validate_machine_record  # noqa: E402
from engine.us_short_price_engine import HOLDING_COLUMNS, NEW_ENTRY_COLUMNS  # noqa: E402

_AS_OF = "20260112"
_CANDIDATE_AF = {
    "order_type": "pullback_limit", "entry_plan": "pullback", "pullback_entry_price": 99.0,
    "breakout_entry_price": None, "limit_order_price": 101.0, "valid_entry_low": 99.0, "valid_entry_high": 101.0,
    "order_expiry": "first_regular_session_only", "gap_policy": "limit_band_first_session_no_chase",
    "effective_support": 98.0, "effective_resistance": 110.0, "structure_quality": "strong",
    "stop_clear_price": 98.0, "take_profit_reduce_price": 105.0, "take_profit_exit_price": 110.0,
    "risk_reward_ratio": 2.0, "min_rr_gate_status": "pass", "post_round_rr_status": "ok",
    "price_engine_used": "support_atr_engine", "price_sub_mode": "pullback",
}
_HOLDING_AF = {
    "stop_clear_price": 95.0, "take_profit_reduce_price": 108.0, "take_profit_exit_price": 115.0,
    "risk_reward_ratio": 1.8, "post_round_rr_status": "ok",
    "price_engine_used": "holding_exit_engine", "price_sub_mode": None,
}


def _machine_record(rows):
    return mr.assemble_machine_record({"regime": {"market_risk_regime": "进攻"}, "rows": rows}, as_of=_AS_OF)


def _candidate(ticker="AAA", action_fields=None, executable=True, final_action="建仓",
               observe_reason_type=None, sized=True):
    row = {"ticker": ticker, "row_source": "top15_candidate", "final_action": final_action,
           "observe_reason_type": observe_reason_type, "row_context": "candidate", "selection_rank": 1,
           "action_rank": 1, "action_group": _ag(final_action),
           "veto": {"veto_tier": "none", "row_context": "candidate"},
           "price": {"executable": executable, "trace": {},
                     "action_fields": _CANDIDATE_AF if action_fields is None else action_fields},
           "score": {"core_score": 50.0},
           "risk_downgrade": {"points": 0.0, "hard_veto": False, "components": {"history": 0.0, "current_event": 0.0, "analyst": 0.0}},
           "selection_record": {"selection_rank": 1, "selection_bucket": "core_top",   # top15_candidate = selected
                                "core_score": 50.0, "theme_momentum_score": 0.0}}
    if sized:
        row["sizing"] = {"status": "sized", "desired_model_shares": 10}
    return row


def _holding(ticker="HLD"):
    return {"ticker": ticker, "row_source": "holding_pass2_only", "final_action": "持有",
            "observe_reason_type": None, "row_context": "holding", "selection_rank": None,
            "action_rank": 1, "action_group": 4, "veto": {"veto_tier": "none", "row_context": "holding"},
            "price": {"executable": True, "trace": {"breached": False}, "action_fields": _HOLDING_AF}}


def _cells(table, ticker="AAA"):
    cols = table["columns"]
    tix = cols.index("ticker")
    row = next(r for r in table["rows"] if r[tix] == ticker)
    return {c: row[i] for i, c in enumerate(cols)}


class Projection(unittest.TestCase):
    def test_price_columns_lifted(self):
        flat = at.flatten_machine_record(_machine_record([_candidate()]))
        r0 = flat["rows"][0]
        for col in ("order_type", "entry_plan", "valid_entry_high", "stop_clear_price",
                    "take_profit_reduce_price", "risk_reward_ratio", "order_expiry", "gap_policy",
                    "min_rr_gate_status", "post_round_rr_status", "price_engine_used", "price_sub_mode"):
            self.assertEqual(r0[col], _CANDIDATE_AF[col])

    def test_sizing_shares_lifted(self):
        flat = at.flatten_machine_record(_machine_record([_candidate()]))
        self.assertEqual(flat["rows"][0]["model_position_size_shares"], 10)

    def test_selection_bucket_projected(self):
        # the preserved Top15 selection_bucket lands on its frozen §11.3 column via the threaded selection_record
        # (not blank) — R-USSHORT-BATCH4-SELECTION-TRACE-AND-RECALL-CLOSURE-GAP
        row = _candidate()
        row["selection_record"] = {"selection_rank": 1, "selection_bucket": "core_top",
                                   "core_score": 50.0, "theme_momentum_score": 0.0}
        flat = at.flatten_machine_record(_machine_record([row]))
        self.assertEqual(flat["rows"][0]["selection_bucket"], "core_top")

    def test_no_selection_record_leaves_bucket_unset(self):
        # a non-selected holding row (no selection_record) leaves the bucket cell honestly unset
        flat = at.flatten_machine_record(_machine_record([_holding()]))
        self.assertIsNone(flat["rows"][0].get("selection_bucket"))

    def test_forged_flat_bucket_cleared(self):
        # a FORGED flat selection_bucket on a non-selected holding row (no record) is cleared — only a record sets it
        row = _holding()
        row["selection_bucket"] = "core_top"   # forged flat value, holding row carries no record
        flat = at.flatten_machine_record(_machine_record([row]))
        self.assertIsNone(flat["rows"][0].get("selection_bucket"))

    def test_selected_row_missing_record_rejected(self):
        # a top15_candidate (selected) with NO selection_record fails closed — the canonical source is required
        row = _candidate(); del row["selection_record"]
        with self.assertRaises(at.WeekendActionTableError):
            at.flatten_machine_record(_machine_record([row]))

    def test_malformed_selection_record_rejected(self):
        for bad in ({"selection_rank": 1, "selection_bucket": "garbage", "core_score": 50.0, "theme_momentum_score": 0.0},
                    {"selection_rank": 0, "selection_bucket": "core_top", "core_score": 50.0, "theme_momentum_score": 0.0},
                    {"selection_rank": 1, "selection_bucket": "core_top", "core_score": 150.0, "theme_momentum_score": 0.0},
                    {"selection_rank": 1, "selection_bucket": "core_top"}):   # bad bucket / rank / score-range / partial
            row = _candidate(); row["selection_record"] = bad
            with self.assertRaises(at.WeekendActionTableError):
                at.flatten_machine_record(_machine_record([row]))

    def test_holding_only_row_with_record_rejected(self):
        # a non-selected holding row carrying a (forged) selection_record fails closed
        row = _holding()
        row["selection_record"] = {"selection_rank": 1, "selection_bucket": "core_top",
                                   "core_score": 50.0, "theme_momentum_score": 0.0}
        with self.assertRaises(at.WeekendActionTableError):
            at.flatten_machine_record(_machine_record([row]))

    def test_duplicate_selection_rank_across_selected_rows_rejected(self):
        # two selected rows both record-rank 1 → fail closed (selected rows must be unique 1..N)
        with self.assertRaises(at.WeekendActionTableError):
            at.flatten_machine_record(_machine_record([_candidate("AAA"), _candidate("BBB")]))

    def test_record_rank_vs_landed_conflict_rejected(self):
        row = _candidate(); row["selection_rank"] = 2   # landed top-level ≠ record rank 1
        with self.assertRaises(at.WeekendActionTableError):
            at.flatten_machine_record(_machine_record([row]))

    def test_record_core_vs_machine_score_conflict_rejected(self):
        row = _candidate(); row["selection_record"]["core_score"] = 99.0   # ≠ machine score.core_score 50
        with self.assertRaises(at.WeekendActionTableError):
            at.flatten_machine_record(_machine_record([row]))

    def test_two_selected_rows_unique_ranks_pass(self):   # multi-row positive control
        a, b = _candidate("AAA"), _candidate("BBB")
        b["selection_rank"] = 2
        b["selection_record"]["selection_rank"] = 2
        flat = at.flatten_machine_record(_machine_record([a, b]))
        self.assertEqual(len(flat["rows"]), 2)

    def test_flat_bucket_conflicting_with_record_uses_record(self):
        # a pre-existing flat value is IGNORED — the selection_record is the sole source (record wins).
        row = _candidate()
        row["selection_bucket"] = "core_backfill"   # conflicting forged flat
        row["selection_record"] = {"selection_rank": 1, "selection_bucket": "core_top",
                                   "core_score": 50.0, "theme_momentum_score": 0.0}
        flat = at.flatten_machine_record(_machine_record([row]))
        self.assertEqual(flat["rows"][0]["selection_bucket"], "core_top")

    def test_rich_layer_and_field_records_preserved(self):
        flat = at.flatten_machine_record(_machine_record([_candidate()]))
        r0 = flat["rows"][0]
        self.assertIsInstance(r0["price"], dict)          # rich layer kept
        self.assertIn("field_records", r0)                # §10 registry kept
        self.assertTrue(validate_machine_record(flat)["clean"])

    def test_holding_flattens(self):
        flat = at.flatten_machine_record(_machine_record([_holding()]))
        r0 = flat["rows"][0]
        self.assertEqual(r0["price_engine_used"], "holding_exit_engine")
        self.assertIsNone(r0["price_sub_mode"])           # holding is not pullback/breakout
        self.assertEqual(r0["stop_clear_price"], 95.0)
        self.assertEqual(r0["post_round_rr_status"], "ok")


class CsvPopulated(unittest.TestCase):
    def test_action_table_cells_populated(self):
        table = at.build_action_table(_machine_record([_candidate()]))
        cells = _cells(table)
        for col in ("entry_plan", "valid_entry_high", "order_type", "model_position_size_shares",
                    "take_profit_reduce_price", "stop_clear_price", "risk_reward_ratio", "order_expiry",
                    "gap_policy", "min_rr_gate_status", "post_round_rr_status"):
            self.assertTrue(cells[col], f"{col} should be populated, got empty")
        self.assertEqual(cells["valid_entry_high"], "101.0")
        self.assertEqual(cells["model_position_size_shares"], "10")
        self.assertEqual(cells["order_expiry"], "first_regular_session_only")
        self.assertEqual(cells["gap_policy"], "limit_band_first_session_no_chase")
        self.assertEqual(cells["min_rr_gate_status"], "pass")
        self.assertEqual(cells["post_round_rr_status"], "ok")

    def test_unsourced_columns_stay_empty(self):
        # columns with no v1 pipeline source must stay EMPTY (honest, not fabricated)
        cells = _cells(at.build_action_table(_machine_record([_candidate()])))
        for col in ("macro_cluster", "overextension_state", "coverage_status"):
            self.assertEqual(cells[col], "")

    def test_batch4_ship_gate_fields_are_engine_derived(self):
        cells = _cells(at.build_action_table(_machine_record([_candidate()])))
        self.assertEqual(cells["live_permission_status"], "paper_or_minimal_only")
        self.assertEqual(cells["live_size_warning"], "paper_or_minimal_only_not_full_size_license")
        self.assertEqual(cells["model_position_size_amount"], "1010.0")

    def test_forged_full_size_cells_cannot_reach_action_table(self):
        row = _candidate()
        row["live_permission_status"] = "full_size_eligible"
        row["live_size_warning"] = None
        row["model_position_size_amount"] = 999999.0
        cells = _cells(at.build_action_table(_machine_record([row])))
        self.assertEqual(cells["live_permission_status"], "paper_or_minimal_only")
        self.assertEqual(cells["live_size_warning"], "paper_or_minimal_only_not_full_size_license")
        self.assertEqual(cells["model_position_size_amount"], "1010.0")

    def test_multiple_rows(self):
        table = at.build_action_table(_machine_record([_candidate("AAA"), _holding("HLD")]))
        self.assertEqual(len(table["rows"]), 2)
        self.assertTrue(_cells(table, "AAA")["entry_plan"])
        self.assertTrue(_cells(table, "HLD")["stop_clear_price"])


class FailClosed(unittest.TestCase):
    def test_malformed_record_rejected(self):
        for bad in (None, {}, {"rows": "x"}, {"rows": [None]}):
            with self.assertRaises(at.WeekendActionTableError):
                at.flatten_machine_record(bad)

    def test_bad_action_reason_pair_rejected(self):
        bad = {"schema_name": "us_short_machine_record_contract", "schema_version": "1.0.0", "as_of": _AS_OF,
               "rows": [{"ticker": "AAA", "row_source": "top15_candidate", "final_action": "观察",
                         "observe_reason_type": "BANANA"}]}
        with self.assertRaises(at.WeekendActionTableError):
            at.flatten_machine_record(bad)

    def test_noncanonical_and_duplicate_ticker_rejected(self):
        base = {"final_action": "持有", "observe_reason_type": None, "row_source": "holding_account_only"}
        with self.assertRaises(at.WeekendActionTableError):   # A-share code
            at.flatten_machine_record({"rows": [{**base, "ticker": "600519"}]})
        with self.assertRaises(at.WeekendActionTableError):   # duplicate canonical identity
            at.flatten_machine_record({"rows": [{**base, "ticker": "AAA"}, {**base, "ticker": "aaa"}]})

    def test_illegal_lifted_enum_fails_closed(self):
        # an action_fields with an ILLEGAL order_type rides nested through K (which does not check action_fields
        # internals), but flattening lifts it to the order_type COLUMN where the §10 validator rejects it.
        bad_af = {**_CANDIDATE_AF, "order_type": "ILLEGAL_TYPE"}
        rec = _machine_record([_candidate(action_fields=bad_af)])
        with self.assertRaises(at.WeekendActionTableError):
            at.flatten_machine_record(rec)


class PriceContractFailClosed(unittest.TestCase):
    """R-USSHORT-BATCH4-ACTION-TABLE-PROJECTION-PRICE-CONTRACT-GAP: an executable row whose price is lifted into
    the official §11.3 CSV must carry the §6 price-engine contract — empty / partial / nonnumeric action_fields
    can never render a blank or garbage entry/stop/RR while still showing an action + size."""

    def _reject(self, rows):
        # a broken price/projection is fail-closed at EITHER official boundary: machine-record assembly
        # (§9 action↔price / §10) or the §11.3 action_table flatten — both prevent a clean official row.
        with self.assertRaises((mr.WeekendMachineRecordError, at.WeekendActionTableError)):
            at.flatten_machine_record(_machine_record(rows))

    def test_executable_build_empty_action_fields_rejected(self):
        self._reject([_candidate(action_fields={})])

    def test_build_missing_critical_field_rejected(self):
        for drop in ("stop_clear_price", "valid_entry_high", "limit_order_price", "take_profit_reduce_price",
                     "risk_reward_ratio", "entry_plan", "order_expiry", "gap_policy", "min_rr_gate_status",
                     "post_round_rr_status"):
            af = {k: v for k, v in _CANDIDATE_AF.items() if k != drop}
            self._reject([_candidate(action_fields=af)])

    def test_nonnumeric_price_or_rr_rejected(self):
        for col, bad in (("valid_entry_high", "BAD_PRICE"), ("stop_clear_price", "X"),
                         ("risk_reward_ratio", "NOT_NUMERIC"), ("limit_order_price", float("nan"))):
            self._reject([_candidate(action_fields={**_CANDIDATE_AF, col: bad})])

    def test_bad_price_engine_or_sub_mode_rejected(self):
        self._reject([_candidate(action_fields={**_CANDIDATE_AF, "price_engine_used": "holding_exit_engine"})])
        self._reject([_candidate(action_fields={**_CANDIDATE_AF, "price_sub_mode": "BANANA"})])

    def test_build_bad_fixed_execution_status_fields_rejected(self):
        for col, bad in (("order_expiry", "multi_day_gtc"), ("gap_policy", "chase_gap_open"),
                         ("min_rr_gate_status", "fail_below_floor"),
                         ("post_round_rr_status", "broke_after_round")):
            self._reject([_candidate(action_fields={**_CANDIDATE_AF, col: bad})])

    def test_executable_holding_empty_action_fields_rejected(self):
        h = _holding()
        h["price"]["action_fields"] = {}
        self._reject([h])

    def test_holding_with_sub_mode_rejected(self):
        h = _holding()
        h["price"]["action_fields"] = {**_HOLDING_AF, "price_sub_mode": "pullback"}   # holding is not pullback/breakout
        self._reject([h])

    def test_holding_missing_or_bad_post_round_status_rejected(self):
        h = _holding()
        h["price"]["action_fields"] = {k: v for k, v in _HOLDING_AF.items() if k != "post_round_rr_status"}
        self._reject([h])
        h = _holding()
        h["price"]["action_fields"] = {**_HOLDING_AF, "post_round_rr_status": "BANANA"}
        self._reject([h])

    def test_non_breached_holding_ok_status_requires_target_and_rr(self):
        af = {**_HOLDING_AF, "take_profit_reduce_price": None, "take_profit_exit_price": None,
              "risk_reward_ratio": None, "post_round_rr_status": "ok"}
        h = _holding()
        h["price"]["action_fields"] = af
        self._reject([h])

    def test_event_clear_null_event_price_rejected_at_flatten(self):
        # R-USSHORT-BATCH4-ACTION-PRICE-MAPPING-GAP: the §11.3 projection boundary independently fails closed on
        # a 清仓-事件 whose event reference price is null (defense in depth) — assemble a valid event-clear record,
        # then null the event price and flatten directly: action_price_error rejects it at the action_table layer.
        h = _holding()
        h["final_action"], h["action_group"] = "清仓-事件", _ag("清仓-事件")
        h["veto"] = {"veto_tier": "position_hard_veto", "row_context": "holding"}
        h["price"]["action_fields"] = {**_HOLDING_AF, "event_clear_reference_price": 8.0}
        rec = _machine_record([h])   # passes assembly (event price present)
        self.assertEqual(at.flatten_machine_record(rec)["rows"][0]["event_clear_reference_price"], 8.0)
        rec["rows"][0]["price"]["action_fields"]["event_clear_reference_price"] = None
        with self.assertRaises(at.WeekendActionTableError):
            at.flatten_machine_record(rec)

    # --- positive controls: valid payloads + legitimate optional/None columns pass ---
    def test_valid_breakout_build_passes(self):
        af = {**_CANDIDATE_AF, "order_type": "breakout_stop_limit", "entry_plan": "breakout",
              "price_sub_mode": "breakout", "pullback_entry_price": None, "breakout_entry_price": 99.0}
        rec = _machine_record([_candidate(action_fields=af)])
        self.assertTrue(validate_machine_record(at.flatten_machine_record(rec))["clean"])

    def test_valid_holding_no_target_passes(self):
        # a holding with a valid stop but no take-profit / RR (no-target case) is legitimate
        af = {"stop_clear_price": 95.0, "take_profit_reduce_price": None, "take_profit_exit_price": None,
              "risk_reward_ratio": None, "post_round_rr_status": "tp_not_computable",
              "price_engine_used": "holding_exit_engine", "price_sub_mode": None}
        h = _holding()
        h["price"]["action_fields"] = af
        self.assertTrue(validate_machine_record(at.flatten_machine_record(_machine_record([h])))["clean"])

    def test_valid_breached_holding_no_target_passes(self):
        af = {"stop_clear_price": 95.0, "take_profit_reduce_price": None, "take_profit_exit_price": None,
              "risk_reward_ratio": None, "post_round_rr_status": "ok",
              "price_engine_used": "holding_exit_engine", "price_sub_mode": None}
        h = _holding()
        h["price"]["trace"] = {"breached": True}
        h["price"]["action_fields"] = af
        self.assertTrue(validate_machine_record(at.flatten_machine_record(_machine_record([h])))["clean"])

    def test_nonexecutable_partial_action_fields_ok(self):
        # an observe(price_not_executable) row keeps honest partial output (§6) — no required-field gate
        row = _candidate(final_action="观察", observe_reason_type="price_not_executable", executable=False,
                         sized=False, action_fields={"price_engine_used": "support_atr_engine",
                                                     "price_sub_mode": "pullback", "min_rr_gate_status": "fail_below_floor"})
        self.assertTrue(validate_machine_record(at.flatten_machine_record(_machine_record([row])))["clean"])

    def test_optional_none_columns_stay_empty(self):
        cells = _cells(at.build_action_table(_machine_record([_candidate()])))   # pullback build
        self.assertEqual(cells["breakout_entry_price"], "")        # inactive side
        self.assertEqual(cells["event_clear_reference_price"], "")  # no event for a candidate


class Triangulation(unittest.TestCase):
    def test_required_subsets_of_engine_columns(self):
        self.assertTrue({"order_expiry", "gap_policy", "min_rr_gate_status", "post_round_rr_status"}
                        <= set(at._BUILD_REQUIRED))
        self.assertIn("post_round_rr_status", at._HOLDING_REQUIRED)
        self.assertTrue(set(at._BUILD_REQUIRED) <= set(NEW_ENTRY_COLUMNS))
        self.assertTrue(set(at._HOLDING_REQUIRED) <= set(HOLDING_COLUMNS))
        self.assertTrue(at._NUMERIC_PRICE_COLUMNS <= set(NEW_ENTRY_COLUMNS) | set(HOLDING_COLUMNS))


_OX_WARNING = {"overextension_state": "warning", "strips_theme_score": False,
               "execution_flags": {"force_pullback": True, "reduce_size": True, "raise_rr_gate": True},
               "conditions_met": 0, "condition_names": []}


class OverextensionColumn(unittest.TestCase):
    """cut 2d: the §4.3 overextension_state §11.3 column is lifted from the row's tier result (previously a
    deliberately-empty column); absent → empty; a malformed tier fails closed at the machine-record boundary."""

    def _flat_row(self, overextension=None):
        row = _candidate()
        if overextension is not None:
            row["overextension"] = overextension
        return at.flatten_machine_record(_machine_record([row]))["rows"][0]

    def test_column_populated_from_tier(self):
        self.assertEqual(self._flat_row(_OX_WARNING)["overextension_state"], "warning")

    def test_all_three_states_lift(self):
        for st in ("none", "warning", "chasing_extreme"):
            self.assertEqual(self._flat_row({**_OX_WARNING, "overextension_state": st})["overextension_state"], st)

    def test_column_empty_when_absent(self):
        self.assertIsNone(self._flat_row().get("overextension_state"))

    def test_rendered_table_carries_the_column_value(self):
        row = _candidate()
        row["overextension"] = _OX_WARNING
        table = at.build_action_table(_machine_record([row]))   # renders end-to-end (must not raise)
        col_idx = table["columns"].index("overextension_state")
        self.assertEqual(table["rows"][0][col_idx], "warning")

    def test_malformed_tier_fails_closed_at_machine_boundary(self):
        row = _candidate()
        row["overextension"] = {"overextension_state": "bogus", "execution_flags": {}}
        with self.assertRaises(mr.WeekendMachineRecordError):
            _machine_record([row])   # rejected at assembly, before the flatten ever runs


if __name__ == "__main__":
    unittest.main()
