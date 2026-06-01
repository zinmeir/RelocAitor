@echo off
REM ============================================================
REM  AI Global Relocation Intelligence — One-click setup & run
REM
REM  Place this file in the SAME folder as app.py, then double-click.
REM  It will:
REM    1. Move misplaced files into static/ and templates/ if needed
REM    2. Create a Python virtual environment
REM    3. Install dependencies
REM    4. Start the Flask server
REM    5. Open your browser to the app
REM ============================================================

setlocal enabledelayedexpansion

REM Always run from the folder this .bat lives in
cd /d "%~dp0"

echo.
echo ============================================================
echo   AI Global Relocation Intelligence  -  Setup ^& Run
echo ============================================================
echo.
echo  Working folder: %CD%
echo.

REM ---------- 1. Check Python is installed ----------
echo [1/5] Checking for Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  ERROR: Python is not installed or not on PATH.
    echo  Install it from https://www.python.org/downloads/
    echo  During install, tick "Add Python to PATH".
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo       Found: %%v

REM ---------- 2. Fix folder structure if needed ----------
echo.
echo [2/5] Verifying folder structure...

if not exist "templates\" mkdir templates
if not exist "static\css\" mkdir static\css
if not exist "static\js\"  mkdir static\js

REM Move stray HTML/CSS/JS into the right places (only if they're loose)
if exist "index.html"    move /Y "index.html"    "templates\"     >nul
if exist "style.css"     move /Y "style.css"     "static\css\"    >nul
if exist "app.js"        move /Y "app.js"        "static\js\"     >nul
if exist "countries.js"  move /Y "countries.js"  "static\js\"     >nul
if exist "map.js"        move /Y "map.js"        "static\js\"     >nul

REM Verify the critical files now exist where Flask expects them
set MISSING=0
if not exist "app.py"                       (echo   MISSING: app.py                       & set MISSING=1)
if not exist "templates\index.html"         (echo   MISSING: templates\index.html         & set MISSING=1)
if not exist "static\css\style.css"         (echo   MISSING: static\css\style.css         & set MISSING=1)
if not exist "static\js\app.js"             (echo   MISSING: static\js\app.js             & set MISSING=1)
if not exist "static\js\countries.js"       (echo   MISSING: static\js\countries.js       & set MISSING=1)
if not exist "static\js\map.js"             (echo   MISSING: static\js\map.js             & set MISSING=1)

if "%MISSING%"=="1" (
    echo.
    echo  ERROR: Some required files are missing from this folder.
    echo  Make sure you have all 11 files from the project.
    echo.
    pause
    exit /b 1
)
echo       Folder structure OK

REM ---------- 3. Create virtual environment ----------
echo.
echo [3/5] Setting up virtual environment...
if not exist "venv\Scripts\activate.bat" (
    echo       Creating new venv ^(this takes ~20 seconds^)...
    python -m venv venv
    if errorlevel 1 (
        echo  ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo       venv created
) else (
    echo       venv already exists
)

REM ---------- 4. Install dependencies ----------
echo.
echo [4/5] Installing dependencies...
call "venv\Scripts\activate.bat"

REM Only run pip install if Flask isn't already installed
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo       Installing packages ^(this takes ~30-60 seconds^)...
    python -m pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo  ERROR: Failed to install dependencies.
        pause
        exit /b 1
    )
    echo       Dependencies installed
) else (
    echo       Dependencies already installed
)

REM ---------- 5. Launch app ----------
echo.
echo [5/5] Starting the app...
echo.
echo ============================================================
echo   App is running!   Opening browser at http://localhost:5000
echo.
echo   To stop the server, press Ctrl+C in this window.
echo ============================================================
echo.

REM Open the browser shortly after the server starts
start "" cmd /c "timeout /t 3 >nul & start http://localhost:5000"

REM Run the Flask app (this blocks until you Ctrl+C)
python app.py

echo.
echo Server stopped. Press any key to close this window.
pause >nul
endlocal
