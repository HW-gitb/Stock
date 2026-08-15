# Disposable US-short full-flow runtest launcher.
#
# It intentionally preserves the existing capstone gates while rooting every
# mutable path in a fresh capsule; an explicit -Live command is the run authorization.
# Use -AsOf YYYYMMDD to bind the test date; private inputs are auto-selected
# from state\us_short\weekly_private\_run_inputs when omitted.

[CmdletBinding()]
param(
    [string]$NowEt = '',
    [string]$AsOf = '',
    [string]$BatchTemplate = '',
    [string]$AccountState = '',
    [switch]$Live,
    [int]$MomentumTopK = 0,
    [string[]]$ExtraArgs = @(),
    [string]$SourceRoot = '',
    [string]$CapsuleRoot = 'D:\cnhea\Stock_runtest_private',
    [string]$Commit = 'HEAD',
    [string]$RunId = '',
    [string]$PythonExe = '',
    [switch]$ConfirmRuntest
)

$ErrorActionPreference = 'Stop'

if (-not $ConfirmRuntest) {
    throw 'Runtest is intentionally explicit. Re-run with -ConfirmRuntest; this creates a new isolated capsule and may call providers under the existing US-short gates.'
}
if ($ExtraArgs.Count -gt 0) {
    # The ordinary launcher intentionally exposes raw pass-through.  A capsule
    # cannot: argparse accepts the last duplicate, so any forwarded authority
    # or path flag could override the capsule-owned private root, inputs, or
    # live/budget gate.  Add future knobs as explicit audited wrapper params.
    throw 'Runtest does not forward -ExtraArgs; it rejects all raw runner flags so capsule paths and authorization gates cannot be overridden.'
}
$ExplicitAsOf = -not [string]::IsNullOrWhiteSpace($AsOf)
$ExplicitNowEt = -not [string]::IsNullOrWhiteSpace($NowEt)
if ($Live -and ($ExplicitAsOf -or $ExplicitNowEt)) {
    throw '-Live requires the wrapper to use the actual current ET clock; do not combine it with -AsOf or -NowEt.'
}
$RuntimeRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($SourceRoot)) {
    $SourceRoot = $RuntimeRoot
}
$SourceRoot = (Resolve-Path -LiteralPath $SourceRoot).Path
$Manager = Join-Path $SourceRoot 'runners\runtest_capsule.py'
if (-not (Test-Path -LiteralPath $Manager -PathType Leaf)) {
    throw "Missing runtest capsule manager: $Manager"
}
. (Join-Path $RuntimeRoot '.tools\Resolve-AshortPython.ps1')
$PythonExe = Resolve-AshortPython -Requested $PythonExe
if (-not [string]::IsNullOrWhiteSpace($AsOf)) {
    if (-not [string]::IsNullOrWhiteSpace($NowEt)) {
        throw '-AsOf and -NowEt are mutually exclusive; the specified date automatically uses the ET pre-open clock.'
    }
    try {
        $asOfDate = [DateTime]::ParseExact($AsOf, 'yyyyMMdd', [Globalization.CultureInfo]::InvariantCulture)
    } catch {
        throw '-AsOf must be a valid YYYYMMDD date.'
    }
    $NowEt = $asOfDate.ToString('yyyy-MM-ddT08:00:00')
}
if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "us_short_$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))_$PID"
}

$RunInputs = Join-Path $SourceRoot 'state\us_short\weekly_private\_run_inputs'
if ([string]::IsNullOrWhiteSpace($BatchTemplate)) {
    $BatchTemplate = Get-ChildItem -LiteralPath $RunInputs -Recurse -File -Filter '*batch*template*.json' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if ([string]::IsNullOrWhiteSpace($AccountState)) {
    $AccountState = Get-ChildItem -LiteralPath $RunInputs -Recurse -File -Filter '*account*state*.json' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
}

if ($Live -and ([string]::IsNullOrWhiteSpace($BatchTemplate) -or [string]::IsNullOrWhiteSpace($AccountState))) {
    throw 'A live runtest could not find a batch template and account state under state\us_short\weekly_private\_run_inputs; add the private facts there or pass explicit input paths.'
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
    # Script parameters require a hashtable splat.  An array splat passes
    # these tokens positionally, so named values can bind to the wrong worker
    # parameters (for example PythonExe to an integer worker parameter).
    $WorkerParams = @{
        PrivateRoot = $PrivateRoot
        PythonExe = $PythonExe
    }
    if (-not [string]::IsNullOrWhiteSpace($NowEt)) { $WorkerParams.NowEt = $NowEt }
    if (-not [string]::IsNullOrWhiteSpace($BatchTemplate)) {
        $WorkerParams.BatchTemplate = Join-Path $Capsule 'private_inputs\us_batch_template'
    }
    if (-not [string]::IsNullOrWhiteSpace($AccountState)) {
        $WorkerParams.AccountState = Join-Path $Capsule 'private_inputs\us_account_state'
    }
    if ($Live) { $WorkerParams.Live = $true }
    if ($MomentumTopK -gt 0) { $WorkerParams.MomentumTopK = $MomentumTopK }
    Write-Host "[RUNTEST] US-short full flow is isolated in $Capsule" -ForegroundColor Cyan
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
