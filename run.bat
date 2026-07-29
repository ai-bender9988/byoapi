@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    set "PYCMD=python"
) else (
    where python3 >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        set "PYCMD=python3"
    ) else (
        echo Python was not found on this computer.
        echo Opening the download page in your browser...
        echo.
        echo During installation, check the box "Add python.exe to PATH" before clicking Install.
        echo Then close this window and double-click run.bat again.
        echo.
        explorer https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

REM Found *a* python command - now check it's actually new enough. This app
REM uses "str | None"-style type hints (PEP 604), which only work at runtime
REM on Python 3.10+; on anything older (including Python 2, if that's what
REM "python" happens to point to) proxy.py would fail immediately with a
REM cryptic TypeError instead of a clear "upgrade Python" message.
%PYCMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not %ERRORLEVEL% EQU 0 (
    echo Found Python, but it's older than the required version ^(3.10+^).
    echo Opening the download page in your browser...
    echo.
    echo During installation, check the box "Add python.exe to PATH" before clicking Install.
    echo Then close this window and double-click run.bat again.
    echo.
    explorer https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist kie_key.txt (
    echo No kie_key.txt found yet - that's fine, the app itself will let you
    echo paste your kie.ai API key into it: open Options once the app loads.
    echo ^(Or set it up by hand first: rename kie_key.example.txt to kie_key.txt
    echo and paste your key into it, then run this again.^)
    echo.
)

echo Starting BYOAPI...
echo Your browser will open automatically in a couple of seconds.
echo Close this window ^(or press Ctrl+C^) any time to stop the server.
echo.

start "" /min cmd /c "timeout /t 2 /nobreak >nul & explorer http://127.0.0.1:8787"
%PYCMD% proxy.py

echo.
echo Server stopped.
pause
