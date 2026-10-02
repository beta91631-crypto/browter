@echo off
setlocal
cd /d "%~dp0"
set "REPORT=%~dp0diagnostic.txt"
set "PYTHON=%~dp0.venv\Scripts\python.exe"

>"%REPORT%" echo BrowserCMD diagnostic bootstrap
>>"%REPORT%" echo Windows version: %OS% %PROCESSOR_ARCHITECTURE%
>>"%REPORT%" echo Python path candidates:
where py >>"%REPORT%" 2>&1
where python >>"%REPORT%" 2>&1
if exist "%PYTHON%" goto use_python
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -m browsercmd.diagnostics --output "%REPORT%" >>"%REPORT%" 2>&1
    goto done
)
where python >nul 2>nul
if not errorlevel 1 (
    python -m browsercmd.diagnostics --output "%REPORT%" >>"%REPORT%" 2>&1
    goto done
)
>>"%REPORT%" echo Python unavailable; automated package, browser, and image tests skipped.
goto done

:use_python
"%PYTHON%" -m browsercmd.diagnostics --output "%REPORT%" >>"%REPORT%" 2>&1
:done
echo Diagnostic report written: %REPORT%
pause