"""Offline contract tests for the row-19 margin-ratio denominator probe.

No network, no credential: every call goes through an injected stand-in client.
The probe's whole job is to turn three unknowns into recorded facts, so the
tests here pin the two ways a probe lies -- reading the unit wrong, and letting
a thin or absent answer read as a usable one.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners import a_short_margin_ratio_source_probe as probe  # noqa: E402


#: 中证全指 float value, published in 万元 (~7.1e13 CNY).
WHOLE_MARKET_FLOAT_MV_WAN = 7_100_000_000.0
#: Three-exchange rzye at ~2.59e12 CNY gives a ~3.6% ratio against the above.
RZYE_PER_EXCHANGE = 864_000_000_000.0


def _index_frame(trade_dates, float_mv=WHOLE_MARKET_FLOAT_MV_WAN):
    return pd.DataFrame([
        {"ts_code": "000985.CSI", "trade_date": date, "float_mv": float_mv,
         "total_mv": float_mv * 1.3, "pe": 14.2}
        for date in trade_dates
    ])


def _margin_frame(trade_dates):
    return pd.DataFrame([
        {"trade_date": date, "exchange_id": exchange, "rzye": RZYE_PER_EXCHANGE}
        for date in trade_dates for exchange in probe.MARGIN_EXCHANGES
    ])


class _Client:
    """Records every request; returns whatever the scenario dictates."""

    def __init__(self, *, index_by_window=None, margin_by_window=None, raises=None):
        self.index_by_window = index_by_window or {}
        self.margin_by_window = margin_by_window or {}
        self.raises = raises or {}
        self.requests = []

    def index_dailybasic(self, **kwargs):
        self.requests.append(("index_dailybasic", kwargs))
        key = (kwargs.get("ts_code"), kwargs.get("start_date"))
        if key in self.raises:
            raise self.raises[key]
        return self.index_by_window.get(key, pd.DataFrame())

    def margin(self, **kwargs):
        self.requests.append(("margin", kwargs))
        key = kwargs.get("start_date")
        if key in self.raises:
            raise self.raises[key]
        return self.margin_by_window.get(key, pd.DataFrame())


def _windows():
    return {window["label"]: window for window in probe.PROBE_WINDOWS}


def _full_scenario(*, six_year_index=True, six_year_margin=True,
                   float_mv=WHOLE_MARKET_FLOAT_MV_WAN):
    windows = _windows()
    index_by_window = {}
    for index in probe.CANDIDATE_INDICES:
        for label, window in windows.items():
            if label == "six_years_back" and not six_year_index:
                continue
            index_by_window[(index["ts_code"], window["start_date"])] = _index_frame(
                [window["end_date"]], float_mv=float_mv)
    margin_by_window = {windows["recent"]["start_date"]: _margin_frame(
        [windows["recent"]["end_date"]])}
    if six_year_margin:
        margin_by_window[windows["six_years_back"]["start_date"]] = _margin_frame(
            [windows["six_years_back"]["end_date"]])
    return _Client(index_by_window=index_by_window, margin_by_window=margin_by_window)


def _run(client):
    with tempfile.TemporaryDirectory() as tmp:
        return probe.run_probe(client, raw_root=Path(tmp))


class UnitInferenceTests(unittest.TestCase):
    def test_a_wan_yuan_float_value_is_read_as_wan_yuan(self):
        resolved = probe.infer_unit(WHOLE_MARKET_FLOAT_MV_WAN)
        self.assertEqual(resolved["unit"], "10k CNY (万元)")
        self.assertEqual(resolved["scale_to_yuan"], 1e4)

    def test_a_yuan_float_value_is_read_as_yuan(self):
        resolved = probe.infer_unit(WHOLE_MARKET_FLOAT_MV_WAN * 1e4)
        self.assertEqual(resolved["unit"], "CNY")
        self.assertEqual(resolved["scale_to_yuan"], 1.0)

    def test_a_missing_or_non_finite_value_resolves_to_no_unit(self):
        for value in (None, float("nan"), float("inf"), 0.0, -1.0, True):
            self.assertIsNone(probe.infer_unit(value)["unit"], msg=repr(value))

    def test_the_ratio_cross_check_rejects_a_wrong_unit_reading(self):
        balance = RZYE_PER_EXCHANGE * 3
        right = probe.margin_ratio_cross_check(balance, WHOLE_MARKET_FLOAT_MV_WAN, 1e4)
        wrong = probe.margin_ratio_cross_check(balance, WHOLE_MARKET_FLOAT_MV_WAN, 1.0)
        self.assertTrue(right["plausible"])
        self.assertFalse(wrong["plausible"])
        self.assertGreater(right["ratio_pct"], 0.5)
        self.assertLess(right["ratio_pct"], 8.0)

    def test_the_ratio_cross_check_refuses_incomplete_inputs(self):
        self.assertFalse(probe.margin_ratio_cross_check(None, 1.0, 1.0)["plausible"])
        self.assertFalse(probe.margin_ratio_cross_check(1.0, None, 1.0)["plausible"])
        self.assertFalse(probe.margin_ratio_cross_check(1.0, 1.0, None)["plausible"])
        self.assertFalse(probe.margin_ratio_cross_check(1.0, 0.0, 1.0)["plausible"])


class ProbeVerdictTests(unittest.TestCase):
    def test_a_complete_answer_reports_the_denominator_and_six_year_depth(self):
        summary = _run(_full_scenario())
        self.assertEqual(summary["verdict"], "denominator_and_six_year_history_available")
        self.assertEqual(summary["recommended_denominator"], "000985.CSI")
        self.assertTrue(summary["margin_ratio_cross_check"]["plausible"])
        self.assertTrue(summary["denominator_six_years_reachable"])
        self.assertTrue(summary["margin_numerator"]["six_years_back_reachable"])
        self.assertEqual(summary["margin_numerator"]["three_exchange_rzye_yuan"],
                         RZYE_PER_EXCHANGE * 3)

    def test_a_shallow_denominator_is_not_reported_as_six_year_capable(self):
        summary = _run(_full_scenario(six_year_index=False))
        self.assertEqual(summary["verdict"], "denominator_available_three_year_history_only")
        self.assertFalse(summary["denominator_six_years_reachable"])

    def test_a_shallow_numerator_alone_also_downgrades_the_verdict(self):
        summary = _run(_full_scenario(six_year_margin=False))
        self.assertEqual(summary["verdict"], "denominator_available_three_year_history_only")
        self.assertFalse(summary["margin_numerator"]["six_years_back_reachable"])

    def test_an_unreachable_endpoint_never_reads_as_a_usable_denominator(self):
        windows = _windows()
        client = _Client(raises={
            (index["ts_code"], window["start_date"]): RuntimeError("抱歉，您没有访问该接口的权限")
            for index in probe.CANDIDATE_INDICES for window in windows.values()
        })
        summary = _run(client)
        self.assertEqual(summary["verdict"], "no_reachable_float_mv_denominator")
        self.assertIsNone(summary["recommended_denominator"])
        self.assertIn("permission_or_entitlement",
                      {call.get("error_category") for call in summary["calls"]})

    def test_a_frame_without_float_mv_is_not_a_denominator(self):
        windows = _windows()
        bare = pd.DataFrame([{"ts_code": "000985.CSI", "trade_date": "20260804", "pe": 14.0}])
        client = _Client(index_by_window={
            (index["ts_code"], window["start_date"]): bare
            for index in probe.CANDIDATE_INDICES for window in windows.values()
        })
        summary = _run(client)
        self.assertEqual(summary["verdict"], "no_reachable_float_mv_denominator")

    def test_an_implausible_ratio_blocks_the_available_verdict(self):
        # A denominator 100x too small (a far-too-narrow index, not a unit
        # step) still resolves to a unit bucket, but the ratio it implies is
        # one no A-share market has ever occupied.
        summary = _run(_full_scenario(float_mv=WHOLE_MARKET_FLOAT_MV_WAN / 100))
        self.assertEqual(summary["verdict"], "denominator_reachable_but_unit_unresolved")
        self.assertFalse(summary["margin_ratio_cross_check"]["plausible"])

    def test_a_whole_unit_step_is_absorbed_by_design_and_that_is_correct(self):
        """Document the cross-check's real edge -- do not mistake it for a hole.

        ``infer_unit`` reads the scale off the observed magnitude, so a
        denominator differing by exactly 1e4 lands in the adjacent bucket and
        converts to the same CNY value.  The check therefore cannot
        discriminate a whole unit step -- and does not need to: the 万元-vs-元
        confusion is an *assumption* error, and this probe never assumes.
        """
        stepped = _run(_full_scenario(float_mv=WHOLE_MARKET_FLOAT_MV_WAN / 1e4))
        baseline = _run(_full_scenario())
        self.assertEqual(stepped["margin_ratio_cross_check"]["ratio"],
                         baseline["margin_ratio_cross_check"]["ratio"])
        self.assertEqual(
            stepped["indices"]["000985.CSI"]["float_mv_unit"]["unit"], "100m CNY (亿元)")
        self.assertEqual(
            baseline["indices"]["000985.CSI"]["float_mv_unit"]["unit"], "10k CNY (万元)")

    def test_the_call_budget_is_never_exceeded(self):
        client = _full_scenario()
        summary = _run(client)
        self.assertLessEqual(summary["call_budget"]["used"], probe.CALL_BUDGET)
        self.assertEqual(len(client.requests), summary["call_budget"]["used"])

    def test_an_incomplete_margin_session_is_not_summed_into_a_numerator(self):
        windows = _windows()
        partial = pd.DataFrame([
            {"trade_date": windows["recent"]["end_date"], "exchange_id": "SSE",
             "rzye": RZYE_PER_EXCHANGE},
            {"trade_date": windows["recent"]["end_date"], "exchange_id": "SZSE",
             "rzye": RZYE_PER_EXCHANGE},
        ])
        client = _full_scenario()
        client.margin_by_window[windows["recent"]["start_date"]] = partial
        summary = _run(client)
        self.assertIsNone(summary["margin_numerator"]["three_exchange_rzye_yuan"])
        self.assertFalse(summary["margin_ratio_cross_check"]["plausible"])

    def test_the_tracked_summary_carries_no_raw_rows_or_credentials(self):
        summary = _run(_full_scenario())
        text = json.dumps(summary, ensure_ascii=False, default=str)
        for forbidden in ("token", "TUSHARE", "http://", "https://", "api.tushare"):
            self.assertNotIn(forbidden, text, msg=forbidden)

        # No raw vendor row survives anywhere in the tracked summary.  Assert on
        # the carrier key at every depth, not on the substring "rows" -- that
        # would match the legitimate "row_count" and pass for the wrong reason.
        def _raw_row_carriers(node, path="$"):
            if isinstance(node, dict):
                found = ["/".join((path, "rows"))] if "rows" in node else []
                for key, value in node.items():
                    found += _raw_row_carriers(value, f"{path}/{key}")
                return found
            if isinstance(node, list):
                out = []
                for index, value in enumerate(node):
                    out += _raw_row_carriers(value, f"{path}[{index}]")
                return out
            return []

        self.assertEqual(_raw_row_carriers(summary), [])
        self.assertTrue(summary["comparison_only"])
        self.assertFalse(summary["production_effect_enabled"])

    def test_raw_is_written_under_the_injected_gitignored_root_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "raw"
            probe.run_probe(_full_scenario(), raw_root=root)
            written = sorted(path.name for path in root.glob("*.json"))
        self.assertTrue(written)
        self.assertTrue(all(name.endswith(".json") for name in written))
        self.assertIn("margin_recent.json", written)


class PlantedControlTests(unittest.TestCase):
    def test_neutralising_the_ratio_band_lets_a_too_narrow_denominator_pass(self):
        """Prove the band is what blocks a bad denominator, not luck.

        The patch removes the gate itself (widens the band to accept anything);
        a real input still reaches it, which is what makes this control valid.
        """
        narrow = WHOLE_MARKET_FLOAT_MV_WAN / 100
        self.assertEqual(_run(_full_scenario(float_mv=narrow))["verdict"],
                         "denominator_reachable_but_unit_unresolved")
        original = probe.PLAUSIBLE_RATIO_BAND
        try:
            probe.PLAUSIBLE_RATIO_BAND = (0.0, 1e9)   # the gate, removed
            neutralised = _run(_full_scenario(float_mv=narrow))
        finally:
            probe.PLAUSIBLE_RATIO_BAND = original
        self.assertEqual(neutralised["verdict"], "denominator_and_six_year_history_available")
        self.assertEqual(_run(_full_scenario(float_mv=narrow))["verdict"],
                         "denominator_reachable_but_unit_unresolved")


if __name__ == "__main__":
    unittest.main()
