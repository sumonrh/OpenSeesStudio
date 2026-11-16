"""Tools-tab calculators: section properties and moment-curvature.

Both dialogs are self-contained and return their result to the main window,
which adds the custom section or hinge definition to the project.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath,
                           QPen, QPolygonF)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox,
                               QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QTabWidget, QTextEdit, QVBoxLayout, QWidget)

from . import theme
from .dialogs import BaseDialog, hint, int_spin, spin
from .hinge_catalog import defaults as hinge_defaults
from .model import HingeDefinition, Project, Section
from .moment_curvature import (MomentCurvatureInput, MomentCurvatureResult,
                               run_moment_curvature)
from .section_property import (PARAM_LABELS, SHAPE_DEFS,
                               SectionPropertyResult,
                               compute_section_properties)
from .units import UNITS


# --------------------------------------------------------------------------- #
# drawing helpers
# --------------------------------------------------------------------------- #
def _format(value: float, digits: int = 5) -> str:
    if value is None or not math.isfinite(value):
        return "-"
    magnitude = abs(value)
    if magnitude == 0.0:
        return "0"
    if magnitude < 1e-4 or magnitude >= 1e6:
        return f"{value:.{digits}e}"
    return f"{value:.{digits}g}"


class XYPlot(QWidget):
    """Small dependency-free line plot with optional marker points."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.xs: List[float] = []
        self.ys: List[float] = []
        self.markers: List[Tuple[float, float, str]] = []
        self.xlabel = ""
        self.ylabel = ""
        self.title = ""
        self.setMinimumHeight(300)

    def set_data(self, xs: List[float], ys: List[float],
                 xlabel: str = "", ylabel: str = "", title: str = "",
                 markers: Optional[List[Tuple[float, float, str]]] = None) -> None:
        self.xs = list(xs)
        self.ys = list(ys)
        self.xlabel = xlabel
        self.ylabel = ylabel
        self.title = title
        self.markers = list(markers or [])
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QBrush(QColor("#ffffff")))
        p.setPen(QPen(QColor(theme.BORDER), 1.0))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        left, right, top, bottom = 74, 24, 38, 56
        plot = QRectF(left, top, max(10.0, self.width() - left - right),
                      max(10.0, self.height() - top - bottom))
        p.setPen(QPen(QColor(theme.ACCENT_DARK), 1.0))
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.drawText(QRectF(10, 6, self.width() - 20, 24), Qt.AlignLeft, self.title)
        if not self.xs or not self.ys:
            p.setPen(QPen(QColor(theme.MUTED)))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(plot, Qt.AlignCenter, "No data")
            p.end()
            return
        xmin, xmax = min(self.xs), max(self.xs)
        ymin, ymax = min(self.ys), max(self.ys)
        if xmax - xmin < 1e-12:
            xmax = xmin + 1.0
        if ymax - ymin < 1e-12:
            ymax = ymin + 1.0
        xpad = (xmax - xmin) * 0.04
        ypad = (ymax - ymin) * 0.08
        xmin -= xpad
        xmax += xpad
        ymin -= ypad
        ymax += ypad
        if min(self.xs) >= 0.0:
            xmin = max(0.0, xmin)
        if min(self.ys) >= 0.0:
            ymin = max(0.0, ymin)

        def px(x: float) -> float:
            return plot.left() + (x - xmin) / (xmax - xmin) * plot.width()

        def py(y: float) -> float:
            return plot.bottom() - (y - ymin) / (ymax - ymin) * plot.height()

        p.setFont(QFont("Segoe UI", 8))
        for i in range(6):
            tx = xmin + (xmax - xmin) * i / 5.0
            ty = ymin + (ymax - ymin) * i / 5.0
            x = px(tx)
            y = py(ty)
            p.setPen(QPen(QColor("#e8eef4"), 1.0))
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QPen(QColor(theme.MUTED), 1.0))
            p.drawText(QRectF(x - 44, plot.bottom() + 5, 88, 16),
                       Qt.AlignCenter, _format(tx, 4))
            p.drawText(QRectF(2, y - 8, left - 8, 16),
                       Qt.AlignRight | Qt.AlignVCenter, _format(ty, 4))
        p.setPen(QPen(QColor("#1f3a5f"), 1.2))
        p.drawLine(QPointF(plot.left(), plot.top()),
                   QPointF(plot.left(), plot.bottom()))
        p.drawLine(QPointF(plot.left(), plot.bottom()),
                   QPointF(plot.right(), plot.bottom()))
        if xmin < 0.0 < xmax:
            p.setPen(QPen(QColor("#c4d2df"), 1.0, Qt.DashLine))
            p.drawLine(QPointF(px(0.0), plot.top()),
                       QPointF(px(0.0), plot.bottom()))
        if ymin < 0.0 < ymax:
            p.setPen(QPen(QColor("#c4d2df"), 1.0, Qt.DashLine))
            p.drawLine(QPointF(plot.left(), py(0.0)),
                       QPointF(plot.right(), py(0.0)))
        path = QPainterPath()
        for index, (x, y) in enumerate(zip(self.xs, self.ys)):
            point = QPointF(px(x), py(y))
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        p.setPen(QPen(QColor(theme.ACCENT), 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        for x, y, label in self.markers:
            point = QPointF(px(x), py(y))
            p.setPen(QPen(QColor(theme.ORANGE), 1.4))
            p.setBrush(QBrush(QColor("#ffffff")))
            p.drawEllipse(point, 4.0, 4.0)
            p.setPen(QPen(QColor(theme.ORANGE)))
            p.drawText(QPointF(point.x() + 6, point.y() - 5), label)
        p.setPen(QPen(QColor(theme.ACCENT_DARK)))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(QRectF(plot.left(), plot.bottom() + 22, plot.width(), 18),
                   Qt.AlignCenter, self.xlabel)
        p.save()
        p.translate(13, plot.center().y())
        p.rotate(-90)
        p.drawText(QRectF(-plot.height() / 2.0, -8, plot.height(), 16),
                   Qt.AlignCenter, self.ylabel)
        p.restore()
        p.end()


class SectionShapeView(QWidget):
    """Draw the section outline used by the property calculator."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.result: Optional[SectionPropertyResult] = None
        self.setMinimumHeight(260)

    def set_result(self, result: Optional[SectionPropertyResult]) -> None:
        self.result = result
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QBrush(QColor("#f8fbfe")))
        p.setPen(QPen(QColor(theme.BORDER), 1.0))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        result = self.result
        if result is None or not result.outers:
            p.setPen(QPen(QColor(theme.MUTED)))
            p.drawText(self.rect(), Qt.AlignCenter, "No section")
            p.end()
            return
        points = [pt for poly in result.outers for pt in poly]
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        scale = min((self.width() - 50) / max(x1 - x0, 1e-6),
                    (self.height() - 50) / max(y1 - y0, 1e-6))
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0

        def mapped(poly):
            return QPolygonF([
                QPointF(self.width() / 2.0 + (x - cx) * scale,
                        self.height() / 2.0 - (y - cy) * scale)
                for x, y in poly])

        # Centroid axes.
        ax = self.width() / 2.0 + (result.Cx - cx) * scale
        ay = self.height() / 2.0 - (result.Cy - cy) * scale
        p.setPen(QPen(QColor(theme.ACCENT), 1.0, Qt.DashLine))
        p.drawLine(QPointF(ax, 10), QPointF(ax, self.height() - 10))
        p.drawLine(QPointF(10, ay), QPointF(self.width() - 10, ay))
        p.setBrush(QBrush(QColor("#dcebf9")))
        p.setPen(QPen(QColor(theme.ACCENT_DARK), 1.6))
        for poly in result.outers:
            p.drawPolygon(mapped(poly))
        p.setBrush(QBrush(QColor("#f8fbfe")))
        for poly in result.holes:
            p.drawPolygon(mapped(poly))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(theme.MUTED)))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(QRectF(10, self.height() - 24, self.width() - 20, 18),
                   Qt.AlignCenter,
                   f"{SHAPE_DEFS[result.shape][0]}  |  "
                   f"A = {_format(result.A)} mm2")
        p.end()


# --------------------------------------------------------------------------- #
# Section Property Pro
# --------------------------------------------------------------------------- #
class SectionPropertyDialog(BaseDialog):
    """Calculate section properties and add the result as a custom section."""

    def __init__(self, project: Project, parent=None) -> None:
        super().__init__("Section Property Pro", parent, 1000)
        self.project = project
        self.result: Optional[SectionPropertyResult] = None
        self._name_edited = False
        self.resize(1060, 780)
        self.body.addWidget(hint(
            "Green's-theorem area and inertias, principal axes, elastic section "
            "moduli, and Saint-Venant torsion/warping on a triangular mesh. "
            "Transfer adds a User-defined custom section with the computed "
            "A, Iy, Iz and J."))

        row = QHBoxLayout()
        left = QVBoxLayout()
        form = QFormLayout()
        self.name = QLineEdit("Section Property Pro")
        form.addRow("Section name", self.name)
        self.shape = QComboBox()
        for key, (label, _inputs) in SHAPE_DEFS.items():
            self.shape.addItem(label, key)
        form.addRow("Shape", self.shape)
        left.addLayout(form)

        self.dim_host = QWidget()
        self.dim_form = QGridLayout(self.dim_host)
        self.dim_form.setContentsMargins(0, 0, 0, 0)
        defaults = {"b": 200.0, "d": 300.0, "tf": 15.0, "tw": 10.0,
                    "t": 12.0, "b_inner": 150.0, "d_inner": 250.0,
                    "gap": 50.0, "c": 20.0, "holeR": 50.0}
        self.dim_widgets: Dict[str, QWidget] = {}
        self.dim_labels: Dict[str, QLabel] = {}
        self.dim_rows: Dict[str, int] = {}
        for index, key in enumerate(defaults):
            label = QLabel(PARAM_LABELS.get(key, key))
            if key == "holeR":
                widget = spin(UNITS.length(defaults[key]), 0.0,
                              UNITS.length(1e7), UNITS.length_decimals,
                              UNITS.length(10.0), UNITS.length_unit)
            else:
                widget = spin(UNITS.length(defaults[key]), UNITS.length(0.001),
                              UNITS.length(1e7), UNITS.length_decimals,
                              UNITS.length(10.0), UNITS.length_unit)
            widget.valueChanged.connect(self._schedule)
            self.dim_widgets[key] = widget
            self.dim_labels[key] = label
            row_index = index // 2
            column = (index % 2) * 2
            self.dim_rows[key] = row_index
            self.dim_form.addWidget(label, row_index, column)
            self.dim_form.addWidget(widget, row_index, column + 1)
        left.addWidget(self.dim_host)

        self.resolution = QComboBox()
        self.resolution.addItem("Standard mesh", 9000)
        self.resolution.addItem("Fine mesh (slower)", 16000)
        self.resolution.addItem("Coarse mesh (fast)", 5000)
        mesh_row = QFormLayout()
        mesh_row.addRow("Torsion / warping mesh", self.resolution)
        left.addLayout(mesh_row)
        self.calculate_btn = QPushButton("Calculate")
        self.calculate_btn.clicked.connect(self._calculate)
        left.addWidget(self.calculate_btn)
        self.status = QLabel("Enter the dimensions, then Calculate.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        left.addWidget(self.status)
        left.addWidget(hint(
            "The transferred section is stored as a User-defined custom "
            "section, so the calculated values are not replaced by the "
            "approximate formulas used by the parametric shapes."))
        left.addStretch(1)
        row.addLayout(left, 0)

        right = QVBoxLayout()
        self.preview = SectionShapeView()
        right.addWidget(self.preview, 1)
        self.props = QTextEdit()
        self.props.setReadOnly(True)
        self.props.setMinimumHeight(250)
        self.props.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;")
        right.addWidget(self.props, 0)
        row.addLayout(right, 1)
        self.body.addLayout(row, 1)

        self.shape.currentIndexChanged.connect(self._shape_changed)
        self.resolution.currentIndexChanged.connect(self._schedule)
        self.name.textEdited.connect(lambda _t: setattr(self, "_name_edited", True))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._calculate)
        self._sync_shape()
        self.buttons("Transfer to Section Library")

    def _sync_shape(self) -> None:
        key = self.shape.currentData() or "IShape"
        used = set(SHAPE_DEFS[key][1])
        for name, label in self.dim_labels.items():
            visible = name in used
            label.setVisible(visible)
            self.dim_widgets[name].setVisible(visible)

    def _shape_changed(self, *_args) -> None:
        self._sync_shape()
        if not self._name_edited:
            self.name.setText(f"SPP {SHAPE_DEFS[self.shape.currentData()][0]}")
        self._schedule()

    def _schedule(self, *_args) -> None:
        if not self._name_edited:
            key = self.shape.currentData() or "IShape"
            self.name.setText(f"SPP {SHAPE_DEFS[key][0]}")
        self._timer.start()

    def _params(self) -> dict:
        key = self.shape.currentData() or "IShape"
        out = {}
        for name in SHAPE_DEFS[key][1]:
            out[name] = UNITS.length_base(self.dim_widgets[name].value())
        return out

    def _calculate(self) -> None:
        self._timer.stop()
        key = self.shape.currentData() or "IShape"
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            QApplication.processEvents()
            result = compute_section_properties(
                key, self._params(),
                max_nodes=int(self.resolution.currentData() or 9000))
        except Exception as exc:
            self.result = None
            self.preview.set_result(None)
            self.props.setPlainText(str(exc))
            self.status.setText(str(exc))
            self.status.setStyleSheet("color:#c92a2a; font-weight:600;")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.result = result
        self.preview.set_result(result)
        self.status.setText(
            f"{SHAPE_DEFS[key][0]} calculated"
            + (f" - {result.mesh_nodes} mesh nodes" if result.mesh_nodes else ""))
        self.status.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        self._fill_properties(result)

    def _fill_properties(self, r: SectionPropertyResult) -> None:
        lines = [
            f"Area A              {_format(r.A)} mm2",
            f"Mass (steel)        {_format(r.mass_per_length)} kg/m",
            "",
            f"Centroid Cx         {_format(r.Cx)} mm",
            f"Centroid Cy         {_format(r.Cy)} mm",
            f"Ix (strong)         {_format(r.Ix)} mm4",
            f"Iy (weak)           {_format(r.Iy)} mm4",
            f"Ixy                 {_format(r.Ixy)} mm4",
            f"Polar Ip            {_format(r.Ip)} mm4",
            f"Principal I1        {_format(r.I1)} mm4",
            f"Principal I2        {_format(r.I2)} mm4",
            f"Principal angle     {_format(r.alpha, 4)} deg",
            "",
            f"Sx top / bottom     {_format(r.SxTop)} / {_format(r.SxBot)} mm3",
            f"Sy right / left     {_format(r.SyRight)} / {_format(r.SyLeft)} mm3",
            f"Radius rx / ry      {_format(r.rx)} / {_format(r.ry)} mm",
            "",
            f"Torsion J           {_format(r.J)} mm4  ({r.torsion_source or '-'})",
            f"Warping Cw          {_format(r.Cw)} mm6  ({r.warping_source or '-'})",
        ]
        if r.mesh_nodes:
            lines.append(f"Mesh                {r.mesh_nodes} nodes / "
                         f"{r.mesh_elements} triangles")
        for warning in r.warnings:
            lines.append(f"Warning: {warning}")
        self.props.setPlainText("\n".join(lines))

    def result_section(self) -> Optional[Section]:
        if self.result is None:
            return None
        r = self.result
        section = Section(self.project.next_section(),
                          self.name.text().strip() or "Section Property Pro",
                          shape="User")
        section.A = r.A
        section.Iy = r.Ix      # OpenSees local y bending uses the strong axis
        section.Iz = r.Iy
        section.J = r.J
        section.catalog = "Custom"
        section.designation = ""
        section.family = "Section Property Pro"
        section.cy = section.cz = 0.0
        outer, inner = r.outline()
        section.outline_outer = [[float(y), float(z)] for y, z in outer]
        section.outline_inner = ([[float(y), float(z)] for y, z in inner]
                                 if inner else [])
        return section

    def accept(self) -> None:
        self._timer.stop()
        self._calculate()
        if self.result is None:
            QMessageBox.warning(self, "Section Property Pro",
                                "Calculate a valid section first.")
            return
        super().accept()


# --------------------------------------------------------------------------- #
# Moment Curvature Pro
# --------------------------------------------------------------------------- #
class MomentCurvatureDialog(BaseDialog):
    """Moment-curvature analysis and spring-hinge backbone generation."""

    def __init__(self, project: Project, selected_beams: Optional[List[int]] = None,
                 parent=None) -> None:
        super().__init__("Moment Curvature Pro", parent, 1080)
        self.project = project
        self.selected_beams = list(selected_beams or [])
        self.result: Optional[MomentCurvatureResult] = None
        self._dirty = True
        self.resize(1120, 900)
        self.body.addWidget(hint(
            "Mander confined/unconfined concrete and a Park steel envelope are "
            "integrated over a fibre grid for axial load and biaxial bending. "
            "The strong-axis curve is idealised to a trilinear moment-rotation "
            "backbone and stored as a spring hinge definition, ready for "
            "pushover and nonlinear time history."))

        top = QGridLayout()
        self.name = QLineEdit("Moment backbone")
        self.section = QComboBox()
        self.section.addItem("Rectangular", "rectangular")
        self.section.addItem("Circular", "circular")
        self.axis = QComboBox()
        self.axis.addItem("Strong axis", "strong")
        self.axis.addItem("Weak axis", "weak")
        self.fc = spin(30.0, 1.0, 150.0, 1, 5.0, "MPa")
        self.fy = spin(420.0, 100.0, 1200.0, 1, 50.0, "MPa")
        self.P = spin(0.0, UNITS.force(-1e9), UNITS.force(1e9), 2,
                      UNITS.force(100.0), UNITS.force_unit)
        self.L = spin(UNITS.length(4000.0), UNITS.length(10.0),
                      UNITS.length(1e6), UNITS.length_decimals,
                      UNITS.length(500.0), UNITS.length_unit)
        top.addWidget(QLabel("Hinge name"), 0, 0)
        top.addWidget(self.name, 0, 1)
        top.addWidget(QLabel("Section"), 0, 2)
        top.addWidget(self.section, 0, 3)
        top.addWidget(QLabel("Hinge axis"), 1, 0)
        top.addWidget(self.axis, 1, 1)
        top.addWidget(QLabel("Member length L"), 1, 2)
        top.addWidget(self.L, 1, 3)
        top.addWidget(QLabel("fc"), 2, 0)
        top.addWidget(self.fc, 2, 1)
        top.addWidget(QLabel("fy"), 2, 2)
        top.addWidget(self.fy, 2, 3)
        top.addWidget(QLabel("Axial load P (+ compression)"), 3, 0)
        top.addWidget(self.P, 3, 1)
        self.assign = QCheckBox(
            f"Assign to selected beam elements ({len(self.selected_beams)})")
        self.assign.setChecked(bool(self.selected_beams))
        self.assign.setEnabled(bool(self.selected_beams))
        top.addWidget(self.assign, 3, 2, 1, 2)
        self.body.addLayout(top)

        self.geometry_page = QWidget()
        geometry_form = QGridLayout(self.geometry_page)
        self.B = spin(UNITS.length(400.0), UNITS.length(10.0), UNITS.length(1e7),
                      UNITS.length_decimals, UNITS.length(50.0), UNITS.length_unit)
        self.H = spin(UNITS.length(600.0), UNITS.length(10.0), UNITS.length(1e7),
                      UNITS.length_decimals, UNITS.length(50.0), UNITS.length_unit)
        self.nx = int_spin(4, 2, 100)
        self.ny = int_spin(4, 2, 100)
        self.D = spin(UNITS.length(600.0), UNITS.length(10.0), UNITS.length(1e7),
                      UNITS.length_decimals, UNITS.length(50.0), UNITS.length_unit)
        self.n_bars = int_spin(12, 4, 200)
        self.cover = spin(UNITS.length(40.0), UNITS.length(1.0),
                          UNITS.length(1e6), UNITS.length_decimals,
                          UNITS.length(10.0), UNITS.length_unit)
        self.db = spin(UNITS.length(25.0), UNITS.length(1.0), UNITS.length(1e5),
                       UNITS.length_decimals, UNITS.length(5.0), UNITS.length_unit)
        self.dbt = spin(UNITS.length(10.0), UNITS.length(1.0), UNITS.length(1e5),
                        UNITS.length_decimals, UNITS.length(2.0), UNITS.length_unit)
        self.s = spin(UNITS.length(100.0), UNITS.length(1.0), UNITS.length(1e6),
                      UNITS.length_decimals, UNITS.length(10.0), UNITS.length_unit)
        self._geometry_rows: Dict[str, Tuple[QLabel, QWidget, int, int]] = {}

        def add_geometry(key: str, text: str, widget: QWidget) -> None:
            row = len(self._geometry_rows) // 2
            col = (len(self._geometry_rows) % 2) * 2
            label = QLabel(text)
            geometry_form.addWidget(label, row, col)
            geometry_form.addWidget(widget, row, col + 1)
            self._geometry_rows[key] = (label, widget, row, col)

        add_geometry("B", "Width B", self.B)
        add_geometry("H", "Depth H", self.H)
        add_geometry("nx", "Bars per top/bottom nx", self.nx)
        add_geometry("ny", "Bars per side ny", self.ny)
        add_geometry("D", "Diameter D", self.D)
        add_geometry("n_bars", "Number of bars", self.n_bars)
        add_geometry("cover", "Cover", self.cover)
        add_geometry("db", "Longitudinal db", self.db)
        add_geometry("dbt", "Tie dbt", self.dbt)
        add_geometry("s", "Tie spacing s", self.s)
        self.body.addWidget(self.geometry_page)

        self.calculate_btn = QPushButton("Calculate moment-curvature and backbone")
        self.calculate_btn.clicked.connect(self._calculate)
        self.body.addWidget(self.calculate_btn)
        self.status = QLabel("Enter the section and reinforcement, then Calculate.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        self.body.addWidget(self.status)

        self.tabs = QTabWidget()
        self.mc_plot = XYPlot()
        self.backbone_plot = XYPlot()
        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;")
        self.tabs.addTab(self.mc_plot, "Moment-curvature")
        self.tabs.addTab(self.backbone_plot, "Backbone")
        self.tabs.addTab(self.summary, "Summary")
        self.body.addWidget(self.tabs, 1)

        self.section.currentIndexChanged.connect(self._sync_section)
        self.section.currentIndexChanged.connect(self._mark_dirty)
        self.axis.currentIndexChanged.connect(self._axis_changed)
        for widget in (self.fc, self.fy, self.P, self.L, self.B, self.H,
                       self.nx, self.ny, self.D, self.n_bars, self.cover,
                       self.db, self.dbt, self.s):
            widget.valueChanged.connect(self._mark_dirty)
        self._sync_section()
        self.buttons("Create Hinge")

    def _sync_section(self, *_args) -> None:
        circular = self.section.currentData() == "circular"
        hidden = {"D", "n_bars"} if not circular else {"B", "H", "nx", "ny"}
        for key in ("B", "H", "nx", "ny", "D", "n_bars"):
            label, widget, _row, _col = self._geometry_rows[key]
            visible = key not in hidden
            label.setVisible(visible)
            widget.setVisible(visible)
        self.axis.setEnabled(not circular)
        if circular:
            self.axis.setCurrentIndex(0)

    def _axis_changed(self, *_args) -> None:
        self._mark_dirty()
        if self.result is not None:
            self._show_result()

    def _mark_dirty(self, *_args) -> None:
        self._dirty = True
        if self.result is not None:
            self.status.setText(
                "Inputs changed - click Calculate (or Create Hinge) to refresh "
                "the curve and backbone.")
            self.status.setStyleSheet("color:#b26a00; font-size:11px;")

    def _inputs(self) -> MomentCurvatureInput:
        section = str(self.section.currentData())
        inp = MomentCurvatureInput(
            section=section,
            B=UNITS.length_base(self.B.value()),
            H=UNITS.length_base(self.H.value()),
            D=UNITS.length_base(self.D.value()),
            cover=UNITS.length_base(self.cover.value()),
            nx=self.nx.value(), ny=self.ny.value(),
            n_bars=self.n_bars.value(),
            db=UNITS.length_base(self.db.value()),
            dbt=UNITS.length_base(self.dbt.value()),
            s=UNITS.length_base(self.s.value()),
            fc=self.fc.value(), fy=self.fy.value(),
            P=UNITS.force_base(self.P.value()),
            L=UNITS.length_base(self.L.value()))
        return inp

    def _calculate(self) -> None:
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            QApplication.processEvents()
            self.result = run_moment_curvature(self._inputs())
        except Exception as exc:
            self.result = None
            self.status.setText(str(exc))
            self.status.setStyleSheet("color:#c92a2a; font-weight:600;")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._dirty = False
        self.status.setText(
            "Moment-curvature converged; the selected axis is idealised to a "
            "trilinear rotation backbone.")
        self.status.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        if not self.name.text().strip():
            self.name.setText("Moment backbone")
        self._show_result()

    def _current_curve(self):
        if self.result is None:
            return None
        if self.axis.currentData() == "weak" and self.result.weak is not None:
            return self.result.weak
        return self.result.strong

    def _show_result(self) -> None:
        curve = self._current_curve()
        if curve is None or not curve.moments:
            self.mc_plot.set_data([], [], "Curvature (1/m)", "Moment (kN m)",
                                  "Moment-curvature")
            self.backbone_plot.set_data([], [], "Rotation (rad)",
                                        "Moment (kN m)", "Idealised backbone")
            return
        markers = []
        if curve.yield_moment:
            markers.append((curve.yield_rotation, curve.yield_moment / 1000.0,
                            "My"))
        if curve.peak_moment:
            markers.append((curve.peak_rotation, curve.peak_moment / 1000.0,
                            "Mp"))
        if (curve.ultimate_moment
                and abs(curve.ultimate_moment - curve.peak_moment) > 1e-6):
            markers.append((curve.ultimate_rotation,
                            curve.ultimate_moment / 1000.0, "Mu"))
        self.mc_plot.set_data(
            curve.curvatures, curve.moments, "Curvature (1/m)",
            "Moment (kN m)", "Moment-curvature")
        self.backbone_plot.set_data(
            [p[0] for p in curve.backbone],
            [p[1] / 1000.0 for p in curve.backbone],
            "Plastic rotation (rad)", "Moment (kN m)",
            "Idealised moment-rotation backbone", markers)
        lines = [
            f"Section              {self.result.inputs.section}",
            f"Hinge axis           {self.axis.currentData()}",
            f"Concrete fc          {self.result.inputs.fc:g} MPa",
            f"Steel fy             {self.result.inputs.fy:g} MPa",
            f"Axial load P         {_format(self.result.inputs.P)} kN compression",
            f"Gross area Ag        {_format(self.result.Ag)} mm2",
            f"Steel area Ast       {_format(self.result.Ast)} mm2",
            f"Reinforcement ratio  {self.result.reinforcement_ratio * 100:.3f} %",
            "",
            f"Confined fcc         {_format(self.result.confinement['fcc'])} MPa",
            f"Confined ecc         {_format(self.result.confinement['ecc'], 6)}",
            f"Ultimate ecu         {_format(self.result.confinement['ecu'], 6)}",
            f"Confinement fLp      {_format(self.result.confinement['fLp'])} MPa",
            f"Plastic hinge Lp     {_format(self.result.Lp_mm)} mm",
            "",
            f"Yield moment My      {_format(curve.yield_moment / 1000.0)} kN m",
            f"Peak moment Mu       {_format(curve.peak_moment / 1000.0)} kN m",
            f"Ultimate moment      {_format(curve.ultimate_moment / 1000.0)} kN m",
            f"Yield rotation       {_format(curve.yield_rotation, 6)} rad",
            f"Peak rotation        {_format(curve.peak_rotation, 6)} rad",
            f"Ultimate rotation    {_format(curve.ultimate_rotation, 6)} rad",
            f"Initial stiffness    {_format(curve.initial_stiffness)} kN mm/rad",
            f"Post-yield ratio b   {_format(curve.post_yield_ratio, 4)}",
            f"Rotation ductility   {_format(curve.ductility, 4)}",
            f"Converged points     {curve.converged} / {curve.total}",
        ]
        for warning in self.result.warnings:
            lines.append(f"Warning: {warning}")
        lines.append("")
        lines.append("Spring hinge backbone points (rotation rad, moment kN m):")
        for rotation, moment in curve.backbone:
            lines.append(f"  {rotation:10.6g}   {moment / 1000.0:12.6g}")
        self.summary.setPlainText("\n".join(lines))

    def hinge(self) -> Optional[HingeDefinition]:
        curve = self._current_curve()
        if curve is None or len(curve.backbone) < 2 or curve.peak_moment <= 0:
            return None
        points = [[float(r), float(m)] for r, m in curve.backbone[1:]]
        if len(points) > 3:
            points = [points[0], points[len(points) // 2], points[-1]]
        while len(points) < 3:
            r, m = points[-1]
            points.append([r * 1.1, m])
        params = hinge_defaults("MomentBackbone")
        params["damage1"] = 0.0
        params["damage2"] = 0.0
        definition = HingeDefinition(
            self.project.next_hinge(),
            self.name.text().strip() or "Moment backbone",
            "MomentBackbone", "Moment-rotation (spring)",
            max(0.01, min(0.25, self.result.Lp_mm / max(self.result.inputs.L, 1.0))),
            params)
        definition.curve = points
        return definition

    def accept(self) -> None:
        if self.result is None or self._dirty:
            self._calculate()
        if self.result is None:
            QMessageBox.warning(self, "Moment Curvature Pro",
                                "Calculate a valid moment-curvature result first.")
            return
        super().accept()
