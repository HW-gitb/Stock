# US-short 软发现「查询质量探针」20260815 运行单

**这是 20260815 槽唯一一次允许花钱的运行。照本单从上到下走，不要即兴改参数。创建本运行单不授权 provider 调用。**

- 决策槽：`20260815`（周六，非交易日——故意不占真实交易日）
- 形状：四条已审 v0.2.0 Stage-1 模板全上，Web 与 X 两条 lane 都跑
- 花费上限：Tavily 4 + DeepSeek 4 + xAI 4 = **12 次实际调用**
- 重试：0；任一付费步骤中断后先停，不得自行重跑
- 目的：验证 Tavily `days=7` 是否减少窗口外旧闻，并按冻结指标取得三选一裁决
- 本单只在 `D:\cnhea\Codex\worktrees\000e\Stock` 执行；不碰主树
- 固定解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`

---

## 硬时间窗：北京时间 08-15（周六）21:30 之前

`--generated-at` 必须早于 `2026-08-15T13:30:00+00:00`（纽约 09:30，北京/新加坡 21:30）。过了这个点，两个 fetch runner 都会报 `generated_at must be before the decision open`，该槽随即废止。

选择一个比预计完成抓取时刻晚几分钟、但严格早于上述 cutoff 的 UTC 时间。所有命令里的 `<GENERATED_AT>` 必须使用同一个值；runner 会检查来源 `fetched_at <= generated_at`。

例：北京时间 10:00 开跑，可使用 `2026-08-15T02:30:00+00:00`。不要照抄示例而忽略实际开跑时间。

---

## 0. 开跑前检查（全部离线、不花钱）

```powershell
Set-Location -LiteralPath "D:\cnhea\Codex\worktrees\000e\Stock"

# a) 0815 的正式槽和 assessment 必须全部为空；任何 True/输出都先停。
Get-ChildItem state\us_short -Filter "*20260815*"
Test-Path docs\us_short_soft_discovery_query_quality_probe_assessment_20260815.json

# b) 必须是独立审查通过后的干净工作树。
git status --short
git log --oneline -1

# c) 只看三个 key 是否存在，绝不打印值。
@("TAVILY_API_KEY","DEEPSEEK_API_KEY","XAI_API_KEY") | ForEach-Object {
    "{0}: {1}" -f $_, $(if ([Environment]::GetEnvironmentVariable($_)) {"present"} else {"MISSING"})
}

# d) 0815 packet/schema/runbook 都必须已经在本工作树。
Test-Path docs\us_short_soft_discovery_query_quality_probe_packet_20260815.json
Test-Path schemas\us_short_soft_discovery_query_quality_probe_packet_20260815.schema.json
Test-Path docs\us_short_soft_discovery_probe_20260815_runbook.md
```

全部通过后仍需用户对**这一次** Web+X 探针作新鲜、明确授权；“建立 0815 槽”本身不是付费授权。

---

## 1. 建 parent plan（离线、不花钱）

```powershell
& "C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe" -m runners.us_short_llm_theme_discovery_build_parent_plan `
  --decision-date 20260815 `
  --generated-at "<GENERATED_AT>"
```

记录打印出的 `artifact_path`，形如：

```text
state/us_short/us_short_llm_theme_discovery_query_plan_parent_20260815_<64位哈希>.json
```

该 builder 只读已审 policy，不接受自由查询。若报 `decision date is not the independent 20260815 probe packet slot`，立即停手核对代码态和日期。

---

## 2. Web lane（第一次付费：Tavily + DeepSeek）

```powershell
& "C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe" -m runners.us_short_llm_theme_discovery_fetch_web `
  --parent-plan "<第 1 步 artifact_path>" `
  --expected-decision-date 20260815 `
  --generated-at "<GENERATED_AT>" `
  --live `
  --confirm-user-authorization
```

跑完先读正式产物与 plan 账本：

```powershell
Get-Content state\us_short\us_short_llm_theme_discovery_web_20260815.json | ConvertFrom-Json |
  Select-Object -ExpandProperty themes | Measure-Object | Select-Object Count
Get-Content state\us_short\us_short_llm_theme_discovery_plan_web_20260815_budget.json

$webReceipt = Get-Content state\us_short\us_short_llm_theme_discovery_web_20260815_receipt.json | ConvertFrom-Json
$webReceipt.drop_ledger | Group-Object reason | Sort-Object Name | Select-Object Name, Count
```

`published_at_outside_decision_week` 是否从 20260809 的 33 条显著下降，是验证 Tavily 是否实际采纳 `days=7` 的诊断；它不是新增阈值，也不替代 packet 的正式质量门。

这是唯一中场停点。若 Web 报错、账本不完整、全部内容明显不可用，停止并回报，不得自行重跑或继续花 X 的钱。

---

## 3. X lane（第二次付费：xAI）

```powershell
& "C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe" -m runners.us_short_llm_theme_discovery_fetch_x `
  --parent-plan "<第 1 步 artifact_path>" `
  --expected-decision-date 20260815 `
  --generated-at "<GENERATED_AT>" `
  --live `
  --confirm-user-authorization
```

完整输出名必须是：

- `state/us_short/us_short_llm_theme_discovery_x_20260815.json`
- `state/us_short/us_short_llm_theme_discovery_x_20260815_receipt.json`
- `state/us_short/us_short_llm_theme_discovery_plan_xai_20260815_budget.json`

---

## 4. 预检裁决（离线、不写 assessment）

```powershell
& "C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe" -m runners.us_short_soft_discovery_query_quality_probe_assess `
  --packet-path docs\us_short_soft_discovery_query_quality_probe_packet_20260815.json `
  --generated-at "<GENERATED_AT>" `
  --preflight-only
```

`--packet-path` 必须显式传入。assessor 默认仍是历史 20260730 packet；省略参数会用错契约。

---

## 5. 落定不可变裁决（离线、只写一次）

确认预检输入和输出无误后，去掉 `--preflight-only`：

```powershell
& "C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe" -m runners.us_short_soft_discovery_query_quality_probe_assess `
  --packet-path docs\us_short_soft_discovery_query_quality_probe_packet_20260815.json `
  --generated-at "<GENERATED_AT>"
```

唯一合法 assessment 路径是 `docs/us_short_soft_discovery_query_quality_probe_assessment_20260815.json`。裁决仍只可能是：

- `pass_to_query_planner_implementation`
- `revise_stage1_templates_before_planner`
- `provider_or_execution_inconclusive_do_not_grade_templates`

---

## 中止条件

| 现象 | 处置 |
|---|---|
| 任一步报 `formal decision slot is already occupied` | 停止；不得删除槽文件后重来 |
| 任一步报 `not bound to the reviewed policy` | 停止；重跑不能修复 plan/policy 漂移 |
| Web 或 X 付费步骤中断 | 停止；先审账本与已付调用，不得自行重试 |
| 预算、查询数、槽名或 provider scope 与 packet 不同 | 停止；不得临场改 packet 或命令 |
| `generated_at must be before the decision open` | 0815 槽废止；下一非交易槽是 08-22（六）/08-23（日），必须另起改期刀 |

任何情况下都不要删除或覆盖 20260809/20260815 冻结件，不要添加 `--query`，不要改阈值、metric const、预算或 decision date 来“再试一次”。

---

## 跑完后的交接材料

只交以下 tracked/结构化材料，不贴 raw provider 响应：

1. 第 4/5 步打印的 JSON 与 verdict。
2. `state/us_short/us_short_llm_theme_discovery_web_20260815_receipt.json`。
3. `state/us_short/us_short_llm_theme_discovery_x_20260815_receipt.json`。
4. `state/us_short/us_short_llm_theme_discovery_plan_web_20260815_budget.json`。
5. `state/us_short/us_short_llm_theme_discovery_plan_xai_20260815_budget.json`。
6. Web drop reason 分组，尤其 `published_at_outside_decision_week`。

raw 只留在 gitignored 的 `provider_samples/us_short_llm_theme_discovery_fetch_web` 与 `provider_samples/us_short_llm_theme_discovery_fetch_x`。

裁决 PASS 后仍需先独立审查本次冻结证据，再单独实施 4d-iii；建槽或抓取成功均不会自动启用 `theme_soft_boost_enabled`、Top15、席位、确认器或生命周期效果。
