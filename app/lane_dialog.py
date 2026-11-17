"""Traffic lane definition dialog: start/end points plus lateral shift."""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPen, QPolygonF)
from PySide6.QtWidgets import (QAbstractItemView, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from . import theme
from .dialogs import BaseDialog, hint, spin, title_label
from .live_load import chain_geometry
from .model import Lane, Project


class LanePreview(QWidget):
    """Small plan preview of the bridge, lane centerline and wheel lines."""

    def __init__(self, project: Project, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.start = (0.0, 0.0, 0.0)
        self.end = (1000.0, 0.0, 0.0)
        self.offset = 0.0
        self.points = []
        self.setMinimumHeight(220)

    def set_lane(self, start, end, offset, points=None) -> None:
        self.start = tuple(float(v) for v in start)
        self.end = tuple(float(v) for v in end)
        self.offset = float(offset)
        self.points = [tuple(float(v) for v in p) for p in (points or [])]
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        lane = Lane(1, "", self.start, self.end, self.offset,
                    points=list(self.points))
        pts = [n.xyz for n in self.project.nodes.values()]
        pts += lane.path
        pts += lane.shifted_points()
        for line in lane.wheel_paths(1800.0):
            pts += line
        if not pts:
            p.end()
            return
        xs = [v[0] for v in pts]
        ys = [v[1] for v in pts]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        if x1 - x0 < 1.0:
            x1 = x0 + 1.0
        if y1 - y0 < 1.0:
            y1 = y0 + 1.0
        pad = 24.0
        sx = (self.width() - 2 * pad) / (x1 - x0)
        sy = (self.height() - 2 * pad) / (y1 - y0)
        scale = min(sx, sy)
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2

        def m(x, y):
            return QPointF(self.width() / 2 + (x - cx) * scale,
                           self.height() / 2 - (y - cy) * scale)

        p.setPen(QPen(QColor("#c3cdd9"), 1.0))
        for e in self.project.elements.values():
            if len(e.nodes) < 2:
                continue
            a = self.project.node_xyz(e.nodes[0])
            b = self.project.node_xyz(e.nodes[1])
            p.drawLine(m(a[0], a[1]), m(b[0], b[1]))

        p.setPen(QPen(QColor("#9aa9b9"), 1.1, Qt.DashLine))
        path_pts = [m(pt[0], pt[1]) for pt in lane.path]
        p.drawPolyline(QPolygonF(path_pts))
        shifted = lane.shifted_points()
        p.setPen(QPen(QColor("#e8622c"), 2.4))
        p.drawPolyline(QPolygonF([m(pt[0], pt[1]) for pt in shifted]))
        p.setBrush(QBrush(QColor("#e8622c")))
        p.setPen(Qt.NoPen)
        p.drawEllipse(m(shifted[0][0], shifted[0][1]), 4, 4)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#7c5cbf"), 1.2, Qt.DashLine))
        for line in lane.wheel_paths(1800.0):
            p.drawPolyline(QPolygonF([m(pt[0], pt[1]) for pt in line]))
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QPen(QColor("#b34700")))
        p.drawText(m(shifted[0][0], shifted[0][1]) + QPointF(5, -5), "lane")
        p.setPen(QPen(QColor("#9aa9b9")))
        p.drawText(QRectF(6, 4, self.width() - 12, 18), Qt.AlignLeft,
                   "Plan view: dashed = reference line, orange = shifted lane, "
                   "purple = CL-625 wheel lines")
        p.end()


class LaneSectionPreview(QWidget):
    """Cross-section view of the deck, lane centerline and wheel lines."""

    def __init__(self, project: Project, parent=None) -> None:
        super().__init__(parent)
        self.project = project
        self.start = (0.0, 0.0, 0.0)
        self.end = (0.0, 0.0, 0.0)
        self.offset = 0.0
        self.setMinimumHeight(120)

    def set_lane(self, start, end, offset) -> None:
        self.start = tuple(float(v) for v in start)
        self.end = tuple(float(v) for v in end)
        self.offset = float(offset)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        ys = [n.y for n in self.project.nodes.values()]
        if ys:
            y0, y1 = min(ys), max(ys)
        else:
            y0, y1 = -6000.0, 6000.0
        if y1 - y0 < 6000.0:
            mid = (y0 + y1) / 2
            y0, y1 = mid - 6000.0, mid + 6000.0
        pad = 26.0
        scale = (self.width() - 2 * pad) / (y1 - y0)

        def sx(y):
            return pad + (y - y0) * scale

        deck_y = self.height() * 0.60
        p.setPen(QPen(QColor("#9aa9b9"), 1.0))
        p.drawText(QRectF(6, 4, self.width() - 12, 18), Qt.AlignLeft,
                   "Cross-section at lane start: green = lane centre, "
                   "purple = CL-625 wheel lines")
        p.setPen(QPen(QColor("#41566e"), 9.0))
        p.drawLine(QPointF(pad, deck_y), QPointF(self.width() - pad, deck_y))
        gy = sorted({round(n.y, 6) for n in self.project.nodes.values()})
        p.setPen(QPen(QColor("#41566e"), 2.0))
        for y in gy:
            p.drawLine(QPointF(sx(y), deck_y + 5), QPointF(sx(y), deck_y + 18))
        start = self.start
        end = self.end
        mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2,
               (start[2] + end[2]) / 2)
        lane = Lane(1, "", start, end, self.offset)
        center = lane.shifted_point(mid, 0.0)
        p.setPen(QPen(QColor("#16a34a"), 2.4))
        p.drawLine(QPointF(sx(center[1]), deck_y - 42),
                   QPointF(sx(center[1]), deck_y + 12))
        (l0, l1), (r0, r1) = lane.wheel_lines(1800.0)
        p.setPen(QPen(QColor("#7c5cbf"), 1.4, Qt.DashLine))
        p.drawLine(QPointF(sx(l0[1]), deck_y - 34),
                   QPointF(sx(l0[1]), deck_y + 8))
        p.drawLine(QPointF(sx(r0[1]), deck_y - 34),
                   QPointF(sx(r0[1]), deck_y + 8))
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QPen(QColor("#166534")))
        p.drawText(QPointF(sx(center[1]) + 5, deck_y - 46),
                   f"shift {self.offset/1000:+.2f} m")
        p.setPen(QPen(QColor("#41566e")))
        p.drawText(QRectF(pad, deck_y + 20, self.width() - 2 * pad, 18),
                   Qt.AlignCenter,
                   f"deck width {(y1-y0)/1000:g} m")
        p.end()


class LaneDialog(BaseDialog):
    def __init__(self, project: Project,
                 selected_nodes: Optional[Sequence[int]] = None,
                 selected_elements: Optional[Sequence[int]] = None,
                 parent=None) -> None:
        super().__init__("Traffic Lanes", parent, 860)
        self.project = project
        self.selected_nodes = [int(t) for t in (selected_nodes or [])]
        self.selected_elements = [int(t) for t in (selected_elements or [])]
        self._points: List[Tuple[float, float, float]] = []
        self._elements: List[int] = []
        self._loading = False
        self.lanes: Dict[int, Lane] = {
            tag: Lane.from_dict(lane.to_dict()) for tag, lane in project.lanes.items()}
        self.current_tag: Optional[int] = None
        self.resize(1120, 760)
        self.body.addWidget(hint(
            "Define a straight traffic lane by its start and end points. The "
            "lateral shift moves the lane left of the start -> end direction; "
            "positive is to the left. The live-load truck travels between the "
            "lane ends, with the vehicle allowed to enter and leave."))

        row = QHBoxLayout()
        left = QVBoxLayout()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Tag", "Name", "Start (m)", "End (m)", "Shift (m)"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 42)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 80)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        left.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        add = QPushButton("New lane")
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
        self.name = QLineEdit("Lane 1")
        self.start_x = spin(0.0, -1e9, 1e9, 3, 0.5, "m")
        self.start_y = spin(0.0, -1e9, 1e9, 3, 0.5, "m")
        self.start_z = spin(0.0, -1e9, 1e9, 3, 0.5, "m")
        self.end_x = spin(0.0, -1e9, 1e9, 3, 0.5, "m")
        self.end_y = spin(0.0, -1e9, 1e9, 3, 0.5, "m")
        self.end_z = spin(0.0, -1e9, 1e9, 3, 0.5, "m")
        self.offset = spin(0.0, -1e9, 1e9, 3, 0.25, "m")
        form.addRow("Name", self.name)
        form.addRow("Start X", self.start_x)
        form.addRow("Start Y", self.start_y)
        form.addRow("Start Z", self.start_z)
        form.addRow("End X", self.end_x)
        form.addRow("End Y", self.end_y)
        form.addRow("End Z", self.end_z)
        form.addRow("Lateral shift (+ left)", self.offset)
        right.addLayout(form)

        pick = QPushButton("Use selected nodes (first -> start, last -> end)")
        pick.setEnabled(bool(self.selected_nodes))
        pick.clicked.connect(self._pick_nodes)
        right.addWidget(pick)
        self.chain_label = QLabel("No element chain selected")
        self.chain_label.setWordWrap(True)
        self.chain_label.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        right.addWidget(self.chain_label)
        chain_row = QHBoxLayout()
        chain_btn = QPushButton("Use selected element chain")
        chain_btn.setEnabled(bool(self.selected_elements))
        chain_btn.clicked.connect(self._pick_elements)
        reverse_btn = QPushButton("Reverse direction")
        reverse_btn.clicked.connect(self._reverse_chain)
        chain_row.addWidget(chain_btn)
        chain_row.addWidget(reverse_btn)
        right.addLayout(chain_row)
        apply = QPushButton("Add / update lane")
        apply.setDefault(True)
        apply.clicked.connect(self._apply)
        right.addWidget(apply)
        right.addWidget(title_label("Preview"))
        self.preview = LanePreview(self.project)
        self.preview.setMinimumHeight(160)
        right.addWidget(self.preview, 1)
        self.section_preview = LaneSectionPreview(self.project)
        right.addWidget(self.section_preview)
        row.addLayout(right, 4)
        self.body.addLayout(row, 1)
        self.buttons("Save lanes", "Cancel")

        self.name.textChanged.connect(self._preview)
        for widget in (self.start_x, self.start_y, self.start_z,
                       self.end_x, self.end_y, self.end_z, self.offset):
            widget.valueChanged.connect(self._geometry_edited)
        self._refresh_table()
        self._set_defaults()

    # ------------------------------------------------------------------ data
    def _set_defaults(self) -> None:
        pts = [n.xyz for n in self.project.nodes.values()]
        if pts:
            x0 = min(p[0] for p in pts)
            x1 = max(p[0] for p in pts)
            y = sum(p[1] for p in pts) / len(pts)
        else:
            x0, x1, y = 0.0, 1000.0, 0.0
        self._loading = True
        self.start_x.setValue(x0 / 1000.0)
        self.start_y.setValue(y / 1000.0)
        self.end_x.setValue(x1 / 1000.0)
        self.end_y.setValue(y / 1000.0)
        self._loading = False
        if self.lanes:
            first = sorted(self.lanes)[0]
            self._load_lane(first)
        else:
            self._points = []
            self._elements = []
            self.chain_label.setText("No element chain selected")
            self._preview()

    def _refresh_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for tag in sorted(self.lanes):
            lane = self.lanes[tag]
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(tag), lane.name,
                f"{lane.start[0]/1000:g}, {lane.start[1]/1000:g}",
                f"{lane.end[0]/1000:g}, {lane.end[1]/1000:g}",
                f"{lane.offset/1000:g}",
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, tag)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        if self.lanes and self.current_tag in self.lanes:
            self._select_tag(self.current_tag)

    def _select_tag(self, tag: int) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and int(item.text()) == tag:
                self.table.selectRow(row)
                return

    def _selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        item = self.table.item(rows[0].row(), 0)
        if item:
            self._load_lane(int(item.text()))

    def _load_lane(self, tag: int) -> None:
        lane = self.lanes.get(tag)
        if lane is None:
            return
        self.current_tag = tag
        self._loading = True
        self.name.setText(lane.name)
        self.start_x.setValue(lane.start[0] / 1000.0)
        self.start_y.setValue(lane.start[1] / 1000.0)
        self.start_z.setValue(lane.start[2] / 1000.0)
        self.end_x.setValue(lane.end[0] / 1000.0)
        self.end_y.setValue(lane.end[1] / 1000.0)
        self.end_z.setValue(lane.end[2] / 1000.0)
        self.offset.setValue(lane.offset / 1000.0)
        self._loading = False
        self._points = list(lane.points)
        self._elements = list(lane.element_tags)
        if self._points:
            self.chain_label.setText(
                f"{len(self._elements)} element chain, "
                f"{len(self._points)} vertices, direction "
                f"{self._points[0]} -> {self._points[-1]}")
        else:
            self.chain_label.setText("Straight lane from start/end coordinates")
        self._preview()

    def _new(self) -> None:
        self.current_tag = None
        self.table.clearSelection()
        self._points = []
        self._elements = []
        self.chain_label.setText("No element chain selected")
        self._loading = True
        self.name.setText(f"Lane {len(self.lanes) + 1}")
        self.end_x.setValue(self.start_x.value() + 35.0)
        self._loading = False
        self._preview()

    def _delete(self) -> None:
        if self.current_tag not in self.lanes:
            return
        del self.lanes[self.current_tag]
        self.current_tag = None
        self._refresh_table()
        self._new()

    def _pick_nodes(self) -> None:
        if not self.selected_nodes:
            return
        first = self.project.nodes.get(self.selected_nodes[0])
        last = self.project.nodes.get(self.selected_nodes[-1])
        if first is None or last is None:
            QMessageBox.information(self, "Traffic lane",
                                    "Select at least two nodes in the viewport.")
            return
        self._points = []
        self._elements = []
        self.chain_label.setText("Straight lane from start/end coordinates")
        self._loading = True
        self.start_x.setValue(first.x / 1000.0)
        self.start_y.setValue(first.y / 1000.0)
        self.start_z.setValue(first.z / 1000.0)
        self.end_x.setValue(last.x / 1000.0)
        self.end_y.setValue(last.y / 1000.0)
        self.end_z.setValue(last.z / 1000.0)
        self._loading = False
        self._preview()

    def _pick_elements(self) -> None:
        if not self.selected_elements:
            QMessageBox.information(
                self, "Traffic lane",
                "Select a connected line of beam elements in the viewport.")
            return
        geometry = chain_geometry(self.project, self.selected_elements)
        if geometry is None:
            QMessageBox.information(
                self, "Traffic lane",
                "The selected elements must form a single continuous line "
                "without branches or closed loops.")
            return
        self._points = [tuple(p[1]) for p in geometry["points"]]
        self._elements = list(geometry["element_tags"])
        self._set_chain_fields()
        self.chain_label.setText(
            f"{len(self._elements)} elements, {len(self._points)} vertices; "
            f"start {self._points[0]} -> end {self._points[-1]}")
        self._preview()

    def _reverse_chain(self) -> None:
        if len(self._points) >= 2:
            self._points.reverse()
            self._elements.reverse()
            self._set_chain_fields()
            self.chain_label.setText(
                f"{len(self._elements)} elements, {len(self._points)} vertices; "
                f"start {self._points[0]} -> end {self._points[-1]}")
            self._preview()

    def _set_chain_fields(self) -> None:
        if len(self._points) < 2:
            return
        first, last = self._points[0], self._points[-1]
        self._loading = True
        self.start_x.setValue(first[0] / 1000.0)
        self.start_y.setValue(first[1] / 1000.0)
        self.start_z.setValue(first[2] / 1000.0)
        self.end_x.setValue(last[0] / 1000.0)
        self.end_y.setValue(last[1] / 1000.0)
        self.end_z.setValue(last[2] / 1000.0)
        self._loading = False

    def _geometry_edited(self, *_args) -> None:
        if not self._loading and self._points:
            self._points = []
            self._elements = []
            self.chain_label.setText("Straight lane from start/end coordinates")
        self._preview()

    def _collect(self) -> Optional[Lane]:
        try:
            offset = self.offset.value() * 1000.0
        except ValueError:
            QMessageBox.warning(self, "Traffic lane", "Enter a valid lane shift.")
            return None
        if len(self._points) >= 2:
            points = list(self._points)
            start, end = points[0], points[-1]
            elements = list(self._elements)
        else:
            try:
                start = (self.start_x.value() * 1000.0,
                         self.start_y.value() * 1000.0,
                         self.start_z.value() * 1000.0)
                end = (self.end_x.value() * 1000.0,
                       self.end_y.value() * 1000.0,
                       self.end_z.value() * 1000.0)
            except ValueError:
                QMessageBox.warning(self, "Traffic lane",
                                    "Enter valid lane coordinates.")
                return None
            points = []
            elements = []
        if math.dist(start, end) <= 1e-6:
            QMessageBox.warning(self, "Traffic lane",
                                "Lane start and end must be different points.")
            return None
        tag = self.current_tag if self.current_tag in self.lanes else self.project.next_lane()
        return Lane(tag, self.name.text().strip() or f"Lane {tag}",
                    start, end, offset, 0.0, points, elements)

    def _apply(self) -> None:
        lane = self._collect()
        if lane is None:
            return
        self.lanes[lane.tag] = lane
        self.current_tag = lane.tag
        self._refresh_table()
        self._select_tag(lane.tag)
        self._preview()

    def _preview(self) -> None:
        start = (self.start_x.value() * 1000.0,
                 self.start_y.value() * 1000.0,
                 self.start_z.value() * 1000.0)
        end = (self.end_x.value() * 1000.0,
               self.end_y.value() * 1000.0,
               self.end_z.value() * 1000.0)
        offset = self.offset.value() * 1000.0
        self.preview.set_lane(start, end, offset, self._points)
        self.section_preview.set_lane(start, end, offset)
