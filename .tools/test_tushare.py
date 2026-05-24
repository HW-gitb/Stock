"""Tushare connectivity smoke test.

Verifies:
1. TUSHARE_TOKEN env var is set
2. ts.pro_api() initializes
3. trade_cal returns recent trading dates
4. pro.daily returns rows for the most recent trade date
5. pro.daily_basic and pro.adj_factor also work (commonly used in A-EGS/backtest)
"""
import os
import sys
import time
import traceback
from datetime import datetime, timedelta

import tushare as ts

# tushare 1.4.29 hardcodes http://api.waditu.com/dataapi which currently 503s;
# the client treats the falsy Response as "no result" and returns an empty
# DataFrame. Point it at the canonical host (or whatever TUSHARE_BASE_URL is).
from tushare.pro.client import DataApi as _DataApi
_base_url = os.environ.get("TUSHARE_BASE_URL", "https://api.tushare.pro/dataapi")
if hasattr(_DataApi, "_DataApi__http_url"):
    _DataApi._DataApi__http_url = _base_url

SEP = "=" * 70


def step(title):
    print()
    print(SEP)
    print(title)
    print(SEP)


def show_df(df, n=3):
    if df is None:
        print("  -> None")
        return
    print(f"  rows={len(df)}  cols={list(df.columns)}")
    if len(df):
        print(df.head(n).to_string(index=False))


def main():
    overall_ok = True
    t0 = time.time()

    step("STEP 1 - env / library")
    token = os.environ.get("TUSHARE_TOKEN")
    print(f"  tushare version : {ts.__version__}")
    print(f"  token set       : {bool(token)}")
    if not token:
        print("  FAIL: TUSHARE_TOKEN missing")
        return 2
    print(f"  token length    : {len(token)}  head={token[:6]}...")

    step("STEP 2 - pro_api()")
    try:
        ts.set_token(token)
        pro = ts.pro_api()
        print("  pro_api()       : OK")
    except Exception as e:
        print(f"  FAIL: {e}")
        traceback.print_exc()
        return 2

    step("STEP 3 - trade_cal (last 30 days)")
    today = datetime.now()
    start = (today - timedelta(days=30)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    try:
        cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end,
                            is_open="1", fields="cal_date,is_open")
        show_df(cal, n=5)
        if cal is None or len(cal) == 0:
            print("  FAIL: empty calendar")
            overall_ok = False
            last_td = None
        else:
            last_td = str(cal["cal_date"].max())
            print(f"  latest trade_date: {last_td}")
    except Exception as e:
        print(f"  FAIL: {e}")
        traceback.print_exc()
        overall_ok = False
        last_td = None

    if not last_td:
        return 1

    step(f"STEP 4 - pro.daily(trade_date={last_td})")
    try:
        df = pro.daily(trade_date=last_td,
                       fields="ts_code,trade_date,open,close,vol,amount")
        show_df(df)
        if df is None or len(df) == 0:
            print("  FAIL: empty daily")
            overall_ok = False
    except Exception as e:
        print(f"  FAIL: {e}")
        traceback.print_exc()
        overall_ok = False

    step(f"STEP 5 - pro.daily_basic(trade_date={last_td})")
    try:
        df = pro.daily_basic(trade_date=last_td,
                             fields="ts_code,trade_date,turnover_rate,pe_ttm,pb,total_mv")
        show_df(df)
        if df is None or len(df) == 0:
            print("  WARN: empty daily_basic")
    except Exception as e:
        print(f"  FAIL: {e}")
        traceback.print_exc()
        overall_ok = False

    step(f"STEP 6 - pro.adj_factor(trade_date={last_td})")
    try:
        df = pro.adj_factor(trade_date=last_td,
                            fields="ts_code,trade_date,adj_factor")
        show_df(df)
        if df is None or len(df) == 0:
            print("  WARN: empty adj_factor")
    except Exception as e:
        print(f"  FAIL: {e}")
        traceback.print_exc()
        overall_ok = False

    step(f"STEP 7 - pro.index_daily (000300.SH last 5d)")
    try:
        df = pro.index_daily(ts_code="000300.SH", start_date=start, end_date=end,
                             fields="ts_code,trade_date,close,pct_chg")
        show_df(df)
        if df is None or len(df) == 0:
            print("  WARN: empty index_daily")
    except Exception as e:
        print(f"  FAIL: {e}")
        traceback.print_exc()
        overall_ok = False

    step("SUMMARY")
    elapsed = time.time() - t0
    print(f"  elapsed: {elapsed:.2f}s")
    print(f"  overall : {'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
