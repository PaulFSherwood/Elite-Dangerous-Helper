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
        self.secondary_goal_map: dict[str, str] = {}
        self.goal_profiles: dict[str, dict[str, Any]] = {}
        self.buildout_stages: list[dict[str, Any]] = []
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
        self.secondary_goal_map = {
            str(name): str(goal)
            for name, goal in (raw.get("secondary_goal_map", {}) or {}).items()
            if str(name).strip() and str(goal).strip()
        }
        self.goal_profiles = {
            str(name): dict(profile)
            for name, profile in (raw.get("goal_profiles", {}) or {}).items()
            if isinstance(profile, dict)
        }
        self.buildout_stages = [
            dict(stage)
            for stage in (raw.get("buildout_stages", []) or [])
            if isinstance(stage, dict) and str(stage.get("name", "")).strip()
        ]

    def goal_steps(self, goal_name: str) -> list[tuple[FacilityRef, str]]:
        result: list[tuple[FacilityRef, str]] = []
        for step in self.goals.get(goal_name, []):
            facility = self.facilities.get(step.facility_id)
            if facility is not None:
                result.append((facility, step.reason))
        return result

    def mapped_secondary_goal(self, secondary_goal: str) -> str:
        return self.secondary_goal_map.get(str(secondary_goal or ""), "")

    def goal_requirement_counts(
        self, goal_name: str
    ) -> tuple[dict[tuple[str, str, int, str, str], int], bool]:
        """Return functional requirement multiplicity plus primary-port requirement.

        Goal completion is layout-independent.  If a recipe names Hephaestus but
        an equivalent Opis already exists, that requirement is satisfied.  Counts
        are preserved so recipes that intentionally need two equivalent outposts
        still require two physical facilities.
        """

        counts: dict[tuple[str, str, int, str, str], int] = {}
        needs_primary = False
        for facility, _reason in self.goal_steps(goal_name):
            if facility.id == "primary_port":
                needs_primary = True
                continue
            signature = self.functional_signature(facility)
            counts[signature] = counts.get(signature, 0) + 1
        return counts, needs_primary

    def goal_progress(
        self,
        goal_name: str,
        completed_facilities: list[FacilityRef],
        *,
        primary_port_complete: bool = False,
        active_facilities: list[FacilityRef] | None = None,
    ) -> dict[str, Any]:
        """Evaluate Not started / In progress / Complete for one goal.

        Only completed physical facilities satisfy the goal.  A currently-building
        matching facility can move the status to In progress, but does not count as
        complete until construction actually finishes.
        """

        required, needs_primary = self.goal_requirement_counts(goal_name)
        completed_counts: dict[tuple[str, str, int, str, str], int] = {}
        for facility in completed_facilities:
            if facility.id == "primary_port":
                continue
            signature = self.functional_signature(facility)
            completed_counts[signature] = completed_counts.get(signature, 0) + 1

        satisfied = sum(
            min(count, completed_counts.get(signature, 0))
            for signature, count in required.items()
        )
        total = sum(required.values())
        primary_ok = not needs_primary or primary_port_complete
        complete = satisfied >= total and primary_ok

        active_match = False
        for facility in active_facilities or []:
            signature = self.functional_signature(facility)
            if signature in required and completed_counts.get(signature, 0) < required[signature]:
                active_match = True
                break

        if complete:
            status = "Complete"
        elif satisfied > 0 or active_match:
            status = "In progress"
        else:
            status = "Not started"

        return {
            "goal": goal_name,
            "status": status,
            "satisfied": satisfied,
            "total": total,
            "primary_required": needs_primary,
            "primary_complete": primary_port_complete,
        }

    def stage_facilities(self, stage: dict[str, Any]) -> list[FacilityRef]:
        result: list[FacilityRef] = []
        seen: set[tuple[str, str, int, str, str]] = set()
        for facility_id in stage.get("facility_ids", []) or []:
            facility = self.facilities.get(str(facility_id))
            if facility is None:
                continue
            signature = self.functional_signature(facility)
            if signature in seen:
                continue
            seen.add(signature)
            result.append(facility)
        return result

    def ordered_buildout_stages(
        self,
        primary_goal: str,
        secondary_goal: str,
        known_facilities: list[FacilityRef],
    ) -> list[dict[str, Any]]:
        """Rank optional post-goal development stages for the current system.

        This is deliberately heuristic rather than a MILP clone: Observatory's
        job is to explain the next useful build while the commander is actively
        colonising.  Stages that are nearly complete and overlap the selected
        economies rise first; broad late-stage categories remain available after
        the original goals are met.
        """

        known_counts: dict[tuple[str, str, int, str, str], int] = {}
        known_economies: set[str] = set()
        for facility in known_facilities:
            signature = self.functional_signature(facility)
            known_counts[signature] = known_counts.get(signature, 0) + 1
            economy = self._normalise(facility.market_economy or facility.economy)
            if economy:
                known_economies.add(economy)

        goal_weights = self.goal_economy_weights(primary_goal, secondary_goal)
        ranked: list[tuple[int, str, dict[str, Any]]] = []
        for raw_stage in self.buildout_stages:
            stage = dict(raw_stage)
            facilities = self.stage_facilities(stage)
            if not facilities:
                continue
            signatures = [self.functional_signature(facility) for facility in facilities]
            satisfied = sum(1 for signature in signatures if known_counts.get(signature, 0) > 0)
            total = len(signatures)
            missing = max(0, total - satisfied)
            if missing == 0:
                stage["status"] = "Complete"
            elif satisfied:
                stage["status"] = "In progress"
            else:
                stage["status"] = "Not started"
            stage["satisfied"] = satisfied
            stage["total"] = total

            overlap = 0
            novelty = 0
            for economy, value in (stage.get("economies", {}) or {}).items():
                key = self._normalise(str(economy))
                try:
                    amount = int(value)
                except (TypeError, ValueError):
                    amount = 0
                overlap += amount * goal_weights.get(key, 0)
                if key and key not in known_economies:
                    novelty += amount
            try:
                priority = int(stage.get("priority", 0) or 0)
            except (TypeError, ValueError):
                priority = 0
            coverage_bonus = int(80 * satisfied / max(1, total))
            score = priority + 4 * overlap + 5 * novelty + coverage_bonus - 3 * missing
            stage["score"] = score
            ranked.append((-score, str(stage.get("name", "")), stage))

        ranked.sort()
        return [stage for _score, _name, stage in ranked]

    def combined_goal_steps(
        self,
        primary_goal: str,
        secondary_goal: str = "None",
        *,
        include_network_support: bool = True,
    ) -> list[tuple[FacilityRef, str]]:
        """Merge both dropdowns into one functional system blueprint.

        Primary recipe rows retain priority.  Goal-aligned orbital support is
        deliberately introduced immediately after the primary/claim station so
        a fresh plan starts building a surface+orbit network early instead of
        treating orbit as an afterthought.  The secondary dropdown then adds its
        missing facilities without duplicating exact layouts already requested.
        """

        merged: list[tuple[FacilityRef, str]] = []
        exact_positions: dict[str, int] = {}

        def add_facility(facility: FacilityRef, reason: str) -> None:
            if facility.id in exact_positions:
                index = exact_positions[facility.id]
                current, current_reason = merged[index]
                if reason and reason not in current_reason:
                    merged[index] = (current, f"{current_reason}  •  {reason}")
                return
            exact_positions[facility.id] = len(merged)
            merged.append((facility, reason))

        primary_steps = self.goal_steps(primary_goal)
        for facility, reason in primary_steps:
            tagged = f"Primary ({primary_goal}): {reason}" if reason else f"Primary ({primary_goal})"
            add_facility(facility, tagged)
            if facility.id == "primary_port" and include_network_support:
                profile = self.goal_profiles.get(primary_goal, {})
                for facility_id in profile.get("orbital_support", []) or []:
                    support = self.facilities.get(str(facility_id))
                    if support is not None:
                        add_facility(
                            support,
                            f"Orbital network support for {primary_goal}; place with a port/body cluster for a strong link when possible.",
                        )

        mapped_goal = self.secondary_goal_map.get(secondary_goal, "")
        if secondary_goal and secondary_goal != "None" and mapped_goal:
            for facility, reason in self.goal_steps(mapped_goal):
                if facility.id == "primary_port":
                    continue
                tagged = (
                    f"Secondary ({secondary_goal}): {reason}"
                    if reason else f"Secondary ({secondary_goal})"
                )
                add_facility(facility, tagged)
            if include_network_support:
                profile = self.goal_profiles.get(mapped_goal, {})
                for facility_id in profile.get("orbital_support", []) or []:
                    support = self.facilities.get(str(facility_id))
                    if support is not None:
                        add_facility(
                            support,
                            f"Orbital network support for secondary goal {secondary_goal}.",
                        )
        return merged

    def goal_economy_weights(
        self,
        primary_goal: str,
        secondary_goal: str = "None",
    ) -> dict[str, int]:
        """Soft economy preferences from both selected goals.

        Explicit goal-profile weights take precedence over inferring economy
        from recipe rows.  Primary weights are stronger than secondary weights.
        """

        weights: dict[str, int] = {}

        def apply(goal_name: str, multiplier: int) -> None:
            profile = self.goal_profiles.get(goal_name, {})
            explicit = profile.get("economies", {}) or {}
            if isinstance(explicit, dict) and explicit:
                for economy, value in explicit.items():
                    try:
                        amount = int(value)
                    except (TypeError, ValueError):
                        continue
                    key = self._normalise(str(economy))
                    if key:
                        weights[key] = weights.get(key, 0) + multiplier * amount
                return
            for facility, _reason in self.goal_steps(goal_name):
                economy = facility.market_economy or facility.economy
                if economy:
                    key = self._normalise(economy)
                    weights[key] = weights.get(key, 0) + multiplier

        apply(primary_goal, 3)
        mapped_goal = self.secondary_goal_map.get(secondary_goal, "")
        if mapped_goal:
            apply(mapped_goal, 1)
        return weights

    @classmethod
    def functional_signature(cls, facility: FacilityRef) -> tuple[str, str, int, str, str]:
        """Return a layout-independent identity for mechanically equivalent rows.

        Named layouts such as Aerecura/Erebus or Hephaestus/Opis have the same
        game mechanics.  Existing systems should therefore satisfy a goal with
        an equivalent layout rather than being told to build the exact cosmetic
        name from a recipe.
        """

        return (
            cls._normalise(facility.facility_type),
            cls._normalise(facility.category),
            int(facility.tier or 0),
            cls._normalise(facility.site_type),
            cls._normalise(facility.economy),
        )

    @staticmethod
    def is_port(facility: FacilityRef) -> bool:
        return facility.facility_type in {"Primary Port", "Planetary Port", "Starport", "Outpost"}

    @staticmethod
    def is_supporting_facility(facility: FacilityRef) -> bool:
        return facility.facility_type in {"Settlement", "Installation", "Hub"}

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

    @classmethod
    def point_shortfall(
        cls,
        facility: FacilityRef,
        tier_2: int,
        tier_3: int,
        *,
        previous_t2_ports: int = 0,
        previous_t3_ports: int = 0,
    ) -> tuple[int, int]:
        """Return only the construction points still missing for ``facility``.

        Keeping this calculation in the catalog gives the UI one authoritative
        affordability rule.  In particular, a facility must never be labelled
        NEXT merely because it is the first queued row if the commander cannot
        currently pay its point cost.
        """

        cost_t2, cost_t3 = cls.point_cost(
            facility,
            previous_t2_ports=previous_t2_ports,
            previous_t3_ports=previous_t3_ports,
        )
        return max(0, cost_t2 - int(tier_2)), max(0, cost_t3 - int(tier_3))

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
