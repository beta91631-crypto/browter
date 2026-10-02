@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if exist "%PYTHON%" goto use_python
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -m browsercmd.collect_logs
    goto done
)
where python >nul 2>nul
if not errorlevel 1 (
    python -m browsercmd.collect_logs
    goto done
)
if not exist logs mkdir logs
>logs\SEND_ME.txt echo Python unavailable; BrowserCMD log collection could not run.
echo Python unavailable; partial report written to logs\SEND_ME.txt
goto done

:use_python
"%PYTHON%" -m browsercmd.collect_logs
:done
pause