"""Dialogs for spring supports and node constraints (rigid links, equalDOF)."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .dialogs import BaseDialog, hint, int_spin, parse_tags, spin, title_label
from .model import Project, SPRING_DOFS
from .units import UNITS


class SpringDialog(BaseDialog):
    """Create zeroLength point springs on one or more nodes."""

    def __init__(self, project: Project, selected_nodes: List[int], parent=None) -> None:
        super().__init__("Point Spring Support", parent, 600)
        self.project = project
        self.body.addWidget(title_label("Apply to nodes"))
        self.nodes = QLineEdit(", ".join(str(t) for t in selected_nodes))
        self.nodes.setPlaceholderText("e.g. 5, 6, 7")
        self.body.addWidget(self.nodes)
        self.body.addWidget(hint(
            "Each node gets a zeroLength spring connected to a fixed ground point "
            "at the same coordinates. Use translational DOFs for soil springs and "
            "rotational DOFs for moment-rotation springs."))

        form = QFormLayout()
        self.dof = QComboBox()
        for index, label in enumerate(SPRING_DOFS, start=1):
            self.dof.addItem(f"{label}  (global {label[0]})", index)
        self.kind = QComboBox()
        self.kind.addItem("Linear (Elastic)", "linear")
        self.kind.addItem("Nonlinear force-deformation (MultiLinear)", "multilinear")
        self.kind.addItem("P-Y spring (PySimple1)", "py")
        form.addRow("DOF", self.dof)
        form.addRow("Type", self.kind)
        self.body.addLayout(form)

        self.linear_box = QWidget()
        linear_form = QFormLayout(self.linear_box)
        linear_form.setContentsMargins(0, 0, 0, 0)
        self.k = spin(10.0, 1e-9, 1e15, 3, 1.0)
        linear_form.addRow("Stiffness", self.k)
        self.body.addWidget(self.linear_box)

        self.curve_box = QWidget()
        curve_lay = QVBoxLayout(self.curve_box)
        curve_lay.setContentsMargins(0, 0, 0, 0)
        curve_lay.addWidget(QLabel("Positive backbone points (mirrored for reverse loading)"))
        self.curve = QTableWidget(3, 2)
        self.curve.setHorizontalHeaderLabels(["Disp / rotation", "Force / moment"])
        self.curve.verticalHeader().setVisible(False)
        self.curve.setMinimumHeight(130)
        for row, (u, f) in enumerate(((0.0, 0.0), (1.0, 10.0), (4.0, 20.0))):
            self.curve.setItem(row, 0, QTableWidgetItem(str(u)))
            self.curve.setItem(row, 1, QTableWidgetItem(str(f)))
        curve_lay.addWidget(self.curve)
        row = QHBoxLayout()
        add = QPushButton("Add point")
        add.clicked.connect(self._add_row)
        remove = QPushButton("Remove point")
        remove.clicked.connect(self._remove_row)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        curve_lay.addLayout(row)
        self.body.addWidget(self.curve_box)

        self.py_box = QWidget()
        py_form = QFormLayout(self.py_box)
        py_form.setContentsMargins(0, 0, 0, 0)
        self.soil = QComboBox()
        self.soil.addItem("Sand (soil type 1)", 1)
        self.soil.addItem("Clay (soil type 2)", 2)
        self.pult = spin(100.0, 1e-9, 1e15, 3, 10.0)
        self.y50 = spin(10.0, 1e-9, 1e9, 3, 1.0)
        self.cd = spin(0.5, 0.0, 1.0, 3, 0.1)
        py_form.addRow("Soil", self.soil)
        py_form.addRow("Ultimate force pult", self.pult)
        py_form.addRow("Displacement y50", self.y50)
        py_form.addRow("Drag coefficient cd", self.cd)
        self.body.addWidget(self.py_box)
        self.body.addWidget(hint(
            "P-Y springs use OpenSees PySimple1 and apply to UX/UY/UZ only. "
            "For piles, place one spring at each depth node in the lateral direction."))

        self.kind.currentIndexChanged.connect(self._sync)
        self.dof.currentIndexChanged.connect(self._units_changed)
        self._sync()
        self.buttons("Apply")

    def _add_row(self) -> None:
        row = self.curve.rowCount()
        self.curve.insertRow(row)
        self.curve.setItem(row, 0, QTableWidgetItem("0"))
        self.curve.setItem(row, 1, QTableWidgetItem("0"))

    def _remove_row(self) -> None:
        row = self.curve.currentRow()
        if row >= 0 and self.curve.rowCount() > 2:
            self.curve.removeRow(row)

    def _units_changed(self) -> None:
        dof = int(self.dof.currentData() or 1)
        if dof <= 3:
            self.k.setSuffix(f" {UNITS.dist_unit}")
            self.pult.setSuffix(f" {UNITS.force_unit}")
            self.y50.setSuffix(f" {UNITS.length_unit}")
        else:
            self.k.setSuffix(f" {UNITS.moment_unit}/rad")
        self._sync()

    def _sync(self) -> None:
        kind = self.kind.currentData()
        self.linear_box.setVisible(kind == "linear")
        self.curve_box.setVisible(kind == "multilinear")
        self.py_box.setVisible(kind == "py")
        if kind == "py" and int(self.dof.currentData() or 1) > 3:
            self.py_box.setToolTip("PySimple1 requires UX, UY or UZ.")
        self._units_changed_suffixes()

    def _units_changed_suffixes(self) -> None:
        dof = int(self.dof.currentData() or 1)
        if dof <= 3:
            self.k.setSuffix(f" {UNITS.dist_unit}")
            self.pult.setSuffix(f" {UNITS.force_unit}")
            self.y50.setSuffix(f" {UNITS.length_unit}")
        else:
            self.k.setSuffix(f" {UNITS.moment_unit}/rad")

    def targets(self) -> List[int]:
        try:
            return [t for t in parse_tags(self.nodes.text()) if t in self.project.nodes]
        except ValueError:
            return []

    def spec(self) -> dict:
        dof = int(self.dof.currentData() or 1)
        kind = str(self.kind.currentData())
        if dof <= 3:
            k = UNITS.dist_base(self.k.value())
            pult = UNITS.force_base(self.pult.value())
            y50 = UNITS.length_base(self.y50.value())
        else:
            k = UNITS.moment_base(self.k.value())
            pult = UNITS.force_base(self.pult.value())
            y50 = UNITS.length_base(self.y50.value())
        points = []
        for row in range(self.curve.rowCount()):
            u_item = self.curve.item(row, 0)
            f_item = self.curve.item(row, 1)
            if u_item is None or f_item is None:
                continue
            try:
                u = float(u_item.text())
                f = float(f_item.text())
            except ValueError:
                continue
            if dof <= 3:
                points.append([UNITS.length_base(u), UNITS.force_base(f)])
            else:
                points.append([u, UNITS.moment_base(f)])
        return {"dof": dof, "kind": kind, "k": k,
                "curve": points, "pult": pult, "y50": y50,
                "cd": self.cd.value(), "soil_type": int(self.soil.currentData())}


class RigidLinkDialog(BaseDialog):
    """Create rigidLink beam/bar constraints between nodes."""

    def __init__(self, project: Project, selected_nodes: List[int], parent=None) -> None:
        super().__init__("Rigid Link", parent, 520)
        self.project = project
        master = selected_nodes[0] if selected_nodes else 1
        slaves = [t for t in selected_nodes[1:]] or [master + 1]
        form = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItem("Rigid beam (all 6 DOF)", "rigid_beam")
        self.kind.addItem("Rigid bar (translations only)", "rigid_bar")
        self.master = int_spin(master, 1, max(project.nodes, default=1))
        self.slaves = QLineEdit(", ".join(str(t) for t in slaves))
        form.addRow("Type", self.kind)
        form.addRow("Master node", self.master)
        form.addRow("Slave nodes", self.slaves)
        self.body.addLayout(form)
        self.body.addWidget(hint(
            "rigidLink beam constrains all six DOFs and transfers moments; "
            "rigidLink bar constrains translations only. Use a master node that "
            "is part of the supported structure."))
        self.buttons("Apply")

    def spec(self) -> dict:
        try:
            slaves = [t for t in parse_tags(self.slaves.text())
                      if t in self.project.nodes and t != self.master.value()]
        except ValueError:
            slaves = []
        return {"kind": str(self.kind.currentData()),
                "master": self.master.value(), "slaves": slaves,
                "dofs": [], "perp": 3}


class EqualDOFDialog(BaseDialog):
    """Constrain selected DOFs of slave nodes to a master node."""

    def __init__(self, project: Project, selected_nodes: List[int], parent=None) -> None:
        super().__init__("Equal DOF", parent, 520)
        self.project = project
        master = selected_nodes[0] if selected_nodes else 1
        slaves = [t for t in selected_nodes[1:]] or [master + 1]
        form = QFormLayout()
        self.master = int_spin(master, 1, max(project.nodes, default=1))
        self.slaves = QLineEdit(", ".join(str(t) for t in slaves))
        form.addRow("Master node", self.master)
        form.addRow("Slave nodes", self.slaves)
        self.body.addLayout(form)
        self.body.addWidget(QLabel("Constrained DOFs"))
        dof_row = QHBoxLayout()
        self.dofs = []
        for index, label in enumerate(SPRING_DOFS, start=1):
            box = QCheckBox(label)
            box.setChecked(index <= 3)
            dof_row.addWidget(box)
            self.dofs.append(box)
        self.body.addLayout(dof_row)
        self.body.addWidget(hint(
            "equalDOF links the checked DOFs of every slave to the master node; "
            "other DOFs remain independent."))
        self.buttons("Apply")

    def spec(self) -> dict:
        try:
            slaves = [t for t in parse_tags(self.slaves.text())
                      if t in self.project.nodes and t != self.master.value()]
        except ValueError:
            slaves = []
        dofs = [i for i, box in enumerate(self.dofs, start=1) if box.isChecked()]
        return {"kind": "equal_dof", "master": self.master.value(),
                "slaves": slaves, "dofs": dofs, "perp": 3}


class DiaphragmDialog(BaseDialog):
    """Rigid diaphragm constraint about a global axis."""

    def __init__(self, project: Project, selected_nodes: List[int], parent=None) -> None:
        super().__init__("Rigid Diaphragm", parent, 520)
        self.project = project
        master = selected_nodes[0] if selected_nodes else 1
        slaves = [t for t in selected_nodes[1:]] or [master + 1]
        form = QFormLayout()
        self.master = int_spin(master, 1, max(project.nodes, default=1))
        self.slaves = QLineEdit(", ".join(str(t) for t in slaves))
        self.axis = QComboBox()
        self.axis.addItem("Plane normal X", 1)
        self.axis.addItem("Plane normal Y", 2)
        self.axis.addItem("Plane normal Z (horizontal)", 3)
        form.addRow("Master node", self.master)
        form.addRow("Slave nodes", self.slaves)
        form.addRow("Diaphragm axis", self.axis)
        self.body.addLayout(form)
        self.body.addWidget(hint(
            "rigidDiaphragm makes the nodes move as a rigid plane. The axis is "
            "the global direction normal to that plane; use Z for a floor."))
        self.buttons("Apply")

    def spec(self) -> dict:
        try:
            slaves = [t for t in parse_tags(self.slaves.text())
                      if t in self.project.nodes and t != self.master.value()]
        except ValueError:
            slaves = []
        return {"kind": "rigid_diaphragm", "master": self.master.value(),
                "slaves": slaves, "dofs": [], "perp": int(self.axis.currentData())}
