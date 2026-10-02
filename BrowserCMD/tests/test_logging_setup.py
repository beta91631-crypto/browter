import logging
import sys
import tempfile
import unittest
from pathlib import Path
from io import StringIO

from browsercmd.logging_setup import (
    _prune_logs,
    handle_uncaught_exception,
    redact_text,
    run_child,
    setup_logging,
)
from browsercmd.collect_logs import collect


class LoggingSetupTests(unittest.TestCase):
    def test_redacts_url_queries_credentials_and_control_codes(self):
        text = redact_text(
            "open https://user:pass@example.test/p?a=secret, token=abc password='word' "
            "Authorization: Bearer private\x1b[31m"
        )
        self.assertIn("https://example.test/p", text)
        for secret in (
            "user:pass@",
            "a=secret",
            "token=abc",
            "password='word'",
            "Bearer private",
            "\x1b",
        ):
            self.assertNotIn(secret, text)

    def test_header_and_exception_traceback_are_written(self):
        with tempfile.TemporaryDirectory() as directory:
            logger, path = setup_logging(directory, config={"token": "dont-log-me"})
            try:
                raise ValueError("bad input password=top-secret")
            except ValueError:
                exc_info = sys.exc_info()
            handle_uncaught_exception(
                logger,
                exc_info,
                output=StringIO(),
                input_stream=StringIO(),
                pause_on_crash=False,
                log_path=path,
            )
            logger.handlers[0].close()
            content = path.read_text(encoding="utf-8")
            self.assertIn("BrowserCMD version:", content)
            self.assertIn("ValueError: bad input", content)
            self.assertNotIn("dont-log-me", content)
            self.assertNotIn("top-secret", content)

    def test_child_logs_exit_and_last_fifty_stderr_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            logger, path = setup_logging(directory)
            command = [
                sys.executable,
                "-c",
                "import sys; [print(f'line{i}', file=sys.stderr) for i in range(52)]; "
                "print('password=child-secret', file=sys.stderr); sys.exit(7)",
            ]
            self.assertEqual(run_child(command, logger), 7)
            logger.handlers[0].close()
            content = path.read_text(encoding="utf-8")
            self.assertIn("exit_code=7", content)
            self.assertNotIn("Child stderr: line0\n", content)
            self.assertIn("Child stderr: line51", content)
            self.assertNotIn("child-secret", content)

    def test_prunes_to_ten_session_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(12):
                (root / f"session-{index:02}.txt").write_text("log", encoding="utf-8")
            _prune_logs(root, keep=10)
            self.assertEqual(len(list(root.glob("session-*.txt"))), 10)

    def test_session_file_stays_within_configured_size_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            logger, path = setup_logging(directory, max_bytes=1024)
            logger.error("x" * 5000)
            logger.handlers[0].close()
            self.assertLessEqual(path.stat().st_size, 1024)

    def test_support_bundle_uses_last_300_lines_and_redacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / "logs"
            logs.mkdir()
            diagnostic = root / "diagnostic.txt"
            diagnostic.write_text("diagnostic marker", encoding="utf-8")
            (logs / "session-test.txt").write_text(
                "\n".join([f"line{index}" for index in range(305)] + ["https://example.test/?token=hidden"]),
                encoding="utf-8",
            )
            bundle_path = collect(diagnostic, logs, root / "SEND_ME.txt")
            bundle = bundle_path.read_text(encoding="utf-8")
            self.assertIn("diagnostic marker", bundle)
            self.assertIn("line6\n", bundle)
            self.assertNotIn("line5\n", bundle)
            self.assertNotIn("hidden", bundle)


if __name__ == "__main__":
    unittest.main()