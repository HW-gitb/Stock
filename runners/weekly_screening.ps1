# weekly_screening.ps1 — 周五实盘选股 + 数据保险一键脚本
#
# 顺序：
#   1) A-EGS\egs_main.py                       (主选股；产 data_health.json by Codex layer)
#   2) runners\data_canary.py                  (旁路跨源对账；sina 默认，VPN-agnostic)
#   3) runners\forward_tracker.py              (Phase 3.5 实盘 forward 累计；不影响主流程)
#   4) runners\a_short_semantic_risk_summary.py(语义风险 advisory Step1：cninfo 官方结构化层；
#                                               watch pool = 当次 EGS analysis_input 候选；
#                                               Step2 web_llm:本脚本不做(Stage-4 过渡 sidecar);产出路径见契约 §web_llm 产出路径)
#
# 设计约束：
# - canary / tracker / semantic 在 egs_main 失败时不跑（拿不到当次 candidates，意义为零）
# - canary / tracker / semantic 自身失败不影响整体 exit code（旁路约束：不阻断选股）
# - semantic 是 advisory-only:cninfo 取数失败/反爬绝不阻断周报;落 research 非生产 lane,
#   绝不进 result/a_short、不进 production scoring/decision/veto
# - 整体 exit code 取 egs_main 的 exit code
#
# Usage:
#   .\runners\weekly_screening.ps1                                   # as-of = 今天
#   .\runners\weekly_screening.ps1 -AsOf 20260522
#   .\runners\weekly_screening.ps1 -AsOf 20260522 -CanarySource em
#   .\runners\weekly_screening.ps1 -PythonExe C:\Path\To\python.exe   # python 不在 PATH 时
#   .\runners\weekly_screening.ps1 -SkipCanary                        # 只跑选股
#   .\runners\weekly_screening.ps1 -SkipTracker                       # 不跑 forward tracker capture
#   .\runners\weekly_screening.ps1 -SkipSemanticRisk                  # 不跑语义风险 advisory Step1
#   .\runners\weekly_screening.ps1 -AsOf 20260522 -L3Mode neutralize  # historical replay guard

param(
    [ValidatePattern('^\d{8}$')]
    [string]$AsOf = (Get-Date -Format 'yyyyMMdd'),
    [ValidateSet('sina', 'em')]
    [string]$CanarySource = 'sina',
    [ValidateSet('pit', 'today', 'neutralize')]
    [string]$L3Mode = $null,
    [string]$PythonExe = 'python',
    [switch]$AllowHistoricalOverwrite,
    [switch]$SkipCanary,
    [switch]$SkipTracker,
    [switch]$SkipSemanticRisk
)

# We rely on $LASTEXITCODE from native exes (python.exe), not PowerShell
# cmdlet error handling, so the default $ErrorActionPreference is fine —
# explicit override removed (it was cosmetic and misled readers into
# thinking it affected the Python subprocess exit semantics).
#
# $PSScriptRoot is the directory of THIS .ps1 file (runners/), so the
# project root is one level up. If this script is ever moved, update
# both the path math and the python invocations below.
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $ProjectRoot 'A-EGS\egs_main.py') -PathType Leaf)) {
    Write-Host "[FATAL] expected A-EGS\egs_main.py (as a file) under $ProjectRoot." -ForegroundColor Red
    exit 1
}
if (-not (Get-Command $PythonExe -ErrorAction SilentlyContinue)) {
    Write-Host "[FATAL] Python executable not found: $PythonExe" -ForegroundColor Red
    Write-Host "        Pass -PythonExe C:\Path\To\python.exe or add python to PATH." -ForegroundColor Red
    exit 1
}

$RunDate = Get-Date -Format 'yyyyMMdd'
$IsHistoricalAsOf = $AsOf -ne $RunDate
$EffectiveL3Mode = $L3Mode

if ([string]::IsNullOrWhiteSpace($EffectiveL3Mode)) {
    if ($IsHistoricalAsOf) {
        Write-Host "[FATAL] Historical -AsOf $AsOf is not the current run date $RunDate." -ForegroundColor Red
        Write-Host "        Pass -L3Mode pit or -L3Mode neutralize explicitly; default --l3-mode=today is blocked for historical official-output runs." -ForegroundColor Red
        exit 1
    }
    $EffectiveL3Mode = 'today'
}

if ($IsHistoricalAsOf -and $EffectiveL3Mode -eq 'today') {
    Write-Host "[FATAL] Historical -AsOf $AsOf cannot run with -L3Mode today." -ForegroundColor Red
    Write-Host "        Use -L3Mode pit for a strict PIT snapshot, or -L3Mode neutralize for an L3-neutral replay." -ForegroundColor Red
    exit 1
}

$ExistingOfficialOutputs = @()
$OfficialResultDir = Join-Path $ProjectRoot "result\a_short\$AsOf"
if (Test-Path $OfficialResultDir) {
    $ExistingOfficialOutputs += $OfficialResultDir
}
$EgsRootDir = Join-Path $ProjectRoot 'A-EGS'
$EgsResultDir = Join-Path $EgsRootDir 'Result'
@(
    (Join-Path $EgsResultDir "egs_tier1_$AsOf.csv"),
    (Join-Path $EgsResultDir "egs_full_$AsOf.csv"),
    # egs_main.py defaults xlsx output to A-EGS\ unless CONF["xlsx_dir"] is set.
    (Join-Path $EgsRootDir "egs_tier1_$AsOf.xlsx"),
    (Join-Path $EgsResultDir "egs_tier1_$AsOf.xlsx")
) | ForEach-Object {
    $Path = $_
    if (Test-Path $Path) {
        $ExistingOfficialOutputs += $Path
    }
}

if ($IsHistoricalAsOf -and $ExistingOfficialOutputs.Count -gt 0 -and -not $AllowHistoricalOverwrite) {
    Write-Host "[FATAL] Historical -AsOf $AsOf would overwrite existing official output(s):" -ForegroundColor Red
    foreach ($Path in $ExistingOfficialOutputs) {
        Write-Host "        $Path" -ForegroundColor Red
    }
    Write-Host "        Re-run only after reviewing those outputs, and pass -AllowHistoricalOverwrite if the overwrite is intentional." -ForegroundColor Red
    exit 1
}

if ($IsHistoricalAsOf -and $AllowHistoricalOverwrite) {
    Write-Host "[WARN] Historical official-output overwrite explicitly allowed for $AsOf." -ForegroundColor Yellow
}

Set-Location $ProjectRoot

Write-Host "=== Weekly screening pipeline ===" -ForegroundColor Cyan
Write-Host "as-of:         $AsOf"
Write-Host "run date:      $RunDate"
Write-Host "historical:    $IsHistoricalAsOf"
Write-Host "l3 mode:       $EffectiveL3Mode"
Write-Host "canary source: $CanarySource"
Write-Host "skip canary:   $SkipCanary"
Write-Host "skip tracker:  $SkipTracker"
Write-Host "skip semantic: $SkipSemanticRisk"
Write-Host ""

# --- Stage 1: egs_main ---
$EgsArgs = @('A-EGS\egs_main.py', '--as-of', $AsOf, '--l3-mode', $EffectiveL3Mode)
if ($EffectiveL3Mode -eq 'pit') {
    $EgsArgs += '--l3-pit-strict'
}

Write-Host "[1/4] Running $PythonExe $($EgsArgs -join ' ') ..." -ForegroundColor Yellow
& $PythonExe @EgsArgs
$EgsExitCode = $LASTEXITCODE
if ($null -eq $EgsExitCode) { $EgsExitCode = 1 }

if ($EgsExitCode -ne 0) {
    Write-Host ""
    Write-Host "[SKIP] egs_main exit $EgsExitCode -> skipping canary + tracker + semantic (no fresh candidates)" -ForegroundColor Red
    exit $EgsExitCode
}

# --- Stage 2: data_canary ---
if ($SkipCanary) {
    Write-Host ""
    Write-Host "[2/4] -SkipCanary set, canary not run" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "[2/4] Running runners\data_canary.py --as-of $AsOf --source $CanarySource ..." -ForegroundColor Yellow
    & $PythonExe runners\data_canary.py --as-of $AsOf --source $CanarySource
    $CanaryExitCode = $LASTEXITCODE
    if ($null -eq $CanaryExitCode) { $CanaryExitCode = 1 }

    $CanaryLog = Join-Path $ProjectRoot "logs\data_canary_$AsOf.json"
    if (Test-Path $CanaryLog) {
        try {
            $CanaryPayload = Get-Content -Raw -Encoding UTF8 $CanaryLog | ConvertFrom-Json
            Write-Host "[ADVISORY] data_canary status=$($CanaryPayload.status); sidecar only, not a data-pass and not a ship-gate signal. Log: $CanaryLog" -ForegroundColor Yellow
        } catch {
            Write-Host "[ADVISORY] data_canary log exists but could not be parsed; sidecar only, not a data-pass and not a ship-gate signal. Log: $CanaryLog" -ForegroundColor Yellow
        }
    } else {
        Write-Host "[ADVISORY] data_canary log not found; sidecar only, not a data-pass and not a ship-gate signal." -ForegroundColor Yellow
    }

    if ($CanaryExitCode -ne 0) {
        # canary 本身设计为永远 exit 0；非 0 说明 Python 进程崩了，不是数据问题
        # 仍然不让它影响主流程退出码（旁路约束）
        Write-Host "[WARN] canary process exit $CanaryExitCode (unexpected; check logs/data_canary_$AsOf.json)" -ForegroundColor Yellow
    }
}

# --- Stage 3: forward_tracker capture ---
if ($SkipTracker) {
    Write-Host ""
    Write-Host "[3/4] -SkipTracker set, forward tracker not run" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "[3/4] Running runners\forward_tracker.py capture --as-of $AsOf ..." -ForegroundColor Yellow
    & $PythonExe runners\forward_tracker.py capture --as-of $AsOf
    $TrackerExitCode = $LASTEXITCODE
    if ($null -eq $TrackerExitCode) { $TrackerExitCode = 1 }

    if ($TrackerExitCode -ne 0) {
        # tracker capture 失败不影响主流程退出码（旁路约束）。
        # 失败原因通常是 analysis_input.json 缺失或 Python 异常，不是数据问题。
        Write-Host "[WARN] forward_tracker exit $TrackerExitCode (check logs/forward_tracker.csv)" -ForegroundColor Yellow
    }
}

# --- Stage 4: semantic-risk advisory sidecar (过渡;Step1 headless cninfo official only;web run-path 见契约 §web_llm 产出路径) ---
# 旁路约束(同 canary/tracker):advisory-only,失败绝不阻断周报;落 research 非生产 lane(禁 result/a_short);
# watch pool = 当次 EGS analysis_input 候选(runner 内部再过主板 Top15)。
# 本 Stage-4 = 过渡 standalone summary sidecar(只产官方结构化层)。web 产出路径(当前/过渡)见契约 §web_llm 产出路径;Slice 3 把本入口串到 M6.7 pipeline。
if ($SkipSemanticRisk) {
    Write-Host ""
    Write-Host "[4/4] -SkipSemanticRisk set, semantic-risk advisory not run" -ForegroundColor DarkGray
} else {
    Write-Host ""
    $SemAnalysisInput = Join-Path $ProjectRoot "result\a_short\$AsOf\analysis_input.json"
    if (-not (Test-Path $SemAnalysisInput)) {
        Write-Host "[WARN] semantic-risk skipped: analysis_input not found at $SemAnalysisInput (advisory sidecar, weekly not blocked)" -ForegroundColor Yellow
    } else {
        $SemOut = Join-Path $ProjectRoot "research\results\a_short\semantic_risk_$AsOf\summary.json"
        Write-Host "[4/4] Running runners\a_short_semantic_risk_summary.py --as-of $AsOf --analysis-input <egs> ..." -ForegroundColor Yellow
        & $PythonExe runners\a_short_semantic_risk_summary.py --as-of $AsOf --analysis-input $SemAnalysisInput --out $SemOut --confirm-fetch-authorized
        $SemExitCode = $LASTEXITCODE
        if ($null -eq $SemExitCode) { $SemExitCode = 1 }

        if ($SemExitCode -ne 0) {
            # cninfo 取数失败/反爬/anti-scrape 不影响主流程退出码（旁路约束:advisory 绝不阻断选股）
            Write-Host "[WARN] semantic-risk exit $SemExitCode (advisory sidecar; cninfo fetch/anti-scrape failure does NOT block the weekly)" -ForegroundColor Yellow
        } else {
            Write-Host "[ADVISORY] semantic-risk official_structured summary -> $SemOut. Transitional standalone sidecar; web_llm run path: see contract docs/a_short_semantic_risk_contract.md §web_llm 产出路径. advisory-only, not a veto/ship-gate." -ForegroundColor Yellow
        }
    }
}

Write-Host ""
Write-Host "=== Pipeline done ===" -ForegroundColor Cyan
exit 0
