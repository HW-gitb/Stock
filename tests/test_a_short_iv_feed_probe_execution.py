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
            pro=types.SimpleNamespace(client=types.SimpleNamespace(DataApi=_FakeDataApi)),
            set_token=lambda t: calls.__setitem__("set_token", calls["set_token"] + 1),
            pro_api=lambda token: ("PRO", token),
        )
        pro = init_tushare_pro("tok123", ts_module=fake_ts)
        self.assertEqual(pro, ("PRO", "tok123"))
        self.assertEqual(calls["set_token"], 0)                       # never wrote token cache
        self.assertNotEqual(getattr(_FakeDataApi, "_DataApi__http_url"), "OLD")  # endpoint pinned

    def test_pin_failure_missing_dataapi_is_hard_error(self):
        fake_ts = types.SimpleNamespace(pro=types.SimpleNamespace(),  # no .client.DataApi
                                        pro_api=lambda token: ("PRO", token))
        with self.assertRaises(RuntimeError):
            init_tushare_pro("tok", ts_module=fake_ts)

    def test_pin_failure_missing_attr_is_hard_error(self):
        class _NoAttrDataApi:  # lacks _DataApi__http_url
            pass
        fake_ts = types.SimpleNamespace(
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

    def test_provider_exception_flagged_with_sanitized_status(self):
        b = _good_pro_behaviors()
        b["opt_basic"] = PermissionError("permission denied: tk.csv")
        _, _, _, report = fetch_probe_inputs(_FakePro(b), AS_OF)
        self.assertTrue(report["had_provider_error"])
        bad = [s for s in report["endpoint_statuses"] if s["endpoint"] == "opt_basic"][0]
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error_class"], "PermissionError")
        self.assertEqual(bad["error_category"], "permission_or_quota")

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
