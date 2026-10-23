@echo off
rem Builds klarc.exe (the Klar compiler written in Klar) without Python.
rem   build.bat                 uses seed\klarc-windows.exe, %KLARC%, or downloads the seed of this version's release
rem The seed compiles compiler/klarc.klar into build\klarc1.exe, which compiles it again into build\klarc.exe; both
rem must be the same bytes.
setlocal
cd /d "%~dp0"
for /f "usebackq tokens=1,2 delims== " %%a in ("pyproject.toml") do if "%%a"=="version" set "VERSION=%%~b"
set "SEED=%KLARC%"
if "%SEED%"=="" set "SEED=seed\klarc-windows.exe"
if not exist "%SEED%" (
  if not exist seed mkdir seed
  echo downloading the seed compiler for v%VERSION%
  curl -fsSL -o "%SEED%" "https://github.com/veosett/Klar/releases/download/v%VERSION%/klarc-windows.exe" || exit /b 1
)
if not exist build mkdir build
"%SEED%" build compiler/klarc.klar -o build/klarc1.exe --target windows --lib klar
if errorlevel 1 exit /b 1
build\klarc1.exe build compiler/klarc.klar -o build/klarc.exe --target windows --lib klar
if errorlevel 1 exit /b 1
fc /b build\klarc1.exe build\klarc.exe >nul
if errorlevel 1 (
  echo error: klarc does not reproduce itself
  exit /b 1
)
del build\klarc1.exe
echo ok: build\klarc.exe
