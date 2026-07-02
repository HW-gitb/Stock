@echo off
setlocal

set "REPO_ROOT=%~dp0.."
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"
set "REPO_PYTHON_LIBS=%REPO_ROOT%\.tools\python_libs"

if not exist "%REPO_PYTHON_LIBS%\jsonschema" (
    echo Missing repo-local jsonschema package under "%REPO_PYTHON_LIBS%" 1>&2
    exit /b 1
)

if defined PYTHONPATH (
    echo ;%PYTHONPATH%; | find /I ";%REPO_PYTHON_LIBS%;" >nul
    if errorlevel 1 set "PYTHONPATH=%REPO_PYTHON_LIBS%;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%REPO_PYTHON_LIBS%"
)

if defined STOCK_TEST_PYTHON (
    set "PYTHON_EXE=%STOCK_TEST_PYTHON%"
) else (
    for %%P in (python py python3) do (
        if not defined PYTHON_EXE (
            where %%P >nul 2>nul
            if not errorlevel 1 set "PYTHON_EXE=%%P"
        )
    )
)

if not defined PYTHON_EXE (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
        if not defined PYTHON_EXE if exist "%%~fD\python.exe" set "PYTHON_EXE=%%~fD\python.exe"
    )
)

if not defined PYTHON_EXE if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" (
    set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Launcher\py.exe"
)

if not defined PYTHON_EXE (
    for /d %%D in ("%ProgramFiles%\Python*") do (
        if not defined PYTHON_EXE if exist "%%~fD\python.exe" set "PYTHON_EXE=%%~fD\python.exe"
    )
)

if not defined PYTHON_EXE if defined ProgramFiles(x86) (
    for /d %%D in ("%ProgramFiles(x86)%\Python*") do (
        if not defined PYTHON_EXE if exist "%%~fD\python.exe" set "PYTHON_EXE=%%~fD\python.exe"
    )
)

if not defined PYTHON_EXE (
    echo No Python executable found. Install Python or set STOCK_TEST_PYTHON to a python.exe path. 1>&2
    exit /b 1
)

"%PYTHON_EXE%" -c "import jsonschema"
if errorlevel 1 (
    echo jsonschema is not importable after prepending "%REPO_PYTHON_LIBS%" to PYTHONPATH. 1>&2
    exit /b 1
)

pushd "%REPO_ROOT%" >nul
if errorlevel 1 exit /b 1

if "%~1"=="" (
    "%PYTHON_EXE%" -m unittest discover -s tests
) else (
    "%PYTHON_EXE%" -m unittest %*
)
set "TEST_EXIT=%ERRORLEVEL%"

popd >nul
exit /b %TEST_EXIT%
