@echo off
setlocal
set "ROOT=%~dp0"
set "ENTRY=%ROOT%pacienti_ai_independent\pacienti_ai_app.py"

if not exist "%ENTRY%" (
  echo [ERROR] Lipseste entrypoint-ul: %ENTRY%
  exit /b 1
)

set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%PYEXE%" goto run_pyexe
if exist "%ROOT%.venv\Scripts\python.exe" set "PYEXE=%ROOT%.venv\Scripts\python.exe"
if exist "%PYEXE%" goto run_pyexe

where python >nul 2>nul
if %errorlevel%==0 (
  echo [INFO] Launching with python
  python "%ENTRY%"
  exit /b %errorlevel%
)

where py >nul 2>nul
if %errorlevel%==0 (
  echo [INFO] Launching with py -3
  py -3 "%ENTRY%"
  exit /b %errorlevel%
)

echo [ERROR] Nu am gasit Python. Instaleaza Python 3.12+.
exit /b 1

:run_pyexe
echo [INFO] Launching with %PYEXE%
"%PYEXE%" "%ENTRY%"
exit /b %errorlevel%
