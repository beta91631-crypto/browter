import asyncio
import importlib.util
import io
import json
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from browsercmd.browser import (
    BROWSER_FLAGS,
    BrowserStartError,
    CDPClient,
    CDPError,
    browser_command,
    navigation_target,
    start_browser,
    validate_url,
)


class FakeProcess:
    def __init__(self, returncode=None, stderr=b"", ready=False, command=None):
        self.returncode = returncode
        self.stderr = io.BytesIO(stderr)
        self.command = command
        if ready:
            profile = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--user-data-dir="))
            (Path(profile) / "DevToolsActivePort").write_text("12345\n/devtools/browser/fake\n")

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class FakeWebSocket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def recv(self):
        return next(self.messages)

    async def close(self):
        return None


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.log_dir = tempfile.TemporaryDirectory()
        self.logger, self.log_path = __import__("browsercmd.logging_setup", fromlist=["setup_logging"]).setup_logging(
            self.log_dir.name
        )

    def tearDown(self):
        for handler in self.logger.handlers[:]:
            handler.close()
            self.logger.removeHandler(handler)
        self.log_dir.cleanup()

    def test_browser_command_uses_only_approved_launch_flags(self):
        command = browser_command("browser.exe", "profile")
        self.assertEqual(command, ["browser.exe", *BROWSER_FLAGS, "--user-data-dir=profile", "about:blank"])
        self.assertNotIn("--no-sandbox", command)
        self.assertNotIn("--disable-web-security", command)

    def test_start_falls_back_after_logged_exit_21(self):
        launched = []

        def popen(command, **kwargs):
            launched.append(command)
            if len(launched) == 1:
                return FakeProcess(returncode=21, stderr=b"startup failed\n", command=command)
            return FakeProcess(ready=True, command=command)

        session = start_browser(
            self.logger,
            [("Brave", "brave.exe"), ("Edge", "msedge.exe")],
            ready_timeout=0.2,
            poll_interval=0.001,
            popen_factory=popen,
        )
        self.assertEqual(session.name, "Edge")
        self.assertEqual(session.port, 12345)
        session.close()
        for handler in self.logger.handlers:
            handler.flush()
        text = self.log_path.read_text(encoding="utf-8")
        self.assertIn("exit code 21", text)
        self.assertIn("stderr_tail=['startup failed']", text)
        self.assertIn("browser=Edge", text)

    def test_no_candidates_fails_clearly(self):
        with self.assertRaisesRegex(BrowserStartError, "No supported browser"):
            start_browser(self.logger, candidates=[])

    def test_navigation_allowlist_and_duckduckgo_search(self):
        self.assertEqual(navigation_target("about:blank"), "about:blank")
        self.assertEqual(navigation_target("example.com"), "https://example.com")
        self.assertEqual(navigation_target("localhost:8080/path"), "https://localhost:8080/path")
        self.assertEqual(navigation_target("//example.com/path"), "https://example.com/path")
        self.assertEqual(navigation_target("hello browser world"), "https://duckduckgo.com/?q=hello+browser+world")
        self.assertEqual(validate_url("https://example.test/a"), "https://example.test/a")
        for blocked in (
            "file:///etc/passwd",
            "javascript:alert(1)",
            "data:text/html,unsafe",
            "chrome://settings",
            "edge://settings",
            "brave://settings",
            "https://user:pass@example.test/",
            "https://example.test/\nunsafe",
        ):
            with self.subTest(blocked=blocked), self.assertRaises(ValueError):
                navigation_target(blocked)

    def test_cdp_request_matches_response_id_and_surfaces_protocol_errors(self):
        websocket = FakeWebSocket(
            [
                json.dumps({"method": "Page.loadEventFired", "params": {}}),
                json.dumps({"id": 1, "result": {"value": 2}}),
                json.dumps({"id": 2, "error": {"message": "bad method"}}),
            ]
        )
        client = CDPClient(websocket, self.logger)

        async def run():
            self.assertEqual(await client.command("Runtime.evaluate", {"expression": "1+1"}), {"value": 2})
            with self.assertRaisesRegex(CDPError, "Runtime.invalid"):
                await client.command("Runtime.invalid")

        asyncio.run(run())
        self.assertEqual(websocket.sent[0]["method"], "Runtime.evaluate")

    @unittest.skipUnless(importlib.util.find_spec("websockets"), "websockets dependency is not installed")
    def test_cdp_connects_to_local_websocket_server(self):
        from websockets.asyncio.server import serve

        async def run():
            async def handler(connection):
                request = json.loads(await connection.recv())
                await connection.send(json.dumps({"id": request["id"], "result": {"ready": True}}))

            async with serve(handler, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]
                session = SimpleNamespace(port=port, websocket_path="/devtools/browser/test")
                client = await CDPClient.connect(session, self.logger, timeout=2)
                result = await client.command("Browser.getVersion")
                await client.close()
                self.assertEqual(result, {"ready": True})

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()