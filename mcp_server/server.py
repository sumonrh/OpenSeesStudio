"""OpenSees Studio MCP server.

Exposes the model-generation and analysis capabilities of OpenSees Studio to
AI agents over the Model Context Protocol (stdio transport).

Run with:  python -m mcp_server
"""

from __future__ import annotations

import builtins
import functools
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Keep the JSON-RPC stream clean.  OpenSees prints banners from C code, which
# would corrupt stdio.  Redirect the C-level stdout to devnull, keep a private
# handle for the protocol, and send Python prints to stderr.
# --------------------------------------------------------------------------- #
def _protect_protocol_stream() -> None:
    try:
        real_fd = os.dup(1)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 1)
        os.close(devnull)
        sys.stdout = os.fdopen(real_fd, "w", buffering=1, encoding="utf-8",
                               errors="replace")
    except OSError:
        pass
    _print = builtins.print

    def _print_stderr(*args, **kwargs):
        kwargs.setdefault("file", sys.stderr)
        _print(*args, **kwargs)

    builtins.print = _print_stderr


_protect_protocol_stream()

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.mcpserver import Image, MCPServer  # noqa: E402

from app import opsgen  # noqa: E402
from app.model import (Element, ElementLoad, LoadCase, LoadCombination,  # noqa: E402
                       Material, NodalLoad, Node, Project, Section,
                       default_project)
from mcp_server.gui import GuiClient  # noqa: E402

# --------------------------------------------------------------------------- #
# state
# --------------------------------------------------------------------------- #
class State:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.project: Project = default_project()
        self.path: str = ""
        self.static: Optional[opsgen.StaticResults] = None
        self.modal: Optional[opsgen.ModalResults] = None
        self.gui = GuiClient()
        self.synced_nodes: int = 0


STATE = State()

SUPPORT_PRESETS = {
    "fixed": [True] * 6,
    "pinned": [True, True, True, False, False, False],
    "roller_z": [True, True, False, False, False, False],
    "roller_x": [False, True, True, False, False, False],
    "free": [False] * 6,
}

PLANES = {"YZ": 0, "XZ": 1, "XY": 2}


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with STATE.lock:
            return fn(*args, **kwargs)

    return wrapper


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _p() -> Project:
    return STATE.project


def _point(value, name: str) -> tuple:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must be [x, y, z].")
    return (float(value[0]), float(value[1]), float(value[2]))


def _delta(value) -> tuple:
    return _point(value, "delta")


def _require_nodes(tags: List[int]) -> None:
    missing = [t for t in tags if t not in _p().nodes]
    if missing:
        raise ValueError(f"Unknown node tag(s): {missing}")


def _require_elements(tags: List[int]) -> None:
    missing = [t for t in tags if t not in _p().elements]
    if missing:
        raise ValueError(f"Unknown element tag(s): {missing}")


def _require_case(name: str) -> None:
    if name not in _p().cases:
        raise ValueError(f"Unknown load case '{name}'. Cases: {list(_p().cases)}")


def _scene(name: str) -> str:
    if not name:
        name = _p().settings.get("last_case", "")
    if not name:
        names = _p().scenario_names()
        if not names:
            raise ValueError("The project has no load cases.")
        name = names[0]
    if name not in _p().cases and name not in _p().combos:
        raise ValueError(f"Unknown scenario '{name}'. Available: {_p().scenario_names()}")
    return name


def _node_json(n: Node) -> dict:
    return {"tag": n.tag, "x": n.x, "y": n.y, "z": n.z,
            "support": [1 if b else 0 for b in n.support]}


def _element_json(e: Element) -> dict:
    return {"tag": e.tag, "kind": e.kind, "nodes": list(e.nodes),
            "material": e.mat, "section": e.sec,
            "vecxz": list(e.vecxz) if e.vecxz else None,
            "thickness": e.thickness,
            "length": _p().element_length(e)}


def _summary() -> dict:
    p = _p()
    (x0, y0, z0), (x1, y1, z1) = p.bbox()
    return {
        "title": p.title,
        "path": STATE.path,
        "units": "kN, mm, tonne, s",
        "nodes": len(p.nodes),
        "elements": len(p.elements),
        "materials": len(p.materials),
        "sections": len(p.sections),
        "supports": sum(1 for n in p.nodes.values() if any(n.support)),
        "load_cases": list(p.cases),
        "combinations": list(p.combos),
        "nodal_loads": len(p.nodal_loads),
        "element_loads": len(p.elem_loads),
        "self_weight": dict(p.self_weight),
        "bbox": {"min": [x0, y0, z0], "max": [x1, y1, z1]},
        "has_static_results": STATE.static is not None,
        "has_modal_results": STATE.modal is not None,
        "gui_connected": STATE.gui.connected,
    }


def _sync_gui(fit: bool = False) -> None:
    if not STATE.gui.connected:
        return
    auto_fit = fit or STATE.synced_nodes == 0
    try:
        STATE.gui.call("load_project",
                       {"project": _p().to_dict(), "fit": auto_fit}, timeout=20.0)
        STATE.synced_nodes = len(_p().nodes)
    except Exception as exc:            # noqa: BLE001 - GUI may have closed
        STATE.gui.last_error = str(exc)
        STATE.gui.close()


def _changed(label: str, sync: bool = True) -> dict:
    STATE.static = None
    STATE.modal = None
    if sync:
        _sync_gui()
    return {"ok": True, "action": label}


def _static_payload(res: opsgen.StaticResults) -> dict:
    return {"scenario": res.scenario,
            "displacements": {str(k): list(v) for k, v in res.displacements.items()},
            "reactions": {str(k): list(v) for k, v in res.reactions.items()},
            "element_forces": {str(k): list(v) for k, v in res.element_forces.items()},
            "element_kind": {str(k): v for k, v in res.element_kind.items()},
            "max_disp": res.max_disp}


def _modal_payload(res: opsgen.ModalResults, mode: int = 1) -> dict:
    return {"mode": mode,
            "modes": [{"mode": m.mode, "eigenvalue": m.eigenvalue, "omega": m.omega,
                       "period": m.period, "frequency": m.frequency} for m in res.modes],
            "shapes": {str(k): {str(n): list(v) for n, v in shape.items()}
                       for k, shape in res.shapes.items()}}


# --------------------------------------------------------------------------- #
# MCP server
# --------------------------------------------------------------------------- #
server = MCPServer(
    name="opensees-studio",
    title="OpenSees Studio",
    version="1.0.0",
    instructions=(
        "OpenSees Studio is a graphical model generator for OpenSees. "
        "Use these tools to build structural models and analyse them.\n\n"
        "Units are always kN, mm, tonne, s. E is in kN/mm^2 (200 = 200 GPa), "
        "density in t/mm^3 (steel 7.85e-9), distributed loads in kN/mm "
        "(10 kN/m = 0.01).\n\n"
        "Typical workflow: project_new -> add_nodes -> add_elements -> "
        "assign_supports -> add_load_case -> add_nodal_loads / add_element_loads / "
        "set_self_weight -> add_load_combination -> check_model -> run_static -> "
        "get_static_results. Use run_modal for periods and mode shapes.\n\n"
        "A running GUI can be attached with gui_connect (the app must be started "
        "with the --bridge flag); the model is then mirrored live and "
        "gui_screenshot returns the viewport image.\n\n"
        "Node/element tags are assigned automatically and returned by the tools."
    ),
)


# --------------------------------------------------------------------------- #
# project
# --------------------------------------------------------------------------- #
@server.tool()
@_locked
def project_new(title: str = "Untitled") -> dict:
    """Start a new empty project (default materials, sections and load cases DL/LL)."""
    STATE.project = default_project()
    STATE.project.title = title
    STATE.path = ""
    STATE.static = None
    STATE.modal = None
    STATE.synced_nodes = 0
    _sync_gui(fit=True)
    return _summary()


@server.tool()
@_locked
def project_open(path: str) -> dict:
    """Open an OpenSees Studio project (.ospj JSON file) from disk."""
    p = Path(path)
    if not p.exists():
        raise ValueError(f"File not found: {path}")
    STATE.project = Project.load(str(p))
    STATE.project.title = STATE.project.title or p.stem
    STATE.path = str(p)
    STATE.static = None
    STATE.modal = None
    STATE.synced_nodes = 0
    _sync_gui(fit=True)
    return _summary()


@server.tool()
@_locked
def project_save(path: str = "") -> dict:
    """Save the project. Uses the current path when path is empty."""
    target = path or STATE.path or "model.ospj"
    if not target.lower().endswith((".ospj", ".json")):
        target += ".ospj"
    STATE.project.save(target)
    STATE.path = target
    return {"ok": True, "path": target, "title": STATE.project.title}


@server.tool()
@_locked
def project_summary() -> dict:
    """Return counts, bounding box, load cases, combinations and result status."""
    return _summary()


# --------------------------------------------------------------------------- #
# geometry: nodes
# --------------------------------------------------------------------------- #
def _add_points(points) -> List[int]:
    created = []
    for i, raw in enumerate(points):
        x, y, z = _point(raw, f"points[{i}]")
        tag = _p().next_node()
        _p().nodes[tag] = Node(tag, x, y, z)
        created.append(tag)
    return created


@server.tool()
@_locked
def add_nodes(points: List[List[float]]) -> dict:
    """Create nodes at [x, y, z] coordinates (mm) and return their tags.

    Example: add_nodes([[0,0,0],[6000,0,0],[6000,0,3500]])
    """
    if not points:
        raise ValueError("points is empty.")
    created = _add_points(points)
    _changed(f"add {len(created)} node(s)")
    return {"ok": True, "nodes": created}


@server.tool()
@_locked
def add_node_line(start: List[float], delta: List[float], count: int) -> dict:
    """Create `count` equally spaced nodes starting at `start` with step `delta` (mm)."""
    if count < 1:
        raise ValueError("count must be >= 1.")
    sx, sy, sz = _point(start, "start")
    dx, dy, dz = _delta(delta)
    points = [[sx + i * dx, sy + i * dy, sz + i * dz] for i in range(count)]
    created = _add_points(points)
    _changed(f"add {len(created)} node(s) in a line")
    return {"ok": True, "nodes": created}


@server.tool()
@_locked
def list_nodes() -> List[dict]:
    """List all nodes with coordinates and support flags."""
    return [_node_json(n) for n in _p().nodes.values()]


@server.tool()
@_locked
def get_node(tag: int) -> dict:
    """Get one node by tag."""
    node = _p().nodes.get(tag)
    if node is None:
        raise ValueError(f"Unknown node {tag}.")
    return _node_json(node)


@server.tool()
@_locked
def move_nodes(tags: List[int], delta: List[float]) -> dict:
    """Translate nodes by delta = [dx, dy, dz] (mm). Connected elements follow."""
    _require_nodes(tags)
    dx, dy, dz = _delta(delta)
    for t in tags:
        n = _p().nodes[t]
        n.x += dx
        n.y += dy
        n.z += dz
    _changed(f"move {len(tags)} node(s)")
    return {"ok": True, "moved": list(tags), "delta": [dx, dy, dz]}


@server.tool()
@_locked
def copy_nodes(tags: List[int], delta: List[float], count: int = 1,
               include_attached_elements: bool = True) -> dict:
    """Copy nodes `count` times at 1x, 2x ... delta. Attached elements are copied."""
    _require_nodes(tags)
    if count < 1:
        raise ValueError("count must be >= 1.")
    dx, dy, dz = _delta(delta)
    node_set = set(tags)
    elem_set = {t for t, e in _p().elements.items() if all(n in node_set for n in e.nodes)} \
        if include_attached_elements else set()

    new_nodes: List[int] = []
    new_elems: List[int] = []
    for k in range(1, count + 1):
        mapping: Dict[int, int] = {}
        for t in tags:
            n = _p().nodes[t]
            new_tag = _p().next_node()
            _p().nodes[new_tag] = Node(new_tag, n.x + k * dx, n.y + k * dy, n.z + k * dz)
            mapping[t] = new_tag
            new_nodes.append(new_tag)
        for t in sorted(elem_set):
            e = _p().elements[t]
            if any(n not in mapping for n in e.nodes):
                continue
            new_tag = _p().next_element()
            _p().elements[new_tag] = Element(
                new_tag, e.kind, [mapping[n] for n in e.nodes], e.mat, e.sec,
                list(e.vecxz) if e.vecxz else None, e.thickness, e.group)
            new_elems.append(new_tag)
    _changed(f"copy {len(tags)} node(s) x{count}")
    return {"ok": True, "nodes": new_nodes, "elements": new_elems}


@server.tool()
@_locked
def mirror_nodes(tags: List[int], plane: str = "YZ", copy: bool = True,
                 include_attached_elements: bool = True) -> dict:
    """Mirror nodes about a global plane: 'YZ' (flips X), 'XZ' (flips Y), 'XY' (flips Z)."""
    _require_nodes(tags)
    key = plane.upper().replace(" ", "")
    if key not in PLANES:
        raise ValueError("plane must be one of YZ, XZ, XY.")
    axis = PLANES[key]
    node_set = set(tags)
    elem_set = {t for t, e in _p().elements.items() if all(n in node_set for n in e.nodes)} \
        if include_attached_elements else set()

    def flip(n):
        c = [n.x, n.y, n.z]
        c[axis] = -c[axis]
        return c

    if not copy:
        for t in tags:
            n = _p().nodes[t]
            n.x, n.y, n.z = flip(n)
        for t in elem_set:
            e = _p().elements[t]
            if e.kind == "shell":
                e.nodes = list(reversed(e.nodes))
        _changed(f"mirror {len(tags)} node(s) in place")
        return {"ok": True, "nodes": list(tags), "elements": sorted(elem_set)}

    mapping: Dict[int, int] = {}
    new_nodes: List[int] = []
    for t in tags:
        n = _p().nodes[t]
        new_tag = _p().next_node()
        x, y, z = flip(n)
        _p().nodes[new_tag] = Node(new_tag, x, y, z)
        mapping[t] = new_tag
        new_nodes.append(new_tag)
    new_elems: List[int] = []
    for t in sorted(elem_set):
        e = _p().elements[t]
        if any(n not in mapping for n in e.nodes):
            continue
        nodes = [mapping[n] for n in e.nodes]
        if e.kind == "shell":
            nodes = list(reversed(nodes))
        new_tag = _p().next_element()
        _p().elements[new_tag] = Element(
            new_tag, e.kind, nodes, e.mat, e.sec,
            list(e.vecxz) if e.vecxz else None, e.thickness, e.group)
        new_elems.append(new_tag)
    _changed(f"mirror {len(tags)} node(s)")
    return {"ok": True, "nodes": new_nodes, "elements": new_elems}


@server.tool()
@_locked
def delete_nodes(tags: List[int]) -> dict:
    """Delete nodes and every element attached to them."""
    _require_nodes(tags)
    node_set = set(tags)
    removed_el = [t for t, e in _p().elements.items() if any(n in node_set for n in e.nodes)]
    for t in removed_el:
        _p().elements.pop(t, None)
    for t in tags:
        _p().nodes.pop(t, None)
    _p().nodal_loads = [l for l in _p().nodal_loads if l.node in _p().nodes]
    _p().elem_loads = [l for l in _p().elem_loads if l.elem in _p().elements]
    _changed(f"delete {len(tags)} node(s)")
    return {"ok": True, "deleted_nodes": list(tags), "deleted_elements": removed_el}


# --------------------------------------------------------------------------- #
# geometry: elements
# --------------------------------------------------------------------------- #
@server.tool()
@_locked
def add_elements(kind: str, node_tags: List[int], material: int = 1,
                 section: int = 1, vecxz: Optional[List[float]] = None,
                 thickness: float = 100.0) -> dict:
    """Create elements. kind = beam | truss | shell.

    For beam/truss, 3+ node tags create a chain between consecutive nodes.
    For shell, tags are taken in groups of four (i, j, k, l).
    vecxz is the beam local z axis; omit for automatic (global Z, or global X
    for vertical members).
    """
    kind = kind.lower()
    if kind not in ("beam", "truss", "shell"):
        raise ValueError("kind must be beam, truss or shell.")
    _require_nodes(node_tags)
    if material not in _p().materials:
        raise ValueError(f"Unknown material {material}. Available: {list(_p().materials)}")
    if section not in _p().sections:
        raise ValueError(f"Unknown section {section}. Available: {list(_p().sections)}")
    vx = None
    if vecxz is not None:
        vx = [float(v) for v in vecxz]
        if len(vx) != 3:
            raise ValueError("vecxz must be [x, y, z].")

    if kind == "shell":
        if not node_tags or len(node_tags) % 4 != 0:
            raise ValueError("Shell elements need node tags in groups of four.")
        groups = [node_tags[i:i + 4] for i in range(0, len(node_tags), 4)]
    else:
        if len(node_tags) < 2:
            raise ValueError("A beam or truss needs at least two nodes.")
        groups = [[node_tags[i], node_tags[i + 1]] for i in range(len(node_tags) - 1)]

    created = []
    for group in groups:
        if len(set(group)) != len(group):
            raise ValueError("An element cannot reference the same node twice.")
        tag = _p().next_element()
        _p().elements[tag] = Element(tag, kind, group, material, section, vx, thickness)
        created.append(tag)
    _changed(f"add {len(created)} element(s)")
    return {"ok": True, "elements": created, "kind": kind}


@server.tool()
@_locked
def list_elements() -> List[dict]:
    """List all elements with type, nodes, material, section and length."""
    return [_element_json(e) for e in _p().elements.values()]


@server.tool()
@_locked
def update_element(tag: int, material: Optional[int] = None,
                   section: Optional[int] = None,
                   vecxz: Optional[List[float]] = None) -> dict:
    """Change an element's material, section or local-z axis."""
    e = _p().elements.get(tag)
    if e is None:
        raise ValueError(f"Unknown element {tag}.")
    if material is not None:
        if material not in _p().materials:
            raise ValueError(f"Unknown material {material}.")
        e.mat = material
    if section is not None:
        if section not in _p().sections:
            raise ValueError(f"Unknown section {section}.")
        e.sec = section
    if vecxz is not None:
        e.vecxz = [float(v) for v in vecxz]
    _changed(f"update element {tag}")
    return _element_json(e)


@server.tool()
@_locked
def delete_elements(tags: List[int]) -> dict:
    """Delete elements by tag (nodes are kept)."""
    _require_elements(tags)
    for t in tags:
        _p().elements.pop(t, None)
    _p().elem_loads = [l for l in _p().elem_loads if l.elem in _p().elements]
    _changed(f"delete {len(tags)} element(s)")
    return {"ok": True, "deleted": list(tags)}


# --------------------------------------------------------------------------- #
# properties
# --------------------------------------------------------------------------- #
@server.tool()
@_locked
def list_materials() -> List[dict]:
    """List the material library."""
    return [dict(m.__dict__) for m in _p().materials.values()]


@server.tool()
@_locked
def add_material(name: str, kind: str = "Elastic", E: float = 200.0,
                 nu: float = 0.3, rho: float = 7.85e-9, fy: float = 0.235,
                 b: float = 0.01, fc: float = 0.030) -> dict:
    """Add a material (Elastic, ElasticPP, Steel02 or Concrete02). E in kN/mm^2."""
    tag = _p().next_material()
    _p().materials[tag] = Material(tag, name, kind, E, nu, rho, fy, b, fc)
    _changed(f"add material {tag}")
    return {"ok": True, "tag": tag}


@server.tool()
@_locked
def list_sections() -> List[dict]:
    """List frame sections with computed A, Iy, Iz and J."""
    return [dict(s.__dict__) for s in _p().sections.values()]


@server.tool()
@_locked
def add_section(name: str, shape: str = "Rectangle", b: float = 300.0,
                h: float = 600.0, d: float = 400.0, t: float = 12.0,
                tw: float = 10.0, tf: float = 15.0,
                A: float = 0.0, Iy: float = 0.0, Iz: float = 0.0,
                J: float = 0.0) -> dict:
    """Add a section. shape = Rectangle | Circle | Pipe | Box | I-Shape | User.

    For User, A/Iy/Iz/J are used as given; other shapes compute them from
    dimensions (mm, mm^4).
    """
    if shape not in ("Rectangle", "Circle", "Pipe", "Box", "I-Shape", "User"):
        raise ValueError("Unsupported section shape.")
    tag = _p().next_section()
    s = Section(tag, name, shape, b, h, d, t, tw, tf, A, Iy, Iz, J)
    if shape != "User":
        s.compute()
    _p().sections[tag] = s
    _changed(f"add section {tag}")
    return {"ok": True, "tag": tag, "A": s.A, "Iy": s.Iy, "Iz": s.Iz, "J": s.J}


# --------------------------------------------------------------------------- #
# supports
# --------------------------------------------------------------------------- #
@server.tool()
@_locked
def assign_supports(tags: List[int],
                    dof: Any = "fixed") -> dict:
    """Assign supports. dof is a preset ('fixed', 'pinned', 'roller_z',
    'roller_x', 'free') or six booleans [DX, DY, DZ, RX, RY, RZ].
    """
    _require_nodes(tags)
    if isinstance(dof, str):
        key = dof.lower()
        if key not in SUPPORT_PRESETS:
            raise ValueError(f"Unknown support preset '{dof}'. "
                             f"Use one of {list(SUPPORT_PRESETS)} or 6 booleans.")
        flags = list(SUPPORT_PRESETS[key])
    else:
        if len(dof) != 6:
            raise ValueError("dof must contain six booleans.")
        flags = [bool(v) for v in dof]
    for t in tags:
        _p().nodes[t].support = list(flags)
    _changed(f"supports on {len(tags)} node(s)")
    return {"ok": True, "nodes": list(tags), "dof": [1 if b else 0 for b in flags]}


# --------------------------------------------------------------------------- #
# loads
# --------------------------------------------------------------------------- #
@server.tool()
@_locked
def add_load_case(name: str, kind: str = "Dead") -> dict:
    """Create a load case (Dead, Live, Wind, Seismic, Snow, Temperature, Other)."""
    if name in _p().cases:
        raise ValueError(f"Load case '{name}' already exists.")
    _p().cases[name] = LoadCase(name, kind)
    _changed(f"add load case {name}")
    return {"ok": True, "cases": list(_p().cases)}


@server.tool()
@_locked
def list_load_cases() -> List[dict]:
    """List load cases."""
    return [dict(c.__dict__) for c in _p().cases.values()]


@server.tool()
@_locked
def add_nodal_loads(node_tags: List[int], case: str, values: List[float],
                    replace: bool = True) -> dict:
    """Apply a nodal load [FX, FY, FZ, MX, MY, MZ] (kN, kN.mm) to nodes.

    With replace=True existing nodal loads of that case on those nodes are
    replaced.
    """
    _require_nodes(node_tags)
    _require_case(case)
    if len(values) != 6:
        raise ValueError("values must be [FX, FY, FZ, MX, MY, MZ].")
    vals = [float(v) for v in values]
    if replace:
        _p().nodal_loads = [l for l in _p().nodal_loads
                            if not (l.node in node_tags and l.case == case)]
    for t in node_tags:
        _p().nodal_loads.append(NodalLoad(_p().next_load(), t, case, list(vals)))
    _changed(f"nodal load on {len(node_tags)} node(s)")
    return {"ok": True, "nodes": list(node_tags), "case": case, "values": vals}


@server.tool()
@_locked
def add_element_loads(element_tags: List[int], case: str, value: float,
                      direction: str = "Global Z", kind: str = "uniform",
                      value2: float = 0.0, trapezoid: bool = False,
                      position: float = 0.5, replace: bool = False) -> dict:
    """Apply a distributed or point load to elements.

    direction: local-y | local-z | Global X | Global Y | Global Z.
    kind: uniform | point.  value is kN/mm for uniform, kN for point.
    trapezoid=True with value2 gives a linearly varying load (approximated).
    position is x/L for point loads.
    """
    _require_elements(element_tags)
    _require_case(case)
    kind = kind.lower()
    if kind not in ("uniform", "point"):
        raise ValueError("kind must be uniform or point.")
    if replace:
        _p().elem_loads = [l for l in _p().elem_loads
                           if not (l.elem in element_tags and l.case == case)]
    for t in element_tags:
        _p().elem_loads.append(ElementLoad(
            _p().next_load(), t, case, kind, direction, float(value),
            float(value2), float(position), bool(trapezoid)))
    _changed(f"element load on {len(element_tags)} element(s)")
    return {"ok": True, "elements": list(element_tags), "case": case,
            "direction": direction, "value": float(value)}


@server.tool()
@_locked
def set_self_weight(case: str, factor: float = 1.0) -> dict:
    """Apply self weight (rho*A*g) to all elements in a load case; factor 0 removes it."""
    _require_case(case)
    if abs(factor) < 1e-12:
        _p().self_weight.pop(case, None)
    else:
        _p().self_weight[case] = float(factor)
    _changed(f"self weight {case} = {factor}")
    return {"ok": True, "self_weight": dict(_p().self_weight)}


@server.tool()
@_locked
def add_load_combination(name: str, factors: Dict[str, float]) -> dict:
    """Create a load combination, e.g. {"DL": 1.4, "LL": 1.6}."""
    if not factors:
        raise ValueError("factors is empty.")
    for case in factors:
        _require_case(case)
    _p().combos[name] = LoadCombination(name, [(c, float(f)) for c, f in factors.items()])
    _changed(f"add combination {name}")
    return {"ok": True, "combinations": {n: dict(c.factors) for n, c in _p().combos.items()}}


@server.tool()
@_locked
def list_combinations() -> List[dict]:
    """List load combinations and their factors."""
    return [{"name": c.name, "kind": c.kind, "factors": dict(c.factors)}
            for c in _p().combos.values()]


# --------------------------------------------------------------------------- #
# validation and analysis
# --------------------------------------------------------------------------- #
@server.tool()
@_locked
def check_model() -> dict:
    """Validate the model (missing references, unconnected nodes, supports, loads)."""
    errors, warnings = opsgen.check_model(_p())
    return {"ok": not errors, "errors": errors, "warnings": warnings}


@server.tool()
@_locked
def run_static(scenario: str = "") -> dict:
    """Run a static analysis for a load case or combination and return a summary."""
    name = _scene(scenario)
    res = opsgen.run_static(_p(), name)
    STATE.static = res
    STATE.modal = None
    STATE.project.settings["last_case"] = name
    if STATE.gui.connected:
        try:
            STATE.gui.call("show_static", _static_payload(res), timeout=20.0)
        except Exception:               # noqa: BLE001
            STATE.gui.close()
    peak = max(res.displacements, key=lambda t: max(abs(v) for v in res.displacements[t]),
               default=0)
    return {"ok": True, "scenario": name, "max_disp_mm": res.max_disp,
            "max_disp_node": peak,
            "displacements": len(res.displacements),
            "element_forces": len(res.element_forces)}


@server.tool()
@_locked
def get_static_results(node_tags: Optional[List[int]] = None,
                       element_tags: Optional[List[int]] = None,
                       include_reactions: bool = True,
                       include_forces: bool = False) -> dict:
    """Return static results. Filter with node_tags / element_tags.

    Displacements are always returned; reactions and element forces are optional.
    """
    if STATE.static is None:
        raise ValueError("No static results. Call run_static first.")
    res = STATE.static
    nodes = node_tags if node_tags is not None else list(res.displacements)
    elems = element_tags if element_tags is not None else list(res.element_forces)
    out: Dict[str, Any] = {
        "scenario": res.scenario,
        "max_disp": res.max_disp,
        "displacements": {str(t): res.displacements[t] for t in nodes if t in res.displacements},
    }
    if include_reactions:
        out["reactions"] = {str(t): res.reactions[t] for t in nodes if t in res.reactions}
    if include_forces:
        out["element_forces"] = {str(t): res.element_forces.get(t, []) for t in elems}
        out["element_kind"] = {str(t): res.element_kind.get(t, "") for t in elems}
    return out


@server.tool()
@_locked
def run_modal(n_modes: int = 6) -> dict:
    """Run an eigenvalue analysis and return periods and frequencies."""
    res = opsgen.run_modal(_p(), int(n_modes))
    STATE.modal = res
    STATE.static = None
    if STATE.gui.connected:
        try:
            STATE.gui.call("show_mode", _modal_payload(res, 1), timeout=20.0)
        except Exception:               # noqa: BLE001
            STATE.gui.close()
    return {"ok": True, "modes": [{"mode": m.mode, "period": m.period,
                                   "frequency": m.frequency,
                                   "eigenvalue": m.eigenvalue}
                                  for m in res.modes]}


@server.tool()
@_locked
def get_modes() -> List[dict]:
    """Return the modal results table (mode, eigenvalue, period, frequency)."""
    if STATE.modal is None:
        raise ValueError("No modal results. Call run_modal first.")
    return [{"mode": m.mode, "eigenvalue": m.eigenvalue, "omega": m.omega,
             "period": m.period, "frequency": m.frequency} for m in STATE.modal.modes]


@server.tool()
@_locked
def get_mode_shape(mode: int = 1) -> dict:
    """Return the normalised mode shape: node -> [ux, uy, uz, rx, ry, rz]."""
    if STATE.modal is None:
        raise ValueError("No modal results. Call run_modal first.")
    shape = STATE.modal.shapes.get(int(mode))
    if shape is None:
        raise ValueError(f"Mode {mode} not available.")
    return {str(t): v for t, v in shape.items()}


@server.tool()
@_locked
def export_tcl(path: str) -> dict:
    """Write an OpenSees Tcl input file for the current model."""
    target = Path(path)
    if target.suffix.lower() != ".tcl":
        target = target.with_suffix(".tcl")
    text = opsgen.export_tcl(_p())
    target.write_text(text, encoding="utf-8")
    return {"ok": True, "path": str(target), "lines": len(text.splitlines())}


# --------------------------------------------------------------------------- #
# GUI bridge
# --------------------------------------------------------------------------- #
def _find_app_exe() -> Optional[str]:
    env = os.environ.get("OPENSEES_STUDIO_EXE", "")
    if env and Path(env).exists():
        return env
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).resolve().parent.parent / "OpenSeesStudio.exe"
        if candidate.exists():
            return str(candidate)
    root = Path(__file__).resolve().parent.parent
    for candidate in (root / "dist" / "OpenSeesStudio" / "OpenSeesStudio.exe",
                      Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" /
                      "OpenSees Studio" / "OpenSeesStudio.exe"):
        if candidate.exists():
            return str(candidate)
    return None


@server.tool()
@_locked
def gui_launch(port: int = 8765, timeout: float = 30.0) -> dict:
    """Start OpenSees Studio (with the bridge) and connect to it.

    Set OPENSEES_STUDIO_EXE to override the executable location.
    """
    if STATE.gui.connected:
        return {"ok": True, "already_running": True,
                "gui": STATE.gui.call("ping", timeout=3.0)}
    exe = _find_app_exe()
    if not exe:
        raise ValueError("Could not locate OpenSeesStudio.exe. "
                         "Set the OPENSEES_STUDIO_EXE environment variable.")
    import subprocess
    import time

    subprocess.Popen([exe, "--bridge", str(int(port))], close_fds=True)
    last_error = ""
    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        try:
            info = STATE.gui.connect("127.0.0.1", int(port), timeout=2.0)
            _sync_gui(fit=True)
            return {"ok": True, "exe": exe, "gui": info}
        except Exception as exc:        # noqa: BLE001 - retry until timeout
            last_error = str(exc)
            time.sleep(0.5)
    raise ValueError(f"The GUI did not become ready: {last_error}")


@server.tool()
@_locked
def gui_connect(host: str = "127.0.0.1", port: int = 8765) -> dict:
    """Connect to a running OpenSees Studio GUI (started with --bridge).

    Once connected, model changes are mirrored to the GUI automatically.
    """
    info = STATE.gui.connect(host, int(port))
    _sync_gui(fit=True)
    return {"ok": True, "gui": info, "host": host, "port": int(port)}


@server.tool()
@_locked
def gui_disconnect() -> dict:
    """Disconnect from the GUI (the MCP server keeps working headless)."""
    STATE.gui.close()
    return {"ok": True, "connected": False}


@server.tool()
@_locked
def gui_status() -> dict:
    """Report whether a GUI is attached and what it is showing."""
    if not STATE.gui.connected:
        return {"connected": False, "hint": "Start OpenSees Studio with --bridge."}
    try:
        info = STATE.gui.call("ping", timeout=3.0)
        return {"connected": True, "gui": info}
    except Exception as exc:            # noqa: BLE001
        STATE.gui.close()
        return {"connected": False, "error": str(exc)}


@server.tool()
@_locked
def gui_sync(fit: bool = True) -> dict:
    """Push the current model to the attached GUI and refresh the view."""
    if not STATE.gui.connected:
        raise ValueError("No GUI attached. Call gui_connect first.")
    _sync_gui(fit=fit)
    if not STATE.gui.connected:
        raise ValueError(f"GUI sync failed: {STATE.gui.last_error}")
    return {"ok": True}


@server.tool()
@_locked
def gui_deformed_scale(scale: float = 0) -> dict:
    """Exaggerate the deformed shape in the attached GUI (0 = automatic)."""
    if not STATE.gui.connected:
        raise ValueError("No GUI attached. Call gui_connect first.")
    result = STATE.gui.call("set_deformed_scale", {"scale": float(scale)})
    return {"ok": True, **result}


@server.tool()
@_locked
def gui_screenshot(viewport_only: bool = True) -> Any:
    """Capture the GUI and return the image (requires gui_connect)."""
    if not STATE.gui.connected:
        raise ValueError("No GUI attached. Call gui_connect first.")
    import base64

    data = STATE.gui.call("screenshot", {"viewport_only": viewport_only}, timeout=30.0)
    raw = base64.b64decode(data["png_base64"])
    return Image(data=raw, format="png")


@server.tool()
@_locked
def gui_show_results() -> dict:
    """Show the latest static or modal results in the attached GUI."""
    if not STATE.gui.connected:
        raise ValueError("No GUI attached. Call gui_connect first.")
    if STATE.static is not None:
        STATE.gui.call("show_static", _static_payload(STATE.static))
        return {"ok": True, "showing": "static", "scenario": STATE.static.scenario}
    if STATE.modal is not None:
        STATE.gui.call("show_mode", _modal_payload(STATE.modal, 1))
        return {"ok": True, "showing": "modal", "mode": 1}
    raise ValueError("No results yet. Run an analysis first.")


# --------------------------------------------------------------------------- #
# resources
# --------------------------------------------------------------------------- #
@server.resource("opensees://project", name="OpenSees Studio project",
                 description="Current model as OpenSees Studio JSON",
                 mime_type="application/json")
def project_resource() -> str:
    return json.dumps(_p().to_dict(), indent=2)


@server.resource("opensees://results/static", name="Static results",
                 description="Latest static results as JSON",
                 mime_type="application/json")
def static_resource() -> str:
    if STATE.static is None:
        return json.dumps({"error": "no static results"})
    return json.dumps(_static_payload(STATE.static))


@server.resource("opensees://results/modal", name="Modal results",
                 description="Latest modal results as JSON",
                 mime_type="application/json")
def modal_resource() -> str:
    if STATE.modal is None:
        return json.dumps({"error": "no modal results"})
    return json.dumps(_modal_payload(STATE.modal))


# --------------------------------------------------------------------------- #
def main() -> None:
    transport = os.environ.get("OPENSEES_MCP_TRANSPORT", "stdio")
    server.run(transport=transport)


if __name__ == "__main__":
    main()
