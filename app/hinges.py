"""OpenSees hinge-material library and element assignment dialogs."""

from __future__ import annotations

import copy
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QScrollArea,
                               QTableWidget, QTableWidgetItem,
                               QTableWidgetSelectionRange, QTabWidget,
                               QVBoxLayout, QWidget)

from . import theme
from .hinge_catalog import FAMILIES, MATERIALS, defaults, image_path
from .hysteresis import HysteresisDialog
from .model import HingeDefinition, Project
from .units import UNITS


class HingeLibraryDialog(QDialog):
    """Create reusable hinge definitions using the OpenSees material catalogue."""

    def __init__(self, project: Project, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hinge Library")
        self.resize(1120, 760)
        self.project = project
        self.defs: Dict[int, HingeDefinition] = copy.deepcopy(project.hinge_defs)
        self.current: Optional[HingeDefinition] = None
        self._loading = False

        lay = QVBoxLayout(self)
        title = QLabel("Hinge definitions")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {theme.ACCENT_DARK};")
        lay.addWidget(title)
        lay.addWidget(QLabel(
            "Each definition is a real OpenSees uniaxial material. Families are "
            "separated into tabs so material-specific parameters are never mixed. "
            "Fibre models can be assigned to beam elements; moment-rotation models "
            "are library-only until spring hinges are available."))

        body = QHBoxLayout()
        left = QVBoxLayout()
        self.tabs = QTabWidget()
        self.lists: Dict[str, QListWidget] = {}
        for family in FAMILIES:
            page = QWidget()
            play = QVBoxLayout(page)
            play.setContentsMargins(4, 4, 4, 4)
            widget = QListWidget()
            widget.currentRowChanged.connect(self._selection_changed)
            self.lists[family] = widget
            play.addWidget(widget, 1)
            self.tabs.addTab(page, family)
        left.addWidget(self.tabs, 1)
        row = QHBoxLayout()
        for text, slot in (("New", self._new), ("Duplicate", self._duplicate),
                           ("Delete", self._delete)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        left.addLayout(row)
        body.addLayout(left, 0)

        right = QVBoxLayout()
        form = QFormLayout()
        self.name = QLineEdit()
        self.material = QComboBox()
        self.length_ratio = QDoubleSpinBox()
        self.length_ratio.setRange(0.01, 0.25)
        self.length_ratio.setDecimals(3)
        self.length_ratio.setSingleStep(0.01)
        form.addRow("Name", self.name)
        form.addRow("OpenSees material", self.material)
        form.addRow("Plastic hinge length / L", self.length_ratio)
        right.addLayout(form)
        self.material.currentIndexChanged.connect(self._material_changed)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        right.addWidget(self.note)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(6, 6, 6, 6)
        self.scroll.setWidget(self.form_host)
        right.addWidget(self.scroll, 1)
        self._param_widgets: Dict[str, QWidget] = {}
        diagram = QPushButton("Hysteresis diagram / parameter definitions…")
        diagram.clicked.connect(self._diagram)
        right.addWidget(diagram)
        body.addLayout(right, 1)
        lay.addLayout(body, 1)

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

        self.tabs.currentChanged.connect(self._tab_changed)
        self._reload_lists()
        self._select_first()

    # ------------------------------------------------------------------ widgets
    def _current_family(self) -> str:
        return self.tabs.tabText(self.tabs.currentIndex())

    def _family_list(self) -> QListWidget:
        return self.lists[self._current_family()]

    def _current_def(self) -> Optional[HingeDefinition]:
        item = self._family_list().currentItem()
        if item is None:
            return None
        return self.defs.get(item.data(Qt.UserRole))

    def _select_first(self) -> None:
        for index, family in enumerate(FAMILIES):
            widget = self.lists[family]
            if widget.count():
                self.tabs.blockSignals(True)
                self.tabs.setCurrentIndex(index)
                self.tabs.blockSignals(False)
                widget.setCurrentRow(0)
                return
        self.current = None
        self._clear_form()

    def _reload_lists(self) -> None:
        self._loading = True
        for family in FAMILIES:
            widget = self.lists[family]
            current = widget.currentItem().data(Qt.UserRole) if widget.currentItem() else None
            widget.blockSignals(True)
            widget.clear()
            for h in sorted(self.defs.values(), key=lambda d: d.tag):
                if h.family != family:
                    continue
                item = QListWidgetItem(f"H{h.tag}   {h.name}   [{h.material}]")
                item.setData(Qt.UserRole, h.tag)
                widget.addItem(item)
                if h.tag == current:
                    widget.setCurrentItem(item)
            widget.blockSignals(False)
        self._loading = False

    def _clear_form(self) -> None:
        self.name.clear()
        self.material.clear()
        self.length_ratio.setValue(0.1)
        while self.form.rowCount():
            self.form.removeRow(0)
        self._param_widgets = {}
        self.note.setText("")

    def _fill_materials(self, family: str, preferred: str = "") -> None:
        self.material.blockSignals(True)
        self.material.clear()
        for m in MATERIALS.values():
            if m.family == family:
                self.material.addItem(f"{m.key} — {m.label.split(' — ', 1)[-1]}",
                                      m.key)
        index = self.material.findData(preferred)
        self.material.setCurrentIndex(index if index >= 0 else 0)
        self.material.blockSignals(False)

    def _build_params(self, material: str) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._param_widgets = {}
        spec = MATERIALS[material]
        for p in spec.params:
            if p.unit == "stress":
                widget = _spin(UNITS.stress(p.default), UNITS.stress(p.low),
                               UNITS.stress(p.high), p.decimals,
                               UNITS.stress_unit)
            elif p.unit == "length":
                widget = _spin(UNITS.length(p.default), UNITS.length(p.low),
                               UNITS.length(p.high), UNITS.length_decimals,
                               UNITS.length_unit)
            elif p.unit == "force":
                widget = _spin(UNITS.force(p.default), UNITS.force(p.low),
                               UNITS.force(p.high), 3, UNITS.force_unit)
            elif p.unit == "rotation":
                widget = _spin(p.default, p.low, p.high, p.decimals, "rad")
            elif p.unit == "rot_stiffness":
                widget = _spin(p.default, p.low, p.high, p.decimals,
                               "kN·mm/rad")
            else:
                widget = _spin(p.default, p.low, p.high, p.decimals)
            widget.setToolTip(p.description)
            self.form.addRow(p.label, widget)
            self._param_widgets[p.key] = widget
        self.note.setText((spec.note + "  " if spec.note else "") +
                          "Source: OpenSees documentation. " +
                          ("Moment-rotation material: spring hinge only." if spec.kind == "spring" else ""))

    # ------------------------------------------------------------------ state
    def _selection_changed(self, _row: int) -> None:
        if self._loading:
            return
        self._store()
        h = self._current_def()
        self.current = h
        if h is None:
            self._clear_form()
            return
        self._loading = True
        self.name.setText(h.name)
        self.length_ratio.setValue(h.length_ratio)
        self._fill_materials(h.family, h.material)
        self._build_params(h.material)
        defaults_for_material = {p.key: p.default
                                 for p in MATERIALS[h.material].params}
        for key, widget in self._param_widgets.items():
            value = float(h.params.get(key, defaults_for_material.get(key, 0.0)))
            self._set_widget(widget, key, value)
        self._loading = False

    def _tab_changed(self, _index: int) -> None:
        if self._loading:
            return
        self._store()
        widget = self._family_list()
        if widget.count():
            widget.setCurrentRow(0)
        else:
            self.current = None
            self._clear_form()

    def _material_changed(self, _index: int) -> None:
        if self._loading or self.current is None:
            return
        material = self.material.currentData()
        if not material:
            return
        self.current.material = material
        self.current.family = MATERIALS[material].family
        self.current.params = defaults(material)
        self._build_params(material)
        for key, p in enumerate(MATERIALS[material].params):
            self._set_widget(self._param_widgets[p.key], p.key, p.default)

    def _set_widget(self, widget: QWidget, key: str, base_value: float) -> None:
        spec = next(p for p in MATERIALS[self.current.material].params
                    if p.key == key)
        if spec.unit == "stress":
            value = UNITS.stress(base_value)
        elif spec.unit == "length":
            value = UNITS.length(base_value)
        elif spec.unit == "force":
            value = UNITS.force(base_value)
        else:
            value = base_value
        widget.setValue(value)

    def _read_widget(self, widget: QWidget, key: str) -> float:
        spec = next(p for p in MATERIALS[self.current.material].params
                    if p.key == key)
        value = widget.value()
        if spec.unit == "stress":
            return UNITS.stress_base(value)
        if spec.unit == "length":
            return UNITS.length_base(value)
        if spec.unit == "force":
            return UNITS.force_base(value)
        return float(value)

    def _store(self) -> None:
        if self._loading or self.current is None:
            return
        self.current.name = self.name.text().strip() or f"Hinge {self.current.tag}"
        self.current.length_ratio = self.length_ratio.value()
        material = self.material.currentData()
        if material:
            self.current.material = material
            self.current.family = MATERIALS[material].family
        if self._param_widgets:
            self.current.params = {
                key: self._read_widget(widget, key)
                for key, widget in self._param_widgets.items()}
        widget = self.lists.get(self.current.family)
        if widget is not None:
            for row in range(widget.count()):
                item = widget.item(row)
                if item.data(Qt.UserRole) == self.current.tag:
                    item.setText(f"H{self.current.tag}   {self.current.name}   "
                                 f"[{self.current.material}]")
                    break

    # ------------------------------------------------------------------ actions
    def _new(self) -> None:
        self._store()
        family = self._current_family()
        if self.current is not None and self.current.family == family:
            spec = MATERIALS.get(self.current.material)
        else:
            spec = next((m for m in MATERIALS.values() if m.family == family), None)
        if spec is None:
            return
        tag = max(self.defs, default=0) + 1
        h = HingeDefinition(tag, f"{spec.key} {tag}", spec.key, family,
                            0.10, defaults(spec.key))
        self.defs[tag] = h
        self._reload_lists()
        widget = self.lists[family]
        for row in range(widget.count()):
            if widget.item(row).data(Qt.UserRole) == tag:
                widget.setCurrentRow(row)
                break

    def _duplicate(self) -> None:
        self._store()
        source = self._current_def()
        if source is None:
            return
        tag = max(self.defs, default=0) + 1
        h = copy.deepcopy(source)
        h.tag = tag
        h.name = f"{source.name} copy"
        self.defs[tag] = h
        self._reload_lists()
        widget = self.lists[h.family]
        for row in range(widget.count()):
            if widget.item(row).data(Qt.UserRole) == tag:
                widget.setCurrentRow(row)
                break

    def _delete(self) -> None:
        self._store()
        source = self._current_def()
        if source is None:
            return
        used = sum(1 for hinge in self.project.hinge_assignments.values()
                   if hinge == source.tag)
        if used and QMessageBox.question(
                self, "Delete hinge",
                f"{source.name} is assigned to {used} element(s). "
                "Delete it and clear those assignments?") != QMessageBox.Yes:
            return
        self.defs.pop(source.tag, None)
        self._reload_lists()
        self._select_first()

    def _diagram(self) -> None:
        self._store()
        h = self._current_def()
        if h is None:
            return
        image = image_path(h.material)
        HysteresisDialog(h.material, h.params, self, image_path=image,
                         note=MATERIALS[h.material].note).exec()

    def accept(self) -> None:
        self._store()
        super().accept()


class AssignHingesDialog(QDialog):
    """Assign created fibre hinge definitions to beam elements."""

    def __init__(self, project: Project, parent=None,
                 selected: Optional[List[int]] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Hinges")
        self.resize(880, 700)
        self.project = project
        self.defs = {tag: h for tag, h in project.hinge_defs.items()
                     if MATERIALS.get(h.material) is not None
                     and MATERIALS[h.material].kind == "fiber"}
        self.assignments: Dict[int, int] = {
            e: h for e, h in project.hinge_assignments.items() if h in self.defs}
        self.beams = sorted(tag for tag, e in project.elements.items()
                            if e.kind == "beam" and len(e.nodes) >= 2)
        self._selected = set(selected or [])

        lay = QVBoxLayout(self)
        title = QLabel("Assign hinges to elements")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {theme.ACCENT_DARK};")
        lay.addWidget(title)
        if not self.defs:
            warning = QLabel(
                "No fibre hinge definitions exist. Create one in Define Hinges. "
                "Moment-rotation definitions are spring-only and are not listed here.")
            warning.setWordWrap(True)
            warning.setStyleSheet("color:#c92a2a; font-weight:600;")
            lay.addWidget(warning)
        self.count = QLabel()
        self.count.setStyleSheet(f"color:{theme.MUTED};")
        lay.addWidget(self.count)

        tools = QHBoxLayout()
        tools.addWidget(QLabel("Set selected rows to"))
        self.bulk = QComboBox()
        self.bulk.addItem("None", 0)
        for h in sorted(self.defs.values(), key=lambda d: d.tag):
            self.bulk.addItem(f"H{h.tag}  {h.name}  [{h.material}]", h.tag)
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

        self.table = QTableWidget(len(self.beams), 4)
        self.table.setHorizontalHeaderLabels(
            ["Element", "Section", "Material", "Assigned hinge"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        for col, width in enumerate((80, 220, 100, 420)):
            self.table.setColumnWidth(col, width)
        lay.addWidget(self.table, 1)

        for row, tag in enumerate(self.beams):
            e = project.elements[tag]
            sec = project.section_of(e)
            mat = project.material_of(e)
            self.table.setItem(row, 0, QTableWidgetItem(str(tag)))
            self.table.setItem(row, 1, QTableWidgetItem(f"{sec.tag}  {sec.name}"))
            self.table.setItem(row, 2, QTableWidgetItem(mat.name))
            combo = QComboBox()
            combo.addItem("None", 0)
            for h in sorted(self.defs.values(), key=lambda d: d.tag):
                combo.addItem(f"H{h.tag}  {h.name}  [{h.material}]", h.tag)
            combo.setCurrentIndex(max(0, combo.findData(
                self.assignments.get(tag, 0))))
            combo.currentIndexChanged.connect(lambda _i: self._update_count())
            self.table.setCellWidget(row, 3, combo)
            if tag in self._selected:
                self.table.setRangeSelected(
                    QTableWidgetSelectionRange(row, 0, row, 3), True)

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
            combo = self.table.cellWidget(row, 3)
            combo.setCurrentIndex(max(0, combo.findData(target)))
        self._update_count()

    def _clear_selected(self) -> None:
        for row in self._selected_rows():
            self.table.cellWidget(row, 3).setCurrentIndex(0)
        self._update_count()

    def _update_count(self) -> None:
        n = sum(1 for row in range(len(self.beams))
                if self.table.cellWidget(row, 3).currentData())
        self.count.setText(f"{n} of {len(self.beams)} beam elements assigned")

    def accept(self) -> None:
        out = {}
        for row, tag in enumerate(self.beams):
            hinge = int(self.table.cellWidget(row, 3).currentData() or 0)
            if hinge and hinge in self.defs:
                out[tag] = hinge
        self.assignments = out
        super().accept()


def _spin(value: float, low: float, high: float, decimals: int,
          suffix: str = ""):
    widget = QDoubleSpinBox()
    widget.setRange(low, high)
    widget.setDecimals(decimals)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    if suffix:
        widget.setSuffix(" " + suffix)
    return widget
