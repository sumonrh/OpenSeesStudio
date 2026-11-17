"""Midas-style bridge live-load dialog: lanes, trucks, envelopes and influence lines."""

from __future__ import annotations

import csv
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath,
                           QPen)
from PySide6.QtWidgets import (QAbstractItemView, QApplication,
                               QComboBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QProgressBar, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QTextEdit, QVBoxLayout, QWidget)

from . import theme
from .dialogs import BaseDialog, hint, int_spin, spin
from .live_load import (BCL_SUBDIVISIONS, DEFAULT_LANE_UDL, MAX_AXLES,
                        MAX_SPANS, Axle, LiveLoadConfig, LiveLoadResults,
                        Span, analyze, auto_dla_info, beam_chain_from_project,
                        preset_axles)
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
        self.resize(1240, 900)
        self.body.addWidget(hint(
            "Moving truck and lane-load envelopes for a continuous bridge beam. "
            "Supports are pinned at every span boundary; rotations remain "
            "continuous. The engine uses a beam FEM with unit-load influence "
            "functions, selected-axle DLA and favourable UDL zones. Units: "
            "spans m, E GPa, I m4, axle loads kN, moment kN m."))

        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)
        self._build_structure_tab()
        self._build_vehicle_tab()
        self._build_results_tab()
        self._build_bottom_bar()
        self._sync_controls()
        self._load_defaults()

    # ------------------------------------------------------------------ tabs
    def _build_structure_tab(self) -> None:
        page = QWidget()
        lay = QHBoxLayout(page)
        left = QVBoxLayout()
        self.span_table = QTableWidget(3, 2)
        self.span_table.setHorizontalHeaderLabels(["Span", "Length (m)"])
        self.span_table.verticalHeader().setVisible(False)
        self.span_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.span_table.horizontalHeader().setStretchLastSection(True)
        self.span_table.setColumnWidth(0, 90)
        self.span_table.setMaximumWidth(300)
        left.addWidget(QLabel("Continuous beam spans"))
        left.addWidget(self.span_table, 1)
        row = QHBoxLayout()
        add = QPushButton("Add span")
        add.clicked.connect(self._add_span)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_span)
        row.addWidget(add)
        row.addWidget(remove)
        left.addLayout(row)
        import_btn = QPushButton("Import selected beam chain")
        import_btn.setEnabled(bool(self.selected_elements))
        import_btn.clicked.connect(self._import_chain)
        left.addWidget(import_btn)
        self.chain_label = QLabel()
        self.chain_label.setWordWrap(True)
        self.chain_label.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        left.addWidget(self.chain_label)
        lay.addLayout(left, 0)

        right = QVBoxLayout()
        form = QFormLayout()
        self.E = spin(200.0, 1.0, 1000.0, 3, 10.0, "GPa")
        self.I = spin(0.005, 1e-9, 100.0, 6, 0.001, "m4")
        self.elems = int_spin(20, 2, 40)
        self.increment = spin(0.25, 0.01, 10.0, 3, 0.05, "m")
        form.addRow("Young's modulus E", self.E)
        form.addRow("Moment of inertia I", self.I)
        form.addRow("Elements per span", self.elems)
        form.addRow("Truck sweep increment", self.increment)
        right.addLayout(form)
        right.addWidget(hint(
            "Choose a bridge girder line in the viewport, then use Import to "
            "fill the spans and mean E/I from the selected beam chain. Elements "
            "per span controls the beam mesh used by the influence engine."))
        right.addWidget(QLabel("Analysis method"))
        method = QLabel(
            "Midas-style influence-line moving load: the stiffness matrix is "
            "factorized once, unit point loads at four stations per element give "
            "cubic influence functions, truck extrema are refined around the "
            "best sweep positions, and lane UDL uses each response's favourable "
            "positive/negative zones. This is not a time-history vehicle run.")
        method.setWordWrap(True)
        method.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        right.addWidget(method)
        right.addStretch(1)
        lay.addLayout(right, 1)
        self.tabs.addTab(page, "Structure")

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
        self.load_case = QComboBox()
        self.load_case.addItem("Truck only", "truck")
        self.load_case.addItem("Lane load", "lane")
        self.load_case.addItem("Envelope (Truck + Lane)", "envelope")
        self.dla_mode = QComboBox()
        self.dla_mode.addItem("Auto (selected-axle groups)", "auto")
        self.dla_mode.addItem("Manual override", "manual")
        self.dla_override = spin(25.0, 0.0, 100.0, 1, 5.0, "%")
        self.dla_multiplier = spin(100.0, 0.0, 100.0, 1, 10.0, "%")
        form.addRow("Truck / vehicle", self.truck_model)
        form.addRow("BCL axle 3-4 subdivision", self.bcl_subdivision)
        form.addRow("Lane name", self.lane_name)
        form.addRow("Lane load UDL", self.lane_udl)
        form.addRow("Load case", self.load_case)
        form.addRow("DLA mode", self.dla_mode)
        form.addRow("Manual DLA", self.dla_override)
        form.addRow("DLA multiplier d", self.dla_multiplier)
        left.addLayout(form)
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
        self.dla_mode.currentIndexChanged.connect(self._sync_controls)
        self.load_case.currentIndexChanged.connect(self._sync_controls)
        self.span_table.cellChanged.connect(lambda *_: self._update_dla_hint())

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
        self.analyze_btn = QPushButton("Analyze live load")
        self.analyze_btn.setDefault(True)
        self.analyze_btn.clicked.connect(self._analyze)
        self.export_btn = QPushButton("Export CSV")
        self.export_btn.clicked.connect(self._export)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(self.analyze_btn)
        row.addWidget(self.export_btn)
        row.addWidget(self.progress)
        row.addWidget(self.status, 1)
        row.addWidget(close)
        self.body.addLayout(row)

    # --------------------------------------------------------------- defaults
    def _load_defaults(self) -> None:
        spans = [20.0, 25.0, 20.0]
        for i, value in enumerate(spans):
            self.span_table.setItem(i, 0, QTableWidgetItem(f"S{i + 1}"))
            self.span_table.setItem(i, 1, QTableWidgetItem(f"{value:g}"))
        self.span_table.item(0, 0).setFlags(Qt.ItemIsEnabled)
        self._fill_axles(preset_axles("CL-625"), editable=False)
        self.truck_model.setCurrentIndex(0)
        self._sync_controls()
        self._update_dla_hint()

    def _fill_axles(self, rows: Sequence[Axle], editable: bool) -> None:
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

    def _add_span(self) -> None:
        if self.span_table.rowCount() >= MAX_SPANS:
            QMessageBox.information(self, "Live load", f"At most {MAX_SPANS} spans.")
            return
        row = self.span_table.rowCount()
        self.span_table.insertRow(row)
        self.span_table.setItem(row, 0, QTableWidgetItem(f"S{row + 1}"))
        self.span_table.setItem(row, 1, QTableWidgetItem("20"))
        self._renumber_spans()

    def _remove_span(self) -> None:
        row = self.span_table.currentRow()
        if row < 0 or self.span_table.rowCount() <= 1:
            return
        self.span_table.removeRow(row)
        self._renumber_spans()

    def _renumber_spans(self) -> None:
        for row in range(self.span_table.rowCount()):
            item = self.span_table.item(row, 0)
            if item is None:
                self.span_table.setItem(row, 0, QTableWidgetItem(f"S{row + 1}"))
            else:
                item.setText(f"S{row + 1}")

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

    def _remove_axle(self) -> None:
        if self.truck_model.currentData() != "Custom":
            return
        row = self.axle_table.currentRow()
        if row >= 0 and self.axle_table.rowCount() > 1:
            self.axle_table.removeRow(row)
            for i in range(self.axle_table.rowCount()):
                self.axle_table.item(i, 0).setText(str(i + 1))

    def _sync_controls(self) -> None:
        model = self.truck_model.currentData()
        custom = model == "Custom"
        self.bcl_subdivision.setEnabled(model == "BCL-625")
        self.add_axle_btn.setEnabled(custom)
        self.remove_axle_btn.setEnabled(custom)
        self._set_axle_editabled(custom)
        manual = self.dla_mode.currentData() == "manual"
        self.dla_override.setEnabled(manual)
        self._update_dla_hint()

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
        out = []
        for row in range(self.span_table.rowCount()):
            item = self.span_table.item(row, 1)
            try:
                value = float(item.text()) if item else 0.0
            except ValueError:
                value = 0.0
            out.append(Span(value))
        return out

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
            E=self.E.value() * 1e9,
            I=self.I.value(),
            elems_per_span=self.elems.value(),
            truck_increment=self.increment.value(),
            load_case=str(self.load_case.currentData()),
            dla_override=self.dla_override.value() / 100.0 if manual else None,
            dla_multiplier=self.dla_multiplier.value() / 100.0,
            lane_udl=self.lane_udl.value(),
            truck_model=str(self.truck_model.currentData()),
            bcl_subdivision=float(self.bcl_subdivision.currentData()),
            lane_name=self.lane_name.text().strip() or "Lane 1")

    # --------------------------------------------------------------- analysis
    def _analyze(self) -> None:
        try:
            spans = self._spans()
            axles = self._axles()
            config = self.config()
        except Exception as exc:
            QMessageBox.warning(self, "Live load", str(exc))
            return
        self.analyze_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
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
            self.export_btn.setEnabled(True)
        self.progress.setValue(1000)
        self.status.setText("Analysis complete.")
        self.result_summary.setPlainText(self.results.summary())
        self._sync_result_cases()
        self._show_results()
        self._show_influence()
        self.tabs.setCurrentIndex(2)

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

    # ----------------------------------------------------------------- import
    def _import_chain(self) -> None:
        chain = beam_chain_from_project(self.project, self.selected_elements)
        if chain is None:
            QMessageBox.information(
                self, "Live load",
                "Select a connected chain of beam elements along a bridge "
                "girder, then import it.")
            return
        spans, E, I, note = chain
        self.span_table.setRowCount(len(spans))
        for row, span in enumerate(spans):
            item0 = QTableWidgetItem(f"S{row + 1}")
            item0.setFlags(Qt.ItemIsEnabled)
            self.span_table.setItem(row, 0, item0)
            self.span_table.setItem(row, 1, QTableWidgetItem(f"{span.length:g}"))
        self.E.setValue(E / 1e9)
        self.I.setValue(I)
        self._chain_note = note
        self.chain_label.setText(note)
        self._update_dla_hint()

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
