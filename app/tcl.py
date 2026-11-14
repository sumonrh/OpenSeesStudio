"""Minimal OpenSees Tcl reader and runner.

The importer understands the model commands written by
:func:`app.opsgen.export_tcl` (nodes, supports, materials, sections, elements
and load patterns) plus the usual OpenSees analysis commands for the scripting
console.  It is not a general Tcl interpreter: loops, procedures and ``expr``
are not evaluated.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from typing import Dict, Iterable, List, Tuple

from .model import (Element, ElementLoad, LoadCase, Material, NodalLoad,
                    Node, Project, Section)


class Braced(str):
    """A ``{...}`` Tcl word, kept distinct so patterns can be expanded."""


def _braced(text: str, i: int) -> Tuple[Braced, int]:
    depth = 1
    i += 1
    out: List[str] = []
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            out.append(ch)
            out.append(text[i + 1])
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return Braced("".join(out)), i + 1
        out.append(ch)
        i += 1
    raise ValueError("unbalanced braces in Tcl script")


def _quoted(text: str, i: int) -> Tuple[str, int]:
    i += 1
    out: List[str] = []
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
            i += 2
            continue
        if ch == '"':
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    raise ValueError("unterminated quoted string in Tcl script")


def tokenize(text: str) -> Iterable[Tuple[str, List]]:
    """Yield ``(command, arguments)`` pairs from a Tcl script."""
    text = text.replace("\\\r\n", " ").replace("\\\n", " ")
    i, n = 0, len(text)
    words: List = []
    while i < n:
        ch = text[i]
        if ch in " \t\r":
            i += 1
            continue
        if ch in "\n;":
            if words:
                yield str(words[0]), words[1:]
                words = []
            i += 1
            continue
        if ch == "#" and not words:
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch == "{":
            word, i = _braced(text, i)
        elif ch == '"':
            word, i = _quoted(text, i)
        else:
            j = i
            while j < n and text[j] not in " \t\r\n;":
                j += 1
            word = text[i:j]
            i = j
        words.append(word)
    if words:
        yield str(words[0]), words[1:]


def _num(value) -> float:
    if isinstance(value, Braced):
        return 0.0
    return float(value)


def _int(value) -> int:
    if isinstance(value, Braced):
        return 0
    return int(float(value))


class _Importer:
    def __init__(self) -> None:
        self.p = Project()
        self.p.title = "Imported Tcl"
        self.transforms: Dict[int, List[float]] = {}
        self.plate_sections: Dict[int, Tuple[int, float]] = {}
        self._material_by_E: Dict[float, int] = {}
        self.default_case = ""
        self.warnings: List[str] = []

    # ------------------------------------------------------------------ bits
    def _material_tag(self, E: float, nu: float = 0.3) -> int:
        key = round(E, 9)
        if key in self._material_by_E:
            return self._material_by_E[key]
        tag = self.p.next_material()
        self.p.materials[tag] = Material(tag, f"Imported E={E:g}", "Elastic",
                                         E=E, nu=nu)
        self._material_by_E[key] = tag
        return tag

    def _section(self, A: float, Iy: float, Iz: float, J: float) -> int:
        for sec in self.p.sections.values():
            if (abs(sec.A - A) < 1e-9 and abs(sec.Iy - Iy) < 1e-9
                    and abs(sec.Iz - Iz) < 1e-9 and abs(sec.J - J) < 1e-9):
                return sec.tag
        tag = self.p.next_section()
        self.p.sections[tag] = Section(tag, f"Imported A={A:g}", "User",
                                       A=A, Iy=Iy, Iz=Iz, J=J)
        return tag

    def _case(self, name: str) -> str:
        if name not in self.p.cases:
            self.p.cases[name] = LoadCase(name, "Other")
        return name

    # -------------------------------------------------------------- commands
    def command(self, cmd: str, args: List) -> None:
        name = cmd.lower()
        if name in ("wipe", "model", "timeseries", "geomtransf", "ndmaterial",
                    "test", "system", "numberer", "constraints", "algorithm",
                    "integrator", "analysis", "analyze", "eigen", "recorder",
                    "printmodel", "puts"):
            if name == "geomtransf" and len(args) >= 5:
                self.transforms[_int(args[1])] = [_num(args[2]), _num(args[3]),
                                                  _num(args[4])]
            if name == "ndmaterial" and len(args) >= 5:
                tag = _int(args[1])
                self.p.materials[tag] = Material(
                    tag, f"Imported {args[0]}", "Elastic", E=_num(args[2]),
                    nu=_num(args[3]), rho=_num(args[4]))
            return
        if name == "uniaxialmaterial":
            self._uniaxial(args)
            return
        if name == "section":
            if args and str(args[0]).lower() == "platefiber" and len(args) >= 4:
                self.plate_sections[_int(args[1])] = (_int(args[2]), _num(args[3]))
            return
        if name == "node" and len(args) >= 4:
            tag = _int(args[0])
            self.p.nodes[tag] = Node(tag, _num(args[1]), _num(args[2]),
                                     _num(args[3]))
            return
        if name == "fix" and len(args) >= 7:
            node = self.p.nodes.get(_int(args[0]))
            if node is not None:
                node.support = [bool(_int(v)) for v in args[1:7]]
            return
        if name == "element":
            self._element(args)
            return
        if name == "pattern":
            self._pattern(args)
            return
        if name in ("load", "eleload"):
            self._load(name, args, self.default_case or "Imported")
            return
        self.warnings.append(f"ignored command: {cmd}")

    def _uniaxial(self, args: List) -> None:
        if len(args) < 3:
            return
        kind = str(args[0])
        tag = _int(args[1])
        E = 200.0
        nu = 0.3
        if kind == "Elastic" and len(args) >= 3:
            E = _num(args[2])
        elif kind in ("Steel01", "Steel02") and len(args) >= 4:
            E = _num(args[3])
        elif kind == "ElasticPP" and len(args) >= 3:
            E = _num(args[2])
        self.p.materials[tag] = Material(tag, f"{kind} {tag}", "Elastic",
                                         E=E, nu=nu)

    def _element(self, args: List) -> None:
        if len(args) < 3:
            return
        kind = str(args[0])
        tag = _int(args[1])
        num = [_num(v) for v in args[1:]]
        try:
            if kind == "elasticBeamColumn" and len(args) >= 11:
                _t, i, j, A, E, G, J, Iy, Iz, transf = num[:10]
                mat = self._material_tag(E, max(0.0, E / (2.0 * max(G, 1e-9)) - 1.0))
                sec = self._section(A, Iy, Iz, J)
                self.p.elements[tag] = Element(
                    tag, "beam", [_int(i), _int(j)], mat, sec,
                    self.transforms.get(_int(transf)))
            elif kind == "truss" and len(args) >= 5:
                _t, i, j, A, mat = num[:5]
                sec = self._section(A, 1e-6, 1e-6, 1e-6)
                self.p.elements[tag] = Element(tag, "truss",
                                               [_int(i), _int(j)],
                                               _int(mat), sec, None)
            elif kind == "ShellMITC4" and len(args) >= 7:
                nodes = [_int(v) for v in args[2:6]]
                mat, thickness = self.plate_sections.get(
                    _int(args[6]), (self.p.next_material(), 100.0))
                if mat not in self.p.materials:
                    self.p.materials[mat] = Material(mat, "Imported shell", "Elastic")
                sec = self._section(1.0, 1.0, 1.0, 1.0)
                self.p.elements[tag] = Element(tag, "shell", nodes, mat, sec,
                                               None, thickness)
            else:
                self.warnings.append(f"unsupported element: {kind}")
        except (ValueError, IndexError):
            self.warnings.append(f"could not read element: {kind}")

    def _pattern(self, args: List) -> None:
        if len(args) < 3:
            return
        name = self._case(f"Pattern {_int(args[1])}")
        self.default_case = name
        body = next((a for a in args[3:] if isinstance(a, Braced)), None)
        if body is not None:
            for cmd, sub in tokenize(str(body)):
                if cmd.lower() in ("load", "eleload"):
                    self._load(cmd.lower(), sub, name)
                elif cmd.lower() == "eleloadrange":
                    self.warnings.append("unsupported command: eleLoadRange")
        self.default_case = ""

    def _load(self, kind: str, args: List, case: str) -> None:
        case = self._case(case or "Imported")
        tag = self.p.next_load()
        if kind == "load" and len(args) >= 7:
            node = _int(args[0])
            values = [_num(v) for v in args[1:7]]
            if node in self.p.nodes:
                self.p.nodal_loads.append(NodalLoad(tag, node, case, values))
            return
        if kind != "eleload":
            return
        elems: List[int] = []
        load_type = ""
        values: List[float] = []
        i = 0
        while i < len(args):
            token = str(args[i]).lower()
            if token == "-ele" and i + 1 < len(args):
                i += 1
                while i < len(args) and not str(args[i]).startswith("-"):
                    elems.append(_int(args[i]))
                    i += 1
                continue
            if token == "-type" and i + 1 < len(args):
                load_type = str(args[i + 1]).lower()
                i += 2
                continue
            try:
                values.append(_num(args[i]))
            except (TypeError, ValueError):
                pass
            i += 1
        for elem in elems:
            if elem not in self.p.elements:
                continue
            if "uniform" in load_type and len(values) >= 2:
                for value, direction in ((values[0], "local-y"),
                                         (values[1], "local-z")):
                    if abs(value) > 1e-15:
                        self.p.elem_loads.append(ElementLoad(
                            self.p.next_load(), elem, case, "uniform",
                            direction, value))
            elif "point" in load_type and len(values) >= 3:
                py, pz, position = values[:3]
                for value, direction in ((py, "local-y"), (pz, "local-z")):
                    if abs(value) > 1e-15:
                        self.p.elem_loads.append(ElementLoad(
                            self.p.next_load(), elem, case, "point",
                            direction, value, 0.0, position))


def import_text(text: str, title: str = "Imported Tcl") -> Tuple[Project, dict]:
    importer = _Importer()
    importer.p.title = title
    for cmd, args in tokenize(text):
        importer.command(cmd, args)
    info = {
        "nodes": len(importer.p.nodes),
        "elements": len(importer.p.elements),
        "materials": len(importer.p.materials),
        "sections": len(importer.p.sections),
        "loads": len(importer.p.nodal_loads) + len(importer.p.elem_loads),
        "warnings": importer.warnings[:20],
    }
    return importer.p, info


# --------------------------------------------------------------------------- #
# console runners
# --------------------------------------------------------------------------- #
def run_python(code: str) -> dict:
    """Execute Python with OpenSeesPy as ``ops`` and return captured output."""
    from openseespy import opensees as ops

    buffer = io.StringIO()
    namespace = {"ops": ops, "opensees": ops, "__name__": "__console__"}
    with redirect_stdout(buffer):
        exec(compile(code, "<script console>", "exec"), namespace)
    return {"output": buffer.getvalue(), "ok": True}


def run_tcl(code: str) -> dict:
    """Execute the supported Tcl command subset in the OpenSees domain."""
    from openseespy import opensees as ops

    buffer = io.StringIO()
    executed = 0
    results: List[str] = []

    def convert(value):
        if isinstance(value, Braced):
            return str(value)
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return str(value)

    def dispatch(cmd: str, args: List) -> None:
        nonlocal executed
        name = cmd.lower()
        if name == "puts":
            print(" ".join(str(a) for a in args))
            return
        if name == "pattern":
            plain = [a for a in args if not isinstance(a, Braced)]
            ops.pattern(*[convert(a) for a in plain])
            executed += 1
            body = next((a for a in args if isinstance(a, Braced)), None)
            if body is not None:
                for sub_cmd, sub_args in tokenize(str(body)):
                    dispatch(sub_cmd, sub_args)
            return
        fn = getattr(ops, cmd, None)
        if fn is None or not callable(fn):
            raise ValueError(f"unsupported Tcl command: {cmd}")
        with redirect_stdout(buffer):
            value = fn(*[convert(a) for a in args])
        if value is not None:
            results.append(f"{cmd}: {value}")
        executed += 1

    with redirect_stdout(buffer):
        for cmd, args in tokenize(code):
            dispatch(cmd, args)

    output = buffer.getvalue()
    if results:
        output += ("\n" if output else "") + "\n".join(results)
    return {"output": output, "ok": True, "commands": executed}
