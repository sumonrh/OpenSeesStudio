"""Results viewer: displacements, reactions, element forces and modes."""

from __future__ import annotations

import csv
import math
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileDialog,
                               QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QTextEdit, QVBoxLayout, QWidget)

from . import theme
from .model import Project, fmt
from .opsgen import ModalResults, StaticResults


def _num(v: float) -> str:
    if abs(v) < 5e-5:
        return "0"
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _table(headers: List[str], rows: List[List], max_height: int = 0) -> QTableWidget:
    t = QTableWidget(len(rows), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().setDefaultSectionSize(23)
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            it = QTableWidgetItem(str(v))
            if c > 1:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t.setItem(r, c, it)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    return t


def _wrap(title: str, widget: QWidget) -> QWidget:
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setContentsMargins(6, 8, 6, 6)
    hint = QLabel(title)
    hint.setStyleSheet(f"color: {theme.MUTED};")
    lay.addWidget(hint)
    lay.addWidget(widget, 1)
    return page


class ResultsDialog(QDialog):
    plotStatic = Signal(str)
    plotMode = Signal(int)

    def __init__(self, project: Project, static: Optional[StaticResults] = None,
                 modal: Optional[ModalResults] = None, scenario: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Analysis Results")
        self.resize(1080, 660)
        self.project = project
        self.static = static
        self.modal = modal
        self.scenario = scenario

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)

        header = QHBoxLayout()
        title = QLabel("Analysis Results")
        title.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {theme.ACCENT_DARK};")
        header.addWidget(title)
        header.addStretch(1)
        if static:
            label = QLabel(f"Static analysis   ·   {scenario}")
        elif modal:
            label = QLabel(f"Modal analysis   ·   {len(modal.modes)} modes")
        else:
            label = QLabel("No results")
        label.setStyleSheet(f"color: {theme.MUTED};")
        header.addWidget(label)
        lay.addLayout(header)

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        if static:
            self._build_static()
        if modal:
            self._build_modal()

        bar = QHBoxLayout()
        bar.addStretch(1)
        if static:
            plot = QPushButton("Show deformed shape")
            plot.clicked.connect(lambda: self.plotStatic.emit(self.scenario))
            bar.addWidget(plot)
        if modal:
            anim = QPushButton("Animate mode shape")
            anim.clicked.connect(self._animate)
            bar.addWidget(anim)
        export = QPushButton("Export CSV…")
        export.clicked.connect(self._export)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bar.addWidget(export)
        bar.addWidget(close)
        lay.addLayout(bar)

    # ------------------------------------------------------------------ static
    def _build_static(self) -> None:
        r = self.static
        assert r is not None

        peak_node = max(r.displacements, key=lambda t: max(abs(v) for v in r.displacements[t]),
                        default=0)
        rows = [
            ["Scenario", r.scenario],
            ["Nodes", len(self.project.nodes)],
            ["Elements", len(self.project.elements)],
            ["Max |displacement|", f"{_num(r.max_disp)} mm  (node {peak_node})"],
        ]
        for i, name in enumerate(("UX", "UY", "UZ", "RX", "RY", "RZ")):
            rows.append([f"Node {peak_node} {name}", _num(r.displacements.get(peak_node, [0] * 6)[i])])
        summary = _table(["Item", "Value"], rows)
        self.tabs.addTab(_wrap("Analysis summary", summary), "Summary")

        drows = []
        for tag in sorted(r.displacements):
            d = r.displacements[tag]
            mag = math.sqrt(sum(v * v for v in d[:3]))
            drows.append([tag, *[_num(v) for v in d], _num(mag)])
        self.tabs.addTab(_wrap("Nodal displacements (mm, rad)",
                               _table(["Node", "UX", "UY", "UZ", "RX", "RY", "RZ", "|U|"], drows)),
                         "Displacements")

        rrows = []
        for tag in sorted(r.reactions):
            d = r.reactions[tag]
            if not any(abs(v) > 1e-9 for v in d):
                continue
            mag = math.sqrt(sum(v * v for v in d[:3]))
            rrows.append([tag, *[_num(v) for v in d], _num(mag)])
        self.tabs.addTab(_wrap("Support reactions (kN, kN·mm)",
                               _table(["Node", "FX", "FY", "FZ", "MX", "MY", "MZ", "|F|"], rrows)),
                         "Reactions")

        frows = []
        for tag in sorted(r.element_forces):
            f = r.element_forces[tag]
            kind = r.element_kind.get(tag, "")
            if kind == "truss":
                if f:
                    frows.append([tag, "Truss", "axial", _num(f[0]), "", "", "", "", ""])
            elif len(f) >= 12:
                frows.append([tag, "Beam", "i", _num(f[0]), _num(f[1]), _num(f[2]),
                              _num(f[3]), _num(f[4]), _num(f[5])])
                frows.append(["", "", "j", _num(f[6]), _num(f[7]), _num(f[8]),
                              _num(f[9]), _num(f[10]), _num(f[11])])
        self.tabs.addTab(_wrap("Element forces (kN, kN·mm) - i and j ends",
                               _table(["Elem", "Type", "End", "N", "Vy", "Vz", "T", "My", "Mz"], frows)),
                         "Element Forces")

        log = QTextEdit()
        log.setReadOnly(True)
        log.setPlainText(r.log or "No solver messages.")
        log.setStyleSheet("font-family: Consolas; font-size: 11px;")
        self.tabs.addTab(log, "Messages")

    # ------------------------------------------------------------------- modal
    def _build_modal(self) -> None:
        m = self.modal
        assert m is not None
        rows = [[x.mode, fmt(x.eigenvalue, 4), fmt(x.period, 5), fmt(x.frequency, 5),
                 fmt(2 * math.pi / max(x.period, 1e-12), 5)] for x in m.modes]
        table = _table(["Mode", "Eigenvalue λ", "Period T (s)", "Frequency f (Hz)", "ω (rad/s)"], rows)
        table.cellDoubleClicked.connect(lambda r, _c: self.plotMode.emit(int(table.item(r, 0).text())))
        self.tabs.addTab(_wrap("Double-click a mode to plot it in the viewport", table), "Modes")

        log = QTextEdit()
        log.setReadOnly(True)
        log.setPlainText(m.log or "No solver messages.")
        log.setStyleSheet("font-family: Consolas; font-size: 11px;")
        self.tabs.addTab(log, "Messages")

    def _animate(self) -> None:
        if not self.modal:
            return
        current = self.tabs.currentIndex()
        mode = 1
        table = self.tabs.widget(current).findChild(QTableWidget)
        if table is not None and table.currentRow() >= 0:
            try:
                mode = int(table.item(table.currentRow(), 0).text())
            except (AttributeError, TypeError, ValueError):
                mode = 1
        self.plotMode.emit(mode)

    # ------------------------------------------------------------------ export
    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export results", "results.csv",
                                              "CSV files (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if self.static:
                w.writerow(["# Static results", self.static.scenario])
                w.writerow(["Node", "UX", "UY", "UZ", "RX", "RY", "RZ"])
                for tag in sorted(self.static.displacements):
                    w.writerow([tag] + self.static.displacements[tag])
                w.writerow([])
                w.writerow(["Node", "FX", "FY", "FZ", "MX", "MY", "MZ"])
                for tag in sorted(self.static.reactions):
                    w.writerow([tag] + self.static.reactions[tag])
                w.writerow([])
                w.writerow(["Element", "Type", "N1", "Vy1", "Vz1", "T1", "My1", "Mz1",
                            "N2", "Vy2", "Vz2", "T2", "My2", "Mz2"])
                for tag in sorted(self.static.element_forces):
                    w.writerow([tag, self.static.element_kind.get(tag, "")] +
                               self.static.element_forces[tag])
            if self.modal:
                w.writerow(["# Modal results"])
                w.writerow(["Mode", "Eigenvalue", "Period", "Frequency"])
                for x in self.modal.modes:
                    w.writerow([x.mode, x.eigenvalue, x.period, x.frequency])
