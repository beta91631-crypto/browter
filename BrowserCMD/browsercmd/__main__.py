"""BrowserCMD startup and logging smoke-test entry point."""

from __future__ import annotations

import argparse

from . import __version__
from .logging_setup import install_exception_hooks, setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="BrowserCMD terminal browser")
    parser.add_argument("--debug", action="store_true", help="Enable additional diagnostic detail")
    parser.add_argument("--crash-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"BrowserCMD {__version__}")
    args = parser.parse_args()
    logger, path = setup_logging(config={"debug": args.debug})
    install_exception_hooks(logger, path)
    if args.crash_test:
        raise RuntimeError("Deliberate logging crash test")
    logger.info("Startup complete; browser navigation is not implemented yet")
    print(f"BrowserCMD {__version__}: startup logging ready. Session log: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())