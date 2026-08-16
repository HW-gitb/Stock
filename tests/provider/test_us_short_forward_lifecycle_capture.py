from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_status_source as status_source  # noqa: E402
from runners import us_short_forward_lifecycle_capture as lifecycle  # noqa: E402
from tests.provider.us_short_private_test_root_light import temporary_us_short_state_directory  # noqa: E402


OBSERVED_AT = "2026-07-13T13:00:00Z"
STATE_DIR = ROOT / "state" / "us_short"


def _ticker_reference(*, active: bool = True, exchange: str = "NYSE") -> dict:
    return {
        "observed": True,
        "observed_at": OBSERVED_AT,
        "coverage": "full",
        "active_listings": {"TEST": {"active": active, "primary_exchange": exchange}},
    }


def _halt_feed(*, halted: bool = False) -> dict:
    return {
        "observed": True,
        "observed_at": OBSERVED_AT,
        "halted_symbols": ["TEST"] if halted else [],
    }


def _bankruptcy_screen(*, bankrupt: bool = False) -> dict:
    return {
        "observed": True,
        "observed_at": OBSERVED_AT,
        "lookback_window": "P90D",
        "by_ticker": {
            "TEST": {
                "screen_status": "bankrupt_8k_found" if bankrupt else "screened_no_filing",
                "filing_accession": "0000000000-test" if bankrupt else None,
            }
        },
    }


def _status_record(
    ticker: str,
    *,
    active: bool = True,
    exchange: str = "NYSE",
    halted: bool = False,
    bankrupt: bool = False,
    unknown: bool = False,
) -> dict:
    if unknown:
        return status_source.resolve_status_record(
            ticker,
            as_of="2026-07-13",
            observed_at=OBSERVED_AT,
        )
    reference = _ticker_reference(active=active, exchange=exchange)
    reference["active_listings"] = {ticker: reference["active_listings"].pop("TEST")}
    feed = _halt_feed(halted=halted)
    feed["halted_symbols"] = [ticker] if halted else []
    bankruptcy = _bankruptcy_screen(bankrupt=bankrupt)
    bankruptcy["by_ticker"] = {ticker: bankruptcy["by_ticker"].pop("TEST")}
    return status_source.resolve_status_record(
        ticker,
        ticker_reference=reference,
        halt_feed=feed,
        bankruptcy_screen=bankruptcy,
        as_of="2026-07-13",
        observed_at=OBSERVED_AT,
    )


def _candidate_row(ticker: str, record: dict) -> dict:
    return {
        "ticker": ticker,
        "exchange": "NYSE",
        "delisted": record["flags"]["delisted"]["value"],
        "halted": record["flags"]["halted"]["value"],
        "bankruptcy": record["flags"]["bankruptcy"]["value"],
        "otc": record["flags"]["otc"]["value"],
        "status_flags_sourced": True,
        "status_provenance": record,
    }


def _candidate_payload(decision_date: str, rows: list[dict]) -> dict:
    return {
        "schema_name": "us_short_universe_candidate_artifact",
        "schema_version": "1.1.0",
        "decision_date": decision_date,
        "generated_at": OBSERVED_AT,
        "rows": rows,
        "row_count": len(rows),
    }


class ForwardLifecycleCaptureTest(unittest.TestCase):
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_dir = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        original_state_dir = lifecycle.STATE_DIR
        original_snapshot_state_dir = lifecycle.forward_snapshot.STATE_US_SHORT_DIR
        lifecycle.STATE_DIR = self.state_dir
        lifecycle.forward_snapshot.STATE_US_SHORT_DIR = self.state_dir
        self.addCleanup(setattr, lifecycle, "STATE_DIR", original_state_dir)
        self.addCleanup(setattr, lifecycle.forward_snapshot, "STATE_US_SHORT_DIR", original_snapshot_state_dir)
        token = __import__('os').getpid()
        self.initial_path = self.state_dir / f"test_forward_lifecycle_{token}_candidate_initial.json"
        self.current_path = self.state_dir / f"test_forward_lifecycle_{token}_candidate_current.json"
        self.snapshot_path = self.state_dir / "forward_universe_snapshot_20260713.json"
        self.observation_path = self.state_dir / "forward_lifecycle_observation_20260713_20260713.json"
        self._remove_output_paths()

    def tearDown(self):
        self._remove_output_paths()
        self.initial_path.unlink(missing_ok=True)
        self.current_path.unlink(missing_ok=True)

    def _remove_output_paths(self):
        for path in (self.snapshot_path, self.observation_path):
            path.unlink(missing_ok=True)

    def _write_candidate(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _freeze_initial_snapshot(self):
        rows = [
            _candidate_row(symbol, _status_record(symbol))
            for symbol in ("AAPL", "DEAD", "HALT", "BANK", "GONE", "OTCM", "UNKN")
        ]
        self._write_candidate(self.initial_path, _candidate_payload("20260713", rows))
        return lifecycle.freeze_forward_snapshot(
            confirm_user_authorization=True,
            candidate_path=self.initial_path,
        )

    def test_freezes_active_snapshot_and_records_only_fail_closed_lifecycle_events(self):
        self._freeze_initial_snapshot()
        current_rows = [
            _candidate_row("AAPL", _status_record("AAPL")),
            _candidate_row("DEAD", _status_record("DEAD", active=False)),
            _candidate_row("HALT", _status_record("HALT", halted=True)),
            _candidate_row("BANK", _status_record("BANK", bankrupt=True)),
            _candidate_row("OTCM", _status_record("OTCM", exchange="OTC")),
            _candidate_row("UNKN", _status_record("UNKN", unknown=True)),
        ]
        self._write_candidate(self.current_path, _candidate_payload("20260713", current_rows))

        result = lifecycle.capture_forward_lifecycle_observation(
            confirm_user_authorization=True,
            snapshot_path=self.snapshot_path,
            candidate_path=self.current_path,
        )
        self.assertEqual(result["event_count"], 6)
        self.assertEqual(result["blocked_symbol_count"], 6)

        observation = json.loads(self.observation_path.read_text(encoding="utf-8"))
        events_by_symbol = {event["symbol"]: event for event in observation["events"]}
        self.assertNotIn("AAPL", events_by_symbol)
        self.assertEqual(events_by_symbol["DEAD"]["event_type"], "inactive_or_ticker_change_unresolved")
        self.assertEqual(events_by_symbol["HALT"]["event_type"], "halted")
        self.assertEqual(events_by_symbol["BANK"]["event_type"], "bankruptcy")
        self.assertEqual(events_by_symbol["GONE"]["event_type"], "missing_from_current_universe_requires_manual_review")
        self.assertEqual(events_by_symbol["OTCM"]["event_type"], "otc_or_exchange_migration")
        self.assertEqual(events_by_symbol["UNKN"]["event_type"], "critical_status_unknown_requires_manual_review")
        self.assertTrue(all(event["manual_review_required"] for event in observation["events"]))
        self.assertTrue(all(event["new_entry_blocked"] for event in observation["events"]))
        self.assertFalse(observation["boundary"]["automatic_corporate_action_processing_performed"])
        self.assertFalse(observation["boundary"]["merger_or_ticker_change_semantics_confirmed"])
        self.assertFalse(observation["boundary"]["selection_or_ranking_changed"])

    def test_missing_confirmation_or_bad_status_rejects_before_private_outputs(self):
        rows = [_candidate_row("AAPL", _status_record("AAPL"))]
        self._write_candidate(self.initial_path, _candidate_payload("20260713", rows))
        with self.assertRaises(lifecycle.ForwardLifecycleCaptureError):
            lifecycle.freeze_forward_snapshot(
                confirm_user_authorization=False,
                candidate_path=self.initial_path,
            )
        self.assertFalse(self.snapshot_path.exists())

        broken = _candidate_payload("20260713", rows)
        broken["rows"][0]["status_flags_sourced"] = False
        self._write_candidate(self.initial_path, broken)
        with self.assertRaises(lifecycle.ForwardLifecycleCaptureError):
            lifecycle.freeze_forward_snapshot(
                confirm_user_authorization=True,
                candidate_path=self.initial_path,
            )
        self.assertFalse(self.snapshot_path.exists())

    def test_noncanonical_or_duplicate_current_symbol_rejects_before_observation_write(self):
        self._freeze_initial_snapshot()
        rows = [_candidate_row("aapl", _status_record("AAPL"))]
        self._write_candidate(self.current_path, _candidate_payload("20260713", rows))
        with self.assertRaises(lifecycle.ForwardLifecycleCaptureError):
            lifecycle.capture_forward_lifecycle_observation(
                confirm_user_authorization=True,
                snapshot_path=self.snapshot_path,
                candidate_path=self.current_path,
            )
        self.assertFalse(self.observation_path.exists())


if __name__ == "__main__":
    unittest.main()
