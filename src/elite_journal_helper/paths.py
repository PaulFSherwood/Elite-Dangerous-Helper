"""Stable paths to project/runtime resources.

The public launcher remains in the repository/install root for shortcut
compatibility, while Python implementation modules live under ``src/``.
Resources intentionally remain in their existing top-level folders so current
installations and asset layouts do not need a second migration.
"""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]
ASSETS_DIR = PROJECT_ROOT / "assets"
DATA_DIR = PROJECT_ROOT / "data"
STYLES_DIR = PROJECT_ROOT / "styles"
