"""Data model for OpenSees Studio.

Units used throughout the application: kN, mm, tonne, s.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

G_ACC = 9806.65  # mm/s^2


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fmt(v: float, digits: int = 3) -> str:
    if v is None:
        return ""
    if abs(v) >= 1e5 or (abs(v) < 1e-3 and v != 0):
        return f"{v:.{digits}e}"
    s = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


# --------------------------------------------------------------------------- #
# entities
# --------------------------------------------------------------------------- #
@dataclass
class Node:
    tag: int
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    support: List[bool] = field(default_factory=lambda: [False] * 6)
    spring: List[float] = field(default_factory=lambda: [0.0] * 6)

    @property
    def xyz(self) -> Tuple[float, float, float]:
        return (self.x, self.y, self.z)

    @property
    def fixed(self) -> bool:
        return any(self.support)

    def support_code(self) -> str:
        return "".join("1" if b else "0" for b in self.support)

    def to_dict(self) -> dict:
        return {"tag": self.tag, "x": self.x, "y": self.y, "z": self.z,
                "support": list(self.support), "spring": list(self.spring)}

    @staticmethod
    def from_dict(d: dict) -> "Node":
        return Node(int(d["tag"]), _f(d.get("x")), _f(d.get("y")), _f(d.get("z")),
                    [bool(b) for b in d.get("support", [False] * 6)],
                    [_f(s) for s in d.get("spring", [0.0] * 6)])


MATERIAL_KINDS = ("Elastic", "ElasticPP", "Steel02", "Concrete02")


@dataclass
class Material:
    tag: int
    name: str = "Steel"
    kind: str = "Elastic"
    E: float = 200.0          # kN/mm^2
    nu: float = 0.3
    rho: float = 7.85e-9      # tonne/mm^3
    fy: float = 0.235         # kN/mm^2
    b: float = 0.01
    fc: float = 0.030
    epsc0: float = -0.002
    fpcu: float = -0.006
    epsU: float = -0.02

    @property
    def G(self) -> float:
        return self.E / (2.0 * (1.0 + self.nu))

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "Material":
        m = Material(int(d["tag"]))
        for k, v in d.items():
            if hasattr(m, k) and k != "tag":
                setattr(m, k, v)
        return m


SECTION_SHAPES = ("Rectangle", "Circle", "Hexagon", "Octagon", "Box", "Pipe",
                  "I-Shape", "L-Shape", "T-Shape", "User")

SHAPE_LABELS = {
    "Rectangle": "Solid rectangle",
    "Circle": "Solid circle",
    "Hexagon": "Solid hexagon",
    "Octagon": "Solid octagon",
    "Box": "Rectangular hollow",
    "Pipe": "Circular hollow / pipe",
    "I-Shape": "I / H section",
    "L-Shape": "Angle (L)",
    "T-Shape": "Tee (T)",
    "User": "User-defined properties",
}


@dataclass
class Section:
    tag: int
    name: str = "Section"
    shape: str = "Rectangle"
    b: float = 300.0      # width, local y
    h: float = 600.0      # depth, local z
    d: float = 400.0      # diameter
    t: float = 12.0       # wall / flange thickness
    tw: float = 10.0      # web thickness
    tf: float = 15.0      # flange thickness
    A: float = 0.0
    Iy: float = 0.0
    Iz: float = 0.0
    J: float = 0.0
    catalog: str = "Custom"
    designation: str = ""
    family: str = ""
    cy: float = 0.0
    cz: float = 0.0

    @property
    def is_standard(self) -> bool:
        return bool(self.designation) and self.catalog not in ("", "Custom")

    @property
    def mass_per_length(self) -> float:
        """Approximate steel mass in kg/m (rho = 7.85 t/m3)."""
        return self.A * 7.85e-3

    # ------------------------------------------------------------------ #
    def compute(self) -> None:
        b, h, d, t, tw, tf = self.b, self.h, self.d, self.t, self.tw, self.tf
        self.cy = self.cz = 0.0
        if self.shape == "Rectangle":
            self.A = b * h
            self.Iy = b * h ** 3 / 12.0
            self.Iz = h * b ** 3 / 12.0
            self.J = _rect_torsion(max(b, h), min(b, h))
        elif self.shape == "Circle":
            self.A = math.pi * d ** 2 / 4.0
            self.Iy = self.Iz = math.pi * d ** 4 / 64.0
            self.J = math.pi * d ** 4 / 32.0
        elif self.shape == "Pipe":
            di = max(d - 2 * t, 1e-6)
            self.A = math.pi * (d ** 2 - di ** 2) / 4.0
            self.Iy = self.Iz = math.pi * (d ** 4 - di ** 4) / 64.0
            self.J = 2.0 * self.Iy
        elif self.shape == "Hexagon" or self.shape == "Octagon":
            n = 6 if self.shape == "Hexagon" else 8
            pts = _regular_polygon(n, max(d, 1e-6))
            area, cy, cz, iy, iz = _polygon_props(pts)
            self.A, self.cy, self.cz = area, cy, cz
            self.Iy, self.Iz = iy, iz
            self.J = 0.75 * (iy + iz)
        elif self.shape == "Box":
            bi = max(b - 2 * t, 1e-6)
            hi = max(h - 2 * t, 1e-6)
            self.A = b * h - bi * hi
            self.Iy = (b * h ** 3 - bi * hi ** 3) / 12.0
            self.Iz = (h * b ** 3 - hi * bi ** 3) / 12.0
            self.J = _rect_torsion(max(b, h), min(b, h)) - _rect_torsion(max(bi, hi), min(bi, hi))
        elif self.shape == "I-Shape":
            hw = max(h - 2 * tf, 1e-6)
            self.A = 2 * b * tf + hw * tw
            self.Iy = (b * h ** 3 - (b - tw) * hw ** 3) / 12.0
            self.Iz = (2 * tf * b ** 3 + hw * tw ** 3) / 12.0
            self.J = (2 * b * tf ** 3 + hw * tw ** 3) / 3.0
        elif self.shape == "L-Shape":
            leg_b = max(b, t)
            leg_h = max(h, t)
            pts = [(0.0, 0.0), (leg_b, 0.0), (leg_b, t),
                   (t, t), (t, leg_h), (0.0, leg_h)]
            area, cy, cz, iy, iz = _polygon_props(pts)
            self.A, self.cy, self.cz = area, cy, cz
            self.Iy, self.Iz = iy, iz
            self.J = (_rect_torsion(max(leg_b, t), min(leg_b, t)) +
                      _rect_torsion(max(leg_h - t, t), min(leg_h - t, t)))
        elif self.shape == "T-Shape":
            flange_t = min(max(tf, 1e-6), h)
            web_t = min(max(tw, 1e-6), b)
            web_h = max(h - flange_t, 1e-6)
            pts = [(-web_t / 2, 0.0), (web_t / 2, 0.0),
                   (web_t / 2, web_h), (b / 2, web_h),
                   (b / 2, h), (-b / 2, h),
                   (-b / 2, web_h), (-web_t / 2, web_h)]
            area, cy, cz, iy, iz = _polygon_props(pts)
            self.A, self.cy, self.cz = area, cy, cz
            self.Iy, self.Iz = iy, iz
            self.J = (_rect_torsion(max(b, flange_t), min(b, flange_t)) +
                      _rect_torsion(max(web_h, web_t), min(web_h, web_t)))
        # "User" keeps the values entered by the user

    def outline(self):
        """Return (outer, inner) section outlines in local (y, z) mm."""
        b, h, d, t, tw, tf = self.b, self.h, self.d, self.t, self.tw, self.tf
        if self.shape == "Circle":
            return [_regular_polygon(24, max(d, 1.0)), None]
        if self.shape == "Pipe":
            ro = max(d / 2.0, 0.5)
            ri = max(ro - t, 0.0)
            inner = (_regular_polygon(24, 2.0 * ri) if ri > 0.5 else None)
            return [_regular_polygon(24, max(d, 1.0)), inner]
        if self.shape == "Hexagon":
            return [_regular_polygon(6, max(d, 1.0)), None]
        if self.shape == "Octagon":
            return [_regular_polygon(8, max(d, 1.0)), None]
        if self.shape == "I-Shape":
            tw = min(max(tw, 1.0), b)
            tf = min(max(tf, 1.0), 0.49 * h)
            outer = [(-b / 2, h / 2), (b / 2, h / 2), (b / 2, h / 2 - tf),
                     (tw / 2, h / 2 - tf), (tw / 2, -h / 2 + tf), (b / 2, -h / 2 + tf),
                     (b / 2, -h / 2), (-b / 2, -h / 2), (-b / 2, -h / 2 + tf),
                     (-tw / 2, -h / 2 + tf), (-tw / 2, h / 2 - tf), (-b / 2, h / 2 - tf)]
            return [outer, None]
        if self.shape == "Box":
            outer = [(-b / 2, -h / 2), (b / 2, -h / 2), (b / 2, h / 2), (-b / 2, h / 2)]
            bi, hi = b - 2 * t, h - 2 * t
            inner = ([(-bi / 2, -hi / 2), (bi / 2, -hi / 2),
                      (bi / 2, hi / 2), (-bi / 2, hi / 2)] if bi > 1 and hi > 1 else None)
            return [outer, inner]
        if self.shape == "L-Shape":
            leg_b = max(b, t)
            leg_h = max(h, t)
            pts = [(0.0, 0.0), (leg_b, 0.0), (leg_b, t),
                   (t, t), (t, leg_h), (0.0, leg_h)]
            return [[(y - self.cy, z - self.cz) for y, z in pts], None]
        if self.shape == "T-Shape":
            flange_t = min(max(tf, 1e-6), h)
            web_t = min(max(tw, 1e-6), b)
            web_h = max(h - flange_t, 1e-6)
            pts = [(-web_t / 2, 0.0), (web_t / 2, 0.0),
                   (web_t / 2, web_h), (b / 2, web_h),
                   (b / 2, h), (-b / 2, h),
                   (-b / 2, web_h), (-web_t / 2, web_h)]
            return [[(y - self.cy, z - self.cz) for y, z in pts], None]
        if self.shape == "User" and self.A > 0:
            side = math.sqrt(self.A)
            b = h = max(side, 1.0)
        return [[(-b / 2, -h / 2), (b / 2, -h / 2),
                 (b / 2, h / 2), (-b / 2, h / 2)], None]

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "Section":
        s = Section(int(d["tag"]))
        for k, v in d.items():
            if hasattr(s, k) and k != "tag":
                setattr(s, k, v)
        return s


def _regular_polygon(n: int, diameter: float,
                     rotation: Optional[float] = None) -> List[Tuple[float, float]]:
    """Vertices of a regular polygon centred on the origin."""
    radius = max(diameter, 1e-9) / 2.0
    start = math.pi / n if rotation is None else rotation
    return [(radius * math.cos(start + i * 2.0 * math.pi / n),
             radius * math.sin(start + i * 2.0 * math.pi / n))
            for i in range(n)]


def _polygon_props(points: List[Tuple[float, float]]):
    """Area, centroid and centroidal second moments of a polygon.

    ``points`` are (y, z) pairs.  Returns (A, cy, cz, Iy, Iz), where Iy is
    the integral of z^2 and Iz the integral of y^2 over the area.
    """
    if len(points) < 3:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    a2 = cy = cz = iy0 = iz0 = 0.0
    for (y0, z0), (y1, z1) in zip(points, points[1:] + points[:1]):
        cross = y0 * z1 - y1 * z0
        a2 += cross
        cy += (y0 + y1) * cross
        cz += (z0 + z1) * cross
        iy0 += (z0 * z0 + z0 * z1 + z1 * z1) * cross
        iz0 += (y0 * y0 + y0 * y1 + y1 * y1) * cross
    area = 0.5 * a2
    if abs(area) < 1e-12:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    cy /= 6.0 * area
    cz /= 6.0 * area
    iy = iy0 / 12.0 - area * cz * cz
    iz = iz0 / 12.0 - area * cy * cy
    return abs(area), cy, cz, abs(iy), abs(iz)


def _rect_torsion(a: float, b: float) -> float:
    """Torsion constant of a solid rectangle (a >= b)."""
    if a <= 0 or b <= 0:
        return 0.0
    r = b / a
    return a * b ** 3 * (1.0 / 3.0 - 0.21 * r * (1.0 - r ** 4 / 12.0))


ELEMENT_KINDS = ("beam", "truss", "shell")


@dataclass
class Element:
    tag: int
    kind: str = "beam"
    nodes: List[int] = field(default_factory=list)
    mat: int = 1
    sec: int = 1
    vecxz: Optional[List[float]] = None   # None = automatic local z axis
    thickness: float = 100.0
    group: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "Element":
        e = Element(int(d["tag"]))
        for k, v in d.items():
            if hasattr(e, k) and k != "tag":
                setattr(e, k, v)
        return e


@dataclass
class HingeDefinition:
    """A reusable lumped plastic-hinge property definition."""

    tag: int
    name: str = "Hinge"
    model: str = "Trilinear"
    length_ratio: float = 0.10
    fy: float = 0.235
    post_yield_ratio: float = 0.02
    ductility: float = 10.0
    pinching: float = 0.8
    damage: float = 0.02
    beta: float = 0.4

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "HingeDefinition":
        h = HingeDefinition(int(d["tag"]))
        for k, v in d.items():
            if hasattr(h, k) and k != "tag":
                setattr(h, k, v)
        return h


LOAD_DIRECTIONS = ("local-y", "local-z", "Global X", "Global Y", "Global Z")

PUSHOVER_DEFAULTS = {
    "gravity_case": "",
    "lateral_case": "",
    "control_node": 0,
    "control_dof": 1,
    "target_displacement": 100.0,     # mm
    "steps": 20,
    "hinge_model": "Trilinear",
    "hinge_length_ratio": 0.10,
    "fy": 0.235,                      # kN/mm^2
    "post_yield_ratio": 0.02,
    "ductility": 10.0,
    "pinching": 0.8,
    "damage": 0.02,
    "beta": 0.4,
}


@dataclass
class LoadCase:
    name: str = "DL"
    kind: str = "Dead"
    note: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "LoadCase":
        return LoadCase(str(d.get("name", "DL")), str(d.get("kind", "Dead")), str(d.get("note", "")))


LOADCASE_KINDS = ("Dead", "Live", "Wind", "Seismic", "Snow", "Temperature", "Other")


@dataclass
class NodalLoad:
    tag: int
    node: int
    case: str
    values: List[float] = field(default_factory=lambda: [0.0] * 6)

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "NodalLoad":
        return NodalLoad(int(d["tag"]), int(d["node"]), str(d["case"]),
                         [_f(v) for v in d.get("values", [0.0] * 6)])


@dataclass
class ElementLoad:
    tag: int
    elem: int
    case: str
    kind: str = "uniform"          # uniform | point
    direction: str = "local-z"
    value: float = 0.0             # kN/mm for uniform, kN for point
    value2: float = 0.0            # optional end value for trapezoidal
    position: float = 0.5          # point-load location, fraction of length
    trapezoid: bool = False

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "ElementLoad":
        e = ElementLoad(int(d["tag"]), int(d["elem"]), str(d["case"]))
        for k, v in d.items():
            if hasattr(e, k) and k != "tag":
                setattr(e, k, v)
        return e


@dataclass
class LoadCombination:
    name: str = "COMB1"
    factors: List[Tuple[str, float]] = field(default_factory=list)
    kind: str = "Add"

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind,
                "factors": [[c, f] for c, f in self.factors]}

    @staticmethod
    def from_dict(d: dict) -> "LoadCombination":
        return LoadCombination(str(d.get("name", "COMB1")),
                               [(str(c), _f(f)) for c, f in d.get("factors", [])],
                               str(d.get("kind", "Add")))


COMBINATION_KINDS = ("Add", "SRSS", "ABS", "Envelope")


# --------------------------------------------------------------------------- #
# project
# --------------------------------------------------------------------------- #
DEFAULT_SETTINGS = {
    "static_steps": 1.0,
    "modal_modes": 6,
    "mass_from_density": True,
    "last_case": "DL",
    "last_combo": "",
    "deformed_scale": None,   # None = auto
    "force_unit": "kN",       # display only; model data is always kN-mm-t
    "length_unit": "m",
}


class Project:
    def __init__(self) -> None:
        self.nodes: Dict[int, Node] = {}
        self.elements: Dict[int, Element] = {}
        self.materials: Dict[int, Material] = {}
        self.sections: Dict[int, Section] = {}
        self.cases: Dict[str, LoadCase] = {}
        self.nodal_loads: List[NodalLoad] = []
        self.elem_loads: List[ElementLoad] = []
        self.self_weight: Dict[str, float] = {}
        self.combos: Dict[str, LoadCombination] = {}
        self.hinge_defs: Dict[int, HingeDefinition] = {}
        self.hinge_assignments: Dict[int, int] = {}
        self.settings: dict = dict(DEFAULT_SETTINGS)
        self.title: str = "Untitled"
        self.path: str = ""

    # ---------------------------------------------------------------- tags
    @staticmethod
    def _next(tags) -> int:
        return max(tags, default=0) + 1

    def next_node(self) -> int:
        return self._next(self.nodes.keys())

    def next_element(self) -> int:
        return self._next(self.elements.keys())

    def next_material(self) -> int:
        return self._next(self.materials.keys())

    def next_section(self) -> int:
        return self._next(self.sections.keys())

    def next_hinge(self) -> int:
        return self._next(self.hinge_defs.keys())

    def next_load(self) -> int:
        return max([l.tag for l in self.nodal_loads] + [l.tag for l in self.elem_loads] + [0]) + 1

    def subdivide_elements(self, tags: List[int],
                           divisions: int) -> Tuple[List[int], List[int]]:
        """Split two-node beam/truss elements into equal-length parts.

        Intermediate nodes are created or reused, and element loads are
        redistributed onto the new segments.  Returns (new_nodes, new_elements).
        """
        if divisions < 2:
            raise ValueError("divisions must be at least 2")
        targets = []
        for tag in tags:
            e = self.elements.get(tag)
            if (e is not None and len(e.nodes) == 2
                    and e.kind in ("beam", "truss")
                    and all(n in self.nodes for n in e.nodes)
                    and self.element_length(e) > 1e-9):
                targets.append(tag)

        coords = {(round(n.x, 3), round(n.y, 3), round(n.z, 3)): tag
                  for tag, n in self.nodes.items()}
        new_nodes: List[int] = []
        new_elements: List[int] = []

        for tag in targets:
            e = self.elements[tag]
            p0 = self.node_xyz(e.nodes[0])
            p1 = self.node_xyz(e.nodes[1])
            chain = [e.nodes[0]]
            for i in range(1, divisions):
                f = i / divisions
                xyz = tuple(a + (b - a) * f for a, b in zip(p0, p1))
                key = tuple(round(v, 3) for v in xyz)
                node_tag = coords.get(key)
                if node_tag is None:
                    node_tag = self.next_node()
                    self.nodes[node_tag] = Node(node_tag, *xyz)
                    coords[key] = node_tag
                    new_nodes.append(node_tag)
                chain.append(node_tag)
            chain.append(e.nodes[1])

            loads = [loader for loader in self.elem_loads if loader.elem == tag]
            new_tags: List[int] = []
            for i in range(divisions):
                new_tag = self.next_element()
                self.elements[new_tag] = Element(
                    new_tag, e.kind, [chain[i], chain[i + 1]], e.mat, e.sec,
                    list(e.vecxz) if e.vecxz else None, e.thickness, e.group)
                new_tags.append(new_tag)
            self.elements.pop(tag, None)
            self.elem_loads = [loader for loader in self.elem_loads
                               if loader.elem != tag]

            for load in loads:
                if load.kind == "point":
                    pos = min(max(float(load.position), 0.0), 1.0)
                    idx = min(int(pos * divisions), divisions - 1)
                    local = pos * divisions - idx
                    self.elem_loads.append(ElementLoad(
                        self.next_load(), new_tags[idx], load.case, "point",
                        load.direction, load.value, load.value2, local, False))
                    continue
                trapezoid = bool(load.trapezoid and abs(load.value2) > 0)
                for i, new_tag in enumerate(new_tags):
                    start = load.value
                    end = load.value2
                    if trapezoid:
                        f0, f1 = i / divisions, (i + 1) / divisions
                        start = load.value + (load.value2 - load.value) * f0
                        end = load.value + (load.value2 - load.value) * f1
                    self.elem_loads.append(ElementLoad(
                        self.next_load(), new_tag, load.case, "uniform",
                        load.direction, start, end, load.position, trapezoid))
            new_elements.extend(new_tags)

        return new_nodes, new_elements

    # ------------------------------------------------------------ queries
    def node_xyz(self, tag: int) -> Tuple[float, float, float]:
        n = self.nodes.get(tag)
        if n is None:
            return (0.0, 0.0, 0.0)
        return n.xyz

    def element_length(self, e: Element) -> float:
        if len(e.nodes) < 2:
            return 0.0
        p = self.node_xyz(e.nodes[0])
        q = self.node_xyz(e.nodes[1])
        return math.dist(p, q)

    def material_of(self, e: Element) -> Material:
        return self.materials.get(e.mat) or Material(e.mat)

    def section_of(self, e: Element) -> Section:
        return self.sections.get(e.sec) or Section(e.sec)

    def case_names(self) -> List[str]:
        return list(self.cases.keys())

    def scenario_names(self) -> List[str]:
        return list(self.cases.keys()) + list(self.combos.keys())

    def pushover_settings(self) -> dict:
        settings = dict(PUSHOVER_DEFAULTS)
        settings.update(self.settings.get("pushover", {}))
        return settings

    def loads_of_case(self, case: str):
        return ([l for l in self.nodal_loads if l.case == case],
                [l for l in self.elem_loads if l.case == case])

    def bbox(self):
        if not self.nodes:
            return (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
        xs = [n.x for n in self.nodes.values()]
        ys = [n.y for n in self.nodes.values()]
        zs = [n.z for n in self.nodes.values()]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    # -------------------------------------------------------- serialization
    def to_dict(self) -> dict:
        return {
            "format": "OpenSeesStudio",
            "version": 1,
            "title": self.title,
            "units": "kN-mm-t",
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "elements": [e.to_dict() for e in self.elements.values()],
            "materials": [m.to_dict() for m in self.materials.values()],
            "sections": [s.to_dict() for s in self.sections.values()],
            "cases": [c.to_dict() for c in self.cases.values()],
            "nodal_loads": [l.to_dict() for l in self.nodal_loads],
            "elem_loads": [l.to_dict() for l in self.elem_loads],
            "self_weight": self.self_weight,
            "combos": [c.to_dict() for c in self.combos.values()],
            "hinge_defs": [h.to_dict() for h in self.hinge_defs.values()],
            "hinge_assignments": [
                {"element": element, "hinge": hinge}
                for element, hinge in self.hinge_assignments.items()],
            "settings": self.settings,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        p = cls()
        p.title = d.get("title", "Untitled")
        p.nodes = {n.tag: n for n in (Node.from_dict(x) for x in d.get("nodes", []))}
        p.elements = {e.tag: e for e in (Element.from_dict(x) for x in d.get("elements", []))}
        p.materials = {m.tag: m for m in (Material.from_dict(x) for x in d.get("materials", []))}
        p.sections = {s.tag: s for s in (Section.from_dict(x) for x in d.get("sections", []))}
        p.cases = {c.name: c for c in (LoadCase.from_dict(x) for x in d.get("cases", []))}
        p.nodal_loads = [NodalLoad.from_dict(x) for x in d.get("nodal_loads", [])]
        p.elem_loads = [ElementLoad.from_dict(x) for x in d.get("elem_loads", [])]
        p.self_weight = {str(k): _f(v) for k, v in d.get("self_weight", {}).items()}
        p.combos = {c.name: c for c in (LoadCombination.from_dict(x) for x in d.get("combos", []))}
        p.hinge_defs = {h.tag: h for h in (
            HingeDefinition.from_dict(x) for x in d.get("hinge_defs", []))}
        for item in d.get("hinge_assignments", []):
            try:
                element = int(item["element"])
                hinge = int(item["hinge"])
            except (KeyError, TypeError, ValueError):
                continue
            if hinge in p.hinge_defs:
                p.hinge_assignments[element] = hinge
        legacy = d.get("hinges", [])
        if legacy and not p.hinge_defs:
            grouped = {}
            for raw in legacy:
                try:
                    element = int(raw["element"])
                except (KeyError, TypeError, ValueError):
                    continue
                key = (
                    str(raw.get("model", "Trilinear")),
                    round(float(raw.get("length_ratio", 0.10)), 9),
                    round(float(raw.get("fy", 0.235)), 9),
                    round(float(raw.get("post_yield_ratio", 0.02)), 9),
                    round(float(raw.get("ductility", 10.0)), 9),
                    round(float(raw.get("pinching", 0.8)), 9),
                    round(float(raw.get("damage", 0.02)), 9),
                    round(float(raw.get("beta", 0.4)), 9),
                )
                tag = grouped.get(key)
                if tag is None:
                    tag = p.next_hinge()
                    grouped[key] = tag
                    p.hinge_defs[tag] = HingeDefinition(
                        tag, f"Hinge {tag}", key[0], key[1], key[2], key[3],
                        key[4], key[5], key[6], key[7])
                p.hinge_assignments[element] = tag
        p.settings = dict(DEFAULT_SETTINGS)
        p.settings.update(d.get("settings", {}))
        return p

    def save(self, path: str) -> None:
        self.path = path
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def load(cls, path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as fh:
            p = cls.from_dict(json.load(fh))
        p.path = path
        p.title = p.title or "Untitled"
        return p

    def clone(self) -> "Project":
        c = Project.from_dict(self.to_dict())
        c.path = self.path
        return c


def default_project() -> Project:
    p = Project()
    p.title = "Untitled"
    p.materials[1] = Material(1, "Steel (S355)", "Elastic", E=200.0, nu=0.3,
                              rho=7.85e-9, fy=0.235)
    p.materials[2] = Material(2, "Concrete C30", "Elastic", E=30.0, nu=0.2,
                              rho=2.5e-9, fc=0.030)
    s = Section(1, "H 300x300x10x15", "I-Shape", b=300.0, h=300.0, tw=10.0, tf=15.0)
    s.compute()
    p.sections[1] = s
    s2 = Section(2, "Rect 300x600", "Rectangle", b=300.0, h=600.0)
    s2.compute()
    p.sections[2] = s2
    p.sections[3] = Section(3, "Plate 100 mm", "User", A=1.0, Iy=1.0, Iz=1.0, J=1.0)
    p.cases["DL"] = LoadCase("DL", "Dead")
    p.cases["LL"] = LoadCase("LL", "Live")
    p.combos["COMB1"] = LoadCombination("COMB1", [("DL", 1.0), ("LL", 1.0)])
    return p
