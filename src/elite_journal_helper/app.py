#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
import time

_PROCESS_START = time.perf_counter()
_PROFILE_STARTUP = False



def _startup_trace(message: str) -> None:
    if not _PROFILE_STARTUP:
        return
    elapsed = time.perf_counter() - _PROCESS_START
    print(f"[startup +{elapsed:6.2f}s] {message}", flush=True)


def main() -> None:
    global _PROFILE_STARTUP

    from .version import APP_NAME, DISPLAY_VERSION

    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--journal-dir", help="Elite Dangerous journal folder")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {DISPLAY_VERSION}",
    )
    parser.add_argument("--no-top", action="store_true", help="Disable always-on-top window")
    parser.add_argument(
        "--profile-startup",
        action="store_true",
        help="Print detailed startup timing diagnostics",
    )
    parser.add_argument(
        "--history-files",
        type=int,
        default=30,
        help="Number of recent journal files to read on startup",
    )

    args = parser.parse_args()
    _PROFILE_STARTUP = bool(args.profile_startup)

    # Keep --help/--version lightweight by delaying Qt imports until after
    # argparse has handled metadata-only commands.
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtGui import QColor, QIcon, QPixmap
    from PyQt6.QtWidgets import QApplication, QSplashScreen

    from .paths import ASSETS_DIR

    app = QApplication(sys.argv)
    _startup_trace("Qt application created")

    # The normal in-window startup overlay cannot appear until OverlayWindow has
    # finished constructing.  Show a tiny splash *before* importing the heavier
    # Observatory modules so a desktop-icon launch gives immediate feedback.
    splash_pixmap = QPixmap(560, 150)
    splash_pixmap.fill(QColor("#081018"))
    splash = QSplashScreen(splash_pixmap)
    splash.showMessage(
        "Observatory is starting…\nLoading application modules",
        Qt.AlignmentFlag.AlignCenter,
        QColor("#D7E9F7"),
    )
    splash.show()
    app.processEvents()
    _startup_trace("Pre-window splash visible")

    from .journal import JournalMonitor, resolve_journal_dir
    _startup_trace("Journal module imported")
    from .ui import OverlayWindow
    _startup_trace("UI modules imported")

    journal_dir = resolve_journal_dir(args.journal_dir)

    if not journal_dir.exists():
        splash.close()
        print(f"Journal directory not found: {journal_dir}")
        return

    icon_path = ASSETS_DIR / "ed_helper_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    splash.showMessage(
        "Observatory is starting…\nBuilding interface",
        Qt.AlignmentFlag.AlignCenter,
        QColor("#D7E9F7"),
    )
    app.processEvents()

    monitor = JournalMonitor(journal_dir, history_files=args.history_files)
    _startup_trace("Journal monitor shell created")
    window = OverlayWindow(
        monitor,
        always_on_top=not args.no_top,
        startup_profile=args.profile_startup,
    )
    _startup_trace("Main window constructed")

    # Show the application immediately. Journal/history reconstruction happens
    # in the background and fills the already-visible fields as data becomes
    # available. The splash covers only the pre-window construction gap; after
    # that the normal full-window loading overlay owns startup progress.
    window.set_startup_loading(True, "Preparing Observatory…")

    def on_startup_progress(message: str) -> None:
        _startup_trace(message)
        window.set_startup_message(message)

    def on_startup_finished() -> None:
        _startup_trace("Startup loading finished")
        window.finish_startup_loading()

    def on_startup_failed(message: str) -> None:
        _startup_trace(f"Startup failed: {message}")
        window.fail_startup_loading(message)

    monitor.startup_progress.connect(on_startup_progress)
    monitor.startup_finished.connect(on_startup_finished)
    monitor.startup_failed.connect(on_startup_failed)

    window.show()
    window.raise_()
    window.activateWindow()
    app.processEvents()
    splash.finish(window)
    _startup_trace("Main window shown")

    # Give the first paint event a chance to put the loading screen on the
    # desktop before the background loader starts doing disk work.
    QTimer.singleShot(75, monitor.start_async)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
