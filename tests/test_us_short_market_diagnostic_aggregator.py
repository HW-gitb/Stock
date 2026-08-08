from __future__ import annotations

import copy
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

import jsonschema
from referencing import Registry, Resource

from engine.us_short_market_diagnostic import construct_weekly_return
from engine.us_short_market_diagnostic_aggregator import (
    MarketDiagnosticAggregationError,
    build_market_diagnostic_report,
    publish_completed_market_diagnostic_window,
    render_market_diagnostic_markdown,
    write_market_diagnostic_report,
)
from engine.us_short_market_diagnostic_lifecycle import persist_settled_weekly_record
from engine.us_short_market_diagnostic_start_receipt import issue_start_receipt
from tests.test_us_short_market_diagnostic import _weekly_rows


ROOT = Path(__file__).resolve().parents[1]


def _money(value: Decimal) -> str:
    return f"{value:.6f}"


def _two_window_rows() -> list[dict]:
    first = _weekly_rows()
    second = copy.deepcopy(first)
    previous_nav = Decimal(first[-1]["strategy"]["nav"])
    previous_cost = Decimal(first[-1]["strategy"]["cumulative_cost_paid"])
    for row in second:
        week = row["calendar_week_index"] + 26
        row["calendar_week_index"] = week
        row["window_id"] = "26w-27-52"
        for field in ("decision_date", "valuation_date"):
            shifted = date.fromisoformat(row[field][:4] + "-" + row[field][4:6] + "-" + row[field][6:])
            row[field] = (shifted + timedelta(days=26 * 7)).strftime("%Y%m%d")
        for benchmark in row["benchmarks"].values():
            shifted = date.fromisoformat(
                benchmark["price_date"][:4]
                + "-"
                + benchmark["price_date"][4:6]
                + "-"
                + benchmark["price_date"][6:]
            )
            benchmark["price_date"] = (shifted + timedelta(days=26 * 7)).strftime("%Y%m%d")
        weekly_return = row["strategy"]["weekly_return"]
        current_nav = (
            previous_nav
            if weekly_return is None
            else (previous_nav * (Decimal("1") + Decimal(str(weekly_return)))).quantize(Decimal("0.000001"))
        )
        row["strategy"]["prior_nav"] = _money(previous_nav)
        row["strategy"]["nav"] = _money(current_nav)
        row["strategy"]["weekly_return"] = construct_weekly_return(
            _money(previous_nav), _money(current_nav)
        )
        row["strategy"]["cash"] = _money((current_nav * Decimal("0.600000")).quantize(Decimal("0.000001")))
        row["strategy"]["market_value"] = _money(
            (current_nav * Decimal("0.400000")).quantize(Decimal("0.000001"))
        )
        row["strategy"]["cumulative_cost_paid"] = _money(
            previous_cost + Decimal(row["strategy"]["cumulative_cost_paid"])
        )
        row["strategy"]["source_sha256"] = f"{600 + week:064x}"
        # De-duplicate: benchmarks share price packets, and a record whose source
        # digests repeat is rejected by the store. These rows now have to survive
        # persistence, because the report is derived from the store rather than
        # handed to the builder.
        digests = [
            digest
            for benchmark in row["benchmarks"].values()
            for digest in (
                benchmark["price_packet_sha256"],
                benchmark["dividend_sidecar_sha256"],
            )
            if digest is not None
        ] + [f"{900 + week:064x}"]
        row["source_refs"] = list(dict.fromkeys(digests))
        previous_nav = current_nav
    return first + second


def _validate_report_schema(report: dict) -> None:
    report_schema = json.loads(
        (ROOT / "schemas" / "us_short_market_diagnostic_report.schema.json").read_text(encoding="utf-8")
    )
    summary_schema = json.loads(
        (ROOT / "schemas" / "us_short_market_diagnostic_summary.schema.json").read_text(encoding="utf-8")
    )
    registry = Registry().with_resources(
        [
            (report_schema["$id"], Resource.from_contents(report_schema)),
            (summary_schema["$id"], Resource.from_contents(summary_schema)),
            ("us_short_market_diagnostic_summary.schema.json", Resource.from_contents(summary_schema)),
        ]
    )
    errors = sorted(
        jsonschema.Draft7Validator(report_schema, registry=registry).iter_errors(report),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise AssertionError(errors[0].message)


def _authorized_store(testcase, rows):
    """A real, authorized lifecycle store that outlives the test body.

    Knife 7 makes producing a verdict need the same authorization as reading the
    weeks it summarises, so these tests can no longer hand a bare list of records
    to the builder: they open a clock the way an operator would.
    """

    holder = tempfile.TemporaryDirectory()
    testcase.addCleanup(holder.cleanup)
    root = Path(holder.name) / "market_diagnostic_private"
    issue_start_receipt(
        diagnostic_epoch=rows[0]["diagnostic_epoch"],
        completion_notification={
            "issued_at": "2025-12-29T00:00:00+00:00",
            "issuer": "codex",
            "notification_text": "US-short 26-week diagnostic design is complete.",
        },
        first_decision_date=rows[0]["decision_date"],
        root=root,
        as_of_date="20260731",
    )
    for row in rows:
        persist_settled_weekly_record(row, root=root)
    return root


class UsShortMarketDiagnosticAggregatorTest(unittest.TestCase):
    def test_missing_real_lifecycle_is_not_started_and_creates_no_public_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lifecycle_root = Path(td) / "not_started"
            output_root = Path(td) / "market_diagnostic_26w"
            self.assertEqual(
                {"status": "not_started"},
                publish_completed_market_diagnostic_window(
                    lifecycle_root=lifecycle_root,
                    output_root=output_root,
                    as_of_date="20260731",
                ),
            )
            self.assertFalse(output_root.exists())

    def test_does_not_publish_before_a_canonical_26_week_boundary(self) -> None:
        rows = _weekly_rows()[:25]
        store = _authorized_store(self, rows)
        self.assertIsNone(build_market_diagnostic_report(lifecycle_root=store))

    def test_builds_fixed_window_since_inception_and_deidentified_markdown(self) -> None:
        rows = _weekly_rows()
        store = _authorized_store(self, rows)
        report = build_market_diagnostic_report(lifecycle_root=store)
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual("26w-1-26", report["window_summary"]["window_id"])
        self.assertEqual(26, report["since_inception"]["calendar_week_count"])
        self.assertEqual(["VTI", "IWB", "SPY", "QQQ"], list(report["window_summary"]["benchmarks"]))
        self.assertEqual(
            "v1.1 attribution is active and remains sticky after automatic activation.",
            report["window_summary"]["v1_1_reminder"]["text"],
        )
        self.assertEqual(1, len(report["ruleset_segments"]["fixed_window"]))
        _validate_report_schema(report)

        markdown = render_market_diagnostic_markdown(report)
        self.assertIn("当前 26 周区块", markdown)
        self.assertIn("Since-inception 表现", markdown)
        self.assertNotIn("20260105", markdown)
        self.assertNotIn("100000.000000", markdown)

    def test_the_public_projection_refuses_free_text_and_unsafe_identifiers(self) -> None:
        """What stops the private store's Chinese reminder and raw fields reaching a shared file.

        This coverage used to ride on the write-once test, which handed a mutated
        report to the writer. The writer no longer takes one, and the guard was
        left with nothing exercising it: stubbing it out kept the whole pack
        green. ``render_market_diagnostic_markdown`` is the remaining consumer
        that takes a report in hand, so the projection is asserted through it.
        """

        store = _authorized_store(self, _weekly_rows())
        report = build_market_diagnostic_report(lifecycle_root=store)
        assert report is not None
        self.assertTrue(render_market_diagnostic_markdown(report))

        cases = {
            "non-canonical reminder text": ("window_summary", "v1_1_reminder", "text",
                                            "PII must not enter public output"),
            "unknown reminder status": ("window_summary", "v1_1_reminder", "status", "surprise"),
            "free-text status reason": ("window_summary", "status_reason", None,
                                        "because the market was strange this quarter"),
            "unsafe epoch identifier": ("window_summary", "diagnostic_epoch", None,
                                        "epoch for cnhea's account"),
            "unsafe epoch in since_inception": ("since_inception", "diagnostic_epoch", None,
                                                "epoch\nwith a newline"),
        }
        for label, (scope, field, subfield, value) in cases.items():
            with self.subTest(label):
                tampered = copy.deepcopy(report)
                if subfield is None:
                    tampered[scope][field] = value
                else:
                    tampered[scope][field][subfield] = value
                with self.assertRaises(MarketDiagnosticAggregationError):
                    render_market_diagnostic_markdown(tampered)

    def test_second_boundary_keeps_fixed_block_separate_from_since_inception(self) -> None:
        store = _authorized_store(self, _two_window_rows())
        report = build_market_diagnostic_report(lifecycle_root=store)
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual("26w-27-52", report["window_summary"]["window_id"])
        self.assertEqual(52, report["since_inception"]["calendar_week_count"])
        self.assertEqual("26w-27-52", report["since_inception"]["through_window_id"])
        self.assertEqual(26, report["window_summary"]["calendar_weeks"])
        _validate_report_schema(report)

    def test_public_pair_is_immutable_and_identical_rerun_is_idempotent(self) -> None:
        rows = _weekly_rows()
        store = _authorized_store(self, rows)
        report = build_market_diagnostic_report(lifecycle_root=store)
        assert report is not None
        with tempfile.TemporaryDirectory() as td:
            output_root = Path(td) / "market_diagnostic_26w"
            self.assertEqual("published", write_market_diagnostic_report(lifecycle_root=store, output_root=output_root))
            json_path = output_root / "26w-1-26.json"
            markdown_path = output_root / "26w-1-26.md"
            json_bytes = json_path.read_bytes()
            markdown_bytes = markdown_path.read_bytes()
            self.assertEqual("idempotent", write_market_diagnostic_report(lifecycle_root=store, output_root=output_root))
            self.assertEqual(json_bytes, json_path.read_bytes())
            self.assertEqual(markdown_bytes, markdown_path.read_bytes())

            # A conflicting verdict can no longer be handed in — the writer derives
            # its own report — so the only way two verdicts can now collide is two
            # genuinely different authorized stores aiming at the same window.
            other_rows = copy.deepcopy(rows)
            for row in other_rows:
                row["diagnostic_epoch"] = "us-short-26w-other"
            other_store = _authorized_store(self, other_rows)
            with self.assertRaises(MarketDiagnosticAggregationError):
                write_market_diagnostic_report(lifecycle_root=other_store, output_root=output_root)

            markdown_path.unlink()
            with self.assertRaises(MarketDiagnosticAggregationError):
                write_market_diagnostic_report(lifecycle_root=store, output_root=output_root)

    def test_lifecycle_publish_only_emits_at_week_26(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lifecycle_root = Path(td) / "market_diagnostic_private"
            rows = _weekly_rows()
            issue_start_receipt(
                diagnostic_epoch=rows[0]["diagnostic_epoch"],
                completion_notification={
                    "issued_at": "2025-12-29T00:00:00+00:00",
                    "issuer": "codex",
                    "notification_text": "US-short 26-week diagnostic design is complete.",
                },
                first_decision_date=rows[0]["decision_date"],
                root=lifecycle_root,
                as_of_date="20260731",
            )
            output_root = Path(td) / "market_diagnostic_26w"
            for row in _weekly_rows()[:25]:
                persist_settled_weekly_record(row, root=lifecycle_root)
            self.assertEqual(
                {"status": "not_ready", "last_calendar_week_index": 25},
                publish_completed_market_diagnostic_window(
                    lifecycle_root=lifecycle_root,
                    output_root=output_root,
                    as_of_date="20260731",
                ),
            )
            persist_settled_weekly_record(_weekly_rows()[25], root=lifecycle_root)
            result = publish_completed_market_diagnostic_window(
                lifecycle_root=lifecycle_root,
                output_root=output_root,
                as_of_date="20260731",
            )
            self.assertEqual("published", result["status"])
            self.assertEqual("26w-1-26", result["window_id"])
            self.assertTrue((output_root / "26w-1-26.json").is_file())
            self.assertTrue((output_root / "26w-1-26.md").is_file())
            self.assertEqual(
                "idempotent",
                publish_completed_market_diagnostic_window(
                    lifecycle_root=lifecycle_root,
                    output_root=output_root,
                    as_of_date="20260731",
                )["status"],
            )


if __name__ == "__main__":
    unittest.main()
