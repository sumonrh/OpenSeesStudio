"""Response-spectrum definition and results dialogs."""

from __future__ import annotations

import copy
import csv
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QFileDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from . import theme
from .dialogs import BaseDialog, hint, int_spin, spin
from .groundmotion import spectrum_from_record
from .model import Project, ResponseSpectrumCase, fmt
from .opsgen import ResponseSpectrumResults
from .units import UNITS


def _num(value: float, decimals: int = 4) -> str:
    if abs(value) < 5e-5:
        return "0"
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


class ResponseSpectrumPlot(QWidget):
    """Period versus spectral acceleration, with modal period markers."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.results: Optional[ResponseSpectrumResults] = None
        self.setMinimumHeight(260)

    def set_results(self, results: ResponseSpectrumResults) -> None:
        self.results = results
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QBrush(QColor("#ffffff")))
        p.setPen(QPen(QColor(theme.BORDER)))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        r = self.results
        if r is None or len(r.periods) < 2:
            p.setPen(QPen(QColor(theme.MUTED)))
            p.drawText(self.rect(), Qt.AlignCenter, "Define a response spectrum")
            p.end()
            return
        left, top, right, bottom = 62, 18, 18, 38
        width = max(self.width() - left - right, 10)
        height = max(self.height() - top - bottom, 10)
        xmax = max(max(r.periods), 1e-9)
        ymax = max(max(r.accelerations), 1e-9) * 1.1

        def px(x: float) -> float:
            return left + width * x / xmax

        def py(y: float) -> float:
            return top + height - height * y / ymax

        p.setPen(QPen(QColor(theme.BORDER), 1.0))
        for i in range(6):
            x = xmax * i / 5.0
            y = ymax * i / 5.0
            p.drawLine(QPointF(px(x), top), QPointF(px(x), top + height))
            p.drawLine(QPointF(left, py(y)), QPointF(left + width, py(y)))
        p.setPen(QPen(QColor(theme.TEXT), 1.4))
        p.drawLine(QPointF(left, top), QPointF(left, top + height))
        p.drawLine(QPointF(left, top + height),
                   QPointF(left + width, top + height))
        p.setPen(QPen(QColor(theme.ACCENT), 2.0))
        for i in range(1, len(r.periods)):
            p.drawLine(QPointF(px(r.periods[i - 1]), py(r.accelerations[i - 1])),
                       QPointF(px(r.periods[i]), py(r.accelerations[i])))
        p.setPen(QPen(QColor(theme.ORANGE), 1.2, Qt.DashLine))
        for period in r.modal_periods:
            if 0.0 <= period <= xmax:
                p.drawLine(QPointF(px(period), top),
                           QPointF(px(period), top + height))
        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QPen(QColor(theme.MUTED)))
        for i in range(6):
            x = xmax * i / 5.0
            y = ymax * i / 5.0
            p.drawText(QRectF(px(x) - 35, top + height + 5, 70, 16),
                       Qt.AlignCenter, f"{x:.3g}")
            p.drawText(QRectF(4, py(y) - 8, left - 10, 16),
                       Qt.AlignRight | Qt.AlignVCenter, f"{y:.3g}")
        p.drawText(QRectF(left, top + height + 23, width, 16),
                   Qt.AlignCenter, "Period (s)")
        p.end()


class ResponseSpectrumDialog(BaseDialog):
    """Define the acceleration spectrum and modal combination."""

    def __init__(self, project: Project, parent=None) -> None:
        super().__init__("Response Spectrum Analysis", parent, 760)
        self.project = project
        self.case = copy.deepcopy(project.response_spectrum)
        self._case = self.case

        self.body.addWidget(hint(
            "Enter spectral acceleration in g. Use a catalog record to generate "
            "a 5%-damped spectrum at the periods in the table."))
        form = QFormLayout()
        self.name = QLineEdit(self.case.name)
        self.direction = QComboBox()
        for label, key in (("Global X", 1), ("Global Y", 2), ("Global Z", 3)):
            self.direction.addItem(label, key)
        self.damping = spin(self.case.damping_ratio, 0.0, 0.5, 4, 0.01)
        self.combination = QComboBox()
        for label, key in (("SRSS", "SRSS"), ("CQC", "CQC")):
            self.combination.addItem(label, key)
        self.modes = int_spin(self.case.n_modes, 1, 200)
        self.scale = spin(self.case.scale, 0.0, 100.0, 4, 0.1)
        form.addRow("Case name", self.name)
        form.addRow("Direction", self.direction)
        form.addRow("Damping ratio", self.damping)
        form.addRow("Combination", self.combination)
        form.addRow("Modes", self.modes)
        form.addRow("Scale", self.scale)
        self.body.addLayout(form)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Period (s)", "Sa (g)"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for period, sa in zip(self.case.periods, self.case.accelerations):
            self._append_row(period, sa)
        self.body.addWidget(self.table, 1)

        row = QHBoxLayout()
        add = QPushButton("Add row")
        add.clicked.connect(self._add_row)
        remove = QPushButton("Remove row")
        remove.clicked.connect(self._remove_row)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        self.record = QComboBox()
        for rec in sorted(project.ground_motions.values(), key=lambda r: r.tag):
            self.record.addItem(f"#{rec.tag}  {rec.name}", rec.tag)
        if self.record.count() == 0:
            self.record.addItem("No catalog records", 0)
        row.addWidget(QLabel("Catalog record"))
        row.addWidget(self.record)
        generate = QPushButton("Generate")
        generate.clicked.connect(self._generate)
        row.addWidget(generate)
        self.body.addLayout(row)
        self.info = hint("")
        self.body.addWidget(self.info)

        index = self.direction.findData(self.case.direction)
        if index >= 0:
            self.direction.setCurrentIndex(index)
        index = self.combination.findData(self.case.combination)
        if index >= 0:
            self.combination.setCurrentIndex(index)
        index = self.record.findData(self.case.record)
        if index >= 0:
            self.record.setCurrentIndex(index)
        self.buttons("Save")

    def _append_row(self, period: float, sa: float) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, value in enumerate((period, sa)):
            item = QTableWidgetItem(_num(value, 6))
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, col, item)

    def _add_row(self) -> None:
        last = 0.0
        if self.table.rowCount():
            try:
                last = float(self.table.item(self.table.rowCount() - 1, 0).text())
            except (AttributeError, ValueError):
                last = 0.0
        self._append_row(last + 0.1, 0.0)
        self.table.selectRow(self.table.rowCount() - 1)

    def _remove_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _periods(self) -> list[float]:
        values = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            try:
                values.append(float(item.text()) if item else 0.0)
            except ValueError:
                raise ValueError(f"Row {row + 1}: period is not a number.")
        return values

    def _generate(self) -> None:
        tag = int(self.record.currentData() or 0)
        rec = self.project.ground_motions.get(tag)
        if rec is None:
            QMessageBox.warning(self, "Response spectrum",
                                "Choose a ground-motion catalog record.")
            return
        try:
            periods = self._periods()
            if not periods:
                raise ValueError("Add at least one period row first.")
            values = spectrum_from_record(rec, periods, self.damping.value())
        except Exception as exc:
            QMessageBox.warning(self, "Response spectrum", str(exc))
            return
        for row, value in enumerate(values):
            item = QTableWidgetItem(_num(value, 6))
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 1, item)
        self.info.setText(
            f"Generated from {rec.name} at ζ = {self.damping.value():g}.")

    def accept(self) -> None:
        try:
            periods = self._periods()
            accelerations = []
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 1)
                accelerations.append(float(item.text()) if item else 0.0)
            if len(periods) < 2 or len(periods) != len(accelerations):
                raise ValueError("Enter at least two period/Sa rows.")
            pairs = sorted(zip(periods, accelerations))
            if pairs[0][0] < 0.0:
                raise ValueError("Periods must be non-negative.")
            if any(pairs[i + 1][0] <= pairs[i][0] for i in range(len(pairs) - 1)):
                raise ValueError("Periods must be strictly increasing.")
            if any(sa < 0.0 for _, sa in pairs):
                raise ValueError("Spectral accelerations must be non-negative.")
        except Exception as exc:
            QMessageBox.warning(self, "Response spectrum", str(exc))
            return
        self._case = ResponseSpectrumCase(
            name=self.name.text().strip() or "RS1",
            direction=int(self.direction.currentData() or 1),
            damping_ratio=self.damping.value(),
            combination=self.combination.currentData() or "SRSS",
            n_modes=self.modes.value(),
            scale=self.scale.value(),
            record=int(self.record.currentData() or 0),
            periods=[p for p, _ in pairs],
            accelerations=[sa for _, sa in pairs])
        super().accept()

    def spec(self) -> ResponseSpectrumCase:
        return self._case


class ResponseSpectrumResultsDialog(QDialog):
    """Spectrum plot, modal table and a link back to the deformed model."""

    showDeformed = Signal()

    def __init__(self, project: Project, results: ResponseSpectrumResults,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Response Spectrum Results")
        self.resize(900, 680)
        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.project = project
        self.results = results

        lay = QVBoxLayout(self)
        title = QLabel(f"Response spectrum — {results.case_name}")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {theme.ACCENT_DARK};")
        lay.addWidget(title)
        info = QLabel(
            f"Direction {results.direction}; {results.combination}; "
            f"{results.n_modes} modes; ζ = {results.damping_ratio:g}; "
            f"peak |u| = {fmt(UNITS.length(results.peak_disp), 4)} "
            f"{UNITS.length_unit}")
        info.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        lay.addWidget(info)

        self.plot = ResponseSpectrumPlot()
        self.plot.set_results(results)
        lay.addWidget(self.plot, 1)

        self.table = QTableWidget(len(results.modal_periods), 4)
        self.table.setHorizontalHeaderLabels(
            ["Mode", "Period (s)", "Mass ratio (%)", "Cumulative (%)"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row, period in enumerate(results.modal_periods):
            values = [str(row + 1), _num(period, 5)]
            if row < len(results.modal_mass_ratios):
                values.append(_num(results.modal_mass_ratios[row], 3))
            else:
                values.append("")
            if row < len(results.modal_cumulative_ratios):
                values.append(_num(results.modal_cumulative_ratios[row], 3))
            else:
                values.append("")
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, col, item)
        lay.addWidget(self.table, 1)

        bar = QHBoxLayout()
        bar.addStretch(1)
        show = QPushButton("Show deformed shape")
        show.clicked.connect(self.showDeformed.emit)
        export = QPushButton("Export spectrum CSV…")
        export.clicked.connect(self._export)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bar.addWidget(show)
        bar.addWidget(export)
        bar.addWidget(close)
        lay.addLayout(bar)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export response spectrum", "response_spectrum.csv",
            "CSV files (*.csv);;All files (*)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["period_s", "Sa_g"])
            for period, sa in zip(self.results.periods,
                                  self.results.accelerations):
                writer.writerow([period, sa])
