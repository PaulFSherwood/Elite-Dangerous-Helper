from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
# from db import connect_db, init_db, save_state_snapshot, save_first_footfall
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QSettings, pyqtSignal

from state import (
    BodyInfo,
    CommanderState,
    commodity_key,
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
CONSTRUCTION_BODY_INDEX_KEY = "construction/body_index"
CONSTRUCTION_BODY_INDEXED_FILES_KEY = "construction/body_indexed_files"
CARRIER_INVENTORY_KEY = "construction/carrier_inventory"
CARRIER_INVENTORY_KNOWN_KEY = "construction/carrier_inventory_known"
CARRIER_KNOWN_COMMODITIES_KEY = "construction/carrier_known_commodities"
CARRIER_LAST_EVENT_TIMESTAMP_KEY = "construction/carrier_last_event_timestamp"
CARRIER_LAST_EVENT_FINGERPRINT_KEY = "construction/carrier_last_event_fingerprint"
CARRIER_TRACKING_VERSION_KEY = "construction/carrier_tracking_version"
CARRIER_TRACKING_VERSION = 2
OWNED_CARRIER_ID_KEY = "construction/owned_carrier_id"
MARKET_SOURCES_KEY = "construction/market_sources"
MARKET_SOURCES_BY_SYSTEM_KEY = "construction/market_sources_by_system"


def _settings_int_dict(settings: QSettings, key: str) -> dict[str, int]:
    raw = _settings_json_dict(settings, key)
    result: dict[str, int] = {}
    for name, count in raw.items():
        commodity = commodity_key(name)
        if not commodity:
            continue
        try:
            result[commodity] = max(0, int(count))
        except (TypeError, ValueError):
            continue
    return result


def _settings_string_list(settings: QSettings, key: str) -> set[str]:
    raw = settings.value(key, "[]")
    try:
        values = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return set()
    if not isinstance(values, list):
        return set()
    result: set[str] = set()
    for value in values:
        if str(value) == "*":
            result.add("*")
            continue
        key = commodity_key(value)
        if key:
            result.add(key)
    return result


def load_logistics_data(state: CommanderState, settings: QSettings) -> None:
    """Load persisted logistics without trusting v3.0.1's guessed carrier data."""
    state.ship_inventory = {}
    state.ship_inventory_known = False

    try:
        tracking_version = int(settings.value(CARRIER_TRACKING_VERSION_KEY, 0) or 0)
    except (TypeError, ValueError):
        tracking_version = 0

    if tracking_version == CARRIER_TRACKING_VERSION:
        state.carrier_inventory = _settings_int_dict(settings, CARRIER_INVENTORY_KEY)
        state.carrier_known_commodities = _settings_string_list(
            settings, CARRIER_KNOWN_COMMODITIES_KEY
        )
        state.carrier_inventory_known = bool(state.carrier_known_commodities)
        state.carrier_last_event_timestamp = str(
            settings.value(CARRIER_LAST_EVENT_TIMESTAMP_KEY, "") or ""
        )
        state.carrier_last_event_fingerprint = str(
            settings.value(CARRIER_LAST_EVENT_FINGERPRINT_KEY, "") or ""
        )
    else:
        # v3.0.1 reconstructed missing history as if the carrier had started at
        # zero, which can create phantom cargo. Require a fresh baseline once.
        state.carrier_inventory = {}
        state.carrier_known_commodities = set()
        state.carrier_inventory_known = False
        state.carrier_last_event_timestamp = ""
        state.carrier_last_event_fingerprint = ""

    raw_carrier_id = settings.value(OWNED_CARRIER_ID_KEY, "")
    try:
        state.owned_carrier_id = int(raw_carrier_id) if str(raw_carrier_id).strip() else None
    except (TypeError, ValueError):
        state.owned_carrier_id = None

    raw_sources = _settings_json_dict(settings, MARKET_SOURCES_KEY)
    state.market_sources = {
        commodity_key(name): str(location).strip()
        for name, location in raw_sources.items()
        if commodity_key(name) and str(location).strip()
    }

    raw_by_system = _settings_json_dict(settings, MARKET_SOURCES_BY_SYSTEM_KEY)
    by_system: dict[str, dict[str, str]] = {}
    for name, systems in raw_by_system.items():
        key = commodity_key(name)
        if not key or not isinstance(systems, dict):
            continue
        cleaned = {
            str(system).strip(): str(station).strip()
            for system, station in systems.items()
            if str(system).strip() and str(station).strip()
        }
        if cleaned:
            by_system[key] = cleaned
    state.market_sources_by_system = by_system


def save_logistics_data(state: CommanderState, settings: QSettings) -> None:
    settings.setValue(CARRIER_TRACKING_VERSION_KEY, CARRIER_TRACKING_VERSION)
    settings.setValue(
        CARRIER_INVENTORY_KEY,
        json.dumps(state.carrier_inventory, sort_keys=True),
    )
    settings.setValue(
        CARRIER_INVENTORY_KNOWN_KEY,
        bool(state.carrier_inventory_known),
    )
    settings.setValue(
        CARRIER_KNOWN_COMMODITIES_KEY,
        json.dumps(sorted(state.carrier_known_commodities)),
    )
    settings.setValue(
        CARRIER_LAST_EVENT_TIMESTAMP_KEY,
        state.carrier_last_event_timestamp,
    )
    settings.setValue(
        CARRIER_LAST_EVENT_FINGERPRINT_KEY,
        state.carrier_last_event_fingerprint,
    )
    if state.owned_carrier_id is None:
        settings.remove(OWNED_CARRIER_ID_KEY)
    else:
        settings.setValue(OWNED_CARRIER_ID_KEY, str(state.owned_carrier_id))
    settings.setValue(MARKET_SOURCES_KEY, json.dumps(state.market_sources, sort_keys=True))
    settings.setValue(
        MARKET_SOURCES_BY_SYSTEM_KEY,
        json.dumps(state.market_sources_by_system, sort_keys=True),
    )
    settings.sync()


def carrier_commodity_known(state: CommanderState, key: str) -> bool:
    key = commodity_key(key)
    return bool(
        state.carrier_inventory_known
        and key
        and ("*" in state.carrier_known_commodities or key in state.carrier_known_commodities)
    )


def _cargo_transfer_fingerprint(event: dict) -> str:
    return json.dumps(
        {
            "timestamp": event.get("timestamp", ""),
            "Transfers": event.get("Transfers", []) or [],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _mark_carrier_watermark(state: CommanderState, event: dict) -> None:
    timestamp = str(event.get("timestamp", "") or "")
    if timestamp:
        state.carrier_last_event_timestamp = timestamp
    state.carrier_last_event_fingerprint = _cargo_transfer_fingerprint(event)


def _apply_carrier_transfer(state: CommanderState, transfer: dict) -> bool:
    """Apply one transfer only when that commodity has a trustworthy baseline."""
    key = commodity_key(transfer.get("Type_Localised") or transfer.get("Type"))
    if not key or not carrier_commodity_known(state, key):
        return False
    try:
        count = max(0, int(transfer.get("Count", 0) or 0))
    except (TypeError, ValueError):
        return False
    if count <= 0:
        return False

    direction = str(transfer.get("Direction", "")).strip().lower()
    current = max(0, int(state.carrier_inventory.get(key, 0) or 0))
    if direction == "tocarrier":
        state.carrier_inventory[key] = current + count
    elif direction == "toship":
        if count > current:
            # A missing transfer happened while Observatory was not tracking, or
            # the baseline was wrong. Do not silently clamp and keep lying.
            state.carrier_inventory.pop(key, None)
            if "*" in state.carrier_known_commodities:
                state.carrier_known_commodities.clear()
            else:
                state.carrier_known_commodities.discard(key)
            state.carrier_inventory_known = bool(state.carrier_known_commodities)
            state.log(f"Carrier {key} baseline lost; reset after verifying inventory")
        else:
            state.carrier_inventory[key] = current - count
    else:
        return False
    return True


def apply_ship_snapshot(state: CommanderState, data: dict) -> bool:
    """Replace ship cargo from Elite's authoritative Cargo/Cargo.json snapshot.

    MarketBuy/MarketSell and CargoTransfer can arrive before Cargo.json is
    rewritten.  Ignore an older snapshot so it cannot temporarily roll the UI
    back to pre-transaction cargo.
    """
    if not isinstance(data, dict):
        return False
    snapshot_timestamp = str(data.get("timestamp", "") or "")
    if (
        state.ship_inventory_last_delta_timestamp
        and snapshot_timestamp
        and snapshot_timestamp < state.ship_inventory_last_delta_timestamp
    ):
        state.log("Ignored stale ship cargo snapshot")
        return False
    vessel = str(data.get("Vessel", "Ship") or "Ship").strip().lower()
    if vessel != "ship":
        return False

    inventory: dict[str, int] = {}
    for item in data.get("Inventory", []) or []:
        if not isinstance(item, dict):
            continue
        key = commodity_key(item.get("Name_Localised") or item.get("Name"))
        if not key:
            continue
        try:
            count = max(0, int(item.get("Count", 0) or 0))
        except (TypeError, ValueError):
            continue
        if count:
            inventory[key] = inventory.get(key, 0) + count

    changed = inventory != state.ship_inventory or not state.ship_inventory_known
    state.ship_inventory = inventory
    state.ship_inventory_known = True
    if snapshot_timestamp:
        state.ship_inventory_last_snapshot_timestamp = snapshot_timestamp
    return changed


def _apply_ship_delta(state: CommanderState, commodity: object, count: object, direction: int, timestamp: object = "") -> bool:
    """Apply immediate live ship-cargo evidence from a journal transaction."""
    if not state.ship_inventory_known:
        return False
    key = commodity_key(commodity)
    if not key:
        return False
    try:
        amount = max(0, int(count or 0))
    except (TypeError, ValueError):
        return False
    if amount <= 0:
        return False
    current = max(0, int(state.ship_inventory.get(key, 0) or 0))
    updated = max(0, current + direction * amount)
    if updated:
        state.ship_inventory[key] = updated
    else:
        state.ship_inventory.pop(key, None)
    stamp = str(timestamp or "")
    if stamp:
        state.ship_inventory_last_delta_timestamp = max(
            state.ship_inventory_last_delta_timestamp, stamp
        )
    return updated != current


def read_cargo_file(state: CommanderState, journal_dir: Path) -> bool:
    cargo_path = journal_dir / "Cargo.json"
    if not cargo_path.exists():
        return False
    try:
        with cargo_path.open("r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception as exc:
        state.log(f"Cargo read error: {exc}")
        return False
    return apply_ship_snapshot(state, data)


def _market_source_name(data: dict, state: CommanderState) -> str:
    return str(
        data.get("StationName")
        or state.station
        or data.get("StarSystem")
        or state.system
        or ""
    ).strip()


def _market_source_system(data: dict, state: CommanderState) -> str:
    return str(data.get("StarSystem") or state.system or "").strip()


def _remember_market_source(
    state: CommanderState, commodity: object, source: str, system: str
) -> bool:
    """Remember that a station sells a commodity, preserving sources per system."""
    key = commodity_key(commodity)
    source = str(source or "").strip()
    system = str(system or "").strip()
    if not key or not source:
        return False

    changed = False
    if system:
        systems = state.market_sources_by_system.setdefault(key, {})
        if systems.get(system) != source:
            systems[system] = source
            changed = True

    # Market snapshots are discovery evidence, not necessarily where the player
    # actually bought the item.  Keep the legacy/default source only when empty;
    # MarketBuy below updates it to the most recent purchase station.
    if key not in state.market_sources:
        state.market_sources[key] = source
        changed = True
    return changed


def apply_market_snapshot(state: CommanderState, data: dict) -> bool:
    """Learn buy locations from Market.json; never treat it as carrier storage."""
    if not isinstance(data, dict):
        return False

    source = _market_source_name(data, state)
    system = _market_source_system(data, state)
    if not source:
        return False

    changed = False
    for item in data.get("Items", []) or []:
        if not isinstance(item, dict):
            continue
        try:
            stock = int(item.get("Stock", 0) or 0)
        except (TypeError, ValueError):
            stock = 0

        keys = {
            commodity_key(item.get("Name")),
            commodity_key(item.get("Name_Localised")),
        }
        for key in keys:
            if not key:
                continue
            if stock > 0:
                if _remember_market_source(state, key, source, system):
                    changed = True
                continue

            # If a refreshed Market.json says this exact remembered station has
            # no stock, stop advertising it as a local source.  We intentionally
            # leave the generic last-purchase source alone: that is history, not
            # a claim that the station currently has stock.
            if system:
                systems = state.market_sources_by_system.get(key, {})
                if systems.get(system) == source:
                    systems.pop(system, None)
                    if not systems:
                        state.market_sources_by_system.pop(key, None)
                    changed = True

    return changed


def read_market_file(state: CommanderState, journal_dir: Path) -> bool:
    market_path = journal_dir / "Market.json"
    if not market_path.exists():
        return False
    try:
        with market_path.open("r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception as exc:
        state.log(f"Market read error: {exc}")
        return False
    changed = apply_market_snapshot(state, data)
    if changed:
        state.log(f"Market source scan: {_market_source_name(data, state)}")
    return changed


def restore_carrier_tracking(
    state: CommanderState,
    journal_dir: Path,
) -> tuple[int, int, bool]:
    """Safely advance a persisted carrier baseline through journal history.

    If a CarrierBuy exists, that purchase is a genuine all-zero baseline. Without
    one, historical CargoTransfer events are never assumed to start from zero.
    A manual "carrier empty" baseline therefore remains exact across app restarts:
    only transfer events newer than its saved watermark are replayed.
    """
    files = sorted(journal_dir.glob("Journal*.log"), key=lambda p: p.name)
    events_applied = 0
    purchase_baseline = False
    persisted_baseline = bool(state.carrier_inventory_known)
    watermark = state.carrier_last_event_timestamp

    for journal_path in files:
        try:
            with journal_path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not any(token in line for token in (
                        '"CargoTransfer"', '"CarrierBuy"', '"CarrierStats"'
                    )):
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    name = event.get("event")
                    if name == "CarrierStats":
                        try:
                            state.owned_carrier_id = int(event.get("CarrierID"))
                        except (TypeError, ValueError):
                            pass
                        continue

                    if name == "CarrierBuy":
                        if persisted_baseline:
                            # The user's saved baseline is later than old purchase
                            # history; do not rewind it during startup.
                            continue
                        state.carrier_inventory.clear()
                        state.carrier_known_commodities = {"*"}
                        state.carrier_inventory_known = True
                        state.carrier_last_event_timestamp = str(event.get("timestamp", "") or "")
                        state.carrier_last_event_fingerprint = ""
                        purchase_baseline = True
                        try:
                            state.owned_carrier_id = int(event.get("CarrierID"))
                        except (TypeError, ValueError):
                            pass
                        continue

                    if name != "CargoTransfer" or not state.carrier_inventory_known:
                        continue

                    timestamp = str(event.get("timestamp", "") or "")
                    if persisted_baseline and watermark and timestamp <= watermark:
                        continue

                    changed = False
                    for transfer in event.get("Transfers", []) or []:
                        if isinstance(transfer, dict) and _apply_carrier_transfer(state, transfer):
                            changed = True
                    _mark_carrier_watermark(state, event)
                    if changed:
                        events_applied += 1
        except OSError:
            continue

    return len(files), events_applied, purchase_baseline

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



def _body_to_json(body: BodyInfo) -> dict:
    """Serialize the journal fields needed by the construction Sites view."""
    return {
        "name": body.name,
        "body_id": body.body_id,
        "kind": body.kind,
        "subtype": body.subtype,
        "distance_ls": body.distance_ls,
        "landable": body.landable,
        "mapped": body.mapped,
        "scanned": body.scanned,
        "terraform_state": body.terraform_state,
        "radius_m": body.radius_m,
        "surface_temp_k": body.surface_temp_k,
        "materials": body.materials,
        "rings": body.rings,
    }


def _body_from_json(data: dict) -> Optional[BodyInfo]:
    if not isinstance(data, dict) or not data.get("name"):
        return None
    allowed = {
        key: data[key]
        for key in BodyInfo.__dataclass_fields__
        if key in data
    }
    try:
        return BodyInfo(**allowed)
    except TypeError:
        return None


def load_construction_body_index(state: CommanderState, settings: QSettings) -> None:
    """Restore the full-history system/body index used by Construction mode."""
    raw = _settings_json_dict(settings, CONSTRUCTION_BODY_INDEX_KEY)
    for system_key, rows in raw.items():
        if not isinstance(system_key, str) or not isinstance(rows, dict):
            continue
        bodies: dict[str, BodyInfo] = {}
        for body_name, body_data in rows.items():
            body = _body_from_json(body_data)
            if body is not None:
                bodies[str(body_name)] = body
        if bodies:
            state.system_body_cache[system_key] = bodies


def save_construction_body_index(state: CommanderState, settings: QSettings) -> None:
    payload = {
        system_key: {
            body_name: _body_to_json(body)
            for body_name, body in bodies.items()
        }
        for system_key, bodies in state.system_body_cache.items()
        if bodies
    }
    settings.setValue(
        CONSTRUCTION_BODY_INDEX_KEY,
        json.dumps(payload, sort_keys=True),
    )
    settings.sync()


def _scan_body_history_file(state: CommanderState, journal_path: Path) -> int:
    """Index every scanned star, planet, moon, and belt-like body in a journal."""
    added = 0
    with journal_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"event":"Scan"' not in line and '"event": "Scan"' not in line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") != "Scan":
                continue
            body_name = event.get("BodyName")
            address = event.get("SystemAddress")
            system = event.get("StarSystem")
            if not body_name or (address is None and not system):
                continue

            if event.get("StarType") is not None:
                kind = "Star"
                subtype = event.get("StarType") or "Unknown star"
            elif event.get("PlanetClass") is not None:
                kind = "Planet"
                subtype = event.get("PlanetClass") or "Unknown planet"
            else:
                # Keep unusual scan bodies too. This gives Construction mode a
                # chance to show belt clusters or future body types rather than
                # silently dropping them.
                kind = "Body"
                subtype = event.get("BodyType") or "Unknown"

            body = BodyInfo(
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
                mass_em=event.get("MassEM"),
                gravity_g=(event.get("SurfaceGravity") / 9.80665) if event.get("SurfaceGravity") is not None else None,
                atmosphere=event.get("Atmosphere") or event.get("AtmosphereType") or "",
                volcanism=event.get("Volcanism") or "",
                parents=event.get("Parents", []),
                materials={
                    str(row.get("Name", "")).lower(): row.get("Percent")
                    for row in event.get("Materials", [])
                    if row.get("Name") and row.get("Percent") is not None
                },
                rings=event.get("Rings", []),
            )

            for key in system_cache_keys(system, address):
                bodies = state.system_body_cache.setdefault(key, {})
                if body_name not in bodies:
                    added += 1
                bodies[body_name] = body
    return added


def index_construction_body_history(
    state: CommanderState,
    settings: QSettings,
    journal_dir: Path,
) -> tuple[int, int]:
    """Incrementally build a persistent all-journal body index.

    Exploration may intentionally load only recent journal files. Construction
    cannot do that: its Sites view must show every known body in the selected
    system, including bodies scanned months earlier.
    """
    indexed_files = _settings_json_dict(
        settings,
        CONSTRUCTION_BODY_INDEXED_FILES_KEY,
    )
    files_scanned = 0
    bodies_added = 0

    journals = sorted(
        journal_dir.glob("Journal*.log"),
        key=lambda path: path.stat().st_mtime,
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
            bodies_added += _scan_body_history_file(state, journal_path)
        except OSError:
            continue
        indexed_files[journal_path.name] = signature
        files_scanned += 1

    if files_scanned:
        settings.setValue(
            CONSTRUCTION_BODY_INDEXED_FILES_KEY,
            json.dumps(indexed_files, sort_keys=True),
        )
        save_construction_body_index(state, settings)
    return files_scanned, bodies_added


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

    elif name == "Cargo":
        if apply_ship_snapshot(state, event):
            state.log("Ship cargo snapshot updated")
            changed = True

    elif name == "CarrierBuy":
        try:
            state.owned_carrier_id = int(event.get("CarrierID"))
        except (TypeError, ValueError):
            pass
        if state.live_updates_enabled:
            # Carrier purchase is a real zero baseline for every commodity.
            state.carrier_inventory.clear()
            state.carrier_known_commodities = {"*"}
            state.carrier_inventory_known = True
            state.carrier_last_event_timestamp = str(event.get("timestamp", "") or "")
            state.carrier_last_event_fingerprint = ""
        changed = True

    elif name == "CarrierStats":
        try:
            state.owned_carrier_id = int(event.get("CarrierID"))
        except (TypeError, ValueError):
            pass
        changed = True

    elif name == "CargoTransfer":
        # CargoTransfer is the authoritative local delta for fleet-carrier cargo.
        # It is only applied to commodities with a trusted baseline. Cargo.json
        # separately supplies the ship side of the same transfer.
        if state.live_updates_enabled:
            transfer_changed = False
            ship_changed = False
            for transfer in event.get("Transfers", []) or []:
                if not isinstance(transfer, dict):
                    continue
                if _apply_carrier_transfer(state, transfer):
                    transfer_changed = True
                direction = str(transfer.get("Direction", "")).strip().lower()
                ship_direction = 1 if direction == "toship" else -1 if direction == "tocarrier" else 0
                if ship_direction and _apply_ship_delta(
                    state,
                    transfer.get("Type_Localised") or transfer.get("Type"),
                    transfer.get("Count", 0),
                    ship_direction,
                    event.get("timestamp", ""),
                ):
                    ship_changed = True
            _mark_carrier_watermark(state, event)
            if transfer_changed:
                state.log("Carrier cargo updated from transfer")
            if ship_changed:
                state.log("Ship cargo updated from transfer")
            if transfer_changed or ship_changed:
                changed = True

    elif name == "Market":
        # The journal event identifies the market; its full commodity list is in
        # Market.json and is read by JournalMonitor immediately after this event.
        market_system = event.get("StarSystem")
        if market_system:
            set_system(state, market_system, event.get("SystemAddress"), clear=False)
        state.station = event.get("StationName", state.station)
        changed = True

    elif name == "MarketBuy":
        # Buying is direct evidence that this station sells the commodity. Update
        # ship cargo immediately as well; Cargo.json may lag the journal event.
        if state.live_updates_enabled:
            commodity = event.get("Type_Localised") or event.get("Type")
            key = commodity_key(commodity)
            source = _market_source_name(event, state)
            system = _market_source_system(event, state)
            if key and source:
                # A purchase is stronger evidence than an old pasted/discovered
                # source.  Keep the latest purchase station so stale external
                # names naturally refresh.  Per-system history is retained so a
                # known local colony source still wins in the Materials view.
                previous = state.market_sources.get(key)
                state.market_sources[key] = source
                source_changed = previous != source
                if system:
                    systems = state.market_sources_by_system.setdefault(key, {})
                    if systems.get(system) != source:
                        systems[system] = source
                        source_changed = True
                if source_changed:
                    state.log(f"Material source updated: {source}")
                    changed = True
            if _apply_ship_delta(
                state, commodity, event.get("Count", 0), 1, event.get("timestamp", "")
            ):
                state.log("Ship cargo updated from market purchase")
                changed = True

    elif name == "MarketSell":
        if state.live_updates_enabled and _apply_ship_delta(
            state,
            event.get("Type_Localised") or event.get("Type"),
            event.get("Count", 0),
            -1,
            event.get("timestamp", ""),
        ):
            state.log("Ship cargo updated from market sale")
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


    elif name == "ColonisationConstructionDepot":
        market_id = event.get("MarketID")
        resources = []
        for row in event.get("ResourcesRequired", []) or []:
            commodity = (
                row.get("Name_Localised")
                or str(row.get("Name", "")).replace("$", "").replace("_name;", "").replace(";", "").title()
            )
            try:
                required = int(row.get("RequiredAmount", 0) or 0)
                delivered = int(row.get("ProvidedAmount", 0) or 0)
            except (TypeError, ValueError):
                continue
            if not commodity or required <= 0:
                continue
            resources.append({
                "commodity": commodity,
                "required": required,
                "delivered": delivered,
                "carrier": 0,
                "source": "Journal depot",
                "payment": row.get("Payment"),
            })

        if market_id is not None and resources:
            key = str(market_id)
            state.construction_depots[key] = {
                "market_id": key,
                "system": state.system,
                "system_address": state.system_address,
                "station": state.station or "Construction depot",
                "body": state.body or "Unknown body",
                "timestamp": event.get("timestamp"),
                "progress": event.get("ConstructionProgress"),
                "complete": bool(event.get("ConstructionComplete", False)),
                "failed": bool(event.get("ConstructionFailed", False)),
                "resources": resources,
            }
            state.latest_construction_depot_key = key
            state.log(f"Construction depot updated: {len(resources)} commodities")
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
    startup_progress = pyqtSignal(str)
    startup_finished = pyqtSignal()
    startup_failed = pyqtSignal(str)

    def __init__(self, journal_dir: Path, history_files: int = 30):
        super().__init__()
        self.history_files = history_files
        self.journal_dir = journal_dir
        self.settings = QSettings("GrrWooD", "EliteDangerousObservatory")
        self.state = CommanderState()
        load_held_data(self.state, self.settings)
        load_fss_data(self.state, self.settings)
        load_construction_body_index(self.state, self.settings)
        load_logistics_data(self.state, self.settings)
        # self.db = connect_db()
        # init_db(self.db)
        self.current_file: Optional[Path] = None
        self.position = 0
        self.lock = threading.Lock()
        self.observer: Optional[Observer] = None
        self._startup_thread: Optional[threading.Thread] = None

    def initialize(self) -> None:
        self.state.live_updates_enabled = False
        self.startup_progress.emit("Finding Elite journal files…")
        self.current_file = newest_journal_file(self.journal_dir)
        if not self.current_file:
            raise FileNotFoundError(f"No Journal*.log files found in {self.journal_dir}")

        journals = sorted(
            self.journal_dir.glob("Journal*.log"),
            key=lambda p: p.stat().st_mtime
        )

        self.startup_progress.emit("Indexing exploration history…")
        files_indexed, completion_keys_added = index_fss_history(
            self.state,
            self.settings,
            self.journal_dir,
        )
        self.startup_progress.emit("Indexing construction bodies and system sites…")
        body_files_indexed, bodies_added = index_construction_body_history(
            self.state,
            self.settings,
            self.journal_dir,
        )
        if files_indexed:
            self.state.log(
                f"FSS history indexed: {files_indexed} files, "
                f"{completion_keys_added} completion keys added"
            )
        if body_files_indexed:
            self.state.log(
                f"Construction body index: {body_files_indexed} files, "
                f"{bodies_added} bodies added"
            )

        self.startup_progress.emit("Restoring carrier and logistics state…")
        carrier_files, transfer_events, purchase_baseline = restore_carrier_tracking(
            self.state, self.journal_dir
        )
        if purchase_baseline:
            self.state.log(
                f"Carrier cargo reconstructed from purchase baseline: "
                f"{transfer_events} transfer events across {carrier_files} journal files"
            )
            save_logistics_data(self.state, self.settings)
        elif self.state.carrier_inventory_known and transfer_events:
            self.state.log(
                f"Carrier cargo advanced by {transfer_events} offline transfer events"
            )
            save_logistics_data(self.state, self.settings)
        elif not self.state.carrier_inventory_known:
            self.state.log("Carrier cargo baseline pending")

        journals_to_read = journals[-self.history_files:]
        self.startup_progress.emit(f"Reading {len(journals_to_read)} recent journal files…")

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
        self.startup_progress.emit("Loading route, Cargo.json, and Market.json…")
        read_nav_route(self.state, self.journal_dir)
        read_cargo_file(self.state, self.journal_dir)
        if read_market_file(self.state, self.journal_dir):
            save_logistics_data(self.state, self.settings)
        self.state.log(f"Watching: {self.current_file.name}")
        self.state.live_updates_enabled = True


    def set_carrier_empty_baseline(self, commodities: list[str]) -> None:
        """Mark selected construction commodities as zero on the carrier now."""
        keys = {commodity_key(name) for name in (commodities or []) if commodity_key(name)}
        if not keys:
            return
        with self.lock:
            for key in keys:
                self.state.carrier_inventory[key] = 0
            if "*" not in self.state.carrier_known_commodities:
                self.state.carrier_known_commodities.update(keys)
            self.state.carrier_inventory_known = True
            # The user's current carrier screen is the baseline. Ignore all
            # journal deltas at or before this instant; future CargoTransfer
            # events advance the saved snapshot.
            self.state.carrier_last_event_timestamp = (
                datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            )
            self.state.carrier_last_event_fingerprint = ""
            save_logistics_data(self.state, self.settings)
            self.state.log(f"Carrier zero baseline set for {len(keys)} construction commodities")
        self.updated.emit()

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

                    event_name = event.get("event")
                    if apply_event(self.state, event):
                        changed = True

                    if event_name == "Market":
                        if read_market_file(self.state, self.journal_dir):
                            changed = True

                    if event_name in {
                        "CargoTransfer", "MarketBuy", "MarketSell",
                        "ColonisationConstructionDepot",
                    }:
                        if read_cargo_file(self.state, self.journal_dir):
                            changed = True

                    if event_name in {
                        "CargoTransfer", "CarrierBuy", "CarrierStats",
                        "Market", "MarketBuy",
                    }:
                        save_logistics_data(self.state, self.settings)

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

    def start_async(self) -> None:
        """Load history off the GUI thread, then start live monitoring.

        Startup used to run before the main window was shown, which made a
        perfectly healthy launch look like the application never opened.
        Journal parsing is file/JSON work and does not need to block Qt's GUI
        event loop, so keep the window responsive while it is reconstructed.
        """
        if self._startup_thread is not None and self._startup_thread.is_alive():
            return

        def runner() -> None:
            try:
                self.start()
            except Exception as exc:
                self.startup_failed.emit(str(exc))
                return
            self.startup_finished.emit()

        self._startup_thread = threading.Thread(
            target=runner,
            name="observatory-startup",
            daemon=True,
        )
        self._startup_thread.start()

    def start(self) -> None:
        self.initialize()
        self.startup_progress.emit("Starting live journal monitor…")

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

                    if path.name.lower() == "market.json":
                        with monitor.lock:
                            if read_market_file(monitor.state, monitor.journal_dir):
                                save_logistics_data(monitor.state, monitor.settings)
                                monitor.updated.emit()
                        return

                    if path.name.lower() == "cargo.json":
                        with monitor.lock:
                            if read_cargo_file(monitor.state, monitor.journal_dir):
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

                    if path.name.lower() == "market.json":
                        with monitor.lock:
                            if read_market_file(monitor.state, monitor.journal_dir):
                                save_logistics_data(monitor.state, monitor.settings)
                                monitor.updated.emit()
                        return

                    if path.name.lower() == "cargo.json":
                        with monitor.lock:
                            if read_cargo_file(monitor.state, monitor.journal_dir):
                                monitor.updated.emit()
                        return

                    monitor.process_updates()

                def on_moved(self, event):
                    if event.is_directory:
                        return
                    path = Path(getattr(event, "dest_path", "") or event.src_path)
                    if path.name.lower() == "cargo.json":
                        with monitor.lock:
                            if read_cargo_file(monitor.state, monitor.journal_dir):
                                monitor.updated.emit()
                        return
                    if path.name.lower() == "market.json":
                        with monitor.lock:
                            if read_market_file(monitor.state, monitor.journal_dir):
                                save_logistics_data(monitor.state, monitor.settings)
                                monitor.updated.emit()
                        return
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
