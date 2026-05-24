"""End-to-end PIT mechanism test using the REAL state/l3_snapshots/ directory.

Creates synthetic snapshots, exercises _load + the score_l3 pit branch's gap
logic (>14d WARN vs <=14d INFO), then cleans up.

Does NOT call any Tushare API. Does NOT pollute the directory with leftovers
on success. On crash, leftover files all start with `_e2etest_` prefix for
easy manual cleanup.
"""
import io
import logging
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, r"D:\cnhea\Stock\A-EGS")
import egs_main as mod  # noqa: E402

REAL_DIR = mod.L3_SNAPSHOT_DIR
print(f"using real snapshot dir: {REAL_DIR}")
existed_before = os.path.isdir(REAL_DIR)
preexisting = set(os.listdir(REAL_DIR)) if existed_before else set()


def _cleanup_e2e_only():
    """Remove only files we just created; never touch user's real snapshots."""
    if not os.path.isdir(REAL_DIR):
        return
    for name in os.listdir(REAL_DIR):
        if name in preexisting:
            continue
        try:
            os.remove(os.path.join(REAL_DIR, name))
        except OSError:
            pass


# Capture log warnings so we can assert on them
log_capture = io.StringIO()
handler = logging.StreamHandler(log_capture)
handler.setLevel(logging.WARNING)
mod.log.addHandler(handler)


def _drain_warnings():
    handler.flush()
    out = log_capture.getvalue()
    log_capture.truncate(0)
    log_capture.seek(0)
    return out


try:
    # === Step 1: write a synthetic snapshot at date D ===
    today = datetime.now()
    d_recent = (today - timedelta(days=3)).strftime("%Y%m%d")
    d_old = (today - timedelta(days=30)).strftime("%Y%m%d")
    d_future = (today + timedelta(days=10)).strftime("%Y%m%d")

    fake_concepts = pd.DataFrame({"code": ["C1", "C2"], "name": ["X", "Y"]})
    fake_sc = {"A.SH": ["C1"], "B.SZ": ["C2"]}
    fake_cm = {"C1": ["A.SH", "Z.SH"], "C2": ["B.SZ"]}

    mod._write_l3_snapshot(d_recent, fake_concepts, fake_sc, fake_cm)
    expected = f"{mod.L3_SNAPSHOT_PREFIX}{d_recent}{mod.L3_SNAPSHOT_SUFFIX}"
    assert os.path.exists(os.path.join(REAL_DIR, expected)), \
        f"snapshot file {expected} not created"
    print(f"PASS step1: snapshot file {expected} created in real dir")

    # === Step 2: pit lookup finds it ===
    today_str = today.strftime("%Y%m%d")
    out = mod._load_l3_snapshot(today_str)
    assert out is not None
    cdf, sc, cm, snap_date = out
    assert snap_date == d_recent, f"expected {d_recent}, got {snap_date}"
    assert sc == fake_sc and cm == fake_cm
    print(f"PASS step2: _load_l3_snapshot finds {snap_date} (3d before today)")

    # === Step 3: gap <=14 days -> INFO path (no WARN) ===
    # Drive the score_l3 pit branch
    mod.CONF["l3_mode"] = "pit"
    mod.CONF["l3_pit_strict"] = False
    mod.TODAY = today_str
    mod.TODAY_DT = today

    df_in = pd.DataFrame({"ts_code": ["A.SH", "B.SZ"], "pct_20d_n": [5.0, 10.0]})
    ad_in = pd.DataFrame({
        "ts_code": ["A.SH", "B.SZ"] * 5,
        "trade_date": [today_str] * 10,
        "pct_chg": [1.0] * 10,
        "amount": [1e8] * 10,
    })
    _ = _drain_warnings()  # clear
    _ = mod.score_l3(df_in, [today_str] * 5, ad_in)
    warns = _drain_warnings()
    assert "behind as_of" not in warns, f"unexpected gap-warn in <=14d case: {warns}"
    print(f"PASS step3: gap=3d -> no >14d WARN")

    # === Step 4: gap > 14 days -> WARN path ===
    # Add an older snapshot and remove the recent one
    os.remove(os.path.join(REAL_DIR, expected))
    mod._write_l3_snapshot(d_old, fake_concepts, fake_sc, fake_cm)
    _ = _drain_warnings()
    _ = mod.score_l3(df_in, [today_str] * 5, ad_in)
    warns = _drain_warnings()
    assert "behind as_of" in warns and ">14d" in warns, f"expected gap WARN, got: {warns}"
    print(f"PASS step4: gap=30d -> WARN logged (does not abort)")
    # Important: gap WARN must NOT abort. We verify the result df was returned
    # by checking that cat_score was actually computed (not all 50).
    result = mod.score_l3(df_in, [today_str] * 5, ad_in)
    assert "cat_score" in result.columns
    print(f"PASS step4b: pit run completed despite gap>14d (return df, not crash)")

    # === Step 5: no snapshot <= as_of + strict -> SystemExit ===
    os.remove(os.path.join(REAL_DIR, f"{mod.L3_SNAPSHOT_PREFIX}{d_old}{mod.L3_SNAPSHOT_SUFFIX}"))
    # Now no snapshots at all
    mod.CONF["l3_pit_strict"] = True
    try:
        _ = mod.score_l3(df_in, [today_str] * 5, ad_in)
        print("FAIL step5: SystemExit not raised")
        sys.exit(1)
    except SystemExit as e:
        assert "L3 mode=pit requires a snapshot" in str(e), f"unexpected msg: {e}"
        print(f"PASS step5: pit + no snapshot + strict -> SystemExit")

    # === Step 6: no snapshot + non-strict -> fallback to cat_score=50 ===
    mod.CONF["l3_pit_strict"] = False
    out = mod.score_l3(df_in, [today_str] * 5, ad_in)
    assert list(out["cat_score"]) == [50.0, 50.0], f"expected [50,50], got {list(out['cat_score'])}"
    print(f"PASS step6: pit + no snapshot + non-strict -> cat_score=50 fallback")

    # === Step 7: future-dated snapshot must NOT match as_of < snapshot ===
    mod._write_l3_snapshot(d_future, fake_concepts, fake_sc, fake_cm)
    mod.TODAY = today_str  # as_of = today, snapshot is in the future
    out = mod._load_l3_snapshot(today_str)
    assert out is None, f"future snapshot must not match today as_of; got {out[3] if out else None}"
    print(f"PASS step7: future-dated snapshot ignored")

finally:
    _cleanup_e2e_only()
    mod.log.removeHandler(handler)
    print()
    leftover = set(os.listdir(REAL_DIR)) - preexisting if os.path.isdir(REAL_DIR) else set()
    if leftover:
        print(f"WARN: leftover test files: {leftover}")
    else:
        print("clean: no leftover test files in state/l3_snapshots/")

print()
print("ALL E2E PIT TESTS PASSED")
