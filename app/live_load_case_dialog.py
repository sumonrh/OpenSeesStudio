"""Live-load case dialog: select a saved vehicle and lane, then run."""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressBar, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from . import theme
from .dialogs import BaseDialog, hint, spin, title_label
from .live_load import (Axle, LiveLoadConfig, LiveLoadResults, Span,
                        analyze, beam_chain_from_project, chain_geometry,
                        preset_axles)
from .model import Lane, Project, Vehicle
from .vehicle_dialog import VehicleDiagram


class LiveLoadCaseDialog(BaseDialog):
    def __init__(self, project: Project,
                 selected_elements: Optional[Sequence[int]] = None,
                 parent=None) -> None:
        super().__init__("Live Load Case", parent, 1040)
        self.project = project
        self.selected_elements = [int(t) for t in (selected_elements or [])]
        self.results: Optional[LiveLoadResults] = None
        self.chain_spans: List[Span] = []
        self.chain_E = 200e9
        self.chain_I = 0.005
        self.chain_start_m = 0.0
        self.support_x: List[float] = []
        self.chain_note = ""
        self.chain_geometry = None
        self._detect_chain()
        self.resize(1120, 760)
        self.body.addWidget(hint(
            "Select a saved vehicle and traffic lane, then run the CL-625 "
            "moving-load envelope. Supports, spans and E/I come from the "
            "model; the resulting LL Max/Min/All envelopes appear in the main "
            "model view."))
        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)
        self._build_model_tab()
        self._build_case_tab()
        self._build_bottom_bar()
        self._refresh_vehicles()
        self._refresh_lanes()
        self._sync_controls()

    def _detect_chain(self) -> None:
        tags = [tag for tag in self.selected_elements
                if tag in self.project.elements
                and self.project.elements[tag].kind == "beam"]
        if not tags:
            beams = [tag for tag, e in self.project.elements.items()
                     if e.kind == "beam"]
            lanes = sorted(self.project.lanes.values(), key=lambda l: l.tag)
            if lanes:
                lane = lanes[0]
                ux, uy, _uz = lane.direction
                plan_len = (ux * ux + uy * uy) ** 0.5
                if plan_len > 1e-9:
                    ux, uy = ux / plan_len, uy / plan_len
                    candidates = []
                    for tag in beams:
                        e = self.project.elements[tag]
                        a = self.project.node_xyz(e.nodes[0])
                        b = self.project.node_xyz(e.nodes[1])
                        dx, dy = b[0] - a[0], b[1] - a[1]
                        length = (dx * dx + dy * dy) ** 0.5
                        if length <= 1e-9:
                            continue
                        if abs(dx * ux + dy * uy) / length < 0.95:
                            continue
                        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
                        lateral = ((mx - lane.shifted_start[0]) * lane.lateral_axis[0]
                                   + (my - lane.shifted_start[1]) * lane.lateral_axis[1])
                        candidates.append((abs(lateral), tag))
                    if candidates:
                        nearest = min(c[0] for c in candidates)
                        tags = [tag for dist, tag in candidates
                                if dist <= nearest + 500.0]
            if not tags:
                tags = beams
        chain = beam_chain_from_project(self.project, tags)
        if chain is None:
            self.chain_note = "No continuous beam chain with supports was found."
            return
        self.chain_spans, self.chain_E, self.chain_I, self.chain_note = chain
        self.chain_geometry = chain_geometry(self.project, tags)
        xs = [self.project.node_xyz(node)[0]
              for tag in tags if tag in self.project.elements
              for node in self.project.elements[tag].nodes]
        self.chain_start_m = min(xs) / 1000.0 if xs else 0.0
        cumulative = 0.0
        self.support_x = [self.chain_start_m]
        for span in self.chain_spans:
            cumulative += span.length
            self.support_x.append(self.chain_start_m + cumulative)

    def _build_model_tab(self) -> None:
        page = QWidget()
        lay = QHBoxLayout(page)
        left = QVBoxLayout()
        left.addWidget(title_label("Bridge from model"))
        supports = QLabel("Supports: " + ", ".join(
            f"{x:g}" for x in self.support_x) + " m")
        spans = QLabel("Spans: " + ", ".join(
            f"{s.length:g}" for s in self.chain_spans) + " m")
        for label in (supports, spans):
            label.setWordWrap(True)
            left.addWidget(label)
        note = QLabel(self.chain_note)
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        left.addWidget(note)
        left.addStretch(1)
        lay.addLayout(left, 1)
        right = QVBoxLayout()
        form = QFormLayout()
        form.addRow("Young's modulus E", QLabel(f"{self.chain_E / 1e9:g} GPa"))
        form.addRow("Moment of inertia I", QLabel(f"{self.chain_I:.6g} m4"))
        right.addLayout(form)
        right.addWidget(hint(
            "Support locations, span lengths and E/I are read directly from "
            "the selected/detected girder chain. Use the Load tab to edit "
            "Vehicles or Lanes."))
        right.addStretch(1)
        lay.addLayout(right, 1)
        self.tabs.addTab(page, "Model")

    def _build_case_tab(self) -> None:
        page = QWidget()
        lay = QHBoxLayout(page)
        left = QVBoxLayout()
        form = QFormLayout()
        self.case_name = QLineEdit("LL")
        self.vehicle_combo = QComboBox()
        self.lane_combo = QComboBox()
        self.lane_udl = spin(9.0, 0.0, 1000.0, 3, 1.0, "kN/m")
        self.dla_mode = QComboBox()
        self.dla_mode.addItem("Auto (selected-axle groups)", "auto")
        self.dla_mode.addItem("Manual override", "manual")
        self.dla_override = spin(25.0, 0.0, 100.0, 1, 5.0, "%")
        self.dla_multiplier = spin(100.0, 0.0, 100.0, 1, 10.0, "%")
        form.addRow("Case name", self.case_name)
        form.addRow("Vehicle", self.vehicle_combo)
        form.addRow("Lane", self.lane_combo)
        form.addRow("Lane load UDL", self.lane_udl)
        form.addRow("DLA mode", self.dla_mode)
        form.addRow("Manual DLA", self.dla_override)
        form.addRow("DLA multiplier d", self.dla_multiplier)
        left.addLayout(form)
        self.vehicle_caption = QLabel()
        self.vehicle_caption.setWordWrap(True)
        self.vehicle_caption.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        left.addWidget(self.vehicle_caption)
        self.lane_caption = QLabel()
        self.lane_caption.setWordWrap(True)
        self.lane_caption.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        left.addWidget(self.lane_caption)
        left.addWidget(hint(
            "Vehicles and lanes are defined from their own buttons on the Load "
            "tab. This dialog only creates the moving-load case and runs the "
            "LL Max/LL Min/LL All result envelopes."))
        left.addStretch(1)
        lay.addLayout(left, 1)
        right = QVBoxLayout()
        right.addWidget(QLabel("Vehicle elevation"))
        self.vehicle_diagram = VehicleDiagram()
        right.addWidget(self.vehicle_diagram)
        right.addStretch(1)
        lay.addLayout(right, 1)
        self.tabs.addTab(page, "Case")
        self.vehicle_combo.currentIndexChanged.connect(self._vehicle_changed)
        self.lane_combo.currentIndexChanged.connect(self._lane_changed)
        self.dla_mode.currentIndexChanged.connect(self._sync_controls)

    def _build_bottom_bar(self) -> None:
        row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setMaximumWidth(260)
        self.status = QLabel("Ready.")
        self.status.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        run = QPushButton("Run live load case")
        run.setDefault(True)
        run.clicked.connect(self._analyze)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(run)
        row.addWidget(self.progress)
        row.addWidget(self.status, 1)
        row.addWidget(close)
        self.body.addLayout(row)

    def _refresh_vehicles(self) -> None:
        self.vehicle_combo.blockSignals(True)
        self.vehicle_combo.clear()
        for tag in sorted(self.project.vehicles):
            vehicle = self.project.vehicles[tag]
            self.vehicle_combo.addItem(vehicle.name, tag)
        self.vehicle_combo.blockSignals(False)
        self._vehicle_changed()

    def _refresh_lanes(self) -> None:
        self.lane_combo.blockSignals(True)
        self.lane_combo.clear()
        for tag in sorted(self.project.lanes):
            lane = self.project.lanes[tag]
            self.lane_combo.addItem(lane.name, tag)
        self.lane_combo.blockSignals(False)
        self._lane_changed()

    def _vehicle(self) -> Optional[Vehicle]:
        tag = self.vehicle_combo.currentData()
        return self.project.vehicles.get(int(tag)) if tag is not None else None

    def _lane(self) -> Optional[Lane]:
        tag = self.lane_combo.currentData()
        return self.project.lanes.get(int(tag)) if tag is not None else None

    def _vehicle_changed(self, *_args) -> None:
        vehicle = self._vehicle()
        if vehicle is None:
            self.vehicle_caption.setText("No vehicle defined.")
            self.vehicle_diagram.set_axles([])
            return
        axles = [Axle(a, s) for a, s in vehicle.axles]
        if vehicle.model in ("CL-625", "BCL-625"):
            axles = preset_axles(vehicle.model)
            self.vehicle_caption.setText(
                f"{vehicle.name}: {vehicle.model} preset.")
        else:
            self.vehicle_caption.setText(
                f"{vehicle.name}: custom, {len(axles)} axles.")
        self.vehicle_diagram.set_axles(axles)

    def _lane_changed(self, *_args) -> None:
        lane = self._lane()
        if lane is None:
            self.lane_caption.setText("No lane defined. Use Load > Lanes.")
            return
        direction = "start -> end"
        self.lane_caption.setText(
            f"{lane.name}: {lane.length / 1000.0:g} m, shift "
            f"{lane.offset / 1000.0:+.2f} m, {direction}; "
            f"{len(lane.element_tags)} elements.")

    def _sync_controls(self) -> None:
        manual = self.dla_mode.currentData() == "manual"
        self.dla_override.setEnabled(manual)

    def _spans(self) -> List[Span]:
        return list(self.chain_spans)

    def _axles(self) -> List[Axle]:
        vehicle = self._vehicle()
        if vehicle is None:
            return []
        if vehicle.model in ("CL-625", "BCL-625"):
            return preset_axles(vehicle.model)
        return [Axle(a, s) for a, s in vehicle.axles]

    def config(self) -> LiveLoadConfig:
        vehicle = self._vehicle()
        lane = self._lane()
        if vehicle is None:
            raise ValueError("Select a vehicle.")
        if lane is None:
            raise ValueError("Select a lane.")
        if lane.points:
            lane_start, lane_end = 0.0, lane.length / 1000.0
        else:
            x0 = lane.shifted_start[0] / 1000.0 - self.chain_start_m
            x1 = lane.shifted_end[0] / 1000.0 - self.chain_start_m
            lane_start, lane_end = sorted((x0, x1))
        manual = self.dla_mode.currentData() == "manual"
        return LiveLoadConfig(
            E=self.chain_E, I=self.chain_I,
            elems_per_span=20, truck_increment=0.10,
            load_case="envelope",
            dla_override=self.dla_override.value() / 100.0 if manual else None,
            dla_multiplier=self.dla_multiplier.value() / 100.0,
            lane_udl=self.lane_udl.value(),
            truck_model=vehicle.model,
            bcl_subdivision=vehicle.bcl_subdivision,
            lane_name=lane.name,
            lane_start=lane_start, lane_end=lane_end,
            lane_offset=lane.offset / 1000.0)

    def _analyze(self) -> None:
        try:
            spans = self._spans()
            axles = self._axles()
            config = self.config()
        except Exception as exc:
            QMessageBox.warning(self, "Live load case", str(exc))
            return
        if not spans:
            QMessageBox.warning(self, "Live load case",
                                "No continuous beam chain was found.")
            return
        self.progress.setValue(0)
        self.status.setText("Analyzing...")

        def progress(fraction: float, message: str) -> None:
            self.progress.setValue(int(max(0.0, min(1.0, fraction)) * 1000))
            self.status.setText(message)
            QApplication.processEvents()

        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.results = analyze(spans, axles, config, progress)
        except Exception as exc:
            self.results = None
            self.status.setText(str(exc))
            QMessageBox.warning(self, "Live load case", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.progress.setValue(1000)
        self.status.setText("Live-load envelopes ready.")
        self.accept()
