# Disposable US-short full-flow runtest launcher.
#
# It intentionally preserves the existing capstone gates (including -Live's
# per-run confirmation) while rooting every mutable path in a fresh capsule.

[CmdletBinding()]
param(
    [string]$NowEt = '',
    [string]$BatchTemplate = '',
    [string]$AccountState = '',
    [switch]$Live,
    [switch]$PrepareBudget,
    [int]$Pass2Budget = 0,
    [int]$MomentumTopK = 0,
    [string[]]$ExtraArgs = @(),
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$CapsuleRoot = 'D:\cnhea\Stock_runtest_private',
    [string]$Commit = 'HEAD',
    [string]$RunId = '',
    [string]$PythonExe = 'python',
    [switch]$ConfirmRuntest
)

$ErrorActionPreference = 'Stop'

if (-not $ConfirmRuntest) {
    throw 'Runtest is intentionally explicit. Re-run with -ConfirmRuntest; this creates a new isolated capsule and may call providers under the existing US-short gates.'
}
if ($Live -and $PrepareBudget) {
    throw '-Live and -PrepareBudget remain mutually exclusive inside runtest.'
}
if ($ExtraArgs.Count -gt 0) {
    # The ordinary launcher intentionally exposes raw pass-through.  A capsule
    # cannot: argparse accepts the last duplicate, so any forwarded authority
    # or path flag could override the capsule-owned private root, inputs, or
    # live/budget gate.  Add future knobs as explicit audited wrapper params.
    throw 'Runtest does not forward -ExtraArgs; it rejects all raw runner flags so capsule paths and authorization gates cannot be overridden.'
}
if (($Live -or $PrepareBudget) -and ([string]::IsNullOrWhiteSpace($BatchTemplate) -or [string]::IsNullOrWhiteSpace($AccountState))) {
    throw 'A live or budget runtest requires explicit -BatchTemplate and -AccountState so no source-repo private input is reused.'
}

$SourceRoot = (Resolve-Path -LiteralPath $SourceRoot).Path
$Manager = Join-Path $SourceRoot 'runners\runtest_capsule.py'
if (-not (Test-Path -LiteralPath $Manager -PathType Leaf)) {
    throw "Missing runtest capsule manager: $Manager"
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "us_short_$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))_$PID"
}

$CopyArgs = @()
if (-not [string]::IsNullOrWhiteSpace($BatchTemplate)) {
    $BatchTemplate = (Resolve-Path -LiteralPath $BatchTemplate).Path
    $CopyArgs += @('--copy-input', "us_batch_template=$BatchTemplate")
}
if (-not [string]::IsNullOrWhiteSpace($AccountState)) {
    $AccountState = (Resolve-Path -LiteralPath $AccountState).Path
    $CopyArgs += @('--copy-input', "us_account_state=$AccountState")
}

$CreateArgs = @(
    $Manager, '--capsule-root', $CapsuleRoot, 'create',
    '--source-root', $SourceRoot, '--market', 'us_short', '--run-id', $RunId, '--commit', $Commit
) + $CopyArgs
$CreateOutput = & $PythonExe @CreateArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$Created = ($CreateOutput | Select-Object -Last 1 | ConvertFrom-Json)
$Capsule = [string]$Created.capsule
$CapsuleRepo = [string]$Created.repo

& $PythonExe $Manager '--capsule-root' $CapsuleRoot 'activate' '--capsule' $Capsule
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
    $Worker = Join-Path $CapsuleRepo 'runners\us_short_weekly_capstone.ps1'
    $PrivateRoot = Join-Path $Capsule 'private\us_short'
    $WorkerArgs = @('-PrivateRoot', $PrivateRoot, '-PythonExe', $PythonExe)
    if (-not [string]::IsNullOrWhiteSpace($NowEt)) { $WorkerArgs += @('-NowEt', $NowEt) }
    if (-not [string]::IsNullOrWhiteSpace($BatchTemplate)) {
        $WorkerArgs += @('-BatchTemplate', (Join-Path $Capsule 'private_inputs\us_batch_template'))
    }
    if (-not [string]::IsNullOrWhiteSpace($AccountState)) {
        $WorkerArgs += @('-AccountState', (Join-Path $Capsule 'private_inputs\us_account_state'))
    }
    if ($Live) { $WorkerArgs += '-Live' }
    if ($PrepareBudget) { $WorkerArgs += '-PrepareBudget' }
    if ($Pass2Budget -gt 0) { $WorkerArgs += @('-Pass2Budget', $Pass2Budget) }
    if ($MomentumTopK -gt 0) { $WorkerArgs += @('-MomentumTopK', $MomentumTopK) }
    Write-Host "[RUNTEST] US-short full flow is isolated in $Capsule" -ForegroundColor Cyan
    Push-Location $CapsuleRepo
    try {
        & $Worker @WorkerArgs
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
