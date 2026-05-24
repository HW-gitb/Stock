# weekly_screening.ps1 — 周五实盘选股 + 数据保险一键脚本
#
# 顺序：
#   1) A-EGS\egs_main.py          (主选股；产 data_health.json by Codex layer)
#   2) runners\data_canary.py     (旁路跨源对账；sina 默认，VPN-agnostic)
#
# 设计约束：
# - canary 在 egs_main 失败时不跑（拿不到当次 candidates，对账无意义）
# - canary 自身失败不影响整体 exit code（旁路约束：不阻断选股）
# - 整体 exit code 取 egs_main 的 exit code
#
# Usage:
#   .\runners\weekly_screening.ps1                                   # as-of = 今天
#   .\runners\weekly_screening.ps1 -AsOf 20260522
#   .\runners\weekly_screening.ps1 -AsOf 20260522 -CanarySource em
#   .\runners\weekly_screening.ps1 -PythonExe C:\Path\To\python.exe   # python 不在 PATH 时
#   .\runners\weekly_screening.ps1 -SkipCanary                        # 只跑选股

param(
    [ValidatePattern('^\d{8}$')]
    [string]$AsOf = (Get-Date -Format 'yyyyMMdd'),
    [ValidateSet('sina', 'em')]
    [string]$CanarySource = 'sina',
    [string]$PythonExe = 'python',
    [switch]$SkipCanary
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
Set-Location $ProjectRoot

Write-Host "=== Weekly screening pipeline ===" -ForegroundColor Cyan
Write-Host "as-of:         $AsOf"
Write-Host "canary source: $CanarySource"
Write-Host "skip canary:   $SkipCanary"
Write-Host ""

# --- Stage 1: egs_main ---
Write-Host "[1/2] Running A-EGS\egs_main.py --as-of $AsOf ..." -ForegroundColor Yellow
& $PythonExe A-EGS\egs_main.py --as-of $AsOf
$EgsExitCode = $LASTEXITCODE
if ($null -eq $EgsExitCode) { $EgsExitCode = 1 }

if ($EgsExitCode -ne 0) {
    Write-Host ""
    Write-Host "[SKIP] egs_main exit $EgsExitCode -> skipping canary (no fresh candidates to reconcile)" -ForegroundColor Red
    exit $EgsExitCode
}

# --- Stage 2: data_canary ---
if ($SkipCanary) {
    Write-Host ""
    Write-Host "[2/2] -SkipCanary set, canary not run" -ForegroundColor DarkGray
    exit 0
}

Write-Host ""
Write-Host "[2/2] Running runners\data_canary.py --as-of $AsOf --source $CanarySource ..." -ForegroundColor Yellow
& $PythonExe runners\data_canary.py --as-of $AsOf --source $CanarySource
$CanaryExitCode = $LASTEXITCODE
if ($null -eq $CanaryExitCode) { $CanaryExitCode = 1 }

if ($CanaryExitCode -ne 0) {
    # canary 本身设计为永远 exit 0；非 0 说明 Python 进程崩了，不是数据问题
    # 仍然不让它影响主流程退出码（旁路约束）
    Write-Host "[WARN] canary process exit $CanaryExitCode (unexpected; check logs/data_canary_$AsOf.json)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Pipeline done ===" -ForegroundColor Cyan
exit 0
