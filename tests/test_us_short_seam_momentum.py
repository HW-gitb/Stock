# -*- coding: utf-8 -*-
"""Tests for engine/us_short_seam_momentum.py (Cut 6-a: batch5→batch4 momentum score-block seam).

Pure/offline. Covers the projection, the FULL producer-result partition validation (accepted key set,
min_coverage, coverage_matrix identity==union + row shape + scored/n_present relation + per-disposition
band + physical bound, sub_feature_coverage universe), the CROSS-SUMMARY coherence (row/column margin
conservation + Gale-Ryser realizability — the fixtures are built from a real incidence, and a
real-producer positive control proves no false-negative), post-canonical duplicate rejection, exact
built-in numeric domain, exact built-in CONTAINER types at the public boundary (dict/list subclasses +
hostile-str keys contained as MomentumSeamError, never a raw exception), binding<->engine<->producer
conformance + identity authority, and an end-to-end projection -> core_score neutral-block proof.
"""
import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import us_short_seam_momentum as sm  # noqa: E402
from engine.us_short_seam_momentum import (  # noqa: E402
    project_momentum_block,
    MomentumSeamError,
    DISPOSITION_SCORED,
    DISPOSITION_INSUFFICIENT_HISTORY,
    DISPOSITION_INSUFFICIENT_COVERAGE,
    DISPOSITION_ABSENT,
    COVERAGE_DISPOSITIONS,
    _finite_block_value,
)
from engine.us_short_momentum import momentum_block  # noqa: E402
from engine.us_short_core_score import core_score, NEUTRAL_BLOCK  # noqa: E402
from engine.us_short_eligibility_gate import canonical_us_ticker  # noqa: E402

_SUB_FEATURES = ("ret_1m", "ret_3m", "ret_5d", "ret_10d", "rel_spy_1m", "rel_qqq_1m", "vol_surge")


def _result(block=None, hist=None, cov=None, min_coverage=4):
    """A COHERENT full producer result built from a REAL ticker×sub-feature incidence (so its margins
    are conserved AND Gale-Ryser realizable): a scored ticker holds exactly `min_coverage` sub-features,
    an insufficient_coverage ticker holds 1 (needs min_coverage >= 2), a history ticker holds 0. Tests
    mutate one field off this baseline to exercise a single fail-closed edge."""
    block = {} if block is None else dict(block)
    hist = [] if hist is None else list(hist)
    cov = [] if cov is None else list(cov)
    incidence = {}
    for t in block:
        incidence[t] = set(_SUB_FEATURES[:min_coverage])   # >= min_coverage present -> scored
    for t in hist:
        incidence[t] = set()                               # 0 present
    for t in cov:
        incidence[t] = set(_SUB_FEATURES[:1])              # exactly 1 present
    matrix = {t: {"n_present": len(p), "scored": len(p) >= min_coverage} for t, p in incidence.items()}
    subfeat = {sf: sum(1 for p in incidence.values() if sf in p) for sf in _SUB_FEATURES}
    return {
        "momentum_block": dict(block),
        "insufficient_history": hist,
        "insufficient_coverage": cov,
        "coverage_matrix": matrix,
        "sub_feature_coverage": subfeat,
        "min_coverage": min_coverage,
    }


class _HostileStr(str):
    """A str subclass whose canonical-path methods bomb — proves the seam rejects a non-plain-`str` via
    `type(x) is not str` BEFORE any dispatch. Hashable (inherits str.__hash__)."""

    def isascii(self):
        raise RuntimeError("isascii boom")

    def strip(self, *a, **k):
        raise RuntimeError("strip boom")

    def upper(self):
        raise RuntimeError("upper boom")


class _StrKeyBomb(str):
    """A str subclass whose __str__/__repr__ bomb — proves no diagnostic ever formats an untrusted key
    (rejected via type(k) is str first). Hashable so it can be a dict key."""

    def __str__(self):
        raise RuntimeError("str boom")

    def __repr__(self):
        raise RuntimeError("repr boom")


class _FloatBomb(float):
    def __float__(self):
        raise RuntimeError("float boom")


class _CmpBombFloat(float):
    def __le__(self, other):
        raise RuntimeError("le boom")

    def __ge__(self, other):
        raise RuntimeError("ge boom")


class _SneakyDict(dict):
    """A dict subclass whose access methods bomb — proves the seam rejects a container subclass BEFORE
    dispatching .keys()/.items()/iteration."""

    def keys(self):
        raise RuntimeError("keys boom")

    def items(self):
        raise RuntimeError("items boom")

    def __iter__(self):
        raise RuntimeError("iter boom")


class _SneakyList(list):
    def __iter__(self):
        raise RuntimeError("iter boom")


class ProjectionHappyPathTests(unittest.TestCase):
    def test_scored_targets_projected(self):
        out = project_momentum_block(_result(block={"AAPL": 80.0, "MSFT": 20.0, "NVDA": 55.5}), ["AAPL", "MSFT"])
        self.assertEqual(out["momentum_by_ticker"], {"AAPL": 80.0, "MSFT": 20.0})
        self.assertEqual(out["neutral_fill_tickers"], [])
        self.assertEqual((out["target_count"], out["scored_count"]), (2, 2))

    def test_insufficient_and_absent_go_to_neutral_fill(self):
        out = project_momentum_block(_result(block={"AAPL": 80.0}, hist=["TSLA"], cov=["AMD"]),
                                     ["AAPL", "TSLA", "AMD", "ZZZ"])
        self.assertEqual(out["momentum_by_ticker"], {"AAPL": 80.0})
        self.assertEqual(out["neutral_fill_tickers"], ["TSLA", "AMD", "ZZZ"])
        self.assertEqual(out["coverage"], {
            "AAPL": DISPOSITION_SCORED, "TSLA": DISPOSITION_INSUFFICIENT_HISTORY,
            "AMD": DISPOSITION_INSUFFICIENT_COVERAGE, "ZZZ": DISPOSITION_ABSENT,
        })

    def test_empty_targets_ok(self):
        out = project_momentum_block(_result(block={"AAPL": 50.0}), [])
        self.assertEqual((out["momentum_by_ticker"], out["neutral_fill_tickers"]), ({}, []))

    def test_disposition_vocab_is_closed(self):
        self.assertEqual(COVERAGE_DISPOSITIONS, {
            DISPOSITION_SCORED, DISPOSITION_INSUFFICIENT_HISTORY,
            DISPOSITION_INSUFFICIENT_COVERAGE, DISPOSITION_ABSENT})


class IdentityCanonicalizationTests(unittest.TestCase):
    def test_target_casefold_matches_canonical_producer_key(self):
        out = project_momentum_block(_result(block={"AAPL": 70.0}), [" aapl "])
        self.assertEqual(out["momentum_by_ticker"], {"AAPL": 70.0})

    def test_class_share_preserved(self):
        out = project_momentum_block(_result(block={"BRK.B": 65.0}), ["brk.b"])
        self.assertEqual(out["momentum_by_ticker"], {"BRK.B": 65.0})

    def test_duplicate_target_rejected(self):
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(_result(block={"AAPL": 50.0}), ["AAPL", "aapl"])

    def test_non_canonical_target_rejected(self):
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(_result(), ["600000.SH"])

    def test_non_str_target_rejected(self):
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(_result(), [123])


class ProducerResultShapeTests(unittest.TestCase):
    def test_result_not_dict_rejected(self):
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(["AAPL"], ["AAPL"])

    def test_missing_accepted_key_rejected(self):
        r = _result(block={"AAPL": 50.0})
        del r["coverage_matrix"]
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_extra_producer_key_rejected(self):
        r = _result(block={"AAPL": 50.0})
        r["surprise"] = 1
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_block_not_dict_rejected(self):
        r = _result()
        r["momentum_block"] = ["AAPL"]
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_non_canonical_block_key_rejected(self):
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(_result(block={"600000.SH": 50.0}), ["AAPL"])

    def test_insufficient_element_non_canonical_rejected(self):
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(_result(block={"AAPL": 50.0}, cov=["600000.SH"]), ["AAPL"])

    def test_scored_and_insufficient_clash_rejected(self):
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(_result(block={"AAPL": 50.0}, hist=["AAPL"]), ["AAPL"])

    def test_min_coverage_bad_value_rejected(self):
        for bad in (True, 0, 4.0, "4", None, 100):
            r = _result(block={"AAPL": 50.0})
            r["min_coverage"] = bad
            with self.assertRaises(MomentumSeamError):
                project_momentum_block(r, ["AAPL"])


class CoveragePartitionTests(unittest.TestCase):
    def test_forged_coverage_scored_value_but_matrix_unscored_rejected(self):
        r = _result(block={"AAPL": 50.0})
        r["coverage_matrix"]["AAPL"] = {"n_present": 0, "scored": False}
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_scored_flag_disagrees_with_relation_rejected(self):
        r = _result(block={"AAPL": 50.0})
        r["coverage_matrix"]["AAPL"] = {"n_present": 4, "scored": False}
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_matrix_missing_identity_rejected(self):
        r = _result(block={"AAPL": 50.0})
        del r["coverage_matrix"]["AAPL"]
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_matrix_extra_identity_rejected(self):
        r = _result(block={"AAPL": 50.0})
        r["coverage_matrix"]["MSFT"] = {"n_present": 4, "scored": True}
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_matrix_row_wrong_shape_rejected(self):
        for bad_row in ({"n_present": 4}, {"n_present": 4, "scored": True, "x": 1}):
            r = _result(block={"AAPL": 50.0})
            r["coverage_matrix"]["AAPL"] = bad_row
            with self.assertRaises(MomentumSeamError):
                project_momentum_block(r, ["AAPL"])

    def test_matrix_n_present_bad_type_rejected(self):
        for bad in (4.0, True, "4"):
            r = _result(block={"AAPL": 50.0})
            r["coverage_matrix"]["AAPL"] = {"n_present": bad, "scored": True}
            with self.assertRaises(MomentumSeamError):
                project_momentum_block(r, ["AAPL"])

    def test_matrix_scored_non_bool_rejected(self):
        r = _result(block={"AAPL": 50.0})
        r["coverage_matrix"]["AAPL"] = {"n_present": 4, "scored": 1}
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_history_with_nonzero_n_present_rejected(self):
        r = _result(hist=["TSLA"])
        r["coverage_matrix"]["TSLA"] = {"n_present": 2, "scored": False}
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["TSLA"])

    def test_n_present_above_subfeature_max_rejected(self):
        r = _result(block={"AAPL": 50.0})
        r["coverage_matrix"]["AAPL"] = {"n_present": 1000, "scored": True}
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_margin_conservation_violation_rejected(self):
        # bump a column count within its own [0,#ident] bound but break Σrow == Σcol
        r = _result(block={"AAPL": 50.0})   # n_ident == 1; AAPL holds first-4 features
        r["sub_feature_coverage"]["rel_spy_1m"] = 1   # was 0 -> Σcol=5 != Σrow=4
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_margin_equal_total_but_unrealizable_rejected(self):
        # Codex's example: row degrees [7,1], col degrees [2,2,2,2,0,0,0]; equal total 8 but not
        # Gale-Ryser realizable (k=1: 7 > 4). Bands + identity + conservation all pass first.
        r = {
            "momentum_block": {"AAA": 50.0},
            "insufficient_history": [],
            "insufficient_coverage": ["BBB"],
            "coverage_matrix": {"AAA": {"n_present": 7, "scored": True},
                                "BBB": {"n_present": 1, "scored": False}},
            "sub_feature_coverage": dict(zip(_SUB_FEATURES, [2, 2, 2, 2, 0, 0, 0])),
            "min_coverage": 4,
        }
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAA", "BBB"])

    def test_coherent_partition_positive_control(self):
        out = project_momentum_block(_result(block={"AAPL": 90.0}, hist=["TSLA"], cov=["AMD"]),
                                     ["AAPL", "TSLA", "AMD"])
        self.assertEqual(out["scored_count"], 1)


class SubFeatureCoverageTests(unittest.TestCase):
    def test_wrong_universe_rejected(self):
        r = _result(block={"AAPL": 50.0})
        r["sub_feature_coverage"] = {"ret_1m": 1}
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_count_above_identity_count_rejected(self):
        r = _result(block={"AAPL": 50.0})   # n_ident == 1
        r["sub_feature_coverage"]["ret_1m"] = 5
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_count_bad_type_rejected(self):
        for bad in (True, 1.0, "1", -1):
            r = _result(block={"AAPL": 50.0})
            r["sub_feature_coverage"]["ret_1m"] = bad
            with self.assertRaises(MomentumSeamError):
                project_momentum_block(r, ["AAPL"])


class DuplicateRejectionTests(unittest.TestCase):
    def test_duplicate_in_insufficient_history_rejected(self):
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(_result(hist=["AAPL", "aapl"]), ["AAPL"])

    def test_duplicate_in_insufficient_coverage_rejected(self):
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(_result(cov=["AMD", "amd"]), ["AMD"])


class BlockValueDomainTests(unittest.TestCase):
    def _expect_raise(self, value):
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(_result(block={"AAPL": value}), ["AAPL"])

    def test_bool_rejected(self):
        self._expect_raise(True)
        self._expect_raise(False)

    def test_numeric_string_rejected(self):
        self._expect_raise("50")

    def test_nan_inf_rejected(self):
        self._expect_raise(float("nan"))
        self._expect_raise(float("inf"))

    def test_out_of_domain_rejected(self):
        self._expect_raise(100.0001)
        self._expect_raise(-0.0001)

    def test_none_rejected(self):
        self._expect_raise(None)

    def test_overflowing_huge_int_contained(self):
        # a legitimate exact int too large for float() must be contained as MomentumSeamError, not a
        # raw OverflowError (§3.5 cold-attack finding)
        self._expect_raise(10 ** 309)
        self._expect_raise(-(10 ** 309))

    def test_boundaries_accepted(self):
        out = project_momentum_block(_result(block={"AAA": 0.0, "BBB": 100.0}), ["AAA", "BBB"])
        self.assertEqual(out["momentum_by_ticker"], {"AAA": 0.0, "BBB": 100.0})

    def test_int_coerced_to_float(self):
        out = project_momentum_block(_result(block={"AAPL": 50}), ["AAPL"])
        self.assertIs(type(out["momentum_by_ticker"]["AAPL"]), float)

    def test_finite_block_value_unit(self):
        for bad in (True, "50", float("nan"), 101.0, _FloatBomb(50.0), _CmpBombFloat(50.0), 10 ** 309):
            self.assertIsNone(_finite_block_value(bad))
        self.assertEqual(_finite_block_value(0), 0.0)
        self.assertEqual(_finite_block_value(100), 100.0)


class HostileSubclassValueTests(unittest.TestCase):
    def test_hostile_str_target(self):
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(_result(block={"AAPL": 50.0}), [_HostileStr("AAPL")])

    def test_hostile_str_block_key(self):
        r = _result(block={"AAPL": 50.0})
        r["momentum_block"][_HostileStr("MSFT")] = 50.0
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_hostile_float_bomb_value_contained(self):
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(_result(block={"AAPL": _FloatBomb(50.0)}), ["AAPL"])

    def test_hostile_comparison_float_contained(self):
        for v in (_CmpBombFloat(50.0), _CmpBombFloat(150.0)):
            with self.assertRaises(MomentumSeamError):
                project_momentum_block(_result(block={"AAPL": v}), ["AAPL"])


class HostileContainerTests(unittest.TestCase):
    """Residual B: exact built-in container types at the public boundary; a subclass or a hostile-str key
    must be contained as MomentumSeamError before any .keys()/.items()/iteration/format dispatch."""

    def test_result_dict_subclass_rejected(self):
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(_SneakyDict(_result(block={"AAPL": 50.0})), ["AAPL"])

    def test_block_dict_subclass_rejected(self):
        r = _result(block={"AAPL": 50.0})
        r["momentum_block"] = _SneakyDict(r["momentum_block"])
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_matrix_dict_subclass_rejected(self):
        r = _result(block={"AAPL": 50.0})
        r["coverage_matrix"] = _SneakyDict(r["coverage_matrix"])
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_matrix_row_dict_subclass_rejected(self):
        r = _result(block={"AAPL": 50.0})
        r["coverage_matrix"]["AAPL"] = _SneakyDict({"n_present": 4, "scored": True})
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_subfeat_dict_subclass_rejected(self):
        r = _result(block={"AAPL": 50.0})
        r["sub_feature_coverage"] = _SneakyDict(r["sub_feature_coverage"])
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_insufficient_list_subclass_rejected(self):
        r = _result(block={"AAPL": 50.0})
        r["insufficient_history"] = _SneakyList([])
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_target_list_subclass_rejected(self):
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(_result(block={"AAPL": 50.0}), _SneakyList(["AAPL"]))

    def test_hostile_str_extra_result_key_contained(self):
        r = _result(block={"AAPL": 50.0})
        r[_StrKeyBomb("extra")] = 1   # extra key whose __str__/__repr__ bomb -> must not be formatted
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])

    def test_hostile_str_subfeat_key_contained(self):
        r = _result(block={"AAPL": 50.0})
        r["sub_feature_coverage"][_StrKeyBomb("ret_1m")] = 0
        with self.assertRaises(MomentumSeamError):
            project_momentum_block(r, ["AAPL"])


class ConformanceTests(unittest.TestCase):
    def test_engine_consts_match_binding(self):
        b = sm.load_binding()
        self.assertEqual([sm._BLOCK_MIN, sm._BLOCK_MAX], b["block_value_domain"])
        self.assertEqual(list(sm._SUB_FEATURE_UNIVERSE), b["sub_feature_universe"])
        self.assertEqual(sm._ACCEPTED_PRODUCER_KEYS, set(b["accepted_producer_result_keys"]))
        self.assertEqual(sm._COVERAGE_ROW_KEYS, set(b["coverage_row_shape"]))
        self.assertEqual(COVERAGE_DISPOSITIONS, set(b["disposition_vocabulary"]))
        self.assertEqual(list(sm._PROJECTION_OUTPUT_KEYS), b["projection_output_keys"])

    def test_sub_feature_universe_matches_producer_default(self):
        default_sf = inspect.signature(momentum_block).parameters["sub_features"].default
        self.assertEqual(sm._SUB_FEATURE_UNIVERSE, tuple(default_sf))

    def test_identity_authority_triangulated(self):
        # the seam's identity function IS the single eligibility-gate policy the binding names
        self.assertIs(sm.canonical_us_ticker, canonical_us_ticker)
        self.assertIn("canonical_us_ticker", sm.load_binding()["identity_policy"])

    def test_projection_output_keys(self):
        out = project_momentum_block(_result(block={"AAPL": 50.0}), ["AAPL"])
        self.assertEqual(set(out), set(sm._PROJECTION_OUTPUT_KEYS))


class RealProducerPositiveControlTests(unittest.TestCase):
    """Prove the validator ACCEPTS genuine momentum_block output (no false-negative from the margin
    conservation / Gale-Ryser realizability checks)."""

    def test_real_producer_output_projects(self):
        feats = {
            "AAA": {"ret_1m": 0.10, "ret_3m": 0.20, "ret_5d": 0.05, "ret_10d": 0.08},
            "BBB": {"ret_1m": -0.05, "ret_3m": 0.02, "ret_5d": -0.01, "ret_10d": 0.03},
            "CCC": {"ret_1m": 0.01},   # 1 feature -> insufficient_coverage (< default min_coverage 4)
            "DDD": {},                 # 0 features -> insufficient_history
        }
        res = momentum_block(feats)
        out = project_momentum_block(res, ["AAA", "BBB", "CCC", "DDD"])
        self.assertEqual(set(out["momentum_by_ticker"]), {"AAA", "BBB"})
        self.assertIn("CCC", out["neutral_fill_tickers"])
        self.assertIn("DDD", out["neutral_fill_tickers"])


class EndToEndCoreScoreTests(unittest.TestCase):
    """Finding (5): a valid scored value contributes to core_score; a neutral-fill disposition omits the
    block so core_score applies the §4.2 neutral default."""

    def test_scored_contributes_and_neutral_fill_omits(self):
        out = project_momentum_block(_result(block={"AAPL": 80.0}, hist=["TSLA"]), ["AAPL", "TSLA"])
        aapl_score = core_score({"momentum": out["momentum_by_ticker"]["AAPL"], "theme": 50.0, "catalyst": 50.0})
        self.assertNotIn("momentum", aapl_score["missing_blocks"])
        self.assertEqual(aapl_score["blocks_used"]["momentum"], 80.0)

        self.assertIn("TSLA", out["neutral_fill_tickers"])
        tsla_score = core_score({"theme": 50.0, "catalyst": 50.0})   # composer omits momentum
        self.assertIn("momentum", tsla_score["missing_blocks"])
        self.assertEqual(tsla_score["blocks_used"]["momentum"], NEUTRAL_BLOCK)


if __name__ == "__main__":
    unittest.main()
