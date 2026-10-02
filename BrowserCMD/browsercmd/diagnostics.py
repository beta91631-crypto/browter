"""Best-effort diagnostics that use only the Python standard library."""

from __future__ import annotations

import importlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from .logging_setup import redact_text
from .browser import BROWSER_FLAGS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BROWSER_NAMES = {
    "Brave": ("brave.exe", "brave", "brave-browser"),
    "Edge": ("msedge.exe", "msedge", "microsoft-edge"),
    "Chrome": ("chrome.exe", "chrome", "google-chrome"),
}


def _browser_candidates() -> dict[str, str | None]:
    roots = [
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")),
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")),
        Path(os.environ.get("LOCALAPPDATA", "C:/Users/Default/AppData/Local")),
    ]
    known = {
        "Brave": (
            "BraveSoftware/Brave-Browser/Application/brave.exe",
        ),
        "Edge": ("Microsoft/Edge/Application/msedge.exe",),
        "Chrome": ("Google/Chrome/Application/chrome.exe",),
    }
    found: dict[str, str | None] = {}
    for label, names in BROWSER_NAMES.items():
        path = next((shutil.which(name) for name in names if shutil.which(name)), None)
        if path is None:
            for root in roots:
                path = next((str(root / relative) for relative in known[label] if (root / relative).is_file()), None)
                if path:
                    break
        found[label] = path
    return found


def _run_capture(command: list[str], timeout: float = 8) -> tuple[int | None, str, list[str], bool]:
    with tempfile.TemporaryFile(mode="w+b") as stderr_file:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=stderr_file, shell=False)
        timed_out = False
        try:
            stdout, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            stdout, _ = process.communicate()
        stderr_file.flush()
        stderr_file.seek(0, os.SEEK_END)
        size = stderr_file.tell()
        stderr_file.seek(max(0, size - 256 * 1024))
        stderr_tail = stderr_file.read().decode("utf-8", errors="replace").splitlines()[-50:]
    return process.returncode, stdout.decode("utf-8", errors="replace"), stderr_tail, timed_out


def _browser_version(path: str) -> str:
    try:
        code, stdout, stderr, timed_out = _run_capture([path, "--version"], timeout=5)
        version = stdout.strip() or (stderr[-1] if stderr else "unknown")
        return redact_text(f"{version} (exit={code}, timeout={timed_out})")
    except (OSError, subprocess.SubprocessError) as error:
        return redact_text(f"unavailable: {type(error).__name__}: {error}")


def _cdp_test(port: int) -> str:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3) as response:
            version_info = json.load(response)
        endpoint = version_info["webSocketDebuggerUrl"]
        websockets = importlib.import_module("websockets.sync.client")
        with websockets.connect(endpoint, open_timeout=3) as connection:
            connection.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": "1+1"}}))
            result = json.loads(connection.recv())
        value = result.get("result", {}).get("result", {}).get("value")
        return f"VERIFIED WebSocket CDP Runtime.evaluate result={value!r}"
    except ImportError:
        return "UNTESTED websockets package unavailable; HTTP DevTools endpoint was not handshaken"
    except Exception as error:
        return redact_text(f"FAILED {type(error).__name__}: {error}")


def _browser_launch_test(path: str) -> list[str]:
    lines: list[str] = []
    with tempfile.TemporaryDirectory(prefix="BrowserCMD-diagnose-") as profile:
        active_file = Path(profile) / "DevToolsActivePort"
        command = [path, *BROWSER_FLAGS, f"--user-data-dir={profile}", "about:blank"]
        lines.append(f"Launch command: {redact_text(json.dumps(command))}")
        with tempfile.TemporaryFile(mode="w+b") as stderr_file:
            try:
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=stderr_file, shell=False)
            except OSError as error:
                return lines + [f"Launch: FAILED {type(error).__name__}: {error}"]
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not active_file.is_file() and process.poll() is None:
                time.sleep(0.1)
            port: int | None = None
            if active_file.is_file():
                try:
                    port = int(active_file.read_text(encoding="utf-8").splitlines()[0])
                except (OSError, ValueError, IndexError):
                    pass
            if port:
                lines.append(f"Launch: DevToolsActivePort={port}")
                lines.append(f"CDP handshake: {_cdp_test(port)}")
            else:
                lines.append("Launch: FAILED; DevToolsActivePort not created within 10 seconds")
            if process.poll() is None:
                process.terminate()
                try:
                    exit_code = process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    exit_code = process.wait()
            else:
                exit_code = process.returncode
            stderr_file.flush()
            stderr_file.seek(0, os.SEEK_END)
            size = stderr_file.tell()
            stderr_file.seek(max(0, size - 256 * 1024))
            tail = stderr_file.read().decode("utf-8", errors="replace").splitlines()[-50:]
            lines.append(f"Browser exit code: {exit_code}")
            lines.extend(f"Browser stderr: {line}" for line in tail)
    return lines


def generate_report(project_root: Path = PROJECT_ROOT) -> str:
    lines = [
        "BrowserCMD diagnostic report",
        f"OS: {platform.platform()}",
        f"Python version: {sys.version.replace(os.linesep, ' ')}",
        f"Python path: {sys.executable}",
        f"pip freeze command: {json.dumps([sys.executable, '-m', 'pip', 'freeze'])}",
    ]
    code, frozen, stderr, timed_out = _run_capture([sys.executable, "-m", "pip", "freeze"])
    lines.append(f"pip freeze exit code: {code}; timed_out={timed_out}")
    lines.extend(f"pip: {line}" for line in frozen.splitlines())
    lines.extend(f"pip stderr: {line}" for line in stderr)
    lines.append(f"venv exists: {(project_root / '.venv').is_dir()}")

    browsers = _browser_candidates()
    for label, path in browsers.items():
        lines.append(f"{label}: {path or 'not found'}")
        if path:
            lines.append(f"{label} version: {_browser_version(path)}")
    browser = next((browsers[name] for name in ("Brave", "Edge", "Chrome") if browsers[name]), None)
    if browser:
        lines.extend(_browser_launch_test(browser))
    else:
        lines.append("Browser launch/CDP handshake: UNTESTED; no supported browser found")

    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            lines.append(f"Localhost port bind: VERIFIED port={listener.getsockname()[1]}")
    except OSError as error:
        lines.append(f"Localhost port bind: FAILED {type(error).__name__}: {error}")

    size = shutil.get_terminal_size(fallback=(0, 0))
    color = os.environ.get("COLORTERM") or os.environ.get("TERM", "unknown")
    lines.append(f"Terminal size: {size.columns}x{size.lines}")
    lines.append(f"Truecolor strip: advertised={color}; visual output not detectable in a report")
    lines.append("Half-block test: U+2580 (▀) encodes; visual output not detectable in a report")
    lines.append("Sixel query result: not detected; no interactive terminal response collected")

    try:
        pixel = importlib.import_module("browsercmd.pixel")
        lines.append(f"Image pipeline self-test: {pixel.self_test()}")
    except (ImportError, AttributeError) as error:
        lines.append(f"Image pipeline self-test: UNTESTED {type(error).__name__}: {error}")
    return redact_text("\n".join(lines) + "\n")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Write a BrowserCMD diagnostic report")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "diagnostic.txt")
    args = parser.parse_args()
    report = generate_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Diagnostic report written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())