"""Smoke test for refactored L3 snapshot helpers (H1+C2+M1+M2)."""
import os
import pickle
import shutil
import sys
import tempfile

import pandas as pd

sys.path.insert(0, r"D:\cnhea\Stock\A-EGS")
import egs_main as mod  # noqa: E402

TMP = tempfile.mkdtemp(prefix="l3_v2_")
mod.L3_SNAPSHOT_DIR = TMP

# --- T1: empty dir
assert mod._list_l3_snapshot_dates() == []
assert mod._load_l3_snapshot("20260101") is None
print("PASS T1: empty dir")

# --- T2: single-file write
concepts = pd.DataFrame({"code": ["C1", "C2", "C3"], "name": ["a", "b", "c"]})
sc = {"A": ["C1", "C2"], "B": ["C3"]}
cm = {"C1": ["A", "X"], "C2": ["A"], "C3": ["B", "Y", "Z"]}
mod._write_l3_snapshot("20260520", concepts, sc, cm)
files = sorted(os.listdir(TMP))
assert files == ["l3_snapshot_20260520.pkl"], f"got {files}"
print("PASS T2: single-file written")

# --- T3: list/load
assert mod._list_l3_snapshot_dates() == ["20260520"]
out = mod._load_l3_snapshot("20260520")
assert out is not None
cdf, sc2, cm2, snap = out
assert snap == "20260520" and sc2 == sc and cm2 == cm
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

# --- T6: _build_market_stock_concepts
fetched = {"A": ["C1", "C2"]}  # only A was a candidate
cm = {"C1": ["A", "X", "Y"], "C2": ["A", "Z"], "C3": ["X", "W"]}
result = mod._build_market_stock_concepts(fetched, cm, limit=5)
print("  market result keys:", sorted(result.keys()))
print("  A ->", result["A"])
print("  X ->", result["X"])
print("  W ->", result["W"])
assert set(result.keys()) == {"A", "X", "Y", "Z", "W"}
assert "C1" in result["A"] and "C2" in result["A"]
assert set(result["X"]) == {"C1", "C3"}
assert result["W"] == ["C3"]
print("PASS T6: market coverage with limit")

# --- T7: limit truncation
fetched = {}
cm = {f"C{i}": ["A"] for i in range(10)}
result = mod._build_market_stock_concepts(fetched, cm, limit=5)
assert len(result["A"]) == 5, f"expected 5, got {len(result['A'])}"
print("PASS T7: per-stock limit applied")

# --- T8: M2 reset CONF["l3_snapshot_date"]
mod.CONF["l3_snapshot_date"] = "20260101"
mod.CONF["l3_mode"] = "neutralize"
df_in = pd.DataFrame({"ts_code": ["A"], "pct_20d_n": [5.0]})
mod.score_l3(df_in, ["20260522"] * 5, pd.DataFrame())
assert mod.CONF["l3_snapshot_date"] is None, f"got {mod.CONF['l3_snapshot_date']}"
print("PASS T8: l3_snapshot_date reset on every call")

shutil.rmtree(TMP)
print()
print("ALL TESTS PASSED")
