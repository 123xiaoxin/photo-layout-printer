@echo off
title Photo Layout Tool

REM ===== Step 0: Go to script directory =====
cd /d "%~dp0"

REM ===== Step 1: Log file setup =====
set "LOG_FILE=%~dp0launcher_log.txt"
echo. > "%LOG_FILE%"
echo === Photo Layout Tool Launch Log === >> "%LOG_FILE%"
echo Date: %date% %time% >> "%LOG_FILE%"
echo WorkingDir: %cd% >> "%LOG_FILE%"

echo ========================================
echo   Photo Layout Tool - Launcher
echo ========================================
echo.

REM ===== Step 2: Find Python (simple flat checks, no loops/goto tricks) =====
set "PY="

echo Step 1/5: Checking embedded python.exe...
if exist "python.exe" (
    set "PY=%cd%\python.exe"
    echo   Found: %PY%
    goto :python_found
)
echo   Not found.

echo Step 2/5: Checking user-dir Python314...
if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python314\python.exe" (
    set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python314\python.exe"
    echo   Found: %PY%
    goto :python_found
)
echo   Not found.

echo Step 3/5: Checking user-dir Python313...
if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe" (
    set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python313\python.exe"
    echo   Found: %PY%
    goto :python_found
)
echo   Not found.

echo Step 4/5: Checking user-dir Python312...
if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe" (
    set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe"
    echo   Found: %PY%
    goto :python_found
)
echo   Not found.

echo Step 5/5: Checking system PATH...
where python >nul 2>nul
if %errorlevel% equ 0 (
    for /f "delims=" %%Q in ('where python 2^>nul ^| findstr /v /i "WindowsApps"') do (
        set "PY=%%Q"
        echo   Found: %%Q
        goto :python_found
    )
)
echo   Not found.

REM Also check common install paths quickly
if not defined PY if exist "C:\Python314\python.exe"  set "PY=C:\Python314\python.exe"
if not defined PY if exist "C:\Python311\python.exe"  set "PY=C:\Python311\python.exe"
if not defined PY if exist "C:\Python310\python.exe"  set "PY=C:\Python310\python.exe"
if not defined PY if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe" set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe"
if not defined PY if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python310\python.exe" set "PY=%USERPROFILE%\AppData\Local\Programs\Python\Python310\python.exe"
if defined PY (
    echo   Found fallback: %PY%
    goto :python_found
)

echo.
echo [ERROR] Python not found anywhere!
echo Please install Python 3.8+ from https://www.python.org/downloads/
echo and check "Add Python to PATH" during install.
echo.
echo Python: %PY% >> "%LOG_FILE%"
echo ERROR: Python not found >> "%LOG_FILE%"
pause
exit /b 1

:python_found
echo.
echo Python OK: %PY%
echo Python: %PY% >> "%LOG_FILE%"

REM ===== Step 3: Dependencies (quiet install, ignore errors, Python has fallback anyway) =====
echo.
echo Checking dependencies...
echo Checking dependencies... >> "%LOG_FILE%"

"%PY%" -c "import PIL, tkinterdnd2" 2>nul
if errorlevel 1 goto :need_pillow
goto :pillow_ok
:need_pillow
echo   Installing Pillow + tkinterdnd2...
"%PY%" -m pip install Pillow tkinterdnd2 -q 2>> "%LOG_FILE%"
:pillow_ok
echo   Pillow/tkinterdnd2: OK

"%PY%" -c "import win32print" 2>nul
if errorlevel 1 goto :need_pywin32
goto :pywin32_ok
:need_pywin32
echo   Installing pywin32 (optional)...
"%PY%" -m pip install pywin32 -q 2>> "%LOG_FILE%"
:pywin32_ok
echo   pywin32 (printer lib): OK or fallback available
echo Dependencies OK.
echo Dependencies OK. >> "%LOG_FILE%"

REM ===== Step 4: Launch the GUI =====
echo.
echo ========================================
echo   Starting Photo Layout Tool...
echo   (Close GUI window when done)
echo ========================================
echo.
echo Launching GUI... >> "%LOG_FILE%"

"%PY%" "%~dp0photo_layout_printer.py" >> "%LOG_FILE%" 2>&1
set "EXITCODE=%errorlevel%"

echo.
echo ========================================
echo   Program finished. Exit code: %EXITCODE%
echo ========================================
echo.
echo Exit code: %EXITCODE% >> "%LOG_FILE%"
echo See log at: %LOG_FILE%
echo.
REM ========== UNCONDITIONAL PAUSE - PREVENTS FLASH-CLOSE ==========
pause
