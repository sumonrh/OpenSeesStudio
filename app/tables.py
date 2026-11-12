"""Spreadsheet-style model tables."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog,
                               QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from . import theme
from .model import (Element, ElementLoad, LoadCase, LoadCombination, Material,
                    NodalLoad, Node, Project, SECTION_SHAPES, Section, fmt)
from .units import UNITS


def _load_values(l: ElementLoad):
    """Element-load values in the current display units."""
    if l.kind == "point":
        return UNITS.force(l.value), UNITS.force(l.value2)
    return UNITS.dist(l.value), UNITS.dist(l.value2)


def _cell(text) -> QTableWidgetItem:
    it = QTableWidgetItem(str(text))
    return it


class EditableTable(QTableWidget):
    """QTableWidget with Excel-compatible Ctrl+C / Ctrl+V."""

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.Copy):
            self.copy_selection()
            event.accept()
            return
        if event.matches(QKeySequence.Paste):
            self.paste_clipboard()
            event.accept()
            return
        super().keyPressEvent(event)

    def copy_selection(self) -> None:
        ranges = self.selectedRanges()
        if ranges:
            r0 = min(r.topRow() for r in ranges)
            r1 = max(r.bottomRow() for r in ranges)
            c0 = min(r.leftColumn() for r in ranges)
            c1 = max(r.rightColumn() for r in ranges)
        else:
            r0 = r1 = self.currentRow()
            c0 = c1 = self.currentColumn()
        if r0 < 0 or c0 < 0:
            return
        lines = []
        for r in range(r0, r1 + 1):
            row = []
            for c in range(c0, c1 + 1):
                item = self.item(r, c)
                row.append(item.text() if item else "")
            lines.append("\t".join(row))
        QApplication.clipboard().setText("\n".join(lines))

    def paste_clipboard(self) -> None:
        text = QApplication.clipboard().text()
        if not text:
            return
        rows = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if rows and rows[-1] == "":
            rows.pop()
        if not rows:
            return
        ranges = self.selectedRanges()
        if ranges:
            r0 = min(r.topRow() for r in ranges)
            c0 = min(r.leftColumn() for r in ranges)
        else:
            r0, c0 = self.currentRow(), self.currentColumn()
        r0 = max(r0, 0)
        c0 = max(c0, 0)
        for i, line in enumerate(rows):
            r = r0 + i
            if r >= self.rowCount():
                self.insertRow(r)
            for j, value in enumerate(line.split("\t")):
                c = c0 + j
                if c >= self.columnCount():
                    break
                item = self.item(r, c)
                if item is None:
                    self.setItem(r, c, _cell(value))
                else:
                    item.setText(value)
        self.setCurrentCell(r0, c0)


class TablePage(QWidget):
    def __init__(self, headers: List[str], rows: List[List], widths: Optional[Dict[int, int]] = None,
                 new_row=None) -> None:
        super().__init__()
        self._new_row = new_row
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.table = EditableTable(len(rows), len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.verticalHeader().setDefaultSectionSize(24)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        for i, h in enumerate(headers):
            self.table.setColumnWidth(i, (widths or {}).get(i, max(64, 9 * len(h) + 22)))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self.table.setItem(r, c, _cell(val))
        lay.addWidget(self.table)

        bar = QHBoxLayout()
        add = QPushButton("Add row")
        add.clicked.connect(self._add)
        dup = QPushButton("Duplicate row")
        dup.clicked.connect(self._dup)
        rem = QPushButton("Delete rows")
        rem.clicked.connect(self._del)
        copy = QPushButton("Copy")
        copy.setToolTip("Copy selected cells as tab-separated text (Ctrl+C)")
        copy.clicked.connect(self.table.copy_selection)
        paste = QPushButton("Paste")
        paste.setToolTip("Paste cells copied from Excel (Ctrl+V)")
        paste.clicked.connect(self.table.paste_clipboard)
        bar.addWidget(add); bar.addWidget(dup); bar.addWidget(rem)
        bar.addWidget(copy); bar.addWidget(paste); bar.addStretch(1)
        self.count = QLabel()
        bar.addWidget(self.count)
        lay.addLayout(bar)
        self.table.itemChanged.connect(lambda *_: self._update_count())
        self._update_count()

    def _update_count(self) -> None:
        self.count.setText(f"{self.table.rowCount()} rows")
        self.count.setStyleSheet(f"color: {theme.MUTED};")

    def _add(self) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        if self._new_row:
            for c, v in enumerate(self._new_row(self.table)):
                self.table.setItem(r, c, _cell(v))
        self.table.scrollToBottom()

    def _dup(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            return
        vals = [self.table.item(r, c).text() if self.table.item(r, c) else ""
                for c in range(self.table.columnCount())]
        nr = self.table.rowCount()
        self.table.insertRow(nr)
        for c, v in enumerate(vals):
            self.table.setItem(nr, c, _cell(v))

    def _del(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        for r in rows:
            self.table.removeRow(r)

    def rows(self) -> List[List[str]]:
        out = []
        for r in range(self.table.rowCount()):
            row = []
            for c in range(self.table.columnCount()):
                it = self.table.item(r, c)
                row.append(it.text().strip() if it else "")
            if any(row):
                out.append(row)
        return out


# --------------------------------------------------------------------------- #
class TablesDialog(QDialog):
    def __init__(self, project: Project, parent=None, case_filter: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Model Tables")
        self.resize(1120, 680)
        self.project = project
        self.result_project: Optional[Project] = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        top = QHBoxLayout()
        top.addWidget(QLabel("Load case filter"))
        self.case_filter = QComboBox()
        self.case_filter.addItem("All cases", "")
        for case in project.cases:
            self.case_filter.addItem(case, case)
        self.case_filter.setMinimumWidth(170)
        self.case_filter.currentIndexChanged.connect(self._filter_changed)
        top.addWidget(self.case_filter)
        top.addStretch(1)
        lay.addLayout(top)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        self._build_pages()

        index = self.case_filter.findData(case_filter)
        if index >= 0:
            self.case_filter.blockSignals(True)
            self.case_filter.setCurrentIndex(index)
            self.case_filter.blockSignals(False)
        self._filter_changed()

        bar = QHBoxLayout()
        info = QLabel(f"Display units: {UNITS.force_name} · {UNITS.length_name}. "
                      "Edit cells directly. 'Apply' validates and rebuilds the model.")
        info.setStyleSheet(f"color: {theme.MUTED};")
        bar.addWidget(info)
        bar.addStretch(1)
        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self._reload)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        apply_btn = QPushButton("Apply")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._apply)
        bar.addWidget(reload_btn); bar.addWidget(close); bar.addWidget(apply_btn)
        lay.addLayout(bar)

    # ------------------------------------------------------------------ pages
    def _build_pages(self) -> None:
        p = self.project
        u = UNITS
        self.page_nodes = TablePage(
            ["Tag", "X", "Y", "Z"],
            [[n.tag, fmt(u.length(n.x), u.length_decimals), fmt(u.length(n.y), u.length_decimals),
              fmt(u.length(n.z), u.length_decimals)]
             for n in p.nodes.values()],
            {0: 70}, new_row=lambda t: [max((int(t.item(r, 0).text()) for r in range(t.rowCount())
                                             if t.item(r, 0)), default=0) + 1, "0", "0", "0"])
        self.page_supports = TablePage(
            ["Node", "DX", "DY", "DZ", "RX", "RY", "RZ"],
            [[n.tag] + [1 if b else 0 for b in n.support] for n in p.nodes.values()],
            {0: 70})
        self.page_elements = TablePage(
            ["Tag", "Type", "Node1", "Node2", "Node3", "Node4", "Material", "Section", "Thickness"],
            [[e.tag, e.kind, *[e.nodes[i] if i < len(e.nodes) else "" for i in range(4)],
              e.mat, e.sec, fmt(u.length(e.thickness), u.length_decimals)]
             for e in p.elements.values()],
            {0: 60, 1: 80}, new_row=lambda t: [max((int(t.item(r, 0).text()) for r in range(t.rowCount())
                                                    if t.item(r, 0)), default=0) + 1, "beam", "", "", "", "", 1, 1,
                                               fmt(u.length(100.0), u.length_decimals)])
        self.page_materials = TablePage(
            ["Tag", "Name", "Type", "E", "Nu", "Density", "fy", "b"],
            [[m.tag, m.name, m.kind, fmt(u.stress(m.E), 5), fmt(m.nu, 3),
              fmt(u.density(m.rho), 6), fmt(u.stress(m.fy), 5), fmt(m.b, 4)]
             for m in p.materials.values()],
            {1: 160, 2: 100}, new_row=lambda t: [max((int(t.item(r, 0).text()) for r in range(t.rowCount())
                                                      if t.item(r, 0)), default=0) + 1,
                                                 "New material", "Elastic", fmt(u.stress(200.0), 5), 0.3,
                                                 fmt(u.density(7.85e-9), 6), fmt(u.stress(0.235), 5), 0.01])
        self.page_sections = TablePage(
            ["Tag", "Name", "Shape", "b", "h", "d", "t", "tw", "tf", "A", "Iy", "Iz", "J"],
            [[s.tag, s.name, s.shape, fmt(u.length(s.b), u.length_decimals),
              fmt(u.length(s.h), u.length_decimals), fmt(u.length(s.d), u.length_decimals),
              fmt(u.length(s.t), u.length_decimals), fmt(u.length(s.tw), u.length_decimals),
              fmt(u.length(s.tf), u.length_decimals), fmt(u.area(s.A), 6),
              fmt(u.inertia(s.Iy), 9), fmt(u.inertia(s.Iz), 9), fmt(u.inertia(s.J), 9)]
             for s in p.sections.values()],
            {1: 150, 2: 90})
        self.page_cases = TablePage(
            ["Name", "Type", "Note"],
            [[c.name, c.kind, c.note] for c in p.cases.values()],
            {0: 120, 1: 110}, new_row=lambda t: [f"LC{t.rowCount() + 1}", "Other", ""])
        self.page_nodal = TablePage(
            ["Tag", "Node", "Case", "FX", "FY", "FZ", "MX", "MY", "MZ"],
            [[l.tag, l.node, l.case] + [fmt(v, 3) for v in
                                        [u.force(x) for x in l.values[:3]]] +
                                       [fmt(v, 6) for v in
                                        [u.moment(x) for x in l.values[3:]]]
             for l in p.nodal_loads],
            {0: 60, 2: 100},
            new_row=lambda t: [self._next_load_tag(), next(iter(p.nodes), 1),
                               self._default_case(), "0", "0", "0", "0", "0", "0"])
        self.page_eleload = TablePage(
            ["Tag", "Element", "Case", "Type", "Direction", "w1 / P", "w2", "x/L"],
            [[l.tag, l.elem, l.case, "Trapezoid" if l.trapezoid else l.kind.capitalize(),
              l.direction, *[fmt(v, 5) for v in _load_values(l)], fmt(l.position, 3)]
             for l in p.elem_loads],
            {2: 100, 3: 90, 4: 100},
            new_row=lambda t: [self._next_load_tag(), next(iter(p.elements), 1),
                               self._default_case(), "Uniform", "local-z",
                               "0", "0", "0.5"])
        self.page_combos = TablePage(
            ["Name", "Type", "Factors (case:factor, ...)"],
            [[c.name, c.kind, ", ".join(f"{n}:{fmt(f, 3)}" for n, f in c.factors)]
             for c in p.combos.values()],
            {0: 130, 1: 90, 2: 420}, new_row=lambda t: [f"COMB{t.rowCount() + 1}", "Add", ""])

        for title, page in (("Nodes", self.page_nodes), ("Supports", self.page_supports),
                            ("Elements", self.page_elements), ("Materials", self.page_materials),
                            ("Sections", self.page_sections), ("Load Cases", self.page_cases),
                            ("Nodal Loads", self.page_nodal), ("Element Loads", self.page_eleload),
                            ("Combinations", self.page_combos)):
            self.tabs.addTab(page, title)

    def _filter_changed(self, *_args) -> None:
        case = self.case_filter.currentData()
        for page in (self.page_nodal, self.page_eleload):
            for row in range(page.table.rowCount()):
                item = page.table.item(row, 2)
                hidden = bool(case) and (item is None or item.text().strip() != case)
                page.table.setRowHidden(row, hidden)

    def _default_case(self) -> str:
        return self.case_filter.currentData() or next(iter(self.project.cases), "DL")

    def _next_load_tag(self) -> int:
        tags = [load.tag for load in self.project.nodal_loads]
        tags += [load.tag for load in self.project.elem_loads]
        for page in (self.page_nodal, self.page_eleload):
            for row in range(page.table.rowCount()):
                item = page.table.item(row, 0)
                if item is None:
                    continue
                try:
                    tags.append(int(float(item.text())))
                except (TypeError, ValueError):
                    pass
        return max(tags, default=0) + 1

    def _reload(self) -> None:
        while self.tabs.count():
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            w.deleteLater()
        self._build_pages()

    # ------------------------------------------------------------------ apply
    def _apply(self) -> None:
        try:
            self.result_project = self._collect()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid table data", str(exc))
            return
        self.accept()

    def _collect(self) -> Project:
        base = self.project
        p = base.clone()
        errors: List[str] = []

        def num(text: str, where: str, default: float = 0.0) -> float:
            try:
                return float(text) if text not in ("", "-") else default
            except ValueError:
                errors.append(f"{where}: '{text}' is not a number")
                return default

        def tag(text: str, where: str) -> int:
            try:
                v = int(float(text))
                if v <= 0:
                    raise ValueError
                return v
            except ValueError:
                errors.append(f"{where}: '{text}' is not a positive integer tag")
                return 0

        # ---- nodes -----------------------------------------------------
        nodes: Dict[int, Node] = {}
        for row in self.page_nodes.rows():
            t = tag(row[0], "Nodes")
            if t in nodes:
                errors.append(f"Nodes: duplicate tag {t}")
            old = base.nodes.get(t)
            nodes[t] = Node(t, UNITS.length_base(num(row[1], f"Node {t} X")),
                            UNITS.length_base(num(row[2], f"Node {t} Y")),
                            UNITS.length_base(num(row[3], f"Node {t} Z")),
                            list(old.support) if old else [False] * 6,
                            list(old.spring) if old else [0.0] * 6)
        if not nodes:
            errors.append("Nodes: the model needs at least one node")

        # ---- supports --------------------------------------------------
        for row in self.page_supports.rows():
            t = tag(row[0], "Supports")
            if t not in nodes:
                errors.append(f"Supports: node {t} does not exist")
                continue
            flags = []
            for text in row[1:7]:
                flags.append(text.strip().lower() in ("1", "y", "yes", "true"))
            nodes[t].support = flags

        # ---- materials -------------------------------------------------
        materials: Dict[int, Material] = {}
        for row in self.page_materials.rows():
            t = tag(row[0], "Materials")
            if t in materials:
                errors.append(f"Materials: duplicate tag {t}")
            m = materials.setdefault(t, Material(t))
            m.name = row[1] or f"Material {t}"
            m.kind = row[2] if row[2] in ("Elastic", "ElasticPP", "Steel02", "Concrete02") else "Elastic"
            m.E = UNITS.stress_base(num(row[3], f"Material {t} E"))
            m.nu = num(row[4], f"Material {t} Nu", 0.3)
            m.rho = UNITS.density_base(num(row[5], f"Material {t} density"))
            m.fy = UNITS.stress_base(num(row[6], f"Material {t} fy"))
            m.b = num(row[7], f"Material {t} b", 0.01)
        if not materials:
            materials[1] = Material(1, "Steel", "Elastic", 200.0, 0.3, 7.85e-9)

        # ---- sections --------------------------------------------------
        sections: Dict[int, Section] = {}
        for row in self.page_sections.rows():
            t = tag(row[0], "Sections")
            if t in sections:
                errors.append(f"Sections: duplicate tag {t}")
            old = base.sections.get(t)
            s = sections.setdefault(t, Section(t))
            s.name = row[1] or f"Section {t}"
            s.shape = row[2] if row[2] in SECTION_SHAPES else "Rectangle"
            s.b = UNITS.length_base(num(row[3], f"Section {t} b", 300))
            s.h = UNITS.length_base(num(row[4], f"Section {t} h", 600))
            s.d = UNITS.length_base(num(row[5], f"Section {t} d", 400))
            s.t = UNITS.length_base(num(row[6], f"Section {t} t", 12))
            s.tw = UNITS.length_base(num(row[7], f"Section {t} tw", 10))
            s.tf = UNITS.length_base(num(row[8], f"Section {t} tf", 15))
            if s.shape == "User":
                s.A = UNITS.area_base(num(row[9], f"Section {t} A", 1))
                s.Iy = UNITS.inertia_base(num(row[10], f"Section {t} Iy", 1))
                s.Iz = UNITS.inertia_base(num(row[11], f"Section {t} Iz", 1))
                s.J = UNITS.inertia_base(num(row[12], f"Section {t} J", 1))
                s.catalog, s.designation, s.family = "Custom", "", ""
            elif (old is not None and old.is_standard and old.shape == s.shape
                  and all(abs(a - b) < 0.01 for a, b in
                          ((old.b, s.b), (old.h, s.h), (old.d, s.d),
                           (old.t, s.t), (old.tw, s.tw), (old.tf, s.tf)))):
                s.A, s.Iy, s.Iz, s.J = old.A, old.Iy, old.Iz, old.J
                s.catalog, s.designation, s.family = (old.catalog, old.designation,
                                                      old.family)
                s.cy, s.cz = old.cy, old.cz
            else:
                s.catalog, s.designation, s.family = "Custom", "", ""
                s.compute()
        if not sections:
            s = Section(1, "Section 1", "Rectangle", 300, 600, 400, 12)
            s.compute()
            sections[1] = s

        # ---- elements --------------------------------------------------
        elements: Dict[int, Element] = {}
        for row in self.page_elements.rows():
            t = tag(row[0], "Elements")
            if t in elements:
                errors.append(f"Elements: duplicate tag {t}")
            kind = (row[1] or "beam").strip().lower()
            if kind not in ("beam", "truss", "shell"):
                errors.append(f"Element {t}: type must be beam, truss or shell")
                kind = "beam"
            ns = []
            for text in row[2:6]:
                if text.strip():
                    ns.append(tag(text, f"Element {t} node"))
            need = 4 if kind == "shell" else 2
            if len(ns) != need:
                errors.append(f"Element {t}: {kind} needs {need} nodes, got {len(ns)}")
            for nt in ns:
                if nt not in nodes:
                    errors.append(f"Element {t}: node {nt} does not exist")
            mt = tag(row[6], f"Element {t} material")
            st = tag(row[7], f"Element {t} section")
            if mt not in materials:
                errors.append(f"Element {t}: material {mt} does not exist")
            if st not in sections:
                errors.append(f"Element {t}: section {st} does not exist")
            old = base.elements.get(t)
            elements[t] = Element(t, kind, ns, mt, st,
                                  list(old.vecxz) if (old and old.vecxz) else None,
                                  UNITS.length_base(num(row[8], f"Element {t} thickness", 100.0)),
                                  old.group if old else "")

        # ---- cases -----------------------------------------------------
        cases: Dict[str, LoadCase] = {}
        for row in self.page_cases.rows():
            name = row[0]
            if not name:
                continue
            if name in cases:
                errors.append(f"Load cases: duplicate name '{name}'")
            cases[name] = LoadCase(name, row[1] if row[1] else "Other", row[2] if len(row) > 2 else "")
        if not cases:
            cases["DL"] = LoadCase("DL", "Dead")

        # ---- nodal loads ----------------------------------------------
        nodal: List[NodalLoad] = []
        for row in self.page_nodal.rows():
            t = tag(row[0], "Nodal loads")
            nt = tag(row[1], f"Nodal load {t} node")
            if nt not in nodes:
                errors.append(f"Nodal load {t}: node {nt} does not exist")
            if row[2] not in cases:
                errors.append(f"Nodal load {t}: unknown load case '{row[2]}'")
            vals = [num(v, f"Nodal load {t} value") for v in row[3:9]]
            vals = ([UNITS.force_base(v) for v in vals[:3]] +
                    [UNITS.moment_base(v) for v in vals[3:]])
            nodal.append(NodalLoad(t, nt, row[2], vals))

        # ---- element loads --------------------------------------------
        eleloads: List[ElementLoad] = []
        for row in self.page_eleload.rows():
            t = tag(row[0], "Element loads")
            et = tag(row[1], f"Element load {t} element")
            if et not in elements:
                errors.append(f"Element load {t}: element {et} does not exist")
            if row[2] not in cases:
                errors.append(f"Element load {t}: unknown load case '{row[2]}'")
            typ = row[3].strip().lower()
            kind = "point" if typ.startswith("point") else "uniform"
            v1 = num(row[5], f"Element load {t} value")
            v2 = num(row[6], f"Element load {t} w2", 0.0)
            if kind == "point":
                v1, v2 = UNITS.force_base(v1), UNITS.force_base(v2)
            else:
                v1, v2 = UNITS.dist_base(v1), UNITS.dist_base(v2)
            l = ElementLoad(t, et, row[2], kind, row[4] or "local-z",
                            v1, v2,
                            num(row[7], f"Element load {t} x/L", 0.5),
                            typ.startswith("trap"))
            eleloads.append(l)

        # ---- combinations ---------------------------------------------
        combos: Dict[str, LoadCombination] = {}
        for row in self.page_combos.rows():
            name = row[0]
            if not name:
                continue
            if name in combos:
                errors.append(f"Combinations: duplicate name '{name}'")
            factors: List[Tuple[str, float]] = []
            for part in (row[2] if len(row) > 2 else "").replace(";", ",").split(","):
                part = part.strip()
                if not part:
                    continue
                if ":" not in part:
                    errors.append(f"Combination {name}: '{part}' must look like CASE:factor")
                    continue
                cname, ftext = part.split(":", 1)
                cname = cname.strip()
                if cname not in cases:
                    errors.append(f"Combination {name}: unknown case '{cname}'")
                factors.append((cname, num(ftext, f"Combination {name} factor", 1.0)))
            combos[name] = LoadCombination(name, factors, row[1] or "Add")

        if errors:
            raise ValueError("\n".join(errors[:14]) +
                             ("\n…" if len(errors) > 14 else ""))

        p.nodes = nodes
        p.materials = materials
        p.sections = sections
        p.elements = elements
        p.cases = cases
        p.nodal_loads = nodal
        p.elem_loads = eleloads
        p.combos = combos
        p.hinge_assignments = {
            e: h for e, h in p.hinge_assignments.items()
            if e in p.elements and h in p.hinge_defs}
        return p
