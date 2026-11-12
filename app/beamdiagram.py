"""Beam force diagrams computed from end forces and member loads.

OpenSees returns only the element end forces for an elasticBeamColumn.  The
internal force distribution follows from equilibrium with the loads applied
between the ends.  This module rebuilds that distribution for the result
viewer.  Units are the model units: kN, mm.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from .model import G_ACC, Element, Project
from .opsgen import (_local_components, _project_vec, _scenario_factors,
                     _ensure_section, auto_vecxz, local_axes)

COMPONENTS: Tuple[str, ...] = ("Fx", "Vy", "Vz", "Mx", "My", "Mz")
MOMENT_COMPONENTS = {"Mx", "My", "Mz"}
COMPONENT_TITLES = {
    "Fx": "Axial force Fx",
    "Vy": "Shear force Vy",
    "Vz": "Shear force Vz",
    "Mx": "Torsion Mx",
    "My": "Bending moment My",
    "Mz": "Bending moment Mz",
}

# Local load record:
#   ("uniform", wy, wz)  - kN/mm over the whole element
#   ("point", py, pz, a) - kN at fraction a of the element length
LoadRecord = Tuple


def _add_uniform(records: Dict[int, List[LoadRecord]], tag: int,
                 wy: float, wz: float) -> None:
    if abs(wy) < 1e-15 and abs(wz) < 1e-15:
        return
    records.setdefault(tag, []).append(("uniform", wy, wz))


def beam_load_records(project: Project,
                      scenario: str) -> Dict[int, List[LoadRecord]]:
    """Local beam loads for *scenario* (a case or a combination)."""
    records: Dict[int, List[LoadRecord]] = {}
    factors = _scenario_factors(project, scenario)

    for case, factor in factors:
        if abs(factor) < 1e-15:
            continue

        # ---- explicit element loads ----------------------------------
        for load in project.elem_loads:
            if load.case != case:
                continue
            e = project.elements.get(load.elem)
            if e is None or e.kind != "beam" or len(e.nodes) < 2:
                continue
            if load.kind == "point":
                py, pz, _px = _local_components(
                    project, e, load.direction, load.value, load.value2, False)
                a = min(max(float(load.position), 1e-4), 1.0 - 1e-4)
                if abs(py * factor) > 1e-15 or abs(pz * factor) > 1e-15:
                    records.setdefault(e.tag, []).append(
                        ("point", py * factor, pz * factor, a))
                continue

            w1y, w1z, _ = _local_components(
                project, e, load.direction, load.value, load.value2, False)
            if load.trapezoid and abs(load.value2) > 0:
                # The solver represents a trapezoid by 11 point loads.  Use
                # exactly the same approximation so diagrams close at the j end.
                w2y, w2z, _ = _local_components(
                    project, e, load.direction, load.value2, load.value2, False)
                n = 11
                seg = 1.0 / n
                for i in range(n):
                    x = (i + 0.5) / n
                    wy = (w1y + (w2y - w1y) * x) * factor
                    wz = (w1z + (w2z - w1z) * x) * factor
                    if abs(wy) > 1e-15 or abs(wz) > 1e-15:
                        records.setdefault(e.tag, []).append(
                            ("point", wy * seg, wz * seg, x))
            else:
                _add_uniform(records, e.tag, w1y * factor, w1z * factor)

        # ---- self weight ---------------------------------------------
        sw = project.self_weight.get(case, 0.0)
        if abs(sw) < 1e-15:
            continue
        for e in project.elements.values():
            if e.kind != "beam" or len(e.nodes) < 2:
                continue
            mat = project.material_of(e)
            if mat.rho <= 0:
                continue
            sec = _ensure_section(project.section_of(e))
            w_unit = mat.rho * G_ACC * 1e-3 * sw * factor
            wy, wz, _ = _project_vec(project, e, (0.0, 0.0, -w_unit * sec.A))
            _add_uniform(records, e.tag, wy, wz)

    return records


def _station_value(comp: str, x: float, force: Sequence[float],
                   uniform: Tuple[float, float],
                   points: List[Tuple[float, float, float]],
                   length: float) -> float:
    """Internal force at fraction *x* of the element length."""
    if comp == "Fx":
        return -force[0]
    if comp == "Mx":
        return -force[3]

    qy, qz = uniform
    py = sum(p[0] for p in points if p[2] <= x + 1e-12)
    pz = sum(p[1] for p in points if p[2] <= x + 1e-12)
    xm = x * length

    if comp == "Vy":
        return -force[1] - qy * xm - py
    if comp == "Vz":
        return -force[2] - qz * xm - pz
    if comp == "Mz":
        m = -force[5] + force[1] * xm + 0.5 * qy * xm * xm
        for p_y, _p_z, a in points:
            if a <= x + 1e-12:
                m += p_y * (xm - a * length)
        return m
    if comp == "My":
        m = -force[4] - force[2] * xm - 0.5 * qz * xm * xm
        for _p_y, p_z, a in points:
            if a <= x + 1e-12:
                m -= p_z * (xm - a * length)
        return m
    return 0.0


def diagram_series(project: Project, res, element: Element, scenario: str,
                   component: str, loads: Optional[List[LoadRecord]] = None,
                   samples: int = 21) -> List[Tuple[float, float]]:
    """Return ``[(x/L, value), ...]`` for one element and component.

    Point loads are represented by closely spaced stations on either side so
    the shear diagram shows its jump discontinuously.
    """
    if component not in COMPONENTS or element.kind not in ("beam", "truss"):
        return []
    force = res.element_forces.get(element.tag) or []
    if element.kind == "truss":
        if component != "Fx" or not force:
            return []
        return [(0.0, float(force[0])), (1.0, float(force[0]))]
    if len(force) < 12:
        return []

    length = project.element_length(element)
    if length <= 1e-9:
        return []

    if loads is None:
        loads = beam_load_records(project, scenario).get(element.tag, [])
    uniform = (sum(r[1] for r in loads if r[0] == "uniform"),
               sum(r[2] for r in loads if r[0] == "uniform"))
    points = [(r[1], r[2], r[3]) for r in loads if r[0] == "point"]

    xs = {0.0, 1.0}
    count = max(int(samples), 2)
    for i in range(1, count - 1):
        xs.add(i / (count - 1))
    for _py, _pz, a in points:
        a = min(max(a, 1e-6), 1.0 - 1e-6)
        xs.add(max(0.0, a - 1e-7))
        xs.add(min(1.0, a + 1e-7))

    out = [(x, _station_value(component, x, force, uniform, points, length))
           for x in sorted(xs)]
    return out


def series_extreme(series: List[Tuple[float, float]]) -> Tuple[float, float]:
    """Return (signed absolute maximum, position) of a series."""
    if not series:
        return 0.0, 0.0
    x, v = max(series, key=lambda item: abs(item[1]))
    return v, x
