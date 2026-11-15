"""Dialogs for bearing, isolator and damper elements."""

from __future__ import annotations

from typing import List

from PySide6.QtWidgets import (QComboBox, QFormLayout, QGroupBox, QLineEdit)

from .dialogs import BaseDialog, hint, int_spin, parse_tags, spin, title_label
from .model import Project
from .units import UNITS

DEVICE_CHOICES = (
    ("Elastomeric bearing (elastomericBearingBoucWen)", "bearing"),
    ("Lead-rubber isolator (LeadRubberX)", "isolator"),
    ("Viscous damper (twoNodeLink + ViscousDamper)", "damper_viscous"),
    ("Bilinear oil damper (twoNodeLink + BilinearOilDamper)", "damper_oil"),
)


def _length(value: float, step: float = 10.0) -> object:
    return spin(UNITS.length(value), 0.0, UNITS.length(1e12),
                UNITS.length_decimals, UNITS.length(step), UNITS.length_unit)


def _force(value: float, step: float = 10.0) -> object:
    return spin(UNITS.force(value), 0.0, UNITS.force(1e15), 4,
                UNITS.force(step), UNITS.force_unit)


def _stiffness(value: float, step: float = 10.0) -> object:
    return spin(UNITS.dist(value), 0.0, UNITS.dist(1e15), 6,
                UNITS.dist(step), UNITS.dist_unit)


def _stress(value: float, step: float = 0.001) -> object:
    return spin(UNITS.stress(value), 0.0, UNITS.stress(1e9), 6,
                UNITS.stress(step), UNITS.stress_unit)


def _moment(value: float, step: float = 1e6) -> object:
    return spin(UNITS.moment(value), 0.0, UNITS.moment(1e18), 4,
                UNITS.moment(step), f"{UNITS.moment_unit}/rad")


class DeviceDialog(BaseDialog):
    """Create a two-node bearing, isolator or damper element."""

    def __init__(self, project: Project, selected_nodes: List[int],
                 preset: str = "bearing", parent=None) -> None:
        super().__init__("Create Device Element", parent, 560)
        self.project = project

        self.body.addWidget(title_label("Device"))
        self.kind = QComboBox()
        for label, key in DEVICE_CHOICES:
            self.kind.addItem(label, key)
        index = self.kind.findData("damper_viscous" if preset == "damper" else preset)
        if index >= 0:
            self.kind.setCurrentIndex(index)
        self.kind.currentIndexChanged.connect(self._sync)
        self.body.addWidget(self.kind)

        form = QFormLayout()
        self.nodes = QLineEdit(", ".join(str(t) for t in selected_nodes))
        self.nodes.setPlaceholderText("e.g. 5, 6")
        form.addRow("Node i, j", self.nodes)
        self.body.addLayout(form)
        self.body.addWidget(hint(
            "The two nodes define the device axis. A bearing or isolator normally "
            "connects a foundation node to the supported node; a damper normally "
            "connects two structure nodes. Zero-length devices are allowed."))

        # ---- elastomeric bearing --------------------------------------
        self.bearing_box = QGroupBox("Elastomeric bearing (Bouc-Wen shear)")
        bf = QFormLayout(self.bearing_box)
        self.b_kinit = _stiffness(2.0, 0.5)
        self.b_qd = _force(100.0, 10.0)
        self.b_alpha1 = spin(0.02, 0.0, 1.0, 5, 0.01)
        self.b_alpha2 = spin(0.05, 0.0, 1.0, 5, 0.01)
        self.b_mu = spin(2.0, 0.1, 100.0, 3, 0.1)
        self.b_eta = spin(1.0, 0.01, 100.0, 3, 0.1)
        self.b_beta = spin(0.5, 0.0, 10.0, 3, 0.1)
        self.b_gamma = spin(0.5, 0.0, 10.0, 3, 0.1)
        self.b_kv = _stiffness(1000.0, 10.0)
        self.b_kt = _moment(1.0e6, 1.0e5)
        self.b_kry = _moment(1.0e8, 1.0e6)
        self.b_krz = _moment(1.0e8, 1.0e6)
        bf.addRow("Initial shear stiffness", self.b_kinit)
        bf.addRow("Characteristic strength qd", self.b_qd)
        bf.addRow("Post-yield ratio alpha1", self.b_alpha1)
        bf.addRow("Hardening ratio alpha2", self.b_alpha2)
        bf.addRow("Hardening exponent mu", self.b_mu)
        bf.addRow("Yield exponent eta", self.b_eta)
        bf.addRow("Hysteresis beta", self.b_beta)
        bf.addRow("Hysteresis gamma", self.b_gamma)
        bf.addRow("Vertical stiffness Kv", self.b_kv)
        bf.addRow("Torsional stiffness Kt", self.b_kt)
        bf.addRow("Rotational stiffness Kry", self.b_kry)
        bf.addRow("Rotational stiffness Krz", self.b_krz)
        self.body.addWidget(self.bearing_box)

        # ---- lead-rubber isolator -------------------------------------
        self.isolator_box = QGroupBox("Lead-rubber isolator (LeadRubberX)")
        inf = QFormLayout(self.isolator_box)
        self.i_fy = _force(500.0, 10.0)
        self.i_alpha = spin(0.10, 0.0, 1.0, 4, 0.01)
        self.i_gr = _stress(0.0004, 0.00005)
        self.i_kbulk = _stress(2.0, 0.1)
        self.i_d1 = _length(200.0, 10.0)
        self.i_d2 = _length(400.0, 10.0)
        self.i_ts = _length(3.0, 0.5)
        self.i_tr = _length(8.0, 0.5)
        self.i_n = int_spin(10, 1, 200)
        inf.addRow("Yield strength Fy", self.i_fy)
        inf.addRow("Post-yield ratio alpha", self.i_alpha)
        inf.addRow("Rubber shear modulus Gr", self.i_gr)
        inf.addRow("Rubber bulk modulus Kbulk", self.i_kbulk)
        inf.addRow("Internal diameter D1", self.i_d1)
        inf.addRow("Outer diameter D2", self.i_d2)
        inf.addRow("Steel shim thickness ts", self.i_ts)
        inf.addRow("Rubber layer thickness tr", self.i_tr)
        inf.addRow("Number of rubber layers n", self.i_n)
        self.body.addWidget(self.isolator_box)

        # ---- damper ---------------------------------------------------
        self.damper_box = QGroupBox("Damper (twoNodeLink)")
        df = QFormLayout(self.damper_box)
        self._damper_form = df
        self.d_kel = _stiffness(500.0, 10.0)
        self.d_cd = spin(10.0, 0.0, 1e15, 6, 1.0)
        self.d_alpha = spin(0.5, 0.01, 2.0, 3, 0.05)
        self.d_gap = _length(0.0, 1.0)
        self.d_nm = QComboBox()
        self.d_nm.addItem("Dormand-Prince 54 (1)", 1)
        self.d_nm.addItem("Adams-Bashforth-Moulton (2)", 2)
        self.d_nm.addItem("Rosenbrock Triple (3)", 3)
        self.d_dir = QComboBox()
        for index, label in enumerate(("axial x", "local y", "local z",
                                       "rotation x", "rotation y", "rotation z"),
                                      start=1):
            self.d_dir.addItem(f"{index}  {label}", index)
        self.d_fr = _force(100.0, 10.0)
        self.d_p = spin(0.10, 0.0, 1.0, 4, 0.01)
        df.addRow("Elastic stiffness K_el", self.d_kel)
        df.addRow("Damping coefficient Cd", self.d_cd)
        df.addRow("Velocity exponent alpha", self.d_alpha)
        df.addRow("Gap length", self.d_gap)
        df.addRow("Numerical method", self.d_nm)
        df.addRow("Direction", self.d_dir)
        df.addRow("Relief load Fr (oil)", self.d_fr)
        df.addRow("Post-relief ratio p (oil)", self.d_p)
        self.body.addWidget(self.damper_box)

        self.body.addWidget(hint(
            "Bearing and isolator stiffnesses use force and moment units. "
            "Damper Cd uses force/(length/time)^alpha; viscous and oil dampers "
            "act in time-history and dynamic analyses."))

        self.d_alpha.valueChanged.connect(self._sync)
        self._sync()
        self.buttons("Create")

    # ------------------------------------------------------------------ ui
    def _sync(self) -> None:
        kind = str(self.kind.currentData())
        self.bearing_box.setVisible(kind == "bearing")
        self.isolator_box.setVisible(kind == "isolator")
        self.damper_box.setVisible(kind in ("damper_viscous", "damper_oil"))
        oil = kind == "damper_oil"
        for field in (self.d_fr, self.d_p):
            field.setVisible(oil)
            label = self._damper_form.labelForField(field)
            if label is not None:
                label.setVisible(oil)
        alpha = self.d_alpha.value()
        self.d_cd.setSuffix(
            f" {UNITS.force_unit}/({UNITS.length_unit}/s)^{alpha:g}")

    # -------------------------------------------------------------- values
    def _damping_base(self, value: float, alpha: float) -> float:
        return (value * UNITS.force_base(1.0)
                / (UNITS.length_base(1.0) ** max(alpha, 0.0)))

    def spec(self) -> dict:
        kind = str(self.kind.currentData())
        nodes = parse_tags(self.nodes.text())
        device = {"type": kind}
        element_kind = "damper" if kind.startswith("damper_") else kind
        if kind == "bearing":
            device.update({
                "k_init": UNITS.dist_base(self.b_kinit.value()),
                "qd": UNITS.force_base(self.b_qd.value()),
                "alpha1": self.b_alpha1.value(),
                "alpha2": self.b_alpha2.value(),
                "mu": self.b_mu.value(),
                "eta": self.b_eta.value(),
                "beta": self.b_beta.value(),
                "gamma": self.b_gamma.value(),
                "kv": UNITS.dist_base(self.b_kv.value()),
                "kt": UNITS.moment_base(self.b_kt.value()),
                "kry": UNITS.moment_base(self.b_kry.value()),
                "krz": UNITS.moment_base(self.b_krz.value()),
            })
        elif kind == "isolator":
            device.update({
                "fy": UNITS.force_base(self.i_fy.value()),
                "alpha": self.i_alpha.value(),
                "gr": UNITS.stress_base(self.i_gr.value()),
                "kbulk": UNITS.stress_base(self.i_kbulk.value()),
                "d1": UNITS.length_base(self.i_d1.value()),
                "d2": UNITS.length_base(self.i_d2.value()),
                "ts": UNITS.length_base(self.i_ts.value()),
                "tr": UNITS.length_base(self.i_tr.value()),
                "n": int(self.i_n.value()),
            })
        else:
            alpha = self.d_alpha.value()
            device.update({
                "k_el": UNITS.dist_base(self.d_kel.value()),
                "cd": self._damping_base(self.d_cd.value(), alpha),
                "alpha": alpha,
                "gap": UNITS.length_base(self.d_gap.value()),
                "nm": int(self.d_nm.currentData()),
                "direction": int(self.d_dir.currentData()),
            })
            if kind == "damper_oil":
                device["fr"] = UNITS.force_base(self.d_fr.value())
                device["p"] = self.d_p.value()
        return {"kind": element_kind, "nodes": nodes, "device": device}
