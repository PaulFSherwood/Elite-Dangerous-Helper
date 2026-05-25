#!/usr/bin/env python3


# ------------------------------------------------------------
# Ubuntu/Kubuntu setup:
#
#   sudo apt update
#   sudo apt install python3 python3-pyqt6 python3-watchdog
#
# Run from the repo folder:
#
#   python3 ed_journal_probe.py
#
# Optional alias:
#
#   echo "alias edHelper='python3 ~/Documents/src/elite-journal-helper/ed_journal_probe.py'" >> ~/.bashrc
#   source ~/.bashrc
#
# Then run with:
#
#   edHelper
#
# If using zsh instead of bash:
#
#   echo "alias edHelper='python3 ~/Documents/src/elite-journal-helper/ed_journal_probe.py'" >> ~/.zshrc
#   source ~/.zshrc
#
# Change the path above if you clone the repo somewhere else.
# ------------------------------------------------------------

import argparse
import copy
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PyQt6.QtGui import QColor, QBrush, QTextCursor, QIcon
from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QHeaderView,
    QPushButton,
    QFrame,
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


@dataclass
class BodyInfo:
    name: str
    body_id: Optional[int] = None
    kind: str = "?"
    subtype: str = "?"
    distance_ls: Optional[float] = None
    landable: Optional[bool] = None
    mapped: Optional[bool] = None
    bio_signals: Optional[int] = None
    geo_signals: Optional[int] = None
    scanned: bool = False

    bio_species: list[str] = field(default_factory=list)
    bio_expected_genuses: list[str] = field(default_factory=list)
    bio_completed_species: list[str] = field(default_factory=list)
    bio_status: str = ""

    terraform_state: str = ""
    special_note: str = ""

    radius_m: Optional[float] = None
    surface_temp_k: Optional[float] = None


@dataclass
class CommanderState:
    commander: Optional[str] = None

    ship: Optional[str] = None
    ship_name: Optional[str] = None
    suit: Optional[str] = None
    on_foot: bool = False

    system: Optional[str] = None
    system_address: Optional[int] = None
    body: Optional[str] = None
    station: Optional[str] = None
    docked: bool = False

    nav_route: list[str] = field(default_factory=list)
    nav_target: Optional[str] = None
    nav_final: Optional[str] = None

    body_count: Optional[int] = None
    system_body_cache: dict[str, dict[str, BodyInfo]] = field(default_factory=dict)
    system_count_cache: dict[str, tuple[Optional[int], Optional[int]]] = field(default_factory=dict)
    non_body_count: Optional[int] = None
    bodies: dict[str, BodyInfo] = field(default_factory=dict)

    latitude: Optional[float] = None
    longitude: Optional[float] = None

    last_event: Optional[str] = None
    last_timestamp: Optional[str] = None
    messages: list[str] = field(default_factory=list)

    special_alerts: list[str] = field(default_factory=list)
    special_seen: set[str] = field(default_factory=set)

    def log(self, msg: str) -> None:
        self.messages.append(msg)
        self.messages = self.messages[-12:]


def looks_like_suit(value: Optional[str]) -> bool:
    if not value:
        return False
    return "suit" in value.lower()


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


def signal_counts(event: dict) -> tuple[Optional[int], Optional[int]]:
    bio = 0
    geo = 0
    found_any = False

    for sig in event.get("Signals", []):
        sig_type = str(sig.get("Type") or sig.get("Type_Localised") or "").lower()
        count = int(sig.get("Count", 0))

        if "biological" in sig_type or "organic" in sig_type:
            bio += count
            found_any = True
        elif "geological" in sig_type:
            geo += count
            found_any = True

    if not found_any:
        return None, None

    return bio, geo

def system_cache_key(system: Optional[str], address: Optional[int]) -> Optional[str]:
    if address is not None:
        return f"addr:{address}"

    if system:
        return f"name:{system.lower()}"

    return None


def cache_current_system(state: CommanderState) -> None:
    key = system_cache_key(state.system, state.system_address)

    if not key:
        return

    if state.bodies:
        state.system_body_cache[key] = copy.deepcopy(state.bodies)

    state.system_count_cache[key] = (state.body_count, state.non_body_count)


def restore_cached_system(state: CommanderState) -> None:
    key = system_cache_key(state.system, state.system_address)

    if not key:
        state.bodies.clear()
        return

    if key in state.system_body_cache:
        state.bodies = copy.deepcopy(state.system_body_cache[key])
    else:
        state.bodies.clear()

    if key in state.system_count_cache:
        state.body_count, state.non_body_count = state.system_count_cache[key]

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

SPECIAL_KEYWORDS = [
    "ancient",
    "ancient ruin",
    "ancient ruins",
    "anomaly",
    "barnacle",
    "listening post",
    "guardian",
    "non-human",
    "non human",
    "guardian ruins",
    "guardian ruin",
    "guardian structure",
    "guardian beacon",
    "lagrange",
    "notable stellar phenomena",
    "probe",
    "thargoid",
    "thargoid structure",
    "thargoid surface site",
    "thargoid barnacle",
    "unknown artefact",
    "unknown artifact",
    "unregistered",
    "xeno",
]


def text_has_special_keyword(*values: object) -> bool:
    combined = " ".join(str(v).lower() for v in values if v)
    return any(keyword in combined for keyword in SPECIAL_KEYWORDS)


def record_special_alert(state: CommanderState, title: str, detail: str = "") -> None:
    location_parts = []

    if state.system:
        location_parts.append(state.system)

    if state.body:
        location_parts.append(state.body)

    location = " / ".join(location_parts)

    message = title
    if detail:
        message += f": {detail}"

    if location:
        message += f" @ {location}"

    if message in state.special_seen:
        return

    state.special_seen.add(message)
    state.special_alerts.append(message)
    state.special_alerts = state.special_alerts[-10:]
    state.log(f"!!! SPECIAL: {message}")

def add_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)

def upsert_body(state: CommanderState, body: BodyInfo) -> None:
    key = body.name

    if body.kind == "Star" and body.distance_ls is not None and body.distance_ls <= 1:
        state.bodies.pop("__arrival_star__", None)

    existing = state.bodies.get(key)
    if existing:
        for field_name, value in body.__dict__.items():
            if value is None or value == "?":
                continue

            # Do not let a later Scan/WasMapped=False overwrite our own DSS completion.
            if field_name == "mapped" and existing.mapped is True and value is False:
                continue

            if field_name in ("bio_species", "bio_expected_genuses", "bio_completed_species") and value == []:
                continue

            setattr(existing, field_name, value)
    else:
        state.bodies[key] = body

def is_guardian_candidate(body: BodyInfo) -> bool:
    subtype = (body.subtype or "").lower()

    if not body.landable:
        return False

    if not ("rocky" in subtype or "high metal content" in subtype):
        return False

    if body.surface_temp_k is None or body.radius_m is None:
        return False

    radius_km = body.radius_m / 1000.0

    return (
        180 <= body.surface_temp_k <= 310
        and 1000 <= radius_km <= 3000
    )


def is_thargoid_interest_body(body: BodyInfo) -> bool:
    subtype = (body.subtype or "").lower()

    return (
        "ammonia world" in subtype
        or "ammonia-based life" in subtype
        or "ammonia based life" in subtype
    )


def update_candidate_notes(state: CommanderState, body_name: str) -> None:
    body = state.bodies.get(body_name)
    if not body:
        return

    notes = []

    if is_guardian_candidate(body):
        notes.append("Guardian candidate")

    if is_thargoid_interest_body(body):
        notes.append("Thargoid-interest ammonia body")

    body.special_note = " | ".join(notes)

    if body.special_note:
        state.log(f"Candidate: {body.name} - {body.special_note}")

def self_safe_bio_complete(body: BodyInfo) -> bool:
    if not body.bio_signals:
        return False

    if not body.bio_completed_species:
        return False

    expected = body.bio_expected_genuses if body.bio_expected_genuses else body.bio_species

    if expected:
        completed_keys = {
            name.strip().split()[0].lower()
            for name in body.bio_completed_species
            if name
        }

        expected_keys = {
            name.strip().split()[0].lower()
            for name in expected
            if name
        }

        return expected_keys.issubset(completed_keys)

    return len(body.bio_completed_species) >= body.bio_signals


def bio_key(name: str) -> str:
    # Converts "Fungoida Bullarum" or "Fungoida" into "fungoida".
    if not name:
        return ""
    return name.strip().split()[0].lower()


def resolve_organic_body_name(state: CommanderState, event: dict) -> Optional[str]:
    # Prefer explicit body name if Elite provides it.
    body_name = event.get("BodyName")
    if body_name and body_name in state.bodies:
        return body_name

    # Elite may give BodyID or Body as a number during organic scans.
    body_id = event.get("BodyID")

    if body_id is None:
        raw_body = event.get("Body")
        if isinstance(raw_body, int):
            body_id = raw_body
        elif isinstance(raw_body, str) and raw_body.isdigit():
            body_id = int(raw_body)
        elif isinstance(raw_body, str) and raw_body in state.bodies:
            return raw_body

    if body_id is not None:
        for body in state.bodies.values():
            if body.body_id == body_id:
                return body.name

    # Fallback to current body only if it matches a known body name.
    if state.body and state.body in state.bodies:
        return state.body

    # Last fallback: if only one bio body exists, use it.
    bio_bodies = [
        body.name
        for body in state.bodies.values()
        if body.bio_signals and body.bio_signals > 0
    ]

    if len(bio_bodies) == 1:
        return bio_bodies[0]

    return None
SHIP_NAME_MAP = {
    "sidewinder": "Sidewinder",
    "eagle": "Eagle",
    "hauler": "Hauler",
    "adder": "Adder",
    "viper": "Viper",
    "viper_mkiv": "Viper Mk IV",
    "cobra_mkiii": "Cobra Mk III",
    "cobra_mkiv": "Cobra Mk IV",
    "diamondback": "Diamondback Scout",
    "diamondbackxl": "Diamondback Explorer",
    "type6": "Type-6 Transporter",
    "dolphin": "Dolphin",
    "asp": "Asp Scout",
    "asp_scout": "Asp Scout",
    "asp_explorer": "Asp Explorer",
    "vulture": "Vulture",
    "empire_courier": "Imperial Courier",
    "federation_dropship": "Federal Dropship",
    "type7": "Type-7 Transporter",
    "alliance_chieftain": "Alliance Chieftain",
    "alliance_crusader": "Alliance Crusader",
    "alliance_challenger": "Alliance Challenger",
    "krait_mkii": "Krait Mk II",
    "krait_light": "Krait Phantom",
    "python": "Python",
    "python_nx": "Python Mk II",
    "type8": "Type-8 Transporter",
    "type9": "Type-9 Heavy",
    "type10": "Type-10 Defender",
    "anaconda": "Anaconda",
    "federation_corvette": "Federal Corvette",
    "cutter": "Imperial Cutter",
    "belugaliner": "Beluga Liner",
    "orca": "Orca",
    "mamba": "Mamba",
    "ferdelance": "Fer-de-Lance",
    "panthermkii": "Panther Clipper Mk II",
}

def friendly_ship_name(raw_name: Optional[str]) -> str:
    if not raw_name:
        return "Unknown ship"

    key = raw_name.strip().lower()
    return SHIP_NAME_MAP.get(key, raw_name)

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
        state.on_foot = True
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


class OverlayWindow(QWidget):
    def has_bio(self, body: BodyInfo) -> bool:
        return bool(body.bio_signals and body.bio_signals > 0)

    def bio_complete(self, body: BodyInfo) -> bool:
        if not self.has_bio(body):
            return False

        if not body.bio_completed_species:
            return False

        expected = body.bio_expected_genuses if body.bio_expected_genuses else body.bio_species

        if expected:
            return all(
                self.bio_name_completed(expected_name, body.bio_completed_species)
                for expected_name in expected
            )

        return len(body.bio_completed_species) >= body.bio_signals

    def update_info_card(self, card: QFrame, icon: str, title: str, value: str) -> None:
        layout = card.layout()
        if layout is None:
            return

        icon_label = layout.itemAt(0).widget()
        text_layout = layout.itemAt(1).layout()

        if icon_label:
            icon_label.setText(icon)

        if text_layout:
            title_label = text_layout.itemAt(0).widget()
            value_label = text_layout.itemAt(1).widget()

            if title_label:
                title_label.setText(title)
            if value_label:
                value_label.setText(value)

    def make_info_card(self, icon: str, title: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("infoCard")

        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        icon_label = QLabel(icon)
        icon_label.setObjectName("cardIcon")

        text_box = QVBoxLayout()
        text_box.setSpacing(1)

        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")

        value_label = QLabel(value)
        value_label.setObjectName("cardValue")

        text_box.addWidget(title_label)
        text_box.addWidget(value_label)

        layout.addWidget(icon_label)
        layout.addLayout(text_box)
        layout.addStretch()

        return card

    def __init__(self, monitor: JournalMonitor, always_on_top: bool = True):
        flags = Qt.WindowType.Window
        if always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint

        super().__init__(flags=flags)
        self.monitor = monitor

        self.opacity_enabled = True
        self.normal_opacity = 0.78
        self.solid_opacity = 1.0

        self.setWindowTitle("Paul Observatory")
        icon_path = Path(__file__).resolve().parent / "assets" / "ed_helper_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1120, 520)
        self.setWindowOpacity(self.normal_opacity)

        self.system_label = QLabel()
        self.ship_label = QLabel()
        self.location_label = QLabel()
        self.count_label = QLabel()
        self.special_label = QLabel()

        self.ship_card = QFrame()
        self.mode_card = QFrame()
        self.location_card = QFrame()
        self.bodies_card = QFrame()
        self.other_card = QFrame()
        self.high_value_card = QFrame()
        self.bio_card = QFrame()

        self.legend_label = QLabel(
            "Legend  |  Bio: gray = expected, green = found, purple = complete  |  DSS: orange = needed, green = complete"
        )
        self.legend_label.setObjectName("legendLabel")

        self.opacity_button = QPushButton("●")
        self.opacity_button.setToolTip("Toggle transparency")
        self.opacity_button.setFixedSize(28, 28)
        self.opacity_button.clicked.connect(self.toggle_opacity)
        self.opacity_button.setObjectName("opacityButton")

        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)

        self.table.setHorizontalHeaderLabels(
            ["ID", "Body", "Type", "Class", "Distance", "Bio", "Geo", "DSS", "Bio Progress", "Recommendation"]
        )

        table_header = self.table.horizontalHeader()

        # Let normal columns size to their contents.
        for col in range(10):
            table_header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        # Let Bio Status take extra width when the window is stretched.
        table_header.setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)

        # Optional: keep the last column from auto-stretching instead of Bio Status.
        table_header.setStretchLastSection(False)

        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(85)

        header = QVBoxLayout()
        header.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.addWidget(self.system_label, stretch=1)
        top_row.addWidget(self.opacity_button, stretch=0)

        ship_row = QHBoxLayout()
        ship_row.setSpacing(10)
        
        self.ship_card = self.make_info_card("🚀", "Ship", "Unknown ship")
        self.mode_card = self.make_info_card("🧭", "Mode", "Unknown")
        self.location_card = self.make_info_card("📍", "Location", "space")
        
        ship_row.addWidget(self.ship_card, stretch=2)
        ship_row.addWidget(self.mode_card, stretch=1)
        ship_row.addWidget(self.location_card, stretch=2)
        
        summary_row = QHBoxLayout()
        summary_row.setSpacing(10)
        
        self.bodies_card = self.make_info_card("◎", "Bodies", "? / ?")
        self.other_card = self.make_info_card("✦", "Other", "0")
        self.high_value_card = self.make_info_card("◇", "High-value", "0")
        self.bio_card = self.make_info_card("☘", "Bio bodies", "0")
        
        summary_row.addWidget(self.bodies_card)
        summary_row.addWidget(self.other_card)
        summary_row.addWidget(self.high_value_card)
        summary_row.addWidget(self.bio_card)

        header.addLayout(top_row)
        header.addWidget(self.special_label)
        header.addLayout(ship_row)
        header.addLayout(summary_row)

        layout = QVBoxLayout()
        layout.addLayout(header)
        layout.addWidget(self.table)
        layout.addWidget(self.legend_label)
        layout.addWidget(self.log_box)
        self.setLayout(layout)

        self.setStyleSheet("""
            QWidget {
                background-color: #0F1720;
                color: #E6EDF3;
                font-size: 13px;
            }

            QLabel {
                color: #E6EDF3;
                font-size: 14px;
                padding: 2px;
            }

            QLabel#legendLabel {
                background-color: #16202A;
                color: #C7D0D9;
                font-size: 12px;
                padding: 7px;
                border: 1px solid #2A3A48;
                border-radius: 8px;
            }

            QFrame#infoCard {
                background-color: #16202A;
                border: 1px solid #2A3A48;
                border-radius: 12px;
            }
            
            QLabel#cardIcon {
                color: #F59E0B;
                font-size: 20px;
                font-weight: bold;
            }
            
            QLabel#cardTitle {
                color: #9FB0BF;
                font-size: 12px;
            }
            
            QLabel#cardValue {
                color: #E6EDF3;
                font-size: 15px;
                font-weight: bold;
            }

            QTableWidget {
                background-color: #111A22;
                alternate-background-color: #13202A;
                color: #E6EDF3;
                gridline-color: #243342;
                selection-background-color: #27445C;
                border: 1px solid #2A3A48;
                border-radius: 10px;
            }

            QHeaderView::section {
                background-color: #1E2B36;
                color: #DCE6EE;
                padding: 6px;
                border: none;
                border-right: 1px solid #2A3A48;
            }

            QTextEdit {
                background-color: #0B1117;
                color: #A7FF83;
                border: 1px solid #2A3A48;
                border-radius: 10px;
                padding: 6px;
            }

            QPushButton#opacityButton {
                background-color: #1E2B36;
                color: #F59E0B;
                border: 1px solid #3A4A58;
                border-radius: 14px;
                font-size: 16px;
                font-weight: bold;
            }

            QPushButton#opacityButton:hover {
                background-color: #2A3A48;
            }
        """)

        self.special_label.setStyleSheet("""
            QLabel {
                background-color: #4A102A;
                color: #FFD700;
                font-weight: bold;
                padding: 8px;
                border: 1px solid #8A3A5A;
                border-radius: 10px;
            }
        """)

        self.monitor.updated.connect(self.refresh)
        self.refresh()

    def is_high_value_world(self, body: BodyInfo) -> bool:
        subtype = (body.subtype or "").lower()
        terraform = (body.terraform_state or "").lower()

        return (
            "earthlike" in subtype
            or "earth-like" in subtype
            or "water world" in subtype
            or "ammonia world" in subtype
            or (
                "high metal content" in subtype
                and "terraform" in terraform
            )
            or (
                "rocky body" in subtype
                and "terraform" in terraform
            )
        )

    def priority_text(self, body: BodyInfo) -> str:
        if self.is_high_value_world(body):
            subtype = body.subtype or "High value body"
            terraform = " Terraformable" if "terraform" in (body.terraform_state or "").lower() else ""
            note = f" | {body.special_note}" if body.special_note else ""

            if body.mapped is True:
                return f"{terraform} {subtype} - mapped{note}".strip()

            return f"{terraform} {subtype} - DSS NEEDED{note}".strip()

        if body.bio_signals and body.bio_signals > 0:
            if self.bio_complete(body):
                return "Bio complete"
            return "Bio signals"

        if body.scanned is False:
            return "Not FSS scanned"

        if body.kind == "Planet" and body.mapped is False:
            return "Not mapped"

        if body.special_note:
            return body.special_note

        return ""

    def bio_key(self, name: str) -> str:
        return bio_key(name)

    def bio_name_started(self, expected_name: str, known_names: list[str]) -> bool:
        expected_key = self.bio_key(expected_name)

        for known in known_names:
            known_key = self.bio_key(known)
            if known_key == expected_key:
                return True

        return False

    def bio_name_completed(self, expected_name: str, completed_names: list[str]) -> bool:
        expected_key = self.bio_key(expected_name)

        for completed in completed_names:
            completed_key = self.bio_key(completed)
            if completed_key == expected_key:
                return True

        return False

    def make_bio_status_widget(self, body: BodyInfo) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        expected = body.bio_expected_genuses[:] if body.bio_expected_genuses else body.bio_species[:]

        # If we only know "3 biological signals" but not names yet,
        # show Bio 1 / Bio 2 / Bio 3.
        if not expected and body.bio_signals:
            expected = [f"Bio {i + 1}" for i in range(body.bio_signals)]

        started_keys = {bio_key(name) for name in body.bio_species if name}
        completed_keys = {bio_key(name) for name in body.bio_completed_species if name}

        for index, name in enumerate(expected):
            key = bio_key(name)

            # Expected genus names such as "Fungoida" should match scanned
            # species names such as "Fungoida Bullarum".
            done = key in completed_keys
            started = key in started_keys

            # Fallback for placeholder Bio 1 / Bio 2 / Bio 3 when names are unknown.
            if name.startswith("Bio "):
                done = index < len(body.bio_completed_species)
                started = index < len(body.bio_species)

            if done:
                label_text = f"✓ {name}"
                color = "#CBC3E3"      # completed final Analyse / 3-of-3
                text_color = "#000000"
            elif started:
                label_text = f"• {name}"
                color = "#1F5A32"      # found / sampling started
                text_color = "#FFFFFF"
            else:
                label_text = name
                color = "#3A3A3A"      # expected but not found yet
                text_color = "#DDDDDD"

            label = QLabel(label_text)
            label.setStyleSheet(f"""
                QLabel {{
                    background-color: {color};
                    color: {text_color};
                    border-radius: 5px;
                    padding: 2px 6px;
                }}
            """)

            layout.addWidget(label)

        layout.addStretch()
        return container

    def toggle_opacity(self) -> None:
        self.opacity_enabled = not self.opacity_enabled

        if self.opacity_enabled:
            self.setWindowOpacity(self.normal_opacity)
            self.opacity_button.setText("●")
        else:
            self.setWindowOpacity(self.solid_opacity)
            self.opacity_button.setText("○")

    def refresh(self) -> None:
        state = self.monitor.state

        if state.special_alerts:
            self.special_label.setText(f"!!! SPECIAL: {state.special_alerts[-1]}")
            self.special_label.setStyleSheet("""
                QLabel {
                    background-color: #4A102A;
                    color: #FFD700;
                    font-weight: bold;
                    padding: 8px;
                    border-radius: 8px;
                }
            """)
        else:
            self.special_label.setText("Special: none detected in this system")
            self.special_label.setStyleSheet("""
                QLabel {
                    background-color: #26323D;
                    color: #C7D0D9;
                    font-weight: bold;
                    padding: 8px;
                    border-radius: 8px;
                }
            """)

        system = state.system or "Unknown system"
        target = state.nav_target or "none"
        final = state.nav_final or "none"

        self.system_label.setText(
            f"System: {system}    Target: {target}    Final: {final}    Event: {state.last_event or '?'}"
        )

        ship = state.ship_name or friendly_ship_name(state.ship)
        mode = "On Foot" if state.on_foot else "In Ship"

        ship_icon = "🧍" if state.on_foot else "🚀"
        
        self.update_info_card(self.ship_card, ship_icon, "Ship", ship)
        self.update_info_card(self.mode_card, "🧭", "Mode", mode)

        where = state.station or state.body or "space"
        latlon = ""
        if state.latitude is not None and state.longitude is not None:
            latlon = f"    Lat/Lon: {state.latitude:.4f}, {state.longitude:.4f}"

        self.update_info_card(self.location_card, "📍", "Location", f"{where}{latlon}")

        planet_star_scanned_count = len([
            b for b in state.bodies.values()
            if b.scanned and b.kind in ("Planet", "Star")
        ])

        other_scanned_count = len([
            b for b in state.bodies.values()
            if b.scanned and b.kind not in ("Planet", "Star")
        ])

        total = state.body_count if state.body_count is not None else "?"

        high_value_unmapped = [
            b for b in state.bodies.values()
            if self.is_high_value_world(b) and b.mapped is not True
        ]

        bio_bodies = [
            b for b in state.bodies.values()
            if b.bio_signals and b.bio_signals > 0
        ]

        other_text = ""
        if other_scanned_count > 0:
            other_text = f"    Other scanned: {other_scanned_count}"

        self.update_info_card(
            self.bodies_card,
            "◎",
            "Bodies",
            f"{planet_star_scanned_count} / {total}",
        )
        
        self.update_info_card(
            self.other_card,
            "✦",
            "Other scanned",
            str(other_scanned_count),
        )
        
        self.update_info_card(
            self.high_value_card,
            "◇",
            "High-value",
            str(len(high_value_unmapped)),
        )
        
        self.update_info_card(
            self.bio_card,
            "☘",
            "Bio bodies",
            str(len(bio_bodies)),
        )

        def body_sort_key(b: BodyInfo):
            high_value_unmapped = self.is_high_value_world(b) and b.mapped is not True
            has_bio = b.bio_signals and b.bio_signals > 0
            high_value_mapped = self.is_high_value_world(b) and b.mapped is True
            not_mapped = b.mapped is False
            not_scanned = b.scanned is False

            if high_value_unmapped:
                priority = 0
            elif has_bio:
                priority = 1
            elif high_value_mapped:
                priority = 2
            elif not_mapped:
                priority = 3
            elif not_scanned:
                priority = 4
            else:
                priority = 5

            return (
                priority,
                b.distance_ls is None,
                b.distance_ls if b.distance_ls is not None else 999999999,
                b.body_id if b.body_id is not None else 999999,
                b.name,
            )

        bodies = sorted(
            state.bodies.values(),
            key=body_sort_key,
        )

        self.table.setRowCount(len(bodies))

        for row, body in enumerate(bodies):
            high_value = self.is_high_value_world(body)
            can_be_dss_mapped = body.kind == "Planet"
            mapped_text = "" if not can_be_dss_mapped or body.mapped is None else ("Yes" if body.mapped else "No")
            priority = self.priority_text(body)

            values = [
                "" if body.body_id is None else str(body.body_id),
                body.name,
                body.kind,
                body.subtype,
                "" if body.distance_ls is None else f"{body.distance_ls:.1f}",
                "" if body.bio_signals is None else str(body.bio_signals),
                "" if body.geo_signals is None else str(body.geo_signals),
                mapped_text,
                body.bio_status,
                priority,
            ]

            for col, value in enumerate(values):
                item = QTableWidgetItem(value)

                # Row background meanings:
                # dark red/orange = Earth-like or Water World not DSS mapped
                # dark blue = Earth-like or Water World already mapped
                # dark green = biological signals
                # dark gray = known body but not fully scanned/classified yet

                if high_value and body.mapped is not True:
                    item.setBackground(QBrush(QColor("#4A1F24")))
                    item.setForeground(QBrush(QColor("#FFFFFF")))

                elif high_value and body.mapped is True:
                    item.setBackground(QBrush(QColor("#17324A")))
                    item.setForeground(QBrush(QColor("#FFFFFF")))

                elif body.bio_signals and body.bio_signals > 0:
                    # Do not color the whole row for bio.
                    # Bio status should only affect Bio Status and Priority columns.
                    if col == 9:
                        if self.bio_complete(body):
                            item.setBackground(QBrush(QColor("#CBC3E3")))  # completed bio
                            item.setForeground(QBrush(QColor("#000000")))
                        else:
                            item.setBackground(QBrush(QColor("#1F5A32")))  # bio still needs work
                            item.setForeground(QBrush(QColor("#FFFFFF")))

                elif body.scanned is False:
                    item.setBackground(QBrush(QColor("#26323D")))
                    item.setForeground(QBrush(QColor("#DDDDDD")))

                # Make the Mapped cell extra obvious.
                # Make the DSS cell look like a small status pill.
                if col == 7 and can_be_dss_mapped:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                    if high_value and body.mapped is not True:
                        item.setText("DSS Needed")
                        item.setBackground(QBrush(QColor("#7F1D1D")))
                        item.setForeground(QBrush(QColor("#FFFFFF")))
                    elif body.mapped is False:
                        item.setText("No")
                        item.setBackground(QBrush(QColor("#A16207")))
                        item.setForeground(QBrush(QColor("#FFFFFF")))
                    elif body.mapped is True:
                        item.setText("Yes")
                        item.setBackground(QBrush(QColor("#2E7D32")))
                        item.setForeground(QBrush(QColor("#FFFFFF")))

                self.table.setItem(row, col, item)

            # Bios Status pill split
            if body.bio_signals and body.bio_signals > 0:
                self.table.setCellWidget(row, 8, self.make_bio_status_widget(body))
                self.table.setRowHeight(row, 32)
            else:
                self.table.removeCellWidget(row, 8)

        self.table.resizeRowsToContents()
        # auto scroll
        self.log_box.setPlainText("\n".join(state.messages))
        self.log_box.moveCursor(QTextCursor.MoveOperation.End)

    def closeEvent(self, event) -> None:
        self.monitor.stop()
        event.accept()


def main() -> None:
    parser = argparse.ArgumentParser(description="Elite Dangerous Linux overlay")
    parser.add_argument("--journal-dir", help="Elite Dangerous journal folder")
    parser.add_argument("--no-top", action="store_true", help="Disable always-on-top window")
    parser.add_argument(
        "--history-files",
        type=int,
        default=30,
        help="Number of recent journal files to read on startup",
    )

    args = parser.parse_args()

    journal_dir = resolve_journal_dir(args.journal_dir)

    if not journal_dir.exists():
        print(f"Journal directory not found: {journal_dir}")
        return

    app = QApplication(sys.argv)

    icon_path = Path(__file__).resolve().parent / "assets" / "ed_helper_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    monitor = JournalMonitor(journal_dir, history_files=args.history_files)
    monitor.start()

    window = OverlayWindow(monitor, always_on_top=not args.no_top)
    window.show()
    window.raise_()
    window.activateWindow()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
