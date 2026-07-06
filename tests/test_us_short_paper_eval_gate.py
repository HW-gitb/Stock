# -*- coding: utf-8 -*-
"""Tests for US-short §12.1 / §18.1 #29 corporate-action evaluability gate (engine/us_short_paper_eval_gate.py).

Covers: evaluable (paper / reporting / shadow use) ONLY when all three confirmations are literally True;
fail-closed not_evaluable on any missing / False / None / truthy-non-bool confirmation (only literal True
confirms); the unconfirmed list + the local blocks_paper_performance_due_to_corporate_action cause; the FIXED
full_size_ship_gate_allowed=False ship-gate invariant (paper is never full-size ship-gate eligible, §12 / §27);
and malformed fail-closed (non-dict, unknown confirmation key). Pure/offline; no provider/live; no A-share crossing.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_paper_eval_gate as g  # noqa: E402

ALL = {"adjustment_mode_confirmed": True, "split_dividend_handled": True, "ex_date_price_consistent": True}


def offline_evidence(**overrides):
    evidence = {
        "schema_name": "us_short_paper_eval_adjustment_evidence",
        "schema_version": "1.0.0",
        "decision_date": "20260706",
        "source_refs": [
            {
                "id": "reviewed_local_price_packet",
                "path": "state/us_short/price_adjustment_evidence_20260706.json",
                "sha256": "a" * 64,
            }
        ],
        "adjustment_mode": {
            "status": "confirmed",
            "mode": "split_dividend_adjusted",
            "source_ref_ids": ["reviewed_local_price_packet"],
        },
        "split_handling": {
            "status": "events_reconciled",
            "source_ref_ids": ["reviewed_local_price_packet"],
            "event_refs": [
                {
                    "event_id": "AAPL-split-20200831",
                    "ticker": "AAPL",
                    "ex_date": "2020-08-31",
                    "source_ref_ids": ["reviewed_local_price_packet"],
                }
            ],
        },
        "dividend_handling": {
            "status": "no_events",
            "source_ref_ids": ["reviewed_local_price_packet"],
            "event_refs": [],
        },
        "ex_date_price_consistency": {
            "status": "consistent",
            "source_ref_ids": ["reviewed_local_price_packet"],
            "checked_event_ids": ["AAPL-split-20200831"],
        },
        "scope": {
            "offline_detection_only": True,
            "provider_call_performed": False,
            "corporate_action_reconciliation_claimed": False,
            "ship_gate_or_production_authorized": False,
        },
    }
    evidence.update(overrides)
    return evidence


class Evaluable(unittest.TestCase):
    def test_all_confirmed_is_evaluable_but_not_ship_gate(self):
        r = g.paper_performance_evaluability(dict(ALL))
        self.assertEqual(r["status"], "evaluable")
        self.assertEqual(r["unconfirmed"], [])
        self.assertFalse(r["blocks_paper_performance_due_to_corporate_action"])
        # evaluable for paper / reporting / shadow use — but NEVER full-size ship-gate eligible (§12 / §27)
        self.assertFalse(r["full_size_ship_gate_allowed"])
        self.assertEqual(r["ship_gate_evidence_level"], "paper_not_live_normalized")


class FailClosed(unittest.TestCase):
    def test_any_false_blocks(self):
        for k in g._CONFIRMATIONS:
            ctx = dict(ALL); ctx[k] = False
            r = g.paper_performance_evaluability(ctx)
            self.assertEqual(r["status"], "not_evaluable", k)
            self.assertEqual(r["unconfirmed"], [k])
            self.assertTrue(r["blocks_paper_performance_due_to_corporate_action"])

    def test_missing_key_is_unconfirmed(self):
        ctx = {"adjustment_mode_confirmed": True, "split_dividend_handled": True}  # ex_date omitted
        r = g.paper_performance_evaluability(ctx)
        self.assertEqual(r["status"], "not_evaluable")
        self.assertEqual(r["unconfirmed"], ["ex_date_price_consistent"])

    def test_empty_context_all_unconfirmed(self):
        r = g.paper_performance_evaluability({})
        self.assertEqual(r["status"], "not_evaluable")
        self.assertEqual(set(r["unconfirmed"]), set(g._CONFIRMATIONS))

    def test_truthy_non_bool_does_not_confirm(self):  # only literal True confirms (no sloppy truthy unlock)
        for truthy in (1, "yes", "true", [1], 1.0):
            ctx = dict(ALL); ctx["adjustment_mode_confirmed"] = truthy
            r = g.paper_performance_evaluability(ctx)
            self.assertEqual(r["status"], "not_evaluable", repr(truthy))
            self.assertIn("adjustment_mode_confirmed", r["unconfirmed"])

    def test_none_does_not_confirm(self):
        ctx = dict(ALL); ctx["split_dividend_handled"] = None
        self.assertEqual(g.paper_performance_evaluability(ctx)["status"], "not_evaluable")


class MalformedFailsClosed(unittest.TestCase):
    def test_non_dict_refused(self):
        for bad in (None, "x", 5, []):
            with self.assertRaises(g.PaperEvalGateError, msg=repr(bad)):
                g.paper_performance_evaluability(bad)

    def test_unknown_key_refused(self):  # a typo'd confirmation key must fail closed, not be silently ignored
        ctx = dict(ALL); ctx["adjustment_mode_confiremd"] = True  # typo
        with self.assertRaises(g.PaperEvalGateError):
            g.paper_performance_evaluability(ctx)


class ShipGateNeverAllowed(unittest.TestCase):
    """R-USSHORT-BATCH3-PAPER-EVAL-GATE-SHIP-GATE-PERMISSION-GAP: corporate-action evaluability NEVER implies
    full-size ship-gate eligibility — paper is design-iteration evidence only (§12 / §27); only live_normalized
    graduates."""

    def test_ship_gate_disallowed_for_all_inputs(self):  # confirmed OR not, full-size ship-gate stays disallowed
        for ctx in (dict(ALL), {}, {"adjustment_mode_confirmed": True},
                    {"adjustment_mode_confirmed": True, "split_dividend_handled": False, "ex_date_price_consistent": True}):
            r = g.paper_performance_evaluability(ctx)
            self.assertFalse(r["full_size_ship_gate_allowed"], ctx)
            self.assertEqual(r["ship_gate_evidence_level"], "paper_not_live_normalized")

    def test_no_ship_gate_named_field_is_true_even_when_evaluable(self):  # would fail if all-confirmed exposed a ship-gate=True
        r = g.paper_performance_evaluability(dict(ALL))
        self.assertNotIn(True, [v for k, v in r.items() if "ship_gate" in k])


class OfflineEvidenceDetection(unittest.TestCase):
    def test_reviewed_offline_evidence_drives_existing_gate(self):
        r = g.paper_performance_evaluability_from_offline_evidence(offline_evidence())
        self.assertEqual(r["status"], "evaluable")
        self.assertEqual(r["unconfirmed"], [])
        self.assertEqual(r["adjustment_context"], dict(ALL))
        self.assertEqual(r["corporate_action_gate_source"], "offline_adjustment_evidence")
        self.assertFalse(r["full_size_ship_gate_allowed"])

    def test_missing_source_ref_does_not_confirm_adjustment_mode(self):
        evidence = offline_evidence(
            adjustment_mode={
                "status": "confirmed",
                "mode": "split_dividend_adjusted",
                "source_ref_ids": ["missing_source"],
            }
        )
        r = g.paper_performance_evaluability_from_offline_evidence(evidence)
        self.assertEqual(r["status"], "not_evaluable")
        self.assertIn("adjustment_mode_confirmed", r["unconfirmed"])
        self.assertFalse(r["adjustment_context"]["adjustment_mode_confirmed"])

    def test_split_event_without_ex_date_check_blocks_consistency(self):
        evidence = offline_evidence(
            ex_date_price_consistency={
                "status": "consistent",
                "source_ref_ids": ["reviewed_local_price_packet"],
                "checked_event_ids": [],
            }
        )
        r = g.paper_performance_evaluability_from_offline_evidence(evidence)
        self.assertEqual(r["status"], "not_evaluable")
        self.assertIn("ex_date_price_consistent", r["unconfirmed"])
        self.assertFalse(r["adjustment_context"]["ex_date_price_consistent"])

    def test_no_event_evidence_can_mark_ex_date_check_not_applicable(self):
        no_events = offline_evidence(
            split_handling={
                "status": "no_events",
                "source_ref_ids": ["reviewed_local_price_packet"],
                "event_refs": [],
            },
            ex_date_price_consistency={
                "status": "not_applicable_no_events",
                "source_ref_ids": ["reviewed_local_price_packet"],
                "checked_event_ids": [],
            },
        )
        r = g.paper_performance_evaluability_from_offline_evidence(no_events)
        self.assertEqual(r["status"], "evaluable")
        self.assertEqual(r["unconfirmed"], [])

    def test_unknown_offline_evidence_key_fails_closed(self):
        evidence = offline_evidence(unreviewed_live_fetch=True)
        with self.assertRaises(g.PaperEvalGateError):
            g.paper_performance_evaluability_from_offline_evidence(evidence)

    def test_source_ref_path_and_hash_are_checked_by_engine(self):
        for field, bad_value in (
            ("path", "C:/state/us_short/raw.json"),
            ("path", "../state/us_short/raw.json"),
            ("sha256", "not-a-sha"),
        ):
            evidence = offline_evidence()
            evidence["source_refs"][0][field] = bad_value
            with self.subTest(field=field, bad_value=bad_value):
                with self.assertRaises(g.PaperEvalGateError):
                    g.paper_performance_evaluability_from_offline_evidence(evidence)

    def test_schema_validation_rejects_unhashable_status_and_mode_as_typed_error(self):
        for section, field, bad_value in (
            ("adjustment_mode", "status", {"bad": "status"}),
            ("adjustment_mode", "status", ["bad_status"]),
            ("adjustment_mode", "mode", {"bad": "mode"}),
            ("adjustment_mode", "mode", ["bad_mode"]),
            ("split_handling", "status", {"bad": "status"}),
            ("split_handling", "status", ["bad_status"]),
            ("dividend_handling", "status", {"bad": "status"}),
            ("dividend_handling", "status", ["bad_status"]),
            ("ex_date_price_consistency", "status", {"bad": "status"}),
            ("ex_date_price_consistency", "status", ["bad_status"]),
        ):
            evidence = offline_evidence()
            evidence[section][field] = bad_value
            with self.subTest(section=section, field=field, bad_value=bad_value):
                with self.assertRaises(g.PaperEvalGateError):
                    g.paper_performance_evaluability_from_offline_evidence(evidence)

    def test_schema_validation_requires_scope_block(self):
        evidence = offline_evidence()
        del evidence["scope"]
        with self.assertRaises(g.PaperEvalGateError):
            g.paper_performance_evaluability_from_offline_evidence(evidence)

    def test_schema_validation_rejects_identity_and_decision_date_shape_drift(self):
        for field, bad_value in (
            ("schema_name", "other_packet"),
            ("schema_version", "2.0.0"),
            ("decision_date", "2026-07-06"),
        ):
            evidence = offline_evidence()
            evidence[field] = bad_value
            with self.subTest(field=field, bad_value=bad_value):
                with self.assertRaises(g.PaperEvalGateError):
                    g.paper_performance_evaluability_from_offline_evidence(evidence)


if __name__ == "__main__":
    unittest.main()
