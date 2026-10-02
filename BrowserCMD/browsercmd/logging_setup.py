"""Bounded, redacted session logging for BrowserCMD."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import TextIO
from urllib.parse import urlsplit, urlunsplit

from . import __version__

MAX_LOG_BYTES = 5 * 1024 * 1024
MAX_LOGS = 10
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_HEADER_SECRET_RE = re.compile(
    r"(?im)\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*[:=][^\r\n]*"
)
_VALUE_SECRET_RE = re.compile(
    r"""(?i)(?P<lead>--?(?:access[_-]?token|refresh[_-]?token|api[_-]?key|token|password|passwd|secret|auth[_-]?token)\b(?:=|\s+)|\b(?:access[_-]?token|refresh[_-]?token|api[_-]?key|token|password|passwd|secret|auth[_-]?token)[\"']?\s*[:=]\s*)(?P<quote>[\"']?)(?P<value>[^\s,;&\"']+)(?P=quote)"""
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _clean_url(match: re.Match[str]) -> str:
    value = match.group(0)
    suffix = ""
    while value and value[-1] in "),.;]}:":
        suffix = value[-1] + suffix
        value = value[:-1]
    try:
        parts = urlsplit(value)
        host = parts.netloc.rsplit("@", 1)[-1]
        value = urlunsplit((parts.scheme, host, parts.path, "", ""))
    except ValueError:
        value = "<redacted-url>"
    return value + suffix


def redact_text(value: str) -> str:
    """Remove URL query/fragment data and common credential values."""
    value = _URL_RE.sub(_clean_url, value)
    value = _HEADER_SECRET_RE.sub(lambda match: match.group(0).split(":", 1)[0] + ": <redacted>", value)
    value = _VALUE_SECRET_RE.sub(
        lambda match: f"{match.group('lead')}{match.group('quote')}<redacted>{match.group('quote')}",
        value,
    )
    return _CONTROL_RE.sub("", value)


class _CappedFileHandler(logging.Handler):
    def __init__(self, path: Path, max_bytes: int) -> None:
        super().__init__()
        self.path = path
        self.max_bytes = max_bytes
        self._written = path.stat().st_size if path.exists() else 0
        self._capped = self._written >= max_bytes
        self._stream = path.open("ab")

    def emit(self, record: logging.LogRecord) -> None:
        if self._capped:
            return
        try:
            payload = (self.format(record) + "\n").encode("utf-8", errors="replace")
            remaining = self.max_bytes - self._written
            if len(payload) > remaining:
                marker = b"[WARN] Log size limit reached; further entries omitted.\n"
                payload = (payload[: max(0, remaining - len(marker))] + marker)[:remaining]
                self._capped = True
            self._stream.write(payload)
            self._stream.flush()
            self._written += len(payload)
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        try:
            self._stream.close()
        finally:
            super().close()


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def _terminal_info() -> str:
    terminal = "Windows Terminal" if os.environ.get("WT_SESSION") else (
        "conhost" if os.name == "nt" else "POSIX TTY" if sys.stdout.isatty() else "captured output"
    )
    size = shutil.get_terminal_size(fallback=(0, 0))
    color = os.environ.get("COLORTERM") or os.environ.get("TERM", "unknown")
    return f"type={terminal}, size={size.columns}x{size.lines}, color={color}, sixel=not detected"


def _browser_info() -> tuple[str, str]:
    names = ("brave", "brave-browser", "msedge", "microsoft-edge", "chrome", "google-chrome", "chromium")
    for name in names:
        path = shutil.which(name)
        if path:
            return path, "not queried"
    return "not detected", "unknown"


def _prune_logs(directory: Path, protected: Path | None = None, keep: int = MAX_LOGS) -> None:
    logs = sorted(directory.glob("session-*.txt"), key=lambda item: item.stat().st_mtime, reverse=True)
    retained = set(logs[:keep])
    if protected is not None:
        retained.add(protected)
    for path in logs:
        if path not in retained:
            path.unlink(missing_ok=True)


def setup_logging(
    logs_dir: Path | str | None = None,
    config: dict[str, object] | None = None,
    max_bytes: int = MAX_LOG_BYTES,
) -> tuple[logging.Logger, Path]:
    """Create a new session log and retain at most ten session files."""
    if logs_dir is None:
        logs_dir = os.environ.get("BROWSERCMD_LOGS_DIR") or Path(__file__).resolve().parents[1] / "logs"
    directory = Path(logs_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = directory / f"session-{stamp}.txt"
    if path.exists():
        path = directory / f"session-{stamp}-{os.getpid()}.txt"

    logger = logging.getLogger(f"browsercmd.{path.stem}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    handler = _CappedFileHandler(path, max_bytes)
    handler.setFormatter(_RedactingFormatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)

    browser_path, browser_version = _browser_info()
    logger.info("BrowserCMD version: %s", __version__)
    logger.info("OS version: %s", platform.platform())
    logger.info("Python version: %s", sys.version.replace("\n", " "))
    logger.info("Terminal: %s", _terminal_info())
    logger.info("Browser path: %s; version: %s", browser_path, browser_version)
    logger.info("Config: %s", json.dumps(config or {}, sort_keys=True, ensure_ascii=True))
    _prune_logs(directory, protected=path)
    return logger, path


def _stderr_tail(stream: TextIO, max_bytes: int = 256 * 1024) -> list[str]:
    stream.flush()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(max(0, size - max_bytes))
    text = stream.read().decode("utf-8", errors="replace")
    return text.splitlines()[-50:]


def run_child(
    command: list[str], logger: logging.Logger, timeout: float | None = None
) -> int:
    """Run a child without a shell and log its redacted command, status, and stderr tail."""
    args = [str(part) for part in command]
    rendered = redact_text(shlex.join(args))
    logger.info("Child process start: command=%s", rendered)
    started = time.monotonic()
    with tempfile.TemporaryFile(mode="w+b") as stderr_file:
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=stderr_file, shell=False)
        timed_out = False
        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            exit_code = process.wait()
        tail = _stderr_tail(stderr_file)
    logger.log(
        logging.ERROR if exit_code else logging.INFO,
        "Child process exit: command=%s exit_code=%s timed_out=%s elapsed_ms=%.1f",
        rendered,
        exit_code,
        timed_out,
        (time.monotonic() - started) * 1000,
    )
    for line in tail:
        logger.error("Child stderr: %s", line)
    return exit_code


def handle_uncaught_exception(
    logger: logging.Logger,
    exc_info: tuple[type[BaseException], BaseException, object],
    output: TextIO = sys.stderr,
    input_stream: TextIO = sys.stdin,
    pause_on_crash: bool | None = None,
    log_path: Path | None = None,
) -> None:
    logger.critical("Unhandled exception", exc_info=exc_info)
    if log_path is None:
        handlers = [handler for handler in logger.handlers if isinstance(handler, _CappedFileHandler)]
        log_path = handlers[0].path if handlers else Path("logs/session-unknown.txt")
    if output.isatty():
        output.write("\x1b[0m\x1b[?25h\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?2026l\x1b[?1049l\n")
    output.write(f"BrowserCMD crashed. Log saved: {log_path}\n")
    output.flush()
    should_pause = os.name == "nt" if pause_on_crash is None else pause_on_crash
    if should_pause and input_stream.isatty():
        try:
            input_stream.readline()
        except (EOFError, OSError):
            pass


def install_exception_hooks(logger: logging.Logger, log_path: Path) -> None:
    def handle(exc_type: type[BaseException], exc: BaseException, traceback: object) -> None:
        handle_uncaught_exception(logger, (exc_type, exc, traceback), log_path=log_path)

    sys.excepthook = handle

    def handle_thread(args: threading.ExceptHookArgs) -> None:
        handle_uncaught_exception(
            logger,
            (args.exc_type, args.exc_value, args.exc_traceback),
            log_path=log_path,
        )

    threading.excepthook = handle_thread