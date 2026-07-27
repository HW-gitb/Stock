@echo off
setlocal

set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "PINNED_PYTHON=C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe"
set "PYTHON_EXE="

if not exist "%PINNED_PYTHON%" (
    echo Pinned Stock Python was not found: "%PINNED_PYTHON%" 1>&2
    exit /b 1
)
set "PYTHON_EXE=%PINNED_PYTHON%"
rem The hard-coded executable is authoritative; inherited overrides are ignored and cleared.
set "STOCK_PYTHON="
set "STOCK_TEST_PYTHON="

pushd "%REPO_ROOT%" >nul
if errorlevel 1 exit /b 1

if "%~1"=="" (
    "%PYTHON_EXE%" ".tools\bounded_unittest.py" focused 300 -- discover -s tests
) else (
    "%PYTHON_EXE%" ".tools\bounded_unittest.py" focused 300 -- %*
)
set "TEST_EXIT=%ERRORLEVEL%"

popd >nul
exit /b %TEST_EXIT%
