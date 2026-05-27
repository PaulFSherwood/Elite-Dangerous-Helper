from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush, QTextCursor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QHeaderView,
    QPushButton,
    QFrame,
    QSizePolicy,
    QComboBox,
)

from journal import JournalMonitor
from state import BodyInfo
from rules import bio_key
from ships import friendly_ship_icon_path, friendly_ship_name, on_foot_icon_path
from search_targets import SEARCH_TYPES, get_items_for_type, get_rule_description


def load_stylesheet() -> str:
    style_path = Path(__file__).resolve().parent / "styles" / "dashboard.qss"
    if not style_path.exists():
        return ""
    return style_path.read_text(encoding="utf-8")

class OverlayWindow(QWidget):
    def set_alert_style(self, active: bool) -> None:
        value = "true" if active else "false"
        for widget in (self.special_card, self.special_icon_label):
            widget.setProperty("alert", value)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def has_bio(self, body: BodyInfo) -> bool:
        return bool(body.bio_signals and body.bio_signals > 0)

    def bio_complete(self, body: BodyInfo) -> bool:
        if not self.has_bio(body):
            return False

        if not body.bio_completed_species:
            return False

        expected = body.bio_expected_genuses if body.bio_expected_genuses else body.bio_species

        if expected:
            return all(
                self.bio_name_completed(expected_name, body.bio_completed_species)
                for expected_name in expected
            )

        return len(body.bio_completed_species) >= body.bio_signals

    def update_info_card(
        self,
        card: QFrame,
        icon: str,
        title: str,
        value: str,
        icon_path: Optional[Path] = None,
    ) -> None:
        layout = card.layout()
        if layout is None:
            return

        icon_label = layout.itemAt(0).widget()
        text_layout = layout.itemAt(1).layout()

        if icon_label:
            if icon_path and icon_path.exists():
                pixmap = QPixmap(str(icon_path))
                pixmap = pixmap.scaled(
                    30,
                    30,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                icon_label.setPixmap(pixmap)
                icon_label.setText("")
            else:
                icon_label.setPixmap(QPixmap())
                icon_label.setText(icon)

        if text_layout:
            title_label = text_layout.itemAt(0).widget()
            value_label = text_layout.itemAt(1).widget()

            if title_label:
                title_label.setText(title)
            if value_label:
                value_label.setText(value)

    def update_search_rules_label(self) -> None:
        search_type = self.search_type_combo.currentText()
        search_item = self.search_item_combo.currentText()
    
        if search_type == "None" or search_item == "None":
            self.search_rules_label.setText("Search: none")
            return
    
        rule = get_rule_description(search_type, search_item)
    
        conditions = rule.get("conditions", [])
        match = rule.get("match", "")
    
        if conditions:
            condition_text = " | ".join(conditions)
        else:
            condition_text = "No rule defined"
    
        self.search_rules_label.setText(
            f"{search_item}: {condition_text}    Match: {match}"
        )

    def update_search_item_dropdown(self) -> None:
        search_type = self.search_type_combo.currentText()
        items = get_items_for_type(search_type)

        self.search_item_combo.blockSignals(True)
        self.search_item_combo.clear()

        if not items:
            self.search_item_combo.addItem("None")
            self.search_item_combo.setEnabled(False)
        else:
            self.search_item_combo.addItems(items)
            self.search_item_combo.setEnabled(True)

        self.search_item_combo.blockSignals(False)
        self.update_search_rules_label()

    def make_info_card(self, icon: str, title: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("infoCard")

        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        icon_label = QLabel(icon)
        icon_label.setObjectName("cardIcon")
        icon_label.setFixedSize(34, 34)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        text_box = QVBoxLayout()
        text_box.setSpacing(1)

        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        title_label.setMinimumWidth(0)
        title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        value_label = QLabel(value)
        value_label.setObjectName("cardValue")
        value_label.setMinimumWidth(0)
        value_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        text_box.addWidget(title_label)
        text_box.addWidget(value_label)

        layout.addWidget(icon_label)
        layout.addLayout(text_box, stretch=1)

        return card

    def __init__(self, monitor: JournalMonitor, always_on_top: bool = True):
        flags = Qt.WindowType.Window
        if always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint

        super().__init__(flags=flags)
        self.monitor = monitor

        self.resize(1280, 760)
        self.setMinimumSize(900, 500)

        self.opacity_enabled = True
        self.normal_opacity = 0.78
        self.solid_opacity = 1.0

        self.setWindowTitle("Paul Observatory")
        icon_path = Path(__file__).resolve().parent / "assets" / "ed_helper_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setWindowOpacity(self.normal_opacity)

        self.system_label = QLabel()
        self.ship_label = QLabel()
        self.location_label = QLabel()
        self.count_label = QLabel()
        self.special_card = QFrame()
        self.special_card.setObjectName("specialCard")
        
        self.special_icon_label = QLabel("✦")
        self.special_icon_label.setObjectName("specialIcon")

        self.special_label = QLabel("Special: none detected in this system")
        self.special_label.setObjectName("specialText")

        self.search_type_combo = QComboBox()
        self.search_type_combo.addItems(SEARCH_TYPES.keys())
        self.search_type_combo.setObjectName("searchCombo")

        self.search_item_combo = QComboBox()
        self.search_item_combo.setObjectName("searchCombo")

        self.search_type_combo.currentTextChanged.connect(self.update_search_item_dropdown)
        self.search_item_combo.currentTextChanged.connect(self.update_search_rules_label)

        special_layout = QHBoxLayout(self.special_card)
        special_layout.setContentsMargins(14, 8, 14, 8)
        special_layout.setSpacing(10)

        self.search_rules_label = QLabel("No search target selected")
        self.search_rules_label.setObjectName("searchRulesLabel")

        special_layout.addWidget(self.special_icon_label)
        special_layout.addWidget(self.special_label, stretch=1)
        special_layout.addWidget(self.search_type_combo)
        special_layout.addWidget(self.search_item_combo)
        special_layout.addWidget(self.search_rules_label, stretch=1)

        self.update_search_item_dropdown()
        self.update_search_rules_label()

        self.log_title_label = QLabel("Journal Log")
        self.log_title_label.setObjectName("sectionTitle")

        self.legend_title_label = QLabel("Legend")
        self.legend_title_label.setObjectName("sectionTitle")

        self.footer_label = QLabel()
        self.footer_label.setObjectName("footerLabel")

        self.ship_card = QFrame()
        self.mode_card = QFrame()
        self.location_card = QFrame()
        self.bodies_card = QFrame()
        self.other_card = QFrame()
        self.high_value_card = QFrame()
        self.bio_card = QFrame()

        self.legend_label = QLabel("""
        <table cellspacing="6" cellpadding="2">
        <tr>
        <td><b>Bio Progress</b></td>
        <td><span style="background-color:#3A3A3A; color:#3A3A3A;">■■</span> expected</td>
        <td><span style="background-color:#1F5A32; color:#1F5A32;">■■</span> found</td>
        <td><span style="background-color:#CBC3E3; color:#CBC3E3;">■■</span> complete</td>
        </tr>
        <tr>
        <td><b>DSS</b></td>
        <td><span style="background-color:#A16207; color:#A16207;">■■</span> needed</td>
        <td><span style="background-color:#2E7D32; color:#2E7D32;">■■</span> complete</td>
        <td><span style="background-color:#26323D; color:#26323D;">■■</span> not applicable</td>
        </tr>
        <tr>
        <td><b>Rows</b></td>
        <td><span style="background-color:#4A1F24; color:#4A1F24;">■■</span> high-value unmapped</td>
        <td><span style="background-color:#17324A; color:#17324A;">■■</span> high-value mapped</td>
        <td><span style="background-color:#1F5A32; color:#1F5A32;">■■</span> bio signals</td>
        </tr>
        </table>
        """)
        self.legend_label.setTextFormat(Qt.TextFormat.RichText)
        self.legend_label.setObjectName("legendLabel")

        self.legend_label.setObjectName("legendLabel")

        self.opacity_button = QPushButton("●\n│\n○")
        self.opacity_button.setToolTip("Toggle transparency / solid")
        self.opacity_button.setFixedSize(28, 58)
        self.opacity_button.clicked.connect(self.toggle_opacity)
        self.opacity_button.setObjectName("opacityButton")

        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)

        self.table.setHorizontalHeaderLabels(
            ["ID", "Body", "Type", "Class", "Distance", "Bio", "Geo", "DSS", "Bio Progress", "Recommendation"]
        )

        table_header = self.table.horizontalHeader()

        for col in range(10):
            table_header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        # Body gets the extra width
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        # Recommendation stays fixed so it cannot steal width.
        table_header.setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(9, 80)

        # Bio Progress gets the extra width.
        table_header.setSectionResizeMode(8, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(8, 320)

        table_header.setStretchLastSection(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(70)
        self.log_box.setMaximumHeight(80)

        header = QVBoxLayout()
        header.setSpacing(10)

        # Top route card: System / Target / Final / Event
        route_card = QFrame()
        route_card.setObjectName("wideCard")

        route_layout = QHBoxLayout(route_card)
        route_layout.setContentsMargins(12, 8, 12, 8)
        route_layout.setSpacing(10)

        self.system_card = self.make_info_card("◎", "System", "Unknown")
        self.target_card = self.make_info_card("➜", "Target", "none")
        self.final_card = self.make_info_card("◆", "Final", "none")
        self.event_card = self.make_info_card("✦", "Event", "?")

        route_layout.addWidget(self.system_card, stretch=2)
        route_layout.addWidget(self.target_card, stretch=2)
        route_layout.addWidget(self.final_card, stretch=2)
        route_layout.addWidget(self.event_card, stretch=1)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(route_card, stretch=1)
        top_row.addWidget(self.opacity_button, stretch=0)

        # Middle left card: Ship / Mode / Location
        ship_status_card = QFrame()
        ship_status_card.setObjectName("wideCard")

        ship_row = QHBoxLayout(ship_status_card)
        ship_row.setContentsMargins(12, 8, 12, 8)
        ship_row.setSpacing(10)

        self.ship_card = self.make_info_card("🚀", "Ship", "Unknown ship")
        self.mode_card = self.make_info_card("🧭", "Mode", "Unknown")
        self.location_card = self.make_info_card("📍", "Location", "space")

        ship_row.addWidget(self.ship_card, stretch=2)
        ship_row.addWidget(self.mode_card, stretch=1)
        ship_row.addWidget(self.location_card, stretch=2)

        # Middle right card: Bodies / Other / High-value / Bio
        summary_status_card = QFrame()
        summary_status_card.setObjectName("wideCard")

        summary_row = QHBoxLayout(summary_status_card)
        summary_row.setContentsMargins(12, 8, 12, 8)
        summary_row.setSpacing(10)

        self.bodies_card = self.make_info_card("◎", "Bodies", "? / ?")
        self.other_card = self.make_info_card("✦", "Other", "0")
        self.high_value_card = self.make_info_card("◇", "High-value", "0")
        self.bio_card = self.make_info_card("☘", "Bio bodies", "0")

        summary_row.addWidget(self.bodies_card)
        summary_row.addWidget(self.other_card)
        summary_row.addWidget(self.high_value_card)
        summary_row.addWidget(self.bio_card)

        middle_row = QHBoxLayout()
        middle_row.setSpacing(10)
        middle_row.addWidget(ship_status_card, stretch=1)
        middle_row.addWidget(summary_status_card, stretch=1)

        # Final header order
        header.addWidget(self.special_card)
        header.addLayout(top_row)
        header.addLayout(middle_row)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)
        
        log_card = QFrame()
        log_card.setObjectName("bottomCard")
        log_card.setMaximumHeight(115)

        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(10, 6, 10, 10)
        log_layout.setSpacing(2)

        self.log_title_label.setFixedHeight(18)

        log_layout.addWidget(self.log_title_label)
        log_layout.addWidget(self.log_box)
        log_layout.addStretch(0)
        
        legend_card = QFrame()
        legend_card.setObjectName("bottomCard")
        legend_card.setMaximumHeight(115)

        legend_layout = QVBoxLayout(legend_card)
        legend_layout.setContentsMargins(10, 6, 10, 8)
        legend_layout.setSpacing(2)

        self.legend_title_label.setFixedHeight(18)

        legend_layout.addWidget(self.legend_title_label)
        legend_layout.addWidget(self.legend_label)
        
        bottom_row.addWidget(log_card, stretch=2)
        bottom_row.addWidget(legend_card, stretch=1)
        
        layout = QVBoxLayout()
        layout.addLayout(header)
        layout.addWidget(self.table, stretch=1)
        layout.addLayout(bottom_row, stretch=0)
        layout.addWidget(self.footer_label)
        self.setLayout(layout)

        self.setStyleSheet(load_stylesheet())


        self.monitor.updated.connect(self.refresh)
        self.refresh()

    def is_high_value_world(self, body: BodyInfo) -> bool:
        subtype = (body.subtype or "").lower()
        terraform = (body.terraform_state or "").lower()

        return (
            "earthlike" in subtype
            or "earth-like" in subtype
            or "water world" in subtype
            or "ammonia world" in subtype
            or (
                "high metal content" in subtype
                and "terraform" in terraform
            )
            or (
                "rocky body" in subtype
                and "terraform" in terraform
            )
        )

    def priority_text(self, body: BodyInfo) -> str:
        if self.is_high_value_world(body):
            subtype = body.subtype or "High value body"
            terraform = " Terraformable" if "terraform" in (body.terraform_state or "").lower() else ""
            note = f" | {body.special_note}" if body.special_note else ""

            if body.mapped is True:
                return f"{terraform} {subtype} - mapped{note}".strip()

            return f"{terraform} {subtype} - DSS NEEDED{note}".strip()

        if body.bio_signals and body.bio_signals > 0:
            if self.bio_complete(body):
                return "Bio complete"
            return "Bio signals"

        if body.scanned is False:
            return "Not FSS scanned"

        if body.kind == "Planet" and body.mapped is False:
            return "Not mapped"

        if body.special_note:
            return body.special_note

        return ""

    def bio_key(self, name: str) -> str:
        return bio_key(name)

    def bio_name_started(self, expected_name: str, known_names: list[str]) -> bool:
        expected_key = self.bio_key(expected_name)

        for known in known_names:
            known_key = self.bio_key(known)
            if known_key == expected_key:
                return True

        return False

    def bio_name_completed(self, expected_name: str, completed_names: list[str]) -> bool:
        expected_key = self.bio_key(expected_name)

        for completed in completed_names:
            completed_key = self.bio_key(completed)
            if completed_key == expected_key:
                return True

        return False

    def make_class_pill_widget(self, text: str, color: str, text_color: str = "#FFFFFF", row_color: str = "transparent", ) -> QWidget:
        container = QWidget()
        container.setStyleSheet(f"QWidget {{ background-color: {row_color}; }}")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        label = QLabel(text)
        label.setFixedHeight(24)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                color: {text_color};
                border-radius: 6px;
                padding: 1px 8px;
                font-weight: bold;
            }}
        """)

        layout.addWidget(label)
        layout.addStretch()
        return container

    def make_bio_status_widget(self, body: BodyInfo) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        expected = body.bio_expected_genuses[:] if body.bio_expected_genuses else body.bio_species[:]

        # If we only know "3 biological signals" but not names yet,
        # show Bio 1 / Bio 2 / Bio 3.
        if not expected and body.bio_signals:
            expected = [f"Bio {i + 1}" for i in range(body.bio_signals)]

        started_keys = {bio_key(name) for name in body.bio_species if name}
        completed_keys = {bio_key(name) for name in body.bio_completed_species if name}

        for index, name in enumerate(expected):
            key = bio_key(name)

            # Expected genus names such as "Fungoida" should match scanned
            # species names such as "Fungoida Bullarum".
            done = key in completed_keys
            started = key in started_keys

            # Fallback for placeholder Bio 1 / Bio 2 / Bio 3 when names are unknown.
            if name.startswith("Bio "):
                done = index < len(body.bio_completed_species)
                started = index < len(body.bio_species)

            if done:
                label_text = f"✓ {name}"
                color = "#CBC3E3"      # completed final Analyse / 3-of-3
                text_color = "#000000"
            elif started:
                label_text = f"• {name}"
                color = "#1F5A32"      # found / sampling started
                text_color = "#FFFFFF"
            else:
                label_text = name
                color = "#3A3A3A"      # expected but not found yet
                text_color = "#DDDDDD"

            label = QLabel(label_text)
            label.setFixedHeight(24)
            label.setMinimumWidth(80)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            label.setStyleSheet(f"""
                QLabel {{
                    background-color: {color};
                    color: {text_color};
                    border-radius: 5px;
                    padding: 1px 2px;
                }}
            """)

            layout.addWidget(label)

        layout.addStretch()
        return container


    def toggle_opacity(self) -> None:
        self.opacity_enabled = not self.opacity_enabled

        if self.opacity_enabled:
            self.setWindowOpacity(self.normal_opacity)
            self.opacity_button.setText("●\n│\n○")
        else:
            self.setWindowOpacity(self.solid_opacity)
            self.opacity_button.setText("○\n│\n●")

    def refresh(self) -> None:
        state = self.monitor.state

        if state.special_alerts:
            self.special_icon_label.setText("✦")
            self.special_label.setText(f"Special: {state.special_alerts[-1]}")
            self.set_alert_style(True)
        else:
            self.special_icon_label.setText("✦")
            self.special_label.setText("Special: none detected in this system")
            self.set_alert_style(False)

        system = state.system or "Unknown system"
        target = state.nav_target or "none"
        final = state.nav_final or "none"

        self.update_info_card(self.system_card, "◎", "System", system)
        self.update_info_card(self.target_card, "➜", "Target", target)
        self.update_info_card(self.final_card, "◆", "Final", final)
        self.update_info_card(self.event_card, "✦", "Event", state.last_event or "?")

        ship = state.ship_name or friendly_ship_name(state.ship)
        mode = "On Foot" if state.on_foot else "In Ship"
        
        ship_icon_path = on_foot_icon_path() if state.on_foot else friendly_ship_icon_path(state.ship)
        
        self.update_info_card(
            self.ship_card,
            "🚀",
            "Ship",
            ship,
            icon_path=ship_icon_path,
        )
        
        self.update_info_card(self.mode_card, "🧭", "Mode", mode)

        where = state.station or state.body or "space"
        latlon = ""
        if state.latitude is not None and state.longitude is not None:
            latlon = f"  {state.latitude:.2f}, {state.longitude:.2f}"

        self.update_info_card(self.location_card, "📍", "Location", f"{where}{latlon}")

        planet_star_scanned_count = len([
            b for b in state.bodies.values()
            if b.scanned and b.kind in ("Planet", "Star")
        ])

        other_scanned_count = len([
            b for b in state.bodies.values()
            if b.scanned and b.kind not in ("Planet", "Star")
        ])

        total = state.body_count if state.body_count is not None else "?"

        high_value_unmapped = [
            b for b in state.bodies.values()
            if self.is_high_value_world(b) and b.mapped is not True
        ]

        bio_bodies = [
            b for b in state.bodies.values()
            if b.bio_signals and b.bio_signals > 0
        ]

        other_text = ""
        if other_scanned_count > 0:
            other_text = f"    Other scanned: {other_scanned_count}"

        self.update_info_card(
            self.bodies_card,
            "◎",
            "Bodies",
            f"{planet_star_scanned_count} / {total}",
        )
        
        self.update_info_card(
            self.other_card,
            "✦",
            "Other scanned",
            str(other_scanned_count),
        )
        
        self.update_info_card(
            self.high_value_card,
            "◇",
            "High-value",
            str(len(high_value_unmapped)),
        )
        
        self.update_info_card(
            self.bio_card,
            "☘",
            "Bio bodies",
            str(len(bio_bodies)),
        )

        def body_sort_key(b: BodyInfo):
            high_value_unmapped = self.is_high_value_world(b) and b.mapped is not True
            has_bio = b.bio_signals and b.bio_signals > 0
            high_value_mapped = self.is_high_value_world(b) and b.mapped is True
            not_mapped = b.mapped is False
            not_scanned = b.scanned is False

            if high_value_unmapped:
                priority = 0
            elif has_bio:
                priority = 1
            elif high_value_mapped:
                priority = 2
            elif not_mapped:
                priority = 3
            elif not_scanned:
                priority = 4
            else:
                priority = 5

            return (
                priority,
                b.distance_ls is None,
                b.distance_ls if b.distance_ls is not None else 999999999,
                b.body_id if b.body_id is not None else 999999,
                b.name,
            )

        bodies = sorted(
                state.bodies.values(),
                key=body_sort_key,
                )

        self.table.setRowCount(len(bodies))

        for row, body in enumerate(bodies):
            high_value = self.is_high_value_world(body)
            can_be_dss_mapped = body.kind == "Planet"
            mapped_text = "" if not can_be_dss_mapped or body.mapped is None else ("Yes" if body.mapped else "No")
            priority = self.priority_text(body)

            values = [
                "" if body.body_id is None else str(body.body_id),
                body.name,
                body.kind,
                body.subtype,
                "" if body.distance_ls is None else f"{body.distance_ls:.1f}",
                "" if body.bio_signals is None else str(body.bio_signals),
                "" if body.geo_signals is None else str(body.geo_signals),
                mapped_text,
                body.bio_status,
                priority,
            ]

            for col, value in enumerate(values):
                item = QTableWidgetItem(value)

                # Row background meanings:
                # dark red/orange = Earth-like or Water World not DSS mapped
                # dark blue = Earth-like or Water World already mapped
                # dark green = biological signals
                # dark gray = known body but not fully scanned/classified yet

                if high_value and body.mapped is not True:
                    item.setBackground(QBrush(QColor("#4A1F24")))
                    item.setForeground(QBrush(QColor("#FFFFFF")))

                elif high_value and body.mapped is True:
                    item.setBackground(QBrush(QColor("#17324A")))
                    item.setForeground(QBrush(QColor("#FFFFFF")))

                elif body.bio_signals and body.bio_signals > 0:
                    # Do not color the whole row for bio.
                    # Bio status should only affect Bio Status and Priority columns.
                    if col == 9:
                        if self.bio_complete(body):
                            item.setBackground(QBrush(QColor("#CBC3E3")))  # completed bio
                            item.setForeground(QBrush(QColor("#000000")))
                        else:
                            item.setBackground(QBrush(QColor("#1F5A32")))  # bio still needs work
                            item.setForeground(QBrush(QColor("#FFFFFF")))

                elif body.scanned is False:
                    item.setBackground(QBrush(QColor("#26323D")))
                    item.setForeground(QBrush(QColor("#DDDDDD")))

                # Make the Mapped cell extra obvious.
                # Make the DSS cell look like a small status pill.
                if col == 7 and can_be_dss_mapped:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                    if high_value and body.mapped is not True:
                        item.setText("DSS Needed")
                        item.setBackground(QBrush(QColor("#7F1D1D")))
                        item.setForeground(QBrush(QColor("#FFFFFF")))
                    elif body.mapped is False:
                        item.setText("No")
                        item.setBackground(QBrush(QColor("#A16207")))
                        item.setForeground(QBrush(QColor("#FFFFFF")))
                    elif body.mapped is True:
                        item.setText("Yes")
                        item.setBackground(QBrush(QColor("#2E7D32")))
                        item.setForeground(QBrush(QColor("#FFFFFF")))

                self.table.setItem(row, col, item)

                # Class column pill for special world types.
                subtype_lower = (body.subtype or "").lower()
                row_color = "transparent"

                if high_value and body.mapped is not True:
                    row_color = "#4A1F24"
                elif high_value and body.mapped is True:
                    row_color = "#17324A"
                elif body.scanned is False:
                    row_color = "#26323D"

                if "earthlike" in subtype_lower or "earth-like" in subtype_lower:
                    self.table.setCellWidget(
                        row,
                        3,
                        self.make_class_pill_widget(body.subtype, "#1F5A32", row_color=row_color),
                    )
                elif "water world" in subtype_lower:
                    self.table.setCellWidget(
                        row,
                        3,
                        self.make_class_pill_widget(body.subtype, "#1F4F6B", row_color=row_color),
                    )
                else:
                    self.table.removeCellWidget(row, 3)

            # Bios Status pill split
            if body.bio_signals and body.bio_signals > 0:
                self.table.setCellWidget(row, 8, self.make_bio_status_widget(body))
                self.table.setRowHeight(row, 32)
            else:
                self.table.removeCellWidget(row, 8)

        commander = state.commander or "Unknown"
        footer_ship = state.ship_name or friendly_ship_name(state.ship)

        self.footer_label.setText(
            f"Commander: {commander}        Ship: {footer_ship}        Elite Dangerous Journal Helper        v1.1.0-dev"
        )

        # Keep rows compact even when Bio progress contains widgets
        for row in range(self.table.rowCount()):
            self.table.setRowHeight(row, 32)
        # auto scroll
        self.log_box.setPlainText("\n".join(state.messages))
        self.log_box.moveCursor(QTextCursor.MoveOperation.End)

    def closeEvent(self, event) -> None:
        self.monitor.stop()
        event.accept()
