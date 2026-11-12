"""Pushover results view: capacity curve, steps and hinge state."""

from __future__ import annotations

import csv
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QFileDialog, QHBoxLayout, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QTextEdit, QVBoxLayout, QWidget)

from . import theme
from .model import Project, fmt
from .opsgen import PushoverResults
from .units import UNITS


class PushoverPlot(QWidget):
    """Base shear versus control displacement."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.results: Optional[PushoverResults] = None
        self.selected = 0
        self.setMinimumHeight(260)

    def set_results(self, results: PushoverResults, selected: int = 0) -> None:
        self.results = results
        self.selected = selected
        self.update()

    def set_selected(self, index: int) -> None:
        self.selected = index
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QBrush(QColor("#ffffff")))
        p.setPen(QPen(QColor(theme.BORDER)))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        r = self.results
        if r is None or not r.steps:
            p.setPen(QPen(QColor(theme.MUTED)))
            p.drawText(self.rect(), Qt.AlignCenter, "Run a pushover analysis")
            p.end()
            return
        left, top, right, bottom = 58, 18, 18, 36
        width = max(self.width() - left - right, 10)
        height = max(self.height() - top - bottom, 10)
        xs = [UNITS.length(s.displacement) for s in r.steps]
        ys = [UNITS.force(s.base_shear) for s in r.steps]
        xmin, xmax = min(xs + [0.0]), max(xs + [0.0])
        ymin, ymax = min(ys + [0.0]), max(ys + [0.0])
        if abs(xmax - xmin) < 1e-9:
            xmax = xmin + 1.0
        if abs(ymax - ymin) < 1e-9:
            ymax = ymin + 1.0
        pad_x = (xmax - xmin) * 0.05
        pad_y = (ymax - ymin) * 0.08
        xmin -= pad_x
        xmax += pad_x
        ymin -= pad_y
        ymax += pad_y

        def px(x: float) -> float:
            return left + (x - xmin) / (xmax - xmin) * width

        def py(y: float) -> float:
            return top + height - (y - ymin) / (ymax - ymin) * height

        # axes
        p.setPen(QPen(QColor(theme.BORDER), 1.2))
        p.drawLine(QPointF(left, top), QPointF(left, top + height))
        p.drawLine(QPointF(left, top + height), QPointF(left + width, top + height))
        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QPen(QColor(theme.MUTED)))
        for frac in (0.0, 0.5, 1.0):
            x = xmin + frac * (xmax - xmin)
            y = ymin + frac * (ymax - ymin)
            p.drawText(QRectF(2, top + height - (y - ymin) / (ymax - ymin) * height - 8,
                              left - 7, 16), Qt.AlignRight | Qt.AlignVCenter,
                       fmt(y, 2))
            p.drawText(QRectF(px(x) - 32, top + height + 4, 64, 14), Qt.AlignCenter,
                       fmt(x, 2))
        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        p.drawText(QRectF(left, 0, width, top), Qt.AlignCenter,
                   "Capacity curve")
        p.drawText(QRectF(left, top + height + 20, width, 15), Qt.AlignCenter,
                   f"Control displacement ({UNITS.length_unit})")
        p.save()
        p.translate(12, top + height / 2)
        p.rotate(-90)
        p.drawText(QRectF(-height / 2, -14, height, 14), Qt.AlignCenter,
                   f"Base shear ({UNITS.force_unit})")
        p.restore()

        poly = QPolygonF([QPointF(px(x), py(y)) for x, y in zip(xs, ys)])
        p.setPen(QPen(QColor(theme.ACCENT), 2.2))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(poly)
        for i, (x, y) in enumerate(zip(xs, ys)):
            r_pt = 4.0 if i == self.selected else 2.2
            p.setBrush(QBrush(QColor(theme.SELECTED) if i == self.selected
                              else QColor(theme.ACCENT)))
            p.setPen(QPen(QColor("#ffffff"), 1.0))
            p.drawEllipse(QPointF(px(x), py(y)), r_pt, r_pt)
        if r.steps:
            s = r.steps[self.selected]
            p.setFont(QFont("Segoe UI", 8))
            p.setPen(QPen(QColor(theme.ACCENT_DARK)))
            p.drawText(QPointF(left + 8, top + 14),
                       f"Step {s.step}: {fmt(UNITS.length(s.displacement), 3)} "
                       f"{UNITS.length_unit}, {fmt(UNITS.force(s.base_shear), 2)} "
                       f"{UNITS.force_unit}")
        p.end()


class PushoverResultsDialog(QDialog):
    stepSelected = Signal(int)

    def __init__(self, project: Project, results: PushoverResults, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pushover Results")
        self.resize(1020, 700)
        self.project = project
        self.results = results

        lay = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Pushover analysis")
        title.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {theme.ACCENT_DARK};")
        header.addWidget(title)
        header.addStretch(1)
        info = QLabel(f"{results.hinge_model} hinges · "
                      f"lateral {results.lateral_case or '—'} · "
                      f"{len(results.steps)} steps")
        info.setStyleSheet(f"color:{theme.MUTED};")
        header.addWidget(info)
        lay.addLayout(header)

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self.plot = PushoverPlot()
        page = QWidget()
        play = QVBoxLayout(page)
        play.addWidget(self.plot, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Display step"))
        self.step_combo = QComboBox()
        self.step_combo.setMinimumWidth(300)
        row.addWidget(self.step_combo)
        show = QPushButton("Show deformed shape")
        show.clicked.connect(self._show_current)
        row.addWidget(show)
        row.addStretch(1)
        play.addLayout(row)
        self.tabs.addTab(page, "Capacity Curve")

        self.steps_table = QTableWidget(0, 5)
        self.steps_table.setHorizontalHeaderLabels(
            ["Step", f"Control disp ({UNITS.length_unit})",
             f"Base shear ({UNITS.force_unit})", "Max hinge rotation (rad)",
             "Hinges yielded"])
        self.steps_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.steps_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.steps_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.steps_table.verticalHeader().setVisible(False)
        self.steps_table.horizontalHeader().setStretchLastSection(True)
        self.steps_table.itemSelectionChanged.connect(self._table_selected)
        self.tabs.addTab(self.steps_table, "Steps")

        self.hinge_table = QTableWidget(0, 6)
        self.hinge_table.setHorizontalHeaderLabels(
            ["Element", "End", "Hinge rotation (rad)",
             f"Hinge moment ({UNITS.moment_unit})", "Yield moment",
             "State"])
        self.hinge_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.hinge_table.setAlternatingRowColors(True)
        self.hinge_table.verticalHeader().setVisible(False)
        self.hinge_table.horizontalHeader().setStretchLastSection(True)
        self.tabs.addTab(self.hinge_table, "Hinge State")

        log = QTextEdit()
        log.setReadOnly(True)
        log.setPlainText(results.log or "No solver messages.")
        log.setStyleSheet("font-family: Consolas; font-size: 11px;")
        self.tabs.addTab(log, "Messages")

        bar = QHBoxLayout()
        bar.addStretch(1)
        export = QPushButton("Export CSV…")
        export.clicked.connect(self._export)
        bar.addWidget(export)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bar.addWidget(close)
        lay.addLayout(bar)

        for i, step in enumerate(results.steps):
            self.step_combo.addItem(
                f"Step {step.step}  ·  u={fmt(UNITS.length(step.displacement), 3)} "
                f"{UNITS.length_unit}  ·  V={fmt(UNITS.force(step.base_shear), 2)} "
                f"{UNITS.force_unit}")
        self.step_combo.currentIndexChanged.connect(self._select_step)
        self._fill_steps()
        self.plot.set_results(self.results, 0)
        self._select_step(0)

    def _fill_steps(self) -> None:
        self.steps_table.setRowCount(len(self.results.steps))
        for row, step in enumerate(self.results.steps):
            yielded = sum(
                1 for tag, moments in step.hinge_moments.items()
                if max(moments, default=0.0) > 0.98 * self.results.hinge_yield.get(tag, 1e99))
            values = [str(step.step), fmt(UNITS.length(step.displacement), 4),
                      fmt(UNITS.force(step.base_shear), 3),
                      fmt(self.results.max_hinge_rotation(step), 6), str(yielded)]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.steps_table.setItem(row, col, cell)
        self.steps_table.resizeColumnsToContents()

    def _select_step(self, index: int) -> None:
        if not (0 <= index < len(self.results.steps)):
            return
        self.step_combo.blockSignals(True)
        self.step_combo.setCurrentIndex(index)
        self.step_combo.blockSignals(False)
        self.steps_table.blockSignals(True)
        self.steps_table.selectRow(index)
        self.steps_table.blockSignals(False)
        self.plot.set_selected(index)
        self._fill_hinges(self.results.steps[index])
        self.stepSelected.emit(index)

    def _table_selected(self) -> None:
        rows = self.steps_table.selectionModel().selectedRows()
        if rows:
            self._select_step(rows[0].row())

    def _fill_hinges(self, step) -> None:
        rows = []
        for tag in sorted(step.hinge_rotations):
            rots = step.hinge_rotations.get(tag, [0.0, 0.0])
            moms = step.hinge_moments.get(tag, [0.0, 0.0])
            yield_m = self.results.hinge_yield.get(tag, 0.0)
            for end, (rot, mom) in enumerate(zip(rots, moms)):
                state = "Yielding" if mom > 0.98 * yield_m > 0 else "Elastic"
                rows.append([tag, "i" if end == 0 else "j",
                             fmt(rot, 6), fmt(UNITS.moment(mom), 3),
                             fmt(UNITS.moment(yield_m), 3), state])
        self.hinge_table.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if c >= 2:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c == 5 and value == "Yielding":
                    cell.setForeground(QBrush(QColor("#c92a2a")))
                self.hinge_table.setItem(r, c, cell)
        self.hinge_table.resizeColumnsToContents()

    def _show_current(self) -> None:
        index = self.step_combo.currentIndex()
        if index >= 0:
            self.stepSelected.emit(index)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export pushover results",
                                              "pushover.csv", "CSV files (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["# Pushover", self.results.lateral_case,
                             self.results.hinge_model])
            writer.writerow(["Step", f"Control disp ({UNITS.length_unit})",
                             f"Base shear ({UNITS.force_unit})",
                             "Max hinge rotation (rad)", "Hinges yielded"])
            for step in self.results.steps:
                yielded = sum(
                    1 for tag, moments in step.hinge_moments.items()
                    if max(moments, default=0.0)
                    > 0.98 * self.results.hinge_yield.get(tag, 1e99))
                writer.writerow([step.step, UNITS.length(step.displacement),
                                 UNITS.force(step.base_shear),
                                 self.results.max_hinge_rotation(step), yielded])
