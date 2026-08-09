# US-short 软发现「查询质量探针」20260809 运行单

**这是唯一一次要花钱的运行。照本单从上到下走，不要即兴改参数。**

- 决策槽：`20260809`（周日，非交易日 —— 故意不占真实交易日）
- 形状（用户 2026-08-03 裁定）：四条 Stage-1 模板全上、Web 与 X 两条 lane 都跑
- 花费上限：Tavily 4 + DeepSeek 4 + xAI 4 = **12 次实际调用**
- 需要你亲手授权的只有 **两步**（第 2、第 3 步），其余全部离线不花钱
- 全部命令在 `D:\cnhea\Stock` 下跑，解释器固定 `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`

---

## ⏰ 硬时间窗：北京时间 08-09（周日）**21:30 之前**

`--generated-at` 必须**早于** `2026-08-09T13:30:00+00:00`（= 纽约 09:30 = 北京 21:30）。过了这个点，两个 fetch runner 都会抛 `generated_at must be before the decision open`，这一枪当天就打不了了（顺延的代价见文末中止条件表）。

**`--generated-at` 怎么填**：填一个**比你开始跑的时刻晚几分钟、但早于 21:30 北京时间**的 UTC 时间戳。原因是 runner 会校验 `fetched_at <= generated_at`——如果填成「此刻」，而抓取花了 30 秒，就会因为 `fetched_at cannot be after generated_at` 失败。

例：北京时间 10:00 开跑 → 填 `2026-08-09T02:30:00+00:00`（= 北京 10:30）。**下面所有命令里的 `<GENERATED_AT>` 都填同一个值。**

---

## 0. 开跑前的检查（5 分钟，全部不花钱）

```powershell
cd D:\cnhea\Stock

# a) 20260809 的槽必须是空的。有任何输出就停下来查，不要继续。
Get-ChildItem state\us_short -Filter "*20260809*"

# b) 代码自审查通过之日起没动过
git status --short
git log --oneline -1

# c) 三个 key 都在（只看有没有，不要打印内容）
@("TAVILY_API_KEY","DEEPSEEK_API_KEY","XAI_API_KEY") | ForEach-Object {
    "{0}: {1}" -f $_, $(if ([Environment]::GetEnvironmentVariable($_)) {"present"} else {"MISSING"})
}

# d) 改期件必须已经合进这棵树。False 就先合，否则第 1 步会报 20260808 那句。
Test-Path docs\us_short_soft_discovery_query_quality_probe_packet_20260809.json
```

四项全绿才往下走。

---

## 1. 建计划（不花钱、不联网）

```powershell
& "C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe" -m runners.us_short_llm_theme_discovery_build_parent_plan `
  --decision-date 20260809 `
  --generated-at "<GENERATED_AT>"
```

它会打印一行 JSON，里面有 `artifact_path`。**把那个路径记下来，下面两步要用**，形如：

```
state/us_short/us_short_llm_theme_discovery_query_plan_parent_20260809_<64位哈希>.json
```

这一步只读已审的 v0.2.0 policy，不接受任何自由文本查询。若报 `decision date is not the independent 20260809 probe packet slot`，说明日期打错了。

---

## 2. Web lane（**第一次花钱**：Tavily + DeepSeek）

```powershell
& "C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe" -m runners.us_short_llm_theme_discovery_fetch_web `
  --parent-plan "<第 1 步打印的 artifact_path>" `
  --expected-decision-date 20260809 `
  --generated-at "<GENERATED_AT>" `
  --live `
  --confirm-user-authorization
```

**跑完先看这两样，再决定要不要继续**：

```powershell
Get-Content state\us_short\us_short_llm_theme_discovery_web_20260809.json | ConvertFrom-Json |
  Select-Object -ExpandProperty themes | Measure-Object | Select-Object Count
Get-Content state\us_short\us_short_llm_theme_discovery_plan_web_20260809_budget.json
```

**这是你唯一的中场休息**。如果 web 侧捞回来的全是宏观评论、没有具体公司，那第 3 步的钱可以不花——直接跳到「中止」一节。

---

## 3. X lane（**第二次花钱**：xAI）

```powershell
& "C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe" -m runners.us_short_llm_theme_discovery_fetch_x `
  --parent-plan "<同上，第 1 步那个 artifact_path>" `
  --expected-decision-date 20260809 `
  --generated-at "<GENERATED_AT>" `
  --live `
  --confirm-user-authorization
```

跑完后产物为 `state\us_short\us_short_llm_theme_discovery_x_20260809.json`；对应 receipt 与 plan 级账本的完整文件名见文末「跑完之后」，不要用省略号代替文件名。

---

## 4. 预检裁决（不花钱、不写盘）

```powershell
& "C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe" -m runners.us_short_soft_discovery_query_quality_probe_assess `
  --packet-path docs\us_short_soft_discovery_query_quality_probe_packet_20260809.json `
  --generated-at "<GENERATED_AT>" `
  --preflight-only
```

⚠️ **`--packet-path` 必须显式传**。评估器的默认值是**旧的 20260730 packet**，不传就会拿旧问法去比对，裁决作废。

预检不写盘，只把裁决算出来给你看。

---

## 5. 落定裁决（不花钱，写一次不可变产物）

预检结果符合预期后，去掉 `--preflight-only` 再跑一次：

```powershell
& "C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe" -m runners.us_short_soft_discovery_query_quality_probe_assess `
  --packet-path docs\us_short_soft_discovery_query_quality_probe_packet_20260809.json `
  --generated-at "<GENERATED_AT>"
```

裁决是三选一：`pass_to_query_planner_implementation` / `revise_stage1_templates_before_planner` / `inconclusive`。

---

## 🛑 中止条件：出现下列任一情况，**立刻停手，不要重试**

| 现象 | 为什么不能重试 |
|---|---|
| 任一步报 `formal decision slot is already occupied` | 槽已被占，重试只会再撞一次；先查是谁写的 |
| 任一步报 `not bound to the reviewed policy` | 计划与已审 policy 对不上，重试解决不了 |
| Web 或 X 跑到一半崩了 | **钱可能已经付了一部分**。packet 的门写着 `no_retry_or_rerun_without_new_authorization`——重跑要先看账本 `*_budget.json` 确认已扣多少，再决定 |
| `generated_at must be before the decision open` | 过了 21:30，这个槽就废了。**换决策日不是改个参数就行**——packet / schema / 两个 runner 的常量都把日期钉死在 `20260809`，顺延要另起一刀重挪槽，下一个非交易槽是 08-15（六）/ 08-16（日） |

**任何情况下都不要**：手动删 `state/us_short/` 里的 20260809 文件、改 packet、给命令加 `--query`、或者换个决策日「再试一次」。这些动作会把可复用的证据变成不可复用的。

---

## 跑完之后

把这三样贴回对话，我来收口（写 register / SESSION_LOG / handoff）：

1. 第 4 步或第 5 步打印的那行 JSON（含 `verdict`）
2. `state\us_short\us_short_llm_theme_discovery_web_20260809_receipt.json` 和 `state\us_short\us_short_llm_theme_discovery_x_20260809_receipt.json` 的内容
3. **两个**账本：`state\us_short\us_short_llm_theme_discovery_plan_web_20260809_budget.json` 和 `state\us_short\us_short_llm_theme_discovery_plan_xai_20260809_budget.json`（A4 之后账本是 plan 级、按 `web`/`xai` 两个 provider 分，**不再是** 20260731～0802 那种 tavily/deepseek/xai 三个 per-vendor 账本）

**不要**把原始响应贴进来——它们在 `provider_samples/us_short_llm_theme_discovery_fetch_web|_x` 下，是 gitignored 的付费原文，留在盘上即可。

---

## 这一枪之后

裁决出来才轮到下一步：`pass` → 实现完整一周 Web+X 跑到打分；`revise` → 改模板再来一次（下一个非交易槽）；`inconclusive` → 拿诊断决定改什么。这些都不在本运行单范围内。
