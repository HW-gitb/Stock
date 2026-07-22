@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0us_short_paper_one_click.ps1" %*
exit /b %ERRORLEVEL%
