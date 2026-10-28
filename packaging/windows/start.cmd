@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if not exist "%~dp0tools\uv.exe" (
  echo Missing tools\uv.exe. Extract the complete ZIP before starting.
  exit /b 1
)
set "UV_CACHE_DIR=%~dp0.cache\uv"
set "UV_PYTHON_INSTALL_DIR=%~dp0.python"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUTF8=1"
if exist "%~dp0.venv\Scripts\python.exe" goto sync
"%~dp0tools\uv.exe" venv --no-config --no-project --managed-python --python 3.11.17 "%~dp0.venv"
if errorlevel 1 goto finished
:sync
"%~dp0tools\uv.exe" pip sync --no-config --python "%~dp0.venv\Scripts\python.exe" "%~dp0requirements.txt"
if errorlevel 1 goto finished
"%~dp0.venv\Scripts\python.exe" -B "%~dp0start.py" %*
:finished
set "RPPG_EXIT=%ERRORLEVEL%"
if not "%RPPG_EXIT%"=="0" (
  echo Startup failed. First launch requires Internet access. See the error above.
  if "%~1"=="" pause
)
exit /b %RPPG_EXIT%
