@echo off
setlocal

set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"

call "%REPO_ROOT%\.tools\run_unittest_with_repo_pythonpath.cmd" tests.test_doc_governance_guard tests.test_readme_route_row_length tests.test_route_doc_ledger_status_consistency
exit /b %ERRORLEVEL%
