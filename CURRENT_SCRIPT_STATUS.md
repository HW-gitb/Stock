# Current Script Status

脚本状态以当前仓库文件为准；本文件只做快速索引。

| Script | Status | Notes |
|---|---|---|
| `A-EGS/egs_main.py` | stable / active | A 股短线筛选入口，当前按 AGENTS 记录为 v7.10；Phase 7 前不迁移 |
| `runners/backtest_rank.py` | stable / active | Phase 2 rank backtest 入口；支持 analyzer veto replay 和 stats-only |
| `runners/run_analysis_report.py` | stable / active | Phase 4 单票 deterministic report runner；输出 schema-validated JSON + Markdown |
| `runners/forward_tracker.py` | active / accumulating | Phase 3.5 实盘 forward tracker；后台累积 forward returns |
| `runners/weekly_screening.ps1` | active | 周五一键脚本；筛选后自动 forward capture |
| `runners/data_canary.py` | active / non-blocking | 旁路数据对账；失败不阻断主流程 |
| `runners/diagnose_subscore_predictive.py` | diagnostic | Phase 3.3 子分数预测力诊断 |
| `runners/diagnose_tier1_bad_signals.py` | diagnostic | Tier1 坏票特征诊断 |

## Validation Notes

- bundled Python 可跑多数 unit tests。
- schema-validating 路径需要 `jsonschema`，通常使用本机 Python 3.13。
- 当前常规测试命令：

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

## Next Script Family

Phase 5 将新增 execution backtest 相关 runner/schema。开工前先写 Phase 5 kickoff spec 和 execution output contract。
