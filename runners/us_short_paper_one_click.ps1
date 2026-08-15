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
    [Nullable[int]]$MaxRetriesPerCall = $null,
    [Nullable[double]]$RetryBackoffSeconds = $null,
    [Nullable[int]]$MaxTotalHttpAttempts = $null,
    [switch]$DisableSoftDiscovery,
    [switch]$DisableThemeSoftBoost,
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
if ($null -ne $MaxRetriesPerCall) {
    $cliArgs += @("--max-retries-per-call", "$MaxRetriesPerCall")
}
if ($null -ne $RetryBackoffSeconds) {
    $cliArgs += @("--retry-backoff-seconds", "$RetryBackoffSeconds")
}
if ($null -ne $MaxTotalHttpAttempts) {
    $cliArgs += @("--max-total-http-attempts", "$MaxTotalHttpAttempts")
}
if ($DisableSoftDiscovery) {
    $cliArgs += "--disable-soft-discovery"
}
if ($DisableThemeSoftBoost) {
    $cliArgs += "--disable-theme-soft-boost"
}
if (-not [string]::IsNullOrWhiteSpace($PrivateRoot)) {
    $cliArgs += @("--private-root", $PrivateRoot)
}

Write-Host "[US-SHORT PAPER] one-click full system" -ForegroundColor Cyan
Write-Host "[US-SHORT PAPER] python = $PythonExe" -ForegroundColor DarkGray
# The Python runner deliberately writes normal run metadata to stderr.  With
# ErrorActionPreference=Stop, Windows PowerShell 5.1 turns any native stderr
# into a terminating RemoteException before redirection can help.  Start the
# same pinned Python with a tiny bootstrap that redirects Python's stderr to
# stdout before the runner loads; the native exit code remains authoritative.
$stderrToStdoutBootstrap = @'
import runpy, sys
sys.stderr = sys.stdout
script = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(script, run_name="__main__")
'@
$stderrToStdoutBootstrap | & $PythonExe - @cliArgs
$RunExitCode = $LASTEXITCODE
if ($null -eq $RunExitCode) { $RunExitCode = 1 }
exit $RunExitCode
