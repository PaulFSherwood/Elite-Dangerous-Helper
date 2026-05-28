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
