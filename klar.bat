@echo off
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
where python >nul 2>nul
if %errorlevel%==0 (
  python -m klar %*
) else (
  py -3 -m klar %*
)
