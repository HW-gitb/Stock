"""Smoke test for refactored L3 snapshot helpers (H1+C2+M1+M2)."""
import os
import pickle
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "A-EGS"))
import egs_main as mod  # noqa: E402

TMP = tempfile.mkdtemp(prefix="l3_v2_")
mod.L3_SNAPSHOT_DIR = TMP

# --- T1: empty dir
assert mod._list_l3_snapshot_dates() == []
assert mod._load_l3_snapshot("20260101") is None
print("PASS T1: empty dir")

# --- T2: single-file write
concepts = pd.DataFrame({"code": ["C1", "C2", "C3"], "name": ["a", "b", "c"]})
sc = {"600000.SH": ["C1", "C2"], "000001.SZ": ["C3"]}
cm = {
    "C1": ["600000.SH", "300001.SZ"],
    "C2": ["600000.SH"],
    "C3": ["000001.SZ", "688001.SH"],
}
mod._write_l3_snapshot("20260520", concepts, sc, cm)
files = sorted(os.listdir(TMP))
assert files == ["l3_snapshot_20260520.pkl"], f"got {files}"
print("PASS T2: single-file written")

# --- T3: list/load
assert mod._list_l3_snapshot_dates() == ["20260520"]
out = mod._load_l3_snapshot("20260520")
assert out is not None
cdf, sc2, cm2, snap = out
expected_cm = {"C1": ["600000.SH"], "C2": ["600000.SH"], "C3": ["000001.SZ"]}
assert snap == "20260520" and sc2 == sc and cm2 == expected_cm
print("PASS T3: load roundtrip")

# --- T4: corrupt file -> None + warn (M1)
path = mod._l3_snapshot_path("20260520")
with open(path, "wb") as f:
    f.write(b"not a pickle")
out = mod._load_l3_snapshot("20260520")
assert out is None, f"expected None from corrupt file, got {out}"
print("PASS T4: corrupt pickle handled")

# --- T5: schema mismatch -> None + warn
with open(path, "wb") as f:
    pickle.dump({"schema": 999, "foo": "bar"}, f)
out = mod._load_l3_snapshot("20260520")
assert out is None
print("PASS T5: schema mismatch handled")

# --- T5b: schema=1 but missing required keys -> None + warn
with open(path, "wb") as f:
    pickle.dump({"schema": 1, "snap_date": "20260520", "concepts_df": None}, f)
out = mod._load_l3_snapshot("20260520")
assert out is None, "expected None when required keys missing"
print("PASS T5b: missing-keys payload handled")

# --- T6: M2 reset CONF["l3_snapshot_date"]
mod.CONF["l3_snapshot_date"] = "20260101"
mod.CONF["l3_mode"] = "neutralize"
df_in = pd.DataFrame({"ts_code": ["600000.SH"], "pct_20d_n": [5.0]})
mod.score_l3(df_in, ["20260522"] * 5, pd.DataFrame())
assert mod.CONF["l3_snapshot_date"] is None, f"got {mod.CONF['l3_snapshot_date']}"
print("PASS T6: l3_snapshot_date reset on every call")

shutil.rmtree(TMP)
print()
print("ALL TESTS PASSED")
