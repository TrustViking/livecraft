@echo off
chcp 65001 >nul
rem Livecraft launcher (CLAUDE.md 10). One file for both cases:
rem   installed program - livecraft.exe lies next to this file, it is started;
rem   repository        - no livecraft.exe here, app.main is started from .venv_livecraft.
rem Without pause the console window would close together with the program.
setlocal EnableExtensions

set "ROOT=%~dp0."
set "LIVECRAFT_EXE=%ROOT%\livecraft.exe"
set "PYTHON=%ROOT%\.venv_livecraft\Scripts\python.exe"

cd /d "%ROOT%"
if exist "%LIVECRAFT_EXE%" (
  "%LIVECRAFT_EXE%" %*
) else if exist "%PYTHON%" (
  "%PYTHON%" -m app.main %*
) else (
  echo [ERROR] Neither livecraft.exe nor Python found next to livecraft.bat: "%ROOT%"
  pause
  exit /b 2
)
set "CODE=%ERRORLEVEL%"

echo.
echo Exit code: %CODE%
pause
exit /b %CODE%
