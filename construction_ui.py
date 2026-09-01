from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from PyQt6.QtCore import Qt, QSettings, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from construction_rules import (
    ColonisationCatalog,
    FacilityDescriptor,
    FacilityPrerequisite,
    FacilityRef,
    MaterialRequirement,
)
from state import commodity_key


PRIMARY_GOALS = [
    "Expansion Materials Hub",
    "Tritium Production Hub",
    "Carrier Support Hub",
    "Industrial Hub",
    "Mining and Refinery Hub",
    "Agricultural Hub",
    "Research and Technology Hub",
    "Tourism Hub",
    "Population Center",
    "Balanced Colony",
    "Custom Plan",
]

SECONDARY_GOALS = [
    "None",
    "Expansion Support",
    "Carrier Support",
    "Tritium Availability",
    "Population Growth",
    "Commodity Profit",
    "Research Capability",
    "Tourism",
    "Mining and Refining",
    "Balanced Services",
]

PLAN_SCOPES = [
    "Primary Goal Only",
    "Primary + Secondary Goals",
    "Continue System Build-Out",
]

# Facility choices and goal recipes now live in data/colonisation_facilities.json.
# This default catalog is still usable if the JSON is incomplete, and the data
# file can be edited without touching the PyQt UI code.
CATALOG = ColonisationCatalog()


class BodySortItem(QTableWidgetItem):
    """QTableWidget item that keeps Elite bodies in natural system order."""

    def __init__(self, text: str, sort_key: tuple[Any, ...]):
        super().__init__(text)
        self.sort_key = sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, BodySortItem):
            return self.sort_key < other.sort_key
        return super().__lt__(other)


class NumericSortItem(QTableWidgetItem):
    """QTableWidget item that sorts comma-formatted numbers numerically."""

    def __init__(self, text: str, value: int):
        super().__init__(text)
        self.sort_value = int(value)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, NumericSortItem):
            return self.sort_value < other.sort_value
        try:
            other_value = int(other.text().replace(',', '').strip())
        except (AttributeError, ValueError):
            return super().__lt__(other)
        return self.sort_value < other_value


@dataclass
class SiteData:
    body: str
    body_type: str = "Unknown"
    landable: bool = False
    orbital_used: int = 0
    orbital_total: int = 0
    surface_used: int = 0
    surface_total: int = 0
    facility: str = ""
    status: str = "Available"
    confidence: str = "Needs entry"
    body_id: int = 999999
    mass_em: Optional[float] = None
    radius_km: Optional[float] = None
    atmosphere: str = ""
    volcanism: str = ""
    parent_body: str = ""
    distance_ls: Optional[float] = None


@dataclass
class MaterialData:
    commodity: str
    required: int = 0
    delivered: int = 0
    ship: int = 0
    carrier: int = 0
    source: str = ""

    @property
    def still_needed(self) -> int:
        # "Still needed" means material that still has to be acquired. Cargo
        # already on the ship or carrier is owned even though it is not yet
        # counted as Delivered by the construction depot.
        return max(
            0,
            int(self.required)
            - int(self.delivered)
            - int(self.ship)
            - int(self.carrier),
        )

@dataclass
class FacilityData:
    role: str
    reason: str
    preferred_site: str
    location: str = "Unassigned"
    status: str = "Queued"
    facility_id: str = ""
    facility_type: str = ""
    category: str = ""
    tier: int = 0
    economy: str = ""
    market_economy: str = ""
    construction_tonnage: int = 0
    point_cost_mode: str = "fixed"
    requires_tier_2: int = 0
    requires_tier_3: int = 0
    provides_tier_2: int = 0
    provides_tier_3: int = 0
    confidence: str = "unverified"
    construction_started: bool = False

    @classmethod
    def from_reference(cls, facility: FacilityRef, reason: str) -> "FacilityData":
        return cls(
            role=facility.display_name,
            reason=reason or facility.notes or facility.point_summary,
            preferred_site=facility.site_type,
            facility_id=facility.id,
            facility_type=facility.facility_type,
            category=facility.category,
            tier=facility.tier,
            economy=facility.economy,
            market_economy=facility.market_economy,
            construction_tonnage=facility.construction_tonnage,
            point_cost_mode=facility.point_cost_mode,
            requires_tier_2=facility.requires_tier_2,
            requires_tier_3=facility.requires_tier_3,
            provides_tier_2=facility.provides_tier_2,
            provides_tier_3=facility.provides_tier_3,
            confidence=facility.confidence,
        )

    @property
    def point_summary(self) -> str:
        if self.point_cost_mode == "t2_port":
            prefix = "requires escalating T2 port cost (3, 5, 7, …)"
            return f"{prefix}, provides +{self.provides_tier_3} T3" if self.provides_tier_3 else prefix
        if self.point_cost_mode == "t3_port":
            return "requires escalating T3 port cost (6, 12, 18, …)"
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


@dataclass
class PlanData:
    primary_goal: str = "Balanced Colony"
    secondary_goal: str = "None"
    plan_scope: str = "Continue System Build-Out"
    phase: str = "Unknown"
    primary_port_complete: bool = False
    primary_port_name: str = "Primary Port"
    primary_port_location: str = "Not selected"
    current_build: str = "Not selected"
    current_location: str = "Not selected"
    previous_current_build: str = ""
    previous_current_location: str = ""
    concurrent_limit: int = 5
    sites: list[SiteData] = field(default_factory=list)
    facilities: list[FacilityData] = field(default_factory=list)
    materials_by_build: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    ship_capacity_tons: int = 1168
    point_balance_calibrated: bool = False
    point_adjust_tier_2: int = 0
    point_adjust_tier_3: int = 0
    point_calibration_tier_2: int = 0
    point_calibration_tier_3: int = 0


class ConstructionPanel(QWidget):
    """Editable construction plan contained within the existing fixed-size UI."""

    current_build_changed = pyqtSignal(str, str)
    system_lock_changed = pyqtSignal(str, bool)
    carrier_empty_baseline_requested = pyqtSignal(object)

    def __init__(self, settings: QSettings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings = settings
        self.system_locked = self.settings.value("construction/system_locked", False, type=bool)
        self.locked_system_name = str(self.settings.value("construction/locked_system_name", "") or "")
        self.system_name = self.locked_system_name if self.system_locked and self.locked_system_name else "Unknown system"
        self.current_system_name = self.system_name
        self.plan = PlanData()
        self.editing = False
        self.live_depot: Optional[dict[str, Any]] = None
        self.live_depot_resources: list[MaterialData] = []
        self.ship_inventory: dict[str, int] = {}
        self.ship_inventory_known = False
        self.carrier_inventory: dict[str, int] = {}
        self.carrier_inventory_known = False
        self.carrier_known_commodities: set[str] = set()
        self.market_sources: dict[str, str] = {}
        self.active_focus: dict[str, Any] = self._load_active_focus()
        self._rendering_materials = False

        # Construction mode receives several filesystem/journal notifications for
        # a single in-game action.  Keep the live planner in memory and coalesce
        # persistence instead of forcing synchronous settings I/O on every event.
        self._settings_sync_timer = QTimer(self)
        self._settings_sync_timer.setSingleShot(True)
        self._settings_sync_timer.setInterval(250)
        self._settings_sync_timer.timeout.connect(self.settings.sync)
        self._system_replan_timer = QTimer(self)
        self._system_replan_timer.setSingleShot(True)
        self._system_replan_timer.setInterval(90)
        self._system_replan_timer.timeout.connect(self._apply_system_data_replan)
        self._last_saved_plan_key = ""
        self._last_saved_plan_payload = ""
        self._last_system_data_signature: tuple[Any, ...] | None = None

        self._load_plan()
        self._build_ui()
        self._apply_plan()

    def _key(self) -> str:
        safe = self.system_name.lower().replace("/", "_")
        return f"construction/plans/{safe}"

    def _load_plan(self) -> None:
        raw = self.settings.value(self._key(), "")
        if not raw:
            self.plan = PlanData()
            self._last_saved_plan_key = self._key()
            self._last_saved_plan_payload = ""
            return
        self._last_saved_plan_key = self._key()
        self._last_saved_plan_payload = str(raw)
        try:
            data = json.loads(str(raw))
            sites = [SiteData(**row) for row in data.pop("sites", [])]
            facilities = [FacilityData(**row) for row in data.pop("facilities", [])]
            allowed = {k: data[k] for k in PlanData.__dataclass_fields__ if k in data}
            self.plan = PlanData(**allowed)
            self.plan.sites = sites
            self.plan.facilities = facilities
            changed = self._clean_saved_site_facilities()
            changed = self._refresh_plan_facility_metadata() or changed
            if changed:
                self._save_plan()
        except (ValueError, TypeError):
            self.plan = PlanData()

    def _schedule_settings_sync(self) -> None:
        # QSettings.setValue updates the in-process value immediately.  The
        # expensive disk flush is delayed briefly so a burst of journal events
        # results in one sync instead of dozens on the GUI thread.
        self._settings_sync_timer.start()

    def _save_plan(self) -> None:
        key = self._key()
        payload = json.dumps(asdict(self.plan), sort_keys=True)
        if key == self._last_saved_plan_key and payload == self._last_saved_plan_payload:
            return
        self.settings.setValue(key, payload)
        self._last_saved_plan_key = key
        self._last_saved_plan_payload = payload
        self._schedule_settings_sync()

    def _load_active_focus(self) -> dict[str, Any]:
        raw = self.settings.value("construction/active_focus", "")
        if not raw:
            return {}
        try:
            data = json.loads(str(raw))
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_active_focus_record(self, facility: FacilityData, materials: Optional[list[MaterialData]] = None) -> None:
        if not facility or not facility.role or facility.role == "Not selected":
            return
        if materials is None:
            materials = self._stored_materials_for(facility)
        record = {
            "system_name": self.system_name,
            "plan_key": self._key(),
            "build": facility.role,
            "location": facility.location,
            "facility_id": facility.facility_id,
            "facility_type": facility.facility_type,
            "category": facility.category,
            "tier": facility.tier,
            "economy": facility.economy,
            "market_economy": facility.market_economy,
            "construction_tonnage": facility.construction_tonnage,
            "point_cost_mode": facility.point_cost_mode,
            "preferred_site": facility.preferred_site,
            "construction_started": bool(facility.construction_started),
            "reason": facility.reason,
            "confidence": facility.confidence,
            "material_key": self._material_key_for(facility),
            "ship_capacity_tons": int(self.plan.ship_capacity_tons or 1),
            "materials": [self._material_dict(row) for row in materials],
        }
        if record == self.active_focus:
            return
        self.active_focus = record
        self.settings.setValue("construction/active_focus", json.dumps(record, sort_keys=True))
        self._schedule_settings_sync()

    def _active_focus_facility(self) -> Optional[FacilityData]:
        if not self.active_focus:
            return None
        build = str(self.active_focus.get("build", "")).strip()
        if not build or build == "Not selected":
            return None
        return FacilityData(
            role=build,
            reason=str(self.active_focus.get("reason", "Pinned focus build from another system")),
            preferred_site=str(self.active_focus.get("preferred_site", "surface")),
            location=str(self.active_focus.get("location", "Not selected")),
            status="Building now",
            facility_id=str(self.active_focus.get("facility_id", "")),
            facility_type=str(self.active_focus.get("facility_type", "")),
            category=str(self.active_focus.get("category", "")),
            tier=self._int_cell(self.active_focus.get("tier", 0)),
            economy=str(self.active_focus.get("economy", "")),
            market_economy=str(self.active_focus.get("market_economy", "")),
            construction_tonnage=self._int_cell(self.active_focus.get("construction_tonnage", 0)),
            point_cost_mode=str(self.active_focus.get("point_cost_mode", "fixed") or "fixed"),
            construction_started=bool(self.active_focus.get("construction_started", False)),
            confidence=str(self.active_focus.get("confidence", "active_focus")),
        )

    def display_system_name(self) -> str:
        """System whose construction plan is displayed by every construction tab."""
        if self.system_locked and self.locked_system_name:
            return self.locked_system_name
        return self.system_name or "Unknown system"

    def live_system_name(self) -> str:
        """The commander's current journal system, even while the plan is locked."""
        return self.current_system_name or "Unknown system"

    def focus_system_name(self) -> str:
        """System that owns the pinned focus build."""
        active_system = str(self.active_focus.get("system_name", "") or "").strip()
        if active_system:
            return active_system
        return self.display_system_name()

    def system_lock_state(self) -> tuple[str, bool]:
        return self.display_system_name(), bool(self.system_locked)

    def _save_system_lock(self) -> None:
        self.settings.setValue("construction/system_locked", bool(self.system_locked))
        self.settings.setValue("construction/locked_system_name", self.locked_system_name)
        self._schedule_settings_sync()

    def _emit_system_lock_changed(self) -> None:
        self.system_lock_changed.emit(self.display_system_name(), bool(self.system_locked))

    def set_system_locked(self, locked: bool, current_system: Optional[str] = None) -> None:
        current_system = (current_system or "").strip() or self.current_system_name or "Unknown system"

        if locked:
            # Lock the plan currently displayed, not whichever shopping system the
            # commander may have jumped to since opening Construction mode.
            lock_target = self.system_name if self.system_name not in ("", "Unknown system") else current_system
            self.system_locked = True
            self.locked_system_name = lock_target
            self.set_system(lock_target, force=True)
        else:
            # Unlocking intentionally follows the live journal system again.
            self.system_locked = False
            self.locked_system_name = ""
            self.set_system(current_system, force=True)

        self._save_system_lock()
        self._emit_system_lock_changed()
        self._apply_plan()

    def toggle_system_lock(self, current_system: Optional[str] = None) -> None:
        self.set_system_locked(not self.system_locked, current_system)

    def set_system(self, system_name: str, *, force: bool = False) -> bool:
        system_name = system_name or "Unknown system"
        if self.system_locked and not force and self.locked_system_name and system_name != self.locked_system_name:
            return False
        if system_name == self.system_name:
            return True
        self.system_name = system_name
        self._last_system_data_signature = None
        if self.system_locked:
            self.locked_system_name = system_name
        self.active_focus = self._load_active_focus()
        self._load_plan()
        self._apply_plan()
        self._emit_system_lock_changed()
        return True

    @staticmethod
    def _body_sort_key(name: str, body_id: int = 999999) -> tuple[Any, ...]:
        """Sort like the Elite system map instead of raw BodyID order.

        Expected examples:
          A, A 1, A 2, A 2 a, AB 1, B, B 1

        Body names include the system name, which can itself contain numbers and
        letters.  We therefore read only the trailing body designation.
        """
        tokens = name.strip().split()
        designation: list[str] = []
        valid_token = re.compile(r"^(?:[A-Z]{1,3}|[a-z]{1,3}|\d+)$")
        for index in range(len(tokens)):
            suffix = tokens[index:]
            if suffix and all(valid_token.match(token) for token in suffix):
                designation = suffix
                break
        if not designation:
            return (999, body_id if body_id is not None else 999999, name.lower())

        star_token = ""
        body_number = -1
        moon_tokens: list[Any] = []

        first = designation[0]
        pos = 0
        if first.isalpha():
            star_token = first.upper()
            pos = 1

        if pos < len(designation) and designation[pos].isdigit():
            body_number = int(designation[pos])
            pos += 1

        for token in designation[pos:]:
            if token.isdigit():
                moon_tokens.append((0, int(token)))
            else:
                moon_tokens.append((1, token.upper()))

        # A-group first, AB outliers after all A bodies, then B-group, etc.
        if star_token == "":
            star_order = -1
        elif star_token == "A":
            star_order = 0
        elif star_token == "AB":
            star_order = 1
        elif len(star_token) == 1 and star_token.isalpha():
            star_order = 2 + (ord(star_token) - ord("B"))
        else:
            star_order = 99

        is_star = body_number == -1 and not moon_tokens
        star_vs_children = 0 if is_star else 1
        return (
            star_order,
            star_vs_children,
            body_number if body_number >= 0 else -1,
            tuple(moon_tokens),
            body_id if body_id is not None else 999999,
            name.lower(),
        )

    @staticmethod
    def _estimate_surface_slots(body: Any) -> int:
        """Conservative estimate from the samples supplied by the user.

        The value is explicitly marked Estimated and never treated as confirmed.
        """
        if not bool(getattr(body, "landable", False)):
            return 0
        radius_m = getattr(body, "radius_m", None)
        radius_km = (float(radius_m) / 1000.0) if radius_m else 0.0
        atmosphere = str(getattr(body, "atmosphere", "") or "").lower()
        volcanism = str(getattr(body, "volcanism", "") or "").lower()

        if radius_km < 1500:
            base = 1
        elif radius_km < 2300:
            base = 2
        else:
            base = 3

        if volcanism and volcanism not in ("none", "no volcanism"):
            base += 1
        if "thin" in atmosphere:
            base += 2
        return min(6, max(0, base))

    @staticmethod
    def _system_data_signature(system_name: str, bodies: dict[str, Any]) -> tuple[Any, ...]:
        """Cheap fingerprint of body data that can affect colony planning.

        Journal/Cargo/Market writes can all emit UI refreshes even when the
        system map has not changed.  Deep planning must not be regenerated for
        those unrelated events.
        """

        rows: list[tuple[Any, ...]] = []
        for name, body in (bodies or {}).items():
            parents: list[tuple[str, str]] = []
            for parent in getattr(body, "parents", []) or []:
                if not isinstance(parent, dict):
                    continue
                for kind, value in parent.items():
                    parents.append((str(kind), str(value)))
            radius_m = getattr(body, "radius_m", None)
            mass_em = getattr(body, "mass_em", None)
            distance_ls = getattr(body, "distance_ls", None)
            rows.append((
                str(name),
                str(getattr(body, "kind", "Unknown") or "Unknown"),
                str(getattr(body, "subtype", "") or ""),
                bool(getattr(body, "landable", False)),
                getattr(body, "body_id", None),
                round(float(radius_m), 3) if radius_m is not None else None,
                round(float(mass_em), 8) if mass_em is not None else None,
                str(getattr(body, "atmosphere", "") or ""),
                str(getattr(body, "volcanism", "") or ""),
                round(float(distance_ls), 5) if distance_ls is not None else None,
                tuple(parents),
            ))
        rows.sort(key=lambda row: row[0].casefold())
        return (str(system_name or "Unknown system"), tuple(rows))

    def set_system_data(self, system_name: str, bodies: dict[str, Any]) -> None:
        """Apply system-map changes without replanning on every journal event."""
        self.current_system_name = system_name or "Unknown system"
        if not self.set_system(system_name):
            # System Status Lock is active and the commander has jumped away.
            # Keep the planning tabs pinned to the locked colony system.
            return

        signature = self._system_data_signature(self.system_name, bodies)
        if signature == self._last_system_data_signature:
            return
        self._last_system_data_signature = signature

        known = {site.body: site for site in self.plan.sites}
        id_to_name = {
            int(getattr(body, "body_id")): name
            for name, body in bodies.items()
            if getattr(body, "body_id", None) is not None
        }
        changed = False
        for name, body in sorted(
            bodies.items(),
            key=lambda item: self._body_sort_key(
                item[0], getattr(item[1], "body_id", 999999) or 999999
            ),
        ):
            kind = str(getattr(body, "kind", "Unknown") or "Unknown")
            subtype = str(getattr(body, "subtype", "") or "")
            body_type = subtype if subtype not in ("", "?") else kind
            landable = bool(getattr(body, "landable", False))
            body_id = getattr(body, "body_id", 999999) or 999999
            radius_m = getattr(body, "radius_m", None)
            radius_km = (float(radius_m) / 1000.0) if radius_m else None
            mass_em = getattr(body, "mass_em", None)
            atmosphere = str(getattr(body, "atmosphere", "") or "")
            volcanism = str(getattr(body, "volcanism", "") or "")
            distance_ls = getattr(body, "distance_ls", None)
            parent_body = ""
            for parent in reversed(getattr(body, "parents", []) or []):
                if not isinstance(parent, dict):
                    continue
                parent_id = next(iter(parent.values()), None)
                try:
                    parent_name = id_to_name.get(int(parent_id))
                except (TypeError, ValueError):
                    parent_name = None
                if parent_name and parent_name != name:
                    parent_body = parent_name
                    break

            if name in known:
                site = known[name]
                old_metadata = (
                    site.body_type, site.landable, site.body_id, site.radius_km,
                    site.mass_em, site.atmosphere, site.volcanism,
                    site.parent_body, site.distance_ls,
                )
                new_metadata = (
                    body_type, landable, body_id, radius_km, mass_em, atmosphere,
                    volcanism, parent_body, distance_ls,
                )
                if old_metadata != new_metadata:
                    site.body_type = body_type
                    site.landable = landable
                    site.body_id = body_id
                    site.radius_km = radius_km
                    site.mass_em = mass_em
                    site.atmosphere = atmosphere
                    site.volcanism = volcanism
                    site.parent_body = parent_body
                    site.distance_ls = distance_ls
                    changed = True
                continue

            estimated_surface = self._estimate_surface_slots(body)
            confidence = "Estimated from body data" if landable else "Journal body"
            self.plan.sites.append(
                SiteData(
                    body=name,
                    body_type=body_type,
                    landable=landable,
                    surface_total=estimated_surface,
                    confidence=confidence,
                    body_id=body_id,
                    mass_em=mass_em,
                    radius_km=radius_km,
                    atmosphere=atmosphere,
                    volcanism=volcanism,
                    parent_body=parent_body,
                    distance_ls=distance_ls,
                )
            )
            changed = True

        self.plan.sites.sort(key=lambda site: self._body_sort_key(site.body, site.body_id))
        if changed:
            self._save_plan()

        # FSS can discover several bodies in a burst.  Coalesce those changes so
        # a twenty-body scan produces one deep-plan rebuild instead of twenty.
        self._system_replan_timer.start()

    def _apply_system_data_replan(self) -> None:
        self._regenerate_facilities()
        # _render_queue also refreshes Sites/Materials, so paint once.
        self._render_queue()

    def set_construction_depots(self, depots: dict[str, dict]) -> None:
        """Use live journal depot resources for the Materials tab.

        The in-game ColonisationConstructionDepot event is the authority for
        Required/Delivered amounts after a construction site exists. The last
        focused build is also pinned globally, so the material list stays visible
        while hauling from another system.
        """
        candidates: list[dict[str, Any]] = []
        for depot in (depots or {}).values():
            if not isinstance(depot, dict):
                continue
            depot_system = depot.get("system")
            if depot_system and str(depot_system) != self.system_name:
                continue
            candidates.append(depot)

        if not candidates:
            # Do not wipe the pinned/focus material list when the commander jumps
            # away to buy cargo. A new depot event will replace it when observed.
            return

        candidates.sort(key=lambda row: str(row.get("timestamp") or ""), reverse=True)
        depot = candidates[0]

        facility = self._focus_facility()
        started_now = False
        if facility is not None and facility in self.plan.facilities:
            if facility.status == "Building now" and not facility.construction_started:
                # Selecting a Focus in Observatory is only planning intent.  A
                # live ColonisationConstructionDepot event is evidence that Elite
                # has actually created the construction site and therefore spent
                # its construction-point cost.
                facility.construction_started = True
                started_now = True
        saved_rows = self._stored_materials_for(facility, include_live=False)
        saved_sources = {
            commodity_key(row.commodity): row.source
            for row in saved_rows
            if commodity_key(row.commodity)
            and row.source
            and not self._is_placeholder_source(row.source)
        }
        for saved in self.active_focus.get("materials", []) or []:
            if not isinstance(saved, dict):
                continue
            key = commodity_key(saved.get("commodity", ""))
            if not key:
                continue
            source = str(saved.get("source", ""))
            if source and not self._is_placeholder_source(source):
                saved_sources[key] = source

        resources: list[MaterialData] = []
        for row in depot.get("resources", []) or []:
            if not isinstance(row, dict):
                continue
            commodity = str(row.get("commodity", "")).strip()
            if not commodity:
                continue
            key = commodity_key(commodity)
            resources.append(MaterialData(
                commodity=commodity,
                required=self._int_cell(row.get("required", 0)),
                delivered=self._int_cell(row.get("delivered", 0)),
                ship=0,
                carrier=0,
                source=saved_sources.get(key, ""),
            ))

        previous_key = self.live_depot.get("market_id") if isinstance(self.live_depot, dict) else None
        next_key = depot.get("market_id")
        previous_signature = [
            (row.commodity, row.required, row.delivered, row.carrier)
            for row in self.live_depot_resources
        ]
        next_signature = [
            (row.commodity, row.required, row.delivered, row.carrier)
            for row in resources
        ]
        depot_changed = previous_key != next_key or previous_signature != next_signature
        self.live_depot = depot
        self.live_depot_resources = resources

        # The monitor calls this on every construction-mode refresh.  Persist and
        # repaint only when Elite actually changed the depot snapshot (or when the
        # first depot event proves that construction started).
        if facility is not None and resources and (depot_changed or started_now):
            key = self._material_key_for(facility)
            self.plan.materials_by_build[key] = [self._material_dict(row) for row in resources]
            self._save_plan()
            self._save_active_focus_record(facility, resources)

        if started_now:
            self._save_plan()
            self._render_queue()
            self._update_overview_status()

        if depot_changed:
            self._render_materials()

    def set_logistics_data(
        self,
        ship_inventory: dict[str, int],
        ship_inventory_known: bool,
        carrier_inventory: dict[str, int],
        carrier_inventory_known: bool,
        carrier_known_commodities: set[str],
        market_sources: dict[str, str],
    ) -> None:
        """Apply live ship cargo, tracked carrier cargo, and learned market sources."""
        next_ship = {
            commodity_key(name): max(0, self._int_cell(count))
            for name, count in (ship_inventory or {}).items()
            if commodity_key(name)
        }
        next_inventory = {
            commodity_key(name): max(0, self._int_cell(count))
            for name, count in (carrier_inventory or {}).items()
            if commodity_key(name)
        }
        next_known_commodities = {
            commodity_key(name) if name != "*" else "*"
            for name in (carrier_known_commodities or set())
            if name == "*" or commodity_key(name)
        }
        next_sources = {
            commodity_key(name): str(location).strip()
            for name, location in (market_sources or {}).items()
            if commodity_key(name) and str(location).strip()
        }
        next_known = bool(carrier_inventory_known)
        next_ship_known = bool(ship_inventory_known)

        if (
            next_ship == self.ship_inventory
            and next_ship_known == self.ship_inventory_known
            and next_inventory == self.carrier_inventory
            and next_known_commodities == self.carrier_known_commodities
            and next_sources == self.market_sources
            and next_known == self.carrier_inventory_known
        ):
            return

        self.ship_inventory = next_ship
        self.ship_inventory_known = next_ship_known
        self.carrier_inventory = next_inventory
        self.carrier_known_commodities = next_known_commodities
        self.market_sources = next_sources
        self.carrier_inventory_known = next_known
        self._render_materials()

    def set_current_build(self, facility: str, location: str) -> None:
        self.plan.current_build = facility or "Not selected"
        self.plan.current_location = location or "Not selected"
        self._save_plan()
        self._apply_plan()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        top = QHBoxLayout()
        self.title = QLabel("Construction")
        self.title.setObjectName("tableTitle")
        top.addWidget(self.title)
        top.addStretch()
        self.lock_label = QLabel("Plan fields locked")
        self.lock_label.setObjectName("constructionLock")
        self.edit_button = QPushButton("Edit Plan")
        self.edit_button.setObjectName("constructionEditButton")
        self.cancel_button = QPushButton("Cancel")
        self.save_button = QPushButton("Save Changes")
        self.cancel_button.hide()
        self.save_button.hide()
        top.addWidget(self.lock_label)
        top.addWidget(self.edit_button)
        top.addWidget(self.cancel_button)
        top.addWidget(self.save_button)
        outer.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("constructionTabs")
        self.tabs.addTab(self._build_overview_tab(), "Overview")
        self.tabs.addTab(self._build_sites_tab(), "Sites")
        self.tabs.addTab(self._build_queue_tab(), "Build Queue")
        self.tabs.addTab(self._build_materials_tab(), "Materials")
        outer.addWidget(self.tabs, stretch=1)

        self.edit_button.clicked.connect(lambda: self.set_editing(True))
        self.cancel_button.clicked.connect(self.cancel_edits)
        self.save_button.clicked.connect(self.save_edits)
        self.primary_combo.currentTextChanged.connect(self._preview_queue)
        self.secondary_combo.currentTextChanged.connect(self._preview_queue)
        self.plan_scope_combo.currentTextChanged.connect(self._preview_queue)

    def _box(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("constructionBox")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        heading = QLabel(title)
        heading.setObjectName("constructionHeading")
        layout.addWidget(heading)
        return frame, layout

    def _build_overview_tab(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setSpacing(8)

        # The Overview answers four player questions: which colony plan is open,
        # what is active, what should be built next, and what should be hauled now.
        purpose, p = self._box("Build System")
        self.overview_build_system_value = QLabel("Unknown system")
        self.overview_build_system_value.setObjectName("constructionBigValue")
        self.overview_system_state_value = QLabel("Following current system")
        self.overview_system_state_value.setObjectName("constructionMuted")

        # Locked mode is intentionally compact.  The normal Overview is a status
        # dashboard, not a settings form; the full dropdowns only appear while
        # Edit Plan is active so the card remains usable in a non-maximised window.
        self.overview_goal_summary = QLabel("")
        self.overview_goal_summary.setObjectName("constructionGoalSummary")
        self.overview_goal_summary.setWordWrap(True)
        self.overview_scope_summary = QLabel("")
        self.overview_scope_summary.setObjectName("constructionMuted")
        self.overview_scope_summary.setWordWrap(True)
        self.overview_workflow_hint = QLabel(
            "Daily workflow: Build Queue → Track NEXT Build → Materials. "
            "Use Edit Plan only to change goals, slot capacity, or existing facilities."
        )
        self.overview_workflow_hint.setObjectName("constructionWorkflowHint")
        self.overview_workflow_hint.setWordWrap(True)
        self.overview_edit_button = QPushButton("Edit Plan")
        self.overview_edit_button.setObjectName("constructionPrimaryAction")
        self.overview_edit_button.clicked.connect(lambda: self.set_editing(True))

        self.primary_combo = QComboBox()
        self.primary_combo.addItems(PRIMARY_GOALS)
        self.primary_goal_status = QLabel("Not started")
        self.primary_goal_status.setObjectName("constructionGoalStatus")
        self.secondary_combo = QComboBox()
        self.secondary_combo.addItems(SECONDARY_GOALS)
        self.secondary_goal_status = QLabel("Not selected")
        self.secondary_goal_status.setObjectName("constructionGoalStatus")
        self.plan_scope_combo = QComboBox()
        self.plan_scope_combo.addItems(PLAN_SCOPES)
        self.plan_phase_status = QLabel("Selected goals")
        self.plan_phase_status.setObjectName("constructionPhaseStatus")
        self.phase_edit = QLineEdit()
        self.phase_edit.hide()

        p.addWidget(self.overview_build_system_value)
        p.addWidget(self.overview_system_state_value)
        p.addWidget(self.overview_goal_summary)
        p.addWidget(self.overview_scope_summary)
        p.addWidget(self.overview_workflow_hint)
        p.addWidget(self.overview_edit_button)

        self.goal_editor = QWidget()
        goal_grid = QGridLayout(self.goal_editor)
        goal_grid.setContentsMargins(0, 2, 0, 0)
        goal_grid.setHorizontalSpacing(8)
        goal_grid.setVerticalSpacing(3)
        self.primary_goal_label = QLabel("Primary")
        self.secondary_goal_label = QLabel("Secondary")
        self.plan_scope_label = QLabel("Scope")
        goal_grid.addWidget(self.primary_goal_label, 0, 0)
        goal_grid.addWidget(self.primary_combo, 0, 1)
        goal_grid.addWidget(self.primary_goal_status, 0, 2)
        goal_grid.addWidget(self.secondary_goal_label, 1, 0)
        goal_grid.addWidget(self.secondary_combo, 1, 1)
        goal_grid.addWidget(self.secondary_goal_status, 1, 2)
        goal_grid.addWidget(self.plan_scope_label, 2, 0)
        goal_grid.addWidget(self.plan_scope_combo, 2, 1)
        goal_grid.addWidget(self.plan_phase_status, 2, 2)
        self.plan_edit_hint = QLabel(
            "Choose the two goals and scope. Existing colony? Add completed facilities on the Sites tab. "
            "You normally do not need Advanced setup."
        )
        self.plan_edit_hint.setObjectName("constructionWorkflowHint")
        self.plan_edit_hint.setWordWrap(True)
        goal_grid.addWidget(self.plan_edit_hint, 3, 0, 1, 3)
        goal_grid.setColumnStretch(1, 1)
        p.addWidget(self.goal_editor)

        self.advanced_setup_button = QPushButton("Advanced setup ▸")
        self.advanced_setup_button.setCheckable(True)
        self.advanced_setup_button.setObjectName("constructionSecondaryAction")
        self.advanced_setup_button.setToolTip(
            "Show primary-port corrections and manual T2/T3 calibration. Most plans do not need these controls."
        )
        self.advanced_setup_button.toggled.connect(self._set_advanced_setup_visible)
        p.addWidget(self.advanced_setup_button)

        # Existing-colony details are setup data, not daily hauling information.
        # Keep them available only while Edit Plan is active.
        self.colony_setup_editor = QWidget()
        colony_layout = QGridLayout(self.colony_setup_editor)
        colony_layout.setContentsMargins(0, 4, 0, 0)
        colony_layout.setHorizontalSpacing(8)
        colony_layout.setVerticalSpacing(3)
        self.primary_port_check = QCheckBox("Primary port complete")
        self.primary_port_name_edit = QLineEdit()
        self.primary_port_location_edit = QLineEdit()
        colony_layout.addWidget(self.primary_port_check, 0, 0, 1, 3)
        colony_layout.addWidget(QLabel("Primary port"), 1, 0)
        colony_layout.addWidget(self.primary_port_name_edit, 1, 1, 1, 2)
        colony_layout.addWidget(QLabel("Location"), 2, 0)
        colony_layout.addWidget(self.primary_port_location_edit, 2, 1, 1, 2)

        self.point_calibration_check = QCheckBox("Use in-game construction-point calibration")
        self.point_calibration_check.setToolTip(
            "Calibrate Observatory to the T2/T3 balance shown by Elite. "
            "The saved difference is then carried forward while Observatory applies later known costs/rewards."
        )
        self.point_t2_spin = QSpinBox()
        self.point_t2_spin.setRange(0, 999)
        self.point_t3_spin = QSpinBox()
        self.point_t3_spin.setRange(0, 999)
        colony_layout.addWidget(self.point_calibration_check, 3, 0, 1, 3)
        colony_layout.addWidget(QLabel("Game T2"), 4, 0)
        colony_layout.addWidget(self.point_t2_spin, 4, 1)
        colony_layout.addWidget(QLabel("Game T3"), 4, 2)
        colony_layout.addWidget(self.point_t3_spin, 4, 3)
        self.point_calibration_note = QLabel("")
        self.point_calibration_note.setObjectName("constructionMuted")
        self.point_calibration_note.setWordWrap(True)
        colony_layout.addWidget(self.point_calibration_note, 5, 0, 1, 4)
        p.addWidget(self.colony_setup_editor)
        self.colony_setup_editor.hide()
        p.addStretch()

        current, c = self._box("Active Job")
        self.current_build_value = QLabel("Not selected")
        self.current_build_value.setObjectName("constructionBigValue")
        self.current_build_value.setWordWrap(True)
        self.current_focus_system_value = QLabel("Build system: not selected")
        self.current_focus_system_value.setObjectName("constructionMuted")
        self.current_location_value = QLabel("Not selected")
        self.current_location_value.setWordWrap(True)
        c.addWidget(self.current_build_value)
        c.addWidget(self.current_focus_system_value)
        c.addWidget(QLabel("Location"))
        c.addWidget(self.current_location_value)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        c.addWidget(QLabel("Material progress"))
        c.addWidget(self.progress)
        self.undo_focus_button = QPushButton("Undo Build Selection")
        self.undo_focus_button.setToolTip("Restore the previously tracked build if this one was selected by mistake.")
        self.undo_focus_button.clicked.connect(self.undo_focus_change)
        c.addWidget(self.undo_focus_button)
        c.addStretch()

        next_box, n = self._box("Next Recommended Build")
        self.next_build_value = QLabel("No recommendation yet")
        self.next_build_value.setObjectName("constructionBigValue")
        self.next_build_value.setWordWrap(True)
        self.next_location_value = QLabel("Enter body slot counts on Sites")
        self.next_location_value.setWordWrap(True)
        self.next_reason_value = QLabel("")
        self.next_reason_value.setWordWrap(True)
        n.addWidget(self.next_build_value)
        n.addWidget(QLabel("Recommended location"))
        n.addWidget(self.next_location_value)
        n.addWidget(QLabel("Why"))
        n.addWidget(self.next_reason_value)
        self.set_next_current_button = QPushButton("Track NEXT Build")
        self.set_next_current_button.setToolTip("Track the recommended build for materials. This does not start construction in Elite.")
        self.set_next_current_button.clicked.connect(self.set_recommendation_as_current)
        n.addWidget(self.set_next_current_button)
        n.addStretch()

        action, a = self._box("Next Action")
        self.next_action_title = QLabel("Track the next build")
        self.next_action_title.setObjectName("constructionBigValue")
        self.next_action_title.setWordWrap(True)
        self.next_action_detail = QLabel("Track the recommended build to begin material monitoring. Elite still controls construction.")
        self.next_action_detail.setWordWrap(True)
        self.next_action_source = QLabel("Paste Location")
        self.next_action_source.setObjectName("materialSourcePill")
        self.next_action_source.setWordWrap(True)
        a.addWidget(self.next_action_title)
        a.addWidget(self.next_action_detail)
        a.addWidget(QLabel("Material source"))
        a.addWidget(self.next_action_source)
        action_buttons = QHBoxLayout()
        self.open_materials_button = QPushButton("Open Materials")
        self.open_materials_button.clicked.connect(lambda: self.set_view_name("Materials"))
        self.copy_next_source_button = QPushButton("Copy Source")
        self.copy_next_source_button.clicked.connect(self.copy_next_action_source)
        action_buttons.addWidget(self.open_materials_button)
        action_buttons.addWidget(self.copy_next_source_button)
        a.addLayout(action_buttons)
        a.addStretch()

        self.overview_grid = grid
        self.overview_next_box = next_box
        self.overview_action_box = action
        grid.addWidget(purpose, 0, 0)
        grid.addWidget(current, 0, 1)
        grid.addWidget(next_box, 1, 0)
        grid.addWidget(action, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        return page

    def _build_sites_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)

        summary = QHBoxLayout()
        self.site_summary = QLabel("Sites are calculated from the rows below.")
        self.site_summary.setObjectName("constructionNotice")
        # Retained in saved plans for compatibility, but hidden because v3.0.8
        # exposed this control even though it does not affect planning.
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 20)
        self.concurrent_spin.hide()
        summary.addWidget(self.site_summary, stretch=1)
        layout.addLayout(summary)

        self.sites_help = QLabel(
            "Daily view: ✓ built, ⚒ building, → next, • planned. "
            "During Edit Plan, correct used/total slots or add facilities that already existed before Observatory."
        )
        self.sites_help.setObjectName("constructionWorkflowHint")
        self.sites_help.setWordWrap(True)
        layout.addWidget(self.sites_help)

        self.sites_edit_actions = QWidget()
        sites_actions = QHBoxLayout(self.sites_edit_actions)
        sites_actions.setContentsMargins(0, 0, 0, 0)
        self.add_existing_facility_button = QPushButton("Add Existing Facility…")
        self.add_existing_facility_button.setObjectName("constructionPrimaryAction")
        self.add_existing_facility_button.setToolTip(
            "Select a body row, then choose a facility already completed in this system. No exact typing required."
        )
        self.add_existing_facility_button.clicked.connect(self.add_existing_facility_to_selected_site)
        sites_actions.addWidget(self.add_existing_facility_button)
        self.sites_edit_note = QLabel("Select a body first. You can still edit the Builds column manually if needed.")
        self.sites_edit_note.setObjectName("constructionMuted")
        sites_actions.addWidget(self.sites_edit_note, stretch=1)
        self.sites_edit_actions.hide()
        layout.addWidget(self.sites_edit_actions)

        self.sites_next = QLabel("Next build: enter or confirm site totals")
        self.sites_next.setObjectName("constructionNextBuild")
        self.sites_next.setWordWrap(True)
        layout.addWidget(self.sites_next)

        self.sites_table = QTableWidget(0, 7)
        self.sites_table.setHorizontalHeaderLabels([
            "Body / location",
            "Type",
            "Landable",
            "Orbital used/total",
            "Surface used/total",
            "Builds on this body",
            "Confidence",
        ])
        header = self.sites_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.sites_table.verticalHeader().setVisible(False)
        self.sites_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.sites_table.setSortingEnabled(True)
        self.sites_table.horizontalHeader().setSortIndicatorShown(True)
        self.sites_table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.copy_cell_action = QAction("Copy Cell", self.sites_table)
        self.copy_row_action = QAction("Copy Row", self.sites_table)
        self.copy_cell_action.triggered.connect(self.copy_selected_site_cell)
        self.copy_row_action.triggered.connect(self.copy_selected_site_row)
        self.sites_table.addAction(self.copy_cell_action)
        self.sites_table.addAction(self.copy_row_action)
        layout.addWidget(self.sites_table)
        return page

    def copy_selected_site_cell(self) -> None:
        item = self.sites_table.currentItem()
        if item is not None:
            QApplication.clipboard().setText(item.text())

    def copy_selected_site_row(self) -> None:
        row = self.sites_table.currentRow()
        if row < 0:
            return
        values: list[str] = []
        for col in range(self.sites_table.columnCount()):
            item = self.sites_table.item(row, col)
            values.append(item.text() if item else "")
        QApplication.clipboard().setText("\t".join(values))

    def _build_queue_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)

        self.queue_notice = QLabel("Suggested build order for the selected Build System.")
        self.queue_notice.setWordWrap(True)
        self.queue_notice.setObjectName("constructionNotice")
        layout.addWidget(self.queue_notice)

        self.queue_table = QTableWidget(0, 8)
        self.queue_table.setHorizontalHeaderLabels([
            "Order", "Recommended build", "Where to build", "Site", "Points", "Reason", "Status", "Action"
        ])
        # Keep every queue column user-resizable.  Stretch mode made the header
        # handles effectively fixed, which was especially painful for the long
        # facility names and prerequisite explanations.
        queue_header = self.queue_table.horizontalHeader()
        queue_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        queue_header.setMinimumSectionSize(55)
        for column, width in enumerate((60, 320, 170, 80, 190, 360, 105, 105)):
            queue_header.resizeSection(column, width)
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.queue_table)

        actions = QHBoxLayout()
        self.queue_next_button = QPushButton("Track NEXT Build")
        self.queue_next_button.setObjectName("constructionPrimaryAction")
        self.queue_next_button.setToolTip(
            "Track the planner's NEXT build for materials. This does not start construction in Elite."
        )
        self.queue_focus_button = QPushButton("Track Selected")
        self.queue_complete_button = QPushButton("Mark Complete (manual)")
        self.queue_complete_button.setToolTip(
            "Fallback only: use this if Elite/journal completion was not detected automatically."
        )
        self.queue_skip_button = QPushButton("Skip Selected")
        self.queue_next_button.clicked.connect(self.set_recommendation_as_current)
        self.queue_focus_button.clicked.connect(self.set_selected_queue_as_current)
        self.queue_complete_button.clicked.connect(self.mark_selected_queue_complete)
        self.queue_skip_button.clicked.connect(self.skip_selected_queue_item)
        actions.addWidget(self.queue_next_button)
        actions.addWidget(self.queue_focus_button)
        actions.addWidget(self.queue_complete_button)
        actions.addWidget(self.queue_skip_button)
        actions.addStretch()
        layout.addLayout(actions)
        return page

    def _build_materials_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.materials_context = QLabel("No build is being tracked")
        self.materials_context.setObjectName("constructionNextBuild")
        self.materials_context.setWordWrap(True)
        layout.addWidget(self.materials_context)

        self.next_haul_card = QFrame()
        self.next_haul_card.setObjectName("nextHaulCard")
        next_haul_layout = QHBoxLayout(self.next_haul_card)
        next_haul_layout.setContentsMargins(12, 8, 12, 8)
        next_haul_layout.setSpacing(10)
        next_haul_text = QVBoxLayout()
        next_haul_text.setSpacing(2)
        self.next_haul_title = QLabel("NEXT HAUL: track a build")
        self.next_haul_title.setObjectName("nextHaulTitle")
        self.next_haul_detail = QLabel("")
        self.next_haul_detail.setObjectName("constructionMuted")
        self.next_haul_source = QLabel("Paste Location")
        self.next_haul_source.setObjectName("materialSourcePill")
        self.next_haul_source.setWordWrap(True)
        next_haul_text.addWidget(self.next_haul_title)
        next_haul_text.addWidget(self.next_haul_detail)
        next_haul_layout.addLayout(next_haul_text, stretch=1)
        next_haul_layout.addWidget(self.next_haul_source, stretch=1)
        self.copy_haul_source_button = QPushButton("Copy Source")
        self.copy_haul_source_button.clicked.connect(self.copy_next_action_source)
        next_haul_layout.addWidget(self.copy_haul_source_button)
        layout.addWidget(self.next_haul_card)

        toolbar = QHBoxLayout()
        self.logistics_status_label = QLabel("Ship cargo: update pending • Carrier cargo: update pending")
        self.logistics_status_label.setObjectName("constructionMuted")
        self.set_carrier_empty_button = QPushButton("Set Carrier Empty")
        self.set_carrier_empty_button.setToolTip(
            "Use after the carrier has zero of every commodity listed for this construction build."
        )
        self.set_carrier_empty_button.clicked.connect(self.mark_tracked_carrier_empty)
        self.ship_capacity_spin = QSpinBox()
        self.ship_capacity_spin.setRange(1, 50000)
        self.ship_capacity_spin.setSuffix(" t")
        self.add_material_button = QPushButton("Add Material Row")
        self.remove_material_button = QPushButton("Remove Selected")
        self.add_material_button.clicked.connect(self.add_material_row)
        self.remove_material_button.clicked.connect(self.remove_selected_material_row)
        self.ship_capacity_spin.valueChanged.connect(lambda _value: self._render_materials())
        toolbar.addWidget(self.logistics_status_label)
        toolbar.addWidget(self.set_carrier_empty_button)
        toolbar.addStretch()
        toolbar.addWidget(QLabel("Ship capacity"))
        toolbar.addWidget(self.ship_capacity_spin)
        toolbar.addWidget(self.add_material_button)
        toolbar.addWidget(self.remove_material_button)
        layout.addLayout(toolbar)

        self.materials_table = QTableWidget(0, 8)
        self.materials_table.setHorizontalHeaderLabels([
            "Commodity", "Required", "Delivered", "Ship", "Carrier", "Still needed", "Ship trips", "Material Source"
        ])
        header = self.materials_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSortIndicatorShown(True)
        self.materials_table.verticalHeader().setVisible(False)
        self.materials_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.materials_table.itemChanged.connect(self.on_material_item_changed)
        self.materials_table.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.copy_material_source_action = QAction("Copy Material Source", self.materials_table)
        self.copy_material_cell_action = QAction("Copy Cell", self.materials_table)
        self.copy_material_source_action.triggered.connect(self.copy_selected_material_source)
        self.copy_material_cell_action.triggered.connect(self.copy_selected_material_cell)
        self.materials_table.addAction(self.copy_material_source_action)
        self.materials_table.addAction(self.copy_material_cell_action)
        self._materials_sort_initialized = False
        layout.addWidget(self.materials_table)
        return page

    @staticmethod
    def _int_cell(text: str) -> int:
        try:
            return max(0, int(str(text).replace(",", "").strip()))
        except (TypeError, ValueError):
            return 0

    def _focus_facility(self) -> Optional[FacilityData]:
        local_focus = next((facility for facility in self.plan.facilities if facility.status == "Building now"), None)
        if local_focus is not None:
            return local_focus
        return self._active_focus_facility()

    def _focus_or_next_facility(self) -> Optional[FacilityData]:
        focus = self._focus_facility()
        if focus is not None:
            return focus
        return self._next_buildable_facility()

    def _is_active_focus_facility(self, facility: Optional[FacilityData]) -> bool:
        if facility is None or not self.active_focus:
            return False
        return (
            facility.role == str(self.active_focus.get("build", ""))
            and facility.location == str(self.active_focus.get("location", ""))
        )

    def _material_key_for(self, facility: Optional[FacilityData] = None) -> str:
        facility = facility or self._focus_facility()
        if facility is None:
            return "manual"
        return facility.facility_id or facility.role

    @staticmethod
    def _material_dict(row: MaterialData) -> dict[str, Any]:
        # Ship/carrier quantities are live logistics state, not plan data. Do not
        # persist them in the construction plan where they could become stale.
        return {
            "commodity": row.commodity,
            "required": int(row.required),
            "delivered": int(row.delivered),
            "source": row.source,
        }

    def _seed_materials_for(self, facility: Optional[FacilityData]) -> list[MaterialData]:
        if facility is None or not facility.facility_id:
            return []
        return [
            MaterialData(commodity=item.commodity, required=item.required)
            for item in CATALOG.material_requirements(facility.facility_id)
        ]

    def _rows_from_dicts(self, stored: list[dict[str, Any]]) -> list[MaterialData]:
        rows: list[MaterialData] = []
        for row in stored:
            if not isinstance(row, dict):
                continue
            commodity = str(row.get("commodity", "")).strip()
            if not commodity:
                continue
            rows.append(MaterialData(
                commodity=commodity,
                required=self._int_cell(row.get("required", 0)),
                delivered=self._int_cell(row.get("delivered", 0)),
                ship=0,
                carrier=0,
                source=str(row.get("source", "")),
            ))
        return rows

    def _merge_material_sources(
        self,
        authority_rows: list[MaterialData],
        saved_rows: list[MaterialData],
    ) -> list[MaterialData]:
        saved = {
            commodity_key(row.commodity): row
            for row in saved_rows
            if commodity_key(row.commodity)
        }
        merged: list[MaterialData] = []
        for row in authority_rows:
            key = commodity_key(row.commodity)
            previous = saved.get(key)
            source = row.source
            if previous is not None and previous.source and not self._is_placeholder_source(previous.source):
                source = previous.source
            merged.append(MaterialData(
                commodity=row.commodity,
                required=row.required,
                delivered=row.delivered,
                ship=0,
                carrier=0,
                source=source,
            ))
        return merged

    def _carrier_key_known(self, key: str) -> bool:
        return bool(
            self.carrier_inventory_known
            and key
            and ("*" in self.carrier_known_commodities or key in self.carrier_known_commodities)
        )

    def _apply_logistics_overlays(self, rows: list[MaterialData]) -> list[MaterialData]:
        overlaid: list[MaterialData] = []
        for row in rows:
            key = commodity_key(row.commodity)
            ship = max(0, int(self.ship_inventory.get(key, 0) or 0)) if self.ship_inventory_known else 0
            carrier = (
                max(0, int(self.carrier_inventory.get(key, 0) or 0))
                if self._carrier_key_known(key)
                else 0
            )

            source = row.source
            if key and self._is_placeholder_source(source):
                source = self.market_sources.get(key, source)

            overlaid.append(MaterialData(
                commodity=row.commodity,
                required=row.required,
                delivered=row.delivered,
                ship=ship,
                carrier=carrier,
                source=source,
            ))
        return overlaid

    def _stored_materials_for(
        self,
        facility: Optional[FacilityData],
        *,
        include_live: bool = True,
    ) -> list[MaterialData]:
        key = self._material_key_for(facility)
        stored_rows = self._rows_from_dicts(self.plan.materials_by_build.get(key, []))

        active_rows: list[MaterialData] = []
        if self._is_active_focus_facility(facility):
            active_rows = self._rows_from_dicts(self.active_focus.get("materials", []) or [])

        saved_rows = stored_rows or active_rows

        if include_live and self.live_depot_resources and (
            not self.live_depot
            or not self.live_depot.get("system")
            or str(self.live_depot.get("system")) == self.system_name
            or self._is_active_focus_facility(facility)
        ):
            rows = self._merge_material_sources(self.live_depot_resources, saved_rows)
        elif saved_rows:
            rows = saved_rows
        else:
            rows = self._seed_materials_for(facility)

        return self._apply_logistics_overlays(rows)

    def _collect_material_edits(self) -> list[MaterialData]:
        rows: list[MaterialData] = []
        for row in range(self.materials_table.rowCount()):
            def text(col: int) -> str:
                item = self.materials_table.item(row, col)
                return item.text().strip() if item else ""
            commodity = text(0)
            if not commodity or commodity.startswith("No material list"):
                continue
            rows.append(MaterialData(
                commodity=commodity,
                required=self._int_cell(text(1)),
                delivered=self._int_cell(text(2)),
                ship=0,
                carrier=0,
                source="" if text(7) == "Paste Location" else text(7),
            ))
        return rows

    def _store_material_edits(self) -> None:
        facility = self._focus_facility()
        rows = self._collect_material_edits()
        if self._is_active_focus_facility(facility):
            self.active_focus["materials"] = [self._material_dict(row) for row in rows]
            self.active_focus["ship_capacity_tons"] = int(self.plan.ship_capacity_tons or 1)
            self.settings.setValue("construction/active_focus", json.dumps(self.active_focus, sort_keys=True))
            self._schedule_settings_sync()
            return
        key = self._material_key_for(facility)
        self.plan.materials_by_build[key] = [
            self._material_dict(row) for row in rows
        ]
        if facility is not None and facility.status == "Building now":
            self._save_active_focus_record(facility, rows)

    def add_material_row(self) -> None:
        row = self.materials_table.rowCount()
        self.materials_table.insertRow(row)
        for col, value in enumerate(["", "0", "0", "0", "0", "0", "0", "Paste Location"]):
            item = QTableWidgetItem(value)
            if col in (3, 4, 5, 6):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.materials_table.setItem(row, col, item)

    def remove_selected_material_row(self) -> None:
        row = self.materials_table.currentRow()
        if row >= 0:
            self.materials_table.removeRow(row)
            self._store_material_edits()
            self._save_plan()


    @staticmethod
    def _is_placeholder_source(text: str) -> bool:
        return str(text or "").strip() in ("", "Paste Location", "Journal depot", "Waiting for journal depot or JSON")

    def on_material_item_changed(self, item: QTableWidgetItem) -> None:
        if self._rendering_materials or item is None:
            return
        # The source/location field is intentionally editable while the plan is
        # locked.  Save it immediately so a pasted station is not lost.
        if item.column() == 7:
            self._store_material_edits()
            self._save_plan()
            self._render_materials()

    def copy_selected_material_cell(self) -> None:
        item = self.materials_table.currentItem()
        if item is not None:
            QApplication.clipboard().setText(item.text())

    def copy_selected_material_source(self) -> None:
        row = self.materials_table.currentRow()
        if row < 0:
            return
        item = self.materials_table.item(row, 7)
        if item is None:
            return
        text = item.text().strip()
        if not self._is_placeholder_source(text):
            QApplication.clipboard().setText(text)

    def mark_tracked_carrier_empty(self) -> None:
        facility = self._focus_facility()
        rows = self._stored_materials_for(facility) if facility is not None else []
        commodities = [row.commodity for row in rows if commodity_key(row.commodity)]
        if not commodities:
            QMessageBox.information(
                self,
                "Carrier baseline",
                "Load the construction material list first.",
            )
            return

        answer = QMessageBox.question(
            self,
            "Set carrier construction cargo to zero?",
            "Use this only when your carrier has ZERO of every commodity listed "
            "in this Materials table. Other cargo such as Tritium is fine.\n\n"
            "Observatory will save zero as the baseline and then track future "
            "CargoTransfer events automatically.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.carrier_empty_baseline_requested.emit(commodities)

    def _next_action_data(self) -> tuple[str, str, str, int]:
        """Return title, detail, source and progress for the active focus build."""
        facility = self._focus_facility()
        if facility is None:
            next_facility = self._next_buildable_facility()
            if next_facility is not None:
                return (
                    "Track the next build",
                    f"Track NEXT ({next_facility.role}) to begin material monitoring.",
                    "Paste Location",
                    0,
                )
            blocked = next((row for row in self.plan.facilities if row.status == "Queued"), None)
            if blocked is not None:
                return (
                    "No buildable next facility",
                    f"{blocked.role}: {self._facility_block_reason(blocked)}",
                    "No source needed",
                    0,
                )
            return (
                "Plan complete",
                "No queued construction remains. Change Plan Scope or goals if you want more development.",
                "No source needed",
                0,
            )

        rows = self._stored_materials_for(facility)
        required_total = sum(max(0, row.required) for row in rows)
        delivered_total = sum(min(max(0, row.delivered), max(0, row.required)) for row in rows)
        progress = int((delivered_total * 100) / required_total) if required_total else 0
        needed = sorted(
            (row for row in rows if row.still_needed > 0),
            key=lambda row: row.still_needed,
            reverse=True,
        )

        if needed:
            material = needed[0]
            capacity = max(1, int(self.plan.ship_capacity_tons or 1))
            trips = (material.still_needed + capacity - 1) // capacity
            source = material.source.strip() if material.source else "Paste Location"
            if self._is_placeholder_source(source):
                source = "Paste Location"
            return (
                f"Deliver {material.commodity}",
                f"{material.still_needed:,} t left • {trips} ship trip{'s' if trips != 1 else ''}",
                source,
                progress,
            )

        if rows:
            remaining_delivery = sum(
                max(0, int(row.required) - int(row.delivered)) for row in rows
            )
            if remaining_delivery > 0:
                stocked = sum(max(0, int(row.ship) + int(row.carrier)) for row in rows)
                return (
                    "Deliver stocked materials",
                    f"{remaining_delivery:,} t still needs depot delivery • "
                    f"{stocked:,} t currently on ship/carrier",
                    "No source needed",
                    progress,
                )
            return (
                "Material delivery complete",
                "Return to the construction site and verify the build completes.",
                "No source needed",
                100,
            )

        return (
            "Load depot requirements",
            "Visit the focused construction site so Elite writes its depot material list.",
            "Paste Location",
            0,
        )

    def _update_overview_status(self) -> None:
        if not hasattr(self, "overview_build_system_value"):
            return

        build_system = self.display_system_name()
        current_system = self.live_system_name()
        self.overview_build_system_value.setText(build_system)
        if self.system_locked:
            state_text = "🔒 Locked to build system"
        elif current_system == build_system:
            state_text = "🔓 Following current system"
        else:
            state_text = f"🔓 Following current system: {current_system}"
        self.overview_system_state_value.setText(state_text)

        effective_primary, effective_secondary = self._effective_goal_names()
        effective_scope = self._effective_plan_scope()
        primary_progress, secondary_progress = self.selected_goal_progress(
            effective_primary, effective_secondary
        )
        primary_text = self._progress_label(primary_progress)
        secondary_text = self._progress_label(secondary_progress)
        phase_text = self.current_development_phase(
            effective_primary, effective_secondary, effective_scope
        )
        self.primary_goal_status.setText(primary_text)
        self.secondary_goal_status.setText(secondary_text)
        self.plan_phase_status.setText(phase_text)
        self.overview_goal_summary.setText(
            f"Primary: {effective_primary} — {primary_text}\n"
            f"Secondary: {effective_secondary} — {secondary_text}"
        )
        self.overview_scope_summary.setText(
            f"Scope: {effective_scope}  •  Phase: {phase_text}"
        )

        build_name, build_location = self.focus_build_display()
        self.current_build_value.setText(build_name)
        self.current_location_value.setText(build_location)
        self.current_focus_system_value.setText(f"Build system: {self.focus_system_name()}")

        action_title, action_detail, source, progress = self._next_action_data()
        self.progress.setValue(progress)
        self.next_action_title.setText(action_title)
        self.next_action_detail.setText(action_detail)
        self.next_action_source.setText(source)
        source_available = not self._is_placeholder_source(source) and source != "No source needed"
        source_missing = not source_available and source != "No source needed"
        self.next_action_source.setProperty("missing", "true" if source_missing else "false")
        self.next_action_source.style().unpolish(self.next_action_source)
        self.next_action_source.style().polish(self.next_action_source)
        self.copy_next_source_button.setEnabled(source_available)
        if hasattr(self, "next_haul_title"):
            self.next_haul_title.setText(f"NEXT HAUL: {action_title}")
            self.next_haul_detail.setText(action_detail)
            self.next_haul_source.setText(source)
            self.next_haul_source.setProperty("missing", "true" if source_missing else "false")
            self.next_haul_source.style().unpolish(self.next_haul_source)
            self.next_haul_source.style().polish(self.next_haul_source)
            self.copy_haul_source_button.setEnabled(source_available)

    def copy_next_action_source(self) -> None:
        _title, _detail, source, _progress = self._next_action_data()
        if not self._is_placeholder_source(source) and source != "No source needed":
            QApplication.clipboard().setText(source)

    def _render_materials(self) -> None:
        if not hasattr(self, "materials_table"):
            return
        facility = self._focus_facility()
        self.plan.ship_capacity_tons = (
            self.ship_capacity_spin.value()
            if hasattr(self, "ship_capacity_spin")
            else self.plan.ship_capacity_tons
        )
        capacity = max(1, int(self.plan.ship_capacity_tons or 1))
        rows = self._stored_materials_for(facility) if facility is not None else []

        if facility is None:
            self.materials_context.setText(
                f"No build is being tracked • Build system: {self.display_system_name()}"
            )
        else:
            self.materials_context.setText(
                f"BUILDING: {facility.role}  •  {facility.location}  •  "
                f"Build system: {self.focus_system_name()}"
            )

        tracked_keys = {commodity_key(row.commodity) for row in rows if commodity_key(row.commodity)}
        carrier_ready = bool(tracked_keys) and all(self._carrier_key_known(key) for key in tracked_keys)
        ship_status = "synced" if self.ship_inventory_known else "UPDATE PENDING"
        carrier_status = "tracking" if carrier_ready else "UPDATE PENDING"
        if hasattr(self, "logistics_status_label"):
            self.logistics_status_label.setText(
                f"Ship cargo: {ship_status} • Carrier cargo: {carrier_status}"
            )
            self.logistics_status_label.setToolTip(
                "Ship cargo comes from Cargo.json. Carrier cargo is maintained from "
                "a zero baseline plus CargoTransfer journal events."
            )
        if hasattr(self, "set_carrier_empty_button"):
            self.set_carrier_empty_button.setEnabled(bool(tracked_keys))

        self._rendering_materials = True
        if self._materials_sort_initialized:
            sort_section = self.materials_table.horizontalHeader().sortIndicatorSection()
            sort_order = self.materials_table.horizontalHeader().sortIndicatorOrder()
        else:
            sort_section = 5
            sort_order = Qt.SortOrder.DescendingOrder

        self.materials_table.setSortingEnabled(False)
        try:
            if not rows:
                self.materials_table.setRowCount(1)
                values = [
                    "No material data yet", "", "", "", "", "", "", "Paste Location"
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if col == 7:
                        item.setBackground(QColor("#493710"))
                        item.setForeground(QColor("#F59E0B"))
                    else:
                        item.setForeground(QColor("#E4B65E"))
                    self.materials_table.setItem(0, col, item)
            else:
                self.materials_table.setRowCount(len(rows))
                for row, material in enumerate(rows):
                    key = commodity_key(material.commodity)
                    carrier_known = self._carrier_key_known(key)
                    left = material.still_needed
                    trips = (left + capacity - 1) // capacity if left else 0
                    source = material.source.strip() if material.source else "Paste Location"
                    ship_text = f"{material.ship:,}" if self.ship_inventory_known else "Update pending"
                    carrier_text = f"{material.carrier:,}" if carrier_known else "Update pending"
                    values = [
                        material.commodity,
                        f"{material.required:,}",
                        f"{material.delivered:,}",
                        ship_text,
                        carrier_text,
                        f"{left:,}",
                        str(trips),
                        source,
                    ]
                    for col, value in enumerate(values):
                        if col in (1, 2, 3, 4, 5, 6):
                            sort_value = self._int_cell(value) if value != "Update pending" else -1
                            item = NumericSortItem(value, sort_value)
                        else:
                            item = QTableWidgetItem(value)

                        editable = self.editing and col in (0, 1, 2, 7)
                        if not self.editing and col == 7:
                            editable = True
                        if col in (3, 4, 5, 6):
                            editable = False
                        if not editable:
                            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                        if left > 0 and col in (0, 5, 6):
                            item.setForeground(QColor("#ffb000"))
                        elif left == 0:
                            item.setForeground(QColor("#6F7B85"))
                            item.setBackground(QColor("#101A22"))

                        if col == 4 and not carrier_known:
                            item.setForeground(QColor("#F59E0B"))
                        if col == 3 and not self.ship_inventory_known:
                            item.setForeground(QColor("#F59E0B"))

                        if col == 7:
                            if self._is_placeholder_source(value):
                                item.setText("Paste Location")
                                item.setBackground(QColor("#493710"))
                                item.setForeground(QColor("#F59E0B"))
                            else:
                                item.setBackground(QColor("#5B21B6"))
                                item.setForeground(QColor("#FFFFFF"))
                        self.materials_table.setItem(row, col, item)
        finally:
            self._rendering_materials = False
            self.materials_table.setSortingEnabled(True)
            if 0 <= sort_section < self.materials_table.columnCount():
                self.materials_table.sortItems(sort_section, sort_order)
            self._materials_sort_initialized = True

        self._update_overview_status()

    @staticmethod
    def _parse_usage(text: str) -> tuple[int, int]:
        try:
            used_text, total_text = text.strip().split("/", 1)
            used = max(0, int(used_text))
            total = max(0, int(total_text))
            return min(used, total), total
        except (ValueError, AttributeError):
            return 0, 0

    @staticmethod
    def _usage_text(used: int, total: int) -> str:
        return f"{used}/{total}"

    def _collect_site_edits(self) -> list[SiteData]:
        rows: list[SiteData] = []
        for row in range(self.sites_table.rowCount()):
            def text(col: int) -> str:
                item = self.sites_table.item(row, col)
                return item.text().strip() if item else ""

            orbital_used, orbital_total = self._parse_usage(text(3))
            surface_used, surface_total = self._parse_usage(text(4))
            body_name = text(0) or f"Location {row + 1}"
            previous = next((site for site in self.plan.sites if site.body == body_name), None)
            rows.append(SiteData(
                body=body_name,
                body_type=text(1) or "Unknown",
                landable=text(2).lower() in ("yes", "true", "1"),
                orbital_used=orbital_used,
                orbital_total=orbital_total,
                surface_used=surface_used,
                surface_total=surface_total,
                facility=self._physical_site_facility_text(text(5)),
                status="Available",
                confidence="User confirmed" if self.editing else (text(6) or "User entered"),
                body_id=previous.body_id if previous else 999999,
                mass_em=previous.mass_em if previous else None,
                radius_km=previous.radius_km if previous else None,
                atmosphere=previous.atmosphere if previous else "",
                volcanism=previous.volcanism if previous else "",
                parent_body=previous.parent_body if previous else "",
                distance_ls=previous.distance_ls if previous else None,
            ))
        return rows

    def set_editing(self, enabled: bool) -> None:
        self.editing = enabled
        self.lock_label.setText("✎ EDITING PLAN" if enabled else "Plan fields locked")
        self.lock_label.setProperty("editing", "true" if enabled else "false")
        self.lock_label.style().unpolish(self.lock_label)
        self.lock_label.style().polish(self.lock_label)
        self.edit_button.setVisible(not enabled)
        self.cancel_button.setVisible(enabled)
        self.save_button.setVisible(enabled)
        for widget in (
            self.primary_combo,
            self.secondary_combo,
            self.plan_scope_combo,
            self.phase_edit,
            self.primary_port_check,
            self.primary_port_name_edit,
            self.primary_port_location_edit,
            self.concurrent_spin,
            self.point_calibration_check,
            self.point_t2_spin,
            self.point_t3_spin,
        ):
            widget.setEnabled(enabled)
        self.sites_table.setEditTriggers(
            QTableWidget.EditTrigger.AllEditTriggers if enabled
            else QTableWidget.EditTrigger.NoEditTriggers
        )
        # Confidence is troubleshooting data. Keep the normal player workflow
        # focused on slots and builds, but reveal it during Edit Plan.
        self.sites_table.setColumnHidden(6, not enabled)
        if hasattr(self, "goal_editor"):
            self.goal_editor.setVisible(enabled)
        if hasattr(self, "advanced_setup_button"):
            self.advanced_setup_button.setVisible(enabled)
            self.advanced_setup_button.blockSignals(True)
            self.advanced_setup_button.setChecked(False)
            self.advanced_setup_button.blockSignals(False)
            self.advanced_setup_button.setText("Advanced setup ▸")
        if hasattr(self, "colony_setup_editor"):
            self.colony_setup_editor.setVisible(False)
        if hasattr(self, "overview_goal_summary"):
            self.overview_goal_summary.setVisible(not enabled)
            self.overview_scope_summary.setVisible(not enabled)
        if hasattr(self, "overview_workflow_hint"):
            self.overview_workflow_hint.setVisible(not enabled)
        if hasattr(self, "overview_edit_button"):
            self.overview_edit_button.setVisible(not enabled)
        if hasattr(self, "sites_edit_actions"):
            self.sites_edit_actions.setVisible(enabled)
        # Editing needs more vertical room than the status dashboard. Hide the
        # lower recommendation/action cards while the plan form is open so the
        # goal, scope, site and calibration controls do not get clipped in a
        # normal (non-maximised) window.
        if hasattr(self, "overview_next_box"):
            self.overview_next_box.setVisible(not enabled)
        if hasattr(self, "overview_action_box"):
            self.overview_action_box.setVisible(not enabled)
        if hasattr(self, "overview_grid"):
            self.overview_grid.setRowStretch(0, 2 if enabled else 1)
            self.overview_grid.setRowStretch(1, 0 if enabled else 1)
        if hasattr(self, "materials_table"):
            # Material Source stays editable even when the plan is locked,
            # because choosing where to buy commodities is an operational action.
            self.materials_table.setEditTriggers(QTableWidget.EditTrigger.AllEditTriggers)
            self._render_materials()
        if hasattr(self, "add_material_button"):
            self.add_material_button.setVisible(enabled)
            self.remove_material_button.setVisible(enabled)
            self.ship_capacity_spin.setEnabled(enabled)

    def _set_advanced_setup_visible(self, visible: bool) -> None:
        if hasattr(self, "advanced_setup_button"):
            self.advanced_setup_button.setText("Advanced setup ▾" if visible else "Advanced setup ▸")
        if hasattr(self, "colony_setup_editor"):
            self.colony_setup_editor.setVisible(bool(visible and self.editing))

    def add_existing_facility_to_selected_site(self) -> None:
        """Guided existing-colony entry without requiring exact facility typing."""

        row = self.sites_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a body", "Select the body that already contains the facility.")
            return
        body_item = self.sites_table.item(row, 0)
        landable_item = self.sites_table.item(row, 2)
        if body_item is None:
            return
        body = body_item.text().strip()
        landable = bool(landable_item and landable_item.text().strip().lower() == "yes")

        choices: list[str] = []
        by_choice: dict[str, FacilityRef] = {}
        for reference in CATALOG.facilities.values():
            if reference.id == "primary_port":
                label = "Orbital/Surface — Primary Port / Genesis"
            else:
                if reference.site_type == "surface" and not landable:
                    continue
                label = f"{reference.site_type.title()} — {reference.display_name}"
            choices.append(label)
            by_choice[label] = reference
        choices.sort(key=str.casefold)
        selected, ok = QInputDialog.getItem(
            self,
            "Add Existing Facility",
            f"Completed facility on {body}:",
            choices,
            0,
            True,
        )
        if not ok or not str(selected).strip():
            return
        selected_text = str(selected).strip()
        reference = by_choice.get(selected_text)
        if reference is None:
            # Editable combo supports fast typing. Resolve either the full label
            # or a facility/layout name the player typed manually.
            candidate = selected_text.split(" — ", 1)[-1].strip()
            reference = CATALOG.facility_from_text(candidate)
        if reference is None:
            QMessageBox.information(
                self,
                "Facility not recognised",
                "Choose a facility from the list, or enter the completed build manually in the Builds column.",
            )
            return
        if reference.site_type == "surface" and not landable:
            QMessageBox.information(self, "Surface facility", f"{reference.display_name} requires a landable body.")
            return

        facility_item = self.sites_table.item(row, 5)
        existing_text = facility_item.text().strip() if facility_item else ""
        physical = self._physical_site_facility_text(existing_text)
        marker_name = "Primary Port" if reference.id == "primary_port" else reference.display_name
        marker = f"✓ {marker_name}"
        existing_fragments = [part.strip() for part in re.split(r"[;\n]+", physical) if part.strip()]
        if any(CATALOG._normalise(marker_name) in CATALOG._normalise(part) for part in existing_fragments):
            QMessageBox.information(self, "Already listed", f"{marker_name} is already listed on {body}.")
            return
        existing_fragments.append(marker)
        self.sites_table.setItem(row, 5, QTableWidgetItem("; ".join(existing_fragments)))

        usage_col = 4 if reference.site_type == "surface" else 3
        usage_item = self.sites_table.item(row, usage_col)
        used, total = self._parse_usage(usage_item.text() if usage_item else "0/0")
        used += 1
        total = max(total, used)
        self.sites_table.setItem(row, usage_col, QTableWidgetItem(self._usage_text(used, total)))

        if reference.id == "primary_port":
            self.primary_port_check.setChecked(True)
            if self.primary_port_name_edit.text().strip() in ("", "Primary Port"):
                self.primary_port_name_edit.setText("Genesis")
            location_kind = "Surface" if reference.site_type == "surface" else "Orbit"
            self.primary_port_location_edit.setText(f"{body} — {location_kind} {used}")

        self.sites_edit_note.setText(f"Added as existing: {marker_name}. Save Changes when finished.")

    def cancel_edits(self) -> None:
        self._apply_plan()
        self.set_editing(False)

    def save_edits(self) -> None:
        old_goal = self.plan.primary_goal
        old_secondary = self.plan.secondary_goal
        old_scope = self.plan.plan_scope
        new_goal = self.primary_combo.currentText()
        new_secondary = self.secondary_combo.currentText()
        new_scope = self.plan_scope_combo.currentText()
        if old_goal != new_goal or old_secondary != new_secondary or old_scope != new_scope:
            answer = QMessageBox.question(
                self,
                "Change system goals?",
                "Changing the goals or plan scope regenerates the recommended build queue. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.plan.primary_goal = new_goal
        self.plan.secondary_goal = new_secondary
        self.plan.plan_scope = new_scope
        self.plan.phase = self.phase_edit.text().strip() or "Unknown"
        self.plan.primary_port_complete = self.primary_port_check.isChecked()
        self.plan.primary_port_name = self.primary_port_name_edit.text().strip() or "Primary Port"
        self.plan.primary_port_location = self.primary_port_location_edit.text().strip() or "Not selected"
        self.plan.concurrent_limit = self.concurrent_spin.value()
        self.plan.ship_capacity_tons = self.ship_capacity_spin.value()
        self._store_material_edits()
        self.plan.sites = self._collect_site_edits()

        # The Sites spreadsheet can mark the primary port directly by typing
        # "Genesis", "Primary Port", or "✓ Genesis" into Builds on this body.
        self._infer_primary_port_from_sites()
        if self.plan.primary_port_complete:
            self._mark_primary_port_on_site()

        self._regenerate_facilities()
        if self.point_calibration_check.isChecked():
            raw_t2, raw_t3, _t2_ports, _t3_ports = self._construction_state_raw()
            target_t2 = self.point_t2_spin.value()
            target_t3 = self.point_t3_spin.value()
            self.plan.point_balance_calibrated = True
            self.plan.point_calibration_tier_2 = target_t2
            self.plan.point_calibration_tier_3 = target_t3
            self.plan.point_adjust_tier_2 = target_t2 - raw_t2
            self.plan.point_adjust_tier_3 = target_t3 - raw_t3
        else:
            self.plan.point_balance_calibrated = False
            self.plan.point_adjust_tier_2 = 0
            self.plan.point_adjust_tier_3 = 0
        self._save_plan()
        self._apply_plan()

    def _mark_primary_port_on_site(self) -> None:
        location_lower = self.plan.primary_port_location.lower()
        for site in self.plan.sites:
            if site.body.lower() in location_lower or location_lower.startswith(site.body.lower()):
                marker = f"✓ {self.plan.primary_port_name}"
                if marker.lower() not in site.facility.lower():
                    site.facility = f"{site.facility}; {marker}".strip("; ")
                if "orbit" in location_lower and site.orbital_total > 0:
                    site.orbital_used = max(1, site.orbital_used)
                elif "surface" in location_lower and site.surface_total > 0:
                    site.surface_used = max(1, site.surface_used)
                site.confidence = "User confirmed"
                return

    def _apply_plan(self) -> None:
        if not hasattr(self, "primary_combo"):
            return
        self.primary_combo.setCurrentText(self.plan.primary_goal)
        self.secondary_combo.setCurrentText(self.plan.secondary_goal)
        self.plan_scope_combo.setCurrentText(self.plan.plan_scope)
        self.phase_edit.setText(self.plan.phase)
        self.primary_port_check.setChecked(self.plan.primary_port_complete)
        self.primary_port_name_edit.setText(self.plan.primary_port_name)
        self.primary_port_location_edit.setText(self.plan.primary_port_location)
        raw_t2, raw_t3, _t2_ports, _t3_ports = self._construction_state_raw()
        current_t2, current_t3, _current_t2_ports, _current_t3_ports = self._construction_state()
        self.point_calibration_check.setChecked(self.plan.point_balance_calibrated)
        self.point_t2_spin.setValue(
            current_t2 if self.plan.point_balance_calibrated else raw_t2
        )
        self.point_t3_spin.setValue(
            current_t3 if self.plan.point_balance_calibrated else raw_t3
        )
        if self.plan.point_balance_calibrated:
            self.point_calibration_note.setText(
                f"Calibration offset: {self.plan.point_adjust_tier_2:+d} T2, "
                f"{self.plan.point_adjust_tier_3:+d} T3. Later known builds still change the balance normally."
            )
        else:
            self.point_calibration_note.setText(
                "Leave calibration off when Observatory matches Elite; enable it only when the in-game T2/T3 counter differs."
            )
        display_build, display_location = self.focus_build_display()
        self.current_build_value.setText(display_build)
        self.current_location_value.setText(display_location)
        self.concurrent_spin.setValue(self.plan.concurrent_limit)
        if hasattr(self, "ship_capacity_spin"):
            self.ship_capacity_spin.setValue(self.plan.ship_capacity_tons or 1168)
        self._render_sites()
        self._render_queue()
        self._render_materials()
        self.set_editing(False)
        self.current_build_changed.emit(display_build, display_location)

    def _preview_queue(self, _text: str) -> None:
        if self.editing:
            self._render_queue(
                self.primary_combo.currentText(),
                self.secondary_combo.currentText(),
                self.plan_scope_combo.currentText(),
            )

    @staticmethod
    def _looks_like_primary_port_marker(text: str) -> bool:
        lowered = text.lower()
        return (
            "primary port" in lowered
            or "genesis" in lowered
            or "starter port" in lowered
        )

    def _infer_primary_port_from_sites(self) -> None:
        """Allow the Sites spreadsheet to be the source of truth.

        If the player types something like "✓ Genesis" or "Primary Port" into
        Builds on this body, the planner marks the primary port complete and
        uses that row as the occupied location.
        """
        if self.plan.primary_port_complete:
            return
        for site in self.plan.sites:
            if not self._looks_like_primary_port_marker(site.facility):
                continue
            self.plan.primary_port_complete = True
            if self.plan.primary_port_name in ("", "Primary Port"):
                match = re.search(r"(?:✓|complete:?)?\s*([^;]+)", site.facility, re.IGNORECASE)
                self.plan.primary_port_name = (match.group(1).strip() if match else "Genesis") or "Genesis"
            if site.orbital_used > 0:
                self.plan.primary_port_location = f"{site.body} — Orbit 1"
            elif site.surface_used > 0:
                self.plan.primary_port_location = f"{site.body} — Surface 1"
            else:
                self.plan.primary_port_location = site.body
            return

    @staticmethod
    def _facility_body_from_location(location: str) -> str:
        return str(location or "").split(" — ", 1)[0].strip()

    def _queue_display_location(self, location: str) -> str:
        """Use compact body text in the queue while preserving full data.

        The Build System is already displayed above the table, so a location
        such as ``Nyeakua GG-D b4-1 A 2 — Surface 2`` can be shown as
        ``A 2 — Surface 2``.  The full location remains available as a tooltip.
        """
        full = str(location or "")
        system = str(self.system_name or "").strip()
        prefix = f"{system} " if system and system != "Unknown system" else ""
        if prefix and full.startswith(prefix):
            return full[len(prefix):]
        return full

    @staticmethod
    def _physical_site_facility_text(text: str) -> str:
        """Return only facility markers that represent physical/completed sites.

        The Sites table overlays planner-only markers (``•`` planned, ``→`` next,
        ``⚒`` building) on top of the editable physical-site text.  v3.0.7/3.0.8
        could accidentally save those overlays back into ``SiteData.facility``
        when Edit Plan was saved.  That made future planning believe every
        recommendation already existed.
        """

        kept: list[str] = []
        for part in re.split(r"[;\n]+", str(text or "")):
            cleaned = part.strip()
            if not cleaned:
                continue
            if cleaned.startswith(("•", "→", "⚒")) or "→" in cleaned or "⚒" in cleaned:
                continue
            kept.append(cleaned)
        return "; ".join(kept)

    def _clean_saved_site_facilities(self) -> bool:
        """Repair persisted planner overlays from v3.0.7/v3.0.8."""

        changed = False
        for site in self.plan.sites:
            cleaned = self._physical_site_facility_text(site.facility)
            if cleaned != site.facility:
                site.facility = cleaned
                changed = True
        return changed

    @staticmethod
    def _site_facility_fragments(text: str) -> list[str]:
        """Split saved physical Sites markers into catalog-resolvable facilities."""

        fragments: list[str] = []
        for part in re.split(r"[;\n]+", str(text or "")):
            cleaned = part.strip()
            if not cleaned:
                continue
            # Never count planner overlays as physical facilities.  This also
            # makes old polluted settings harmless before they are saved again.
            if cleaned.startswith(("•", "→", "⚒")) or "→" in cleaned or "⚒" in cleaned:
                continue
            cleaned = re.sub(r"^[✓\s]+", "", cleaned).strip()
            if cleaned:
                fragments.append(cleaned)
        return fragments

    @staticmethod
    def _descriptor_for_facility_data(facility: FacilityData) -> FacilityDescriptor:
        reference = CATALOG.facility(facility.facility_id) if facility.facility_id else None
        if reference is not None:
            return reference.descriptor
        return FacilityDescriptor(
            facility_type=facility.facility_type,
            category=facility.category,
            economy=facility.economy,
            tier=facility.tier,
            facility_id=facility.facility_id,
        )

    @staticmethod
    def _reference_for_facility_data(facility: FacilityData) -> FacilityRef:
        by_id = CATALOG.facility(facility.facility_id) if facility.facility_id else None
        by_text = CATALOG.facility_from_text(facility.role)

        # Saved plans can survive several catalog revisions.  If an old row's
        # id points at a different layout than the human-readable role now
        # names, trust the role and migrate it to the current catalog entry.
        # This specifically prevents stale embedded T2/T3 values from turning a
        # completed Aerecura into a +1 T2 facility after an upgrade.
        reference = by_id
        if by_text is not None:
            if by_id is None:
                reference = by_text
            else:
                role_norm = CATALOG._normalise(facility.role)
                id_name_norm = CATALOG._normalise(by_id.name)
                text_name_norm = CATALOG._normalise(by_text.name)
                if text_name_norm and text_name_norm in role_norm and id_name_norm not in role_norm:
                    reference = by_text
        if reference is not None:
            return reference
        return FacilityRef(
            id=facility.facility_id or facility.role,
            name=facility.role,
            facility_type=facility.facility_type,
            category=facility.category,
            tier=facility.tier,
            site_type=facility.preferred_site,
            economy=facility.economy,
            market_economy=facility.market_economy,
            construction_tonnage=facility.construction_tonnage,
            point_cost_mode=facility.point_cost_mode,
            requires_tier_2=facility.requires_tier_2,
            requires_tier_3=facility.requires_tier_3,
            provides_tier_2=facility.provides_tier_2,
            provides_tier_3=facility.provides_tier_3,
            confidence=facility.confidence,
            notes=facility.reason,
        )

    def _refresh_plan_facility_metadata(self) -> bool:
        """Migrate saved planner rows onto the current authoritative catalog.

        Construction plans are persistent, while facility rules are now being
        corrected from current in-game/community data.  Refreshing every known
        row prevents old serialized cost/reward fields from corrupting the
        current construction-point balance.  Status/location are preserved.
        """

        changed = False
        for facility in self.plan.facilities:
            reference = self._reference_for_facility_data(facility)
            if reference.id == (facility.facility_id or facility.role) and CATALOG.facility(reference.id) is None:
                continue
            updates = {
                "facility_id": reference.id,
                "facility_type": reference.facility_type,
                "category": reference.category,
                "tier": reference.tier,
                "economy": reference.economy,
                "market_economy": reference.market_economy,
                "preferred_site": reference.site_type,
                "construction_tonnage": reference.construction_tonnage,
                "point_cost_mode": reference.point_cost_mode,
                "requires_tier_2": reference.requires_tier_2,
                "requires_tier_3": reference.requires_tier_3,
                "provides_tier_2": reference.provides_tier_2,
                "provides_tier_3": reference.provides_tier_3,
                "confidence": reference.confidence,
            }
            for key, value in updates.items():
                if getattr(facility, key) != value:
                    setattr(facility, key, value)
                    changed = True
            if facility.facility_id != "primary_port" and reference.display_name != facility.role:
                facility.role = reference.display_name
                changed = True
        return changed

    def _completed_facility_descriptors(self) -> list[FacilityDescriptor]:
        descriptors: list[FacilityDescriptor] = []
        for facility in self.plan.facilities:
            if facility.status == "Complete":
                descriptors.append(self._descriptor_for_facility_data(facility))

        # Sites may contain facilities that were built before Observatory began
        # tracking the plan.  Classify those by structured type/economy so a
        # prerequisite is not tied to one exact layout name.
        for site in self.plan.sites:
            for fragment in self._site_facility_fragments(site.facility):
                descriptor = CATALOG.descriptor_from_text(fragment)
                if descriptor is not None:
                    descriptors.append(descriptor)
        return descriptors

    def _construction_state_raw(self) -> tuple[int, int, int, int]:
        """Reconstruct points from facilities Observatory can positively identify.

        This is the calculated ledger before any user calibration.  Completed
        facilities contribute their net historical cost/reward.  A row merely
        selected as Focus/``Building now`` does *not* spend points until a live
        construction-depot event proves that Elite actually started the build.
        """

        tier_2 = 0
        tier_3 = 0
        t2_ports = 0
        t3_ports = 0
        completed_plan_locations: set[tuple[str, str]] = set()

        for facility in self.plan.facilities:
            if facility.status == "Building now" and not facility.construction_started:
                continue
            if facility.status not in ("Complete", "Building now"):
                continue
            reference = self._reference_for_facility_data(facility)
            cost_t2, cost_t3 = CATALOG.point_cost(
                reference,
                previous_t2_ports=t2_ports,
                previous_t3_ports=t3_ports,
            )
            tier_2 -= cost_t2
            tier_3 -= cost_t3
            if reference.point_cost_mode == "t2_port":
                t2_ports += 1
            elif reference.point_cost_mode == "t3_port":
                t3_ports += 1
            if facility.status == "Complete":
                tier_2 += reference.provides_tier_2
                tier_3 += reference.provides_tier_3
                if reference.id:
                    completed_plan_locations.add(
                        (self._facility_body_from_location(facility.location), reference.id)
                    )

        # Facilities recorded in Sites may pre-date Observatory.  Count only
        # catalog-resolvable completed markers and deduplicate against plan rows.
        for site in self.plan.sites:
            for fragment in self._site_facility_fragments(site.facility):
                reference = CATALOG.facility_from_text(fragment)
                if reference is None:
                    continue
                if (site.body, reference.id) in completed_plan_locations:
                    continue
                cost_t2, cost_t3 = CATALOG.point_cost(
                    reference,
                    previous_t2_ports=t2_ports,
                    previous_t3_ports=t3_ports,
                )
                tier_2 += reference.provides_tier_2 - cost_t2
                tier_3 += reference.provides_tier_3 - cost_t3
                if reference.point_cost_mode == "t2_port":
                    t2_ports += 1
                elif reference.point_cost_mode == "t3_port":
                    t3_ports += 1

        return max(0, tier_2), max(0, tier_3), t2_ports, t3_ports

    def _construction_state(self) -> tuple[int, int, int, int]:
        """Return the current point balance used for NEXT-build decisions.

        Elite does not currently expose the system's live T2/T3 counters in the
        journal events Observatory consumes.  When the calculated historical
        ledger differs from the counter shown in-game, Edit Plan can calibrate
        it once.  Observatory stores the *difference* rather than freezing a
        snapshot, so later known costs/rewards continue moving the balance.
        """

        tier_2, tier_3, t2_ports, t3_ports = self._construction_state_raw()
        if self.plan.point_balance_calibrated:
            tier_2 = max(0, tier_2 + int(self.plan.point_adjust_tier_2 or 0))
            tier_3 = max(0, tier_3 + int(self.plan.point_adjust_tier_3 or 0))
        return tier_2, tier_3, t2_ports, t3_ports

    def _construction_point_balance(self) -> tuple[int, int]:
        tier_2, tier_3, _t2_ports, _t3_ports = self._construction_state()
        return tier_2, tier_3

    def _prerequisite_satisfied(
        self,
        prerequisite: FacilityPrerequisite,
        descriptors: Optional[list[FacilityDescriptor]] = None,
    ) -> bool:
        candidates = descriptors if descriptors is not None else self._completed_facility_descriptors()
        return any(
            CATALOG.descriptor_matches_prerequisite(descriptor, prerequisite)
            for descriptor in candidates
        )

    def _facility_can_build(
        self,
        facility: FacilityData,
        tier_2: int,
        tier_3: int,
        descriptors: list[FacilityDescriptor],
        t2_ports: int = 0,
        t3_ports: int = 0,
    ) -> bool:
        reference = self._reference_for_facility_data(facility)
        cost_t2, cost_t3 = CATALOG.point_cost(
            reference, previous_t2_ports=t2_ports, previous_t3_ports=t3_ports
        )
        if cost_t2 > tier_2 or cost_t3 > tier_3:
            return False
        return all(
            self._prerequisite_satisfied(prerequisite, descriptors)
            for prerequisite in reference.prerequisites
        )

    def _facility_block_reason(self, facility: FacilityData) -> str:
        """Explain why a queued facility cannot be started *right now*.

        This deliberately uses the live/calibrated current point balance rather
        than the future simulated balance used to order the rest of the queue.
        A later row can therefore become NEXT when an earlier goal row is legal
        only after that bridge facility finishes.
        """

        tier_2, tier_3, t2_ports, t3_ports = self._construction_state()
        descriptors = self._completed_facility_descriptors()
        reference = self._reference_for_facility_data(facility)
        short_t2, short_t3 = CATALOG.point_shortfall(
            reference,
            tier_2,
            tier_3,
            previous_t2_ports=t2_ports,
            previous_t3_ports=t3_ports,
        )
        shortages: list[str] = []
        if short_t2:
            shortages.append(f"{short_t2} T2")
        if short_t3:
            shortages.append(f"{short_t3} T3")
        if shortages:
            return (
                f"Needs {' and '.join(shortages)} more construction points "
                f"(current: {tier_2} T2, {tier_3} T3)."
            )

        missing = [
            prerequisite.display_name
            for prerequisite in reference.prerequisites
            if not self._prerequisite_satisfied(prerequisite, descriptors)
        ]
        if missing:
            return f"Missing prerequisite: {', '.join(missing)}."

        if facility.preferred_site == "surface" and not self._location_is_real(facility.location):
            return "No compatible surface slot is currently assigned."
        if facility.preferred_site == "orbital" and not self._location_is_real(facility.location):
            return "No compatible orbital slot is currently assigned."
        return ""

    def _next_buildable_facility(self) -> Optional[FacilityData]:
        """Return the first queued facility Elite should allow us to start now."""

        for facility in self.plan.facilities:
            if facility.status != "Queued":
                continue
            if not self._facility_block_reason(facility):
                return facility
        return None

    def _apply_facility_points(
        self,
        facility: FacilityData,
        tier_2: int,
        tier_3: int,
        t2_ports: int = 0,
        t3_ports: int = 0,
    ) -> tuple[int, int, int, int]:
        reference = self._reference_for_facility_data(facility)
        cost_t2, cost_t3 = CATALOG.point_cost(
            reference, previous_t2_ports=t2_ports, previous_t3_ports=t3_ports
        )
        tier_2 = max(0, tier_2 - cost_t2 + reference.provides_tier_2)
        tier_3 = max(0, tier_3 - cost_t3 + reference.provides_tier_3)
        if reference.point_cost_mode == "t2_port":
            t2_ports += 1
        elif reference.point_cost_mode == "t3_port":
            t3_ports += 1
        return tier_2, tier_3, t2_ports, t3_ports

    def _repair_impossible_building_focus(self) -> bool:
        """Demote stale planner focus rows whose prerequisites do not exist.

        A ``Building now`` row is a player-selected Observatory focus, not proof
        that Elite actually allowed construction to start.  This matters when
        facility rules are corrected after a plan was already saved: an old
        focus such as Tartarus may remain pinned even though the system has no
        completed Extraction settlement.  Elite cannot have legitimately
        started that hub in that state, so return it to the queue and clear the
        stale global focus record.

        Construction-point affordability is intentionally *not* used here.  A
        legitimate in-progress build has already spent its point cost, so its
        current balance can be lower than the amount originally required.
        """

        descriptors = self._completed_facility_descriptors()
        changed = False
        for facility in self.plan.facilities:
            if facility.status != "Building now":
                continue
            reference = self._reference_for_facility_data(facility)
            if not reference.prerequisites:
                continue
            if all(
                self._prerequisite_satisfied(prerequisite, descriptors)
                for prerequisite in reference.prerequisites
            ):
                continue

            facility.status = "Queued"
            if (
                self.plan.current_build == facility.role
                and self.plan.current_location == facility.location
            ):
                self.plan.current_build = "Not selected"
                self.plan.current_location = "Not selected"
            active_focus_id = str(self.active_focus.get("facility_id", "") or "")
            active_focus_system = str(self.active_focus.get("system_name", "") or "")
            if (
                self._is_active_focus_facility(facility)
                or (
                    active_focus_id
                    and active_focus_id == facility.facility_id
                    and (not active_focus_system or active_focus_system == self.system_name)
                )
            ):
                self.active_focus = {}
                self.settings.remove("construction/active_focus")
                self._schedule_settings_sync()
            changed = True
        return changed

    def _simulated_state_before(self, index: int) -> tuple[int, int, int, int, list[FacilityDescriptor]]:
        """Project points/descriptors after buildable rows before ``index`` finish.

        Prerequisite selection must use the state that will exist when the
        dependant is reached, not only the points available this second.  This
        is what lets an early T1 orbital installation generate a T2 point and
        then makes a large +2-T3 settlement the better prerequisite choice.
        """

        tier_2, tier_3, t2_ports, t3_ports = self._construction_state()
        descriptors = self._completed_facility_descriptors()
        for facility in self.plan.facilities:
            if facility.status == "Building now":
                reference = self._reference_for_facility_data(facility)
                if facility.construction_started:
                    # Cost is already reflected in the current balance; only the
                    # completion reward remains in the future simulation.
                    tier_2 += reference.provides_tier_2
                    tier_3 += reference.provides_tier_3
                    descriptors.append(self._descriptor_for_facility_data(facility))
                elif self._facility_can_build(
                    facility, tier_2, tier_3, descriptors, t2_ports, t3_ports
                ):
                    # Focus selected but Elite has not started the site yet.
                    tier_2, tier_3, t2_ports, t3_ports = self._apply_facility_points(
                        facility, tier_2, tier_3, t2_ports, t3_ports
                    )
                    descriptors.append(self._descriptor_for_facility_data(facility))

        for facility in self.plan.facilities[:max(0, index)]:
            if facility.status != "Queued":
                continue
            if not self._facility_can_build(
                facility, tier_2, tier_3, descriptors, t2_ports, t3_ports
            ):
                continue
            tier_2, tier_3, t2_ports, t3_ports = self._apply_facility_points(
                facility, tier_2, tier_3, t2_ports, t3_ports
            )
            descriptors.append(self._descriptor_for_facility_data(facility))
        return tier_2, tier_3, t2_ports, t3_ports, descriptors

    def _ensure_prerequisite_rows(self) -> bool:
        """Insert/move generic prerequisite facilities ahead of dependants.

        Example: Tartarus requires ``Settlement - Extraction``.  The resolver
        searches for *any* matching Settlement/Extraction facility already in
        the plan/system.  If none exists, it picks the best matching facility
        that the current T2/T3 balance can build, rather than hard-coding one
        settlement name.
        """

        changed = False
        # Multiple passes allow a newly inserted prerequisite to have its own
        # prerequisite without turning the resolver into name-specific code.
        for _pass in range(8):
            pass_changed = False
            index = 0
            while index < len(self.plan.facilities):
                facility = self.plan.facilities[index]
                reference = self._reference_for_facility_data(facility)
                if not reference.prerequisites:
                    index += 1
                    continue

                for prerequisite in reference.prerequisites:
                    if self._prerequisite_satisfied(prerequisite):
                        continue

                    matching_index: Optional[int] = None
                    for candidate_index, candidate in enumerate(self.plan.facilities):
                        if candidate is facility or candidate.status == "Skipped":
                            continue
                        descriptor = self._descriptor_for_facility_data(candidate)
                        if CATALOG.descriptor_matches_prerequisite(descriptor, prerequisite):
                            matching_index = candidate_index
                            break

                    if matching_index is not None:
                        if matching_index > index:
                            candidate = self.plan.facilities.pop(matching_index)
                            self.plan.facilities.insert(index, candidate)
                            pass_changed = True
                            changed = True
                            index += 1
                        continue

                    future_t2, future_t3, _future_t2_ports, _future_t3_ports, _future_desc = (
                        self._simulated_state_before(index)
                    )
                    candidate_ref = CATALOG.best_prerequisite_candidate(
                        prerequisite,
                        available_tier_2=future_t2,
                        available_tier_3=future_t3,
                    )
                    if candidate_ref is None:
                        continue

                    candidate = FacilityData.from_reference(
                        candidate_ref,
                        (
                            f"Prerequisite for {facility.role}: requires "
                            f"{prerequisite.display_name}. Any facility matching "
                            "that type/category and economy can satisfy it."
                        ),
                    )
                    self.plan.facilities.insert(index, candidate)
                    pass_changed = True
                    changed = True
                    index += 1

                index += 1

            if not pass_changed:
                break
        return changed

    def _physical_facility_references(self) -> list[FacilityRef]:
        """Known built/in-progress facilities, including pre-Observatory sites.

        Site markers are treated as completed existing facilities.  Complete and
        Building-now queue rows are also physical, but are deduplicated against
        the same exact facility recorded on the same body in Sites.
        """

        refs: list[FacilityRef] = []
        seen: set[tuple[str, str]] = set()
        for facility in self.plan.facilities:
            if facility.status not in ("Complete", "Building now"):
                continue
            reference = self._reference_for_facility_data(facility)
            body = self._facility_body_from_location(facility.location)
            key = (body, reference.id)
            if key in seen:
                continue
            refs.append(reference)
            seen.add(key)
        for site in self.plan.sites:
            for fragment in self._site_facility_fragments(site.facility):
                reference = CATALOG.facility_from_text(fragment)
                if reference is None:
                    continue
                key = (site.body, reference.id)
                if key in seen:
                    continue
                refs.append(reference)
                seen.add(key)
        return refs

    def _existing_functional_counts(self) -> dict[tuple[str, str, int, str, str], int]:
        counts: dict[tuple[str, str, int, str, str], int] = {}
        for reference in self._physical_facility_references():
            if reference.id == "primary_port":
                continue
            signature = CATALOG.functional_signature(reference)
            counts[signature] = counts.get(signature, 0) + 1
        return counts

    def _known_facility_signatures(self) -> set[tuple[str, str, int, str, str]]:
        signatures = {
            CATALOG.functional_signature(reference)
            for reference in self._physical_facility_references()
            if reference.id != "primary_port"
        }
        for facility in self.plan.facilities:
            if facility.status == "Skipped":
                continue
            reference = self._reference_for_facility_data(facility)
            if reference.id != "primary_port":
                signatures.add(CATALOG.functional_signature(reference))
        return signatures

    def _site_type_can_accept_more(self, site_type: str) -> bool:
        # If the player has not entered/confirmed any slot totals yet, do not
        # pretend there is no capacity.  Once totals are known, respect them.
        totals_known = any(
            site.surface_total > 0 or site.orbital_total > 0
            for site in self.plan.sites
        )
        if not totals_known:
            return True
        if site_type == "surface":
            return any(
                site.landable and site.surface_used < site.surface_total
                for site in self.plan.sites
            )
        if site_type == "orbital":
            return any(site.orbital_used < site.orbital_total for site in self.plan.sites)
        return False

    def _best_point_bridge_candidate(
        self,
        remaining: list[FacilityData],
        tier_2: int,
        tier_3: int,
        descriptors: list[FacilityDescriptor],
        t2_ports: int,
        t3_ports: int,
        excluded_signatures: set[tuple[str, str, int, str, str]],
    ) -> FacilityRef | None:
        """Find one mechanically buildable facility that unlocks point progress.

        A goal recipe can legitimately ask for more T2/T3 than its named rows
        generate.  Rather than leaving a blocked facility labelled NEXT, insert
        a bridge facility that is buildable now and produces the missing point
        tier.  Economy alignment with the primary goal is weighted most heavily;
        the secondary goal then breaks otherwise similar choices.
        """

        needed_t2 = 0
        needed_t3 = 0
        for facility in remaining:
            reference = self._reference_for_facility_data(facility)
            if not all(
                self._prerequisite_satisfied(prerequisite, descriptors)
                for prerequisite in reference.prerequisites
            ):
                continue
            cost_t2, cost_t3 = CATALOG.point_cost(
                reference, previous_t2_ports=t2_ports, previous_t3_ports=t3_ports
            )
            needed_t2 = max(0, cost_t2 - tier_2)
            needed_t3 = max(0, cost_t3 - tier_3)
            if needed_t2 or needed_t3:
                break
        if not needed_t2 and not needed_t3:
            return None

        primary_goal, secondary_goal = self._effective_goal_names()
        economy_weights = CATALOG.goal_economy_weights(primary_goal, secondary_goal)

        def buildable(reference: FacilityRef) -> bool:
            if reference.id == "primary_port":
                return False
            if CATALOG.functional_signature(reference) in excluded_signatures:
                return False
            if not self._site_type_can_accept_more(reference.site_type):
                return False
            cost_t2, cost_t3 = CATALOG.point_cost(
                reference, previous_t2_ports=t2_ports, previous_t3_ports=t3_ports
            )
            if cost_t2 > tier_2 or cost_t3 > tier_3:
                return False
            return all(
                self._prerequisite_satisfied(prerequisite, descriptors)
                for prerequisite in reference.prerequisites
            )

        candidates = [
            reference
            for reference in CATALOG.facilities.values()
            if buildable(reference)
            and (reference.provides_tier_2 > 0 or reference.provides_tier_3 > 0)
        ]
        if not candidates:
            return None

        # Prefer the point tier directly blocking the next prerequisite-satisfied
        # goal row.  If no direct provider is currently buildable (for example
        # we need T3 but have no T2 to pay for a T3-producing settlement), a T2
        # generator becomes the bridge to the bridge.
        direct = [
            reference
            for reference in candidates
            if (needed_t2 and reference.provides_tier_2 > 0)
            or (needed_t3 and reference.provides_tier_3 > 0)
        ]
        pool = direct or candidates

        def sort_key(reference: FacilityRef) -> tuple[int, int, int, int, int, int, str]:
            economy = CATALOG._normalise(reference.market_economy or reference.economy)
            affinity = economy_weights.get(economy, 0)
            direct_reward = (
                (reference.provides_tier_2 if needed_t2 else 0)
                + (reference.provides_tier_3 if needed_t3 else 0)
            )
            total_reward = reference.provides_tier_2 + reference.provides_tier_3
            cost_t2, cost_t3 = CATALOG.point_cost(
                reference, previous_t2_ports=t2_ports, previous_t3_ports=t3_ports
            )
            tonnage = reference.construction_tonnage or 10**9
            return (
                -affinity,
                -direct_reward,
                -total_reward,
                cost_t2 + cost_t3,
                tonnage,
                reference.preferred_rank,
                reference.display_name.casefold(),
            )

        return sorted(pool, key=sort_key)[0]

    def _reorder_facilities_for_buildability(self) -> bool:
        """Turn both goal recipes into a dependency/point-feasible build order."""

        original = list(self.plan.facilities)
        completed = [facility for facility in original if facility.status == "Complete"]
        building = [facility for facility in original if facility.status == "Building now"]
        queued = [facility for facility in original if facility.status == "Queued"]
        skipped = [facility for facility in original if facility.status == "Skipped"]
        other = [
            facility
            for facility in original
            if facility.status not in ("Complete", "Building now", "Queued", "Skipped")
        ]

        tier_2, tier_3, t2_ports, t3_ports = self._construction_state()
        descriptors = self._completed_facility_descriptors()
        ordered: list[FacilityData] = completed + building

        # A depot-confirmed active build has already spent its point cost, so only
        # its completion reward remains.  A Focus row with no depot proof is still
        # only planning intent and must be able to pay the full cost in simulation.
        for facility in building:
            reference = self._reference_for_facility_data(facility)
            if facility.construction_started:
                tier_2 += reference.provides_tier_2
                tier_3 += reference.provides_tier_3
                descriptors.append(self._descriptor_for_facility_data(facility))
            elif self._facility_can_build(
                facility, tier_2, tier_3, descriptors, t2_ports, t3_ports
            ):
                tier_2, tier_3, t2_ports, t3_ports = self._apply_facility_points(
                    facility, tier_2, tier_3, t2_ports, t3_ports
                )
                descriptors.append(self._descriptor_for_facility_data(facility))

        remaining = list(queued)
        while remaining:
            choice: Optional[FacilityData] = None
            for facility in remaining:
                if self._facility_can_build(
                    facility, tier_2, tier_3, descriptors, t2_ports, t3_ports
                ):
                    choice = facility
                    break
            if choice is None:
                excluded_signatures = self._known_facility_signatures()
                excluded_signatures.update(
                    CATALOG.functional_signature(self._reference_for_facility_data(facility))
                    for facility in ordered
                    if self._reference_for_facility_data(facility).id != "primary_port"
                )
                bridge_ref = self._best_point_bridge_candidate(
                    remaining,
                    tier_2,
                    tier_3,
                    descriptors,
                    t2_ports,
                    t3_ports,
                    excluded_signatures,
                )
                if bridge_ref is None:
                    ordered.extend(remaining)
                    break
                bridge_primary, bridge_secondary = self._effective_goal_names()
                bridge = FacilityData.from_reference(
                    bridge_ref,
                    (
                        "Construction-point bridge chosen to keep the combined "
                        f"{bridge_primary} / {bridge_secondary} plan buildable."
                    ),
                )
                ordered.append(bridge)
                tier_2, tier_3, t2_ports, t3_ports = self._apply_facility_points(
                    bridge, tier_2, tier_3, t2_ports, t3_ports
                )
                descriptors.append(self._descriptor_for_facility_data(bridge))
                # The bridge now exists in the future simulated system.  Continue
                # until a real goal row becomes buildable or another bridge is needed.
                continue
            ordered.append(choice)
            remaining.remove(choice)
            tier_2, tier_3, t2_ports, t3_ports = self._apply_facility_points(
                choice, tier_2, tier_3, t2_ports, t3_ports
            )
            descriptors.append(self._descriptor_for_facility_data(choice))

        ordered.extend(other)
        ordered.extend(skipped)
        if ordered == original:
            return False
        self.plan.facilities = ordered
        return True

    def _regenerate_facilities(
        self,
        goal: Optional[str] = None,
        secondary_goal: Optional[str] = None,
        plan_scope: Optional[str] = None,
    ) -> None:
        goal = goal or self.plan.primary_goal
        secondary_goal = (
            self.plan.secondary_goal if secondary_goal is None else secondary_goal
        )
        plan_scope = plan_scope or self.plan.plan_scope
        old_by_id = {
            facility.facility_id: facility
            for facility in self.plan.facilities
            if facility.facility_id
        }
        old_by_role = {facility.role: facility for facility in self.plan.facilities}
        generated: list[FacilityData] = []
        existing_counts = self._existing_functional_counts()

        # Scope controls how far Observatory plans, not how many rows it is allowed
        # to return.  Primary-only stops after the primary objective.  The normal
        # dual-goal scope includes both dropdowns.  Continue System Build-Out adds
        # ranked development stages after those objectives are covered.
        effective_secondary = secondary_goal
        if plan_scope == "Primary Goal Only":
            effective_secondary = "None"

        # Primary and secondary objectives are merged before dependency solving.
        # A mechanically equivalent layout already present in the system consumes
        # one requested goal slot.  Example: an existing Opis satisfies one
        # Industrial Planetary Outpost request that otherwise names Hephaestus.
        for facility_ref, reason in CATALOG.combined_goal_steps(goal, effective_secondary):
            if facility_ref.id != "primary_port":
                signature = CATALOG.functional_signature(facility_ref)
                if existing_counts.get(signature, 0) > 0:
                    existing_counts[signature] -= 1
                    continue
            previous = old_by_id.get(facility_ref.id) or old_by_role.get(facility_ref.display_name)
            facility = FacilityData.from_reference(facility_ref, reason)
            if previous:
                facility.status = previous.status
                facility.location = previous.location
            if facility.facility_id == "primary_port" and self.plan.primary_port_complete:
                facility.status = "Complete"
                facility.location = self.plan.primary_port_location
                facility.role = self.plan.primary_port_name or facility.role
            generated.append(facility)

        # Preserve things that already physically exist or are genuinely under
        # construction even when they are not part of the newly selected goals.
        generated_ids = {facility.facility_id for facility in generated if facility.facility_id}
        for previous in self.plan.facilities:
            if previous.facility_id in generated_ids:
                continue
            if previous.status in ("Complete", "Building now"):
                generated.append(previous)

        if plan_scope == "Continue System Build-Out":
            self._append_system_buildout_rows(
                generated, goal, effective_secondary, old_by_id, old_by_role
            )

        self.plan.facilities = generated
        self._repair_impossible_building_focus()
        self._ensure_prerequisite_rows()
        self._reorder_facilities_for_buildability()
        self._assign_recommended_locations()

    def _append_system_buildout_rows(
        self,
        generated: list[FacilityData],
        primary_goal: str,
        secondary_goal: str,
        old_by_id: dict[str, FacilityData],
        old_by_role: dict[str, FacilityData],
    ) -> None:
        """Extend the finite goal recipes into a substantial system plan.

        No arbitrary facility-count ceiling is used.  The physical slot inventory
        is the natural bound when it is known.  Each functional facility class is
        added at most once during broad build-out; explicit primary/secondary
        recipes can still request multiplicity where the goal genuinely needs it.
        """

        known_refs = list(self._physical_facility_references())
        known_signatures = {
            CATALOG.functional_signature(reference)
            for reference in known_refs
            if reference.id != "primary_port"
        }
        for facility in generated:
            reference = self._reference_for_facility_data(facility)
            if reference.id == "primary_port":
                continue
            known_refs.append(reference)
            known_signatures.add(CATALOG.functional_signature(reference))

        totals_known = any(
            site.surface_total > 0 or site.orbital_total > 0
            for site in self.plan.sites
        )
        surface_remaining: Optional[int] = None
        orbital_remaining: Optional[int] = None
        if totals_known:
            surface_remaining = sum(
                max(0, site.surface_total - site.surface_used)
                for site in self.plan.sites
                if site.landable
            )
            orbital_remaining = sum(
                max(0, site.orbital_total - site.orbital_used)
                for site in self.plan.sites
            )
            # Goal rows already queued by this regeneration consume future slots.
            for facility in generated:
                if facility.status in ("Complete", "Building now"):
                    continue
                if facility.preferred_site == "surface" and surface_remaining is not None:
                    surface_remaining = max(0, surface_remaining - 1)
                elif facility.preferred_site == "orbital" and orbital_remaining is not None:
                    orbital_remaining = max(0, orbital_remaining - 1)

        stages = CATALOG.ordered_buildout_stages(
            primary_goal, secondary_goal, known_refs
        )
        for stage in stages:
            stage_name = str(stage.get("name", "System Development"))
            description = str(stage.get("description", "")).strip()
            before_satisfied = int(stage.get("satisfied", 0) or 0)
            before_total = int(stage.get("total", 0) or 0)
            for reference in CATALOG.stage_facilities(stage):
                signature = CATALOG.functional_signature(reference)
                if signature in known_signatures:
                    continue
                if reference.site_type == "surface" and surface_remaining is not None:
                    if surface_remaining <= 0:
                        continue
                if reference.site_type == "orbital" and orbital_remaining is not None:
                    if orbital_remaining <= 0:
                        continue

                reason = (
                    f"System build-out — {stage_name}: "
                    f"{before_satisfied}/{before_total} stage functions already present. "
                    f"{description}"
                ).strip()
                previous = old_by_id.get(reference.id) or old_by_role.get(reference.display_name)
                facility = FacilityData.from_reference(reference, reason)
                if previous and previous.status not in ("Skipped",):
                    facility.status = previous.status
                    facility.location = previous.location
                generated.append(facility)
                known_refs.append(reference)
                known_signatures.add(signature)
                if reference.site_type == "surface" and surface_remaining is not None:
                    surface_remaining -= 1
                elif reference.site_type == "orbital" and orbital_remaining is not None:
                    orbital_remaining -= 1

                # Update the stage progress embedded in subsequent explanations.
                before_satisfied = min(before_total, before_satisfied + 1)

    @staticmethod
    def _is_port_reference(reference: FacilityRef) -> bool:
        return CATALOG.is_port(reference)

    @staticmethod
    def _location_is_real(location: str) -> bool:
        text = str(location or "")
        return " — Surface " in text or " — Orbit " in text

    def _primary_port_body(self) -> str:
        location = str(self.plan.primary_port_location or "")
        if not self._location_is_real(location):
            return ""
        return self._facility_body_from_location(location)

    def _effective_goal_names(self) -> tuple[str, str]:
        if self.editing and hasattr(self, "primary_combo") and hasattr(self, "secondary_combo"):
            return self.primary_combo.currentText(), self.secondary_combo.currentText()
        return self.plan.primary_goal, self.plan.secondary_goal

    def _effective_plan_scope(self) -> str:
        if self.editing and hasattr(self, "plan_scope_combo"):
            return self.plan_scope_combo.currentText()
        return self.plan.plan_scope

    def _completed_physical_references(self) -> list[FacilityRef]:
        """Facilities that are actually complete, including pre-Observatory sites."""

        refs: list[FacilityRef] = []
        seen: set[tuple[str, str]] = set()
        for facility in self.plan.facilities:
            if facility.status != "Complete":
                continue
            reference = self._reference_for_facility_data(facility)
            body = self._facility_body_from_location(facility.location)
            key = (body, reference.id)
            if key in seen:
                continue
            refs.append(reference)
            seen.add(key)
        for site in self.plan.sites:
            for fragment in self._site_facility_fragments(site.facility):
                reference = CATALOG.facility_from_text(fragment)
                if reference is None:
                    continue
                key = (site.body, reference.id)
                if key in seen:
                    continue
                refs.append(reference)
                seen.add(key)
        return refs

    def _building_references(self) -> list[FacilityRef]:
        return [
            self._reference_for_facility_data(facility)
            for facility in self.plan.facilities
            if facility.status == "Building now"
        ]

    def goal_progress(self, goal_name: str) -> dict[str, Any]:
        return CATALOG.goal_progress(
            goal_name,
            self._completed_physical_references(),
            primary_port_complete=self.plan.primary_port_complete,
            active_facilities=self._building_references(),
        )

    def selected_goal_progress(
        self,
        primary_goal: Optional[str] = None,
        secondary_goal: Optional[str] = None,
    ) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
        primary_goal = primary_goal or self.plan.primary_goal
        secondary_goal = self.plan.secondary_goal if secondary_goal is None else secondary_goal
        primary = self.goal_progress(primary_goal)
        mapped_secondary = CATALOG.mapped_secondary_goal(secondary_goal)
        secondary = self.goal_progress(mapped_secondary) if mapped_secondary else None
        return primary, secondary

    @staticmethod
    def _progress_label(progress: Optional[dict[str, Any]]) -> str:
        if progress is None:
            return "Not selected"
        total = int(progress.get("total", 0) or 0)
        satisfied = int(progress.get("satisfied", 0) or 0)
        status = str(progress.get("status", "Not started"))
        if total:
            return f"{status} — {satisfied}/{total} requirements"
        return status

    def current_development_phase(
        self,
        primary_goal: Optional[str] = None,
        secondary_goal: Optional[str] = None,
        plan_scope: Optional[str] = None,
    ) -> str:
        primary_goal = primary_goal or self.plan.primary_goal
        secondary_goal = self.plan.secondary_goal if secondary_goal is None else secondary_goal
        plan_scope = plan_scope or self._effective_plan_scope()
        primary, secondary = self.selected_goal_progress(primary_goal, secondary_goal)
        if primary.get("status") != "Complete":
            return "Selected goals — primary incomplete"
        if plan_scope != "Primary Goal Only" and secondary is not None and secondary.get("status") != "Complete":
            return "Selected goals — secondary incomplete"
        if plan_scope != "Continue System Build-Out":
            return "Selected goals complete — ready to move on"

        known = self._completed_physical_references()
        ranked = CATALOG.ordered_buildout_stages(primary_goal, secondary_goal, known)
        next_stage = next((stage for stage in ranked if stage.get("status") != "Complete"), None)
        if next_stage is None:
            return "System build-out complete"
        return f"System Build-Out — next stage: {next_stage.get('name', 'System Development')}"

    def _related_bodies_for_facility(self, facility: FacilityData) -> set[str]:
        """Bodies already hosting a direct prerequisite/dependant.

        Placing dependency chains on one body is especially useful after Update
        3 because a port and supporting facilities on/around the same body form
        strong market links.  This is a placement preference, never a fabricated
        construction prerequisite.
        """

        related: set[str] = set()
        reference = self._reference_for_facility_data(facility)
        descriptor = self._descriptor_for_facility_data(facility)
        for other in self.plan.facilities:
            if other is facility or not self._location_is_real(other.location):
                continue
            other_ref = self._reference_for_facility_data(other)
            body = self._facility_body_from_location(other.location)
            if not body:
                continue
            if any(
                CATALOG.descriptor_matches_prerequisite(
                    self._descriptor_for_facility_data(other), prerequisite
                )
                for prerequisite in reference.prerequisites
            ):
                related.add(body)
            if any(
                CATALOG.descriptor_matches_prerequisite(descriptor, prerequisite)
                for prerequisite in other_ref.prerequisites
            ):
                related.add(body)
        return related

    def _body_facility_references(self, body: str) -> list[FacilityRef]:
        refs: list[FacilityRef] = []
        seen: set[str] = set()
        for facility in self.plan.facilities:
            if not self._location_is_real(facility.location):
                continue
            if self._facility_body_from_location(facility.location) != body:
                continue
            reference = self._reference_for_facility_data(facility)
            if reference.id not in seen:
                refs.append(reference)
                seen.add(reference.id)
        for site in self.plan.sites:
            if site.body != body:
                continue
            for fragment in self._site_facility_fragments(site.facility):
                reference = CATALOG.facility_from_text(fragment)
                if reference is not None and reference.id not in seen:
                    refs.append(reference)
                    seen.add(reference.id)
        return refs

    def _site_parent_name(self, site: SiteData) -> str:
        """Return the direct parent body when journal data (or naming) provides it."""

        if site.parent_body:
            return site.parent_body
        tokens = site.body.rsplit(" ", 1)
        if len(tokens) == 2 and tokens[1].islower() and tokens[1].isalpha():
            return tokens[0]
        return ""

    def _planet_moon_neighbor(self, first_body: str, second_body: str) -> bool:
        """True only for a direct parent/child planet-moon relationship.

        This is a travel-convenience tie breaker.  It must never be treated as a
        Strong Market Link: Frontier's strong-link rule still requires the port
        and supporting facility to be on/orbiting the same body.
        """

        if not first_body or not second_body or first_body == second_body:
            return False
        first = next((site for site in self.plan.sites if site.body == first_body), None)
        second = next((site for site in self.plan.sites if site.body == second_body), None)
        if first is None or second is None:
            return False
        return (
            self._site_parent_name(first) == second.body
            or self._site_parent_name(second) == first.body
        )

    @staticmethod
    def _body_economy_affinity(site: SiteData, economy: str) -> int:
        """Small placement bonus from Update-3 body/economy interactions.

        This deliberately uses only body facts Observatory actually has.  It
        does not guess journal-missing organics/geologicals/resource richness.
        """

        economy = CATALOG._normalise(economy)
        body_type = CATALOG._normalise(site.body_type)
        volcanism = CATALOG._normalise(site.volcanism)
        score = 0
        if economy == "extraction":
            if volcanism and volcanism not in {"none", "no volcanism"}:
                score += 90
            if "high metal content" in body_type or "metal rich" in body_type:
                score += 55
        elif economy in {"industrial", "refinery"}:
            if "gas giant" in body_type or "rocky ice" in body_type:
                score += 45
            if economy == "refinery" and "rocky" in body_type:
                score += 35
            if economy == "industrial" and "icy" in body_type:
                score += 25
        elif economy == "agriculture":
            if "earth like" in body_type or "water world" in body_type:
                score += 70
            if "icy" in body_type:
                score -= 45
        elif economy in {"high tech", "research bio", "scientific"}:
            if "earth like" in body_type or "ammonia" in body_type or "gas giant" in body_type:
                score += 55
        elif economy == "tourism":
            if "earth like" in body_type or "water world" in body_type or "ammonia" in body_type:
                score += 65
        return score

    def _placement_score(
        self,
        site: SiteData,
        facility: FacilityData,
        related_bodies: set[str],
    ) -> int:
        reference = self._reference_for_facility_data(facility)
        score = 0
        if site.body in related_bodies:
            score += 1000
        elif any(self._planet_moon_neighbor(site.body, body) for body in related_bodies):
            # Small bonus only: convenient nearby infrastructure, not an
            # economic strong-link substitute for same-body placement.
            score += 55

        primary_body = self._primary_port_body()
        local_refs = self._body_facility_references(site.body)
        is_port = self._is_port_reference(reference)
        local_ports = [other for other in local_refs if self._is_port_reference(other)]
        local_support = [other for other in local_refs if not self._is_port_reference(other)]

        # Update 3: port<->supporting-facility on the same body is a strong link;
        # different bodies are only weak links.  Build goal clusters around an
        # existing/planned port whenever the correct physical slot exists.
        if not is_port and local_ports:
            score += 520 + 30 * max(int(port.tier or 0) for port in local_ports)
        elif is_port and local_support:
            score += 420 + 20 * len(local_support)
        elif primary_body and site.body == primary_body and not is_port:
            score += 300
        elif primary_body and self._planet_moon_neighbor(site.body, primary_body):
            score += 25

        economy = CATALOG._normalise(reference.market_economy or reference.economy)
        if economy:
            for other in local_refs:
                other_economy = CATALOG._normalise(other.market_economy or other.economy)
                if other_economy and other_economy == economy:
                    score += 70

            primary_goal, secondary_goal = self._effective_goal_names()
            weights = CATALOG.goal_economy_weights(primary_goal, secondary_goal)
            score += 8 * weights.get(economy, 0)
            score += self._body_economy_affinity(site, economy)

        # When otherwise equal, leave bodies with more capacity flexible.
        if facility.preferred_site == "surface":
            score += max(0, site.surface_total - site.surface_used)
        else:
            score += max(0, site.orbital_total - site.orbital_used)
        return score

    def _best_location_for_facility(
        self,
        facility: FacilityData,
        reserved: set[str],
    ) -> str:
        group = facility.preferred_site
        related_bodies = self._related_bodies_for_facility(facility)
        candidates: list[tuple[int, tuple[Any, ...], int, str]] = []
        for site in self.plan.sites:
            if group == "surface":
                if not site.landable:
                    continue
                used, total = site.surface_used, site.surface_total
                label_word = "Surface"
            elif group == "orbital":
                used, total = site.orbital_used, site.orbital_total
                label_word = "Orbit"
            else:
                continue
            for number in range(used + 1, total + 1):
                label = f"{site.body} — {label_word} {number}"
                if label in reserved:
                    continue
                candidates.append((
                    -self._placement_score(site, facility, related_bodies),
                    self._body_sort_key(site.body, site.body_id),
                    number,
                    label,
                ))
        if candidates:
            candidates.sort()
            return candidates[0][3]
        if group == "surface":
            return "No available surface slots"
        if group == "orbital":
            return "No available orbital slots"
        return "No compatible construction slots"

    def _free_location(self, preferred: str) -> str:
        """Return a free slot of the requested type only.

        Surface and orbital construction are hard constraints.  A surface
        settlement/hub is never silently moved into orbit, and an orbital
        installation/port is never silently moved onto a planet.
        """

        dummy = FacilityData(
            role="slot probe", reason="", preferred_site=preferred
        )
        return self._best_location_for_facility(dummy, set())

    def _assign_recommended_locations(self) -> None:
        reserved: set[str] = set()
        for facility in self.plan.facilities:
            if (
                facility.status in ("Complete", "Building now")
                and self._location_is_real(facility.location)
            ):
                reserved.add(facility.location)
                continue
            proposed = self._best_location_for_facility(facility, reserved)
            facility.location = proposed
            if self._location_is_real(proposed):
                reserved.add(proposed)

    def _next_unreserved_location(self, preferred: str, reserved: set[str]) -> str:
        # Kept for older callers; unlike pre-v3.0.6 this never crosses the
        # surface/orbital boundary.
        dummy = FacilityData(
            role="slot probe", reason="", preferred_site=preferred
        )
        return self._best_location_for_facility(dummy, reserved)

    def _site_markers(self) -> dict[str, list[str]]:
        markers: dict[str, list[str]] = {}
        next_buildable = self._next_buildable_facility()
        for facility in self.plan.facilities:
            location = facility.location or ""
            matched = next(
                (site for site in self.plan.sites if location.startswith(site.body + " —")),
                None,
            )
            if matched is None:
                continue
            if facility.status == "Complete":
                marker = f"✓ {facility.role}"
            elif facility.status == "Building now":
                marker = f"⚒ {facility.role}"
            elif facility is next_buildable:
                marker = f"→ {facility.role}"
            else:
                marker = f"• {facility.role}"
            markers.setdefault(matched.body, []).append(marker)
        return markers

    def _render_sites(self) -> None:
        self.sites_table.setSortingEnabled(False)
        self.plan.sites.sort(key=lambda site: self._body_sort_key(site.body, site.body_id))
        markers = self._site_markers()
        self.sites_table.setRowCount(len(self.plan.sites))
        for row, site in enumerate(self.plan.sites):
            marker_parts = []
            if site.facility:
                marker_parts.append(site.facility)
            marker_parts.extend(markers.get(site.body, []))
            marker_text = "; ".join(part for part in marker_parts if part)
            values = [
                site.body,
                site.body_type,
                "Yes" if site.landable else "No",
                self._usage_text(site.orbital_used, site.orbital_total),
                self._usage_text(site.surface_used, site.surface_total),
                marker_text,
                site.confidence,
            ]
            highlighted = marker_text.startswith("→") or "→" in marker_text
            building = "⚒" in marker_text
            complete = "✓" in marker_text
            for col, value in enumerate(values):
                item = (
                    BodySortItem(value, self._body_sort_key(site.body, site.body_id))
                    if col == 0
                    else QTableWidgetItem(value)
                )
                # In Edit Plan mode the player can correct slot counts and type
                # facility markers directly in the spreadsheet.  Body metadata
                # and confidence remain journal-derived/read-only.
                if col in (0, 1, 2, 6):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if highlighted:
                    item.setBackground(QColor("#5B3B05"))
                elif building:
                    item.setBackground(QColor("#4A3410"))
                elif complete and col == 5:
                    item.setBackground(QColor("#173820"))
                self.sites_table.setItem(row, col, item)
        self.sites_table.setSortingEnabled(True)
        self.sites_table.sortItems(0, Qt.SortOrder.AscendingOrder)

        orbital_used = sum(site.orbital_used for site in self.plan.sites)
        orbital_total = sum(site.orbital_total for site in self.plan.sites)
        surface_used = sum(site.surface_used for site in self.plan.sites)
        surface_total = sum(site.surface_total for site in self.plan.sites)
        capacity_notes: list[str] = []
        if any(str(site.confidence).startswith("Estimated") for site in self.plan.sites):
            capacity_notes.append("some surface capacity is estimated")
        if self.plan.sites and orbital_total == 0:
            capacity_notes.append("no orbital capacity entered")
        suffix = f"  •  Setup note: {', '.join(capacity_notes)}" if capacity_notes else ""
        self.site_summary.setText(
            f"Build system: {self.display_system_name()}  •  "
            f"Orbital {orbital_used}/{orbital_total}  •  Surface {surface_used}/{surface_total}  •  "
            f"Available: {max(0, orbital_total-orbital_used)} orbital, "
            f"{max(0, surface_total-surface_used)} surface{suffix}"
        )

        next_facility = self._next_buildable_facility()
        if next_facility is None:
            blocked = next((f for f in self.plan.facilities if f.status == "Queued"), None)
            if blocked is None:
                self.sites_next.setText("Next build: plan complete or no goal recommendation available")
            else:
                self.sites_next.setText(
                    f"NO BUILDABLE NEXT FACILITY • {blocked.role} is blocked: "
                    f"{self._facility_block_reason(blocked)}"
                )
        else:
            self.sites_next.setText(
                f"→ NEXT BUILD: {next_facility.role}  •  Build at {next_facility.location}  •  "
                f"{next_facility.point_summary}  •  {next_facility.reason}"
            )

    def _render_queue(
        self,
        goal: Optional[str] = None,
        secondary_goal: Optional[str] = None,
        plan_scope: Optional[str] = None,
    ) -> None:
        goal = goal or self.plan.primary_goal
        secondary_goal = (
            self.plan.secondary_goal if secondary_goal is None else secondary_goal
        )
        plan_scope = plan_scope or self._effective_plan_scope()
        changed_metadata = self._clean_saved_site_facilities()
        changed_metadata = self._refresh_plan_facility_metadata() or changed_metadata
        if changed_metadata:
            self._save_plan()

        # A saved queue may contain only completed rows after an older Sites edit
        # accidentally promoted planned bullet markers to existing facilities.
        # If the selected objectives/build-out are still incomplete, regenerate
        # instead of displaying a false "plan complete" state.
        primary_before, secondary_before = self.selected_goal_progress(goal, secondary_goal)
        has_pending = any(
            row.status in ("Queued", "Building now") for row in self.plan.facilities
        )
        phase_before = self.current_development_phase(goal, secondary_goal, plan_scope)
        needs_pending_work = primary_before.get("status") != "Complete"
        if plan_scope != "Primary Goal Only" and secondary_before is not None:
            needs_pending_work = needs_pending_work or secondary_before.get("status") != "Complete"
        if plan_scope == "Continue System Build-Out":
            needs_pending_work = needs_pending_work or phase_before != "System build-out complete"

        if (
            goal != self.plan.primary_goal
            or secondary_goal != self.plan.secondary_goal
            or plan_scope != self.plan.plan_scope
            or not self.plan.facilities
            or (not has_pending and needs_pending_work)
        ):
            self._regenerate_facilities(goal, secondary_goal, plan_scope)
        else:
            changed = self._repair_impossible_building_focus()
            changed = self._ensure_prerequisite_rows() or changed
            changed = self._reorder_facilities_for_buildability() or changed
            self._assign_recommended_locations()
            if changed:
                self._save_plan()

        rows = self.plan.facilities
        tier_2, tier_3 = self._construction_point_balance()
        primary_progress, secondary_progress = self.selected_goal_progress(goal, secondary_goal)
        phase = self.current_development_phase(goal, secondary_goal, plan_scope)
        secondary_text = self._progress_label(secondary_progress)
        point_source = "game-calibrated" if self.plan.point_balance_calibrated else "calculated"
        self.queue_notice.setText(
            f"{self.display_system_name()}  •  Points now: {tier_2} T2, {tier_3} T3 ({point_source})  •  "
            f"Primary: {self._progress_label(primary_progress)}  •  "
            f"Secondary: {secondary_text}  •  {phase}"
        )
        self.queue_table.setRowCount(len(rows))
        next_facility = self._next_buildable_facility()
        for row, facility in enumerate(rows):
            if self.plan.primary_port_complete and facility.facility_id == "primary_port":
                facility.status = "Complete"
            block_reason = self._facility_block_reason(facility) if facility.status == "Queued" else ""
            if facility.status == "Queued" and facility is next_facility:
                action = "→ NEXT"
            elif facility.status == "Queued" and block_reason:
                action = "BLOCKED"
            elif facility.status == "Building now":
                action = "⚒ BUILDING"
            elif facility.status == "Complete":
                action = "✓ COMPLETE"
            elif facility.status == "Skipped":
                action = "Skipped"
            else:
                action = "Planned"
            values = [
                str(row + 1),
                facility.role,
                self._queue_display_location(facility.location),
                facility.preferred_site.title(),
                facility.point_summary,
                facility.reason,
                facility.status,
                block_reason if action == "BLOCKED" else action,
            ]
            tooltips = [
                str(row + 1),
                facility.role,
                facility.location,
                facility.preferred_site.title(),
                facility.point_summary,
                facility.reason,
                facility.status,
                block_reason if action == "BLOCKED" else action,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(tooltips[col])
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if action == "→ NEXT":
                    item.setBackground(QColor("#5B3B05"))
                elif action == "BLOCKED":
                    item.setForeground(QColor("#EF5350"))
                elif action == "⚒ BUILDING":
                    item.setBackground(QColor("#4A3410"))
                elif action == "✓ COMPLETE":
                    item.setBackground(QColor("#173820"))
                elif action == "Skipped":
                    item.setForeground(QColor("#6F7B85"))
                self.queue_table.setItem(row, col, item)

        if hasattr(self, "queue_next_button"):
            self.queue_next_button.setEnabled(next_facility is not None)

        if next_facility:
            try:
                next_row = rows.index(next_facility)
                self.queue_table.selectRow(next_row)
                self.queue_table.scrollToItem(
                    self.queue_table.item(next_row, 0),
                    QAbstractItemView.ScrollHint.EnsureVisible,
                )
            except (ValueError, AttributeError):
                pass
            self.next_build_value.setText(next_facility.role)
            self.next_location_value.setText(next_facility.location)
            self.next_reason_value.setText(
                f"{next_facility.reason}  •  {next_facility.point_summary}  •  "
                f"confidence: {next_facility.confidence}"
            )
            self.set_next_current_button.setEnabled(
                self._location_is_real(next_facility.location)
            )
            self.undo_focus_button.setEnabled(bool(self.plan.previous_current_build))
        else:
            blocked = next((f for f in self.plan.facilities if f.status == "Queued"), None)
            if blocked is not None:
                self.next_build_value.setText("No buildable next facility")
                self.next_location_value.setText(blocked.location)
                self.next_reason_value.setText(
                    f"{blocked.role} is currently blocked. {self._facility_block_reason(blocked)}"
                )
            else:
                self.next_build_value.setText("No more recommended builds")
                self.next_location_value.setText("None")
                self.next_reason_value.setText("")
            self.set_next_current_button.setEnabled(False)
            self.undo_focus_button.setEnabled(bool(self.plan.previous_current_build))
        if hasattr(self, "sites_next"):
            self._render_sites()
        self._render_materials()

    def _selected_queue_facility(self) -> Optional[FacilityData]:
        row = self.queue_table.currentRow()
        if row < 0 or row >= len(self.plan.facilities):
            return None
        return self.plan.facilities[row]

    def set_recommendation_as_current(self) -> None:
        facility = self._next_buildable_facility()
        if facility is None:
            return
        self._set_focus_facility(facility)

    def set_selected_queue_as_current(self) -> None:
        facility = self._selected_queue_facility()
        if facility is None:
            return
        if facility.status == "Queued":
            blocked = self._facility_block_reason(facility)
            if blocked:
                QMessageBox.information(
                    self,
                    "Facility is blocked",
                    f"{facility.role}\n\n{blocked}",
                )
                return
        self._set_focus_facility(facility)

    def _set_focus_facility(self, facility: FacilityData) -> None:
        if self.plan.current_build and self.plan.current_build != "Not selected":
            self.plan.previous_current_build = self.plan.current_build
            self.plan.previous_current_location = self.plan.current_location
        for other in self.plan.facilities:
            if other.status == "Building now":
                other.status = "Queued"
        facility.status = "Building now"
        facility.construction_started = False
        self.plan.current_build = facility.role
        self.plan.current_location = facility.location
        self._save_plan()
        self._save_active_focus_record(facility)
        self._apply_plan()
        # Tracking a build is primarily a materials workflow. Move the player to
        # the operational screen automatically; the Build Queue remains one click away.
        self.set_view_name("Materials")

    def undo_focus_change(self) -> None:
        previous_build = self.plan.previous_current_build
        previous_location = self.plan.previous_current_location
        if not previous_build:
            return
        current_build = self.plan.current_build
        current_location = self.plan.current_location
        restored: Optional[FacilityData] = None
        for facility in self.plan.facilities:
            if facility.role == current_build and facility.location == current_location:
                facility.status = "Queued"
            if facility.role == previous_build and facility.location == previous_location:
                facility.status = "Building now"
                restored = facility
        self.plan.current_build = previous_build
        self.plan.current_location = previous_location or "Not selected"
        self.plan.previous_current_build = current_build if current_build != "Not selected" else ""
        self.plan.previous_current_location = current_location if current_location != "Not selected" else ""
        self._save_plan()
        if restored is not None:
            self._save_active_focus_record(restored)
        self._apply_plan()


    def skip_selected_queue_item(self) -> None:
        facility = self._selected_queue_facility()
        if facility is None:
            return
        if facility.status == "Building now":
            self.plan.current_build = "Not selected"
            self.plan.current_location = "Not selected"
            self.active_focus = {}
            self.settings.remove("construction/active_focus")
        facility.status = "Skipped"
        self._save_plan()
        self._apply_plan()

    def mark_selected_queue_complete(self) -> None:
        facility = self._selected_queue_facility()
        if facility is None:
            return
        facility.status = "Complete"
        if facility.facility_id == "primary_port" or facility.role == "Primary Port":
            self.plan.primary_port_complete = True
            self.plan.primary_port_location = facility.location
            self.plan.primary_port_name = facility.role
        if (
            self.plan.current_build == facility.role
            and self.plan.current_location == facility.location
        ):
            self.plan.current_build = "Not selected"
            self.plan.current_location = "Not selected"
            self.active_focus = {}
            self.settings.remove("construction/active_focus")
        self._save_plan()
        self._apply_plan()



    def focus_build_display(self) -> tuple[str, str]:
        """Return the actual pinned/current build, not the next recommendation."""
        facility = self._focus_facility()
        if facility is not None:
            return facility.role, facility.location
        return self.plan.current_build, self.plan.current_location

    def focus_material_summary(self) -> tuple[str, str, str]:
        """Compact material status for construction mini mode."""
        facility = self._focus_facility()
        if facility is None:
            return ("No focus build", "Trips —", "Source: —")
        rows = self._stored_materials_for(facility)
        capacity = max(1, int(self.plan.ship_capacity_tons or 1))
        needed = [row for row in rows if row.still_needed > 0]
        if not needed:
            return ("Materials: complete", "Trips 0", "Source: —")
        needed.sort(key=lambda row: row.still_needed, reverse=True)
        top = needed[0]
        total_left = sum(row.still_needed for row in needed)
        trips = (total_left + capacity - 1) // capacity
        source = top.source.strip() if top.source else ""
        if self._is_placeholder_source(source):
            source = "Paste Location"
        return (
            f"{top.commodity}: {top.still_needed:,} left",
            f"Trips {trips}",
            f"Source: {source}",
        )

    def focus_material_progress_percent(self) -> int:
        """Delivered-material percentage for the pinned construction job."""
        _title, _detail, _source, progress = self._next_action_data()
        return max(0, min(100, int(progress)))

    def set_view_name(self, name: str) -> None:
        mapping = {"Overview": 0, "Sites": 1, "Build Queue": 2, "Materials": 3}
        self.tabs.setCurrentIndex(mapping.get(name, 0))

    def view_name(self) -> str:
        return self.tabs.tabText(self.tabs.currentIndex())
