from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional


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
    mass_em: Optional[float] = None
    gravity_g: Optional[float] = None
    atmosphere: str = ""
    volcanism: str = ""
    parents: list[dict] = field(default_factory=list)

    materials: dict[str, float] = field(default_factory=dict)
    rings: list[dict] = field(default_factory=list)
    mining_signals: list[dict] = field(default_factory=list)
    search_match: str = ""

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

    # FSS completion is separate from the number of Scan events loaded for the
    # current visit. Elite can report a system as 100% complete even when it
    # does not replay every old Scan event after returning to the system.
    fss_progress: Optional[float] = None
    fss_complete: bool = False
    system_fss_cache: dict[str, tuple[Optional[float], bool]] = field(default_factory=dict)

    # Persistent journal-history index. Keys are addr:<SystemAddress> and, when
    # available, name:<lowercase system name>. Values are the known body count.
    fss_completed_systems: dict[str, Optional[int]] = field(default_factory=dict)

    latitude: Optional[float] = None
    longitude: Optional[float] = None

    last_event: Optional[str] = None
    last_timestamp: Optional[str] = None
    messages: list[str] = field(default_factory=list)

    special_alerts: list[str] = field(default_factory=list)
    special_seen: set[str] = field(default_factory=set)

    systems_visited: int | None = None
    planets_scanned_level_3: int | None = None
    efficient_scans: int | None = None
    first_footfalls: int | None = None
    session_bio_completed: int = 0

    # Unsold exploration and exobiology data.
    # Sets prevent duplicate journal events from increasing the counters.
    held_exploration_systems: set[str] = field(default_factory=set)
    held_bio_samples: set[str] = field(default_factory=set)

    construction_depots: dict[str, dict] = field(default_factory=dict)
    latest_construction_depot_key: Optional[str] = None

    live_updates_enabled: bool = False
    seen_scan_body_ids: set[int] = field(default_factory=set)
    seen_first_footfall_bodies: set[int] = field(default_factory=set)

    def log(self, msg: str) -> None:
        self.messages.append(msg)
        self.messages = self.messages[-12:]

def system_cache_keys(system: Optional[str], address: Optional[int]) -> list[str]:
    keys: list[str] = []

    if address is not None:
        keys.append(f"addr:{address}")

    if system:
        keys.append(f"name:{system.lower()}")

    return keys


def system_cache_key(system: Optional[str], address: Optional[int]) -> Optional[str]:
    keys = system_cache_keys(system, address)
    return keys[0] if keys else None


def cache_current_system(state: CommanderState) -> None:
    key = system_cache_key(state.system, state.system_address)

    if not key:
        return

    if state.bodies:
        state.system_body_cache[key] = copy.deepcopy(state.bodies)

    state.system_count_cache[key] = (state.body_count, state.non_body_count)
    state.system_fss_cache[key] = (state.fss_progress, state.fss_complete)


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
    else:
        state.body_count = None
        state.non_body_count = None

    if key in state.system_fss_cache:
        state.fss_progress, state.fss_complete = state.system_fss_cache[key]
    else:
        state.fss_progress = None
        state.fss_complete = False

    # A completed-system record can come from a much older journal file than
    # the normal body-history window. Prefer the address key, but also accept
    # the name key for older events that did not include an address.
    for completed_key in system_cache_keys(state.system, state.system_address):
        if completed_key not in state.fss_completed_systems:
            continue

        state.fss_complete = True
        if state.fss_progress is None:
            state.fss_progress = 1.0

        completed_count = state.fss_completed_systems.get(completed_key)
        if state.body_count is None and completed_count is not None:
            state.body_count = completed_count
        break
