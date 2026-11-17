"""Bridge live-load dialog: lanes, trucks, envelopes and influence lines."""

from __future__ import annotations

import csv
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath,
                           QPen, QPolygonF)
from PySide6.QtWidgets import (QAbstractItemView, QApplication,
                               QComboBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QProgressBar, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QTextEdit, QVBoxLayout, QWidget)

from . import theme
from .dialogs import BaseDialog, hint, int_spin, spin, title_label
from .live_load import (BCL_SUBDIVISIONS, DEFAULT_LANE_UDL, MAX_AXLES,
                        Axle, LiveLoadConfig, LiveLoadResults,
                        Span, analyze, auto_dla_info, beam_chain_from_project,
                        chain_geometry, preset_axles)
from .model import Project
from .version import APP_VERSION


def _fmt(value: float, digits: int = 4) -> str:
    if value is None:
        return "-"
    magnitude = abs(value)
    if magnitude and (magnitude < 1e-4 or magnitude >= 1e6):
        return f"{value:.{digits}e}"
    return f"{value:.{digits}g}"


class EnvelopePlot(QWidget):
    """Max/min envelope diagram with a zero line and filled demand band."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.xs: List[float] = []
        self.maximum: List[float] = []
        self.minimum: List[float] = []
        self.xlabel = ""
        self.ylabel = ""
        self.title = ""
        self.setMinimumHeight(300)

    def set_data(self, xs: Sequence[float], maximum: Sequence[float],
                 minimum: Sequence[float], xlabel: str, ylabel: str,
                 title: str) -> None:
        self.xs = list(xs)
        self.maximum = list(maximum)
        self.minimum = list(minimum)
        self.xlabel, self.ylabel, self.title = xlabel, ylabel, title
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QBrush(QColor("#ffffff")))
        p.setPen(QPen(QColor(theme.BORDER), 1.0))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        left, right, top, bottom = 76, 22, 38, 56
        plot = QRectF(left, top, max(10, self.width() - left - right),
                      max(10, self.height() - top - bottom))
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.setPen(QPen(QColor(theme.ACCENT_DARK)))
        p.drawText(QRectF(10, 6, self.width() - 20, 24), Qt.AlignLeft,
                   self.title)
        if not self.xs:
            p.setPen(QPen(QColor(theme.MUTED)))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(plot, Qt.AlignCenter, "No results yet")
            p.end()
            return
        xmin, xmax = min(self.xs), max(self.xs)
        ymin = min(self.minimum)
        ymax = max(self.maximum)
        if xmax - xmin < 1e-12:
            xmax = xmin + 1.0
        if ymax - ymin < 1e-12:
            ymax = ymin + 1.0
        xpad = (xmax - xmin) * 0.03
        ypad = (ymax - ymin) * 0.10
        xmin -= xpad
        xmax += xpad
        ymin -= ypad
        ymax += ypad
        if ymin > 0:
            ymin = 0.0
        if ymax < 0:
            ymax = 0.0

        def px(x: float) -> float:
            return plot.left() + (x - xmin) / (xmax - xmin) * plot.width()

        def py(y: float) -> float:
            return plot.bottom() - (y - ymin) / (ymax - ymin) * plot.height()

        p.setFont(QFont("Segoe UI", 8))
        for i in range(6):
            tx = xmin + (xmax - xmin) * i / 5.0
            ty = ymin + (ymax - ymin) * i / 5.0
            x, y = px(tx), py(ty)
            p.setPen(QPen(QColor("#e8eef4"), 1.0))
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QPen(QColor(theme.MUTED)))
            p.drawText(QRectF(x - 42, plot.bottom() + 5, 84, 16),
                       Qt.AlignCenter, _fmt(tx))
            p.drawText(QRectF(2, y - 8, left - 8, 16),
                       Qt.AlignRight | Qt.AlignVCenter, _fmt(ty))
        p.setPen(QPen(QColor("#1f3a5f"), 1.2))
        p.drawLine(QPointF(plot.left(), plot.top()),
                   QPointF(plot.left(), plot.bottom()))
        p.drawLine(QPointF(plot.left(), plot.bottom()),
                   QPointF(plot.right(), plot.bottom()))
        zero = py(0.0)
        p.setPen(QPen(QColor("#c4d2df"), 1.0, Qt.DashLine))
        p.drawLine(QPointF(plot.left(), zero), QPointF(plot.right(), zero))

        max_path = QPainterPath()
        min_path = QPainterPath()
        for i, (x, hi, lo) in enumerate(zip(self.xs, self.maximum,
                                           self.minimum)):
            if i == 0:
                max_path.moveTo(px(x), py(hi))
                min_path.moveTo(px(x), py(lo))
            else:
                max_path.lineTo(px(x), py(hi))
                min_path.lineTo(px(x), py(lo))
        fill = QPainterPath(max_path)
        for x, lo in reversed(list(zip(self.xs, self.minimum))):
            fill.lineTo(px(x), py(lo))
        fill.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(15, 111, 184, 28)))
        p.drawPath(fill)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(theme.ACCENT), 2.0))
        p.drawPath(max_path)
        p.setPen(QPen(QColor("#c92a2a"), 1.8, Qt.DashLine))
        p.drawPath(min_path)

        imax = max(range(len(self.maximum)), key=lambda i: self.maximum[i])
        imin = min(range(len(self.minimum)), key=lambda i: self.minimum[i])
        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        for index, color, label, values in (
                (imax, theme.ORANGE, "max", self.maximum),
                (imin, "#c92a2a", "min", self.minimum)):
            x, y = px(self.xs[index]), py(values[index])
            p.setPen(QPen(QColor(color), 1.4))
            p.setBrush(QBrush(QColor("#ffffff")))
            p.drawEllipse(QPointF(x, y), 3.5, 3.5)
            p.drawText(QPointF(x + 5, y - 5), label)

        p.setPen(QPen(QColor(theme.ACCENT_DARK)))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(QRectF(plot.left(), plot.bottom() + 22, plot.width(), 18),
                   Qt.AlignCenter, self.xlabel)
        p.save()
        p.translate(13, plot.center().y())
        p.rotate(-90)
        p.drawText(QRectF(-plot.height() / 2, -8, plot.height(), 16),
                   Qt.AlignCenter, self.ylabel)
        p.restore()
        p.end()


class VehicleDiagram(QWidget):
    """Side elevation with axle loads and spacing dimensions."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: List[Tuple[float, float]] = []
        self.setMinimumHeight(150)

    def set_axles(self, rows: Sequence[Axle]) -> None:
        self.rows = [(float(a.load), float(a.spacing)) for a in rows]
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        if not self.rows:
            p.setPen(QPen(QColor(theme.MUTED)))
            p.drawText(self.rect(), Qt.AlignCenter, "No vehicle defined")
            p.end()
            return
        loads = [r[0] for r in self.rows]
        gaps = [r[1] for r in self.rows[:-1]]
        total = sum(gaps)
        left, right = 58.0, max(self.width() - 58.0, 80.0)
        span = max(total, 1.0)
        scale = (right - left) / span
        baseline = self.height() * 0.60
        p.setPen(QPen(QColor(theme.BORDER), 1.0))
        p.drawLine(QPointF(20, baseline + 44), QPointF(self.width() - 20, baseline + 44))
        p.setPen(QPen(QColor("#41566e"), 3.0))
        p.drawLine(QPointF(left - 14, baseline), QPointF(right + 14, baseline))
        cumulative = 0.0
        xs = []
        for i, (load, _spacing) in enumerate(self.rows):
            x = left + cumulative * scale
            xs.append(x)
            p.setPen(QPen(QColor("#41566e"), 2.0))
            p.setBrush(QBrush(QColor("#41566e")))
            p.drawEllipse(QPointF(x, baseline + 7), 7.0, 7.0)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(theme.ORANGE), 1.8))
            p.drawLine(QPointF(x, baseline - 4), QPointF(x, baseline - 40))
            p.setBrush(QBrush(QColor(theme.ORANGE)))
            p.drawPolygon(QPolygonF([
                QPointF(x, baseline - 4),
                QPointF(x - 4, baseline - 12),
                QPointF(x + 4, baseline - 12)]))
            p.setBrush(Qt.NoBrush)
            p.setFont(QFont("Segoe UI", 8, QFont.Bold))
            p.setPen(QPen(QColor(theme.ORANGE)))
            label_y = baseline - (58.0 if i % 2 == 0 else 78.0)
            p.drawText(QRectF(x - 30, label_y, 60, 16),
                       Qt.AlignCenter, f"{load:g} kN")
            p.setFont(QFont("Segoe UI", 7))
            p.setPen(QPen(QColor("#41566e")))
            if i < len(gaps):
                cumulative += gaps[i]
        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QPen(QColor(theme.MUTED)))
        p.drawText(QRectF(left - 40, baseline + 20, 40, 14),
                   Qt.AlignRight, "front")
        p.drawText(QRectF(right + 4, baseline + 20, 50, 14),
                   Qt.AlignLeft, "rear")
        for i, gap in enumerate(gaps):
            x0, x1 = xs[i], xs[i + 1]
            y = baseline + 32
            p.setPen(QPen(QColor("#8ea6bd"), 1.0))
            p.drawLine(QPointF(x0, y), QPointF(x1, y))
            p.drawLine(QPointF(x0, y - 3), QPointF(x0, y + 3))
            p.drawLine(QPointF(x1, y - 3), QPointF(x1, y + 3))
            p.setPen(QPen(QColor("#41566e")))
            label_y = y - 16 if i % 2 == 0 else y + 4
            p.drawText(QRectF((x0 + x1) / 2 - 35, label_y, 70, 14),
                       Qt.AlignCenter, f"{gap:g} m")
        p.end()


class LiveLoadDialog(BaseDialog):
    def __init__(self, project: Project, selected_elements: Optional[Sequence[int]] = None,
                 parent=None) -> None:
        super().__init__("Bridge Live Load", parent, 1180)
        self.project = project
        self.selected_elements = list(selected_elements or [])
        self.results: Optional[LiveLoadResults] = None
        self.custom_axles: List[Axle] = preset_axles("CL-625")
        self._last_truck = "CL-625"
        self._chain_note = ""
        self.chain_spans: List[Span] = []
        self.chain_E = 200e9
        self.chain_I = 0.005
        self.chain_start_m = 0.0
        self.support_x: List[float] = []
        self.chain_tags: List[int] = []
        self.chain_geometry = None
        self._detect_chain()
        self.resize(1240, 900)
        self.body.addWidget(hint(
            "Define the moving vehicle and traffic lane. Support locations, "
            "spans and mean E/I are read from the model. The computed LL Max, "
            "LL Min and LL All envelopes are displayed in the main model view."))

        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)
        self._build_structure_tab()
        self._build_vehicle_tab()
        self._build_bottom_bar()
        self._sync_controls()
        self._load_defaults()

    # ------------------------------------------------------------------ tabs
    def _build_structure_tab(self) -> None:
        page = QWidget()
        lay = QHBoxLayout(page)
        left = QVBoxLayout()
        left.addWidget(title_label("Bridge from model"))
        self.support_label = QLabel()
        self.support_label.setWordWrap(True)
        self.span_label = QLabel()
        self.span_label.setWordWrap(True)
        self.chain_label = QLabel()
        self.chain_label.setWordWrap(True)
        self.chain_label.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        left.addWidget(self.support_label)
        left.addWidget(self.span_label)
        left.addWidget(self.chain_label)
        refresh = QPushButton("Refresh from model")
        refresh.clicked.connect(self._refresh_model)
        left.addWidget(refresh)
        left.addStretch(1)
        lay.addLayout(left, 1)

        right = QVBoxLayout()
        form = QFormLayout()
        self.E_label = QLabel()
        self.I_label = QLabel()
        self.elems = int_spin(20, 2, 40)
        self.increment = spin(0.25, 0.01, 10.0, 3, 0.05, "m")
        form.addRow("Young's modulus E", self.E_label)
        form.addRow("Moment of inertia I", self.I_label)
        form.addRow("Elements per span", self.elems)
        form.addRow("Truck sweep increment", self.increment)
        right.addLayout(form)
        right.addWidget(hint(
            "Support locations and span lengths are read from the model's "
            "continuous beam chain. Select a girder chain before opening this "
            "dialog to force a particular line; otherwise the longest chain "
            "parallel to the traffic lane is used. E and I are the mean values "
            "of the chain members. Elements per span controls only the "
            "influence-engine mesh."))
        right.addWidget(QLabel("Analysis method"))
        method = QLabel(
            "Influence-line moving load: the stiffness matrix is "
            "factorized once, unit point loads at four stations per element give "
            "cubic influence functions, truck extrema are refined around the "
            "best sweep positions, and lane UDL uses each response's favourable "
            "positive/negative zones. This is not a time-history vehicle run.")
        method.setWordWrap(True)
        method.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        right.addWidget(method)
        right.addStretch(1)
        lay.addLayout(right, 1)
        self.tabs.addTab(page, "Model")
        self._update_model_info()

    def _build_vehicle_tab(self) -> None:
        page = QWidget()
        lay = QHBoxLayout(page)
        left = QVBoxLayout()
        form = QFormLayout()
        self.truck_model = QComboBox()
        for label, key in (("CL-625", "CL-625"), ("BCL-625", "BCL-625"),
                           ("Custom vehicle / train", "Custom")):
            self.truck_model.addItem(label, key)
        self.bcl_subdivision = QComboBox()
        for value in BCL_SUBDIVISIONS:
            self.bcl_subdivision.addItem(f"{value:g} m", value)
        self.bcl_subdivision.setCurrentIndex(1)
        self.lane_name = QLineEdit("Lane 1")
        self.lane_udl = spin(DEFAULT_LANE_UDL, 0.0, 1000.0, 3, 1.0, "kN/m")
        self.dla_mode = QComboBox()
        self.dla_mode.addItem("Auto (selected-axle groups)", "auto")
        self.dla_mode.addItem("Manual override", "manual")
        self.dla_override = spin(25.0, 0.0, 100.0, 1, 5.0, "%")
        self.dla_multiplier = spin(100.0, 0.0, 100.0, 1, 10.0, "%")
        form.addRow("Truck / vehicle", self.truck_model)
        form.addRow("BCL axle 3-4 subdivision", self.bcl_subdivision)
        self.bcl_label = form.labelForField(self.bcl_subdivision)
        form.addRow("Lane name", self.lane_name)
        form.addRow("Lane load UDL", self.lane_udl)
        form.addRow("DLA mode", self.dla_mode)
        form.addRow("Manual DLA", self.dla_override)
        form.addRow("DLA multiplier d", self.dla_multiplier)
        left.addLayout(form)

        left.addWidget(title_label("Lane travel"))
        lane_form = QFormLayout()
        self.lane_combo = QComboBox()
        self.lane_start = spin(0.0, -1e7, 1e7, 3, 0.5, "m")
        self.lane_end = spin(0.0, -1e7, 1e7, 3, 0.5, "m")
        self.lane_offset = spin(0.0, -1e6, 1e6, 3, 0.25, "m")
        lane_form.addRow("Saved lane", self.lane_combo)
        lane_form.addRow("Start x", self.lane_start)
        lane_form.addRow("End x", self.lane_end)
        lane_form.addRow("Lateral shift", self.lane_offset)
        left.addLayout(lane_form)
        self.define_lanes_btn = QPushButton("Define / edit lanes...")
        self.define_lanes_btn.clicked.connect(self._define_lanes)
        left.addWidget(self.define_lanes_btn)
        left.addWidget(hint(
            "The truck sweep is bounded by the lane start/end, extended by the "
            "truck length so the whole vehicle can enter and leave. The lateral "
            "shift places the lane (and its wheel lines) across the bridge; the "
            "1D envelope uses the lane's longitudinal X extent."))
        self.dla_hint = QLabel()
        self.dla_hint.setWordWrap(True)
        self.dla_hint.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        left.addWidget(self.dla_hint)
        left.addWidget(hint(
            "CL-625 and BCL-625 use the standard five-axle tables. BCL-625 "
            "envelopes axle 3-4 spacings from 6.6 m to 18 m. Custom supports "
            "1-20 axles. The last axle's spacing is ignored. Lane load is "
            "80% of the selected truck plus the favourable lane UDL zones, "
            "with no DLA on either part."))
        left.addStretch(1)
        lay.addLayout(left, 0)

        right = QVBoxLayout()
        right.addWidget(QLabel("Vehicle elevation"))
        self.vehicle_diagram = VehicleDiagram()
        right.addWidget(self.vehicle_diagram)
        self.vehicle_caption = QLabel()
        self.vehicle_caption.setWordWrap(True)
        self.vehicle_caption.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        right.addWidget(self.vehicle_caption)
        right.addWidget(QLabel("Axles (front to rear)"))
        self.axle_table = QTableWidget(5, 3)
        self.axle_table.setHorizontalHeaderLabels(
            ["Axle", "Load (kN)", "Spacing to next (m)"])
        self.axle_table.verticalHeader().setVisible(False)
        self.axle_table.horizontalHeader().setStretchLastSection(True)
        self.axle_table.setColumnWidth(0, 60)
        self.axle_table.setColumnWidth(1, 130)
        right.addWidget(self.axle_table, 1)
        row = QHBoxLayout()
        self.add_axle_btn = QPushButton("Add axle")
        self.add_axle_btn.clicked.connect(self._add_axle)
        self.remove_axle_btn = QPushButton("Remove axle")
        self.remove_axle_btn.clicked.connect(self._remove_axle)
        row.addWidget(self.add_axle_btn)
        row.addWidget(self.remove_axle_btn)
        row.addStretch(1)
        right.addLayout(row)
        right.addWidget(hint(
            "Presets are read-only; select Custom to edit axle loads and "
            "spacings. Preset values are restored when analyzed."))
        lay.addLayout(right, 1)
        self.tabs.addTab(page, "Vehicle & Lane")
        self.truck_model.currentIndexChanged.connect(self._truck_changed)
        self.bcl_subdivision.currentIndexChanged.connect(self._vehicle_changed)
        self.dla_mode.currentIndexChanged.connect(self._sync_controls)
        self.lane_combo.currentIndexChanged.connect(self._lane_changed)
        self.axle_table.itemChanged.connect(self._vehicle_changed)

    def _build_results_tab(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        row = QHBoxLayout()
        self.result_case = QComboBox()
        self.result_case.addItems(["Truck", "Lane", "Envelope"])
        self.result_response = QComboBox()
        self.result_response.addItems(["Shear", "Moment", "Deflection"])
        row.addWidget(QLabel("Display case"))
        row.addWidget(self.result_case)
        row.addWidget(QLabel("Response"))
        row.addWidget(self.result_response)
        row.addStretch(1)
        lay.addLayout(row)
        self.plot = EnvelopePlot()
        lay.addWidget(self.plot, 1)

        lower = QHBoxLayout()
        self.summary_table = QTableWidget(3, 5)
        self.summary_table.setHorizontalHeaderLabels(
            ["Response", "Max", "at x (m)", "Min", "at x (m)"])
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.summary_table.horizontalHeader().setStretchLastSection(True)
        self.summary_table.setMaximumHeight(130)
        lower.addWidget(self.summary_table, 1)
        self.reaction_table = QTableWidget(0, 5)
        self.reaction_table.setHorizontalHeaderLabels(
            ["Support", "R max (kN)", "R min (kN)", "Gov. x (m)",
             "BCL gap (m)"])
        self.reaction_table.verticalHeader().setVisible(False)
        self.reaction_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.reaction_table.horizontalHeader().setStretchLastSection(True)
        self.reaction_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self.reaction_table.setMaximumHeight(170)
        lower.addWidget(self.reaction_table, 1)
        lay.addLayout(lower)
        self.tabs.addTab(page, "Envelopes")
        self.result_case.currentIndexChanged.connect(self._show_results)
        self.result_response.currentIndexChanged.connect(self._show_results)

        influence_page = QWidget()
        ilay = QVBoxLayout(influence_page)
        irow = QHBoxLayout()
        self.influence_combo = QComboBox()
        self.influence_combo.addItem("Moment at nearest midspan node",
                                     "moment_mid")
        self.influence_combo.addItem("Shear at left support", "shear_left")
        self.influence_combo.addItem("Reaction at support 1", "reaction_0")
        irow.addWidget(QLabel("Influence line"))
        irow.addWidget(self.influence_combo)
        irow.addStretch(1)
        ilay.addLayout(irow)
        self.influence_plot = EnvelopePlot()
        ilay.addWidget(self.influence_plot, 1)
        ilay.addWidget(hint(
            "Unit-load influence ordinates. Positive ordinates are favourable "
            "for a maximum lane-load response; negative ordinates for a minimum."))
        self.tabs.addTab(influence_page, "Influence lines")
        self.influence_combo.currentIndexChanged.connect(self._show_influence)

        summary_page = QWidget()
        slay = QVBoxLayout(summary_page)
        self.result_summary = QTextEdit()
        self.result_summary.setReadOnly(True)
        self.result_summary.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;")
        slay.addWidget(self.result_summary, 1)
        self.tabs.addTab(summary_page, "Summary")

    def _build_bottom_bar(self) -> None:
        row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setMaximumWidth(280)
        self.status = QLabel("Ready.")
        self.status.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        self.analyze_btn = QPushButton("Run live load")
        self.analyze_btn.setDefault(True)
        self.analyze_btn.clicked.connect(self._analyze)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(self.analyze_btn)
        row.addWidget(self.progress)
        row.addWidget(self.status, 1)
        row.addWidget(close)
        self.body.addLayout(row)

    # --------------------------------------------------------------- defaults
    def _detect_chain(self) -> None:
        """Read the girder chain, supports and E/I from the model."""
        self.chain_spans = []
        self.chain_tags = []
        self.support_x = []
        tags = [tag for tag in self.selected_elements
                if tag in self.project.elements
                and self.project.elements[tag].kind == "beam"]
        if not tags:
            beams = [tag for tag, e in self.project.elements.items()
                     if e.kind == "beam"]
            lanes = sorted(self.project.lanes.values(), key=lambda l: l.tag)
            if lanes:
                lane = lanes[0]
                ux, uy, _uz = lane.direction
                plan_len = (ux * ux + uy * uy) ** 0.5
                if plan_len > 1e-9:
                    ux, uy = ux / plan_len, uy / plan_len
                    candidates = []
                    for tag in beams:
                        e = self.project.elements[tag]
                        a = self.project.node_xyz(e.nodes[0])
                        b = self.project.node_xyz(e.nodes[1])
                        dx, dy = b[0] - a[0], b[1] - a[1]
                        length = (dx * dx + dy * dy) ** 0.5
                        if length <= 1e-9:
                            continue
                        dot = abs(dx * ux + dy * uy) / length
                        if dot < 0.95:
                            continue
                        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
                        lateral = ((mx - lane.shifted_start[0]) * lane.lateral_axis[0]
                                   + (my - lane.shifted_start[1]) * lane.lateral_axis[1])
                        candidates.append((abs(lateral), tag))
                    if candidates:
                        nearest = min(c[0] for c in candidates)
                        tags = [tag for dist, tag in candidates
                                if dist <= nearest + 500.0]
            if not tags:
                tags = beams
        chain = beam_chain_from_project(self.project, tags)
        if chain is None:
            self.chain_note = ("No continuous beam chain with supports was "
                               "found in the model.")
            return
        self.chain_spans, self.chain_E, self.chain_I, self.chain_note = chain
        self.chain_tags = tags
        self.chain_geometry = chain_geometry(self.project, tags)
        xs = [self.project.node_xyz(node)[0]
              for tag in tags if tag in self.project.elements
              for node in self.project.elements[tag].nodes]
        self.chain_start_m = min(xs) / 1000.0 if xs else 0.0
        cumulative = 0.0
        self.support_x = [self.chain_start_m]
        for span in self.chain_spans:
            cumulative += span.length
            self.support_x.append(self.chain_start_m + cumulative)
        self.chain_note += (f" Chain start x = {self.chain_start_m:g} m; "
                            f"supports at "
                            + ", ".join(f"{x:g}" for x in self.support_x)
                            + " m.")

    def _update_model_info(self) -> None:
        if not self.chain_spans:
            self.support_label.setText("Supports: not detected")
            self.span_label.setText("Spans: not detected")
            self.E_label.setText("-")
            self.I_label.setText("-")
            self.chain_label.setText(self.chain_note)
            return
        self.support_label.setText(
            "Support x (m): " + ", ".join(f"{x:g}" for x in self.support_x))
        self.span_label.setText(
            "Spans (m): " + ", ".join(f"{span.length:g}"
                                      for span in self.chain_spans))
        self.E_label.setText(f"{self.chain_E / 1e9:g} GPa")
        self.I_label.setText(f"{self.chain_I:.6g} m4")
        self.chain_label.setText(self.chain_note)

    def _refresh_model(self) -> None:
        self._detect_chain()
        self._update_model_info()
        self._refresh_lanes()
        self._lane_changed()
        self._update_dla_hint()
        self.analyze_btn.setEnabled(bool(self.chain_spans))

    def _load_defaults(self) -> None:
        self._fill_axles(preset_axles("CL-625"), editable=False)
        self.truck_model.setCurrentIndex(0)
        self._refresh_lanes(select_first=True)
        self._lane_changed()
        self._sync_controls()
        self._update_dla_hint()
        self.analyze_btn.setEnabled(bool(self.chain_spans))

    def _beam_start_m(self) -> float:
        if self.chain_spans:
            return self.chain_start_m
        xs = [n.x for n in self.project.nodes.values()]
        return min(xs) / 1000.0 if xs else 0.0

    def _refresh_lanes(self, select_first: bool = False) -> None:
        current = self.lane_combo.currentData() if self.lane_combo.count() else None
        self.lane_combo.blockSignals(True)
        self.lane_combo.clear()
        self.lane_combo.addItem("Custom / bridge ends", None)
        for tag in sorted(self.project.lanes):
            lane = self.project.lanes[tag]
            self.lane_combo.addItem(lane.name, tag)
        index = self.lane_combo.findData(current)
        if select_first and self.lane_combo.count() > 1:
            index = 1
        elif index < 0:
            index = 1 if self.lane_combo.count() > 1 else 0
        self.lane_combo.setCurrentIndex(index)
        self.lane_combo.blockSignals(False)

    def _lane_changed(self, *_args) -> None:
        tag = self.lane_combo.currentData()
        if tag is None:
            self.lane_start.setValue(0.0)
            self.lane_end.setValue(sum(span.length for span in self.chain_spans))
            self.lane_offset.setValue(0.0)
            if not self.lane_name.text().strip():
                self.lane_name.setText("Lane 1")
            return
        lane = self.project.lanes.get(int(tag))
        if lane is None:
            return
        if lane.points:
            low, high = 0.0, lane.length / 1000.0
        else:
            base = self._beam_start_m()
            x0 = lane.shifted_start[0] / 1000.0 - base
            x1 = lane.shifted_end[0] / 1000.0 - base
            low, high = sorted((x0, x1))
        self.lane_start.setValue(low)
        self.lane_end.setValue(high)
        self.lane_offset.setValue(lane.offset / 1000.0)
        self.lane_name.setText(lane.name)

    def _define_lanes(self) -> None:
        from .lane_dialog import LaneDialog

        node_tags = set()
        for tag in self.selected_elements:
            e = self.project.elements.get(tag)
            if e is not None:
                node_tags.update(e.nodes)
        ordered = sorted(
            (tag for tag in node_tags if tag in self.project.nodes),
            key=lambda tag: self.project.nodes[tag].xyz)
        dlg = LaneDialog(self.project, ordered, self.selected_elements, self)
        if not dlg.exec():
            return
        self.project.lanes = {
            tag: lane for tag, lane in dlg.lanes.items() if lane.length > 1e-6}
        self._refresh_lanes(select_first=True)
        self._lane_changed()

    def _fill_axles(self, rows: Sequence[Axle], editable: bool) -> None:
        self.axle_table.blockSignals(True)
        self.axle_table.setRowCount(len(rows))
        for i, axle in enumerate(rows):
            self.axle_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            for col, value in ((1, axle.load), (2, axle.spacing)):
                item = QTableWidgetItem(f"{value:g}")
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if not editable:
                    item.setFlags(Qt.ItemIsEnabled)
                self.axle_table.setItem(i, col, item)
            self.axle_table.item(i, 0).setFlags(Qt.ItemIsEnabled)
        self._set_axle_editabled(editable)
        self.axle_table.blockSignals(False)
        self.vehicle_diagram.set_axles(rows)
        model = self.truck_model.currentData()
        if model == "CL-625":
            self.vehicle_caption.setText(
                "CL-625: five fixed axles, 50 + 125 + 125 + 175 + 150 kN.")
        elif model == "BCL-625":
            self.vehicle_caption.setText(
                "BCL-625: five axles; axle 3-4 gap is enveloped from 6.6 m to "
                "18 m. The schematic shows the 6.6 m base gap.")
        else:
            self.vehicle_caption.setText("Custom vehicle: edit loads and spacing below.")

    def _set_axle_editabled(self, editable: bool) -> None:
        for row in range(self.axle_table.rowCount()):
            for col in (1, 2):
                item = self.axle_table.item(row, col)
                if item is None:
                    continue
                flags = Qt.ItemIsEnabled
                if editable:
                    flags |= Qt.ItemIsEditable
                item.setFlags(flags)

    def _truck_changed(self, *_args) -> None:
        model = self.truck_model.currentData()
        if self._last_truck == "Custom" and model != "Custom":
            try:
                self.custom_axles = self._axles()
            except Exception:
                pass
        if model == "Custom":
            self._fill_axles(self.custom_axles or [Axle(0, 0)], editable=True)
        else:
            self._fill_axles(preset_axles(str(model)), editable=False)
        self._last_truck = str(model)
        self._sync_controls()

    def _add_axle(self) -> None:
        if self.truck_model.currentData() != "Custom":
            return
        if self.axle_table.rowCount() >= MAX_AXLES:
            QMessageBox.information(self, "Live load", f"At most {MAX_AXLES} axles.")
            return
        row = self.axle_table.rowCount()
        self.axle_table.insertRow(row)
        self.axle_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.axle_table.setItem(row, 1, QTableWidgetItem("50"))
        self.axle_table.setItem(row, 2, QTableWidgetItem("0"))
        self._set_axle_editabled(True)
        self._vehicle_changed()

    def _remove_axle(self) -> None:
        if self.truck_model.currentData() != "Custom":
            return
        row = self.axle_table.currentRow()
        if row >= 0 and self.axle_table.rowCount() > 1:
            self.axle_table.removeRow(row)
            for i in range(self.axle_table.rowCount()):
                self.axle_table.item(i, 0).setText(str(i + 1))
            self._vehicle_changed()

    def _sync_controls(self) -> None:
        model = self.truck_model.currentData()
        custom = model == "Custom"
        bcl = model == "BCL-625"
        self.bcl_subdivision.setEnabled(bcl)
        self.bcl_subdivision.setVisible(bcl)
        if self.bcl_label is not None:
            self.bcl_label.setVisible(bcl)
        self.add_axle_btn.setEnabled(custom)
        self.remove_axle_btn.setEnabled(custom)
        self._set_axle_editabled(custom)
        manual = self.dla_mode.currentData() == "manual"
        self.dla_override.setEnabled(manual)
        self._update_dla_hint()

    def _vehicle_changed(self, *_args) -> None:
        model = self.truck_model.currentData()
        if model == "Custom":
            self.vehicle_diagram.set_axles(self._axles())
        elif model == "BCL-625":
            self.vehicle_diagram.set_axles(preset_axles("BCL-625"))
        else:
            self.vehicle_diagram.set_axles(preset_axles(str(model)))

    def _update_dla_hint(self) -> None:
        try:
            spans = self._spans()
            axles = self._axles()
            if spans and axles:
                value, text = auto_dla_info(spans, axles)
                self.dla_hint.setText(text)
                return
        except Exception:
            pass
        self.dla_hint.setText("Auto DLA is evaluated from the axles on each span.")

    # ----------------------------------------------------------------- values
    def _spans(self) -> List[Span]:
        return list(self.chain_spans)

    def _axles(self) -> List[Axle]:
        model = self.truck_model.currentData()
        if model != "Custom":
            return preset_axles(str(model))
        rows = []
        for row in range(self.axle_table.rowCount()):
            try:
                load = float(self.axle_table.item(row, 1).text())
                spacing = float(self.axle_table.item(row, 2).text())
            except (AttributeError, ValueError):
                load, spacing = 0.0, 0.0
            rows.append(Axle(load, spacing))
        return rows

    def config(self) -> LiveLoadConfig:
        manual = self.dla_mode.currentData() == "manual"
        return LiveLoadConfig(
            E=self.chain_E,
            I=self.chain_I,
            elems_per_span=self.elems.value(),
            truck_increment=self.increment.value(),
            load_case="envelope",
            dla_override=self.dla_override.value() / 100.0 if manual else None,
            dla_multiplier=self.dla_multiplier.value() / 100.0,
            lane_udl=self.lane_udl.value(),
            truck_model=str(self.truck_model.currentData()),
            bcl_subdivision=float(self.bcl_subdivision.currentData()),
            lane_name=self.lane_name.text().strip() or "Lane 1",
            lane_start=self.lane_start.value(),
            lane_end=self.lane_end.value(),
            lane_offset=self.lane_offset.value())

    # --------------------------------------------------------------- analysis
    def _analyze(self) -> None:
        try:
            spans = self._spans()
            axles = self._axles()
            config = self.config()
        except Exception as exc:
            QMessageBox.warning(self, "Live load", str(exc))
            return
        if not spans:
            QMessageBox.warning(
                self, "Live load",
                "No continuous beam chain with supports was found in the model. "
                "Check the girder supports, then use Refresh from model.")
            return
        self.analyze_btn.setEnabled(False)
        self.progress.setValue(0)
        self.status.setText("Analyzing...")
        self.status.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")

        def progress(fraction: float, message: str) -> None:
            self.progress.setValue(int(max(0.0, min(1.0, fraction)) * 1000))
            self.status.setText(message)
            QApplication.processEvents()

        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.results = analyze(spans, axles, config, progress)
        except Exception as exc:
            self.results = None
            self.status.setText(str(exc))
            self.status.setStyleSheet("color:#c92a2a; font-weight:600;")
            QMessageBox.warning(self, "Live load", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            self.analyze_btn.setEnabled(True)
        self.progress.setValue(1000)
        self.status.setText("Live-load envelopes ready.")
        self.accept()

    def _sync_result_cases(self) -> None:
        if self.results is None:
            return
        self.result_case.blockSignals(True)
        self.result_case.clear()
        for label, key in (("Truck", "truck"), ("Lane", "lane"),
                           ("Envelope", "envelope")):
            if key in self.results.cases:
                self.result_case.addItem(label, key)
        index = self.result_case.findData(self.results.load_case)
        self.result_case.setCurrentIndex(max(0, index))
        self.result_case.blockSignals(False)

    def _show_results(self, *_args) -> None:
        if self.results is None:
            return
        key = str(self.result_case.currentData() or self.results.load_case)
        case = self.results.cases.get(key)
        if case is None:
            return
        response = self.result_response.currentIndex()
        if response == 0:
            data = case.shear
            title, ylabel = "Shear envelope", "Shear (kN)"
        elif response == 1:
            data = case.moment
            title, ylabel = "Moment envelope", "Moment (kN m)"
        else:
            data = case.deflection
            title, ylabel = "Deflection envelope", "Deflection (mm)"
        xs = [p.x for p in data]
        if response == 2:
            hi = [p.max * 1000.0 for p in data]
            lo = [p.min * 1000.0 for p in data]
        else:
            hi = [p.max for p in data]
            lo = [p.min for p in data]
        self.plot.set_data(xs, hi, lo, "Position along bridge (m)",
                           ylabel, title)

        rows = []
        for name, points, scale in (
                ("Shear (kN)", case.shear, 1.0),
                ("Moment (kN m)", case.moment, 1.0),
                ("Deflection (mm)", case.deflection, 1000.0)):
            pmax = max(points, key=lambda p: p.max * scale)
            pmin = min(points, key=lambda p: p.min * scale)
            rows.append([name, _fmt(pmax.max * scale), _fmt(pmax.x),
                         _fmt(pmin.min * scale), _fmt(pmin.x)])
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.summary_table.setItem(r, c, item)
        self.reaction_table.setRowCount(len(case.reactions))
        for r, reaction in enumerate(case.reactions):
            values = [f"S{r + 1} @ {_fmt(reaction.x)} m", _fmt(reaction.max),
                      _fmt(reaction.min), _fmt(reaction.governing_position),
                      ("-" if reaction.governing_spacing is None
                       else _fmt(reaction.governing_spacing))]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if c:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.reaction_table.setItem(r, c, item)
        self.result_summary.setPlainText(self.results.summary())

    def _show_influence(self, *_args) -> None:
        if self.results is None:
            return
        key = str(self.influence_combo.currentData() or "moment_mid")
        points = self.results.influence.get(key, [])
        if not points:
            self.influence_plot.set_data([], [], [], "Position (m)",
                                         "Influence", "Unit-load influence line")
            return
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        if key == "moment_mid":
            unit, title = "Moment per kN (kN m)", "Moment influence at midspan"
        elif key == "reaction_0":
            unit, title = "Reaction per kN (kN)", "Support 1 reaction influence"
        else:
            unit, title = "Shear per kN (kN)", "Left-end shear influence"
        self.influence_plot.set_data(xs, [max(0.0, y) for y in ys],
                                     [min(0.0, y) for y in ys],
                                     "Load position (m)", unit, title)

    # ----------------------------------------------------------------- export
    def _export(self) -> None:
        if self.results is None:
            QMessageBox.information(self, "Live load", "Run the analysis first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export live-load envelopes", "live_load_envelopes.csv",
            "CSV files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["OpenSees Studio live load", APP_VERSION])
                writer.writerow(["load_case", self.results.load_case])
                writer.writerow(["truck", self.results.config.truck_model])
                writer.writerow(["increment_m", self.results.increment_used])
                writer.writerow(["dla_used", self.results.dla_used])
                writer.writerow([])
                writer.writerow(["case", "response", "x", "max", "min"])
                for case_name, case in self.results.cases.items():
                    for response, points in (("shear", case.shear),
                                             ("moment", case.moment),
                                             ("deflection", case.deflection)):
                        for p in points:
                            writer.writerow([case_name, response, p.x,
                                             p.max, p.min])
                writer.writerow([])
                writer.writerow(["case", "support", "x", "Rmax", "Rmin",
                                 "gov_lead", "gov_spacing"])
                for case_name, case in self.results.cases.items():
                    for s, reaction in enumerate(case.reactions, 1):
                        writer.writerow([case_name, s, reaction.x,
                                         reaction.max, reaction.min,
                                         reaction.governing_position,
                                         reaction.governing_spacing])
            self.status.setText(f"Exported {path}")
        except Exception as exc:
            QMessageBox.warning(self, "Live load", str(exc))
