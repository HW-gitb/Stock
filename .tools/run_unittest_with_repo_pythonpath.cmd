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
rem Do not inherit PATH/PYTHONPATH pollution: the child must resolve only the pinned
rem Python and Windows process-control tools used by the bounded runner.
set "PINNED_PYTHON_DIR=C:\Users\cnhea\AppData\Local\Programs\Python\Python313"
set "PYTHONPATH="
set "PATH=%PINNED_PYTHON_DIR%;%PINNED_PYTHON_DIR%\Scripts;%ProgramFiles%\Git\cmd;%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0"
set "TIMEOUT_SECONDS=300"
set "EXPLICIT_TIMEOUT="
set "UNITTEST_ARGS="

pushd "%REPO_ROOT%" >nul
if errorlevel 1 exit /b 1

"%PYTHON_EXE%" -c "import jsonschema" >nul 2>&1
if errorlevel 1 (
    echo Required jsonschema dependency is not importable in the pinned Stock Python. 1>&2
    popd >nul
    exit /b 1
)

rem A usage guard must exit through a SINGLE-level label: `exit /b` from a nested
rem `if (...)` block loses its code and the launcher would report success with no
rem tests run (GOV-R4).  Both usage checks therefore `goto` out of the block.
if /I "%~1"=="--timeout-seconds" (
    if "%~2"=="" goto usage_missing_timeout_value
    set "TIMEOUT_SECONDS=%~2"
    set "EXPLICIT_TIMEOUT=1"
    shift /1
    shift /1
)

:collect_unittest_args
if "%~1"=="" goto run_unittest
set "UNITTEST_ARGS=%UNITTEST_ARGS% "%~1""
shift /1
goto collect_unittest_args

:run_unittest
if not defined UNITTEST_ARGS (
    if defined EXPLICIT_TIMEOUT goto usage_missing_unittest_args
    "%PYTHON_EXE%" ".tools\bounded_unittest.py" focused %TIMEOUT_SECONDS% -- discover -s tests
) else (
    "%PYTHON_EXE%" ".tools\bounded_unittest.py" focused %TIMEOUT_SECONDS% -- %UNITTEST_ARGS%
)
set "TEST_EXIT=%ERRORLEVEL%"

popd >nul
exit /b %TEST_EXIT%

:usage_missing_timeout_value
echo --timeout-seconds requires a positive integer no greater than 1300. 1>&2
popd >nul
exit /b 2

:usage_missing_unittest_args
echo --timeout-seconds requires unittest arguments. 1>&2
popd >nul
exit /b 2
