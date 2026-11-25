"""Results sidebar for beam diagrams and deformation."""

from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QGridLayout, QGroupBox, QLabel, QPushButton,
                               QTabWidget, QVBoxLayout, QWidget)

from . import theme
from .beamdiagram import COMPONENTS, COMPONENT_TITLES


REACTION_FORCE_COMPONENTS = (
    ("Fx", "Force reaction along global X"),
    ("Fy", "Force reaction along global Y"),
    ("Fz", "Force reaction along global Z"),
    ("Fxyz", "Show Fx, Fy, and Fz reaction arrows separately"),
)

REACTION_MOMENT_COMPONENTS = (
    ("Mx", "Moment reaction about global X"),
    ("My", "Moment reaction about global Y"),
    ("Mz", "Moment reaction about global Z"),
    ("Mxyz", "Show Mx, My, and Mz reaction arrows separately"),
)


class ResultsPanel(QWidget):
    """Side panel with load-case/combination driven results display."""

    diagramRequested = Signal()
    deformationRequested = Signal()
    reactionRequested = Signal()
    reactionDisplayChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(255)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self._build_diagram_tab()
        self._build_deformation_tab()
        self._build_reaction_tab()

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
        self.deform_values = QCheckBox("Show deformation values")
        self.deform_values.setToolTip("Show the resultant displacement at each node")
        lay.addLayout(form)
        lay.addWidget(self.deform_values)
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

    def _build_reaction_tab(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)

        form = QFormLayout()
        self.reaction_case = QComboBox()
        self.reaction_case.setMinimumWidth(150)
        self.reaction_case.currentIndexChanged.connect(self._scenario_changed)
        form.addRow("Load case / combo", self.reaction_case)
        self.reaction_kind = QLabel("")
        self.reaction_kind.setStyleSheet(f"color:{theme.MUTED};")
        form.addRow("", self.reaction_kind)
        lay.addLayout(form)

        self.reaction_boxes: Dict[str, QCheckBox] = {}
        force_box = QGroupBox("Force reactions")
        fgrid = QGridLayout(force_box)
        fgrid.setContentsMargins(8, 8, 8, 8)
        for i, (comp, tip) in enumerate(REACTION_FORCE_COMPONENTS):
            cb = QCheckBox(comp)
            cb.setToolTip(tip)
            cb.setChecked(comp in ("Fx", "Fy", "Fz"))
            cb.toggled.connect(lambda on, c=comp: self._reaction_component_toggled(c, on))
            self.reaction_boxes[comp] = cb
            fgrid.addWidget(cb, i // 2, i % 2)
        lay.addWidget(force_box)

        moment_box = QGroupBox("Moment reactions")
        mgrid = QGridLayout(moment_box)
        mgrid.setContentsMargins(8, 8, 8, 8)
        for i, (comp, tip) in enumerate(REACTION_MOMENT_COMPONENTS):
            cb = QCheckBox(comp)
            cb.setToolTip(tip)
            cb.setChecked(comp in ("Mx", "My", "Mz"))
            cb.toggled.connect(lambda on, c=comp: self._reaction_component_toggled(c, on))
            self.reaction_boxes[comp] = cb
            mgrid.addWidget(cb, i // 2, i % 2)
        lay.addWidget(moment_box)

        opt = QGroupBox("Display options")
        opt_lay = QFormLayout(opt)
        opt_lay.setContentsMargins(8, 8, 8, 8)
        self.reaction_scale = QDoubleSpinBox()
        self.reaction_scale.setRange(0.0, 10.0)
        self.reaction_scale.setDecimals(2)
        self.reaction_scale.setSingleStep(0.25)
        self.reaction_scale.setValue(0.0)
        self.reaction_scale.setSpecialValueText("Auto")
        self.reaction_scale.setToolTip("Reaction arrow scale multiplier; Auto fits the model")
        self.reaction_values = QCheckBox("Show values")
        self.reaction_values.setChecked(True)
        self.reaction_values.toggled.connect(lambda _on: self.reactionDisplayChanged.emit())
        self.reaction_legend = QPushButton("Legend")
        self.reaction_legend.setCheckable(True)
        self.reaction_legend.setChecked(True)
        self.reaction_legend.setToolTip(
            "Show or hide the max/min reaction summary overlay on the right side of the viewport")
        self.reaction_legend.toggled.connect(lambda _on: self.reactionDisplayChanged.emit())
        opt_lay.addRow("Scale", self.reaction_scale)
        opt_lay.addRow("", self.reaction_values)
        opt_lay.addRow("", self.reaction_legend)
        lay.addWidget(opt)

        apply_btn = QPushButton("Apply reactions")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self.reactionRequested.emit)
        lay.addWidget(apply_btn)
        self.reaction_note = QLabel("Choose a load case or combination, tick the "
                                    "reaction directions and press Apply.")
        self.reaction_note.setWordWrap(True)
        self.reaction_note.setStyleSheet(f"color:{theme.MUTED};")
        lay.addWidget(self.reaction_note)
        lay.addStretch(1)
        self.tabs.addTab(page, "Reactions")

    def _reaction_component_toggled(self, comp: str, checked: bool) -> None:
        if not checked:
            return
        force_primary = ("Fx", "Fy", "Fz")
        moment_primary = ("Mx", "My", "Mz")
        if comp == "Fxyz":
            to_uncheck = list(force_primary)
        elif comp in force_primary:
            to_uncheck = ["Fxyz"]
        elif comp == "Mxyz":
            to_uncheck = list(moment_primary)
        elif comp in moment_primary:
            to_uncheck = ["Mxyz"]
        else:
            return
        for other in to_uncheck:
            cb = self.reaction_boxes.get(other)
            if cb is not None and cb.isChecked():
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)

    # ------------------------------------------------------------------ state
    def set_scenarios(self, names: List[str]) -> None:
        for combo in (self.diagram_case, self.deform_case, self.reaction_case):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            if current in names:
                combo.setCurrentText(current)
            combo.blockSignals(False)
        self._scenario_changed()

    def set_current_scenario(self, name: str) -> None:
        for combo in (self.diagram_case, self.deform_case, self.reaction_case):
            index = combo.findText(name)
            if index >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)
        self._scenario_changed()

    def _scenario_changed(self, *_args) -> None:
        for combo, label in ((self.diagram_case, self.diagram_kind),
                             (self.deform_case, self.deform_kind),
                             (self.reaction_case, self.reaction_kind)):
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

    def deformation_show_values(self) -> bool:
        return self.deform_values.isChecked()

    def set_deformation_scale(self, value: float) -> None:
        self.deform_scale.blockSignals(True)
        self.deform_scale.setValue(value)
        self.deform_scale.blockSignals(False)

    def show_diagram_tab(self) -> None:
        self.tabs.setCurrentIndex(0)

    def show_deformation_tab(self) -> None:
        self.tabs.setCurrentIndex(1)

    def show_reactions_tab(self) -> None:
        self.tabs.setCurrentIndex(2)

    def reaction_scenario(self) -> str:
        return self.reaction_case.currentText()

    def reaction_components(self) -> List[str]:
        return [c for c, cb in self.reaction_boxes.items() if cb.isChecked()]

    def reaction_scale_value(self) -> float:
        return float(self.reaction_scale.value())

    def reaction_show_values(self) -> bool:
        return self.reaction_values.isChecked()

    def reaction_show_legend(self) -> bool:
        return self.reaction_legend.isChecked()

    def set_note(self, text: str) -> None:
        self.diagram_note.setText(text)
        self.deform_note.setText(text)
        self.reaction_note.setText(text)

    def set_busy(self, busy: bool) -> None:
        self.setEnabled(not busy)
