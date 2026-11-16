"""Analysis run control: choose available analyses, like SAP2000."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)

from . import theme
from .dialogs import BaseDialog, hint
from .hinge_catalog import (MATERIALS as HINGE_MATERIALS,
                            SPRING_HINGE_MATERIALS)
from .model import Project


def lateral_case(project: Project) -> str:
    """Best available lateral scenario for pushover."""
    configured = str(project.pushover_settings().get("lateral_case") or "")
    if configured in project.scenario_names():
        return configured
    for name in project.scenario_names():
        if any(l.case == name and abs(l.values[0]) > 1e-12
               for l in project.nodal_loads):
            return name
    return ""


def fibre_hinge_elements(project: Project) -> list[int]:
    """Beam elements assigned to a fibre hinge definition."""
    fibre = {h.tag for h in project.hinge_defs.values()
             if h.material in HINGE_MATERIALS
             and HINGE_MATERIALS[h.material].kind == "fiber"}
    return [e for e, h in project.hinge_assignments.items()
            if h in fibre and e in project.elements
            and project.elements[e].kind == "beam"]


def hinge_elements(project: Project) -> list[int]:
    """Beam elements assigned to a fibre or spring hinge definition."""
    usable = {h.tag for h in project.hinge_defs.values()
              if h.material in HINGE_MATERIALS
              and (HINGE_MATERIALS[h.material].kind == "fiber"
                   or (HINGE_MATERIALS[h.material].kind == "spring"
                       and h.material in SPRING_HINGE_MATERIALS
                       and h.curve))}
    return [e for e, h in project.hinge_assignments.items()
            if h in usable and e in project.elements
            and project.elements[e].kind == "beam"]


class RunControlDialog(BaseDialog):
    """Checklist of analyses that the current model can run."""

    def __init__(self, project: Project, static_scenario: str = "",
                 parent=None) -> None:
        super().__init__("Run Analysis", parent, 640)
        self.project = project
        self.static_scenario = static_scenario
        self.rows: dict[str, tuple[QCheckBox, QLabel, bool]] = {}

        self.body.addWidget(hint(
            "Only analyses supported by the current model are enabled. "
            "Selected analyses run in order; the last result stays displayed."))
        self.body.addWidget(self._section("Available analyses"))
        self._add("static", "Static analysis",
                  f"Load case or combination: {static_scenario or 'none'}",
                  bool(project.elements and static_scenario
                       in project.scenario_names()), checked=True)
        has_mass = any(m.rho > 0.0 for m in project.materials.values())
        self._add("modal", "Modal analysis",
                  "Eigenvalue analysis; requires material density for mass",
                  bool(project.elements and has_mass),
                  checked=bool(project.settings.get("modal_configured", False)))
        hinges = hinge_elements(project)
        lateral = lateral_case(project)
        push_reason = (f"{len(hinges)} hinged element(s), lateral case "
                       f"'{lateral}'" if hinges and lateral else
                       "Requires assigned fibre or spring hinges and a lateral load case")
        self._add("pushover", "Pushover analysis", push_reason,
                  bool(project.elements and hinges and lateral),
                  checked=bool(project.settings.get("pushover_configured", False)
                               or (hinges and lateral)))
        case = project.time_history
        th_ok = case.source == "sine"
        if case.source == "file":
            th_ok = bool(case.path and Path(case.path).exists())
        elif case.source == "catalog":
            th_ok = case.record in project.ground_motions
        self._add("time_history", "Time history",
                  f"{case.name}: {case.source}, dt={case.dt:g} s, "
                  f"{case.n_steps or 'full'} steps",
                  bool(project.elements and th_ok),
                  checked=bool(project.settings.get("th_configured", False)
                               or (case.source in ("file", "catalog") and th_ok)))
        case = project.response_spectrum
        rs_ok = (bool(project.elements) and len(case.periods) == len(case.accelerations)
                 and len(case.periods) >= 2)
        self._add("response_spectrum", "Response spectrum",
                  f"{case.name}: {case.combination}, {len(case.periods)} points, "
                  f"{case.n_modes} modes", rs_ok,
                  checked=bool(project.settings.get("rs_configured", False)))

        row = QHBoxLayout()
        all_button = QPushButton("Check available")
        all_button.clicked.connect(lambda: self._set_all(True))
        none_button = QPushButton("Clear")
        none_button.clicked.connect(lambda: self._set_all(False))
        row.addWidget(all_button)
        row.addWidget(none_button)
        row.addStretch(1)
        self.body.addLayout(row)
        self.buttons("Run Selected", "Cancel")

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"font-weight:600; color:{theme.ACCENT_DARK}; font-size:12px;")
        return label

    def _add(self, key: str, label: str, detail: str, enabled: bool,
             checked: bool = False) -> None:
        box = QVBoxLayout()
        box.setSpacing(1)
        check = QCheckBox(label)
        check.setChecked(bool(enabled and checked))
        check.setEnabled(enabled)
        detail_label = QLabel(detail)
        detail_label.setWordWrap(True)
        detail_label.setStyleSheet(
            f"color:{theme.MUTED if enabled else '#a33'}; font-size:11px; "
            "margin-left:18px;")
        box.addWidget(check)
        box.addWidget(detail_label)
        self.body.addLayout(box)
        self.rows[key] = (check, detail_label, enabled)

    def _set_all(self, value: bool) -> None:
        for check, _detail, enabled in self.rows.values():
            check.setChecked(bool(value) and enabled)

    def availability(self) -> dict[str, bool]:
        return {key: enabled for key, (_c, _d, enabled) in self.rows.items()}

    def selected(self) -> list[str]:
        return [key for key, (check, _d, enabled) in self.rows.items()
                if enabled and check.isChecked()]

    def pushover_config(self) -> dict:
        cfg = dict(self.project.pushover_settings())
        cfg["lateral_case"] = lateral_case(self.project)
        if not cfg.get("gravity_case") and "DL" in self.project.cases:
            cfg["gravity_case"] = "DL"
        node = int(cfg.get("control_node") or 0)
        if node not in self.project.nodes:
            node = max(self.project.nodes,
                       key=lambda t: self.project.nodes[t].z, default=0)
        cfg["control_node"] = node
        if float(cfg.get("target_displacement") or 0.0) <= 0.0 and self.project.nodes:
            zs = [n.z for n in self.project.nodes.values()]
            cfg["target_displacement"] = max(0.02 * (max(zs) - min(zs)), 10.0)
        cfg.setdefault("steps", 20)
        return cfg
