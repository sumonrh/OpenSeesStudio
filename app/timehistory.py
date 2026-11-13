"""Time-history results view: response trace and CSV export."""

from __future__ import annotations

import csv
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)

from . import theme
from .model import Project, fmt
from .opsgen import TimeHistoryResults
from .units import UNITS

_DOFS = ("UX", "UY", "UZ", "RX", "RY", "RZ")
_QUANTITIES = (("Displacement", "disp"), ("Velocity", "vel"),
               ("Acceleration", "accel"))


class TimeHistoryPlot(QWidget):
    """One node/DOF response trace versus time."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.results: Optional[TimeHistoryResults] = None
        self.node = 0
        self.dof = 1
        self.quantity = "disp"
        self.setMinimumHeight(300)

    def set_trace(self, results: TimeHistoryResults, node: int, dof: int,
                  quantity: str) -> None:
        self.results = results
        self.node = int(node)
        self.dof = int(dof)
        self.quantity = quantity
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
    """Select a node/DOF and inspect the recorded response."""

    def __init__(self, project: Project, results: TimeHistoryResults,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Time-History Results")
        self.resize(980, 660)
        self.project = project
        self.results = results

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

        self.axis_note = QLabel("")
        self.axis_note.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        lay.addWidget(self.axis_note)

        self.plot = TimeHistoryPlot()
        lay.addWidget(self.plot, 1)

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

        # Start on the node/DOF with the largest displacement response.
        best = (-1.0, 0, 1)
        for nid, rows in results.node_disp.items():
            for dof in range(1, 7):
                peak = max((abs(row[dof - 1]) for row in rows
                            if len(row) >= dof), default=0.0)
                if peak > best[0]:
                    best = (peak, nid, dof)
        if best[1]:
            index = self.node.findData(best[1])
            if index >= 0:
                self.node.setCurrentIndex(index)
            self.dof.setCurrentIndex(best[2] - 1)

        self.node.currentIndexChanged.connect(self._refresh)
        self.dof.currentIndexChanged.connect(self._refresh)
        self.quantity.currentIndexChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self, *_args) -> None:
        node = int(self.node.currentData() or 0)
        dof = int(self.dof.currentData() or 1)
        quantity = self.quantity.currentData() or "disp"
        self.plot.set_trace(self.results, node, dof, quantity)
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
