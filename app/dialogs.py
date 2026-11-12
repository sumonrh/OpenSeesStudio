"""Dialog boxes for model generation, loads and analysis settings."""

from __future__ import annotations

import copy
import math
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QRadioButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from . import steelsections, theme
from .model import (COMBINATION_KINDS, ELEMENT_KINDS, LOADCASE_KINDS,
                    LOAD_DIRECTIONS, MATERIAL_KINDS, SECTION_SHAPES,
                    SHAPE_LABELS, Element, LoadCase, LoadCombination, Material,
                    Project, Section, fmt)
from .units import UNITS


# --------------------------------------------------------------------------- #
# widgets
# --------------------------------------------------------------------------- #
def spin(value: float = 0.0, lo: float = -1e9, hi: float = 1e9, dec: int = 3,
         step: float = 100.0, suffix: str = "") -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(dec)
    w.setSingleStep(step)
    w.setValue(value)
    if suffix:
        w.setSuffix(" " + suffix)
    w.setKeyboardTracking(False)
    return w


def int_spin(value: int = 1, lo: int = 1, hi: int = 100000) -> QSpinBox:
    w = QSpinBox()
    w.setRange(lo, hi)
    w.setValue(value)
    return w


def hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(f"color: {theme.MUTED}; font-size: 11px;")
    lab.setWordWrap(True)
    return lab


def title_label(text: str) -> QLabel:
    lab = QLabel(text)
    f = QFont("Segoe UI", 9, QFont.Bold)
    lab.setFont(f)
    lab.setStyleSheet(f"color: {theme.ACCENT_DARK}; margin-top: 2px;")
    return lab


class BaseDialog(QDialog):
    def __init__(self, title: str, parent=None, width: int = 460) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.setModal(True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(14, 12, 14, 12)
        self.body.setSpacing(9)

    def buttons(self, ok_text: str = "Apply", cancel_text: str = "Close") -> None:
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(cancel_text)
        cancel.clicked.connect(self.reject)
        ok = QPushButton(ok_text)
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        self.body.addLayout(row)


def _list_line(text: str) -> str:
    return text.replace(" ", "")


def parse_tags(text: str) -> List[int]:
    out: List[int] = []
    for part in _list_line(text).split(","):
        if not part:
            continue
        if "-" in part[1:]:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


# --------------------------------------------------------------------------- #
# node / element
# --------------------------------------------------------------------------- #
class NodeDialog(BaseDialog):
    def __init__(self, project: Project, parent=None) -> None:
        super().__init__("Create Nodes", parent, 420)
        self.project = project
        self.body.addWidget(title_label("Coordinates"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.x = spin(0.0, -1e12, 1e12, UNITS.length_decimals,
                        UNITS.length(100.0), UNITS.length_unit)
        self.y = spin(0.0, -1e12, 1e12, UNITS.length_decimals,
                        UNITS.length(100.0), UNITS.length_unit)
        self.z = spin(0.0, -1e12, 1e12, UNITS.length_decimals,
                        UNITS.length(100.0), UNITS.length_unit)
        form.addRow("X", self.x)
        form.addRow("Y", self.y)
        form.addRow("Z", self.z)
        self.body.addLayout(form)

        self.body.addWidget(title_label("Repeat"))
        grid = QGridLayout()
        self.count = int_spin(1, 1, 500)
        self.dx = spin(0.0, -1e12, 1e12, UNITS.length_decimals,
                         UNITS.length(100.0), UNITS.length_unit)
        self.dy = spin(0.0, -1e12, 1e12, UNITS.length_decimals,
                         UNITS.length(100.0), UNITS.length_unit)
        self.dz = spin(0.0, -1e12, 1e12, UNITS.length_decimals,
                         UNITS.length(100.0), UNITS.length_unit)
        grid.addWidget(QLabel("Number of nodes"), 0, 0)
        grid.addWidget(self.count, 0, 1)
        grid.addWidget(QLabel("ΔX  ΔY  ΔZ  spacing"), 1, 0, 1, 2)
        row = QHBoxLayout()
        row.addWidget(self.dx); row.addWidget(self.dy); row.addWidget(self.dz)
        grid.addLayout(row, 2, 0, 1, 2)
        self.body.addLayout(grid)
        self.body.addWidget(hint("Node tags are assigned automatically. "
                                 "Repeated nodes are spaced by (ΔX, ΔY, ΔZ) each step."))
        self.buttons("Create")

    def positions(self) -> List[Tuple[float, float, float]]:
        n = self.count.value()
        return [(UNITS.length_base(self.x.value() + i * self.dx.value()),
                 UNITS.length_base(self.y.value() + i * self.dy.value()),
                 UNITS.length_base(self.z.value() + i * self.dz.value())) for i in range(n)]


class ElementDialog(BaseDialog):
    def __init__(self, project: Project, selected_nodes: List[int], parent=None) -> None:
        super().__init__("Create Elements", parent, 470)
        self.project = project
        self.body.addWidget(title_label("Element type"))
        self.kind = QComboBox()
        self.kind.addItem("Beam  (elasticBeamColumn, 2 nodes)", "beam")
        self.kind.addItem("Truss (2 nodes)", "truss")
        self.kind.addItem("Shell (ShellMITC4, 4 nodes)", "shell")
        self.kind.currentIndexChanged.connect(self._sync)
        self.body.addWidget(self.kind)

        form = QFormLayout()
        self.nodes = QLineEdit(", ".join(str(t) for t in selected_nodes))
        self.nodes.setPlaceholderText("e.g. 1, 2")
        form.addRow("Node i, j [, k, l]", self.nodes)
        self.mat = QComboBox()
        for m in project.materials.values():
            self.mat.addItem(f"{m.tag}  {m.name}", m.tag)
        self.sec = QComboBox()
        for s in project.sections.values():
            self.sec.addItem(f"{s.tag}  {s.name}", s.tag)
        form.addRow("Material", self.mat)
        form.addRow("Section", self.sec)
        self.body.addLayout(form)

        self.orient_box = QGroupBox("Beam orientation (local z axis)")
        ob = QVBoxLayout(self.orient_box)
        self.auto = QCheckBox("Automatic (global Z, or global X for vertical members)")
        self.auto.setChecked(True)
        ob.addWidget(self.auto)
        row = QHBoxLayout()
        self.vx = spin(0.0, -1, 1, 3, 0.1)
        self.vy = spin(0.0, -1, 1, 3, 0.1)
        self.vz = spin(1.0, -1, 1, 3, 0.1)
        row.addWidget(QLabel("vecxz"))
        row.addWidget(self.vx); row.addWidget(self.vy); row.addWidget(self.vz)
        ob.addLayout(row)
        self.auto.toggled.connect(lambda on: [w.setEnabled(not on) for w in (self.vx, self.vy, self.vz)])
        [w.setEnabled(False) for w in (self.vx, self.vy, self.vz)]
        self.body.addWidget(self.orient_box)

        self.shell_box = QGroupBox("Shell thickness")
        sb = QHBoxLayout(self.shell_box)
        self.thickness = spin(UNITS.length(100.0), UNITS.length(0.001), UNITS.length(1e7),
                              UNITS.length_decimals, UNITS.length(10.0), UNITS.length_unit)
        sb.addWidget(self.thickness)
        self.body.addWidget(self.shell_box)
        self.shell_box.setVisible(False)
        self.orient_box.setVisible(True)

        self.body.addWidget(hint("Tip: select nodes in the viewport first; their tags "
                                 "are filled in automatically."))
        self.kind.currentIndexChanged.connect(self._sync)
        self.buttons("Create")

    def _sync(self) -> None:
        kind = self.kind.currentData()
        self.shell_box.setVisible(kind == "shell")
        self.orient_box.setVisible(kind == "beam")

    def spec(self) -> dict:
        tags = parse_tags(self.nodes.text())
        vec = None if self.auto.isChecked() else [self.vx.value(), self.vy.value(), self.vz.value()]
        return {"kind": self.kind.currentData(), "nodes": tags,
                "mat": self.mat.currentData(), "sec": self.sec.currentData(),
                "vecxz": vec, "thickness": UNITS.length_base(self.thickness.value())}


class SubdivideDialog(BaseDialog):
    def __init__(self, eligible: int, selected: int, parent=None) -> None:
        super().__init__("Subdivide Elements", parent, 440)
        self.eligible = eligible
        self.body.addWidget(title_label("Division"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Number of divisions per element"))
        self.divisions = int_spin(2, 2, 200)
        self.divisions.setMinimumWidth(90)
        row.addWidget(self.divisions)
        row.addStretch(1)
        self.body.addLayout(row)
        self.summary = QLabel()
        self.summary.setStyleSheet(f"color:{theme.ACCENT_DARK}; font-weight:600;")
        self.body.addWidget(self.summary)
        if selected > eligible:
            self.body.addWidget(hint(
                f"{selected - eligible} selected element(s) are not two-node beams or "
                "trusses and will be left unchanged."))
        self.body.addWidget(hint(
            "Each selected element is replaced by equal-length segments. Intermediate "
            "nodes are created or reused, and element loads are carried onto the new "
            "segments."))
        self.divisions.valueChanged.connect(self._update_summary)
        self._update_summary()
        self.buttons("Subdivide")

    def _update_summary(self) -> None:
        n = self.divisions.value()
        self.summary.setText(
            f"{self.eligible} element(s) × {n} divisions = "
            f"{self.eligible * n} element(s)")

    def spec(self) -> int:
        return self.divisions.value()


class SupportDialog(BaseDialog):
    LABELS = ("DX", "DY", "DZ", "RX", "RY", "RZ")

    def __init__(self, project: Project, selected: List[int], parent=None) -> None:
        super().__init__("Assign Supports", parent, 430)
        self.project = project
        self.selected = selected

        self.body.addWidget(title_label("Restrained degrees of freedom"))
        grid = QGridLayout()
        self.boxes: List[QCheckBox] = []
        for i, name in enumerate(self.LABELS):
            cb = QCheckBox(name)
            self.boxes.append(cb)
            grid.addWidget(cb, i // 3, i % 3)
        self.body.addLayout(grid)

        quick = QHBoxLayout()
        for text, code in (("Fixed", [1] * 6), ("Pinned", [1, 1, 1, 0, 0, 0]),
                           ("Roller Z", [1, 1, 0, 0, 0, 0]), ("Clear", [0] * 6)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, c=code: [cb.setChecked(bool(v)) for cb, v in zip(self.boxes, c)])
            quick.addWidget(b)
        self.body.addLayout(quick)

        self.all_nodes = QRadioButton("All nodes")
        self.sel_nodes = QRadioButton(f"Selected nodes ({len(selected)})")
        if selected:
            self.sel_nodes.setChecked(True)
        else:
            self.all_nodes.setChecked(True)
            self.sel_nodes.setEnabled(False)
        self.body.addWidget(self.sel_nodes)
        self.body.addWidget(self.all_nodes)
        self.buttons("Assign")

    def support(self) -> List[bool]:
        return [cb.isChecked() for cb in self.boxes]

    def target(self) -> List[int]:
        return list(self.project.nodes) if self.all_nodes.isChecked() else self.selected


class CopyMoveDialog(BaseDialog):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(title, parent, 430)
        self.body.addWidget(title_label("Operation"))
        row0 = QHBoxLayout()
        self.copy_mode = QRadioButton("Copy")
        self.move_mode = QRadioButton("Move")
        self.copy_mode.setChecked(True)
        row0.addWidget(self.copy_mode)
        row0.addWidget(self.move_mode)
        row0.addStretch(1)
        self.body.addLayout(row0)
        self.body.addWidget(title_label("Translation"))
        grid = QGridLayout()
        self.dx = spin(UNITS.length(1000.0), -1e12, 1e12, UNITS.length_decimals,
                        UNITS.length(100.0), UNITS.length_unit)
        self.dy = spin(0.0, -1e12, 1e12, UNITS.length_decimals,
                         UNITS.length(100.0), UNITS.length_unit)
        self.dz = spin(0.0, -1e12, 1e12, UNITS.length_decimals,
                         UNITS.length(100.0), UNITS.length_unit)
        grid.addWidget(QLabel("ΔX"), 0, 0); grid.addWidget(self.dx, 0, 1)
        grid.addWidget(QLabel("ΔY"), 1, 0); grid.addWidget(self.dy, 1, 1)
        grid.addWidget(QLabel("ΔZ"), 2, 0); grid.addWidget(self.dz, 2, 1)
        self.body.addLayout(grid)

        self.body.addWidget(title_label("Repetition"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Number of copies"))
        self.count = int_spin(1, 1, 200)
        row.addWidget(self.count)
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addWidget(hint("Copy n creates n new sets at 1×, 2× … n× the translation."))

        self.with_elements = QCheckBox("Also duplicate elements connected to the nodes")
        self.with_elements.setChecked(True)
        self.body.addWidget(self.with_elements)
        self.keep_selection = QCheckBox("Select the newly created nodes")
        self.keep_selection.setChecked(True)
        self.body.addWidget(self.keep_selection)
        self.move_mode.toggled.connect(self._sync_mode)
        self.buttons("Apply")

    def _sync_mode(self) -> None:
        move = self.move_mode.isChecked()
        self.count.setEnabled(not move)
        self.keep_selection.setEnabled(not move)

    def is_copy(self) -> bool:
        return self.copy_mode.isChecked()

    def delta(self):
        return (UNITS.length_base(self.dx.value()),
                UNITS.length_base(self.dy.value()),
                UNITS.length_base(self.dz.value()))


class MirrorDialog(BaseDialog):
    previewChanged = Signal(int, float)

    def __init__(self, parent=None) -> None:
        super().__init__("Mirror", parent, 430)
        self.body.addWidget(title_label("Mirror plane"))
        self.plane = QComboBox()
        self.plane.addItems(["XZ plane (mirror Y)", "XY plane (mirror Z)",
                             "YZ plane (mirror X)"])
        self.body.addWidget(self.plane)
        grid = QGridLayout()
        self.coordinate_label = QLabel("Plane X coordinate")
        self.coordinate = spin(UNITS.length(0.0), -1e12, 1e12,
                               UNITS.length_decimals, UNITS.length(100.0),
                               UNITS.length_unit)
        grid.addWidget(self.coordinate_label, 0, 0)
        grid.addWidget(self.coordinate, 0, 1)
        self.body.addLayout(grid)
        self.body.addWidget(hint("The plane is normal to the selected global axis. "
                                 "Its position is previewed in the viewport."))
        self.body.addWidget(title_label("Options"))
        self.copy = QCheckBox("Keep original (copy)")
        self.copy.setChecked(True)
        self.with_elements = QCheckBox("Mirror connected elements")
        self.with_elements.setChecked(True)
        self.body.addWidget(self.copy)
        self.body.addWidget(self.with_elements)
        self.plane.currentIndexChanged.connect(self._sync)
        self.coordinate.valueChanged.connect(self._sync)
        self._sync()
        self.buttons("Apply")

    def _axis(self) -> int:
        return {0: 1, 1: 2, 2: 0}[self.plane.currentIndex()]

    def _sync(self, *_args) -> None:
        axis = self._axis()
        self.coordinate_label.setText(f"Plane {('X', 'Y', 'Z')[axis]} coordinate")
        self.previewChanged.emit(axis, self.offset())

    def offset(self) -> float:
        return UNITS.length_base(self.coordinate.value())

    def refresh_preview(self) -> None:
        self._sync()

    def spec(self):
        return (self._axis(), self.offset(), self.copy.isChecked(),
                self.with_elements.isChecked())


# --------------------------------------------------------------------------- #
# materials / sections
# --------------------------------------------------------------------------- #
class MaterialDialog(BaseDialog):
    def __init__(self, project: Project, parent=None) -> None:
        super().__init__("Material Library", parent, 640)
        self.project = project
        self.materials: Dict[int, Material] = copy.deepcopy(project.materials)
        self.current: Optional[Material] = None

        row = QHBoxLayout()
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumWidth(210)
        self.list.currentRowChanged.connect(self._select)
        left.addWidget(self.list)
        btns = QHBoxLayout()
        add = QPushButton("New")
        add.clicked.connect(self._add)
        rem = QPushButton("Delete")
        rem.clicked.connect(self._remove)
        btns.addWidget(add); btns.addWidget(rem)
        left.addLayout(btns)
        row.addLayout(left, 1)

        right = QVBoxLayout()
        form = QFormLayout()
        self.name = QLineEdit()
        self.kind = QComboBox()
        self.kind.addItems(MATERIAL_KINDS)
        self.E = spin(UNITS.stress(200.0), 0, 1e18, 5, UNITS.stress(10.0),
                      UNITS.stress_unit)
        self.nu = spin(0.3, 0.0, 0.499, 3, 0.01)
        self.rho = spin(UNITS.density(7.85e-9), 0, UNITS.density(1e-3), 12,
                        UNITS.density(1e-9), UNITS.density_unit)
        self.fy = spin(UNITS.stress(0.235), 0, 1e18, 5, UNITS.stress(0.01),
                       UNITS.stress_unit)
        self.b = spin(0.01, 0, 1, 4, 0.005)
        self.fc = spin(UNITS.stress(0.030), -1e18, 1e18, 5, UNITS.stress(0.005),
                       UNITS.stress_unit)
        self.epsc0 = spin(-0.002, -1, 1, 5, 0.0005)
        self.fpcu = spin(UNITS.stress(-0.006), -1e18, 1e18, 5, UNITS.stress(0.001),
                         UNITS.stress_unit)
        self.epsU = spin(-0.02, -1, 1, 5, 0.002)
        form.addRow("Name", self.name)
        form.addRow("Type", self.kind)
        form.addRow("E", self.E)
        form.addRow("ν", self.nu)
        form.addRow("Density ρ", self.rho)
        form.addRow("fy", self.fy)
        form.addRow("Hardening b", self.b)
        form.addRow("fc", self.fc)
        form.addRow("εc0", self.epsc0)
        form.addRow("f'cu", self.fpcu)
        form.addRow("εU", self.epsU)
        right.addLayout(form)
        right.addStretch(1)
        right.addWidget(hint(f"Display units: {UNITS.force_name}, {UNITS.length_name}, "
                             f"tonne. Model values are stored in kN, mm, tonne. "
                             f"Self weight uses g = 9806.65 mm/s²."))
        row.addLayout(right, 2)
        self.body.addLayout(row)

        for w in (self.name,):
            w.textChanged.connect(self._store)
        for w in (self.E, self.nu, self.rho, self.fy, self.b, self.fc, self.epsc0,
                  self.fpcu, self.epsU, self.kind):
            w.valueChanged.connect(self._store) if hasattr(w, "valueChanged") else None
        self.kind.currentIndexChanged.connect(self._store)
        self.kind.currentIndexChanged.connect(self._sync_fields)

        self._reload()
        self.buttons("Save")

    def _reload(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for m in self.materials.values():
            self.list.addItem(QListWidgetItem(f"{m.tag}   {m.name}"))
        self.list.blockSignals(False)
        if self.materials:
            self.list.setCurrentRow(0)

    def _select(self, row: int) -> None:
        keys = list(self.materials)
        if 0 <= row < len(keys):
            self.current = self.materials[keys[row]]
            m = self.current
            for w in (self.name,):
                w.blockSignals(True)
            self.name.setText(m.name)
            self.name.blockSignals(False)
            self.kind.blockSignals(True)
            self.kind.setCurrentText(m.kind)
            self.kind.blockSignals(False)
            for w, v in ((self.E, UNITS.stress(m.E)), (self.nu, m.nu),
                         (self.rho, UNITS.density(m.rho)),
                         (self.fy, UNITS.stress(m.fy)), (self.b, m.b),
                         (self.fc, UNITS.stress(m.fc)),
                         (self.epsc0, m.epsc0), (self.fpcu, UNITS.stress(m.fpcu)),
                         (self.epsU, m.epsU)):
                w.blockSignals(True); w.setValue(v); w.blockSignals(False)
            self._sync_fields()

    def _sync_fields(self) -> None:
        k = self.kind.currentText()
        for w in (self.fy, self.b):
            w.setEnabled(k in ("ElasticPP", "Steel02"))
        for w in (self.fc, self.epsc0, self.fpcu, self.epsU):
            w.setEnabled(k == "Concrete02")

    def _store(self, *args) -> None:
        if not self.current:
            return
        m = self.current
        m.name = self.name.text() or "Material"
        m.kind = self.kind.currentText()
        m.E = UNITS.stress_base(self.E.value())
        m.nu = self.nu.value()
        m.rho = UNITS.density_base(self.rho.value())
        m.fy = UNITS.stress_base(self.fy.value())
        m.b = self.b.value()
        m.fc = UNITS.stress_base(self.fc.value())
        m.epsc0 = self.epsc0.value()
        m.fpcu = UNITS.stress_base(self.fpcu.value())
        m.epsU = self.epsU.value()
        row = self.list.currentRow()
        if row >= 0:
            self.list.item(row).setText(f"{m.tag}   {m.name}")

    def _add(self) -> None:
        tag = max(self.materials, default=0) + 1
        self.materials[tag] = Material(tag, f"Material {tag}")
        self._reload()
        self.list.setCurrentRow(len(self.materials) - 1)

    def _remove(self) -> None:
        row = self.list.currentRow()
        keys = list(self.materials)
        if 0 <= row < len(keys) and len(keys) > 1:
            used = [e.mat for e in self.project.elements.values() if e.mat == keys[row]]
            if used:
                QMessageBox.warning(self, "Material in use",
                                    f"Material {keys[row]} is used by {len(used)} element(s).")
                return
            del self.materials[keys[row]]
            self.current = None
            self._reload()
            self.list.setCurrentRow(min(row, len(self.materials) - 1))


class SectionPreview(QWidget):
    """Small scalable drawing of a section outline."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.section: Optional[Section] = None
        self.setMinimumSize(270, 210)

    def set_section(self, section: Optional[Section]) -> None:
        self.section = section
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QBrush(QColor("#f8fbfe")))
        p.setPen(QPen(QColor(theme.BORDER), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        sec = self.section
        if sec is None:
            p.setPen(QPen(QColor(theme.MUTED)))
            p.drawText(self.rect(), Qt.AlignCenter, "No section")
            p.end()
            return
        outer, inner = sec.outline()
        all_pts = list(outer) + list(inner or [])
        if len(all_pts) < 3:
            p.end()
            return
        ys = [pt[0] for pt in all_pts]
        zs = [pt[1] for pt in all_pts]
        y0, y1, z0, z1 = min(ys), max(ys), min(zs), max(zs)
        w = max(y1 - y0, 1e-6)
        h = max(z1 - z0, 1e-6)
        scale = min((self.width() - 46) / w, (self.height() - 46) / h)
        cy, cz = (y0 + y1) / 2.0, (z0 + z1) / 2.0

        def mapped(points):
            return QPolygonF([QPointF(self.width() / 2.0 + (y - cy) * scale,
                                      self.height() / 2.0 - (z - cz) * scale)
                              for y, z in points])

        origin = QPointF(self.width() / 2.0 - cy * scale,
                         self.height() / 2.0 + cz * scale)
        p.setPen(QPen(QColor(theme.ACCENT), 1.0, Qt.DashLine))
        p.drawLine(QPointF(origin.x(), 12),
                   QPointF(origin.x(), self.height() - 12))
        p.drawLine(QPointF(12, origin.y()),
                   QPointF(self.width() - 12, origin.y()))
        p.setBrush(QBrush(QColor("#dcebf9")))
        p.setPen(QPen(QColor(theme.ACCENT_DARK), 1.6))
        p.drawPolygon(mapped(outer))
        if inner:
            p.setBrush(QBrush(QColor("#f8fbfe")))
            p.drawPolygon(mapped(inner))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(theme.MUTED)))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(QRectF(8, self.height() - 22, self.width() - 16, 18),
                   Qt.AlignCenter, sec.name or sec.designation or sec.shape)
        p.end()


class SectionDialog(BaseDialog):
    def __init__(self, project: Project, parent=None) -> None:
        super().__init__("Section Library", parent, 1040)
        self.project = project
        self.sections: Dict[int, Section] = copy.deepcopy(project.sections)
        self.current: Optional[Section] = None
        self._loading = False
        self._kind = "i"
        self._entries: List[tuple] = []
        self._entry_by_name: Dict[str, tuple] = {}
        if not self.sections:
            s = Section(1, "Section 1", "I-Shape",
                        b=300.0, h=600.0, d=600.0, t=12.0, tw=10.0, tf=15.0)
            s.compute()
            self.sections[1] = s
        self.resize(1180, 760)

        row = QHBoxLayout()
        left = QVBoxLayout()
        title = QLabel("Sections in model")
        title.setStyleSheet(f"font-weight:600; color:{theme.ACCENT_DARK};")
        left.addWidget(title)
        self.list = QListWidget()
        self.list.setMinimumWidth(235)
        self.list.currentRowChanged.connect(self._select)
        left.addWidget(self.list, 1)
        b = QHBoxLayout()
        add = QPushButton("New")
        add.clicked.connect(self._add)
        dup = QPushButton("Duplicate")
        dup.clicked.connect(self._duplicate)
        rem = QPushButton("Delete")
        rem.clicked.connect(self._remove)
        b.addWidget(add); b.addWidget(dup); b.addWidget(rem)
        left.addLayout(b)
        left.addWidget(hint("Standard sections keep the published area and inertias. "
                            "Custom shapes compute properties from their dimensions."))
        row.addLayout(left, 0)

        right = QVBoxLayout()
        form = QFormLayout()
        self.name = QLineEdit()
        form.addRow("Name", self.name)
        right.addLayout(form)

        self.tabs = QTabWidget()
        self._build_standard_tab()
        self._build_custom_tab()
        right.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        self.preview = SectionPreview()
        bottom.addWidget(self.preview, 1)
        pbox = QVBoxLayout()
        self.props = QLabel()
        self.props.setStyleSheet(
            f"background:#f4f8fc; border:1px solid {theme.BORDER}; border-radius:4px;"
            "padding:8px; font-family: Consolas;")
        self.props.setAlignment(Qt.AlignTop)
        pbox.addWidget(self.props, 1)
        pbox.addWidget(hint("A, Iy, Iz and J are used by the solver. "
                            "Mass assumes steel density 7.85 t/m³."))
        bottom.addLayout(pbox, 2)
        right.addLayout(bottom, 0)
        row.addLayout(right, 1)
        self.body.addLayout(row)

        self.name.textChanged.connect(self._name_changed)
        self._fill_families()
        self._populate_standard()
        self._reload()
        self.buttons("Save")

    # ------------------------------------------------------------------ setup
    def _build_standard_tab(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        form = QFormLayout()
        self.db = QComboBox()
        for key, (label, _families) in steelsections.DATABASES.items():
            self.db.addItem(label, key)
        self.family = QComboBox()
        form.addRow("Database", self.db)
        form.addRow("Family", self.family)
        lay.addLayout(form)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search designation, e.g. W12X26 or W310x39")
        lay.addWidget(self.search)
        self.standard_table = QTableWidget(0, 9)
        self.standard_table.setHorizontalHeaderLabels(
            ["Designation", "d / H (mm)", "b / B (mm)", "tw / t (mm)",
             "tf (mm)", "A (mm²)", "Ix (mm⁴)", "Iy (mm⁴)", "J (mm⁴)"])
        self.standard_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.standard_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.standard_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.standard_table.setAlternatingRowColors(True)
        self.standard_table.verticalHeader().setVisible(False)
        self.standard_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.standard_table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((148, 72, 72, 72, 58, 92, 105, 105, 90)):
            self.standard_table.setColumnWidth(column, width)
        self.standard_table.itemSelectionChanged.connect(self._standard_selected)
        lay.addWidget(self.standard_table, 1)
        self.standard_count = QLabel()
        self.standard_count.setStyleSheet(f"color:{theme.MUTED};")
        lay.addWidget(self.standard_count)
        self.db.currentIndexChanged.connect(self._database_changed)
        self.family.currentIndexChanged.connect(self._family_changed)
        self.search.textChanged.connect(self._filter_standard)
        self.tabs.addTab(page, "Standard Database")

    def _build_custom_tab(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        form = QFormLayout()
        self.shape = QComboBox()
        for shape in SECTION_SHAPES:
            self.shape.addItem(SHAPE_LABELS.get(shape, shape), shape)
        form.addRow("Shape", self.shape)
        self._dim_labels: Dict[str, QLabel] = {}
        self._dim_widgets: Dict[str, QDoubleSpinBox] = {}
        defaults = {"b": 300.0, "h": 600.0, "d": 400.0, "t": 12.0,
                    "tw": 10.0, "tf": 15.0}
        for key in ("b", "h", "d", "t", "tw", "tf"):
            label = QLabel("")
            widget = spin(UNITS.length(defaults[key]), UNITS.length(0.001),
                          UNITS.length(1e7), UNITS.length_decimals,
                          UNITS.length(10.0), UNITS.length_unit)
            setattr(self, key, widget)
            self._dim_labels[key] = label
            self._dim_widgets[key] = widget
            form.addRow(label, widget)
        self.A = spin(UNITS.area(1000.0), 0.0, UNITS.area(1e14), 3,
                      UNITS.area(100.0), UNITS.area_unit)
        self.Iy = spin(0.0, 0.0, UNITS.inertia(1e20), 3,
                       UNITS.inertia(1e8), UNITS.inertia_unit)
        self.Iz = spin(0.0, 0.0, UNITS.inertia(1e20), 3,
                       UNITS.inertia(1e8), UNITS.inertia_unit)
        self.J = spin(0.0, 0.0, UNITS.inertia(1e20), 3,
                      UNITS.inertia(1e8), UNITS.inertia_unit)
        for key, text, widget in (("A", "Area A", self.A), ("Iy", "Iy", self.Iy),
                                  ("Iz", "Iz", self.Iz), ("J", "J", self.J)):
            label = QLabel(text)
            form.addRow(label, widget)
            self._dim_labels[key] = label
            self._dim_widgets[key] = widget
        lay.addLayout(form)
        lay.addWidget(hint("Choose a shape and enter its dimensions. Hexagon and octagon "
                           "use the diameter across corners. User-defined properties use "
                           "A, Iy, Iz and J directly."))
        self.shape.currentIndexChanged.connect(self._shape_changed)
        for widget in (self.b, self.h, self.d, self.t, self.tw, self.tf,
                       self.A, self.Iy, self.Iz, self.J):
            widget.valueChanged.connect(self._store)
        self.tabs.addTab(page, "Custom Shape")
        self._sync_custom_fields()

    # --------------------------------------------------------------- database
    def _database_changed(self, *_args) -> None:
        if self._loading:
            return
        self._fill_families()
        self._populate_standard()
        if self.standard_table.rowCount():
            self._loading = True
            self.standard_table.selectRow(0)
            self._loading = False
            self._standard_selected()

    def _fill_families(self, preferred: str = "") -> None:
        key = self.db.currentData() or "AISC"
        _label, families = steelsections.DATABASES[key]
        current = preferred or (self.family.currentData() or "W")
        self.family.blockSignals(True)
        self.family.clear()
        for family in families:
            self.family.addItem(steelsections.FAMILY_LABELS[family], family)
        index = self.family.findData(current)
        self.family.setCurrentIndex(index if index >= 0 else 0)
        self.family.blockSignals(False)

    def _family_changed(self, *_args) -> None:
        if self._loading:
            return
        self._populate_standard()
        if self.standard_table.rowCount():
            self._loading = True
            self.standard_table.selectRow(0)
            self._loading = False
            self._standard_selected()

    def _populate_standard(self) -> None:
        key = self.db.currentData() or "AISC"
        family = self.family.currentData() or "W"
        kind, entries = steelsections.get_sections(key, family)
        self._kind = kind
        self._entries = list(entries)
        self._entry_by_name = {e[0]: e for e in self._entries}
        self.standard_table.setRowCount(0)
        self.standard_table.setRowCount(len(entries))
        for row, item in enumerate(entries):
            if kind == "i":
                name, depth, width, tw, tf, area, ix, iy, j = item
                values = [name, depth, width, tw, tf, area, ix, iy, j]
            elif kind == "rhs":
                name, depth, width, t, area, ix, iy, j = item
                values = [name, depth, width, t, "", area, ix, iy, j]
            else:
                name, diameter, t, area, i, j = item
                values = [name, diameter, "", t, "", area, i, i, j]
            for column, value in enumerate(values):
                if column == 0:
                    cell = QTableWidgetItem(str(value))
                elif value == "":
                    cell = QTableWidgetItem("")
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    cell = QTableWidgetItem(f"{float(value):.6g}")
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.standard_table.setItem(row, column, cell)
        self.standard_count.setText(f"{len(entries)} sections · {key} {family}")
        self._filter_standard(self.search.text())

    def _filter_standard(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self.standard_table.rowCount()):
            item = self.standard_table.item(row, 0)
            self.standard_table.setRowHidden(
                row, bool(needle) and (item is None or needle not in item.text().lower()))

    def _standard_selected(self) -> None:
        if self._loading:
            return
        row = self.standard_table.currentRow()
        item = self.standard_table.item(row, 0) if row >= 0 else None
        if item is not None:
            self._apply_standard(item.text())

    def _apply_standard(self, name: str) -> None:
        entry = self._entry_by_name.get(name)
        if entry is None or self.current is None:
            return
        s = self.current
        key = self.db.currentData() or "AISC"
        family = self.family.currentData() or "W"
        if self._kind == "i":
            _n, depth, width, tw, tf, area, ix, iy, j = entry
            s.shape = "I-Shape"
            s.b, s.h, s.d = width, depth, depth
            s.tw, s.tf, s.t = tw, tf, 0.0
            s.A, s.Iy, s.Iz, s.J = area, ix, iy, j
        elif self._kind == "rhs":
            _n, depth, width, t, area, ix, iy, j = entry
            s.shape = "Box"
            s.b, s.h, s.d = width, depth, depth
            s.t, s.tw, s.tf = t, 0.0, 0.0
            s.A, s.Iy, s.Iz, s.J = area, ix, iy, j
        else:
            _n, diameter, t, area, i, j = entry
            s.shape = "Pipe"
            s.b = s.h = s.d = diameter
            s.t, s.tw, s.tf = t, 0.0, 0.0
            s.A, s.Iy, s.Iz, s.J = area, i, i, j
        s.catalog = key
        s.designation = name
        s.family = family
        s.cy = s.cz = 0.0
        s.name = name
        self._loading = True
        self.name.setText(s.name)
        self.shape.setCurrentIndex(max(0, self.shape.findData(s.shape)))
        self._set_custom_values(s)
        self._loading = False
        self._refresh_item()
        self._update_props()

    # ---------------------------------------------------------------- custom
    def _shape_changed(self, *_args) -> None:
        self._sync_custom_fields()
        if not self._loading:
            self._store()

    def _sync_custom_fields(self) -> None:
        shape = self.shape.currentData() or "I-Shape"
        used = {
            "Rectangle": {"b", "h"},
            "Circle": {"d"},
            "Hexagon": {"d"},
            "Octagon": {"d"},
            "Box": {"b", "h", "t"},
            "Pipe": {"d", "t"},
            "I-Shape": {"b", "h", "tw", "tf"},
            "L-Shape": {"b", "h", "t"},
            "T-Shape": {"b", "h", "tw", "tf"},
            "User": set(),
        }.get(shape, {"b", "h"})
        labels = {
            "Rectangle": {"b": "Width b", "h": "Depth h"},
            "Circle": {"d": "Diameter d"},
            "Hexagon": {"d": "Diameter across corners d"},
            "Octagon": {"d": "Diameter across corners d"},
            "Box": {"b": "Width b", "h": "Depth h", "t": "Wall t"},
            "Pipe": {"d": "Outside diameter d", "t": "Wall t"},
            "I-Shape": {"b": "Flange width b", "h": "Depth h",
                        "tw": "Web tw", "tf": "Flange tf"},
            "L-Shape": {"b": "Leg b", "h": "Leg h", "t": "Thickness t"},
            "T-Shape": {"b": "Flange width b", "h": "Depth h",
                        "tw": "Web tw", "tf": "Flange tf"},
        }.get(shape, {})
        for key in ("b", "h", "d", "t", "tw", "tf"):
            label = self._dim_labels[key]
            widget = self._dim_widgets[key]
            label.setText(labels.get(key, key))
            visible = key in used
            label.setVisible(visible)
            widget.setVisible(visible)
        user = shape == "User"
        for key in ("A", "Iy", "Iz", "J"):
            self._dim_labels[key].setVisible(user)
            self._dim_widgets[key].setVisible(user)

    def _set_custom_values(self, s: Section) -> None:
        for key, widget, value in (
                ("b", self.b, s.b), ("h", self.h, s.h), ("d", self.d, s.d),
                ("t", self.t, s.t), ("tw", self.tw, s.tw), ("tf", self.tf, s.tf)):
            widget.blockSignals(True)
            widget.setValue(UNITS.length(value))
            widget.blockSignals(False)
        for widget, value, conv in ((self.A, s.A, UNITS.area),
                                    (self.Iy, s.Iy, UNITS.inertia),
                                    (self.Iz, s.Iz, UNITS.inertia),
                                    (self.J, s.J, UNITS.inertia)):
            widget.blockSignals(True)
            widget.setValue(conv(value))
            widget.blockSignals(False)

    def _store(self, *_args) -> None:
        if self._loading or self.current is None:
            return
        if self.tabs.currentIndex() != 1:
            return
        s = self.current
        was_standard = s.is_standard
        old_name = s.name
        s.shape = self.shape.currentData() or "I-Shape"
        if was_standard and old_name == s.designation:
            s.name = SHAPE_LABELS.get(s.shape, s.shape)
            self.name.blockSignals(True)
            self.name.setText(s.name)
            self.name.blockSignals(False)
        if s.shape == "User":
            s.A = UNITS.area_base(self.A.value())
            s.Iy = UNITS.inertia_base(self.Iy.value())
            s.Iz = UNITS.inertia_base(self.Iz.value())
            s.J = UNITS.inertia_base(self.J.value())
            s.cy = s.cz = 0.0
        else:
            s.b = UNITS.length_base(self.b.value())
            s.h = UNITS.length_base(self.h.value())
            s.d = UNITS.length_base(self.d.value())
            s.t = UNITS.length_base(self.t.value())
            s.tw = UNITS.length_base(self.tw.value())
            s.tf = UNITS.length_base(self.tf.value())
            s.compute()
        s.catalog = "Custom"
        s.designation = ""
        s.family = ""
        self._refresh_item()
        self._update_props()

    def _name_changed(self, text: str) -> None:
        if self._loading or self.current is None:
            return
        self.current.name = text.strip() or "Section"
        self._refresh_item()
        self._update_props()

    # ----------------------------------------------------------------- common
    def _reload(self) -> None:
        row = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        for s in self.sections.values():
            item = QListWidgetItem(f"{s.tag}   {s.name}")
            item.setToolTip(f"{s.shape} · {s.catalog}"
                            + (f" · {s.designation}" if s.designation else ""))
            self.list.addItem(item)
        self.list.blockSignals(False)
        if not self.sections:
            self.current = None
            self._update_props()
            return
        target = row if 0 <= row < len(self.sections) else 0
        self.list.setCurrentRow(target)
        self._select(target)

    def _select(self, row: int) -> None:
        keys = list(self.sections)
        if not (0 <= row < len(keys)):
            return
        self._loading = True
        self.current = self.sections[keys[row]]
        s = self.current
        self.name.blockSignals(True)
        self.name.setText(s.name)
        self.name.blockSignals(False)
        if s.is_standard:
            database = "CISC" if s.catalog.upper().startswith("CISC") else "AISC"
            index = self.db.findData(database)
            self.db.blockSignals(True)
            self.db.setCurrentIndex(index if index >= 0 else 0)
            self.db.blockSignals(False)
            family = s.family or ("W" if s.shape == "I-Shape"
                                  else "HSS Rect" if s.shape == "Box" else "HSS Rnd")
            self._fill_families(family)
            self._populate_standard()
            self.tabs.setCurrentIndex(0)
            row2 = self._find_designation(s.designation)
            if row2 >= 0:
                self.standard_table.selectRow(row2)
                self.standard_table.scrollToItem(self.standard_table.item(row2, 0))
            idx = self.shape.findData(s.shape)
            self.shape.blockSignals(True)
            self.shape.setCurrentIndex(idx if idx >= 0 else 0)
            self.shape.blockSignals(False)
            self._set_custom_values(s)
            self._sync_custom_fields()
        else:
            self.tabs.setCurrentIndex(1)
            idx = self.shape.findData(s.shape)
            self.shape.blockSignals(True)
            self.shape.setCurrentIndex(idx if idx >= 0 else 0)
            self.shape.blockSignals(False)
            self._set_custom_values(s)
            self._sync_custom_fields()
        self._loading = False
        self._update_props()

    def _find_designation(self, designation: str) -> int:
        for row in range(self.standard_table.rowCount()):
            item = self.standard_table.item(row, 0)
            if item is not None and item.text() == designation:
                return row
        return -1

    def _refresh_item(self) -> None:
        row = self.list.currentRow()
        if self.current and 0 <= row < self.list.count():
            self.list.item(row).setText(f"{self.current.tag}   {self.current.name}")
            self.list.item(row).setToolTip(
                f"{self.current.shape} · {self.current.catalog}"
                + (f" · {self.current.designation}" if self.current.designation else ""))

    def _update_props(self) -> None:
        s = self.current
        if s is None:
            self.props.setText("No section selected")
            self.preview.set_section(None)
            return
        source = (f"{s.catalog} {s.designation}" if s.is_standard
                  else "Custom dimensions")
        self.props.setText(
            f"A  = {fmt(UNITS.area(s.A), 6)} {UNITS.area_unit}\n"
            f"mass = {fmt(s.mass_per_length, 1)} kg/m\n"
            f"Iy = {fmt(UNITS.inertia(s.Iy), 3)} {UNITS.inertia_unit}\n"
            f"Iz = {fmt(UNITS.inertia(s.Iz), 3)} {UNITS.inertia_unit}\n"
            f"J  = {fmt(UNITS.inertia(s.J), 3)} {UNITS.inertia_unit}\n"
            f"Source: {source}")
        self.preview.set_section(s)

    def _add(self) -> None:
        tag = max(self.sections, default=0) + 1
        s = Section(tag, f"Section {tag}", "I-Shape",
                    b=300.0, h=600.0, d=600.0, t=12.0, tw=10.0, tf=15.0)
        s.compute()
        self.sections[tag] = s
        self._reload()
        self.list.setCurrentRow(len(self.sections) - 1)

    def _duplicate(self) -> None:
        if self.current is None:
            return
        tag = max(self.sections, default=0) + 1
        s = copy.deepcopy(self.current)
        s.tag = tag
        s.name = f"{self.current.name} copy"
        self.sections[tag] = s
        self._reload()
        self.list.setCurrentRow(len(self.sections) - 1)

    def _remove(self) -> None:
        row = self.list.currentRow()
        keys = list(self.sections)
        if 0 <= row < len(keys) and len(self.sections) > 1:
            used = [e.tag for e in self.project.elements.values() if e.sec == keys[row]]
            if used:
                QMessageBox.warning(self, "Section in use",
                                    f"Section {keys[row]} is used by {len(used)} element(s).")
                return
            del self.sections[keys[row]]
            self.current = None
            self._reload()
            self.list.setCurrentRow(min(row, len(self.sections) - 1))


# --------------------------------------------------------------------------- #
# load cases / combinations
# --------------------------------------------------------------------------- #
class LoadCaseDialog(BaseDialog):
    def __init__(self, project: Project, parent=None) -> None:
        super().__init__("Load Cases", parent, 560)
        self.cases = copy.deepcopy(project.cases)
        self.original_names: List[str] = list(project.cases)
        self.rename_map: Dict[str, str] = {}

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Case name", "Type", "Description"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.body.addWidget(self.table)

        row = QHBoxLayout()
        add = QPushButton("Add case")
        add.clicked.connect(self._add)
        rem = QPushButton("Delete")
        rem.clicked.connect(self._remove)
        row.addWidget(add); row.addWidget(rem); row.addStretch(1)
        self.body.addLayout(row)
        self.body.addWidget(hint("Load cases group nodal and element loads. "
                                 "Every case becomes a separate OpenSees load pattern."))

        self._reload()
        self.buttons("Save")

    def _reload(self) -> None:
        self.table.setRowCount(len(self.cases))
        for i, c in enumerate(self.cases.values()):
            self.table.setItem(i, 0, QTableWidgetItem(c.name))
            combo = QComboBox()
            combo.addItems(LOADCASE_KINDS)
            combo.setCurrentText(c.kind if c.kind in LOADCASE_KINDS else "Other")
            self.table.setCellWidget(i, 1, combo)
            self.table.setItem(i, 2, QTableWidgetItem(c.note))

    def _add(self) -> None:
        n = 1
        while f"LC{n}" in [c.name for c in self.cases.values()]:
            n += 1
        self.cases[f"LC{n}"] = LoadCase(f"LC{n}", "Other")
        self._reload()

    def _remove(self) -> None:
        row = self.table.currentRow()
        names = list(self.cases)
        if 0 <= row < len(names) and len(names) > 1:
            del self.cases[names[row]]
            self._reload()

    def collect(self) -> Dict[str, LoadCase]:
        out: Dict[str, LoadCase] = {}
        new_names: List[str] = []
        for i in range(self.table.rowCount()):
            name_item = self.table.item(i, 0)
            if not name_item or not name_item.text().strip():
                continue
            name = name_item.text().strip()
            new_names.append(name)
            combo = self.table.cellWidget(i, 1)
            note = self.table.item(i, 2).text() if self.table.item(i, 2) else ""
            out[name] = LoadCase(name, combo.currentText() if combo else "Other", note)
        if len(new_names) == len(self.original_names):
            self.rename_map = {o: n for o, n in zip(self.original_names, new_names) if o != n}
        return out


class ComboDialog(BaseDialog):
    def __init__(self, project: Project, parent=None) -> None:
        super().__init__("Load Combinations", parent, 620)
        self.project = project
        self.combos = copy.deepcopy(project.combos)
        self._keys = list(self.combos)
        self._loading = False

        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMaximumWidth(200)
        self.list.currentRowChanged.connect(self._select)
        row.addWidget(self.list)
        right = QVBoxLayout()
        form = QFormLayout()
        self.name = QLineEdit()
        self.kind = QComboBox()
        self.kind.addItems(COMBINATION_KINDS)
        form.addRow("Name", self.name)
        form.addRow("Type", self.kind)
        right.addLayout(form)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Case", "Factor", "Include"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        right.addWidget(self.table)
        row.addLayout(right, 1)
        self.body.addLayout(row)

        b = QHBoxLayout()
        add = QPushButton("New combination")
        add.clicked.connect(self._add)
        rem = QPushButton("Delete")
        rem.clicked.connect(self._remove)
        b.addWidget(add); b.addWidget(rem); b.addStretch(1)
        self.body.addLayout(b)
        self.body.addWidget(hint("Factors may be negative. Combinations are applied as "
                                 "the sum of the factored cases."))
        self.name.textChanged.connect(self._store)
        self.kind.currentTextChanged.connect(self._store)
        self.table.itemChanged.connect(self._store)
        self._reload()
        self.buttons("Save")

    def _reload(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for c in self.combos.values():
            self.list.addItem(QListWidgetItem(c.name))
        self.list.blockSignals(False)
        self._keys = list(self.combos)
        if self.combos:
            self.list.setCurrentRow(0)

    def _select(self, row: int) -> None:
        if not (0 <= row < len(self._keys)):
            return
        self._loading = True
        c = self.combos[self._keys[row]]
        self.name.setText(c.name)
        self.kind.setCurrentText(c.kind)
        factors = dict(c.factors)
        cases = list(self.project.cases)
        self.table.setRowCount(len(cases))
        for i, case in enumerate(cases):
            self.table.setItem(i, 0, QTableWidgetItem(case))
            self.table.setItem(i, 1, QTableWidgetItem(fmt(factors.get(case, 0.0), 3)))
            self.table.setItem(i, 2, QTableWidgetItem("Yes" if case in factors else ""))
        self._loading = False

    def _store(self) -> None:
        if self._loading:
            return
        row = self.list.currentRow()
        if not (0 <= row < len(self._keys)):
            return
        c = self.combos[self._keys[row]]
        c.name = self.name.text().strip() or c.name
        c.kind = self.kind.currentText()
        factors = []
        for i in range(self.table.rowCount()):
            case = self.table.item(i, 0).text()
            include = (self.table.item(i, 2).text().strip().lower() in ("yes", "y", "1", "true", "✓"))
            try:
                f = float(self.table.item(i, 1).text())
            except (TypeError, ValueError):
                f = 0.0
            if include and abs(f) > 1e-12:
                factors.append((case, f))
        c.factors = factors
        self.list.item(row).setText(c.name)

    def _add(self) -> None:
        n = 1
        while f"COMB{n}" in [c.name for c in self.combos.values()]:
            n += 1
        self.combos[f"COMB{n}"] = LoadCombination(f"COMB{n}", [(list(self.project.cases)[0], 1.0)]
                                                  if self.project.cases else [])
        self._reload()
        self.list.setCurrentRow(len(self.combos) - 1)

    def _remove(self) -> None:
        row = self.list.currentRow()
        keys = list(self.combos)
        if 0 <= row < len(keys):
            del self.combos[keys[row]]
            self._reload()

    def accept(self) -> None:
        self._store()
        super().accept()


# --------------------------------------------------------------------------- #
# loads
# --------------------------------------------------------------------------- #
class NodalLoadDialog(BaseDialog):
    def __init__(self, project: Project, selected: List[int], parent=None) -> None:
        super().__init__("Nodal Loads", parent, 470)
        self.project = project
        self.selected = selected
        self.body.addWidget(title_label("Load case"))
        self.case = QComboBox()
        self.case.addItems(list(project.cases))
        self.body.addWidget(self.case)

        self.body.addWidget(title_label("Forces and moments"))
        grid = QGridLayout()
        self.spins: List[QDoubleSpinBox] = []
        labels = ("FX", "FY", "FZ", "MX", "MY", "MZ")
        units = (UNITS.force_unit, UNITS.force_unit, UNITS.force_unit,
                 UNITS.moment_unit, UNITS.moment_unit, UNITS.moment_unit)
        for i, (lab, unit) in enumerate(zip(labels, units)):
            if i < 3:
                w = spin(0.0, UNITS.force(-1e12), UNITS.force(1e12), 3,
                         UNITS.force(10.0), unit)
            else:
                w = spin(0.0, UNITS.moment(-1e12), UNITS.moment(1e12), 3,
                         UNITS.moment(10.0), unit)
            self.spins.append(w)
            grid.addWidget(QLabel(lab), i // 3, (i % 3) * 2)
            grid.addWidget(w, i // 3, (i % 3) * 2 + 1)
        self.body.addLayout(grid)

        self.body.addWidget(title_label("Apply to"))
        box = QVBoxLayout()
        self.sel = QRadioButton(f"Selected nodes ({len(selected)})")
        self.one = QRadioButton("Node")
        self.node = QLineEdit()
        self.node.setMaximumWidth(120)
        self.all = QRadioButton("All nodes")
        if selected:
            self.sel.setChecked(True)
        else:
            self.all.setChecked(True)
            self.sel.setEnabled(False)
        row = QHBoxLayout()
        row.addWidget(self.one); row.addWidget(self.node); row.addStretch(1)
        box.addWidget(self.sel)
        box.addLayout(row)
        box.addWidget(self.all)
        self.body.addLayout(box)

        self.replace = QCheckBox("Replace existing nodal loads of this case on the target nodes")
        self.replace.setChecked(True)
        self.body.addWidget(self.replace)

        self.one.toggled.connect(lambda on: self.node.setEnabled(on))
        self.node.setEnabled(False)
        self.buttons("Apply")

    def values(self) -> List[float]:
        return ([UNITS.force_base(w.value()) for w in self.spins[:3]] +
                [UNITS.moment_base(w.value()) for w in self.spins[3:]])

    def target(self) -> List[int]:
        if self.sel.isChecked():
            return self.selected
        if self.one.isChecked():
            try:
                return parse_tags(self.node.text())
            except ValueError:
                return []
        return list(self.project.nodes)


class ElementLoadDialog(BaseDialog):
    def __init__(self, project: Project, selected: List[int], parent=None) -> None:
        super().__init__("Element Loads", parent, 500)
        self.project = project
        self.selected = selected
        form = QFormLayout()
        self.case = QComboBox(); self.case.addItems(list(project.cases))
        self.kind = QComboBox()
        self.kind.addItems(["Uniform load", "Trapezoidal load", "Point load"])
        self.direction = QComboBox(); self.direction.addItems(LOAD_DIRECTIONS)
        self.value = spin(UNITS.dist(10.0), UNITS.dist(-1e9), UNITS.dist(1e9), 5,
                          UNITS.dist(1.0), UNITS.dist_unit)
        self.value2 = spin(0.0, UNITS.dist(-1e9), UNITS.dist(1e9), 5,
                           UNITS.dist(1.0), UNITS.dist_unit)
        self.position = spin(0.5, 0.0, 1.0, 3, 0.05)
        form.addRow("Load case", self.case)
        form.addRow("Type", self.kind)
        form.addRow("Direction", self.direction)
        form.addRow("w1 / P", self.value)
        form.addRow("w2", self.value2)
        form.addRow("Point position x/L", self.position)
        self.body.addLayout(form)

        self.body.addWidget(title_label("Apply to"))
        self.sel = QRadioButton(f"Selected elements ({len(selected)})")
        self.one = QRadioButton("Element")
        self.elem = QLineEdit(); self.elem.setMaximumWidth(120)
        self.all = QRadioButton("All elements")
        if selected:
            self.sel.setChecked(True)
        else:
            self.sel.setEnabled(False)
            self.all.setChecked(True)
        row = QHBoxLayout(); row.addWidget(self.one); row.addWidget(self.elem); row.addStretch(1)
        self.body.addWidget(self.sel)
        self.body.addLayout(row)
        self.body.addWidget(self.all)

        self.replace = QCheckBox("Replace existing loads of this case on the target elements")
        self.replace.setChecked(True)
        self.body.addWidget(self.replace)

        self.one.toggled.connect(lambda on: self.elem.setEnabled(on))
        self.elem.setEnabled(False)
        self.kind.currentIndexChanged.connect(self._sync)
        self._sync()
        self.body.addWidget(hint(f"Uniform load units are {UNITS.dist_unit} along the chosen "
                                 f"local/global direction. A 10 kN/m load is "
                                 f"{fmt(UNITS.dist(0.01), 5)} {UNITS.dist_unit}."))
        self.buttons("Apply")

    def _sync(self) -> None:
        i = self.kind.currentIndex()
        unit = UNITS.force_unit if i == 2 else UNITS.dist_unit
        self.value.setSuffix(" " + unit)
        self.value2.setSuffix(" " + unit)
        self.value2.setEnabled(i == 1)
        self.position.setEnabled(i == 2)

    def spec(self) -> dict:
        i = self.kind.currentIndex()
        if i == 2:
            value = UNITS.force_base(self.value.value())
            value2 = UNITS.force_base(self.value2.value())
        else:
            value = UNITS.dist_base(self.value.value())
            value2 = UNITS.dist_base(self.value2.value())
        return {"kind": {0: "uniform", 1: "uniform", 2: "point"}[i],
                "trapezoid": i == 1,
                "direction": self.direction.currentText(),
                "value": value,
                "value2": value2,
                "position": self.position.value()}

    def target(self) -> List[int]:
        if self.sel.isChecked():
            return self.selected
        if self.one.isChecked():
            try:
                return parse_tags(self.elem.text())
            except ValueError:
                return []
        return list(self.project.elements)


class SelfWeightDialog(BaseDialog):
    def __init__(self, project: Project, parent=None) -> None:
        super().__init__("Self Weight", parent, 420)
        self.project = project
        form = QFormLayout()
        self.case = QComboBox(); self.case.addItems(list(project.cases))
        self.factor = spin(1.0, -10, 10, 4, 0.1)
        form.addRow("Load case", self.case)
        form.addRow("Factor", self.factor)
        self.body.addLayout(form)
        self.body.addWidget(hint("Self weight is applied to every element using ρ·A·g from "
                                 "the material density and section area (g = 9806.65 mm/s²)."))
        self.buttons("Apply")


class PushoverDialog(BaseDialog):
    """Setup for a displacement-controlled pushover with lumped hinges."""

    def __init__(self, project: Project, selected_node: Optional[int] = None,
                 parent=None) -> None:
        super().__init__("Pushover Analysis", parent, 520)
        self.project = project
        cfg = project.pushover_settings()
        self.body.addWidget(title_label("Loading"))
        form = QFormLayout()
        self.gravity = QComboBox()
        self.gravity.addItem("(none)", "")
        for name in project.scenario_names():
            self.gravity.addItem(name, name)
        self.lateral = QComboBox()
        for name in project.scenario_names():
            self.lateral.addItem(name, name)
        form.addRow("Gravity case / combo", self.gravity)
        form.addRow("Lateral case / combo", self.lateral)
        self.control_node = int_spin(1, 1, max(project.nodes, default=1))
        self.control_dof = QComboBox()
        self.control_dof.addItem("UX", 1)
        self.control_dof.addItem("UY", 2)
        self.control_dof.addItem("UZ", 3)
        self.target = spin(UNITS.length(100.0), -UNITS.length(1e8),
                           UNITS.length(1e8), UNITS.length_decimals,
                           UNITS.length(5.0), UNITS.length_unit)
        self.steps = int_spin(20, 2, 5000)
        form.addRow("Control node", self.control_node)
        form.addRow("Control DOF", self.control_dof)
        form.addRow("Target displacement", self.target)
        form.addRow("Steps", self.steps)
        self.body.addLayout(form)

        self.body.addWidget(title_label("Lumped plastic hinges"))
        hform = QFormLayout()
        self.hinge_model = QComboBox()
        for label, key in (("Bilinear — Steel01", "Bilinear"),
                           ("Trilinear — Hysteretic", "Trilinear"),
                           ("Takeda-like — Hysteretic", "Takeda"),
                           ("Flag-shaped — FlagShape", "Flag")):
            self.hinge_model.addItem(label, key)
        self.hinge_ratio = spin(float(cfg.get("hinge_length_ratio", 0.10)),
                                0.01, 0.25, 3, 0.01)
        self.fy = spin(UNITS.stress(float(cfg.get("fy", 0.235))),
                       0.0, UNITS.stress(10.0), 5, UNITS.stress(0.01),
                       UNITS.stress_unit)
        self.post = spin(float(cfg.get("post_yield_ratio", 0.02)),
                         0.0, 0.5, 4, 0.005)
        self.ductility = spin(float(cfg.get("ductility", 10.0)),
                              2.0, 100.0, 2, 1.0)
        self.pinching = spin(float(cfg.get("pinching", 0.8)),
                             0.0, 1.0, 3, 0.05)
        self.damage = spin(float(cfg.get("damage", 0.02)),
                           0.0, 1.0, 4, 0.005)
        self.beta = spin(float(cfg.get("beta", 0.4)),
                         0.0, 1.0, 3, 0.05)
        hform.addRow("Hinge model", self.hinge_model)
        hform.addRow("Plastic hinge length / L", self.hinge_ratio)
        hform.addRow("Yield strength fy", self.fy)
        hform.addRow("Post-yield stiffness ratio", self.post)
        hform.addRow("Ultimate / yield strain", self.ductility)
        hform.addRow("Pinching", self.pinching)
        hform.addRow("Damage", self.damage)
        hform.addRow("Takeda beta", self.beta)
        self.body.addLayout(hform)
        self.body.addWidget(hint(
            "Beam elements are rebuilt as beamWithHinges elements for this run. "
            "The hinge sections use a fiber mesh and the selected hysteresis law, "
            "so hinge rotation is an approximation of the local curvature × plastic "
            "hinge length. The base model and its elastic results are not changed."))

        # defaults
        gravity = cfg.get("gravity_case") or ("DL" if "DL" in project.cases else "")
        self.gravity.setCurrentIndex(max(0, self.gravity.findData(gravity)))
        lateral = cfg.get("lateral_case")
        if not lateral:
            for preferred in ("WIND", "EQ", "LAT", "LL"):
                if preferred in project.cases:
                    lateral = preferred
                    break
        if not lateral and project.scenario_names():
            lateral = project.scenario_names()[0]
        if lateral:
            self.lateral.setCurrentIndex(max(0, self.lateral.findData(lateral)))
        node = selected_node or cfg.get("control_node") or 0
        if node not in project.nodes:
            node = max(project.nodes, key=lambda t: project.nodes[t].z,
                       default=1) if project.nodes else 1
        self.control_node.setValue(int(node))
        self.control_dof.setCurrentIndex(max(0, self.control_dof.findData(
            int(cfg.get("control_dof", 1)))))
        if project.nodes:
            zs = [n.z for n in project.nodes.values()]
            height = max(zs) - min(zs)
            target = float(project.settings.get("pushover", {}).get(
                "target_displacement", 0.0) or 0.0)
            if target <= 0:
                target = max(0.02 * height, 10.0)
            self.target.setValue(UNITS.length(target))
        self.steps.setValue(int(cfg.get("steps", 20)))
        self.hinge_ratio.setValue(float(cfg.get("hinge_length_ratio", 0.10)))
        self.hinge_model.setCurrentIndex(max(
            0, self.hinge_model.findData(str(cfg.get("hinge_model", "Trilinear")))))
        self.hinge_model.currentIndexChanged.connect(self._sync)
        self._sync()
        self.buttons("Run Pushover")

    def _sync(self, *_args) -> None:
        model = self.hinge_model.currentData()
        use_hyst = model in ("Trilinear", "Takeda")
        for widget, enabled in (
                (self.pinching, model == "Takeda"),
                (self.damage, model == "Takeda"),
                (self.beta, model in ("Takeda", "Flag")),
                (self.ductility, use_hyst),
                (self.post, True)):
            widget.setEnabled(enabled)

    def spec(self) -> dict:
        return {
            "gravity_case": self.gravity.currentData() or "",
            "lateral_case": self.lateral.currentData() or "",
            "control_node": self.control_node.value(),
            "control_dof": self.control_dof.currentData() or 1,
            "target_displacement": UNITS.length_base(self.target.value()),
            "steps": self.steps.value(),
            "hinge_model": self.hinge_model.currentData() or "Trilinear",
            "hinge_length_ratio": self.hinge_ratio.value(),
            "fy": UNITS.stress_base(self.fy.value()),
            "post_yield_ratio": self.post.value(),
            "ductility": self.ductility.value(),
            "pinching": self.pinching.value(),
            "damage": self.damage.value(),
            "beta": self.beta.value(),
        }


class AnalysisDialog(BaseDialog):
    def __init__(self, project: Project, parent=None) -> None:
        super().__init__("Analysis Settings", parent, 430)
        form = QFormLayout()
        self.steps = spin(float(project.settings.get("static_steps", 1.0)), 1e-6, 1e6, 6, 0.1)
        self.modes = int_spin(int(project.settings.get("modal_modes", 6)), 1, 200)
        self.mass = QCheckBox("Build lumped masses from material densities")
        self.mass.setChecked(bool(project.settings.get("mass_from_density", True)))
        form.addRow("Static load steps", self.steps)
        form.addRow("Number of modes", self.modes)
        form.addRow("", self.mass)
        self.body.addLayout(form)
        self.body.addWidget(hint("Static analysis uses LoadControl with the load step above. "
                                 "Modal analysis needs non-zero mass; the eigen solver switches "
                                 "to LAPACK for small models."))
        self.buttons("Save")

    def values(self) -> dict:
        return {"static_steps": self.steps.value(),
                "modal_modes": self.modes.value(),
                "mass_from_density": self.mass.isChecked()}
