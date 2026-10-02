# BrowserCMD State

Capability level: **L1**

Current phase: **P0 complete**; health gates and logging-first validation are in place.

Done:
- Step 0 environment probe recorded in `docs/ENV_REPORT.txt`.
- Confirmed Python execution, package index access, temporary package installation, and a real pseudo-terminal.
- Confirmed Windows and a real Gecko browser are unavailable in this Linux container.
- Confirmed the repo has no reusable SocialCMD or YoutubePlayerCMD code to import.
- Runtime logging, redaction, retention, child-process capture, and crash hooks remain in place and verified.
- Added the required P0 quality gates: `scripts/check` and `scripts/smoke_test`.
- Added `.gitattributes` and `docs/PITFALLS.md` to cover Windows and terminal pitfalls.
- The P0 smoke path uses `--fake-engine` and logs loudly that the real engine remains `UNTESTED`.

Next step: keep the project on the verified L1 path, and do not advance to browser-specific work until a real Windows/browser-capable environment is available.

Open blockers:
- Real Zen/Firefox BiDi launch is not available here.
- Windows console input and Sixel are still `UNTESTED`.
- No Windows Job Object or terminal kill-on-close verification is possible in this environment.