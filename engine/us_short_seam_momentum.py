# -*- coding: utf-8 -*-
"""US-short scoring-seam: momentum block projection (batch5→batch4 R3 seam, offline half — Cut 6-a).

Design authority: docs/us_short_system_design.md §4.2 (core_score 40% 动量 block; 缺分量→中性) /
§4.0 (两遍打分) / §18.2 (跨模块共享契约先 schema-first 冻结再消费) / §19. This module is PURE INTERNAL
GLUE with no provider contract and no new scoring threshold. It does NOT fetch, does NOT score, and
does NOT re-run the producer; it PROJECTS the already-computed full-pool momentum PRODUCER result
(engine/us_short_momentum.py::momentum_block) onto the target row set (the Pass2-clean candidates +
force-in holdings) that the batch4 weekend analysis stage
(engine/us_short_weekend_analysis.py::analyze_rows) scores via core_score.

Because it is a cross-module seam, its shared contract is frozen SCHEMA-FIRST (§18.2): the accepted
producer-result shape, the projection output shape, the coverage partition policy (incl. the margin
conservation + Gale-Ryser realizability rule), the identity authority, and the disposition/neutral-fill
policy are pinned in docs/us_short_seam_momentum_binding_20260702.json (+ its adversarial schema test);
the module consts below are triangulated == that binding.

WHAT THIS IS: the momentum leg of the score_blocks seam. For each target ticker it returns either the
ticker's 0-100 full-pool momentum block value (the producer SCORED it) or a neutral-fill disposition
(insufficient_history / insufficient_coverage / absent from the pool). The composer (later cut) then
OMITS the momentum block for a neutral-fill ticker so core_score applies the §4.2 neutral-block rule.

WHAT THIS IS NOT: not a fetch, not feature computation, not a re-implementation of momentum_block, not
the theme / catalyst legs, not the score_blocks composer, not Pass2, not selection. Live provider
fetch of the daily series that feeds the producer remains GATED (SR-PROVIDER-001).

Fail-closed / whole-class. (1) The producer result is re-validated as ONE COHERENT PARTITION: accepted
key set, min_coverage, block value numeric type + [0,100] domain, coverage_matrix row shape, the
partition invariants (matrix identities == scored∪history∪coverage; scored ⟺ n_present≥min_coverage;
history ⟺ n_present==0; insufficient_coverage ⟺ 0<n_present<min_coverage), AND the cross-summary
coherence — because momentum_block derives per-ticker n_present (row degrees) and per-sub_feature counts
(column degrees) from the SAME ticker×sub-feature incidence, their totals must be equal and the two
degree sequences must be jointly Gale-Ryser realizable as a binary incidence matrix; a forged result
that invents the two margins independently is rejected. (2) EXACT built-in types at the public boundary:
containers must be exactly `dict`/`list`/`tuple` (a subclass overriding .get/.items/__iter__ is rejected
BEFORE dispatch, not accepted via isinstance), every dict key is `type(k) is str` before any set/`in`/
format op, a block value is an exact built-in int/float (bool / numeric-string / numeric subclass /
hostile __float__/__le__ rejected before any conversion), and NO diagnostic ever formats an untrusted
key/value (only type names + known-safe constants) — so no attacker-controlled dunder can leak outside
`MomentumSeamError`. Every identity-bearing collection rejects a post-canonical duplicate. The caller's
target set is canonicalized under the single identity policy (engine/us_short_eligibility_gate.py::
canonical_us_ticker). Pure/offline; no provider/live/network; no A-share crossing.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from engine.us_short_eligibility_gate import canonical_us_ticker  # single identity policy (one stock, one id)

BINDING_PATH = Path(__file__).resolve().parent.parent / "docs" / "us_short_seam_momentum_binding_20260702.json"


def load_binding():
    """Return the frozen seam binding (single source; the schema-test freezes it and a conformance test
    triangulates these module consts == binding, so neither can silently drift)."""
    return json.loads(BINDING_PATH.read_text(encoding="utf-8"))


# --- Frozen consts (triangulated == binding by tests/test_us_short_seam_momentum.py conformance). ---
_BLOCK_MIN, _BLOCK_MAX = 0.0, 100.0
# The v1 accepted momentum sub-feature universe; a conformance test triangulates this == the producer's
# own default sub_features (engine/us_short_momentum.py::momentum_block) so the two cannot drift apart.
_SUB_FEATURE_UNIVERSE = ("ret_1m", "ret_3m", "ret_5d", "ret_10d", "rel_spy_1m", "rel_qqq_1m", "vol_surge")
_MAX_SUBFEATURES = len(_SUB_FEATURE_UNIVERSE)   # a coverage count / min_coverage can't exceed the universe size
_ACCEPTED_PRODUCER_KEYS = frozenset({
    "momentum_block", "insufficient_history", "insufficient_coverage",
    "coverage_matrix", "sub_feature_coverage", "min_coverage",
})
_COVERAGE_ROW_KEYS = frozenset({"n_present", "scored"})

# Per-target coverage disposition vocabulary (single source; §11.5 覆盖诚实 downstream reads these).
DISPOSITION_SCORED = "scored"
DISPOSITION_INSUFFICIENT_HISTORY = "insufficient_history"
DISPOSITION_INSUFFICIENT_COVERAGE = "insufficient_coverage"
DISPOSITION_ABSENT = "absent_from_pool"
COVERAGE_DISPOSITIONS = frozenset({
    DISPOSITION_SCORED, DISPOSITION_INSUFFICIENT_HISTORY,
    DISPOSITION_INSUFFICIENT_COVERAGE, DISPOSITION_ABSENT,
})
_PROJECTION_OUTPUT_KEYS = ("momentum_by_ticker", "neutral_fill_tickers", "coverage", "target_count", "scored_count")

# Producer-result keys (from engine/us_short_momentum.py::momentum_block).
_BLOCK_KEY = "momentum_block"
_HIST_KEY = "insufficient_history"
_COV_KEY = "insufficient_coverage"
_MATRIX_KEY = "coverage_matrix"
_SUBFEAT_KEY = "sub_feature_coverage"
_MIN_COVERAGE_KEY = "min_coverage"
_N_PRESENT = "n_present"
_SCORED = "scored"


class MomentumSeamError(ValueError):
    """The momentum producer result or the caller's target ticker set is malformed / self-contradictory /
    has drifted from the frozen seam contract (fail-closed — never project a bad or unavailable value
    into a live score, and never leak an attacker-controlled exception outside this type)."""


def _require_exact_dict(x, *, name):
    """Exactly a built-in `dict` (a subclass overriding .get/.items/__iter__ is rejected BEFORE any
    dispatch); else raise. Returns x."""
    if type(x) is not dict:
        raise MomentumSeamError(f"{name} 须为精确内建 dict（拒子类，防 hostile .get/.items 分发）: {type(x).__name__}")
    return x


def _require_exact_list(x, *, name):
    """Exactly a built-in `list` (a subclass overriding __iter__ is rejected); else raise. Returns x."""
    if type(x) is not list:
        raise MomentumSeamError(f"{name} 须为精确内建 list（拒子类）: {type(x).__name__}")
    return x


def _str_keys(d, *, name):
    """Return the key set of an exact dict, requiring every key to be a plain `str` FIRST (so a non-str
    or str-subclass key can neither invoke a hostile __eq__/__hash__ during set ops nor a hostile __str__
    in a diagnostic). `d` is already an exact dict."""
    out = set()
    for k in d.keys():
        if type(k) is not str:
            raise MomentumSeamError(f"{name} 键须为 str: {type(k).__name__}")
        out.add(k)
    return out


def _finite_block_value(x):
    """A strict momentum block value in [0, 100]: an EXACT built-in int/float (NOT bool, NOT a numeric
    string, NOT a numpy/other numeric subclass, NOT an object with a hostile __float__/__le__), finite,
    in-domain; else None. Exact-type is checked BEFORE any conversion/comparison, so an untrusted value
    can neither dispatch a hostile dunder nor leak a raw exception; a legitimate huge int (abs ≳ 1.8e308)
    that would overflow float() is CONTAINED (returns None, never a raw OverflowError). Out-of-[0,100]
    returns None (the caller raises) rather than clamping — clamping would mask a producer bug."""
    if type(x) is not int and type(x) is not float:
        return None
    try:
        xf = float(x)   # exact built-in int/float -> float() can't dispatch a hostile __float__, but a
    except OverflowError:  # legitimate huge int overflows float() intrinsically -> contain it fail-closed
        return None
    if not math.isfinite(xf) or not (_BLOCK_MIN <= xf <= _BLOCK_MAX):
        return None
    return xf


def _exact_int(x, *, min_value):
    """An EXACT built-in int (NOT bool, NOT a subclass) >= min_value; else None."""
    if type(x) is not int:
        return None
    return x if x >= min_value else None


def _canonical_ticker_strict(raw, *, where):
    """raw -> canonical US ticker, fail-closed. A non-plain-`str` (incl. a hostile str subclass) is
    rejected BEFORE any method dispatch; a non-canonical / A-share / blank value raises. Returns a plain
    str. `raw!r` in the error is safe because raw is proven a plain str first."""
    if type(raw) is not str:
        raise MomentumSeamError(f"{where} ticker 须为 str: {type(raw).__name__}")
    ct = canonical_us_ticker(raw)   # raw is a plain str here -> str methods are the builtins (safe)
    if ct is None:
        raise MomentumSeamError(f"{where} 非规范 US ticker（拒 A 股码/坏形/空）: {raw!r}")
    return ct


def _canonical_unique_targets(target_tickers):
    """Canonicalize the caller's target ticker set (one identity per stock) in order; reject a
    non-exact-list/tuple / non-str / non-canonical / post-canonical duplicate ticker. Returns a list."""
    if type(target_tickers) is not list and type(target_tickers) is not tuple:
        raise MomentumSeamError(f"target_tickers 须为精确内建 list/tuple: {type(target_tickers).__name__}")
    out, seen = [], set()
    for raw in target_tickers:
        ct = _canonical_ticker_strict(raw, where="target")
        if ct in seen:
            raise MomentumSeamError(f"target_tickers 含规范化后重复 ticker（一股一票）: {ct}")
        seen.add(ct)
        out.append(ct)
    return out


def _canonical_unique_list(seq, *, key):
    """Validate a producer identity-bearing list -> ordered list of canonical tickers; reject a
    non-exact-list / non-str / non-canonical / post-canonical DUPLICATE (never silently set-collapse)."""
    _require_exact_list(seq, name=f"momentum_result['{key}']")
    out, seen = [], set()
    for x in seq:
        ct = _canonical_ticker_strict(x, where=key)
        if ct in seen:
            raise MomentumSeamError(f"{key} 含规范化后重复 ticker（拒静默折叠、一股一态）: {ct}")
        seen.add(ct)
        out.append(ct)
    return out


def _assert_coverage_realizable(row_degrees, col_degrees):
    """momentum_block derives per-ticker n_present (row degrees) and per-sub_feature counts (column
    degrees) from ONE ticker×sub-feature incidence, so (a) Σ row == Σ col and (b) the two degree
    sequences must be jointly realizable as a binary incidence matrix (Gale-Ryser). A forged result that
    invents the two margins independently — with equal OR unequal totals — is rejected; the real
    producer's margins always come from a real incidence and are therefore always realizable."""
    total_row, total_col = sum(row_degrees), sum(col_degrees)
    if total_row != total_col:
        raise MomentumSeamError(
            f"coverage 边际不守恒：Σn_present {total_row} != Σsub_feature_coverage {total_col}")
    r = sorted(row_degrees, reverse=True)   # Gale-Ryser: rows desc; Σ top-k r_i <= Σ_j min(c_j, k)
    prefix = 0
    for k in range(1, len(r) + 1):
        prefix += r[k - 1]
        if prefix > sum(min(c, k) for c in col_degrees):
            raise MomentumSeamError(
                f"coverage 行/列度序列不可实现为二部 incidence 矩阵（Gale-Ryser 在 k={k} 失败）")


def _validate_producer_result(result):
    """Re-validate the momentum producer result as ONE coherent partition (do NOT trust the caller ran
    the real producer). Returns (scored:{ticker: float}, insufficient_history:set, insufficient_coverage:
    set). Fail-closed on every malformed shape / value / identity, on any partition contradiction, and on
    a cross-summary (row/column margin) incoherence."""
    _require_exact_dict(result, name="momentum_result")
    result_keys = _str_keys(result, name="momentum_result")
    if result_keys != set(_ACCEPTED_PRODUCER_KEYS):
        missing = sorted(set(_ACCEPTED_PRODUCER_KEYS) - result_keys)
        n_extra = len(result_keys - set(_ACCEPTED_PRODUCER_KEYS))
        raise MomentumSeamError(f"momentum_result 键集须恰为接受契约（缺 {missing} / 多 {n_extra} 个非法键）")

    min_coverage = _exact_int(result[_MIN_COVERAGE_KEY], min_value=1)
    if min_coverage is None or min_coverage > _MAX_SUBFEATURES:
        raise MomentumSeamError(
            f"min_coverage 须为 [1,{_MAX_SUBFEATURES}] 的精确 int: {type(result[_MIN_COVERAGE_KEY]).__name__}")

    # momentum_block: exact dict, canonical keys (dup->raise), EXACT-type finite [0,100] values.
    block = _require_exact_dict(result[_BLOCK_KEY], name=f"'{_BLOCK_KEY}'")
    scored: dict[str, float] = {}
    for k, v in block.items():
        ck = _canonical_ticker_strict(k, where=_BLOCK_KEY + " 键")
        if ck in scored:
            raise MomentumSeamError(f"{_BLOCK_KEY} 含规范化后重复 ticker: {ck}")
        fv = _finite_block_value(v)
        if fv is None:
            raise MomentumSeamError(
                f"{_BLOCK_KEY}[{ck}] 值须为 [0,100] 精确内建有限数（拒 bool/子类/串/NaN/Inf/越域）: {type(v).__name__}")
        scored[ck] = fv

    hist = set(_canonical_unique_list(result[_HIST_KEY], key=_HIST_KEY))
    cov = set(_canonical_unique_list(result[_COV_KEY], key=_COV_KEY))
    scored_set = set(scored)

    clash = (scored_set & hist) | (scored_set & cov) | (hist & cov)
    if clash:
        raise MomentumSeamError(
            f"momentum_result 自相矛盾：ticker 同时出现在多个 disposition 集（一票一态）: {sorted(clash)}")

    # coverage_matrix: exact dict, canonical keys (dup->raise), EXACT row shape {n_present:int, scored:bool}.
    matrix_raw = _require_exact_dict(result[_MATRIX_KEY], name=f"'{_MATRIX_KEY}'")
    matrix: dict[str, dict] = {}
    for k, row in matrix_raw.items():
        ck = _canonical_ticker_strict(k, where=_MATRIX_KEY + " 键")
        if ck in matrix:
            raise MomentumSeamError(f"{_MATRIX_KEY} 含规范化后重复 ticker: {ck}")
        _require_exact_dict(row, name=f"{_MATRIX_KEY}[{ck}] 行")
        if _str_keys(row, name=f"{_MATRIX_KEY}[{ck}] 行") != _COVERAGE_ROW_KEYS:
            raise MomentumSeamError(f"{_MATRIX_KEY}[{ck}] 行键须恰为 {sorted(_COVERAGE_ROW_KEYS)}")
        n_present = _exact_int(row[_N_PRESENT], min_value=0)
        if n_present is None or n_present > _MAX_SUBFEATURES:
            raise MomentumSeamError(
                f"{_MATRIX_KEY}[{ck}].n_present 须为 [0,{_MAX_SUBFEATURES}] 的精确 int: {type(row[_N_PRESENT]).__name__}")
        if type(row[_SCORED]) is not bool:
            raise MomentumSeamError(f"{_MATRIX_KEY}[{ck}].scored 须为 bool: {type(row[_SCORED]).__name__}")
        matrix[ck] = {_N_PRESENT: n_present, _SCORED: row[_SCORED]}

    union = scored_set | hist | cov
    if set(matrix.keys()) != union:
        missing = sorted(union - set(matrix))
        extra = sorted(set(matrix) - union)
        raise MomentumSeamError(
            f"{_MATRIX_KEY} 身份集须恰等于 scored∪history∪coverage（缺 {missing} / 多 {extra}）")

    # per-ticker partition consistency (the forged-coverage class): scored flag must equal the coverage
    # relation, and each disposition's n_present must match its defining band.
    for t, row in matrix.items():
        n, sc = row[_N_PRESENT], row[_SCORED]
        if sc != (n >= min_coverage):
            raise MomentumSeamError(
                f"{_MATRIX_KEY}[{t}].scored={sc} 与 (n_present {n} >= min_coverage {min_coverage}) 不一致")
        if t in scored_set:
            if n < min_coverage:
                raise MomentumSeamError(f"{t} 在 {_BLOCK_KEY} 但 n_present {n} < min_coverage {min_coverage}（矛盾）")
        elif t in hist:
            if n != 0:
                raise MomentumSeamError(f"{t} 在 {_HIST_KEY} 但 n_present {n} != 0（须无任何 sub-feature）")
        else:  # t in cov (union == matrix keys, sets disjoint -> t is in exactly one)
            if not (0 < n < min_coverage):
                raise MomentumSeamError(
                    f"{t} 在 {_COV_KEY} 但 n_present {n} 不在 (0, min_coverage {min_coverage})")

    # sub_feature_coverage: exact dict; keys == frozen universe; each count an exact int in [0, #identities].
    subfeat = _require_exact_dict(result[_SUBFEAT_KEY], name=f"'{_SUBFEAT_KEY}'")
    if _str_keys(subfeat, name=_SUBFEAT_KEY) != set(_SUB_FEATURE_UNIVERSE):
        raise MomentumSeamError(f"{_SUBFEAT_KEY} 键集须恰为冻结 sub_feature 宇宙 {list(_SUB_FEATURE_UNIVERSE)}")
    n_ident = len(union)
    for sf in _SUB_FEATURE_UNIVERSE:
        c = _exact_int(subfeat[sf], min_value=0)
        if c is None or c > n_ident:
            raise MomentumSeamError(f"{_SUBFEAT_KEY}[{sf}] 须为 [0,{n_ident}] 的精确 int: {type(subfeat[sf]).__name__}")

    # cross-summary coherence: row degrees (n_present) and column degrees (sub_feature counts) come from
    # ONE incidence -> equal totals + Gale-Ryser realizable (rejects independently-forged margins).
    _assert_coverage_realizable([matrix[t][_N_PRESENT] for t in matrix],
                                [subfeat[sf] for sf in _SUB_FEATURE_UNIVERSE])
    return scored, hist, cov


def project_momentum_block(momentum_result, target_tickers):
    """Project the full-pool momentum producer result onto the target ticker set (§4.2 momentum leg).

    momentum_result = engine/us_short_momentum.py::momentum_block(...) output (re-validated here as one
                      coherent partition, incl. cross-summary margin realizability).
    target_tickers  = the stocks being scored this run (Pass2-clean candidates + force-in holdings);
                      canonicalized under the single identity policy, one row per stock.

    For each target ticker: SCORED by the producer -> its 0-100 momentum block value; else
    (insufficient_history / insufficient_coverage / absent from the pool) -> neutral-fill (the composer
    omits the momentum block so core_score applies the §4.2 neutral-block rule — never a fabricated
    number). Returns:
        {"momentum_by_ticker": {ticker: 0-100 float},   # scored targets only
         "neutral_fill_tickers": [ticker, ...],          # targets to omit -> core_score neutral (target order)
         "coverage": {ticker: <disposition>},            # per-target §11.5 honesty (COVERAGE_DISPOSITIONS)
         "target_count": int, "scored_count": int}
    Raises MomentumSeamError on a malformed / self-contradictory / margin-incoherent producer result, an
    out-of-domain value, a non-canonical / duplicate identity, or any hostile public-boundary input
    (whole-class fail-closed; only MomentumSeamError escapes)."""
    targets = _canonical_unique_targets(target_tickers)
    scored, insuff_hist, insuff_cov = _validate_producer_result(momentum_result)

    momentum_by_ticker: dict[str, float] = {}
    neutral_fill: list[str] = []
    coverage: dict[str, str] = {}
    for t in targets:
        if t in scored:
            momentum_by_ticker[t] = scored[t]
            coverage[t] = DISPOSITION_SCORED
        else:
            neutral_fill.append(t)
            if t in insuff_hist:
                coverage[t] = DISPOSITION_INSUFFICIENT_HISTORY
            elif t in insuff_cov:
                coverage[t] = DISPOSITION_INSUFFICIENT_COVERAGE
            else:
                coverage[t] = DISPOSITION_ABSENT
    return {
        "momentum_by_ticker": momentum_by_ticker,
        "neutral_fill_tickers": neutral_fill,
        "coverage": coverage,
        "target_count": len(targets),
        "scored_count": len(momentum_by_ticker),
    }
