"""Solver-bridge verification against closed-form solutions."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.model import (Project, Element, Node, NodalLoad, LoadCase, Section,
                       default_project)
from app import opsgen

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

print()
if FAILS:
    print("FAILURES:", FAILS)
    sys.exit(1)
print("ALL SOLVER TESTS PASSED")
