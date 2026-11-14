"""Capture an OpenSees model built by a script and convert it to a Project.

The Script Console runs standard OpenSeesPy/Tcl commands.  While a script runs,
this recorder wraps the model-building commands, keeps their arguments, and
later converts the captured domain into OpenSees Studio's kN-mm model.  Units
are chosen in the console because OpenSees itself is unit-agnostic.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .model import (Element, ElementLoad, LoadCase, Material, NodalLoad, Node,
                    Project, Section)

# Multipliers from the script unit system to Studio's kN, mm, tonne, s.
UNIT_PRESETS = {
    "m": {"length": 1000.0, "area": 1.0e6, "inertia": 1.0e12,
          "force": 1.0, "moment": 1000.0, "dist": 1.0e-3,
          "stress": 1.0e-6, "density": 1.0e-9},
    "mm": {"length": 1.0, "area": 1.0, "inertia": 1.0,
           "force": 1.0, "moment": 1.0, "dist": 1.0,
           "stress": 1.0, "density": 1.0},
}

UNIT_LABELS = {
    "m": "m  (forces kN, stress kN/m², density t/m³)",
    "mm": "mm (forces kN, stress kN/mm², density t/mm³)",
}

_RECORDED = ("wipe", "model", "node", "fix", "element", "uniaxialMaterial",
             "nDMaterial", "section", "geomTransf", "pattern", "load",
             "eleLoad")


class ScriptModelRecorder:
    """Record model-building commands and build a Studio project from them."""

    def __init__(self, units: str = "m") -> None:
        self.units = units if units in UNIT_PRESETS else "m"
        self.factors = UNIT_PRESETS[self.units]
        self._patched: List[Tuple[object, str, object]] = []
        self.reset()

    # ------------------------------------------------------------------ data
    def reset(self) -> None:
        self.ndm = 3
        self.ndf = 6
        self.nodes: Dict[int, Tuple[float, float, float]] = {}
        self.fixes: Dict[int, List[bool]] = {}
        self.materials: Dict[int, dict] = {}
        self.sections: Dict[int, dict] = {}
        self.transforms: Dict[int, List[float]] = {}
        self.elements: List[dict] = []
        self.nodal_loads: List[dict] = []
        self.elem_loads: List[dict] = []
        self.case = "Imported script"
        self.cases = {self.case}
        self.warnings: List[str] = []

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def element_count(self) -> int:
        return len(self.elements)

    # -------------------------------------------------------------- recording
    def attach(self, ops) -> None:
        """Patch model-building functions on the OpenSees module."""
        if self._patched:
            return
        for name in _RECORDED:
            original = getattr(ops, name, None)
            if original is None:
                continue

            def make(orig, command):
                def wrapper(*args, **kwargs):
                    self.record(command, args)
                    return orig(*args, **kwargs)
                return wrapper

            setattr(ops, name, make(original, name))
            self._patched.append((ops, name, original))

    def detach(self) -> None:
        for ops, name, original in self._patched:
            setattr(ops, name, original)
        self._patched.clear()

    def record(self, command: str, args) -> None:
        handler = getattr(self, f"_cmd_{command}", None)
        if handler is None:
            return
        try:
            handler(*args)
        except Exception as exc:  # noqa: BLE001 - never break the analysis
            self.warnings.append(f"{command}: {exc}")

    # --------------------------------------------------------------- commands
    def _cmd_wipe(self) -> None:
        self.reset()

    def _cmd_model(self, *args) -> None:
        self.reset()
        for i, value in enumerate(args[:-1]):
            if str(value) == "-ndm":
                self.ndm = int(args[i + 1])
            elif str(value) == "-ndf":
                self.ndf = int(args[i + 1])

    def _cmd_node(self, tag, *coords) -> None:
        L = self.factors["length"]
        values = [float(v) * L for v in coords]
        if self.ndm == 2:
            x, y = values[0], values[1] if len(values) > 1 else 0.0
            self.nodes[int(tag)] = (x, 0.0, y)
        else:
            x = values[0] if values else 0.0
            y = values[1] if len(values) > 1 else 0.0
            z = values[2] if len(values) > 2 else 0.0
            self.nodes[int(tag)] = (x, y, z)

    def _cmd_fix(self, tag, *flags) -> None:
        self.fixes[int(tag)] = [bool(int(v)) for v in flags]

    def _cmd_uniaxialMaterial(self, kind, tag, *params) -> None:
        self.materials[int(tag)] = {"source": "uniaxial", "kind": str(kind),
                                    "params": [float(v) for v in params]}

    def _cmd_nDMaterial(self, kind, tag, *params) -> None:
        self.materials[int(tag)] = {"source": "nd", "kind": str(kind),
                                    "params": [float(v) for v in params]}

    def _cmd_section(self, kind, tag, *params) -> None:
        self.sections[int(tag)] = {"kind": str(kind),
                                   "params": [float(v) for v in params]}

    def _cmd_geomTransf(self, kind, tag, *vec) -> None:
        self.transforms[int(tag)] = [float(v) for v in vec]

    def _cmd_element(self, kind, tag, *args) -> None:
        values = [float(tag)]
        for value in args:
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                values.append(value)
        self.elements.append({"kind": str(kind), "args": values})

    def _cmd_pattern(self, kind, tag, *args) -> None:
        self.case = f"Pattern {int(tag)}"
        self.cases.add(self.case)

    def _cmd_load(self, node, *values) -> None:
        self.nodal_loads.append({"node": int(node),
                                 "values": [float(v) for v in values],
                                 "case": self.case})

    def _cmd_eleLoad(self, *args) -> None:
        self.elem_loads.append({"args": list(args), "case": self.case})

    # ---------------------------------------------------------------- convert
    def _material(self, p: Project, tag: int, rec: dict) -> int:
        if tag in p.materials:
            return tag
        E, nu, rho, fy = 200.0, 0.3, 0.0, 0.235
        params = rec["params"]
        kind = rec["kind"].lower()
        if rec["source"] == "nd":
            if kind == "elasticisotropic" and len(params) >= 2:
                E, nu = params[0], params[1]
                if len(params) >= 3:
                    rho = params[2]
        elif kind == "elastic" and params:
            E = params[0]
        elif kind in ("steel01", "steel02") and len(params) >= 3:
            fy, E = params[0], params[1]
        elif kind == "elasticpp" and params:
            E = params[0]
        elif kind == "concrete02" and params:
            fy = abs(params[0])
        material = Material(tag, f"{rec['kind']} {tag}", "Elastic",
                            E=E * self.factors["stress"], nu=nu,
                            rho=rho * self.factors["density"],
                            fy=fy * self.factors["stress"])
        p.materials[tag] = material
        return tag

    def _material_for_E(self, p: Project, E: float) -> int:
        for tag, mat in p.materials.items():
            if abs(mat.E - E) < 1e-9:
                return tag
        tag = p.next_material()
        p.materials[tag] = Material(tag, f"Script E={E:g}", "Elastic", E=E)
        return tag

    def _section_for(self, p: Project, A: float, Iy: float, Iz: float,
                     J: float) -> int:
        for sec in p.sections.values():
            if (abs(sec.A - A) < 1e-9 and abs(sec.Iy - Iy) < 1e-9
                    and abs(sec.Iz - Iz) < 1e-9 and abs(sec.J - J) < 1e-9):
                return sec.tag
        tag = p.next_section()
        p.sections[tag] = Section(tag, f"Script A={A:g}", "User",
                                  A=A, Iy=Iy, Iz=Iz, J=J)
        return tag

    def _support(self, flags: List[bool]) -> List[bool]:
        if self.ndf == 6:
            out = (flags + [False] * 6)[:6]
            return out
        if self.ndf == 3:
            ux = flags[0] if len(flags) > 0 else False
            uy = flags[1] if len(flags) > 1 else False
            rz = flags[2] if len(flags) > 2 else False
            # The 2D model is embedded in Studio's 3D space; restrain the
            # out-of-plane translation and rotations at supports so the
            # global out-of-plane rigid modes cannot occur.
            return [ux, True, uy, True, rz, True]
        ux = flags[0] if len(flags) > 0 else False
        uy = flags[1] if len(flags) > 1 else False
        return [ux, False, uy, False, False, False]

    def _nodal_values(self, values: List[float]) -> List[float]:
        f, m = self.factors["force"], self.factors["moment"]
        if self.ndf == 6:
            vals = (values + [0.0] * 6)[:6]
            return [vals[0] * f, vals[1] * f, vals[2] * f,
                    vals[3] * m, vals[4] * m, vals[5] * m]
        if self.ndf == 3:
            vals = (values + [0.0] * 3)[:3]
            return [vals[0] * f, 0.0, vals[1] * f, 0.0, vals[2] * m, 0.0]
        vals = (values + [0.0] * 2)[:2]
        return [vals[0] * f, 0.0, vals[1] * f, 0.0, 0.0, 0.0]

    def _parse_eleload(self, args: List) -> Tuple[List[int], str, List[float]]:
        elems: List[int] = []
        kind = ""
        values: List[float] = []
        i = 0
        while i < len(args):
            token = str(args[i]).lower()
            if token in ("-ele", "-elems") and i + 1 < len(args):
                i += 1
                while i < len(args) and not str(args[i]).startswith("-"):
                    elems.append(int(float(args[i])))
                    i += 1
                continue
            if token == "-type" and i + 1 < len(args):
                kind = str(args[i + 1]).lower()
                i += 2
                continue
            try:
                values.append(float(args[i]))
            except (TypeError, ValueError):
                pass
            i += 1
        return elems, kind, values

    def build(self, title: str = "Script model") -> Project:
        """Convert the captured commands into a Studio project."""
        p = Project()
        p.title = title
        for tag, rec in sorted(self.materials.items()):
            self._material(p, tag, rec)

        for tag, xyz in sorted(self.nodes.items()):
            p.nodes[tag] = Node(tag, xyz[0], xyz[1], xyz[2])
        for tag, flags in self.fixes.items():
            if tag in p.nodes:
                p.nodes[tag].support = self._support(flags)

        F = self.factors
        for rec in self.elements:
            kind = rec["kind"].lower()
            a = rec["args"]
            try:
                tag = int(a[0])
                nodes = [int(a[1]), int(a[2])]
            except (IndexError, TypeError, ValueError):
                self.warnings.append(f"element {rec['kind']}: bad arguments")
                continue
            if any(t not in p.nodes for t in nodes):
                self.warnings.append(f"element {tag}: missing nodes")
                continue
            if kind == "elasticbeamcolumn":
                if len(a) == 7:          # 2D: tag i j A E Iz transf
                    A, E, Iz = a[3] * F["area"], a[4], a[5] * F["inertia"]
                    Iy, J = Iz, 2.0 * Iz
                    transf = int(a[6])
                    vec = self.transforms.get(transf) or None
                    sec = self._section_for(p, A, Iy, Iz, J)
                    mat = self._material_for_E(p, E * F["stress"])
                elif len(a) >= 10:       # 3D
                    A = a[3] * F["area"]
                    E = a[4]
                    J = a[6] * F["inertia"]
                    Iy = a[7] * F["inertia"]
                    Iz = a[8] * F["inertia"]
                    transf = int(a[9])
                    vec = self.transforms.get(transf) or None
                    sec = self._section_for(p, A, Iy, Iz, J)
                    mat = self._material_for_E(p, E * F["stress"])
                else:
                    self.warnings.append(f"element {tag}: unsupported beam signature")
                    continue
                p.elements[tag] = Element(tag, "beam", nodes, mat, sec, vec)
            elif kind == "truss":
                A = a[3] * F["area"]
                mat = int(a[4])
                if mat not in p.materials:
                    p.materials[mat] = Material(mat, f"Truss material {mat}")
                sec = self._section_for(p, A, 1e-6, 1e-6, 1e-6)
                p.elements[tag] = Element(tag, "truss", nodes, mat, sec, None)
            elif kind == "shellmitc4":
                if len(a) < 6:
                    continue
                shell_nodes = [int(v) for v in a[1:5]]
                sec_tag = int(a[5])
                record = self.sections.get(sec_tag, {})
                params = record.get("params", [])
                thickness = (params[1] * F["length"]
                             if record.get("kind", "").lower() == "platefiber"
                             and len(params) > 1 else 100.0)
                mat_tag = int(params[0]) if len(params) > 0 else 1
                if mat_tag not in p.materials:
                    p.materials[mat_tag] = Material(mat_tag, "Shell material")
                sec = self._section_for(p, 1.0, 1.0, 1.0, 1.0)
                p.elements[tag] = Element(tag, "shell", shell_nodes, mat_tag,
                                          sec, None, thickness)
            else:
                self.warnings.append(f"unsupported element type: {rec['kind']}")

        cases = set(self.cases)
        for item in self.nodal_loads:
            if item["node"] not in p.nodes:
                continue
            case = item["case"]
            cases.add(case)
            p.nodal_loads.append(NodalLoad(
                p.next_load(), item["node"], case,
                self._nodal_values(item["values"])))
        for item in self.elem_loads:
            elems, kind, values = self._parse_eleload(item["args"])
            case = item["case"]
            cases.add(case)
            for elem in elems:
                if elem not in p.elements:
                    continue
                if "uniform" in kind and values:
                    wy = values[0] * F["dist"]
                    # A 2D beamUniform acts in the member's in-plane local y;
                    # after mapping X-Z into Studio's 3D space that is local z.
                    direction = "local-z" if self.ndf == 3 else "local-y"
                    p.elem_loads.append(ElementLoad(
                        p.next_load(), elem, case, "uniform", direction, wy))
                    if self.ndf >= 6 and len(values) > 1 and abs(values[1]) > 1e-15:
                        p.elem_loads.append(ElementLoad(
                            p.next_load(), elem, case, "uniform", "local-z",
                            values[1] * F["dist"]))
                elif "point" in kind and len(values) >= 3:
                    py, pz, pos = values[0], values[1], values[2]
                    direction = "local-z" if self.ndf == 3 else "local-y"
                    p.elem_loads.append(ElementLoad(
                        p.next_load(), elem, case, "point", direction,
                        py * F["force"], 0.0, pos))
                    if self.ndf >= 6 and abs(pz) > 1e-15:
                        p.elem_loads.append(ElementLoad(
                            p.next_load(), elem, case, "point", "local-z",
                            pz * F["force"], 0.0, pos))
                else:
                    self.warnings.append(
                        f"unsupported element load on {elem}: {kind}")

        for case in cases:
            p.cases.setdefault(case, LoadCase(case, "Other"))
        if "DL" in p.cases:
            p.self_weight.setdefault("DL", 1.0)
        return p
