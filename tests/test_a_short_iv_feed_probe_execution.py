"""Tests for the A-short IV feed probe EXECUTION wiring (filter / run_probe / write path / main guards).

No live Tushare: fetch is not exercised here. The sanctioned write path
`write_probe_summary` MUST validate (schema + consistency) before writing — this closes the
register forward-item (consumers/writers cannot bypass validation). Synthetic fixtures only.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import contextlib  # noqa: E402
import io  # noqa: E402
import types  # noqa: E402

from runners.a_short_iv_feed_probe import (  # noqa: E402
    filter_50etf_options, run_probe, write_probe_summary, build_probe_summary,
    assess_opt_coverage, main, UNDERLYING, init_tushare_pro, fetch_probe_inputs, _safe_pro_call,
    _categorize_error, build_fetch_failure_summary, write_fetch_failure_summary,
)


class _FakePro:
    """behaviors: method-name -> DataFrame | Exception | callable(**kw)->DataFrame."""
    def __init__(self, behaviors):
        self._b = behaviors

    def __getattr__(self, name):
        def call(**kw):
            b = self._b.get(name, pd.DataFrame())
            if isinstance(b, Exception):
                raise b
            if callable(b) and not isinstance(b, pd.DataFrame):
                return b(**kw)
            return b
        return call


def _good_pro_behaviors():
    codes = [f"100000{i:02d}.SH" for i in range(40)]
    return {
        "opt_basic": _basic(),
        "trade_cal": pd.DataFrame({"cal_date": PIT_DATES}),
        "opt_daily": lambda **kw: pd.DataFrame(
            [{"ts_code": c, "trade_date": kw["trade_date"], "settle": 0.1, "close": 0.1, "vol": 100, "oi": 500}
             for c in codes]),
        "fund_daily": _underlier(),
    }

AS_OF = "20260630"
PIT_DATES = [f"202606{d + 1:02d}" for d in range(20)]


def _basic(n=40, label="50ETF", code_prefix="100000"):
    rows = []
    for i in range(n):
        rows.append({"ts_code": f"{code_prefix}{i:02d}.SH",
                     "name": f"{label}购6月{2000 + i}",
                     "call_put": "C" if i % 2 == 0 else "P",
                     "exercise_price": 2.0 + (i % 10) * 0.1,
                     "maturity_date": "20260725" if i < n // 2 else "20260822"})
    return pd.DataFrame(rows)


def _daily(codes, dates=PIT_DATES):
    rows = []
    for td in dates:
        for c in codes:
            rows.append({"ts_code": c, "trade_date": td, "settle": 0.1, "close": 0.1, "vol": 100, "oi": 500})
    return pd.DataFrame(rows)


def _underlier(dates=PIT_DATES, ts=UNDERLYING):
    return pd.DataFrame([{"ts_code": ts, "trade_date": td, "close": 2.5} for td in dates])


class FilterTests(unittest.TestCase):
    def test_filter_keeps_only_50etf(self):
        mixed = pd.concat([_basic(4, label="50ETF"), _basic(4, label="300ETF", code_prefix="200000")],
                          ignore_index=True)
        out = filter_50etf_options(mixed)
        self.assertTrue((out["name"].str.contains("50ETF")).all())
        self.assertEqual(len(out), 4)

    def test_no_name_column_returns_empty(self):
        self.assertTrue(filter_50etf_options(_basic().drop(columns=["name"])).empty)


class RunProbeTests(unittest.TestCase):
    def test_good_inputs_computable(self):
        basic = _basic()
        s = run_probe(basic, _daily(list(basic["ts_code"])), _underlier(), AS_OF, "t")
        self.assertTrue(s["computable"], s["assessment"]["reasons"])

    def test_non_50etf_daily_noise_filtered_out(self):
        basic = _basic()  # 50ETF codes 1000xx
        # opt_daily mixes our 50ETF codes + 300ETF codes; run_probe must keep only the 50ETF ones
        daily = pd.concat([_daily(list(basic["ts_code"])), _daily(["20000099.SH"])], ignore_index=True)
        s = run_probe(basic, daily, _underlier(), AS_OF, "t")
        self.assertTrue(s["computable"], s["assessment"]["reasons"])

    def test_no_50etf_in_basic_not_computable(self):
        basic = _basic(label="300ETF", code_prefix="200000")  # no 50ETF
        s = run_probe(basic, _daily(list(basic["ts_code"])), _underlier(), AS_OF, "t")
        self.assertFalse(s["computable"])


class WritePathTests(unittest.TestCase):
    def setUp(self):
        basic = _basic()
        self.good = run_probe(basic, _daily(list(basic["ts_code"])), _underlier(), AS_OF, "t")

    def test_writes_valid_summary(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "probe.json"
            write_probe_summary(self.good, str(out))
            self.assertTrue(out.exists())
            reloaded = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(reloaded["computable"])

    def test_refuses_to_write_cross_field_inconsistent_summary(self):
        # register forward-item cure: schema PASSES latest_usable_date="29991231" but the write path
        # runs validate_probe_summary_consistency, which rejects (latest_usable_date > as_of).
        bad = copy.deepcopy(self.good)
        bad["assessment"]["latest_usable_date"] = "29991231"
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "probe.json"
            with self.assertRaises(Exception):
                write_probe_summary(bad, str(out))
            self.assertFalse(out.exists())


class TushareInitTests(unittest.TestCase):
    def test_init_does_not_call_set_token_and_pins_endpoint(self):
        # R-AIV-PROBE-EXEC-TUSHARE-INIT-SIDE-EFFECT: must not write tk.csv via set_token; must pin url.
        calls = {"set_token": 0}

        class _FakeDataApi:
            pass
        setattr(_FakeDataApi, "_DataApi__http_url", "OLD")
        fake_ts = types.SimpleNamespace(
            __version__="1.4.29",
            pro=types.SimpleNamespace(client=types.SimpleNamespace(DataApi=_FakeDataApi)),
            set_token=lambda t: calls.__setitem__("set_token", calls["set_token"] + 1),
            pro_api=lambda token: ("PRO", token),
        )
        pro = init_tushare_pro("tok123", ts_module=fake_ts)
        self.assertEqual(pro, ("PRO", "tok123"))
        self.assertEqual(calls["set_token"], 0)                       # never wrote token cache
        self.assertNotEqual(getattr(_FakeDataApi, "_DataApi__http_url"), "OLD")  # endpoint pinned

    def test_pin_failure_missing_dataapi_is_hard_error(self):
        fake_ts = types.SimpleNamespace(__version__="1.4.29", pro=types.SimpleNamespace(),  # no .client.DataApi
                                        pro_api=lambda token: ("PRO", token))
        with self.assertRaises(RuntimeError):
            init_tushare_pro("tok", ts_module=fake_ts)

    def test_pin_failure_missing_attr_is_hard_error(self):
        class _NoAttrDataApi:  # lacks _DataApi__http_url
            pass
        fake_ts = types.SimpleNamespace(
            __version__="1.4.29",
            pro=types.SimpleNamespace(client=types.SimpleNamespace(DataApi=_NoAttrDataApi)),
            pro_api=lambda token: ("PRO", token))
        with self.assertRaises(RuntimeError):
            init_tushare_pro("tok", ts_module=fake_ts)


class FetchLineageTests(unittest.TestCase):
    def test_all_ok_no_provider_error(self):
        _, _, _, report = fetch_probe_inputs(_FakePro(_good_pro_behaviors()), AS_OF)
        self.assertFalse(report["had_provider_error"])
        self.assertEqual(report["opt_basic_rows"], 40)
        self.assertEqual(report["underlier_rows"], 20)
        self.assertEqual(report["underlier_trade_dates"], PIT_DATES)

    def test_independent_underlier_dates_are_pit_filtered(self):
        behaviors = _good_pro_behaviors()
        behaviors["fund_daily"] = _underlier([*PIT_DATES, "20260701", "bad-date"])
        _, _, _, report = fetch_probe_inputs(_FakePro(behaviors), AS_OF)
        self.assertEqual(report["underlier_trade_dates"], PIT_DATES)

    def test_max_trade_dates_param_widens_window(self):
        b = _good_pro_behaviors()
        b["trade_cal"] = pd.DataFrame({"cal_date": [f"2026{m:02d}{d:02d}"
                                                    for m in (1, 2, 3) for d in range(1, 29)]})  # 84 dates
        _, _, _, rep = fetch_probe_inputs(_FakePro(b), "20260331", lookback_days=200, max_trade_dates=300)
        self.assertGreater(rep["trade_dates_probed"], 25)   # build path widens beyond probe's default 25

    def test_provider_exception_flagged_with_sanitized_status(self):
        b = _good_pro_behaviors()
        b["opt_basic"] = PermissionError("permission denied: tk.csv")
        _, _, _, report = fetch_probe_inputs(_FakePro(b), AS_OF)
        self.assertTrue(report["had_provider_error"])
        bad = [s for s in report["endpoint_statuses"] if s["endpoint"] == "opt_basic"][0]
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error_class"], "PermissionError")
        self.assertEqual(bad["error_category"], "permission_or_quota")

    def test_opt_daily_transient_failure_retries_and_recovers(self):
        calls = {"count": 0}
        pauses = []
        behaviors = _good_pro_behaviors()
        original = behaviors["opt_daily"]

        def flaky_opt_daily(**kw):
            if kw["trade_date"] == PIT_DATES[0] and calls["count"] == 0:
                calls["count"] += 1
                raise TimeoutError("transient timeout")
            calls["count"] += 1
            return original(**kw)

        behaviors["opt_daily"] = flaky_opt_daily
        _, _, _, report = fetch_probe_inputs(
            _FakePro(behaviors), AS_OF, sleep_fn=pauses.append,
        )

        self.assertFalse(report["had_provider_error"])
        self.assertFalse(report["opt_daily_fail_fast_triggered"])
        self.assertEqual(report["trade_dates_probed"], report["trade_dates_planned"])
        self.assertEqual(report["retry_recoveries"], [{
            "endpoint": "opt_daily", "trade_date": PIT_DATES[0], "attempt_count": 2,
        }])
        self.assertEqual(pauses, [0.25])

    def test_opt_daily_error_phrase_variants_retry_before_fail_fast(self):
        variants = (
            ("Read timed out", "network"),
            ("504 Gateway Time-out", "provider_server"),
            ("Server returned 504", "provider_server"),
        )
        for message, expected_category in variants:
            with self.subTest(message=message):
                calls = {"count": 0}
                pauses = []
                behaviors = _good_pro_behaviors()
                original = behaviors["opt_daily"]

                def flaky_opt_daily(**kw):
                    if kw["trade_date"] == PIT_DATES[0] and calls["count"] == 0:
                        calls["count"] += 1
                        raise RuntimeError(message)
                    calls["count"] += 1
                    return original(**kw)

                self.assertEqual(_categorize_error(RuntimeError(message)), expected_category)
                _, _, _, report = fetch_probe_inputs(
                    _FakePro({**behaviors, "opt_daily": flaky_opt_daily}), AS_OF,
                    sleep_fn=pauses.append,
                )

                self.assertFalse(report["had_provider_error"])
                self.assertEqual(report["retry_recoveries"], [{
                    "endpoint": "opt_daily", "trade_date": PIT_DATES[0], "attempt_count": 2,
                }])
                self.assertEqual(pauses, [0.25])

    def test_403_forbidden_is_permission_and_does_not_retry(self):
        calls = {"count": 0}
        pauses = []

        def forbidden_opt_daily(**_kw):
            calls["count"] += 1
            raise RuntimeError("403 forbidden")

        self.assertEqual(_categorize_error(RuntimeError("403 forbidden")), "permission_or_quota")
        behaviors = _good_pro_behaviors()
        _, _, _, report = fetch_probe_inputs(
            _FakePro({**behaviors, "opt_daily": forbidden_opt_daily}), AS_OF,
            sleep_fn=pauses.append,
        )

        failure = [s for s in report["endpoint_statuses"] if s["endpoint"] == "opt_daily"][0]
        self.assertTrue(report["had_provider_error"])
        self.assertEqual(failure["error_category"], "permission_or_quota")
        self.assertEqual(failure["attempt_count"], 1)
        self.assertEqual(calls["count"], 1)
        self.assertEqual(pauses, [])

    def test_opt_daily_terminal_failure_does_not_retry(self):
        calls = {"count": 0}
        pauses = []

        def denied_opt_daily(**_kw):
            calls["count"] += 1
            raise PermissionError("permission denied")

        behaviors = _good_pro_behaviors()
        behaviors["opt_daily"] = denied_opt_daily
        _, _, _, report = fetch_probe_inputs(
            _FakePro(behaviors), AS_OF, sleep_fn=pauses.append,
        )

        self.assertTrue(report["had_provider_error"])
        self.assertTrue(report["opt_daily_fail_fast_triggered"])
        self.assertEqual(report["trade_dates_probed"], 1)
        failure = [s for s in report["endpoint_statuses"] if s["endpoint"] == "opt_daily"][0]
        self.assertEqual(failure["error_category"], "permission_or_quota")
        self.assertEqual(failure["attempt_count"], 1)
        self.assertEqual(failure["retry_count"], 0)
        self.assertEqual(calls["count"], 1)
        self.assertEqual(pauses, [])

    def test_persistent_opt_daily_failure_fails_fast_and_writes_sanitized_receipt(self):
        behaviors = _good_pro_behaviors()
        behaviors["opt_daily"] = RuntimeError(
            "connection timeout url=https://api.example.invalid/?token=SECRET123 raw_rows=[1]"
        )
        _, _, _, report = fetch_probe_inputs(_FakePro(behaviors), AS_OF, sleep_fn=lambda _seconds: None)

        self.assertTrue(report["had_provider_error"])
        self.assertTrue(report["opt_daily_fail_fast_triggered"])
        failures = [s for s in report["endpoint_statuses"] if s["endpoint"] == "opt_daily"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["attempt_count"], 3)
        receipt = build_fetch_failure_summary(report, AS_OF)
        self.assertEqual(receipt["trade_dates_planned"], len(PIT_DATES))
        self.assertEqual(receipt["trade_dates_probed"], 1)
        self.assertEqual(receipt["failures"], [{
            "endpoint": "opt_daily", "failure_count": 1, "total_attempt_count": 3,
            "error_categories": ["network"], "first_trade_date": PIT_DATES[0],
            "last_trade_date": PIT_DATES[0],
        }])
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "iv_failure.json"
            write_fetch_failure_summary(receipt, str(out))
            raw = out.read_text(encoding="utf-8")
        for leak in ("SECRET123", "token=", "url=", "raw_rows", "api.example.invalid", "RuntimeError"):
            self.assertNotIn(leak, raw)

    def test_terminal_output_does_not_leak_url_token_rawrows(self):
        leaky = RuntimeError("request failed url=https://api.example.invalid/dataapi?token=SECRET123 raw_rows=[{'x':1}]")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _df, status = _safe_pro_call(_FakePro({"opt_basic": leaky}), "opt_basic")
        out = buf.getvalue()
        for leak in ("SECRET123", "token=", "url=", "raw_rows", "api.example.invalid"):
            self.assertNotIn(leak, out)
        self.assertFalse(status["ok"])
        self.assertEqual(status["error_class"], "RuntimeError")

    def test_sanitized_error_categories_distinguish_rate_limit_and_provider_server(self):
        _df, limited = _safe_pro_call(
            _FakePro({"opt_basic": RuntimeError("HTTP 429 Too Many Requests")}), "opt_basic",
        )
        _df, server = _safe_pro_call(
            _FakePro({"opt_basic": RuntimeError("HTTP 503 Service Unavailable")}), "opt_basic",
        )
        _df, gateway_timeout = _safe_pro_call(
            _FakePro({"opt_basic": RuntimeError("HTTP 504 Gateway Timeout")}), "opt_basic",
        )
        self.assertEqual(limited["error_category"], "rate_limit")
        self.assertEqual(server["error_category"], "provider_server")
        self.assertEqual(gateway_timeout["error_category"], "provider_server")


class MainGuardTests(unittest.TestCase):
    def test_requires_fetch_authorization(self):
        with self.assertRaises(SystemExit):
            main(["--as-of", AS_OF, "--out", "x.json"])   # no --confirm-fetch-authorized

    def test_rejects_invalid_as_of_before_any_fetch(self):
        with self.assertRaises(SystemExit):
            main(["--as-of", "20260631", "--out", "x.json", "--confirm-fetch-authorized"])

    def test_provider_error_aborts_without_writing_summary(self):
        # adversarial: a provider exception must NOT land as an ordinary not-computable artifact.
        b = _good_pro_behaviors()
        b["opt_basic"] = PermissionError("denied")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "probe.json"
            with self.assertRaises(SystemExit):
                main(["--as-of", AS_OF, "--out", str(out), "--confirm-fetch-authorized"],
                     pro_factory=lambda: _FakePro(b))
            self.assertFalse(out.exists())               # no summary written on provider failure

    def test_good_provider_writes_computable_summary(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "probe.json"
            main(["--as-of", AS_OF, "--out", str(out), "--confirm-fetch-authorized"],
                 pro_factory=lambda: _FakePro(_good_pro_behaviors()))
            self.assertTrue(out.exists())
            self.assertTrue(json.loads(out.read_text(encoding="utf-8"))["computable"])


if __name__ == "__main__":
    unittest.main()
