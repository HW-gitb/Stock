import json, csv, os
import importlib.metadata
import jsonschema
from jsonschema import Draft202012Validator, Draft7Validator
from collections import defaultdict

SCHEMA = r'D:\cnhea\Stock\schemas\analysis_input.schema.json'
AIN    = r'D:\cnhea\Stock\result\a_short\20260522\analysis_input.json'
SNAP   = r'D:\cnhea\Stock\result\a_short\20260522\snapshot.json'
TIER1  = r'D:\cnhea\Stock\A-EGS\Result\egs_tier1_20260522.csv'
CANDS  = r'D:\cnhea\Stock\result\a_short\20260522\candidates.csv'

sep = '=' * 70

# ----- TASK 1 -----
print(sep); print('TASK 1 - Schema legality'); print(sep)
schema = json.load(open(SCHEMA, encoding='utf-8'))
print('$schema       :', schema.get('$schema'))
print('$id           :', schema.get('$id'))
print('title         :', schema.get('title'))
print('has description:', bool(schema.get('description')))
print('required[]    :', 'required' in schema, '(len=%d)' % len(schema.get('required', [])))
print('required keys :', schema.get('required'))
try:
    Draft202012Validator.check_schema(schema)
    print('Draft 2020-12 meta-schema: PASS')
except Exception as e:
    print('Draft 2020-12 meta-schema: FAIL ->', str(e)[:200])
try:
    Draft7Validator.check_schema(schema)
    print('Draft 7 meta-schema     : PASS')
except Exception as e:
    print('Draft 7 meta-schema     : FAIL ->', str(e)[:200])

# ----- TASK 2 -----
print()
print(sep); print('TASK 2 - Field coverage (M0-M6)'); print(sep)
found = set()
def walk(o):
    if isinstance(o, dict):
        if 'properties' in o and isinstance(o['properties'], dict):
            for k, v in o['properties'].items():
                found.add(k); walk(v)
        for k, v in o.items():
            if k != 'properties': walk(v)
    elif isinstance(o, list):
        for x in o: walk(x)
walk(schema)

required_fields = [
    'ts_code','name','l2_name','close','pct_5d','pct_20d','pct_60d','drawdown_20d',
    'avg_amount_20d','final_score','esp_score','cat_score','l4_score','l4_flag',
    'l2_flags','overheat_flag','entry_flag','big_ratio','reduce_penalty','val_bonus',
    'val_penalty','q0_dt_yoy','pe_ttm','pb','roe','turnover_rate','total_mv'
]
covered = [f for f in required_fields if f in found]
missing = [f for f in required_fields if f not in found]
print('Total required:', len(required_fields))
print('Covered (direct): %d -> %s' % (len(covered), covered))
print('Missing (direct): %d -> %s' % (len(missing), missing))
print('Coverage rate: %.1f%%' % (100 * len(covered) / len(required_fields)))
aliases = {
    'l2_name':['sw_l2_name','sw_l2_code'],
    'big_ratio':['big_order_ratio'],
    'turnover_rate':['turnover_rate','turnover','turn_rate','turnover_rate_f','free_turnover_rate'],
}
print('Alias probe for missing direct fields:')
for k in missing:
    for a in aliases.get(k, []):
        print('  %-15s ~ %-25s : %s' % (k, a, 'YES' if a in found else 'no'))

# ----- TASK 3 -----
print()
print(sep); print('TASK 3 - Output files presence/validity'); print(sep)
for p in [AIN, SNAP]:
    sz = os.path.getsize(p)
    try:
        d = json.load(open(p, encoding='utf-8'))
        print('%-22s  size=%d B  valid_json=True  top_keys=%s' %
              (os.path.basename(p), sz, list(d.keys())[:6]))
        if p == AIN:
            print('                        candidates count =', len(d.get('candidates', [])))
        else:
            c = d.get('counts', {})
            print('                        counts.final_count=%s  watch_count=%s' %
                  (c.get('final_count'), c.get('watch_count')))
    except Exception as e:
        print(p, 'PARSE FAIL', e)

# ----- TASK 4 -----
print()
print(sep); print('TASK 4 - jsonschema validation of analysis_input.json'); print(sep)
data = json.load(open(AIN, encoding='utf-8'))
v = Draft7Validator(schema)
errors = list(v.iter_errors(data))
print('jsonschema %s  ->  total errors: %d' % (importlib.metadata.version('jsonschema'), len(errors)))
if errors:
    groups = defaultdict(list)
    for e in errors:
        path = '/' + '/'.join(str(p) for p in e.absolute_path)
        parts = path.split('/')
        if len(parts) > 2 and parts[1] == 'candidates' and parts[2].isdigit():
            norm = '/candidates/[i]/' + '/'.join(parts[3:])
        else:
            norm = path
        groups[(norm, e.validator)].append(e.message[:160])
    for (path, val), msgs in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:25]:
        print('  %4d  %-22s %s' % (len(msgs), val, path))
        print('        sample:', msgs[0])
else:
    print('  PASS - no validation errors')

# ----- TASK 5 -----
print()
print(sep); print('TASK 5 - Top-3 consistency'); print(sep)
cands = data['candidates']
def keyfn(c):
    r = c.get('selection', {}).get('rank')
    return (r if r is not None else 10**9, -(c.get('scores', {}).get('final_score') or 0))
top3 = sorted(cands, key=keyfn)[:3]
with open(TIER1, encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))
csv_cols = list(rows[0].keys()) if rows else []
print('CSV columns sample:', csv_cols[:10])
pct_csv_field = 'pct_20d' if 'pct_20d' in csv_cols else ('pct_20d_n' if 'pct_20d_n' in csv_cols else None)
print('Using CSV pct field:', pct_csv_field)
print()
incon = 0
for i in range(3):
    a, b = top3[i], rows[i]
    ts_a, ts_b = a['ts_code'], b['ts_code']
    fs_a, fs_b = a['scores'].get('final_score'), float(b['final_score'])
    json_pct_field = pct_csv_field if pct_csv_field in a.get('technical', {}) else 'pct_20d'
    pj = a['technical'].get(json_pct_field)
    pc = float(b[pct_csv_field]) if pct_csv_field else None
    diffs = []
    if ts_a != ts_b: diffs.append('ts_code json=%s csv=%s' % (ts_a, ts_b))
    if abs(fs_a - fs_b) > 1e-3: diffs.append('final_score json=%s csv=%s' % (fs_a, fs_b))
    if pc is None or abs(pj - pc) > 1e-6:
        diffs.append('%s json=%s csv %s=%s' % (json_pct_field, pj, pct_csv_field, pc))
    print('Row%d  json: ts=%-10s  final=%-6s  %s=%s' % (i+1, ts_a, fs_a, json_pct_field, pj))
    print('      csv : ts=%-10s  final=%-6s  %s=%s' % (ts_b, fs_b, pct_csv_field, pc))
    print('      diff:', diffs if diffs else 'IDENTICAL')
    if diffs: incon += 1
print('Inconsistent top-3 rows:', incon)

# ----- TASK 6 -----
print()
print(sep); print('TASK 6 - manifest and candidates.csv six fields'); print(sep)
snap = json.load(open(SNAP, encoding='utf-8'))
need = ['ts_code','name','final_score','close','run_date','tier']
print('snapshot.json top-level keys:', list(snap.keys()))
manifest_need = ['schema_name','schema_version','generated_at','trade_date','preset','analysis_input','candidates','source_files','counts','columns']
manifest_missing = [f for f in manifest_need if f not in snap]
print('snapshot manifest missing fields:', manifest_missing)
with open(CANDS, encoding='utf-8-sig') as f:
    cand_rows = list(csv.DictReader(f))
bad = []
for i, r in enumerate(cand_rows):
    miss = [f for f in need if f not in r]
    if miss:
        bad.append((i, r.get('ts_code'), miss))
print('candidates.csv rows:', len(cand_rows))
print('candidates.csv records missing >=1 of six fields: %d / %d' % (len(bad), len(cand_rows)))
for i, ts, miss in bad[:20]:
    print('  idx %d ts_code=%s missing=%s' % (i, ts, miss))

# ----- TASK 7 -----
print()
print(sep); print('TASK 7 - high_20d / low_20d null consistency'); print(sep)
both = neither = only_h = only_l = 0
oh, ol = [], []
for c in cands:
    t = c.get('technical', {})
    h, l = t.get('high_20d'), t.get('low_20d')
    hv, lv = h is not None, l is not None
    if hv and lv: both += 1
    elif not hv and not lv: neither += 1
    elif hv and not lv:
        only_h += 1; oh.append((c['ts_code'], c.get('name'), h, l))
    else:
        only_l += 1; ol.append((c['ts_code'], c.get('name'), h, l))
print('total candidates:', len(cands))
print('both present     :', both)
print('neither present  :', neither)
print('high set, low null (INCONSISTENT):', only_h)
for ts, nm, h, l in oh:
    print('  %s  %s  high_20d=%s  low_20d=%s' % (ts, nm, h, l))
print('low set, high null (informational):', only_l)
for ts, nm, h, l in ol:
    print('  %s  %s  high_20d=%s  low_20d=%s' % (ts, nm, h, l))

print()
print(sep); print('END'); print(sep)
