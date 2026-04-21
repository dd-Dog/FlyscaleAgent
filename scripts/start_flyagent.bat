@echo off
setlocal
rem 随系统/计划任务后台启动时使用：工作目录切到项目根，再启动 uvicorn
set "ROOT=%~dp0.."
cd /d "%ROOT%"

set "PY="
if exist "%ROOT%\.venv\Scripts\python.exe" (
  set "PY=%ROOT%\.venv\Scripts\python.exe"
)
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [FlyAgent] 未找到 Python，请先安装或创建 .venv
  exit /b 1
)

if not defined FLYAGENT_HOST set "FLYAGENT_HOST=0.0.0.0"
if not defined FLYAGENT_PORT set "FLYAGENT_PORT=8765"
"%PY%" -m uvicorn app.main:app --host %FLYAGENT_HOST% --port %FLYAGENT_PORT%
