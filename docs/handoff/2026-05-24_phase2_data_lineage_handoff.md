# Phase 2 Data Lineage Handoff

Date: 2026-05-24

## What Changed

Closed the Phase 2.6 lineage tail by adding a formal `data_lineage` object to `backtest_report.json`. Report schema bumped to `rank_backtest_report` v1.10.0.

Files changed:

- `schemas/rank_backtest_report.schema.json` (v1.9.0 → v1.10.0; `data_lineage` added to `required` + `properties`)
- `runners/backtest_rank.py` (writes `data_lineage` block; schema_version constant bumped)
- `result/a_short/backtest/backtest_report.json` (regenerated via `--stats-only`)
- `docs/CURRENT.md` (Phase 2.6 status flipped to 完成；§6 next-step list rewritten around Phase 3)
- `AGENTS.md` (handoff chain link)

## Why

Phase 2.6 design doc and AGENTS guardrail were already in place, but report lineage was only partially recorded — provider, API surface, benchmark identifiers, and PIT limitations were scattered across `settings`, `forward_daily`, and the free-text `limitations` array, or absent entirely. The 24p v7.10 review explicitly flagged this as the Phase 2.6 闭环 gap.

A future reader (LLM teammate, audit, or a Phase 7 DataHub refactor) now has one canonical place to identify what fed every number in the report.

## The data_lineage Object

```json
"data_lineage": {
  "data_provider": "tushare",
  "api_families": {
    "candidate_generation": [
      "daily", "daily_basic", "moneyflow", "fina_indicator",
      "stk_limit", "stock_basic", "trade_cal",
      "index_member_all", "index_member", "index_classify",
      "adj_factor", "concept", "concept_detail"
    ],
    "forward_evaluation": [
      "daily", "adj_factor", "stk_limit", "index_daily", "trade_cal"
    ]
  },
  "forward_return_adjustment_mode": "qfq_via_adj_factor",
  "benchmark_sources": {
    "csi300": "tushare:index_daily/000300.SH",
    "csi1000": "tushare:index_daily/000852.SH",
    "eligible": "internal:generated/_intermediate/egs_full_YYYYMMDD.csv Tier1+Tier2 equal-weight"
  },
  "pit_limitations": [
    "Tushare financials are filtered by ann_date<=as_of but returned values reflect latest revisions, not as-originally-disclosed (Tushare API limitation, not fixable here).",
    "L3 concept catalysts have no native as-of parameter; PIT support is via locally accumulated state/l3_snapshots/ snapshots (only effective once coverage is meaningful).",
    "SW industry membership applies in_date/out_date PIT filtering (B3a fix).",
    "Stock universe includes delisted stocks per as_of (B2 fix)."
  ]
}
```

Notes:

- `forward_return_adjustment_mode` is read from `forward_daily.adj` when available; otherwise defaults to `qfq_via_adj_factor`. Schema enum currently `qfq_via_adj_factor | none` matches `forward_daily.adj`.
- `pit_limitations` is a centralized, structured subset; the dynamic `l3_mode`-dependent note still lives in the top-level `limitations` array (it varies per run).
- This is additive metadata only. No production screening, candidate scoring, sample selection, or stats computation changed.

## Validation Commands

Syntax check:

```powershell
python -c "from pathlib import Path; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in ['runners/backtest_rank.py']]; print('syntax ok')"
```

Result: `syntax ok`.

Schema meta-validation:

```powershell
python -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/rank_backtest_report.schema.json',encoding='utf-8')); Draft7Validator.check_schema(s); print('schema meta-validation ok')"
```

Result: `schema meta-validation ok`.

Stats-only regeneration:

```powershell
python runners/backtest_rank.py --mode production --stats-only --windows 5,10,20 --split-date 20250101
```

Result: success, exit code 0.

Independent report-against-schema validation:

```powershell
python -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/rank_backtest_report.schema.json',encoding='utf-8')); r=json.load(open('result/a_short/backtest/backtest_report.json',encoding='utf-8')); errs=list(Draft7Validator(s).iter_errors(r)); print(f'errors: {len(errs)}'); print('schema_version:', r['schema_version'])"
```

Result: `errors: 0`, `schema_version: 1.10.0`.

## Invalidated Old Conclusions

- `rank_backtest_report` v1.9.0 outputs remain readable but no longer match the current contract (missing `data_lineage`).
- `CURRENT.md` claim that Phase 2.6 was "待启动" is invalid; Phase 2.6 is now complete.
- `CURRENT.md` schema-version references to `1.8.0` are invalid; current is `1.10.0`.

No strategy conclusion changes. Phase 2 strategy boundary unchanged: engineering signoff yes, strategy signoff no, Tier1-only is the primary subset.

## Next Notes

- Future schema changes that introduce a new data source (e.g., 美股扩展时引入 polygon/alpaca) must extend `data_provider` enum and add to `api_families`. Treat any new external API endpoint as a `data_lineage` change requiring schema version bump.
- Phase 3 analyzer/state work should be the next handoff. The Phase 2.6 work is now considered fully closed.

---

## 2026-05-24 追加：data canary 旁路对账脚本

新建 `runners/data_canary.py`：每周选股后跑一次，对 Tier1 候选随机抽 5 只，对比 close/pe/pb/name 在 Tushare（egs_main.py 落盘）和 akshare（实时快照）是否一致。属于 Phase 2.6 lineage 收尾的最后一块拼图——data_lineage 元数据说"我们用了什么源"，canary 验证"这个源没有静默漂移"。

### 改动文件

- 新增 `runners/data_canary.py`（~230 行）
- 修改 `.gitignore` 加 `logs/`（canary 输出目录）
- 修改 AGENTS.md 文件参考
- 修改 CURRENT.md §2/§7

### 设计约束（违反则不应合入）

- **不进入打分**：不写 `analysis_input.json`、不动 candidates.csv、不改 EGS Tier 划分
- **不阻断选股**：任何异常（akshare 未装 / 抓取失败 / 候选缺失）都只写 `logs/data_canary_<as_of>.json` 并 exit 0
- **不对比行业**：Tushare 用 SW 申万，akshare 默认东财/同花顺，体系不一致硬比会大量误报
- **阈值收紧**：close 差异 > 0.5% warning / > 5% error；pe/pb 差异 > 10% 才 warning；name 忽略 ST/*ST/PT 前缀

### 三个 graceful 分支

| 分支 | 触发 | 验证状态 |
|---|---|---|
| `skipped_akshare_not_installed` | akshare 未装 | 已沙箱验证 |
| `skipped_no_candidates` | 找不到 egs_full_<as_of>.csv 也找不到 backtest candidates | 路径分支已加 |
| `error_akshare_fetch_failed` | akshare API 异常（限速 / 网络 / 接口变更） | 已沙箱验证（沙箱无法连东财，正好验证不阻断逻辑） |
| `ok / warn / error_drift / error_missing` | 真实对账 | **需用户本地（非沙箱）跑一次验证** |

### 使用

```powershell
# 默认：auto-find A-EGS/Result/egs_full_<today>.csv，过滤 Tier1，随机抽 5 只
python runners/data_canary.py

# 指定 as-of
python runners/data_canary.py --as-of 20260522

# 手工指定候选源
python runners/data_canary.py --candidates A-EGS/Result/egs_full_20260522.csv
```

输出：`logs/data_canary_<as_of>.json`。结构含 `summary.overall_status`（ok/warn/error_drift/error_missing）、`comparisons` 数组（每只票的 diff）、`thresholds`、`limitations`。

### 失效旧结论

无。canary 是旁路新增工具，不改任何已有结论或数据流。

### 验证命令

```powershell
python -c "from pathlib import Path; compile(Path('runners/data_canary.py').read_text(encoding='utf-8'), 'runners/data_canary.py', 'exec'); print('syntax ok')"
python runners/data_canary.py --as-of 20260522 --help
python runners/data_canary.py --as-of 20260522   # 沙箱无网会落 error_akshare_fetch_failed，符合预期
```

### 下一步

1. 用户本地（非沙箱）跑一次 `python runners/data_canary.py --as-of 20260522` 验证真实对账分支；如果 5 只里 close 差异都 < 0.5% 且 name 一致 → 收尾完成
2. 周五选股流程末尾加一行 canary 调用（手工 / 脚本 / scheduler 都可，不强制）
3. 第一次跑出 warning 时复查阈值是否合适，再决定是否调整

## 2026-05-24 追加：data canary debug hardening

Codex 本地 debug 后修复 `runners/data_canary.py` 的几个旁路健壮性问题：

- 手工传入 repo 外候选文件时，不再因 `Path.relative_to(ROOT)` 抛异常。
- 候选 CSV 读取失败 / 缺必需列时，写 log 后 exit 0。
- `--tier ''` 现在真正允许禁用 tier 过滤，不再强制要求 `tier` 列。
- `--sample-size 0` 或负数解析后会 graceful skip。
- akshare 返回字段缺失时，写 `error_akshare_schema_mismatch` 后 exit 0。
- akshare 代码列统一 `zfill(6)`，避免数值型代码丢前导 0 后误判缺失。
- 所有 skip/error 分支补 `summary.overall_status`，便于后续自动读取。

验证命令：

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; compile(Path('runners/data_canary.py').read_text(encoding='utf-8'), 'runners/data_canary.py', 'exec'); print('syntax ok')"
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe runners\data_canary.py --as-of 19990101
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe runners\data_canary.py --as-of 20260522
```

额外用伪 akshare DataFrame 覆盖了真实对账分支、akshare schema mismatch、`--sample-size 0`、`--tier ''` 分支。

验证结果：

- syntax ok。
- bundled Python 未安装 akshare，输出 `skipped_akshare_not_installed`，exit 0。
- Python 3.13 已安装 akshare，但 Codex 环境访问东财代理失败，输出 `error_akshare_fetch_failed`，exit 0，符合“不阻断选股”约束。
- 伪 akshare 真实对账分支输出 `overall_status=ok`，5 只样本 comparison 结构完整。

失效旧结论：

- “真实对账分支只能等用户本地验证”这句话需要细化：比较逻辑已用伪 akshare 本地验证；真实 akshare 网络源仍需用户在非代理受限环境跑一次确认。

---

## 2026-05-24 append: Tushare internal data health

AKShare/Eastmoney proved unreliable in the user's normal environment, so the P0 data insurance path moved to an internal Tushare health check. This is not a second provider and does not change scoring, ranking, candidates, or backtest conclusions.

### Changed files

- `A-EGS/egs_main.py`
  - `export_analysis_input(...)` now returns the in-memory `analysis_input` dict in addition to file paths.
  - Added `build_data_health(...)`, `export_data_health(...)`, and `log_data_health_summary(...)`.
  - Official non-backtest runs now write `result/a_short/<trade_date>/data_health.json` after `analysis_input.json`, `snapshot.json`, and `candidates.csv` are written.
  - Official non-backtest runs print/log a one-line summary: `[DATA_HEALTH] OK|WARN|ERROR: errors=N, warnings=N, watch=N, tier1=N, final=N -> <path>`.
  - `--backtest-mode` skips `data_health.json` to avoid polluting generated 24-period backtest artifact directories.
- `schemas/data_health.schema.json`
  - New Draft 7 contract for the `data_health.json` output, schema version `1.0.0`.

### Checks covered

- `analysis_input` schema identity/version and current `EGS_VERSION`.
- `source.data_provider == tushare`.
- Required output files exist.
- Full universe is non-empty and not unusually small.
- Watch pool, final pool, and Tier1 counts are non-empty and below-threshold cases are surfaced.
- Watch-pool close is present and positive.
- PE/PB missing-rate warning when above 20%.
- Watch-pool SW L1/L2 unknown labels.
- Candidate `data_quality.completeness_score` warning below 95 and error below 75.

### Validation commands

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; compile(Path('A-EGS/egs_main.py').read_text(encoding='utf-8'), 'A-EGS/egs_main.py', 'exec'); print('egs syntax ok')"
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import json; from jsonschema import Draft7Validator; schema=json.load(open('schemas/data_health.schema.json',encoding='utf-8')); Draft7Validator.check_schema(schema); print('data_health schema ok')"
C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe -c "import sys,json,importlib.util,pandas as pd; from jsonschema import Draft7Validator; sys.argv=['egs_main.py','--help']; spec=importlib.util.spec_from_file_location('egs_main','A-EGS/egs_main.py'); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); df_full=pd.read_csv('A-EGS/Result/egs_full_20260522.csv'); cand=pd.read_csv('result/a_short/20260522/candidates.csv'); codes=cand['ts_code'].astype(str).tolist(); df_full['ts_code']=df_full['ts_code'].astype(str); watch=df_full[df_full['ts_code'].isin(codes)].copy(); watch['order']=watch['ts_code'].map({c:i for i,c in enumerate(codes)}); watch=watch.sort_values('order').drop(columns=['order']); tier1=watch[watch['tier'].astype(str).eq('Tier1')].copy(); ai=json.load(open('result/a_short/20260522/analysis_input.json',encoding='utf-8')); ai['source']['screening_engine_version']=mod.EGS_VERSION; health=mod.build_data_health(df_full,watch,tier1,ai,'20260522','result/a_short/20260522/analysis_input.json','result/a_short/20260522/snapshot.json','result/a_short/20260522/candidates.csv','A-EGS/Result/egs_tier1_20260522.csv','A-EGS/Result/egs_full_20260522.csv'); schema=json.load(open('schemas/data_health.schema.json',encoding='utf-8')); errors=list(Draft7Validator(schema).iter_errors(health)); print(health['overall_status'], health['metrics']); print('validation_errors', len(errors)); print('errors', health['errors']); print('warnings', health['warnings'][:3])"
```

### Validation result

- Syntax validation: `egs syntax ok`.
- Schema meta-validation on local Python 3.13: `data_health schema ok` (`jsonschema` is not installed in bundled Python).
- Builder validation on 20260522 existing artifacts with current-version source metadata: `overall_status=ok`, schema validation errors `0`.
- Metrics observed: `full_count=1307`, `watch_count=15`, `tier1_count=15`, `final_count=5`, `close_missing_or_nonpositive_count=0`, `pe_missing_count=1`, `pb_missing_count=0`, `watch_l1_unknown_count=0`, `watch_l2_unknown_count=0`, `completeness_score_min=95.65`.
- Errors: `[]`; warnings: `[]`.

### Invalidated old notes

- The previous P0 suggestion "use AKShare canary as weekly insurance" is no longer the *sole* primary recommendation. Internal data_health is now the **always-on primary check**; akshare canary becomes a **complementary second-source check** (see the sina switch append below — sina endpoint is stable, was rescued, and gives independent cross-source signal that internal health alone cannot).
- "Need user local real AKShare reconciliation before closing data insurance" is updated: real reconciliation is now working via `--source=sina` (see append below). Phase 2.6 lineage closure now relies on TWO complementary layers.

---

## 2026-05-24 追加：data_canary --source sina（akshare 切新浪源，VPN-agnostic）

### 背景

用户本地实测：akshare 的东财源 `stock_zh_a_spot_em()` 在用户网络环境下不稳定——
- 不连 VPN：东财对默认 requests 客户端的 TLS 指纹反爬，连接被 reset (`RemoteDisconnected`)
- 连 VPN：本地代理把国内域名 `*.eastmoney.com` 错误路由到海外节点 → `ProxyError`

但 akshare 的新浪源 `stock_zh_a_spot()` 连不连 VPN 都通（返回 5521 只全市场），字段虽然没有 pe/pb，但**最关键的 close + name 是有的**。close + name 能拦行情错 / 复权错 / 代码对应错 / 退市误标 / 停牌误判，这些才是数据 bug 高频场景；pe/pb 因为口径不同（Tushare TTM vs 东财动态）容差本来就放宽到 10%，实际拦截力有限。

### 改动

- `runners/data_canary.py`
  - 加 `AK_SOURCES` 字典：`sina`（默认，close+name only）+ `em`（含 pe/pb，需 VPN split-tunnel）
  - 加 `--source {sina,em}` CLI 选项（默认 `sina`）
  - `_compare_one()` 接收 `supports_pe_pb` 参数，sina 源跳过 pe/pb 对账
  - `_normalize_code()` 抽取数字 + zfill(6)，兼容 sina 可能返回的 `sh600000` 前缀格式（实测当前 sina 返回纯 6 位，但防御保留）
  - 报告 `limitations` 根据所选源动态调整（sina 时提示"如需 pe/pb 切 --source=em"）
  - 报告新增 `source` 字段标识所选源
- 同主题不另建 handoff（按 AGENTS.md §交接记录 新门槛规则）

### 设计 trade-off

| 维度 | sina（默认） | em |
|---|---|---|
| close 对账 | ✅ | ✅ |
| name 对账 | ✅ | ✅ |
| pe/pb 对账 | ❌ | ✅ |
| VPN 依赖 | 无 | 必须 split-tunnel `*.eastmoney.com` |
| 反爬风险 | 低 | 高 |
| 周五跑稳定性 | 高 | 不稳定 |

选 sina 作默认的核心理由：**稳定性 > 字段完整性**。canary 是周度旁路检查，能不能跑过比检查多少字段重要。pe/pb 不在 canary 拦截也没关系——内置 `data_health.json` 已经会 warn pe/pb 缺失率 > 20%，相当于在 Tushare 自己输出上做 sanity check，覆盖了 canary 失去的 pe/pb 那块。

### 验证

```powershell
python D:\cnhea\Stock\runners\data_canary.py --as-of 20260522
```

用户本地实测输出：
```
[INFO] fetching akshare stock_zh_a_spot via --source=sina (5 candidates to check)...
[OK] canary ok: 0 missing, 0 errors, 0 warnings (5 sampled from 49 Tier1 rows) -> logs\data_canary_20260522.json
```

5 只 Tier1 抽样（小商品城 / 北方稀土 / 信质集团 / 杰克科技 / 工业富联）的 close + name 在 Tushare 和 sina 之间完全一致，包括"工业富联"这种容易乱码的名字。Phase 2.6 lineage 闭环真正落地——从此 canary 是可以每周跑得通的工具，不是"理论上可跑、实际挂"的形式主义。

### 双层数据保险定位（与上一段 Codex internal health 协同）

| 层 | 工具 | 触发 | 检查什么 | 优势 |
|---|---|---|---|---|
| 第一层（默认开） | `data_health.json`（egs_main.py 自动写） | 每次实盘选股 | Tushare 自己输出的 sanity（completeness_score / pe 缺失率 / 行业未知率 / 候选池大小） | 不依赖第二个源，永远跑得通 |
| 第二层（按需） | `data_canary.py --source sina` | 选股后手动跑 | Tushare ↔ sina **跨源**对账 close + name | 拦内置 health 看不到的"两个源都说有数但值不同"的数据漂移 |

两层互补，不重复：
- 内置 health 能拦 Tushare 单源内部不一致（如行业全是"未知"那类塌方）
- canary 能拦"Tushare 的数自洽但其实错了"（如 SW v4 那次：tushare 返回不完整但每个值看着都对）

### 失效旧结论

- 上一段 Codex internal health 里的"AKShare endpoint/proxy path is unstable"——**em 源仍不稳定**，但 sina 源稳定，这条结论范围需细化。已修订上一段措辞。
- 上一段"akshare canary 降级为 optional"——更准确说法是"akshare canary 是 secondary cross-source check，complementary 不 redundant"。

### Next

- 周五选股流程：先跑 `egs_main.py`（自动产 data_health.json），再可选跑 `data_canary.py --source sina` 做跨源验证。不强制同时跑，但同时跑可拦更多类型的 bug
- 如果未来用户调好 VPN split-tunnel 让东财通了，跑 `data_canary.py --source em` 可启用 pe/pb 对账

---

## 2026-05-24 追加：weekly_screening.ps1 一键 wrapper

### 背景

双层数据保险（data_health + canary）落地后，用户问能不能"自动同时跑"。直接把 canary 调用嵌进 egs_main.py 违反 canary 的旁路约束（不进入打分、不阻断选股），所以采用极薄 wrapper 方案：~60 行 PowerShell，串两个独立 Python 入口，互不耦合。

### 改动

- 新增 `runners/weekly_screening.ps1`
- `runners/README.md` 加入口说明
- `docs/CURRENT.md §7` 加运行命令
- 同主题追加，不另建 handoff

### 设计要点

| 决策 | 理由 |
|---|---|
| egs_main 失败时**跳过** canary | 没有当次 candidates，对账无意义；exit code 透传 egs_main |
| canary 失败时**不影响**整体 exit code | 旁路约束第一条：永不阻断选股；canary 自己 graceful skip 已经处理数据/网络问题，wrapper 这里多兜底 Python 进程崩溃 |
| 默认 `--source sina` | 与 canary 默认对齐；VPN-agnostic |
| 支持 `-SkipCanary` switch | 紧急情况下只跑选股 |
| 支持 `-CanarySource em` | 未来 VPN split-tunnel 调好时可切回东财源（pe/pb 对账） |
| 不把 egs_main 重写成被 wrapper 调用的库 | 维持入口独立性，下次 Codex 改 egs_main 不会踩 wrapper 雷 |

### 验证

```powershell
# 沙箱内只跑参数解析 + stage1 启动确认（不跑完整 egs_main）
powershell -NoProfile -File D:\cnhea\Stock\runners\weekly_screening.ps1 -AsOf 20260522 -SkipCanary
```

输出表头 + "[1/2] Running A-EGS\egs_main.py --as-of 20260522 ..."，证明工作目录切换、参数解析、stage 路由都对。完整端到端跑（含 stage 2 canary）由用户每周五自然触发。

### Next

- 用户下次周五（实盘日）跑 `.\runners\weekly_screening.ps1` 验证完整路径
- 如果未来加 Phase 3 analyzer，按相同模式扩展 wrapper：egs_main → analyzer → canary（仍保留 canary 旁路语义）

---

## 2026-05-24 追加：canary + data_health 全量审查后的 bug 修复

用户要求"从头到尾"审查脚本。发现 4 个 MED + 1 个 LOW 的真实问题，全部修复。

### 修复 1：data_canary 顶层 `status` 字段，统一 happy / skip 两条路径

**问题**：skip / error 分支的 payload 有顶层 `status`，成功路径只有 `summary.overall_status`。下游脚本想"读一个键判断 canary 是否完全 OK"，写不出统一 grep。

**修复**：`runners/data_canary.py` 成功路径 payload 加 `"status": overall` 与 `summary.overall_status` 同值。skip/error 分支已有该字段，不动。

### 修复 2：EGS_API_FAMILIES 提为模块常量，data_health + data_lineage 共享

**问题**：`A-EGS/egs_main.py:1013` 写死 `["daily", "daily_basic", "fina_indicator", "index_*", "moneyflow", "concept_*"]`（6 个，含通配符）；`runners/backtest_rank.py` 的 data_lineage 写死 13 个具体名。两个都声称"egs_main 用了什么 Tushare API"，结果不一致。Phase 7 DataHub 想要单一真相源，这是伏笔。

**修复**：
- `A-EGS/egs_main.py` 加 module-level `EGS_API_FAMILIES = [...]`（13 个，与 backtest_rank 的完整版对齐），`build_data_health()` 改读这个常量
- `runners/backtest_rank.py` 加 `_current_egs_api_families()` regex + ast 读取 egs_main 的常量（同 `_current_egs_version()` 模式），运行时保证两边永远一致
- `_current_egs_api_families()` 解析失败时回落到 hardcoded 13 个名（与常量内容同步），且 fallback 触发的话下次 data_health check 会标 drift

### 修复 3：data_health limitations 措辞过时

**问题**：`A-EGS/egs_main.py:1039` 写"AKShare canary remains optional because its Eastmoney endpoint is unstable in this environment."——这句话是 Codex 在 sina 切换之前写的。每次实盘选股会写到 `data_health.json`，下次用户/LLM 看 log 会被误导以为 canary 完全不可用。

**修复**：改成 "AKShare canary (runners/data_canary.py) now uses sina (stock_zh_a_spot) by default and works reliably; the em source needs VPN split-tunnel for *.eastmoney.com if pe/pb reconciliation is required."

### 修复 4：data_canary 非原子写

**问题**：`_write_log` 直接 `open("w")` + `json.dump`。Ctrl+C / OOM / 断电时会留下截断的无效 JSON。egs_main 旁边 `write_json_atomic` 已经用 tmpfile + os.replace 做对了，canary 没保持一致。

**修复**：`_write_log` 改成 `tempfile.mkstemp` 写完后 `os.replace` 原子替换；失败时清理 tmp 文件。

### 修复 5：`_normalize_code` 对 >6 位数字截断方向错误（LOW）

**问题**：`return digits.zfill(6)[-6:]` 对 `"1234567"` 取后 6 位 `"234567"`，**丢前导 1 错配到另一只票**。A 股不会出现 >6 位，但港股 5 位 / 美股 / 未来扩展可能踩到。

**修复**：`>6 位直接返回 ""`，让对账归到 `missing_in_akshare`（旁路约束允许这种 graceful 失败），不做错误猜测。

### 验证

```powershell
# 1. 语法
python -c "from pathlib import Path; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in ['runners/data_canary.py','runners/backtest_rank.py','A-EGS/egs_main.py']]; print('syntax ok all 3')"

# 2. EGS_API_FAMILIES regex 解析
python -c "import sys; sys.path.insert(0,'runners'); from backtest_rank import _current_egs_api_families; fams = _current_egs_api_families(); assert len(fams)==13 and 'stk_limit' in fams; print('PASS')"

# 3. _normalize_code 边界 case
python -c "import sys; sys.path.insert(0,'runners'); from data_canary import _normalize_code; assert _normalize_code('1234567')=='' and _normalize_code('sh600000')=='600000' and _normalize_code('1')=='000001'; print('PASS')"

# 4. data_canary skip 路径写 log 含顶层 status
python runners/data_canary.py --as-of 19990101
# log 含 "status": "skipped_no_candidates"

# 5. stats-only 重生成 backtest_report
python runners/backtest_rank.py --mode production --stats-only --windows 5,10,20 --split-date 20250101
```

验证结果：
- 全部 syntax ok
- `_current_egs_api_families()` 正确解析出 13 个 API 名
- `_normalize_code` 10 个 case 全过（含新加的 '1234567' -> '' reject 行为）
- canary skip 路径写出顶层 `status` 字段
- 重生成的 `backtest_report.json` schema 1.10.0、validator 0 errors、`data_lineage.api_families.candidate_generation` = 13 个名 (与 egs_main EGS_API_FAMILIES 完全一致)、sample_count 360 不变

### 失效旧结论

- 上一段说 "AKShare canary remains optional because its Eastmoney endpoint is unstable" — 现在 data_health.json 的 limitations 字段已更新措辞
- 此前 data_health api_families = 6 个含通配符的不准确版本 — 现在 = 13 个精确名

### Next

下次周五用户跑 `weekly_screening.ps1` 时：
- `data_health.json` limitations 第 3 条会显示新措辞
- `data_canary.json` 含顶层 status 字段
- 任何重跑的 backtest report 的 `data_lineage.api_families.candidate_generation` 自动跟 egs_main 同步

---

## 2026-05-24 append: full script review fixes

Full `A-EGS/egs_main.py` review found and fixed two deterministic robustness bugs:

- `data_health` missing-column handling was too permissive. A non-empty watch DataFrame without `close`/`pb`/industry columns was previously counted as `0` missing values. Missing columns now count as all rows missing, so missing `close` becomes `overall_status=error`.
- `precompute_stock_stats(...)` returned an empty no-column DataFrame when `all_daily` was non-empty but had no matching `ts_code` with the stock universe. Downstream `build_master(...)` then risked `KeyError: pct_20d`. It now returns the same neutral stats table used for severely insufficient daily data.

Validation:

```powershell
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "from pathlib import Path; compile(Path('A-EGS/egs_main.py').read_text(encoding='utf-8'), 'A-EGS/egs_main.py', 'exec'); print('compile ok')"
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "import sys, importlib.util, pandas as pd; sys.argv=['egs_main.py','--help']; spec=importlib.util.spec_from_file_location('egs_main','A-EGS/egs_main.py'); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); watch=pd.DataFrame({'ts_code':['000001.SZ']*5,'tier':['Tier1']*5,'pb':[1]*5,'l1_name':['银行']*5,'l2_name':['银行']*5}); full=watch.copy(); ai={'schema_name':'analysis_input','schema_version':'1.1.0','source':{'screening_engine_version':mod.EGS_VERSION,'data_provider':'tushare'},'candidates':[{'data_quality':{'completeness_score':100}} for _ in range(5)]}; h=mod.build_data_health(full,watch,watch,ai,'20260522','','','','',''); print(h['overall_status']); print(h['metrics']['close_missing_or_nonpositive_count']); print(h['errors'])"
C:\Users\cnhea\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "import sys,importlib.util,pandas as pd; sys.argv=['egs_main.py','--help']; spec=importlib.util.spec_from_file_location('egs_main','A-EGS/egs_main.py'); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); all_daily=pd.DataFrame({'ts_code':['999999.SZ']*1001,'trade_date':['20260522']*1001,'close':[1.0]*1001,'high':[1.0]*1001,'low':[1.0]*1001,'pre_close':[1.0]*1001,'pct_chg':[0.0]*1001,'amount':[1.0]*1001}); stats=mod.precompute_stock_stats({'000001.SZ'}, all_daily); print(stats.shape); print(list(stats.columns))"
```

Results:

- Syntax compile: ok.
- Missing `close` health probe: `overall_status=error`, `close_missing_or_nonpositive_count=5`, errors include `check=close`.
- Daily no-overlap probe: returns `(1, 15)` neutral stats columns instead of `(0, 0)`.
- Existing 20260522 health builder remains `overall_status=ok`, schema validation errors `0`.
