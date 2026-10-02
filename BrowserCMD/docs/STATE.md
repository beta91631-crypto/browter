# BrowserCMD State

Capability level: **L1**

Current phase: P2 (in progress)

Done:
- Step 0 environment probe recorded in `docs/ENV_REPORT.txt`.
- Confirmed Python execution, package index access, temporary package installation, and a real 80x30 pseudo-terminal.
- Confirmed no Windows, Chromium browser, or chafa is available; `rg` is unavailable.
- Confirmed repository has no existing BrowserCMD, SocialCMD, or YoutubePlayerCMD project to reuse.
- Implemented Python session logger with runtime header, default secret/query redaction, 5 MiB cap, ten-log retention, child stderr tail capture, and uncaught exception hooks.
- Logging/support tests: 6 passed (redaction, traceback, child status/stderr tail, retention, size cap, 300-line bundle).
- Linux diagnostic report generated; localhost bind verified and missing browser/CDP reported as unavailable.
- Deliberate CLI crash verified: exit 1, traceback saved, and log path printed.
- P1 browser/URL/CDP adapter added: fallback candidates, temporary profiles, `DevToolsActivePort` readiness, process exit/stderr logging, CDP requests, and navigation allowlist.
- P1 tests: 6 browser tests and 12 total tests passed; includes an actual local WebSocket handshake with websockets 15.0.1 and a fake browser exit-21 fallback.

Next step: implement and test the deterministic Pillow/NumPy pixel-art pipeline and standalone image command.

Open blockers:
- Windows batch behavior and crash-window persistence cannot be executed in this Linux environment.
- Browser/CDP and Sixel cannot be exercised because no browser/terminal protocol response is available.
- Windows Job Object kill-on-close is not implemented; current browser cleanup is graceful/atexit only and does not meet the hard Windows crash-lifecycle requirement.