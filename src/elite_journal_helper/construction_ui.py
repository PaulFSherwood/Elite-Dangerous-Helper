from __future__ import annotations

import copy
import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional
from datetime import datetime, timedelta, timezone

from PyQt6.QtCore import Qt, QSettings, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QPen
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
    QMenu,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QSizePolicy,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .construction_rules import (
    ColonisationCatalog,
    FacilityDescriptor,
    FacilityPrerequisite,
    FacilityRef,
    MaterialRequirement,
    asteroid_location_available,
)
from .state import commodity_key


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
    "Local Construction Supplies",
]

OVERVIEW_COMPACT_WIDTH = 740


PLAN_SCOPES = [
    "Primary Goal Only",
    "Primary + Secondary Goals",
    "Goal-Directed Expansion",
    "Full System Build-Out",
]

LOCAL_MARKET_SOURCE_ROLE = int(Qt.ItemDataRole.UserRole) + 37


class LocalMaterialRowDelegate(QStyledItemDelegate):
    """Outline only actionable local-source rows.

    Local-source knowledge is retained after a material is stocked or delivered,
    but the strong purple cue is reserved for commodities the player still needs
    to acquire.  This keeps completed rows visually quiet.
    """

    def paint(self, painter, option, index) -> None:  # type: ignore[override]
        super().paint(painter, option, index)
        if not bool(index.data(LOCAL_MARKET_SOURCE_ROLE)):
            return

        painter.save()
        painter.setPen(QPen(QColor("#A855F7"), 2))
        rect = option.rect.adjusted(1, 1, -1, -1)
        painter.drawLine(rect.topLeft(), rect.topRight())
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        if index.column() == 0:
            painter.drawLine(rect.topLeft(), rect.bottomLeft())
        model = index.model()
        if model is not None and index.column() == model.columnCount() - 1:
            painter.drawLine(rect.topRight(), rect.bottomRight())
        painter.restore()


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
    # Asteroid-capable locations are a subset of orbital construction slots.
    # An Asteroid Base consumes one normal orbital slot *and* one asteroid slot.
    asteroid_used: int = 0
    asteroid_total: int = 0
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
    # Raw Elite journal ring records.  Asteroid Bases are not generic orbital
    # starports: Elite only offers them at planetary rings or asteroid/belt
    # clusters, so placement must retain this body metadata.
    rings: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MaterialData:
    commodity: str
    required: int = 0
    delivered: int = 0
    ship: int = 0
    carrier: int = 0
    source: str = ""

    @property
    def delivery_remaining(self) -> int:
        """Tonnage Elite still requires at the construction depot."""
        return max(0, int(self.required) - int(self.delivered))

    @property
    def still_needed(self) -> int:
        # The Materials table uses "Still needed" to mean *still to deliver*,
        # not still to buy. Ship/carrier stock is informational and must never
        # make an unfinished depot row look complete.
        return self.delivery_remaining

    @property
    def on_hand_for_build(self) -> int:
        """Owned cargo relevant to this build, capped at the depot shortfall."""
        owned = max(0, int(self.ship)) + max(0, int(self.carrier))
        return min(self.delivery_remaining, owned)

    @property
    def acquisition_needed(self) -> int:
        """Tonnage still to acquire after using current ship/carrier stock."""
        return max(0, self.delivery_remaining - self.on_hand_for_build)

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
    planned_location: str = ""
    location_confirmed: bool = False
    location_locked: bool = False
    deviation_note: str = ""
    logistics_target_body: str = ""
    station_name: str = ""
    market_id: str = ""
    station_type: str = ""
    journal_timestamp: str = ""

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
    plan_scope: str = "Goal-Directed Expansion"
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
    heavy_haul_logistics: bool = False
    mini_tracked_commodity: str = ""


class ConstructionPanel(QWidget):
    """Editable construction plan contained within the existing fixed-size UI."""

    current_build_changed = pyqtSignal(str, str)
    system_lock_changed = pyqtSignal(str, bool)
    carrier_empty_baseline_requested = pyqtSignal(object)
    activity_changed = pyqtSignal(bool)

    def __init__(
        self,
        settings: QSettings,
        parent: Optional[QWidget] = None,
        startup_profile: bool = False,
    ):
        profile_startup = bool(startup_profile)
        _init_started = time.perf_counter() if profile_startup else 0.0
        _init_last = _init_started

        def _trace(label: str) -> None:
            nonlocal _init_last
            if not profile_startup:
                return
            now = time.perf_counter()
            print(
                f"[construction-init +{now - _init_started:6.2f}s / +{now - _init_last:5.2f}s] {label}",
                flush=True,
            )
            _init_last = now

        super().__init__(parent)
        self.startup_profile = profile_startup
        self.settings = settings
        self.system_locked = self.settings.value("construction/system_locked", False, type=bool)
        self.locked_system_name = str(self.settings.value("construction/locked_system_name", "") or "")
        self.system_name = self.locked_system_name if self.system_locked and self.locked_system_name else "Unknown system"
        self.current_system_name = self.system_name
        self.plan = PlanData()
        self.editing = False
        # Edit Plan previews intentionally mutate the in-memory queue. Keep a
        # transaction snapshot so Cancel can restore the exact pre-edit plan
        # without regenerating the entire system build-out.
        self._edit_plan_snapshot: Optional[PlanData] = None
        self.live_depot: Optional[dict[str, Any]] = None
        self.live_depot_resources: list[MaterialData] = []
        self.ship_inventory: dict[str, int] = {}
        self.ship_inventory_known = False
        self.carrier_inventory: dict[str, int] = {}
        self.carrier_inventory_known = False
        self.carrier_known_commodities: set[str] = set()
        self.market_sources: dict[str, str] = {}
        self.market_sources_by_system: dict[str, dict[str, str]] = {}
        self.active_focus: dict[str, Any] = self._load_active_focus()
        self._rendering_materials = False
        self._overview_compact_mode: Optional[bool] = None

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
        _trace("Panel state/timers created")

        self._load_plan()
        _trace("Saved construction plan loaded/migrated")
        self._build_ui()
        _trace("Construction tabs/widgets created")
        # Do not run expensive planner reconciliation before the top-level
        # window has even had a chance to paint. The saved queue is already a
        # valid startup snapshot; live journal/system data schedules the normal
        # replan after Observatory is visible.
        self._apply_plan(reconcile_queue=False)
        _trace("Saved construction plan rendered")

    def _run_user_action(self, action: Callable[[], None]) -> None:
        """Run a player command with immediate visible activity feedback.

        Planner actions can synchronously regenerate several tables. Paint the
        warm/red busy background before that work starts so a long operation
        never looks like a dead click.
        """
        self.activity_changed.emit(True)
        QApplication.processEvents()
        try:
            action()
        finally:
            self.activity_changed.emit(False)

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
            changed = False
            # v3.1.2 changes the broad default from "fill every useful category"
            # to goal-directed expansion. Existing plans migrate to the safer
            # targeted behavior; Full System Build-Out remains opt-in.
            if self.plan.plan_scope == "Continue System Build-Out":
                self.plan.plan_scope = "Goal-Directed Expansion"
                changed = True
            elif self.plan.plan_scope not in PLAN_SCOPES:
                self.plan.plan_scope = "Goal-Directed Expansion"
                changed = True
            changed = self._clean_saved_site_facilities() or changed
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
            "planned_location": facility.planned_location,
            "location_confirmed": bool(facility.location_confirmed),
            "deviation_note": facility.deviation_note,
            "logistics_target_body": facility.logistics_target_body,
            "station_name": facility.station_name,
            "market_id": facility.market_id,
            "station_type": facility.station_type,
            "journal_timestamp": facility.journal_timestamp,
            "tracked_at_utc": str(self.active_focus.get("tracked_at_utc", "") or "")
            or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
            planned_location=str(self.active_focus.get("planned_location", "")),
            location_confirmed=bool(self.active_focus.get("location_confirmed", False)),
            deviation_note=str(self.active_focus.get("deviation_note", "")),
            logistics_target_body=str(self.active_focus.get("logistics_target_body", "")),
            station_name=str(self.active_focus.get("station_name", "")),
            market_id=str(self.active_focus.get("market_id", "")),
            station_type=str(self.active_focus.get("station_type", "")),
            journal_timestamp=str(self.active_focus.get("journal_timestamp", "")),
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
            ring_signature: list[tuple[str, str]] = []
            for ring in getattr(body, "rings", []) or []:
                if not isinstance(ring, dict):
                    continue
                ring_signature.append((
                    str(ring.get("Name", "") or ""),
                    str(ring.get("RingClass", "") or ""),
                ))
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
                tuple(ring_signature),
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
            rings = [dict(ring) for ring in (getattr(body, "rings", []) or []) if isinstance(ring, dict)]
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
                    site.parent_body, site.distance_ls, tuple(
                        (str(r.get("Name", "")), str(r.get("RingClass", "")))
                        for r in site.rings
                    ),
                )
                new_metadata = (
                    body_type, landable, body_id, radius_km, mass_em, atmosphere,
                    volcanism, parent_body, distance_ls, tuple(
                        (str(r.get("Name", "")), str(r.get("RingClass", "")))
                        for r in rings
                    ),
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
                    site.rings = rings
                    changed = True
                continue

            estimated_surface = self._estimate_surface_slots(body)
            is_asteroid_cluster = self._is_asteroid_cluster_text(name, body_type)
            # A ring or belt cluster makes Asteroid Base placement possible, but
            # it does not prove Architect mode actually supplied a construction
            # slot there.  Keep both orbital and asteroid capacity at zero until
            # the player confirms the visible slot counts in Edit Plan.
            confidence = "Asteroid-capable — confirm slots" if is_asteroid_cluster else (
                "Estimated from body data" if landable else "Journal body"
            )
            self.plan.sites.append(
                SiteData(
                    body=name,
                    body_type=body_type,
                    landable=landable,
                    orbital_total=0,
                    asteroid_total=0,
                    surface_total=estimated_surface,
                    confidence=confidence,
                    body_id=body_id,
                    mass_em=mass_em,
                    radius_km=radius_km,
                    atmosphere=atmosphere,
                    volcanism=volcanism,
                    parent_body=parent_body,
                    distance_ls=distance_ls,
                    rings=rings,
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

    @staticmethod
    def _depot_material_signature(rows: list[dict[str, Any]]) -> tuple[tuple[str, int], ...]:
        signature: list[tuple[str, int]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            key = commodity_key(row.get("commodity", ""))
            if not key:
                continue
            try:
                required = max(0, int(row.get("required", 0) or 0))
            except (TypeError, ValueError):
                required = 0
            if required:
                signature.append((key, required))
        return tuple(sorted(signature))

    def _saved_material_key_for_depot(self, depot: dict[str, Any]) -> str:
        """Return one unambiguous saved facility/material key for a depot."""
        wanted = self._depot_material_signature(depot.get("resources", []) or [])
        if not wanted:
            return ""
        matches: list[str] = []
        for key, rows in self.plan.materials_by_build.items():
            if self._depot_material_signature(rows or []) == wanted:
                matches.append(str(key))
        return matches[0] if len(matches) == 1 else ""

    def _facility_for_depot(self, depot: dict[str, Any]) -> Optional[FacilityData]:
        market_id = str(depot.get("market_id", "") or "")
        if market_id:
            direct = next((row for row in self.plan.facilities if row.market_id == market_id), None)
            if direct is not None:
                return direct

        material_key = self._saved_material_key_for_depot(depot)
        if material_key:
            row = next((
                item for item in self.plan.facilities
                if item.facility_id == material_key or item.role == material_key
            ), None)
            if row is not None:
                return row
            reference = CATALOG.facility(material_key)
            if reference is not None:
                recovered = FacilityData.from_reference(
                    reference,
                    "Recovered from Elite journal construction history; this physical site is authoritative.",
                )
                self.plan.facilities.append(recovered)
                return recovered

        station = str(depot.get("station", "") or "").strip()
        if station:
            by_station = [row for row in self.plan.facilities if row.station_name == station]
            if len(by_station) == 1:
                return by_station[0]
        return None

    @staticmethod
    def _depot_site_type(depot: dict[str, Any]) -> str:
        station_type = str(depot.get("station_type", "") or "").casefold()
        if any(word in station_type for word in ("planet", "surface", "settlement", "crater")):
            return "surface"
        return "orbital"

    def _apply_depot_identity(self, facility: FacilityData, depot: dict[str, Any]) -> bool:
        """Apply journal truth to one planner row without moving it again later."""
        before = asdict(facility)
        market_id = str(depot.get("market_id", "") or "")
        station = str(depot.get("station", "") or "").strip()
        body = str(depot.get("body", "") or "").strip()
        facility.market_id = market_id or facility.market_id
        facility.station_name = station or facility.station_name
        facility.station_type = str(depot.get("station_type", "") or facility.station_type)
        facility.journal_timestamp = str(depot.get("timestamp", "") or facility.journal_timestamp)

        if bool(depot.get("failed", False)):
            # A cancelled/destroyed construction site is journal history, but it is
            # not physical infrastructure and must not reserve a build slot.
            facility.status = "Skipped"
            facility.construction_started = False
            facility.location_confirmed = False
            facility.location_locked = False
            note = "Elite journal reports this construction site failed/was removed."
            if note not in facility.deviation_note:
                facility.deviation_note = (facility.deviation_note + "  " + note).strip()
            return asdict(facility) != before

        if body and not body.casefold().startswith("unknown"):
            self._record_actual_location(facility, body)
        facility.construction_started = True
        facility.location_confirmed = True
        facility.location_locked = True
        if bool(depot.get("complete", False)):
            facility.status = "Complete"
        else:
            facility.status = "Building now"
        return asdict(facility) != before

    @staticmethod
    def _is_temporary_construction_identity(
        station: str = "", station_type: str = "", role: str = ""
    ) -> bool:
        """Return True for Elite's temporary colonisation build scaffolding.

        Orbital/Planetary Construction Sites and the Colonisation Ship exist only
        while a permanent facility is being built.  They are useful journal
        evidence for matching a planned row, but must never become persistent
        facilities in the Build Queue themselves.
        """
        text = " ".join((str(station or ""), str(station_type or ""), str(role or ""))).casefold()
        compact = re.sub(r"[^a-z0-9$]+", "", text)
        return (
            "orbital construction site" in text
            or "planetary construction site" in text
            or "colonisation ship" in text
            or "colonization ship" in text
            or "$ext_panel_colonisationship" in text
            or "colonisationship" in compact
            or "colonizationship" in compact
        )

    def _remove_temporary_observed_rows(self) -> bool:
        """Remove v3.1.9 rows created from temporary construction scaffolding."""
        stale = [
            row for row in self.plan.facilities
            if row.confidence == "journal_observed"
            and self._is_temporary_construction_identity(
                row.station_name, row.station_type, row.role
            )
        ]
        if not stale:
            return False

        stale_ids = {row.facility_id for row in stale if row.facility_id}
        stale_roles = {row.role for row in stale}
        self.plan.facilities = [row for row in self.plan.facilities if row not in stale]
        for key in stale_ids:
            self.plan.materials_by_build.pop(key, None)

        if self.plan.current_build in stale_roles:
            self.plan.current_build = "Not selected"
            self.plan.current_location = "Not selected"
        active_id = str(self.active_focus.get("facility_id", "") or "")
        active_role = str(self.active_focus.get("build", "") or "")
        if active_id in stale_ids or active_role in stale_roles:
            self.active_focus = {}
            self.settings.remove("construction/active_focus")
            self._schedule_settings_sync()
        return True

    def _append_observed_depot(self, depot: dict[str, Any]) -> Optional[FacilityData]:
        """Keep unmatched permanent Elite sites visible instead of deleting reality."""
        if bool(depot.get("failed", False)):
            return None
        if self._is_temporary_construction_identity(
            str(depot.get("station", "") or ""),
            str(depot.get("station_type", "") or ""),
        ):
            return None
        market_id = str(depot.get("market_id", "") or "").strip()
        if not market_id:
            return None
        existing = next((row for row in self.plan.facilities if row.market_id == market_id), None)
        if existing is not None:
            return existing
        station = str(depot.get("station", "") or "").strip()
        body = str(depot.get("body", "") or "").strip()
        site_type = self._depot_site_type(depot)
        label = station or f"Market {market_id}"
        row = FacilityData(
            role=f"Observed station / {label}",
            reason=(
                "Observed in Elite journal history but not safely matched to a catalog layout. "
                "It is preserved so the planner cannot reuse or erase a real site."
            ),
            preferred_site=site_type,
            status="Complete" if bool(depot.get("complete", False)) else "Building now",
            facility_id=f"journal_observed_{market_id}",
            facility_type="Observed Station",
            category=str(depot.get("station_type", "") or "Unknown"),
            confidence="journal_observed",
            construction_started=True,
            location_confirmed=True,
            location_locked=True,
            station_name=station,
            market_id=market_id,
            station_type=str(depot.get("station_type", "") or ""),
            journal_timestamp=str(depot.get("timestamp", "") or ""),
        )
        if body and not body.casefold().startswith("unknown"):
            row.location = self._next_actual_location_on_body(body, site_type, row)
            row.planned_location = row.location
        self.plan.facilities.append(row)
        return row

    def _bind_fresh_focus_depot(self, candidates: list[dict[str, Any]]) -> bool:
        """Bind a newly placed Elite site to the currently tracked planner row."""
        facility = self._focus_facility()
        if facility is None or facility not in self.plan.facilities:
            return False
        if facility.market_id or facility.construction_started or facility.status == "Complete":
            return False
        tracked_text = str(self.active_focus.get("tracked_at_utc", "") or "")
        for depot in sorted(candidates, key=lambda row: str(row.get("timestamp") or ""), reverse=True):
            if bool(depot.get("failed", False)):
                continue
            depot_text = str(depot.get("timestamp", "") or "")
            if tracked_text and depot_text:
                try:
                    tracked_dt = datetime.fromisoformat(tracked_text.replace("Z", "+00:00"))
                    depot_dt = datetime.fromisoformat(depot_text.replace("Z", "+00:00"))
                    if depot_dt < tracked_dt - timedelta(seconds=5):
                        continue
                except ValueError:
                    pass
            # Prefer the planned body when available; a different body is still
            # accepted because the player may intentionally deviate in Elite.
            self._apply_depot_identity(facility, depot)
            resources = [row for row in depot.get("resources", []) or [] if isinstance(row, dict)]
            if resources:
                self.plan.materials_by_build[self._material_key_for(facility)] = [
                    self._material_dict(MaterialData(
                        commodity=str(row.get("commodity", "")),
                        required=self._int_cell(row.get("required", 0)),
                        delivered=self._int_cell(row.get("delivered", 0)),
                        source="",
                    ))
                    for row in resources if str(row.get("commodity", "")).strip()
                ]
            return True
        return False

    def _reconcile_construction_history(self, candidates: list[dict[str, Any]]) -> bool:
        """Merge journal-known permanent sites into the plan before replanning."""
        # Early v3.1.9 builds could persist Elite's temporary Orbital/Planetary
        # Construction Site rows as if they were completed colony facilities.
        # Drop those saved artifacts first; their depot records remain available
        # below to match/freeze the actual planned facility when possible.
        changed = self._remove_temporary_observed_rows()
        changed = self._bind_fresh_focus_depot(candidates) or changed
        matched_market_ids: set[str] = set()
        ordered = sorted(candidates, key=lambda row: str(row.get("timestamp") or ""))
        for depot in ordered:
            facility = self._facility_for_depot(depot)
            if facility is None:
                continue
            if self._apply_depot_identity(facility, depot):
                changed = True
            market_id = str(depot.get("market_id", "") or "")
            if market_id:
                matched_market_ids.add(market_id)

        for depot in ordered:
            market_id = str(depot.get("market_id", "") or "")
            if not market_id or market_id in matched_market_ids:
                continue
            if self._append_observed_depot(depot) is not None:
                changed = True

        # v3.1.8 could demote a real site to Queued when tracking another build.
        for facility in self.plan.facilities:
            if facility.construction_started and facility.status == "Queued":
                facility.status = "Building now"
                facility.location_locked = True
                changed = True
        return changed

    def _focus_depot(self, candidates: list[dict[str, Any]], facility: Optional[FacilityData]) -> Optional[dict[str, Any]]:
        if facility is None:
            return None
        if facility.market_id:
            match = next((
                depot for depot in candidates
                if str(depot.get("market_id", "") or "") == facility.market_id
            ), None)
            if match is not None:
                return match
        key = self._material_key_for(facility)
        signature = self._depot_material_signature(self.plan.materials_by_build.get(key, []) or [])
        if signature:
            matches = [
                depot for depot in candidates
                if self._depot_material_signature(depot.get("resources", []) or []) == signature
            ]
            if len(matches) == 1:
                return matches[0]
        return None

    def set_construction_depots(self, depots: dict[str, dict]) -> None:
        """Reconcile all Elite construction records, then feed the focused Materials view."""
        candidates: list[dict[str, Any]] = []
        for depot in (depots or {}).values():
            if not isinstance(depot, dict):
                continue
            depot_system = str(depot.get("system", "") or "").strip()
            if depot_system and depot_system != self.system_name:
                continue
            candidates.append(depot)
        if not candidates:
            return

        history_changed = self._reconcile_construction_history(candidates)
        if history_changed:
            self._save_plan()
            # Rebuild only future/unbuilt rows around the newly authoritative sites.
            self._regenerate_facilities()
            self._render_queue()

        facility = self._focus_facility()
        depot = self._focus_depot(candidates, facility)
        if depot is None:
            return

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
            source = str(saved.get("source", ""))
            if key and source and not self._is_placeholder_source(source):
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
                source=saved_sources.get(key, ""),
            ))

        previous_key = self.live_depot.get("market_id") if isinstance(self.live_depot, dict) else None
        next_key = depot.get("market_id")
        previous_signature = [(row.commodity, row.required, row.delivered) for row in self.live_depot_resources]
        next_signature = [(row.commodity, row.required, row.delivered) for row in resources]
        depot_changed = previous_key != next_key or previous_signature != next_signature
        self.live_depot = depot
        self.live_depot_resources = resources

        if facility is not None and resources:
            key = self._material_key_for(facility)
            self.plan.materials_by_build[key] = [self._material_dict(row) for row in resources]
            self._save_plan()
            if facility.status != "Complete":
                self._save_active_focus_record(facility, resources)

        if facility is not None and facility.status == "Complete":
            if self.plan.current_build == facility.role:
                self.plan.current_build = "Not selected"
                self.plan.current_location = "Not selected"
            if self._is_active_focus_facility(facility):
                self.active_focus = {}
                self.settings.remove("construction/active_focus")
            self._save_plan()
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
        market_sources_by_system: dict[str, dict[str, str]],
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
        next_sources_by_system: dict[str, dict[str, str]] = {}
        for name, systems in (market_sources_by_system or {}).items():
            key = commodity_key(name)
            if not key or not isinstance(systems, dict):
                continue
            cleaned = {
                str(system).strip(): str(station).strip()
                for system, station in systems.items()
                if str(system).strip() and str(station).strip()
            }
            if cleaned:
                next_sources_by_system[key] = cleaned
        next_known = bool(carrier_inventory_known)
        next_ship_known = bool(ship_inventory_known)

        if (
            next_ship == self.ship_inventory
            and next_ship_known == self.ship_inventory_known
            and next_inventory == self.carrier_inventory
            and next_known_commodities == self.carrier_known_commodities
            and next_sources == self.market_sources
            and next_sources_by_system == self.market_sources_by_system
            and next_known == self.carrier_inventory_known
        ):
            return

        self.ship_inventory = next_ship
        self.ship_inventory_known = next_ship_known
        self.carrier_inventory = next_inventory
        self.carrier_known_commodities = next_known_commodities
        self.market_sources = next_sources
        self.market_sources_by_system = next_sources_by_system
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
        tab_started = time.perf_counter() if self.startup_profile else 0.0
        self.tabs.addTab(self._build_overview_tab(), "Overview")
        if self.startup_profile:
            print(
                f"[construction-tabs] Overview widgets: {time.perf_counter() - tab_started:.2f}s",
                flush=True,
            )
            tab_started = time.perf_counter()
        self.tabs.addTab(self._build_queue_tab(), "Build Queue")
        if self.startup_profile:
            print(
                f"[construction-tabs] Build Queue widgets: {time.perf_counter() - tab_started:.2f}s",
                flush=True,
            )
            tab_started = time.perf_counter()
        self.tabs.addTab(self._build_materials_tab(), "Materials")
        if self.startup_profile:
            print(
                f"[construction-tabs] Materials widgets: {time.perf_counter() - tab_started:.2f}s",
                flush=True,
            )
            tab_started = time.perf_counter()
        self.tabs.addTab(self._build_sites_tab(), "System Layout")
        if self.startup_profile:
            print(
                f"[construction-tabs] System Layout widgets: {time.perf_counter() - tab_started:.2f}s",
                flush=True,
            )
        outer.addWidget(self.tabs, stretch=1)

        self.edit_button.clicked.connect(lambda: self._run_user_action(lambda: self.set_editing(True)))
        self.cancel_button.clicked.connect(lambda: self._run_user_action(self.cancel_edits))
        self.save_button.clicked.connect(lambda: self._run_user_action(self.save_edits))
        self.primary_combo.currentTextChanged.connect(
            lambda text: self._run_user_action(lambda: self._preview_queue(text))
        )
        self.secondary_combo.currentTextChanged.connect(
            lambda text: self._run_user_action(lambda: self._preview_queue(text))
        )
        self.plan_scope_combo.currentTextChanged.connect(
            lambda text: self._run_user_action(lambda: self._preview_queue(text))
        )

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
        p.setSpacing(4)
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
        self.overview_goal_summary.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.overview_scope_summary = QLabel("")
        self.overview_scope_summary.setObjectName("constructionMuted")
        self.overview_scope_summary.setWordWrap(True)
        self.overview_scope_summary.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        # Narrow windows use individual summary rows rather than forcing the
        # maximised-window sentence layout to wrap into itself.  Keeping these
        # as separate labels gives Qt a real height hint for each row and avoids
        # clipped/overlapping text without shrinking the font.
        self.overview_primary_compact = QLabel("")
        self.overview_secondary_compact = QLabel("")
        self.overview_next_compact = QLabel("")
        self.overview_logistics_compact = QLabel("")
        self.overview_primary_compact.setObjectName("constructionGoalSummary")
        self.overview_secondary_compact.setObjectName("constructionGoalSummary")
        self.overview_next_compact.setObjectName("constructionMuted")
        self.overview_logistics_compact.setObjectName("constructionMuted")
        for label in (
            self.overview_primary_compact,
            self.overview_secondary_compact,
            self.overview_next_compact,
            self.overview_logistics_compact,
        ):
            label.setWordWrap(True)
            label.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
            label.hide()
        self.overview_workflow_hint = QLabel(
            "Daily workflow: Build Queue → Track NEXT Build → Materials. "
            "Use Edit Plan only to change goals; use System Layout for slot capacity or existing facilities."
        )
        self.overview_workflow_hint.setObjectName("constructionWorkflowHint")
        self.overview_workflow_hint.setWordWrap(True)
        # This paragraph competed with the actual plan status in a normal-height
        # window. Keep the guidance as an Edit Plan tooltip instead of consuming
        # permanent dashboard real estate.
        self.overview_workflow_hint.hide()
        self.overview_edit_button = QPushButton("Edit Plan")
        self.overview_edit_button.setToolTip(self.overview_workflow_hint.text())
        self.overview_edit_button.setObjectName("constructionPrimaryAction")
        self.overview_edit_button.clicked.connect(
            lambda: self._run_user_action(lambda: self.set_editing(True))
        )

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
        p.addWidget(self.overview_primary_compact)
        p.addWidget(self.overview_secondary_compact)
        p.addWidget(self.overview_next_compact)
        p.addWidget(self.overview_logistics_compact)
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
        self.heavy_haul_check = QCheckBox("Prefer large-pad hubs for heavy hauling")
        self.heavy_haul_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.heavy_haul_check.setToolTip(
            "Prioritise large-pad Starports/Planetary Ports near established economy clusters. "
            "Small and medium ports may still be planned when they provide construction points, "
            "prerequisites, or a distinct system function."
        )
        self.heavy_haul_check.toggled.connect(
            lambda _checked: self._run_user_action(lambda: self._preview_queue(""))
        )
        goal_grid.addWidget(self.heavy_haul_check, 3, 0, 1, 3)
        self.plan_edit_hint = QLabel(
            "Change goals/scope here. Port corrections and point calibration are under Advanced setup."
        )
        self.plan_edit_hint.setObjectName("constructionWorkflowHint")
        self.plan_edit_hint.setWordWrap(True)
        goal_grid.addWidget(self.plan_edit_hint, 4, 0, 1, 3)
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
        self.undo_focus_button.clicked.connect(lambda: self._run_user_action(self.undo_focus_change))
        c.addWidget(self.undo_focus_button)
        c.addStretch()

        next_box, n = self._box("Next Recommended Build")
        self.next_build_value = QLabel("No recommendation yet")
        self.next_build_value.setObjectName("constructionBigValue")
        self.next_build_value.setWordWrap(True)
        self.next_location_value = QLabel("Enter body slot counts on System Layout")
        self.next_location_value.setWordWrap(True)
        self.next_reason_value = QLabel("")
        self.next_reason_value.setWordWrap(True)
        # Keep the locked Overview readable at the minimum supported height.
        # The concise first sentence is displayed; the complete planner reason
        # remains available on hover.
        self.next_reason_value.setMaximumHeight(42)
        n.addWidget(self.next_build_value)
        n.addWidget(QLabel("Recommended location"))
        n.addWidget(self.next_location_value)
        n.addWidget(QLabel("Why"))
        n.addWidget(self.next_reason_value)
        self.set_next_current_button = QPushButton("Track NEXT Build")
        self.set_next_current_button.setToolTip("Track the recommended build for materials. This does not start construction in Elite.")
        self.set_next_current_button.clicked.connect(
            lambda: self._run_user_action(self.set_recommendation_as_current)
        )
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
        self.site_summary = QLabel("System layout is calculated from the rows below.")
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
            "During Edit Plan, correct used/total slots or add facilities that already existed before Observatory. "
            "Asteroid is the ring/belt subset of Orbital capacity: an Asteroid Base needs one free slot in both columns."
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
        self.add_existing_facility_button.clicked.connect(
            lambda: self._run_user_action(self.add_existing_facility_to_selected_site)
        )
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

        self.sites_table = QTableWidget(0, 8)
        self.sites_table.setHorizontalHeaderLabels([
            "Body / location",
            "Type",
            "Landable",
            "Orbital used/total",
            "Asteroid used/total",
            "Surface used/total",
            "Builds on this body",
            "Confidence",
        ])
        asteroid_header = self.sites_table.horizontalHeaderItem(4)
        if asteroid_header is not None:
            asteroid_header.setToolTip(
                "Asteroid-capable orbital slots shown by Elite Architect mode. "
                "Do not count every ring automatically; an Asteroid Base consumes one Asteroid slot and one Orbital slot."
            )
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
        self.queue_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_table.customContextMenuRequested.connect(self._show_queue_context_menu)
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
        self.queue_location_button = QPushButton("Change Location…")
        self.queue_location_button.setToolTip(
            "Correct a planned or actual body/slot. Observatory validates surface/orbit type and replans around the change."
        )
        self.queue_next_button.clicked.connect(lambda: self._run_user_action(self.set_recommendation_as_current))
        self.queue_focus_button.clicked.connect(lambda: self._run_user_action(self.set_selected_queue_as_current))
        self.queue_complete_button.clicked.connect(lambda: self._run_user_action(self.mark_selected_queue_complete))
        self.queue_skip_button.clicked.connect(lambda: self._run_user_action(self.skip_selected_queue_item))
        self.queue_location_button.clicked.connect(lambda: self._run_user_action(self.change_selected_queue_location))
        actions.addWidget(self.queue_next_button)
        actions.addWidget(self.queue_focus_button)
        actions.addWidget(self.queue_complete_button)
        actions.addWidget(self.queue_skip_button)
        actions.addWidget(self.queue_location_button)
        actions.addStretch()
        layout.addLayout(actions)
        return page

    def _build_materials_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Keep the operational Materials view table-first.  The build identity and
        # whole-job totals share one compact line instead of consuming a large
        # "Next Haul" card above the table.
        context_row = QHBoxLayout()
        context_row.setContentsMargins(0, 0, 0, 0)
        context_row.setSpacing(12)
        self.materials_context = QLabel("No build is being tracked")
        self.materials_context.setObjectName("constructionNextBuild")
        self.materials_context.setWordWrap(False)
        self.materials_summary = QLabel("")
        self.materials_summary.setObjectName("constructionMuted")
        self.materials_summary.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.materials_summary.setWordWrap(False)
        context_row.addWidget(self.materials_context, stretch=3)
        context_row.addWidget(self.materials_summary, stretch=2)
        layout.addLayout(context_row)

        self.materials_table = QTableWidget(0, 8)
        self.materials_table.setHorizontalHeaderLabels([
            "Commodity", "Required", "Delivered", "Ship", "Carrier", "To Deliver", "Ship trips", "Material Source"
        ])
        header = self.materials_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSortIndicatorShown(True)
        self.materials_table.verticalHeader().setVisible(False)
        self.materials_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.materials_table.setItemDelegate(LocalMaterialRowDelegate(self.materials_table))
        self.materials_table.itemChanged.connect(self.on_material_item_changed)
        self.materials_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.materials_table.customContextMenuRequested.connect(self._show_materials_context_menu)
        self.materials_table.setToolTip(
            "Amber = still need to acquire • Green = already on ship/carrier, just deliver • "
            "Purple outline = local source • Blue source = last purchase • Gray = delivered • "
            "Right-click a commodity to track it in Mini Mode"
        )
        self.copy_material_source_action = QAction("Copy Material Source", self.materials_table)
        self.copy_material_cell_action = QAction("Copy Cell", self.materials_table)
        self.copy_material_source_action.triggered.connect(self.copy_selected_material_source)
        self.copy_material_cell_action.triggered.connect(self.copy_selected_material_cell)
        self._materials_sort_initialized = False
        layout.addWidget(self.materials_table, stretch=1)

        # Status/calibration controls belong in the footer.  The carrier-empty
        # recovery button is only shown when carrier tracking is not ready.
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        self.logistics_status_label = QLabel("Ship cargo: update pending • Carrier cargo: update pending")
        self.logistics_status_label.setObjectName("constructionMuted")
        self.set_carrier_empty_button = QPushButton("Set Carrier Empty")
        self.set_carrier_empty_button.setToolTip(
            "Use after the carrier has zero of every commodity listed for this construction build."
        )
        self.set_carrier_empty_button.clicked.connect(
            lambda: self._run_user_action(self.mark_tracked_carrier_empty)
        )
        self.set_carrier_empty_button.hide()
        self.ship_capacity_spin = QSpinBox()
        self.ship_capacity_spin.setRange(1, 50000)
        self.ship_capacity_spin.setSuffix(" T")
        self.add_material_button = QPushButton("Add Material Row")
        self.remove_material_button = QPushButton("Remove Selected")
        self.add_material_button.clicked.connect(lambda: self._run_user_action(self.add_material_row))
        self.remove_material_button.clicked.connect(
            lambda: self._run_user_action(self.remove_selected_material_row)
        )
        self.ship_capacity_spin.valueChanged.connect(
            lambda _value: self._run_user_action(self._render_materials)
        )
        footer.addWidget(self.logistics_status_label)
        footer.addWidget(self.set_carrier_empty_button)
        footer.addStretch()
        footer.addWidget(QLabel("Ship capacity"))
        footer.addWidget(self.ship_capacity_spin)
        footer.addWidget(self.add_material_button)
        footer.addWidget(self.remove_material_button)
        layout.addLayout(footer)
        return page

    @staticmethod
    def _int_cell(text: str) -> int:
        try:
            return max(0, int(str(text).replace(",", "").strip()))
        except (TypeError, ValueError):
            return 0

    def _focus_facility(self) -> Optional[FacilityData]:
        # Multiple Elite construction sites may be active at once.  Material focus
        # is a separate concept: prefer the explicitly tracked plan row instead of
        # whichever Building-now row happens to appear first in the queue.
        if self.plan.current_build and self.plan.current_build != "Not selected":
            exact = next((
                facility for facility in self.plan.facilities
                if facility.role == self.plan.current_build
                and facility.location == self.plan.current_location
            ), None)
            if exact is not None:
                return exact
            by_role = next((
                facility for facility in self.plan.facilities
                if facility.role == self.plan.current_build
            ), None)
            if by_role is not None:
                return by_role
        active = self._active_focus_facility()
        if active is not None:
            if active.market_id:
                matched = next((
                    facility for facility in self.plan.facilities
                    if facility.market_id == active.market_id
                ), None)
                if matched is not None:
                    return matched
            return active
        return None

    def _focus_or_next_facility(self) -> Optional[FacilityData]:
        focus = self._focus_facility()
        if focus is not None:
            return focus
        return self._next_buildable_facility()

    def _is_active_focus_facility(self, facility: Optional[FacilityData]) -> bool:
        if facility is None or not self.active_focus:
            return False
        active_market = str(self.active_focus.get("market_id", "") or "")
        if active_market and facility.market_id and active_market == facility.market_id:
            return True
        active_id = str(self.active_focus.get("facility_id", "") or "")
        if active_id and facility.facility_id and active_id == facility.facility_id:
            return True
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

    @staticmethod
    def _normalise_system_name(name: str) -> str:
        return " ".join(str(name or "").split()).casefold()

    def _local_market_source(self, key: str) -> str:
        """Return a known station selling this commodity in the build system."""
        wanted = self._normalise_system_name(self.focus_system_name())
        if not wanted or wanted == "unknown system":
            return ""
        systems = self.market_sources_by_system.get(key, {})
        for system, station in systems.items():
            if self._normalise_system_name(system) == wanted and str(station).strip():
                return str(station).strip()
        return ""

    def _material_source_info(self, key: str, saved_source: str) -> tuple[str, bool, bool]:
        """Choose source text with local colony markets taking priority.

        Returns (source, is_local, is_auto_external).  A known local market stays
        pinned even after buying the same commodity elsewhere.  Otherwise the
        latest MarketBuy source replaces stale automatic/legacy source names.
        """
        local = self._local_market_source(key) if key else ""
        if local:
            return local, True, False

        recent = str(self.market_sources.get(key, "") or "").strip() if key else ""
        if recent:
            return recent, False, True

        source = str(saved_source or "").strip()
        return source, False, False

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

            source, _is_local, _is_auto_external = self._material_source_info(key, row.source)

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
            def save_source_change() -> None:
                self._store_material_edits()
                self._save_plan()
                self._render_materials()
            self._run_user_action(save_source_change)

    def _show_materials_context_menu(self, pos) -> None:
        """Show explicit Material actions for the row the player right-clicked."""
        item = self.materials_table.itemAt(pos)
        if item is not None:
            self.materials_table.setCurrentItem(item)
            self.materials_table.selectRow(item.row())

        menu = QMenu(self.materials_table)
        track_action = None
        clear_tracking_action = None
        row = self.materials_table.currentRow()
        commodity = ""
        if row >= 0:
            commodity_item = self.materials_table.item(row, 0)
            commodity = commodity_item.text().strip() if commodity_item is not None else ""
            if commodity and not commodity.startswith("No material"):
                tracked_key = commodity_key(self.plan.mini_tracked_commodity)
                commodity_is_tracked = bool(tracked_key and tracked_key == commodity_key(commodity))
                if commodity_is_tracked:
                    tracking_label = menu.addAction(f"✓ {commodity} is tracked in Mini Mode")
                    tracking_label.setEnabled(False)
                else:
                    track_action = menu.addAction(f"Track {commodity} in Mini Mode")

        if self.plan.mini_tracked_commodity:
            clear_tracking_action = menu.addAction("Use Automatic Mini Commodity")

        if menu.actions():
            menu.addSeparator()
        menu.addAction(self.copy_material_source_action)
        menu.addAction(self.copy_material_cell_action)

        chosen = menu.exec(self.materials_table.viewport().mapToGlobal(pos))
        if chosen is track_action and commodity:
            self.plan.mini_tracked_commodity = commodity
            self._save_plan()
            self._render_materials()
        elif chosen is clear_tracking_action:
            self.plan.mini_tracked_commodity = ""
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
        delivery_needed = sorted(
            (row for row in rows if row.delivery_remaining > 0),
            key=lambda row: row.delivery_remaining,
            reverse=True,
        )
        acquisition_needed = sorted(
            (row for row in delivery_needed if row.acquisition_needed > 0),
            key=lambda row: row.acquisition_needed,
            reverse=True,
        )

        if acquisition_needed:
            material = acquisition_needed[0]
            capacity = max(1, int(self.plan.ship_capacity_tons or 1))
            trips = (material.delivery_remaining + capacity - 1) // capacity
            source = material.source.strip() if material.source else "Paste Location"
            if self._is_placeholder_source(source):
                source = "Paste Location"
            return (
                f"Haul {material.commodity}",
                f"{material.delivery_remaining:,} t still needs depot delivery • "
                f"{material.acquisition_needed:,} t still needs to be acquired • "
                f"{trips} delivery trip{'s' if trips != 1 else ''}",
                source,
                progress,
            )

        if delivery_needed:
            remaining_delivery = sum(row.delivery_remaining for row in delivery_needed)
            stocked_for_build = sum(row.on_hand_for_build for row in delivery_needed)
            return (
                "Deliver stocked materials",
                f"{remaining_delivery:,} t still needs depot delivery • "
                f"{stocked_for_build:,} t of that amount is on ship/carrier",
                "No source needed",
                progress,
            )

        if rows:
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

    def _material_source_visual_kind(self, source: str) -> str:
        """Return a compact UI classification for a displayed material source."""
        text = str(source or "").strip()
        if self._is_placeholder_source(text):
            return "missing"
        if text == "No source needed":
            return "none"

        wanted = self._normalise_system_name(self.focus_system_name())
        if wanted and wanted != "unknown system":
            for systems in self.market_sources_by_system.values():
                if not isinstance(systems, dict):
                    continue
                for system, station in systems.items():
                    if (
                        self._normalise_system_name(system) == wanted
                        and str(station or "").strip() == text
                    ):
                        return "local"

        if any(str(station or "").strip() == text for station in self.market_sources.values()):
            return "external"
        return "manual"

    @staticmethod
    def _apply_source_pill_kind(label: QLabel, kind: str, missing: bool) -> None:
        label.setProperty("sourceKind", kind)
        label.setProperty("missing", "true" if missing else "false")
        label.style().unpolish(label)
        label.style().polish(label)

    @staticmethod
    def _compact_phase_text(text: str) -> str:
        """Short phase wording for the constrained Edit Plan grid."""
        value = str(text or "")
        replacements = (
            ("Full System Build-Out — next stage: ", "Next: "),
            ("Goal-Directed Expansion — next capability: ", "Next: "),
            ("Selected goals — ", "Goals: "),
            ("Selected goals complete — ", "Goals complete — "),
        )
        for prefix, short in replacements:
            if value.startswith(prefix):
                return short + value[len(prefix):]
        return value

    def _apply_overview_summary_visibility(self) -> None:
        """Show the wide or compact Build System summary for the current width."""
        if not hasattr(self, "overview_goal_summary"):
            return
        show_summary = not self.editing
        compact = bool(self._overview_compact_mode)
        self.overview_goal_summary.setVisible(show_summary and not compact)
        self.overview_scope_summary.setVisible(show_summary and not compact)
        self.overview_primary_compact.setVisible(show_summary and compact)
        self.overview_secondary_compact.setVisible(show_summary and compact)
        self.overview_next_compact.setVisible(show_summary and compact)
        self.overview_logistics_compact.setVisible(
            show_summary and compact and bool(self.overview_logistics_compact.text().strip())
        )

    def _update_overview_responsive_mode(self, width: Optional[int] = None) -> None:
        if not hasattr(self, "overview_goal_summary"):
            return
        panel_width = int(self.width() if width is None else width)
        compact = panel_width < OVERVIEW_COMPACT_WIDTH
        if self._overview_compact_mode == compact:
            return
        self._overview_compact_mode = compact
        self._apply_overview_summary_visibility()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_overview_responsive_mode(event.size().width())

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
        self.plan_phase_status.setText(
            self._compact_phase_text(phase_text) if self.editing else phase_text
        )
        self.overview_goal_summary.setText(
            f"Primary: {effective_primary} — {primary_text}\n"
            f"Secondary: {effective_secondary} — {secondary_text}"
        )
        heavy_haul = self._effective_heavy_haul_logistics()
        logistics_text = "  •  Logistics: Heavy-haul hubs" if heavy_haul else ""
        compact_phase = self._compact_phase_text(phase_text)
        self.overview_scope_summary.setText(
            f"Scope: {effective_scope}  •  {compact_phase}{logistics_text}"
        )
        summary_tooltip = f"Scope: {effective_scope}\nPhase: {phase_text}{logistics_text}"
        self.overview_scope_summary.setToolTip(summary_tooltip)

        # At companion-window widths, remove the requirement fractions and give
        # each important fact its own row. Scope remains available in the tooltip
        # because the player is already looking at the Build System panel.
        primary_compact = primary_text.split(" — ", 1)[0]
        secondary_compact = secondary_text.split(" — ", 1)[0]
        phase_line = compact_phase if compact_phase.startswith("Next:") else f"Phase: {compact_phase}"
        self.overview_primary_compact.setText(
            f"Primary: {effective_primary} — {primary_compact}"
        )
        self.overview_secondary_compact.setText(
            f"Secondary: {effective_secondary} — {secondary_compact}"
        )
        self.overview_next_compact.setText(phase_line)
        self.overview_next_compact.setToolTip(summary_tooltip)
        self.overview_logistics_compact.setText(
            "Logistics: Heavy-haul hubs" if heavy_haul else ""
        )
        self._update_overview_responsive_mode()
        self._apply_overview_summary_visibility()

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
        source_kind = self._material_source_visual_kind(source)
        self._apply_source_pill_kind(self.next_action_source, source_kind, source_missing)
        self.copy_next_source_button.setEnabled(source_available)

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

        tracked_keys = {commodity_key(row.commodity) for row in rows if commodity_key(row.commodity)}
        carrier_ready = bool(tracked_keys) and all(self._carrier_key_known(key) for key in tracked_keys)

        required_total = sum(max(0, int(row.required)) for row in rows)
        delivered_total = sum(
            min(max(0, int(row.delivered)), max(0, int(row.required))) for row in rows
        )
        remaining_total = sum(row.delivery_remaining for row in rows)
        progress = int((delivered_total * 100) / required_total) if required_total else 0
        estimated_trips = sum(
            (row.delivery_remaining + capacity - 1) // capacity
            for row in rows
            if row.delivery_remaining > 0
        )
        ship_total = sum(max(0, int(row.ship)) for row in rows)
        carrier_total = sum(max(0, int(row.carrier)) for row in rows)

        if facility is None:
            self.materials_context.setText(
                f"No build is being tracked • Build system: {self.display_system_name()}"
            )
            self.materials_summary.setText("")
        else:
            location = self._queue_display_location(facility.location)
            self.materials_context.setText(f"BUILDING: {facility.role}  •  {location}")
            ship_text = f"{ship_total:,} T" if self.ship_inventory_known else "pending"
            carrier_text = f"{carrier_total:,} T" if carrier_ready else "pending"
            self.materials_summary.setText(
                "Ship: " + ship_text
                + "  |  Carrier: " + carrier_text
                + f"  |  <span style='color:#F59E0B'>Remaining: {remaining_total:,} t</span>"
                + f"  |  <span style='color:#F59E0B'>Trips (est.): {estimated_trips:,}</span>"
                + f"  |  <span style='color:#F59E0B'>Progress: {progress}%</span>"
            )

        ship_status = "synced" if self.ship_inventory_known else "UPDATE PENDING"
        carrier_status = "✓ tracking" if carrier_ready else "UPDATE PENDING"
        if hasattr(self, "logistics_status_label"):
            self.logistics_status_label.setText(
                f"Ship cargo: {ship_status} • Carrier cargo: {carrier_status}"
            )
            self.logistics_status_label.setToolTip(
                "Ship cargo comes from Cargo.json. Carrier cargo is maintained from "
                "a zero baseline plus CargoTransfer journal events."
            )
        if hasattr(self, "set_carrier_empty_button"):
            show_carrier_reset = bool(tracked_keys) and not carrier_ready
            self.set_carrier_empty_button.setVisible(show_carrier_reset)
            self.set_carrier_empty_button.setEnabled(show_carrier_reset)

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
                    local_source = self._local_market_source(key)
                    is_local_source = bool(local_source and source == local_source)
                    auto_external_source = str(self.market_sources.get(key, "") or "").strip()
                    is_auto_external = bool(
                        not is_local_source and auto_external_source and source == auto_external_source
                    )
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

                        acquisition_needed = material.acquisition_needed
                        stocked_for_delivery = left > 0 and acquisition_needed == 0

                        if left <= 0:
                            # Depot-complete rows should visually disappear into the background.
                            item.setForeground(QColor("#6F7B85"))
                            item.setBackground(QColor("#101A22"))
                            item.setToolTip("Delivered to the construction depot. No action needed.")
                        elif stocked_for_delivery:
                            # The depot still needs this tonnage, but the commander already owns
                            # enough on ship/carrier.  Green means: do not go shopping for it.
                            item.setBackground(QColor("#10261C"))
                            item.setForeground(QColor("#B7C9BF"))
                            if col in (0, 4, 5, 6):
                                item.setForeground(QColor("#72D69B"))
                            item.setToolTip(
                                f"All {left:,} t still required by the depot is already on ship/carrier. "
                                "No purchase is needed; just deliver it."
                            )
                        else:
                            # Amber means there is still material the commander must acquire.
                            item.setBackground(QColor("#241D0D"))
                            item.setForeground(QColor("#E6EDF3"))
                            if col in (0, 5, 6):
                                item.setForeground(QColor("#ffb000"))

                        if col == 4 and not carrier_known:
                            item.setForeground(QColor("#F59E0B"))
                        if col == 3 and not self.ship_inventory_known:
                            item.setForeground(QColor("#F59E0B"))

                        source_actionable = acquisition_needed > 0
                        local_actionable = bool(is_local_source and source_actionable)
                        item.setData(LOCAL_MARKET_SOURCE_ROLE, local_actionable)
                        if is_local_source:
                            if source_actionable:
                                item.setToolTip(
                                    f"Available locally in {self.focus_system_name()} at {local_source}."
                                )
                            else:
                                item.setToolTip(
                                    f"Known local source retained: {local_source}. "
                                    "No additional purchase is needed for this build."
                                )

                        if col == 7:
                            # Source colours are action cues, not permanent labels.  Once the
                            # required amount is already on hand or delivered, keep the useful
                            # station name but let the row fall back to the normal muted styling.
                            if not source_actionable:
                                if self._is_placeholder_source(value):
                                    item.setText("Paste Location")
                                if left == 0:
                                    item.setBackground(QColor("#101A22"))
                                    item.setForeground(QColor("#6F7B85"))
                                else:
                                    # Keep the source text for reference, but match the stocked
                                    # row's green action state instead of making it look like a shortage.
                                    item.setBackground(QColor("#10261C"))
                                    item.setForeground(QColor("#8FB5A0"))
                                if not self._is_placeholder_source(value):
                                    item.setToolTip(
                                        f"Source retained for reference: {value}. "
                                        "No additional purchase is needed for this build."
                                    )
                            elif self._is_placeholder_source(value):
                                item.setText("Paste Location")
                                item.setBackground(QColor("#493710"))
                                item.setForeground(QColor("#F59E0B"))
                                item.setToolTip(
                                    "No source is known yet. Visit a commodity market or paste a location."
                                )
                            elif is_local_source:
                                item.setBackground(QColor("#211A2E"))
                                item.setForeground(QColor("#D8B4FE"))
                                item.setToolTip(
                                    f"LOCAL SOURCE • {self.focus_system_name()} • {source}. "
                                    "Local sources stay preferred even if you later buy elsewhere."
                                )
                            elif is_auto_external:
                                item.setBackground(QColor("#123047"))
                                item.setForeground(QColor("#BAE6FD"))
                                item.setToolTip(
                                    "Last station where this commodity was bought. "
                                    "This updates automatically on the next purchase unless a local source is known."
                                )
                            else:
                                item.setBackground(QColor("#27313D"))
                                item.setForeground(QColor("#E6EDF3"))
                                item.setToolTip(
                                    "Manual/legacy source. A local market or a future purchase can replace it."
                                )

                        if (
                            col == 0
                            and commodity_key(self.plan.mini_tracked_commodity)
                            == key
                        ):
                            font = item.font()
                            font.setBold(True)
                            item.setFont(font)
                            existing_tip = item.toolTip().strip()
                            item.setToolTip(
                                "TRACKED IN MINI MODE"
                                + (f"\n{existing_tip}" if existing_tip else "")
                            )
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
            asteroid_used, asteroid_total = self._parse_usage(text(4))
            surface_used, surface_total = self._parse_usage(text(5))
            body_name = text(0) or f"Location {row + 1}"
            previous = next((site for site in self.plan.sites if site.body == body_name), None)
            body_type = text(1) or "Unknown"
            landable = text(2).lower() in ("yes", "true", "1")
            facility_text = self._physical_site_facility_text(text(6))
            editable_changed = bool(
                previous is None
                or previous.orbital_used != orbital_used
                or previous.orbital_total != orbital_total
                or previous.asteroid_used != asteroid_used
                or previous.asteroid_total != asteroid_total
                or previous.surface_used != surface_used
                or previous.surface_total != surface_total
                or previous.facility != facility_text
            )
            confidence = (
                "User confirmed"
                if self.editing and editable_changed
                else (previous.confidence if previous else (text(7) or "User entered"))
            )
            rows.append(SiteData(
                body=body_name,
                body_type=body_type,
                landable=landable,
                orbital_used=orbital_used,
                orbital_total=orbital_total,
                asteroid_used=asteroid_used,
                asteroid_total=asteroid_total,
                surface_used=surface_used,
                surface_total=surface_total,
                facility=facility_text,
                status="Available",
                confidence=confidence,
                body_id=previous.body_id if previous else 999999,
                mass_em=previous.mass_em if previous else None,
                radius_km=previous.radius_km if previous else None,
                atmosphere=previous.atmosphere if previous else "",
                volcanism=previous.volcanism if previous else "",
                parent_body=previous.parent_body if previous else "",
                distance_ls=previous.distance_ls if previous else None,
                rings=[dict(ring) for ring in previous.rings] if previous else [],
            ))
        return rows

    def set_editing(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled and not self.editing:
            self._edit_plan_snapshot = copy.deepcopy(self.plan)
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
            self.heavy_haul_check,
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
        self.sites_table.setColumnHidden(7, not enabled)
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
            self._apply_overview_summary_visibility()
        if hasattr(self, "overview_workflow_hint"):
            self.overview_workflow_hint.setVisible(False)
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
        site = next((entry for entry in self.plan.sites if entry.body == body), None)
        if self._is_asteroid_base_reference(reference) and (
            site is None or not self._site_has_asteroid_environment(site)
        ):
            QMessageBox.information(
                self,
                "Asteroid Base",
                "Asteroid Bases can only be placed at a planetary ring or asteroid/belt cluster.",
            )
            return

        facility_item = self.sites_table.item(row, 6)
        existing_text = facility_item.text().strip() if facility_item else ""
        physical = self._physical_site_facility_text(existing_text)
        marker_name = "Primary Port" if reference.id == "primary_port" else reference.display_name
        marker = f"✓ {marker_name}"
        existing_fragments = [part.strip() for part in re.split(r"[;\n]+", physical) if part.strip()]
        if any(CATALOG._normalise(marker_name) in CATALOG._normalise(part) for part in existing_fragments):
            QMessageBox.information(self, "Already listed", f"{marker_name} is already listed on {body}.")
            return
        existing_fragments.append(marker)
        self.sites_table.setItem(row, 6, QTableWidgetItem("; ".join(existing_fragments)))

        usage_col = 5 if reference.site_type == "surface" else 3
        usage_item = self.sites_table.item(row, usage_col)
        used, total = self._parse_usage(usage_item.text() if usage_item else "0/0")
        used += 1
        total = max(total, used)
        self.sites_table.setItem(row, usage_col, QTableWidgetItem(self._usage_text(used, total)))

        if self._is_asteroid_base_reference(reference):
            asteroid_item = self.sites_table.item(row, 4)
            asteroid_used, asteroid_total = self._parse_usage(
                asteroid_item.text() if asteroid_item else "0/0"
            )
            asteroid_used += 1
            asteroid_total = max(asteroid_total, asteroid_used)
            self.sites_table.setItem(
                row, 4, QTableWidgetItem(self._usage_text(asteroid_used, asteroid_total))
            )

        if reference.id == "primary_port":
            self.primary_port_check.setChecked(True)
            if self.primary_port_name_edit.text().strip() in ("", "Primary Port"):
                self.primary_port_name_edit.setText("Genesis")
            location_kind = "Surface" if reference.site_type == "surface" else "Orbit"
            self.primary_port_location_edit.setText(f"{body} — {location_kind} {used}")

        self.sites_edit_note.setText(f"Added as existing: {marker_name}. Save Changes when finished.")

    def cancel_edits(self) -> None:
        # Previewing goals/scope is allowed to mutate the in-memory queue, but
        # Cancel should be a transaction rollback, not another full build-out.
        if self._edit_plan_snapshot is not None:
            self.plan = copy.deepcopy(self._edit_plan_snapshot)
        self._edit_plan_snapshot = None
        self.editing = False
        self._apply_plan(reconcile_queue=False)

    def save_edits(self) -> None:
        old_goal = self.plan.primary_goal
        old_secondary = self.plan.secondary_goal
        old_scope = self.plan.plan_scope
        old_heavy_haul = self.plan.heavy_haul_logistics
        old_sites = copy.deepcopy(self.plan.sites)
        old_primary_port = (
            self.plan.primary_port_complete,
            self.plan.primary_port_name,
            self.plan.primary_port_location,
        )
        new_goal = self.primary_combo.currentText()
        new_secondary = self.secondary_combo.currentText()
        new_scope = self.plan_scope_combo.currentText()
        new_heavy_haul = self.heavy_haul_check.isChecked()
        if (
            old_goal != new_goal
            or old_secondary != new_secondary
            or old_scope != new_scope
            or old_heavy_haul != new_heavy_haul
        ):
            answer = QMessageBox.question(
                self,
                "Change system plan?",
                "Changing the goals, plan scope, or logistics policy regenerates the recommended build queue. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.plan.primary_goal = new_goal
        self.plan.secondary_goal = new_secondary
        self.plan.plan_scope = new_scope
        self.plan.heavy_haul_logistics = new_heavy_haul
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

        # Point calibration changes affordability/next-build status, but it does
        # not change what physically exists or the selected system build-out.
        # Apply calibration before any optional regeneration so point-dependent
        # ordering sees the player's corrected values.
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

        new_primary_port = (
            self.plan.primary_port_complete,
            self.plan.primary_port_name,
            self.plan.primary_port_location,
        )
        buildout_changed = (
            old_goal != self.plan.primary_goal
            or old_secondary != self.plan.secondary_goal
            or old_scope != self.plan.plan_scope
            or old_heavy_haul != self.plan.heavy_haul_logistics
            or old_sites != self.plan.sites
            or old_primary_port != new_primary_port
        )
        if buildout_changed:
            self._regenerate_facilities()
        elif self._edit_plan_snapshot is not None:
            # Goal/scope previews may have rebuilt the queue even when the user
            # ultimately returned every planner option to its saved value. Keep
            # the original queue for calibration-only/no-op saves.
            self.plan.facilities = copy.deepcopy(self._edit_plan_snapshot.facilities)

        self._edit_plan_snapshot = None
        self._save_plan()
        # Calibration-only edits keep the existing physical/planned queue and
        # skip the expensive full build-out regeneration.
        self._apply_plan(reconcile_queue=False)

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

    def _apply_plan(self, *, reconcile_queue: bool = True) -> None:
        if not hasattr(self, "primary_combo"):
            return
        for combo in (self.primary_combo, self.secondary_combo, self.plan_scope_combo):
            combo.blockSignals(True)
        try:
            self.primary_combo.setCurrentText(self.plan.primary_goal)
            self.secondary_combo.setCurrentText(self.plan.secondary_goal)
            self.plan_scope_combo.setCurrentText(self.plan.plan_scope)
        finally:
            for combo in (self.primary_combo, self.secondary_combo, self.plan_scope_combo):
                combo.blockSignals(False)
        self.phase_edit.setText(self.plan.phase)
        self.primary_port_check.setChecked(self.plan.primary_port_complete)
        if hasattr(self, "heavy_haul_check"):
            self.heavy_haul_check.blockSignals(True)
            self.heavy_haul_check.setChecked(bool(self.plan.heavy_haul_logistics))
            self.heavy_haul_check.blockSignals(False)
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
            self.ship_capacity_spin.blockSignals(True)
            self.ship_capacity_spin.setValue(self.plan.ship_capacity_tons or 1168)
            self.ship_capacity_spin.blockSignals(False)
        self._render_sites()
        self._render_queue(reconcile=reconcile_queue)
        self._render_materials()
        self.set_editing(False)
        self.current_build_changed.emit(display_build, display_location)

    def _preview_queue(self, _text: str) -> None:
        if self.editing:
            primary = self.primary_combo.currentText()
            secondary = self.secondary_combo.currentText()
            scope = self.plan_scope_combo.currentText()
            # Always regenerate from the current edit controls. This matters when
            # Heavy-haul is toggled back to its saved value: logistics-only rows
            # from the previous preview must disappear immediately.
            self._regenerate_facilities(primary, secondary, scope)
            self._render_queue(primary, secondary, scope)

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
    def _facility_has_physical_proof(facility: FacilityData) -> bool:
        """True once Elite/journal evidence says this location physically exists."""
        return bool(
            facility.status == "Complete"
            or facility.construction_started
            or facility.location_confirmed
            or facility.market_id
        ) and facility.status != "Skipped"

    @staticmethod
    def _copy_persistent_facility_state(target: FacilityData, previous: FacilityData) -> None:
        """Carry physical/journal identity across planner regeneration.

        v3.1.8 rebuilt FacilityData rows from the catalog and copied only status
        and location.  That discarded the very flags that prove a site exists,
        allowing later replans to move real construction sites.
        """
        for field_name in (
            "status",
            "location",
            "construction_started",
            "planned_location",
            "location_confirmed",
            "location_locked",
            "deviation_note",
            "logistics_target_body",
            "station_name",
            "market_id",
            "station_type",
            "journal_timestamp",
        ):
            setattr(target, field_name, getattr(previous, field_name))

    @staticmethod
    def _reference_for_facility_data(facility: FacilityData) -> FacilityRef:
        by_id = CATALOG.facility(facility.facility_id) if facility.facility_id else None

        # The normal case is a current catalog id paired with its own display
        # name. Avoid a full free-text scan across every catalog facility for
        # that overwhelmingly common path. Only fall back to fuzzy/text lookup
        # when the saved id is missing or the role no longer resembles it.
        if by_id is not None:
            role_norm = CATALOG._normalise(facility.role)
            known_names = (by_id.name, by_id.display_name, *by_id.aliases)
            for known_name in known_names:
                known_norm = CATALOG._normalise(known_name)
                if known_norm and (
                    role_norm == known_norm
                    or f" {known_norm} " in f" {role_norm} "
                ):
                    return by_id

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
        if self._is_asteroid_base_reference(reference):
            if self._location_is_real(facility.location):
                body = self._facility_body_from_location(facility.location)
                site = next((row for row in self.plan.sites if row.body == body), None)
                if site is None or not self._site_has_free_asteroid_location(site):
                    return False
            elif not self._has_available_asteroid_slot():
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

    def _facility_block_reason(
        self,
        facility: FacilityData,
        *,
        construction_state: Optional[tuple[int, int, int, int]] = None,
        descriptors: Optional[list[FacilityDescriptor]] = None,
    ) -> str:
        """Explain why a queued facility cannot be started *right now*.

        This deliberately uses the live/calibrated current point balance rather
        than the future simulated balance used to order the rest of the queue.
        A later row can therefore become NEXT when an earlier goal row is legal
        only after that bridge facility finishes.
        """

        if construction_state is None:
            construction_state = self._construction_state()
        tier_2, tier_3, t2_ports, t3_ports = construction_state
        if descriptors is None:
            descriptors = self._completed_facility_descriptors()
        reference = self._reference_for_facility_data(facility)
        if self._is_asteroid_base_reference(reference):
            if not self._system_has_asteroid_environment():
                return (
                    "Asteroid Base cannot be placed in this system: Elite requires "
                    "a planetary ring or asteroid/belt cluster."
                )
            if self._location_is_real(facility.location):
                body = self._facility_body_from_location(facility.location)
                site = next((row for row in self.plan.sites if row.body == body), None)
                if site is None or not self._site_has_asteroid_environment(site):
                    return (
                        "Asteroid Base location is incompatible: choose a ringed body "
                        "or asteroid/belt cluster."
                    )
                if not self._site_has_free_asteroid_location(site):
                    return (
                        f"{body} has no free confirmed Asteroid + Orbital slot. "
                        "In Edit Plan, enter the Asteroid used/total count shown by Elite Architect mode."
                    )
            elif not self._has_available_asteroid_slot():
                return (
                    "No free Asteroid-capable slot is confirmed. In Edit Plan, enter "
                    "Asteroid used/total for a ringed body or asteroid/belt cluster; "
                    "an Asteroid Base also consumes a normal Orbital slot."
                )
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

    def _next_buildable_facility(
        self,
        *,
        construction_state: Optional[tuple[int, int, int, int]] = None,
        descriptors: Optional[list[FacilityDescriptor]] = None,
    ) -> Optional[FacilityData]:
        """Return the first queued facility Elite should allow us to start now."""

        if construction_state is None:
            construction_state = self._construction_state()
        if descriptors is None:
            descriptors = self._completed_facility_descriptors()
        for facility in self.plan.facilities:
            if facility.status != "Queued":
                continue
            if not self._facility_block_reason(
                facility,
                construction_state=construction_state,
                descriptors=descriptors,
            ):
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
            # Once a depot event proves the site exists, planner prerequisites
            # are no longer allowed to demote or erase that physical reality.
            if facility.construction_started or facility.market_id:
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
            if not self._reference_has_available_location(reference):
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
        prefer_heavy_hub = (
            self._effective_heavy_haul_logistics()
            and self._selected_goals_physically_complete(*self._effective_goal_names())
        )
        while remaining:
            buildable = [
                facility for facility in remaining
                if self._facility_can_build(
                    facility, tier_2, tier_3, descriptors, t2_ports, t3_ports
                )
            ]
            choice: Optional[FacilityData] = None
            if buildable and prefer_heavy_hub:
                choice = next(
                    (
                        facility for facility in buildable
                        if facility.logistics_target_body
                        and CATALOG.is_large_pad_hub(self._reference_for_facility_data(facility))
                    ),
                    None,
                )
                if choice is None:
                    choice = next(
                        (
                            facility for facility in buildable
                            if CATALOG.is_large_pad_hub(self._reference_for_facility_data(facility))
                        ),
                        None,
                    )
            if choice is None and buildable:
                choice = buildable[0]
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
        # dual-goal scope includes both dropdowns. Goal-Directed Expansion adds
        # only strongly related supporting capabilities; Full System Build-Out
        # remains available when the commander intentionally wants broad coverage.
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
                self._copy_persistent_facility_state(facility, previous)
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
            if previous.status in ("Complete", "Building now") or self._facility_has_physical_proof(previous):
                generated.append(previous)

        if plan_scope in ("Goal-Directed Expansion", "Full System Build-Out"):
            self._append_system_buildout_rows(
                generated, goal, effective_secondary, old_by_id, old_by_role,
                full_buildout=(plan_scope == "Full System Build-Out"),
            )
            self._ensure_heavy_haul_hubs(
                generated, goal, effective_secondary, old_by_id, old_by_role, plan_scope
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
        *,
        full_buildout: bool = False,
    ) -> None:
        """Extend selected goals with useful post-goal development.

        Goal-Directed Expansion adds only enough of the highest-value supporting
        stages to give the system the capabilities it needs. Full System Build-Out
        remains available for commanders who deliberately want broad category
        coverage. Neither mode uses a fixed facility-count ceiling.
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
        asteroid_remaining: Optional[int] = None
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
            asteroid_remaining = sum(
                max(0, site.asteroid_total - self._effective_asteroid_used(site))
                for site in self.plan.sites
                if self._site_has_asteroid_environment(site)
            )
            # Goal rows already queued by this regeneration consume future slots.
            for facility in generated:
                if facility.status in ("Complete", "Building now"):
                    continue
                if facility.preferred_site == "surface" and surface_remaining is not None:
                    surface_remaining = max(0, surface_remaining - 1)
                elif facility.preferred_site == "orbital" and orbital_remaining is not None:
                    orbital_remaining = max(0, orbital_remaining - 1)
                    if (
                        asteroid_remaining is not None
                        and self._is_asteroid_base_reference(self._reference_for_facility_data(facility))
                    ):
                        asteroid_remaining = max(0, asteroid_remaining - 1)

        stages = (
            CATALOG.ordered_buildout_stages(primary_goal, secondary_goal, known_refs)
            if full_buildout
            else CATALOG.targeted_buildout_stages(primary_goal, secondary_goal, known_refs)
        )
        for stage in stages:
            stage_name = str(stage.get("name", "System Development"))
            description = str(stage.get("description", "")).strip()
            if full_buildout:
                stage_references = [
                    reference for reference in CATALOG.stage_facilities(stage)
                    if self._reference_is_system_applicable(reference)
                ]
            else:
                stage_references = [
                    reference for reference in CATALOG.stage_target_facilities(stage)
                    if self._reference_is_system_applicable(reference)
                ]
            target_total = len(stage_references)
            before_total = target_total
            before_satisfied = sum(
                1 for reference in stage_references
                if CATALOG.functional_signature(reference) in known_signatures
            )
            needed_for_stage = max(0, target_total - before_satisfied)
            if needed_for_stage <= 0:
                continue
            for reference in stage_references:
                signature = CATALOG.functional_signature(reference)
                if signature in known_signatures:
                    continue
                if not self._reference_has_available_location(reference):
                    continue
                if reference.site_type == "surface" and surface_remaining is not None:
                    if surface_remaining <= 0:
                        continue
                if reference.site_type == "orbital" and orbital_remaining is not None:
                    if orbital_remaining <= 0:
                        continue
                if (
                    self._is_asteroid_base_reference(reference)
                    and asteroid_remaining is not None
                    and asteroid_remaining <= 0
                ):
                    continue

                reason = (
                    f"{'Full build-out' if full_buildout else 'Goal-directed expansion'} — {stage_name}: "
                    f"{before_satisfied}/{target_total if not full_buildout else before_total} target functions already present. "
                    f"{description}"
                ).strip()
                previous = old_by_id.get(reference.id) or old_by_role.get(reference.display_name)
                facility = FacilityData.from_reference(reference, reason)
                if self._is_asteroid_base_reference(reference):
                    # Elite exposes Asteroid Base placement through a compatible
                    # ring/belt location; the final visual subtype follows that
                    # environment and is not something Observatory should promise
                    # before the player places it.
                    facility.role = "Starport / Tier 2 / Asteroid Base / Ring-dependent"
                if previous and previous.status not in ("Skipped",):
                    self._copy_persistent_facility_state(facility, previous)
                generated.append(facility)
                known_refs.append(reference)
                known_signatures.add(signature)
                if reference.site_type == "surface" and surface_remaining is not None:
                    surface_remaining -= 1
                elif reference.site_type == "orbital" and orbital_remaining is not None:
                    orbital_remaining -= 1
                    if self._is_asteroid_base_reference(reference) and asteroid_remaining is not None:
                        asteroid_remaining -= 1

                # Update the stage progress embedded in subsequent explanations.
                before_satisfied = min(before_total, before_satisfied + 1)
                needed_for_stage -= 1
                if needed_for_stage <= 0:
                    break

    def _selected_goals_physically_complete(
        self,
        primary_goal: Optional[str] = None,
        secondary_goal: Optional[str] = None,
    ) -> bool:
        """True when the selected role is already established in the real colony.

        Heavy-haul infrastructure is deliberately a post-goal optimisation.  A
        brand-new colony should still earn its cheap T2/T3 bridges and satisfy
        the selected mission before spending scarce points on convenience hubs.
        """

        primary_goal = primary_goal or self.plan.primary_goal
        secondary_goal = self.plan.secondary_goal if secondary_goal is None else secondary_goal
        known = self._completed_physical_references()
        primary = CATALOG.goal_progress(
            primary_goal,
            known,
            primary_port_complete=self.plan.primary_port_complete,
            active_facilities=[],
        )
        if primary.get("status") != "Complete":
            return False
        mapped_secondary = CATALOG.mapped_secondary_goal(secondary_goal)
        if not mapped_secondary:
            return True
        secondary = CATALOG.goal_progress(
            mapped_secondary,
            known,
            primary_port_complete=self.plan.primary_port_complete,
            active_facilities=[],
        )
        return secondary.get("status") == "Complete"

    def _physical_body_references_for_logistics(self, body: str) -> list[FacilityRef]:
        """Return only facilities that physically exist/are actively building on a body."""

        refs: list[FacilityRef] = []
        seen: set[str] = set()
        for facility in self.plan.facilities:
            if facility.status not in ("Complete", "Building now"):
                continue
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

    def _body_has_physical_large_hub(self, body: str) -> bool:
        return any(
            CATALOG.is_large_pad_hub(reference)
            for reference in self._physical_body_references_for_logistics(body)
        )

    def _heavy_haul_cluster_score(self, site: SiteData) -> int:
        """Operational importance of an already-developed body.

        Supporting facilities carry most of the weight because those are the
        economies a same-body large port can strongly link.  Small/medium ports
        still add a little value, and the primary-port body receives a modest
        stability bonus.  Planned-but-unbuilt rows are intentionally excluded so
        the app does not invent a 'cluster' from its own future suggestions.
        """

        score = 0
        goal_weights = CATALOG.goal_economy_weights(*self._effective_goal_names())
        for reference in self._physical_body_references_for_logistics(site.body):
            if CATALOG.is_large_pad_hub(reference):
                continue
            if CATALOG.is_supporting_facility(reference):
                score += 3
            elif CATALOG.is_port(reference):
                score += 1
            economy = CATALOG._normalise(reference.market_economy or reference.economy)
            if economy and goal_weights.get(economy, 0) > 0:
                score += 1
        if site.body == self._primary_port_body():
            score += 1
        return score

    @staticmethod
    def _site_has_free_slot(site: SiteData, site_type: str) -> bool:
        if site_type == "surface":
            return bool(site.landable and site.surface_total > site.surface_used)
        if site_type == "orbital":
            return bool(site.orbital_total > site.orbital_used)
        return False

    def _ensure_heavy_haul_hubs(
        self,
        generated: list[FacilityData],
        primary_goal: str,
        secondary_goal: str,
        old_by_id: dict[str, FacilityData],
        old_by_role: dict[str, FacilityData],
        plan_scope: str,
    ) -> None:
        """Target large-pad hubs at the colony's strongest existing clusters.

        This is intentionally a preference, not a ban on Outposts.  Cheap T1
        ports remain valuable point generators and distinct economy functions.
        Once the selected goals physically exist, heavy-haul mode tries to give
        up to two (goal-directed) or three (full build-out) important bodies a
        large-pad hub.  Existing Starport rows are reused first; a Tier-3
        Planetary Port is added when the important body has surface capacity but
        no orbital slot for a large orbital Starport.
        """

        if not self._effective_heavy_haul_logistics():
            return
        if not self._selected_goals_physically_complete(primary_goal, secondary_goal):
            return

        candidates = [
            site for site in self.plan.sites
            if self._heavy_haul_cluster_score(site) >= 4
            and not self._body_has_physical_large_hub(site.body)
            and (
                self._site_has_free_slot(site, "orbital")
                or self._site_has_free_slot(site, "surface")
            )
        ]
        candidates.sort(
            key=lambda site: (
                -self._heavy_haul_cluster_score(site),
                self._body_sort_key(site.body, site.body_id),
            )
        )
        if not candidates:
            return

        max_hubs = 3 if plan_scope == "Full System Build-Out" else 2
        assigned_bodies = {
            facility.logistics_target_body
            for facility in generated
            if facility.logistics_target_body
        }
        used_ids = {facility.facility_id for facility in generated if facility.facility_id}

        # Asteroid Bases are *not* generic orbital hubs: Elite only offers
        # them at ringed bodies or asteroid clusters.  Heavy-haul convenience
        # therefore uses Coriolis variants for arbitrary orbital targets; the
        # normal build-out planner may still choose an Asteroid Base when a
        # compatible ring/belt location really exists.
        orbital_ids = [
            "starport_coriolis_no_truss",
            "starport_coriolis_dual_truss",
            "starport_coriolis_quad_truss",
        ]
        surface_ids = [
            "tier3_port_zeus",
            "tier3_port_hera",
            "tier3_port_poseidon",
        ]

        def existing_large_row(site_type: str) -> Optional[FacilityData]:
            for row in generated:
                if row.status != "Queued" or row.logistics_target_body:
                    continue
                reference = self._reference_for_facility_data(row)
                if reference.site_type == site_type and CATALOG.is_large_pad_hub(reference):
                    return row
            return None

        def add_large_row(site_type: str, body: str) -> Optional[FacilityData]:
            ids = orbital_ids if site_type == "orbital" else surface_ids
            for facility_id in ids:
                if facility_id in used_ids:
                    continue
                reference = CATALOG.facility(facility_id)
                if reference is None:
                    continue
                previous = old_by_id.get(reference.id) or old_by_role.get(reference.display_name)
                row = FacilityData.from_reference(
                    reference,
                    (
                        f"Heavy-haul logistics: establish a large-pad hub on {body} so the "
                        "existing same-body economy cluster can feed a practical bulk-haul port."
                    ),
                )
                if previous and previous.status not in ("Skipped",):
                    self._copy_persistent_facility_state(row, previous)
                row.logistics_target_body = body
                generated.append(row)
                used_ids.add(reference.id)
                return row
            return None

        hubs_targeted = 0
        for site in candidates:
            if hubs_targeted >= max_hubs:
                break
            if site.body in assigned_bodies:
                continue

            # Reuse a large orbital Starport already required by the full build
            # before adding another expensive port.  If the cluster has no free
            # orbital slot, a Tier-3 surface Planetary Port is the fallback.
            row: Optional[FacilityData] = None
            if self._site_has_free_slot(site, "orbital"):
                row = existing_large_row("orbital")
                if row is None:
                    row = add_large_row("orbital", site.body)
            if row is None and self._site_has_free_slot(site, "surface"):
                row = existing_large_row("surface")
                if row is None:
                    row = add_large_row("surface", site.body)
            if row is None:
                continue

            row.logistics_target_body = site.body
            assigned_bodies.add(site.body)
            hubs_targeted += 1

    def _queue_reason_with_logistics(self, facility: FacilityData) -> str:
        reason = facility.reason
        reference = self._reference_for_facility_data(facility)
        if (
            self._effective_heavy_haul_logistics()
            and facility.logistics_target_body
            and CATALOG.is_large_pad_hub(reference)
        ):
            reason += (
                f"  •  Heavy-haul hub for {facility.logistics_target_body}: prefer large-pad "
                "access beside the established economy cluster/strong-link network."
            )
        if facility.deviation_note:
            reason += f"  •  ⚠ {facility.deviation_note}"
        return reason

    @staticmethod
    def _is_port_reference(reference: FacilityRef) -> bool:
        return CATALOG.is_port(reference)

    @staticmethod
    def _is_asteroid_base_reference(reference: FacilityRef) -> bool:
        return (
            CATALOG._normalise(reference.facility_type) == "starport"
            and CATALOG._normalise(reference.category) == "asteroid base"
        )

    @staticmethod
    def _is_asteroid_cluster_text(body_name: str, body_type: str) -> bool:
        text = f"{body_name} {body_type}".casefold()
        return "belt cluster" in text or "asteroid cluster" in text

    @classmethod
    def _site_has_asteroid_environment(cls, site: SiteData) -> bool:
        """Elite only permits Asteroid Bases at rings or asteroid clusters."""
        if cls._is_asteroid_cluster_text(site.body, site.body_type):
            return True
        return bool(site.rings)

    def _system_has_asteroid_environment(self) -> bool:
        return any(self._site_has_asteroid_environment(site) for site in self.plan.sites)

    def _asteroid_facilities_on_body(self, body: str) -> int:
        """Count physically committed Asteroid Bases on one body.

        Saved v3.1.8 plans predate the dedicated asteroid counter, so the
        facility queue is also used as a migration-safe lower bound.
        """
        count = 0
        for facility in self.plan.facilities:
            if facility.status not in ("Complete", "Building now"):
                continue
            reference = self._reference_for_facility_data(facility)
            if not self._is_asteroid_base_reference(reference):
                continue
            if self._facility_body_from_location(facility.location) == body:
                count += 1
        return count

    def _effective_asteroid_used(self, site: SiteData) -> int:
        return max(int(site.asteroid_used or 0), self._asteroid_facilities_on_body(site.body))

    @staticmethod
    def _asteroid_reservation_prefix(body: str) -> str:
        return f"@asteroid:{body}:"

    def _reserved_asteroid_count(self, body: str, reserved: set[str]) -> int:
        prefix = self._asteroid_reservation_prefix(body)
        return sum(1 for value in reserved if value.startswith(prefix))

    def _reserve_asteroid_slot(self, body: str, reserved: set[str]) -> None:
        number = self._reserved_asteroid_count(body, reserved) + 1
        reserved.add(f"{self._asteroid_reservation_prefix(body)}{number}")

    def _site_has_free_asteroid_location(self, site: SiteData, reserved: Optional[set[str]] = None) -> bool:
        """Asteroid Base requires a ring/belt, one orbital slot and one asteroid slot."""
        if not self._site_has_asteroid_environment(site):
            return False
        reserved = reserved or set()
        asteroid_used = self._effective_asteroid_used(site) + self._reserved_asteroid_count(site.body, reserved)
        return asteroid_location_available(
            has_environment=True,
            orbital_used=site.orbital_used,
            orbital_total=site.orbital_total,
            asteroid_used=asteroid_used,
            asteroid_total=site.asteroid_total,
        )

    def _has_available_asteroid_slot(self) -> bool:
        return any(self._site_has_free_asteroid_location(site) for site in self.plan.sites)

    def _reference_is_system_applicable(self, reference: FacilityRef) -> bool:
        if self._is_asteroid_base_reference(reference):
            return self._system_has_asteroid_environment()
        return True

    def _reference_has_available_location(self, reference: FacilityRef) -> bool:
        if self._is_asteroid_base_reference(reference):
            return self._has_available_asteroid_slot()
        return self._site_type_can_accept_more(reference.site_type)

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

    def _effective_heavy_haul_logistics(self) -> bool:
        if self.editing and hasattr(self, "heavy_haul_check"):
            return bool(self.heavy_haul_check.isChecked())
        return bool(self.plan.heavy_haul_logistics)

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
        if plan_scope in ("Primary Goal Only", "Primary + Secondary Goals"):
            return "Selected goals complete — ready to move on"

        known = self._completed_physical_references()
        if plan_scope == "Goal-Directed Expansion":
            ranked = CATALOG.targeted_buildout_stages(primary_goal, secondary_goal, known)
            if not ranked:
                return "Goal-directed expansion complete — system has the selected capabilities"
            return f"Goal-Directed Expansion — next capability: {ranked[0].get('name', 'System Development')}"

        ranked = CATALOG.ordered_buildout_stages(primary_goal, secondary_goal, known)
        known_signatures = {CATALOG.functional_signature(reference) for reference in known}
        next_stage = None
        for stage in ranked:
            feasible = [
                reference for reference in CATALOG.stage_facilities(stage)
                if self._reference_is_system_applicable(reference)
            ]
            if not feasible:
                continue
            satisfied = sum(
                1 for reference in feasible
                if CATALOG.functional_signature(reference) in known_signatures
            )
            if satisfied < len(feasible):
                next_stage = stage
                break
        if next_stage is None:
            return "Full system build-out complete"
        return f"Full System Build-Out — next stage: {next_stage.get('name', 'System Development')}"

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
        local_refs = [
            other for other in self._body_facility_references(site.body)
            if other.id != reference.id
        ]
        is_port = self._is_port_reference(reference)
        is_large_hub = CATALOG.is_large_pad_hub(reference)
        local_ports = [other for other in local_refs if self._is_port_reference(other)]
        local_large_hubs = [other for other in local_ports if CATALOG.is_large_pad_hub(other)]
        local_support = [other for other in local_refs if not self._is_port_reference(other)]

        if self._effective_heavy_haul_logistics():
            if is_large_hub:
                # Explicit target bodies are selected from facilities that already
                # physically exist, so this bonus is deliberately stronger than
                # generic economy affinity or future-plan proximity.
                if facility.logistics_target_body:
                    if site.body == facility.logistics_target_body:
                        score += 5000
                    else:
                        score -= 1200
                cluster_score = self._heavy_haul_cluster_score(site)
                score += 220 * cluster_score
                if cluster_score == 0:
                    score -= 600
            elif not is_port and local_large_hubs:
                # Once a large-pad hub exists/plans onto a body, keep later
                # support nearby so bulk-haul commanders can actually use it.
                score += 900 + 60 * len(local_large_hubs)

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
        reference = self._reference_for_facility_data(facility)
        asteroid_base = self._is_asteroid_base_reference(reference)
        related_bodies = self._related_bodies_for_facility(facility)
        candidates: list[tuple[int, tuple[Any, ...], int, str]] = []
        for site in self.plan.sites:
            if asteroid_base and not self._site_has_free_asteroid_location(site, reserved):
                continue
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
            if asteroid_base:
                return "No free Asteroid + Orbital slot on a compatible ring/belt"
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
                self._location_is_real(facility.location)
                and (
                    facility.status in ("Complete", "Building now")
                    or facility.location_locked
                    or self._facility_has_physical_proof(facility)
                )
            ):
                reserved.add(facility.location)
                reference = self._reference_for_facility_data(facility)
                if (
                    facility.status != "Complete"
                    and self._is_asteroid_base_reference(reference)
                ):
                    body = self._facility_body_from_location(facility.location)
                    if body:
                        self._reserve_asteroid_slot(body, reserved)
                continue
            proposed = self._best_location_for_facility(facility, reserved)
            facility.location = proposed
            if self._location_is_real(proposed):
                reserved.add(proposed)
                reference = self._reference_for_facility_data(facility)
                if self._is_asteroid_base_reference(reference):
                    body = self._facility_body_from_location(proposed)
                    if body:
                        self._reserve_asteroid_slot(body, reserved)

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
                self._usage_text(self._effective_asteroid_used(site), site.asteroid_total),
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
                if col in (0, 1, 2, 7):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if highlighted:
                    item.setBackground(QColor("#5B3B05"))
                elif building:
                    item.setBackground(QColor("#4A3410"))
                elif complete and col == 6:
                    item.setBackground(QColor("#173820"))
                self.sites_table.setItem(row, col, item)
        self.sites_table.setSortingEnabled(True)
        self.sites_table.sortItems(0, Qt.SortOrder.AscendingOrder)

        orbital_used = sum(site.orbital_used for site in self.plan.sites)
        orbital_total = sum(site.orbital_total for site in self.plan.sites)
        asteroid_used = sum(self._effective_asteroid_used(site) for site in self.plan.sites)
        asteroid_total = sum(site.asteroid_total for site in self.plan.sites)
        surface_used = sum(site.surface_used for site in self.plan.sites)
        surface_total = sum(site.surface_total for site in self.plan.sites)
        capacity_notes: list[str] = []
        if any(str(site.confidence).startswith("Estimated") for site in self.plan.sites):
            capacity_notes.append("some surface capacity is estimated")
        if self.plan.sites and orbital_total == 0:
            capacity_notes.append("no orbital capacity entered")
        if self._system_has_asteroid_environment() and asteroid_total == 0:
            capacity_notes.append("ring/belt detected; confirm Asteroid slots in Edit Plan")
        suffix = f"  •  Setup note: {', '.join(capacity_notes)}" if capacity_notes else ""
        self.site_summary.setText(
            f"Build system: {self.display_system_name()}  •  "
            f"Orbital {orbital_used}/{orbital_total}  •  "
            f"Asteroid {asteroid_used}/{asteroid_total}  •  "
            f"Surface {surface_used}/{surface_total}  •  "
            f"Available: {max(0, orbital_total-orbital_used)} orbital, "
            f"{max(0, asteroid_total-asteroid_used)} asteroid, "
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

    @staticmethod
    def _compact_overview_reason(text: str, limit: int = 150) -> str:
        """Keep the Overview's Why field useful without letting it eat the card."""
        value = " ".join(str(text or "").split())
        if not value:
            return ""
        # Planner reasons are intentionally explanatory, often with a concise
        # first sentence followed by implementation detail. The queue retains
        # the full text; Overview only needs the headline.
        first = re.split(r"(?<=[.!?])\s+", value, maxsplit=1)[0]
        if len(first) <= limit:
            return first
        return first[: max(1, limit - 1)].rstrip() + "…"

    def _render_queue(
        self,
        goal: Optional[str] = None,
        secondary_goal: Optional[str] = None,
        plan_scope: Optional[str] = None,
        *,
        reconcile: bool = True,
    ) -> None:
        goal = goal or self.plan.primary_goal
        secondary_goal = (
            self.plan.secondary_goal if secondary_goal is None else secondary_goal
        )
        plan_scope = plan_scope or self._effective_plan_scope()
        if reconcile:
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
            if plan_scope == "Goal-Directed Expansion":
                needs_pending_work = needs_pending_work or not phase_before.startswith("Goal-directed expansion complete")
            elif plan_scope == "Full System Build-Out":
                needs_pending_work = needs_pending_work or phase_before != "Full system build-out complete"

            if (
                goal != self.plan.primary_goal
                or secondary_goal != self.plan.secondary_goal
                or plan_scope != self.plan.plan_scope
                or self._effective_heavy_haul_logistics() != bool(self.plan.heavy_haul_logistics)
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
        shared_construction_state = self._construction_state()
        tier_2, tier_3 = shared_construction_state[:2]
        shared_descriptors = self._completed_facility_descriptors()
        primary_progress, secondary_progress = self.selected_goal_progress(goal, secondary_goal)
        phase = self.current_development_phase(goal, secondary_goal, plan_scope)
        secondary_text = self._progress_label(secondary_progress)
        point_source = "game-calibrated" if self.plan.point_balance_calibrated else "calculated"
        logistics_notice = "  •  Heavy-haul logistics ON" if self._effective_heavy_haul_logistics() else ""
        self.queue_notice.setText(
            f"{self.display_system_name()}  •  Points now: {tier_2} T2, {tier_3} T3 ({point_source})  •  "
            f"Primary: {self._progress_label(primary_progress)}  •  "
            f"Secondary: {secondary_text}  •  {phase}{logistics_notice}"
        )
        self.queue_table.setRowCount(len(rows))
        next_facility = self._next_buildable_facility(
            construction_state=shared_construction_state,
            descriptors=shared_descriptors,
        )
        for row, facility in enumerate(rows):
            if self.plan.primary_port_complete and facility.facility_id == "primary_port":
                facility.status = "Complete"
            block_reason = (
                self._facility_block_reason(
                    facility,
                    construction_state=shared_construction_state,
                    descriptors=shared_descriptors,
                )
                if facility.status == "Queued" else ""
            )
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
            queue_reason = self._queue_reason_with_logistics(facility)
            identity_bits: list[str] = []
            if facility.station_name:
                identity_bits.append(f"Actual station: {facility.station_name}")
            if facility.market_id:
                identity_bits.append(f"MarketID: {facility.market_id}")
            identity_tip = " • ".join(identity_bits)
            values = [
                str(row + 1),
                facility.role,
                self._queue_display_location(facility.location),
                facility.preferred_site.title(),
                facility.point_summary,
                queue_reason,
                facility.status,
                block_reason if action == "BLOCKED" else action,
            ]
            tooltips = [
                str(row + 1),
                facility.role,
                (f"{facility.location}\n{identity_tip}" if identity_tip else facility.location),
                facility.preferred_site.title(),
                facility.point_summary,
                queue_reason,
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
            full_reason = (
                f"{next_facility.reason}  •  {next_facility.point_summary}  •  "
                f"confidence: {next_facility.confidence}"
            )
            self.next_reason_value.setText(
                self._compact_overview_reason(next_facility.reason)
            )
            self.next_reason_value.setToolTip(full_reason)
            self.set_next_current_button.setEnabled(
                self._location_is_real(next_facility.location)
            )
            self.undo_focus_button.setEnabled(bool(self.plan.previous_current_build))
        else:
            blocked = next((f for f in self.plan.facilities if f.status == "Queued"), None)
            if blocked is not None:
                self.next_build_value.setText("No buildable next facility")
                self.next_location_value.setText(blocked.location)
                blocked_reason = (
                    f"{blocked.role} is currently blocked. {self._facility_block_reason(blocked)}"
                )
                self.next_reason_value.setText(
                    self._compact_overview_reason(blocked_reason)
                )
                self.next_reason_value.setToolTip(blocked_reason)
            else:
                self.next_build_value.setText("No more recommended builds")
                self.next_location_value.setText("None")
                self.next_reason_value.setText("")
                self.next_reason_value.setToolTip("")
            self.set_next_current_button.setEnabled(False)
            self.undo_focus_button.setEnabled(bool(self.plan.previous_current_build))
        if hasattr(self, "sites_next"):
            self._render_sites()
        self._render_materials()

    def _show_queue_context_menu(self, pos) -> None:
        """Right-click shortcuts for the same Build Queue commands as the buttons."""
        item = self.queue_table.itemAt(pos)
        if item is not None:
            self.queue_table.selectRow(item.row())

        facility = self._selected_queue_facility()
        menu = QMenu(self.queue_table)

        track_selected = menu.addAction("Track Selected Build")
        track_allowed = bool(
            facility is not None
            and (
                (facility.status == "Queued" and not self._facility_block_reason(facility))
                or (facility.status == "Building now" and facility.construction_started)
            )
        )
        track_selected.setEnabled(track_allowed)
        track_next = menu.addAction("Track NEXT Build")
        track_next.setEnabled(self._next_buildable_facility() is not None)

        menu.addSeparator()
        change_location = menu.addAction("Change Location…")
        mark_complete = menu.addAction("Mark Complete (manual)")
        skip_selected = menu.addAction("Skip Selected")
        change_location.setEnabled(facility is not None)
        mark_complete.setEnabled(bool(facility is not None and facility.status in ("Queued", "Building now")))
        skip_selected.setEnabled(bool(
            facility is not None
            and facility.status in ("Queued", "Building now")
            and not self._facility_has_physical_proof(facility)
        ))

        if self.plan.previous_current_build:
            menu.addSeparator()
            undo_tracking = menu.addAction("Undo Build Selection")
        else:
            undo_tracking = None

        chosen = menu.exec(self.queue_table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == track_selected:
            self._run_user_action(self.set_selected_queue_as_current)
        elif chosen == track_next:
            self._run_user_action(self.set_recommendation_as_current)
        elif chosen == change_location:
            self._run_user_action(self.change_selected_queue_location)
        elif chosen == mark_complete:
            self._run_user_action(self.mark_selected_queue_complete)
        elif chosen == skip_selected:
            self._run_user_action(self.skip_selected_queue_item)
        elif undo_tracking is not None and chosen == undo_tracking:
            self._run_user_action(self.undo_focus_change)

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
        if facility.status == "Building now" and facility.construction_started:
            # A real concurrent construction site can become the Materials focus
            # without changing the physical state of any other active site.
            self._set_focus_facility(facility)
            return
        if facility.status != "Queued":
            if facility.status == "Building now":
                QMessageBox.information(self, "Already tracked", f"{facility.role} is already the tracked build.")
            else:
                QMessageBox.information(
                    self,
                    "Not a queued build",
                    f"{facility.role} is {facility.status.lower()} and cannot be selected as the current build.",
                )
            return
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
            if other is facility:
                continue
            # Only demote an unstarted planning focus. Depot-confirmed sites stay
            # Building now even while the commander tracks materials for another site.
            if other.status == "Building now" and not other.construction_started:
                other.status = "Queued"
        if facility.status != "Complete":
            facility.status = "Building now"
        # Never erase proof that this site already exists when changing focus.
        if not facility.construction_started:
            facility.construction_started = False
        self.plan.current_build = facility.role
        self.plan.current_location = facility.location
        # A new tracking session needs a fresh timestamp so cached depot events
        # from an older construction site cannot be mistaken for this build.
        self.active_focus = {}
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
                if not facility.construction_started:
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


    def _next_actual_location_on_body(
        self, body: str, preferred_site: str, facility: Optional[FacilityData] = None
    ) -> str:
        """Return the next physical slot label on one specific Elite body."""
        prefix = "Surface" if preferred_site == "surface" else "Orbit"
        highest = 0
        for other in self.plan.facilities:
            if other is facility or not self._facility_has_physical_proof(other):
                continue
            location = str(other.location or "")
            if not location.startswith(body + " — " + prefix + " "):
                continue
            try:
                highest = max(highest, int(location.rsplit(" ", 1)[-1]))
            except ValueError:
                pass
        site = next((row for row in self.plan.sites if row.body == body), None)
        if site is not None:
            used = site.surface_used if preferred_site == "surface" else site.orbital_used
            highest = max(highest, int(used or 0))
        return f"{body} — {prefix} {highest + 1}"

    def _record_actual_location(self, facility: FacilityData, body: str) -> bool:
        body = str(body or "").strip()
        if not body or body.casefold().startswith("unknown"):
            return False
        planned_body = self._facility_body_from_location(facility.location)
        if planned_body == body:
            facility.location_confirmed = True
            facility.location_locked = True
            if not facility.planned_location:
                facility.planned_location = facility.location
            return False
        old_location = facility.location
        new_location = self._next_actual_location_on_body(body, facility.preferred_site, facility)
        if not facility.planned_location:
            facility.planned_location = old_location
        facility.location = new_location
        facility.location_confirmed = True
        facility.location_locked = True
        facility.deviation_note = (
            f"Elite reports this build on {body}; Observatory originally planned {old_location}."
        )
        if self.plan.current_build == facility.role:
            self.plan.current_location = new_location
        site = next((row for row in self.plan.sites if row.body == body), None)
        if site is not None:
            try:
                slot = int(new_location.rsplit(" ", 1)[-1])
            except ValueError:
                slot = 0
            if facility.preferred_site == "surface":
                site.surface_used = max(site.surface_used, slot)
            else:
                site.orbital_used = max(site.orbital_used, slot)
                reference = self._reference_for_facility_data(facility)
                if self._is_asteroid_base_reference(reference):
                    site.asteroid_used = max(
                        site.asteroid_used, self._asteroid_facilities_on_body(body), 1
                    )
                    site.asteroid_total = max(site.asteroid_total, site.asteroid_used)
        return True

    def change_selected_queue_location(self) -> None:
        facility = self._selected_queue_facility()
        if facility is None:
            return
        eligible: list[str] = []
        reference = self._reference_for_facility_data(facility)
        asteroid_base = self._is_asteroid_base_reference(reference)
        for site in self.plan.sites:
            if asteroid_base and not self._site_has_free_asteroid_location(site):
                continue
            if facility.preferred_site == "surface":
                if not site.landable:
                    continue
                if site.surface_total > 0 and site.surface_used >= site.surface_total:
                    continue
            else:
                if site.orbital_total > 0 and site.orbital_used >= site.orbital_total:
                    continue
            eligible.append(site.body)
        if not eligible:
            QMessageBox.information(
                self, "No compatible location",
                "No compatible body/slot is currently available in System Layout."
            )
            return
        body, ok = QInputDialog.getItem(
            self,
            "Change build location",
            f"Choose the body for:\n{facility.role}",
            eligible,
            0,
            False,
        )
        if not ok or not body:
            return
        old_location = facility.location
        new_location = self._next_actual_location_on_body(str(body), facility.preferred_site, facility)
        if not facility.planned_location:
            facility.planned_location = old_location
        facility.location = new_location
        facility.location_locked = True
        facility.deviation_note = f"Location manually changed from {old_location} to {new_location}."
        if self.plan.current_build == facility.role:
            self.plan.current_location = new_location
        self._save_plan()
        self._apply_plan()

    def skip_selected_queue_item(self) -> None:
        facility = self._selected_queue_facility()
        if facility is None:
            return
        if self._facility_has_physical_proof(facility):
            QMessageBox.information(
                self,
                "Physical site preserved",
                "Elite has already reported this construction site. It cannot be skipped from the planner; "
                "complete, fail/remove, or manually correct its location instead.",
            )
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
        facility.construction_started = True
        facility.location_confirmed = True
        facility.location_locked = True
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

    def focus_material_summary(self) -> tuple[str, str, bool, str, str]:
        """Compact material status for construction mini mode.

        A player-pinned commodity takes precedence over the automatic largest-
        remaining choice. If the pin does not exist in the current build, mini
        mode quietly falls back to the normal automatic behavior.
        """
        facility = self._focus_facility()
        if facility is None:
            return ("No focus build", "Stock —", False, "Trips —", "Source: —")
        rows = self._stored_materials_for(facility)
        capacity = max(1, int(self.plan.ship_capacity_tons or 1))

        tracked_key = commodity_key(self.plan.mini_tracked_commodity)
        tracked = next(
            (row for row in rows if tracked_key and commodity_key(row.commodity) == tracked_key),
            None,
        )
        if tracked is not None:
            remaining = tracked.delivery_remaining
            trips = (remaining + capacity - 1) // capacity if remaining else 0
            stock_exact = self.ship_inventory_known and self.carrier_inventory_known
            if stock_exact:
                stock_line = f"Stock {max(0, int(tracked.ship)) + max(0, int(tracked.carrier)):,} T"
            elif self.ship_inventory_known:
                stock_line = f"Stock {max(0, int(tracked.ship)):,}+? T"
            else:
                stock_line = "Stock …"
            if remaining <= 0:
                source = "Delivered"
            elif tracked.acquisition_needed == 0:
                source = "On ship/carrier"
            else:
                source = tracked.source.strip() if tracked.source else ""
                if self._is_placeholder_source(source):
                    source = "Paste Location"
            return (
                f"{tracked.commodity}: {remaining:,} left",
                stock_line,
                stock_exact,
                f"Trips {trips}",
                f"Source: {source}",
            )

        needed = [row for row in rows if row.delivery_remaining > 0]
        if not needed:
            return ("Materials: complete", "Stock —", False, "Trips 0", "Source: —")
        needed.sort(key=lambda row: row.delivery_remaining, reverse=True)
        top = needed[0]
        stock_exact = self.ship_inventory_known and self.carrier_inventory_known
        if stock_exact:
            stock_line = f"Stock {max(0, int(top.ship)) + max(0, int(top.carrier)):,} T"
        elif self.ship_inventory_known:
            stock_line = f"Stock {max(0, int(top.ship)):,}+? T"
        else:
            stock_line = "Stock …"
        total_left = sum(row.delivery_remaining for row in needed)
        trips = (total_left + capacity - 1) // capacity
        if all(row.acquisition_needed == 0 for row in needed):
            source = "On ship/carrier"
        else:
            buy_row = max(needed, key=lambda row: row.acquisition_needed)
            source = buy_row.source.strip() if buy_row.source else ""
            if self._is_placeholder_source(source):
                source = "Paste Location"
        return (
            f"{top.commodity}: {top.delivery_remaining:,} left",
            stock_line,
            stock_exact,
            f"Trips {trips}",
            f"Source: {source}",
        )

    def focus_material_progress_percent(self) -> int:
        """Delivered-material percentage for the pinned construction job."""
        _title, _detail, _source, progress = self._next_action_data()
        return max(0, min(100, int(progress)))

    def set_view_name(self, name: str) -> None:
        mapping = {"Overview": 0, "Build Queue": 1, "Materials": 2, "System Layout": 3, "Sites": 3}
        self.tabs.setCurrentIndex(mapping.get(name, 0))

    def view_name(self) -> str:
        return self.tabs.tabText(self.tabs.currentIndex())
