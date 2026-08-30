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
class FacilityPrerequisite:
    """Structured prerequisite for a facility.

    Prerequisites deliberately describe *what kind of facility* must already
    exist rather than naming one exact layout.  Elite's construction menu may
    phrase a dependency as, for example, ``Settlement - Extraction``.  Any
    completed facility with matching structured attributes should satisfy that
    dependency, regardless of its layout/name.
    """

    facility_type: str = ""
    category: str = ""
    economy: str = ""
    min_tier: int = 0

    @property
    def display_name(self) -> str:
        pieces = [piece for piece in (self.facility_type, self.category, self.economy) if piece]
        return " - ".join(pieces) if pieces else "Facility prerequisite"


@dataclass(frozen=True)
class FacilityDescriptor:
    """Minimal structured identity used when a site entry is free-form text."""

    facility_type: str = ""
    category: str = ""
    economy: str = ""
    tier: int = 0
    facility_id: str = ""

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
    market_economy: str = ""
    construction_tonnage: int = 0
    point_cost_mode: str = "fixed"
    preferred_rank: int = 0
    requires_tier_2: int = 0
    requires_tier_3: int = 0
    provides_tier_2: int = 0
    provides_tier_3: int = 0
    confidence: str = "unverified"
    notes: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    prerequisites: tuple[FacilityPrerequisite, ...] = field(default_factory=tuple)
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

    @property
    def descriptor(self) -> FacilityDescriptor:
        return FacilityDescriptor(
            facility_type=self.facility_type,
            category=self.category,
            economy=self.economy,
            tier=self.tier,
            facility_id=self.id,
        )


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
                prerequisites: list[FacilityPrerequisite] = []
                for prerequisite in row.get("prerequisites", []) or []:
                    if not isinstance(prerequisite, dict):
                        continue
                    try:
                        prerequisites.append(
                            FacilityPrerequisite(
                                facility_type=str(prerequisite.get("facility_type", "")).strip(),
                                category=str(prerequisite.get("category", "")).strip(),
                                economy=str(prerequisite.get("economy", "")).strip(),
                                min_tier=int(prerequisite.get("min_tier", 0) or 0),
                            )
                        )
                    except (TypeError, ValueError):
                        continue
                facility = FacilityRef(
                    id=str(row["id"]),
                    name=str(row.get("name", row["id"])),
                    facility_type=str(row.get("facility_type", "Unknown")),
                    category=str(row.get("category", "")),
                    tier=int(row.get("tier", 0) or 0),
                    site_type=str(row.get("site_type", "surface")),
                    economy=str(row.get("economy", "")),
                    market_economy=str(row.get("market_economy", "")),
                    construction_tonnage=int(row.get("construction_tonnage", 0) or 0),
                    point_cost_mode=str(row.get("point_cost_mode", "fixed") or "fixed"),
                    preferred_rank=int(row.get("preferred_rank", 0) or 0),
                    requires_tier_2=int(requires.get("tier_2", 0) or 0),
                    requires_tier_3=int(requires.get("tier_3", 0) or 0),
                    provides_tier_2=int(provides.get("tier_2", 0) or 0),
                    provides_tier_3=int(provides.get("tier_3", 0) or 0),
                    confidence=str(verification.get("status", "unverified")),
                    notes=str(row.get("notes", "")),
                    aliases=tuple(
                        str(alias).strip()
                        for alias in row.get("aliases", []) or []
                        if str(alias).strip()
                    ),
                    prerequisites=tuple(prerequisites),
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

    @staticmethod
    def _normalise(value: str) -> str:
        text = str(value or "").casefold().replace("–", "-").replace("—", "-")
        return " ".join(text.replace("/", " ").replace("-", " ").split())

    @classmethod
    def descriptor_matches_prerequisite(
        cls,
        descriptor: FacilityDescriptor,
        prerequisite: FacilityPrerequisite,
    ) -> bool:
        if prerequisite.facility_type:
            if cls._normalise(descriptor.facility_type) != cls._normalise(prerequisite.facility_type):
                return False
        if prerequisite.category:
            if cls._normalise(descriptor.category) != cls._normalise(prerequisite.category):
                return False
        if prerequisite.economy:
            if cls._normalise(descriptor.economy) != cls._normalise(prerequisite.economy):
                return False
        if prerequisite.min_tier and int(descriptor.tier or 0) < prerequisite.min_tier:
            return False
        return True

    def facility_matches_prerequisite(
        self,
        facility: FacilityRef,
        prerequisite: FacilityPrerequisite,
    ) -> bool:
        return self.descriptor_matches_prerequisite(facility.descriptor, prerequisite)

    def matching_facilities(self, prerequisite: FacilityPrerequisite) -> list[FacilityRef]:
        return [
            facility
            for facility in self.facilities.values()
            if self.facility_matches_prerequisite(facility, prerequisite)
        ]

    @staticmethod
    def point_cost(facility: FacilityRef, *, previous_t2_ports: int = 0, previous_t3_ports: int = 0) -> tuple[int, int]:
        """Return the facility's construction-point cost in the current system state.

        Frontier's port costs escalate system-wide.  Community data refreshed
        against Colonization Construction v3.4.1 and real-game checks gives:

        * Tier-2 ports (Coriolis/Asteroid Base): 3, 5, 7, 9, ... T2.
        * Tier-3 ports (Orbis/Ocellus/Dodec/Planetary Port): 6, 12, 18, ... T3.

        The original claim/primary station is handled separately by Observatory
        and does not consume from either escalating sequence.
        """

        if facility.point_cost_mode == "t2_port":
            return 3 + 2 * max(0, int(previous_t2_ports)), 0
        if facility.point_cost_mode == "t3_port":
            return 0, 6 * (max(0, int(previous_t3_ports)) + 1)
        return facility.requires_tier_2, facility.requires_tier_3

    @classmethod
    def _can_pay(
        cls,
        facility: FacilityRef,
        tier_2: int,
        tier_3: int,
        *,
        previous_t2_ports: int = 0,
        previous_t3_ports: int = 0,
    ) -> bool:
        cost_t2, cost_t3 = cls.point_cost(
            facility,
            previous_t2_ports=previous_t2_ports,
            previous_t3_ports=previous_t3_ports,
        )
        return cost_t2 <= tier_2 and cost_t3 <= tier_3

    def best_prerequisite_candidate(
        self,
        prerequisite: FacilityPrerequisite,
        *,
        available_tier_2: int = 0,
        available_tier_3: int = 0,
    ) -> FacilityRef | None:
        """Pick the strongest matching prerequisite that can be built *now*.

        Buildable candidates are preferred over blocked ones.  Within that
        group, favour the facility that yields the most next-tier construction
        points, then the lower construction-point cost.  This makes a large
        Extraction settlement such as Aerecura preferable when the commander
        has the one T2 point required to build it.
        """

        candidates = self.matching_facilities(prerequisite)
        if not candidates:
            return None

        buildable = [
            facility
            for facility in candidates
            if self._can_pay(facility, available_tier_2, available_tier_3)
        ]
        pool = buildable or candidates

        def sort_key(facility: FacilityRef) -> tuple[int, int, int, int, int, int, str]:
            cost_t2, cost_t3 = self.point_cost(facility)
            shortage = max(0, cost_t2 - available_tier_2) + max(0, cost_t3 - available_tier_3)
            total_cost = cost_t2 + cost_t3
            # Higher next-tier reward is useful, but among mechanically equal
            # choices prefer less hauling.  preferred_rank is only a stable
            # tie-break for otherwise equivalent cosmetic layouts.
            tonnage = facility.construction_tonnage or 10**9
            return (
                -shortage,
                facility.provides_tier_3,
                facility.provides_tier_2,
                -total_cost,
                -tonnage,
                facility.preferred_rank,
                facility.display_name.casefold(),
            )

        return max(pool, key=sort_key)

    def facility_from_text(self, text: str) -> FacilityRef | None:
        """Resolve a free-form site marker to a known facility when possible."""

        normalised = self._normalise(text)
        if not normalised:
            return None
        best: tuple[int, FacilityRef] | None = None
        for facility in self.facilities.values():
            names = (facility.name, facility.display_name, *facility.aliases)
            for name in names:
                candidate = self._normalise(name)
                if not candidate:
                    continue
                if normalised == candidate:
                    score = 1000 + len(candidate)
                elif f" {candidate} " in f" {normalised} ":
                    score = len(candidate)
                else:
                    continue
                if best is None or score > best[0]:
                    best = (score, facility)
        return best[1] if best else None

    def descriptor_from_text(self, text: str) -> FacilityDescriptor | None:
        """Classify a site marker by facility type/economy, not layout name.

        Exact known layouts are resolved first so their authoritative metadata
        is used.  The lightweight fallback lets an entry such as "Extraction
        Settlement" satisfy a ``Settlement - Extraction`` prerequisite even if
        its exact layout name has not been added to the local database yet.
        """

        known = self.facility_from_text(text)
        if known is not None:
            return known.descriptor

        normalised = self._normalise(text)
        if not normalised:
            return None

        facility_type = ""
        if "settlement" in normalised:
            facility_type = "Settlement"
        elif "hub" in normalised:
            facility_type = "Hub"
        elif "installation" in normalised or "station" in normalised or "space farm" in normalised:
            facility_type = "Installation"
        elif "planetary port" in normalised or "planetary outpost" in normalised:
            facility_type = "Planetary Port"
        elif "starport" in normalised or "asteroid base" in normalised:
            facility_type = "Starport"
        elif "outpost" in normalised:
            facility_type = "Outpost"

        economy = ""
        economy_words = (
            ("Extraction", ("extraction", "mining")),
            ("Industrial", ("industrial",)),
            ("Research Bio", ("research bio",)),
            ("Scientific", ("scientific", "research")),
            ("Civilian", ("civilian",)),
            ("Agriculture", ("agriculture", "agricultural")),
            ("Tourism", ("tourism", "tourist")),
            ("Military", ("military",)),
            ("High Tech", ("high tech", "hightech")),
            ("Refinery", ("refinery", "refining")),
        )
        for economy_name, words in economy_words:
            if any(word in normalised for word in words):
                economy = economy_name
                break

        category = ""
        category_words = (
            "Large Mining Settlement", "Medium Mining Settlement", "Small Mining Settlement",
            "Large Agricultural Settlement", "Medium Agricultural Settlement", "Small Agricultural Settlement",
            "Large Industrial Settlement", "Medium Industrial Settlement", "Small Industrial Settlement",
            "Large Military Settlement", "Medium Military Settlement", "Small Military Settlement",
            "Large Scientific Settlement", "Medium Scientific Settlement", "Small Scientific Settlement",
            "Large Tourism Settlement", "Medium Tourism Settlement", "Small Tourism Settlement",
            "Communication Station", "Space Farm", "Mining Outpost", "Relay Station",
            "Research Station", "Security Station", "Satellite", "Military", "Tourist",
        )
        for category_name in category_words:
            if self._normalise(category_name) in normalised:
                category = category_name
                break

        if not facility_type and not category and not economy:
            return None
        return FacilityDescriptor(
            facility_type=facility_type,
            category=category,
            economy=economy,
        )

    def text_satisfies_prerequisite(self, text: str, prerequisite: FacilityPrerequisite) -> bool:
        descriptor = self.descriptor_from_text(text)
        return bool(
            descriptor is not None
            and self.descriptor_matches_prerequisite(descriptor, prerequisite)
        )
