#!/usr/bin/env bash
set -euo pipefail

APP_ID="elite-journal-helper"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"

rm -rf "$DATA_HOME/$APP_ID"
rm -f "$DATA_HOME/applications/$APP_ID.desktop"
rm -f "$DATA_HOME/icons/hicolor/256x256/apps/$APP_ID.png"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA_HOME/applications" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" || true

echo "Elite Journal Helper removed."
