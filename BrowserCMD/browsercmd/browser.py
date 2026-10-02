"""System-browser discovery, bounded process management, and CDP transport."""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus, urlsplit

from .logging_setup import redact_text

BROWSER_FLAGS = ("--headless", "--remote-debugging-port=0")
MAX_URL_LENGTH = 8192
MAX_CDP_MESSAGE_BYTES = 4 * 1024 * 1024
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


class BrowserStartError(RuntimeError):
    pass


class CDPError(RuntimeError):
    pass


def discover_browsers() -> list[tuple[str, str]]:
    """Return installed browser executables in the required fallback order."""
    labels = (
        ("Brave", ("brave.exe", "brave", "brave-browser")),
        ("Edge", ("msedge.exe", "msedge", "microsoft-edge")),
        ("Chrome", ("chrome.exe", "chrome", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser")),
    )
    found: list[tuple[str, str]] = []
    for label, names in labels:
        path = next((shutil.which(name) for name in names if shutil.which(name)), None)
        if path:
            found.append((label, path))
    return found


def browser_command(executable: str, profile: str | Path) -> list[str]:
    return [executable, *BROWSER_FLAGS, f"--user-data-dir={profile}", "about:blank"]


def validate_url(value: str) -> str:
    """Accept only HTTP(S) navigation and the blank internal page."""
    value = value.strip()
    if len(value) > MAX_URL_LENGTH:
        raise ValueError("URL exceeds the 8192-character limit")
    if value == "about:blank":
        return value
    if any(ord(character) < 32 or 0x7F <= ord(character) <= 0x9F for character in value):
        raise ValueError("URL contains control characters")
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError(f"Blocked URL scheme: {parts.scheme or 'missing'}")
    if not parts.hostname or parts.username is not None or parts.password is not None:
        raise ValueError("URL must include a host and must not contain credentials")
    try:
        _ = parts.port
    except ValueError as error:
        raise ValueError("URL contains an invalid port") from error
    return value


def navigation_target(address: str) -> str:
    """Resolve an address or route plain search terms to DuckDuckGo."""
    value = address.strip()
    if not value:
        raise ValueError("Enter a URL or search terms")
    if value == "about:blank":
        return value
    if value.startswith("//"):
        return validate_url(f"https:{value}")
    if re.match(r"^[^/:]+:\d+(?:/|$)", value):
        return validate_url(f"https://{value}")
    if _SCHEME_RE.match(value):
        return validate_url(value)
    if any(character.isspace() for character in value):
        return f"https://duckduckgo.com/?q={quote_plus(value)}"
    return validate_url(value if value.startswith("//") else f"https://{value}")


@dataclass
class BrowserSession:
    name: str
    executable: str
    command: list[str]
    process: subprocess.Popen[bytes]
    profile: tempfile.TemporaryDirectory[str]
    port: int
    websocket_path: str
    logger: logging.Logger
    stderr_tail: deque[str] = field(default_factory=lambda: deque(maxlen=50))
    stderr_thread: threading.Thread | None = None
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.process.poll() is None:
            self.process.terminate()
            try:
                exit_code = self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                exit_code = self.process.wait()
        else:
            exit_code = self.process.returncode
        if self.stderr_thread is not None:
            self.stderr_thread.join(timeout=1)
        self.logger.info(
            "Browser child exit: command=%s exit_code=%s stderr_tail=%s",
            redact_text(shlex.join(self.command)),
            exit_code,
            list(self.stderr_tail),
        )
        self.profile.cleanup()


def _drain_stderr(process: subprocess.Popen[bytes], tail: deque[str]) -> None:
    stream = process.stderr
    if stream is None:
        return
    try:
        for line in iter(stream.readline, b""):
            decoded = line.decode("utf-8", errors="replace").rstrip("\r\n")
            tail.append(decoded[-4096:])
    finally:
        stream.close()


def _stop_process(process: subprocess.Popen[bytes]) -> int | None:
    if process.poll() is not None:
        return process.returncode
    process.terminate()
    try:
        return process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait()


def _failed_launch(
    logger: logging.Logger,
    name: str,
    command: list[str],
    process: subprocess.Popen[bytes] | None,
    tail: deque[str],
    reason: str,
    stderr_thread: threading.Thread | None = None,
) -> None:
    exit_code = _stop_process(process) if process is not None else "not_started"
    if stderr_thread is not None:
        stderr_thread.join(timeout=1)
    logger.error(
        "Browser launch failed: browser=%s command=%s exit_code=%s reason=%s stderr_tail=%s",
        name,
        redact_text(shlex.join(command)),
        exit_code,
        reason,
        list(tail),
    )


def start_browser(
    logger: logging.Logger,
    candidates: list[tuple[str, str]] | None = None,
    ready_timeout: float = 10,
    poll_interval: float = 0.1,
    popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> BrowserSession:
    """Try browsers in order and return once DevToolsActivePort is ready."""
    choices = discover_browsers() if candidates is None else candidates
    if not choices:
        logger.error("Browser launch failed: no supported browser executable found")
        raise BrowserStartError("No supported browser found (tried Brave, Edge, Chrome)")

    failures: list[str] = []
    for name, executable in choices:
        profile = tempfile.TemporaryDirectory(prefix="BrowserCMD-")
        command = browser_command(executable, profile.name)
        tail: deque[str] = deque(maxlen=50)
        process: subprocess.Popen[bytes] | None = None
        stderr_thread: threading.Thread | None = None
        logger.info("Browser child start: browser=%s command=%s", name, redact_text(shlex.join(command)))
        try:
            process = popen_factory(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, shell=False)
        except OSError as error:
            profile.cleanup()
            reason = f"start error {type(error).__name__}: {error}"
            _failed_launch(logger, name, command, None, tail, reason)
            failures.append(f"{name}: {reason}")
            continue

        stderr_thread = threading.Thread(target=_drain_stderr, args=(process, tail), daemon=True)
        stderr_thread.start()
        active_port = Path(profile.name) / "DevToolsActivePort"
        deadline = time.monotonic() + ready_timeout
        port: int | None = None
        websocket_path: str | None = None
        reason = "DevToolsActivePort timeout"
        while time.monotonic() < deadline:
            exit_code = process.poll()
            if exit_code is not None:
                reason = f"browser exited before DevToolsActivePort (exit code {exit_code})"
                break
            if active_port.is_file():
                try:
                    lines = active_port.read_text(encoding="utf-8").splitlines()
                    port = int(lines[0])
                    websocket_path = lines[1]
                    if 0 < port < 65536 and websocket_path.startswith("/devtools/browser/"):
                        break
                    port = None
                    websocket_path = None
                except (OSError, ValueError, IndexError):
                    reason = "invalid DevToolsActivePort contents"
            time.sleep(poll_interval)

        if port is not None and websocket_path is not None:
            logger.info("Browser ready: browser=%s port=%d websocket_path=%s", name, port, websocket_path)
            session = BrowserSession(
                name,
                executable,
                command,
                process,
                profile,
                port,
                websocket_path,
                logger,
                tail,
                stderr_thread,
            )
            atexit.register(session.close)
            return session

        _failed_launch(logger, name, command, process, tail, reason, stderr_thread)
        profile.cleanup()
        failures.append(f"{name}: {reason}; stderr={list(tail)}")

    logger.error("All browser candidates failed: %s", failures)
    raise BrowserStartError("Unable to start a browser: " + "; ".join(failures))


class CDPClient:
    """Small request/response CDP client over a local asyncio WebSocket."""

    def __init__(self, websocket: object, logger: logging.Logger, timeout: float = 10) -> None:
        self.websocket = websocket
        self.logger = logger
        self.timeout = timeout
        self._next_id = 0

    @classmethod
    async def connect(cls, session: BrowserSession, logger: logging.Logger, timeout: float = 10) -> CDPClient:
        endpoint = f"ws://127.0.0.1:{session.port}{session.websocket_path}"
        try:
            import websockets

            websocket = await websockets.connect(
                endpoint,
                open_timeout=timeout,
                close_timeout=timeout,
                max_size=MAX_CDP_MESSAGE_BYTES,
            )
            logger.info("CDP connected: endpoint=%s", redact_text(endpoint))
            return cls(websocket, logger, timeout)
        except Exception as error:
            logger.exception("CDP connect failed: endpoint=%s", redact_text(endpoint))
            raise CDPError(f"CDP connection failed: {type(error).__name__}") from error

    async def command(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        self._next_id += 1
        request_id = self._next_id
        message = {"id": request_id, "method": method, "params": params or {}}
        try:
            async with asyncio.timeout(self.timeout):
                await self.websocket.send(json.dumps(message))
                while True:
                    response = json.loads(await self.websocket.recv())
                    if response.get("id") != request_id:
                        continue
                    if "error" in response:
                        self.logger.error("CDP command failed: method=%s error=%s", method, response["error"])
                        raise CDPError(f"CDP command {method} failed")
                    result = response.get("result", {})
                    return result if isinstance(result, dict) else {}
        except CDPError:
            raise
        except Exception as error:
            self.logger.exception("CDP request failed: method=%s", method)
            raise CDPError(f"CDP request {method} failed: {type(error).__name__}") from error

    async def close(self) -> None:
        try:
            await self.websocket.close()
            self.logger.info("CDP disconnected")
        except Exception:
            self.logger.exception("CDP disconnect failed")