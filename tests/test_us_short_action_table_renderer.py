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
from engine.us_short_private_paths import PrivatePathError  # noqa: E402

CONTRACT = json.loads((ROOT / "presets" / "us_short_action_table_contract_20260620.json").read_text(encoding="utf-8"))


def _field(**over):
    base = {
        "field_id": "tag1", "owner_module": "engine.us_short_x", "data_source": "FMP",
        "pit_basis": "prior_friday_close", "privacy_class": "public_universe",
        "current_landing_surface": "weekly_report.risk_section", "terminal_surface_target": "risk_tags",
        "operation_impact": "仅标签", "evidence_ref_kind": None, "lifecycle_item_id": 7,
        "field_class": "structured_tag", "disposition": "landed",
        "impact_target": None, "claim_type": None, "evidence_ref": None,
    }
    base.update(over)
    return base


def _clean_record():
    """A §10-clean machine record (passes validate_machine_record) carrying a few action_table columns."""
    return {
        "schema_name": "us_short_machine_record_contract", "schema_version": "1.0.0", "as_of": "20260622",
        "rows": [{
            "ticker": "AAPL", "row_source": "top15_candidate", "final_action": "建仓",
            "action_rank": 2, "decision_trace": "passed gate; pullback entry",
            "risk_tags": ["macro_cluster:ai_complex", "near_earnings"],
            "coverage_status": "full", "model_position_size_shares": 100,
            "field_records": [_field()],
        }],
    }


class ColumnContract(unittest.TestCase):
    def test_columns_are_the_frozen_contract_set_and_order(self):
        self.assertEqual(rndr.action_table_columns(), CONTRACT["core_columns"])
        self.assertEqual(len(rndr.action_table_columns()), 51)

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


if __name__ == "__main__":
    unittest.main()
