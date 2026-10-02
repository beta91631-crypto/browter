# BrowserCMD Plan

Capability selected for this run: L1. Follow phases in order; Windows and browser adapters remain explicitly untested without the required environment.

| Phase | Scope | Acceptance |
|---|---|---|
| P0 | Environment report, scaffold, runtime logging, Windows launcher/diagnostic/log collection scripts, project docs | Python logging tests pass; Windows scripts are delivered and marked untested here. |
| P1 | Browser process launch, fallback, and CDP handshake adapter | Pure process/error behavior tested where possible; browser launch/CDP marked untested at L1. |
| P2 | Pixel-art pipeline and settings | Unit and deterministic output tests pass; standalone command runs. |
| P3 | DOM-to-block extraction and local fixtures | Fixture outputs match expected blocks, including malicious text and Arabic. |
| P4 | Text/image layout and cell-diff renderer | Fake-terminal behavior and golden captures pass. |
| P5 | Navigation and interaction adapter | Windows/browser interaction marked untested at L1. |
| P6 | Live settings and image cache | Pure config/cache behavior tested; browser/background integration marked untested where unavailable. |
| P7 | Hardening, performance, and documentation | Security/limits tests pass; unavailable performance budgets are marked untested. |

Scope guard: implement only the requested terminal browser in `BrowserCMD/`; do not modify `YoutubePlayerCMD/` or unrelated files.