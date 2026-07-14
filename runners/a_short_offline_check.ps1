param([string]$PythonExe = '')

$ProjectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $ProjectRoot '.tools\Resolve-AshortPython.ps1')
try {
    $PythonExe = Resolve-AshortPython -Requested $PythonExe
} catch {
    Write-Host "[FATAL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

& $PythonExe (Join-Path $PSScriptRoot 'a_short_preflight.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$env:STOCK_TEST_PYTHON = $PythonExe
& (Join-Path $ProjectRoot '.tools\run_unittest_with_repo_pythonpath.cmd') `
    tests.test_a_short_preflight `
    tests.test_a_short_entry_funnel_calibration `
    tests.test_a_short_weekly_pipeline `
    tests.phase6.test_weekly_screening_guardrails `
    tests.test_a_short_review1_knives_1_5 `
    tests.test_a_short_review1_knives_6_10 `
    tests.execution.test_backtest_execution `
    tests.execution.test_materialize_execution_price_data `
    tests.execution.test_materialize_execution_price_data_tushare `
    tests.execution.test_aggregate_execution_reports
exit $LASTEXITCODE
