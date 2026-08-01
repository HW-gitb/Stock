from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.us_short_forward_universe_snapshot import (  # noqa: E402
    ForwardUniverseSnapshotError,
    build_forward_universe_snapshot,
    write_forward_universe_snapshot,
)
from runners import us_short_forward_universe_snapshot as snapshot_runner  # noqa: E402
from tests.provider.us_short_private_test_root import temporary_us_short_state_directory  # noqa: E402


STATE_DIR = ROOT / "state" / "us_short"


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class ForwardUniverseSnapshotTest(unittest.TestCase):
    def setUp(self):
        self._state_root_context = temporary_us_short_state_directory(ROOT)
        self.state_dir = Path(self._state_root_context.__enter__())
        self.addCleanup(self._state_root_context.__exit__, None, None, None)
        original_git_ignored = snapshot_runner._git_ignored
        state_root = self.state_dir.resolve()

        def _git_ignored_for_private_test(path):
            resolved = Path(path).resolve()
            if resolved == state_root or state_root in resolved.parents:
                return True
            return original_git_ignored(path)

        snapshot_runner._git_ignored = _git_ignored_for_private_test
        self.addCleanup(setattr, snapshot_runner, "_git_ignored", original_git_ignored)
        self.slug = f"test_forward_universe_{os.getpid()}_{self._testMethodName}"
        self.input_path = self.state_dir / f"{self.slug}_input.json"
        self.output_path = snapshot_runner._snapshot_path_for("20260706")
        self.leaky_output = ROOT / "docs" / f"{self.slug}_snapshot.json"
        for path in (self.input_path, self.output_path, self.leaky_output):
            path.unlink(missing_ok=True)

    def tearDown(self):
        for path in (self.input_path, self.output_path, self.leaky_output):
            path.unlink(missing_ok=True)

    def _rows(self):
        return [
            {
                "symbol": " msft ",
                "listing_status": "active",
                "primary_exchange": "NASDAQ",
                "cik": "0000789019",
                "status_as_of": "2026-07-06",
            },
            {
                "ticker": "AAPL",
                "listing_status": "active",
                "exchange": "NASDAQ",
                "cik": 320193,
            },
        ]

    def _source_refs(self):
        return [{"role": "active_listing_input", "path": _rel(self.input_path)}]

    def test_build_snapshot_freezes_active_universe_with_hashes_and_retention_policy(self):
        _write_json(self.input_path, {"rows": self._rows()})

        snapshot = build_forward_universe_snapshot(
            forward_start_date="20260706",
            provider_as_of="2026-07-06",
            provider_label="local_reviewed_active_listing",
            source_refs=self._source_refs(),
            rows=self._rows(),
            generated_at="2026-07-06T00:00:00Z",
        )

        self.assertEqual(snapshot["schema_name"], "us_short_forward_universe_snapshot")
        self.assertEqual(snapshot["forward_start_date"], "20260706")
        self.assertEqual(snapshot["provider_as_of"], "2026-07-06")
        self.assertEqual(snapshot["row_count"], 2)
        self.assertEqual(snapshot["active_symbols"], ["AAPL", "MSFT"])
        self.assertEqual([row["ticker"] for row in snapshot["active_universe"]], ["AAPL", "MSFT"])
        self.assertTrue(snapshot["retention_policy"]["delist_events_retained"])
        self.assertTrue(snapshot["retention_policy"]["halt_events_retained"])
        self.assertTrue(snapshot["retention_policy"]["merger_events_retained"])
        self.assertTrue(snapshot["retention_policy"]["no_trade_events_retained"])
        self.assertFalse(snapshot["retention_policy"]["post_forward_start_deletion_allowed"])
        self.assertEqual(snapshot["hashes"]["algorithm"], "sha256")
        self.assertRegex(snapshot["hashes"]["active_symbols_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(snapshot["hashes"]["active_universe_rows_sha256"], r"^[0-9a-f]{64}$")
        self.assertFalse(snapshot["scope"]["network_access_performed"])
        self.assertFalse(snapshot["scope"]["provider_calls_performed"])
        self.assertFalse(snapshot["scope"]["datahub_consumption_allowed"])
        self.assertFalse(snapshot["scope"]["production_storage_allowed"])
        self.assertFalse(snapshot["scope"]["ship_gate_evidence_claimed"])
        self.assertFalse(snapshot["scope"]["broker_or_order_automation_allowed"])
        self.assertFalse(snapshot["scope"]["a_share_crossing_allowed"])

    def test_rejects_duplicate_ticker_after_canonicalization(self):
        rows = self._rows() + [{"ticker": "aapl", "listing_status": "active", "primary_exchange": "NASDAQ"}]
        _write_json(self.input_path, {"rows": rows})

        with self.assertRaises(ForwardUniverseSnapshotError):
            build_forward_universe_snapshot(
                forward_start_date="20260706",
                provider_as_of="2026-07-06",
                provider_label="local_reviewed_active_listing",
                source_refs=self._source_refs(),
                rows=rows,
                generated_at="2026-07-06T00:00:00Z",
            )

    def test_rejects_inactive_or_unknown_listing_status(self):
        rows = [{"ticker": "AAPL", "listing_status": "delisted", "primary_exchange": "NASDAQ"}]
        _write_json(self.input_path, {"rows": rows})

        with self.assertRaises(ForwardUniverseSnapshotError):
            build_forward_universe_snapshot(
                forward_start_date="20260706",
                provider_as_of="2026-07-06",
                provider_label="local_reviewed_active_listing",
                source_refs=self._source_refs(),
                rows=rows,
                generated_at="2026-07-06T00:00:00Z",
            )

    def test_rejects_non_string_exchange_without_typeerror(self):
        for field in ("primary_exchange", "exchange"):
            for bad_exchange in ({"exchange": "NASDAQ"}, ["NASDAQ"]):
                with self.subTest(field=field, bad_type=type(bad_exchange).__name__):
                    row = {"ticker": "AAPL", "listing_status": "active", field: bad_exchange}
                    _write_json(self.input_path, {"rows": [row]})

                    with self.assertRaises(ForwardUniverseSnapshotError):
                        build_forward_universe_snapshot(
                            forward_start_date="20260706",
                            provider_as_of="2026-07-06",
                            provider_label="local_reviewed_active_listing",
                            source_refs=self._source_refs(),
                            rows=[row],
                            generated_at="2026-07-06T00:00:00Z",
                        )

    def test_write_snapshot_requires_canonical_gitignored_state_path(self):
        _write_json(self.input_path, {"rows": self._rows()})

        with self.assertRaises(ForwardUniverseSnapshotError):
            write_forward_universe_snapshot(
                forward_start_date="20260706",
                provider_as_of="2026-07-06",
                provider_label="local_reviewed_active_listing",
                source_refs=self._source_refs(),
                rows=self._rows(),
                output_path=self.leaky_output,
                generated_at="2026-07-06T00:00:00Z",
            )

        self.assertFalse(self.leaky_output.exists())

    def test_cli_reads_local_input_and_writes_gitignored_snapshot(self):
        _write_json(self.input_path, {"rows": self._rows()})

        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT)
        env["PYTHONIOENCODING"] = "utf-8"   # GOV-R6: pin both ends, never the ambient locale
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "runners" / "us_short_forward_universe_snapshot.py"),
                "--input",
                _rel(self.input_path),
                "--forward-start-date",
                "20260706",
                "--provider-as-of",
                "2026-07-06",
                "--provider-label",
                "local_reviewed_active_listing",
                "--generated-at",
                "2026-07-06T00:00:00Z",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.output_path.exists())
        summary = json.loads(result.stdout)
        self.assertEqual(summary["snapshot_path"], _rel(self.output_path))
        self.assertEqual(summary["row_count"], 2)
        written = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertEqual(written["active_symbols"], ["AAPL", "MSFT"])


if __name__ == "__main__":
    unittest.main()
