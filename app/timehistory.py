"""Time-history results view: response trace, step navigation and forces."""

from __future__ import annotations

import csv
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QSlider, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme
from .model import Project, fmt
from .opsgen import TimeHistoryResults
from .units import UNITS

_DOFS = ("UX", "UY", "UZ", "RX", "RY", "RZ")
_QUANTITIES = (("Displacement", "disp"), ("Velocity", "vel"),
               ("Acceleration", "accel"))
_FORCE_LABELS = ("N", "Vy", "Vz", "T", "My", "Mz")


def _num(value: float, decimals: int = 4) -> str:
    if abs(value) < 5e-5:
        return "0"
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


class TimeHistoryPlot(QWidget):
    """One node/DOF response trace versus time, with a step cursor."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.results: Optional[TimeHistoryResults] = None
        self.node = 0
        self.dof = 1
        self.quantity = "disp"
        self.step = 0
        self.setMinimumHeight(280)

    def set_trace(self, results: TimeHistoryResults, node: int, dof: int,
                  quantity: str, step: int = 0) -> None:
        self.results = results
        self.node = int(node)
        self.dof = int(dof)
        self.quantity = quantity
        self.step = int(step)
        self.update()

    def set_step(self, step: int) -> None:
        self.step = int(step)
        self.update()

    def _values(self) -> tuple[list[float], list[float]]:
        if self.results is None:
            return [], []
        rows = self.results.history(self.node, self.quantity)
        if not rows:
            return [], []
        times = list(self.results.time)
        n = min(len(times), len(rows))
        values = []
        for i in range(n):
            component = rows[i][self.dof - 1] if len(rows[i]) >= self.dof else 0.0
            values.append(UNITS.length(component))
        return times[:n], values

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QBrush(QColor("#ffffff")))
        p.setPen(QPen(QColor(theme.BORDER)))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        xs, ys = self._values()
        if not xs:
            p.setPen(QPen(QColor(theme.MUTED)))
            p.drawText(self.rect(), Qt.AlignCenter, "Run a time-history analysis")
            p.end()
            return
        left, top, right, bottom = 64, 20, 22, 42
        width = max(self.width() - left - right, 10)
        height = max(self.height() - top - bottom, 10)
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys + [0.0]), max(ys + [0.0])
        if abs(xmax - xmin) < 1e-12:
            xmax = xmin + 1.0
        if abs(ymax - ymin) < 1e-12:
            ymax = ymin + 1.0
        pad = (ymax - ymin) * 0.08
        ymin -= pad
        ymax += pad

        def px(x: float) -> float:
            return left + (x - xmin) / (xmax - xmin) * width

        def py(y: float) -> float:
            return top + height - (y - ymin) / (ymax - ymin) * height

        p.setPen(QPen(QColor(theme.BORDER), 1.0))
        for i in range(6):
            x = xmin + (xmax - xmin) * i / 5.0
            y = ymin + (ymax - ymin) * i / 5.0
            p.drawLine(QPointF(px(x), top), QPointF(px(x), top + height))
            p.drawLine(QPointF(left, py(y)), QPointF(left + width, py(y)))
        p.setPen(QPen(QColor(theme.TEXT), 1.4))
        p.drawLine(QPointF(left, top), QPointF(left, top + height))
        p.drawLine(QPointF(left, top + height),
                   QPointF(left + width, top + height))

        p.setPen(QPen(QColor(theme.ACCENT), 2.0))
        for i in range(1, len(xs)):
            p.drawLine(QPointF(px(xs[i - 1]), py(ys[i - 1])),
                       QPointF(px(xs[i]), py(ys[i])))

        # Current-step cursor and marker.
        if 0 <= self.step < len(xs):
            p.setPen(QPen(QColor(theme.ORANGE), 1.2, Qt.DashLine))
            p.drawLine(QPointF(px(xs[self.step]), top),
                       QPointF(px(xs[self.step]), top + height))
            p.setPen(QPen(QColor(theme.ORANGE), 2.0))
            p.setBrush(QColor(theme.ORANGE))
            p.drawEllipse(QPointF(px(xs[self.step]), py(ys[self.step])), 4, 4)
            p.setBrush(Qt.NoBrush)

        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QPen(QColor(theme.MUTED)))
        for i in range(6):
            x = xmin + (xmax - xmin) * i / 5.0
            y = ymin + (ymax - ymin) * i / 5.0
            p.drawText(QRectF(px(x) - 35, top + height + 5, 70, 16),
                       Qt.AlignCenter, f"{x:.3g}")
            p.drawText(QRectF(4, py(y) - 8, left - 10, 16),
                       Qt.AlignRight | Qt.AlignVCenter, f"{y:.3g}")
        p.setPen(QPen(QColor(theme.MUTED)))
        p.drawText(QRectF(left, top + height + 23, width, 16),
                   Qt.AlignCenter, "Time (s)")
        p.end()


class TimeHistoryResultsDialog(QDialog):
    """Inspect a time history and drive the model one step at a time."""

    stepSelected = Signal(int)

    def __init__(self, project: Project, results: TimeHistoryResults,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Time-History Results")
        self.resize(1080, 820)
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.project = project
        self.results = results
        self._current_step = 0

        lay = QVBoxLayout(self)
        title = QLabel(f"Time history — {results.case_name}")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {theme.ACCENT_DARK};")
        lay.addWidget(title)
        info = QLabel(
            f"{results.n_steps} of {results.n_steps_requested} steps at "
            f"dt = {results.dt:g} s; {results.ground_motion}")
        info.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        info.setWordWrap(True)
        lay.addWidget(info)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Node"))
        self.node = QComboBox()
        for tag in sorted(results.node_disp):
            self.node.addItem(str(tag), tag)
        controls.addWidget(self.node)
        controls.addWidget(QLabel("DOF"))
        self.dof = QComboBox()
        for index, label in enumerate(_DOFS, start=1):
            self.dof.addItem(label, index)
        controls.addWidget(self.dof)
        controls.addWidget(QLabel("Quantity"))
        self.quantity = QComboBox()
        for label, key in _QUANTITIES:
            self.quantity.addItem(label, key)
        controls.addWidget(self.quantity)
        controls.addStretch(1)
        lay.addLayout(controls)

        step_row = QHBoxLayout()
        self.prev_btn = QPushButton("◀")
        self.prev_btn.setFixedWidth(36)
        self.next_btn = QPushButton("▶")
        self.next_btn.setFixedWidth(36)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, max(results.n_steps - 1, 0))
        self.step_spin = QSpinBox()
        self.step_spin.setRange(1, max(results.n_steps, 1))
        self.step_label = QLabel("")
        self.step_label.setMinimumWidth(230)
        step_row.addWidget(QLabel("Step"))
        step_row.addWidget(self.prev_btn)
        step_row.addWidget(self.slider, 1)
        step_row.addWidget(self.next_btn)
        step_row.addWidget(self.step_spin)
        step_row.addWidget(self.step_label)
        lay.addLayout(step_row)

        self.axis_note = QLabel("")
        self.axis_note.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        lay.addWidget(self.axis_note)

        self.plot = TimeHistoryPlot()
        lay.addWidget(self.plot, 1)

        forces_label = QLabel("Element end forces at the selected step")
        forces_label.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        lay.addWidget(forces_label)
        self.forces = QTableWidget()
        self.forces.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.forces.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.forces.verticalHeader().setVisible(False)
        self.forces.setMinimumHeight(190)
        self.forces.setMaximumHeight(280)
        lay.addWidget(self.forces)

        self.peak = QLabel("")
        self.peak.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        lay.addWidget(self.peak)

        bar = QHBoxLayout()
        bar.addStretch(1)
        export = QPushButton("Export CSV…")
        export.clicked.connect(self._export)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bar.addWidget(export)
        bar.addWidget(close)
        lay.addLayout(bar)

        # Start on the step with the largest displacement response.
        best = (-1.0, 0, 1, 0)
        for nid, rows in results.node_disp.items():
            for dof in range(1, 7):
                for i, row in enumerate(rows):
                    value = abs(row[dof - 1]) if len(row) >= dof else 0.0
                    if value > best[0]:
                        best = (value, nid, dof, i)
        if best[1]:
            index = self.node.findData(best[1])
            if index >= 0:
                self.node.setCurrentIndex(index)
            self.dof.setCurrentIndex(best[2] - 1)
        self._current_step = best[3]

        self.node.currentIndexChanged.connect(self._refresh_trace)
        self.dof.currentIndexChanged.connect(self._refresh_trace)
        self.quantity.currentIndexChanged.connect(self._refresh_trace)
        self.slider.valueChanged.connect(
            lambda value: self._set_step(value))
        self.step_spin.valueChanged.connect(
            lambda value: self._set_step(value - 1))
        self.prev_btn.clicked.connect(
            lambda: self._set_step(self._current_step - 1))
        self.next_btn.clicked.connect(
            lambda: self._set_step(self._current_step + 1))
        self._build_force_table()
        self._refresh_trace()
        self._set_step(self._current_step, emit=False)

    @property
    def current_step(self) -> int:
        return self._current_step

    def _build_force_table(self) -> None:
        self.force_ids = sorted(self.results.element_forces)
        headers = ["Element"]
        for end in ("i", "j"):
            headers += [f"{label}_{end}" for label in _FORCE_LABELS]
        self.forces.setColumnCount(len(headers))
        self.forces.setHorizontalHeaderLabels(headers)
        self.forces.setRowCount(max(len(self.force_ids), 1))
        if not self.force_ids:
            self.forces.setItem(0, 0, QTableWidgetItem(
                "No element forces recorded for this model."))
            self.forces.setSpan(0, 0, 1, len(headers))
            return
        for row, eid in enumerate(self.force_ids):
            self.forces.setItem(row, 0, QTableWidgetItem(str(eid)))
        self.forces.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.forces.horizontalHeader().setStretchLastSection(True)

    def _force_text(self, value: float, moment: bool) -> str:
        if moment:
            return _num(UNITS.moment(value))
        return _num(UNITS.force(value))

    def _fill_forces(self, step: int) -> None:
        if not self.force_ids:
            return
        for row, eid in enumerate(self.force_ids):
            rows = self.results.element_history(eid)
            values = rows[step] if 0 <= step < len(rows) else []
            for col, label in enumerate(_FORCE_LABELS, start=1):
                for end in range(2):
                    value = values[end * 6 + (col - 1)] if len(values) > end * 6 + (col - 1) else 0.0
                    moment = label in ("My", "Mz", "T")
                    item = QTableWidgetItem(self._force_text(value, moment))
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.forces.setItem(row, 1 + end * 6 + (col - 1), item)

    def _set_step(self, index: int, emit: bool = True) -> None:
        n = len(self.results.time)
        if n <= 0:
            return
        index = max(0, min(int(index), n - 1))
        self._current_step = index
        for widget, value in ((self.slider, index),
                              (self.step_spin, index + 1)):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        time_value = self.results.time[index]
        self.step_label.setText(
            f"Step {index + 1}/{n}   t = {time_value:.4g} s")
        self.plot.set_step(index)
        self._fill_forces(index)
        if emit:
            self.stepSelected.emit(index)

    def _refresh_trace(self, *_args) -> None:
        node = int(self.node.currentData() or 0)
        dof = int(self.dof.currentData() or 1)
        quantity = self.quantity.currentData() or "disp"
        self.plot.set_trace(self.results, node, dof, quantity,
                            self._current_step)
        rows = self.results.history(node, quantity)
        peak = max((abs(row[dof - 1]) for row in rows if len(row) >= dof),
                   default=0.0)
        suffix = "" if quantity == "disp" else "/s" if quantity == "vel" else "/s²"
        label = {"disp": "displacement", "vel": "velocity",
                 "accel": "acceleration"}[quantity]
        self.axis_note.setText(
            f"Node {node}, {_DOFS[dof - 1]} — {label} "
            f"({UNITS.length_unit}{suffix})")
        self.peak.setText(
            f"Peak |{_DOFS[dof - 1]}| at node {node}: "
            f"{fmt(UNITS.length(peak), 4)} {UNITS.length_unit}{suffix} ({label})")

    def _export(self) -> None:
        node = int(self.node.currentData() or 0)
        dof = int(self.dof.currentData() or 1)
        quantity = self.quantity.currentData() or "disp"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export time history", f"time_history_node{node}.csv",
            "CSV files (*.csv);;All files (*)")
        if not path:
            return
        rows = self.results.history(node, quantity)
        suffix = "" if quantity == "disp" else "/s" if quantity == "vel" else "/s²"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["time_s",
                             f"{_DOFS[dof - 1]} ({UNITS.length_unit}{suffix})"])
            for time_value, row in zip(self.results.time, rows):
                writer.writerow([time_value,
                                 row[dof - 1] if len(row) >= dof else ""])
