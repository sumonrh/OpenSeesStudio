"""Ground-motion catalog management dialogs."""

from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from . import theme
from .dialogs import BaseDialog, hint, spin
from .groundmotion import detect_format, read_file
from .model import GroundMotionRecord, Project
from .units import UNITS


class MotionPreview(QWidget):
    """Small acceleration-time preview for a catalog record."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.dt = 0.01
        self.values: list[float] = []
        self.note = ""
        self.setMinimumHeight(150)

    def set_data(self, dt: float, values: list[float], note: str = "") -> None:
        self.dt = dt
        self.values = values
        self.note = note
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QBrush(QColor("#ffffff")))
        p.setPen(QPen(QColor(theme.BORDER)))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if not self.values:
            p.setPen(QPen(QColor(theme.MUTED)))
            p.drawText(self.rect(), Qt.AlignCenter, "Select a record to preview")
            p.end()
            return
        left, top, right, bottom = 46, 14, 14, 30
        width = max(self.width() - left - right, 10)
        height = max(self.height() - top - bottom, 10)
        values = self.values
        step = max(1, len(values) // 3000)
        values = values[::step]
        times = [i * step * self.dt for i in range(len(values))]
        xmax = max(times[-1], 1e-9)
        ymax = max(max(abs(v) for v in values), 1e-9)
        p.setPen(QPen(QColor(theme.BORDER), 1.0))
        p.drawLine(QPointF(left, top + height / 2),
                   QPointF(left + width, top + height / 2))
        p.setPen(QPen(QColor(theme.ACCENT), 1.4))
        for i in range(1, len(values)):
            x0 = left + width * times[i - 1] / xmax
            y0 = top + height / 2 - height / 2 * values[i - 1] / ymax
            x1 = left + width * times[i] / xmax
            y1 = top + height / 2 - height / 2 * values[i] / ymax
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QPen(QColor(theme.MUTED)))
        p.drawText(QRectF(left, top + height + 4, width, 18),
                   Qt.AlignCenter, "Time (s)")
        p.drawText(QRectF(2, top, left - 6, height),
                   Qt.AlignCenter, "a (g)")
        p.end()


class GroundMotionRecordDialog(BaseDialog):
    """Add or edit one catalog record."""

    def __init__(self, project: Project, record: GroundMotionRecord | None = None,
                 parent=None) -> None:
        super().__init__("Ground Motion Record", parent, 620)
        self.project = project
        self.record = copy.deepcopy(record) if record else GroundMotionRecord()
        self._npts = int(self.record.npts)
        self._detected_dt = float(self.record.dt or 0.01)

        form = QFormLayout()
        self.name = QLineEdit(self.record.name)
        self.path = QLineEdit(self.record.path)
        self.path.setPlaceholderText("PEER AT2, time + acceleration, or acceleration only")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path, 1)
        path_row.addWidget(browse)
        path_host = QWidget()
        path_host.setLayout(path_row)
        self.format = QComboBox()
        for label, key in (("Auto detect", "auto"), ("PEER AT2 / NGA", "at2"),
                           ("Time + acceleration", "two_column"),
                           ("Acceleration only", "single_column")):
            self.format.addItem(label, key)
        self.dt = spin(self.record.dt or 0.01, 0.0001, 1.0, 5, 0.005, "s")
        self.scale = spin(self.record.scale or 1.0, 0.0, 100.0, 4, 0.1)
        self.note = QLineEdit(self.record.note)
        self.note.setPlaceholderText("Event, station, component, …")
        self.info = hint("")
        form.addRow("Name", self.name)
        form.addRow("File", path_host)
        form.addRow("Format", self.format)
        form.addRow("Time step", self.dt)
        form.addRow("Record scale", self.scale)
        form.addRow("Note", self.note)
        form.addRow("", self.info)
        self.body.addLayout(form)
        self.buttons("Save")

        index = self.format.findData(self.record.format)
        if index >= 0:
            self.format.setCurrentIndex(index)
        self.path.editingFinished.connect(self._probe)
        self.format.currentIndexChanged.connect(self._probe)
        if self.record.path:
            self._probe()

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open ground motion", self.path.text() or "",
            "Ground motions (*.txt *.dat *.at2 *.csv);;All files (*)")
        if path:
            self.path.setText(path)
            if not self.name.text().strip():
                self.name.setText(Path(path).stem)
            self._probe()

    def _probe(self) -> None:
        path = self.path.text().strip()
        if not path:
            self.info.setText("")
            return
        try:
            motion = read_file(path, self.format.currentData() or "auto",
                               self.dt.value())
        except Exception as exc:
            self.info.setText(f"⚠ {exc}")
            self.info.setStyleSheet("color:#c92a2a; font-size:11px;")
            return
        self.info.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        self.info.setText(f"{motion.note}; duration {motion.duration:g} s")
        self._npts = motion.npts
        self._detected_dt = motion.dt
        if self.format.currentData() == "auto":
            actual = detect_format(path)
            index = self.format.findData(actual)
            if index >= 0:
                self.format.blockSignals(True)
                self.format.setCurrentIndex(index)
                self.format.blockSignals(False)
        if self.format.currentData() == "single_column":
            self.dt.setValue(motion.dt)

    def _build(self) -> GroundMotionRecord:
        path = self.path.text().strip()
        motion = read_file(path, self.format.currentData() or "auto",
                           self.dt.value())
        name = self.name.text().strip() or Path(path).stem or "Record"
        return GroundMotionRecord(
            tag=self.record.tag,
            name=name,
            path=path,
            format=self.format.currentData() or "auto",
            dt=motion.dt,
            npts=motion.npts,
            scale=self.scale.value(),
            note=self.note.text().strip())

    def accept(self) -> None:
        if not self.path.text().strip():
            QMessageBox.warning(self, "Ground motion", "Choose a ground-motion file.")
            return
        try:
            self.record = self._build()
        except Exception as exc:
            QMessageBox.warning(self, "Ground motion", str(exc))
            return
        super().accept()

    def spec(self) -> GroundMotionRecord:
        return self.record


class GroundMotionCatalogDialog(QDialog):
    """Project ground-motion catalog."""

    def __init__(self, project: Project, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ground Motion Catalog")
        self.resize(1080, 680)
        self.project = project
        self.records = copy.deepcopy(project.ground_motions)

        lay = QVBoxLayout(self)
        title = QLabel("Ground-motion catalog")
        title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {theme.ACCENT_DARK};")
        lay.addWidget(title)
        lay.addWidget(hint(
            "Records are referenced by file path. The time-history case may "
            "select one record; the record scale is applied before the case scale."))

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Tag", "Name", "Format", "dt (s)", "Points", "Duration (s)", "File"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        for col, width in enumerate((50, 180, 130, 75, 75, 95, 400)):
            self.table.setColumnWidth(col, width)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        lay.addWidget(self.table, 1)

        self.preview = MotionPreview()
        lay.addWidget(self.preview, 0)

        row = QHBoxLayout()
        add = QPushButton("Add…")
        add.clicked.connect(self._add)
        edit = QPushButton("Edit…")
        edit.clicked.connect(self._edit)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        row.addWidget(add)
        row.addWidget(edit)
        row.addWidget(remove)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        row.addWidget(close)
        row.addWidget(save)
        lay.addLayout(row)
        self._refresh()

    def _selected_tag(self) -> int:
        row = self.table.currentRow()
        if row < 0:
            return 0
        item = self.table.item(row, 0)
        try:
            return int(item.text()) if item else 0
        except ValueError:
            return 0

    def _refresh(self) -> None:
        self.table.setRowCount(len(self.records))
        for row, rec in enumerate(sorted(self.records.values(), key=lambda r: r.tag)):
            duration = max(rec.dt * max(rec.npts - 1, 0), 0.0)
            cells = (str(rec.tag), rec.name, rec.format, f"{rec.dt:g}",
                     str(rec.npts), f"{duration:g}", rec.path)
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col in (0, 3, 4, 5):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, col, item)
        if self.records:
            self.table.selectRow(0)
        else:
            self.preview.set_data(0.0, [])

    def _selection_changed(self) -> None:
        tag = self._selected_tag()
        rec = self.records.get(tag)
        if rec is None:
            self.preview.set_data(0.0, [])
            return
        try:
            motion = read_file(rec.path, rec.format, rec.dt)
            self.preview.set_data(motion.dt, motion.values, rec.name)
        except Exception:
            self.preview.set_data(0.0, [])

    def _add(self) -> None:
        dlg = GroundMotionRecordDialog(self.project, None, self)
        if not dlg.exec():
            return
        rec = dlg.spec()
        rec.tag = max(self.records, default=0) + 1
        self.records[rec.tag] = rec
        self._refresh()
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text() == str(rec.tag):
                self.table.selectRow(row)
                break

    def _edit(self) -> None:
        tag = self._selected_tag()
        rec = self.records.get(tag)
        if rec is None:
            return
        dlg = GroundMotionRecordDialog(self.project, rec, self)
        if not dlg.exec():
            return
        updated = dlg.spec()
        updated.tag = tag
        self.records[tag] = updated
        self._refresh()

    def _remove(self) -> None:
        tag = self._selected_tag()
        rec = self.records.get(tag)
        if rec is None:
            return
        if QMessageBox.question(
                self, "Remove record",
                f"Remove '{rec.name}' from the catalog?") != QMessageBox.Yes:
            return
        del self.records[tag]
        self._refresh()
