"""Per-element lumped plastic-hinge assignment table."""

from __future__ import annotations

import copy
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QTableWidgetSelectionRange, QVBoxLayout)

from . import theme
from .hysteresis import HysteresisDialog, MODEL_LABELS
from .model import HingeAssignment, Project
from .units import UNITS

MODELS = (("None", ""),) + tuple((label, key) for key, label in MODEL_LABELS.items())


class HingeTableDialog(QDialog):
    """Editable table for assigning hinge properties to beam elements."""

    COLUMNS = ["Element", "Section", "Hinge model", "Lp / L", "fy",
               "b", "μu", "Pinch", "Damage", "β"]

    def __init__(self, project: Project, parent=None,
                 selected: Optional[list[int]] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hinge Assignments")
        self.resize(1180, 720)
        self.project = project
        self.hinges: Dict[int, HingeAssignment] = copy.deepcopy(project.hinges)
        self.defaults = project.pushover_settings()
        self.beams = sorted(tag for tag, e in project.elements.items()
                            if e.kind == "beam" and len(e.nodes) >= 2)
        self._selected = set(selected or [])

        lay = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Lumped plastic hinges")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {theme.ACCENT_DARK};")
        header.addWidget(title)
        header.addStretch(1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{theme.MUTED};")
        header.addWidget(self.count)
        lay.addLayout(header)
        lay.addWidget(QLabel(
            "Assign a hinge model to each beam element. The hinge acts at both "
            "element ends; unassigned elements remain elastic during pushover. "
            "Different steel and concrete members can use different models."))

        tools = QHBoxLayout()
        tools.addWidget(QLabel("Set selected rows to"))
        self.bulk_model = QComboBox()
        for label, key in MODELS:
            self.bulk_model.addItem(label, key)
        tools.addWidget(self.bulk_model)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_bulk)
        tools.addWidget(apply_btn)
        clear_btn = QPushButton("Clear selected")
        clear_btn.clicked.connect(self._clear_selected)
        tools.addWidget(clear_btn)
        select_btn = QPushButton("Select all")
        select_btn.clicked.connect(self.table_select_all)
        tools.addWidget(select_btn)
        tools.addStretch(1)
        diagram_btn = QPushButton("Hysteresis diagram…")
        diagram_btn.clicked.connect(self._show_diagram)
        tools.addWidget(diagram_btn)
        lay.addLayout(tools)

        self.table = QTableWidget(len(self.beams), len(self.COLUMNS))
        headers = list(self.COLUMNS)
        headers[4] = f"fy ({UNITS.stress_unit})"
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked |
                                   QAbstractItemView.EditKeyPressed |
                                   QAbstractItemView.SelectedClicked)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        widths = (70, 190, 190, 78, 110, 80, 70, 78, 84, 70)
        for i, width in enumerate(widths):
            self.table.setColumnWidth(i, width)
        lay.addWidget(self.table, 1)

        for row, tag in enumerate(self.beams):
            self._populate_row(row, tag)
            if tag in self._selected:
                self.table.setRangeSelected(
                    QTableWidgetSelectionRange(row, 0, row, len(self.COLUMNS) - 1),
                    True)

        bar = QHBoxLayout()
        bar.addStretch(1)
        cancel = QPushButton("Close")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        bar.addWidget(cancel)
        bar.addWidget(save)
        lay.addLayout(bar)
        self._update_count()

    # ------------------------------------------------------------------ rows
    def _defaults_for(self, tag: int) -> dict:
        e = self.project.elements[tag]
        mat = self.project.material_of(e)
        values = dict(self.defaults)
        values["fy"] = mat.fy if mat.fy > 0 else values.get("fy", 0.235)
        values["model"] = values.get("hinge_model", "Trilinear")
        values["length_ratio"] = values.get("hinge_length_ratio", 0.10)
        return values

    def _populate_row(self, row: int, tag: int) -> None:
        e = self.project.elements[tag]
        sec = self.project.section_of(e)
        assignment = self.hinges.get(tag)
        values = self._defaults_for(tag)
        if assignment:
            values.update(assignment.to_dict())
            model = assignment.model
        else:
            model = ""
        item = QTableWidgetItem(str(tag))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 0, item)
        sec_item = QTableWidgetItem(f"{sec.tag}  {sec.name}")
        sec_item.setFlags(sec_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 1, sec_item)

        combo = QComboBox()
        for label, key in MODELS:
            combo.addItem(label, key)
        combo.setCurrentIndex(max(0, combo.findData(model)))
        combo.currentIndexChanged.connect(
            lambda _idx, r=row: self._row_changed(r))
        combo.currentIndexChanged.connect(lambda _idx: self._update_count())
        self.table.setCellWidget(row, 2, combo)
        numeric = (
            ("length_ratio", UNITS.length(0.0), 0.10, 3, False),
            ("fy", UNITS.stress(0.0), 0.235, 5, True),
            ("post_yield_ratio", 0.0, 0.02, 4, False),
            ("ductility", 0.0, 10.0, 2, False),
            ("pinching", 0.0, 0.8, 3, False),
            ("damage", 0.0, 0.02, 4, False),
            ("beta", 0.0, 0.4, 3, False),
        )
        for col, (key, _zero, fallback, decimals, stress) in enumerate(numeric, start=3):
            value = float(values.get(key, fallback) or fallback)
            shown = UNITS.stress(value) if stress else value
            cell = QTableWidgetItem(f"{shown:.{decimals}f}")
            cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if not model:
                cell.setForeground(Qt.gray)
            self.table.setItem(row, col, cell)
        self._row_changed(row)

    def _row_changed(self, row: int) -> None:
        combo = self.table.cellWidget(row, 2)
        enabled = bool(combo.currentData()) if combo else False
        color = QBrush(QColor("#1f3a5f" if enabled else theme.MUTED))
        for col in range(3, len(self.COLUMNS)):
            item = self.table.item(row, col)
            if item is not None:
                item.setFlags((item.flags() | Qt.ItemIsEditable) if enabled
                              else (item.flags() & ~Qt.ItemIsEditable))
                item.setForeground(color)

    def _read_row(self, row: int) -> Optional[HingeAssignment]:
        tag = self.beams[row]
        combo = self.table.cellWidget(row, 2)
        model = combo.currentData() if combo else ""
        if not model:
            return None
        try:
            length_ratio = float(self.table.item(row, 3).text())
            fy = UNITS.stress_base(float(self.table.item(row, 4).text()))
            post = float(self.table.item(row, 5).text())
            duct = float(self.table.item(row, 6).text())
            pinch = float(self.table.item(row, 7).text())
            damage = float(self.table.item(row, 8).text())
            beta = float(self.table.item(row, 9).text())
        except (TypeError, ValueError, AttributeError):
            raise ValueError(f"Invalid hinge value on element {tag}.")
        return HingeAssignment(
            tag, model, max(0.01, min(0.25, length_ratio)), max(fy, 1e-6),
            max(post, 0.0), max(duct, 2.0), min(max(pinch, 0.0), 1.0),
            max(damage, 0.0), min(max(beta, 0.0), 1.0))

    def _collect(self) -> Dict[int, HingeAssignment]:
        out = {}
        for row in range(len(self.beams)):
            assignment = self._read_row(row)
            if assignment is not None:
                out[assignment.element] = assignment
        return out

    # --------------------------------------------------------------- actions
    def _selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self.table.selectedIndexes()})

    def _apply_bulk(self) -> None:
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "Hinge table",
                                    "Select one or more rows first.")
            return
        model = self.bulk_model.currentData() or ""
        for row in rows:
            combo = self.table.cellWidget(row, 2)
            combo.setCurrentIndex(max(0, combo.findData(model)))
        self._update_count()

    def _clear_selected(self) -> None:
        for row in self._selected_rows():
            combo = self.table.cellWidget(row, 2)
            combo.setCurrentIndex(max(0, combo.findData("")))
        self._update_count()

    def table_select_all(self) -> None:
        self.table.selectAll()

    def _show_diagram(self) -> None:
        rows = self._selected_rows()
        row = rows[0] if rows else (self.table.currentRow() if self.table.currentRow() >= 0 else 0)
        try:
            assignment = self._read_row(row) if self.beams else None
        except ValueError as exc:
            QMessageBox.warning(self, "Hinge table", str(exc))
            return
        if assignment is None:
            values = self._defaults_for(self.beams[row]) if self.beams else {}
            model = "Trilinear"
            E = self.project.material_of(self.project.elements[self.beams[row]]).E \
                if self.beams else 200.0
        else:
            values = assignment.to_dict()
            model = assignment.model
            E = self.project.material_of(
                self.project.elements[assignment.element]).E
        HysteresisDialog(model, values, self, initial_stiffness=E).exec()

    def _update_count(self) -> None:
        n = sum(1 for row in range(len(self.beams))
                if self.table.cellWidget(row, 2).currentData())
        self.count.setText(f"{n} of {len(self.beams)} beam elements have hinges")

    def accept(self) -> None:
        try:
            self.hinges = self._collect()
        except ValueError as exc:
            QMessageBox.warning(self, "Hinge table", str(exc))
            return
        super().accept()
