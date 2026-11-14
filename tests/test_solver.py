"""Solver-bridge verification against closed-form solutions."""
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.model import (Project, Element, Node, NodalLoad, LoadCase, Section,
                       HingeDefinition, TimeHistoryCase, GroundMotionRecord,
                       ResponseSpectrumCase, default_project)
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

print()
if FAILS:
    print("FAILURES:", FAILS)
    sys.exit(1)
print("ALL SOLVER TESTS PASSED")
