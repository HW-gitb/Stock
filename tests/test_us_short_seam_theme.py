import math
import unittest
from datetime import date, timedelta
from importlib import import_module

from engine.us_short_core_score import core_score
from engine.us_short_industry_heat import industry_heat_block
from engine.us_short_provisional_theme_heat import provisional_theme_heat_block
from engine.us_short_theme_block import assemble_theme_block
from engine.us_short_seam_theme import (
    BINDING_PATH,
    CONFIRM_FLAG_KEYS,
    COVERAGE_DISPOSITIONS,
    OUTPUT_KEYS,
    PROJECTION_BASIS_POLICY,
    PRODUCER_REFS,
    THEME_MEMBERSHIP_POLICY,
    ThemeSeamError,
    load_binding,
    project_theme_block,
)


class EvilDict(dict):
    pass


class EvilList(list):
    pass


def _industry_result(heat):
    return {
        "industry_heat_by_ticker": heat,
        "sector_heat": {"Technology": 88.0},
        "sector_metrics": {
            "Technology": {
                "members": 3,
                "group_rel_strength": 0.10,
                "breadth_up_frac": 1.0,
                "new_high_frac": 1.0,
                "leader_rs": 0.15,
            }
        },
        "insufficient_sectors": [],
        "min_sector_members": 3,
    }


def _theme_result(theme_heat, insufficient_themes=None):
    insufficient_themes = [] if insufficient_themes is None else insufficient_themes
    return {
        "theme_heat": theme_heat,
        "confirm_flags": {
            theme_id: {
                "theme_breadth_up_frac": True,
                "theme_volume_confirm_frac": True,
                "theme_leader_rs": True,
                "theme_member_count": True,
            }
            for theme_id in theme_heat
        },
        "theme_metrics": {
            theme_id: {
                "member_count": 3,
                "breadth_up_frac": 1.0,
                "volume_confirm_frac": 1.0,
                "leader_rs": 0.15,
            }
            for theme_id in theme_heat
        },
        "insufficient_themes": insufficient_themes,
        "min_theme_members": 3,
    }


_AS_OF = "2026-06-30"
_SERIES_LEN = 64


def _dates(n):
    end = date.fromisoformat(_AS_OF)
    return [(end - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


def _dated_series(closes, volumes=None):
    points = []
    for idx, close in enumerate(closes):
        point = {"date": _dates(len(closes))[idx], "close": close}
        if volumes is not None:
            point["volume"] = volumes[idx]
        points.append(point)
    return {
        "as_of": _AS_OF,
        "session": "RTH",
        "adjustment_mode": "split_div_adjusted",
        "points": points,
    }


def _rising(start=100.0, step=1.0):
    return [float(start + step * idx) for idx in range(_SERIES_LEN)]


def _declining(start=200.0, step=-1.0):
    return [float(start + step * idx) for idx in range(_SERIES_LEN)]


def _surging_volume():
    return [1000.0] * 54 + [6000.0] * 10


def _flat_volume():
    return [1000.0] * _SERIES_LEN


def _hot_member():
    return _dated_series(_rising(), _surging_volume())


def _cold_member():
    return _dated_series(_declining(), _flat_volume())


def _sector_members():
    return {
        "AAPL": {"sector": "Technology", "series": _hot_member()},
        "MSFT": {"sector": "Technology", "series": _hot_member()},
        "NVDA": {"sector": "Technology", "series": _hot_member()},
        "JPM": {"sector": "Financials", "series": _cold_member()},
        "BAC": {"sector": "Financials", "series": _cold_member()},
        "WFC": {"sector": "Financials", "series": _cold_member()},
        "XOM": {"sector": "Energy", "series": _hot_member()},
        "CVX": {"sector": "Energy", "series": _hot_member()},
        "COP": {"sector": "Energy", "series": _hot_member()},
    }


def _producer_themes():
    return {
        "AI": {"members": {"AAPL": _hot_member(), "MSFT": _hot_member(), "NVDA": _hot_member()}},
        "BANKS": {"members": {"JPM": _cold_member(), "BAC": _cold_member(), "WFC": _cold_member()}},
        "SMALL": {"members": {"XOM": _hot_member(), "TSLA": _hot_member()}},
    }


def _theme_membership_from_producer_input(themes):
    return {theme_id: list(theme["members"].keys()) for theme_id, theme in themes.items()}


class SeamThemeProjectionTest(unittest.TestCase):
    def test_project_theme_block_matches_theme_block_direction_rules(self):
        industry = _industry_result({"AAPL": 10.0, "MSFT": 80.0})
        themes = _theme_result({"AI": 90.0, "DATA": 70.0})
        membership = {"AI": ["AAPL"], "DATA": ["NVDA"]}

        result = project_theme_block(
            industry_result=industry,
            provisional_theme_result=themes,
            theme_members_by_id=membership,
            target_tickers=["AAPL", "MSFT", "NVDA"],
        )

        expected = assemble_theme_block(
            [
                {
                    "theme_heat_score": 90.0,
                    "industry_heat_score": 10.0,
                    "theme_is_cross_sector": True,
                },
                {"industry_heat_score": 80.0, "theme_is_cross_sector": False},
                {"theme_heat_score": 70.0, "theme_is_cross_sector": True},
            ]
        )
        self.assertEqual(result["target_count"], 3)
        self.assertEqual(result["scored_count"], 3)
        self.assertEqual(result["neutral_fill_tickers"], [])
        self.assertEqual(
            result["theme_block_by_ticker"],
            {"AAPL": expected[0], "MSFT": expected[1], "NVDA": expected[2]},
        )
        self.assertEqual(
            result["coverage"],
            {
                "AAPL": "scored_theme_base",
                "MSFT": "scored_industry_base",
                "NVDA": "scored_theme_base",
            },
        )

    def test_project_theme_block_assembles_full_pool_before_projecting_targets(self):
        industry = _industry_result({"MSFT": 80.0})
        themes = _theme_result({"AI": 10.0, "DATA": 90.0})
        membership = {"AI": ["AAPL"], "DATA": ["NVDA"]}

        full_pool_rows = [
            {"theme_heat_score": 10.0, "theme_is_cross_sector": True},
            {"industry_heat_score": 80.0, "theme_is_cross_sector": False},
            {"theme_heat_score": 90.0, "theme_is_cross_sector": True},
        ]
        full_pool_expected = dict(zip(["AAPL", "MSFT", "NVDA"], assemble_theme_block(full_pool_rows)))
        target_subset_value = assemble_theme_block([full_pool_rows[0]])[0]

        result = project_theme_block(
            industry_result=industry,
            provisional_theme_result=themes,
            theme_members_by_id=membership,
            target_tickers=["AAPL"],
        )

        self.assertNotEqual(full_pool_expected["AAPL"], target_subset_value)
        self.assertEqual(result["theme_block_by_ticker"], {"AAPL": full_pool_expected["AAPL"]})
        self.assertEqual(result["coverage"], {"AAPL": "scored_theme_base"})

    def test_project_theme_block_accepts_real_producer_outputs_across_dispositions(self):
        industry_result = industry_heat_block(
            _sector_members(),
            spy_series=_dated_series(_rising(100.0, 0.2)),
            qqq_series=_dated_series(_rising(100.0, 0.2)),
        )
        themes_by_id = _producer_themes()
        provisional_theme_result = provisional_theme_heat_block(
            themes_by_id,
            spy_series=_dated_series(_rising(100.0, 0.2)),
            qqq_series=_dated_series(_rising(100.0, 0.2)),
        )

        result = project_theme_block(
            industry_result=industry_result,
            provisional_theme_result=provisional_theme_result,
            theme_members_by_id=_theme_membership_from_producer_input(themes_by_id),
            target_tickers=["AAPL", "XOM", "TSLA", "AMZN"],
        )

        self.assertIn("AAPL", result["theme_block_by_ticker"])
        self.assertIn("XOM", result["theme_block_by_ticker"])
        self.assertEqual(result["neutral_fill_tickers"], ["TSLA", "AMZN"])
        self.assertEqual(
            result["coverage"],
            {
                "AAPL": "scored_theme_base",
                "XOM": "scored_industry_base",
                "TSLA": "neutral_insufficient_theme_no_industry",
                "AMZN": "neutral_missing_theme_and_industry_base",
            },
        )

    def test_insufficient_theme_falls_back_to_industry_base(self):
        industry = _industry_result({"AAPL": 80.0})
        themes = _theme_result({}, insufficient_themes=["AI"])

        result = project_theme_block(
            industry_result=industry,
            provisional_theme_result=themes,
            theme_members_by_id={"AI": ["AAPL"]},
            target_tickers=["AAPL"],
        )

        self.assertEqual(result["theme_block_by_ticker"], {"AAPL": 100.0})
        self.assertEqual(result["neutral_fill_tickers"], [])
        self.assertEqual(result["coverage"], {"AAPL": "scored_industry_base"})

    def test_missing_theme_and_industry_base_gets_neutral_fill(self):
        result = project_theme_block(
            industry_result=_industry_result({}),
            provisional_theme_result=_theme_result({}, insufficient_themes=["AI"]),
            theme_members_by_id={"AI": ["AAPL"]},
            target_tickers=["AAPL", "MSFT"],
        )

        self.assertEqual(result["theme_block_by_ticker"], {})
        self.assertEqual(result["neutral_fill_tickers"], ["AAPL", "MSFT"])
        self.assertEqual(
            result["coverage"],
            {
                "AAPL": "neutral_insufficient_theme_no_industry",
                "MSFT": "neutral_missing_theme_and_industry_base",
            },
        )

    def test_project_theme_block_rejects_duplicate_cross_theme_membership(self):
        with self.assertRaisesRegex(ThemeSeamError, "duplicate theme membership"):
            project_theme_block(
                industry_result=_industry_result({"AAPL": 80.0}),
                provisional_theme_result=_theme_result({"AI": 90.0, "DATA": 70.0}),
                theme_members_by_id={"AI": ["AAPL"], "DATA": ["aapl"]},
                target_tickers=["AAPL"],
            )

    def test_project_theme_block_rejects_unknown_theme_membership(self):
        with self.assertRaisesRegex(ThemeSeamError, "unknown theme_id"):
            project_theme_block(
                industry_result=_industry_result({"AAPL": 80.0}),
                provisional_theme_result=_theme_result({"AI": 90.0}),
                theme_members_by_id={"UNKNOWN": ["AAPL"]},
                target_tickers=["AAPL"],
            )

    def test_project_theme_block_rejects_duplicate_normalized_theme_metadata_keys(self):
        themes = _theme_result({"AI": 90.0})
        themes["confirm_flags"][" AI "] = dict(themes["confirm_flags"]["AI"])

        with self.assertRaisesRegex(ThemeSeamError, "duplicate normalized theme_id"):
            project_theme_block(
                industry_result=_industry_result({"AAPL": 80.0}),
                provisional_theme_result=themes,
                theme_members_by_id={"AI": ["AAPL"]},
                target_tickers=["AAPL"],
            )

        themes = _theme_result({"AI": 90.0})
        themes["theme_metrics"][" AI "] = {}

        with self.assertRaisesRegex(ThemeSeamError, "duplicate normalized theme_id"):
            project_theme_block(
                industry_result=_industry_result({"AAPL": 80.0}),
                provisional_theme_result=themes,
                theme_members_by_id={"AI": ["AAPL"]},
                target_tickers=["AAPL"],
            )

    def test_project_theme_block_rejects_duplicate_normalized_industry_metadata_keys(self):
        industry = _industry_result({"AAPL": 80.0})
        industry["sector_metrics"][" Technology "] = {}

        with self.assertRaisesRegex(ThemeSeamError, "duplicate normalized label"):
            project_theme_block(
                industry_result=industry,
                provisional_theme_result=_theme_result({}),
                theme_members_by_id={},
                target_tickers=["AAPL"],
            )

    def test_project_theme_block_rejects_duplicate_normalized_membership_theme_id(self):
        with self.assertRaisesRegex(ThemeSeamError, "duplicate normalized theme_id"):
            project_theme_block(
                industry_result=_industry_result({"AAPL": 80.0, "MSFT": 70.0}),
                provisional_theme_result=_theme_result({"AI": 90.0}),
                theme_members_by_id={"AI": ["AAPL"], " AI ": ["MSFT"]},
                target_tickers=["AAPL", "MSFT"],
            )

    def test_project_theme_block_rejects_bad_industry_heat_values(self):
        for bad_industry_heat in (True, math.inf, -0.01, 100.01):
            with self.subTest(bad_industry_heat=bad_industry_heat):
                with self.assertRaises(ThemeSeamError):
                    project_theme_block(
                        industry_result=_industry_result({"AAPL": bad_industry_heat}),
                        provisional_theme_result=_theme_result({}),
                        theme_members_by_id={},
                        target_tickers=["AAPL"],
                    )

    def test_project_theme_block_rejects_hostile_containers(self):
        with self.assertRaisesRegex(ThemeSeamError, "exact dict"):
            project_theme_block(
                industry_result=EvilDict(_industry_result({"AAPL": 80.0})),
                provisional_theme_result=_theme_result({}),
                theme_members_by_id={},
                target_tickers=["AAPL"],
            )

        with self.assertRaisesRegex(ThemeSeamError, "exact list"):
            project_theme_block(
                industry_result=_industry_result({"AAPL": 80.0}),
                provisional_theme_result=_theme_result({}, insufficient_themes=["AI"]),
                theme_members_by_id={"AI": EvilList(["AAPL"])},
                target_tickers=["AAPL"],
            )

    def test_project_theme_block_conforms_to_binding_artifact(self):
        binding = load_binding()

        self.assertTrue(str(BINDING_PATH).endswith(binding["artifact_id"] + ".json"))
        self.assertEqual(OUTPUT_KEYS, tuple(binding["output_contract"]["required_keys"]))
        self.assertEqual(PRODUCER_REFS, tuple(binding["producer_refs"]))
        self.assertEqual(PROJECTION_BASIS_POLICY, binding["projection_basis_policy"])
        self.assertEqual(COVERAGE_DISPOSITIONS, tuple(binding["output_contract"]["coverage_dispositions"]))
        self.assertEqual(CONFIRM_FLAG_KEYS, tuple(binding["input_contract"]["confirm_flag_keys"]))
        self.assertEqual(THEME_MEMBERSHIP_POLICY, binding["input_contract"]["theme_membership_policy"])
        self.assertEqual(
            binding["authorization_boundary"],
            {
                "provider_call": False,
                "live_data": False,
                "datahub_write": False,
                "production_runner": False,
                "broker_or_order_execution": False,
            },
        )

    def test_project_theme_block_binding_producer_refs_resolve_to_callables(self):
        binding = load_binding()

        for ref in binding["producer_refs"]:
            module_path, func_name = ref.split("::", 1)
            module_name = module_path[:-3].replace("/", ".")
            producer = getattr(import_module(module_name), func_name)
            self.assertTrue(callable(producer), ref)

    def test_project_theme_block_can_feed_core_score_with_neutral_fill(self):
        theme = project_theme_block(
            industry_result=_industry_result({"AAPL": 80.0}),
            provisional_theme_result=_theme_result({}),
            theme_members_by_id={},
            target_tickers=["AAPL", "MSFT"],
        )

        scored = core_score({"momentum": 50.0, "catalyst": 50.0})

        self.assertEqual(theme["neutral_fill_tickers"], ["MSFT"])
        self.assertEqual(scored["blocks_used"]["theme"], 50.0)
        self.assertIn("theme", scored["missing_blocks"])
        self.assertEqual(scored["core_score"], 50.0)

    def test_project_theme_block_scored_value_contributes_to_core_score(self):
        theme = project_theme_block(
            industry_result=_industry_result({"AAPL": 80.0}),
            provisional_theme_result=_theme_result({}),
            theme_members_by_id={},
            target_tickers=["AAPL"],
        )

        scored = core_score(
            {
                "momentum": 50.0,
                "theme": theme["theme_block_by_ticker"]["AAPL"],
                "catalyst": 50.0,
            }
        )

        self.assertEqual(theme["theme_block_by_ticker"]["AAPL"], 100.0)
        self.assertEqual(scored["blocks_used"]["theme"], 100.0)
        self.assertEqual(scored["core_score"], 67.5)


if __name__ == "__main__":
    unittest.main()
