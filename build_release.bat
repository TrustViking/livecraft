@echo off
chcp 65001 >nul
rem Livecraft: release build - exe + installer without anybody's data (CLAUDE.md 13 stage 8, 14 decision 16).
rem The build folder dist\livecraft gets: livecraft.exe and livecraftw.exe (PyInstaller, one folder), livecraft.bat,
rem tools\yt-dlp.exe, tools\deno.exe and secrets\client_secret.json (the program passport, one for everybody, 9).
rem Nothing else from secrets\: no vault, no livecraft.json, no channels, no sign-in tokens, no cookies - a person
rem gets values through an access token or types them in.
rem The only environment is .venv_livecraft: the app and pyinstaller live there.
rem Exit codes: 0 - exe and installer built; 1 - build failed; 3 - exe built, Inno Setup not found.
setlocal EnableExtensions

set "ROOT=%~dp0."
cd /d "%ROOT%"

set "BUILD_PYTHON=%ROOT%\.venv_livecraft\Scripts\python.exe"
set "SPEC=%ROOT%\livecraft.spec"
set "ISS=%ROOT%\livecraft.iss"
set "DIST_APP=%ROOT%\dist\livecraft"
set "DISCOVERY_DIR=%DIST_APP%\_internal\googleapiclient\discovery_cache\documents"
set "CLIENT_SECRET=%ROOT%\secrets\client_secret.json"
set "YTDLP=%ROOT%\tools\yt-dlp.exe"
set "DENO=%ROOT%\tools\deno.exe"

rem --- 1. environment and the files the installer carries --------------------------
if not exist "%BUILD_PYTHON%" (
  echo [ERROR] Python not found: "%BUILD_PYTHON%"
  call :finish 1
  exit /b 1
)
"%BUILD_PYTHON%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] PyInstaller not found in .venv_livecraft.
  call :finish 1
  exit /b 1
)
for %%F in ("%CLIENT_SECRET%" "%YTDLP%" "%DENO%") do if not exist "%%~F" (
  echo [ERROR] File not found: "%%~F"
  call :finish 1
  exit /b 1
)

rem --- 2. version: app\version.py is the only source; every build bumps patch +1 --
rem The bumped app\version.py stays in the working tree - commit it with the build.
set "APP_VERSION="
set "VERSION_FILE=%TEMP%\livecraft_build_version.tmp"
"%BUILD_PYTHON%" -m app.version --bump > "%VERSION_FILE%"
if not errorlevel 1 set /p APP_VERSION=<"%VERSION_FILE%"
if exist "%VERSION_FILE%" del /Q "%VERSION_FILE%"
if not defined APP_VERSION (
  echo [ERROR] Cannot bump APP_VERSION in app\version.py.
  call :finish 1
  exit /b 1
)
echo [INFO] Version: %APP_VERSION%

rem --- 3. exe ------------------------------------------------------------------
if exist "%ROOT%\build" rmdir /S /Q "%ROOT%\build"
if exist "%ROOT%\dist" rmdir /S /Q "%ROOT%\dist"
"%BUILD_PYTHON%" -m PyInstaller --noconfirm --clean --distpath "%ROOT%\dist" --workpath "%ROOT%\build" "%SPEC%"
if errorlevel 1 (
  echo [ERROR] PyInstaller failed.
  call :finish 1
  exit /b 1
)
for %%D in (youtube.v3.json sheets.v4.json drive.v3.json docs.v1.json) do if not exist "%DISCOVERY_DIR%\%%D" (
  echo [ERROR] %%D is missing in the build: "%DISCOVERY_DIR%"
  call :finish 1
  exit /b 1
)

rem Next to the exe: launcher, external binaries and the program passport.
mkdir "%DIST_APP%\tools" >nul 2>&1
mkdir "%DIST_APP%\secrets" >nul 2>&1
copy /Y "%ROOT%\livecraft.bat" "%DIST_APP%\livecraft.bat" >nul
copy /Y "%YTDLP%" "%DIST_APP%\tools\yt-dlp.exe" >nul
copy /Y "%DENO%" "%DIST_APP%\tools\deno.exe" >nul
copy /Y "%CLIENT_SECRET%" "%DIST_APP%\secrets\client_secret.json" >nul
for %%F in (livecraft.exe livecraftw.exe livecraft.bat tools\yt-dlp.exe tools\deno.exe secrets\client_secret.json) do if not exist "%DIST_APP%\%%F" (
  echo [ERROR] %%F is missing in "%DIST_APP%".
  call :finish 1
  exit /b 1
)
echo [OK] Portable build: %DIST_APP%

rem --- 4. installer ------------------------------------------------------------
set "ISCC="
for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do if not defined ISCC set "ISCC=%%I"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo [ERROR] Inno Setup 6 ^(ISCC.exe^) not found - the exe is built, but the installer needs Inno Setup.
  echo         Install Inno Setup 6 from https://jrsoftware.org/isdl.php and run this script again.
  call :finish 3
  exit /b 3
)

"%ISCC%" /Q /DAppVersion=%APP_VERSION% "%ISS%"
if errorlevel 1 (
  echo [ERROR] Inno Setup failed.
  call :finish 1
  exit /b 1
)
echo [OK] Installer: dist\installer\livecraft-setup-%APP_VERSION%.exe
call :finish 0
exit /b 0

:finish
if not defined NO_PAUSE pause
exit /b %1
