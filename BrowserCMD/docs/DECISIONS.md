# Decisions

- P0 uses only Python's standard library for logging and diagnostic collection so reports remain available when optional runtime dependencies are missing.
- Logs default to redacting URL query/fragment data and common credential keys. Debug mode does not disable redaction.
- Browser and CDP behavior remains deferred to P1; no browser flags or CDP exchange have been runtime-verified in this L1 environment.
- DOM extraction strategy (Runtime.evaluate versus DOMSnapshot/accessibility tree) is not yet selected; decide in P3 after fixture evidence.