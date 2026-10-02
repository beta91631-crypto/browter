"""Create the single redacted log bundle requested by BrowserCMD support."""

from __future__ import annotations

import argparse
from pathlib import Path

from .logging_setup import redact_text

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def collect(
    diagnostic_path: Path | None = None,
    logs_dir: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    diagnostic_path = diagnostic_path or PROJECT_ROOT / "diagnostic.txt"
    logs_dir = logs_dir or PROJECT_ROOT / "logs"
    output_path = output_path or logs_dir / "SEND_ME.txt"
    sessions = sorted(logs_dir.glob("session-*.txt"), key=lambda path: path.stat().st_mtime, reverse=True)
    sections = ["BrowserCMD support bundle", "", "=== diagnostic.txt ==="]
    sections.append(diagnostic_path.read_text(encoding="utf-8", errors="replace") if diagnostic_path.exists() else "Not found")
    sections.extend(("", "=== newest session log (last 300 lines) ==="))
    if sessions:
        lines = sessions[0].read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
        sections.append("\n".join(lines))
    else:
        sections.append("No session log found")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(redact_text("\n".join(sections)) + "\n", encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect a redacted BrowserCMD support bundle")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    print(f"Support bundle written: {collect(output_path=args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())