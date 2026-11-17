"""Vehicle definition dialog."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme
from .dialogs import BaseDialog, hint, spin, title_label
from .live_load import BCL_SUBDIVISIONS, MAX_AXLES, Axle, preset_axles
from .model import Project, Vehicle


class VehicleDiagram(QWidget):
    """Side elevation with axle loads and spacing dimensions."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: List[Tuple[float, float]] = []
        self.setMinimumHeight(150)

    def set_axles(self, rows: Sequence[Axle]) -> None:
        self.rows = [(float(a.load), float(a.spacing)) for a in rows]
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        if not self.rows:
            p.setPen(QPen(QColor(theme.MUTED)))
            p.drawText(self.rect(), Qt.AlignCenter, "No vehicle defined")
            p.end()
            return
        loads = [r[0] for r in self.rows]
        gaps = [r[1] for r in self.rows[:-1]]
        total = sum(gaps)
        left, right = 58.0, max(self.width() - 58.0, 80.0)
        scale = (right - left) / max(total, 1.0)
        baseline = self.height() * 0.60
        p.setPen(QPen(QColor("#41566e"), 3.0))
        p.drawLine(QPointF(left - 14, baseline), QPointF(right + 14, baseline))
        cumulative = 0.0
        xs = []
        for i, (load, _spacing) in enumerate(self.rows):
            x = left + cumulative * scale
            xs.append(x)
            p.setPen(QPen(QColor("#41566e"), 2.0))
            p.setBrush(QBrush(QColor("#41566e")))
            p.drawEllipse(QPointF(x, baseline + 7), 7.0, 7.0)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(theme.ORANGE), 1.8))
            p.drawLine(QPointF(x, baseline - 4), QPointF(x, baseline - 40))
            p.setBrush(QBrush(QColor(theme.ORANGE)))
            p.drawPolygon(QPolygonF([
                QPointF(x, baseline - 4),
                QPointF(x - 4, baseline - 12),
                QPointF(x + 4, baseline - 12)]))
            p.setBrush(Qt.NoBrush)
            p.setFont(QFont("Segoe UI", 8, QFont.Bold))
            p.setPen(QPen(QColor(theme.ORANGE)))
            label_y = baseline - (58.0 if i % 2 == 0 else 78.0)
            p.drawText(QRectF(x - 30, label_y, 60, 16),
                       Qt.AlignCenter, f"{load:g} kN")
            if i < len(gaps):
                cumulative += gaps[i]
        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QPen(QColor(theme.MUTED)))
        p.drawText(QRectF(left - 40, baseline + 20, 40, 14),
                   Qt.AlignRight, "front")
        p.drawText(QRectF(right + 4, baseline + 20, 50, 14),
                   Qt.AlignLeft, "rear")
        for i, gap in enumerate(gaps):
            x0, x1 = xs[i], xs[i + 1]
            y = baseline + 32
            p.setPen(QPen(QColor("#8ea6bd"), 1.0))
            p.drawLine(QPointF(x0, y), QPointF(x1, y))
            p.drawLine(QPointF(x0, y - 3), QPointF(x0, y + 3))
            p.drawLine(QPointF(x1, y - 3), QPointF(x1, y + 3))
            p.setPen(QPen(QColor("#41566e")))
            label_y = y - 16 if i % 2 == 0 else y + 4
            p.drawText(QRectF((x0 + x1) / 2 - 35, label_y, 70, 14),
                       Qt.AlignCenter, f"{gap:g} m")
        p.end()


class VehicleDialog(BaseDialog):
    def __init__(self, project: Project, parent=None) -> None:
        super().__init__("Vehicles", parent, 860)
        self.project = project
        self.vehicles: Dict[int, Vehicle] = {
            tag: Vehicle.from_dict(vehicle.to_dict())
            for tag, vehicle in project.vehicles.items()}
        self.current_tag: Optional[int] = None
        self.resize(1120, 760)
        self.body.addWidget(hint(
            "Define the moving vehicle by axle loads and spacing. CL-625 and "
            "BCL-625 are fixed presets; Custom supports 1-20 axles. The last "
            "axle spacing is ignored."))
        row = QHBoxLayout()
        left = QVBoxLayout()
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Tag", "Name", "Model", "Axles"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        left.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        add = QPushButton("New vehicle")
        add.clicked.connect(self._new)
        delete = QPushButton("Delete")
        delete.clicked.connect(self._delete)
        buttons.addWidget(add)
        buttons.addWidget(delete)
        buttons.addStretch(1)
        left.addLayout(buttons)
        row.addLayout(left, 3)

        right = QVBoxLayout()
        form = QFormLayout()
        self.name = QLineEdit("CL-625")
        self.model = QComboBox()
        for label, key in (("CL-625", "CL-625"), ("BCL-625", "BCL-625"),
                           ("Custom vehicle / train", "Custom")):
            self.model.addItem(label, key)
        self.bcl_subdivision = QComboBox()
        for value in BCL_SUBDIVISIONS:
            self.bcl_subdivision.addItem(f"{value:g} m", value)
        self.bcl_subdivision.setCurrentIndex(1)
        form.addRow("Name", self.name)
        form.addRow("Model", self.model)
        form.addRow("BCL axle 3-4 subdivision", self.bcl_subdivision)
        self.bcl_label = form.labelForField(self.bcl_subdivision)
        right.addLayout(form)
        right.addWidget(QLabel("Vehicle elevation"))
        self.diagram = VehicleDiagram()
        right.addWidget(self.diagram)
        self.caption = QLabel()
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        right.addWidget(self.caption)
        right.addWidget(QLabel("Axles (front to rear)"))
        self.axle_table = QTableWidget(5, 3)
        self.axle_table.setHorizontalHeaderLabels(
            ["Axle", "Load (kN)", "Spacing to next (m)"])
        self.axle_table.verticalHeader().setVisible(False)
        self.axle_table.horizontalHeader().setStretchLastSection(True)
        self.axle_table.setColumnWidth(0, 60)
        self.axle_table.setColumnWidth(1, 130)
        right.addWidget(self.axle_table, 1)
        axle_row = QHBoxLayout()
        self.add_axle_btn = QPushButton("Add axle")
        self.add_axle_btn.clicked.connect(self._add_axle)
        self.remove_axle_btn = QPushButton("Remove axle")
        self.remove_axle_btn.clicked.connect(self._remove_axle)
        axle_row.addWidget(self.add_axle_btn)
        axle_row.addWidget(self.remove_axle_btn)
        axle_row.addStretch(1)
        right.addLayout(axle_row)
        apply = QPushButton("Add / update vehicle")
        apply.setDefault(True)
        apply.clicked.connect(self._apply)
        right.addWidget(apply)
        row.addLayout(right, 4)
        self.body.addLayout(row, 1)
        self.buttons("Save vehicles", "Cancel")
        self.model.currentIndexChanged.connect(self._model_changed)
        self.axle_table.itemChanged.connect(self._vehicle_changed)
        self.bcl_subdivision.currentIndexChanged.connect(self._vehicle_changed)
        self._refresh_table()
        self._set_defaults()

    def _set_defaults(self) -> None:
        if self.vehicles:
            self._load_vehicle(sorted(self.vehicles)[0])
        else:
            self._new()

    def _refresh_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for tag in sorted(self.vehicles):
            vehicle = self.vehicles[tag]
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [str(tag), vehicle.name, vehicle.model,
                      str(len(vehicle.axles))]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, tag)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        if self.current_tag in self.vehicles:
            self._select_tag(self.current_tag)

    def _select_tag(self, tag: int) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and int(item.text()) == tag:
                self.table.selectRow(row)
                return

    def _selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if rows:
            item = self.table.item(rows[0].row(), 0)
            if item:
                self._load_vehicle(int(item.text()))

    def _load_vehicle(self, tag: int) -> None:
        vehicle = self.vehicles.get(tag)
        if vehicle is None:
            return
        self.current_tag = tag
        self.name.setText(vehicle.name)
        index = self.model.findData(vehicle.model)
        self.model.setCurrentIndex(max(0, index))
        self.bcl_subdivision.setCurrentIndex(max(
            0, self.bcl_subdivision.findData(vehicle.bcl_subdivision)))
        rows = [Axle(a, s) for a, s in vehicle.axles] or preset_axles(
            vehicle.model if vehicle.model in ("CL-625", "BCL-625") else "CL-625")
        self._fill_axles(rows, vehicle.model == "Custom")
        self._sync_controls()

    def _new(self) -> None:
        self.current_tag = None
        self.table.clearSelection()
        self.name.setText(f"Vehicle {len(self.vehicles) + 1}")
        self.model.setCurrentIndex(0)
        self._fill_axles(preset_axles("CL-625"), False)
        self._sync_controls()

    def _delete(self) -> None:
        if self.current_tag not in self.vehicles:
            return
        del self.vehicles[self.current_tag]
        self.current_tag = None
        self._refresh_table()
        self._new()

    def _fill_axles(self, rows: Sequence[Axle], editable: bool) -> None:
        self.axle_table.blockSignals(True)
        self.axle_table.setRowCount(len(rows))
        for i, axle in enumerate(rows):
            self.axle_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            for col, value in ((1, axle.load), (2, axle.spacing)):
                item = QTableWidgetItem(f"{value:g}")
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if not editable:
                    item.setFlags(Qt.ItemIsEnabled)
                self.axle_table.setItem(i, col, item)
            self.axle_table.item(i, 0).setFlags(Qt.ItemIsEnabled)
        self.axle_table.blockSignals(False)
        self.diagram.set_axles(rows)
        self._set_caption()

    def _set_axle_editable(self, editable: bool) -> None:
        for row in range(self.axle_table.rowCount()):
            for col in (1, 2):
                item = self.axle_table.item(row, col)
                if item is None:
                    continue
                flags = Qt.ItemIsEnabled
                if editable:
                    flags |= Qt.ItemIsEditable
                item.setFlags(flags)

    def _model_changed(self, *_args) -> None:
        model = self.model.currentData()
        if model == "Custom":
            self._fill_axles(self._axles(), True)
        else:
            self._fill_axles(preset_axles(str(model)), False)
        self._sync_controls()

    def _sync_controls(self) -> None:
        model = self.model.currentData()
        custom = model == "Custom"
        bcl = model == "BCL-625"
        self.bcl_subdivision.setVisible(bcl)
        self.bcl_subdivision.setEnabled(bcl)
        if self.bcl_label is not None:
            self.bcl_label.setVisible(bcl)
        self.add_axle_btn.setEnabled(custom)
        self.remove_axle_btn.setEnabled(custom)
        self._set_axle_editable(custom)
        self._set_caption()

    def _set_caption(self) -> None:
        model = self.model.currentData()
        if model == "CL-625":
            self.caption.setText(
                "CL-625: five fixed axles, 50 + 125 + 125 + 175 + 150 kN.")
        elif model == "BCL-625":
            self.caption.setText(
                "BCL-625: five axles; axle 3-4 gap is enveloped from 6.6 m to "
                "18 m. The schematic shows the 6.6 m base gap.")
        else:
            self.caption.setText("Custom vehicle: edit loads and spacing below.")

    def _vehicle_changed(self, *_args) -> None:
        model = self.model.currentData()
        if model == "Custom":
            self.diagram.set_axles(self._axles())
        elif model == "BCL-625":
            self.diagram.set_axles(preset_axles("BCL-625"))
        else:
            self.diagram.set_axles(preset_axles("CL-625"))

    def _axles(self) -> List[Axle]:
        rows = []
        for row in range(self.axle_table.rowCount()):
            try:
                load = float(self.axle_table.item(row, 1).text())
                spacing = float(self.axle_table.item(row, 2).text())
            except (AttributeError, ValueError):
                load, spacing = 0.0, 0.0
            rows.append(Axle(load, spacing))
        return rows

    def _add_axle(self) -> None:
        if self.model.currentData() != "Custom":
            return
        if self.axle_table.rowCount() >= MAX_AXLES:
            QMessageBox.information(self, "Vehicles", f"At most {MAX_AXLES} axles.")
            return
        row = self.axle_table.rowCount()
        self.axle_table.insertRow(row)
        self.axle_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self.axle_table.setItem(row, 1, QTableWidgetItem("50"))
        self.axle_table.setItem(row, 2, QTableWidgetItem("0"))
        self._set_axle_editable(True)
        self._vehicle_changed()

    def _remove_axle(self) -> None:
        if self.model.currentData() != "Custom":
            return
        row = self.axle_table.currentRow()
        if row >= 0 and self.axle_table.rowCount() > 1:
            self.axle_table.removeRow(row)
            for i in range(self.axle_table.rowCount()):
                self.axle_table.item(i, 0).setText(str(i + 1))
            self._vehicle_changed()

    def _apply(self) -> None:
        model = str(self.model.currentData())
        axles = self._axles() if model == "Custom" else [
            (a.load, a.spacing) for a in preset_axles(model)]
        if not axles:
            QMessageBox.warning(self, "Vehicles", "Define at least one axle.")
            return
        tag = self.current_tag if self.current_tag in self.vehicles else self.project.next_vehicle()
        vehicle = Vehicle(
            tag, self.name.text().strip() or f"Vehicle {tag}", model, axles,
            float(self.bcl_subdivision.currentData()))
        self.vehicles[tag] = vehicle
        self.current_tag = tag
        self._refresh_table()
        self._select_tag(tag)
