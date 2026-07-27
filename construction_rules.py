from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent / "data"
FACILITY_FILE = DATA_DIR / "colonisation_facilities.json"


@dataclass(frozen=True)
class MaterialRequirement:
    """One commodity requirement for a facility when known.

    The facility database may omit materials for rows we have not verified yet.
    Missing material data should be shown as unknown, not guessed.
    """

    commodity: str
    required: int

@dataclass(frozen=True)
class FacilityRef:
    """One exact selectable construction facility/layout from the in-game menus."""

    id: str
    name: str
    facility_type: str
    category: str
    tier: int
    site_type: str
    economy: str = ""
    requires_tier_2: int = 0
    requires_tier_3: int = 0
    provides_tier_2: int = 0
    provides_tier_3: int = 0
    confidence: str = "unverified"
    notes: str = ""
    materials: tuple[MaterialRequirement, ...] = field(default_factory=tuple)

    @property
    def display_name(self) -> str:
        if self.id == "primary_port":
            return "Primary Port"
        pieces = [self.facility_type, f"Tier {self.tier}"]
        if self.category:
            pieces.append(self.category)
        pieces.append(self.name)
        if self.economy and self.economy != "Unknown":
            pieces[-1] = f"{pieces[-1]} ({self.economy})"
        return " / ".join(pieces)

    @property
    def point_summary(self) -> str:
        parts: list[str] = []
        if self.requires_tier_2:
            parts.append(f"requires {self.requires_tier_2} T2")
        if self.requires_tier_3:
            parts.append(f"requires {self.requires_tier_3} T3")
        if self.provides_tier_2:
            parts.append(f"provides +{self.provides_tier_2} T2")
        if self.provides_tier_3:
            parts.append(f"provides +{self.provides_tier_3} T3")
        return ", ".join(parts) if parts else "points unknown"


@dataclass(frozen=True)
class GoalStepRef:
    facility_id: str
    reason: str


class ColonisationCatalog:
    """Loads the colonisation facility database used by the planner.

    The JSON file is intentionally data-driven so facility tiers, point rewards,
    prerequisites, and goal recipes can be edited without changing UI code.
    """

    def __init__(self, path: Path = FACILITY_FILE):
        self.path = path
        self.facilities: dict[str, FacilityRef] = {}
        self.goals: dict[str, list[GoalStepRef]] = {}
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {"facilities": [], "goals": {}}

        facilities: dict[str, FacilityRef] = {}
        for row in raw.get("facilities", []):
            try:
                points = row.get("construction_points", {}) or {}
                requires = points.get("requires", {}) or {}
                provides = points.get("provides", {}) or {}
                verification = row.get("verification", {}) or {}
                materials: list[MaterialRequirement] = []
                for material in row.get("materials", []) or []:
                    try:
                        commodity = str(material.get("commodity", "")).strip()
                        required = int(material.get("required", 0) or 0)
                        if commodity and required > 0:
                            materials.append(MaterialRequirement(commodity=commodity, required=required))
                    except (AttributeError, TypeError, ValueError):
                        continue
                facility = FacilityRef(
                    id=str(row["id"]),
                    name=str(row.get("name", row["id"])),
                    facility_type=str(row.get("facility_type", "Unknown")),
                    category=str(row.get("category", "")),
                    tier=int(row.get("tier", 0) or 0),
                    site_type=str(row.get("site_type", "surface")),
                    economy=str(row.get("economy", "")),
                    requires_tier_2=int(requires.get("tier_2", 0) or 0),
                    requires_tier_3=int(requires.get("tier_3", 0) or 0),
                    provides_tier_2=int(provides.get("tier_2", 0) or 0),
                    provides_tier_3=int(provides.get("tier_3", 0) or 0),
                    confidence=str(verification.get("status", "unverified")),
                    notes=str(row.get("notes", "")),
                    materials=tuple(materials),
                )
                facilities[facility.id] = facility
            except (KeyError, TypeError, ValueError):
                continue
        self.facilities = facilities

        goals: dict[str, list[GoalStepRef]] = {}
        for goal_name, steps in (raw.get("goals", {}) or {}).items():
            parsed: list[GoalStepRef] = []
            for step in steps:
                if isinstance(step, str):
                    parsed.append(GoalStepRef(step, ""))
                elif isinstance(step, dict) and step.get("facility_id"):
                    parsed.append(
                        GoalStepRef(
                            facility_id=str(step["facility_id"]),
                            reason=str(step.get("reason", "")),
                        )
                    )
            goals[str(goal_name)] = parsed
        self.goals = goals

    def goal_steps(self, goal_name: str) -> list[tuple[FacilityRef, str]]:
        result: list[tuple[FacilityRef, str]] = []
        for step in self.goals.get(goal_name, []):
            facility = self.facilities.get(step.facility_id)
            if facility is not None:
                result.append((facility, step.reason))
        return result

    def facility(self, facility_id: str) -> FacilityRef | None:
        return self.facilities.get(facility_id)

    def material_requirements(self, facility_id: str) -> list[MaterialRequirement]:
        facility = self.facilities.get(facility_id)
        if facility is None:
            return []
        return list(facility.materials)

    def exact_names(self) -> list[str]:
        return [facility.display_name for facility in self.facilities.values()]
