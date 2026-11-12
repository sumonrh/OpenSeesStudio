"""Results sidebar for beam diagrams and deformation."""

from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QGridLayout, QGroupBox, QLabel, QPushButton,
                               QTabWidget, QVBoxLayout, QWidget)

from . import theme
from .beamdiagram import COMPONENTS, COMPONENT_TITLES


class ResultsPanel(QWidget):
    """Side panel with load-case/combination driven results display."""

    diagramRequested = Signal()
    deformationRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(255)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self._build_diagram_tab()
        self._build_deformation_tab()

    # ------------------------------------------------------------------ build
    def _build_diagram_tab(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)

        form = QFormLayout()
        self.diagram_case = QComboBox()
        self.diagram_case.setMinimumWidth(150)
        self.diagram_case.currentIndexChanged.connect(self._scenario_changed)
        form.addRow("Load case / combo", self.diagram_case)
        self.diagram_kind = QLabel("")
        self.diagram_kind.setStyleSheet(f"color:{theme.MUTED};")
        form.addRow("", self.diagram_kind)
        lay.addLayout(form)

        comp_box = QGroupBox("Components")
        grid = QGridLayout(comp_box)
        grid.setContentsMargins(8, 8, 8, 8)
        self.component_boxes: Dict[str, QCheckBox] = {}
        for i, comp in enumerate(COMPONENTS):
            cb = QCheckBox(comp)
            cb.setToolTip(COMPONENT_TITLES[comp])
            cb.setChecked(comp in ("My", "Mz"))
            self.component_boxes[comp] = cb
            grid.addWidget(cb, i // 2, i % 2)
        lay.addWidget(comp_box)

        opt = QGroupBox("Display options")
        opt_lay = QFormLayout(opt)
        opt_lay.setContentsMargins(8, 8, 8, 8)
        self.diagram_fill = QComboBox()
        self.diagram_fill.addItem("Solid fill", True)
        self.diagram_fill.addItem("No fill", False)
        self.diagram_scale = QDoubleSpinBox()
        self.diagram_scale.setRange(0.0, 100.0)
        self.diagram_scale.setDecimals(2)
        self.diagram_scale.setSingleStep(0.25)
        self.diagram_scale.setValue(0.0)
        self.diagram_scale.setSpecialValueText("Auto")
        self.diagram_scale.setToolTip("Diagram drawing scale; Auto fits the view")
        self.diagram_values = QCheckBox("Show values")
        self.diagram_deform = QCheckBox("Overlay deformed shape")
        opt_lay.addRow("Fill", self.diagram_fill)
        opt_lay.addRow("Scale", self.diagram_scale)
        opt_lay.addRow("", self.diagram_values)
        opt_lay.addRow("", self.diagram_deform)
        lay.addWidget(opt)

        apply_btn = QPushButton("Apply diagrams")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self.diagramRequested.emit)
        lay.addWidget(apply_btn)
        self.diagram_note = QLabel("Choose a load case or combination, tick the "
                                   "force components and press Apply.")
        self.diagram_note.setWordWrap(True)
        self.diagram_note.setStyleSheet(f"color:{theme.MUTED};")
        lay.addWidget(self.diagram_note)
        lay.addStretch(1)
        self.tabs.addTab(page, "Beam Diagrams")

    def _build_deformation_tab(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        form = QFormLayout()
        self.deform_case = QComboBox()
        self.deform_case.setMinimumWidth(150)
        self.deform_case.currentIndexChanged.connect(self._scenario_changed)
        form.addRow("Load case / combo", self.deform_case)
        self.deform_kind = QLabel("")
        self.deform_kind.setStyleSheet(f"color:{theme.MUTED};")
        form.addRow("", self.deform_kind)
        self.deform_scale = QDoubleSpinBox()
        self.deform_scale.setRange(0.0, 100000.0)
        self.deform_scale.setDecimals(1)
        self.deform_scale.setSingleStep(1.0)
        self.deform_scale.setValue(0.0)
        self.deform_scale.setSpecialValueText("Auto")
        self.deform_scale.setToolTip("Deformed-shape magnification; Auto fits the view")
        form.addRow("Scale", self.deform_scale)
        lay.addLayout(form)
        btn = QPushButton("Show deformation")
        btn.setDefault(True)
        btn.clicked.connect(self.deformationRequested.emit)
        lay.addWidget(btn)
        self.deform_note = QLabel("Deformation can be displayed for each load case "
                                  "or combination. The undeformed shape stays "
                                  "visible as a dashed outline.")
        self.deform_note.setWordWrap(True)
        self.deform_note.setStyleSheet(f"color:{theme.MUTED};")
        lay.addWidget(self.deform_note)
        lay.addStretch(1)
        self.tabs.addTab(page, "Deformation")

    # ------------------------------------------------------------------ state
    def set_scenarios(self, names: List[str]) -> None:
        for combo in (self.diagram_case, self.deform_case):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            if current in names:
                combo.setCurrentText(current)
            combo.blockSignals(False)
        self._scenario_changed()

    def set_current_scenario(self, name: str) -> None:
        for combo in (self.diagram_case, self.deform_case):
            index = combo.findText(name)
            if index >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)
        self._scenario_changed()

    def _scenario_changed(self, *_args) -> None:
        for combo, label in ((self.diagram_case, self.diagram_kind),
                             (self.deform_case, self.deform_kind)):
            text = combo.currentText()
            kind = self._kind_of(text)
            label.setText(kind)

    def _kind_of(self, name: str) -> str:
        project = getattr(self.window(), "project", None)
        if project is not None:
            if name in getattr(project, "combos", {}):
                return "Load combination"
            if name in getattr(project, "cases", {}):
                return "Load case"
        return ""

    def diagram_scenario(self) -> str:
        return self.diagram_case.currentText()

    def deformation_scenario(self) -> str:
        return self.deform_case.currentText()

    def components(self) -> List[str]:
        return [c for c, cb in self.component_boxes.items() if cb.isChecked()]

    def diagram_scale_value(self) -> float:
        return float(self.diagram_scale.value())

    def diagram_show_values(self) -> bool:
        return self.diagram_values.isChecked()

    def diagram_overlay_deform(self) -> bool:
        return self.diagram_deform.isChecked()

    def diagram_has_fill(self) -> bool:
        return bool(self.diagram_fill.currentData())

    def deformation_scale_value(self) -> float:
        return float(self.deform_scale.value())

    def set_deformation_scale(self, value: float) -> None:
        self.deform_scale.blockSignals(True)
        self.deform_scale.setValue(value)
        self.deform_scale.blockSignals(False)

    def show_diagram_tab(self) -> None:
        self.tabs.setCurrentIndex(0)

    def show_deformation_tab(self) -> None:
        self.tabs.setCurrentIndex(1)

    def set_note(self, text: str) -> None:
        self.diagram_note.setText(text)
        self.deform_note.setText(text)

    def set_busy(self, busy: bool) -> None:
        self.setEnabled(not busy)
