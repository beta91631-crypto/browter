@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        where python >nul 2>nul
        if errorlevel 1 (
            echo Python 3 was not found. Install Python 3 and rerun BrowserCMD.bat.
            pause
            exit /b 1
        )
        python -m venv .venv
    )
    if errorlevel 1 (
        echo Failed to create the BrowserCMD virtual environment.
        pause
        exit /b 1
    )
)

if not exist ".venv\browsercmd-deps-installed" set "BROWSERCMD_SETUP=1"
if /i "%~1"=="--setup" set "BROWSERCMD_SETUP=1"
if defined BROWSERCMD_SETUP (
    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Dependency installation failed. See the output above.
        pause
        exit /b 1
    )
    type nul > ".venv\browsercmd-deps-installed"
    if /i "%~1"=="--setup" exit /b 0
)

for /F %%a in ('echo prompt $E^| cmd') do set "ESC=%%a"
"%PYTHON%" -m browsercmd %*
set "APP_EXIT=%ERRORLEVEL%"
echo %ESC%[0m%ESC%[?25h%ESC%[?1000l%ESC%[?1002l%ESC%[?1003l%ESC%[?1006l%ESC%[?2026l%ESC%[?1049l
exit /b %APP_EXIT%