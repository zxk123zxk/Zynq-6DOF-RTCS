@echo off
rem PC-side vision entry: pin the venv, cd to this folder, pass args through.
rem   .\env.cmd scripts\grasp_point.py --frames 9 --json
rem ASCII-only on purpose: cmd.exe reads .cmd as ANSI, so non-ASCII comments
rem get mis-decoded and half-lines get run as commands (seen 2026-10-25).
rem venv: prefer D:\rtcs-venv because the project path is long enough to hit MAX_PATH.
setlocal
cd /d "%~dp0"
set "PY=D:\rtcs-venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [env.cmd] venv not found: D:\rtcs-venv\Scripts\python.exe or .venv\Scripts\python.exe
  exit /b 9009
)
"%PY%" %*
exit /b %ERRORLEVEL%
