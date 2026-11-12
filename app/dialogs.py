"""Dialog boxes for model generation, loads and analysis settings."""

from __future__ import annotations

import copy
import math
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QRadioButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from . import theme
from .model import (COMBINATION_KINDS, ELEMENT_KINDS, LOADCASE_KINDS,
                    LOAD_DIRECTIONS, MATERIAL_KINDS, SECTION_SHAPES, Element,
                    LoadCase, LoadCombination, Material, Project, Section,
                    fmt)
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
    def __init__(self, parent=None) -> None:
        super().__init__("Mirror", parent, 400)
        self.body.addWidget(title_label("Mirror plane"))
        self.plane = QComboBox()
        self.plane.addItems(["XZ plane (mirror Y)", "XY plane (mirror Z)", "YZ plane (mirror X)"])
        self.body.addWidget(self.plane)
        self.body.addWidget(title_label("Options"))
        self.copy = QCheckBox("Keep original (copy)")
        self.copy.setChecked(True)
        self.with_elements = QCheckBox("Mirror connected elements")
        self.with_elements.setChecked(True)
        self.body.addWidget(self.copy)
        self.body.addWidget(self.with_elements)
        self.body.addWidget(hint("The mirror plane passes through the global origin."))
        self.buttons("Apply")

    def spec(self):
        idx = self.plane.currentIndex()
        return {0: 1, 1: 2, 2: 0}[idx], self.copy.isChecked(), self.with_elements.isChecked()


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


class SectionDialog(BaseDialog):
    def __init__(self, project: Project, parent=None) -> None:
        super().__init__("Section Library", parent, 660)
        self.sections: Dict[int, Section] = copy.deepcopy(project.sections)
        self.current: Optional[Section] = None

        row = QHBoxLayout()
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumWidth(220)
        self.list.currentRowChanged.connect(self._select)
        left.addWidget(self.list)
        b = QHBoxLayout()
        add = QPushButton("New")
        add.clicked.connect(self._add)
        rem = QPushButton("Delete")
        rem.clicked.connect(self._remove)
        b.addWidget(add); b.addWidget(rem)
        left.addLayout(b)
        row.addLayout(left, 1)

        right = QVBoxLayout()
        form = QFormLayout()
        self.name = QLineEdit()
        self.shape = QComboBox()
        self.shape.addItems(SECTION_SHAPES)
        self.b = spin(UNITS.length(300.0), UNITS.length(0.001), UNITS.length(1e7),
                      UNITS.length_decimals, UNITS.length(10.0), UNITS.length_unit)
        self.h = spin(UNITS.length(600.0), UNITS.length(0.001), UNITS.length(1e7),
                      UNITS.length_decimals, UNITS.length(10.0), UNITS.length_unit)
        self.d = spin(UNITS.length(400.0), UNITS.length(0.001), UNITS.length(1e7),
                      UNITS.length_decimals, UNITS.length(10.0), UNITS.length_unit)
        self.t = spin(UNITS.length(12.0), UNITS.length(0.001), UNITS.length(1e6),
                      UNITS.length_decimals, UNITS.length(1.0), UNITS.length_unit)
        self.tw = spin(UNITS.length(10.0), UNITS.length(0.001), UNITS.length(1e6),
                       UNITS.length_decimals, UNITS.length(1.0), UNITS.length_unit)
        self.tf = spin(UNITS.length(15.0), UNITS.length(0.001), UNITS.length(1e6),
                       UNITS.length_decimals, UNITS.length(1.0), UNITS.length_unit)
        form.addRow("Name", self.name)
        form.addRow("Shape", self.shape)
        form.addRow("Width b", self.b)
        form.addRow("Depth h", self.h)
        form.addRow("Diameter d", self.d)
        form.addRow("Wall t", self.t)
        form.addRow("Web tw", self.tw)
        form.addRow("Flange tf", self.tf)
        right.addLayout(form)

        self.props = QLabel()
        self.props.setStyleSheet(
            f"background:#f4f8fc; border:1px solid {theme.BORDER}; border-radius:4px;"
            "padding:8px; font-family: Consolas;")
        right.addWidget(self.props)
        right.addWidget(hint("Section properties are computed automatically for standard "
                             "shapes; choose 'User' to enter A, Iy, Iz, J directly."))
        row.addLayout(right, 2)
        self.body.addLayout(row)

        self.name.textChanged.connect(self._store)
        for w in (self.b, self.h, self.d, self.t, self.tw, self.tf):
            w.valueChanged.connect(self._store)
        self.shape.currentIndexChanged.connect(self._store)
        self.shape.currentIndexChanged.connect(self._sync)

        self._reload()
        self.buttons("Save")

    def _reload(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for s in self.sections.values():
            self.list.addItem(QListWidgetItem(f"{s.tag}   {s.name}"))
        self.list.blockSignals(False)
        if self.sections:
            self.list.setCurrentRow(0)

    def _select(self, row: int) -> None:
        keys = list(self.sections)
        if 0 <= row < len(keys):
            self.current = self.sections[keys[row]]
            s = self.current
            self.name.blockSignals(True)
            self.name.setText(s.name)
            self.name.blockSignals(False)
            self.shape.blockSignals(True)
            self.shape.setCurrentText(s.shape)
            self.shape.blockSignals(False)
            for w, v in ((self.b, UNITS.length(s.b)), (self.h, UNITS.length(s.h)),
                         (self.d, UNITS.length(s.d)), (self.t, UNITS.length(s.t)),
                         (self.tw, UNITS.length(s.tw)), (self.tf, UNITS.length(s.tf))):
                w.blockSignals(True); w.setValue(v); w.blockSignals(False)
            self._sync()

    def _sync(self) -> None:
        shp = self.shape.currentText()
        for w, on in ((self.b, shp in ("Rectangle", "Box", "I-Shape")),
                      (self.h, shp in ("Rectangle", "Box", "I-Shape")),
                      (self.d, shp in ("Circle", "Pipe")),
                      (self.t, shp in ("Pipe", "Box")),
                      (self.tw, shp == "I-Shape"),
                      (self.tf, shp == "I-Shape")):
            w.setEnabled(on)
        self._store()

    def _store(self, *args) -> None:
        if not self.current:
            return
        s = self.current
        s.name = self.name.text() or "Section"
        s.shape = self.shape.currentText()
        s.b = UNITS.length_base(self.b.value())
        s.h = UNITS.length_base(self.h.value())
        s.d = UNITS.length_base(self.d.value())
        s.t = UNITS.length_base(self.t.value())
        s.tw = UNITS.length_base(self.tw.value())
        s.tf = UNITS.length_base(self.tf.value())
        s.compute()
        self.props.setText(
            f"A  = {fmt(UNITS.area(s.A), 1)} {UNITS.area_unit}\n"
            f"Iy = {fmt(UNITS.inertia(s.Iy), 1)} {UNITS.inertia_unit}\n"
            f"Iz = {fmt(UNITS.inertia(s.Iz), 1)} {UNITS.inertia_unit}\n"
            f"J  = {fmt(UNITS.inertia(s.J), 1)} {UNITS.inertia_unit}")
        row = self.list.currentRow()
        if row >= 0:
            self.list.item(row).setText(f"{s.tag}   {s.name}")

    def _add(self) -> None:
        tag = max(self.sections, default=0) + 1
        self.sections[tag] = Section(tag, f"Section {tag}")
        self.sections[tag].compute()
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
