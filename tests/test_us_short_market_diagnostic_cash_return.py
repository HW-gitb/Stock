from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from engine.us_short_market_diagnostic_attribution import (
    build_attribution_input,
    build_attribution_report,
)
from engine.us_short_market_diagnostic_cash_return import (
    CAPTURE_SCHEMA_NAME,
    CAPTURE_SCHEMA_VERSION,
    FETCH_FAILED,
    FETCH_OK,
    MISSING_VALUE,
    REASON_FETCH_FAILED,
    REASON_NO_PUBLISHED_RATE,
    SERIES_ID,
    VENDOR,
    CashReturnError,
    build_cash_observation,
    validate_cash_capture,
)
from runners import us_short_market_diagnostic_cash_fetch as cash
from tests.test_us_short_market_diagnostic import _weekly_rows

DIGEST = f"{909:064x}"
VALUATION = "20260724"
DECISION = "20260727"
AS_OF = "20260806"


def _observation(day: str, value: str, published: str | None) -> dict:
    return {"date": day, "value": value, "available_from": published}


def _capture(observations: list[dict] | None = None, *, status: str = FETCH_OK, **overrides) -> dict:
    capture = {
        "schema_name": CAPTURE_SCHEMA_NAME,
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "series_id": SERIES_ID,
        "vendor": VENDOR,
        "observed_at": "2026-08-06T12:00:00Z",
        "vintage_realtime_date": "2026-08-06",
        "observation_window_start": "2026-07-03",
        "observation_window_end": "2026-07-24",
        "fetch_status": status,
        "error_kind": None,
        "observations": (
            [
                _observation("20260723", "3.83", "2026-07-24"),
                _observation("20260724", "3.87", "2026-07-25"),
            ]
            if observations is None
            else observations
        ),
    }
    capture.update(overrides)
    return capture


def _build(capture=None, **overrides) -> dict:
    kwargs = dict(
        capture=_capture() if capture is None else capture,
        capture_sha256=DIGEST,
        valuation_date=VALUATION,
        decision_date=DECISION,
        as_of_date=AS_OF,
    )
    kwargs.update(overrides)
    return build_cash_observation(**kwargs)


class CashCaptureTest(unittest.TestCase):
    def test_an_ok_capture_without_its_vintage_pin_is_refused(self) -> None:
        """An unpinned read is a different measurement, not a sloppier one.

        FRED's DGS3MO view is revisable: probed on 2026-08-06, the 2026-06-19
        Juneteenth row did not exist in the 2026-06-22 vintage and exists as "."
        today. A week that divides by the days it thinks it had would silently
        recompute history, so a capture that cannot name its vintage is unusable.
        """

        with self.assertRaises(CashReturnError) as ctx:
            validate_cash_capture(_capture(vintage_realtime_date=None))
        self.assertIn("real-time date", str(ctx.exception))

    def test_a_pin_after_the_as_of_date_is_refused(self) -> None:
        with self.assertRaises(CashReturnError) as ctx:
            validate_cash_capture(_capture(vintage_realtime_date="2026-09-01"), as_of_date=AS_OF)
        self.assertIn("after as_of_date", str(ctx.exception))

    def test_a_rate_without_a_publication_date_is_refused(self) -> None:
        """Without it the point-in-time choice below cannot be made at all."""

        with self.assertRaises(CashReturnError) as ctx:
            validate_cash_capture(_capture([_observation("20260724", "3.87", None)]))
        self.assertIn("no publication date", str(ctx.exception))

    def test_a_placeholder_may_not_claim_to_have_been_published(self) -> None:
        with self.assertRaises(CashReturnError) as ctx:
            validate_cash_capture(_capture([_observation("20260724", MISSING_VALUE, "2026-07-25")]))
        self.assertIn("cannot have been published", str(ctx.exception))

    def test_a_rate_published_before_the_day_it_measures_is_refused(self) -> None:
        with self.assertRaises(CashReturnError) as ctx:
            validate_cash_capture(_capture([_observation("20260724", "3.87", "2026-07-23")]))
        self.assertIn("before the day it measures", str(ctx.exception))

    def test_observations_must_be_ordered_and_distinct(self) -> None:
        for label, observations in (
            ("repeated", [_observation("20260724", "3.87", "2026-07-25")] * 2),
            (
                "backwards",
                [
                    _observation("20260724", "3.87", "2026-07-25"),
                    _observation("20260723", "3.83", "2026-07-24"),
                ],
            ),
        ):
            with self.subTest(label):
                with self.assertRaises(CashReturnError):
                    validate_cash_capture(_capture(observations))

    def test_a_failed_capture_may_not_carry_observations(self) -> None:
        with self.assertRaises(CashReturnError) as ctx:
            validate_cash_capture(_capture(status=FETCH_FAILED, vintage_realtime_date=None))
        self.assertIn("carries observations", str(ctx.exception))

    def test_a_wrong_series_is_refused(self) -> None:
        """DTB3 is a discount-basis rate and needs a different conversion."""

        with self.assertRaises(CashReturnError) as ctx:
            validate_cash_capture(_capture(series_id="DTB3"))
        self.assertIn("DGS3MO", str(ctx.exception))


class CashObservationTest(unittest.TestCase):
    def test_the_weekly_return_is_the_annual_rate_over_one_canonical_week(self) -> None:
        """Pinned to the number, not to the formula restated.

        3.87% a year over a seven-day week is 0.000742. Any drift in the day
        count or the divisor moves this, and the consumer annualises it straight
        back over the same seven days, so the two have to agree exactly.
        """

        observation = _build()
        self.assertAlmostEqual(0.00074219, observation["weekly_return"], places=8)
        self.assertAlmostEqual(0.0387, observation["weekly_return"] * 365 / 7, places=6)
        self.assertEqual("20260724", observation["as_of_date"])
        self.assertEqual("2026-07-25T23:59:59Z", observation["available_at"])

    def test_the_effective_period_ends_exactly_on_the_valuation_date(self) -> None:
        """The consumer's two containment checks leave no other legal value."""

        observation = _build()
        self.assertEqual(VALUATION, observation["effective_end_date"])
        self.assertEqual("20260717", observation["effective_start_date"])

    def test_a_holiday_placeholder_steps_back_and_never_becomes_zero(self) -> None:
        observation = _build(
            _capture(
                [
                    _observation("20260723", "3.83", "2026-07-24"),
                    _observation("20260724", MISSING_VALUE, None),
                ]
            )
        )
        self.assertEqual("evaluable", observation["status"])
        self.assertEqual("20260723", observation["as_of_date"])
        self.assertAlmostEqual(0.00073452, observation["weekly_return"], places=8)

    def test_a_rate_not_yet_published_at_decision_time_is_not_used(self) -> None:
        """Dated before the decision is not the same as available at the decision.

        This is stricter than the consumer's gate on purpose: the consumer can
        only judge the timestamp it is handed, and choosing which observation to
        hand it is this module's whole job.
        """

        observation = _build(
            _capture(
                [
                    _observation("20260723", "3.83", "2026-07-24"),
                    _observation("20260724", "3.87", "2026-07-28"),  # after the decision
                ]
            )
        )
        self.assertEqual("20260723", observation["as_of_date"])
        self.assertAlmostEqual(0.00073452, observation["weekly_return"], places=8)

    def test_a_rate_dated_after_the_week_it_would_price_is_not_used(self) -> None:
        """The capture gate only reaches back to as_of, which is weeks later.

        A capture taken on 2026-08-06 legitimately holds rates through 2026-08-05,
        and every one of them passes the capture's own look-ahead check. Only this
        bound stops the newest of them from pricing a week that ended on the 24th
        -- and the consumer would not degrade that week, it would refuse the whole
        packet, because cash dated after its valuation date is a hard error there.
        """

        observation = _build(
            _capture(
                [
                    _observation("20260723", "3.83", "2026-07-24"),
                    _observation("20260724", "3.87", "2026-07-25"),
                    # Dated after the week it would price, yet already published
                    # when the decision was made -- so the publication rule below
                    # lets it through and only the valuation bound stops it.
                    _observation("20260726", "3.90", "2026-07-27"),
                ]
            )
        )
        self.assertEqual("20260724", observation["as_of_date"])
        self.assertAlmostEqual(0.00074219, observation["weekly_return"], places=8)

    def test_a_rate_more_than_one_week_stale_is_refused(self) -> None:
        """The only bound that keeps a stale rate out, so it is pinned exactly.

        The published effective period is the canonical week by construction, so
        the consumer's "period may not span more than 21 days" check can never
        fire however old the rate is. Nothing downstream would notice a
        three-week-old rate presented as this week's.
        """

        for label, day, expected in (
            ("seven days back is still this week's", "20260717", "evaluable"),
            ("eight days back is not", "20260716", "unavailable"),
        ):
            with self.subTest(label):
                observation = _build(
                    _capture(
                        [_observation(day, "3.87", f"{day[:4]}-{day[4:6]}-{int(day[6:]) + 1:02d}")],
                        observation_window_start="2026-07-03",
                        observation_window_end=VALUATION,
                    )
                )
                self.assertEqual(expected, observation["status"])

    def test_an_empty_window_is_unavailable_and_says_why(self) -> None:
        for label, capture in (
            ("all placeholders", _capture([_observation("20260724", MISSING_VALUE, None)])),
            ("nothing at all", _capture([])),
            (
                "everything published too late",
                _capture([_observation("20260724", "3.87", "2026-07-30")]),
            ),
        ):
            with self.subTest(label):
                observation = _build(capture)
                self.assertEqual("unavailable", observation["status"])
                self.assertEqual([REASON_NO_PUBLISHED_RATE], observation["data_quality_reasons"])
                self.assertIsNone(observation["weekly_return"])

    def test_a_failed_fetch_is_unavailable_not_an_exception(self) -> None:
        observation = _build(_capture(status=FETCH_FAILED, vintage_realtime_date=None, observations=[]))
        self.assertEqual("unavailable", observation["status"])
        self.assertEqual([REASON_FETCH_FAILED], observation["data_quality_reasons"])

    def test_an_unavailable_observation_carries_nothing_at_all(self) -> None:
        """The consumer refuses an unavailable row that still holds a value."""

        observation = _build(_capture([]))
        for field in (
            "weekly_return",
            "effective_start_date",
            "effective_end_date",
            "as_of_date",
            "available_at",
            "source_sha256",
        ):
            with self.subTest(field):
                self.assertIsNone(observation[field])
        self.assertEqual([], observation["source_refs"])

    def test_a_rate_older_than_the_lookback_is_not_reached_for(self) -> None:
        """Three weeks stale is not this week's rate."""

        observation = _build(_capture([_observation("20260626", "3.87", "2026-06-29")]))
        self.assertEqual("unavailable", observation["status"])

    def test_the_digest_is_bound_into_the_walk(self) -> None:
        observation = _build()
        self.assertEqual(DIGEST, observation["source_sha256"])
        self.assertIn(DIGEST, observation["source_refs"])


class CashObservationConsumerGateTest(unittest.TestCase):
    """The acceptance criterion: the real v1.1 input gate accepts this."""

    def _target(self, rows) -> dict:
        return {
            row["calendar_week_index"]: {
                "status": "evaluable",
                "as_of_date": row["decision_date"],
                "carried_holdings_exposure": 0.2,
                "new_order_exposure": 0.4,
                "cash_capacity_exposure": 0.5,
                "environment_position_cap": 0.8,
                "long_only_cap": 1.0,
                "source_refs": [f"{600 + row['calendar_week_index']:064x}"],
                "data_quality_reasons": [],
            }
            for row in rows
        }

    def _cash_for(self, rows) -> dict:
        result = {}
        for row in rows:
            valuation = datetime.strptime(row["valuation_date"], "%Y%m%d").date()
            published = (valuation + __import__("datetime").timedelta(days=1)).strftime("%Y-%m-%d")
            digest = f"{(800 + row['calendar_week_index']):064x}"
            capture = _capture(
                [_observation(row["valuation_date"], "3.87", published)],
                observation_window_start=(
                    valuation - __import__("datetime").timedelta(days=21)
                ).strftime("%Y-%m-%d"),
                observation_window_end=valuation.strftime("%Y-%m-%d"),
            )
            result[row["calendar_week_index"]] = build_cash_observation(
                capture=capture,
                capture_sha256=digest,
                valuation_date=row["valuation_date"],
                decision_date=row["decision_date"],
                as_of_date=AS_OF,
            )
        return result

    def test_the_v1_1_input_gate_accepts_a_produced_cash_leg(self) -> None:
        rows = _weekly_rows()[:3]
        packet = build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week=self._cash_for(rows),
            as_of_date=AS_OF,
        )
        self.assertEqual(3, len(packet["weeks"]))
        for week in packet["weeks"]:
            self.assertEqual("evaluable", week["cash_return"]["status"])
            self.assertEqual("pit_3m_tbill", week["cash_return"]["instrument"])

    def test_an_unavailable_cash_leg_degrades_the_week_rather_than_raising(self) -> None:
        rows = _weekly_rows()[:2]
        produced = self._cash_for(rows)
        produced[1] = _build(_capture([]))
        packet = build_attribution_input(
            rows,
            attribution_epoch="us_short_market_diagnostic_attribution_v1",
            target_exposure_by_week=self._target(rows),
            cash_return_by_week=produced,
            as_of_date=AS_OF,
        )
        self.assertEqual("unavailable", packet["weeks"][0]["cash_return"]["status"])
        # ...and the report, which is where a week gets a status at all, degrades
        # that week rather than publishing an effect without its cash leg.
        report = build_attribution_report(packet, as_of_date=AS_OF)
        self.assertEqual("unavailable", report["weeks"][0]["status"])
        self.assertIsNone(report["weeks"][0]["exposure_effect"])


class CashFetchRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.inputs = Path(holder.name) / "market_diagnostic_inputs_private"
        self.requests: list[str] = []

    def _opener(self, rows):
        def opener(url: str) -> bytes:
            self.requests.append(url)
            return json.dumps({"observations": rows}).encode("utf-8")

        return opener

    _ROWS = [
        {"realtime_start": "2026-07-24", "realtime_end": "9999-12-31", "date": "2026-07-23", "value": "3.83"},
        {"realtime_start": "2026-07-25", "realtime_end": "9999-12-31", "date": "2026-07-24", "value": "3.87"},
    ]

    def _run(self, **overrides):
        kwargs = dict(
            decision_date=DECISION,
            valuation_date=VALUATION,
            calendar_week_index=1,
            as_of_date=AS_OF,
            inputs_root=self.inputs,
            opener=self._opener(self._ROWS),
            api_key="k" * 32,
            now=lambda: datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc),
            confirm_user_authorization=True,
        )
        kwargs.update(overrides)
        return cash.capture_cash_week(**kwargs)

    def test_a_live_capture_without_authorization_is_refused(self) -> None:
        """FRED is a real vendor; the direct and CLI paths had no door."""

        with self.assertRaises(cash.CashFetchError) as ctx:
            self._run(confirm_user_authorization=False)
        self.assertIn("authorization", str(ctx.exception))
        self.assertEqual([], self.requests, "it reached the vendor before the gate")

    def test_a_week_is_captured_once_and_never_re_requested(self) -> None:
        first = self._run()
        self.assertEqual("captured", first["status"])
        self.assertEqual("evaluable", first["cash_status"])
        self.assertEqual(1, len(self.requests))

        second = self._run()
        self.assertEqual("idempotent", second["status"])
        self.assertEqual(1, len(self.requests), "a second run re-requested the vendor")
        self.assertTrue(second["reused_capture"])

    def test_the_request_pins_a_real_time_window(self) -> None:
        """Without the pin the read is the revised view, which is hindsight."""

        self._run()
        self.assertIn("realtime_start=2026-07-03", self.requests[0])
        self.assertIn("realtime_end=2026-08-06", self.requests[0])

    def test_a_missing_key_fails_closed_without_touching_the_network(self) -> None:
        """No fallback to the unpinned public download: that view is revised."""

        result = self._run(api_key=None)
        self.assertEqual("unavailable", result["cash_status"])
        self.assertEqual([], self.requests)
        stored = cash.week_directory(DECISION, inputs_root=self.inputs) / cash.CAPTURE_FILENAME
        self.assertIn("MissingApiKey", stored.read_text(encoding="utf-8"))

    def test_the_key_never_reaches_any_stored_byte(self) -> None:
        """urllib puts the failing URL, and therefore the key, into its message."""

        secret = "s3cr3t" + "k" * 26

        def exploding(url: str) -> bytes:
            raise RuntimeError(f"HTTP 403 for {url}")

        result = self._run(opener=exploding, api_key=secret)
        self.assertEqual("unavailable", result["cash_status"])
        directory = cash.week_directory(DECISION, inputs_root=self.inputs)
        for path in directory.iterdir():
            with self.subTest(path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn(secret, text)
                self.assertNotIn("api_key", text)
        self.assertIn("RuntimeError", (directory / cash.CAPTURE_FILENAME).read_text(encoding="utf-8"))

    def test_rows_the_module_refuses_degrade_the_week_rather_than_raising(self) -> None:
        """A vendor that ANSWERS with unusable rows is a failed fetch, not a crash.

        Validation used to sit after the try, so FRED returning an observation
        dated past the as-of escaped `_build_capture` entirely instead of becoming
        the ordinary `failed` capture the honesty fields below describe.
        """

        future = [{"realtime_start": "2099-01-02", "realtime_end": "9999-12-31",
                   "date": "2099-01-01", "value": "3.87"}]
        result = self._run(opener=self._opener(future))
        self.assertEqual("unavailable", result["cash_status"])
        stored = cash.week_directory(DECISION, inputs_root=self.inputs) / cash.CAPTURE_FILENAME
        self.assertIn(FETCH_FAILED, stored.read_text(encoding="utf-8"))

    def test_a_non_private_destination_is_refused(self) -> None:
        with self.assertRaises(cash.CashFetchError) as ctx:
            self._run(inputs_root=Path(cash.ROOT) / "docs")
        self.assertIn("non-private", str(ctx.exception))
        self.assertFalse((Path(cash.ROOT) / "docs" / "cash").exists())

    def test_a_conflicting_observation_for_the_same_week_is_refused(self) -> None:
        self._run()
        with self.assertRaises(cash.CashFetchError) as ctx:
            self._run(calendar_week_index=2)
        self.assertIn("immutable", str(ctx.exception))

    def test_a_value_and_its_availability_date_come_from_one_vintage(self) -> None:
        """The reviewer's probe, verbatim: a revision must not inherit the old date.

        FRED revised DGS3MO for 2026-06-01 from 4.20 to 3.00 on 06-08. Taking the
        value from the vintage current at the read but the date from the EARLIEST
        vintage of the day paired 3.00 with 06-02 — a rate nobody could have seen,
        wearing a date that made it look point-in-time. Both now come from the one
        vintage that was current at the real-time end being read.
        """

        rows = [
            {"realtime_start": "2026-06-02", "realtime_end": "2026-06-07", "date": "2026-06-01", "value": "4.20"},
            {"realtime_start": "2026-06-08", "realtime_end": "9999-12-31", "date": "2026-06-01", "value": "3.00"},
        ]
        with self.subTest("read today: the revision, dated when it was revised"):
            self.assertEqual(
                [{"date": "20260601", "value": "3.00", "available_from": "2026-06-08"}],
                cash._collapse(rows, realtime_end="2026-08-06"),
            )
        with self.subTest("read as the world stood on 06-03: only the original"):
            self.assertEqual(
                [{"date": "20260601", "value": "4.20", "available_from": "2026-06-02"}],
                cash._collapse(rows, realtime_end="2026-06-03"),
            )

    def test_a_revision_is_not_usable_by_a_decision_that_predates_it(self) -> None:
        """The same probe carried through to the observation the gate consumes."""

        capture = _capture(
            [_observation("20260601", "3.00", "2026-06-08")],
            observation_window_start="2026-05-11",
            observation_window_end="2026-06-01",
        )
        observation = build_cash_observation(
            capture=capture,
            capture_sha256=DIGEST,
            valuation_date="20260601",
            decision_date="20260603",
            as_of_date=AS_OF,
        )
        self.assertEqual("unavailable", observation["status"])
        self.assertEqual([REASON_NO_PUBLISHED_RATE], observation["data_quality_reasons"])

    def test_collapse_reports_a_day_absent_from_the_as_of_vintage_as_a_placeholder(self) -> None:
        rows = [
            {"realtime_start": "2026-07-25", "realtime_end": "2026-07-27", "date": "2026-07-24", "value": "3.80"},
        ]
        collapsed = cash._collapse(rows, realtime_end="2026-08-06")
        self.assertEqual(MISSING_VALUE, collapsed[0]["value"])
        self.assertIsNone(collapsed[0]["available_from"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
