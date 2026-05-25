# Elite Journal Helper

A small Linux-native helper for **Elite Dangerous** exploration.
<img width="1121" height="547" alt="image" src="https://github.com/user-attachments/assets/1aac591c-23ac-4fbc-bee9-e254bff26b19" />

The app watches Elite Dangerous journal logs, updates live as the game writes new events, and shows an always-on-top PyQt6 window with system, body, DSS, exobiology, and special-signal information.

## Current Status

This repo is currently centered around one Python file:

```text
ed_journal_probe.py
```

## Features

- Live watches the newest `Journal*.log` file.
- Uses Linux file monitoring through `watchdog` / inotify.
- Shows an always-on-top PyQt6 window.
- Displays current system, body/location, ship/suit state, and last journal event.
- Shows stars, planets, belts, and discovered bodies in a table.
- Tracks DSS mapping status.
- Tracks biological signal counts.
- Tracks exobiology sampling progress.
- Uses colored Bio Status pills:
  - Gray = expected organic, not found yet.
  - Green = found / sampling started.
  - Purple with check mark = final `Analyse` / 3-of-3 completed.
- Sorts important bodies toward the top.
- Highlights high-value DSS targets:
  - Earth-like worlds
  - Water worlds
  - Ammonia worlds
  - Terraformable high metal content worlds
  - Terraformable rocky bodies
- Adds soft candidate notes for:
  - Guardian candidate bodies
  - Thargoid-interest ammonia bodies
- Watches for special signal keywords such as:
  - Guardian
  - Thargoid
  - Non-Human
  - Notable Stellar Phenomena
  - Listening Post
  - Unregistered signals
  - Ancient ruins / structures
  - Barnacles
  - Anomalies

## Install on Ubuntu / Kubuntu

Install the required packages:

```bash
sudo apt update
sudo apt install python3 python3-pyqt6 python3-watchdog
```

## Run

From the repo folder:

```bash
python3 ed_journal_probe.py --history-files 300
```

Or run with a full path:

```bash
python3 ~/Documents/src/elite-journal-helper/ed_journal_probe.py
```

Adjust the path if you cloned the repo somewhere else.

## Optional Alias

For Bash:

```bash
echo "alias edHelper='python3 ~/Documents/src/elite-journal-helper/ed_journal_probe.py'" >> ~/.bashrc
source ~/.bashrc
```

Then launch with:

```bash
edHelper
```

For Zsh:

```bash
echo "alias edHelper='python3 ~/Documents/src/elite-journal-helper/ed_journal_probe.py'" >> ~/.zshrc
source ~/.zshrc
```

## Journal Folder

The app tries to auto-detect the Elite Dangerous journal folder.

Common Steam / Proton locations:

```text
~/.steam/debian-installation/steamapps/compatdata/359320/pfx/drive_c/users/steamuser/Saved Games/Frontier Developments/Elite Dangerous
```

```text
~/.local/share/Steam/steamapps/compatdata/359320/pfx/drive_c/users/steamuser/Saved Games/Frontier Developments/Elite Dangerous
```

You can also pass the journal folder manually:

```bash
python3 ed_journal_probe.py --journal-dir "/path/to/Elite Dangerous"
```

## UI Meaning

### Mapped

`Mapped` means **DSS probe mapping completed**, not merely FSS scanned, landed on, or exobiology-scanned.

- Green `Yes` = DSS complete.
- Orange/Yellow `No` = DSS not complete.
- Blank = not a DSS-mappable body, such as a star or belt cluster.

### Bio Status

The Bio Status column tracks exobiology separately from DSS mapping.

Pill colors:

```text
Gray      = expected genus, not found yet
Green     = found / sampling started
Purple ✓  = final Analyse / 3-of-3 completed
```

Example progression:

```text
[Bacterium] [Fonticula] [Fungoida] [Osseus]
[Bacterium] [Fonticula] [• Fungoida] [Osseus]
[Bacterium] [Fonticula] [✓ Fungoida] [Osseus]
```

### Priority

The Priority column summarizes what matters most.

Examples:

```text
Water World - DSS NEEDED
Terraformable High metal content body - DSS NEEDED
Bio signals
Bio complete
Guardian candidate
Thargoid-interest ammonia body
```

## Special Alerts

Special alerts are keyword-based. They are attention flags, not proof that something rare exists.

The app checks journal events such as:

```text
FSSSignalDiscovered
SAASignalsFound
CodexEntry
```

Keyword examples:

```text
guardian
thargoid
non-human
xeno
ancient
ruins
guardian structure
guardian beacon
thargoid structure
barnacle
notable stellar phenomena
lagrange
anomaly
unregistered
listening post
```

False positives can happen, so the keyword list may need tuning as more journal examples are seen.

## Guardian Candidate Heuristic

The app can mark a body as a possible Guardian-style candidate when it looks similar to known Guardian ruin body conditions:

```text
Landable
Rocky Body or High Metal Content Body
Surface temperature roughly 180-310 K
Radius roughly 1,000-3,000 km
```

This is only a soft clue.

## Thargoid Interest Heuristic

The app can mark ammonia-related bodies as Thargoid-interest candidates.

This is also only a soft clue. A hard alert should come from an actual journal signal, Codex entry, or FSS event containing wording such as:

```text
Thargoid
Non-Human
Barnacle
Probe
Sensor
```

## Current Limitations

- Currently a single Python file.
- No saved database yet.
- No web dashboard yet.
- No iPhone/mobile dashboard yet.
- No EDSM/Inara/EDDN integration.
- Bio prediction is basic.
- Special alerts may need tuning.
- Old journal data may not always reconstruct all exobiology state perfectly, because some live state depends on the order and presence of journal events.

## Future Ideas

- Split into modules:
  - journal reader
  - state model
  - rules engine
  - UI
  - web server
- Add local SQLite history.
- Add a browser/iPhone dashboard.
- Add desktop notifications or sounds.
- Add flight-plan / route monitoring.
- Add better biological prediction.
- Add exportable exploration session reports.
- Add settings for colors, alerts, and keyword lists.

## Disclaimer

This is an unofficial Elite Dangerous helper tool. It is not affiliated with Frontier Developments.
