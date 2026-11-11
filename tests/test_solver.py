"""Solver-bridge verification against closed-form solutions."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.model import Project, Element, Node, NodalLoad, LoadCase, default_project
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
