"""Structure wizards: frame, truss and girder-bridge templates."""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

from .model import Element, Node, Project

WIZARDS = {
    "frame2d": ("2D Frame", "Moment frame in the X-Z plane."),
    "frame3d": ("3D Frame", "Moment frame with bays in X and Y."),
    "truss2d": ("2D Truss", "Simply supported planar truss with parallel chords."),
    "truss3d": ("3D Truss", "Rectangular space truss with four chords."),
    "bridge": ("Girder Bridge", "Multi-span concrete or steel girder bridge grillage."),
}


class _Builder:
    """Appends nodes, beams and supports to a project with fresh tags."""

    def __init__(self, project: Project) -> None:
        self.p = project
        self._next_node_tag = project.next_node()
        self._next_element_tag = project.next_element()
        self.nodes: Dict[Tuple[float, float, float], int] = {}
        self.node_count = 0
        self.element_count = 0

    def node(self, x: float, y: float, z: float) -> int:
        key = (round(x, 3), round(y, 3), round(z, 3))
        tag = self.nodes.get(key)
        if tag is not None:
            return tag
        tag = self._next_node_tag
        self._next_node_tag += 1
        self.p.nodes[tag] = Node(tag, x, y, z)
        self.nodes[key] = tag
        self.node_count += 1
        return tag

    def beam(self, i: int, j: int, mat: int, sec: int,
             vecxz: List[float] | None, kind: str = "beam") -> None:
        tag = self._next_element_tag
        self._next_element_tag += 1
        self.p.elements[tag] = Element(tag, kind, [i, j], mat, sec,
                                       list(vecxz) if vecxz else None)
        self.element_count += 1

    def support(self, tag: int, dx=False, dy=False, dz=False,
                rx=False, ry=False, rz=False) -> None:
        self.p.nodes[tag].support = [dx, dy, dz, rx, ry, rz]


def _frame(p: Project, b: _Builder, spec: dict) -> None:
    bw = spec["bay_width"]
    bd = spec["bay_depth"]
    sh = spec["storey_height"]
    xs = [i * bw for i in range(spec["bays_x"] + 1)]
    ys = [j * bd for j in range(spec["bays_y"] + 1)]
    zs = [k * sh for k in range(spec["storeys"] + 1)]
    mat = spec["mat"]
    col, beam = spec["col_sec"], spec["beam_sec"]

    for x in xs:
        for y in ys:
            for k in range(len(zs) - 1):
                b.beam(b.node(x, y, zs[k]), b.node(x, y, zs[k + 1]),
                       mat, col, [1.0, 0.0, 0.0])
    for z in zs[1:]:
        for y in ys:
            for a, c in zip(xs, xs[1:]):
                b.beam(b.node(a, y, z), b.node(c, y, z), mat, beam, [0.0, 0.0, 1.0])
        for x in xs:
            for a, c in zip(ys, ys[1:]):
                b.beam(b.node(x, a, z), b.node(x, c, z), mat, beam, [0.0, 0.0, 1.0])
    for x in xs:
        for y in ys:
            b.support(b.node(x, y, 0.0), True, True, True, True, True, True)


def _planar_truss(b: _Builder, xs: List[float], y: float, height: float,
                  mat: int, sec: int) -> None:
    bottom = [b.node(x, y, 0.0) for x in xs]
    top = [b.node(x, y, height) for x in xs]
    n = len(xs) - 1
    for i in range(n):
        b.beam(bottom[i], bottom[i + 1], mat, sec, None, "truss")
        b.beam(top[i], top[i + 1], mat, sec, None, "truss")
    for i in range(n + 1):
        b.beam(bottom[i], top[i], mat, sec, None, "truss")
    for i in range(n):
        if i < n / 2:
            b.beam(bottom[i], top[i + 1], mat, sec, None, "truss")
        else:
            b.beam(top[i], bottom[i + 1], mat, sec, None, "truss")


def _truss(p: Project, b: _Builder, spec: dict) -> None:
    xs = [i * spec["panel_width"] for i in range(spec["panels"] + 1)]
    height = spec["height"]
    mat, sec = spec["mat"], spec["sec"]
    _planar_truss(b, xs, 0.0, height, mat, sec)

    if spec["kind"] == "truss3d":
        width = spec["width"]
        _planar_truss(b, xs, width, height, mat, sec)
        for x in xs:
            b.beam(b.node(x, 0.0, 0.0), b.node(x, width, 0.0), mat, sec, None, "truss")
            b.beam(b.node(x, 0.0, height), b.node(x, width, height),
                   mat, sec, None, "truss")
        for i in range(len(xs) - 1):
            b.beam(b.node(xs[i], 0.0, 0.0), b.node(xs[i + 1], width, 0.0),
                   mat, sec, None, "truss")
            b.beam(b.node(xs[i + 1], 0.0, 0.0), b.node(xs[i], width, 0.0),
                   mat, sec, None, "truss")
            b.beam(b.node(xs[i], 0.0, height), b.node(xs[i + 1], width, height),
                   mat, sec, None, "truss")
            b.beam(b.node(xs[i + 1], 0.0, height), b.node(xs[i], width, height),
                   mat, sec, None, "truss")
        b.support(b.node(xs[0], 0.0, 0.0), True, True, True)
        b.support(b.node(xs[0], width, 0.0), False, True, True)
        b.support(b.node(xs[-1], 0.0, 0.0), True, False, True)
        b.support(b.node(xs[-1], width, 0.0), False, False, True)
    else:
        b.support(b.node(xs[0], 0.0, 0.0), True, True, True)
        b.support(b.node(xs[-1], 0.0, 0.0), False, True, True)
    planar = spec["kind"] == "truss2d"
    for tag in b.nodes.values():
        node = p.nodes[tag]
        node.support = [node.support[0], node.support[1] or planar,
                        node.support[2], True, True, True]


def _bridge(p: Project, b: _Builder, spec: dict) -> None:
    spans = spec["spans"]
    length = spec["span_length"]
    width = spec["width"]
    girders = spec["girders"]
    spacing = spec["cross_spacing"]
    mat = spec["mat"]

    ys = [j * width / (girders - 1) for j in range(girders)]
    xs: List[float] = [0.0]
    for k in range(spans):
        start = k * length
        parts = max(1, math.ceil(length / max(spacing, 1e-6)))
        for i in range(1, parts + 1):
            xs.append(round(start + i * length / parts, 6))
    xs = sorted(set(xs))

    for y in ys:
        for a, c in zip(xs, xs[1:]):
            b.beam(b.node(a, y, 0.0), b.node(c, y, 0.0),
                   mat, spec["girder_sec"], [0.0, 0.0, 1.0])
    for x in xs:
        for a, c in zip(ys, ys[1:]):
            b.beam(b.node(x, a, 0.0), b.node(x, c, 0.0),
                   mat, spec["cross_sec"], [0.0, 0.0, 1.0])

    supports = sorted({k * length for k in range(spans + 1)})
    for x in supports:
        for y in ys:
            b.support(b.node(x, y, 0.0), False, False, True)
        if x == 0.0:
            b.support(b.node(x, ys[0], 0.0), True, True, True)
        else:
            b.support(b.node(x, ys[0], 0.0), False, True, True)


def generate(project: Project, spec: dict) -> Tuple[int, int]:
    """Create the wizard geometry in ``project``; returns node, element counts."""
    b = _Builder(project)
    if spec["kind"] in ("frame2d", "frame3d"):
        _frame(project, b, spec)
    elif spec["kind"] in ("truss2d", "truss3d"):
        _truss(project, b, spec)
    else:
        _bridge(project, b, spec)
    if "DL" in project.cases:
        project.self_weight.setdefault("DL", 1.0)
    return b.node_count, b.element_count
