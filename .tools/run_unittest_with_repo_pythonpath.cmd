@echo off
setlocal

set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "REPO_PYTHON_LIBS=%REPO_ROOT%\.tools\python_libs"
set "PINNED_PYTHON=C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe"
set "PYTHON_EXE="
set "PIN_VALIDATOR=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%REPO_PYTHON_LIBS%\jsonschema" (
    echo Missing repo-local jsonschema package under "%REPO_PYTHON_LIBS%" 1>&2
    exit /b 1
)

set "ORIGINAL_PYTHONPATH=%PYTHONPATH%"

if defined PYTHONPATH (
    set "PYTHONPATH=%REPO_PYTHON_LIBS%;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%REPO_PYTHON_LIBS%"
)

if not exist "%PINNED_PYTHON%" (
    echo Pinned Stock Python was not found: "%PINNED_PYTHON%" 1>&2
    exit /b 1
)
if not exist "%PIN_VALIDATOR%" (
    echo Pinned Stock Python validation requires Windows PowerShell: "%PIN_VALIDATOR%" 1>&2
    exit /b 1
)
"%PIN_VALIDATOR%" -NoProfile -Command "$ErrorActionPreference = 'Stop'; . '%REPO_ROOT%\.tools\Resolve-AshortPython.ps1'; Resolve-AshortPython | Out-Null"
if errorlevel 1 (
    echo A legacy interpreter override does not equal the pinned Stock Python. 1>&2
    exit /b 1
)
set "PYTHON_EXE=%PINNED_PYTHON%"
rem Validation above rejects poisoned legacy overrides; clear accepted values for child processes.
set "STOCK_PYTHON="
set "STOCK_TEST_PYTHON="

"%PYTHON_EXE%" -c "import jsonschema" >nul 2>&1
if errorlevel 1 (
    rem The repository copy can shadow an otherwise usable interpreter package when its rpds binary is absent.
    if defined ORIGINAL_PYTHONPATH (
        set "PYTHONPATH=%ORIGINAL_PYTHONPATH%"
    ) else (
        set "PYTHONPATH="
    )
    "%PYTHON_EXE%" -c "import jsonschema" >nul 2>&1
    if errorlevel 1 (
        echo jsonschema is not importable from either "%REPO_PYTHON_LIBS%" or the pinned Stock Python. 1>&2
        echo The repository copy needs its matching rpds compiled extension. Install jsonschema for the pinned Stock Python 1>&2
        echo ^(for example, "%PYTHON_EXE%" -m pip install jsonschema^) and rerun; this launcher will use that copy. 1>&2
        exit /b 1
    )
)

pushd "%REPO_ROOT%" >nul
if errorlevel 1 exit /b 1

rem Prove the selected interpreter has the full A-short runtime before tests.
"%PYTHON_EXE%" runners\a_short_preflight.py
if errorlevel 1 (
    echo The selected Stock Python failed the full A-short dependency preflight. 1>&2
    exit /b 2
)

if "%~1"=="" (
    "%PYTHON_EXE%" -m unittest discover -s tests
) else (
    "%PYTHON_EXE%" -m unittest %*
)
set "TEST_EXIT=%ERRORLEVEL%"

popd >nul
exit /b %TEST_EXIT%
