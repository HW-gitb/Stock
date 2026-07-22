# us_short_weekly_capstone.ps1 — US-short 周度一键 capstone 启动器
#
# 目的：把 runners\us_short_weekly_capstone.py 的固定参数封进一条命令，操作方每周不用重打长命令。
# 这是一个薄封装：不重述任何选股/PIT 语义(唯一权威仍是 runner + 各 stage),只负责填参数 + 转发。
#
# 默认行为 = dry-run(不联网、不需要真实文件),打印本周计划(含决策日 + 每个 stage 的 gated/离线 + 输入输出路径)。
# 真跑(联网 provider fetch)必须显式 -Live,且按 ship-gate 设计仍是多步授权(先 dry-run 看边界 → -PrepareBudget 算预算
# → 独立授权该精确预算 → -Live -Pass2Budget N),脚本不替你一键授权真钱路径。
#
# 参数每次自动/固定：
#   --now-et            省略 -NowEt = 自动取「当前 ET 墙钟」(UTC→America/Eastern,DST 自适应)。
#                       周末/周一盘前跑都收敛到即将到来的决策日;若跑在美股盘中(死区)runner fail-closed 拒跑。
#   --private-root      不传 = 用 runner 默认 state/us_short → 报告落
#                       <repo>\state\us_short\weekly_private\<决策日>\weekly_report.md(从 D:\cnhea\Stock 跑即该绝对路径)。
#   --batch4-template-path / --account-state-path
#                       默认指向 gitignored 私密输入位置 state\us_short\weekly_private\_run_inputs\(C3-safe,不在按决策日归档的目录内)。
#                       账户状态含真实持仓 → 必私密;其 as_of 必须 == 本周决策日(先 dry-run 看决策日,再用
#                       runners\us_short_account_state_from_manual_tables.py --as-of <决策日> 生成到该路径),否则 -Live 会被拒。
#
# Usage:
#   .\runners\us_short_weekly_capstone.ps1                          # dry-run:打印本周计划(默认,安全)
#   .\runners\us_short_weekly_capstone.ps1 -NowEt 2026-07-20T08:00:00   # 覆盖决策时刻(naive ET)
#   .\runners\us_short_weekly_capstone.ps1 -PrepareBudget -MomentumTopK 200  # 跑上游漏斗算 Pass2 精确预算(联网、不出报告)
#   .\runners\us_short_weekly_capstone.ps1 -Live -MomentumTopK 200 -Pass2Budget 137   # 真跑(需已独立授权 K + 预算)
#   .\runners\us_short_weekly_capstone.ps1 -PythonExe C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe   # 可省略；传值仅校验固定主 Python
#   .\runners\us_short_weekly_capstone.ps1 -PrivateRoot D:\external\private   # 覆盖私密输出根(仓外亦可)
#   .\runners\us_short_weekly_capstone.ps1 -ExtraArgs '--provider-pace-seconds','2.0'   # 透传其余 runner 参数
#
# 约束：
# - 默认 dry-run;-Live 与 -PrepareBudget 互斥。
# - -Live / -PrepareBudget 前会检查 batch4 模板 + 账户状态文件存在,缺则早失败给出补齐指引(dry-run 不检查、也不需要)。
# - -Live 生产跑要求已授权的 -MomentumTopK(1..250) 与正整数 -Pass2Budget(先 -PrepareBudget 得预算再独立授权),脚本先行提醒、最终由 runner 强制。
# - 脚本不改选股逻辑、不 push、不碰真钱边界;真跑是否放行由 runner 的 provider_health/授权门决定。

[CmdletBinding()]
param(
    [string]$NowEt = "",
    [string]$PrivateRoot = "",
    [string]$BatchTemplate = "",
    [string]$AccountState = "",
    [switch]$Live,
    [switch]$PrepareBudget,
    [int]$Pass2Budget = 0,
    [int]$MomentumTopK = 0,
    [string]$PythonExe = "",
    [string[]]$ExtraArgs = @()
)

$ErrorActionPreference = "Stop"

# repo root = 本脚本(runners\)的上一级
$repo = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $repo "runners\us_short_weekly_capstone.py"
if (-not (Test-Path $runner)) {
    throw "找不到 capstone runner: $runner"
}
. (Join-Path $repo ".tools\Resolve-AshortPython.ps1")
$PythonExe = Resolve-AshortPython -Requested $PythonExe

if ($Live -and $PrepareBudget) {
    throw "-Live 与 -PrepareBudget 互斥:先 -PrepareBudget 算预算并独立授权,再单独 -Live -Pass2Budget N。"
}

# --now-et:省略则取当前 ET 墙钟(DST 自适应);Windows 时区 id "Eastern Standard Time" 含夏令时切换。
if ([string]::IsNullOrWhiteSpace($NowEt)) {
    $etZone = [System.TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
    $nowEtLocal = [System.TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $etZone)
    $NowEt = $nowEtLocal.ToString("yyyy-MM-ddTHH:mm:ss")
    Write-Host "[now-et] 自动取当前 ET = $NowEt" -ForegroundColor DarkGray
}

# 固定私密输入位置(可覆盖)。默认落 gitignored state\us_short\weekly_private\_run_inputs\(C3-safe)。
$runInputs = Join-Path $repo "state\us_short\weekly_private\_run_inputs"
if ([string]::IsNullOrWhiteSpace($BatchTemplate)) {
    $BatchTemplate = Join-Path $runInputs "batch4_action_template.json"
}
if ([string]::IsNullOrWhiteSpace($AccountState)) {
    $AccountState = Join-Path $runInputs "us_short_account_state.json"
}

# 真跑/预算跑才需要真实输入文件;dry-run 不读它们。
if ($Live -or $PrepareBudget) {
    $missing = @()
    if (-not (Test-Path $BatchTemplate)) { $missing += $BatchTemplate }
    if (-not (Test-Path $AccountState))  { $missing += $AccountState }
    if ($missing.Count -gt 0) {
        throw ("非 dry-run 需要真实输入文件,但缺失:`n  " + ($missing -join "`n  ") +
               "`n补齐后重跑:账户状态用 runners\us_short_account_state_from_manual_tables.py --as-of <决策日> 生成(as_of 必须==本周决策日,先 dry-run 看决策日)。")
    }
    if ($Live -and ($MomentumTopK -le 0 -or $Pass2Budget -le 0)) {
        Write-Host "[提醒] -Live 生产跑要求已授权的 -MomentumTopK(1..250) 与正整数 -Pass2Budget;缺则 runner 会拒。先 -PrepareBudget 得预算再独立授权。" -ForegroundColor Yellow
    }
}

# 组装参数
$cliArgs = @(
    $runner,
    "--now-et", $NowEt,
    "--batch4-template-path", $BatchTemplate,
    "--account-state-path", $AccountState
)
if (-not [string]::IsNullOrWhiteSpace($PrivateRoot)) { $cliArgs += @("--private-root", $PrivateRoot) }
if ($MomentumTopK -gt 0) { $cliArgs += @("--momentum-top-k", "$MomentumTopK") }
if ($Pass2Budget -gt 0)  { $cliArgs += @("--pass2-call-budget", "$Pass2Budget") }
if ($PrepareBudget)      { $cliArgs += "--prepare-pass2-budget" }
# -Live 自动带上 --confirm-user-authorization(= 本次 per-execution 授权,SR-PROVIDER-001);dry-run 是默认,操作方须自觉打 -Live 才联网真跑,不会被无意触发。
if ($Live)               { $cliArgs += @("--live", "--confirm-user-authorization") }
if ($ExtraArgs.Count -gt 0) { $cliArgs += $ExtraArgs }

$mode = if ($Live) { "LIVE(联网真跑)" } elseif ($PrepareBudget) { "PREPARE-BUDGET(联网算预算)" } else { "DRY-RUN(默认,不联网)" }
Write-Host "[模式] $mode" -ForegroundColor Cyan
Write-Host "[命令] $PythonExe $($cliArgs -join ' ')" -ForegroundColor DarkGray

& $PythonExe @cliArgs
exit $LASTEXITCODE
