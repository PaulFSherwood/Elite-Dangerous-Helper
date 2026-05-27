#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from journal import JournalMonitor, resolve_journal_dir
from ui import OverlayWindow


def main() -> None:
    parser = argparse.ArgumentParser(description="Elite Dangerous Linux overlay")
    parser.add_argument("--journal-dir", help="Elite Dangerous journal folder")
    parser.add_argument("--no-top", action="store_true", help="Disable always-on-top window")
    parser.add_argument(
        "--history-files",
        type=int,
        default=30,
        help="Number of recent journal files to read on startup",
    )

    args = parser.parse_args()

    journal_dir = resolve_journal_dir(args.journal_dir)

    if not journal_dir.exists():
        print(f"Journal directory not found: {journal_dir}")
        return

    app = QApplication(sys.argv)

    icon_path = Path(__file__).resolve().parent / "assets" / "ed_helper_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    monitor = JournalMonitor(journal_dir, history_files=args.history_files)
    monitor.start()

    window = OverlayWindow(monitor, always_on_top=not args.no_top)
    window.show()
    window.raise_()
    window.activateWindow()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
