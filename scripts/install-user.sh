#!/usr/bin/env bash
set -euo pipefail

APP_ID="elite-journal-helper"
APP_NAME="Elite Journal Helper"
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_DIR="$DATA_HOME/$APP_ID"
APPLICATIONS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/256x256/apps"
DESKTOP_FILE="$APPLICATIONS_DIR/$APP_ID.desktop"
ICON_FILE="$ICON_DIR/$APP_ID.png"

[[ -f "$ROOT_DIR/ed_journal_probe.py" ]] || {
  echo "Could not find ed_journal_probe.py in the project root."
  exit 1
}

rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR" "$APPLICATIONS_DIR" "$ICON_DIR"

tar --exclude='.git' --exclude='.github' --exclude='__pycache__' \
    --exclude='.pytest_cache' --exclude='*.pyc' --exclude='*.log' \
    --exclude='*.sqlite' --exclude='*.sqlite3' --exclude='*.bak' \
    --exclude='*.bak-*' --exclude='*.patch' --exclude='PreviousVersion*' \
    --exclude='.venv' --exclude='venv' --exclude='build' --exclude='dist' \
    --exclude='docs' --exclude='tests' --exclude='tools' --exclude='scripts' \
    --exclude='requirements-dev.txt' \
    -cf - -C "$ROOT_DIR" . | tar -xf - -C "$INSTALL_DIR"

cp "$INSTALL_DIR/assets/ed_helper_icon.png" "$ICON_FILE"

cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=$APP_NAME
Comment=Elite Dangerous exploration and construction journal helper
Exec=python3 "$INSTALL_DIR/ed_journal_probe.py"
Icon=$APP_ID
Terminal=false
StartupNotify=true
Categories=Game;Utility;
Keywords=Elite;Dangerous;Exploration;Journal;Exobiology;Colonisation;Construction;
DESKTOP

chmod 644 "$DESKTOP_FILE" "$ICON_FILE"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPLICATIONS_DIR" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" || true

echo "$APP_NAME installed."
echo "Files: $INSTALL_DIR"
echo "Menu shortcut: $DESKTOP_FILE"
