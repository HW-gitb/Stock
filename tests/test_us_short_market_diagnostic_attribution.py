from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import unittest

from jsonschema import Draft7Validator

from engine.us_short_market_diagnostic_attribution import (
    ATTRIBUTION_BOUNDARY,
    _MAX_CASH_ANNUALISED,
    _MAX_CASH_EFFECTIVE_DAYS,
    _MIN_CASH_ANNUALISED,
    _TOLERANCE,
    AttributionError,
    build_attribution_input,
    build_attribution_report,
    calculate_target_exposure,
    validate_attribution_input,
    validate_attribution_report,
)
from tests.test_us_short_market_diagnostic import _weekly_rows


ROOT = Path(__file__).resolve().parents[1]


class UsShortMarketDiagnosticAttributionTest(unittest.TestCase):
    def _cash(self, rows: list[dict], *, unavailable_week: int | None = None) -> dict[int, dict]:
        result: dict[int, dict] = {}
        for row in rows:
            week = row["calendar_week_index"]
            if week == unavailable_week:
                continue
            valuation = datetime.strptime(row["valuation_date"], "%Y%m%d").date()
            source = f"{500 + week:064x}"
            result[week] = {
                "status": "evaluable",
                "instrument": "pit_3m_tbill",
                "weekly_return": 0.0001,
                "effective_start_date": (valuation - timedelta(days=7)).strftime("%Y%m%d"),
                "effective_end_date": valuation.strftime("%Y%m%d"),
                "as_of_date": valuation.strftime("%Y%m%d"),
                "available_at": f"{row['decision_date'][0:4]}-{row['decision_date'][4:6]}-{row['decision_date'][6:8]}T08:00:00Z",
                "source_sha256": source,
                "source_refs": [source],
                "data_quality_reasons": [],
            }
        return result

    def _target(self, rows: list[dict], *, cash_capacity: float = 0.5) -> dict[int, dict]:
        result: dict[int, dict] = {}
        for row in rows:
            week = row["calendar_week_index"]
            source = f"{600 + week:064x}"
            result[week] = {
                "status": "evaluable",
                "as_of_date": row["decision_date"],
                "carried_holdings_exposure": 0.2,
                "new_order_exposure": 0.4,
                "cash_capacity_exposure": cash_capacity,
                "environment_position_cap": 0.8,
                "long_only_cap": 1.0,
                "source_refs": [source],
                "data_quality_reasons": [],
            }
        return result

    def _packet(self, *, price_only: bool = False, cash: dict[int, dict] | None = None) -> dict:
        rows = _weekly_rows(price_only=price_only)[:2]
        return build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week=self._cash(rows) if cash is None else cash,
        )

    def test_complete_packet_splits_excess_and_preserves_identity(self) -> None:
        packet = self._packet()
        report = build_attribution_report(packet)

        self.assertEqual(report["status"], "evaluable")
        self.assertEqual(report["summary"]["evaluable_weeks"], 2)
        self.assertEqual(report["summary"]["unavailable_weeks"], 0)
        for row in report["weeks"]:
            self.assertEqual(row["g_star"], 0.5)
            self.assertAlmostEqual(
                row["raw_excess"], row["exposure_effect"] + row["active_system_effect"], places=12
            )
            self.assertAlmostEqual(row["identity_residual"], 0.0, places=12)
        self.assertAlmostEqual(
            report["summary"]["raw_excess"],
            report["summary"]["exposure_effect"] + report["summary"]["active_system_effect"],
            places=12,
        )
        validate_attribution_report(report)
        schema = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "schemas"
                / "us_short_market_diagnostic_attribution_report.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            [],
            list(Draft7Validator(schema).iter_errors(report)),
        )

    def test_missing_cash_is_unavailable_and_never_zero_filled(self) -> None:
        rows = _weekly_rows()[:2]
        packet = build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week={},
        )
        report = build_attribution_report(packet)

        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["summary"]["evaluable_weeks"], 0)
        self.assertEqual(report["summary"]["unavailable_weeks"], 2)
        self.assertIsNone(report["summary"]["active_system_effect"])
        self.assertIn("pit_3m_tbill_not_available", report["weeks"][0]["unavailable_reasons"])
        self.assertTrue(all(row["matched_target_return"] is None for row in report["weeks"]))
        validate_attribution_report(report)

    def test_price_only_vti_cannot_enter_attribution(self) -> None:
        report = build_attribution_report(self._packet(price_only=True))

        self.assertEqual(report["status"], "unavailable")
        self.assertTrue(all(row["vti_total_return"] is None for row in report["weeks"]))
        self.assertIn("vti_total_return_not_available", report["weeks"][0]["unavailable_reasons"])

    def test_target_exposure_uses_rule_constraints_not_actual_nav(self) -> None:
        target = {
            "status": "evaluable",
            "as_of_date": "20260102",
            "carried_holdings_exposure": 0.7,
            "new_order_exposure": 0.6,
            "cash_capacity_exposure": 0.9,
            "environment_position_cap": 0.8,
            "long_only_cap": 1.0,
            "source_refs": ["a" * 64],
            "data_quality_reasons": [],
        }

        result = calculate_target_exposure(target)

        self.assertAlmostEqual(result["requested_exposure"], 1.3)
        self.assertAlmostEqual(result["g_star"], 0.8)
        self.assertEqual(result["binding_constraints"], ["environment_position_cap"])

    def test_cash_observation_after_decision_date_is_rejected(self) -> None:
        rows = _weekly_rows()[:2]
        cash = self._cash(rows)
        cash[1]["available_at"] = "2026-01-03T08:00:00Z"

        with self.assertRaises(AttributionError):
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=cash,
            )

    def _fat_rows(self) -> list[dict]:
        """26 weeks carrying the MINIMUM provenance an evaluable week really has.

        Four per-ETF dividend sidecar digests — they exist per ETF and cannot be
        merged — plus the settlement/state/NAV digests the record already brings.
        This is the shape real data has, and it is the shape that used to be
        impossible to summarise.
        """

        import copy

        rows = []
        for row in _weekly_rows():
            row = copy.deepcopy(row)
            week = row["calendar_week_index"]
            sidecars = [f"{9000 + week * 10 + i:064x}" for i in range(4)]
            for index, symbol in enumerate(("VTI", "IWB", "SPY", "QQQ")):
                row["benchmarks"][symbol]["dividend_sidecar_sha256"] = sidecars[index]
                row["benchmarks"][symbol]["return_quality"] = "total_return_evaluable"
            row["source_refs"] = list(dict.fromkeys(row["source_refs"] + sidecars))
            rows.append(row)
        return rows

    def test_a_full_26_week_window_is_reachable_with_real_provenance(self) -> None:
        """The window this module exists to produce, on the provenance real weeks carry.

        Flat-rolling every week's digests into one root list hit its own 256
        ceiling around week 24, so the 26-week attribution report — the module's
        only purpose — could not be built from honest data. Provenance is layered
        now: one pointer per week at the root, each week complete in itself.
        """

        rows = self._fat_rows()
        self.assertEqual(26, len(rows))
        packet = build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week=self._cash(rows),
        )
        report = build_attribution_report(packet)

        self.assertEqual(26, len(report["weeks"]))
        self.assertEqual("evaluable", report["status"])
        self.assertEqual(26, len(report["source_refs"]), "the root carries one pointer per week")
        for index, week in enumerate(report["weeks"]):
            with self.subTest(week=index + 1):
                self.assertGreaterEqual(
                    len(week["source_refs"]), 9, "each week keeps its own full provenance"
                )
                self.assertIn(
                    packet["weeks"][index]["strategy"]["weekly_record_sha256"],
                    report["source_refs"],
                    "the root must name every week it summarises",
                )

    def test_a_week_the_root_does_not_name_is_refused(self) -> None:
        """The layered binding, in reverse: the root may not omit a week it summarises."""

        rows = self._fat_rows()[:3]
        packet = build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week=self._cash(rows),
        )
        orphan = packet["weeks"][1]["strategy"]["weekly_record_sha256"]
        packet["source_refs"] = [ref for ref in packet["source_refs"] if ref != orphan]
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_input(packet)
        self.assertIn("not named by", str(ctx.exception))

    def test_one_cash_row_cannot_price_twenty_six_different_weeks(self) -> None:
        """Design 12.7 forbids a fixed cash rate; the PIT checks did not enforce it.

        Every earlier check asked "is this in the past?" and none asked "is this
        THIS week's rate?", so one December quote keyed to all 26 weeks became the
        whole cash leg of the exposure-matched benchmark.
        """

        rows = _weekly_rows()
        frozen = {}
        for row in rows:
            observation = dict(self._cash([row])[row["calendar_week_index"]])
            observation["effective_start_date"] = "20251201"
            observation["effective_end_date"] = "20251208"
            observation["as_of_date"] = "20251208"
            frozen[row["calendar_week_index"]] = observation

        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=frozen,
            )
        self.assertIn("does not cover this week", str(ctx.exception))

    def test_a_cash_period_long_enough_to_cover_everything_proves_nothing(self) -> None:
        rows = _weekly_rows()[:2]
        stretched = {}
        for row in rows:
            observation = dict(self._cash([row])[row["calendar_week_index"]])
            observation["effective_start_date"] = "20200101"
            stretched[row["calendar_week_index"]] = observation

        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=stretched,
            )
        self.assertIn("spans more than", str(ctx.exception))

    def test_a_target_exposure_must_name_the_decision_it_was_taken_at(self) -> None:
        """The same defect as the cash leg, one step further: it had no date at all.

        Only the caller's dictionary key tied a target exposure to week t, so the
        same observation could be keyed to every week and nothing would notice.
        """

        rows = _weekly_rows()[:3]
        misfiled = {
            row["calendar_week_index"]: dict(self._target([rows[0]])[rows[0]["calendar_week_index"]])
            for row in rows
        }
        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=misfiled,
                cash_return_by_week=self._cash(rows),
            )
        self.assertIn("does not match this week's decision date", str(ctx.exception))

    def test_an_evaluable_target_with_no_as_of_date_is_refused(self) -> None:
        """The schema allows null; only the engine can refuse an evaluable one.

        Sibling of the mismatch case above: that one covers a WRONG date, this one
        covers NO date, and the schema's `anyOf [date8, null]` lets the second
        through. Without this the "as_of_date is required" branch was dead
        letter — a target with no temporal identity at all still validated.
        """

        rows = _weekly_rows()[:2]
        undated = self._target(rows)
        for observation in undated.values():
            observation["as_of_date"] = None

        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=undated,
                cash_return_by_week=self._cash(rows),
            )
        self.assertIn("as_of_date is required", str(ctx.exception))

    def test_a_side_table_key_that_matches_no_week_is_refused(self) -> None:
        """A typo used to be indistinguishable from having no data at all."""

        rows = _weekly_rows()[:2]
        cash = self._cash(rows)
        cash[99] = cash[1]
        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=cash,
            )
        self.assertIn("keyed to weeks this packet does not contain", str(ctx.exception))

    def test_the_root_is_exactly_one_pointer_per_week(self) -> None:
        """One pointer per week was written in the schema description and enforced nowhere."""

        import copy

        rows = _weekly_rows()[:3]
        base = build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week=self._cash(rows),
        )

        with self.subTest("a dropped week leaves an orphan pointer"):
            packet = copy.deepcopy(base)
            packet["weeks"] = packet["weeks"][:2]
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_input(packet)
            self.assertIn("exactly one pointer per week", str(ctx.exception))

        with self.subTest("the root may not carry unrelated digests"):
            packet = copy.deepcopy(base)
            packet["source_refs"] = packet["source_refs"] + ["%064x" % 4242]
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_input(packet)
            self.assertIn("exactly one pointer per week", str(ctx.exception))

        with self.subTest("two weeks may not share one pointer"):
            packet = copy.deepcopy(base)
            shared = packet["weeks"][0]["strategy"]["weekly_record_sha256"]
            stale = packet["weeks"][1]["strategy"]["weekly_record_sha256"]
            packet["weeks"][1]["strategy"]["weekly_record_sha256"] = shared
            packet["weeks"][1]["source_refs"] = [
                shared if ref == stale else ref for ref in packet["weeks"][1]["source_refs"]
            ]
            packet["source_refs"] = [ref for ref in packet["source_refs"] if ref != stale]
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_input(packet)
            self.assertIn("distinct", str(ctx.exception))

    def test_a_report_week_must_carry_and_be_named_by_its_own_pointer(self) -> None:
        """Sharing any digest with the root was vacuous on the report side.

        Every week could carry week 1's digest and nothing else -- all per-week
        provenance gone, most root pointers naming nothing -- and the published
        artifact still passed its own fail-closed door.
        """

        import copy

        rows = _weekly_rows()[:3]
        report = build_attribution_report(
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=self._cash(rows),
            )
        )
        first = report["weeks"][0]["weekly_record_sha256"]
        flattened = copy.deepcopy(report)
        for week in flattened["weeks"]:
            week["source_refs"] = [first]
            week["target_exposure_source_refs"] = [first]
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_report(flattened)
        # Deliberately the exact phrase: "source_refs" alone is also a substring of
        # "target_exposure_source_refs", so the looser assertion was satisfied by a
        # different guard entirely.
        self.assertIn("must contain its own weekly_record_sha256", str(ctx.exception))

    def test_a_month_of_accrual_cannot_be_reported_as_one_week(self) -> None:
        """The span bound has to be calibrated, not merely present.

        At 31 days a full month's accrual sat in the weekly slot and inflated the
        cash leg 4.4x -- the check permitted exactly what its own comment said it
        was there to forbid.
        """

        rows = _weekly_rows()[:2]
        stretched = {}
        for row in rows:
            observation = dict(self._cash([row])[row["calendar_week_index"]])
            valuation = datetime.strptime(observation["effective_end_date"], "%Y%m%d")
            observation["effective_start_date"] = (
                valuation - timedelta(days=_MAX_CASH_EFFECTIVE_DAYS + 1)
            ).strftime("%Y%m%d")
            stretched[row["calendar_week_index"]] = observation

        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=stretched,
            )
        self.assertIn("spans more than", str(ctx.exception))

    def test_one_vti_observation_cannot_price_two_weeks(self) -> None:
        """Same class as the cash leg, on the leg first argued to be safe."""

        import copy

        rows = _weekly_rows()[:3]
        packet = build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week=self._cash(rows),
        )
        copied = copy.deepcopy(packet)
        for week in copied["weeks"][1:]:
            week["vti"] = copy.deepcopy(copied["weeks"][0]["vti"])
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_input(copied)
        self.assertIn("cannot price two weeks", str(ctx.exception))

    def test_an_irreproducible_decision_time_degrades_the_week_not_the_packet(self) -> None:
        """Design 12.7 lists it with the other three missing inputs, which all degrade."""

        import copy

        rows = _weekly_rows()[:3]
        packet = build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week=self._cash(rows),
        )
        degraded = copy.deepcopy(packet)
        degraded["weeks"][1]["decision_time_reproducible"] = False
        report = build_attribution_report(degraded)

        self.assertEqual(3, len(report["weeks"]), "the packet must not be rejected outright")
        self.assertEqual("unavailable", report["weeks"][1]["status"])
        self.assertIn("decision_time_not_reproducible", report["weeks"][1]["unavailable_reasons"])
        self.assertEqual("unavailable", report["status"])
        self.assertIsNone(report["summary"]["raw_excess"])

    def test_a_side_table_key_shaped_like_a_typo_is_refused(self) -> None:
        """The guard accepted the very shapes the lookup then silently discards."""

        rows = _weekly_rows()[:2]
        for bad_key in ("01", " 1", 1.5):
            with self.subTest(bad_key):
                cash = self._cash(rows)
                cash[bad_key] = cash[1]
                with self.assertRaises(AttributionError) as ctx:
                    build_attribution_input(
                        rows,
                        attribution_epoch="us_short_market_diagnostic_attribution_v1",
                        target_exposure_by_week=self._target(rows),
                        cash_return_by_week=cash,
                    )
                self.assertIn("keyed to weeks this packet does not contain", str(ctx.exception))

    def _base_packet(self, weeks: int = 3) -> dict:
        rows = _weekly_rows()[:weeks]
        return build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week=self._cash(rows),
        )

    def test_the_cash_span_bound_is_calibrated_in_both_directions(self) -> None:
        """A bound tested only from above passes at any threshold; this pins it exactly."""

        rows = _weekly_rows()[:2]
        for offset, should_pass in ((_MAX_CASH_EFFECTIVE_DAYS, True),
                                    (_MAX_CASH_EFFECTIVE_DAYS + 1, False)):
            with self.subTest(days=offset):
                observations = {}
                for row in rows:
                    observation = dict(self._cash([row])[row["calendar_week_index"]])
                    end = datetime.strptime(observation["effective_end_date"], "%Y%m%d")
                    observation["effective_start_date"] = (
                        end - timedelta(days=offset)
                    ).strftime("%Y%m%d")
                    observations[row["calendar_week_index"]] = observation
                call = lambda: build_attribution_input(
                    rows,
                    attribution_epoch="us_short_market_diagnostic_attribution_v1",
                    target_exposure_by_week=self._target(rows),
                    cash_return_by_week=observations,
                )
                if should_pass:
                    self.assertEqual(2, len(call()["weeks"]))
                else:
                    with self.assertRaises(AttributionError):
                        call()

    def test_cash_dated_after_the_valuation_date_is_still_refused(self) -> None:
        """The sibling of the cover check: together they force end == valuation exactly."""

        rows = _weekly_rows()[:2]
        ahead = {}
        for row in rows:
            observation = dict(self._cash([row])[row["calendar_week_index"]])
            end = datetime.strptime(observation["effective_end_date"], "%Y%m%d")
            observation["effective_end_date"] = (end + timedelta(days=1)).strftime("%Y%m%d")
            ahead[row["calendar_week_index"]] = observation
        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=ahead,
            )
        self.assertIn("after the valuation date", str(ctx.exception))

    def test_a_week_that_omits_its_own_pointer_is_refused(self) -> None:
        """The other half of the layered binding: the week must carry what the root names."""

        import copy

        packet = copy.deepcopy(self._base_packet())
        pointer = packet["weeks"][1]["strategy"]["weekly_record_sha256"]
        packet["weeks"][1]["source_refs"] = [
            ref for ref in packet["weeks"][1]["source_refs"] if ref != pointer
        ]
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_input(packet)
        self.assertIn("its own weekly_record_sha256", str(ctx.exception))

    def test_the_report_root_is_exactly_one_pointer_per_week(self) -> None:
        """Same invariant as the input side, on the artifact that actually gets published."""

        import copy

        report = build_attribution_report(self._base_packet())
        with self.subTest("orphan pointer"):
            broken = copy.deepcopy(report)
            broken["weeks"] = broken["weeks"][:2]
            broken["summary"]["calendar_weeks"] = 2
            broken["summary"]["evaluable_weeks"] = 2
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_report(broken)
            self.assertIn("exactly one pointer per week", str(ctx.exception))
        with self.subTest("unrelated digest at the root"):
            broken = copy.deepcopy(report)
            broken["source_refs"] = broken["source_refs"] + ["%064x" % 777]
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_report(broken)
            self.assertIn("exactly one pointer per week", str(ctx.exception))

    def test_out_of_range_requested_exposure_components_are_refused(self) -> None:
        """The components are bounded, or `requested = carried + new` bounds nothing."""

        report = build_attribution_report(self._base_packet())
        week = report["weeks"][0]
        week["constraint_exposures"]["carried_holdings_exposure"] = 5.0
        week["constraint_exposures"]["new_order_exposure"] = -4.4
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_report(report)
        self.assertIn("out-of-range", str(ctx.exception))

    def test_the_report_g_star_must_be_the_minimum_even_when_the_components_agree(self) -> None:
        """The g* re-derivation, isolated from the component-sum check that now shadows it."""

        report = build_attribution_report(self._base_packet())
        week = report["weeks"][0]
        week["g_star"] = 0.42
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_report(report)
        self.assertIn("rule-implied minimum", str(ctx.exception))

    def test_the_report_long_only_cap_must_equal_one(self) -> None:
        """A long-only ceiling below 1 would silently redefine the whole exposure ladder."""

        report = build_attribution_report(self._base_packet())
        week = report["weeks"][0]
        week["constraint_exposures"]["long_only_cap"] = 0.5
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_report(report)
        self.assertIn("long_only_cap", str(ctx.exception))

    def test_both_roots_stay_capped_at_one_pointer_per_week(self) -> None:
        """Restoring the 256 ceiling is how the unreachable-window defect comes back."""

        import json

        for name in (
            "us_short_market_diagnostic_attribution_input.schema.json",
            "us_short_market_diagnostic_attribution_report.schema.json",
        ):
            with self.subTest(name):
                schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
                self.assertEqual(
                    26, schema["properties"]["source_refs"]["maxItems"],
                    "the root is one pointer per week; a bigger cap means it is rolling up again",
                )
                self.assertEqual(26, schema["properties"]["weeks"]["maxItems"])

    def test_the_report_says_its_exposures_are_producer_asserted(self) -> None:
        """The artifact must not claim more than it can prove.

        Three separate texts used to state the laundering was closed while the
        split-across-components form still validated at the same fivefold shrink.
        A reader of the schema is the person least able to check, so the schema is
        where the caveat has to live.
        """

        import json

        schema = json.loads(
            (ROOT / "schemas" / "us_short_market_diagnostic_attribution_report.schema.json")
            .read_text(encoding="utf-8")
        )
        description = schema["definitions"]["constraint_exposures"]["description"]
        self.assertIn("PRODUCER-ASSERTED", description)
        self.assertIn("still validates", description)

        report = build_attribution_report(self._base_packet())
        self.assertIn("target_exposure_source_refs", report["weeks"][0])
        self.assertTrue(
            report["weeks"][0]["target_exposure_source_refs"],
            "an exposure published with no provenance of its own cannot be checked by anyone",
        )

    def test_split_components_still_launder_and_that_is_recorded_not_hidden(self) -> None:
        """The live hole, asserted as live so nobody re-closes it in prose.

        If a future change makes this refuse, that is good news — and this test
        failing is how we find out, rather than discovering it years later from a
        register entry that was optimistic.
        """

        import copy

        report = build_attribution_report(self._base_packet())
        honest = report["weeks"][0]["exposure_effect"]

        laundered = copy.deepcopy(report)
        week = laundered["weeks"][0]
        week["constraint_exposures"].update(
            {
                "carried_holdings_exposure": 0.5,
                "new_order_exposure": 0.4,
                "requested_exposure": 0.9,
                "cash_capacity_exposure": 1.0,
                "environment_position_cap": 1.0,
                "long_only_cap": 1.0,
            }
        )
        week["requested_exposure"] = 0.9
        week["g_star"] = 0.9
        week["binding_constraints"] = ["requested_exposure"]
        week["matched_target_return"] = (
            0.9 * week["vti_total_return"] + 0.1 * week["cash_weekly_return"]
        )
        week["exposure_effect"] = week["matched_target_return"] - week["vti_total_return"]
        week["active_system_effect"] = (
            week["strategy_weekly_return"] - week["matched_target_return"]
        )
        week["identity_residual"] = 0.0
        week["raw_excess"] = week["strategy_weekly_return"] - week["vti_total_return"]

        rows = laundered["weeks"]
        def compound(key):
            wealth = 1.0
            for row in rows:
                wealth *= 1.0 + float(row[key])
            return wealth - 1.0

        strategy_cumulative = compound("strategy_weekly_return")
        vti_cumulative = compound("vti_total_return")
        target_cumulative = compound("matched_target_return")
        laundered["summary"].update(
            {
                "strategy_cumulative_return": strategy_cumulative,
                "vti_cumulative_return": vti_cumulative,
                "matched_target_cumulative_return": target_cumulative,
                "raw_excess": strategy_cumulative - vti_cumulative,
                "exposure_effect": target_cumulative - vti_cumulative,
                "active_system_effect": strategy_cumulative - target_cumulative,
                "identity_residual": 0.0,
                "weekly_identity_max_abs_residual": 0.0,
            }
        )

        validate_attribution_report(laundered)  # accepted today, by design
        self.assertNotAlmostEqual(honest, laundered["weeks"][0]["exposure_effect"], places=6)

    def test_a_price_only_vti_week_is_refused_on_each_half_independently(self) -> None:
        """Section 16 acceptance 3 is an AND, and the old fixture set both halves.

        `_weekly_rows(price_only=True)` sets `return_quality` to price-only AND
        clears the sidecar digest, so deleting either branch of the builder's
        evaluability test left the other one still refusing. Each half needs a
        fixture that moves only it.
        """

        import copy

        with self.subTest("evaluable VTI with no sidecar digest"):
            packet = copy.deepcopy(self._base_packet(2))
            packet["weeks"][0]["vti"]["sidecar_observation_sha256"] = None
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_input(packet)
            # Not just "sidecar": the containment guard below says that word too,
            # and a missing digest falls into it, so this half could be deleted
            # with nothing red unless the message is pinned to THIS guard.
            self.assertIn("total-return sidecar", str(ctx.exception))

        with self.subTest("evaluable VTI with the wrong return quality"):
            packet = copy.deepcopy(self._base_packet(2))
            packet["weeks"][0]["vti"]["return_quality"] = "unavailable"
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_input(packet)
            self.assertIn("total-return sidecar", str(ctx.exception))

        with self.subTest("a price-only week never becomes evaluable in the builder"):
            price_only = build_attribution_input(
                _weekly_rows(price_only=True)[:2],
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
            )
            self.assertEqual("unavailable", price_only["weeks"][0]["vti"]["status"])

    def test_a_cash_number_that_is_not_a_weekly_yield_is_refused(self) -> None:
        """The day bound checks the label; this checks the number.

        A legal seven-day period carrying a month's accrual — or an annualised
        rate mistaken for a weekly one — used to pass every date check and invert
        the sign of the published exposure effect.
        """

        rows = _weekly_rows()[:2]
        for label, value in (("a month of accrual", 0.0031), ("an annual rate", 0.045)):
            with self.subTest(label):
                inflated = {}
                for row in rows:
                    observation = dict(self._cash([row])[row["calendar_week_index"]])
                    observation["weekly_return"] = value
                    inflated[row["calendar_week_index"]] = observation
                with self.assertRaises(AttributionError) as ctx:
                    build_attribution_input(
                        rows,
                        attribution_epoch="us_short_market_diagnostic_attribution_v1",
                        target_exposure_by_week=self._target(rows),
                        cash_return_by_week=inflated,
                    )
                self.assertIn("annualises to", str(ctx.exception))

    def test_an_honest_week_with_settlement_lag_drift_is_not_refused(self) -> None:
        """The day bound must not reject weeks the lifecycle contract permits.

        Only `decision_date` is pinned to exactly seven days; `valuation_date` has
        no cadence rule, so ordinary lag drift makes a real gap of eleven or more.
        A bound of ten turned that into an unavailable report.
        """

        rows = _weekly_rows()[:2]
        widened = {}
        for row in rows:
            observation = dict(self._cash([row])[row["calendar_week_index"]])
            end = datetime.strptime(observation["effective_end_date"], "%Y%m%d")
            observation["effective_start_date"] = (end - timedelta(days=14)).strftime("%Y%m%d")
            observation["weekly_return"] = 0.0002
            widened[row["calendar_week_index"]] = observation
        packet = build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week=widened,
        )
        self.assertEqual("evaluable", packet["weeks"][0]["cash_return"]["status"])

    def test_the_builder_can_report_an_irreproducible_decision_time(self) -> None:
        """De-const-ing the schema was half the fix; the only producer still could not say it."""

        rows = _weekly_rows()[:3]
        packet = build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week=self._cash(rows),
            decision_time_reproducible_by_week={2: False},
        )
        self.assertTrue(packet["weeks"][0]["decision_time_reproducible"])
        self.assertFalse(packet["weeks"][1]["decision_time_reproducible"])

        report = build_attribution_report(packet)
        self.assertEqual("unavailable", report["weeks"][1]["status"])
        self.assertIn("decision_time_not_reproducible", report["weeks"][1]["unavailable_reasons"])

        with self.assertRaises(AttributionError):
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=self._cash(rows),
                decision_time_reproducible_by_week={99: False},
            )

    def test_every_observation_is_bound_into_its_own_week_provenance(self) -> None:
        """The single check that ties VTI, cash and target into the week — and it had none."""

        import copy

        packet = copy.deepcopy(self._base_packet())
        stray = packet["weeks"][0]["cash_return"]["source_refs"][0]
        packet["weeks"][0]["source_refs"] = [
            ref for ref in packet["weeks"][0]["source_refs"] if ref != stray
        ]
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_input(packet)
        self.assertIn("do not cover all nested observations", str(ctx.exception))

    def test_a_cash_period_that_is_not_ordered_is_refused(self) -> None:
        rows = _weekly_rows()[:2]
        reversed_period = {}
        for row in rows:
            observation = dict(self._cash([row])[row["calendar_week_index"]])
            observation["effective_start_date"] = observation["effective_end_date"]
            reversed_period[row["calendar_week_index"]] = observation
        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=reversed_period,
            )
        self.assertIn("must be ordered", str(ctx.exception))

    def test_the_cash_band_uses_the_period_the_report_consumes(self) -> None:
        """Annualise over what the report compounds, not over what the producer declares.

        The report compounds this number once per week. Dividing by the declared
        span let a producer buy headroom by widening the label: the identical
        month-of-accrual number that fails at seven days passed at twenty-one, and
        at the ceiling the published active-system effect changed sign.
        """

        rows = _weekly_rows()[:2]
        stretched = {}
        for row in rows:
            observation = dict(self._cash([row])[row["calendar_week_index"]])
            end_day = datetime.strptime(observation["effective_end_date"], "%Y%m%d")
            observation["effective_start_date"] = (end_day - timedelta(days=21)).strftime("%Y%m%d")
            observation["weekly_return"] = 0.0031  # a month of accrual, verbatim
            stretched[row["calendar_week_index"]] = observation

        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=stretched,
            )
        message = str(ctx.exception)
        self.assertIn("annualises to", message)
        self.assertIn("7-day", message, "the consumed week, not the declared span")

    def test_the_cash_band_and_span_bounds_are_pinned_to_their_values(self) -> None:
        """Bounds imported into their own fixtures pin the comparison, never the number.

        Both earlier span tests used the constant on both sides, so the cap passed
        at 8 and at 400 alike, and the floor had no test at all.
        """

        self.assertEqual(21, _MAX_CASH_EFFECTIVE_DAYS)
        self.assertEqual(0.10, _MAX_CASH_ANNUALISED)
        self.assertEqual(-0.01, _MIN_CASH_ANNUALISED)
        # Widening this one loosens the identity, both re-derivations, g* and
        # the component sum at once; section 12.7 permits machine precision only.
        self.assertEqual(1e-12, _TOLERANCE)

        rows = _weekly_rows()[:2]
        with self.subTest("a negative yield beyond the floor is refused"):
            negative = {}
            for row in rows:
                observation = dict(self._cash([row])[row["calendar_week_index"]])
                observation["weekly_return"] = -0.002  # -10.4%/yr
                negative[row["calendar_week_index"]] = observation
            with self.assertRaises(AttributionError) as ctx:
                build_attribution_input(
                    rows,
                    attribution_epoch="us_short_market_diagnostic_attribution_v1",
                    target_exposure_by_week=self._target(rows),
                    cash_return_by_week=negative,
                )
            self.assertIn("annualises to", str(ctx.exception))

        with self.subTest("a 60-day declared span is refused whatever the number"):
            wide = {}
            for row in rows:
                observation = dict(self._cash([row])[row["calendar_week_index"]])
                end_day = datetime.strptime(observation["effective_end_date"], "%Y%m%d")
                observation["effective_start_date"] = (
                    end_day - timedelta(days=60)
                ).strftime("%Y%m%d")
                wide[row["calendar_week_index"]] = observation
            with self.assertRaises(AttributionError) as ctx:
                build_attribution_input(
                    rows,
                    attribution_epoch="us_short_market_diagnostic_attribution_v1",
                    target_exposure_by_week=self._target(rows),
                    cash_return_by_week=wide,
                )
            self.assertIn("spans more than", str(ctx.exception))

    def test_published_target_provenance_must_resolve_inside_its_week(self) -> None:
        """Provenance that resolves to nothing invites a check the reader cannot make."""

        import copy

        report = build_attribution_report(self._base_packet())
        for label, mutate in (
            ("empty on an evaluable week", lambda w: w.__setitem__("target_exposure_source_refs", [])),
            ("an invented digest", lambda w: w.__setitem__(
                "target_exposure_source_refs", ["f" * 64])),
        ):
            with self.subTest(label):
                broken = copy.deepcopy(report)
                mutate(broken["weeks"][0])
                with self.assertRaises(AttributionError):
                    validate_attribution_report(broken)

        with self.subTest("another week's provenance"):
            broken = copy.deepcopy(report)
            broken["weeks"][0]["target_exposure_source_refs"] = list(
                broken["weeks"][1]["target_exposure_source_refs"]
            )
            with self.assertRaises(AttributionError):
                validate_attribution_report(broken)

    def test_the_reproducible_side_table_raises_the_public_api_error(self) -> None:
        """Design 12.7: public entries raise AttributionError, never a bare TypeError."""

        rows = _weekly_rows()[:2]
        for bad in ([], [1], {1}, "1", 42, False):
            with self.subTest(repr(bad)):
                with self.assertRaises(AttributionError):
                    build_attribution_input(
                        rows,
                        attribution_epoch="us_short_market_diagnostic_attribution_v1",
                        target_exposure_by_week=self._target(rows),
                        cash_return_by_week=self._cash(rows),
                        decision_time_reproducible_by_week=bad,
                    )

    def test_a_v1_legal_price_only_week_cannot_be_admitted_as_total_return(self) -> None:
        """Section 16 acceptance 3, on the conjunct wrongly claimed to be pinned upstream.

        The v1 contract forbids a sidecar only when the benchmark is NOT
        evaluable, so price-only + evaluable + a degradation reason + a PRESENT
        sidecar digest is v1-legal. Deleting the return-quality conjunct admits
        exactly that record as total-return evaluable.
        """

        import copy

        from engine.us_short_market_diagnostic import validate_weekly_record

        rows = copy.deepcopy(_weekly_rows()[:2])
        for row in rows:
            benchmark = row["benchmarks"]["VTI"]
            benchmark["return_quality"] = "price_return_diagnostic"
            benchmark["data_quality_reasons"] = ["dividend_sidecar_not_reconciled"]
        validate_weekly_record(rows[0])  # v1-legal, sidecar still present

        packet = build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week=self._cash(rows),
        )
        self.assertEqual("unavailable", packet["weeks"][0]["vti"]["status"])
        self.assertIsNone(packet["weeks"][0]["vti"]["sidecar_observation_sha256"])

    def test_the_v1_contract_pins_the_vti_total_return_and(self) -> None:
        """Two conjuncts of the builder's evaluability test live in another module.

        The builder cannot be shown to enforce them independently, because no
        v1-valid record can reach it with only one half moved. This pins the
        contract that makes that true, so relaxing it upstream fails here rather
        than silently letting a mislabelled price-only week into attribution.
        """

        import copy

        from engine.us_short_market_diagnostic import (
            MarketDiagnosticError,
            validate_weekly_record,
        )

        row = _weekly_rows()[0]
        with self.subTest("total return with no dividend sidecar"):
            mutated = copy.deepcopy(row)
            mutated["benchmarks"]["VTI"]["dividend_sidecar_sha256"] = None
            with self.assertRaises(MarketDiagnosticError) as ctx:
                validate_weekly_record(mutated)
            self.assertIn("dividend sidecar", str(ctx.exception))
        with self.subTest("price-only with no degradation reason"):
            mutated = copy.deepcopy(row)
            mutated["benchmarks"]["VTI"]["return_quality"] = "price_return_diagnostic"
            with self.assertRaises(MarketDiagnosticError) as ctx:
                validate_weekly_record(mutated)
            self.assertIn("degradation reason", str(ctx.exception))

    def _cash_with(self, rows, **overrides) -> dict:
        table = {}
        for row in rows:
            observation = dict(self._cash([row])[row["calendar_week_index"]])
            observation.update(overrides)
            table[row["calendar_week_index"]] = observation
        return table

    def _expect_refused(self, rows, *, cash=None, target=None, fragment=""):
        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=target or self._target(rows),
                cash_return_by_week=cash or self._cash(rows),
            )
        if fragment:
            self.assertIn(fragment, str(ctx.exception))

    def test_the_band_divisor_is_a_constant_no_producer_can_move(self) -> None:
        """Three attempts hung the band on a length the producer chose; this pins the fourth.

        First the declared effective span, then the gap between valuations — each
        time the same month-of-accrual number got through by widening the lever.
        The divisor is now the canonical week, and the packet must actually keep
        that cadence, so there is no lever left to widen. The fixture below moves
        the valuation gap away from seven precisely so this test can tell a
        constant apart from the interval it replaced.
        """

        import copy

        rows = copy.deepcopy(_weekly_rows()[:2])
        # Week 1 settles five days later than usual — a plain settlement lag the
        # lifecycle permits, because only decision_date is pinned. Under the old
        # divisor this widened week 2's band to 12 days and let 0.0031 through.
        shifted = datetime.strptime(rows[0]["valuation_date"], "%Y%m%d") - timedelta(days=5)
        rows[0]["valuation_date"] = shifted.strftime("%Y%m%d")
        for benchmark in rows[0]["benchmarks"].values():
            benchmark["price_date"] = rows[0]["valuation_date"]

        cash = self._cash(rows)
        cash[1]["effective_end_date"] = rows[0]["valuation_date"]
        cash[1]["as_of_date"] = rows[0]["valuation_date"]
        cash[1]["effective_start_date"] = (shifted - timedelta(days=7)).strftime("%Y%m%d")
        cash[2]["weekly_return"] = 0.0031  # the month of accrual, verbatim

        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=cash,
            )
        message = str(ctx.exception)
        self.assertIn("annualises to", message)
        self.assertIn("canonical 7-day week", message)

    def test_the_band_divisor_is_exactly_seven_not_six_or_eight(self) -> None:
        """One day either way is a real change in the threshold, so pin the value.

        0.0021 annualises to 10.95% over seven days -- refused -- but to 9.58%
        over eight and 12.78% over six. Only a value that straddles the band can
        tell one divisor from another.
        """

        rows = _weekly_rows()[:2]
        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=self._cash_with(rows, weekly_return=0.0021),
            )
        self.assertIn("annualises to 0.1095", str(ctx.exception))

        # And a value that is honest at seven days must still be accepted, so a
        # divisor moved the other way is caught too.
        packet = build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week=self._cash_with(rows, weekly_return=0.0019),
        )
        self.assertEqual("evaluable", packet["weeks"][0]["cash_return"]["status"])

    def test_valuation_dates_must_advance(self) -> None:
        """Ordering the whole window depends on; it had no reverse case of its own."""

        import copy

        rows = copy.deepcopy(_weekly_rows()[:2])
        rows[1]["valuation_date"] = rows[0]["valuation_date"]
        for benchmark in rows[1]["benchmarks"].values():
            benchmark["price_date"] = rows[1]["valuation_date"]
        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=self._cash(rows),
            )
        self.assertIn("valuation dates must be strictly increasing", str(ctx.exception))

    def test_the_packet_must_keep_the_canonical_decision_cadence(self) -> None:
        """The divisor is a constant, so the cadence it stands for has to be real.

        Stored records already satisfy this (the lifecycle enforces it); a
        hand-built packet did not have to, and would then have been priced as a
        week when it was not one.
        """

        import copy

        rows = copy.deepcopy(_weekly_rows()[:2])
        # Week indexes stay consecutive; only the calendar step doubles, so this
        # reaches the cadence rule rather than the ordering one.
        for field in ("decision_date", "valuation_date"):
            shifted = datetime.strptime(rows[1][field], "%Y%m%d") + timedelta(days=7)
            rows[1][field] = shifted.strftime("%Y%m%d")
        for benchmark in rows[1]["benchmarks"].values():
            benchmark["price_date"] = rows[1]["valuation_date"]
        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=self._cash(rows),
            )
        self.assertIn("exactly 7 days", str(ctx.exception))

    def test_a_side_table_value_that_is_not_an_object_raises_the_public_api_error(self) -> None:
        """A legal key with an illegal value escaped as a bare TypeError."""

        rows = _weekly_rows()[:2]
        cash = self._cash(rows)
        cash[1] = 42
        with self.assertRaises(AttributionError):
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=cash,
            )

    def test_one_week_spelled_two_ways_is_refused(self) -> None:
        """`{1: honest, "1": wrong}` used to pass and lose the second row in silence."""

        rows = _weekly_rows()[:2]
        base = self._cash(rows)
        wrong = dict(base[1])
        wrong["weekly_return"] = 0.09
        cash = {1: base[1], "1": wrong, 2: base[2]}
        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=cash,
            )
        self.assertIn("both name week 1", str(ctx.exception))

    def test_a_cash_observation_must_bind_the_document_it_names(self) -> None:
        """Section 16 acceptance 1 walks root -> week -> observation; the cash leg broke it."""

        rows = _weekly_rows()[:2]
        unbound = {}
        for row in rows:
            observation = dict(self._cash([row])[row["calendar_week_index"]])
            observation["source_sha256"] = "d" * 64
            unbound[row["calendar_week_index"]] = observation
        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=unbound,
            )
        self.assertIn("source_sha256 must appear", str(ctx.exception))

    def test_target_provenance_must_be_wholly_inside_the_week(self) -> None:
        """A subset rule relaxed to 'intersects' passes a real ref carrying a forged one."""

        import copy

        report = build_attribution_report(self._base_packet())
        broken = copy.deepcopy(report)
        week = broken["weeks"][0]
        week["target_exposure_source_refs"] = list(week["target_exposure_source_refs"]) + ["e" * 64]
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_report(broken)
        self.assertIn("does not carry", str(ctx.exception))

    def test_a_ref_with_sibling_keys_would_be_silently_inert(self) -> None:
        """Draft-07 ignores keys beside a $ref, so no schema node may rely on one."""

        import json

        for name in (
            "us_short_market_diagnostic_attribution_input.schema.json",
            "us_short_market_diagnostic_attribution_report.schema.json",
        ):
            schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
            offenders = []

            def walk(node, path):
                if isinstance(node, dict):
                    if "$ref" in node:
                        siblings = set(node) - {"$ref", "description"}
                        if siblings:
                            offenders.append(f"{path}: {sorted(siblings)}")
                    for key, value in node.items():
                        walk(value, f"{path}.{key}")
                elif isinstance(node, list):
                    for index, value in enumerate(node):
                        walk(value, f"{path}[{index}]")

            walk(schema, name)
            self.assertEqual([], offenders, "a constraint beside a $ref is silently ignored")

    def test_a_bool_side_table_key_is_refused(self) -> None:
        """`True` equals 1 in a dict lookup, so it silently resolves to week 1."""

        rows = _weekly_rows()[:2]
        base = self._cash(rows)
        # Built literally: `cash[True] = x` would OVERWRITE key 1, because
        # `hash(True) == hash(1)`. That collision is the whole hazard — a bool key
        # resolves to week 1 in the lookup while reading as a different key.
        cash = {True: base[1], 2: base[2]}
        self._expect_refused(rows, cash=cash, fragment="does not contain")

    def test_an_evaluable_vti_with_no_weekly_return_is_refused(self) -> None:
        """Otherwise a null return reaches the report and crashes it untyped."""

        import copy

        packet = copy.deepcopy(self._base_packet(2))
        packet["weeks"][0]["vti"]["weekly_return"] = None
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_input(packet)
        self.assertIn("total-return sidecar", str(ctx.exception))

    def test_cash_observed_after_the_valuation_date_is_refused(self) -> None:
        """Section 16's as-of leg, which had no reverse case of its own."""

        rows = _weekly_rows()[:2]
        late = {}
        for row in rows:
            observation = dict(self._cash([row])[row["calendar_week_index"]])
            end = datetime.strptime(observation["effective_end_date"], "%Y%m%d")
            observation["as_of_date"] = (end + timedelta(days=1)).strftime("%Y%m%d")
            late[row["calendar_week_index"]] = observation
        self._expect_refused(rows, cash=late, fragment="after the valuation date")

    def test_an_input_long_only_cap_below_one_is_refused(self) -> None:
        """The long-only ceiling defines the whole exposure ladder; it is not a free number."""

        rows = _weekly_rows()[:2]
        target = self._target(rows)
        for observation in target.values():
            observation["long_only_cap"] = 0.5
        self._expect_refused(rows, target=target, fragment="long-only ceiling")

    def test_report_scalar_ranges_and_binding_constraints_are_re_derived(self) -> None:
        """Three live report guards that had no reverse case between them."""

        import copy

        report = build_attribution_report(self._base_packet())
        cases = (
            ("g_star out of range", lambda w: w.__setitem__("g_star", 1.5), "outside [0, 1]"),
            (
                "requested exposure out of range",
                lambda w: w.__setitem__("requested_exposure", 3.0),
                "outside [0, 2]",
            ),
            (
                "binding constraints not re-derived",
                lambda w: w.__setitem__("binding_constraints", ["long_only_cap"]),
                "binding",
            ),
        )
        for label, mutate, fragment in cases:
            with self.subTest(label):
                broken = copy.deepcopy(report)
                mutate(broken["weeks"][0])
                with self.assertRaises(AttributionError) as ctx:
                    validate_attribution_report(broken)
                self.assertIn(fragment, str(ctx.exception))

    def test_the_report_schema_requires_the_target_provenance_field(self) -> None:
        """Code enforces it today; a schema that stops requiring it is how that erodes."""

        import json

        schema = json.loads(
            (ROOT / "schemas" / "us_short_market_diagnostic_attribution_report.schema.json")
            .read_text(encoding="utf-8")
        )
        self.assertIn(
            "target_exposure_source_refs", schema["definitions"]["week"]["required"]
        )

    def test_a_non_mapping_side_table_raises_the_public_api_error(self) -> None:
        """All three side tables, not just the two that had the check."""

        rows = _weekly_rows()[:2]
        for name in (
            "cash_return_by_week",
            "target_exposure_by_week",
            "decision_time_reproducible_by_week",
        ):
            for bad in ([], 42, "1"):
                with self.subTest(f"{name}={bad!r}"):
                    kwargs = {
                        "attribution_epoch": "us_short_market_diagnostic_attribution_v1",
                        "target_exposure_by_week": self._target(rows),
                        "cash_return_by_week": self._cash(rows),
                    }
                    kwargs[name] = bad
                    with self.assertRaises(AttributionError):
                        build_attribution_input(rows, **kwargs)

    def test_the_report_gate_carries_the_same_rules_as_the_input_gate(self) -> None:
        """A rule that lives only on the input side is absent exactly when it is needed.

        `validate_attribution_report` is the only independent check a report gets
        once it has been persisted, passed between processes, or hand-edited. Two
        rules were missing here: twenty-six consecutive DAYS published as a
        twenty-six WEEK verdict, and an annual rate in the weekly cash slot flipped
        the sign of both headline effects.
        """

        import copy

        report = build_attribution_report(self._base_packet())

        with self.subTest("consecutive days are not consecutive weeks"):
            daily = copy.deepcopy(report)
            base = datetime.strptime(daily["weeks"][0]["decision_date"], "%Y%m%d")
            for offset, week in enumerate(daily["weeks"]):
                week["decision_date"] = (base + timedelta(days=offset)).strftime("%Y%m%d")
                week["valuation_date"] = (base + timedelta(days=offset - 1)).strftime("%Y%m%d")
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_report(daily)
            self.assertIn("exactly 7 days", str(ctx.exception))

        with self.subTest("an annual rate in the weekly cash slot"):
            inflated = copy.deepcopy(report)
            week = inflated["weeks"][0]
            week["cash_weekly_return"] = 0.045
            week["matched_target_return"] = (
                week["g_star"] * week["vti_total_return"]
                + (1.0 - week["g_star"]) * week["cash_weekly_return"]
            )
            week["exposure_effect"] = week["matched_target_return"] - week["vti_total_return"]
            week["active_system_effect"] = (
                week["strategy_weekly_return"] - week["matched_target_return"]
            )
            week["identity_residual"] = 0.0
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_report(inflated)
            self.assertIn("annualises to", str(ctx.exception))

    def test_the_cadence_rule_is_pinned_on_both_sides(self) -> None:
        """Only the long side was tested, so relaxing it to `> 7` reddened nothing.

        Under that relaxation twenty-six records sitting on twenty-six consecutive
        days all enter the packet, each week's cash priced over seven days and
        compounded weekly.
        """

        import copy

        for label, delta in (("a doubled step", 7), ("a single-day step", -6)):
            with self.subTest(label):
                rows = copy.deepcopy(_weekly_rows()[:2])
                for field in ("decision_date", "valuation_date"):
                    shifted = datetime.strptime(rows[1][field], "%Y%m%d") + timedelta(days=delta)
                    rows[1][field] = shifted.strftime("%Y%m%d")
                for benchmark in rows[1]["benchmarks"].values():
                    benchmark["price_date"] = rows[1]["valuation_date"]
                with self.assertRaises(AttributionError) as ctx:
                    build_attribution_input(
                        rows,
                        attribution_epoch="us_short_market_diagnostic_attribution_v1",
                        target_exposure_by_week=self._target(rows),
                        cash_return_by_week=self._cash(rows),
                    )
                self.assertIn("exactly 7 days", str(ctx.exception))

    def test_a_vti_observation_must_bind_the_sidecar_it_names(self) -> None:
        """The rule the cash leg carries, applied to the leg that lacked it."""

        import copy

        packet = copy.deepcopy(self._base_packet(2))
        packet["weeks"][0]["vti"]["source_refs"] = ["c" * 64]
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_input(packet)
        self.assertIn("sidecar_observation_sha256 must appear", str(ctx.exception))

    def test_the_report_orders_and_numbers_its_own_weeks(self) -> None:
        """Two live report guards that had no reverse case between them."""

        import copy

        report = build_attribution_report(self._base_packet())
        cases = (
            (
                "week indexes must be consecutive",
                lambda r: r["weeks"][1].__setitem__("calendar_week_index", 5),
                "consecutive",
            ),
            (
                "valuation dates must advance",
                lambda r: r["weeks"][1].__setitem__(
                    "valuation_date", r["weeks"][0]["valuation_date"]
                ),
                "valuation dates",
            ),
        )
        for label, mutate, fragment in cases:
            with self.subTest(label):
                broken = copy.deepcopy(report)
                mutate(broken)
                with self.assertRaises(AttributionError) as ctx:
                    validate_attribution_report(broken)
                self.assertIn(fragment, str(ctx.exception))

    def test_an_evaluable_vti_may_not_carry_degraded_or_empty_provenance(self) -> None:
        """A live guard with no coverage: evaluable and 'reasons' are exclusive."""

        import copy

        packet = copy.deepcopy(self._base_packet(2))
        packet["weeks"][0]["vti"]["data_quality_reasons"] = ["stale_sidecar"]
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_input(packet)
        self.assertIn("degraded or empty provenance", str(ctx.exception))

    def test_a_typo_key_with_no_int_twin_is_refused(self) -> None:
        """The shape rule, isolated from the duplicate-spelling rule that shadowed it.

        Every earlier fixture paired the typo with its int twin, so the
        two-spellings guard fired first and a relaxed shape rule went unnoticed.
        """

        rows = _weekly_rows()[:2]
        cash = self._cash(rows)
        cash["02"] = cash.pop(2)
        with self.assertRaises(AttributionError) as ctx:
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=cash,
            )
        self.assertIn("does not contain", str(ctx.exception))

    def test_the_input_schema_requires_the_target_as_of_date(self) -> None:
        """The report side has this pin; the input side did not."""

        import json

        schema = json.loads(
            (ROOT / "schemas" / "us_short_market_diagnostic_attribution_input.schema.json")
            .read_text(encoding="utf-8")
        )
        self.assertIn("as_of_date", schema["definitions"]["target_exposure"]["required"])

    def test_the_builder_vti_conjuncts_each_have_a_builder_path_case(self) -> None:
        """`price_only=True` moves two halves at once, so neither was pinned alone."""

        packet = build_attribution_input(
            _weekly_rows(price_only=True)[:2],
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
        )
        week = packet["weeks"][0]["vti"]
        self.assertEqual("unavailable", week["status"])
        self.assertIsNone(week["weekly_return"], "the weekly-return conjunct")
        self.assertIsNone(week["sidecar_observation_sha256"], "the sidecar conjunct")
        self.assertEqual([], week["source_refs"])
        self.assertIn("vti_total_return_not_available", week["data_quality_reasons"])

    def _report_with(self, mutate):
        import copy

        report = build_attribution_report(self._base_packet())
        broken = copy.deepcopy(report)
        mutate(broken)
        return broken

    def test_the_report_cash_band_is_calibrated_like_its_input_twin(self) -> None:
        """A ceiling tested only 23x above itself is not a ceiling.

        The report gate got the band last round with one fixture at 0.045, which
        annualises to 2.35 -- so the divisor, the day count, the floor and the
        ceiling could all be relaxed with nothing turning red. This uses the exact
        month-of-accrual number the input twin refuses.
        """

        with self.subTest("a month of accrual"):
            broken = self._report_with(
                lambda r: self._retune_cash(r["weeks"][0], 0.0031)
            )
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_report(broken)
            self.assertIn("annualises to 0.1616", str(ctx.exception))

        with self.subTest("a negative yield beyond the floor"):
            broken = self._report_with(
                lambda r: self._retune_cash(r["weeks"][0], -0.002)
            )
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_report(broken)
            self.assertIn("annualises to -0.1043", str(ctx.exception))

        with self.subTest("an honest yield is still accepted"):
            report = build_attribution_report(self._base_packet())
            validate_attribution_report(report)

    def _retune_cash(self, week, value):
        """Move the cash leg and recompute everything downstream honestly."""

        week["cash_weekly_return"] = value
        week["matched_target_return"] = (
            week["g_star"] * week["vti_total_return"] + (1.0 - week["g_star"]) * value
        )
        week["exposure_effect"] = week["matched_target_return"] - week["vti_total_return"]
        week["active_system_effect"] = (
            week["strategy_weekly_return"] - week["matched_target_return"]
        )
        week["identity_residual"] = 0.0

    def test_the_report_cadence_is_pinned_on_both_sides(self) -> None:
        """Only the short side was covered, so twenty-six fortnights still passed.

        Relaxing the report rule to `< 7` left every test green while a fifty-two
        week span published as a `26w-1-26` verdict.
        """

        import copy

        report = build_attribution_report(self._base_packet())
        for label, step in (("a fortnightly step", 14), ("a daily step", 1)):
            with self.subTest(label):
                broken = copy.deepcopy(report)
                base = datetime.strptime(broken["weeks"][0]["decision_date"], "%Y%m%d")
                for offset, week in enumerate(broken["weeks"]):
                    week["decision_date"] = (base + timedelta(days=offset * step)).strftime("%Y%m%d")
                    week["valuation_date"] = (
                        base + timedelta(days=offset * step - 1)
                    ).strftime("%Y%m%d")
                with self.assertRaises(AttributionError) as ctx:
                    validate_attribution_report(broken)
                self.assertIn("exactly 7 days", str(ctx.exception))

    def test_the_published_split_cannot_be_moved_between_the_two_effects(self) -> None:
        """The one thing that makes the headline numbers non-forgeable, finally tested.

        Shifting a fixed amount out of the exposure effect and into the active
        system effect keeps `raw = exposure + active` EXACTLY, so the identity
        check never fires — the re-derivation tolerance is the sole catcher, and
        it had no test at any tolerance. Section 12.7: the active-system effect
        must not be dressed up as anything else.
        """

        import copy

        report = build_attribution_report(self._base_packet())

        with self.subTest("per week"):
            broken = copy.deepcopy(report)
            week = broken["weeks"][0]
            week["exposure_effect"] += 0.02
            week["active_system_effect"] -= 0.02
            self.assertAlmostEqual(
                week["raw_excess"],
                week["exposure_effect"] + week["active_system_effect"],
                places=12,
                msg="the identity must still hold, or a different guard is the catcher",
            )
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_report(broken)
            self.assertIn("effect", str(ctx.exception))

        with self.subTest("in the summary"):
            broken = copy.deepcopy(report)
            broken["summary"]["exposure_effect"] += 0.02
            broken["summary"]["active_system_effect"] -= 0.02
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_report(broken)
            self.assertIn("summary", str(ctx.exception))

    def test_two_report_weeks_may_not_share_one_pointer(self) -> None:
        """The input twin has this subtest; the report twin had only two."""

        import copy

        report = build_attribution_report(self._base_packet())
        broken = copy.deepcopy(report)
        shared = broken["weeks"][0]["weekly_record_sha256"]
        stale = broken["weeks"][1]["weekly_record_sha256"]
        broken["weeks"][1]["weekly_record_sha256"] = shared
        broken["weeks"][1]["source_refs"] = [
            shared if ref == stale else ref for ref in broken["weeks"][1]["source_refs"]
        ]
        broken["source_refs"] = [ref for ref in broken["source_refs"] if ref != stale]
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_report(broken)
        self.assertIn("distinct", str(ctx.exception))

    def test_an_unavailable_report_row_may_not_carry_numbers(self) -> None:
        """Section 16 acceptance 5: a missing input is null, never zero or a leftover."""

        import copy

        report = build_attribution_report(self._base_packet())
        broken = copy.deepcopy(report)
        week = broken["weeks"][1]
        week["status"] = "unavailable"
        week["unavailable_reasons"] = ["pit_3m_tbill_not_available"]
        # Counts and summary made consistent with the new status, so the ONLY
        # thing left that can object is the rule under test: an unavailable row
        # still carrying its numbers.
        broken["status"] = "unavailable"
        broken["summary"]["evaluable_weeks"] -= 1
        broken["summary"]["unavailable_weeks"] += 1
        for field in (
            "strategy_cumulative_return",
            "vti_cumulative_return",
            "matched_target_cumulative_return",
            "raw_excess",
            "exposure_effect",
            "active_system_effect",
            "identity_residual",
            "weekly_identity_max_abs_residual",
        ):
            broken["summary"][field] = None
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_report(broken)
        self.assertIn("unavailable row carries a metric", str(ctx.exception))

    def test_a_non_boolean_reproducible_flag_is_refused(self) -> None:
        """A legal key with an illegal value; the sibling lookup has this case."""

        rows = _weekly_rows()[:2]
        with self.assertRaises(AttributionError):
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=self._cash(rows),
                decision_time_reproducible_by_week={1: "yes"},
            )

    def test_a_report_return_below_negative_one_is_refused(self) -> None:
        """The input gate floors returns at -1; a mixed report published +75pp without it."""

        import copy

        report = build_attribution_report(self._base_packet())
        for field in ("strategy_weekly_return", "vti_total_return", "cash_weekly_return"):
            with self.subTest(field):
                broken = copy.deepcopy(report)
                broken["weeks"][0][field] = -1.5
                with self.assertRaises(AttributionError) as ctx:
                    validate_attribution_report(broken)
                self.assertIn("greater than -1", str(ctx.exception))

    def _mixed_report(self) -> dict:
        """A report whose third week is genuinely unavailable, built the normal way."""

        rows = _weekly_rows()[:3]
        return build_attribution_report(
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=self._cash(rows, unavailable_week=3),
            )
        )

    def test_the_matched_target_return_cannot_be_moved_wholesale(self) -> None:
        """The third re-derivation guard, and the only one that pins the benchmark.

        Add a constant to `matched_target_return` and recompute BOTH effects from
        it. `raw = exposure + active` still holds exactly, so the identity guard
        is silent; the effect re-derivation reads the forged matched return and
        agrees with itself. Only re-deriving matched from g*, VTI and cash objects
        -- and without it the published split flips both signs.
        """

        import copy

        broken = copy.deepcopy(build_attribution_report(self._base_packet()))
        for week in broken["weeks"]:
            week["matched_target_return"] += 0.03
            week["exposure_effect"] = week["matched_target_return"] - week["vti_total_return"]
            week["active_system_effect"] = (
                week["strategy_weekly_return"] - week["matched_target_return"]
            )
            self.assertAlmostEqual(
                week["raw_excess"],
                week["exposure_effect"] + week["active_system_effect"],
                places=12,
                msg="the identity must still hold, or a different guard is the catcher",
            )
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_report(broken)
        self.assertIn("invalid matched target return", str(ctx.exception))

    def test_the_input_gate_bounds_every_target_exposure_component(self) -> None:
        """Its report twin had this test; the entry that BUILDS the numbers did not.

        Unbounded, `build_attribution_input` accepts a cash capacity of 1.5, a
        negative environment cap and a missing carried exposure, and
        `calculate_target_exposure` then escapes with a bare `TypeError` from
        `float(None)` -- an untyped error out of a public entry.
        """

        rows = _weekly_rows()[:2]
        for label, name, value in (
            ("above the ceiling", "cash_capacity_exposure", 1.5),
            ("below the floor", "environment_position_cap", -0.5),
            ("missing entirely", "carried_holdings_exposure", None),
        ):
            with self.subTest(label):
                targets = self._target(rows)
                for week in targets.values():
                    week[name] = value
                with self.assertRaises(AttributionError) as ctx:
                    build_attribution_input(
                        rows,
                        attribution_epoch="us_short_market_diagnostic_attribution_v1",
                        target_exposure_by_week=targets,
                        cash_return_by_week=self._cash(rows),
                    )
                self.assertIn("bounded target-exposure inputs", str(ctx.exception))

    def test_the_report_bounds_the_three_exposure_constraints(self) -> None:
        """Untested on BOTH gates: a cap outside [0, 1] that is not the minimum.

        Nothing downstream notices -- g* stays the cash capacity, the binding list
        is unchanged, the identity holds -- so this guard is the sole objection.
        """

        import copy

        broken = copy.deepcopy(build_attribution_report(self._base_packet()))
        broken["weeks"][0]["constraint_exposures"]["environment_position_cap"] = 1.5
        self.assertEqual(["cash_capacity_exposure"], broken["weeks"][0]["binding_constraints"])
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_report(broken)
        self.assertIn("invalid exposure constraint", str(ctx.exception))

    def test_an_evaluable_report_cannot_hide_an_unavailable_week(self) -> None:
        """Section 16 acceptance 5's core rule, until now shadowed by the count check.

        The counts are corrected, the missing row keeps its nulls, and the summary
        is the one compounded over exactly the two weeks that survived -- so a
        twenty-six week verdict published over a subset has no other objection.
        """

        import copy

        mixed = self._mixed_report()
        self.assertEqual("unavailable", mixed["status"])
        forged = copy.deepcopy(mixed)
        forged["status"] = "evaluable"
        forged["summary"] = copy.deepcopy(build_attribution_report(self._base_packet(2))["summary"])
        forged["summary"]["calendar_weeks"] = 3
        forged["summary"]["evaluable_weeks"] = 2
        forged["summary"]["unavailable_weeks"] = 1
        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_report(forged)
        self.assertIn("evaluable report cannot contain unavailable weeks", str(ctx.exception))

    def test_an_unavailable_row_may_not_carry_exposures_or_effects(self) -> None:
        """Each field the nulling rule covers, added back one at a time.

        The whole ten-field tuple was bound as a block, so the two published
        effects could be dropped from it; the two constraint guards beside it were
        reached by no fixture at all.
        """

        import copy

        mixed = self._mixed_report()
        cases = (
            ("exposure effect", lambda w: w.__setitem__("exposure_effect", 0.0), "carries a metric"),
            (
                "active system effect",
                lambda w: w.__setitem__("active_system_effect", 0.0),
                "carries a metric",
            ),
            (
                "constraint exposures",
                lambda w: w["constraint_exposures"].__setitem__("cash_capacity_exposure", 0.5),
                "carries exposure constraints",
            ),
            (
                "binding constraints",
                lambda w: w.__setitem__("binding_constraints", ["cash_capacity_exposure"]),
                "carries binding constraints",
            ),
        )
        for label, mutate, fragment in cases:
            with self.subTest(label):
                broken = copy.deepcopy(mixed)
                mutate(broken["weeks"][2])
                with self.assertRaises(AttributionError) as ctx:
                    validate_attribution_report(broken)
                self.assertIn(fragment, str(ctx.exception))

    def test_a_week_from_another_window_is_refused_on_both_gates(self) -> None:
        """Week 27 belongs to the next twenty-six, and neither gate had a case."""

        import copy

        with self.subTest("input"):
            packet = copy.deepcopy(self._base_packet())
            packet["weeks"][0]["calendar_week_index"] = 27
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_input(packet)
            self.assertIn("does not belong to window_id", str(ctx.exception))

        with self.subTest("report"):
            broken = copy.deepcopy(build_attribution_report(self._base_packet()))
            broken["weeks"][0]["calendar_week_index"] = 27
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_report(broken)
            self.assertIn("does not belong to window_id", str(ctx.exception))

    def test_a_valuation_after_its_decision_is_refused_on_both_gates(self) -> None:
        """Pricing a week after the decision it prices is look-ahead; no gate had a case."""

        import copy

        def push(week: dict) -> None:
            week["valuation_date"] = (
                datetime.strptime(week["decision_date"], "%Y%m%d") + timedelta(days=1)
            ).strftime("%Y%m%d")

        with self.subTest("input"):
            packet = copy.deepcopy(self._base_packet())
            push(packet["weeks"][0])
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_input(packet)
            self.assertIn("cannot be after decision_date", str(ctx.exception))

        with self.subTest("report"):
            broken = copy.deepcopy(build_attribution_report(self._base_packet()))
            push(broken["weeks"][0])
            with self.assertRaises(AttributionError) as ctx:
                validate_attribution_report(broken)
            self.assertIn("cannot be after decision_date", str(ctx.exception))

    def test_historical_backfill_boundary_is_fail_closed(self) -> None:
        packet = self._packet()
        packet["boundary"]["historical_backfill_performed"] = True

        with self.assertRaises(AttributionError):
            build_attribution_report(packet)

    def test_the_code_boundary_and_the_schema_boundary_cannot_drift_apart(self) -> None:
        """What `_exact_boundary` actually guards, finally asserted.

        The schema already pins all ten flags by `const`, so deleting the Python
        check reddened nothing — which read as "it is redundant". It is not: the
        two have different sources, and this is the only thing that notices them
        disagreeing. Nothing tested that, so nothing tested `_exact_boundary`.
        """

        import json

        for schema_name in (
            "us_short_market_diagnostic_attribution_input.schema.json",
            "us_short_market_diagnostic_attribution_report.schema.json",
        ):
            with self.subTest(schema_name):
                schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
                boundary = schema["definitions"]["boundary"]
                self.assertFalse(boundary["additionalProperties"])
                pinned = {name: prop["const"] for name, prop in boundary["properties"].items()}
                self.assertEqual(
                    ATTRIBUTION_BOUNDARY, pinned,
                    "the schema and the module disagree about the diagnostic boundary",
                )
                self.assertEqual(sorted(ATTRIBUTION_BOUNDARY), sorted(boundary["required"]))

    def test_report_source_binding_and_status_counts_are_fail_closed(self) -> None:
        report = build_attribution_report(self._packet())
        report["source_refs"] = report["source_refs"][1:]
        with self.assertRaises(AttributionError):
            validate_attribution_report(report)

        report = build_attribution_report(self._packet())
        report["summary"]["unavailable_weeks"] = 1
        with self.assertRaises(AttributionError):
            validate_attribution_report(report)

    def test_a_self_inconsistent_report_week_is_refused(self) -> None:
        report = build_attribution_report(self._packet())
        week = report["weeks"][0]
        week["g_star"] = 0.9
        week["requested_exposure"] = 0.1
        week["constraint_exposures"]["requested_exposure"] = 0.1
        week["binding_constraints"] = ["requested_exposure"]
        week["matched_target_return"] = (
            week["g_star"] * week["vti_total_return"]
            + (1.0 - week["g_star"]) * week["cash_weekly_return"]
        )
        week["raw_excess"] = week["strategy_weekly_return"] - week["vti_total_return"]
        week["exposure_effect"] = week["matched_target_return"] - week["vti_total_return"]
        week["active_system_effect"] = week["strategy_weekly_return"] - week["matched_target_return"]
        week["identity_residual"] = 0.0

        with self.assertRaises(AttributionError):
            validate_attribution_report(report)

    def test_requested_exposure_must_equal_its_two_declared_components(self) -> None:
        """Arithmetic consistency only — and the test name says only that on purpose.

        This does NOT prove a filled position cannot be laundered into a target:
        splitting the realised 0.9 into carried 0.5 + new 0.4 passes this check and
        still shrinks the published exposure effect fivefold. Design 12.7 forbids
        this module from reading fills, so the binding belongs to the
        target-exposure producer; see the register. Naming this test after the
        stronger property is how the next reader concludes a live hole is closed.
        """

        report = build_attribution_report(self._packet())
        week = report["weeks"][0]
        week["requested_exposure"] = 0.9
        week["constraint_exposures"].update(
            {
                "requested_exposure": 0.9,
                "cash_capacity_exposure": 1.0,
                "environment_position_cap": 1.0,
                "long_only_cap": 1.0,
            }
        )
        week["g_star"] = 0.9
        week["binding_constraints"] = ["requested_exposure"]
        week["matched_target_return"] = (
            0.9 * week["vti_total_return"] + 0.1 * week["cash_weekly_return"]
        )
        week["exposure_effect"] = week["matched_target_return"] - week["vti_total_return"]
        week["active_system_effect"] = (
            week["strategy_weekly_return"] - week["matched_target_return"]
        )
        week["identity_residual"] = 0.0

        with self.assertRaises(AttributionError) as ctx:
            validate_attribution_report(report)
        self.assertIn("carried", str(ctx.exception))

    def test_the_report_carries_the_inputs_of_every_value_it_claims_to_re_derive(self) -> None:
        """The structural rule behind that fix, so the next re-derived value cannot arrive naked."""

        report = build_attribution_report(self._packet())
        constraints = report["weeks"][0]["constraint_exposures"]
        for name in (
            "requested_exposure",
            "carried_holdings_exposure",
            "new_order_exposure",
            "cash_capacity_exposure",
            "environment_position_cap",
            "long_only_cap",
        ):
            self.assertIn(name, constraints)
        self.assertAlmostEqual(
            constraints["carried_holdings_exposure"] + constraints["new_order_exposure"],
            constraints["requested_exposure"],
            places=12,
        )

    def test_as_of_date_blocks_future_input_report_and_cash_availability(self) -> None:
        rows = _weekly_rows()[:2]
        cash = self._cash(rows)
        with self.assertRaises(AttributionError):
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=cash,
                as_of_date="20260101",
            )

        packet = self._packet()
        with self.assertRaises(AttributionError):
            validate_attribution_input(packet, as_of_date="20260101")

        report = build_attribution_report(packet)
        with self.assertRaises(AttributionError):
            validate_attribution_report(report, as_of_date="20260101")

    def test_public_apis_normalize_untyped_input_failures(self) -> None:
        target = self._target(_weekly_rows()[:1])[1]
        target["cash_capacity_exposure"] = 10**10000
        with self.assertRaises(AttributionError):
            calculate_target_exposure(target)

        rows = _weekly_rows()[:2]
        cash = self._cash(rows)
        cash[1]["available_at"] = None
        with self.assertRaises(AttributionError):
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=self._target(rows),
                cash_return_by_week=cash,
            )

        with self.assertRaises(AttributionError):
            build_attribution_input(
                rows,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
                target_exposure_by_week=[],
                cash_return_by_week=self._cash(rows),
            )

        malformed = _weekly_rows()[:2]
        malformed[0]["calendar_week_index"] = "1"
        with self.assertRaises(AttributionError):
            build_attribution_input(
                malformed,
                attribution_epoch="us_short_market_diagnostic_attribution_v1",
            )

        packet = self._packet()
        for week in packet["weeks"]:
            week["strategy"]["weekly_return"] = 1e308
        with self.assertRaises(AttributionError):
            build_attribution_report(packet)

    def test_report_summary_and_evaluable_reason_invariants_are_fail_closed(self) -> None:
        report = build_attribution_report(self._packet())
        report["summary"]["calendar_weeks"] = 1
        with self.assertRaises(AttributionError):
            validate_attribution_report(report)

        report = build_attribution_report(self._packet())
        report["weeks"][0]["unavailable_reasons"] = ["should_be_empty"]
        with self.assertRaises(AttributionError):
            validate_attribution_report(report)


if __name__ == "__main__":
    unittest.main()
