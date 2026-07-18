from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QSettings, QSize, QRect
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
    QButtonGroup,
)

from journal import JournalMonitor
from state import BodyInfo
from rules import bio_key
from bio_icons import bio_icon_html
from ships import friendly_ship_icon_path, friendly_ship_name, on_foot_icon_path
from search_targets import SEARCH_TYPES, get_items_for_type, get_rule_description, evaluate_search_target

WINDOW_WIDTH = 1270
WINDOW_HEIGHT = 715

WINDOW_MIN_WIDTH = 900
WINDOW_MIN_HEIGHT = 500

SPECIAL_HEIGHT = 92
ROUTE_HEIGHT = 70
STATUS_HEIGHT = 70

TABLE_MIN_HEIGHT = 270

BOTTOM_HEIGHT = 135
FOOTER_HEIGHT = 28

HEADER_SPACING = 5
ROW_SPACING = 10

VERSION = "v2.6.1"
THIN_HEIGHT = 48
THIN_MIN_WIDTH = 760

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

    def calculate_bio_progress_width(self, bodies: list[BodyInfo]) -> int:
        min_width = 320
        max_width = 640
    
        pill_padding = 28      # left/right padding inside each pill
        pill_spacing = 6       # space between pills
        container_padding = 12 # table cell/layout padding
    
        widest = min_width
    
        font_metrics = self.fontMetrics()
    
        for body in bodies:
            expected = body.bio_expected_genuses[:] if body.bio_expected_genuses else body.bio_species[:]
    
            if not expected and body.bio_signals:
                expected = [f"Bio {i + 1}" for i in range(body.bio_signals)]
    
            if not expected:
                continue
    
            row_width = container_padding
    
            for name in expected:
                text_width = font_metrics.horizontalAdvance(name)
                row_width += text_width + pill_padding + pill_spacing
    
            widest = max(widest, row_width)
    
        return min(max(widest, min_width), max_width)

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

    def search_selection_changed(self) -> None:
        state = self.monitor.state
        bodies = list(state.bodies.values())

        if bodies:
            self.update_search_rules_from_bodies(bodies)
        else:
            self.update_search_rules_label()

    def update_search_rules_label(self) -> None:
        if hasattr(self, "search_rules_card"):
            self.search_rules_card.setProperty("confirmed", "false")
            self.search_rules_card.style().unpolish(self.search_rules_card)
            self.search_rules_card.style().polish(self.search_rules_card)
            self.search_rules_card.update()

        search_type = self.search_type_combo.currentText().replace("⚒ ", "").replace("⚙ ", "")
        search_item = self.search_item_combo.currentText()
        search_type = self.clean_search_type()
        search_item = self.clean_search_item()

        if search_type == "None" or search_item == "None":
            self.search_rules_label.setText(
                "<b style='color:#60A5FA;'>Search target</b><br>"
                "No target selected."
            )
            return

        rule = get_rule_description(search_type, search_item)
        conditions = rule.get("conditions", [])
        match = rule.get("match", "")

        condition_text = " &nbsp;&nbsp;&nbsp;&nbsp; ".join(
            f"<span style='color:#EF4444;'>●</span> {condition}"
            for condition in conditions
        )

        if not condition_text:
            condition_text = "No rule defined"

        self.search_rules_label.setText(
            f"<b style='color:#60A5FA;'>{search_type}: {search_item}</b><br>"
            f"{condition_text}<br>"
            f"<span style='color:#9FB0BF;'>Watching:</span> {match}"
        )

    def clean_search_type(self) -> str:
        return (
            self.search_type_combo.currentText()
            .replace("⚒ ", "")
            .replace("⚙ ", "")
        )
    
    
    def clean_search_item(self) -> str:
        return (
            self.search_item_combo.currentText()
            .replace("💎 ", "")
            .replace("⚛ ", "")
        )

    def update_search_item_dropdown(self) -> None:
        search_type = self.search_type_combo.currentText().replace("⚒ ", "").replace("⚙ ", "")
        search_type = self.clean_search_type()
        search_item = self.clean_search_item()
        items = get_items_for_type(search_type)

        self.search_item_combo.blockSignals(True)
        self.search_item_combo.clear()

        if not items:
            self.search_item_combo.addItem("None")
            self.search_item_combo.setEnabled(False)
        else:
            for item in items:
                if search_type == "Mining":
                    self.search_item_combo.addItem(f"💎 {item}")
                elif search_type == "Engineering":
                    self.search_item_combo.addItem(f"⚛ {item}")
                else:
                    self.search_item_combo.addItem(item)
            self.search_item_combo.setEnabled(True)

        self.search_item_combo.blockSignals(False)
        # self.update_search_rules_label()
        self.search_selection_changed()

    def set_table_filter(self, mode: str) -> None:
        self.table_filter_mode = mode

        for button in self.table_filter_buttons:
            is_active = button.text() == mode
            button.setChecked(is_active)
            button.setProperty("active", "true" if is_active else "false")
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()

        if hasattr(self, "table"):
            self.refresh()

    def make_table_filter_button(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("tableFilterButton")
        button.setCheckable(True)
        button.setMinimumHeight(24)
        button.clicked.connect(lambda _checked=False, mode=text: self.set_table_filter(mode))
        return button

    def search_result_for_body(self, body: BodyInfo) -> dict:
        search_type = self.search_type_combo.currentText().replace("⚒ ", "").replace("⚙ ", "")
        search_item = self.search_item_combo.currentText()
        return evaluate_search_target(search_type, search_item, body)

    def body_passes_filter(self, body: BodyInfo) -> bool:
        mode = getattr(self, "table_filter_mode", "All")

        if mode == "All":
            return True

        high_value = self.is_high_value_world(body)
        search_text = self.search_result_for_body(body).get("match_text", "")

        if mode == "Action":
            return bool(
                search_text
                or body.special_note
                or (high_value and body.mapped is not True)
                or (body.bio_signals and body.bio_signals > 0 and not self.bio_complete(body))
                or (body.kind == "Planet" and body.mapped is False)
                or body.scanned is False
            )

        if mode == "Bio":
            return bool(body.bio_signals and body.bio_signals > 0)

        if mode == "High-value":
            return high_value

        if mode == "Search":
            return bool(search_text)

        return True

    def bio_progress_summary(self, body: BodyInfo) -> str:
        if not body.bio_signals or body.bio_signals <= 0:
            return ""

        expected = body.bio_expected_genuses[:] if body.bio_expected_genuses else body.bio_species[:]
        expected_count = len(expected) if expected else body.bio_signals
        completed_count = len(body.bio_completed_species)

        # Completed species often includes both genus and species labels. Cap the
        # display so it does not claim more than the expected biological count.
        completed_count = min(completed_count, expected_count)
        remaining = max(expected_count - completed_count, 0)

        if remaining == 0 and completed_count > 0:
            return f"Bio complete {completed_count}/{expected_count}"

        return f"Bio {completed_count}/{expected_count} — {remaining} remaining"

    def notes_for_body(self, body: BodyInfo) -> str:
        notes: list[str] = []
        search_text = self.search_result_for_body(body).get("match_text", "")

        if search_text:
            notes.append(search_text)

        high_value = self.is_high_value_world(body)
        if high_value and body.mapped is not True:
            notes.append("High-value — DSS needed")
        elif high_value and body.mapped is True:
            notes.append("High-value mapped")

        bio_summary = self.bio_progress_summary(body)
        if bio_summary:
            notes.append(bio_summary)

        if body.kind == "Planet" and body.mapped is False and not high_value:
            notes.append("Unmapped planet")

        if body.scanned is False:
            notes.append("Not FSS scanned")

        if body.special_note:
            notes.append(body.special_note)

        return " • ".join(notes)

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

    def make_stat_chip(self, icon: str, tooltip: str) -> QLabel:
        label = QLabel(f"{icon} —")
        label.setObjectName("commanderStatChip")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setToolTip(tooltip)
        label.setMinimumWidth(104)
        label.setMinimumHeight(30)
        label.setTextFormat(Qt.TextFormat.RichText)

        return label

    def make_route_separator(self) -> QFrame:
        separator = QFrame()
        separator.setObjectName("routeSeparator")
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFixedWidth(1)
        return separator

    def __init__(self, monitor: JournalMonitor, always_on_top: bool = True):
        # ------------------------------------------------------------------
        # 1. Window setup
        #
        # This is only the outer window shell:
        #   - window flags
        #   - starting size
        #   - opacity defaults
        #   - window title/icon
        #
        # Nothing layout-related should be placed before widgets exist.
        # ------------------------------------------------------------------

        flags = Qt.WindowType.Window
        if always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint

        super().__init__(flags=flags)
        self.monitor = monitor
        self.settings = QSettings("GrrWooD", "EliteDangerousObservatory")
        self.thin_mode = False
        self.full_size = QSize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.full_geometry = self.geometry()
        self.thin_target_system: Optional[str] = None
        self.thin_known_targets: set[str] = set()

        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        self.opacity_enabled = True
        self.normal_opacity = 0.78
        self.solid_opacity = 1.0

        self.setWindowTitle("Observatory")

        icon_path = Path(__file__).resolve().parent / "assets" / "ed_helper_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setWindowOpacity(self.normal_opacity)

        # ------------------------------------------------------------------
        # 2. Special/search row widgets
        #
        # Visual order:
        #   [special icon] [special alert text] [search type] [search item] [rules text]
        #
        # This is the top-most content row in the mockup.
        # ------------------------------------------------------------------

        self.special_card = QFrame()
        self.special_card.setObjectName("specialCard")

        self.special_icon_label = QLabel("✦")
        self.special_icon_label.setObjectName("specialIcon")

        self.special_label = QLabel("No special signals")
        self.special_label.setObjectName("specialText")

        self.search_type_combo = QComboBox()
        self.search_type_combo.setObjectName("searchCombo")

        self.search_type_combo.addItem("None")
        self.search_type_combo.addItem("⚒ Mining")
        self.search_type_combo.addItem("⚙ Engineering")

        self.search_item_combo = QComboBox()
        self.search_item_combo.setObjectName("searchCombo")

        self.search_rules_label = QLabel("Search: none")
        self.search_rules_label.setObjectName("searchRulesLabel")

        self.search_rules_label.setTextFormat(Qt.TextFormat.RichText)
        self.search_rules_label.setWordWrap(True)

        special_layout = QHBoxLayout(self.special_card)
        special_layout.setContentsMargins(14, 8, 14, 8)
        special_layout.setSpacing(10)

        # Left side: special alert message.
        # Left side: special alert message.
        special_message_card = QFrame()
        special_message_card.setObjectName("specialMessageCard")
        special_message_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        
        special_message_layout = QHBoxLayout(special_message_card)
        special_message_layout.setContentsMargins(12, 6, 14, 6)
        special_message_layout.setSpacing(8)
        
        self.special_icon_label.setFixedWidth(28)
        self.special_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.special_label.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Preferred,
        )
        
        special_message_layout.addWidget(self.special_icon_label)
        special_message_layout.addWidget(self.special_label)

        # Middle: dropdown card.
        search_select_card = QFrame()
        search_select_card.setObjectName("searchSelectCard")

        search_select_layout = QHBoxLayout(search_select_card)
        search_select_layout.setContentsMargins(12, 6, 12, 6)
        search_select_layout.setSpacing(8)

        search_select_title = QLabel("Looking for:")
        search_select_title.setObjectName("searchCardTitle")

        search_select_layout.addWidget(search_select_title)
        search_select_layout.addWidget(self.search_type_combo)
        search_select_layout.addWidget(self.search_item_combo)

        # Right side: rules card.
        self.search_rules_card = QFrame()
        self.search_rules_card.setObjectName("searchRulesCard")

        search_rules_layout = QVBoxLayout(self.search_rules_card)
        search_rules_layout.setContentsMargins(12, 6, 12, 6)
        search_rules_layout.setSpacing(2)
        search_rules_layout.addWidget(self.search_rules_label)

        # Full special/search row.
        special_layout.addWidget(special_message_card, stretch=1)
        special_layout.addWidget(search_select_card, stretch=1)
        special_layout.addWidget(self.search_rules_card, stretch=1)

        # Connect the dropdowns after they exist.
        self.search_type_combo.currentTextChanged.connect(self.update_search_item_dropdown)
        self.search_item_combo.currentTextChanged.connect(self.search_selection_changed)

        # Populate the second dropdown based on the first dropdown,
        # then evaluate the selected search target against already-loaded journal history.
        self.update_search_item_dropdown()

        # ------------------------------------------------------------------
        # 3. Route/system row widgets
        #
        # Visual order:
        #   System | Target | Final | Event | opacity toggle
        #
        # route_card holds the four info cards.
        # top_row holds route_card plus the opacity toggle button.
        # ------------------------------------------------------------------

        self.opacity_button = QPushButton("●\n│\n○")
        self.opacity_button.setToolTip("Toggle transparency / solid")
        self.opacity_button.setFixedSize(28, 58)
        self.opacity_button.clicked.connect(self.toggle_opacity)
        self.opacity_button.setObjectName("opacityButton")

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
        route_layout.addWidget(self.make_route_separator())
        route_layout.addWidget(self.target_card, stretch=2)
        route_layout.addWidget(self.make_route_separator())
        route_layout.addWidget(self.final_card, stretch=2)
        route_layout.addWidget(self.make_route_separator())
        route_layout.addWidget(self.event_card, stretch=1)

        # Compact commander statistics card.
        # This sits between the route cards and the opacity toggle.
        # The labels intentionally use icons + numbers only.
        # Hover text explains what each stat means.
        stats_card = QFrame()
        stats_card.setObjectName("commanderStatsCard")
        
        stats_layout = QVBoxLayout(stats_card)
        stats_layout.setContentsMargins(1, 1, 1, 1)
        stats_layout.setSpacing(1)
        
        stats_top_row = QHBoxLayout()
        stats_top_row.setSpacing(1)
        
        stats_bottom_row = QHBoxLayout()
        stats_bottom_row.setSpacing(1)
        
        self.systems_visited_stat = self.make_stat_chip("★", "Systems visited")
        self.planets_scanned_stat = self.make_stat_chip("🌍", "Planets scanned to level 3")
        self.efficient_scans_stat = self.make_stat_chip("🗺", "Efficient DSS scans")
        self.bio_completed_stat = self.make_stat_chip("🧬", "Bio scans completed this session")



        # Baseline totals captured when the monitor starts.
        # The blue number shows how much each value increased during this app session.
        self.session_start_stats = {
                "systems_visited": None,
                "planets_scanned_level_3": None,
                "efficient_scans": None,
        }
        
        stats_top_row.addWidget(self.systems_visited_stat)
        stats_top_row.addWidget(self.planets_scanned_stat)
        
        stats_bottom_row.addWidget(self.efficient_scans_stat)
        stats_bottom_row.addWidget(self.bio_completed_stat)
        
        stats_layout.addLayout(stats_top_row)
        stats_layout.addLayout(stats_bottom_row)
        
        top_row = QHBoxLayout()
        top_row.setSpacing(ROW_SPACING)
        top_row.addWidget(route_card, stretch=1)
        top_row.addWidget(stats_card, stretch=0)
        top_row.addWidget(self.opacity_button, stretch=0)

        # ------------------------------------------------------------------
        # 4. Ship/status row widgets
        #
        # Visual order:
        #   Left card:  Ship | Mode | Location
        #   Right card: Bodies | Other scanned | High-value | Bio bodies
        #
        # middle_row holds both wide cards side-by-side.
        # ------------------------------------------------------------------

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

        summary_status_card = QFrame()
        summary_status_card.setObjectName("wideCard")

        summary_row = QHBoxLayout(summary_status_card)
        summary_row.setContentsMargins(12, 8, 12, 8)
        summary_row.setSpacing(10)

        self.bodies_card = self.make_info_card("◎", "Bodies", "? / ?")
        self.other_card = self.make_info_card("✦", "Other scanned", "0")
        self.high_value_card = self.make_info_card("◇", "High-value", "0")
        self.bio_card = self.make_info_card("☘", "Bio bodies", "0")

        summary_row.addWidget(self.bodies_card)
        summary_row.addWidget(self.other_card)
        summary_row.addWidget(self.high_value_card)
        summary_row.addWidget(self.bio_card)

        middle_row = QHBoxLayout()
        middle_row.setSpacing(ROW_SPACING)
        middle_row.addWidget(ship_status_card, stretch=1)
        middle_row.addWidget(summary_status_card, stretch=1)

        # ------------------------------------------------------------------
        # 5. Spreadsheet/table section
        #
        # This is the large central data area.
        #
        # Column index reference:
        #   0 ID
        #   1 Body
        #   2 Type
        #   3 Class
        #   4 Distance
        #   5 Bio
        #   6 Geo
        #   7 DSS
        #   8 Bio Progress
        #   9 Recommendation
        # ------------------------------------------------------------------

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)

        self.table.setHorizontalHeaderLabels(
            [
                "ID",
                "Body",
                "Type",
                "Class",
                "Distance",
                "DSS",
                "Bio Progress",
                "Notes & Signals",
            ]
        )

        table_card = QFrame()
        table_card.setObjectName("tableCard")

        table_card_layout = QVBoxLayout(table_card)
        table_card_layout.setContentsMargins(6, 6, 6, 6)
        table_card_layout.setSpacing(6)

        table_toolbar = QHBoxLayout()
        table_toolbar.setContentsMargins(2, 0, 2, 0)
        table_toolbar.setSpacing(6)

        table_title = QLabel("Body Table")
        table_title.setObjectName("tableTitle")
        table_toolbar.addWidget(table_title)
        table_toolbar.addStretch()

        self.table_filter_mode = "All"
        self.table_filter_buttons = []
        self.table_filter_group = QButtonGroup(self)
        self.table_filter_group.setExclusive(True)

        for filter_name in ("All", "Action", "Bio", "High-value", "Search"):
            button = self.make_table_filter_button(filter_name)
            self.table_filter_buttons.append(button)
            self.table_filter_group.addButton(button)
            table_toolbar.addWidget(button)

        table_card_layout.addLayout(table_toolbar)
        table_card_layout.addWidget(self.table, stretch=1)

        table_header = self.table.horizontalHeader()

        for col in range(8):
            table_header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)

        self.table.setColumnWidth(0, 34)    # ID
        self.table.setColumnWidth(1, 170)   # Body
        self.table.setColumnWidth(2, 80)    # Type
        self.table.setColumnWidth(3, 135)   # Class
        self.table.setColumnWidth(4, 85)    # Distance
        self.table.setColumnWidth(5, 85)    # DSS
        self.table.setColumnWidth(6, 360)   # Bio Progress
        self.table.setColumnWidth(7, 270)   # Notes & Signals

        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)
        table_header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)

        table_header.setStretchLastSection(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)

        # ------------------------------------------------------------------
        # 6. Bottom row widgets
        #
        # Visual order:
        #   Journal Log | Legend
        #
        # This row stays compact and fixed-height.
        # ------------------------------------------------------------------

        self.log_title_label = QLabel("Journal Log")
        self.log_title_label.setObjectName("sectionTitle")
        self.log_title_label.setFixedHeight(18)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(70)
        self.log_box.setMaximumHeight(80)

        log_card = QFrame()
        log_card.setObjectName("bottomCard")

        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(10, 6, 10, 10)
        log_layout.setSpacing(2)
        log_layout.addWidget(self.log_title_label)
        log_layout.addWidget(self.log_box)
        log_layout.addStretch(0)

        self.legend_title_label = QLabel("Legend")
        self.legend_title_label.setObjectName("sectionTitle")
        self.legend_title_label.setFixedHeight(18)

        self.legend_label = QLabel("""
        <table cellspacing="6" cellpadding="2">
        <tr>
        <td><b>Bio Progress</b></td>
        <td><span style="background-color:#3A3A3A; color:#3A3A3A;">■■</span> expected</td>
        <td><span style="background-color:#D69E2E; color:#D69E2E;">■■</span> in progress</td>
        <td><span style="background-color:#7C3AED; color:#7C3AED;">■■</span> complete</td>
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

        legend_card = QFrame()
        legend_card.setObjectName("bottomCard")

        legend_layout = QVBoxLayout(legend_card)
        legend_layout.setContentsMargins(10, 6, 10, 8)
        legend_layout.setSpacing(2)
        legend_layout.addWidget(self.legend_title_label)
        legend_layout.addWidget(self.legend_label)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(ROW_SPACING)
        bottom_row.addWidget(log_card, stretch=2)
        bottom_row.addWidget(legend_card, stretch=1)

        # ------------------------------------------------------------------
        # 7. Footer
        #
        # The footer is updated in refresh().
        # ------------------------------------------------------------------

        self.footer_left_label = QLabel()
        self.footer_left_label.setObjectName("footerLabel")

        self.footer_version_label = QLabel(VERSION)
        self.footer_version_label.setObjectName("footerLabel")

        self.full_mode_button = QPushButton("▁")
        self.full_mode_button.setObjectName("modeToggleButton")
        self.full_mode_button.setToolTip("Switch to thin view")
        self.full_mode_button.setFixedSize(28, 24)
        self.full_mode_button.clicked.connect(self.toggle_view_mode)

        # ------------------------------------------------------------------
        # 8. Apply fixed section heights
        #
        # These lines must appear after the widgets exist.
        # ------------------------------------------------------------------

        self.special_card.setFixedHeight(SPECIAL_HEIGHT)
        route_card.setFixedHeight(ROUTE_HEIGHT)
        ship_status_card.setFixedHeight(STATUS_HEIGHT)
        summary_status_card.setFixedHeight(STATUS_HEIGHT)

        self.table.setMinimumHeight(TABLE_MIN_HEIGHT)

        log_card.setFixedHeight(BOTTOM_HEIGHT)
        legend_card.setFixedHeight(BOTTOM_HEIGHT)

        self.footer_left_label.setFixedHeight(FOOTER_HEIGHT)

        # ------------------------------------------------------------------
        # 9. Main top-to-bottom layout
        #
        # Visual order:
        #   1. Special/search row
        #   2. Route row
        #   3. Ship/status row
        #   4. Table
        #   5. Journal/legend row
        #   6. Footer
        # ------------------------------------------------------------------

        header = QVBoxLayout()
        header.setSpacing(HEADER_SPACING)
        header.addWidget(self.special_card)
        header.addLayout(top_row)
        header.addLayout(middle_row)

        layout = QVBoxLayout()
        layout.setSpacing(HEADER_SPACING)

        layout.addLayout(header)
        layout.addWidget(table_card, stretch=1)
        layout.addLayout(bottom_row, stretch=0)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(0)
        footer_row.addWidget(self.footer_left_label)
        footer_row.addStretch()
        footer_row.addWidget(self.full_mode_button)
        footer_row.addWidget(self.footer_version_label)

        layout.addLayout(footer_row)

        self.full_content = QWidget()
        self.full_content.setObjectName("fullContent")
        self.full_content.setLayout(layout)

        self.thin_card = QFrame()
        self.thin_card.setObjectName("thinCard")
        self.thin_card.setFixedHeight(THIN_HEIGHT - 6)

        thin_layout = QHBoxLayout(self.thin_card)
        thin_layout.setContentsMargins(10, 3, 6, 3)
        thin_layout.setSpacing(8)

        self.thin_system_label = QLabel("Waiting for journal data")
        self.thin_system_label.setObjectName("thinSystem")
        self.thin_system_label.setMinimumWidth(180)
        self.thin_system_label.setToolTip(
            "Current system. Hover here for exploration totals."
        )

        self.thin_status_label = QLabel("")
        self.thin_status_label.setObjectName("thinStatus")
        self.thin_status_label.setTextFormat(Qt.TextFormat.RichText)
        self.thin_status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.thin_held_data_label = QLabel("★ 0  │  ☘ 0")
        self.thin_held_data_label.setObjectName("thinHeldData")
        self.thin_held_data_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.thin_held_data_label.setMinimumWidth(100)
        self.thin_held_data_label.setToolTip(
            "★ systems with unsold exploration data\n"
            "☘ completed biological samples not yet sold"
        )

        self.thin_mode_button = QPushButton("▣")
        self.thin_mode_button.setObjectName("modeToggleButton")
        self.thin_mode_button.setToolTip("Return to full view")
        self.thin_mode_button.setFixedSize(28, 28)
        self.thin_mode_button.clicked.connect(self.toggle_view_mode)

        thin_layout.addWidget(self.thin_system_label)
        thin_layout.addWidget(self.make_route_separator())
        thin_layout.addWidget(self.thin_status_label, stretch=1)
        thin_layout.addWidget(self.make_route_separator())
        thin_layout.addWidget(self.thin_held_data_label)
        thin_layout.addWidget(self.thin_mode_button)

        root_layout = QVBoxLayout()
        root_layout.setContentsMargins(6, 3, 6, 3)
        root_layout.setSpacing(0)
        root_layout.addWidget(self.full_content)
        root_layout.addWidget(self.thin_card)
        self.setLayout(root_layout)
        self.thin_card.hide()

        # ------------------------------------------------------------------
        # 10. Stylesheet and live updates
        #
        # Styling is loaded from styles/dashboard.qss so users can customize
        # colors without editing Python code.
        # ------------------------------------------------------------------

        self.setStyleSheet(load_stylesheet())

        self.set_table_filter("All")
        self.monitor.updated.connect(self.refresh)
        self.refresh()

        saved_mode = self.settings.value("thin_mode", False, type=bool)
        if saved_mode:
            self.set_view_mode(True)

    def toggle_view_mode(self) -> None:
        self.set_view_mode(not self.thin_mode)

    def set_view_mode(self, thin: bool) -> None:
        if thin == self.thin_mode:
            return

        current_geometry = self.geometry()
        old_bottom = current_geometry.bottom()

        if thin:
            # Save full-window state before changing flags or size.
            self.full_size = self.size()
            self.full_geometry = current_geometry

            self.full_content.hide()
            self.thin_card.show()

            # Remove the desktop title bar in thin mode.
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            self.show()

            self.setMinimumSize(THIN_MIN_WIDTH, THIN_HEIGHT)
            self.setMaximumHeight(THIN_HEIGHT)

            new_width = max(current_geometry.width(), THIN_MIN_WIDTH)
            new_geometry = QRect(
                current_geometry.x(),
                current_geometry.y(),
                new_width,
                THIN_HEIGHT,
            )

            # Keep the old bottom edge fixed, making the window collapse downward.
            new_geometry.moveBottom(old_bottom)
            self.setGeometry(new_geometry)

        else:
            # Restore the normal desktop title bar.
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)
            self.show()

            self.thin_card.hide()
            self.full_content.show()

            self.setMaximumHeight(16777215)
            self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

            if hasattr(self, "full_geometry"):
                self.setGeometry(self.full_geometry)
            else:
                self.resize(self.full_size)

        self.thin_mode = thin
        self.settings.setValue("thin_mode", thin)
        self.refresh_thin_view()

    def short_body_name(self, body: BodyInfo) -> str:
        system = self.monitor.state.system or ""
        name = body.name
        if system and name.startswith(system):
            name = name[len(system):].strip()
        return name or str(body.body_id or "?")

    def target_complete(self, body: BodyInfo) -> bool:
        needs_dss = self.is_high_value_world(body)
        needs_bio = bool(body.bio_signals and body.bio_signals > 0)
        dss_done = (not needs_dss) or body.mapped is True
        bio_done = (not needs_bio) or self.bio_complete(body)
        return dss_done and bio_done

    def bio_progress_icons(self, body: BodyInfo) -> str:
        expected = (
            body.bio_expected_genuses[:]
            if body.bio_expected_genuses
            else body.bio_species[:]
        )
        count = len(expected) if expected else int(body.bio_signals or 0)
        if count <= 0:
            return ""

        if not expected:
            expected = [f"Bio {index + 1}" for index in range(count)]

        started = {bio_key(name) for name in body.bio_species if name}
        completed = {
            bio_key(name)
            for name in body.bio_completed_species
            if name
        }
        icons: list[str] = []

        for index, name in enumerate(expected):
            key = bio_key(name)
            if (key and key in completed) or (
                not key and index < len(body.bio_completed_species)
            ):
                color = "#7C3AED"
            elif (key and key in started) or (
                not key and index < len(body.bio_species)
            ):
                color = "#D69E2E"
            else:
                color = "#707780"

            icons.append(bio_icon_html(name, color, size=15))

        return "&nbsp;".join(icons)

    def thin_target_html(self, body: BodyInfo) -> str:
        name = self.short_body_name(body)
        parts = [f"<b>{name}</b>"]
        if self.is_high_value_world(body) and body.mapped is not True:
            parts.append("<span style='color:#EF5350;'>◆</span>")
        bio = self.bio_progress_icons(body)
        if bio:
            parts.append(bio)
        return " ".join(parts)

    def refresh_thin_view(self) -> None:
        if not hasattr(self, "thin_status_label"):
            return

        state = self.monitor.state
        system = state.system or "Unknown system"
        self.thin_system_label.setText(system)
        self.thin_held_data_label.setText(
            f"★ {len(state.held_exploration_systems)}"
            f"  │  ☘ {len(state.held_bio_samples)}"
        )

        # Keep lifetime/session statistics available without occupying bar space.
        tooltip_lines = [f"Current system: {system}"]
        if state.systems_visited is not None:
            tooltip_lines.append(f"Systems visited: {state.systems_visited:,}")
        if state.planets_scanned_level_3 is not None:
            tooltip_lines.append(
                f"Planets scanned to level 3: {state.planets_scanned_level_3:,}"
            )
        if state.efficient_scans is not None:
            tooltip_lines.append(f"Efficient DSS scans: {state.efficient_scans:,}")
        tooltip_lines.append(
            f"Biological scans completed this session: "
            f"{state.session_bio_completed:,}"
        )
        self.thin_system_label.setToolTip("\n".join(tooltip_lines))

        if self.thin_target_system != system:
            self.thin_target_system = system
            self.thin_known_targets.clear()

        bodies = list(state.bodies.values())
        scanned = [
            body
            for body in bodies
            if body.scanned and body.kind in ("Planet", "Star")
        ]
        total = state.body_count

        scan_complete = bool(
            total is not None
            and total > 0
            and len(scanned) >= total
        )

        if not scan_complete:
            if total is None:
                self.thin_status_label.setText(
                    "<b style='color:#9FB0BF;'>HONK</b>"
                    "&nbsp;&nbsp;│&nbsp;&nbsp;"
                    "<span style='color:#9FB0BF;'>Discover system bodies</span>"
                )
                return

            scanned_count = min(len(scanned), total)
            dots: list[str] = []

            for index in range(total):
                # Neutral silver means identified; dark gray means still unknown.
                color = "#8B929A" if index < scanned_count else "#3A4149"
                dots.append(f"<span style='color:{color};'>●</span>")

            dot_text = "&nbsp;".join(dots)
            self.thin_status_label.setText(
                f"<b style='color:#60A5FA;'>FSS {scanned_count}/{total}</b>"
                f"&nbsp;&nbsp;│&nbsp;&nbsp;{dot_text}"
            )
            return

        current_targets = [
            body
            for body in bodies
            if body.kind == "Planet"
            and (
                self.is_high_value_world(body)
                or bool(body.bio_signals and body.bio_signals > 0)
            )
        ]
        self.thin_known_targets.update(body.name for body in current_targets)

        target_by_name = {body.name: body for body in current_targets}
        completed = 0
        remaining: list[BodyInfo] = []

        for name in sorted(self.thin_known_targets):
            body = target_by_name.get(name)
            if body is None:
                continue

            if self.target_complete(body):
                completed += 1
            else:
                remaining.append(body)

        total_targets = len(self.thin_known_targets)

        if total_targets == 0:
            self.thin_status_label.setText(
                "<b style='color:#22C55E;'>COMPLETE</b>"
                "&nbsp;&nbsp;│&nbsp;&nbsp;"
                "<span style='color:#9FB0BF;'>No scan targets</span>"
            )
            return

        if completed >= total_targets:
            self.thin_status_label.setText(
                f"<b style='color:#22C55E;'>COMPLETE</b>"
                f"&nbsp;&nbsp;│&nbsp;&nbsp;"
                f"<span style='color:#9FB0BF;'>Targets {completed}/{total_targets}</span>"
            )
            return

        remaining.sort(
            key=lambda body: (
                body.distance_ls is None,
                body.distance_ls or 0,
                body.body_id or 999999,
            )
        )

        entries = [self.thin_target_html(body) for body in remaining]
        details = "&nbsp;&nbsp;│&nbsp;&nbsp;".join(entries)

        self.thin_status_label.setText(
            f"<b style='color:#D69E2E;'>TARGETS {completed}/{total_targets}</b>"
            + (
                "&nbsp;&nbsp;│&nbsp;&nbsp;" + details
                if details
                else ""
            )
        )

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
    
        if not expected and body.bio_signals:
            expected = [f"Bio {i + 1}" for i in range(body.bio_signals)]
    
        started_keys = {bio_key(name) for name in body.bio_species if name}
        completed_keys = {bio_key(name) for name in body.bio_completed_species if name}
    
        for index, name in enumerate(expected):
            key = bio_key(name)
    
            done = key in completed_keys
            started = key in started_keys
    
            if name.startswith("Bio "):
                done = index < len(body.bio_completed_species)
                started = index < len(body.bio_species)
    
            if done:
                icon = bio_icon_html(name, "#FFFFFF", size=14)
                label_text = f"{icon}&nbsp;✓ {name}"
                color = "#7C3AED"
                text_color = "#FFFFFF"
            elif started:
                icon = bio_icon_html(name, "#1A1200", size=14)
                label_text = f"{icon}&nbsp;• {name}"
                color = "#D69E2E"
                text_color = "#000000"
            else:
                icon = bio_icon_html(name, "#B7BEC7", size=14)
                label_text = f"{icon}&nbsp;{name}"
                color = "#3A3A3A"
                text_color = "#DDDDDD"
    
            label = QLabel(label_text)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setFixedHeight(24)
            label.setMinimumWidth(72)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    
            label.setStyleSheet(f"""
                QLabel {{
                    background-color: {color};
                    color: {text_color};
                    border-radius: 5px;
                    padding: 1px 8px;
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

    def update_search_rules_from_bodies(self, bodies: list[BodyInfo]) -> None:
        search_type = self.search_type_combo.currentText()
        search_item = self.search_item_combo.currentText()
        search_type = self.clean_search_type()
        search_item = self.clean_search_item()

        if search_type == "None" or search_item == "None":
            self.update_search_rules_label()
            return

        best_conditions = []
        confirmed = False
        best_match_text = ""

        for body in bodies:
            result = evaluate_search_target(search_type, search_item, body)

            if result.get("conditions"):
                if not best_conditions:
                    best_conditions = result["conditions"]
                else:
                    merged = []
                    for index, (name, found) in enumerate(best_conditions):
                        new_found = found
                        if index < len(result["conditions"]):
                            _, other_found = result["conditions"][index]
                            new_found = found or other_found
                        merged.append((name, new_found))
                    best_conditions = merged

            if result.get("match_text"):
                best_match_text = result["match_text"]

            if result.get("title_confirmed"):
                confirmed = True
                break

        if not best_conditions:
            self.update_search_rules_label()
            return

        self.search_rules_card.setProperty("confirmed", "true" if confirmed else "false")
        self.search_rules_card.style().unpolish(self.search_rules_card)
        self.search_rules_card.style().polish(self.search_rules_card)
        self.search_rules_card.update()

        title_color = "#22C55E" if confirmed else "#60A5FA"
        status_word = "FOUND" if confirmed else "SEARCHING"

        found_color = "#22C55E" if confirmed else "#60A5FA"
        condition_text = " &nbsp;&nbsp;&nbsp;&nbsp; ".join(
            f"<span style='color:{found_color if found else '#EF4444'};'>●</span> {name}"
            for name, found in best_conditions
        )

        if best_match_text:
            result_line = f"<b>Result:</b> {best_match_text}"
        else:
            rule = get_rule_description(search_type, search_item)
            result_line = f"<span style='color:#9FB0BF;'>Watching:</span> {rule.get('match', '')}"

        self.search_rules_label.setText(
            f"<b style='color:{title_color};'>{status_word}: {search_item}</b><br>"
            f"{condition_text}<br>"
            f"{result_line}"
        )

    def stat_delta_from_start(self, key: str, current_total: int | None) -> int | None:
        if current_total is None:
            return None
    
        start_total = self.session_start_stats.get(key)
    
        if start_total is None:
            self.session_start_stats[key] = current_total
            return 0
    
        return max(current_total - start_total, 0)
    
    
    def stat_chip_text(self, icon: str, key: str, current_total: int | None) -> str:
        titles = {
            "systems_visited": "Systems visited",
            "planets_scanned_level_3": "Planets L3",
            "efficient_scans": "Efficient DSS",
        }
        title = titles.get(key, key)

        if current_total is None:
            return f"<span style='color:#9FB0BF;'>{icon} {title}</span><br><b>—</b>"
    
        delta = self.stat_delta_from_start(key, current_total)
    
        return (
            f"<span style='color:#9FB0BF;'>{icon} {title}</span><br>"
            f"<b>{current_total:,}</b> "
            f"<span style='color:#6CB6FF;'>+{delta:,}</span>"
        )

    def refresh(self) -> None:
        state = self.monitor.state
        self.refresh_thin_view()

        if state.special_alerts:
            self.special_icon_label.setText("✦")
            self.special_label.setText(f"Special: {state.special_alerts[-1]}")
            self.set_alert_style(True)
        else:
            self.special_icon_label.setText("✦")
            self.special_label.setText("No special signals")
            self.set_alert_style(False)

        system = state.system or "Unknown system"
        target = state.nav_target or "none"
        final = state.nav_final or "none"

        self.update_info_card(self.system_card, "🌌", "System", system)
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

        all_bodies = sorted(
                state.bodies.values(),
                key=body_sort_key,
        )

        self.update_search_rules_from_bodies(all_bodies)
        search_type = self.clean_search_type()
        search_item = self.clean_search_item()

        bodies = [body for body in all_bodies if self.body_passes_filter(body)]

        # Resize Bio Progress based on the widest visible bio pill row.
        self.table.setColumnWidth(6, self.calculate_bio_progress_width(bodies))

        self.table.setRowCount(len(bodies))

        for row, body in enumerate(bodies):
            high_value = self.is_high_value_world(body)
            can_be_dss_mapped = body.kind == "Planet"
            mapped_text = "" if not can_be_dss_mapped or body.mapped is None else ("Yes" if body.mapped else "No")
            priority = self.priority_text(body)

            search_type = self.search_type_combo.currentText().replace("⚒ ", "").replace("⚙ ", "")
            search_item = self.search_item_combo.currentText()
            search_result = evaluate_search_target(search_type, search_item, body)
            special_comment = search_result.get("match_text", "")

            notes = self.notes_for_body(body)

            values = [
                "" if body.body_id is None else str(body.body_id),
                body.name,
                body.kind,
                body.subtype,
                "" if body.distance_ls is None else f"{body.distance_ls:.1f}",
                mapped_text,
                "",
                notes,
            ]

            for col, value in enumerate(values):
                item = QTableWidgetItem(value)

                # Center text
                if col == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

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
                    if col == 7:
                        if self.bio_complete(body):
                            item.setBackground(QBrush(QColor("#7C3AED")))  # completed bio
                            item.setForeground(QBrush(QColor("#000000")))
                        else:
                            item.setBackground(QBrush(QColor("#5C4618")))  # bio still needs work
                            item.setForeground(QBrush(QColor("#FFFFFF")))

                elif body.scanned is False:
                    item.setBackground(QBrush(QColor("#26323D")))
                    item.setForeground(QBrush(QColor("#DDDDDD")))

                # Make the Mapped cell extra obvious.
                # Make the DSS cell look like a small status pill.
                if col == 5 and can_be_dss_mapped:
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
                self.table.setCellWidget(row, 6, self.make_bio_status_widget(body))
                self.table.setRowHeight(row, 32)
            else:
                self.table.removeCellWidget(row, 6)

        self.systems_visited_stat.setText(
            self.stat_chip_text("🌌", "systems_visited", state.systems_visited)
        )
        
        self.planets_scanned_stat.setText(
            self.stat_chip_text("🌍", "planets_scanned_level_3", state.planets_scanned_level_3)
        )
        
        self.efficient_scans_stat.setText(
            self.stat_chip_text("🗺", "efficient_scans", state.efficient_scans)
        )
        
        self.bio_completed_stat.setText(
            f"<span style='color:#9FB0BF;'>🧬 Bio completed</span><br>"
            f"<b>{state.session_bio_completed:,}</b> "
            f"<span style='color:#6CB6FF;'>+{state.session_bio_completed:,}</span>"
        )

        commander = state.commander or "Unknown"
        footer_ship = state.ship_name or friendly_ship_name(state.ship)

        self.footer_left_label.setText(
            f"Commander: {commander}        Ship: {footer_ship}        Elite Dangerous Journal Helper"
        )

        self.footer_version_label.setText(VERSION)

        # Keep rows compact even when Bio progress contains widgets
        for row in range(self.table.rowCount()):
            self.table.setRowHeight(row, 32)
        # auto scroll
        self.log_box.setPlainText("\n".join(state.messages))
        self.log_box.moveCursor(QTextCursor.MoveOperation.End)

    def closeEvent(self, event) -> None:
        self.monitor.stop()
        event.accept()
