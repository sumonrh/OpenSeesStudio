"""Parameter dialogs for the structure wizards."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFormLayout

from .dialogs import BaseDialog, hint, int_spin, spin
from .model import Project
from .units import UNITS
from .wizards import WIZARDS


class StructureWizard(BaseDialog):
    """Parameter dialog for one of the structure templates."""

    def __init__(self, project: Project, kind: str, parent=None) -> None:
        title, subtitle = WIZARDS[kind]
        super().__init__(title, parent, 460)
        self.project = project
        self.kind = kind
        self.body.addWidget(hint(subtitle))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.material = self._combo(project.materials, "No materials")
        form.addRow("Material", self.material)

        if kind in ("frame2d", "frame3d"):
            self.bays_x = int_spin(3, 1, 50)
            self.bays_y = int_spin(2, 1, 50)
            self.bay_width = self._length(6000.0, "Bay width X")
            self.bay_depth = self._length(6000.0, "Bay width Y")
            self.storeys = int_spin(3, 1, 100)
            self.storey_height = self._length(3500.0, "Storey height")
            self.col_section = self._combo(project.sections, "No sections")
            self.beam_section = self._combo(project.sections, "No sections",
                                            prefer=1)
            form.addRow("Bays X", self.bays_x)
            if kind == "frame3d":
                form.addRow("Bays Y", self.bays_y)
            form.addRow("Bay width X", self.bay_width)
            if kind == "frame3d":
                form.addRow("Bay width Y", self.bay_depth)
            form.addRow("Storeys", self.storeys)
            form.addRow("Storey height", self.storey_height)
            form.addRow("Column section", self.col_section)
            form.addRow("Beam section", self.beam_section)
        elif kind in ("truss2d", "truss3d"):
            self.panels = int_spin(6, 1, 60)
            self.panel_width = self._length(4000.0, "Panel width")
            self.height = self._length(4000.0, "Truss height")
            self.width = self._length(4000.0, "Truss width")
            self.section = self._combo(project.sections, "No sections", prefer=1)
            form.addRow("Panels", self.panels)
            form.addRow("Panel width", self.panel_width)
            form.addRow("Truss height", self.height)
            if kind == "truss3d":
                form.addRow("Truss width", self.width)
            form.addRow("Section", self.section)
        else:
            self.spans = int_spin(3, 1, 20)
            self.span_length = self._length(30000.0, "Span length")
            self.width = self._length(12000.0, "Deck width")
            self.girders = int_spin(5, 2, 20)
            self.cross_spacing = self._length(5000.0, "Cross-beam spacing")
            self.girder_section = self._combo(project.sections, "No sections",
                                              prefer=1)
            self.cross_section = self._combo(project.sections, "No sections")
            form.addRow("Spans", self.spans)
            form.addRow("Span length", self.span_length)
            form.addRow("Deck width", self.width)
            form.addRow("Girders", self.girders)
            form.addRow("Cross-beam spacing", self.cross_spacing)
            form.addRow("Girder section", self.girder_section)
            form.addRow("Cross-beam section", self.cross_section)

        self.body.addLayout(form)
        self.body.addWidget(hint(
            "Nodes, elements and supports are created for the current project. "
            "Material and section choices are taken from the libraries."))
        self.buttons("Generate")

    def _combo(self, items: dict, empty: str, prefer: int = 0) -> QComboBox:
        combo = QComboBox()
        for tag, item in sorted(items.items()):
            combo.addItem(f"{tag}   {item.name}", tag)
        if combo.count() == 0:
            combo.addItem(empty, 0)
        else:
            combo.setCurrentIndex(min(prefer, combo.count() - 1))
        return combo

    @staticmethod
    def _length(value_mm: float, tip: str):
        w = spin(UNITS.length(value_mm), 1e-6, 1e12, UNITS.length_decimals,
                 UNITS.length(1000.0), UNITS.length_unit)
        w.setToolTip(tip)
        return w

    def spec(self) -> dict:
        spec = {
            "kind": self.kind,
            "mat": int(self.material.currentData() or 0),
        }
        if self.kind in ("frame2d", "frame3d"):
            spec.update({
                "bays_x": self.bays_x.value(),
                "bays_y": self.bays_y.value() if self.kind == "frame3d" else 0,
                "bay_width": UNITS.length_base(self.bay_width.value()),
                "bay_depth": (UNITS.length_base(self.bay_depth.value())
                              if self.kind == "frame3d" else 0.0),
                "storeys": self.storeys.value(),
                "storey_height": UNITS.length_base(self.storey_height.value()),
                "col_sec": int(self.col_section.currentData() or 0),
                "beam_sec": int(self.beam_section.currentData() or 0),
            })
        elif self.kind in ("truss2d", "truss3d"):
            spec.update({
                "panels": self.panels.value(),
                "panel_width": UNITS.length_base(self.panel_width.value()),
                "height": UNITS.length_base(self.height.value()),
                "width": (UNITS.length_base(self.width.value())
                          if self.kind == "truss3d" else 0.0),
                "sec": int(self.section.currentData() or 0),
            })
        else:
            spec.update({
                "spans": self.spans.value(),
                "span_length": UNITS.length_base(self.span_length.value()),
                "width": UNITS.length_base(self.width.value()),
                "girders": self.girders.value(),
                "cross_spacing": UNITS.length_base(self.cross_spacing.value()),
                "girder_sec": int(self.girder_section.currentData() or 0),
                "cross_sec": int(self.cross_section.currentData() or 0),
            })
        return spec
