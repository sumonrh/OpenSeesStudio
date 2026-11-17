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

from app import (groundmotion, hinge_catalog, live_load as live_load_engine,
                 moment_curvature as moment_curvature_engine, opsgen, tcl,
                 wizards)
from app import section_property
from app.model import (BoundaryConstraint, Element, ElementLoad,  # noqa: E402
                       GroundMotionRecord, HingeDefinition, Lane, LoadCase,
                       LoadCombination, Material, NodalLoad, Node, Project,
                       ResponseSpectrumCase, Section, SpringSupport,
                       TimeHistoryCase, default_project)
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
        self.pushover: Optional[opsgen.PushoverResults] = None
        self.time_history: Optional[opsgen.TimeHistoryResults] = None
        self.spectrum: Optional[opsgen.ResponseSpectrumResults] = None
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


def _curve_points(value) -> List[List[float]]:
    if value is None:
        return []
    points: List[List[float]] = []
    for pair in value:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("curve points must be [deformation, force] pairs.")
        points.append([float(pair[0]), float(pair[1])])
    return points


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
        "springs": len(p.springs),
        "constraints": len(p.constraints),
        "lanes": len(p.lanes),
        "vehicles": len(p.vehicles),
        "live_load_cases": list(p.live_load_cases),
        "load_cases": list(p.cases),
        "combinations": list(p.combos),
        "nodal_loads": len(p.nodal_loads),
        "element_loads": len(p.elem_loads),
        "self_weight": dict(p.self_weight),
        "bbox": {"min": [x0, y0, z0], "max": [x1, y1, z1]},
        "has_static_results": STATE.static is not None,
        "has_modal_results": STATE.modal is not None,
        "has_pushover_results": STATE.pushover is not None,
        "has_time_history_results": STATE.time_history is not None,
        "has_response_spectrum_results": STATE.spectrum is not None,
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
    STATE.pushover = None
    STATE.time_history = None
    STATE.spectrum = None
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
    version="1.0.19",
    instructions=(
        "OpenSees Studio is a graphical model generator and analysis GUI for "
        "OpenSees. Use these tools to build structural models and analyse them.\n\n"
        "Units are always kN, mm, tonne, s. E is in kN/mm^2 (200 = 200 GPa), "
        "density in t/mm^3 (steel 7.85e-9), distributed loads in kN/mm "
        "(10 kN/m = 0.01).\n\n"
        "Typical workflow: project_new -> add_nodes -> add_elements -> "
        "assign_supports -> add_load_case -> add_nodal_loads / add_element_loads / "
        "set_self_weight -> add_load_combination -> check_model -> run_static -> "
        "get_static_results. Use run_modal for periods and mode shapes.\n\n"
        "add_elements supports beam, truss (behavior '', tension or compression), "
        "cable (tension-only corotTruss), shell, force_beam and disp_beam "
        "(fibre section plus Lobatto/Legendre/NewtonCotes/Radau integration). "
        "Point springs use add_point_spring; node constraints use add_constraint.\n\n"
        "For nonlinear work call list_hinge_materials, add_hinge_definition and "
        "assign_hinges, then run_pushover (requires a lateral case and hinges). "
        "MomentBackbone hinge definitions carry a stored moment-rotation curve "
        "and build beam-end spring hinges for pushover and nonlinear time "
        "history. Use section_properties for Section Property Pro values, "
        "moment_curvature for a reinforced-concrete backbone, and live_load for "
        "bridge moving-truck/lane envelopes and influence lines. "
        "Point springs use add_point_spring (Elastic, MultiLinear or PySimple1 p-y); "
        "node constraints use add_constraint (rigid_beam, rigid_bar, equal_dof, "
        "rigid_diaphragm). Dynamic work uses add_ground_motion, "
        "configure_time_history, run_time_history, configure_response_spectrum and "
        "run_response_spectrum. generate_frame_2d/3d, generate_truss_2d/3d and "
        "generate_bridge create complete models from parameters. "
        "import_tcl/export_tcl exchange models; run_python and run_tcl execute "
        "scripts in the shared OpenSees domain.\n\n"
        "A running GUI can be attached with gui_connect (the app must be started "
        "with the --bridge flag); the model is then mirrored live. "
        "gui_set_visibility and gui_set_labels control the view, and "
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
                list(e.vecxz) if e.vecxz else None, e.thickness, e.group,
                e.behavior, dict(e.device), e.integration,
                e.integration_points)
            new_elems.append(new_tag)
    _changed(f"copy {len(tags)} node(s) x{count}")
    return {"ok": True, "nodes": new_nodes, "elements": new_elems}


@server.tool()
@_locked
def mirror_nodes(tags: List[int], plane: str = "YZ", copy: bool = True,
                 include_attached_elements: bool = True,
                 coordinate: float = 0.0) -> dict:
    """Mirror nodes about a global plane: 'YZ' (flips X), 'XZ' (flips Y), 'XY' (flips Z).

    coordinate is the plane position along its normal, in mm (0 = through the origin).
    """
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
        c[axis] = 2.0 * float(coordinate) - c[axis]
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
            list(e.vecxz) if e.vecxz else None, e.thickness, e.group,
            e.behavior, dict(e.device), e.integration,
            e.integration_points)
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
                 thickness: float = 100.0, behavior: str = "",
                 integration: str = "Lobatto",
                 integration_points: int = 5) -> dict:
    """Create elements. kind = beam | truss | cable | shell | force_beam | disp_beam.

    For beam/truss/cable/force_beam/disp_beam, 3+ node tags create a chain
    between consecutive nodes. For shell, tags are taken in groups of four
    (i, j, k, l). vecxz is the beam local z axis; omit for automatic (global Z,
    or global X for vertical members). behavior is '', tension or compression
    for truss elements; cable elements are always tension-only corotTruss
    elements. Nonlinear frame members use a fibre section and the selected
    beam integration (Lobatto, Legendre, NewtonCotes or Radau).
    """
    kind = kind.lower()
    if kind not in ("beam", "truss", "cable", "shell",
                    "force_beam", "disp_beam"):
        raise ValueError("kind must be beam, truss, cable, shell, force_beam "
                         "or disp_beam.")
    if behavior not in ("", "tension", "compression"):
        raise ValueError("behavior must be '', tension or compression.")
    if behavior and kind != "truss":
        raise ValueError("behavior applies to truss elements only.")
    if integration not in ("Lobatto", "Legendre", "NewtonCotes", "Radau"):
        raise ValueError("integration must be Lobatto, Legendre, NewtonCotes "
                         "or Radau.")
    if not 2 <= int(integration_points) <= 40:
        raise ValueError("integration_points must be between 2 and 40.")
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
        _p().elements[tag] = Element(tag, kind, group, material, section, vx,
                                     thickness, behavior=behavior,
                                     integration=integration,
                                     integration_points=int(integration_points))
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
# structure wizards
# --------------------------------------------------------------------------- #
def _replace_geometry() -> Project:
    p = _p()
    p.nodes.clear()
    p.elements.clear()
    p.nodal_loads.clear()
    p.elem_loads.clear()
    p.hinge_assignments.clear()
    p.springs.clear()
    p.constraints.clear()
    return p


def _wizard_result(kind: str, spec: dict, replace: bool) -> dict:
    p = _p()
    if spec.get("mat") not in p.materials:
        raise ValueError(f"Unknown material {spec.get('mat')}.")
    for key in ("col_sec", "beam_sec", "sec", "girder_sec", "cross_sec"):
        if key in spec and spec[key] not in p.sections:
            raise ValueError(f"Unknown section {spec[key]}.")
    if replace:
        _replace_geometry()
    nodes, elements = wizards.generate(p, spec)
    if p.title in ("", "Untitled"):
        p.title = wizards.WIZARDS[kind][0]
    _changed(f"generate {wizards.WIZARDS[kind][0]}")
    return {"ok": True, "wizard": kind, "nodes": nodes, "elements": elements,
            "replaced": bool(replace)}


@server.tool()
@_locked
def generate_frame_2d(bays_x: int = 3, bay_width: float = 6000.0,
                      storeys: int = 3, storey_height: float = 3500.0,
                      material: int = 1, column_section: int = 1,
                      beam_section: int = 2, replace: bool = True) -> dict:
    """Generate a 2D moment frame in the X-Z plane (mm units)."""
    return _wizard_result("frame2d", {
        "kind": "frame2d", "mat": material, "bays_x": int(bays_x),
        "bays_y": 0, "bay_width": float(bay_width), "bay_depth": 0.0,
        "storeys": int(storeys), "storey_height": float(storey_height),
        "col_sec": column_section, "beam_sec": beam_section}, replace)


@server.tool()
@_locked
def generate_frame_3d(bays_x: int = 3, bays_y: int = 2,
                      bay_width: float = 6000.0, bay_depth: float = 5000.0,
                      storeys: int = 3, storey_height: float = 3500.0,
                      material: int = 1, column_section: int = 1,
                      beam_section: int = 2, replace: bool = True) -> dict:
    """Generate a 3D moment frame with bays in X and Y (mm units)."""
    return _wizard_result("frame3d", {
        "kind": "frame3d", "mat": material, "bays_x": int(bays_x),
        "bays_y": int(bays_y), "bay_width": float(bay_width),
        "bay_depth": float(bay_depth), "storeys": int(storeys),
        "storey_height": float(storey_height), "col_sec": column_section,
        "beam_sec": beam_section}, replace)


@server.tool()
@_locked
def generate_truss_2d(panels: int = 6, panel_width: float = 4000.0,
                      height: float = 4000.0, material: int = 1,
                      section: int = 1, replace: bool = True) -> dict:
    """Generate a simply supported planar truss with Pratt diagonals."""
    return _wizard_result("truss2d", {
        "kind": "truss2d", "mat": material, "panels": int(panels),
        "panel_width": float(panel_width), "height": float(height),
        "width": 0.0, "sec": section}, replace)


@server.tool()
@_locked
def generate_truss_3d(panels: int = 6, panel_width: float = 4000.0,
                      height: float = 4000.0, width: float = 4000.0,
                      material: int = 1, section: int = 1,
                      replace: bool = True) -> dict:
    """Generate a rectangular space truss with four chords."""
    return _wizard_result("truss3d", {
        "kind": "truss3d", "mat": material, "panels": int(panels),
        "panel_width": float(panel_width), "height": float(height),
        "width": float(width), "sec": section}, replace)


@server.tool()
@_locked
def generate_bridge(spans: int = 3, span_length: float = 30000.0,
                    width: float = 12000.0, girders: int = 5,
                    cross_spacing: float = 5000.0, material: int = 2,
                    girder_section: int = 2, cross_section: int = 2,
                    replace: bool = True) -> dict:
    """Generate a multi-span girder bridge grillage with pier supports."""
    return _wizard_result("bridge", {
        "kind": "bridge", "mat": material, "spans": int(spans),
        "span_length": float(span_length), "width": float(width),
        "girders": int(girders), "cross_spacing": float(cross_spacing),
        "girder_sec": girder_section, "cross_sec": cross_section}, replace)


@server.tool()
@_locked
def subdivide_elements(tags: List[int], parts: int = 2) -> dict:
    """Split beam or truss elements into equal parts, carrying loads over."""
    _require_elements(tags)
    if int(parts) < 2:
        raise ValueError("parts must be at least 2.")
    created_nodes, created_elements = _p().subdivide_elements(
        [int(t) for t in tags], int(parts))
    _changed(f"subdivide {len(tags)} element(s)")
    return {"ok": True, "created_nodes": created_nodes,
            "created_elements": created_elements}


# --------------------------------------------------------------------------- #
# hinges
# --------------------------------------------------------------------------- #
@server.tool()
@_locked
def list_hinge_materials() -> List[dict]:
    """List the OpenSees hinge material catalogue with parameter definitions."""
    return [{
        "key": spec.key, "label": spec.label, "family": spec.family,
        "kind": spec.kind, "note": spec.note,
        "params": [dict(param.__dict__) for param in spec.params],
    } for spec in hinge_catalog.MATERIALS.values()]


@server.tool()
@_locked
def add_hinge_definition(name: str = "Hinge", material: str = "Steel01",
                         length_ratio: float = 0.10,
                         params: Optional[Dict[str, float]] = None,
                         curve: Optional[List[List[float]]] = None) -> dict:
    """Create a reusable hinge definition using an OpenSees material name.

    For material='MomentBackbone', curve contains [rotation_rad, moment_kNmm]
    points.  The curve is required for a spring hinge that can be assigned to
    beam ends; use moment_curvature(create_hinge=true) to generate one.
    """
    spec = hinge_catalog.MATERIALS.get(material)
    if spec is None:
        raise ValueError(f"Unknown hinge material '{material}'. "
                         "Call list_hinge_materials for the names.")
    values = hinge_catalog.defaults(material)
    for key, value in (params or {}).items():
        if key not in values:
            raise ValueError(f"'{key}' is not a parameter of {material}.")
        values[key] = float(value)
    points = _curve_points(curve)
    if material == "MomentBackbone" and len(points) < 2:
        raise ValueError("MomentBackbone needs at least two curve points.")
    tag = _p().next_hinge()
    hinge = HingeDefinition(int(tag), str(name), material, spec.family,
                            float(length_ratio), values)
    hinge.curve = points
    _p().hinge_defs[tag] = hinge
    _changed(f"add hinge {tag}")
    return {"ok": True, **hinge.to_dict()}


@server.tool()
@_locked
def list_hinge_definitions() -> List[dict]:
    """List hinge definitions with their material, family and parameters."""
    return [h.to_dict() for h in sorted(_p().hinge_defs.values(),
                                        key=lambda h: h.tag)]


@server.tool()
@_locked
def update_hinge_definition(tag: int, name: Optional[str] = None,
                            material: Optional[str] = None,
                            length_ratio: Optional[float] = None,
                            params: Optional[Dict[str, float]] = None,
                            curve: Optional[List[List[float]]] = None) -> dict:
    """Update a hinge definition; changing the material resets its parameters.

    Pass curve=[] to clear a stored moment-rotation backbone.
    """
    hinge = _p().hinge_defs.get(int(tag))
    if hinge is None:
        raise ValueError(f"Unknown hinge definition {tag}.")
    if material is not None and material != hinge.material:
        spec = hinge_catalog.MATERIALS.get(material)
        if spec is None:
            raise ValueError(f"Unknown hinge material '{material}'.")
        hinge.material = material
        hinge.family = spec.family
        hinge.params = hinge_catalog.defaults(material)
    if name is not None:
        hinge.name = str(name)
    if length_ratio is not None:
        hinge.length_ratio = float(length_ratio)
    for key, value in (params or {}).items():
        if key not in hinge.params:
            raise ValueError(f"'{key}' is not a parameter of {hinge.material}.")
        hinge.params[key] = float(value)
    if curve is not None:
        hinge.curve = _curve_points(curve)
    _changed(f"update hinge {tag}")
    return {"ok": True, **hinge.to_dict()}


@server.tool()
@_locked
def delete_hinge_definition(tag: int) -> dict:
    """Delete a hinge definition and every element assignment using it."""
    p = _p()
    if int(tag) not in p.hinge_defs:
        raise ValueError(f"Unknown hinge definition {tag}.")
    p.hinge_defs.pop(int(tag), None)
    p.hinge_assignments = {e: h for e, h in p.hinge_assignments.items()
                           if h != int(tag)}
    _changed(f"delete hinge {tag}")
    return {"ok": True}


@server.tool()
@_locked
def assign_hinges(element_tags: List[int], hinge: int) -> dict:
    """Assign a hinge definition to beam elements (fibre or spring hinge)."""
    _require_elements(element_tags)
    definition = _p().hinge_defs.get(int(hinge))
    if definition is None:
        raise ValueError(f"Unknown hinge definition {hinge}.")
    if (definition.material == "MomentBackbone" and len(definition.curve) < 2):
        raise ValueError("MomentBackbone must have a stored curve before "
                         "assignment. Use moment_curvature(create_hinge=true) or "
                         "update_hinge_definition(curve=...).")
    bad = [t for t in element_tags if _p().elements[t].kind != "beam"]
    if bad:
        raise ValueError(f"Hinges apply to beam elements only; invalid: {bad}.")
    for tag in element_tags:
        _p().hinge_assignments[int(tag)] = int(hinge)
    _changed(f"assign hinge {hinge} to {len(element_tags)} element(s)")
    return {"ok": True, "hinge": int(hinge),
            "material": definition.material,
            "elements": [int(t) for t in element_tags]}


@server.tool()
@_locked
def list_hinge_assignments() -> List[dict]:
    """List element hinge assignments."""
    out = []
    for element, hinge in sorted(_p().hinge_assignments.items()):
        definition = _p().hinge_defs.get(hinge)
        out.append({
            "element": element, "hinge": hinge,
            "name": definition.name if definition else "",
            "material": definition.material if definition else "",
            "kind": (hinge_catalog.MATERIALS[definition.material].kind
                     if definition and definition.material in hinge_catalog.MATERIALS
                     else ""),
        })
    return out


@server.tool()
@_locked
def clear_hinge_assignments(element_tags: Optional[List[int]] = None) -> dict:
    """Remove hinge assignments (all of them, or from the given elements)."""
    p = _p()
    if element_tags is None:
        removed = list(p.hinge_assignments)
        p.hinge_assignments.clear()
    else:
        removed = [t for t in element_tags if t in p.hinge_assignments]
        for tag in removed:
            p.hinge_assignments.pop(tag, None)
    _changed(f"clear {len(removed)} hinge assignment(s)")
    return {"ok": True, "removed": removed}


@server.tool()
@_locked
def moment_curvature(section: str = "rectangular",
                     B: float = 400.0, H: float = 600.0, D: float = 600.0,
                     cover: float = 40.0, nx: int = 4, ny: int = 4,
                     n_bars: int = 12, db: float = 25.0, dbt: float = 10.0,
                     s: float = 100.0, fc: float = 30.0, fy: float = 420.0,
                     P: float = 0.0, L: float = 4000.0,
                     Lp_mm: float = 0.0,
                     axis: str = "strong",
                     include_curve: bool = True,
                     create_hinge: bool = False,
                     name: str = "Moment backbone",
                     assign_to: Optional[List[int]] = None) -> dict:
    """Reinforced-concrete moment-curvature and trilinear M-rotation backbone.

    Lengths in mm, fc/fy in MPa, P positive compression in kN.  axis is
    'strong' or 'weak' (weak applies to rectangular sections).  When
    create_hinge or assign_to is set, a MomentBackbone hinge definition is
    stored and optionally assigned to beam elements.  Curve points are
    [rotation_rad, moment_kNmm].
    """
    inputs = moment_curvature_engine.MomentCurvatureInput(
        section=str(section), B=float(B), H=float(H), D=float(D),
        cover=float(cover), nx=int(nx), ny=int(ny), n_bars=int(n_bars),
        db=float(db), dbt=float(dbt), s=float(s), fc=float(fc), fy=float(fy),
        P=float(P), L=float(L), Lp_mm=float(Lp_mm))
    result = moment_curvature_engine.run_moment_curvature(inputs)
    curve = (result.weak if axis.lower() == "weak" and result.weak is not None
             else result.strong)
    if axis.lower() == "weak" and result.weak is None:
        axis = "strong"

    def curve_payload(c, axis_name: str = axis) -> dict:
        return {
            "axis": axis_name,
            "yield_moment_kNm": c.yield_moment / 1000.0,
            "peak_moment_kNm": c.peak_moment / 1000.0,
            "ultimate_moment_kNm": c.ultimate_moment / 1000.0,
            "yield_rotation_rad": c.yield_rotation,
            "peak_rotation_rad": c.peak_rotation,
            "ultimate_rotation_rad": c.ultimate_rotation,
            "initial_stiffness_kNmm_rad": c.initial_stiffness,
            "post_yield_ratio": c.post_yield_ratio,
            "ductility": c.ductility,
            "converged_points": c.converged,
            "total_points": c.total,
            "backbone": [[float(r), float(m)] for r, m in c.backbone],
            "moment_curvature": ([[float(phi), float(m)]
                                 for phi, m in zip(c.curvatures, c.moments)]
                                if include_curve else []),
        }

    payload: Dict[str, Any] = {
        "section": inputs.section,
        "axis": axis,
        "Ag_mm2": result.Ag,
        "Ast_mm2": result.Ast,
        "reinforcement_ratio": result.reinforcement_ratio,
        "Lp_mm": result.Lp_mm,
        "confinement": {
            "fcc_MPa": result.confinement.get("fcc"),
            "ecc": result.confinement.get("ecc"),
            "ecu": result.confinement.get("ecu"),
            "fLp_MPa": result.confinement.get("fLp"),
        },
        "strong": curve_payload(result.strong, "strong"),
        "weak": (curve_payload(result.weak, "weak")
                 if result.weak is not None else None),
        "warnings": result.warnings,
    }
    if create_hinge or assign_to:
        if assign_to:
            _require_elements(assign_to)
            bad = [t for t in assign_to if _p().elements[t].kind != "beam"]
            if bad:
                raise ValueError(f"Hinges apply to beam elements only; invalid: {bad}.")
        points = [[float(r), float(m)] for r, m in curve.backbone[1:]]
        if len(points) < 2:
            raise ValueError("The moment-curvature result has no usable backbone.")
        params = hinge_catalog.defaults("MomentBackbone")
        params["damage1"] = 0.0
        params["damage2"] = 0.0
        tag = _p().next_hinge()
        ratio = max(0.01, min(0.25, result.Lp_mm / max(inputs.L, 1.0)))
        definition = HingeDefinition(
            int(tag), str(name), "MomentBackbone",
            "Moment-rotation (spring)", ratio, params)
        definition.curve = points
        _p().hinge_defs[tag] = definition
        assigned = []
        if assign_to:
            for element in assign_to:
                _p().hinge_assignments[int(element)] = int(tag)
                assigned.append(int(element))
        _changed(f"add moment backbone hinge {tag}")
        payload["hinge"] = definition.to_dict()
        payload["assigned_elements"] = assigned
    return payload


    """List the material library."""
    return [dict(m.__dict__) for m in _p().materials.values()]


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
                J: float = 0.0,
                outline_outer: Optional[List[List[float]]] = None,
                outline_inner: Optional[List[List[float]]] = None) -> dict:
    """Add a section.

    shape = Rectangle | Circle | Hexagon | Octagon | Box | Pipe | I-Shape |
    L-Shape | T-Shape | User.  For User, A/Iy/Iz/J are used as given; other
    shapes compute them from dimensions (mm, mm^4).  outline_outer/inner are
    optional local (y, z) outlines for custom-section preview and 3D drawing.
    """
    if shape not in ("Rectangle", "Circle", "Hexagon", "Octagon", "Box",
                     "Pipe", "I-Shape", "L-Shape", "T-Shape", "User"):
        raise ValueError("Unsupported section shape.")
    tag = _p().next_section()
    s = Section(tag, name, shape, b, h, d, t, tw, tf, A, Iy, Iz, J)
    if shape != "User":
        s.compute()
    if outline_outer:
        s.outline_outer = [[float(p[0]), float(p[1])] for p in outline_outer]
    if outline_inner:
        s.outline_inner = [[float(p[0]), float(p[1])] for p in outline_inner]
    _p().sections[tag] = s
    _changed(f"add section {tag}")
    return {"ok": True, "tag": tag, "A": s.A, "Iy": s.Iy, "Iz": s.Iz, "J": s.J,
            "outline_outer_points": len(s.outline_outer),
            "outline_inner_points": len(s.outline_inner)}


@server.tool()
@_locked
def section_properties(shape: str = "IShape", b: float = 200.0,
                       d: float = 300.0, tf: float = 15.0,
                       tw: float = 10.0, t: float = 12.0,
                       b_inner: float = 150.0, d_inner: float = 250.0,
                       gap: float = 50.0, c: float = 20.0,
                       holeR: float = 50.0, max_nodes: int = 9000) -> dict:
    """Section Property Pro: area, inertias, J and Cw for a parametric shape.

    shape is IShape, TShape, CShape, LShape, Rectangle, RectHollow, OpenBox,
    SolidCircle, Pipe, Hexagon, Octagon, DoubleAngle, DoubleChannel or
    OctagonHole.  Dimensions are mm.  The returned section_fields mapping is
    ready for add_section(shape='User', ...).
    """
    if shape not in section_property.SHAPE_DEFS:
        raise ValueError(f"Unknown shape '{shape}'. "
                         f"Use {list(section_property.SHAPE_DEFS)}.")
    values = {"b": b, "d": d, "tf": tf, "tw": tw, "t": t,
              "b_inner": b_inner, "d_inner": d_inner, "gap": gap,
              "c": c, "holeR": holeR}
    params = {key: float(values[key])
              for key in section_property.SHAPE_DEFS[shape][1]}
    result = section_property.compute_section_properties(
        shape, params, max_nodes=int(max_nodes))
    return {
        "shape": result.shape,
        "params": result.params,
        "A_mm2": result.A,
        "Cx_mm": result.Cx,
        "Cy_mm": result.Cy,
        "Ix_mm4": result.Ix,
        "Iy_mm4": result.Iy,
        "Ixy_mm4": result.Ixy,
        "Ip_mm4": result.Ip,
        "I1_mm4": result.I1,
        "I2_mm4": result.I2,
        "principal_angle_deg": result.alpha,
        "Sx_top_mm3": result.SxTop,
        "Sx_bottom_mm3": result.SxBot,
        "Sy_right_mm3": result.SyRight,
        "Sy_left_mm3": result.SyLeft,
        "rx_mm": result.rx,
        "ry_mm": result.ry,
        "J_mm4": result.J,
        "Cw_mm6": result.Cw,
        "torsion_source": result.torsion_source,
        "warping_source": result.warping_source,
        "mass_per_length_kg_m": result.mass_per_length,
        "warnings": result.warnings,
        "section_fields": {"A": result.A, "Iy": result.Ix,
                           "Iz": result.Iy, "J": result.J},
        "outlines": [{"outer": [[float(x), float(y)] for x, y in outer],
                      "holes": [[[float(x), float(y)] for x, y in hole]
                                for hole in result.holes]}
                     for outer in result.outers],
    }


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


@server.tool()
@_locked
def add_point_spring(node: int, dof: int = 1, kind: str = "linear",
                     k: float = 10.0,
                     curve: Optional[List[List[float]]] = None,
                     pult: float = 100.0, y50: float = 10.0,
                     cd: float = 0.5, soil_type: int = 1,
                     behavior: str = "") -> dict:
    """Add a zeroLength point spring at a node (linear, multilinear or p-y).

    dof: 1..6 (UX, UY, UZ, RX, RY, RZ). curve contains [displacement, force]
    backbone points and is used for kind='multilinear'. PySimple1 is used for
    kind='py' with translational DOFs. behavior: '', 'tension' or 'compression'.
    """
    p = _p()
    if int(node) not in p.nodes:
        raise ValueError(f"Unknown node {node}.")
    if not 1 <= int(dof) <= 6:
        raise ValueError("dof must be between 1 and 6.")
    if kind not in ("linear", "multilinear", "py"):
        raise ValueError("kind must be linear, multilinear or py.")
    if behavior not in ("", "tension", "compression"):
        raise ValueError("behavior must be '', tension or compression.")
    if kind == "py" and int(dof) > 3:
        raise ValueError("PySimple1 springs need a translational DOF (1-3).")
    if kind == "py" and behavior:
        raise ValueError("P-Y springs do not use a tension/compression wrapper.")
    if kind == "multilinear" and behavior == "compression":
        raise ValueError("OpenSees has no compression-only wrapper for a "
                         "multi-linear curve.")
    points = [[float(u), float(f)] for u, f in (curve or [[0.0, 0.0], [1.0, 10.0]])]
    if kind == "multilinear" and len(points) < 2:
        raise ValueError("curve needs at least two points.")
    for tag, existing in list(p.springs.items()):
        if existing.node == int(node) and existing.dof == int(dof):
            p.springs.pop(tag, None)
    tag = p.next_spring()
    p.springs[tag] = SpringSupport(
        tag, int(node), dof=int(dof), kind=kind, k=float(k),
        curve=points, pult=float(pult), y50=float(y50), cd=float(cd),
        soil_type=int(soil_type), behavior=behavior)
    _changed(f"add point spring {tag}")
    return {"ok": True, **p.springs[tag].to_dict()}


@server.tool()
@_locked
def list_springs() -> List[dict]:
    """List point springs (zeroLength supports)."""
    return [s.to_dict() for s in sorted(_p().springs.values(),
                                        key=lambda s: s.tag)]


@server.tool()
@_locked
def delete_point_spring(tag: int) -> dict:
    """Delete a point spring."""
    if int(tag) not in _p().springs:
        raise ValueError(f"Unknown point spring {tag}.")
    _p().springs.pop(int(tag), None)
    _changed(f"delete point spring {tag}")
    return {"ok": True}


@server.tool()
@_locked
def add_constraint(kind: str, master: int, slaves: List[int],
                   dofs: Optional[List[int]] = None, perp: int = 3) -> dict:
    """Add a rigidLink beam/bar, equalDOF or rigidDiaphragm constraint.

    kind: rigid_beam, rigid_bar, equal_dof or rigid_diaphragm.
    """
    p = _p()
    if kind not in ("rigid_beam", "rigid_bar", "equal_dof", "rigid_diaphragm"):
        raise ValueError("Invalid constraint kind.")
    if int(master) not in p.nodes:
        raise ValueError(f"Unknown master node {master}.")
    slave_tags = [int(s) for s in slaves if int(s) in p.nodes]
    if not slave_tags:
        raise ValueError("No valid slave nodes.")
    if int(master) in slave_tags:
        raise ValueError("The master node cannot also be a slave.")
    values = [int(d) for d in (dofs or [1, 2, 3])]
    if kind == "equal_dof" and not any(1 <= d <= 6 for d in values):
        raise ValueError("equal_dof needs at least one DOF (1-6).")
    tag = p.next_constraint()
    p.constraints[tag] = BoundaryConstraint(
        tag, kind, int(master), slave_tags, values, int(perp))
    _changed(f"add constraint {tag}")
    return {"ok": True, **p.constraints[tag].to_dict()}


@server.tool()
@_locked
def list_constraints() -> List[dict]:
    """List rigid links, equalDOF constraints and rigid diaphragms."""
    return [c.to_dict() for c in sorted(_p().constraints.values(),
                                        key=lambda c: c.tag)]


@server.tool()
@_locked
def delete_constraint(tag: int) -> dict:
    """Delete a node constraint."""
    if int(tag) not in _p().constraints:
        raise ValueError(f"Unknown constraint {tag}.")
    _p().constraints.pop(int(tag), None)
    _changed(f"delete constraint {tag}")
    return {"ok": True}


@server.tool()
@_locked
def add_lane(name: str, start: List[float], end: List[float],
             offset: float = 0.0, width: float = 0.0) -> dict:
    """Define a straight traffic lane from start/end points (mm).

    offset is the lateral shift in mm, positive to the left of start -> end.
    """
    p = _p()
    if len(start) != 3 or len(end) != 3:
        raise ValueError("Lane start and end must be [x, y, z] points in mm.")
    s = tuple(float(v) for v in start)
    e = tuple(float(v) for v in end)
    if any(abs(v) == float("inf") or v != v for v in (*s, *e)):
        raise ValueError("Lane coordinates must be finite.")
    if (sum((a - b) ** 2 for a, b in zip(s, e))) ** 0.5 <= 1e-6:
        raise ValueError("Lane start and end must be different points.")
    lane = Lane(p.next_lane(), name or "Lane", s, e,
                float(offset), float(width))
    p.lanes[lane.tag] = lane
    _changed(f"add traffic lane {lane.tag}")
    return {"ok": True, **lane.to_dict()}


@server.tool()
@_locked
def add_lane_from_elements(name: str, beam_tags: List[int],
                           offset: float = 0.0,
                           reverse: bool = False) -> dict:
    """Define a lane from a selected single beam-element chain.

    The element tags must form one continuous line; the lane direction is the
    chain order, optionally reversed.
    """
    p = _p()
    geometry = live_load_engine.chain_geometry(p, [int(t) for t in beam_tags])
    if geometry is None:
        raise ValueError("beam_tags must form a single continuous beam line.")
    points = [tuple(pt[1]) for pt in geometry["points"]]
    elements = [int(t) for t in geometry["element_tags"]]
    if reverse:
        points.reverse()
        elements.reverse()
    lane = Lane(p.next_lane(), name or "Lane", points[0], points[-1],
                float(offset), 0.0, points, elements)
    p.lanes[lane.tag] = lane
    _changed(f"add traffic lane {lane.tag} from elements")
    return {"ok": True, **lane.to_dict()}


@server.tool()
@_locked
def list_lanes() -> List[dict]:
    """List traffic lane definitions."""
    return [lane.to_dict() for lane in sorted(_p().lanes.values(),
                                              key=lambda lane: lane.tag)]


@server.tool()
@_locked
def update_lane(tag: int, name: Optional[str] = None,
                start: Optional[List[float]] = None,
                end: Optional[List[float]] = None,
                offset: Optional[float] = None,
                width: Optional[float] = None) -> dict:
    """Update a traffic lane. Omitted fields keep their current values."""
    p = _p()
    lane = p.lanes.get(int(tag))
    if lane is None:
        raise ValueError(f"Unknown traffic lane {tag}.")
    if name is not None:
        lane.name = str(name)
    if start is not None:
        if len(start) != 3:
            raise ValueError("Lane start must be [x, y, z] in mm.")
        lane.start = tuple(float(v) for v in start)
    if end is not None:
        if len(end) != 3:
            raise ValueError("Lane end must be [x, y, z] in mm.")
        lane.end = tuple(float(v) for v in end)
    if offset is not None:
        lane.offset = float(offset)
    if width is not None:
        lane.width = float(width)
    if lane.length <= 1e-6:
        raise ValueError("Lane start and end must be different points.")
    _changed(f"update traffic lane {tag}")
    return {"ok": True, **lane.to_dict()}


@server.tool()
@_locked
def delete_lane(tag: int) -> dict:
    """Delete a traffic lane."""
    if int(tag) not in _p().lanes:
        raise ValueError(f"Unknown traffic lane {tag}.")
    _p().lanes.pop(int(tag), None)
    _changed(f"delete traffic lane {tag}")
    return {"ok": True}


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
def list_loads(case: str = "") -> dict:
    """List nodal and element loads, optionally filtered by load case."""
    p = _p()
    nodal = [l.to_dict() for l in p.nodal_loads if not case or l.case == case]
    element = [l.to_dict() for l in p.elem_loads if not case or l.case == case]
    self_weight = {c: f for c, f in p.self_weight.items()
                   if not case or c == case}
    return {"case": case or "all", "nodal_loads": nodal,
            "element_loads": element, "self_weight": self_weight}


@server.tool()
@_locked
def get_settings() -> dict:
    """Return analysis settings and the stored pushover configuration."""
    return {"settings": dict(_p().settings),
            "pushover": _p().pushover_settings()}


@server.tool()
@_locked
def set_settings(static_steps: Optional[float] = None,
                 modal_modes: Optional[int] = None,
                 mass_from_density: Optional[bool] = None) -> dict:
    """Update static/modal analysis settings."""
    p = _p()
    if static_steps is not None:
        if float(static_steps) <= 0:
            raise ValueError("static_steps must be positive.")
        p.settings["static_steps"] = float(static_steps)
    if modal_modes is not None:
        p.settings["modal_modes"] = int(modal_modes)
    if mass_from_density is not None:
        p.settings["mass_from_density"] = bool(mass_from_density)
    return {"ok": True, "settings": dict(p.settings)}


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
    STATE.pushover = STATE.time_history = STATE.spectrum = None
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
    STATE.pushover = STATE.time_history = STATE.spectrum = None
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


@server.tool()
@_locked
def import_tcl(path: str) -> dict:
    """Replace the model with nodes, elements, supports and loads from Tcl."""
    source = Path(path)
    if not source.exists():
        raise ValueError(f"Tcl file not found: {source}")
    project, info = tcl.import_text(source.read_text(encoding="utf-8",
                                                     errors="replace"),
                                    source.name)
    if not project.nodes and not project.elements:
        raise ValueError("No model commands were found in the Tcl file.")
    STATE.project = project
    STATE.static = STATE.modal = None
    STATE.pushover = STATE.time_history = STATE.spectrum = None
    _changed(f"import Tcl {source.name}", sync=True)
    return {"ok": True, "path": str(source), **info}


@server.tool()
@_locked
def run_python(code: str) -> dict:
    """Run Python against OpenSeesPy in the shared analysis domain.

    The Studio project is not modified; this is for model experiments and
    OpenSeesPy commands with ``ops`` available.
    """
    return tcl.run_python(code)


@server.tool()
@_locked
def run_tcl(code: str) -> dict:
    """Run OpenSees Tcl model commands (no loops, procedures or variables)."""
    return tcl.run_tcl(code)


# --------------------------------------------------------------------------- #
# pushover
# --------------------------------------------------------------------------- #
@server.tool()
@_locked
def run_pushover(gravity_case: str = "", lateral_case: str = "",
                 control_node: int = 0, control_dof: int = 1,
                 target_displacement: float = 0.0,
                 steps: int = 20) -> dict:
    """Run a displacement-controlled pushover with the assigned hinges."""
    config: Dict[str, Any] = {"gravity_case": gravity_case,
                              "lateral_case": lateral_case}
    if int(control_node) > 0:
        config["control_node"] = int(control_node)
    config["control_dof"] = int(control_dof)
    if float(target_displacement) > 0.0:
        config["target_displacement"] = float(target_displacement)
    config["steps"] = int(steps)
    if not config["lateral_case"]:
        raise ValueError("lateral_case is required.")
    res = opsgen.run_pushover(_p(), config)
    STATE.pushover = res
    STATE.static = STATE.modal = None
    return {"ok": True, "hinge_model": res.hinge_model,
            "control_node": res.control_node, "control_dof": res.control_dof,
            "steps": int(steps), "points": len(res.steps),
            "peak_base_shear": max((abs(s.base_shear) for s in res.steps),
                                   default=0.0),
            "peak_displacement": max((abs(s.displacement) for s in res.steps),
                                     default=0.0),
            "hinges_yielded": len(res.hinge_yield)}


@server.tool()
@_locked
def get_pushover_results(include_steps: bool = True) -> dict:
    """Return the pushover curve, hinge yielding and optional step details."""
    if STATE.pushover is None:
        raise ValueError("No pushover results. Call run_pushover first.")
    res = STATE.pushover
    out: Dict[str, Any] = {
        "hinge_model": res.hinge_model,
        "gravity_case": res.gravity_case,
        "lateral_case": res.lateral_case,
        "control_node": res.control_node,
        "control_dof": res.control_dof,
        "hinge_yield": {str(k): v for k, v in res.hinge_yield.items()},
    }
    if include_steps:
        out["steps"] = [{"step": s.step, "displacement": s.displacement,
                         "base_shear": s.base_shear} for s in res.steps]
    return out


@server.tool()
@_locked
def get_pushover_step(step: int = -1) -> dict:
    """Return displacements and hinge rotations at one pushover step."""
    if STATE.pushover is None:
        raise ValueError("No pushover results. Call run_pushover first.")
    data = STATE.pushover
    try:
        entry = data.steps[int(step)]
    except IndexError as exc:
        raise ValueError(f"Pushover step {step} is out of range.") from exc
    return {"step": entry.step, "displacement": entry.displacement,
            "base_shear": entry.base_shear,
            "node_displacements": {str(k): v
                                   for k, v in entry.displacements.items()},
            "hinge_rotations": {str(k): v
                                for k, v in entry.hinge_rotations.items()},
            "hinge_moments": {str(k): v
                              for k, v in entry.hinge_moments.items()}}


# --------------------------------------------------------------------------- #
# ground motions, time history and response spectrum
# --------------------------------------------------------------------------- #
@server.tool()
@_locked
def list_ground_motions() -> List[dict]:
    """List the ground-motion catalog."""
    return [rec.to_dict() for rec in
            sorted(_p().ground_motions.values(), key=lambda r: r.tag)]


@server.tool()
@_locked
def add_ground_motion(path: str, name: str = "", scale: float = 1.0,
                      format: str = "auto", note: str = "") -> dict:
    """Add a record to the catalog and detect its time step and point count."""
    source = Path(path)
    if not source.exists():
        raise ValueError(f"Ground-motion file not found: {source}")
    try:
        data = groundmotion.read_file(source, format, 0.01)
    except Exception as exc:  # noqa: BLE001 - report the reader error
        raise ValueError(f"Could not read ground motion: {exc}") from exc
    tag = _p().next_ground_motion()
    record = GroundMotionRecord(
        tag=tag, name=name or source.stem, path=str(source),
        format=data.format, dt=data.dt, npts=data.npts,
        scale=float(scale), note=note or data.note)
    _p().ground_motions[tag] = record
    _changed(f"add ground motion {tag}")
    return {"ok": True, **record.to_dict()}


@server.tool()
@_locked
def delete_ground_motion(tag: int) -> dict:
    """Remove a record from the ground-motion catalog."""
    if int(tag) not in _p().ground_motions:
        raise ValueError(f"Unknown ground-motion record {tag}.")
    _p().ground_motions.pop(int(tag), None)
    _changed(f"delete ground motion {tag}")
    return {"ok": True}


@server.tool()
@_locked
def record_response_spectrum(tag: int, periods: List[float],
                             damping_ratio: float = 0.05) -> dict:
    """Compute a pseudo-acceleration spectrum from a catalog record."""
    record = _p().ground_motions.get(int(tag))
    if record is None:
        raise ValueError(f"Unknown ground-motion record {tag}.")
    values = groundmotion.spectrum_from_record(
        record, [float(t) for t in periods], float(damping_ratio))
    return {"ok": True, "record": int(tag), "name": record.name,
            "periods": [float(t) for t in periods],
            "accelerations": values}


@server.tool()
@_locked
def configure_time_history(name: Optional[str] = None,
                           source: Optional[str] = None,
                           path: Optional[str] = None,
                           format: Optional[str] = None,
                           record: Optional[int] = None,
                           dt: Optional[float] = None,
                           n_steps: Optional[int] = None,
                           direction: Optional[int] = None,
                           scale: Optional[float] = None,
                           damping_ratio: Optional[float] = None,
                           damping_mode: Optional[int] = None,
                           gravity_case: Optional[str] = None,
                           sine_amplitude: Optional[float] = None,
                           sine_period: Optional[float] = None) -> dict:
    """Update the stored time-history case (source: sine, file or catalog)."""
    case = _p().time_history
    updates = {
        "name": name, "source": source, "path": path, "format": format,
        "record": record, "dt": dt, "n_steps": n_steps,
        "direction": direction, "scale": scale,
        "damping_ratio": damping_ratio, "damping_mode": damping_mode,
        "gravity_case": gravity_case, "sine_amplitude": sine_amplitude,
        "sine_period": sine_period,
    }
    for key, value in updates.items():
        if value is not None:
            setattr(case, key, value)
    if case.source == "catalog" and case.record not in _p().ground_motions:
        raise ValueError(f"Catalog record {case.record} does not exist.")
    _changed("configure time history")
    return {"ok": True, **case.to_dict()}


@server.tool()
@_locked
def get_time_history_settings() -> dict:
    """Return the stored time-history case."""
    return _p().time_history.to_dict()


@server.tool()
@_locked
def run_time_history() -> dict:
    """Run the stored time-history case and return peak response values."""
    res = opsgen.run_time_history(_p())
    STATE.time_history = res
    STATE.static = STATE.modal = None
    return {"ok": True, "case": res.case_name, "dt": res.dt,
            "steps": res.n_steps, "steps_requested": res.n_steps_requested,
            "peak_disp": res.peak_disp, "peak_vel": res.peak_vel,
            "peak_accel": res.peak_accel,
            "early_stop": res.early_stop}


@server.tool()
@_locked
def get_time_history_results(step: int = -1,
                             node_tags: Optional[List[int]] = None,
                             element_tags: Optional[List[int]] = None) -> dict:
    """Return time-history histories, or all node/element values at one step."""
    if STATE.time_history is None:
        raise ValueError("No time-history results. Call run_time_history first.")
    res = STATE.time_history
    nodes = node_tags if node_tags is not None else list(res.node_disp)
    elems = element_tags if element_tags is not None else list(res.element_forces)
    out: Dict[str, Any] = {"case": res.case_name, "dt": res.dt,
                           "steps": res.n_steps, "time": res.time}
    if step is None or int(step) < 0:
        out["node_disp"] = {str(t): res.node_disp.get(t, []) for t in nodes}
        out["node_vel"] = {str(t): res.node_vel.get(t, []) for t in nodes}
        out["node_accel"] = {str(t): res.node_accel.get(t, []) for t in nodes}
        out["element_forces"] = {str(t): res.element_forces.get(t, [])
                                 for t in elems}
    else:
        index = min(int(step), res.n_steps - 1)
        out["step"] = index
        out["node_disp"] = {str(t): res.node_disp[t][index]
                            for t in nodes if t in res.node_disp}
        out["node_vel"] = {str(t): res.node_vel[t][index]
                           for t in nodes if t in res.node_vel}
        out["node_accel"] = {str(t): res.node_accel[t][index]
                             for t in nodes if t in res.node_accel}
        out["element_forces"] = {str(t): res.element_forces[t][index]
                                 for t in elems if t in res.element_forces}
    return out


@server.tool()
@_locked
def configure_response_spectrum(name: Optional[str] = None,
                                direction: Optional[int] = None,
                                damping_ratio: Optional[float] = None,
                                combination: Optional[str] = None,
                                n_modes: Optional[int] = None,
                                scale: Optional[float] = None,
                                record: Optional[int] = None,
                                periods: Optional[List[float]] = None,
                                accelerations: Optional[List[float]] = None) -> dict:
    """Update the stored response-spectrum case and its curve."""
    case = _p().response_spectrum
    if name is not None:
        case.name = str(name)
    if direction is not None:
        case.direction = int(direction)
    if damping_ratio is not None:
        case.damping_ratio = float(damping_ratio)
    if combination is not None:
        if combination.upper() not in ("SRSS", "CQC"):
            raise ValueError("combination must be SRSS or CQC.")
        case.combination = combination.upper()
    if n_modes is not None:
        case.n_modes = int(n_modes)
    if scale is not None:
        case.scale = float(scale)
    if record is not None:
        case.record = int(record)
    if periods is not None:
        case.periods = [float(v) for v in periods]
    if accelerations is not None:
        case.accelerations = [float(v) for v in accelerations]
    if len(case.periods) != len(case.accelerations):
        raise ValueError("periods and accelerations must have the same length.")
    _changed("configure response spectrum")
    return {"ok": True, **case.to_dict()}


@server.tool()
@_locked
def get_response_spectrum_settings() -> dict:
    """Return the stored response-spectrum case."""
    return _p().response_spectrum.to_dict()


@server.tool()
@_locked
def run_response_spectrum() -> dict:
    """Run the stored response-spectrum case with SRSS or CQC combination."""
    res = opsgen.run_response_spectrum(_p())
    STATE.spectrum = res
    STATE.static = STATE.modal = None
    return {"ok": True, "case": res.case_name, "modes": res.n_modes,
            "combination": res.combination, "peak_disp": res.peak_disp,
            "modal_periods": res.modal_periods,
            "modal_mass_ratios": res.modal_mass_ratios}


@server.tool()
@_locked
def get_response_spectrum_results(node_tags: Optional[List[int]] = None,
                                  element_tags: Optional[List[int]] = None,
                                  include_forces: bool = False) -> dict:
    """Return combined response-spectrum displacements and element forces."""
    if STATE.spectrum is None:
        raise ValueError("No response-spectrum results. "
                         "Call run_response_spectrum first.")
    res = STATE.spectrum
    nodes = node_tags if node_tags is not None else list(res.node_disp)
    elems = element_tags if element_tags is not None else list(res.element_forces)
    out: Dict[str, Any] = {
        "case": res.case_name, "direction": res.direction,
        "combination": res.combination, "peak_disp": res.peak_disp,
        "node_disp": {str(t): res.node_disp[t] for t in nodes
                      if t in res.node_disp},
    }
    if include_forces:
        out["element_forces"] = {str(t): res.element_forces.get(t, [])
                                 for t in elems}
    return out


# --------------------------------------------------------------------------- #
# bridge live load
# --------------------------------------------------------------------------- #
@server.tool()
@_locked
def live_load(spans: Optional[List[float]] = None,
              axles: Optional[List[List[float]]] = None,
              truck_model: str = "CL-625",
              bcl_subdivision: float = 1.0,
              load_case: str = "truck",
              E_GPa: float = 200.0, I_m4: float = 0.005,
              elems_per_span: int = 20,
              truck_increment: float = 0.25,
              dla_override: Optional[float] = None,
              dla_multiplier: float = 1.0,
              lane_udl: float = 9.0,
              lane_start: Optional[float] = None,
              lane_end: Optional[float] = None,
              lane_offset: float = 0.0,
              lane_tag: Optional[int] = None,
              beam_tags: Optional[List[int]] = None,
              include_curves: bool = True,
              include_influence: bool = False) -> dict:
    """Bridge moving-truck and lane-load envelopes and influence lines.

    spans are continuous-beam span lengths in m.  axles are [load_kN, spacing_m]
    pairs and are used when truck_model='Custom'.  E_GPa and I_m4 define the
    constant beam section.  beam_tags optionally imports spans and mean E/I
    from selected beam elements; spans then default to the detected spans.
    dla_override is a fraction (0.25 = 25%) or null for auto selected-axle DLA.
    Envelope curves are returned as [x, max, min] because the analyser is an
    envelope engine, not a time-history vehicle run.
    """
    beam_note = ""
    lane_note = ""
    if lane_tag is not None:
        lane = _p().lanes.get(int(lane_tag))
        if lane is None:
            raise ValueError(f"Unknown traffic lane {lane_tag}.")
        base_m = 0.0
        if beam_tags:
            base_m = min((_p().node_xyz(t)[0]
                          for tag in beam_tags if int(tag) in _p().elements
                          for t in _p().elements[int(tag)].nodes),
                         default=0.0) / 1000.0
        if lane_start is None:
            lane_start = (min(lane.shifted_start[0], lane.shifted_end[0])
                          / 1000.0 - base_m)
        if lane_end is None:
            lane_end = (max(lane.shifted_start[0], lane.shifted_end[0])
                        / 1000.0 - base_m)
        lane_offset = lane.offset / 1000.0
        lane_note = lane.name
    if beam_tags:
        chain = live_load_engine.beam_chain_from_project(_p(), beam_tags)
        if chain is None:
            raise ValueError("beam_tags do not form a connected beam chain.")
        chain_spans, chain_e, chain_i, beam_note = chain
        if spans is None:
            spans = [s.length for s in chain_spans]
            E_GPa = chain_e / 1e9
            I_m4 = chain_i
    if spans is None:
        raise ValueError("Provide spans in metres or beam_tags for a selected chain.")
    span_objects = [live_load_engine.Span(float(length)) for length in spans]
    axle_objects = []
    for pair in (axles or []):
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("axles must be [load_kN, spacing_m] pairs.")
        axle_objects.append(live_load_engine.Axle(float(pair[0]), float(pair[1])))
    config = live_load_engine.LiveLoadConfig(
        E=float(E_GPa) * 1e9, I=float(I_m4),
        elems_per_span=int(elems_per_span),
        truck_increment=float(truck_increment),
        load_case=str(load_case),
        dla_override=(None if dla_override is None else float(dla_override)),
        dla_multiplier=float(dla_multiplier),
        lane_udl=float(lane_udl),
        truck_model=str(truck_model),
        bcl_subdivision=float(bcl_subdivision),
        lane_start=(None if lane_start is None else float(lane_start)),
        lane_end=(None if lane_end is None else float(lane_end)),
        lane_offset=float(lane_offset))
    result = live_load_engine.analyze(span_objects, axle_objects, config)

    def summary(points, scale: float = 1.0) -> dict:
        high = max(points, key=lambda p: p.max)
        low = min(points, key=lambda p: p.min)
        return {"max": float(high.max * scale), "max_x": float(high.x),
                "min": float(low.min * scale), "min_x": float(low.x)}

    cases_out: Dict[str, Any] = {}
    for name, case in result.cases.items():
        case_out: Dict[str, Any] = {
            "shear": summary(case.shear),
            "moment": summary(case.moment),
            "deflection_m": summary(case.deflection),
            "reactions": [{
                "support": index + 1, "x": float(reaction.x),
                "max_kN": float(reaction.max), "min_kN": float(reaction.min),
                "governing_lead_m": float(reaction.governing_position),
                "governing_bcl_gap_m": reaction.governing_spacing,
            } for index, reaction in enumerate(case.reactions)],
            "dla_used": case.dla_used,
            "dla_auto": case.dla_auto,
            "dla_base": case.dla_base,
            "dla_multiplier": case.dla_multiplier,
        }
        if include_curves:
            case_out["shear_curve"] = [[float(p.x), float(p.max), float(p.min)]
                                      for p in case.shear]
            case_out["moment_curve"] = [[float(p.x), float(p.max), float(p.min)]
                                       for p in case.moment]
            case_out["deflection_curve_m"] = [
                [float(p.x), float(p.max), float(p.min)] for p in case.deflection]
        cases_out[name] = case_out
    out: Dict[str, Any] = {
        "load_case": result.load_case,
        "spans_m": [span.length for span in result.spans],
        "truck_model": result.config.truck_model,
        "axle_count": len(result.axles),
        "increment_m": result.increment_used,
        "base_increment_m": result.base_increment,
        "increment_reason": result.increment_reason,
        "position_count": len(result.truck_positions),
        "bcl_spacings_m": result.bcl_spacings,
        "lane": {
            "name": lane_note or result.config.lane_name,
            "start_m": result.config.lane_start,
            "end_m": result.config.lane_end,
            "offset_m": result.config.lane_offset,
        },
        "summary": result.summary(),
        "cases": cases_out,
        "units": {"length": "m", "E": "GPa", "I": "m4",
                  "force": "kN", "moment": "kN m", "deflection": "m"},
        "beam_chain_note": beam_note,
    }
    if include_influence:
        out["influence"] = {
            key: [[float(x), float(value)] for x, value in points]
            for key, points in result.influence.items()}
    return out


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
def gui_set_visibility(mode: str = "activate",
                       nodes: Optional[List[int]] = None,
                       elements: Optional[List[int]] = None) -> dict:
    """Activate, deactivate or restore visibility in the attached GUI.

    mode: "activate" (show only the selection), "deactivate" (hide the
    selection) or "all" (show everything).
    """
    if not STATE.gui.connected:
        raise ValueError("No GUI attached. Call gui_connect first.")
    result = STATE.gui.call("set_visibility", {
        "mode": mode, "nodes": nodes or [], "elements": elements or []})
    return {"ok": True, **result}


@server.tool()
@_locked
def gui_set_labels(node_labels: Optional[bool] = None,
                   element_labels: Optional[bool] = None) -> dict:
    """Show or hide node and element tags in the attached GUI."""
    if not STATE.gui.connected:
        raise ValueError("No GUI attached. Call gui_connect first.")
    params = {}
    if node_labels is not None:
        params["node_labels"] = bool(node_labels)
    if element_labels is not None:
        params["element_labels"] = bool(element_labels)
    result = STATE.gui.call("set_labels", params)
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


@server.tool()
@_locked
def gui_show_diagram(scenario: str = "",
                     components: Optional[List[str]] = None) -> dict:
    """Show beam force diagrams for a static case in the attached GUI."""
    if not STATE.gui.connected:
        raise ValueError("No GUI attached. Call gui_connect first.")
    comps = components or ["My"]
    result = STATE.gui.call("show_diagram", {
        "scenario": scenario, "components": comps})
    return {"ok": True, "showing": "diagram",
            "scenario": scenario or (STATE.static.scenario if STATE.static else ""),
            "components": comps, "result": result}


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
