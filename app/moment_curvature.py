"""Moment-curvature analysis of reinforced-concrete sections.

Ported from the Moment Curvature Pro solver.  The strain-plane integration
uses Mander confined/unconfined concrete and a Park steel envelope.  Results
are returned in the application's base units (kN, mm, rad) together with an
idealised trilinear moment-rotation backbone that can be stored as a spring
hinge definition.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

Point = Tuple[float, float]


# --------------------------------------------------------------------------- #
# Material envelopes
# --------------------------------------------------------------------------- #
def mander_confined(strain: float, fc: float, fcc: float, ecc: float,
                    ec: float, ecu: float) -> float:
    eps = abs(strain)
    spall_end = ecu + 0.005
    if eps > spall_end:
        return 0.0
    e_sec = fcc / ecc
    r = ec / max(ec - e_sec, 1e-12)
    x = eps / ecc
    stress = fcc * x * r / max(r - 1.0 + x ** r, 1e-12)
    if eps > ecu:
        stress *= (spall_end - eps) / max(spall_end - ecu, 1e-12)
    return -stress


def mander_unconfined(strain: float, fc: float) -> float:
    eps = abs(strain)
    eco = 0.002
    spall_start = 0.0035
    spall_end = 0.005
    if eps > spall_end:
        return 0.0
    ec = 5000.0 * math.sqrt(max(fc, 0.0))
    e_sec = fc / eco
    r = ec / max(ec - e_sec, 1e-12)
    x = eps / eco
    stress = fc * x * r / max(r - 1.0 + x ** r, 1e-12)
    if eps > spall_start:
        stress *= (spall_end - eps) / (spall_end - spall_start)
    return -stress


def park_steel(strain: float, fy: float) -> float:
    es = 200000.0
    ey = fy / es
    eps = abs(strain)
    sign = 1.0 if strain >= 0 else -1.0
    if eps <= ey:
        return sign * eps * es
    esh = 0.015
    esu = 0.14
    fu = 1.35 * fy
    if eps <= esh:
        return sign * fy
    if eps >= esu:
        return sign * fu
    ratio = (esu - eps) / (esu - esh)
    return sign * (fu - (fu - fy) * ratio ** 2)


def _integrate(func, start: float, end: float, steps: int = 100) -> float:
    dx = (end - start) / steps
    area = 0.0
    for i in range(steps):
        area += 0.5 * (abs(func(start + i * dx))
                       + abs(func(start + (i + 1) * dx))) * dx
    return area


# --------------------------------------------------------------------------- #
# Inputs and results
# --------------------------------------------------------------------------- #
@dataclass
class MomentCurvatureInput:
    section: str = "rectangular"       # rectangular | circular
    B: float = 400.0                   # mm
    H: float = 600.0                   # mm
    D: float = 600.0                   # mm
    cover: float = 40.0                # mm
    nx: int = 4
    ny: int = 4
    n_bars: int = 12
    db: float = 25.0                   # mm
    dbt: float = 10.0                  # mm
    s: float = 100.0                   # mm
    fc: float = 30.0                   # MPa
    fy: float = 420.0                  # MPa
    P: float = 0.0                     # kN, positive compression
    L: float = 4000.0                  # mm
    Lp_mm: float = 0.0                 # mm, 0 = calculate

    def validate(self) -> Optional[str]:
        if self.fc <= 0 or self.fy <= 0:
            return "Concrete and steel strengths must be positive."
        if self.L <= 0:
            return "Member length must be positive."
        if self.cover <= 0 or self.db <= 0 or self.dbt <= 0 or self.s <= 0:
            return "Cover, bar diameter, tie diameter and spacing must be positive."
        if self.section == "circular":
            if self.D <= 0:
                return "Diameter must be positive."
            if self.n_bars < 4:
                return "At least 4 bars are required for a circular section."
            if self.D < 2 * self.cover:
                return "The reinforcement cage must be inside the section."
        else:
            if self.B <= 0 or self.H <= 0:
                return "Section dimensions must be positive."
            if self.nx < 2 or self.ny < 2:
                return "At least 2 bars per side are required."
            if self.B < 2 * self.cover or self.H < 2 * self.cover:
                return "The reinforcement cage must be inside the section."
        return None


@dataclass
class SectionGeometry:
    bar_coords: List[dict]
    concrete_cells: List[dict]
    Ag: float
    Ast: float
    depth_total: float
    width_total: float
    x_pc: float
    y_pc: float
    cell_x: np.ndarray = field(default_factory=lambda: np.zeros(0))
    cell_y: np.ndarray = field(default_factory=lambda: np.zeros(0))
    cell_area: np.ndarray = field(default_factory=lambda: np.zeros(0))
    cell_core: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
    bar_x: np.ndarray = field(default_factory=lambda: np.zeros(0))
    bar_y: np.ndarray = field(default_factory=lambda: np.zeros(0))
    bar_area: np.ndarray = field(default_factory=lambda: np.zeros(0))
    bar_core: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))


@dataclass
class MomentCurve:
    curvatures: List[float] = field(default_factory=list)      # 1/m
    moments: List[float] = field(default_factory=list)         # kN m
    steel_strain: List[float] = field(default_factory=list)    # %
    concrete_strain: List[float] = field(default_factory=list)  # %
    rotations: List[float] = field(default_factory=list)       # rad
    converged: int = 0
    total: int = 0
    backbone: List[Point] = field(default_factory=list)        # (rad, kN mm)
    yield_moment: float = 0.0                                  # kN mm
    peak_moment: float = 0.0
    ultimate_moment: float = 0.0
    yield_rotation: float = 0.0
    peak_rotation: float = 0.0
    ultimate_rotation: float = 0.0
    initial_stiffness: float = 0.0                             # kN mm/rad
    post_yield_ratio: float = 0.0
    ductility: float = 0.0


@dataclass
class MomentCurvatureResult:
    inputs: MomentCurvatureInput
    geometry: SectionGeometry
    confinement: dict
    Lp_mm: float
    strong: MomentCurve
    weak: Optional[MomentCurve]
    warnings: List[str] = field(default_factory=list)

    @property
    def Ag(self) -> float:
        return self.geometry.Ag

    @property
    def Ast(self) -> float:
        return self.geometry.Ast

    @property
    def reinforcement_ratio(self) -> float:
        return self.geometry.Ast / max(self.geometry.Ag, 1e-12)


# --------------------------------------------------------------------------- #
# Section integration
# --------------------------------------------------------------------------- #
def analytical_dmax(inputs: MomentCurvatureInput, theta: float) -> float:
    if inputs.section == "circular":
        return inputs.D / 2.0
    return (inputs.B / 2.0) * abs(math.cos(theta)) + (inputs.H / 2.0) * abs(math.sin(theta))


def build_geometry(inputs: MomentCurvatureInput) -> SectionGeometry:
    bar_area = math.pi * (inputs.db / 2.0) ** 2
    bars: List[dict] = []
    if inputs.section == "circular":
        depth = width = inputs.D
        ag = math.pi * (inputs.D / 2.0) ** 2
        core_r = (inputs.D - 2.0 * inputs.cover - inputs.dbt) / 2.0
        ds = inputs.D - 2.0 * inputs.cover - inputs.dbt
        r_rebar = (ds - inputs.dbt - inputs.db) / 2.0
        step = 2.0 * math.pi / inputs.n_bars
        for i in range(inputs.n_bars):
            theta = i * step
            x = r_rebar * math.cos(theta)
            y = r_rebar * math.sin(theta)
            bars.append({"x": x, "y": y, "As": bar_area,
                         "in_core": math.hypot(x, y) <= core_r})
    else:
        depth, width = inputs.H, inputs.B
        ag = inputs.B * inputs.H
        x_lim = inputs.B / 2.0 - inputs.cover - inputs.dbt - inputs.db / 2.0
        y_lim = inputs.H / 2.0 - inputs.cover - inputs.dbt - inputs.db / 2.0
        core_w = inputs.B - 2.0 * inputs.cover - inputs.dbt
        core_h = inputs.H - 2.0 * inputs.cover - inputs.dbt

        def add(x: float, y: float) -> None:
            bars.append({"x": x, "y": y, "As": bar_area,
                         "in_core": abs(x) <= core_w / 2.0 and abs(y) <= core_h / 2.0})

        if inputs.nx > 1:
            dx = 2.0 * x_lim / (inputs.nx - 1)
            for i in range(inputs.nx):
                add(-x_lim + i * dx, y_lim)
                add(-x_lim + i * dx, -y_lim)
        if inputs.ny > 2:
            dy = 2.0 * y_lim / (inputs.ny - 1)
            for j in range(1, inputs.ny - 1):
                add(-x_lim, -y_lim + j * dy)
                add(x_lim, -y_lim + j * dy)

    grid = 80
    dx = width / grid
    dy = depth / grid
    d_area = dx * dy
    cells: List[dict] = []
    core_r = (inputs.D - 2.0 * inputs.cover - inputs.dbt) / 2.0 if inputs.section == "circular" else 0.0
    core_w = inputs.B - 2.0 * inputs.cover - inputs.dbt
    core_h = inputs.H - 2.0 * inputs.cover - inputs.dbt
    for i in range(grid):
        for j in range(grid):
            x = -width / 2.0 + (i + 0.5) * dx
            y = -depth / 2.0 + (j + 0.5) * dy
            if inputs.section == "circular":
                if math.hypot(x, y) <= inputs.D / 2.0:
                    cells.append({"x": x, "y": y, "area": d_area,
                                  "in_core": math.hypot(x, y) <= core_r})
            else:
                cells.append({"x": x, "y": y, "area": d_area,
                              "in_core": abs(x) <= core_w / 2.0
                              and abs(y) <= core_h / 2.0})

    alpha1 = max(0.67, 0.85 - 0.0015 * inputs.fc)
    total_p = total_mx = total_my = 0.0
    for cell in cells:
        p = alpha1 * inputs.fc * cell["area"]
        total_p += p
        total_mx += p * cell["y"]
        total_my += p * cell["x"]
    for bar in bars:
        p = inputs.fy * bar_area
        total_p += p
        total_mx += p * bar["y"]
        total_my += p * bar["x"]
        p_disp = alpha1 * inputs.fc * bar_area
        total_p -= p_disp
        total_mx -= p_disp * bar["y"]
        total_my -= p_disp * bar["x"]
    x_pc = total_my / total_p if total_p > 0 else 0.0
    y_pc = total_mx / total_p if total_p > 0 else 0.0
    return SectionGeometry(
        bars, cells, ag, len(bars) * bar_area, depth, width, x_pc, y_pc,
        cell_x=np.asarray([c["x"] for c in cells], dtype=float),
        cell_y=np.asarray([c["y"] for c in cells], dtype=float),
        cell_area=np.asarray([c["area"] for c in cells], dtype=float),
        cell_core=np.asarray([c["in_core"] for c in cells], dtype=bool),
        bar_x=np.asarray([b["x"] for b in bars], dtype=float),
        bar_y=np.asarray([b["y"] for b in bars], dtype=float),
        bar_area=np.full(len(bars), bar_area, dtype=float),
        bar_core=np.asarray([b["in_core"] for b in bars], dtype=bool))


def _mander_confined_vec(strain: np.ndarray, fc: float, fcc: float,
                         ecc: float, ec: float, ecu: float) -> np.ndarray:
    eps = np.abs(strain)
    spall_end = ecu + 0.005
    e_sec = fcc / ecc
    r = ec / max(ec - e_sec, 1e-12)
    x = eps / ecc
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        stress = fcc * x * r / np.maximum(r - 1.0 + x ** r, 1e-12)
    stress = np.where(eps > ecu,
                      stress * (spall_end - eps) / max(spall_end - ecu, 1e-12),
                      stress)
    return np.where(eps > spall_end, 0.0, -stress)


def _mander_unconfined_vec(strain: np.ndarray, fc: float) -> np.ndarray:
    eps = np.abs(strain)
    eco = 0.002
    spall_start = 0.0035
    spall_end = 0.005
    ec = 5000.0 * math.sqrt(max(fc, 0.0))
    e_sec = fc / eco
    r = ec / max(ec - e_sec, 1e-12)
    x = eps / eco
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        stress = fc * x * r / np.maximum(r - 1.0 + x ** r, 1e-12)
    stress = np.where(eps > spall_start,
                      stress * (spall_end - eps) / (spall_end - spall_start),
                      stress)
    return np.where(eps > spall_end, 0.0, -stress)


def _park_steel_vec(strain: np.ndarray, fy: float) -> np.ndarray:
    es = 200000.0
    ey = fy / es
    eps = np.abs(strain)
    sign = np.where(strain >= 0.0, 1.0, -1.0)
    esh = 0.015
    esu = 0.14
    fu = 1.35 * fy
    elastic = sign * eps * es
    plateau = sign * fy
    ratio = (esu - eps) / (esu - esh)
    hardening = sign * (fu - (fu - fy) * ratio ** 2)
    return np.where(eps <= ey, elastic,
                    np.where(eps <= esh, plateau,
                             np.where(eps >= esu, sign * fu, hardening)))


def section_forces(geometry: SectionGeometry, inputs: MomentCurvatureInput,
                   fcc: float, ecc: float, ecu: float, eps_top: float,
                   eps_bot: float, theta: float, d_max: float,
                   ignore_fracture: bool = False) -> dict:
    fc, fy = inputs.fc, inputs.fy
    ec = 5000.0 * math.sqrt(max(fc, 0.0))
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    scale = (eps_top - eps_bot) / (2.0 * d_max)
    strain_c = eps_bot + scale * (geometry.cell_x * cos_t
                                  + geometry.cell_y * sin_t + d_max)
    mask = strain_c < 0
    p_total = mx = my = 0.0
    max_c = max_core_c = 0.0
    if np.any(mask):
        stress = np.zeros_like(strain_c)
        core_mask = mask & geometry.cell_core
        unc_mask = mask & ~geometry.cell_core
        if np.any(core_mask):
            stress[core_mask] = _mander_confined_vec(
                strain_c[core_mask], fc, fcc, ecc, ec, ecu)
        if np.any(unc_mask):
            stress[unc_mask] = _mander_unconfined_vec(
                strain_c[unc_mask], fc)
        force = stress * geometry.cell_area
        p_total = float(np.sum(force))
        mx = float(-np.sum(force * (geometry.cell_y - geometry.y_pc)))
        my = float(-np.sum(force * (geometry.cell_x - geometry.x_pc)))
        max_c = float(np.max(-strain_c[mask]))
        core_mask = mask & geometry.cell_core
        if np.any(core_mask):
            max_core_c = float(np.max(-strain_c[core_mask]))

    strain_b = eps_bot + scale * (geometry.bar_x * cos_t
                                  + geometry.bar_y * sin_t + d_max)
    stress_b = _park_steel_vec(strain_b, fy)
    if ignore_fracture:
        stress_b = np.where(np.abs(strain_b) > 0.14,
                            np.where(strain_b > 0, 1.35 * fy, -1.35 * fy),
                            stress_b)
    force_b = stress_b * geometry.bar_area
    p_total += float(np.sum(force_b))
    mx += float(-np.sum(force_b * (geometry.bar_y - geometry.y_pc)))
    my += float(-np.sum(force_b * (geometry.bar_x - geometry.x_pc)))
    tension = strain_b > 0
    max_t = float(np.max(strain_b[tension])) if np.any(tension) else 0.0
    comp = strain_b < 0
    if np.any(comp):
        conc = np.zeros_like(strain_b)
        core_mask = comp & geometry.bar_core
        unc_mask = comp & ~geometry.bar_core
        if np.any(core_mask):
            conc[core_mask] = _mander_confined_vec(
                strain_b[core_mask], fc, fcc, ecc, ec, ecu)
        if np.any(unc_mask):
            conc[unc_mask] = _mander_unconfined_vec(strain_b[unc_mask], fc)
        displaced = conc * geometry.bar_area
        p_total -= float(np.sum(displaced))
        mx += float(np.sum(displaced * (geometry.bar_y - geometry.y_pc)))
        my += float(np.sum(displaced * (geometry.bar_x - geometry.x_pc)))
    return {"P": p_total, "Mx": mx, "My": my,
            "max_t": max_t, "max_c": max_c, "max_core_c": max_core_c}


def ultimate_strain(inputs: MomentCurvatureInput, pcc: float, ps: float,
                    f_lp: float) -> dict:
    fc, fy = inputs.fc, inputs.fy
    ec = 5000.0 * math.sqrt(max(fc, 0.0))
    fcc = fc * (2.254 * math.sqrt(max(0.0, 1.0 + 7.94 * f_lp / fc))
                - 2.0 * f_lp / fc - 1.254)
    eco = 0.002059
    ecc = eco * (1.0 + 5.0 * (fcc / fc - 1.0))
    confined = lambda strain: mander_confined(-strain, fc, fcc, ecc, ec, 1.0)
    steel = lambda strain: park_steel(strain, fy)
    lo, hi = 0.01, 0.15
    final = 0.03
    energies: dict = {}
    for _ in range(50):
        trial = (lo + hi) / 2.0
        u_sh = 110.0 * ps
        u_cc = _integrate(confined, 0.0, trial, 100)
        u_sl = _integrate(steel, 0.0, trial, 100) * pcc
        u_co = 0.017 * math.sqrt(max(fc, 0.0))
        balance = u_sh - (u_cc + u_sl - u_co)
        energies = {"Ush": u_sh, "Ucc": u_cc, "Usl": u_sl, "Uco": u_co,
                    "Balance": balance}
        final = trial
        if abs(balance) < 1e-6:
            break
        if balance > 0:
            lo = trial
        else:
            hi = trial
    return {"ecu": final, "fcc": fcc, "ecc": ecc, "energies": energies}


def analyze_curve(inputs: MomentCurvatureInput, geometry: SectionGeometry,
                  confinement: dict, axis: str = "strong") -> MomentCurve:
    target_f = -inputs.P * 1000.0
    theta = math.pi / 2.0 if axis == "strong" else 0.0
    d_max = analytical_dmax(inputs, theta)
    points = 300
    max_curv = (confinement["ecu"] * 1.5) / (0.15 * geometry.depth_total)
    curve = MomentCurve(total=points + 1)
    for i in range(points + 1):
        curv = max_curv * (i / points) ** 1.5
        lo, hi = -0.05, 0.05
        eps_center = 0.0
        final = None
        converged = False
        for _ in range(60):
            eps_top = eps_center - curv * d_max
            eps_bot = eps_center + curv * d_max
            forces = section_forces(geometry, inputs, confinement["fcc"],
                                    confinement["ecc"], confinement["ecu"],
                                    eps_top, eps_bot, theta, d_max)
            diff = forces["P"] - target_f
            tol = 1e-6 * max(1.0, abs(target_f), inputs.fc * geometry.Ag)
            if abs(diff) < tol or (hi - lo) < 1e-12:
                converged = True
                final = forces
                break
            if diff > 0:
                hi = eps_center
                eps_center = (eps_center + lo) / 2.0
            else:
                lo = eps_center
                eps_center = (eps_center + hi) / 2.0
        if converged or i == 0:
            if final is None:
                final = section_forces(
                    geometry, inputs, confinement["fcc"], confinement["ecc"],
                    confinement["ecu"], eps_center - curv * d_max,
                    eps_center + curv * d_max, theta, d_max)
            curve.curvatures.append(curv * 1000.0)       # 1/m
            curve.moments.append((final["Mx"] if axis == "strong"
                                  else final["My"]) / 1e6)  # kN m
            curve.steel_strain.append(final["max_t"] * 100.0)
            curve.concrete_strain.append(final["max_c"] * 100.0)
            curve.converged += 1
            if i > 0 and (final["max_core_c"] > confinement["ecu"]
                          or final["max_t"] > 0.09):
                break
    _rotations(curve, inputs)
    return curve


def _rotations(curve: MomentCurve, inputs: MomentCurvatureInput) -> None:
    ey = inputs.fy / 200000.0
    phi_y = 0.0
    for i, strain in enumerate(curve.steel_strain):
        if strain / 100.0 >= ey:
            phi_y = curve.curvatures[i] / 1000.0
            break
    if phi_y == 0.0 and curve.curvatures:
        phi_y = curve.curvatures[-1] / 1000.0
    lp = inputs.Lp_mm or max(0.08 * inputs.L + 0.022 * inputs.fy * inputs.db,
                             0.044 * inputs.fy * inputs.db)
    rotations = []
    for phi_m in curve.curvatures:
        phi = phi_m / 1000.0
        if phi <= phi_y:
            rotations.append(phi * inputs.L / 3.0)
        else:
            rotations.append(phi_y * inputs.L / 3.0 + (phi - phi_y) * lp)
    curve.rotations = rotations


def _idealise(curve: MomentCurve, inputs: MomentCurvatureInput) -> None:
    if not curve.moments:
        return
    moments = curve.moments
    peak_index = max(range(len(moments)), key=lambda i: moments[i])
    yield_index = 0
    ey = inputs.fy / 200000.0
    for i, strain in enumerate(curve.steel_strain):
        if strain / 100.0 >= ey:
            yield_index = i
            break
    else:
        target = 0.75 * moments[peak_index]
        yield_index = next((i for i, m in enumerate(moments) if m >= target),
                           peak_index)
    if yield_index > peak_index:
        yield_index = peak_index
    ultimate_index = len(moments) - 1
    while ultimate_index > peak_index and moments[ultimate_index] <= 0:
        ultimate_index -= 1

    def safe_rotation(index: int) -> float:
        if not curve.rotations:
            return 0.0
        index = max(0, min(index, len(curve.rotations) - 1))
        return max(0.0, curve.rotations[index])

    my = max(0.0, moments[yield_index])
    mp = max(my, moments[peak_index])
    mu = max(0.0, moments[ultimate_index])
    ty = safe_rotation(yield_index)
    tp = safe_rotation(peak_index)
    tu = safe_rotation(ultimate_index)
    if ty <= 0.0:
        ty = max(curve.curvatures[yield_index] / 1000.0 * inputs.L / 3.0, 1e-9)
    if tp <= ty:
        tp = ty * 1.05
    if tu <= tp:
        tu = tp * 1.05
    if mu <= 0.0:
        mu = my
    curve.backbone = [(0.0, 0.0), (ty, my * 1000.0),
                      (tp, mp * 1000.0), (tu, mu * 1000.0)]
    curve.yield_moment = my * 1000.0
    curve.peak_moment = mp * 1000.0
    curve.ultimate_moment = mu * 1000.0
    curve.yield_rotation = ty
    curve.peak_rotation = tp
    curve.ultimate_rotation = tu
    curve.initial_stiffness = my * 1000.0 / max(ty, 1e-12)
    denominator = (mp - my)
    if denominator > 0 and ty > 0:
        curve.post_yield_ratio = max(
            0.0, ((mp - my) / max(tp - ty, 1e-12)) / (my / ty))
    curve.ductility = tu / max(ty, 1e-12)


def run_moment_curvature(inputs: MomentCurvatureInput) -> MomentCurvatureResult:
    error = inputs.validate()
    if error:
        raise ValueError(error)
    geometry = build_geometry(inputs)
    ec = 5000.0 * math.sqrt(max(inputs.fc, 0.0))
    if inputs.section == "circular":
        ds = inputs.D - 2.0 * inputs.cover - inputs.dbt
        asc = math.pi * (inputs.dbt / 2.0) ** 2
        ps = 4.0 * asc / max(ds * inputs.s, 1e-12)
        r_core = ds / 2.0
        pcc = inputs.n_bars * math.pi * (inputs.db / 2.0) ** 2 / max(
            math.pi * r_core ** 2, 1e-12)
        sc = inputs.s - inputs.dbt
        ae = 0.25 * math.pi * ds * max(ds - sc / 2.0, 0.0)
        acc = 0.25 * math.pi * ds ** 2 * (1.0 - pcc)
        ke = ae / max(acc, 1e-12)
        f_lp = ke * ps * inputs.fy / 2.0
        confinement = {"pcc": pcc, "ps": ps, "ds": ds, "Ke": ke,
                       "fLp": f_lp, "coreArea": acc}
    else:
        bc = inputs.B - 2.0 * inputs.cover - inputs.dbt
        dc = inputs.H - 2.0 * inputs.cover - inputs.dbt
        ac = bc * dc
        pcc = ((2 * inputs.nx + 2 * (inputs.ny - 2))
               * math.pi * (inputs.db / 2.0) ** 2) / max(ac, 1e-12)
        rho_x = (4.0 * math.pi * (inputs.dbt / 2.0) ** 2) / max(inputs.s * dc, 1e-12)
        rho_y = (4.0 * math.pi * (inputs.dbt / 2.0) ** 2) / max(inputs.s * bc, 1e-12)
        sum_sq = ((inputs.nx - 1) * (bc / max(inputs.nx - 1, 1)) ** 2
                  + (inputs.ny - 1) * (dc / max(inputs.ny - 1, 1)) ** 2)
        ke = ((1.0 - sum_sq / max(6.0 * bc * dc, 1e-12))
              * (1.0 - (inputs.s - inputs.dbt) / max(2.0 * bc, 1e-12))
              * (1.0 - (inputs.s - inputs.dbt) / max(2.0 * dc, 1e-12))
              / max(1.0 - pcc, 1e-12))
        confinement = {"pcc": pcc, "ps": rho_x + rho_y, "ds": 0.0,
                       "Ke": ke,
                       "fLp": (ke * rho_x * inputs.fy + ke * rho_y * inputs.fy) / 2.0,
                       "coreArea": ac}
    confinement.update(ultimate_strain(inputs, confinement["pcc"],
                                       confinement["ps"], confinement["fLp"]))
    lp = inputs.Lp_mm or max(0.08 * inputs.L + 0.022 * inputs.fy * inputs.db,
                             0.044 * inputs.fy * inputs.db)
    strong = analyze_curve(inputs, geometry, confinement, "strong")
    weak = analyze_curve(inputs, geometry, confinement, "weak") if inputs.section == "rectangular" else None
    _idealise(strong, inputs)
    if weak is not None:
        _idealise(weak, inputs)
    warnings: List[str] = []
    if strong.converged < strong.total * 0.8:
        warnings.append("Only the early part of the moment-curvature curve converged.")
    return MomentCurvatureResult(inputs, geometry, confinement, lp,
                                 strong, weak, warnings)
