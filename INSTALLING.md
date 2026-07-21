# Installing Elite Journal Helper

Put these scripts in the project root beside `ed_journal_probe.py`.

## KDE Plasma or GNOME

```bash
chmod +x install-user.sh uninstall-user.sh
./install-user.sh
```

This installs to:

```text
~/.local/share/elite-journal-helper
~/.local/share/applications/elite-journal-helper.desktop
~/.local/share/icons/hicolor/256x256/apps/elite-journal-helper.png
```

Both KDE Plasma and GNOME use the same `.desktop` launcher.

Remove it with:

```bash
./uninstall-user.sh
```

## Windows

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install-windows.ps1
```

Add a desktop shortcut too:

```powershell
.\install-windows.ps1 -DesktopShortcut
```

The Windows installer copies the app into `%LOCALAPPDATA%\EliteJournalHelper`,
creates a private Python virtual environment, installs PyQt6 and watchdog,
and adds a Start Menu shortcut.

For a custom Windows icon, add `assets\ed_helper_icon.ico`. Windows shortcuts
do not reliably use PNG files as icons.

Remove it with:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\uninstall-windows.ps1
```
