from __future__ import annotations

import json
import os
import threading
# from db import connect_db, init_db, save_state_snapshot, save_first_footfall
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QSettings, pyqtSignal

from state import (
    BodyInfo,
    CommanderState,
    cache_current_system,
    restore_cached_system,
    system_cache_keys,
)
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
    "~/Saved Games/Frontier Developments/Elite Dangerous",
    "~/.steam/debian-installation/steamapps/compatdata/359320/pfx/drive_c/users/steamuser/Saved Games/Frontier Developments/Elite Dangerous",
    "~/.local/share/Steam/steamapps/compatdata/359320/pfx/drive_c/users/steamuser/Saved Games/Frontier Developments/Elite Dangerous",
]


HELD_EXPLORATION_KEY = "held_data/exploration_systems"
HELD_BIO_KEY = "held_data/bio_samples"
FSS_COMPLETED_KEY = "fss/completed_systems"
FSS_INDEXED_FILES_KEY = "fss/indexed_files"


def _settings_string_set(settings: QSettings, key: str) -> set[str]:
    raw = settings.value(key, "[]")

    try:
        values = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return set()

    if not isinstance(values, list):
        return set()

    return {str(value) for value in values if value}


def load_held_data(state: CommanderState, settings: QSettings) -> None:
    state.held_exploration_systems = _settings_string_set(
        settings,
        HELD_EXPLORATION_KEY,
    )
    state.held_bio_samples = _settings_string_set(
        settings,
        HELD_BIO_KEY,
    )


def save_held_data(state: CommanderState, settings: QSettings) -> None:
    settings.setValue(
        HELD_EXPLORATION_KEY,
        json.dumps(sorted(state.held_exploration_systems)),
    )
    settings.setValue(
        HELD_BIO_KEY,
        json.dumps(sorted(state.held_bio_samples)),
    )
    settings.sync()


def exploration_system_key(state: CommanderState) -> Optional[str]:
    if state.system_address is not None:
        return f"addr:{state.system_address}"

    if state.system:
        return f"name:{state.system.lower()}"

    return None



def _settings_json_dict(settings: QSettings, key: str) -> dict:
    raw = settings.value(key, "{}")

    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}

    return value if isinstance(value, dict) else {}


def load_fss_data(state: CommanderState, settings: QSettings) -> None:
    raw = _settings_json_dict(settings, FSS_COMPLETED_KEY)
    completed: dict[str, Optional[int]] = {}

    for key, count in raw.items():
        if not isinstance(key, str) or not key:
            continue

        if count is None:
            completed[key] = None
            continue

        try:
            completed[key] = int(count)
        except (TypeError, ValueError):
            completed[key] = None

    state.fss_completed_systems = completed


def save_fss_data(state: CommanderState, settings: QSettings) -> None:
    settings.setValue(
        FSS_COMPLETED_KEY,
        json.dumps(state.fss_completed_systems, sort_keys=True),
    )
    settings.sync()


def _as_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def mark_fss_complete(
    state: CommanderState,
    system: Optional[str],
    address: Optional[int],
    count: Optional[int],
) -> None:
    keys = system_cache_keys(system, address)

    if not keys:
        return

    body_count: Optional[int]
    try:
        body_count = int(count) if count is not None else None
    except (TypeError, ValueError):
        body_count = None

    for key in keys:
        old_count = state.fss_completed_systems.get(key)
        if body_count is not None or key not in state.fss_completed_systems:
            state.fss_completed_systems[key] = body_count if body_count is not None else old_count

    current_keys = set(system_cache_keys(state.system, state.system_address))
    if current_keys.intersection(keys):
        state.fss_complete = True
        state.fss_progress = 1.0
        if state.body_count is None and body_count is not None:
            state.body_count = body_count


def _scan_fss_history_file(state: CommanderState, journal_path: Path) -> int:
    current_system: Optional[str] = None
    current_address: Optional[int] = None
    completions_before = len(state.fss_completed_systems)

    interesting_names = (
        "Location",
        "FSDJump",
        "CarrierJump",
        "FSSDiscoveryScan",
        "FSSAllBodiesFound",
    )

    with journal_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not any(name in line for name in interesting_names):
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_name = event.get("event")

            if event_name in ("Location", "FSDJump", "CarrierJump"):
                current_system = event.get("StarSystem") or current_system
                current_address = event.get("SystemAddress", current_address)
                continue

            system = (
                event.get("SystemName")
                or event.get("StarSystem")
                or current_system
            )
            address = event.get("SystemAddress", current_address)

            if event_name == "FSSAllBodiesFound":
                mark_fss_complete(
                    state,
                    system,
                    address,
                    event.get("Count"),
                )
                continue

            if event_name == "FSSDiscoveryScan":
                progress = _as_float(event.get("Progress"))
                if progress is not None and progress >= 0.999999:
                    mark_fss_complete(
                        state,
                        system,
                        address,
                        event.get("BodyCount"),
                    )

    return len(state.fss_completed_systems) - completions_before


def index_fss_history(
    state: CommanderState,
    settings: QSettings,
    journal_dir: Path,
) -> tuple[int, int]:
    indexed_files = _settings_json_dict(settings, FSS_INDEXED_FILES_KEY)
    files_scanned = 0
    completion_keys_added = 0

    journals = sorted(
        journal_dir.glob("Journal*.log"),
        key=lambda p: p.stat().st_mtime,
    )

    for journal_path in journals:
        try:
            stat = journal_path.stat()
        except OSError:
            continue

        signature = f"{stat.st_size}:{stat.st_mtime_ns}"
        if indexed_files.get(journal_path.name) == signature:
            continue

        try:
            completion_keys_added += _scan_fss_history_file(state, journal_path)
        except OSError:
            continue

        indexed_files[journal_path.name] = signature
        files_scanned += 1

    if files_scanned:
        settings.setValue(
            FSS_INDEXED_FILES_KEY,
            json.dumps(indexed_files, sort_keys=True),
        )
        settings.setValue(
            FSS_COMPLETED_KEY,
            json.dumps(state.fss_completed_systems, sort_keys=True),
        )
        settings.sync()

    return files_scanned, completion_keys_added


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

    # Live commander stat estimates.
    #
    # Official totals still come from the Statistics journal event.
    # These live updates make the visible totals move while playing,
    # instead of waiting for Elite to write another Statistics event.
    #
    # This only runs after journal history loading is complete.
    if state.live_updates_enabled:
        if name == "FSDJump":
            if state.systems_visited is not None:
                state.systems_visited += 1

        elif name == "Scan" and event.get("PlanetClass"):
            body_id = event.get("BodyID")

            if body_id is not None and body_id not in state.seen_scan_body_ids:
                state.seen_scan_body_ids.add(body_id)

                if state.planets_scanned_level_3 is not None:
                    state.planets_scanned_level_3 += 1

        elif name == "SAAScanComplete":
            probes_used = event.get("ProbesUsed")
            efficiency_target = event.get("EfficiencyTarget")

            if (
                probes_used is not None
                and efficiency_target is not None
                and efficiency_target > 0
                and probes_used <= efficiency_target
            ):
                if state.efficient_scans is not None:
                    state.efficient_scans += 1
        # elif name == "Touchdown" and event.get("FirstFootfall") is True:
        #     body_id = event.get("BodyID")
        # 
        #     if body_id is not None and body_id not in state.seen_first_footfall_bodies:
        #         state.seen_first_footfall_bodies.add(body_id)
        # 
        #         if state.first_footfalls is not None:
        #             state.first_footfalls += 1
        # 
        #         if hasattr(state, "session_first_footfalls_live"):
        #             state.session_first_footfalls_live += 1

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

        progress = _as_float(event.get("Progress"))
        if progress is not None:
            state.fss_progress = progress

        if progress is not None and progress >= 0.999999:
            mark_fss_complete(
                state,
                event.get("SystemName") or event.get("StarSystem") or state.system,
                event.get("SystemAddress", state.system_address),
                state.body_count,
            )

        if state.live_updates_enabled:
            system_key = exploration_system_key(state)
            if system_key:
                state.held_exploration_systems.add(system_key)

        if state.fss_complete:
            state.log(f"FSS complete: {state.body_count} bodies")
        else:
            state.log(f"Honk complete: {state.body_count} bodies detected")
        changed = True

    elif name == "FSSAllBodiesFound":
        state.body_count = event.get("Count", state.body_count)
        mark_fss_complete(
            state,
            event.get("SystemName") or event.get("StarSystem") or state.system,
            event.get("SystemAddress", state.system_address),
            state.body_count,
        )
        state.log("All bodies found by FSS")
        changed = True

    elif name == "Scan":
        if state.live_updates_enabled:
            system_key = exploration_system_key(state)
            if system_key:
                state.held_exploration_systems.add(system_key)

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

            materials = {}
            
            for material in event.get("Materials", []):
                mat_name = material.get("Name")
                mat_percent = material.get("Percent")
            
                if mat_name and mat_percent is not None:
                    materials[mat_name.lower()] = mat_percent

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
                    materials=materials,
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
                before_count = len(existing.bio_completed_species)

                add_unique(existing.bio_completed_species, species)
                add_unique(existing.bio_completed_species, genus)

                after_count = len(existing.bio_completed_species)

                # Count live bio completions only after history loading is done.
                # Also keep one unsold sample per body/species until Vista
                # Genomics writes SellOrganicData.
                if state.live_updates_enabled and after_count > before_count:
                    state.session_bio_completed += 1

                    sample_key = "|".join(
                        (
                            str(state.system_address or state.system or "?"),
                            str(event.get("BodyID") or body_name),
                            str(event.get("Species") or species),
                        )
                    )
                    state.held_bio_samples.add(sample_key)

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

    elif name in ("SellExplorationData", "MultiSellExplorationData"):
        if state.live_updates_enabled:
            sold_count = len(state.held_exploration_systems)
            state.held_exploration_systems.clear()
            state.log(f"Exploration data sold: {sold_count} systems cleared")
        changed = True

    elif name == "SellOrganicData":
        if state.live_updates_enabled:
            sold_count = len(state.held_bio_samples)
            state.held_bio_samples.clear()
            state.log(f"Biological data sold: {sold_count} samples cleared")
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
        self.settings = QSettings("GrrWooD", "EliteDangerousObservatory")
        self.state = CommanderState()
        load_held_data(self.state, self.settings)
        load_fss_data(self.state, self.settings)
        # self.db = connect_db()
        # init_db(self.db)
        self.current_file: Optional[Path] = None
        self.position = 0
        self.lock = threading.Lock()
        self.observer: Optional[Observer] = None

    def initialize(self) -> None:
        self.state.live_updates_enabled = False
        self.current_file = newest_journal_file(self.journal_dir)
        if not self.current_file:
            raise FileNotFoundError(f"No Journal*.log files found in {self.journal_dir}")

        journals = sorted(
            self.journal_dir.glob("Journal*.log"),
            key=lambda p: p.stat().st_mtime
        )

        files_indexed, completion_keys_added = index_fss_history(
            self.state,
            self.settings,
            self.journal_dir,
        )
        if files_indexed:
            self.state.log(
                f"FSS history indexed: {files_indexed} files, "
                f"{completion_keys_added} completion keys added"
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

                    # if event.get("event") == "Touchdown" and event.get("FirstFootfall") is True:
                    #     save_first_footfall(self.db, self.state, event)

        cache_current_system(self.state)
        save_fss_data(self.state, self.settings)
        # save_state_snapshot(self.db, self.state)

        self.position = self.current_file.stat().st_size
        self.state.log(f"Loaded {len(journals_to_read)} journal files")
        read_nav_route(self.state, self.journal_dir)
        self.state.log(f"Watching: {self.current_file.name}")
        self.state.live_updates_enabled = True

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

                    if event.get("event") in {
                        "FSSDiscoveryScan",
                        "Scan",
                        "ScanOrganic",
                        "SellExplorationData",
                        "MultiSellExplorationData",
                        "SellOrganicData",
                    }:
                        save_held_data(self.state, self.settings)

                    if event.get("event") in {
                        "FSSDiscoveryScan",
                        "FSSAllBodiesFound",
                    }:
                        save_fss_data(self.state, self.settings)

                    # if event.get("event") == "Touchdown" and event.get("FirstFootfall") is True:
                    #     save_first_footfall(self.db, self.state, event)

                self.position = f.tell()

            if changed:
                # save_state_snapshot(self.db, self.state)
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
        # save_state_snapshot(self.db, self.state)
        # self.db.close()

        if self.observer:
            self.observer.stop()
            self.observer.join()
