"""Tests for the A-short weekly pipeline (batch ②).

Covers normalize_candidate (EGS candidate → engine input mapping), build_weekly_report (per-stock
M6.7 envelope), validate_weekly_report (incl. the P2 consumer-validation: it MUST validate the IV
feed it consumed + every M6.7), write_weekly_report contract, latest_iv_percentile, IV-missing
propagation, and main() wiring with an injected price provider (no live Tushare). Synthetic inputs.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import jsonschema
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runners.a_short_weekly_pipeline import (  # noqa: E402
    normalize_candidate, build_weekly_report as _build_weekly_report, validate_weekly_report,
    write_weekly_report, latest_iv_percentile, latest_iv_hv, main, SCHEMA_PATH,
    _is_official_analysis_input_path,
    _fetch_price_series, _prev_trading_day, _load_validated_overlay, MIN_PRICE_OBS, resolve_market_regime,
    _candidate_price_clock, _candidate_price_exclusion,
    validate_account_state, stateful_risk_for_candidate, _ex_div_notices, _fetch_dividends,
    _build_exclusion_summary, _upcoming_events, _fetch_unlocks, _fetch_earnings_schedule, _attach_forward_event_impacts,
    FORWARD_EVENT_WINDOW_DAYS, _FORWARD_EVENT_SOURCE_ID, _FORWARD_EVENT_CONFIDENCE,
    _dragon_list_events, _fetch_dragon_list, _attach_dragon_list_impacts, _recent_trading_days,
    DRAGON_LIST_LOOKBACK_TRADING_DAYS, _DRAGON_LIST_EVIDENCE_VALUE, _DRAGON_LIST_MARKER,
    _fetch_dragon_inst, _sum_inst_net,
    _block_trade_events, _fetch_block_trade, _attach_block_trade_impacts,
    _fetch_daily_close, _attach_block_discount,
    _financial_trends, _fetch_forecast, _fetch_income, _fetch_balancesheet, _attach_financial_trend_impacts,
    _forecast_red_flags, _income_red_flags, _balancesheet_red_flags, _industry_fundamentals, _FIN_STATEMENT_MARKER,
    _attach_holding_disposition, _factor_comparison_realized_regime, _build_evidence_reminders,
)
from runners.a_short_account_state_from_manual_tables import _bundle_digest  # noqa: E402
from engine.a_short_runtime_config import (  # noqa: E402
    load_runtime_configuration, runtime_configuration_lineage,
)
from runners.a_short_phase5_engine import validate_operation_impact_no_dangling as _vop  # noqa: E402
from runners.a_short_m67_render import render_weekly_markdown, write_weekly_markdown  # noqa: E402
from runners.a_short_phase5_engine import _semantic_operation_impacts  # noqa: E402
from engine.a_short_rule6_contract import RULE6_CHECKS, RULE6_D_TIER_REASONS  # noqa: E402
from engine.a_short_delisting import _field, derive_delisting_flags  # noqa: E402
from runners.a_short_semantic_risk_summary import build_summary_from_fetches  # noqa: E402
from runners.a_short_theme_overlay_comparison import (  # noqa: E402
    assemble_overlay, build_summary,
)
import runners.a_short_weekly_pipeline as _weekly_pipeline_module  # noqa: E402

# Every main() call in this module uses an isolated synthetic ratchet. Tests must
# never discover, read, or update the user's gitignored private account state.
_TEST_RATCHET_DIR = tempfile.TemporaryDirectory()
_weekly_pipeline_module.HOLDING_RATCHET_DEFAULT_PATH = str(
    Path(_TEST_RATCHET_DIR.name) / "ratchet_state.json"
)

AS_OF = "20260609"
GEN = "2026-06-09T12:00:00+08:00"
M67_SCHEMA = ROOT / "schemas" / "a_short_m67_report.schema.json"
FIXT_AI = ROOT / "schemas" / "examples" / "analysis_input.example.json"
_DEFAULT_WEEKLY_BASELINE = None
_DEFAULT_WEEKLY_BUILDER = None
_MARGIN_CHECK_IDS = {"rule6_margin_extreme_accumulation", "rule6_short_selling_surge"}


def _complete_margin_coverage(reference_date=AS_OF):
    """Modern synthetic inputs must explicitly opt into a complete margin source."""
    return {"reference_date": reference_date, "effective_ref_date": reference_date,
            "row_count": 1200, "universe_size": 1100,
            "coverage_complete": True, "status": "complete"}


def build_weekly_report(*args, **kwargs):
    """Keep ordinary synthetic weekly inputs source-complete; outage tests pass None explicitly."""
    kwargs.setdefault("margin_coverage", _complete_margin_coverage())
    return _build_weekly_report(*args, **kwargs)


def _analysis_input(trade_date=AS_OF, candidates=None):
    """Schema+PIT-valid analysis_input envelope (from the repo example) with our candidates."""
    base = json.loads(FIXT_AI.read_text(encoding="utf-8"))
    base["trade_date"] = trade_date
    src = base.get("source") or {}
    src["runtime_configuration"] = runtime_configuration_lineage(load_runtime_configuration())
    if src.get("l3_mode") == "pit":               # keep PIT invariant: snapshot <= trade_date
        src["l3_snapshot_date"] = trade_date
    if candidates is not None:
        base["candidates"] = candidates
    return base


def _series():
    # mirrors the engine test fixture: day12 carries support 2.87 + resistance 3.10; day13 ALSO highs 3.10 so
    # #6 effective_resistance corroborates it (strong, not a single-day spike) → t1=3.10 → build RR still passes.
    s = []
    for i in range(30):
        if i == 12:
            s.append({"high": 3.10, "low": 2.87, "close": 2.90})
        elif i == 13:
            s.append({"high": 3.10, "low": 2.88, "close": 2.90})   # #6:次日背书近20日高 → resistance strong(否则 3.10 被判单日插针)
        else:
            s.append({"high": 2.92, "low": 2.88, "close": 2.90})
    return s


def _egs_candidate(ts_code="600000.SH", **over):
    # mirrors the REAL egs_main analysis_input contract (derived_flags.is_lock / hard_veto;
    # event_risk.suspension.is_suspended) — NOT the engine-input shape.
    cand = {
        "ts_code": ts_code, "name": "测试",
        "analysis_role": "final",
        "quote": {"close": 2.90},
        "scores": {"esp_score": 60, "l4_score": 70},
        "liquidity": {"avg_amount_5d": 2e8, "avg_amount_20d": 2e8},
        "derived_flags": {"chasing_high": False, "overheat_flag": False, "has_crash_veto": False,
                          "is_lock": False, "is_breakout": False, "m4_review_required": None,
                          "hard_veto": False},
        "event_risk": {"holder_reduction": {"active_plan": False},
                       "suspension": {"is_suspended": False},
                       "delisting": {"st_flag": False, "delisting_warning": False},
                       "rule6_checks": [
                           {"id": check_id, "group": group,
                            "status": "not_applicable" if check_id in RULE6_D_TIER_REASONS else "pass",
                            "notes": RULE6_D_TIER_REASONS.get(check_id)}
                           for check_id, group in RULE6_CHECKS
                       ]},
    }
    cand.update(over)
    return cand


_EXAMPLE_CAND = json.loads(FIXT_AI.read_text(encoding="utf-8"))["candidates"][0]


def _ai_candidate(ts_code="600000.SH", close=2.90, is_lock=False, suspended=False,
                  hard_veto=False, active_plan=False):
    """Full schema-valid candidate (deep-copied from the repo example), leaf-overridden.
    close defaults to 2.90 to align with the injected `_series()` support (低吸→建仓 path)."""
    c = copy.deepcopy(_EXAMPLE_CAND)
    c["ts_code"] = ts_code
    c["analysis_role"] = "final"
    c["quote"]["close"] = close
    c["derived_flags"]["is_lock"] = is_lock
    c["derived_flags"]["hard_veto"] = hard_veto
    c["event_risk"]["suspension"]["is_suspended"] = suspended
    c["event_risk"]["holder_reduction"]["active_plan"] = active_plan
    return c


def _overlay_row(eligible=True, crowding=False):
    return {"eligible": eligible, "crowding_hit": crowding}


def _account():
    return {
        "schema_name": "a_short_account_state",
        "schema_version": "1.0.0",
        "as_of": AS_OF,
        "available_cash": 500000.0,
        "total_equity": 1000000.0,
        "current_gross_exposure": 0.0,
        "positions": [],
        "rule12": {
            "status": "inactive",
            "reason": None,
            "triggered_at": None,
            "cooldown_until": None,
            "recovery_position_multiplier": None,
            "consecutive_stop_losses_window": 0,
            "drawdown_pct": 0.0,
            "iv_change_abs_1d_pctpt": 0.0,
        },
        "rule13_cooldowns": [],
        "manual_order_only": True,
        "broker_connection_allowed": False,
    }


def _account_bundle(account=None, decision_as_of=AS_OF):
    account = copy.deepcopy(account or _account())
    facts_as_of = account["as_of"]
    lineage = {
        "schema_name": "a_short_account_state_lineage", "schema_version": "1.0.0",
        "generated_at": None, "decision_as_of": decision_as_of, "facts_as_of": facts_as_of,
        "facts_staleness": ("current" if facts_as_of == decision_as_of else "stale_warning"),
        "config": {"rule13_cooldown_calendar_days": 5,
                   "rule13_default_max_reentry_position_pct": 0.5,
                   "rule12_default_recovery_position_multiplier": 0.5},
        "source_tables": [], "rule12": {"source": "excel_portfolio_rule12", "progressed": None},
        "rule13_cooldowns": [], "consistency_warnings": [],
    }
    digest = _bundle_digest(account, lineage)
    return {"schema_name": "a_short_account_bundle", "schema_version": "1.0.0",
            "decision_as_of": decision_as_of, "facts_as_of": facts_as_of,
            "snapshot_id": f"a-short-account-{facts_as_of}-{digest[:16]}",
            "snapshot_digest": digest, "account": account, "lineage": lineage}


def _write_account(path, account=None, decision_as_of=AS_OF):
    Path(path).write_text(json.dumps(_account_bundle(account, decision_as_of)), encoding="utf-8")


def _feed(last_pct=55.0):
    series = [{"trade_date": d, "iv_value": 0.15 + 0.001 * i,
               "iv_percentile_252d": (last_pct if i == 4 else 40.0),
               "hv_value": 0.14 + 0.001 * i}
              for i, d in enumerate(["20260601", "20260602", "20260603", "20260604", AS_OF])]
    return {"as_of": AS_OF, "n_days": len(series), "series": series}


def _valid_overlay_for(codes, as_of=AS_OF):
    """Schema + consistency valid overlay summary for an arbitrary candidate set (Slice A builders)."""
    pool = pd.DataFrame([
        {"ts_code": c, "baseline_rank": i + 1, "esp_score": 60.0 - i, "l4_score": 70.0,
         "overheat_flag": False, "chasing_high": False, "chase_flag": False, "high_pos_shrink": False}
        for i, c in enumerate(codes)])
    theme_heat = {"score": {c: 90.0 - i for i, c in enumerate(codes)},
                  "best_concept": {c: "c1" for c in codes}}
    industry_heat_by_l2 = {"半导体": 95.0, "银行": 20.0}
    sw_l2_by_code = {c: "半导体" for c in codes}
    breadth = {c: {"up_frac": 0.8, "vol_frac": 0.6, "pass": True} for c in codes}
    persistence = {c: 1.0 for c in codes}
    fit = {c: 0.8 for c in codes}
    assembled = assemble_overlay(pool, theme_heat, industry_heat_by_l2, breadth,
                                 persistence, fit, sw_l2_by_code)
    return build_summary(assembled, as_of=as_of,
                         pit_source={"concept_membership": "pit", "sw_mapping": "forward"},
                         dropped_at_l0_l5=[], generated_at="2026-06-10T00:00:00+08:00")


def _valid_overlay(as_of=AS_OF):
    """Schema + consistency valid overlay covering exactly the default weekly pool."""
    return _valid_overlay_for(["600000.SH", "000001.SZ"], as_of)


def _normalized(ts_code="600000.SH", iv_pct=55.0, **cand_over):
    normalized = normalize_candidate(_egs_candidate(ts_code, **cand_over), _series(),
                                     _overlay_row(), iv_pct, {"available_cash": 500000.0}, "震荡期")
    normalized["margin_coverage"] = _complete_margin_coverage()
    normalized["price_data_through"] = AS_OF
    for check in normalized.get("rule6_checks") or []:
        if check.get("id") in _MARGIN_CHECK_IDS:
            check["metrics"] = {"status": "complete"}
    return normalized


def _weekly(normalized_list=None, iv_feed_ref="iv_feed.json"):
    global _DEFAULT_WEEKLY_BASELINE, _DEFAULT_WEEKLY_BUILDER
    if normalized_list is None and iv_feed_ref == "iv_feed.json":
        if _DEFAULT_WEEKLY_BASELINE is None or _DEFAULT_WEEKLY_BUILDER is not build_weekly_report:
            _DEFAULT_WEEKLY_BASELINE = build_weekly_report([_normalized()], AS_OF, GEN,
                                                           iv_feed_ref=iv_feed_ref)
            _DEFAULT_WEEKLY_BUILDER = build_weekly_report
        return copy.deepcopy(_DEFAULT_WEEKLY_BASELINE)
    nl = normalized_list if normalized_list is not None else [_normalized()]
    return build_weekly_report(nl, AS_OF, GEN, iv_feed_ref=iv_feed_ref)


def _sized_lineage():
    # (provided, sized) run_lineage —— 带账户定量的合法 lineage(配 available_cash>0 用,过 #3 双向不变式)。
    return {"analysis_input": "ai.json", "selection_bucket": "bucket", "iv_feed": "iv_feed.json",
            "account_ref": "acct.json", "account_status": "provided", "sizing_mode": "sized",
            "account_snapshot": {"snapshot_id": "a-short-account-20260609-0123456789abcdef",
                                 "snapshot_digest": "0" * 64, "facts_as_of": AS_OF,
                                 "decision_as_of": AS_OF, "positions_count": 0,
                                 "integrity_status": "clear", "blocking_kinds": [], "blocking_count": 0},
            "price_freshness": {"mode": "strict_as_of", "run_date": None,
                                "accepted_prior_settled_date": None, "price_data_through": AS_OF}}


class NormalizeTests(unittest.TestCase):
    def test_one_click_analysis_input_path_is_the_strict_official_lane(self):
        self.assertTrue(_is_official_analysis_input_path(
            ROOT / "result" / "a_short" / AS_OF / "analysis_input.json"
        ))
        self.assertFalse(_is_official_analysis_input_path(ROOT / "research" / "ai.json"))

    def test_missing_delisting_text_fails_closed_into_phase5_veto(self):
        for value in (pd.NA, np.nan, None, "<NA>", "nan", "NaN", "None", "NaT", "null"):
            self.assertEqual(_field({"name": value}, "name"), "")
        self.assertEqual(_field({"name": "正常名称"}, "name"), "正常名称")
        flags = derive_delisting_flags({"name": pd.NA, "list_status": "L"})
        candidate = _egs_candidate(event_risk={
            "holder_reduction": {"active_plan": False},
            "suspension": {"is_suspended": False},
            "delisting": flags,
        })
        normalized = normalize_candidate(candidate, _series(), _overlay_row(), 55.0, {}, "震荡期")
        self.assertTrue(normalized["event"]["st_or_delisting"])

    def test_maps_egs_fields(self):
        n = _normalized()
        self.assertEqual(n["close"], 2.90)
        self.assertEqual(n["analysis_role"], "final")
        self.assertEqual(n["esp_score"], 60)
        self.assertTrue(n["overlay"]["eligible"])
        self.assertEqual(n["iv"]["iv_percentile_252d"], 55.0)
        self.assertEqual(n["liquidity"]["avg_amount_5d"], 2e8)
        self.assertEqual(n["market_regime"], "震荡期")

    def test_candidate_close_uses_the_same_latest_bar_as_its_indicators(self):
        candidate = _egs_candidate(quote={"close": 1.23})
        series = _series()
        series[-1]["close"] = 3.21

        normalized = normalize_candidate(candidate, series, _overlay_row(), 55.0, {}, "震荡期")

        self.assertEqual(normalized["close"], 3.21)

    def test_maps_event_and_derived_flags(self):
        n = normalize_candidate(
            _egs_candidate(derived_flags={"overheat_flag": True, "chasing_high": False,
                                          "has_crash_veto": False, "is_lock": False,
                                          "is_breakout": False, "hard_veto": False},
                           event_risk={"holder_reduction": {"active_plan": True},
                                       "suspension": {"is_suspended": False},
                                       "delisting": {"st_flag": True, "delisting_warning": False}}),
            _series(), _overlay_row(), 55.0, {}, "震荡期")
        self.assertTrue(n["derived"]["overheat"])
        self.assertTrue(n["event"]["holder_reduction_active"])
        self.assertTrue(n["event"]["st_or_delisting"])

    def test_unknown_delisting_field_fails_closed_into_phase5_veto(self):
        candidate = _egs_candidate(
            event_risk={
                "holder_reduction": {"active_plan": False},
                "suspension": {"is_suspended": False},
                "delisting": {"st_flag": False, "delisting_warning": None},
            }
        )
        n = normalize_candidate(candidate, _series(), _overlay_row(), 55.0, {}, "震荡期")
        self.assertTrue(n["event"]["st_or_delisting"])
        from runners.a_short_phase5_engine import build_m67_report
        report = build_m67_report(n, AS_OF, GEN)
        self.assertEqual(report["m67"]["table"]["操作"], "否决")

    def test_stage3_large_unlock_watch_cannot_reenter_as_a_new_entry(self):
        candidate = _egs_candidate(analysis_role="watch")
        candidate["event_risk"]["unlock"] = {"large_unlock_flag": True}
        n = normalize_candidate(candidate, _series(), _overlay_row(), 55.0,
                                {"available_cash": 500000.0}, "震荡期")
        from runners.a_short_phase5_engine import build_m67_report
        report = build_m67_report(n, AS_OF, GEN)
        self.assertEqual(report["m67"]["table"]["操作"], "观察")
        self.assertIn("非 final，仅观察", report["machine"]["entry_exit_size_star"]["reject_reason"])

    def test_maps_rule6_checks_and_materializes_only_iv_from_validated_feed(self):
        cand = _egs_candidate()
        original = cand["event_risk"]["rule6_checks"]
        n = normalize_candidate(cand, _series(), _overlay_row(), 55.0, {}, "震荡期")
        by_id = {check["id"]: check for check in n["rule6_checks"]}
        original_by_id = {check["id"]: check for check in original}
        self.assertEqual(by_id["rule6_50etf_iv"]["status"], "pass")
        self.assertEqual(by_id["rule6_50etf_iv"]["metrics"]["iv_percentile_252d"], 55.0)
        for check_id, check in original_by_id.items():
            if check_id != "rule6_50etf_iv":
                self.assertEqual(by_id[check_id], check)

    def test_maps_real_egs_hard_risk_contract_fields(self):
        # R-ASHORT-WEEKLY-EGS-HARD-RISK-MAPPING-GAP: real keys is_lock / suspension.is_suspended /
        # hard_veto must reach the engine hard-risk inputs (not the wrong limit_locked/suspended keys).
        n = normalize_candidate(
            _egs_candidate(derived_flags={"chasing_high": False, "overheat_flag": False,
                                          "has_crash_veto": False, "is_lock": True,
                                          "is_breakout": False, "hard_veto": True},
                           event_risk={"holder_reduction": {"active_plan": False},
                                       "suspension": {"is_suspended": True},
                                       "delisting": {"st_flag": False, "delisting_warning": False}}),
            _series(), _overlay_row(), 55.0, {}, "震荡期")
        self.assertTrue(n["derived"]["limit_locked"])
        self.assertTrue(n["derived"]["suspended"])
        self.assertTrue(n["derived"]["hard_veto"])

    def test_missing_overlay_defaults_false(self):
        n = normalize_candidate(_egs_candidate(), _series(), None, 55.0, {}, "震荡期")
        self.assertFalse(n["overlay"]["eligible"])
        self.assertFalse(n["overlay"]["crowding_hit"])

    def test_maps_vol_confirm(self):
        # vol_confirm now flows from EGS derived_flags → engine breakout entry (no longer dormant).
        n = normalize_candidate(
            _egs_candidate(derived_flags={"chasing_high": False, "overheat_flag": False,
                                          "has_crash_veto": False, "is_lock": False,
                                          "is_breakout": True, "vol_confirm": True, "hard_veto": False}),
            _series(), _overlay_row(), 55.0, {}, "震荡期")
        self.assertTrue(n["derived"]["vol_confirm"])
        self.assertTrue(n["derived"]["breakout"])

    def test_regime_fallback_flows_to_engine_input(self):
        n = normalize_candidate(_egs_candidate(), _series(), _overlay_row(), 55.0, {},
                                "震荡期", regime_fallback={"active": True, "reason": "x"})
        self.assertTrue(n["regime_fallback"]["active"])


class AccountStateTests(unittest.TestCase):
    def test_validate_account_state_accepts_contract_shape(self):
        acct = validate_account_state(copy.deepcopy(_account()), AS_OF)
        self.assertEqual(acct["available_cash"], 500000.0)

    def test_validate_account_state_rejects_duplicate_positions(self):
        acct = copy.deepcopy(_account())
        pos = {"ts_code": "600000.SH", "name": "测试", "shares": 1000,
               "avg_cost": 2.70, "entry_date": "20260601", "stop_loss": 2.55}
        acct["positions"] = [copy.deepcopy(pos), copy.deepcopy(pos)]
        with self.assertRaises(SystemExit):
            validate_account_state(acct, AS_OF)

    def test_validate_account_state_rejects_stale_rule12_active(self):
        acct = copy.deepcopy(_account())
        acct["rule12"] = {"status": "active_cooldown", "cooldown_until": "20260608"}
        with self.assertRaises(SystemExit):
            validate_account_state(acct, AS_OF)

    def test_stateful_risk_maps_held_position(self):
        acct = copy.deepcopy(_account())
        acct["positions"] = [{"ts_code": "600000.SH", "name": "测试", "shares": 1000,
                              "avg_cost": 2.70, "entry_date": "20260601", "stop_loss": 2.55}]
        ctx = stateful_risk_for_candidate(acct, "600000.SH", AS_OF)
        self.assertEqual(ctx["position_state"], "held")
        self.assertEqual(ctx["position"]["avg_cost"], 2.70)

    def test_stateful_risk_maps_rule13_cooldown(self):
        acct = copy.deepcopy(_account())
        acct["rule13_cooldowns"] = [{
            "ts_code": "600000.SH",
            "status": "active_cooldown",
            "exit_date": "20260608",
            "cooldown_until": "20260610",
            "requires_new_catalyst": True,
            "new_catalyst_confirmed": False,
            "requires_m4_recheck": True,
            "m4_recheck_passed": False,
            "max_reentry_position_pct": 0.5,
        }]
        ctx = stateful_risk_for_candidate(acct, "600000.SH", AS_OF)
        self.assertEqual(ctx["position_state"], "flat")
        self.assertTrue(ctx["rule13"]["reentry_blocked"])


class BuildWeeklyTests(unittest.TestCase):
    def test_default_weekly_fixture_is_cached_and_isolated(self):
        global _DEFAULT_WEEKLY_BASELINE, _DEFAULT_WEEKLY_BUILDER
        _DEFAULT_WEEKLY_BASELINE = None
        _DEFAULT_WEEKLY_BUILDER = None
        with patch(f"{__name__}.build_weekly_report", wraps=build_weekly_report) as build:
            first = _weekly()
            first["reports"][0]["ts_code"] = "poison"
            second = _weekly()
        self.assertEqual(build.call_count, 1)
        self.assertEqual(second["reports"][0]["ts_code"], "600000.SH")

    def test_default_weekly_fixture_rebuilds_for_a_patched_builder(self):
        global _DEFAULT_WEEKLY_BASELINE, _DEFAULT_WEEKLY_BUILDER
        _DEFAULT_WEEKLY_BASELINE = None
        _DEFAULT_WEEKLY_BUILDER = None
        _weekly()
        with patch(f"{__name__}.build_weekly_report", wraps=build_weekly_report) as build:
            _weekly()
        self.assertEqual(build.call_count, 1)

    def test_envelope(self):
        w = _weekly([_normalized("600000.SH"), _normalized("000001.SZ")])
        self.assertEqual(w["schema_name"], "a_short_weekly_report")
        self.assertEqual(w["n_stocks"], 2)
        self.assertEqual(len(w["reports"]), 2)
        self.assertTrue(all(v is False for v in w["boundary"].values()))

    def test_buildable_candidate_yields_jiacang(self):
        w = _weekly([_normalized()])
        self.assertEqual(w["reports"][0]["m67"]["table"]["操作"], "建仓")

    def test_hard_veto_candidate_yields_fouju_null_trade(self):
        n = _normalized(event_risk={"holder_reduction": {"active_plan": True},
                                    "suspension": {"is_suspended": False},
                                    "delisting": {"st_flag": False, "delisting_warning": False}})
        rep = _weekly([n])["reports"][0]
        self.assertEqual(rep["m67"]["table"]["操作"], "否决")
        for k in ("股数", "入", "盈一", "盈二", "损"):
            self.assertIsNone(rep["m67"]["table"][k])

    def test_real_egs_hard_risk_fields_cannot_become_jiacang(self):
        # actual-analysis-input-shape: is_lock / suspension.is_suspended / hard_veto each → not 建仓.
        def _df(**kw):
            base = {"chasing_high": False, "overheat_flag": False, "has_crash_veto": False,
                    "is_lock": False, "is_breakout": False, "hard_veto": False}
            base.update(kw)
            return base
        cases = [
            {"derived_flags": _df(is_lock=True)},
            {"derived_flags": _df(hard_veto=True)},
            {"event_risk": {"holder_reduction": {"active_plan": False},
                            "suspension": {"is_suspended": True},
                            "delisting": {"st_flag": False, "delisting_warning": False}}},
        ]
        for over in cases:
            rep = _weekly([_normalized(**over)])["reports"][0]
            self.assertNotEqual(rep["m67"]["table"]["操作"], "建仓", over)

    def test_account_position_coverage_rejects_missing_output_landing(self):
        with self.assertRaises(ValueError):
            build_weekly_report([_normalized("600000.SH")], AS_OF, GEN,
                                account_positions=[{"ts_code": "600001.SH"}])


class ValidateWeeklyTests(unittest.TestCase):
    def test_good_passes(self):
        validate_weekly_report(_weekly(), _feed())  # no raise

    def test_consumer_validates_iv_feed_p2(self):
        # P2: the pipeline MUST validate the feed it consumed → a corrupt feed is caught here.
        bad_feed = _feed()
        bad_feed["series"][0]["iv_value"] = -1.0
        with self.assertRaises(ValueError):
            validate_weekly_report(_weekly(), bad_feed)

    def test_rejects_future_dated_feed(self):
        bad_feed = _feed()
        bad_feed["series"][-1]["trade_date"] = "20260631"  # invalid calendar
        with self.assertRaises(ValueError):
            validate_weekly_report(_weekly(), bad_feed)

    def test_rejects_feed_as_of_after_weekly_as_of(self):
        # R-ASHORT-WEEKLY-IV-FEED-PIT-CROSS-ASOF: feed from after the weekly run = future IV.
        future = {"as_of": "20260612", "n_days": 1,
                  "series": [{"trade_date": "20260612", "iv_value": 0.15, "iv_percentile_252d": 50.0}]}
        with self.assertRaises(ValueError):
            validate_weekly_report(_weekly(), future)  # weekly as_of = 20260609

    def test_rejects_n_stocks_mismatch(self):
        w = _weekly()
        w["n_stocks"] = 99
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_rejects_report_as_of_mismatch(self):
        w = _weekly()
        w["reports"][0]["as_of"] = "20260101"
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_rejects_duplicate_ts_code(self):
        w = _weekly([_normalized("600000.SH"), _normalized("600000.SH")])
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_rejects_manual_review_duplicate_report_landing(self):
        w = _weekly()
        w["holdings_manual_review"] = [{"ts_code": "600000.SH", "name": "测试", "reason": "无价"}]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_rejects_boundary_not_all_false(self):
        w = _weekly()
        w["boundary"]["production"] = True
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_rejects_run_lineage_status_mode_mismatch(self):
        # #1 hardening: (account_status, sizing_mode) is a STRICT bijection. A contradictory pair must not
        # pass, else a mislabeled lineage could let a sizing-less 观察 read as account-backed (or vice versa).
        # Both off-diagonal pairings must raise — incl. (provided, observation_only_no_account), which the
        # prior two-rule check let through.
        for acct_st, size_md in [("provided", "observation_only_no_account"), ("absent", "sized")]:
            w = _weekly()
            w["run_lineage"]["account_status"] = acct_st
            w["run_lineage"]["sizing_mode"] = size_md
            with self.assertRaises(ValueError):
                validate_weekly_report(w, _feed())


class WriteWeeklyTests(unittest.TestCase):
    def test_write_roundtrip(self):
        w = _weekly()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "weekly.json"
            write_weekly_report(w, _feed(), str(out))
            loaded = json.loads(out.read_text(encoding="utf-8"))
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            jsonschema.validate(loaded, json.load(f))
        self.assertEqual(loaded["n_stocks"], 1)

    def test_write_rejects_tampered_report(self):
        w = _weekly()
        # tamper a 建仓 report's table to drift from machine plan → per-report m67 consistency fails
        w["reports"][0]["m67"]["table"]["入"] = 999.0
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "weekly.json"
            with self.assertRaises((ValueError, jsonschema.ValidationError)):
                write_weekly_report(w, _feed(), str(out))
            self.assertFalse(out.exists())

    def test_write_rejects_production_output_path(self):
        # R-ASHORT-WEEKLY-OFFICIAL-OUTPUT-PATH-BOUNDARY: never write result/a_short/<date>.
        w = _weekly()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "result" / "a_short" / "20260609" / "weekly.json"
            with self.assertRaises(ValueError):
                write_weekly_report(w, _feed(), str(out))
            self.assertFalse(out.exists())

    def test_write_rejects_noncalendar_as_of_even_empty(self):
        # Fifth-knife PIT clock guard: reject before an invalid envelope exists.
        with self.assertRaisesRegex(ValueError, "price_data_through is not a valid PIT clock"):
            build_weekly_report([], "20260631", GEN, iv_feed_ref="f")

    def test_write_rejects_noncalendar_as_of_even_empty_envelope(self):
        # R-ASHORT-WEEKLY-WRITE-ASOF-CALENDAR-GAP: the sanctioned writer
        # must still reject a malformed but otherwise valid empty envelope.
        # `decision_as_of` is a TOP-LEVEL envelope field, not a run_lineage
        # one; setting the lineage copy leaves the top-level value stale and
        # trips the neighbouring decision-consistency guard instead.  The
        # message is pinned so this test cannot silently drift again.
        weekly = _weekly([])
        weekly["as_of"] = "20260631"
        weekly["decision_as_of"] = "20260631"
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "weekly.json"
            with self.assertRaisesRegex(ValueError, "非合法日历日期"):
                write_weekly_report(weekly, _feed(), str(out))
            self.assertFalse(out.exists())


class IVMissingTests(unittest.TestCase):
    def test_latest_iv_percentile(self):
        self.assertEqual(latest_iv_percentile(_feed(last_pct=67.0)), 67.0)
        self.assertIsNone(latest_iv_percentile({"series": []}))

    def test_latest_iv_hv(self):
        iv_v, hv_v = latest_iv_hv(_feed())
        self.assertAlmostEqual(iv_v, 0.154, places=6)      # i=4: 0.15+0.004
        self.assertAlmostEqual(hv_v, 0.144, places=6)      # i=4: 0.14+0.004
        self.assertEqual(latest_iv_hv({"series": []}), (None, None))
        self.assertEqual(latest_iv_hv({}), (None, None))

    def test_normalize_threads_iv_value_hv_value(self):
        n = normalize_candidate(_egs_candidate(), _series(), None, 55.0, {}, "震荡期",
                                iv_value=0.30, hv_value=0.20)
        self.assertEqual(n["iv"]["iv_value"], 0.30)
        self.assertEqual(n["iv"]["hv_value"], 0.20)
        self.assertEqual(n["iv"]["iv_percentile_252d"], 55.0)

    def test_iv_hv_surfaces_in_weekly_m67(self):
        # 端到端:feed 的 iv_value/hv_value → normalize → 引擎 M6.7 波动率状态含 IV/HV 标签
        n = normalize_candidate(_egs_candidate(), _series(), None, 55.0, {}, "震荡期",
                                iv_value=0.30, hv_value=0.20)
        rep = _weekly([n])["reports"][0]
        self.assertIn("IV/HV", rep["m67"]["精简结论区"]["波动率状态"])
        self.assertEqual(rep["machine"]["iv_gate"]["iv_hv_regime"], "iv_rich")

    def test_iv_missing_propagates_observe_only(self):
        n = _normalized(iv_pct=None)
        rep = _weekly([n])["reports"][0]
        self.assertEqual(rep["machine"]["iv_gate"]["status"], "observe_only_missing_feed")
        self.assertIn("IV未知", rep["m67"]["精简结论区"]["波动率状态"])


class MainWiringTests(unittest.TestCase):
    def _write_inputs(self, td, feed=None, ai=None):
        ai = ai if ai is not None else _analysis_input(
            candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
        (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
        (Path(td) / "feed.json").write_text(json.dumps(feed or _feed()), encoding="utf-8")
        _write_account(Path(td) / "acct.json")

    def test_main_rejects_truncated_crash_veto_summary_without_payload_text(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            bad = Path(td) / "crash-veto.json"
            bad.write_text('{"ticker": "600000.SH",', encoding="utf-8")
            with self.assertRaisesRegex(
                SystemExit, "invalid/stale --crash-veto-summary: JSONDecodeError"
            ) as exc:
                main([
                    "--as-of", AS_OF,
                    "--analysis-input", str(Path(td) / "ai.json"),
                    "--iv-feed", str(Path(td) / "feed.json"),
                    "--account", str(Path(td) / "acct.json"),
                    "--crash-veto-summary", str(bad),
                    "--out", str(Path(td) / "weekly.json"),
                ], price_provider=lambda code: _series())
        self.assertNotIn("600000.SH", str(exc.exception))

    def test_main_rejects_truncated_iv_feed_without_payload_text(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            bad = Path(td) / "feed.json"
            bad.write_text('{"ticker": "000001.SZ",', encoding="utf-8")
            with self.assertRaisesRegex(
                SystemExit, "invalid/stale --iv-feed: JSONDecodeError"
            ) as exc:
                main([
                    "--as-of", AS_OF,
                    "--analysis-input", str(Path(td) / "ai.json"),
                    "--iv-feed", str(bad),
                    "--account", str(Path(td) / "acct.json"),
                    "--out", str(Path(td) / "weekly.json"),
                ], price_provider=lambda code: _series())
        self.assertNotIn("000001.SZ", str(exc.exception))

    # R-ASHORT-WEEKLY-MAIN-PARSE-EXIT-RESIDUAL-THREE-SITES: the three named sites used to omit
    # UnicodeDecodeError, so an invalid-UTF-8 input escaped as a bare exception.  One reverse
    # control each; the positive controls are the existing valid-input tests in this class.
    _INVALID_UTF8 = b'{"schema_name": "\xff\xfe", "ts_code": "600000.SH"}'

    def test_main_rejects_invalid_utf8_regulatory_confirmations_without_path_or_payload(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            bad = Path(td) / "reg-confirm.json"
            bad.write_bytes(self._INVALID_UTF8)
            with self.assertRaisesRegex(
                SystemExit, "invalid/stale --regulatory-confirmations: UnicodeDecodeError"
            ) as exc:
                main([
                    "--as-of", AS_OF,
                    "--analysis-input", str(Path(td) / "ai.json"),
                    "--iv-feed", str(Path(td) / "feed.json"),
                    "--account", str(Path(td) / "acct.json"),
                    "--regulatory-confirmations", str(bad),
                    "--out", str(Path(td) / "weekly.json"),
                ], price_provider=lambda code: _series())
        message = str(exc.exception)
        self.assertNotIn(str(bad), message)
        self.assertNotIn("600000.SH", message)

    def test_main_rejects_invalid_utf8_holding_regulatory_confirmations_without_path_or_payload(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            bad = Path(td) / "holding-reg-confirm.json"
            bad.write_bytes(self._INVALID_UTF8)
            with self.assertRaisesRegex(
                SystemExit, "invalid/stale --holding-regulatory-confirmations: UnicodeDecodeError"
            ) as exc:
                main([
                    "--as-of", AS_OF,
                    "--analysis-input", str(Path(td) / "ai.json"),
                    "--iv-feed", str(Path(td) / "feed.json"),
                    "--account", str(Path(td) / "acct.json"),
                    "--holding-regulatory-confirmations", str(bad),
                    "--out", str(Path(td) / "weekly.json"),
                ], price_provider=lambda code: _series())
        message = str(exc.exception)
        self.assertNotIn(str(bad), message)
        self.assertNotIn("600000.SH", message)

    def test_load_account_bundle_rejects_invalid_utf8_without_leaking_the_private_path(self):
        from runners.a_short_weekly_pipeline import load_account_bundle
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "private-account-bundle.json"
            bad.write_bytes(self._INVALID_UTF8)
            with self.assertRaisesRegex(SystemExit, "UnicodeDecodeError") as exc:
                load_account_bundle(str(bad), AS_OF)
        message = str(exc.exception)
        # The whole point of this site: an OSError/decode failure must not print where the
        # operator's account state lives.
        self.assertNotIn(str(bad), message)
        self.assertNotIn("private-account-bundle", message)

    def test_load_account_bundle_oserror_message_carries_no_private_path(self):
        # The `{exc}` interpolation this repair removed: OSError stringifies WITH the filename,
        # so an unreadable/missing bundle used to print the private account-state path.
        from runners.a_short_weekly_pipeline import load_account_bundle
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "private-account-bundle.json"
            with self.assertRaisesRegex(SystemExit, "FileNotFoundError") as exc:
                load_account_bundle(str(missing), AS_OF)
        message = str(exc.exception)
        self.assertNotIn(str(missing), message)
        self.assertNotIn("private-account-bundle", message)

    def test_main_accepts_only_current_digest_bound_regulatory_confirmation(self):
        from engine.a_short_regulatory_advisory import event_fingerprint
        from engine.data.analysis_input_contract import build_a_short_run_identity

        ai = _analysis_input(candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
        event = {"source": "cninfo", "title": "official notice", "category": "regulatory",
                 "disclosure_date": AS_OF, "url_or_pdf": "https://example.invalid/notice.pdf",
                 "risk_type": "investigation", "severity": "high"}
        fingerprint = event_fingerprint("600000.SH", event)
        confirmation = {
            "schema_name": "a_short_regulatory_advisory_confirmation",
            "schema_version": "1.0.0",
            "as_of": AS_OF,
            "candidate_digest": build_a_short_run_identity(AS_OF, ai["candidates"])["candidate_digest"],
            "confirmations": [{"ts_code": "600000.SH", "event_fingerprint": fingerprint,
                               "decision": "confirmed_material",
                               "reviewed_at": "2026-06-09T09:30:00+08:00",
                               "note": "Official notice checked manually."}],
            "boundary": {"advisory_only": True, "modifies_egs_or_rule6": False, "automates_order": False},
        }
        semantic = lambda code: ({"status": "risk", "had_pit_announcements": True, "events": [event]}
                                 if code == "600000.SH" else None)
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td, ai=ai)
            confirmation_path = Path(td) / "regulatory-confirmation.json"
            confirmation_path.write_text(json.dumps(confirmation), encoding="utf-8")
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out), "--regulatory-confirmations", str(confirmation_path)],
                 price_provider=lambda code: _series(), semantic_provider=semantic)
            weekly = json.loads(out.read_text(encoding="utf-8"))
        report = {row["ts_code"]: row for row in weekly["reports"]}["600000.SH"]
        self.assertEqual(report["machine"]["layer"]["semantic_risk"]["regulatory_confirmation"]["status"],
                         "confirmed_material")
        self.assertEqual(report["machine"]["layer"]["semantic_risk"]["regulatory_confirmation"]
                         ["confirmed_material_event_fingerprints"], [fingerprint])
        self.assertEqual(report["m67"]["table"]["操作"], "否决")

    def test_main_rejects_unmatched_regulatory_confirmation(self):
        from engine.data.analysis_input_contract import build_a_short_run_identity

        ai = _analysis_input(candidates=[_ai_candidate("600000.SH")])
        confirmation = {
            "schema_name": "a_short_regulatory_advisory_confirmation",
            "schema_version": "1.0.0",
            "as_of": AS_OF,
            "candidate_digest": build_a_short_run_identity(AS_OF, ai["candidates"])["candidate_digest"],
            "confirmations": [{"ts_code": "600000.SH", "event_fingerprint": "0" * 64,
                               "decision": "confirmed_material",
                               "reviewed_at": "2026-06-09T09:30:00+08:00",
                               "note": "Must not attach to another event."}],
            "boundary": {"advisory_only": True, "modifies_egs_or_rule6": False, "automates_order": False},
        }
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td, ai=ai)
            confirmation_path = Path(td) / "regulatory-confirmation.json"
            confirmation_path.write_text(json.dumps(confirmation), encoding="utf-8")
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(Path(td) / "weekly.json"),
                      "--regulatory-confirmations", str(confirmation_path)],
                     price_provider=lambda code: _series(), semantic_provider=lambda code: None)

    def test_main_with_injected_price_provider(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(loaded["n_stocks"], 2)
        self.assertEqual(loaded["iv_feed_ref"], "feed.json")
        self.assertEqual(loaded["reports"][0]["m67"]["table"]["操作"], "观察")
        self.assertEqual(loaded["reports"][0]["machine"]["rule6_gate"]["disposition"], "manual_review")

    def test_v2_comparison_weekly_order_is_pre_publish_summary_then_post_publish_capture(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            root = Path(td) / "state" / "a_short" / "factor_comparison_private" / "v2"
            dates = pd.bdate_range(end=pd.Timestamp(AS_OF), periods=len(_series())).strftime("%Y%m%d").tolist()
            dated_series = [{**row, "trade_date": trade_date} for row, trade_date in zip(_series(), dates)]
            with patch("builtins.print") as terminal:
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out), "--run-date", AS_OF, "--factor-comparison-v2-root", str(root)],
                     price_provider=lambda code: dated_series)
            weekly = json.loads(out.read_text(encoding="utf-8"))
            markdown = out.with_suffix(".md").read_text(encoding="utf-8")
            self.assertEqual(weekly["factor_comparison_v2"]["status"], "evidence_unavailable_or_inconclusive")
            self.assertIn(weekly["factor_comparison_v2"]["message"], markdown)
            terminal_text = "\n".join(str(call.args[0]) for call in terminal.call_args_list if call.args)
            self.assertIn("[factor-comparison-v2] " + weekly["factor_comparison_v2"]["message"], terminal_text)
            self.assertTrue((root / "weeks" / AS_OF / "capture.json").is_file())
            self.assertFalse((root.parent / "ledger.json").exists())  # no legacy v1 dual write

    def test_p2_target_policy_is_pre_publish_summary_then_post_publish_capture(self):
        from runners.a_short_target_policy_comparison_runner import settle_and_summarize

        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            root = Path(td) / "logs" / "a_short_target_policy_comparison.json"
            summary = settle_and_summarize(root=None, as_of=AS_OF)
            with patch("runners.a_short_target_policy_comparison_runner.settle_and_summarize",
                       return_value=summary) as settle, \
                    patch("runners.a_short_target_policy_comparison_runner.capture_after_published_weekly",
                          return_value={"status": "captured"}) as capture:
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out), "--run-date", AS_OF, "--target-policy-root", str(root)],
                     price_provider=lambda code: _series())
            weekly = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(weekly["target_policy_comparison"], summary)
            self.assertIn(summary["message"], out.with_suffix(".md").read_text(encoding="utf-8"))
            settle.assert_called_once()
            capture.assert_called_once()

    def test_p4b_manual_promotion_reminder_is_advisory_and_fail_closed(self):
        candidate = {"status": "manual_promotion_candidate", "adjudication": {
            "verdict": "candidate_for_manual_promotion", "automatic_policy_switch": False}}
        reminders = _build_evidence_reminders(AS_OF, None, None, candidate)
        item = next(row for row in reminders["reminders"] if row["track"] == "p4b_manual_promotion")
        self.assertEqual(item["status"], "review_due")
        self.assertIn("独立最高风险审查", item["message"])
        self.assertTrue(reminders["production_unchanged"])

        unavailable = _build_evidence_reminders(
            AS_OF, None, None, {"status": "evidence_unavailable_or_inconclusive", "adjudication": {}})
        item = next(row for row in unavailable["reminders"] if row["track"] == "p4b_manual_promotion")
        self.assertEqual(item["status"], "unavailable")

    def test_p4_terminal_verdicts_are_not_rendered_as_accumulating(self):
        do_not_promote = _build_evidence_reminders(
            AS_OF, None, None,
            {"status": "do_not_promote", "adjudication": {"verdict": "do_not_promote"}},
        )
        p4_item = next(row for row in do_not_promote["reminders"] if row["track"] == "p4b_manual_promotion")
        self.assertEqual(p4_item["status"], "retain_baseline")
        self.assertEqual(do_not_promote["status"], "closed")
        self.assertIn("保留现有基线", p4_item["message"])
        self.assertIn("不会自动改 production 配置", p4_item["message"])

        retired = _build_evidence_reminders(
            AS_OF, None, None,
            {"status": "retired_for_epoch", "adjudication": {"verdict": "inconclusive_retired_for_epoch"}},
        )
        p4_item = next(row for row in retired["reminders"] if row["track"] == "p4b_manual_promotion")
        self.assertEqual(p4_item["status"], "retired_for_epoch")
        self.assertEqual(retired["status"], "closed")
        self.assertIn("新预注册/新 epoch", p4_item["message"])

    def test_p4_reminder_markdown_uses_the_unified_p2_p3_p4_heading(self):
        rendered = render_weekly_markdown({
            "a_short_evidence_reminders": _build_evidence_reminders(
                AS_OF, None, None,
                {"status": "do_not_promote", "adjudication": {"verdict": "do_not_promote"}},
            ),
            "reports": [],
            "n_stocks": 0,
        })
        self.assertIn("P2/P3/P4", rendered)

    def test_p3_final_action_is_pre_publish_summary_then_post_publish_capture(self):
        from runners.a_short_final_action_validation_runner import unavailable_public_summary

        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            root = Path(td) / "logs" / "a_short_final_action_validation.json"
            summary = unavailable_public_summary(AS_OF)
            with patch("runners.a_short_final_action_validation_runner.settle_and_summarize",
                       return_value=summary) as settle, \
                    patch("runners.a_short_final_action_validation_runner.capture_after_published_weekly",
                          return_value={"status": "captured"}) as capture:
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out), "--run-date", AS_OF,
                      "--final-action-validation-root", str(root)], price_provider=lambda code: _series())
            weekly = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("a_short_evidence_reminders", weekly)
            self.assertIn(summary["message"], out.with_suffix(".md").read_text(encoding="utf-8"))
            self.assertEqual(weekly["a_short_evidence_reminders"]["production_unchanged"], True)
            settle.assert_called_once()
            capture.assert_called_once()

    def test_p2_target_policy_is_absent_without_its_private_root(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            self.assertNotIn("target_policy_comparison", json.loads(out.read_text(encoding="utf-8")))

    def test_p2_long_window_isolated_from_official_m67_series(self):
        from runners.a_short_target_policy_comparison_runner import settle_and_summarize

        production_series = _series()
        dates = pd.bdate_range(end=pd.Timestamp(AS_OF), periods=253).strftime("%Y%m%d").tolist()
        shadow_series = [
            {"trade_date": trade_date, "high": 2.92, "low": 2.88, "close": 2.90}
            for trade_date in dates
        ]
        shadow_series[-30:] = [dict(row, trade_date=trade_date)
                               for row, trade_date in zip(_series(), dates[-30:])]
        summary = settle_and_summarize(root=None, as_of=AS_OF)
        captured = []
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            baseline_out, p2_out = Path(td) / "baseline.json", Path(td) / "p2.json"
            common = ["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json")]
            main(common + ["--out", str(baseline_out)], price_provider=lambda code: production_series)
            with patch("runners.a_short_target_policy_comparison_runner.settle_and_summarize",
                       return_value=summary), \
                    patch("runners.a_short_target_policy_comparison_runner.capture_after_published_weekly",
                          side_effect=lambda **kwargs: captured.append(kwargs["candidates"]) or {"status": "captured"}):
                main(common + ["--out", str(p2_out), "--run-date", AS_OF,
                               "--target-policy-root", str(Path(td) / "logs" / "p2.json")],
                     price_provider=lambda code: production_series,
                     target_policy_price_provider=lambda code: shadow_series)
            baseline = json.loads(baseline_out.read_text(encoding="utf-8"))
            p2_weekly = json.loads(p2_out.read_text(encoding="utf-8"))
        def _without_generated_at(value):
            if isinstance(value, dict):
                return {key: _without_generated_at(item) for key, item in value.items()
                        if key != "generated_at"}
            if isinstance(value, list):
                return [_without_generated_at(item) for item in value]
            return value

        self.assertEqual(_without_generated_at(p2_weekly["reports"]),
                         _without_generated_at(baseline["reports"]))
        self.assertEqual(len(captured), 1)
        self.assertTrue(all(len(candidate["price_series"]) == 253 for candidate in captured[0]))

    def test_authorized_fetch_keeps_official_120d_and_p2_450d_separate(self):
        import runners.a_short_weekly_pipeline as wp

        starts = []
        dates = pd.bdate_range(end=pd.Timestamp(AS_OF), periods=30).strftime("%Y%m%d").tolist()
        dated_series = [dict(row, trade_date=trade_date)
                        for row, trade_date in zip(_series(), dates)]

        def _spy(ts, pro, code, start, end, accept_prior_settled_date=None):
            starts.append(start)
            return dated_series, end

        class _Pro:
            pass

        old_ts = sys.modules.get("tushare")
        original_fetch = wp._fetch_price_series
        sys.modules["tushare"] = object()
        wp._fetch_price_series = _spy
        try:
            with tempfile.TemporaryDirectory() as td:
                self._write_inputs(td)
                with patch("runners.a_short_target_policy_comparison_runner.capture_after_published_weekly",
                           return_value={"status": "captured"}):
                    main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                          "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                          "--out", str(Path(td) / "weekly.json"), "--run-date", AS_OF,
                          "--confirm-fetch-authorized", "--skip-semantic",
                          "--target-policy-root", str(Path(td) / "logs" / "p2.json")],
                         pro_factory=lambda: _Pro(), semantic_provider=lambda code: None,
                         web_llm_provider=lambda code: None)
        finally:
            wp._fetch_price_series = original_fetch
            if old_ts is not None:
                sys.modules["tushare"] = old_ts
            else:
                sys.modules.pop("tushare", None)

        self.assertIn("20260209", starts)
        self.assertIn("20250316", starts)
        self.assertEqual(starts.count("20260209"), 2)
        self.assertEqual(starts.count("20250316"), 2)

    def test_invalid_p2_summary_becomes_nonfatal_current_unavailable_banner(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            with patch("runners.a_short_target_policy_comparison_runner.settle_and_summarize",
                       return_value={"not": "a summary"}), \
                    patch("runners.a_short_target_policy_comparison_runner.capture_after_published_weekly",
                          return_value={"status": "captured"}):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out), "--run-date", AS_OF,
                      "--target-policy-root", str(Path(td) / "logs" / "p2.json")],
                     price_provider=lambda code: _series())
            weekly = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(weekly["target_policy_comparison"]["status"], "evidence_unavailable_or_inconclusive")
        self.assertEqual(weekly["target_policy_comparison"]["production_unchanged"], True)

    def test_v2_replay_drift_does_not_skip_p2_capture(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            v2_root = Path(td) / "state" / "a_short" / "factor_comparison_private" / "v2"
            p2_root = Path(td) / "logs" / "a_short_target_policy_comparison.json"
            with patch("engine.a_short_factor_comparison_v2_weekly.capture_v2_after_published_weekly",
                       side_effect=ValueError(f"{AS_OF}: v2 capture replay input drifted")), \
                    patch("runners.a_short_target_policy_comparison_runner.capture_after_published_weekly",
                          return_value={"status": "captured"}) as p2_capture:
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out), "--run-date", AS_OF,
                      "--factor-comparison-v2-root", str(v2_root),
                      "--target-policy-root", str(p2_root)],
                      price_provider=lambda code: _series())
        p2_capture.assert_called_once()

    def test_v2_capture_failure_prints_only_safe_error_code_and_keeps_m67_nonblocking(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            v2_root = Path(td) / "state" / "a_short" / "factor_comparison_private" / "v2"
            secret_message = "C:\\private\\token.txt"
            terminal = StringIO()
            with patch("engine.a_short_factor_comparison_v2_weekly.capture_v2_after_published_weekly",
                       side_effect=RuntimeError(secret_message)), \
                    patch("runners.a_short_target_policy_comparison_runner.capture_after_published_weekly",
                          return_value={"status": "captured"}) as p2_capture, redirect_stdout(terminal):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out), "--run-date", AS_OF,
                      "--factor-comparison-v2-root", str(v2_root),
                      "--target-policy-root", str(Path(td) / "logs" / "p2.json")],
                     price_provider=lambda code: _series())
            p2_capture.assert_called_once()
            output = terminal.getvalue()
        self.assertIn("error_code=unknown", output)
        self.assertIn("M6.7 output remains authoritative and unchanged", output)
        self.assertNotIn("600598.SH", output)
        self.assertNotIn("token.txt", output)
        self.assertNotIn("RuntimeError", output)
        self.assertNotIn("traceback", output.lower())

    def test_v2_capture_is_not_reached_when_official_publish_fails(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            root = Path(td) / "state" / "a_short" / "factor_comparison_private" / "v2"
            args = ["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                    "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                    "--out", str(Path(td) / "weekly.json"), "--run-date", AS_OF,
                    "--factor-comparison-v2-root", str(root)]
            with patch("runners.a_short_weekly_pipeline.publish_weekly_bundle", side_effect=RuntimeError("publish failed")), \
                    patch("engine.a_short_factor_comparison_v2_weekly.capture_v2_after_published_weekly") as capture:
                with self.assertRaises(RuntimeError):
                    main(args, price_provider=lambda code: _series())
                capture.assert_not_called()
            self.assertFalse(root.exists())

    def test_legacy_v1_comparison_capture_flags_are_rejected_before_any_weekly_work(self):
        with self.assertRaises(SystemExit):
            main(["--as-of", AS_OF, "--analysis-input", "missing-ai.json", "--iv-feed", "missing-feed.json",
                  "--out", "missing-weekly.json", "--factor-comparison-root", "legacy-root"])

    def test_v2_comparison_capture_requires_a_real_run_date_before_any_weekly_work(self):
        with self.assertRaises(SystemExit):
            main(["--as-of", AS_OF, "--analysis-input", "missing-ai.json", "--iv-feed", "missing-feed.json",
                  "--out", "missing-weekly.json", "--factor-comparison-v2-root",
                  "state/a_short/factor_comparison_private/v2"])
    def test_main_preserves_watch_as_nonfinal_observation(self):
        ai = _analysis_input(candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
        ai["candidates"][1]["analysis_role"] = "watch"
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td, ai=ai)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            report = {row["ts_code"]: row for row in json.loads(out.read_text(encoding="utf-8"))["reports"]}
        self.assertEqual(report["000001.SZ"]["m67"]["table"]["操作"], "观察")
        self.assertIn("非 final，仅观察", report["000001.SZ"]["machine"]["entry_exit_size_star"]["reject_reason"])

    def test_main_accepts_legacy_v14_mixed_rank_counts_without_misreporting_them_as_l0(self):
        """Real Run-1 regression: old v1.4 mixed rank counts must not crash or become hard-veto summary rows."""
        ai = _analysis_input(candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
        ai["universe_summary"].pop("rank_exclusion_counts", None)  # exact legacy v1.4 shape
        ai["universe_summary"]["excluded_counts"] = {
            "unlock": 2, "suspended": 0, "relisted": 0, "holder_reduction_veto_10d": 0,
            "l1_industry_leader": 601, "l2_quality_risk": 255, "rank_unexpected": 0,
        }
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td, ai=ai)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            weekly = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(weekly["exclusion_summary"]["total_excluded"], 2)
        self.assertEqual([r["source_field"] for r in weekly["exclusion_summary"]["by_reason"]],
                         ["share_float_unlock"])

    def test_price_freshness_mode_controls_tolerance(self):
        # the intraday tolerance is gated on the EXPLICIT --price-freshness-mode (NOT inferred from
        # run-date==as-of). Spy on _fetch_price_series to capture what main passed as the accepted clock.
        import runners.a_short_weekly_pipeline as wp
        cap = {}

        def _spy(ts, pro, code, start, end, accept_prior_settled_date=None):
            cap["accept"] = accept_prior_settled_date
            raise SystemExit("captured")                   # short-circuit once the wiring is observed

        class _Pro:
            def trade_cal(self, **kw):
                return pd.DataFrame({"cal_date": ["20260605", "20260608", AS_OF]})

        orig = wp._fetch_price_series
        old_ts = sys.modules.get("tushare")
        sys.modules["tushare"] = object()
        wp._fetch_price_series = _spy
        try:
            with tempfile.TemporaryDirectory() as td:
                self._write_inputs(td)
                base = ["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                        "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                        "--out", str(Path(td) / "w.json"), "--confirm-fetch-authorized", "--skip-semantic"]
                kw = dict(pro_factory=lambda: _Pro(), semantic_provider=lambda c: None,
                          web_llm_provider=lambda c: None)
                with self.assertRaises(SystemExit):        # explicit intraday mode + run-date==as-of
                    main(base + ["--run-date", AS_OF, "--price-freshness-mode", "intraday_prior_settled"], **kw)
                self.assertEqual(cap["accept"], "20260608")   # prior trading day passed
                cap.clear()
                with self.assertRaises(SystemExit):        # default strict — NO tolerance even if run-date==as-of
                    main(base + ["--run-date", AS_OF], **kw)
                self.assertIsNone(cap["accept"])
        finally:
            wp._fetch_price_series = orig
            if old_ts is not None:
                sys.modules["tushare"] = old_ts
            else:
                sys.modules.pop("tushare", None)

    def test_intraday_mode_rejects_historical_run_date_after_as_of(self):
        # explicit intraday mode where the run-date is AFTER as_of (genuine past replay, as_of EOD已发布)
        # is rejected up front (guard), before fetch. (canonical 解析器只会产 as_of>=run_date 的 live。)
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--run-date", "20260615", "--price-freshness-mode",
                      "intraday_prior_settled", "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(Path(td) / "w.json"), "--confirm-fetch-authorized", "--skip-semantic"],
                     pro_factory=lambda: object(), semantic_provider=lambda c: None,
                     web_llm_provider=lambda c: None)

    def test_intraday_mode_allows_prospective_run_date_before_as_of(self):
        # canonical: run-date BEFORE as_of (周末/周一盘前跑、as_of=即将到来的周一) → 前瞻 live → guard 放行,
        # 价格门容忍最新 bar==前一交易日(20260608)。spy 短路 fetch 以证明已越过 guard 并走 intraday 分支。
        import runners.a_short_weekly_pipeline as wp
        cap = {}

        def _spy(ts, pro, code, start, end, accept_prior_settled_date=None):
            cap["accept"] = accept_prior_settled_date
            raise SystemExit("captured")

        class _Pro:
            def trade_cal(self, **kw):
                return pd.DataFrame({"cal_date": ["20260605", "20260608", AS_OF]})

        orig = wp._fetch_price_series
        old_ts = sys.modules.get("tushare")
        sys.modules["tushare"] = object()
        wp._fetch_price_series = _spy
        try:
            with tempfile.TemporaryDirectory() as td:
                self._write_inputs(td)
                with self.assertRaises(SystemExit):           # spy 短路(非 guard) → 证明 guard 已放行
                    main(["--as-of", AS_OF, "--run-date", "20260605", "--price-freshness-mode",
                          "intraday_prior_settled", "--analysis-input", str(Path(td) / "ai.json"),
                          "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                          "--out", str(Path(td) / "w.json"), "--confirm-fetch-authorized", "--skip-semantic"],
                         pro_factory=lambda: _Pro(), semantic_provider=lambda c: None,
                         web_llm_provider=lambda c: None)
                self.assertEqual(cap["accept"], "20260608")   # 前瞻 → 前一交易日容忍生效
        finally:
            wp._fetch_price_series = orig
            if old_ts is not None:
                sys.modules["tushare"] = old_ts
            else:
                sys.modules.pop("tushare", None)

    def test_strict_mode_records_price_freshness_lineage(self):
        # default strict run: the artifact records the price clock = as_of (injected list → strict clock).
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            pf = json.loads(out.read_text(encoding="utf-8"))["run_lineage"]["price_freshness"]
        self.assertEqual(pf["mode"], "strict_as_of")
        self.assertEqual(pf["price_data_through"], AS_OF)
        self.assertIsNone(pf["accepted_prior_settled_date"])

    def test_intraday_mode_records_prior_settled_and_renders_clock(self):
        # full intraday path (real _fetch_price_series via fake tushare): bars end at the prior settled
        # day; the artifact + Markdown must honestly state price_data_through == prior settled, != as_of.
        dates = pd.date_range(end="20260608", periods=25, freq="D").strftime("%Y%m%d").tolist()
        fake = _fake_ts(pd.DataFrame({"trade_date": dates, "high": [3.1] * 25,
                                      "low": [2.8] * 25, "close": [2.9] * 25}))

        class _Pro:
            def trade_cal(self, **kw):
                return pd.DataFrame({"cal_date": ["20260605", "20260608", AS_OF]})

        old = sys.modules.get("tushare")
        sys.modules["tushare"] = fake
        try:
            with tempfile.TemporaryDirectory() as td:
                feed = _feed()
                feed["series"][-1]["trade_date"] = "20260608"
                self._write_inputs(td, feed=feed)
                out = Path(td) / "weekly_m67.json"
                main(["--as-of", AS_OF, "--run-date", AS_OF, "--price-freshness-mode", "intraday_prior_settled",
                      "--analysis-input", str(Path(td) / "ai.json"), "--iv-feed", str(Path(td) / "feed.json"),
                      "--account", str(Path(td) / "acct.json"), "--out", str(out), "--confirm-fetch-authorized",
                      "--skip-semantic"], pro_factory=lambda: _Pro(),
                     semantic_provider=lambda c: None, web_llm_provider=lambda c: None)
                pf = json.loads(out.read_text(encoding="utf-8"))["run_lineage"]["price_freshness"]
                md = (Path(td) / "weekly_m67.md").read_text(encoding="utf-8")
        finally:
            if old is not None:
                sys.modules["tushare"] = old
            else:
                sys.modules.pop("tushare", None)
        self.assertEqual(pf["mode"], "intraday_prior_settled")
        self.assertEqual(pf["run_date"], AS_OF)
        self.assertEqual(pf["accepted_prior_settled_date"], "20260608")
        self.assertEqual(pf["price_data_through"], "20260608")     # honest: features through prior settled day
        self.assertIn("价格时钟", md)                               # clock visible to the user in Markdown
        self.assertIn("20260608", md)

    def test_portfolio_facts_follow_the_price_clock_and_share_dragon_window(self):
        """6A: decision date may differ, but facts and lookback both bind to price_data_through."""
        dates = pd.date_range(end="20260608", periods=25, freq="D").strftime("%Y%m%d").tolist()
        fake = _fake_ts(pd.DataFrame({"trade_date": dates, "high": [3.1] * 25,
                                      "low": [2.8] * 25, "close": [2.9] * 25}))
        fact_calls, dragon_calls = [], []

        class _Pro:
            def trade_cal(self, **_kw):
                return pd.DataFrame({"cal_date": ["20260602", "20260603", "20260604", "20260605", "20260608", AS_OF]})

        def portfolio_provider(codes, fact_as_of):
            fact_calls.append((list(codes), fact_as_of))
            return ({code: {"ts_code": code, "as_of": fact_as_of, "source": "fixture",
                            "circ_mv_rmb": 10_000_000_000.0,
                            "margin_balance_to_float_mv_pct": 1.0,
                            "is_large_index_component": False}
                     for code in codes}, "ok")

        old = sys.modules.get("tushare")
        sys.modules["tushare"] = fake
        try:
            with tempfile.TemporaryDirectory() as td:
                feed = _feed()
                feed["series"][-1]["trade_date"] = "20260608"
                self._write_inputs(td, feed=feed)
                out = Path(td) / "weekly_m67.json"
                main(["--as-of", AS_OF, "--run-date", AS_OF, "--price-freshness-mode", "intraday_prior_settled",
                      "--analysis-input", str(Path(td) / "ai.json"), "--iv-feed", str(Path(td) / "feed.json"),
                      "--out", str(out), "--confirm-fetch-authorized", "--skip-semantic"],
                     pro_factory=lambda: _Pro(), portfolio_risk_provider=portfolio_provider,
                     dragon_list_provider=lambda day: dragon_calls.append(day) or [])
                weekly = json.loads(out.read_text(encoding="utf-8"))
        finally:
            if old is not None:
                sys.modules["tushare"] = old
            else:
                sys.modules.pop("tushare", None)
        self.assertEqual(weekly["as_of"], AS_OF)
        self.assertEqual(weekly["run_lineage"]["price_freshness"]["price_data_through"], "20260608")
        self.assertEqual([(sorted(codes), fact_as_of) for codes, fact_as_of in fact_calls],
                         [(["000001.SZ", "600000.SH"], "20260608")])
        self.assertEqual(dragon_calls, ["20260602", "20260603", "20260604", "20260605", "20260608"])
        self.assertEqual(weekly["portfolio_risk"]["fact_fetch"], {"status": "ok", "as_of": "20260608"})
        self.assertEqual({row["fact_as_of"] for row in weekly["portfolio_risk"]["stock_results"]}, {"20260608"})

    def test_portfolio_fact_fetch_states_are_visible_and_unavailable_fails_closed(self):
        rows = [_normalized("600000.SH"), _normalized("000001.SZ")]
        for row in rows:
            row["stateful_risk"] = {
                "position_state": "held",
                "position": {"ts_code": row["ts_code"], "shares": 10_000, "avg_cost": 2.7,
                             "entry_date": "20260601", "stop_loss": 2.5},
            }
        not_published = build_weekly_report(rows, AS_OF, GEN, portfolio_fact_overrides={},
                                            portfolio_fact_fetch_status="not_published")
        self.assertEqual(not_published["portfolio_risk"]["fact_fetch"],
                         {"status": "not_published", "as_of": AS_OF})
        unavailable = build_weekly_report(
            rows, AS_OF, GEN,
            portfolio_fact_overrides={row["ts_code"]: {"ts_code": row["ts_code"], "as_of": AS_OF,
                                                          "fetch_status": "unavailable"}
                                       for row in rows},
            portfolio_fact_fetch_status="unavailable")
        self.assertEqual(unavailable["portfolio_risk"]["fact_fetch"],
                         {"status": "unavailable", "as_of": AS_OF})
        self.assertEqual(unavailable["portfolio_risk"]["status"], "manual_review_required")

    def test_main_converts_provider_unavailable_result_to_fail_closed_facts(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td, ai=_analysis_input(candidates=[_ai_candidate("600000.SH")]))
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--out", str(out)],
                 price_provider=lambda _code: _series(),
                 portfolio_risk_provider=lambda _codes, _as_of: ({}, "unavailable"))
            weekly = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(weekly["portfolio_risk"]["fact_fetch"],
                         {"status": "unavailable", "as_of": AS_OF})
        self.assertEqual(weekly["portfolio_risk"]["fact_sources"], [
            {"source": "portfolio_risk_provider_unavailable", "as_of": AS_OF}
        ])

    def test_mixed_price_latest_dates_abort_no_file(self):
        # candidates with differing latest price-bar dates (uneven endpoint) → fail-closed, no file.
        def _prov(code):
            return (_series(), "20260609" if code == "600000.SH" else "20260608")  # (series, latest) differs
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "w.json"
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out)], price_provider=_prov)
            self.assertFalse(out.exists())

    def test_main_writes_markdown_sibling_with_banner(self):
        # pipeline main emits a readable weekly_m67.md sibling next to the json (honesty banner present).
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly_m67.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            md = Path(td) / "weekly_m67.md"
            self.assertTrue(md.exists())
            text = md.read_text(encoding="utf-8")
        self.assertIn("# A-short 周报 M6.7", text)
        self.assertIn("edge 未验证", text)        # honesty banner
        self.assertIn("## 一览", text)

    def test_main_with_account_records_sized_lineage(self):
        # A valid account remains sized, but the example's pending Rule6 checks keep it observe-only.
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            w = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(w["run_lineage"]["account_status"], "provided")
        self.assertEqual(w["run_lineage"]["sizing_mode"], "sized")
        self.assertEqual(w["reports"][0]["m67"]["table"]["操作"], "观察")

    def test_main_account_position_outputs_hold_for_held_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            acct = _account()
            acct["positions"] = [{"ts_code": "600000.SH", "name": "测试", "shares": 1000,
                                  "avg_cost": 2.70, "entry_date": "20260601", "stop_loss": 2.55}]
            _write_account(Path(td) / "acct.json", acct)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            w = json.loads(out.read_text(encoding="utf-8"))
        by = {r["ts_code"]: r for r in w["reports"]}
        self.assertEqual(by["600000.SH"]["m67"]["table"]["操作"], "持有")
        self.assertIn("已有持仓", by["600000.SH"]["m67"]["精简结论区"]["操作建议"])
        self.assertEqual(by["000001.SZ"]["m67"]["table"]["操作"], "观察")
        # The flat row is blocked by the legacy input's unavailable margin source.
        # That suppresses a new entry but must not hide its portfolio review state.
        self.assertEqual(by["000001.SZ"]["machine"]["layer"]["portfolio_risk"]["status"],
                         "manual_review_required")

    def test_main_rule13_active_blocks_flat_reentry(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            acct = _account()
            acct["rule13_cooldowns"] = [{
                "ts_code": "600000.SH",
                "status": "active_cooldown",
                "exit_date": "20260608",
                "cooldown_until": "20260610",
                "requires_new_catalyst": True,
                "new_catalyst_confirmed": False,
                "requires_m4_recheck": True,
                "m4_recheck_passed": False,
                "max_reentry_position_pct": 0.5,
            }]
            _write_account(Path(td) / "acct.json", acct)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            w = json.loads(out.read_text(encoding="utf-8"))
        by = {r["ts_code"]: r for r in w["reports"]}
        self.assertEqual(by["600000.SH"]["m67"]["table"]["操作"], "否决")
        self.assertIn("Rule13", "|".join(by["600000.SH"]["machine"]["layer"]["hard_veto"]))

    def test_main_without_account_is_observation_only_and_artifact_labeled(self):
        # the same candidate that builds WITH account becomes 观察 with NO account; the durable artifact
        # (json run_lineage + md banner) marks it sizing-less so a reader can't mistake it for a real avoid.
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly_m67.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--out", str(out)],   # NO --account
                 price_provider=lambda code: _series())
            w = json.loads(out.read_text(encoding="utf-8"))
            md = (Path(td) / "weekly_m67.md").read_text(encoding="utf-8")
        self.assertEqual(w["run_lineage"]["account_status"], "absent")
        self.assertEqual(w["run_lineage"]["sizing_mode"], "observation_only_no_account")
        self.assertNotEqual(w["reports"][0]["m67"]["table"]["操作"], "建仓")   # no sizing -> not 建仓
        self.assertIn("无账户", md)                                            # durable no-sizing banner in the .md
        self.assertIn("sizing 假象", md)

    def test_main_account_file_with_bad_cash_aborts_no_silent_sizingless(self):
        # account FILE supplied but available_cash missing/non-numeric -> refuse (do not silently run sizing-less)
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            (Path(td) / "bad_acct.json").write_text(json.dumps({"market_regime": "震荡期"}), encoding="utf-8")
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "bad_acct.json"),
                      "--out", str(Path(td) / "w.json")], price_provider=lambda code: _series())

    def test_main_invalid_as_of_aborts(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            with self.assertRaises(SystemExit):
                main(["--as-of", "20260631", "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--out", str(Path(td) / "w.json")],
                     price_provider=lambda code: _series())

    def test_main_no_provider_without_confirm_aborts(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--out", str(Path(td) / "w.json")])

    def test_main_empty_price_series_without_current_clock_aborts_no_file(self):
        # A missing latest bar is source-ambiguous, so it remains batch fail-closed.
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out)], price_provider=lambda code: ([], None))
            self.assertFalse(out.exists())

    def test_main_short_price_series_with_stale_clock_aborts_no_file(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out)],
                     price_provider=lambda code: (_series()[:MIN_PRICE_OBS - 1], "20260608"))
            self.assertFalse(out.exists())

    def test_main_isolates_current_clock_short_history_candidate(self):
        ai = _analysis_input(candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])

        def _provider(code):
            return (_series()[:MIN_PRICE_OBS - 1], AS_OF) if code == "600000.SH" else (_series(), AS_OF)

        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td, ai=ai)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=_provider)
            weekly = json.loads(out.read_text(encoding="utf-8"))
            markdown = out.with_suffix(".md").read_text(encoding="utf-8")
        self.assertEqual([row["ts_code"] for row in weekly["reports"]], ["000001.SZ"])
        self.assertEqual(weekly["candidate_exclusions"], [{
            "ts_code": "600000.SH", "name": "博杰股份",
            "reason": "insufficient_usable_history", "source_status": "price_clock_current",
        }])
        self.assertIn("单票候选排除", markdown)
        self.assertIn("insufficient_usable_history", markdown)

    def test_main_isolates_current_known_suspension_only(self):
        suspended = _ai_candidate("600000.SH")
        suspended["event_risk"]["suspension"] = {
            "is_suspended": True, "recent_suspension_5d": True,
            "source_status": "known_hit", "observed_at": AS_OF,
        }
        ai = _analysis_input(candidates=[suspended, _ai_candidate("000001.SZ")])

        def _provider(code):
            return ([], None) if code == "600000.SH" else (_series(), AS_OF)

        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td, ai=ai)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=_provider)
            weekly = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([row["ts_code"] for row in weekly["reports"]], ["000001.SZ"])
        self.assertEqual(weekly["candidate_exclusions"], [{
            "ts_code": "600000.SH", "name": "博杰股份",
            "reason": "confirmed_suspension", "source_status": "known_hit",
        }])

    def test_main_held_confirmed_suspension_routes_to_manual_review_once(self):
        suspended = _ai_candidate("600000.SH")
        suspended["event_risk"]["suspension"] = {
            "is_suspended": True, "recent_suspension_5d": True,
            "source_status": "known_hit", "observed_at": AS_OF,
        }
        ai = _analysis_input(candidates=[suspended, _ai_candidate("000001.SZ")])
        acct = _account()
        acct["positions"] = [{"ts_code": "600000.SH", "name": "测试", "shares": 1000,
                              "avg_cost": 2.70, "entry_date": "20260601", "stop_loss": 2.55}]
        semantic_seen, news_seen = [], []

        def _semantic(code):
            semantic_seen.append(code)
            return {"status": "clear"}

        def _news(code):
            news_seen.append(code)
            return {"status": "risk"}

        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td, ai=ai)
            _write_account(Path(td) / "acct.json", acct)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: (_series(), AS_OF),
                 holding_semantic_provider=_semantic, holding_web_llm_provider=_news,
                 dividend_provider=lambda code: ([{"ann_date": "20260601", "ex_date": "20260615"}]
                                                 if code == "600000.SH" else []),
                 unlock_provider=lambda code: ([{"ann_date": "20260601", "float_date": "20260615"}]
                                               if code == "600000.SH" else []))
            weekly = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([row["ts_code"] for row in weekly["reports"]], ["000001.SZ"])
        self.assertEqual([row["ts_code"] for row in weekly["candidate_exclusions"]], ["600000.SH"])
        self.assertEqual([row["ts_code"] for row in weekly["holdings_manual_review"]], ["600000.SH"])
        reason = weekly["holdings_manual_review"][0]["reason"]
        self.assertIn("confirmed_suspension", reason)
        self.assertIn("官方语义=clear", reason)
        self.assertIn("新闻=risk", reason)
        self.assertIn("未来已知事件", reason)
        self.assertEqual(semantic_seen, ["600000.SH"])
        self.assertEqual(news_seen, ["600000.SH"])
        self.assertEqual([notice["ts_code"] for notice in weekly["ex_div_notices"]], ["600000.SH"])
        self.assertEqual([event["ts_code"] for event in weekly["upcoming_events"]["events"]], ["600000.SH"])

    def test_main_held_current_short_history_routes_to_manual_review_once(self):
        short_history = _ai_candidate("600000.SH")
        ai = _analysis_input(candidates=[short_history, _ai_candidate("000001.SZ")])
        acct = _account()
        acct["positions"] = [{"ts_code": "600000.SH", "name": "测试", "shares": 1000,
                              "avg_cost": 2.70, "entry_date": "20260601", "stop_loss": 2.55}]

        def _provider(code):
            return (_series()[:MIN_PRICE_OBS - 1], AS_OF) if code == "600000.SH" else (_series(), AS_OF)

        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td, ai=ai)
            _write_account(Path(td) / "acct.json", acct)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=_provider)
            weekly = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([row["ts_code"] for row in weekly["reports"]], ["000001.SZ"])
        self.assertEqual([row["ts_code"] for row in weekly["holdings_manual_review"]], ["600000.SH"])
        self.assertIn("insufficient_usable_history", weekly["holdings_manual_review"][0]["reason"])

    def test_candidate_price_clock_rejects_short_history_mixed_with_eligible_clock(self):
        cands = [_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")]
        prices = {
            "600000.SH": (_series()[:MIN_PRICE_OBS - 1], "20260608"),
            "000001.SZ": (_series(), AS_OF),
        }
        with self.assertRaises(SystemExit):
            _candidate_price_clock(cands, prices, AS_OF, "20260608")

    def test_candidate_price_clock_allows_asof_short_history_with_intraday_tolerance(self):
        candidate = _ai_candidate("600000.SH")
        prices = {"600000.SH": (_series()[:MIN_PRICE_OBS - 1], AS_OF)}
        clock = _candidate_price_clock([candidate], prices, AS_OF, "20260608")
        exclusion = _candidate_price_exclusion(candidate, prices["600000.SH"][0], AS_OF, clock, AS_OF)
        self.assertEqual(clock, AS_OF)
        self.assertEqual(exclusion["reason"], "insufficient_usable_history")

    def test_main_stale_known_suspension_with_current_short_history_aborts_no_file(self):
        suspended = _ai_candidate("600000.SH")
        suspended["event_risk"]["suspension"] = {
            "is_suspended": True, "recent_suspension_5d": True,
            "source_status": "known_hit", "observed_at": "20260608",
        }
        ai = _analysis_input(candidates=[suspended, _ai_candidate("000001.SZ")])

        def _provider(code):
            return (_series()[:MIN_PRICE_OBS - 1], AS_OF) if code == "600000.SH" else (_series(), AS_OF)

        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td, ai=ai)
            out = Path(td) / "weekly.json"
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out)], price_provider=_provider)
            self.assertFalse(out.exists())

    def test_main_analysis_input_trade_date_mismatch_aborts(self):
        # R-ASHORT-WEEKLY-ANALYSIS-INPUT-CONSUMER-VALIDATION-GAP: trade_date must == --as-of.
        for td_val in ("20260601", "20260612"):   # stale, future
            with tempfile.TemporaryDirectory() as td:
                self._write_inputs(td, ai=_analysis_input(
                    trade_date=td_val, candidates=[_ai_candidate("600000.SH")]))
                out = Path(td) / "weekly.json"
                with self.assertRaises(SystemExit):
                    main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                          "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                          "--out", str(out)], price_provider=lambda code: _series())
                self.assertFalse(out.exists())

    def test_main_malformed_analysis_input_aborts(self):
        with tempfile.TemporaryDirectory() as td:
            bad = _analysis_input(candidates=[_ai_candidate("600000.SH")])
            del bad["source"]                       # drop a schema-required top-level field
            self._write_inputs(td, ai=bad)
            out = Path(td) / "weekly.json"
            with self.assertRaises((ValueError, SystemExit)):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--out", str(out)], price_provider=lambda code: _series())
            self.assertFalse(out.exists())

    def test_main_regime_from_analysis_input_takes_precedence(self):
        # market_regime sourced from analysis_input.market_context (EGS); account state is cash/position only.
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH")])
            ai["market_context"]["market_regime"]["status"] = "attack"   # → 进攻期
            self._write_inputs(td, ai=ai)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(loaded["reports"][0]["m67"]["精简结论区"]["当前环境"], "进攻期")

    def test_unknown_regime_fallback_cannot_be_overridden_by_account(self):
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH")])
            ai["market_context"]["market_regime"]["status"] = "unknown"
            self._write_inputs(td, ai=ai)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series())
            loaded = json.loads(out.read_text(encoding="utf-8"))
        rep = loaded["reports"][0]
        self.assertIn("震荡期", rep["m67"]["精简结论区"]["当前环境"])
        self.assertIn("EGS regime unknown", rep["m67"]["精简结论区"]["当前环境"])
        self.assertEqual(rep["machine"]["risk_families"]["market_regime"]["action"], "downgrade")
        self.assertIn("regime unknown", rep["m67"]["精简结论区"]["操作建议"])

    def test_resolve_market_regime_unknown_returns_conservative_fallback(self):
        ai = _analysis_input(candidates=[_ai_candidate("600000.SH")])
        ai["market_context"]["market_regime"]["status"] = "unknown"
        regime, fallback = resolve_market_regime(ai)
        self.assertEqual(regime, "震荡期")
        self.assertEqual(fallback["action"], "downgrade_and_halve")

    def test_main_with_valid_overlay_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            (Path(td) / "ov.json").write_text(json.dumps(_valid_overlay(AS_OF)), encoding="utf-8")
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--overlay", str(Path(td) / "ov.json"), "--out", str(out)],
                 price_provider=lambda code: _series())
            self.assertTrue(out.exists())

    def _assert_main_overlay_aborts_no_file(self, overlay_obj):
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            (Path(td) / "ov.json").write_text(json.dumps(overlay_obj), encoding="utf-8")
            out = Path(td) / "weekly.json"
            md = Path(td) / "weekly.md"
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                      "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                      "--overlay", str(Path(td) / "ov.json"), "--out", str(out)],
                     price_provider=lambda code: _series())
            self.assertFalse(out.exists(), "weekly.json written despite invalid overlay")   # each absent
            self.assertFalse(md.exists(), "weekly.md written despite invalid overlay")       # separately

    def test_main_overlay_missing_weekly_candidate_writes_no_file(self):
        # internally-valid overlay covering only 600000.SH while weekly candidates are
        # [600000.SH, 000001.SZ]; the missing row would silently default to eligible/crowding=false
        # → MY lineage check (not overlay-internal consistency) must abort before any write.
        self._assert_main_overlay_aborts_no_file(_valid_overlay_for(["600000.SH"]))

    def test_main_overlay_wrong_candidate_set_writes_no_file(self):
        # internally-valid overlay for a different same-size set (600002.SH instead of 000001.SZ).
        self._assert_main_overlay_aborts_no_file(_valid_overlay_for(["600000.SH", "600002.SH"]))

    def test_main_overlay_duplicate_candidate_writes_no_file(self):
        # schema+consistency-valid overlay with a DUPLICATE current candidate row: dict/set collapse
        # would hide it (3 rows -> set of 2 == weekly set). The raw-list dup check must abort before write.
        self._assert_main_overlay_aborts_no_file(_valid_overlay_for(["600000.SH", "000001.SZ", "000001.SZ"]))

    def test_main_skip_semantic_leaves_semantic_neutral(self):
        # --skip-semantic (even with --confirm) must NOT auto-fetch cninfo; semantic stays neutral.
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out), "--confirm-fetch-authorized", "--skip-semantic"],
                 price_provider=lambda code: _series())
            w = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(w["reports"][0]["machine"]["layer"]["semantic_risk"]["impact"], "none")

    def test_cninfo_provider_reuses_summary_gates(self):
        # R-ASHORT-M67-CNINFO-PROVIDER-BYPASSES-SEMANTIC-SUMMARY-GATES: provider must reuse the
        # reviewed summary gates (main_board_top15 + missing->unknown + batch-empty->unknown).
        from runners.a_short_weekly_pipeline import _build_cninfo_semantic_provider
        calls = {}

        def fetch_factory(raws):
            def f(codes, a, l):
                calls["codes"] = list(codes)
                return raws
            return f
        empty = [{"ts_code": c, "ok": True, "error_category": None, "announcements": []}
                 for c in ("600000.SH", "000001.SZ", "600519.SH")]
        prov = _build_cninfo_semantic_provider(["600000.SH", "000001.SZ", "600519.SH"], AS_OF, 90,
                                               fetcher=fetch_factory(empty))
        self.assertEqual(prov("600000.SH")["status"], "unknown")     # mass ok-empty -> unknown (NOT clear)
        # non-main (ChiNext 300750) is neither fetched nor fed
        prov2 = _build_cninfo_semantic_provider(["600000.SH", "300750.SZ"], AS_OF, 90,
                                                fetcher=fetch_factory(empty))
        self.assertNotIn("300750.SZ", calls["codes"])               # not fetched
        self.assertIsNone(prov2("300750.SZ"))                       # not fed into M6.7
        # malformed raw (no ts_code) -> no "None" mapping; requested code missing -> unknown
        prov3 = _build_cninfo_semantic_provider(["600000.SH"], AS_OF, 90,
                                                fetcher=fetch_factory([{"ok": True, "announcements": []}]))
        self.assertIsNone(prov3("None"))
        self.assertEqual(prov3("600000.SH")["status"], "unknown")

    def test_cninfo_provider_rejects_bad_lookback_without_fetch(self):
        from runners.a_short_weekly_pipeline import _build_cninfo_semantic_provider
        called = {"n": 0}

        def f(c, a, l):
            called["n"] += 1
            return []
        for bad in (0, -5, "90", None):
            self.assertIsNone(_build_cninfo_semantic_provider(["600000.SH"], AS_OF, bad, fetcher=f))
        self.assertEqual(called["n"], 0)                            # never fetched on bad lookback

    def test_cninfo_provider_feeds_official_risk(self):
        from runners.a_short_weekly_pipeline import _build_cninfo_semantic_provider
        risk = [{"ts_code": "600000.SH", "ok": True, "error_category": None, "announcements": [
            {"announcementTitle": "关于立案调查的公告", "adjunctUrl": "http://x/p.pdf",
             "announcementTime": 1700000000000, "secCode": "600000"}]}]
        prov = _build_cninfo_semantic_provider(["600000.SH"], AS_OF, 90, fetcher=lambda c, a, l: risk)
        self.assertEqual(prov("600000.SH")["status"], "risk")       # genuine official risk still feeds
        self.assertTrue(prov("600000.SH")["events"])

    def test_build_cninfo_semantic_provider_nonblocking_on_failure(self):
        from runners.a_short_weekly_pipeline import _build_cninfo_semantic_provider

        def boom(codes, a, l):
            raise RuntimeError("net down")
        self.assertIsNone(_build_cninfo_semantic_provider(["600000.SH"], AS_OF, 90, fetcher=boom))

    def test_main_unconfirmed_semantic_provider_stays_pending(self):
        # An injected high official event is not a veto without the digest- and event-bound
        # manual confirmation input; a stock with no semantic stays neutral. No network.
        with tempfile.TemporaryDirectory() as td:
            self._write_inputs(td)
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)],
                 price_provider=lambda code: _series(),
                 semantic_provider=lambda code: (_official("risk", "high", "立案调查")
                                                 if code == "600000.SH" else None))
            w = json.loads(out.read_text(encoding="utf-8"))
        by = {r["ts_code"]: r for r in w["reports"]}
        self.assertEqual(by["600000.SH"]["m67"]["table"]["操作"], "观察")
        self.assertEqual(by["600000.SH"]["machine"]["layer"]["semantic_risk"]["impact"], "pending")
        self.assertEqual(by["600000.SH"]["machine"]["layer"]["semantic_risk"]
                         ["regulatory_confirmation"]["status"], "pending_confirmation")
        self.assertEqual(by["000001.SZ"]["machine"]["layer"]["semantic_risk"]["impact"], "none")  # no semantic


def _fake_ts(df):
    class _FakeTs:
        def __init__(self):
            self.calls = {}

        def pro_bar(self, **kw):
            self.calls.update(kw)
            return df
    return _FakeTs()


class PriceFetchTests(unittest.TestCase):
    def test_uses_stock_asset_E_and_returns_bars(self):
        # R-ASHORT-WEEKLY-PRICE-FETCH-FAIL-OPEN: A-share stocks need asset="E"; latest bar == end.
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260108", "20260109"], "high": [3.0, 3.1],
                                    "low": [2.9, 2.95], "close": [2.95, 3.0]}))
        series, latest = _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")
        self.assertEqual(ts.calls.get("asset"), "E")
        self.assertEqual(ts.calls.get("adj"), "qfq")
        self.assertEqual(len(series), 2)
        self.assertEqual(series[0]["trade_date"], "20260108")  # holding trailing-stop needs the PIT date
        self.assertEqual(latest, "20260109")        # actual latest bar date surfaced for lineage

    def test_provider_exception_aborts(self):
        ts = _fake_ts(None)
        ts.pro_bar = lambda **kw: (_ for _ in ()).throw(
            RuntimeError("request failed url=https://api.example.invalid token=SECRET123"))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")

    def test_transient_timeout_retries_then_returns_prices(self):
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260109"], "high": [3.1],
                                    "low": [2.95], "close": [3.0]}))
        attempts = 0

        def flaky_pro_bar(**kw):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise TimeoutError("provider timed out")
            return pd.DataFrame({"trade_date": ["20260109"], "high": [3.1],
                                 "low": [2.95], "close": [3.0]})

        ts.pro_bar = flaky_pro_bar
        with patch("runners.a_short_weekly_pipeline.time.sleep") as sleep:
            series, latest = _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")
        self.assertEqual(attempts, 3)
        self.assertEqual(sleep.call_args_list[0].args, (0.5,))
        self.assertEqual(sleep.call_args_list[1].args, (1.0,))
        self.assertEqual((len(series), latest), (1, "20260109"))

    def test_rate_limit_retries_are_bounded_then_abort(self):
        ts = _fake_ts(None)
        attempts = 0

        def limited_pro_bar(**kw):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("HTTP 429 Too Many Requests")

        ts.pro_bar = limited_pro_bar
        with patch("runners.a_short_weekly_pipeline.time.sleep") as sleep:
            with self.assertRaises(SystemExit):
                _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")
        self.assertEqual(attempts, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_tushare_chinese_rate_limit_retries_are_bounded_then_abort(self):
        ts = _fake_ts(None)
        attempts = 0

        def limited_pro_bar(**kw):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("每分钟最多访问该接口")

        ts.pro_bar = limited_pro_bar
        with patch("runners.a_short_weekly_pipeline.time.sleep") as sleep:
            with self.assertRaises(SystemExit):
                _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")
        self.assertEqual(attempts, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_tushare_permission_error_does_not_retry(self):
        ts = _fake_ts(None)
        attempts = 0

        def denied_pro_bar(**kw):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("没有访问该接口的权限")

        ts.pro_bar = denied_pro_bar
        with patch("runners.a_short_weekly_pipeline.time.sleep") as sleep:
            with self.assertRaises(SystemExit):
                _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")
        self.assertEqual(attempts, 1)
        sleep.assert_not_called()

    def test_non_transient_exception_does_not_retry(self):
        ts = _fake_ts(None)
        attempts = 0

        def invalid_pro_bar(**kw):
            nonlocal attempts
            attempts += 1
            raise ValueError("bad local argument")

        ts.pro_bar = invalid_pro_bar
        with patch("runners.a_short_weekly_pipeline.time.sleep") as sleep:
            with self.assertRaises(SystemExit):
                _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")
        self.assertEqual(attempts, 1)
        sleep.assert_not_called()

    def test_future_bar_aborts(self):
        # R-ASHORT-WEEKLY-PRICE-SERIES-PIT-FRESHNESS-GAP: trade_date > as_of must abort.
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260109", "20260630"], "high": [3.0, 99.0],
                                    "low": [2.9, 1.0], "close": [3.0, 50.0]}))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")

    def test_stale_latest_bar_aborts(self):
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260101", "20260102"], "high": [3.0, 3.1],
                                    "low": [2.9, 2.95], "close": [2.95, 3.0]}))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20251201", "20260109")

    def test_noncalendar_trade_date_aborts(self):
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260631"], "high": [3.0], "low": [2.9], "close": [2.95]}))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20260101", "20260109")

    # --- reviewed intraday tolerance (R-ASHORT-WEEKLY-PRICE-SERIES-PIT-FRESHNESS-GAP) ---
    def test_intraday_prior_settled_bar_accepted(self):
        # as_of=Monday(0615), today's EOD not published → latest bar == prior trading day(Friday 0612)
        # is the latest SETTLED data and is accepted (not stale) when the tolerance is supplied.
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260611", "20260612"], "high": [3.0, 3.1],
                                    "low": [2.9, 2.95], "close": [2.95, 3.0]}))
        series, latest = _fetch_price_series(ts, object(), "600000.SH", "20260201", "20260615",
                                             accept_prior_settled_date="20260612")
        self.assertEqual(len(series), 2)                   # accepted: Friday-latest for a Monday as_of
        self.assertEqual(latest, "20260612")               # surfaces the prior-settled clock for lineage

    def test_intraday_tolerance_rejects_older_than_prior_settled(self):
        # the tolerance accepts ONLY the prior trading day; anything older is genuine staleness → abort.
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260610", "20260611"], "high": [3.0, 3.1],
                                    "low": [2.9, 2.95], "close": [2.95, 3.0]}))
        with self.assertRaises(SystemExit):                # latest 0611 < prior_settled 0612 → stale
            _fetch_price_series(ts, object(), "600000.SH", "20260201", "20260615",
                                accept_prior_settled_date="20260612")

    def test_intraday_tolerance_never_accepts_future_bar(self):
        # even with the tolerance set, a bar after as_of is never accepted (future-row guard precedes it).
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260612", "20260630"], "high": [3.0, 9.0],
                                    "low": [2.9, 1.0], "close": [3.0, 5.0]}))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20260201", "20260615",
                                accept_prior_settled_date="20260612")

    def test_no_tolerance_stays_strict(self):
        # default (no tolerance, e.g. historical replay): latest != as_of still aborts (unchanged gate).
        ts = _fake_ts(pd.DataFrame({"trade_date": ["20260611", "20260612"], "high": [3.0, 3.1],
                                    "low": [2.9, 2.95], "close": [2.95, 3.0]}))
        with self.assertRaises(SystemExit):
            _fetch_price_series(ts, object(), "600000.SH", "20260201", "20260615")

    def test_prev_trading_day_returns_latest_strictly_before_as_of(self):
        class _Pro:
            def trade_cal(self, **kw):
                return pd.DataFrame({"cal_date": ["20260605", "20260608", "20260609"]})
        self.assertEqual(_prev_trading_day(_Pro(), "20260609"), "20260608")   # excludes as_of itself

    def test_prev_trading_day_none_when_empty_or_error(self):
        class _Empty:
            def trade_cal(self, **kw):
                return pd.DataFrame({"cal_date": []})
        self.assertIsNone(_prev_trading_day(_Empty(), "20260609"))
        class _Boom:
            def trade_cal(self, **kw):
                raise RuntimeError("trade_cal api down")
        self.assertIsNone(_prev_trading_day(_Boom(), "20260609"))            # fail-closed to strict

    def test_main_future_price_row_writes_no_file(self):
        # Codex repro: a fake tushare through main(--confirm-fetch-authorized) must NOT write.
        fake = _fake_ts(pd.DataFrame({"trade_date": ["20260630"], "high": [99.0],
                                      "low": [1.0], "close": [50.0]}))
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH")])
            (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
            (Path(td) / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
            _write_account(Path(td) / "acct.json")
            out = Path(td) / "weekly.json"
            old = sys.modules.get("tushare")
            sys.modules["tushare"] = fake
            try:
                with self.assertRaises(SystemExit):
                    main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                          "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                          "--out", str(out), "--confirm-fetch-authorized",
                          "--skip-semantic"], pro_factory=lambda: object())  # no real cninfo fetch in unit test
            finally:
                if old is not None:
                    sys.modules["tushare"] = old
                else:
                    sys.modules.pop("tushare", None)
            self.assertFalse(out.exists())


class OverlayConsumerTests(unittest.TestCase):
    # R-ASHORT-WEEKLY-OVERLAY-CONSUMER-VALIDATION-GAP
    def _write(self, td, ov):
        p = Path(td) / "ov.json"
        p.write_text(json.dumps(ov), encoding="utf-8")
        return str(p)

    def test_valid_same_as_of_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            m = _load_validated_overlay(self._write(td, _valid_overlay(AS_OF)), AS_OF)
            self.assertIn("600000.SH", m)

    def test_future_or_stale_as_of_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit):  # future
                _load_validated_overlay(self._write(td, _valid_overlay("20260612")), AS_OF)
            with self.assertRaises(SystemExit):  # stale
                _load_validated_overlay(self._write(td, _valid_overlay("20260101")), AS_OF)

    def test_candidate_count_drift_rejected(self):
        ov = _valid_overlay(AS_OF)
        ov["candidate_count"] += 1
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                _load_validated_overlay(self._write(td, ov), AS_OF)

    def test_malformed_overlay_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(jsonschema.ValidationError):
                _load_validated_overlay(self._write(td, {"foo": 1}), AS_OF)


class SchemaTests(unittest.TestCase):
    def test_weekly_schema_valid(self):
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.Draft7Validator.check_schema(schema)

    def test_schema_requires_price_freshness_in_run_lineage(self):
        # Codex R-ASHORT-M67-INTRADAY-PRICE-FRESHNESS-LINEAGE-GAP: the price clock must be machine-readable
        # and the schema must reject a missing/invalid price_freshness block.
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        self.assertIn("price_freshness", schema["properties"]["run_lineage"]["required"])
        w = build_weekly_report([], AS_OF, GEN, iv_feed_ref="f")     # default lineage incl. price_freshness
        jsonschema.validate(w, schema)                               # valid as built
        del w["run_lineage"]["price_freshness"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(w, schema)                           # missing → rejected
        w2 = build_weekly_report([], AS_OF, GEN, iv_feed_ref="f")
        w2["run_lineage"]["price_freshness"]["mode"] = "bogus_mode"  # invalid enum
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(w2, schema)

    def test_weekly_design_doc_documents_schema_required_run_lineage(self):
        # R-ASHORT-WEEKLYSCREENING-M67-BUNDLE-CONTRACT-DRIFT R3: the active weekly pipeline DESIGN doc must
        # not drift back to omitting run_lineage / its account semantics while the schema requires them.
        # Doc↔schema sync guard: every schema-required run_lineage subfield must be named in the design doc.
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        self.assertIn("run_lineage", schema["required"])
        required_subfields = schema["properties"]["run_lineage"]["required"]
        design = (ROOT / "docs" / "a_short_weekly_pipeline_design_20260610.md").read_text(encoding="utf-8")
        self.assertIn("run_lineage", design)
        for field in required_subfields:        # analysis_input/selection_bucket/iv_feed/account_status/sizing_mode
            self.assertIn(field, design, f"weekly design doc omits schema-required run_lineage.{field}")

    def test_weekly_design_doc_marks_overlay_wiring_done_not_future(self):
        # R-ASHORT-WEEKLYSCREENING-M67-BUNDLE-CONTRACT-DRIFT R4: Slice A overlay data-loading is WIRED
        # (A-EGS/egs_main.py calls build_overlay_summary_from_panels; weekly_screening.ps1 passes --overlay;
        # the pipeline consumes it via _load_validated_overlay). Regression-pin so the active design doc cannot
        # drift back to listing overlay data-loading as 仍未来/future while README + code already wire it.
        import re
        design = (ROOT / "docs" / "a_short_weekly_pipeline_design_20260610.md").read_text(encoding="utf-8")
        self.assertIn("--overlay", design)                          # positive: overlay consumption documented
        for seg in re.findall(r"仍未来[^\n]*", design):              # no future-heading may list overlay
            self.assertNotIn("overlay", seg.lower(),
                             f"weekly design lists overlay as 仍未来 while code/README wire it: {seg!r}")


def _official(status, sev=None, rt="x", dd="20260601", url="u"):
    # full PIT official_structured evidence shape (matches build_official_structured output)
    evs = [{"source": "cninfo", "title": "t", "category": "c", "disclosure_date": dd,
            "url_or_pdf": url, "risk_type": rt, "severity": sev}] if sev else []
    return {"status": status, "events": evs, "had_pit_announcements": bool(evs)}


def _confirmed_regulatory(semantic, decision="confirmed_material", ts_code="600000.SH", event_indexes=(0,)):
    from engine.a_short_regulatory_advisory import event_fingerprint
    out = dict(semantic)
    out["regulatory_advisory"] = {"event_decisions": [
        {"event_fingerprint": event_fingerprint(ts_code, semantic["events"][index]), "decision": decision}
        for index in event_indexes
    ]}
    return out


def _web(status, risk, action="downgrade", n_sources=1):
    # Slice 2 engine input shape: {"web_llm": {...}, "sources": [...]} (DeepSeek 判官产出)
    src = [{"title": "t", "url": "http://x/%d" % i, "source_type": "sina"} for i in range(n_sources)]
    return {"web_llm": {"status": status, "risk_level": risk, "action": action}, "sources": src}


class SemanticIntoM67(unittest.TestCase):
    """Slice 1/1b: cninfo official_structured folded into M6.7 via the semantic_official family.
    official high WITH complete evidence (non-empty url_or_pdf)→否决; high with blank URL→待核 (pending,
    never veto); medium/low→待核 (no penalty, no clear); clear/unknown/None→neutral; never rescues;
    machine.layer.semantic_risk trace; consistency preserved by construction."""
    GEN = "2026-06-09T00:00:00+08:00"

    def _report(self, semantic, **over):
        from runners.a_short_phase5_engine import build_m67_report, validate_m67_consistency
        n = _normalized(**over)
        n["semantic"] = semantic
        r = build_m67_report(n, AS_OF, self.GEN)
        validate_m67_consistency(r)          # must ALWAYS stay consistent (table↔action, 否决→null, …)
        return r

    def test_confirmed_high_official_forces_fouju_and_nulls_trade(self):
        r = self._report(_confirmed_regulatory(_official("risk", "high", "立案调查")))
        self.assertEqual(r["m67"]["table"]["操作"], "否决")
        for k in ("股数", "入", "盈一", "盈二", "损"):
            self.assertIsNone(r["m67"]["table"][k])
        self.assertEqual(r["machine"]["layer"]["semantic_risk"]["impact"], "veto")
        self.assertIn("语义官方", r["m67"]["精简结论区"]["否决审查触发"])

    def test_unconfirmed_high_is_pending_not_veto(self):
        r = self._report(_official("risk", "high", "立案调查"))
        self.assertEqual(r["m67"]["table"]["操作"], "建仓")
        self.assertEqual(r["machine"]["layer"]["semantic_risk"]["impact"], "pending")
        self.assertEqual(r["machine"]["layer"]["semantic_risk"]["regulatory_confirmation"]["status"],
                         "pending_confirmation")

    def test_medium_official_is_pending_no_penalty(self):
        base = self._report(None)
        self.assertEqual(base["m67"]["table"]["操作"], "建仓")
        r = self._report(_official("risk", "medium", "fund_occupation"))
        self.assertEqual(r["m67"]["table"]["操作"], "建仓")                       # NOT downgraded
        self.assertEqual(r["m67"]["table"]["优先级"], base["m67"]["table"]["优先级"])  # star unchanged
        self.assertEqual(r["machine"]["layer"]["semantic_risk"]["impact"], "pending")
        self.assertIn("语义待核", r["m67"]["精简结论区"]["否决审查触发"])
        self.assertTrue(any("semantic_pending_review" in o
                            for o in r["machine"]["layer"]["observe_only"]))

    def test_clear_unknown_none_are_neutral(self):
        base = self._report(None)
        for sem in (_official("clear"), _official("unknown"), None):
            r = self._report(sem)
            self.assertEqual(r["m67"]["table"]["操作"], base["m67"]["table"]["操作"])
            self.assertEqual(r["machine"]["layer"]["semantic_risk"]["impact"], "none")
        self.assertEqual(self._report(None)["machine"]["layer"]["semantic_risk"]["official_status"],
                         "unknown")

    def test_semantic_never_rescues_base_hard_veto(self):
        from runners.a_short_phase5_engine import build_m67_report, validate_m67_consistency
        n = _normalized(); n["derived"]["hard_veto"] = True       # base = 否决
        n["semantic"] = _official("clear")                        # semantic clear must NOT upgrade
        r = build_m67_report(n, AS_OF, self.GEN); validate_m67_consistency(r)
        self.assertEqual(r["m67"]["table"]["操作"], "否决")

    def test_invalid_semantic_input_fails_closed(self):
        # R-ASHORT-M67-SEMANTIC-OFFICIAL-INPUT-CONSISTENCY-GAP + ...-EVIDENCE-SHAPE-GAP: malformed /
        # inconsistent / non-PIT / fabricated provider output must ValueError before any report
        # (no action↔trace contradiction; residual/non-PIT evidence cannot trigger M6.7 否决).
        from runners.a_short_phase5_engine import build_m67_report
        ev = {"source": "cninfo", "title": "t", "category": "c", "disclosure_date": "20260601",
              "url_or_pdf": "u", "risk_type": "立案", "severity": "high"}    # one valid PIT event
        bad_inputs = [
            {"status": "clear", "events": [ev]},                        # clear cannot carry events
            {"status": "unknown", "events": [ev]},                      # unknown cannot carry events
            {"events": [ev]},                                           # missing status
            {"status": "risk", "events": []},                           # risk must carry an event
            {"status": "risk", "events": [{**ev, "severity": "huge"}]}, # invalid severity
            {"status": "risk", "events": "abc"},                        # non-list events
            {"status": "risk", "events": ["x"]},                        # non-dict event
            "not-a-dict",                                               # non-dict semantic
            {"status": "risk", "events": [{"severity": "high", "risk_type": "x"}]},  # severity-only, no evidence
            {"status": "risk", "events": [{**ev, "source": "web"}]},    # non-official (manual/web) source
            {"status": "risk", "events": [{**ev, "disclosure_date": "20260701"}]},   # future date > as_of
            {"status": "risk", "events": [{**ev, "disclosure_date": "notadate"}]},   # non-canonical date
            {"status": "risk", "events": [{k: v for k, v in ev.items() if k != "risk_type"}]},  # missing risk_type
            {"status": "risk", "events": [{**ev, "risk_type": ""}]},                  # blank risk_type
            {"status": "risk", "events": [{**ev, "title": ""}]},                      # blank title
            {"status": "risk", "events": [{**ev, "category": ""}]},                   # blank category
            {"status": "risk", "events": [{**ev, "url_or_pdf": 123}]},                # url_or_pdf non-string
            {"status": "risk", "events": [{**ev, "title": "   "}]},                   # whitespace-only title
            {"status": "risk", "events": [ev], "had_pit_announcements": False},       # risk but no PIT
            {"status": "risk", "events": [ev]},                                       # missing had_pit_announcements
        ]
        # NOTE: blank url_or_pdf is NOT fail-closed here — Slice 1b approach A demotes it to 待核
        # (see test_high_with_empty_url_demotes_to_pending), it must not abort.
        for bad in bad_inputs:
            n = _normalized(); n["semantic"] = bad
            with self.assertRaises(ValueError):
                build_m67_report(n, AS_OF, self.GEN)

    def test_consumption_map_states_evidence_full_rule_not_generic(self):
        # R-ASHORT-M67-EVIDENCE-FULL-RUNTIME-EXPLANATION-DRIFT: the runtime consumption trace
        # (machine.consumption.semantic) must state the evidence-full rule, not the old generic
        # a generic "veto on any official high" — else the trace contradicts the blank-URL pending behavior.
        cm = self._report(_official("risk", "high", "立案调查"))["machine"]["consumption"]["semantic"]
        for kw in ("url_or_pdf", "证据齐全", "待核"):
            self.assertIn(kw, cm, f"consumption.semantic lost evidence-full anchor: {kw}")

    def test_high_with_empty_url_demotes_to_pending(self):
        # Slice 1b approach A: a high event with blank/whitespace url_or_pdf is evidence-incomplete →
        # 待核 (NOT 否决, NOT crash); only full-evidence high vetoes.
        for blank in ("", "   "):
            r = self._report(_official("risk", "high", "立案调查", url=blank))
            self.assertEqual(r["m67"]["table"]["操作"], "建仓")        # demoted, not 否决
            sr = r["machine"]["layer"]["semantic_risk"]
            self.assertEqual(sr["impact"], "pending")
            self.assertEqual(sr["evidence_incomplete_high"], 1)
            self.assertEqual(sr["severity_max"], "high")               # severity honest, impact demoted
            self.assertIn("待人工确认", r["m67"]["精简结论区"]["否决审查触发"])

    def test_full_url_high_vetoes_even_alongside_a_blank_url_high(self):
        sem = {"status": "risk", "had_pit_announcements": True, "events": [
            {"source": "cninfo", "title": "t", "category": "c", "disclosure_date": "20260601",
             "url_or_pdf": "u", "risk_type": "立案", "severity": "high"},
            {"source": "cninfo", "title": "t2", "category": "c", "disclosure_date": "20260601",
             "url_or_pdf": "", "risk_type": "处罚", "severity": "high"}]}
        r = self._report(_confirmed_regulatory(sem))
        self.assertEqual(r["m67"]["table"]["操作"], "否决")            # confirmed full-evidence high vetoes
        self.assertEqual(r["machine"]["layer"]["semantic_risk"]["impact"], "veto")

    def test_normalize_semantic_param_threads_through_build_weekly(self):
        n = normalize_candidate(_egs_candidate(), _series(), _overlay_row(), 55.0,
                                {"available_cash": 500000.0}, "震荡期",
                                semantic=_confirmed_regulatory(_official("risk", "high", "立案调查")))
        self.assertEqual(n["semantic"]["status"], "risk")
        w = build_weekly_report([n], AS_OF, self.GEN)
        self.assertEqual(w["reports"][0]["m67"]["table"]["操作"], "否决")


class SemanticWebLLMIntoM67(unittest.TestCase):
    """Slice 2: DeepSeek web_llm folded into M6.7 via the semantic_web_llm family.
    web risk/risk_candidate/headwind WITH sources → downgrade (**NEVER hard_veto**); tailwind/clear_light →
    no downgrade + never rescues hard risk; unknown/None → neutral; contract-violating/malformed web →
    neutralized with a trace flag (advisory non-blocking, NOT a fail-closed abort like official)."""
    GEN = "2026-06-09T00:00:00+08:00"

    def _report(self, web, **over):
        from runners.a_short_phase5_engine import build_m67_report, validate_m67_consistency
        n = _normalized(**over)
        n["semantic_web_llm"] = web
        r = build_m67_report(n, AS_OF, self.GEN)
        validate_m67_consistency(r)              # must ALWAYS stay consistent
        return r

    def _wtrace(self, r):
        return r["machine"]["layer"]["semantic_risk"]["web_llm"]

    def _web_downgrades(self, r):
        return [d for d in r["machine"]["layer"]["downgrade"] if "语义web/LLM" in d]

    def test_web_risk_with_sources_downgrades_never_vetoes(self):
        r = self._report(_web("risk", "high"))
        self.assertNotEqual(r["m67"]["table"]["操作"], "否决")     # web NEVER hard_veto
        self.assertEqual(self._wtrace(r)["impact"], "downgrade")
        self.assertTrue(self._web_downgrades(r))

    def test_web_risk_candidate_and_headwind_downgrade(self):
        for st in ("risk_candidate", "headwind"):
            r = self._report(_web(st, "medium"))
            self.assertEqual(self._wtrace(r)["impact"], "downgrade")
            self.assertNotEqual(r["m67"]["table"]["操作"], "否决")
            self.assertTrue(self._web_downgrades(r))

    def test_web_tailwind_and_clear_light_no_downgrade(self):
        for web in (_web("tailwind", "low", action="no_action"),
                    _web("clear_light", "none", action="no_action")):
            r = self._report(web)
            self.assertEqual(self._wtrace(r)["impact"], "none")
            self.assertFalse(self._web_downgrades(r))

    def test_web_unknown_and_none_are_neutral(self):
        for web in (_web("unknown", "unknown", action="no_action", n_sources=0), None):
            r = self._report(web)
            self.assertEqual(self._wtrace(r)["status"], "unknown")
            self.assertEqual(self._wtrace(r)["impact"], "none")
            self.assertFalse(self._web_downgrades(r))

    def test_web_tailwind_never_rescues_confirmed_official_advisory_veto(self):
        from runners.a_short_phase5_engine import build_m67_report, validate_m67_consistency
        n = _normalized()
        n["semantic"] = _confirmed_regulatory(_official("risk", "high", "立案调查"))
        n["semantic_web_llm"] = _web("tailwind", "low", action="no_action")
        r = build_m67_report(n, AS_OF, self.GEN); validate_m67_consistency(r)
        self.assertEqual(r["m67"]["table"]["操作"], "否决")        # web tailwind cannot upgrade

    def test_web_never_rescues_base_hard_veto(self):
        from runners.a_short_phase5_engine import build_m67_report, validate_m67_consistency
        n = _normalized(); n["derived"]["hard_veto"] = True
        n["semantic_web_llm"] = _web("tailwind", "low", action="no_action")
        r = build_m67_report(n, AS_OF, self.GEN); validate_m67_consistency(r)
        self.assertEqual(r["m67"]["table"]["操作"], "否决")

    def test_invalid_web_neutralized_not_aborted(self):
        # advisory non-blocking: contract-violating / malformed web is NEUTRALIZED (trace flag), NOT raised
        # (unlike official's fail-closed abort). Each invalid shape → impact none + invalid_neutralized=True.
        bad = [
            _web("risk", "none"),                                              # risk ⇒ low/med/high
            {"web_llm": {"status": "risk", "risk_level": "high", "action": "downgrade"}, "sources": []},  # assessed needs sources
            _web("clear_light", "high", action="no_action"),                  # clear_light ⇒ none
            {"web_llm": {"status": "risk"}, "sources": [{"title": "t", "url": "u"}]},  # missing keys
            {"web_llm": "notdict", "sources": []},                            # web_llm non-dict
            {"sources": [{"title": "t", "url": "u"}]},                         # missing web_llm
        ]
        for w in bad:
            r = self._report(w)                                               # must NOT raise
            tr = self._wtrace(r)
            self.assertTrue(tr["invalid_neutralized"], f"not neutralized: {w}")
            self.assertEqual(tr["impact"], "none")
            self.assertEqual(tr["status"], "unknown")
            self.assertFalse(self._web_downgrades(r))

    def test_web_trace_populated_from_judgment(self):
        r = self._report(_web("risk", "medium", action="observe", n_sources=2))
        tr = self._wtrace(r)
        self.assertEqual((tr["status"], tr["risk_level"], tr["action"]), ("risk", "medium", "observe"))
        self.assertEqual(tr["sources_count"], 2)
        self.assertFalse(tr["invalid_neutralized"])

    def test_consumption_map_states_web_llm_rule(self):
        cm = self._report(None)["machine"]["consumption"]["semantic"]
        for kw in ("semantic_web_llm", "downgrade", "hard_veto"):
            self.assertIn(kw, cm, f"consumption.semantic lost web_llm anchor: {kw}")

    def test_web_provider_threads_through_normalize_and_build_weekly(self):
        n = normalize_candidate(_egs_candidate(), _series(), _overlay_row(), 55.0,
                                {"available_cash": 500000.0}, "震荡期",
                                semantic_web_llm=_web("risk", "high"))
        self.assertEqual(n["semantic_web_llm"]["web_llm"]["status"], "risk")
        w = build_weekly_report([n], AS_OF, self.GEN)
        wt = w["reports"][0]["machine"]["layer"]["semantic_risk"]["web_llm"]
        self.assertEqual(wt["impact"], "downgrade")


class DeepSeekWebProviderWiring(unittest.TestCase):
    """Slice 2 pipeline glue: _build_deepseek_web_llm_provider (em news fetch + DeepSeek judge, non-blocking).
    Injected fake news_fetcher(codes, names, as_of, lookback) + fake ds_client → no network. Covers per-code
    judge, no-items→None, no-key→whole-layer-None, fetch-failure→None, main-board Top15 gate (non-blocking)."""
    def _client(self, content):
        from tests.test_a_short_deepseek_semantic_adapter import _FakeClient
        return _FakeClient(content)

    def test_provider_judges_per_code_and_unknown_is_none(self):
        from runners.a_short_weekly_pipeline import _build_deepseek_web_llm_provider
        raws = [{"ts_code": "600000.SH", "ok": True, "items": [{"title": "公司被立案调查", "url": "u"}]},
                {"ts_code": "600001.SH", "ok": True, "items": []}]      # no items → judge unknown → None
        prov = _build_deepseek_web_llm_provider(
            ["600000.SH", "600001.SH"], {"600000.SH": "A", "600001.SH": "B"}, AS_OF,
            news_fetcher=lambda codes, names, as_of, lookback: raws,
            ds_client=self._client('{"status":"risk","risk_level":"high","action":"downgrade","summary":"立案"}'))
        self.assertIsNotNone(prov)
        self.assertEqual(prov("600000.SH")["web_llm"]["status"], "risk")
        self.assertEqual(prov("600000.SH")["sources"][0]["source_type"], "em")   # em-sourced evidence
        self.assertIsNone(prov("600001.SH"))                            # unknown → None (中性)

    def test_provider_none_without_client(self):
        import os
        from unittest import mock
        from runners.a_short_weekly_pipeline import _build_deepseek_web_llm_provider
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)                    # no key + no injected client
            prov = _build_deepseek_web_llm_provider(
                ["600000.SH"], {}, AS_OF, news_fetcher=lambda codes, names, as_of, lookback: [])
        self.assertIsNone(prov)                                         # whole web layer unknown (non-blocking)

    def test_provider_none_on_fetch_failure(self):
        from runners.a_short_weekly_pipeline import _build_deepseek_web_llm_provider
        def boom(codes, names, as_of, lookback):
            raise RuntimeError("em down")
        prov = _build_deepseek_web_llm_provider(["600000.SH"], {}, AS_OF, news_fetcher=boom,
                                                ds_client=self._client("{}"))
        self.assertIsNone(prov)                                         # fetch fail → non-blocking None

    def test_provider_filters_to_main_board_top15(self):
        # R-ASHORT-M67-DEEPSEEK-WEBLLM-TOP15-SCOPE-BYPASS: provider must reuse the official main_board_top15
        # gate BEFORE any em fetch / DeepSeek judge — only the deduped main-board Top15 is fetched, and a
        # non-main-board (or beyond-cap) candidate gets neutral None even if the weekly report still lists it.
        from runners.a_short_weekly_pipeline import _build_deepseek_web_llm_provider
        from runners.a_short_semantic_risk_probe import main_board_top15
        codes = [f"60{i:04d}.SH" for i in range(20)] + ["300750.SZ", "688111.SH"]  # 20 main + ChiNext + STAR
        main_codes, _ = main_board_top15(codes)
        self.assertLessEqual(len(main_codes), 15)
        self.assertNotIn("300750.SZ", main_codes)
        seen = {}
        def fetcher(cs, names, as_of, lookback):
            seen["codes"] = list(cs)
            return [{"ts_code": c, "ok": True, "items": [{"title": "公司被立案", "url": "u"}]} for c in cs]
        prov = _build_deepseek_web_llm_provider(
            codes, {}, AS_OF, news_fetcher=fetcher,
            ds_client=self._client('{"status":"risk","risk_level":"high","action":"downgrade","summary":"x"}'))
        self.assertEqual(seen["codes"], list(main_codes))    # fetcher 只收过滤后的主板 Top15(不含 300750/688/超界)
        self.assertNotIn("300750.SZ", seen["codes"])
        self.assertIsNone(prov("300750.SZ"))                 # 非主板候选 → 中性 None(不抓不判)
        self.assertIsNotNone(prov(main_codes[0]))            # 主板 Top15 内 → 正常判


class CashAllocationTests(unittest.TestCase):
    """#3 全局现金分配:多只建仓按区间上沿统一消耗 available_cash,确定性排序,归零转观察,过 schema+validator。"""
    def _builds(self):
        # Cash-allocation tests isolate the cash rule.  Give each synthetic
        # candidate complete, low-risk and mutually diversified M5.5 facts so
        # the portfolio fail-closed path is not what decides these assertions.
        rows = [_normalized("600000.SH"), _normalized("600519.SH"), _normalized("601318.SH")]
        for row, sw_l2_key in zip(rows, ("bank", "consumer", "health")):
            row["portfolio_risk_facts"] = {
                "source": "cash_allocation_fixture",
                "sw_l2_key": sw_l2_key,
                "circ_mv_rmb": 10_000_000_000.0,
                "margin_balance_to_float_mv_pct": 1.0,
                "is_large_index_component": False,
            }
        return rows

    def test_no_account_no_cash_allocation(self):
        w = build_weekly_report([_normalized()], AS_OF, GEN)        # 默认 absent lineage + available_cash None
        self.assertIsNone(w["cash_allocation"])
        validate_weekly_report(w, _feed())                          # observation-only 一致(absent⟺cash_allocation None)

    def test_global_cash_allocation_demotes_under_budget_and_validates(self):
        # 全局现金不足 3 只满额 → 排序 rank1 满、靠后不足 → 转观察;sized lineage + 整份过 schema/validator。
        w = build_weekly_report(self._builds(), AS_OF, GEN, iv_feed_ref="iv_feed.json",
                                run_lineage=_sized_lineage(), available_cash=150000.0)
        ops = [r["m67"]["table"]["操作"] for r in w["reports"]]
        self.assertTrue(all(o in ("建仓", "观察") for o in ops))
        self.assertEqual(w["reports"][0]["m67"]["table"]["操作"], "建仓")   # rank1(index 0)满足
        self.assertIn("观察", ops)                                          # 现金不足 → 至少一只转观察(非伪建仓)
        cs = w["cash_allocation"]
        self.assertEqual(cs["available_cash_start"], 150000.0)
        self.assertLessEqual(cs["allocated_cash_total"], 150000.0 + 1e-6)
        self.assertGreaterEqual(cs["remaining_cash"], -1e-6)
        for r in w["reports"]:
            if r["m67"]["table"]["操作"] == "建仓":                          # 存活建仓:股数正 + 审计字段齐
                self.assertGreaterEqual(r["m67"]["table"]["股数"], 100)
                pl = r["machine"]["entry_exit_size_star"]["plan"]
                for fld in ("cash_allocation_rank", "cash_budget_used", "raw_shares", "allocated_shares"):
                    self.assertIsNotNone(pl.get(fld))
        with tempfile.TemporaryDirectory() as td:    # write_weekly_report = jsonschema + validate_weekly_report
            write_weekly_report(w, _feed(), str(Path(td) / "w.json"))

    def test_cash_allocation_deterministic(self):
        a = build_weekly_report(self._builds(), AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=150000.0)
        b = build_weekly_report(self._builds(), AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=150000.0)
        self.assertEqual([r["m67"]["table"]["股数"] for r in a["reports"]],
                         [r["m67"]["table"]["股数"] for r in b["reports"]])
        self.assertEqual(a["cash_allocation"], b["cash_allocation"])

    def test_ample_cash_demotes_nothing(self):
        # C 反向失败:现金充裕时不得过度降级——全部保持建仓,剩余现金>0(防把够钱的建仓错降为观察)。
        w = build_weekly_report(self._builds(), AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=10_000_000.0)
        ops = [r["m67"]["table"]["操作"] for r in w["reports"]]
        self.assertTrue(all(o == "建仓" for o in ops))
        self.assertGreater(w["cash_allocation"]["remaining_cash"], 0)
        validate_weekly_report(w, _feed())

    def test_final_shortfall_never_promotes_watch_into_cash_allocation(self):
        rows = self._builds()
        rows[1]["analysis_role"] = "watch"
        rows[2]["analysis_role"] = "watch"
        w = build_weekly_report(rows, AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=10_000_000.0)
        by_code = {r["ts_code"]: r for r in w["reports"]}
        self.assertEqual(by_code["600000.SH"]["m67"]["table"]["操作"], "建仓")
        for code in ("600519.SH", "601318.SH"):
            self.assertEqual(by_code[code]["m67"]["table"]["操作"], "观察")
            self.assertIn("非 final，仅观察", by_code[code]["machine"]["entry_exit_size_star"]["reject_reason"])
        allocated_codes = {r["ts_code"] for r in w["reports"]
                           if r["m67"]["table"]["操作"] == "建仓"}
        self.assertEqual(allocated_codes, {"600000.SH"})
        validate_weekly_report(w, _feed())

    def test_sized_lineage_without_cash_allocation_rejected(self):
        # 对抗矛盾①:声称账户定量(sized)却无 cash_allocation → 必拒(防静默跳过全局分配,重开过度分配 bug)。
        w = build_weekly_report(self._builds(), AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=None)
        self.assertIsNone(w["cash_allocation"])
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_observation_lineage_with_cash_allocation_rejected(self):
        # 对抗矛盾②:声称无账户(observation-only,默认 lineage)却带 cash_allocation 对象 → 必拒。
        w = build_weekly_report(self._builds(), AS_OF, GEN, available_cash=150000.0)   # 默认 absent lineage
        self.assertIsNotNone(w["cash_allocation"])
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def _sized_weekly(self):
        return build_weekly_report(self._builds(), AS_OF, GEN, run_lineage=_sized_lineage(), available_cash=150000.0)

    def _first_build(self, w):
        return next(r for r in w["reports"] if r["m67"]["table"]["操作"] == "建仓")

    def test_forged_allocated_shares_rejected(self):
        # audit-math:伪造 allocated_shares(≠ shares/table 股数)→ 必拒(防伪造分配冒充已做全局现金分配)。
        w = self._sized_weekly()
        self._first_build(w)["machine"]["entry_exit_size_star"]["plan"]["allocated_shares"] = 999999
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_forged_cash_budget_used_rejected(self):
        # audit-math:伪造 cash_budget_used(≠ round(shares×entry_high,2))→ 必拒。
        w = self._sized_weekly()
        self._first_build(w)["machine"]["entry_exit_size_star"]["plan"]["cash_budget_used"] = 0.01
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_forged_weekly_cash_summary_rejected(self):
        # audit-math:伪造 cash_allocation 摘要(allocated_cash_total/remaining_cash 与 Σ 不符)→ 必拒。
        w = self._sized_weekly()
        w["cash_allocation"]["allocated_cash_total"] = 1.0
        w["cash_allocation"]["remaining_cash"] = 999999.0
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())


class _StubDividendPro:
    """测试用 tushare pro 桩:dividend() 返回注入的 DataFrame(测 _fetch_dividends 的列/过滤逻辑,不抓网络)。"""
    def __init__(self, df):
        self._df = df

    def dividend(self, **kwargs):
        return self._df


class ExDivNoticeTests(unittest.TestCase):
    """#1 除权除息提示(advisory,不改决策):PIT(ann≤as_of)+ 窗口(as_of..as_of+14)+ 每票最近;过 schema/validator/render。"""
    def _prov(self, mapping):
        return lambda code: mapping.get(code, [])

    def test_in_window_pit_announced(self):
        prov = self._prov({"600000.SH": [{"ann_date": "20260601", "ex_date": "20260615"}]})
        n = _ex_div_notices([("600000.SH", "甲")], AS_OF, prov)     # AS_OF=20260609 → 6 天
        self.assertEqual(len(n), 1)
        self.assertEqual((n[0]["ex_date"], n[0]["days_to_ex"]), ("20260615", 6))

    def test_outside_window_excluded(self):
        prov = self._prov({"600000.SH": [{"ann_date": "20260601", "ex_date": "20260710"}]})   # >14 天
        self.assertEqual(_ex_div_notices([("600000.SH", "甲")], AS_OF, prov), [])

    def test_lookahead_announcement_excluded(self):
        # ann_date 晚于 as_of → 该除权在 as_of 时尚未公告,提示即 look-ahead → 剔除
        prov = self._prov({"600000.SH": [{"ann_date": "20260612", "ex_date": "20260615"}]})
        self.assertEqual(_ex_div_notices([("600000.SH", "甲")], AS_OF, prov), [])

    def test_bad_ex_date_skipped_no_fabrication(self):
        prov = self._prov({"600000.SH": [{"ann_date": "20260601", "ex_date": "2026XX15"}]})
        self.assertEqual(_ex_div_notices([("600000.SH", "甲")], AS_OF, prov), [])

    def test_no_provider_empty(self):
        self.assertEqual(_ex_div_notices([("600000.SH", "甲")], AS_OF, None), [])

    def test_nearest_per_code(self):
        prov = self._prov({"600000.SH": [{"ann_date": "20260601", "ex_date": "20260620"},
                                          {"ann_date": "20260601", "ex_date": "20260611"}]})
        n = _ex_div_notices([("600000.SH", "甲")], AS_OF, prov)
        self.assertEqual([x["ex_date"] for x in n], ["20260611"])     # 同票取最近一次

    def test_weekly_attach_schema_validator_render(self):
        w = build_weekly_report([_normalized()], AS_OF, GEN)
        w["ex_div_notices"] = [{"ts_code": "600000.SH", "name": "甲", "ex_date": "20260615", "days_to_ex": 6}]
        with tempfile.TemporaryDirectory() as td:    # write = jsonschema + validate_weekly_report
            write_weekly_report(w, _feed(), str(Path(td) / "w.json"))
        md = render_weekly_markdown(w)
        self.assertIn("除权除息提示", md)
        self.assertIn("20260615", md)

    def test_validator_rejects_inconsistent_days(self):
        w = build_weekly_report([_normalized()], AS_OF, GEN)
        w["ex_div_notices"] = [{"ts_code": "600000.SH", "name": "甲", "ex_date": "20260615", "days_to_ex": 99}]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_missing_ann_date_no_notice(self):
        # PIT-EVIDENCE-GAP 修复:无 ann_date → 无法证 as_of 时已公告 → 不提示(防 look-ahead)
        prov = self._prov({"600000.SH": [{"ex_date": "20260615"}]})   # 缺 ann_date
        self.assertEqual(_ex_div_notices([("600000.SH", "甲")], AS_OF, prov), [])

    def test_validator_rejects_foreign_ts(self):
        # VALIDATOR-GUARD-GAP 修复:提示 ts_code 不在本周候选/持仓 → 必拒(张冠李戴)
        w = build_weekly_report([_normalized()], AS_OF, GEN)           # report ts=600000.SH
        w["ex_div_notices"] = [{"ts_code": "999999.SH", "name": "无关", "ex_date": "20260615", "days_to_ex": 6}]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_rejects_far_window(self):
        # VALIDATOR-GUARD-GAP 修复:超 14 日窗口的提示 → 必拒(20260609→20260709=30 天)
        w = build_weekly_report([_normalized()], AS_OF, GEN)
        w["ex_div_notices"] = [{"ts_code": "600000.SH", "name": "甲", "ex_date": "20260709", "days_to_ex": 30}]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_blank_or_invalid_ann_date_no_notice(self):
        # PIT 证据:空白/非法 ann_date 同样无法证 PIT → 不提示
        for bad in ("", "   ", "2026XX01"):
            prov = self._prov({"600000.SH": [{"ann_date": bad, "ex_date": "20260615"}]})
            self.assertEqual(_ex_div_notices([("600000.SH", "甲")], AS_OF, prov), [], f"ann={bad!r}")

    def test_fetch_dividends_fail_closed_missing_div_proc_column(self):
        # _fetch_dividends fail-closed:provider 响应缺 div_proc 列 → 无法证 实施 → []
        df = pd.DataFrame([{"ts_code": "600000.SH", "ann_date": "20260601", "ex_date": "20260615"}])
        self.assertEqual(_fetch_dividends(_StubDividendPro(df), "600000.SH"), [])

    def test_fetch_dividends_filters_to_shishi(self):
        df = pd.DataFrame([{"ts_code": "600000.SH", "ann_date": "20260601", "div_proc": "预案", "ex_date": "20260615"},
                           {"ts_code": "600000.SH", "ann_date": "20260602", "div_proc": "实施", "ex_date": "20260616"}])
        self.assertEqual(_fetch_dividends(_StubDividendPro(df), "600000.SH"),
                         [{"ann_date": "20260602", "ex_date": "20260616"}])   # 仅 实施

    def test_validator_accepts_manual_review_holding_notice(self):
        # 正向:提示 ts_code 属 holdings_manual_review(无价持仓)→ validator 接受(在周报 universe 内)
        w = build_weekly_report([_normalized()], AS_OF, GEN)
        w["holdings_manual_review"] = [{"ts_code": "600519.SH", "name": "乙", "reason": "停牌"}]
        w["ex_div_notices"] = [{"ts_code": "600519.SH", "name": "乙", "ex_date": "20260615", "days_to_ex": 6}]
        validate_weekly_report(w, _feed())     # 不 raise


class ExclusionSummaryTests(unittest.TestCase):
    """4.2 Round2: 上游过滤批次级 exclusion_summary(counts-only, public_tracked, evidence-tied, fail-closed)。"""

    _AI_REF = "research/results/a_short/20260609/analysis_input.json"

    def _weekly_excl(self, counts):
        w = _weekly()
        w["run_lineage"]["analysis_input"] = self._AI_REF    # exclusion_summary 须有源 lineage
        es = _build_exclusion_summary(counts, AS_OF)
        if es is not None:
            w["exclusion_summary"] = es
        return w

    def test_build_from_counts_drops_zero(self):
        es = _build_exclusion_summary(
            {"holder_reduction_veto_10d": 12, "unlock": 5, "suspended": 3, "relisted": 0}, AS_OF)
        self.assertEqual(es["total_excluded"], 20)
        self.assertEqual(len(es["by_reason"]), 3)            # relisted 0 dropped
        self.assertIn("10日减持 12 只", es["m67_text"])
        self.assertEqual(es["evidence_ref"]["kind"], "lineage_key")
        self.assertEqual(es["evidence_ref"]["as_of"], AS_OF)
        self.assertTrue(all(r["privacy_class"] == "public_tracked" for r in es["by_reason"]))

    def test_build_zero_returns_none(self):
        self.assertIsNone(_build_exclusion_summary({}, AS_OF))
        self.assertIsNone(_build_exclusion_summary({"unlock": 0, "suspended": 0}, AS_OF))

    def test_build_fails_closed_on_unknown_nonzero_key(self):
        # 完整性: 未映射的上游过滤原因(count>0)绝不静默丢 → raise
        with self.assertRaises(ValueError):
            _build_exclusion_summary({"unlock": 1, "stage3_policy_veto": 4}, AS_OF)
        es = _build_exclusion_summary({"unlock": 1, "stage3_policy_veto": 0}, AS_OF)  # 0 无害
        self.assertEqual(es["total_excluded"], 1)

    def test_legacy_rank_keys_are_known_post_l0_and_ignored(self):
        es = _build_exclusion_summary({
            "unlock": 2, "l1_industry_leader": 601, "l2_quality_risk": 255,
            "rank_unexpected": 0,
        }, AS_OF)
        self.assertEqual(es["total_excluded"], 2)
        self.assertEqual([r["source_field"] for r in es["by_reason"]], ["share_float_unlock"])

    def test_schema_and_validator_accept(self):
        w = self._weekly_excl({"unlock": 2, "suspended": 1})
        jsonschema.validate(w, json.load(open(SCHEMA_PATH, encoding="utf-8")))
        validate_weekly_report(w, _feed())                   # no raise

    def test_absent_is_valid(self):
        w = _weekly()                                        # 无 exclusion_summary → 向后兼容
        jsonschema.validate(w, json.load(open(SCHEMA_PATH, encoding="utf-8")))
        validate_weekly_report(w, _feed())

    def test_schema_requires_evidence_ref(self):
        w = self._weekly_excl({"unlock": 2})
        del w["exclusion_summary"]["evidence_ref"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(w, json.load(open(SCHEMA_PATH, encoding="utf-8")))

    def test_validator_rejects_missing_evidence_ref(self):
        w = self._weekly_excl({"unlock": 2})
        del w["exclusion_summary"]["evidence_ref"]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_rejects_evidence_as_of_drift(self):
        w = self._weekly_excl({"unlock": 2})
        w["exclusion_summary"]["evidence_ref"]["as_of"] = "20250101"
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_rejects_missing_lineage(self):
        w = self._weekly_excl({"unlock": 2})
        w["run_lineage"]["analysis_input"] = ""              # 无源 lineage → 无法溯源
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_schema_rejects_artifact_path_kind(self):
        # 本轮 evidence 仅 lineage_key:artifact_path kind 在 schema 即被拒(可解析 artifact 实现前不开放)
        w = self._weekly_excl({"unlock": 2})
        w["exclusion_summary"]["evidence_ref"] = {
            "kind": "artifact_path", "value": "does/not/exist.json", "as_of": AS_OF}
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(w, json.load(open(SCHEMA_PATH, encoding="utf-8")))

    def test_validator_rejects_artifact_path_kind(self):
        # validator 独立把关(不止 schema):非 lineage_key kind 直接拒
        w = self._weekly_excl({"unlock": 2})
        w["exclusion_summary"]["evidence_ref"]["kind"] = "artifact_path"
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_rejects_wrong_lineage_key(self):
        # 乱写 value(非受审 dotted path)即使非空也拒 — 堵"evidence 可伪造"残留
        w = self._weekly_excl({"unlock": 2})
        w["exclusion_summary"]["evidence_ref"]["value"] = "nonsense.not.parseable"
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_rejects_total_mismatch(self):
        w = self._weekly_excl({"unlock": 2})
        w["exclusion_summary"]["total_excluded"] = 99
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_rejects_as_of_drift(self):
        w = self._weekly_excl({"unlock": 2})
        w["exclusion_summary"]["as_of"] = "20250101"
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_rejects_zero_count_entry(self):
        w = self._weekly_excl({"unlock": 2})
        w["exclusion_summary"]["by_reason"].append(
            {"source_field": "x", "stage": "l0_filter", "veto_class": "production_hard_veto",
             "count": 0, "pit_basis": "disclosure_date", "production_effect_enabled": True,
             "privacy_class": "public_tracked"})
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_render_contains_counts(self):
        w = self._weekly_excl({"holder_reduction_veto_10d": 7})
        md = render_weekly_markdown(w)
        self.assertIn("本轮上游过滤摘要", md)
        self.assertIn("10日减持 7 只", md)
        self.assertIn("holder_reduction_veto_10d", md)

    def test_visibility_exclusivity_row_vs_batch(self):
        # 4.2 第3轮:同一 source_field 既 row operation_impact 又 batch_exclusion(exclusion_summary)→ 互斥 guard raise
        # (同一风险同一运行只能一种可见性形态;构造合法 web priority_down 候选 impact 人为撞 batch 的 source_field)
        w = self._weekly_excl({"unlock": 2})        # exclusion by_reason source_field = "share_float_unlock"
        imp = _semantic_operation_impacts(None, {"status": "risk", "risk_level": "high"}, True,
                                          w["as_of"], "new_entry")[0]
        imp["source_field"] = "share_float_unlock"  # 人为与 batch_exclusion 同 source
        w["reports"][0].setdefault("machine", {})["operation_impact"] = [imp]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())


class UpcomingEventsTests(unittest.TestCase):
    """4.2 forward_events 第1刀: 未来已知事件日历(限售解禁, analysis-only advisory, PIT, unknown-not-clear)。"""

    def _ue_event(self, ts="600000.SH", event_date="20260615", observed_at="20260601", days=6, event_type="limit_unlock"):
        return {"ts_code": ts, "name": "测试", "event_type": event_type, "event_date": event_date,
                "observed_at": observed_at, "source_id": _FORWARD_EVENT_SOURCE_ID[event_type],
                "expected_effect": "manual_review", "confidence": _FORWARD_EVENT_CONFIDENCE[event_type], "days_to_event": days}

    def _weekly_ue(self, status="checked", events=None):
        w = _weekly()
        w["upcoming_events"] = {"as_of": AS_OF, "status": status, "events": events or []}
        return w

    # ── builder(PIT / unknown-not-clear / 每票取最近)──
    def test_builder_provider_none_unknown(self):
        ue = _upcoming_events([("600000.SH", "x")], AS_OF, None)
        self.assertEqual(ue["status"], "unknown_or_unavailable")        # 没查 → unknown(绝不当无事件)
        self.assertEqual(ue["events"], [])

    def test_builder_all_fetch_fail_unknown(self):
        # 漏洞#1 修复(unknown-not-clear): provider 非 None 但**所有票取数失败**(返回 None/抛)→ status unknown(不当「无未来事件」)
        self.assertEqual(_upcoming_events([("600000.SH", "x"), ("600001.SH", "y")], AS_OF, lambda c: None)["status"],
                         "unknown_or_unavailable")
        def _boom(c):
            raise RuntimeError("x")
        self.assertEqual(_upcoming_events([("600000.SH", "x")], AS_OF, _boom)["status"], "unknown_or_unavailable")

    def test_builder_partial_fail_empty_marks_unchecked(self):
        # 一票查成(真无→[])+ 一票失败(None)→ checked(有查成,不整体 unknown)但失败票进 unchecked_codes(per-code unknown-not-clear)
        prov = lambda c: [] if c == "600000.SH" else None
        ue = _upcoming_events([("600000.SH", "x"), ("600001.SH", "y")], AS_OF, prov)
        self.assertEqual(ue["status"], "checked")
        self.assertEqual(ue["events"], [])
        self.assertEqual([u["ts_code"] for u in ue["unchecked_codes"]], ["600001.SH"])   # 失败票显式列出,不静默当无事件

    def test_builder_partial_fail_with_events_marks_unchecked(self):
        # 一票查成有解禁 + 一票失败 → checked + 该 event 落地 + 失败票仍进 unchecked(查成的 event 不被部分失败丢掉)
        prov = lambda c: ([{"ann_date": "20260601", "float_date": "20260615"}] if c == "600000.SH" else None)
        ue = _upcoming_events([("600000.SH", "x"), ("600001.SH", "y")], AS_OF, prov)
        self.assertEqual(ue["status"], "checked")
        self.assertEqual([e["ts_code"] for e in ue["events"]], ["600000.SH"])
        self.assertEqual([u["ts_code"] for u in ue["unchecked_codes"]], ["600001.SH"])

    def test_builder_emits_unlock_event(self):
        prov = lambda c: [{"ann_date": "20260601", "float_date": "20260615"}] if c == "600000.SH" else []
        ue = _upcoming_events([("600000.SH", "x")], AS_OF, prov)
        self.assertEqual(ue["status"], "checked")
        e = ue["events"][0]
        self.assertEqual((e["event_type"], e["event_date"], e["observed_at"], e["days_to_event"]),
                         ("limit_unlock", "20260615", "20260601", 6))

    def test_builder_lookahead_ann_skipped(self):
        prov = lambda c: [{"ann_date": "20260610", "float_date": "20260615"}]    # ann > as_of → look-ahead
        self.assertEqual(_upcoming_events([("600000.SH", "x")], AS_OF, prov)["events"], [])

    def test_builder_outside_window_skipped(self):
        prov = lambda c: [{"ann_date": "20260601", "float_date": "20260720"}]    # > as_of + 21
        self.assertEqual(_upcoming_events([("600000.SH", "x")], AS_OF, prov)["events"], [])

    def test_builder_past_event_skipped(self):
        prov = lambda c: [{"ann_date": "20260601", "float_date": "20260601"}]    # float < as_of
        self.assertEqual(_upcoming_events([("600000.SH", "x")], AS_OF, prov)["events"], [])

    def test_builder_nearest_per_code(self):
        prov = lambda c: [{"ann_date": "20260601", "float_date": "20260620"},
                          {"ann_date": "20260601", "float_date": "20260612"}]
        ue = _upcoming_events([("600000.SH", "x")], AS_OF, prov)
        self.assertEqual(len(ue["events"]), 1)
        self.assertEqual(ue["events"][0]["event_date"], "20260612")     # 取最近

    def test_builder_missing_ann_skipped(self):
        prov = lambda c: [{"ann_date": None, "float_date": "20260615"}]          # 无公告日 → 无法 PIT,跳过
        self.assertEqual(_upcoming_events([("600000.SH", "x")], AS_OF, prov)["events"], [])

    # ── schema + validator ──
    def test_schema_and_validator_accept(self):
        w = self._weekly_ue(events=[self._ue_event()])
        _attach_forward_event_impacts(w, AS_OF)                         # 落地(满足 row no-dangling 强制;event ts ∈ reports)
        jsonschema.validate(w, json.load(open(SCHEMA_PATH, encoding="utf-8")))
        validate_weekly_report(w, _feed())

    def test_schema_and_validator_accept_unchecked_codes(self):
        # per-code coverage:checked + unchecked_codes(ts ∈ universe)→ schema + validator 接受
        w = self._weekly_ue(events=[self._ue_event()])
        _attach_forward_event_impacts(w, AS_OF)
        w["upcoming_events"]["unchecked_codes"] = [{"ts_code": "600000.SH", "name": "测试", "event_type": "limit_unlock"}]
        jsonschema.validate(w, json.load(open(SCHEMA_PATH, encoding="utf-8")))
        validate_weekly_report(w, _feed())

    def test_validator_unchecked_foreign_ts_rejected(self):
        w = self._weekly_ue(events=[self._ue_event()])
        _attach_forward_event_impacts(w, AS_OF)
        w["upcoming_events"]["unchecked_codes"] = [{"ts_code": "000001.SZ", "name": "外", "event_type": "limit_unlock"}]   # 不在 universe(张冠李戴)
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_absent_is_valid(self):
        w = _weekly()                                                   # 无 upcoming_events → 向后兼容
        jsonschema.validate(w, json.load(open(SCHEMA_PATH, encoding="utf-8")))
        validate_weekly_report(w, _feed())

    def test_validator_unknown_with_events_rejected(self):
        w = self._weekly_ue(status="unknown_or_unavailable", events=[self._ue_event()])
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_foreign_ts_rejected(self):
        w = self._weekly_ue(events=[self._ue_event(ts="600999.SH")])    # 不在候选/持仓 → 张冠李戴
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_observed_after_as_of_rejected(self):
        w = self._weekly_ue(events=[self._ue_event(observed_at="20260610")])   # PIT: observed > as_of
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_event_before_as_of_rejected(self):
        w = self._weekly_ue(events=[self._ue_event(event_date="20260601")])    # event_date < as_of
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_days_mismatch_rejected(self):
        w = self._weekly_ue(events=[self._ue_event(days=99)])
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_outside_window_rejected(self):
        w = self._weekly_ue(events=[self._ue_event(event_date="20260720", days=41)])
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    # ── render(checked 列事件 / unknown 显未核查)──
    def test_render_checked_lists_events(self):
        md = render_weekly_markdown(self._weekly_ue(events=[self._ue_event()]))
        self.assertIn("未来已知事件日历", md)
        self.assertIn("limit_unlock", md)
        self.assertIn("20260601", md)                                   # 公告日(PIT)可见

    def test_render_unknown_shows_unchecked(self):
        md = render_weekly_markdown(self._weekly_ue(status="unknown_or_unavailable"))
        self.assertIn("未核查/不可得", md)                             # unknown-not-clear: 不当无事件
        self.assertNotIn("limit_unlock", md)

    def test_render_checked_empty_shows_no_events(self):
        md = render_weekly_markdown(self._weekly_ue(status="checked", events=[]))
        self.assertIn("未来已知事件日历", md)
        self.assertIn("本周已查", md)                                  # checked + 空 = 已查无事件(区别于 unknown)
        self.assertNotIn("limit_unlock", md)

    def test_fetch_unlocks_distinguishes_fail_from_empty(self):
        # 漏洞#1 修复: 取数失败(缺列/异常)→ None(未查成);成功返回空 → [](真无解禁) —— 二者必须可区分(unknown-not-clear)
        import pandas as pd
        class _Pro:
            def __init__(self, df): self._df = df
            def share_float(self, **kw): return self._df
        # 缺 ann_date 列 → None(未查成,不静默当真无)
        self.assertIsNone(_fetch_unlocks(_Pro(pd.DataFrame({"ts_code": ["600000.SH"], "float_date": ["20260615"]})), "600000.SH"))
        # provider 异常 → None(未查成)
        class _Boom:
            def share_float(self, **kw): raise RuntimeError("x")
        self.assertIsNone(_fetch_unlocks(_Boom(), "600000.SH"))
        # 成功返回空 df → [](该票真无未来解禁,区别于未查成)
        self.assertEqual(_fetch_unlocks(_Pro(pd.DataFrame({"ts_code": [], "ann_date": [], "float_date": []})), "600000.SH"), [])
        # 正常 → [{ann_date, float_date}]
        ok = _fetch_unlocks(_Pro(pd.DataFrame({"ts_code": ["600000.SH"], "ann_date": ["20260601"],
                                               "float_date": ["20260615"], "float_share": [1], "float_ratio": [1.0]})), "600000.SH")
        self.assertEqual(ok, [{"ann_date": "20260601", "float_date": "20260615"}])

    # ── 第2刀: 财报预约披露(earnings_disclosure)+ 多 provider 框架 ──
    def test_fetch_earnings_schedule_distinguishes_fail_from_empty(self):
        # 财报预约 provider 同 fail-closed: 缺列/异常→None(未查成);空→[](真无预约);正常→[{ann_date,pre_date}]
        import pandas as pd
        class _Pro:
            def __init__(self, df): self._df = df
            def disclosure_date(self, **kw): return self._df
        self.assertIsNone(_fetch_earnings_schedule(_Pro(pd.DataFrame({"ts_code": ["600000.SH"], "ann_date": ["20260601"]})), "600000.SH"))   # 缺 pre_date 列
        class _Boom:
            def disclosure_date(self, **kw): raise RuntimeError("x")
        self.assertIsNone(_fetch_earnings_schedule(_Boom(), "600000.SH"))
        self.assertEqual(_fetch_earnings_schedule(_Pro(pd.DataFrame({"ts_code": [], "ann_date": [], "pre_date": []})), "600000.SH"), [])
        ok = _fetch_earnings_schedule(_Pro(pd.DataFrame({"ts_code": ["600000.SH"], "ann_date": ["20260601"],
                                                         "pre_date": ["20260615"], "actual_date": [None]})), "600000.SH")
        self.assertEqual(ok, [{"ann_date": "20260601", "pre_date": "20260615"}])

    def test_builder_emits_earnings_event(self):
        # 财报预约披露: earnings_provider(pre_date)→ event_type=earnings_disclosure, source_id=tushare.disclosure_date, confidence=medium
        prov = lambda c: [{"ann_date": "20260601", "pre_date": "20260615"}]
        ue = _upcoming_events([("600000.SH", "x")], AS_OF, None, earnings_provider=prov)
        self.assertEqual(ue["status"], "checked")
        e = ue["events"][0]
        self.assertEqual((e["event_type"], e["event_date"], e["observed_at"], e["source_id"], e["confidence"], e["days_to_event"]),
                         ("earnings_disclosure", "20260615", "20260601", "tushare.disclosure_date", "medium", 6))

    def test_builder_multi_type_same_code_both_land(self):
        # 同一票 unlock + earnings 都近端 → 两类 events 都收(不互相覆盖,key=(票,类))
        unlock = lambda c: [{"ann_date": "20260601", "float_date": "20260612"}]
        earn = lambda c: [{"ann_date": "20260601", "pre_date": "20260618"}]
        ue = _upcoming_events([("600000.SH", "x")], AS_OF, unlock, earnings_provider=earn)
        self.assertEqual(ue["status"], "checked")
        self.assertEqual(sorted(e["event_type"] for e in ue["events"]), ["earnings_disclosure", "limit_unlock"])

    def test_builder_one_type_fails_marks_unchecked_with_type(self):
        # unlock 查成(真无→[])+ earnings 取数失败(None)→ checked 但 unchecked 标 earnings_disclosure(per-(票,类) unknown-not-clear)
        ue = _upcoming_events([("600000.SH", "x")], AS_OF, (lambda c: []), earnings_provider=(lambda c: None))
        self.assertEqual(ue["status"], "checked")
        self.assertEqual([(u["ts_code"], u["event_type"]) for u in ue["unchecked_codes"]], [("600000.SH", "earnings_disclosure")])

    def test_builder_both_providers_none_unknown(self):
        # 两 provider 都 None(未授权/不可用)→ unknown(绝不当无事件)
        self.assertEqual(_upcoming_events([("600000.SH", "x")], AS_OF, None, earnings_provider=None)["status"],
                         "unknown_or_unavailable")

    def test_builder_earnings_pit_lookahead_skipped(self):
        # earnings 同 PIT: ann_date(预约公告)> as_of(look-ahead)→ 跳过(不伪造)
        earn = lambda c: [{"ann_date": "20260610", "pre_date": "20260615"}]
        self.assertEqual(_upcoming_events([("600000.SH", "x")], AS_OF, None, earnings_provider=earn)["events"], [])


class ForwardEventRowLandingTests(unittest.TestCase):
    """4.2 forward_events row landing(R-...-ROW-LANDING-GUARD-GAP): upcoming events 落 per-stock operation_impact + 文本
    (advisory,不改 操作/EGS/选股/TopN、绝不 hard_veto/rescue);status!=checked 不落。"""

    def _w(self, status="checked", ts=None, effect="manual_review", event_type="limit_unlock"):
        w = _weekly()
        ts = ts or w["reports"][0]["ts_code"]
        w["upcoming_events"] = {"as_of": AS_OF, "status": status,
                                "events": ([{"ts_code": ts, "name": "x", "event_type": event_type,
                                             "event_date": "20260615", "observed_at": "20260601",
                                             "source_id": _FORWARD_EVENT_SOURCE_ID[event_type], "expected_effect": effect,
                                             "confidence": _FORWARD_EVENT_CONFIDENCE[event_type], "days_to_event": 6}] if status == "checked" else [])}
        return w

    def _fwd(self, rep, etype=None):
        sf = f"forward_event_{etype}" if etype else None
        return [i for i in (rep["machine"].get("operation_impact") or [])
                if (i["source_field"] == sf if sf else str(i["source_field"]).startswith("forward_event_"))]

    def test_event_lands_on_candidate_row(self):
        w = self._w()
        rep = w["reports"][0]
        action_before, egs_before = rep["m67"]["table"]["操作"], rep["m67"]["table"]["EGS分"]
        _attach_forward_event_impacts(w, AS_OF)
        imp = self._fwd(rep)
        self.assertEqual(len(imp), 1)
        self.assertEqual(imp[0]["visibility_shape"], "candidate_row_impact")
        self.assertEqual(imp[0]["new_entry_effect"], "manual_review")
        self.assertEqual(imp[0]["veto_class"], "none")             # 绝不 veto
        self.assertFalse(imp[0]["production_effect_enabled"])      # analysis-only
        self.assertIn("未来事件", rep["m67"]["精简结论区"]["风控触发"])    # 逐票文本落地
        # no-EGS-TopN-change: 操作 / EGS分 不被 forward event 改
        self.assertEqual((rep["m67"]["table"]["操作"], rep["m67"]["table"]["EGS分"]), (action_before, egs_before))
        validate_weekly_report(w, _feed())                         # row no-dangling guard 过

    def test_held_event_holding_impact(self):
        from runners.a_short_phase5_engine import validate_operation_impact_no_dangling
        w = self._w()
        rep = w["reports"][0]
        rep["machine"]["stateful_risk"] = {"position_state": "held", "rule12": {"status": "inactive"},
                                           "rule13": {"status": "none"}, "reasons": []}
        rep["m67"]["精简结论区"]["操作建议"] = "已有持仓,禁止自动加仓。"   # ⑩ blocked_add 需「禁止加仓」可见
        _attach_forward_event_impacts(w, AS_OF)
        imp = self._fwd(rep)[0]
        self.assertEqual((imp["visibility_shape"], imp["holding_effect"], imp["blocked_add_required"], imp["pending_successor_slice"]),
                         ("holding_row_impact", "hold_watch", True, None))   # S3b 已收官:held forward_event 经合并引擎落持仓处置,不再 pending S3b
        self.assertEqual(imp["implementation_status"], "implemented")        # 非 future_s3b(已实现)
        validate_operation_impact_no_dangling(rep)                 # row no-dangling + ⑩ blocked_add 文本 过

    def test_no_hard_veto_rescue(self):
        # forward event 结构上不可能 veto/rescue:veto_class=none + new_entry_effect 非 hard_veto;且不改 操作
        w = self._w()
        rep = w["reports"][0]
        _attach_forward_event_impacts(w, AS_OF)
        imp = self._fwd(rep)[0]
        self.assertEqual(imp["veto_class"], "none")
        self.assertNotEqual(imp["new_entry_effect"], "hard_veto")

    def test_unknown_status_no_landing(self):
        w = self._w(status="unknown_or_unavailable")
        _attach_forward_event_impacts(w, AS_OF)
        self.assertEqual(self._fwd(w["reports"][0]), [])           # unknown → 不落逐票(不伪造)

    def test_no_event_for_code_no_landing(self):
        w = self._w(ts="600999.SH")                                # event ts 不在 reports
        _attach_forward_event_impacts(w, AS_OF)
        self.assertEqual(self._fwd(w["reports"][0]), [])

    def test_event_lands_on_manual_review_holding(self):
        # holdings_manual_review(无价/停牌旁路持仓,不进 reports[])的票有 checked 事件:validator 用
        # universe = reports ∪ manual_review 接受它 → 事件须落该持仓 reason,不能只在全局表 dangling。
        w = self._w(ts="600519.SH")
        w["holdings_manual_review"] = [{"ts_code": "600519.SH", "name": "乙", "reason": "停牌"}]
        _attach_forward_event_impacts(w, AS_OF)
        h = w["holdings_manual_review"][0]
        self.assertIn("停牌", h["reason"])                          # 原 reason 保留(append 不覆盖)
        self.assertIn("未来已知事件", h["reason"])                  # 事件落地到该持仓 reason(marker)
        self.assertEqual(self._fwd(w["reports"][0]), [])           # 没串到候选行
        validate_weekly_report(w, _feed())                         # universe 接受 + 已落地,no-dangling 过

    def test_validator_rejects_unlanded_candidate_event(self):
        # row no-dangling 由消费者 validator 强制:checked event 对应 reports[] 行但跳过 _attach(operation_impact 缺失)→ 拒(不靠 main 顺序)
        w = self._w()
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_rejects_unlanded_manual_review_event(self):
        # manual_review-only 持仓的 checked event 但 reason 无落地标记(跳过 _attach)→ 拒
        w = self._w(ts="600519.SH")
        w["holdings_manual_review"] = [{"ts_code": "600519.SH", "name": "乙", "reason": "停牌"}]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_source_guard_blocks_production_mutation(self):
        # SOURCE-GUARD: forward_event impact 被篡改成生产/硬否决/越界 → engine no-dangling guard 拒(永久 analysis-only)
        from runners.a_short_phase5_engine import validate_operation_impact_no_dangling
        w = self._w()
        rep = w["reports"][0]
        _attach_forward_event_impacts(w, AS_OF)
        validate_operation_impact_no_dangling(rep)                 # 原始 advisory 形态过
        imp = self._fwd(rep)[0]
        for k, bad in [("production_effect_enabled", True), ("veto_class", "production_hard_veto"),
                       ("field_class", "semantic_advisory"), ("new_entry_effect", "hard_veto"),
                       ("holding_effect", "reduce")]:
            good = imp[k]
            imp[k] = bad
            with self.assertRaises(ValueError):                    # 逐项隔离:每种篡改都被拒
                validate_operation_impact_no_dangling(rep)
            imp[k] = good                                          # 复原

    # ── 第2刀: earnings_disclosure 逐票落地 + per-type guard ──
    def test_earnings_lands_per_type_impact(self):
        # 财报预约披露 event → operation_impact source_field=forward_event_earnings_disclosure(per-type)+ 操作建议含 marker
        w = self._w(event_type="earnings_disclosure")
        rep = w["reports"][0]
        _attach_forward_event_impacts(w, AS_OF)
        imp = self._fwd(rep, "earnings_disclosure")
        self.assertEqual(len(imp), 1)
        self.assertEqual((imp[0]["visibility_shape"], imp[0]["veto_class"]), ("candidate_row_impact", "none"))
        self.assertIn("未来已知事件", rep["m67"]["精简结论区"]["操作建议"])
        validate_weekly_report(w, _feed())

    def test_multi_type_lands_separate_impacts(self):
        # 同票 unlock + earnings → 2 个 per-type impact(分别 source_field);文本面只汇总一次;两类都 no-dangling
        w = self._w()
        rep = w["reports"][0]
        w["upcoming_events"]["events"].append({"ts_code": rep["ts_code"], "name": "x",
                                               "event_type": "earnings_disclosure", "event_date": "20260618",
                                               "observed_at": "20260601", "source_id": "tushare.disclosure_date",
                                               "expected_effect": "manual_review", "confidence": "medium", "days_to_event": 9})
        _attach_forward_event_impacts(w, AS_OF)
        self.assertEqual(sorted(i["source_field"] for i in self._fwd(rep)),
                         ["forward_event_earnings_disclosure", "forward_event_limit_unlock"])
        validate_weekly_report(w, _feed())

    def test_source_guard_covers_earnings(self):
        # SOURCE-GUARD ⑪ 用 forward_event_ 前缀:earnings impact 篡改成生产硬否决也被拒(覆盖新类,不漏)
        from runners.a_short_phase5_engine import validate_operation_impact_no_dangling
        w = self._w(event_type="earnings_disclosure")
        rep = w["reports"][0]
        _attach_forward_event_impacts(w, AS_OF)
        validate_operation_impact_no_dangling(rep)                 # 原始 advisory 过
        imp = self._fwd(rep, "earnings_disclosure")[0]
        imp["veto_class"] = "production_hard_veto"                  # ⑪: earnings 篡改生产硬否决 → 拒
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(rep)
        imp["veto_class"] = "none"                                 # 复原
        rep["m67"]["精简结论区"]["操作建议"] = "试探仓建仓,止损,未验证"   # ⑫: 抹去 earnings 未来事件字样 → 拒
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(rep)

    def test_validator_rejects_unlanded_earnings(self):
        # per-type 落地强制:earnings event 但跳过 _attach(无 earnings impact)→ 拒(不靠 main 顺序)
        w = self._w(event_type="earnings_disclosure")
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    # ── IMPACT-EVIDENCE 反向 guard(impact → 必须有匹配 checked calendar event,与正向落地双向闭合)──
    def test_reverse_guard_rejects_fake_source_type(self):
        # report 多一个 forward_event_fake impact(calendar 无此类型)→ 不在允许枚举 → 反向拒
        w = self._w()
        rep = w["reports"][0]
        _attach_forward_event_impacts(w, AS_OF)
        validate_weekly_report(w, _feed())                         # 正常(limit_unlock event↔impact)
        fake = dict(self._fwd(rep, "limit_unlock")[0]); fake["source_field"] = "forward_event_fake"
        rep["machine"]["operation_impact"].append(fake)
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_reverse_guard_rejects_impact_without_calendar_evidence(self):
        # impact 在,但清空 calendar events → (code,type) 无匹配 → 反向拒(伪造/悬空)
        w = self._w()
        _attach_forward_event_impacts(w, AS_OF)
        validate_weekly_report(w, _feed())
        w["upcoming_events"]["events"] = []                        # 清空日历(impact 还在)
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_reverse_guard_rejects_impact_type_without_matching_event(self):
        # report 多一个 earnings impact,但 calendar 只有 limit_unlock event → (code,earnings) 无匹配 → 反向拒
        w = self._w()
        rep = w["reports"][0]
        _attach_forward_event_impacts(w, AS_OF)
        fe = dict(self._fwd(rep, "limit_unlock")[0])
        fe["source_field"] = "forward_event_earnings_disclosure"
        fe["evidence_ref"] = dict(fe["evidence_ref"], value="upcoming_events.events[earnings_disclosure]")
        rep["machine"]["operation_impact"].append(fe)
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_reverse_guard_rejects_impact_for_code_without_event(self):
        # 2 报告:calendar event 只给 600000.SH;同型 impact 复制到 600001.SH → (600001.SH,limit_unlock) 无匹配 → 反向拒
        w = _weekly([_normalized(ts_code="600000.SH"), _normalized(ts_code="600001.SH")])
        w["upcoming_events"] = {"as_of": AS_OF, "status": "checked",
                                "events": [{"ts_code": "600000.SH", "name": "x", "event_type": "limit_unlock",
                                            "event_date": "20260615", "observed_at": "20260601",
                                            "source_id": "tushare.share_float", "expected_effect": "manual_review",
                                            "confidence": "high", "days_to_event": 6}]}
        _attach_forward_event_impacts(w, AS_OF)                    # 落到 600000.SH(匹配)
        repA = next(r for r in w["reports"] if r["ts_code"] == "600000.SH")
        repB = next(r for r in w["reports"] if r["ts_code"] == "600001.SH")
        repB["machine"].setdefault("operation_impact", []).append(
            dict(next(i for i in repA["machine"]["operation_impact"] if str(i["source_field"]).startswith("forward_event_"))))
        repB["m67"]["精简结论区"]["操作建议"] = (repB["m67"]["精简结论区"].get("操作建议") or "") + "｜未来已知事件"   # 过 ⑫,隔离反向
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_reverse_guard_checked_empty_no_impact_passes(self):
        # checked 空日历 + 无 forward impact → 正反向都不触发 → 过(不误拒正常态)
        w = self._w()
        w["upcoming_events"]["events"] = []                        # checked 但空(不调 _attach,无 impact)
        validate_weekly_report(w, _feed())

    def test_advice_landing_on_candidate_row(self):
        # ADVICE-LANDING:候选有近端解禁 → 操作建议(用户主看)含未来事件/人工复核字样,不只风控触发;table 操作不变(analysis-only)
        w = self._w()
        rep = w["reports"][0]
        action_before = rep["m67"]["table"]["操作"]
        adv_before = rep["m67"]["精简结论区"]["操作建议"]
        _attach_forward_event_impacts(w, AS_OF)
        adv = rep["m67"]["精简结论区"]["操作建议"]
        self.assertIn("未来已知事件", adv)                          # 落用户主看的操作建议
        self.assertIn("人工复核", adv)
        self.assertIn(adv_before, adv)                             # 原建仓建议保留(append 非覆盖,护栏不破)
        self.assertEqual(rep["m67"]["table"]["操作"], action_before)   # table 操作不变(不改 EGS/决策)
        validate_weekly_report(w, _feed())

    def test_advice_landing_on_holding(self):
        # 持仓行一致:held 操作建议也含未来事件字样(对称,防 held 漂移);⑩ 禁止加仓 + ⑫ 未来事件 同过
        from runners.a_short_phase5_engine import validate_operation_impact_no_dangling
        w = self._w()
        rep = w["reports"][0]
        rep["machine"]["stateful_risk"] = {"position_state": "held", "rule12": {"status": "inactive"},
                                           "rule13": {"status": "none"}, "reasons": []}
        rep["m67"]["精简结论区"]["操作建议"] = "已有持仓,禁止自动加仓。"
        _attach_forward_event_impacts(w, AS_OF)
        self.assertIn("未来已知事件", rep["m67"]["精简结论区"]["操作建议"])
        validate_operation_impact_no_dangling(rep)

    def test_advice_guard_rejects_missing_advice(self):
        # ⑫ guard:forward_event impact 落地但操作建议被抹去未来事件字样(仍像干净建仓)→ engine no-dangling guard 拒
        from runners.a_short_phase5_engine import validate_operation_impact_no_dangling
        w = self._w()
        rep = w["reports"][0]
        _attach_forward_event_impacts(w, AS_OF)
        validate_operation_impact_no_dangling(rep)                 # 落地形态过
        rep["m67"]["精简结论区"]["操作建议"] = "试探仓建仓,止损,edge 未验证"   # 抹去未来事件字样
        with self.assertRaises(ValueError):
            validate_operation_impact_no_dangling(rep)

    def test_advice_lands_in_rendered_markdown(self):
        # render regression:渲染后的 Markdown 候选行用户可见未来事件字样(不只机器侧 operation_impact)
        from runners.a_short_m67_render import render_weekly_markdown
        w = self._w()
        _attach_forward_event_impacts(w, AS_OF)
        self.assertIn("未来已知事件", render_weekly_markdown(w))


_DL_WINDOW = ["20260603", "20260604", "20260605", "20260608", "20260609"]   # 近5交易日 <= AS_OF(20260609)


class DragonListTests(unittest.TestCase):
    """4.2 Round5 龙虎榜(top_list/top_inst, analysis-only · comparison-only):provider fail-closed / trade_cal 窗口 /
    builder PIT+unknown-not-clear / 候选+持仓落 板块资金事件+operation_impact / 双向 no-dangling / 席位分析(第二刀)/
    comparison-only isolation(绝不改 EGS/TopN/操作/股数/否决)/ render。第三刀覆盖候选 + 账户持仓(Tier-3 板块资金事件 render 掩面已放行『龙虎榜对照』);holdings_manual_review 留后续。"""

    # ── provider _fetch_dragon_list(fail-closed:缺列/异常→None 未查成;空→[] 真无;正常→清洗 dicts)──
    def test_fetch_dragon_list_distinguishes_fail_from_empty(self):
        class _Pro:
            def __init__(self, df): self._df = df
            def top_list(self, **kw): return self._df
        self.assertIsNone(_fetch_dragon_list(_Pro(pd.DataFrame({"ts_code": ["600000.SH"], "reason": ["x"]})), "20260605"))  # 缺 net_amount 列
        class _Boom:
            def top_list(self, **kw): raise RuntimeError("x")
        self.assertIsNone(_fetch_dragon_list(_Boom(), "20260605"))
        self.assertEqual(_fetch_dragon_list(_Pro(pd.DataFrame({"ts_code": [], "net_amount": [], "reason": []})), "20260605"), [])
        ok = _fetch_dragon_list(_Pro(pd.DataFrame({"trade_date": ["20260605"], "ts_code": ["600000.SH"], "name": ["测试"],
                                                   "net_amount": [1234.5], "reason": ["日涨幅偏离7%"]})), "20260605")
        self.assertEqual(ok, [{"ts_code": "600000.SH", "name": "测试", "net_amount": 1234.5, "reason": "日涨幅偏离7%"}])

    def test_fetch_dragon_list_cleans_blank(self):
        class _Pro:
            def top_list(self, **kw): return pd.DataFrame({"ts_code": ["600000.SH"], "name": [""], "net_amount": [None], "reason": [""]})
        self.assertEqual(_fetch_dragon_list(_Pro(), "20260605"),
                         [{"ts_code": "600000.SH", "name": "", "net_amount": None, "reason": None}])   # 空 net/reason → None(不伪造 0)

    # ── _recent_trading_days(trade_cal,fail-closed,剔除 > as_of)──
    def test_recent_trading_days_ok(self):
        class _Pro:
            def trade_cal(self, **kw):
                return pd.DataFrame({"cal_date": ["20260603", "20260604", "20260605", "20260608", "20260609", "20260610"]})
        self.assertEqual(_recent_trading_days(_Pro(), "20260609", 5), _DL_WINDOW)   # 最近5个 <= as_of(剔除未来 20260610)

    def test_recent_trading_days_fail_closed(self):
        class _Boom:
            def trade_cal(self, **kw): raise RuntimeError("x")
        self.assertIsNone(_recent_trading_days(_Boom(), "20260609", 5))
        class _NoCol:
            def trade_cal(self, **kw): return pd.DataFrame({"x": [1]})
        self.assertIsNone(_recent_trading_days(_NoCol(), "20260609", 5))

    # ── builder _dragon_list_events(unknown-not-clear / PIT / 候选过滤)──
    def test_builder_provider_none_unknown(self):
        dl = _dragon_list_events([("600000.SH", "x")], AS_OF, None, _DL_WINDOW)
        self.assertEqual((dl["status"], dl["events"], dl["window_dates"]), ("unknown_or_unavailable", [], _DL_WINDOW))

    def test_builder_no_trade_days_unknown(self):
        self.assertEqual(_dragon_list_events([("600000.SH", "x")], AS_OF, lambda d: [], None)["status"], "unknown_or_unavailable")
        self.assertEqual(_dragon_list_events([("600000.SH", "x")], AS_OF, lambda d: [], [])["status"], "unknown_or_unavailable")

    def test_builder_all_days_fail_unknown(self):
        self.assertEqual(_dragon_list_events([("600000.SH", "x")], AS_OF, lambda d: None, _DL_WINDOW)["status"], "unknown_or_unavailable")
        def _boom(d):
            raise RuntimeError("x")
        self.assertEqual(_dragon_list_events([("600000.SH", "x")], AS_OF, _boom, _DL_WINDOW)["status"], "unknown_or_unavailable")

    def test_builder_partial_day_fail_marks_unchecked(self):
        prov = lambda d: [] if d == "20260609" else None      # 一天查成(真无)+ 其余取数失败
        dl = _dragon_list_events([("600000.SH", "x")], AS_OF, prov, _DL_WINDOW)
        self.assertEqual((dl["status"], dl["events"]), ("checked", []))
        self.assertEqual(dl["unchecked_dates"], ["20260603", "20260604", "20260605", "20260608"])   # 失败日显式列出,不当无上榜

    def test_builder_emits_candidate_appearance(self):
        prov = lambda d: ([{"ts_code": "600000.SH", "name": "测试", "net_amount": 1e6, "reason": "涨幅偏离"}] if d == "20260605" else [])
        dl = _dragon_list_events([("600000.SH", "x")], AS_OF, prov, _DL_WINDOW)
        self.assertEqual(dl["status"], "checked")
        e = dl["events"][0]
        self.assertEqual((e["ts_code"], e["trade_date"], e["net_amount"], e["reason"]), ("600000.SH", "20260605", 1e6, "涨幅偏离"))

    def test_builder_drops_non_candidate(self):
        prov = lambda d: [{"ts_code": "600999.SH", "name": "非候选", "net_amount": 1e6, "reason": "x"}]
        self.assertEqual(_dragon_list_events([("600000.SH", "x")], AS_OF, prov, _DL_WINDOW)["events"], [])   # 非候选丢弃

    def test_builder_multi_day_appearance(self):
        prov = lambda d: ([{"ts_code": "600000.SH", "name": "x", "net_amount": 1e6, "reason": "r"}] if d in ("20260605", "20260609") else [])
        dl = _dragon_list_events([("600000.SH", "x")], AS_OF, prov, _DL_WINDOW)
        self.assertEqual(sorted(e["trade_date"] for e in dl["events"]), ["20260605", "20260609"])   # 多日各一条(不去重)

    def test_builder_uses_candidate_name(self):
        prov = lambda d: ([{"ts_code": "600000.SH", "name": "provider名", "net_amount": 1e6, "reason": "r"}] if d == "20260605" else [])
        self.assertEqual(_dragon_list_events([("600000.SH", "候选名")], AS_OF, prov, _DL_WINDOW)["events"][0]["name"], "候选名")

    # ── attach _attach_dragon_list_impacts(候选/held-candidate;comparison-only;no-EGS-change)──
    def _w_dl(self, status="checked", ts=None):
        w = _weekly()
        ts = ts or w["reports"][0]["ts_code"]
        w["dragon_list"] = {"as_of": AS_OF, "status": status, "lookback_trading_days": 5, "window_dates": _DL_WINDOW,
                            "events": ([{"ts_code": ts, "name": "x", "trade_date": "20260605", "net_amount": 1234.0,
                                         "reason": "涨幅偏离"}] if status == "checked" else [])}
        return w

    def _dlimp(self, rep):
        return [i for i in (rep["machine"].get("operation_impact") or []) if i["source_field"] == "dragon_list_appearance"]

    def test_attach_candidate_landing(self):
        w = self._w_dl()
        rep = w["reports"][0]
        before = (rep["m67"]["table"]["操作"], rep["m67"]["table"]["EGS分"], rep["m67"]["table"]["股数"])
        _attach_dragon_list_impacts(w, AS_OF)
        imp = self._dlimp(rep)
        self.assertEqual(len(imp), 1)
        self.assertEqual((imp[0]["visibility_shape"], imp[0]["new_entry_effect"], imp[0]["holding_effect"]),
                         ("candidate_row_impact", "informational", "none"))
        self.assertEqual((imp[0]["veto_class"], imp[0]["production_effect_enabled"], imp[0]["blocked_add_required"],
                          imp[0]["pit_basis"], imp[0]["implementation_status"]),
                         ("none", False, False, "trade_date_window", "implemented"))
        self.assertIn("龙虎榜对照", rep["m67"]["精简结论区"]["板块资金事件"])   # 文本落地
        # comparison-only: 操作/EGS分/股数 不被改
        self.assertEqual((rep["m67"]["table"]["操作"], rep["m67"]["table"]["EGS分"], rep["m67"]["table"]["股数"]), before)
        validate_weekly_report(w, _feed())                              # 双向 no-dangling + ⑬ 过

    def test_attach_held_candidate_holding_impact(self):
        w = self._w_dl()
        rep = w["reports"][0]
        rep["machine"]["stateful_risk"] = {"position_state": "held", "rule12": {"status": "inactive"},
                                           "rule13": {"status": "none"}, "reasons": []}
        _attach_dragon_list_impacts(w, AS_OF)
        imp = self._dlimp(rep)[0]
        self.assertEqual((imp["visibility_shape"], imp["new_entry_effect"], imp["holding_effect"], imp["blocked_add_required"]),
                         ("holding_row_impact", "none", "none", False))   # held-candidate 也 comparison-only(无任何持仓动作)
        self.assertEqual(imp["privacy_class"], "private_account")          # 涉持仓 → 私密
        _vop(rep)                                                          # comparison-only isolation + marker 过

    def test_attach_preserves_existing_sector_text(self):
        # 反向(no-clobber): 已有 板块资金事件 内容(非 unknown)→ append 不覆盖(保留原文 + marker)
        w = self._w_dl()
        rep = w["reports"][0]
        rep["m67"]["精简结论区"]["板块资金事件"] = "半导体景气上行"
        _attach_dragon_list_impacts(w, AS_OF)
        sector = rep["m67"]["精简结论区"]["板块资金事件"]
        self.assertIn("半导体景气上行", sector)
        self.assertIn("龙虎榜对照", sector)

    def test_fetch_dragon_list_nonfinite_net_amount_nulled(self):
        # 反向/pre-flight: net_amount 为 Inf/NaN → None(不写出非法 JSON;NaN 经 str 过滤、Inf 经 finite 门)
        class _Pro:
            def top_list(self, **kw):
                return pd.DataFrame({"ts_code": ["600000.SH", "600001.SH"], "name": ["a", "b"],
                                     "net_amount": [float("inf"), float("nan")], "reason": ["r", "r"]})
        rows = _fetch_dragon_list(_Pro(), "20260605")
        self.assertEqual([r["net_amount"] for r in rows], [None, None])

    def test_attach_unknown_no_landing(self):
        w = self._w_dl(status="unknown_or_unavailable")
        _attach_dragon_list_impacts(w, AS_OF)
        self.assertEqual(self._dlimp(w["reports"][0]), [])                # unknown → 不伪造逐票

    def test_attach_no_event_for_code_no_landing(self):
        w = self._w_dl(ts="600999.SH")                                    # event ts 不在 reports
        _attach_dragon_list_impacts(w, AS_OF)
        self.assertEqual(self._dlimp(w["reports"][0]), [])

    # ── schema + validator(双向 no-dangling / PIT / 窗口 / 张冠李戴)──
    def _dl_event(self, ts="600000.SH", trade_date="20260605", net_amount=1234.0, reason="涨幅偏离"):
        return {"ts_code": ts, "name": "测试", "trade_date": trade_date, "net_amount": net_amount, "reason": reason}

    def _weekly_dl(self, status="checked", events=None, window=None, **extra):
        w = _weekly()
        dl = {"as_of": AS_OF, "status": status, "lookback_trading_days": 5,
              "window_dates": (window if window is not None else _DL_WINDOW), "events": events or []}
        dl.update(extra)
        w["dragon_list"] = dl
        return w

    def _fake_dl_impact(self, **over):
        imp = {"source_field": "dragon_list_appearance", "field_class": "structured", "visibility_shape": "candidate_row_impact",
               "impact_scope": "new_entry", "new_entry_effect": "informational", "holding_effect": "none",
               "blocked_add_required": False, "veto_class": "none", "reason": "x",
               "evidence_ref": {"kind": "lineage_key", "value": _DRAGON_LIST_EVIDENCE_VALUE, "as_of": AS_OF},
               "confidence": "high", "pit_basis": "trade_date_window", "production_effect_enabled": False,
               "implementation_status": "implemented", "m67_landing_surface": "精简结论区.板块资金事件",
               "terminal_surface_target": "already_structured", "pending_successor_slice": None, "privacy_class": "public_tracked"}
        imp.update(over)
        return imp

    def _schema(self):
        return json.load(open(SCHEMA_PATH, encoding="utf-8"))

    def test_schema_and_validator_accept(self):
        w = self._weekly_dl(events=[self._dl_event()])
        _attach_dragon_list_impacts(w, AS_OF)                             # 落地满足正向 no-dangling
        jsonschema.validate(w, self._schema())
        validate_weekly_report(w, _feed())

    def test_absent_is_valid(self):
        w = _weekly()                                                     # 无 dragon_list → 向后兼容
        jsonschema.validate(w, self._schema())
        validate_weekly_report(w, _feed())

    def test_schema_accept_unknown(self):
        w = self._weekly_dl(status="unknown_or_unavailable")
        jsonschema.validate(w, self._schema())
        validate_weekly_report(w, _feed())

    def test_schema_accept_unchecked_dates(self):
        w = self._weekly_dl(events=[self._dl_event()], unchecked_dates=["20260603"])
        _attach_dragon_list_impacts(w, AS_OF)
        jsonschema.validate(w, self._schema())
        validate_weekly_report(w, _feed())

    def test_dragon_impact_passes_m67_schema(self):
        w = self._w_dl()
        _attach_dragon_list_impacts(w, AS_OF)
        jsonschema.validate(w["reports"][0], json.load(open(M67_SCHEMA, encoding="utf-8")))

    def test_validator_unknown_with_events_rejected(self):
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_dl(status="unknown_or_unavailable", events=[self._dl_event()]), _feed())

    def test_validator_foreign_ts_rejected(self):
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_dl(events=[self._dl_event(ts="600999.SH")]), _feed())   # 不在 reports(张冠李戴)

    def test_validator_event_after_as_of_rejected(self):
        with self.assertRaises(ValueError):                               # trade_date > as_of(非 PIT;不在 window→先命中 PIT 分支)
            validate_weekly_report(self._weekly_dl(events=[self._dl_event(trade_date="20260610")]), _feed())

    def test_validator_event_outside_window_rejected(self):
        with self.assertRaises(ValueError):                               # <= as_of 但不在 window_dates
            validate_weekly_report(self._weekly_dl(events=[self._dl_event(trade_date="20260601")]), _feed())

    def test_validator_window_date_future_rejected(self):
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_dl(events=[], window=["20260605", "20260620"]), _feed())   # window 含未来

    def test_validator_unchecked_outside_window_rejected(self):
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_dl(events=[], unchecked_dates=["20260601"]), _feed())

    def test_validator_as_of_mismatch_rejected(self):
        w = self._weekly_dl(events=[])
        w["dragon_list"]["as_of"] = "20260101"
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_reverse_evidence_no_event_rejected(self):
        # impact 存在但 dragon_list 无匹配 event(伪造/空日历)→ 反向 evidence guard 拒
        w = self._weekly_dl(events=[])                                    # checked,空 events
        rep = w["reports"][0]
        rep["machine"].setdefault("operation_impact", []).append(self._fake_dl_impact())
        rep["m67"]["精简结论区"]["板块资金事件"] = "龙虎榜对照(伪造)"      # 过 ⑬ marker,只测反向证据
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_reverse_evidence_bad_ref_rejected(self):
        w = self._weekly_dl(events=[self._dl_event()])
        _attach_dragon_list_impacts(w, AS_OF)
        self._dlimp(w["reports"][0])[0]["evidence_ref"]["value"] = "fake"
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_forward_landing_dangling_rejected(self):
        # checked event 但对应 report 无 dragon_list_appearance impact(未 attach)→ 正向 no-dangling 拒
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_dl(events=[self._dl_event()]), _feed())

    # ── engine guard ⑬(comparison-only isolation,source-class 级,防篡改)──
    def _landed_rep(self):
        w = self._w_dl()
        _attach_dragon_list_impacts(w, AS_OF)
        return w["reports"][0]

    def _landed_rep_held(self):
        w = self._w_dl()
        w["reports"][0]["machine"]["stateful_risk"] = {"position_state": "held", "rule12": {"status": "inactive"},
                                                       "rule13": {"status": "none"}, "reasons": []}
        _attach_dragon_list_impacts(w, AS_OF)
        return w["reports"][0]

    def test_validator_checked_empty_window_rejected(self):
        # 覆盖闭合: checked 但 window_dates 空 → 拒(无任何查成日,应为 unknown)
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_dl(status="checked", events=[], window=[]), _feed())

    def test_validator_checked_all_unchecked_rejected(self):
        # 覆盖闭合: checked 但全部 window 都在 unchecked_dates → 拒(无任何实际查成日)
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_dl(status="checked", events=[], unchecked_dates=list(_DL_WINDOW)), _feed())

    def test_validator_partial_unchecked_legal(self):
        # 正向: 至少一日查成(部分 unchecked)+ 无 event → 合法 checked
        validate_weekly_report(self._weekly_dl(status="checked", events=[], unchecked_dates=["20260603", "20260604"]), _feed())

    def test_guard_held_public_candidate_mutation_rejected(self):
        # held 行的 trade-event impact 被改成 candidate_row_impact/public → guard 拒(涉真实持仓须 holding/private)
        rep = self._landed_rep_held()
        imp = self._dlimp(rep)[0]
        imp["visibility_shape"], imp["privacy_class"] = "candidate_row_impact", "public_tracked"
        with self.assertRaises(ValueError):
            _vop(rep)

    def test_guard_legal_passes(self):
        _vop(self._landed_rep())                                          # 不 raise

    def test_guard_production_enabled_rejected(self):
        rep = self._landed_rep()
        self._dlimp(rep)[0]["production_effect_enabled"] = True
        with self.assertRaises(ValueError):
            _vop(rep)

    def test_guard_veto_class_rejected(self):
        rep = self._landed_rep()
        self._dlimp(rep)[0]["veto_class"] = "m67_advisory_veto"
        with self.assertRaises(ValueError):
            _vop(rep)

    def test_guard_new_entry_effect_rejected(self):
        rep = self._landed_rep()
        self._dlimp(rep)[0]["new_entry_effect"] = "sizing_down"           # comparison-only 不许 sizing
        with self.assertRaises(ValueError):
            _vop(rep)

    def test_guard_holding_effect_rejected(self):
        rep = self._landed_rep()
        self._dlimp(rep)[0]["holding_effect"] = "hold_watch"
        with self.assertRaises(ValueError):
            _vop(rep)

    def test_guard_blocked_add_rejected(self):
        rep = self._landed_rep()
        self._dlimp(rep)[0]["blocked_add_required"] = True
        with self.assertRaises(ValueError):
            _vop(rep)

    def test_guard_marker_removed_rejected(self):
        rep = self._landed_rep()
        rep["m67"]["精简结论区"]["板块资金事件"] = "unknown"               # 抹去「龙虎榜对照」marker
        with self.assertRaises(ValueError):
            _vop(rep)

    # ── render(checked 列上榜 / unknown 显未核查 / unchecked 警告)──
    def test_render_checked_lists_appearances(self):
        md = render_weekly_markdown(self._weekly_dl(events=[self._dl_event()]))
        self.assertIn("龙虎榜", md)
        self.assertIn("20260605", md)
        self.assertIn("涨幅偏离", md)

    def test_render_unknown_shows_unchecked(self):
        self.assertIn("未核查/不可得", render_weekly_markdown(self._weekly_dl(status="unknown_or_unavailable")))

    def test_render_checked_empty(self):
        self.assertIn("本周已查", render_weekly_markdown(self._weekly_dl(status="checked", events=[])))

    def test_render_unchecked_dates_warning(self):
        md = render_weekly_markdown(self._weekly_dl(events=[self._dl_event()], unchecked_dates=["20260603", "20260604"]))
        self.assertIn("未能核查龙虎榜", md)

    # ── 第二刀 席位分析(top_inst):provider / _sum_inst_net / builder seat-join / 覆盖 / 文本 / validator / render ──
    def _inst_rows(self, code="600000.SH"):
        return [{"ts_code": code, "exalter": "机构专用", "side": "0", "net_buy": 5e6},
                {"ts_code": code, "exalter": "某游资营业部", "side": "1", "net_buy": -2e6}]

    def test_fetch_dragon_inst_fail_closed(self):
        class _Pro:
            def __init__(self, df): self._df = df
            def top_inst(self, **kw): return self._df
        self.assertIsNone(_fetch_dragon_inst(_Pro(pd.DataFrame({"ts_code": ["x"], "exalter": ["y"]})), "20260605"))  # 缺 net_buy
        class _Boom:
            def top_inst(self, **kw): raise RuntimeError("x")
        self.assertIsNone(_fetch_dragon_inst(_Boom(), "20260605"))
        self.assertEqual(_fetch_dragon_inst(_Pro(pd.DataFrame({"ts_code": [], "exalter": [], "net_buy": []})), "20260605"), [])
        ok = _fetch_dragon_inst(_Pro(pd.DataFrame({"trade_date": ["20260605"], "ts_code": ["600000.SH"], "exalter": ["机构专用"],
                                                   "side": [0], "buy": [1], "sell": [0], "net_buy": [5e6]})), "20260605")
        self.assertEqual(ok, [{"ts_code": "600000.SH", "exalter": "机构专用", "side": "0", "net_buy": 5e6}])

    def test_sum_inst_net(self):
        self.assertEqual(_sum_inst_net([{"exalter": "机构专用", "net_buy": 3e6}, {"exalter": "游资", "net_buy": -1e6},
                                        {"exalter": "机构专用", "net_buy": 2e6}]), 5e6)
        self.assertIsNone(_sum_inst_net([{"exalter": "游资", "net_buy": 1e6}]))            # 无机构 → None(不伪造 0)
        self.assertIsNone(_sum_inst_net([{"exalter": "机构专用", "net_buy": None}]))        # 机构但 net 全 None → None

    def test_builder_attaches_seats(self):
        dprov = lambda d: ([{"ts_code": "600000.SH", "name": "x", "net_amount": 1e6, "reason": "r"}] if d == "20260605" else [])
        iprov = lambda d: (self._inst_rows() if d == "20260605" else [])
        dl = _dragon_list_events([("600000.SH", "x")], AS_OF, dprov, _DL_WINDOW, inst_provider=iprov)
        self.assertEqual(dl["seats_status"], "checked")
        e = dl["events"][0]
        self.assertEqual(len(e["seats"]), 2)
        self.assertEqual(e["inst_net_buy"], 5e6)                          # 机构专用 net_buy 合计

    def test_builder_no_inst_provider_unchanged(self):
        # 第一刀式调用(无 inst_provider)→ 输出不变(无 seats_status、event 无 seats)
        dprov = lambda d: ([{"ts_code": "600000.SH", "name": "x", "net_amount": 1e6, "reason": "r"}] if d == "20260605" else [])
        dl = _dragon_list_events([("600000.SH", "x")], AS_OF, dprov, _DL_WINDOW)
        self.assertNotIn("seats_status", dl)
        self.assertNotIn("seats", dl["events"][0])

    def test_builder_all_inst_fail_seats_unknown(self):
        dprov = lambda d: ([{"ts_code": "600000.SH", "name": "x", "net_amount": 1e6, "reason": "r"}] if d == "20260605" else [])
        dl = _dragon_list_events([("600000.SH", "x")], AS_OF, dprov, _DL_WINDOW, inst_provider=lambda d: None)
        self.assertEqual(dl["seats_status"], "unknown_or_unavailable")     # 席位全没查成 → unknown(不当无席位)
        self.assertNotIn("seats", dl["events"][0])

    def test_builder_partial_inst_fail_unchecked_seat_dates(self):
        dprov = lambda d: ([{"ts_code": "600000.SH", "name": "x", "net_amount": 1e6, "reason": "r"}] if d in ("20260605", "20260609") else [])
        iprov = lambda d: (self._inst_rows() if d == "20260605" else None)   # 20260609 席位失败
        dl = _dragon_list_events([("600000.SH", "x")], AS_OF, dprov, _DL_WINDOW, inst_provider=iprov)
        self.assertEqual(dl["seats_status"], "checked")
        self.assertEqual(dl["unchecked_seat_dates"], ["20260609"])
        by_day = {e["trade_date"]: e for e in dl["events"]}
        self.assertIn("seats", by_day["20260605"])
        self.assertNotIn("seats", by_day["20260609"])                     # 席位失败日不附 seats

    def test_builder_no_events_inst_checked(self):
        dl = _dragon_list_events([("600000.SH", "x")], AS_OF, lambda d: [], _DL_WINDOW, inst_provider=lambda d: [])
        self.assertEqual((dl["status"], dl["seats_status"]), ("checked", "checked"))   # 无上榜→无席位可查,trivially 完整

    def test_attach_text_mentions_seats(self):
        w = self._w_dl()
        w["dragon_list"]["seats_status"] = "checked"
        w["dragon_list"]["events"][0]["seats"] = [{"exalter": "机构专用", "side": "0", "net_buy": 5e6}]
        w["dragon_list"]["events"][0]["inst_net_buy"] = 5e6
        _attach_dragon_list_impacts(w, AS_OF)
        sector = w["reports"][0]["m67"]["精简结论区"]["板块资金事件"]
        self.assertIn("席位1家", sector)
        self.assertIn("机构净", sector)

    def test_validator_accepts_seats(self):
        w = self._weekly_dl(events=[self._dl_event()], seats_status="checked")
        w["dragon_list"]["events"][0]["seats"] = [{"exalter": "机构专用", "side": "0", "net_buy": 5e6}]
        w["dragon_list"]["events"][0]["inst_net_buy"] = 5e6
        _attach_dragon_list_impacts(w, AS_OF)
        jsonschema.validate(w, self._schema())
        validate_weekly_report(w, _feed())

    def test_validator_seats_unknown_with_event_seats_rejected(self):
        w = self._weekly_dl(events=[self._dl_event()], seats_status="unknown_or_unavailable")
        w["dragon_list"]["events"][0]["seats"] = [{"exalter": "机构专用", "side": "0", "net_buy": 5e6}]
        _attach_dragon_list_impacts(w, AS_OF)
        with self.assertRaises(ValueError):                               # unknown 却带 seats
            validate_weekly_report(w, _feed())

    def test_validator_seats_on_unchecked_seat_date_rejected(self):
        w = self._weekly_dl(events=[self._dl_event()], seats_status="checked", unchecked_seat_dates=["20260605"])
        w["dragon_list"]["events"][0]["seats"] = [{"exalter": "机构专用", "side": "0", "net_buy": 5e6}]  # event 日 20260605 在 unchecked
        _attach_dragon_list_impacts(w, AS_OF)
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_unchecked_seat_dates_outside_window_rejected(self):
        w = self._weekly_dl(events=[self._dl_event()], seats_status="checked", unchecked_seat_dates=["20260601"])
        _attach_dragon_list_impacts(w, AS_OF)
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_checked_missing_seats_rejected(self):
        # 反向(b): seats_status=checked + 非 unchecked 日的 event 缺 seats → 拒(席位证据逐 event 覆盖)
        w = self._weekly_dl(events=[self._dl_event()], seats_status="checked")   # event 无 seats、无 unchecked
        _attach_dragon_list_impacts(w, AS_OF)
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_seats_missing_inst_net_rejected(self):
        # 反向(b): event 带 seats 却缺 inst_net_buy key → 拒
        w = self._weekly_dl(events=[self._dl_event()], seats_status="checked")
        w["dragon_list"]["events"][0]["seats"] = [{"exalter": "机构专用", "side": "0", "net_buy": 5e6}]
        _attach_dragon_list_impacts(w, AS_OF)
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_seats_without_status_rejected(self):
        # 反向(a): event 带 seats/inst_net_buy 但无 seats_status → 拒(无覆盖状态托管)
        w = self._weekly_dl(events=[self._dl_event()])                           # 无 seats_status
        w["dragon_list"]["events"][0]["seats"] = [{"exalter": "机构专用", "side": "0", "net_buy": 5e6}]
        w["dragon_list"]["events"][0]["inst_net_buy"] = 5e6
        _attach_dragon_list_impacts(w, AS_OF)
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_checked_empty_seats_accepted(self):
        # 正向: seats_status=checked + 查成日真无席位(seats=[], inst_net_buy=null)→ 接受(空 ≠ 未查)
        w = self._weekly_dl(events=[self._dl_event()], seats_status="checked")
        w["dragon_list"]["events"][0]["seats"] = []
        w["dragon_list"]["events"][0]["inst_net_buy"] = None
        _attach_dragon_list_impacts(w, AS_OF)
        validate_weekly_report(w, _feed())                                       # 不 raise

    def test_validator_unchecked_date_without_seats_accepted(self):
        # 正向: event 在 unchecked_seat_date 且不带 seats → 接受(未查成日不附 seats)
        w = self._weekly_dl(events=[self._dl_event()], seats_status="checked", unchecked_seat_dates=["20260605"])
        _attach_dragon_list_impacts(w, AS_OF)
        validate_weekly_report(w, _feed())                                       # 不 raise

    def test_render_seats_column(self):
        w = self._weekly_dl(events=[self._dl_event()], seats_status="checked")
        w["dragon_list"]["events"][0]["seats"] = [{"exalter": "机构专用", "side": "0", "net_buy": 5e6},
                                                  {"exalter": "游资", "side": "1", "net_buy": -1e6}]
        w["dragon_list"]["events"][0]["inst_net_buy"] = 5e6
        md = render_weekly_markdown(w)
        self.assertIn("2席", md)
        self.assertIn("机构净", md)

    def test_render_seats_unknown_line(self):
        self.assertIn("席位(top_inst)未核查",
                      render_weekly_markdown(self._weekly_dl(events=[self._dl_event()], seats_status="unknown_or_unavailable")))

    def test_render_seat_cell_unchecked(self):
        # 席位失败日的 event(无 seats)→ 席位栏「未核查」
        w = self._weekly_dl(events=[self._dl_event()], seats_status="checked", unchecked_seat_dates=["20260605"])
        self.assertIn("未核查", render_weekly_markdown(w))

    def test_main_wires_seats(self):
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
            (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
            (Path(td) / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
            out = Path(td) / "weekly.json"
            dprov = (lambda d: [{"ts_code": "600000.SH", "name": "测试", "net_amount": 1e6, "reason": "涨幅偏离"}] if d == "20260605" else [])
            iprov = (lambda d: [{"ts_code": "600000.SH", "exalter": "机构专用", "side": "0", "net_buy": 5e6}] if d == "20260605" else [])
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--out", str(out)],
                 price_provider=lambda code: _series(), dragon_list_provider=dprov,
                 dragon_list_days=_DL_WINDOW, dragon_list_inst_provider=iprov)
            loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(loaded["dragon_list"]["seats_status"], "checked")
        e = [x for x in loaded["dragon_list"]["events"] if x["ts_code"] == "600000.SH"][0]
        self.assertEqual((len(e["seats"]), e["inst_net_buy"]), (1, 5e6))

    # ── main wiring(注入 provider + trade_days → 端到端落盘 + 校验)──
    def test_main_wires_dragon_list(self):
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
            (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
            (Path(td) / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
            out = Path(td) / "weekly.json"
            prov = (lambda d: [{"ts_code": "600000.SH", "name": "测试", "net_amount": 1e6, "reason": "涨幅偏离"}]
                    if d == "20260605" else [])
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--out", str(out)],
                 price_provider=lambda code: _series(), dragon_list_provider=prov, dragon_list_days=_DL_WINDOW)
            loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(loaded["dragon_list"]["status"], "checked")
        self.assertEqual([e["ts_code"] for e in loaded["dragon_list"]["events"]], ["600000.SH"])
        rep = [r for r in loaded["reports"] if r["ts_code"] == "600000.SH"][0]
        self.assertIn("龙虎榜对照", rep["m67"]["精简结论区"]["板块资金事件"])
        self.assertTrue(any(i["source_field"] == "dragon_list_appearance" for i in (rep["machine"].get("operation_impact") or [])))

    def test_main_no_provider_dragon_unknown(self):
        # 无 --confirm / 不注入 dragon provider → dragon_list status=unknown_or_unavailable(unknown-not-clear,绝不当无上榜)
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
            (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
            (Path(td) / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--out", str(out)],
                 price_provider=lambda code: _series())
            loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(loaded["dragon_list"]["status"], "unknown_or_unavailable")

    # ── 第三刀: 非候选持仓纳入龙虎榜/席位对照 + Tier-3 板块资金事件 render 掩面放行 ──
    def test_card_field_unmasks_dragon_for_tier3(self):
        # Tier-3(account_position_only)的 板块资金事件 含「龙虎榜对照」(独立真取数,非 EGS 维度)→ render 不掩;无 marker → 仍掩
        from runners.a_short_m67_render import _card_field
        rep = {"row_source": "account_position_only",
               "m67": {"精简结论区": {"板块资金事件": "龙虎榜对照(comparison-only,不改决策):近5交易日2次上龙虎榜"}}}
        self.assertIn("龙虎榜对照", _card_field(rep, "板块资金事件"))
        rep2 = {"row_source": "account_position_only", "m67": {"精简结论区": {"板块资金事件": "半导体景气上行"}}}
        self.assertIn("未核查", _card_field(rep2, "板块资金事件"))   # 无 marker → 仍掩(EGS 维度未覆盖)

    def test_main_dragon_covers_holdings(self):
        # dragon universe = reports 行(候选 + 账户持仓);非候选持仓上榜 → 进 events + holding_row_impact(private_account)
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH")])
            acct = _account()
            acct["positions"] = [{"ts_code": "600519.SH", "name": "持仓", "shares": 100,
                                  "avg_cost": 10.0, "entry_date": "20260601", "stop_loss": 9.0}]
            (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
            (Path(td) / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
            _write_account(Path(td) / "acct.json", acct)
            out = Path(td) / "weekly.json"
            dprov = (lambda d: [{"ts_code": "600519.SH", "name": "持仓", "net_amount": 1e6, "reason": "涨幅偏离"}] if d == "20260605" else [])
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--account", str(Path(td) / "acct.json"),
                  "--out", str(out)], price_provider=lambda code: _series(),
                 dragon_list_provider=dprov, dragon_list_days=_DL_WINDOW)
            loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("600519.SH", [e["ts_code"] for e in loaded["dragon_list"]["events"]])   # 持仓进 universe
        rep = [r for r in loaded["reports"] if r["ts_code"] == "600519.SH"][0]
        imp = [i for i in (rep["machine"].get("operation_impact") or []) if i["source_field"] == "dragon_list_appearance"][0]
        self.assertEqual((imp["visibility_shape"], imp["privacy_class"]), ("holding_row_impact", "private_account"))


class BlockTradeTests(unittest.TestCase):
    """4.2 Round5 大宗交易第一刀(block_trade, analysis-only · comparison-only,镜像龙虎榜):provider fail-closed /
    builder PIT+unknown-not-clear+按(票,日)聚合(amount 合计+笔数)/ 候选+持仓落 板块资金事件+operation_impact /
    双向 no-dangling / comparison-only isolation(绝不改 EGS/TopN/操作/股数)/ render。买卖方营业部=第二刀。"""

    def _bt_event(self, ts="600000.SH", trade_date="20260605", amount=5e7, trade_count=1):
        # 第二刀:checked event 必有 parties 且 len==trade_count(helper 自动生成对齐)
        return {"ts_code": ts, "name": "测试", "trade_date": trade_date, "amount": amount, "trade_count": trade_count,
                "parties": [{"buyer": "机构专用", "seller": "游资", "amount": amount} for _ in range(trade_count)]}

    def _weekly_bt(self, status="checked", events=None, window=None, **extra):
        w = _weekly()
        bt = {"as_of": AS_OF, "status": status, "lookback_trading_days": 5,
              "window_dates": (window if window is not None else _DL_WINDOW), "events": events or []}
        bt.update(extra)
        w["block_trade"] = bt
        return w

    def _w_bt(self, status="checked", ts=None):
        w = _weekly()
        ts = ts or w["reports"][0]["ts_code"]
        w["block_trade"] = {"as_of": AS_OF, "status": status, "lookback_trading_days": 5, "window_dates": _DL_WINDOW,
                            "events": ([{"ts_code": ts, "name": "x", "trade_date": "20260605", "amount": 5e7, "trade_count": 1,
                                         "parties": [{"buyer": "机构专用", "seller": "游资", "amount": 5e7}]}] if status == "checked" else [])}
        return w

    def _btimp(self, rep):
        return [i for i in (rep["machine"].get("operation_impact") or []) if i["source_field"] == "block_trade_appearance"]

    def _schema(self):
        return json.load(open(SCHEMA_PATH, encoding="utf-8"))

    # ── provider(fail-closed)──
    def test_fetch_block_trade_fail_closed(self):
        class _Pro:
            def __init__(self, df): self._df = df
            def block_trade(self, **kw): return self._df
        self.assertIsNone(_fetch_block_trade(_Pro(pd.DataFrame({"ts_code": ["x"]})), "20260605"))   # 缺 amount
        self.assertIsNone(_fetch_block_trade(_Pro(pd.DataFrame({"ts_code": ["x"], "amount": [1.0]})), "20260605"))   # 第二刀 fail-closed:缺 buyer/seller 列
        self.assertIsNone(_fetch_block_trade(_Pro(pd.DataFrame({"ts_code": ["x"], "amount": [1.0], "buyer": ["a"], "seller": ["b"]})), "20260605"))   # 第三刀 fail-closed:缺 price 列
        class _Boom:
            def block_trade(self, **kw): raise RuntimeError("x")
        self.assertIsNone(_fetch_block_trade(_Boom(), "20260605"))
        self.assertEqual(_fetch_block_trade(_Pro(pd.DataFrame({"ts_code": [], "amount": [], "buyer": [], "seller": [], "price": []})), "20260605"), [])
        ok = _fetch_block_trade(_Pro(pd.DataFrame({"trade_date": ["20260605"], "ts_code": ["600000.SH"],
                                                   "price": [10.0], "vol": [1.0], "amount": [5e7],
                                                   "buyer": ["机构专用"], "seller": ["某游资"]})), "20260605")
        self.assertEqual(ok, [{"ts_code": "600000.SH", "amount": 5e7, "price": 10.0, "buyer": "机构专用", "seller": "某游资"}])

    # ── 第二刀: 买卖方营业部(parties)──
    def test_builder_collects_parties(self):
        prov = lambda d: ([{"ts_code": "600000.SH", "amount": 3e7, "buyer": "机构专用", "seller": "游资A"},
                           {"ts_code": "600000.SH", "amount": 2e7, "buyer": "游资B", "seller": "机构专用"}] if d == "20260605" else [])
        e = _block_trade_events([("600000.SH", "x")], AS_OF, prov, _DL_WINDOW)["events"][0]
        self.assertEqual(e["trade_count"], 2)
        self.assertEqual([(p["buyer"], p["seller"], p["amount"]) for p in e["parties"]],
                         [("机构专用", "游资A", 3e7), ("游资B", "机构专用", 2e7)])

    def test_render_shows_parties(self):
        w = self._weekly_bt(events=[self._bt_event()])
        w["block_trade"]["events"][0]["parties"] = [{"buyer": "机构专用", "seller": "游资A", "amount": 5e7}]
        md = render_weekly_markdown(w)
        self.assertIn("买卖方", md)
        self.assertIn("机构专用→游资A", md)

    def test_attach_text_mentions_parties(self):
        w = self._w_bt()
        w["block_trade"]["events"][0]["parties"] = [{"buyer": "机构专用", "seller": "游资A", "amount": 5e7}]
        _attach_block_trade_impacts(w, AS_OF)
        self.assertIn("买卖方机构专用→游资A", w["reports"][0]["m67"]["精简结论区"]["板块资金事件"])

    def test_schema_accepts_parties(self):
        w = self._weekly_bt(events=[self._bt_event()])
        w["block_trade"]["events"][0]["parties"] = [{"buyer": "机构专用", "seller": "游资A", "amount": 5e7}]
        _attach_block_trade_impacts(w, AS_OF)
        jsonschema.validate(w, self._schema())
        validate_weekly_report(w, _feed())

    def test_validator_missing_parties_rejected(self):
        # checked block_trade event 无 parties → schema(required)+ validator(len) 双拒(第二刀 parties no-dangling)
        ev = {"ts_code": "600000.SH", "name": "x", "trade_date": "20260605", "amount": 5e7, "trade_count": 1}
        w = self._weekly_bt(events=[ev])
        _attach_block_trade_impacts(w, AS_OF)
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(w, self._schema())

    def test_validator_party_count_mismatch_rejected(self):
        # len(parties) != trade_count → validator 拒(买卖方逐笔须与笔数一致)
        ev = {"ts_code": "600000.SH", "name": "x", "trade_date": "20260605", "amount": 5e7, "trade_count": 2,
              "parties": [{"buyer": "机构专用", "seller": "游资", "amount": 5e7}]}   # 1 party != count 2
        w = self._weekly_bt(events=[ev])
        _attach_block_trade_impacts(w, AS_OF)
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_blank_buyer_seller_legal(self):
        # 正向: 单元格空白 → party buyer/seller=None(列存在),len==count → 合法接受
        ev = {"ts_code": "600000.SH", "name": "x", "trade_date": "20260605", "amount": 5e7, "trade_count": 1,
              "parties": [{"buyer": None, "seller": None, "amount": 5e7}]}
        w = self._weekly_bt(events=[ev])
        _attach_block_trade_impacts(w, AS_OF)
        jsonschema.validate(w, self._schema())
        validate_weekly_report(w, _feed())

    def test_fetch_block_trade_nonfinite_amount_nulled(self):
        class _Pro:
            def block_trade(self, **kw):
                return pd.DataFrame({"ts_code": ["600000.SH", "600001.SH"], "amount": [float("inf"), float("nan")],
                                     "buyer": ["a", "b"], "seller": ["c", "d"], "price": [9.5, 9.6]})
        self.assertEqual([r["amount"] for r in _fetch_block_trade(_Pro(), "20260605")], [None, None])

    # ── builder(unknown-not-clear / 聚合 / 候选过滤)──
    def test_builder_provider_none_unknown(self):
        bt = _block_trade_events([("600000.SH", "x")], AS_OF, None, _DL_WINDOW)
        self.assertEqual((bt["status"], bt["events"], bt["window_dates"]), ("unknown_or_unavailable", [], _DL_WINDOW))

    def test_builder_all_fail_unknown(self):
        self.assertEqual(_block_trade_events([("600000.SH", "x")], AS_OF, lambda d: None, _DL_WINDOW)["status"], "unknown_or_unavailable")

    def test_builder_partial_fail_unchecked(self):
        prov = lambda d: [] if d == "20260609" else None
        bt = _block_trade_events([("600000.SH", "x")], AS_OF, prov, _DL_WINDOW)
        self.assertEqual((bt["status"], bt["events"]), ("checked", []))
        self.assertEqual(bt["unchecked_dates"], ["20260603", "20260604", "20260605", "20260608"])

    def test_builder_aggregates_per_stock_day(self):
        # 同(票,日)多笔 → 聚合 amount 合计 + trade_count 笔数;非候选丢弃
        prov = lambda d: ([{"ts_code": "600000.SH", "amount": 3e7}, {"ts_code": "600000.SH", "amount": 2e7},
                           {"ts_code": "600999.SH", "amount": 1e7}] if d == "20260605" else [])
        bt = _block_trade_events([("600000.SH", "x")], AS_OF, prov, _DL_WINDOW)
        self.assertEqual(len(bt["events"]), 1)
        e = bt["events"][0]
        self.assertEqual((e["ts_code"], e["trade_date"], e["amount"], e["trade_count"]), ("600000.SH", "20260605", 5e7, 2))

    def test_builder_amount_all_none_kept_null(self):
        prov = lambda d: ([{"ts_code": "600000.SH", "amount": None}, {"ts_code": "600000.SH", "amount": None}] if d == "20260605" else [])
        e = _block_trade_events([("600000.SH", "x")], AS_OF, prov, _DL_WINDOW)["events"][0]
        self.assertEqual((e["amount"], e["trade_count"]), (None, 2))   # 金额全缺→None,笔数仍计

    # ── attach(候选/held;comparison-only;no-EGS-change)──
    def test_attach_candidate_landing(self):
        w = self._w_bt()
        rep = w["reports"][0]
        before = (rep["m67"]["table"]["操作"], rep["m67"]["table"]["EGS分"], rep["m67"]["table"]["股数"])
        _attach_block_trade_impacts(w, AS_OF)
        imp = self._btimp(rep)
        self.assertEqual(len(imp), 1)
        self.assertEqual((imp[0]["visibility_shape"], imp[0]["new_entry_effect"], imp[0]["holding_effect"], imp[0]["veto_class"]),
                         ("candidate_row_impact", "informational", "none", "none"))
        self.assertFalse(imp[0]["production_effect_enabled"])
        self.assertIn("大宗交易对照", rep["m67"]["精简结论区"]["板块资金事件"])
        self.assertEqual((rep["m67"]["table"]["操作"], rep["m67"]["table"]["EGS分"], rep["m67"]["table"]["股数"]), before)
        validate_weekly_report(w, _feed())

    def test_attach_held_holding_impact(self):
        w = self._w_bt()
        rep = w["reports"][0]
        rep["machine"]["stateful_risk"] = {"position_state": "held", "rule12": {"status": "inactive"},
                                           "rule13": {"status": "none"}, "reasons": []}
        _attach_block_trade_impacts(w, AS_OF)
        imp = self._btimp(rep)[0]
        self.assertEqual((imp["visibility_shape"], imp["privacy_class"]), ("holding_row_impact", "private_account"))
        _vop(rep)

    def test_attach_unknown_no_landing(self):
        w = self._w_bt(status="unknown_or_unavailable")
        _attach_block_trade_impacts(w, AS_OF)
        self.assertEqual(self._btimp(w["reports"][0]), [])

    # ── schema + validator(双向 no-dangling / PIT / 窗口 / 张冠李戴)──
    def test_schema_and_validator_accept(self):
        w = self._weekly_bt(events=[self._bt_event()])
        _attach_block_trade_impacts(w, AS_OF)
        jsonschema.validate(w, self._schema())
        validate_weekly_report(w, _feed())

    def test_absent_is_valid(self):
        jsonschema.validate(_weekly(), self._schema())
        validate_weekly_report(_weekly(), _feed())

    def test_schema_accept_unknown(self):
        validate_weekly_report(self._weekly_bt(status="unknown_or_unavailable"), _feed())

    def test_dragon_impact_passes_m67_schema(self):
        w = self._w_bt()
        _attach_block_trade_impacts(w, AS_OF)
        jsonschema.validate(w["reports"][0], json.load(open(M67_SCHEMA, encoding="utf-8")))

    def test_validator_unknown_with_events_rejected(self):
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_bt(status="unknown_or_unavailable", events=[self._bt_event()]), _feed())

    def test_validator_foreign_ts_rejected(self):
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_bt(events=[self._bt_event(ts="600999.SH")]), _feed())

    def test_validator_event_after_as_of_rejected(self):
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_bt(events=[self._bt_event(trade_date="20260610")]), _feed())

    def test_validator_event_outside_window_rejected(self):
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_bt(events=[self._bt_event(trade_date="20260601")]), _feed())

    def test_validator_reverse_evidence_bad_ref_rejected(self):
        w = self._weekly_bt(events=[self._bt_event()])
        _attach_block_trade_impacts(w, AS_OF)
        self._btimp(w["reports"][0])[0]["evidence_ref"]["value"] = "fake"
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_forward_landing_dangling_rejected(self):
        with self.assertRaises(ValueError):                               # checked event 不 attach → 悬空
            validate_weekly_report(self._weekly_bt(events=[self._bt_event()]), _feed())

    # ── engine guard ⑭(comparison-only isolation)──
    def _landed_rep(self):
        w = self._w_bt()
        _attach_block_trade_impacts(w, AS_OF)
        return w["reports"][0]

    def _landed_rep_held(self):
        w = self._w_bt()
        w["reports"][0]["machine"]["stateful_risk"] = {"position_state": "held", "rule12": {"status": "inactive"},
                                                       "rule13": {"status": "none"}, "reasons": []}
        _attach_block_trade_impacts(w, AS_OF)
        return w["reports"][0]

    def test_validator_checked_empty_window_rejected(self):
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_bt(status="checked", events=[], window=[]), _feed())

    def test_validator_checked_all_unchecked_rejected(self):
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_bt(status="checked", events=[], unchecked_dates=list(_DL_WINDOW)), _feed())

    def test_validator_partial_unchecked_legal(self):
        validate_weekly_report(self._weekly_bt(status="checked", events=[], unchecked_dates=["20260603", "20260604"]), _feed())

    def test_guard_held_public_candidate_mutation_rejected(self):
        rep = self._landed_rep_held()
        imp = self._btimp(rep)[0]
        imp["visibility_shape"], imp["privacy_class"] = "candidate_row_impact", "public_tracked"
        with self.assertRaises(ValueError):
            _vop(rep)

    def test_guard_legal_passes(self):
        _vop(self._landed_rep())

    def test_guard_production_enabled_rejected(self):
        rep = self._landed_rep(); self._btimp(rep)[0]["production_effect_enabled"] = True
        with self.assertRaises(ValueError):
            _vop(rep)

    def test_guard_veto_rejected(self):
        rep = self._landed_rep(); self._btimp(rep)[0]["veto_class"] = "m67_advisory_veto"
        with self.assertRaises(ValueError):
            _vop(rep)

    def test_guard_new_entry_effect_rejected(self):
        rep = self._landed_rep(); self._btimp(rep)[0]["new_entry_effect"] = "sizing_down"
        with self.assertRaises(ValueError):
            _vop(rep)

    def test_guard_holding_effect_rejected(self):
        rep = self._landed_rep(); self._btimp(rep)[0]["holding_effect"] = "hold_watch"
        with self.assertRaises(ValueError):
            _vop(rep)

    def test_guard_marker_removed_rejected(self):
        rep = self._landed_rep(); rep["m67"]["精简结论区"]["板块资金事件"] = "unknown"
        with self.assertRaises(ValueError):
            _vop(rep)

    # ── render ──
    def test_render_checked_lists(self):
        md = render_weekly_markdown(self._weekly_bt(events=[self._bt_event()]))
        self.assertIn("大宗交易", md)
        self.assertIn("20260605", md)

    def test_render_unknown(self):
        self.assertIn("未取到大宗交易", render_weekly_markdown(self._weekly_bt(status="unknown_or_unavailable")))

    def test_render_checked_empty(self):
        self.assertIn("无大宗交易记录", render_weekly_markdown(self._weekly_bt(status="checked", events=[])))

    # ── main wiring(注入 provider + 复用 trade_cal 窗口;持仓覆盖)──
    def test_main_wires_block_trade(self):
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
            (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
            (Path(td) / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
            out = Path(td) / "weekly.json"
            prov = (lambda d: [{"ts_code": "600000.SH", "amount": 5e7}, {"ts_code": "600000.SH", "amount": 2e7}] if d == "20260605" else [])
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--out", str(out)],
                 price_provider=lambda code: _series(), block_trade_provider=prov, dragon_list_days=_DL_WINDOW)
            loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(loaded["block_trade"]["status"], "checked")
        e = [x for x in loaded["block_trade"]["events"] if x["ts_code"] == "600000.SH"][0]
        self.assertEqual((e["amount"], e["trade_count"]), (7e7, 2))
        rep = [r for r in loaded["reports"] if r["ts_code"] == "600000.SH"][0]
        self.assertTrue(any(i["source_field"] == "block_trade_appearance" for i in (rep["machine"].get("operation_impact") or [])))

    def test_main_no_provider_block_trade_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
            (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
            (Path(td) / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
            out = Path(td) / "weekly.json"
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--out", str(out)],
                 price_provider=lambda code: _series())
            loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(loaded["block_trade"]["status"], "unknown_or_unavailable")

    # ── 第三刀: 折价率(raw-close provider / discount compute / coverage / validator / render / attach / main)──
    def _w_disc(self, close=10.0, price=9.5, close_prov=None, block_prov=None):
        # 经真 builder + close_provider 构造带折价的 checked block_trade(落 report[0]),再 attach。
        w = _weekly()
        ts = w["reports"][0]["ts_code"]
        bp = block_prov or (lambda d: ([{"ts_code": ts, "amount": 5e7, "price": price, "buyer": "机构专用", "seller": "游资"}] if d == "20260605" else []))
        cp = close_prov or (lambda d: ({ts: close} if d == "20260605" else {}))
        w["block_trade"] = _block_trade_events([(ts, "x")], AS_OF, bp, _DL_WINDOW, close_provider=cp)
        _attach_block_trade_impacts(w, AS_OF)
        return w

    def test_fetch_daily_close_fail_closed(self):
        class _Pro:
            def __init__(self, df): self._df = df
            def daily(self, **kw): return self._df
        self.assertIsNone(_fetch_daily_close(_Pro(pd.DataFrame({"ts_code": ["x"]})), "20260605"))   # 缺 close 列
        self.assertIsNone(_fetch_daily_close(_Pro(pd.DataFrame({"close": [1.0]})), "20260605"))      # 缺 ts_code 列
        class _Boom:
            def daily(self, **kw): raise RuntimeError("x")
        self.assertIsNone(_fetch_daily_close(_Boom(), "20260605"))
        self.assertEqual(_fetch_daily_close(_Pro(pd.DataFrame({"ts_code": [], "close": []})), "20260605"), {})
        ok = _fetch_daily_close(_Pro(pd.DataFrame({"ts_code": ["600000.SH"], "trade_date": ["20260605"], "close": [10.0]})), "20260605")
        self.assertEqual(ok, {"600000.SH": 10.0})

    def test_fetch_daily_close_nonfinite_nulled(self):
        class _Pro:
            def daily(self, **kw):
                return pd.DataFrame({"ts_code": ["600000.SH", "600001.SH"], "close": [float("inf"), float("nan")]})
        self.assertEqual(_fetch_daily_close(_Pro(), "20260605"), {"600000.SH": None, "600001.SH": None})

    def test_fetch_block_trade_returns_price(self):
        class _Pro:
            def block_trade(self, **kw):
                return pd.DataFrame({"trade_date": ["20260605"], "ts_code": ["600000.SH"], "price": [9.5],
                                     "vol": [1.0], "amount": [5e7], "buyer": ["a"], "seller": ["b"]})
        self.assertEqual(_fetch_block_trade(_Pro(), "20260605")[0]["price"], 9.5)

    def test_builder_discount_unwired_unchanged(self):
        # close_provider 未接线(第二刀式)→ 无 discount_status,event 无 close,party 无 discount(输出与第二刀一致)
        prov = lambda d: ([{"ts_code": "600000.SH", "amount": 5e7, "price": 9.5, "buyer": "a", "seller": "b"}] if d == "20260605" else [])
        bt = _block_trade_events([("600000.SH", "x")], AS_OF, prov, _DL_WINDOW)
        self.assertNotIn("discount_status", bt)
        self.assertNotIn("close", bt["events"][0])
        self.assertNotIn("discount", bt["events"][0]["parties"][0])

    def test_builder_computes_discount_raw_close(self):
        # 折价: price 9.5 < raw close 10.0 → discount = -0.05;基准=未复权 close(独立 provider,非前复权)
        w = self._w_disc(close=10.0, price=9.5)
        e = w["block_trade"]["events"][0]
        self.assertEqual(e["close"], 10.0)
        self.assertAlmostEqual(e["parties"][0]["discount"], -0.05)
        self.assertEqual(w["block_trade"]["discount_status"], "checked")
        validate_weekly_report(w, _feed())
        jsonschema.validate(w, self._schema())

    def test_builder_premium_positive(self):
        # 溢价: price 10.5 > close 10.0 → discount = +0.05
        e = self._w_disc(close=10.0, price=10.5)["block_trade"]["events"][0]
        self.assertAlmostEqual(e["parties"][0]["discount"], 0.05)

    def test_builder_discount_all_fail_unknown(self):
        # close_provider 全失败 → discount_status=unknown(绝不当无折价),event 无 close/discount
        w = self._w_disc(close_prov=lambda d: None)
        self.assertEqual(w["block_trade"]["discount_status"], "unknown_or_unavailable")
        e = w["block_trade"]["events"][0]
        self.assertNotIn("close", e)
        self.assertNotIn("discount", e["parties"][0])
        validate_weekly_report(w, _feed())

    def test_builder_discount_close_zero_nulled(self):
        # raw close=0 → discount=None(不除零),但 close 键存在(查成)
        w = self._w_disc(close=0.0)
        e = w["block_trade"]["events"][0]
        self.assertEqual(e["close"], 0.0)
        self.assertIsNone(e["parties"][0]["discount"])
        validate_weekly_report(w, _feed())

    def test_builder_discount_stock_no_close_nulled(self):
        # 该日收盘查成但该股无 close(停牌)→ event.close=None,party.discount=None(键在值 null,不伪造)
        w = self._w_disc(close_prov=lambda d: {})
        e = w["block_trade"]["events"][0]
        self.assertIsNone(e["close"])
        self.assertIsNone(e["parties"][0]["discount"])
        self.assertEqual(w["block_trade"]["discount_status"], "checked")
        validate_weekly_report(w, _feed())

    def test_builder_discount_partial_unchecked(self):
        # 多事件日: 一日 close 查成、一日失败 → checked + unchecked_discount_dates,失败日 event 无 close
        ts = "600000.SH"
        bp = lambda d: ([{"ts_code": ts, "amount": 5e7, "price": 9.5, "buyer": "a", "seller": "b"}] if d in ("20260605", "20260608") else [])
        cp = lambda d: ({ts: 10.0} if d == "20260605" else None)   # 20260608 收盘取数失败
        bt = _block_trade_events([(ts, "x")], AS_OF, bp, _DL_WINDOW, close_provider=cp)
        self.assertEqual(bt["discount_status"], "checked")
        self.assertEqual(bt["unchecked_discount_dates"], ["20260608"])
        by_day = {e["trade_date"]: e for e in bt["events"]}
        self.assertEqual(by_day["20260605"]["close"], 10.0)
        self.assertNotIn("close", by_day["20260608"])
        self.assertNotIn("discount", by_day["20260608"]["parties"][0])

    def test_validator_close_without_status_rejected(self):
        w = self._w_disc(); del w["block_trade"]["discount_status"]   # event 带 close 但无覆盖状态托管
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_checked_event_missing_close_rejected(self):
        w = self._w_disc(); del w["block_trade"]["events"][0]["close"]   # checked 查成日 event 缺 close
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_checked_party_missing_discount_rejected(self):
        w = self._w_disc(); del w["block_trade"]["events"][0]["parties"][0]["discount"]   # checked 查成日 party 缺 discount
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_checked_party_missing_price_rejected(self):
        # checked 查成日 party 缺 price 证据键 → 拒(折价层缺料却标 checked = 假覆盖)
        w = self._w_disc(); del w["block_trade"]["events"][0]["parties"][0]["price"]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_builder_discount_blank_price_legal(self):
        # price 单元格空白(列在,值 None)→ party.price=None 键在、discount=None,checked 合法接受(不误拒)
        w = self._w_disc(price=None)
        e = w["block_trade"]["events"][0]
        self.assertIsNone(e["parties"][0]["price"])
        self.assertIsNone(e["parties"][0]["discount"])
        self.assertEqual(w["block_trade"]["discount_status"], "checked")
        validate_weekly_report(w, _feed())
        jsonschema.validate(w, self._schema())

    def test_builder_discount_row_missing_price_provenance_rejected(self):
        # 注入/未来 block_provider 行**缺 price 键**(契约违反)+ close 接线 → builder 不补 price=None(不伪造),
        # party 无 price 键 → validator 拒(checked 折价层缺 price 溯源)。区别于空白 cell(行带 price=None 键,合法)。
        w = _weekly()
        ts = w["reports"][0]["ts_code"]
        bp = lambda d: ([{"ts_code": ts, "amount": 5e7, "buyer": "a", "seller": "b"}] if d == "20260605" else [])  # 行无 price 键
        cp = lambda d: ({ts: 10.0} if d == "20260605" else {})
        w["block_trade"] = _block_trade_events([(ts, "x")], AS_OF, bp, _DL_WINDOW, close_provider=cp)
        _attach_block_trade_impacts(w, AS_OF)
        self.assertNotIn("price", w["block_trade"]["events"][0]["parties"][0])   # builder 不补 price 键(溯源保真)
        self.assertEqual(w["block_trade"]["discount_status"], "checked")          # close 查成
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_unchecked_discount_date_with_close_rejected(self):
        w = self._w_disc(); w["block_trade"]["unchecked_discount_dates"] = ["20260605"]   # 该 event 日标 unchecked 却带 close
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_unknown_discount_with_close_rejected(self):
        w = self._w_disc(); w["block_trade"]["discount_status"] = "unknown_or_unavailable"   # unknown 却 event 带 close/discount
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_unchecked_discount_date_outside_window_rejected(self):
        w = self._w_disc(); w["block_trade"]["unchecked_discount_dates"] = ["20260601"]   # 不在 window
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_unchecked_discount_without_checked_rejected(self):
        # unchecked_discount_dates 存在但 discount_status 非 checked → 拒(先去 close/discount 以隔离该 guard)
        w = self._w_disc()
        del w["block_trade"]["discount_status"]
        w["block_trade"]["events"][0].pop("close", None)
        for p in w["block_trade"]["events"][0]["parties"]:
            p.pop("discount", None)
        w["block_trade"]["unchecked_discount_dates"] = ["20260605"]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_guard_discount_isolation_passes(self):
        # 折价率 attach 后仍是 comparison-only:engine no-dangling guard 通过(不引入决策字段)
        _vop(self._w_disc()["reports"][0])

    def test_render_shows_discount(self):
        md = render_weekly_markdown(self._w_disc(close=10.0, price=9.5))
        self.assertIn("折价率", md)
        self.assertIn("-5.00%", md)

    def test_render_discount_unknown_caveat(self):
        md = render_weekly_markdown(self._w_disc(close_prov=lambda d: None))
        self.assertIn("折价率未核查", md)

    def test_attach_text_mentions_discount(self):
        w = self._w_disc(close=10.0, price=9.5)
        self.assertIn("折价率-5.00%", w["reports"][0]["m67"]["精简结论区"]["板块资金事件"])

    def test_main_wires_daily_close_discount(self):
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
            (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
            (Path(td) / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
            out = Path(td) / "weekly.json"
            bprov = lambda d: ([{"ts_code": "600000.SH", "amount": 5e7, "price": 9.5, "buyer": "机构专用", "seller": "游资"}] if d == "20260605" else [])
            cprov = lambda d: ({"600000.SH": 10.0} if d == "20260605" else {})
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--out", str(out)],
                 price_provider=lambda code: _series(), block_trade_provider=bprov,
                 daily_close_provider=cprov, dragon_list_days=_DL_WINDOW)
            loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(loaded["block_trade"]["discount_status"], "checked")
        e = [x for x in loaded["block_trade"]["events"] if x["ts_code"] == "600000.SH"][0]
        self.assertEqual(e["close"], 10.0)
        self.assertAlmostEqual(e["parties"][0]["discount"], -0.05)


class FinancialTrendsTests(unittest.TestCase):
    """4.2 财报质量趋势 ②业绩预告 forecast(框架 + forecast):per-stock 新增报表取数 → 自然符号红旗(tushare 预告 type 负面分类 /
    p_change_max<0)→ advisory priority_down operation_impact + 风控触发(财报趋势对照);comparison-only · candidate-only · 绝不
    hard_veto/非生产/不改 EGS/选股/股数;unknown-not-clear;不新设阈值(决策4)。"""

    def _rec(self, ts="600000.SH", stype="forecast", period="20260331", observed_at="20260415",
             flags=None, summary="业绩预告类型「预减」(负面)(报告期20260331)"):
        return {"ts_code": ts, "name": "测试", "statement_type": stype, "period": period,
                "observed_at": observed_at, "red_flags": flags or ["业绩预告类型「预减」(负面)"], "summary": summary}

    def _weekly_ft(self, status="checked", records=None):
        w = _weekly()
        w["financial_trends"] = {"as_of": AS_OF, "status": status, "records": records if records is not None else []}
        return w

    def _fc(self, ann="20260415", end="20260331", ftype="预减", pmin=None, pmax=None):
        return {"ann_date": ann, "end_date": end, "type": ftype, "p_change_min": pmin, "p_change_max": pmax}

    # ── forecast 自然符号红旗(不新设阈值)──
    def test_forecast_neg_type_flags(self):
        res = _forecast_red_flags([self._fc(ftype="预减")], AS_OF)
        self.assertIsNotNone(res)
        self.assertTrue(any("预减" in f for f in res[0]))

    def test_forecast_positive_type_no_flag(self):
        # 扭亏=正面(含「亏」但不含负面分类子串 预减/略减/首亏/续亏)+ p_change_max>0 → 无红旗(substring 不误撞)
        self.assertIsNone(_forecast_red_flags([self._fc(ftype="扭亏", pmin=50, pmax=120)], AS_OF))

    def test_forecast_续盈_no_flag(self):
        self.assertIsNone(_forecast_red_flags([self._fc(ftype="续盈", pmin=5, pmax=20)], AS_OF))

    def test_forecast_pchange_max_negative_flags(self):
        # p_change_max<0 → 必降(自然符号),即使 type 非负面分类
        res = _forecast_red_flags([self._fc(ftype="略增", pmin=-30, pmax=-5)], AS_OF)
        self.assertIsNotNone(res)
        self.assertTrue(any("上限" in f for f in res[0]))

    def test_forecast_pchange_min_negative_alone_no_flag(self):
        # 仅下限<0、上限>=0 → 区间含正,不武断红旗(不新设阈值)
        self.assertIsNone(_forecast_red_flags([self._fc(ftype="略增", pmin=-5, pmax=20)], AS_OF))

    def test_forecast_pit_lookahead_skipped(self):
        # ann_date > as_of → look-ahead 丢弃 → 无可用 → None
        self.assertIsNone(_forecast_red_flags([self._fc(ann="20260701", end="20260630")], AS_OF))

    def test_forecast_nearest_period(self):
        # PIT 最近报告期(20260331 预减红旗),不被更早 20250930 预增覆盖
        recs = [self._fc(ann="20260415", end="20260331", ftype="预减"),
                self._fc(ann="20251015", end="20250930", ftype="预增", pmin=10, pmax=30)]
        res = _forecast_red_flags(recs, AS_OF)
        self.assertIsNotNone(res)
        self.assertEqual(res[2], "20260331")

    def test_forecast_empty_no_flag(self):
        self.assertIsNone(_forecast_red_flags([], AS_OF))

    def test_forecast_missing_ann_skipped(self):
        self.assertIsNone(_forecast_red_flags([self._fc(ann=None)], AS_OF))   # 无公告日 → 无法 PIT,丢弃

    # ── ③ income 自然符号红旗(归母净利<0 / 营收·毛利率·净利率同比下滑;不新设阈值)──
    def _inc(self, ann="20260415", end="20260331", trev=1000.0, rev=1000.0, cost=600.0, ni=100.0, napt=100.0):
        return {"ann_date": ann, "end_date": end, "total_revenue": trev, "revenue": rev,
                "oper_cost": cost, "n_income": ni, "n_income_attr_p": napt}

    def test_income_loss_flags(self):
        res = _income_red_flags([self._inc(napt=-50.0, ni=-50.0)], AS_OF)   # q0 only(无同期)→ 仅亏损
        self.assertIsNotNone(res)
        self.assertTrue(any("亏损" in f for f in res[0]))

    def test_income_revenue_decline_yoy(self):
        recs = [self._inc(end="20260331", ann="20260415", trev=800.0, rev=800.0, cost=480.0),
                self._inc(end="20250331", ann="20250415", trev=1000.0, rev=1000.0, cost=600.0)]   # gm/nm 持平,仅营收降
        res = _income_red_flags(recs, AS_OF)
        self.assertTrue(any("营收同比下滑" in f for f in res[0]))

    def test_income_gross_margin_decline_yoy(self):
        recs = [self._inc(end="20260331", ann="20260415", cost=700.0),     # gm=(1000-700)/1000=0.30
                self._inc(end="20250331", ann="20250415", cost=600.0)]     # gm=0.40 → q0<q1
        res = _income_red_flags(recs, AS_OF)
        self.assertTrue(any("毛利率同比下滑" in f for f in res[0]))

    def test_income_net_margin_decline_yoy(self):
        recs = [self._inc(end="20260331", ann="20260415", napt=80.0, ni=80.0),    # nm=0.08
                self._inc(end="20250331", ann="20250415", napt=120.0, ni=120.0)]  # nm=0.12 → q0<q1
        res = _income_red_flags(recs, AS_OF)
        self.assertTrue(any("净利率同比下滑" in f for f in res[0]))

    def test_income_healthy_no_flag(self):
        recs = [self._inc(end="20260331", ann="20260415", trev=1100.0, rev=1100.0, cost=600.0, napt=150.0, ni=150.0),
                self._inc(end="20250331", ann="20250415")]   # 营收↑/毛利率↑/净利率↑/盈利 → 无红旗
        self.assertIsNone(_income_red_flags(recs, AS_OF))

    def test_income_no_prior_yoy_skipped(self):
        # 仅 q0、盈利、无同期基数 → 同比类不判(不伪造)→ None
        self.assertIsNone(_income_red_flags([self._inc(napt=100.0)], AS_OF))

    def test_income_pit_lookahead_skipped(self):
        self.assertIsNone(_income_red_flags([self._inc(ann="20260701", end="20260630", napt=-50.0)], AS_OF))

    def test_builder_income_emits(self):
        # type-agnostic builder 分派 income red-flag fn
        ft = _financial_trends([("600000.SH", "x")], AS_OF, income_provider=lambda c: [self._inc(napt=-50.0, ni=-50.0)])
        self.assertEqual(ft["status"], "checked")
        self.assertEqual(ft["records"][0]["statement_type"], "income")

    # ── ④ balancesheet 自然符号方向红旗(资产负债率↑/应收占比↑/存货占比↑/商誉减值;全 YoY,不新设阈值)──
    def _bs(self, ann="20260415", end="20260331", ta=10000.0, liab=4000.0, ar=1000.0, inv=1000.0, gw=0.0):
        return {"ann_date": ann, "end_date": end, "total_assets": ta, "total_liab": liab,
                "accounts_receiv": ar, "inventories": inv, "goodwill": gw}

    def test_bs_debt_ratio_rising(self):
        recs = [self._bs(end="20260331", ann="20260415", liab=5000.0),    # 50%
                self._bs(end="20250331", ann="20250415", liab=4000.0)]    # 40% → 上升(应收/存货/商誉 持平/0,仅负债率)
        self.assertTrue(any("资产负债率上升" in f for f in _balancesheet_red_flags(recs, AS_OF)[0]))

    def test_bs_receivables_rising(self):
        recs = [self._bs(end="20260331", ann="20260415", ar=2000.0),     # 20%
                self._bs(end="20250331", ann="20250415", ar=1000.0)]     # 10% → 上升
        self.assertTrue(any("应收占比上升" in f for f in _balancesheet_red_flags(recs, AS_OF)[0]))

    def test_bs_inventory_rising(self):
        recs = [self._bs(end="20260331", ann="20260415", inv=2000.0),
                self._bs(end="20250331", ann="20250415", inv=1000.0)]
        self.assertTrue(any("存货占比上升" in f for f in _balancesheet_red_flags(recs, AS_OF)[0]))

    def test_bs_goodwill_impairment(self):
        recs = [self._bs(end="20260331", ann="20260415", gw=500.0),      # 商誉 500
                self._bs(end="20250331", ann="20250415", gw=1000.0)]     # 商誉 1000 → q0<q1 且 q1>0 → 减值迹象
        self.assertTrue(any("商誉减值迹象" in f for f in _balancesheet_red_flags(recs, AS_OF)[0]))

    def test_bs_goodwill_increase_no_flag(self):
        recs = [self._bs(end="20260331", ann="20260415", gw=1000.0),
                self._bs(end="20250331", ann="20250415", gw=500.0)]      # 商誉↑(新并购)→ 非减值 → 无红旗(其余持平)
        self.assertIsNone(_balancesheet_red_flags(recs, AS_OF))

    def test_bs_healthy_no_flag(self):
        recs = [self._bs(end="20260331", ann="20260415", liab=3000.0, ar=800.0, inv=800.0, gw=1000.0),   # 负债率/应收/存货↓、商誉↑
                self._bs(end="20250331", ann="20250415", liab=4000.0, ar=1000.0, inv=1000.0, gw=500.0)]
        self.assertIsNone(_balancesheet_red_flags(recs, AS_OF))

    def test_bs_no_prior_no_flag(self):
        # 全为同期比较,无去年同期基数 → 无红旗(不用绝对阈值兜底)
        self.assertIsNone(_balancesheet_red_flags([self._bs(liab=9000.0)], AS_OF))

    def test_bs_pit_lookahead_skipped(self):
        self.assertIsNone(_balancesheet_red_flags([self._bs(ann="20260701", end="20260630", liab=9000.0)], AS_OF))

    def test_builder_balancesheet_emits(self):
        recs = [self._bs(end="20260331", ann="20260415", liab=5000.0), self._bs(end="20250331", ann="20250415", liab=4000.0)]
        ft = _financial_trends([("600000.SH", "x")], AS_OF, balancesheet_provider=lambda c: recs)
        self.assertEqual(ft["status"], "checked")
        self.assertEqual(ft["records"][0]["statement_type"], "balancesheet")

    # ── ⑤ industry_fundamentals 行业基本面(advisory-only · summary_only · 候选 scope · 聚合③④ income/balancesheet)──
    def _ft_bf(self, ts="600000.SH", stype="income", flags=None, summary="营收同比下滑(报告期20260331 vs 20250331)"):
        return {"ts_code": ts, "name": "测试", "statement_type": stype, "period": "20260331",
                "observed_at": "20260415", "red_flags": flags or ["营收同比下滑"], "summary": summary}

    def test_indf_aggregates_by_industry(self):
        ft = {"status": "checked", "records": [self._ft_bf("600000.SH", "income"),
                                               self._ft_bf("000001.SZ", "balancesheet", flags=["资产负债率上升"])]}
        indf = _industry_fundamentals(ft, {"600000.SH": "半导体", "000001.SZ": "半导体", "600519.SH": "白酒"}, AS_OF)
        self.assertEqual(indf["scope"], "candidates_only")
        names = [g["sw_l2_name"] for g in indf["by_industry"]]
        self.assertIn("半导体", names)
        self.assertNotIn("白酒", names)                      # 白酒无红旗候选 → 不列(避噪声)
        g = [x for x in indf["by_industry"] if x["sw_l2_name"] == "半导体"][0]
        self.assertEqual((g["candidate_count"], g["red_flag_candidate_count"]), (2, 2))
        self.assertEqual(sorted(g["red_flag_codes"]), ["000001.SZ", "600000.SH"])

    def test_indf_excludes_forecast(self):
        # 行业基本面=已实现 income/balancesheet,②预告 forecast 不计
        ft = {"status": "checked", "records": [self._ft_bf("600000.SH", "forecast", flags=["业绩预告类型「预减」(负面)"])]}
        self.assertIsNone(_industry_fundamentals(ft, {"600000.SH": "半导体"}, AS_OF))

    def test_indf_unknown_status_none(self):
        self.assertIsNone(_industry_fundamentals({"status": "unknown_or_unavailable", "records": []}, {}, AS_OF))

    def _weekly_indf(self, by_industry=None, ft_records=None):
        w = _weekly()
        recs = ft_records if ft_records is not None else [self._ft_bf("600000.SH", "income")]
        w["financial_trends"] = {"as_of": AS_OF, "status": "checked", "records": recs}
        _attach_financial_trend_impacts(w, AS_OF)            # 满足 financial_trends forward no-dangling(income 记录落逐票)
        if by_industry is None:
            by_industry = [{"sw_l2_name": "半导体", "candidate_count": 1, "red_flag_candidate_count": 1,
                            "red_flag_codes": ["600000.SH"], "summary": "半导体:1 候选中 1 只有财报红旗(营收同比下滑)"}]
        w["industry_fundamentals"] = {"as_of": AS_OF, "scope": "candidates_only", "by_industry": by_industry}
        return w

    def test_validator_indf_accept(self):
        w = self._weekly_indf()
        jsonschema.validate(w, json.load(open(SCHEMA_PATH, encoding="utf-8")))
        validate_weekly_report(w, _feed())

    def test_validator_indf_bad_scope_rejected(self):
        w = self._weekly_indf()
        w["industry_fundamentals"]["scope"] = "full_industry"   # 必 candidates_only
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_indf_foreign_ts_rejected(self):
        w = self._weekly_indf(by_industry=[{"sw_l2_name": "半导体", "candidate_count": 1, "red_flag_candidate_count": 1,
                                            "red_flag_codes": ["600999.SH"], "summary": "x"}])   # 张冠李戴
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_indf_source_not_rolled_rejected(self):
        # income 记录存在但未进任何行业 rollup → 反向 reject(行业聚合漏票)
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_indf(by_industry=[]), _feed())

    def test_render_indf(self):
        self.assertIn("行业基本面", render_weekly_markdown(self._weekly_indf()))

    def test_main_industry_fundamentals(self):
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
            (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
            (Path(td) / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
            out = Path(td) / "weekly.json"
            iprov = lambda c: ([{"ann_date": "20260415", "end_date": "20260331", "total_revenue": 800.0,
                                 "revenue": 800.0, "oper_cost": 700.0, "n_income": -50.0, "n_income_attr_p": -50.0}]
                               if c == "600000.SH" else [])
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--out", str(out)],
                 price_provider=lambda code: _series(), income_provider=iprov, dragon_list_days=_DL_WINDOW)
            loaded = json.loads(out.read_text(encoding="utf-8"))
        indf = loaded.get("industry_fundamentals")
        self.assertIsNotNone(indf)
        self.assertEqual(indf["scope"], "candidates_only")
        self.assertTrue(any("600000.SH" in g["red_flag_codes"] for g in indf["by_industry"]))

    # ── provider 字段覆盖 fail-closed(R-ASHORT-GAP42-FINANCIAL-TRENDS-PROVIDER-FIELD-COVERAGE-GUARD-GAP):
    #    缺 red-flag 输入列 → None(未查成),绝不静默当「已查无红旗」;列存在值空(blank cell)仍查成 ──
    def test_fetch_forecast_missing_metric_column_unchecked(self):
        class _Pro:                                    # 有 PIT+type 但缺 p_change_max 列 → None(无法跑 p_change 红旗)
            def forecast(self, **kw):
                return pd.DataFrame({"ts_code": ["600000.SH"], "ann_date": ["20260415"], "end_date": ["20260331"], "type": ["预减"]})
        self.assertIsNone(_fetch_forecast(_Pro(), "600000.SH"))

    def test_fetch_forecast_blank_cells_checked(self):
        class _Pro:                                    # 列全在、值空(blank cell)→ 返回行(查成),红旗经 type 判
            def forecast(self, **kw):
                return pd.DataFrame({"ts_code": ["600000.SH"], "ann_date": ["20260415"], "end_date": ["20260331"],
                                     "type": ["预减"], "p_change_min": [None], "p_change_max": [None]})
        recs = _fetch_forecast(_Pro(), "600000.SH")
        self.assertEqual(len(recs), 1)
        self.assertIsNone(recs[0]["p_change_max"])     # blank cell → None(合法,列在)

    def test_fetch_income_missing_metric_column_unchecked(self):
        class _Pro:                                    # 缺 total_revenue 等红旗输入列 → None
            def income(self, **kw):
                return pd.DataFrame({"ts_code": ["600000.SH"], "ann_date": ["20260415"], "end_date": ["20260331"]})
        self.assertIsNone(_fetch_income(_Pro(), "600000.SH"))

    def test_fetch_income_missing_profit_column_unchecked(self):
        class _Pro:                                    # 有营收/成本但缺利润列(n_income_attr_p/n_income 都无)→ None
            def income(self, **kw):
                return pd.DataFrame({"ts_code": ["600000.SH"], "ann_date": ["20260415"], "end_date": ["20260331"],
                                     "total_revenue": [1000.0], "revenue": [1000.0], "oper_cost": [600.0]})
        self.assertIsNone(_fetch_income(_Pro(), "600000.SH"))

    def test_fetch_income_blank_cells_checked(self):
        class _Pro:                                    # 列全在(含一个利润列)、值空 → 查成
            def income(self, **kw):
                return pd.DataFrame({"ts_code": ["600000.SH"], "ann_date": ["20260415"], "end_date": ["20260331"],
                                     "total_revenue": [None], "revenue": [None], "oper_cost": [None], "n_income": [None]})
        self.assertEqual(len(_fetch_income(_Pro(), "600000.SH")), 1)

    def test_fetch_balancesheet_missing_metric_column_unchecked(self):
        class _Pro:                                    # 缺 goodwill 等红旗输入列 → None
            def balancesheet(self, **kw):
                return pd.DataFrame({"ts_code": ["600000.SH"], "ann_date": ["20260415"], "end_date": ["20260331"],
                                     "total_assets": [1e4], "total_liab": [4e3], "accounts_receiv": [1e3], "inventories": [1e3]})
        self.assertIsNone(_fetch_balancesheet(_Pro(), "600000.SH"))

    def test_fetch_balancesheet_blank_cells_checked(self):
        class _Pro:                                    # 列全在、值空 → 查成
            def balancesheet(self, **kw):
                return pd.DataFrame({"ts_code": ["600000.SH"], "ann_date": ["20260415"], "end_date": ["20260331"],
                                     "total_assets": [None], "total_liab": [None], "accounts_receiv": [None],
                                     "inventories": [None], "goodwill": [None]})
        self.assertEqual(len(_fetch_balancesheet(_Pro(), "600000.SH")), 1)

    def test_builder_missing_metric_column_marks_unchecked(self):
        # 端到端:provider 缺 metric 列 → builder 标该(票,类)未查成 → 唯一(票,类)失败 → status unknown(绝不 checked 空 records 假「无红旗」)
        class _Pro:
            def income(self, **kw):
                return pd.DataFrame({"ts_code": ["600000.SH"], "ann_date": ["20260415"], "end_date": ["20260331"]})
        ft = _financial_trends([("600000.SH", "x")], AS_OF, income_provider=lambda c: _fetch_income(_Pro(), c))
        self.assertEqual(ft["status"], "unknown_or_unavailable")

    # ── 再审查 #5 PIT-FILTERED-COVERAGE:provider 非空但无 PIT-valid 评估基础 → unchecked(false-clean 防护);真空 [] 仍查成 ──
    def test_builder_income_future_only_unchecked(self):
        # provider 非空但全是未来报告期(end>as_of)→ realized 全过滤 → 无评估基础 → 未查成 → unknown(非 checked 空)
        prov = lambda c: [self._inc(ann="20260415", end="20260930", napt=-50.0, ni=-50.0)]
        ft = _financial_trends([("600000.SH", "x")], AS_OF, income_provider=prov)
        self.assertEqual(ft["status"], "unknown_or_unavailable")
        self.assertEqual(ft["records"], [])

    def test_builder_balancesheet_no_prior_unchecked(self):
        # provider 非空但只有 q0、无去年同期 q-4 → 全 YoY 无可比 → 无评估基础 → 未查成
        prov = lambda c: [self._bs(ann="20260415", end="20260331", liab=5000.0)]
        self.assertEqual(_financial_trends([("600000.SH", "x")], AS_OF, balancesheet_provider=prov)["status"],
                         "unknown_or_unavailable")

    def test_builder_true_empty_checked(self):
        # provider 真空 [] → 查成、真无数据(诚实 clean,非 unchecked)
        ft = _financial_trends([("600000.SH", "x")], AS_OF, income_provider=lambda c: [])
        self.assertEqual(ft["status"], "checked")
        self.assertEqual(ft["records"], [])
        self.assertNotIn("unchecked_codes", ft)

    def test_builder_income_q0_only_loss_still_checked(self):
        # income q0-only(无 q-4)有亏损 → q0 即可判亏损 → 有评估基础 → checked + record(亏损不需同期)
        prov = lambda c: [self._inc(ann="20260415", end="20260331", napt=-50.0, ni=-50.0)]
        ft = _financial_trends([("600000.SH", "x")], AS_OF, income_provider=prov)
        self.assertEqual(ft["status"], "checked")
        self.assertEqual(ft["records"][0]["statement_type"], "income")

    def test_builder_partial_pit_filtered_marks_unchecked(self):
        # 一票 PIT-valid red flag + 一票全未来期 → checked + 失败票进 unchecked_codes(per-key,非整体 unknown)
        prov = lambda c: ([self._inc(ann="20260415", end="20260331", napt=-50.0, ni=-50.0)] if c == "600000.SH"
                          else [self._inc(ann="20260415", end="20260930", napt=-50.0, ni=-50.0)])
        ft = _financial_trends([("600000.SH", "x"), ("000001.SZ", "y")], AS_OF, income_provider=prov)
        self.assertEqual(ft["status"], "checked")
        self.assertEqual([r["ts_code"] for r in ft["records"]], ["600000.SH"])
        self.assertEqual([u["ts_code"] for u in ft["unchecked_codes"]], ["000001.SZ"])

    # ── 再审查 #2 COVERAGE-KEY-CONSISTENCY:(ts_code,statement_type) 唯一键 / record↔unchecked 互斥 / unknown 不带 unchecked / unchecked candidate-only ──
    def test_validator_unknown_with_unchecked_rejected(self):
        w = self._weekly_ft(status="unknown_or_unavailable", records=[])
        w["financial_trends"]["unchecked_codes"] = [{"ts_code": "600000.SH", "name": "t", "statement_type": "forecast"}]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_duplicate_records_rejected(self):
        w = self._weekly_ft(records=[self._rec(), self._rec()])   # 同 (600000, forecast) 两次
        _attach_financial_trend_impacts(w, AS_OF)
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_duplicate_unchecked_rejected(self):
        w = self._weekly_ft(records=[])
        w["financial_trends"]["unchecked_codes"] = [{"ts_code": "600000.SH", "name": "t", "statement_type": "forecast"},
                                                    {"ts_code": "600000.SH", "name": "t", "statement_type": "forecast"}]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_record_and_unchecked_same_key_rejected(self):
        w = self._weekly_ft(records=[self._rec()])
        _attach_financial_trend_impacts(w, AS_OF)
        w["financial_trends"]["unchecked_codes"] = [{"ts_code": "600000.SH", "name": "t", "statement_type": "forecast"}]
        with self.assertRaises(ValueError):       # 同键既 record 又 unchecked
            validate_weekly_report(w, _feed())

    def test_validator_held_unchecked_rejected(self):
        # candidate-only:持仓(held)不得进 financial_trends.unchecked_codes(持仓财报趋势留后续刀,不泄漏 held scope)
        w = self._weekly_ft(status="checked", records=[])
        w["reports"][0].setdefault("machine", {})["stateful_risk"] = {"position_state": "held"}
        w["financial_trends"]["unchecked_codes"] = [{"ts_code": "600000.SH", "name": "t", "statement_type": "forecast"}]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    # ── 再审查 #3 REALIZED-PERIOD-PIT:income/balancesheet 已实现报表报告期不得 > as_of;forecast 业绩预告可指未来期(豁免)──
    def test_income_future_period_skipped(self):
        # end>as_of(20260609)→ 已实现未来报告期丢弃 → 唯一记录被丢 → None
        self.assertIsNone(_income_red_flags([self._inc(ann="20260415", end="20260930", napt=-50.0, ni=-50.0)], AS_OF))

    def test_balancesheet_future_period_skipped(self):
        self.assertIsNone(_balancesheet_red_flags([self._bs(ann="20260415", end="20260930", liab=9000.0)], AS_OF))

    def test_forecast_future_period_allowed(self):
        # forecast 业绩预告可指未来报告期(realized=False 豁免);ann_date<=as_of + 预减 → 仍红旗
        res = _forecast_red_flags([self._fc(ann="20260415", end="20260930", ftype="预减")], AS_OF)
        self.assertIsNotNone(res)
        self.assertEqual(res[2], "20260930")

    def test_validator_income_future_period_rejected(self):
        w = self._weekly_ft(records=[self._rec(stype="income", period="20260930", flags=["归母净利润为负(亏损)"], summary="亏损")])
        _attach_financial_trend_impacts(w, AS_OF)     # 落地满足 forward;唯一失败=realized-period PIT
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    # ── 再审查 #4 INDUSTRY-FUNDAMENTALS-SUMMARY-ONLY-ROLLUP:必产 rollup / dup-codes / 禁逐票 impact ──
    def test_validator_missing_industry_rollup_rejected(self):
        # income/bs 红旗记录存在但缺 industry_fundamentals → 拒(⑤ summary-only 必产行业上下文)
        w = _weekly()
        w["financial_trends"] = {"as_of": AS_OF, "status": "checked", "records": [self._ft_bf("600000.SH", "income")]}
        _attach_financial_trend_impacts(w, AS_OF)
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_duplicate_industry_code_rejected(self):
        w = self._weekly_indf(by_industry=[{"sw_l2_name": "半导体", "candidate_count": 1, "red_flag_candidate_count": 1,
                                            "red_flag_codes": ["600000.SH", "600000.SH"], "summary": "x"}])
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_guard_rejects_industry_fundamentals_row_impact(self):
        # ⑰:⑤ summary_only,绝不产逐票 operation_impact(防把行业摘要伪装成 row impact)
        rep = self._attached_report()
        rep["machine"]["operation_impact"].append({
            "source_field": "industry_fundamentals", "field_class": "structured",
            "visibility_shape": "candidate_row_impact", "impact_scope": "new_entry", "new_entry_effect": "informational",
            "holding_effect": "none", "blocked_add_required": False, "veto_class": "none", "reason": "x",
            "evidence_ref": {"kind": "lineage_key", "value": "industry_fundamentals", "as_of": AS_OF}, "confidence": "high",
            "pit_basis": "disclosure_date", "production_effect_enabled": False, "implementation_status": "implemented",
            "m67_landing_surface": "x", "terminal_surface_target": "already_structured", "pending_successor_slice": None,
            "privacy_class": "public_tracked"})
        with self.assertRaises(ValueError):
            _vop(rep)

    # ── builder(unknown-not-clear / PIT / candidate-only)──
    def test_builder_provider_none_unknown(self):
        ft = _financial_trends([("600000.SH", "x")], AS_OF)
        self.assertEqual(ft["status"], "unknown_or_unavailable")     # 全 provider None → unknown(绝不当无红旗)
        self.assertEqual(ft["records"], [])

    def test_builder_all_fetch_fail_unknown(self):
        self.assertEqual(_financial_trends([("600000.SH", "x")], AS_OF, forecast_provider=lambda c: None)["status"],
                         "unknown_or_unavailable")
        def _boom(c):
            raise RuntimeError("x")
        self.assertEqual(_financial_trends([("600000.SH", "x")], AS_OF, forecast_provider=_boom)["status"],
                         "unknown_or_unavailable")

    def test_builder_partial_fail_marks_unchecked(self):
        prov = lambda c: ([self._fc(ftype="预减")] if c == "600000.SH" else None)
        ft = _financial_trends([("600000.SH", "x"), ("000001.SZ", "y")], AS_OF, forecast_provider=prov)
        self.assertEqual(ft["status"], "checked")
        self.assertEqual([r["ts_code"] for r in ft["records"]], ["600000.SH"])
        self.assertEqual([u["ts_code"] for u in ft["unchecked_codes"]], ["000001.SZ"])   # 失败票显式列出,不静默当无

    def test_builder_checked_no_redflag_no_record(self):
        # 查成但无红旗 → checked + 空 records(不噪声;coverage 由 status 体现,镜像①)
        ft = _financial_trends([("600000.SH", "x")], AS_OF, forecast_provider=lambda c: [self._fc(ftype="预增", pmin=10, pmax=30)])
        self.assertEqual(ft["status"], "checked")
        self.assertEqual(ft["records"], [])

    def test_builder_emits_record(self):
        ft = _financial_trends([("600000.SH", "x")], AS_OF, forecast_provider=lambda c: [self._fc(ftype="预减", pmax=-10)])
        self.assertEqual(ft["status"], "checked")
        r = ft["records"][0]
        self.assertEqual((r["ts_code"], r["statement_type"], r["period"], r["observed_at"]),
                         ("600000.SH", "forecast", "20260331", "20260415"))
        self.assertTrue(r["red_flags"] and r["summary"])

    def test_builder_held_excluded(self):
        ft = _financial_trends([("600000.SH", "x")], AS_OF, forecast_provider=lambda c: [self._fc(ftype="预减")],
                               held_codes={"600000.SH"})
        self.assertEqual(ft["records"], [])             # 持仓排除(candidate-only,持仓财报趋势留后续刀)

    # ── attach + schema + validator(双向 no-dangling · PIT · 张冠李戴)──
    def test_attach_lands_impact_and_text(self):
        w = self._weekly_ft(records=[self._rec()])
        _attach_financial_trend_impacts(w, AS_OF)
        rep = w["reports"][0]
        imps = [i for i in rep["machine"]["operation_impact"] if i["source_field"] == "financial_trend_forecast"]
        self.assertEqual(len(imps), 1)
        self.assertEqual((imps[0]["new_entry_effect"], imps[0]["veto_class"], imps[0]["production_effect_enabled"]),
                         ("priority_down", "none", False))
        self.assertEqual((imps[0]["visibility_shape"], imps[0]["impact_scope"], imps[0]["privacy_class"]),
                         ("candidate_row_impact", "new_entry", "public_tracked"))
        self.assertIn(_FIN_STATEMENT_MARKER, rep["m67"]["精简结论区"]["风控触发"])   # no-dangling 真落地
        jsonschema.validate(w, json.load(open(SCHEMA_PATH, encoding="utf-8")))
        validate_weekly_report(w, _feed())             # 含 per-report 引擎 guard ⑯

    def test_absent_is_valid(self):
        w = _weekly()                                  # 无 financial_trends → 向后兼容
        jsonschema.validate(w, json.load(open(SCHEMA_PATH, encoding="utf-8")))
        validate_weekly_report(w, _feed())

    def test_validator_unknown_with_records_rejected(self):
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_ft(status="unknown_or_unavailable", records=[self._rec()]), _feed())

    def test_validator_foreign_ts_rejected(self):
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_ft(records=[self._rec(ts="600999.SH")]), _feed())

    def test_validator_observed_after_as_of_rejected(self):
        with self.assertRaises(ValueError):       # observed_at > as_of(PIT/look-ahead)
            validate_weekly_report(self._weekly_ft(records=[self._rec(observed_at="20260701")]), _feed())

    def test_validator_record_without_landing_rejected(self):
        # checked record 但未 attach(无逐票 impact)→ forward no-dangling 拒
        with self.assertRaises(ValueError):
            validate_weekly_report(self._weekly_ft(records=[self._rec()]), _feed())

    def test_validator_impact_without_record_rejected(self):
        # 反向 evidence guard:report 有 financial_trend_ impact 但 section 无匹配 record → 拒
        w = self._weekly_ft(records=[self._rec()])
        _attach_financial_trend_impacts(w, AS_OF)
        w["financial_trends"]["records"] = []
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    def test_validator_unchecked_foreign_ts_rejected(self):
        w = self._weekly_ft(records=[self._rec()])
        _attach_financial_trend_impacts(w, AS_OF)
        w["financial_trends"]["unchecked_codes"] = [{"ts_code": "000999.SZ", "name": "外", "statement_type": "forecast"}]
        with self.assertRaises(ValueError):
            validate_weekly_report(w, _feed())

    # ── engine guard ⑯(comparison-only + candidate-only isolation)──
    def _attached_report(self):
        w = self._weekly_ft(records=[self._rec()])
        _attach_financial_trend_impacts(w, AS_OF)
        return w["reports"][0]

    def _ftimp(self, rep):
        return [i for i in rep["machine"]["operation_impact"] if i["source_field"] == "financial_trend_forecast"][0]

    def test_guard_accepts_normal(self):
        _vop(self._attached_report())                  # 正常候选红旗 → 过

    def test_guard_rejects_hard_veto(self):
        rep = self._attached_report()
        self._ftimp(rep)["new_entry_effect"] = "hard_veto"   # veto_class 保持 none → 专测 ⑯ never-hard-veto
        with self.assertRaises(ValueError):
            _vop(rep)

    def test_guard_rejects_production_enabled(self):
        rep = self._attached_report()
        self._ftimp(rep)["production_effect_enabled"] = True
        with self.assertRaises(ValueError):
            _vop(rep)

    def test_guard_rejects_missing_marker(self):
        rep = self._attached_report()
        rep["m67"]["精简结论区"]["风控触发"] = "无"        # 抹掉 marker
        with self.assertRaises(ValueError):
            _vop(rep)

    def test_guard_rejects_holding_shape(self):
        rep = self._attached_report()
        self._ftimp(rep)["visibility_shape"] = "holding_row_impact"
        with self.assertRaises(ValueError):
            _vop(rep)

    def test_guard_rejects_held_report(self):
        # 持仓(held)报告带 financial_trend impact → guard 拒(candidate-only,持仓财报趋势留后续刀)
        rep = self._attached_report()
        rep["machine"]["stateful_risk"] = {"position_state": "held"}
        with self.assertRaises(ValueError):
            _vop(rep)

    # ── render ──
    def test_render_lists_redflag(self):
        w = self._weekly_ft(records=[self._rec()])
        _attach_financial_trend_impacts(w, AS_OF)
        md = render_weekly_markdown(w)
        self.assertIn("财报质量趋势", md)
        self.assertIn("业绩预告", md)

    def test_render_unknown_caveat(self):
        md = render_weekly_markdown(self._weekly_ft(status="unknown_or_unavailable"))
        self.assertIn("未取到财报报表", md)

    # ── main 接线(注入 forecast_provider;无 --account → 候选全 eligible)──
    def test_main_wires_forecast_provider(self):
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
            (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
            (Path(td) / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
            out = Path(td) / "weekly.json"
            fprov = lambda c: ([self._fc(ftype="预减", pmax=-10)] if c == "600000.SH" else [])
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--out", str(out)],
                 price_provider=lambda code: _series(), forecast_provider=fprov, dragon_list_days=_DL_WINDOW)
            loaded = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(loaded["financial_trends"]["status"], "checked")
        recs = [r for r in loaded["financial_trends"]["records"] if r["ts_code"] == "600000.SH"]
        self.assertEqual(len(recs), 1)
        rep = [r for r in loaded["reports"] if r["ts_code"] == "600000.SH"][0]
        self.assertTrue(any(i["source_field"] == "financial_trend_forecast" for i in rep["machine"]["operation_impact"]))

    def test_main_wires_income_provider(self):
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
            (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
            (Path(td) / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
            out = Path(td) / "weekly.json"
            iprov = lambda c: ([{"ann_date": "20260415", "end_date": "20260331", "total_revenue": 800.0,
                                 "revenue": 800.0, "oper_cost": 700.0, "n_income": -50.0, "n_income_attr_p": -50.0}]
                               if c == "600000.SH" else [])
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--out", str(out)],
                 price_provider=lambda code: _series(), income_provider=iprov, dragon_list_days=_DL_WINDOW)
            loaded = json.loads(out.read_text(encoding="utf-8"))
        recs = [r for r in loaded["financial_trends"]["records"] if r["statement_type"] == "income"]
        self.assertEqual(len(recs), 1)
        rep = [r for r in loaded["reports"] if r["ts_code"] == "600000.SH"][0]
        self.assertTrue(any(i["source_field"] == "financial_trend_income" for i in rep["machine"]["operation_impact"]))

    def test_main_wires_balancesheet_provider(self):
        with tempfile.TemporaryDirectory() as td:
            ai = _analysis_input(candidates=[_ai_candidate("600000.SH"), _ai_candidate("000001.SZ")])
            (Path(td) / "ai.json").write_text(json.dumps(ai), encoding="utf-8")
            (Path(td) / "feed.json").write_text(json.dumps(_feed()), encoding="utf-8")
            out = Path(td) / "weekly.json"
            bs = lambda ta, liab, end, ann: {"ann_date": ann, "end_date": end, "total_assets": ta, "total_liab": liab,
                                             "accounts_receiv": 1000.0, "inventories": 1000.0, "goodwill": 0.0}
            bprov = lambda c: ([bs(10000.0, 5000.0, "20260331", "20260415"), bs(10000.0, 4000.0, "20250331", "20250415")]
                               if c == "600000.SH" else [])
            main(["--as-of", AS_OF, "--analysis-input", str(Path(td) / "ai.json"),
                  "--iv-feed", str(Path(td) / "feed.json"), "--out", str(out)],
                 price_provider=lambda code: _series(), balancesheet_provider=bprov, dragon_list_days=_DL_WINDOW)
            loaded = json.loads(out.read_text(encoding="utf-8"))
        recs = [r for r in loaded["financial_trends"]["records"] if r["statement_type"] == "balancesheet"]
        self.assertEqual(len(recs), 1)
        rep = [r for r in loaded["reports"] if r["ts_code"] == "600000.SH"][0]
        self.assertTrue(any(i["source_field"] == "financial_trend_balancesheet" for i in rep["machine"]["operation_impact"]))


class S3bHoldingDispositionPipelineTests(unittest.TestCase):
    """S3b R1+R2: pipeline _attach_holding_disposition 在 attach 后对持仓行重算(纳入 forward_event held 晚到信号)+ render 持仓处置列。"""

    def _held_rep(self, signal="hold_watch", blocked=True, row_source="account_position_only"):
        return {"ts_code": "600000.SH", "name": "测试", "row_source": row_source, "coverage_status": "partial",
                "m67": {"精简结论区": {k: "" for k in ("当前环境", "波动率状态", "现价与成本", "否决审查触发",
                                                       "板块资金事件", "风控触发", "操作建议")},
                        "table": {"操作": "持有", "股数": None, "入": None, "盈一": None, "盈二": None, "损": None,
                                  "类型": "已有持仓", "EGS分": None, "优先级": "—", "触发条件": ""}},
                "machine": {"stateful_risk": {"position_state": "held"},
                            "operation_impact": [{"source_field": "forward_event_limit_unlock", "holding_effect": signal,
                                                  "blocked_add_required": blocked, "visibility_shape": "holding_row_impact",
                                                  "impact_scope": "existing_holding", "privacy_class": "private_account"}]}}

    def test_attach_folds_forward_event_held(self):
        # build 后 attach 追加的 forward_event held 信号 → _attach_holding_disposition 重算纳入
        w = {"reports": [self._held_rep("hold_watch", True)]}
        _attach_holding_disposition(w)
        t = w["reports"][0]["m67"]["table"]
        self.assertEqual(t["持仓处置"], "持有警戒")
        self.assertTrue(t["禁止加仓"])
        self.assertEqual(w["reports"][0]["machine"]["holding_management_signal"], "hold_watch")

    def test_attach_noop_on_candidate(self):
        rep = self._held_rep()
        rep["m67"]["table"]["操作"] = "建仓"      # 非持有 → no-op
        rep["machine"]["stateful_risk"] = {}
        _attach_holding_disposition({"reports": [rep]})
        self.assertNotIn("持仓处置", rep["m67"]["table"])

    def test_render_shows_disposition(self):
        rep = self._held_rep("clear_review", True)
        _attach_holding_disposition({"reports": [rep]})
        md = render_weekly_markdown({"as_of": AS_OF, "reports": [rep], "run_lineage": {}})
        self.assertIn("持仓处置", md)
        self.assertIn("建议清仓复核", md)


class NormalizeContractParityTests(unittest.TestCase):
    """normalize_candidate ↔ analysis_input 契约 parity(堵"未来键改名静默 suppress veto"这一最坏失败模式):
    用 canonical analysis_input fixture(= EGS 导出契约形状)构造"全危险"候选,过 analysis_input schema 校验后跑
    normalize_candidate,断言引擎侧每个硬风险旗标都真映射;若 normalize 读取键与契约漂移,这些断言会失败。"""

    def _payload(self):
        from tests.support.analysis_input_payload import cloned_minimal_analysis_input_payload
        return cloned_minimal_analysis_input_payload()

    def test_dangerous_flags_map_through_not_silently_dropped(self) -> None:
        payload = self._payload()
        cand = payload["candidates"][0]
        cand["derived_flags"].update({
            "overheat_flag": True, "chasing_high": True, "is_breakout": True,
            "vol_confirm": True, "has_crash_veto": True, "is_lock": True, "hard_veto": True,
        })
        cand["event_risk"]["holder_reduction"]["active_plan"] = True
        cand["event_risk"]["suspension"]["is_suspended"] = True
        cand["event_risk"]["delisting"]["st_flag"] = True
        cand["liquidity"]["avg_amount_5d"] = 1.0e8
        schema = json.loads((ROOT / "schemas" / "analysis_input.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(payload, schema)   # "全危险"候选仍是合法契约(否则下面映射断言无意义)
        norm = normalize_candidate(cand, [], {}, 55.0, {}, "震荡期")
        for key in ("hard_veto", "crash_veto", "limit_locked", "suspended", "overheat", "chasing_high"):
            self.assertTrue(norm["derived"][key], f"derived.{key} 未从契约映射(疑似键漂移静默 suppress veto)")
        self.assertTrue(norm["event"]["holder_reduction_active"])
        self.assertTrue(norm["event"]["st_or_delisting"])
        self.assertEqual(norm["liquidity"]["avg_amount_5d"], 1.0e8)

    def test_clean_candidate_maps_to_false_not_constant_true(self) -> None:
        # 反向:干净候选 → 引擎侧 False(证明上面的 True 不是恒真映射)
        cand = self._payload()["candidates"][0]
        norm = normalize_candidate(cand, [], {}, 55.0, {}, "震荡期")
        self.assertFalse(norm["derived"]["hard_veto"])
        self.assertFalse(norm["derived"]["crash_veto"])
        self.assertFalse(norm["event"]["st_or_delisting"])
        self.assertFalse(norm["event"]["holder_reduction_active"])


class PipelineCanonicalDateStrictnessTests(unittest.TestCase):
    """P1(defect-class,与 engine 同口径):pipeline _is_valid_date 严格 canonical(account/事件日期等契约门)。"""

    def test_pipeline_is_valid_date_strict(self):
        from runners.a_short_weekly_pipeline import _is_valid_date as pv
        self.assertTrue(pv("20260605"))
        for bad in ("202606 5", "2026065", "20260631", "2026060a", ""):
            self.assertFalse(pv(bad), f"应拒非 canonical {bad!r}")


class AccountMainBoardAndOutputPrivacyTests(unittest.TestCase):
    """P1(Codex Slice4):validate_account_state 强制主板;P0(Slice2/4):账户输出守门须同守 .md sibling(非只 .json)。"""

    def _acct(self):
        return json.loads((ROOT / "schemas" / "examples" / "a_short_account_state.example.json").read_text(encoding="utf-8"))

    def test_validate_account_state_rejects_b_share_position(self):
        a = self._acct()
        a["positions"][0]["ts_code"] = "200001.SZ"
        with self.assertRaises(SystemExit):
            validate_account_state(a, a["as_of"])

    def test_main_board_position_still_passes(self):
        a = self._acct()
        validate_account_state(a, a["as_of"])   # 主板不破

    def test_md_sibling_guarded_not_only_json(self):
        from runners.a_short_weekly_pipeline import _reject_nonprivate_account_output_path as g
        repo = str(ROOT)
        g(f"{repo}/state/a_short/__probe__.json", True, False)        # .json 被 state/*/*.json 忽略 → 放行(JSON-only 守的盲点)
        with self.assertRaises(SystemExit):
            g(f"{repo}/state/a_short/__probe__.md", True, False)      # .md 不被同规则忽略 → 必须拒(P0 根因)
        g(f"{repo}/state/a_short/weekly_private/20260615/__probe__.md", True, False)  # weekly_private 下 → 放行


class FactorComparisonRealizedRegimeTests(unittest.TestCase):
    def test_private_csi300_context_is_pit_bound_and_provider_failure_is_nonblocking(self):
        dates = pd.bdate_range("2026-01-02", periods=21)

        class Pro:
            def __init__(self):
                self.calls = []

            def index_daily(self, **kwargs):
                self.calls.append(kwargs)
                rows = [
                    {"trade_date": value.strftime("%Y%m%d"), "close": 100.0 * (1.003 ** index)}
                    for index, value in enumerate(dates)
                ]
                return pd.DataFrame(list(reversed(rows)))

        pro = Pro()
        state = _factor_comparison_realized_regime(pro, "20260202", "20260130")
        self.assertEqual(state["status"], "available")
        self.assertEqual(state["label"], "trend_up_vol_low")
        self.assertEqual(pro.calls[0]["ts_code"], "000300.SH")
        self.assertEqual(_factor_comparison_realized_regime(None, "20260202", "20260130")["status"], "unavailable")


class LoadPublishedBundleTests(unittest.TestCase):
    """刀2: the official reader accepts a bundle only through its matching complete receipt."""

    def _bundle(self, root, *, dir_name="20260622", stage_status="complete", tamper=None):
        d = Path(root) / dir_name
        d.mkdir(parents=True, exist_ok=True)
        weekly = {"as_of": "20260622", "decision_as_of": "20260622", "run_date": "20260622",
                  "price_data_through": "20260622",
                  "run_lineage": {"run_id": "a-short-20260622-01", "candidate_digest": "b" * 64,
                                   "decision_as_of": "20260622", "price_data_through": "20260622"}}
        receipt = {"schema_name": "a_short_weekly_publish_receipt", "as_of": "20260622",
                   "decision_as_of": "20260622", "run_date": "20260622", "price_data_through": "20260622",
                   "run_id": "a-short-20260622-01", "candidate_digest": "b" * 64,
                   "stage_status": stage_status, "outputs": ["weekly_m67.json", "weekly_m67.md"]}
        if tamper:
            tamper(weekly, receipt)
        (d / "weekly_m67.json").write_text(json.dumps(weekly), encoding="utf-8")
        (d / "weekly_m67.md").write_text("# report", encoding="utf-8")
        (d / "weekly_m67.receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        return str(d / "weekly_m67.json")

    def test_complete_receipt_accepts(self):
        from runners.a_short_weekly_pipeline import load_published_weekly_bundle
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_published_weekly_bundle(self._bundle(tmp))["as_of"], "20260622")

    def test_failed_receipt_rejects(self):
        from runners.a_short_weekly_pipeline import load_published_weekly_bundle
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_published_weekly_bundle(self._bundle(tmp, stage_status="failed"))

    def test_identity_mismatch_rejects(self):
        from runners.a_short_weekly_pipeline import load_published_weekly_bundle
        with tempfile.TemporaryDirectory() as tmp:
            out = self._bundle(tmp, tamper=lambda w, r: r.__setitem__("run_id", "wrong-id"))
            with self.assertRaises(ValueError):
                load_published_weekly_bundle(out)

    def test_directory_asof_mismatch_rejects(self):
        from runners.a_short_weekly_pipeline import load_published_weekly_bundle
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_published_weekly_bundle(self._bundle(tmp, dir_name="20260101"))


if __name__ == "__main__":
    unittest.main()
