#!/usr/bin/env bash
set -euo pipefail

APP_ID="elite-journal-helper"
APP_NAME="Elite Journal Helper"
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_DIR="$DATA_HOME/$APP_ID"
APPLICATIONS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/256x256/apps"
DESKTOP_FILE="$APPLICATIONS_DIR/$APP_ID.desktop"
ICON_FILE="$ICON_DIR/$APP_ID.png"

[[ -f "$SOURCE_DIR/ed_journal_probe.py" ]] || {
  echo "Run this installer from the project folder beside ed_journal_probe.py."
  exit 1
}

mkdir -p "$INSTALL_DIR" "$APPLICATIONS_DIR" "$ICON_DIR"

tar --exclude='.git' --exclude='.github' --exclude='__pycache__' \
    --exclude='*.pyc' --exclude='*.log' --exclude='.venv' \
    --exclude='venv' --exclude='build' --exclude='dist' \
    --exclude='install-user.sh' --exclude='uninstall-user.sh' \
    --exclude='install-windows.ps1' --exclude='uninstall-windows.ps1' \
    -cf - -C "$SOURCE_DIR" . | tar -xf - -C "$INSTALL_DIR"

cp "$INSTALL_DIR/assets/ed_helper_icon.png" "$ICON_FILE"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=$APP_NAME
Comment=Elite Dangerous exploration journal overlay
Exec=python3 "$INSTALL_DIR/ed_journal_probe.py"
Icon=$APP_ID
Terminal=false
StartupNotify=true
Categories=Game;Utility;
Keywords=Elite;Dangerous;Exploration;Journal;Exobiology;
EOF

chmod 644 "$DESKTOP_FILE" "$ICON_FILE"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPLICATIONS_DIR" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" || true

echo "$APP_NAME installed."
echo "Files: $INSTALL_DIR"
echo "Menu shortcut: $DESKTOP_FILE"
