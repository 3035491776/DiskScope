@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Please run setup.bat first.
    exit /b 1
)
".venv\Scripts\python.exe" "launcher\bootstrap.py"
set "RESULT=%ERRORLEVEL%"
endlocal & exit /b %RESULT%

