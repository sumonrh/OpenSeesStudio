"""Solver-bridge verification against closed-form solutions."""
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.model import (Project, Element, Node, NodalLoad, LoadCase, Section,
                       HingeDefinition, TimeHistoryCase, GroundMotionRecord,
                       ResponseSpectrumCase, Lane, default_project)
from app import opsgen
from app import groundmotion

FAILS = []


def check(name, got, want, rtol=1e-6):
    ok = abs(got - want) <= rtol * max(abs(want), 1e-9)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: got {got:.6g}, want {want:.6g}")
    if not ok:
        FAILS.append(name)


def cantilever(load_dir, area_dir):
    p = default_project()
    p.materials[1].E = 200.0
    p.materials[1].nu = 0.3
    p.materials[1].rho = 7.85e-9
    s = p.sections[1]
    s.shape, s.b, s.h = "Rectangle", 300.0, 600.0
    s.compute()
    p.nodes[1] = Node(1, 0, 0, 0, support=[True] * 6)
    p.nodes[2] = Node(2, 4000, 0, 0)
    p.elements[1] = Element(1, "beam", [1, 2], 1, 1, vecxz=[0, 0, 1])
    p.cases["DL"] = LoadCase("DL")
    p.elements[1].vecxz = [0, 0, 1]
    v = [0.0] * 6
    v[1 if load_dir == "Y" else 2] = 10.0
    p.nodal_loads.append(NodalLoad(1, 2, "DL", v))
    r = opsgen.run_static(p, "DL")
    d = r.displacements[2]
    E, I = 200.0, (s.Iy if area_dir == "strong" else s.Iz)
    want = 10.0 * 4000 ** 3 / (3 * E * I)
    got = d[1] if load_dir == "Y" else d[2]
    check(f"cantilever {load_dir} (I={'Iy' if area_dir=='strong' else 'Iz'})", got, want)
    f = r.element_forces[1]
    print("   localForce:", [round(x, 3) for x in f])
    return f, want


print("== static: cantilever ==")
fz, dz = cantilever("Z", "strong")
fy, dy = cantilever("Y", "weak")
check("base moment My under Z load", abs(fz[4]), 10.0 * 4000, 1e-6)
check("base moment Mz under Y load", abs(fy[5]), 10.0 * 4000, 1e-6)

print("== beam diagrams ==")
from app.beamdiagram import beam_load_records, diagram_series
from app.model import ElementLoad

p = default_project()
p.materials[1].E = 200.0
p.materials[1].rho = 7.85e-9
s = p.sections[1]
s.shape, s.b, s.h = "Rectangle", 300.0, 600.0
s.compute()
p.nodes[1] = Node(1, 0, 0, 0, support=[True] * 6)
p.nodes[2] = Node(2, 4000, 0, 0)
p.elements[1] = Element(1, "beam", [1, 2], 1, 1, vecxz=[0, 0, 1])
p.cases["DL"] = LoadCase("DL")
p.elem_loads.append(ElementLoad(1, 1, "DL", "uniform", "local-y", -0.01))
r = opsgen.run_static(p, "DL")
loads = beam_load_records(p, "DL")
vy = diagram_series(p, r, p.elements[1], "DL", "Vy", loads.get(1, []))
mz = diagram_series(p, r, p.elements[1], "DL", "Mz", loads.get(1, []))
check("diagram shear at fixed end", vy[0][1], -40.0, 1e-9)
check("diagram shear at free end", vy[-1][1], 0.0, 1e-9)
check("diagram moment at fixed end", mz[0][1], -0.01 * 4000 ** 2 / 2, 1e-9)
check("diagram moment at free end", mz[-1][1], 0.0, 1e-9)

print("== beam diagram My sign ==")
p = default_project()
p.materials[1].E = 200.0
s = p.sections[1]
s.shape, s.b, s.h = "Rectangle", 300.0, 600.0
s.compute()
p.nodes[1] = Node(1, 0, 0, 0,
                 support=[True, True, True, True, False, True])
p.nodes[2] = Node(2, 4000, 0, 0)
p.nodes[3] = Node(3, 8000, 0, 0,
                 support=[True, True, True, True, False, True])
p.elements[1] = Element(1, "beam", [1, 2], 1, 1, vecxz=[0, 0, 1])
p.elements[2] = Element(2, "beam", [2, 3], 1, 1, vecxz=[0, 0, 1])
p.cases["DL"] = LoadCase("DL")
p.nodal_loads.append(NodalLoad(1, 2, "DL", [0.0, 0.0, -10.0, 0.0, 0.0, 0.0]))
r = opsgen.run_static(p, "DL")
loads = beam_load_records(p, "DL")
my = diagram_series(p, r, p.elements[1], "DL", "My", loads.get(1, []))
check("diagram My at midspan (sagging positive)", my[-1][1], 20000.0)

print("== point load location ==")
for pos in (0.25, 0.75):
    p = default_project()
    p.materials[1].E = 200.0
    s = p.sections[1]
    s.shape, s.b, s.h = "Rectangle", 300.0, 600.0
    s.compute()
    p.nodes[1] = Node(1, 0, 0, 0, support=[True] * 6)
    p.nodes[2] = Node(2, 4000, 0, 0)
    p.elements[1] = Element(1, "beam", [1, 2], 1, 1, vecxz=[0, 0, 1])
    p.cases["DL"] = LoadCase("DL")
    p.elem_loads.append(ElementLoad(1, 1, "DL", "point", "local-y", -10.0,
                                    0.0, pos))
    r = opsgen.run_static(p, "DL")
    a = pos * 4000.0
    want = -10.0 * a ** 2 * (3 * 4000.0 - a) / (6 * 200.0 * s.Iz)
    check(f"point load at {pos:.2f}L deflection", r.displacements[2][1], want)
    loads = beam_load_records(p, "DL")
    mz = diagram_series(p, r, p.elements[1], "DL", "Mz", loads.get(1, []))
    check(f"point load at {pos:.2f}L base moment", mz[0][1], -10.0 * a)

print("== element subdivision ==")
p = default_project()
p.nodes[1] = Node(1, 0, 0, 0)
p.nodes[2] = Node(2, 1000, 0, 0)
p.elements[1] = Element(1, "beam", [1, 2], 1, 1, vecxz=[0, 0, 1])
p.elem_loads = [
    ElementLoad(1, 1, "DL", "uniform", "Global Z", -0.01, 0.0, 0.5),
    ElementLoad(2, 1, "DL", "point", "Global Z", -5.0, 0.0, 0.25),
]
sub_nodes, sub_elems = p.subdivide_elements([1], 4)
check("subdivision intermediate nodes", len(sub_nodes), 3)
check("subdivision new elements", len(sub_elems), 4)
check("subdivision removes original", 1 if 1 not in p.elements else 0, 1)
for i, node_tag in enumerate(sub_nodes):
    check(f"intermediate node {i + 1} position", p.nodes[node_tag].x, 250.0 * (i + 1))
check("subdivision preserves total length",
      sum(p.element_length(p.elements[t]) for t in sub_elems), 1000.0)
uniform = [l for l in p.elem_loads if l.kind == "uniform"]
point = [l for l in p.elem_loads if l.kind == "point"]
check("subdivision replicates uniform load", len(uniform), 4)
check("subdivision keeps uniform intensity", sum(l.value for l in uniform), -0.04)
check("subdivision keeps one point load", len(point), 1)
check("subdivision moves point load to its segment",
      1 if point and point[0].elem == sub_elems[1] else 0, 1)
check("subdivision converts point-load position",
      point[0].position if point else -1.0, 0.0)

for label, load in (
        ("uniform", ElementLoad(1, 1, "DL", "uniform", "local-y", -0.01)),
        ("point", ElementLoad(1, 1, "DL", "point", "local-y", -10.0, 0.0, 0.25))):
    p = default_project()
    p.materials[1].E = 200.0
    p.nodes[1] = Node(1, 0, 0, 0, support=[True] * 6)
    p.nodes[2] = Node(2, 4000, 0, 0)
    p.elements[1] = Element(1, "beam", [1, 2], 1, 1, vecxz=[0, 0, 1])
    p.cases["DL"] = LoadCase("DL")
    p.elem_loads = [load]
    before = opsgen.run_static(p, "DL")
    p.subdivide_elements([1], 5)
    after = opsgen.run_static(p, "DL")
    check(f"subdivision preserves {label}-load displacement",
          after.displacements[2][1], before.displacements[2][1], 1e-6)

print("== pushover with lumped plastic hinges ==")
p = default_project()
p.nodes[1] = Node(1, 0, 0, 0, support=[True] * 6)
p.nodes[2] = Node(2, 0, 0, 1000)
p.elements[1] = Element(1, "beam", [1, 2], 1, 2, vecxz=None)
p.cases["LAT"] = LoadCase("LAT")
p.nodal_loads.append(NodalLoad(1, 2, "LAT", [10.0, 0, 0, 0, 0, 0]))
p.hinge_defs[1] = HingeDefinition(
    1, "Hinge 1", "Hysteretic", "Hysteretic", 0.10,
    {"fy": 0.235, "b": 0.02, "ductility": 10.0, "pinchX": 0.8,
     "pinchY": 0.8, "damage1": 0.02, "damage2": 0.0, "beta": 0.4})
p.hinge_assignments[1] = 1
cfg = {"gravity_case": "", "lateral_case": "LAT", "control_node": 2,
       "control_dof": 1, "target_displacement": 20.0, "steps": 5}
push = opsgen.run_pushover(p, cfg)
check("pushover step count", len(push.steps), 6)
check("pushover target displacement", abs(push.steps[-1].displacement), 20.0)
check("pushover base shear increases",
      1 if push.steps[-1].base_shear > push.steps[0].base_shear + 1.0 else 0, 1)
check("pushover hinge rotation develops",
      1 if push.max_hinge_rotation(push.steps[-1]) > 0.0 else 0, 1)
check("only assigned hinge is used", len(push.hinge_yield), 1)
check("pushover hinges yield",
      sum(1 for tag, moments in push.steps[-1].hinge_moments.items()
          if max(moments) > 0.98 * push.hinge_yield.get(tag, 1e99)), 1)
check("pushover step state is reusable",
      1 if push.static_at(-1).displacements.get(2) else 0, 1)
cloned = p.clone()
check("hinge assignment persists",
      1 if cloned.hinge_defs.get(1)
      and cloned.hinge_defs[1].material == "Hysteretic"
      and cloned.hinge_assignments.get(1) == 1 else 0, 1)

p2 = p.clone()
p2.hinge_assignments.clear()
try:
    opsgen.run_pushover(p2, cfg)
    check("pushover rejects unassigned model", 0, 1)
except ValueError as exc:
    check("pushover rejects unassigned model",
          1 if "No hinges" in str(exc) else 0, 1)

print("== OpenSees hinge material catalogue ==")
from app.hinge_catalog import MATERIALS, defaults as hinge_defaults, build_command
import openseespy.opensees as ops
ops.wipe()
ops.model("BasicBuilder", "-ndm", 3, "-ndf", 6)
for tag, (key, spec) in enumerate(MATERIALS.items(), start=1):
    if spec.kind != "fiber":
        continue
    command, args = build_command(key, tag, hinge_defaults(key), 200.0)
    try:
        ops.uniaxialMaterial(command, tag, *args)
        check(f"{key} material command", 1, 1)
    except Exception as exc:
        check(f"{key} material command", 0, 1)
        print("   ", exc)

print("== custom section shapes ==")
s = Section(1, "Hex", "Hexagon", d=400.0)
s.compute()
check("hexagon area", s.A, 3.0 * math.sqrt(3.0) / 2.0 * 200.0 ** 2)
s = Section(2, "Oct", "Octagon", d=400.0)
s.compute()
check("octagon area", s.A, 2.0 * math.sqrt(2.0) * 200.0 ** 2)
s = Section(3, "Angle", "L-Shape", b=150.0, h=150.0, t=12.0)
s.compute()
check("angle area", s.A, 150.0 * 12.0 + 138.0 * 12.0)
check("angle centroid", s.cy, 41.9375, 1e-4)
s = Section(4, "Tee", "T-Shape", b=300.0, h=400.0, tw=12.0, tf=20.0)
s.compute()
check("tee area", s.A, 300.0 * 20.0 + 380.0 * 12.0)
check("tee centroid", s.cz, 303.6364, 1e-4)

print("== static: truss axial ==")
p = default_project()
p.nodes[1] = Node(1, 0, 0, 0, support=[True] * 6)
p.nodes[2] = Node(2, 1000, 0, 0)
p.nodes[2].support = [False, True, True, True, True, True]
p.elements[1] = Element(1, "truss", [1, 2], 1, 1)
p.elements[1].kind = "truss"
p.cases["DL"] = LoadCase("DL")
p.nodal_loads.append(NodalLoad(1, 2, "DL", [50.0, 0, 0, 0, 0, 0]))
r = opsgen.run_static(p, "DL")
check("truss axial force", r.element_forces[1][0], 50.0, 1e-9)
check("truss elongation", r.displacements[2][0],
      50.0 * 1000.0 / (200.0 * p.sections[1].A))
check("truss support reaction", r.reactions[1][0], -50.0, 1e-9)

print("== modal: cantilever frequencies (10 elements) ==")
p = default_project()
p.materials[1].E = 200.0
p.materials[1].rho = 7.85e-9
s = p.sections[1]
s.shape, s.b, s.h = "Rectangle", 300.0, 600.0
s.compute()
nel, L = 10, 4000.0
p.nodes[1] = Node(1, 0, 0, 0, support=[True] * 6)
for i in range(1, nel + 1):
    p.nodes[i + 1] = Node(i + 1, L * i / nel, 0, 0)
for i in range(1, nel + 1):
    p.elements[i] = Element(i, "beam", [i, i + 1], 1, 1, vecxz=[0, 0, 1])
m = 7.85e-9 * s.A
f_weak = (1.875104068711961 ** 2) / (2 * math.pi) * math.sqrt(1000.0 * 200.0 * s.Iz / (m * L ** 4))
f_strong = (1.875104068711961 ** 2) / (2 * math.pi) * math.sqrt(1000.0 * 200.0 * s.Iy / (m * L ** 4))
mr = opsgen.run_modal(p, 6)
check("mode 1 (weak axis) frequency", mr.modes[0].frequency, f_weak, 1.5e-2)
check("mode 2 (strong axis) frequency", mr.modes[1].frequency, f_strong, 1.5e-2)
print("   periods:", [round(x.period, 5) for x in mr.modes])
print("   shape tip mode1:", [round(v, 4) for v in mr.shapes[1][nel + 1]])

print("== load combination scaling ==")
p = default_project()
p.nodes[1] = Node(1, 0, 0, 0, support=[True] * 6)
p.nodes[2] = Node(2, 1000, 0, 0, support=[False, True, True, True, True, True])
p.elements[1] = Element(1, "truss", [1, 2], 1, 1)
p.elements[1].kind = "truss"
p.cases["DL"] = LoadCase("DL")
p.cases["LL"] = LoadCase("LL")
p.nodal_loads.append(NodalLoad(1, 2, "DL", [10.0, 0, 0, 0, 0, 0]))
p.nodal_loads.append(NodalLoad(2, 2, "LL", [10.0, 0, 0, 0, 0, 0]))
from app.model import LoadCombination
p.combos["C"] = LoadCombination("C", [("DL", 1.2), ("LL", 1.6)])
r = opsgen.run_static(p, "C")
check("combination axial", r.element_forces[1][0], 1.2 * 10 + 1.6 * 10, 1e-9)

print("== vertical member with automatic orientation ==")
p = default_project()
p.materials[1].E = 200.0
s = p.sections[1]
s.shape, s.b, s.h = "Rectangle", 300.0, 600.0
s.compute()
p.nodes[1] = Node(1, 0, 0, 0, support=[True] * 6)
p.nodes[2] = Node(2, 0, 0, 1000)
p.elements[1] = Element(1, "beam", [1, 2], 1, 1)      # vecxz = None (auto)
p.cases["DL"] = LoadCase("DL")
p.nodal_loads.append(NodalLoad(1, 2, "DL", [10.0, 0, 0, 0, 0, 0]))
r = opsgen.run_static(p, "DL")
check("vertical column tip displacement", r.displacements[2][0],
      10.0 * 1000 ** 3 / (3 * 200.0 * s.Iy))

print("== tcl export ==")
pt = default_project()
pt.nodes[1] = Node(1, 0, 0, 0, support=[True] * 6)
pt.nodes[2] = Node(2, 1000, 0, 0, support=[False, True, True, True, True, True])
pt.elements[1] = Element(1, "truss", [1, 2], 1, 1)
pt.cases["DL"] = LoadCase("DL")
pt.nodal_loads.append(NodalLoad(1, 2, "DL", [50.0, 0, 0, 0, 0, 0]))
txt = opsgen.export_tcl(pt)
assert "element truss 1 1 2" in txt and "pattern Plain" in txt
print("   tcl lines:", len(txt.splitlines()))

print("== time-history ground-motion readers ==")
tmpdir = Path(tempfile.mkdtemp(prefix="osstudio_gm_"))
two_col = tmpdir / "two_col.txt"
two_col.write_text("0.0 0.0\n0.01 0.10\n0.02 0.0\n", encoding="utf-8")
dt, values, note = groundmotion.read_two_column(two_col)
check("two-column dt", dt, 0.01, 1e-12)
check("two-column point count", len(values), 3, 0)
check("two-column first acceleration", values[1], 0.10, 1e-12)
at2 = tmpdir / "record.at2"
at2.write_text("2 0.01 NPTS, DT\n0.0 1.0\n", encoding="utf-8")
dt2, values2, _ = groundmotion.read_at2(at2)
check("AT2 dt", dt2, 0.01, 1e-12)
check("AT2 point count", len(values2), 2, 0)
sine_case = TimeHistoryCase(source="sine", dt=0.01, n_steps=100,
                            sine_amplitude=0.10, sine_period=1.0)
sine = groundmotion.load_ground_motion(sine_case)
check("sine point count", len(sine.values), 100, 0)
check("sine starts at zero", sine.values[0], 0.0, 1e-12)
check("sine peak amplitude", max(abs(v) for v in sine.values), 0.10, 2e-2)

print("== time-history solver ==")
p = default_project()
p.materials[1].E = 200.0
p.materials[1].rho = 7.85e-9
s = p.sections[1]
s.shape, s.b, s.h = "Rectangle", 300.0, 600.0
s.compute()
p.nodes[1] = Node(1, 0, 0, 0, support=[True] * 6)
p.nodes[2] = Node(2, 0, 0, 3000)
p.elements[1] = Element(1, "beam", [1, 2], 1, 1, vecxz=[1, 0, 0])
p.cases["DL"] = LoadCase("DL")
p.time_history = TimeHistoryCase(source="sine", dt=0.01, n_steps=100,
                                 direction=1, damping_ratio=0.05,
                                 sine_amplitude=0.10, sine_period=1.0)
th = opsgen.run_time_history(p)
check("time-history completed steps", th.n_steps, 100, 0)
check("time-history requested steps", th.n_steps_requested, 100, 0)
check("time-history time rows", len(th.time), 100, 0)
check("time-history node rows", len(th.node_disp[2]), 100, 0)
check("time-history positive peak displacement",
      1 if th.peak_disp > 0.0 else 0, 1, 0)
check("time-history peak displacement bounded",
      1 if th.peak_disp < 10.0 else 0, 1, 0)
print(f"   peak displacement: {th.peak_disp:.6g} mm")
check("time-history peak velocity positive",
      1 if th.peak_vel > 0.0 else 0, 1, 0)
check("time-history peak acceleration positive",
      1 if th.peak_accel > 0.0 else 0, 1, 0)
cloned = Project.from_dict(p.to_dict())
check("time-history case persists", cloned.time_history.n_steps, 100, 0)
check("time-history source persists", 1 if cloned.time_history.source == "sine" else 0, 1, 0)

print("== ground-motion catalog and response spectrum ==")
p.ground_motions[1] = GroundMotionRecord(
    1, "Two-column demo", str(two_col), "two_column", 0.01, 3, 1.0, "test")
catalog_case = TimeHistoryCase(source="catalog", record=1, n_steps=3,
                               direction=1, damping_ratio=0.05)
p.time_history = catalog_case
th_catalog = opsgen.run_time_history(p)
check("catalog time-history steps", th_catalog.n_steps, 3, 0)
check("catalog time-history peak positive",
      1 if th_catalog.peak_disp > 0.0 else 0, 1, 0)
sa = groundmotion.spectrum_from_record(
    p.ground_motions[1], [0.0, 0.2, 0.5, 1.0], 0.05)
check("record spectrum point count", len(sa), 4, 0)
check("record spectrum non-negative",
      1 if all(v >= 0.0 and math.isfinite(v) for v in sa) else 0, 1, 0)
p.response_spectrum = ResponseSpectrumCase(
    name="RS test", direction=1, damping_ratio=0.05, combination="SRSS",
    n_modes=2, periods=[0.0, 0.2, 0.5, 1.0],
    accelerations=[0.40, 0.80, 0.60, 0.30])
rs = opsgen.run_response_spectrum(p)
check("response-spectrum modes", rs.n_modes, 2, 0)
check("response-spectrum peak positive",
      1 if rs.peak_disp > 0.0 else 0, 1, 0)
check("response-spectrum node DOFs", len(rs.node_disp[2]), 6, 0)
check("response-spectrum element forces", len(rs.element_forces[1]), 12, 0)
cloned_rs = Project.from_dict(p.to_dict())
check("ground-motion catalog persists",
      1 if 1 in cloned_rs.ground_motions else 0, 1, 0)
check("response-spectrum case persists",
      len(cloned_rs.response_spectrum.periods), 4, 0)

print("== structure wizard models solve ==")
from app import wizards  # noqa: E402


def wizard_model(kind):
    p = default_project()
    spec = {"kind": kind, "mat": 1}
    if kind.startswith("frame"):
        spec.update(bays_x=3, bays_y=2 if kind == "frame3d" else 0,
                    bay_width=6000.0, bay_depth=5000.0, storeys=3,
                    storey_height=3500.0, col_sec=1, beam_sec=1)
    elif kind.startswith("truss"):
        spec.update(panels=6, panel_width=4000.0, height=4000.0,
                    width=4000.0, sec=1)
    else:
        spec.update(spans=3, span_length=30000.0, width=12000.0, girders=5,
                    cross_spacing=5000.0, girder_sec=2, cross_sec=2)
    wizards.generate(p, spec)
    return p


for kind in ("frame2d", "frame3d", "truss2d", "truss3d", "bridge"):
    model = wizard_model(kind)
    res = opsgen.run_static(model, "DL")
    peak = max(abs(v) for vec in res.displacements.values() for v in vec)
    check(f"{kind} wizard solves under self weight",
          1 if math.isfinite(peak) and peak > 0.0 else 0, 1, 0)

print("== point springs and constraints ==")
from app.model import (BoundaryConstraint, SpringSupport, NodalLoad,  # noqa: E402
                       LoadCase)


def spring_model(kind: str):
    project = default_project()
    project.nodes = {1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 1000.0, 0.0, 0.0)}
    project.nodes[1].support = [True] * 6
    project.elements = {1: Element(1, "beam", [1, 2], 1, 1,
                                   [0.0, 0.0, 1.0])}
    project.cases = {"DL": LoadCase("DL", "Dead")}
    project.nodal_loads = [NodalLoad(1, 2, "DL", [0.0, 0.0, -10.0, 0, 0, 0])]
    if kind == "linear":
        spring = SpringSupport(1, 2, dof=3, kind="linear", k=10.0)
    elif kind == "curve":
        spring = SpringSupport(1, 2, dof=3, kind="multilinear", k=10.0,
                               curve=[[0.0, 0.0], [1.0, 5.0], [4.0, 15.0]])
    else:
        spring = SpringSupport(1, 2, dof=3, kind="py", pult=100.0,
                               y50=10.0, cd=0.5)
    project.springs = {1: spring}
    return project


plain = spring_model("linear")
plain.springs.clear()
r_plain = opsgen.run_static(plain, "DL")
u_plain = abs(r_plain.displacements[2][2])
for kind in ("linear", "curve", "py"):
    model = spring_model(kind)
    r = opsgen.run_static(model, "DL")
    u = abs(r.displacements[2][2])
    check(f"{kind} spring solves", 1 if math.isfinite(u) and u > 0 else 0, 1, 0)
    if kind == "linear":
        check("linear spring adds stiffness", u < u_plain, 1, 0)
        k_beam = 10.0 / u_plain
        check("linear spring stiffness", 10.0 / u - k_beam, 10.0, 1e-6)

for kind in ("rigid_beam", "equal_dof", "rigid_diaphragm"):
    model = spring_model("linear")
    model.nodes[3] = Node(3, 2000.0, 0.0, 0.0)
    model.elements[2] = Element(2, "beam", [2, 3], 1, 1, [0.0, 0.0, 1.0])
    model.nodal_loads = [NodalLoad(1, 3, "DL", [0.0, 0.0, -10.0, 0, 0, 0])]
    model.constraints = {1: BoundaryConstraint(
        1, kind, 2, [3], dofs=[1, 2, 3], perp=3)}
    r = opsgen.run_static(model, "DL")
    peak = max(abs(v) for vec in r.displacements.values() for v in vec)
    check(f"{kind} constraint solves", 1 if math.isfinite(peak) else 0, 1, 0)

round_trip = Project.from_dict(spring_model("curve").to_dict())
check("spring and constraint persistence",
      len(round_trip.springs) == 1
      and round_trip.springs[1].kind == "multilinear",
      1, 0)

print("== unilateral springs, trusses and cable ==")


def spring_direction(behavior: str, load: float):
    project = default_project()
    project.nodes = {1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 1000.0, 0.0, 0.0)}
    project.nodes[1].support = [True] * 6
    project.elements = {1: Element(1, "beam", [1, 2], 1, 1,
                                   [0.0, 0.0, 1.0])}
    project.cases = {"DL": LoadCase("DL", "Dead")}
    project.nodal_loads = [NodalLoad(1, 2, "DL", [0.0, 0.0, load, 0, 0, 0])]
    project.springs = {1: SpringSupport(1, 2, dof=3, kind="linear", k=10.0,
                                        behavior=behavior)}
    return opsgen.run_static(project, "DL").displacements[2][2]


tension_engaged = abs(spring_direction("tension", -10.0))
tension_released = abs(spring_direction("tension", 10.0))
compression_engaged = abs(spring_direction("compression", 10.0))
compression_released = abs(spring_direction("compression", -10.0))
check("tension-only spring engages tension only",
      tension_engaged < tension_released, 1, 0)
check("compression-only spring engages compression only",
      compression_engaged < compression_released, 1, 0)


def truss_behavior(behavior: str, load: float):
    project = default_project()
    project.nodes = {1: Node(1, 0.0, 0.0, 0.0), 2: Node(2, 1000.0, 0.0, 0.0)}
    project.nodes[1].support = [True] * 6
    project.nodes[2].support = [False, True, True, True, True, True]
    project.elements = {1: Element(1, "truss", [1, 2], 1, 1,
                                   behavior=behavior)}
    project.cases = {"DL": LoadCase("DL", "Dead")}
    project.nodal_loads = [NodalLoad(1, 2, "DL", [load, 0, 0, 0, 0, 0])]
    return opsgen.run_static(project, "DL").displacements[2][0]


check("tension-only truss solves in tension",
      1 if abs(truss_behavior("tension", 10.0)) > 0 else 0, 1, 0)
check("compression-only truss solves in compression",
      1 if abs(truss_behavior("compression", -10.0)) > 0 else 0, 1, 0)

cable_project = default_project()
cable_project.nodes = {1: Node(1, 0.0, 0.0, 0.0),
                       2: Node(2, 1000.0, 0.0, -100.0)}
cable_project.nodes[1].support = [True] * 6
cable_project.nodes[2].support = [False, True, False, True, True, True]
cable_project.elements = {1: Element(1, "cable", [1, 2], 1, 1)}
cable_project.cases = {"DL": LoadCase("DL", "Dead")}
cable_project.nodal_loads = [NodalLoad(1, 2, "DL", [0, 0, -10, 0, 0, 0])]
cable_res = opsgen.run_static(cable_project, "DL")
check("cable element solves",
      1 if math.isfinite(cable_res.displacements[2][2]) else 0, 1, 0)

print("== nonlinear frame members and devices ==")


def frame_member(kind: str):
    project = default_project()
    project.materials[1].E = 200.0
    project.sections[1].shape = "Rectangle"
    project.sections[1].b, project.sections[1].h = 300.0, 600.0
    project.sections[1].compute()
    project.nodes = {1: Node(1, 0.0, 0.0, 0.0, support=[True] * 6),
                     2: Node(2, 4000.0, 0.0, 0.0)}
    project.elements = {1: Element(1, kind, [1, 2], 1, 1, vecxz=[0, 0, 1])}
    project.cases = {"DL": LoadCase("DL", "Dead")}
    project.nodal_loads = [NodalLoad(1, 2, "DL", [0.0, 0.0, 10.0, 0, 0, 0])]
    result = opsgen.run_static(project, "DL")
    want = 10.0 * 4000.0 ** 3 / (3.0 * 200.0 * project.sections[1].Iy)
    return result.displacements[2][2], want


for member in ("force_beam", "disp_beam"):
    got, want = frame_member(member)
    check(f"{member} cantilever", got, want, 0.01)


def bearing_support(device: dict):
    project = default_project()
    project.nodes = {
        1: Node(1, 0.0, 0.0, 0.0, support=[True] * 6),
        2: Node(2, 0.0, 0.0, 0.0,
                support=[True, True, False, True, True, True]),
    }
    kind = "isolator" if device.get("type") == "isolator" else "bearing"
    project.elements = {1: Element(1, kind, [1, 2], 1, 1, device=device)}
    project.cases = {"DL": LoadCase("DL", "Dead")}
    project.nodal_loads = [NodalLoad(1, 2, "DL", [0, 0, -100.0, 0, 0, 0])]
    return opsgen.run_static(project, "DL").displacements[2][2]


bearing = {"type": "bearing", "k_init": 2.0, "qd": 100.0,
           "alpha1": 0.02, "alpha2": 0.05, "mu": 2.0, "eta": 1.0,
           "beta": 0.5, "gamma": 0.5, "kv": 1000.0, "kt": 1e6,
           "kry": 1e8, "krz": 1e8}
check("elastomeric bearing vertical stiffness", bearing_support(bearing),
      -0.1, 1e-6)

isolator = {"type": "isolator", "fy": 500.0, "alpha": 0.1, "gr": 4e-4,
            "kbulk": 2.0, "d1": 200.0, "d2": 400.0, "ts": 3.0,
            "tr": 8.0, "n": 10}
check("LeadRubberX isolator solves",
      1 if math.isfinite(bearing_support(isolator)) else 0, 1, 0)

damper_project = default_project()
damper_project.nodes = {
    1: Node(1, 0.0, 0.0, 0.0, support=[True] * 6),
    2: Node(2, 0.0, 0.0, 3000.0),
    3: Node(3, 0.0, 0.0, 0.0, support=[True] * 6),
}
damper_project.elements = {
    1: Element(1, "beam", [1, 2], 1, 1, vecxz=[1, 0, 0]),
    2: Element(2, "damper", [3, 2], 1, 1,
               device={"type": "damper_viscous", "k_el": 500.0,
                       "cd": 10.0, "alpha": 0.5, "gap": 0.0,
                       "nm": 1, "direction": 1}),
}
damper_project.cases = {"DL": LoadCase("DL", "Dead")}
damper_project.nodal_loads = [NodalLoad(1, 2, "DL", [10.0, 0, 0, 0, 0, 0])]
import openseespy.opensees as ops  # noqa: E402

opsgen.build(damper_project, "DL")
check("damper builds as twoNodeLink",
      1 if ops.eleType(2) == "TwoNodeLink" else 0, 1, 0)

export_project = default_project()
export_project.nodes = {
    1: Node(1, 0.0, 0.0, 0.0, support=[True] * 6),
    2: Node(2, 1000.0, 0.0, 0.0),
    3: Node(3, 1000.0, 0.0, 0.0),
}
export_project.elements = {
    1: Element(1, "force_beam", [1, 2], 1, 1, vecxz=[0, 0, 1]),
    2: Element(2, "isolator", [2, 3], 1, 1, device=isolator),
}
tcl_text = opsgen.export_tcl(export_project)
check("tcl export writes forceBeamColumn",
      1 if "element forceBeamColumn 1 1 2" in tcl_text else 0, 1, 0)
check("tcl export writes LeadRubberX",
      1 if "element LeadRubberX 2 2 3" in tcl_text else 0, 1, 0)

print("== script console model capture ==")
from app import scriptmodel, tcl  # noqa: E402

script = '''
import openseespy.opensees as ops
ops.wipe()
ops.model("basic", "-ndm", 2, "-ndf", 3)
ops.node(1, 0.0, 0.0)
ops.node(2, 0.0, 3.0)
ops.node(3, 4.0, 3.0)
ops.fix(1, 1, 1, 1)
ops.geomTransf("Linear", 1)
ops.element("elasticBeamColumn", 1, 1, 2, 0.25, 34e6, 0.0052, 1)
ops.element("elasticBeamColumn", 2, 2, 3, 0.25, 34e6, 0.0052, 1)
ops.timeSeries("Linear", 1)
ops.pattern("Plain", 1, 1)
ops.eleLoad("-ele", 2, "-type", "-beamUniform", -25.0)
ops.load(3, 0.0, -10.0, 0.0)
'''
recorder = scriptmodel.ScriptModelRecorder("m")
tcl.run_python(script, recorder=recorder)
captured = recorder.build()
check("script capture node count", len(captured.nodes), 3, 0)
check("script capture element count", len(captured.elements), 2, 0)
check("script capture converts metres to mm",
      captured.nodes[2].z, 3000.0, 1e-9)
section = captured.section_of(captured.elements[1])
check("script capture converts area", section.A, 250000.0, 1e-12)
check("script capture converts inertia", section.Iz, 5.2e9, 1e-6)
check("script capture converts E", captured.material_of(captured.elements[1]).E,
      34.0, 1e-12)
check("script capture fixes 2D out-of-plane modes",
      1 if all(captured.nodes[1].support) else 0, 1, 0)
check("script capture converts beam UDL",
      captured.elem_loads[0].value, -0.025, 1e-12)
check("script capture converts nodal load",
      captured.nodal_loads[0].values[2], -10.0, 1e-12)
captured_res = opsgen.run_static(captured, "Pattern 1")
peak = max(abs(v) for vec in captured_res.displacements.values() for v in vec)
check("script captured model solves",
      1 if math.isfinite(peak) and 0.0 < peak < 1000.0 else 0, 1, 0)

print("== section property calculator ==")
from app.section_property import compute_section_properties  # noqa: E402
from app.moment_curvature import (MomentCurvatureInput,  # noqa: E402
                                  run_moment_curvature)
from app.hinge_catalog import defaults as hinge_defaults  # noqa: E402

r = compute_section_properties("IShape", {"b": 200, "d": 400, "tf": 20, "tw": 10})
area = 2 * 200 * 20 + (400 - 40) * 10
ix = (200 * 400 ** 3 - (200 - 10) * 360 ** 3) / 12
iy = (2 * 20 * 200 ** 3 + 360 * 10 ** 3) / 12
check("section property I area", r.A, area, 1e-9)
check("section property I strong inertia", r.Ix, ix, 1e-9)
check("section property I weak inertia", r.Iy, iy, 1e-9)
check("section property I torsion", r.J,
      2 / 3 * 200 * 20 ** 3 + 1 / 3 * 360 * 10 ** 3, 1e-9)
check("section property I warping", r.Cw, iy * (400 - 20) ** 2 / 4, 1e-9)
circle = compute_section_properties("SolidCircle", {"d": 400})
check("section property circle area", circle.A, math.pi * 200 ** 2, 1e-9)
check("section property circle torsion", circle.J,
      math.pi * 200 ** 4 / 2, 1e-9)
check("section property circle warping", circle.Cw, 0.0, 1e-9)
source = Section(99, "SPP", "User")
source.A, source.Iy, source.Iz, source.J = r.A, r.Ix, r.Iy, r.J
outer, inner = r.outline()
source.outline_outer = [[x, y] for x, y in outer]
clone = Project.from_dict(Project.to_dict(default_project()))
source.name = "ported"
clone.sections[99] = source
clone2 = Project.from_dict(Project.to_dict(clone))
check("custom section outline persists",
      1 if len(clone2.sections[99].outline_outer) == len(outer) else 0, 1, 0)

print("== moment curvature backbone ==")
mc = run_moment_curvature(MomentCurvatureInput(
    section="rectangular", B=400, H=600, cover=40, nx=4, ny=4,
    db=25, dbt=10, s=100, fc=30, fy=420, P=500, L=4000))
check("moment curvature points", 1 if len(mc.strong.moments) > 20 else 0, 1, 0)
check("moment curvature peak positive",
      1 if mc.strong.peak_moment > 0 else 0, 1, 0)
check("moment curvature backbone points", len(mc.strong.backbone), 4, 0)
check("moment curvature yield before ultimate",
      1 if 0 < mc.strong.yield_rotation < mc.strong.ultimate_rotation else 0, 1, 0)
check("moment curvature ductility", 1 if mc.strong.ductility > 1 else 0, 1, 0)
check("moment curvature weak axis present", 1 if mc.weak is not None else 0, 1, 0)
circular_mc = run_moment_curvature(MomentCurvatureInput(
    section="circular", D=600, cover=40, n_bars=12, db=25, dbt=10, s=100,
    fc=30, fy=420, P=500, L=4000))
check("circular moment curvature has no weak axis", 1 if circular_mc.weak is None else 0, 1, 0)
check("circular moment curvature peak", 1 if circular_mc.strong.peak_moment > 0 else 0, 1, 0)

print("== moment backbone spring hinge ==")
from app.hinge_catalog import build_command  # noqa: E402
curve = [[0.005, 50000.0], [0.05, 60000.0], [0.10, 60000.0]]
command, args = build_command("MomentBackbone", 77,
                              hinge_defaults("MomentBackbone"), 1.0, curve)
check("moment backbone material command", 1 if command == "Hysteretic" else 0, 1, 0)
ops.wipe()
ops.model("BasicBuilder", "-ndm", 3, "-ndf", 6)
try:
    ops.uniaxialMaterial(command, 77, *args)
    check("moment backbone material creates", 1, 1)
except Exception as exc:
    check("moment backbone material creates", 0, 1)
    print("   ", exc)

ps = default_project()
ps.nodes[1] = Node(1, 0, 0, 0, support=[True] * 6)
ps.nodes[2] = Node(2, 0, 0, 1000)
ps.elements[1] = Element(1, "beam", [1, 2], 1, 2, vecxz=None)
ps.cases["LAT"] = LoadCase("LAT")
ps.nodal_loads.append(NodalLoad(1, 2, "LAT", [10.0, 0, 0, 0, 0, 0]))
spring = HingeDefinition(1, "MC hinge", "MomentBackbone",
                         "Moment-rotation (spring)", 0.1,
                         hinge_defaults("MomentBackbone"))
spring.curve = [list(p) for p in curve]
ps.hinge_defs[1] = spring
ps.hinge_assignments[1] = 1
cfg = {"gravity_case": "", "lateral_case": "LAT", "control_node": 2,
       "control_dof": 1, "target_displacement": 20.0, "steps": 5}
spring_push = opsgen.run_pushover(ps, cfg)
check("spring hinge pushover steps", len(spring_push.steps), 6, 0)
check("spring hinge pushover base shear",
      1 if spring_push.steps[-1].base_shear > 1.0 else 0, 1, 0)
check("spring hinge pushover rotation",
      1 if spring_push.max_hinge_rotation(spring_push.steps[-1]) > 0 else 0, 1, 0)
check("spring hinge yield moment", spring_push.hinge_yield.get(1, 0.0), 50000.0)
check("spring hinge model label",
      1 if "MomentBackbone" in spring_push.hinge_model else 0, 1, 0)
ps.time_history = TimeHistoryCase(source="sine", dt=0.01, n_steps=20,
                                  direction=1, damping_ratio=0.05,
                                  sine_amplitude=0.10, sine_period=1.0)
spring_th = opsgen.run_time_history(ps)
check("spring hinge time-history steps", spring_th.n_steps, 20, 0)
check("spring hinge time-history peak",
      1 if spring_th.peak_disp > 0 else 0, 1, 0)
check("spring hinge time-history forces",
      1 if spring_th.element_forces.get(1) else 0, 1, 0)
spring_json = spring.to_dict()
restored = HingeDefinition.from_dict(spring_json)
check("spring hinge curve persists",
      1 if restored.curve == spring.curve else 0, 1, 0)

print("== bridge live load ==")
from app.live_load import (Axle as LLAxle, Span as LLSpan,  # noqa: E402
                          LiveLoadConfig, analyze as live_analyze,
                          beam_chain_from_project, build_bcl_spacings,
                          compute_effective_increment, truck_positions)
ll_cfg = LiveLoadConfig(elems_per_span=8, truck_increment=0.2,
                        load_case="truck", dla_override=0.0,
                        dla_multiplier=1.0, truck_model="Custom")
ll = live_analyze([LLSpan(8.0)], [LLAxle(100.0, 0.0)], ll_cfg)
check("live load single-span moment", max(p.max for p in ll.moment), 200.0)
check("live load single-span shear", max(p.max for p in ll.shear), 100.0)
check("live load single-span shear minimum", min(p.min for p in ll.shear), -100.0)
check("live load single-span deflection",
      min(p.min for p in ll.deflection),
      -100000.0 * 8.0 ** 3 / (48.0 * 200e9 * 0.005), 1e-10)
check("live load support reaction", ll.reactions[0].max, 100.0)
check("live load support reaction minimum",
      1 if abs(ll.reactions[0].min) < 1e-9 else 0, 1, 0)
ll_cfg_lane = LiveLoadConfig(elems_per_span=8, truck_increment=0.2,
                             load_case="lane", dla_override=2.0,
                             dla_multiplier=1.0, lane_udl=9.0,
                             truck_model="Custom")
ll_lane = live_analyze([LLSpan(8.0)], [LLAxle(0.0, 0.0)], ll_cfg_lane)
check("live load lane UDL moment", max(p.max for p in ll_lane.moment), 72.0)
check("live load lane support reaction", ll_lane.reactions[0].max, 36.0)
check("live load lane deflection",
      min(p.min for p in ll_lane.deflection),
      -5.0 * 9000.0 * 8.0 ** 4 / (384.0 * 200e9 * 0.005), 2e-6)
check("live load lane has no DLA", ll_lane.dla_used, 0.0)

print("== traffic lanes and truck travel ==")
lane = Lane(1, "Lane A", (0.0, 0.0, 0.0), (10000.0, 0.0, 0.0), 2000.0)
check("lane length", lane.length, 10000.0)
check("lane lateral axis",
      1 if lane.lateral_axis == (0.0, 1.0, 0.0) else 0, 1)
check("lane shifted start",
      1 if lane.shifted_start == (0.0, 2000.0, 0.0) else 0, 1)
(left0, left1), (right0, right1) = lane.wheel_lines(1800.0)
check("lane left wheel line", 1 if left0 == (0.0, 2900.0, 0.0) else 0, 1)
check("lane right wheel line", 1 if right0 == (0.0, 1100.0, 0.0) else 0, 1)

lp = default_project()
lp.lanes[1] = lane
restored = Project.from_dict(lp.to_dict())
check("lane survives project round trip", len(restored.lanes), 1)
check("restored lane offset", restored.lanes[1].offset, 2000.0)

poly = Lane(2, "Curved lane",
            (0.0, 0.0, 0.0), (10000.0, 0.0, 0.0), 0.0,
            points=[(0.0, 0.0, 0.0), (5000.0, 1000.0, 0.0),
                    (10000.0, 0.0, 0.0)],
            element_tags=[1, 2])
lp.lanes[2] = poly
restored = Project.from_dict(lp.to_dict())
check("curved lane survives round trip",
      1 if len(restored.lanes[2].points) == 3 else 0, 1)
check("curved lane element tags survive round trip",
      1 if restored.lanes[2].element_tags == [1, 2] else 0, 1)

chain_project = Project()
chain_project.nodes[1] = Node(1, 0, 0, 0)
chain_project.nodes[2] = Node(2, 5000, 0, 0)
chain_project.nodes[3] = Node(3, 10000, 0, 0)
chain_project.elements[1] = Element(1, "beam", [1, 2], 1, 1)
chain_project.elements[2] = Element(2, "beam", [2, 3], 1, 1)
from app.live_load import chain_geometry  # noqa: E402
geometry = chain_geometry(chain_project, [1, 2])
check("element-chain geometry vertices",
      len(geometry["points"]) if geometry else 0, 3)
check("element-chain geometry elements",
      len(geometry["element_tags"]) if geometry else 0, 2)
check("element-chain geometry length",
      geometry["points"][-1][0] if geometry else 0.0, 10.0)

lane_spans = [LLSpan(20.0), LLSpan(25.0), LLSpan(20.0)]
lane_supports = [0.0, 20.0, 45.0, 65.0]
lane_axles = [LLAxle(50.0, 3.6), LLAxle(125.0, 1.2),
              LLAxle(125.0, 6.6), LLAxle(175.0, 6.6), LLAxle(150.0, 0.0)]
truck_len = sum(a.spacing for a in lane_axles[:-1])


def reference_positions(supports, axles, step):
    start = -sum(a.spacing for a in axles[:-1])
    end = supports[-1] - start
    count = max(2, int((end - start) / step + 1e-6) + 1)
    values = {min(end, start + i * step) for i in range(count)}
    values.add(end)
    from app.live_load import reverse_axles
    for direction in (list(axles), reverse_axles(axles)):
        for support in supports:
            distance = 0.0
            for i, axle in enumerate(direction):
                for sign in (1, -1):
                    lead = support + sign * distance
                    for offset in (-1e-6, 0.0, 1e-6):
                        if start <= lead + offset <= end:
                            values.add(lead + offset)
                if i < len(direction) - 1:
                    distance += axle.spacing
    return sorted(values)


default_positions = truck_positions(lane_supports, lane_axles, 0.25)
check("default travel matches reference algorithm",
      1 if default_positions == reference_positions(
          lane_supports, lane_axles, 0.25) else 0, 1)
check("default travel enters at minus truck length",
      default_positions[0], -truck_len)
check("default travel exits at span end plus truck length",
      default_positions[-1], lane_supports[-1] + truck_len)
lane_positions = truck_positions(lane_supports, lane_axles, 0.25, 10.0, 55.0)
check("lane start bounds the sweep", lane_positions[0], 10.0 - truck_len)
check("lane end bounds the sweep", lane_positions[-1], 55.0 + truck_len)

full_cfg = LiveLoadConfig(elems_per_span=8, truck_increment=0.5,
                          load_case="truck", dla_override=0.25,
                          truck_model="Custom")
full = live_analyze([LLSpan(35.0), LLSpan(35.0), LLSpan(35.0)],
                    [LLAxle(100.0, 8.0), LLAxle(80.0, 0.0)], full_cfg)
lane_cfg = LiveLoadConfig(elems_per_span=8, truck_increment=0.5,
                          load_case="truck", dla_override=0.25,
                          truck_model="Custom", lane_start=0.0, lane_end=105.0,
                          lane_offset=1.5, lane_name="Lane A")
lane_full = live_analyze([LLSpan(35.0), LLSpan(35.0), LLSpan(35.0)],
                         [LLAxle(100.0, 8.0), LLAxle(80.0, 0.0)], lane_cfg)
check("full-bridge lane preserves moment envelope",
      max(p.max for p in lane_full.moment), max(p.max for p in full.moment))
check("full-bridge lane preserves moment minimum",
      min(p.min for p in lane_full.moment), min(p.min for p in full.moment))
check("lane appears in result summary",
      1 if "Lane A" in lane_full.summary() else 0, 1)
short_cfg = LiveLoadConfig(elems_per_span=8, truck_increment=0.5,
                           load_case="truck", dla_override=0.25,
                           truck_model="Custom", lane_start=50.0,
                           lane_end=55.0)
short = live_analyze([LLSpan(35.0), LLSpan(35.0), LLSpan(35.0)],
                     [LLAxle(100.0, 8.0), LLAxle(80.0, 0.0)], short_cfg)
short_at_14 = min(short.moment, key=lambda p: abs(p.x - 14.0)).max
full_at_14 = min(full.moment, key=lambda p: abs(p.x - 14.0)).max
check("short lane restrains travel into span 1",
      1 if short_at_14 < full_at_14 else 0, 1)
ll_auto = live_analyze([LLSpan(8.0)], [LLAxle(100.0, 0.0)],
                       LiveLoadConfig(elems_per_span=8, truck_increment=0.2,
                                      load_case="truck", dla_override=None,
                                      dla_multiplier=1.0, truck_model="Custom"))
ll_off = live_analyze([LLSpan(8.0)], [LLAxle(100.0, 0.0)],
                      LiveLoadConfig(elems_per_span=8, truck_increment=0.2,
                                     load_case="truck", dla_override=None,
                                     dla_multiplier=0.0, truck_model="Custom"))
check("live load auto DLA 40 percent",
      max(p.max for p in ll_auto.moment),
      max(p.max for p in ll_off.moment) * 1.4)
check("BCL spacing configurations", len(build_bcl_spacings(1.0)), 13, 0)
check("BCL spacing range", build_bcl_spacings(1.0)[0], 6.6, 1e-9)
check("BCL spacing upper bound", build_bcl_spacings(1.0)[-1], 18.0, 1e-9)
step, _reason = compute_effective_increment(
    [LLSpan(1000.0), LLSpan(1000.0)],
    [LLAxle(50, 3.6), LLAxle(100, 0.0)], 0.001, 40)
check("live load sweep step floor", step >= 0.02, 1, 0)
check("live load sweep step cap", (2000.0 + 2 * 3.6) / step <= 6000, 1, 0)
chain_project = default_project()
chain_project.nodes = {
    1: Node(1, 0, 0, 0, support=[True] * 6),
    2: Node(2, 10000, 0, 0),
    3: Node(3, 20000, 0, 0, support=[True] * 6),
}
chain_project.elements = {
    1: Element(1, "beam", [1, 2], 1, 1, vecxz=None),
    2: Element(2, "beam", [2, 3], 1, 1, vecxz=None),
}
chain = beam_chain_from_project(chain_project, [1, 2])
check("live load beam chain spans", len(chain[0]) if chain else 0, 1, 0)
check("live load beam chain length", chain[0][0].length if chain else 0, 20.0, 0)
check("live load beam chain E", chain[1] if chain else 0, 200e9, 1e-9)
chain_project.nodes[2].support = [True] * 6
chain2 = beam_chain_from_project(chain_project, [1, 2])
check("live load beam chain intermediate support",
      1 if chain2 and len(chain2[0]) == 2 else 0, 1, 0)

print()
if FAILS:
    print("FAILURES:", FAILS)
    sys.exit(1)
print("ALL SOLVER TESTS PASSED")
