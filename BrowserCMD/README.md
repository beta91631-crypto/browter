# BrowserCMD

BrowserCMD is being built as a Windows terminal browser. At this stage, the verified functionality is the Python session logger, its redaction/retention rules, and support-report generation. Page navigation and rendering are not implemented yet.

## Requirements

- Windows with Python 3.10 or newer for the `.bat` launchers.
- A supported system Chromium browser (Brave, Edge, or Chrome) is required for browser features; browser detection and launch are not yet verified.
- The launcher creates `.venv` and installs the bounded dependencies from `requirements.txt` on first run.

## Current commands

- `BrowserCMD.bat` creates the environment and starts the current logging smoke-test entry point.
- `BrowserCMD.bat --setup` installs or refreshes dependencies.
- `diagnose.bat` writes `diagnostic.txt` with environment, browser, terminal, and self-test results.
- `collect-logs.bat` writes a redacted `logs\SEND_ME.txt` support bundle.
- For a deliberate exception-hook test from this directory: `.venv\Scripts\python.exe -m browsercmd --crash-test`.

## Support data

Session logs are UTF-8 files under `logs/`, capped at 5 MiB each with the ten newest retained. Queries and common credential fields are redacted by default. Do not send cookies, passwords, or other secrets in support reports.

See [ROADMAP.md](ROADMAP.md) for planned browser functionality and [docs/ENV_REPORT.txt](docs/ENV_REPORT.txt) for the environment in which this build was tested.