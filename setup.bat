@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARG="
if defined DISKSCOPE_PYTHON (
    set "PYTHON_EXE=%DISKSCOPE_PYTHON%"
) else (
    python -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python"
    if not defined PYTHON_EXE (
        py -3 -c "import sys" >nul 2>&1
        if not errorlevel 1 (
            set "PYTHON_EXE=py"
            set "PYTHON_ARG=-3"
        )
    )
)

if not defined PYTHON_EXE (
    echo ERROR: Python was not found. Install supported 64-bit Python 3.11-3.14 and retry.
    exit /b 1
)

"%PYTHON_EXE%" %PYTHON_ARG% -c "import sys, struct; sys.exit(0 if (3, 11) <= sys.version_info[:2] < (3, 15) and struct.calcsize('P') == 8 else 1)"
if errorlevel 1 (
    echo ERROR: DiskScope requires 64-bit Python 3.11-3.14.
    exit /b 1
)
"%PYTHON_EXE%" %PYTHON_ARG% --version

if not exist ".venv\Scripts\python.exe" (
    echo Creating local Python environment...
    "%PYTHON_EXE%" %PYTHON_ARG% -m venv ".venv"
    if errorlevel 1 (
        echo ERROR: Could not create .venv.
        exit /b 1
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv was not created correctly.
    exit /b 1
)

echo Installing backend dependencies...
".venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt"
if errorlevel 1 (
    echo ERROR: Backend dependency installation failed.
    exit /b 1
)
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 (
    echo ERROR: Backend dependency check failed.
    exit /b 1
)

node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js was not found. Install Node.js and retry.
    exit /b 1
)
call npm.cmd --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: npm was not found. Install Node.js with npm and retry.
    exit /b 1
)

echo Installing frontend dependencies...
call npm.cmd --prefix "frontend" install
if errorlevel 1 (
    echo ERROR: Frontend dependency installation failed.
    exit /b 1
)

echo Building Web UI...
call npm.cmd --prefix "frontend" run build
if errorlevel 1 (
    echo ERROR: Web UI build failed.
    exit /b 1
)

echo DiskScope M0 setup completed successfully.
exit /b 0
