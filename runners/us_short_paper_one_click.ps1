# US-short paper-account full-system one-click launcher.
# The sibling .cmd supplies a process-scoped ExecutionPolicy bypass; this
# script validates the pinned host Python and invokes one Python process; a
# caller cannot redirect it to PATH, bundled, or another interpreter.

[CmdletBinding()]
param(
    [string]$NowEt = "",
    [string]$PrivateRoot = "",
    [int]$MomentumTopK = 200,
    [double]$ProviderPaceSeconds = 1.0,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $repo "runners\us_short_paper_one_click.py"
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "找不到 US-short paper one-click runner: $runner"
}
. (Join-Path $repo ".tools\Resolve-AshortPython.ps1")
$PythonExe = Resolve-AshortPython -Requested $PythonExe

if ([string]::IsNullOrWhiteSpace($NowEt)) {
    $etZone = [System.TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
    $NowEt = [System.TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $etZone).ToString("yyyy-MM-ddTHH:mm:ss")
}

$cliArgs = @(
    $runner,
    "--now-et", $NowEt,
    "--momentum-top-k", "$MomentumTopK",
    "--provider-pace-seconds", "$ProviderPaceSeconds"
)
if (-not [string]::IsNullOrWhiteSpace($PrivateRoot)) {
    $cliArgs += @("--private-root", $PrivateRoot)
}

Write-Host "[US-SHORT PAPER] one-click full system" -ForegroundColor Cyan
Write-Host "[US-SHORT PAPER] python = $PythonExe" -ForegroundColor DarkGray
& $PythonExe @cliArgs
exit $LASTEXITCODE
