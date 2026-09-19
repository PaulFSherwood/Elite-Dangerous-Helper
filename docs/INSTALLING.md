# Installing Elite Journal Helper

You can run Elite Journal Helper directly from the repository or install a desktop/menu shortcut.

## Linux: run from the repository

Install the required packages:

```bash
sudo apt update
sudo apt install python3 python3-pyqt6 python3-watchdog
```

Then run:

```bash
python3 ed_journal_probe.py
```

## Linux: user desktop installation

From the repository root:

```bash
chmod +x scripts/install-user.sh scripts/uninstall-user.sh
./scripts/install-user.sh
```

The installer copies the app to:

```text
~/.local/share/elite-journal-helper
```

and creates the normal desktop/menu integration under `~/.local/share`.

Remove it with:

```bash
./scripts/uninstall-user.sh
```

## Windows

Open PowerShell in the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-windows.ps1
```

To create a desktop shortcut too:

```powershell
.\scripts\install-windows.ps1 -DesktopShortcut
```

The installer copies the application to `%LOCALAPPDATA%\EliteJournalHelper`, creates a private Python virtual environment, installs the dependencies from `requirements.txt`, and adds a Start Menu shortcut.

For a custom Windows shortcut icon, provide `assets\ed_helper_icon.ico`. If it is absent, the installer falls back to the Python executable icon.

Remove the application with:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\uninstall-windows.ps1
```

## Journal location override

The app searches the normal Elite Dangerous journal locations. You can override the folder explicitly:

```bash
python3 ed_journal_probe.py --journal-dir "/path/to/Elite Dangerous"
```

or set `ED_JOURNAL_DIR` in the environment.
