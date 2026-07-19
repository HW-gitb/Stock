# -*- coding: utf-8 -*-
"""Tests for the US-short action_table.csv renderer (engine/us_short_action_table_renderer.py, batch-3 R2a).

Covers: the rendered column set/order is byte-faithful to the FROZEN us_short_action_table_contract (single
source); the renderer refuses a machine record the §10 validator rejects (consumes only a validated machine
layer); cell formatting (None/list/bool); and the FIRST-persister §18.0 P0 private-path guard wiring
(relative + non-gitignored in-repo paths fail closed; an outside-repo path writes).
"""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_action_table_renderer as rndr  # noqa: E402
from engine.us_short_action_rank import action_group  # noqa: E402
from engine.us_short_private_paths import PrivatePathError  # noqa: E402
from engine.us_short_run_origin import RunOriginError  # noqa: E402
from engine.us_short_weekend_machine_record import assemble_machine_record  # noqa: E402

CONTRACT = json.loads((ROOT / "presets" / "us_short_action_table_contract_20260620.json").read_text(encoding="utf-8"))


def _clean_record():
    """A real official §10 machine record carrying a few already-projected action-table cells."""
    row = {
        "ticker": "AAPL", "row_source": "top15_candidate", "row_context": "candidate",
        "final_action": "建仓", "observe_reason_type": None, "selection_rank": 1,
        "action_rank": 2, "action_group": action_group("建仓"),
        "veto": {"veto_tier": "none", "row_context": "candidate"},
        "price": {"executable": True, "trace": {}, "action_fields": {"limit_order_price": 10.0}},
        "score": {"core_score": 50.0},
        "risk_downgrade": {"points": 0.0, "hard_veto": False, "components": {"history": 0.0, "current_event": 0.0, "analyst": 0.0}},
        "sizing": {"status": "sized", "desired_model_shares": 100},
        "risk_tags": ["macro_cluster:ai_complex", "near_earnings"],
        "coverage_status": "full", "model_position_size_shares": 100,
    }
    return assemble_machine_record(
        {"regime": {"market_risk_regime": "进攻"}, "rows": [row],
         "weekly_build_limit": 3, "build_count": 1},
        as_of="20260622",
    )


def _stripped_official_record():
    record = _clean_record()
    record["rows"][0].pop("veto")
    record["rows"][0]["field_records"] = []
    return record


class ColumnContract(unittest.TestCase):
    def test_columns_are_the_frozen_contract_set_and_order(self):
        self.assertEqual(rndr.action_table_columns(), CONTRACT["core_columns"])
        self.assertEqual(len(rndr.action_table_columns()), 54)

    def test_returns_a_copy_not_the_cache(self):
        cols = rndr.action_table_columns()
        cols.append("MUTANT")
        self.assertNotIn("MUTANT", rndr.action_table_columns())


class Render(unittest.TestCase):
    def test_clean_record_renders_columns_and_values(self):
        out = rndr.render_action_table(_clean_record())
        self.assertEqual(out["columns"], CONTRACT["core_columns"])
        self.assertEqual(len(out["rows"]), 1)
        row = dict(zip(out["columns"], out["rows"][0]))
        self.assertEqual(row["ticker"], "AAPL")
        self.assertEqual(row["final_action"], "建仓")
        self.assertEqual(row["action_rank"], "2")
        self.assertEqual(row["risk_tags"], "macro_cluster:ai_complex;near_earnings")  # list -> ';'-joined
        self.assertEqual(row["coverage_status"], "full")
        self.assertEqual(row["model_position_size_shares"], "100")
        self.assertEqual(row["order_type"], "")  # a column the machine row omits -> empty cell

    def test_row_cell_count_matches_column_count(self):
        out = rndr.render_action_table(_clean_record())
        self.assertEqual(len(out["rows"][0]), len(out["columns"]))

    def test_refuses_not_clean_record(self):
        bad = _clean_record()
        bad["rows"][0]["final_action"] = "invalid_action"  # §10 vocab violation -> not clean
        with self.assertRaises(rndr.NotCleanMachineRecordError):
            rndr.render_action_table(bad)

    def test_no_clean_gate_bypass(self):
        # the validate=False opt-out was REMOVED (R-USSHORT-BATCH3-R2A-RENDER-VALIDATE-FALSE-BYPASS):
        # the §10 gate is welded — a not-clean record always raises, and there is no parameter to skip it.
        bad = _clean_record()
        bad["rows"][0]["final_action"] = "invalid_action"
        with self.assertRaises(rndr.NotCleanMachineRecordError):
            rndr.render_action_table(bad)                       # always validates
        with self.assertRaises(TypeError):
            rndr.render_action_table(bad, validate=False)       # no such parameter — the bypass is gone

    def test_refuses_official_record_with_stripped_registry(self):
        with self.assertRaises(rndr.NotCleanMachineRecordError):
            rndr.render_action_table(_stripped_official_record())


class CellFormatting(unittest.TestCase):
    def test_none_is_empty(self):
        self.assertEqual(rndr._cell(None), "")

    def test_bool(self):
        self.assertEqual(rndr._cell(True), "true")
        self.assertEqual(rndr._cell(False), "false")

    def test_list_joined(self):
        self.assertEqual(rndr._cell(["a", "b", "c"]), "a;b;c")

    def test_number(self):
        self.assertEqual(rndr._cell(3), "3")


class PrivatePathGuardWiring(unittest.TestCase):
    """FIRST batch-3 persister: write_action_table must fail closed on a non-private path (§18.0 P0)."""

    def test_relative_path_refused(self):
        with self.assertRaises(PrivatePathError):
            rndr.write_action_table(_clean_record(), "action_table.csv")

    def test_in_repo_non_gitignored_path_refused(self):
        with self.assertRaises(PrivatePathError):
            rndr.write_action_table(_clean_record(), ROOT / "us_short_action_table_TMP.csv")

    def test_outside_repo_path_writes(self):  # outside the repo = user's own private location -> allowed
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "action_table.csv"
            rndr.write_action_table(_clean_record(), out)
            self.assertTrue(out.exists())
            with open(out, encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0], CONTRACT["core_columns"])  # header = frozen columns
            self.assertEqual(len(rows), 2)                        # header + 1 data row
            self.assertEqual(rows[1][rows[0].index("ticker")], "AAPL")

    def test_guard_runs_before_render_even_for_not_clean_record(self):
        # a relative path is refused by the guard regardless of record cleanliness (guard is the first gate)
        bad = _clean_record()
        bad["rows"][0]["final_action"] = "invalid_action"
        with self.assertRaises(PrivatePathError):
            rndr.write_action_table(bad, "rel.csv")

    def test_writes_creating_a_missing_parent_dir(self):  # the <决策日> private dir may not exist yet
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "20260622" / "action_table.csv"
            self.assertFalse(out.parent.exists())
            rndr.write_action_table(_clean_record(), out)
            self.assertTrue(out.exists())

    def test_not_clean_record_not_written_on_a_valid_path(self):
        bad = _clean_record()
        bad["rows"][0]["final_action"] = "invalid_action"
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "action_table.csv"
            with self.assertRaises(rndr.NotCleanMachineRecordError):
                rndr.write_action_table(bad, out)
            self.assertFalse(out.exists())  # render refused -> no file

    def test_stripped_official_registry_not_written_on_valid_path(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "action_table.csv"
            with self.assertRaises(rndr.NotCleanMachineRecordError):
                rndr.write_action_table(_stripped_official_record(), out)
            self.assertFalse(out.exists())


class OfficialProvenanceGate(unittest.TestCase):
    """R-USSHORT-BATCH4-OFFLINE-ARTIFACT-MODE-PROVENANCE-GAP: the OFFICIAL persister requires the exact immutable
    run_origin on the record, so a provenance-stripped record can never be persisted as an actionable CSV that is
    indistinguishable from operational data. A missing / swapped origin fails BEFORE any file is created."""

    def test_clean_record_carries_run_origin(self):
        self.assertEqual(_clean_record().get("run_origin"),
                         {"run_mode": "offline_test", "data_origin": "caller_supplied_fixture",
                          "operational_use": "not_authorized"})

    def test_missing_run_origin_refused_before_file_creation(self):
        rec = _clean_record()
        rec.pop("run_origin", None)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "action_table.csv"
            with self.assertRaises(RunOriginError):
                rndr.write_action_table(rec, out)
            self.assertFalse(out.exists())   # provenance-stripped record never persisted

    def test_swapped_run_origin_refused_before_file_creation(self):
        rec = _clean_record()
        rec["run_origin"] = {"run_mode": "live", "data_origin": "real_provider", "operational_use": "authorized"}
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "action_table.csv"
            with self.assertRaises(RunOriginError):
                rndr.write_action_table(rec, out)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
