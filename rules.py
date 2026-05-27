from __future__ import annotations

from typing import Optional

from state import BodyInfo, CommanderState


def looks_like_suit(value: Optional[str]) -> bool:
    if not value:
        return False
    return "suit" in value.lower()

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
