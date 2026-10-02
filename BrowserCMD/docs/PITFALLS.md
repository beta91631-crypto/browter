# BrowserCMD Pitfalls

## Windows console pitfalls
- Set `chcp 65001` and `PYTHONUTF8=1` in the launcher; Unicode block characters can crash a UTF-8 console.
- Enable VT output (`ENABLE_VIRTUAL_TERMINAL_PROCESSING`) and VT input (`ENABLE_VIRTUAL_TERMINAL_INPUT`), and restore the original modes on every exit path.
- Batch files must use CRLF endings, quote paths with spaces, escape shell metacharacters, and check `errorlevel` after each `call`.
- Prefer `asyncio.create_subprocess_exec` over shelling out; do not use `os.system` or `shell=True`.
- Deleting a browser profile while the engine is running may raise `PermissionError`; kill the process tree first, then retry.

## Browser and engine pitfalls
- Zen/Firefox use a throwaway profile and `--no-remote`; never touch the real user profile.
- The browser endpoint is on `127.0.0.1` only, and the app must log the exact launch command and stderr tail.
- There is no CDP backend for Firefox/Gecko; use BiDi and treat any missing endpoint as a logged failure.

## Rendering pitfalls
- Strip control characters and escape sequences from all page-supplied strings before drawing to the terminal.
- Keep the half-block path as the fallback when Sixel or chafa are unavailable.
- Do not assume terminal support for Sixel; detect it and log the result.

## General pitfall
- Do not layer fixes on top of a broken state; return to the last green tag and continue from there.
