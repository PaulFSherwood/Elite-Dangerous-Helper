#!/usr/bin/env python3
"""Compatibility launcher for Elite Journal Helper.

Keep this filename at the project/install root so existing desktop shortcuts,
shell aliases, and user launch commands continue to work while the application
implementation lives in ``src/elite_journal_helper``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from elite_journal_helper.app import main


if __name__ == "__main__":
    main()
