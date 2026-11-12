"""Hinge definition library and element assignment dialogs."""

from __future__ import annotations

import copy
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QTableWidgetSelectionRange, QTabWidget,
                               QVBoxLayout, QWidget)

from . import theme
from .hysteresis import HysteresisDialog, MODEL_LABELS
from .model import HingeDefinition, Project
from .units import UNITS

MODELS = ("Bilinear", "Trilinear", "Takeda", "Flag")


class HingeLibraryDialog(QDialog):
    """Create and edit reusable hinge definitions, grouped by model type."""

    def __init__(self, project: Project, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hinge Library")
        self.resize(980, 620)
        self.project = project
        self.defs: Dict[int, HingeDefinition] = copy.deepcopy(project.hinge_defs)
        self.defaults = project.pushover_settings()
        self.tables: Dict[str, QTableWidget] = {}
        self.row_defs: Dict[str, List[int]] = {}

        lay = QVBoxLayout(self)
        title = QLabel("Hinge definitions")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {theme.ACCENT_DARK};")
        lay.addWidget(title)
        lay.addWidget(QLabel(
            "Create reusable hinge definitions. Each hinge type has its own tab "
            "and its own parameter list; a definition can then be assigned to one "
            "or more beam elements. An empty tab means no hinge of that type exists."))

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        for model in MODELS:
            self._build_tab(model)

        tools = QHBoxLayout()
        new_btn = QPushButton("New hinge")
        new_btn.clicked.connect(self._new)
        dup_btn = QPushButton("Duplicate")
        dup_btn.clicked.connect(self._duplicate)
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._delete)
        tools.addWidget(new_btn)
        tools.addWidget(dup_btn)
        tools.addWidget(del_btn)
        tools.addStretch(1)
        diagram_btn = QPushButton("Hysteresis diagram…")
        diagram_btn.clicked.connect(self._diagram)
        tools.addWidget(diagram_btn)
        lay.addLayout(tools)

        bar = QHBoxLayout()
        bar.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        bar.addWidget(close)
        bar.addWidget(save)
        lay.addLayout(bar)

        self._reload()

    # ------------------------------------------------------------------ build
    def _columns(self, model: str) -> List[str]:
        columns = ["Name", "Lp / L", f"fy ({UNITS.stress_unit})", "b"]
        if model in ("Trilinear", "Takeda"):
            columns.append("μu")
        if model == "Takeda":
            columns += ["Pinch", "Damage", "β"]
        elif model == "Flag":
            columns += ["β"]
        return columns

    def _build_tab(self, model: str) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 6, 6, 6)
        table = QTableWidget(0, len(self._columns(model)))
        table.setHorizontalHeaderLabels(self._columns(model))
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.DoubleClicked |
                                      QAbstractItemView.EditKeyPressed)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.setColumnWidth(0, 200)
        table.setColumnWidth(1, 78)
        table.setColumnWidth(2, 120)
        table.setColumnWidth(3, 70)
        self.tables[model] = table
        lay.addWidget(table, 1)
        self.tabs.addTab(page, MODEL_LABELS[model])

    def _current_model(self) -> str:
        index = self.tabs.currentIndex()
        return MODELS[index] if 0 <= index < len(MODELS) else MODELS[0]

    # ------------------------------------------------------------------ data
    def _reload(self) -> None:
        for model, table in self.tables.items():
            defs = [h for h in sorted(self.defs.values(), key=lambda d: d.tag)
                    if h.model == model]
            self.row_defs[model] = [h.tag for h in defs]
            table.setRowCount(len(defs))
            for row, h in enumerate(defs):
                values = [h.name, f"{h.length_ratio:.3f}",
                          f"{UNITS.stress(h.fy):.5f}",
                          f"{h.post_yield_ratio:.4f}"]
                if model in ("Trilinear", "Takeda"):
                    values.append(f"{h.ductility:.2f}")
                if model == "Takeda":
                    values += [f"{h.pinching:.3f}", f"{h.damage:.4f}",
                               f"{h.beta:.3f}"]
                elif model == "Flag":
                    values.append(f"{h.beta:.3f}")
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if col:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(row, col, item)
            table.resizeColumnsToContents()
            table.setColumnWidth(0, max(160, table.columnWidth(0)))

    def _selected_def(self) -> Optional[HingeDefinition]:
        model = self._current_model()
        rows = {i.row() for i in self.tables[model].selectedIndexes()}
        if not rows:
            return None
        row = min(rows)
        tags = self.row_defs.get(model, [])
        if 0 <= row < len(tags):
            return self.defs.get(tags[row])
        return None

    def _new(self) -> None:
        model = self._current_model()
        tag = max(self.defs, default=0) + 1
        defaults = self.defaults
        h = HingeDefinition(
            tag, f"{MODEL_LABELS[model].split(' — ')[0]} {tag}",
            model, float(defaults.get("hinge_length_ratio", 0.10)),
            float(defaults.get("fy", 0.235)),
            float(defaults.get("post_yield_ratio", 0.02)),
            float(defaults.get("ductility", 10.0)),
            float(defaults.get("pinching", 0.8)),
            float(defaults.get("damage", 0.02)),
            float(defaults.get("beta", 0.4)))
        self.defs[tag] = h
        self._reload()
        table = self.tables[model]
        row = self.row_defs[model].index(tag)
        table.selectRow(row)

    def _duplicate(self) -> None:
        source = self._selected_def()
        if source is None:
            QMessageBox.information(self, "Hinge library",
                                    "Select a hinge definition first.")
            return
        tag = max(self.defs, default=0) + 1
        h = copy.deepcopy(source)
        h.tag = tag
        h.name = f"{source.name} copy"
        self.defs[tag] = h
        self._reload()
        table = self.tables[h.model]
        table.selectRow(self.row_defs[h.model].index(tag))

    def _delete(self) -> None:
        source = self._selected_def()
        if source is None:
            return
        used = sum(1 for hinge in self.project.hinge_assignments.values()
                   if hinge == source.tag)
        if used and QMessageBox.question(
                self, "Delete hinge",
                f"{source.name} is assigned to {used} element(s). Delete it and "
                "clear those assignments?") != QMessageBox.Yes:
            return
        self.defs.pop(source.tag, None)
        self._reload()

    def _diagram(self) -> None:
        h = self._selected_def()
        if h is None:
            QMessageBox.information(self, "Hinge library",
                                    "Select a hinge definition first.")
            return
        element = next((tag for tag, hinge in self.project.hinge_assignments.items()
                        if hinge == h.tag), None)
        E = (self.project.material_of(self.project.elements[element]).E
             if element is not None else 200.0)
        HysteresisDialog(h.model, h.to_dict(), self, initial_stiffness=E).exec()

    def _read_table(self, model: str) -> None:
        table = self.tables[model]
        tags = self.row_defs.get(model, [])
        for row, tag in enumerate(tags):
            h = self.defs.get(tag)
            if h is None:
                continue
            try:
                h.name = table.item(row, 0).text().strip() or f"Hinge {tag}"
                h.length_ratio = max(0.01, min(0.25, float(
                    table.item(row, 1).text())))
                h.fy = max(UNITS.stress_base(float(table.item(row, 2).text())),
                           1e-6)
                h.post_yield_ratio = max(float(table.item(row, 3).text()), 0.0)
            except (TypeError, ValueError, AttributeError):
                raise ValueError(f"Invalid value in {model} hinge '{h.name}'.")
            col = 4
            if model in ("Trilinear", "Takeda"):
                h.ductility = max(float(table.item(row, col).text()), 2.0)
                col += 1
            if model == "Takeda":
                h.pinching = min(max(float(table.item(row, col).text()), 0.0), 1.0)
                h.damage = max(float(table.item(row, col + 1).text()), 0.0)
                h.beta = min(max(float(table.item(row, col + 2).text()), 0.0), 1.0)
            elif model == "Flag":
                h.beta = min(max(float(table.item(row, col).text()), 0.0), 1.0)

    def accept(self) -> None:
        try:
            for model in MODELS:
                self._read_table(model)
        except ValueError as exc:
            QMessageBox.warning(self, "Hinge library", str(exc))
            return
        super().accept()


class AssignHingesDialog(QDialog):
    """Assign created hinge definitions to beam elements."""

    def __init__(self, project: Project, parent=None,
                 selected: Optional[List[int]] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Hinges")
        self.resize(820, 680)
        self.project = project
        self.defs = project.hinge_defs
        self.assignments: Dict[int, int] = copy.deepcopy(project.hinge_assignments)
        self.beams = sorted(tag for tag, e in project.elements.items()
                            if e.kind == "beam" and len(e.nodes) >= 2)
        self._selected = set(selected or [])

        lay = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Assign hinges to elements")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {theme.ACCENT_DARK};")
        header.addWidget(title)
        header.addStretch(1)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{theme.MUTED};")
        header.addWidget(self.count)
        lay.addLayout(header)
        if not self.defs:
            lay.addWidget(QLabel(
                "No hinge definitions exist. Create hinges first in the Hinge "
                "Library, then return here to assign them."))

        tools = QHBoxLayout()
        tools.addWidget(QLabel("Set selected rows to"))
        self.bulk = QComboBox()
        self.bulk.addItem("None", 0)
        for h in sorted(self.defs.values(), key=lambda d: d.tag):
            self.bulk.addItem(f"H{h.tag}  {h.name}  ({MODEL_LABELS[h.model]})",
                              h.tag)
        tools.addWidget(self.bulk)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_bulk)
        tools.addWidget(apply_btn)
        clear_btn = QPushButton("Clear selected")
        clear_btn.clicked.connect(self._clear_selected)
        tools.addWidget(clear_btn)
        select_btn = QPushButton("Select all")
        select_btn.clicked.connect(lambda: self.table.selectAll())
        tools.addWidget(select_btn)
        tools.addStretch(1)
        lay.addLayout(tools)

        self.table = QTableWidget(len(self.beams), 3)
        self.table.setHorizontalHeaderLabels(["Element", "Section", "Assigned hinge"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 90)
        self.table.setColumnWidth(1, 240)
        lay.addWidget(self.table, 1)

        for row, tag in enumerate(self.beams):
            e = project.elements[tag]
            sec = project.section_of(e)
            self.table.setItem(row, 0, QTableWidgetItem(str(tag)))
            self.table.setItem(row, 1, QTableWidgetItem(f"{sec.tag}  {sec.name}"))
            combo = QComboBox()
            combo.addItem("None", 0)
            for h in sorted(self.defs.values(), key=lambda d: d.tag):
                combo.addItem(f"H{h.tag}  {h.name}  ({MODEL_LABELS[h.model]})",
                              h.tag)
            combo.setCurrentIndex(max(0, combo.findData(
                self.assignments.get(tag, 0))))
            combo.currentIndexChanged.connect(lambda _i: self._update_count())
            self.table.setCellWidget(row, 2, combo)
            if tag in self._selected:
                self.table.setRangeSelected(
                    QTableWidgetSelectionRange(row, 0, row, 2), True)

        bar = QHBoxLayout()
        bar.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        bar.addWidget(close)
        bar.addWidget(save)
        lay.addLayout(bar)
        self._update_count()

    def _selected_rows(self) -> List[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def _apply_bulk(self) -> None:
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "Assign hinges",
                                    "Select one or more beam rows first.")
            return
        target = int(self.bulk.currentData() or 0)
        for row in rows:
            combo = self.table.cellWidget(row, 2)
            combo.setCurrentIndex(max(0, combo.findData(target)))
        self._update_count()

    def _clear_selected(self) -> None:
        for row in self._selected_rows():
            combo = self.table.cellWidget(row, 2)
            combo.setCurrentIndex(0)
        self._update_count()

    def _update_count(self) -> None:
        n = sum(1 for row in range(len(self.beams))
                if self.table.cellWidget(row, 2).currentData())
        self.count.setText(f"{n} of {len(self.beams)} beam elements assigned")

    def accept(self) -> None:
        out = {}
        for row, tag in enumerate(self.beams):
            hinge = int(self.table.cellWidget(row, 2).currentData() or 0)
            if hinge and hinge in self.defs:
                out[tag] = hinge
        self.assignments = out
        super().accept()
