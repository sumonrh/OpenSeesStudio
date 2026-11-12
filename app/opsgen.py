"""Bridge between the application model and the OpenSees solver.

Every analysis rebuilds a fresh OpenSees domain from the :class:`Project`.
Units: kN, mm, tonne, s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import openseespy.opensees as ops

from .model import (Element, ElementLoad, Material, Node, Project, Section,
                    G_ACC)

_EPS = 1e-12


# --------------------------------------------------------------------------- #
# geometry helpers
# --------------------------------------------------------------------------- #
def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    l = math.sqrt(_dot(a, a))
    if l < _EPS:
        return (0.0, 0.0, 0.0)
    return (a[0] / l, a[1] / l, a[2] / l)


def local_axes(p, q, vecxz) -> Tuple[Tuple[float, ...], ...]:
    """Return (x, y, z) unit vectors of an element's local system."""
    x = _norm(_sub(q, p))
    v = (float(vecxz[0]), float(vecxz[1]), float(vecxz[2]))
    z = _norm(_sub(v, tuple(_dot(v, x) * c for c in x)))
    if _dot(z, z) < 0.5:            # v parallel to the member -> pick fallback
        v = (1.0, 0.0, 0.0) if abs(x[0]) < 0.9 else (0.0, 1.0, 0.0)
        z = _norm(_sub(v, tuple(_dot(v, x) * c for c in x)))
    y = _cross(z, x)
    return x, y, z


def auto_vecxz(p, q) -> List[float]:
    """Default local-z: global Z, unless the member is vertical."""
    x = _norm(_sub(q, p))
    if abs(x[2]) > 0.98:
        return [1.0, 0.0, 0.0]
    return [0.0, 0.0, 1.0]


# --------------------------------------------------------------------------- #
# results containers
# --------------------------------------------------------------------------- #
@dataclass
class StaticResults:
    scenario: str = ""
    displacements: Dict[int, List[float]] = field(default_factory=dict)
    reactions: Dict[int, List[float]] = field(default_factory=dict)
    element_forces: Dict[int, List[float]] = field(default_factory=dict)
    element_kind: Dict[int, str] = field(default_factory=dict)
    max_disp: float = 0.0
    log: str = ""


@dataclass
class ModeResult:
    mode: int = 1
    eigenvalue: float = 0.0
    omega: float = 0.0
    period: float = 0.0
    frequency: float = 0.0


@dataclass
class ModalResults:
    modes: List[ModeResult] = field(default_factory=list)
    shapes: Dict[int, Dict[int, List[float]]] = field(default_factory=dict)
    log: str = ""


@dataclass
class PushoverStep:
    step: int = 0
    displacement: float = 0.0
    base_shear: float = 0.0
    displacements: Dict[int, List[float]] = field(default_factory=dict)
    hinge_rotations: Dict[int, List[float]] = field(default_factory=dict)
    hinge_moments: Dict[int, List[float]] = field(default_factory=dict)


@dataclass
class PushoverResults:
    gravity_case: str = ""
    lateral_case: str = ""
    control_node: int = 0
    control_dof: int = 1
    hinge_model: str = ""
    steps: List[PushoverStep] = field(default_factory=list)
    hinge_yield: Dict[int, float] = field(default_factory=dict)
    log: str = ""

    def static_at(self, index: int = -1) -> StaticResults:
        step = self.steps[index]
        return StaticResults(
            scenario=f"Pushover step {step.step}",
            displacements={t: list(v) for t, v in step.displacements.items()},
            max_disp=max((max(abs(v) for v in d) for d in step.displacements.values()),
                         default=0.0),
            log=self.log)

    def max_hinge_rotation(self, step: PushoverStep) -> float:
        return max((abs(v) for vals in step.hinge_rotations.values() for v in vals),
                   default=0.0)


# --------------------------------------------------------------------------- #
# model construction
# --------------------------------------------------------------------------- #
def _material_command(m: Material):
    if m.kind == "ElasticPP":
        return ("uniaxialMaterial", "ElasticPP", m.tag, m.E, m.fy)
    if m.kind == "Steel02":
        return ("uniaxialMaterial", "Steel02", m.tag, m.fy, m.E, m.b)
    if m.kind == "Concrete02":
        return ("uniaxialMaterial", "Concrete02", m.tag, m.fc, m.epsc0, m.fpcu, m.epsU)
    return ("uniaxialMaterial", "Elastic", m.tag, m.E)


def _ensure_section(s: Section) -> Section:
    if s.A <= 0.0 or s.Iy <= 0.0 or s.Iz <= 0.0:
        s.compute()
    return s


def _point_in_polygon(y: float, z: float, poly) -> bool:
    inside = False
    j = len(poly) - 1
    for i, (yi, zi) in enumerate(poly):
        yj, zj = poly[j]
        if ((zi > z) != (zj > z)) and (y < (yj - yi) * (z - zi) / (zj - zi) + yi):
            inside = not inside
        j = i
    return inside


def _rect_fibers(y0: float, y1: float, z0: float, z1: float,
                 ny: int, nz: int):
    ny = max(2, ny)
    nz = max(2, nz)
    dy = (y1 - y0) / ny
    dz = (z1 - z0) / nz
    area = abs((y1 - y0) * (z1 - z0)) / (ny * nz)
    return [(y0 + (i + 0.5) * dy, z0 + (j + 0.5) * dz, area)
            for i in range(ny) for j in range(nz)]


def _section_fiber_mesh(sec: Section):
    """Return fibers that capture thin walls of standard section shapes."""
    b = max(float(getattr(sec, "b", 0.0) or 0.0), 1.0)
    h = max(float(getattr(sec, "h", 0.0) or 0.0), 1.0)
    t = max(float(getattr(sec, "t", 0.0) or 0.0), 0.0)
    tw = max(float(getattr(sec, "tw", 0.0) or 0.0), 0.0)
    tf = max(float(getattr(sec, "tf", 0.0) or 0.0), 0.0)
    shape = getattr(sec, "shape", "Rectangle")
    if shape in ("Circle", "Pipe", "Hexagon", "Octagon"):
        b = h = max(float(getattr(sec, "d", 0.0) or 0.0), 1.0)

    def subdiv(length: float, minimum: float, cap: int = 12) -> int:
        return max(2, min(cap, int(round(length / max(minimum, 1.0)))))

    fibers = []
    if shape == "I-Shape":
        tw = max(min(tw, b), 2.0)
        tf = max(min(tf, 0.45 * h), 1.0)
        fibers += _rect_fibers(-b / 2, b / 2, h / 2 - tf, h / 2,
                               subdiv(b, 40.0), subdiv(tf, 10.0))
        fibers += _rect_fibers(-tw / 2, tw / 2, -h / 2 + tf, h / 2 - tf,
                               subdiv(tw, 8.0, 6), subdiv(h - 2 * tf, 40.0, 12))
        fibers += _rect_fibers(-b / 2, b / 2, -h / 2, -h / 2 + tf,
                               subdiv(b, 40.0), subdiv(tf, 10.0))
        return fibers
    if shape == "Box":
        t = max(min(t, 0.45 * min(b, h)), 1.0)
        fibers += _rect_fibers(-b / 2, b / 2, h / 2 - t, h / 2,
                               subdiv(b, 30.0, 10), subdiv(t, 8.0, 4))
        fibers += _rect_fibers(-b / 2, b / 2, -h / 2, -h / 2 + t,
                               subdiv(b, 30.0, 10), subdiv(t, 8.0, 4))
        fibers += _rect_fibers(-b / 2, -b / 2 + t, -h / 2 + t, h / 2 - t,
                               subdiv(t, 8.0, 4), subdiv(h - 2 * t, 30.0, 10))
        fibers += _rect_fibers(b / 2 - t, b / 2, -h / 2 + t, h / 2 - t,
                               subdiv(t, 8.0, 4), subdiv(h - 2 * t, 30.0, 10))
        return fibers
    if shape == "L-Shape":
        t = max(min(t, 0.45 * min(b, h)), 1.0)
        fibers += _rect_fibers(-b / 2, b / 2, -h / 2, -h / 2 + t,
                               subdiv(b, 30.0, 10), subdiv(t, 8.0, 4))
        fibers += _rect_fibers(-b / 2, -b / 2 + t, -h / 2 + t, h / 2,
                               subdiv(t, 8.0, 4), subdiv(h - t, 30.0, 10))
        return fibers
    if shape == "T-Shape":
        tw = max(min(tw, b), 2.0)
        tf = max(min(tf, 0.45 * h), 1.0)
        fibers += _rect_fibers(-b / 2, b / 2, h / 2 - tf, h / 2,
                               subdiv(b, 30.0, 10), subdiv(tf, 8.0, 4))
        fibers += _rect_fibers(-tw / 2, tw / 2, -h / 2, h / 2 - tf,
                               subdiv(tw, 8.0, 5), subdiv(h - tf, 30.0, 10))
        return fibers

    outer, inner = sec.outline()
    if len(outer) < 3:
        return []
    ys = [p[0] for p in outer]
    zs = [p[1] for p in outer]
    y0, y1, z0, z1 = min(ys), max(ys), min(zs), max(zs)
    nx = max(8, min(24, int(round(b / 25.0))))
    ny = max(8, min(24, int(round(h / 25.0))))
    dy, dz = (y1 - y0) / ny, (z1 - z0) / nx
    area = abs((y1 - y0) * (z1 - z0)) / (nx * ny)
    for iy in range(ny):
        y = y0 + (iy + 0.5) * dy
        for iz in range(nx):
            z = z0 + (iz + 0.5) * dz
            if not _point_in_polygon(y, z, outer):
                continue
            if inner and _point_in_polygon(y, z, inner):
                continue
            fibers.append((y, z, area))
    return fibers


def _add_hinge_section(project: Project, sec: Section, mat: Material,
                       config: dict, mat_tag: int, shear_tag: int,
                       base_sec_tag: int, sec_tag: int,
                       log: List[str]) -> bool:
    """Create a fiber hinge section with the selected hysteresis law.

    An elastic shear material is aggregated into the section so that
    distributed beam loads do not produce an ill-conditioned element.
    """
    fibers = _section_fiber_mesh(sec)
    if not fibers:
        log.append(f"Section {sec.tag}: no fibers generated for pushover hinge.")
        return False
    fy = abs(float(config.get("fy", mat.fy) or mat.fy or 0.235))
    fy = max(fy, 1e-6)
    post = max(float(config.get("post_yield_ratio", 0.02)), 0.0)
    ductility = max(float(config.get("ductility", 10.0)), 2.0)
    model = str(config.get("model", config.get("hinge_model", "Trilinear")))
    E = max(mat.E, 1e-6)
    ey = fy / E
    e2 = ey * 3.0
    eu = max(ey * ductility, e2 * 1.5)
    s2 = fy * (1.0 + post * 3.0)
    su = fy * (1.0 + post * ductility)

    if model == "Bilinear":
        ops.uniaxialMaterial("Steel01", mat_tag, fy, E, post)
    elif model == "Flag":
        flag_beta = max(0.0, min(1.0, float(config.get("beta", 0.5))))
        ops.uniaxialMaterial("FlagShape", mat_tag, E, fy, E * post, flag_beta)
    else:
        if model == "Takeda":
            pinch = max(0.0, min(1.0, float(config.get("pinching", 0.8))))
            damage = max(0.0, float(config.get("damage", 0.02)))
            beta = max(0.0, float(config.get("beta", 0.4)))
        else:
            pinch, damage, beta = 1.0, 0.0, 0.0
        ops.uniaxialMaterial(
            "Hysteretic", mat_tag,
            fy, ey, s2, e2, su, eu,
            -fy, -ey, -s2, -e2, -su, -eu,
            pinch, pinch, damage, 0.0, beta)

    ops.section("Fiber", base_sec_tag, "-GJ", max(mat.G * sec.J, 1e-6))
    for y, z, area in fibers:
        ops.fiber(y, z, area, mat_tag)
    shear_stiffness = max(mat.G * sec.A, 1e-6)
    ops.uniaxialMaterial("Elastic", shear_tag, shear_stiffness)
    ops.section("Aggregator", sec_tag, shear_tag, "Vy", shear_tag, "Vz",
                "-section", base_sec_tag)
    log.append(f"Pushover hinge section {sec_tag}: {len(fibers)} fibers, "
               f"{model} material {mat_tag}, elastic shear {shear_tag}.")
    return True


def build(project: Project, scenario: Optional[str] = None,
          verbose: bool = False,
          pushover: Optional[dict] = None) -> List[str]:
    """Build a fresh OpenSees model.  If *scenario* is given, loads are applied.

    If *pushover* is given, beam elements are built as ``beamWithHinges`` with
    fiber hinge sections using the selected hysteresis law.
    """
    log: List[str] = []

    nodes = project.nodes
    if not nodes:
        raise ValueError("The model has no nodes.")

    ops.wipe()
    ops.model("BasicBuilder", "-ndm", 3, "-ndf", 6)

    # ---- materials ----------------------------------------------------
    for m in project.materials.values():
        getattr(ops, _material_command(m)[0])(*_material_command(m)[1:])
    if not project.materials:
        ops.uniaxialMaterial("Elastic", 1, 200000.0)

    # ---- nodes --------------------------------------------------------
    for n in nodes.values():
        ops.node(n.tag, n.x, n.y, n.z)

    # ---- supports -----------------------------------------------------
    for n in nodes.values():
        if any(n.support):
            ops.fix(n.tag, *[1 if b else 0 for b in n.support])

    # ---- elements -----------------------------------------------------
    transf_cache: Dict[Tuple[float, float, float], int] = {}
    transf_tag = 1
    shell_sec = 900000
    hinge_cache: Dict[tuple, int] = {}
    hinge_mat_tag = 2_000_000
    hinge_sec_tag = 1_000_000

    for e in project.elements.values():
        if len(e.nodes) < 2 or any(t not in nodes for t in e.nodes):
            log.append(f"Element {e.tag} skipped: missing nodes {e.nodes}")
            continue
        mat = project.material_of(e)
        sec = _ensure_section(project.section_of(e))

        if e.kind == "truss":
            area = sec.A
            ops.element("truss", e.tag, e.nodes[0], e.nodes[1], area, mat.tag)
            continue

        if e.kind == "shell":
            if len(e.nodes) < 4:
                log.append(f"Element {e.tag} skipped: shell needs 4 nodes")
                continue
            st = shell_sec + e.tag
            ops.nDMaterial("ElasticIsotropic", st, mat.E, mat.nu, mat.rho)
            ops.section("PlateFiber", st, st, e.thickness)
            ops.element("ShellMITC4", e.tag, *e.nodes[:4], st)
            continue

        # beam
        p = project.node_xyz(e.nodes[0])
        q = project.node_xyz(e.nodes[1])
        vx = tuple(e.vecxz) if e.vecxz else tuple(auto_vecxz(p, q))
        key = tuple(round(c, 6) for c in vx)
        if key not in transf_cache:
            transf_cache[key] = transf_tag
            ops.geomTransf("Linear", transf_tag, *vx)
            transf_tag += 1

        if pushover is not None and e.tag in project.hinges:
            hinge = project.hinges[e.tag]
            hp = hinge.to_dict()
            cache_key = (
                sec.tag, mat.tag, str(hp.get("model", "Trilinear")),
                round(float(hp.get("fy", mat.fy) or 0.0), 9),
                round(float(hp.get("post_yield_ratio", 0.02)), 9),
                round(float(hp.get("ductility", 10.0)), 9),
                round(float(hp.get("pinching", 0.8)), 9),
                round(float(hp.get("damage", 0.02)), 9),
                round(float(hp.get("beta", 0.4)), 9),
            )
            hinge_sec = hinge_cache.get(cache_key)
            if hinge_sec is None:
                slot = len(hinge_cache)
                hinge_sec = hinge_sec_tag + slot * 2
                tag = hinge_mat_tag + slot * 3
                shear_tag = tag + 1
                base_sec = hinge_sec + 1
                if _add_hinge_section(project, sec, mat, hp, tag, shear_tag,
                                      base_sec, hinge_sec, log):
                    hinge_cache[cache_key] = hinge_sec
                else:
                    hinge_sec = None
            if hinge_sec is not None:
                length = max(project.element_length(e), 1e-6)
                ratio = max(0.01, min(0.25, float(
                    hp.get("length_ratio", 0.1))))
                lp = min(length * ratio, 0.2 * length)
                ops.element("beamWithHinges", e.tag, e.nodes[0], e.nodes[1],
                            hinge_sec, lp, hinge_sec, lp,
                            mat.E, sec.A, sec.Iz, sec.Iy, mat.G, sec.J,
                            transf_cache[key])
                continue

        ops.element("elasticBeamColumn", e.tag, e.nodes[0], e.nodes[1],
                    sec.A, mat.E, mat.G, sec.J, sec.Iy, sec.Iz,
                    transf_cache[key])

    # ---- lumped masses (for modal analysis) ---------------------------
    if project.settings.get("mass_from_density", True):
        masses: Dict[int, float] = {}
        for e in project.elements.values():
            if len(e.nodes) < 2 or any(t not in nodes for t in e.nodes):
                continue
            mat = project.material_of(e)
            sec = _ensure_section(project.section_of(e))
            if e.kind == "shell":
                if len(e.nodes) >= 4:
                    a = 0.5 * abs(_dot(_cross(_sub(project.node_xyz(e.nodes[1]), project.node_xyz(e.nodes[0])),
                                              _sub(project.node_xyz(e.nodes[2]), project.node_xyz(e.nodes[0])))))
                    b = 0.5 * abs(_dot(_cross(_sub(project.node_xyz(e.nodes[2]), project.node_xyz(e.nodes[0])),
                                              _sub(project.node_xyz(e.nodes[3]), project.node_xyz(e.nodes[0])))))
                    # rho [t/mm^3] * volume [mm^3] = t; 1 OpenSees mass unit = 1000 t
                    m = mat.rho * (a + b) * e.thickness / 4.0 * 1e-3
                    for t in e.nodes[:4]:
                        masses[t] = masses.get(t, 0.0) + m
            else:
                m = mat.rho * sec.A * project.element_length(e) / 2.0 * 1e-3
                for t in e.nodes[:2]:
                    masses[t] = masses.get(t, 0.0) + m
        for t, m in masses.items():
            if m > 0:
                ops.mass(t, m, m, m, 0.0, 0.0, 0.0)

    # ---- loads --------------------------------------------------------
    if scenario:
        _apply_scenario(project, scenario, log, verbose)

    return log


def _scenario_factors(project: Project, scenario: str) -> List[Tuple[str, float]]:
    combo = project.combos.get(scenario)
    if combo is not None:
        return [(c, f) for c, f in combo.factors if c in project.cases]
    return [(scenario, 1.0)]


def _apply_scenario(project: Project, scenario: str, log: List[str],
                    verbose: bool = False, ts_base: int = 1,
                    p_base: int = 1) -> Tuple[int, int]:
    factors = _scenario_factors(project, scenario)
    if not factors:
        raise ValueError(f"Scenario '{scenario}' has no load cases.")

    ts_tag = ts_base
    p_tag = p_base
    for case_name, factor in factors:
        if abs(factor) < 1e-12:
            continue
        ops.timeSeries("Linear", ts_tag)
        ops.pattern("Plain", p_tag, ts_tag, "-fact", factor)
        _apply_case_loads(project, case_name, log, verbose)
        ts_tag += 1
        p_tag += 1
    return ts_tag, p_tag


def _apply_case_loads(project: Project, case: str, log: List[str],
                      verbose: bool = False) -> None:
    for nl in project.nodal_loads:
        if nl.case != case:
            continue
        if any(abs(v) > 0 for v in nl.values):
            ops.load(nl.node, *nl.values)

    for el in project.elem_loads:
        if el.case != case:
            continue
        e = project.elements.get(el.elem)
        if e is None or len(e.nodes) < 2:
            continue
        # --- distributed ------------------------------------------------
        if el.kind == "uniform":
            if e.kind == "shell":
                _shell_pressure(project, el, e)
                continue
            if el.trapezoid and abs(el.value2) > 0:
                _trapezoid_loads(project, e, el, log)
                continue
            wy, wz, _wx = _local_components(project, e, el.direction,
                                            el.value, el.value2, False)
            if abs(wy) > 0 or abs(wz) > 0:
                ops.eleLoad("-ele", e.tag, "-type", "-beamUniform", wy, wz)
            continue

        # --- point ------------------------------------------------------
        py, pz, _px = _local_components(project, e, el.direction, el.value,
                                        el.value2, False)
        if abs(py) > 0 or abs(pz) > 0:
            ops.eleLoad("-ele", e.tag, "-type", "-beamPoint", py, pz,
                        min(max(el.position, 1e-4), 1 - 1e-4))

    sw = project.self_weight.get(case, 0.0)
    if abs(sw) > 1e-12:
        _apply_self_weight(project, sw, log)


def _project_vec(project: Project, e: Element, vec):
    p = project.node_xyz(e.nodes[0])
    q = project.node_xyz(e.nodes[1])
    _x, y, z = local_axes(p, q, e.vecxz or auto_vecxz(p, q))
    return _dot(vec, y), _dot(vec, z), _dot(vec, _x)


def _apply_self_weight(project: Project, factor: float, log: List[str]) -> None:
    """Apply ρ·A·g (and ρ·A·t·g for shells) in the global -Z direction."""
    applied = 0
    # 1 t·mm/s² = 1 N = 1e-3 kN
    kn = 1.0e-3
    for e in project.elements.values():
        if len(e.nodes) < 2 or any(t not in project.nodes for t in e.nodes):
            continue
        mat = project.material_of(e)
        sec = _ensure_section(project.section_of(e))
        if mat.rho <= 0:
            continue
        w_unit = mat.rho * G_ACC * kn * factor      # kN per mm³ of material
        if e.kind == "shell":
            if len(e.nodes) < 4:
                continue
            p0 = project.node_xyz(e.nodes[0])
            p1 = project.node_xyz(e.nodes[1])
            p2 = project.node_xyz(e.nodes[2])
            p3 = project.node_xyz(e.nodes[3])
            c1 = _cross(_sub(p1, p0), _sub(p2, p0))
            c2 = _cross(_sub(p2, p0), _sub(p3, p0))
            area = 0.5 * math.sqrt(_dot(c1, c1)) + 0.5 * math.sqrt(_dot(c2, c2))
            f = -w_unit * area * e.thickness / 4.0
            for t in e.nodes[:4]:
                ops.load(t, 0.0, 0.0, f, 0.0, 0.0, 0.0)
            applied += 1
        elif e.kind == "truss":
            length = project.element_length(e)
            f = -w_unit * sec.A * length / 2.0
            for t in e.nodes[:2]:
                ops.load(t, 0.0, 0.0, f, 0.0, 0.0, 0.0)
            applied += 1
        else:
            w = -w_unit * sec.A                 # kN/mm, downward
            wy, wz, _wx = _project_vec(project, e, (0.0, 0.0, w))
            ops.eleLoad("-ele", e.tag, "-type", "-beamUniform", wy, wz)
            applied += 1
    if applied:
        log.append(f"Self weight applied to {applied} element(s), factor {factor}.")


def _local_components(project: Project, e: Element, direction: str,
                      v1: float, v2: float, trapezoid: bool):
    """Convert a load value to the element local (y, z, x) components."""
    if direction == "local-y":
        return v1, 0.0, 0.0
    if direction == "local-z":
        return 0.0, v1, 0.0
    gx = {"Global X": v1, "Global Y": 0.0, "Global Z": 0.0}.get(direction, 0.0)
    gy = {"Global X": 0.0, "Global Y": v1, "Global Z": 0.0}.get(direction, 0.0)
    gz = {"Global X": 0.0, "Global Y": 0.0, "Global Z": v1}.get(direction, 0.0)
    p = project.node_xyz(e.nodes[0])
    q = project.node_xyz(e.nodes[1])
    xa, y, z = local_axes(p, q, e.vecxz or auto_vecxz(p, q))
    g = (gx, gy, gz)
    return _dot(g, y), _dot(g, z), _dot(g, xa)


def _trapezoid_loads(project: Project, e: Element, el: ElementLoad,
                     log: List[str]) -> None:
    """Approximate a trapezoidal load by a series of point loads."""
    n = 11
    length = project.element_length(e)
    if length <= 0:
        return
    w1_y, w1_z, _ = _local_components(project, e, el.direction, el.value, el.value2, False)
    w2_y, w2_z, _ = _local_components(project, e, el.direction, el.value2, el.value2, False)
    for i in range(n):
        xL = (i + 0.5) / n
        wy = w1_y + (w2_y - w1_y) * xL
        wz = w1_z + (w2_z - w1_z) * xL
        seg = length / n
        ops.eleLoad("-ele", e.tag, "-type", "-beamPoint", wy * seg,
                    wz * seg, min(max(xL, 1e-4), 1 - 1e-4))
    log.append(f"Element {e.tag}: trapezoidal load approximated by {n} point loads.")


def _shell_pressure(project: Project, el: ElementLoad, e: Element) -> None:
    """Uniform pressure on a shell is applied as equivalent nodal forces."""
    if len(e.nodes) < 4:
        return
    p0 = project.node_xyz(e.nodes[0])
    p1 = project.node_xyz(e.nodes[1])
    p2 = project.node_xyz(e.nodes[2])
    p3 = project.node_xyz(e.nodes[3])
    c1 = _cross(_sub(p1, p0), _sub(p2, p0))
    c2 = _cross(_sub(p2, p0), _sub(p3, p0))
    area = 0.5 * math.sqrt(_dot(c1, c1)) + 0.5 * math.sqrt(_dot(c2, c2))
    n = _norm(c1)
    f = el.value * area / 4.0
    for t in e.nodes[:4]:
        ops.load(t, f * n[0], f * n[1], f * n[2], 0.0, 0.0, 0.0)


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def check_model(project: Project):
    """Return (errors, warnings) for the current model."""
    errors: List[str] = []
    warnings: List[str] = []
    if not project.nodes:
        errors.append("The model has no nodes.")
    if not project.elements:
        errors.append("The model has no elements.")
    if not project.cases:
        errors.append("The model has no load cases.")

    used = set()
    for t, e in project.elements.items():
        if len(e.nodes) < 2:
            errors.append(f"Element {t} has too few nodes.")
            continue
        for n in e.nodes:
            if n not in project.nodes:
                errors.append(f"Element {t} references missing node {n}.")
        used.update(e.nodes)
        if e.mat not in project.materials:
            errors.append(f"Element {t} references missing material {e.mat}.")
        if e.sec not in project.sections:
            errors.append(f"Element {t} references missing section {e.sec}.")
        if len(e.nodes) >= 2 and project.element_length(e) < 1e-9:
            errors.append(f"Element {t} has zero length.")

    orphans = [t for t in project.nodes if t not in used]
    if orphans:
        errors.append(f"{len(orphans)} node(s) are not connected to any element "
                      f"(e.g. {orphans[:6]}). Delete them or connect them.")

    supported = [n for n in project.nodes.values() if any(n.support)]
    if project.nodes and not supported:
        warnings.append("No supports are defined - the structure is unstable.")

    has_loads = bool(project.nodal_loads or project.elem_loads or project.self_weight)
    if not has_loads:
        warnings.append("No loads are applied.")

    return errors, warnings


# --------------------------------------------------------------------------- #
# analysis
# --------------------------------------------------------------------------- #
def run_static(project: Project, scenario: str) -> StaticResults:
    errors, _warnings = check_model(project)
    if errors:
        raise ValueError("Model check failed:\n• " + "\n• ".join(errors))
    log: List[str] = []
    log += build(project, scenario)
    ops.wipeAnalysis()
    ops.constraints("Plain")
    ops.numberer("RCM")
    ops.system("BandGen")
    ops.algorithm("Linear")
    steps = float(project.settings.get("static_steps", 1.0) or 1.0)
    ops.integrator("LoadControl", steps)
    ops.analysis("Static")
    code = ops.analyze(1)
    if code != 0:
        raise RuntimeError(f"Static analysis failed (OpenSees return code {code}).")
    ops.reactions()          # compute nodal reactions before reading them

    res = StaticResults(scenario=scenario, log="\n".join(log))
    for tag in project.nodes:
        res.displacements[tag] = [float(ops.nodeDisp(tag, i)) for i in range(1, 7)]
        res.reactions[tag] = [float(ops.nodeReaction(tag, i)) for i in range(1, 7)]
    for tag, e in project.elements.items():
        res.element_kind[tag] = e.kind
        try:
            if e.kind == "truss":
                r = ops.eleResponse(tag, "axialForce")
            elif e.kind == "shell":
                r = ops.eleResponse(tag, "forces")
            else:
                r = ops.eleResponse(tag, "localForce")
            res.element_forces[tag] = [float(v) for v in r] if r is not None else []
        except Exception:
            res.element_forces[tag] = []
    res.max_disp = max((max(abs(v) for v in d) for d in res.displacements.values()),
                       default=0.0)
    return res


def run_pushover(project: Project, config: Optional[dict] = None) -> PushoverResults:
    """Run a displacement-controlled pushover with lumped plastic hinges.

    Beam elements are rebuilt as ``beamWithHinges``; the hinge sections are
    fiber sections using the selected bilinear, trilinear, Takeda-like or
    flag-shaped hysteresis law.
    """
    errors, _warnings = check_model(project)
    if errors:
        raise ValueError("Model check failed:\n• " + "\n• ".join(errors))

    cfg = project.pushover_settings()
    if config:
        cfg.update(config)
    hinges = {tag: h for tag, h in project.hinges.items()
              if tag in project.elements
              and project.elements[tag].kind == "beam"
              and len(project.elements[tag].nodes) >= 2}
    if not hinges:
        raise ValueError("No hinges are assigned. Assign hinges to beam "
                         "elements in the hinge table before running pushover.")
    lateral = str(cfg.get("lateral_case") or "")
    gravity = str(cfg.get("gravity_case") or "")
    if not lateral:
        raise ValueError("Select a lateral load case or combination.")
    node = int(cfg.get("control_node") or 0)
    if node not in project.nodes:
        raise ValueError("Select a valid pushover control node.")
    dof = int(cfg.get("control_dof") or 1)
    if dof not in (1, 2, 3):
        raise ValueError("Pushover control DOF must be UX, UY or UZ.")
    target = float(cfg.get("target_displacement") or 0.0)
    if abs(target) < 1e-9:
        raise ValueError("Enter a non-zero target displacement.")
    steps = max(1, int(cfg.get("steps") or 20))

    log: List[str] = []
    log += build(project, None, pushover=cfg)
    ops.wipeAnalysis()

    if gravity:
        _apply_scenario(project, gravity, log)
        ops.constraints("Transformation")
        ops.numberer("RCM")
        ops.system("BandGen")
        ops.test("NormDispIncr", 1e-6, 50, 0)
        ops.algorithm("Newton")
        ops.integrator("LoadControl", 1.0)
        ops.analysis("Static")
        rc = ops.analyze(1)
        if rc != 0:
            raise RuntimeError(
                f"Gravity analysis '{gravity}' failed (OpenSees return code {rc}).")
        ops.loadConst("-time", 0.0)
        log.append(f"Gravity load case '{gravity}' applied and held constant.")
        ops.wipeAnalysis()

    ts_next, p_next = _apply_scenario(project, lateral, log, ts_base=101, p_base=101)
    lateral_cases = {c for c, _f in _scenario_factors(project, lateral)}
    has_control_load = any(
        l.node == node and abs(l.values[dof - 1]) > 1e-12
        for l in project.nodal_loads if l.case in lateral_cases)
    if not has_control_load:
        control = [0.0] * 6
        control[dof - 1] = 1.0e-3
        ops.load(node, *control)
        log.append(f"Added a 0.001 kN control-direction reference load at "
                   f"node {node} DOF {dof}.")

    ops.constraints("Transformation")
    ops.numberer("RCM")
    ops.system("BandGen")
    ops.test("NormDispIncr", 1e-6, 50, 0)
    ops.algorithm("Newton")
    du = target / steps
    ops.integrator("DisplacementControl", node, dof, du)
    ops.analysis("Static")

    hinge_tags = sorted(hinges)
    lp_cache = {}
    for tag in hinge_tags:
        length = project.element_length(project.elements[tag])
        ratio = max(0.01, min(0.25, float(hinges[tag].length_ratio)))
        lp_cache[tag] = min(length * ratio, 0.2 * length)

    result = PushoverResults(
        gravity_case=gravity, lateral_case=lateral,
        control_node=node, control_dof=dof,
        hinge_model=", ".join(sorted({h.model for h in hinges.values()})))
    for tag in hinge_tags:
        e = project.elements[tag]
        sec = _ensure_section(project.section_of(e))
        fy = abs(float(hinges[tag].fy or 0.235))
        my = fy * sec.Iy / max(sec.h / 2.0, 1e-6)
        mz = fy * sec.Iz / max(sec.b / 2.0, 1e-6)
        result.hinge_yield[tag] = max(my, mz)

    def record(step_no: int) -> None:
        ops.reactions()
        displacement = float(ops.nodeDisp(node, dof))
        base_shear = -sum(
            float(ops.nodeReaction(tag, dof))
            for tag, n in project.nodes.items() if any(n.support))
        displacements = {
            tag: [float(ops.nodeDisp(tag, i)) for i in range(1, 7)]
            for tag in project.nodes
        }
        rotations: Dict[int, List[float]] = {}
        moments: Dict[int, List[float]] = {}
        for tag in hinge_tags:
            rot = []
            mom = []
            for sec_num in (1, 6):
                try:
                    force = ops.eleResponse(tag, "section", sec_num, "force")
                    deform = ops.eleResponse(tag, "section", sec_num,
                                             "deformation")
                except Exception:
                    force, deform = [], []
                m = max((abs(float(v)) for v in force[1:3]), default=0.0) \
                    if force else 0.0
                k = max((abs(float(v)) for v in deform[1:3]), default=0.0) \
                    if deform else 0.0
                mom.append(m)
                rot.append(k * lp_cache.get(tag, 0.0))
            rotations[tag] = rot
            moments[tag] = mom
        result.steps.append(PushoverStep(
            step_no, displacement, base_shear, displacements, rotations, moments))

    record(0)
    for step_no in range(1, steps + 1):
        rc = ops.analyze(1)
        if rc != 0:
            raise RuntimeError(
                f"Pushover failed at step {step_no} of {steps} "
                f"(control displacement {result.steps[-1].displacement:.3f} mm, "
                f"OpenSees return code {rc}).")
        record(step_no)

    result.log = "\n".join(log)
    return result


def run_modal(project: Project, nmodes: int = 6) -> ModalResults:
    errors, _warnings = check_model(project)
    if errors:
        raise ValueError("Model check failed:\n• " + "\n• ".join(errors))
    log: List[str] = []
    log += build(project, None)
    ops.wipeAnalysis()
    ops.constraints("Plain")
    ops.numberer("RCM")
    ops.system("BandGen")
    ops.algorithm("Linear")
    ops.analysis("Transient")
    free = 6 * len(project.nodes) - sum(
        sum(1 for b in n.support if b) for n in project.nodes.values())
    n = max(1, min(int(nmodes), max(1, free - 1)))
    log.append(f"Requested {nmodes} modes, solving {n} (free DOF: {free}).")
    try:
        eig = ops.eigen("-fullGenLapack", n)
    except Exception:
        eig = ops.eigen(n)

    res = ModalResults(log="\n".join(log))
    if not eig:
        raise RuntimeError("No eigenvalues were computed - check the model mass.")

    for i, lam in enumerate(eig, start=1):
        lam = float(lam)
        w = math.sqrt(max(lam, 0.0))
        mr = ModeResult(i, lam, w, (2 * math.pi / w) if w > 0 else 0.0,
                        (w / (2 * math.pi)) if w > 0 else 0.0)
        res.modes.append(mr)
        shape: Dict[int, List[float]] = {}
        for tag in project.nodes:
            shape[tag] = [float(ops.nodeEigenvector(tag, i, d)) for d in range(1, 7)]
        peak = max((math.sqrt(sum(v * v for v in s[:3])) for s in shape.values()), default=0.0)
        if peak > 0:
            for tag in shape:
                shape[tag] = [v / peak for v in shape[tag]]
        res.shapes[i] = shape
    return res


# --------------------------------------------------------------------------- #
# Tcl export
# --------------------------------------------------------------------------- #
def export_tcl(project: Project) -> str:
    L: List[str] = []
    A = L.append
    A("# OpenSees Tcl model generated by OpenSees Studio")
    A("# Units: kN, mm, tonne, s")
    A("wipe")
    A("model BasicBuilder -ndm 3 -ndf 6")
    A("")
    A("# ---------------- materials ----------------")
    for m in project.materials.values():
        cmd = _material_command(m)
        A("uniaxialMaterial " + " ".join(_tcl(v) for v in cmd[1:]))
    A("")
    A("# ---------------- nodes --------------------")
    for n in project.nodes.values():
        A(f"node {n.tag} {_num(n.x)} {_num(n.y)} {_num(n.z)}")
    A("")
    A("# ---------------- supports -----------------")
    for n in project.nodes.values():
        if any(n.support):
            A(f"fix {n.tag} " + " ".join("1" if b else "0" for b in n.support))
    A("")
    A("# ---------------- elements -----------------")
    tag = 1
    for e in project.elements.values():
        mat = project.material_of(e)
        sec = _ensure_section(project.section_of(e))
        if e.kind == "truss":
            A(f"element truss {e.tag} {e.nodes[0]} {e.nodes[1]} {_num(sec.A)} {mat.tag}")
        elif e.kind == "shell":
            st = 900000 + e.tag
            A(f"nDMaterial ElasticIsotropic {st} {_num(mat.E)} {_num(mat.nu)} {_num(mat.rho)}")
            A(f"section PlateFiber {st} {st} {_num(e.thickness)}")
            A(f"element ShellMITC4 {e.tag} " + " ".join(str(t) for t in e.nodes[:4]) + f" {st}")
        else:
            p = project.node_xyz(e.nodes[0])
            q = project.node_xyz(e.nodes[1])
            vx = e.vecxz or auto_vecxz(p, q)
            A(f"geomTransf Linear {tag} {_num(vx[0])} {_num(vx[1])} {_num(vx[2])}")
            A(f"element elasticBeamColumn {e.tag} {e.nodes[0]} {e.nodes[1]} "
              f"{_num(sec.A)} {_num(mat.E)} {_num(mat.G)} {_num(sec.J)} "
              f"{_num(sec.Iy)} {_num(sec.Iz)} {tag}")
            tag += 1
    A("")
    A("# ---------------- loads --------------------")
    ts = 1
    for case in project.cases:
        A(f"timeSeries Linear {ts}")
        A(f"pattern Plain {ts} {ts} {{")
        for nl in project.nodal_loads:
            if nl.case == case and any(abs(v) > 0 for v in nl.values):
                A("  load %d %s" % (nl.node, " ".join(_num(v) for v in nl.values)))
        for el in project.elem_loads:
            if el.case != case:
                continue
            if el.kind == "uniform" and not el.trapezoid:
                wy, wz, _wx = _local_components(project, project.elements[el.elem],
                                                el.direction, el.value, el.value2, False)
                A(f"  eleLoad -ele {el.elem} -type -beamUniform {_num(wy)} {_num(wz)}")
            elif el.kind == "point":
                py, pz, _px = _local_components(project, project.elements[el.elem],
                                                el.direction, el.value, el.value2, False)
                A(f"  eleLoad -ele {el.elem} -type -beamPoint {_num(py)} "
                  f"{_num(pz)} {_num(el.position)}")
        sw = project.self_weight.get(case, 0.0)
        if abs(sw) > 1e-12:
            A(f"  # self weight, factor {_num(sw)}")
            for e in project.elements.values():
                if len(e.nodes) < 2:
                    continue
                mat = project.material_of(e)
                sec = _ensure_section(project.section_of(e))
                w_unit = mat.rho * G_ACC * 1e-3 * sw
                if e.kind == "truss":
                    f = -w_unit * sec.A * project.element_length(e) / 2.0
                    for t in e.nodes[:2]:
                        A(f"  load {t} 0 0 {_num(f)} 0 0 0")
                elif e.kind == "shell":
                    continue
                else:
                    wy, wz, _wx = _project_vec(project, e, (0.0, 0.0, -w_unit * sec.A))
                    A(f"  eleLoad -ele {e.tag} -type -beamUniform {_num(wy)} {_num(wz)}")
        A("}")
        ts += 1

    if project.combos:
        A("")
        A("# ---------------- load combinations -------")
        for combo in project.combos.values():
            terms = " + ".join(f"{_num(f)}*{c}" for c, f in combo.factors)
            A(f"# {combo.name} ({combo.kind}): {terms}")
        A("# Apply a combination by scaling the matching pattern factors,")
        A("# e.g. pattern Plain 100 1 -fact 1.2 { ... }")
    A("")
    A("# ---------------- analysis ------------------")
    A("constraints Plain")
    A("numberer RCM")
    A("system BandGen")
    A("algorithm Linear")
    A("integrator LoadControl 1.0")
    A("analysis Static")
    A('puts "Analysis terminated with code [analyze 1]"')
    A("")
    A('puts "Node displacements:"')
    for n in project.nodes.values():
        A(f'puts "  node {n.tag}: [nodeDisp {n.tag}]"')
    return "\n".join(L)


def _num(v) -> str:
    if isinstance(v, float):
        if abs(v) >= 1e-6 or v == 0:
            s = f"{v:.10g}"
        else:
            s = f"{v:.6e}"
        return s
    return str(v)


def _tcl(v) -> str:
    if isinstance(v, str) and not v.replace(".", "").replace("-", "").isdigit():
        return v
    return _num(v)
