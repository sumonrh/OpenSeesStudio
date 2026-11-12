"""Hysteresis model diagrams and parameter definitions for plastic hinges."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme
from .units import UNITS

MODEL_LABELS = {
    "Bilinear": "Bilinear — Steel01",
    "Trilinear": "Trilinear — Hysteretic",
    "Takeda": "Takeda-like — Hysteretic",
    "Flag": "Flag-shaped — FlagShape",
}


def _num(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}g}"


class HysteresisPlot(QWidget):
    """Schematic cyclic envelope for the selected hinge law."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model = "Trilinear"
        self.params: dict = {}
        self.setMinimumHeight(300)

    def set_model(self, model: str, params: dict) -> None:
        self.model = model
        self.params = dict(params)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QBrush(QColor("#ffffff")))
        p.setPen(QPen(QColor(theme.BORDER)))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

        left, top, right, bottom = 62, 26, 24, 44
        width = max(self.width() - left - right, 10)
        height = max(self.height() - top - bottom, 10)
        cx = left + width / 2.0
        cy = top + height / 2.0

        post = max(float(self.params.get("post_yield_ratio", 0.02)), 0.0)
        duct = max(float(self.params.get("ductility", 10.0)), 2.0)
        ey = 1.0
        fy = 1.0
        e2 = 3.0
        eu = max(4.0, min(duct, 12.0))
        s2 = fy * (1.0 + post * (e2 - ey))
        su = fy * (1.0 + post * (eu - ey))
        beta = 0.5 if self.model == "Flag" else max(
            0.0, min(1.0, float(self.params.get("beta", 0.4))))
        xmax = max(eu, 2.5)
        ymax = max(su, 1.0)

        def sx(v: float) -> float:
            return cx + v * width * 0.44 / xmax

        def sy(v: float) -> float:
            return cy - v * height * 0.40 / ymax

        p.setPen(QPen(QColor(theme.BORDER), 1.0))
        p.drawLine(QPointF(left, cy), QPointF(left + width, cy))
        p.drawLine(QPointF(cx, top), QPointF(cx, top + height))
        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QPen(QColor(theme.MUTED)))
        p.drawText(QRectF(left, top + height + 8, width, 16), Qt.AlignCenter,
                   "Deformation  ε  (or hinge rotation θ)")
        p.save()
        p.translate(18, top + height / 2)
        p.rotate(-90)
        p.drawText(QRectF(-height / 2, -12, height, 16), Qt.AlignCenter,
                   "Force  σ  (or moment M)")
        p.restore()
        p.setFont(QFont("Segoe UI", 10, QFont.Bold))
        p.setPen(QPen(QColor(theme.ACCENT_DARK)))
        p.drawText(QRectF(left, 2, width, 20), Qt.AlignCenter,
                   MODEL_LABELS.get(self.model, self.model))

        # envelope, positive and negative
        p.setPen(QPen(QColor(theme.ACCENT), 2.4))
        envelope = [
            QPointF(sx(-eu), sy(-su)), QPointF(sx(-e2), sy(-s2)),
            QPointF(sx(-ey), sy(-fy)), QPointF(sx(0), sy(0)),
            QPointF(sx(ey), sy(fy)), QPointF(sx(e2), sy(s2)),
            QPointF(sx(eu), sy(su)),
        ]
        if self.model in ("Bilinear", "Flag"):
            envelope = [
                QPointF(sx(-eu), sy(-su)), QPointF(sx(-ey), sy(-fy)),
                QPointF(sx(0), sy(0)), QPointF(sx(ey), sy(fy)),
                QPointF(sx(eu), sy(su)),
            ]
        p.drawPolyline(QPolygonF(envelope))
        p.setBrush(QBrush(QColor(theme.ACCENT)))
        p.setPen(QPen(QColor("#ffffff"), 1.0))
        for x, y in ((ey, fy), (eu, su)) + (
                ((e2, s2),) if self.model in ("Trilinear", "Takeda") else ()):
            p.drawEllipse(QPointF(sx(x), sy(y)), 3.2, 3.2)
        p.setBrush(Qt.NoBrush)

        # schematic cyclic path
        p.setPen(QPen(QColor(theme.SELECTED), 1.7, Qt.DashLine))
        loop = [
            QPointF(sx(0), sy(0)),
            QPointF(sx(ey), sy(fy)),
        ]
        if self.model in ("Trilinear", "Takeda"):
            loop.append(QPointF(sx(e2), sy(s2)))
        loop.append(QPointF(sx(eu), sy(su)))
        if self.model == "Flag":
            loop += [
                QPointF(sx(eu * 0.50), sy(0.0)),
                QPointF(sx(-ey), sy(-fy)),
                QPointF(sx(-eu), sy(-su)),
                QPointF(sx(-eu * 0.50), sy(0.0)),
                QPointF(sx(ey), sy(fy)),
            ]
        elif self.model == "Takeda":
            pinch = max(0.0, min(1.0, float(self.params.get("pinching", 0.8))))
            loop += [
                QPointF(sx(eu * 0.72), sy(0.0)),
                QPointF(sx(-eu * 0.55 - 0.35 * pinch), sy(0.0)),
                QPointF(sx(-eu), sy(-su)),
                QPointF(sx(-eu * 0.55), sy(0.0)),
                QPointF(sx(ey), sy(fy)),
            ]
        else:
            loop += [
                QPointF(sx(eu * 0.72), sy(0.0)),
                QPointF(sx(-ey), sy(-fy)),
                QPointF(sx(-eu), sy(-su)),
                QPointF(sx(-eu * 0.72), sy(0.0)),
                QPointF(sx(ey), sy(fy)),
            ]
        p.drawPolyline(QPolygonF(loop))

        # parameter labels, kept inside the plot area
        def label(point: QPointF, text: str, dx: float = 7, dy: float = -6) -> None:
            x = point.x() + dx
            y = point.y() + dy
            p.drawText(QPointF(x, y), text)

        p.setFont(QFont("Segoe UI", 8, QFont.Bold))
        p.setPen(QPen(QColor("#c92a2a")))
        fy_pt = QPointF(sx(ey), sy(fy))
        if fy_pt.x() + 30 > left + width:
            label(fy_pt, "fy", -20, -6)
        else:
            label(fy_pt, "fy", 7, -6)
        label(QPointF(sx(ey * 0.45), sy(fy * 0.55)), "E", 8, 2)
        be_pt = QPointF(sx(e2 if self.model in ("Trilinear", "Takeda") else eu * 0.55),
                        sy(s2 if self.model in ("Trilinear", "Takeda") else su * 0.55))
        if be_pt.x() + 30 > left + width:
            label(be_pt, "bE", -28, -6)
        else:
            label(be_pt, "bE", 6, -6)
        if self.model in ("Trilinear", "Takeda"):
            label(QPointF(sx(e2), sy(s2)), "ε2", 6, 12)
            label(QPointF(sx(eu), sy(su)), "εu", -22, -6)
        if self.model == "Takeda":
            label(QPointF(sx(eu * 0.42), sy(-su * 0.12)),
                  f"β = {_num(beta, 3)}", -2, 4)
            label(QPointF(sx(-eu * 0.55), sy(su * 0.55)),
                  f"pinch = {_num(float(self.params.get('pinching', 0.8)), 3)}",
                  -30, 0)
        if self.model == "Flag":
            label(QPointF(sx(eu * 0.50), sy(0.0)),
                  f"β = {_num(beta, 3)}", 8, -8)
            label(QPointF(sx(-eu * 0.45), sy(-su * 0.35)), "Eh = bE", 0, 14)
        p.end()


class HysteresisDialog(QDialog):
    def __init__(self, model: str, params: dict, parent=None,
                 initial_stiffness: Optional[float] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hinge Hysteresis")
        self.resize(820, 900)
        self.model = model
        self.params = dict(params)
        self.E = float(initial_stiffness or 200.0)

        lay = QVBoxLayout(self)
        title = QLabel(MODEL_LABELS.get(model, model))
        title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {theme.ACCENT_DARK};")
        lay.addWidget(title)
        hint = QLabel("Schematic cyclic response. The diagram identifies the "
                      "parameters used by the selected hinge law; it is not a "
                      "calibrated test plot.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{theme.MUTED}; font-size:11px;")
        lay.addWidget(hint)
        self.plot = HysteresisPlot()
        self.plot.setMaximumHeight(430)
        self.plot.set_model(model, self.params)
        lay.addWidget(self.plot, 1)
        self.table = self._build_table()
        self.table.setMinimumHeight(260)
        lay.addWidget(self.table, 0)
        bar = QHBoxLayout()
        bar.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bar.addWidget(close)
        lay.addLayout(bar)

    def _build_table(self) -> QTableWidget:
        fy = float(self.params.get("fy", 0.235))
        post = float(self.params.get("post_yield_ratio", 0.02))
        duct = float(self.params.get("ductility", 10.0))
        pinch = float(self.params.get("pinching", 0.8))
        damage = float(self.params.get("damage", 0.02))
        beta = float(self.params.get("beta", 0.4))
        ey = fy / max(self.E, 1e-9)
        e2 = ey * 3.0
        eu = ey * duct
        s2 = fy * (1.0 + post * 3.0)
        su = fy * (1.0 + post * duct)

        rows = [
            ("E", f"{_num(UNITS.stress(self.E), 4)} {UNITS.stress_unit}",
             "Initial elastic stiffness of the hinge material."),
            ("fy", f"{_num(UNITS.stress(fy), 4)} {UNITS.stress_unit}",
             "Yield strength; the first envelope point."),
            ("εy", f"{_num(ey, 4)}", "Yield strain = fy / E."),
            ("b", f"{_num(post, 4)}",
             "Post-yield stiffness ratio; hardening modulus Eh = b·E."),
        ]
        if self.model in ("Trilinear", "Takeda"):
            rows += [
                ("ε2, f2", f"{_num(e2, 4)}, {_num(UNITS.stress(s2), 4)}",
                 "Second envelope point; defines the trilinear break."),
                ("εu / εy", f"{_num(duct, 4)}",
                 "Ultimate-to-yield strain ductility; sets the last envelope point."),
                ("ffu", f"{_num(UNITS.stress(su), 4)} {UNITS.stress_unit}",
                 "Force at the ultimate strain."),
            ]
        if self.model == "Takeda":
            rows += [
                ("β", f"{_num(beta, 4)}",
                 "Degraded unloading stiffness exponent; the Takeda-like branch."),
                ("pinching", f"{_num(pinch, 4)}",
                 "Pinching factor applied during reloading."),
                ("damage", f"{_num(damage, 4)}",
                 "Strength/stiffness damage from cyclic deformation."),
            ]
        if self.model == "Flag":
            rows += [
                ("β", f"{_num(beta, 4)}",
                 "Flag-shape parameter: 0 gives bilinear elastic, 1 gives "
                 "bilinear hysteretic response."),
                ("Eh", f"{_num(UNITS.stress(self.E * post), 4)} {UNITS.stress_unit}",
                 "Post-yield (flag) stiffness = b·E."),
            ]
        table = QTableWidget(len(rows), 3)
        table.setHorizontalHeaderLabels(["Parameter", "Value", "Definition"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        for r, (name, value, definition) in enumerate(rows):
            table.setItem(r, 0, QTableWidgetItem(name))
            table.setItem(r, 1, QTableWidgetItem(value))
            table.setItem(r, 2, QTableWidgetItem(definition))
        table.setMaximumHeight(300)
        return table
