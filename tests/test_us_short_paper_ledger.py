# -*- coding: utf-8 -*-
"""Tests for US-short §12.1 paper_performance private persister (engine/us_short_paper_ledger.py).

Covers: the §18.0 P0 private-path guard on write AND the symmetric guard on load; validate-before-write (no file
on refusal); load fail-closed (missing / corrupt-JSON / not-valid-record); the full record + per-entry shape with
the EXACT paper_net_result contract — closed-world 6-key entries + per-outcome invariants (cash_unfilled all 0 /
open_unrealized all None / closed finite gross·net, non-negative cost, net == gross - cost, outcome⇔gross SIGN
[a stop loses, a tp gains]); the canonical
`paper_performance.json` filename; roundtrip + a tampered-row load refusal; and an integration drift-guard feeding
REAL paper_net_result outputs. Pure structure-over-IO; no provider/live; no A-share.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import engine.us_short_paper_ledger as pl  # noqa: E402
from engine.us_short_private_paths import PrivatePathError  # noqa: E402


def _entry(outcome="filled_tp_exit", **over):
    if outcome == "open_unrealized":
        d = {"outcome": outcome, "realized": False, "net_return": None, "gross_return": None,
             "cost_fraction": None, "unfilled_cash": False}
    else:
        # sign-consistent: a stop is a LOSS (gross < 0), a take-profit is a GAIN (gross > 0), cash is 0
        net = 0.0 if outcome == "cash_unfilled" else (-0.05 if outcome == "filled_stopped" else 0.05)
        d = {"outcome": outcome, "realized": True, "net_return": net, "gross_return": net,
             "cost_fraction": 0.0, "unfilled_cash": outcome == "cash_unfilled"}
    d.update(over)
    return d


def _record(entries=None, as_of="20260619"):
    return {"as_of": as_of, "entries": entries if entries is not None else [_entry()]}


class ValidateRecord(unittest.TestCase):
    def test_valid_all_outcomes_pass(self):
        pl._validate_record(_record([_entry(o) for o in pl._OUTCOMES]))

    def test_non_dict_or_bad_as_of_refused(self):
        for bad in (None, "x", {"as_of": "20260231", "entries": []}, {"as_of": "2026-06-19", "entries": []}, {"entries": []}):
            with self.assertRaises(pl.PaperLedgerError, msg=repr(bad)):
                pl._validate_record(bad)

    def test_bad_entries_container_refused(self):
        with self.assertRaises(pl.PaperLedgerError):
            pl._validate_record({"as_of": "20260619", "entries": "nope"})
        with self.assertRaises(pl.PaperLedgerError):
            pl._validate_record(_record(["notadict"]))

    def test_bad_outcome_or_bool_refused(self):
        with self.assertRaises(pl.PaperLedgerError):
            pl._validate_record(_record([_entry(outcome="made_up")]))
        with self.assertRaises(pl.PaperLedgerError):
            pl._validate_record(_record([_entry(realized="yes")]))
        with self.assertRaises(pl.PaperLedgerError):
            pl._validate_record(_record([_entry(unfilled_cash=1)]))

    def test_net_result_consistency_enforced(self):
        # open_unrealized must be realized=False / net_return=None
        for bad in (_entry("open_unrealized", realized=True), _entry("open_unrealized", net_return=0.05)):
            with self.assertRaises(pl.PaperLedgerError, msg=repr(bad)):
                pl._validate_record(_record([bad]))
        # a realized outcome must be realized=True / a finite net_return
        for bad in (_entry("filled_tp_exit", realized=False), _entry("filled_stopped", net_return=None),
                    _entry("filled_tp_exit", net_return=float("inf")), _entry("cash_unfilled", net_return="0")):
            with self.assertRaises(pl.PaperLedgerError, msg=repr(bad)):
                pl._validate_record(_record([bad]))

    def test_full_per_outcome_invariants(self):  # the exact paper_net_result per-outcome contract
        for bad in (_entry("cash_unfilled", net_return=0.05),       # cash_unfilled must be net 0
                    _entry("cash_unfilled", gross_return=0.05),     # cash_unfilled must be gross 0
                    _entry("cash_unfilled", unfilled_cash=False),   # cash_unfilled must be unfilled_cash True
                    _entry("open_unrealized", unfilled_cash=True),  # open must be unfilled_cash False
                    _entry("filled_tp_exit", net_return=0.99),      # net != gross - cost
                    _entry("filled_stopped", cost_fraction=-0.1)):  # cost must be non-negative
            with self.assertRaises(pl.PaperLedgerError, msg=repr(bad)):
                pl._validate_record(_record([bad]))

    def test_wrong_entry_key_set_refused(self):
        miss = _entry(); del miss["cost_fraction"]   # missing a contract key
        with self.assertRaises(pl.PaperLedgerError):
            pl._validate_record(_record([miss]))
        extra = _entry(); extra["extra"] = 1          # extra key (closed-world)
        with self.assertRaises(pl.PaperLedgerError):
            pl._validate_record(_record([extra]))

    def test_outcome_sign_enforced(self):  # R-USSHORT-BATCH3-NET-RESULT-OUTCOME-SIGN-GAP
        # a stop booked as a GAIN (gross >= 0) or a take-profit booked as a LOSS (gross <= 0) is impossible for a
        # v1 long — the producer enforces it via fill geometry; the persister re-checks (the outcome label is
        # persisted, so a corrupted paper_performance.json with a stop-as-gain must not load as valid)
        for bad in (_entry("filled_stopped", net_return=0.05, gross_return=0.05),    # stop with a positive gross
                    _entry("filled_stopped", net_return=0.0, gross_return=0.0),      # stop with zero gross
                    _entry("filled_tp_exit", net_return=-0.05, gross_return=-0.05),  # tp with a negative gross
                    _entry("filled_tp_exit", net_return=0.0, gross_return=0.0)):     # tp with zero gross
            with self.assertRaises(pl.PaperLedgerError, msg=repr(bad)):
                pl._validate_record(_record([bad]))

    def test_correct_outcome_sign_passes(self):  # positive controls: a stop loses, a tp gains
        pl._validate_record(_record([_entry("filled_stopped", net_return=-0.05, gross_return=-0.05),
                                     _entry("filled_tp_exit", net_return=0.05, gross_return=0.05)]))


class WriteGuardAndRoundtrip(unittest.TestCase):
    def test_relative_path_refused(self):
        with self.assertRaises(PrivatePathError):
            pl.write_paper_performance(_record(), "rel_paper.json")

    def test_tracked_in_repo_path_refused(self):
        with self.assertRaises(PrivatePathError):
            pl.write_paper_performance(_record(), ROOT / "docs" / "_nonprivate_paper_probe.json")
        self.assertFalse((ROOT / "docs" / "_nonprivate_paper_probe.json").exists())  # refused before any write

    def test_refuses_malformed_before_write(self):
        d = Path(tempfile.mkdtemp())
        try:
            with self.assertRaises(pl.PaperLedgerError):
                pl.write_paper_performance(_record([_entry(outcome="made_up")]), d / "x.json")
            self.assertFalse((d / "x.json").exists())  # validate fails closed, no file
        finally:
            for f in d.glob("*"):
                f.unlink()
            d.rmdir()

    def test_outside_repo_roundtrip(self):
        d = Path(tempfile.mkdtemp())
        try:
            rec = _record([_entry(o) for o in pl._OUTCOMES])
            p = pl.write_paper_performance(rec, d / "paper_performance.json")
            self.assertTrue(p.exists())
            self.assertEqual(pl.load_paper_performance(p), rec)
        finally:
            for f in d.glob("*"):
                f.unlink()
            d.rmdir()

    def test_load_refuses_tampered_row(self):  # a persisted row tampered to violate the invariant is refused on load
        d = Path(tempfile.mkdtemp())
        try:
            p = pl.write_paper_performance(_record([_entry("filled_tp_exit")]), d / "pp.json")
            data = json.loads(p.read_text(encoding="utf-8"))
            data["entries"][0]["net_return"] = 0.99  # tamper: net_return no longer == gross_return - cost_fraction
            p.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(pl.PaperLedgerError):
                pl.load_paper_performance(p)
        finally:
            for f in d.glob("*"):
                f.unlink()
            d.rmdir()


class LoadGuardAndFailClosed(unittest.TestCase):
    def test_relative_source_refused(self):
        with self.assertRaises(PrivatePathError):
            pl.load_paper_performance("rel_paper.json")

    def test_tracked_in_repo_source_refused(self):
        with self.assertRaises(PrivatePathError):
            pl.load_paper_performance(ROOT / "docs" / "README.md")

    def test_missing_or_corrupt_or_invalid_refused(self):
        d = Path(tempfile.mkdtemp())
        try:
            with self.assertRaises(pl.PaperLedgerError):  # missing
                pl.load_paper_performance(d / "nope.json")
            (d / "bad.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(pl.PaperLedgerError):  # corrupt JSON
                pl.load_paper_performance(d / "bad.json")
            (d / "inval.json").write_text(json.dumps({"as_of": "20260619", "entries": [{"outcome": "made_up"}]}), encoding="utf-8")
            with self.assertRaises(pl.PaperLedgerError):  # valid JSON, invalid record
                pl.load_paper_performance(d / "inval.json")
        finally:
            for f in d.glob("*"):
                f.unlink()
            d.rmdir()


class IntegrationWithNetResult(unittest.TestCase):
    """Drift guard: real paper_net_result outputs are valid ledger entries (so a net-result shape change surfaces)."""

    def test_real_net_results_are_valid_entries(self):
        import engine.us_short_paper_net_result as nr
        cost = {"commission_fee": 0.001, "slippage_bps": 10.0, "spread_cost": 0.0005}
        fills = [
            {"status": "not_filled", "fill_price": None, "exit_price": None, "exit_reason": None, "reason": "x"},
            {"status": "filled_held", "fill_price": 100.0, "exit_price": None, "exit_reason": None, "reason": None},
            {"status": "filled_stopped", "fill_price": 100.0, "exit_price": 95.0, "exit_reason": "same_day_stop", "reason": None},
            {"status": "filled_tp_exit", "fill_price": 100.0, "exit_price": 110.0, "exit_reason": "same_day_tp_exit", "reason": None},
        ]
        entries = [nr.paper_net_result(f, cost_prior=cost) for f in fills]
        pl._validate_record(_record(entries))  # must not raise — net_result outputs ARE valid ledger entries


class DateAsciiStrict(unittest.TestCase):
    """R-USSHORT-BATCH3-PAPER-LEDGER-DATE-ASCII-GAP: the inline date gate rejects Unicode digit dates (only ASCII
    digits pass — int() would otherwise coerce Arabic-Indic / fullwidth digits)."""

    def test_ascii_accepted_unicode_rejected(self):
        self.assertTrue(pl._strict_yyyymmdd("20260619"))
        for bad in ("٢٠٢٦٠٦١٩",  # Arabic-Indic "20260619"
                    "２０２６０６１９"):  # fullwidth "20260619"
            self.assertFalse(pl._strict_yyyymmdd(bad), repr(bad))
            with self.assertRaises(pl.PaperLedgerError):  # and via the record as_of gate
                pl._validate_record({"as_of": bad, "entries": []})


class CanonicalArtifact(unittest.TestCase):
    """R-USSHORT-BATCH3-PAPER-LEDGER-FORMAT-DRIFT (resolved via design-owner decision 2026-06-23 → JSON): lock the
    canonical format so code and §12.1 authority agree on `paper_performance.json`, not `.csv`."""

    def test_canonical_filename_and_dir(self):
        self.assertEqual(pl.PAPER_PERFORMANCE_PATH.name, "paper_performance.json")
        self.assertEqual(pl.PAPER_PERFORMANCE_PATH.parent.name, "model_paper_private")


if __name__ == "__main__":
    unittest.main()
