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
    carrier: int = 0
    source: str = ""

    @property
    def still_needed(self) -> int:
        return max(0, int(self.required) - int(self.delivered) - int(self.carrier))

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

    def __init__(self, settings: QSettings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings = settings
        self.system_name = "Unknown system"
        self.plan = PlanData()
        self.editing = False
        self.live_depot: Optional[dict[str, Any]] = None
        self.live_depot_resources: list[MaterialData] = []
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

    def set_system(self, system_name: str) -> None:
        system_name = system_name or "Unknown system"
        if system_name == self.system_name:
            return
        self.system_name = system_name
        self._load_plan()
        self._apply_plan()

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
        self.set_system(system_name)
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
        Required/Delivered amounts after a construction site exists. Facility
        database materials are only a planning fallback before that event is
        observed.
        """
        candidates: list[dict[str, Any]] = []
        for depot in (depots or {}).values():
            if not isinstance(depot, dict):
                continue
            depot_system = depot.get("system")
            depot_address = depot.get("system_address")
            if depot_system and str(depot_system) != self.system_name:
                continue
            candidates.append(depot)

        if not candidates:
            if self.live_depot is not None or self.live_depot_resources:
                self.live_depot = None
                self.live_depot_resources = []
                self._render_materials()
            return

        candidates.sort(key=lambda row: str(row.get("timestamp") or ""), reverse=True)
        depot = candidates[0]
        resources: list[MaterialData] = []
        for row in depot.get("resources", []) or []:
            if not isinstance(row, dict):
                continue
            commodity = str(row.get("commodity", "")).strip()
            if not commodity:
                continue
            resources.append(MaterialData(
                commodity=commodity,
                required=self._int_cell(row.get("required", 0)),
                delivered=self._int_cell(row.get("delivered", 0)),
                carrier=self._int_cell(row.get("carrier", 0)),
                source=str(row.get("source", "Paste Location")),
            ))

        previous_key = self.live_depot.get("market_id") if isinstance(self.live_depot, dict) else None
        next_key = depot.get("market_id")
        previous_count = len(self.live_depot_resources)
        self.live_depot = depot
        self.live_depot_resources = resources
        if previous_key != next_key or previous_count != len(resources):
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
        self.lock_label = QLabel("Plan locked")
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

        purpose, p = self._box("System Purpose")
        self.primary_combo = QComboBox()
        self.primary_combo.addItems(PRIMARY_GOALS)
        self.secondary_combo = QComboBox()
        self.secondary_combo.addItems(SECONDARY_GOALS)
        self.phase_edit = QLineEdit()
        for label, widget in (("Primary goal", self.primary_combo), ("Secondary goal", self.secondary_combo), ("Colony phase", self.phase_edit)):
            p.addWidget(QLabel(label))
            p.addWidget(widget)
        p.addStretch()

        existing, e = self._box("Existing Colony")
        self.primary_port_check = QCheckBox("Primary port is complete")
        self.primary_port_name_edit = QLineEdit()
        self.primary_port_location_edit = QLineEdit()
        e.addWidget(self.primary_port_check)
        e.addWidget(QLabel("Primary port / station name"))
        e.addWidget(self.primary_port_name_edit)
        e.addWidget(QLabel("Occupied location"))
        e.addWidget(self.primary_port_location_edit)
        e.addStretch()

        next_box, n = self._box("Next Recommended Build")
        self.next_build_value = QLabel("No recommendation yet")
        self.next_build_value.setObjectName("constructionBigValue")
        self.next_location_value = QLabel("Enter body slot counts on Sites")
        self.next_reason_value = QLabel("")
        self.next_reason_value.setWordWrap(True)
        n.addWidget(self.next_build_value)
        n.addWidget(QLabel("Recommended location"))
        n.addWidget(self.next_location_value)
        n.addWidget(QLabel("Why"))
        n.addWidget(self.next_reason_value)
        focus_buttons = QHBoxLayout()
        self.set_next_current_button = QPushButton("Set This as Focus Build")
        self.set_next_current_button.clicked.connect(self.set_recommendation_as_current)
        self.undo_focus_button = QPushButton("Undo Focus")
        self.undo_focus_button.setToolTip("Restore the previous focus build if this was clicked by mistake.")
        self.undo_focus_button.clicked.connect(self.undo_focus_change)
        focus_buttons.addWidget(self.set_next_current_button)
        focus_buttons.addWidget(self.undo_focus_button)
        n.addLayout(focus_buttons)
        n.addStretch()

        current, c = self._box("Focus Build")
        self.current_build_value = QLabel("Not selected")
        self.current_build_value.setObjectName("constructionBigValue")
        self.current_location_value = QLabel("Not selected")
        c.addWidget(QLabel("Facility"))
        c.addWidget(self.current_build_value)
        c.addWidget(QLabel("Location"))
        c.addWidget(self.current_location_value)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        c.addWidget(QLabel("Progress"))
        c.addWidget(self.progress)
        c.addStretch()

        grid.addWidget(purpose, 0, 0)
        grid.addWidget(existing, 0, 1)
        grid.addWidget(next_box, 0, 2)
        grid.addWidget(current, 0, 3)
        for col in range(4):
            grid.setColumnStretch(col, 1)
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

        self.queue_notice = QLabel(
            "Recommendations come from data/colonisation_facilities.json and are assigned to the first free matching slot. "
            "Rows marked player_note/unverified still need in-game confirmation before being treated as guaranteed."
        )
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
        self.queue_focus_button.clicked.connect(self.set_selected_queue_as_current)
        self.queue_complete_button.clicked.connect(self.mark_selected_queue_complete)
        actions.addWidget(self.queue_focus_button)
        actions.addWidget(self.queue_complete_button)
        actions.addStretch()
        layout.addLayout(actions)
        return page

    def _build_materials_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)

        self.materials_notice = QLabel(
            "Depot progress shows what the build still needs. Paste the station/system you plan to buy from into Material Source."
        )
        self.materials_notice.setWordWrap(True)
        self.materials_notice.setObjectName("constructionNotice")
        layout.addWidget(self.materials_notice)

        toolbar = QHBoxLayout()
        self.materials_context = QLabel("Materials for: no focus build selected")
        self.materials_context.setObjectName("constructionNextBuild")
        self.ship_capacity_spin = QSpinBox()
        self.ship_capacity_spin.setRange(1, 50000)
        self.ship_capacity_spin.setSuffix(" t")
        self.add_material_button = QPushButton("Add Material Row")
        self.remove_material_button = QPushButton("Remove Selected")
        self.add_material_button.clicked.connect(self.add_material_row)
        self.remove_material_button.clicked.connect(self.remove_selected_material_row)
        self.ship_capacity_spin.valueChanged.connect(lambda _value: self._render_materials())
        toolbar.addWidget(self.materials_context, stretch=1)
        toolbar.addWidget(QLabel("Ship capacity"))
        toolbar.addWidget(self.ship_capacity_spin)
        toolbar.addWidget(self.add_material_button)
        toolbar.addWidget(self.remove_material_button)
        layout.addLayout(toolbar)

        self.materials_table = QTableWidget(0, 7)
        self.materials_table.setHorizontalHeaderLabels([
            "Commodity", "Required", "Delivered", "Carrier", "Still needed", "Ship trips", "Material Source"
        ])
        self.materials_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
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
        layout.addWidget(self.materials_table)
        return page

    @staticmethod
    def _int_cell(text: str) -> int:
        try:
            return max(0, int(str(text).replace(",", "").strip()))
        except (TypeError, ValueError):
            return 0

    def _focus_or_next_facility(self) -> Optional[FacilityData]:
        return (
            next((facility for facility in self.plan.facilities if facility.status == "Building now"), None)
            or next((facility for facility in self.plan.facilities if facility.status == "Queued"), None)
        )

    def _material_key_for(self, facility: Optional[FacilityData] = None) -> str:
        facility = facility or self._focus_or_next_facility()
        if facility is None:
            return "manual"
        return facility.facility_id or facility.role

    @staticmethod
    def _material_dict(row: MaterialData) -> dict[str, Any]:
        return {
            "commodity": row.commodity,
            "required": int(row.required),
            "delivered": int(row.delivered),
            "carrier": int(row.carrier),
            "source": row.source,
        }

    def _seed_materials_for(self, facility: Optional[FacilityData]) -> list[MaterialData]:
        if facility is None or not facility.facility_id:
            return []
        return [
            MaterialData(commodity=item.commodity, required=item.required)
            for item in CATALOG.material_requirements(facility.facility_id)
        ]

    def _stored_materials_for(self, facility: Optional[FacilityData]) -> list[MaterialData]:
        key = self._material_key_for(facility)
        stored = self.plan.materials_by_build.get(key, [])
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
                carrier=self._int_cell(row.get("carrier", 0)),
                source=str(row.get("source", "")),
            ))
        if rows:
            return rows
        if self.live_depot_resources:
            return list(self.live_depot_resources)
        return self._seed_materials_for(facility)

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
                carrier=self._int_cell(text(3)),
                source="" if text(6) == "Paste Location" else text(6),
            ))
        return rows

    def _store_material_edits(self) -> None:
        facility = self._focus_or_next_facility()
        key = self._material_key_for(facility)
        self.plan.materials_by_build[key] = [
            self._material_dict(row) for row in self._collect_material_edits()
        ]

    def add_material_row(self) -> None:
        row = self.materials_table.rowCount()
        self.materials_table.insertRow(row)
        for col, value in enumerate(["", "0", "0", "0", "0", "0", "Paste Location"]):
            item = QTableWidgetItem(value)
            if col in (4, 5):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.materials_table.setItem(row, col, item)

    def remove_selected_material_row(self) -> None:
        row = self.materials_table.currentRow()
        if row >= 0:
            self.materials_table.removeRow(row)


    @staticmethod
    def _is_placeholder_source(text: str) -> bool:
        return str(text or "").strip() in ("", "Paste Location", "Journal depot", "Waiting for journal depot or JSON")

    def on_material_item_changed(self, item: QTableWidgetItem) -> None:
        if self._rendering_materials or item is None:
            return
        # The source/location field is intentionally editable while the plan is
        # locked.  Save it immediately so a pasted station is not lost.
        if item.column() == 6:
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
        item = self.materials_table.item(row, 6)
        if item is None:
            return
        text = item.text().strip()
        if not self._is_placeholder_source(text):
            QApplication.clipboard().setText(text)

    def _render_materials(self) -> None:
        if not hasattr(self, "materials_table"):
            return
        facility = self._focus_or_next_facility()
        self.plan.ship_capacity_tons = self.ship_capacity_spin.value() if hasattr(self, "ship_capacity_spin") else self.plan.ship_capacity_tons
        capacity = max(1, int(self.plan.ship_capacity_tons or 1))
        rows = self._stored_materials_for(facility)

        live_label = ""
        if self.live_depot:
            station = self.live_depot.get("station") or "Construction depot"
            body = self.live_depot.get("body") or "Unknown body"
            live_label = f"  •  depot progress: {station} @ {body}"

        if facility is None:
            self.materials_context.setText("Materials for: no focus build selected" + live_label)
            self.materials_notice.setText(
                "Set a focus build first. Paste a buying station/system into Material Source after the material rows appear."
            )
        else:
            self.materials_context.setText(f"Materials for: {facility.role}  •  {facility.location}{live_label}")
            if self.live_depot_resources:
                self.materials_notice.setText(
                    "Using live depot progress for Required and Delivered. Paste where you will buy each commodity into Material Source."
                )
            elif rows:
                self.materials_notice.setText(
                    "Using the facility database material template. Paste where you will buy each commodity into Material Source."
                )
            else:
                self.materials_notice.setText(
                    f"No material template or live depot data is available for {facility.role}. "
                    "Visit/dock at the construction site once so Elite writes depot progress, or add the facility materials to the JSON database."
                )

        self._rendering_materials = True
        self.materials_table.setSortingEnabled(False)
        try:
            if not rows:
                self.materials_table.setRowCount(1)
                values = ["No material data yet", "", "", "", "", "", "Paste Location"]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if col == 6:
                        item.setBackground(QColor("#493710"))
                        item.setForeground(QColor("#F59E0B"))
                    else:
                        item.setForeground(QColor("#E4B65E"))
                    self.materials_table.setItem(0, col, item)
            else:
                self.materials_table.setRowCount(len(rows))
                for row, material in enumerate(rows):
                    left = material.still_needed
                    trips = (left + capacity - 1) // capacity if left else 0
                    source = material.source.strip() if material.source else "Paste Location"
                    values = [
                        material.commodity,
                        str(material.required),
                        str(material.delivered),
                        str(material.carrier),
                        str(left),
                        str(trips),
                        source,
                    ]
                    for col, value in enumerate(values):
                        item = QTableWidgetItem(value)
                        editable = self.editing and col in (0, 1, 2, 3, 6)
                        if not self.editing and col == 6:
                            editable = True
                        if col in (4, 5):
                            editable = False
                        if not editable:
                            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        if left > 0 and col in (0, 4, 5):
                            item.setForeground(QColor("#ffb000"))
                        if col == 6:
                            if self._is_placeholder_source(value):
                                item.setText("Paste Location")
                                item.setBackground(QColor("#493710"))
                                item.setForeground(QColor("#F59E0B"))
                            else:
                                # Bio-progress-like pill color: make saved sources stand out.
                                item.setBackground(QColor("#5B21B6"))
                                item.setForeground(QColor("#FFFFFF"))
                        self.materials_table.setItem(row, col, item)
        finally:
            self._rendering_materials = False
            self.materials_table.setSortingEnabled(True)

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
        self.lock_label.setText("Editing unlocked" if enabled else "Plan locked")
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
        if hasattr(self, "materials_table"):
            # Material Source stays editable even when the plan is locked,
            # because choosing where to buy commodities is an operational action.
            self.materials_table.setEditTriggers(QTableWidget.EditTrigger.AllEditTriggers)
            self._render_materials()
        if hasattr(self, "add_material_button"):
            self.add_material_button.setEnabled(enabled)
            self.remove_material_button.setEnabled(enabled)
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
        self.current_build_value.setText(self.plan.current_build)
        self.current_location_value.setText(self.plan.current_location)
        self.concurrent_spin.setValue(self.plan.concurrent_limit)
        if hasattr(self, "ship_capacity_spin"):
            self.ship_capacity_spin.setValue(self.plan.ship_capacity_tons or 1168)
        self._render_sites()
        self._render_queue()
        self._render_materials()
        self.set_editing(False)
        self.current_build_changed.emit(self.plan.current_build, self.plan.current_location)

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
        self.queue_table.setRowCount(len(rows))
        next_facility: Optional[FacilityData] = None
        for row, facility in enumerate(rows):
            if facility.status == "Queued" and next_facility is None:
                next_facility = facility
                action = "→ NEXT"
            elif facility.status == "Building now":
                action = "⚒ BUILDING"
            elif facility.status == "Complete":
                action = "✓ COMPLETE"
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
        self._apply_plan()

    def undo_focus_change(self) -> None:
        previous_build = self.plan.previous_current_build
        previous_location = self.plan.previous_current_location
        if not previous_build:
            return
        current_build = self.plan.current_build
        current_location = self.plan.current_location
        for facility in self.plan.facilities:
            if facility.role == current_build and facility.location == current_location:
                facility.status = "Queued"
            if facility.role == previous_build and facility.location == previous_location:
                facility.status = "Building now"
        self.plan.current_build = previous_build
        self.plan.current_location = previous_location or "Not selected"
        self.plan.previous_current_build = current_build if current_build != "Not selected" else ""
        self.plan.previous_current_location = current_location if current_location != "Not selected" else ""
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
        if self.plan.current_build == facility.role:
            self.plan.current_build = "Not selected"
            self.plan.current_location = "Not selected"
        self._save_plan()
        self._apply_plan()


    def focus_material_summary(self) -> tuple[str, str, str]:
        """Compact material status for construction mini mode."""
        facility = self._focus_or_next_facility()
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
