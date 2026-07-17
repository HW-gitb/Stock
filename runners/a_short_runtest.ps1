# Disposable A-short full-flow runtest launcher.
#
# This is intentionally separate from weekly_screening.ps1.  It executes that
# complete official entry only inside a fresh detached clone, with EGS cache
# reads/writes disabled.  It never writes a formal result in the source repo.

[CmdletBinding()]
param(
    [ValidatePattern('^(\d{8})?$')]
    [string]$AsOf = $null,
    [string]$Account = $null,
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$CapsuleRoot = 'D:\cnhea\Stock_runtest_private',
    [string]$Commit = 'HEAD',
    [string]$RunId = '',
    [string]$PythonExe = '',
    [switch]$ConfirmRuntest
)

$ErrorActionPreference = 'Stop'

if (-not $ConfirmRuntest) {
    throw 'Runtest is intentionally explicit. Re-run with -ConfirmRuntest; this creates a new isolated capsule and may call data providers.'
}

$SourceRoot = (Resolve-Path -LiteralPath $SourceRoot).Path
$Manager = Join-Path $SourceRoot 'runners\runtest_capsule.py'
if (-not (Test-Path -LiteralPath $Manager -PathType Leaf)) {
    throw "Missing runtest capsule manager: $Manager"
}
. (Join-Path $SourceRoot '.tools\Resolve-AshortPython.ps1')
$PythonExe = Resolve-AshortPython -Requested $PythonExe
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "a_short_$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))_$PID"
}

$CopyArgs = @()
if (-not [string]::IsNullOrWhiteSpace($Account)) {
    $Account = (Resolve-Path -LiteralPath $Account).Path
    if (-not (Test-Path -LiteralPath $Account -PathType Leaf)) {
        throw "-Account must be a regular input file: $Account"
    }
    $CopyArgs += @('--copy-input', "a_short_account=$Account")
}

$CreateArgs = @(
    $Manager, '--capsule-root', $CapsuleRoot, 'create',
    '--source-root', $SourceRoot, '--market', 'a_short', '--run-id', $RunId, '--commit', $Commit
) + $CopyArgs
$CreateOutput = & $PythonExe @CreateArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$Created = ($CreateOutput | Select-Object -Last 1 | ConvertFrom-Json)
$Capsule = [string]$Created.capsule
$CapsuleRepo = [string]$Created.repo

$ActivateOutput = & $PythonExe $Manager '--capsule-root' $CapsuleRoot 'activate' '--capsule' $Capsule
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$PreviousEnvironment = @{}
$CapsuleTemp = Join-Path $Capsule 'tmp'
New-Item -ItemType Directory -Force -Path $CapsuleTemp | Out-Null
foreach ($Name in @('TEMP', 'TMP', 'XDG_CACHE_HOME', 'PYTHONPYCACHEPREFIX')) {
    $PreviousEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
    [Environment]::SetEnvironmentVariable($Name, $CapsuleTemp, 'Process')
}

$RunExitCode = 1
try {
    $Worker = Join-Path $CapsuleRepo 'runners\weekly_screening.ps1'
    # A PowerShell script worker requires a hashtable splat.  An array splat
    # passes these tokens positionally, so the forced runtest gates can bind
    # to the wrong weekly-screening parameters.
    $WorkerParams = @{
        L3Mode = 'today'
        CachePolicy = 'disabled'
        PythonExe = $PythonExe
    }
    if (-not [string]::IsNullOrWhiteSpace($AsOf)) { $WorkerParams.AsOf = $AsOf }
    if (-not [string]::IsNullOrWhiteSpace($Account)) {
        $WorkerParams.Account = Join-Path $Capsule 'private_inputs\a_short_account'
    }
    Write-Host "[RUNTEST] A-short full flow is isolated in $Capsule" -ForegroundColor Cyan
    Push-Location $CapsuleRepo
    try {
        & $Worker @WorkerParams
        $RunExitCode = if ($null -eq $LASTEXITCODE) { 1 } else { [int]$LASTEXITCODE }
    } finally {
        Pop-Location
    }
} catch {
    Write-Host "[FATAL] runtest worker threw: $($_.Exception.Message)" -ForegroundColor Red
    $RunExitCode = 1
} finally {
    foreach ($Name in $PreviousEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($Name, $PreviousEnvironment[$Name], 'Process')
    }
    & $PythonExe $Manager '--capsule-root' $CapsuleRoot 'finish' '--capsule' $Capsule '--exit-code' $RunExitCode
    if ($LASTEXITCODE -ne 0) { $RunExitCode = 2 }
}

if ($RunExitCode -eq 0) {
    Write-Host "[RUNTEST] completed; results remain only in $Capsule" -ForegroundColor Green
} else {
    Write-Host "[RUNTEST] failed; capsule retained for inspection: $Capsule" -ForegroundColor Red
}
exit $RunExitCode
