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


SECTION_SHAPES = ("Rectangle", "Circle", "Pipe", "Box", "I-Shape", "User")


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

    # ------------------------------------------------------------------ #
    def compute(self) -> None:
        b, h, d, t, tw, tf = self.b, self.h, self.d, self.t, self.tw, self.tf
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
        # "User" keeps the values entered by the user

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "Section":
        s = Section(int(d["tag"]))
        for k, v in d.items():
            if hasattr(s, k) and k != "tag":
                setattr(s, k, v)
        return s


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


LOAD_DIRECTIONS = ("local-y", "local-z", "Global X", "Global Y", "Global Z")


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

    def next_load(self) -> int:
        return max([l.tag for l in self.nodal_loads] + [l.tag for l in self.elem_loads] + [0]) + 1

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
