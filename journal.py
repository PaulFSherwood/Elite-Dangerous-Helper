from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from state import BodyInfo, CommanderState, cache_current_system, restore_cached_system
from rules import (
    add_unique,
    looks_like_suit,
    record_special_alert,
    resolve_organic_body_name,
    self_safe_bio_complete,
    signal_counts,
    text_has_special_keyword,
    update_candidate_notes,
    upsert_body,
)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False


DEFAULT_JOURNAL_CANDIDATES = [
    "~/.steam/debian-installation/steamapps/compatdata/359320/pfx/drive_c/users/steamuser/Saved Games/Frontier Developments/Elite Dangerous",
    "~/.local/share/Steam/steamapps/compatdata/359320/pfx/drive_c/users/steamuser/Saved Games/Frontier Developments/Elite Dangerous",
]

def resolve_journal_dir(user_path: Optional[str]) -> Path:
    if user_path:
        return Path(user_path).expanduser()

    env_path = os.environ.get("ED_JOURNAL_DIR")
    if env_path:
        return Path(env_path).expanduser()

    for candidate in DEFAULT_JOURNAL_CANDIDATES:
        path = Path(candidate).expanduser()
        if path.exists():
            return path

    return Path(DEFAULT_JOURNAL_CANDIDATES[0]).expanduser()


def newest_journal_file(journal_dir: Path) -> Optional[Path]:
    journals = sorted(journal_dir.glob("Journal*.log"), key=lambda p: p.stat().st_mtime)
    return journals[-1] if journals else None

def set_system(state: CommanderState, system: Optional[str], address: Optional[int], clear: bool) -> None:
    if not system:
        return

    changed = system != state.system or address != state.system_address

    if clear or changed:
        cache_current_system(state)

        state.system = system
        state.system_address = address
        state.body = None
        state.station = None
        state.docked = False

        # Clear old alert banner when entering a new system.
        # The log still keeps history, but the top banner should reflect this system.
        state.special_alerts.clear()
        state.special_seen.clear()

        restore_cached_system(state)
        update_nav_target(state)

        state.log(f"Entered system: {system}")

def update_nav_target(state: CommanderState) -> None:
    if not state.nav_route:
        state.nav_target = None
        state.nav_final = None
        return

    state.nav_final = state.nav_route[-1]

    if not state.system:
        state.nav_target = state.nav_route[0]
        return

    current_lower = state.system.lower()

    for index, system_name in enumerate(state.nav_route):
        if system_name.lower() == current_lower:
            next_index = index + 1
            if next_index < len(state.nav_route):
                state.nav_target = state.nav_route[next_index]
            else:
                state.nav_target = None
            return

    # If current system is not in route, keep first route item as target.
    state.nav_target = state.nav_route[0]

def read_nav_route(state: CommanderState, journal_dir: Path) -> None:
    nav_path = journal_dir / "NavRoute.json"

    if not nav_path.exists():
        state.nav_route = []
        state.nav_target = None
        state.nav_final = None
        return

    try:
        with nav_path.open("r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception as exc:
        state.nave_route = []
        state.nav_target = None
        state.nave_route = None
        state.log(f"NavRoute read error: {exc}")
        return

    route = []
    for item in data.get("Route", []):
        system_name = item.get("StarSystem")
        if system_name:
            route.append(system_name)

    state.nav_route = route
    update_nav_target(state)

    if route:
        state.log(f"NavRoute loaded: {len(route)} systems")
    else:
        state.nav_target = None
        state.nav_final = None
        state.log("NaveRoute cleared")

def apply_event(state: CommanderState, event: dict) -> bool:
    name = event.get("event")
    state.last_event = name
    state.last_timestamp = event.get("timestamp")

    changed = False

    if name == "LoadGame":
        state.commander = event.get("Commander", state.commander)

        loaded_ship = event.get("Ship")
        if looks_like_suit(loaded_ship):
            state.suit = loaded_ship
        elif loaded_ship:
            state.ship = loaded_ship

        changed = True

    elif name == "Loadout":
        loaded_ship = event.get("Ship")
        if loaded_ship and not looks_like_suit(loaded_ship):
            state.ship = loaded_ship
            state.ship_name = event.get("ShipName", state.ship_name)
        changed = True

    elif name == "SuitLoadout":
        state.suit = event.get("SuitName") or event.get("Suit") or state.suit
        changed = True

    elif name == "Embark":
        state.on_foot = False
        ship_type = event.get("ShipType")
        if ship_type and not looks_like_suit(ship_type):
            state.ship = ship_type
        state.ship_name = event.get("ShipName", state.ship_name)
        changed = True

    elif name == "Disembark":
        state.on_foot = True
        changed = True

    elif name == "Location":
        set_system(state, event.get("StarSystem"), event.get("SystemAddress"), clear=False)
        state.body = event.get("Body", state.body)
        state.station = event.get("StationName")
        state.docked = bool(event.get("Docked", False))
        state.latitude = event.get("Latitude")
        state.longitude = event.get("Longitude")
        changed = True

    elif name in ("FSDJump", "CarrierJump"):
        set_system(state, event.get("StarSystem"), event.get("SystemAddress"), clear=True)

        star_class = event.get("StarClass")
        if star_class:
            state.bodies["__arrival_star__"] = BodyInfo(
                name="Arrival star",
                kind="Star",
                subtype=f"Class {star_class}",
                distance_ls=0.0,
                scanned=False,
            )

        changed = True

    elif name == "FSSDiscoveryScan":
        state.body_count = event.get("BodyCount", state.body_count)
        state.non_body_count = event.get("NonBodyCount", state.non_body_count)
        state.log(f"Honk complete: {state.body_count} bodies detected")
        changed = True

    elif name == "FSSAllBodiesFound":
        state.body_count = event.get("Count", state.body_count)
        state.log("All bodies found by FSS")
        changed = True

    elif name == "Scan":
        body_name = event.get("BodyName")
        if body_name:
            if "StarType" in event:
                kind = "Star"
                subtype = event.get("StarType", "?")
            elif "PlanetClass" in event:
                kind = "Planet"
                subtype = event.get("PlanetClass", "?")
            else:
                kind = "Body"
                subtype = "?"

            upsert_body(
                state,
                BodyInfo(
                    name=body_name,
                    body_id=event.get("BodyID"),
                    kind=kind,
                    subtype=subtype,
                    distance_ls=event.get("DistanceFromArrivalLS"),
                    landable=event.get("Landable"),
                    mapped=event.get("WasMapped"),
                    scanned=True,
                    terraform_state=event.get("TerraformState", ""),
                    radius_m=event.get("Radius"),
                    surface_temp_k=event.get("SurfaceTemperature"),
                    rings=event.get("Rings", []),
                ),
            )
            update_candidate_notes(state, body_name)
            cache_current_system(state)
            changed = True

    elif name in ("FSSBodySignals", "SAASignalsFound"):
        body_name = event.get("BodyName")
        if body_name:
            bio, geo = signal_counts(event)
            existing = state.bodies.get(body_name, BodyInfo(name=body_name))

            # Mining hotspots come from SAASignalsFound on a ring body.
            # Example signal:
            # { "Type": "Tritium", "Count": 4 }
            if name == "SAASignalsFound":
                mining_signals = []

                for sig in event.get("Signals", []):
                    signal_type = sig.get("Type") or ""
                    signal_local = sig.get("Type_Localised") or signal_type
                    count = sig.get("Count", 0)

                    if signal_type or signal_local:
                        mining_signals.append(
                            {
                                "type": signal_type,
                                "localised": signal_local,
                                "count": count,
                            }
                        )

                if mining_signals:
                    existing.mining_signals = mining_signals

            for sig in event.get("Signals", []):
                sig_type = (
                    sig.get("Type_Localised")
                    or sig.get("Type")
                    or ""
                )

                if text_has_special_keyword(sig_type, body_name):
                    record_special_alert(
                        state,
                        "Interesting surface/body signal",
                        f"{body_name} - {sig_type}"
                    )

            # Signal counts, when present
            if bio is not None:
                existing.bio_signals = bio

            if geo is not None:
                existing.geo_signals = geo

            # Genus/species hints, usually more useful after DSS/SAA scan
            genuses = []
            for genus in event.get("Genuses", []):
                name_local = (
                    genus.get("Genus_Localised")
                    or genus.get("Genus")
                    or genus.get("Name_Localised")
                    or genus.get("Name")
                )
                if name_local:
                    add_unique(genuses, name_local)

            if genuses:
                existing.bio_expected_genuses = genuses

                # If bio_signals was not set by Signals, infer it from genus count.
                if existing.bio_signals is None:
                    existing.bio_signals = len(genuses)

                completed = len(existing.bio_completed_species)

                if completed >= len(genuses) and completed > 0:
                    existing.bio_status = "Completed: " + ", ".join(existing.bio_completed_species)
                else:
                    remaining = [
                        g for g in genuses
                        if g not in existing.bio_completed_species
                    ]
                    existing.bio_status = "Needed: " + ", ".join(remaining)

            state.bodies[body_name] = existing
            cache_current_system(state)

            if existing.bio_signals:
                state.log(f"Biological signals found: {body_name} x{existing.bio_signals}")

            changed = True

    elif name == "FSSSignalDiscovered":
        signal_name = (
            event.get("SignalName_Localised")
            or event.get("SignalName")
            or event.get("USSType_Localised")
            or event.get("USSType")
            or "Unknown signal"
        )

        signal_type = (
            event.get("SignalType_Localised")
            or event.get("SignalType")
            or ""
        )

        state.log(f"FSS signal: {signal_name} {signal_type}".strip())

        if text_has_special_keyword(signal_name, signal_type):
            record_special_alert(
                state,
                "Interesting FSS signal",
                f"{signal_name} {signal_type}".strip()
            )

        changed = True

    elif name == "SAAScanComplete":
        body_name = event.get("BodyName") or state.body
        body_id = event.get("BodyID")

        if body_name:
            existing = state.bodies.get(body_name, BodyInfo(name=body_name))
            existing.body_id = body_id if body_id is not None else existing.body_id
            existing.mapped = True
            state.bodies[body_name] = existing
            cache_current_system(state)

            state.log(f"DSS complete: {body_name}")
            changed = True

    elif name == "ScanOrganic":
        species = event.get("Species_Localised") or event.get("Species") or "organic"
        genus = event.get("Genus_Localised") or event.get("Genus") or species
        scan_type = event.get("ScanType", "?")
        scan_type_lower = str(scan_type).lower()

        body_name = resolve_organic_body_name(state, event)

        if body_name:
            existing = state.bodies.get(body_name, BodyInfo(name=body_name))

            # This list means "organics actually found/scanned on foot."
            # Do not put DSS expected genuses here.
            add_unique(existing.bio_species, species)
            add_unique(existing.bio_species, genus)

            # Analyse is the final 3/3 completion event.
            if scan_type_lower in ("analyse", "analyze"):
                add_unique(existing.bio_completed_species, species)
                add_unique(existing.bio_completed_species, genus)

            if self_safe_bio_complete(existing):
                existing.bio_status = "Completed: " + ", ".join(existing.bio_completed_species)
                state.log(f"Bio complete: {body_name} - {species}")
            elif existing.bio_completed_species:
                existing.bio_status = (
                    "Collected: " + ", ".join(existing.bio_completed_species)
                )
            else:
                existing.bio_status = "Started: " + ", ".join(existing.bio_species)

            state.bodies[body_name] = existing
            cache_current_system(state)
            state.log(f"Organic scan: {scan_type} - {species} @ {body_name}")

        changed = True

    elif name == "CodexEntry":
        entry_name = (
            event.get("Name_Localised")
            or event.get("Name")
            or "Codex entry"
        )

        category = (
            event.get("Category_Localised")
            or event.get("Category")
            or ""
        )

        sub_category = (
            event.get("SubCategory_Localised")
            or event.get("SubCategory")
            or ""
        )

        if text_has_special_keyword(entry_name, category, sub_category):
            record_special_alert(
                state,
                "Special Codex entry",
                f"{entry_name} / {category} / {sub_category}"
            )

        changed = True

    elif name == "SupercruiseExit":
        state.body = event.get("Body", state.body)
        state.station = None
        state.docked = False
        changed = True

    elif name == "SupercruiseEntry":
        state.body = None
        state.station = None
        state.docked = False
        changed = True

    elif name == "ApproachBody":
        state.body = event.get("Body", state.body)
        changed = True

    elif name == "Touchdown":
        # Ship landed
        state.body = event.get("Body", state.body)
        state.latitude = event.get("Latitude", state.latitude)
        state.longitude = event.get("Longitude", state.longitude)
        state.docked = False
        changed = True

    elif name == "Liftoff":
        state.on_foot = False
        state.latitude = None
        state.longitude = None
        changed = True

    elif name == "Docked":
        state.station = event.get("StationName", state.station)
        state.docked = True
        changed = True

    elif name == "Undocked":
        state.station = None
        state.docked = False
        changed = True

    elif name == "Statistics":
        exploration = event.get("Exploration", {})

        state.systems_visited = exploration.get("Systems_Visited")
        state.planets_scanned_level_3 = exploration.get("Planets_Scanned_To_Level_3")
        state.efficient_scans = exploration.get("Efficient_Scans")
        state.first_footfalls = exploration.get("First_Footfalls")

    return changed


class JournalMonitor(QObject):
    updated = pyqtSignal()

    def __init__(self, journal_dir: Path, history_files: int = 30):
        super().__init__()
        self.history_files = history_files
        self.journal_dir = journal_dir
        self.state = CommanderState()
        self.current_file: Optional[Path] = None
        self.position = 0
        self.lock = threading.Lock()
        self.observer: Optional[Observer] = None

    def initialize(self) -> None:
        self.current_file = newest_journal_file(self.journal_dir)
        if not self.current_file:
            raise FileNotFoundError(f"No Journal*.log files found in {self.journal_dir}")

        journals = sorted(
            self.journal_dir.glob("Journal*.log"),
            key=lambda p: p.stat().st_mtime
        )

        journals_to_read = journals[-self.history_files:]

        for journal_path in journals_to_read:
            with journal_path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    apply_event(self.state, event)

        cache_current_system(self.state)

        self.position = self.current_file.stat().st_size
        self.state.log(f"Loaded {len(journals_to_read)} journal files")
        read_nav_route(self.state, self.journal_dir)
        self.state.log(f"Watching: {self.current_file.name}")

    def process_updates(self) -> None:
        with self.lock:
            latest = newest_journal_file(self.journal_dir)
            changed = False

            if latest and latest != self.current_file:
                self.current_file = latest
                self.position = 0
                self.state.log(f"New journal: {self.current_file.name}")
                changed = True

            if not self.current_file:
                return

            current_size = self.current_file.stat().st_size
            if current_size < self.position:
                self.position = 0

            with self.current_file.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(self.position)

                while True:
                    line_start = f.tell()
                    line = f.readline()

                    if not line:
                        break

                    if not line.endswith("\n"):
                        f.seek(line_start)
                        break

                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if apply_event(self.state, event):
                        changed = True

                self.position = f.tell()

            if changed:
                self.updated.emit()

    def start(self) -> None:
        self.initialize()

        if WATCHDOG_AVAILABLE:
            monitor = self

            class Handler(FileSystemEventHandler):
                def on_modified(self, event):
                    if event.is_directory:
                        return

                    path = Path(event.src_path)

                    if path.name.lower() == "navroute.json":
                        with monitor.lock:
                            read_nav_route(monitor.state, monitor.journal_dir)
                            monitor.updated.emit()
                        return

                    monitor.process_updates()

                def on_created(self, event):
                    if event.is_directory:
                        return

                    path = Path(event.src_path)

                    if path.name.lower() == "navroute.json":
                        with monitor.lock:
                            read_nav_route(monitor.state, monitor.journal_dir)
                            monitor.updated.emit()
                        return

                    monitor.process_updates()

                def on_moved(self, event):
                    monitor.process_updates()

            self.observer = Observer()
            self.observer.schedule(Handler(), str(self.journal_dir), recursive=False)
            self.observer.start()
        else:
            self.state.log("Watchdog missing; UI will not live-update correctly.")

    def stop(self) -> None:
        if self.observer:
            self.observer.stop()
            self.observer.join()
