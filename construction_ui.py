from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from PyQt6.QtCore import Qt, QSettings, pyqtSignal
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

from construction_rules import ColonisationCatalog, FacilityRef, MaterialRequirement
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
    tier: int = 0
    economy: str = ""
    requires_tier_2: int = 0
    requires_tier_3: int = 0
    provides_tier_2: int = 0
    provides_tier_3: int = 0
    confidence: str = "unverified"

    @classmethod
    def from_reference(cls, facility: FacilityRef, reason: str) -> "FacilityData":
        return cls(
            role=facility.display_name,
            reason=reason or facility.notes or facility.point_summary,
            preferred_site=facility.site_type,
            facility_id=facility.id,
            facility_type=facility.facility_type,
            tier=facility.tier,
            economy=facility.economy,
            requires_tier_2=facility.requires_tier_2,
            requires_tier_3=facility.requires_tier_3,
            provides_tier_2=facility.provides_tier_2,
            provides_tier_3=facility.provides_tier_3,
            confidence=facility.confidence,
        )

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


@dataclass
class PlanData:
    primary_goal: str = "Balanced Colony"
    secondary_goal: str = "None"
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
            return
        try:
            data = json.loads(str(raw))
            sites = [SiteData(**row) for row in data.pop("sites", [])]
            facilities = [FacilityData(**row) for row in data.pop("facilities", [])]
            allowed = {k: data[k] for k in PlanData.__dataclass_fields__ if k in data}
            self.plan = PlanData(**allowed)
            self.plan.sites = sites
            self.plan.facilities = facilities
        except (ValueError, TypeError):
            self.plan = PlanData()

    def _save_plan(self) -> None:
        self.settings.setValue(self._key(), json.dumps(asdict(self.plan), sort_keys=True))
        self.settings.sync()

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
            "tier": facility.tier,
            "economy": facility.economy,
            "preferred_site": facility.preferred_site,
            "reason": facility.reason,
            "confidence": facility.confidence,
            "material_key": self._material_key_for(facility),
            "ship_capacity_tons": int(self.plan.ship_capacity_tons or 1),
            "materials": [self._material_dict(row) for row in materials],
        }
        self.active_focus = record
        self.settings.setValue("construction/active_focus", json.dumps(record, sort_keys=True))
        self.settings.sync()

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
            tier=self._int_cell(self.active_focus.get("tier", 0)),
            economy=str(self.active_focus.get("economy", "")),
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
        self.settings.sync()

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

    def set_system_data(self, system_name: str, bodies: dict[str, Any]) -> None:
        """Load every indexed body while preserving player-entered corrections."""
        self.current_system_name = system_name or "Unknown system"
        if not self.set_system(system_name):
            # System Status Lock is active and the commander has jumped away.
            # Keep the planning tabs pinned to the locked colony system.
            return
        known = {site.body: site for site in self.plan.sites}
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

            if name in known:
                site = known[name]
                site.body_type = body_type
                site.landable = landable
                site.body_id = body_id
                site.radius_km = radius_km
                site.mass_em = mass_em
                site.atmosphere = atmosphere
                site.volcanism = volcanism
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
                )
            )
            changed = True

        self.plan.sites.sort(key=lambda site: self._body_sort_key(site.body, site.body_id))
        if changed:
            self._save_plan()
        self._regenerate_facilities()
        self._render_sites()
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
        self.live_depot = depot
        self.live_depot_resources = resources

        if facility is not None and resources:
            key = self._material_key_for(facility)
            self.plan.materials_by_build[key] = [self._material_dict(row) for row in resources]
            self._save_plan()
            self._save_active_focus_record(facility, resources)

        if previous_key != next_key or previous_signature != next_signature:
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
        self.overview_system_state_value.setObjectName("constructionStatusPill")
        self.primary_combo = QComboBox()
        self.primary_combo.addItems(PRIMARY_GOALS)
        self.secondary_combo = QComboBox()
        self.secondary_combo.addItems(SECONDARY_GOALS)
        self.phase_edit = QLineEdit()
        self.phase_edit.hide()
        p.addWidget(self.overview_build_system_value)
        p.addWidget(self.overview_system_state_value)
        p.addWidget(QLabel("Primary goal"))
        p.addWidget(self.primary_combo)
        p.addWidget(QLabel("Secondary goal"))
        p.addWidget(self.secondary_combo)

        # Existing-colony details are setup data, not daily hauling information.
        # Keep them available only while Edit Plan is active.
        self.colony_setup_editor = QWidget()
        colony_layout = QVBoxLayout(self.colony_setup_editor)
        colony_layout.setContentsMargins(0, 6, 0, 0)
        colony_layout.setSpacing(4)
        self.primary_port_check = QCheckBox("Primary port is complete")
        self.primary_port_name_edit = QLineEdit()
        self.primary_port_location_edit = QLineEdit()
        colony_layout.addWidget(self.primary_port_check)
        colony_layout.addWidget(QLabel("Primary port / station name"))
        colony_layout.addWidget(self.primary_port_name_edit)
        colony_layout.addWidget(QLabel("Occupied location"))
        colony_layout.addWidget(self.primary_port_location_edit)
        p.addWidget(self.colony_setup_editor)
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
        self.undo_focus_button = QPushButton("Undo Focus Change")
        self.undo_focus_button.setToolTip("Restore the previous focus build if this was selected by mistake.")
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
        self.set_next_current_button = QPushButton("Set This as Focus Build")
        self.set_next_current_button.clicked.connect(self.set_recommendation_as_current)
        n.addWidget(self.set_next_current_button)
        n.addStretch()

        action, a = self._box("Next Action")
        self.next_action_title = QLabel("Choose a focus build")
        self.next_action_title.setObjectName("constructionBigValue")
        self.next_action_title.setWordWrap(True)
        self.next_action_detail = QLabel("Set the recommended build as Focus to begin tracking materials.")
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
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 20)
        summary.addWidget(self.site_summary, stretch=1)
        summary.addWidget(QLabel("Concurrent build limit"))
        summary.addWidget(self.concurrent_spin)
        layout.addLayout(summary)

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
        self.queue_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.queue_table)

        actions = QHBoxLayout()
        self.queue_focus_button = QPushButton("Set Selected as Focus Build")
        self.queue_complete_button = QPushButton("Mark Selected Complete")
        self.queue_skip_button = QPushButton("Skip Selected")
        self.queue_focus_button.clicked.connect(self.set_selected_queue_as_current)
        self.queue_complete_button.clicked.connect(self.mark_selected_queue_complete)
        self.queue_skip_button.clicked.connect(self.skip_selected_queue_item)
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

        self.materials_context = QLabel("No focus build selected")
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
        self.next_haul_title = QLabel("NEXT HAUL: choose a focus build")
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
        return next((facility for facility in self.plan.facilities if facility.status == "Queued"), None)

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
            self.settings.sync()
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
            return (
                "Choose a focus build",
                "Set the recommended build as Focus to begin tracking materials.",
                "Paste Location",
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
                f"No focus build selected • Build system: {self.display_system_name()}"
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
                facility=text(5),
                status="Available",
                confidence="User confirmed" if self.editing else (text(6) or "User entered"),
                body_id=previous.body_id if previous else 999999,
                mass_em=previous.mass_em if previous else None,
                radius_km=previous.radius_km if previous else None,
                atmosphere=previous.atmosphere if previous else "",
                volcanism=previous.volcanism if previous else "",
            ))
        return rows

    def set_editing(self, enabled: bool) -> None:
        self.editing = enabled
        self.lock_label.setText("Editing plan" if enabled else "Plan fields locked")
        self.edit_button.setVisible(not enabled)
        self.cancel_button.setVisible(enabled)
        self.save_button.setVisible(enabled)
        for widget in (
            self.primary_combo,
            self.secondary_combo,
            self.phase_edit,
            self.primary_port_check,
            self.primary_port_name_edit,
            self.primary_port_location_edit,
            self.concurrent_spin,
        ):
            widget.setEnabled(enabled)
        self.sites_table.setEditTriggers(
            QTableWidget.EditTrigger.AllEditTriggers if enabled
            else QTableWidget.EditTrigger.NoEditTriggers
        )
        # Confidence is troubleshooting data. Keep the normal player workflow
        # focused on slots and builds, but reveal it during Edit Plan.
        self.sites_table.setColumnHidden(6, not enabled)
        if hasattr(self, "colony_setup_editor"):
            self.colony_setup_editor.setVisible(enabled)
        if hasattr(self, "materials_table"):
            # Material Source stays editable even when the plan is locked,
            # because choosing where to buy commodities is an operational action.
            self.materials_table.setEditTriggers(QTableWidget.EditTrigger.AllEditTriggers)
            self._render_materials()
        if hasattr(self, "add_material_button"):
            self.add_material_button.setVisible(enabled)
            self.remove_material_button.setVisible(enabled)
            self.ship_capacity_spin.setEnabled(enabled)

    def cancel_edits(self) -> None:
        self._apply_plan()
        self.set_editing(False)

    def save_edits(self) -> None:
        old_goal = self.plan.primary_goal
        new_goal = self.primary_combo.currentText()
        if old_goal != new_goal:
            answer = QMessageBox.question(
                self,
                "Change system goal?",
                "Changing the primary goal regenerates the recommended build queue. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.plan.primary_goal = new_goal
        self.plan.secondary_goal = self.secondary_combo.currentText()
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
        self.phase_edit.setText(self.plan.phase)
        self.primary_port_check.setChecked(self.plan.primary_port_complete)
        self.primary_port_name_edit.setText(self.plan.primary_port_name)
        self.primary_port_location_edit.setText(self.plan.primary_port_location)
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
            self._render_queue(self.primary_combo.currentText())

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

    def _regenerate_facilities(self, goal: Optional[str] = None) -> None:
        goal = goal or self.plan.primary_goal
        old_by_id = {facility.facility_id: facility for facility in self.plan.facilities if facility.facility_id}
        old_by_role = {facility.role: facility for facility in self.plan.facilities}
        generated: list[FacilityData] = []

        for facility_ref, reason in CATALOG.goal_steps(goal):
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

        self.plan.facilities = generated
        self._assign_recommended_locations()

    def _free_location(self, preferred: str) -> str:
        candidates = self.plan.sites
        if preferred == "surface":
            for site in candidates:
                if site.landable and site.surface_used < site.surface_total:
                    return f"{site.body} — Surface {site.surface_used + 1}"
            for site in candidates:
                if site.orbital_used < site.orbital_total:
                    return f"{site.body} — Orbit {site.orbital_used + 1}"
        else:
            for site in candidates:
                if site.orbital_used < site.orbital_total:
                    return f"{site.body} — Orbit {site.orbital_used + 1}"
            for site in candidates:
                if site.landable and site.surface_used < site.surface_total:
                    return f"{site.body} — Surface {site.surface_used + 1}"
        return "Enter available slots on Sites"

    def _assign_recommended_locations(self) -> None:
        reserved: set[str] = set()
        for facility in self.plan.facilities:
            if facility.status in ("Complete", "Building now") and facility.location != "Unassigned":
                reserved.add(facility.location)
                continue
            proposed = self._free_location(facility.preferred_site)
            # Move forward if an earlier queue row already reserved the same first slot.
            if proposed in reserved:
                proposed = self._next_unreserved_location(facility.preferred_site, reserved)
            facility.location = proposed
            if proposed != "Enter available slots on Sites":
                reserved.add(proposed)

    def _next_unreserved_location(self, preferred: str, reserved: set[str]) -> str:
        groups = ("surface", "orbital") if preferred == "surface" else ("orbital", "surface")
        for group in groups:
            for site in self.plan.sites:
                used = site.surface_used if group == "surface" else site.orbital_used
                total = site.surface_total if group == "surface" else site.orbital_total
                if group == "surface" and not site.landable:
                    continue
                for number in range(used + 1, total + 1):
                    label = f"{site.body} — {'Surface' if group == 'surface' else 'Orbit'} {number}"
                    if label not in reserved:
                        return label
        return "Enter available slots on Sites"

    def _site_markers(self) -> dict[str, list[str]]:
        markers: dict[str, list[str]] = {}
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
            elif facility is next((f for f in self.plan.facilities if f.status == "Queued"), None):
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
        self.site_summary.setText(
            f"Build system: {self.display_system_name()}  •  "
            f"Orbital {orbital_used}/{orbital_total}  •  Surface {surface_used}/{surface_total}  •  "
            f"Available: {max(0, orbital_total-orbital_used)} orbital, "
            f"{max(0, surface_total-surface_used)} surface"
        )

        next_facility = next((f for f in self.plan.facilities if f.status == "Queued"), None)
        if next_facility is None:
            self.sites_next.setText("Next build: plan complete or no goal recommendation available")
        else:
            self.sites_next.setText(
                f"→ NEXT BUILD: {next_facility.role}  •  Build at {next_facility.location}  •  "
                f"{next_facility.point_summary}  •  {next_facility.reason}"
            )

    def _render_queue(self, goal: Optional[str] = None) -> None:
        goal = goal or self.plan.primary_goal
        if goal != self.plan.primary_goal or not self.plan.facilities:
            self._regenerate_facilities(goal)
        else:
            self._assign_recommended_locations()

        rows = self.plan.facilities
        self.queue_notice.setText(
            f"Build system: {self.display_system_name()}  •  Suggested order; verify any unconfirmed facility data in game."
        )
        self.queue_table.setRowCount(len(rows))
        next_facility: Optional[FacilityData] = None
        for row, facility in enumerate(rows):
            if self.plan.primary_port_complete and facility.facility_id == "primary_port":
                facility.status = "Complete"
            if facility.status == "Queued" and next_facility is None:
                next_facility = facility
                action = "→ NEXT"
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
                facility.location,
                facility.preferred_site.title(),
                facility.point_summary,
                facility.reason,
                facility.status,
                action,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if action == "→ NEXT":
                    item.setBackground(QColor("#5B3B05"))
                elif action == "⚒ BUILDING":
                    item.setBackground(QColor("#4A3410"))
                elif action == "✓ COMPLETE":
                    item.setBackground(QColor("#173820"))
                elif action == "Skipped":
                    item.setForeground(QColor("#6F7B85"))
                self.queue_table.setItem(row, col, item)

        if next_facility:
            self.next_build_value.setText(next_facility.role)
            self.next_location_value.setText(next_facility.location)
            self.next_reason_value.setText(
                f"{next_facility.reason}  •  {next_facility.point_summary}  •  "
                f"confidence: {next_facility.confidence}"
            )
            self.set_next_current_button.setEnabled(
                next_facility.location != "Enter available slots on Sites"
            )
            self.undo_focus_button.setEnabled(bool(self.plan.previous_current_build))
        else:
            self.next_build_value.setText("Plan complete or custom plan")
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
        facility = next((f for f in self.plan.facilities if f.status == "Queued"), None)
        if facility is None:
            return
        self._set_focus_facility(facility)

    def set_selected_queue_as_current(self) -> None:
        facility = self._selected_queue_facility()
        if facility is not None:
            self._set_focus_facility(facility)

    def _set_focus_facility(self, facility: FacilityData) -> None:
        if self.plan.current_build and self.plan.current_build != "Not selected":
            self.plan.previous_current_build = self.plan.current_build
            self.plan.previous_current_location = self.plan.current_location
        for other in self.plan.facilities:
            if other.status == "Building now":
                other.status = "Queued"
        facility.status = "Building now"
        self.plan.current_build = facility.role
        self.plan.current_location = facility.location
        self._save_plan()
        self._save_active_focus_record(facility)
        self._apply_plan()

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

    def set_view_name(self, name: str) -> None:
        mapping = {"Overview": 0, "Sites": 1, "Build Queue": 2, "Materials": 3}
        self.tabs.setCurrentIndex(mapping.get(name, 0))

    def view_name(self) -> str:
        return self.tabs.tabText(self.tabs.currentIndex())
